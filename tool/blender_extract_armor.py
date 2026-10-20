"""Runs INSIDE Blender (background): cut a piece of armour out of a generated "character wearing it" model.

    blender -b -P blender_extract_armor.py -- body_parts.glb dressed.glb slot out.glb [key=value ...]

The dressed model (Hunyuan, made from pictures of the same character in armour) is aligned to the rigged base body
(height from the feet, XY on the torso), then every face is classified by its texture colour: skin-coloured faces
(reference colour sampled from the dressed model's forearms, which stay bare in every outfit) are dropped, the rest inside the slot's height band is the armour. The piece gets a little thickness and is written in the base
body's space, ready for blender_fit_armor.py mode=keep.
Options: skin_tol=0.10 (colour distance that still counts as skin), thick=0.004 (m), top=, bottom= (landmark names
or metres to override the band), debug=path.png (render of the classification),
space=source (write the piece in the dressed model's coordinates instead of the body's).
Prints lines starting with EXTRACT_.
"""
import colorsys
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
body_path, dressed_path, slot, dst = argv[0], argv[1], argv[2], argv[3]
opt = dict(a.split("=", 1) for a in argv[4:] if "=" in a)
skin_tol = float(opt.get("skin_tol", 0.10))
thick = float(opt.get("thick", 0.004))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=body_path)
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
body = [o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups]
before = set(bpy.context.scene.objects)
bpy.ops.import_scene.gltf(filepath=dressed_path)
new = [o for o in bpy.context.scene.objects if o not in before]
meshes = [o for o in new if o.type == "MESH" and not o.name.split(".")[0].endswith(("-colonly", "-convcolonly"))]
for o in [o for o in new if o.type == "MESH" and o not in meshes]:  # the item's collision proxy
    new.remove(o)
    bpy.data.objects.remove(o, do_unlink=True)
for o in meshes:
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
for o in new:
    if o.type in ("ARMATURE", "EMPTY"):
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
dressed = bpy.context.view_layer.objects.active
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
me = dressed.data
# glTF splits vertices along UV seams, so the surface falls apart into UV islands; weld them (UVs live on the
# face corners in Blender and are kept) so that neighbours, pieces and the thickness work across seams
_bm = bmesh.new()
_bm.from_mesh(me)
_n0 = len(_bm.verts)
bmesh.ops.remove_doubles(_bm, verts=_bm.verts, dist=1e-5)
print(f"EXTRACT_WELD vertices {_n0} -> {len(_bm.verts)}")
_bm.to_mesh(me)
_bm.free()
me.update()


def _norm(name):
    n = name.lower()
    for sep in ("mixamorig:", "mixamorig_", "mixamorig."):
        n = n.replace(sep, "")
    return n


def joint(*names):
    ps = [arm.matrix_world @ b.head_local for b in arm.data.bones if _norm(b.name) in names]
    return sum(ps, Vector()) / len(ps) if ps else None


neck, head = joint("neck"), joint("head")
shoulder = joint("leftarm", "rightarm", "leftupperarm", "rightupperarm")
hips = joint("leftupleg", "rightupleg", "leftupperleg", "rightupperleg")
knees = joint("leftleg", "rightleg", "leftlowerleg", "rightlowerleg")
lm = {"neck": (neck or head).z, "shoulder": shoulder.z, "hips": hips.z, "knees": knees.z,
      "ankles": joint("leftfoot", "rightfoot").z}
lm["waist"] = lm["hips"] + 0.31 * (lm["shoulder"] - lm["hips"])
lm["collar"] = (lm["neck"] + lm["shoulder"]) / 2
l_arm = joint("leftarm", "leftupperarm")

