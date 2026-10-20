"""Runs INSIDE Blender (background): cut a real mouth into a rigged closed-mouth head and fill it.

    blender -b -P blender_mouth_cut.py -- job.json

job.json: {"source": rigged.glb, "out": out.glb, "mouth_c", "corner_L", "corner_R": [x,y,z] glTF (surface points),
           "hinge": [x,y,z] glTF (jaw joint, optional), "head_bone", "jaw_bone" (optional), "teeth_glb", "tongue_glb",
           "kit": {"arch_width": 0.05}, "lip_colour": [r,g,b] (optional), "open_deg": 22, "preview": png, "report": json}

Recipe of the game's 3d-animator facial-rig.md §16, for gameplay distance:
1. cut exactly along the lip line (the parabola through the right corner, the centre and the left corner, front view):
   every front edge the line crosses is split at the crossing (UVs and skin weights interpolated), faces are joined
   along the line and the line edges are split open; the corners stay joined.
2. roll the lips inward: two rings from each slit edge back into the head, curling up into the upper lip and down
   into the lower, flat at the corners; the roll gets its own lip material.
3. one skinned cavity cup behind the lips (roof on the head, floor on the jaw, blended), dark inside.
4. the face-parts teeth and tongue scaled to the mouth width behind the lips: upper teeth + gum on the head, lower
   teeth + gum + tongue on the jaw.
5. shape keys with the mouth plate's names, so lip sync is the same: jawOpen = everything on the jaw turned about
   the hinge; mouthSmile, mouthStretch, mouthFunnel, mouthPucker, mouthUpperUp, mouthLowerDown move the lips.
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))


def fail(msg):
    print("CUT_FAIL " + msg, flush=True)
    sys.exit(1)


def bl(p):
    return Vector((p[0], -p[2], p[1]))


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["source"])
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for o in list(bpy.data.objects):
    if o.type == "MESH" and (not o.vertex_groups or o.name.startswith("Mouth")):
        d = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.meshes.remove(d)
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
HEAD, JAW = job["head_bone"], job.get("jaw_bone") or job["head_bone"]

M, CL, CR = bl(job["mouth_c"]), bl(job["corner_L"]), bl(job["corner_R"])
W = (CL - CR).length
if W <= 0:
    fail("нулевая ширина рта")
for c in (CL, CR):
    if abs(c.z - M.z) > 0.6 * W:
        fail("уголки рта не на линии губ: переразметьте лицо")
hinge = bl(job["hinge"]) if job.get("hinge") else Vector((M.x, M.y + 1.2 * W, M.z + 0.5 * W))
import numpy as np
def lip_curve(pts):
    """front-view lip line z(x) through all given points: parabola for 3, a Catmull-Rom curve (sampled densely, then
    interpolated) for 4+ points, so mid-lip clicks follow a cupid's bow or a sneer."""
    pts = sorted(pts, key=lambda p: p.x)
    xs_, zs_ = [p.x for p in pts], [p.z for p in pts]
    if len(pts) <= 3:
        c = np.polyfit(xs_, zs_, 2)
        return lambda x: float(np.polyval(c, x))
    ext = [pts[0] * 2 - pts[1]] + pts + [pts[-1] * 2 - pts[-2]]
    sx, sz = [], []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for k in range(24):
            t = k / 24
            q = 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
            sx.append(q.x); sz.append(q.z)
    sx.append(pts[-1].x); sz.append(pts[-1].z)
    order = np.argsort(sx)
    sx, sz = np.array(sx)[order], np.array(sz)[order]
    return lambda x: float(np.interp(x, sx, sz))


LIP_PTS = [CR, M, CL] + [bl(job[k]) for k in ("mid_L", "mid_R") if job.get(k)]
line_z = lip_curve(LIP_PTS)
x0, x1 = min(CR.x, CL.x), max(CR.x, CL.x)
cx = (x0 + x1) / 2


def side(p):
    return p.z - line_z(p.x)


front_limit = max(CL.y, CR.y) + 0.35 * W          # only the front skin around the mouth is cut (Blender: forward = -y)

face = max((o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups),
           key=lambda o: sum(1 for v in o.data.vertices if ((o.matrix_world @ v.co) - M).length < W))
