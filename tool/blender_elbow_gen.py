"""Runs INSIDE Blender (background): elbow armour of the «Equipment: procedural» editor, made by the elbow generators in
vendor/blender_armour/ElbowArmor to the character's arms and put on them.

    blender -b -P blender_elbow_gen.py -- job.json

job.json: {"style": leather | mail | early_plate | winged_plate | articulated_plate | plate_mail_hybrid,
           "sides": ["L", "R"], "params": {"gap": air over the arm, a share of its radius, "wing": the wing's size, a
           share of the style's}, "out": piece.glb, "work": a folder (the generator's textures),
           "character": rigged.glb, "names": {naming: {joint: bone}}, "mask": mask.json}

The generator builds an elbow of a man's arm, in metres, about the elbow joint: up the upper arm +Z, its cup out to
the elbow's point -Y, the crook +Y, a right one's wing +X; the arm's middle at y .008 (its straps, its mail sleeve
round it). Each arm is measured on the skin at its elbow (the middle of its round across the arm, and its radius);
the elbow is scaled as one piece to it (its arm radius to the arm's and the gap), its +Z along the upper arm, its cup
to the elbow's point (away from the bend; for an arm straight at rest, backwards), so a right one's wing goes to the
outside; the left one is the right one mirrored, as the generator makes it. The upper strap and lames move with the
upper arm, the lower ones with the forearm, the cup half with each (it rides on the joint), mail from one to the
other. What it hides goes into the mask (body_mask.py). Prints ARMOUR_GEN_OK {json} (as blender_armour_gen.py).
"""
import importlib
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Quaternion, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor" / "blender_armour"
sys.path.insert(0, str(HERE))
for folder in ("KettleHat", "HelmetVariants", "ElbowArmor"):
    sys.path.insert(0, str(VENDOR / folder))
from i18n import t as _t

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
style, prm = job["style"], job.get("params") or {}
sides = [s for s in job.get("sides") or ["L", "R"] if s in ("L", "R")] or ["L", "R"]
PARTS = ("Eye_", "EyeSocket", "Teeth_", "Gum_", "Tongue", "MouthCavity", "Icosphere")
AXIS_Y = .008     # the arm's middle in the generator's frame (its straps and sleeve: elbow_fittings, elbow_builders)
SOFT = ("Mail_Rings", "Textile_Sleeve", "Mail_Edge", "Mail_Seam", "Gusset", "Internal_Leather")   # from the upper arm to the forearm
CUP = ("Steel_Couter", "Formed_Leather", "Padded_Liner", "Cup_Rivet", "Leather_Stitches")   # the cup and what is on it: half each
HUG = ("Upper_Strap", "Lower_Strap", *SOFT)   # round the arm (elbow_fittings.fastening_band, the sleeve)
STRAP_THICK = 2.0   # the generator's straps are 2 mm on a man (here a little over 1): twice that
STRAP_AIR = .06     # and off the arm by that much more of its radius than the rest (2 mm on a goblin's)


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
bpy.ops.import_scene.gltf(filepath=job["character"])
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    fail(_t("blender.the_character_has_no_skeleton_build"))
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
body = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups and not o.name.startswith(PARTS)]
names = next((tbl for tbl in job["names"].values() if tbl.get("forearm_L") in arm.data.bones), None)
if not body or names is None:
    fail(_t("ag.bones_not_recognised"))
W = arm.matrix_world
verts, polys = [], []
for o in body:
    k = len(verts)
    verts += [o.matrix_world @ v.co for v in o.data.vertices]
    polys += [tuple(k + i for i in f.vertices) for f in o.data.polygons]
tree = BVHTree.FromPolygons(verts, polys)
H = max(v.z for v in verts) - min(v.z for v in verts)


