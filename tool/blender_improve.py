"""Blender side of the «Improve» step (model_improve.py): one Blender run for the steps that need it.

blender -b --factory-startup -P blender_improve.py -- <in.glb> <out> [bake=<dense.ply>] [sym=pos|neg]
                                                     [size=2048] [cage=0.004] [ray=0.012]
  bake  (D) the dense mesh's relief baked into a tangent-space normal map of the model's own unwrap (Cycles on the CPU,
        selected -> active; cage / ray in parts of the model's size), hooked into its material
  sym   (C) the mirror plane x = x0 found from the mesh (each vertex's mirror image against its nearest vertex,
        golden-section), the model moved so it is x = 0, then Symmetrize keeping the +X half (pos: the model's own left)
        or the -X half (neg); the mirrored half takes the kept half's UVs, so its texture (and normal map) too
  -> <out> GLB (its pictures as they were, the baked normal map added)
blender ... -- <in.glb> <prefix> render=back,left,right [w=864] [h=1152]
  (E) the model in EEVEE under Blender's courtyard light, orthographic, framed by its own bounds like the app's
  previews -> <prefix>_<view>.png
Prints IMPROVE_OK {json} at the end."""
import json
import math
import os
import sys
import time

import bpy
from mathutils import Vector
from mathutils.kdtree import KDTree

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[:2]
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
T = {}
t0 = time.time()
bpy.ops.wm.read_factory_settings(use_empty=True)   # (the factory scene's cube, camera and light out of the export)
sc = bpy.context.scene
bpy.ops.import_scene.gltf(filepath=src)
for o in sc.objects:   # Godot's collision proxies (<name>-colonly / -convcolonly): not the model
    if o.type == "MESH" and "colonly" in o.name.lower():
        o.hide_render = True
meshes = [o for o in sc.objects if o.type == "MESH" and not o.hide_render]
info = {}


def bounds(objs):
    dg = bpy.context.evaluated_depsgraph_get()
    pts = []
    for o in objs:
        ev = o.evaluated_get(dg)
        pts += [ev.matrix_world @ v.co for v in ev.to_mesh().vertices]
        ev.to_mesh_clear()
    lo = Vector((min(p.x for p in pts), min(p.y for p in pts), min(p.z for p in pts)))
    hi = Vector((max(p.x for p in pts), max(p.y for p in pts), max(p.z for p in pts)))
    return lo, hi


if "render" in opt:
    W, H = int(opt.get("w", 864)), int(opt.get("h", 1152))
    sc.render.resolution_x, sc.render.resolution_y = W, H
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    world = bpy.data.worlds.new("hdri")
    world.use_nodes = True
    nt = world.node_tree
    bg = next(n for n in nt.nodes if n.type == "BACKGROUND")
    env = nt.nodes.new("ShaderNodeTexEnvironment")
    env.image = bpy.data.images.load(os.path.join(os.path.dirname(bpy.app.binary_path), "%d.%d" % bpy.app.version[:2],
                                                  "datafiles", "studiolights", "world", "courtyard.exr"))
    nt.links.new(env.outputs["Color"], bg.inputs["Color"])
    flat = nt.nodes.new("ShaderNodeBackground")
    flat.inputs["Color"].default_value = (0.16, 0.16, 0.16, 1)
    lp = nt.nodes.new("ShaderNodeLightPath")
    mix = nt.nodes.new("ShaderNodeMixShader")
    wo = next(n for n in nt.nodes if n.type == "OUTPUT_WORLD")
    nt.links.new(lp.outputs["Is Camera Ray"], mix.inputs[0])
    nt.links.new(bg.outputs[0], mix.inputs[1])
    nt.links.new(flat.outputs[0], mix.inputs[2])
    nt.links.new(mix.outputs[0], wo.inputs["Surface"])
    sc.world = world
    engines = [i.identifier for i in bpy.types.RenderSettings.bl_rna.properties["engine"].enum_items]
    sc.render.engine = "BLENDER_EEVEE_NEXT" if "BLENDER_EEVEE_NEXT" in engines else "BLENDER_EEVEE"
    sc.view_settings.view_transform = "Standard"
    try:
        sc.eevee.taa_render_samples = 32
    except AttributeError:
        pass
    lo, hi = bounds(meshes)
    c = (lo + hi) / 2
    cam.data.ortho_scale = max(hi.z - lo.z, max(hi.x - lo.x, hi.y - lo.y) * H / W) * 1.08
    done = []
    for view in opt["render"].split(","):
        yaw = {"front": 0, "back": 180, "left": 90, "right": -90}[view]
        r = math.radians(yaw)
        cam.location = c + Vector((math.sin(r), -math.cos(r), 0.0)) * 10
        cam.rotation_euler = (math.radians(90), 0, r)
        cam.data.clip_end = 100
        sc.render.filepath = f"{out}_{view}.png"
        bpy.ops.render.render(write_still=True)
        done.append(view)
    print("IMPROVE_OK" + json.dumps({"rendered": done, "seconds": round(time.time() - t0, 1)}))
    raise SystemExit(0)