fw, finv = face.matrix_world, face.matrix_world.inverted()
report = {"mouth_width": round(W, 4)}

# the skin before cutting: everything put inside the mouth must stay behind it
from mathutils.bvhtree import BVHTree
face.data.calc_loop_triangles()
_wv = [fw @ v.co for v in face.data.vertices]
skin_bvh = BVHTree.FromPolygons(_wv, [tuple(t.vertices) for t in face.data.loop_triangles])
_ymin = min(v.y for v in _wv)


def skin_y(x, z):
    """depth (Blender y) of the outer skin seen from the front at (x, z), or None"""
    h = skin_bvh.ray_cast(Vector((x, _ymin - W * 20, z)), Vector((0, 1, 0)), W * 80)
    return None if h[0] is None else h[0].y


# ------------------------------------------------------------------ 1. cut along the line
bm = bmesh.new(); bm.from_mesh(face.data)
dl = bm.verts.layers.deform.verify()
P = lambda v: fw @ v.co
gi = {g.name: g.index for g in face.vertex_groups}
if HEAD not in gi:
    fail("у лица нет веса головы " + HEAD)
if JAW not in gi:
    face.vertex_groups.new(name=JAW); gi[JAW] = face.vertex_groups[JAW].index


def in_zone(p):
    return x0 + W * 0.01 < p.x < x1 - W * 0.01 and p.y < front_limit and abs(side(p)) < 0.35 * W


cross = []
for e in bm.edges:
    a, b = P(e.verts[0]), P(e.verts[1])
    sa, sb = side(a), side(b)
    if sa * sb < 0 and (in_zone(a) or in_zone(b)):
        t = sa / (sa - sb)
        q = a.lerp(b, t)
        if x0 + W * 0.01 < q.x < x1 - W * 0.01 and q.y < front_limit:
            cross.append((e, t))
new_verts = set()
for e, t in cross:
    v0 = e.verts[0]
    ne, nv = bmesh.utils.edge_split(e, v0, t)
    new_verts.add(nv)
for v in bm.verts:   # original vertices lying on the line itself are cut points too (else their faces bridge the slit)
    p = P(v)
    if abs(side(p)) < W * 0.004 and in_zone(p):
        new_verts.add(v)
report["crossed_edges"] = len(cross)
if len(new_verts) < 6:
    fail(f"линия рта пересекла только {len(new_verts)} рёбер: точки рта не на губах?")
bm.faces.ensure_lookup_table()
line_edges = set()
for f in list(bm.faces):
    nv = [v for v in f.verts if v in new_verts]
    if len(nv) > 2:
        nv = max(((x, y) for i, x in enumerate(nv) for y in nv[i + 1:]), key=lambda ab: (P(ab[0]) - P(ab[1])).length)
        nv = list(nv)
    if len(nv) == 2 and not any(nv[1] in e.verts for e in nv[0].link_edges):
        r = bmesh.ops.connect_verts(bm, verts=nv)
        for e in r["edges"]:
            line_edges.add(e)
report["line_edges"] = len(line_edges)
for e in bm.edges:
    if all(v in new_verts for v in e.verts) and all(abs(side(P(v))) < W * 0.004 for v in e.verts):
        line_edges.add(e)
res = bmesh.ops.split_edges(bm, edges=[e for e in line_edges if e.is_valid])
# classify the copies on the line: upper lip or lower lip, from their faces
bm.verts.ensure_lookup_table()
on_line = [v for v in bm.verts if (abs(side(P(v))) < W * 0.004 and in_zone(P(v))) or v in new_verts]
upper, lower = [], []
for v in set(on_line):
    if not v.link_faces:
        continue
    c = sum((fw @ f.calc_center_median() for f in v.link_faces), Vector()) / len(v.link_faces)
    (upper if side(c) > 0 else lower).append(v)


def copy_weights(v, from_side):
    """weights of the nearest connected neighbour on the given side (the cut verts must not mix head and jaw)"""
    best, bd = None, 1e9
    for e in v.link_edges:
        o = e.other_vert(v)
        sp = side(P(o))
        if (sp > 0) == (from_side > 0) and abs(sp) > W * 1e-4:
            d = (P(o) - P(v)).length
            if d < bd:
                best, bd = o, d
    if best is not None:
        v[dl].clear()
        for k, w in best[dl].items():
            v[dl][k] = w


