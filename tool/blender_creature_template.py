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
    """a leg leads no skin of another leg: heat and its smoothing leak through the chest and the belly, and a right
    elbow's skin kept 4-10 % of the left upper arm - when the legs went apart (a gallop, a jump) its triangles
    stretched up to 4.8 times into spikes. Where two limbs share a vertex, a small share of another limb (under 20 % of
    the strongest one's) goes to the bone the strongest hangs from (the chest, the hips); toward an even share (the
    middle line between the legs: the brisket, the crotch) it is kept more and more, whole when even - so the skin
    there still follows both legs and nothing jumps where the strongest changes. (Giving each vertex to its strongest
    leg whole cut a seam down the brisket: 6.6 times there in the walk. Letting the strongest keep only what it has
    over the others gave the crotch to the hips - a steep step from the hips to the shin, 5.2 times in a turning
    gallop.)"""
    bones = arm_data.bones
    root_of = {}
    for b in bones:
        k = limb_of(b.name)
        if k and (b.parent is None or limb_of(b.parent.name) != k):
            root_of[k] = b.parent.name if b.parent else b.name

    def kept(r):   # of another limb's weight, what stays: none under 0.2 of the strongest, all of it at 0.8 and up
        t = min(1.0, max(0.0, (r - 0.2) / 0.6))
        return t * t * (3.0 - 2.0 * t)
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
            extra = 0.0
            for g in list(v.groups):
                k = limb_of(gn[g.group])
                if not k or k == keep:
                    continue
                share = kept(per[k] / per[keep])
                extra += g.weight * (1.0 - share)
                if share > 1e-4:
                    o.vertex_groups[g.group].add([v.index], g.weight * share, "REPLACE")
                else:
                    o.vertex_groups[g.group].remove([v.index])
            body = root_of.get(keep)
            if body and extra > 1e-6:
                vg = o.vertex_groups.get(body) or o.vertex_groups.new(name=body)
                old = next((g.weight for g in v.groups if g.group == vg.index), 0.0)
                vg.add([v.index], old + extra, "REPLACE")
                moved += 1
    return moved


rep["one_limb_vertices"] = one_limb()


