"""Runs INSIDE Blender (background): give a rigged winged character its own wing bones and take a held prop off
the body.

    blender -b -P blender_fairy_fix.py -- rigged.glb out.glb [prop_hand=RightHand] [preview=path.png]

Wings: thin pale membranes (with a gold rim) behind the back, found by colour and grown over the surface from their
tips; split per side and into upper / lower plates; each plate gets a bone from its root at the back to its tip,
parented to the upper spine, and is weighted to it rigidly (a short blend with the spine at the root).
Prop: the gold object in the hand (a wand) is grown from its highest point over gold-coloured surface, cut out of
the body into its own mesh "Prop_<hand>", weighted 100 % to the hand bone, so the game can hide or swap it.
Prints FIX_ lines.
"""
import colorsys
import math
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Quaternion, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
me = next(o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups)
for o in list(bpy.context.scene.objects):
    if o.type == "MESH" and o is not me:
        bpy.data.objects.remove(o, do_unlink=True)
m = me.data
pre = "mixamorig:" if any(b.name.startswith("mixamorig:") for b in arm.data.bones) else ""


def bn(n):
    return pre + n if pre + n in arm.data.bones else n


img = next(n.image for mt in m.materials if mt and mt.node_tree for n in mt.node_tree.nodes
           if n.type == "TEX_IMAGE" and n.image)
W, H = img.size
px = np.empty(W * H * 4, np.float32)
img.pixels.foreach_get(px)
px = px.reshape(H, W, 4)[:, :, :3]
uv = np.empty(len(m.loops) * 2)
m.uv_layers.active.data.foreach_get("uv", uv)
uv = uv.reshape(-1, 2)
lv = np.empty(len(m.loops), dtype=np.int64)
m.loops.foreach_get("vertex_index", lv)
vuv = np.zeros((len(m.vertices), 2))
vuv[lv] = uv
col = px[np.clip((vuv[:, 1] % 1) * (H - 1), 0, H - 1).astype(int), np.clip((vuv[:, 0] % 1) * (W - 1), 0, W - 1).astype(int)]
hsv = np.array([colorsys.rgb_to_hsv(*c) for c in col])
hue, sat, val = hsv[:, 0], hsv[:, 1], hsv[:, 2]
P = np.array([tuple(me.matrix_world @ v.co) for v in m.vertices])
Hgt = P[:, 2].max() - P[:, 2].min()
bm = bmesh.new()
bm.from_mesh(m)
bm.verts.ensure_lookup_table()
NB = [[e.other_vert(v).index for e in v.link_edges] for v in bm.verts]
bm.free()


def grow(seeds, allowed):
    out = np.zeros(len(P), bool)
    st = list(seeds)
    out[st] = True
    while st:
        a = st.pop()
        for b in NB[a]:
            if allowed[b] and not out[b]:
                out[b] = True
                st.append(b)
    return out


def components(mask):
    seen = np.zeros(len(P), bool)
    comps = []
    for i in np.flatnonzero(mask):
        if seen[i]:
            continue
        c = []
        st = [i]
        seen[i] = True
        while st:
            a = st.pop()
            c.append(a)
            for b in NB[a]:
                if mask[b] and not seen[b]:
                    seen[b] = True
                    st.append(b)
        comps.append(np.array(c))
    return sorted(comps, key=len, reverse=True)


gold = (hue > 0.08) & (hue < 0.18) & (sat > 0.35) & (val > 0.45)

# ---------------------------------------------------------------- prop in the hand
hand = bn(opt.get("prop_hand", "RightHand"))
hb = arm.data.bones[hand]
hp = np.array(tuple(arm.matrix_world @ hb.head_local))
near_hand = np.linalg.norm(P - hp, axis=1) < 0.25 * Hgt
prop_allowed = gold & near_hand
prop = np.zeros(len(P), bool)
if prop_allowed.any():
    top = np.flatnonzero(prop_allowed)[np.argmax(P[prop_allowed][:, 2])]
    prop = grow([top], prop_allowed)
    # close the gaps between gold pieces (the jewel, the ribbon): neighbours mostly prop are prop
    for _ in range(3):
        add = [i for i in np.flatnonzero(~prop & near_hand) if NB[i] and sum(prop[j] for j in NB[i]) / len(NB[i]) >= 0.5]
        prop[add] = True
