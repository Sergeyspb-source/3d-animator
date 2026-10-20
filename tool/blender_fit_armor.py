"""Runs INSIDE Blender (background): fit a static armour mesh onto a rigged, split body and skin it.

    blender -b -P blender_fit_armor.py -- body_parts.glb armour.glb slot out.glb [key=value ...]

slot: chest, helmet, gloves, boots, pants, bracers, pauldrons (see SLOTS).
Options: offset=0.006 (m, gap to the body), length=waist (chest/pants bottom landmark: chest, waist, hips, knees,
ankles), width=1.0, height=1.0, depth=1.0 (extra factors), up=0.0 (m, move up/down).
Steps: 1) place the armour between skeleton landmarks: chest goes from the collar (between shoulders and neck)
down to the chosen length, pants from the waist down; width/depth follow the body region; other slots use the
region bounding box,
2) push every armour vertex that is inside or too close to the body out along the body normal (no poke-through),
3) copy skin weights from the nearest body surface point (barycentric), 4) export armour + skeleton as GLB.
shrink=0 (0..1 smoothed shrinkwrap: pull vertices within shrink_reach=0.04 m back to the offset; shrink_smooth=10),
Prints lines starting with FIT_.
"""
import sys

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

argv = sys.argv[sys.argv.index("--") + 1:]
body_path, armour_path, slot, dst = argv[0], argv[1], argv[2], argv[3]
opt = dict(a.split("=", 1) for a in argv[4:] if "=" in a)
offset = float(opt.get("offset", 0.006))
length = opt.get("length", "")
f_width, f_height, f_depth = (float(opt.get(k, 1.0)) for k in ("width", "height", "depth"))
f_up = float(opt.get("up", 0.0))
f_scale = float(opt.get("scale", 1.0))   # overall size, all axes
mode = opt.get("mode", "landmarks")       # landmarks | uniform (keep the armour's own proportions)

SLOTS = {
    "chest": ["torso"],
    "helmet": ["head"],
    "head": ["head"],  # a whole replacement head (helmeted head, other ears, long hair): the body's head is hidden
    "gloves": ["hand_L", "hand_R"],
    "boots": ["foot_L", "foot_R"],
    "pants": ["pelvis", "leg_L", "leg_R"],
    "belt": ["pelvis"],
    "bracers": ["arm_L", "arm_R"],
    "pauldrons": ["torso", "arm_L", "arm_R"],
    "arms": ["arm_L", "arm_R", "hand_L", "hand_R"],  # a whole arm in one piece: pauldron, vambrace, gauntlet
}
regions = SLOTS[slot]
# body regions the armour may take skin weights from: a vest must not follow the thighs when a leg is lifted
WEIGHT_FROM = {
    "chest": ["torso", "pelvis"],
    "helmet": ["head"],
    "head": ["head"],
    "gloves": ["hand_L", "hand_R", "arm_L", "arm_R"],
    "boots": ["foot_L", "foot_R", "leg_L", "leg_R"],
    "pants": ["pelvis", "leg_L", "leg_R"],
    "belt": ["pelvis"],
    "arms": ["torso", "arm_L", "arm_R", "hand_L", "hand_R"],
    "bracers": ["arm_L", "arm_R", "hand_L", "hand_R"],
    "pauldrons": ["torso", "arm_L", "arm_R"],
}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=body_path)
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
body_parts = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups]  # skips the importer's bone-shape Icosphere
before = set(bpy.context.scene.objects)
bpy.ops.import_scene.gltf(filepath=armour_path)
new = [o for o in bpy.context.scene.objects if o not in before]
armour_meshes = [o for o in new if o.type == "MESH"]
for o in [o for o in armour_meshes if o.name.split(".")[0].endswith(("-colonly", "-convcolonly"))]:
    armour_meshes.remove(o)  # the item's own collision proxy is not part of the wearable mesh
    new.remove(o)
    bpy.data.objects.remove(o, do_unlink=True)
for o in new:  # throw away any skeleton the armour came with; it gets ours
    if o.type in ("ARMATURE", "EMPTY"):
        for c in o.children:
            mw = c.matrix_world.copy()
            c.parent = None
            c.matrix_world = mw
for o in new:
    if o.type in ("ARMATURE", "EMPTY"):
        bpy.data.objects.remove(o, do_unlink=True)