# ---------------------------------------------------------------- 1. align the dressed model to the base body
bpts = np.array([tuple(o.matrix_world @ v.co) for o in body for v in o.data.vertices])
dpts = np.empty(len(me.vertices) * 3)
me.vertices.foreach_get("co", dpts)
dpts = dpts.reshape(-1, 3)
b_lo, b_hi = bpts.min(0), bpts.max(0)
d_lo, d_hi = dpts.min(0), dpts.max(0)
s = (b_hi[2] - b_lo[2]) / (d_hi[2] - d_lo[2])


def torso_xy(pts, lo, hi):
    # centre of the torso band (between 45 % and 70 % of the height) ignores arms, ears and feet
    z0, z1 = lo[2] + 0.45 * (hi[2] - lo[2]), lo[2] + 0.70 * (hi[2] - lo[2])
    band = pts[(pts[:, 2] > z0) & (pts[:, 2] < z1)]
    band = band[np.abs(band[:, 0] - np.median(band[:, 0])) < 0.18 * (hi[2] - lo[2])]  # drop the hanging arms
    return (band[:, 0].min() + band[:, 0].max()) / 2, (band[:, 1].min() + band[:, 1].max()) / 2


bx, by = torso_xy(bpts, b_lo, b_hi)
half_sh = abs(l_arm.x - bx)
dx, dy = torso_xy(dpts, d_lo, d_hi)
dpts = (dpts - np.array([dx, dy, d_lo[2]])) * s + np.array([bx, by, b_lo[2]])
me.vertices.foreach_set("co", dpts.ravel())
me.update()
print(f"EXTRACT_ALIGN scale={s:.4f} dressed_height={(d_hi[2] - d_lo[2]):.3f} body_height={(b_hi[2] - b_lo[2]):.3f}")

# ---------------------------------------------------------------- 2. colour of every face
mat = me.materials[0]
tex = next(n for n in mat.node_tree.nodes if n.type == "TEX_IMAGE")
img = tex.image
W, H = img.size
px = np.empty(W * H * 4, dtype=np.float32)
img.pixels.foreach_get(px)
px = px.reshape(H, W, 4)[:, :, :3]
uv = np.empty(len(me.loops) * 2)
me.uv_layers.active.data.foreach_get("uv", uv)
uv = uv.reshape(-1, 2)
npoly = len(me.polygons)
loop_start = np.empty(npoly, dtype=np.int64)
me.polygons.foreach_get("loop_start", loop_start)
centre = np.empty(npoly * 3)
me.polygons.foreach_get("center", centre)
centre = centre.reshape(-1, 3)
fuv = (uv[loop_start] + uv[loop_start + 1] + uv[loop_start + 2]) / 3  # Hunyuan meshes are triangles
xi = np.clip((fuv[:, 0] % 1.0) * (W - 1), 0, W - 1).astype(int)
yi = np.clip((fuv[:, 1] % 1.0) * (H - 1), 0, H - 1).astype(int)
col = px[yi, xi]
hsv = np.array([colorsys.rgb_to_hsv(*c) for c in col])

# skin reference: the forearms are bare in every outfit we generate (chest, pants, helmet, boots)
fore = (centre[:, 2] > lm["hips"] - 0.1 * (lm["hips"] - lm["knees"])) & (centre[:, 2] < lm["waist"]) & \
       (np.abs(centre[:, 0] - bx) > 0.62 * half_sh + 0.06)
skin_ref = np.median(col[fore], axis=0) if fore.sum() > 50 else np.array([0.45, 0.45, 0.25])
# armour reference for a chest piece: the middle of the torso, front and back, is covered by it
core = (np.abs(centre[:, 0] - bx) < 0.5 * half_sh) & (centre[:, 2] > lm["waist"]) & \
       (centre[:, 2] < lm["shoulder"] - 0.04)


def kmeans(x, k, iters=20):
    rng = np.random.default_rng(0)
    c = x[rng.choice(len(x), k, replace=False)]
    for _ in range(iters):
        lab_ = np.argmin(((x[:, None] - c[None]) ** 2).sum(-1), 1)
        c = np.array([x[lab_ == i].mean(0) if (lab_ == i).any() else c[i] for i in range(k)])
    return c