def loose_pieces():
    """loose pieces (bristles, hair strips, a leg's fringe, tusks, horns, claws: islands of the skin welded by position,
    apart from the body - the biggest island and any island with a bone inside it, a tail made as a piece of its own)
    take the weights of the body skin they grow from. A short piece (under 12 % of the model's size: a strip, a tusk, a
    bristle) moves as one with the skin at its root (the third of the piece nearest the body). A long one (a fringe
    along a leg) takes the skin under each of its vertices, from the body part it grows from: the limbs holding 30 % of
    its root's weight and the body bones; the rest of a vertex's weight is its root's - so the fringe bends with the
    leg at the elbow and the wrist. (Heat finds no way into a closed small piece and gives it the nearest bones by
    distance: a chin's fringe went with the shoulders, the tusks with the shoulder blades. One set of weights for a
    long piece could not bend: a plate of the fringe under the wrist stayed with the forearm and stuck out when the
    wrist bent. The skin under every vertex of a short strip hanging under the belly by a thigh tore it 23 times.)"""
    from mathutils.bvhtree import BVHTree
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
    main = max(count, key=count.get)
    lo_, hi_ = {}, {}
    for i, c in enumerate(comp):
        p = pts[i]
        if c in lo_:
            lo_[c] = Vector(map(min, lo_[c], p))
            hi_[c] = Vector(map(max, hi_[c], p))
        else:
            lo_[c], hi_[c] = p.copy(), p.copy()
    # (a bone inside a piece: rays from points along the bone cross the piece an odd number of times in most of the six
    # directions - a closed tail around its bones; a fringe behind a leg has its box around the leg but not the bone)
    samples = [[(rig.matrix_world @ b.head_local).lerp(rig.matrix_world @ b.tail_local, t) for t in (0.25, 0.5, 0.75)]
               for b in arm_data.bones]
    polys = {}
    base = 0
    for o in meshes:
        for f in o.data.polygons:
            polys.setdefault(comp[base + f.vertices[0]], []).append([base + vi for vi in f.vertices])
        base += len(o.data.vertices)
    dirs = [Vector(d) for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1))]

    def holds_bone(c):
        pad = 1e-3 * size
        near = [sm for sm in samples if sum(all(lo_[c][i] - pad <= p[i] <= hi_[c][i] + pad for i in range(3)) for p in sm) >= 2]
        if not near:
            return False
        ids = sorted({i for f in polys.get(c, []) for i in f})
        at = {i: k for k, i in enumerate(ids)}
        bvh = BVHTree.FromPolygons([pts[i] for i in ids], [[at[i] for i in f] for f in polys.get(c, [])])

        def crossings(p, d):
            k = 0
            for _ in range(256):
                hit = bvh.ray_cast(p, d)
                if hit[0] is None:
                    break
                k += 1
                p = hit[0] + d * (1e-5 * size)
            return k
        inside = lambda p: sum(crossings(p, d) % 2 for d in dirs) >= 4  # noqa: E731
        return any(sum(inside(p) for p in sm) >= 2 for sm in near)
    pieces = {c for c in count if c != main and not holds_bone(c)}
    if not pieces:
        return 0
    groups = {o: {g.index: g.name for g in o.vertex_groups} for o in meshes}
    tree = KDTree(n)
    for i, p in enumerate(pts):
        if comp[i] not in pieces:
            tree.insert(p, i)
    tree.balance()
    by = {}
    for i in range(n):
        if comp[i] in pieces:
            by.setdefault(comp[i], []).append(i)

    def skin_at(p, k=4):   # the body skin's weights at a point: its k nearest vertices, nearer ones counting more
        acc = {}
        for _p, j, d in tree.find_n(p, k):
            o, vi = owner[j]
            w0 = 1.0 / (d + 1e-3 * size)
            for g in o.data.vertices[vi].groups:
                nm = groups[o][g.group]
                acc[nm] = acc.get(nm, 0.0) + g.weight * w0
        tot = sum(acc.values()) or 1.0
        return {nm: w / tot for nm, w in acc.items()}
    moved = 0
    for c, ids in by.items():
        near = sorted((tree.find(pts[i])[2], i) for i in ids)
        root_ids = [i for _d, i in near[:max(1, int(0.3 * len(near)))]]   # (the piece's root: its third nearest the body)
        root = {}
        for i in root_ids:
            for nm, w in skin_at(pts[i], 1).items():
                root[nm] = root.get(nm, 0.0) + w / len(root_ids)
        share = {}
        for nm, w in root.items():
            if limb_of(nm):
                share[limb_of(nm)] = share.get(limb_of(nm), 0.0) + w
        grows = {k for k, w in share.items() if w >= 0.3}
        short = (hi_[c] - lo_[c]).length < 0.12 * size   # (a strip, a tusk, a bristle: one piece with its root)
        for i in ids:
            under = {} if short else skin_at(pts[i])
            own = {nm: w for nm, w in under.items() if not limb_of(nm) or limb_of(nm) in grows}
            s_ = sum(own.values())
            mix = {nm: w for nm, w in own.items()}      # (s_ of the skin under it, the rest the root's)
            for nm, w in root.items():
                mix[nm] = mix.get(nm, 0.0) + (1.0 - s_) * w
            top = sorted(mix.items(), key=lambda x: -x[1])[:4]
            tot = sum(w for _n, w in top) or 1.0
            o, vi = owner[i]
            for g in list(o.data.vertices[vi].groups):
                o.vertex_groups[g.group].remove([vi])
            for nm, w in top:
                if w / tot > 1e-3:
                    (o.vertex_groups.get(nm) or o.vertex_groups.new(name=nm)).add([vi], w / tot, "REPLACE")
            moved += 1
    rep["loose_pieces"] = len(by)
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