bpy.context.view_layer.update()
bpy.ops.object.select_all(action="DESELECT")
for o in armour_meshes:
    o.select_set(True)
    for m in list(o.modifiers):
        o.modifiers.remove(m)
    o.vertex_groups.clear()
bpy.context.view_layer.objects.active = armour_meshes[0]
if len(armour_meshes) > 1:
    bpy.ops.object.join()
armour = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
armour.name = f"Armor_{slot}"

# ---------------------------------------------------------------- 1. place on the slot regions
target = [o for o in body_parts if any(o.name == f"Body_{r}" or o.name.startswith(f"Body_{r}.") for r in regions)]
if not target:
    print("FIT_FAIL body has no parts for slot", slot, [o.name for o in body_parts])
    raise SystemExit


def bbox(objs):
    pts = [o.matrix_world @ v.co for o in objs for v in o.data.vertices]
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


tlo, thi = bbox(target)
alo, ahi = bbox([armour])
margin = 1.06


# ---- skeleton landmarks (heights in Blender Z, world space)
def _norm(name):
    n = name.lower()
    for sep in ("mixamorig:", "mixamorig_", "mixamorig."):
        n = n.replace(sep, "")
    return n


def joint_z(*names):
    zs = [(arm.matrix_world @ b.head_local).z for b in arm.data.bones if _norm(b.name) in names]
    return sum(zs) / len(zs) if zs else None


lm = dict(
    neck=joint_z("neck") or joint_z("head"),
    shoulder=joint_z("leftarm", "rightarm", "leftupperarm", "rightupperarm"),
    chest=joint_z("spine2", "upperchest"),
    waist=None,
    hips=joint_z("leftupleg", "rightupleg", "leftupperleg", "rightupperleg"),
    knees=joint_z("leftleg", "rightleg", "leftlowerleg", "rightlowerleg"),
    ankles=joint_z("leftfoot", "rightfoot"),
)
# The waist (belt line) is derived from proportions, not from spine joints: the auto-rigger places those
# inconsistently. Anatomically it sits about a third of the way from the hip joints up to the shoulders.
if lm["hips"] is not None and lm["shoulder"] is not None:
    lm["waist"] = lm["hips"] + 0.31 * (lm["shoulder"] - lm["hips"])
if lm["hips"] is not None and lm["knees"] is not None:
    lm["hips"] -= 0.25 * (lm["hips"] - lm["knees"])  # a bit below the hip joints, where a skirt or hem ends
print("FIT_LANDMARKS " + " ".join(f"{k}={v:.3f}" for k, v in lm.items() if v is not None))

# defaults: chest from the collar to the waist, pants from the waist to the ankles
SPAN = {"chest": ("collar", length or "waist"), "pants": ("waist", length or "ankles")}
span = SPAN.get(slot)
if span and lm["neck"] and lm["shoulder"]:
    lm["collar"] = (lm["neck"] + lm["shoulder"]) / 2
top_z = lm.get(span[0]) if span else None
bot_z = lm.get(span[1]) if span else None
tc, ac = (tlo + thi) / 2, (alo + ahi) / 2
sx = (thi.x - tlo.x) * margin / max(ahi.x - alo.x, 1e-6)
sy = (thi.y - tlo.y) * margin / max(ahi.y - alo.y, 1e-6)
sy = min(max(sy, sx * 0.6), sx * 1.6)  # generated depth is a guess: do not let it go wild
if mode == "uniform":
    # one scale for all axes taken from the body width: the armour keeps its own shape, hangs from the collar
    if opt.get("native") == "1":  # a kit item on its own kit body: the sheet already has the right size
        sx = 1.0
    sy = sx
    sz = sx
    anchor = "uniform" if opt.get("native") != "1" else "native"
    new_h0 = (ahi.z - alo.z) * sz
    tz = (top_z - new_h0 / 2) if top_z is not None else tc.z
elif top_z is not None and bot_z is not None and top_z > bot_z:
    # height between two landmarks, independent of the width: a human-proportioned vest gets shortened
    # (or lengthened) to the character instead of being scaled as a whole
    anchor = f"{span[0]}..{span[1]}"
    sz = (top_z - bot_z) / max(ahi.z - alo.z, 1e-6)
    tz = (top_z + bot_z) / 2