if slot == "chest" and fore.sum() > 50 and core.sum() > 50:
    # nearest of several skin colours (forearms) vs several armour colours (torso core): leather and green skin
    # can be close in hue, a single threshold mixes them up
    sk_c, ar_c = kmeans(col[fore], 4), kmeans(col[core], 6)
    d_sk = np.sqrt(((col[:, None] - sk_c[None]) ** 2).sum(-1)).min(1)
    d_ar = np.sqrt(((col[:, None] - ar_c[None]) ** 2).sum(-1)).min(1)
    skin = d_sk * (1.0 + skin_tol) < d_ar  # ties go to the armour: a hole is worse than a speck of skin
    how = f"nearest of 4 skin / 6 armour colours ({int(core.sum())} core faces)"
else:
    ref_hsv = colorsys.rgb_to_hsv(*skin_ref)
    dh = np.abs(hsv[:, 0] - ref_hsv[0])
    dh = np.minimum(dh, 1 - dh)
    skin = (dh < 0.06 + skin_tol * 0.3) & (hsv[:, 1] > ref_hsv[1] * 0.55) & \
           (np.linalg.norm(col - skin_ref, axis=1) < 0.18 + skin_tol)
    how = "hue/distance threshold"
print(f"EXTRACT_SKIN ref_rgb={tuple(round(float(c), 3) for c in skin_ref)} from {int(fore.sum())} forearm faces, "
      f"{how}, skin faces={int(skin.sum())} of {npoly}")

bm = bmesh.new()
bm.from_mesh(me)
bm.faces.ensure_lookup_table()
nbr = [[f2.index for e in f.edges for f2 in e.link_faces if f2 is not f] for f in bm.faces]

def flood_colour(seed, tol, allowed):
    """Faces of the seed's median colour that are connected to the seed (through such faces) inside `allowed`."""
    ref = np.median(col[seed], axis=0)
    near = (np.linalg.norm(col - ref, axis=1) < tol) & allowed
    mask = seed & near
    stack = list(np.flatnonzero(mask))
    while stack:
        k = stack.pop()
        for j in nbr[k]:
            if near[j] and not mask[j]:
                mask[j] = True
                stack.append(j)
    return mask, tuple(round(float(c), 3) for c in ref)

# ---------------------------------------------------------------- 3. height band of the slot
BAND = {"chest": ("neck", "hips"), "pants": ("waist", "ankles"), "helmet": (None, "neck"),
        "boots": ("knees", None), "gloves": ("waist", "knees")}
top, bot = BAND.get(slot, (None, None))
top = opt.get("top", top)
bot = opt.get("bottom", bot)


def zval(x, default):
    if x is None:
        return default
    try:
        return float(x)
    except ValueError:
        return lm[x]


z_top = zval(top, 1e9)
z_bot = zval(bot, -1e9)
if slot == "chest":
    z_bot -= 0.25 * (lm["hips"] - lm["knees"])  # a vest may come down over the belt
