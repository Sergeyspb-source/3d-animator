"""Runs INSIDE Blender (background): join every mesh of a GLB into one object (materials kept) and write it.

    blender -b -P blender_join.py -- model.glb out.glb

Used to rig a segmented model (Tripo parts) as one character. Prints JOIN_OK <vertices>.
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=argv[0])
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for o in meshes:
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
for o in list(bpy.context.scene.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="SELECT")
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.join()
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
ob = bpy.context.view_layer.objects.active
ob.name = "dressed"
bpy.ops.export_scene.gltf(filepath=argv[1], export_format="GLB", use_selection=True)
print("JOIN_OK", len(ob.data.vertices))