# faces the line crossed through a vertex stay joined across the slit and stretch into a rod when the jaw opens
bridge = []
for f in bm.faces:
    ps = [P(v) for v in f.verts]
    if all(in_zone(p) for p in ps) and max(side(p) for p in ps) > W * 0.004 and min(side(p) for p in ps) < -W * 0.004             and abs(sum(p.x for p in ps) / len(ps) - cx) < (x1 - x0) / 2 - 0.08 * W:
        bridge.append(f)
bmesh.ops.delete(bm, geom=bridge, context="FACES")
report["bridge_faces_removed"] = len(bridge)
upper = [v for v in upper if v.is_valid]; lower = [v for v in lower if v.is_valid]
for v in upper:
    copy_weights(v, 1)
for v in lower:
    copy_weights(v, -1)
report["lip_verts"] = {"upper": len(upper), "lower": len(lower)}
# the upper lip belongs to the head: any jaw weight above the slit (seen on UV-seam twins) goes to the head
hj, jj = gi[HEAD], gi[JAW]
upper_set = set(upper)   # the upper copies on the slit too: on a UV seam they may have no upper neighbour to copy
fixed = 0
if HEAD != JAW:
    for v in bm.verts:
        p = P(v)
        if (v in upper_set) or (side(p) > W * 0.004 and abs(p.x - cx) < 0.55 * (x1 - x0) and p.y < front_limit and side(p) < 0.6 * W):
            w = v[dl].get(jj, 0.0)
            if w > 0:
                v[dl][hj] = v[dl].get(hj, 0.0) + w
                del v[dl][jj]
                fixed += 1
report["upper_lip_jaw_cleared"] = fixed
# smooth the jaw weight below the lower lip and beside the corners (the chin underside sheared into fins when the
# weight dropped fast toward the neck); the slit copies keep theirs. Neighbours include UV-seam twins.
if HEAD != JAW:
    from collections import defaultdict
    twins = defaultdict(list)
    q = W * 1e-3
    for v in bm.verts:
        twins[tuple(round(c / q) for c in v.co)].append(v)
    keep = set(upper) | set(lower)
    zone = [v for v in bm.verts if v not in keep and (P(v) - M).length < 2.2 * W and side(P(v)) < 0.6 * W]
    for _ in range(12):
        new = {}
        for v in zone:
            nb = [e.other_vert(v) for e in v.link_edges]
            for t in twins[tuple(round(c / q) for c in v.co)]:
                if t is not v:
                    nb += [e.other_vert(t) for e in t.link_edges]
            if not nb:
                continue
            avg = sum(n[dl].get(jj, 0.0) for n in nb) / len(nb)
            new[v] = 0.5 * v[dl].get(jj, 0.0) + 0.5 * avg
        for v, w in new.items():
            if side(P(v)) > 0 and abs(P(v).x - cx) < 0.55 * (x1 - x0):
                continue     # never give the upper lip a jaw weight
            old = v[dl].get(jj, 0.0)
            if abs(w - old) < 1e-6:
                continue
            v[dl][jj] = w
            v[dl][hj] = max(0.0, v[dl].get(hj, 0.0) - (w - old))
    report["jaw_smoothed_verts"] = len(zone)
    # the lower lip itself goes fully with the jaw (fading over 0.35 W below the slit), so the mouth opens wide
    lips = 0
    for v in bm.verts:
        p = P(v); d = -side(p)
        if v not in upper_set and 0 <= d < 0.6 * W and abs(p.x - cx) < 0.5 * (x1 - x0) and p.y < front_limit:
            u = abs(p.x - cx) / (0.5 * (x1 - x0))
            target = (1.0 - max(0.0, (d - 0.35 * W) / (0.25 * W))) * (1 - u ** 4)
            old = v[dl].get(jj, 0.0)
            if target > old:
                v[dl][jj] = target
                v[dl][hj] = max(0.0, v[dl].get(hj, 0.0) - (target - old))
                lips += 1
    report["lower_lip_full_jaw"] = lips

