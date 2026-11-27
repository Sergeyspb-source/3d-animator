"""Runs INSIDE Blender (background): footwear of the «Equipment: procedural» editor, made by the footwear generators in
vendor/blender_armour/Footwear to the character's feet and put on them.

    blender -b -P blender_footwear_gen.py -- job.json

job.json: {"style": leather_shoe | ankle_boot | mail_foot | round_sabaton | pointed_sabaton | hybrid_boot | turnshoe | work_boot | sandal
           | tall_boot (the last four: footwear_extra.py),
           "sides": ["L", "R"], "params": {"gap": air round the foot, a share of its size, "hide": the foot hidden in a
           closed shoe (1, the default; sandals never), "keep": the skin kept inside below the shaft's rim, a share of
           the body's height (.0114: 2 cm of a man; or "keep_mm": millimetres on a man 1.75 m tall), "width": the shoe's
           width against the last's own (1), "spring" / "spring_mm": the toe's tip lifted off the ground on a man's shoe
           (.010 m / 10 mm)}, "out": piece.glb,
           "work": a folder (the generator's textures), "character": rigged.glb, "names": {naming: {joint: bone}},
           "mask": mask.json, "under": [the GLBs worn on the shins under a tall boot: trousers, wraps]}

The generator builds a man's right shoe, in metres, on one last: the ankle joint at the origin, the toe -Y, up +Z, the
sole's bottom at -ankle_height; at the sole the last reaches .206 forward of the ankle and .064 back, .050 to either
side; the shaft above the ankle is the last's profile too. Each foot is measured on the skin (its heel, its toes'
tip with the claws, its width and middle, the ground, the ankle's height) and the shoe is scaled to it along, its toe
along the foot, its sole on the ground; above the ankle the shaft is fitted round the leg at each height.
A closed shoe hides the foot (hide): below the ankle it keeps the last's own form at the foot's length (as wide and as
high as a man's shoe of that length, rising to the ankle's height only near the ankle; a goblin's broad clawed toes
go through it unseen), and the skin in it is hidden whole up to `keep` below the rim along the shin; that much skin
stays inside the rim, the shoe fitted round it there (a bending ankle would open holes at a bare edge). Otherwise
(sandals, hide 0) the shoe is fitted round the foot at each height and hides what it covers (body_mask).
The left one is the right one mirrored, as the generator makes it. It moves with the foot, its toe with the toes, its
shaft more and more with the shin; steel goes whole with what it lies on. What it hides goes into the mask, each foot
on its own. Prints ARMOUR_GEN_OK {json} (as blender_armour_gen.py).
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
# what is worn on the shins under a tall boot (trousers, wraps: job «under»): the shaft is fitted round them as round the
# leg (made on the skin alone, loose trousers came out through it); at rest, as the body is measured
uverts = []
if style in ("tall_boot",):
    for g in job.get("under") or []:
        had = set(bpy.data.objects)
        try:
            bpy.ops.import_scene.gltf(filepath=g)
        except Exception as e:  # noqa: BLE001
            print("UNDER_SKIPPED", g, e, flush=True)
            continue
        new = [o for o in bpy.data.objects if o not in had]
        for o in new:
            if o.type == "ARMATURE":
                o.data.pose_position = "REST"
        bpy.context.view_layer.update()
        uverts += [o.matrix_world @ v.co for o in new if o.type == "MESH" for v in o.data.vertices]
        for o in new:
            bpy.data.objects.remove(o, do_unlink=True)
gap = float(prm.get("gap", .06))
hide = bool(prm.get("hide", 1)) and style != "sandal"   # (a sandal leaves the foot bare)
# the skin kept inside below the rim (world): the editor's in millimetres on a man 1.75 m tall, or a share of the height
keep = (float(prm["keep_mm"]) / 1750 if "keep_mm" in prm else float(prm.get("keep", .0114))) * H
FOOT_PRESS_MM = 25   # the shin's skin shown under the boot pressed in this far (mm on a man 1.75 m tall; prm press_mm): a hybrid
# boot's 98 skin vertices out in the guards' clips -> 55 at 15 mm, 29 at 25 (the holes at its rim 32 -> 47)
k_width = float(prm.get("width", 1.))


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
    for grow in (1, 2, 4):   # (a shin's sparse rows: a thin slice held too few of them)
        sl = [v for v in (verts + uverts if uverts else verts) if abs(v.z - z) < band * grow and Vector((v.x - q.x, v.y - q.y, 0)).length < reach]
        if len(sl) >= 12:
            break
    else:
        return None
    al = [(v - q).dot(f["fdir"]) for v in sl]
    ac = [(v - q).dot(f["xs"]) for v in sl]
    mid = q + f["fdir"] * ((max(al) + min(al)) / 2) + f["xs"] * ((max(ac) + min(ac)) / 2)
    hd, hw = (max(al) - min(al)) / 2, (max(ac) - min(ac)) / 2
    if hide:   # an ellipse round the whole slice, not the one in its box: a calf's corners came out through the shaft
        cd, cw = (max(al) + min(al)) / 2, (max(ac) + min(ac)) / 2   # (the skin kept below the rim is seen there)
        k = max(1., max(math.hypot((a_ - cd) / max(hd, 1e-6), (c_ - cw) / max(hw, 1e-6)) for a_, c_ in zip(al, ac)))
        hd, hw = hd * k, hw * k
    return Vector((mid.x, mid.y, z)), hd, hw


feet = {s: foot(s) for s in sides}

# ---------------------------------------------------------------- the generator's right shoe, in its own frame
cat = importlib.import_module("footwear_catalog")
last = importlib.import_module("footwear_last")
pair = importlib.import_module("footwear_pair")
make_materials = importlib.import_module("kettle_hat_details").make_materials
prepare_meshes = importlib.import_module("generate_kettle_hat").prepare_meshes
import footwear_extra as FX   # (everyday ones beside the generator's six: turnshoes, work boots, sandals)
p = FX.config(cat, style) if style in FX.STYLES else cat.validate_config(style, {})
if style in FX.TALL:   # (a tall boot's top: a share of the way up the shin from the ankle to the knee, in the frame's heights)
    tops = [FX.TALL[style] * (f["K"].z - f["A"].z) * p["ankle_height"] / max(1e-6, f["A"].z - f["ground"]) for f in feet.values()]
    FX.tall(last, p, p["ankle_height"] + sum(tops) / len(tops))
p["hidden_foot"] = hide   # (a turnshoe's throat closed over a hidden foot: footwear_extra)
bpy.ops.object.select_all(action="DESELECT")   # their mesh preparation unwraps whatever is selected
col = bpy.data.collections.new("Footwear")
bpy.context.scene.collection.children.link(col)
mats = make_materials(Path(job.get("work") or Path(job["out"]).parent) / f"{Path(job['out']).stem}_tex")
(FX if style in FX.STYLES else importlib.import_module("footwear_builders")).build(style, p, mats, col)
prepare_meshes([o for o in col.objects if o.type in {"MESH", "CURVE"} and o.name != "FootMail_Rings"])
right = [o for o in col.objects if o.type == "MESH"]
pair.canonical_meshes(right, p)   # the ankle at the origin, the sole's bottom at -ankle_height
for o in list(col.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
ah = p["ankle_height"]
k_len = p["foot_length"] / .270
sole_front, sole_back, sole_side = SOLE[1] * k_len, SOLE[2] * k_len, SOLE[3] * p["foot_width"] / .100
spring = (float(prm["spring_mm"]) / 1000 if "spring_mm" in prm else float(prm.get("spring", .010))) * k_len   # the toe's spring: its tip lifted off the ground (a man's 1 cm)
if spring > 0 and hide:   # (from the ball, more and more to the tip; sole, upper and steel alike: what lies on what stays
    # on it. Not under a bare foot: a sandal's sole lifted at the toe let the toes through it)
    y_ball = last.BALL * sole_front
    for o in right:
        for v in o.data.vertices:
            t = clamp((-v.co.y - y_ball) / (sole_front - y_ball), 0, 1.2)
            v.co.z += spring * t * t


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


def curve(fn, zs, n, floor=()):
    """fn at the frame's heights zs (tuples of n numbers, None where not found), smoothed along them: a function of the
    height (the slices are noisy: a bone's bump, a toe's claw, the calf). floor: the numbers never smoothed below what
    was found there (a shaft's size round a leg widening to the calf: smoothed, its top was too tight)."""
    ks = [fn(z) for z in zs]
    good = [i for i, k in enumerate(ks) if k]
    if not good:
        return lambda z: None
    ks = [k or ks[min(good, key=lambda g: abs(g - i))] for i, k in enumerate(ks)]   # (a missing one: the nearest found)
    raw = list(ks)
    for _ in range(2):
        ks = [tuple((ks[max(0, i - 1)][j] + 2 * ks[i][j] + ks[min(len(ks) - 1, i + 1)][j]) / 4 for j in range(n)) for i in range(len(ks))]
    ks = [tuple(max(k[j], r[j]) if j in floor else k[j] for j in range(n)) for k, r in zip(ks, raw)]

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
    return curve(lambda z: shaft_k(f, origin, sx, sy, sz, z), zs, 5, (0, 1) if hide else ())


def widen(obs, f, origin, sx, sy, sz, share=None):
    """Along the foot: at each stretch of it the shoe no narrower than the foot there and the gap (a goblin's toes
    spread wide where a last narrows to its toe), each side of the shoe's own middle there; below the ankle. share(z):
    how much of it at the frame's height z (a hidden foot: only where the skin stays, near the rim)."""
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
            k = 1 + (k - 1) * (1 - smooth(-.01, .02, v.co.z)) * (1 if share is None else share(v.co.z))   # the foot only, not the shaft
            v.co.x = c + (v.co.x - c) * k


def push_out(obs, f, pts, clear):
    """A tall boot over trousers (pts: what is worn under it, world): nowhere inside them. Round the shin's line (the
    ankle to the knee, on down to the ground) in bins along it and round it: how far the trousers reach out against the
    boot's inner wall there (its leather's nearest), the shortfall smoothed over the bins, every part of the boot moved
    out by it (straps, the welt with the leather: what lies on what stays on it). Below the ankle the boot keeps the
    last's own form, not the leg's: a trouser's hem round the ankle came out through it there."""
    A, K = f["A"], f["K"]
    ax = (K - A).normalized()
    e1 = f["fdir"] - ax * f["fdir"].dot(ax)
    e1.normalize()
    e2 = ax.cross(e1)
    wall = [o for o in obs if o.name.startswith(("Leather_Upper", "Inner_Lining"))]
    ws = [o.matrix_world @ v.co for o in wall for v in o.data.vertices]
    if not ws:
        return
    t0, t1 = min((q - A).dot(ax) for q in ws), max((q - A).dot(ax) for q in ws)
    NT, NA = 40, 36

    def at(q):
        d = q - A
        t = d.dot(ax)
        r = d - ax * t
        return (t - t0) / max(1e-6, t1 - t0) * NT - .5, (math.atan2(r.dot(e2), r.dot(e1)) + math.pi) / math.tau * NA - .5, r.length
    inner, outer = [[None] * NA for _ in range(NT)], [[0.] * NA for _ in range(NT)]
    for q in ws:
        x, y, r = at(q)
        i, j = int(round(x)), int(round(y)) % NA
        if 0 <= i < NT:
            inner[i][j] = r if inner[i][j] is None else min(inner[i][j], r)
    for q in pts:
        x, y, r = at(q)
        i, j = int(round(x)), int(round(y)) % NA
        if 0 <= i < NT and inner[i][j] is not None and r < 1.6 * inner[i][j]:   # (the trousers round this leg, not the other)
            outer[i][j] = max(outer[i][j], r)
    need = [[max(0., outer[i][j] + clear - inner[i][j]) if inner[i][j] is not None and outer[i][j] > 0 else 0. for j in range(NA)] for i in range(NT)]
    for _ in range(3):   # (smoothed, never below what was found: no lumps, nothing left inside)
        sm = [[(2 * need[i][j] + need[i][(j + 1) % NA] + need[i][(j - 1) % NA] + need[max(0, i - 1)][j] + need[min(NT - 1, i + 1)][j]) / 6 for j in range(NA)] for i in range(NT)]
        need = [[max(sm[i][j], need[i][j] * .85) for j in range(NA)] for i in range(NT)]
    moved = 0.

    def get(x, y):
        x = clamp(x, 0, NT - 1.001)
        i, u = int(x), x - int(x)
        j, v = int(math.floor(y)) % NA, y - math.floor(y)
        j1 = (j + 1) % NA
        return (need[i][j] * (1 - v) + need[i][j1] * v) * (1 - u) + (need[min(NT - 1, i + 1)][j] * (1 - v) + need[min(NT - 1, i + 1)][j1] * v) * u
    for o in obs:
        mi = o.matrix_world.inverted()
        for v in o.data.vertices:
            q = o.matrix_world @ v.co
            x, y, r = at(q)
            n = get(x, y)
            if n > 0 and r > 1e-6:
                d = q - A
                rr = d - ax * d.dot(ax)
                v.co = mi @ (q + rr.normalized() * n)
                moved = max(moved, n)
        o.data.update()
    print("TALL_PUSH", round(moved, 4), flush=True)


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
    # a hidden foot: below the ankle the last's own form at the foot's length (sy across and up too), up to the ankle's
    # height near the ankle only; fitted round the skin where it stays (keep below the rim) and round the shin above
    zb = p["shaft_height"] - ah - keep / sz   # the lowest kept skin in the frame
    band = (lambda z: smooth(zb - .03, zb, z)) if hide else None
    sx_own = sy * k_width

    def own_z(z):
        """The frame's height z (below the ankle) of the last's own form: the height above the sole scaled as along
        (sy), more and more as the ankle's own (sz) towards it."""
        if z >= 0:
            return z
        hw = z + ah
        return hw * (sy + (sz - sy) * (hw / ah) ** 2) / sz - ah
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
            x, y, zf = vx.co.x, vx.co.y, vx.co.z
            w = smooth(.0, .035, zf)
            kf = fit_foot(zf) if w < 1 else None
            ks = fit_shaft(zf) if w > 0 else None
            if hide:   # below the ankle the last's own form, fitted round the skin only where it stays; the shaft round the leg
                b = band(zf)
                xf = kf[3] + x * kf[0] if kf is not None else x
                xo, zo = x * sx_own / sx, own_z(zf)
                xb, zb_ = xo + (xf - xo) * b, zo + (zf - zo) * b
                if ks is not None:
                    kx, ky, dx, dy, yc = ks   # round the leg's own middle
                    xb, y = xb + (dx + x * kx - xb) * w, y + (dy + (y - yc) * ky - y) * w
                vx.co.x, vx.co.y, vx.co.z = xb, y, zb_ + (zf - zb_) * w
                continue
            if kf is not None:
                kx, dx = kf[0], kf[3]
                x = x + (dx + x * kx - x) * (1 - w)
            if ks is not None:
                kx, ky, dx, dy, yc = ks   # round the leg's own middle
                x, y = x + (dx + x * kx - x) * w, y + (dy + (y - yc) * ky - y) * w
            vx.co.x, vx.co.y = x, y
        obs.append(ob)
    widen(obs, f, origin, sx, sy, sz, band)
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
    if uverts:   # (a tall boot over trousers: nowhere inside them)
        push_out(obs, f, uverts, .003 * H / 1.75 + gap * f["half_w"] * .5)
    info[s] = {"length": round(f["toe"] - f["heel"], 2), "half_width": round(f["half_w"], 2), "ankle": round(f["A"].z - f["ground"], 2),
               "scale": [round(sx, 1), round(sy, 1), round(sz, 1)],
               "hidden_to": round((p["shaft_height"] - ah) * sz - keep, 3) if hide else None}   # (along the shin from the ankle)
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
    from body_mask import body_mask, where
    for s in sides:
        if hide:   # the foot whole and the shin up to keep below the rim (along the shin from the ankle)
            f = feet[s]
            up = (f["K"] - f["A"]).normalized()
            fb = bone(f"foot_{s}")
            own = {fb.name, *(b.name for b in fb.children_recursive), names[f"leg_{s}"]}
            lim = info[s]["hidden_to"]
            keys |= {tuple(x) for x in where(body, own, lambda q, A=f["A"], up=up, lim=lim: (q - A).dot(up) < lim)}
        else:
            keys |= {tuple(x) for x in body_mask(body, [ob for x, ob in parts if x == s], erode=4)}
    # (2026-11-27) a patch of skin left shown inside the boot, cut off from the rest by the hidden foot, hidden too: a hybrid
    # boot's instep came out through its plate in the clips (the guards' 61 clips: 136 places, the holes round it 86 -> 32).
    # Toes seen in an open shoe stay (body_mask.drop_islands: only what is all under the boot)
    from body_mask import drop_islands, press_under
    keys = {tuple(x) for x in drop_islands(body, [list(k) for k in keys], [ob for _, ob in parts])}
    pm = float(prm.get("press_mm", FOOT_PRESS_MM))
    if pm > 0:   # (the shin's skin shown in the shaft pressed in, as under a greave: it came out through a boot's shaft)
        hid_ = {k for k in keys if len(k) == 3}
        near_ = lambda k: any((k[0] + a, k[1] + b, k[2] + c) in hid_ for a in (-1, 0, 1) for b in (-1, 0, 1) for c in (-1, 0, 1))  # noqa: E731
        keys |= {tuple(m) for m in press_under(body, [ob for _, ob in parts], pm / 1750 * H, 30 / 1750 * H, by_bone=True)
                 if not near_(tuple(m[:3]))}
import blender_texbake as TB
TB.tag_mail([ob for _, ob in parts])   # (the mail's rings: a slot of their own)
obj = join([ob for _, ob in parts])
obj.name = f"{style}_footwear"
for vg in [g for g in obj.vertex_groups if g.name.endswith("_")]:   # no toe bone: the foot's
    obj.vertex_groups.remove(vg)
for m in obj.data.materials:   # full metal looks black in a game scene without reflections (cf. armour_gen_ui.PRESETS)
    b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.use_nodes else None
    if b is not None and b.inputs["Metallic"].default_value > .7:
        b.inputs["Metallic"].default_value = .65
if job.get("uv_out"):   # made for the character (not a style's preview): its textures baked, its unwrap given out
    import blender_texbake as TB
    UVTEX = TB.bake_made(obj, job.get("item") or obj.name, job, Path(job.get("work") or Path(job["out"]).parent) / f"{Path(job['out']).stem}_tex")
else:
    UVTEX = {}
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
                                     "build": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}, "uvtex": UVTEX}), flush=True)
