"""Runs INSIDE Blender (background): a hairstyle of the «Equipment: procedural» editor, made on the character's head
and put on it (a MADE piece, as blender_footwear_gen.py).

    blender -b -P blender_hair_gen.py -- job.json

job.json: {"style": long | bob | back | crop | short | mohawk, "params": {"length": share of the height, "color":
           linear rgb, "seed"}, "out": piece.glb, "work": a folder, "character": rigged.glb, "names": {naming: {joint:
           bone}}, "mask": mask.json, "uv_out": (made for the character, not a style's preview: its colour in the
           texture; a preview's is grey, the editor tints it), "template": the user's default beard outlines or
           hairlines (over tool/beard_template.json, tool/hair_template.json), "learn": a template file the nodes
           fitted by hand go into (only that is done)}

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
    zf, zs, zb = (.42 if style in LOW_FRONT else .62) * R, (.04 if style in LOW_FRONT else .30) * R, -.55 * R
    if style in LOW_FRONT and fb < .5:   # (a round arch over the forehead, down to the temples)
        return zs + (zf - zs) * math.cos(fb / .5 * math.pi / 2)
    return zf + (zs - zf) * min(1, fb / .5) if fb < .5 else zs + (zb - zs) * min(1, (fb - .5) / .25)


LOW_FRONT = {"wavy", "half_up", "braids", "side_braid", "crown_braid", "braid_bun", "low_bun", "low_tails", "ponytail"}
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


def ear_gap(p):
    """how far a point is from an ear - all of it, its thick root and the hollow in it too (by its thin shell only,
    bits of a cut were left in the ear's hollow and by its root): the hair goes round it there"""
    loc, n, i, d = ear_pts.find_nearest(p)
    return d if loc is not None else 9 * R


def hair_field(p):
    """how far a point is inside the hairline (+ in, - out), smooth along the head, an ear left out round it: an edge
    drawn by it is a line, not the skin mesh's vertices' staircase, and leaves no holes by the ears"""
    rel = p - O
    return min(rel.z - zmin_at(math.atan2(rel.x, -rel.y)), ear_gap(p) - .03 * R)


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
    """four cards' locks side by side, each along v (its root at v = 1, its tip at 0): many fine strands, more of them
    in its middle, each its own length (ragged tips), lighter to their ends; a soft body only near its root (it was
    upside down: the solid body at the tips - each lock ended in a square cut, a plank - and the ragged ends at the root)"""
    A = np.zeros((TH, TW), np.float32)
    lum = np.full((TH, TW), .4, np.float32)
    cw = TW // 4
    yy = np.arange(TH, dtype=np.float32)   # (from its root down)
    for k in range(4):
        x0 = k * cw
        u = (np.arange(cw) + .5) / cw * 2 - 1
        body = (np.exp(-(u / .42) ** 2)[None, :] * np.clip(1 - yy[:, None] / (TH * .5), 0, 1) ** .7 * .85
                * np.clip((yy[:, None] - TH * .02) / (TH * .1), 0, 1))   # (coming in at the root: the card starts off the base)
        A[:, x0:x0 + cw] = body
        lum[:, x0:x0 + cw] = .45 + .2 * body
        for s_ in range(170):
            cx = x0 + min(cw - 4., max(3., cw / 2 + rnd.gauss(0, cw * .22)))
            w = .55 + rnd.random() * .9
            Ls = TH * (.4 + .6 * rnd.random() ** .55)
            br = .65 + .5 * rnd.random()
            sway, amp = rnd.random() * 6.28, 1 + 2.5 * rnd.random()
            y0_ = int(TH * .1 * rnd.random() ** 1.5)   # (each its own start: no straight line where the card begins)
            ys = np.arange(y0_, int(Ls))
            xs = cx + amp * np.sin(ys / TH * 5 + sway) + (x0 + cw / 2 - cx) * .3 * ys / TH   # (closing in a little to the tip)
            tipfade = np.clip((Ls - ys) / (TH * .07), 0, 1) * np.clip((ys - y0_) / (TH * .03), 0, 1)
            for dx in range(-2, 3):
                xi = np.clip((xs + dx).astype(int), x0, x0 + cw - 1)
                al = np.exp(-((xs + dx - xi - .5) ** 2 + dx * dx) / (w * w)) * tipfade
                A[ys, xi] = np.maximum(A[ys, xi], al)
                m_ = al > .3
                lum[ys[m_], xi[m_]] = np.minimum(1., br * (.8 + .35 * ys[m_] / TH))
    img = np.zeros((TH, TW, 4), np.float32)
    img[..., 3] = A[::-1]
    img[..., :3] = lum[::-1][..., None] * COL[None, None, :]
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


def locks_tile(TW, TH, ncol, nrow, seed, nstr=7., reach=2.3):
    """a tiling picture of hair locks along v (rows: root up, tip down), as a sculpted beard's: pointed, in staggered
    rows, each one's tip over the roots of the row under it (a pixel shows the lock highest there - a tip over another's
    root: no order to keep, so it tiles), fine uneven strands in each converging on its tip, its root in the shadow of
    the tips over it. -> (height 0..1, light 0..1, cover 0..1: how far into a lock, 1 its middle)"""
    r = np.random.default_rng(seed)
    best = np.full((TH, TW), -1e9, np.float32)
    hgt = np.zeros((TH, TW), np.float32); lum = np.full((TH, TW), .25, np.float32); cov = np.zeros((TH, TW), np.float32)
    cw, rh = TW / ncol, TH / nrow
    yy, xx = np.mgrid[0:TH, 0:TW].astype(np.float32)
    for j in range(nrow):
        for i in range(ncol):
            cx = (i + .5 * (j % 2) + r.uniform(-.3, .3)) * cw
            y0 = (j + r.uniform(-.25, .25)) * rh
            w = cw * r.uniform(.5, .9)   # (its half width at its widest)
            L = rh * reach * r.uniform(.85, 1.15)
            bend = r.uniform(-.5, .5) * w
            br = r.uniform(.72, 1.)
            ph = r.uniform(0, 6.28)
            hairs = r.uniform(0, 1, 48) ** .7   # (its hairs' light across it, uneven)
            t = ((yy - y0) % TH) / L
            xc = cx + bend * np.sin(np.pi * np.clip(t, 0, 1))
            hw = w * np.sqrt(np.clip(t / .12, 0, 1)) * np.clip(1 - t, 0, 1) ** .85 + 1e-3
            s = ((xx - xc + TW / 2) % TW - TW / 2) / hw
            ins = (t >= 0) & (t <= 1) & (np.abs(s) < 1)
            prof = np.sqrt(np.clip(1 - s * s, 0, 1))
            el = .45 * prof + .9 * t
            win = ins & (el > best)
            if not win.any():
                continue
            best[win] = el[win]
            hi = hairs[np.clip(((s + 1) * 23.5).astype(int), 0, 47)]
            st = .45 * (.5 + .5 * np.cos(np.pi * s * nstr * .5 + ph)) + .55 * hi
            hgt[win] = (.55 * prof + .45 * t ** .7 + .06 * st)[win]
            under = .5 + .5 * np.clip(t / .4, 0, 1)
            lum[win] = (br * (.4 + .6 * prof ** .7) * under * (.6 + .4 * st))[win]
            cov[win] = (prof * (1 - .35 * t))[win]
    return hgt, lum, cov


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
def build_cards(L, part, cut_z, wave=0., messy=0., swept=0., narrow=1.):
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

    face_half = 0.   # (the face's own half width, its cheeks', from outside)
    z = E.z + .3 * R
    while z > E.z - 1.3 * R:
        for sd in (1, -1):
            h = cast(Vector((O.x + sd * 3 * R, O.y - .45 * R, z)), -X * sd, 3 * R, tree=bvh)
            if h:
                face_half = max(face_half, abs(h[0].x - O.x))
        z -= .1 * R
    face_half = min(face_half, 1.2 * R)

    def keep_x(q):   # how far from the middle hair in front of the face and the chest stays (smooth with the height)
        return max(R * (.9 + .3 * swept + .4 * _ramp((q - O).z, -.8 * R, -2.2 * R)), face_half + .12 * R)

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
        f = X * sd * 1.3 * (1 - .7 * swept) * top * fr - UP * (.35 + .9 * (1 - top * fr)) + BACK * (.3 * top + .55 * (1 - top) + 1.3 * swept * fr)   # (swept: back off the face first)
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

    lift_k = .55 if cut_z is not None else 1.   # (a bob close to the head: its layers stood off it - a hood)

    def lay_gap(q, layer):   # (its height over the skin: low by the hairline, its layer's further in)
        return (.025 + (.035 + .1 * layer) * lift_k * smooth(0., .45 * R, hair_field(q))) * R

    def guide(root, n, layer):
        p = root.copy(); pts = [p.copy()]
        gap = lay_gap(p, layer)
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
            gap = max(gap, lay_gap(q, layer))   # (rising off the skin as it goes in from the hairline, never back down)
            if on_head:
                loc, nrm, i, dist = bvh.find_nearest(q)
                if loc is not None:
                    q = loc + (nrm.normalized() if nrm.dot(q - O) > 0 else -nrm.normalized()) * gap
            q = push_out(q, gap)
            if in_front(q):   # (off the face: half way each step - a jump to its side made a corner at the temple)
                q.x += (O.x + math.copysign(keep_x(q), q.x - O.x if abs(q.x - O.x) > 1e-6 else 1) - q.x) * .5
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
        gap = (.08 + .1 * layer * lift_k) * R
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
        return smooth_lock(pos, gap)

    def smooth_lock(pts, gap, iters=30):
        """the whole strand a smooth curve: each point half way to its neighbours' middle, again and again, kept out of
        the body and drawn off the face a little each time (its root stays; its end goes with the one before it) -
        where it turned off the skull to fall, or the face pushed it aside, it bent at a corner"""
        P = [q.copy() for q in pts]
        m = len(P)
        if m < 4:
            return P
        for it in range(iters):
            Q = [P[0]] + [P[i] * .5 + (P[i - 1] + P[i + 1]) * .25 for i in range(1, m - 1)]
            Q.append(P[-1] + (Q[-1] - P[-2]))
            for i in range(1, m):
                loc, nrm, fi, dist = full.find_nearest(Q[i])
                if loc is not None:
                    nn = nrm.normalized(); side = (Q[i] - loc).dot(nn)
                    if side < gap:
                        Q[i] = Q[i] + nn * (gap - side)
                if in_front(Q[i]):
                    dx = Q[i].x - O.x; kx = keep_x(Q[i])
                    if abs(dx) < kx:
                        Q[i].x += (O.x + math.copysign(kx, dx if abs(dx) > 1e-6 else 1) - Q[i].x) * .5
            P = Q
        return P

    bm = bmesh.new()
    uvl = bm.loops.layers.uv.new("UVMap")

    def card(pts, w0, slot, k_free=10 ** 6):
        if cut_z is not None:   # a bob: cut at the jaw - longer in front (an A line), each lock a little its own
            fr = min(1., max(0., (-(pts[0] - O).y / R + .2) / .9))
            cz = cut_z - .3 * R * fr + rnd.uniform(-.05, .05) * R
            k = next((i for i, p in enumerate(pts) if p.z < cz), len(pts))
            pts = pts[:max(3, k + 1)]
            m_ = len(pts)
            for i in range(m_):   # (its end turned in under, toward the neck: curved, not a square wall)
                f = smooth(.5, 1., i / max(1, m_ - 1))
                d_ = Vector((O.x - pts[i].x, O.y - pts[i].y, 0))
                if d_.length > 1e-6:
                    pts[i] = pts[i] + d_.normalized() * (.2 * R * f ** 1.6) + UP * (.06 * R * f ** 2)
                loc, nrm, fi_, dd = full.find_nearest(pts[i])
                if loc is not None:
                    nn = nrm.normalized(); sd_ = (pts[i] - loc).dot(nn)
                    if sd_ < .04 * R:
                        pts[i] = pts[i] + nn * (.04 * R - sd_)
        r0 = pts[0] - O
        z_on = O.z - rnd.uniform(.12, .4) * R   # (each its own start: all at one height they made a step by the temple)
        ks = min(k_free, next((i for i, p in enumerate(pts) if p.z < z_on or (p - O).length > 1.3 * R), len(pts)))
        pts = pts[max(0, ks - 2):]   # (from where it leaves the skull: on it the base is the hair - not by the ears' tops: high on a goblin)
        if len(pts) < 4:
            return
        ph, amp = 2.2 * r0.x / R + 1.4 * r0.y / R, .06 * R   # (one sway for the whole hair: neighbours together)
        lam = 1.6 * R
        if wave:   # (waves in clumps: the cards rooted near each other one S - its phase, its length; all of them together
            # read as a corrugated sheet, each its own as frizz)
            cell = (round(math.atan2(r0.x, -r0.y) / .3), round(r0.z / (.45 * R)))
            cr = random.Random(hash(cell) & 0xffffffff)
            ph, amp, lam = cr.random() * 6.28 + .35 * rnd.random(), (.06 + .07 * wave) * R * (.8 + .4 * cr.random()), (.75 + .4 * cr.random()) * R
        pts = [p if p.z > zst else p + Vector((math.sin(ph + (zst - p.z) / lam * 3.14), 0, 0)) * amp * min(1., (zst - p.z) / R) for p in pts]
        if messy:   # (tousled: each lock its own way out and aside, more to its end)
            mr = random.Random(hash((round(r0.x / (.2 * R)), round(r0.y / (.2 * R)), round(r0.z / (.2 * R)))) & 0xffffffff)
            dv = Vector((mr.uniform(-1, 1), mr.uniform(-1, 1), mr.uniform(-.2, .5))) * (messy * .14 * R)
            pts = [p + dv * (i / (len(pts) - 1)) ** 1.5 for i, p in enumerate(pts)]
        left, right, mid = [], [], []
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
            mid.append(bm.verts.new(p + o + out.normalized() * (.16 * w)))
        u0, u1 = slot / 4 + .005, (slot + 1) / 4 - .005
        um = .5 * (u0 + u1)
        for i in range(len(pts) - 1):
            v0, v1 = 1 - i / (len(pts) - 1), 1 - (i + 1) / (len(pts) - 1)
            for (a_, b_, ua, ub) in ((left, mid, u0, um), (mid, right, um, u1)):
                f = bm.faces.new((a_[i], b_[i], b_[i + 1], a_[i + 1]))
                for lp, uv in zip(f.loops, ((ua, v0), (ub, v0), (ub, v1), (ua, v1))):
                    lp[uvl].uv = uv
    n_cards = 0
    for layer, every, w in ((0, 3, .7), (1, 2, .6), (2, 3, .56)):
        for k, (r0, n) in enumerate(roots):
            if k % every:
                continue
            pts, kf = guide(r0 + n * ((.01 + (.03 + .08 * layer) * smooth(0., .45 * R, hair_field(r0))) * R), n, layer)
            card(settle(pts, kf, layer), w * narrow * R * (.8 + .4 * rnd.random()), rnd.randrange(4), kf)
            n_cards += 1
    print("cards", n_cards, flush=True)
    cm = bpy.data.meshes.new("hair_cards"); bm.to_mesh(cm); bm.free()
    cards = bpy.data.objects.new("hair_cards", cm); sc.collection.objects.link(cards)
    atlas = strands_atlas()
    im = save("strands", atlas, True)
    m_cards, _ = material("hair_strands", im, True)
    cm.materials.append(m_cards)
    # the hair on the skull: the smooth base, its locks from the parting down and out, on to a ring under the head
    ring = [Vector((O.x + 1.2 * R * math.sin(a), O.y - 1.2 * R * math.cos(a), O.z - 3.5 * R)) for a in (k * math.pi / 8 for k in range(16))]
    top, solid = sleek_base(ring, lift=.05, part=1.1, name="top", px=px)
    return [cards, top], solid


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
         # (cut: a straight line round the head - its height at the front and at the back (x R over the head's middle):
         # a fringe over the forehead to it; crown: the hairs fall from the top of the head all round; bald: the top
         # of the head bare within that angle; edge: the cut blunt (x R of its rounding))
         "bowl": dict(T=.17, quiff=0., side=.13, fade=False, turn=0., cut=(.18, -.3), crown=True, edge=.12),
         "tonsure": dict(T=.11, quiff=0., side=.1, fade=False, turn=0., cut=(.22, -.35), crown=True, bald=50., edge=.1),
         "caesar": dict(T=.05, quiff=0., side=.025, fade=False, turn=0., cut=(.5, None), crown=True, edge=.08),
         "crop": dict(T=.12, quiff=.10, side=.02, fade=True, turn=0.),
         "short": dict(T=.12, quiff=.16, side=.06, fade=False, turn=25.),
         "mohawk": dict(T=.03, quiff=0., side=.02, fade=True, turn=0.)}