# ------------------------------------------------------------------ 2. roll the lips inward
lip_mat = bpy.data.materials.new("lip_inner"); lip_mat.use_nodes = True
lb = next(n for n in lip_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
lb.inputs["Base Color"].default_value = (*job.get("lip_colour", [0.45, 0.16, 0.16]), 1)
lb.inputs["Roughness"].default_value = 0.35
face.data.materials.append(lip_mat)
lip_idx = len(face.data.materials) - 1
boundary = [e for e in bm.edges if e.is_boundary and all(v in set(upper) | set(lower) for v in e.verts)]
roll_faces = []
for verts_side, sgn in ((set(upper), 1), (set(lower), -1)):
    edges = [e for e in boundary if all(v in verts_side for v in e.verts)]
    for ring, (back, curl) in enumerate(((0.16, 0.05), (0.30, 0.10))):
        if not edges:
            break
        ext = bmesh.ops.extrude_edge_only(bm, edges=edges)
        nv = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMVert)]
        ne = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMEdge)]
        nf = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMFace)]
        for v in nv:
            p = P(v)
            u = (p.x - x0) / max(x1 - x0, 1e-9)
            prof = math.sin(math.pi * max(0.0, min(1.0, u))) ** 0.6     # flat at the corners
            step_back = (0.16 if ring == 0 else 0.14) * W * prof
            step_curl = (0.05 if ring == 0 else 0.05) * W * prof * sgn
            q = p + Vector((0, step_back, step_curl))
            sy = skin_y(q.x, q.z)          # thin, back-sloping lips: keep the roll under the skin
            if sy is not None and q.y < sy + 0.04 * W:
                q.y = sy + 0.04 * W
            v.co = finv @ q
        for f in nf:
            f.material_index = lip_idx
            roll_faces.append(f)
        edges = [e for e in ne if e.is_boundary and all(v in nv for v in e.verts)]
bm.normal_update()
bm.to_mesh(face.data); bm.free()
report["roll_faces"] = len(roll_faces)

# ------------------------------------------------------------------ 3. cavity cup
def jaw_blend(z, zc, band):
    return max(0.0, min(1.0, 0.5 - (z - zc) / (2 * band)))


def skin(o, fn):
    """vertex groups head/jaw from fn(world point) -> jaw weight; armature modifier on arm"""
    gh, gj = o.vertex_groups.new(name=HEAD), (o.vertex_groups.new(name=JAW) if JAW != HEAD else None)
    for v in o.data.vertices:
        w = fn(o.matrix_world @ v.co) if gj else 0.0
        if 1 - w > 1e-4:
            gh.add([v.index], 1 - w, "REPLACE")
        if gj and w > 1e-4:
            gj.add([v.index], w, "REPLACE")
    m = o.modifiers.new("Armature", "ARMATURE"); m.object = arm
    o.parent = arm; o.matrix_parent_inverse = arm.matrix_world.inverted()


cav_c = Vector((cx, M.y + 0.42 * W, line_z(cx) - 0.04 * W))
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
cav = bpy.context.active_object; cav.name = cav.data.name = "MouthCavity"
cav.data.transform(Matrix.Diagonal((0.52 * W, 0.50 * W, 0.40 * W, 1)))
bm = bmesh.new(); bm.from_mesh(cav.data)
bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.calc_center_median().y < -0.30 * W], context="FACES")
bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
bm.to_mesh(cav.data); bm.free()
cav.location = cav_c
bpy.ops.object.transform_apply(location=True)
for v in cav.data.vertices:          # the cup must not poke out through the (recessed) skin around the lips
    sy = skin_y(v.co.x, v.co.z)
    if sy is not None and v.co.y < sy + 0.04 * W:
        v.co.y = sy + 0.04 * W
