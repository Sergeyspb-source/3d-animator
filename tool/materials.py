"""Material recognition for albedo textures: roughness + metallic maps for glTF / Godot.

Pipeline (all on the UV atlas, so it works for any model):
  1. mask the texels that are really used (UV islands),
  2. k-means in Lab colour space -> K colour groups,
  3. zero-shot CLIP (laion ViT-B/32, already in the local HF cache) names each group from a few
     texture patches ("wood", "metal", "stone", ...), or a colour heuristic if CLIP is unavailable,
  4. each group gets a roughness / metallic value; boundaries are soft, with a little albedo-driven detail.

The result is a glTF metallicRoughness image: G = roughness, B = metallic (R = 1, unused occlusion).
"""
from __future__ import annotations

import numpy as np
from PIL import Image, ImageDraw

# key: (russian label, [CLIP prompts], roughness, metallic)
MATERIALS = {
    "wood":        ("Дерево", ["a photo of wood planks", "a close-up of wood grain", "a wooden beam",
                               "a hand-painted game texture of wooden planks", "stylized dark wood texture"], 0.75, 0.0),
    "metal":       ("Металл (сталь, железо)", ["a photo of steel metal", "a close-up of brushed iron", "a metal blade",
                                               "a hand-painted game texture of steel", "a shiny grey metal plate"], 0.40, 1.0),
    "dark_metal":  ("Тёмный/ржавый металл", ["a photo of rusty iron", "a close-up of corroded dark metal",
                                             "a hand-painted game texture of rusty metal"], 0.60, 0.85),
    "gold":        ("Золото, латунь, бронза", ["a photo of polished brass", "a photo of gold metal", "bronze metal"], 0.30, 1.0),
    "stone":       ("Камень", ["a photo of rough stone", "a stone wall", "a close-up of cobblestone",
                               "a hand-painted game texture of stone bricks"], 0.90, 0.0),
    "thatch":      ("Солома, тростник", ["a photo of thatch roof", "dry straw", "a close-up of reeds",
                                         "a hand-painted game texture of a thatched roof"], 0.95, 0.0),
    "plaster":     ("Штукатурка, глина", ["a photo of a plaster wall", "a close-up of clay", "a whitewashed wall",
                                          "a hand-painted game texture of beige plaster"], 0.90, 0.0),
    "fabric":      ("Ткань", ["a photo of woven cloth", "a close-up of fabric", "a canvas banner", "burlap",
                              "a hand-painted game texture of cloth"], 0.92, 0.0),
    "leather":     ("Кожа (материал)", ["a photo of leather", "a close-up of brown leather",
                                        "a hand-painted game texture of leather"], 0.60, 0.0),
    "skin":        ("Кожа (человек, существо)", ["a photo of human skin", "a close-up of skin"], 0.55, 0.0),
    "glass":       ("Стекло", ["a photo of clear glass", "a glass window"], 0.12, 0.0),
    "wax_plastic": ("Воск, пластик", ["a photo of smooth wax", "a close-up of plastic", "a candle"], 0.50, 0.0),
    "light":       ("Свет, огонь (светящееся)", ["a glowing lantern flame", "a lit window at night"], 0.50, 0.0),
    "other":       ("Прочее", ["a photo of an object"], 0.80, 0.0),
}
KEYS = list(MATERIALS)
# which materials make sense for each asset category (CLIP picks only among these)
CANDIDATES = {
    "building":  ["wood", "stone", "thatch", "plaster", "metal", "glass", "fabric"],
    "prop":      ["wood", "metal", "stone", "fabric", "leather", "plaster", "glass", "wax_plastic"],
    "item":      ["wood", "metal", "gold", "stone", "fabric", "leather", "glass", "wax_plastic"],
    "character": ["skin", "leather", "fabric", "metal", "gold", "wood", "stone"],
}
# Prior knowledge (added to CLIP's logits): big colour groups of a building are rarely metal, and so on.
# The user can always change the result in the material editor.
PRIOR = {
    "building": {"wood": 3.0, "thatch": 1.5, "stone": 1.5, "plaster": 1.0, "metal": -4.0, "glass": -4.0, "fabric": -3.0},
    "prop":     {"wood": 1.0, "plaster": -1.0, "glass": -3.0, "wax_plastic": -2.0},
    "item":     {"metal": 1.5, "wood": 1.0, "glass": -4.0, "wax_plastic": -4.0},
    "character": {"skin": 2.0, "gold": -2.0},
}
_clip = {}


def _uv_mask(uv, faces, W, H):
    img = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(img)
    for tri in uv[faces]:
        d.polygon([(float(u) * (W - 1), (1 - float(v)) * (H - 1)) for u, v in tri], fill=255)
    return np.asarray(img) > 0


