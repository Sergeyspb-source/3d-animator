"""Runs INSIDE Blender: a crude stand-alone 'cuirass' (own topology, no skin, wrong size and place) to test
armour fitting as if it came from a generator.   blender -b -P proto_make_cuirass.py -- out.glb"""
import sys

import bpy

dst = sys.argv[sys.argv.index("--") + 1:][0]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.mesh.primitive_cylinder_add(vertices=40, radius=0.5, depth=1.2, location=(3, 1, 2))
o = bpy.context.active_object
o.scale = (1.0, 0.6, 1.0)  # flattened front-to-back like a torso
bpy.ops.object.modifier_add(type="SUBSURF")
o.modifiers[0].levels = 2
bpy.ops.object.modifier_apply(modifier=o.modifiers[0].name)
m = bpy.data.materials.new("bronze")
m.use_nodes = True
b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
b.inputs["Base Color"].default_value = (0.7, 0.45, 0.2, 1)
b.inputs["Metallic"].default_value = 0.9
b.inputs["Roughness"].default_value = 0.4
o.data.materials.append(m)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB")
print("CUIRASS_OK", len(o.data.vertices))
