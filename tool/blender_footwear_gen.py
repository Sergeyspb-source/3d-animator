"""Runs INSIDE Blender (background): footwear of the «Equipment: procedural» editor, made by the footwear generators in
vendor/blender_armour/Footwear to the character's feet and put on them.

    blender -b -P blender_footwear_gen.py -- job.json

job.json: {"style": leather_shoe | ankle_boot | mail_foot | round_sabaton | pointed_sabaton | hybrid_boot,
           "sides": ["L", "R"], "params": {"gap": air round the foot, a share of its size}, "out": piece.glb,
           "work": a folder (the generator's textures), "character": rigged.glb, "names": {naming: {joint: bone}},
           "mask": mask.json}

The generator builds a man's right shoe, in metres, on one last: the ankle joint at the origin, the toe -Y, up +Z, the
sole's bottom at -ankle_height; at the sole the last reaches .206 forward of the ankle and .064 back, .050 to either
side; the shaft above the ankle is the last's profile too. Each foot is measured on the skin (its heel, its toes'
tip with the claws, its width and middle, the ground, the ankle's height) and the shoe is scaled to it along, across
and up, its toe along the foot, its sole on the ground; above the ankle the shaft is fitted round the leg at each
height. The left one is the right one mirrored, as the generator makes it. It moves with the foot, its toe with the
toes, its shaft more and more with the shin; steel goes whole with what it lies on. What it hides goes into the mask
(body_mask.py), each foot on its own. Prints ARMOUR_GEN_OK {json} (as blender_armour_gen.py).
"""
import importlib
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
VENDOR = HERE / "vendor" / "blender_armour"
sys.path.insert(0, str(HERE))
for folder in ("KettleHat", "HelmetVariants", "ElbowArmor", "Footwear"):
    sys.path.insert(0, str(VENDOR / folder))
from i18n import t as _t

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
style, prm = job["style"], job.get("params") or {}
sides = [s for s in job.get("sides") or ["L", "R"] if s in ("L", "R")] or ["L", "R"]
PARTS = ("Eye_", "EyeSocket", "Teeth_", "Gum_", "Tongue", "MouthCavity", "Icosphere")
SOLE = (.009, .206, .064, .050)   # footwear_last.PROFILE at the sole: height, forward, back, to either side (metres)
RIGID = ("Steel_", "Lame_Rivet")   # steel's weights: whole, by its middle


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
names = next((tbl for tbl in job["names"].values() if tbl.get("foot_L") in arm.data.bones), None)
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
gap = float(prm.get("gap", .06))


def bone(key):
    b = arm.data.bones.get(names.get(key, ""))
    return b


def foot(s):
    """A foot on the skin: {A: the ankle, fdir: along it (level), side: to its outside... its x axis, ground, heel and toe
    (along fdir from A), half width and the middle's offset (along side), the leg's round above the ankle}."""
    A = W @ bone(f"foot_{s}").head_local
    tb = bone(f"toe_{s}")
    T = W @ tb.head_local if tb else W @ bone(f"foot_{s}").tail_local
    fdir = Vector((T.x - A.x, T.y - A.y, 0)).normalized()
    up = Vector((0, 0, 1))
    xs = (-fdir).cross(up)   # the frame's +X (its -Y along the foot, +Z up)
    own = {b.name for b in (bone(f"foot_{s}"), tb) if b} | {b.name for b in bone(f"foot_{s}").children_recursive}
    pts = []
    for o in body:
        gi = {g.index: g.name for g in o.vertex_groups}
        for v in o.data.vertices:
            tot = sum(g.weight for g in v.groups)
            on = sum(g.weight for g in v.groups if gi[g.group] in own)
            if tot > 1e-9 and on / tot > .5:
                pts.append(o.matrix_world @ v.co)
    if not pts:
        fail(_t("ag.no_skin_around_the_limb"))
    ground = min(p.z for p in pts)
    along = [(p - A).dot(fdir) for p in pts]
    low = [p for p in pts if p.z < ground + .4 * (A.z - ground)]
    across = [(p - A).dot(xs) for p in low] or [0]
    # the skin round this foot (the ankle too: its own bones' vertices cover only part of it there)
    mid = A + fdir * ((min(along) + max(along)) / 2)
    reach = (max(along) - min(along)) * .75
    near = [q for q in verts if q.z < A.z + .3 * (A.z - ground) and (Vector((q.x - mid.x, q.y - mid.y, 0))).length < reach]
    return {"A": A, "K": W @ bone(f"leg_{s}").head_local, "fdir": fdir, "xs": xs, "ground": ground, "pts": near, "heel": min(along), "toe": max(along),
            "half_w": (max(across) - min(across)) / 2, "mid_x": (max(across) + min(across)) / 2}


