"""Models for a problem write-up, all under one camera (Blender 5.2, headless).

    "D:\\Blender 5.2\\blender.exe" -b -P "docs/Solve problems/_tools/render_models.py" -- OUT_DIR [options] [label=]model.glb ...

Options:
    --size 2560x1440    frame size (16:9 for the video)
    --views front,q34   front and three-quarter (40 degrees); also: side, back
    --looks clay,tex    grey clay with cavity, and the model's own texture (skipped for a model without one)
    --bg                dark grey background (#2b2b2f) instead of transparent
    --fill 0.87         share of the frame height the models take

Each model -> OUT_DIR/<label>_<look>_<view>.png. All models are framed by their common bounds, so a before/after
pair lines up pixel for pixel and a wipe between them works in the video. Collision proxy nodes (-colonly,
-convcolonly) are left out. Reads .glb, .gltf, .fbx, .obj.
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
opt = {"size": "2560x1440", "views": "front,q34", "looks": "clay,tex", "fill": "0.87"}
bg = False
out = None
models = []
i = 0
while i < len(argv):
    a = argv[i]
    if a == "--bg":
        bg = True
    elif a.startswith("--") and a[2:] in opt:
        opt[a[2:]] = argv[i + 1]
        i += 1
    elif out is None:
        out = Path(a)
    else:
        label, path = ("", a)
        if "=" in a and not Path(a).exists():
            label, _, path = a.partition("=")
        p = Path(path)
        models.append((label or f"{p.parent.name}_{p.stem}", p))
    i += 1
if out is None or not models:
    sys.exit(__doc__)
out.mkdir(parents=True, exist_ok=True)
W, H = (int(v) for v in opt["size"].lower().split("x"))
YAW = {"front": 0.0, "q34": 40.0, "side": 90.0, "back": 180.0}

sc = bpy.context.scene
for o in list(bpy.data.objects):
    bpy.data.objects.remove(o)
sc.render.engine = "BLENDER_WORKBENCH"
sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = W, H, 100
sc.render.film_transparent = not bg
sc.render.image_settings.file_format = "PNG"
sc.render.image_settings.color_mode = "RGBA"
transforms = [t.identifier for t in sc.view_settings.bl_rna.properties["view_transform"].enum_items]
if "Standard" in transforms:
    sc.view_settings.view_transform = "Standard"
sc.world = sc.world or bpy.data.worlds.new("world")
sc.world.color = (0.0242, 0.0242, 0.0284)  # #2b2b2f
sh = sc.display.shading
sh.light = "STUDIO"
sh.show_cavity = True
sh.cavity_type = "BOTH"
sh.show_specular_highlight = True
sh.single_color = (0.62, 0.62, 0.6)

COLLISION = ("-colonly", "-convcolonly")
loaded = []  # (label, objects shown, has a texture)
for label, path in models:
    before = set(bpy.data.objects)
    ext = path.suffix.lower()
    if ext in (".glb", ".gltf"):
        bpy.ops.import_scene.gltf(filepath=str(path))
    elif ext == ".fbx":
        bpy.ops.import_scene.fbx(filepath=str(path))
    elif ext == ".obj":
        bpy.ops.wm.obj_import(filepath=str(path))
    else:
        sys.exit(f"cannot read {path}")
    new = [o for o in bpy.data.objects if o not in before]
    shown = []
    for o in new:
        if any(c in o.name for c in COLLISION):
            o.hide_render = True
        elif o.type == "MESH":
            shown.append(o)
    textured = any(n.type == "TEX_IMAGE" and n.image for o in shown for s in o.material_slots
                   if s.material and s.material.use_nodes for n in s.material.node_tree.nodes)
    loaded.append((label, new, shown, textured))

dg = bpy.context.evaluated_depsgraph_get()
pts = [o.evaluated_get(dg).matrix_world @ Vector(c) for _, _, shown, _ in loaded for o in shown
       for c in o.evaluated_get(dg).bound_box]
lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
centre = (lo + hi) / 2
footprint = math.hypot(hi.x - lo.x, hi.y - lo.y)
fill = float(opt["fill"])
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
sc.collection.objects.link(cam)
sc.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = max(footprint / fill, (hi.z - lo.z) / fill * W / H)  # ortho scale spans the frame width
reach = 2 * (footprint + hi.z - lo.z) + 10
cam.data.clip_end = 2 * reach

written = []
for label, objs, shown, textured in loaded:
    for _, others, _, _ in loaded:
        for o in others:
            if not any(c in o.name for c in COLLISION):
                o.hide_render = others is not objs
    for look in opt["looks"].split(","):
        if look == "tex" and not textured:
            continue
        sh.color_type = "TEXTURE" if look == "tex" else "SINGLE"
        for view in opt["views"].split(","):
            r = math.radians(YAW[view])
            d = Vector((math.sin(r), -math.cos(r), 0.0))
            cam.location = centre + d * reach
            cam.rotation_euler = (math.radians(90), 0, r)
            sc.render.filepath = str(out / f"{label}_{look}_{view}.png")
            bpy.ops.render.render(write_still=True)
            written.append(sc.render.filepath)
print("\n".join(["written:"] + written))
