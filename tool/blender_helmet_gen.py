"""Runs INSIDE Blender (background): a helmet of the «Equipment: procedural» editor, made by the helmet generators in
vendor/blender_armour (KettleHat, HelmetVariants) to the character's head and put on it.

    blender -b -P blender_helmet_gen.py -- job.json

job.json: {"style": kettle_hat | open_bascinet | barbute | visored_bascinet | sallet | armet,
           "params": {"gap": air over the head, a share of its half depth, "visor_angle", "cheek_angle" (degrees),
                      "tail": a sallet's tail, "brim": a kettle hat's brim, shares of their usual size},
           "out": piece.glb, "work": a folder (the generators' textures),
           "character": rigged.glb, "names": {naming: {joint: bone}}, "mask": mask.json}

The generators build for a human head, in metres, with fixed eye slits and rivets. The head is measured on the skin:
the eyes, its depth and width at the brow, its top, the chin (where the face's front goes back sharply), the neck and
the shoulders' top beside it. The helmet is built in its own proportions with the head's (width to depth, top over the
brow), scaled as one piece to it (its eye slits at the eyes, a kettle hat's brim at the brow); below the face it is
drawn up so it ends at the chin, not on the shoulders (a goblin's face is short and its neck shorter than a man's),
and an aventail hangs round the neck down to the shoulders' top, closing in to the neck (it covers the neck, it does
not fall on the chest). It moves with the head (an aventail's lower rings more and more with the neck). What it hides
goes into the mask (body_mask.py), and the ears with it: they would stick out through the sides or under a brim.
Prints ARMOUR_GEN_OK {json} (as blender_armour_gen.py).
"""
import importlib
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "vendor" / "blender_armour" / "HelmetVariants"))
sys.path.insert(0, str(HERE / "vendor" / "blender_armour" / "KettleHat"))
from i18n import t as _t

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
style, prm = job["style"], job.get("params") or {}
PARTS = ("Eye_", "EyeSocket", "Teeth_", "Gum_", "Tongue", "MouthCavity", "Icosphere")
EYE_Z = .041      # the eye slits' height in the HelmetVariants' frame (a barbute's T, a sallet's slit), metres
FACE_Z = .02      # below it (under the eye slits) a helmet is drawn up to the chin
BROW = .025       # a kettle hat's brim over the eyes, metres (it sits on the brow)
SNOUT = .03       # a visor out this far (the generators' .06 and .039 are long hounds' snouts)
RING = 72         # an aventail ring's vertices (helmet_mail: 12 x 6), one after another


def fail(msg):
    print("ARMOUR_GEN_FAIL " + msg, flush=True)
    sys.exit(1)


def clamp(x, lo, hi):
    return max(lo, min(hi, x))