def _kmeans(x, k, iters=14, seed=0):
    rng = np.random.default_rng(seed)
    centers = [x[rng.integers(len(x))]]
    for _ in range(k - 1):  # k-means++ init
        d2 = np.min(((x[:, None, :] - np.array(centers)[None]) ** 2).sum(-1), axis=1)
        centers.append(x[rng.choice(len(x), p=d2 / d2.sum())] if d2.sum() > 0 else x[rng.integers(len(x))])
    c = np.array(centers)
    for _ in range(iters):
        lab = ((x[:, None, :] - c[None]) ** 2).sum(-1).argmin(1)
        for j in range(k):
            if (lab == j).any():
                c[j] = x[lab == j].mean(0)
    return c


def _features(lab):
    # lightness matters more than hue for materials; chroma channels are compressed
    return np.stack([lab[..., 0] / 100.0 * 1.3, lab[..., 1] / 128.0, lab[..., 2] / 128.0], axis=-1)


def _load_clip():
    if "model" not in _clip:
        import open_clip
        import torch

        model, _, pre = open_clip.create_model_and_transforms("hf-hub:laion/CLIP-ViT-B-32-laion2B-s34B-b79K")
        tok = open_clip.get_tokenizer("hf-hub:laion/CLIP-ViT-B-32-laion2B-s34B-b79K")
        model.eval()
        rows = []
        with torch.no_grad():
            for k in KEYS:  # several phrasings per material, averaged
                t = model.encode_text(tok(MATERIALS[k][1]))
                t = t / t.norm(dim=-1, keepdim=True)
                t = t.mean(0)
                rows.append(t / t.norm())
        _clip.update(model=model, pre=pre, text=torch.stack(rows))
    return _clip


def _exposure(img: Image.Image) -> Image.Image:
    """Bring a patch to a mid brightness so dark albedo (dark wood) is readable to CLIP."""
    a = np.asarray(img).astype(np.float32) / 255.0
    lum = a.mean()
    gain = np.clip(0.45 / max(lum, 1e-3), 0.6, 4.0)
    a = np.clip(a * gain, 0, 1)
    lo, hi = np.percentile(a, 2), np.percentile(a, 98)  # stretch contrast a little
    if hi - lo > 0.02:
        a = np.clip((a - lo) / (hi - lo), 0, 1)
    return Image.fromarray((a * 255).astype(np.uint8))


def _heuristic(rgb_mean, lab_mean, chroma):
    """Fallback when CLIP is not available."""
    L, a, b = lab_mean
    hue_warm = a > 3 and b > 8
    if chroma < 8 and L > 55:
        return "metal"
    if chroma < 8:
        return "stone"
    if hue_warm and L < 45:
        return "wood"
    if hue_warm:
        return "thatch" if b > 25 else "plaster"
    return "other"


def suggest(patches_per_cluster, stats, use_clip=True, candidates=None, prior=None):
    """-> list of (material key, confidence) per cluster, restricted to `candidates` if given."""
    out = []
    allowed = [KEYS.index(c) for c in (candidates or KEYS)]
    bias = None
    if prior:
        import torch

        bias = torch.tensor([prior.get(KEYS[i], 0.0) for i in allowed], dtype=torch.float32)
    clip = None
    if use_clip:
        try:
            clip = _load_clip()
        except Exception:  # noqa: BLE001  (missing weights, no internet, ...)
            clip = None
    for patches, st in zip(patches_per_cluster, stats):
        if clip is not None and patches:
            import torch

            with torch.no_grad():
                x = torch.stack([clip["pre"](_exposure(p)) for p in patches])
                f = clip["model"].encode_image(x)
                f = f / f.norm(dim=-1, keepdim=True)
                sim = 100.0 * f @ clip["text"][allowed].T
                if bias is not None:
                    sim = sim + bias
                probs = sim.softmax(-1).mean(0)
            i = int(probs.argmax())
            out.append((KEYS[allowed[i]], float(probs[i])))
        else:
            out.append((_heuristic(st["rgb"], st["lab"], st["chroma"]), 0.0))
    return out


