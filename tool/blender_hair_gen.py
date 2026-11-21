"""Runs INSIDE Blender (background): a hairstyle of the «Equipment: procedural» editor, made on the character's head
and put on it (a MADE piece, as blender_footwear_gen.py).

    blender -b -P blender_hair_gen.py -- job.json

job.json: {"style": long | bob | back | crop | short | mohawk, "params": {"length": share of the height, "color":
           linear rgb, "seed"}, "out": piece.glb, "work": a folder, "character": rigged.glb, "names": {naming: {joint:
           bone}}, "mask": mask.json, "uv_out": (made for the character, not a style's preview: its colour in the
           texture; a preview's is grey, the editor tints it)}

Two ways, after what games do (and what the user chose from the prototypes):
- long hair, a bob: hair cards - strips with a strands texture (alpha) laid along strands. Each strand grows from
  the scalp along the style's way (from the parting out and down, a little back), lying on the skull to its widest,
  then falls: a chain of fixed links under gravity, meeting the body (the ears too: it slides off them), rubbing on
  it, not bending on itself, kept off the face and the chest's middle, no wider than it left the head. Three layers
  of cards for the volume, a cap in the hair's colour under them (no skin between). A bob is cut at the jaw.
- short cuts (combed back, a crop, short, the mohawk's base): a shell in the cut's shape - the scalp raised by the
  cut's thickness (volume on the top, a quiff at the front, nothing at its edges), unwrapped along the hair's way
  (meridians between a pole on the forehead under the hairline and one on the neck under the nape: from the face
  back over the top and from the temples, down over the back), clumps as grooves in its shape, fine hairs in its
  texture; a crop's sides fade out. A mohawk: thick blades along the head's middle and a ponytail on that base.
Weights: the head's, more and more the neck's and the chest's below the jaw. The skin under the cap or the shell is
the mask. Prints ARMOUR_GEN_OK {json}.
"""
import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from i18n import t as _t

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
style, prm = job["style"], job.get("params") or {}
FINAL = bool(job.get("uv_out"))   # (made for the character: its colour in the texture; a preview grey, tinted by the editor)
HAIR = np.array(prm.get("color") or [.05, .025, .012], np.float32)   # (linear)
COL = np.ones(3, np.float32)   # (the textures are drawn grey: the colour goes on as they are saved - below)
rnd = random.Random(int(prm.get("seed", 1)) * 7 + 3)
PARTS = ("Eye_", "EyeSocket", "EyeLid", "Teeth_", "Gum_", "Tongue", "MouthCavity", "Icosphere")
WORK = Path(job.get("work") or Path(job["out"]).parent)
WORK.mkdir(parents=True, exist_ok=True)
STEM = Path(job["out"]).stem


def fail(msg):
    print("ARMOUR_GEN_FAIL " + msg, flush=True)
    sys.exit(1)


