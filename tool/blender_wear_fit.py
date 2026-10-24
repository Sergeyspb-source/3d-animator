"""Runs INSIDE Blender (background): put a piece of armour on a landmark-rigged character as the editor placed it.

    blender -b -P blender_wear_fit.py -- job.json

job.json: {"character": rigged.glb, "armour": piece.glb, "out": out.glb, "item": name,
           "placements": [{"side": "L", "matrix": [16 floats, column-major, glTF space],
                           "limb": {"a": [x, y, z], "b": [x, y, z]} (the limb's two joints, glTF space),
                           "bone": name of the limb's bone}, ...],
           "offset": gap to the skin (model units), "conform": 0..1, "rigidity": 0..1, "deforms": [...],
           "wall": {"k": wall thickness factor, "mid", "axis": the piece's tube axis in its own space},
           "rings": [{"c", "n", "r", "s", "b"}: openings drawn in, piece space],
           "report": path.json}

The editor (landmark_editor.html, mode «Броня») already placed each copy: along the limb between its joints, sized
to the limb's thickness, turned and nudged by the user. Here every copy gets that matrix (a mirrored copy has a
negative determinant: its faces are flipped back), then:
- fits the limb's shape: around the limb axis, in cells of (position along the limb, angle), the piece is scaled
  away from the axis so its inner wall clears the skin by the gap («conform» > 0 also draws loose cells in towards
  it). One smooth factor per cell moves the inner and the outer wall together, so the piece keeps its shape and
  wall thickness, instead of single vertices being snapped onto the skin;
- takes its skin weights from the nearest point of the body, only from the limb's own bone, its parent and its
  children (a bracer must not follow the fingers or the torso), smooths them over the piece and, by «rigidity»,
  draws them towards the limb's own bone (1 = the piece moves as one with the bone);
- is exported with the character's skeleton only: the game puts it on the same skeleton by bone names.
"""
import json
import re
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector, kdtree
from mathutils.bvhtree import BVHTree
from mathutils.geometry import barycentric_transform

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
report = {}


def fail(msg):
    print("WEAR_FAIL " + msg, flush=True)
    sys.exit(1)


PARTS = ("Eye_", "EyeSocket", "Teeth_", "Gum_", "Tongue", "MouthCavity", "Icosphere")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["character"])
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    fail("у персонажа нет скелета: сначала постройте скелет по разметке")
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
body = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups and not o.name.startswith(PARTS)]
if not body:
    fail("у персонажа нет кожи с весами")
character_objs = set(bpy.data.objects)

# the armour as one plain mesh in world space (a skinned source loses its old skin: the vertices are its rest pose)
bpy.ops.import_scene.gltf(filepath=job["armour"])
new = [o for o in bpy.data.objects if o not in character_objs]
src_meshes = [o for o in new if o.type == "MESH" and not o.name.startswith("Icosphere")
              and not re.search(r"-(conv)?colonly$|-col$", o.name)]   # a collision hull of the export is no armour
if not src_meshes:
    fail("в файле вещи нет сетки")
for o in src_meshes:
    for m in list(o.modifiers):
        o.modifiers.remove(m)
    mw = o.matrix_world.copy()
    o.parent = None
    o.data = o.data.copy()
    o.data.transform(mw)
    o.matrix_world = Matrix()
    o.vertex_groups.clear()
    if o.data.shape_keys:
        o.shape_key_clear()
new_names = [o.name for o in new]   # the join removes objects: keep names, not references
bpy.ops.object.select_all(action="DESELECT")
for o in src_meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = src_meshes[0]
if len(src_meshes) > 1:
    bpy.ops.object.join()
src = bpy.context.view_layer.objects.active
for n in new_names:
    o = bpy.data.objects.get(n)
    if o is not None and o is not src:
        bpy.data.objects.remove(o, do_unlink=True)

# glTF (Y up, +Z forward) -> Blender (Z up, -Y forward): x' = x, y' = -z, z' = y
CONV = Matrix(((1, 0, 0, 0), (0, 0, -1, 0), (0, 1, 0, 0), (0, 0, 0, 1)))

# «Толщина стенки» (piece space, glTF; the same as the editor's wallGrid / wallApply): about the piece's own tube
# axis, in cells (12 along x 24 around), the inner wall is the nearest point to the axis; each vertex's depth above
# it is scaled by k, so the inner wall stays where the fit put it and only the outer surface moves
WALL_T, WALL_A = 12, 24


