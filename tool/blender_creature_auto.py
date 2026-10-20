"""Runs INSIDE Blender (background): prepare an auto-rigged creature (UniRig output) for blender_creature_finish.py.

    blender -b -P blender_creature_auto.py -- rigged.glb out.glb

1) orientation: the direction from the back-leg junction to the front-leg junction is "forward"; the model is turned
   about Z so it looks along -Y (glTF +Z, the Godot convention) and centred on X,
2) bone names from the skeleton's shape: chains ending near the ground are legs (front/back by position along the
   body, left/right of the creature), the remaining two chains are the head (on the front-leg side) and the tail;
   the path between the junctions is the spine,
3) a first guess of the mouth line for the jaw: small loose pieces in the snout are teeth; they split into an upper
   and a lower row by height and the line runs between them. Without teeth the line goes through the middle of the
   lower half of the snout.
Writes out.glb (turned, renamed) and prints AUTO_NAMES {json}, AUTO_JAW {json}, AUTO_OK.
"""
import json
import math
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
me = next(o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups)
for o in list(bpy.context.scene.objects):
    if o.type == "MESH" and not o.vertex_groups:
        bpy.data.objects.remove(o, do_unlink=True)

P = np.array([tuple(me.matrix_world @ v.co) for v in me.data.vertices])
H = float(P[:, 2].max() - P[:, 2].min())
mw = arm.matrix_world
bones = {b.name: b for b in arm.data.bones}
head = {n: mw @ b.head_local for n, b in bones.items()}
tail = {n: mw @ b.tail_local for n, b in bones.items()}
kids = {n: [c.name for c in b.children] for n, b in bones.items()}
root = next(n for n, b in bones.items() if b.parent is None)


def chain_up(leaf):
    """leaf -> up to (not including) the first ancestor that branches"""
    out = [leaf]
    cur = bones[leaf].parent
    while cur is not None and len(cur.children) == 1:
        out.append(cur.name)
        cur = cur.parent
    return out[::-1], (cur.name if cur is not None else None)


leaves = [n for n in bones if not kids[n]]
chains = []
for lf in leaves:
    ch, junction = chain_up(lf)
    chains.append(dict(bones=ch, junction=junction, end=tail[lf]))
# a finger-like split at a paw (two toes on one ankle) is part of that leg, not a new chain
legs = [c for c in chains if c["end"].z < 0.12 * H]
others = [c for c in chains if c["end"].z >= 0.12 * H]


def leg_root(c):
    """walk up from the leg's chain while the bones stay leg-like (below the body)"""
    return c["junction"]


juncs = {}
for c in legs:
    juncs.setdefault(c["junction"], []).append(c)
# merge toe splits: a junction whose own position is low belongs to a leg above it
for j in list(juncs):
    if j and head[j].z < 0.25 * H and bones[j].parent is not None:
        up, jj = chain_up(j)
        juncs.setdefault(jj, []).append(dict(bones=up + sum([c["bones"] for c in juncs[j]], []), junction=jj,
                                             end=juncs[j][0]["end"]))
        del juncs[j]
leg_juncs = sorted(juncs, key=lambda j: len(juncs[j]), reverse=True)[:2]
if len(leg_juncs) < 2:
    print("AUTO_FAIL legs not found:", {j: len(v) for j, v in juncs.items()})
    raise SystemExit
pos = {j: (head[j] if j else Vector()) for j in leg_juncs}
bm = bmesh.new()
bm.from_mesh(me.data)
bm.verts.ensure_lookup_table()
seen_v, islands = set(), []
for v in bm.verts:
    if v.index in seen_v:
        continue
    st, isl = [v], []
    seen_v.add(v.index)
    while st:
        x = st.pop()
        isl.append(x.index)
        for e in x.link_edges:
            y = e.other_vert(x)
            if y.index not in seen_v:
                seen_v.add(y.index)
                st.append(y)
    islands.append(isl)
bm.free()
small = [np.array(i) for i in islands if 3 <= len(i) <= 1500]
small_c = np.array([P[i].mean(0) for i in small]) if small else np.zeros((0, 3))
vg_names = {g.index: g.name for g in me.vertex_groups}
dom = {}
for v in me.data.vertices:
    if v.groups:
        g = max(v.groups, key=lambda g: g.weight)
        dom[vg_names[g.group]] = dom.get(vg_names[g.group], 0) + 1


def head_score(c):
    """the head carries the teeth, eyes and claws of the face (many small loose pieces) and a lot of mesh"""
    e = np.array(tuple(c["end"]))
    near = int((np.linalg.norm(small_c - e, axis=1) < 0.15 * H).sum()) if len(small_c) else 0
    mass = sum(dom.get(x, 0) for x in c["bones"])
    return near * 50 + mass


others.sort(key=head_score, reverse=True)
a, b = leg_juncs


def path_up(n):
    out = []
    while n is not None:
        out.append(n)
        n = bones[n].parent.name if bones[n].parent else None
    return out


def dist_along(c, j):
    return 0 if c["junction"] == j else (1 if c["junction"] in path_up(j) or j in path_up(c["junction"]) else 2)


