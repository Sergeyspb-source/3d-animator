"""Runs INSIDE Blender (imported by the generators): «Texture by the unwrap» for any piece, and the bake that gives the
pieces made by the vendor generators (a helmet, elbows, footwear) textures of their own.

A piece's faces are in groups, a slot each (plate, strap, detail, mail, quilt, trim, wood: the editor's parts); each
group has its own unwrap and its own colour texture. uv_package gives each group's unwrap out as pictures
(<slot>_layout.png: the islands' outlines over its colours, _mask, _color, _lines; uv.json with a hash of each unwrap);
uv_user takes a texture painted on one back (<slot>_user.png, its unwrap's hash the same) as that group's colour.

bake_made: a vendor piece (its own procedural and image materials, on their own UVs) unwrapped per slot and baked into
plain image materials, one per slot - its colour (as a dielectric: Cycles' diffuse colour), its roughness, its
metalness kept as a value - so the game gets textures, and the unwrap can be given out and painted.
"""
import hashlib
import json
import math
from pathlib import Path

import bpy
import numpy as np

SLOTS = ("plate", "strap", "detail", "mail", "quilt", "trim", "wood")
MAIL_WORDS = ("mail", "ring", "aventail", "chain")


def slot_of(name: str) -> str:
    """A vendor material's (or part's) slot by its name: mail, leather straps, small metal, padding, else plate."""
    n = (name or "").lower()
    if any(w in n for w in MAIL_WORDS):
        return "mail"
    if any(w in n for w in ("rivet", "buckle", "brass", "gold", "bronze", "nail", "stud")):
        return "detail"
    if any(w in n for w in ("liner", "lining", "padding", "pad", "quilt", "cloth", "fabric", "gambeson")):
        return "quilt"
    if any(w in n for w in ("leather", "strap", "belt", "lace")):
        return "strap"
    if any(w in n for w in ("trim", "border", "rim", "edge")):
        return "trim"
    return "plate"


def tag_mail(objects):
    """The rings of a mail part (by its object's name) given a material of their own before the parts are joined, so
    the mail is a slot of its own (its steel is the plates' material)."""
    copies = {}
    for o in objects:
        if o.type != "MESH" or not any(w in o.name.lower() for w in MAIL_WORDS):
            continue
        for i, m in enumerate(o.data.materials):
            if m is None or slot_of(m.name) != "plate":   # (its steel only: a leather strap on it stays leather)
                continue
            if m.name not in copies:
                c = m.copy(); c.name = f"Mail_{m.name}"; copies[m.name] = c
            o.data.materials[i] = copies[m.name]


def pixels(im, size):
    a = np.empty(size * size * 4, np.float32)
    im.pixels.foreach_get(a)
    return a.reshape(size * size, 4)


def _faces(obj, mis):
    mat = np.empty(len(obj.data.polygons), np.int32); obj.data.polygons.foreach_get("material_index", mat)
    return np.isin(mat, list(mis))


def _corners(obj, layer):
    """Each face as its points from its smallest one on (the same face whatever its place in the mesh, its first
    corner), with its corners' UVs in that order: [(points, uvs)]."""
    me = obj.data
    uv = np.empty(len(me.loops) * 2, np.float32); me.uv_layers[layer].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    lv = np.empty(len(me.loops), np.int32); me.loops.foreach_get("vertex_index", lv)
    ls = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_total", lt)
    out = []
    for a, t in zip(ls, lt):
        v = lv[a:a + t]; r = int(np.argmin(v))
        out.append((tuple(np.roll(v, -r).tolist()), np.roll(uv[a:a + t], -r, axis=0), a, r))
    return out


def uv_hash(obj, mis, layer="UVMap"):
    """A hash of the group's unwrap: its faces (by their points) and their UVs, whatever the faces' order (a vendor
    piece's comes in another order each time)."""
    sel = _faces(obj, mis)
    rows = sorted((k, np.round(u * 4096).astype(np.int32).tobytes()) for (k, u, _, _), s_ in zip(_corners(obj, layer), sel) if s_)
    h = hashlib.md5()
    for k, u in rows:
        h.update(np.array(k, np.int32).tobytes()); h.update(u)
    return h.hexdigest()[:16]


def uv_hash_loops(obj, mis, layer="UVMap"):   # (the hash before 2026-11-12, by the faces' order: still taken)
    me = obj.data
    uv = np.empty(len(me.loops) * 2, np.float32); me.uv_layers[layer].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    ls = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_total", lt)
    sel = _faces(obj, mis)
    idx = np.concatenate([np.arange(a, a + t) for a, t, k in zip(ls, lt, sel) if k] or [np.zeros(0, np.int64)])
    return hashlib.md5(np.round(uv[idx] * 4096).astype(np.int32).tobytes()).hexdigest()[:16]