cand = ~skin & (centre[:, 2] < z_top) & (centre[:, 2] > z_bot)
pants_mask = np.zeros(npoly, bool)
beard_mask = np.zeros(npoly, bool)
if slot == "chest":  # no hands, no hanging arms below the armpit
    armpit = half_sh * 1.15
    cand &= ~((np.abs(centre[:, 0] - bx) > armpit) & (centre[:, 2] < lm["shoulder"] - 0.02))
    # the pants: their colour is sampled at the crotch (always cloth under a vest) and removed below the waist
    leg_h = lm["hips"] - lm["knees"]
    crotch = (centre[:, 2] < lm["hips"] - 0.12 * leg_h) & (centre[:, 2] > lm["hips"] - 0.35 * leg_h) & \
             (np.abs(centre[:, 0] - bx) < half_sh * 0.7) & ~skin
    if crotch.sum() > 30:
        # only cloth connected to the crotch: dark shadows on the metal have the same colour but are not attached
        pants_mask, ref = flood_colour(crotch, float(opt.get("pants_tol", 0.08)), centre[:, 2] < lm["waist"])
        cand &= ~pants_mask
        print(f"EXTRACT_PANTS ref_rgb={ref} from {int(crotch.sum())} faces, removed={int(pants_mask.sum())}")
    # the beard: hair hanging from the chin over the collar, grown down from the chin
    chin = (centre[:, 2] > lm["neck"]) & (centre[:, 2] < lm["neck"] + 0.05) & \
           (np.abs(centre[:, 0] - bx) < half_sh * 0.35) & (centre[:, 1] < by - 0.02) & ~skin
    if chin.sum() > 20:
        beard, ref = flood_colour(chin, float(opt.get("beard_tol", 0.2)),
                                  (centre[:, 2] > lm["waist"]) & (centre[:, 1] < by))
        cand &= ~beard
        beard_mask = beard
        print(f"EXTRACT_BEARD ref_rgb={ref} from {int(chin.sum())} faces, removed={int(beard.sum())}")
    # ...and by shape: whatever hangs below the neck right where the base character's own head part (beard) is
    head = [o for o in body if o.name.split(".")[0] == "Body_head"]
    if head:
        from mathutils.bvhtree import BVHTree
        hv = [head[0].matrix_world @ v.co for v in head[0].data.vertices]
        hbvh = BVHTree.FromPolygons(hv, [tuple(p.vertices) for p in head[0].data.polygons])
        tol = float(opt.get("beard_gap", 0.02))
        zone = np.flatnonzero(cand & (centre[:, 2] < lm["neck"]) & (centre[:, 1] < by))
        near_head = np.zeros(npoly, bool)
        for k in zone:
            hit = hbvh.find_nearest(Vector(centre[k].tolist()), tol)
            near_head[k] = hit[0] is not None
        cand &= ~near_head
        beard_mask = beard_mask | near_head
        print(f"EXTRACT_BEARD_SHAPE removed={int(near_head.sum())} faces within {tol * 1000:.0f} mm of Body_head")
removed = pants_mask | beard_mask  # never brought back by the smoothing below

# ---------------------------------------------------------------- 4. smooth the labels, keep big pieces
lab = cand.copy()
for _ in range(3):
    votes = np.array([sum(lab[j] for j in nb) / max(len(nb), 1) for nb in nbr])
    lab = np.where(votes > 0.5, True, np.where(votes < 0.5, False, lab)) & (centre[:, 2] < z_top) & (centre[:, 2] > z_bot) & ~removed
# close small holes (dark gaps between plates, rivets): grow into non-skin faces, then shrink back
grow_n = int(opt.get("close", 4))
in_band = (centre[:, 2] < z_top) & (centre[:, 2] > z_bot)
g = lab.copy()
for _ in range(grow_n):
    g = g | (np.array([any(g[j] for j in nb) for nb in nbr]) & ~skin & ~removed & in_band)
for _ in range(grow_n):
    g = g & np.array([all(g[j] for j in nb) for nb in nbr])
print(f"EXTRACT_CLOSE filled={int((g & ~lab).sum())} faces")
lab = lab | g
seen = np.zeros(npoly, bool)
comps = []
for f in range(npoly):
    if not lab[f] or seen[f]:
        continue
    stack, comp = [f], []
    seen[f] = True
    while stack:
        k = stack.pop()
        comp.append(k)
        for j in nbr[k]:
            if lab[j] and not seen[j]:
                seen[j] = True
                stack.append(j)
    comps.append(comp)
comps.sort(key=len, reverse=True)
keep = set()
for c in comps:
    if len(c) >= max(200, 0.02 * len(comps[0])):
        keep.update(c)
