"""Model improvement - the «Improve» step of the Models chain: a draft made closer to its pictures before release.

What it does to a draft (work/web_drafts/export/<category>/<name>/<name>.glb; the generator's file is kept as
work_dir/improve/<category>/<name>/before.glb and every run starts from it again):
  A  texture from the pictures: each concept view (front / back / left / right, the left one mirrored when there is no
     right) fitted onto the model's silhouette and projected into the model's OWN unwrap - each texel from the picture
     that faces it best (weights^sharp, the front first) and sees it (z-buffer); what no picture shows keeps the
     model's texture, its colour moved by the projected-minus-own difference spread over the mesh. Hand fitting: pins
     per view (the picture's point -> where it belongs on the model), a smooth warp that lands every pin exactly.
  E  missing sides drawn by ChatGPT through Codex (refgen.codex_image): the model rendered from that side, repainted to
     the concept; the user accepts each picture, then it counts as a view for A.
  C  symmetry (characters): one half of the mesh and its texture mirrored onto the other (Blender's Symmetrize), the
     half whose front silhouette matches the concept better.
  D  relief (Hunyuan): the dense mesh before the 50K simplification (hy_pipeline's shape_raw.ply) baked into a
     tangent-space normal map of the draft's unwrap.
  then the vertex normals again over welded positions (sf3d_tool.welded_normals: Blender's export splits them).
Measured on the goblin / knight / shield (work/model_improve/REPORT.md): A 36-153 s, C 4 s, D 3-30 s on the CPU, no GPU;
E 1-5 min per side (the user's ChatGPT plan). Blender steps: blender_improve.py.

Views (glTF: +Y up, the model faces +Z, its own left is +X):
  front d=+Z (image right = +X), back d=-Z (right = -X), left d=+X (right = -Z), right d=-X (right = +Z)
"""
import io
import json
import shutil
import struct
import subprocess
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
import tex_pad  # noqa: E402

VIEWS = {"front": (0, 0, 1), "back": (0, 0, -1), "left": (1, 0, 0), "right": (-1, 0, 0)}
ORDER = ["front", "left", "right", "back"]
UP = np.array([0.0, 1.0, 0.0])
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)


# ------------------------------------------------------------------ geometry, rasteriser, fitting, blending
def view_axes(name_or_d):
    d = np.asarray(VIEWS[name_or_d] if isinstance(name_or_d, str) else name_or_d, float)
    d = d / np.linalg.norm(d)
    right = np.cross(-d, UP)
    right /= np.linalg.norm(right)
    up = np.cross(right, -d)
    return d, right, up


def read_glb(path):
    b = Path(path).read_bytes()
    j, bin0 = tex_pad.read_glb(b)
    return j, bin0