def bake_aux(obj, groups, size, item, what, socket):
    """socket(node_tree) -> an output: baked as emission into a float image per group (its pixels as an array)."""
    ims = {}
    for g in groups:
        im = bpy.data.images.new(f"{item}_{g['slot']}_{what}", size, size, alpha=False, float_buffer=True)
        im.colorspace_settings.name = "Non-Color"
        for m in g["mats"]:
            nt = m.node_tree
            node = nt.nodes.get("bake") or nt.nodes.new("ShaderNodeTexImage"); node.name = "bake"
            node.image = im; nt.nodes.active = node
            out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output) if any(
                n.type == "OUTPUT_MATERIAL" and n.is_active_output for n in nt.nodes) else next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
            em = nt.nodes.get("bake_em") or nt.nodes.new("ShaderNodeEmission"); em.name = "bake_em"
            nt.links.new(socket(nt), em.inputs[0]); nt.links.new(em.outputs[0], out.inputs[0])
        ims[g["slot"]] = im
    bpy.ops.object.bake(type="EMIT", margin=4)
    out = {k: pixels(im, size)[:, :3].copy() for k, im in ims.items()}
    for im in ims.values():
        bpy.data.images.remove(im)
    return out


def uv_user(obj, groups, size, job, info, layer="UVMap"):
    """A texture given back for a group (job["uvtex"][slot]: its path, the hash of the unwrap it was painted on) made
    that group's colour - when the unwrap is still that one (else info[slot] = "changed")."""
    for g in groups:
        t = (job.get("uvtex") or {}).get(g["slot"])
        if not t or not Path(str(t.get("path") or "")).exists():
            continue
        if t.get("hash") not in (uv_hash(obj, g["mis"], layer), uv_hash_loops(obj, g["mis"], layer)):
            info[g["slot"]] = "changed"
            continue
        b = bpy.data.images.load(str(t["path"]))
        if tuple(b.size) != (size, size):
            b.scale(size, size)
        px = pixels(b, size).copy(); bpy.data.images.remove(b)
        px[:, 3] = 1
        g["color"].pixels.foreach_set(px.ravel())
        info[g["slot"]] = "ok"


