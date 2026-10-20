"""Runs INSIDE Blender (background): split a "kit sheet" model (Tripo and similar: body, helmet, armour, weapons
laid out side by side in one mesh) into separate GLB items.

    blender -b -P blender_split_kit.py -- kit.glb out_dir [min_verts=300]

Loose pieces are found after welding UV-seam vertices; pieces smaller than min_verts (rivets, straps that came
apart) join the big piece whose bounding box contains them. Each item is written as out_dir/part_NN.glb with its
origin at the bottom centre, plus a labelled overview render out_dir/overview.png.
Prints lines starting with KIT_.
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], Path(argv[1])
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
min_verts = int(opt.get("min_verts", 300))
out.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH"]
for o in meshes:
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
for o in list(bpy.context.scene.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
kit = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bm = bmesh.new()
bm.from_mesh(kit.data)
bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
bm.to_mesh(kit.data)
bm.free()
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.separate(type="LOOSE")
bpy.ops.object.mode_set(mode="OBJECT")
pieces = [o for o in bpy.context.scene.objects if o.type == "MESH"]


def bbox(o):
    ps = [o.matrix_world @ v.co for v in o.data.vertices]
    return (Vector([min(p[i] for p in ps) for i in range(3)]), Vector([max(p[i] for p in ps) for i in range(3)]))


big = [o for o in pieces if len(o.data.vertices) >= min_verts]
small = [o for o in pieces if len(o.data.vertices) < min_verts]
boxes = {o.name: bbox(o) for o in big}
for s in small:  # a loose rivet or strap goes to the item it sits on (or the nearest one)
    lo, hi = bbox(s)
    c = (lo + hi) / 2

    def dist(o):
        blo, bhi = boxes[o.name]
        d = Vector([max(blo[i] - c[i], 0, c[i] - bhi[i]) for i in range(3)])
        return d.length

    host = min(big, key=dist)
    bpy.ops.object.select_all(action="DESELECT")
    s.select_set(True)
    host.select_set(True)
    bpy.context.view_layer.objects.active = host
    bpy.ops.object.join()
big.sort(key=lambda o: (round(-bbox(o)[1].z, 1), bbox(o)[0].x))  # top row first, left to right
items = []
for i, o in enumerate(big):
    lo, hi = bbox(o)
    o.name = f"part_{i:02d}"
    o.data.name = o.name
    items.append(dict(name=o.name, verts=len(o.data.vertices), faces=len(o.data.polygons),
                      size=[round(x, 3) for x in (hi - lo)], centre=[round(x, 3) for x in (lo + hi) / 2]))

# ---- overview render with numbers
sc = bpy.context.scene
r = sc.render
r.resolution_x, r.resolution_y = 1400, 900
r.engine = "BLENDER_EEVEE"
sc.view_settings.view_transform = "Standard"
w = bpy.data.worlds.new("w")
sc.world = w
w.use_nodes = True
next(n for n in w.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = (0.86, 0.86, 0.88, 1)
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3
sun.rotation_euler = (math.radians(50), 0, math.radians(35))
sc.collection.objects.link(sun)
allp = [bbox(o) for o in big]
lo = Vector([min(b[0][i] for b in allp) for i in range(3)])
hi = Vector([max(b[1][i] for b in allp) for i in range(3)])
c = (lo + hi) / 2
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = max(hi.x - lo.x, (hi.z - lo.z) * 14 / 9) * 1.1
sc.collection.objects.link(cam)
sc.camera = cam
cam.location = c + Vector((0, -3, 0))
cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
labels = []
for o, it in zip(big, items):
    t = bpy.data.curves.new(o.name + "_t", "FONT")
    t.body = o.name[-2:]
    t.size = (hi.z - lo.z) * 0.05
    to = bpy.data.objects.new(o.name + "_t", t)
    blo, bhi = bbox(o)
    to.location = Vector(((blo.x + bhi.x) / 2, lo.y - 0.05, bhi.z + 0.005))
    to.rotation_euler = (math.radians(90), 0, 0)
    m = bpy.data.materials.new("red")
    m.diffuse_color = (0.9, 0.05, 0.05, 1)
    m.use_nodes = True
    m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.9, 0.05, 0.05, 1)
    m.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (0.9, 0.05, 0.05, 1)
    t.materials.append(m)
    sc.collection.objects.link(to)
    labels.append(to)
r.filepath = str(out / "overview.png")
bpy.ops.render.render(write_still=True)
for to in labels:
    bpy.data.objects.remove(to, do_unlink=True)

# ---- export every item with its origin at the bottom centre
for o, it in zip(big, items):
    blo, bhi = bbox(o)
    shift = Vector(((blo.x + bhi.x) / 2, (blo.y + bhi.y) / 2, blo.z))
    for v in o.data.vertices:
        v.co = v.co - shift
    o.location = (0, 0, 0)
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    p = out / f"{o.name}.glb"
    bpy.ops.export_scene.gltf(filepath=str(p), export_format="GLB", use_selection=True)
    it["glb"] = str(p)
    for v in o.data.vertices:
        v.co = v.co + shift
(out / "kit.json").write_text(json.dumps(dict(source=src, items=items), indent=2), encoding="utf-8")
for it in items:
    print("KIT_ITEM", it["name"], "verts", it["verts"], "size", it["size"], "centre", it["centre"])
print("KIT_OK", len(items), out)
