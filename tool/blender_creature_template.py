"""Runs INSIDE Blender (background): a creature's skeleton built from a template's joints placed on the model
(creature_templates.py: a quadruped, a bird, a serpent) and the model skinned to it.

    blender -b -P blender_creature_template.py -- job.json

job.json: {"src": the model (GLB; a skeleton it has is dropped), "out": GLB (<name>_auto.glb: named, without a jaw),
"template": "quadruped" | "bird" | "serpent", "joints": {id: [x, y, z]} (glTF, after the yaw turn), "yaw": degrees
(the model turned about the up axis to look along +Z), "preview": png path prefix (renders with the bones), "smooth": n}.
The bones run from joint to joint (creature_templates.build_list); a chain's bones are connected; the legs' and the
wings' local Z points forward (they bend about X), the body's up. Heat weights on a welded copy (blender_heat.proxy_heat:
the seams of Tripo / TRELLIS models welded first; a serpent sized by its length). Prints TEMPLATE_OK {report}.
"""
import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_heat  # noqa: E402
import creature_templates as CT  # noqa: E402

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
TPL = job["template"]
J = job["joints"]
bl = lambda p: Vector((p[0], -p[2], p[1]))  # noqa: E731  glTF (x, y, z) -> Blender (x, -z, y)

# ---------------------------------------------------------------- the model, clean and turned
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["src"])
scene = bpy.context.scene
bpy.context.view_layer.update()
meshes = [o for o in scene.objects if o.type == "MESH" and not o.name.startswith("Icosphere")]
if not meshes:
    raise SystemExit("TEMPLATE_ERROR no meshes")
world = {o: o.matrix_world.copy() for o in meshes}
turn = Matrix.Rotation(math.radians(float(job.get("yaw", 0.0))), 4, "Z")
for o in meshes:
    for m in list(o.modifiers):
        if m.type == "ARMATURE":
            o.modifiers.remove(m)
    o.vertex_groups.clear()
    o.parent = None
    o.matrix_world = turn @ world[o]
    if o.data.shape_keys:   # (a model's own keys: kept on the basis only)
        o.shape_key_clear()
