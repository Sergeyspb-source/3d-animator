"""Runs INSIDE Blender (background): list the segments of a dressed, segmented character and guess what each is.

    blender -b -P blender_outfit_scan.py -- model.glb out_dir

For every mesh with at least 40 faces: faces, position in the figure (height 0..1, left/right of the middle),
average colour and whether it looks like skin; a guess of the slot; a small textured render out_dir/<name>.png.
Prints one line per segment: SCAN_SEG {json}. Left/right are the character's own (Blender +X = its left).
"""
import colorsys
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], Path(argv[1])
out.mkdir(parents=True, exist_ok=True)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
bpy.context.view_layer.update()
segs = [o for o in bpy.context.scene.objects if o.type == "MESH" and len(o.data.polygons) >= 40]
allp = [o.matrix_world @ v.co for o in segs for v in o.data.vertices]
mlo = Vector([min(p[i] for p in allp) for i in range(3)])
mhi = Vector([max(p[i] for p in allp) for i in range(3)])
H, W = mhi.z - mlo.z, mhi.x - mlo.x
mid_x = (mlo.x + mhi.x) / 2


def mean_colour(o):
    for m in o.data.materials:
        if m and m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and n.image.size[0] > 0:
                    w, h = n.image.size
                    px = np.empty(w * h * 4, dtype=np.float32)
                    n.image.pixels.foreach_get(px)
                    px = px.reshape(h, w, 4)
                    uv = o.data.uv_layers.active
                    if uv is None:
                        return None
                    co = np.empty(len(uv.data) * 2)
                    uv.data.foreach_get("uv", co)
                    co = co.reshape(-1, 2)[:: max(1, len(uv.data) // 4000)]
                    xs = np.clip((co[:, 0] % 1) * (w - 1), 0, w - 1).astype(int)
                    ys = np.clip((co[:, 1] % 1) * (h - 1), 0, h - 1).astype(int)
                    return np.median(px[ys, xs, :3], axis=0)
    return None


info = []
for o in segs:
    pts = [o.matrix_world @ v.co for v in o.data.vertices]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    c = (lo + hi) / 2
    zc, hgt, wid = (c.z - mlo.z) / H, (hi.z - lo.z) / H, (hi.x - lo.x) / W
    dx = (c.x - mid_x) / W
    col = mean_colour(o)
    skin = False
    if col is not None:
        hh, ss, vv = colorsys.rgb_to_hsv(*col)
        skin = bool(0.09 < hh < 0.30 and ss > 0.3 and vv > 0.25)  # olive / green / tan skin
    info.append(dict(name=o.name, faces=len(o.data.polygons), zc=round(zc, 3), height=round(hgt, 3),
                     width=round(wid, 3), dx=round(dx, 3), skin=skin,
                     colour=[round(float(x), 2) for x in col] if col is not None else None))


def guess(s):
    side = "левый" if s["dx"] > 0 else "правый"
    if s["skin"] and s["height"] > 0.35:
        return "skip"
    if s["zc"] > 0.8:
        return "head" if s["skin"] else "helmet"
    if s["skin"]:
        return "skip"
    if s["width"] > 0.3 and abs(s["dx"]) < 0.08 and s["height"] > 0.15:
        return "chest"
    if s["width"] > 0.3 and abs(s["dx"]) > 0.15 and s["zc"] > 0.55:
        return "arm " + side  # shoulder to fingers in one piece (T or A pose)
    if s["zc"] < 0.12:
        return "boot " + side
    if 0.25 < s["zc"] < 0.5 and abs(s["dx"]) > 0.03 and s["height"] < 0.3 and s["zc"] - s["height"] / 2 > 0.15:
        return "thigh " + side
    if s["zc"] < 0.38 and abs(s["dx"]) > 0.03:
        return "boot " + side
    if 0.6 < s["zc"] <= 0.85 and abs(s["dx"]) > 0.08:
        return "pauldron " + side
    if 0.35 < s["zc"] <= 0.65 and abs(s["dx"]) > 0.18:
        return "bracer " + side
    if 0.3 < s["zc"] < 0.6 and abs(s["dx"]) < 0.08:
        return "belt"
    return "skip"


for s in info:
    s["guess"] = guess(s)
# a face (skin, at the top) together with a helmet: one replacement head
if any(s["guess"] == "head" for s in info):
    for s in info:
        if s["guess"] == "helmet":
            s["guess"] = "head"

# ---- one small textured render per segment
sc = bpy.context.scene
r = sc.render
r.resolution_x, r.resolution_y = 220, 240
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
sc.collection.objects.link(cam)
sc.camera = cam
for o, s in zip(segs, info):
    for x in segs:
        x.hide_render = x is not o
    pts = [o.matrix_world @ v.co for v in o.data.vertices]
    lo = Vector([min(p[i] for p in pts) for i in range(3)])
    hi = Vector([max(p[i] for p in pts) for i in range(3)])
    c = (lo + hi) / 2
    cam.data.ortho_scale = max(hi.x - lo.x, hi.z - lo.z) * 1.2
    cam.location = c + Vector((0, -3, 0))
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    r.filepath = str(out / f"{s['name']}.png")
    bpy.ops.render.render(write_still=True)
    s["thumb"] = r.filepath
    print("SCAN_SEG " + json.dumps(s, ensure_ascii=False))
print("SCAN_OK", len(info))