else:  # other slots: keep proportions, anchor per slot
    ANCHOR = {"pauldrons": "top", "boots": "bottom"}
    anchor = ANCHOR.get(slot, "centre")
    sz = sx
    new_h0 = (ahi.z - alo.z) * sz
    tz = (thi.z + (thi.z - tlo.z) * 0.04 - new_h0 / 2 if anchor == "top"
          else tlo.z - 0.003 + new_h0 / 2 if anchor == "bottom" else tc.z)
sx, sy, sz = sx * f_width * f_scale, sy * f_depth * f_scale, sz * f_height * f_scale
scale = Vector((sx, sy, sz))
new_h = (ahi.z - alo.z) * sz
if span and top_z is not None:
    tz = top_z - new_h / 2  # keep the collar where it is when the user changes the length factor
centre = Vector((tc.x, tc.y, tz + f_up))
if slot in ("helmet", "head") and mode != "keep":
    # the head's bounding box is dominated by the ears (and beard, nose): size the helmet on the skull instead,
    # the top third of the head, by its front-to-back depth, and sit the helmet's crown on top of it
    hp = [o.matrix_world @ v.co for o in target for v in o.data.vertices]
    top3 = [p for p in hp if p.z > thi.z - (thi.z - tlo.z) * 0.33]
    s_lo = Vector([min(p[i] for p in top3) for i in range(3)])
    s_hi = Vector([max(p[i] for p in top3) for i in range(3)])
    k = (s_hi.y - s_lo.y) * float(opt.get("fit_margin", 1.12)) / max(ahi.y - alo.y, 1e-6) * f_scale
    if slot == "head":  # a whole head: same height as the one it replaces (crown to beard tip)
        k = (thi.z - tlo.z) / max(ahi.z - alo.z, 1e-6) * f_scale
    scale = Vector((k * f_width, k * f_depth, k * f_height))
    new_h = (ahi.z - alo.z) * scale.z
    crown = thi.z - (thi.z - tlo.z) * float(opt.get("crown", -0.015))  # hair spikes stick up above the skull
    centre = Vector(((s_lo.x + s_hi.x) / 2, (s_lo.y + s_hi.y) / 2, crown - new_h / 2 + f_up))
    anchor = "skull"
if mode == "keep":
    # armour cut from a generated "goblin wearing it" and already aligned to this body: leave it where it is
    # (the size factor still works, hanging from the armour's top edge)
    anchor = "keep"
    scale = Vector((f_scale,) * 3)
    new_h = (ahi.z - alo.z) * f_scale
    centre = Vector((ac.x, ac.y, ahi.z - new_h / 2 + f_up))
for v in armour.data.vertices:
    p = v.co - ac
    v.co = centre + Vector((p.x * scale.x, p.y * scale.y, p.z * scale.z))
armour.data.update()
print(f"FIT_PLACE scale=({scale.x:.2f},{scale.y:.2f},{scale.z:.2f}) anchor={anchor} "
      f"target_size={tuple(round(x, 3) for x in (thi - tlo))} armour_height={new_h:.3f}")

# ---------------------------------------------------------------- 2. no poke-through
dg = bpy.context.evaluated_depsgraph_get()
all_verts, all_tris, owner = [], [], []
# a replacement head hides the body's own head: nothing to push it away from
# (and the neck of the torso part reaches up to the chin, it would flatten the new face): no push for it
push_parts = [] if slot == "head" else body_parts
for o in push_parts:
    base = len(all_verts)
    all_verts += [o.matrix_world @ v.co for v in o.data.vertices]
    for poly in o.data.polygons:
        vs = list(poly.vertices)
        for k in range(1, len(vs) - 1):
            all_tris.append((base + vs[0], base + vs[k], base + vs[k + 1]))
            owner.append((o, vs[0], vs[k], vs[k + 1]))
bvh = BVHTree.FromPolygons(all_verts, all_tris)
pushed = 0
for v in armour.data.vertices:
    loc, nrm, idx, dist = bvh.find_nearest(v.co)
    if loc is None:
        continue
    inside = (v.co - loc).dot(nrm) < offset
    if inside:
        v.co = loc + nrm * offset
        pushed += 1
armour.data.update()
print(f"FIT_PUSH moved={pushed} of {len(armour.data.vertices)} vertices out of the body (offset {offset * 1000:.0f} mm)")