def wall_thickness(me, wall):
    k = float(wall.get("k", 1.0))
    a, m = Vector(wall["axis"]).normalized(), Vector(wall["mid"])
    p1 = (Vector((1, 0, 0)) if abs(a.x) < .9 else Vector((0, 0, 1))).cross(a).normalized()
    p2 = a.cross(p1)
    back = CONV.inverted()
    cyl = []
    for v in me.vertices:
        d = (back @ v.co) - m
        t = d.dot(a)
        rad = d - a * t
        cyl.append((t, math.atan2(rad.dot(p2), rad.dot(p1)), rad))
    t0 = min(c[0] for c in cyl)
    t1 = max(c[0] for c in cyl)
    t1 += 1e-9 * (1 + abs(t1))
    g = [None] * (WALL_T * WALL_A)
    for t, ang, rad in cyl:
        i = min(WALL_T - 1, int((t - t0) / (t1 - t0) * WALL_T))
        j = min(WALL_A - 1, int((ang + math.pi) / (2 * math.pi) * WALL_A))
        if g[i * WALL_A + j] is None or rad.length < g[i * WALL_A + j]:
            g[i * WALL_A + j] = rad.length
    for _ in range(WALL_T + WALL_A):   # empty cells: the mean of filled neighbours
        if None not in g:
            break
        upd = []
        for i in range(WALL_T):
            for j in range(WALL_A):
                if g[i * WALL_A + j] is not None:
                    continue
                nb = [g[ii * WALL_A + jj % WALL_A] for ii, jj in ((i - 1, j), (i + 1, j), (i, j - 1), (i, j + 1)) if 0 <= ii < WALL_T]
                nb = [x for x in nb if x is not None]
                if nb:
                    upd.append((i * WALL_A + j, sum(nb) / len(nb)))
        if not upd:
            break
        for idx, x in upd:
            g[idx] = x
    g = [0.0 if x is None else x for x in g]
    for v, (t, ang, rad) in zip(me.vertices, cyl):
        r = rad.length
        if r < 1e-12:
            continue
        x = min(WALL_T - 1.0, max(0.0, (t - t0) / (t1 - t0) * WALL_T - .5))
        i0 = int(x); i1 = min(WALL_T - 1, i0 + 1); fx = x - i0
        y = (ang + math.pi) / (2 * math.pi) * WALL_A - .5
        jf = math.floor(y); fy = y - jf; j0 = jf % WALL_A; j1 = (j0 + 1) % WALL_A
        rin = ((g[i0 * WALL_A + j0] * (1 - fy) + g[i0 * WALL_A + j1] * fy) * (1 - fx)
               + (g[i1 * WALL_A + j0] * (1 - fy) + g[i1 * WALL_A + j1] * fy) * fx)
        v.co = CONV @ ((back @ v.co) + rad * ((rin + (r - rin) * k) / r - 1))


_orig = [v.co.copy() for v in src.data.vertices]   # the handles' falloff is measured on the piece as it came
if job.get("wall") and abs(float(job["wall"].get("k", 1.0)) - 1) > 1e-3:
    wall_thickness(src.data, job["wall"])
report["wall"] = float((job.get("wall") or {}).get("k", 1.0))
# openings marked in the editor («Отверстие»): everything near the circle drawn towards its axis by s of its radius,
# a smooth falloff over the band b; measured on the piece as it came, as the editor's ringApply
for g in job.get("rings", []):
    c, n = CONV @ Vector(g["c"]), (CONV.to_3x3() @ Vector(g["n"])).normalized()
    r, s, b = float(g["r"]), float(g["s"]), float(g["b"])
    for v, o in zip(src.data.vertices, _orig):
        q = o - c
        h = q.dot(n)
        rad = q - n * h
        rho = rad.length
        if rho < 1e-12:
            continue
        d = math.hypot(h, rho - r)
        if d >= b:
            continue
        t = d / b
        v.co += rad * (-s * r * (1 - t * t * (3 - 2 * t)) / rho)
report["rings"] = len(job.get("rings", []))

# surface points pulled in the editor (piece space, glTF): the same smooth falloff as the editor's preview
for df in job.get("deforms", []):
    p, d, r = CONV @ Vector(df["p"]), CONV.to_3x3() @ Vector(df["d"]), float(df["r"])
    for v, o in zip(src.data.vertices, _orig):
        x = (o - p).length / r
        if x < 1:
            v.co += d * (1 - x * x * (3 - 2 * x))
report["deforms"] = len(job.get("deforms", []))

