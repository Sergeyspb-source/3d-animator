"""Runs INSIDE Blender (background): split a rigged character into body-region meshes on one skeleton.

    blender -b -P blender_split_parts.py -- rigged.glb out.glb

Each face goes to the region whose bones influence it most (head, torso, pelvis, arm/hand/leg/foot per side).
The parts stay skinned to the same armature, so armour pieces can replace or hide them one by one in Godot.
Cut edges are welded (same weights and normals), so nothing opens up when the character moves.
Prints lines starting with SPLIT_.
"""
import os
import sys

import bmesh
import bpy

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from blender_weld import weld_parts  # noqa: E402

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]

SIDE = {"left": "L", "right": "R"}
FINGERS = ("thumb", "index", "middle", "ring", "pinky")


def bone_region(name):
    """Region key for a bone name in Mixamo ('mixamorig:LeftArm') or Godot-humanoid ('LeftUpperArm') style."""
    n = name.lower()
    for sep in ("mixamorig:", "mixamorig_", "mixamorig."):
        n = n.replace(sep, "")
    side = ""
    for word, letter in SIDE.items():
        if n.startswith(word):
            side, n = letter, n[len(word):]
    if n.startswith(("head", "neck")):
        return "head"
    if n in ("hips",):
        return "pelvis"
    if n.startswith(("spine", "chest", "upperchest", "shoulder")):
        return "torso"
    if n.startswith(("hand",)) or n.startswith(FINGERS):
        return f"hand_{side}" if side else None
    if n in ("arm", "forearm", "upperarm", "lowerarm"):
        return f"arm_{side}" if side else None
    if n in ("upleg", "leg", "upperleg", "lowerleg"):
        return f"leg_{side}" if side else None
    if n.startswith(("foot", "toe")):
        return f"foot_{side}" if side else None
    return None  # unknown bone: takes the region of its parent


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
bpy.context.view_layer.update()
arm = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE"), None)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups]  # not the bone-shape Icosphere
if arm is None or not meshes:
    print("SPLIT_FAIL needs a rigged model (armature + mesh)")
    raise SystemExit

# bone -> region, unknown bones inherit from their parent
region_of = {}
for b in arm.data.bones:
    chain, cur, reg = [], b, None
    while cur is not None and reg is None:
        reg = bone_region(cur.name)
        chain.append(cur)
        cur = cur.parent
    for x in chain:
        region_of.setdefault(x.name, reg or "torso")

bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
body = bpy.context.view_layer.objects.active
me = body.data
group_region = {vg.index: region_of.get(vg.name, "torso") for vg in body.vertex_groups}

# region of every vertex = region with the largest total weight
vert_region = []
for v in me.vertices:
    acc = {}
    for g in v.groups:
        r = group_region.get(g.group)
        if r:
            acc[r] = acc.get(r, 0.0) + g.weight
    vert_region.append(max(acc, key=acc.get) if acc else "torso")

def _norm(name):
    n = name.lower()
    for sep in ("mixamorig:", "mixamorig_", "mixamorig."):
        n = n.replace(sep, "")
    return n


def _joint(side_word, names):
    """Armature-space head of the first bone called <side><name>, or None."""
    for b in arm.data.bones:
        n = _norm(b.name)
        if n.startswith(side_word) and n[len(side_word):] in names:
            return arm.matrix_world @ b.head_local
    return None


# Cut hands and feet at the wrist / ankle plane instead of wherever the skin weights happen to switch:
# armour needs bracers and gloves (and greaves and boots) to meet at the joint.
mw = body.matrix_world
for side_word, letter in (("left", "L"), ("right", "R")):
    for limb, hand_names, lower_names in (("arm", ("hand",), ("forearm", "lowerarm")),
                                          ("leg", ("foot",), ("leg", "lowerleg"))):
        end = "hand" if limb == "arm" else "foot"
        joint = _joint(side_word, hand_names)
        knee = _joint(side_word, lower_names)
        if joint is None or knee is None:
            continue
        axis = (joint - knee).normalized()
        for v in me.vertices:
            if vert_region[v.index] in (f"{limb}_{letter}", f"{end}_{letter}"):
                beyond = (mw @ v.co - joint).dot(axis) > 0
                vert_region[v.index] = f"{end}_{letter}" if beyond else f"{limb}_{letter}"

bm = bmesh.new()
bm.from_mesh(me)
bm.faces.ensure_lookup_table()
face_region = []
for f in bm.faces:
    votes = {}
    for v in f.verts:
        r = vert_region[v.index]
        votes[r] = votes.get(r, 0) + 1
    face_region.append(max(votes, key=votes.get))
# remove ragged single-face islands: a face takes the region that most of its neighbours have
for _ in range(3):
    new = list(face_region)
    for f in bm.faces:
        nb = []
        for e in f.edges:
            if len(e.link_faces) == 2:
                other = e.link_faces[0] if e.link_faces[1] is f else e.link_faces[1]
                nb.append(face_region[other.index])
        if nb:
            top = max(set(nb), key=nb.count)
            if top != face_region[f.index] and nb.count(top) >= 2:
                new[f.index] = top
    face_region = new
bm.free()

regions = sorted(set(face_region))
parts = []
for key in regions:
    ob = body.copy()
    ob.data = body.data.copy()
    bpy.context.collection.objects.link(ob)
    b2 = bmesh.new()
    b2.from_mesh(ob.data)
    b2.faces.ensure_lookup_table()
    kill = [f for f in b2.faces if face_region[f.index] != key]
    bmesh.ops.delete(b2, geom=kill, context="FACES")
    b2.to_mesh(ob.data)
    b2.free()
    ob.name = f"Body_{key}"
    ob.data.name = f"Body_{key}"
    parts.append(ob)
bpy.data.objects.remove(body, do_unlink=True)
bpy.context.view_layer.update()

seams = weld_parts(parts)
for ob in parts:
    print(f"SPLIT_PART {ob.name} tris={len(ob.data.polygons)} verts={len(ob.data.vertices)}")
print(f"SPLIT_SEAMS {seams}")
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", export_skins=True, export_animations=False,
                          export_normals=True, use_selection=False)
print("SPLIT_OK", dst)
