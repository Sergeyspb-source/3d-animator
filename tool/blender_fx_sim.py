"""Runs INSIDE Blender (background): simulate smoke / fire / an explosion with Mantaflow and render it as a flipbook
sheet (frames in a grid on one PNG with alpha) for Godot particles.

    blender -b -P blender_fx_sim.py -- out.png kind=explosion|smoke|fire [grid=8] [res=64] [size=256] [cache=dir]
                                                                        [tint=r,g,b]

explosion  a short burst of fire and smoke pushed outwards, fades out (one-shot),
smoke      a puff of smoke rising and spreading (one-shot),
fire       a steady flame; the sheet loops (the last frames cross-fade into the first).
Prints FX_ lines.
"""
import math
import os
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
out = Path(argv[0])
opt = dict(a.split("=", 1) for a in argv[1:] if "=" in a)
kind = opt.get("kind", "explosion")
grid = int(opt.get("grid", 8))
res = int(opt.get("res", 64))
size = int(opt.get("size", 256))
frames = grid * grid
cache = Path(opt.get("cache", str(out.with_suffix("")) + "_cache"))
tint = tuple(float(x) for x in opt.get("tint", "1,1,1").split(","))

bpy.ops.wm.read_factory_settings(use_empty=True)
sc = bpy.context.scene
warm = {"explosion": 1, "smoke": 2, "fire": 40}[kind]   # frames simulated before the sheet starts (fire settles)
sc.frame_start, sc.frame_end = 1, warm + frames + (16 if kind == "fire" else 0)

# ---- domain
bpy.ops.mesh.primitive_cube_add(size=2, location=(0, 0, 1))
dom = bpy.context.active_object
dom.name = "domain"
mod = dom.modifiers.new("fluid", "FLUID")
mod.fluid_type = "DOMAIN"
ds = mod.domain_settings
ds.domain_type = "GAS"
ds.resolution_max = res
ds.cache_directory = str(cache)
ds.cache_type = "ALL"
ds.cache_frame_start, ds.cache_frame_end = sc.frame_start, sc.frame_end
ds.use_adaptive_domain = False
ds.alpha = 0.0 if kind == "fire" else 1.0           # buoyancy from density
ds.beta = 1.6 if kind != "smoke" else 0.8           # buoyancy from heat
ds.vorticity = 0.25
ds.use_noise = False
ds.flame_vorticity = 0.6
ds.flame_smoke = 1.0 if kind != "fire" else 0.3
ds.flame_smoke_color = (0.75, 0.72, 0.68)
ds.burning_rate = 0.9 if kind == "explosion" else 0.75
ds.use_dissolve_smoke = True
ds.dissolve_speed = 40 if kind == "explosion" else (45 if kind == "smoke" else 10)
ds.use_dissolve_smoke_log = True

# ---- emitter
bpy.ops.mesh.primitive_uv_sphere_add(radius=0.28 if kind != "fire" else 0.25, location=(0, 0, 0.55 if kind != "fire" else 0.3))
em = bpy.context.active_object
em.name = "emitter"
fm = em.modifiers.new("fluid", "FLUID")
fm.fluid_type = "FLOW"
fs = fm.flow_settings
fs.flow_type = {"explosion": "BOTH", "smoke": "SMOKE", "fire": "FIRE"}[kind]
fs.flow_behavior = "INFLOW"
fs.flow_source = "MESH"
fs.surface_distance = 0.5
fs.use_initial_velocity = kind == "explosion"
if kind == "explosion":
    fs.velocity_normal = 2.5
    fs.fuel_amount = 2.5
    fs.temperature = 2.0
if kind == "smoke":
    fs.smoke_color = (0.55, 0.55, 0.55)
    fs.density = 1.2
# bursts: the emitter works only for the first frames
if kind in ("explosion", "smoke"):
    fs.use_inflow = True
    fs.keyframe_insert("use_inflow", frame=1)
    fs.use_inflow = False
    fs.keyframe_insert("use_inflow", frame=4 if kind == "explosion" else 7)

# ---- bake
bpy.ops.object.select_all(action="DESELECT")
dom.select_set(True)
bpy.context.view_layer.objects.active = dom
with bpy.context.temp_override(object=dom, active_object=dom, selected_objects=[dom]):
    bpy.ops.fluid.bake_all()
print("FX_BAKED", kind, "frames", sc.frame_end)
em.hide_render = True

# ---- material: density as smoke, flame as emission
mat = bpy.data.materials.new("fx")
mat.use_nodes = True
nt = mat.node_tree
for n in list(nt.nodes):
    nt.nodes.remove(n)
