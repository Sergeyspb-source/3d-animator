"""Runs INSIDE Blender (background): add a lip-sync mouth plate to a rigged character (closed-mouth Tripo heads).

    blender -b -P blender_mouth_plate.py -- job.json

job.json: {"source": rigged.glb, "out": out.glb, "mouth_c": [x,y,z], "corner_L": [..], "corner_R": [..]  (glTF space),
           "head_bone": "mixamorig:Head", "report": path.json (optional)}

Ported from the game project's home beggar (source_assets/home_beggar/add_beggar_mouth.py) and generalised: the mouth
line comes from the landmark editor's three face points instead of a texture search, and every size scales with the
mouth width (the beggar's numbers were metres for a 3.3 cm mouth). A thin plate lies on the skin along the line;
its basis is a closed-mouth arc, ARKit-style shape keys open it into a dark mouth with an upper-teeth band and a
tongue: jawOpen mouthFunnel mouthPucker mouthStretch mouthSmile mouthUpperUp mouthLowerDown (the names the game's
lipsync.py -> make_face_clip.py pipeline drives). The plate copies the skin weights under it (head, neck, Jaw), and
the face gets a small jawOpen key that lowers the chin below the open lower edge.
"""
import json
import math
import sys

import bmesh
import bpy
import mathutils
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

job = json.loads(open(sys.argv[sys.argv.index("--") + 1], encoding="utf-8").read())


def bl(p):  # glTF -> Blender
    return Vector((p[0], -p[2], p[1]))


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["source"])
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups]
for o in list(bpy.data.objects):
    if o.type == "MESH" and not o.vertex_groups:
        bpy.data.objects.remove(o, do_unlink=True)   # the importer's bone-shape sphere
arm.data.pose_position = "REST"
bpy.context.view_layer.update()

M, CL, CR = bl(job["mouth_c"]), bl(job["corner_L"]), bl(job["corner_R"])
W = (CL - CR).length                       # mouth width
k = W / 0.033                              # the beggar's sizes were tuned on a 3.3 cm mouth
SURFACE_OFFSET = 0.0012 * k
OPEN_HEIGHT = 0.017 * k
NU, NV = 28, 10

# the face = the mesh with the most vertices near the mouth
def near(o):
    mw = o.matrix_world
    return sum(1 for v in o.data.vertices if ((mw @ v.co) - M).length < W)
face = max(meshes, key=near)
fw = face.matrix_world
me = face.data
me.calc_loop_triangles()
wverts = [fw @ v.co for v in me.vertices]
tris = [tuple(t.vertices) for t in me.loop_triangles]
bvh = BVHTree.FromPolygons(wverts, tris)
ymin = min(v.y for v in wverts)


def surface(x, z):
    """First skin hit looking from the front (the character faces -Y): (location, normal, triangle) or None."""
    loc, nrm, idx, _ = bvh.ray_cast(Vector((x, ymin - W * 10, z)), Vector((0, 1, 0)), W * 40)
    return None if loc is None else (loc, nrm, idx)


# mouth line: parabola through the right corner, the centre and the left corner (front view x -> z)
xs = np.array([CR.x, M.x, CL.x]); zs = np.array([CR.z, M.z, CL.z])
coef = np.polyfit(xs, zs, 2)
cx, half_w = float((CL.x + CR.x) / 2), float(abs(CL.x - CR.x) / 2)


def line_z(x):
    return float(np.polyval(coef, x))


SHAPES = {   # width scale, upper height, lower height, roundness, corner lift (beggar values, scaled by k)
    "Basis":          (1.00, 0.0006, 0.0006, 0.25, 0.0),
    "jawOpen":        (0.94, 0.0035, OPEN_HEIGHT / k, 0.55, 0.0),
    "mouthFunnel":    (0.62, 0.0040, 0.0075, 0.50, 0.0),
    "mouthPucker":    (0.45, 0.0015, 0.0020, 0.50, 0.0),
    "mouthStretch":   (1.14, 0.0018, 0.0030, 0.70, 0.0),
    "mouthSmile":     (1.08, 0.0012, 0.0030, 0.70, 0.0030),
    "mouthUpperUp":   (1.00, 0.0030, 0.0,    0.60, 0.0),
    "mouthLowerDown": (1.00, 0.0,    0.0045, 0.60, 0.0),
}
SHAPES = {n: (sw, hu * k, hl * k, p, lift * k) for n, (sw, hu, hl, p, lift) in SHAPES.items()}
us = np.linspace(-1.0, 1.0, NU)
vs = np.linspace(-1.0, 1.0, NV)


