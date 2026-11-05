"""Hand corrections of a character's shape keys (the face's expressions: jawOpen, mouthSmile, the brows...), made with
the brush in the markup editor's «Pose» mode and kept next to the character, so a rebuilt skeleton gets them again.

    <stem>_face_edits.json   {"version": 1, "keys": {key: [{"mesh": name, "prim": p, "v": [[i, bx, by, bz, ox, oy, oz], ...]}]},
                              "applied": {"size": ..., "mtime_ns": ...}}
    <rigged>.noedit.glb      the model as the build made it (the edits are always laid on this one)

Painted over textures («Поза» → «🖌 Текстура»): a layer per image, <stem>_tex/<image name>.png (RGBA, see-through
where not painted), laid over the model's image of that name (its base colour: the skin, the face mask's own) on the
same model as built, as the shape edits are.

A vertex edit: its index in the primitive, where it stands at rest (glTF, the mesh's own space; to find it again
after a rebuild) and the offset added to the key's displacement there. The key is written back as a sparse accessor
(only the points it moves), its normals' displacement corrected by how the edit turns the surface, so the light
falls as on the model (Blender's export keeps the face's keys sparse too). Plain numpy; no Blender.
"""
import json
import shutil
import struct
from pathlib import Path

import numpy as np

FLOAT, U32 = 5126, 5125
_NP = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}
_N = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4, "MAT4": 16}


def read_glb(path):
    b = Path(path).read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    rest = b[20 + n:]
    bin_ = b""
    if len(rest) >= 8:
        ln, kind = struct.unpack("<II", rest[:8])
        if kind == 0x004E4942:
            bin_ = rest[8:8 + ln]
    return j, bytearray(bin_)


