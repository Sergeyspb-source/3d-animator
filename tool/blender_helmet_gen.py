"""Runs INSIDE Blender (background): a helmet of the «Equipment: procedural» editor, made by the helmet generators in
vendor/blender_armour (KettleHat, HelmetVariants) to the character's head and put on it.

    blender -b -P blender_helmet_gen.py -- job.json

job.json: {"style": kettle_hat | open_bascinet | barbute | visored_bascinet | sallet | armet | (helmets_extra) nasal_helm |
                    spangenhelm | great_helm | morion | close_helm,
           "params": {"gap": air over the head, a share of its half depth, "visor_angle", "cheek_angle" (degrees),
                      "tail": a sallet's tail, "brim": a kettle hat's brim, shares of their usual size,
                      "keep_mm": the skin kept round what is seen (under the rim, round the openings), mm on a man
                      1.75 m tall (20)},
           "out": piece.glb, "work": a folder (the generators' textures),
           "character": rigged.glb, "names": {naming: {joint: bone}}, "mask": mask.json,
           "under": [the GLBs of what is worn on the head under it: a coif - measured with the head]}

The generators build for a human head, in metres, with fixed eye slits and rivets. The head is measured on the skin:
the eyes, its depth and width at the brow, its top, the chin (where the face's front goes back sharply), the neck and
the shoulders' top beside it. The helmet is built in its own proportions with the head's (width to depth, top over the
brow), scaled as one piece to it (its eye slits at the eyes, a kettle hat's brim at the brow); below the face it is
drawn up so it ends at the chin, not on the shoulders (a goblin's face is short and its neck shorter than a man's),
and an aventail hangs round the neck down to the shoulders' top, closing in to the neck (it covers the neck, it does
not fall on the chest). It moves with the head (an aventail's lower rings more and more with the neck). What it hides
goes into the mask (body_mask.head_cover): only skin that cannot be seen, and the face's own parts closed in (eyes,
teeth, tongue, the mouth: a closed helmet hides the head whole), less a band of `keep_mm` round what is seen (the
head turning on the neck shows the skin a little way in under the rim); an ear meeting the shell is laid against the
head, under it (its vertices' moves are in the mask too); an ear left out (a brim over it, a cut-out) stays.
Where the skull comes into the shell (a goblin's egg-shaped head, wider behind than the helmet's ellipse) the shell goes
out round it (clear_head); in front of the face it comes forward over what it would cut (the nose): a bump (clear_face).
Prints ARMOUR_GEN_OK {json} (as blender_armour_gen.py).
"""
import importlib
import json
import math
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE / "vendor" / "blender_armour" / "HelmetVariants"))
sys.path.insert(0, str(HERE / "vendor" / "blender_armour" / "KettleHat"))
from i18n import t as _t
import helmets_extra as X   # our five more (nasal helm, spangenhelm, great helm, morion, close helmet)

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
H = max(v.z for v in verts) - min(v.z for v in verts)
# what is worn on the head under it (a coif, a padded one: job["under"]): measured as the head is - the helmet goes
# over it (made on the skin alone, a mail coif came out through it): a ray out from the head's inside meets the skin,
# then the layers on it (their inner and outer walls) - the outermost of them close over the skin counts
uverts, upolys = [], []
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
    for o in new:
        if o.type == "MESH":
            k = len(uverts)
            uverts += [o.matrix_world @ v.co for v in o.data.vertices]
            upolys += [tuple(k + i for i in f.vertices) for f in o.data.polygons]
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
tree = BVHTree.FromPolygons(verts, polys)
treeU = BVHTree.FromPolygons(uverts, upolys) if upolys else None