for o in list(scene.objects):
    if o.type != "MESH" or o not in meshes:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.make_single_user(object=True, obdata=True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ---------------------------------------------------------------- the armature
arm_data = bpy.data.armatures.new("Armature")
rig = bpy.data.objects.new("Armature", arm_data)
scene.collection.objects.link(rig)
bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
plan = CT.build_list(TPL, J)
roll = CT.TEMPLATES[TPL].get("roll", {})
eb = {}
for name, h, t, _p in plan:
    b = arm_data.edit_bones.new(name)
    b.head, b.tail = bl(h), bl(t)
    if (b.tail - b.head).length < 1e-4:
        b.tail = b.head + Vector((0, 0, 0.01))
    eb[name] = b
for name, _h, _t, p in plan:
    if p:
        b = eb[name]
        b.parent = eb[p]
        b.use_connect = (b.head - eb[p].tail).length < 1e-5
FWD, UP = Vector((0, -1, 0)), Vector((0, 0, 1))
for name, b in eb.items():
    d = (b.tail - b.head).normalized()
    want = FWD if any(name.startswith(k) for k, v in roll.items() if v == "fwd") else UP
    if abs(d.dot(want)) > 0.9:   # (a hanging tail, a leg pointing forward: the other axis)
        want = UP if want is FWD else FWD
    b.align_roll(want)
bpy.ops.object.mode_set(mode="OBJECT")

# ---------------------------------------------------------------- skin
rep = blender_heat.proxy_heat(meshes, rig, smooth=int(job.get("smooth", 6)), size="max" if TPL == "serpent" else "height")
LIMB = re.compile(r"^(leg_[A-Z]{2}|leg_[LR]\d+|wingx?_[LR])_")


def limb_of(bone):
    m = LIMB.match(bone)
    return m[1] if m else None


def one_limb():
    """the skin between two legs follows the body, not both legs: heat and its smoothing leak through the chest and the
    belly, and a right elbow's skin kept 4-10 % of the left upper arm - when the legs went apart (a gallop, a jump) its
    triangles stretched up to 4.8 times into spikes. Where two limbs share a vertex, the strongest keeps only what it
    has over the others (nothing on the line between them, where they are even, all of it far from it), the rest goes
    to the bone it hangs from (the chest, the hips): the leg's hold fades smoothly toward the middle, no seam. (Giving
    each vertex to its strongest leg whole cut a seam down the brisket: 6.6 times there in the walk.)"""
    bones = arm_data.bones
    root_of = {}
    for b in bones:
        k = limb_of(b.name)
        if k and (b.parent is None or limb_of(b.parent.name) != k):
            root_of[k] = b.parent.name if b.parent else b.name
    moved = 0
    for o in meshes:
        gn = {g.index: g.name for g in o.vertex_groups}
        for v in o.data.vertices:
            per = {}
            for g in v.groups:
                k = limb_of(gn[g.group])
                if k and g.weight > 1e-4:
                    per[k] = per.get(k, 0.0) + g.weight
            if len(per) < 2:
                continue
            keep = max(per, key=per.get)
            rest_ = sum(w for k, w in per.items() if k != keep)
            share = max(0.0, per[keep] - rest_) / per[keep]   # (of the strongest limb's weight, what it keeps)
            extra = 0.0
            for g in list(v.groups):
                k = limb_of(gn[g.group])
                if not k:
                    continue
                if k == keep:
                    extra += g.weight * (1.0 - share)
                    if share > 1e-4:
                        o.vertex_groups[g.group].add([v.index], g.weight * share, "REPLACE")
                    else:
                        o.vertex_groups[g.group].remove([v.index])
                else:
                    extra += g.weight
                    o.vertex_groups[g.group].remove([v.index])
            body = root_of.get(keep)
            if body:
                vg = o.vertex_groups.get(body) or o.vertex_groups.new(name=body)
                old = next((g.weight for g in v.groups if g.group == vg.index), 0.0)
                vg.add([v.index], old + extra, "REPLACE")
            moved += 1
    return moved


rep["one_limb_vertices"] = one_limb()


def loose_pieces():
    """small loose pieces (bristles, a fringe, tusks, horns, claws: islands of the skin welded by position, few vertices and
    short) take the weights of the main skin they sit on - one set for the whole piece, so it moves as
    one with it (heat finds no way into a closed small piece and gives it the nearest bones by distance: a chin's fringe
    went with the shoulders)"""
    from mathutils.kdtree import KDTree
    pts, owner = [], []
    for o in meshes:
        mw = o.matrix_world
        for v in o.data.vertices:
            pts.append(mw @ v.co)
            owner.append((o, v.index))
    n = len(pts)
    size = max((max(p[i] for p in pts) - min(p[i] for p in pts)) for i in range(3))
    q = 1e-4 * size
    key = {}
    wid = [key.setdefault((round(p.x / q), round(p.y / q), round(p.z / q)), len(key)) for p in pts]
    par = list(range(len(key)))

    def find(a):
        while par[a] != a:
            par[a] = par[par[a]]
            a = par[a]
        return a
    base = 0
    for o in meshes:
        for e in o.data.edges:
            a, b = find(wid[base + e.vertices[0]]), find(wid[base + e.vertices[1]])
            if a != b:
                par[a] = b
        base += len(o.data.vertices)
    comp = [find(wid[i]) for i in range(n)]
    count = {}
    for c in comp:
        count[c] = count.get(c, 0) + 1
    lo_, hi_ = {}, {}
    for i, c in enumerate(comp):
        p = pts[i]
        if c in lo_:
            lo_[c] = Vector(map(min, lo_[c], p))
            hi_[c] = Vector(map(max, hi_[c], p))
        else:
            lo_[c], hi_[c] = p.copy(), p.copy()
    # (small in both: few vertices and short - a long loose tail keeps its own heat weights along its bones)
    # a small piece the legs would pull apart (its vertices led by different legs: a hair strip under the belly between
    # the hind legs stretched 4.4 times into a spike in the walk) - one piece with the skin under it, whatever its length
    lead_limbs = {}
    for i, (o, vi) in enumerate(owner):
        gs = o.data.vertices[vi].groups
        if gs:
            k = limb_of(o.vertex_groups[max(gs, key=lambda g: g.weight).group].name)
            if k:
                lead_limbs.setdefault(comp[i], set()).add(k)
    small = {c for c, k in count.items() if k < 0.02 * n and ((hi_[c] - lo_[c]).length < 0.06 * size or len(lead_limbs.get(c, ())) > 1)}
    if not small:
        return 0
    groups = {o: {g.index: g.name for g in o.vertex_groups} for o in meshes}
    tree = KDTree(n)
    for i, p in enumerate(pts):
        if comp[i] not in small:
            tree.insert(p, i)
    tree.balance()
    by = {}
    for i in range(n):
        if comp[i] in small:
            by.setdefault(comp[i], []).append(i)
    moved = 0
    for c, ids in by.items():
        acc = {}
        for i in ids:
            _p, j, _d = tree.find(pts[i])
            o, vi = owner[j]
            for g in o.data.vertices[vi].groups:
                nm = groups[o][g.group]
                acc[nm] = acc.get(nm, 0.0) + g.weight
        top = sorted(acc.items(), key=lambda x: -x[1])[:4]
        tot = sum(w for _n, w in top) or 1.0
        for i in ids:
            o, vi = owner[i]
            for g in list(o.data.vertices[vi].groups):
                o.vertex_groups[g.group].remove([vi])
            for nm, w in top:
                (o.vertex_groups.get(nm) or o.vertex_groups.new(name=nm)).add([vi], w / tot, "REPLACE")
            moved += 1
    return moved


rep["loose_vertices"] = loose_pieces()
for o in meshes:
    mod = o.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    o.parent = rig
    o.matrix_parent_inverse = rig.matrix_world.inverted()
# the share of the skin each bone leads (a bone leading nothing sits outside the model)
lead = {b.name: 0 for b in arm_data.bones}
for o in meshes:
    gn = {g.index: g.name for g in o.vertex_groups}
    for v in o.data.vertices:
        if v.groups:
            g = max(v.groups, key=lambda x: x.weight)
            lead[gn[g.group]] = lead.get(gn[g.group], 0) + 1
rep.update(bones=len(arm_data.bones), empty=[n for n, c in lead.items() if c == 0])

# ---------------------------------------------------------------- export (rest pose)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
Path(job["out"]).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=str(job["out"]), export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4)

