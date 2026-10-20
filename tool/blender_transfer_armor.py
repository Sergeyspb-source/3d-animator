"""Runs INSIDE Blender (background): carry an armour piece from the body it was made for onto our base body.

    blender -b -P blender_transfer_armor.py -- src_parts.glb armour_on_src.glb dst_parts.glb out.glb [key=value ...]

src_parts.glb  the kit's own naked body, rigged and split (same bone names as ours)
armour_on_src  the armour fitted and skinned on that body (blender_fit_armor.py output)
dst_parts.glb  our base body, rigged and split
1) skeleton: every bone of the source maps onto the same bone of ours (move, turn, stretch along the bone by the
   length ratio, scale across it by the ratio of body thickness around the bone); body and armour follow by their
   skin weights, like an animation pose,
2) surface: the remaining difference between the two naked bodies (muscles, belly) is measured per source-body
   vertex and carried to the armour from its nearest source-body points,
3) report: how far the armour stands off our body and how much of our body would show through.
The result is a static mesh in our body's space, for blender_fit_armor.py mode=keep (push-out, skinning).
Options: girth=1 (0 = no thickness matching), surface=1, k=8 (neighbours for the surface step),
skin_excl=0.02 (source points this close to the armour are not skin), armour_all=path.glb (every piece of the
outfit in source coordinates: none of it counts as skin), rigid=1 (helmets, whole heads: no bending,
no surface step).
Prints lines starting with XFER_.
"""
import sys

import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.kdtree import KDTree

argv = sys.argv[sys.argv.index("--") + 1:]
src_path, arm_path, dst_path, out = argv[:4]
opt = dict(a.split("=", 1) for a in argv[4:] if "=" in a)
use_girth = opt.get("girth", "1") != "0"
use_surface = opt.get("surface", "1") != "0"
K = int(opt.get("k", 8))


def norm(name):
    n = name.lower()
    for sep in ("mixamorig:", "mixamorig_", "mixamorig."):
        n = n.replace(sep, "")
    return n


def load(path):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.context.scene.objects if o not in before]
    bpy.context.view_layer.update()
    arm = next((o for o in new if o.type == "ARMATURE"), None)
    meshes = [o for o in new if o.type == "MESH" and o.vertex_groups]
    return arm, meshes


bpy.ops.wm.read_factory_settings(use_empty=True)
s_arm, s_body = load(src_path)
a_arm, a_meshes = load(arm_path)
d_arm, d_body = load(dst_path)


def frames(arm):
    out = {}
    for b in arm.data.bones:
        h = arm.matrix_world @ b.head_local
        t = arm.matrix_world @ b.tail_local
        out[norm(b.name)] = (h, t, b)
    return out


fs, fd = frames(s_arm), frames(d_arm)


def skin(o):
    """world positions and {bone: weight} per vertex"""
    names = {vg.index: norm(vg.name) for vg in o.vertex_groups}
    pts = [o.matrix_world @ v.co for v in o.data.vertices]
    ws = [{names[g.group]: g.weight for g in v.groups if g.weight > 1e-4} for v in o.data.vertices]
    return pts, ws


def resolve(bone):
    """our bone for a source bone; a bone we do not have takes its parent's mapping"""
    cur = fs[bone][2] if bone in fs else None
    while cur is not None:
        if norm(cur.name) in fd:
            return norm(cur.name)
        cur = cur.parent
    return None


# ---- thickness of the body around every bone (mean distance of its dominant vertices from the bone segment)
def girth(frames_, parts):
    acc = {}
    for o in parts:
        pts, ws = skin(o)
        for p, w in zip(pts, ws):
            if not w:
                continue
            b = max(w, key=w.get)
            if b not in frames_:
                continue
            h, t, _ = frames_[b]
            d = t - h
            L = d.length or 1e-6
            u = max(0.0, min(1.0, (p - h).dot(d) / (L * L)))
            acc.setdefault(b, []).append((p - (h + d * u)).length)
    return {b: float(np.median(v)) for b, v in acc.items() if len(v) >= 20}


gs, gd = (girth(fs, s_body), girth(fd, d_body)) if use_girth else ({}, {})

# overall size ratio (a Hunyuan model is ~2 units tall, ours 1 m): thickness ratios are judged relative to it
def height(parts):
    zs = [(o.matrix_world @ v.co).z for o in parts for v in o.data.vertices]
    return max(zs) - min(zs)


g_all = height(d_body) / max(height(s_body), 1e-6)
XF = {}
for b in fs:
    tb = resolve(b)
    if tb is None:
        continue
    hs, ts, _ = fs[b]
    hd, td, _ = fd[tb]
    ds, dd = ts - hs, td - hd
    if ds.length < 1e-6 or dd.length < 1e-6:
        continue
    q = ds.normalized().rotation_difference(dd.normalized())
    along = dd.length / ds.length if tb == b else 1.0
    g = gd.get(tb, 0) / gs[b] if b in gs and gd.get(tb) else g_all
    g = g_all * max(0.7, min(1.45, g / g_all))
    XF[b] = (hs, ds.normalized(), along, g, q, hd)
print(f"XFER_BONES mapped={len(XF)} of {len(fs)} source bones, girth ratios: "
      + " ".join(f"{b}={XF[b][3]:.2f}" for b in ("spine", "spine1", "spine2", "hips", "leftarm", "leftupleg") if b in XF))


def move(p, w):
    acc, tot = Vector(), 0.0
    for b, x in w.items():
        xf = XF.get(b) or XF.get(resolve(b) or "", None)
        if xf is None:
            continue
        hs, u, along, g, q, hd = xf
        r = p - hs
        a = r.dot(u)
        perp = r - u * a
        local = u * (a * along) + perp * g
        acc += (hd + q @ local) * x
        tot += x
    return acc / tot if tot > 0 else p