def write_glb(path, j, bin_):
    while len(bin_) % 4:
        bin_ += b"\0"
    j["buffers"][0]["byteLength"] = len(bin_)
    js = json.dumps(j, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + struct.pack("<II", len(bin_), 0x004E4942) + bytes(bin_)
    tmp = Path(str(path) + ".tmp")
    tmp.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
    tmp.replace(path)


def _view(j, bin_, bv, offset, ctype, comps, count):
    v = j["bufferViews"][bv]
    dt = np.dtype(_NP[ctype])
    start = v.get("byteOffset", 0) + offset
    stride = v.get("byteStride") or dt.itemsize * comps
    if stride == dt.itemsize * comps:
        return np.frombuffer(bytes(bin_[start:start + stride * count]), dt).reshape(count, comps).copy()
    raw = np.frombuffer(bytes(bin_[start:start + stride * count]), np.uint8).reshape(count, stride)
    return raw[:, :dt.itemsize * comps].copy().view(dt).reshape(count, comps)


def accessor(j, bin_, idx):
    """The accessor's data (count x components, float), sparse ones expanded."""
    a = j["accessors"][idx]
    comps, count = _N[a["type"]], a["count"]
    out = (_view(j, bin_, a["bufferView"], a.get("byteOffset", 0), a["componentType"], comps, count).astype(np.float64)
           if "bufferView" in a else np.zeros((count, comps)))
    sp = a.get("sparse")
    if sp:
        k = sp["count"]
        ii = _view(j, bin_, sp["indices"]["bufferView"], sp["indices"].get("byteOffset", 0), sp["indices"]["componentType"], 1, k)[:, 0]
        vv = _view(j, bin_, sp["values"]["bufferView"], sp["values"].get("byteOffset", 0), a["componentType"], comps, k)
        out[ii.astype(np.int64)] = vv
    return out


def _append(j, bin_, data: bytes):
    while len(bin_) % 4:
        bin_ += b"\0"
    j["bufferViews"].append({"buffer": 0, "byteOffset": len(bin_), "byteLength": len(data)})
    bin_ += data
    return len(j["bufferViews"]) - 1


def sparse_accessor(j, bin_, arr, eps=1e-9):
    """A new VEC3 float accessor holding arr as a sparse one (the rows that are not zero); its index."""
    nz = np.nonzero(np.abs(arr).max(axis=1) > eps)[0].astype(np.uint32)
    a = {"componentType": FLOAT, "count": int(arr.shape[0]), "type": "VEC3"}
    if len(nz):
        vals = arr[nz].astype(np.float32)
        a["sparse"] = {"count": int(len(nz)),
                       "indices": {"bufferView": _append(j, bin_, nz.tobytes()), "componentType": U32},
                       "values": {"bufferView": _append(j, bin_, vals.tobytes())}}
        a["min"], a["max"] = [float(x) for x in np.minimum(vals.min(axis=0), 0)], [float(x) for x in np.maximum(vals.max(axis=0), 0)]
    else:
        a["min"], a["max"] = [0.0, 0.0, 0.0], [0.0, 0.0, 0.0]
    j["accessors"].append(a)
    return len(j["accessors"]) - 1


def vertex_normals(pos, tris):
    """Area-weighted vertex normals of a triangle list (unit; zero where a vertex has no triangle)."""
    fn = np.cross(pos[tris[:, 1]] - pos[tris[:, 0]], pos[tris[:, 2]] - pos[tris[:, 0]])
    n = np.zeros_like(pos)
    for k in range(3):
        np.add.at(n, tris[:, k], fn)
    ln = np.linalg.norm(n, axis=1, keepdims=True)
    return np.divide(n, ln, out=np.zeros_like(n), where=ln > 1e-20)


def _tris(j, bin_, prim, count):
    if "indices" in prim:
        return accessor(j, bin_, prim["indices"])[:, 0].astype(np.int64).reshape(-1, 3)
    return np.arange(count, dtype=np.int64).reshape(-1, 3)


def _find(base, pts, idx, tol):
    """For each edited vertex: its index again (the same one if it is still there, else the nearest point within tol;
    -1 when none). base: the primitive's rest positions now."""
    out = np.array(idx, dtype=np.int64)
    ok = (out >= 0) & (out < len(base))
    good = np.zeros(len(out), bool)
    good[ok] = np.linalg.norm(base[out[ok]] - pts[ok], axis=1) < tol * 0.01
    if good.all():
        return out
    try:
        from scipy.spatial import cKDTree
        d, nn = cKDTree(base).query(pts[~good], distance_upper_bound=tol)
        out[~good] = np.where(np.isfinite(d), nn, -1)
    except ImportError:   # no scipy: only the vertices still at their index
        out[~good] = -1
    return out


def _paint(j, bin_, tex_dir: Path | None) -> int:
    """Every painted layer of tex_dir laid over the GLB's image of its name (the new picture appended to the buffer,
    the image pointed at it; the format kept). The count of images painted."""
    if not tex_dir or not tex_dir.is_dir():
        return 0
    from io import BytesIO
    from PIL import Image
    n = 0
    for im in j.get("images", []):
        layer = tex_dir / f"{_safe(im.get('name') or '')}.png"
        if "bufferView" not in im or not layer.exists():
            continue
        v = j["bufferViews"][im["bufferView"]]
        raw = bytes(bin_[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]])
        pic = Image.open(BytesIO(raw)).convert("RGBA")
        top = Image.open(layer).convert("RGBA")
        if top.size != pic.size:
            top = top.resize(pic.size, Image.BILINEAR)
        out = Image.alpha_composite(pic, top)
        buf = BytesIO()
        if im.get("mimeType") == "image/jpeg":
            out.convert("RGB").save(buf, "JPEG", quality=95)
        else:
            out.save(buf, "PNG", optimize=False)
        im["bufferView"] = _append(j, bin_, buf.getvalue())
        n += 1
    return n


def _safe(name: str) -> str:
    import re
    return re.sub(r"[^\w.+-]+", "_", name).strip("_") or "image"


