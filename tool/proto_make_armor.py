"""Runs INSIDE Blender: build a TEST armour piece from one body part (inflated copy, metal material, same skin).

    blender -b -P proto_make_armor.py -- parts.glb part_name out.glb [inflate_m]

Only for prototyping the equipment architecture in Godot; real armour comes from the generators and is fitted
to the body with weight transfer.
"""
import sys

import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, part, dst = argv[0], argv[1], argv[2]
inflate = float(argv[3]) if len(argv) > 3 else 0.012

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
bpy.context.view_layer.update()
body = bpy.data.objects[part]
armor = body.copy()
armor.data = body.data.copy()
bpy.context.collection.objects.link(armor)
armor.name = "Armor_" + part.replace("Body_", "")
scale = armor.matrix_world.to_scale()[0] or 1.0
for v in armor.data.vertices:
    v.co += v.normal * (inflate / scale)
armor.data.update()
mat = bpy.data.materials.new("steel")
mat.use_nodes = True
b = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
b.inputs["Base Color"].default_value = (0.55, 0.58, 0.65, 1)
b.inputs["Metallic"].default_value = 0.9
b.inputs["Roughness"].default_value = 0.35
armor.data.materials.clear()
armor.data.materials.append(mat)
for o in list(bpy.context.scene.objects):
    if o.type == "MESH" and o is not armor:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", export_skins=True, export_animations=False)
print("ARMOR_OK", armor.name, len(armor.data.vertices), "vertices")
