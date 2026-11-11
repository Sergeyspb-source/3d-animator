"""A library of ready materials for the pieces, as an alternative to the procedural look: ambientCG and Poly Haven, both
CC0 (anything may be done with them, a game included) and with open APIs. Searched from the armour editor; a material
chosen is downloaded once (1K JPG: its colour, its normal map in OpenGL's convention, its roughness, its metalness if
it has one) into export/materials/<source>_<id>/ with material.json, its real size (the side of the sample, cm) kept
for the tiling. The editor shows it on the piece, Blender bakes it (blender_armour_gen.node_mat: box-projected by that
size, the wear over it).
"""
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "sf3d-tool"}
ACG = "https://ambientcg.com/api/v2/full_json"
PH = "https://api.polyhaven.com"
_PH_LIST = None   # Poly Haven's textures, fetched once: {id: info}


def _get(url, timeout=60) -> bytes:
    import time
    for k in range(4):   # (a dropped connection now and then: again)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except OSError:
            if k == 3:
                raise
            time.sleep(1 + k)


def _json(url):
    return json.loads(_get(url).decode("utf-8"))


def search(source: str, q: str, limit: int = 24) -> list:
    """[{source, id, name, thumb, size_cm}] for the words q."""
    q = (q or "").strip()
    if source == "polyhaven":
        global _PH_LIST
        if _PH_LIST is None:
            _PH_LIST = _json(f"{PH}/assets?t=textures")
        words = [w for w in re.split(r"\W+", q.lower()) if w]
        def hit(k, a):
            text = " ".join([k, a.get("name", ""), *a.get("categories", []), *a.get("tags", [])]).lower()
            return all(w in text for w in words)
        found = [(k, a) for k, a in _PH_LIST.items() if hit(k, a)]
        found.sort(key=lambda x: -int(x[1].get("download_count") or 0))
        return [{"source": "polyhaven", "id": k, "name": a.get("name", k),
                 "thumb": f"https://cdn.polyhaven.com/asset_img/thumbs/{k}.png?width=256&height=256",
                 "size_cm": round(float((a.get("dimensions") or [1000])[0]) / 10) or 100} for k, a in found[:limit]]
    url = f"{ACG}?" + urllib.parse.urlencode({"type": "Material", "q": q, "limit": limit, "include": "imageData", "sort": "Popular"})
    out = []
    for a in _json(url).get("foundAssets", []):
        out.append({"source": "ambientcg", "id": a["assetId"], "name": a.get("displayName") or a["assetId"],
                    "thumb": (a.get("previewImage") or {}).get("256-PNG", ""), "size_cm": int(a.get("dimensionX") or 0) or 50})
    return out


def get(folder: Path, source: str, mid: str, size_cm: float = 0) -> dict:
    """The material's maps on disk (downloaded the first time): {source, id, name, color, normal, rough, metal?, size_cm}."""
    mid = re.sub(r"[^A-Za-z0-9_-]+", "_", mid)
    d = Path(folder) / f"{source}_{mid}"
    if source == "custom":   # (made here: nothing to download)
        return json.loads((d / "material.json").read_text(encoding="utf-8"))
    meta = d / "material.json"
    if meta.exists():
        return json.loads(meta.read_text(encoding="utf-8"))
    d.mkdir(parents=True, exist_ok=True)
    out = {"source": source, "id": mid, "name": mid, "size_cm": size_cm or 50}
    if source == "polyhaven":
        files, info = _json(f"{PH}/files/{mid}"), _json(f"{PH}/info/{mid}")
        out["name"] = info.get("name", mid)
        out["size_cm"] = size_cm or round(float((info.get("dimensions") or [1000])[0]) / 10) or 100
        for key, name in (("Diffuse", "color"), ("nor_gl", "normal"), ("Rough", "rough"), ("Metal", "metal")):
            url = (((files.get(key) or {}).get("1k") or {}).get("jpg") or {}).get("url")
            if url:
                (d / f"{name}.jpg").write_bytes(_get(url, 120))
                out[name] = (d / f"{name}.jpg").resolve().as_posix()
    else:
        z = zipfile.ZipFile(io.BytesIO(_get(f"https://ambientcg.com/get?file={mid}_1K-JPG.zip", 180)))
        for suffix, name in (("_Color.jpg", "color"), ("_NormalGL.jpg", "normal"), ("_Roughness.jpg", "rough"), ("_Metalness.jpg", "metal")):
            m = next((n for n in z.namelist() if n.endswith(suffix)), None)
            if m:
                (d / f"{name}.jpg").write_bytes(z.read(m))
                out[name] = (d / f"{name}.jpg").resolve().as_posix()
        out["name"] = re.sub(r"(\D)(\d)", r"\1 \2", mid, count=1)
    if "color" not in out:
        raise RuntimeError(f"{source} {mid}: no colour map")
    meta.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