def smooth(a, b, x):
    t = clamp((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.unit_settings.system = "METRIC"

# ---------------------------------------------------------------- the character, its head measured
bpy.ops.import_scene.gltf(filepath=job["character"])
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    fail(_t("blender.the_character_has_no_skeleton_build"))
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
body = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups and not o.name.startswith(PARTS)]
names = next((tbl for tbl in job["names"].values() if tbl.get("head") in arm.data.bones), None)
if not body or names is None:
    fail(_t("ag.bones_not_recognised"))
W = arm.matrix_world
head_b = arm.data.bones[names["head"]]
neck_b = arm.data.bones.get(names.get("neck", ""))
head_bones = {head_b.name} | {b.name for b in head_b.children_recursive}

verts, polys = [], []
for o in body:
    k = len(verts)
    verts += [o.matrix_world @ v.co for v in o.data.vertices]
    polys += [tuple(k + i for i in f.vertices) for f in o.data.polygons]
tree = BVHTree.FromPolygons(verts, polys)
H = max(v.z for v in verts) - min(v.z for v in verts)


def hit(org, d, far):
    h = tree.ray_cast(org, Vector(d), far)
    return h[3] if h[0] is not None else None


J = W @ head_b.head_local
top0 = hit(J, (0, 0, 1), H)
eyes = [W @ arm.data.bones[names[f"eye_{s}"]].head_local for s in "LR" if names.get(f"eye_{s}") in arm.data.bones]
if len(eyes) < 2:   # the eyes' own meshes
    eyes = [sum((o.matrix_world @ v.co for v in o.data.vertices), Vector()) / len(o.data.vertices)
            for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("Eye_") and len(o.data.vertices)]
E = sum(eyes, Vector()) / len(eyes) if len(eyes) >= 2 else J + Vector((0, 0, .4 * (top0 or .2 * H)))
C = Vector((E.x, J.y, E.z))   # on the head's upright axis, at the eyes
top = hit(C, (0, 0, 1), H)
if top is None:
    fail(_t("ag.no_skin_around_the_limb"))
fronts, backs, wides = [], [], []
for k in (.1, .2, .3, .4):   # the brow and the forehead (eyes to top: top)
    q = C + Vector((0, 0, k * top))
    f, b = hit(q, (0, -1, 0), H), hit(q, (0, 1, 0), H)
    xr, xl = hit(q, (1, 0, 0), H), hit(q, (-1, 0, 0), H)
    if f and b:
        fronts.append(f)
        backs.append(b)
    if xr and xl:
        wides.append((xr + xl) / 2)
if not fronts or not wides:
    fail(_t("ag.no_skin_around_the_limb"))
front, back = max(fronts), max(backs)
half_d = (front + back) / 2
half_w = sorted(wides)[len(wides) // 2]
centre = Vector((C.x, C.y + (back - front) / 2, C.z))

# the chin: going down the face's front from the eyes, where it goes back sharply (to the throat)
step, far = half_d / 20, 4 * half_d
chin, prev = None, None
z = E.z
while z > E.z - 2.5 * half_d:
    h = tree.ray_cast(Vector((E.x, centre.y - far, z)), Vector((0, 1, 0)), 2 * far)
    y = h[0].y if h[0] is not None else None
    if prev is not None and y is not None and y - prev > .25 * half_d:
        chin = z + step
        break
    prev, z = y, z - step
if chin is None:   # the jaw's end, else a man's proportions
    jaw = arm.data.bones.get(names.get("jaw", ""))
    chin = (W @ jaw.tail_local).z if jaw else E.z - 1.2 * half_d
# the shoulders' top beside the neck, and the neck's round under the chin
shoulder = max((W @ arm.data.bones[names[f"shoulder_{s}"]].head_local).z for s in "LR"
               if names.get(f"shoulder_{s}") in arm.data.bones) if names.get("shoulder_L") in arm.data.bones else chin - half_d
for sx in (1.25, -1.25):
    h = tree.ray_cast(Vector((E.x + sx * half_w, J.y, chin)), Vector((0, 0, -1)), H)
    if h[0] is not None:
        shoulder = max(shoulder, h[0].z)
N0 = (W @ neck_b.head_local) if neck_b else J
zn = (chin + shoulder) / 2
nf, nb = hit(Vector((N0.x, N0.y, zn)), (0, -1, 0), H), hit(Vector((N0.x, N0.y, zn)), (0, 1, 0), H)
nr, nl = hit(Vector((N0.x, N0.y, zn)), (1, 0, 0), H), hit(Vector((N0.x, N0.y, zn)), (-1, 0, 0), H)
if nf and nb and nr and nl:   # its middle and its round
    neck_c = Vector((N0.x + (nr - nl) / 2, N0.y + (nb - nf) / 2, zn))
    neck_r = ((nf + nb) / 2 + (nr + nl) / 2) / 2
else:
    neck_c, neck_r = Vector((N0.x, N0.y, zn)), .5 * half_w
gap = float(prm.get("gap", .07)) * half_d


# ---------------------------------------------------------------- the generator's helmet
def build(dims):
    """The generator's helmet for dims {rx, ry, height} (metres). Returns (root, the parameters used, the root's
    height under the eyes in metres)."""
    tex = Path(job.get("work") or Path(job["out"]).parent) / f"{Path(job['out']).stem}_tex"
    if style == "kettle_hat":
        K = importlib.import_module("generate_kettle_hat")
        cfg = {"crown_radius_x": clamp(dims["rx"], .075, .15), "crown_radius_y": clamp(dims["ry"], .085, .17),
               "crown_height": clamp(dims["height"], .09, .22),
               "brim_width": clamp(K.DEFAULTS["brim_width"] * float(prm.get("brim", 1)), .02, .10)}
        p = K.validate_config(cfg)
        root, _ = K.build(p, tex)
        return root, p, -BROW
    G = importlib.import_module("generate_helmet")
    base = {**G.DEFAULTS, **G.STYLES[style]}
    cfg = {"rx": clamp(dims["rx"], *G.BOUNDS["rx"]), "ry": clamp(dims["ry"], *G.BOUNDS["ry"]),
           "height": clamp(dims["height"], *G.BOUNDS["height"])}
    if style in ("visored_bascinet", "armet"):
        cfg["visor_angle"] = clamp(float(prm.get("visor_angle", 0)), 0, 65)
    if style in ("visored_bascinet", "armet"):
        cfg["visor_projection"] = SNOUT
    if style == "armet":
        cfg["cheek_angle"] = clamp(float(prm.get("cheek_angle", 0)), 0, 35)
    if style == "sallet":
        cfg["tail_length"] = clamp(base["tail_length"] * float(prm.get("tail", 1)), 0, .11)
    p = G.validate_config(style, cfg)
    root, _ = G.build(style, p, tex)
    return root, p, EYE_Z


def _under(o, root):
    while o.parent is not None:
        if o.parent is root:
            return True
        o = o.parent
    return False


def flatten(root):
    """The helmet's meshes (the visor's and the cheeks' too, turned on their pivots) baked where they are in its own
    frame; the pivots and the root go."""
    bpy.context.view_layer.update()
    kids = [o for o in bpy.data.objects if o.type == "MESH" and _under(o, root)]
    for o in kids:
        mw = o.matrix_world.copy()
        o.parent = None
        o.data.transform(mw)
        o.matrix_world.identity()
    for o in [o for o in bpy.data.objects if o.type == "EMPTY" and (o is root or _under(o, root))]:
        bpy.data.objects.remove(o, do_unlink=True)
    return kids


# the build's metres per the character's unit: its depth to the head's
if style == "kettle_hat":
    ry_m = importlib.import_module("generate_kettle_hat").DEFAULTS["crown_radius_y"]
else:
    G = importlib.import_module("generate_helmet")
    ry_m = {**G.DEFAULTS, **G.STYLES[style]}["ry"]
s = (half_d + gap) / ry_m
if style == "kettle_hat":   # the brim at the brow, the crown over the rest of the head
    base_z = E.z + BROW * s
    dims = {"rx": (half_w + gap) / s, "ry": ry_m, "height": (E.z + top - base_z + gap) / s}
else:
    base_z = E.z - EYE_Z * s
    dims = {"rx": (half_w + gap) / s, "ry": ry_m, "height": (E.z + top - base_z + gap) / s - {**G.DEFAULTS, **G.STYLES[style]}["brow_z"]}
bpy.ops.object.select_all(action="DESELECT")   # their mesh preparation unwraps whatever is selected
root, p, eye_z = build(dims)
parts = flatten(root)


def frame_z(z_world):   # a height on the character in the helmet's frame (metres)
    return (z_world - base_z) / s


# below the face, drawn up to end just under the chin (the generators reach a man's neck: here the shoulders)
squeeze = 1.0
if style != "kettle_hat":
    shell = [o for o in parts if not o.name.startswith(("Aventail_Rings", "Chinstrap", "Buckle"))]
    low = min(v.co.z for o in shell for v in o.data.vertices)
    target = frame_z(chin) - .006
    if low < target < FACE_Z:
        squeeze = clamp((target - FACE_Z) / (low - FACE_Z), .35, 1)
    for o in parts:
        if o.name.startswith("Aventail_Rings"):
            continue
        for v in o.data.vertices:
            if v.co.z < FACE_Z:
                v.co.z = FACE_Z + (v.co.z - FACE_Z) * squeeze

# an aventail: from where it hangs (drawn up with the helmet) down to the shoulders' top, closing in round the neck;
# in front it goes across from the leather carrier's ends (at the visor's lower back corners) before the neck, behind
# the visor, not out under its snout; each ring moved whole (its shape kept)
CARRIER = .97   # the carrier's ends, radians from the front (visored_bascinet.build)
for o in [o for o in parts if o.name.startswith("Aventail_Rings")]:
    me = o.data
    n = len(me.vertices) // RING
    cs = [sum((me.vertices[r * RING + i].co for i in range(RING)), Vector()) / RING for r in range(n)]
    z1, z0 = max(c.z for c in cs), min(c.z for c in cs)
    z1n = FACE_Z + (z1 - FACE_Z) * squeeze if z1 < FACE_Z else z1
    z0n = min(z1n - .02, frame_z(shoulder) + .004)
    r0 = sum(c.xy.length for c in cs if c.z < z0 + 1e-4) / max(1, sum(1 for c in cs if c.z < z0 + 1e-4))
    rn = 1.35 * neck_r / s   # the bottom row: round the neck, a little loose
    nc = Vector(((neck_c.x - centre.x) / s, (neck_c.y - centre.y) / s))   # the neck's middle in the helmet's frame
    y_end = -p["ry"] * 1.01 * math.cos(CARRIER)   # the carrier's ends: the front goes no further out than across them
    for r, c in enumerate(cs):
        t = (z1 - c.z) / max(z1 - z0, 1e-9)
        w = smooth(0, 1, t)
        k = 1 + (min(1.0, rn / max(r0, 1e-9)) - 1) * w   # closing in going down, round the neck
        to = Vector((c.x * k + nc.x * w, c.y * k + nc.y * w, z1n + (z0n - z1n) * t))
        if to.y < y_end:
            to.y = y_end + (to.y - y_end) * .3
        d = to - c
        for i in range(RING):
            me.vertices[r * RING + i].co += d
    me.update()

# to the character: scaled, at the head
M = Matrix.Translation((centre.x, centre.y, base_z)) @ Matrix.Scale(s, 4)
for o in parts:
    o.data.transform(M)
    o.data.update()

# ---------------------------------------------------------------- one object, on the head (an aventail down to the neck)
for o in parts:
    o.vertex_groups.clear()
    gh = o.vertex_groups.new(name=head_b.name)
    gn = o.vertex_groups.new(name=neck_b.name) if neck_b else None
    zs = [v.co.z for v in o.data.vertices]
    ring = o.name.startswith("Aventail") and gn is not None and zs
    z1, z0 = (max(zs), min(zs)) if ring else (0, 0)
    for v in o.data.vertices:
        k = .65 * clamp((z1 - v.co.z) / max(z1 - z0, 1e-9), 0, 1) if ring else 0   # lower, more with the neck
        gh.add([v.index], 1 - k, "REPLACE")
        if k > 0:
            gn.add([v.index], k, "REPLACE")
bpy.ops.object.select_all(action="DESELECT")
for o in parts:
    o.select_set(True)
bpy.context.view_layer.objects.active = parts[0]
if len(parts) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
obj.name = f"{style}_helmet"
for m in obj.data.materials:   # full metal looks black in a game scene without reflections (cf. armour_gen_ui.PRESETS)
    b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.use_nodes else None
    if b is not None and b.inputs["Metallic"].default_value > .7:
        b.inputs["Metallic"].default_value = .65
mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = arm
obj.parent = arm
obj.matrix_parent_inverse = arm.matrix_world.inverted()

if job.get("mask"):   # what it hides, the ears too
    from body_mask import above, body_mask, ears
    keys = {tuple(x) for x in body_mask(body, [obj])}
    keys |= {tuple(x) for x in ears(body, head_bones, centre, half_w, J.z, E.z + top, out=1.0)}   # past the skull's side
    keys |= {tuple(x) for x in above(body, head_bones, E.z + .25 * top)}   # over the brow: hair, a hat, under the helmet
    Path(job["mask"]).write_text(json.dumps([list(x) for x in sorted(keys)]), encoding="utf-8")

for o in list(bpy.data.objects):   # the skeleton and the helmet only
    if o.type == "MESH" and o is not obj:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4)
print("ARMOUR_GEN_OK " + json.dumps({"vertices": len(obj.data.vertices), "bones": [head_b.name] + ([neck_b.name] if neck_b else []),
                                     "radius": round(half_d, 4), "sides": [], "scale": round(s, 4), "squeeze": round(squeeze, 3),
                                     "head": {"half_width": round(half_w, 3), "half_depth": round(half_d, 3), "eyes_to_top": round(top, 3),
                                              "chin": round(chin, 3), "shoulder": round(shoulder, 3), "neck": round(neck_r, 3)},
                                     "build": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}}), flush=True)
