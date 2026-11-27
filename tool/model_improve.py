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
import hashlib
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
            cams=None, mr_smooth=True, detail=0.7, log=None, skin_warp=None):
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
    if skin_warp:   # (pins on the skins: each texel reads the pictures where its skin point was dragged from)
        pos0, nrm0 = Tx["pos"], Tx["nrm"]
        if skin_warp.get("head"):
            moved = skin_move(pos0, nrm0, *skin_warp["head"])
            if moved is not None:
                Tx["pos"], Tx["nrm"] = moved
        if skin_warp.get("ears"):   # (an ear's texels from their own place, over what the head's pins did)
            moved = ears_move(pos0, nrm0, Tx["fid"], *skin_warp["ears"])
            if moved is not None:
                on, P2, N2 = moved
                Tx["pos"] = Tx["pos"].copy(); Tx["nrm"] = Tx["nrm"].copy()
                Tx["pos"][on], Tx["nrm"][on] = P2, N2
        for bw in skin_warp.get("body") or []:   # (the torso, the arms, the legs: each part's texels by its face)
            moved = body_move(pos0, nrm0, Tx["fid"], *bw)
            if moved is not None:
                on, P2, N2 = moved
                Tx["pos"] = Tx["pos"].copy(); Tx["nrm"] = Tx["nrm"].copy()
                Tx["pos"][on], Tx["nrm"][on] = P2, N2
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
        _marks3d(st, base, M, info.get("category") or cat)
        sizes = {v: Image.open(x["path"]).size for v, x in pics.items()}
        a_info = project(base, d / "step_a.glb", {v: x["path"] for v, x in pics.items()}, mirror=bool(opts.get("mirror")),
                         sharp=float(opts.get("sharp", 4.0)), delight_k=float(opts.get("delight", 0.0)),
                         pins=view_pins(st, cams, {v: x["path"] for v, x in pics.items()}, bool(opts.get("mirror")), sizes),
                         cams=cams, skin_warp=skin_warp_of(d, st, base))
        a_info["marks"] = sum(len(v) for v in (st.get("marks") or {}).values())
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
        _marks3d(st, base, M, info.get("category") or cat)
        sizes = {v: Image.open(x["path"]).size for v, x in pics.items()}
        project(base, d / "codex_base.glb", {v: x["path"] for v, x in pics.items()}, cams=cams,
                pins=view_pins(st, cams, {v: x["path"] for v, x in pics.items()}, False, sizes), skin_warp=skin_warp_of(d, st, base))
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


# ------------------------------------------------------------------ the head's skin laid flat (pins on the skin)
# A cylinder round the head's vertical axis, as in face cloning from front and side photos: the face in the middle, the
# sides and the ears to the left and right, the back of the head at the edges. Every skin pixel keeps its 3D point, so a
# pin on the skin (this feature of the pictures belongs there on the head) moves where on the surface a texel reads
# its colour; the pictures stay projected with their real foreshortening. Same scale both ways at the head's mean radius.
def head_faces(M):
    V = M["V"]
    y0, y1 = V[:, 1].min(), V[:, 1].max()
    m3 = guess_marks3d(M)
    hands = [m3[k][1] for k in ("hand_L", "hand_R") if k in m3]
    arm_y = float(np.mean(hands)) if hands else y0 + 0.75 * (y1 - y0)
    neck = arm_y + 0.04 * (y1 - y0)
    return (V[M["F"]][:, :, 1] > neck).all(1), neck


def skin_params(M, keep, width=2048):
    hv = M["V"][np.unique(M["F"][keep])]
    cz = float(np.median(hv[:, 2]))
    ylo, yhi = float(hv[:, 1].min()), float(hv[:, 1].max())
    r = float(np.median(np.hypot(hv[:, 0], hv[:, 2] - cz)))
    s = width / (2 * np.pi * r)
    return {"cx": 0.0, "cz": cz, "ylo": ylo, "yhi": yhi, "scale": s, "W": int(width), "H": int(np.ceil((yhi - ylo) * s)) + 4}


def skin_xy(P, sp):
    th = np.arctan2(P[:, 0] - sp["cx"], P[:, 2] - sp["cz"])   # (0 = the front, +: the model's left)
    return np.stack([(th / (2 * np.pi) + 0.5) * sp["W"], (sp["yhi"] - P[:, 1]) * sp["scale"] + 2], 1)


def skin_build(M, keep, sp):
    """every skin pixel: the outermost surface point along its radius (an ear covers the head behind it), its normal"""
    W, H = sp["W"], sp["H"]
    V = M["V"]
    P2 = skin_xy(V, sp)
    rho = np.hypot(V[:, 0] - sp["cx"], V[:, 2] - sp["cz"])
    kidx = np.nonzero(keep)[0]
    tx = P2[:, 0][M["F"][kidx]]
    wrap = (tx.max(1) - tx.min(1)) > W / 2   # (triangles across the back seam: drawn on both edges)
    Qw = P2.copy(); Qw[Qw[:, 0] < W / 2, 0] += W
    Qw2 = Qw.copy(); Qw2[:, 0] -= W
    fid_all = np.full((H, W), -1, np.int64); bary_all = np.zeros((H, W, 3), np.float32); zall = np.full((H, W), -np.inf)
    for grp, Q in ((kidx[~wrap], P2), (kidx[wrap], Qw), (kidx[wrap], Qw2)):
        if not len(grp):
            continue
        fid, bary, zb = raster(Q, M["F"][grp], W, H, z=rho)
        sel = (fid >= 0) & (zb > zall)
        fid_all[sel] = grp[fid[sel]]; bary_all[sel] = bary[sel]; zall[sel] = zb[sel]
    ok = fid_all >= 0
    tri = M["F"][fid_all[ok]]
    b = bary_all[ok].astype(np.float64)
    xyz = np.full((H, W, 3), np.nan, np.float32)
    xyz[ok] = (V[tri] * b[..., None]).sum(1)
    N = M.get("N")
    if N is None:
        N = M["N"] = smooth_normals(V, M["F"])
    n = (N[tri] * b[..., None]).sum(1)
    nrm = np.zeros((H, W, 3), np.float32)
    nrm[ok] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    return xyz, nrm


def skin_guide(xyz, nrm, sp):
    """the head's relief on the skin: lit along the radius and from above"""
    ok = np.isfinite(xyz[..., 0])
    rad = np.zeros_like(nrm)
    rad[..., 0] = np.nan_to_num(xyz[..., 0] - sp["cx"]); rad[..., 2] = np.nan_to_num(xyz[..., 2] - sp["cz"])
    rad /= np.maximum(np.linalg.norm(rad, axis=2, keepdims=True), 1e-9)
    L = rad * 0.8 + np.array([0, 0.45, 0])
    L /= np.maximum(np.linalg.norm(L, axis=2, keepdims=True), 1e-9)
    g = 0.25 + 0.55 * np.clip((nrm * L).sum(2), 0, 1) + 0.2 * np.clip((nrm * rad).sum(2), 0, 1)
    img = np.zeros((sp["H"], sp["W"], 4), np.uint8)
    v = (g * 235).clip(0, 255).astype(np.uint8)
    img[ok, 0] = v[ok]; img[ok, 1] = v[ok]; img[ok, 2] = (v[ok] * 1.03).clip(0, 255).astype(np.uint8); img[ok, 3] = 255
    return Image.fromarray(img, "RGBA")


