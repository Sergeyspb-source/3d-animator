"""Model defects mended in a GLB itself (numpy, no Blender: the clips, skins and pictures stay byte for byte).

fix_normals: the vertex normals that point against the skin's own faces turned back. Tripo leaves some (the nurgl:
52 faces of 45 393): lit from the wrong side they show as dark or light squares on the skin, whatever the texture.
Each vertex's normal is checked against the faces round its position (their windings, area-weighted, across the
UV seams' split vertices); where it points away from them (dot < 0) it takes theirs. Everything else is left exact.
"""
import json
import struct
from pathlib import Path

import numpy as np

_CT = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_NC = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}


def _read(path: Path):
    raw = Path(path).read_bytes()
    magic, _ver, _total = struct.unpack_from("<III", raw, 0)
    if magic != 0x46546C67:
        raise RuntimeError(f"not a GLB: {path}")
    off, js, bin_ = 12, None, b""
    while off < len(raw):
        ln, kind = struct.unpack_from("<II", raw, off)
        chunk = raw[off + 8: off + 8 + ln]
        if kind == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif kind == 0x004E4942:
            bin_ = chunk
        off += 8 + ln
    return js, bytearray(bin_)


def _write(path: Path, js: dict, bin_: bytes):
    jb = json.dumps(js, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    jb += b" " * (-len(jb) % 4)
    bin_ = bytes(bin_) + b"\0" * (-len(bin_) % 4)
    body = struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(bin_), 0x004E4942) + bin_
    Path(path).write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)


def _view(js, bin_, ai):
    """(array view of the accessor's data, its byte positions) - tightly packed or strided"""
    a = js["accessors"][ai]
    bv = js["bufferViews"][a["bufferView"]]
    dt = np.dtype(_CT[a["componentType"]])
    n = _NC[a["type"]]
    start = bv.get("byteOffset", 0) + a.get("byteOffset", 0)
    stride = bv.get("byteStride") or dt.itemsize * n
    idx = start + np.arange(a["count"])[:, None] * stride + np.arange(n)[None, :] * dt.itemsize
    flat = np.frombuffer(bytes(bin_), dtype=np.uint8)
    data = flat[idx[..., None] + np.arange(dt.itemsize)].copy().view(dt).reshape(a["count"], n)
    return data, idx


def fix_normals(src: Path, out: Path | None = None, mode: str = "all", angle: float = 0.0) -> int:
    """The vertex normals made again from the skin's faces: mode "all" - every vertex (smooth everywhere, across the
    UV seams' split vertices: no seam shows), "off" - only those further than `angle` degrees from the faces round
    them (90 = only the ones pointing away). Writes `out` (default: in place) only when anything changed. Returns how
    many vertices changed."""
    js, bin_ = _read(src)
    fixed = 0
    for mesh in js.get("meshes", []):
        for prim in mesh.get("primitives", []):
            at = prim.get("attributes", {})
            if prim.get("mode", 4) != 4 or "NORMAL" not in at or "POSITION" not in at or "indices" not in prim:
                continue
            if js["accessors"][at["NORMAL"]].get("componentType") != 5126 or "sparse" in js["accessors"][at["NORMAL"]]:
                continue
            pos, _ = _view(js, bin_, at["POSITION"])
            nrm, nidx = _view(js, bin_, at["NORMAL"])
            tri = _view(js, bin_, prim["indices"])[0].reshape(-1, 3).astype(np.int64)
            pos = pos.astype(np.float64)
            fn = np.cross(pos[tri[:, 1]] - pos[tri[:, 0]], pos[tri[:, 2]] - pos[tri[:, 0]])   # (area-weighted)
            # the same position = one point of the skin (a seam's split vertices together)
            size = float(np.ptp(pos, axis=0).max()) or 1.0
            keys = np.round(pos / (size * 1e-5)).astype(np.int64)
            _, grp = np.unique(keys, axis=0, return_inverse=True)
            grp = grp.reshape(-1)
            acc = np.zeros((grp.max() + 1, 3))
            for c in range(3):
                np.add.at(acc, grp[tri[:, c]], fn)
            want = acc[grp]
            ln = np.linalg.norm(want, axis=1)
            ok = ln > 1e-20
            want[ok] /= ln[ok, None]
            cosv = np.einsum("ij,ij->i", nrm.astype(np.float64), want)
            if mode == "all":   # (changed: those not already within a hair of it)
                bad = ok & (cosv < 0.99999)
            else:
                bad = ok & (cosv < np.cos(np.radians(angle or 90.0)))
            if not bad.any():
                continue
            nrm[bad] = want[bad].astype(np.float32)
            raw = nrm.astype(np.float32).view(np.uint8).reshape(len(nrm), 3, 4)
            arr = np.frombuffer(bytes(bin_), dtype=np.uint8).copy()
            arr[nidx[bad][..., None] + np.arange(4)] = raw[bad]
            bin_ = bytearray(arr.tobytes())
            fixed += int(bad.sum())
    if fixed:
        _write(out or src, js, bin_)
    return fixed