# the body at rest, for the fit and the weights
verts, tris, owner = [], [], []
for o in body:
    o.data.calc_loop_triangles()
    base = len(verts)
    verts += [o.matrix_world @ v.co for v in o.data.vertices]
    for t in o.data.loop_triangles:
        tris.append(tuple(base + i for i in t.vertices))
        owner.append((o, tuple(t.vertices)))
bvh = BVHTree.FromPolygons(verts, tris)
offset = float(job.get("offset", 0.0))
conform = min(1.0, max(0.0, float(job.get("conform", 0.0))))
rigidity = min(1.0, max(0.0, float(job.get("rigidity", 0.0))))

# ---------------------------------------------------------------- fitting the limb's shape
NT, NA = 16, 24   # cells along the limb and around it


class Limb:
    """Cylinder coordinates about the limb axis: t along it (0 at joint a, 1 at joint b), angle, distance."""

    def __init__(self, a, b):
        self.a, self.len = a, (b - a).length
        self.u = (b - a) / self.len
        self.p1 = (Vector((1, 0, 0)) if abs(self.u.x) < .9 else Vector((0, 0, 1))).cross(self.u).normalized()
        self.p2 = self.u.cross(self.p1)

    def cyl(self, co):
        d = co - self.a
        t = d.dot(self.u)
        rad = d - self.u * t
        return t / self.len, math.atan2(rad.dot(self.p2), rad.dot(self.p1)), rad

    def axis(self, t):
        return self.a + self.u * (t * self.len)

    def out(self, ang):
        return self.p1 * math.cos(ang) + self.p2 * math.sin(ang)


def fill(grid):
    """Empty cells (None) take the mean of their filled neighbours, repeatedly; the angle wraps around."""
    for _ in range(NT + NA):
        holes = [(i, j) for i in range(NT) for j in range(NA) if grid[i][j] is None]
        if not holes:
            break
        upd = {}
        for i, j in holes:
            nb = [grid[ii][(j + dj) % NA] for ii, dj in ((i - 1, 0), (i + 1, 0), (i, -1), (i, 1)) if 0 <= ii < NT]
            nb = [x for x in nb if x is not None]
            if nb:
                upd[(i, j)] = sum(nb) / len(nb)
        if not upd:
            break
        for (i, j), x in upd.items():
            grid[i][j] = x
    return [[1.0 if x is None else x for x in row] for row in grid]


def soften(grid, keep_max=True):
    """Max over the 3x3 neighbourhood (so no cell drops below what it needs), then a 1-2-1 blur, twice."""
    for _ in range(2):
        if keep_max:
            grid = [[max(grid[ii][(j + dj) % NA] for ii in (i - 1, i, i + 1) if 0 <= ii < NT for dj in (-1, 0, 1))
                     for j in range(NA)] for i in range(NT)]
        grid = [[sum(w * grid[min(NT - 1, max(0, i + di))][(j + dj) % NA]
                     for di, dj, w in ((0, 0, 4), (-1, 0, 2), (1, 0, 2), (0, -1, 2), (0, 1, 2),
                                       (-1, -1, 1), (-1, 1, 1), (1, -1, 1), (1, 1, 1))) / 16
                 for j in range(NA)] for i in range(NT)]
    return grid


def scale_radially(me, limb, t0, t1, grid):
    """Every vertex moves away from (or towards) the limb axis by the factor of its cell, bilinear between cells."""
    for v in me.vertices:
        t, ang, rad = limb.cyl(v.co)
        x = min(NT - 1.0, max(0.0, (t - t0) / (t1 - t0) * NT - .5))
        y = (ang + math.pi) / (2 * math.pi) * NA - .5
        i0, j0 = int(x), math.floor(y)
        fx, fy = x - i0, y - j0
        i1, j0, j1 = min(NT - 1, i0 + 1), j0 % NA, (j0 + 1) % NA
        f = ((grid[i0][j0] * (1 - fy) + grid[i0][j1] * fy) * (1 - fx) + (grid[i1][j0] * (1 - fy) + grid[i1][j1] * fy) * fx)
        v.co += rad * (f - 1)


def cell(limb, t0, t1, co):
    t, ang, rad = limb.cyl(co)
    i = min(NT - 1, max(0, int((t - t0) / (t1 - t0) * NT)))
    j = min(NA - 1, int((ang + math.pi) / (2 * math.pi) * NA))
    return i, j, rad.length