print(f"EXTRACT_PIECES kept={sum(1 for c in comps if len(c) >= max(200, 0.02 * len(comps[0])))} "
      f"of {len(comps)} faces={len(keep)} band_z=({z_bot:.3f}..{z_top if z_top < 1e8 else 0:.3f})")

if opt.get("debug"):
    # colour code for a quick look: red = armour, green = skin, grey = other
    dbg = dressed.copy()
    dbg.data = me.copy()
    bpy.context.scene.collection.objects.link(dbg)
    mats = []
    for name, rgba in (("armour", (0.9, 0.1, 0.1, 1)), ("skin", (0.1, 0.7, 0.1, 1)), ("other", (0.6, 0.6, 0.6, 1)), ("dropped", (0.1, 0.3, 0.9, 1)), ("pants", (0.9, 0.8, 0.1, 1))):
        m = bpy.data.materials.new(name)
        m.diffuse_color = rgba
        m.use_nodes = True
        m.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = rgba
        mats.append(m)
    dbg.data.materials.clear()
    for m in mats:
        dbg.data.materials.append(m)
    kept = np.isin(np.arange(npoly), list(keep))
    idx = np.select([kept, skin, cand, removed], [0, 1, 3, 4], 2)
    dbg.data.polygons.foreach_set("material_index", idx.astype(np.int32))
    dbg.data.update()

# ---------------------------------------------------------------- 5. separate, thicken, export
for f in bm.faces:
    f.select = f.index in keep
drop = [f for f in bm.faces if f.index not in keep]
bmesh.ops.delete(bm, geom=drop, context="FACES")
bm.to_mesh(me)
bm.free()
me.update()
dressed.name = f"Armor_{slot}"
mod = dressed.modifiers.new("thick", "SOLIDIFY")
mod.thickness = thick
mod.offset = -1.0
mod.use_even_offset = True
bpy.context.view_layer.objects.active = dressed
bpy.ops.object.modifier_apply(modifier=mod.name)
print(f"EXTRACT_MESH faces={len(me.polygons)} thickness={thick * 1000:.0f} mm")

if opt.get("debug"):
    sc = bpy.context.scene
    for o in body:
        o.hide_render = True
    dressed.hide_render = True
    r = sc.render
    r.resolution_x, r.resolution_y = 500, 700
    r.engine = "BLENDER_WORKBENCH"
    sc.display.shading.color_type = "MATERIAL"
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = "ORTHO"
    hgt = b_hi[2] - b_lo[2]
    cam.data.ortho_scale = hgt * 1.1
    sc.collection.objects.link(cam)
    sc.camera = cam
    c = Vector(((b_lo + b_hi) / 2).tolist())
    for name, d in (("front", (0, -1, 0)), ("side", (1, 0, 0)), ("back", (0, 1, 0))):
        cam.location = c + Vector(d) * hgt * 3
        cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
        r.filepath = opt["debug"].replace(".png", f"_{name}.png")
        bpy.ops.render.render(write_still=True)
    bpy.data.objects.remove(dbg, do_unlink=True)

for o in body:
    bpy.data.objects.remove(o, do_unlink=True)
bpy.data.objects.remove(arm, do_unlink=True)
for o in list(bpy.context.scene.objects):
    if o is not dressed:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
dressed.select_set(True)
if opt.get("space") == "source":
    # back into the dressed model's own coordinates (for blender_transfer_armor.py, which carries the piece
    # over by the skeletons instead of this simple height alignment)
    m = dressed.data
    co = np.empty(len(m.vertices) * 3)
    m.vertices.foreach_get("co", co)
    co = (co.reshape(-1, 3) - np.array([bx, by, b_lo[2]])) / s + np.array([dx, dy, d_lo[2]])
    m.vertices.foreach_set("co", co.ravel())
    m.update()
    print("EXTRACT_SPACE source (dressed model coordinates)")
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True)
print("EXTRACT_OK", dst)
