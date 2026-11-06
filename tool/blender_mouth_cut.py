"""Runs INSIDE Blender (background): cut a real mouth into a rigged closed-mouth head and fill it.

    blender -b -P blender_mouth_cut.py -- job.json

job.json: {"source": rigged.glb, "out": out.glb, "mouth_c", "corner_L", "corner_R": [x,y,z] glTF (surface points),
           "hinge": [x,y,z] glTF (jaw joint, optional), "head_bone", "jaw_bone" (optional), "teeth_glb", "tongue_glb",
           "kit": {"arch_width": 0.05}, "lip_colour": [r,g,b] (optional), "open_deg": 22, "preview": png, "report": json}

Recipe of the game's 3d-animator facial-rig.md §16, for gameplay distance:
1. cut exactly along the lip line (the parabola through the right corner, the centre and the left corner, front view):
   every front edge the line crosses is split at the crossing (UVs and skin weights interpolated), faces are joined
   along the line and the line edges are split open; the corners stay joined.
2. roll the lips inward: two rings from each slit edge back into the head, curling up into the upper lip and down
   into the lower, flat at the corners; the roll gets its own lip material.
3. one skinned cavity cup behind the lips (roof on the head, floor on the jaw, blended), dark inside.
4. the face-parts teeth and tongue scaled to the mouth width behind the lips: upper teeth + gum on the head, lower
   teeth + gum + tongue on the jaw.
5. shape keys with the mouth plate's names, so lip sync is the same: jawOpen = everything on the jaw turned about
   the hinge; mouthSmile, mouthStretch, mouthFunnel, mouthPucker, mouthUpperUp, mouthLowerDown move the lips (the
   one-sided ones split into ...Left / ...Right); cheekSquint / noseSneer Left and Right when the eyes are marked.
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bisect
import bpy
from mathutils import Matrix, Vector
sys.path.insert(0, str(Path(__file__).resolve().parent))   # Blender does not put the script's folder on the path
from i18n import t as _t

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))


def fail(msg):
    print("CUT_FAIL " + msg, flush=True)
    sys.exit(1)


def bl(p):
    return Vector((p[0], -p[2], p[1]))


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["source"])
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for o in list(bpy.data.objects):
    if o.type == "MESH" and (not o.vertex_groups or o.name.startswith("Mouth")):
        d = o.data
        bpy.data.objects.remove(o, do_unlink=True)
        bpy.data.meshes.remove(d)
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
HEAD, JAW = job["head_bone"], job.get("jaw_bone") or job["head_bone"]

M, CL, CR = bl(job["mouth_c"]), bl(job["corner_L"]), bl(job["corner_R"])
W = (CL - CR).length
if W <= 0:
    fail(_t("blender.the_mouth_has_zero_width"))
for c in (CL, CR):
    if abs(c.z - M.z) > 0.6 * W:
        fail(_t("blender.the_mouth_corners_are_not_on_the_lip"))
hinge = bl(job["hinge"]) if job.get("hinge") else Vector((M.x, M.y + 1.2 * W, M.z + 0.5 * W))
import numpy as np
def lip_curve(pts):
    """front-view lip line z(x) through all given points: parabola for 3, a Catmull-Rom curve (sampled densely, then
    interpolated) for 4+ points, so mid-lip clicks follow a cupid's bow or a sneer."""
    pts = sorted(pts, key=lambda p: p.x)
    xs_, zs_ = [p.x for p in pts], [p.z for p in pts]
    if len(pts) <= 3:
        c = np.polyfit(xs_, zs_, 2)
        return lambda x: float(np.polyval(c, x))
    ext = [pts[0] * 2 - pts[1]] + pts + [pts[-1] * 2 - pts[-2]]
    sx, sz = [], []
    for i in range(1, len(ext) - 2):
        p0, p1, p2, p3 = ext[i - 1], ext[i], ext[i + 1], ext[i + 2]
        for k in range(24):
            t = k / 24
            q = 0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3)
            sx.append(q.x); sz.append(q.z)
    sx.append(pts[-1].x); sz.append(pts[-1].z)
    order = np.argsort(sx)
    sx, sz = np.array(sx)[order], np.array(sz)[order]
    return lambda x: float(np.interp(x, sx, sz))


LIP_PTS = [CR, M, CL] + [bl(job[k]) for k in ("mid_L", "mid_R") if job.get(k)]
line_z = lip_curve(LIP_PTS)
x0, x1 = min(CR.x, CL.x), max(CR.x, CL.x)
cx = (x0 + x1) / 2


def side(p):
    return p.z - line_z(p.x)


front_limit = max(CL.y, CR.y) + 0.35 * W          # only the front skin around the mouth is cut (Blender: forward = -y)

face = max((o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups),
           key=lambda o: sum(1 for v in o.data.vertices if ((o.matrix_world @ v.co) - M).length < W))
fw, finv = face.matrix_world, face.matrix_world.inverted()
report = {"mouth_width": round(W, 4)}

# the skin before cutting: everything put inside the mouth must stay behind it
from mathutils.bvhtree import BVHTree
face.data.calc_loop_triangles()
_wv = [fw @ v.co for v in face.data.vertices]
skin_bvh = BVHTree.FromPolygons(_wv, [tuple(t.vertices) for t in face.data.loop_triangles])
_ymin = min(v.y for v in _wv)


def skin_y(x, z):
    """depth (Blender y) of the outer skin seen from the front at (x, z), or None"""
    h = skin_bvh.ray_cast(Vector((x, _ymin - W * 20, z)), Vector((0, 1, 0)), W * 80)
    return None if h[0] is None else h[0].y


# ------------------------------------------------------------------ 0. the seam: which lip each point is on
# The clicked line is where the lips meet seen from the front; inside they may meet elsewhere. On a mouth sculpted shut
# the upper lip's underside dips under the line before it turns into the head (women_young: on the jaw's side of a
# plane through the line, it went down with the jaw and stood as a brown jagged shelf on the lower lip), and a line
# clicked a little high leaves a strip of the upper lip to the lower one. Two walks over the skin (points welded by
# place: glTF splits them on UV seams), from the upper lip's front and from the lower's (0.12 W off the line, across
# the mouth), give each point near the mouth the lip it is nearer to along the surface. Where that disagrees with the
# line near the cut, the point goes to that lip's side. side() is from here on "which side of the seam": the cut goes
# round the fold and leaves it with the upper lip, and every later step (weights, lip bones, keys) sees it so.
# (Moving the fold over to the upper lip after the cut instead - its faces on the upper edge's twins, its motion in
# the keys taken from that edge - stretched it on man-young, whose upper edge partly goes with the jaw.)
side_line = side
SEAM_ON = bool(job.get("seam_follow", True)) and not (job.get("face_topo") or job.get("oval_mesh"))
SP = [side_line(p) for p in _wv]   # per source point: the side it goes to
_seam_moved = 0
if SEAM_ON:
    import heapq
    _me = face.data
    _q = W * 1e-4
    _node, _np, _vn = {}, [], []
    for p in _wv:
        k_ = (round(p.x / _q), round(p.y / _q), round(p.z / _q))
        if k_ not in _node:
            _node[k_] = len(_np); _np.append(p)
        _vn.append(_node[k_])
    _half = (x1 - x0) / 2
    _reg = lambda p: abs(p.x - cx) < 1.6 * _half and abs(p.z - M.z) < 1.0 * W and p.y < M.y + 2.5 * W
    _adj = {}
    for e in _me.edges:
        a_, b_ = _vn[e.vertices[0]], _vn[e.vertices[1]]
        if a_ != b_ and _reg(_np[a_]) and _reg(_np[b_]):
            d_ = (_np[a_] - _np[b_]).length
            _adj.setdefault(a_, []).append((b_, d_)); _adj.setdefault(b_, []).append((a_, d_))

    def _seeds(dz):
        out = set()
        for i in range(41):
            x = x0 + (0.08 + 0.84 * i / 40) * (x1 - x0)
            h = skin_bvh.ray_cast(Vector((x, _ymin - 20 * W, line_z(x) + dz)), Vector((0, 1, 0)), 80 * W)
            if h[0] is not None:
                tri = _me.loop_triangles[h[2]]
                out.add(min((_vn[i_] for i_ in tri.vertices), key=lambda n: (_np[n] - h[0]).length))
        return out

    def _walk(src):
        dist = {s_: 0.0 for s_ in src}; hq = [(0.0, s_) for s_ in src]
        while hq:
            d_, n = heapq.heappop(hq)
            if d_ > dist.get(n, 1e18):
                continue
            for m, w in _adj.get(n, []):
                nd = d_ + w
                if nd < dist.get(m, 1e18):
                    dist[m] = nd; heapq.heappush(hq, (nd, m))
        return dist
    _du, _dd = _walk(_seeds(0.12 * W)), _walk(_seeds(-0.12 * W))
    for vi, p in enumerate(_wv):
        a_, b_ = _du.get(_vn[vi]), _dd.get(_vn[vi])
        if a_ is None or b_ is None:
            continue
        sf = (b_ - a_) / 2          # > 0: nearer the upper lip along the skin
        if p.y < front_limit + 0.15 * W and abs(p.x - cx) < 1.05 * _half and abs(sf) > 0.01 * W \
                and (sf > 0) != (SP[vi] > 0):
            SP[vi] = math.copysign(max(abs(SP[vi]), 0.006 * W), sf); _seam_moved += 1
    report["seam_points_moved"] = _seam_moved


def _side_from(pairs):
    """side() looked up: the nearest point's side (exact on the mesh's own points), the line's away from them"""
    from mathutils.kdtree import KDTree
    kd = KDTree(len(pairs))
    for i, (p, _) in enumerate(pairs):
        kd.insert(p, i)
    kd.balance()
    vals = [v for _, v in pairs]

    def f(p):
        co, i, d = kd.find(p)
        return side_line(p) if i is None or d > 0.1 * W else vals[i]
    return f


if _seam_moved:
    side = _side_from(list(zip(_wv, SP)))


# ------------------------------------------------------------------ 1. cut along the line
bm = bmesh.new(); bm.from_mesh(face.data)
# which lip a point is on, for the lip bones (step 4b): the layer is made now, before any vertex is held - a layer
# added later frees every BMVert the script holds (the slit's copies died and the lip roll found no edge to roll)
LIP_SIDE = bm.verts.layers.int.get("lip_side") or bm.verts.layers.int.new("lip_side")
SS = bm.verts.layers.float.get("seam_side") or bm.verts.layers.float.new("seam_side")   # step 0: each point's side
SEAM_UP = bm.verts.layers.int.get("seam_up") or bm.verts.layers.int.new("seam_up")   # 1 given to the upper lip, 2 its edge
dl = bm.verts.layers.deform.verify()
bm.verts.ensure_lookup_table()
for v in bm.verts:
    v[SS] = SP[v.index]
    v[SEAM_UP] = 1 if SP[v.index] > 0 and side_line(_wv[v.index]) <= 0 else 0
# a point's side: from the seam's layer when the seam moved any (the cut's own points are given 0 there); else, as
# before, by where it is (the rebuilt face mask's points have no value in the layer: read as 0, they found no
# neighbours to take weights from, and fairy's lower lip opened in a notch)
sv = (lambda v: v[SS]) if _seam_moved else (lambda v: side(P(v)))
P = lambda v: fw @ v.co
gi = {g.name: g.index for g in face.vertex_groups}
if HEAD not in gi:
    fail(_t("blender.the_face_has_no_head_weight") + HEAD)
if JAW not in gi:
    face.vertex_groups.new(name=JAW); gi[JAW] = face.vertex_groups[JAW].index


def in_zone(p):
    return x0 + W * 0.01 < p.x < x1 - W * 0.01 and p.y < front_limit and abs(side(p)) < 0.35 * W



FACE_TOPO = bool(job.get("face_topo") and job.get("eye_L") and job.get("eye_R"))
OVAL = FACE_TOPO or bool(job.get("oval_mesh") and job.get("lip_top") and job.get("lip_bot"))   # oval: experimental
CORNERS = set()


