"""Face mask retopology, imported INSIDE Blender by blender_mouth_cut.py (job key face_topo).

The front of the face (hairline to under the chin, almost to the ears) is rebuilt with animation-friendly topology:
rings around the mouth (the editor's oval: slit, lip edge, outer loop, deformation zone, boundary), rings around
each eye (from the eyelid clicks) with a cap, and an even, smoothed constrained-Delaunay triangulation everywhere
else. The old mesh is cut exactly along the mask outline (crossing edges are split there) and the new mesh is built
on those very cut vertices, so the seam is closed. The mask gets its own planar UVs and a texture baked from the
original surface (base colour, normal, roughness), so UV seams of the source cannot tear it. Skin weights come
from the original surface under every new vertex.
"""
import math

import bmesh
import bpy
import mathutils.geometry as G
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def catmull_closed(pts, n_per):
    out = []
    k = len(pts)
    for i in range(k):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % k], pts[(i + 2) % k]
        for s in range(n_per):
            t = s / n_per
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t
                              + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return out


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


def build(C):
    """C: dict of the caller's context (bm, dl, face, fw, finv, skin_bvh, skin_y, W, cx, line_z, x0, x1, M, job, bl,
    report, fail, scene, arm). Returns (upper slit verts, lower slit verts, corners set, slit verts set)."""
    bm, dl, face, fw, finv = C["bm"], C["dl"], C["face"], C["fw"], C["finv"]
    skin_bvh, skin_y, W, cx, line_z = C["skin_bvh"], C["skin_y"], C["W"], C["cx"], C["line_z"]
    x0, x1, M, job, bl, report, fail = C["x0"], C["x1"], C["M"], C["job"], C["bl"], C["report"], C["fail"]
    P = lambda v: fw @ v.co
    me = face.data
    tris = list(me.loop_triangles)
    wv = [fw @ v.co for v in me.vertices]
    ymin = min(v.y for v in wv)

    # the untouched original, as the bake source (bm is not written to the mesh yet)
    src = bpy.data.objects.new("bake_src", me.copy())
    bpy.context.scene.collection.objects.link(src)
    src.matrix_world = fw.copy()

    def ray(x, z):
        return skin_bvh.ray_cast(Vector((x, ymin - W * 20, z)), Vector((0, 1, 0)), W * 80)

    def bary(tri, p):
        a, b, c = (wv[i] for i in tri.vertices)
        return G.barycentric_transform(p, a, b, c, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))

    def weights_at(p, ti):
        b = bary(tris[ti], p)
        out = {}
        for w, vi in zip(b, tris[ti].vertices):
            for g in me.vertices[vi].groups:
                out[g.group] = out.get(g.group, 0.0) + max(0.0, w) * g.weight
        tot = sum(out.values()) or 1.0
        return {k: w / tot for k, w in out.items() if w / tot > 1e-3}

    def new_vert(x, z):
        h = ray(x, z)
        if h[0] is None:
            fail(f"нет кожи под маской лица в точке ({x:.3g}, {z:.3g}): уменьшите маску")
        v = bm.verts.new(finv @ h[0])
        for k, w in weights_at(h[0], h[2]).items():
            v[dl][k] = w
        return v

    # ------------------------------------------------------------ landmarks
    EL, ER = bl(job["eye_L"]), bl(job["eye_R"])
    ipd = (EL - ER).length
    s = ipd * float(job.get("face_density", 0.11))          # target edge length
    rims = {}
    for sd, ec in (("L", EL), ("R", ER)):
        pts = [bl(p) for p in job.get("eye_rim_" + sd) or []]
        if len(pts) < 4:
            w_, h_ = 0.22 * ipd, 0.09 * ipd
            pts = [ec + Vector((-w_, 0, 0)), ec + Vector((0, 0, h_)), ec + Vector((w_, 0, 0)), ec + Vector((0, 0, -h_))]
        rims[sd] = catmull_closed([Vector((p.x, p.z)) for p in pts], 6)
    chin = bl(job["chin"]) if job.get("chin") else Vector((cx, 0, M.z - 0.6 * ipd))

    # ------------------------------------------------------------ rings: mouth (oval) and eyes
    half = (x1 - x0) / 2
    T_ = bl(job["lip_top"]) if job.get("lip_top") else Vector((cx, 0, line_z(cx) + 0.15 * W))
    B_ = bl(job["lip_bot"]) if job.get("lip_bot") else Vector((cx, 0, line_z(cx) - 0.2 * W))
    hu = max(W * 0.02, T_.z - line_z(T_.x)); hl = max(W * 0.02, line_z(B_.x) - B_.z)
    RINGS = [(1.0, 0.0), (1.04, 1.0), (1.14, 1.5), (1.28, 2.0), (1.42, 2.5)]
    HU = max(hu * 1.2, bl(job["limit_top"]).z - line_z(cx)) if job.get("limit_top") else 0.0
    NM = 32

    def ring_up(h_):
        if h_ <= 1 or not HU:
            return hu * h_
        return hu + (HU - hu) * (h_ - 1) / (RINGS[-1][1] - 1)

    def mpt(k, i):
        a_, h_ = RINGS[k]
        th = 2 * math.pi * i / NM
        x = cx + half * a_ * math.cos(th)
        sn = math.sin(th)
        return x, line_z(x) + (ring_up(h_) if sn >= 0 else hl * h_) * sn

    # points the mask must contain with a margin: the mouth's outer ring and the eyes' outer loops
    must = [Vector(mpt(4, i)) for i in range(NM)]
    for rim2 in rims.values():
        c2 = sum(rim2, Vector((0, 0))) / len(rim2)
        must += [c2 + (p - c2) * 2.0 for p in rim2]
    # ------------------------------------------------------------ mask outline (front view x, z)
    if job.get("mask"):
        mpts = [Vector((bl(p).x, bl(p).z)) for p in job["mask"]]
        outline = catmull_closed(mpts, max(2, int(64 / len(mpts))))
    else:
        top, bot = max(EL.z, ER.z) + 0.85 * ipd, chin.z - 0.12 * ipd
        mz, hz = (top + bot) / 2, (top - bot) / 2
        hx = abs(EL.x - ER.x) / 2 + 0.75 * ipd
        outline, radii = [], []
        for i in range(48):
            th = 2 * math.pi * i / 48
            c, sn = math.cos(th), math.sin(th)
            r = 1.0 / (abs(c) ** 2.5 + abs(sn) ** 2.5) ** (1 / 2.5)       # superellipse
            good = 0.15
            for k in range(1, 41):     # the farthest point where the skin still faces forward (dips inside are fine)
                f_ = k / 40
                x, z = cx + hx * c * r * f_, mz + hz * sn * r * f_
                h = ray(x, z)
                if h[0] is None:
                    break
                if h[1].dot(Vector((0, -1, 0))) > 0.45 and z > chin.z + 0.02 * ipd:   # forward-facing, above the chin edge
                    good = f_
            good *= 0.96
            radii.append((c * r, sn * r, good))
        # never smaller than the rings it must hold (+12 %), then smoothed around so the outline stays a round shape
        for k, (ux, uz, g) in enumerate(radii):
            th = math.atan2(uz, ux)
            need = 0.0
            for q in must:
                dx, dz = (q.x - cx) / hx, (q.y - mz) / hz
                if abs(((math.atan2(dz, dx) - th + math.pi) % (2 * math.pi)) - math.pi) < math.pi / 24:
                    need = max(need, math.hypot(dx, dz) / max(math.hypot(ux, uz), 1e-9) * 1.12)
            radii[k] = (ux, uz, max(g, need))
        rs = [g for _, _, g in radii]
        for _ in range(3):
            rs = [max(rs[i], (rs[i - 1] + rs[i] + rs[(i + 1) % len(rs)]) / 3) if False else
                  (rs[i - 1] + 2 * rs[i] + rs[(i + 1) % len(rs)]) / 4 for i in range(len(rs))]
        for (ux, uz, g), r_ in zip(radii, rs):
            r_ = max(r_, g if g > 0 else r_)
            outline.append(Vector((cx + hx * ux * r_, max(mz + hz * uz * r_, chin.z + 0.02 * ipd))))
    poly = [(p.x, p.y) for p in outline]
    mcx = sum(p.x for p in outline) / len(outline); mcz = sum(p.y for p in outline) / len(outline)
    report["mask_points"] = len(outline)

    def in_mask(p):
        return inside(poly, p.x, p.z)

    def front(p):
        sy = skin_y(p.x, p.z)
        return sy is not None and p.y < sy + 0.08 * W

    # ------------------------------------------------------------ cut the old mesh along the outline
    rim = []
    for e in list(bm.edges):
        a, b = P(e.verts[0]), P(e.verts[1])
        ia, ib = in_mask(a), in_mask(b)
        if ia == ib or not (front(a) or front(b)):
            continue
        lo, hi = 0.0, 1.0                                      # bisect the crossing
        for _ in range(18):
            mid = (lo + hi) / 2
            if in_mask(a.lerp(b, mid)) == ia:
                lo = mid
            else:
                hi = mid
        _, nv = bmesh.utils.edge_split(e, e.verts[0], (lo + hi) / 2)
        rim.append(nv)
    rimset = set(rim)
    # split the faces the outline crosses through their two cut points, so no old face spans inside and outside
    for f in list(bm.faces):
        if not f.is_valid:
            continue
        cv = [v for v in f.verts if v in rimset]
        if len(cv) == 2 and not any(cv[1] in e.verts for e in cv[0].link_edges):
            try:
                bmesh.ops.connect_verts(bm, verts=cv)
            except Exception:
                pass
    kill = [f for f in bm.faces if front(fw @ f.calc_center_median()) and in_mask(fw @ f.calc_center_median())]
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    rim = [v for v in rim if v.is_valid]
    bmesh.ops.remove_doubles(bm, verts=rim, dist=W * 2e-4)     # UV-seam twins on the rim become one vertex
    rim = list({v for v in rim if v.is_valid})
    # order the rim by walking the hole's boundary edges (angle sorting zig-zags on an uneven outline)
    rs_ = set(rim)
    nbr = {v: [e.other_vert(v) for e in v.link_edges if e.is_boundary and e.other_vert(v) in rs_] for v in rim}
    best = []
    for st in rim[:20]:
        loop, seen, cur, prev = [st], {st}, st, None
        while True:
            nx = [w for w in nbr[cur] if w is not prev and w not in seen]
            if not nx:
                break
            prev, cur = cur, nx[0]
            loop.append(cur); seen.add(cur)
        if len(loop) > len(best):
            best = loop
    report["mask_rim_walk"] = [len(best), len(rim)]
    if len(best) < 0.8 * len(rim):
        rim.sort(key=lambda v: math.atan2(P(v).z - mcz, P(v).x - mcx))
    else:
        rim = best
    report["mask_rim"] = len(rim)
    report["mask_deleted_faces"] = len(kill)
    if len(rim) < 12:
        fail("контур маски лица почти не пересёк сетку: проверьте маску")

    U = [new_vert(*mpt(0, i)) for i in range(NM // 2 + 1)]
    D = {NM // 2: U[NM // 2], NM: U[0]}
    for i in range(NM // 2 + 1, NM):
        D[i] = new_vert(*mpt(0, i))
    MR = {k: [new_vert(*mpt(k, i)) for i in range(NM)] for k in range(1, 5)}
    mouth_outer = [mpt(4, i) for i in range(NM)]
    EYE_SCALES = [1.0, 1.3, 1.65, 2.0]
    ER_ = {}
    eye_outer = {}
    for sd, rim2 in rims.items():
        c2 = sum(rim2, Vector((0, 0))) / len(rim2)
        loops = []
        for sc in EYE_SCALES:
            loops.append([new_vert(c2.x + (p.x - c2.x) * sc, c2.y + (p.y - c2.y) * sc) for p in rim2])
        ER_[sd] = (c2, loops)
        eye_outer[sd] = [(c2.x + (p.x - c2.x) * EYE_SCALES[-1], c2.y + (p.y - c2.y) * EYE_SCALES[-1]) for p in rim2]

    # ------------------------------------------------------------ fill: smoothed constrained Delaunay
    pts2, kind = [], []                                       # kind: ("rim", v) / ("vert", v) / ("free", None)
    edges2 = []

    def add_loop(vs2, verts):
        start = len(pts2)
        for (x, z), v in zip(vs2, verts):
            pts2.append((x, z)); kind.append(("vert", v))
        n = len(vs2)
        for i in range(n):
            edges2.append((start + i, start + (i + 1) % n))
    add_loop([(P(v).x, P(v).z) for v in rim], rim)
    add_loop(mouth_outer, MR[4])
    for sd in ("L", "R"):
        add_loop(eye_outer[sd], ER_[sd][1][-1])
    holes = [mouth_outer, eye_outer["L"], eye_outer["R"]]

    def in_hole(x, z, grow=1.0):
        for hpoly in holes:
            hx_ = sum(p[0] for p in hpoly) / len(hpoly); hz_ = sum(p[1] for p in hpoly) / len(hpoly)
            if inside([(hx_ + (p[0] - hx_) * grow, hz_ + (p[1] - hz_) * grow) for p in hpoly], x, z):
                return True
        return False
    rim2d = [Vector((P(v).x, P(v).z)) for v in rim]
    xs = [p[0] for p in poly]; zs = [p[1] for p in poly]
    z = min(zs); row = 0
    while z < max(zs):
        x = min(xs) + (s / 2 if row % 2 else 0)
        while x < max(xs):
            q = Vector((x, z))
            if inside(poly, x, z) and not in_hole(x, z, 1.12) and min((q - r).length for r in rim2d) > 0.55 * s:
                pts2.append((x, z)); kind.append(("free", None))
            x += s
        z += s * 0.866; row += 1
    res = G.delaunay_2d_cdt(pts2, edges2, [], 0, W * 1e-6)
    out_v, _, out_f, orig_v = res[0], res[1], res[2], res[3]
    to_in = []
    for oi, ov in enumerate(orig_v):   # points the triangulation added (constraint crossings) become free points
        if ov:
            to_in.append(ov[0])
        else:
            pts2.append(tuple(out_v[oi])); kind.append(("free", None)); to_in.append(len(pts2) - 1)
    faces2 = []
    for f in out_f:
        cxy = sum((Vector(out_v[i]) for i in f), Vector((0, 0))) / 3
        if inside(poly, cxy.x, cxy.y) and not in_hole(cxy.x, cxy.y):
            faces2.append([to_in[i] for i in f])
    # Laplacian smoothing of the free points (2D)
    nb = {}
    for f in faces2:
        for a_, b_ in ((f[0], f[1]), (f[1], f[2]), (f[2], f[0])):
            nb.setdefault(a_, set()).add(b_); nb.setdefault(b_, set()).add(a_)
    pv = [Vector(p) for p in pts2]
    for _ in range(8):
        new = {}
        for i, (kd, _) in enumerate(kind):
            if kd == "free" and i in nb:
                avg = sum((pv[j] for j in nb[i]), Vector((0, 0))) / len(nb[i])
                new[i] = pv[i].lerp(avg, 0.6)
        for i, q in new.items():
            pv[i] = q
    verts_of = []
    for i, (kd, v) in enumerate(kind):
        verts_of.append(v if kd != "free" else (new_vert(pv[i].x, pv[i].y) if i in nb else None))

    new_faces = []
    mat_idx = len(me.materials)                                 # the baked mask material (appended below)

    def make(vs):
        if len(set(vs)) < len(vs) or any(v is None for v in vs):
            return None
        try:
            f = bm.faces.new(vs)
        except ValueError:
            return None
        f.smooth = True
        f.material_index = mat_idx
        new_faces.append(f)
        return f
    for f in faces2:
        make([verts_of[i] for i in f])
    for i in range(NM // 2):
        make([U[i], U[i + 1], MR[1][i + 1], MR[1][i]])
    for i in range(NM // 2, NM):
        make([D[i], D[i + 1], MR[1][(i + 1) % NM], MR[1][i]])
    for k in range(1, 4):
        for i in range(NM):
            make([MR[k][i], MR[k][(i + 1) % NM], MR[k + 1][(i + 1) % NM], MR[k + 1][i]])
    for sd in ("L", "R"):
        c2, loops = ER_[sd]
        n = len(loops[0])
        for a_, b_ in zip(loops, loops[1:]):
            for i in range(n):
                make([a_[i], a_[(i + 1) % n], b_[(i + 1) % n], b_[i]])
        cv = new_vert(c2.x, c2.y)                              # cap over the painted eye (the eye step cuts it)
        for i in range(n):
            make([cv, loops[0][(i + 1) % n], loops[0][i]])
    report["mask_new_faces"] = len(new_faces)

    # ------------------------------------------------------------ orientation like the skin
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

    # ------------------------------------------------------------ planar UVs for the mask
    span = max(max(xs) - min(xs), max(zs) - min(zs)) * 1.02
    ux0, uz0 = (min(xs) + max(xs) - span) / 2, (min(zs) + max(zs) - span) / 2
    uvl = bm.loops.layers.uv.verify()
    for f in nf:
        for l in f.loops:
            p = P(l.vert)
            l[uvl].uv = ((p.x - ux0) / span, (p.z - uz0) / span)

    # ------------------------------------------------------------ bake the mask texture from the original
    res_px = int(job.get("bake_size", 2048))
    tmp_bm = bm.copy()
    keep = {f.index for f in nf}
    bmesh.ops.delete(tmp_bm, geom=[f for f in tmp_bm.faces if f.index not in keep], context="FACES")
    tmp_me = bpy.data.meshes.new("mask_bake"); tmp_bm.to_mesh(tmp_me); tmp_bm.free()
    tgt = bpy.data.objects.new("mask_bake", tmp_me); bpy.context.scene.collection.objects.link(tgt)
    tgt.matrix_world = fw.copy()
    bake_mat = bpy.data.materials.new("mask_bake"); bake_mat.use_nodes = True
    tmp_me.materials.clear(); tmp_me.materials.append(bake_mat)
    for p_ in tmp_me.polygons:
        p_.material_index = 0
    tex = bake_mat.node_tree.nodes.new("ShaderNodeTexImage")
    bake_mat.node_tree.nodes.active = tex
    sc = bpy.context.scene
    sc.render.engine = "CYCLES"
    try:
        sc.cycles.device = "CPU"; sc.cycles.samples = 16
    except AttributeError:
        pass
    sc.render.bake.use_selected_to_active = True
    sc.render.bake.cage_extrusion = 0.12 * W
    sc.render.bake.max_ray_distance = 0.4 * W
    sc.render.bake.margin = 8
    imgs = {}
    # no normal-map bake: tangent-space normals baked selected-to-active came out patchy per triangle; the relief
    # is in the geometry itself (the mask follows the surface)
    for name, btype, colour in (("color", "DIFFUSE", True), ("rough", "ROUGHNESS", False)):
        img = bpy.data.images.new("face_mask_" + name, res_px, res_px, alpha=False, float_buffer=False)
        if not colour:
            img.colorspace_settings.name = "Non-Color"
        tex.image = img
        bpy.ops.object.select_all(action="DESELECT")
        src.select_set(True); tgt.select_set(True)
        bpy.context.view_layer.objects.active = tgt
        kw = {"type": btype}
        if btype == "DIFFUSE":
            kw["pass_filter"] = {"COLOR"}
        bpy.ops.object.bake(**kw)
        img.pack()
        imgs[name] = img
    # the mask material on the face
    mm = bpy.data.materials.new("face_mask"); mm.use_nodes = True
    nt = mm.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tc = nt.nodes.new("ShaderNodeTexImage"); tc.image = imgs["color"]
    nt.links.new(tc.outputs["Color"], bsdf.inputs["Base Color"])
    tr = nt.nodes.new("ShaderNodeTexImage"); tr.image = imgs["rough"]
    nt.links.new(tr.outputs["Color"], bsdf.inputs["Roughness"])
    me.materials.append(mm)
    for ob in (src, tgt):
        d = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(d)
    sc.render.engine = "BLENDER_WORKBENCH"
    report["mask_bake_px"] = res_px
    return U[1:NM // 2], [D[i] for i in range(NM // 2 + 1, NM)], {U[0], U[NM // 2]}, set(U) | set(D.values())