def uv_package(obj, groups, size, item, job, info, layer="UVMap"):
    """Per group in job["uv_out"]: <slot>_color.png (its colours as baked), <slot>_mask.png (its islands white),
    <slot>_lines.png (the islands' edges on nothing), <slot>_layout.png (the edges over the colours); uv.json. The
    colours a texture given back was painted on are kept (not written over by it)."""
    if not job.get("uv_out"):
        return
    d = Path(job["uv_out"]); d.mkdir(parents=True, exist_ok=True)
    def one(nt):
        v = nt.nodes.new("ShaderNodeValue"); v.outputs[0].default_value = 1.
        return v.outputs[0]
    mask = bake_aux(obj, groups, size, item, "uvmask", one)
    me = obj.data
    uv = np.empty(len(me.loops) * 2, np.float32); me.uv_layers[layer].data.foreach_get("uv", uv); uv = uv.reshape(-1, 2)
    ls = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_start", ls)
    lt = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("loop_total", lt)
    out = {"size": size, "slots": {}}
    def save(name, arr):
        im = bpy.data.images.new(f"{item}_uvpack_{name}", size, size, alpha=True)
        im.pixels.foreach_set(arr.astype(np.float32).ravel())
        im.filepath_raw = str(d / f"{name}.png"); im.file_format = "PNG"; im.save()
        bpy.data.images.remove(im)
    for g in groups:
        sl, sel = g["slot"], _faces(obj, g["mis"])
        if not sel.any():
            continue
        col = pixels(g["color"], size).copy(); col[:, 3] = 1
        mk = np.clip(mask[sl][:, 0], 0, 1)
        own = info.get(sl) == "ok" and (d / f"{sl}_color.png").exists()
        # the islands' edges: an edge of one face only, on the unwrap (a pixel wide)
        count, seg = {}, {}
        q = np.round(uv * 8192).astype(np.int64)
        for f in np.nonzero(sel)[0]:
            a0, n = ls[f], lt[f]
            for j in range(n):
                a, b = a0 + j, a0 + (j + 1) % n
                ka, kb = (q[a, 0], q[a, 1]), (q[b, 0], q[b, 1])
                k = (ka, kb) if ka <= kb else (kb, ka)
                count[k] = count.get(k, 0) + 1; seg[k] = (a, b)
        lines = np.zeros((size, size), np.float32)
        for k, c in count.items():
            if c == 1:
                a, b = seg[k]
                (x0, y0), (x1, y1) = uv[a] * (size - 1), uv[b] * (size - 1)
                n = int(max(abs(x1 - x0), abs(y1 - y0))) + 1
                xs = np.clip(np.round(np.linspace(x0, x1, n + 1)).astype(int), 0, size - 1)
                ys = np.clip(np.round(np.linspace(y0, y1, n + 1)).astype(int), 0, size - 1)
                lines[ys, xs] = 1
        lines = lines.ravel()
        if not own:
            save(f"{sl}_color", col)
            lay = col.copy(); lay[:, :3] = lay[:, :3] * (1 - lines[:, None]) + np.array([1, .1, .6])[None, :] * lines[:, None]
            save(f"{sl}_layout", lay)
        save(f"{sl}_mask", np.stack([mk, mk, mk, np.ones_like(mk)], axis=1))
        save(f"{sl}_lines", np.stack([lines * 0, lines * 0, lines * 0, lines], axis=1))
        out["slots"][sl] = {"hash": uv_hash(obj, g["mis"], layer), "faces": int(sel.sum())}
    out["geo"] = geo_hash(obj)
    cs = _corners(obj, layer)   # each face by its points, its corners' UVs: found again whatever the faces' order
    np.savez_compressed(d / "uv_loops.npz", geo=np.array(out["geo"]), fn=np.array([len(k) for k, _, _, _ in cs], np.int32),
                        fv=np.array([x for k, _, _, _ in cs for x in k], np.int32), fuv=np.concatenate([u for _, u, _, _ in cs]).astype(np.float32))   # (the next make of this mesh takes it back)
    (d / "uv.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


def geo_hash(obj):
    """The mesh as it is (its points, its faces): the same piece made again gives the same."""
    me = obj.data
    co = np.empty(len(me.vertices) * 3, np.float32); me.vertices.foreach_get("co", co)
    h = hashlib.md5(np.round(co * 1e4).astype(np.int64).tobytes())   # (not the faces' or the materials' order: a vendor piece's is not the same each time)
    h.update(str(len(me.polygons)).encode())
    return h.hexdigest()[:16]


def unwrap(obj, sets, job, layer):
    """Each set of materials (its faces) its own unwrap, filling its own texture, on the UV layer - as given out with the
    piece last time (uv_loops.npz in job["uv_prev"]) when the mesh is the same: smart_project's islands and packing of
    a big part are not the same from run to run, and a texture painted on the unwrap must find it again."""
    me = obj.data
    gh = geo_hash(obj)
    prev = Path(str(job.get("uv_prev") or "")) / "uv_loops.npz"
    if job.get("uv_prev") and prev.exists():
        try:
            z = np.load(prev)
            if str(z["geo"]) == gh:
                keys, sizes, uvs = z["fv"], z["fn"], z["fuv"].reshape(-1, 2)
                saved, k0 = {}, 0
                for n in sizes:
                    saved[tuple(keys[k0:k0 + n].tolist())] = uvs[k0:k0 + n]; k0 += n
                cur = _corners(obj, layer)
                if all(k in saved for k, _, _, _ in cur):
                    uv = np.empty((len(me.loops), 2), np.float32)
                    for k, _, a, r in cur:
                        uv[a:a + len(k)] = np.roll(saved[k], r, axis=0)
                    me.uv_layers[layer].data.foreach_set("uv", uv.ravel())
                    return
        except Exception:  # noqa: BLE001  (unwrapped again)
            pass
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    me.uv_layers.active = me.uv_layers[layer]
    mat = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("material_index", mat)
    for mis in sets:
        sel = np.isin(mat, list(mis))
        if not sel.any():
            continue
        bpy.ops.object.mode_set(mode="EDIT"); bpy.ops.mesh.select_all(action="DESELECT"); bpy.ops.object.mode_set(mode="OBJECT")
        me.polygons.foreach_set("select", sel)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=.006)
        bpy.ops.object.mode_set(mode="OBJECT")