# the shaft: a thin straight stick on the vertical line through the gold head, down past the fist
if prop.any():
    head_c = P[prop].mean(0)
    r_shaft = float(opt.get("shaft_r", 0.012)) * Hgt
    horiz = np.linalg.norm(P[:, :2] - head_c[:2], axis=1)
    z_bottom = hp[2] - 0.12 * Hgt
    top = P[prop][:, 2].max()
    head_zone = (horiz < 0.05 * Hgt) & (P[:, 2] > top - 0.10 * Hgt)          # the star / jewel on top
    shaft = (horiz < r_shaft) & (P[:, 2] > z_bottom) & (P[:, 2] <= top - 0.10 * Hgt)
    prop = head_zone | shaft
q = P[prop]
print(f"FIX_PROP vertices={int(prop.sum())}" + (f" z {q[:, 2].min():.3f}..{q[:, 2].max():.3f}" if len(q) else ""))

# ---------------------------------------------------------------- wings
pale = (val > 0.55) & (sat < 0.45) & (((hue > 0.68) & (hue < 0.99)) | (sat < 0.15))
band = (P[:, 1] > 0.035 * Hgt / 1.0) & (P[:, 2] > 0.30 * Hgt) & (P[:, 2] < 0.81 * Hgt) & ~prop
allowed = (pale | gold) & band
seeds = np.flatnonzero(pale & allowed & (np.abs(P[:, 0]) > 0.13 * Hgt))
wing = grow(seeds, allowed)
for _ in range(2):
    add = [i for i in np.flatnonzero(~wing & band) if NB[i] and sum(wing[j] for j in NB[i]) / len(NB[i]) >= 0.6]
    wing[add] = True
# take in the rim: a few rings of neighbours that are not hair (orange) or robe (deep purple)
hair = (hue > 0.02) & (hue < 0.11) & (sat > 0.45) & (val > 0.3)
robe = (hue > 0.66) & (hue < 0.82) & (sat > 0.45) & (val < 0.6)
rim_ok = band & ~hair & ~robe
for _ in range(int(opt.get("rim_rings", 5))):
    add = [i for i in np.flatnonzero(~wing & rim_ok) if any(wing[j] for j in NB[i])]
    wing[add] = True
# holes: small patches that are not wing (dark veins of the pattern) but sit inside it join the wing
holes = components(~wing & ~prop)
filled = 0
for c in holes[1:]:                                   # [0] is the body itself
    if len(c) < 2000 and any(wing[j] for i in c for j in NB[i]):
        wing[c] = True
        filled += len(c)
print(f"FIX_HOLES filled={filled} vertices in {len(holes) - 1} patches")
comps = components(wing)
wing[:] = False
for c in comps:
    if len(c) >= 0.03 * len(comps[0]):
        wing[c] = True
print(f"FIX_WINGS vertices={int(wing.sum())} pieces={sum(1 for c in comps if len(c) >= 0.03 * len(comps[0]))}")

# plates: per side, upper / lower split where the wing is narrowest in height
plates, cuts = {}, {}
for side, s in (("L", 1), ("R", -1)):
    idx = np.flatnonzero(wing & (P[:, 0] * s > 0))
    if not len(idx):
        continue
    zs = P[idx, 2]
    hist, edges = np.histogram(zs, bins=40)
    mid = slice(10, 30)
    k = 10 + int(np.argmin(hist[mid]))
    zcut = (edges[k] + edges[k + 1]) / 2
    plates[f"wing_{side}_upper"] = idx[zs >= zcut]
    plates[f"wing_{side}_lower"] = idx[zs < zcut]
    cuts[side] = (zcut, idx)
    print(f"FIX_SPLIT {side} at z={zcut:.3f}: upper {int((zs >= zcut).sum())}, lower {int((zs < zcut).sum())}")

