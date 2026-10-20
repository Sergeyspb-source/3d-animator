"""Runs INSIDE Blender (background): prepare a tree, bush or grass model for wind in Godot.

    blender -b -P blender_vegetation.py -- model.glb out.glb [kind=tree|bush|grass] [preview=path.png]

Writes a vertex colour layer "wind" (glTF COLOR_0) that the Godot shader tool/godot/wind_foliage.gdshader reads:
  R  bend    how far the vertex sways with the whole plant: 0 at the root, growing with height (squared, so the
             trunk stays stiff and the crown moves),
  G  flutter quick small motion of leaves: 1 on foliage (found by texture colour: green / autumn hues, or the
             outer shell of the crown), 0 on bark,
  B  phase   a per-clump offset (0..1) so different branches do not move in step.
The mesh is put on the ground with its origin at the root (pivot at the base, what a placed plant needs).
Prints VEG_ lines.
"""
import colorsys
import math
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
kind = opt.get("kind", "tree")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and not o.name.split(".")[0].endswith(
    ("-colonly", "-convcolonly"))]
cols = [o for o in bpy.context.scene.objects if o.type == "MESH" and o not in meshes]
for o in meshes:
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
m = ob.data
P = np.array([tuple(v.co) for v in m.vertices])

# ---- the root: lowest part of the trunk, centre of the bottom 3 % of the height
z0, z1 = P[:, 2].min(), P[:, 2].max()
H = z1 - z0
base = P[P[:, 2] < z0 + 0.03 * H]
root = np.array([np.median(base[:, 0]), np.median(base[:, 1]), z0])
shift = Vector((-root[0], -root[1], -root[2]))
for v in m.vertices:
    v.co += shift
for o in cols:
    o.location += shift
P = np.array([tuple(v.co) for v in m.vertices])

# ---- texture colour per vertex
img = None
for mt in m.materials:
    if mt and mt.node_tree:
        for n in mt.node_tree.nodes:
            if n.type == "TEX_IMAGE" and n.image and n.image.size[0] > 0:
                img = n.image
                break
foliage = np.zeros(len(P))
if img is not None and m.uv_layers:
    W, Hh = img.size
    px = np.empty(W * Hh * 4, np.float32)
    img.pixels.foreach_get(px)
    px = px.reshape(Hh, W, 4)[:, :, :3]
    uv = np.empty(len(m.loops) * 2)
    m.uv_layers.active.data.foreach_get("uv", uv)
    uv = uv.reshape(-1, 2)
    lv = np.empty(len(m.loops), dtype=np.int64)
    m.loops.foreach_get("vertex_index", lv)
    vuv = np.zeros((len(P), 2))
    vuv[lv] = uv
    c = px[np.clip((vuv[:, 1] % 1) * (Hh - 1), 0, Hh - 1).astype(int), np.clip((vuv[:, 0] % 1) * (W - 1), 0, W - 1).astype(int)]
    # reference colours from the plant itself: the outer top of the crown is foliage, the trunk near the ground
    # is bark; every vertex takes the nearer one (works for olive, autumn and blue-ish leaves alike)
    hrel0 = (P[:, 2] - z0) / max(H, 1e-6)
    rad0 = np.hypot(P[:, 0] - root[0], P[:, 1] - root[1])
    rad0 = rad0 / max(rad0.max(), 1e-6)
    crown_s = (hrel0 > 0.7) & (rad0 > 0.35) if kind == "tree" else (hrel0 > 0.6)
    trunk_s = (hrel0 > 0.05) & (hrel0 < 0.3) & (rad0 < 0.25)
    if kind != "grass" and crown_s.sum() > 30 and trunk_s.sum() > 30:
        cr, tr = np.median(c[crown_s], 0), np.median(c[trunk_s], 0)
        dc, dt = np.linalg.norm(c - cr, axis=1), np.linalg.norm(c - tr, axis=1)
        foliage = (dc < dt).astype(float)
        print(f"VEG_COLOURS crown={np.round(cr, 2)} bark={np.round(tr, 2)}")
    else:
        hsv = np.array([colorsys.rgb_to_hsv(*x) for x in c])
        hue, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]
        foliage = ((hue > 0.1) & (hue < 0.48) & (sat > 0.15)).astype(float)# leaves hang high: very low "green" is moss on the roots, not foliage
if kind == "tree":
    foliage *= (P[:, 2] > 0.25 * H)

# smooth the foliage mask over the surface a little (texture specks)
bm = bmesh.new()
bm.from_mesh(m)
bm.verts.ensure_lookup_table()
NB = [[e.other_vert(v).index for e in v.link_edges] for v in bm.verts]
bm.free()
for _ in range(3):
    foliage = np.array([(foliage[i] + sum(foliage[j] for j in nb)) / (1 + len(nb)) for i, nb in enumerate(NB)])
foliage = np.clip((foliage - 0.25) / 0.5, 0, 1)

# ---- bend: grows with height; grass bends from the very root, a tree's trunk stays stiff
hrel = np.clip(P[:, 2] / max(H, 1e-6), 0, 1)
radial = np.linalg.norm(P[:, :2], axis=1) / max(np.linalg.norm(P[:, :2], axis=1).max(), 1e-6)
if kind == "grass":
    bend = hrel ** 1.3