def centred(limb):
    """The limb's real middle line: the joints of a markup sit off the middle of the flesh (often by a fifth of the
    limb's radius), so the centres of the skin around the bone are found slice by slice and a line is fitted to them.
    Fitting about the joint line instead leaves air on one side and presses the piece onto the other."""
    centres = []
    for i in range(9):
        t = .1 + .8 * i / 8
        o = limb.axis(t)
        hits = [h[0] for j in range(24) for h in [bvh.ray_cast(o, limb.out(j / 24 * 2 * math.pi), limb.len)] if h[0] is not None]
        if len(hits) >= 18:
            centres.append(sum(hits, Vector()) / len(hits))
    if len(centres) < 3:
        return limb
    c = sum(centres, Vector()) / len(centres)
    d = limb.u.copy()
    for _ in range(20):   # the main direction of the centres (power iteration on their spread), started at the bone
        w = sum(((p - c) * (p - c).dot(d) for p in centres), Vector())
        if w.length < 1e-12:
            break
        d = w.normalized()
    if d.dot(limb.u) < 0:
        d = -d
    if d.dot(limb.u) < .9:   # a bent or stubby limb: keep the bone's direction, move only to the middle
        d = limb.u
    a, b = limb.a, limb.a + limb.u * limb.len
    return Limb(c + d * (a - c).dot(d), c + d * (b - c).dot(d))