def apply(base_glb, out_glb, edits, tex_dir: Path | None = None) -> dict:
    """Lay every key's edits (and the painted layers of tex_dir) on base_glb and write out_glb.
    {"points": laid, "missed": not found again, "painted": images}."""
    j, bin_ = read_glb(base_glb)
    laid = missed = 0
    meshes = {m.get("name"): (mi, m) for mi, m in enumerate(j.get("meshes", []))}
    built = {}   # (mesh, primitive) -> its rest places as built: every edit finds its points by them
    keys = edits.get("keys") or {}
    for key in sorted(keys, key=lambda k: k != BASIS):   # the face at rest first: the keys' edits go on top of it
        for g in keys[key]:
            hit = meshes.get(g.get("mesh"))
            if hit is None:
                missed += len(g.get("v") or [])
                continue
            mi, m = hit
            names = (m.get("extras") or {}).get("targetNames") or []
            if (key != BASIS and key not in names) or g.get("prim", 0) >= len(m["primitives"]):
                missed += len(g.get("v") or [])
                continue
            prim = m["primitives"][g["prim"]]
            base = accessor(j, bin_, prim["attributes"]["POSITION"])
            b0 = built.setdefault((mi, g["prim"]), base.copy())
            rows = np.array(g["v"], dtype=np.float64).reshape(-1, 7)
            if not len(rows):
                continue
            size = float(np.linalg.norm(b0.max(axis=0) - b0.min(axis=0))) or 1.0
            where = _find(b0, rows[:, 1:4], rows[:, 0].astype(np.int64), 0.002 * size)
            use = where >= 0
            missed += int((~use).sum())
            laid += int(use.sum())
            if key == BASIS:
                _rest(j, bin_, prim, base, where[use], rows[use, 4:7])
                continue
            t = names.index(key)
            tg = prim["targets"][t]
            dpos = accessor(j, bin_, tg["POSITION"])
            new = dpos.copy()
            np.add.at(new, where[use], rows[use, 4:7])
            if "NORMAL" in tg:   # the light: the normals' displacement turned as the edit turns the surface
                tris = _tris(j, bin_, prim, len(base))
                dn = accessor(j, bin_, tg["NORMAL"])
                dn += vertex_normals(base + new, tris) - vertex_normals(base + dpos, tris)
                tg["NORMAL"] = sparse_accessor(j, bin_, dn, 1e-6)
            tg["POSITION"] = sparse_accessor(j, bin_, new)
    mesh = mesh_apply(j, bin_, edits.get("mesh")) if edits.get("mesh") else {"cut": 0, "filled": 0, "missed": 0}
    painted = _paint(j, bin_, tex_dir)
    write_glb(out_glb, j, bin_)
    return {"points": laid, "missed": missed, "painted": painted, "mesh": mesh}


BASIS = "__basis"   # the edits of the face at rest (its base shape), under this name among the keys


# ---------------------------------------------------------------- the mesh by hand («Поза» → «▦ Сетка»): torn flaps
# taken away (their triangles), holes patched (a new primitive of its own colour over the hole's rim, its points copied
# from the rim's: weights, keys, normals). Kept by place, so a rebuilt model gets them again.
def raw_accessor(j, bin_, idx):
    """The accessor's data in its own component type (dense; sparse ones expanded)."""
    a = j["accessors"][idx]
    comps, count, dt = _N[a["type"]], a["count"], _NP[a["componentType"]]
    out = _view(j, bin_, a["bufferView"], a.get("byteOffset", 0), a["componentType"], comps, count) if "bufferView" in a \
        else np.zeros((count, comps), dt)
    sp = a.get("sparse")
    if sp:
        k = sp["count"]
        ii = _view(j, bin_, sp["indices"]["bufferView"], sp["indices"].get("byteOffset", 0), sp["indices"]["componentType"], 1, k)[:, 0]
        out[ii.astype(np.int64)] = _view(j, bin_, sp["values"]["bufferView"], sp["values"].get("byteOffset", 0), a["componentType"], comps, k)
    return out


