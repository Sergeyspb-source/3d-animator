"""Eyelids of their own topology, grown into the face's skin. Runs inside Blender: blender_eye_insert.py calls build().

Per eye a lid of rows is built round the opening, in the face's own mesh:
  - the margin with its thickness: the wet line just over the ball and the lash line in front of it (material
    eyelid_rim: the lashes find it), a sleeve from the wet line back under the lid over the ball (nothing is seen through
    between the lid and the ball);
  - the lid's body: rows over the ball (upper 3, lower 2), on spheres round the ball's centre;
  - the crease over the upper lid (a groove) and the fold from it to the skin;
  - the orbit's two loops out on the skin (front rays), a hair under it.
The rows are concentric loops round the opening; at the corners they part sideways round the ball. The source's skin
round the opening - its lid flaps, its painted lid and lashes, a pit by a corner - is cut away inside a loop between the
orbit's loops, its new edge pressed onto the patch: it grows out of the skin with nothing to weld (zipped to the cut's
edge the band met every layer the source has there - a fold under a brow, inner shells, a flap by the temple - and left
holes, a different few on every model).
The keys (eyeBlink / eyeSquint / eyeWide per side) turn the lid's rows about the ball's lateral axis, all of a lid by the
same angle (it slides over the ball whole); the crease turns part way, the fold less, the orbit's loops follow the skin.
A blink also has a helper key (eyeBlink<Side>_arc, weight 4v(1-v) along the blink): a key is a straight line from the
open place to the closed one - the chord cuts deep into the ball half way; the helper bends it back onto the arc.
Its own unwrap: the rows x columns grid in a texture of its own (eyelid_skin, both eyes), coloured from the face's
texture where the patch lies on skin, filled smoothly from it over the lid (the source had its painted eye there).
"""
import math

import bmesh
import bpy
import numpy as np
from mathutils import Vector
from mathutils.bvhtree import BVHTree
from mathutils.interpolate import poly_3d_calc

SIDE = {"L": "Left", "R": "Right"}
NU = 14   # columns along each lid (the ring: 2 x NU)
# the rings from the sleeve's open end out: name, upper lid (turn away from the opening, deg; radius over the wet line
# in lid thicknesses; skin share), lower lid (the same), at the corners the turn sideways (deg), share of the lid's turn
# in a blink (upper, lower). Skin share 1: on the skin (front ray), 0: on the sphere round the ball.
RINGS = [
    ("sleeve2", (26., 0., 0.), (16., 0., 0.), 9., (1., 1.)),
    ("sleeve1", (11., 0., 0.), (7., 0., 0.), 4., (1., 1.)),
    ("wet", (0., 0., 0.), (0., 0., 0.), 0., (1., 1.)),
    ("lash", (1.5, 1., 0.), (1.5, 1., 0.), 1., (1., 1.)),
    ("body1", (9., 1.15, 0.), (6., 1.05, 0.), 4., (1., 1.)),
    ("body2", (18., 1.25, 0.), (12., 1.05, 0.), 8., (1., 1.)),
    ("body3", (27., 1.25, 0.), (18., 1., .3), 12., (1., .6)),
    ("crease", (34., .6, 0.), (25., 1., .7), 16., (.55, .25)),
    ("fold", (39., 1.8, .5), (32., 1., 1.), 20., (.2, 0.)),
    ("orb1", (0., 0., 1.), (0., 0., 1.), 0., (0., 0.)),
    ("orb2", (0., 0., 1.), (0., 0., 1.), 0., (0., 0.)),
]
IW = RINGS.index(next(x for x in RINGS if x[0] == "wet"))
# on the skin: how far out from the lash line (front view, in ball radii): upper, lower, corner
GROW = {"body3": (.25, .25, .2), "crease": (.4, .4, .32), "fold": (.55, .58, .45), "orb1": (.8, .78, .65),
        "orb2": (1.08, 1.0, .88)}
CUT = (.93, .9, .76)   # the cut's loop (the old skin's new edge: between orb1 and orb2, over the patch)


def smoothstep(a, b, x):
    t = min(1., max(0., (x - a) / (b - a)))
    return t * t * (3 - 2 * t)


