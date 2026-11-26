"""Texture transfer, the Blender half (driven by tool/tex_transfer.py): a painted copy of a piece (Hunyuan3D-Paint,
TRELLIS.2, Meshy... - its own mesh and unwrap) baked selected -> active into OUR piece's unwrap, per material slot.

blender -b -P blender_tex_transfer.py -- <target.glb> <source.glb> <out_dir> [align=auto|none] [rotate_y=DEG] [icp=N]
    [sizes=name:W,name:W...]

- the target's materials are named by the caller (sf3dmat_<i>), each baked into its own image of its own size;
- the copy is put over the piece: bounding boxes (centre, largest size), then ICP with scale (both ways: each point to the
  other surface's nearest, Umeyama); a generator's copy comes normalised and centred, Paint's sits in place already;
- what is read off the copy: its base colour, and metallic / roughness only where a texture drives them (a bare factor
  says nothing: Hunyuan-Paint writes metallic 1 with no map) - each through an emission, no lights involved;
- per slot: <out>/sf3dmat_<i>_{color,metal,rough}.npy (float32, linear), _hit.npy (the ray found the copy), _cover.npy
  (the slot's own islands); <out>/transfer.json: the fit (matrix, error) and which passes were baked.
"""
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

argv = sys.argv[sys.argv.index("--") + 1:]
TARGET, SOURCE, OUT = argv[0], argv[1], Path(argv[2])
OPT = dict(a.split("=", 1) for a in argv[3:] if "=" in a)
ALIGN = OPT.get("align", "auto")
ROT_Y = float(OPT.get("rotate_y", 0))
ICP_N = int(OPT.get("icp", 25))
SIZES = {k: int(v) for k, v in (x.split(":") for x in OPT.get("sizes", "").split(",") if ":" in x)}
OUT.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)


def import_glb(path):
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    new = [o for o in bpy.data.objects if o not in before]
    for o in new:
        if o.type == "ARMATURE":
            o.data.pose_position = "REST"   # a fitted piece's skin: baked as it was made
    return [o for o in new if o.type == "MESH"]


def real(objs, need_named=False):
    """meshes that render (a rig's bone shapes come in as hidden meshes) and, for the piece, carry its materials"""
    return [o for o in objs if not o.hide_render and o.visible_get() and len(o.data.polygons)
            and (not need_named or any(m and m.name.startswith("sf3dmat_") for m in o.data.materials))]


tgt = real(import_glb(TARGET), need_named=True)
src = real(import_glb(SOURCE))
if not tgt or not src:
    raise SystemExit("TT_FAIL no mesh in " + ("the target" if not tgt else "the copy"))
for o in src:   # the copy's own node transforms baked into its mesh: one matrix moves it after
    o.data = o.data.copy()
    o.data.transform(o.matrix_world)
    o.parent = None
    o.matrix_world = Matrix.Identity(4)
    o.data.update()


def world_points(objs, limit=None):
    dg = bpy.context.evaluated_depsgraph_get()
    pts, tris = [], []
    base = 0
    for o in objs:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        me.calc_loop_triangles()
        co = np.empty(len(me.vertices) * 3, np.float64)
        me.vertices.foreach_get("co", co)
        co = co.reshape(-1, 3)
        mw = np.array(o.matrix_world)
        co = co @ mw[:3, :3].T + mw[:3, 3]
        lt = np.empty(len(me.loop_triangles) * 3, np.int64)
        me.loop_triangles.foreach_get("vertices", lt)
        pts.append(co)
        tris.append(lt.reshape(-1, 3) + base)
        base += len(co)
        ev.to_mesh_clear()
    pts = np.concatenate(pts)
    return pts, np.concatenate(tris)


def bvh_of(pts, tris):
    return BVHTree.FromPolygons([Vector(p) for p in pts], tris.tolist(), all_triangles=True)


def umeyama(a, b):
    """s, R, t with b ~ s R a + t"""
    ma, mb = a.mean(0), b.mean(0)
    A, B = a - ma, b - mb
    U, S, Vt = np.linalg.svd(B.T @ A / len(a))
    D = np.eye(3)
    if np.linalg.det(U) * np.linalg.det(Vt) < 0:
        D[2, 2] = -1
    R = U @ D @ Vt
    s = np.trace(np.diag(S) @ D) / max((A ** 2).sum() / len(a), 1e-12)
    return s, R, mb - s * R @ ma


