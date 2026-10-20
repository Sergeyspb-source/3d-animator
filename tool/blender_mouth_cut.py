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
coef = np.polyfit([CR.x, M.x, CL.x], [CR.z, M.z, CL.z], 2)
x0, x1 = min(CR.x, CL.x), max(CR.x, CL.x)
cx = (x0 + x1) / 2


def line_z(x):
    return float(np.polyval(coef, x))


def side(p):
    return p.z - line_z(p.x)


front_limit = max(CL.y, CR.y) + 0.35 * W          # only the front skin around the mouth is cut (Blender: forward = -y)

face = max((o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups),
           key=lambda o: sum(1 for v in o.data.vertices if ((o.matrix_world @ v.co) - M).length < W))
fw, finv = face.matrix_world, face.matrix_world.inverted()
report = {"mouth_width": round(W, 4)}

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
report["crossed_edges"] = len(cross)
if len(new_verts) < 6:
    fail(f"линия рта пересекла только {len(new_verts)} рёбер: точки рта не на губах?")
bm.faces.ensure_lookup_table()
line_edges = set()
for f in list(bm.faces):
    nv = [v for v in f.verts if v in new_verts]
    if len(nv) == 2:
        r = bmesh.ops.connect_verts(bm, verts=nv)
        for e in r["edges"]:
            line_edges.add(e)
report["line_edges"] = len(line_edges)
res = bmesh.ops.split_edges(bm, edges=list(line_edges))
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


for v in upper:
    copy_weights(v, 1)
for v in lower:
    copy_weights(v, -1)
report["lip_verts"] = {"upper": len(upper), "lower": len(lower)}

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
            v.co = finv @ (p + Vector((0, step_back, step_curl)))
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
cmat = bpy.data.materials.new("mouth_cavity"); cmat.use_nodes = True
cb = next(n for n in cmat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
cb.inputs["Base Color"].default_value = (0.08, 0.025, 0.025, 1); cb.inputs["Roughness"].default_value = 0.35
cav.data.materials.append(cmat)
for p_ in cav.data.polygons:
    p_.use_smooth = True
skin(cav, lambda p: jaw_blend(p.z, line_z(cx), 0.08 * W))

# ------------------------------------------------------------------ 4. teeth and tongue
kit_w = float(job.get("kit", {}).get("arch_width", 0.05))
s = W * 1.0 / kit_w
anchor = Vector((cx, M.y + 0.30 * W, line_z(cx)))
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
    skin(o, lambda p, j=on_jaw: 1.0 if j else 0.0)
report["inserted"] = [o.name for o in parts]

# ------------------------------------------------------------------ 5. shape keys
theta = math.radians(float(job.get("open_deg", 22)))
jaw_objs = [face, cav] + [o for o in parts]


def jaw_w(o, v):
    g = o.vertex_groups.get(JAW)
    return next((x.weight for x in v.groups if g is not None and x.group == g.index), 0.0) if JAW != HEAD else 0.0


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
    return p + Vector((sx * 0.07 * W, 0.02 * W, 0.08 * W)) * w * w


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
    report["previews"] = shots
if job.get("report"):
    Path(job["report"]).write_text(json.dumps(report, indent=1), encoding="utf-8")
print("CUT_OK", json.dumps(report), flush=True)