def skin_pictures(M, xyz, nrm, sp, pics, cams, pins, sharp=4.0, prio=None):
    """the pictures as the projection lays them, drawn on the skin (with the picture pins and landmarks): what the skin
    pins then move"""
    prio = {"front": 1.0, "back": 0.85, "left": 0.6, "right": 0.6, **(prio or {})}
    ok = np.isfinite(xyz[..., 0])
    P = xyz[ok].astype(np.float64); Nn = nrm[ok].astype(np.float64)
    acc = np.zeros((len(P), 3)); ws = np.zeros(len(P)); cover = np.zeros(len(P))
    for v, pic in pics.items():
        if v not in cams:
            continue
        rgb_, a = pic_alpha(pic[1] if isinstance(pic, tuple) else pic)
        if isinstance(pic, tuple):
            rgb_, a = rgb_[:, ::-1].copy(), a[:, ::-1].copy()
        cam = cams[v]
        zb = silhouette(M, v, cam, a.shape[1], a.shape[0])
        Tx = {"pos": P, "nrm": Nn}
        w, xy = view_weights(Tx, v, cam, zb, a)
        if (pins or {}).get(v):
            xy = xy + pin_field(pins[v])(xy)
        pre = sample(rgb_.astype(np.float32) * a[..., None], xy)
        col = pre / np.maximum(sample(a.astype(np.float32), xy), 1e-3)[:, None]
        k = (prio.get(v, 1.0) * w) ** sharp
        acc += col * k[:, None]; ws += k; cover = np.maximum(cover, w)
    img = np.zeros((sp["H"], sp["W"], 4), np.uint8)
    col = acc / np.maximum(ws, 1e-12)[:, None]
    rgba = np.concatenate([col.clip(0, 255), (np.clip(cover * 1.5, 0, 1) * 255)[:, None]], 1).astype(np.uint8)
    img[ok] = rgba
    return Image.fromarray(img, "RGBA")


def skin_move(pos, nrm, sp, xyz, xnrm, pins):
    """texels on the head: their skin point q read from the skin point q + D(q) (the pins' warp) - its 3D point and
    normal from the skin maps; texels off the head or landing off the skin keep theirs"""
    if not pins:
        return None
    from scipy.ndimage import map_coordinates
    q = skin_xy(pos, sp)
    on = (pos[:, 1] >= sp["ylo"]) & (q[:, 1] >= 0) & (q[:, 1] < sp["H"])
    if not on.any():
        return None
    qq = q[on] + pin_field(pins)(q[on])
    moved = np.linalg.norm(qq - q[on], axis=1) > 0.05

    def at(qs):
        xs = np.mod(qs[:, 0] - 0.5, sp["W"]); ys = np.clip(qs[:, 1] - 0.5, 0, sp["H"] - 1)
        return (np.stack([map_coordinates(xyz[..., c], [ys, xs], order=0, mode="nearest") for c in range(3)], 1),
                np.stack([map_coordinates(xnrm[..., c], [ys, xs], order=0, mode="nearest") for c in range(3)], 1))
    Pa, Na = at(q[on])
    Pb, Nb = at(qq)
    good = moved & np.isfinite(Pa).all(1) & np.isfinite(Pb).all(1)
    pos2, nrm2 = pos.copy(), nrm.copy()
    idx = np.nonzero(on)[0][good]
    # (moved by the skin's own move: a layer under the outermost one - behind an ear, an ear's back - keeps its depth
    # instead of jumping onto the outer surface)
    pos2[idx] += Pb[good] - Pa[good]
    n2 = nrm2[idx] + Nb[good] - Na[good]
    nrm2[idx] = n2 / np.maximum(np.linalg.norm(n2, axis=1, keepdims=True), 1e-9)
    return pos2, nrm2


def skin_state(d: Path, st: dict, base: Path, M=None, width=2048):
    """the head skin's parameters and maps for base.glb, built once (cached by the model's time)"""
    key = str(base.stat().st_mtime_ns)
    sk = (st.get("skin") or {}).get("head")
    if sk and sk.get("key") == key and (d / "skin_head_xyz.npy").exists():
        return sk["params"], np.load(d / "skin_head_xyz.npy"), np.load(d / "skin_head_nrm.npy"), M
    M = M or load(base)
    keep, _ = head_faces(M)
    sp = skin_params(M, keep, width)
    xyz, nrm = skin_build(M, keep, sp)
    np.save(d / "skin_head_xyz.npy", xyz); np.save(d / "skin_head_nrm.npy", nrm)
    skin_guide(xyz, nrm, sp).save(d / "skin_head_guide.png")
    st.setdefault("skin", {})["head"] = {"key": key, "params": sp}
    save_state(d, st)
    return sp, xyz, nrm, M


def skin_warp_of(d: Path, st: dict, base: Path):
    """for project(): {"head": (params, xyz, nrm, pins), "ears": (params, faces, xyz, nrm, pins)} for the skins that
    have pins, else None"""
    out = {}
    pins = (st.get("pins") or {}).get("skin_head")
    if pins:
        sp, xyz, nrm, _ = skin_state(d, st, base)
        out["head"] = (sp, xyz, nrm, [tuple(p) for p in pins])
    pins = (st.get("pins") or {}).get("skin_ears")
    if pins:
        ep = ears_state(d, st, base)
        if ep:
            prm, faces, xyz, nrm, _ = ep
            out["ears"] = (prm, faces, xyz, nrm, [tuple(p) for p in pins])
    for view in BODY_SKINS:
        pins = (st.get("pins") or {}).get(view)
        if pins:
            bp = body_state(d, st, base, view)
            if bp:
                prm, faces, xyz, nrm, _ = bp
                out.setdefault("body", []).append((prm, faces, xyz, nrm, [tuple(p) for p in pins]))
    return out or None


# ------------------------------------------------------------------ the ears laid flat, each with its back
# The head's cylinder sees an ear from outside only; its back is behind it. Here each ear is cut off the head (what
# lies farther out along the radius than the skull under it, joined to the ear tip) and laid on its own plane (the
# ear's flattest direction, facing front): the side facing front and the back side drawn as seen through it, so both
# panels have the same outline - [left back | left front || right front | right back], the right ear mirrored.
def skull_fit(xyz, sp):
    """the skull as an ellipsoid (axis-aligned, centred on the model's middle left-right) fitted to the head's outer
    skin above its lower third; the ears, the nose and the chin stick out of it and are left out by a robust loss"""
    from scipy.optimize import least_squares
    ok = np.isfinite(xyz[..., 0])
    P = xyz[ok].astype(np.float64)
    P = P[P[:, 1] > sp["ylo"] + 0.3 * (sp["yhi"] - sp["ylo"])]
    if len(P) > 30000:
        P = P[np.random.default_rng(0).choice(len(P), 30000, replace=False)]
    r0 = float(np.median(np.linalg.norm(P - [0, np.median(P[:, 1]), sp["cz"]], axis=1)))

    def res(x):
        a, b, c, cy, cz = x
        return np.sqrt((P[:, 0] / a) ** 2 + ((P[:, 1] - cy) / b) ** 2 + ((P[:, 2] - cz) / c) ** 2) - 1

    x0 = [r0, r0, r0, float(np.median(P[:, 1])), sp["cz"]]
    fit = least_squares(res, x0, loss="cauchy", f_scale=0.02)
    a, b, c, cy, cz = fit.x
    return {"a": abs(a), "b": abs(b), "c": abs(c), "cy": cy, "cz": cz}