def build_shell(cfg):
    def backness(p):
        return min(1., max(0., ((p - O).y / R + .2) / 1.0))

    def cut_z(p):   # (a straight cut's height round the head: the front's to the back's)
        f, b = cfg["cut"]
        fb = abs(math.atan2((p - O).x, -(p - O).y)) / math.pi
        return (f + (b - f) * smooth(.15, .75, fb)) * R if b is not None else None

    def field(p):
        """how far inside the cut's line (+ in, - out), smooth along the head: its hairline, a straight cut round it, a
        fringe over the forehead, a monk's bare top, a crop's sides, a mohawk's strip, the ears left out round them"""
        rel = p - O
        th = math.atan2(rel.x, -rel.y)
        if cfg.get("cut"):
            cz = cut_z(p)
            if cz is None:   # (a fringe only: the hairline, and over the forehead down to the cut)
                v = max(rel.z - zmin_at(th), min(rel.z - cfg["cut"][0] * R, (math.radians(70) - abs(th)) * R))
            else:
                v = rel.z - cz
        else:
            v = rel.z - zmin_at(th)
            if style == "crop":
                v = min(v, rel.z - (.15 - .35 * backness(p)) * R)
            if style == "mohawk":
                v = min(v, .3 * R - abs(p.x - O.x))
        if cfg.get("bald"):   # (a monk's: the top bare)
            v = min(v, (rel.angle(Vector((0, .1, 1))) - math.radians(cfg["bald"])) * rel.length)
        return min(v, ear_gap(p) - .03 * R, rel.z + 1.2 * R)

    def in_cut(p):   # (a little past the line: its edge is the alpha's; not on an ear's own body)
        return field(p) > -.1 * R and ear_gap(p) > .015 * R
    bm = bmesh.new(); bm.from_mesh(me); bm.transform(skin.matrix_world)
    for lay in list(bm.verts.layers.deform.values()):   # (the skin's weights not carried over: its groups are not the hair's)
        bm.verts.layers.deform.remove(lay)
    keep = {v for v in bm.verts if in_cut(v.co) and v.index not in ear_v}   # (none on an ear: bits were left on its tip, in its hollow)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context="VERTS")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    for lay in list(bm.loops.layers.uv.values()):
        bm.loops.layers.uv.remove(lay)
    bm.verts.ensure_lookup_table(); bm.normal_update()
    FLD = [field(v.co) for v in bm.verts]
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
        return t * min(1., max(0., FLD[i] + .02 * R) / (cfg.get("edge", .6) * R)) ** .7   # (rounded off to its line: no rim; a straight cut blunt)
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
    if cfg.get("crown"):   # (the hairs from the top of the head down all round: a bowl's, a fringe's)
        PF, PB = O + UP * (2.2 * R) + BACK * (.2 * R), O - UP * (3 * R)
    CC = (PF + PB) * .5; ax = (PF - PB).normalized()
    ref = UP - ax * UP.dot(ax)
    if ref.length < .3:   # (an axis up through the crown: round it from the face)
        ref = FRONT - ax * FRONT.dot(ax)
    ref.normalize(); ref2 = ax.cross(ref)
    S = 2.2 * R
    UVV = {}
    for v in bm.verts:
        d = v.co - CC; dl = d.length
        pol = math.acos(max(-1., min(1., d.dot(ax) / max(dl, 1e-12))))
        az = math.atan2(d.dot(ref2), d.dot(ref))
        UVV[v.index] = (az / (2 * math.pi) * 5., pol * 1.6 * R / S)   # (round it: five tiles - whole: no seam)
    # (its line drawn by the alpha: a crop's sides fading out wide; any other's crisp)
    fade = {v.index: (smooth(-.01 * R, .45 * R, FLD[v.index]) if cfg["fade"] else smooth(-.015 * R, .015 * R, FLD[v.index])) for v in bm.verts}
    uvl = bm.loops.layers.uv.new("UVMap")
    vs = [w for _, w in UVV.values()]
    u0, v0, span = -2.5, min(vs), max(5., max(vs) - min(vs))   # (the texture one turn wide: its edges meet)

    def wrapped(us_):   # (a face across the cut: its far side a turn on - the texture repeats there)
        return [u + 5. if (max(us_) - min(us_) > 2.5 and u < 0) else u for u in us_]
    for f in bm.faces:
        uu_ = wrapped([UVV[lp.vert.index][0] for lp in f.loops])
        for lp, u in zip(f.loops, uu_):
            lp[uvl].uv = ((u - u0) / span, (UVV[lp.vert.index][1] - v0) / span)   # (one texture over the whole cut: drawn below)
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
            pu0 = np.array([uvd[j].uv[0] * T for j in tri]); pv = np.array([uvd[j].uv[1] * T for j in tri])
            fv = np.array([fade[m.loops[j].vertex_index] for j in tri])
            for shift in ((0., -T) if pu0.max() > T else (0.,)):   # (a face across the cut: past the edge, drawn again from the other)
                pu = pu0 + shift
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
    if cfg["fade"]:
        img[..., 3] = np.maximum(fade_img ** 3, np.clip(fade_img * (fi * 1.6 - .2), 0, 1))
    else:   # (a crisp line, the fine hairs only just ruffling it)
        img[..., 3] = np.clip((fade_img - .5) * 10 + .5 + .6 * (fi - .5), 0, 1)
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
        lis = list(poly.loop_indices)
        for li, u in zip(lis, wrapped([UVV[m.loops[li].vertex_index][0] for li in lis])):
            uvt.data[li].uv = (u, UVV[m.loops[li].vertex_index][1])
    dsp = ob.modifiers.new("grooves", "DISPLACE"); dsp.texture = ctex; dsp.texture_coords = "UV"; dsp.uv_layer = "tile"
    dsp.strength = .09 * R * min(1., cfg["T"] / .1); dsp.mid_level = .5   # (a thin cut's grooves shallow)
    bpy.context.view_layer.objects.active = ob
    for md in list(ob.modifiers):
        bpy.ops.object.modifier_apply(modifier=md.name)
    m.uv_layers.remove(m.uv_layers["tile"])
    for v in m.vertices:   # (the grooves not into the skin: through a thin cut it showed in patches)
        loc, nrm, fi_, d_ = full.find_nearest(v.co)
        if loc is not None:
            nn = nrm.normalized(); nn = nn if nn.dot(v.co - O) > 0 else -nn
            sd_ = (v.co - loc).dot(nn)
            if sd_ < .015 * R:
                v.co += nn * (.015 * R - sd_)
    m.update()
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
BEARD = {   # T: on the cheeks, J: at the jaw (x the head's radius); hang: under the chin (x the length); patch: bare under the lip;
    # W: the hanging part's half width (x the mouth's width); HB: how far back from the chin's front it hangs (x R)
    "stubble": dict(T=0., J=0., hang=0., patch=False, must=None),
    "short": dict(T=.075, J=.11, hang=0., patch=False, must="short"),
    "full": dict(T=.09, J=.15, hang=1., patch=True, must="handlebar"),
    "long": dict(T=.1, J=.17, hang=1., patch=True, must="droop"),
    "goatee": dict(T=.05, J=.075, hang=1., patch=True, must="goatee", W=.68, HB=.6),   # (thin on the chin, the mouth's width: it was a full beard's mass)
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


def conform(bm, gap, reach, target=None, fixed=()):
    """the open edge put down on the skin (at gap), the way there spread in over reach and smoothed off: a piece made
    for another face (or rounded by a remesh) stood off the skin at its edge"""
    bm.verts.ensure_lookup_table()
    dist = edge_dist(bm)
    src = {}
    for v in bm.verts:
        if dist[v.index] == 0. and v.index not in fixed:
            tg = target(v.co) if target else None   # (an outline's own line, where it is near)
            loc, nrm = tg if tg else full.find_nearest(v.co)[:2]
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
        if j in fixed:
            continue
        k = max(0., 1 - dd[j] / reach) ** 2
        bm.verts[j].co += src[i] * k


def push_out(bm, gap):
    for v in bm.verts:
        s, nn = out_of_skin(v.co)
        if s < gap:
            v.co += nn * (gap - s)


def raster_fade(m, fade, T, mat=None):
    """a per-vertex value over the unwrap: rasterised from the triangles, barycentric (a material's faces only)"""
    out = np.zeros((T, T), np.float32)
    uvd = m.uv_layers[0].data
    for poly in m.polygons:
        if mat is not None and poly.material_index != mat:
            continue
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
        if outline is not None:   # (an oval round the lips themselves: the box ate the beard by the corners, inside its outline)
            ax, zc, az = .5 * u + .03 * R, yM + .5 * (F["lipUp"] - F["lipDn"]), .5 * (F["lipUp"] + F["lipDn"])
            return (1 - ((p.x - mx) / ax) ** 2 - ((p.z - zc) / az) ** 2) * min(ax, az)
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

    def ear(p):   # (with an outline the ear itself only: its margin cut the sideburn short of the outline)
        loc, n, i, d = ear_pts.find_nearest(p)
        return (d if loc is not None else R) - (.06 if outline is not None else .2) * R

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
NODES_OUT, LOOP, LOOPS_OUT = {}, [], []
# the default outline: nodes fitted by hand (the user's, on a character) kept by the face's measures, put on another face by
# them - each style's own (a goatee's jaw under the chin, a full beard's sideburns by the ear's top...); a style with
# none of its own takes another's
TPL_FILE = HERE / "beard_template.json"
TPL_FROM = {"long": "full", "stubble": "short"}
MOUTH_NODES = ("corner", "lip", "chin", "must")
TPL, MUST_TPL = {}, {}


def _zknots(F):
    yM, yC = F["yM"], F["yC"]
    return [yC - (yM - yC), yC, yM, E.z], [-2., -1., 0., 1.]


def _pw(x, xs, ys):   # (piecewise linear, on past its ends)
    i = 0 if x < xs[1] else (len(xs) - 2 if x >= xs[-2] else max(j for j in range(len(xs) - 1) if xs[j] <= x))
    return ys[i] + (ys[i + 1] - ys[i]) * (x - xs[i]) / (xs[i + 1] - xs[i])


def node_norm(F, k, p):
    """a node by the face's measures: round the mouth by its width from its middle and its front; elsewhere across by
    the head's half width there, up by the chin, the mouth and the eyes, its depth from the head's middle (x R)"""
    if k.startswith(MOUTH_NODES):
        return ["m", (p.x - F["mx"]) / F["u"], (p.z - F["yM"]) / F["u"], (F["front"](p) - F["fM"]) / F["u"]]
    zs, ws = _zknots(F)
    return ["s", (p.x - F["mx"]) / F["half"](p.z), _pw(p.z, zs, ws), F["front"](p) / R]


def mouth_inside(F):
    """the mouth's inside (its bag, the lips' inner sides): hidden from the front behind the lips - the skin by its corners
    is not"""
    mx, yM, mw = F["mx"], F["yM"], F["mw"]

    def f(v):
        if not (abs(v.x - mx) < 1.1 * mw and yM - 1.2 * F["lipDn"] < v.z < yM + 1.2 * F["lipUp"]):
            return False
        h = full.ray_cast(Vector((v.x, O.y - 4 * R, v.z)), BACK, 8 * R)
        return h[0] is not None and h[0].y < v.y - .03 * R
    return f


_OUTER = []


def node_denorm(F, rec):
    g, a, b, c = rec
    if not _OUTER:   # (put on the outer skin: from inside the chin the nearest was the mouth's bag)
        im = mouth_inside(F)
        bad = {i for i, v in enumerate(V) if im(v)}
        _OUTER.append(BVHTree.FromPolygons(V, [f for f in P if not any(i in bad or i in ear_v for i in f)]))
    if g == "m":
        q = Vector((F["mx"] + a * F["u"], O.y - (F["fM"] + c * F["u"]), F["yM"] + b * F["u"]))
    else:
        zs, ws = _zknots(F)
        z = _pw(b, ws, zs)
        q = Vector((F["mx"] + a * F["half"](z), O.y - c * R, z))
    return _OUTER[0].find_nearest(q)[0] or q


def load_template(F, st):
    """this style's default nodes on this face: the user's own (job's «template»: «Remember as the default» in the editor)
    over the toolkit's (tool/beard_template.json); a style with none of its own takes another's"""
    TPL.clear(); MUST_TPL.clear()
    srcs = []
    for f in (job.get("template"), TPL_FILE):
        try:
            srcs.append(json.loads(Path(f).read_text(encoding="utf-8")) if f else {})
        except (OSError, ValueError):
            srcs.append({})
    rec = next((src[k] for k in (st, TPL_FROM.get(st)) for src in srcs if k and isinstance(src.get(k), dict)), {})
    for k, r in rec.items():
        if isinstance(r, list) and len(r) == 4:
            (MUST_TPL if k.startswith("must") else TPL)[k] = node_denorm(F, r)


def learn_template(F, st, path):
    """the nodes fitted by hand kept as the style's default (by the face's measures), into the template file"""
    pth = Path(path)
    try:
        tp = json.loads(pth.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tp = {}
    rec = {k: node_norm(F, k, v) for k, v in NODES_IN.items() if k != "tip"}
    for k in [k for k in rec if k.endswith("_L") and k[:-2] + "_R" in rec]:   # (the pairs mirrored: one shape)
        l_, r_ = rec[k], rec[k[:-2] + "_R"]
        m_ = [l_[0], .5 * (l_[1] - r_[1]), .5 * (l_[2] + r_[2]), .5 * (l_[3] + r_[3])]
        rec[k], rec[k[:-2] + "_R"] = m_, [m_[0], -m_[1], m_[2], m_[3]]
    for k in rec:   # (one in the middle: on it)
        if not k.endswith(("_L", "_R")):
            rec[k][1] = 0.
    tp[st] ={k: [r[0]] + [round(x, 4) for x in r[1:]] for k, r in sorted(rec.items())}
    write_template(pth, tp)
    print("tmpl learnt", st, len(tp[st]), flush=True)


def write_template(pth, tp):
    rows = [json.dumps(k) + ": {\n" + ",\n".join("  %s: %s" % (json.dumps(n), json.dumps(r)) for n, r in v.items()) + "}" for k, v in sorted(tp.items())]
    pth.write_text("{\n" + ",\n".join(rows) + "\n}\n", encoding="utf-8")   # (a node a line)


# the hairline's default: its nodes fitted by hand kept by the head's measures - each its angle round the head's axis,
# its height between the neck, the eyes and the top of the head - put on another head by them; a style's own, or the
# last one kept for any hairstyle («hair»)
HAIR_TPL_FILE = HERE / "hair_template.json"


def _hknots():
    return [NK.z, E.z, TOP.z], [-1., 0., 1.]


def _hair_on(th, z):
    """the scalp's point at an angle round the head's axis and a height (from outside, the ears left out)"""
    d = Vector((math.sin(th), -math.cos(th), 0))
    h = cast(Vector((O.x, O.y, z)) + d * (3 * R), -d, 3 * R, tree=bvh)
    return h[0] if h else Vector((O.x, O.y, z)) + d * R


def hair_template(st):
    """this hairstyle's hairline nodes on this head: the user's own (job's «template») over the toolkit's"""
    srcs = []
    for f in (job.get("template"), HAIR_TPL_FILE):
        try:
            srcs.append(json.loads(Path(f).read_text(encoding="utf-8")) if f else {})
        except (OSError, ValueError):
            srcs.append({})
    rec = next((src[k] for k in ("hair_" + st, "hair") for src in srcs if isinstance(src.get(k), dict)), {})
    zs, ws = _hknots()
    return {k: _hair_on(r[1], _pw(r[2], ws, zs)) for k, r in rec.items() if isinstance(r, list) and len(r) == 3 and r[0] == "h"}


def learn_hair(st, path, angs):
    """the hairline's nodes fitted by hand kept as this style's default and as any hairstyle's without its own"""
    pth = Path(path)
    try:
        tp = json.loads(pth.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tp = {}
    zs, ws = _hknots()
    rec = {k: ["h", math.atan2((p - O).x, -(p - O).y), _pw(p.z, zs, ws)] for k, p in NODES_IN.items() if k in angs}
    for k in [k for k in rec if k.endswith("_L") and k[:-2] + "_R" in rec]:   # (the pairs mirrored: one shape)
        l_, r_ = rec[k], rec[k[:-2] + "_R"]
        th, z = .5 * (abs(l_[1]) + abs(r_[1])), .5 * (l_[2] + r_[2])
        rec[k], rec[k[:-2] + "_R"] = ["h", th, z], ["h", -th, z]
    for k, a in (("front", 0.), ("nape", math.pi)):   # (in the middle: on it)
        if k in rec:
            rec[k][1] = a
    rec = {k: [r[0]] + [round(x, 4) for x in r[1:]] for k, r in sorted(rec.items())}
    tp["hair_" + st] = rec; tp["hair"] = rec
    write_template(pth, tp)
    print("tmpl learnt hair", st, len(rec), flush=True)
# (under the lower lip a pair, as the rest: one in the middle sat there alone)
# (and one by each corner of the lips: the outline round the mouth drawn closer)
BEARD_LOOP = ["burn_R", "cheek_R", "corner_R", "lip_R", "chin_R", "chin_L", "lip_L", "corner_L", "cheek_L", "burn_L", "jaw_L", "throat", "jaw_R"]
GOATEE_LOOP = ["corner_R", "lip_R", "chin_R", "chin_L", "lip_L", "corner_L", "jaw_L", "throat", "jaw_R"]


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

    def __init__(self, pts, seed, block=None, centre=None):
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
        # (each point of it on an outer skin's vertex: the nearest of all, by a lip's corner, was in the mouth, the wall
        # went round inside it and the fill got out by the corner outside - goblin_hero_2)
        ov = {i for f in P if not any(REP[i] in bk or i in ear_v for i in f) for i in f}
        ko = KDTree(len(ov))
        for i in ov:
            ko.insert(V[i], i)
        ko.balance()
        ids = [REP[ko.find(c)[1]] for c in cur]
        # (the mouth a wall too, outside: the lower lip runs into the mouth and out over the upper one)
        wall = set()
        gaps = 0
        for k in range(len(ids)):
            pp = path(ids[k - 1], ids[k])
            if pp[-1] != ids[k - 1]:   # (no way along its edges: a slit in the skin - goblin_hero_2's under the lip;
                # the wall there the skin round the step, or the fill got out through it and the outline was lost)
                gaps += 1
                a_, b_ = V[ids[k - 1]], V[ids[k]]
                for t_ in (0., .25, .5, .75, 1.):
                    for _, j_, _ in kd.find_range(a_.lerp(b_, t_), max(.6 * (b_ - a_).length, .02 * R)):
                        pp.append(REP[j_])
                if job.get("debug"):
                    print("gap", k, tuple(round(x, 3) for x in cur[k - 1]), tuple(round(x, 3) for x in V[ids[k - 1]]),
                          tuple(round(x, 3) for x in cur[k]), tuple(round(x, 3) for x in V[ids[k]]), flush=True)
            wall.update(pp)
        if job.get("debug"):
            jumps = sorted(((cur[k] - cur[k - 1]).length / R, k) for k in range(len(cur)))[-5:]
            print("outline gaps", gaps, "jumps/R", [(round(a, 2), k) for a, k in jumps], flush=True)
        on = set(wall)
        wall |= bk
        # what is inside by the curve seen from in the jaw at the mouth's height (its angle round, its angle down: the
        # chin's underside between its front and the throat), no further from there than the curve (the chest is under
        # it too) - none of its mesh's ways: where they do not hold it (a slit; a lip over the chin, goblin_hero_2's;
        # the jaw off the neck, man-young's) it is the outline
        C_ = np.array([centre.x, O.y, centre.z]) if centre is not None else np.array([O.x, O.y, E.z - R])

        def ang(p):
            d = p - C_
            return np.arctan2(d[..., 0], -d[..., 1]), np.arctan2(d[..., 2], np.hypot(d[..., 0], d[..., 1]))
        cp = np.array([c[:] for c in cur]); px, pz = ang(cp)
        reach_ = 1.15 * np.linalg.norm(cp - C_, axis=1).max()

        def seen_in(pts):
            qx, qz = ang(pts)
            ins = np.zeros(len(pts), bool)
            for k in range(len(cp)):   # (even-odd: a ray along the angle)
                x0, z0, x1, z1 = px[k - 1], pz[k - 1], px[k], pz[k]
                cr = (z0 > qz) != (z1 > qz)
                xi = x0 + (qz - z0) * (x1 - x0) / np.where(z1 != z0, z1 - z0, 1e-12)
                ins ^= cr & (qx < xi)
            return ins & (pts[:, 2] < E.z) & (np.linalg.norm(pts - C_, axis=1) < reach_)
        # (filled from a few places that should be inside - the chin, under it, the cheeks; a fill that got out - up
        # past the eyes, or a quarter of the body - was from outside: dropped; from a place inside, the wall has a hole)
        inside, leak = set(), False
        for sp in seed:
            q = outer.find_nearest(sp)[0] or sp
            sd = REP[kd.find(q)[1]]
            if sd in wall:
                sd = next((j for j in EDGES.get(sd, ()) if j not in wall), None)
            if sd is None or sd in inside:
                continue
            got, st, par_ = {sd}, [sd], {}
            while st and len(got) < .25 * len(V):
                i = st.pop()
                for j in EDGES.get(i, ()):
                    if j not in got and j not in wall:
                        got.add(j); st.append(j); par_[j] = i
            if job.get("debug"):
                print("fill", tuple(round(x, 3) for x in sp), len(got), round(max(V[i].z for i in got), 3), flush=True)
                if max(V[i].z for i in got) > E.z:   # (where it got out: its way's points by the curve)
                    i = max(got, key=lambda i: V[i].z); way = []
                    while i in par_:
                        way.append(i); i = par_[i]
                    by = [(round(self.kc.find(V[i])[2] / R, 3), tuple(round(x, 3) for x in V[i])) for i in way]
                    print("  out by", sorted(by)[:4], flush=True)
            if len(got) < .25 * len(V) and max(V[i].z for i in got) < E.z:
                inside |= got
            elif seen_in(np.array([V[sd][:]]))[0]:
                leak = True
        if len(inside) <= 20 or leak:
            Va = np.array([v[:] for v in V])
            inside = {REP[i] for i in np.nonzero(seen_in(Va))[0] if REP[i] not in bk and i not in ear_v}
            print("outline by its angles from the jaw: inside %d" % len(inside), flush=True)
        self.ok = len(inside) > 20
        if job.get("debug"):   # (the line, to look at it over the beard)
            (WORK / f"{STEM}.cur.json").write_text(json.dumps([list(c) for c in cur]), encoding="utf-8")
        self.inside, self.wall = inside, on
        print("outline: inside %d wall %d ok %s" % (len(inside), len(wall), self.ok), flush=True)

    def edge_target(self, p):
        """the outline's own point nearest an edge's vertex (the edge put down on the line, not on the skin nearest:
        under the jaw that was down the neck, and the beard went past its outline)"""
        c, i, d = self.kc.find(p)
        if d > .3 * R:
            return None
        loc, nrm, fi, dd = full.find_nearest(self.cur[i])
        return (self.cur[i], nrm) if loc is not None else None

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
    tg = {"throat": Vector((mx, cf + 1.1 * u, yC - .5 * u))}
    for sd, sn in ((1, "L"), (-1, "R")):
        tg["chin_" + sn] = Vector((mx + sd * .3 * u, cf, yM - F["lipDn"] - .3 * u))
        tg["lip_" + sn] = Vector((mx + sd * .62 * u, O.y - F["fM"] + .25 * u, yM - .25 * u))
        tg["corner_" + sn] = Vector((mx + sd * .75 * u, O.y - F["fM"] + .3 * u, yM + .35 * u))
        tg["cheek_" + sn] = Vector((mx + sd * .85 * R, O.y - .55 * R, .5 * (yM + E.z) - .1 * R))
        tg["burn_" + sn] = Vector((O.x + sd * 1.0 * R, O.y - .05 * R, E.z - .6 * R))
        tg["jaw_" + sn] = Vector((O.x + sd * .75 * R, O.y + .1 * R, yC - .1 * R))
    # (round the mouth not snapped to that edge but put by the lips: under the lower lip - under the bare skin there
    # when it has it - and by the lips' corners; on a small chin the nearest edge was under it and the chin outside)
    top = yM - F["lipDn"]; hz = .5 * max(.15 * R, .45 * (top - yC))
    zch = top - 1.6 * hz if patch else top - .06 * R
    put = {}
    for sd, sn in ((1, "L"), (-1, "R")):
        for k, x_, z_ in (("chin_" + sn, mx + sd * .3 * u, zch), ("lip_" + sn, mx + sd * .62 * u, yM - .2 * u)):
            h = cast(Vector((x_, O.y - 4 * R, z_)), BACK, 8 * R, tree=bvh)
            if h:
                put[k] = h[0]
    out = {}
    for k in loop:
        if k in NODES_IN:
            out[k] = NODES_IN[k]
        elif k in TPL:   # (fitted by hand once, kept by the face's measures)
            out[k] = TPL[k]
        elif k in put:
            out[k] = put[k]
        elif bnd:
            out[k] = V[min(bnd, key=lambda i: (V[i] - tg[k]).length)].copy()
        else:
            out[k] = tg[k]
    # (the pairs mirror each other about the face's middle: snapped each to its own vertex they came out uneven)
    for k in loop:
        if k.endswith("_L") and k[:-2] + "_R" in out and k not in NODES_IN and k[:-2] + "_R" not in NODES_IN:
            a, b = out[k], out[k[:-2] + "_R"]
            m = (a + Vector((2 * mx - b.x, b.y, b.z))) / 2
            out[k] = full.find_nearest(m)[0] or m
            mm = Vector((2 * mx - m.x, m.y, m.z))
            out[k[:-2] + "_R"] = full.find_nearest(mm)[0] or mm
    return out


def beard_uv(F, p, conv):
    """the hairs down (v), across them round the head's axis (u); under the chin closing in on the wedge's point"""
    th = math.atan2(p.x - F["mx"], max(.5 * R, -(p.y - O.y)))   # (not round the axis under the jaw: it swirled there)
    return th * R * conv(p.z), -p.z


def flow_uv(bm, F, skip=()):
    """the hairs' unwrap along their fall: each vertex, from the top down, takes its across (u) from the ones above it
    along the surface's steepest way up (their way down: the hairs fall that way), its along (v) as theirs and the way
    from them; where nothing is above (the beard's top edge, under the lips) across is round the head. So the hairs
    go straight down the cheeks and the chin, from the throat to the point under it, closing in on the point"""
    bm.verts.ensure_lookup_table(); bm.normal_update()
    UV = {}
    for v in sorted(bm.verts, key=lambda v: -v.co.z):
        if v.index in skip:   # (a moustache joined to it: its own unwrap, along it)
            continue
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
    cfg = dict(BEARD[st])
    mmode = prm.get("must", "merge")   # the moustache: into the beard, over it (long, out past it), none
    if mmode == "none" and st != "mustache":
        cfg["must"] = None
    F = face_frame()
    if job.get("learn"):   # (the nodes fitted by hand kept as the default: only that)
        learn_template(F, st, job["learn"])
        sys.exit(0)
    load_template(F, st)
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
        def in_mouth(v):   # (the mouth's inside: hidden from the front behind the lips - the skin by its corners is not)
            if not (abs(v.x - mx) < 1.1 * mw and yM - 1.2 * F["lipDn"] < v.z < yM + 1.2 * F["lipUp"]):
                return False
            h = full.ray_cast(Vector((v.x, O.y - 4 * R, v.z)), BACK, 8 * R)
            return h[0] is not None and h[0].y < v.y - .03 * R
        OL = Outline([nodes[k] for k in LOOP], seeds, in_mouth, Vector((mx, O.y, yM)))
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
        a0 = cfg.get("W", 1.) * u * vol ** .3   # (the hanging part's half width: as the sculpted one's, the mouth's width)
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
        fldR = beard_field(F, st, cfg["patch"], OL)
        # (with an outline: a little past it, thinning to nothing just outside it - its edge then on the contour; the
        # edge's way in thinned it inside it and the remesh cut that off: the beard stopped short of its outline)
        def beard_t(p):   # (the beard's own thickness under a point of the moustache; none off it)
            if OL is None or fldR(p) < -.3 * R:
                return 0.
            return vol * R * (cfg["T"] + (cfg["J"] - cfg["T"]) * smooth(yM, yC - .3 * u, p.z))

        def beard_on(p):   # (its thickness where a moustache over it lies on it: the beard thick by it, to its edge)
            return 0. if OL is None else beard_t(p) * smooth(-.06 * R, .02 * R, fldR(p))
        mo = moustache(F, cfg["must"], vol, float(prm.get("length", .05)), beard_t if mmode == "merge" else None, mmode == "over",
                       beard_on if mmode == "over" else None) if cfg["must"] else None
        mpts = [(c, max(h_, d_)) for cen_, hs_, ds_ in MUST_LINES for c, h_, d_ in zip(cen_, hs_, ds_)]
        mend = [(c, max(h_, d_)) for cen_, hs_, ds_ in MUST_LINES for i_, (c, h_, d_) in enumerate(zip(cen_, hs_, ds_)) if i_ > .55 * len(cen_)]

        def by_must(p):   # (by the moustache: the beard thick right to its edge there - it has something to join)
            return any((p - c).length < r_ + .15 * R for c, r_ in mpts)

        def bridge(p):   # (under a moustache's end just past the beard's edge: the beard on to it - the two one; no wider
            # than the moustache: its edge, faded, showed round it as stubble; over the beard its ends stay out)
            return OL is not None and mmode == "merge" and fldR(p) > -.35 * R and any((p - c).length < r_ + .03 * R for c, r_ in mend)
        sh = scalp_shell((lambda p: fldR(p) > -.08 * R or bridge(p)) if OL is not None else beard_region(F, st, cfg["patch"]), lambda v: 0., "beard_base", close=3)
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
            if OL is not None:
                m_ = fldR(v.co)
                ramp = 1. if ((by_mouth(v.co) or by_must(v.co)) and m_ > -.02 * R) or bridge(v.co) else min(1., max(0., (m_ + .06 * R) / (.16 * R))) ** .6
            else:
                ramp = min(1., dist[v.index] / (.3 * R)) ** .6
            t = vol * R * (cfg["T"] + (cfg["J"] - cfg["T"]) * low) * ramp
            q = v.co + nn * (.015 * R + t)
            if Lh > 0:
                g = smooth(yC + .7 * u, yC - .1 * u, v.co.z) * smooth(fC - cfg.get("HB", 1.3) * R, fC - .15 * R, front(v.co))   # (a goatee's from the chin's front only: from the throat too it hung as a thick wedge)
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
                t = vol * R * (cfg["T"] + (cfg["J"] - cfg["T"]) * low) * min(1., max(0., mf[v.index] + .05 * R) / (.15 * R)) ** .6
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
            fade = {i: min(1., max(0., (m + .03 * R) / (.08 * R))) for i, m in mf.items()}
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
        merged = False
        if cfg["must"]:   # the moustache one body with the beard where they meet (no walls inside, no seam), its own texture
            bm.to_mesh(ob.data); bm.free()
            ob.data.materials.append(bpy.data.materials.new("hair_beard_tmp"))   # (slot 0 the beard's, the moustache's after)
            bo = ob.modifiers.new("join", "BOOLEAN"); bo.operation = "UNION"; bo.object = mo
            for k_, v_ in (("solver", "EXACT"), ("use_self", True), ("material_mode", "TRANSFER")):
                try:
                    setattr(bo, k_, v_)
                except (AttributeError, TypeError):
                    pass
            nf0 = len(ob.data.polygons)
            bpy.context.view_layer.objects.active = ob
            try:
                bpy.ops.object.modifier_apply(modifier=bo.name)
                merged = len(ob.data.polygons) > .5 * nf0 and any(p_.material_index == 1 for p_ in ob.data.polygons)
            except RuntimeError:
                merged = False
            if merged:
                bpy.data.objects.remove(mo, do_unlink=True)
            else:   # (the union failed: side by side, as before)
                if bo.name in ob.modifiers:
                    ob.modifiers.remove(bo)
                obs.append(mo)
            print("moustache joined" if merged else "moustache apart", flush=True)
            bm = bmesh.new(); bm.from_mesh(ob.data)
        MUST = {v.index for f in bm.faces if f.material_index == 1 for v in f.verts} if merged else set()
        # only what is out of the skin: its underside on the face, the wedge's back in the throat gone
        bm.normal_update()
        drop = []
        for f in bm.faces:
            s, nn = out_of_skin(f.calc_center_median())
            if f.material_index == 1:   # (the moustache's: on the lip as made - cut there it came out in stripes)
                if s < -.005 * R:
                    drop.append(f)
                continue
            # (its underside: on the skin, or in it; facing the skin only right by it - further off, in the crease
            # between the jaw and the neck, that took its outside too and opened holes there)
            if s < (.03 if Lh > .05 * R else .022) * R or (s < .05 * R and f.normal.dot(nn) < -.5):
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
        bmesh.ops.delete(bm, geom=[f for i in isl if len(i) < .12 * big and not any(f.material_index == 1 for f in i) for f in i], context="FACES")   # (not the moustache's)
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
        # (holes in it filled: in the crease between the jaw and the neck its body folds, and cut off by the skin
        # there its outside went too - the background showed through it from below; its outer edge and a hole round
        # the mouth - long - stay)
        bnd_e = {e for e in bm.edges if len(e.link_faces) == 1}
        loops, seen_e = [], set()
        for e0 in bnd_e:
            if e0 in seen_e:
                continue
            st_, cur_ = [e0], []; seen_e.add(e0)
            while st_:
                e = st_.pop(); cur_.append(e)
                for v in e.verts:
                    for e2 in v.link_edges:
                        if e2 in bnd_e and e2 not in seen_e:
                            seen_e.add(e2); st_.append(e2)
            loops.append(cur_)
        if len(loops) > 1:
            lens = [sum(e.calc_length() for e in lp) for lp in loops]
            longest = max(range(len(loops)), key=lambda i: lens[i])
            for i, lp in enumerate(loops):
                if i != longest and lens[i] < 1.0 * R:
                    try:
                        res = bmesh.ops.holes_fill(bm, edges=lp, sides=0)
                        bmesh.ops.triangulate(bm, faces=res.get("faces", []))
                    except Exception:   # noqa: BLE001
                        pass
        bm.normal_update()
        bm.verts.ensure_lookup_table()
        fixed = {v.index for v in bm.verts if any(f.material_index == 1 for f in v.link_faces)}   # (the moustache's: as made)
        conform(bm, .012 * R, .35 * R, (lambda p: None if bridge(p) and fldR(p) < -.02 * R else OL.edge_target(p)) if OL is not None else None, fixed)   # (its edge down on the skin: on its outline - not where it went on past it to the moustache; by the moustache it left the outline short, under the lip)
        push_out(bm, .012 * R)
        bm.verts.ensure_lookup_table()
        dist = edge_dist(bm)
        # dense at the skin (only a short fringe of hairs at its edge there), the hairs thinning to its ends (the
        # hanging part's lower half, to the point)
        fade = {}
        for v in bm.verts:
            end = smooth(yC - .45 * Lh, yC - 1.05 * Lh, v.co.z) if Lh > .05 * R else 0.
            # (no fade at its edge on the skin: dense there, as asked - put down on its outline its last faces were
            # drawn out, and the fade over them was a see-through patch: the background through it by the jaw)
            fade[v.index] = 1 - .85 * end ** .8
            if mpts and any((v.co - c).length < r_ + .05 * R for c, r_ in mpts):   # (by the moustache: whole, no fringe)
                fade[v.index] = 1.
        obs.insert(0, _beard_skin(ob, bm, fade, F, conv))
        return obs, obs[0]
    if cfg["must"]:
        obs.append(moustache(F, cfg["must"], vol, float(prm.get("length", .05))))
    return obs, obs[0]


def _beard_skin(ob, bm, fade, F, conv, stubble=False):
    """the hairs over a beard's mass: the flow of its hairs (down, round the head; its distance down), and on it the
    locks (_beard_locks) - or for stubble short hairs in a see-through texture; its edge fading out (the alpha). A
    moustache joined to it (its faces the second material) keeps its own unwrap and texture"""
    bm.faces.ensure_lookup_table(); bm.verts.ensure_lookup_table()
    old = bm.loops.layers.uv.get("UVMap") or (bm.loops.layers.uv.values()[0] if len(bm.loops.layers.uv) else None)
    keep = {f.index: [tuple(lp[old].uv) for lp in f.loops] for f in bm.faces if f.material_index == 1} if old is not None else {}
    skip = {v.index for v in bm.verts if v.link_faces and all(f.material_index == 1 for f in v.link_faces)}
    for lay in list(bm.loops.layers.uv.values()):
        bm.loops.layers.uv.remove(lay)
    UVV = flow_uv(bm, F, skip)
    us = [a for a, _ in UVV.values()]; vs = [b for _, b in UVV.values()]
    u0, v0, span = min(us), min(vs), max(max(us) - min(us), max(vs) - min(vs)) + 1e-6
    uvl = bm.loops.layers.uv.new("UVMap")
    for f in bm.faces:
        if f.index in keep:
            for lp, uv in zip(f.loops, keep[f.index]):
                lp[uvl].uv = uv
            continue
        for lp in f.loops:
            a, b = UVV.get(lp.vert.index, (u0, v0))
            lp[uvl].uv = ((a - u0) / span, (b - v0) / span)
    m = ob.data; bm.to_mesh(m); bm.free()
    for poly in m.polygons:
        poly.use_smooth = True
    if not stubble:
        return _beard_locks(ob, m, UVV, fade, skip)
    T = 1024
    PF = 1.6 * R   # (a fine tile's size on the face)
    fine = strands_tile(512, 512, 260, 1.5, 3., 31, False)
    uu = (np.arange(T) + .5) / T * span + u0
    vv = (np.arange(T) + .5) / T * span + v0
    UU, VV = np.meshgrid(uu, vv)
    fi = fine[((VV / PF * 512) % 512).astype(int), ((UU / PF * 512) % 512).astype(int)]
    fd = raster_fade(m, fade, T, 0 if keep else None)
    img = np.zeros((T, T, 4), np.float32)
    # (stubble: short hairs, a light shadow between them - the skin seen through)
    rs = np.random.default_rng(7)
    dots = np.zeros((T, T), np.float32)
    for _ in range(int(T * T * .045)):
        x, y = rs.integers(0, T, 2); ln = rs.integers(2, 6)
        dots[y:y + ln, x] = .6 + .4 * rs.random()
    lum = .18 + .1 * (1 - dots)
    img[..., 3] = np.clip(np.maximum(dots * .95, .28), 0, 1) * np.clip(fd * 1.2, 0, 1)
    img[..., :3] = lum[..., None] * COL[None, None, :]
    mat, _ = material("hair_beard", save("beard", img, True), True, .55)
    normal_map(mat, fi, "beard_normal")
    if len(m.materials):
        m.materials[0] = mat
    else:
        m.materials.append(mat)
    return ob


LOCK_K = {"short": .7, "goatee": .8}   # (a lock's size by the beard: a short or a small one's smaller)


def _hash_cells(P, cell):
    """points bucketed by a grid's cells: (cell of a point -> [its indices])"""
    key = np.floor(P / cell).astype(np.int64)
    kk = (key[:, 0] * 73856093) ^ (key[:, 1] * 19349663) ^ (key[:, 2] * 83492791)
    order = np.argsort(kk, kind="stable"); ks = kk[order]
    uq, st = np.unique(ks, return_index=True); en = np.append(st[1:], len(ks))
    look = {int(k): order[a:b] for k, a, b in zip(uq, st, en)}

    def near(c):
        kc = np.floor(np.asarray(c) / cell).astype(np.int64)
        out = [look.get(int(((kc[0] + i) * 73856093) ^ ((kc[1] + j) * 19349663) ^ ((kc[2] + k) * 83492791)))
               for i in (-1, 0, 1) for j in (-1, 0, 1) for k in (-1, 0, 1)]
        out = [o for o in out if o is not None]
        return np.concatenate(out) if out else np.zeros(0, np.int64)
    return near


def bomb_locks(P, N, Vv, locks, reach):
    """the locks' field at points of the surface (its texels, its vertices): each lock from its root down along the
    hairs' fall (its along by the flow's distance down, its across on the root's tangent plane), the highest at a point
    shown - its tip over the roots under it. -> (height, light, cover) per point"""
    K = len(P)
    best = np.full(K, -1e9, np.float32); hgt = np.zeros(K, np.float32)
    lum = np.full(K, .25, np.float32); cov = np.zeros(K, np.float32)
    near = _hash_cells(P, reach)
    for lk in locks:
        idx = near(lk["c"])
        if not len(idx):
            continue
        rel = P[idx] - lk["c"]
        t = (Vv[idx] - lk["v"]) / lk["L"]
        lat = rel @ lk["e"]
        xc = lk["bend"] * np.sin(np.pi * np.clip(t, 0, 1))
        hw = lk["w"] * np.sqrt(np.clip((t + .1) / .22, 0, 1)) * np.clip(1 - t, 0, 1) ** .85 + 1e-7
        s = (lat - xc) / hw
        ok = ((t >= -.1) & (t <= 1) & (np.abs(s) < 1) & (np.abs(rel @ lk["n"]) < .35 * R) & (N[idx] @ lk["n"] > .15)
              & (np.einsum("ij,ij->i", rel, rel) < reach * reach))
        prof = np.sqrt(np.clip(1 - s * s, 0, 1))
        tt = np.clip(t, 0, 1)
        el = .45 * prof + .9 * tt
        win = ok & (el > best[idx])
        if not win.any():
            continue
        iw = idx[win]; s, tt, prof = s[win], tt[win], prof[win]
        best[iw] = el[win]
        hi = lk["hairs"][np.clip(((s + 1) * 23.5).astype(int), 0, 47)]
        st = .45 * (.5 + .5 * np.cos(np.pi * s * 3.5 + lk["ph"])) + .55 * hi
        hgt[iw] = .55 * prof + .45 * tt ** .7 + .06 * st
        lum[iw] = lk["br"] * (.4 + .6 * prof ** .7) * (.5 + .5 * np.clip(tt / .4, 0, 1)) * (.6 + .4 * st)
        cov[iw] = prof * (1 - .35 * tt)
    return hgt, lum, cov


def _beard_locks(ob, m, UVV, fade, skip, name="beard", k=None, lw=(.085, .14), ll=(.4, .62), rmin=.13, relief=.05, T=1024, alpha=(.7, .9)):
    """the beard's hairs as locks laid on its surface itself (not through a tile on an unwrap: down a beard hanging
    to a point the hairs' unwrap is squeezed across many times - every lock smeared sideways into bands): pointed
    locks a constant size on it, rooted all over it, each down along the hairs' fall, its tip over the roots under it,
    strands in it; drawn into an unwrap of its own (no squeeze) as its colour, alpha (thinning to its ends: the locks'
    middles only) and normal map, and as relief in its shape. The same for a hairstyle's smooth base (its own lock
    sizes: lw, ll - half width, length - and rmin, x R; its v the way to where it is gathered)"""
    rng = np.random.default_rng(int(prm.get("seed", 1)) * 11 + 5)
    if k is None:
        k = LOCK_K.get(style, 1.) * float(prm.get("vol", 1.)) ** .3
    nv = len(m.vertices)
    Pv = np.array([v.co[:] for v in m.vertices], np.float32)
    Nv = np.array([v.normal[:] for v in m.vertices], np.float32)
    Vv = np.array([UVV.get(i, (0., 0.))[1] for i in range(nv)], np.float32)
    beard_v = np.array([i not in skip and i in UVV for i in range(nv)])
    Fv = np.array([fade.get(i, 1.) for i in range(nv)], np.float32)
    # the hairs' way at each vertex: down its flow (the flow's distance's growth, on the surface)
    ed = np.zeros(len(m.edges) * 2, np.int64); m.edges.foreach_get("vertices", ed); ed = ed.reshape(-1, 2)
    g = np.zeros((nv, 3), np.float32)
    for a, b in ((0, 1), (1, 0)):
        dp = Pv[ed[:, b]] - Pv[ed[:, a]]; dv = Vv[ed[:, b]] - Vv[ed[:, a]]
        ok = beard_v[ed[:, a]] & beard_v[ed[:, b]]
        np.add.at(g, ed[ok, a], dp[ok] * (dv[ok] / np.maximum(np.einsum("ij,ij->i", dp[ok], dp[ok]), 1e-12))[:, None])
    g -= Nv * np.einsum("ij,ij->i", g, Nv)[:, None]
    down = -(np.array(UP[:], np.float32)[None, :] - Nv * Nv[:, 2:3])
    gl = np.linalg.norm(g, axis=1)
    D = np.where(gl[:, None] > 1e-6, g / np.maximum(gl, 1e-9)[:, None], down / np.maximum(np.linalg.norm(down, axis=1), 1e-9)[:, None])
    # roots: spread over it (darts: none nearer another than rmin)
    rmin = rmin * R * k
    cand = rng.permutation(np.nonzero(beard_v)[0])
    taken, cells = [], {}
    for i in cand:
        c = Pv[i]; kc = tuple(np.floor(c / rmin).astype(int))
        if any(np.dot(Pv[j] - c, Pv[j] - c) < rmin * rmin for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1)
               for j in cells.get((kc[0] + dx, kc[1] + dy, kc[2] + dz), ())):
            continue
        cells.setdefault(kc, []).append(i); taken.append(i)
    locks = []
    for i in taken:
        n = Nv[i]; d = D[i]; e = np.cross(n, d); e /= max(1e-9, np.linalg.norm(e))
        w = rng.uniform(*lw) * R * k
        locks.append(dict(c=Pv[i], n=n, e=e, v=Vv[i], w=w, L=rng.uniform(*ll) * R * k, bend=rng.uniform(-.5, .5) * w,
                          br=rng.uniform(.72, 1.), ph=rng.uniform(0, 6.28), hairs=rng.uniform(0, 1, 48) ** .7))
    reach = (max(ll) + max(lw)) * 1.05 * R * k
    # its own unwrap (the beard's faces; a joined moustache's keep theirs)
    bpy.ops.object.select_all(action="DESELECT")
    bpy.context.view_layer.objects.active = ob; ob.select_set(True)
    bpy.ops.object.mode_set(mode="EDIT")
    bme = bmesh.from_edit_mesh(m)
    for f in bme.faces:
        f.select = f.material_index != 1
    bmesh.update_edit_mesh(m)
    bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=.006)
    bpy.ops.object.mode_set(mode="OBJECT")
    # its texels: their place, normal, distance down the flow, fade (barycentric from the triangles)
    att = np.concatenate([Pv, Nv, Vv[:, None], Fv[:, None]], axis=1)
    buf = np.zeros((T, T, att.shape[1]), np.float32); got = np.zeros((T, T), bool)
    uvd = m.uv_layers.active.data
    m.calc_loop_triangles()
    for tri in m.loop_triangles:
        if m.polygons[tri.polygon_index].material_index == 1:
            continue
        li = tri.loops
        pu = np.array([uvd[j].uv[0] * T for j in li]); pv = np.array([uvd[j].uv[1] * T for j in li])
        x0, x1 = int(max(0, pu.min() - 1)), int(min(T - 1, pu.max() + 1))
        y0, y1 = int(max(0, pv.min() - 1)), int(min(T - 1, pv.max() + 1))
        den = (pv[1] - pv[2]) * (pu[0] - pu[2]) + (pu[2] - pu[1]) * (pv[0] - pv[2])
        if x1 < x0 or y1 < y0 or abs(den) < 1e-12:
            continue
        gx, gy = np.meshgrid(np.arange(x0, x1 + 1) + .5, np.arange(y0, y1 + 1) + .5)
        l0 = ((pv[1] - pv[2]) * (gx - pu[2]) + (pu[2] - pu[1]) * (gy - pv[2])) / den
        l1 = ((pv[2] - pv[0]) * (gx - pu[2]) + (pu[0] - pu[2]) * (gy - pv[2])) / den
        l2 = 1 - l0 - l1
        ins = (l0 >= -.02) & (l1 >= -.02) & (l2 >= -.02)
        vt = tri.vertices
        val = l0[..., None] * att[vt[0]] + l1[..., None] * att[vt[1]] + l2[..., None] * att[vt[2]]
        sub = buf[y0:y1 + 1, x0:x1 + 1]; sg = got[y0:y1 + 1, x0:x1 + 1]
        sub[ins] = val[ins]; sg[ins] = True
    tp = buf[got]
    tn = tp[:, 3:6] / np.maximum(np.linalg.norm(tp[:, 3:6], axis=1), 1e-9)[:, None]
    h_, l_, c_ = bomb_locks(tp[:, :3], tn, tp[:, 6], locks, reach)
    hgt = np.zeros((T, T), np.float32); lum = np.zeros((T, T), np.float32); cvr = np.zeros((T, T), np.float32); fd = np.zeros((T, T), np.float32)
    hgt[got], lum[got], cvr[got], fd[got] = h_, l_, c_, tp[:, 7]
    for _ in range(8):   # (out past the islands' edges: no dark seams by the texture's filtering)
        has = got.astype(np.float32)
        acc = [np.zeros((T, T), np.float32) for _ in range(4)]; cnt = np.zeros((T, T), np.float32)
        for ax, sh in ((0, 1), (0, -1), (1, 1), (1, -1)):
            hs = np.roll(has, sh, ax); cnt += hs
            for q, a_ in zip(acc, (hgt, lum, cvr, fd)):
                q += np.roll(a_ * has, sh, ax)
        grow = (~got) & (cnt > 0)
        for q, a_ in zip(acc, (hgt, lum, cvr, fd)):
            a_[grow] = q[grow] / cnt[grow]
        got = got | grow
    img = np.zeros((T, T, 4), np.float32)
    img[..., :3] = (.15 + .85 * lum)[..., None] * COL[None, None, :]
    # (where it covers: whole; thinning to its ends, the locks' middles only - each there or not, no speckle)
    img[..., 3] = np.clip((fd - alpha[0] + alpha[1] * cvr) * (alpha[2] if len(alpha) > 2 else 4), 0, 1)   # (a base's: a crisp line - its locks spilled past it as a ragged fringe)
    mat, _ = material(f"hair_{name}", save(name, img, True), True, .55)
    normal_map(mat, hgt, f"{name}_normal", 3.)
    if len(m.materials):   # (slot 0 the beard's; a joined moustache's after it)
        m.materials[0] = mat
    else:
        m.materials.append(mat)
    # the locks as relief in its shape (not at its edge: it lies on the skin there; not the moustache)
    hv, _, _ = bomb_locks(Pv, Nv, Vv, locks, reach)
    acc = np.zeros(nv, np.float32); cnt = np.zeros(nv, np.float32)
    np.add.at(acc, ed[:, 0], hv[ed[:, 1]]); np.add.at(acc, ed[:, 1], hv[ed[:, 0]])
    np.add.at(cnt, ed[:, 0], 1); np.add.at(cnt, ed[:, 1], 1)
    hv = np.where(cnt > 0, .5 * hv + .5 * acc / np.maximum(cnt, 1), hv)
    dsp = (hv - .5) * relief * R * k * Fv * beard_v
    m.vertices.foreach_set("co", (Pv + Nv * dsp[:, None]).ravel())
    m.update()
    print("locks %d" % len(locks), flush=True)
    return ob


MUST_LINES = []   # the moustache's halves: (their middle line, half heights, half depths) - the beard thick by them


def moustache(F, kind, vol, length, under=None, over=False, on=None):
    """two thick locks from the middle under the nose out along the upper lip over the mouth's corners, tapering to a
    point: a handlebar's ends curled up, a long beard's drooping to the chin, a short one's ending at the corners"""
    yM, mx, u, yS = F["yM"], F["mx"], F["u"], F["yS"]
    kl = (length / .045) ** .5 if kind == "handlebar" and style == "mustache" else 1.
    span, drop, curl, hk = {"handlebar": (1.3, .3, .38, 1.25), "short": (.62, .1, 0., .9), "droop": (1.1, 1.2, 0., 1.25),
                            "goatee": (1.0, .1, .32, 1.)}[kind]   # (a goatee's: over the lips, curled - not down into it)
    if over:   # (over the beard: long, its ends out past it, curled - as the sculpted one's)
        span, curl, hk = span * 1.35, max(curl, .3), hk * 1.1
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
    spiral = curl0 > 0 and under is None   # (its ends curled: a spiral on past them; sunk into a beard, none)
    MUST_LINES.clear()
    MS = .45   # (a half's middle: its thickness there by its own nodes)

    lipz = yM + .5 * F["lipUp"]

    def anchor(x, z):
        """the skin's point at a width and a height under the nose: the upper lip found there first (from outside, at
        its own height - the nose is above it), then from just in front of it at the height wanted, back: a ray
        from outside at that height met a long nose's tip hanging in front, and the moustache stood on it"""
        ph = math.asin(max(-.98, min(.98, (x - mx) / rf)))
        d = Vector((math.sin(ph), -math.cos(ph), 0))
        h = cast(Vector((mx, O.y, lipz)) + d * (3 * R), -d, 3 * R, tree=bvh)
        base = h[0] if h else Vector((mx, O.y, lipz)) + d * rf
        h2 = cast(base + UP * (z - lipz) + d * (.08 * R), -d, 1.5 * R, tree=bvh)
        if h2:
            nn = h2[1].normalized()
            return h2[0], (nn if nn.dot(d) > 0 else -nn)
        return base + UP * (z - lipz), d

    def skin_at(x, z):
        return anchor(x, z)[0]

    def lagr(f0, f1, f2, t):   # (through the three stations: 0, its middle, its end)
        return f0 * (t - MS) * (t - 1) / MS + f1 * t * (t - 1) / (MS * (MS - 1)) + f2 * t * (t - MS) / (1 - MS)
    for sd in (1, -1):
        sn = "L" if sd > 0 else "R"
        span = span0; drop = drop0; curl = curl0

        def prof0(s):   # the default: (its x, its top edge's height, its bottom edge's)
            ph = sd * max(0., s) * span / rf
            dz = -drop * math.sin(min(1., max(0., s) / .75) * math.pi / 2) + (0. if spiral else curl * max(0., (s - .55) / .45) ** 2)
            if kind == "droop":   # (down past the corners to the jaw)
                dz = -drop * max(0., s) ** 1.3
            # its top under the nose all along it (up under the wings), its bottom over the mouth's line; tapering
            top = yS + dz
            n_b = nose_bottom(mx + sd * max(0., s) * span) if kind != "short" else None
            if n_b is not None:   # (blended off past the wings: no step)
                wn = 1 - smooth(.4, .75, s)
                top = top + wn * max(0., n_b - .015 * R - top)
            bot = low + dz
            tap = max(.04, (1 - (.55 if spiral else 1.) * max(0., s) ** 1.6)) ** .7   # (curled: thick on into its curl)
            zc = .5 * (top + bot)
            hgt = max(.05 * R, .5 * (top - bot)) * tap * (.9 + .1 * hk * vol ** .5)
            return mx + rf * math.sin(ph), zc + hgt, zc - hgt
        # its outline's nodes: the middle's top (under the nose) and bottom, a half's top and bottom at its middle,
        # its end; the user's where moved, the default's otherwise
        st0, stm, st1 = prof0(0.), prof0(MS), prof0(1.)
        dflt = {"must_ct": (mx, st0[1]), "must_cb": (mx, st0[2]), "must_top_" + sn: (stm[0], stm[1]),
                "must_bot_" + sn: (stm[0], stm[2]), "must_" + sn: (st1[0], .5 * (st1[1] + st1[2])),
                "must_lo_" + sn: (st1[0], .5 * (st1[1] + st1[2]) - .01 * R)}   # (its end's top and bottom: apart, a blunt end)
        given = {**MUST_TPL, **NODES_IN}   # (by hand; or the default fitted by hand once)
        mine = any(k in given for k in dflt)
        val = {k: ((given[k].x, given[k].z) if k in given else v) for k, v in dflt.items()}
        for k, (x_, z_) in val.items():
            if k not in NODES_OUT or k in NODES_IN:
                NODES_OUT[k] = NODES_IN[k] if k in NODES_IN else skin_at(x_, z_)

        def prof(s):
            if not mine:
                return prof0(s)
            t = max(0., s)
            x0, xm, x1 = mx, val["must_top_" + sn][0] * .5 + val["must_bot_" + sn][0] * .5, val["must_" + sn][0] * .5 + val["must_lo_" + sn][0] * .5
            top = lagr(val["must_ct"][1], val["must_top_" + sn][1], val["must_" + sn][1], t)
            bot = lagr(val["must_cb"][1], val["must_bot_" + sn][1], val["must_lo_" + sn][1], t)
            if top < bot:
                top, bot = bot, top
            x_ = lagr(x0, xm, x1, t)
            n_b = nose_bottom(x_)
            if n_b is not None and n_b - top < .12 * R:   # (up under the nose's wings, when it is near: skin showed between)
                top += (1 - smooth(.4, .75, t)) * max(0., n_b - .015 * R - top)
            return x_, top, bot
        cen, hs, ds, sps, nns = [], [], [], [], []
        for i in range(Nr + 1):
            s = -.08 + 1.08 * i / Nr
            x_, top, bot = prof(s)
            zc, hgt = .5 * (top + bot), max(.008 * R, .5 * (top - bot))
            dep = min(hgt * .75, .11 * R * vol ** .5) if hgt > .02 * R else hgt * .75
            sp_, nn = anchor(x_, zc)   # (on the skin under the nose, not on its tip)
            c = sp_ + nn * (.015 * R + dep)
            sps.append(sp_); nns.append(nn)
            cen.append(c); hs.append(hgt); ds.append(dep)
        if under is not None:   # over the beard: sunk into it, as thick as it there - not a lock cut off on top of it
            tb = [under(p_) for p_ in sps]
            first = next((i for i, t_ in enumerate(tb) if t_ > 0 and i > .3 * len(tb)), None)
            if first is not None:
                for i in range(first, len(tb)):
                    k = min(1., (i - first + 1) / 4)
                    t_ = max(tb[i], .02 * R)
                    ds[i] += (min(ds[i], .5 * t_) - ds[i]) * k
                    hs[i] += (min(hs[i], max(.6 * t_, .03 * R)) - hs[i]) * k
                    cen[i] = cen[i] + ((sps[i] + nns[i] * max(.012 * R, t_ - ds[i])) - cen[i]) * k   # (its top at the beard's)
        if on is not None:   # over the beard: on it, its thickness under it (none by the nose), not sunk in it
            lift = [on(p_) for p_ in sps]
            for _ in range(4):
                lift = [lift[0]] + [(lift[i - 1] + 2 * lift[i] + lift[i + 1]) / 4 for i in range(1, len(lift) - 1)] + [lift[-1]]
            cen = [c + nns[i] * lift[i] for i, c in enumerate(cen)]
        for _ in range(3):   # (its line smooth over the lips' bumps)
            cen = [cen[0]] + [(cen[i - 1] + cen[i] * 2 + cen[i + 1]) / 4 for i in range(1, len(cen) - 1)] + [cen[-1]]
        MUST_LINES.append((list(cen), list(hs), list(ds)))
        if "must_" + sn not in given and "must_lo_" + sn not in given:
            NODES_OUT["must_" + sn] = cen[-1] + UP * max(.005 * R, hs[-1])
            NODES_OUT["must_lo_" + sn] = cen[-1] - UP * max(.005 * R, hs[-1])
        if spiral and len(cen) > 4:   # its end curled: on past it a spiral up and back in over itself, thinning to a point
            im = int(MS * Nr)
            h1, d1 = max(hs[-1], .75 * hs[im]), max(ds[-1], .75 * ds[im])   # (not pinched before its curl: a lock curled, not a wire)
            n0 = int(.7 * len(cen))
            for i in range(n0, len(cen)):
                k = (i - n0) / max(1, len(cen) - 1 - n0)
                hs[i] = max(hs[i], hs[n0] + (h1 - hs[n0]) * k); ds[i] = max(ds[i], ds[n0] + (d1 - ds[n0]) * k)
            # (its curl facing the front, as a handlebar's: in the skin's plane by the mouth's corner it was seen edge on)
            C0, t0 = cen[-1], (cen[-1] - cen[-4]).normalized()
            nn0 = (nns[-1] + FRONT * 1.5).normalized()
            # (out first, then up: its end going down by the mouth curled down under the lip)
            out_ = X * sd + t0 * max(0., t0.dot(X * sd)) - UP * .3
            e1 = (out_ - nn0 * nn0.dot(out_)).normalized(); e2 = nn0.cross(e1).normalized()
            if e2.dot(UP) < 0:
                e2.negate()
            r0, PHI, NC = .6 * curl0, 1.5 * math.pi, 20
            for q in range(1, NC + 1):
                f = q / NC; ph = PHI * f; r_ = r0 * (1 - .5 * f)
                cen.append(C0 + e2 * r0 + (e1 * math.sin(ph) - e2 * math.cos(ph)) * r_ + nn0 * (.35 * r0 * f))
                hs.append(h1 * max(.1, 1 - f ** 1.5) ** .7); ds.append(d1 * max(.1, 1 - f ** 1.5) ** .7)
        rows, sl = [], 0.
        for i, c in enumerate(cen):
            if i:
                sl += (c - cen[i - 1]).length
            t = (cen[min(len(cen) - 1, i + 1)] - cen[max(0, i - 1)]).normalized()
            n1 = (UP if i == 0 else n1) - t * (UP if i == 0 else n1).dot(t)   # (carried along it: round its curl too)
            n1.normalize(); n2 = t.cross(n1).normalized()
            rows.append(([bm.verts.new(c + n1 * (math.cos(a) * hs[i]) + n2 * (math.sin(a) * ds[i])) for a in (j / M * 2 * math.pi for j in range(M))], sl))
        cap = list(rows[0][0]) if sd < 0 else list(reversed(rows[0][0]))   # (its root closed)
        fc = bm.faces.new(cap)
        for lp in fc.loops:
            lp[uvl].uv = (0., .5)
        for i in range(len(rows) - 1):
            for j in range(M):
                q = [rows[i][0][j], rows[i + 1][0][j], rows[i + 1][0][(j + 1) % M], rows[i][0][(j + 1) % M]]
                # (its hairs top to bottom as the beard's: down round its section from its top edge over its front
                # - and its back the same way - slanting out; along it they read as a rope)
                uq = [(rows[i][1], j / M), (rows[i + 1][1], j / M), (rows[i + 1][1], (j + 1) / M), (rows[i][1], (j + 1) / M)]
                if sd < 0:
                    q.reverse(); uq.reverse()
                f = bm.faces.new(q)
                L_ = max(1e-6, rows[-1][1])
                for lp, (a, t_) in zip(f.loops, uq):
                    vv_ = 1 - abs(2 * t_ - 1)
                    kk = .07 + .3 * min(1., max(0., a / L_)) ** 1.3   # (its slant: ~20 degrees at its middle, ~60 to its end)
                    lp[uvl].uv = (a / (1.5 * R) + kk * vv_, vv_)
        fe = bm.faces.new(list(rows[-1][0]) if sd > 0 else list(reversed(rows[-1][0])))   # (its end closed: blunt, or a point)
        for lp in fe.loops:
            lp[uvl].uv = (rows[-1][1] / (1.5 * R), .5)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    push_out(bm, .01 * R)   # (not into the upper lip's bulge: a thin one's middle went behind it)
    for _ in range(2):   # (the push's bumps off)
        bmesh.ops.smooth_vert(bm, verts=bm.verts[:], factor=.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    bm.normal_update()
    mm = bpy.data.meshes.new("hair_moustache"); bm.to_mesh(mm); bm.free()
    ob = bpy.data.objects.new("hair_moustache", mm); sc.collection.objects.link(ob)
    for poly in mm.polygons:
        poly.use_smooth = True
    # (its locks as the beard's: from its top edge down round it - u along it is 1.5 R a tile, v its half section)
    tile = strands_tile(256, 512, 90, 1.5, 3., 41, False)
    lh, ll, _ = locks_tile(256, 512, 14, 2, 43, nstr=5., reach=1.7)
    lum = (.18 + .82 * ll) * (.88 + .12 * tile)
    img = np.zeros((512, 256, 3), np.float32); img[...] = lum[..., None] * COL[None, None, :]
    mat, _ = material("hair_moustache", save("moustache", img, False), False, .55)
    normal_map(mat, lh * .9 + tile * .1, "moustache_normal")
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


# ---------------------------------------------------------------- hair gathered: braids, buns, tails (the user's references, 2026-11-22)
# Over a smooth base - the hair combed from a middle parting to where it is gathered, its locks painted on its surface
# (as a beard's) - braids, a bun, tails, wisps by the face; or long cards with waves, braids from the temples over them.
def resample(pts, step, closed=False):
    P = list(pts) + ([pts[0]] if closed else [])
    cum = [0.]
    for a, b in zip(P, P[1:]):
        cum.append(cum[-1] + (b - a).length)
    S = cum[-1]
    n = max(2, int(round(S / step)))
    out, j = [], 0
    for i in range(n + (0 if closed else 1)):
        s_ = S * i / n
        while j < len(cum) - 2 and cum[j + 1] < s_:
            j += 1
        t = (s_ - cum[j]) / max(1e-12, cum[j + 1] - cum[j])
        out.append(P[j].lerp(P[j + 1], t))
    return out


def scalp_at(th, z, out=0.):
    """the scalp's point at an angle round the head's axis (0 the face, +90 its left) and a height over its middle
    (x R), from outside (the ears left out), and its outward normal; out: raised off it"""
    d = Vector((math.sin(th), -math.cos(th), 0))
    c = Vector((O.x, O.y, O.z + z * R))
    h = cast(c + d * (3 * R), -d, 3 * R, tree=bvh)
    if not h:
        return c + d * R, d
    nn = h[1].normalized()
    nn = nn if nn.dot(h[0] - O) > 0 else -nn
    return h[0] + nn * out, nn


def tube_e(bm, uvl, Q, ra, rb, axis, closed=False, M=10, vs=None, mat=0, caps=True, u_k=1.):
    """a tube along Q, its section an ellipse: ra along axis (each point's), rb across it; its unwrap round it (u) and
    along it (v, every vs of its length one tile)"""
    vs = vs or R
    n = len(Q); rows = []; s_ = 0.
    for i, q in enumerate(Q):
        if i:
            s_ += (q - Q[i - 1]).length
        t = ((Q[(i + 1) % n] - Q[i - 1]) if closed else (Q[min(n - 1, i + 1)] - Q[max(0, i - 1)])).normalized()
        ea = axis[i] - t * axis[i].dot(t)
        ea = ea.normalized() if ea.length > 1e-9 else t.orthogonal().normalized()
        eb = t.cross(ea)
        rows.append(([bm.verts.new(q + ea * (math.cos(a) * ra[i]) + eb * (math.sin(a) * rb[i])) for a in (j / M * 2 * math.pi for j in range(M))], s_))
    for i in range(n if closed else n - 1):
        r0, r1 = rows[i], rows[(i + 1) % n]
        v0, v1 = r0[1] / vs, (r1[1] if i + 1 < n else rows[-1][1] + (Q[0] - Q[-1]).length) / vs
        for j in range(M):
            f = bm.faces.new((r0[0][j], r1[0][j], r1[0][(j + 1) % M], r0[0][(j + 1) % M]))
            f.material_index = mat
            for lp, uv in zip(f.loops, ((j / M * u_k, v0), (j / M * u_k, v1), ((j + 1) / M * u_k, v1), ((j + 1) / M * u_k, v0))):
                lp[uvl].uv = uv
    if caps and not closed:
        for r, rev in ((rows[0][0], True), (rows[-1][0], False)):
            f = bm.faces.new(list(reversed(r)) if rev else r)
            f.material_index = mat
            for lp in f.loops:
                lp[uvl].uv = (.5 * u_k, 0.)
    return rows


def out_of(p):
    """the body's outward way at a point (from its nearest skin)"""
    loc, nrm, fi, d = full.find_nearest(p)
    if loc is None:
        return (p - O).normalized()
    o = p - loc
    return o.normalized() if o.length > 1e-7 else nrm.normalized()


def braid(bm, uvl, path, w, closed=False, tassel=0., tie=True, outs=None):
    """a plait of three locks along a path, w its half width: each lock goes side to side and over and under the others
    (across sin t, out sin 2t, a third of a turn apart: where two cross one is over the other), flattened; an open one
    narrows to a tie and ends in a tassel (its length); a closed one (round the head) is whole"""
    A, Dp, a, b = .6, .7, .33, .21
    P = resample(path, .1 * w, closed)
    n = len(P)
    cum = [0.]
    for i in range(1, n):
        cum.append(cum[-1] + (P[i] - P[i - 1]).length)
    S = cum[-1] + ((P[0] - P[-1]).length if closed else 0.)
    pitch = 2.4 * w
    if closed:
        pitch = S / max(3, round(S / pitch))
    T_, O_, SD = [], [], []
    if outs is not None:   # (the outward ways given at the path's own points: each new point takes its nearest's)
        from mathutils.kdtree import KDTree
        kp = KDTree(len(path))
        for i, q in enumerate(path):
            kp.insert(q, i)
        kp.balance()
    for i, p in enumerate(P):
        t = ((P[(i + 1) % n] - P[i - 1]) if closed else (P[min(n - 1, i + 1)] - P[max(0, i - 1)])).normalized()
        o = outs[kp.find(p)[1]] if outs is not None else out_of(p)
        T_.append(t); O_.append(o)
    for _ in range(6):   # (the outward way smoothed along it: from a lumpy skin it turned and the locks twisted)
        O_ = [(O_[i - 1] + 2 * O_[i] + O_[(i + 1) % n]) if closed or 0 < i < n - 1 else O_[i] for i in range(n)]
        O_ = [o.normalized() for o in O_]
    for i in range(n):
        o = O_[i] - T_[i] * O_[i].dot(T_[i]); O_[i] = o.normalized(); SD.append(T_[i].cross(O_[i]))

    def tap(s_):   # (to its tie: narrower)
        return 1. if closed else 1. - .45 * smooth(S - 2.6 * w, S, s_)
    for k in range(3):
        Q, ra, rb = [], [], []
        for i in range(n):
            ph = 2 * math.pi * cum[i] / pitch + 2 * math.pi * k / 3; tp = tap(cum[i])
            Q.append(P[i] + SD[i] * (A * w * tp * math.sin(ph)) + O_[i] * (.5 * Dp * w * tp * math.sin(2 * ph)))
            ra.append(a * w * tp); rb.append(b * w * tp)
        tube_e(bm, uvl, Q, ra, rb, SD, closed, M=10, vs=1.2 * R, caps=not closed, u_k=.5)
    if closed:
        return
    end, t_end = P[-1], T_[-1]
    if tie:   # (a band round its end)
        q = [end - t_end * (.1 * w) + t_end * (.35 * w * i / 4) for i in range(5)]
        tube_e(bm, uvl, q, [.62 * w] * 5, [.62 * w] * 5, [SD[-1]] * 5, M=14, mat=1)
    if tassel > 0:   # (its tassel: out of the band, swelling, to a point - on down its way, falling)
        L_ = tassel; m_ = 14; q = [end + t_end * (.2 * w)]; d = t_end.copy()
        for i in range(1, m_ + 1):
            d = (d - UP * .12).normalized()
            q.append(q[-1] + d * (L_ / m_))
        rr = [w * (.55 + .25 * math.sin(math.pi * min(1., i / m_ / .5) / 2)) * (1 - (i / m_) ** 2.2) + .01 * w for i in range(m_ + 1)]
        tube_e(bm, uvl, q, rr, [x * .8 for x in rr], [SD[-1]] * (m_ + 1), M=12, vs=1.2 * R, u_k=.5)


def drape(root, d0, L, gap, n=26, front=1., iters=140):
    """a hanging lock's line (a braid's, a tail's) from its root: its first link along d0, then a chain of fixed links
    under gravity meeting the body (rubbing on it), pulled a little forward (front > 0: onto the chest) or back"""
    rest = L / n
    pos = [root.copy(), root + d0 * rest]
    for i in range(2, n + 1):
        pos.append(pos[-1] - UP * rest)
    prev = [p.copy() for p in pos]
    G = Vector((0, 0, -9.8)) * (H / 1.0); dt2 = (1 / 30) ** 2
    for it in range(iters):
        for i in range(2, n + 1):
            v = (pos[i] - prev[i]) * .85
            pull = FRONT * (2. * front * H) if pos[i].z < E.z - R else Vector()   # (from under the ears on: it chose the back over a shoulder)
            old = pos[i].copy(); prev[i] = old
            new = old + v + (G + pull) * dt2
            mv = new - old; ml = mv.length
            if ml > 1e-9:
                hit, hn, hi, hd = full.ray_cast(old, mv / ml, ml + gap)
                if hit is not None:
                    hn = hn.normalized(); hn = hn if hn.dot(mv) < 0 else -hn
                    new = hit + hn * gap + (mv - hn * mv.dot(hn)) * .4
            pos[i] = new
        for c in range(3):
            for i in range(2, n + 1):
                d = pos[i] - pos[i - 1]; Lc = d.length
                if Lc > 1e-9:
                    pos[i] = pos[i - 1] + d * (rest / Lc)
            for i in range(3, n + 1):   # (stiff: not bending much - a braid is)
                d = pos[i] - pos[i - 2]; Lc = d.length; want = 1.9 * rest
                if 1e-9 < Lc < want:
                    pos[i] = pos[i] + d * ((want - Lc) / Lc * .5)
            for i in range(2, n + 1):
                loc, nrm, fi, dist = full.find_nearest(pos[i])
                if loc is not None:
                    nn = nrm.normalized(); side = (pos[i] - loc).dot(nn)
                    if side < gap:
                        pos[i] = pos[i] + nn * (gap - side)
    for _ in range(12):
        pos = [pos[0], pos[1]] + [pos[i] * .5 + (pos[i - 1] + pos[i + 1]) * .25 for i in range(2, n)] + [pos[n]]
        for i in range(2, n + 1):
            loc, nrm, fi, dist = full.find_nearest(pos[i])
            if loc is not None:
                nn = nrm.normalized(); side = (pos[i] - loc).dot(nn)
                if side < gap:
                    pos[i] = pos[i] + nn * (gap - side)
    return pos


def coil(c, nb, r0, turns=2.3, rise=.9, lift=0.):
    """a bun's line: a spiral on the head round c (nb its way out), from its outside in, rising as it goes in"""
    e1 = (UP - nb * nb.dot(UP)); e1 = e1.normalized() if e1.length > 1e-6 else X.copy()
    e2 = nb.cross(e1)
    pts = []
    m_ = int(48 * turns)
    for i in range(m_ + 1):
        f = i / m_; ph = 2 * math.pi * turns * f
        r = r0 * (1 - .62 * f)
        q = c + (e1 * math.cos(ph) + e2 * math.sin(ph)) * r
        h = cast(q + nb * (2 * R), -nb, 4 * R, tree=bvh)   # (down onto the head under it)
        base = h[0] if h else q
        pts.append(base + nb * (lift + rise * r0 * f ** .8))   # (each ring higher in: a bun's dome)
    return pts


def crown_loop(zf, zs, zb, out):
    """a braid's line round the head: at zf over its middle at the forehead, zs over the ears, zb behind (x R)"""
    pts, nrm = [], []
    for i in range(96):
        th = 2 * math.pi * i / 96
        fb = abs(math.atan2(math.sin(th), math.cos(th))) / math.pi
        z = zf + (zs - zf) * smooth(0, .5, fb) if fb < .5 else zs + (zb - zs) * smooth(.5, 1., fb)
        p, nn = scalp_at(th, z, out)
        pts.append(p); nrm.append(nn)
    return pts, nrm


def sleek_base(gathers, lift=.035, part=.9, name="sleek", px=None):
    """the hair combed smooth to where it is gathered: the scalp under the hairline raised a little (rounded off to its
    edge, fuller round the gatherings), its locks long and fine, each from the middle parting out and on to the
    nearest gathering (the way to it, the parting's: their sum's way - the hairs' flow)"""
    G = np.array([g[:] for g in gathers], np.float32)

    def to_g(p):
        return float(np.min(np.linalg.norm(G - np.array(p[:], np.float32), axis=1)))
    bm = bmesh.new(); bm.from_mesh(me); bm.transform(skin.matrix_world)
    for lay in list(bm.verts.layers.deform.values()):
        bm.verts.layers.deform.remove(lay)
    over = hair_field
    keep = {v for v in bm.verts if over(v.co) > -.1 * R and ear_gap(v.co) > .015 * R and v.index not in ear_v}
    grown = set(keep)
    for _ in range(4):
        grown |= {e.other_vert(v) for v in grown for e in v.link_edges if ear_gap(e.other_vert(v).co) > .015 * R and e.other_vert(v).index not in ear_v}
    closed = set(grown)
    for _ in range(4):
        closed -= {v for v in closed if any(e.other_vert(v) not in closed for e in v.link_edges)}
    keep |= closed
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if v not in keep], context="VERTS")
    bmesh.ops.remove_doubles(bm, verts=bm.verts[:], dist=1e-5)
    for lay in list(bm.loops.layers.uv.values()):
        bm.loops.layers.uv.remove(lay)
    bm.verts.ensure_lookup_table(); bm.normal_update()
    dist = edge_dist(bm)
    for v in bm.verts:
        nn = v.normal.copy()
        if nn.dot(v.co - O) < 0:
            nn.negate()
        g = to_g(v.co)
        t = (.006 + (.014 + lift) * smooth(-.02 * R, .45 * R, over(v.co)) ** .7 + .06 * math.exp(-(g / (.45 * R)) ** 2)) * R
        v.co += nn * t
    for _ in range(4):
        bmesh.ops.smooth_vert(bm, verts=[v for v in bm.verts if dist[v.index] > 0], factor=.5, use_axis_x=True, use_axis_y=True, use_axis_z=True)
    push_out(bm, .02 * R)
    bm.verts.ensure_lookup_table()
    px = O.x if px is None else px   # (the parting: the middle, or to a side)
    UVV = {}
    for v in bm.verts:   # (the flow's distance: on to the gathering; out from the parting over the top in front)
        rel = v.co - O
        top = smooth(.1 * R, .7 * R, rel.z) * smooth(.4 * R, -.6 * R, rel.y)
        UVV[v.index] = (0., -to_g(v.co) + part * top * abs(v.co.x - px))
    # (whole over the hairline, only the locks' tips at it: the line drawn by the alpha, smooth)
    fade = {v.index: smooth(-.015 * R, .015 * R, over(v.co)) for v in bm.verts}   # (its line: crisp, where the field crosses it)
    m = bpy.data.meshes.new("hair_" + name); bm.to_mesh(m)
    solid = bm.copy()
    bmesh.ops.delete(solid, geom=[f for f in solid.faces if min(fade[v.index] for v in f.verts) < .99], context="FACES")
    mi = bpy.data.meshes.new(name + "_solid"); solid.to_mesh(mi); solid.free(); bm.free()
    inner = bpy.data.objects.new(name + "_solid", mi); sc.collection.objects.link(inner)
    ob = bpy.data.objects.new("hair_" + name, m); sc.collection.objects.link(ob)
    uvl = m.uv_layers.new(name="UVMap")
    for poly in m.polygons:
        poly.use_smooth = True
    _beard_locks(ob, m, UVV, fade, set(), name=name, k=1., lw=(.045, .07), ll=(.8, 1.2), rmin=.07, relief=.02, alpha=(.575, .15, 10))
    return ob, inner


