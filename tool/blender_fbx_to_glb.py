"""Runs INSIDE Blender (background): convert a rigged FBX (e.g. Mixamo "With Skin") to GLB for the browser viewer.

    blender -b -P blender_fbx_to_glb.py -- in.fbx out.glb

Keeps the skeleton, skin weights, materials and every animation. Prints FBX2GLB_OK {json summary}.
"""
import json
import sys

import bpy

src, dst = sys.argv[sys.argv.index("--") + 1:][:2]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.fbx(filepath=src)
scene = bpy.context.scene
arms = [o for o in scene.objects if o.type == "ARMATURE"]
meshes = [o for o in scene.objects if o.type == "MESH"]
info = {"bones": sum(len(a.data.bones) for a in arms), "meshes": len(meshes),
        "vertices": sum(len(o.data.vertices) for o in meshes),
        "skinned": sum(1 for o in meshes if any(m.type == "ARMATURE" for m in o.modifiers)),
        "animations": [a.name for a in bpy.data.actions]}
if meshes:
    bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", export_skins=True, export_animations=True,
                              export_animation_mode="ACTIONS", export_influence_nb=4)
print("FBX2GLB_OK", json.dumps(info), flush=True)
