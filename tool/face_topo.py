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
    # an int layer to find kept vertices again after subdivide_edges; adding a layer reallocates the mesh too, so it
    # must exist before any vertex reference is taken (the caller's own vertex lists are not used past this call)
    if bm.verts.layers.int.get("ftag") is None:
        bm.verts.layers.int.new("ftag")
    dl = bm.verts.layers.deform.verify()
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

    def ray_near(x, z, ref_y):
        """the hit along the front ray nearest to depth ref_y (an overhanging nose hides the upper lip)"""
        o, d, best = Vector((x, ymin - W * 20, z)), Vector((0, 1, 0)), (None, None, None, None)
        for _ in range(8):
            h = skin_bvh.ray_cast(o, d, W * 80)
            if h[0] is None:
                break
            if best[0] is None or abs(h[0].y - ref_y) < abs(best[0].y - ref_y):
                best = h
            o = h[0] + d * (W * 1e-4)
        return best

    def new_vert(x, z, ref_y=None):
        h = ray(x, z) if ref_y is None else ray_near(x, z, ref_y)
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
    # centre inside the head, behind the face: every mask point is placed by a ray from here outward, so it lands on
    # the surface itself - also under the chin and on the side of the cheeks, where a front ray cannot reach
    C = Vector((cx, M.y + 1.0 * ipd, ((EL.z + ER.z) / 2 + M.z) / 2))
    R0 = ((EL + ER) / 2 - C).length

    def to_uv(p):
        d = p - C
        return Vector((math.atan2(d.x, -d.y) * R0, math.atan2(d.z, math.hypot(d.x, d.y)) * R0))

    def dir_of(u, v):
        az, el = u / R0, v / R0
        return Vector((math.sin(az) * math.cos(el), -math.cos(az) * math.cos(el), math.sin(el)))

    def ray_rad(u, v):
        return skin_bvh.ray_cast(C, dir_of(u, v), ipd * 6)

    last_r = [R0]

    def new_vert_uv(u, v):
        h = ray_rad(u, v)
        if h[0] is None:   # the ray slipped past the surface (a gap under the chin, a collar): the nearest skin
            h = skin_bvh.find_nearest(C + dir_of(u, v) * last_r[0])
            if h[0] is None:
                fail(f"нет кожи под маской лица в направлении ({u:.3g}, {v:.3g}): уменьшите маску")
            report["mask_ray_misses"] = report.get("mask_ray_misses", 0) + 1
        else:
            last_r[0] = (h[0] - C).length
        nv_ = bm.verts.new(finv @ h[0])
        for k, w in weights_at(h[0], h[2]).items():
            nv_[dl][k] = w
        return nv_

    # ------------------------------------------------------------ skin colour (hair fused to the face is told by colour)
    tex_px = {}

    def base_image(mi):
        m = me.materials[mi] if mi < len(me.materials) else None
        if mi in tex_px or m is None or not m.use_nodes:
            return tex_px.get(mi)
        bsdf_ = next((n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
        img, stack = None, [l_.from_node for l_ in bsdf_.inputs["Base Color"].links] if bsdf_ else []
        while stack and img is None:
            n = stack.pop()
            if n.type == "TEX_IMAGE" and n.image and n.image.size[0]:
                img = n.image
            else:
                stack += [l_.from_node for i_ in n.inputs for l_ in i_.links]
        if img is None:
            tex_px[mi] = None
            return None
        import numpy as np
        a_ = np.empty(img.size[0] * img.size[1] * 4, dtype=np.float32)
        img.pixels.foreach_get(a_)
        tex_px[mi] = (a_.reshape(img.size[1], img.size[0], 4)[..., :3], img.size[0], img.size[1])
        return tex_px[mi]
    uv_data = me.uv_layers.active.data if me.uv_layers.active else None

    def colour_at(p, ti):
        if uv_data is None or ti is None:
            return None
        t = tris[ti]
        px = base_image(t.material_index)
        if px is None:
            return None
        b = bary(t, p)
        uv = sum((uv_data[li].uv * max(0.0, w) for w, li in zip(b, t.loops)), Vector((0, 0)))
        arr, w_, h_ = px
        return Vector(arr[int(min(h_ - 1, max(0, (uv.y % 1.0) * h_))), int(min(w_ - 1, max(0, (uv.x % 1.0) * w_)))])

    def front_hit(x, z, ref_y=None):   # 3D point a front ray (nearest the reference depth) finds
        h = ray(x, z) if ref_y is None else ray_near(x, z, ref_y)
        return h[0]

    # ------------------------------------------------------------ rings: mouth (oval) and eyes
    half = (x1 - x0) / 2
    T_ = bl(job["lip_top"]) if job.get("lip_top") else Vector((cx, 0, line_z(cx) + 0.15 * W))
    B_ = bl(job["lip_bot"]) if job.get("lip_bot") else Vector((cx, 0, line_z(cx) - 0.2 * W))
    hu = max(W * 0.02, T_.z - line_z(T_.x)); hl = max(W * 0.02, line_z(B_.x) - B_.z)
    RINGS = [(1.0, 0.0), (1.04, 1.0), (1.14, 1.5), (1.28, 2.0), (1.42, 2.5)]
    HU = max(hu * 1.05, bl(job["limit_top"]).z - line_z(cx)) if job.get("limit_top") else 0.0
    NM = 32
    # a mouth modelled half-open: ring 0 runs along the inner lip edges and everything between them is cut out
    OT = max(0.0, bl(job["open_top"]).z - line_z(bl(job["open_top"]).x)) if job.get("open_top") else 0.0
    OB = max(0.0, line_z(bl(job["open_bot"]).x) - bl(job["open_bot"]).z) if job.get("open_bot") else 0.0
    OT, OB = min(OT, 0.9 * hu), min(OB, 0.9 * hl)          # inside the lip edges (ring 1)
    if OT or OB:
        report["mouth_open"] = [round(OT / W, 3), round(OB / W, 3)]

    def ring_up(h_):
        if h_ <= 1 or not HU:
            return hu * h_
        return hu + (HU - hu) * (h_ - 1) / (RINGS[-1][1] - 1)

    def mpt(k, i):
        a_, h_ = RINGS[k]
        th = 2 * math.pi * i / NM
        x = cx + half * a_ * math.cos(th)
        sn = math.sin(th)
        if k == 0:
            return x, line_z(x) + (OT if sn >= 0 else OB) * sn
        return x, line_z(x) + (ring_up(h_) if sn >= 0 else hl * h_) * sn

    def eye_grow(c2, p, sc):
        """a point of the eye loop sc times the eyelid outline; the growth is capped in ipd (up 0.08, sideways 0.25),
        so the loops around big cartoon eyes do not run into a fringe or the hair at the temples"""
        gx, gz = (p.x - c2.x) * (sc - 1), (p.y - c2.y) * (sc - 1)
        gx = max(-0.25 * ipd * (sc - 1), min(0.25 * ipd * (sc - 1), gx))
        gz = max(-0.12 * ipd * (sc - 1), min(0.08 * ipd * (sc - 1), gz))
        return p.x + gx, p.y + gz

    # points the mask must contain with a margin: the mouth's outer ring and the eyes' outer loops
    must = []
    for i in range(NM):
        q3 = front_hit(*mpt(4, i), ref_y=M.y)
        if q3 is not None:
            must.append(to_uv(q3))
    for rim2 in rims.values():
        c2 = sum(rim2, Vector((0, 0))) / len(rim2)
        for p in rim2:
            q3 = front_hit(*eye_grow(c2, p, 2.0))
            if q3 is not None:
                must.append(to_uv(q3))
    # ------------------------------------------------------------ mask outline (front view x, z)
    # the skin colour (nose, cheeks, brow skin; median): hair painted on the same surface is told by it
    refs = []
    for dx, dz in ((0, -0.35), (-0.45, -0.45), (0.45, -0.45), (-0.3, 0.45), (0.3, 0.45), (0, 0.5)):
        hq = skin_bvh.ray_cast(Vector(((EL.x + ER.x) / 2 + dx * ipd, ymin - W * 20, (EL.z + ER.z) / 2 + dz * ipd)), Vector((0, 1, 0)), W * 80)
        cq = colour_at(hq[0], hq[2]) if hq[0] is not None else None
        if cq is not None:
            refs.append(cq)
    skin_col = Vector([sorted(c[i] for c in refs)[len(refs) // 2] for i in range(3)]) if len(refs) >= 3 else None
    if skin_col is not None:
        report["skin_colour"] = [round(c, 3) for c in skin_col]
    if job.get("mask"):
        mpts = [to_uv(bl(p)) for p in job["mask"]]
        outline = catmull_closed(mpts, max(2, int(64 / len(mpts))))
    else:
        eu, cu = to_uv((EL + ER) / 2), to_uv(chin)
        # up to the hairline (the editor's handle; by default a low forehead line over the brows), down under the chin
        # (a point on the skin: the radial v is compressed up the forehead, so the default is set in 3D, not in v)
        em = (EL + ER) / 2
        ft = bl(job["face_top"]) if job.get("face_top") else front_hit(em.x, em.z + 0.62 * ipd)
        top = to_uv(ft).y if ft is not None else eu.y + 0.3 * ipd
        top, bot = max(top, eu.y + 0.1 * ipd), cu.y - 0.75 * ipd
        mz, hz = (top + bot) / 2, (top - bot) / 2
        hx = abs(to_uv(EL).x - to_uv(ER).x) / 2 + 0.9 * ipd
        cx_uv = eu.x
        outline, radii = [], []
        for i in range(48):
            th = 2 * math.pi * i / 48
            c, sn = math.cos(th), math.sin(th)
            r = 1.0 / (abs(c) ** 2.5 + abs(sn) ** 2.5) ** (1 / 2.5)       # superellipse
            good = 0.15
            hair_from = None                       # where the current stretch of hair colour began (k, point)
            for k in range(1, 41):     # the farthest point where the skin still faces forward (dips inside are fine)
                f_ = k / 40
                x, z = cx_uv + hx * c * r * f_, mz + hz * sn * r * f_
                h = ray_rad(x, z)
                if h[0] is None:
                    break
                q_ = h[0]
                # above the brows or past the outer eye corners: stop where hair hangs in front of the skin (a fringe,
                # curls at the temples); not around the eyes, where a brow ridge hides a little of the lid from the front
                if q_.z > M.z and (q_.z > max(EL.z, ER.z) + 0.15 * ipd or abs(q_.x - cx) > max(abs(EL.x - cx), abs(ER.x - cx)) + 0.3 * ipd):
                    fhit = ray(h[0].x, h[0].z)
                    if fhit[0] is not None and (h[0] - fhit[0]).length > 0.04 * ipd:
                        break
                    # hair painted on the same surface (a fringe fused to the forehead): seen from the front off the
                    # skin colour for longer than a brow is tall
                    cq = colour_at(fhit[0], fhit[2]) if skin_col is not None and fhit[0] is not None else None
                    if cq is not None and (cq - skin_col).length > 0.2:
                        hair_from = hair_from or (k, h[0].copy())
                        if (h[0] - hair_from[1]).length > 0.25 * ipd:
                            good = min(good, (hair_from[0] - 1) / 40)
                            report["mask_hair_stops"] = report.get("mask_hair_stops", 0) + 1
                            break
                    else:
                        hair_from = None
                if h[1].dot(dir_of(x, z)) > 0.3:     # the surface faces outward along the ray (not an ear or a fold)
                    good = f_
            if hair_from:      # the outline ends on hair: back to where it began
                good = min(good, (hair_from[0] - 1) / 40)
            good *= 0.96
            radii.append((c * r, sn * r, good))
        # never smaller than the rings it must hold (+0.05 ipd), then smoothed around so the outline stays a round shape
        for k, (ux, uz, g) in enumerate(radii):
            th = math.atan2(uz, ux)
            need = 0.0
            for q in must:
                dx, dz = (q.x - cx_uv) / hx, (q.y - mz) / hz
                if abs(((math.atan2(dz, dx) - th + math.pi) % (2 * math.pi)) - math.pi) < math.pi / 24:
                    d_uv = max(math.hypot(q.x - cx_uv, q.y - mz), 1e-9)
                    need = max(need, math.hypot(dx, dz) / max(math.hypot(ux, uz), 1e-9) * (1 + 0.05 * ipd / d_uv))
            radii[k] = (ux, uz, max(g, need))
        rs = [g for _, _, g in radii]
        for _ in range(3):
            rs = [max(rs[i], (rs[i - 1] + rs[i] + rs[(i + 1) % len(rs)]) / 3) if False else
                  (rs[i - 1] + 2 * rs[i] + rs[(i + 1) % len(rs)]) / 4 for i in range(len(rs))]
        for (ux, uz, g), r_ in zip(radii, rs):
            r_ = max(r_, g if g > 0 else r_)
            ou, ov = cx_uv + hx * ux * r_, mz + hz * uz * r_
            outline.append(Vector((max(cx_uv - hx, min(cx_uv + hx, ou)), max(bot, min(top, ov)))))
        report["mask_radii"] = [round(x, 2) for x in rs]
    poly = [(p.x, p.y) for p in outline]
    mcx = sum(p.x for p in outline) / len(outline); mcz = sum(p.y for p in outline) / len(outline)
    report["mask_points"] = len(outline)

    def in_mask(p):
        q = to_uv(p)
        return inside(poly, q.x, q.y)

    def front(p):   # on the outer skin as seen from the centre (not inner folds, not the back of an ear)
        d = p - C
        h = skin_bvh.ray_cast(C, d.normalized(), d.length + 0.3 * W)
        return h[0] is not None and abs((h[0] - C).length - d.length) < 0.15 * W

    def hair_sheet(f, c, n):
        """a thin sheet painted in hair colour (a lock fused to the forehead): never part of the mask"""
        if skin_col is None:
            return False
        if any(abs(c.x - e.x) < 0.6 * ipd and e.z - 0.1 * ipd < c.z < e.z + 0.45 * ipd for e in (EL, ER)):
            return False   # the brow band: a dark, thin brow ridge over the eye is skin, not a lock of hair
        hq = skin_bvh.find_nearest(c)
        cq = colour_at(hq[0], hq[2]) if hq[0] is not None else None
        if cq is None or (cq - skin_col).length <= 0.2:
            return False
        return skin_bvh.ray_cast(c - n * (W * 1e-3), -n, 0.25 * ipd)[0] is not None

    def skin_face(f):
        """the face is skin the mask replaces: seen first from the centre, or - hidden behind something, like a brow
        ridge overhanging the eye - still solid and close to that first surface. Thin sheets lying over the skin (hair
        strands, brow tufts) are not: they stay whole and move with the skin under them."""
        c = fw @ f.calc_center_median()
        f.normal_update()
        nf_ = (fw.to_3x3() @ f.normal).normalized()
        if nf_.length > 0.5 and hair_sheet(f, c, nf_):
            return False
        if front(c):
            return True
        # only over the eyes, where the brow ridge overhangs: elsewhere a thick lock of hair over the cheek would be
        # taken for skin and cut into the mask edge
        # ... and in the mouth, where the lips overhang a half-open mouth's painted teeth
        in_mouth = abs(c.x - cx) < half * 1.45 and line_z(c.x) - 2.6 * hl < c.z < line_z(c.x) + max(2.6 * hu, HU)
        if not in_mouth and not any(abs(c.x - e.x) < 0.6 * ipd and e.z - 0.1 * ipd < c.z < e.z + 0.8 * ipd for e in (EL, ER)):
            return False
        d = c - C
        h = skin_bvh.ray_cast(C, d.normalized(), d.length)
        if h[0] is None or d.length - (h[0] - C).length > 0.6 * ipd:
            return False
        f.normal_update()
        n = (fw.to_3x3() @ f.normal).normalized()
        if n.length < 0.5:
            return False
        t = skin_bvh.ray_cast(c - n * (W * 1e-3), -n, 0.25 * ipd)   # through the sheet: its other side is right there
        return t[0] is None

    # ------------------------------------------------------------ cut the old mesh along the outline
    rim = []
    for e in list(bm.edges):
        a, b = P(e.verts[0]), P(e.verts[1])
        ia, ib = in_mask(a), in_mask(b)
        if ia == ib or not any(skin_face(f) for f in e.link_faces):
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
    kill = [f for f in bm.faces if in_mask(fw @ f.calc_center_median()) and skin_face(f)]
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
        rim.sort(key=lambda v: math.atan2(to_uv(P(v)).y - mcz, to_uv(P(v)).x - mcx))
    else:
        rim = best
    report["mask_rim"] = len(rim)
    report["mask_deleted_faces"] = len(kill)
    if len(rim) < 12:
        fail("контур маски лица почти не пересёк сетку: проверьте маску")

    # depth chained ring by ring along each direction (slit outward), as the editor draws it: no jump onto the nose
    U = [new_vert(*mpt(0, i), ref_y=M.y) for i in range(NM // 2 + 1)]
    D = {NM // 2: U[NM // 2], NM: U[0]}
    for i in range(NM // 2 + 1, NM):
        D[i] = new_vert(*mpt(0, i), ref_y=M.y)
    prev = [P(U[i]) .y if i <= NM // 2 else P(D[i]).y for i in range(NM)]
    MR = {}
    for k in range(1, 5):
        MR[k] = []
        for i in range(NM):
            v_ = new_vert(*mpt(k, i), ref_y=prev[i])
            prev[i] = P(v_).y
            MR[k].append(v_)
    mouth_outer = [tuple(to_uv(P(v))) for v in MR[4]]
    EYE_SCALES = [1.0, 1.3, 1.65, 2.0]
    ER_ = {}
    eye_outer = {}
    for sd, rim2 in rims.items():
        c2 = sum(rim2, Vector((0, 0))) / len(rim2)
        loops = []
        # depth chained loop by loop from the eye's own surface (like the mouth rings): above the lid a front ray hits
        # the overhanging brow ridge first, which left shards along the upper lid
        h0 = ray(c2.x, c2.y)
        prev = [h0[0].y if h0[0] is not None else M.y] * len(rim2)
        for sc in EYE_SCALES:
            lp = [new_vert(*eye_grow(c2, p, sc), ref_y=prev[i]) for i, p in enumerate(rim2)]
            prev = [P(v).y for v in lp]
            loops.append(lp)
        ER_[sd] = (c2, loops)
        eye_outer[sd] = [tuple(to_uv(P(v))) for v in loops[-1]]

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
    add_loop([tuple(to_uv(P(v))) for v in rim], rim)
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
    rim2d = [to_uv(P(v)) for v in rim]
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
    if job.get("debug_uv"):
        import json as _j
        open(job["debug_uv"], "w").write(_j.dumps({"poly": poly, "rim": [list(to_uv(P(v))) for v in rim],
            "mouth": mouth_outer, "eyeL": eye_outer["L"], "eyeR": eye_outer["R"], "free": [p_ for p_, k_ in zip(pts2, kind) if k_[0] == "free"]}))
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
        verts_of.append(v if kd != "free" else (new_vert_uv(pv[i].x, pv[i].y) if i in nb else None))

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
        if job.get("eyes_open"):   # the eyeball step puts a ball here: the inner ring is the smooth eyelid edge
            continue
        cv = new_vert(c2.x, c2.y)                              # cap over the painted eye
        for i in range(n):
            make([cv, loops[0][(i + 1) % n], loops[0][i]])
    report["mask_new_faces"] = len(new_faces)

    # ------------------------------------------------------------ smoothing: subdivide the fill, relax, back onto the surface
    # (like Relax in sculpting tools): long thin triangles where the fill meets the rings become even. Rings, the slit,
    # the eyelid loops and the seam to the old mesh stay fixed.
    fixed = set(rim) | set(U) | set(D.values())
    for k in MR:
        fixed |= set(MR[k])
    for sd in ("L", "R"):
        for lp in ER_[sd][1]:
            fixed |= set(lp)
    ring_faces = {f for f in new_faces if f.is_valid and all(v in fixed for v in f.verts)}
    fill = [f for f in new_faces if f.is_valid and f not in ring_faces]
    levels = int(job.get("face_smooth", 1))
    if levels > 0 and fill:
        fill_set = set(fill)
        edges = [e for f in fill for e in f.edges
                 if all(g in fill_set for g in e.link_faces) or not all(v in fixed for v in e.verts)]
        edges = list({e for e in edges if not all(v in fixed for v in e.verts)})
        # subdivide_edges reallocates the mesh: every kept BMVert reference goes stale, so keep indices and re-look up
        # subdivide_edges reallocates the mesh: every kept BMVert reference goes stale. Tag the kept vertices in an
        # int layer (indices are not stable either) and look them up again by tag afterwards.
        tag = bm.verts.layers.int["ftag"]
        for v in bm.verts:
            v[tag] = 0
        keep_lists = {"U": U, "D": [D[k] for k in sorted(D)], "rim": rim}
        for k in MR:
            keep_lists["MR%d" % k] = MR[k]
        for sd in ER_:
            for j, lp in enumerate(ER_[sd][1]):
                keep_lists["E%s%d" % (sd, j)] = lp
        nid = 1
        ids = {}
        for name, vs in keep_lists.items():
            ids[name] = []
            for v in vs:
                if v[tag] == 0:
                    v[tag] = nid; nid += 1
                ids[name].append(v[tag])
        dkeys = sorted(D)
        bmesh.ops.subdivide_edges(bm, edges=edges, cuts=levels, use_grid_fill=True, use_only_quads=False)
        by_tag = {v[tag]: v for v in bm.verts if v[tag]}
        U = [by_tag[t] for t in ids["U"]]
        D = {k: by_tag[t] for k, t in zip(dkeys, ids["D"])}
        rim = [by_tag[t] for t in ids["rim"]]
        MR = {k: [by_tag[t] for t in ids["MR%d" % k]] for k in MR}
        ER_ = {sd: (ER_[sd][0], [[by_tag[t] for t in ids["E%s%d" % (sd, j)]] for j in range(len(ER_[sd][1]))]) for sd in ER_}
        fixed = set(rim) | set(U) | set(D.values())
        for k in MR:
            fixed |= set(MR[k])
        for sd in ("L", "R"):
            for lp in ER_[sd][1]:
                fixed |= set(lp)
        bmesh.ops.triangulate(bm, faces=[f for f in bm.faces if f.material_index == mat_idx and len(f.verts) > 4])
    new_faces = [f for f in bm.faces if f.material_index == mat_idx]
    movable = {v for f in new_faces for v in f.verts if v not in fixed}
    for _ in range(int(job.get("face_relax", 12))):
        target = {}
        for v in movable:
            nbs = [e.other_vert(v) for e in v.link_edges]
            if nbs:
                target[v] = v.co.lerp(sum((n.co for n in nbs), Vector()) / len(nbs), 0.5)
        for v, t in target.items():
            v.co = t
        for v in movable:   # back onto the original surface along the ray from the centre
            d = (fw @ v.co) - C
            h = skin_bvh.ray_cast(C, d.normalized(), ipd * 6)
            if h[0] is not None:
                v.co = finv @ h[0]
    for v in movable:       # skin weights where the point ended up
        p_ = fw @ v.co
        h = skin_bvh.find_nearest(p_)
        if h[2] is not None:
            v[dl].clear()
            for k, w in weights_at(h[0], h[2]).items():
                v[dl][k] = w
    report["mask_smoothed_points"] = len(movable)

    # ------------------------------------------------------------ orientation like the skin
    nf = [f for f in new_faces if f.is_valid]
    flipped = 0
    for f in nf:   # every face looks away from the centre inside the head
        f.normal_update()
        if (fw.to_3x3() @ f.normal).dot((fw @ f.calc_center_median()) - C) < 0:
            f.normal_flip(); flipped += 1
    report["mask_flipped"] = flipped

    # ------------------------------------------------------------ planar UVs for the mask
    span = max(max(xs) - min(xs), max(zs) - min(zs)) * 1.02
    ux0, uz0 = (min(xs) + max(xs) - span) / 2, (min(zs) + max(zs) - span) / 2
    uvl = bm.loops.layers.uv.verify()
    for f in nf:
        for l in f.loops:
            q = to_uv(P(l.vert))
            l[uvl].uv = ((q.x - ux0) / span, (q.y - uz0) / span)

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
    # the colour is baked as emission of the base colour: the DIFFUSE colour pass is base x (1 - metallic), which came
    # out darker than the old texture on Tripo's slightly metallic skin and left a line at the mask edge
    swaps = []
    for m in {s_.material for s_ in src.material_slots if s_.material and s_.material.use_nodes}:
        nt_ = m.node_tree
        out = next((n for n in nt_.nodes if n.type == "OUTPUT_MATERIAL" and n.is_active_output), None)
        bsdf_ = next((n for n in nt_.nodes if n.type == "BSDF_PRINCIPLED"), None)
        if out is None or bsdf_ is None:
            continue
        old = [l_.from_socket for l_ in out.inputs["Surface"].links]
        em = nt_.nodes.new("ShaderNodeEmission")
        bc = bsdf_.inputs["Base Color"]
        if bc.links:
            nt_.links.new(bc.links[0].from_socket, em.inputs["Color"])
        else:
            em.inputs["Color"].default_value = bc.default_value
        nt_.links.new(em.outputs["Emission"], out.inputs["Surface"])
        swaps.append((nt_, out, old, em))
    # tangent-space normal map baked from the old surface (its own normal map + the relief the relaxed mesh lost)
    passes = [("color", "EMIT", True), ("rough", "ROUGHNESS", False)]
    if job.get("bake_normal", True):   # the old skin's relief (its normal map + the detail the new mesh smooths away)
        passes.append(("normal", "NORMAL", False))
        sc.render.bake.normal_space = "TANGENT"
    for name, btype, colour in passes:
        img = bpy.data.images.new("face_mask_" + name, res_px, res_px, alpha=False, float_buffer=False)
        if not colour:
            img.colorspace_settings.name = "Non-Color"
        tex.image = img
        bpy.ops.object.select_all(action="DESELECT")
        src.select_set(True); tgt.select_set(True)
        bpy.context.view_layer.objects.active = tgt
        bpy.ops.object.bake(type=btype)
        img.pack()
        imgs[name] = img
        if btype == "EMIT":    # the materials are shared with the face: put the surfaces back before roughness
            for nt_, out, old, em in swaps:
                nt_.nodes.remove(em)
                for fs in old:
                    nt_.links.new(fs, out.inputs["Surface"])
    # the mask material on the face
    mm = bpy.data.materials.new("face_mask"); mm.use_nodes = True
    nt = mm.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    tc = nt.nodes.new("ShaderNodeTexImage"); tc.image = imgs["color"]
    nt.links.new(tc.outputs["Color"], bsdf.inputs["Base Color"])
    tr = nt.nodes.new("ShaderNodeTexImage"); tr.image = imgs["rough"]
    nt.links.new(tr.outputs["Color"], bsdf.inputs["Roughness"])
    if "normal" in imgs:
        tn = nt.nodes.new("ShaderNodeTexImage"); tn.image = imgs["normal"]
        nm = nt.nodes.new("ShaderNodeNormalMap")
        nt.links.new(tn.outputs["Color"], nm.inputs["Color"]); nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    me.materials.append(mm)
    for ob in (src, tgt):
        d = ob.data
        bpy.data.objects.remove(ob, do_unlink=True)
        bpy.data.meshes.remove(d)
    sc.render.engine = "BLENDER_WORKBENCH"
    report["mask_bake_px"] = res_px
    return U[1:NM // 2], [D[i] for i in range(NM // 2 + 1, NM)], {U[0], U[NM // 2]}, set(U) | set(D.values())