def to_mat(s, R, t):
    M = np.eye(4)
    M[:3, :3] = s * R
    M[:3, 3] = t
    return M


tp, tt = world_points(tgt)
sp, st = world_points(src)
t_bvh = bvh_of(tp, tt)
lo_t, hi_t = tp.min(0), tp.max(0)
lo_s, hi_s = sp.min(0), sp.max(0)
diag = float(np.linalg.norm(hi_t - lo_t))
rng = np.random.default_rng(0)
M = np.eye(4)
err = None
if ALIGN == "auto":
    rz = math.radians(ROT_Y)   # (Blender: Z up; the copy's turn about the vertical)
    R0 = np.array([[math.cos(rz), -math.sin(rz), 0], [math.sin(rz), math.cos(rz), 0], [0, 0, 1]])
    s0 = float(np.max(hi_t - lo_t) / max(np.max(hi_s - lo_s), 1e-9))
    c_t, c_s = (lo_t + hi_t) / 2, (lo_s + hi_s) / 2
    M = to_mat(s0, R0, c_t - s0 * R0 @ c_s)
    s_pick = sp[rng.choice(len(sp), min(len(sp), 6000), replace=False)]
    t_pick = tp[rng.choice(len(tp), min(len(tp), 6000), replace=False)]
    for it in range(ICP_N):
        moved = s_pick @ M[:3, :3].T + M[:3, 3]
        a, b, d = [], [], []
        for p0, p in zip(s_pick, moved):   # the copy's points to the piece's surface
            hit = t_bvh.find_nearest(Vector(p))
            if hit[0] is not None:
                a.append(p0); b.append(np.array(hit[0])); d.append(hit[3])
        s_now = sp @ M[:3, :3].T + M[:3, 3]
        s_bvh = bvh_of(s_now, st)
        Minv = np.linalg.inv(M)
        for q in t_pick:                   # the piece's points to the copy's surface (no shrinking onto a part)
            hit = s_bvh.find_nearest(Vector(q))
            if hit[0] is not None:
                a.append(Minv[:3, :3] @ np.array(hit[0]) + Minv[:3, 3]); b.append(q); d.append(hit[3])
        a, b, d = np.array(a), np.array(b), np.array(d)
        keep = d <= max(np.percentile(d, 90), 1e-9)   # the farthest tenth: parts one of them lacks
        s, R, t = umeyama(a[keep], b[keep])
        M_new = to_mat(s, R, t)
        err = float(np.median(d) / diag)
        if np.abs(M_new - M).max() < 1e-6:
            M = M_new
            break
        M = M_new
for o in src:
    o.matrix_world = Matrix(M.tolist())
bpy.context.view_layer.update()

# ---- the bake
sc = bpy.context.scene
try:
    sc.render.engine = "CYCLES"
except TypeError:
    pass
sc.cycles.device = "CPU"   # (the GPU stays with the other jobs; an emission bake is light)
sc.cycles.samples = 4
bk = sc.render.bake
bk.use_selected_to_active = True
bk.cage_extrusion = 0.03 * diag
bk.max_ray_distance = 0.09 * diag
bk.margin = 2
bk.use_clear = False


def bsdf_of(m):
    return next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.use_nodes else None


def out_of(m):
    nt = m.node_tree
    outs = [n for n in nt.nodes if n.type == "OUTPUT_MATERIAL"]
    return next((n for n in outs if n.is_active_output), outs[0] if outs else nt.nodes.new("ShaderNodeOutputMaterial"))


src_mats = {m for o in src for m in o.data.materials if m}
for m in src_mats:
    if not m.use_nodes:
        m.use_nodes = True
textured = {k: any((b := bsdf_of(m)) is not None and b.inputs[k].is_linked for m in src_mats)
            for k in ("Metallic", "Roughness")}