cmat = bpy.data.materials.new("mouth_cavity"); cmat.use_nodes = True
cb = next(n for n in cmat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
cb.inputs["Base Color"].default_value = (0.08, 0.025, 0.025, 1); cb.inputs["Roughness"].default_value = 0.35
cav.data.materials.append(cmat)
for p_ in cav.data.polygons:
    p_.use_smooth = True
# what the lower lip skin really gets from the jaw: inner parts on the jaw use the same, so they open together
_jg = face.vertex_groups.get(JAW)
_ws = [next((g.weight for g in v.groups if _jg is not None and g.group == _jg.index), 0.0)
       for v in face.data.vertices
       if abs((fw @ v.co).x - cx) < 0.3 * W and -0.35 * W < side(fw @ v.co) < -0.03 * W and (fw @ v.co).y < front_limit]
JAW_IN = 0.95 * ((sum(_ws) / len(_ws)) if _ws else 1.0)   # with the lower lip, a touch less so the teeth stay inside the chin
report["lower_lip_jaw_weight"] = round(JAW_IN, 3)
skin(cav, lambda p: JAW_IN * jaw_blend(p.z, line_z(cx), 0.08 * W))

# ------------------------------------------------------------------ 4. teeth and tongue
kit_w = float(job.get("kit", {}).get("arch_width", 0.05))
s = W * 0.95 / kit_w
anchor = Vector((cx, M.y + 0.10 * W, line_z(cx)))
parts = []
for path in (job.get("teeth_glb"), job.get("tongue_glb")):
    if not path or not Path(path).exists():
        continue
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    for o in set(bpy.data.objects) - before:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True); continue
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        o.matrix_world = Matrix.Translation(anchor) @ Matrix.Scale(s, 4) @ o.matrix_world
        bpy.ops.object.select_all(action="DESELECT"); o.select_set(True)
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
        parts.append(o)
for o in parts:
    on_jaw = o.name.startswith(("Teeth_Lower", "Gum_Lower", "Tongue"))
    skin(o, lambda p, j=on_jaw: JAW_IN if j else 0.0)
# push each row back until no vertex is in front of the skin (recessed chins, sloping lips); upper and lower apart,
# so a recessed chin does not hide the upper teeth from the side
groups = {"upper": [o for o in parts if o.name.startswith(("Teeth_Upper", "Gum_Upper"))],
          "lower": [o for o in parts if not o.name.startswith(("Teeth_Upper", "Gum_Upper"))]}
pushed = {}
for gname, objs in groups.items():
    lift = 0.045 * W if gname == "lower" else 0.0
    need = 0.0
    for o in objs:
        for v in list(o.data.vertices)[::3]:
            p = o.matrix_world @ v.co + Vector((0, 0, lift if not o.name.startswith("Tongue") else 0.0))
            # upper row against the skin above the slit, lower row below it: fang tips that hang past the line may
            # show over the other lip, as on a real fanged mouth
            if (gname == "upper" and side(p) < 0.02 * W) or (gname == "lower" and side(p) > -0.02 * W):
                continue
            sy = skin_y(p.x, p.z)
            if sy is not None:
                need = max(need, sy + 0.03 * W - p.y)
    need = min(need, 1.5 * W)
    for o in objs:
        lz = lift if o.name.startswith(("Teeth_Lower", "Gum_Lower")) else 0.0
        o.data.transform(Matrix.Translation(Vector((0, need, lz))))
    pushed[gname] = round(need, 4)
report["inserted"] = [o.name for o in parts]
report["parts_pushed_back"] = pushed