def hit(org, d, far):
    d = Vector(d)
    h = tree.ray_cast(org, d, far)
    if h[0] is None:
        return None
    r = h[3]
    if treeU is not None:   # the layers worn on it there
        t = 0.0
        for _ in range(8):
            q = treeU.ray_cast(org + d * (t + 1e-4), d, far)
            if q[0] is None:
                break
            t += 1e-4 + q[3]
            if t > r + .06 * H:
                break
            r = max(r, t)
    return r


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
chin, prev, chin_y = None, None, centre.y - half_d   # chin_y: the chin's front (its tip)
z = E.z
while z > E.z - 2.5 * half_d:
    h = tree.ray_cast(Vector((E.x, centre.y - far, z)), Vector((0, 1, 0)), 2 * far)
    y = h[0].y if h[0] is not None else None
    if prev is not None and y is not None and y - prev > .25 * half_d:
        chin, chin_y = z + step, prev
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
    base = style_base()
    cfg = {"rx": clamp(dims["rx"], *G.BOUNDS["rx"]), "ry": clamp(dims["ry"], *G.BOUNDS["ry"]),
           "height": clamp(dims["height"], *G.BOUNDS["height"])}
    if style in X.STYLES:   # ours: the generator's frame and defaults, its checks not (they know its five only)
        p = {**base, **cfg}
        if style == "close_helm":
            p["visor_angle"] = clamp(float(prm.get("visor_angle", 0)), 0, 65)
            p["cheek_angle"] = clamp(float(prm.get("cheek_angle", 0)), 0, 35)
            p["visor_projection"] = SNOUT
        root, _ = X.build(style, p, tex)
        return root, p, EYE_Z
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


def style_base():
    G = importlib.import_module("generate_helmet")
    return {**G.DEFAULTS, **(G.STYLES.get(style) or X.STYLES[style])}


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
    ry_m = style_base()["ry"]
s = (half_d + gap) / ry_m
if style == "kettle_hat":   # the brim at the brow, the crown over the rest of the head
    base_z = E.z + BROW * s
    dims = {"rx": (half_w + gap) / s, "ry": ry_m, "height": (E.z + top - base_z + gap) / s}
else:
    base_z = E.z - EYE_Z * s
    dims = {"rx": (half_w + gap) / s, "ry": ry_m, "height": ((E.z + top - base_z + gap) / s - style_base()["brow_z"]) * X.RISE.get(style, 1)}
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

# the chin strap: a U from the helmet's sides made for a man's jaw (on a goblin it hangs under the neck): its bottom
# just under the chin, a little behind its tip; «strap» moves it up (+) or down, «strap_fwd» forward (+) or back, in
# shares of the head's half depth
straps = [o for o in parts if o.name.startswith(("Chinstrap", "Buckle"))]
if straps:
    vs = [v for o in straps for v in o.data.vertices]
    zt, zb = max(v.co.z for v in vs), min(v.co.z for v in vs)
    low = [v.co.y for v in vs if v.co.z < zb + .002]
    yb = sum(low) / len(low)
    tz = frame_z(chin - (.08 - float(prm.get("strap", 0))) * half_d)
    ty = (chin_y + (.3 - float(prm.get("strap_fwd", 0))) * half_d - centre.y) / s
    if zt - zb > 1e-6 and tz < zt:
        for v in vs:
            t = (zt - v.co.z) / (zt - zb)
            v.co.z = zt + (v.co.z - zt) * (tz - zt) / (zb - zt)
            v.co.y += t * (ty - yb)
        for o in straps:
            o.data.update()

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



# ---------------------------------------------------------------- the face goes under it: the shell goes round the nose
def wall_tree():
    """The helmet's metal as a BVH: not its straps and mail, nor the liner (it hangs inside the head's skin at the rim)."""
    vs, fs = [], []
    for o in parts:
        if not o.name.startswith(("Aventail_Rings", "Chinstrap", "Buckle")) and "liner" not in o.name.lower():
            k = len(vs)
            vs += [v.co.copy() for v in o.data.vertices]
            fs += [tuple(k + i for i in f.vertices) for f in o.data.polygons]
    return BVHTree.FromPolygons(vs, fs)