def wire_source(kind):
    """each copy material's emission = its base colour / metallic / roughness"""
    for m in src_mats:
        nt, b = m.node_tree, bsdf_of(m)
        em = nt.nodes.get("tt_em") or nt.nodes.new("ShaderNodeEmission")
        em.name = "tt_em"
        for l in list(em.inputs[0].links):
            nt.links.remove(l)
        sock = b.inputs[{"color": "Base Color", "metal": "Metallic", "rough": "Roughness"}[kind]] if b else None
        if sock is not None and sock.is_linked:
            nt.links.new(sock.links[0].from_socket, em.inputs[0])
        elif sock is not None:
            v = sock.default_value
            em.inputs[0].default_value = tuple(v) if kind == "color" else (v, v, v, 1)
        else:
            em.inputs[0].default_value = (.5, .5, .5, 1)
        nt.links.new(em.outputs[0], out_of(m).inputs["Surface"])


tgt_mats = {}
for o in tgt:
    for m in o.data.materials:
        if m and m.name.startswith("sf3dmat_"):
            tgt_mats[m.name] = m
images = {}


def target_images(kind):
    for name, m in tgt_mats.items():
        if not m.use_nodes:
            m.use_nodes = True
        n = SIZES.get(name, 1024)
        im = bpy.data.images.new(f"{name}_{kind}", n, n, alpha=True, float_buffer=True)
        im.colorspace_settings.name = "Non-Color"
        im.pixels.foreach_set(np.zeros(n * n * 4, np.float32))   # alpha 0: what no ray reaches stays 0
        nt = m.node_tree
        node = nt.nodes.get("tt_target") or nt.nodes.new("ShaderNodeTexImage")
        node.name = "tt_target"
        node.image = im
        nt.nodes.active = node
        images[(name, kind)] = im


def save(kind, alpha_too=False):
    for name in tgt_mats:
        im = images[(name, kind)]
        n = im.size[0]
        px = np.empty(n * n * 4, np.float32)
        im.pixels.foreach_get(px)
        px = px.reshape(n, n, 4)[::-1]   # (Blender's rows go up)
        np.save(OUT / f"{name}_{kind}.npy", px[..., :3] if kind == "color" else px[..., 0])
        if alpha_too:
            np.save(OUT / f"{name}_hit.npy", px[..., 3] > .5)


def bake_onto(active_objs):
    for o in active_objs:   # one target mesh at a time is the active one; the copy is selected for each
        bpy.ops.object.select_all(action="DESELECT")
        for s_ in src:
            s_.select_set(True)
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.bake(type="EMIT")


done = ["color"]
wire_source("color")
target_images("color")
bake_onto(tgt)
save("color", alpha_too=True)
for kind, key in (("metal", "Metallic"), ("rough", "Roughness")):
    if textured[key]:
        wire_source(kind)
        target_images(kind)
        bake_onto(tgt)
        save(kind)
        done.append(kind)

# the slots' own islands (the cover the padding keeps): the piece alone, a constant 1
bk.use_selected_to_active = False
for name, m in tgt_mats.items():
    nt = m.node_tree
    em = nt.nodes.get("tt_one") or nt.nodes.new("ShaderNodeEmission")
    em.name = "tt_one"
    em.inputs[0].default_value = (1, 1, 1, 1)
    nt.links.new(em.outputs[0], out_of(m).inputs["Surface"])
target_images("cover")
bpy.ops.object.select_all(action="DESELECT")
for o in tgt:
    o.select_set(True)
bpy.context.view_layer.objects.active = tgt[0]
bpy.ops.object.bake(type="EMIT")
for name in tgt_mats:
    im = images[(name, "cover")]
    n = im.size[0]
    px = np.empty(n * n * 4, np.float32)
    im.pixels.foreach_get(px)
    np.save(OUT / f"{name}_cover.npy", px.reshape(n, n, 4)[::-1][..., 0] > .5)

(OUT / "transfer.json").write_text(json.dumps({
    "materials": sorted(tgt_mats), "passes": done, "matrix": M.tolist(), "fit_error": err,
    "scale": float(np.cbrt(abs(np.linalg.det(M[:3, :3])))), "target_size": diag}, indent=1), encoding="utf-8")
print("TT_OK", json.dumps({"passes": done, "fit_error": err}))
