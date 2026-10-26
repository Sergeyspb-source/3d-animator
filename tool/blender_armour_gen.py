"""Runs INSIDE Blender (background): a piece of armour made in the «Equipment: procedural» editor
(armour_gen_editor.html) finished for the game.

    blender -b -P blender_armour_gen.py -- job.json

job.json: {"character": rigged.glb, "out": piece.glb, "preview": png prefix, "work": folder, "item": name,
           "names": {naming: {joint: bone}}, "piece": the editor's piece, "sides": ["L", "R"] (a limb's; else none),
           "mesh": mesh.json, "wear": 0..1, "tex": texture size, "seed"}
mesh.json (the editor's, glTF axes, base64 little-endian arrays): {"v": float32 xyz, "uv": float32 the pattern's
           texture coordinates per vertex, "n": uint8 face sizes, "f": uint32 vertex indices, "m": uint8 material slots
           (0 the surface, 1 leather: straps, backing, lacing, 2 rivets and buckles, 3 mail, 4 quilting, 5 the rims' trim), "bi": uint16
           x4 bones per vertex (indices into "bones", three.js's names), "bw": float32 x4 their weights, "mats": the
           slots' specs (node_mat), "patterns": {"mail", "quilt": png} (red: height, green: light), "pattern_unit":
           a pattern tile's size, "radius": the limb radius the noise is scaled by}

The shape and the weights are the editor's: the piece is built there out of the skin, live, so what is seen (also in
its poses) is what is made. Here the three materials are procedural shaders baked into textures (colour, roughness,
normal) so the game gets plain PBR, and the piece is exported with the character's skeleton, like a piece put on in
the «Armour» mode, with renders of it on the character.
"""
import base64
import json
import math
import re
import sys
from array import array
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))   # Blender does not put the script's folder on the path
from i18n import t as _t

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))


def fail(msg):
    print("ARMOUR_GEN_FAIL " + msg, flush=True)
    sys.exit(1)


PARTS = ("Eye_", "EyeSocket", "Teeth_", "Gum_", "Tongue", "MouthCavity", "Icosphere")

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["character"])
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    fail(_t("blender.the_character_has_no_skeleton_build"))
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
body = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups and not o.name.startswith(PARTS)]
if not body:
    fail(_t("blender.the_character_has_no_skin_with"))
names = next((tbl for tbl in job["names"].values() if tbl.get("hips") in arm.data.bones), None)
if names is None:
    fail(_t("ag.bones_not_recognised"))