outn = nt.nodes.new("ShaderNodeOutputMaterial")
vol = nt.nodes.new("ShaderNodeVolumePrincipled")
vol.inputs["Density"].default_value = 18.0 if kind != "fire" else 4.0
vol.inputs["Color"].default_value = (0.85 * tint[0], 0.83 * tint[1], 0.8 * tint[2], 1)
vol.inputs["Blackbody Intensity"].default_value = 1.0 if kind != "smoke" else 0.0
vol.inputs["Temperature"].default_value = 1350
fl = nt.nodes.new("ShaderNodeAttribute")
fl.attribute_name = "flame"
mul = nt.nodes.new("ShaderNodeMath")
mul.operation = "MULTIPLY"
mul.inputs[1].default_value = 25.0
nt.links.new(fl.outputs["Fac"], mul.inputs[0])
nt.links.new(mul.outputs[0], vol.inputs["Blackbody Intensity"]) if kind != "smoke" else None
nt.links.new(vol.outputs[0], outn.inputs["Volume"])
dom.data.materials.append(mat)

# ---- render setup: orthographic side view, transparent background
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = 2.0
sc.collection.objects.link(cam)
sc.camera = cam
cam.location = (0, -6, 1)
cam.rotation_euler = (math.radians(90), 0, 0)
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 5.0
sun.rotation_euler = (math.radians(40), 0, math.radians(30))
sc.collection.objects.link(sun)
w = bpy.data.worlds.new("w")
sc.world = w
w.use_nodes = True
next(n for n in w.node_tree.nodes if n.type == "BACKGROUND").inputs["Strength"].default_value = 1.6
r = sc.render
try:
    r.engine = "BLENDER_EEVEE"
except TypeError:
    r.engine = "BLENDER_EEVEE_NEXT"
try:
    sc.eevee.volumetric_tile_size = "2"
    sc.eevee.volumetric_samples = 64
except Exception:  # noqa: BLE001
    pass
r.film_transparent = True
r.resolution_x = r.resolution_y = size * 2   # rendered larger, cropped to the effect below
r.image_settings.file_format = "PNG"
r.image_settings.color_mode = "RGBA"
sc.view_settings.view_transform = "Standard"
tmp = cache / "frames"
tmp.mkdir(parents=True, exist_ok=True)
paths = []
total = frames + (16 if kind == "fire" else 0)
for i in range(total):
    sc.frame_set(warm + i + 1)
    r.filepath = str(tmp / f"f_{i:03d}.png")
    bpy.ops.render.render(write_still=True)
    paths.append(r.filepath)
print("FX_RENDERED", len(paths))

# ---- sheet
def load(p):
    im = bpy.data.images.load(p)
    a = np.array(im.pixels[:], dtype=np.float32).reshape(size * 2, size * 2, 4)[::-1]
    bpy.data.images.remove(im)
    return a


imgs = [load(p) for p in paths]
# frame the effect: one square crop that holds every frame (so the motion is not jumpy), then scale to `size`
alpha = np.max([a[..., 3] for a in imgs], axis=0)
ys, xs = np.where(alpha > 0.15)
if len(ys):
    cy, cx = (ys.min() + ys.max()) / 2, (xs.min() + xs.max()) / 2
    half = max(ys.max() - ys.min(), xs.max() - xs.min()) / 2 * 1.08 + 2
    y0, x0 = int(max(0, cy - half)), int(max(0, cx - half))
    y1, x1 = int(min(size * 2, cy + half)), int(min(size * 2, cx + half))
    s0 = min(y1 - y0, x1 - x0)
    def crop(a):
        c = a[y0:y0 + s0, x0:x0 + s0]
        idx = (np.arange(size) * s0 / size).astype(int)
        # box filter: average of the source pixels that fall into each target pixel
        k = max(1, s0 // size)
        if k > 1:
            c = c[:k * (s0 // k), :k * (s0 // k)].reshape(s0 // k, k, s0 // k, k, 4).mean((1, 3))
            idx = (np.arange(size) * (s0 // k) / size).astype(int)
        return c[idx][:, idx]
    imgs = [crop(a) for a in imgs]
    print(f"FX_FRAME crop {s0}px of {size * 2}")
else:
    imgs = [a[::2, ::2] for a in imgs]
if kind == "fire":
    # loop: the last 16 frames cross-fade into the first 16
    for k in range(16):
        t = (k + 1) / 17
        imgs[k] = imgs[k] * t + imgs[frames + k] * (1 - t)
    imgs = imgs[:frames]
else:
    # one-shots end fully transparent
    for k in range(6):
        imgs[frames - 6 + k][..., 3] *= 1 - (k + 1) / 6
sheet = np.zeros((grid * size, grid * size, 4), np.float32)
for i, a in enumerate(imgs):
    y, x = divmod(i, grid)
    sheet[y * size:(y + 1) * size, x * size:(x + 1) * size] = a
img = bpy.data.images.new("sheet", grid * size, grid * size, alpha=True)
img.pixels.foreach_set(sheet[::-1].ravel())
img.filepath_raw = str(out)
img.file_format = "PNG"
img.save()
print("FX_OK", out, f"{grid}x{grid}")