def elbow(s):
    """The arm at its elbow: (the middle of its round, its radius across (to the sides) and front to back, how far
    out the elbow's point is from the middle, up the upper arm, to the elbow's point)."""
    A = W @ arm.data.bones[names[f"arm_{s}"]].head_local
    E = W @ arm.data.bones[names[f"forearm_{s}"]].head_local
    Hd = W @ arm.data.bones[names[f"hand_{s}"]].head_local
    u = (A - E).normalized()
    f = (Hd - E).normalized()
    bend = u + f   # straight: none; bent: toward the crook
    if bend.length > .15:
        o = -(bend - u * bend.dot(u)).normalized()
    else:   # straight at rest: the elbow's point is behind (the character faces -Y)
        back = Vector((0, 1, 0))
        o = (back - u * back.dot(u)).normalized()
    v = u.cross(o)
    dirs = [(o * math.cos(a) + v * math.sin(a)) for a in (math.tau * k / 16 for k in range(16))]
    far = .5 * (A - E).length
    hits = []
    for d in dirs:
        h = tree.ray_cast(E, d, far)
        hits.append(h[3] if h[0] is not None else None)
    pairs = [(hits[k], hits[k + 8]) for k in range(8) if hits[k] and hits[k + 8]]
    if not pairs:
        fail(_t("ag.no_skin_around_the_limb"))
    shift = Vector()   # the middle: for opposite pairs evenly round, twice their half differences' mean
    for k in range(8):
        if hits[k] and hits[k + 8]:
            shift += dirs[k] * ((hits[k] - hits[k + 8]) / 2)
    c = E + shift * (2 / len(pairs))

    def out(d):
        h = tree.ray_cast(c, d, far)
        return h[3] if h[0] is not None else None
    point, crook, rs, ls = out(o), out(-o), out(v), out(-v)
    r = sorted((a + b) / 2 for a, b in pairs)[len(pairs) // 2]
    across = (rs + ls) / 2 if rs and ls else r
    fore_aft = (point + crook) / 2 if point and crook else r

    def round_at(h):   # the arm's mean radius h along it from the elbow (up the upper arm +, down the forearm -)
        q = c + (u if h > 0 else f) * abs(h)
        rr = [tree.ray_cast(q, d, far) for d in (o, -o, v, -v)]
        rr = [x[3] for x in rr if x[0] is not None]
        return sum(rr) / len(rr) if len(rr) == 4 else (across + fore_aft) / 2
    return c, across, fore_aft, point or fore_aft, u, o, round_at


# ---------------------------------------------------------------- the generator's right elbow, in its own frame
cat = importlib.import_module("elbow_catalog")
gen = importlib.import_module("generate_elbow")
make_materials = importlib.import_module("kettle_hat_details").make_materials
prepare_meshes = importlib.import_module("generate_kettle_hat").prepare_meshes
base = {**cat.DEFAULTS, **cat.VARIANTS[style]}
gap = float(prm.get("gap", .08))
arms = {s: elbow(s) for s in sides}


def scales(a):
    """The frame to the world across and front to back: the cup's rim a little wider than the arm (a man's elbow is
    wider than his arm, a goblin's is not), front to back the generator's arm (.82 of its radius: its straps, its
    sleeve) to this one."""
    return 1.12 * a[1] * (1 + gap) / base["half_width"], a[2] * (1 + gap) / (.82 * base["arm_radius"])


# the cup as deep as this elbow's point is out behind the arm's middle (the generator's is a man's), and the gap; its
# top inside at .006 - depth - point (elbow_geometry.cup_point), the arm's middle at .008
need = max(a[3] * (1 + gap) / scales(a)[1] for a in arms.values())
cfg = {"depth": clamp(need - AXIS_Y + .006 - base["point"], *cat.BOUNDS["depth"])} if style != "mail" else {}
if base["wing_width"] > 0:
    cfg["wing_width"] = clamp(base["wing_width"] * float(prm.get("wing", 1)), *cat.BOUNDS["wing_width"])
p = cat.validate_config(style, cfg)
bpy.ops.object.select_all(action="DESELECT")   # their mesh preparation unwraps whatever is selected
col = bpy.data.collections.new("Elbow_Armour")
bpy.context.scene.collection.children.link(col)
mats = make_materials(Path(job.get("work") or Path(job["out"]).parent) / f"{Path(job['out']).stem}_tex")
importlib.import_module("elbow_builders").build(style, p, mats, col)
prepare_meshes([o for o in col.objects if o.type in {"MESH", "CURVE"} and o.name != "Mail_Rings"])
right = [o for o in col.objects if o.type == "MESH"]
gen.canonical_meshes(right)
for o in list(col.objects):   # its own empties (none expected), the meshes only
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
hh = p["half_height"]
# the lames' inside likewise (their ellipse 1 x .9 of the arm's radius about y .006; the further ones narrower)
LAME_IN = min([math.hypot(v.co.x / p["arm_radius"], (v.co.y - .006) / (.9 * p["arm_radius"])) for o in right if o.name.startswith("Lame_")
               for v in o.data.vertices] or [1])
# the straps' inside (the least of their ellipse's measure: the generator's solidify goes in from it)
STRAP_IN = {n: min(math.hypot(v.co.x / p["arm_radius"], (v.co.y - .002) / (.82 * p["arm_radius"])) for v in o.data.vertices)
            for n in ("Upper_Strap", "Lower_Strap") for o in right if o.name == n}

# ---------------------------------------------------------------- each side: mirrored for the left, weighted, onto the arm
parts, info = [], {}
for s in sides:
    c, r_x, r_y, point, u, o, round_at = arms[s]
    sx, sy = scales(arms[s])
    sz = (sx + sy) / 2
    # the straps' heights: the arm there is thicker or thinner than at the joint; the cup opens out with it round the
    # arm's middle (more and more from the joint to them), the straps and mail go round it there, the gap off it
    hs = .52 * p["half_height"]
    r0 = (r_x + r_y) / 2
    hl = .72 * p["half_height"] + .028   # the lames' middle (elbow_geometry.lame)
    r_up, r_lo = round_at(hs * sz), round_at(-hs * sz)
    r_up2, r_lo2 = round_at(hl * sz), round_at(-hl * sz)
    k_up, k_lo = r_up / r0, r_lo / r0

    def round_z(z):   # the arm's round at the frame's height z: at the joint, the straps, the lames
        a, b = (r_up, r_up2) if z > 0 else (r_lo, r_lo2)
        z = abs(z)
        return r0 + (a - r0) * smooth(0, hs, z) if z < hs else a + (b - a) * smooth(hs, hl, z)

    def hug_k(z, ex, ey, g=gap):   # a strap's, a lame's or the mail's round at height z (the generator's: ex, ey of its radius) to the arm's
        rh = round_z(z)
        return rh * (1 + g) / (sx * ex * p["arm_radius"]), rh * (1 + g) / (sy * ey * p["arm_radius"])

    def cup_k(z):   # the cup opens out with the arm round its middle, never in: it keeps its round over the elbow
        return max(1., 1 + ((k_up if z > 0 else k_lo) - 1) * smooth(0, hs, abs(z)))
    Yf, Zf = -o, u
    Xf = Yf.cross(Zf)
    R = Matrix((Xf, Yf, Zf)).transposed().to_4x4()   # columns: the frame's axes in the world
    origin = c + AXIS_Y * sy * o   # the frame's (0, .008) is the arm's middle
    M = Matrix.Translation(origin) @ R @ Matrix.Diagonal((sx, sy, sz, 1))
    up_b, lo_b = names[f"arm_{s}"], names[f"forearm_{s}"]
    E0 = W @ arm.data.bones[lo_b].head_local
    fw = ((W @ arm.data.bones[names[f"hand_{s}"]].head_local) - E0).normalized()
    bend_q = (-u).rotation_difference(fw)
    for src in right:
        ob = src.copy()
        ob.data = src.data.copy()
        col.objects.link(ob)
        if s == "L":   # the left one: the right one mirrored (x), its faces turned back out
            for vx in ob.data.vertices:
                vx.co.x *= -1
            bm = bmesh.new()
            bm.from_mesh(ob.data)
            bmesh.ops.reverse_faces(bm, faces=list(bm.faces))
            bm.to_mesh(ob.data)
            bm.free()
        strap = next((x for x in ("Upper_Strap", "Lower_Strap") if src.name.startswith(x)), None)
        lame = src.name.startswith("Lame_")
        hug = src.name.startswith(HUG)
        ex, ey, yc = (1, .82, .002) if strap else (1, .9, .006) if lame else (.94, .82, AXIS_Y)   # elbow_fittings.fastening_band, elbow_geometry.lame, the sleeve
        rm = p["arm_radius"]
        for vx in ob.data.vertices:
            x, y, z = vx.co
            if strap:
                # a strap: twice as thick (its inside where it was), off the arm a little more than the rest; in front
                # (the crook) round the arm, at the sides and behind (its rivets, inside the cup) with the cup
                nx, ny = x / (ex * rm), (y - yc) / (ey * rm)
                e = math.hypot(nx, ny)
                e_in = STRAP_IN[strap]
                t = (e_in + (e - e_in) * STRAP_THICK) / e if e > 1e-9 else 1
                x, y = x * t, yc + (y - yc) * t
                hx, hy = hug_k(z, ex * e_in, ey * e_in, gap + STRAP_AIR)
                kc = cup_k(z)
                w = smooth(0, .5, ny / max(e, 1e-9))
                vx.co.x = x * (w * hx + (1 - w) * kc)
                vx.co.y = yc + (y - yc) * (w * hy + (1 - w) * kc)
            elif lame:   # a lame lies on the arm (its rivets with it), the further ones a little narrower, as made
                hx, hy = hug_k(z, ex * LAME_IN, ey * LAME_IN, gap + STRAP_AIR)
                vx.co.x = x * hx
                vx.co.y = yc + (y - yc) * hy
            elif src.name.startswith("Internal_Leather"):   # from inside the cup out onto the arm at the lames
                w = smooth(.65 * hh, hh, abs(z))
                hx, hy = hug_k(z, ex * LAME_IN, ey * LAME_IN, gap + STRAP_AIR)
                k = cup_k(z)
                vx.co.x = x * (w * hx + (1 - w) * k)
                vx.co.y = yc + (y - yc) * (w * hy + (1 - w) * k)
            elif hug:   # the mail round the arm
                kx, ky = hug_k(z, ex, ey)
                vx.co.x = x * kx
                vx.co.y = yc + (y - yc) * ky
            else:
                k = cup_k(z)
                vx.co.x = x * k
                vx.co.y = AXIS_Y + (y - AXIS_Y) * k
        zs = [vx.co.z for vx in ob.data.vertices]
        soft = src.name.startswith(SOFT)
        across = min(zs) < -.3 * hh and max(zs) > .3 * hh
        zc = sum(zs) / max(1, len(zs))
        ob.vertex_groups.clear()
        gu, gl = ob.vertex_groups.new(name=up_b), ob.vertex_groups.new(name=lo_b)
        for vx in ob.data.vertices:
            if soft:
                k = smooth(.5 * hh, -.5 * hh, vx.co.z)   # the forearm's share
            elif src.name.startswith(CUP) or across:
                k = .5   # it rides on the joint
            else:
                k = 0. if zc > 0 else 1.
            gu.add([vx.index], 1 - k, "REPLACE")
            gl.add([vx.index], k, "REPLACE")
        zf = [vx.co.z for vx in ob.data.vertices]
        ob.data.transform(M)
        # the lower half turned onto the forearm: the frame's -Z goes on along the upper arm, the forearm bends off it
        # (an arm a little bent at rest), more and more from the joint to the lower strap
        for vx, z in zip(ob.data.vertices, zf):
            if z < 0:
                qw = Quaternion().slerp(bend_q, smooth(0, hs, -z))
                vx.co = c + qw @ (vx.co - c)
        ob.data.update()
        parts.append((s, ob, hug))
    info[s] = {"radius": round(r0, 3), "scale": [round(sx, 2), round(sy, 2)], "point": round(point, 3), "straps": [round(k_up, 2), round(k_lo, 2)]}
for src in right:
    bpy.data.objects.remove(src, do_unlink=True)



def join(obs):
    bpy.ops.object.select_all(action="DESELECT")
    for ob in obs:
        ob.select_set(True)
    bpy.context.view_layer.objects.active = obs[0]
    if len(obs) > 1:
        bpy.ops.object.join()
    return bpy.context.view_layer.objects.active


# what each elbow hides is measured on its own (both together are as wide as the shoulders, and body_mask's distances
# are shares of a piece's size), on its cup and plates only: the straps lie on the skin and slide off it as the arm
# bends (the skin under them would show as holes), the mail is open; and kept in from the cup's rim
keys = set()
if job.get("mask"):
    from body_mask import body_mask
    for s in sides:
        keys |= {tuple(x) for x in body_mask(body, [ob for x, ob, h in parts if x == s and not h], erode=3)}   # the cup turns half with the forearm
obj = join([ob for _, ob, _ in parts])
obj.name = f"{style}_elbows"
for m in obj.data.materials:   # full metal looks black in a game scene without reflections (cf. armour_gen_ui.PRESETS)
    b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.use_nodes else None
    if b is not None and b.inputs["Metallic"].default_value > .7:
        b.inputs["Metallic"].default_value = .65
mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = arm
obj.parent = arm
obj.matrix_parent_inverse = arm.matrix_world.inverted()

if job.get("mask"):   # what it hides
    Path(job["mask"]).write_text(json.dumps([list(x) for x in sorted(keys)]), encoding="utf-8")

for o in list(bpy.data.objects):   # the skeleton and the elbows only
    if o.type == "MESH" and o is not obj:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4)
print("ARMOUR_GEN_OK " + json.dumps({"vertices": len(obj.data.vertices), "bones": sorted({names[f"{j}_{s}"] for s in sides for j in ("arm", "forearm")}),
                                     "radius": max(v["radius"] for v in info.values()), "sides": sides, "arms": info,
                                     "build": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}}), flush=True)
