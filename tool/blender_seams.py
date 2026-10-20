"""Runs INSIDE Blender (background): measure and repair the seams between separate mesh parts of a rigged model.

    blender -b -P blender_seams.py -- in.glb [out.glb] [eps]

Parts cut from one body (head, torso, arms, legs...) share boundary vertices. If those copies carry different skin
weights or normals, the seam opens into a jagged crack as soon as the character moves. This script
  1. finds vertex copies that sit at the same place in different parts (within eps, metres),
  2. reports how much their skin weights disagree and how far they drift apart in a stress pose,
  3. with an output path: gives every copy the same averaged weights and normal (the parts stay separate
     objects, so armour can still be swapped), re-measures the stress pose and exports a GLB.
Prints lines starting with SEAM_.
"""
import math
import sys

import bpy
import mathutils
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src = argv[0]
dst = argv[1] if len(argv) > 1 and argv[1] != "-" else None
eps = float(argv[2]) if len(argv) > 2 else 0.0005

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
bpy.context.view_layer.update()
scene = bpy.context.scene
meshes = [o for o in scene.objects if o.type == "MESH" and o.vertex_groups]  # not the bone-shape Icosphere
arm = next((o for o in scene.objects if o.type == "ARMATURE"), None)
print(f"SEAM_INFO parts={len(meshes)} armature={'yes' if arm else 'no'}")


def world_positions(objs, evaluated=False):
    out = {}
    dg = bpy.context.evaluated_depsgraph_get() if evaluated else None
    for o in objs:
        oo = o.evaluated_get(dg) if evaluated else o
        me = oo.to_mesh() if evaluated else o.data
        mw = oo.matrix_world
        out[o.name] = [mw @ v.co for v in me.vertices]
        if evaluated:
            oo.to_mesh_clear()
    return out


rest = world_positions(meshes)
# ---- 1. coincident vertices in different parts
flat = [(name, i, p) for name, pts in rest.items() for i, p in enumerate(pts)]
kd = mathutils.kdtree.KDTree(len(flat))
for k, (_, _, p) in enumerate(flat):
    kd.insert(p, k)
kd.balance()
parent = list(range(len(flat)))


def find(a):
    while parent[a] != a:
        parent[a] = parent[parent[a]]
        a = parent[a]
    return a


for k, (name, i, p) in enumerate(flat):
    for _, k2, _d in kd.find_range(p, eps):
        if k2 != k and flat[k2][0] != name:  # only copies in a DIFFERENT part
            parent[find(k)] = find(k2)
clusters = {}
for k in range(len(flat)):
    clusters.setdefault(find(k), []).append(k)
seam = [c for c in clusters.values() if len({flat[k][0] for k in c}) > 1]
seam_verts = sum(len(c) for c in seam)
print(f"SEAM_FOUND clusters={len(seam)} vertices={seam_verts} (eps={eps} m)")
if not seam:
    raise SystemExit

# ---- per-vertex weights by bone name
def weights(obj, vi):
    names = {vg.index: vg.name for vg in obj.vertex_groups}
    return {names[g.group]: g.weight for g in obj.data.vertices[vi].groups if g.weight > 1e-5}


objs = {o.name: o for o in meshes}


def mismatch():
    tot, n = 0.0, 0
    for c in seam:
        ws = [weights(objs[flat[k][0]], flat[k][1]) for k in c]
        keys = set().union(*ws)
        for w in ws[1:]:
            tot += sum(abs(ws[0].get(b, 0) - w.get(b, 0)) for b in keys)
            n += 1
    return tot / max(n, 1)


def stress_gap():
    """Pose the rig hard, then measure how far apart the former twins end up."""
    if arm is None:
        return None
    for pb in arm.pose.bones:
        pb.rotation_mode = "XYZ"
        pb.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()
    # twist every second bone, a deliberately rough pose
    for n, pb in enumerate(arm.pose.bones):
        if len(pb.children) > 0 or n % 2 == 0:
            pb.rotation_euler = (math.radians(35 if n % 3 else -30), math.radians(20), math.radians(25 if n % 2 else -25))
    bpy.context.view_layer.update()
    posed = world_positions(meshes, evaluated=True)
    gaps = []
    for c in seam:
        pts = [posed[flat[k][0]][flat[k][1]] for k in c]
        gaps.append(max((a - b).length for a in pts for b in pts))
    for pb in arm.pose.bones:
        pb.rotation_euler = (0, 0, 0)
    bpy.context.view_layer.update()
    return sum(gaps) / len(gaps), max(gaps), sum(1 for g in gaps if g > 0.003) / len(gaps)


m0 = mismatch()
g0 = stress_gap()
print(f"SEAM_BEFORE weight_mismatch={m0:.3f} (0 = identical, 2 = totally different)")
if g0:
    print(f"SEAM_BEFORE stress_gap_mean_mm={g0[0] * 1000:.2f} max_mm={g0[1] * 1000:.1f} share_over_3mm={g0[2] * 100:.0f}%")
if not dst:
    raise SystemExit

# ---- 3. repair: identical weights and normal for every twin
mean_normals = {name: [None] * len(rest[name]) for name in rest}
for c in seam:
    ws = [weights(objs[flat[k][0]], flat[k][1]) for k in c]
    keys = set().union(*ws)
    avg = {b: sum(w.get(b, 0) for w in ws) / len(ws) for b in keys}
    tot = sum(avg.values()) or 1
    avg = {b: v / tot for b, v in avg.items() if v / tot > 1e-4}
    nrm = Vector((0, 0, 0))
    centre = sum((rest[flat[k][0]][flat[k][1]] for k in c), Vector()) / len(c)
    for k in c:
        o = objs[flat[k][0]]
        nrm += (o.matrix_world.to_3x3() @ o.data.vertices[flat[k][1]].normal)
    nrm.normalize()
    for k in c:
        name, vi, _ = flat[k]
        o = objs[name]
        for vg in o.vertex_groups:
            vg.remove([vi])
        for b, w in avg.items():
            vg = o.vertex_groups.get(b) or o.vertex_groups.new(name=b)
            vg.add([vi], w, "REPLACE")
        o.data.vertices[vi].co = o.matrix_world.inverted() @ centre  # snap the twins together
        mean_normals[name][vi] = (o.matrix_world.to_3x3().inverted() @ nrm).normalized()

for o in meshes:
    me = o.data
    me.update()
    nl = [mean_normals[o.name][i] or me.vertices[i].normal.copy() for i in range(len(me.vertices))]
    try:
        me.normals_split_custom_set_from_vertices(nl)
    except Exception as e:  # noqa: BLE001
        print("SEAM_WARN custom normals not set:", e)
bpy.context.view_layer.update()
print(f"SEAM_AFTER weight_mismatch={mismatch():.3f}")
g1 = stress_gap()
if g1:
    print(f"SEAM_AFTER stress_gap_mean_mm={g1[0] * 1000:.2f} max_mm={g1[1] * 1000:.1f} share_over_3mm={g1[2] * 100:.0f}%")
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", export_skins=True, export_animations=False,
                          export_normals=True, use_selection=False)
print("SEAM_OK", dst)