def clear_face():
    """Where the shell in front of the face has the skin ahead of it or too near (a nose through a nasal bar, a sallet's
    band, a great helm's front, the edges of a barbute's T), it comes forward over it, smoothly: a bump over the nose,
    the plate's thickness and rivets kept. Measured straight from the front, on a grid over the face."""
    shell = [o for o in parts if not o.name.startswith(("Aventail_Rings", "Chinstrap", "Buckle"))]
    if not shell:
        return 0.0
    t_h = wall_tree()
    cell = .03 * half_d
    x0, z0 = centre.x - 1.15 * half_w, chin - .1 * half_d
    nx, nz = int(2.3 * half_w / cell) + 1, int((E.z + .4 * top - z0) / cell) + 1
    y0, far, clear, deep = centre.y - 3 * half_d, 6 * half_d, max(.05 * half_d, .6 * gap), .9 * half_d
    D = np.zeros((nz, nx))
    for j in range(nz):
        for i in range(nx):
            org = Vector((x0 + i * cell, y0, z0 + j * cell))
            sk = tree.ray_cast(org, Vector((0, 1, 0)), far)[0]
            hl = t_h.ray_cast(org, Vector((0, 1, 0)), far)[0]
            if sk is None or hl is None or sk.y > centre.y - .2 * half_d or hl.y > centre.y:
                continue
            if hl.y - sk.y < deep:   # (deeper: the far wall seen through an opening)
                D[j, i] = clamp(hl.y - (sk.y - clear), 0, .8 * half_d)
    need = D.copy()
    if need.max() <= 0:
        return 0.0
    r = max(2, int(round(.06 * half_d / cell)))   # smoothed, never below what each place needs
    kernel = np.ones(2 * r + 1) / (2 * r + 1)
    wide = D.copy()
    for _ in range(8):
        pad = np.pad(wide, r, mode="edge")
        pad = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="same"), 0, pad)
        pad = np.apply_along_axis(lambda m: np.convolve(m, kernel, mode="same"), 1, pad)
        wide = np.maximum(pad[r:-r, r:-r], need)
    moved = 0.0
    for o in shell:
        for v in o.data.vertices:
            w = smooth(0, 1, (centre.y - .1 * half_d - v.co.y) / (.45 * half_d))
            fx, fz = (v.co.x - x0) / cell, (v.co.z - z0) / cell
            if w <= 0 or not (0 <= fx < nx - 1 and 0 <= fz < nz - 1):
                continue
            i, j = int(fx), int(fz)
            a, b = fx - i, fz - j
            d = ((wide[j, i] * (1 - a) + wide[j, i + 1] * a) * (1 - b) + (wide[j + 1, i] * (1 - a) + wide[j + 1, i + 1] * a) * b) * w
            v.co.y -= d
            moved = max(moved, d)
        o.data.update()
    return moved