def outline(params, u, v):
    sw, hu, hl, p, lift = params
    x = cx + u * half_w * sw
    prof = (1.0 - min(1.0, abs(u)) ** 2) ** p
    z = line_z(cx + u * half_w) + (v * hu * prof if v > 0 else v * hl * prof) + lift * abs(u) ** 2
    return x, z


def basis_row(v):
    """Closed mouth: teeth, tongue and their blend rows fold onto the edges, so only the dark band shows."""
    lo, hi = -0.56, 0.34
    if v >= hi:
        return 1.0
    if v <= lo:
        return -1.0
    return -1.0 + 2.0 * (v - lo) / (hi - lo)


def plate_point(params, u, v):
    if params is SHAPES["Basis"]:
        v = basis_row(v)
    x, z = outline(params, u, v)
    h = surface(x, z)
    if h is None:
        raise SystemExit(f"MOUTH_FAIL no skin under mouth point {(x, z)}: check the mouth points of the face markup")
    return h[0] + h[1] * SURFACE_OFFSET


basis = {(i, j): plate_point(SHAPES["Basis"], u, v) for i, u in enumerate(us) for j, v in enumerate(vs)}
bm = bmesh.new()
inv = fw.inverted()
grid = {key: bm.verts.new(inv @ p) for key, p in basis.items()}
for i in range(NU - 1):
    for j in range(NV - 1):
        bm.faces.new((grid[i, j], grid[i + 1, j], grid[i + 1, j + 1], grid[i, j + 1]))
uvl = bm.loops.layers.uv.new("UVMap")   # colours from a small gradient texture (Godot ignores COLOR_0 as albedo)
vert_key = {vv: key for key, vv in grid.items()}
for f in bm.faces:
    for loop in f.loops:
        i, j = vert_key[loop.vert]
        loop[uvl].uv = (i / (NU - 1), j / (NV - 1))
bm.verts.index_update()
order = sorted(grid.keys(), key=lambda key: grid[key].index)
mouth_me = bpy.data.meshes.new("Mouth")
bm.to_mesh(mouth_me)
bm.free()
mouth = bpy.data.objects.new("Mouth", mouth_me)
bpy.context.scene.collection.objects.link(mouth)
mouth.parent = face.parent
mouth.parent_type = face.parent_type
mouth.matrix_parent_inverse = face.matrix_parent_inverse.copy()
mouth.matrix_world = fw.copy()
mouth.shape_key_add(name="Basis")
for name, params in SHAPES.items():
    if name == "Basis":
        continue
    sk = mouth.shape_key_add(name=name, from_mix=False)
    for n, (i, j) in enumerate(order):
        sk.data[n].co = inv @ plate_point(params, us[i], vs[j])
