"""Runs INSIDE Blender (background): open a generated armour piece so a limb can go in.

    blender -b -P blender_armour_hollow.py -- in.glb out.glb [open=both|top|bottom] [axis=auto|z|x,y,z] [wall=0.08|auto]

Image-to-3D models (SF3D, Hunyuan3D) come out as closed solids: a bracer is a capped log with no hole and no inner
wall. Here the piece's tube axis is found (the axis of its vertices whose other two spreads are most alike), the caps
are cut away (faces facing along the axis near an open end: both ends for a bracer, a greave or a cuirass, only the
upper one for a boot, only the lower one for a helmet or a cuisse closed below like a pot; axis=z takes the vertical
for upright pieces; axis=x,y,z is a direction in the GLB's own space, Y up, as the editor's «Вскрыть» sends its tube
axis), and the shell left is given a wall thickness inwards (wall = a share of its mean radius), so it has an inner
wall to sit on the skin. A piece that already has its wall (Hunyuan3D) takes wall=0; wall=auto looks: rays from the
middle out across the axis pass two surfaces (the inner wall, then the outer) when the piece has a wall, one when it is
a solid or a single sheet. The outer shape and the texture stay as generated. Prints HOLLOW_OK / HOLLOW_FAIL.
"""
import json
import re
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = Path(argv[0]), Path(argv[1])
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
OPEN = opt.get("open", "both")
WALL = opt.get("wall", "0.08")
AXIS = opt.get("axis", "auto")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(src))
meshes = [o for o in bpy.data.objects if o.type == "MESH" and len(o.data.vertices) >= 200
          and not re.search(r"-(conv)?colonly$|-col$", o.name)]   # the export's collision hull is not the piece
if not meshes:
    print("HOLLOW_FAIL no mesh", flush=True)
    sys.exit(1)
for o in [o for o in bpy.data.objects if o.type == "MESH" and o not in meshes]:
    bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.join()
ob = bpy.context.view_layer.objects.active
ob.data.transform(ob.matrix_world)
ob.matrix_world = Matrix()

# the tube axis: of the three principal axes, the one whose other two spreads are most alike
pts = [v.co.copy() for v in ob.data.vertices]
m = sum(pts, Vector()) / len(pts)
C = Matrix(((0, 0, 0), (0, 0, 0), (0, 0, 0)))
for p in pts:
    d = p - m
    for i in range(3):
        for j in range(3):
            C[i][j] += d[i] * d[j] / len(pts)
vals, vecs = [], []
M = C.copy()
for _ in range(3):   # power iteration with deflation
    v = Vector((1, .7, .3)).normalized()
    for _ in range(100):
        w = M @ v
        if w.length < 1e-30:
            break
        v = w.normalized()
    lam = v.dot(M @ v)
    vals.append(lam)
    vecs.append(v.copy())
    for i in range(3):
        for j in range(3):
            M[i][j] -= lam * v[i] * v[j]
best = min(range(3), key=lambda i: abs(vals[(i + 1) % 3] - vals[(i + 2) % 3]) / max(vals[(i + 1) % 3], vals[(i + 2) % 3], 1e-30))
axis = vecs[best].normalized()
if "," in AXIS:   # glTF (x, y up, z) -> Blender (x, -z, y)
    g = [float(x) for x in AXIS.split(",")]
    axis = Vector((g[0], -g[2], g[1])).normalized()
    if OPEN == "bottom":
        axis = -axis
elif OPEN in ("top", "bottom") or AXIS == "z":   # an upright piece: a boot's shaft, a helmet, a cuirass
    axis = Vector((0, 0, 1)) if OPEN != "bottom" else Vector((0, 0, -1))   # the open end is the axis' far end
ts = [(p - m).dot(axis) for p in pts]
t0, t1 = min(ts), max(ts)
L = t1 - t0
rad = sorted((p - m - axis * (p - m).dot(axis)).length for p in pts)
r_mean = sum(rad) / len(rad)

if WALL == "auto":   # does the piece have its own wall: count the surfaces a ray from the middle passes going out
    bvh = BVHTree.FromObject(ob, bpy.context.evaluated_depsgraph_get())
    side = axis.orthogonal().normalized()
    counts = []
    for k in range(8):
        d = (Matrix.Rotation(k * 3.14159265 / 4, 3, axis) @ side).normalized()
        o, n = m.copy(), 0
        while n < 6:
            hit = bvh.ray_cast(o, d)
            if hit[0] is None:
                break
            n += 1
            o = hit[0] + d * 1e-4 * max(r_mean, 1e-6)
        counts.append(n)
    counts.sort()
    WALL = 0.0 if counts[len(counts) // 2] >= 2 else 0.08
    print("HOLLOW_WALL " + json.dumps({"surfaces": counts, "wall": WALL}), flush=True)
WALL = float(WALL)

# cut the caps: a plane across the axis a little in from each open end gives a clean opening, then what is left of
# a domed cap (faces turned along the axis in the end zone) goes too
bm = bmesh.new()
bm.from_mesh(ob.data)
ends = [(t1, axis)] + ([(t0, -axis)] if OPEN == "both" else [])
for t_end, n in ends:
    co = m + axis * (t_end - (.04 * L if n.dot(axis) > 0 else -.04 * L))
    bmesh.ops.bisect_plane(bm, geom=bm.verts[:] + bm.edges[:] + bm.faces[:], plane_co=co, plane_no=n, clear_outer=True)
bm.normal_update()
kill = []
for f in bm.faces:
    c = f.calc_center_median() - m
    t = c.dot(axis)
    along = f.normal.dot(axis)
    # a shell with its own wall (Hunyuan3D) has an inner cap too, facing into the piece: what lies across the axis
    # near the axis goes either way; the walls are further out
    core = abs(along) > .45 and (c - axis * t).length < .75 * r_mean
    top = t > t1 - .2 * L and (along > .45 or core)
    bottom = OPEN == "both" and t < t0 + .2 * L and (along < -.45 or core)
    if top or bottom:
        kill.append(f)
bmesh.ops.delete(bm, geom=kill, context="FACES")
bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
bm.to_mesh(ob.data)
bm.free()

# a wall inwards (the solidify goes against the normals: the outer shell keeps its place and size)
if WALL > 0:
    mod = ob.modifiers.new("wall", "SOLIDIFY")
    mod.thickness = WALL * r_mean
    mod.offset = -1.0
    mod.use_even_offset = True
    mod.use_rim = True
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.modifier_apply(modifier=mod.name)

dst.parent.mkdir(parents=True, exist_ok=True)
bpy.ops.object.select_all(action="DESELECT")
ob.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(dst), export_format="GLB", use_selection=True)
print("HOLLOW_OK " + json.dumps({"caps_removed": len(kill), "axis": [round(x, 3) for x in axis], "length": round(L, 4),
                                  "mean_radius": round(r_mean, 4), "wall": round(WALL * r_mean, 4),
                                  "vertices": len(ob.data.vertices)}), flush=True)