def smooth(a, b, x):
    t = min(1., max(0., (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


# ---------------------------------------------------------------- the character, its head
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.unit_settings.system = "METRIC"
bpy.ops.import_scene.gltf(filepath=job["character"])
sc = bpy.context.scene
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    fail(_t("blender.the_character_has_no_skeleton_build"))
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
body = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups and not o.name.startswith(PARTS)]
names = next((tbl for tbl in job["names"].values() if tbl.get("head") in arm.data.bones), None)
if not body or names is None:
    fail(_t("ag.bones_not_recognised"))
skin = max(body, key=lambda o: len(o.data.vertices))
me = skin.data
V = [skin.matrix_world @ v.co for v in me.vertices]
P = [list(p.vertices) for p in me.polygons]
full = BVHTree.FromPolygons(V, P)
W = arm.matrix_world
UP, FRONT, X = Vector((0, 0, 1)), Vector((0, -1, 0)), Vector((1, 0, 0))
BACK = -FRONT
bone = lambda k: arm.data.bones.get(names.get(k, ""))   # noqa: E731
HD, NK = W @ bone("head").head_local, W @ (bone("neck") or bone("head")).head_local
S2 = W @ (bone("spine2") or bone("neck") or bone("head")).head_local
hit = full.ray_cast(HD + UP * 2.0, -UP, 4.0)[0]
TOP = hit if hit is not None and hit.z > HD.z else HD + UP * .12
hh = TOP.z - HD.z
O = HD + UP * (.42 * hh)
H = max(v.z for v in V) - min(v.z for v in V)


def cast(o, d, far=2.0, tree=None):
    loc, n, i, dist = (tree or full).ray_cast(o, d, far)
    return (loc, n, dist) if loc is not None else None


R = max((cast(O, X) or (None, None, .05))[2], (cast(O, -X) or (None, None, .05))[2])
eyes = [W @ bone(k).head_local for k in ("eye_L", "eye_R") if bone(k)]
E = sum(eyes, Vector()) / len(eyes) if eyes else O - UP * (.1 * R)
print("head", tuple(round(x, 3) for x in O), "R %.4f H %.3f" % (R, H), flush=True)


def thin(p):   # an ear: a ray in toward the head's axis meets its other side at once
    d = Vector((O.x - p.x, O.y - p.y, 0))
    if d.length < 1e-6:
        return False
    d.normalize()
    return full.ray_cast(p + d * (.01 * R), d, .25 * R)[0] is not None


# the ears: their thin shell, and the rings round it at the head's side (their roots, their rims)
ear_v = {i for i, v in enumerate(V) if abs(v.x - O.x) > .75 * R and O.z - 1.5 * R < v.z < O.z + 1.4 * R and thin(v)}
nbr = {}
for f in P:
    for i in f:
        nbr.setdefault(i, set()).update(f)
for _ in range(4):
    ear_v |= {j for i in ear_v for j in nbr.get(i, ()) if abs(V[j].x - O.x) > .8 * R}
bvh = BVHTree.FromPolygons(V, [p for p in P if not any(i in ear_v for i in p)])   # (the skin without the ears)
ear_pts = BVHTree.FromPolygons(V, [p for p in P if all(i in ear_v for i in p)])
EARS = {}
for sd in (1, -1):
    pe = [V[i] for i in ear_v if (V[i].x - O.x) * sd > .9 * R and thin(V[i])]
    if pe:
        EARS[sd] = dict(y0=min(p.y for p in pe), y1=max(p.y for p in pe), z1=max(p.z for p in pe), z0=min(p.z for p in pe))
core = {i for i in ear_v if thin(V[i])}
core |= {j for i in core for j in nbr.get(i, ()) if abs(V[j].x - O.x) > .85 * R}
core_tree = BVHTree.FromPolygons(V, [f for f in P if all(i in core for i in f)])


def near_ear(p, r):
    loc, n, i, dist = ear_pts.find_nearest(p)
    return loc is not None and dist < r


def by_ear(p):   # (a short cut's: the ear's core only, at the head's side - the wider rings bit into the nape)
    if abs(p.x - O.x) < .7 * R:
        return False
    loc, n, i, d = core_tree.find_nearest(p)
    return loc is not None and d < .07 * R


def zmin_default(th):
    """the hairline's height over the head's middle round the head (th: 0 the face, ±pi the nape): high at the
    forehead, lower over the ears, down to the nape behind"""
    fb = abs(th) / math.pi
    zf, zs, zb = .62 * R, .30 * R, -.55 * R
    return zf + (zs - zf) * min(1, fb / .5) if fb < .5 else zs + (zb - zs) * min(1, (fb - .5) / .25)


HL = None   # the hairline fitted by hand: [(th, height)] round the head, from its nodes


def zmin_at(th):
    if not HL:
        return zmin_default(th)
    m = len(HL)
    th = (th - HL[0][0]) % (2 * math.pi) + HL[0][0]
    k = max(i for i in range(m) if HL[i][0] <= th)
    a, b = HL[k][0], HL[(k + 1) % m][0] + (2 * math.pi if k + 1 >= m else 0)
    t = (th - a) / max(1e-9, b - a)
    z0, z1, z2, z3 = HL[(k - 1) % m][1], HL[k][1], HL[(k + 1) % m][1], HL[(k + 2) % m][1]
    return .5 * (2 * z1 + (z2 - z0) * t + (2 * z0 - 5 * z1 + 4 * z2 - z3) * t * t + (3 * z1 - z0 - 3 * z2 + z3) * t ** 3)


def hairline(p, ears=near_ear):
    """above the hairline (by its height round the head: the default's, or through the nodes moved by hand)"""
    rel = p - O
    if ears is near_ear and near_ear(p, .12 * R):
        return False
    if ears is by_ear and by_ear(p):
        return False
    return rel.z > zmin_at(math.atan2(rel.x, -rel.y))


# ---------------------------------------------------------------- textures
def save(name, arr, alpha, colour=True):
    """an image from an array (rows bottom up), saved next to the piece (the export takes it in). A colour texture's
    grey is the hair's light: made for the character it is times the hair's colour (as the editor tints the grey
    preview: in linear light, the image itself sRGB - a linear colour written straight in came out near black)"""
    h, w = arr.shape[:2]
    rgba = np.ones((h, w, 4), np.float32)
    rgba[..., :arr.shape[2]] = arr
    if colour and FINAL:
        g = np.clip(rgba[..., :3], 0, 1)
        lin = np.where(g <= .04045, g / 12.92, ((g + .055) / 1.055) ** 2.4) * HAIR[None, None, :]
        rgba[..., :3] = np.where(lin <= .0031308, lin * 12.92, 1.055 * np.power(np.clip(lin, 1e-8, 1), 1 / 2.4) - .055)
    im = bpy.data.images.new(f"{STEM}_{name}", w, h, alpha=alpha)
    im.pixels.foreach_set(rgba.ravel())
    im.filepath_raw = str(WORK / f"{STEM}_{name}.png")
    im.file_format = "PNG"
    im.save()
    return im


def strands_atlas(TW=512, TH=1024):
    """four cards' strands side by side: along v (0 its root .. 1 its end), ragged ends, alpha"""
    img = np.zeros((TH, TW, 4), np.float32)
    lum = np.full((TH, TW), .8, np.float32)
    for k in range(4):
        x0 = k * TW // 4
        cw = TW // 4   # (a soft solid middle under the strands: the card reads as a lock, not a few hairs)
        xs_ = np.arange(cw); env = np.clip(1 - np.abs((xs_ + .5) / cw * 2 - 1) ** 2 * 1.4, 0, 1) * .75
        yy = np.arange(TH)[:, None]; tip = np.clip((TH * .78 - yy) / (TH * .12), 0, 1)
        img[:, x0:x0 + cw, 3] = np.maximum(img[:, x0:x0 + cw, 3], env[None, :] * tip)
        for s in range(130):
            cx = x0 + 4 + rnd.random() * (TW // 4 - 8)
            w = .6 + rnd.random() * 1.4
            end = TH * (.7 + .3 * rnd.random())
            br = .7 + .6 * rnd.random()
            sway = rnd.random() * 6.28
            ys = np.arange(int(end))
            xs = cx + 2.5 * np.sin(ys / TH * 6 + sway)
            for dx in range(-2, 3):
                xi = np.clip((xs + dx).astype(int), x0, x0 + TW // 4 - 1)
                al = np.exp(-((xs + dx - xi - .5) ** 2 + dx * dx) / (w * w)) * np.clip((end - ys) / 60, 0, 1)
                img[ys, xi, 3] = np.maximum(img[ys, xi, 3], al)
                m = al > .05
                lum[ys[m], xi[m]] = np.minimum(1.0, br)
    img[..., :3] = lum[..., None] * COL[None, None, :]
    return img


def strands_tile(TW, TH, n, wmin, wmax, seed, clump):
    """a tiling height of strands along v (fine hairs, or wide clumps)"""
    r = random.Random(seed)
    h = np.zeros((TH, TW), np.float32)
    for s in range(n):
        cx = r.random() * TW; w = wmin + r.random() * (wmax - wmin); L = TH * (.3 + .7 * r.random()); y0 = r.random() * TH
        ys = np.arange(int(L)); yy = ((y0 + ys) % TH).astype(int)
        xs = cx + (4 if clump else 1.5) * np.sin(ys / TH * 6.28 * 2 + r.random() * 6.28)
        amp = .5 + .5 * r.random()
        for dx in range(-int(wmax) - 1, int(wmax) + 2):
            xi = ((xs + dx).astype(int)) % TW
            al = amp * np.exp(-((xs + dx - np.floor(xs + dx) - .5) ** 2 + dx * dx) / (w * w)) * np.minimum(1, np.minimum(ys, L - ys) / (.15 * L + 1))
            h[yy, xi] = np.maximum(h[yy, xi], al)
    return h


def material(name, im, cut, rough=.6):
    """the image's colour (its alpha cutting it: glTF's MASK - a Round node is the exporter's sign of a clip)"""
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    t = nt.nodes.new("ShaderNodeTexImage"); t.image = im
    nt.links.new(t.outputs[0], b.inputs["Base Color"])
    if cut:
        rd = nt.nodes.new("ShaderNodeMath"); rd.operation = "ROUND"
        nt.links.new(t.outputs["Alpha"], rd.inputs[0]); nt.links.new(rd.outputs[0], b.inputs["Alpha"])
        if hasattr(m, "blend_method"):
            try:
                m.blend_method = "CLIP"
            except TypeError:
                pass
    b.inputs["Roughness"].default_value = rough
    try:
        b.inputs["Specular IOR Level"].default_value = .3
    except KeyError:
        pass
    return m, t


# ---------------------------------------------------------------- long hair, a bob: cards
def build_cards(L, part, cut_z):
    roots = []
    N = 2000   # (fewer roots, steps and points than the prototype's: a preview in about a minute, a lighter piece)
    for i in range(N):
        z = 1 - 2 * (i + .5) / N; r = math.sqrt(1 - z * z); ph = i * 2.39996
        d = Vector((r * math.cos(ph), r * math.sin(ph), z))
        h = cast(O, d, tree=bvh)
        if h and hairline(h[0]):
            roots.append((h[0], h[1].normalized() if h[1].dot(d) > 0 else -h[1].normalized()))
    px = O.x + part * R

    def _ramp(z, a, b):
        t = min(1., max(0., (a - z) / (a - b)))
        return t * t * (3 - 2 * t)

    def keep_x(q):   # how far from the middle hair in front of the face and the chest stays (smooth with the height)
        return R * (.9 + .4 * _ramp((q - O).z, -.8 * R, -2.2 * R))

    def in_front(q):
        rel = q - O
        if rel.z > .55 * R or rel.z < -4 * R:
            return False
        ylim = (O.y - .15 * R) + (NK.y - (O.y - .15 * R)) * _ramp(rel.z, -.8 * R, -2.2 * R)
        return q.y < ylim and abs(rel.x) < keep_x(q)

    def flow(p, n):   # from the parting out and down, a little back; behind the crown down
        sd = math.tanh((p.x - px) / (.06 * R))
        top = min(1., max(0., ((p - O).z / R + .1) / .9))
        fr = min(1., max(0., (-(p - O).y / R + .5) / .9))
        f = X * sd * 1.3 * top * fr - UP * (.35 + .9 * (1 - top * fr)) + BACK * (.3 * top + .55 * (1 - top))
        f = f - n * f.dot(n)
        return f.normalized() if f.length > 1e-6 else -UP

    def push_out(p, gap):
        loc, n, i, dist = bvh.find_nearest(p)
        if loc is None:
            return p
        if (p - loc).dot(n) < 0 or dist < gap:
            nn = n.normalized() if n.dot(p - O) > -1 else -n.normalized()
            return loc + nn * gap
        return p

    def guide(root, n, layer):
        p = root.copy(); pts = [p.copy()]
        gap = (.06 + .1 * layer) * R
        Ls = L * (.85 + .3 * rnd.random()) * (1 if layer < 2 else 1.05)
        d = flow(p, n); x0 = abs(p.x - O.x)
        ds = Ls / 30
        held, k_free = True, 10 ** 6
        for k in range(30):
            if held and len(pts) > 3 and p.z < pts[-2].z and math.hypot(p.x - O.x, p.y - O.y) < math.hypot(pts[-2].x - O.x, pts[-2].y - O.y) - 1e-6:
                held = False; k_free = len(pts) - 1   # (going down and in toward the head's axis: past its widest)
            on_head = held and p.z > O.z - .35 * R
            loc, nrm, i, dist = bvh.find_nearest(p)
            want = flow(p, nrm.normalized() if nrm.dot(p - O) > 0 else -nrm.normalized()) if on_head and loc is not None else -UP
            d = (d * .6 + want * .4).normalized()
            q = p + d * ds
            if on_head:
                loc, nrm, i, dist = bvh.find_nearest(q)
                if loc is not None:
                    q = loc + (nrm.normalized() if nrm.dot(q - O) > 0 else -nrm.normalized()) * gap
            q = push_out(q, gap)
            if in_front(q):
                q.x = O.x + math.copysign(keep_x(q), q.x - O.x if abs(q.x - O.x) > 1e-6 else 1)
            if q.z < NK.z + .6 * R and abs(q.x - O.x) > max(x0, 1.3 * R):
                q.x = O.x + math.copysign(max(x0, 1.3 * R), q.x - O.x)
            d = (q - p).normalized() if (q - p).length > 1e-9 else d
            p = q; pts.append(p.copy())
        return pts, k_free

    zst = max([O.z - .35 * R] + [e["z1"] + .03 * R for e in EARS.values()])
    G = Vector((0, 0, -9.8)) * (H / 1.0)   # (as fast for any size: the steps are in the body's own units)
    dt2 = (1 / 30) ** 2

    def settle(pts, k_free, layer, iters=100):
        n = len(pts)
        k0 = min(k_free, next((i for i, p in enumerate(pts) if p.z < zst), n))
        if k0 >= n - 1:
            return pts
        k0 = max(1, k0)
        rest = [(pts[i + 1] - pts[i]).length for i in range(n - 1)]
        xmax = max(abs(pts[k0 - 1].x - O.x), 1.15 * R)
        e = EARS.get(1 if pts[0].x >= O.x else -1)
        front = (pts[0] - O).y < -.2 * R or (e is not None and pts[0].y < (e["y0"] + e["y1"]) / 2 and abs(pts[0].x - O.x) > .5 * R)
        pos = [p.copy() for p in pts]
        for i in range(k0, n):
            pos[i] = pos[i - 1] - UP * rest[i - 1]
        prev = [p.copy() for p in pos]
        gap = (.08 + .1 * layer) * R
        touch = [False] * n
        for it in range(iters):
            for i in range(k0, n):   # verlet: its speed (damped, rubbing where it touches), gravity; not through the body
                v = (pos[i] - prev[i]) * (.5 if touch[i] else .8)
                pull = Vector((0, -2.5 if front else 2.5, 0)) * (H / 1.0) if touch[i] and pos[i].z < NK.z + .3 * R else Vector()
                old = pos[i].copy(); prev[i] = old; new = old + v + (G + pull) * dt2
                mv = new - old; ml = mv.length
                if ml > 1e-9:
                    hit, hn, hi, hd = full.ray_cast(old, mv / ml, ml + gap)
                    if hit is not None:
                        hn = hn.normalized(); hn = hn if hn.dot(mv) < 0 else -hn
                        new = hit + hn * gap + (mv - hn * mv.dot(hn)) * .5; touch[i] = True
                pos[i] = new
            for c in range(3):
                for i in range(k0, n):   # its links' lengths
                    d = pos[i] - pos[i - 1]; Lc = d.length
                    if Lc > 1e-9:
                        want = pos[i - 1] + d * (rest[i - 1] / Lc)
                        hit, hn, hi, hd = full.ray_cast(pos[i - 1], d / Lc, rest[i - 1])
                        if hit is not None and hd > gap:
                            hn = hn.normalized(); hn = hn if hn.dot(d) < 0 else -hn; want = hit + hn * gap
                        pos[i] = want
                for i in range(max(k0, 2), n):   # not bending on itself
                    d = pos[i] - pos[i - 2]; Lc = d.length; want = .9 * (rest[i - 1] + rest[i - 2])
                    if 1e-9 < Lc < want:
                        pos[i] = pos[i] + d * ((want - Lc) / Lc * .3)
                for i in range(k0, n):   # out of the body, off the face and the chest's middle, no wider than it left
                    loc, nrm, fi, dist = full.find_nearest(pos[i])
                    touch[i] = False
                    if loc is not None:
                        nn = nrm.normalized(); side = (pos[i] - loc).dot(nn)
                        if side < gap:
                            pos[i] = pos[i] + nn * (gap - side); touch[i] = True
                    if abs(pos[i].x - O.x) > xmax:
                        pos[i].x = O.x + math.copysign(xmax, pos[i].x - O.x)
                    if in_front(pos[i]):
                        tx = O.x + math.copysign(keep_x(pos[i]), pos[i].x - O.x if abs(pos[i].x - O.x) > 1e-6 else 1)
                        pos[i].x += (tx - pos[i].x) * .5
        for _ in range(12):   # smoothed, out of the body again
            sm = [p.copy() for p in pos]
            for i in range(max(2, k0 - 6), n - 1):
                sm[i] = pos[i] * .5 + (pos[i - 1] + pos[i + 1]) * .25
            pos = sm
            for i in range(max(2, k0 - 6), n):
                loc, nrm, fi, dist = full.find_nearest(pos[i])
                if loc is not None:
                    nn = nrm.normalized(); side = (pos[i] - loc).dot(nn)
                    if side < gap:
                        pos[i] = pos[i] + nn * (gap - side)
        return pos

    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")

    def card(pts, w0, slot):
        if cut_z is not None:   # a bob: cut at the jaw
            k = next((i for i, p in enumerate(pts) if p.z < cut_z), len(pts))
            pts = pts[:max(3, k + 1)]
        r0 = pts[0] - O
        ph, amp = 2.2 * r0.x / R + 1.4 * r0.y / R, .06 * R   # (one sway for the whole hair: neighbours together)
        pts = [p if p.z > zst else p + Vector((math.sin(ph + (zst - p.z) / (1.6 * R) * 3.14), 0, 0)) * amp * min(1., (zst - p.z) / R) for p in pts]
        left, right = [], []
        for i, p in enumerate(pts):
            t = (pts[min(i + 1, len(pts) - 1)] - pts[max(i - 1, 0)]).normalized()
            out = (p - O) if p.z > NK.z else Vector((p.x - O.x, p.y - O.y, 0))
            loc, nrm, fi, dist = bvh.find_nearest(p)
            k = min(1., max(0., (p.z - (O.z - .7 * R)) / (.6 * R)))   # (flat on the skull, round the body below)
            if loc is not None and k > 0:
                nn = nrm.normalized(); nn = nn if nn.dot(p - loc) >= 0 else -nn
                out = nn * k + out.normalized() * (1 - k)
            side = t.cross(out)
            side = side.normalized() if side.length > 1e-9 else X
            below = max(0., (O.z - .35 * R - p.z) / (4 * R))
            w = w0 * (1 + .8 * min(1., below)) * (1 - .55 * (i / (len(pts) - 1)) ** 2)
            o = out.normalized() * (.02 * R)
            left.append(bm.verts.new(p - side * w / 2 + o)); right.append(bm.verts.new(p + side * w / 2 + o))
        u0, u1 = slot / 4 + .005, (slot + 1) / 4 - .005
        for i in range(len(pts) - 1):
            f = bm.faces.new((left[i], right[i], right[i + 1], left[i + 1]))
            v0, v1 = 1 - i / (len(pts) - 1), 1 - (i + 1) / (len(pts) - 1)
            for lp, uv in zip(f.loops, ((u0, v0), (u1, v0), (u1, v1), (u0, v1))):
                lp[uvl].uv = uv
    n_cards = 0
    for layer, every, w in ((0, 3, .7), (1, 2, .6), (2, 3, .56)):
        for k, (r0, n) in enumerate(roots):
            if k % every:
                continue
            pts, kf = guide(r0 + n * ((.04 + .08 * layer) * R), n, layer)
            card(settle(pts, kf, layer), w * R * (.8 + .4 * rnd.random()), rnd.randrange(4))
            n_cards += 1
    print("cards", n_cards, flush=True)
    cm = bpy.data.meshes.new("hair_cards"); bm.to_mesh(cm); bm.free()
    cards = bpy.data.objects.new("hair_cards", cm); sc.collection.objects.link(cards)
    atlas = strands_atlas()
    im = save("strands", atlas, True)
    m_cards, _ = material("hair_strands", im, True)
    cm.materials.append(m_cards)
    # the cap: the scalp, a little off it, darker (the hair's depth), its strands from the parting down
    cap = scalp_shell(hairline, lambda v: .05 * R, "hair_cap")
    for f in cap.data.polygons:
        f.use_smooth = True
    uvc = cap.data.uv_layers.new(name="UVMap")
    for poly in cap.data.polygons:
        for li in poly.loop_indices:
            c = cap.data.vertices[cap.data.loops[li].vertex_index].co - O
            uvc.data[li].uv = ((.02 + .2 * ((-c.y / (1.5 * R)) % 1.0)), .2 + .5 * math.atan2(abs(c.x - (px - O.x)), c.z) / math.pi)
    dark = atlas.copy(); dark[..., :3] *= .38; dark[..., 3] = 1   # (the hair's depth: dark, no light patch on the crown)
    m_cap, _ = material("hair_cap", save("cap", dark, False), False, .8)
    cap.data.materials.append(m_cap)
    return [cards, cap], cap


def scalp_shell(region, lift, name, close=0):
    """the region's skin (welded), each point raised out from the head by lift(vertex)"""
    bm = bmesh.new(); bm.from_mesh(me); bm.transform(skin.matrix_world)
    for lay in list(bm.verts.layers.deform.values()):   # (the skin's weights not carried over: its groups are not the hair's)
        bm.verts.layers.deform.remove(lay)
    keep = {v for v in bm.verts if region(v.co)}
    if close:   # (the skin mesh's own notches on the line filled: grown, shrunk back - only filling)
        grown = set(keep)
        for _ in range(close):
            grown |= {e.other_vert(v) for v in grown for e in v.link_edges if not by_ear(e.other_vert(v).co)}
        closed = set(grown)
        for _ in range(close):
            closed -= {v for v in closed if any(e.other_vert(v) not in closed for e in v.link_edges)}
        keep |= closed
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context="VERTS")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    for lay in list(bm.loops.layers.uv.values()):
        bm.loops.layers.uv.remove(lay)
    bm.verts.ensure_lookup_table(); bm.normal_update()
    for v in bm.verts:
        nn = v.normal.copy()
        if nn.dot(v.co - O) < 0:
            nn.negate()
        v.co += nn * lift(v)
    m = bpy.data.meshes.new(name); bm.to_mesh(m); bm.free()
    ob = bpy.data.objects.new(name, m); sc.collection.objects.link(ob)
    return ob


# ---------------------------------------------------------------- short cuts: a shell
SHORT = {"back": dict(T=.13, quiff=.22, side=.07, fade=False, turn=0.),
         "crop": dict(T=.12, quiff=.10, side=.02, fade=True, turn=0.),
         "short": dict(T=.12, quiff=.16, side=.06, fade=False, turn=25.),
         "mohawk": dict(T=.03, quiff=0., side=.02, fade=True, turn=0.)}


def build_shell(cfg):
    def backness(p):
        return min(1., max(0., ((p - O).y / R + .2) / 1.0))

    def in_cut(p):
        if not hairline(p, by_ear):
            return False
        if style == "crop":
            return (p - O).z > (.15 - .35 * backness(p)) * R
        if style == "mohawk":
            return abs(p.x - O.x) < .3 * R
        return True
    bm = bmesh.new(); bm.from_mesh(me); bm.transform(skin.matrix_world)
    for lay in list(bm.verts.layers.deform.values()):   # (the skin's weights not carried over: its groups are not the hair's)
        bm.verts.layers.deform.remove(lay)
    keep = {v for v in bm.verts if in_cut(v.co)}
    grown = set(keep)
    for _ in range(4):
        grown |= {e.other_vert(v) for v in grown for e in v.link_edges if not by_ear(e.other_vert(v).co)}
    closed = set(grown)
    for _ in range(4):
        closed -= {v for v in closed if any(e.other_vert(v) not in closed for e in v.link_edges)}
    keep |= closed
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context="VERTS")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    for lay in list(bm.loops.layers.uv.values()):
        bm.loops.layers.uv.remove(lay)
    bm.verts.ensure_lookup_table(); bm.normal_update()
    n = len(bm.verts)
    import heapq
    dist = [1e9] * n   # the way in from the cut's edge (along the skin)
    edge = {v.index for e in bm.edges if len(e.link_faces) < 2 for v in e.verts}
    for i in edge:
        dist[i] = 0.
    hq = [(0., i) for i in edge]; heapq.heapify(hq)
    while hq:
        d0, i = heapq.heappop(hq)
        if d0 > dist[i]:
            continue
        for e in bm.verts[i].link_edges:
            j = e.other_vert(bm.verts[i]).index; dd = d0 + e.calc_length()
            if dd < dist[j]:
                dist[j] = dd; heapq.heappush(hq, (dd, j))

    def thick(v, i):
        rel = v.co - O
        top = min(1., max(0., (rel.z / R - .1) / .6))
        front = min(1., max(0., (-rel.y / R - .1) / .7)) * top
        t = R * (cfg["side"] + (cfg["T"] - cfg["side"]) * top + cfg["quiff"] * front ** 1.5)
        return t * min(1., dist[i] / (.6 * R)) ** .7   # (rounded off to the edge: no rim)
    hgt = [thick(v, i) for i, v in enumerate(bm.verts)]
    for v, h in zip(bm.verts, hgt):
        nn = v.normal.copy()
        if nn.dot(v.co - O) < 0:
            nn.negate()
        v.co += nn * (.024 * R + h)
    for _ in range(6):
        bmesh.ops.smooth_vert(bm, verts=[v for v in bm.verts if dist[v.index] > 0], factor=.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    for v, h in zip(bm.verts, hgt):   # (out of the skin's bumps the smoothing pulled it into)
        loc, nrm, fi, d = full.find_nearest(v.co)
        if loc is None:
            continue
        nn = nrm.normalized(); nn = nn if nn.dot(v.co - O) > 0 else -nn
        side = (v.co - loc).dot(nn); need = .024 * R + .5 * h
        if side < need:
            v.co += nn * (need - side)
    # the unwrap along the hair's way: meridians between a pole on the forehead under the hairline and one on the neck
    # under the nape (turned to a side for a side-swept cut)
    a = math.radians(cfg["turn"])
    fwd = FRONT * math.cos(a) + X * math.sin(a)
    PF = O + fwd * R - UP * (.15 * R)
    PB = O - fwd * (.9 * R) - UP * (1.6 * R)
    CC = (PF + PB) * .5; ax = (PF - PB).normalized()
    ref = (UP - ax * UP.dot(ax)).normalized(); ref2 = ax.cross(ref)
    S = 2.2 * R
    UVV = {}
    for v in bm.verts:
        d = v.co - CC; dl = d.length
        pol = math.acos(max(-1., min(1., d.dot(ax) / max(dl, 1e-12))))
        az = math.atan2(d.dot(ref2), d.dot(ref))
        UVV[v.index] = (az * 1.3 * R / S, pol * 1.6 * R / S)
    fade = {v.index: (min(1., dist[v.index] / (.45 * R)) if cfg["fade"] else min(1., dist[v.index] / (.06 * R))) for v in bm.verts}
    uvl = bm.loops.layers.uv.new("UVMap")
    us = [u for u, _ in UVV.values()]; vs = [w for _, w in UVV.values()]
    u0, v0, span = min(us), min(vs), max(max(us) - min(us), max(vs) - min(vs))
    for f in bm.faces:
        for lp in f.loops:
            u, w = UVV[lp.vert.index]
            lp[uvl].uv = ((u - u0) / span, (w - v0) / span)   # (one texture over the whole cut: drawn below)
    m = bpy.data.meshes.new("hair_shell"); bm.to_mesh(m)
    # (what it hides: its solid part only - where it fades out (a crop's sides, any cut's ragged edge) the skin stays,
    # hidden it showed as holes through the faded hair)
    solid = bm.copy()
    bmesh.ops.delete(solid, geom=[f for f in solid.faces if min(fade[v.index] for v in f.verts) < .99], context="FACES")
    mi = bpy.data.meshes.new("hair_shell_solid"); solid.to_mesh(mi); solid.free(); bm.free()
    inner = bpy.data.objects.new("hair_shell_solid", mi); sc.collection.objects.link(inner)
    ob = bpy.data.objects.new("hair_shell", m); sc.collection.objects.link(ob)
    for poly in m.polygons:
        poly.use_smooth = True
    # the texture over the unwrap: fine hairs (~2 mm) and clumps (~2 cm) along v, their light; the fade (a crop's
    # sides) its alpha - the fine hairs stay longest. Drawn per pixel: the tiles at their own scales; the fade
    # rasterised from the triangles
    T = 1024
    fine = strands_tile(512, 512, 200, 2., 4., 11, False)
    clumps = strands_tile(256, 256, 16, 18, 30, 12, True)
    uu = (np.arange(T) + .5) / T * span + u0
    vv = (np.arange(T) + .5) / T * span + v0
    UU, VV = np.meshgrid(uu, vv)
    fi = fine[((VV * .6 * 512) % 512).astype(int), ((UU * .6 * 512) % 512).astype(int)]
    cl = clumps[((VV * 256) % 256).astype(int), ((UU * 256) % 256).astype(int)]
    k = np.clip(fi * .55 + .25, 0, 1) * np.clip(cl * .8 + .4, 0, 1.2)
    lum = .3 + .7 * np.clip(k, 0, 1)
    img = np.zeros((T, T, 4), np.float32)
    img[..., :3] = lum[..., None] * COL[None, None, :]
    fade_img = np.zeros((T, T), np.float32)
    uvd = m.uv_layers[0].data
    for poly in m.polygons:   # (rasterised: each triangle of the polygon, barycentric)
        li = list(poly.loop_indices)
        for t in range(1, len(li) - 1):
            tri = [li[0], li[t], li[t + 1]]
            pu = np.array([uvd[j].uv[0] * T for j in tri]); pv = np.array([uvd[j].uv[1] * T for j in tri])
            fv = np.array([fade[m.loops[j].vertex_index] for j in tri])
            x0, x1 = int(max(0, pu.min() - 1)), int(min(T - 1, pu.max() + 1))
            y0, y1 = int(max(0, pv.min() - 1)), int(min(T - 1, pv.max() + 1))
            if x1 < x0 or y1 < y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
            den = (pv[1] - pv[2]) * (pu[0] - pu[2]) + (pu[2] - pu[1]) * (pv[0] - pv[2])
            if abs(den) < 1e-12:
                continue
            l0 = ((pv[1] - pv[2]) * (gx - pu[2]) + (pu[2] - pu[1]) * (gy - pv[2])) / den
            l1 = ((pv[2] - pv[0]) * (gx - pu[2]) + (pu[0] - pu[2]) * (gy - pv[2])) / den
            l2 = 1 - l0 - l1
            inside = (l0 >= -.02) & (l1 >= -.02) & (l2 >= -.02)
            val = l0 * fv[0] + l1 * fv[1] + l2 * fv[2]
            sub = fade_img[y0:y1 + 1, x0:x1 + 1]
            sub[inside] = np.maximum(sub[inside], val[inside])
    img[..., 3] = np.maximum(fade_img ** 3, np.clip(fade_img * (fi * 1.6 - .2), 0, 1))
    m_shell, tnode = material("hair_shell", save("shell", img, True), True, .55)
    # the relief: fine hairs and clumps as a normal map over the same unwrap
    hgt_img = fi * .4 + cl * .6
    gy_, gx_ = np.gradient(hgt_img)
    s = 6.0
    nrm = np.dstack([-gx_ * s, -gy_ * s, np.ones_like(hgt_img)])
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
    nim = save("shell_normal", nrm * .5 + .5, False, colour=False)
    nim.colorspace_settings.name = "Non-Color"
    nt = m_shell.node_tree; b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tn = nt.nodes.new("ShaderNodeTexImage"); tn.image = nim
    nm = nt.nodes.new("ShaderNodeNormalMap"); nt.links.new(tn.outputs[0], nm.inputs["Color"]); nt.links.new(nm.outputs[0], b.inputs["Normal"])
    m.materials.append(m_shell)
    # the clumps as grooves in the shape: subdivided, displaced (applied: a game takes the mesh)
    sub = ob.modifiers.new("sub", "SUBSURF"); sub.levels = sub.render_levels = 2
    ctex = bpy.data.textures.new("clumps", "IMAGE")
    cim = bpy.data.images.new(f"{STEM}_clumps_h", 256, 256)
    cim.pixels.foreach_set(np.dstack([clumps, clumps, clumps, np.ones_like(clumps)]).astype(np.float32).ravel())
    cim.pack()   # (packed: a generated image's pixels are not what a modifier reads otherwise)
    ctex.image = cim
    # (the displacement's own unwrap: the clumps' tiling coordinates, not the texture's square)
    uvt = m.uv_layers.new(name="tile")
    for poly in m.polygons:
        for li in poly.loop_indices:
            u, w = UVV[m.loops[li].vertex_index]
            uvt.data[li].uv = (u, w)
    dsp = ob.modifiers.new("grooves", "DISPLACE"); dsp.texture = ctex; dsp.texture_coords = "UV"; dsp.uv_layer = "tile"
    dsp.strength = .09 * R; dsp.mid_level = .5
    bpy.context.view_layer.objects.active = ob
    for md in list(ob.modifiers):
        bpy.ops.object.modifier_apply(modifier=md.name)
    m.uv_layers.remove(m.uv_layers["tile"])
    return ob, inner


def build_mohawk(base):
    """thick blades along the head's middle, standing up at the front, swept back behind, and a ponytail"""
    L = float(prm.get("length", .08)) * H
    bm = bmesh.new(); uvl = bm.loops.layers.uv.new("UVMap")
    r0 = .075 * R * 2.3
    Nn = 12
    tail = None

    def tube(pts, rad, flat_ax=None, k=1.):
        n = len(pts); rows = []; s = 0.
        for i in range(n):
            if i:
                s += (pts[i] - pts[i - 1]).length
            t = (pts[min(n - 1, i + 1)] - pts[max(0, i - 1)]).normalized()
            ref = flat_ax if flat_ax is not None else (UP if abs(t.z) < .9 else FRONT)
            n1 = (ref - t * ref.dot(t)).normalized(); n2 = t.cross(n1).normalized()
            row = [bm.verts.new(pts[i] + n1 * (math.cos(a) * rad[i] * k) + n2 * (math.sin(a) * rad[i])) for a in (j / 8 * 6.2832 for j in range(8))]
            rows.append((row, s))
        for i in range(n - 1):
            for j in range(8):
                f = bm.faces.new((rows[i][0][j], rows[i + 1][0][j], rows[i + 1][0][(j + 1) % 8], rows[i][0][(j + 1) % 8]))
                for lp, (uu, vv) in zip(f.loops, ((j / 8, rows[i][1]), (j / 8, rows[i + 1][1]), ((j + 1) / 8, rows[i + 1][1]), ((j + 1) / 8, rows[i][1]))):
                    lp[uvl].uv = (uu * .25, vv / (2.2 * R))
    for row in (0, -1, 1):
        for k in range(Nn):
            t = (k + (.5 if row else 0)) / (Nn - 1)
            if t > 1:
                continue
            ang = math.pi * (.3 + .72 * t)
            d = (FRONT * math.cos(ang) + UP * math.sin(ang)).normalized()
            h = cast(O + X * (row * .09 * R), d, tree=bvh)
            if not h:
                continue
            Sp = h[0]
            if (Sp - O).z < .55 * R and t < .3:
                continue
            nrm = (Sp - O).normalized()
            if not row and (tail is None or t >= tail[2]):
                tail = (Sp, nrm, t)
            Ls = L * (.5 + .6 * math.sin(math.pi * min(1, t * 1.1)) ** .8) * (.85 + .3 * rnd.random()) * (.8 if row else 1)
            dv = (nrm + BACK * (-.15 + 1.1 * t) + X * (row * .25)).normalized()
            pts = [Sp - nrm * (.3 * r0)]; rad = [r0 * (.85 if row else 1)]
            for i in range(1, 9):
                dv = (dv + BACK * (.07 + .05 * t) - UP * (.03 * t)).normalized()
                pts.append(pts[-1] + dv * (Ls / 8)); rad.append(rad[0] * max(.02, (1 - i / 8) ** 1.1))
            tube(pts, rad, dv.cross(X).normalized(), 1.7)
    if tail is not None:   # the ponytail: back and down the neck, bound twice, to a point
        Sp, nrm, _ = tail
        Lp, rp = 1.4 * L, .9 * r0
        pts = [Sp + nrm * (.5 * rp)]; rad = [rp]
        dv = (BACK - UP * .4).normalized()
        for i in range(1, 17):
            dv = (dv - UP * .18).normalized()
            q = pts[-1] + dv * (Lp / 16)
            loc, nn, fi, dd = full.find_nearest(q)
            if loc is not None and dd < 1.2 * rp:
                q = loc + (q - loc).normalized() * 1.2 * rp
            f = i / 16; band = 1.25 if (.1 < f < .16 or .22 < f < .28) else 1
            pts.append(q); rad.append(rp * band * ((.75 + .25 * (1 - f / .3)) if f < .3 else max(.03, ((1 - f) / .7) ** .8) * (1.15 if f < .45 else 1)))
        tube(pts, rad)
    mm = bpy.data.meshes.new("hair_mohawk"); bm.to_mesh(mm); bm.free()
    ob = bpy.data.objects.new("hair_mohawk", mm); sc.collection.objects.link(ob)
    for poly in mm.polygons:
        poly.use_smooth = True
    tile = strands_tile(256, 512, 60, 2, 4, 21, False)
    lum = .35 + .65 * tile
    img = np.zeros((512, 256, 3), np.float32); img[...] = lum[..., None] * COL[None, None, :]
    m_m, _ = material("hair_mohawk", save("mohawk", img, False), False, .55)
    mm.materials.append(m_m)
    return [ob, base]


# ---------------------------------------------------------------- a beard: a mass on the face, a moustache
# (after a sculpted one - a head with a beard made in Tripo, the user's: a mass over the cheeks and the jaw, its edge
# rising from the moustache's ends to the sideburns, bare skin under the lower lip, a wedge hanging from the chin to a
# point; a moustache of two thick tapering locks over the upper lip, their ends curled; the hairs all down)
FM = {k: Vector((v[0], -v[2], v[1])) for k, v in (job.get("face") or {}).items()   # (glTF's axes to Blender's)
      if isinstance(v, (list, tuple)) and len(v) == 3}
BEARD = {   # T: on the cheeks, J: at the jaw (x the head's radius); hang: under the chin (x the length); patch: bare under the lip
    "stubble": dict(T=0., J=0., hang=0., patch=False, must=None),
    "short": dict(T=.075, J=.11, hang=0., patch=False, must="short"),
    "full": dict(T=.09, J=.15, hang=1., patch=True, must="handlebar"),
    "long": dict(T=.1, J=.17, hang=1., patch=True, must="droop"),
    "goatee": dict(T=.08, J=.12, hang=1., patch=True, must="goatee"),
    "mustache": dict(T=0., J=0., hang=0., patch=False, must="handlebar")}


def edge_dist(bm):
    """each vertex's way in from the mesh's open edge, along it"""
    import heapq
    bm.verts.ensure_lookup_table()
    dist = [1e9] * len(bm.verts)
    edge = {v.index for e in bm.edges if len(e.link_faces) < 2 for v in e.verts}
    for i in edge:
        dist[i] = 0.
    hq = [(0., i) for i in edge]; heapq.heapify(hq)
    while hq:
        d0, i = heapq.heappop(hq)
        if d0 > dist[i]:
            continue
        for e in bm.verts[i].link_edges:
            j = e.other_vert(bm.verts[i]).index; dd = d0 + e.calc_length()
            if dd < dist[j]:
                dist[j] = dd; heapq.heappush(hq, (dd, j))
    return dist


def out_of_skin(p):
    """(how far the point is out of the skin, the skin's outward normal there)"""
    loc, nrm, fi, d = full.find_nearest(p)
    if loc is None:
        return 1., UP
    nn = nrm.normalized()
    return (p - loc).dot(nn), nn


def conform(bm, gap, reach):
    """the open edge put down on the skin (at gap), the way there spread in over reach and smoothed off: a piece made
    for another face (or rounded by a remesh) stood off the skin at its edge"""
    bm.verts.ensure_lookup_table()
    dist = edge_dist(bm)
    src = {}
    for v in bm.verts:
        if dist[v.index] == 0.:
            loc, nrm, fi, d = full.find_nearest(v.co)
            if loc is not None:
                nn = nrm.normalized()
                src[v.index] = loc + nn * gap - v.co
    if not src:
        return
    # (each vertex near the edge takes its nearest edge vertex's way, less and less further in)
    import heapq
    near = {i: i for i in src}; dd = {i: 0. for i in src}
    hq = [(0., i) for i in src]; heapq.heapify(hq)
    while hq:
        d0, i = heapq.heappop(hq)
        if d0 > dd.get(i, 1e9) or d0 > reach:
            continue
        for e in bm.verts[i].link_edges:
            j = e.other_vert(bm.verts[i]).index; d1 = d0 + e.calc_length()
            if d1 < dd.get(j, 1e9):
                dd[j] = d1; near[j] = near[i]; heapq.heappush(hq, (d1, j))
    for j, i in near.items():
        k = max(0., 1 - dd[j] / reach) ** 2
        bm.verts[j].co += src[i] * k


def push_out(bm, gap):
    for v in bm.verts:
        s, nn = out_of_skin(v.co)
        if s < gap:
            v.co += nn * (gap - s)


def raster_fade(m, fade, T):
    """a per-vertex value over the unwrap: rasterised from the triangles, barycentric"""
    out = np.zeros((T, T), np.float32)
    uvd = m.uv_layers[0].data
    for poly in m.polygons:
        li = list(poly.loop_indices)
        for t in range(1, len(li) - 1):
            tri = [li[0], li[t], li[t + 1]]
            pu = np.array([uvd[j].uv[0] * T for j in tri]); pv = np.array([uvd[j].uv[1] * T for j in tri])
            fv = np.array([fade[m.loops[j].vertex_index] for j in tri])
            x0, x1 = int(max(0, pu.min() - 1)), int(min(T - 1, pu.max() + 1))
            y0, y1 = int(max(0, pv.min() - 1)), int(min(T - 1, pv.max() + 1))
            if x1 < x0 or y1 < y0:
                continue
            gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
            den = (pv[1] - pv[2]) * (pu[0] - pu[2]) + (pu[2] - pu[1]) * (pv[0] - pv[2])
            if abs(den) < 1e-12:
                continue
            l0 = ((pv[1] - pv[2]) * (gx - pu[2]) + (pu[2] - pu[1]) * (gy - pv[2])) / den
            l1 = ((pv[2] - pv[0]) * (gx - pu[2]) + (pu[0] - pu[2]) * (gy - pv[2])) / den
            l2 = 1 - l0 - l1
            inside = (l0 >= -.02) & (l1 >= -.02) & (l2 >= -.02)
            val = l0 * fv[0] + l1 * fv[1] + l2 * fv[2]
            sub = out[y0:y1 + 1, x0:x1 + 1]
            sub[inside] = np.maximum(sub[inside], val[inside])
    return out


def normal_map(mat, hgt_img, name, s=6.):
    gy_, gx_ = np.gradient(hgt_img)
    nrm = np.dstack([-gx_ * s, -gy_ * s, np.ones_like(hgt_img)])
    nrm /= np.linalg.norm(nrm, axis=2, keepdims=True)
    nim = save(name, nrm * .5 + .5, False, colour=False)
    nim.colorspace_settings.name = "Non-Color"
    nt = mat.node_tree; b = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tn = nt.nodes.new("ShaderNodeTexImage"); tn.image = nim
    nm = nt.nodes.new("ShaderNodeNormalMap"); nt.links.new(tn.outputs[0], nm.inputs["Color"]); nt.links.new(nm.outputs[0], b.inputs["Normal"])


def face_frame():
    """the face's measures: the mouth (from the face's markup; without one from the profile), the lips, the nose's
    base, the chin, the head's half width by the height"""
    front = lambda p: (p - O).dot(FRONT)   # noqa: E731
    prof = []
    z = E.z - .1 * R
    while z > NK.z - .5 * R:
        h = cast(Vector((O.x, O.y, z)) + FRONT * (4 * R), BACK, 8 * R, tree=bvh)
        prof.append((z, front(h[0]) if h else -1e9))
        z -= R / 20
    iN = max((i for i in range(len(prof)) if prof[i][0] > E.z - 1.3 * R), key=lambda i: prof[i][1])
    mc, cL, cR, lt, lb = (FM.get(k) for k in ("mouth_c", "mouth_corner_L", "mouth_corner_R", "lip_top", "lip_bot"))
    if mc and cL and cR:
        yM, mx, u = mc.z, mc.x, (cL - cR).length
        lipUp = max(.06 * R, (lt.z - mc.z) if lt else .12 * R) * 1.25
        lipDn = max(.06 * R, (mc.z - lb.z) if lb else .12 * R) * 1.25
        fM = front(mc)
    else:   # (the lips: the profile's two bumps under the nose, the mouth the deepest between them)
        pk = [i for i in range(iN + 3, len(prof) - 2) if prof[i][1] >= max(prof[i - 1][1], prof[i + 1][1], prof[i - 2][1], prof[i + 2][1])]
        if len(pk) >= 2:
            iM = min(range(pk[0], pk[1] + 1), key=lambda i: prof[i][1])
        else:
            iM = min(range(len(prof)), key=lambda i: abs(prof[i][0] - (E.z - 1.25 * R)))
        yM, mx, u, lipUp, lipDn, fM = prof[iM][0], O.x, .75 * R, .15 * R, .15 * R, prof[iM][1]
    # the chin: its front the most forward under the lower lip; its bottom where the profile has gone well back
    # behind it (to the throat)
    ic = [i for i in range(len(prof)) if yM - lipDn - 1.2 * R <= prof[i][0] <= yM - lipDn]
    iF = max(ic, key=lambda i: prof[i][1]) if ic else None
    fC = prof[iF][1] if iF is not None else fM - .2 * R   # (the chin's front)
    iC = next((i for i in range(iF, len(prof)) if prof[i][1] < fC - .35 * R), None) if iF is not None else None
    yC = prof[iC][0] if iC is not None else yM - 1.1 * R
    yC = min(yM - .5 * R, max(yM - 1.8 * R, yC))
    # the nose's base: going down from its tip, where the profile has gone half way back to the upper lip's front
    # (its underside is about level: that is its bottom; the deepest point was the philtrum's, just over the lip)
    iL = min(range(len(prof)), key=lambda i: abs(prof[i][0] - (yM + .7 * lipUp)))
    half_f = prof[iN][1] - .5 * (prof[iN][1] - prof[iL][1])
    iS = next((i for i in range(iN, iL + 1) if prof[i][1] < half_f), iL)
    yS = max(yM + lipUp, min(yM + lipUp + .7 * R, prof[iS][0] - .02 * R))
    hw = {}

    def half(z):
        k = round(z / (R / 40))
        if k not in hw:
            # (from outside in: from inside a ray met the mouth's own skin first, and the jaw came out narrow)
            a = cast(Vector((O.x + 3 * R, O.y, z)), -X, 3 * R, tree=bvh); b = cast(Vector((O.x - 3 * R, O.y, z)), X, 3 * R, tree=bvh)
            hw[k] = max(3 * R - a[2] if a else R, 3 * R - b[2] if b else R)
        return hw[k]
    print("face: mouth %.3f chin %.3f nose base %.3f u %.4f marks %s" % (yM, yC, yS, u, bool(mc)), flush=True)
    if job.get("debug"):
        print("prof", iN, [(round(z, 4), round(f, 4)) for z, f in prof[:40]], flush=True)
    return dict(front=front, yM=yM, mx=mx, u=u, lipUp=lipUp, lipDn=lipDn, fM=fM, yC=yC, fC=fC, yS=yS, half=half,
                mw=.55 * u + .04 * R, yTop=yM + .55 * (E.z - yM))


def beard_field(F, kind, patch, outline=None):
    """where a beard grows, as a field: how far a point is inside it (< 0 outside) - its line smooth wherever it
    crosses the face's polygons (a yes/no per vertex was the skin's staircase). Each condition a margin: and the
    least of them, or the most, not the negative"""
    front, yM, mx, u, mw, fM, yC = F["front"], F["yM"], F["mx"], F["u"], F["mw"], F["fM"], F["yC"]
    AND, OR = min, max

    def near(p, k):   # (no further back than k mouth widths behind the mouth's front)
        return front(p) - (fM - k * u)

    def lips(p):
        return AND(p.z - (yM - F["lipDn"]), yM + F["lipUp"] - p.z, mw - abs(p.x - mx))

    def below(p):   # (under the mouth; under the jaw the throat only, not down the neck's sides)
        k = 1.6 + (1.05 - 1.6) * smooth(yC, yC - .4 * u, p.z)
        return AND(yM - F["lipDn"] - p.z, p.z - (NK.z + .15 * R), near(p, k), .92 * F["half"](p.z) - abs(p.x - O.x))

    def cheeks(p):   # (up to the moustache's ends in front, rising behind to the sideburns by the ears)
        bk = smooth(fM - .6 * u, fM - 1.5 * u, front(p))
        top = min(F["yTop"], yM + .45 * u)
        return AND(top + bk * max(0., E.z - .55 * R - top) - p.z, p.z - (yM - 2 * u), abs(p.x - mx) - .55 * u,
                   near(p, 1.25 + .35 * bk), OR(p.z - (yC - .2 * u), near(p, 1.05)))

    def lip_top(p):
        return AND(p.z - (yM + .6 * F["lipUp"]), min(F["yTop"], F["yS"]) - p.z, near(p, .45), 1.25 * mw - abs(p.x - mx))

    def bare(p):   # (the skin under the lower lip, as the sculpted one's: an oval, the upper part of the chin)
        top = yM - F["lipDn"]; hz = .5 * max(.15 * R, .45 * (top - yC))
        e = ((p.x - mx) / (.45 * u)) ** 2 + ((p.z - (top - .6 * hz)) / hz) ** 2
        return AND((1 - e) * hz, near(p, .6))

    def ear(p):
        loc, n, i, d = ear_pts.find_nearest(p)
        return (d if loc is not None else R) - .2 * R

    def field(p):
        m = AND(-lips(p), ear(p))
        if outline is not None:   # (its outline by its nodes: the user's, or the ones on the edge found here)
            return AND(m, outline(p))
        if kind == "stubble":
            return AND(m, OR(below(p), cheeks(p), lip_top(p)))
        if patch:
            m = AND(m, -bare(p))
        if kind == "goatee":
            return AND(m, below(p), 1.1 * mw - abs(p.x - mx), p.z - (yC - .3 * R))
        return AND(m, OR(below(p), cheeks(p)))
    return field


def beard_region(F, kind, patch, outline=None):
    fld = beard_field(F, kind, patch, outline)
    return lambda p: fld(p) > 0


# ---------------------------------------------------------------- fitting by hand: the outline's nodes on the skin
def gl2b(v):
    return Vector((v[0], -v[2], v[1]))


def b2gl(p):
    return [round(p.x, 5), round(p.z, 5), round(-p.y, 5)]


NODES_IN = {k: gl2b(v) for k, v in (prm.get("nodes") or {}).items() if isinstance(v, (list, tuple)) and len(v) == 3}
NODES_OUT, LOOP = {}, []
BEARD_LOOP = ["burn_R", "cheek_R", "corner_R", "chin_top", "corner_L", "cheek_L", "burn_L", "jaw_L", "throat", "jaw_R"]
GOATEE_LOOP = ["corner_R", "chin_top", "corner_L", "jaw_L", "throat", "jaw_R"]


_KD, EDGES, REP = None, None, None


def skin_kd():
    """the skin's vertices to look up by place; its edges with the copies a file makes along the unwrap's seams as
    one vertex (unwelded, a curve's wall had gaps at the seams and a fill got out through them)"""
    global _KD, EDGES, REP
    if _KD is None:
        from mathutils.kdtree import KDTree
        _KD = KDTree(len(V))
        for i, v in enumerate(V):
            _KD.insert(v, i)
        _KD.balance()
        REP = list(range(len(V)))
        for i, v in enumerate(V):
            if REP[i] == i:
                for _, j, _ in _KD.find_range(v, 1e-6):
                    if j > i:
                        REP[j] = i
        EDGES = {}
        for e in me.edges:
            i, j = REP[e.vertices[0]], REP[e.vertices[1]]
            if i != j:
                EDGES.setdefault(i, set()).add(j); EDGES.setdefault(j, set()).add(i)
    return _KD


def catmull_closed3(P, n):
    out, m = [], len(P)
    for i in range(m):
        p0, p1, p2, p3 = P[i - 1], P[i], P[(i + 1) % m], P[(i + 2) % m]
        for k in range(n):
            t = k / n; t2 = t * t; t3 = t2 * t
            out.append(.5 * (2 * p1 + (p2 - p0) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (3 * p1 - p0 - 3 * p2 + p3) * t3))
    return out


class Outline:
    """a closed outline on the skin through the nodes (a smooth curve, each point of it put down on the skin): it cuts
    the skin's mesh - along its edges - and what is inside is the part with the seed (the chin) in it. As a field:
    how far from the curve, + inside, - outside (smooth: the curve's own distance, not the mesh's staircase)"""

    def __init__(self, pts, seed, block=None):
        import heapq
        kd = skin_kd()
        bk = {REP[i] for i, v in enumerate(V) if block(v)} if block else set()
        # (put down on the outer skin: not into the mouth, not on an ear - a curve through the cheek went there)
        outer = BVHTree.FromPolygons(V, [f for f in P if not any(REP[i] in bk or i in ear_v for i in f)])
        cur = [outer.find_nearest(c)[0] or c for c in catmull_closed3([p.copy() for p in pts], 24)]
        self.cur = cur
        from mathutils.kdtree import KDTree
        self.kc = KDTree(len(cur))
        for i, c in enumerate(cur):
            self.kc.insert(c, i)
        self.kc.balance()

        def path(a, b):   # (the shortest way along the mesh's edges)
            if a == b:
                return [a]
            dist, prev, hq = {a: 0.}, {}, [(0., a)]
            while hq:
                d0, i = heapq.heappop(hq)
                if i == b:
                    break
                if d0 > dist[i] or d0 > 2 * R:
                    continue
                for j in EDGES.get(i, ()):
                    d1 = d0 + (V[j] - V[i]).length
                    if d1 < dist.get(j, 1e9):
                        dist[j] = d1; prev[j] = i; heapq.heappush(hq, (d1, j))
            out, i = [b], b
            while i != a and i in prev:
                i = prev[i]; out.append(i)
            return out
        ids = [REP[kd.find(c)[1]] for c in cur]
        # (the mouth a wall too, outside: the lower lip runs into the mouth and out over the upper one)
        wall = set()
        gaps = 0
        for k in range(len(ids)):
            pp = path(ids[k - 1], ids[k])
            if pp[-1] != ids[k - 1]:
                gaps += 1
            wall.update(pp)
        if job.get("debug"):
            jumps = sorted(((cur[k] - cur[k - 1]).length / R, k) for k in range(len(cur)))[-5:]
            print("outline gaps", gaps, "jumps/R", [(round(a, 2), k) for a, k in jumps], flush=True)
        on = set(wall)
        wall |= bk
        # (filled from a few places that should be inside - the chin, under it, the cheeks; a fill that got out - up
        # past the eyes, or a quarter of the body - was from outside: dropped)
        inside = set()
        for sp in seed:
            q = outer.find_nearest(sp)[0] or sp
            sd = REP[kd.find(q)[1]]
            if sd in wall:
                sd = next((j for j in EDGES.get(sd, ()) if j not in wall), None)
            if sd is None or sd in inside:
                continue
            got, st = {sd}, [sd]
            while st and len(got) < .25 * len(V):
                i = st.pop()
                for j in EDGES.get(i, ()):
                    if j not in got and j not in wall:
                        got.add(j); st.append(j)
            if job.get("debug"):
                print("fill", tuple(round(x, 3) for x in sp), len(got), round(max(V[i].z for i in got), 3), flush=True)
            if len(got) < .25 * len(V) and max(V[i].z for i in got) < E.z:
                inside |= got
        self.ok = len(inside) > 20
        self.inside, self.wall = inside, on
        print("outline: inside %d wall %d ok %s" % (len(inside), len(wall), self.ok), flush=True)

    def __call__(self, p):
        d = self.kc.find(p)[2]
        i = REP[skin_kd().find(p)[1]]
        return d if (i in self.inside or i in self.wall) else -d


def beard_nodes(F, kind, patch, loop):
    """the outline's nodes: the user's where given; the rest on the edge of where it grows by the face's measures -
    each rough place snapped to the nearest skin vertex on that edge"""
    fld = beard_field(F, kind, patch)
    near_ = [i for i, p in enumerate(V) if (p - O).length < 3.5 * R and p.z < E.z]
    val = {i: fld(V[i]) for i in near_}
    bnd = [i for i in near_ if val[i] > 0 and any(val.get(j, -1.) <= 0 for j in nbr.get(i, ()))]
    mx, yM, u, yC = F["mx"], F["yM"], F["u"], F["yC"]
    cf = O.y - F["fC"]
    tg = {"chin_top": Vector((mx, cf, yM - F["lipDn"] - .3 * u)), "throat": Vector((mx, cf + 1.1 * u, yC - .5 * u))}
    for sd, sn in ((1, "L"), (-1, "R")):
        tg["corner_" + sn] = Vector((mx + sd * .75 * u, O.y - F["fM"] + .3 * u, yM + .35 * u))
        tg["cheek_" + sn] = Vector((mx + sd * .85 * R, O.y - .55 * R, .5 * (yM + E.z) - .1 * R))
        tg["burn_" + sn] = Vector((O.x + sd * 1.0 * R, O.y - .05 * R, E.z - .6 * R))
        tg["jaw_" + sn] = Vector((O.x + sd * .75 * R, O.y + .1 * R, yC - .1 * R))
    out = {}
    for k in loop:
        if k in NODES_IN:
            out[k] = NODES_IN[k]
        elif bnd:
            out[k] = V[min(bnd, key=lambda i: (V[i] - tg[k]).length)].copy()
        else:
            out[k] = tg[k]
    return out


def beard_uv(F, p, conv):
    """the hairs down (v), across them round the head's axis (u); under the chin closing in on the wedge's point"""
    th = math.atan2(p.x - F["mx"], max(.5 * R, -(p.y - O.y)))   # (not round the axis under the jaw: it swirled there)
    return th * R * conv(p.z), -p.z


def flow_uv(bm, F):
    """the hairs' unwrap along their fall: each vertex, from the top down, takes its across (u) from the ones above it
    along the surface's steepest way up (their way down: the hairs fall that way), its along (v) as theirs and the way
    from them; where nothing is above (the beard's top edge, under the lips) across is round the head. So the hairs
    go straight down the cheeks and the chin, from the throat to the point under it, closing in on the point"""
    bm.verts.ensure_lookup_table(); bm.normal_update()
    UV = {}
    for v in sorted(bm.verts, key=lambda v: -v.co.z):
        n = v.normal
        asc = UP - n * n.dot(UP)
        al = asc.length
        ws, su, sv = 0., 0., 0.
        for e in v.link_edges:
            o = e.other_vert(v)
            if o.index not in UV:
                continue
            d = o.co - v.co; dl = d.length
            if dl < 1e-12:
                continue
            w = max(0., d.dot(asc) / (dl * al)) ** 8 if al > .15 else max(0., d.z / dl) ** 4   # (straight up: from the sides mixed, a herringbone in the middle)
            if w > 1e-6:
                ws += w; su += w * UV[o.index][0]; sv += w * (UV[o.index][1] + dl)
        if ws > 0:
            UV[v.index] = (su / ws, sv / ws)
        else:
            th = math.atan2(v.co.x - F["mx"], max(.5 * R, -(v.co.y - O.y)))
            UV[v.index] = (th * R, -v.co.z)
    return UV


def build_beard(st):
    cfg = BEARD[st]
    F = face_frame()
    vol = float(prm.get("vol", 1.))
    Lh = float(prm.get("length", .05)) * H * cfg["hang"]
    obs = []
    yM, mx, u, yC = F["yM"], F["mx"], F["u"], F["yC"]
    OL = None
    if st != "mustache":   # its outline's nodes (shown in the editor, moved there by hand)
        LOOP[:] = GOATEE_LOOP if st == "goatee" else BEARD_LOOP
        nodes = beard_nodes(F, st, cfg["patch"], LOOP)
        NODES_OUT.update(nodes)
        cf_ = O.y - F["fC"]
        seeds = [Vector((mx, cf_, .5 * (yC + yM - F["lipDn"]))), Vector((mx, cf_ + .5 * u, yC - .1 * u))]
        for a_, b_ in (("corner", "jaw"), ("cheek", "jaw"), ("burn", "corner")):
            for sn in "LR":
                if a_ + "_" + sn in nodes and b_ + "_" + sn in nodes:
                    seeds.append((nodes[a_ + "_" + sn] + nodes[b_ + "_" + sn]) / 2)
        mw = F["mw"]
        OL = Outline([nodes[k] for k in LOOP], seeds,
                     lambda v: abs(v.x - mx) < 1.1 * mw and yM - 1.2 * F["lipDn"] < v.z < yM + 1.2 * F["lipUp"])
        if not OL.ok:
            OL = None
    cf = O.y - F["fC"]
    kf = .25   # (the hanging part's lean forward, x its drop)
    if Lh > 0:
        tip = NODES_IN.get("tip")
        if tip is not None:   # (its point where the user put it: its length, its lean)
            Lh = max(.1 * R, yC - tip.z)
            kf = max(-.5, min(1.5, (cf - vol * R * cfg["J"] - tip.y) / Lh))
        NODES_OUT["tip"] = Vector((mx, cf - vol * R * cfg["J"] - kf * Lh, yC - Lh))
    if st == "stubble":
        fld = beard_field(F, "stubble", False, OL)
        sh = scalp_shell(lambda p: fld(p) > -.06 * R, lambda v: .006 * R, "hair_beard", close=3)
        bm = bmesh.new(); bm.from_mesh(sh.data)
        bm.verts.ensure_lookup_table()
        fade = {v.index: min(1., max(0., (fld(v.co) + .02 * R) / (.15 * R))) for v in bm.verts}
        conv = lambda z: 1.   # noqa: E731
        obs.append(_beard_skin(sh, bm, fade, F, conv, stubble=True))
    elif cfg["T"] > 0:
        a0 = 1.0 * u * vol ** .3   # (the hanging part's half width: as the sculpted one's, the mouth's width)
        front = F["front"]

        def shape(x):   # (its point in the middle)
            return max(0., 1 - abs(x - mx) / a0) ** 1.15

        def wid(z):   # the hanging part's half width at a height (to its point)
            if Lh <= 0 or z >= yC:
                return a0
            return a0 * max(.02, 1 - min(1., (yC - z) / Lh) ** (1 / 1.15))

        def conv(z):
            return min(2., a0 / max(1e-6, wid(z)))

        def by_mouth(p):   # (the edge round the lips and the bare skin under them: thick there, a sculpted edge)
            return yM - F["lipDn"] - 1.1 * u < p.z < yM + F["lipUp"] + .3 * u and abs(p.x - mx) < 1.05 * u and front(p) > F["fM"] - .7 * u
        # the mass on the skin: the region raised by its thickness (thin at its outer edge, not at the mouth's),
        # closed under (a solid); under the jaw it hangs: its outside drawn down - most at the chin's front, none at
        # the throat - to a point in the middle, a little forward, off the chest
        sh = scalp_shell(beard_region(F, st, cfg["patch"], OL), lambda v: 0., "beard_base", close=3)
        sb = bmesh.new(); sb.from_mesh(sh.data); bpy.data.objects.remove(sh, do_unlink=True)
        sb.normal_update(); sb.verts.ensure_lookup_table()
        for e in sb.edges:   # (the mouth's edge: not where the thickness starts)
            e.tag = len(e.link_faces) < 2 and all(by_mouth(v.co) for v in e.verts)
        import heapq
        dist = [1e9] * len(sb.verts)
        src = {v.index for e in sb.edges if len(e.link_faces) < 2 and not e.tag for v in e.verts}
        for i in src:
            dist[i] = 0.
        hq = [(0., i) for i in src]; heapq.heapify(hq)
        while hq:
            d0, i = heapq.heappop(hq)
            if d0 > dist[i]:
                continue
            for e in sb.verts[i].link_edges:
                j = e.other_vert(sb.verts[i]).index; dd = d0 + e.calc_length()
                if dd < dist[j]:
                    dist[j] = dd; heapq.heappush(hq, (dd, j))
        cb = bmesh.new(); vin, vout = {}, {}
        fC = F["fC"]
        for v in sb.verts:
            nn = v.normal.copy()
            if nn.dot(v.co - O) < 0:
                nn.negate()
            low = smooth(yM, yC - .3 * u, v.co.z)
            t = vol * R * (cfg["T"] + (cfg["J"] - cfg["T"]) * low) * min(1., dist[v.index] / (.3 * R)) ** .6
            q = v.co + nn * (.015 * R + t)
            if Lh > 0:
                g = smooth(yC + .7 * u, yC - .1 * u, v.co.z) * smooth(fC - 1.3 * R, fC - .15 * R, front(v.co))
                hang = Lh * shape(v.co.x) * g
                q = q - UP * hang + FRONT * (kf * hang)
            vin[v.index] = cb.verts.new(v.co - nn * (.015 * R)); vout[v.index] = cb.verts.new(q)
        for f in sb.faces:
            cb.faces.new([vout[v.index] for v in f.verts])
            cb.faces.new([vin[v.index] for v in reversed(f.verts)])
            for lp in f.loops:
                if len(lp.edge.link_faces) == 1:
                    a, b = lp.vert.index, lp.link_loop_next.vert.index
                    cb.faces.new((vout[b], vout[a], vin[a], vin[b]))
        if Lh <= .05 * R and cfg["T"] < .05:   # (thin, nothing hanging: its outside only, straight off the skin - a remesh lost it)
            cb.free(); sb.free()
            fld = beard_field(F, st, cfg["patch"], OL)
            sh = scalp_shell(lambda p: fld(p) > -.06 * R, lambda v: 0., "beard_base", close=3)   # (wider: its line drawn by the alpha)
            sb = bmesh.new(); sb.from_mesh(sh.data); bpy.data.objects.remove(sh, do_unlink=True)
            sb.normal_update(); sb.verts.ensure_lookup_table()
            dist = edge_dist(sb)
            mf = {v.index: fld(v.co) for v in sb.verts}
            tops = {}
            for v in sb.verts:
                nn = v.normal.copy()
                if nn.dot(v.co - O) < 0:
                    nn.negate()
                low = smooth(yM, yC - .3 * u, v.co.z)
                t = vol * R * (cfg["T"] + (cfg["J"] - cfg["T"]) * low) * min(1., max(0., mf[v.index]) / (.25 * R)) ** .6
                tops[v.index] = v.co + nn * (.015 * R + t)
            for v in sb.verts:
                v.co = tops[v.index]
            for _ in range(3):
                bmesh.ops.smooth_vert(sb, verts=[v for v in sb.verts if dist[v.index] > 0], factor=.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
            push_out(sb, .012 * R)
            for lay in list(sb.loops.layers.uv.values()):
                sb.loops.layers.uv.remove(lay)
            mv = bpy.data.meshes.new("beard_thin"); ob = bpy.data.objects.new("hair_beard", mv); sc.collection.objects.link(ob)
            if job.get("debug"):
                dm = bpy.data.meshes.new("dbg_thin"); sb.to_mesh(dm); dbo = bpy.data.objects.new("dbg_thin", dm); sc.collection.objects.link(dbo)
            fade = {i: min(1., max(0., (m + .02 * R) / (.12 * R))) for i, m in mf.items()}
            obs.append(_beard_skin(ob, sb, fade, F, conv))
            if cfg["must"]:
                obs.append(moustache(F, cfg["must"], vol, float(prm.get("length", .05))))
            return obs, obs[0]
        sb.free()
        for v in list(vout.values()):   # (a long one off the chest: it lies on it)
            s_, nn = out_of_skin(v.co)
            if v.co.z < yC - .3 * R and s_ < .12 * R:
                v.co += nn * (.12 * R - s_)
        mv = bpy.data.meshes.new("beard_vol"); cb.to_mesh(mv); cb.free()
        ob = bpy.data.objects.new("hair_beard", mv); sc.collection.objects.link(ob)
        # one body of the two: remeshed (voxels), smoothed
        rm = ob.modifiers.new("vox", "REMESH"); rm.mode = "VOXEL"; rm.voxel_size = (.03 if Lh > .05 * R else .022) * R; rm.adaptivity = 0
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.modifier_apply(modifier=rm.name)
        if job.get("debug"):
            dbg = ob.copy(); dbg.data = ob.data.copy(); dbg.name = "dbg_remesh"; sc.collection.objects.link(dbg)
        bm = bmesh.new(); bm.from_mesh(ob.data)
        for _ in range(4):
            bmesh.ops.smooth_vert(bm, verts=bm.verts[:], factor=.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
        # only what is out of the skin: its underside on the face, the wedge's back in the throat gone
        bm.normal_update()
        drop = []
        for f in bm.faces:
            s, nn = out_of_skin(f.calc_center_median())
            if s < (.03 if Lh > .05 * R else .022) * R or (s < .12 * R and f.normal.dot(nn) < -.2):
                drop.append(f)
        if job.get("debug"):
            print("beard faces", len(bm.faces), "dropped", len(drop), flush=True)
        bmesh.ops.delete(bm, geom=drop, context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        bm.faces.ensure_lookup_table()
        seen, isl = set(), []
        for f0 in bm.faces:   # (crumbs off: its biggest pieces only)
            if f0.index in seen:
                continue
            stk, cur = [f0], []; seen.add(f0.index)
            while stk:
                f = stk.pop(); cur.append(f)
                for e in f.edges:
                    for g in e.link_faces:
                        if g.index not in seen:
                            seen.add(g.index); stk.append(g)
            isl.append(cur)
        big = max(len(i) for i in isl)
        bmesh.ops.delete(bm, geom=[f for i in isl if len(i) < .12 * big for f in i], context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        conform(bm, .012 * R, .35 * R)   # (its edge down on the skin)
        push_out(bm, .012 * R)
        bm.verts.ensure_lookup_table()
        dist = edge_dist(bm)
        # dense at the skin (only a short fringe of hairs at its edge there), the hairs thinning to its ends (the
        # hanging part's lower half, to the point)
        fade = {}
        for v in bm.verts:
            end = smooth(yC - .45 * Lh, yC - 1.05 * Lh, v.co.z) if Lh > .05 * R else 0.
            fade[v.index] = min(min(1., dist[v.index] / (.05 * R)), 1 - .85 * end ** .8)
        obs.append(_beard_skin(ob, bm, fade, F, conv))
    if cfg["must"]:
        obs.append(moustache(F, cfg["must"], vol, float(prm.get("length", .05))))
    return obs, obs[0]


def _beard_skin(ob, bm, fade, F, conv, stubble=False):
    """the hairs over a beard's mass: its unwrap (down, round the head), fine hairs and clumps in its texture and
    normal map, clumps as grooves in its shape; its edge fading out (the alpha)"""
    for lay in list(bm.loops.layers.uv.values()):
        bm.loops.layers.uv.remove(lay)
    UVV = flow_uv(bm, F)
    us = [a for a, _ in UVV.values()]; vs = [b for _, b in UVV.values()]
    u0, v0, span = min(us), min(vs), max(max(us) - min(us), max(vs) - min(vs)) + 1e-6
    uvl = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        for lp in f.loops:
            a, b = UVV[lp.vert.index]
            lp[uvl].uv = ((a - u0) / span, (b - v0) / span)
    m = ob.data; bm.to_mesh(m); bm.free()
    for poly in m.polygons:
        poly.use_smooth = True
    T = 1024
    PF, PC = 1.6 * R, 1.1 * R   # (a fine tile's, a clumps tile's size on the face)
    fine = strands_tile(512, 512, 260, 1.5, 3., 31, False)
    clumps = strands_tile(256, 256, 18, 14, 26, 32, True)
    uu = (np.arange(T) + .5) / T * span + u0
    vv = (np.arange(T) + .5) / T * span + v0
    UU, VV = np.meshgrid(uu, vv)
    fi = fine[((VV / PF * 512) % 512).astype(int), ((UU / PF * 512) % 512).astype(int)]
    cl = clumps[((VV / PC * 256) % 256).astype(int), ((UU / PC * 256) % 256).astype(int)]
    fd = raster_fade(m, fade, T)
    img = np.zeros((T, T, 4), np.float32)
    if stubble:   # (short hairs, a light shadow between them: the skin seen through)
        rs = np.random.default_rng(7)
        dots = np.zeros((T, T), np.float32)
        for _ in range(int(T * T * .045)):
            x, y = rs.integers(0, T, 2); ln = rs.integers(2, 6)
            dots[y:y + ln, x] = .6 + .4 * rs.random()
        lum = .18 + .1 * (1 - dots)
        img[..., 3] = np.clip(np.maximum(dots * .95, .28), 0, 1) * np.clip(fd * 1.2, 0, 1)
    else:
        k = np.clip(fi * .6 + .3, 0, 1) * np.clip(cl * .5 + .6, 0, 1.1)
        lum = .4 + .6 * np.clip(k, 0, 1)
        # (where it covers: whole; thinning, only the hairs - each one there or not, no see-through speckle)
        img[..., 3] = np.clip((fd - .25 + .6 * fi + .15 * cl) * 4, 0, 1)
    img[..., :3] = lum[..., None] * COL[None, None, :]
    mat, _ = material("hair_beard", save("beard", img, True), True, .55)
    normal_map(mat, fi * .4 + cl * .6, "beard_normal")
    m.materials.append(mat)
    if not stubble:   # the clumps as grooves in the shape (applied: a game takes the mesh)
        ctex = bpy.data.textures.new("clumps", "IMAGE")
        cim = bpy.data.images.new(f"{STEM}_clumps_h", 256, 256)
        cim.pixels.foreach_set(np.dstack([clumps, clumps, clumps, np.ones_like(clumps)]).astype(np.float32).ravel())
        cim.pack()
        ctex.image = cim
        uvt = m.uv_layers.new(name="tile")
        for poly in m.polygons:
            for li in poly.loop_indices:
                a, b = UVV[m.loops[li].vertex_index]
                uvt.data[li].uv = (a / PC, b / PC)
        fl = ob.vertex_groups.new(name="deep")   # (not at its edge: it lies on the skin there)
        for v in m.vertices:
            fl.add([v.index], fade[v.index], "REPLACE")
        dsp = ob.modifiers.new("grooves", "DISPLACE"); dsp.texture = ctex; dsp.texture_coords = "UV"; dsp.uv_layer = "tile"
        dsp.strength = .06 * R; dsp.mid_level = .5; dsp.vertex_group = "deep"
        bpy.context.view_layer.objects.active = ob
        for md in list(ob.modifiers):
            bpy.ops.object.modifier_apply(modifier=md.name)
        m.uv_layers.remove(m.uv_layers["tile"])
        ob.vertex_groups.remove(ob.vertex_groups["deep"])
    return ob


def moustache(F, kind, vol, length):
    """two thick locks from the middle under the nose out along the upper lip over the mouth's corners, tapering to a
    point: a handlebar's ends curled up, a long beard's drooping to the chin, a short one's ending at the corners"""
    yM, mx, u, yS = F["yM"], F["mx"], F["u"], F["yS"]
    kl = (length / .045) ** .5 if kind == "handlebar" and style == "mustache" else 1.
    span, drop, curl, hk = {"handlebar": (1.3, .3, .38, 1.25), "short": (.62, .1, 0., .9), "droop": (1.1, 1.2, 0., 1.25),
                            "goatee": (.8, 1.0, 0., 1.)}[kind]
    span *= u * kl; drop *= u; curl *= u * kl
    low = yM - (.12 if kind != "short" else -.25) * u   # (its lower edge: over the mouth's line; a short one's above it)
    nb = {}

    def nose_bottom(x):
        """the nose's lower outline at a width: going up from the upper lip, where the profile there comes forward
        (the nose's wings higher than its middle); none past the wings"""
        k = round((x - mx) / (.02 * R))
        if k not in nb:
            f0, out, z = None, None, yM + .6 * F["lipUp"]
            while z < E.z - .3 * R:
                h = cast(Vector((x, O.y - 4 * R, z)), BACK, 8 * R, tree=bvh)
                f = F["front"](h[0]) if h else -1e9
                if f0 is None:
                    f0 = f
                elif f > f0 + .22 * R:
                    out = z; break
                else:
                    f0 = max(f0, f) if f < f0 + .05 * R else f0
                z += .01 * R
            nb[k] = out
        return nb[k]
    rf = max(.6 * R, F["fM"])   # (the face's radius at the mouth)
    bm = bmesh.new(); uvl = bm.loops.layers.uv.new("UVMap")
    Nr, M = 30, 12
    span0, drop0, curl0 = span, drop, curl
    for sd in (1, -1):
        cen, hs, ds = [], [], []
        span, drop, curl = span0, drop0, curl0
        tn = NODES_IN.get("must_L" if sd > 0 else "must_R")
        if tn is not None:   # (its end where the user put it: how far out, how high)
            span = rf * math.asin(min(.98, abs(tn.x - mx) / rf)) + .02 * R
            dz1 = tn.z - .5 * (yS + low)
            if kind == "droop":
                drop = -dz1
            else:
                curl = dz1 + drop
        for i in range(Nr + 1):
            s = -.08 + 1.08 * i / Nr
            ph = sd * max(0., s) * span / rf
            dz = -drop * math.sin(min(1., max(0., s) / .75) * math.pi / 2) + curl * max(0., (s - .55) / .45) ** 2
            if kind == "droop":   # (down past the corners to the jaw)
                dz = -drop * max(0., s) ** 1.3
            # its top under the nose all along it (up under the wings), its bottom over the mouth's line; tapering
            top = yS + dz
            n_b = nose_bottom(mx + sd * max(0., s) * span)
            if n_b is not None:   # (blended off past the wings: no step)
                wn = 1 - smooth(.4, .75, s)
                top = top + wn * max(0., n_b - .015 * R - top)
            bot = low + dz
            tap = max(.04, (1 - max(0., s) ** 1.6)) ** .7
            zc = .5 * (top + bot)
            hgt = max(.05 * R, .5 * (top - bot)) * tap * (.9 + .1 * hk * vol ** .5)
            dep = min(hgt * .75, .11 * R * vol ** .5) if hgt > .02 * R else hgt * .75
            d = Vector((math.sin(ph), -math.cos(ph), 0))
            h = cast(Vector((mx, O.y, zc)) + d * (3 * R), -d, 3 * R, tree=bvh)   # (from outside: not the mouth's inside)
            if h:
                nn = h[1].normalized()
                nn = nn if nn.dot(d) > 0 else -nn
                c = h[0] + nn * (.015 * R + dep)
            else:
                c = cen[-1] + d * (span / Nr) if cen else Vector((mx, O.y - rf, zc))
            cen.append(c); hs.append(hgt); ds.append(dep)
        for _ in range(3):   # (its line smooth over the lips' bumps)
            cen = [cen[0]] + [(cen[i - 1] + cen[i] * 2 + cen[i + 1]) / 4 for i in range(1, len(cen) - 1)] + [cen[-1]]
        NODES_OUT["must_L" if sd > 0 else "must_R"] = cen[-1].copy()
        rows, sl = [], 0.
        for i, c in enumerate(cen):
            if i:
                sl += (c - cen[i - 1]).length
            t = (cen[min(len(cen) - 1, i + 1)] - cen[max(0, i - 1)]).normalized()
            n1 = (UP - t * UP.dot(t)).normalized(); n2 = t.cross(n1).normalized()
            rows.append(([bm.verts.new(c + n1 * (math.cos(a) * hs[i]) + n2 * (math.sin(a) * ds[i])) for a in (j / M * 2 * math.pi for j in range(M))], sl))
        cap = list(rows[0][0]) if sd < 0 else list(reversed(rows[0][0]))   # (its root closed)
        fc = bm.faces.new(cap)
        for lp in fc.loops:
            lp[uvl].uv = (.5, 0.)
        for i in range(len(rows) - 1):
            for j in range(M):
                q = [rows[i][0][j], rows[i + 1][0][j], rows[i + 1][0][(j + 1) % M], rows[i][0][(j + 1) % M]]
                uq = [(j / M, rows[i][1]), (j / M, rows[i + 1][1]), ((j + 1) / M, rows[i + 1][1]), ((j + 1) / M, rows[i][1])]
                if sd < 0:
                    q.reverse(); uq.reverse()
                f = bm.faces.new(q)
                for lp, (a, b) in zip(f.loops, uq):
                    lp[uvl].uv = (a, b / (1.5 * R))
    push_out(bm, .01 * R)   # (not into the upper lip's bulge: a thin one's middle went behind it)
    for _ in range(2):   # (the push's bumps off)
        bmesh.ops.smooth_vert(bm, verts=bm.verts[:], factor=.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bm.normal_update()
    mm = bpy.data.meshes.new("hair_moustache"); bm.to_mesh(mm); bm.free()
    ob = bpy.data.objects.new("hair_moustache", mm); sc.collection.objects.link(ob)
    for poly in mm.polygons:
        poly.use_smooth = True
    tile = strands_tile(256, 512, 90, 1.5, 3., 41, False)
    cl = strands_tile(128, 256, 10, 8, 14, 42, True)
    cl2 = np.kron(cl, np.ones((2, 2), np.float32))
    k = np.clip(tile * .6 + .3, 0, 1) * np.clip(cl2 * .5 + .6, 0, 1.1)
    lum = .42 + .58 * np.clip(k, 0, 1)
    img = np.zeros((512, 256, 3), np.float32); img[...] = lum[..., None] * COL[None, None, :]
    mat, _ = material("hair_moustache", save("moustache", img, False), False, .55)
    normal_map(mat, tile * .4 + cl2 * .6, "moustache_normal")
    mm.materials.append(mat)
    return ob


# ---------------------------------------------------------------- a wig: the hair of a head made elsewhere (Tripo)
def build_wig(model, kind="hair"):
    """the model's hair told from its skin by the texture's colour (two clusters: a wig's hair the one over the top of
    the head; a beard's the one on the chin, its skin the more of the head's), small islands of it dropped (brows,
    a moustache drawn on the skin); its head aligned to the character's (its skin points onto the character's head
    skin, scale and all: ICP); a wig without the model's beard, a beard below the eyes only; pushed out of the body
    (the push smoothed over it); a wig's dark cap under it, only where its hair is over it (no skin between the
    locks, no dark band on the forehead)"""
    from mathutils import Matrix
    gi = {g.index: g.name for g in skin.vertex_groups}
    ours = []
    for v in me.vertices:
        ws = {gi[g.group]: g.weight for g in v.groups}
        tot = sum(ws.values()) or 1
        if ws.get(names["head"], 0) / tot > .5:
            ours.append(list(skin.matrix_world @ v.co))
    ours = np.array(ours)
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=model)
    new = [o for o in bpy.data.objects if o not in before]
    tobj = max((o for o in new if o.type == "MESH"), key=lambda o: len(o.data.vertices), default=None)
    if tobj is None:
        fail(_t("ag.wig_no_mesh", Path(model).name))
    bpy.context.view_layer.update()
    tm = tobj.data
    import re
    ims = [n.image for m in tm.materials if m and m.use_nodes for n in m.node_tree.nodes if n.type == "TEX_IMAGE" and n.image]
    ims = [im for im in ims if not re.search(r"normal|_rm\b|_rm\.|rough|metal|_orm|occlusion", im.name.lower())]
    img = next((im for im in ims if re.search(r"base|colou?r|albedo|diffuse", im.name.lower())), ims[0] if ims else None)   # (the colour's, not the normals', the roughness')
    if img is None:
        fail(_t("ag.wig_no_texture", Path(model).name))
    w_, h_ = img.size
    px = np.array(img.pixels[:], np.float32).reshape(h_, w_, 4)
    uvd = tm.uv_layers.active.data
    col = np.zeros((len(tm.vertices), 3)); cnt = np.zeros(len(tm.vertices))
    for lp in tm.loops:
        u, v = uvd[lp.index].uv
        col[lp.vertex_index] += px[int((v % 1) * (h_ - 1)), int((u % 1) * (w_ - 1)), :3]; cnt[lp.vertex_index] += 1
    col /= np.maximum(cnt, 1)[:, None]
    zs = np.array([(tobj.matrix_world @ v.co).z for v in tm.vertices])
    # two colour clusters (k-means), the hair's the one higher up (the top of the head is hair, whatever its colour)
    c0, c1 = col[zs > np.percentile(zs, 95)].mean(0), col[zs < np.percentile(zs, 50)].mean(0)
    for _ in range(12):
        lab = np.linalg.norm(col - c0, axis=1) < np.linalg.norm(col - c1, axis=1)
        if lab.all() or (~lab).all():
            break
        c0, c1 = col[lab].mean(0), col[~lab].mean(0)
    upper = lab if zs[lab].mean() > zs[~lab].mean() else ~lab
    # the skin for the alignment: a wig's - not the hair over the top; a beard's - the more of the head
    skin_icp = ~upper if kind == "hair" else (lab if lab.sum() > (~lab).sum() else ~lab)
    bm = bmesh.new(); bm.from_mesh(tm); bm.transform(tobj.matrix_world)
    for lay in list(bm.verts.layers.deform.values()):
        bm.verts.layers.deform.remove(lay)
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    sk = np.array([list(v.co) for v in bm.verts if skin_icp[v.index]])   # (the skin's points for the alignment)
    allv = np.array([list(v.co) for v in bm.verts])
    zc = sk[:, 2].min() + .35 * (sk[:, 2].max() - sk[:, 2].min())
    tsel = sk[sk[:, 2] > zc]   # (the bust's head, not its shoulders)
    if len(tsel) < 50 or len(ours) < 50:
        fail(_t("ag.wig_no_head", Path(model).name))
    s = (ours[:, 0].max() - ours[:, 0].min()) / max(1e-9, tsel[:, 0].max() - tsel[:, 0].min())   # (ear tip to ear tip)
    Rm = np.eye(3); t = ours.mean(0) - s * tsel.mean(0)
    for it in range(40):
        Y = s * (tsel @ Rm.T) + t
        pairs = []
        for i in range(0, len(Y), max(1, len(Y) // 3000)):
            loc, n, fi, d = full.find_nearest(Vector(Y[i]))
            if loc is not None:
                pairs.append((i, np.array(list(loc)), d))
        ds = np.array([q[2] for q in pairs]); cut = np.percentile(ds, 80)
        A = np.array([tsel[i] for i, q, d in pairs if d <= cut]); B = np.array([q for i, q, d in pairs if d <= cut])
        ma, mb = A.mean(0), B.mean(0); A0, B0 = A - ma, B - mb
        U, S_, Vt = np.linalg.svd(B0.T @ A0)
        D = np.eye(3); D[2, 2] = np.sign(np.linalg.det(U @ Vt))
        Rm = U @ D @ Vt; s = (S_ * np.diag(D)).sum() / (A0 ** 2).sum(); t = mb - s * (Rm @ ma)
    print("wig: icp %.4f of R, scale %.5f" % (ds.mean() / R, s), flush=True)
    M = Matrix(((*(s * Rm[0]), t[0]), (*(s * Rm[1]), t[1]), (*(s * Rm[2]), t[2]), (0, 0, 0, 1)))
    Pt = s * (allv @ Rm.T) + t   # (each vertex where it lands on the character)
    if kind == "hair":
        is_hair = upper.copy()
        # (not the model's beard, a moustache: in front of the face below the eyes)
        is_hair &= ~((Pt[:, 2] < E.z - .3 * R) & (Pt[:, 1] < O.y - .4 * R) & (np.abs(Pt[:, 0] - O.x) < .7 * R))
    else:
        # the beard's colour: the one most on the chin (in front, below the mouth); only below the eyes
        chin = (Pt[:, 2] < E.z - 1.1 * R) & (Pt[:, 2] > E.z - 2.6 * R) & (Pt[:, 1] < O.y - .4 * R) & (np.abs(Pt[:, 0] - O.x) < .5 * R)
        hc = lab if (lab & chin).sum() >= (~lab & chin).sum() else ~lab
        if not (hc & chin).any():
            hc = ~skin_icp
        is_hair = hc & (Pt[:, 2] < E.z - .15 * R)
    hl = bm.faces.layers.int.new("hair")
    for f in bm.faces:
        f[hl] = 1 if all(is_hair[v.index] for v in f.verts) else 0
    # (welded first: the file splits its vertices along the unwrap's seams - unwelded, the head's skin fell apart into
    # the unwrap's islands, and the pushed vertices opened cracks; the unwrap is kept, it is the corners')
    span = max((max(v.co[i] for v in bm.verts) - min(v.co[i] for v in bm.verts)) for i in range(3))
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5 * span)
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    hf = {f.index for f in bm.faces if f[hl]}
    seen, islands = set(), []
    for f0 in hf:
        if f0 in seen:
            continue
        st, isl = [f0], []; seen.add(f0)
        while st:
            fi = st.pop(); isl.append(fi)
            for e in bm.faces[fi].edges:
                for g in e.link_faces:
                    if g.index in hf and g.index not in seen:
                        seen.add(g.index); st.append(g.index)
        islands.append(isl)
    if not islands:
        fail(_t("ag.wig_no_hair", Path(model).name))
    big = max(len(i) for i in islands)
    keep = {f for isl in islands if len(isl) >= .02 * big for f in isl}
    # (and the skin's small islands inside the hair are hair: the locks' light highlights read as skin by colour -
    # the head's skin is one big piece)
    sk_f = {f.index for f in bm.faces if f.index not in keep}
    seen_s, sk_isl = set(), []
    for f0 in sk_f:
        if f0 in seen_s:
            continue
        st, isl = [f0], []; seen_s.add(f0)
        while st:
            fi = st.pop(); isl.append(fi)
            for e in bm.faces[fi].edges:
                for g in e.link_faces:
                    if g.index in sk_f and g.index not in seen_s:
                        seen_s.add(g.index); st.append(g.index)
        sk_isl.append(isl)
    if sk_isl:
        bigs = max(len(i) for i in sk_isl)
        for isl in sk_isl:
            if len(isl) < (.05 if kind == "hair" else .01) * bigs:   # (a beard: only specks - the skin under the lip, round the mouth, is a hole of its own)
                keep |= set(isl)
    # (and two rings of faces round them: the hair's edge is drawn by the texture's alpha below, not by the faces'
    # staircase - kept whole, a face only when all its corners were hair, it left ragged edges and holes)
    core_f = set(keep)
    for _ in range(2):
        keep |= {g.index for fi in list(keep) for v in bm.faces[fi].verts for g in v.link_faces}
    keep = {f for f in keep if f in core_f or bm.faces[f][hl] or
            any(g.index in core_f for v in bm.faces[f].verts for g in v.link_faces)}   # (by the faces' marks: welded, the vertices are numbered anew)
    hair_col = col[is_hair].mean(0) if is_hair.any() else col.mean(0)
    bm.transform(M)
    lay = bm.faces.layers.int.new("core")   # (the faces surely hair: solid; the rings round them cut by the alpha)
    bm.faces.ensure_lookup_table()
    for f in bm.faces:
        f[lay] = 1 if f.index in core_f else 0
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in keep], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.verts.ensure_lookup_table()
    gap = (.08 if kind == "hair" else .02) * R   # out of the body, the push smoothed over the hair (no dents where one lock met the skin)
    vec = [Vector()] * len(bm.verts)
    for v in bm.verts:
        loc, n, fi, d = full.find_nearest(v.co)
        if loc is None:
            continue
        nn = n.normalized(); side = (v.co - loc).dot(nn)
        if side < gap:
            vec[v.index] = nn * (gap - side)
    for _ in range(6):
        nv = []
        for v in bm.verts:
            nb = [e.other_vert(v).index for e in v.link_edges]
            avg = sum((vec[j] for j in nb), Vector()) / max(1, len(nb))
            nv.append(vec[v.index] if vec[v.index].length > avg.length else avg * .9 + vec[v.index] * .1)
        vec = nv
    for v in bm.verts:
        v.co += vec[v.index]
    if kind != "hair":   # (a beard made for another face: its edge put down on this one's skin - it stood off it)
        conform(bm, .012 * R, .4 * R)
        push_out(bm, .012 * R)
        # (but not on the lips: the model's mouth is not this one's - its bits round its own mouth, put down, lay
        # on the lips; a moustache over them stays, it is off the skin)
        F = face_frame()
        on_lips = [f for f in bm.faces if (lambda c: F["yM"] - 1.3 * F["lipDn"] < c.z < F["yM"] + F["lipUp"] and abs(c.x - F["mx"]) < F["mw"]
                                                    and out_of_skin(c)[0] < .05 * R)(f.calc_center_median())]
        bmesh.ops.delete(bm, geom=on_lips, context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    hm = bpy.data.meshes.new("hair_wig"); bm.to_mesh(hm); bm.free()
    # the colour with an alpha of how much each texel is hair (by its colour against the two clusters', soft at the
    # line): the hair's edge as drawn, cut by it (glTF MASK; dithered in the editor)
    c_h, c_s = (c0, c1) if zs[lab].mean() > zs[~lab].mean() else (c1, c0)
    rgb = px[..., :3]
    d_h = np.linalg.norm(rgb - c_h[None, None, :], axis=2); d_s = np.linalg.norm(rgb - c_s[None, None, :], axis=2)
    hairness = d_s / np.maximum(d_h + d_s, 1e-6)
    alpha = np.clip((hairness - .42) / .16, 0, 1) if kind == "hair" else np.clip((hairness - .6) / .1, 0, 1)   # (a beard's edge stricter: the model's skin showed as a yellow fringe)
    rgba = np.dstack([rgb, alpha]).astype(np.float32)
    aim = bpy.data.images.new(f"{STEM}_wig_color", w_, h_, alpha=True)
    aim.colorspace_settings.name = img.colorspace_settings.name   # (before the pixels: changed after, a new image is made again - blank)
    aim.pixels.foreach_set(rgba.ravel())
    aim.filepath_raw = str(WORK / f"{STEM}_wig_color.png"); aim.file_format = "PNG"; aim.save()
    mats = []
    for m in tm.materials:
        if m and m.use_nodes:
            nt = m.node_tree
            b = next((n for n in nt.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if b is not None:
                for l in list(b.inputs["Alpha"].links):
                    nt.links.remove(l)
                for l in list(b.inputs["Base Color"].links):
                    nt.links.remove(l)
                t = nt.nodes.new("ShaderNodeTexImage"); t.image = aim
                src_uv = next((n for n in nt.nodes if n.type == "TEX_IMAGE" and n.image == img), None)
                if src_uv is not None and src_uv.inputs[0].links:
                    nt.links.new(src_uv.inputs[0].links[0].from_socket, t.inputs[0])
                nt.links.new(t.outputs[0], b.inputs["Base Color"])
                rd = nt.nodes.new("ShaderNodeMath"); rd.operation = "ROUND"
                nt.links.new(t.outputs["Alpha"], rd.inputs[0]); nt.links.new(rd.outputs[0], b.inputs["Alpha"])
            if hasattr(m, "blend_method"):
                try:
                    m.blend_method = "CLIP"
                except TypeError:
                    pass
            m.name = "hair_wig_edge"
            solid = m.copy(); solid.name = "hair_wig"   # (the solid one: the same colour, not cut - the hair's light highlights cut out showed dark slits)
            sb = next((n for n in solid.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if sb is not None:
                for l in list(sb.inputs["Alpha"].links):
                    solid.node_tree.links.remove(l)
                sb.inputs["Alpha"].default_value = 1.0
            if hasattr(solid, "blend_method"):
                try:
                    solid.blend_method = "OPAQUE"
                except TypeError:
                    pass
            mats.append((solid, m))
    for solid, edge in mats[:1]:
        hm.materials.append(solid); hm.materials.append(edge)
    ca = hm.attributes.get("core")
    if ca is not None and mats:
        for poly, d in zip(hm.polygons, ca.data):
            poly.material_index = 0 if d.value else 1
        hm.attributes.remove(ca)
    wig = bpy.data.objects.new("hair_wig", hm); sc.collection.objects.link(wig)
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    for poly in hm.polygons:
        poly.use_smooth = True
    if kind != "hair":
        return [wig], wig
    cap = scalp_shell(hairline, lambda v: .05 * R, "hair_cap")
    # (only where the wig's solid hair is over all of a face: past its own hairline - under the edge cut by the alpha
    # too - the cap showed as dark steps on the forehead; the body's mask is the cap's, so the skin stays there)
    wt = BVHTree.FromPolygons([wig.matrix_world @ v.co for v in hm.vertices],
                              [list(p.vertices) for p in hm.polygons if p.material_index == 0])
    cb = bmesh.new(); cb.from_mesh(cap.data); cb.faces.ensure_lookup_table()

    def under(c):
        n = (c - O).normalized()
        return wt.ray_cast(c + n * (.01 * R), n, .9 * R)[0] is not None or wt.ray_cast(c - n * (.05 * R), n, .9 * R)[0] is not None
    drop = [f for f in cb.faces if not all(under(v.co) for v in f.verts)]
    bmesh.ops.delete(cb, geom=drop, context="FACES")
    cb.to_mesh(cap.data); cb.free()
    mc = bpy.data.materials.new("hair_cap"); mc.use_nodes = True
    b = next(n for n in mc.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    hc = np.clip(hair_col, 0, 1); hc = np.where(hc <= .04045, hc / 12.92, ((hc + .055) / 1.055) ** 2.4)   # (the texture's sRGB to the material's linear: else the cap came out lighter than the hair)
    b.inputs["Base Color"].default_value = (*(hc * .45), 1); b.inputs["Roughness"].default_value = .8
    cap.data.materials.append(mc)
    for poly in cap.data.polygons:
        poly.use_smooth = True
    return [wig, cap], cap


# ---------------------------------------------------------------- the style
if style.startswith("wig"):
    if not prm.get("model") or not Path(prm["model"]).is_file():
        fail(_t("ag.wig_no_model"))
    obs, mask_of = build_wig(prm["model"], "beard" if job.get("piece") == "beard" else "hair")
elif job.get("piece") == "beard":
    if style not in BEARD:
        fail(_t("ag.unknown_piece", style))
    obs, mask_of = build_beard(style)
    if job.get("debug"):
        bpy.ops.wm.save_as_mainfile(filepath=str(WORK / f"{STEM}_debug.blend"))
else:   # a hairstyle made here: its hairline's nodes (shown in the editor, moved there by hand)
    HAIR_ANG = {"front": 0, "temple_L": 40, "ear_L": 90, "back_L": 135, "nape": 180, "back_R": -135, "ear_R": -90, "temple_R": -40}
    LOOP[:] = ["front", "temple_L", "ear_L", "back_L", "nape", "back_R", "ear_R", "temple_R"]
    if any(k in NODES_IN for k in LOOP):
        HL = sorted(((math.atan2((NODES_IN[k] - O).x, -(NODES_IN[k] - O).y), (NODES_IN[k] - O).z) if k in NODES_IN
                     else (math.radians(a) if a < 180 else math.pi, zmin_default(math.radians(a))) for k, a in HAIR_ANG.items()))
    for k, a in HAIR_ANG.items():
        if k in NODES_IN:
            NODES_OUT[k] = NODES_IN[k]
            continue
        th = math.radians(a); zz = O.z + zmin_at(th)
        d = Vector((math.sin(th), -math.cos(th), 0))
        h = cast(Vector((O.x, O.y, zz)) + d * (3 * R), -d, 3 * R, tree=bvh)
        NODES_OUT[k] = h[0] if h else Vector((O.x, O.y, zz)) + d * R
if job.get("piece") == "beard" or style.startswith("wig"):
    pass
elif style in ("long", "bob"):
    Lh = float(prm.get("length", .26 if style == "long" else .14)) * H * (1.2 if style == "long" else 2.0)
    obs, mask_of = build_cards(Lh, float(prm.get("part", 0. if style == "long" else .3)), (E.z - 1.25 * R) if style == "bob" else None)
elif style in SHORT:
    shell, solid = build_shell(SHORT[style])
    obs, mask_of = (build_mohawk(shell) if style == "mohawk" else [shell]), solid
else:
    fail(_t("ag.unknown_piece", style))

# ---------------------------------------------------------------- the hair's own shadows, in its vertices' colour
def bake_ao(objs, rays=10, reach=.7):
    """how much of the sky each hair vertex sees past the other locks and the body (ambient occlusion), as its colour
    (glTF's COLOR_0: times the texture, in any engine): the dark between the locks, under them, by the skin - what a
    ray-traced render shows and a real-time one (the editor's, a game's) does not work out itself"""
    reach *= R
    verts, polys = [], []
    for ob in objs:
        b0 = len(verts); M = ob.matrix_world
        verts += [M @ v.co for v in ob.data.vertices]
        polys += [[b0 + i for i in p.vertices] for p in ob.data.polygons]
    if not polys:
        return
    hair_tree = BVHTree.FromPolygons(verts, polys)
    rs = random.Random(5)
    dirs = []   # (round the normal, more of them up it: as the light comes)
    for k in range(rays):
        u1 = (k + rs.random()) / rays; th = 2 * math.pi * rs.random(); r = math.sqrt(u1)
        dirs.append((r * math.cos(th), r * math.sin(th), math.sqrt(max(0., 1 - u1))))
    for ob in objs:
        m = ob.data; M = ob.matrix_world; N3 = M.to_3x3().inverted().transposed()
        nv = len(m.vertices)
        if not nv:
            continue
        ao = np.ones(nv, np.float32)
        for v in m.vertices:
            p = M @ v.co
            n = (N3 @ v.normal).normalized()
            loc, nrm, fi, d = full.find_nearest(p)
            out = (p - loc) if loc is not None and d > 1e-6 else (nrm if loc is not None else p - O)
            if n.length < .5:
                n = out.normalized()
            if n.dot(out) < 0:
                n = -n
            t1 = n.orthogonal().normalized(); t2 = n.cross(t1)
            o = p + n * (.012 * R)
            hit = 0
            for a, b, c in dirs:
                w = t1 * a + t2 * b + n * c
                if full.ray_cast(o, w, reach)[0] is not None or hair_tree.ray_cast(o, w, reach)[0] is not None:
                    hit += 1
            ao[v.index] = 1 - hit / rays
        ed = np.zeros(len(m.edges) * 2, np.int32); m.edges.foreach_get("vertices", ed); ed = ed.reshape(-1, 2)
        for _ in range(2):   # (the rays' noise smoothed)
            acc = np.zeros(nv, np.float32); cnt = np.zeros(nv, np.float32)
            np.add.at(acc, ed[:, 0], ao[ed[:, 1]]); np.add.at(acc, ed[:, 1], ao[ed[:, 0]])
            np.add.at(cnt, ed[:, 0], 1); np.add.at(cnt, ed[:, 1], 1)
            ao = np.where(cnt > 0, .5 * ao + .5 * acc / np.maximum(cnt, 1), ao)
        k = (.4 + .6 * ao) ** 2.2   # (seen as .4 .. 1 of the texture's light; the colour is linear)
        ca = m.color_attributes.get("ao") or m.color_attributes.new("ao", "FLOAT_COLOR", "POINT")
        ca.data.foreach_set("color", np.column_stack([k, k, k, np.ones(nv, np.float32)]).ravel())
        m.color_attributes.active_color = ca
        try:
            m.color_attributes.render_color_index = m.color_attributes.active_color_index
        except AttributeError:
            pass


bake_ao(obs)
print("ao baked", flush=True)

# ---------------------------------------------------------------- weights: the head's; below the jaw the neck's and the chest's
groups = [names["head"], names.get("neck", names["head"]), names.get("spine2", names.get("neck", names["head"]))]
groups = [g for g in groups if g in arm.data.bones] or [names["head"]]
d_ = .95 * R


JAW = names.get("jaw") if names.get("jaw") in arm.data.bones else None


def weights(z):
    if job.get("piece") == "beard":   # (a beard: the head's; below the mouth the jaw's - it moves with the chin)
        k = min(1., max(0., (E.z - 1.25 * R - z) / (.5 * R))) if JAW else 0.
        return [(groups[0], 1 - .7 * k)] + ([(JAW, .7 * k)] if JAW else [])
    k = min(1., max(0., (O.z - .6 * d_ * 1.2 - z) / (.18 * H)))
    return [(groups[0], 1 - k), (groups[min(1, len(groups) - 1)], .6 * k), (groups[min(2, len(groups) - 1)], .4 * k)]


for ob in obs + ([mask_of] if mask_of not in obs else []):
    vg = {g: ob.vertex_groups.new(name=g) for g in dict.fromkeys(groups + ([JAW] if JAW and job.get("piece") == "beard" else []))}
    for v in ob.data.vertices:
        for g, w in weights((ob.matrix_world @ v.co).z):
            if w > 1e-4:
                vg[g].add([v.index], w, "ADD")
# what it hides: the skin under its cap or its shell
keys = set()
if job.get("mask"):
    from body_mask import body_mask
    # (a beard hides nothing: it lies on the face with its gap, and where it is open - round the mouth - the hidden
    # lips and chin showed as a hole into the head)
    keys = {tuple(x) for x in body_mask(body, [mask_of], erode=2)} if job.get("piece") != "beard" else set()
    for i in ear_v:   # (the ears never: long hair closes round them, the mask took them - their tips went)
        c = me.vertices[i].co
        keys.discard((round(c.x * 1000), round(c.z * 1000), round(-c.y * 1000)))
    Path(job["mask"]).write_text(json.dumps([list(x) for x in sorted(keys)]), encoding="utf-8")
if mask_of not in obs:
    bpy.data.objects.remove(mask_of, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
for ob in obs:
    ob.select_set(True)
bpy.context.view_layer.objects.active = obs[0]
if len(obs) > 1:
    bpy.ops.object.join()
obj = bpy.context.view_layer.objects.active
obj.name = f"{'beard' if job.get('piece') == 'beard' else 'hair'}_{style}"
mod = obj.modifiers.new("Armature", "ARMATURE")
mod.object = arm
obj.parent = arm
obj.matrix_parent_inverse = arm.matrix_world.inverted()
for o in list(bpy.data.objects):   # the skeleton and the hair only
    if o.type == "MESH" and o is not obj:
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
obj.select_set(True)
arm.select_set(True)
bpy.context.view_layer.objects.active = arm
if NODES_OUT:   # (the outline's nodes, for the editor: shown on the skin, moved by hand)
    Path(job["out"]).with_suffix(".nodes.json").write_text(json.dumps(
        {"nodes": {k: b2gl(v) for k, v in NODES_OUT.items()}, "loop": LOOP, "mid": round(O.x if not FM else FM.get("mouth_c", O).x, 5)}), encoding="utf-8")
_vc = {"export_vertex_color": "ACTIVE"} if "export_vertex_color" in bpy.ops.export_scene.gltf.get_rna_type().properties.keys() else {"export_colors": True}
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4, **_vc)   # (its shadows: the vertices' colour)
print("ARMOUR_GEN_OK " + json.dumps({"vertices": len(obj.data.vertices), "bones": groups, "style": style, "uvtex": {}}), flush=True)