# the skin's own weights under each plate vertex (barycentric): the plate follows head, neck and Jaw like the skin
group_names = {g.index: g.name for g in face.vertex_groups}
for n, (i, j) in enumerate(order):
    hit = surface(*outline(SHAPES["Basis"], us[i], vs[j]))
    a, b, c = (wverts[q] for q in tris[hit[2]])
    bary = mathutils.geometry.barycentric_transform(hit[0], a, b, c, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
    mix = {}
    for q, wq in zip(tris[hit[2]], bary):
        for g in me.vertices[q].groups:
            mix[g.group] = mix.get(g.group, 0.0) + max(0.0, wq) * g.weight
    total = sum(mix.values()) or 1.0
    for gidx, wgt in mix.items():
        if wgt / total > 0.01:
            vg = mouth.vertex_groups.get(group_names[gidx]) or mouth.vertex_groups.new(name=group_names[gidx])
            vg.add([n], wgt / total, "REPLACE")
mod = mouth.modifiers.new("Armature", "ARMATURE")
mod.object = arm
BANDS = [(0.0, (0.42, 0.11, 0.13)), (0.10, (0.42, 0.11, 0.13)), (0.17, (0.16, 0.035, 0.045)),
         (0.74, (0.16, 0.035, 0.045)), (0.80, (0.93, 0.90, 0.86)), (1.0, (0.93, 0.90, 0.86))]   # tongue, inside, teeth
TEX_H = 64
tex = bpy.data.images.new("mouth_bands", 4, TEX_H, alpha=False)
rows = []
for r in range(TEX_H):
    t = (r + 0.5) / TEX_H
    kk = next(n for n in range(1, len(BANDS)) if t <= BANDS[n][0])
    (t0, c0), (t1, c1) = BANDS[kk - 1], BANDS[kk]
    w = (t - t0) / (t1 - t0) if t1 > t0 else 0.0
    rows.append([c0[n] + (c1[n] - c0[n]) * w for n in range(3)] + [1.0])
tex.pixels[:] = [ch for row in rows for _ in range(4) for ch in row]
tex.pack()
mat = bpy.data.materials.new("mouth")
mat.use_nodes = True
bsdf = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
tnode = mat.node_tree.nodes.new("ShaderNodeTexImage")
tnode.image = tex
mat.node_tree.links.new(tnode.outputs["Color"], bsdf.inputs["Base Color"])
bsdf.inputs["Roughness"].default_value = 0.55
mouth_me.materials.append(mat)
for poly in mouth_me.polygons:
    poly.use_smooth = True

# chin key on the face: the skin just below the open lower edge drops a little, fading out under the chin
donors = {face.vertex_groups[n].index for n in (job["head_bone"], job.get("jaw_bone", "")) if n and face.vertex_groups.get(n)}
z_line = line_z(cx)
moved, max_drop = 0, 0.0
if face.data.shape_keys is None:
    face.shape_key_add(name="Basis")
fk = face.shape_key_add(name="jawOpen", from_mix=False)
d_full, d_end = 0.036 * k, 0.054 * k
for v in me.vertices:
    wsum = sum(g.weight for g in v.groups if g.group in donors)
    p = wverts[v.index]
    if wsum < 0.5 or p.y > M.y + W * 0.6:
        continue
    dx = (p.x - cx) / (half_w * 1.6)
    d = z_line - p.z
    dz_below = (d - 0.6 * OPEN_HEIGHT) / (0.7 * OPEN_HEIGHT)
    if abs(dx) >= 1.0 or dz_below < 0.0 or d > d_end:
        continue
    fall_x = 0.5 * (1 + math.cos(math.pi * dx))
    fall_z = min(1.0, dz_below) * (1.0 if d < d_full else max(0.0, (d_end - d) / (d_end - d_full)))
    drop = 0.35 * OPEN_HEIGHT * fall_x * fall_z
    if drop > 0:
        fk.data[v.index].co = inv @ (p - Vector((0, 0, drop)))
        moved += 1
        max_drop = max(max_drop, drop)

arm.data.pose_position = "POSE"
for o in bpy.data.objects:
    o.select_set(o.type in ("ARMATURE", "MESH"))
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_morph=True, export_morph_normal=False, export_influence_nb=4)
report = {"mouth_width": round(W, 5), "scale_vs_beggar": round(k, 3), "plate_verts": len(mouth_me.vertices),
          "keys": [n for n in SHAPES if n != "Basis"], "face_jawOpen_verts": moved, "face_jawOpen_max_drop": round(max_drop, 5)}
if job.get("preview"):   # closed / jawOpen / mouthSmile / mouthFunnel close-ups
    sc = bpy.context.scene
    try:
        sc.render.engine = "BLENDER_WORKBENCH"
        sc.display.shading.color_type = "TEXTURE"
    except (TypeError, AttributeError):
        pass
    sc.render.resolution_x = sc.render.resolution_y = 300
    sc.render.image_settings.color_mode = "RGB"
    sc.world = bpy.data.worlds.new("bg"); sc.world.color = (0.82, 0.8, 0.77)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = "ORTHO"; cam.data.ortho_scale = W * 4; cam.data.clip_end = W * 400
    cam.location = (cx, M.y - W * 100, z_line + W * 0.4); cam.rotation_euler = (math.radians(90), 0, 0)
    keyed = [o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys]
    shots = []
    for key in ("closed", "jawOpen", "mouthSmile", "mouthFunnel"):
        for o in keyed:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 1.0 if kb.name == key else 0.0
        sc.render.filepath = job["preview"].replace(".png", f"_{key}.png")
        bpy.ops.render.render(write_still=True)
        shots.append(sc.render.filepath)
    report["previews"] = shots
if job.get("report"):
    open(job["report"], "w", encoding="utf-8").write(json.dumps(report, indent=1))
print("MOUTH_OK", json.dumps(report), flush=True)