def ear_faces(M, keep, sk, m3, margin=0.06):
    """{"L"/"R": face ids of that ear}: the head's faces standing out of the skull ellipsoid by more than the margin on
    that side, the piece of them that holds the ear tip"""
    import scipy.sparse as sp_
    from scipy.sparse.csgraph import connected_components
    V, F = M["V"], M["F"]
    e = np.sqrt((V[:, 0] / sk["a"]) ** 2 + ((V[:, 1] - sk["cy"]) / sk["b"]) ** 2 + ((V[:, 2] - sk["cz"]) / sk["c"]) ** 2)
    rep, k = weld(V, 1e-5)
    out, bases = {}, {}
    for s, sg in (("L", 1.0), ("R", -1.0)):
        T = m3.get(f"ear_tip_{s}")
        if T is None:
            continue
        T = np.asarray(T)
        # the ear's base: the tip drawn back onto the skull ellipsoid along its radius; the ear = near the base-tip line
        C = np.array([0.0, sk["cy"], sk["cz"]])
        et = np.sqrt((T[0] / sk["a"]) ** 2 + ((T[1] - sk["cy"]) / sk["b"]) ** 2 + ((T[2] - sk["cz"]) / sk["c"]) ** 2)
        B = C + (T - C) / max(et, 1e-6)
        ln = max(float(np.linalg.norm(T - B)), 1e-4)
        ax = (T - B) / ln
        # (a cheek or a jaw standing out of the skull ellipsoid stays out: not much behind the base, not far from it)
        near_ear = (np.linalg.norm(V - B, axis=1) < 1.25 * ln) & ((V - B) @ ax > -0.3 * ln)
        bases[s] = B.tolist()
        stand = (e > 1 + margin) & (sg * V[:, 0] > 0.35 * sk["a"]) & near_ear
        cand = np.nonzero(keep & stand[F].all(1))[0]
        if len(cand) < 20:
            continue
        Fc = rep[F[cand]]
        rows = np.repeat(np.arange(len(cand)), 3)
        A = sp_.coo_matrix((np.ones(len(rows)), (rows, Fc.ravel())), shape=(len(cand), k)).tocsr()
        n, lab = connected_components(A @ A.T, directed=False)
        near = np.argmin(np.linalg.norm(V[F[cand]].mean(1) - T, axis=1))
        out[s] = cand[lab == lab[near]]
    return out, bases


def ears_build(M, ears, width=2048, tips=None, bases=None):
    """the ear panels: per ear its frame (the flattest direction N facing front, e1 toward the tip), the front side
    (faces with n.N > 0, the nearest along N) and the back side (the rest, the nearest along -N) drawn into their
    panels with one scale per ear -> (params, xyz, nrm)"""
    V, F = M["V"], M["F"]
    N_ = M.get("N")
    if N_ is None:
        N_ = M["N"] = smooth_normals(V, F)
    P = width // 4
    W, H = 4 * P, P
    xyz = np.full((H, W, 3), np.nan, np.float32); nrm = np.zeros((H, W, 3), np.float32)
    zall = np.full((H, W), -np.inf)
    prm = {"W": W, "H": H, "P": P, "ears": {}}
    fn = np.cross(V[F[:, 1]] - V[F[:, 0]], V[F[:, 2]] - V[F[:, 0]])
    for s, fids in ears.items():
        vid = np.unique(F[fids])
        Pv = V[vid]
        c = Pv.mean(0)
        _, _, vt = np.linalg.svd(Pv - c, full_matrices=False)
        Nn = vt[2] if vt[2][2] >= 0 else -vt[2]
        tip = np.asarray((tips or {}).get(s)) if (tips or {}).get(s) is not None else Pv[np.argmax(np.linalg.norm(Pv - c, axis=1))]
        root = np.asarray((bases or {}).get(s)) if (bases or {}).get(s) is not None else c
        e1 = (tip - root) - np.dot(tip - root, Nn) * Nn
        e1 /= max(np.linalg.norm(e1), 1e-9)
        e2 = (1 if s == "L" else -1) * np.cross(Nn, e1)
        u, v = (Pv - c) @ e1, (Pv - c) @ e2
        u0, v0 = (u.max() + u.min()) / 2, (v.max() + v.min()) / 2
        sc = 0.9 * P / max(u.max() - u.min(), v.max() - v.min(), 1e-6)
        dirx = -1.0 if s == "L" else 1.0
        cxs = {"back": P * 0.5, "front": P * 1.5} if s == "L" else {"front": P * 2.5, "back": P * 3.5}
        prm["ears"][s] = {"c": c.tolist(), "e1": e1.tolist(), "e2": e2.tolist(), "N": Nn.tolist(), "u0": float(u0), "v0": float(v0),
                          "sc": float(sc), "dir": dirx, "cx": cxs}
        front = (fn[fids] @ Nn) > 0
        for side, sel, sgn in (("front", fids[front], 1.0), ("back", fids[~front], -1.0)):
            if not len(sel):
                continue
            Q = np.zeros((len(V), 2))
            Q[:, 0] = cxs[side] + dirx * (((V - c) @ e1) - u0) * sc
            Q[:, 1] = H / 2 - (((V - c) @ e2) - v0) * sc
            fid, bary, zb = raster(Q, F[sel], W, H, z=sgn * (V @ Nn))
            ok = (fid >= 0) & (zb > zall)
            if not ok.any():
                continue
            tri = F[sel[fid[ok]]]
            b = bary[ok].astype(np.float64)
            xyz[ok] = (V[tri] * b[..., None]).sum(1)
            n = (N_[tri] * b[..., None]).sum(1)
            nrm[ok] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
            zall[ok] = zb[ok]
    return prm, xyz, nrm


def ears_coords(pos, nrm, fid, prm, faces):
    """texels on an ear -> (mask, their panel coordinates): which ear by the face, which side by the normal"""
    on = np.zeros(len(pos), bool)
    q = np.zeros((len(pos), 2))
    for s, e in prm["ears"].items():
        fs = faces.get(s)
        if fs is None or not len(fs):
            continue
        m = np.isin(fid, fs)
        if not m.any():
            continue
        c, e1, e2, Nn = (np.asarray(e[k]) for k in ("c", "e1", "e2", "N"))
        P = pos[m]
        side = np.where(nrm[m] @ Nn > 0, e["cx"]["front"], e["cx"]["back"])
        q[m, 0] = side + e["dir"] * (((P - c) @ e1) - e["u0"]) * e["sc"]
        q[m, 1] = prm["H"] / 2 - (((P - c) @ e2) - e["v0"]) * e["sc"]
        on |= m
    return on, q


def ears_move(pos, nrm, fid, prm, faces, xyz, xnrm, pins):
    """an ear's texels read from where the ear pins dragged them (as skin_move, on the ear panels)"""
    if not pins:
        return None
    from scipy.ndimage import map_coordinates
    on, q = ears_coords(pos, nrm, fid, prm, faces)
    if not on.any():
        return None
    qq = q[on] + pin_field(pins)(q[on])
    xs = np.clip(qq[:, 0] - 0.5, 0, prm["W"] - 1); ys = np.clip(qq[:, 1] - 0.5, 0, prm["H"] - 1)
    Pn = np.stack([map_coordinates(xyz[..., c], [ys, xs], order=0, mode="nearest") for c in range(3)], 1)
    Nn = np.stack([map_coordinates(xnrm[..., c], [ys, xs], order=0, mode="nearest") for c in range(3)], 1)
    good = np.isfinite(Pn).all(1)
    idx = np.nonzero(on)[0]
    P2, N2 = pos[idx].copy(), nrm[idx].copy()
    P2[good], N2[good] = Pn[good], Nn[good]
    return idx, P2, N2


def ears_guide(xyz, nrm, prm):
    """the ears' relief on their panels: lit along the panel's own normal (N in front, -N behind) and from above"""
    ok = np.isfinite(xyz[..., 0])
    L = np.zeros_like(nrm)
    P = prm["P"]
    for s, e in prm["ears"].items():
        Nn = np.asarray(e["N"])
        for side, sgn in (("front", 1.0), ("back", -1.0)):
            x0 = int(e["cx"][side] - P / 2)
            L[:, x0:x0 + P] = sgn * Nn * 0.8 + np.array([0, 0.45, 0])
    L /= np.maximum(np.linalg.norm(L, axis=2, keepdims=True), 1e-9)
    g = 0.25 + 0.75 * np.clip((nrm * L).sum(2), 0, 1)
    img = np.zeros((prm["H"], prm["W"], 4), np.uint8)
    v = (g * 235).clip(0, 255).astype(np.uint8)
    img[ok, 0] = v[ok]; img[ok, 1] = v[ok]; img[ok, 2] = (v[ok] * 1.03).clip(0, 255).astype(np.uint8); img[ok, 3] = 255
    return Image.fromarray(img, "RGBA")