def strands_mat(name, seed):
    """a lock's own hairs along it (a braid's locks, a tail, a bun): fine strands, their light"""
    tile = strands_tile(256, 512, 150, 1.5, 3., seed, False)
    cl = strands_tile(128, 256, 10, 8, 14, seed + 1, True)
    cl2 = np.kron(cl, np.ones((2, 2), np.float32))
    lum = (.3 + .7 * np.clip(tile * .7 + .3, 0, 1)) * np.clip(.75 + .35 * cl2, 0, 1.1)
    img = np.zeros((512, 256, 3), np.float32); img[...] = np.clip(lum, 0, 1)[..., None] * COL[None, None, :]
    mat, _ = material(name, save(name, img, False), False, .55)
    normal_map(mat, tile * .5 + cl2 * .5, name + "_normal")
    return mat


def tie_mat():
    """the bands: dark leather, its own colour (the editor leaves it as it is)"""
    m = bpy.data.materials.new("hair_tie"); m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (.09, .05, .03, 1); b.inputs["Roughness"].default_value = .7
    return m


def locks_obj(name, build, seed):
    """an object of tubes (braids, tails, buns) built by build(bm, uvl): the hair's strands, the bands' leather"""
    bm = bmesh.new(); uvl = bm.loops.layers.uv.new("UVMap")
    build(bm, uvl)
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces[:])
    mm = bpy.data.meshes.new(name); bm.to_mesh(mm); bm.free()
    ob = bpy.data.objects.new(name, mm); sc.collection.objects.link(ob)
    for poly in mm.polygons:
        poly.use_smooth = True
    mm.materials.append(strands_mat(name, seed)); mm.materials.append(tie_mat())
    return ob