# ---------------------------------------------------------------- materials (procedural, baked)
def node_mat(name, spec, R, pattern=None, unit=1.0):
    """A procedural material for the bake from the editor's spec {kind: metal|leather (cloth too), col, spot (rust, patina
    or scuffs), rough, metal, pattern}; pattern: an image (red: height, green: how much light gets in) laid by the UV map
    «pattern» (mail rings, quilting), unit: its tile's size. Returns (material, metallic)."""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    for nd in list(nt.nodes):
        nt.nodes.remove(nd)
    N, L = nt.nodes.new, nt.links.new
    out = N("ShaderNodeOutputMaterial")
    bsdf = N("ShaderNodeBsdfPrincipled")
    L(bsdf.outputs[0], out.inputs[0])
    tc = N("ShaderNodeTexCoord")
    mp = N("ShaderNodeMapping")
    mp.inputs["Scale"].default_value = (1 / R, 1 / R, 1 / R)
    seed = int(job.get("seed", 1))   # another variant: the noise from elsewhere
    mp.inputs["Location"].default_value = (seed * 3.17, seed * 1.93, seed * 2.41)
    L(tc.outputs["Object"], mp.inputs[0])
    wear = float(job.get("wear", .35))
    kind, col, rough, metal, spot = spec["kind"], tuple(spec["col"]), float(spec["rough"]), float(spec["metal"]), tuple(spec["spot"])
    # large blotches, fine grain, rust or scuffs
    big = N("ShaderNodeTexNoise"); big.inputs["Scale"].default_value = 1.5; big.inputs["Detail"].default_value = 6
    fine = N("ShaderNodeTexNoise"); fine.inputs["Scale"].default_value = 14; fine.inputs["Detail"].default_value = 8
    vor = N("ShaderNodeTexVoronoi"); vor.inputs["Scale"].default_value = 9 if kind == "metal" else 28
    for t in (big, fine, vor):
        L(mp.outputs[0], t.inputs[0])
    dark = tuple(c * (.38 if kind == "metal" else .55) for c in col)   # dirt and tarnish
    mix1 = N("ShaderNodeMix"); mix1.data_type = "RGBA"
    mix1.inputs[6].default_value = (*col, 1); mix1.inputs[7].default_value = (*dark, 1)
    L(big.outputs["Fac"], mix1.inputs[0])
    # rust (metal) or worn light scuffs (leather), where the large noise passes a threshold set by the wear
    ramp = N("ShaderNodeValToRGB")
    ramp.color_ramp.elements[0].position = max(.0, .72 - .35 * wear)
    ramp.color_ramp.elements[1].position = min(1.0, ramp.color_ramp.elements[0].position + .08)
    L(fine.outputs["Fac"], ramp.inputs[0])
    mix2 = N("ShaderNodeMix"); mix2.data_type = "RGBA"
    mix2.inputs[7].default_value = (*spot, 1)
    L(mix1.outputs[2], mix2.inputs[6])
    L(ramp.outputs[0], mix2.inputs[0])
    # worn edges: bright metal where the surface is convex (Cycles' pointiness)
    geo = N("ShaderNodeNewGeometry")
    edge = N("ShaderNodeValToRGB")
    edge.color_ramp.elements[0].position = .52
    edge.color_ramp.elements[1].position = .62
    L(geo.outputs["Pointiness"], edge.inputs[0])
    edgef = N("ShaderNodeMath"); edgef.operation = "MULTIPLY"; edgef.inputs[1].default_value = wear * (1.0 if kind == "metal" else .5)
    L(edge.outputs[0], edgef.inputs[0])
    mix3 = N("ShaderNodeMix"); mix3.data_type = "RGBA"
    hi = tuple(min(1, c * 1.9 + .08) for c in col)
    mix3.inputs[7].default_value = (*hi, 1)
    L(mix2.outputs[2], mix3.inputs[6]); L(edgef.outputs[0], mix3.inputs[0])
    colour = mix3.outputs[2]
    if pattern is not None:   # the gaps between the rings, the sunk seams darker
        uvm = N("ShaderNodeUVMap"); uvm.uv_map = "pattern"
        img = N("ShaderNodeTexImage"); img.image = pattern; img.extension = "REPEAT"
        L(uvm.outputs[0], img.inputs[0])
        sep = N("ShaderNodeSeparateColor"); L(img.outputs[0], sep.inputs[0])
        mul = N("ShaderNodeMix"); mul.data_type = "RGBA"; mul.blend_type = "MULTIPLY"; mul.inputs[0].default_value = 1.0
        L(colour, mul.inputs[6]); L(sep.outputs[1], mul.inputs[7])
        colour = mul.outputs[2]
    L(colour, bsdf.inputs["Base Color"])
    rr = N("ShaderNodeMapRange")
    rr.inputs[3].default_value = max(.05, rough - .12); rr.inputs[4].default_value = min(1, rough + .2)
    L(ramp.outputs[0], rr.inputs[0])
    L(rr.outputs[0], bsdf.inputs["Roughness"])
    bsdf.inputs["Metallic"].default_value = metal
    bump = N("ShaderNodeBump")   # hammered (as much as «hammer» says; 0 polished) / grain
    bump.inputs["Strength"].default_value = 1.2 * float(spec.get("bump", .5)) if kind == "metal" else .55
    bump.inputs["Distance"].default_value = .02 * R
    L(vor.outputs["Distance"], bump.inputs["Height"])
    normal = bump.outputs[0]
    if pattern is not None:   # the rings' or the quilting's own relief over it
        b2 = N("ShaderNodeBump"); b2.inputs["Strength"].default_value = .9; b2.inputs["Distance"].default_value = .04 * unit
        L(sep.outputs[0], b2.inputs["Height"]); L(normal, b2.inputs["Normal"])
        normal = b2.outputs[0]
    L(normal, bsdf.inputs["Normal"])
    return m, metal