# ---------------------------------------------------------------- 2a. optional smoothed shrinkwrap
# Push-out only moves vertices that are inside or too close. A generated piece that floats a few centimetres off
# the body (loose gaps under a vest, cuffs standing away from the wrist) stays there. shrink=1 pulls the vertices
# that are within shrink_reach of the body back to the offset distance. The pull is a displacement FIELD that is
# smoothed over the mesh (shrink_smooth rounds of neighbour averaging), so plates and decorations keep their shape
# and move together instead of being flattened onto the skin like a plain Shrinkwrap would do. Loose parts further
# than shrink_reach (skirts, capes) are left alone and the field fades out towards them.
shrink = float(opt.get("shrink", 0.0))
if shrink > 0 and push_parts:
    import bmesh

    reach = float(opt.get("shrink_reach", 0.04))
    rounds = int(opt.get("shrink_smooth", 10))
    me = armour.data
    n_v = len(me.vertices)
    disp = [Vector((0, 0, 0)) for _ in range(n_v)]
    weight = [0.0] * n_v
    gaps_before = []
    for v in me.vertices:
        loc, nrm, idx, dist = bvh.find_nearest(v.co)
        if loc is None:
            continue
        gap_now = (v.co - loc).dot(nrm)
        if gap_now <= offset or gap_now - offset > reach:
            continue
        gaps_before.append((v.index, gap_now))
        t = (gap_now - offset) / reach
        fall = 1.0 - t * t * (3.0 - 2.0 * t)      # smoothstep: full pull next to the body, none at the reach
        disp[v.index] = (loc + nrm * offset - v.co) * fall
        weight[v.index] = fall
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    neigh = [[e.other_vert(v).index for e in v.link_edges] for v in bm.verts]
    bm.free()
    for _ in range(rounds):
        nxt = []
        for i in range(n_v):
            if not neigh[i]:
                nxt.append(disp[i])
                continue
            acc = disp[i] * 2.0
            for j in neigh[i]:
                acc += disp[j]
            nxt.append(acc / (2.0 + len(neigh[i])))
        disp = nxt
    moved = 0
    for v in me.vertices:
        d = disp[v.index] * shrink
        if d.length > 1e-5:
            v.co += d
            moved += 1
    me.update()
    again = 0
    for v in me.vertices:                         # the field is smooth, not exact: never leave a vertex inside the body
        loc, nrm, idx, dist = bvh.find_nearest(v.co)
        if loc is not None and (v.co - loc).dot(nrm) < offset:
            v.co = loc + nrm * offset
            again += 1
    me.update()
    gaps_after = []
    for index, _ in gaps_before:
        v = me.vertices[index]
        loc, nrm, idx, dist = bvh.find_nearest(v.co)
        gaps_after.append((v.co - loc).dot(nrm) if loc is not None else 0.0)
    mb = sum(g for _, g in gaps_before) / len(gaps_before) * 1000 if gaps_before else 0.0
    ma = sum(gaps_after) / len(gaps_after) * 1000 if gaps_after else 0.0
    print(f"FIT_SHRINK pulled={moved} (re-pushed {again}) vertices within {reach * 1000:.0f} mm, "
          f"mean gap of the near vertices before {mb:.1f} mm, after {ma:.1f} mm")

# ---------------------------------------------------------------- 2b. volume down to the body
# Generated armour is a thin open shell. Give it thickness inward, down to the body (minus a small gap): the
# inner wall then sits on the skin, so openings show armour instead of a void, and skin that moves has to get
# through the whole thickness before it shows. Far-off parts (a flared skirt) only get the minimum thickness.
fill = opt.get("fill", "1") != "0" and slot not in ("head",) and push_parts
if fill:
    import bmesh

    bm = bmesh.new()
    bm.from_mesh(armour.data)
    open_shell = any(e.is_boundary for e in bm.edges)
    bm.free()
    if not open_shell:
        print("FIT_FILL skipped: the mesh is already closed (has its own thickness)")
        fill = False
