"""Runs INSIDE Blender (background): clean the edges of armour segments in a segmented model (Tripo parts) by colour.

    blender -b -P blender_refine_segments.py -- model.glb out.glb skin=tripo_part_2,tripo_part_36 [rings=3]
                                               [split=1] [debug=sheet.png]

Automatic segmentation cuts along existing polygons, so near the border a piece of armour carries faces that are
really skin (green specks on the rim). Each part has its own texture, baked from the full model, so the colour of
a face tells what it is. For every armour part (every part not listed in skin=):
1) reference colours: k-means of the skin parts (skin) and of the part's own interior (armour),
2) the faces within `rings` of the part's open border are split (split=1: each into four, UVs follow) so the new
   border can run through the middle of an old face,
3) border-zone faces whose colour is nearer to skin than to the armour are removed (small islands that the removal
   leaves behind go too).
The result keeps every object name, so blender_export_segments.py works on it unchanged. Prints REFINE_ lines.
"""
import sys

import bmesh
import bpy
import numpy as np

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
skin_names = set(opt.get("skin", "").split(","))
rings = int(opt.get("rings", 3))
do_split = opt.get("split", "1") != "0"
bias = float(opt.get("bias", 0.4))  # a border face goes only if clearly nearer to skin than to armour

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = [o for o in bpy.context.scene.objects if o.type == "MESH"]


def pixels(o):
    for m in o.data.materials:
        if m and m.node_tree:
            for n in m.node_tree.nodes:
                if n.type == "TEX_IMAGE" and n.image and n.image.size[0] > 0:
                    w, h = n.image.size
                    px = np.empty(w * h * 4, dtype=np.float32)
                    n.image.pixels.foreach_get(px)
                    return px.reshape(h, w, 4)[:, :, :3]
    return None


def face_colours(bm, px):
    uvl = bm.loops.layers.uv.active
    h, w = px.shape[:2]
    out = np.zeros((len(bm.faces), 3), dtype=np.float32)
    for i, f in enumerate(bm.faces):
        u = sum(l[uvl].uv.x for l in f.loops) / len(f.loops)
        v = sum(l[uvl].uv.y for l in f.loops) / len(f.loops)
        out[i] = px[min(h - 1, max(0, int((v % 1.0) * (h - 1)))), min(w - 1, max(0, int((u % 1.0) * (w - 1))))]
    return out


def kmeans(x, k, iters=20):
    rng = np.random.default_rng(0)
    k = min(k, len(x))
    c = x[rng.choice(len(x), k, replace=False)]
    for _ in range(iters):
        lab = np.argmin(((x[:, None] - c[None]) ** 2).sum(-1), 1)
        c = np.array([x[lab == i].mean(0) if (lab == i).any() else c[i] for i in range(k)])
    return c


def nearest(col, cents):
    return np.sqrt(((col[:, None] - cents[None]) ** 2).sum(-1)).min(1)


# ---- skin colours from the skin parts
skin_cols = []
for o in objs:
    if o.name in skin_names:
        px = pixels(o)
        if px is None:
            continue
        bm = bmesh.new()
        bm.from_mesh(o.data)
        skin_cols.append(face_colours(bm, px))
        bm.free()
if not skin_cols:
    print("REFINE_FAIL no skin parts given (skin=...)")
    raise SystemExit
allc = np.concatenate(skin_cols)
# only the skin itself: the skin parts also carry beard, hair, nails and shadows, which look like metal and leather.
# Keep colours whose hue is in the skin's own range (the dominant hue of the skin parts) and that are not grey.
import colorsys  # noqa: E402

hsv = np.array([colorsys.rgb_to_hsv(*c) for c in allc])
sat_ok = hsv[:, 1] > 0.25
hue0 = np.median(hsv[sat_ok, 0]) if sat_ok.any() else 0.15
dh = np.abs(hsv[:, 0] - hue0)
dh = np.minimum(dh, 1 - dh)
pure = sat_ok & (dh < float(opt.get("hue_tol", 0.05))) & (hsv[:, 2] > 0.2)
skin_c = kmeans(allc[pure] if pure.sum() > 50 else allc, 5)
print(f"REFINE_SKIN hue {hue0 * 360:.0f} deg, {int(pure.sum())} of {len(allc)} skin-part faces used")
print("REFINE_SKIN reference colours:", [tuple(round(float(x), 2) for x in c) for c in skin_c])

for o in objs:
    if o.name in skin_names or len(o.data.polygons) < 50:
        continue
    px = pixels(o)
    if px is None:
        continue
    bm = bmesh.new()
    bm.from_mesh(o.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.faces.ensure_lookup_table()
    n0 = len(bm.faces)

    # distance of every face (in rings) from the open border
    ring = {}
    front = [f for f in bm.faces if any(e.is_boundary for e in f.edges)]
    for f in front:
        ring[f] = 0
    r = 0
    while front and r < rings:
        r += 1
        nxt = []
        for f in front:
            for e in f.edges:
                for g in e.link_faces:
                    if g not in ring:
                        ring[g] = r
                        nxt.append(g)
        front = nxt
    zone = [f for f, k in ring.items() if k < rings]
    inner = [f for f in bm.faces if f not in ring]
    col_all = face_colours(bm, px)
    idx = {f: i for i, f in enumerate(bm.faces)}
    if len(inner) < 30:
        inner = list(bm.faces)
    arm_c = kmeans(col_all[[idx[f] for f in inner]], 6)

    if do_split and zone:
        # split the border zone so the new edge can run through the middle of an old face
        edges = list({e for f in zone for e in f.edges})
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=1, use_grid_fill=True)
        bm.faces.ensure_lookup_table()
        # the zone again, on the finer faces
        ring = {}
        front = [f for f in bm.faces if any(e.is_boundary for e in f.edges)]
        for f in front:
            ring[f] = 0
        r = 0
        while front and r < rings * 2:
            r += 1
            nxt = []
            for f in front:
                for e in f.edges:
                    for g in e.link_faces:
                        if g not in ring:
                            ring[g] = r
                            nxt.append(g)
            front = nxt
        zone = [f for f, k in ring.items() if k < rings * 2]
    col = face_colours(bm, px)
    fidx = {f: i for i, f in enumerate(bm.faces)}
    zc = col[[fidx[f] for f in zone]] if zone else np.zeros((0, 3))
    is_skin = nearest(zc, skin_c) * (1.0 + bias) < nearest(zc, arm_c)
    kill = {f for f, s in zip(zone, is_skin) if s}
    # grow the removal through skin-coloured border faces only once more (thin green rims)
    bmesh.ops.delete(bm, geom=list(kill), context="FACES")
    # specks left floating
    bm.faces.ensure_lookup_table()
    seen, islands = set(), []
    for f in bm.faces:
        if f in seen:
            continue
        st, isl = [f], []
        seen.add(f)
        while st:
            a = st.pop()
            isl.append(a)
            for e in a.edges:
                for g in e.link_faces:
                    if g not in seen:
                        seen.add(g)
                        st.append(g)
        islands.append(isl)
    big = max(len(i) for i in islands) if islands else 0
    specks = [f for i in islands if len(i) < 0.01 * big for f in i]
    if specks:
        bmesh.ops.delete(bm, geom=specks, context="FACES")
    bm.to_mesh(o.data)
    bm.free()
    o.data.update()
    print(f"REFINE_PART {o.name} faces {n0} -> {len(o.data.polygons)}: border zone {len(zone)} faces, "
          f"skin removed {len(kill)}, specks {len(specks)}")

bpy.ops.object.select_all(action="SELECT")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True)
print("REFINE_OK", dst)