def wisps(n=6, L=1.4, z0=.3, z1=.02):
    """loose locks by the face: from the temples down past the cheeks, thin twisted strands waving a little"""
    def build(bm, uvl):
        for sd in (1, -1):
            for k in range(n):
                th = sd * math.radians(55 + 30 * k / max(1, n - 1)); z = z0 + (z1 - z0) * k / max(1, n - 1)
                p, nn = scalp_at(th, z, .02 * R)
                pts = drape(p, (nn * .5 - UP).normalized(), L * R * (.75 + .45 * rnd.random()), .03 * R, n=16, front=.2, iters=80)
                ph = rnd.random() * 6.28; amp = (.04 + .04 * rnd.random()) * R
                m_ = len(pts)
                pts = [q + (X * (sd * math.sin(ph + i * .9)) + FRONT * (.5 * math.cos(ph + i * .9))) * amp * min(1., 2.5 * i / m_) for i, q in enumerate(pts)]
                rr = [(.028 * R) * (1 - .8 * (i / (m_ - 1)) ** 1.5) for i in range(m_)]
                tube_e(bm, uvl, pts, rr, [x * .7 for x in rr], [X] * m_, M=6, vs=.8 * R, u_k=.3)
    return locks_obj("hair_wisps", build, 57)

def ear_root(sd, up=0., back=.15):
    """a point on the hair behind an ear (sd: 1 its left): just over the hairline there, up more (x R)"""
    th = sd * math.radians(102 + 60 * back)
    return scalp_at(th, zmin_at(th) / R + .08 + up)