elif kind == "bush":
    bend = np.clip(hrel ** 1.6 + 0.3 * radial * hrel, 0, 1)
else:
    bend = np.clip(hrel ** 2.2 + 0.35 * radial * hrel, 0, 1)

# ---- phase per clump: cluster positions of the crown into ~12 groups (k-means), branches move out of step
phase = np.zeros(len(P))
crown = np.flatnonzero(hrel > 0.2)
if len(crown) > 50:
    rng = np.random.default_rng(1)
    k = min(12, len(crown) // 20)
    cent = P[crown][rng.choice(len(crown), k, replace=False)]
    for _ in range(12):
        lab = np.argmin(((P[crown][:, None] - cent[None]) ** 2).sum(-1), 1)
        cent = np.array([P[crown][lab == i].mean(0) if (lab == i).any() else cent[i] for i in range(k)])
    d = np.sqrt(((P[:, None] - cent[None]) ** 2).sum(-1))
    w = np.exp(-(d / (0.15 * H)) ** 2)
    ph = rng.random(k)
    # smooth blend of the clump phases (sin/cos average keeps it continuous across clump borders)
    s = (w * np.sin(2 * math.pi * ph)).sum(1)
    c_ = (w * np.cos(2 * math.pi * ph)).sum(1)
    phase = (np.arctan2(s, c_) / (2 * math.pi)) % 1.0

# ---- write COLOR_0
for a in list(m.color_attributes):
    m.color_attributes.remove(a)
ca = m.color_attributes.new("wind", "FLOAT_COLOR", "POINT")
data = np.zeros(len(P) * 4, np.float32)
data[0::4], data[1::4], data[2::4], data[3::4] = bend, foliage, phase, 1.0
ca.data.foreach_set("color", data)
m.color_attributes.active_color = ca
m.color_attributes.render_color_index = 0
print(f"VEG_WIND kind={kind} height={H:.3f} foliage share={float((foliage > 0.5).mean()):.2f} "
      f"bend at top={float(bend[P[:, 2] > 0.9 * H].mean() if (P[:, 2] > 0.9 * H).any() else 0):.2f}")

if opt.get("preview"):
    # debug view: R/G as colours (bend red, foliage green)
    mat = bpy.data.materials.new("dbg")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    attr = nt.nodes.new("ShaderNodeVertexColor")
    attr.layer_name = "wind"
    nt.links.new(attr.outputs[0], bsdf.inputs["Base Color"])
    keep = list(m.materials)
    m.materials.clear()
    m.materials.append(mat)
    sc = bpy.context.scene
    r = sc.render
    r.resolution_x, r.resolution_y = 520, 560
    try:
        r.engine = "BLENDER_EEVEE"
    except TypeError:
        r.engine = "BLENDER_WORKBENCH"
    sc.view_settings.view_transform = "Standard"
    wd = bpy.data.worlds.new("w")
    sc.world = wd
    wd.use_nodes = True
    next(n for n in wd.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = (0.9, 0.9, 0.92, 1)
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    sc.collection.objects.link(sun)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = "ORTHO"
    sc.collection.objects.link(cam)
    sc.camera = cam
    span = max(H, (P[:, 0].max() - P[:, 0].min()), (P[:, 1].max() - P[:, 1].min()))
    cam.data.ortho_scale = 1.1 * span
    c = Vector((0, 0, H / 2))
    cam.location = c + Vector((0, -1, 0.15)).normalized() * 3 * span
    cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
    r.filepath = opt["preview"]
    bpy.ops.render.render(write_still=True)
    m.materials.clear()
    for mt in keep:
        m.materials.append(mt)

# ---- collision: a simple cylinder around the trunk (the crown stays walk-through); none for grass
for o in cols:
    bpy.data.objects.remove(o, do_unlink=True)
if kind != "grass":
    band = P[(P[:, 2] > 0.12 * H) & (P[:, 2] < 0.35 * H) & (foliage < 0.5)]
    if len(band) < 20:
        band = P[P[:, 2] < 0.35 * H]
    cx, cy = np.median(band[:, 0]), np.median(band[:, 1])
    rad = float(np.percentile(np.hypot(band[:, 0] - cx, band[:, 1] - cy), 70))
    top = (0.6 if kind == "tree" else 0.9) * H
    bm = bmesh.new()
    bmesh.ops.create_cone(bm, cap_ends=True, segments=8, radius1=rad, radius2=rad * 0.8, depth=top)
    for v in bm.verts:
        v.co += Vector((cx, cy, top / 2))
    cm = bpy.data.meshes.new(ob.name + "-convcolonly")
    bm.to_mesh(cm)
    bm.free()
    co = bpy.data.objects.new(ob.name + "-convcolonly", cm)
    bpy.context.scene.collection.objects.link(co)
    print(f"VEG_COLLISION trunk radius={rad:.3f} height={top:.3f}")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True, export_vertex_color="ACTIVE",
                          export_all_vertex_colors=False)
print("VEG_OK", dst)
