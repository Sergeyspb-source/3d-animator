"""Runs INSIDE Blender (background): prepare an auto-rigged creature (UniRig output) for blender_creature_finish.py.

    blender -b -P blender_creature_auto.py -- rigged.glb out.glb

1) orientation: the direction from the back-leg junction to the front-leg junction is "forward"; the model is turned
   about Z so it looks along -Y (glTF +Z, the Godot convention) and centred on X,
2) bone names from the skeleton's shape: chains ending near the ground are legs, any number (the body's line from
   their roots: two a side - leg_FL/FR/BL/BR as ever, one a side - hind legs leg_BL/BR (a bird), more - leg_L1.. from
   the front (a spider)); the head is the heaviest chain on the middle line (forward toward it), chains off the
   middle line wings (wing_L_1.. the main way, wingx_ the rest), the middle chain furthest back the tail; the root
   to the head chain the spine (its last bone the chest). No legs (a snake, a fish): the body is the longest way,
   spine_01 by the head back to the tail's end,
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
blen = lambda c: sum((tail[x] - head[x]).length for x in c["bones"])  # noqa: E731


def leg_like(c):
    """a leg comes down to the ground from the body: its end low, below its junction by a good part of how far out it
    goes (a dragon's wing at rest droops to the ground three heights out; a snake lies on it), and it hangs off a bone"""
    if c["junction"] is None or c["end"].z >= 0.12 * H:
        return False
    j = head[c["junction"]]
    drop, out = j.z - c["end"].z, math.hypot(c["end"].x - j.x, c["end"].y - j.y)
    return drop > 0.06 * H


def forks(c):
    """how many branching bones lie between a chain and the root: a leg hangs off the body (as many as the spine's),
    a wing's finger or feather off the wing, several forks further out (a dragon's wing droops to the ground at rest:
    its tips are not legs)"""
    n, cur = 0, c["junction"]
    while cur is not None:
        if len(bones[cur].children) > 1:
            n += 1
        cur = bones[cur].parent.name if bones[cur].parent else None
    return n


def paired(c, pool):
    """a leg has its mirror: another as long, ending as low, as far from the skeleton's root (a snake's raised head
    reaching the ground is not a leg)"""
    r0, d0, l0 = head[root], (c["end"] - head[root]).length, blen(c)
    return any(o is not c and abs(blen(o) - l0) < 0.3 * l0 and abs(o["end"].z - c["end"].z) < 0.1 * H
               and abs((o["end"] - r0).length - d0) < 0.2 * max(d0, 1e-6) and (o["end"] - c["end"]).length > 0.05 * H for o in pool)


legs0 = [c for c in chains if leg_like(c)]
if legs0:
    f0 = min(forks(c) for c in legs0)
    legs0 = [c for c in legs0 if forks(c) <= f0 + 2]
legs = [c for c in legs0 if paired(c, legs0)]
others = [c for c in chains if c not in legs and c["junction"] is not None]
juncs = {}
for c in legs:
    juncs.setdefault(c["junction"], []).append(c)
# merge toe splits: short chains split off a low junction belong to the leg above it (a spider's four legs off one
# low bone are four legs, not toes)
for j in list(juncs):
    if j and head[j].z < 0.25 * H and bones[j].parent is not None and max(blen(c) for c in juncs[j]) < 0.15 * H:
        up, jj = chain_up(j)
        juncs.setdefault(jj, []).append(dict(bones=up + sum([c["bones"] for c in juncs[j]], []), junction=jj,
                                             end=juncs[j][0]["end"]))
        del juncs[j]
legs = [c for j in juncs for c in juncs[j]]
import os
if os.environ.get("SF3D_AUTO_DEBUG"):
    nv = max(1, len(me.data.vertices))
    _vg = {g.index: g.name for g in me.vertex_groups}
    _dom = {}
    for v in me.data.vertices:
        if v.groups:
            g = max(v.groups, key=lambda g: g.weight)
            _dom[_vg[g.group]] = _dom.get(_vg[g.group], 0) + 1
    for c in chains:
        print("DBG mass %.3f" % (sum(_dom.get(x, 0) for x in c["bones"]) / nv), "per len %.3f" % (sum(_dom.get(x, 0) for x in c["bones"]) / nv / max(blen(c) / H, 1e-6)), end=" ")
        print("DBG chain", c["bones"][0], "->", c["bones"][-1], "junc", c["junction"], "jz %.2f" % ((head[c["junction"]].z if c["junction"] else 0) / H),
              "end z %.2f x %.2f y %.2f" % (c["end"].z / H, c["end"].x / H, c["end"].y / H), "len %.2f" % (blen(c) / H), "n", len(c["bones"]))
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


def path_up(n):
    out = []
    while n is not None:
        out.append(n)
        n = bones[n].parent.name if bones[n].parent else None
    return out


# ---- the body's line from the legs (any number), else from the skeleton's longest way (a snake, a fish): its axis
# and the line across it; the head among the chains on the middle line only (a dragon's wing is heavier than its
# head: by the old way it was taken for the head), forward toward it
lvl = lambda v: Vector((v.x, v.y, 0.0))  # noqa: E731
roots = [lvl(c["end"]) for c in legs]   # (their paws: a leg's first bone may be an anchor on the middle line)
if len(roots) >= 3:
    R_ = np.array([tuple(r)[:2] for r in roots])
    m2 = R_.mean(0)
    _, _, vt = np.linalg.svd(R_ - m2)
    axis = Vector((vt[0][0], vt[0][1], 0.0))
    if np.ptp((R_ - m2) @ vt[0]) < 0.35 * np.ptp((R_ - m2) @ vt[1]):   # (legs wider than long: the axis is the other)
        axis = Vector((vt[1][0], vt[1][1], 0.0))
    mid = Vector((m2[0], m2[1], 0.0))
elif len(roots) == 2:
    across0 = (roots[0] - roots[1]).normalized()
    axis = Vector((-across0.y, across0.x, 0.0))
    mid = (roots[0] + roots[1]) / 2
else:   # no legs: the two leaf ends furthest apart
    ends = [lvl(c["end"]) for c in chains]
    i0, i1 = max(((i, j) for i in range(len(ends)) for j in range(i + 1, len(ends))), key=lambda ij: (ends[ij[0]] - ends[ij[1]]).length, default=(0, 0))
    axis = (ends[i0] - ends[i1]).normalized() if len(ends) > 1 else Vector((0, 1, 0))
    mid = (ends[i0] + ends[i1]) / 2 if len(ends) > 1 else lvl(head[root])
across = Vector((-axis.y, axis.x, 0.0))
span = max([abs((lvl(c["end"]) - mid).dot(axis)) for c in chains] + [1e-6])
central = [c for c in others if abs((lvl(c["end"]) - mid).dot(across)) < 0.3 * span] or others
central.sort(key=head_score, reverse=True)
headc = central[0] if central else None
if headc is None:
    print("AUTO_FAIL no head chain")
    raise SystemExit
f = axis if (lvl(headc["end"]) - mid).dot(axis) >= 0 else -axis
jl = [j for j in juncs if j and len(juncs[j]) == 2]
if len(legs) == 4 and len(jl) == 2:   # a quadruped as ever: from the hind legs' junction to the front's (the paws' line
    fj = min(jl, key=lambda j: (head[j] - headc["end"]).length)   # tilted the werewolf 14 deg: its paws stand askew)
    bj = jl[1] if fj == jl[0] else jl[0]
    if (lvl(head[fj]) - lvl(head[bj])).length > 1e-6:
        f = (lvl(head[fj]) - lvl(head[bj])).normalized()
serpent = not legs
# turn so that f -> -Y
ang = math.atan2(f.x, -f.y)  # angle of f measured from -Y
R = Matrix.Rotation(ang, 4, "Z")
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
for c in chains:
    c["end"] = tail[c["bones"][-1]]
print(f"AUTO_TURN degrees={math.degrees(ang):.1f} legs={len(legs)} serpent={serpent}")

# ---- names
names = {}
hj = headc["junction"]
body_up = [x for x in (path_up(hj) if hj else [])][::-1]   # the root .. the head chain's junction
if serpent:
    # a snake / a fish: from the head back to the tail's end, spine_01 by the head (the clips' body the same way)
    tailc = max((c for c in others if c is not headc), key=lambda c: (c["end"] - head[headc["bones"][0]]).length, default=None)
    way_t = (path_up(tailc["bones"][-1])[::-1] if tailc else [root])
    k = 0
    for x in body_up[::-1]:
        k += 1
        names.setdefault(x, f"spine_{k:02d}")
    for x in way_t:
        if x not in names:
            k += 1
            names[x] = f"spine_{k:02d}"
else:
    names[root] = "hips"
    for i, x in enumerate([x for x in body_up if x != root]):
        names.setdefault(x, f"spine_{i + 1:02d}")
    if body_up and body_up[-1] != root:
        names[body_up[-1]] = "chest"
    # the legs: each side's from the front; two a side - front / back (as ever), one - a hind leg (a bird), more - by
    # number (leg_L1_.. a spider's front pair)
    sides = {"L": [], "R": []}
    for c in legs:
        sides["L" if c["end"].x > 0 else "R"].append(c)   # (the creature's left is +X looking along -Y; by the paw)
    for side, lst in sides.items():
        lst.sort(key=lambda c: (min(head[x].y for x in c["bones"]) if lst and len(lst) > 1 else 0))
        n = len(lst)
        for i, c in enumerate(lst):
            key = ("F" if i == 0 else "B") + side if n == 2 else "B" + side if n == 1 else f"{side}{i + 1}"
            for k, x in enumerate(c["bones"]):
                names[x] = f"leg_{key}_{k + 1}"
ch = headc["bones"]
kk = len(ch)
for i, x in enumerate(ch):
    names[x] = ("snout" if i == kk - 1 and kk >= 2 else "head" if i == kk - 2 else f"neck_{i + 1:02d}")
if kk == 1:
    names[ch[0]] = "head"
# the wings: chains off the middle line, each side's furthest out its main way from the body (wing_L_1 ..), the rest
# of that side's lateral bones its feathers / fingers (wingx_)
lateral = [c for c in others if c is not headc and abs(c["end"].x) >= 0.3 * span]
if not (any(c["end"].x > 0 for c in lateral) and any(c["end"].x < 0 for c in lateral)):
    lateral = []   # (wings come in pairs: one lateral chain is something else)
for side in ("L", "R"):
    lst = [c for c in lateral if (c["end"].x > 0) == (side == "L")]
    if not lst:
        continue
    main = max(lst, key=lambda c: abs(c["end"].x) + 0.3 * c["end"].z)
    way = []
    for x in path_up(main["bones"][-1]):
        if x in names:
            break
        way.append(x)
    for i, x in enumerate(way[::-1]):
        names[x] = f"wing_{side}_{i + 1}"
    k = 0
    for c in lst:
        if c is main:
            continue
        k += 1
        for i, x in enumerate(c["bones"]):
            names.setdefault(x, f"wingx_{side}_{k}_{i + 1}")
# a biped's arms (a kaiju): with one leg a side and no wing there, that side's longest way from the body out to a
# hand off the middle line (fingers fork it: measured from the body, not from the last fork) - its front leg
if not serpent and all(len(v) == 1 for v in sides.values()):
    for side in ("L", "R"):
        if any(v.startswith(f"wing_{side}_") for v in names.values()):
            continue
        best = None
        for c in others:
            if c is headc or (c["end"].x > 0) != (side == "L") or abs(c["end"].x) < 0.05 * H:
                continue
            way = []
            for x in path_up(c["bones"][-1]):
                if x in names:
                    break
                way.append(x)
            ln = sum((tail[x] - head[x]).length for x in way)
            if ln > 0.25 * H and (best is None or ln > best[0]):
                best = (ln, way[::-1])
        if best:
            for i, x in enumerate(best[1]):
                names[x] = f"leg_F{side}_{i + 1}"
# the tail: the middle chain furthest back
rest_c = [c for c in others if c is not headc and c not in lateral and not any(x in names for x in c["bones"])]
tailc2 = max(rest_c, key=lambda c: c["end"].y, default=None)
if tailc2 is not None and not serpent:
    for i, x in enumerate(tailc2["bones"]):
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