def ears_state(d: Path, st: dict, base: Path, M=None, width=2048):
    """the ear panels for base.glb, built once (cached by the model's time); None when no ear was found"""
    key = str(base.stat().st_mtime_ns)
    ek = (st.get("skin") or {}).get("ears")
    if ek and ek.get("key") == key and (d / "skin_ears_xyz.npy").exists():
        faces = {s: np.load(d / f"skin_ears_faces_{s}.npy") for s in ek["params"]["ears"]}
        return ek["params"], faces, np.load(d / "skin_ears_xyz.npy"), np.load(d / "skin_ears_nrm.npy"), M
    sp, hxyz, _, M = skin_state(d, st, base, M)
    M = M or load(base)
    keep, _ = head_faces(M)
    m3 = st.get("marks3d") or guess_marks3d(M)
    faces, bases = ear_faces(M, keep, skull_fit(hxyz, sp), m3)
    if not faces:
        return None
    prm, xyz, nrm = ears_build(M, faces, width, tips={s_: m3.get(f"ear_tip_{s_}") for s_ in faces}, bases=bases)
    np.save(d / "skin_ears_xyz.npy", xyz); np.save(d / "skin_ears_nrm.npy", nrm)
    for s_, f_ in faces.items():
        np.save(d / f"skin_ears_faces_{s_}.npy", f_)
    ears_guide(xyz, nrm, prm).save(d / "skin_ears_guide.png")
    st = load_state(d)
    st.setdefault("skin", {})["ears"] = {"key": key, "params": prm}
    save_state(d, st)
    return prm, faces, xyz, nrm, M


# ------------------------------------------------------------------ the body laid flat: the torso, the arms, the legs
# Each part is a cylinder round its own axis (the torso: vertical, as the head; an arm: shoulder -> fingertip; a leg:
# crotch -> sole), its surface drawn outermost along the radius, one scale both ways at the part's mean radius. The
# layouts keep the front picture's look and make mirrored pins work (x -> W - x swaps the sides):
#   skin_torso  the front in the middle, the back at the edges (as the head's skin)
#   skin_arms   [right arm | left arm]: the shoulders meet in the middle, the hands at the edges; an arm's front along the
#               middle row, its top above, its underside below, its back at the top and bottom edges
#   skin_legs   [right leg | left leg]: each one's front in its middle, the hip at the top, the foot at the bottom
# The cut follows the landmarks (hands, elbows, knees - moved by hand in the «Landmarks» mode they cut again): a face is
# an arm's when it lies nearer that arm's axis (in the arm's radii) than the torso's axis (in the torso's half-width /
# half-depth) or its leg's axis (in the leg's radii), the piece holding the hand; below the crotch the rest are legs.
BODY_SKINS = ("skin_torso", "skin_arms", "skin_legs")
BODY_MARKS = ("hand_L", "hand_R", "elbow_L", "elbow_R", "knee_L", "knee_R")


def _unit(v):
    v = np.asarray(v, float)
    return v / max(float(np.linalg.norm(v)), 1e-12)


def _seg_dist(P, A, a, L):
    """distance of points P from the segment A -> A + a L (a unit)"""
    t = np.clip((P - A) @ a, 0, L)
    return np.linalg.norm(P - A - t[:, None] * a, axis=1)


def body_cut(M, m3):
    """{"labels": per face 0 head, 1 torso, 2 arm L, 3 arm R, 4 leg L, 5 leg R; "joints": the axes found} for a T / A-
    posed character facing +Z, or None when the hand / elbow / knee landmarks are missing"""
    import scipy.sparse as sp_
    from scipy.sparse.csgraph import connected_components
    if not all(k in m3 for k in BODY_MARKS):
        return None
    V, F = M["V"], M["F"]
    ymin, ymax = float(V[:, 1].min()), float(V[:, 1].max())
    h = ymax - ymin
    head, neck = head_faces(M)
    J = {k: np.asarray(m3[k], float) for k in BODY_MARKS}
    C = V[F].mean(1)
    # the arms: the shoulder joint = the elbow + 0.9 x (elbow - hand); the radius at the elbow; the fingertip = the
    # farthest point along the axis near it
    arms = {}
    for s in ("L", "R"):
        Hd, E = J[f"hand_{s}"], J[f"elbow_{s}"]
        O = E + 0.9 * (E - Hd)
        a = _unit(Hd - O)
        R = V - O
        t = R @ a
        rr = np.linalg.norm(R - t[:, None] * a, axis=1)
        te = float((E - O) @ a)
        sl = (np.abs(t - te) < 0.012 * h) & (rr < 0.06 * h)
        r = float(np.median(rr[sl])) if sl.sum() > 5 else 0.03 * h
        near = (rr < 3.5 * r) & (t > 0)
        L = float(t[near].max()) if near.any() else float((Hd - O) @ a) * 1.3
        arms[s] = {"O": O, "a": a, "r": max(r, 1e-4), "L": L}
    # the legs: the radius round the knee (across the horizontal slice), the ankle = the middle of the slice at 7 % of the
    # height; the crotch = the lowest height (going up from the knees) where the surface closes between the legs
    legs = {}
    for s, sg in (("L", 1.0), ("R", -1.0)):
        K = J[f"knee_{s}"]
        dxz = np.hypot(V[:, 0] - K[0], V[:, 2] - K[2])
        sl = (np.abs(V[:, 1] - K[1]) < 0.012 * h) & (sg * V[:, 0] > 0) & (dxz < 0.12 * h)
        rl = float(np.median(dxz[sl])) if sl.sum() > 5 else 0.04 * h
        ya = ymin + 0.07 * h
        sa = (np.abs(V[:, 1] - ya) < 0.012 * h) & (sg * V[:, 0] > 0) & (dxz < 0.2 * h)
        A = (V[sa].min(0) + V[sa].max(0)) / 2 if sa.sum() >= 3 else np.array([K[0], ya, K[2]])
        legs[s] = {"K": K, "A": A, "r": max(rl, 1e-4)}
    gap = 0.12 * min(abs(J["knee_L"][0]), abs(J["knee_R"][0]))   # (the thighs' insides come close below the crotch)
    zc = (J["knee_L"][2] + J["knee_R"][2]) / 2
    rl_ = min(legs["L"]["r"], legs["R"]["r"])
    ky = max(J["knee_L"][1], J["knee_R"][1])
    crotch = None
    mid = (np.abs(V[:, 0]) < gap) & (np.abs(V[:, 2] - zc) < 0.6 * rl_)
    for yy in np.arange(ky + 0.02 * h, neck, 0.004 * h):
        if (mid & (np.abs(V[:, 1] - yy) < 0.003 * h)).sum() >= 3:
            crotch = float(yy)
            break
    if crotch is None:
        crotch = float(ky + 0.9 * (ky - ymin))
    for s, g in legs.items():
        a = _unit(g["A"] - g["K"])
        if a[1] > -0.5:   # (a leg runs down)
            a = np.array([0.0, -1.0, 0.0])
        O = g["K"] + a * ((crotch - g["K"][1]) / a[1])   # (the axis's point at the crotch's height)
        t = (V - O) @ a
        g.update({"O": O, "a": a, "L": float(min(t.max(), (O[1] - ymin) / max(-a[1], 1e-6) * 1.15))})
    # the torso: half-width across the middle of the torso (inside the elbows), half-depth across its middle
    ym = (neck + crotch) / 2
    ex = 0.85 * min(abs(J["elbow_L"][0]), abs(J["elbow_R"][0]))
    sl = (np.abs(V[:, 1] - ym) < 0.01 * h) & (np.abs(V[:, 0]) < ex)
    Rx = float(np.abs(V[sl, 0]).max()) if sl.sum() > 5 else 0.95 * max(abs(arms["L"]["O"][0]), abs(arms["R"]["O"][0]))
    sl2 = sl & (np.abs(V[:, 0]) < 0.5 * Rx)
    # (the middle of the depth, not the median: a generator's mesh is often denser on the front)
    cz = float((V[sl2, 2].max() + V[sl2, 2].min()) / 2) if sl2.sum() > 5 else float(zc)
    Rz = float((V[sl2, 2].max() - V[sl2, 2].min()) / 2) if sl2.sum() > 5 else Rx * 0.7
    Rx, Rz = max(Rx, 1e-4), max(Rz, 1e-4)
    # the costs per face (its centre): the nearest part in its own radii
    big = 1e9
    above = C[:, 1] >= crotch
    cost = np.full((len(F), 5), big)
    cost[:, 0] = np.where(above, np.hypot(C[:, 0] / Rx, (C[:, 2] - cz) / Rz), big)
    for i, s in enumerate(("L", "R")):
        g = arms[s]
        cost[:, 1 + i] = _seg_dist(C, g["O"], g["a"], g["L"]) / g["r"]
        g = legs[s]
        cost[:, 3 + i] = np.where(above, big, _seg_dist(C, g["O"], g["a"], g["L"]) / g["r"])
    lab = np.argmin(cost, 1) + 1
    lab[head] = 0
    # (the head's level cut at the neck takes the tops of T-posed shoulders: those near an arm's axis go to the arm)
    back = head & (C[:, 1] < neck + 0.06 * h) & (np.minimum(cost[:, 1], cost[:, 2]) < 1.4)
    lab[back] = np.where(cost[back, 1] <= cost[back, 2], 2, 3)
    # an arm = the piece of its faces holding the hand; its other faces go back to the torso / the legs
    rep, k = weld(V, 1e-5)
    for i, s in enumerate(("L", "R")):
        idx = np.nonzero(lab == 2 + i)[0]
        if not len(idx):
            continue
        rows = np.repeat(np.arange(len(idx)), 3)
        A_ = sp_.coo_matrix((np.ones(len(rows)), (rows, rep[F[idx]].ravel())), shape=(len(idx), k)).tocsr()
        _, cc = connected_components(A_ @ A_.T, directed=False)
        keep = cc == cc[np.argmin(np.linalg.norm(C[idx] - J[f"hand_{s}"], axis=1))]
        rest = idx[~keep]
        if len(rest):
            c2 = cost[rest][:, [0, 3, 4]]
            lab[rest] = np.array([1, 4, 5])[np.argmin(c2, 1)]
    joints = {"neck": float(neck), "crotch": float(crotch), "torso": {"cz": cz, "Rx": Rx, "Rz": Rz},
              "arms": arms, "legs": legs}
    return {"labels": lab, "joints": joints}