def fit_limb(me, limb):
    """Scale the piece about the limb's middle line, cell by cell, so its inner wall clears the skin by the offset."""
    shift = (centred(limb).axis(.5) - limb.axis(.5)).length
    limb = centred(limb)
    ts = [limb.cyl(v.co)[0] for v in me.vertices]
    t0, t1 = min(ts), max(ts)
    if t1 - t0 < 1e-6:
        return {}
    t1 += 1e-6
    inner = [[None] * NA for _ in range(NT)]
    for v in me.vertices:
        i, j, r = cell(limb, t0, t1, v.co)
        if r > 1e-9 and (inner[i][j] is None or r < inner[i][j]):
            inner[i][j] = r
    skin = [[None] * NA for _ in range(NT)]
    for i in range(NT):
        o = limb.axis(t0 + (i + .5) / NT * (t1 - t0))
        for j in range(NA):
            hit = bvh.ray_cast(o, limb.out(-math.pi + (j + .5) / NA * 2 * math.pi), limb.len)
            if hit[0] is not None:
                skin[i][j] = hit[3]
    # a ray that ran far is not this limb's skin (from the foot up inside the shin, along the arm into the torso):
    # such cells are unknown and take their neighbours' factor, or the piece would be stretched into a spike
    near = sorted(x for row in skin for x in row if x is not None)
    if near:
        far = 2.5 * near[len(near) // 2]
        skin = [[x if x is not None and x <= far else None for x in row] for row in skin]
    need, want = [[None] * NA for _ in range(NT)], [[None] * NA for _ in range(NT)]
    for i in range(NT):
        for j in range(NA):
            if inner[i][j] and skin[i][j]:
                f = (skin[i][j] + offset) / inner[i][j]
                need[i][j] = max(1.0, f)                                # never inside the skin
                want[i][j] = f if f > 1 else 1 + conform * (f - 1)      # loose cells drawn in by «conform»
    # a row with no skin around it (above the top of a head under a helmet's dome, past the end of a limb) stays as
    # it is: filled from its neighbours it would take their widening and blow the dome up into a brim
    for i in range(NT):
        if all(x is None for x in skin[i]):
            need[i] = [1.0] * NA
            want[i] = [1.0] * NA
    # the cells that must widen keep their need through the smoothing (max first); the rest follow «conform» only,
    # so a widening near the elbow does not spread over the whole piece
    need = soften([[min(1.8, n) for n in row] for row in fill(need)])
    want = soften([[min(1.8, max(.6, w)) for w in row] for row in fill(want)], keep_max=False)
    grid = [[max(w, n) for w, n in zip(rw, rn)] for rw, rn in zip(want, need)]
    scale_radially(me, limb, t0, t1, grid)
    # what is still too close (the skin varies inside a cell, or the limb is no tube there, as at the ankle under
    # a shoe): pushed out along the skin's normal, not away from the axis
    left = push_out(me, .6 * near[len(near) // 2] if near else .1 * limb.len)   # about the limb's radius
    return {"close_to_skin": left, "axis_shift": round(shift / max(limb.len, 1e-9), 3)}


def push_out(me, radius):
    """Stage 2: what is under the skin or nearer than the offset moves out along the normal of the nearest skin
    point. The push of every vertex spreads over its neighbours within the radius (on a sample of at most ~3000
    points, with a smooth falloff), so the inner and the outer wall move together and the piece keeps its shape
    instead of single vertices being snapped onto the skin. A few rounds; returns how many vertices are still too
    close."""
    n = len(me.vertices)
    sample = list(range(0, n, max(1, n // 3000)))
    kd = kdtree.KDTree(len(sample))
    for k, vi in enumerate(sample):
        kd.insert(me.vertices[vi].co, k)
    kd.balance()
    left = 0
    for _ in range(4):
        need = {}
        for v in me.vertices:
            loc, nrm, idx, dist = bvh.find_nearest(v.co)
            if loc is None:
                continue
            gap = (v.co - loc).dot(nrm)
            if gap < offset:
                need[v.index] = nrm * (offset - gap)
        left = sum(1 for d in need.values() if d.length > .5 * offset)
        if not need:
            break
        # each sample takes the strongest push near it (scaled by the falloff), then every vertex blends the pushes
        # of its four nearest samples, plus whatever it still needs itself along its own normal
        kd_need = kdtree.KDTree(len(need))
        for k, vi in enumerate(need):
            kd_need.insert(me.vertices[vi].co, vi)
        kd_need.balance()
        at = []
        for vi in sample:
            best = Vector()
            for co, k, d in kd_need.find_range(me.vertices[vi].co, radius):
                w = 1 - (d / radius) ** 2
                if need[k].length * w > best.length:
                    best = need[k] * w
            at.append(best)
        for v in me.vertices:
            acc, tot = Vector(), 0.0
            for co, k, d in kd.find_n(v.co, 4):
                w = 1 / (d + 1e-6 * radius)
                acc += at[k] * w
                tot += w
            move = acc / tot if tot else Vector()
            own = need.get(v.index)
            if own is not None:
                u = own.normalized()
                move += u * max(0.0, own.length - move.dot(u))
            v.co += move
        kd = kdtree.KDTree(len(sample))   # the sample moved with the piece
        for k, vi in enumerate(sample):
            kd.insert(me.vertices[vi].co, k)
        kd.balance()
    return left


def bone_family(name, up=True):
    """The limb's own bone, its parent and everything below it: the bones a piece on this limb may follow."""
    b = arm.data.bones.get(name)
    if b is None:
        return None
    fam = {b.name} | {c.name for c in b.children_recursive}
    if b.parent and up:   # up=False: a boot follows the shin and the foot, not the thigh above the knee
        fam.add(b.parent.name)
    # a piece on the body (a cuirass on the spine, a helmet) does not follow the arms or the legs below it: those are
    # limbs of their own; a piece on a limb keeps its limb's bones
    LIMB = ("Arm", "Hand", "UpLeg", "Leg", "Foot", "Toe")
    if not any(w in b.name for w in LIMB):
        fam = {n for n in fam if not any(w in n for w in LIMB)}
    return fam


def skin_weights(o, me, main, radius, allowed=None, up=True):
    """Nearest body point (barycentric, by vertex group), only the limb's bones (or the given ones: the bones a piece
    placed by the skeleton was weighted to), smoothed over the piece within the radius, then drawn towards the main
    bone by the rigidity. Returns the bone names used."""
    fam = bone_family(main, up) if main else (set(allowed) & {b.name for b in arm.data.bones}) or None if allowed else None
    raw = []
    for v in me.vertices:
        acc = {}
        loc, nrm, idx, dist = bvh.find_nearest(v.co)
        if loc is not None:
            bo, tv = owner[idx]
            a, b, c = (bo.matrix_world @ bo.data.vertices[i].co for i in tv)
            bc = barycentric_transform(loc, a, b, c, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
            for w, vi in zip(bc, tv):
                for g in bo.data.vertices[vi].groups:
                    name = bo.vertex_groups[g.group].name
                    if fam is None or name in fam:
                        acc[name] = acc.get(name, 0.0) + max(0.0, w) * g.weight
        tot = sum(acc.values())
        raw.append({k: w / tot for k, w in acc.items()} if tot > 1e-6 else ({main: 1.0} if fam and main else {}))
    if fam and radius > 0:   # a piece is stiffer than skin: weights averaged over nearby points of the piece
        # on a sample of at most ~3000 points (a whole-arm piece has 55k vertices), then every vertex blends its
        # four nearest samples
        n = len(me.vertices)
        sample = list(range(0, n, max(1, n // 3000)))
        kd = kdtree.KDTree(len(sample))
        for k, vi in enumerate(sample):
            kd.insert(me.vertices[vi].co, k)
        kd.balance()
        smooth = []
        for vi in sample:
            acc, tot = {}, 0.0
            for co, k, d in kd.find_range(me.vertices[vi].co, radius):
                w = 1 - (d / radius) ** 2
                tot += w
                for name, x in raw[sample[k]].items():
                    acc[name] = acc.get(name, 0.0) + w * x
            smooth.append({nm: x / tot for nm, x in acc.items()} if tot else raw[vi])
        out = []
        for v in me.vertices:
            acc, tot = {}, 0.0
            for co, k, d in kd.find_n(v.co, 4):
                w = 1 / (d + 1e-6 * radius)
                tot += w
                for name, x in smooth[k].items():
                    acc[name] = acc.get(name, 0.0) + w * x
            out.append({nm: x / tot for nm, x in acc.items()})
        raw = out
    groups = {}
    for v, acc in zip(me.vertices, raw):
        if fam and main and rigidity > 0:
            acc = {n: x * (1 - rigidity) for n, x in acc.items()}
            acc[main] = acc.get(main, 0.0) + rigidity
        top = sorted(acc.items(), key=lambda kv: -kv[1])[:4]
        tot = sum(w for _, w in top) or 1.0
        for name, w in top:
            if w / tot < 1e-3:
                continue
            g = groups.get(name) or o.vertex_groups.new(name=name)
            groups[name] = g
            g.add([v.index], w / tot, "REPLACE")
    return sorted(groups)


pieces = []
for pl in job["placements"]:
    m = pl["matrix"]
    mg = Matrix([[m[c * 4 + r] for c in range(4)] for r in range(4)])   # column-major -> rows
    mb = CONV @ mg @ CONV.inverted()
    me = src.data.copy()
    me.transform(mb)
    if mb.determinant() < 0:   # a mirrored copy: turn the faces back outward
        bm = bmesh.new(); bm.from_mesh(me)
        bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
        bm.to_mesh(me); bm.free()
    o = bpy.data.objects.new(f"Wear_{job.get('item', 'item')}_{pl.get('side', 'L')}", me)
    bpy.context.scene.collection.objects.link(o)
    rep = {"vertices": len(me.vertices)}
    limb = None
    if pl.get("limb"):
        limb = Limb((CONV @ Vector(pl["limb"]["a"]).to_4d()).to_3d(), (CONV @ Vector(pl["limb"]["b"]).to_4d()).to_3d())
        rep.update(fit_limb(me, limb))
    else:   # placed by the skeleton in the editor (a boot, a whole arm): no limb axis, only the push along the normal
        lo = Vector([min(v.co[i] for v in me.vertices) for i in range(3)])
        size = (Vector([max(v.co[i] for v in me.vertices) for i in range(3)]) - lo).length   # the piece's diagonal
        rep["close_to_skin"] = push_out(me, max(.08 * size, 1e-6))
    me.update()
    radius = 0.0
    if limb:   # about half the limb's thickness: the piece bends smoothly, never vertex by vertex
        rs = sorted(limb.cyl(v.co)[2].length for v in me.vertices)
        radius = min(.5 * rs[len(rs) // 2], .25 * limb.len)
    else:      # by the skeleton: a tenth of the piece, so a boot still bends at the ankle
        radius = .1 * size
    rep["bones"] = skin_weights(o, me, pl.get("bone"), radius, pl.get("bones"), pl.get("follow") != "down")
    mod = o.modifiers.new("Armature", "ARMATURE"); mod.object = arm
    o.parent = arm; o.matrix_parent_inverse = arm.matrix_world.inverted()
    for p in me.polygons:
        p.use_smooth = True
    pieces.append(o)
    report[o.name] = rep
bpy.data.objects.remove(src, do_unlink=True)

# export the skeleton and the pieces only
for o in list(bpy.data.objects):
    if o.type == "MESH" and o not in pieces:
        bpy.data.objects.remove(o, do_unlink=True)
arm.data.pose_position = "POSE"
bpy.ops.object.select_all(action="DESELECT")
for o in pieces + [arm]:
    o.select_set(True)
bpy.context.view_layer.objects.active = arm
Path(job["out"]).parent.mkdir(parents=True, exist_ok=True)
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4)
if job.get("report"):
    Path(job["report"]).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("WEAR_OK " + json.dumps(report, ensure_ascii=False), flush=True)
