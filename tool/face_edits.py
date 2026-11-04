"""Hand corrections of a character's shape keys (the face's expressions: jawOpen, mouthSmile, the brows...), made with
the brush in the markup editor's «Pose» mode and kept next to the character, so a rebuilt skeleton gets them again.

    <stem>_face_edits.json   {"version": 1, "keys": {key: [{"mesh": name, "prim": p, "v": [[i, bx, by, bz, ox, oy, oz], ...]}]},
                              "applied": {"size": ..., "mtime_ns": ...}}
    <rigged>.noedit.glb      the model as the build made it (the edits are always laid on this one)

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


def apply(base_glb, out_glb, edits) -> dict:
    """Lay every key's edits on base_glb and write out_glb. {"points": laid, "missed": not found again}."""
    j, bin_ = read_glb(base_glb)
    laid = missed = 0
    meshes = {m.get("name"): (mi, m) for mi, m in enumerate(j.get("meshes", []))}
    for key, groups in (edits.get("keys") or {}).items():
        for g in groups:
            hit = meshes.get(g.get("mesh"))
            if hit is None:
                missed += len(g.get("v") or [])
                continue
            m = hit[1]
            names = (m.get("extras") or {}).get("targetNames") or []
            if key not in names or g.get("prim", 0) >= len(m["primitives"]):
                missed += len(g.get("v") or [])
                continue
            t = names.index(key)
            prim = m["primitives"][g["prim"]]
            tg = prim["targets"][t]
            base = accessor(j, bin_, prim["attributes"]["POSITION"])
            dpos = accessor(j, bin_, tg["POSITION"])
            rows = np.array(g["v"], dtype=np.float64).reshape(-1, 7)
            if not len(rows):
                continue
            size = float(np.linalg.norm(base.max(axis=0) - base.min(axis=0))) or 1.0
            where = _find(base, rows[:, 1:4], rows[:, 0].astype(np.int64), 0.002 * size)
            use = where >= 0
            missed += int((~use).sum())
            laid += int(use.sum())
            new = dpos.copy()
            np.add.at(new, where[use], rows[use, 4:7])
            if "NORMAL" in tg:   # the light: the normals' displacement turned as the edit turns the surface
                tris = _tris(j, bin_, prim, len(base))
                dn = accessor(j, bin_, tg["NORMAL"])
                dn += vertex_normals(base + new, tris) - vertex_normals(base + dpos, tris)
                tg["NORMAL"] = sparse_accessor(j, bin_, dn, 1e-6)
            tg["POSITION"] = sparse_accessor(j, bin_, new)
    write_glb(out_glb, j, bin_)
    return {"points": laid, "missed": missed}


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
    res = apply(base, rigged, edits)
    edits["applied"] = _sig(rigged)
    paths(rigged)[0].write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
    return {**res, "sent": n, "keys": sorted(edits.get("keys") or {})}


def reapply(rigged: Path):
    """After a rebuild: the edits kept for this character laid on the new model (their points found by place).
    None when there are none."""
    rigged = Path(rigged)
    edits = load(rigged)
    if not edits.get("keys"):
        return None
    base = _base(rigged, edits)
    res = apply(base, rigged, edits)
    edits["applied"] = _sig(rigged)
    paths(rigged)[0].write_text(json.dumps(edits, ensure_ascii=False), encoding="utf-8")
    return {**res, "keys": sorted(edits["keys"])}