spine = bn("Spine2") if bn("Spine2") in arm.data.bones else bn("Spine1")
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
inv = arm.matrix_world.inverted()
roots = {}
for name, idx in plates.items():
    q = P[idx]
    k = max(8, len(q) // 50)
    root = q[np.argsort(np.abs(q[:, 0]))[:k]].mean(0)          # nearest the spine
    tipi = np.argmax(np.linalg.norm(q - root, axis=1))
    tip = q[tipi]
    eb = arm.data.edit_bones.new(name)
    eb.head = inv @ Vector(tuple(root))
    eb.tail = inv @ Vector(tuple(root + (tip - root) * 0.9))
    eb.parent = arm.data.edit_bones[spine]
    eb.use_deform = True
    roots[name] = root
bpy.ops.object.mode_set(mode="OBJECT")

# weights: plates rigid on their bone, blended with the spine over the first few centimetres
blend = 0.03 * Hgt / 0.7
for name, idx in plates.items():
    vg = me.vertex_groups.new(name=name)
    d = np.linalg.norm(P[idx] - roots[name], axis=1)
    w = np.clip(d / blend, 0.0, 1.0)
    for i, x in zip(idx, w):
        v = m.vertices[int(i)]
        for g in v.groups:
            g.weight *= (1.0 - x)
        vg.add([int(i)], float(x), "REPLACE")
        if x < 1.0:
            me.vertex_groups[spine].add([int(i)], float(1.0 - x), "ADD")
# across the split the two plates share the vertices: a smooth hand-over instead of a tear
band_w = float(opt.get("split_band", 0.025)) * Hgt
for side, (zcut, idx) in cuts.items():
    up, lo = me.vertex_groups[f"wing_{side}_upper"], me.vertex_groups[f"wing_{side}_lower"]
    for i in idx:
        dz = P[i, 2] - zcut
        if abs(dz) > band_w:
            continue
        t = 0.5 + 0.5 * dz / band_w                      # 0 at the bottom of the band, 1 at the top
        v = m.vertices[int(i)]
        total = sum(g.weight for g in v.groups if g.group in (up.index, lo.index))
        if total <= 0:
            continue
        up.add([int(i)], total * t, "REPLACE")
        lo.add([int(i)], total * (1 - t), "REPLACE")
print("FIX_BONES " + ", ".join(plates))

# ---------------------------------------------------------------- cut the prop into its own mesh
if prop.any():
    bpy.ops.object.select_all(action="DESELECT")
    me.select_set(True)
    bpy.context.view_layer.objects.active = me
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    for i in np.flatnonzero(prop):
        m.vertices[int(i)].select = True
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_mode(type="VERT")
    bpy.ops.mesh.separate(type="SELECTED")
    bpy.ops.object.mode_set(mode="OBJECT")
    pr = next(o for o in bpy.context.selected_objects if o is not me)
    pr.name = "Prop_" + hand.replace(pre, "")
    for g in list(pr.vertex_groups):
        pr.vertex_groups.remove(g)
    g = pr.vertex_groups.new(name=hand)
    g.add(list(range(len(pr.data.vertices))), 1.0, "REPLACE")
    print(f"FIX_PROP_MESH {pr.name} faces={len(pr.data.polygons)} on {hand}")

# ---------------------------------------------------------------- preview: arms up, wings spread
if opt.get("preview"):
    Wm = arm.matrix_world.to_3x3()

    def rot(n, ax, deg):
        b = arm.data.bones[n]
        mm = (Wm @ b.matrix_local.to_3x3()).inverted()
        return Quaternion((mm @ Vector(ax)).normalized(), math.radians(deg))

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
    next(x for x in wd.node_tree.nodes if x.type == "BACKGROUND").inputs["Color"].default_value = (0.82, 0.82, 0.85, 1)
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3
    sun.rotation_euler = (math.radians(50), 0, math.radians(150))
    sc.collection.objects.link(sun)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 1.05 * Hgt
    sc.collection.objects.link(cam)
    sc.camera = cam
    c = Vector((0, 0, 0.5 * Hgt))
    poses = {"rest": {}, "pose": {bn("LeftArm"): ((0, 1, 0), -55), bn("RightArm"): ((0, 1, 0), 55)}}
    for name in plates:
        s = 1 if "_L_" in name else -1
        poses["pose"][name] = ((0, 0, 1), -35 * s)   # spread back
    for tag, pose in poses.items():
        for pb in arm.pose.bones:
            pb.rotation_mode = "QUATERNION"
            pb.rotation_quaternion = (1, 0, 0, 0)
        for n, (ax, deg) in pose.items():
            arm.pose.bones[n].rotation_quaternion = rot(n, ax, deg)
        bpy.context.view_layer.update()
        for nm, d in (("back", (0.35, 1, 0.15)), ("front", (0, -1, 0.1))):
            cam.location = c + Vector(d).normalized() * 3
            cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
            r.filepath = opt["preview"].replace(".png", f"_{tag}_{nm}.png")
            bpy.ops.render.render(write_still=True)
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)

bpy.ops.object.select_all(action="SELECT")
for o in list(bpy.context.scene.objects):
    if o.type not in ("MESH", "ARMATURE"):
        o.select_set(False)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False)
print("FIX_OK", dst)