def leg_round(f, z):
    """The leg at height z from a slice of the skin round the shin's bone line there (the line lies near the shin's
    front, may be outside it: rays from it miss): (its middle, its half depth front to back, its half width); None
    where too little of it is there."""
    A, K = f["A"], f["K"]
    q = A + (K - A) * ((z - A.z) / (K.z - A.z))
    band, reach = .012 * (K - A).length, .3 * (K - A).length
    sl = [v for v in verts if abs(v.z - z) < band and Vector((v.x - q.x, v.y - q.y, 0)).length < reach]
    if len(sl) < 12:
        return None
    al = [(v - q).dot(f["fdir"]) for v in sl]
    ac = [(v - q).dot(f["xs"]) for v in sl]
    mid = q + f["fdir"] * ((max(al) + min(al)) / 2) + f["xs"] * ((max(ac) + min(ac)) / 2)
    return Vector((mid.x, mid.y, z)), (max(al) - min(al)) / 2, (max(ac) - min(ac)) / 2


feet = {s: foot(s) for s in sides}

# ---------------------------------------------------------------- the generator's right shoe, in its own frame
cat = importlib.import_module("footwear_catalog")
last = importlib.import_module("footwear_last")
pair = importlib.import_module("footwear_pair")
make_materials = importlib.import_module("kettle_hat_details").make_materials
prepare_meshes = importlib.import_module("generate_kettle_hat").prepare_meshes
p = cat.validate_config(style, {})
bpy.ops.object.select_all(action="DESELECT")   # their mesh preparation unwraps whatever is selected
col = bpy.data.collections.new("Footwear")
bpy.context.scene.collection.children.link(col)
mats = make_materials(Path(job.get("work") or Path(job["out"]).parent) / f"{Path(job['out']).stem}_tex")
importlib.import_module("footwear_builders").build(style, p, mats, col)
prepare_meshes([o for o in col.objects if o.type in {"MESH", "CURVE"} and o.name != "FootMail_Rings"])
right = [o for o in col.objects if o.type == "MESH"]
pair.canonical_meshes(right, p)   # the ankle at the origin, the sole's bottom at -ankle_height
for o in list(col.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
ah = p["ankle_height"]
k_len = p["foot_length"] / .270
sole_front, sole_back, sole_side = SOLE[1] * k_len, SOLE[2] * k_len, SOLE[3] * p["foot_width"] / .100


def shaft_k(f, origin, sx, sy, sz, zf):
    """Above the ankle the shaft round the leg at the frame's height zf: (to the sides, front to back: factors of the
    last's reach there; the leg's middle in the frame, x and y; the last's own middle front to back); None where the
    leg is not found."""
    lr = leg_round(f, f["A"].z + zf * sz)
    if lr is None:
        return None
    mid, half_d, half_w = lr
    pf, pb, pw = last.profile(p, zf + ah)
    d = mid - Vector((origin.x, origin.y, mid.z))
    return (half_w * (1 + gap) / (sx * pw), half_d * (1 + gap) / (sy * (pf + pb) / 2),
            d.dot(f["xs"]) / sx, -d.dot(f["fdir"]) / sy, (pb - pf) / 2)


def foot_k(f, origin, sx, sy, sz, zf):
    """Below the ankle the shoe round the foot at the frame's height zf, from the foot's skin there (a slice): factors
    (to the sides, forward, back) of the last's reach there and the foot's middle to the sides in the frame; None where
    too little of the foot is there."""
    zw = f["A"].z + zf * sz
    band = .01 * sz
    sl = [q for q in f["pts"] if abs(q.z - zw) < band]
    if len(sl) < 12:
        return None
    al = [(q - origin).dot(f["fdir"]) for q in sl]
    ac = [(q - origin).dot(f["xs"]) for q in sl]
    pf, pb, pw = last.profile(p, max(.009, zf + ah))
    fwd, bk = max(al), -min(al)
    if fwd <= 0 or bk <= 0:
        return None
    lim = lambda k: clamp(k, .6, 1.5)
    return (lim((max(ac) - min(ac)) / 2 * (1 + gap) / (sx * pw)), lim(fwd * (1 + gap) / (sy * pf)), lim(bk * (1 + gap) / (sy * pb)),
            (max(ac) + min(ac)) / 2 / sx)


def curve(fn, zs, n):
    """fn at the frame's heights zs (tuples of n numbers, None where not found), smoothed along them: a function of the
    height (the slices are noisy: a bone's bump, a toe's claw, the calf)."""
    ks = [fn(z) for z in zs]
    good = [k for k in ks if k]
    if not good:
        return lambda z: None
    ks = [k or good[0] for k in ks]
    for _ in range(2):
        ks = [tuple((ks[max(0, i - 1)][j] + 2 * ks[i][j] + ks[min(len(ks) - 1, i + 1)][j]) / 4 for j in range(n)) for i in range(len(ks))]

    def at(z):
        t = clamp((z - zs[0]) / (zs[-1] - zs[0]), 0, 1) * (len(zs) - 1)
        i = min(len(zs) - 2, int(t))
        u = t - i
        return tuple(ks[i][j] * (1 - u) + ks[i + 1][j] * u for j in range(n))
    return at


def foot_curve(f, origin, sx, sy, sz):
    """foot_k from the sole to the ankle at ten heights, smoothed along them (the slices are noisy: a bone's bump, a
    toe's claw): a function of the frame's height."""
    zs = [-ah + p["sole_thickness"] + (ah - p["sole_thickness"]) * i / 9 for i in range(10)]
    return curve(lambda z: foot_k(f, origin, sx, sy, sz, z), zs, 4)


def shaft_curve(f, origin, sx, sy, sz):
    """shaft_k from the ankle to the shaft's top at ten heights, smoothed along them."""
    zs = [(p["shaft_height"] - ah + .01) * i / 9 for i in range(10)]
    return curve(lambda z: shaft_k(f, origin, sx, sy, sz, z), zs, 5)


def widen(obs, f, origin, sx, sy, sz):
    """Along the foot: at each stretch of it the shoe no narrower than the foot there and the gap (a goblin's toes
    spread wide where a last narrows to its toe), each side of the shoe's own middle there; below the ankle."""
    fp = [((q - origin).dot(f["xs"]) / sx, -(q - origin).dot(f["fdir"]) / sy) for q in f["pts"] if q.z < f["A"].z]
    sp = [(v.co.x, v.co.y) for o in obs for v in o.data.vertices if v.co.z < 0]
    if not fp or not sp:
        return
    y0, y1, nb = min(y for _, y in fp), max(y for _, y in fp), 16
    def b(y):
        return min(nb - 1, max(0, int((y - y0) / (y1 - y0) * nb)))
    fx, sx_ = [[] for _ in range(nb)], [[] for _ in range(nb)]
    for x, y in fp:
        fx[b(y)].append(x)
    for x, y in sp:
        if y0 <= y <= y1:
            sx_[b(y)].append(x)
    ks = []
    for i in range(nb):
        if fx[i] and sx_[i]:
            c = (min(sx_[i]) + max(sx_[i])) / 2
            need = max(c - min(fx[i]), max(fx[i]) - c) * (1 + gap)
            ks.append((max(1., need / max((max(sx_[i]) - min(sx_[i])) / 2, 1e-9)), c))
        else:
            ks.append((1., 0.))
    for _ in range(2):
        ks = [tuple((ks[max(0, i - 1)][j] + 2 * ks[i][j] + ks[min(nb - 1, i + 1)][j]) / 4 for j in range(2)) for i in range(nb)]
    for o in obs:   # steel too: the leather under it must not come out through it
        for v in o.data.vertices:
            t = clamp((v.co.y - y0) / (y1 - y0), 0, 1) * (nb - 1)
            i = min(nb - 2, int(t))
            u = t - i
            k = ks[i][0] * (1 - u) + ks[i + 1][0] * u
            c = ks[i][1] * (1 - u) + ks[i + 1][1] * u
            k = 1 + (k - 1) * (1 - smooth(-.01, .02, v.co.z))   # the foot only, not the shaft
            v.co.x = c + (v.co.x - c) * k


# ---------------------------------------------------------------- each side: mirrored for the left, fitted, weighted
parts, info = [], {}
for s in sides:
    f = feet[s]
    sy = (f["toe"] - f["heel"]) * (1 + gap) / (sole_front + sole_back)
    sx = f["half_w"] * (1 + gap) / sole_side
    sz = (f["A"].z - f["ground"]) / ah
    # the frame's origin: sole_back (scaled) in front of the heel (with half the gap behind it), the foot's middle to
    # the sides, at the ankle's height
    base = f["A"] + f["fdir"] * (f["heel"] - (f["toe"] - f["heel"]) * gap / 2 + sole_back * sy) + f["xs"] * f["mid_x"]
    origin = Vector((base.x, base.y, f["A"].z))
    R = Matrix((f["xs"], -f["fdir"], Vector((0, 0, 1)))).transposed().to_4x4()
    M = Matrix.Translation(origin) @ R @ Matrix.Diagonal((sx, sy, sz, 1))
    fit_foot = foot_curve(f, origin, sx, sy, sz)
    fit_shaft = shaft_curve(f, origin, sx, sy, sz)
    obs = []
    foot_b, toe_b, leg_b = names[f"foot_{s}"], names.get(f"toe_{s}"), names[f"leg_{s}"]
    toe_b = toe_b if toe_b in arm.data.bones else foot_b
    T = W @ arm.data.bones[toe_b].head_local
    y_toe = -((T - origin).dot(f["fdir"])) / sy   # the toes' joint in the frame
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
        # the shoe round the foot below the ankle (across, at each height), the shaft round the leg above it: one smooth
        # field for leather and steel alike, so what lies on what stays on it. Along the foot it is not changed with the
        # height (its length is the foot's already): the lames lie over one another at different heights, stretched
        # along each at its own they would cut through each other
        for vx in ob.data.vertices:
            zf = vx.co.z
            w = smooth(.0, .035, zf)
            if w < 1:
                k = fit_foot(zf)
                if k is not None:
                    kx, dx = k[0], k[3]
                    x = vx.co.x
                    vx.co.x = x + (dx + x * kx - x) * (1 - w)
            if w <= 0:
                continue
            k = fit_shaft(zf)
            if k is None:
                continue
            kx, ky, dx, dy, yc = k   # round the leg's own middle
            x, y = vx.co.x, vx.co.y
            vx.co.x = x + (dx + x * kx - x) * w
            vx.co.y = y + (dy + (y - yc) * ky - y) * w
        obs.append(ob)
    widen(obs, f, origin, sx, sy, sz)
    for ob in obs:
        # weights: the foot; the toe (soft parts by where they are, steel whole by its middle); the shaft to the shin
        ob.vertex_groups.clear()
        g_f, g_t, g_l = (ob.vertex_groups.new(name=n) for n in (foot_b, toe_b + ("" if toe_b != foot_b else "_"), leg_b))
        ys = [vx.co.y for vx in ob.data.vertices]
        zs = [vx.co.z for vx in ob.data.vertices]
        rigid = ob.name.startswith(RIGID)
        yc, zc = sum(ys) / len(ys), sum(zs) / len(zs)
        for vx in ob.data.vertices:
            y, z = (yc, zc) if rigid else (vx.co.y, vx.co.z)
            kl = smooth(.01, .06, z)   # the shin's share
            kt = (1 - kl) * smooth(y_toe + .02, y_toe - .02, y)   # the toes' share
            g_l.add([vx.index], kl, "REPLACE")
            g_t.add([vx.index], kt, "REPLACE")
            g_f.add([vx.index], 1 - kl - kt, "REPLACE")
        ob.data.transform(M)
        ob.data.update()
        parts.append((s, ob))
    info[s] = {"length": round(f["toe"] - f["heel"], 2), "half_width": round(f["half_w"], 2), "ankle": round(f["A"].z - f["ground"], 2),
               "scale": [round(sx, 1), round(sy, 1), round(sz, 1)]}
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


# what each foot hides, on its own (both together are as wide as the stance), kept in from the rims (the shaft turns
# with the shin)
keys = set()
if job.get("mask"):
    from body_mask import body_mask
    for s in sides:
        keys |= {tuple(x) for x in body_mask(body, [ob for x, ob in parts if x == s], erode=4)}
obj = join([ob for _, ob in parts])
obj.name = f"{style}_footwear"
for vg in [g for g in obj.vertex_groups if g.name.endswith("_")]:   # no toe bone: the foot's
    obj.vertex_groups.remove(vg)
for m in obj.data.materials:   # full metal looks black in a game scene without reflections (cf. armour_gen_ui.PRESETS)
    b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.use_nodes else None
    if b is not None and b.inputs["Metallic"].default_value > .7:
        b.inputs["Metallic"].default_value = .65
mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = arm
obj.parent = arm
obj.matrix_parent_inverse = arm.matrix_world.inverted()
if job.get("mask"):
    Path(job["mask"]).write_text(json.dumps([list(x) for x in sorted(keys)]), encoding="utf-8")

for o in list(bpy.data.objects):   # the skeleton and the footwear only
    if o.type == "MESH" and o is not obj:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4)
print("ARMOUR_GEN_OK " + json.dumps({"vertices": len(obj.data.vertices), "bones": sorted({names[f"{j}_{s}"] for s in sides for j in ("foot", "toe", "leg")}),
                                     "radius": max(v["half_width"] for v in info.values()), "sides": sides, "feet": info,
                                     "build": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}}), flush=True)
