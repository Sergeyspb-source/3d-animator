"""Runs INSIDE Blender (background): render the body with a fitted armour piece, front and side, to judge the fit.

    blender -b -P blender_fit_preview.py -- body_parts.glb armour_fitted.glb out.png Body_torso[,Body_...]

Body parts listed last are hidden (the armour covers them), like the game will do.
"""
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
body, armour, out = argv[0], argv[1], argv[2]
hide = set(argv[3].split(",")) if len(argv) > 3 and argv[3] else set()
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=body)
bpy.context.view_layer.update()
body_meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups]  # not the bone-shape Icosphere
# frame on the body only: the armour file may store its mesh in another scale under its own armature
pts = [o.matrix_world @ v.co for o in body_meshes for v in list(o.data.vertices)[::15]]
for a in armour.split(";"):  # several fitted pieces may be shown together
    bpy.ops.import_scene.gltf(filepath=a)
bpy.context.view_layer.update()
sc = bpy.context.scene
for o in body_meshes:
    if any(o.name == h or o.name.startswith(h + ".") for h in hide):
        o.hide_render = True
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
c, size = (lo + hi) / 2, max(hi - lo)
r = sc.render
r.resolution_x, r.resolution_y = 560, 700
try:
    r.engine = "BLENDER_EEVEE"
except TypeError:
    r.engine = "BLENDER_WORKBENCH"
sc.view_settings.view_transform = "Standard"
w = bpy.data.worlds.new("w")
sc.world = w
w.use_nodes = True
next(n for n in w.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = (0.86, 0.86, 0.88, 1)
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3
sun.rotation_euler = (math.radians(50), 0, math.radians(35))
sc.collection.objects.link(sun)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = size * 1.08
sc.collection.objects.link(cam)
sc.camera = cam
files = []
for name, d in (("front", (0, -1, 0)), ("side", (1, 0, 0))):
    cam.location = c + Vector(d) * size * 3
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    r.filepath = out.replace(".png", f"_{name}.png")
    bpy.ops.render.render(write_still=True)
    files.append(r.filepath)
print("FITVIEW_OK", ";".join(files))