def _bsdfs(m):
    return [n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"] if m and m.use_nodes else []


def bake_made(obj, item, job, tex_dir):
    """A vendor piece's materials baked into one image material per slot, on an unwrap of each slot's own; its unwrap
    given out and a texture given back taken (uv_package, uv_user). -> {slot: "ok" | "changed"} (the textures given back)"""
    size = int(job.get("tex", 1024))
    me = obj.data
    info = {}
    src = list(me.materials)
    if not src or not me.polygons:
        return info
    sl_of = [slot_of(m.name if m else "") for m in src]
    used = sorted({sl_of[p.material_index] for p in me.polygons}, key=SLOTS.index)
    groups = [{"slot": s, "mis": {i for i, x in enumerate(sl_of) if x == s}} for s in used]
    for g in groups:
        g["mats"] = [src[i] for i in sorted(g["mis"]) if src[i] is not None and src[i].use_nodes]
    # the metalness kept per slot (their textures read at their own UVs, the bake writes by its own)
    for g in groups:
        ms = [b.inputs["Metallic"].default_value for m in g["mats"] for b in _bsdfs(m)]
        g["metal"] = min(.65, sum(ms) / len(ms)) if ms else 0.
    old = [l.name for l in me.uv_layers]
    rend = next((l for l in me.uv_layers if l.active_render), None)
    bl = me.uv_layers.new(name="bake_uv")
    me.uv_layers.active = bl
    if rend is not None:
        rend.active_render = True
    mat = np.empty(len(me.polygons), np.int32); me.polygons.foreach_get("material_index", mat)
    unwrap(obj, [g["mis"] for g in groups], job, "bake_uv")   # each slot its own unwrap, filling its own texture
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    sc = bpy.context.scene
    try:
        sc.render.engine = "CYCLES"
    except TypeError:
        pass
    sc.cycles.samples = 4
    for g in groups:
        for kind, cs in (("color", "sRGB"), ("rough", "Non-Color")):
            im = bpy.data.images.new(f"{item}_{g['slot']}_{kind}", size, size, alpha=False)
            im.colorspace_settings.name = cs
            g[kind] = im
    def target(kind):
        for g in groups:
            for m in g["mats"]:
                nt = m.node_tree
                node = nt.nodes.get("bake") or nt.nodes.new("ShaderNodeTexImage"); node.name = "bake"
                node.image = g[kind]; nt.nodes.active = node
    # the colour as a dielectric's (Cycles' diffuse colour: a metal's is black), its metalness put back after
    kept = []
    for g in groups:
        for m in g["mats"]:
            for b in _bsdfs(m):
                s = b.inputs["Metallic"]
                kept.append((m, b, s.default_value, [(l.from_socket) for l in s.links]))
                for l in list(s.links):
                    m.node_tree.links.remove(l)
                s.default_value = 0.
    target("color")
    bpy.ops.object.bake(type="DIFFUSE", pass_filter={"COLOR"}, margin=4)
    for m, b, v, froms in kept:
        b.inputs["Metallic"].default_value = v
        for fs in froms:
            m.node_tree.links.new(fs, b.inputs["Metallic"])
    target("rough")
    bpy.ops.object.bake(type="ROUGHNESS", margin=4)
    uv_user(obj, groups, size, job, info, "bake_uv")
    tex_dir = Path(tex_dir); tex_dir.mkdir(parents=True, exist_ok=True)
    for g in groups:
        for kind in ("color", "rough"):
            im = g[kind]; im.filepath_raw = str(tex_dir / f"{im.name}.png"); im.file_format = "PNG"; im.save()
    uv_package(obj, groups, size, item, job, info, "bake_uv")
    # plain image materials, one per slot, on the bake's unwrap only
    new = []
    for g in groups:
        m = bpy.data.materials.new(f"{item}_{g['slot']}"); m.use_nodes = True
        nt = m.node_tree
        for nd in list(nt.nodes):
            nt.nodes.remove(nd)
        N, L = nt.nodes.new, nt.links.new
        out = N("ShaderNodeOutputMaterial"); bsdf = N("ShaderNodeBsdfPrincipled"); L(bsdf.outputs[0], out.inputs[0])
        c = N("ShaderNodeTexImage"); c.image = g["color"]; L(c.outputs[0], bsdf.inputs["Base Color"])
        r = N("ShaderNodeTexImage"); r.image = g["rough"]; L(r.outputs[0], bsdf.inputs["Roughness"])
        bsdf.inputs["Metallic"].default_value = g["metal"]
        new.append(m)
    remap = np.zeros(len(src), np.int32)
    for k, g in enumerate(groups):
        for i in g["mis"]:
            remap[i] = k
    me.materials.clear()
    for m in new:
        me.materials.append(m)
    me.polygons.foreach_set("material_index", remap[mat])
    for name in old:   # (a layer's Python object is not to be kept across removing others: taken again by its name)
        me.uv_layers.remove(me.uv_layers[name])
    bl = me.uv_layers["bake_uv"]
    bl.name = "UVMap"
    bl = me.uv_layers["UVMap"]; me.uv_layers.active = bl; bl.active_render = True
    me.update()
    return info