def count_bad_normals(src: Path, angle: float = 45.0) -> int:
    """How many vertices stand further than `angle` degrees from the faces round them (nothing written)."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        return fix_normals(src, Path(d) / "x.glb", mode="off", angle=angle)


# ------------------------------------------------------------------ holes
def _relayout(js, bin_, new_data: dict) -> bytes:
    """the binary chunk laid out again view by view (4-byte aligned), some views' data replaced"""
    out = bytearray()
    for vi, bv in enumerate(js.get("bufferViews", [])):
        data = new_data.get(vi)
        if data is None:
            s = bv.get("byteOffset", 0)
            data = bytes(bin_[s: s + bv["byteLength"]])
        while len(out) % 4:
            out.append(0)
        bv["byteOffset"] = len(out)
        bv["byteLength"] = len(data)
        bv["buffer"] = 0
        out += data
    while len(out) % 4:
        out.append(0)
    js["buffers"] = [{"byteLength": len(out)}]
    return bytes(out)


def _ear_clip(P2):
    """triangles (index triples into P2, in its order's orientation) of a simple polygon; a fan if clipping stalls"""
    n = len(P2)
    idx = list(range(n))
    area = sum(P2[i][0] * P2[(i + 1) % n][1] - P2[(i + 1) % n][0] * P2[i][1] for i in range(n))
    sgn = 1.0 if area >= 0 else -1.0
    tris = []

    def inside(p, a, b, c):
        d = lambda u, v, w: (u[0] - w[0]) * (v[1] - w[1]) - (v[0] - w[0]) * (u[1] - w[1])  # noqa: E731
        s1, s2, s3 = d(p, a, b), d(p, b, c), d(p, c, a)
        return not (((s1 < 0) or (s2 < 0) or (s3 < 0)) and ((s1 > 0) or (s2 > 0) or (s3 > 0)))
    guard = 0
    while len(idx) > 3 and guard < 4 * n:
        guard += 1
        for k in range(len(idx)):
            i0, i1, i2 = idx[k - 1], idx[k], idx[(k + 1) % len(idx)]
            a, b, c = P2[i0], P2[i1], P2[i2]
            cr = (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])
            if cr * sgn <= 1e-15:
                continue
            if any(inside(P2[j], a, b, c) for j in idx if j not in (i0, i1, i2)):
                continue
            tris.append((i0, i1, i2))
            idx.pop(k)
            break
        else:
            break
    if len(idx) == 3:
        tris.append(tuple(idx))
    elif len(idx) > 3:   # (a fan for what is left)
        tris += [(idx[0], idx[k], idx[k + 1]) for k in range(1, len(idx) - 1)]
    return tris