def load(path):
    """-> dict V (n,3) world, F (m,3), UV (n,2) glTF, tex (H,W,3) uint8 base colour, mr (H,W,3) or None, j, bin, img ids"""
    j, bin0 = read_glb(path)
    # node transforms (generators' GLBs: one mesh node, identity or a plain TRS)
    mats = {}

    def node_m(i, parent=np.eye(4)):
        n = j["nodes"][i]
        m = np.eye(4)
        if "matrix" in n:
            m = np.array(n["matrix"], float).reshape(4, 4).T
        else:
            t = np.array(n.get("translation", [0, 0, 0]), float)
            q = n.get("rotation", [0, 0, 0, 1])
            s = np.array(n.get("scale", [1, 1, 1]), float)
            x, y, z, w = q
            R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                          [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                          [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
            m[:3, :3] = R * s
            m[:3, 3] = t
        m = parent @ m
        if "mesh" in n:
            mats.setdefault(n["mesh"], m)
        for c in n.get("children", []):
            node_m(c, m)

    for r in j["scenes"][j.get("scene", 0)]["nodes"]:
        node_m(r)
    Vs, Fs, UVs, prim_mat = [], [], [], None
    off = 0
    for mi, mesh in enumerate(j["meshes"]):
        M = mats.get(mi, np.eye(4))
        for p in mesh["primitives"]:
            a = p["attributes"]
            if "TEXCOORD_0" not in a:
                continue
            v = tex_pad._accessor(j, bin0, a["POSITION"]).astype(np.float64)
            v = v @ M[:3, :3].T + M[:3, 3]
            uv = tex_pad._accessor(j, bin0, a["TEXCOORD_0"]).astype(np.float64)
            f = tex_pad._accessor(j, bin0, p["indices"]).reshape(-1, 3).astype(np.int64)
            Vs.append(v); UVs.append(uv); Fs.append(f + off); off += len(v)
            prim_mat = p.get("material", prim_mat)
    mat = j["materials"][prim_mat]
    pbr = mat.get("pbrMetallicRoughness", {})

    def img_of(tref):
        if not tref:
            return None, None
        tx = j["textures"][tref["index"]]
        src = tx.get("source", (tx.get("extensions") or {}).get("EXT_texture_webp", {}).get("source"))
        bv = j["bufferViews"][j["images"][src]["bufferView"]]
        data = bin0[bv.get("byteOffset", 0): bv.get("byteOffset", 0) + bv["byteLength"]]
        return src, np.asarray(Image.open(io.BytesIO(data)).convert("RGB"))

    bi, tex = img_of(pbr.get("baseColorTexture"))
    mi_, mr = img_of(pbr.get("metallicRoughnessTexture"))
    return {"V": np.concatenate(Vs), "F": np.concatenate(Fs), "UV": np.concatenate(UVs), "tex": tex, "mr": mr,
            "j": j, "bin": bin0, "base_img": bi, "mr_img": mi_, "path": str(path)}


def save_images(src_glb, out_glb, images):
    """images: {image index: PIL image} -> the GLB with those pictures swapped (PNG), all else byte for byte"""
    raw = Path(src_glb).read_bytes()
    j, bin_ = tex_pad.read_glb(raw)
    new = {}
    for i, im in images.items():
        buf = io.BytesIO()
        im.save(buf, "PNG", optimize=False, compress_level=6)
        new[j["images"][i]["bufferView"]] = buf.getvalue()
        j["images"][i]["mimeType"] = "image/png"
    out = bytearray()
    for vi, bv in enumerate(j["bufferViews"]):
        data = new.get(vi)
        if data is None:
            s = bv.get("byteOffset", 0)
            data = bin_[s: s + bv["byteLength"]]
        while len(out) % 4:
            out.append(0)
        bv["byteOffset"] = len(out); bv["byteLength"] = len(data); bv["buffer"] = 0
        out += data
    while len(out) % 4:
        out.append(0)
    j["buffers"] = [{"byteLength": len(out)}]
    jb = json.dumps(j, separators=(",", ":"), ensure_ascii=False).encode()
    jb += b" " * (-len(jb) % 4)
    body = struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(out), 0x004E4942) + bytes(out)
    Path(out_glb).write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def weld(V, tol=1e-6):
    """-> (rep (n,) index of each vertex's welded representative id 0..k-1, k)"""
    q = np.round(V / tol).astype(np.int64)
    _, inv = np.unique(q, axis=0, return_inverse=True)
    return inv.ravel(), int(inv.max()) + 1


def smooth_normals(V, F):
    """area-weighted normals over positions welded (UV seams split vertices; the normal must not)"""
    rep, k = weld(V, 1e-5)
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    acc = np.zeros((k, 3))
    for c in range(3):
        np.add.at(acc, rep[F[:, c]], fn)
    acc /= np.maximum(np.linalg.norm(acc, axis=1, keepdims=True), 1e-12)
    return acc[rep]


def raster(P2, F, W, H, z=None, chunk=4_000_000, grow=0.0):
    """Triangles in pixel coords (x right, y down; pixel i's centre at i + .5).
    grow > 0 (UV islands): also the pixels within `grow` px of a triangle (barycentrics clamped), drawn first so the
    exact ones win - an island's border texels get its own colour, not the padding's mix of the islands round it.
    -> fid (H,W) int32 (-1 empty), bary (H,W,3) float32, zbuf (H,W) (with z: the largest z wins, else -inf)."""
    if grow > 0 and z is None:
        f1, b1, _ = raster(P2, F, W, H, None, chunk, grow=-grow)
        f2, b2, _ = raster(P2, F, W, H, None, chunk, 0.0)
        hit = f2 >= 0
        f1[hit] = f2[hit]
        b1[hit] = b2[hit]
        return f1, b1, np.full((H, W), -np.inf)
    g = -grow if grow < 0 else 0.0   # (the inner call's way of asking for the grown pass)
    T = P2[F]
    lo = np.ceil(T.min(1) - 0.5 - g).astype(np.int64)
    hi = np.floor(T.max(1) - 0.5 + g).astype(np.int64)
    lo = np.maximum(lo, 0)
    hi[:, 0] = np.minimum(hi[:, 0], W - 1)
    hi[:, 1] = np.minimum(hi[:, 1], H - 1)
    size = hi - lo + 1
    ok = (size > 0).all(1)
    fid = np.full(H * W, -1, np.int32)
    bary = np.zeros((H * W, 3), np.float32)
    zb = np.full(H * W, -np.inf, np.float64)
    # buckets by the bounding box size (rounded up to powers of two)
    bw = np.where(ok, 1 << np.ceil(np.log2(np.maximum(size[:, 0], 1))).astype(np.int64), 0)
    bh = np.where(ok, 1 << np.ceil(np.log2(np.maximum(size[:, 1], 1))).astype(np.int64), 0)
    keys = bw * 100000 + bh
    for key in np.unique(keys[ok]):
        sel = np.nonzero(ok & (keys == key))[0]
        sw, sh = int(key // 100000), int(key % 100000)
        gx, gy = np.meshgrid(np.arange(sw), np.arange(sh))
        gx, gy = gx.ravel(), gy.ravel()
        step = max(1, chunk // (sw * sh))
        for s0 in range(0, len(sel), step):
            ids = sel[s0:s0 + step]
            px = lo[ids, 0][:, None] + gx[None]
            py = lo[ids, 1][:, None] + gy[None]
            inb = (px <= hi[ids, 0][:, None]) & (py <= hi[ids, 1][:, None])
            a, b, c = T[ids, 0], T[ids, 1], T[ids, 2]
            v0 = b - a; v1 = c - a
            d = v0[:, 0] * v1[:, 1] - v1[:, 0] * v0[:, 1]
            good = np.abs(d) > 1e-12
            d = np.where(good, d, 1.0)
            cx = px + 0.5 - a[:, 0:1]
            cy = py + 0.5 - a[:, 1:2]
            l1 = (cx * v1[:, 1:2] - v1[:, 0:1] * cy) / d[:, None]
            l2 = (v0[:, 0:1] * cy - cx * v0[:, 1:2]) / d[:, None]
            l0 = 1 - l1 - l2
            if g > 0:   # within g px of each edge: l_i * (the height over edge i) >= -g
                e0 = np.linalg.norm(c - b, axis=1); e1 = np.linalg.norm(c - a, axis=1); e2 = np.linalg.norm(b - a, axis=1)
                ad = np.abs(d)
                h0 = (ad / np.maximum(e0, 1e-9))[:, None]; h1 = (ad / np.maximum(e1, 1e-9))[:, None]; h2 = (ad / np.maximum(e2, 1e-9))[:, None]
                m = inb & good[:, None] & (l0 * h0 >= -g) & (l1 * h1 >= -g) & (l2 * h2 >= -g)
            else:
                e = -1e-4
                m = inb & good[:, None] & (l0 >= e) & (l1 >= e) & (l2 >= e)
            if not m.any():
                continue
            r, cidx = np.nonzero(m)
            pix = py[r, cidx] * W + px[r, cidx]
            bb = np.stack([l0[r, cidx], l1[r, cidx], l2[r, cidx]], 1)
            if g > 0:
                bb = np.clip(bb, 0, None)
                bb /= np.maximum(bb.sum(1, keepdims=True), 1e-9)
            tri = ids[r]
            if z is None:
                fid[pix] = tri
                bary[pix] = bb
            else:
                zz = (bb * z[F[tri]]).sum(1)
                # keep the largest z per pixel against what is there already
                order = np.lexsort((-zz, pix))
                pix, zz, tri, bb = pix[order], zz[order], tri[order], bb[order]
                first = np.ones(len(pix), bool)
                first[1:] = pix[1:] != pix[:-1]
                pix, zz, tri, bb = pix[first], zz[first], tri[first], bb[first]
                win = zz > zb[pix]
                pix, zz, tri, bb = pix[win], zz[win], tri[win], bb[win]
                zb[pix] = zz
                fid[pix] = tri
                bary[pix] = bb
    return fid.reshape(H, W), bary.reshape(H, W, 3), zb.reshape(H, W)


def texels(M, W=None, H=None):
    """the texture's texels on the surface: idx (K,) flat texel index, pos (K,3), nrm (K,3), fid, bary"""
    H = H or M["tex"].shape[0]
    W = W or M["tex"].shape[1]
    P2 = np.stack([M["UV"][:, 0] * W, M["UV"][:, 1] * H], 1)
    fid, bary, _ = raster(P2, M["F"], W, H, grow=1.5)
    idx = np.nonzero(fid.ravel() >= 0)[0]
    f = fid.ravel()[idx]
    b = bary.reshape(-1, 3)[idx].astype(np.float64)
    tri = M["F"][f]
    pos = (M["V"][tri] * b[..., None]).sum(1)
    N = M.get("N")
    if N is None:
        N = M["N"] = smooth_normals(M["V"], M["F"])
    nrm = (N[tri] * b[..., None]).sum(1)
    nrm /= np.maximum(np.linalg.norm(nrm, axis=1, keepdims=True), 1e-12)
    return {"idx": idx, "pos": pos, "nrm": nrm, "fid": f, "bary": b, "W": W, "H": H}


def project_pts(P, view, cam):
    """cam: (s, tx, ty) pixels per unit and the image position of the world origin -> (n,2) pixels, depth (n,)"""
    d, r, u = view_axes(view)
    s, tx, ty = cam
    return np.stack([P @ r * s + tx, -(P @ u) * s + ty], 1), P @ d


def silhouette(M, view, cam, W, H):
    P2, z = project_pts(M["V"], view, cam)
    fid, bary, zb = raster(P2, M["F"], W, H, z=z)
    return zb


def pic_alpha(path):
    im = Image.open(path)
    a = np.asarray(im.convert("RGBA")).astype(np.float32)
    if im.mode != "RGBA":   # no alpha: the background is near white/flat - cut by distance to the corner colour
        corner = np.median(np.concatenate([a[:8, :8, :3].reshape(-1, 3), a[:8, -8:, :3].reshape(-1, 3)]), 0)
        dist = np.linalg.norm(a[..., :3] - corner, axis=2)
        a[..., 3] = np.clip((dist - 12) * 20, 0, 255)
    return a[..., :3].astype(np.uint8), a[..., 3] / 255.0


def main_mask(alpha):
    """the picture's object: its biggest piece (stray specks and a shadow's crumbs dropped)"""
    from scipy.ndimage import label
    m = alpha > 0.5
    lab_, n = label(m)
    if n > 1:
        sizes = np.bincount(lab_.ravel())
        sizes[0] = 0
        keep = sizes >= 0.02 * sizes.max()
        m = keep[lab_]
    return m


def lowpoly(M, faces=6000):
    import fast_simplification
    v, f = fast_simplification.simplify(M["V"].astype(np.float32), M["F"].astype(np.int32),
                                        target_reduction=max(0.0, 1 - faces / len(M["F"])))
    return {"V": v.astype(np.float64), "F": f.astype(np.int64)}


def fit_view(M, view, alpha, iters=160, scale_hint=None):
    """the model's silhouette fitted onto the picture's alpha: scale and shift (IoU, Nelder-Mead at a quarter size on a
    6K-face copy). Starts from the bounding boxes' match and, given scale_hint (the front view's scale: the views of one
    set are drawn at one scale), from that scale too; the better IoU wins."""
    from scipy.optimize import minimize
    H, W = alpha.shape
    mask = main_mask(alpha)
    ys, xs = np.nonzero(mask)
    d, r, u = view_axes(view)
    LP = M.get("_lp") or M.setdefault("_lp", lowpoly(M))
    pr, pu = M["V"] @ r, M["V"] @ u
    k = 4
    small = mask[::k, ::k]
    Hs, Ws = small.shape
    starts = []
    s_bb = (ys.max() - ys.min() + 1) / (pu.max() - pu.min())
    for s0 in [s_bb] + ([scale_hint] if scale_hint else []):
        tx0 = (xs.min() + xs.max() + 1) / 2 - s0 * (pr.min() + pr.max()) / 2
        ty0 = ys.max() + 1 + s0 * pu.min()   # feet on the picture's bottom
        starts.append((s0, tx0, ty0))
        starts.append((s0, tx0, ys.min() + s0 * pu.max()))   # head on its top
    best = None
    for s0, tx0, ty0 in starts:
        def iou(x):
            s, tx, ty = s0 * np.exp(x[0]), tx0 + x[1], ty0 + x[2]
            zb = silhouette(LP, view, (s / k, tx / k, ty / k), Ws, Hs)
            sil = np.isfinite(zb)
            return -(sil & small).sum() / max((sil | small).sum(), 1)
        res = minimize(iou, [0, 0, 0], method="Nelder-Mead",
                       options={"xatol": 0.2, "fatol": 1e-4, "maxiter": iters,
                                "initial_simplex": [[0, 0, 0], [0.03, 0, 0], [0, 12, 0], [0, 0, 12]]})
        if best is None or res.fun < best[0]:
            best = (res.fun, (s0 * np.exp(res.x[0]), tx0 + res.x[1], ty0 + res.x[2]))
    cam = best[1]
    zb = silhouette(M, view, cam, W, H)
    sil = np.isfinite(zb)
    return cam, float((sil & mask).sum() / max((sil | mask).sum(), 1)), zb


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


def sample(img, xy):
    """bilinear (n,2) pixel coords (pixel centres at i + .5) of (H,W,C) float"""
    from scipy.ndimage import map_coordinates
    x = xy[:, 0] - 0.5
    y = xy[:, 1] - 0.5
    if img.ndim == 2:
        return map_coordinates(img, [y, x], order=1, mode="nearest")
    return np.stack([map_coordinates(img[..., c], [y, x], order=1, mode="nearest") for c in range(img.shape[2])], 1)


def view_weights(Tx, view, cam, zb, alpha, c0=0.1, c1=0.55, edge_px=4.0, eps=0.004):
    """per texel: how much this picture should paint it (facing x visible x inside the picture's cut, off its edge)"""
    from scipy.ndimage import distance_transform_edt
    H, W = zb.shape
    d, r, u = view_axes(view)
    xy, dep = project_pts(Tx["pos"], view, cam)
    c = Tx["nrm"] @ d
    face = smoothstep(c0, c1, c)
    ix = np.clip(np.floor(xy[:, 0]).astype(int), 0, W - 1)
    iy = np.clip(np.floor(xy[:, 1]).astype(int), 0, H - 1)
    from scipy.ndimage import minimum_filter
    zmin = minimum_filter(np.where(np.isfinite(zb), zb, -1e9), size=3)
    zref = np.where(np.isfinite(zb), zb, -1e9)[iy, ix]
    px = 1.0 / cam[0]
    slope = 1.5 * px * np.sqrt(np.clip(1 - c * c, 0, 1)) / np.maximum(c, 0.1)
    vis = (dep >= np.minimum(zref, zmin[iy, ix]) - eps - slope) & (zref > -1e8)
    inside = distance_transform_edt(alpha > 0.5)
    edge = np.clip((sample(inside.astype(np.float32), xy) - 1.0) / edge_px, 0, 1)
    # off the occluding contours (a chin over the neck, an arm over the side): depth jumps in the z-buffer, the
    # weight grows over occl_px pixels away from them on both sides - no hard line where the view stops seeing
    zf = np.where(np.isfinite(zb), zb, -1e9)
    gx = np.abs(np.diff(zf, axis=1, append=zf[:, -1:])); gy = np.abs(np.diff(zf, axis=0, append=zf[-1:]))
    jump = (np.maximum(gx, gy) > 0.02) & np.isfinite(zb)
    occl_px = max(edge_px * 2, 6.0)
    dj = distance_transform_edt(~jump).astype(np.float32)
    soft = np.clip(sample(dj, xy) / occl_px, 0, 1)
    w = face * vis * edge * soft
    return w, xy


def lab(rgb_u8):
    from skimage import color
    return color.rgb2lab(np.asarray(rgb_u8, np.float64).reshape(-1, 1, 3) / 255.0).reshape(-1, 3)


def rgb(lab_):
    from skimage import color
    return (np.clip(color.lab2rgb(lab_.reshape(-1, 1, 3)), 0, 1).reshape(-1, 3) * 255 + 0.5).astype(np.uint8)


def vertex_field(M, Tx, val, w, thresh=0.2):
    """per-texel values gathered onto welded vertices (bary x w) -> (vals (k,C), known (k,), tri (K,3) welded ids)"""
    rep, k = weld(M["V"], 1e-5)
    tri = rep[M["F"]][Tx["fid"]]
    C = val.shape[1]
    acc = np.zeros((k, C)); ws = np.zeros(k)
    for c in range(3):
        wt = Tx["bary"][:, c] * w
        np.add.at(acc, tri[:, c], val * wt[:, None])
        np.add.at(ws, tri[:, c], wt)
    known = ws > thresh
    return np.where(known[:, None], acc / np.maximum(ws, 1e-9)[:, None], 0), known, tri


def laplace_extend(M, vals, known):
    """unknown welded vertices solved from their neighbours (graph Laplace, the known held)"""
    import scipy.sparse as sp
    from scipy.sparse.linalg import spsolve
    rep, k = weld(M["V"], 1e-5)
    Fw = rep[M["F"]]
    e = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    A = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(k, k)).tocsr()
    A.data[:] = 1
    deg = np.asarray(A.sum(1)).ravel()
    unk = np.nonzero(~known)[0]
    out = vals.copy()
    if len(unk) and known.any():
        kn = np.nonzero(known)[0]
        L = (sp.diags(deg) - A).tocsr()
        Luu = L[unk][:, unk].tocsc() + sp.eye(len(unk)) * 1e-9
        Luk = L[unk][:, kn]
        for c in range(vals.shape[1]):
            out[unk, c] = spsolve(Luu, -Luk @ vals[kn, c])
    return out


def grow_fill(img, mask, steps=8):
    """the islands grown outward `steps` pixels with their own border colours (each new pixel the mean of its covered
    8 neighbours), then pull-push for the rest: a mip level's average at a seam reads the islands' own colours"""
    from scipy.ndimage import convolve
    a = img.astype(np.float32).copy()
    m = mask.copy()
    k = np.ones((3, 3), np.float32)
    for _ in range(steps):
        wsum = convolve(m.astype(np.float32), k, mode="constant")
        new = (~m) & (wsum > 0)
        if not new.any():
            break
        for c in range(a.shape[2]):
            s = convolve(a[..., c] * m, k, mode="constant")
            a[..., c] = np.where(new, s / np.maximum(wsum, 1e-9), a[..., c])
        m = m | new
    return tex_pad.pad_fill(a.clip(0, 255).astype(img.dtype), m)


def graph_dist(M, sources):
    """distance over the mesh's edges (welded) from the source welded vertices -> (k,)"""
    import scipy.sparse as sp
    from scipy.sparse.csgraph import dijkstra
    rep, k = weld(M["V"], 1e-5)
    Fw = rep[M["F"]]
    P = np.zeros((k, 3)); P[rep] = M["V"]
    e = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    ln = np.linalg.norm(P[e[:, 0]] - P[e[:, 1]], axis=1) + 1e-9
    G = sp.coo_matrix((ln, (e[:, 0], e[:, 1])), shape=(k, k)).tocsr()
    src = np.nonzero(sources)[0]
    if not len(src):
        return np.full(k, np.inf)
    G2 = sp.vstack([sp.hstack([G, sp.csr_matrix((k, 1))]), sp.csr_matrix((np.full(len(src), 1e-9), (np.zeros(len(src), int), src)), shape=(1, k + 1))]).tocsr()
    d = dijkstra(G2, directed=False, indices=k)
    return d[:k]


def fill_hybrid(M, Tx, proj, own, a, detail=0.7, near=0.02, far=0.08):
    """unseen texels: near the seen part (a chin's underside, an armpit) the seen colours spread over them (Laplace)
    + the own fine detail; far from it (a back no picture shows) the own texture kept, its colour moved by the
    seen-minus-own difference spread the same way. Distance over the mesh, in model units (height ~1)."""
    w = (a > 0.5).astype(float) * a
    pv, known, tri = vertex_field(M, Tx, proj, w)
    dv, _, _ = vertex_field(M, Tx, proj - own, w)
    ov, _, _ = vertex_field(M, Tx, own, np.ones(len(own)), thresh=1e-6)
    pv = laplace_extend(M, pv, known)
    dv = laplace_extend(M, dv, known)
    dist = graph_dist(M, known)
    t = smoothstep(near, far, dist)
    b = Tx["bary"][..., None]
    lap = (pv[tri] * b).sum(1) + detail * (own - (ov[tri] * b).sum(1))
    off = own + (dv[tri] * b).sum(1)
    tt = (t[tri] * Tx["bary"]).sum(1)[:, None]
    return lap * (1 - tt) + off * tt


def pin_field(pins, sigma_min=12.0, sigma_max=160.0):
    """Hand fitting: pins [(sx, sy, dx, dy), ...] in the picture's pixels - the picture's point (sx, sy) is to land on
    the model at (dx, dy). -> D(q): for model points q (n,2) the picture point to read = q + D(q). Gaussian radial
    basis on the destinations (each pin's reach ~ 0.7 x the distance to its nearest neighbour, clamped), solved so every
    pin lands exactly; far from all pins nothing moves. A pin with s == d holds its place."""
    P = np.asarray(pins, float).reshape(-1, 4)
    if not len(P):
        return lambda q: np.zeros_like(q)
    dst, disp = P[:, 2:4], P[:, 0:2] - P[:, 2:4]
    n = len(P)
    if n > 1:
        dd = np.linalg.norm(dst[:, None] - dst[None], axis=2) + np.eye(n) * 1e9
        sig = np.clip(0.7 * dd.min(1), sigma_min, sigma_max)
    else:
        sig = np.array([sigma_max * 0.6])
    sig = np.maximum(sig, np.maximum(np.linalg.norm(disp, axis=1) * 1.2, sigma_min))   # (a long move needs room)
    Phi = np.exp(-(np.linalg.norm(dst[:, None] - dst[None], axis=2) ** 2) / (2 * sig[None] ** 2))
    alpha = np.linalg.solve(Phi + np.eye(n) * 1e-6, disp)

    def D(q):
        q = np.asarray(q, float)
        out = np.zeros_like(q)
        for k in range(n):
            out += alpha[k] * np.exp(-((q - dst[k]) ** 2).sum(1) / (2 * sig[k] ** 2))[:, None]
        return out
    return D


def delight(rgb, alpha, strength=0.6, sigma_frac=0.02):
    """the picture's painted light taken out: its lightness minus (strength x) its own blurred lightness around the mean
    (blur inside the object only, sigma = sigma_frac x the picture's height); colour (a, b) kept"""
    from scipy.ndimage import gaussian_filter
    from skimage import color
    if strength <= 0:
        return rgb
    lab_ = color.rgb2lab(rgb.astype(np.float64) / 255.0)
    m = (alpha > 0.5).astype(np.float64)
    s = sigma_frac * rgb.shape[0]
    num = gaussian_filter(lab_[..., 0] * m, s); den = gaussian_filter(m, s)
    blur = num / np.maximum(den, 1e-6)
    mean = (lab_[..., 0] * m).sum() / max(m.sum(), 1)
    lab_[..., 0] = np.clip(lab_[..., 0] - strength * (blur - mean) * m, 0, 100)
    return (np.clip(color.lab2rgb(lab_), 0, 1) * 255 + 0.5).astype(np.uint8)


def smooth_on_mesh(M, Tx, val, iters=40):
    """per-texel values averaged onto welded vertices, smoothed over the mesh (iters x neighbour mean), back to texels:
    a blur that never crosses into other UV islands"""
    import scipy.sparse as sp
    vv, known, tri = vertex_field(M, Tx, val, np.ones(len(val)), thresh=1e-6)
    rep, k = weld(M["V"], 1e-5)
    Fw = rep[M["F"]]
    e = np.concatenate([Fw[:, [0, 1]], Fw[:, [1, 2]], Fw[:, [2, 0]]])
    e = np.concatenate([e, e[:, ::-1]])
    A = sp.coo_matrix((np.ones(len(e)), (e[:, 0], e[:, 1])), shape=(k, k)).tocsr()
    A.data[:] = 1
    P = sp.diags(1 / np.maximum(np.asarray(A.sum(1)).ravel(), 1)) @ A
    for _ in range(iters):
        vv = 0.5 * vv + 0.5 * (P @ vv)
    return (vv[tri] * Tx["bary"][..., None]).sum(1)


# ------------------------------------------------------------------ G: vertex normals after a Blender export
def set_normals(src_glb, out_glb):
    """the GLB with its NORMAL data replaced in place by normals averaged over welded positions (sf3d_tool.welded_normals;
    Blender's glTF export splits them along the UV seams again - blotchy faces). Returns the vertices written."""
    import sf3d_tool as T
    raw = Path(src_glb).read_bytes()
    j, bin_ = tex_pad.read_glb(raw)
    b2 = bytearray(bin_)
    done = 0
    for mesh in j.get("meshes", []):
        for p in mesh["primitives"]:
            a = p["attributes"]
            if "NORMAL" not in a or "indices" not in p or p.get("mode", 4) != 4:
                continue
            acc = j["accessors"][a["NORMAL"]]
            if acc.get("componentType") != 5126:
                continue
            v = tex_pad._accessor(j, bin_, a["POSITION"]).astype(np.float64)
            f = tex_pad._accessor(j, bin_, p["indices"]).reshape(-1, 3).astype(np.int64)
            old = tex_pad._accessor(j, bin_, a["NORMAL"]).astype(np.float64)
            N = T.welded_normals(v, f, fallback=old).astype(np.float32)
            bv = j["bufferViews"][acc["bufferView"]]
            start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
            stride = bv.get("byteStride", 0) or 12
            if stride == 12:
                b2[start:start + 12 * len(N)] = N.tobytes()
            else:
                for k in range(len(N)):
                    b2[start + k * stride:start + k * stride + 12] = N[k].tobytes()
            done += len(N)
    jb = json.dumps(j, separators=(",", ":"), ensure_ascii=False).encode()
    jb += b" " * (-len(jb) % 4)
    b2 = bytes(b2) + b"\0" * (-len(b2) % 4)
    body = struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(b2), 0x004E4942) + b2
    Path(out_glb).write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
    return done


# ------------------------------------------------------------------ A: the pictures projected
def project(glb, out, pics, mirror=False, res=None, c0=0.1, c1=0.55, sharp=4.0, prio=None, delight_k=0.0, pins=None,
            cams=None, mr_smooth=True, detail=0.7, log=None):
    """pics: {view: path or ("flip", path)}; cams: {view: (s, tx, ty)} already fitted (else fitted here);
    pins: {view: [(sx, sy, dx, dy), ...]}. -> info {views: {view: {iou, cam, ...}}, seconds, coverage}"""
    say = log or (lambda *_: None)
    prio = {"front": 1.0, "back": 0.85, "left": 0.6, "right": 0.6, **(prio or {})}
    T = {}
    t0 = time.time()
    M = load(glb)
    if M["tex"] is None:
        raise RuntimeError("the model has no colour texture to paint")
    H0, W0 = M["tex"].shape[:2]
    R = res or max(W0, 2048)
    Tx = texels(M, R, R)
    T["texels"] = round(time.time() - t0, 1)
    pics = dict(pics)
    if mirror and "left" in pics and "right" not in pics:
        pics["right"] = ("flip", pics["left"])
    if mirror and "right" in pics and "left" not in pics:
        pics["left"] = ("flip", pics["right"])
    views = [v for v in ORDER if v in pics]
    acc_c = np.zeros((len(Tx["idx"]), 3)); acc_w = np.zeros(len(Tx["idx"]))
    per_view = []
    info = {"views": {}, "sharp": sharp, "delight": delight_k}
    hint = None
    for v in views:
        t = time.time()
        src = pics[v]
        flip = isinstance(src, tuple)
        rgb_, a = pic_alpha(src[1] if flip else src)
        if flip:
            rgb_, a = rgb_[:, ::-1].copy(), a[:, ::-1].copy()
        if delight_k > 0:
            rgb_ = delight(rgb_, a, delight_k)
        if cams and cams.get(v):
            cam = tuple(cams[v]); iou = None
            zb = silhouette(M, v, cam, a.shape[1], a.shape[0])
        else:
            say(f"fit {v}")
            cam, iou, zb = fit_view(M, v, a, scale_hint=hint)
        hint = hint or cam[0]
        w, xy = view_weights(Tx, v, cam, zb, a, c0=c0, c1=c1)
        vp = (pins or {}).get(v)
        if flip and not vp and (pins or {}).get("left" if v == "right" else "right"):
            Wp = a.shape[1]   # the mirrored side: the other side's pins mirrored with its picture
            vp = [(Wp - sx, sy, Wp - dx, dy) for sx, sy, dx, dy in pins["left" if v == "right" else "right"]]
        if vp:
            xy = xy + pin_field(vp)(xy)
        pre = sample(rgb_.astype(np.float32) * a[..., None], xy)   # (premultiplied: the background never mixes in)
        col = lab((pre / np.maximum(sample(a.astype(np.float32), xy), 1e-3)[:, None]).clip(0, 255))
        shift = [0, 0, 0]
        if acc_w.max() > 0:   # pulled to the colours already laid where they overlap
            ov = (w > 0.3) & (acc_w > 0.3)
            if ov.sum() > 200:
                shift = (acc_c[ov] / acc_w[ov, None] - col[ov]).mean(0)
                col = col + shift
        acc_c += col * w[:, None]; acc_w += w
        per_view.append((v, w, col))
        info["views"][v] = {"iou": None if iou is None else round(iou, 3), "cam": [round(float(x), 3) for x in cam],
                            "flip": flip, "pins": len(vp or []), "seconds": round(time.time() - t, 1)}
    if not per_view:
        raise RuntimeError("no pictures")
    t = time.time()
    # each texel mostly from its best view: an even mix of two pictures whose features sit a little apart doubles them
    ws = np.stack([(prio.get(v, 1.0) * w) ** sharp for v, w, _ in per_view])
    proj = np.einsum("vn,vnc->nc", ws, np.stack([c for _, _, c in per_view])) / np.maximum(ws.sum(0), 1e-12)[:, None]
    a_ = np.clip(acc_w, 0, 1)
    uvpix = np.stack([(Tx["idx"] % R + 0.5) * W0 / R, (Tx["idx"] // R + 0.5) * H0 / R], 1)
    own = lab(sample(M["tex"].astype(np.float32), uvpix).clip(0, 255))
    own2 = fill_hybrid(M, Tx, proj, own, a_, detail=detail)
    final = proj * a_[:, None] + own2 * (1 - a_[:, None])
    img = np.zeros((R * R, 3), np.uint8)
    img[Tx["idx"]] = rgb(final)
    mask = np.zeros(R * R, bool); mask[Tx["idx"]] = True
    images = {M["base_img"]: Image.fromarray(grow_fill(img.reshape(R, R, 3), mask.reshape(R, R)))}
    if M["mr"] is not None and mr_smooth:
        # the generator's metal/roughness map follows ITS painted features (TRELLIS: glossy wet eyes where it drew
        # them): where the pictures paint, those local spots are smoothed away over the mesh, material zones kept
        Hm, Wm = M["mr"].shape[:2]
        mrv = sample(M["mr"].astype(np.float32), np.stack([(Tx["idx"] % R + 0.5) * Wm / R, (Tx["idx"] // R + 0.5) * Hm / R], 1))
        mr2 = mrv * (1 - a_[:, None]) + smooth_on_mesh(M, Tx, mrv, iters=60) * a_[:, None]
        mimg = np.zeros((R * R, 3), np.uint8); mimg[Tx["idx"]] = mr2.clip(0, 255).astype(np.uint8)
        images[M["mr_img"]] = Image.fromarray(grow_fill(mimg.reshape(R, R, 3), mask.reshape(R, R)))
    T["blend"] = round(time.time() - t, 1)
    save_images(glb, out, images)
    T["total"] = round(time.time() - t0, 1)
    info["seconds"] = T
    info["coverage"] = round(float((a_ > 0.5).mean()), 3)
    return info


# ------------------------------------------------------------------ the pins editor's picture of the model
def shade_render(M, view, cam, W, H):
    """the model from that view as the fitted camera sees it, grey and lit from the front-top (RGBA, clear background):
    what the pins are laid on"""
    P2, z = project_pts(M["V"], view, cam)
    fid, bary, zb = raster(P2, M["F"], W, H, z=z)
    ok = fid >= 0
    N = M.get("N")
    if N is None:
        N = M["N"] = smooth_normals(M["V"], M["F"])
    n = (N[M["F"][fid[ok]]] * bary[ok][..., None]).sum(1)
    n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    d, r, u = view_axes(view)
    L = d + 0.7 * u + 0.35 * r
    L /= np.linalg.norm(L)
    sh = 0.22 + 0.78 * np.clip(n @ L, 0, 1) ** 0.9
    out = np.zeros((H, W, 4), np.uint8)
    g = (sh * 225).clip(0, 255).astype(np.uint8)
    out[ok, 0] = g; out[ok, 1] = g; out[ok, 2] = (g * 1.03).clip(0, 255).astype(np.uint8); out[ok, 3] = 255
    return Image.fromarray(out, "RGBA")


# ------------------------------------------------------------------ C: which half to keep
def pick_half(M, alpha, cam):
    """the half (pos = the model's own left, +X / neg) whose front silhouette matches the concept better"""
    zb = silhouette(M, "front", cam, alpha.shape[1], alpha.shape[0])
    sil = np.isfinite(zb)
    mask = main_mask(alpha)
    xm = int(round(cam[1] + cam[0] * (M["V"][:, 0].max() + M["V"][:, 0].min()) / 2))
    res = {}
    for name, sl in (("neg", np.s_[:, :xm]), ("pos", np.s_[:, xm:])):   # front: image right = the model's +X
        s, m = sil[sl], mask[sl]
        res[name] = round(float((s & m).sum() / max((s | m).sum(), 1)), 4)
    return max(res, key=res.get), res


# ------------------------------------------------------------------ D: the dense mesh ready for the bake
def prepare_high(raw_mesh, shape_glb, final_glb, out_ply, zup=False):
    """the generator's dense mesh moved where the draft is (Hunyuan: shape.glb -> the draft by their boxes: one scale,
    the centres), crumbs (< 300 faces) and pieces outside the draft's box dropped -> PLY"""
    import trimesh
    m = trimesh.load(str(raw_mesh), force="mesh", process=False)
    comps = trimesh.graph.connected_component_labels(m.face_adjacency, node_count=len(m.faces))
    cnt = np.bincount(comps)
    m.update_faces(cnt[comps] >= 300)
    m.remove_unreferenced_vertices()
    v = np.asarray(m.vertices, float)
    if zup:
        v = np.stack([v[:, 0], v[:, 2], -v[:, 1]], 1)
    A = np.asarray(trimesh.load(str(shape_glb), force="mesh", process=False).vertices, float)
    B = load(final_glb)["V"]
    s = (B[:, 1].max() - B[:, 1].min()) / (A[:, 1].max() - A[:, 1].min())
    t = (B.max(0) + B.min(0)) / 2 - s * (A.max(0) + A.min(0)) / 2
    v = v * s + t
    lo, hi = B.min(0), B.max(0)
    pad = 0.02 * (hi - lo).max()
    mm = trimesh.Trimesh(v, m.faces, process=False)
    comps = trimesh.graph.connected_component_labels(mm.face_adjacency, node_count=len(mm.faces))
    fc = v[mm.faces].mean(1)
    inside = np.array([bool(((fc[comps == c].mean(0) > lo - pad) & (fc[comps == c].mean(0) < hi + pad)).all())
                       for c in range(comps.max() + 1)])
    mm.update_faces(inside[comps])
    mm.remove_unreferenced_vertices()
    mm.export(str(out_ply))
    return {"faces": int(len(mm.faces)), "scale": round(float(s), 5)}


# ------------------------------------------------------------------ the draft, its pictures, its state
def improve_dir(cfg, cat, stem) -> Path:
    d = Path(cfg["work_dir"]) / "improve" / cat / stem
    d.mkdir(parents=True, exist_ok=True)
    return d


def load_state(d: Path) -> dict:
    p = d / "state.json"
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"pictures": {}, "pins": {}, "cams": {}, "codex": {}, "options": {}}


def save_state(d: Path, st: dict):
    (d / "state.json").write_text(json.dumps(st, indent=1, ensure_ascii=False), encoding="utf-8")


def source_pictures(info: dict) -> dict:
    """the pictures the draft was made from, by view: Hunyuan's prepared views (cut, RGBA), TRELLIS's cut picture
    (raw_cutout.png), SF3D's input.png; else the source file itself as the front"""
    src = Path(info.get("source") or "")
    out = {}
    if src.is_dir():
        for v in VIEWS:
            for name in (f"view_{v}.png", f"source_{v}.png"):
                if (src / name).exists():
                    out[v] = str(src / name)
                    break
    elif src.is_file():
        for name in ("raw_cutout.png", "input.png"):
            if (src.parent / name).exists():
                out["front"] = str(src.parent / name)
                break
        out.setdefault("front", str(src))
    return out


def engine_of(info: dict) -> str:
    e = str(info.get("engine") or "")
    return "hunyuan" if e.startswith("hunyuan") else "trellis" if e.startswith("trellis") else "sf3d"


def raw_mesh_of(info: dict):
    """Hunyuan's dense mesh (hy_pipeline keeps shape_raw.ply since 2026-11-27) and its simplified shape.glb"""
    src = Path(info.get("source") or "")
    if src.is_dir() and (src / "shape_raw.ply").exists() and (src / "shape.glb").exists():
        return src / "shape_raw.ply", src / "shape.glb"
    return None


def pictures(st: dict, info: dict) -> dict:
    """{view: {"path", "kind": concept | codex | upload}}: the draft's own pictures, then the user's (uploaded, Codex
    accepted) over them; a picture the user removed stays out ("off")"""
    out = {v: {"path": p, "kind": "concept"} for v, p in source_pictures(info).items()}
    for v, x in (st.get("pictures") or {}).items():
        if x.get("kind") == "off":
            out.pop(v, None)
        elif x.get("path") and Path(x["path"]).exists():
            out[v] = {"path": x["path"], "kind": x.get("kind", "upload")}
    return out


def defaults(info: dict, pics: dict, has_raw: bool) -> dict:
    cat = info.get("category") or ""
    char = cat in ("character", "creature")
    return {"project": True, "mirror": cat == "character", "sharp": 4.0, "delight": 0.0,
            "sym": "auto" if cat == "character" else "off", "relief": bool(has_raw),
            "codex_missing": [v for v in VIEWS if v not in pics and not (v == "right" and "left" in pics and char)
                              and not (v == "left" and "right" in pics and char)] if char else []}


def _pic_key(glb: Path, pic: str) -> str:
    p = Path(pic)
    return f"{glb.stat().st_mtime_ns}|{p}|{p.stat().st_mtime_ns if p.exists() else 0}"


def fitted(d: Path, st: dict, base: Path, view: str, pic: str, M=None, flip=False):
    """the view's camera fitted on the picture, cached by the base model's and the picture's times"""
    key = _pic_key(base, pic) + ("|flip" if flip else "")
    c = (st.get("cams") or {}).get(view)
    if c and c.get("key") == key:
        return tuple(c["cam"]), c.get("iou"), M
    M = M or load(base)
    rgb_, a = pic_alpha(pic)
    if flip:
        a = a[:, ::-1].copy()
    hint = next((x["cam"][0] for x in (st.get("cams") or {}).values() if x.get("cam")), None)
    cam, iou, _ = fit_view(M, view, a, scale_hint=hint)
    st.setdefault("cams", {})[view] = {"key": key, "cam": [float(x) for x in cam], "iou": round(iou, 4)}
    save_state(d, st)
    return tuple(cam), iou, M


def blender(cfg, args, timeout=900):
    exe = cfg.get("blender_exe")
    if not exe or not Path(exe).exists():
        raise RuntimeError("blender_exe in config.json is not set or not found")
    r = subprocess.run([exe, "-b", "--factory-startup", "-P", str(ROOT / "blender_improve.py"), "--", *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=NO_WINDOW)
    line = next((x for x in r.stdout.splitlines() if x.startswith("IMPROVE_OK")), None)
    if not line:
        raise RuntimeError((r.stdout + r.stderr)[-600:])
    return json.loads(line[len("IMPROVE_OK"):])


def run(cat: str, stem: str, cfg: dict, draft_dir: Path, opts: dict, log=None) -> dict:
    """The whole step on a draft: from before.glb (the generator's file, kept on the first run) -> A -> D, C (one
    Blender run) -> normals -> the draft's GLB, icon and its JSON's "improved". opts: project, mirror, sharp, delight,
    sym (off|auto|pos|neg), relief."""
    say = log or (lambda *_: None)
    t0 = time.time()
    glb = Path(draft_dir) / f"{stem}.glb"
    info_p = Path(draft_dir) / f"{stem}.json"
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.exists() else {}
    info.pop("improved", None)
    d = improve_dir(cfg, cat, stem)
    base = d / "before.glb"
    if not base.exists():
        shutil.copy2(glb, base)
    st = load_state(d)
    pics = pictures(st, info)
    steps, secs = [], {}
    cur = base
    if opts.get("project", True) and pics:
        say("A")
        cams, M = {}, None
        for v, x in pics.items():
            cam, iou, M = fitted(d, st, base, v, x["path"], M)
            cams[v] = cam
        if opts.get("mirror") and "left" in pics and "right" not in pics:
            cams["right"], _, M = fitted(d, st, base, "right", pics["left"]["path"], M, flip=True)
        if opts.get("mirror") and "right" in pics and "left" not in pics:
            cams["left"], _, M = fitted(d, st, base, "left", pics["right"]["path"], M, flip=True)
        t = time.time()
        a_info = project(base, d / "step_a.glb", {v: x["path"] for v, x in pics.items()}, mirror=bool(opts.get("mirror")),
                         sharp=float(opts.get("sharp", 4.0)), delight_k=float(opts.get("delight", 0.0)),
                         pins=st.get("pins") or {}, cams=cams)
        secs["project"] = round(time.time() - t, 1)
        steps.append("project")
        cur = d / "step_a.glb"
    bl = []
    if opts.get("relief") and engine_of(info) == "hunyuan" and raw_mesh_of(info):
        say("D")
        raw, shape = raw_mesh_of(info)
        t = time.time()
        prepare_high(raw, shape, base, d / "high.ply")
        secs["relief_prep"] = round(time.time() - t, 1)
        bl += ["bake=" + str(d / "high.ply")]
        steps.append("relief")
    side = opts.get("sym") or "off"
    if side != "off":
        if side == "auto":
            front = pics.get("front")
            if front:
                cam, _, _ = fitted(d, st, base, "front", front["path"])
                side, _scores = pick_half(load(base), pic_alpha(front["path"])[1], cam)
            else:
                side = "pos"
        bl += ["sym=" + side]
        steps.append("sym:" + side)
    if bl:
        say("C/D")
        t = time.time()
        res = blender(cfg, [cur, d / "step_b.glb", *bl])
        secs["blender"] = round(time.time() - t, 1)
        cur = d / "step_b.glb"
    t = time.time()
    set_normals(cur, glb)
    secs["normals"] = round(time.time() - t, 1)
    try:
        import sf3d_tool as T
        T.render_previews(glb, d, Path(draft_dir) / f"{stem}_icon.png", cfg)
    except Exception as e:  # noqa: BLE001  (an icon is not worth failing the step)
        say(f"icon: {e}")
    secs["total"] = round(time.time() - t0, 1)
    summary = {"steps": steps, "seconds": secs, "views": {v: x["kind"] for v, x in pics.items()},
               "when": time.strftime("%Y-%m-%d %H:%M")}
    if opts.get("project", True) and pics:
        summary["fit"] = {v: (st.get("cams") or {}).get(v, {}).get("iou") for v in a_info["views"]}
    info["improved"] = summary
    info_p.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    st["options"] = opts
    save_state(d, st)
    return summary


def undo(cat: str, stem: str, cfg: dict, draft_dir: Path) -> bool:
    d = improve_dir(cfg, cat, stem)
    base = d / "before.glb"
    if not base.exists():
        return False
    glb = Path(draft_dir) / f"{stem}.glb"
    shutil.copy2(base, glb)
    info_p = Path(draft_dir) / f"{stem}.json"
    if info_p.exists():
        info = json.loads(info_p.read_text(encoding="utf-8"))
        info.pop("improved", None)
        info_p.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    try:
        import sf3d_tool as T
        T.render_previews(glb, d, Path(draft_dir) / f"{stem}_icon.png", cfg)
    except Exception:  # noqa: BLE001
        pass
    return True


# ------------------------------------------------------------------ E: the missing sides through Codex
CODEX_SIDE = {"back": "from behind (the camera looks at its back)",
              "left": "from its own left side (a side view, the character faces the left edge of the picture)",
              "right": "from its own right side (a side view, the character faces the right edge of the picture)",
              "front": "from the front"}
CODEX_PROMPT = ("The FIRST attached picture is a render of a 3D game model, seen {side}. The SECOND attached picture "
                "is the original concept art of the same object, seen from the front.\n"
                "Repaint the first picture so the colours, skin, clothes, materials and small details match the concept "
                "art exactly (the same object, now seen {side}). Keep the first picture's silhouette, pose, proportions, "
                "camera angle, framing and picture size exactly as they are: every outline stays where it is, nothing "
                "added outside the object, nothing cut away. Soft even studio lighting like the concept art, plain flat "
                "light grey background, no ground shadow, no text.")


def codex_sides(cat: str, stem: str, cfg: dict, draft_dir: Path, views: list, log=None, opts=None) -> dict:
    """the model (its pictures projected first, so the render already carries the concept's colours) rendered from each
    missing side, then repainted by Codex -> state["codex"][view] = {path, accepted: False} for the user to judge"""
    import refgen as RF
    say = log or (lambda *_: None)
    glb = Path(draft_dir) / f"{stem}.glb"
    info_p = Path(draft_dir) / f"{stem}.json"
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.exists() else {}
    d = improve_dir(cfg, cat, stem)
    base = d / "before.glb"
    if not base.exists():
        shutil.copy2(glb, base)
    st = load_state(d)
    pics = pictures(st, info)
    front = (pics.get("front") or {}).get("path")
    if not front:
        raise RuntimeError("no front picture")
    src = base
    if pics:
        say("A (for the render)")
        cams = {}
        M = None
        for v, x in pics.items():
            cams[v], _, M = fitted(d, st, base, v, x["path"], M)
        project(base, d / "codex_base.glb", {v: x["path"] for v, x in pics.items()}, cams=cams, pins=st.get("pins") or {})
        src = d / "codex_base.glb"
    fw, fh = Image.open(front).size
    w = 864
    h = int(round(w * fh / fw))
    blender(cfg, [src, d / "codex_src", f"render={','.join(views)}", f"w={w}", f"h={h}"])
    out = {}
    for v in views:
        t = time.time()
        say(f"Codex {v}")
        png = d / f"codex_{v}.png"
        try:
            RF.codex_image(CODEX_PROMPT.format(side=CODEX_SIDE[v]), [d / f"codex_src_{v}.png", front], png, timeout=900)
            st.setdefault("codex", {})[v] = {"path": str(png), "render": str(d / f"codex_src_{v}.png"), "accepted": False,
                                             "seconds": round(time.time() - t, 1)}
            out[v] = {"ok": True, "seconds": round(time.time() - t, 1)}
        except Exception as e:  # noqa: BLE001
            out[v] = {"ok": False, "error": str(e)[-300:]}
        save_state(d, st)
    return out


def codex_accept(cat: str, stem: str, cfg: dict, view: str, accept: bool) -> dict:
    d = improve_dir(cfg, cat, stem)
    st = load_state(d)
    c = (st.get("codex") or {}).get(view)
    if not c:
        return st
    c["accepted"] = bool(accept)
    if accept:
        st.setdefault("pictures", {})[view] = {"path": c["path"], "kind": "codex"}
    elif (st.get("pictures") or {}).get(view, {}).get("kind") == "codex":
        st["pictures"].pop(view)
    save_state(d, st)
    return st


def set_picture(cat: str, stem: str, cfg: dict, view: str, path) -> dict:
    """the user's own picture for a view (path), or None to drop the view ("off")"""
    d = improve_dir(cfg, cat, stem)
    st = load_state(d)
    if path:
        dst = d / f"pic_{view}{Path(path).suffix.lower() or '.png'}"
        shutil.copy2(path, dst)
        st.setdefault("pictures", {})[view] = {"path": str(dst), "kind": "upload"}
        st.get("pins", {}).pop(view, None)
    else:
        st.setdefault("pictures", {})[view] = {"kind": "off"}
    save_state(d, st)
    return st


def set_pins(cat: str, stem: str, cfg: dict, view: str, pins: list) -> dict:
    d = improve_dir(cfg, cat, stem)
    st = load_state(d)
    st.setdefault("pins", {})[view] = [[round(float(x), 2) for x in p[:4]] for p in pins or []]
    save_state(d, st)
    return st


def align(cat: str, stem: str, cfg: dict, draft_dir: Path, view: str) -> dict:
    """what the pins editor shows for a view: the picture, the model drawn from the fitted camera at the picture's size
    (PNG), the model's middle line in the picture (for mirrored pins: front / back), the pins so far"""
    glb = Path(draft_dir) / f"{stem}.glb"
    info_p = Path(draft_dir) / f"{stem}.json"
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.exists() else {}
    d = improve_dir(cfg, cat, stem)
    base = d / "before.glb"
    if not base.exists():
        shutil.copy2(glb, base)
    st = load_state(d)
    pics = pictures(st, info)
    if view not in pics:
        return {"ok": False, "view": view}
    pic = pics[view]["path"]
    cam, iou, M = fitted(d, st, base, view, pic)
    M = M or load(base)
    W, H = Image.open(pic).size
    png = d / f"align_{view}.png"
    key = (st.get("cams") or {}).get(view, {}).get("key")
    if not png.exists() or (st.get("align_keys") or {}).get(view) != key:
        shade_render(M, view, cam, W, H).save(png)
        st.setdefault("align_keys", {})[view] = key
        save_state(d, st)
    mid = cam[1] if view in ("front", "back") else None
    return {"ok": True, "view": view, "picture": pic, "model": str(png), "size": [W, H], "cam": list(cam),
            "iou": iou, "mid_x": mid, "pins": (st.get("pins") or {}).get(view, []), "kind": pics[view]["kind"]}


def status(cat: str, stem: str, cfg: dict, draft_dir: Path) -> dict:
    """the step's panel: the draft's engine / category, its pictures by view, Codex candidates, defaults or the last
    options, whether D can work, the last run"""
    info_p = Path(draft_dir) / f"{stem}.json"
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.exists() else {}
    d = Path(cfg["work_dir"]) / "improve" / cat / stem
    st = load_state(d) if d.exists() else load_state(Path("."))
    pics = pictures(st, info)
    has_raw = engine_of(info) == "hunyuan" and raw_mesh_of(info) is not None
    return {"engine": engine_of(info), "category": info.get("category") or cat, "pictures": pics,
            "codex": st.get("codex") or {}, "pins": {v: len(p) for v, p in (st.get("pins") or {}).items()},
            "options": st.get("options") or defaults(info, pics, has_raw), "defaults": defaults(info, pics, has_raw),
            "has_raw": has_raw, "improved": info.get("improved"), "can_undo": (d / "before.glb").exists(),
            "before": str(d / "before.glb") if (d / "before.glb").exists() else None,
            "fit": {v: x.get("iou") for v, x in (st.get("cams") or {}).items()}}