def clear_head():
    """Where the skull comes into the shell or too near it (a goblin's head is an egg, wider behind than the ellipse the
    helmet is made on: a kettle hat's brim cut the back of the head, the crown the occiput), the shell goes out round
    it, smoothly: looked at across from the head's upright axis at each height and every way round, the shell's inside
    at least `clear` off the skin; what needs more than .3 of the head's half depth (an ear standing out: it is laid
    under the shell) is left. Everything but the aventail moves out across by what its place (height, way round)
    needs: a brim, a plate at one height, moves whole there and stays flat (moved out from the head's middle it waved);
    the thickness, the rivets, the straps' ends go with it."""
    t_h = wall_tree()
    clear = max(.05 * half_d, .6 * gap)
    # the skin without the ears (they go under the shell; round their roots the brim went out in lumps)
    from body_mask import ears, where_thin
    ek = {tuple(x) for x in ears(body, head_bones, centre, half_w, J.z, E.z + top, out=1.0)}
    ball = lambda q: ((q.x - centre.x) / half_w) ** 2 + ((q.y - centre.y) / half_d) ** 2 + ((q.z - centre.z) / top) ** 2  # noqa: E731
    ek |= {tuple(x) for x in where_thin(body, head_bones, lambda q: q.y > centre.y - .3 * half_d and q.z > E.z - .3 * top and ball(q) > 1.15 ** 2, .3 * half_w)}
    sv, sf = [], []
    for o in body:
        kk = [(round(v.co.x * 1000), round(v.co.z * 1000), round(-v.co.y * 1000)) for v in o.data.vertices]
        b0 = len(sv)
        sv += [o.matrix_world @ v.co for v in o.data.vertices]
        sf += [tuple(b0 + i for i in f.vertices) for f in o.data.polygons if not any(kk[i] in ek for i in f.vertices)]
    skull = BVHTree.FromPolygons(sv, sf)

    def skin_at(org, d, far):   # (as hit(): the skin, then what is worn on it there)
        h = skull.ray_cast(org, d, far)
        if h[0] is None:
            return None
        r_ = h[3]
        if treeU is not None:
            t_ = 0.0
            for _ in range(8):
                q = treeU.ray_cast(org + d * (t_ + 1e-4), d, far)
                if q[0] is None:
                    break
                t_ += 1e-4 + q[3]
                if t_ > r_ + .06 * H:
                    break
                r_ = max(r_, t_)
        return r_
    NA, NZ = 96, 40
    z0, z1 = chin, E.z + top + gap
    zs = [z0 + (z1 - z0) * j / (NZ - 1) for j in range(NZ)]
    D = np.zeros((NZ, NA))
    for j, z in enumerate(zs):
        org = Vector((centre.x, centre.y, z))
        for i in range(NA):
            az = math.tau * i / NA
            d = Vector((math.sin(az), -math.cos(az), 0))
            sk = skin_at(org, d, 3 * half_d)
            sh = t_h.ray_cast(org, d, 3 * half_d)
            if sk is None or sh[0] is None:
                continue
            need = sk + clear - sh[3]
            if 0 < need < .3 * half_d:
                D[j, i] = need
    if D.max() <= 0:
        return 0.0
    need = D.copy()
    r = 4
    wide = D.copy()
    k = np.ones(2 * r + 1) / (2 * r + 1)
    for _ in range(8):   # smoothed round (wrapping) and up, never below what each place needs
        pad = np.concatenate([wide[:, -r:], wide, wide[:, :r]], axis=1)
        pad = np.pad(pad, ((r, r), (0, 0)), mode="edge")
        pad = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 0, pad)
        pad = np.apply_along_axis(lambda m: np.convolve(m, k, mode="same"), 1, pad)
        wide = np.maximum(pad[r:-r, r:-r], need)
    moved = 0.0
    for o in parts:
        if o.name.startswith("Aventail_Rings"):
            continue
        for v in o.data.vertices:
            rel = Vector((v.co.x - centre.x, v.co.y - centre.y, 0))
            if rel.length < 1e-9:
                continue
            u = rel.normalized()
            az = math.atan2(u.x, -u.y) % math.tau
            fj = clamp((v.co.z - z0) / (z1 - z0), 0, 1) * (NZ - 1.001)
            fi = az / math.tau * NA
            i0, j0 = int(fi) % NA, int(fj)
            a_, b_ = fi - int(fi), fj - j0
            i1 = (i0 + 1) % NA
            dd = (wide[j0, i0] * (1 - a_) + wide[j0, i1] * a_) * (1 - b_) + (wide[j0 + 1, i0] * (1 - a_) + wide[j0 + 1, i1] * a_) * b_
            if dd > 0:
                v.co += u * dd
                moved = max(moved, dd)
        o.data.update()
    return moved