def like_accessor(j, bin_, arr, like_idx, minmax=False):
    """A new dense accessor of arr in the type of accessor like_idx."""
    a = j["accessors"][like_idx]
    arr = np.ascontiguousarray(arr.astype(_NP[a["componentType"]]))
    acc = {"bufferView": _append(j, bin_, arr.tobytes()), "componentType": a["componentType"], "count": int(len(arr)), "type": a["type"]}
    if a.get("normalized"):
        acc["normalized"] = True
    if minmax:
        acc["min"], acc["max"] = [float(x) for x in arr.min(axis=0)], [float(x) for x in arr.max(axis=0)]
    j["accessors"].append(acc)
    return len(j["accessors"]) - 1


def _near(pos, pts, tol):
    """For each point, the vertices of pos within tol (a list of index arrays)."""
    try:
        from scipy.spatial import cKDTree
        t = cKDTree(pos)
        return [np.array(x, dtype=np.int64) for x in t.query_ball_point(pts, tol)]
    except ImportError:
        return [np.nonzero(np.linalg.norm(pos - p, axis=1) < tol)[0] for p in pts]


def _mesh_cut(j, bin_, m, cuts) -> tuple[int, int]:
    """Take the triangles given by their corners' places away (every copy of such a triangle). (taken, missed)."""
    taken = missed = 0
    for c in cuts:
        if c.get("prim", 0) >= len(m["primitives"]):
            missed += len(c.get("tris") or [])
            continue
        prim = m["primitives"][c["prim"]]
        pos = accessor(j, bin_, prim["attributes"]["POSITION"])
        tris = _tris(j, bin_, prim, len(pos))
        size = float(np.linalg.norm(pos.max(axis=0) - pos.min(axis=0))) or 1.0
        pts = np.array(c.get("tris") or [], dtype=np.float64).reshape(-1, 3)
        near = _near(pos, pts, 1e-4 * size)
        at = {}   # vertex -> the corners (cut point ids) it is
        for pi, vs in enumerate(near):
            for v in vs:
                at.setdefault(int(v), set()).add(pi)
        kill = np.zeros(len(tris), bool)
        for ti, (a, b, cc) in enumerate(tris):
            sa, sb, sc = at.get(int(a)), at.get(int(b)), at.get(int(cc))
            if not (sa and sb and sc):
                continue
            for t0 in {p // 3 for p in sa}:   # a cut triangle all three of whose corners are this one's
                if {3 * t0, 3 * t0 + 1, 3 * t0 + 2} <= (sa | sb | sc) and all(any(p // 3 == t0 for p in s) for s in (sa, sb, sc)):
                    kill[ti] = True
                    break
        n_cut = len(pts) // 3
        taken += int(kill.sum())
        missed += max(0, n_cut - int(kill.sum()))
        if kill.any():
            idx = tris[~kill].reshape(-1, 1)
            prim["indices"] = like_accessor(j, bin_, idx, prim["indices"]) if "indices" in prim else \
                like_accessor(j, bin_, idx.astype(np.uint32), _u32_scalar(j))
    return taken, missed


def _u32_scalar(j):
    j["accessors"].append({"componentType": U32, "count": 0, "type": "SCALAR"})   # a pattern only (its type)
    return len(j["accessors"]) - 1


def _mesh_fill(j, bin_, m, fills) -> tuple[int, int]:
    """Every patch: a new primitive over the hole's rim (its points found by place in any primitive of the mesh and
    copied: weights, keys, uv, normals), triangles as the editor made them, a material of the patch's colour."""
    made = missed = 0
    prims = m["primitives"]
    data = []   # per primitive: positions and the size
    for prim in prims:
        p = accessor(j, bin_, prim["attributes"]["POSITION"])
        data.append(p)
    size = float(max(np.linalg.norm(p.max(axis=0) - p.min(axis=0)) for p in data)) or 1.0
    for fl in fills:
        loop = np.array(fl.get("loop") or [], dtype=np.float64).reshape(-1, 3)
        if len(loop) < 3 or not fl.get("tris"):
            missed += 1
            continue
        src = []   # (primitive, vertex) of each rim point
        for q in loop:
            best = None
            for pi, p in enumerate(data):
                d = np.linalg.norm(p - q, axis=1)
                i = int(np.argmin(d))
                if d[i] < 1e-4 * size and (best is None or d[i] < best[2]):
                    best = (pi, i, d[i])
            src.append(best)
        if any(s is None for s in src):
            missed += 1
            continue
        tpl = prims[src[0][0]]
        attrs = {}
        for name, acc in tpl["attributes"].items():
            rows = []
            for pi, vi, _ in src:
                own = prims[pi]["attributes"].get(name)
                rows.append(raw_accessor(j, bin_, own)[vi] if own is not None else raw_accessor(j, bin_, acc)[0] * 0)
            attrs[name] = like_accessor(j, bin_, np.array(rows), acc, minmax=(name == "POSITION"))
        targets = []
        for ti, tg in enumerate(tpl.get("targets", [])):
            t = {}
            for name in tg:
                rows = np.array([accessor(j, bin_, prims[pi]["targets"][ti][name])[vi] if name in prims[pi]["targets"][ti] else np.zeros(3)
                                 for pi, vi, _ in src])
                t[name] = sparse_accessor(j, bin_, rows)
            targets.append(t)
        col = [float(x) for x in (fl.get("colour") or [0.6, 0.5, 0.4])][:3]
        j.setdefault("materials", []).append({"name": "patch", "doubleSided": True,
                                              "pbrMetallicRoughness": {"baseColorFactor": col + [1.0], "metallicFactor": 0.0, "roughnessFactor": 0.75}})
        tri = np.array(fl["tris"], dtype=np.uint32).reshape(-1, 1)
        j["accessors"].append({"bufferView": _append(j, bin_, tri.tobytes()), "componentType": U32, "count": int(len(tri)), "type": "SCALAR"})
        prims.append({"attributes": attrs, "indices": len(j["accessors"]) - 1, "material": len(j["materials"]) - 1, "mode": 4,
                      **({"targets": targets} if targets else {})})
        made += 1
    return made, missed


def mesh_apply(j, bin_, mesh_edits) -> dict:
    meshes = {m.get("name"): m for m in j.get("meshes", [])}
    out = {"cut": 0, "filled": 0, "missed": 0}
    for name, ed in (mesh_edits or {}).items():
        m = meshes.get(name)
        if m is None:
            out["missed"] += len(ed.get("cut", [])) + len(ed.get("fill", []))
            continue
        t, mi = _mesh_cut(j, bin_, m, ed.get("cut", []))
        f, mf = _mesh_fill(j, bin_, m, ed.get("fill", []))
        out["cut"] += t; out["filled"] += f; out["missed"] += mi + mf
    return out


def dense_accessor(j, bin_, arr, minmax=False):
    a = {"bufferView": _append(j, bin_, arr.astype(np.float32).tobytes()), "componentType": FLOAT, "count": int(arr.shape[0]), "type": "VEC3"}
    if minmax:
        a["min"], a["max"] = [float(x) for x in arr.min(axis=0)], [float(x) for x in arr.max(axis=0)]
    j["accessors"].append(a)
    return len(j["accessors"]) - 1


def _rest(j, bin_, prim, base, idx, off):
    """The face at rest moved (an eyelid lowered over the iris): the primitive's places and normals, and every key that
    moves a point the same way made shorter by as much, so it still ends where it did (a blink closes the lowered
    lid where it closed before, not into the eyeball). A key moving it the other way keeps its length."""
    o = np.zeros_like(base)
    np.add.at(o, idx, off)
    nb = base + o
    tris = _tris(j, bin_, prim, len(base))
    for tg in prim.get("targets", []):
        d = accessor(j, bin_, tg["POSITION"])
        dot, dd = (d * o).sum(axis=1), (d * d).sum(axis=1)
        k = np.where((dot > 0) & (dd > 1e-20), np.minimum(dot / np.maximum(dd, 1e-20), 1.0), 0.0)
        if not np.any(k > 0):
            continue
        dn_ = d * (1 - k)[:, None]
        if "NORMAL" in tg:
            nd = accessor(j, bin_, tg["NORMAL"])
            nd += (vertex_normals(nb + dn_, tris) - vertex_normals(nb, tris)) - (vertex_normals(base + d, tris) - vertex_normals(base, tris))
            tg["NORMAL"] = sparse_accessor(j, bin_, nd, 1e-6)
        tg["POSITION"] = sparse_accessor(j, bin_, dn_)
    if "NORMAL" in prim["attributes"]:
        n = accessor(j, bin_, prim["attributes"]["NORMAL"]) + vertex_normals(nb, tris) - vertex_normals(base, tris)
        ln = np.linalg.norm(n, axis=1, keepdims=True)
        prim["attributes"]["NORMAL"] = dense_accessor(j, bin_, np.divide(n, ln, out=np.zeros_like(n), where=ln > 1e-12))
    prim["attributes"]["POSITION"] = dense_accessor(j, bin_, nb, minmax=True)


def key_data(glb, key) -> list:
    """[{mesh, prim, pi, pd, ni, nd}]: the key's displacement in every primitive, sparse (indices, flat values) for
    positions and normals."""
    j, bin_ = read_glb(glb)
    out = []
    for m in j.get("meshes", []):
        names = (m.get("extras") or {}).get("targetNames") or []
        if key not in names:
            continue
        t = names.index(key)
        for pi, prim in enumerate(m["primitives"]):
            tg = prim["targets"][t]
            g = {"mesh": m.get("name"), "prim": pi}
            for a, (ki, kd) in (("POSITION", ("pi", "pd")), ("NORMAL", ("ni", "nd"))):
                if a in tg:
                    d = accessor(j, bin_, tg[a])
                    nz = np.nonzero(np.abs(d).max(axis=1) > 0)[0]
                    g[ki], g[kd] = nz.tolist(), [round(float(x), 7) for x in d[nz].ravel()]
            out.append(g)
    return out


def paths(rigged: Path):
    rigged = Path(rigged)
    import landmarks as LM
    return rigged.with_name(LM._stem(rigged) + "_face_edits.json"), rigged.with_name(rigged.stem + ".noedit.glb")


def tex_dir(rigged: Path) -> Path:
    import landmarks as LM
    return Path(rigged).with_name(LM._stem(rigged) + "_tex")


def paint_save(rigged: Path, layers: list, reset: bool = False) -> dict:
    """layers: [{name: the image's name, png: base64 RGBA, the strokes since the model was loaded}] laid over the kept
    layer of that image (or the layers all gone: reset); then the model made again from the one as built."""
    import base64
    from io import BytesIO
    from PIL import Image
    rigged = Path(rigged)
    d = tex_dir(rigged)
    if reset and d.is_dir():
        for f in d.glob("*.png"):
            f.unlink()
    for L in layers or []:
        d.mkdir(exist_ok=True)
        top = Image.open(BytesIO(base64.b64decode(L["png"]))).convert("RGBA")
        f = d / f"{_safe(L.get('name') or '')}.png"
        if f.exists():
            old = Image.open(f).convert("RGBA")
            if old.size != top.size:
                old = old.resize(top.size, Image.BILINEAR)
            top = Image.alpha_composite(old, top)
        top.save(f)
    edits = load(rigged)
    base = _base(rigged, edits)
    res = apply(base, rigged, edits, d)
    edits["applied"] = _sig(rigged)
    paths(rigged)[0].write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
    return {**res, "layers": sorted(f.stem for f in d.glob("*.png")) if d.is_dir() else []}


def _sig(p: Path):
    st = p.stat()
    return {"size": st.st_size, "mtime_ns": st.st_mtime_ns}


def load(rigged: Path) -> dict:
    f = paths(rigged)[0]
    try:
        d = json.loads(f.read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {"version": 1, "keys": {}}
    except (OSError, ValueError):
        return {"version": 1, "keys": {}}


def _base(rigged: Path, edits: dict) -> Path:
    """The model as built: the kept copy, or - when the rigged GLB is not the one the edits were last laid on (a
    rebuild wrote it) - the rigged GLB itself, kept now."""
    noedit = paths(rigged)[1]
    if not noedit.exists() or edits.get("applied") != _sig(rigged):
        shutil.copy2(rigged, noedit)
    return noedit


def merge(edits: dict, key: str, groups: list) -> int:
    """Add the session's offsets (the editor's changes since it loaded the model) to the stored ones of the key."""
    store = edits.setdefault("keys", {}).setdefault(key, [])
    n = 0
    for g in groups:
        old = next((x for x in store if x["mesh"] == g["mesh"] and x["prim"] == g["prim"]), None)
        if old is None:
            old = {"mesh": g["mesh"], "prim": g["prim"], "v": []}
            store.append(old)
        by = {int(r[0]): r for r in old["v"]}
        for r in g["v"]:
            i = int(r[0])
            if i in by:
                by[i] = by[i][:4] + [round(by[i][4 + k] + r[4 + k], 7) for k in range(3)]
            else:
                by[i] = [i] + [round(x, 7) for x in r[1:7]]
            n += 1
        old["v"] = [r for r in by.values() if max(abs(x) for x in r[4:7]) > 1e-9]
    edits["keys"][key] = [g for g in store if g["v"]]
    if not edits["keys"][key]:
        del edits["keys"][key]
    return n


def save(rigged: Path, changes: dict, reset=None) -> dict:
    """changes: {key: [groups]} from the editor (offsets since it loaded the model); reset: keys whose edits go.
    Writes the edits file and the rigged GLB with every edit laid on the model as built."""
    rigged = Path(rigged)
    edits = load(rigged)
    base = _base(rigged, edits)
    for k in reset or []:
        (edits.get("keys") or {}).pop(k, None)
    n = sum(merge(edits, k, g) for k, g in (changes or {}).items())
    res = apply(base, rigged, edits, tex_dir(rigged))
    edits["applied"] = _sig(rigged)
    paths(rigged)[0].write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
    return {**res, "sent": n, "keys": sorted(edits.get("keys") or {})}


def mesh_save(rigged: Path, cut: dict, fill: dict, reset: bool = False) -> dict:
    """cut: {mesh: [{prim, tris: flat corner places}]}, fill: {mesh: [{loop, tris, colour}]} from the editor, added to
    the kept ones (or all gone: reset); the model made again from the one as built."""
    rigged = Path(rigged)
    edits = load(rigged)
    base = _base(rigged, edits)
    if reset:
        edits.pop("mesh", None)
    store = edits.setdefault("mesh", {})
    n = 0
    for name, cs in (cut or {}).items():
        store.setdefault(name, {}).setdefault("cut", []).extend(cs); n += sum(len(c.get("tris") or []) // 3 for c in cs)
    for name, fs in (fill or {}).items():
        store.setdefault(name, {}).setdefault("fill", []).extend(fs); n += len(fs)
    if not store:
        edits.pop("mesh", None)
    res = apply(base, rigged, edits, tex_dir(rigged))
    edits["applied"] = _sig(rigged)
    paths(rigged)[0].write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
    return {**res, "sent": n}


def reapply(rigged: Path):
    """After a rebuild: the edits kept for this character laid on the new model (their points found by place).
    None when there are none."""
    rigged = Path(rigged)
    edits = load(rigged)
    painted = tex_dir(rigged).is_dir() and any(tex_dir(rigged).glob("*.png"))
    if not edits.get("keys") and not painted and not edits.get("mesh"):
        return None
    base = _base(rigged, edits)
    res = apply(base, rigged, edits, tex_dir(rigged))
    edits["applied"] = _sig(rigged)
    paths(rigged)[0].write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
    return {**res, "keys": sorted(edits.get("keys") or {})}
