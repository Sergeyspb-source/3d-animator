"""Runs INSIDE Blender (background): remove skeleton, skin weights and armature modifiers from a GLB.

    blender -b -P blender_strip_rig.py -- in.glb out.glb

Meshes keep their materials and textures; their pose is baked into world space (no rig left),
so the result can be fed to an auto-rigger. Prints a short summary line starting with STRIP_OK.
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)

meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
arms = [o for o in bpy.context.scene.objects if o.type == "ARMATURE"]
bones = sum(len(a.data.bones) for a in arms)

for o in meshes:
    bpy.context.view_layer.objects.active = o
    for m in list(o.modifiers):
        if m.type == "ARMATURE":
            o.modifiers.remove(m)
    o.vertex_groups.clear()
    o.parent = None
    o.matrix_world = o.matrix_world  # keep the world pose, drop the parent link
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# drop armatures and any empties left over from the glTF node tree
for o in list(bpy.context.scene.objects):
    if o.type in ("ARMATURE", "EMPTY"):
        bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=False, export_skins=False,
                          export_animations=False)
tris = sum(len(o.data.polygons) for o in meshes)
print(f"STRIP_OK meshes={len(meshes)} removed_bones={bones} polygons={tris}")