head_moved = clear_head()
face_moved = clear_face()
shell_tree = wall_tree()   # (for what comes out through it: the mask)

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
import blender_texbake as TB
TB.tag_mail(parts)   # (the aventail's rings: a slot of their own)
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
if job.get("uv_out"):   # made for the character (not a style's preview): its textures baked, its unwrap given out
    import blender_texbake as TB
    UVTEX = TB.bake_made(obj, job.get("item") or obj.name, job, Path(job.get("work") or Path(job["out"]).parent) / f"{Path(job['out']).stem}_tex")
else:
    UVTEX = {}
mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = arm
obj.parent = arm
obj.matrix_parent_inverse = arm.matrix_world.inverted()

if job.get("mask"):   # what it hides, the ears too
    from body_mask import above, body_mask, ears, head_cover, where, where_thin
    # what it may hide: what it closes over and, over the brow, the head under it (hair, a hat; an open helmet's only
    # within the skull's sides); then head_cover keeps of that all the skin that can be seen - through an eye slit, under
    # a rim - and takes off an ear what came out through the shell
    keys = {tuple(x) for x in body_mask(body, [obj], cover=30)}
    if style not in ("kettle_hat", "nasal_helm", "spangenhelm", "morion"):
        keys |= {tuple(x) for x in above(body, head_bones, E.z + .25 * top)}
    else:
        keys |= {tuple(x) for x in where(body, head_bones, lambda q: q.z > E.z + .25 * top and abs(q.x - centre.x) < .95 * half_w)}
    ear_keys = {tuple(x) for x in ears(body, head_bones, centre, half_w, J.z, E.z + top, out=1.0)}
    # (and an ear's part going back rather than out: what stands thin off the head's ball beside and behind it, from the eyes' level up)
    ball = lambda q: ((q.x - centre.x) / half_w) ** 2 + ((q.y - centre.y) / half_d) ** 2 + ((q.z - centre.z) / top) ** 2  # noqa: E731
    ear_keys |= {tuple(x) for x in where_thin(body, head_bones, lambda q: q.y > centre.y - .3 * half_d and q.z > E.z - .3 * top and ball(q) > 1.15 ** 2, .3 * half_w)}
    # (what else may come out through the shell: the head behind the face - the nape - and all over the brow - a skull's
    # bump, hair; not the face: a nose is met by clear_face)
    poke = {tuple(x) for x in where(body, head_bones, lambda q: q.z > E.z + .25 * top or q.y > centre.y - .15 * half_d)}
    # an ear that meets the shell goes under it, laid against the head (within the gap the helmet leaves)
    # the face's own parts closed in go too (a closed helmet: the eyes, teeth, tongue, the mouth's bag), and the skin a
    # little way in under the rim and round the openings stays (`keep`: mm on a man 1.75 m tall; the head turning on the
    # neck shows it from below)
    inner = [o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith(PARTS) and not o.name.startswith("Icosphere")]
    band = float(prm.get("keep_mm", 20)) / 1750 * H
    keys = head_cover(body, [obj], keys, poke, centre, shell=shell_tree, ear_keys=ear_keys, press=.5 * max(gap, .04 * half_d),
                      radii=(half_w, half_d, top), root=.35 * half_w, inner=inner, band=band, fixed=head_bones,
                      band_fixed=prm.get("band_fixed"))   # (a test's: body_mask.BAND_FIXED otherwise)
    Path(job["mask"]).write_text(json.dumps(keys), encoding="utf-8")

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
                                     "radius": round(half_d, 4), "sides": [], "scale": round(s, 4), "squeeze": round(squeeze, 3), "face_moved": round(face_moved, 4), "head_moved": round(head_moved, 4),
                                     "head": {"half_width": round(half_w, 3), "half_depth": round(half_d, 3), "eyes_to_top": round(top, 3),
                                              "chin": round(chin, 3), "shoulder": round(shoulder, 3), "neck": round(neck_r, 3)},
                                     "build": {k: (round(v, 4) if isinstance(v, float) else v) for k, v in p.items()}, "uvtex": UVTEX}), flush=True)