def inside(poly, x, z):
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, zi = poly[i]
        xj, zj = poly[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi:
            c = not c
        j = i
    return c


def rot_x(q, a):   # q (from the ball's centre) turned about the lateral axis by a (+ = up; forward is -y)
    rho, ph = math.hypot(q.y, q.z), math.atan2(q.z, -q.y) + a
    return Vector((q.x, -rho * math.cos(ph), rho * math.sin(ph)))


def rot_z(q, a):   # about the vertical axis: its azimuth atan2(x, -y) grows by a
    ca, sa = math.cos(a), math.sin(a)
    return Vector((q.x * ca - q.y * sa, q.x * sa + q.y * ca, q.z))


def elev(q):
    return math.atan2(q.z, -q.y)


def resample(pts, n):
    """n + 1 points evenly along a polyline (by its length seen from the front)"""
    arc = [0.]
    for a, b in zip(pts, pts[1:]):
        arc.append(arc[-1] + math.hypot(b.x - a.x, b.z - a.z))
    out = []
    for k in range(n + 1):
        t = arc[-1] * k / n
        i = max(0, min(len(arc) - 2, next((i for i in range(len(arc) - 1) if arc[i + 1] >= t), len(arc) - 2)))
        out.append(pts[i].lerp(pts[i + 1], (t - arc[i]) / max(arc[i + 1] - arc[i], 1e-12)))
    return out


def seg_dist2(px, pz, poly):   # distance (front view) from a point to a closed polyline
    best = 1e18
    for (ax, az), (bx, bz) in zip(poly, poly[1:] + poly[:1]):
        dx, dz = bx - ax, bz - az
        t = max(0., min(1., ((px - ax) * dx + (pz - az) * dz) / (dx * dx + dz * dz + 1e-18)))
        best = min(best, (ax + dx * t - px) ** 2 + (az + dz * t - pz) ** 2)
    return math.sqrt(best)


class Field:
    """the face's skin as it is now (before the lids' cut): its nearest point -> weights, shape keys' moves"""

    def __init__(self, ob):
        me = ob.data
        M = ob.matrix_world
        self.W = [M @ v.co for v in me.vertices]
        me.calc_loop_triangles()
        self.tris = [tuple(t.vertices) for t in me.loop_triangles]
        self.bvh = BVHTree.FromPolygons(self.W, self.tris)
        M3 = M.to_3x3()
        self.N = [(M3 @ v.normal).normalized() for v in me.vertices]
        self.groups = [{g.group: g.weight for g in v.groups if g.weight > 1e-4} for v in me.vertices]
        self.keys = []
        sk = me.shape_keys
        n = len(me.vertices)
        self.D = None
        if sk is not None and len(sk.key_blocks) > 1:
            base = np.empty(n * 3, np.float32)
            sk.key_blocks[0].data.foreach_get("co", base)
            M3 = np.array(M.to_3x3(), np.float32)
            arr = []
            for kb in sk.key_blocks[1:]:
                a = np.empty(n * 3, np.float32)
                kb.data.foreach_get("co", a)
                arr.append((a - base).reshape(-1, 3) @ M3.T)
                self.keys.append(kb.name)
            self.D = np.stack(arr)

    def at(self, p):
        loc, nrm, ti, dist = self.bvh.find_nearest(p)
        if loc is None:
            return None, None
        vs = self.tris[ti]
        w = poly_3d_calc([self.W[i] for i in vs], loc)
        g = {}
        for i, wt in zip(vs, w):
            for k, x in self.groups[i].items():
                g[k] = g.get(k, 0.) + x * max(0., wt)
        top = sorted(g.items(), key=lambda kv: -kv[1])[:4]
        s = sum(x for _, x in top) or 1.
        moves = None
        if self.D is not None:
            moves = sum(self.D[:, i, :] * max(0., float(wt)) for i, wt in zip(vs, w)) / max(1e-9, sum(max(0., float(x)) for x in w))
        return {k: x / s for k, x in top}, moves


class Source:
    """the face before the eyes were cut: its colour at a point (nearest face, its unwrap, its picture)"""

    def __init__(self, me_src, M, base_pixels):
        me_src.calc_loop_triangles()
        self.W = [M @ v.co for v in me_src.vertices]
        self.tris = list(me_src.loop_triangles)
        self.bvh = BVHTree.FromPolygons(self.W, [tuple(t.vertices) for t in self.tris])
        uvl = me_src.uv_layers.active
        self.uv = [[(uvl.data[li].uv.x, uvl.data[li].uv.y) for li in t.loops] for t in self.tris] if uvl else None
        self.px = [base_pixels(me_src.materials[t.material_index] if t.material_index < len(me_src.materials) else None)
                   for t in self.tris] if uvl else None

    def uv_at(self, p):
        if self.uv is None:
            return None
        loc, nrm, ti, dist = self.bvh.find_nearest(p)
        if loc is None:
            return None
        w = poly_3d_calc([self.W[i] for i in self.tris[ti].vertices], loc)
        return (sum(a[0] * x for a, x in zip(self.uv[ti], w)), sum(a[1] * x for a, x in zip(self.uv[ti], w)))

    def colour(self, p):
        if self.uv is None:
            return None
        loc, nrm, ti, dist = self.bvh.find_nearest(p)
        if loc is None or self.px[ti] is None:
            return None
        t = self.tris[ti]
        w = poly_3d_calc([self.W[i] for i in t.vertices], loc)
        u = sum(a[0] * x for a, x in zip(self.uv[ti], w))
        v = sum(a[1] * x for a, x in zip(self.uv[ti], w))
        arr, w_, h_ = self.px[ti][0], self.px[ti][1], self.px[ti][2]
        return arr[int(min(h_ - 1, max(0, (v % 1.) * h_))), int(min(w_ - 1, max(0, (u % 1.) * w_)))]


def build(face, solved, balls, job, src_me, base_pixels):
    """the lids of both eyes into the face's mesh (face: the skin object, solved: blender_eye_insert's per side data:
    centre, r_ball, curve, corners; balls: (object, bone, centre, r); src_me: the face's mesh before the eyes' cut)
    -> report dict"""
    me = face.data
    M = face.matrix_world
    Mi = M.inverted()
    M3i = Mi.to_3x3()
    rep = {}
    rep["peeled"] = _peel(face, solved, int(job.get("lid_peel", 0))) if int(job.get("lid_peel", 0)) > 0 else 0
    field = Field(face)
    src = Source(src_me, M, base_pixels)
    if me.shape_keys is None:
        face.shape_key_add(name="Basis")
    key_names = [kb.name for kb in me.shape_keys.key_blocks[1:]]
    for sd in solved:   # (the blink's helper keys exist before the mesh goes to bmesh: then they are layers)
        nm = "eyeBlink" + SIDE.get(sd, sd) + "_arc"
        if nm not in key_names:
            kb = face.shape_key_add(name=nm, from_mix=False)
            kb.value = 0.
            key_names.append(nm)
    for nm in [f"{k}{SIDE.get(sd, sd)}" for sd in solved for k in ("eyeBlink", "eyeSquint", "eyeWide")]:
        if nm not in key_names:
            kb = face.shape_key_add(name=nm, from_mix=False)
            kb.value = 0.
            key_names.append(nm)
    # materials: the patch's skin (own texture, both eyes) and the margin (plain)
    mats = {}
    skin_col = []
    for sv in solved.values():
        skin_col.append(_skin_colour(src, sv))
    col = np.median(np.array(skin_col), axis=0) if skin_col else np.array([.6, .45, .35])
    lin = [((v + .055) / 1.055) ** 2.4 if v > .04045 else v / 12.92 for v in col]
    rough, factor = _roughness(me, src, solved), _factor(me)
    TW, TH1 = 512, 192   # the texture: an eye's block 512 x 192, both stacked
    img = bpy.data.images.new("eyelid_skin", TW, 2 * TH1, alpha=False)
    for name, base, r_ in (("eyelid_skin", None, rough), ("eyelid_rim", (lin[0] * .5, lin[1] * .4, lin[2] * .38), .4)):
        m = bpy.data.materials.get(name) or bpy.data.materials.new(name)
        m.use_nodes = True
        bs = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        bs.inputs["Roughness"].default_value = r_
        if base is None:
            tx = m.node_tree.nodes.new("ShaderNodeTexImage")
            tx.image = img
            if factor is not None:   # (the face's picture times its colour factor, as the face has it)
                mx = m.node_tree.nodes.new("ShaderNodeMix")
                mx.data_type, mx.blend_type = "RGBA", "MULTIPLY"
                mx.inputs[0].default_value = 1.
                mx.inputs[7].default_value = factor
                m.node_tree.links.new(tx.outputs["Color"], mx.inputs[6])
                m.node_tree.links.new(mx.outputs[2], bs.inputs["Base Color"])
            else:
                m.node_tree.links.new(tx.outputs["Color"], bs.inputs["Base Color"])
        else:
            bs.inputs["Base Color"].default_value = (*base, 1.)
        if m.name not in [x.name for x in me.materials if x]:
            me.materials.append(m)
        mats[name] = [x.name if x else "" for x in me.materials].index(m.name)
    tex = np.zeros((2 * TH1, TW, 3), np.float32)
    known = np.zeros((2 * TH1, TW), bool)
    bake = []
    bm = bmesh.new()
    bm.from_mesh(me)
    deform = bm.verts.layers.deform.verify()
    shape = {kb.name: bm.verts.layers.shape.get(kb.name) for kb in me.shape_keys.key_blocks}
    uvl = bm.loops.layers.uv.active or bm.loops.layers.uv.new("UVMap")
    mid_x = sum(sv["centre"].x for sv in solved.values()) / len(solved) if len(solved) > 1 else None
    patch = set()   # (the lids made so far: the other eye's cut leaves them be)
    for bi, (sd, sv) in enumerate(solved.items()):
        try:
            out = _one_eye(bm, M, sd, sv, balls, job, field, src, deform, shape, uvl, mats, (bi * TH1, TH1, TW), mid_x, patch)
        except Exception as e:  # noqa: BLE001 - one eye's lid failed: the report says why, the other goes on
            import traceback
            traceback.print_exc()
            rep[sd] = {"error": str(e)}
            continue
        rep[sd] = out.pop("report")
        bake.append(out)
    bm.to_mesh(me)
    bm.free()
    me.update()
    rep["seam_normals"] = _seam_normals(face, field, bake) if job.get("lid_seam_normals", True) else 0
    # the texture: the face's colours where the patch lies on skin, the rest filled from them
    for b in bake:
        _bake(b, src, tex, known)
    if known.any():
        from tex_pad import pad_fill
        for b in bake:
            y0, h = b["block"][0], b["block"][1]
            blk = tex[y0:y0 + h]
            kn = known[y0:y0 + h]
            if kn.any():
                tex[y0:y0 + h] = pad_fill(blk, kn)
                _shade(tex[y0:y0 + h], b)
    else:
        tex[...] = col[None, None, :]
    img.pixels.foreach_set(np.concatenate([tex, np.ones((2 * TH1, TW, 1), np.float32)], axis=2).ravel())
    img.pack()
    rep["colour"] = [round(float(x), 3) for x in col]
    return rep


def _peel(face, solved, times):
    """the source's frills and flaps round the eyes peeled off: the faces near an eye with an open edge (the
    unwrap's seams welded) go, a few times over - a thin flap, a frill of painted lid, a strap over the eye go whole,
    the closed skin stays (the eye's own opening only moves out a few rings: the lid's cut is further out)"""
    from collections import Counter
    me = face.data
    M = face.matrix_world
    bm = bmesh.new()
    bm.from_mesh(me)
    eyes = [(sv["centre"], sv["r_ball"]) for sv in solved.values()]
    gone = 0
    for _ in range(times):
        bm.verts.ensure_lookup_table()
        W = [M @ v.co for v in bm.verts]
        first = {}
        rep = [first.setdefault((round(p.x * 2e5), round(p.y * 2e5), round(p.z * 2e5)), i) for i, p in enumerate(W)]
        near = lambda p: any((p - c).length < 3.2 * r for c, r in eyes)   # noqa: E731
        ec = Counter()
        fl = []
        for f in bm.faces:
            vs = [rep[v.index] for v in f.verts]
            es = [frozenset((a_, b_)) for a_, b_ in zip(vs, vs[1:] + vs[:1]) if a_ != b_]
            fl.append((f, es))
            for e in es:
                ec[e] += 1
        kill = [f for f, es in fl if any(ec[e] == 1 for e in es) and near(M @ f.calc_center_median())]
        if not kill:
            break
        gone += len(kill)
        bmesh.ops.delete(bm, geom=kill, context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(me)
    bm.free()
    me.update()
    return gone


def _seam_normals(face, field, outs):
    """one shading across the old skin's edge over the lid: the corners there (the old skin's and the lid's under it,
    within a band round the cut's loop, on the skin as it was) get the face's own smooth normal at their place - else
    the edge read as a line: the old skin's normals and the lid's differ"""
    me = face.data
    M = face.matrix_world
    M3i = M.inverted().to_3x3()
    W = [M @ v.co for v in me.vertices]
    try:
        cn = [Vector(x.vector) for x in me.corner_normals]
    except AttributeError:
        return 0
    changed = 0
    for o in outs:
        fine, c, r = o["fine"], o["c"], o["r"]
        near = {}
        for vi, p in enumerate(W):
            if math.hypot(p.x - c.x, p.z - c.z) > 4. * r:
                continue
            if seg_dist2(p.x, p.z, fine) > .3 * r:
                continue
            loc, n_, ti, dist = field.bvh.find_nearest(p)
            if loc is None or dist > .06 * r:
                continue
            vs = field.tris[ti]
            w = poly_3d_calc([field.W[j] for j in vs], loc)
            n = sum((field.N[j] * float(x) for j, x in zip(vs, w)), Vector()).normalized()
            near[vi] = n
        for li, lp in enumerate(me.loops):
            n = near.get(lp.vertex_index)
            if n is None:
                continue
            nl = (M3i @ n).normalized()
            if nl.dot(cn[li]) < 0:
                nl = -nl
            cn[li] = nl
            changed += 1
    if changed:
        me.normals_split_custom_set([tuple(v) for v in cn])
    return changed


def _skin_colour(src, sv):
    """the skin's median colour round an eye (from the face's texture: under the brow, on the cheek)"""
    c, r = sv["centre"], sv["r_ball"]
    cols = []
    for ang in range(0, 360, 15):
        for k in (1.9, 2.3):
            a = math.radians(ang)
            p = c + Vector((math.cos(a) * k * r, -1.2 * r, math.sin(a) * k * r))
            x = src.colour(p)
            if x is not None:
                cols.append(np.asarray(x, np.float32))
    return np.median(np.array(cols), axis=0) if cols else np.array([.6, .45, .35], np.float32)


def _skin_mat(me):
    """the face's own material (the most used one)"""
    from collections import Counter
    n = Counter(p.material_index for p in me.polygons).most_common(1)
    i = n[0][0] if n else 0
    return me.materials[i] if i < len(me.materials) else None


def _factor(me):
    """the face's colour factor (glTF baseColorFactor: its picture times a colour, a Mix multiply) or None"""
    m = _skin_mat(me)
    if m is None or not m.node_tree:
        return None
    for n in m.node_tree.nodes:
        if n.type == "MIX" and n.data_type == "RGBA" and n.blend_type == "MULTIPLY" and not n.inputs[7].links:
            return tuple(n.inputs[7].default_value)
    return None


def _roughness(me, src, solved):
    """the face's roughness round the eyes: its value, or its map's (a channel of a picture) median there"""
    m = _skin_mat(me)
    bs = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None) if m and m.node_tree else None
    if bs is None:
        return .6
    inp = bs.inputs["Roughness"]
    if not inp.links:
        return float(inp.default_value)
    l = inp.links[0]
    ch = {"Red": 0, "Green": 1, "Blue": 2, "R": 0, "G": 1, "B": 2}.get(l.from_socket.name, 1)
    node = l.from_node
    if node.type == "SEPARATE_COLOR" and node.inputs[0].links:
        node = node.inputs[0].links[0].from_node
    if node.type != "TEX_IMAGE" or node.image is None or not node.image.size[0]:
        return .6
    im = node.image
    arr = np.empty(im.size[0] * im.size[1] * 4, np.float32)
    im.pixels.foreach_get(arr)
    arr = arr.reshape(im.size[1], im.size[0], 4)
    vals = []
    for sv in solved.values():
        c, r = sv["centre"], sv["r_ball"]
        for ang in range(0, 360, 20):
            a = math.radians(ang)
            uv = src.uv_at(c + Vector((math.cos(a) * 2.1 * r, -1.2 * r, math.sin(a) * 2.1 * r)))
            if uv is not None:
                vals.append(float(arr[int(min(im.size[1] - 1, (uv[1] % 1.) * im.size[1])), int(min(im.size[0] - 1, (uv[0] % 1.) * im.size[0])), ch]))
    return float(np.median(vals)) if vals else .6


def _one_eye(bm, Mo, sd, sv, balls, job, field, src, deform, shape, uvl, mats, block, mid_x, patch):
    basis_name = next(iter(shape))   # (the reference key: the first)
    c, r = sv["centre"], sv["r_ball"]
    curve = sv["curve"]   # (Catmull-Rom through the clicks: 0 inner corner, 10 top, 20 outer corner, 30 bottom)
    bulge = max([(v.co - c).length for b, _bn, cc, _r in balls if (cc - c).length < 1e-6 for v in b.data.vertices] or [r])
    ball_ob = next((b for b, _bn, cc, _r in balls if (cc - c).length < 1e-6), None)
    ball_bvh = None
    if ball_ob is not None:
        ball_bvh = BVHTree.FromPolygons([v.co.copy() for v in ball_ob.data.vertices], [list(p.vertices) for p in ball_ob.data.polygons])
    n_c = len(curve)
    q4 = n_c // 4
    up_pts = resample(curve[0:2 * q4 + 1], NU)                      # inner -> top -> outer
    lo_pts = resample(curve[2 * q4:] + [curve[0]], NU)              # outer -> bottom -> inner
    ring2 = up_pts + lo_pts[1:-1]
    N = len(ring2)
    is_up = [True] * (NU + 1) + [False] * (NU - 1)
    upar = [j / NU for j in range(NU + 1)] + [1 - j / NU for j in range(1, NU)]
    fade = [math.sin(math.pi * u) ** .6 for u in upar]
    C2 = (sum(p.x for p in ring2) / N, sum(p.z for p in ring2) / N)
    out_x = 1. if ring2[NU].x > ring2[0].x else -1.   # (+x toward the outer corner)
    Rw_up, Rw_lo = max(1.015 * r, 1.02 * bulge), max(1.01 * r, 1.005 * bulge)
    T = .065 * r
    Rw = [(Rw_up if is_up[i] else Rw_lo) if 0 < i < NU or i > NU else .5 * (Rw_up + Rw_lo) for i in range(N)]

    # the wet line: the opening as clicked, seen from the front, on the sphere just over the ball (the corners pulled
    # in onto it: the opening as marked is often wider than the ball - between the corner and the ball one saw into the head)
    def on_sphere(x, z, R, lim=.92):
        dx, dz = x - c.x, z - c.z
        d = math.hypot(dx, dz)
        if d > lim * R:
            dx, dz = dx * lim * R / d, dz * lim * R / d
        return Vector((c.x + dx, c.y - math.sqrt(max(R * R - dx * dx - dz * dz, 0.)), c.z + dz))
    wet = [on_sphere(p.x, p.z, Rw[i]) for i, p in enumerate(ring2)]
    clamped = sum(1 for i, p in enumerate(ring2) if math.hypot(p.x - c.x, p.z - c.z) > .92 * Rw[i])
    # (smoothed along the line: the clamped corners, the clicks' curve)
    for _ in range(2):
        wet = [wet[i] if i in (0, NU) else (wet[i] * .5 + (wet[i - 1] + wet[(i + 1) % N]) * .25) for i in range(N)]
        wet = [c + (p - c).normalized() * Rw[i] for i, p in enumerate(wet)]

    def side_out(i):   # sideways (about the vertical axis) toward the nearer corner, outward
        return out_x if upar[i] >= .5 else -out_x

    def sphere_pt(k, i):
        nm, up_, lo_, psi, _ = RINGS[k]
        corner = i in (0, NU)
        ph_u, dr_u, _s = up_
        ph_l, dr_l, _s2 = lo_
        if corner:
            ph, dr = 0., .5 * (dr_u + dr_l)
        else:
            ph, dr = (ph_u, dr_u) if is_up[i] else (-ph_l, dr_l)
        q = wet[i] - c
        q = rot_x(q, math.radians(ph) * fade[i])
        # (at the corners the rows part sideways round the ball)
        q = rot_z(q, math.radians(psi) * (1 - fade[i]) * side_out(i))
        R = Rw[i] + dr * T
        if nm.startswith("sleeve"):
            R = Rw[i]
        return c + q.normalized() * R

    def share(k, i):
        up_, lo_ = RINGS[k][1], RINGS[k][2]
        if i in (0, NU):
            return .5 * (up_[2] + lo_[2])
        return up_[2] if is_up[i] else lo_[2]

    # the skin as front rays meet it (the skin round the eye only: not a lock of hair or the nose's far side)
    W_ = field.W
    loc_tris = [t for t in field.tris if any(math.hypot(W_[j].x - c.x, W_[j].z - c.z) < 4.5 * r and W_[j].y < c.y + 2. * r for j in t)]
    skin_bvh = BVHTree.FromPolygons(W_, loc_tris)
    ymin = c.y - 12 * r

    def front(x, z):
        h = skin_bvh.ray_cast(Vector((x, ymin, z)), Vector((0, 1, 0)), 20 * r)
        return h[0]
    lash2 = [(sphere_pt(IW + 1, i).x, sphere_pt(IW + 1, i).z) for i in range(N)]

    def grown(g3, i, cut=False):   # the lash line's loop grown out from the opening's centre by g (ball radii), front view
        g = (.5 * (g3[0] + g3[1]) if i in (0, NU) else g3[0] if is_up[i] else g3[1])
        if i in (0, NU) or fade[i] < .5:
            gc = g3[2]
            g = gc + (g - gc) * smoothstep(0., .5, fade[i])
        x, z = lash2[i]
        dx, dz = x - C2[0], z - C2[1]
        d = math.hypot(dx, dz) or 1e-9
        gx, gz = x + dx / d * g * r, z + dz / d * g * r
        if mid_x is not None and (gx - c.x) * (mid_x - c.x) > 0:   # (toward the nose: short of the face's middle,
            # each loop shorter than the next out - on one line the band between them came out folded flat)
            top_ = float(job.get("lid_nose", .84))
            lim = (.7 if cut else .55 + (top_ - .55) * min(1., g3[2] / GROW["orb2"][2])) * abs(mid_x - c.x)
            if abs(gx - c.x) > lim:
                gx = c.x + math.copysign(lim, gx - c.x)
        return gx, gz

    def skin_pt(k, i):
        x, z = grown(GROW[RINGS[k][0]], i)
        p = front(x, z)
        if p is None:   # (no skin in front there: the sphere's place carried out)
            p = sphere_pt(k, i)
        q = p - c
        lim = Rw[i] + 2.2 * T
        if q.length < lim:   # (the old skin hugging the ball under the source's lid: the patch stays over the lid)
            p = c + q.normalized() * lim
        return p

    rings = []
    for k in range(len(RINGS)):
        row = []
        for i in range(N):
            s = share(k, i)
            if s <= 0.:
                row.append(sphere_pt(k, i))
            elif s >= 1. or RINGS[k][0] not in GROW:
                row.append(skin_pt(k, i) if RINGS[k][0] in GROW else sphere_pt(k, i))
            else:
                row.append(sphere_pt(k, i).lerp(skin_pt(k, i), s))
        rings.append(row)
    # the outer loops smoothed along themselves (front rays over an uneven skin), on the skin again
    for k in range(len(RINGS)):
        if RINGS[k][0] not in ("orb1", "orb2"):
            continue
        row = rings[k]
        for _ in range(2):
            row = [row[i] * .5 + (row[i - 1] + row[(i + 1) % N]) * .25 for i in range(N)]
        rings[k] = [front(p.x, p.z) or p for p in row]
    # (a thin flap of the source's lid or a fold by the temple met by a front ray: a spike in the ring - its distance
    # from the ball's centre far off its neighbours': put back at theirs, its direction kept)
    for k in range(len(RINGS)):
        if max(share(k, i) for i in range(N)) <= 0.:
            continue
        for _ in range(2):
            rho = [(p - c).length for p in rings[k]]
            new_row = []
            for i, p in enumerate(rings[k]):
                if share(k, i) <= 0.:
                    new_row.append(p)
                    continue
                nb = sorted(rho[(i + j) % N] for j in (-2, -1, 1, 2))
                med = .5 * (nb[1] + nb[2])
                if abs(rho[i] - med) > .3 * r:
                    p = c + (p - c).normalized() * med
                new_row.append(p)
            rings[k] = new_row
        if k > 0:   # (and not inside the ring before it)
            rings[k] = [c + (p - c).normalized() * max((p - c).length, (rings[k - 1][i] - c).length - .15 * r) if share(k, i) > 0. else p
                        for i, p in enumerate(rings[k])]

    # ---------------------------------------------------------------- the old skin's edge over the patch
    # The patch's loops out on the skin lie a little under it and the old skin is cut back only inside the first of
    # them: its edge lies over the patch, pressed onto it - nothing to weld. (Zipped to the cut's edge the band met
    # every layer the source has there - a fold under a brow, its inner shells, a flap by the temple - and left holes
    # here and there, a different few on every model)
    def outward(p):   # (the skin's normal there, out of the head: a short ray that way meets no skin)
        loc, n, _i, _d = skin_bvh.find_nearest(p)
        if loc is None:
            return (p - c).normalized()
        n = n.normalized()
        if skin_bvh.ray_cast(loc + n * (.01 * r), n, .3 * r)[0] is not None:
            n = -n
        return n
    for k in range(len(RINGS)):
        for i in range(N):
            s_ = share(k, i)
            if s_ > 0.:   # (under the skin along its own normal: on a steep wall - the nose's side - the line from
                # the ball's centre runs along the skin, and the lid's edge stood off it in a dark slit)
                p = rings[k][i]
                rings[k][i] = p - outward(p) * ((.02 if k == len(RINGS) - 1 else .012) * r * s_)
    cut2 = [grown(CUT, i, True) for i in range(N)]
    for _ in range(2):
        cut2 = [(cut2[i][0] * .5 + (cut2[i - 1][0] + cut2[(i + 1) % N][0]) * .25,
                 cut2[i][1] * .5 + (cut2[i - 1][1] + cut2[(i + 1) % N][1]) * .25) for i in range(N)]
    fine = []
    for i in range(N):   # (a finer loop: the cut follows it)
        a, b = cut2[i], cut2[(i + 1) % N]
        for t in range(4):
            fine.append((a[0] + (b[0] - a[0]) * t / 4, a[1] + (b[1] - a[1]) * t / 4))
    bm.verts.ensure_lookup_table()
    bm.faces.ensure_lookup_table()
    Moi = Mo.inverted()
    P = lambda v: Mo @ v.co   # noqa: E731
    ins = lambda p: inside(fine, p.x, p.z)   # noqa: E731
    # (what goes: the skin inside the loop down to a little behind the patch - where the face turns back at the temple
    # too -, not the source's inner shells deep behind the ball)
    pq = [(rings[k][i], rings[k][(i + 1) % N], rings[k + 1][(i + 1) % N], rings[k + 1][i]) for k in range(IW, len(RINGS) - 1) for i in range(N)]
    pv = [p for q in pq for p in q]
    pbvh = BVHTree.FromPolygons(pv, [(4 * j, 4 * j + 1, 4 * j + 2, 4 * j + 3) for j in range(len(pq))])
    rref = {}

    def ref_r(p):   # (how far out from the ball's centre the patch is in p's direction - or the skin, past it)
        d = (p - c).normalized()
        key_ = (round(d.x * 60), round(d.y * 60), round(d.z * 60))
        if key_ not in rref:
            h = pbvh.ray_cast(c + d * (6 * r), -d, 6 * r)
            if h[0] is None:
                h = skin_bvh.ray_cast(c + d * (3 * r), -d, 3 * r)
            rref[key_] = (h[0] - c).length if h[0] is not None else 2 * r
        return rref[key_]
    yref = {}

    def ref_y(x, z):   # (how deep the patch is there seen from the front - or the skin)
        key_ = (round(x / (.05 * r)), round(z / (.05 * r)))
        if key_ not in yref:
            h = pbvh.ray_cast(Vector((x, ymin, z)), Vector((0, 1, 0)), 20 * r)
            if h[0] is None:
                h = (front(x, z),)
            yref[key_] = h[0].y if h[0] is not None else c.y
        return yref[key_]
    # (what goes: the skin inside the loop down to a little under the patch - seen from the front, or from the ball's
    # centre where the face turns back at the temple -, not the source's inner shells deep behind the ball)
    band = lambda p: (math.hypot(p.x - c.x, p.z - c.z) < 5. * r and p.y < c.y + 2.5 * r   # noqa: E731
                      and (p.y < ref_y(p.x, p.z) + .9 * r or (p - c).length < ref_r(p) + .9 * r))
    cuts = set()
    for e in list(bm.edges):
        a, b = P(e.verts[0]), P(e.verts[1])
        if e.verts[0] in patch or e.verts[1] in patch or ins(a) == ins(b):
            continue
        if min(math.hypot(a.x - c.x, a.z - c.z), math.hypot(b.x - c.x, b.z - c.z)) > 6 * r:
            continue
        t0, t1 = 0., 1.
        for _ in range(18):
            m_ = (t0 + t1) / 2
            if ins(a.lerp(b, m_)) == ins(a):
                t0 = m_
            else:
                t1 = m_
        if not band(a.lerp(b, (t0 + t1) / 2)):   # (where it crosses: a long edge's ends may both lie far off)
            continue
        _, nv = bmesh.utils.edge_split(e, e.verts[0], (t0 + t1) / 2)
        cuts.add(nv)
    for f in list(bm.faces):
        cv = [v for v in f.verts if v in cuts]
        if len(cv) == 2 and not any(cv[1] in e.verts for e in cv[0].link_edges):
            try:
                bmesh.ops.connect_verts(bm, verts=cv)
            except Exception:  # noqa: BLE001
                pass
    M3_ = Mo.to_3x3()
    side_keep = float(job.get("lid_side_keep", 0.))

    def goes(f):   # (inside the loop, near the patch; by the loop not a face turned sideways - the nose's side wall: the
        # lid lay on another part of it and a slit stayed open between them)
        q = Mo @ f.calc_center_median()
        if not (ins(q) and band(q)):
            return False
        if side_keep > 0 and seg_dist2(q.x, q.z, fine) < .35 * r and abs((M3_ @ f.normal).normalized().y) < side_keep:
            return False
        return True
    kill = [f for f in bm.faces if not any(v in patch for v in f.verts) and goes(f)]
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces and math.hypot(P(v).x - c.x, P(v).z - c.z) < 6 * r], context="VERTS")
    # the old skin's new edge pressed onto the patch (from outside, along the line from the ball's centre): its outer
    # layer only - the inner ones' edges stay under the patch, unseen
    dl = lambda p: seg_dist2(p.x, p.z, fine)   # noqa: E731
    shapes_ = list(bm.verts.layers.shape.values())
    M3i_ = Moi.to_3x3()

    def move(v, d_world):
        dlt = M3i_ @ d_world
        v.co += dlt
        for lay in shapes_:
            v[lay] += dlt
    # (the edge as cut is ragged - a face not split leaves a tooth -, its twins along the unwrap's seams apart: it
    # read as a jagged line over the lid. Twins welded, teeth off, the edge relaxed along itself)
    ev = [v for v in bm.verts if v.is_boundary and v not in patch and dl(P(v)) < .1 * r]
    if ev:
        bmesh.ops.remove_doubles(bm, verts=ev, dist=.004 * r)
    def over(q, tol=.05):   # (the lid right under it, along the line to the ball's centre - not just beside its edge)
        d_ = (q - c).normalized()
        h_ = pbvh.ray_cast(q + d_ * (.2 * r), -d_, .4 * r)
        return h_[0] is not None and (h_[0] - q).length < tol * r
    for _ in range(2 if job.get("lid_edge_clean", False) else 0):   # (only over the lid: past its edge a tooth off was a hole)
        teeth = [f for f in bm.faces if not any(v in patch for v in f.verts) and dl(Mo @ f.calc_center_median()) < .15 * r
                 and sum(1 for e in f.edges if e.is_boundary) >= 2 and all(over(P(v)) for v in f.verts)]
        if not teeth:
            break
        bmesh.ops.delete(bm, geom=teeth, context="FACES")
        bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces and math.hypot(P(v).x - c.x, P(v).z - c.z) < 6 * r], context="VERTS")
    for _ in range(6 if job.get("lid_edge_clean", False) else 0):
        ring_ = {}
        for v in bm.verts:
            if v.is_boundary and v not in patch and dl(P(v)) < .2 * r:
                nb_ = [e.other_vert(v) for e in v.link_edges if e.is_boundary]
                if len(nb_) == 2:
                    ring_[v] = (P(nb_[0]) + P(nb_[1])) * .5
        for v, m_ in ring_.items():
            to = P(v) + (m_ - P(v)) * .5
            if over(to, .08):   # (it stays over the lid)
                move(v, to - P(v))
    snapped = 0
    for v in [v for v in bm.verts if v.is_boundary and v not in patch]:
        p = P(v)
        if dl(p) > .12 * r or not band(p):
            continue
        d = (p - c).normalized()
        h = pbvh.ray_cast(p + d * (1.5 * r), -d, 3. * r)
        if h[0] is None or (h[0] - c).length > (p - c).length + .02 * r or (h[0] - p).length > .4 * r:
            continue
        dlt = Moi.to_3x3() @ (h[0] + d * (.002 * r) - p)
        v.co += dlt
        for lay in shapes_:
            v[lay] += dlt
        snapped += 1
        for e in v.link_edges:   # (the ring behind it half way: a slope, not a step - the step drew a dark line)
            w = e.other_vert(v)
            if w.is_boundary or w in patch:
                continue
            q_ = P(w)
            dq = (q_ - c).normalized()
            h2 = pbvh.ray_cast(q_ + dq * (1.5 * r), -dq, 3. * r)
            if h2[0] is None or (h2[0] - q_).length > .3 * r or (h2[0] - c).length > (q_ - c).length:
                continue
            d2 = Moi.to_3x3() @ ((h2[0] + dq * (.006 * r) - q_) * .5)
            w.co += d2
            for lay in shapes_:
                w[lay] += d2

    # ---------------------------------------------------------------- the vertices: weights, keys, places
    keys_here = {"eyeBlink", "eyeSquint", "eyeWide"}
    nameS = SIDE.get(sd, sd)
    new = []
    for k, row in enumerate(rings):
        vr = []
        for i, p in enumerate(row):
            v = bm.verts.new(Moi @ p)
            g, mv = field.at(p)
            for gi, wt in (g or {}).items():
                v[deform][gi] = wt
            patch.add(v)
            vr.append((v, p, mv))
        new.append(vr)
    # the keys: the face's own moves of the skin carried as far as a row is skin; this eye's lid keys its own
    opening = [elev(w - c) for w in wet]
    xs = [w.x for w in wet]

    def lid_at(up, x):   # the wet line's elevation at x on the upper / lower lid
        seq = sorted([(xs[i], opening[i]) for i in range(N) if (is_up[i] if up else (not is_up[i] or i in (0, NU)))])
        if x <= seq[0][0]:
            return seq[0][1]
        for (xa, ea), (xb, eb) in zip(seq, seq[1:]):
            if x <= xb:
                return ea + (eb - ea) * (x - xa) / max(xb - xa, 1e-12)
        return seq[-1][1]
    meet_k = float(job.get("lid_meet", .22))   # (where the lids meet: a share of the opening up from the lower lid)
    ex = float(job.get("lid_expressivity", 1.5))
    turn = {}   # key -> per column the lid's turn (+ = down for the upper / up for the lower: toward closing)
    for i in range(N):
        e_u, e_l = lid_at(True, xs[i]), lid_at(False, xs[i])
        op = max(0., e_u - e_l)
        meet = e_l + meet_k * op
        if i in (0, NU):
            cl = 0.
        elif is_up[i]:
            cl = opening[i] - meet + math.radians(1.)
        else:
            cl = meet - opening[i]
        turn.setdefault("eyeBlink", []).append(cl)
        turn.setdefault("eyeSquint", []).append(cl * .17 * ex if is_up[i] else (.18 * ex * op if i not in (0, NU) else 0.))
        turn.setdefault("eyeWide", []).append(-op * (.11 * ex if is_up[i] else .035 * ex) if i not in (0, NU) else 0.)

    def lid_share(k, i, key):
        up_s, lo_s = RINGS[k][4]
        s = .5 * (up_s + lo_s) if i in (0, NU) else (up_s if is_up[i] else lo_s)
        if key == "eyeWide" and RINGS[k][0] in ("crease", "fold"):
            s = min(1., s * 1.5)
        return s

    def ball_r(d):   # the ball's surface along a direction from its centre (its cornea bulges)
        if ball_bvh is None:
            return bulge
        h = ball_bvh.ray_cast(c + d * (3 * r), -d, 3 * r)
        return (h[0] - c).length if h[0] is not None else bulge

    def placed(k, i, key, f=1.):   # the vertex's place in a key (f of the way: the arc's middle at .5)
        v, p, mv = new[k][i]
        s = share(k, i)
        q = p - c
        a = turn[key][i] * lid_share(k, i, key) * f
        sg = -1. if is_up[i] or (i in (0, NU)) else 1.   # (upper: down, lower: up)
        q2 = rot_x(q, sg * a)
        # (over the cornea a closing lid stays clear of it: its rows lifted together, as far as its wet line needs)
        need = 0.
        if a != 0.:
            wq = rot_x(wet[i] - c, sg * a)
            need = max(0., 1.03 * ball_r(wq.normalized()) + .01 * r - wq.length) * (1. - s)
        p_lid = c + q2.normalized() * (q2.length + need)
        return p_lid

    for k, vr in enumerate(new):
        for i, (v, p, mv) in enumerate(vr):
            s = share(k, i)
            # every key of the face: the skin's move where it is skin
            for ki, nm in enumerate(field.keys):
                lay = shape.get(nm)
                if lay is None:
                    continue
                d = Vector(mv[ki]) if mv is not None else Vector()
                base_key = next((b for b in keys_here if nm == b + nameS), None)
                if base_key is not None:
                    pl = placed(k, i, base_key)
                    pos = p.lerp(pl, 1. - s) + d * s
                else:
                    pos = p + d * s
                v[lay] = Moi @ pos
            for nm, lay in shape.items():   # (keys made here: this side's lid keys if the face had none, the helper)
                if lay is None or nm in field.keys or nm == basis_name:
                    continue
                if nm == "eyeBlink" + nameS + "_arc":
                    end = placed(k, i, "eyeBlink")
                    mid = placed(k, i, "eyeBlink", .5)
                    v[lay] = Moi @ (p + (mid - (p + end) * .5))
                elif any(nm == b + nameS for b in keys_here):
                    b = next(b for b in keys_here if nm == b + nameS)
                    v[lay] = Moi @ p.lerp(placed(k, i, b), 1. - s)
                else:
                    v[lay] = Moi @ p
            if shape.get(basis_name) is not None:
                v[shape[basis_name]] = Moi @ p

    # ---------------------------------------------------------------- the faces
    TOP = len(RINGS) - 1   # (the texture's rows: the rings)
    pidx_k = {}
    y0, TH1, TW = block
    vv = lambda kk, ii: new[kk][ii % N][0]   # noqa: E731

    def uv_of(kk, ii):
        return Vector(((ii / N) * (TW - 8) / TW + 4 / TW, (y0 + 4 + (kk / TOP) * (TH1 - 8)) / (2 * TH1)))
    faces = []
    for k in range(len(RINGS) - 1):
        for i in range(N):
            try:
                f = bm.faces.new((vv(k, i), vv(k, i + 1), vv(k + 1, i + 1), vv(k + 1, i)))
            except ValueError:
                continue
            nm0 = RINGS[k][0]
            f.material_index = mats["eyelid_rim"] if nm0 in ("sleeve2", "sleeve1", "wet") else mats["eyelid_skin"]
            f.smooth = True
            pidx_k[f] = k
            for lp, (kk, ii) in zip(f.loops, ((k, i), (k, i + 1), (k + 1, i + 1), (k + 1, i))):
                lp[uvl].uv = uv_of(kk, ii)
            faces.append(f)
    # the winding: the lid's rows face out, away from the ball
    out_, in_ = 0, 0
    M3n = Mo.to_3x3().inverted().transposed()
    for f in faces:   # (a new face's normal is not there until it is computed: read as zero, nothing was ever turned)
        f.normal_update()
        k_ = pidx_k.get(f)
        if k_ is not None and IW + 1 <= k_ <= IW + 4:
            if (M3n @ f.normal).dot(Mo @ f.calc_center_median() - c) >= 0:
                out_ += 1
            else:
                in_ += 1
    flip = in_ > out_
    if flip:
        for f in faces:
            f.normal_flip()
    # ---------------------------------------------------------------- what the texture is baked from
    grid = [[new[k][i][1] for i in range(N)] for k in range(len(RINGS))]
    shares = [[share(k, i) for i in range(N)] for k in range(len(RINGS))]
    outline2 = [(p.x, p.z) for p in curve]
    report = {"columns": N, "rings": len(RINGS), "cut_faces": len(kill), "edge_snapped": snapped, "flipped": bool(flip),
              "clamped_corners": clamped, "bulge": round(bulge / r, 3)}
    return {"report": report, "grid": grid, "shares": shares, "block": (y0, TH1, TW), "N": N, "outline": outline2, "fine": fine, "c": c,
            "r": r, "crease": [k for k, x in enumerate(RINGS) if x[0] == "crease"][0], "is_up": is_up}


