"""Runs INSIDE Blender (background): put a piece of armour on a landmark-rigged character as the editor placed it.

    blender -b -P blender_wear_fit.py -- job.json

job.json: {"character": rigged.glb, "armour": piece.glb, "out": out.glb, "item": name,
           "placements": [{"side": "L", "matrix": [16 floats, column-major, glTF space]}, ...],
           "offset": gap to the skin (model units), "report": path.json}

The editor (landmark_editor.html, mode «Броня») already fitted each copy: along the limb between its joints, sized
to the limb's thickness, turned and nudged by the user. Here every copy gets that matrix (a mirrored copy has a
negative determinant: its faces are flipped back), is pushed out of the body to the gap (no skin pokes through),
takes its skin weights from the nearest point of the body (barycentric, by vertex group name, 4 strongest), and is
exported with the character's skeleton only: the game puts it on the same skeleton by bone names.
"""
import json
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
report = {}


def fail(msg):
    print("WEAR_FAIL " + msg, flush=True)
    sys.exit(1)


PARTS = ("Eye_", "EyeSocket", "Teeth_", "Gum_", "Tongue", "MouthCavity", "Icosphere")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["character"])
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    fail("у персонажа нет скелета: сначала постройте скелет по разметке")
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
body = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups and not o.name.startswith(PARTS)]
if not body:
    fail("у персонажа нет кожи с весами")
character_objs = set(bpy.data.objects)

# the armour as one plain mesh in world space (a skinned source loses its old skin: the vertices are its rest pose)
bpy.ops.import_scene.gltf(filepath=job["armour"])
new = [o for o in bpy.data.objects if o not in character_objs]
src_meshes = [o for o in new if o.type == "MESH" and not o.name.startswith("Icosphere")]
if not src_meshes:
    fail("в файле вещи нет сетки")
for o in src_meshes:
    for m in list(o.modifiers):
        o.modifiers.remove(m)
    mw = o.matrix_world.copy()
    o.parent = None
    o.data = o.data.copy()
    o.data.transform(mw)
    o.matrix_world = Matrix()
    o.vertex_groups.clear()
    if o.data.shape_keys:
        o.shape_key_clear()
bpy.ops.object.select_all(action="DESELECT")
for o in src_meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = src_meshes[0]
if len(src_meshes) > 1:
    bpy.ops.object.join()
src = bpy.context.view_layer.objects.active
for o in new:
    if o is not src and o.name in bpy.data.objects:
        bpy.data.objects.remove(o, do_unlink=True)

# glTF (Y up, +Z forward) -> Blender (Z up, -Y forward): x' = x, y' = -z, z' = y
CONV = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))

# surface points pulled in the editor (piece space, glTF): the same smooth falloff as the editor's preview
_orig = [v.co.copy() for v in src.data.vertices]
for df in job.get("deforms", []):
    p, d, r = CONV @ Vector(df["p"]), CONV.to_3x3() @ Vector(df["d"]), float(df["r"])
    for v, o in zip(src.data.vertices, _orig):
        x = (o - p).length / r
        if x < 1:
            v.co += d * (1 - x * x * (3 - 2 * x))
report["deforms"] = len(job.get("deforms", []))

# the body at rest, for the push-out and the weights
verts, tris, owner = [], [], []
for o in body:
    o.data.calc_loop_triangles()
    base = len(verts)
    verts += [o.matrix_world @ v.co for v in o.data.vertices]
    for t in o.data.loop_triangles:
        tris.append(tuple(base + i for i in t.vertices))
        owner.append((o, tuple(t.vertices)))
bvh = BVHTree.FromPolygons(verts, tris)
offset = float(job.get("offset", 0.0))

pieces = []
for pl in job["placements"]:
    m = pl["matrix"]
    mg = Matrix([[m[c * 4 + r] for c in range(4)] for r in range(4)])   # column-major -> rows
    mb = CONV @ mg @ CONV.inverted()
    me = src.data.copy()
    me.transform(mb)
    if mb.determinant() < 0:   # a mirrored copy: turn the faces back outward
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(f"Wear_{job.get('item', 'item')}_{pl.get('side', 'L')}", me)
    bpy.context.scene.collection.objects.link(o)
    # push out of the body
    pushed = 0
    for v in me.vertices:
        loc, nrm, idx, dist = bvh.find_nearest(v.co)
        if loc is not None and (v.co - loc).dot(nrm) < offset:
            v.co = loc + nrm * offset
            pushed += 1
    # weights from the nearest body point
    groups = {}
    for v in me.vertices:
        loc, nrm, idx, dist = bvh.find_nearest(v.co)
        if loc is None:
            continue
        bo, tv = owner[idx]
        a, b, c = (bo.matrix_world @ bo.data.vertices[i].co for i in tv)
        bc = barycentric_transform(loc, a, b, c, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        acc = {}
        for w, vi in zip(bc, tv):
            for g in bo.data.vertices[vi].groups:
                name = bo.vertex_groups[g.group].name
                acc[name] = acc.get(name, 0.0) + max(0.0, w) * g.weight
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:4]
        tot = sum(w for _, w in top) or 1.0
        for name, w in top:
            if w / tot < 1e-3:
                continue
            g = groups.get(name) or o.vertex_groups.new(name=name)
            groups[name] = g
            g.add([v.index], w / tot, "REPLACE")
    mod = o.modifiers.new("Armature", "ARMATURE"); mod.object = arm
    o.parent = arm; o.matrix_parent_inverse = arm.matrix_world.inverted()
    for p in me.polygons:
        p.use_smooth = True
    pieces.append(o)
    report[o.name] = {"vertices": len(me.vertices), "pushed_out": pushed, "bones": sorted(groups)}
bpy.data.objects.remove(src, do_unlink=True)

# export the skeleton and the pieces only
for o in list(bpy.data.objects):
    if o.type == "MESH" and o not in pieces:
        bpy.data.objects.remove(o, do_unlink=True)
arm.data.pose_position = "POSE"
bpy.ops.object.select_all(action="DESELECT")
for o in pieces + [arm]:
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
Path(job["out"]).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4)
if job.get("report"):
    Path(job["report"]).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("WEAR_OK " + json.dumps(report, ensure_ascii=False), flush=True)