if fill:
    t_min, t_max, gap = (float(opt.get(k, d)) for k, d in (("fill_min", 0.003), ("fill_max", 0.03),
                                                              ("fill_gap", 0.002)))
    me = armour.data
    me.update()
    # depth is measured to the slot's own body regions only (a pauldron's top edge must not reach for the neck)
    fv, ft = [], []
    for o in body_parts:
        if not any(o.name == f"Body_{r}" or o.name.startswith(f"Body_{r}.") for r in WEIGHT_FROM[slot]):
            continue
        base = len(fv)
        fv += [o.matrix_world @ v.co for v in o.data.vertices]
        for poly in o.data.polygons:
            vs = list(poly.vertices)
            for k in range(1, len(vs) - 1):
                ft.append((base + vs[0], base + vs[k], base + vs[k + 1]))
    fbvh = BVHTree.FromPolygons(fv, ft) if ft else bvh
    toward, depth, inward = 0, [], []
    for v in me.vertices:
        loc, nrm, idx, dist = fbvh.find_nearest(v.co)
        if loc is None:
            depth.append(t_min)
            inward.append(-v.normal)
            continue
        inward.append((loc - v.co).normalized() if dist > 1e-6 else -nrm)
        if (loc - v.co).dot(v.normal) < 0:
            toward += 1  # the normal points away from the body: outward, as it should
        d = dist - gap
        depth.append(t_min if d > t_max else max(t_min, d))
    if toward < len(me.vertices) / 2:  # the shell's normals point inward: flip so "inside" is toward the body
        for p in me.polygons:
            p.flip()
        me.update()
    # inner wall built by hand (the Solidify modifier blows up on the degenerate triangles of generated meshes):
    # every vertex gets a twin moved inward along its smoothed normal by exactly its own depth, rims close the edges
    bm = bmesh.new()
    bm.from_mesh(me)
    bm.verts.ensure_lookup_table()
    bm.normal_update()
    nrm = []
    for v in bm.verts:  # normal averaged with the neighbours: no wild directions on slivers
        n = v.normal.copy()
        for e in v.link_edges:
            n += e.other_vert(v).normal
        nrm.append(n.normalized() if n.length > 1e-9 else Vector((0, 0, 1)))
    n0 = len(bm.verts)
    # straight toward the nearest body point (generated shells have patches of flipped normals), blended with
    # the smoothed normal so neighbouring twins do not bunch up on the same body point
    twin = []
    for i, v in enumerate(bm.verts[:n0]):
        d = (inward[i] * 0.7 - nrm[i] * 0.3)
        d = d.normalized() if d.length > 1e-9 else inward[i]
        if d.dot(inward[i]) < 0.3:
            d = inward[i]
        twin.append(bm.verts.new(v.co + d * depth[i]))
    bm.verts.ensure_lookup_table()
    outer_faces = list(bm.faces)
    uvl = bm.loops.layers.uv.active
    for f in outer_faces:
        g = bm.faces.new([twin[v.index] for v in reversed(f.verts)])
        g.material_index = f.material_index
        if uvl:
            for lo, li in zip(g.loops, reversed(f.loops)):
                lo[uvl].uv = li[uvl].uv
    for e in [e for e in bm.edges if e.is_boundary and e.verts[0].index < n0 and e.verts[1].index < n0]:
        a, b = e.verts
        f = e.link_faces[0]
        # keep the rim's winding consistent with the outer face that owns the edge
        la = next(l for l in f.loops if l.vert is a)
        if la.link_loop_next.vert is not b:
            a, b = b, a
        try:
            rf = bm.faces.new([b, a, twin[a.index], twin[b.index]])
            rf.material_index = f.material_index
            if uvl:
                ua = next(l for l in f.loops if l.vert is a)[uvl].uv
                ub = next(l for l in f.loops if l.vert is b)[uvl].uv
                for lo, uv in zip(rf.loops, (ub, ua, ua, ub)):
                    lo[uvl].uv = uv
        except ValueError:
            pass
    bm.to_mesh(me)
    bm.free()
    me.update()
    dd = sorted(depth)
    print(f"FIT_FILL thickness median {dd[len(dd) // 2] * 1000:.1f} mm, 90% {dd[int(len(dd) * 0.9)] * 1000:.1f} mm, "
          f"vertices {n0} -> {len(armour.data.vertices)}")

# ---------------------------------------------------------------- 3. weights from the nearest body point
names_cache = {}


def wts(o, vi):
    if o.name not in names_cache:
        names_cache[o.name] = {vg.index: vg.name for vg in o.vertex_groups}
    nm = names_cache[o.name]
    return {nm[g.group]: g.weight for g in o.data.vertices[vi].groups if g.weight > 1e-5}


src_parts = [o for o in body_parts
              if any(o.name == f"Body_{r}" or o.name.startswith(f"Body_{r}.") for r in WEIGHT_FROM[slot])]
