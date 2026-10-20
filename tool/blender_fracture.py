"""Runs INSIDE Blender (background): split a model into physically plausible chunks (Voronoi fracture) for a
destructible object, with a flat "inside" material on the cut surfaces, and export whole + chunks as one GLB.

    blender -b -P blender_fracture.py -- in.glb out_dir [chunks=12] [seed=1] [interior=auto|#rrggbb] [name=thing]

Writes <out_dir>/<name>_destructible.glb  (objects: Whole, chunk_01 ... each chunk's origin = its centre) and
<out_dir>/fracture.json (centres in Godot axes, volumes, size). Prints FRAC_ lines.
"""
import json
import math
import random
import re
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
src, out_dir = Path(argv[0]), Path(argv[1])
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
N = int(opt.get("chunks", 12))
SEED = int(opt.get("seed", 1))
NAME = opt.get("name", src.stem)
out_dir.mkdir(parents=True, exist_ok=True)
rng = random.Random(SEED)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(src))
PROXY = re.compile(r"-(conv)?col(only)?$|-(conv)?colonly|-trimesh|-navmesh|-occ", re.I)   # Godot import suffixes
meshes = [o for o in bpy.context.scene.objects if o.type == "MESH" and not PROXY.search(o.name)]
if not meshes:
    raise SystemExit("FRAC_ERROR no mesh in the model")
for o in list(bpy.context.scene.objects):
    if o not in meshes:
        bpy.data.objects.remove(o)
for o in meshes:
    o.data = o.data.copy()
    bpy.context.view_layer.objects.active = o
    o.select_set(True)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
if len(meshes) > 1:
    bpy.ops.object.join()
whole = bpy.context.view_layer.objects.active
whole.name = "Whole"
me = whole.data

# ---- interior colour: the average of the base colour texture, a bit darker
def mean_colour():
    for m in me.materials:
        if not m or not m.use_nodes:
            continue
        for n in m.node_tree.nodes:
            if n.type == "BSDF_PRINCIPLED":
                bc = n.inputs["Base Color"]
                if bc.links and bc.links[0].from_node.type == "TEX_IMAGE" and bc.links[0].from_node.image:
                    img = bc.links[0].from_node.image
                    w, h = img.size
                    buf = np.empty(w * h * 4, np.float32)
                    img.pixels.foreach_get(buf)
                    px = buf.reshape(-1, 4)[::max(1, w * h // 40000), :3]
                    return tuple(float(x) for x in px.mean(0))
                return tuple(float(x) for x in bc.default_value[:3])
    return (0.4, 0.35, 0.3)


hexv = opt.get("interior", "auto")
if hexv.startswith("#") and len(hexv) >= 7:
    base = tuple(int(hexv[i:i + 2], 16) / 255 for i in (1, 3, 5))
    base = tuple(c ** 2.2 for c in base)               # picked as sRGB
else:
    base = mean_colour()
    base = tuple(c * 0.75 for c in base)
inside = bpy.data.materials.new("inside")
inside.use_nodes = True
bs = next(n for n in inside.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
bs.inputs["Base Color"].default_value = (*base, 1)
bs.inputs["Roughness"].default_value = 0.92
me.materials.append(inside)
INSIDE = len(me.materials) - 1

# ---- cut centres inside the mesh, spread evenly (best candidate of several random points)
bm0 = bmesh.new()
bm0.from_mesh(me)
bmesh.ops.recalc_face_normals(bm0, faces=bm0.faces)
bvh = BVHTree.FromBMesh(bm0)
bb = [Vector(c) for c in whole.bound_box]
lo = Vector((min(v.x for v in bb), min(v.y for v in bb), min(v.z for v in bb)))
hi = Vector((max(v.x for v in bb), max(v.y for v in bb), max(v.z for v in bb)))
size = hi - lo


def inside_test(p):
    votes = 0
    for d in (Vector((1, 0.01, 0.02)), Vector((0.02, 1, 0.01)), Vector((0.01, 0.02, 1))):
        n, cur = 0, p.copy()
        for _ in range(64):
            loc, nor, idx, dist = bvh.ray_cast(cur, d)
            if loc is None:
                break
            n += 1
            cur = loc + d.normalized() * 1e-4
        votes += n % 2
    return votes >= 2


def candidate():
    for _ in range(400):
        p = Vector((rng.uniform(lo.x, hi.x), rng.uniform(lo.y, hi.y), rng.uniform(lo.z, hi.z)))
        if inside_test(p):
            return p
    return (lo + hi) / 2


seeds = []
for i in range(N):
    best, bd = None, -1
    for _ in range(14):
        c = candidate()
        d = min(((c - s).length for s in seeds), default=1e9)
        if d > bd:
            best, bd = c, d
    seeds.append(best)
print("FRAC_SEEDS", len(seeds))

# ---- one chunk per seed: the part of the mesh nearer to it than to any other seed
chunks = []
for i, s in enumerate(seeds):
    bm = bm0.copy()
    others = sorted((o for j, o in enumerate(seeds) if j != i), key=lambda o: (o - s).length)
    for o in others:
        mid = (s + o) / 2
        nrm = (o - s).normalized()
        geom = bm.verts[:] + bm.edges[:] + bm.faces[:]
        bmesh.ops.bisect_plane(bm, geom=geom, plane_co=mid, plane_no=nrm, clear_outer=True, clear_inner=False)
    loops = [e for e in bm.edges if e.is_boundary]
    if loops:
        for f in bmesh.ops.holes_fill(bm, edges=loops, sides=0)["faces"]:
            f.material_index = INSIDE
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    if len(bm.faces) < 6:
        bm.free()
        continue
    chunks.append((i, bm))
print("FRAC_CHUNKS", len(chunks))


def volume(bm):
    v = 0.0
    for f in bm.faces:
        if len(f.verts) == 3:
            a, b, c = (x.co for x in f.verts)
            v += a.dot(b.cross(c)) / 6.0
    return abs(v)


objs, info = [], []
tot = 0.0
for k, (i, bm) in enumerate(chunks):
    bmesh.ops.triangulate(bm, faces=bm.faces[:])
    vol = volume(bm)
    cen = sum((v.co for v in bm.verts), Vector()) / len(bm.verts)
    for v in bm.verts:
        v.co -= cen
    m = bpy.data.meshes.new(f"chunk_{k + 1:02d}")
    bm.to_mesh(m)
    bm.free()
    for mat in me.materials:
        m.materials.append(mat)
    ob = bpy.data.objects.new(f"chunk_{k + 1:02d}", m)
    ob.location = cen
    bpy.context.scene.collection.objects.link(ob)
    objs.append(ob)
    sz = Vector(ob.dimensions)
    info.append(dict(name=ob.name, volume=vol, size=[sz.x, sz.z, sz.y],
                     centre=[cen.x, cen.z, -cen.y]))
    tot += vol
for d in info:
    d["share"] = d["volume"] / tot if tot > 1e-12 else 1.0 / len(info)
bm0.free()

res = dict(name=NAME, chunks=info, size=[size.x, size.z, size.y], height=size.z, volume=tot,
           interior=list(base), whole_faces=len(me.polygons))
(out_dir / "fracture.json").write_text(json.dumps(res, indent=1), encoding="utf-8")

bpy.ops.object.select_all(action="DESELECT")
whole.select_set(True)
for o in objs:
    o.select_set(True)
bpy.context.view_layer.objects.active = whole
glb = out_dir / f"{NAME}_destructible.glb"
bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB", use_selection=True, export_yup=True,
                          export_apply=True)
print("FRAC_GLB", glb, len(objs), "chunks")