GATHERED = {   # the gathered styles: the base's gatherings, then what is built on it
    "braids": "two braids from behind the ears, down over the chest",
    "side_braid": "one braid over the left shoulder",
    "crown_braid": "a braid round the head",
    "braid_bun": "a braid round the head, a braided bun on top",
    "low_bun": "a braided bun at the nape, loose locks by the face",
    "low_tails": "two short tails behind the ears, loose locks by the face",
    "ponytail": "a low ponytail at the nape",
}


def build_gathered(st):
    Lh = float(prm.get("length", .2)) * H
    w = .3 * R   # (a braid's half width: a third of the face's)
    objs = []
    if st in ("braids", "side_braid"):
        sides = (1, -1) if st == "braids" else (1,)
        roots = [ear_root(sd, 0., .45) for sd in sides]   # (behind the ears, under them: not over the ear's root)
        base, solid = sleek_base([r[0] for r in roots])

        def build(bm, uvl):
            for (r, nn), sd in zip(roots, sides):
                d0 = (nn * .4 + FRONT * 1.1 - UP * .6 + X * (sd * .1)).normalized()   # (forward and down: over the shoulder's front)
                pts = drape(r + nn * (.6 * w), d0, Lh, 1.05 * w, front=1.)
                braid(bm, uvl, pts, w * (1.15 if st == "side_braid" else 1.), tassel=.32 * Lh)
        objs.append(locks_obj("hair_braids", build, 51))
    elif st in ("crown_braid", "braid_bun"):
        wc = (.27 if st == "crown_braid" else .22) * R   # (the crown's half width: thick, as the reference's)
        zf = zmin_at(0.) / R + (.5 if st == "crown_braid" else .3)   # (behind the hairline: the hair combed up into it)
        loop, nrm = crown_loop(zf, .38 if st == "crown_braid" else .42, -.12 if st == "crown_braid" else .05, .04 * R + .8 * wc)
        gath = loop[::4]
        top = None
        if st == "braid_bun":
            h = cast(O, Vector((0, .3, 1)).normalized(), tree=bvh)   # (on the top of the head, a little back)
            top = h[0] if h else O + UP * R
            tn = (top - O).normalized()
            gath = gath + [top]
        base, solid = sleek_base(gath, part=.5)

        def build(bm, uvl):
            braid(bm, uvl, loop, wc, closed=True, outs=nrm)
            if top is not None:
                braid(bm, uvl, coil(top, tn, .5 * R, 2.6, .45, .04 * R + .7 * wc), wc, tassel=0., tie=False)   # (a round bun, not a tower)
        objs.append(locks_obj("hair_braids", build, 52))
    elif st == "low_bun":
        c, nn = scalp_at(math.pi, -.55, 0.)
        base, solid = sleek_base([c])

        def build(bm, uvl):
            braid(bm, uvl, coil(c, nn, .48 * R, 2.1, .9, .5 * w), w * .9, tassel=0., tie=False)
        objs.append(locks_obj("hair_braids", build, 53))
        objs.append(wisps())
    elif st in ("low_tails", "ponytail"):
        if st == "ponytail":
            roots = [scalp_at(math.pi, -.45, 0.)]
        else:
            roots = [ear_root(sd, .25, .7) for sd in (1, -1)]
        base, solid = sleek_base([r[0] for r in roots])
        rp = (.3 if st == "ponytail" else .2) * R

        def build(bm, uvl):
            for r, nn in roots:
                d0 = (nn - UP * .5).normalized()
                pts = drape(r + nn * (.4 * rp), d0, Lh * (1. if st == "ponytail" else .45), rp, n=20, front=0. if st == "ponytail" else -.3)
                m_ = len(pts)
                rr = [rp * ((.75 if i < 2 else 1.) * (1 - (i / (m_ - 1)) ** 2.4) + .03) for i in range(m_)]
                tube_e(bm, uvl, pts, rr, rr, [X] * m_, M=14, vs=1.2 * R, u_k=1.)
                t0 = (pts[2] - pts[0]).normalized()
                q = [pts[0] + t0 * (.15 * rp + .3 * rp * i / 4) for i in range(5)]   # (its band)
                tube_e(bm, uvl, q, [.85 * rp] * 5, [.85 * rp] * 5, [X] * 5, M=14, mat=1)
        objs.append(locks_obj("hair_tails", build, 54))
        if st == "low_tails":
            objs.append(wisps())
    else:
        fail(_t("ag.unknown_piece", st))
    return [base] + objs, solid