def bake(obj, mats, size, out_dir, item):
    """Each material's colour, roughness and normal into images, then plain image-based materials."""
    sc = bpy.context.scene
    try:
        sc.render.engine = "CYCLES"
    except TypeError:
        pass
    sc.cycles.samples = 4
    try:
        sc.cycles.device = "GPU"
    except (AttributeError, TypeError):
        pass
    bpy.ops.object.select_all(action="DESELECT")
    obj.select_set(True)
    bpy.context.view_layer.objects.active = obj
    imgs = {}
    for m, _ in mats:
        for kind, cs in (("color", "sRGB"), ("rough", "Non-Color"), ("normal", "Non-Color")):
            im = bpy.data.images.new(f"{item}_{m.name}_{kind}", size, size, alpha=False)
            im.colorspace_settings.name = cs
            imgs[(m.name, kind)] = im
    for kind, btype in (("color", "EMIT"), ("rough", "ROUGHNESS"), ("normal", "NORMAL")):
        for m, _ in mats:
            nt = m.node_tree
            node = nt.nodes.get("bake") or nt.nodes.new("ShaderNodeTexImage")
            node.name = "bake"
            node.image = imgs[(m.name, kind)]
            nt.nodes.active = node
            out = next(n for n in nt.nodes if n.type == "OUTPUT_MATERIAL")
            bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
            if kind == "color":   # the colour itself as emission: a metal's diffuse colour is black
                em = nt.nodes.get("bake_em") or nt.nodes.new("ShaderNodeEmission")
                em.name = "bake_em"
                nt.links.new(bsdf.inputs["Base Color"].links[0].from_socket, em.inputs[0])
                nt.links.new(em.outputs[0], out.inputs[0])
            else:
                nt.links.new(bsdf.outputs[0], out.inputs[0])
        bpy.ops.object.bake(type=btype, margin=4)
    for (mn, kind), im in imgs.items():
        im.filepath_raw = str(Path(out_dir) / f"{im.name}.png")
        im.file_format = "PNG"
        im.save()
    for m, metal in mats:   # rebuilt for the game: image textures into a Principled BSDF
        nt = m.node_tree
        for nd in list(nt.nodes):
            nt.nodes.remove(nd)
        N, L = nt.nodes.new, nt.links.new
        out = N("ShaderNodeOutputMaterial"); bsdf = N("ShaderNodeBsdfPrincipled"); L(bsdf.outputs[0], out.inputs[0])
        c = N("ShaderNodeTexImage"); c.image = imgs[(m.name, "color")]; L(c.outputs[0], bsdf.inputs["Base Color"])
        r = N("ShaderNodeTexImage"); r.image = imgs[(m.name, "rough")]; L(r.outputs[0], bsdf.inputs["Roughness"])
        nm = N("ShaderNodeTexImage"); nm.image = imgs[(m.name, "normal")]
        nmap = N("ShaderNodeNormalMap"); L(nm.outputs[0], nmap.inputs["Color"]); L(nmap.outputs[0], bsdf.inputs["Normal"])
        bsdf.inputs["Metallic"].default_value = metal