def _bake(b, src, tex, known):
    """the patch's texture block: per texel its place on the patch (rest), the face's colour there where the patch is
    skin away from the old opening (the source's painted lashes and eye are within ~0.3 r of it)"""
    y0, TH1, TW = b["block"]
    grid, shares, N, r = b["grid"], b["shares"], b["N"], b["r"]
    TOP = len(grid) - 1
    out2 = b["outline"]
    for py in range(TH1):
        vk = (py + .5 - 4) / (TH1 - 8) * TOP
        if vk < 0 or vk > TOP:
            continue
        k0 = min(TOP - 1, int(vk))
        t = vk - k0
        s_row = None
        for px in range(TW):
            ui = (px + .5 - 4) / (TW - 8) * N
            if ui < 0 or ui > N:
                continue
            i0 = min(N - 1, int(ui))
            u = ui - i0
            i1 = (i0 + 1) % N
            p = (grid[k0][i0] * (1 - u) + grid[k0][i1] * u) * (1 - t) + (grid[k0 + 1][i0] * (1 - u) + grid[k0 + 1][i1] * u) * t
            s = (shares[k0][i0] * (1 - u) + shares[k0][i1] * u) * (1 - t) + (shares[k0 + 1][i0] * (1 - u) + shares[k0 + 1][i1] * u) * t
            if s < .45:
                continue
            if seg_dist2(p.x, p.z, out2) < .34 * r:
                continue
            col = src.colour(p)
            if col is None:
                continue
            tex[y0 + py, px] = col
            known[y0 + py, px] = True


def _shade(blk, b):
    """the crease a little darker (a groove's shadow), the band by the margin a touch warmer"""
    y0, TH1, TW = b["block"]
    TOP = len(b["grid"]) - 1
    yy = (np.arange(TH1, dtype=np.float32) + .5 - 4) / (TH1 - 8) * TOP
    ck = b["crease"]
    up = np.array([1. if u else 0. for u in b["is_up"]], np.float32)
    xs = np.clip(((np.arange(TW, dtype=np.float32) + .5 - 4) / (TW - 8) * b["N"]).astype(int), 0, b["N"] - 1)
    upc = up[xs]
    dark = 1. - .22 * np.exp(-((yy - ck) / .55) ** 2)[:, None] * upc[None, :]
    warm = np.exp(-((yy - (IW + 1)) / 1.2) ** 2)[:, None]
    blk[...] = blk * dark[..., None]
    blk[..., 0] = blk[..., 0] * (1 + .06 * warm)
    blk[..., 2] = blk[..., 2] * (1 - .05 * warm)