def fill_holes(src: Path, out: Path | None = None, max_edges: int = 40, max_extent: float = 0.03) -> tuple[int, int]:
    """Small holes in the skin closed (Tripo leaves some: you see through them, dark or light squares). Each hole -
    a loop of boundary edges (by position: a seam's split vertices are one point) at most `max_edges` long and
    `max_extent` of the model's size across - is closed by triangles over its own edge's vertices: their UVs (the
    texture's colour round the hole), skin weights and normals come with them, nothing new is added. Holes next to
    a creature's eyes (their openings, cut on purpose) are left. Writes only when anything was closed. Returns (holes
    closed, triangles added)."""
    from collections import defaultdict
    js, bin_ = _read(src)
    # the eyes' openings: near an eye's or a socket's mesh
    eye_pts = []
    for node in js.get("nodes", []):
        if str(node.get("name", "")).startswith(("Eye_", "EyeSocket_", "EyeLid_")) and "mesh" in node:
            for prim in js["meshes"][node["mesh"]].get("primitives", []):
                eye_pts.append(_view(js, bin_, prim["attributes"]["POSITION"])[0].astype(np.float64))
    eye_pts = np.concatenate(eye_pts) if eye_pts else np.zeros((0, 3))
    new_views, holes, added = {}, 0, 0
    for mesh in js.get("meshes", []):
        for prim in mesh.get("primitives", []):
            at = prim.get("attributes", {})
            if prim.get("mode", 4) != 4 or "POSITION" not in at or "indices" not in prim:
                continue
            acc = js["accessors"][prim["indices"]]
            pos = _view(js, bin_, at["POSITION"])[0].astype(np.float64)
            tri = _view(js, bin_, prim["indices"])[0].reshape(-1, 3).astype(np.int64)
            size = float(np.ptp(pos, axis=0).max()) or 1.0
            keys = np.round(pos / (size * 1e-5)).astype(np.int64)
            _, grp = np.unique(keys, axis=0, return_inverse=True)
            grp = grp.reshape(-1)
            G = grp[tri]
            cnt = defaultdict(int)
            for a, b, c in G:
                for u, v in ((a, b), (b, c), (c, a)):
                    cnt[(min(u, v), max(u, v))] += 1
            # the boundary's directed edges as the faces walk them; the patch walks them the other way
            nxt, rep = {}, {}
            for t, (a, b, c) in zip(tri, G):
                for (u, v), (iu, iv) in (((a, b), (t[0], t[1])), ((b, c), (t[1], t[2])), ((c, a), (t[2], t[0]))):
                    if cnt[(min(u, v), max(u, v))] == 1:
                        nxt[v] = u   # (the patch: v -> u)
                        rep.setdefault(u, iu); rep.setdefault(v, iv)
            seen, newtri = set(), []
            for s in list(nxt):
                if s in seen:
                    continue
                loop, x = [], s
                while x not in seen and x in nxt and len(loop) <= max_edges + 1:
                    seen.add(x); loop.append(x); x = nxt[x]
                if x != s or len(loop) < 3 or len(loop) > max_edges:
                    continue
                P = np.array([pos[rep[g]] for g in loop])
                if float(np.ptp(P, axis=0).max()) > max_extent * size:
                    continue
                if len(eye_pts):
                    c0 = P.mean(axis=0)
                    if np.min(np.linalg.norm(eye_pts - c0, axis=1)) < 3 * float(np.ptp(P, axis=0).max()) + 1e-9:
                        continue
                # the loop's plane (its main directions), clipped there
                c0 = P.mean(axis=0)
                _, _, vt = np.linalg.svd(P - c0)
                P2 = (P - c0) @ vt[:2].T
                for i, j, k in _ear_clip(P2.tolist()):
                    newtri.append((rep[loop[i]], rep[loop[j]], rep[loop[k]]))
                holes += 1
            if not newtri:
                continue
            # the patch's winding: as the faces round it (each patch edge v->u against the face's u->v)
            allt = np.concatenate([tri, np.array(newtri, dtype=np.int64)])
            dt = np.dtype(_CT[acc["componentType"]])
            if allt.max() >= np.iinfo(dt).max:
                continue
            new_views[acc["bufferView"]] = allt.astype(dt).tobytes()
            acc["count"] = int(allt.size)
            acc.pop("byteOffset", None)
            added += len(newtri)
    if added:
        # (an index view shared with something else would be cut wrong: each primitive's own, as exporters make them)
        _write(out or src, js, _relayout(js, bin_, new_views))
    return holes, added