# ------------------------------------------------------------------ 4b. lip bones (Rigify-style naming)
# lip.T / lip.B (centres), lip.T.L/R, lip.B.L/R (halves), lips.L/R (corners). Upper bones and corners are children of
# the head, lower bones of the jaw, so the jaw still opens the mouth; each bone takes a share of its parent's weight on
# the lips near it (Gaussian along the lip, fading 0.5 W away from the slit). Lip sync stays on the shape keys.
LIP_BONES = {}
if job.get("lip_bones", True):
    half = (x1 - x0) / 2
    spots = {"lip.T": (cx, 1), "lip.T.L": (cx + 0.5 * half, 1), "lip.T.R": (cx - 0.5 * half, 1),
             "lip.B": (cx, -1), "lip.B.L": (cx + 0.5 * half, -1), "lip.B.R": (cx - 0.5 * half, -1),
             "lips.L": (x1, 0), "lips.R": (x0, 0)}
    if CL.x < CR.x:   # character's left is +x in Blender here; keep names right if the head was mirrored
        spots["lips.L"], spots["lips.R"] = (x0, 0), (x1, 0)
    bpy.ops.object.select_all(action="DESELECT"); arm.select_set(True); bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ainv = arm.matrix_world.inverted()
    for name, (x, sd) in spots.items():
        z = line_z(x) + sd * 0.06 * W
        sy = skin_y(x, z)
        y = (sy if sy is not None else M.y) + 0.12 * W
        eb = arm.data.edit_bones.new(name)
        eb.head = ainv @ Vector((x, y, z))
        eb.tail = ainv @ Vector((x, y - 0.15 * W, z))
        eb.parent = arm.data.edit_bones[JAW if sd < 0 else HEAD]
        LIP_BONES[name] = (Vector((x, y, z)), sd)
    bpy.ops.object.mode_set(mode="OBJECT")
    groups = {n: face.vertex_groups.new(name=n) for n in LIP_BONES}
    gh, gj = face.vertex_groups[HEAD], face.vertex_groups.get(JAW)
    sig = 0.35 * half
    moved = 0
    for v in face.data.vertices:
        p = fw @ v.co
        if p.y > front_limit + 0.3 * W or abs(side(p)) > 0.5 * W or abs(p.x - cx) > half * 1.25:
            continue
        fall = max(0.0, 1.0 - abs(side(p)) / (0.5 * W))
        up = side(p) >= 0
        src = gh if (up or gj is None) else gj
        sw = next((g.weight for g in v.groups if g.group == src.index), 0.0)
        if sw <= 1e-4:
            continue
        cands = {n: math.exp(-((p.x - c.x) / sig) ** 2) for n, (c, sd) in LIP_BONES.items() if sd == 0 or (sd > 0) == up}
        tot = sum(cands.values())
        if tot <= 1e-6:
            continue
        take = sw * 0.85 * fall
        src.add([v.index], sw - take, "REPLACE")
        for n, c in cands.items():
            if c / tot > 0.02:
                groups[n].add([v.index], take * c / tot, "REPLACE")
        moved += 1
    bpy.ops.object.select_all(action="DESELECT"); face.select_set(True); bpy.context.view_layer.objects.active = face
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    report["lip_bones"] = list(LIP_BONES)
    report["lip_bone_verts"] = moved

# ------------------------------------------------------------------ 5. shape keys
theta = math.radians(float(job.get("open_deg", 26)))
jaw_objs = [face, cav] + [o for o in parts]


def jaw_w(o, v):
    """jaw weight incl. the lower lip bones (children of the jaw: they follow it when it opens)"""
    if JAW == HEAD:
        return 0.0
    ids = {g.index for g in o.vertex_groups if g.name == JAW or g.name.startswith("lip.B")}
    return min(1.0, sum(x.weight for x in v.groups if x.group in ids))


def add_key(o, name, fn):
    if o.data.shape_keys is None:
        o.shape_key_add(name="Basis")
    old = o.data.shape_keys.key_blocks.get(name)
    if old is not None:
        o.shape_key_remove(old)
    k = o.shape_key_add(name=name, from_mix=False)
    mw, inv = o.matrix_world, o.matrix_world.inverted()
    for v in o.data.vertices:
        p = mw @ v.co
        q = fn(o, v, p)
        if q is not None:
            k.data[v.index].co = inv @ q
    return k


def open_jaw(o, v, p):   # rotation about the hinge (lateral axis), by the vertex's jaw weight
    w = jaw_w(o, v)
    if w <= 1e-4:
        return None
    R = Matrix.Rotation(theta * w, 4, "X")
    return hinge + (R @ (p - hinge).to_4d()).to_3d()


for o in jaw_objs:
    add_key(o, "jawOpen", open_jaw)


def lip_fall(p, r):
    """1 on the lips, 0 at radius r from the line (front skin only)"""
    if p.y > front_limit + 0.3 * W:
        return 0.0
    d = abs(side(p)); dx = max(0.0, abs(p.x - cx) - 0.5 * W)
    return max(0.0, 1.0 - math.hypot(d, dx) / r)


def corner_fall(p, c, r):
    return max(0.0, 1.0 - (p - c).length / r) if p.y < front_limit + 0.3 * W else 0.0


def k_smile(o, v, p):
    w = max(corner_fall(p, CL, 0.45 * W), corner_fall(p, CR, 0.45 * W))
    if w <= 0:
        return None
    sx = 1 if p.x > cx else -1
    return p + Vector((sx * 0.12 * W, 0.04 * W, 0.14 * W)) * w