def temple_braids(bm, uvl, w, out, a1=180., z0=.38, z1=.08):
    """braids from each temple back along the head's side over the ear to the back (half up: over the hair)"""
    for sd in (1, -1):
        pts, nrm = [], []
        for i in range(25):
            f = i / 24
            q, nn = scalp_at(sd * math.radians(42 + (a1 - 42) * f), z0 + (z1 - z0) * f, out)
            pts.append(q); nrm.append(nn)
        braid(bm, uvl, pts, w, tassel=0., tie=a1 < 179., outs=nrm)


# ---------------------------------------------------------------- brows and lashes: the face's own hair
# Both move with the face: they carry its shape keys by the same names (a brow the skin's under it; a lash its lid's -
# the eyelid shell's turn, or the skin's margin under its root), so the editor, lip sync, the emotions and Godot (which
# drive blend shapes by name on every mesh of the character) move them with it. Weighted to the head; they hide nothing.
from mathutils.interpolate import poly_3d_calc   # noqa: E402

FACE_HAIR = ("brows", "lashes")
EYE_C = {sd: W @ bone(k).head_local for sd, k in (("L", "eye_L"), ("R", "eye_R")) if bone(k)}


def eye_ball(sd):
    """an eye's centre (its bone's head: the ball's centre) and its ball's radius (its mesh; else a share of the head's)"""
    c = EYE_C.get(sd)
    ob = bpy.data.objects.get(f"Eye_{sd}")
    if ob is not None and ob.type == "MESH" and len(ob.data.vertices):
        vs = [ob.matrix_world @ v.co for v in ob.data.vertices]
        if c is None:
            c = sum(vs, Vector()) / len(vs)
        return c, .5 * (max(v.x for v in vs) - min(v.x for v in vs))
    return c, .2 * R


def lid_ang(c, p):   # (a point's elevation about the ball's centre in its side plane: as the eyelid shells turn)
    return math.atan2(p.z - c.z, c.y - p.y)


def lid_turn(c, p, d):   # (p turned down by d about the ball's lateral axis: the shells' blink)
    q = p - c
    rho, ph = math.hypot(q.y, q.z), math.atan2(q.z, -q.y) - d
    return c + Vector((q.x, -rho * math.cos(ph), rho * math.sin(ph)))


def wrap(a):
    return (a + math.pi) % (2 * math.pi) - math.pi


def along_x(pts, f, x):   # (f of a line's points, between them by x)
    sp_ = sorted(pts, key=lambda p: p.x)
    if x <= sp_[0].x:
        return f(sp_[0])
    for a_, b_ in zip(sp_, sp_[1:]):
        if x <= b_.x:
            t = (x - a_.x) / ((b_.x - a_.x) or 1e-9)
            return f(a_) * (1 - t) + f(b_) * t
    return f(sp_[-1])


_OPEN = {}


def shells_tree(sd):
    """the eyelid shells of an eye (EyeLid_<side>, built with the eyes: blender_eye_insert.lid_shells) as a tree to cast
    rays at, or None"""
    ob = bpy.data.objects.get(f"EyeLid_{sd}")
    if ob is None or ob.type != "MESH" or len(ob.data.vertices) < 20:
        return None
    M = ob.matrix_world
    return BVHTree.FromPolygons([M @ v.co for v in ob.data.vertices], [list(f.vertices) for f in ob.data.polygons])