def oval_remesh():
    """Replace the old triangles around the mouth by clean ring topology fitted to the oval (slit, lip edge, outer
    loop, deformation zone, boundary), zipped to the rest of the face. Positions, skin weights and materials come
    from the old surface under each point; UVs per face from one UV island (the face centre's), so a UV seam through
    the mouth does not smear the texture. The slit is two vertex chains (upper / lower lip), joined at the corners."""
    import mathutils.geometry as G
    from mathutils.bvhtree import BVHTree as BT
    me = face.data
    tris = list(me.loop_triangles)
    uv_data = me.uv_layers.active.data if me.uv_layers.active else None
    # UV islands of the loop triangles
    parent = list(range(len(tris)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]; i = parent[i]
        return i
    edges = {}
    for ti, t in enumerate(tris):
        for a_, b_ in ((0, 1), (1, 2), (2, 0)):
            va, vb = t.vertices[a_], t.vertices[b_]
            ua = tuple(round(c, 5) for c in uv_data[t.loops[a_]].uv) if uv_data else (0, 0)
            ub = tuple(round(c, 5) for c in uv_data[t.loops[b_]].uv) if uv_data else (0, 0)
            key = (min(va, vb), max(va, vb))
            uvk = (ua, ub) if va < vb else (ub, ua)
            for tj, uvj in edges.get(key, []):
                if uvj == uvk:
                    ra, rb = find(ti), find(tj)
                    if ra != rb:
                        parent[ra] = rb
            edges.setdefault(key, []).append((ti, uvk))
    isl = [find(i) for i in range(len(tris))]
    by_isl = {}
    for ti, k in enumerate(isl):
        by_isl.setdefault(k, []).append(ti)
    wv = [fw @ v.co for v in me.vertices]
    isl_bvh = {k: (BT.FromPolygons(wv, [tuple(tris[t].vertices) for t in ts]), ts) for k, ts in by_isl.items() if len(ts) > 0}
    gnames = {g.index: g.name for g in face.vertex_groups}

    def bary(tri, p):
        a_, b_, c_ = (wv[i] for i in tri.vertices)
        return G.barycentric_transform(p, a_, b_, c_, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))

    def project(x, z):
        h = skin_bvh.ray_cast(Vector((x, _ymin - W * 20, z)), Vector((0, 1, 0)), W * 80)
        if h[0] is None:
            fail(_t("blender.no_skin_under_the_mouth_oval_at", x, z))
        return h[0], h[2]

    def weights_at(p, ti):
        b = bary(tris[ti], p); out = {}
        for wgt, vi in zip(b, tris[ti].vertices):
            for g in me.vertices[vi].groups:
                out[g.group] = out.get(g.group, 0.0) + max(0.0, wgt) * g.weight
        tot = sum(out.values()) or 1.0
        return {k: w / tot for k, w in out.items() if w / tot > 1e-3}

    def uv_in(p, island):
        bvh, ts = isl_bvh[island]
        loc, _, li, _ = bvh.find_nearest(p)
        t = tris[ts[li]]
        b = bary(t, loc)
        u = sum(bb * uv_data[l].uv.x for bb, l in zip(b, t.loops)); v = sum(bb * uv_data[l].uv.y for bb, l in zip(b, t.loops))
        return (u, v)

    T_, B_ = bl(job["lip_top"]), bl(job["lip_bot"])
    half = (x1 - x0) / 2
    hu = max(W * 0.02, T_.z - line_z(T_.x)); hl = max(W * 0.02, line_z(B_.x) - B_.z)
    RINGS = [(1.0, 0.0), (1.04, 1.0), (1.14, 1.5), (1.28, 2.0), (1.42, 2.5)]   # same as the editor's OVAL_RINGS
    N = 32
    HU = max(hu * 1.2, bl(job["limit_top"]).z - line_z(cx)) if job.get("limit_top") else 0.0

    def ring_up(h_):   # editor's ringUp: spread between the lip edge and the limit under the nose
        if h_ <= 1 or not HU:
            return hu * h_
        return hu + (HU - hu) * (h_ - 1) / (RINGS[-1][1] - 1)

    def pt2(k, i):
        a_, h_ = RINGS[k]; th = 2 * math.pi * i / N
        x = cx + half * a_ * math.cos(th); sn = math.sin(th)
        return x, line_z(x) + (ring_up(h_) if sn >= 0 else hl * h_) * sn

    # 1) delete the old faces inside the outer ring
    poly4 = [pt2(4, i) for i in range(N)]

    def inside(poly, x, z):
        c = False; j = len(poly) - 1
        for i in range(len(poly)):
            xi, zi = poly[i]; xj, zj = poly[j]
            if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi:
                c = not c
            j = i
        return c
    lim = front_limit + 0.3 * W
    def on_outer_skin(c):   # the first skin seen from the front at this point (no depth limit: cheeks turn away)
        sy = skin_y(c.x, c.z)
        return sy is not None and c.y < sy + 0.08 * W
    # a face goes when any of its corners is inside the outer ring: then the hole's rim is all outside ring 4 and the
    # seam strip only runs outward (rim points inside it folded the seam over the new patch)
    kill = [f for f in bm.faces if on_outer_skin(fw @ f.calc_center_median())
            and any(inside(poly4, (fw @ v.co).x, (fw @ v.co).z) for v in f.verts)]
    hole_verts = {v for f in kill for v in f.verts}   # the hole's rim = old vertices that touched a deleted face
    ks = set(kill)
    from mathutils.kdtree import KDTree as _KD
    _mids = [fw @ ((e.verts[0].co + e.verts[1].co) / 2) for f in kill for e in f.edges]
    kill_mid = _KD(len(_mids))
    for _i, _m in enumerate(_mids):
        kill_mid.insert(_m, _i)
    kill_mid.balance()
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    report["oval_deleted_faces"] = len(kill)
    # 2) ring vertices
    info = {}

    def new_vert(x, z):
        loc, ti = project(x, z)
        v = bm.verts.new(finv @ loc)
        for gk, w in weights_at(loc, ti).items():
            v[dl][gk] = w
        info[v] = ti
        return v
    U = [new_vert(*pt2(0, i)) for i in range(N // 2 + 1)]
    D = {N // 2: U[N // 2], N: U[0]}
    for i in range(N // 2 + 1, N):
        D[i] = new_vert(*pt2(0, i))
    R = {k: [new_vert(*pt2(k, i)) for i in range(N)] for k in range(1, 5)}
    uvl = bm.loops.layers.uv.verify()
    new_faces = []

    def make(vs):
        if len(set(vs)) < len(vs):
            report["oval_degenerate"] = report.get("oval_degenerate", 0) + 1
            return None
        try:
            f = bm.faces.new(vs)
        except ValueError:
            report["oval_face_fail"] = report.get("oval_face_fail", 0) + 1
            return None
        c = sum((P(v) for v in vs), Vector()) / len(vs)
        loc, ti = project(c.x, c.z)
        f.material_index = me.polygons[tris[ti].polygon_index].material_index
        f.smooth = True
        if uv_data:
            for l in f.loops:
                l[uvl].uv = uv_in(P(l.vert), isl[ti])
        new_faces.append(f)
        return f
    for i in range(N // 2):
        make([U[i], U[i + 1], R[1][i + 1], R[1][i]])
    for i in range(N // 2, N):
        make([D[i], D[i + 1], R[1][(i + 1) % N], R[1][i]])
    for k in range(1, 4):
        for i in range(N):
            make([R[k][i], R[k][(i + 1) % N], R[k + 1][(i + 1) % N], R[k + 1][i]])
    # 3) zip ring 4 to the hole's boundary (twins on UV seams grouped by position)
    def ell_angle(p):
        sn = (p.z - line_z(p.x)) / (ring_up(RINGS[4][1]) if p.z >= line_z(p.x) else hl * RINGS[4][1])
        return math.atan2(sn, (p.x - cx) / (half * RINGS[4][0])) % (2 * math.pi)
    # rim of the hole as a chain of edges (UV-seam twins merged by position), walked in order: sorting the rim by
    # angle zig-zags on an irregular Tripo rim and folds the seam triangles
    q = W * 1e-3
    kof = lambda v: tuple(round(c / q) for c in P(v))
    verts_of, adj = {}, {}
    for e in bm.edges:   # open edges lying where a deleted face's edge was (incl. the other side of a UV seam)
        if not e.is_boundary or e.link_faces[0] in new_faces:
            continue
        mid = fw @ ((e.verts[0].co + e.verts[1].co) / 2)
        if kill_mid.find(mid)[2] > W * 2e-3:
            continue
        va, vb = e.verts
        ka, kb = kof(va), kof(vb)
        if ka == kb:
            continue
        verts_of.setdefault(ka, set()).add(va); verts_of.setdefault(kb, set()).add(vb)
        adj.setdefault(ka, set()).add(kb); adj.setdefault(kb, set()).add(ka)
    if len(adj) < 8:
        fail(_t("blender.could_not_find_the_edge_of_the_cut"))
    comps, seen_c = [], set()
    for k0 in adj:
        if k0 in seen_c:
            continue
        st, comp = [k0], []
        seen_c.add(k0)
        while st:
            k = st.pop(); comp.append(k)
            for k2 in adj[k]:
                if k2 not in seen_c:
                    seen_c.add(k2); st.append(k2)
        comps.append(comp)
    report["oval_rim_components"] = sorted((len(c) for c in comps), reverse=True)[:6]
    report["oval_rim_degrees"] = sorted({len(v) for v in adj.values()})
    # the longest closed walk: start anywhere, always go to an unvisited neighbour (the rim nearest the mouth wins)
    best = []
    for start in list(adj)[:12]:
        loop, seen, cur, prev = [start], {start}, start, None
        while True:
            nxt = [k for k in adj[cur] if k != prev and k not in seen]
            if not nxt:
                break
            nxt.sort(key=lambda k: (P(next(iter(verts_of[k]))) - M).length)
            prev, cur = cur, nxt[0]
            loop.append(cur); seen.add(cur)
        if len(loop) > len(best):
            best = loop
    outer = [verts_of[k] for k in best]
    pos = [P(next(iter(vs))) for vs in outer]
    # same turning direction as ring 4 (front view x-z), start at the rim point nearest ring 4's first vertex
    def area(pts):
        return sum(a_.x * b_.z - b_.x * a_.z for a_, b_ in zip(pts, pts[1:] + pts[:1]))
    inner = R[4]
    if (area(pos) > 0) != (area([P(v) for v in inner]) > 0):
        outer.reverse(); pos.reverse()
    j0 = min(range(len(pos)), key=lambda j: (pos[j] - P(inner[0])).length)
    outer = outer[j0:] + outer[:j0]; pos = pos[j0:] + pos[:j0]
    n, m = N, len(outer)
    seg = [(pos[(j + 1) % m] - pos[j]).length for j in range(m)]
    tot = sum(seg) or 1.0
    oa, acc = [], 0.0
    for d in seg:
        oa.append(acc / tot); acc += d
    ia = [i / n for i in range(n)]
    i = j = 0
    while i < n or j < m:
        ni = ia[i + 1] if i + 1 < n else 1.0
        nj = oa[j + 1] if j + 1 < m else 1.0
        a_v, o_v = inner[i % n], next(iter(outer[j % m]))
        if j >= m or (i < n and ni <= nj):
            make([a_v, inner[(i + 1) % n], o_v]); i += 1
        else:
            make([a_v, next(iter(outer[(j + 1) % m])), o_v]); j += 1
    report["oval_rim_open_points"] = len(adj) - m
    report["oval_boundary_points"] = m
    # 4) faces toward the viewer
    # one consistent winding over the new patch (as the old mesh around it), then flip all if most face inward
    nf = [f for f in new_faces if f.is_valid]
    bmesh.ops.recalc_face_normals(bm, faces=nf)
    votes = 0
    for f in nf:
        f.normal_update()
        h = skin_bvh.find_nearest(fw @ f.calc_center_median())
        if h[1] is not None:
            votes += 1 if (fw.to_3x3() @ f.normal).dot(h[1]) > 0 else -1
    if votes < 0:
        for f in nf:
            f.normal_flip()
    report["oval_orientation_votes"] = votes
    bm.normal_update()
    CORNERS.update({U[0], U[N // 2]})
    return U[1:N // 2], [D[i] for i in range(N // 2 + 1, N)], set(U) | set(D.values())


if not OVAL:
    cross = []
    for e in bm.edges:
        a, b = P(e.verts[0]), P(e.verts[1])
        sa, sb = sv(e.verts[0]), sv(e.verts[1])
        if sa * sb < 0 and (in_zone(a) or in_zone(b)):
            t = sa / (sa - sb)
            q = a.lerp(b, t)
            if x0 + W * 0.01 < q.x < x1 - W * 0.01 and q.y < front_limit:
                cross.append((e, t))
    new_verts = set()
    for e, t in cross:
        v0 = e.verts[0]
        ne, nv = bmesh.utils.edge_split(e, v0, t)
        nv[SS] = 0.0
        new_verts.add(nv)
    for v in bm.verts:   # original vertices lying on the line itself are cut points too (else their faces bridge the slit)
        p = P(v)
        if abs(sv(v)) < W * 0.004 and in_zone(p):
            new_verts.add(v)
    report["crossed_edges"] = len(cross)
    if len(new_verts) < 6:
        fail(_t("blender.the_mouth_line_crossed_only_edges", len(new_verts)))
    bm.faces.ensure_lookup_table()
    line_edges = set()
    for f in list(bm.faces):
        nv = [v for v in f.verts if v in new_verts]
        if len(nv) > 2:
            nv = max(((x, y) for i, x in enumerate(nv) for y in nv[i + 1:]), key=lambda ab: (P(ab[0]) - P(ab[1])).length)
            nv = list(nv)
        if len(nv) == 2 and not any(nv[1] in e.verts for e in nv[0].link_edges):
            r = bmesh.ops.connect_verts(bm, verts=nv)
            for e in r["edges"]:
                line_edges.add(e)
    report["line_edges"] = len(line_edges)
    # second pass: faces that still span the slit (one of their on-line points was missed, near the corners) are cut
    # through their own on-line vertices
    second = 0
    for f in list(bm.faces):
        if not f.is_valid:
            continue
        ps = [P(v) for v in f.verts]
        sd = [sv(v) for v in f.verts]
        if not (max(sd) > W * 0.004 and min(sd) < -W * 0.004 and all(q.y < front_limit for q in ps)
                and x0 < sum(q.x for q in ps) / len(ps) < x1):
            continue
        on = [v for v, d in zip(f.verts, sd) if abs(d) < W * 0.004]
        for v in on:
            new_verts.add(v)
        if len(on) == 1:   # the line goes through one vertex and crosses the opposite edge: split that edge too
            for e in list(f.edges):
                if on[0] in e.verts:
                    continue
                sa_, sb_ = sv(e.verts[0]), sv(e.verts[1])
                if sa_ * sb_ < 0:
                    _, nv_ = bmesh.utils.edge_split(e, e.verts[0], sa_ / (sa_ - sb_))
                    nv_[SS] = 0.0
                    new_verts.add(nv_)
                    on.append(nv_)
                    break
        if len(on) >= 2:
            a_, b_ = on[0], on[-1]
            shared = next((e for e in a_.link_edges if b_ in e.verts), None)
            if shared is not None:
                line_edges.add(shared)
            else:
                for e in bmesh.ops.connect_verts(bm, verts=[a_, b_])["edges"]:
                    line_edges.add(e)
            second += 1
    report["second_pass_faces"] = second
    for e in bm.edges:
        if all(v in new_verts for v in e.verts) and all(abs(sv(v)) < W * 0.004 for v in e.verts):
            line_edges.add(e)
    res = bmesh.ops.split_edges(bm, edges=[e for e in line_edges if e.is_valid])
    # classify the copies on the line: upper lip or lower lip, from their faces
    bm.verts.ensure_lookup_table()
    on_line = [v for v in bm.verts if (abs(sv(v)) < W * 0.004 and in_zone(P(v))) or v in new_verts]
    upper, lower = [], []
    for v in set(on_line):
        if not v.link_faces:
            continue
        # by the seam's sides of its faces' points off the line (a face's centre fell either side of the seam)
        vals = [sv(o) for f in v.link_faces for o in f.verts if abs(sv(o)) >= W * 0.004]
        if vals:
            (upper if sum(vals) > 0 else lower).append(v)
        else:
            c = sum((fw @ f.calc_center_median() for f in v.link_faces), Vector()) / len(v.link_faces)
            (upper if side(c) > 0 else lower).append(v)
    if _seam_moved:   # the cut's own points in the lookup too (on the seam)
        side = _side_from([(P(v), sv(v)) for v in bm.verts])
        _lo_ = set(lower)
        for v in bm.verts:   # the cut's copies took the mark of the point they came from: only points off it keep it
            if v[SEAM_UP] == 1 and (sv(v) < W * 0.004 or v in new_verts or v in _lo_):
                v[SEAM_UP] = 0
        for v in upper:
            v[SEAM_UP] = 2
else:
    if FACE_TOPO:   # the whole face mask rebuilt (tool/face_topo.py), slit included
        sys.path.insert(0, str(Path(__file__).resolve().parent))
        import face_topo
        upper, lower, _corners, new_verts = face_topo.build(dict(
            bm=bm, dl=dl, face=face, fw=fw, finv=finv, skin_bvh=skin_bvh, skin_y=skin_y, W=W, cx=cx, line_z=line_z,
            x0=x0, x1=x1, M=M, job=job, bl=bl, report=report, fail=fail))
        CORNERS.update(_corners)
    else:
        upper, lower, new_verts = oval_remesh()
    report['oval'] = True


def copy_weights(v, from_side):
    """weights of the nearest connected neighbour on the given side (the cut verts must not mix head and jaw)"""
    best, bd = None, 1e9
    for e in v.link_edges:
        o = e.other_vert(v)
        sp = sv(o)
        if (sp > 0) == (from_side > 0) and abs(sp) > W * 1e-4:
            d = (P(o) - P(v)).length
            if d < bd:
                best, bd = o, d
    if best is not None:
        v[dl].clear()
        for k, w in best[dl].items():
            v[dl][k] = w


if not OVAL:
    # faces the line crossed through a vertex stay joined across the slit and stretch into a rod when the jaw opens
    bridge = []
    for f in bm.faces:
        ps = [P(v) for v in f.verts]
        if all(in_zone(p) for p in ps) and max(sv(v) for v in f.verts) > W * 0.004 and min(sv(v) for v in f.verts) < -W * 0.004             and abs(sum(p.x for p in ps) / len(ps) - cx) < (x1 - x0) / 2 - 0.08 * W:
            bridge.append(f)
    bmesh.ops.delete(bm, geom=bridge, context="FACES")
    report["bridge_faces_removed"] = len(bridge)

# the mouth the source has inside (a model sculpted with the lips a little apart: their inner sides, joined upper to
# lower behind the slit): the cut goes through the outer skin only, so that joint stayed whole and stretched into
# strips across the open mouth. Its faces near the slit go - behind the outer skin there, between the corners -; the
# roll, the cavity and the teeth of the steps below take their place.
inner = []
_mats = face.data.materials
for f in bm.faces:   # the source's own skin only: a rebuilt face mask lies a little inside the old lips and is not it
    _m = _mats[f.material_index] if f.material_index < len(_mats) else None
    if _m and _m.name.startswith(("lip_inner", "face_mask")):
        continue
    c = fw @ f.calc_center_median()
    if abs(c.x - cx) > (x1 - x0) / 2 + 0.04 * W or abs(side(c)) > 0.15 * W or c.y > M.y + 0.9 * W:
        continue
    sy = skin_y(c.x, c.z)   # the outer skin seen from the front there (the lips)
    if sy is None or c.y < sy + 0.03 * W:
        continue
    ps = [P(v) for v in f.verts]
    if max(sv(v) for v in f.verts) > -0.002 * W and min(sv(v) for v in f.verts) < 0.002 * W:   # it reaches across the slit
        inner.append(f)
bmesh.ops.delete(bm, geom=inner, context="FACES_ONLY")   # (the vertices stay: the slit's lists still name some)
report["inner_mouth_faces_removed"] = len(inner)
# deeper in, the source's mouth inside (its cheeks' inner sides, 0.35 W and more behind the lips, near the slit's
# height) need not reach across the slit to show: half on the head, half on the jaw, they stretched into thin strips
# beside the teeth as the mouth opened. They go too; the cavity, the gums and the tongue are there
deep = []
for f in bm.faces:
    _m = _mats[f.material_index] if f.material_index < len(_mats) else None
    if _m and _m.name.startswith(("lip_inner", "face_mask")):
        continue
    c = fw @ f.calc_center_median()
    # a band about the slit, reaching up only 0.12 W: above it, under a big low nose, the skin lies as deep behind the
    # nose's tip and its faces went too (holes under goblin_hero_2's nose)
    # below the slit 1.25 W deep: the source's mouth floor about 1 W behind the lips, half on the jaw, stretched into
    # grey teeth hanging in the open mouth (women_young); above it the palate stays still and stays
    if abs(c.x - cx) > (x1 - x0) / 2 + 0.04 * W or not -0.3 * W < side(c) < 0.12 * W \
            or c.y > M.y + (1.25 if side(c) < 0 else 0.9) * W:
        continue
    sy = skin_y(c.x, c.z)
    if sy is not None and c.y > sy + 0.35 * W and all(P(v).y > sy + 0.25 * W for v in f.verts):
        deep.append(f)
bmesh.ops.delete(bm, geom=deep, context="FACES_ONLY")
report["deep_inner_faces_removed"] = len(deep)
# a face holding a vertex of the upper lip's slit side and one of the lower's spans the slit, wherever the line runs
# (lips meeting a little above the clicked line left such a face whole: it stretched into a strip)
_up, _lo = {v for v in upper if v.is_valid}, {v for v in lower if v.is_valid}
across = [f for f in bm.faces if any(v in _up for v in f.verts) and any(v in _lo for v in f.verts)
          and not any(v in CORNERS for v in f.verts)]   # at the corners the lips meet: those stay
bmesh.ops.delete(bm, geom=across, context="FACES_ONLY")
report["slit_spanning_faces_removed"] = len(across)
upper = [v for v in upper if v.is_valid]; lower = [v for v in lower if v.is_valid]
for v in upper:
    copy_weights(v, 1)
for v in lower:
    copy_weights(v, -1)
report["lip_verts"] = {"upper": len(upper), "lower": len(lower)}
# the upper lip belongs to the head: any jaw weight above the slit (seen on UV-seam twins) goes to the head
hj, jj = gi[HEAD], gi[JAW]
upper_set = set(upper)   # the upper copies on the slit too: on a UV seam they may have no upper neighbour to copy
fixed = 0
if HEAD != JAW:
    for v in bm.verts:
        p = P(v)
        if (v in upper_set) or (side(p) > W * 0.004 and abs(p.x - cx) < 0.55 * (x1 - x0) and p.y < front_limit and side(p) < 0.6 * W):
            w = v[dl].get(jj, 0.0)
            if w > 0:
                v[dl][hj] = v[dl].get(hj, 0.0) + w
                del v[dl][jj]
                fixed += 1
report["upper_lip_jaw_cleared"] = fixed
# smooth the jaw weight below the lower lip and beside the corners (the chin underside sheared into fins when the
# weight dropped fast toward the neck); the slit copies keep theirs. Neighbours include UV-seam twins.
if HEAD != JAW:
    from collections import defaultdict
    twins = defaultdict(list)
    q = W * 1e-3
    for v in bm.verts:
        twins[tuple(round(c / q) for c in v.co)].append(v)
    keep = set(upper) | set(lower)
    zone = [v for v in bm.verts if v not in keep and (P(v) - M).length < 2.2 * W and side(P(v)) < 0.6 * W]
    for _ in range(12):
        new = {}
        for v in zone:
            nb = [e.other_vert(v) for e in v.link_edges]
            for t in twins[tuple(round(c / q) for c in v.co)]:
                if t is not v:
                    nb += [e.other_vert(t) for e in t.link_edges]
            if not nb:
                continue
            avg = sum(n[dl].get(jj, 0.0) for n in nb) / len(nb)
            new[v] = 0.5 * v[dl].get(jj, 0.0) + 0.5 * avg
        for v, w in new.items():
            if side(P(v)) > 0 and abs(P(v).x - cx) < 0.55 * (x1 - x0):
                continue     # never give the upper lip a jaw weight
            old = v[dl].get(jj, 0.0)
            if abs(w - old) < 1e-6:
                continue
            v[dl][jj] = w
            v[dl][hj] = max(0.0, v[dl].get(hj, 0.0) - (w - old))
    report["jaw_smoothed_verts"] = len(zone)
    # the lower lip itself goes fully with the jaw (fading over 0.35 W below the slit), so the mouth opens wide. Across
    # the mouth the opening is an oval: the jaw's weight goes as sqrt(1 - u^2) (the lip's edge an ellipse's arc) and
    # fades only right at the corners (0.2 W). (1 - u^2) with a 0.35 W fade opened a V: the middle dropped, the sides
    # stayed up and the lower lip looked pulled down into a point
    def open_profile(p):
        u = min(1.0, abs(p.x - cx) / (0.5 * (x1 - x0)))
        dc = min(1.0, min((p - CL).length, (p - CR).length) / (0.2 * W))
        return math.sqrt(max(0.0, 1 - u * u)) * dc * dc * (3 - 2 * dc)
    lips = 0
    lower_set = set(lower)   # the lower copies on the slit lie on the line itself: half of them a hair above it were
    for v in bm.verts:       # left out, kept the head's weight taken from the inside of the mouth, and the roll made
        p = P(v); d = max(0.0, -side(p)) if v in lower_set else -side(p)   # of them stayed while the jaw opened
        if v not in upper_set and 0 <= d < 0.6 * W and abs(p.x - cx) < 0.5 * (x1 - x0) and p.y < front_limit:
            target = (1.0 - max(0.0, (d - 0.35 * W) / (0.25 * W))) * open_profile(p)   # near a corner soft: it stretches
            old = v[dl].get(jj, 0.0)
            # the lip itself (0.3 W from the slit) takes the smooth field as it is: the source's own weights there
            # went up and down between neighbours, and the small triangles along the slit turned over into shards
            # as the jaw opened; further down the larger of the two, fading into the source's own
            k = min(1.0, max(0.0, (d - 0.3 * W) / (0.15 * W)))
            want = target if k <= 0 else (1 - k) * target + k * max(target, old)
            if abs(want - old) > 1e-5:
                v[dl][jj] = want
                v[dl][hj] = max(0.0, v[dl].get(hj, 0.0) + (old - want))
                lips += 1
    report["lower_lip_full_jaw"] = lips
    # which lip a point near the slit belongs to: over the mesh, the nearer slit edge (its upper or lower copies;
    # the cut parted them). By position alone the lower lip's top behind the slit edge (and the lips' inner sides,
    # the source's mouth curling in) lies above the clicked line and was given to the head: its neighbours turned
    # with the jaw and the inside of the lower lip shredded into shards as the mouth opened. Every point of that band
    # (and of the inner sides behind the skin) now gets its lip's smooth field: the upper none, the lower the same as
    # the lower lip's skin, then evened out.
    import heapq
    walls = set()
    for v in bm.verts:
        if v in upper_set or v in lower_set:
            continue
        p = P(v)
        if abs(p.x - cx) > 0.6 * (x1 - x0) or abs(side(p)) > 0.4 * W or p.y > M.y + 1.0 * W:
            continue
        if abs(side(p)) < 0.25 * W:
            walls.add(v)
            continue
        sy = skin_y(p.x, p.z)
        if sy is not None and p.y > sy + 0.02 * W:
            walls.add(v)

    lower_field = open_profile   # the lower lip's jaw weight by place (as for its skin above)

    if walls:
        twin_of = lambda v: twins[tuple(round(c / q) for c in v.co)]
        best, heap, cnt = {}, [], 0   # point -> (distance over the mesh, lower lip?)
        for v in list(upper_set) + list(lower_set):
            # a point joined to both lips' copies is a corner (the lips meet there): it says nothing of which lip;
            # taken for the upper, the lower lip's end round it stayed on the head
            if v.is_valid and not (v in CORNERS or any(e.other_vert(v) in (upper_set if v in lower_set else lower_set) for e in v.link_edges)):
                best[v] = (0.0, v in lower_set)
                heap.append((0.0, cnt, v)); cnt += 1
        heapq.heapify(heap)
        while heap:
            d0, _, v = heapq.heappop(heap)
            if d0 > best[v][0] + 1e-12 or d0 > 0.6 * W:
                continue
            # UV-seam twins join the band, but never across the slit (its upper and lower copies share places)
            nbs = [(e.other_vert(v), e.calc_length()) for e in v.link_edges] + \
                  ([(t, 0.0) for t in twin_of(v) if t is not v] if v in walls else [])
            for o, ln in nbs:
                if o not in walls:
                    continue
                nd = d0 + ln
                if o not in best or nd < best[o][0] - 1e-12:
                    best[o] = (nd, best[v][1]); heapq.heappush(heap, (nd, cnt, o)); cnt += 1
        got = {}
        for v in walls:
            if v in best:
                p = P(v); d = max(0.0, -side(p))
                fade = 1.0 - max(0.0, (d - 0.35 * W) / (0.25 * W)) if not (sy_ := skin_y(p.x, p.z)) or p.y <= sy_ + 0.02 * W else 1.0
                got[v] = lower_field(p) * max(0.0, fade) if best[v][1] else 0.0
        lip_of = {v: best[v][1] for v in got}
        # evened out within each lip, over the mesh and its UV-seam twins (a mesh of loose quads has no other way
        # across: each quad evened on its own and the lip opened in tiles); the slit copies stay as they are
        nbl = {}
        for v in got:
            vs_ = [v] + [t for t in twin_of(v) if t is not v and t in got and lip_of[t] == lip_of[v]]
            nbl[v] = [e.other_vert(u) for u in vs_ for e in u.link_edges] + vs_[1:]
        for _ in range(6):
            new = {}
            for v in got:
                vals = []
                for o in nbl[v]:
                    if o in got and lip_of[o] == lip_of[v]:
                        vals.append(got[o])
                    elif o in (lower_set if lip_of[v] else upper_set):
                        vals.append(o[dl].get(jj, 0.0))
                if vals:
                    new[v] = 0.5 * got[v] + 0.5 * sum(vals) / len(vals)
            got.update(new)
        for grp in {id(twin_of(v)): twin_of(v) for v in got}.values():   # twins end equal
            g_ = [t for t in grp if t in got]
            for lw in (True, False):
                same = [t for t in g_ if lip_of[t] == lw]
                if len(same) > 1:
                    m_ = sum(got[t] for t in same) / len(same)
                    for t in same:
                        got[t] = m_
        for v, w in got.items():
            old = v[dl].get(jj, 0.0)
            v[dl][jj] = w
            v[dl][hj] = max(0.0, v[dl].get(hj, 0.0) + (old - w))
            if v[dl][jj] < 1e-5:
                del v[dl][jj]
        report["lip_band_weighted"] = {"upper": sum(1 for v in got if not lip_of[v]), "lower": sum(1 for v in got if lip_of[v])}
        # kept for the lip bones (step 4b): which lip, over the mesh (1 upper, -1 lower, 0 not near the slit)
        lay = LIP_SIDE
        for v in upper_set:
            if v.is_valid:
                v[lay] = 1
        for v in lower_set:
            if v.is_valid:
                v[lay] = -1
        for v, lw in lip_of.items():
            if v.is_valid:
                v[lay] = -1 if lw else 1

# ------------------------------------------------------------------ 2. roll the lips inward
lip_mat = bpy.data.materials.new("lip_inner"); lip_mat.use_nodes = True
lb = next(n for n in lip_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
lb.inputs["Base Color"].default_value = (*job.get("lip_colour", [0.45, 0.16, 0.16]), 1)
lb.inputs["Roughness"].default_value = 0.35
face.data.materials.append(lip_mat)
lip_idx = len(face.data.materials) - 1
boundary = [e for e in bm.edges if e.is_boundary and all(v in set(upper) | set(lower) | CORNERS for v in e.verts)]
roll_faces = []
for verts_side, sgn in ((set(upper), 1), (set(lower), -1)):
    edges = [e for e in boundary if all(v in verts_side for v in e.verts)]   # not at the corners: the lips meet there (a shared corner stretched a flap)
    for ring, (back, curl) in enumerate(((0.16, 0.05), (0.30, 0.10))):
        if not edges:
            break
        ext = bmesh.ops.extrude_edge_only(bm, edges=edges)
        nv = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMVert)]
        ne = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMEdge)]
        nf = [g for g in ext["geom"] if isinstance(g, bmesh.types.BMFace)]
        for v in nv:
            p = P(v)
            u = (p.x - x0) / max(x1 - x0, 1e-9)
            prof = math.sin(math.pi * max(0.0, min(1.0, u))) ** 0.6     # flat at the corners
            step_back = (0.16 if ring == 0 else 0.14) * W * prof
            step_curl = (0.05 if ring == 0 else 0.05) * W * prof * sgn
            q = p + Vector((0, step_back, step_curl))
            sy = skin_y(q.x, q.z)          # thin, back-sloping lips: keep the roll under the skin
            if sy is not None and q.y < sy + 0.04 * W:
                q.y = sy + 0.04 * W
            v.co = finv @ q
        for f in nf:
            f.material_index = lip_idx
            roll_faces.append(f)
        edges = [e for e in ne if e.is_boundary and all(v in nv for v in e.verts)]
bm.normal_update()
# 2b. where the closed lips touch: on a source sculpted with the mouth shut the skin folds deep into the head between
# them - the lips' insides, a jagged lump, painted with the skin (on women_young 0.12-0.45 W behind the cut, part of the
# lower lip's front hidden under the upper lip's overhang). Opened, the jaw showed it as a brown jagged shelf between
# the lower lip and the teeth. What lies deep behind the cut goes (the roll is the lips' inside); the rest of what is
# hidden at rest takes the lip's inner colour: a material of its own ("lip_shelf"), so the roll's rules (kept still,
# pinned when pressed, the lip cage) do not take it. The upper lip's underside just under the line is the upper lip's
# already: the seam (step 0) left it there.
shelf_mat = bpy.data.materials.new("lip_shelf"); shelf_mat.use_nodes = True
sb_ = next(n for n in shelf_mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
sb_.inputs["Base Color"].default_value = lb.inputs["Base Color"].default_value[:]
sb_.inputs["Roughness"].default_value = 0.35
face.data.materials.append(shelf_mat)
shelf_idx = len(face.data.materials) - 1
_nrm = fw.to_3x3().inverted().transposed()
def _depth_along(vs):   # a lip's cut edge: how deep it is along x (its foremost point near x)
    pts = sorted((P(v).x, P(v).y) for v in vs if v.is_valid)
    def at(x):
        lo, hi = bisect.bisect_left(pts, (x - 0.04 * W, -1e9)), bisect.bisect_right(pts, (x + 0.04 * W, 1e9))
        if hi > lo:
            return min(q[1] for q in pts[lo:hi])
        i = bisect.bisect_left(pts, (x, -1e9))
        near = [pts[k] for k in (i - 1, i) if 0 <= k < len(pts)]
        return min(near, key=lambda q: abs(q[0] - x))[1] if near else None
    return at
slit_y = {-1: _depth_along(lower), 1: _depth_along(upper)}
rim = {lv: {f for v in vs if v.is_valid for f in v.link_faces} for lv, vs in ((-1, lower), (1, upper))}   # on the slit
shelf_n = {"lower": 0, "upper": 0}
blob = []
# (a rebuilt face mask has no source fold: it lies a little inside the old skin, so "hidden at rest" took its lips and
# its philtrum - pink plates on fairy and goblin_1)
for f in ([] if OVAL else bm.faces):
    if f.material_index in (lip_idx, shelf_idx):
        continue
    c = fw @ f.calc_center_median()
    u = (c.x - x0) / max(x1 - x0, 1e-9)
    # not at the corners; near the slit's height only (up to 0.12 W: above, the skin under a big low nose is as
    # hidden, behind the nose's tip, and went pink on goblin_hero_2)
    if not 0.03 < u < 0.97 or not -0.3 * W < side(c) < 0.12 * W:
        continue
    # which lip by where it is (the band's own mark said "upper" for part of the lump below the slit: it went down with
    # the jaw all the same)
    lv = -1 if side(c) < 0 else 1
    n = (_nrm @ f.normal).normalized()
    if not all(v[LIP_SIDE] for v in f.verts):   # the lips' band only
        continue
    sy = skin_y(c.x, c.z)
    hid = None if sy is None else c.y - sy
    sl = slit_y[lv](c.x)
    # the lips' inside proper goes: a jagged lump 0.12-0.45 W deep behind the cut, its faces every way, its top above
    # the roll - it stood in the open mouth whatever its colour; the roll is the lips' inside now. Near the cut's depth
    # it stays (the lower lip's front under an overhanging upper lip, facing the viewer: the lip itself, no hole in it)
    if hid is not None and hid > 0.03 * W and sl is not None and (c.y > sl + 0.08 * W or lv == -1 and n.y > -0.5):
        blob.append(f)
    # hidden behind the skin at rest (the texture there is whatever the painter never saw); on the slit, turned up or
    # down into the fold, a little behind is enough. Never what the closed mouth shows: by the corners, and on a lip
    # seen from below, it went pink
    elif hid is not None and (hid > 0.03 * W or f in rim[lv] and hid > 0.008 * W and abs(n.z) > 0.3 and 0.12 < u < 0.88):
        f.material_index = shelf_idx; shelf_n["lower" if lv == -1 else "upper"] += 1
report["lip_shelf_faces"] = shelf_n
bmesh.ops.delete(bm, geom=blob, context="FACES_ONLY")   # (the vertices stay: the slit's lists still name some)
report["lips_inside_removed"] = len(blob)
if job.get("check"):   # «Проверить рот»: the cut's line for the editor (glTF axes), the upper lip's cut edge at rest
    _bins = {}
    for v in upper:   # the foremost point in each of 48 strips across the mouth (the edge also runs inside)
        if v.is_valid:
            p = P(v); b_ = int((p.x - x0) / max(x1 - x0, 1e-9) * 48)
            if b_ not in _bins or p.y < _bins[b_].y:
                _bins[b_] = p
    report["check_slit"] = [[round(p.x, 5), round(p.z, 5), round(-p.y, 5)] for _, p in sorted(_bins.items())]
bm.to_mesh(face.data); bm.free()
# smooth normals for the rebuilt area: the source mesh carries custom split normals and new vertices get none, which
# shades every new triangle differently. Loops of faces touching the new area get the area-weighted normal of all
# faces at that position (welded across UV-seam twins); the rest of the body keeps its own normals.
if OVAL:
    me_ = face.data
    new_mats = {i for i, m in enumerate(me_.materials) if m and m.name.startswith(("face_mask", "lip_inner", "lip_shelf"))}
    if new_mats:
        q_ = W * 1e-4
        key = [tuple(round(c / q_) for c in v.co) for v in me_.vertices]
        acc = {}
        for poly in me_.polygons:
            n = poly.normal * poly.area
            for vi in poly.vertices:
                acc[key[vi]] = acc.get(key[vi], Vector()) + n
        hot = {key[vi] for poly in me_.polygons if poly.material_index in new_mats for vi in poly.vertices}
        try:
            old = [Vector(cn.vector) for cn in me_.corner_normals]
        except AttributeError:
            me_.calc_normals_split(); old = [Vector(l.normal) for l in me_.loops]
        out = []
        for li, loop in enumerate(me_.loops):
            k_ = key[loop.vertex_index]
            out.append(acc[k_].normalized() if k_ in hot and acc[k_].length > 0 else old[li])
        for poly in me_.polygons:
            poly.use_smooth = True
        me_.normals_split_custom_set(out)
        report["renormalised_points"] = len(hot)
report["roll_faces"] = len(roll_faces)

# ------------------------------------------------------------------ 3. cavity cup
def jaw_blend(z, zc, band):
    return max(0.0, min(1.0, 0.5 - (z - zc) / (2 * band)))


def skin(o, fn):
    """vertex groups head/jaw from fn(world point) -> jaw weight; armature modifier on arm"""
    gh, gj = o.vertex_groups.new(name=HEAD), (o.vertex_groups.new(name=JAW) if JAW != HEAD else None)
    for v in o.data.vertices:
        w = fn(o.matrix_world @ v.co) if gj else 0.0
        if 1 - w > 1e-4:
            gh.add([v.index], 1 - w, "REPLACE")
        if gj and w > 1e-4:
            gj.add([v.index], w, "REPLACE")
    m = o.modifiers.new("Armature", "ARMATURE"); m.object = arm
    o.parent = arm; o.matrix_parent_inverse = arm.matrix_world.inverted()


cav_c = Vector((cx, M.y + 0.42 * W, line_z(cx) - 0.04 * W))
bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=1)
cav = bpy.context.active_object; cav.name = cav.data.name = "MouthCavity"
# the sides nearly upright (the width going as (1 - y^2)^0.15, not a ball's sqrt): a ball's sides closed in towards
# the back and stood in front of the side teeth, two dark panels stretched between the jaws as the mouth opened wide
for v in cav.data.vertices:
    v.co.x *= max(1e-3, 1 - v.co.y ** 2) ** -0.35 if abs(v.co.y) < 0.999 else 1.0
cav.data.transform(Matrix.Diagonal((0.56 * W, 0.50 * W, 0.40 * W, 1)))
bm = bmesh.new(); bm.from_mesh(cav.data)
bmesh.ops.delete(bm, geom=[f for f in bm.faces if f.calc_center_median().y < -0.30 * W], context="FACES")
bmesh.ops.reverse_faces(bm, faces=bm.faces[:])
bm.to_mesh(cav.data); bm.free()
cav.location = cav_c
bpy.ops.object.transform_apply(location=True)
for v in cav.data.vertices:          # the cup must not poke out through the (recessed) skin around the lips
    sy = skin_y(v.co.x, v.co.z)
    if sy is not None and v.co.y < sy + 0.04 * W:
        v.co.y = sy + 0.04 * W
cmat = bpy.data.materials.new("mouth_cavity"); cmat.use_nodes = True
cb = next(n for n in cmat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
cb.inputs["Base Color"].default_value = (0.08, 0.025, 0.025, 1); cb.inputs["Roughness"].default_value = 0.35
cav.data.materials.append(cmat)
for p_ in cav.data.polygons:
    p_.use_smooth = True
# what the lower lip skin really gets from the jaw: inner parts on the jaw use the same, so they open together
_jg = face.vertex_groups.get(JAW)
_ws = [next((g.weight for g in v.groups if _jg is not None and g.group == _jg.index), 0.0)
       for v in face.data.vertices
       if abs((fw @ v.co).x - cx) < 0.3 * W and -0.35 * W < side(fw @ v.co) < -0.03 * W and (fw @ v.co).y < front_limit]
JAW_IN = 0.95 * ((sum(_ws) / len(_ws)) if _ws else 1.0)   # with the lower lip, a touch less so the teeth stay inside the chin
report["lower_lip_jaw_weight"] = round(JAW_IN, 3)
skin(cav, lambda p: JAW_IN * jaw_blend(p.z, line_z(cx), 0.08 * W))

# ------------------------------------------------------------------ 4. teeth and tongue
kit_w = float(job.get("kit", {}).get("arch_width", 0.05))
# the set scaled to the mouth width (0.95 W; the markup's «Зубы −/+» times that) and put 0.10 W behind the middle of
# the lips at the slit, or - with the markup's own place («Зубы»: the front of the upper incisors' biting edge) - so
# that this front point of the set lands there
s = W * 0.95 / kit_w * max(0.3, min(2.0, float(job.get("teeth_scale") or 1.0)))
anchor = Vector((cx, M.y + 0.10 * W, line_z(cx)))
parts = []
for path in (job.get("teeth_glb"), job.get("tongue_glb")):
    if not path or not Path(path).exists():
        continue
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=path)
    for o in set(bpy.data.objects) - before:
        if o.type != "MESH":
            bpy.data.objects.remove(o, do_unlink=True); continue
        parts.append(o)
tu = next((o for o in parts if o.name.startswith("Teeth_Upper")), None)
_kf = Vector()
if tu is not None:
    _tv = [tu.matrix_world @ v.co for v in tu.data.vertices]
    _mid = [v for v in _tv if abs(v.x) < 0.1 * kit_w] or _tv
    _y0 = min(v.y for v in _mid)                       # the set's front (Blender: forward is -y) ...
    _kf = Vector((0.0, _y0, min(v.z for v in _mid if v.y < _y0 + 0.03 * kit_w)))   # ... at the incisors' biting edge
manual = bool(job.get("teeth_front")) and tu is not None
if manual:
    anchor = bl(job["teeth_front"]) - _kf * s
_front = anchor + _kf * s
report["teeth"] = {"place": "markup" if manual else "auto", "scale": round(s * kit_w / (0.95 * W), 3),
                   "front": [round(_front.x, 5), round(_front.z, 5), round(-_front.y, 5)]}   # glTF axes, before step 6
for o in parts:
    bpy.ops.object.select_all(action="DESELECT"); o.select_set(True)
    bpy.context.view_layer.objects.active = o
    o.matrix_world = Matrix.Translation(anchor) @ Matrix.Scale(s, 4) @ o.matrix_world
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
for o in parts:
    on_jaw = o.name.startswith(("Teeth_Lower", "Gum_Lower", "Tongue"))
    skin(o, lambda p, j=on_jaw: JAW_IN if j else 0.0)
# push each row back until no vertex is in front of the skin (recessed chins, sloping lips); upper and lower apart,
# so a recessed chin does not hide the upper teeth from the side
groups = {"upper": [o for o in parts if o.name.startswith(("Teeth_Upper", "Gum_Upper"))],
          "lower": [o for o in parts if not o.name.startswith(("Teeth_Upper", "Gum_Upper"))]}
pushed = {}
# against the skin as rebuilt (the relaxed face mask sits a little inside the old lips: a gum behind the old skin
# poked through the new lower lip) as well as the old one
face.data.calc_loop_triangles()
_bvh_now = BVHTree.FromPolygons([fw @ v.co for v in face.data.vertices], [tuple(t.vertices) for t in face.data.loop_triangles])


def skin_y_now(x, z):
    h = _bvh_now.ray_cast(Vector((x, _ymin - W * 20, z)), Vector((0, 1, 0)), W * 80)
    a_ = skin_y(x, z)
    if h[0] is None or a_ is None:
        return a_
    # through the cut opening the ray finds the back of the mouth: only a surface close to the old skin counts
    return max(a_, h[0].y) if h[0].y - a_ < 0.15 * W else a_


for gname, objs in groups.items():
    lift = 0.045 * W if gname == "lower" else 0.0
    need = 0.0
    for o in objs:
        for v in o.data.vertices:
            p = o.matrix_world @ v.co + Vector((0, 0, lift if not o.name.startswith("Tongue") else 0.0))
            # upper row against the skin above the slit, lower row below it: fang tips that hang past the line may
            # show over the other lip, as on a real fanged mouth
            if (gname == "upper" and side(p) < 0.02 * W) or (gname == "lower" and side(p) > -0.02 * W):
                continue
            sy = skin_y_now(p.x, p.z)
            if sy is not None:
                need = max(need, sy + 0.03 * W - p.y)
    need = min(need, 1.5 * W)
    for o in objs:
        lz = lift if o.name.startswith(("Teeth_Lower", "Gum_Lower")) else 0.0
        o.data.transform(Matrix.Translation(Vector((0, need, lz))))
    pushed[gname] = round(need, 4)
report["inserted"] = [o.name for o in parts]
report["parts_pushed_back"] = pushed

# ------------------------------------------------------------------ 4b. lip bones (Rigify-style naming)
# lip.T / lip.B (centres), lip.T.L/R, lip.B.L/R (halves), lips.L/R (corners). Upper bones and corners are children of
# the head, lower bones of the jaw, so the jaw still opens the mouth; each bone takes a share of its parent's weight on
# the lips near it (Gaussian along the lip, fading 0.5 W away from the slit). Lip sync stays on the shape keys.
LIP_BONES = {}
if job.get("lip_bones", True):
    half = (x1 - x0) / 2
    spots = {"lip.T": (cx, 1), "lip.T.L": (cx + 0.5 * half, 1), "lip.T.R": (cx - 0.5 * half, 1),
             "lip.B": (cx, -1), "lip.B.L": (cx + 0.5 * half, -1), "lip.B.R": (cx - 0.5 * half, -1),
             "lips.L": (x1, 0), "lips.R": (x0, 0)}
    if CL.x < CR.x:   # character's left is +x in Blender here; keep names right if the head was mirrored
        spots["lips.L"], spots["lips.R"] = (x0, 0), (x1, 0)
    bpy.ops.object.select_all(action="DESELECT"); arm.select_set(True); bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    ainv = arm.matrix_world.inverted()
    for name, (x, sd) in spots.items():
        z = line_z(x) + sd * 0.06 * W
        sy = skin_y(x, z)
        y = (sy if sy is not None else M.y) + 0.12 * W
        eb = arm.data.edit_bones.new(name)
        eb.head = ainv @ Vector((x, y, z))
        eb.tail = ainv @ Vector((x, y - 0.15 * W, z))
        eb.parent = arm.data.edit_bones[JAW if sd < 0 else HEAD]
        LIP_BONES[name] = (Vector((x, y, z)), sd)
    bpy.ops.object.mode_set(mode="OBJECT")
    groups = {n: face.vertex_groups.new(name=n) for n in LIP_BONES}
    gh, gj = face.vertex_groups[HEAD], face.vertex_groups.get(JAW)
    sig = 0.35 * half
    moved = 0
    _ls = face.data.attributes.get("lip_side")
    for v in face.data.vertices:
        p = fw @ v.co
        if p.y > front_limit + 0.3 * W or abs(side(p)) > 0.5 * W or abs(p.x - cx) > half * 1.25:
            continue
        fall = max(0.0, 1.0 - abs(side(p)) / (0.5 * W))
        # which lip: as the cut parted them (step 1), else by the line (the lower lip's top behind the slit edge lies
        # above the line: by the line alone it took the upper bones, children of the head, and stayed as the jaw opened)
        lab = _ls.data[v.index].value if _ls is not None else 0
        up = lab > 0 if lab else side(p) >= 0
        src = gh if (up or gj is None) else gj
        sw = next((g.weight for g in v.groups if g.group == src.index), 0.0)
        if sw <= 1e-4:
            continue
        # the corner bones are the head's: the lower lip's jaw weight never goes to them (it stayed in place)
        cands = {n: math.exp(-((p.x - c.x) / sig) ** 2) for n, (c, sd) in LIP_BONES.items()
                 if (sd == 0 and up) or (sd != 0 and (sd > 0) == up)}
        # the two nearest only: with the head, the jaw and more bones, the limit of 4 below dropped the jaw itself
        cands = dict(sorted(cands.items(), key=lambda kv: -kv[1])[:2])
        tot = sum(cands.values())
        if tot <= 1e-6:
            continue
        take = sw * 0.85 * fall
        src.add([v.index], sw - take, "REPLACE")
        for n, c in cands.items():
            if c / tot > 0.02:
                groups[n].add([v.index], take * c / tot, "REPLACE")
        moved += 1
    bpy.ops.object.select_all(action="DESELECT"); face.select_set(True); bpy.context.view_layer.objects.active = face
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    report["lip_bones"] = list(LIP_BONES)
    report["lip_bone_verts"] = moved

# ------------------------------------------------------------------ 5. shape keys
theta = math.radians(float(job.get("open_deg", 26)))
jaw_objs = [face, cav] + [o for o in parts]


def jaw_w(o, v):
    """jaw weight incl. the lower lip bones (children of the jaw: they follow it when it opens)"""
    if JAW == HEAD:
        return 0.0
    ids = {g.index for g in o.vertex_groups if g.name == JAW or g.name.startswith("lip.B")}
    return min(1.0, sum(x.weight for x in v.groups if x.group in ids))


# keys only emotions use (lip sync's mouth shapes stay as they are) go further: at the old reach the emotions, mixed in
# at 0.04-0.5 of them, hardly showed (the brows moved 7-8 mm on a human-sized face)
EXPRESS = float(job.get("face_expressivity", 1.6))
EXPRESS_KEYS = ("brow", "cheekSquint", "noseSneer", "mouthFrown")


def add_key(o, name, fn):
    if EXPRESS != 1.0 and name.startswith(EXPRESS_KEYS):
        fn0 = fn

        def fn(o_, v_, p_):
            q_ = fn0(o_, v_, p_)
            return None if q_ is None else p_ + (q_ - p_) * EXPRESS
    if o.data.shape_keys is None:
        o.shape_key_add(name="Basis")
    old = o.data.shape_keys.key_blocks.get(name)
    if old is not None:
        o.shape_key_remove(old)
    k = o.shape_key_add(name=name, from_mix=False)
    mw, inv = o.matrix_world, o.matrix_world.inverted()
    for v in o.data.vertices:
        p = mw @ v.co
        q = fn(o, v, p)
        if q is not None:
            k.data[v.index].co = inv @ q
    return k


LIP_LEAN = float(job.get("lip_lean", 0.8))   # how far the lower lip leans back onto the teeth as the jaw opens (of its turn)
LIP_RISE = float(job.get("lip_rise", 0.08))  # and how much it stays up over the lower teeth (of W, the jaw open full)
_ls_attr = face.data.attributes.get("lip_side")
_ls = [a.value for a in _ls_attr.data] if _ls_attr is not None and len(_ls_attr.data) == len(face.data.vertices) else None


def open_jaw(o, v, p):   # rotation about the hinge (lateral axis), by the vertex's jaw weight
    w = jaw_w(o, v)
    if w <= 1e-4:
        return None
    R = Matrix.Rotation(theta * w, 4, "X")
    q = hinge + (R @ (p - hinge).to_4d()).to_3d()
    # the lower lip (0.2 W from the slit, its roll too) goes down as a whole, as the lower teeth's front does at the
    # slit's height, a little higher (LIP_RISE: over the teeth's roots), and leans back onto the teeth (LIP_LEAN of the
    # jaw's turn, about the lip's foot 0.25 W below the slit). Turned with the jaw it tilted its top forward and looked
    # thick and turned out; moved as its own edge it still dropped below the teeth and showed the gum. The jaw's turn is taken over 0.2 W further down, to the chin
    if o is face and abs(p.x - cx) < 0.5 * (x1 - x0) + 0.1 * W:
        lower = _ls[v.index] < 0 if _ls is not None and _ls[v.index] != 0 else side(p) < 0
        if lower:
            t = min(1.0, max(0.0, (max(0.0, -side(p)) - 0.2 * W) / (0.2 * W)))
            k = 1 - t * t * (3 - 2 * t)
            if k > 0:
                lz = line_z(p.x)
                E = Vector((p.x, max(p.y, _front.y), lz))   # the teeth's depth (the lip is in front of them)
                d = hinge + (R @ (E - hinge).to_4d()).to_3d() - E
                B = Vector((p.x, p.y, lz - 0.25 * W))
                Rl = Matrix.Rotation(-LIP_LEAN * theta * w, 4, "X")
                lean = (Rl @ (p - B).to_4d()).to_3d() - (p - B)
                q = q.lerp(p + d + lean + Vector((0, 0, LIP_RISE * W * w)), k)
    return q


for o in jaw_objs:
    add_key(o, "jawOpen", open_jaw)


def smooth_key(o, name, passes=40):
    """Corrective smooth of a shape key on the face: the displacement is relaxed over the surface in the transition
    zone (partial jaw weight: mouth corners, cheeks, under the chin), so neighbouring points no longer turn by
    different angles and fold. Rigid parts keep their motion: the lower lip / chin (jaw weight > 0.97), the slit and
    lip roll, and everything still (no displacement and far from the mouth)."""
    kb = o.data.shape_keys.key_blocks[name]
    base = o.data.shape_keys.key_blocks[0]
    n = len(o.data.vertices)
    q_ = W * 1e-4
    # weld UV-seam twins (same place, same jaw weight), but never the two lips of the slit (same place, other weight)
    key = [tuple(round(c / q_) for c in base.data[i].co) + (round(jaw_w(o, o.data.vertices[i]), 1),) for i in range(n)]
    nbr = {}
    for e in o.data.edges:
        a_, b_ = key[e.vertices[0]], key[e.vertices[1]]
        if a_ != b_:
            nbr.setdefault(a_, set()).add(b_); nbr.setdefault(b_, set()).add(a_)
    disp = {}
    for i in range(n):
        disp.setdefault(key[i], kb.data[i].co - base.data[i].co)
    mw = o.matrix_world
    lip_mat = {j for j, m in enumerate(o.data.materials) if m and m.name.startswith("lip_inner")}
    on_lip = set()
    for poly in o.data.polygons:
        if poly.material_index in lip_mat:
            on_lip.update(key[v] for v in poly.vertices)
    # with the rebuilt face mask the whole jaw motion stays on the mask (clean, seam-free mesh): the old mesh outside
    # it is pinned still (moving it lit the Tripo neck in pale patches, its normals split on many UV seams)
    mask_mat = {j for j, m in enumerate(o.data.materials) if m and m.name.startswith("face_mask")}
    on_mask = set()
    for poly in o.data.polygons:
        if poly.material_index in mask_mat or poly.material_index in lip_mat:
            on_mask.update(key[v] for v in poly.vertices)
    if mask_mat:
        for k in list(disp):
            if k not in on_mask and k not in on_lip:
                disp[k] = Vector()
    free = set()
    for i, v in enumerate(o.data.vertices):
        k = key[i]
        if k in on_lip:
            continue
        if mask_mat and k not in on_mask:
            continue
        p = mw @ base.data[i].co
        if (p - M).length > 5.5 * W:
            continue
        w = jaw_w(o, v)
        if w > 0.85 and (p - M).length < 1.6 * W:
            continue   # rigid jaw part: lower lip and chin front only (the throat under the chin is smoothed)
        if abs(side(p)) < 0.5 * W and abs(p.x - cx) < 0.8 * (x1 - x0) / 2:
            continue   # the lips themselves keep their motion; corners and cheeks are smoothed
        free.add(k)
    for _ in range(passes):
        new = {}
        for k in free:
            nb = nbr.get(k)
            if nb:
                avg = sum((disp[j] for j in nb), Vector()) / len(nb)
                new[k] = disp[k].lerp(avg, 0.5)
        disp.update(new)
    # a wide 3D Gaussian average of the displacement (graph smoothing only spreads a few edges on a dense mesh, so
    # the chin's motion stayed packed in a thin band of the throat and folded it)
    from mathutils.kdtree import KDTree as _KD
    bpos0 = {}
    for i in range(n):
        bpos0.setdefault(key[i], mw @ base.data[i].co)
    allk = list(bpos0)
    kd = _KD(len(allk))
    for j, k in enumerate(allk):
        kd.insert(bpos0[k], j)
    kd.balance()
    R = float(job.get("key_smooth_radius", 0.7)) * W
    for _ in range(3):
        new = {}
        for k in free:
            acc, wsum = Vector(), 0.0
            for (_, j, d) in kd.find_range(bpos0[k], R):
                w_ = math.exp(-(d / (0.5 * R)) ** 2)
                acc += disp[allk[j]] * w_; wsum += w_
            if wsum > 0:
                new[k] = acc / wsum
        disp.update(new)
    # untangle: faces that still turn over (skin under the chin compresses as the jaw drops) get their free
    # vertices relaxed again, locally, until nothing folds
    bpos = {}
    for i in range(n):
        bpos.setdefault(key[i], base.data[i].co.copy())
    polys = [[key[v] for v in poly.vertices] for poly in o.data.polygons]
    left = 0
    for it in range(60):
        bad = set()
        for ks in polys:
            if len(ks) < 3:
                continue
            a0, b0, c0 = (bpos[k] for k in ks[:3])
            a1, b1, c1 = (bpos[k] + disp[k] for k in ks[:3])
            n0 = (b0 - a0).cross(c0 - a0); n1 = (b1 - a1).cross(c1 - a1)
            if n0.length > 1e-12 and (n1.length < 1e-12 or n0.normalized().dot(n1.normalized()) < 0.5):
                bad.update(k for k in ks if k in free)
        left = len(bad)
        if not bad:
            break
        grow = set(bad)
        for k in bad:
            grow |= {j for j in nbr.get(k, ()) if j in free}
        for _ in range(4):
            new = {}
            for k in grow:
                nb = nbr.get(k)
                if nb:
                    new[k] = disp[k].lerp(sum((disp[j] for j in nb), Vector()) / len(nb), 0.8)
            disp.update(new)
    report["jawOpen_folds_left"] = left
    # the eyes stay out of it: on a cartoon face the eyes sit close to the mouth, and the smoothed jaw motion pulled
    # the lower lids down off the eyeballs. Nothing moves from the lower lids up, fading in over 0.35 W below them.
    lids = [bl(q).z for sd in "LR" for q in (job.get("eye_rim_" + sd) or [])[3:4] if q]
    if lids:
        z_lid, band = min(lids) - 0.05 * W, 0.35 * W
        for k in disp:
            t = (z_lid - bpos0[k].z) / band
            if t < 1:
                disp[k] = disp[k] * max(0.0, t) ** 2 * (3 - 2 * max(0.0, t))
    for i in range(n):
        kb.data[i].co = base.data[i].co + disp[key[i]]
    return len(free)


report["jawOpen_smoothed"] = smooth_key(face, "jawOpen", int(job.get("key_smooth", 150)))


def lip_fall(p, r):
    """1 on the lips, 0 at radius r from the line (front skin only)"""
    if p.y > front_limit + 0.3 * W:
        return 0.0
    d = abs(side(p)); dx = max(0.0, abs(p.x - cx) - 0.5 * W)
    return max(0.0, 1.0 - math.hypot(d, dx) / r)


def corner_fall(p, c, r):
    return max(0.0, 1.0 - (p - c).length / r) if p.y < front_limit + 0.3 * W else 0.0


def k_smile(o, v, p):
    w = max(corner_fall(p, CL, 0.45 * W), corner_fall(p, CR, 0.45 * W))
    if w <= 0:
        return None
    sx = 1 if p.x > cx else -1
    return p + Vector((sx * 0.12 * W, 0.04 * W, 0.14 * W)) * w


def k_stretch(o, v, p):
    w = max(corner_fall(p, CL, 0.45 * W), corner_fall(p, CR, 0.45 * W))
    if w <= 0:
        return None
    sx = 1 if p.x > cx else -1
    return p + Vector((sx * 0.10 * W, 0.0, -0.02 * W)) * w * w


def k_round(fwd, narrow):
    def f(o, v, p):
        w = lip_fall(p, 0.45 * W)
        if w <= 0:
            return None
        return p + Vector((-(p.x - cx) * narrow, -fwd * W, 0.0)) * w
    return f


def k_lip(dz, upper_side):
    def f(o, v, p):
        if (side(p) > 0) != upper_side:
            return None
        w = lip_fall(p, 0.35 * W)
        return p + Vector((0, 0, dz * W)) * w if w > 0 else None
    return f


def k_frown(o, v, p):   # corners down and a little in, the chin skin under them bunches a little
    w = max(corner_fall(p, CL, 0.5 * W), corner_fall(p, CR, 0.5 * W))
    if w <= 0:
        return None
    sx = 1 if p.x > cx else -1
    return p + Vector((-sx * 0.03 * W, 0.0, -0.12 * W)) * w


_roll_verts = None


def k_press(o, v, p):   # lips pressed together and thinned: each lip toward the slit, rolled in a little
    global _roll_verts
    if _roll_verts is None:   # the rolled-in lip stays (moving it showed more of the pink roll between the lips)
        mi = {j for j, m in enumerate(o.data.materials) if m and m.name.startswith("lip_inner")}
        _roll_verts = {i for pl in o.data.polygons if pl.material_index in mi for i in pl.vertices}
    if v.index in _roll_verts:
        return None
    w = lip_fall(p, 0.4 * W)
    w *= min(1.0, min((p - CL).length, (p - CR).length) / (0.3 * W)) ** 2   # the corners stay: they opened a hole
    if w <= 0:
        return None
    d = side(p)
    if abs(d) < 0.04 * W:   # the slit edges stay shut (right at the line the side sign is noise: they spread apart)
        return None
    w *= min(1.0, (abs(d) - 0.04 * W) / (0.08 * W))
    toward = -0.35 * d * min(1.0, 0.25 * W / max(abs(d), 1e-9))   # at most a quarter of the lip height
    return p + Vector((0, 0, toward)) * w


for name, fn in (("mouthSmile", k_smile), ("mouthStretch", k_stretch), ("mouthFunnel", k_round(0.06, 0.18)),
                 ("mouthPucker", k_round(0.09, 0.35)), ("mouthUpperUp", k_lip(0.06, True)), ("mouthLowerDown", k_lip(-0.07, False)),
                 ("mouthFrown", k_frown), ("mouthPress", k_press)):
    add_key(face, name, fn)


# ARKit's Left / Right: the mouth keys that move one side are split by a soft middle (0.3 W wide; the character's left
# is the corner_L side), so an emotion lifts one corner (a smirk, a sneer) and lip sync drives the sides apart; the
# two halves add up to the key as made. Cheek squint and nose sneer per side where the eyes are marked (they place the
# cheek under the eye and the nose wing)
LSX = 1.0 if CL.x > cx else -1.0


def side_mask(p):   # 1 on the character's left, 0 on the right
    t = max(0.0, min(1.0, 0.5 + (p.x - cx) * LSX / (0.3 * W)))
    return t * t * (3 - 2 * t)


def split_key(o, name):
    kbs = o.data.shape_keys.key_blocks
    kb = kbs.get(name)
    if kb is None:
        return False
    base, mw = kbs[0], o.matrix_world
    n = len(kb.data)
    d = [kb.data[i].co - base.data[i].co for i in range(n)]
    m = [side_mask(mw @ base.data[i].co) for i in range(n)]
    for sd, f in (("Left", lambda x: x), ("Right", lambda x: 1.0 - x)):
        nk = o.shape_key_add(name=name + sd, from_mix=False)
        for i in range(n):
            if d[i].length_squared > 0:
                nk.data[i].co = base.data[i].co + d[i] * f(m[i])
    o.shape_key_remove(kb)
    return True


PAIRED_MOUTH = ("mouthSmile", "mouthFrown", "mouthStretch", "mouthUpperUp", "mouthLowerDown", "mouthPress")
report["keys_split"] = [k for k in PAIRED_MOUTH if split_key(face, k)]
if job.get("eye_L") and job.get("eye_R"):
    _EL, _ER = bl(job["eye_L"]), bl(job["eye_R"])
    _ipd = (_EL - _ER).length
    _mid = (_EL.x + _ER.x) / 2

    def k_cheek(E):   # the cheek under the eye goes up (and a touch forward), the lower lid with it: a squint
        sx = 1.0 if E.x > _mid else -1.0
        C = E + Vector((sx * 0.05 * _ipd, 0, -0.42 * _ipd))

        def f(o, v, p):
            if p.y > E.y + 0.35 * _ipd:   # behind the face
                return None
            w = math.exp(-((p - C).length / (0.3 * _ipd)) ** 2)
            return p + Vector((0, -0.03 * _ipd, 0.11 * _ipd)) * w if w > 1e-3 else None
        return f

    def k_sneer(E):   # the nose wing up and a little in, the skin beside it wrinkling up
        sx = 1.0 if E.x > _mid else -1.0
        nx, nz = _mid + sx * 0.2 * _ipd, M.z + 0.42 * (E.z - M.z)

        def f(o, v, p):
            if p.y > E.y:   # the nose is in front of the eyes
                return None
            w = math.exp(-((p.x - nx) ** 2 + (p.z - nz) ** 2) / (0.22 * _ipd) ** 2)
            return p + Vector((-sx * 0.02 * _ipd, -0.015 * _ipd, 0.10 * _ipd)) * w if w > 1e-3 else None
        return f
    for sd, E in (("Left", _EL), ("Right", _ER)):
        add_key(face, "cheekSquint" + sd, k_cheek(E))
        add_key(face, "noseSneer" + sd, k_sneer(E))
    report["keys_added"] = ["cheekSquintLeft", "noseSneerLeft", "cheekSquintRight", "noseSneerRight"]


def brow_keys():
    """ARKit brow keys on the forehead (lipsync.py drives them from emotions): browInnerUp, browOuterUp and
    browDown per side. Each moves the brow over its eye with a soft falloff: nothing at the eyelid rim (the eyeball
    fits there), full at the brow line, fading again up the forehead. Hair strands lying over the brow move along."""
    EL_, ER_ = bl(job["eye_L"]), bl(job["eye_R"])
    ipd = (EL_ - ER_).length
    mid_x = (EL_.x + ER_.x) / 2
    sides = {}
    for sd, ec in (("Left", EL_), ("Right", ER_)):
        rim = [bl(q) for q in job.get("eye_rim_" + sd[0]) or [] if q]
        if len(rim) < 4:
            rim = [ec + Vector((dx * ipd, 0, dz * ipd)) for dx, dz in ((-.22, 0), (0, .09), (.22, 0), (0, -.09))]
        inner = min(rim, key=lambda q: abs(q.x - mid_x)); outer = max(rim, key=lambda q: abs(q.x - mid_x))
        top = max(rim, key=lambda q: q.z)
        sides[sd] = dict(c=sum(rim, Vector()) / len(rim), inner=inner, outer=outer, top=top,
                         half=max(abs(outer.x - inner.x) / 2, 0.1 * ipd), sx=1.0 if outer.x > inner.x else -1.0)
    front_y = min(EL_.y, ER_.y) - 0.2 * ipd   # the brow skin is in front of the eye centres

    def lift(sd, p):
        """0 at and under the upper lid rim, 1 from 0.22 ipd above it to the brow line, fading up the forehead"""
        g = sides[sd]
        t = min(1.0, abs(p.x - g["c"].x) / (g["half"] * 1.35))
        rim_z = g["top"].z - (g["top"].z - g["c"].z) * t * t
        if p.y > front_y + 0.6 * ipd:
            return 0.0
        a_ = max(0.0, min(1.0, (p.z - rim_z) / (0.22 * ipd)))
        a_ = a_ * a_ * (3 - 2 * a_)
        brow_z = g["top"].z + 0.3 * ipd
        if p.z > brow_z:
            a_ *= math.exp(-((p.z - brow_z) / (0.45 * ipd)) ** 2)
        return a_

    def around(p, x, sigma):
        return math.exp(-((p.x - x) / (sigma * ipd)) ** 2)

    def inner_up(o, v, p):
        w = max(lift(sd, p) * around(p, sides[sd]["inner"].x, 0.32) for sd in sides)
        return p + Vector((0, 0, 0.11 * ipd)) * w if w > 1e-3 else None

    def outer_up(sd):
        def f(o, v, p):
            w = lift(sd, p) * around(p, sides[sd]["outer"].x, 0.3)
            return p + Vector((0, 0, 0.13 * ipd)) * w if w > 1e-3 else None
        return f

    def down(sd):
        def f(o, v, p):   # the brow lowers and pulls toward the nose, the inner end most
            g = sides[sd]
            w = lift(sd, p) * around(p, (2 * g["inner"].x + g["outer"].x) / 3, 0.4)
            return p + Vector((-g["sx"] * 0.05 * ipd, -0.025 * ipd, -0.11 * ipd)) * w if w > 1e-3 else None
        return f
    keys = [("browInnerUp", inner_up)]
    for sd in ("Left", "Right"):
        keys += [("browDown" + sd, down(sd)), ("browOuterUp" + sd, outer_up(sd))]
    for name, fn in keys:
        add_key(face, name, fn)
    return [k for k, _ in keys]


def lip_untangle(o, names, rounds=40):
    """The lips in every mouth key, made even (the shape of the lip kept, its sharp points evened out): a triangle of
    the lips that turns over or stretches four times in a key (a point of it moved apart from its neighbours: the
    source's rough weights, a cut sliver beside it) gets its points' displacement drawn toward their neighbours',
    with a ring around, until nothing turns over. Points the mesh keeps twice (UV seams) move as one; the two lips of
    the slit share places but not weights, so they never mix. Slivers of the cut (no area) are not looked at."""
    kbs = o.data.shape_keys.key_blocks
    base = kbs[0]
    n = len(o.data.vertices)
    q_ = W * 1e-4
    key = [tuple(round(c / q_) for c in base.data[i].co) + (round(jaw_w(o, o.data.vertices[i]), 1),) for i in range(n)]
    nbr = {}
    for e in o.data.edges:
        a_, b_ = key[e.vertices[0]], key[e.vertices[1]]
        if a_ != b_:
            nbr.setdefault(a_, set()).add(b_); nbr.setdefault(b_, set()).add(a_)
    mw = o.matrix_world
    bpos = {}
    for i in range(n):
        bpos.setdefault(key[i], base.data[i].co.copy())
    half_ = (x1 - x0) / 2
    zone = {k for k, b0 in bpos.items()
            if abs(side(mw @ b0)) < 0.5 * W and abs((mw @ b0).x - cx) < half_ + 0.3 * W and (mw @ b0).y < M.y + 1.0 * W}
    o.data.calc_loop_triangles()
    tris = [tuple(key[v] for v in t.vertices) for t in o.data.loop_triangles]
    tris = [t for t in tris if all(k in zone for k in t) and len(set(t)) == 3]
    area0 = []
    for t in tris:
        a0, b0, c0 = (bpos[k] for k in t)
        area0.append((b0 - a0).cross(c0 - a0))
    big = 4e-5 * W * W
    out = {}
    for name in names:
        kb = kbs.get(name)
        if kb is None:
            continue
        disp = {}
        for i in range(n):
            if key[i] in zone:
                disp.setdefault(key[i], kb.data[i].co - base.data[i].co)

        def bad_points():
            bad = set()
            for t, n0 in zip(tris, area0):
                if n0.length < big:
                    continue
                a1, b1, c1 = (bpos[k] + disp[k] for k in t)
                n1 = (b1 - a1).cross(c1 - a1)
                if n1.length < 1e-14 or n0.normalized().dot(n1.normalized()) < 0.3 or n1.length > 4 * n0.length:
                    bad.update(t)
            return bad
        before = left = len(bad_points())
        for _ in range(rounds):
            bad = bad_points()
            left = len(bad)
            if not bad:
                break
            grow = set(bad)
            for k in bad:
                grow |= {j for j in nbr.get(k, ()) if j in zone}
            for _ in range(3):
                new = {}
                for k in grow:
                    nb = [j for j in nbr.get(k, ()) if j in disp]
                    if nb:
                        new[k] = disp[k].lerp(sum((disp[j] for j in nb), Vector()) / len(nb), 0.6)
                disp.update(new)
        left = len(bad_points())
        if left >= before:   # no better (a key with hardly anything turned over: the evening only spread it): kept as built
            if before:
                out[name] = [before, before]
            continue
        for i in range(n):
            if key[i] in disp:
                kb.data[i].co = base.data[i].co + disp[key[i]]
        out[name] = [before, left]
    return out


report["lip_points_evened"] = lip_untangle(face, [k.name for k in face.data.shape_keys.key_blocks[1:]])   # [before, after]

if job.get("eye_L") and job.get("eye_R"):   # (not only on a rebuilt face: without it the emotions' brows stood still)
    report["brow_keys"] = brow_keys()


# ------------------------------------------------------------------ 6. nothing of the mouth through the skin
# The teeth, gums and tongue go with the jaw rigidly, the skin of the chin and the cheeks only partly (smoothed so
# it does not fold): opening the jaw, the lower row and the cavity cup came out through the skin under the lower lip
# and on the cheeks; the push-back of step 4 only looked from the front at rest. Here every pose is checked (rest and
# each shape key) and what shows outside is taken in: a row of teeth moved in as a whole (every key alike), the
# cavity, the gums and the tongue pulled in where they show, with a soft falloff; again until nothing shows, and a
# pass that does not help is taken back (a torn face mask: the teeth would only sink).
def _posed(o, key):
    kb = o.data.shape_keys.key_blocks if o.data.shape_keys else None
    k = kb.get(key) if kb is not None and key != "Basis" else None
    src = k.data if k is not None else (kb[0].data if kb is not None else o.data.vertices)
    return [o.matrix_world @ d.co for d in src]


face.data.calc_loop_triangles()
_tris = [tuple(t.vertices) for t in face.data.loop_triangles]
_fv0 = _posed(face, "Basis")
_bvh0 = BVHTree.FromPolygons(_fv0, _tris)
_outer = set()   # the outer skin: a ray along its normal leaves the head (never the lip roll or a mouth the source has)
for _ti, _t in enumerate(_tris):
    _a, _b, _c = (_fv0[v] for v in _t)
    _n = (_b - _a).cross(_c - _a)
    if _n.length > 1e-14:
        _n.normalize()
        if _bvh0.ray_cast((_a + _b + _c) / 3 + _n * W * 1e-4, _n, 6 * W)[0] is None:
            _outer.add(_ti)
_inner = [cav] + list(parts)
_keys = ["Basis"] + [k.name for k in face.data.shape_keys.key_blocks[1:]]


def through_skin():
    """[(object, vertex, how far out, its place, the way out)]: a vertex of the mouth's insides that is seen from
    outside (a ray from inside the head on through it meets no skin) with the outer skin right behind it, its outer
    side towards it. Teeth seen through the open mouth are not: behind them is the inside of the head."""
    out = []
    for key in _keys:
        fv = _posed(face, key)
        bvh = BVHTree.FromPolygons(fv, _tris)
        for o in _inner:
            for i, p in enumerate(_posed(o, key)):
                # across from behind the mouth (the cheeks, the lips) and from the mouth's middle (also down: the jaw)
                for A in (Vector((M.x, M.y + 0.8 * W, p.z)), M + Vector((0, 0.5 * W, 0))):
                    d = p - A
                    if d.length < 1e-9:
                        continue
                    d.normalize()
                    if bvh.ray_cast(p + d * 1e-6, d, 4 * W)[0] is not None:
                        continue
                    b = bvh.ray_cast(p, -d, 0.5 * W)
                    if b[0] is None or b[2] not in _outer or b[1].dot(d) <= 0:
                        continue
                    out.append((o, i, b[3], p, d, key))
                    break
    return out


def _count(found):
    c = {}
    for o, i, depth, p, d, key in found:
        c.setdefault(key, set()).add((o.name, i))
    return {k: len(v) for k, v in c.items()}


def _shift(o, world_delta_of):   # every key alike: the vertex's place in each pose moved by the same world vector
    inv = o.matrix_world.inverted().to_3x3()
    blocks = o.data.shape_keys.key_blocks if o.data.shape_keys else None
    for i, v in enumerate(o.data.vertices):
        dv = world_delta_of(i)
        if dv is None:
            continue
        dl_ = inv @ dv
        if blocks is None:
            v.co += dl_
            continue
        for kb in blocks:
            kb.data[i].co += dl_
        v.co = blocks[0].data[i].co.copy()   # the mesh itself follows the basis


ROWS = {"upper": ("Teeth_Upper", "Gum_Upper"), "lower": ("Teeth_Lower", "Gum_Lower", "Tongue")}
_found = through_skin() if job.get("skin_check", True) else []
check = {"before": _count(_found), "rows_moved": {}, "soft_points_moved": 0, "passes": 0}
_moved_rows = {}


def _snap():   # every coordinate of the insides (all keys), to take a pass back
    return {o.name: [[d.co.copy() for d in kb.data] for kb in o.data.shape_keys.key_blocks] if o.data.shape_keys
            else [[v.co.copy() for v in o.data.vertices]] for o in _inner}


def _restore(snap):
    for o in _inner:
        if o.data.shape_keys:
            for kb, cos in zip(o.data.shape_keys.key_blocks, snap[o.name]):
                for d, c in zip(kb.data, cos):
                    d.co = c
            for v, c in zip(o.data.vertices, snap[o.name][0]):
                v.co = c
        else:
            for v, c in zip(o.data.vertices, snap[o.name][0]):
                v.co = c


SOFT = ("MouthCavity", "Gum_", "Tongue")   # pulled in where they show; the teeth are rigid: their row moves as a whole
for _pass in range(6):
    if not _found:
        break
    check["passes"] = _pass + 1
    _before_pass, _rows_before, _cav_before = _snap(), dict(_moved_rows), check["soft_points_moved"]
    # a row of teeth (with its gum, so it stays on it) in as a whole, only for the teeth themselves showing: along the
    # way out averaged, as far as the deepest tooth point is out (+ a little), at most 0.08 W in all (deeper in, the
    # teeth would hide in the open mouth: then the rest is reported)
    for row, names in ROWS.items():
        hits = [(depth, d) for o, i, depth, p, d, key in _found if o.name.startswith(names[0])]
        if not hits:
            continue
        way = sum((d for _, d in hits), Vector())
        if way.length < 1e-9:
            continue
        way.normalize()
        step = min(max(dep for dep, _ in hits) + 0.02 * W, 0.08 * W - _moved_rows.get(row, 0.0))
        if step <= 1e-6:
            continue
        for o in parts:
            if o.name.startswith(names[:2]):
                _shift(o, lambda i, s=-way * step: s)
        _moved_rows[row] = _moved_rows.get(row, 0.0) + step
    # the soft insides (the cavity, the gums, the tongue): each point out pulled in by its depth (+ a little), its
    # neighbours following, fading over 0.12 W
    for o in [x for x in _inner if x.name.startswith(SOFT)]:
        pulls = {}
        for oo, i, depth, p, d, key in _found:
            if oo is o:
                mv = -d * (depth + 0.03 * W)
                if i not in pulls or mv.length > pulls[i].length:
                    pulls[i] = mv
        if not pulls:
            continue
        base0 = _posed(o, "Basis")
        src = [(base0[i], mv) for i, mv in pulls.items()]

        def _pull(j, base0=base0, src=src):
            best = None
            for q, mv in src:
                f = math.exp(-((base0[j] - q).length / (0.12 * W)) ** 2)
                if f > 0.05 and (best is None or (mv * f).length > best.length):
                    best = mv * f
            return best
        _shift(o, _pull)
        check["soft_points_moved"] += len(pulls)
    _was = len(_found)
    _found = through_skin()
    if len(_found) >= _was:   # no better (a face the mask tore: the teeth would only sink): this pass back, stop
        _restore(_before_pass)
        _moved_rows, check["soft_points_moved"] = _rows_before, _cav_before
        _found = through_skin()
        check["stopped"] = "no_better"
        break
check["after"] = _count(_found)
check["rows_moved"] = {k: round(v / W, 3) for k, v in _moved_rows.items()}
report["through_skin"] = check

# ------------------------------------------------------------------ 6b. what the seam gave the upper lip moves with it
# (step 0) the keys spread the jaw's motion over the points near the lips whatever their weights: the fold the seam
# left with the upper lip went partly down with the jaw and hung from the open upper lip in flaps. In every key each of
# those points takes the motion of the upper lip's cut edge near it (the six nearest, by inverse distance)
_wa = face.data.attributes.get("seam_up")
if _wa is not None and face.data.shape_keys:
    from mathutils.kdtree import KDTree
    _fv = [i for i, d in enumerate(_wa.data) if d.value == 1]
    _av = [i for i, d in enumerate(_wa.data) if d.value == 2]
    if _fv and _av:
        _kbs = face.data.shape_keys.key_blocks; _b0 = _kbs[0].data
        _kd = KDTree(len(_av))
        for n_, i in enumerate(_av):
            _kd.insert(_b0[i].co, n_)
        _kd.balance()
        _anc = {}
        for i in _fv:
            got = _kd.find_n(_b0[i].co, 6)
            ws = [(_av[n_], 1.0 / max(d_, 1e-9)) for _co, n_, d_ in got]
            t_ = sum(w for _, w in ws)
            _anc[i] = [(a_, w / t_) for a_, w in ws]
        for kb in _kbs[1:]:
            for i, ws in _anc.items():
                kb.data[i].co = _b0[i].co + sum(((kb.data[a_].co - _b0[a_].co) * w for a_, w in ws), Vector())
        report["seam_upper_points_in_keys"] = len(_anc)

# ------------------------------------------------------------------ 6c. the check («Проверить рот» in the markup)
# job "check": the face's triangles near the mouth that some key stretches (an edge over 0.12 W and 2.5 times its
# length at rest) get a material of their own, "check_stretch", bright red: the editor shows the model as cut with
# them marked. The report says how many per key.
if job.get("check") and face.data.shape_keys:
    red = bpy.data.materials.new("check_stretch"); red.use_nodes = True
    _rb = next(n for n in red.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    _rb.inputs["Base Color"].default_value = (1.0, 0.05, 0.03, 1.0)
    face.data.materials.append(red); _red = len(face.data.materials) - 1
    _kbs = face.data.shape_keys.key_blocks
    _near = [p for p in face.data.polygons if (fw @ p.center - M).length < 3.0 * W]
    _vi = sorted({i for p in _near for i in p.vertices})
    _pos = lambda kb: {i: fw @ kb.data[i].co for i in _vi}
    _b = _pos(_kbs[0]); _st = {}
    _lr = {p.index: max((_b[p.vertices[i]] - _b[p.vertices[i - 1]]).length for i in range(len(p.vertices))) for p in _near}
    for kb in _kbs[1:]:
        k_ = _pos(kb); n_ = 0
        for p in _near:
            lk = max((k_[p.vertices[i]] - k_[p.vertices[i - 1]]).length for i in range(len(p.vertices)))
            if lk > 0.12 * W and lk > 2.5 * _lr[p.index]:
                p.material_index = _red; n_ += 1
        if n_:
            _st[kb.name] = n_
    report["check_stretch"] = _st

for o in bpy.data.objects:     # rest = all keys at 0 (Blender 5 adds new keys at 1 -> glTF default weights)
    if o.type == "MESH" and o.data.shape_keys:
        for kb in o.data.shape_keys.key_blocks[1:]:
            kb.value = 0.0

arm.data.pose_position = "POSE"
bpy.ops.object.select_all(action="DESELECT")
for o in bpy.data.objects:
    o.select_set(o.type in ("ARMATURE", "MESH"))
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_morph=True, export_morph_normal=True, export_influence_nb=4)

if job.get("preview"):
    sc = bpy.context.scene
    try:
        sc.render.engine = "BLENDER_WORKBENCH"; sc.display.shading.color_type = "TEXTURE"
    except (TypeError, AttributeError):
        pass
    sc.render.resolution_x = sc.render.resolution_y = 300
    sc.render.image_settings.color_mode = "RGB"
    sc.world = bpy.data.worlds.new("bg"); sc.world.color = (0.82, 0.8, 0.77)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = "ORTHO"; cam.data.ortho_scale = W * 4; cam.data.clip_end = W * 400
    keyed = [o for o in bpy.data.objects if o.type == "MESH" and o.data.shape_keys]
    shots = []
    for key, view in (("closed", "front"), ("jawOpen", "front"), ("jawOpen", "side"), ("mouthSmile", "front")):
        for o in keyed:
            for kb in o.data.shape_keys.key_blocks[1:]:   # a split key shows both its sides
                kb.value = 1.0 if kb.name in (key, key + "Left", key + "Right") else 0.0
        if view == "front":
            cam.location = (cx, M.y - W * 100, line_z(cx) - W * 0.2); cam.rotation_euler = (math.radians(90), 0, 0)
        else:
            cam.location = (cx + W * 100, M.y + W * 0.6, line_z(cx) - W * 0.2); cam.rotation_euler = (math.radians(90), 0, math.radians(90))
        sc.render.filepath = job["preview"].replace(".png", f"_{key}_{view}.png")
        bpy.ops.render.render(write_still=True)
        shots.append(sc.render.filepath)
    if LIP_BONES:   # lip-bone check: left corner up and out, upper lip middle up (a sneer)
        for o in keyed:
            for kb in o.data.shape_keys.key_blocks[1:]:
                kb.value = 0.0
        arm.data.pose_position = "POSE"
        for n, d in (("lips.L", (0.18, 0, 0.22)), ("lip.T.L", (0, 0, 0.16))):
            pb = arm.pose.bones.get(n)
            if pb is not None:
                pb.matrix = Matrix.Translation(Vector(d) * W) @ pb.matrix
        bpy.context.view_layer.update()
        cam.location = (cx, M.y - W * 100, line_z(cx) - W * 0.2); cam.rotation_euler = (math.radians(90), 0, 0)
        sc.render.filepath = job["preview"].replace(".png", "_lipbones_front.png")
        bpy.ops.render.render(write_still=True)
        shots.append(sc.render.filepath)
    report["previews"] = shots
if job.get("report"):
    Path(job["report"]).write_text(json.dumps(report, indent=1), encoding="utf-8")
print("CUT_OK", json.dumps(report), flush=True)