def k_stretch(o, v, p):
    w = max(corner_fall(p, CL, 0.45 * W), corner_fall(p, CR, 0.45 * W))
    if w <= 0:
        return None
    sx = 1 if p.x > cx else -1
    return p + Vector((sx * 0.10 * W, 0.0, -0.02 * W)) * w * w


def k_round(fwd, narrow):
    def f(o, v, p):
        w = lip_fall(p, 0.45 * W)
        if w <= 0:
            return None
        return p + Vector((-(p.x - cx) * narrow, -fwd * W, 0.0)) * w
    return f


def k_lip(dz, upper_side):
    def f(o, v, p):
        if (side(p) > 0) != upper_side:
            return None
        w = lip_fall(p, 0.35 * W)
        return p + Vector((0, 0, dz * W)) * w if w > 0 else None
    return f


for name, fn in (("mouthSmile", k_smile), ("mouthStretch", k_stretch), ("mouthFunnel", k_round(0.06, 0.18)),
                 ("mouthPucker", k_round(0.09, 0.35)), ("mouthUpperUp", k_lip(0.06, True)), ("mouthLowerDown", k_lip(-0.07, False))):
    add_key(face, name, fn)
for o in bpy.data.objects:     # rest = all keys at 0 (Blender 5 adds new keys at 1 -> glTF default weights)
    if o.type == "MESH" and o.data.shape_keys:
        for kb in o.data.shape_keys.key_blocks[1:]:
            kb.value = 0.0

arm.data.pose_position = "POSE"
bpy.ops.object.select_all(action="DESELECT")
for o in bpy.data.objects:
    o.select_set(o.type in ("ARMATURE", "MESH"))
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_morph=True, export_morph_normal=False, export_influence_nb=4)

if job.get("preview"):
    sc = bpy.context.scene
    try:
        sc.render.engine = "BLENDER_WORKBENCH"; sc.display.shading.color_type = "TEXTURE"
    except (TypeError, AttributeError):
        pass
    sc.render.resolution_x = sc.render.resolution_y = 300
    sc.render.image_settings.color_mode = "RGB"
    sc.world = bpy.data.worlds.new("bg"); sc.world.color = (0.82, 0.8, 0.77)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = "ORTHO"; cam.data.ortho_scale = W * 4; cam.data.clip_end = W * 400
    keyed = [o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys]
    shots = []
    for key, view in (("closed", "front"), ("jawOpen", "front"), ("jawOpen", "side"), ("mouthSmile", "front")):
        for o in keyed:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 1.0 if kb.name == key else 0.0
        if view == "front":
            cam.location = (cx, M.y - W * 100, line_z(cx) - W * 0.2); cam.rotation_euler = (math.radians(90), 0, 0)
        else:
            cam.location = (cx + W * 100, M.y + W * 0.6, line_z(cx) - W * 0.2); cam.rotation_euler = (math.radians(90), 0, math.radians(90))
        sc.render.filepath = job["preview"].replace(".png", f"_{key}_{view}.png")
        bpy.ops.render.render(write_still=True)
        shots.append(sc.render.filepath)
    if LIP_BONES:   # lip-bone check: left corner up and out, upper lip middle up (a sneer)
        for o in keyed:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0
        arm.data.pose_position = "POSE"
        for n, d in (("lips.L", (0.18, 0, 0.22)), ("lip.T.L", (0, 0, 0.16))):
            pb = arm.pose.bones.get(n)
            if pb is not None:
                pb.matrix = Matrix.Translation(Vector(d) * W) @ pb.matrix
        bpy.context.view_layer.update()
        cam.location = (cx, M.y - W * 100, line_z(cx) - W * 0.2); cam.rotation_euler = (math.radians(90), 0, 0)
        sc.render.filepath = job["preview"].replace(".png", "_lipbones_front.png")
        bpy.ops.render.render(write_still=True)
        shots.append(sc.render.filepath)
    report["previews"] = shots
if job.get("report"):
    Path(job["report"]).write_text(json.dumps(report, indent=1), encoding="utf-8")
print("CUT_OK", json.dumps(report), flush=True)