def analyze(tex: Image.Image, uv, faces, k=6, use_clip=True, seed=0, category=None):
    """Group the used texels of the albedo atlas into k colour clusters and name them."""
    from skimage import color

    rgb = np.asarray(tex.convert("RGB"))
    H, W = rgb.shape[:2]
    mask = _uv_mask(uv, faces, W, H)
    lab = color.rgb2lab(rgb / 255.0)
    feat = _features(lab)
    used = feat[mask]
    rng = np.random.default_rng(seed)
    sample = used[rng.choice(len(used), min(len(used), 60000), replace=False)]
    centers = _kmeans(sample, k, seed=seed)
    # label every texel (chunked to keep memory low)
    flat = feat.reshape(-1, 3)
    labels = np.empty(len(flat), dtype=np.int16)
    for i in range(0, len(flat), 500_000):
        labels[i:i + 500_000] = ((flat[i:i + 500_000, None, :] - centers[None]) ** 2).sum(-1).argmin(1)
    labels = labels.reshape(H, W)
    # drop empty clusters, order by area (largest first) so the numbering is stable and meaningful
    counts = np.array([(labels[mask] == j).sum() for j in range(k)])
    order = [j for j in np.argsort(-counts) if counts[j] > 0.002 * mask.sum()]
    remap = np.full(k, -1)
    for new, old in enumerate(order):
        remap[old] = new
    labels = np.where(remap[labels] >= 0, remap[labels], 0)
    centers = centers[order]
    n = len(order)

    stats, patches = [], []
    P = 48
    for j in range(n):
        sel = (labels == j) & mask
        m = lab[sel].mean(0)
        r = rgb[sel].mean(0)
        stats.append(dict(share=float(sel.sum() / mask.sum()), rgb=r, lab=m, chroma=float(np.hypot(m[1], m[2]))))
        # patches that are mostly this cluster
        ys, xs = np.where(sel)
        cand = rng.choice(len(ys), min(len(ys), 600), replace=False)
        got = []
        # big clean patches first; thin fragments of the atlas only give small / mixed ones
        for size, need in ((48, 0.75), (32, 0.65), (20, 0.55)):
            for ci in cand:
                y, x = ys[ci], xs[ci]
                y0, x0 = min(max(y - size // 2, 0), H - size), min(max(x - size // 2, 0), W - size)
                if sel[y0:y0 + size, x0:x0 + size].mean() >= need:
                    got.append(Image.fromarray(rgb[y0:y0 + size, x0:x0 + size]).resize((224, 224), Image.BICUBIC))
                if len(got) >= 6:
                    break
            if len(got) >= 3:
                break
        patches.append(got)
    sugg = suggest(patches, stats, use_clip, CANDIDATES.get(category), PRIOR.get(category))
    return dict(labels=labels, mask=mask, centers=centers, lab=lab, stats=stats, suggestions=sugg,
                size=(W, H), k=n)


def build_maps(analysis, assignment, softness=0.02):
    """glTF metallicRoughness image from per-cluster material keys (len == analysis['k'])."""
    labels, mask, lab = analysis["labels"], analysis["mask"], analysis["lab"]
    H, W = labels.shape
    rough_c = np.array([MATERIALS[a][2] for a in assignment], dtype=np.float32)
    metal_c = np.array([MATERIALS[a][3] for a in assignment], dtype=np.float32)
    # soft boundaries: blur the one-hot cluster masks a little so roughness/metal transition smoothly
    from scipy.ndimage import gaussian_filter

    sigma = max(1.0, softness * min(W, H) / 4)
    rough = np.zeros((H, W), np.float32)
    metal = np.zeros((H, W), np.float32)
    wsum = np.zeros((H, W), np.float32) + 1e-6
    for j in range(len(assignment)):
        w = gaussian_filter((labels == j).astype(np.float32), sigma)
        rough += w * rough_c[j]
        metal += w * metal_c[j]
        wsum += w
    rough /= wsum
    metal /= wsum
    # texels outside the UV islands copy their nearest used neighbour, so mip-mapping never
    # blends a bogus default value into the edges of an island
    from scipy.ndimage import distance_transform_edt

    iy, ix = distance_transform_edt(~mask, return_distances=False, return_indices=True)
    rough, metal = rough[iy, ix], metal[iy, ix]
    # a little detail from the albedo itself: darker texels (cracks, grime) read slightly rougher
    L = lab[..., 0]
    local = gaussian_filter(L, 6)
    rough = np.clip(rough + 0.0025 * (local - L), 0.04, 1.0)
    out = np.zeros((H, W, 3), np.uint8)
    out[..., 0] = 255
    out[..., 1] = (rough * 255 + 0.5).astype(np.uint8)
    out[..., 2] = (np.clip(metal, 0, 1) * 255 + 0.5).astype(np.uint8)
    return Image.fromarray(out)


def overlay(tex: Image.Image, analysis, size=512):
    """Atlas with each cluster tinted + numbered legend (for the GUI)."""
    pal = [(230, 25, 75), (60, 180, 75), (255, 225, 25), (0, 130, 200), (245, 130, 48), (145, 30, 180),
           (70, 240, 240), (240, 50, 230)]
    rgb = np.asarray(tex.convert("RGB")).astype(float)
    lab, mask = analysis["labels"], analysis["mask"]
    col = np.zeros_like(rgb)
    for j in range(analysis["k"]):
        col[lab == j] = pal[j % len(pal)]
    out = np.where(mask[..., None], 0.35 * rgb + 0.65 * col, 40.0)
    img = Image.fromarray(out.astype(np.uint8)).resize((size, size), Image.NEAREST)
    d = ImageDraw.Draw(img)
    for j in range(analysis["k"]):
        d.rectangle([6, 6 + j * 22, 22, 22 + j * 22], fill=pal[j % len(pal)])
        d.text((28, 8 + j * 22), f"{j + 1}", fill=(255, 255, 255))
    return img