# ---------------------------------------------------------------- the mesh
kind = job.get("piece", "bracer")
sides = [x for x in job.get("sides") or [] if x in ("L", "R")] or ["C"]
item = job.get("item", kind)
mj = json.loads(Path(job["mesh"]).read_text(encoding="utf-8"))


def unpack(key, code):
    a = array(code)
    a.frombytes(base64.b64decode(mj[key]))
    if sys.byteorder != "little":
        a.byteswap()
    return a


V, N, F, M = unpack("v", "f"), unpack("n", "B"), unpack("f", "I"), unpack("m", "B")
UV, BI, BW = unpack("uv", "f"), unpack("bi", "H"), unpack("bw", "f")
if not N or not V:
    fail(_t("ag.no_geometry"))
co = [Vector((V[i], -V[i + 2], V[i + 1])) for i in range(0, len(V), 3)]   # glTF (Y up) -> Blender (Z up)
faces, k = [], 0
for n in N:
    faces.append(tuple(F[k:k + n]))
    k += n
mesh = bpy.data.meshes.new(f"Wear_{item}")
mesh.from_pydata(co, [], faces)
for p, m in zip(mesh.polygons, M):
    p.material_index = m
mesh.uv_layers.new(name="UVMap")   # the bake's own unwrap, made below
pat_uv = mesh.uv_layers.new(name="pattern")   # the editor's: rows along, the angle round (the mail's rings lie by it)
for lp in mesh.loops:
    pat_uv.data[lp.index].uv = (UV[2 * lp.vertex_index], UV[2 * lp.vertex_index + 1])
mesh.uv_layers.active = mesh.uv_layers["UVMap"]
mesh.uv_layers["UVMap"].active_render = True
obj = bpy.data.objects.new(f"Wear_{item}", mesh)
bpy.context.scene.collection.objects.link(obj)
# the editor's weights, by bone: its names are three.js's (whitespace to _, [ ] . : / dropped)
real = {re.sub(r"[\[\]\.:/]", "", re.sub(r"\s", "_", b.name)): b.name for b in arm.data.bones}
groups = {}
for vi in range(len(co)):
    for kk in range(4):
        w = BW[4 * vi + kk]
        if w <= 1e-4:
            continue
        nm = real.get(mj["bones"][BI[4 * vi + kk]])
        if nm is None:
            continue
        g = groups.get(nm) or obj.vertex_groups.new(name=nm)
        groups[nm] = g
        g.add([vi], w, "ADD")
bones = sorted(groups)
R = float(mj.get("radius") or .05)
bm = bmesh.new()
bm.from_mesh(mesh)
bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5 * R)   # a tube's seam: two columns of the same points
bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
bm.to_mesh(mesh)
bm.free()
for p in mesh.polygons:
    p.use_smooth = True
# the material slots the editor used (plates, leather, details, mail, quilting, trim): only those get a material and textures
used = sorted(set(M))
for p in mesh.polygons:
    p.material_index = used.index(p.material_index)
patterns = {}
for nm, png in (mj.get("patterns") or {}).items():
    if png and any(mj["mats"][u].get("pattern") == nm for u in used):
        pf = Path(job.get("work") or Path(job["out"]).parent) / f"pattern_{nm}.png"
        pf.write_bytes(base64.b64decode(png))
        patterns[nm] = bpy.data.images.load(str(pf))
        patterns[nm].colorspace_settings.name = "Non-Color"
SLOTS = ("plate", "strap", "detail", "mail", "quilt", "trim")
mats = [node_mat(f"{item}_{SLOTS[u]}", mj["mats"][u], R, patterns.get(mj["mats"][u].get("pattern")), float(mj.get("pattern_unit") or R))
        for u in used]
for m, _ in mats:
    mesh.materials.append(m)