def part_xy(P, p):
    """points -> (their panel coordinates on that part's cylinder, their distance from its axis)"""
    O, a, ef, eu = (np.asarray(p[k], float) for k in ("O", "a", "ef", "eu"))
    R = np.asarray(P, float) - O
    t = R @ a
    rr = R - t[:, None] * a
    th = np.arctan2(rr @ eu, rr @ ef)
    q = (np.asarray(p["anchor"], float) + (t * p["s"])[:, None] * np.asarray(p["tdir"], float)
         + (th * p["r"] * p["s"])[:, None] * np.asarray(p["hdir"], float))
    return q, np.linalg.norm(rr, axis=1)


def _frame(a, sg_up=None):
    """a part's cylinder frame round axis a: ef = the front (+Z) square to it; eu = +90 degrees of the angle: for an arm
    (sg_up = +1 left / -1 right) its top, else the model's left (+X)"""
    a = _unit(a)
    ef = np.array([0.0, 0.0, 1.0]) - a[2] * a
    if np.linalg.norm(ef) < 1e-3:
        ef = np.array([0.0, 1.0, 0.0]) - a[1] * a
    ef = _unit(ef)
    if sg_up is not None:
        eu = _unit(sg_up * np.cross(ef, a))
    else:
        eu = np.array([1.0, 0.0, 0.0])
        eu = _unit(eu - (eu @ a) * a - (eu @ ef) * ef)
    return ef, eu


def body_layout(M, cut, view, width=2048):
    """(params {"W", "H", "parts": {name: frame, scale, panel place}}, {name: face ids}) for a body skin, or None"""
    V, F = M["V"], M["F"]
    lab, J = cut["labels"], cut["joints"]
    L_ = lambda v: np.asarray(v, float).tolist()   # noqa: E731
    parts, faces = {}, {}

    def radius(fids, O, a):
        vid = np.unique(F[fids])
        R = V[vid] - O
        t = R @ a
        return float(np.median(np.linalg.norm(R - t[:, None] * a, axis=1))), t

    if view == "skin_torso":
        fids = np.nonzero(lab == 1)[0]
        if len(fids) < 50:
            return None
        vy = V[np.unique(F[fids]), 1]
        ytop, ybot = float(vy.max()), float(vy.min())
        O = np.array([0.0, ytop, J["torso"]["cz"]]); a = np.array([0.0, -1.0, 0.0])
        r, _ = radius(fids, O, a)
        s = width / (2 * np.pi * r)
        W, H = int(width), int(np.ceil((ytop - ybot) * s)) + 4
        parts["torso"] = {"O": L_(O), "a": L_(a), "ef": [0, 0, 1.0], "eu": [1.0, 0, 0], "r": r, "s": s,
                          "anchor": [W / 2, 2.0], "tdir": [0, 1.0], "hdir": [1.0, 0], "rect": [0, 0, W, H]}
        faces["torso"] = fids
    elif view == "skin_arms":
        info = {}
        for i, s_ in enumerate(("L", "R")):
            fids = np.nonzero(lab == 2 + i)[0]
            if len(fids) < 50:
                continue
            g = J["arms"][s_]
            r, t = radius(fids, g["O"], g["a"])
            info[s_] = (fids, g, r, float(t.max()), float(min(t.min(), 0)))
        if not info:
            return None
        r = float(np.mean([x[2] for x in info.values()]))
        Lm = max(x[3] for x in info.values())
        back = min(max(-x[4] for x in info.values()), 0.3 * Lm)
        s = width / (2 * (Lm + back))
        W, H = int(width), int(np.ceil(2 * np.pi * r * s)) + 4
        for s_, (fids, g, _, _, _) in info.items():
            sg = 1.0 if s_ == "L" else -1.0
            ef, eu = _frame(g["a"], sg)
            parts[f"arm_{s_}"] = {"O": L_(g["O"]), "a": L_(g["a"]), "ef": L_(ef), "eu": L_(eu), "r": r, "s": s,
                                  "anchor": [W / 2 + sg * back * s, H / 2], "tdir": [sg, 0], "hdir": [0, -1.0],
                                  "rect": [W / 2, 0, W, H] if s_ == "L" else [0, 0, W / 2, H]}
            faces[f"arm_{s_}"] = fids
    elif view == "skin_legs":
        info = {}
        for i, s_ in enumerate(("L", "R")):
            fids = np.nonzero(lab == 4 + i)[0]
            if len(fids) < 50:
                continue
            g = J["legs"][s_]
            r, t = radius(fids, g["O"], g["a"])
            info[s_] = (fids, g, r, float(t.max()), float(min(t.min(), 0)))
        if not info:
            return None
        r = float(np.mean([x[2] for x in info.values()]))
        Lm = max(x[3] for x in info.values())
        top = min(max(-x[4] for x in info.values()), 0.2 * Lm)
        s = min(width / (4 * np.pi * r), 2048 / (Lm + top))
        P = 2 * np.pi * r * s
        W, H = int(np.ceil(2 * P)), int(np.ceil((Lm + top) * s)) + 4
        for s_, (fids, g, _, _, _) in info.items():
            ef, eu = _frame(g["a"])
            cx = 1.5 * P if s_ == "L" else 0.5 * P
            parts[f"leg_{s_}"] = {"O": L_(g["O"]), "a": L_(g["a"]), "ef": L_(ef), "eu": L_(eu), "r": r, "s": s,
                                  "anchor": [cx, top * s + 2], "tdir": [0, 1.0], "hdir": [1.0, 0],
                                  "rect": [P, 0, 2 * P, H] if s_ == "L" else [0, 0, P, H]}
            faces[f"leg_{s_}"] = fids
    else:
        return None
    return {"W": W, "H": H, "parts": parts}, faces