# forward: toward the leg junction nearer to the highest non-leg chain's end (the head is usually the highest)
headc = others[0] if others else None
fwd_j = min(leg_juncs, key=lambda j: (head[j] - headc["end"]).length if headc else 0)
back_j = b if fwd_j == a else a
f = (head[fwd_j] - head[back_j])
f.z = 0
f.normalize()
# turn so that f -> -Y
ang = math.atan2(f.x, -f.y)  # angle of f measured from -Y
R = Matrix.Rotation(ang, 4, "Z")
cx_before = None
for o in (arm,):
    o.matrix_world = R @ o.matrix_world
bpy.context.view_layer.update()
P = np.array([tuple(me.matrix_world @ v.co) for v in me.data.vertices])
shift = Vector((-(P[:, 0].min() + P[:, 0].max()) / 2, -(P[:, 1].min() + P[:, 1].max()) / 2, 0))
arm.matrix_world = Matrix.Translation(shift) @ arm.matrix_world
bpy.context.view_layer.update()
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True)
me.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
mw = arm.matrix_world
head = {n: mw @ bb.head_local for n, bb in bones.items()}
tail = {n: mw @ bb.tail_local for n, bb in bones.items()}
P = np.array([tuple(me.matrix_world @ v.co) for v in me.data.vertices])
print(f"AUTO_TURN degrees={math.degrees(ang):.1f}")

# ---- names
names = {}
spine = []
n = fwd_j
stop = set(path_up(back_j))
while n is not None and n not in stop:
    spine.append(n)
    n = bones[n].parent.name if bones[n].parent else None
spine = spine[::-1]  # from just after the back junction up to the front junction
names[root] = "hips"
back_path = [x for x in path_up(back_j)[::-1] if x != root]
for i, x in enumerate(back_path + spine[:-1] if spine else back_path):
    names.setdefault(x, f"spine_{i + 1:02d}")
if spine:
    names[spine[-1]] = "chest"
for j, side_key in ((fwd_j, "F"), (back_j, "B")):
    for c in juncs[j]:
        ch = c["bones"]
        side = "L" if head[ch[0]].x > 0 else "R"  # the creature's left is +X when it looks along -Y
        for i, x in enumerate(ch):
            names[x] = f"leg_{side_key}{side}_{i + 1}"
for c in others:
    is_head = c is headc
    ch = c["bones"]
    if is_head:
        k = len(ch)
        for i, x in enumerate(ch):
            names[x] = ("snout" if i == k - 1 and k >= 2 else "head" if i == k - 2 else f"neck_{i + 1:02d}")
        if k == 1:
            names[ch[0]] = "head"
    else:
        for i, x in enumerate(ch):
            names[x] = f"tail_{i + 1:02d}"
for x in bones:  # anything left keeps a readable, unique name
    names.setdefault(x, "extra_" + x)
seen = {}
for k in list(names):
    v = names[k]
    if v in seen.values():
        names[k] = v + "_b"
    seen[k] = names[k]
head_bone = next((k for k, v in names.items() if v == "head"), None)

# ---- mouth guess (creature looks along -Y now)
cx = 0.0
tip_y = float(P[:, 1].min())
hb_y = head[head_bone].y if head_bone else tip_y + 0.2 * H
L = max(0.05 * H, hb_y - tip_y)
snout = (P[:, 1] < tip_y + 1.0 * L) & (np.abs(P[:, 0] - cx) < 0.6 * L)

# the mouth sits at about a third of the snout's height, counted from the bottom of the lower jaw; measured on the
# front part of the snout, in the middle (the cheeks and fangs bulge out at the sides)
part = (P[:, 1] > tip_y + 0.1 * L) & (P[:, 1] < tip_y + 0.4 * L) & (np.abs(P[:, 0] - cx) < 0.3 * L)
if part.sum() < 20:
    part = snout
z_lo, z_hi = float(np.percentile(P[part][:, 2], 2)), float(np.percentile(P[part][:, 2], 98))
frac = 0.36
line = z_lo + frac * (z_hi - z_lo)
method = f"{int(frac * 100)} % of the snout height ({z_lo:.3f}..{z_hi:.3f})"
front = (tip_y + 0.2 * L, line)
corner = (tip_y + 0.6 * L, line + 0.02 * L)
hinge = (tip_y + 0.95 * L, line + 0.05 * L)
jaw = dict(jaw_front=front, jaw_corner=corner, hinge=hinge, cx=cx, half_width=round(0.7 * L, 4),
           floor=round(z_lo - 0.02 * H, 4), fade=round(0.3 * L, 4), jaw_parent="head" if head_bone else root,
           method=method, snout_length=round(L, 4))

bpy.ops.object.select_all(action="SELECT")
for o in list(bpy.context.scene.objects):
    if o.type not in ("MESH", "ARMATURE"):
        o.select_set(False)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False)
print("AUTO_NAMES " + json.dumps(names))
print("AUTO_JAW " + json.dumps(jaw))
print("AUTO_OK", dst)