# ---- 1. skeleton step: source body and armour
src_pts, src_def = [], []
for o in s_body:
    pts, ws = skin(o)
    for p, w in zip(pts, ws):
        src_pts.append(p)
        src_def.append(move(p, w))
armour = a_meshes[0]
a_pts, a_ws = skin(armour)
rigid = opt.get("rigid") == "1"
if rigid:
    # a helmet or a whole head must not bend: one bone (the one carrying most of its weight) moves, turns and
    # scales it as a solid, by the overall size ratio of the two bodies
    tot = {}
    for w in a_ws:
        for b, x in w.items():
            tot[b] = tot.get(b, 0.0) + x
    rb = max(tot, key=tot.get)
    hs, u, along, g, q, hd = XF[rb]
    a_def = [hd + q @ ((p - hs) * g_all) for p in a_pts]
    print(f"XFER_RIGID bone={rb} scale={g_all:.3f}")
else:
    a_def = [move(p, w) for p, w in zip(a_pts, a_ws)]

# our body as a surface
dv, dt = [], []
for o in d_body:
    base = len(dv)
    dv += [o.matrix_world @ v.co for v in o.data.vertices]
    for poly in o.data.polygons:
        vs = list(poly.vertices)
        for k in range(1, len(vs) - 1):
            dt.append((base + vs[0], base + vs[k], base + vs[k + 1]))
dbvh = BVHTree.FromPolygons(dv, dt)


def body_dist(pts):
    ds = []
    for p in pts:
        loc, n, i, d = dbvh.find_nearest(p)
        ds.append(d if loc is not None else 1.0)
    return np.array(ds)


before = body_dist(src_def)
print(f"XFER_SKELETON naked bodies after the skeleton step: median gap {np.median(before) * 1000:.1f} mm, "
      f"90% {np.percentile(before, 90) * 1000:.1f} mm")

# ---- 2. surface step: residual offsets of the source body, carried to the armour
if use_surface and not rigid:
    # only bare skin measures the difference: where the source "body" is the armour itself (a dressed model
    # cut apart), its offset to our body would glue the armour onto our skin
    # (all pieces of the outfit, if given: the tunic next to a pauldron is not skin either)
    ev, et = list(a_pts), [tuple(p.vertices) for p in armour.data.polygons]
    if opt.get("armour_all"):
        before_all = set(bpy.context.scene.objects)
        bpy.ops.import_scene.gltf(filepath=opt["armour_all"])
        for o in [o for o in bpy.context.scene.objects if o not in before_all and o.type == "MESH"]:
            base = len(ev)
            ev += [o.matrix_world @ v.co for v in o.data.vertices]
            et += [tuple(base + i for i in p.vertices) for p in o.data.polygons]
    sbvh = BVHTree.FromPolygons(ev, et)
    excl = float(opt.get("skin_excl", 0.02))
    skin_ids = [i for i, p in enumerate(src_pts) if sbvh.find_nearest(p, excl)[0] is None]
    offs = []
    for p in src_def:
        loc, n, i, d = dbvh.find_nearest(p)
        offs.append((loc - p) if loc is not None and d < 0.06 else Vector())
    kd = KDTree(len(skin_ids))
    for i in skin_ids:
        kd.insert(src_def[i], i)
    kd.balance()
    print(f"XFER_SURFACE skin points {len(skin_ids)} of {len(src_def)} (the rest is under the armour)")
    out_pts = []
    for p in a_def:
        hits = kd.find_n(p, K)
        wsum, acc = 0.0, Vector()
        for co, i, d in hits:
            w = 1.0 / max(d, 0.003) ** 2
            acc += offs[i] * w
            wsum += w
        out_pts.append(p + (acc / wsum if wsum else Vector()))
    after = body_dist([p + o for p, o in zip(src_def, offs)])
    print(f"XFER_SURFACE source body after the surface step: median gap {np.median(after) * 1000:.1f} mm")
else:
    out_pts = a_def

# ---- 3. report on the armour
gap = body_dist(out_pts)
# body showing through, by rays along our body's normals: armour in front = covered, armour only behind = poking
abvh = BVHTree.FromPolygons(out_pts, [tuple(p.vertices) for p in armour.data.polygons])
dn = []
for o in d_body:
    rot = o.matrix_world.to_3x3()
    dn += [(rot @ v.normal).normalized() for v in o.data.vertices]
near, outside = 0, 0
for p, n in zip(dv, dn):
    front = abvh.ray_cast(p + n * 0.0005, n, 0.04)[0] is not None
    back = abvh.ray_cast(p - n * 0.0005, -n, 0.04)[0] is not None
    if front:
        near += 1
    elif back:
        near += 1
        outside += 1
print(f"XFER_REPORT armour off the body: median {np.median(gap) * 1000:.1f} mm, 90% {np.percentile(gap, 90) * 1000:.1f} mm, "
      f"max {gap.max() * 1000:.1f} mm; body vertices under the armour {near}, poking out {outside} "
      f"({100.0 * outside / max(near, 1):.1f}%)")

# ---- export a static mesh in our body's space
for i, v in enumerate(armour.data.vertices):
    v.co = armour.matrix_world.inverted() @ out_pts[i]
armour.data.update()
armour.vertex_groups.clear()
for m in list(armour.modifiers):
    armour.modifiers.remove(m)
mw = armour.matrix_world.copy()
armour.parent = None
armour.matrix_world = mw
for o in list(bpy.context.scene.objects):
    if o is not armour:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
armour.select_set(True)
bpy.context.view_layer.objects.active = armour
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", use_selection=True)
print("XFER_OK", out)