def body_build(M, prm, faces):
    """every pixel of a body skin: the outermost surface point of its part along the part's radius, its normal"""
    V, F = M["V"], M["F"]
    N_ = M.get("N")
    if N_ is None:
        N_ = M["N"] = smooth_normals(V, F)
    W, H = prm["W"], prm["H"]
    xyz = np.full((H, W, 3), np.nan, np.float32); nrm = np.zeros((H, W, 3), np.float32)
    zall = np.full((H, W), -np.inf)
    fid_all = np.full((H, W), -1, np.int64); bary_all = np.zeros((H, W, 3), np.float32)
    yy, xx = np.mgrid[0:H, 0:W] + 0.5
    for name, p in prm["parts"].items():
        fids = faces[name]
        Q, rho = part_xy(V, p)
        per = 2 * np.pi * p["r"] * p["s"]
        hd = np.asarray(p["hdir"], float)
        c = (Q - np.asarray(p["anchor"], float)) @ hd   # (the angle's coordinate: -per/2 .. per/2)
        tc = c[F[fids]]
        wrap = (tc.max(1) - tc.min(1)) > per / 2   # (triangles across the back seam: drawn on both edges)
        Qw = Q.copy(); Qw[c < 0] += per * hd
        Qw2 = Qw - per * hd
        x0, y0, x1, y1 = p["rect"]
        inr = (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)
        for grp, QQ in ((fids[~wrap], Q), (fids[wrap], Qw), (fids[wrap], Qw2)):
            if not len(grp):
                continue
            fid, bary, zb = raster(QQ, F[grp], W, H, z=rho)
            sel = (fid >= 0) & (zb > zall) & inr
            fid_all[sel] = grp[fid[sel]]; bary_all[sel] = bary[sel]; zall[sel] = zb[sel]
    ok = fid_all >= 0
    tri = F[fid_all[ok]]
    b = bary_all[ok].astype(np.float64)
    xyz[ok] = (V[tri] * b[..., None]).sum(1)
    n = (N_[tri] * b[..., None]).sum(1)
    nrm[ok] = n / np.maximum(np.linalg.norm(n, axis=1, keepdims=True), 1e-9)
    return xyz, nrm


def body_guide(xyz, nrm, prm):
    """a body skin's relief: lit along each part's own radius and from above"""
    ok = np.isfinite(xyz[..., 0])
    rad = np.zeros_like(nrm)
    H, W = ok.shape
    yy, xx = np.mgrid[0:H, 0:W] + 0.5
    for p in prm["parts"].values():
        x0, y0, x1, y1 = p["rect"]
        m = ok & (xx >= x0) & (xx < x1) & (yy >= y0) & (yy < y1)
        O, a = np.asarray(p["O"], float), np.asarray(p["a"], float)
        R = xyz[m].astype(np.float64) - O
        rad[m] = R - (R @ a)[:, None] * a
    rad /= np.maximum(np.linalg.norm(rad, axis=2, keepdims=True), 1e-9)
    Lt = rad * 0.8 + np.array([0, 0.45, 0])
    Lt /= np.maximum(np.linalg.norm(Lt, axis=2, keepdims=True), 1e-9)
    g = 0.25 + 0.55 * np.clip((nrm * Lt).sum(2), 0, 1) + 0.2 * np.clip((nrm * rad).sum(2), 0, 1)
    img = np.zeros((H, W, 4), np.uint8)
    v = (g * 235).clip(0, 255).astype(np.uint8)
    img[ok, 0] = v[ok]; img[ok, 1] = v[ok]; img[ok, 2] = (v[ok] * 1.03).clip(0, 255).astype(np.uint8); img[ok, 3] = 255
    return Image.fromarray(img, "RGBA")


def _skin_at(xyz, xnrm, q, rect):
    """a skin map's 3D point and normal at panel points q (nearest pixel, kept inside the rect)"""
    from scipy.ndimage import map_coordinates
    x0, y0, x1, y1 = rect
    xs = np.clip(q[:, 0] - 0.5, x0, x1 - 1); ys = np.clip(q[:, 1] - 0.5, y0, y1 - 1)
    P = np.stack([map_coordinates(xyz[..., k], [ys, xs], order=0, mode="nearest") for k in range(3)], 1)
    N = np.stack([map_coordinates(xnrm[..., k], [ys, xs], order=0, mode="nearest") for k in range(3)], 1)
    return P, N


def body_move(pos, nrm, fid, prm, faces, xyz, xnrm, pins):
    """a body part's texels read from where its pins dragged them (as skin_move, per part: only the pins on that
    part's panel move it) -> (texel ids, positions, normals) or None"""
    if not pins:
        return None
    P_ = np.asarray(pins, float).reshape(-1, 4)
    ids, Ps, Ns = [], [], []
    for name, p in prm["parts"].items():
        x0, y0, x1, y1 = p["rect"]
        pp = P_[(P_[:, 2] >= x0) & (P_[:, 2] < x1) & (P_[:, 3] >= y0) & (P_[:, 3] < y1)]
        fs = faces.get(name)
        if not len(pp) or fs is None or not len(fs):
            continue
        m = np.isin(fid, fs)
        if not m.any():
            continue
        q, _ = part_xy(pos[m], p)
        D = pin_field(pp)(q)
        qq = q + D
        per = 2 * np.pi * p["r"] * p["s"]
        hd = np.asarray(p["hdir"], float)
        c = (qq - np.asarray(p["anchor"], float)) @ hd
        qq = qq + (np.mod(c + per / 2, per) - per / 2 - c)[:, None] * hd   # (round the cylinder, not off its panel)
        Pa, Na = _skin_at(xyz, xnrm, q, (x0, y0, x1, y1))
        Pb, Nb = _skin_at(xyz, xnrm, qq, (x0, y0, x1, y1))
        good = (np.linalg.norm(D, axis=1) > 0.05) & np.isfinite(Pa).all(1) & np.isfinite(Pb).all(1)
        idx = np.nonzero(m)[0]
        P2, N2 = pos[idx].copy(), nrm[idx].copy()
        # (moved by the skin's own move from q to q + D: a layer under the outermost one - skin under the cloth, a
        # fold's far side - keeps its depth instead of jumping onto the outer surface)
        P2[good] += Pb[good] - Pa[good]
        n2 = N2[good] + Nb[good] - Na[good]
        N2[good] = n2 / np.maximum(np.linalg.norm(n2, axis=1, keepdims=True), 1e-9)
        ids.append(idx); Ps.append(P2); Ns.append(N2)
    if not ids:
        return None
    return np.concatenate(ids), np.concatenate(Ps), np.concatenate(Ns)