w_verts, w_tris, w_owner = [], [], []
for o in src_parts:
    base = len(w_verts)
    w_verts += [o.matrix_world @ v.co for v in o.data.vertices]
    for poly in o.data.polygons:
        vs = list(poly.vertices)
        for k in range(1, len(vs) - 1):
            w_tris.append((base + vs[0], base + vs[k], base + vs[k + 1]))
            w_owner.append((o, vs[0], vs[k], vs[k + 1]))
wbvh = BVHTree.FromPolygons(w_verts, w_tris)
for v in armour.data.vertices:
    loc, nrm, idx, dist = wbvh.find_nearest(v.co)
    if idx is None:
        continue
    o, a, b, c = w_owner[idx]
    pa, pb, pc = (o.matrix_world @ o.data.vertices[i].co for i in (a, b, c))
    bary = barycentric_transform(loc, pa, pb, pc, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
    acc = {}
    for wgt, vi in zip(bary, (a, b, c)):
        for bone, w in wts(o, vi).items():
            acc[bone] = acc.get(bone, 0.0) + max(wgt, 0.0) * w
    tot = sum(acc.values()) or 1.0
    for bone, w in acc.items():
        if w / tot > 1e-3:
            vg = armour.vertex_groups.get(bone) or armour.vertex_groups.new(name=bone)
            vg.add([v.index], w / tot, "REPLACE")
mod = armour.modifiers.new("Armature", "ARMATURE")
mod.object = arm
armour.parent = arm
armour.matrix_parent_inverse = arm.matrix_world.inverted()
print(f"FIT_SKIN groups={len(armour.vertex_groups)}")

# ---------------------------------------------------------------- 3b. neck plug for a replacement head
# The body's own head (with its beard covering the throat) gets hidden, and a generated head ends at the chin:
# extrude the open top edge of the visible body (torso/neck) up into the new head, textured with the body's skin.
if slot == "head" and opt.get("neck_plug", "1") != "0":
    import bmesh

    bones = {_norm(b.name): b for b in arm.data.bones}
    nb_, hb_ = bones.get("neck"), bones.get("head")
    if nb_ and hb_:
        nj, hj = arm.matrix_world @ nb_.head_local, arm.matrix_world @ hb_.head_local
        ax = Vector(((nj.x + hj.x) / 2, (nj.y + hj.y) / 2, 0))
        top_z = hj.z + float(opt.get("plug_up", 0.03))
        r_top = float(opt.get("plug_r", 0.045))  # the plug narrows to a neck inside the new head
        pv, pf, puv, pw, mats, fmat = [], [], [], [], [], []
        key = {}
        # only the seam with the hidden head: parts are separate meshes, so the arm/torso seams are open edges too
        seam = {tuple(round(c, 4) for c in (o.matrix_world @ v.co)) for o in target for v in o.data.vertices}
        for o in body_parts:
            if o in target:
                continue
            bm = bmesh.new()
            bm.from_mesh(o.data)
            uvl = bm.loops.layers.uv.active
            mi = None
            for e in bm.edges:
                if not e.is_boundary:
                    continue
                pa, pb = (o.matrix_world @ v.co for v in e.verts)
                if not all(tuple(round(c, 4) for c in p) in seam for p in (pa, pb)):
                    continue
                if max((Vector((p.x, p.y, 0)) - ax).length for p in (pa, pb)) > 0.2:
                    continue
                f = e.link_faces[0]
                uv = {l.vert.index: tuple(l[uvl].uv) for l in f.loops} if uvl else {}
                if mi is None:
                    mats.append(o.data.materials[0] if o.data.materials else None)
                    mi = len(mats) - 1
                ids = []
                for v, p in zip(e.verts, (pa, pb)):
                    k = (o.name, v.index)
                    if k not in key:
                        key[k] = (len(pv), len(pv) + 1)
                        d = Vector((p.x, p.y, 0)) - ax
                        d = d.normalized() * min(d.length, r_top) if d.length > 1e-6 else d
                        pv += [p, Vector((ax.x + d.x, ax.y + d.y, top_z))]
                        puv += [uv.get(v.index, (0, 0))] * 2
                        pw += [wts(o, v.index), {hb_.name: 1.0}]
                    ids.append(key[k])
                (a0, a1), (b0, b1) = ids
                # outward winding: the face normal must point away from the neck axis
                n = (pv[b0] - pv[a0]).cross(pv[a1] - pv[a0])
                mid = (pv[a0] + pv[b0]) / 2
                face = [a0, b0, b1, a1] if n.dot(Vector((mid.x - ax.x, mid.y - ax.y, 0))) > 0 else [a0, a1, b1, b0]
                pf.append(face)
                fmat.append(mi)
            bm.free()
        if pf:
            pm = bpy.data.meshes.new("NeckPlug")
            pm.from_pydata([tuple(p) for p in pv], [], pf)
            uvlay = pm.uv_layers.new(name="UVMap")
            for poly in pm.polygons:
                for li in poly.loop_indices:
                    uvlay.data[li].uv = puv[pm.loops[li].vertex_index]
            for m in mats:
                pm.materials.append(m)
            pm.polygons.foreach_set("material_index", fmat)
            plug = bpy.data.objects.new("NeckPlug", pm)
            bpy.context.scene.collection.objects.link(plug)
            for i, w in enumerate(pw):
                for bone, x in w.items():
                    vg = plug.vertex_groups.get(bone) or plug.vertex_groups.new(name=bone)
                    vg.add([i], x, "REPLACE")
            bpy.ops.object.select_all(action="DESELECT")
            plug.select_set(True)
            armour.select_set(True)
            bpy.context.view_layer.objects.active = armour
            bpy.ops.object.join()
            print(f"FIT_NECK_PLUG faces={len(pf)} from the open top of the body, up to z={top_z:.3f}")
        else:
            print("FIT_NECK_PLUG none: no open body edge around the neck")

# ---------------------------------------------------------------- 3c. which body vertices the armour covers
# A ray from every body vertex along its normal: if it meets this armour within mask_dist, the skin there is
# under the armour and the game can drop those triangles while the item is worn (no poke-through, less to draw).
# The covered zone is shrunk by mask_erode rings so skin stays at openings (armholes, collar, hem).
# Written to <dst stem>.mask.json as glTF mesh-space vertex positions per body part (vertex order may change on
# import, positions do not), quantised to 0.1 mm.
if opt.get("mask", "1") != "0" and slot != "head":
    import json
    from pathlib import Path

    dg = bpy.context.evaluated_depsgraph_get()
    am = armour.evaluated_get(dg).to_mesh()
    abvh = BVHTree.FromPolygons([armour.matrix_world @ v.co for v in am.vertices],
                                [tuple(p.vertices) for p in am.polygons])
    reach = float(opt.get("mask_dist", 0.05))
    erode = int(opt.get("mask_erode", 1))
    near_dist = float(opt.get("mask_near", 0.012))
    mask, n_cov, n_all = {}, 0, 0
    for o in body_parts:
        # only regions the item moves with: a skirt follows the pelvis, so a lifted thigh comes out from under it
        if not any(o.name == f"Body_{r}" or o.name.startswith(f"Body_{r}.") for r in WEIGHT_FROM[slot]):
            continue
        rot = o.matrix_world.to_3x3()
        me = o.data
        cov = set()
        for v in me.vertices:
            p = o.matrix_world @ v.co
            n = (rot @ v.normal).normalized()
            # along the normal, or armour lying right on the skin at a slant (shoulders under a strap)
            if abvh.ray_cast(p + n * 0.0005, n, reach)[0] is not None or \
                    abvh.find_nearest(p, near_dist)[0] is not None:
                cov.add(v.index)
        if not cov:
            continue
        nb = [[] for _ in me.vertices]
        for e in me.edges:
            a, b = e.vertices
            nb[a].append(b)
            nb[b].append(a)
        for _ in range(erode):
            cov = {i for i in cov if all(j in cov for j in nb[i])}
        if not cov:
            continue
        # Blender (x, y, z) -> glTF (x, z, -y), in the mesh's own space
        mask[o.name.split(".")[0]] = sorted({(round(me.vertices[i].co.x * 1e4), round(me.vertices[i].co.z * 1e4),
                                              round(-me.vertices[i].co.y * 1e4)) for i in cov})
        n_cov += len(cov)
        n_all += len(me.vertices)
    Path(dst).with_suffix(".mask.json").write_text(json.dumps(dict(unit=1e-4, covers=mask)), encoding="utf-8")
    print(f"FIT_MASK covered {n_cov} body vertices in {len(mask)} parts: "
          + ", ".join(f"{k}={len(v)}" for k, v in mask.items()))

# ---------------------------------------------------------------- 4. export armour + skeleton only
for o in body_parts:
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", export_skins=True, export_animations=False)
print("FIT_OK", dst, "hides:", ",".join(f"Body_{r}" for r in regions))
