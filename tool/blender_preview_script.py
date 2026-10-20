"""Runs INSIDE Blender (background mode): renders 4 side views + a 3/4 icon of a GLB.

    blender -b -P blender_preview_script.py -- model.glb out_dir [size]

Writes out_dir/view_front.png, view_right.png, view_back.png, view_left.png (grey background)
and out_dir/icon.png (transparent background, 3/4 view). Collision proxy nodes are not rendered.
"""
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
glb, out_dir = argv[0], argv[1]
size = int(argv[2]) if len(argv) > 2 else 512

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
# vertex colours carry data (e.g. the wind map of plants), not paint: show the texture alone
for mat in bpy.data.materials:
    if mat.node_tree:
        for n in [n for n in mat.node_tree.nodes if n.type == "VERTEX_COLOR"]:
            for link in list(n.outputs[0].links) + list(n.outputs[1].links):
                to = link.to_socket
                mat.node_tree.links.remove(link)
                if hasattr(to, "default_value"):
                    try:
                        to.default_value = (1, 1, 1, 1) if len(to.default_value) == 4 else 1.0
                    except TypeError:
                        to.default_value = 1.0
scene = bpy.context.scene

meshes = []
for o in scene.objects:
    if o.name.endswith(("-colonly", "-convcolonly")):
        o.hide_render = True
        o.hide_viewport = True
    elif o.type == "MESH":
        meshes.append(o)
if not meshes:
    raise SystemExit("no visible mesh in " + glb)

# world-space bounding box of everything that will be rendered
pts = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
center = (lo + hi) / 2
diag = (hi - lo).length

# render settings
r = scene.render
r.resolution_x = r.resolution_y = size
r.image_settings.file_format = "PNG"
r.image_settings.color_mode = "RGBA"
try:
    scene.render.engine = "BLENDER_EEVEE"
except TypeError:
    scene.render.engine = "BLENDER_WORKBENCH"
scene.view_settings.view_transform = "Standard"

# soft ambient light plus a key sun
world = bpy.data.worlds.new("w")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (0.82, 0.82, 0.84, 1)
bg.inputs["Strength"].default_value = 1.0
sun_data = bpy.data.lights.new("sun", "SUN")
sun_data.energy = 3.0
sun = bpy.data.objects.new("sun", sun_data)
sun.rotation_euler = (math.radians(50), 0, math.radians(35))
scene.collection.objects.link(sun)

cam_data = bpy.data.cameras.new("cam")
cam = bpy.data.objects.new("cam", cam_data)
scene.collection.objects.link(cam)
scene.camera = cam


def aim(az_deg, el_deg, ortho):
    """Camera on a circle around the model. az 0 = in front (glTF +Z, which is Blender -Y)."""
    az, el = math.radians(az_deg), math.radians(el_deg)
    if ortho:
        cam_data.type = "ORTHO"
        cam_data.ortho_scale = max(hi - lo) * 1.15
        dist = diag * 2
    else:
        cam_data.type = "PERSP"
        cam_data.lens = 50
        fov = 2 * math.atan(18 / 50)  # 36 mm sensor
        dist = (diag / 2) / math.tan(fov / 2) * 0.95
    direction = Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))
    cam.location = center + direction * dist
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()


def render(path, transparent):
    r.film_transparent = transparent
    r.filepath = path
    bpy.ops.render.render(write_still=True)


for name, az in (("front", 0), ("right", 90), ("back", 180), ("left", 270)):
    aim(az, 8, ortho=True)
    render(f"{out_dir}/view_{name}.png", False)
aim(35, 22, ortho=False)
render(f"{out_dir}/icon.png", True)
print("PREVIEW_OK")