# ---------------------------------------------------------------- your own materials (export/materials/custom_<name>)
def _maps_from(rgb, strength=2.5):
    """A normal map (OpenGL: green up) and a roughness from a colour photograph: its brightness taken as the height
    (blurred a little, so its grain, not its noise), the darker hollows rougher."""
    import numpy as np
    from PIL import Image, ImageFilter
    lum = np.asarray(Image.fromarray(rgb).convert("L").filter(ImageFilter.GaussianBlur(1.2)), np.float32) / 255
    h = (lum - lum.mean()) / (lum.std() + 1e-6) * .08
    dx = (np.roll(h, -1, 1) - np.roll(h, 1, 1)) * .5 * strength * 10   # (wrapping round: a seamless texture stays so)
    dy = (np.roll(h, -1, 0) - np.roll(h, 1, 0)) * .5 * strength * 10
    n = np.dstack([-dx, dy, np.ones_like(h)])
    n /= np.linalg.norm(n, axis=2, keepdims=True)
    nrm = ((n * .5 + .5) * 255).round().astype(np.uint8)
    lo, hi = np.percentile(lum, 2), np.percentile(lum, 98)
    t = np.clip((lum - lo) / max(hi - lo, 1e-3), 0, 1)
    rough = ((.88 - .4 * t) * 255).round().astype(np.uint8)
    return nrm, rough


def _seamless(a):
    """Tiles without a seam: the picture cross-faded with itself moved by half (its own seams then in the middle, where
    the original is whole); sin-shaped weights, so no line where either fades."""
    import numpy as np
    h, w = a.shape[:2]
    s = np.roll(np.roll(a, h // 2, 0), w // 2, 1).astype(np.float32)
    wy = np.sin(np.pi * (np.arange(h) + .5) / h) ** .7
    wx = np.sin(np.pi * (np.arange(w) + .5) / w) ** .7
    k = np.minimum(wy[:, None], wx[None, :])
    if a.ndim == 3:
        k = k[:, :, None]
    return (a.astype(np.float32) * k + s * (1 - k)).round().clip(0, 255).astype(np.uint8)


def custom(folder: Path, name: str, files: list, size_cm: float = 30, seamless: bool = True, metal: bool = False) -> dict:
    """Your own material from pictures (data URLs): the colour, and a normal map, a roughness, a metalness if given
    (told by the file's name: «normal»/«nrm», «rough», «metal»; a DirectX normal, «dx» in its name, turned to OpenGL's),
    else worked out from the colour. Saved as the library's are: export/materials/custom_<name>/material.json."""
    import base64
    import numpy as np
    from PIL import Image
    mid = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")[:40] or "material"
    d = Path(folder) / f"custom_{mid}"
    d.mkdir(parents=True, exist_ok=True)
    def load(f):
        im = Image.open(io.BytesIO(base64.b64decode(str(f["data"]).split(",", 1)[1])))
        im = im.convert("RGB")
        if max(im.size) > 2048:
            k = 2048 / max(im.size)
            im = im.resize((round(im.size[0] * k), round(im.size[1] * k)), Image.LANCZOS)
        return im
    kinds = {}
    for f in files:
        low = str(f.get("name", "")).lower()
        kind = ("normal" if re.search(r"normal|nrm|_n\b|_n\.", low) else "rough" if "rough" in low else "metal" if "metal" in low
                else None if re.search(r"height|disp|_ao\b|ambient|occlusion|bump", low) else "color")
        if kind and kind not in kinds:
            kinds[kind] = (f, low)
    if "color" not in kinds:
        raise ValueError("no colour picture")
    col = np.asarray(load(kinds["color"][0]))
    if seamless:
        col = _seamless(col)
    size = (col.shape[1], col.shape[0])
    out = {"source": "custom", "id": mid, "name": name, "size_cm": float(size_cm or 30)}
    Image.fromarray(col).save(d / "color.jpg", quality=92)
    nrm_auto, rough_auto = _maps_from(col)
    for kind in ("normal", "rough", "metal"):
        if kind in kinds:
            a = np.asarray(load(kinds[kind][0]).resize(size, Image.LANCZOS))
            if kind == "normal" and re.search(r"\bdx\b|_dx|directx", kinds[kind][1]):
                a = a.copy(); a[:, :, 1] = 255 - a[:, :, 1]
            if kind != "normal":
                a = a[:, :, 0]
            if seamless:
                a = _seamless(a)
        elif kind == "normal":
            a = nrm_auto
        elif kind == "rough":
            a = rough_auto
        elif metal:
            a = np.full(col.shape[:2], 255, np.uint8)
        else:
            continue
        Image.fromarray(a).save(d / f"{kind}.jpg", quality=92)
        out[kind] = (d / f"{kind}.jpg").resolve().as_posix()
    out["color"] = (d / "color.jpg").resolve().as_posix()
    (d / "material.json").write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out


def customs(folder: Path) -> list:
    """Your own materials made so far, as search results: [{source, id, name, thumb (a file), size_cm}]."""
    out = []
    for m in sorted(Path(folder).glob("custom_*/material.json")) if Path(folder).exists() else []:
        try:
            j = json.loads(m.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        out.append({"source": "custom", "id": j["id"], "name": j.get("name", j["id"]), "thumb": j["color"], "size_cm": j.get("size_cm", 30)})
    return out
