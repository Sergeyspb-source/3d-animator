"""Runs INSIDE Blender (background): colour every Body_* part differently and render front/right/back views.

    blender -b -P blender_parts_view.py -- parts.glb out_dir
"""
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
bpy.context.view_layer.update()
sc = bpy.context.scene
meshes = [o for o in sc.objects if o.type == "MESH"]
pal = [(0.9, 0.2, 0.2), (0.2, 0.7, 0.3), (0.95, 0.8, 0.1), (0.2, 0.5, 0.9), (0.95, 0.5, 0.15), (0.6, 0.3, 0.8),
       (0.2, 0.8, 0.8), (0.9, 0.4, 0.7), (0.5, 0.5, 0.5), (0.6, 0.8, 0.2), (0.4, 0.2, 0.1), (0.1, 0.3, 0.5)]
for k, o in enumerate(sorted(meshes, key=lambda x: x.name)):
    m = bpy.data.materials.new(f"c{k}")
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*pal[k % len(pal)], 1)
    b.inputs["Roughness"].default_value = 0.6
    o.data.materials.clear()
    o.data.materials.append(m)
pts = [o.matrix_world @ v.co for o in meshes for v in list(o.data.vertices)[::20]]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c, size = (lo + hi) / 2, max(hi - lo)
r = sc.render
r.resolution_x = r.resolution_y = 700
try:
    r.engine = "BLENDER_EEVEE"
except TypeError:
    r.engine = "BLENDER_WORKBENCH"
sc.view_settings.view_transform = "Standard"
w = bpy.data.worlds.new("w")
sc.world = w
w.use_nodes = True
next(n for n in w.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = (0.9, 0.9, 0.92, 1)
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3
sun.rotation_euler = (math.radians(50), 0, math.radians(35))
sc.collection.objects.link(sun)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = size * 1.1
sc.collection.objects.link(cam)
sc.camera = cam
for name, d in (("front", (0, -1, 0)), ("right", (1, 0, 0))):
    cam.location = c + Vector(d) * size * 3
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    r.filepath = f"{out}/parts_{name}.png"
    bpy.ops.render.render(write_still=True)
print("PARTS_VIEW_OK")