def body_state(d: Path, st: dict, base: Path, view: str, M=None, width=2048):
    """a body skin for base.glb, built once (cached by the model's time and the landmarks that cut it); None when the
    landmarks are missing or the part was not found -> (params, faces, xyz, nrm, M)"""
    m3 = st.get("marks3d") or {}
    if M is not None and not m3:
        m3 = guess_marks3d(M)
    mk = hashlib.md5(json.dumps({k: m3.get(k) for k in BODY_MARKS}, sort_keys=True).encode()).hexdigest()[:10]
    key = f"{base.stat().st_mtime_ns}/{mk}"
    bk = (st.get("skin") or {}).get(view)
    if bk and bk.get("key") == key and (d / f"{view}_xyz.npy").exists():
        faces = {n: np.load(d / f"{view}_faces_{n}.npy") for n in bk["params"]["parts"]}
        return bk["params"], faces, np.load(d / f"{view}_xyz.npy"), np.load(d / f"{view}_nrm.npy"), M
    M = M or load(base)
    if not m3:
        m3 = guess_marks3d(M)
    cut = body_cut(M, m3)
    lay = body_layout(M, cut, view, width) if cut else None
    if not lay:
        return None
    prm, faces = lay
    xyz, nrm = body_build(M, prm, faces)
    np.save(d / f"{view}_xyz.npy", xyz); np.save(d / f"{view}_nrm.npy", nrm)
    for n, f_ in faces.items():
        np.save(d / f"{view}_faces_{n}.npy", f_)
    body_guide(xyz, nrm, prm).save(d / f"{view}_guide.png")
    st.setdefault("skin", {})[view] = {"key": key, "params": prm}
    save_state(d, st)
    return prm, faces, xyz, nrm, M


# ------------------------------------------------------------------ landmarks: named pins whose model end is a 3D point
# For characters: ear tips, ear holes, elbows, hands (the palm's middle), knees; L = the model's own left (+X). The model
# point lives in 3D (one for every view: an ear tip marked once lands in the front AND the side picture - the ear fitted
# in two planes); the picture point is per view. A side view takes only its own side's marks (the far ear is hidden).
MARK_PARTS = [("ear_tip", "surface"), ("ear_hole", "surface"), ("elbow", "joint"), ("hand", "joint"), ("knee", "joint")]
MARK_NAMES = [f"{p}_{s}" for p, _ in MARK_PARTS for s in ("L", "R")]
MARK_KIND = {f"{p}_{s}": k for p, k in MARK_PARTS for s in ("L", "R")}


def mirror_name(n: str) -> str:
    return n[:-1] + ("R" if n.endswith("L") else "L")


def mark_in_view(n: str, view: str) -> bool:
    """front / back: all; a side view: its own side's ears and knee (a T-posed arm points at the camera there)"""
    if view in ("front", "back"):
        return True
    return (view == "left") == n.endswith("_L") and not n.startswith(("elbow", "hand"))


def guess_marks3d(M) -> dict:
    """first guesses on a T / A-posed character facing +Z: the hand = a slice across the arm a little in from its
    farthest point, the elbow 42 % of the way from the torso's edge to that point, the knee a slice across each leg at
    27 % of the height (joints: the slice's middle, inside the limb); the ear tip = the farthest-out point above the arms
    and the neck, the ear hole = the middle of the ear's outer part (surface marks)"""
    V = M["V"]
    ymin, ymax = V[:, 1].min(), V[:, 1].max()
    h = ymax - ymin
    out = {}
    for s, sg in (("L", 1.0), ("R", -1.0)):
        side = V[sg * V[:, 0] > 0.02 * h]
        if len(side) < 50:
            continue
        tip = side[np.argmax(sg * side[:, 0])]
        arm_y = tip[1]

        def mid(sel):
            pts = side[sel]
            return (pts.min(0) + pts.max(0)) / 2 if len(pts) >= 3 else None

        hx = tip[0] - sg * 0.06 * h
        hand = mid((np.abs(side[:, 0] - hx) < 0.012 * h) & (np.abs(side[:, 1] - arm_y) < 0.12 * h))
        chest = side[(side[:, 1] < arm_y - 0.08 * h) & (side[:, 1] > arm_y - 0.16 * h) & (sg * side[:, 0] < 0.5 * sg * tip[0])]
        sh_x = chest[np.argmax(sg * chest[:, 0]), 0] if len(chest) else 0.3 * tip[0]
        ex = sh_x + 0.42 * (tip[0] - sh_x)
        elbow = mid((np.abs(side[:, 0] - ex) < 0.012 * h) & (np.abs(side[:, 1] - arm_y) < 0.14 * h))
        ky = ymin + 0.27 * h
        knee = mid((np.abs(side[:, 1] - ky) < 0.012 * h) & (sg * side[:, 0] < 0.25 * h))
        head = side[side[:, 1] > max(arm_y + 0.06 * h, ymin + 0.72 * h)]
        for n, p in (("hand", hand), ("elbow", elbow), ("knee", knee)):
            if p is not None:
                out[f"{n}_{s}"] = p
        if len(head) >= 10:
            et = head[np.argmax(sg * head[:, 0])]
            out[f"ear_tip_{s}"] = et
            ear = head[sg * head[:, 0] > 0.6 * sg * et[0]]
            out[f"ear_hole_{s}"] = ear.mean(0) if len(ear) >= 10 else et
    return {k: [round(float(x), 5) for x in v] for k, v in out.items()}


def unproject(M, view, cam, x, y, W, H, kind="surface"):
    """a picture pixel of that view back onto the model: the nearest surface under it (surface marks) or the middle
    between the nearest and the farthest (joint marks: inside the limb). None off the model."""
    d, r, u = view_axes(view)
    s, tx, ty = cam
    P2, z = project_pts(M["V"], view, cam)
    _, _, zn = raster(P2, M["F"], W, H, z=z)
    _, _, zf = raster(P2, M["F"], W, H, z=-z)
    ok = np.isfinite(zn)
    ix, iy = int(np.clip(x, 0, W - 1)), int(np.clip(y, 0, H - 1))
    if not ok[iy, ix]:   # (a click just off the edge: the nearest pixel of the model within 8 px)
        ys, xs = np.nonzero(ok[max(0, iy - 8):iy + 9, max(0, ix - 8):ix + 9])
        if not len(xs):
            return None
        k = np.argmin((xs + max(0, ix - 8) - ix) ** 2 + (ys + max(0, iy - 8) - iy) ** 2)
        ix, iy = xs[k] + max(0, ix - 8), ys[k] + max(0, iy - 8)
    near, far = zn[iy, ix], -zf[iy, ix]
    depth = near if kind == "surface" else (near + far) / 2
    return (r * ((x - tx) / s) + u * (-(y - ty) / s) + d * depth).tolist()


def mark_model_2d(m3, view, cam):
    (xy,), _ = project_pts(np.asarray([m3], float), view, cam)
    return [round(float(xy[0]), 2), round(float(xy[1]), 2)]


def view_pins(st: dict, cams: dict, pics: dict, mirror: bool, sizes: dict) -> dict:
    """every view's pins for the projection: the free ones plus the landmarks (picture point -> the 3D point drawn
    from that view's camera); a mirrored side (no picture of its own) takes the other side's, mirrored with its picture"""
    out = {}
    m3 = st.get("marks3d") or {}
    for v in ORDER:
        if v in pics:
            ps = [tuple(p) for p in (st.get("pins") or {}).get(v, [])]
            for n, sp in ((st.get("marks") or {}).get(v) or {}).items():
                if n in m3 and mark_in_view(n, v) and v in cams:
                    dx, dy = mark_model_2d(m3[n], v, cams[v])
                    ps.append((sp[0], sp[1], dx, dy))
            out[v] = ps
        elif mirror and v in ("left", "right") and ({"left", "right"} - {v}) & set(pics) and v in cams:
            o = "left" if v == "right" else "right"
            Wp = sizes[o][0]
            ps = [(Wp - a, b, Wp - c, e) for a, b, c, e in (st.get("pins") or {}).get(o, [])]
            for n, sp in ((st.get("marks") or {}).get(o) or {}).items():
                mn = mirror_name(n)
                if mn in m3 and mark_in_view(mn, v):
                    dx, dy = mark_model_2d(m3[mn], v, cams[v])
                    ps.append((Wp - sp[0], sp[1], dx, dy))
            out[v] = ps
    return out