bpy.context.view_layer.objects.active = obj
obj.select_set(True)
for mi in range(len(mats)):   # each material its own unwrap filling its own texture (rivets get more than a pixel)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="DESELECT")
    bpy.ops.object.mode_set(mode="OBJECT")
    for p in mesh.polygons:
        p.select = p.material_index == mi
    if not any(p.select for p in mesh.polygons):
        continue
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.uv.smart_project(angle_limit=math.radians(60), island_margin=.006)
    bpy.ops.object.mode_set(mode="OBJECT")
out_dir = Path(job["out"]).parent
out_dir.mkdir(parents=True, exist_ok=True)
tex_dir = Path(job.get("work") or out_dir) / f"{Path(job['out']).stem}_tex"   # the GLB embeds them; kept for a look
tex_dir.mkdir(parents=True, exist_ok=True)
bake(obj, mats, int(job.get("tex", 1024)), tex_dir, item)

mesh.uv_layers.remove(mesh.uv_layers["pattern"])   # baked in: the game gets the one unwrap
mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = arm
obj.parent = arm
obj.matrix_parent_inverse = arm.matrix_world.inverted()

# previews: the character with the piece, front and side, framed on it
sc = bpy.context.scene
pv = job.get("preview")
if pv:
    try:
        sc.render.engine = "BLENDER_EEVEE_NEXT"
    except TypeError:
        try:
            sc.render.engine = "BLENDER_EEVEE"
        except TypeError:
            pass
    sc.render.resolution_x, sc.render.resolution_y = 640, 640
    sc.world = sc.world or bpy.data.worlds.new("w")
    sc.world.use_nodes = True
    bg = next(n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs[0].default_value = (.55, .55, .58, 1)
    bg.inputs[1].default_value = .9
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), math.radians(10), math.radians(30))
    sc.collection.objects.link(sun)
    skin = bpy.data.materials.new("skin")   # the character in one plain colour: the piece is what is looked at
    skin.use_nodes = True
    sb = next(n for n in skin.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    sb.inputs["Base Color"].default_value = (.42, .45, .32, 1)
    sb.inputs["Roughness"].default_value = .7
    for o in bpy.data.objects:
        if o.type == "MESH" and o is not obj:
            o.data.materials.clear()
            o.data.materials.append(skin)
    pts = [obj.matrix_world @ v.co for v in mesh.vertices]
    hx = (arm.matrix_world @ arm.data.bones[names["hips"]].head_local).x
    one = [p for p in pts if p.x > hx] if len(sides) > 1 else pts   # the close-up: the left one
    cd = bpy.data.cameras.new("c"); cd.type = "ORTHO"
    cam = bpy.data.objects.new("c", cd); sc.collection.objects.link(cam); sc.camera = cam
    for vn, eye, P_, k in (("front", Vector((0, -1, .12)), pts, 1.25), ("side", Vector((1, -.35, .12)), pts, 1.25),
                           ("close", Vector((.55, -1, .25)), one, 1.1)):
        lo = Vector([min(p[i] for p in P_) for i in range(3)])
        hi = Vector([max(p[i] for p in P_) for i in range(3)])
        c, size = (lo + hi) / 2, max((hi - lo).length, 1e-6)
        cd.ortho_scale = k * size
        cd.clip_start, cd.clip_end = size * 1e-3, size * 100
        eye.normalize()
        cam.location = c + eye * 6 * size
        cam.rotation_euler = (-eye).to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = f"{pv}_{vn}.png"
        bpy.ops.render.render(write_still=True)

if job.get("mask"):   # what of the body the piece hides (the game takes it away while it is on: body_mask.py)
    from body_mask import body_mask
    Path(job["mask"]).write_text(json.dumps(body_mask(body, [obj])), encoding="utf-8")

for o in list(bpy.data.objects):   # the skeleton and the piece only
    if o.type == "MESH" and o is not obj:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4)
print("ARMOUR_GEN_OK " + json.dumps({"vertices": len(mesh.vertices), "bones": bones, "radius": round(R, 4),
                                     "sides": sides, "over_clothes": bool(mj.get("over_clothes"))}), flush=True)