# ---------------------------------------------------------------- previews: the model, its bones over it
if job.get("preview"):
    import numpy as np
    COL = {"leg_F": (0.18, 0.44, 0.88), "leg_B": (0.13, 0.64, 0.32), "wing": (0.31, 0.64, 0.84), "tail": (0.61, 0.31, 0.84),
           "head": (0.85, 0.23, 0.18), "neck": (0.94, 0.5, 0.18), "": (0.89, 0.61, 0.13)}
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    lo = Vector([min(p[i] for p in corners) for i in range(3)])
    hi = Vector([max(p[i] for p in corners) for i in range(3)])
    C, size = (lo + hi) / 2, (hi - lo).length
    sticks = []
    for b in arm_data.bones:
        h, t = rig.matrix_world @ b.head_local, rig.matrix_world @ b.tail_local
        ln = (t - h).length
        r = max(0.012 * size, 0.08 * ln)
        bpy.ops.mesh.primitive_cone_add(vertices=6, radius1=r, radius2=r * 0.25, depth=ln, location=(h + t) / 2)
        s = bpy.context.active_object
        s.rotation_euler = (t - h).to_track_quat("Z", "Y").to_euler()
        key = next(k for k in COL if b.name.startswith(k) or (k and k in b.name))
        m = bpy.data.materials.new(b.name)
        m.diffuse_color = (*COL[key], 1)
        s.data.materials.append(m)
        bpy.ops.mesh.primitive_uv_sphere_add(radius=r * 1.25, location=h, segments=10, ring_count=6)
        sp = bpy.context.active_object
        sp.data.materials.append(m)
        sticks += [s, sp]
    sc = scene
    sc.render.engine = "BLENDER_WORKBENCH"
    sc.display.shading.light = "STUDIO"
    sc.render.resolution_x, sc.render.resolution_y = 900, 700
    sc.render.image_settings.file_format = "PNG"
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = size * 0.9
    pre = str(job["preview"])
    shots = []
    for view, d in (("side", Vector((1, 0, 0))), ("front", Vector((0, -1, 0))), ("top", Vector((0, 0, 1)))):
        cam.location = C + d * size * 2
        cam.rotation_euler = (0, 0, 0) if view == "top" else (-d).to_track_quat("-Z", "Y").to_euler()
        files = {}
        for part, shown in (("m", meshes), ("b", sticks)):
            for o in meshes + sticks:
                o.hide_render = o not in shown
            sc.display.shading.color_type = "TEXTURE" if part == "m" else "MATERIAL"
            sc.render.film_transparent = part == "b"
            sc.render.filepath = f"{pre}_{view}_{part}.png"
            bpy.ops.render.render(write_still=True)
            files[part] = sc.render.filepath
        # the bones over the model, the model dimmed a little
        im = {k: bpy.data.images.load(v) for k, v in files.items()}
        w, hh = im["m"].size
        A = np.array(im["m"].pixels[:]).reshape(hh, w, 4)
        B = np.array(im["b"].pixels[:]).reshape(hh, w, 4)
        a = B[..., 3:4] * 0.85
        out = A.copy()
        out[..., :3] = A[..., :3] * 0.8 * (1 - a) + B[..., :3] * a
        res = bpy.data.images.new("comp", w, hh)
        res.pixels[:] = out.ravel()
        res.filepath_raw = f"{pre}_{view}.png"
        res.file_format = "PNG"
        res.save()
        for k, v in files.items():
            Path(v).unlink(missing_ok=True)
        shots.append(f"{pre}_{view}.png")
    rep["previews"] = shots
print("TEMPLATE_OK " + json.dumps(rep))