ob = meshes[0]
if len(meshes) > 1:
    bpy.ops.object.select_all(action="DESELECT")
    for o in meshes:
        o.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.join()
me = ob.data

if "bake" in opt:   # ---- D
    t = time.time()
    before = set(sc.objects)
    bpy.ops.wm.ply_import(filepath=opt["bake"])
    hi_ob = next(o for o in sc.objects if o not in before)
    size = int(opt.get("size", 2048))
    img = bpy.data.images.new("relief_normal", size, size, alpha=False, float_buffer=False)
    img.colorspace_settings.name = "Non-Color"
    for slot in ob.material_slots:
        nt = slot.material.node_tree
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = img
        n.name = "bake_target"
        nt.nodes.active = n
    sc.render.engine = "CYCLES"
    sc.cycles.device = "CPU"   # (the GPU stays with the generators)
    sc.cycles.samples = 1
    bb = [ob.matrix_world @ Vector(c) for c in ob.bound_box]
    diag = max((a - b).length for a in bb for b in bb)
    bk = sc.render.bake
    bk.use_selected_to_active = True
    bk.cage_extrusion = float(opt.get("cage", 0.004)) * diag
    bk.max_ray_distance = float(opt.get("ray", 0.012)) * diag
    bk.normal_space = "TANGENT"
    bk.margin = 8
    bk.margin_type = "EXTEND"
    bpy.ops.object.select_all(action="DESELECT")
    hi_ob.select_set(True)
    ob.select_set(True)
    bpy.context.view_layer.objects.active = ob
    bpy.ops.object.bake(type="NORMAL")
    for slot in ob.material_slots:
        nt = slot.material.node_tree
        nt.nodes.remove(nt.nodes["bake_target"])
        bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
        tex = nt.nodes.new("ShaderNodeTexImage")
        tex.image = img
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nm.space = "TANGENT"
        nt.links.new(tex.outputs["Color"], nm.inputs["Color"])
        nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    img.pack()
    bpy.data.objects.remove(hi_ob)
    info["bake"] = {"seconds": round(time.time() - t, 1), "size": size}

if "sym" in opt:   # ---- C
    t = time.time()
    mw = ob.matrix_world
    P = [mw @ v.co for v in me.vertices]
    xs = [p.x for p in P]
    size = max(max(p.z for p in P) - min(p.z for p in P), max(xs) - min(xs))
    sample = P[::max(1, len(P) // 6000)]
    kd = KDTree(len(P))
    for i, p in enumerate(P):
        kd.insert(p, i)
    kd.balance()

    def score(x0):
        return sum(kd.find(Vector((2 * x0 - p.x, p.y, p.z)))[2] for p in sample) / len(sample)

    c = (max(xs) + min(xs)) / 2
    a_, b_ = c - 0.03 * size, c + 0.03 * size
    g = 0.6180339887
    x1, x2 = b_ - g * (b_ - a_), a_ + g * (b_ - a_)
    f1, f2 = score(x1), score(x2)
    for _ in range(30):
        if f1 < f2:
            b_, x2, f2 = x2, x1, f1
            x1 = b_ - g * (b_ - a_); f1 = score(x1)
        else:
            a_, x1, f1 = x1, x2, f2
            x2 = a_ + g * (b_ - a_); f2 = score(x2)
    x0 = (a_ + b_) / 2
    err = score(x0)
    shift = mw.inverted().to_3x3() @ Vector((-x0, 0, 0))
    for v in me.vertices:
        v.co += shift
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob
    ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.symmetrize(direction="POSITIVE_X" if opt["sym"] == "pos" else "NEGATIVE_X", threshold=0.0005 * size)
    bpy.ops.object.mode_set(mode="OBJECT")
    info["sym"] = {"x0": round(x0, 5), "mirror_err": round(err / size, 5), "kept": opt["sym"],
                   "seconds": round(time.time() - t, 1)}

t = time.time()
bpy.ops.export_scene.gltf(filepath=out, export_format="GLB", export_image_format="AUTO", export_yup=True)
info["export_s"] = round(time.time() - t, 1)
info["faces"] = len(me.polygons)
info["seconds"] = round(time.time() - t0, 1)
print("IMPROVE_OK" + json.dumps(info))