def _marks3d(st: dict, base: Path, M=None, cat=""):
    if st.get("marks3d") is None and cat in ("character", "creature"):
        st["marks3d"] = guess_marks3d(M or load(base))
    return st.get("marks3d") or {}


def guess_pic_ear(alpha, model_xy, mid_x, sg_img, H):
    """an ear tip on a front / back picture: the cut's farthest point outward in a band round the model's ear tip"""
    band = int(0.05 * H)
    y0, y1 = max(0, int(model_xy[1]) - band), min(alpha.shape[0], int(model_xy[1]) + band)
    m = alpha[y0:y1] > 0.5
    ys, xs = np.nonzero(m)
    if not len(xs):
        return None
    sel = (xs - mid_x) * sg_img > 0
    if not sel.any():
        return None
    xs, ys = xs[sel], ys[sel]
    k = np.argmax((xs - mid_x) * sg_img)
    return [float(xs[k]), float(ys[k] + y0)]


def marks_for_editor(st, view, cam, pic, W, H, mid):
    """the landmarks of a view for the editor: the model point (3D drawn from the camera), the picture point (set, or a
    first guess: the ear tips on front / back pictures from the cut's outline, the rest where the model point is)"""
    m3 = st.get("marks3d") or {}
    if not m3:
        return []
    set_ = (st.get("marks") or {}).get(view) or {}
    alpha = None
    out = []
    for n in MARK_NAMES:
        if n not in m3 or not mark_in_view(n, view):
            continue
        mxy = mark_model_2d(m3[n], view, cam)
        p, guess = set_.get(n), False
        if p is None:
            guess = True
            p = mxy
            if n.startswith("ear_tip") and view in ("front", "back") and mid is not None:
                if alpha is None:
                    alpha = pic_alpha(pic)[1]
                # (front: the model's +X shows on the image's right; back: on its left)
                sg_img = (1 if n.endswith("_L") else -1) * (1 if view == "front" else -1)
                p = guess_pic_ear(alpha, mxy, mid, sg_img, H) or mxy
        out.append({"name": n, "kind": MARK_KIND[n], "model": mxy, "pic": [round(float(p[0]), 2), round(float(p[1]), 2)],
                    "set": not guess})
    return out


def set_marks(cat: str, stem: str, cfg: dict, view: str, marks: dict) -> dict:
    """the picture points of a view's landmarks ({name: [x, y]}; the ones not given are left as first guesses)"""
    d = improve_dir(cfg, cat, stem)
    st = load_state(d)
    st.setdefault("marks", {})[view] = {n: [round(float(p[0]), 2), round(float(p[1]), 2)] for n, p in (marks or {}).items()
                                        if n in MARK_KIND}
    save_state(d, st)
    return st


def set_mark3d(cat: str, stem: str, cfg: dict, draft_dir: Path, view: str, name: str, x: float, y: float,
               mirror: bool = False) -> dict:
    """a landmark's model point moved in one view (the pixel put back onto the model); mirrored to the other side's
    mark (x -> -x) when asked. -> the view's editor data again"""
    d = improve_dir(cfg, cat, stem)
    st = load_state(d)
    info_p = Path(draft_dir) / f"{stem}.json"
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.exists() else {}
    pics = pictures(st, info)
    base = d / "before.glb"
    cam, _, M = fitted(d, st, base, view, pics[view]["path"])
    M = M or load(base)
    W, H = Image.open(pics[view]["path"]).size
    p = unproject(M, view, cam, x, y, W, H, MARK_KIND.get(name, "surface"))
    if p is not None:
        st = load_state(d)
        m3 = st.setdefault("marks3d", {})
        m3[name] = [round(float(c), 5) for c in p]
        if mirror:
            m3[mirror_name(name)] = [round(-float(p[0]), 5), round(float(p[1]), 5), round(float(p[2]), 5)]
        save_state(d, st)
    return align(cat, stem, cfg, draft_dir, view)


def align(cat: str, stem: str, cfg: dict, draft_dir: Path, view: str) -> dict:
    """what the pins editor shows for a view: the picture, the model drawn from the fitted camera at the picture's size
    (PNG), the model's middle line in the picture (for mirrored pins: front / back), the pins so far. view "skin_head":
    the head's skin laid flat - its relief as the ground, the pictures as the projection lays them on it"""
    glb = Path(draft_dir) / f"{stem}.glb"
    info_p = Path(draft_dir) / f"{stem}.json"
    info = json.loads(info_p.read_text(encoding="utf-8")) if info_p.exists() else {}
    d = improve_dir(cfg, cat, stem)
    base = d / "before.glb"
    if not base.exists():
        shutil.copy2(glb, base)
    st = load_state(d)
    pics = pictures(st, info)
    if view in ("skin_head", "skin_ears", *BODY_SKINS):
        if not pics:
            return {"ok": False, "view": view}
        cams, M = {}, None
        for v, x in pics.items():
            cams[v], _, M = fitted(d, st, base, v, x["path"], M)
        mirror = (st.get("options") or {}).get("mirror", (info.get("category") or cat) == "character")
        use = {v: x["path"] for v, x in pics.items()}
        if mirror and "left" in use and "right" not in use:
            cams["right"], _, M = fitted(d, st, base, "right", use["left"], M, flip=True); use["right"] = ("flip", use["left"])
        if mirror and "right" in use and "left" not in use:
            cams["left"], _, M = fitted(d, st, base, "left", use["right"], M, flip=True); use["left"] = ("flip", use["right"])
        M = M or load(base)
        _marks3d(st, base, M, info.get("category") or cat)
        save_state(d, st)
        if view == "skin_head":
            sp, xyz, nrm, M = skin_state(d, st, base, M)
        elif view == "skin_ears":
            ep = ears_state(d, st, base, M)
            if not ep:
                return {"ok": False, "view": view, "error": "no ears found"}
            sp, _, xyz, nrm, M = ep
            M = M or load(base)
        else:
            bp = body_state(d, st, base, view, M)
            if not bp:
                return {"ok": False, "view": view, "error": "no body part found"}
            sp, _, xyz, nrm, M = bp
            M = M or load(base)
        st = load_state(d)
        sizes = {v: Image.open(x["path"]).size for v, x in pics.items()}
        vp = view_pins(st, cams, {v: x["path"] for v, x in pics.items()}, bool(mirror), sizes)
        skin_pictures(M, xyz, nrm, sp, use, cams, vp).save(d / f"{view}_pics.png")
        return {"ok": True, "view": view, "picture": str(d / f"{view}_pics.png"), "model": str(d / f"{view}_guide.png"),
                "size": [sp["W"], sp["H"]], "cam": None, "iou": None, "mid_x": sp["W"] / 2,
                "pins": (st.get("pins") or {}).get(view, []), "kind": "skin", "marks": []}
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
    cat_ = info.get("category") or cat
    if st.get("marks3d") is None and cat_ in ("character", "creature"):
        _marks3d(st, base, M, cat_)
        save_state(d, st)
    return {"ok": True, "view": view, "picture": pic, "model": str(png), "size": [W, H], "cam": list(cam),
            "iou": iou, "mid_x": mid, "pins": (st.get("pins") or {}).get(view, []), "kind": pics[view]["kind"],
            "marks": marks_for_editor(st, view, cam, pic, W, H, mid)}


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
            "marks": {v: len(m) for v, m in (st.get("marks") or {}).items()},
            "options": st.get("options") or defaults(info, pics, has_raw), "defaults": defaults(info, pics, has_raw),
            "has_raw": has_raw, "improved": info.get("improved"), "can_undo": (d / "before.glb").exists(),
            "before": str(d / "before.glb") if (d / "before.glb").exists() else None,
            "fit": {v: x.get("iou") for v, x in (st.get("cams") or {}).items()}}