def eye_opening(sd):
    """the eye's opening as one sees it, found from the ball's centre: a ray out through it meets nothing, one into a lid
    does - the skin, or an eyelid shell (where the character has them: the skin's cut is wider, hidden under them; where
    the skin hangs lower than a shell's edge it is the lid) - near, within a few radii. Per column round the ball (its
    azimuth) the upper and the lower lid's margin - the first ray up, down from an open one meeting a lid - from the
    inner corner (by the nose) to the outer.
    -> dict(c, r, up, lo: [points on the margins, inner to outer], inner, outer, top, shells) or None (no eye cut)"""
    if sd in _OPEN:
        return _OPEN[sd]
    c, r = eye_ball(sd)
    _OPEN[sd] = None
    if c is None:
        return None
    shells = shells_tree(sd)
    r0, reach = .97 * r, 2.6 * r   # (from just inside the ball: skin tucked in under it is not a lid)

    def ray(th, ph):
        d = Vector((math.sin(th) * math.cos(ph), -math.cos(th) * math.cos(ph), math.sin(ph)))
        hs = [h for h in (full.ray_cast(c + d * r0, d, reach - r0), shells.ray_cast(c + d * r0, d, reach - r0) if shells else (None,) * 4)
              if h[0] is not None]
        return min(hs, key=lambda h: h[3])[0] if hs else None

    def edge(th, ph0, sgn):   # (from an open ray up or down to the first meeting the skin: its place there)
        a, b, p = ph0, None, ph0
        while abs(p) < 1.45:
            p += sgn * .06
            if ray(th, p) is not None:
                b = p
                break
            a = p
        if b is None:
            return None
        for _ in range(9):
            m_ = .5 * (a + b)
            if ray(th, m_) is not None:
                b = m_
            else:
                a = m_
        return ray(th, b)

    NC = 49
    cols = []
    for i in range(NC):
        th = math.radians(-78 + 156 * i / (NC - 1))
        ph0 = next((p for p in (0., .08, -.08, .16, -.16, .26, -.26, .36, -.36) if ray(th, p) is None), None)
        u_, l_ = (edge(th, ph0, 1), edge(th, ph0, -1)) if ph0 is not None else (None, None)
        ok = u_ is not None and l_ is not None and (u_ - c).length < 2.3 * r and (l_ - c).length < 2.3 * r
        cols.append((u_, l_) if ok else None)
    near = [i for i in range(NC) if cols[i] is not None]
    if not near:
        return None
    mid = min(near, key=lambda i: abs(i - NC // 2))   # (the run of open columns round the front: the opening)
    i0 = i1 = mid
    while i0 > 0 and cols[i0 - 1] is not None:
        i0 -= 1
    while i1 < NC - 1 and cols[i1 + 1] is not None:
        i1 += 1
    if i1 - i0 < 4:
        return None
    up = [cols[i][0] for i in range(i0, i1 + 1)]
    lo = [cols[i][1] for i in range(i0, i1 + 1)]
    if abs(up[0].x - O.x) > abs(up[-1].x - O.x):   # (the inner corner first: nearer the face's middle)
        up, lo = up[::-1], lo[::-1]
    ends = ((up[0] + lo[0]) / 2, (up[-1] + lo[-1]) / 2)   # (where it closes)

    def smoothed(pts):   # (the rays' steps off the mesh's faces smoothed out, back on the skin)
        for _ in range(3):
            pts = [pts[0]] + [pts[i] * .5 + (pts[i - 1] + pts[i + 1]) * .25 for i in range(1, len(pts) - 1)] + [pts[-1]]
        return pts
    up, lo = smoothed([ends[0]] + up + [ends[1]]), smoothed([ends[0]] + lo + [ends[1]])
    _OPEN[sd] = dict(c=c, r=r, up=up, lo=lo, inner=ends[0], outer=ends[1], top=max(up, key=lambda p: p.z), shells=shells is not None)
    return _OPEN[sd]


_SKEYS = []


def skin_keys():
    """the skin's shape keys as moves in the world (numpy: key, vertex, xyz) and their names (the face's: the brows,
    the blinks, the mouth...)"""
    if not _SKEYS:
        names, D = [], None
        sk = me.shape_keys
        if sk is not None and len(sk.key_blocks) > 1:
            n = len(me.vertices)
            base = np.empty(n * 3, np.float32)
            sk.key_blocks[0].data.foreach_get("co", base)
            M3 = np.array(skin.matrix_world.to_3x3(), np.float32)
            arr = []
            for kb in sk.key_blocks[1:]:
                a_ = np.empty(n * 3, np.float32)
                kb.data.foreach_get("co", a_)
                d_ = (a_ - base).reshape(-1, 3) @ M3.T
                if np.abs(d_).max() > 1e-7:
                    names.append(kb.name)
                    arr.append(d_)
            D = np.stack(arr) if arr else None
        _SKEYS.extend([names, D])
    return _SKEYS


def skin_moves(p):
    """each key's move of the skin at a point on (or by) it: its nearest face's, between that face's corners -> (key, xyz)"""
    names, D = skin_keys()
    if D is None:
        return None
    loc, nrm, fi, dist = full.find_nearest(p)
    if loc is None:
        return None
    vs = P[fi]
    w = poly_3d_calc([V[i] for i in vs], loc)
    return sum(D[:, i, :] * float(wt) for i, wt in zip(vs, w))


def strokes_img(TW, TH, strokes, ss=2):
    """fine hairs drawn as soft lines (supersampled): each (its points in pixels - x, y up from the bottom row -, its half
    widths along it, its alpha along it, its light) -> alpha, light (rows bottom up)"""
    A = np.zeros((TH * ss, TW * ss), np.float32)
    Lm = np.zeros((TH * ss, TW * ss), np.float32)
    xs, ys, rs_, als, lus = [], [], [], [], []
    for pts, wd, al, lu in strokes:
        pts = np.asarray(pts, np.float32) * ss
        seg = np.hypot(*np.diff(pts, axis=0).T)
        cum = np.concatenate([[0.], np.cumsum(seg)])
        tot = float(cum[-1])
        if tot < 1e-3:
            continue
        n = max(2, int(tot * 1.5))
        s = np.linspace(0., tot, n)
        f = s / tot
        xs.append(np.interp(s, cum, pts[:, 0]))
        ys.append(np.interp(s, cum, pts[:, 1]))
        rs_.append(np.interp(f, np.linspace(0., 1., len(wd)), np.asarray(wd, np.float32)) * ss)
        als.append(np.interp(f, np.linspace(0., 1., len(al)), np.asarray(al, np.float32)))
        lus.append(np.full(n, lu, np.float32))
    if not xs:
        return np.zeros((TH, TW), np.float32), np.zeros((TH, TW), np.float32)
    x, y, rr = np.concatenate(xs), np.concatenate(ys), np.concatenate(rs_)
    a, lu = np.concatenate(als), np.concatenate(lus)
    xi0, yi0 = np.round(x).astype(int), np.round(y).astype(int)
    K = int(np.ceil(rr.max())) + 1
    H_, W_ = A.shape
    for dy in range(-K, K + 1):
        for dx in range(-K, K + 1):
            xi, yi = xi0 + dx, yi0 + dy
            cov = np.clip(rr + .5 - np.hypot(xi - x, yi - y), 0., 1.) * a
            ok = (cov > 0) & (xi >= 0) & (xi < W_) & (yi >= 0) & (yi < H_)
            if ok.any():
                np.maximum.at(A, (yi[ok], xi[ok]), cov[ok])
                np.maximum.at(Lm, (yi[ok], xi[ok]), np.where(cov > .3, lu, 0.)[ok])
    return A.reshape(TH, ss, TW, ss).mean(axis=(1, 3)), Lm.reshape(TH, ss, TW, ss).max(axis=(1, 3))


def blend_mat(name, im, rough=.55):
    """the image's colour, its alpha blended (glTF's BLEND): fine hairs - cut by the alpha they went to nothing in the
    distance (the mip-maps' alpha under the cut)"""
    m, t = material(name, im, False, rough)
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    m.node_tree.links.new(t.outputs["Alpha"], b.inputs["Alpha"])
    try:   # (matt: a glossy band of fine hairs caught the light - pale brows)
        b.inputs["Specular IOR Level"].default_value = .08
    except KeyError:
        pass
    for attr, val in (("surface_render_method", "BLENDED"), ("blend_method", "BLEND")):
        if hasattr(m, attr):
            try:
                setattr(m, attr, val)
            except TypeError:
                pass
    return m


def face_obj(name, verts, faces, uvs, mat, keys):
    """a mesh of the face's hair: its vertices (world), quads, a uv a vertex, its material, its shape keys {name:
    positions} (at 0: rest)"""
    m_ = bpy.data.meshes.new(name)
    m_.from_pydata([tuple(v) for v in verts], [], faces)
    uvl = m_.uv_layers.new(name="UVMap")
    for poly in m_.polygons:
        poly.use_smooth = True
        for li in poly.loop_indices:
            uvl.data[li].uv = uvs[m_.loops[li].vertex_index]
    m_.materials.append(mat)
    ob = bpy.data.objects.new(name, m_)
    sc.collection.objects.link(ob)
    if keys:
        ob.shape_key_add(name="Basis")
        for kname, pos in keys.items():
            kb = ob.shape_key_add(name=kname, from_mix=False)
            for i, p in enumerate(pos):
                kb.data[i].co = p
            kb.value = 0.
    return ob


# -------- lashes: a ribbon along each lid's margin, the lashes in its texture
LASHES = {   # L: the upper ones' length (x the ball's radius), n: lashes an eye, layers (ribbons), lower: the lower ones'
    # share of that length (0: none), curl: how far they turn up (the lower ones down), w: their thickness
    "natural": dict(L=.8, n=210, layers=1, lower=.45, curl=.6, w=1.2),
    "short": dict(L=.48, n=170, layers=1, lower=0., curl=.4, w=1.1),
    "long": dict(L=1.0, n=240, layers=2, lower=.5, curl=.75, w=1.3),
    "thick": dict(L=.82, n=300, layers=2, lower=.55, curl=.6, w=1.6)}


def lash_atlas(st):
    """four rows of lashes (upper A, B; lower A, B), each from the root (its bottom) to the tips: tapered, a little
    bent, in clumps meeting at their tips, leaning to the outer corner (u: the inner corner 0, the outer 1)"""
    TW, RH = 1024, 128
    rs = random.Random(int(prm.get("seed", 1)) * 13 + 5)
    sp = LASHES[st]
    strokes = []
    for row in range(4):
        lower = row >= 2
        n, k, y0 = int(sp["n"] * (.6 if lower else 1.)), 0, row * RH + 3
        while k < n:
            m = min(n - k, rs.choice((2, 3, 3, 4)))   # (a clump)
            cx = rs.random() * TW
            tipx = cx + rs.uniform(-6, 6) + 16 * cx / TW
            Lc = (RH - 8) * rs.uniform(.75, 1.)
            for _ in range(m):
                rx, L_, tx = cx + rs.uniform(-6, 6), Lc * rs.uniform(.8, 1.), tipx + rs.uniform(-2.5, 2.5)
                t = np.linspace(0, 1, 9)
                pts = np.stack([rx + (tx - rx) * t ** 1.5, y0 + L_ * t], 1)
                strokes.append((pts, sp["w"] * np.array([1.3, 1.1, .7, .22]) * (.85 if lower else 1.), [1., .95, .8, .45], rs.uniform(.6, 1.)))
            k += m
    A, Lm = strokes_img(TW, 4 * RH, strokes)
    img = np.zeros((4 * RH, TW, 4), np.float32)
    img[..., 3] = A
    img[..., :3] = ((.35 + .45 * Lm)[..., None] * COL[None, None, :])
    return img


def shell_turns(sd, c, r):
    """the eyelid shells' turn in each of their keys (radians, + down): the upper's, the lower's (EyeLid_<side>, built
    with the eyes: blender_eye_insert.lid_shells) - or None"""
    ob = bpy.data.objects.get(f"EyeLid_{sd}")
    if ob is None or ob.type != "MESH" or not ob.data.shape_keys:
        return None
    kb = ob.data.shape_keys.key_blocks
    M = ob.matrix_world
    bas = [M @ v.co for v in kb[0].data]
    out = {}
    for k in kb[1:]:
        ks = [M @ v.co for v in k.data]
        du = sorted(wrap(lid_ang(c, bas[i]) - lid_ang(c, ks[i])) for i in range(len(bas)) if bas[i].z > c.z + .1 * r)
        dl = sorted(wrap(lid_ang(c, bas[i]) - lid_ang(c, ks[i])) for i in range(len(bas)) if bas[i].z < c.z - .1 * r)
        out[k.name] = (du[len(du) // 2] if du else 0., dl[len(dl) // 2] if dl else 0.)
    return out


def build_lashes(st):
    sp = LASHES[st]
    Lk = max(.2, float(prm.get("length", 1.)))   # (the slider: x the style's length)
    verts, faces, uvs, cols = [], [], [], []   # (cols: side, lid, its root, its vertices)
    NU, NV = 26, 6
    found = {}
    for sd in ("L", "R"):
        op = eye_opening(sd)
        if op is None:
            continue
        found[sd] = op
        c, r = op["c"], op["r"]
        lat = X * (1 if op["outer"].x > op["inner"].x else -1)   # (out to the outer corner)
        for lid, marg, row0, Lf in (("up", op["up"], 0, 1.), ("lo", op["lo"], 2, sp["lower"])):
            if Lf <= 0:
                continue
            arc = [0.]
            for a_, b_ in zip(marg, marg[1:]):
                arc.append(arc[-1] + (b_ - a_).length)

            def at(s):   # (the margin's point at a share of its length)
                t = s * arc[-1]
                for i in range(len(arc) - 1):
                    if arc[i + 1] >= t:
                        return marg[i].lerp(marg[i + 1], (t - arc[i]) / max(arc[i + 1] - arc[i], 1e-9))
                return marg[-1].copy()
            s0, s1 = (.05, .97) if lid == "up" else (.2, .93)
            sgn = 1 if lid == "up" else -1
            for layer in range(sp["layers"]):
                base = len(verts)
                for i in range(NU + 1):
                    s = s0 + (s1 - s0) * i / NU
                    m = at(s)
                    o = (m - c).normalized()
                    prof = ((.35 + .65 * smooth(0., .6, s)) * (1 - .3 * smooth(.85, 1., s))) if lid == "up" else (.5 + .5 * smooth(.2, .7, s))
                    Lc = sp["L"] * Lk * Lf * r * prof * (1 - .12 * layer)
                    # out of the lid forward - over the eye a little, as seen from the front -, curling up (the lower
                    # ones down), the outer ones leaning out
                    d0 = (o * .3 + FRONT * 1. - UP * (.18 * sgn) + lat * (.35 * s * s)).normalized()
                    up_ = UP * sgn
                    up_ = (up_ - d0 * up_.dot(d0)).normalized()
                    root = m + o * ((.02 - .03 * layer) * r)
                    curl = sp["curl"] * (1 + .25 * layer) * (1 if lid == "up" else .5)
                    col = []
                    for j in range(NV):
                        t = j / (NV - 1)
                        col.append(len(verts))
                        verts.append(root + (d0 * t + up_ * (curl * t * t)) * Lc)
                        uvs.append((.02 + .96 * i / NU, (row0 + layer + .03 + .94 * t) / 4))
                    cols.append((sd, lid, m, col))
                for i in range(NU):
                    for j in range(NV - 1):
                        a = base + i * NV + j
                        faces.append((a, a + NV, a + NV + 1, a + 1))
    if not verts:
        fail(_t("ag.lashes_no_eyes"))
    # the keys: each column turned with its lid (about the ball's lateral axis), as far as its root goes
    keys = {}
    for sd, op in found.items():
        c, r = op["c"], op["r"]
        sc_ = [cl for cl in cols if cl[0] == sd]
        turns = shell_turns(sd, c, r)
        moves = {}   # key -> [(turn, shift)] a column
        if turns:   # (the shells: the upper lid down to the lower's margin, as the shell closes over it; the lower as its shell)
            blink = next((v for k, v in turns.items() if k.startswith("eyeBlink")), None)
            rise = max(0., -blink[1]) if blink else 0.
            ang = lambda p: lid_ang(c, p)   # noqa: E731
            for kname, (tu, tl) in turns.items():
                ks = []
                for _, lid, m, _ in sc_:
                    if lid == "up":
                        need = max(0., along_x(op["up"], ang, m.x) - along_x(op["lo"], ang, m.x) - rise)
                        ks.append((need * (tu / blink[0]) if blink and abs(blink[0]) > 1e-6 else 0., Vector()))
                    else:
                        ks.append((tl, Vector()))
                moves[kname] = ks
        else:   # (no shells: the skin's own margin under each root moves; the column turned as far and carried on)
            names, D = skin_keys()
            mv = [skin_moves(m) for _, _, m, _ in sc_]
            for ki, kname in enumerate(names):
                if not any(x is not None and np.abs(x[ki]).max() > 1e-3 * r for x in mv):
                    continue
                ks = []
                for (_, _, m, _), x in zip(sc_, mv):
                    m2 = m + Vector(x[ki]) if x is not None else m
                    d = wrap(lid_ang(c, m) - lid_ang(c, m2))
                    ks.append((d, m2 - lid_turn(c, m, d)))
                moves[kname] = ks
        for kname, ks in moves.items():
            pos = keys.setdefault(kname, [v.copy() for v in verts])
            for (_, _, m, col), (d, sh) in zip(sc_, ks):
                for vi in col:
                    pos[vi] = lid_turn(c, verts[vi], d) + sh
    im = save("lashes", lash_atlas(st), True)
    ob = face_obj("lashes", verts, faces, uvs, blend_mat("lashes", im, .75), keys)
    print("lashes", len(cols), "columns, keys", sorted(keys), flush=True)
    return [ob], ob


# -------- brows: a band along each brow on the skin, the brow (its outline, its hairs) in its texture
BROWS = {   # the outline's nodes in the eye's measures - X: out from the ball's centre (to the outer corner), Z: up from
    # it, in the ball's radii (a human's: the brow from over the inner corner to past the outer, its lower edge 1.5-2
    # radii up) -; n: hairs a brow, hl: their length (x the brow's width there), fill: its body's tint under the hairs,
    # gap: off the skin (x the ball's radius), wild: unruly hairs
    "natural": dict(nodes=dict(head_top=(-1.5, 2.0), arch_top=(.55, 2.42), tail=(1.95, 1.72), arch_bot=(.5, 1.84), head_bot=(-1.45, 1.42)),
                    n=1500, hl=.36, fill=.34, gap=.05, wild=0.),
    "thin": dict(nodes=dict(head_top=(-1.4, 1.86), arch_top=(.6, 2.4), tail=(1.9, 1.78), arch_bot=(.6, 2.1), head_bot=(-1.38, 1.56)),
                 n=950, hl=.5, fill=.28, gap=.04, wild=0.),
    "arched": dict(nodes=dict(head_top=(-1.45, 1.9), arch_top=(.4, 2.62), tail=(1.9, 1.6), arch_bot=(.38, 2.02), head_bot=(-1.42, 1.4)),
                   n=1450, hl=.38, fill=.34, gap=.05, wild=0.),
    "straight": dict(nodes=dict(head_top=(-1.5, 2.02), arch_top=(.7, 2.2), tail=(1.95, 1.84), arch_bot=(.7, 1.62), head_bot=(-1.45, 1.46)),
                     n=1500, hl=.36, fill=.34, gap=.05, wild=0.),
    "thick": dict(nodes=dict(head_top=(-1.55, 2.1), arch_top=(.55, 2.56), tail=(2.0, 1.7), arch_bot=(.5, 1.66), head_bot=(-1.5, 1.3)),
                  n=2100, hl=.34, fill=.42, gap=.06, wild=.15),
    "bushy": dict(nodes=dict(head_top=(-1.6, 2.2), arch_top=(.55, 2.72), tail=(2.05, 1.66), arch_bot=(.5, 1.6), head_bot=(-1.55, 1.24)),
                  n=1900, hl=.5, fill=.36, gap=.12, wild=1.)}
BROW_LOOP = ["head_top", "arch_top", "tail", "arch_bot", "head_bot"]
BROWS_TPL_FILE = HERE / "brows_template.json"


def brow_frame(sd):
    """an eye's measures for its brow: the ball's centre, its radius, which way is out (+1: +x)"""
    c, r = eye_ball(sd)
    return None if c is None else (c, r, 1 if c.x > O.x else -1)


def on_face(x, z):   # (the skin's point there seen from the front)
    h = cast(Vector((x, O.y - 3 * R, z)), -FRONT, 6 * R, tree=bvh)
    return h[0] if h else Vector((x, O.y - R, z))


def brow_node(sd, X_, Z_):
    c, r, s_ = brow_frame(sd)
    return on_face(c.x + s_ * X_ * r, c.z + Z_ * r)


def ridge_dz(sd, X_, Z_):
    """how far up from Z the brow's ridge is at X (the face's most forward there, 1-3 radii over the eye; ball radii) -
    a brow lies on it: under it, on a deep-set eye, the skin folded over it frowning"""
    c, r, s_ = brow_frame(sd)
    x, best = c.x + s_ * X_ * r, None
    for k in range(45):
        z = c.z + (1. + 2.2 * k / 44) * r
        h = cast(Vector((x, O.y - 3 * R, z)), -FRONT, 6 * R, tree=bvh)
        if h and (best is None or h[0].y < best[0] - 1e-4 * r):
            best = (h[0].y, z)
    return (best[1] - c.z) / r - Z_ if best else 0.


def brows_template(st):
    """this style's brow nodes on this face fitted by hand once (the job's «template», the user's; over the toolkit's)"""
    srcs = []
    for f in (job.get("template"), BROWS_TPL_FILE):
        try:
            srcs.append(json.loads(Path(f).read_text(encoding="utf-8")) if f else {})
        except (OSError, ValueError):
            srcs.append({})
    rec = next((src["brows_" + st] for src in srcs if isinstance(src.get("brows_" + st), dict)), {})
    return {f"{k}_{sd}": brow_node(sd, r_[1], r_[2]) for k, r_ in rec.items() if isinstance(r_, list) and len(r_) == 3 and r_[0] == "e"
            for sd in ("L", "R") if brow_frame(sd) is not None}


def learn_brows(st, path):
    """the brows' nodes fitted by hand kept as this style's default, in the eyes' measures (the two sides as one)"""
    pth = Path(path)
    try:
        tp = json.loads(pth.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        tp = {}
    acc = {}
    for key, p in NODES_IN.items():
        k, sd = key[:-2], key[-1:]
        fr = brow_frame(sd) if key[-2:] in ("_L", "_R") and k in BROW_LOOP else None
        if fr is None:
            continue
        c, r, s_ = fr
        acc.setdefault(k, []).append(((p.x - c.x) * s_ / r, (p.z - c.z) / r))
    rec = {k: ["e", round(sum(a for a, _ in v) / len(v), 4), round(sum(b for _, b in v) / len(v), 4)] for k, v in sorted(acc.items())}
    if not rec:
        fail(_t("ag.contour_learn_none"))
    tp["brows_" + st] = rec
    write_template(pth, tp)
    print("tmpl learnt brows", st, len(rec), flush=True)


def frac_line(pts, n):   # (n points along a line, evenly by its length)
    arc = [0.]
    for a_, b_ in zip(pts, pts[1:]):
        arc.append(arc[-1] + (b_ - a_).length)
    out = []
    for k in range(n):
        t, i = arc[-1] * k / (n - 1), 0
        while i < len(arc) - 2 and arc[i + 1] < t:
            i += 1
        out.append(pts[i].lerp(pts[i + 1], (t - arc[i]) / max(arc[i + 1] - arc[i], 1e-9)))
    return out


def skin_pt(p):   # (the skin's nearest point and its normal - out of the head: a model's faces may be wound inward)
    h = bvh.find_nearest(p)
    if h[0] is None:
        return p, -FRONT
    n_ = h[1].normalized()
    return h[0], (n_ if n_.dot(h[0] - O) >= 0 else -n_)


def outer_pt(p):   # (the skin's outer surface over p, from outside: a model's inner layers under it not taken)
    d = (p - O).normalized()
    h = bvh.ray_cast(p + d * (.4 * R), -d, .8 * R)
    if h[0] is None:
        return skin_pt(p)
    n_ = h[1].normalized()
    return h[0], (n_ if n_.dot(d) >= 0 else -n_)


def poly_mask(TW, TH, poly):
    """pixels inside a polygon (pixels' centres; rows bottom up)"""
    yy, xx = np.mgrid[0:TH, 0:TW].astype(np.float32) + .5
    ins = np.zeros((TH, TW), bool)
    for (x1, y1), (x2, y2) in zip(poly, poly[1:] + poly[:1]):
        if abs(y2 - y1) < 1e-9:
            continue
        cr = ((y1 > yy) != (y2 > yy)) & (xx < x1 + (yy - y1) * (x2 - x1) / (y2 - y1))
        ins ^= cr
    return ins


def blur(a, k):   # (a box blur k pixels each way, twice)
    for _ in range(2):
        c_ = np.cumsum(np.pad(a, ((k + 1, k), (0, 0)), mode="edge"), axis=0)
        a = (c_[2 * k + 1:] - c_[:-2 * k - 1]) / (2 * k + 1)
        c_ = np.cumsum(np.pad(a, ((0, 0), (k + 1, k)), mode="edge"), axis=1)
        a = (c_[:, 2 * k + 1:] - c_[:, :-2 * k - 1]) / (2 * k + 1)
    return a


def build_brows(st):
    sp = BROWS[st]
    vol = max(.3, float(prm.get("vol", 1.)))   # (the slider: x its width)
    given = {**brows_template(st), **NODES_IN}
    rs = random.Random(int(prm.get("seed", 1)) * 17 + 11)
    sides = []
    for sd in ("L", "R"):
        if brow_frame(sd) is None:
            continue
        nd, N_ = {}, sp["nodes"]
        # (by default each part - its head, its arch, its tail - up or down onto the brow's ridge, so far)
        lift = {}
        for part, ks in (("head", ("head_top", "head_bot")), ("arch", ("arch_top", "arch_bot")), ("tail", ("tail",))):
            X_ = sum(N_[k][0] for k in ks) / len(ks)
            lift.update({k: .7 * min(.8, max(-.4, ridge_dz(sd, X_, sum(N_[k][1] for k in ks) / len(ks)))) for k in ks})
        for k, (X_, Z_) in N_.items():
            key = f"{k}_{sd}"
            nd[k] = given[key] if key in given else brow_node(sd, X_, Z_ + lift[k])
            NODES_OUT[key] = nd[k]
        sides.append((sd, nd))
    if not sides:
        fail(_t("ag.lashes_no_eyes"))
    LOOPS_OUT[:] = [[f"{k}_{sd}" for k in BROW_LOOP] for sd, _ in sides]
    TW, M, NV = 1024, 56, 11   # (fine: on a bumpy brow ridge a coarse band went under the skin between its vertices)
    bands = []
    for sd, nd in sides:
        r = eye_ball(sd)[1]
        ring = [outer_pt(p)[0] for p in catmull_closed3([nd[k] for k in BROW_LOOP], 12)]   # (as the editor draws it)
        upper, lower = frac_line(ring[0:25], M), frac_line(ring[24:49][::-1], M)   # (head_top -> tail; head_bot -> tail)
        spine = [(a + b) / 2 for a, b in zip(upper, lower)]
        hw = [(a - b).length / 2 * vol for a, b in zip(upper, lower)]
        Ls = sum((b - a).length for a, b in zip(spine, spine[1:]))
        t0, t1 = (spine[0] - spine[1]).normalized(), (spine[-1] - spine[-2]).normalized()
        line = ([outer_pt(spine[0] + t0 * (.12 * Ls * k / 4))[0] for k in range(4, 0, -1)] + spine
                + [outer_pt(spine[-1] + t1 * (.08 * Ls * k / 4))[0] for k in range(1, 5)])   # (a margin past each end)
        hw = [hw[0]] * 4 + hw + [hw[-1] * .5] * 4
        arc = [0.]
        for a_, b_ in zip(line, line[1:]):
            arc.append(arc[-1] + (b_ - a_).length)
        Hb = 1.6 * max(hw)
        frames = []
        for k, p in enumerate(line):
            n_ = outer_pt(p)[1]
            t_ = (line[min(k + 1, len(line) - 1)] - line[max(k - 1, 0)]).normalized()
            b_ = n_.cross(t_).normalized()
            frames.append(b_ if b_.z >= 0 else -b_)
        THs = int(min(512, max(64, math.ceil(TW * 2 * Hb / arc[-1] / 8) * 8)))
        bands.append(dict(sd=sd, r=r, ring=ring, line=line, hw=hw, arc=arc, Hb=Hb, frames=frames, THs=THs, nk=len(line)))
    THa = sum(b["THs"] for b in bands)
    img = np.zeros((THa, TW, 4), np.float32)
    verts, faces, uvs = [], [], []
    y_off = 0
    for b in bands:
        line, arc, Hb, fr, THs, r = b["line"], b["arc"], b["Hb"], b["frames"], b["THs"], b["r"]
        U = [a / arc[-1] for a in arc]
        gap = (sp["gap"] + .04) * r
        base = len(verts)
        for k, p in enumerate(line):
            for j in range(NV):
                v = -1 + 2 * j / (NV - 1)
                q, n_ = outer_pt(p + fr[k] * (v * Hb))
                verts.append(q + n_ * gap)
                uvs.append((U[k], (y_off + (v + 1) / 2 * THs) / THa))
        for k in range(len(line) - 1):
            for j in range(NV - 1):
                a = base + k * NV + j
                faces.append((a, a + NV, a + NV + 1, a + 1))
        # the outline in its band's pixels: along (by the nearest point of its line), across (off it: the band's up)

        def to_px(p):
            k = min(range(len(line)), key=lambda i: (line[i] - p).length)
            return (U[k] * TW, ((p - line[k]).dot(fr[k]) * vol / Hb + 1) / 2 * THs)
        poly = [to_px(p) for p in b["ring"]]
        D = blur(poly_mask(TW, THs, poly).astype(np.float32), 2)
        yc = THs / 2
        kh, kt = 4, len(line) - 5   # (the brow's own head and tail: past the margins)

        def hw_px(x):
            k = min(range(len(line)), key=lambda i: abs(U[i] * TW - x))
            return max(1.5, b["hw"][k] / Hb * THs / 2)
        strokes, n, tries = [], 0, 0
        N = int(sp["n"] * vol ** .5)
        while n < N and tries < N * 40:
            tries += 1
            x, y = rs.random() * TW, rs.random() * THs
            if rs.random() > D[min(THs - 1, int(y)), min(TW - 1, int(x))] ** 1.5:
                continue
            n += 1
            un = min(1., max(0., (x / TW - U[kh]) / max(U[kt] - U[kh], 1e-6)))
            hwp = hw_px(x)
            rel = min(1.2, max(-1.2, (y - yc) / hwp))
            head, tail = 1 - smooth(.04, .22, un), smooth(.7, 1., un)
            # at its head up; then the lower ones up to the tail, the upper ones down to it (meeting in the middle); flat
            # at the tail
            ang = head * (76 + 8 * rel) + (1 - head) * (32 - 44 * (rel + 1) / 2) * (1 - .7 * tail)
            ang = math.radians(ang + rs.gauss(0, 5 + 18 * sp["wild"]))
            L_ = sp["hl"] * 2 * hwp * rs.uniform(.6, 1.1) * (.6 if head > .5 else 1.) * (1 + .6 * sp["wild"] * rs.random())
            d = np.array([math.cos(ang), math.sin(ang)])
            pp = np.array([-d[1], d[0]])
            t = np.linspace(0, 1, 7)[:, None]
            pts = np.array([x, y]) + d * (L_ * t) + pp * (-.18 * rel * L_ * t * t)   # (bent in to the middle)
            strokes.append((pts, np.array([.95, .75, .48, .18]) * (1 + .3 * sp["wild"]), [.95, .9, .7, .3], rs.uniform(.45, 1.)))
        Ah, Lh = strokes_img(TW, THs, strokes)
        Af = D * sp["fill"]
        A = 1 - (1 - Af) * (1 - Ah)
        lum = (Af * (1 - Ah) * .5 + Ah * (.45 + .5 * Lh)) / np.maximum(A, 1e-4)
        img[y_off:y_off + THs, :, 3] = A
        img[y_off:y_off + THs, :, :3] = lum[..., None] * COL[None, None, :]
        y_off += THs
    # the keys: the skin's under each vertex (its brows' keys, the blinks', the frowns'...)
    keys = {}
    names, Dk = skin_keys()
    if Dk is not None:
        mv = [skin_moves(p) for p in verts]
        r = max(b["r"] for b in bands)
        for ki, kname in enumerate(names):
            if any(x is not None and np.abs(x[ki]).max() > 2e-3 * r for x in mv):
                keys[kname] = [p + Vector(x[ki]) if x is not None else p.copy() for p, x in zip(verts, mv)]
    im = save("brows", img, True)
    ob = face_obj("brows", verts, faces, uvs, blend_mat("brows", im, .9), keys)
    print("brows", [b["sd"] for b in bands], "texture", TW, THa, "keys", sorted(keys), flush=True)
    return [ob], ob


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
elif job.get("piece") == "brows":   # (the brows: their outline's nodes shown in the editor, moved there by hand)
    if style not in BROWS:
        fail(_t("ag.unknown_piece", style))
    if job.get("learn"):   # (the nodes fitted by hand kept as the default: only that)
        learn_brows(style, job["learn"])
        sys.exit(0)
    obs, mask_of = build_brows(style)
elif job.get("piece") == "lashes":
    if style not in LASHES:
        fail(_t("ag.unknown_piece", style))
    obs, mask_of = build_lashes(style)
else:   # a hairstyle made here: its hairline's nodes (shown in the editor, moved there by hand)
    HAIR_ANG = {"front": 0, "temple_L": 40, "ear_L": 90, "back_L": 135, "nape": 180, "back_R": -135, "ear_R": -90, "temple_R": -40}
    LOOP[:] = ["front", "temple_L", "ear_L", "back_L", "nape", "back_R", "ear_R", "temple_R"]
    if job.get("learn"):   # (the nodes fitted by hand kept as the default: only that)
        learn_hair(style, job["learn"], HAIR_ANG)
        sys.exit(0)
    GIVEN = {**hair_template(style), **NODES_IN}   # (by hand; or the default fitted by hand once)
    if any(k in GIVEN for k in LOOP):
        HL = sorted(((math.atan2((GIVEN[k] - O).x, -(GIVEN[k] - O).y), (GIVEN[k] - O).z) if k in GIVEN
                     else (math.radians(a) if a < 180 else math.pi, zmin_default(math.radians(a))) for k, a in HAIR_ANG.items()))
    for k, a in HAIR_ANG.items():
        if k in GIVEN:
            NODES_OUT[k] = GIVEN[k]
            continue
        th = math.radians(a); zz = O.z + zmin_at(th)
        d = Vector((math.sin(th), -math.cos(th), 0))
        h = cast(Vector((O.x, O.y, zz)) + d * (3 * R), -d, 3 * R, tree=bvh)
        NODES_OUT[k] = h[0] if h else Vector((O.x, O.y, zz)) + d * R
if job.get("piece") in ("beard", *FACE_HAIR) or style.startswith("wig"):
    pass
elif style in ("long", "bob", "wavy", "half_up", "wavy_short", "shaggy", "warrior", "top_knot"):
    Lh = float(prm.get("length", .26 if style != "bob" else .14)) * H * (2.0 if style == "bob" else 1.2)
    obs, mask_of = build_cards(Lh, float(prm.get("part", .3 if style == "bob" else 0.)), (E.z - 1.25 * R) if style == "bob" else None,
                               wave={"wavy": 1., "half_up": 1., "wavy_short": 1.1, "warrior": .9, "top_knot": .8, "shaggy": .4}.get(style, 0.),
                               messy=1. if style == "shaggy" else 0., swept=1. if style in ("wavy_short", "warrior", "top_knot") else 0.,
                               narrow=.65 if style in ("wavy_short", "warrior", "top_knot", "shaggy") else 1.)
    if style == "warrior":   # (thin braids from the temples back over the ears)
        obs.append(locks_obj("hair_braids", lambda bm, uvl: temple_braids(bm, uvl, .07 * R, .44 * R, 150., .3, .05), 58))
    if style == "top_knot":   # (the top's hair tied at the crown in a short tail)
        def knot(bm, uvl):
            h = cast(O, Vector((0, .45, 1)).normalized(), tree=bvh)   # (on the crown)
            c = h[0] if h else O + UP * R
            nn = (c - O).normalized()
            tube_e(bm, uvl, [c + nn * (.18 * R + .06 * R * i) for i in range(4)], [.2 * R] * 4, [.2 * R] * 4, [X] * 4, M=14, mat=1)
            braid(bm, uvl, coil(c, nn, .36 * R, 2., 1., .42 * R), .15 * R, tassel=0., tie=False)
        obs.append(locks_obj("hair_knot", knot, 59))
    if style == "half_up":   # (braids from the temples back over the hair)
        obs.append(locks_obj("hair_braids", lambda bm, uvl: temple_braids(bm, uvl, .11 * R, .36 * R), 55))   # (over the hair's outer layer)
elif style in GATHERED:
    obs, mask_of = build_gathered(style)
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


if job.get("piece") not in FACE_HAIR:   # (brows, lashes: fine hairs on the skin - nothing over them)
    bake_ao(obs)
    print("ao baked", flush=True)

# ---------------------------------------------------------------- weights: the head's; below the jaw the neck's and the chest's
groups = [names["head"], names.get("neck", names["head"]), names.get("spine2", names.get("neck", names["head"]))]
groups = [g for g in groups if g in arm.data.bones] or [names["head"]]
d_ = .95 * R


JAW = names.get("jaw") if names.get("jaw") in arm.data.bones else None


def weights(z):
    if job.get("piece") in FACE_HAIR:   # (the brows, the lashes: the head's; the face's keys move them)
        return [(groups[0], 1.)]
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
    keys = {tuple(x) for x in body_mask(body, [mask_of], erode=2)} if job.get("piece") not in ("beard", *FACE_HAIR) else set()
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
obj.name = f"{job.get('piece') if job.get('piece') in ('beard', *FACE_HAIR) else 'hair'}_{style}"
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
        {"nodes": {k: b2gl(v) for k, v in NODES_OUT.items()}, "loop": LOOP, "mid": round(O.x if not FM else FM.get("mouth_c", O).x, 5),
         "loops": [lp for lp in (LOOPS_OUT or (list(LOOP), ["must_L", "must_top_L", "must_ct", "must_top_R", "must_R", "must_lo_R", "must_bot_R", "must_cb", "must_bot_L", "must_lo_L"]))
                   if len(lp) > 2 and all(k in NODES_OUT for k in lp)]}), encoding="utf-8")
_vc = {"export_vertex_color": "ACTIVE"} if "export_vertex_color" in bpy.ops.export_scene.gltf.get_rna_type().properties.keys() else {"export_colors": True}
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_influence_nb=4, export_morph=True, export_morph_normal=False,
                          **_vc)   # (its shadows: the vertices' colour; the brows', the lashes' face keys)
print("ARMOUR_GEN_OK " + json.dumps({"vertices": len(obj.data.vertices), "bones": groups, "style": style, "uvtex": {}}), flush=True)
