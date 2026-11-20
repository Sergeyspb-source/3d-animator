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


def hairline(p, ears=near_ear):
    """high at the forehead, lower over the ears, down to the nape behind"""
    rel = p - O
    if ears is near_ear and near_ear(p, .12 * R):
        return False
    if ears is by_ear and by_ear(p):
        return False
    fb = abs(math.atan2(rel.x, -rel.y)) / math.pi
    zf, zs, zb = .62 * R, .30 * R, -.55 * R
    zmin = zf + (zs - zf) * min(1, fb / .5) if fb < .5 else zs + (zb - zs) * min(1, (fb - .5) / .25)
    return rel.z > zmin


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


# ---------------------------------------------------------------- a wig: the hair of a head made elsewhere (Tripo)
def build_wig(model):
    """the model's hair told from its skin by the texture's colour (two clusters; the hair's the one over the top of
    the head), small islands of it dropped (brows, a moustache drawn on the skin); its head aligned to the
    character's (its skin points onto the character's head skin, scale and all: ICP); the hair pushed out of the body
    (the push smoothed over it); a dark cap under it (no skin between the locks)"""
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
    is_hair = lab if zs[lab].mean() > zs[~lab].mean() else ~lab
    bm = bmesh.new(); bm.from_mesh(tm); bm.transform(tobj.matrix_world)
    for lay in list(bm.verts.layers.deform.values()):
        bm.verts.layers.deform.remove(lay)
    bm.verts.ensure_lookup_table(); bm.faces.ensure_lookup_table()
    hf = {f.index for f in bm.faces if all(is_hair[v.index] for v in f.verts)}
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
    sk = np.array([list(v.co) for v in bm.verts if not is_hair[v.index]])
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
    hair_col = col[is_hair].mean(0)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.index not in keep], context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.transform(M)
    bm.verts.ensure_lookup_table()
    gap = .08 * R   # out of the body, the push smoothed over the hair (no dents where one lock met the skin)
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
    hm = bpy.data.meshes.new("hair_wig"); bm.to_mesh(hm); bm.free()
    for m in tm.materials:
        if m and m.use_nodes:   # (opaque: a head's material, not cut by its alpha)
            b = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
            if b is not None:
                for l in list(b.inputs["Alpha"].links):
                    m.node_tree.links.remove(l)
                b.inputs["Alpha"].default_value = 1.0
            if hasattr(m, "blend_method"):
                try:
                    m.blend_method = "OPAQUE"
                except TypeError:
                    pass
            m.name = "hair_wig"
        hm.materials.append(m)
    wig = bpy.data.objects.new("hair_wig", hm); sc.collection.objects.link(wig)
    for o in new:
        bpy.data.objects.remove(o, do_unlink=True)
    cap = scalp_shell(hairline, lambda v: .05 * R, "hair_cap")
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
    obs, mask_of = build_wig(prm["model"])
elif style in ("long", "bob"):
    Lh = float(prm.get("length", .26 if style == "long" else .14)) * H * (1.2 if style == "long" else 2.0)
    obs, mask_of = build_cards(Lh, float(prm.get("part", 0. if style == "long" else .3)), (E.z - 1.25 * R) if style == "bob" else None)
elif style in SHORT:
    shell, solid = build_shell(SHORT[style])
    obs, mask_of = (build_mohawk(shell) if style == "mohawk" else [shell]), solid
else:
    fail(_t("ag.unknown_piece", style))

# ---------------------------------------------------------------- weights: the head's; below the jaw the neck's and the chest's
groups = [names["head"], names.get("neck", names["head"]), names.get("spine2", names.get("neck", names["head"]))]
groups = [g for g in groups if g in arm.data.bones] or [names["head"]]
d_ = .95 * R


def weights(z):
    k = min(1., max(0., (O.z - .6 * d_ * 1.2 - z) / (.18 * H)))
    return [(groups[0], 1 - k), (groups[min(1, len(groups) - 1)], .6 * k), (groups[min(2, len(groups) - 1)], .4 * k)]


for ob in obs + ([mask_of] if mask_of not in obs else []):
    vg = {g: ob.vertex_groups.new(name=g) for g in dict.fromkeys(groups)}
    for v in ob.data.vertices:
        for g, w in weights((ob.matrix_world @ v.co).z):
            if w > 1e-4:
                vg[g].add([v.index], w, "ADD")
# what it hides: the skin under its cap or its shell
keys = set()
if job.get("mask"):
    from body_mask import body_mask
    keys = {tuple(x) for x in body_mask(body, [mask_of], erode=2)}
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
obj.name = f"hair_{style}"
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
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4)
print("ARMOUR_GEN_OK " + json.dumps({"vertices": len(obj.data.vertices), "bones": groups, "style": style, "uvtex": {}}), flush=True)
