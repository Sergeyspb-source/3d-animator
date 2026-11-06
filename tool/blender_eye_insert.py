"""Runs INSIDE Blender (background): cut the painted eyes out of a rigged head and put eyeballs behind the openings.

    blender -b -P blender_eye_insert.py -- job.json

job.json: {"source": rigged.glb, "out": out.glb, "eyes_glb": face-parts eyes.glb (iris along -Y, radius kit_r),
           "kit_r": 0.012, "sides": {"L": {"outline": [[x,y,z] x4 (inner, top, outer, bottom), glTF], "bone": name}, "R": ...},
           "head_bone": name, "preview": path.png (optional), "report": path.json (optional)}

Per eye: the 4 outline clicks become a smooth closed curve (Catmull-Rom). Faces of the head in front of the eye whose
centre falls inside that curve (front view) are deleted - the opening's rim is the eyelid. The eyeball's front is set
just behind the old painted surface and its radius is solved so the rim lies on the ball (no gap, no poke-through):
for a rim point at lateral offset (dx, dz) and depth a behind the front, r = (dx^2 + dz^2 + a^2) / (2a), averaged.
The ball gets 100 % of its eye bone, whose head is moved to the ball centre (only the ball is weighted to it).
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree
sys.path.insert(0, str(Path(__file__).resolve().parent))   # Blender does not put the script's folder on the path
from i18n import t as _t

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))


def fail(msg):
    print("EYES_FAIL " + msg, flush=True)
    sys.exit(1)


def bl(p):
    return Vector((p[0], -p[2], p[1]))


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["source"])
arm = next(o for o in bpy.data.objects if o.type == "ARMATURE")
for o in list(bpy.data.objects):
    if o.type == "MESH" and not o.vertex_groups:
        bpy.data.objects.remove(o, do_unlink=True)
meshes = [o for o in bpy.data.objects if o.type == "MESH" and o.name != "Mouth"]
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
report = {"eyes": {}}


def catmull(pts, n=12):
    """closed Catmull-Rom through 4+ points -> list of points"""
    out = []
    k = len(pts)
    for i in range(k):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % k], pts[(i + 2) % k]
        for s in range(n):
            t = s / n
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return out


def inside(poly, x, z):
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, zi = poly[i]; xj, zj = poly[j]
        if (zi > z) != (zj > z) and x < (xj - xi) * (z - zi) / (zj - zi + 1e-12) + xi:
            c = not c
        j = i
    return c


# the eyeball template
bpy.ops.import_scene.gltf(filepath=job["eyes_glb"])
kit = next(o for o in bpy.data.objects if o.type == "MESH" and o.name.startswith("Eye_L"))
kit_r = float(job.get("kit_r", 0.012))
kit.location = (0, 0, 0)   # the mesh data is already centred on the ball; only the object was offset
kit.name = kit.data.name = "_eye_template"   # free the Eye_L / Eye_R names for the real balls
bpy.context.view_layer.update()
for o in list(bpy.data.objects):
    if o.type == "MESH" and o.name.startswith("Eye_") and o is not kit:
        bpy.data.objects.remove(o, do_unlink=True)



_px_cache = {}


def base_pixels(mat):
    """(pixels HxWx3, w, h, image node) of the image behind a material's base colour, or None (cached per material)"""
    if mat is None or not mat.use_nodes:
        return None
    if mat.name not in _px_cache:
        _px_cache[mat.name] = _base_pixels(mat)
    return _px_cache[mat.name]


def _base_pixels(mat):
    bsdf = next((n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED"), None)
    stack = [l.from_node for l in bsdf.inputs["Base Color"].links] if bsdf else []
    while stack:
        n = stack.pop()
        if n.type == "TEX_IMAGE" and n.image and n.image.size[0]:
            import numpy as np
            a_ = np.empty(n.image.size[0] * n.image.size[1] * 4, dtype=np.float32)
            n.image.pixels.foreach_get(a_)
            return a_.reshape(n.image.size[1], n.image.size[0], 4)[..., :3], n.image.size[0], n.image.size[1], n
        stack += [l.from_node for i in n.inputs for l in i.links]
    return None


def iris_colour():
    """the colour of the painted iris on the rigged model (before any cut): a grid of front rays inside each eye
    outline; the white (sclera), the dark (pupil, lashes) and the grey are dropped, the median of the rest is the iris"""
    src = job.get("iris_from")
    if not src or not Path(src).exists():
        return None
    import numpy as np
    from mathutils.geometry import barycentric_transform
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=src)
    new = [o for o in bpy.data.objects if o not in before]
    found = []
    for o in new:
        if o.type != "MESH":
            continue
        me = o.data; me.calc_loop_triangles()
        wv = [o.matrix_world @ v.co for v in me.vertices]
        tris = list(me.loop_triangles)
        bvh_ = BVHTree.FromPolygons(wv, [tuple(t.vertices) for t in tris])
        uvd = me.uv_layers.active.data if me.uv_layers.active else None
        for spec in job["sides"].values():
            pts = [bl(p) for p in spec["outline"]]
            cx_ = sum(p.x for p in pts) / 4; cz_ = sum(p.z for p in pts) / 4
            poly_ = [(cx_ + (p.x - cx_) * 0.8, cz_ + (p.z - cz_) * 0.8) for p in catmull(pts, 8)]
            x0, x1 = min(q[0] for q in poly_), max(q[0] for q in poly_)
            z0, z1 = min(q[1] for q in poly_), max(q[1] for q in poly_)
            for i in range(16):
                for j in range(16):
                    x, z = x0 + (x1 - x0) * (i + 0.5) / 16, z0 + (z1 - z0) * (j + 0.5) / 16
                    if not inside(poly_, x, z):
                        continue
                    h = bvh_.ray_cast(Vector((x, min(p.y for p in pts) - 10 * (x1 - x0), z)), Vector((0, 1, 0)), 100 * (x1 - x0))
                    if h[0] is None or uvd is None:
                        continue
                    t = tris[h[2]]
                    px = base_pixels(me.materials[t.material_index] if t.material_index < len(me.materials) else None)
                    if px is None:
                        continue
                    A, B, C = (wv[k] for k in t.vertices)
                    bc = barycentric_transform(h[0], A, B, C, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
                    uv = sum((uvd[li].uv * max(0.0, w) for w, li in zip(bc, t.loops)), Vector((0, 0)))
                    arr, w_, h_ = px[0], px[1], px[2]
                    col = arr[int(min(h_ - 1, (uv.y % 1) * h_)), int(min(w_ - 1, (uv.x % 1) * w_))]
                    v_ = float(col.max()); sat = (v_ - float(col.min())) / max(v_, 1e-6)
                    if v_ > 0.12 and sat > 0.25 and not (v_ > 0.85 and sat < 0.3):
                        found.append(col.copy())
    for o in new:
        if o.type == "MESH":
            d = o.data
            bpy.data.objects.remove(o, do_unlink=True)
            bpy.data.meshes.remove(d)
        else:
            bpy.data.objects.remove(o, do_unlink=True)
    if len(found) < 8:
        return None
    return np.median(np.array(found), axis=0)


def tint_kit_iris(target):
    """multiply the kit's saturated (iris) pixels so their median becomes the target; pupil, white and highlights stay"""
    import numpy as np
    mat = kit.material_slots[0].material if kit.material_slots else None
    px = base_pixels(mat)
    if px is None:
        return None
    arr, w_, h_, node = px
    v_ = arr.max(axis=2); sat = (v_ - arr.min(axis=2)) / np.maximum(v_, 1e-6)
    iris = (sat > 0.2) & (v_ > 0.08)
    if iris.sum() < 50:
        return None
    med = np.median(arr[iris], axis=0)
    out = arr.copy()
    out[iris] = np.clip(arr[iris] * (np.asarray(target) / np.maximum(med, 1e-3)), 0, 1)
    img = bpy.data.images.new("eye_iris_tinted", w_, h_, alpha=False)
    img.pixels.foreach_set(np.concatenate([out, np.ones((h_, w_, 1), np.float32)], axis=2).ravel())
    img.pack()
    node.image = img
    return [round(float(c), 3) for c in target]


face = None
balls = []
solved = {}
for side, spec in job["sides"].items():
    rim3 = [bl(p) for p in spec["outline"]]
    curve = catmull(rim3, 10)
    poly = [(p.x, p.z) for p in curve]
    cx = sum(p.x for p in curve) / len(curve); cz = sum(p.z for p in curve) / len(curve)
    width = max(p.x for p in curve) - min(p.x for p in curve)
    if face is None:   # the mesh that holds the eye region
        # the skin, not the mouth parts the cut put inside (on a small face the teeth lie within reach of the eye)
        skins = [o for o in meshes if not o.name.startswith(("Teeth_", "Gum_", "Tongue", "MouthCavity", "Eye"))] or meshes
        face = max(skins, key=lambda o: sum(1 for v in o.data.vertices if ((o.matrix_world @ v.co) - Vector((cx, rim3[0].y, cz))).length < width * 2))
        fw = face.matrix_world
    # the painted surface in front of the aperture centre (before cutting)
    face.data.calc_loop_triangles()
    wv = [fw @ v.co for v in face.data.vertices]
    bvh = BVHTree.FromPolygons(wv, [tuple(t.vertices) for t in face.data.loop_triangles])
    ymin = min(v.y for v in wv)
    hit = bvh.ray_cast(Vector((cx, ymin - width * 20, cz)), Vector((0, 1, 0)), width * 80)
    if hit[0] is None and not job.get("open_rim"):
        fail(_t("blender.no_surface_in_front_of_eye_check_the", side))
    front_y = hit[0].y if hit[0] is not None else 0.0
    rim_surf = []
    for p in curve:
        if job.get("open_rim"):   # the opening is cut already: a ray right on the rim may pass through the hole
            p = Vector((cx, p.y, cz)) + (p - Vector((cx, p.y, cz))) * 1.08
        h = bvh.ray_cast(Vector((p.x, ymin - width * 20, p.z)), Vector((0, 1, 0)), width * 80)
        if h[0] is not None:
            rim_surf.append(h[0])
    if len(rim_surf) < len(curve) * 0.7:
        fail(_t("blender.eye_outline_goes_outside_the_model", side, len(rim_surf), len(curve)))
    if job.get("open_rim"):   # face retopology left a clean hole: the eyelid edge sets the depth, nothing is cut
        front_y = sum(p.y for p in rim_surf) / len(rim_surf) - width * 0.06
    # cut: delete faces in front of the eye whose centre is inside the outline
    bm = bmesh.new(); bm.from_mesh(face.data)
    inv = fw.inverted()
    # cut exactly along the eyelid outline (like the mouth cut): edges crossing it are split at the crossing (UVs and
    # weights interpolated), faces joined along it, then the inside goes - the rim is the smooth curve, not stair steps
    front = lambda p: p.y < front_y + width * 0.6
    ins = lambda p: inside(poly, p.x, p.z)
    kill = []
    if not job.get("open_rim"):
        cuts = set()
        for e in list(bm.edges):
            a_, b_ = fw @ e.verts[0].co, fw @ e.verts[1].co
            if ins(a_) == ins(b_) or not (front(a_) or front(b_)):
                continue
            lo, hi = 0.0, 1.0
            for _ in range(16):
                m_ = (lo + hi) / 2
                if ins(a_.lerp(b_, m_)) == ins(a_):
                    lo = m_
                else:
                    hi = m_
            _, nv = bmesh.utils.edge_split(e, e.verts[0], (lo + hi) / 2)
            cuts.add(nv)
        for f in list(bm.faces):
            cv = [v for v in f.verts if v in cuts]
            if len(cv) == 2 and not any(cv[1] in e.verts for e in cv[0].link_edges):
                try:
                    bmesh.ops.connect_verts(bm, verts=cv)
                except Exception:
                    pass
        for f in bm.faces:
            c = fw @ f.calc_center_median()
            if front(c) and ins(c):
                kill.append(f)
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    loose = [v for v in bm.verts if not v.link_faces]
    bmesh.ops.delete(bm, geom=loose, context="VERTS")
    bm.to_mesh(face.data); bm.free()
    # radius from the rim: the ball front 8 % of the opening width behind the painted surface
    gap = width * 0.08
    rs = []
    for p in rim_surf:
        dx, dz, a = p.x - cx, p.z - cz, p.y - (front_y + gap)
        if a > width * 0.02:
            rs.append((dx * dx + dz * dz + a * a) / (2 * a))
    # cornea at the lid plane like a real eye (the old "rim on the ball" fit sank deep-set eyes far back)
    # natural proportion: the iris (32 deg cap) about half the opening wide -> r = 0.42 width; the cornea just behind
    # the painted eye / the middle of the lids, whichever is further forward (forward = -y)
    lids = [p for p in rim_surf if abs(p.x - cx) < 0.15 * width] or rim_surf
    yl = sum(p.y for p in lids) / len(lids)
    r = 0.42 * width
    front_y, gap = min(front_y if hit[0] is not None else yl, yl), 0.02 * width
    solved[side] = dict(r=r, cx=cx, cz=cz, front_y=front_y, gap=gap, rim=rim_surf, width=width, kill=len(kill), bone=spec.get("bone"),
                        ball=spec.get("ball"), ball_r=spec.get("ball_r"), curve=curve, corners=(rim3[0], rim3[2]))
_iris = iris_colour()
if _iris is not None:
    report["iris_colour"] = tint_kit_iris(_iris)
for side, sv in solved.items():
    r = sum(v["r"] for v in solved.values()) / len(solved) if job.get("sym", True) else sv["r"]
    cx, cz, front_y, gap, rim_surf, width = sv["cx"], sv["cz"], sv["front_y"], sv["gap"], sv["rim"], sv["width"]
    centre = Vector((cx, front_y + gap + r, cz))
    if sv.get("ball") and sv.get("ball_r"):   # placed by hand in the editor
        centre, r = bl(sv["ball"]), float(sv["ball_r"])
    ball = kit.copy(); ball.data = kit.data.copy(); bpy.context.scene.collection.objects.link(ball)
    ball.name = ball.data.name = f"Eye_{side}"
    ball.data.transform(Matrix.Scale(r / kit_r, 4))
    ball.matrix_world = Matrix.Translation(centre)
    bpy.context.view_layer.update()
    bpy.ops.object.select_all(action="DESELECT"); ball.select_set(True); bpy.context.view_layer.objects.active = ball
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bone = sv["bone"] or job["head_bone"]
    g = ball.vertex_groups.new(name=bone)
    g.add(list(range(len(ball.data.vertices))), 1.0, "REPLACE")
    m = ball.modifiers.new("Armature", "ARMATURE"); m.object = arm
    ball.parent = arm; ball.matrix_parent_inverse = arm.matrix_world.inverted()
    balls.append((ball, bone, centre, r))
    sv["centre"], sv["r_ball"] = centre, r
    rim_err = [abs((p - centre).length - r) for p in rim_surf]
    # dark socket behind the ball: what shows in the corners of the opening is a shadowed orbit, not the background
    # The cup runs from the eyelid edge itself back around the ball, so no angle shows a gap between the lid and the
    # socket: per rim direction (azimuth about the gaze axis) a meridian from the lid edge, tucked just behind the
    # skin, sweeps back to 1.12 r behind the ball and closes at the back pole.
    sm_me = bpy.data.meshes.new(f"EyeSocket_{side}")
    sock = bpy.data.objects.new(sm_me.name, sm_me); bpy.context.scene.collection.objects.link(sock)
    bm = bmesh.new()
    gz = Vector((0, -1, 0))                                   # gaze (forward)
    rim_pts = [p for p in (sv.get("curve_surf") or rim_surf)]
    rim_pts = rim_pts[::max(1, len(rim_pts) // 40)]
    R1 = r * 1.12
    meridians = []
    for p in rim_pts:
        d = p - centre
        lat = d - gz * d.dot(gz)
        if lat.length < 1e-9:
            continue
        ax = lat.normalized()
        th0 = math.atan2(lat.length, d.dot(gz))               # angle of the lid edge from the gaze axis
        rho0 = max(d.length - 0.04 * width, R1 * 0.98)        # just behind the lid skin
        col = []
        for k in range(9):
            t = k / 8
            th = th0 + (math.pi * 0.92 - th0) * t
            rho = rho0 + (R1 - rho0) * min(1.0, t * 2.5)
            col.append(bm.verts.new(centre + (gz * math.cos(th) + ax * math.sin(th)) * rho))
        meridians.append(col)
    pole = bm.verts.new(centre - gz * R1)
    m_ = len(meridians)
    for i in range(m_):
        a_, b_ = meridians[i], meridians[(i + 1) % m_]
        for k in range(len(a_) - 1):
            bm.faces.new((a_[k], b_[k], b_[k + 1], a_[k + 1]))
        bm.faces.new((a_[-1], b_[-1], pole))
    bm.normal_update()
    for f in bm.faces:                                        # seen from inside: normals toward the ball centre
        if f.normal.dot(centre - f.calc_center_median()) < 0:
            f.normal_flip()
    bm.to_mesh(sm_me); bm.free()
    for pl in sm_me.polygons:
        pl.use_smooth = True
    bpy.ops.object.select_all(action="DESELECT"); sock.select_set(True); bpy.context.view_layer.objects.active = sock
    if "eye_socket" not in bpy.data.materials:
        sm = bpy.data.materials.new("eye_socket"); sm.use_nodes = True
        sb = next(n for n in sm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        sb.inputs["Base Color"].default_value = (0.05, 0.02, 0.02, 1); sb.inputs["Roughness"].default_value = 0.8
    sock.data.materials.append(bpy.data.materials["eye_socket"])
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    sg = sock.vertex_groups.new(name=job["head_bone"]); sg.add(list(range(len(sock.data.vertices))), 1.0, "REPLACE")
    sm_ = sock.modifiers.new("Armature", "ARMATURE"); sm_.object = arm
    sock.parent = arm; sock.matrix_parent_inverse = arm.matrix_world.inverted()
    if job.get("lid_shells", True):
        # with the eyelid shells the opening round the ball is theirs: the cup's front lip, at the opening's edge,
        # stood out in front of an uneven skin in dark flaps over the eye (women_young, man_young)
        bpy.data.objects.remove(sock, do_unlink=True)
    report["eyes"][side] = {"radius": round(r, 4), "opening_width": round(width, 4), "deleted_faces": sv["kill"],
                            "rim_off_ball_mean": round(sum(rim_err) / len(rim_err), 4)}
bpy.data.objects.remove(kit, do_unlink=True)


# ------------------------------------------------------------------ eyelid keys (ARKit names; lipsync.py drives them)
def lid_keys():
    """eyeBlink / eyeSquint / eyeWide per side. The lid skin turns about the ball centre on the lateral axis, so it
    slides over the ball like a real lid; upper and lower lids meet a quarter of the way up from the lower lid.
    Each vertex turns by the angle its nearest rim point needs, faded by its distance from the rim."""
    if face.data.shape_keys is None:
        face.shape_key_add(name="Basis")
    fw_, inv_ = face.matrix_world, face.matrix_world.inverted()
    pts = [fw_ @ v.co for v in face.data.vertices]
    # glTF splits vertices along UV / normal seams: twins at one position are joined for the walk over the skin
    tol = max((max(p.x for p in pts) - min(p.x for p in pts)) * 1e-5, 1e-9)
    key_of, twins = {}, []
    for i, p in enumerate(pts):
        k_ = (round(p.x / tol), round(p.y / tol), round(p.z / tol))
        if k_ not in key_of:
            key_of[k_] = len(twins); twins.append([])
        twins[key_of[k_]].append(i)
    grp = [0] * len(pts)
    for g_, members in enumerate(twins):
        for i in members:
            grp[i] = g_
    nbr = [set() for _ in pts]
    for e in face.data.edges:
        a_, b_ = e.vertices
        for i in twins[grp[a_]]:
            nbr[i].add(b_)
        for i in twins[grp[b_]]:
            nbr[i].add(a_)
    moves = {}                                   # key name -> {vertex index: new world position}
    for side, sv in solved.items():
        c, r, curve, width = sv["centre"], sv["r_ball"], sv["curve"], sv["width"]
        ci, co = sv["corners"]
        z_mid = lambda x: ci.z + (co.z - ci.z) * (x - ci.x) / ((co.x - ci.x) or 1e-9)
        up = sorted([p for p in curve if p.z >= z_mid(p.x)], key=lambda p: p.x)
        lo = sorted([p for p in curve if p.z < z_mid(p.x)], key=lambda p: p.x)
        if len(up) < 3 or len(lo) < 3:
            continue

        def interp(seq, x, f):
            if x <= seq[0].x:
                return f(seq[0])
            for a, b in zip(seq, seq[1:]):
                if x <= b.x:
                    t = (x - a.x) / ((b.x - a.x) or 1e-9)
                    return f(a) * (1 - t) + f(b) * t
            return f(seq[-1])
        ang = lambda q: math.atan2(q.z - c.z, c.y - q.y)        # elevation about the ball centre (forward = -y)

        def need(p, x):   # how far (radians, + = down) a rim point turns to reach the closed line at x
            zc = interp(lo, x, lambda q: q.z) + 0.25 * (interp(up, x, lambda q: q.z) - interp(lo, x, lambda q: q.z))
            rho = max((p - c).length, 1e-9)
            return ang(p) - math.asin(max(-1.0, min(1.0, (zc - c.z) / rho)))
        d_up = [(p.x, need(p, p.x)) for p in up]
        d_lo = [(p.x, need(p, p.x)) for p in lo]

        def dval(tab, x):
            if x <= tab[0][0]:
                return tab[0][1]
            for (xa, va), (xb, vb) in zip(tab, tab[1:]):
                if x <= xb:
                    t = (x - xa) / ((xb - xa) or 1e-9)
                    return va * (1 - t) + vb * t
            return tab[-1][1]
        x0_, x1_ = min(p.x for p in curve), max(p.x for p in curve)
        # the lid skin = what is connected to the rim through the mesh within reach (a lock of hair lying in front of
        # the eye touches it only far away); seeds: vertices on the rim, at the rim's own depth
        import heapq
        dist = {}
        heap = []
        for i, p in enumerate(pts):
            if abs(p.x - sv["cx"]) > width or abs(p.z - sv["cz"]) > width:
                continue
            q = min(curve, key=lambda q_: math.hypot(p.x - q_.x, p.z - q_.z))
            if math.hypot(p.x - q.x, p.z - q.z) < 0.06 * width and abs(p.y - q.y) < 0.3 * width and p.y < c.y:
                dist[i] = 0.0; heap.append((0.0, i))
        heapq.heapify(heap)
        while heap:
            d0, i = heapq.heappop(heap)
            if d0 > dist.get(i, 1e9):
                continue
            for j in nbr[i]:
                d1 = d0 + (pts[i] - pts[j]).length
                if d1 < 0.6 * width and d1 < dist.get(j, 1e9):
                    for t_ in twins[grp[j]]:
                        dist[t_] = d1
                    heapq.heappush(heap, (d1, j))
        name = {"L": "Left", "R": "Right"}.get(side, side)
        # with the eyelid shells (lid_shells) closing the eye, the skin stays: turned all the way, the source's ragged
        # cut edge closed in teeth and pieces far from the ball flew forward (women_young); even a quarter of the way
        # it lay in stripes over the closed shell (man_young)
        sk = float(job.get("skin_lid_share", 0.0 if job.get("lid_shells", True) else 1.0))
        for key, a_up, a_lo in (("eyeBlink", sk, sk), ("eyeSquint", 0.18 * sk, 0.55 * sk), ("eyeWide", -0.35 * sk, -0.12 * sk)):
            mv = moves.setdefault(key + name, {})
            for i, gd in dist.items():
                p = pts[i]
                d = max(gd, min(math.hypot(p.x - q.x, p.z - q.z) for q in curve))
                upper = p.z >= z_mid(p.x)
                reach = (0.42 if upper else 0.3) * width
                if d > reach:
                    continue
                t = min(1.0, (reach - d) / (0.88 * reach))      # the lid edge band moves fully
                w = (t * t * (3 - 2 * t)) ** 1.4      # soft toward the brow: no fold under a brow ridge
                xc = max(x0_, min(x1_, p.x))
                dlt = (dval(d_up, xc) * a_up if upper else dval(d_lo, xc) * a_lo) * w
                q = p - c
                fwd, rho = -q.y, math.hypot(q.y, q.z)
                phi = math.atan2(q.z, fwd) - dlt
                nq = Vector((q.x, -rho * math.cos(phi), rho * math.sin(phi)))
                lim = min(q.length, r * 1.03)     # the lid stays on the ball (skin already inside it at rest stays)
                if nq.length < lim:
                    nq = nq.normalized() * lim
                mv[i] = c + nq
    kb_names = []
    for key, mv in moves.items():
        old = face.data.shape_keys.key_blocks.get(key)
        if old is not None:
            face.shape_key_remove(old)
        kb = face.shape_key_add(name=key, from_mix=False)
        for i, q in mv.items():
            kb.data[i].co = inv_ @ q
        kb_names.append(key)
    return kb_names


if face is not None and job.get("lid_keys", True):
    report["lid_keys"] = lid_keys()


# ------------------------------------------------------------------ eyelid shells (the user's idea)
def lid_shells():
    """Eyelids of their own over each ball (the user's idea): an upper and a lower shell, parts of spheres just over
    the eye (1.05 and 1.02 times its cornea's bulge), skin coloured, with a dark rim, behind the face's skin - seen only through the eye
    opening. Blinking turns the upper shell down about the ball's lateral axis and the lower one a little up; the
    upper, the bigger, closes over the lower: the closing line is the upper shell's smooth edge, whatever the face's
    mesh round the eye is like (the skin itself stays, lid_keys). Squint and wide turn them part way. Meshes of their own (EyeLid_L / _R) on the head
    bone, with the keys of the skin's names, so the editor, lip sync and Godot drive them with the face."""
    made = []
    uvl = face.data.uv_layers.active
    for side, sv in solved.items():
        c, r, curve, width = sv["centre"], sv["r_ball"], sv["curve"], sv["width"]
        ci, co = sv["corners"]
        z_mid = lambda x: ci.z + (co.z - ci.z) * (x - ci.x) / ((co.x - ci.x) or 1e-9)
        up = sorted([p for p in curve if p.z >= z_mid(p.x)], key=lambda p: p.x)
        lo = sorted([p for p in curve if p.z < z_mid(p.x)], key=lambda p: p.x)
        if len(up) < 3 or len(lo) < 3:
            continue
        ang = lambda q: math.atan2(q.z - c.z, c.y - q.y)        # elevation about the ball's centre (forward = -y)

        def at(seq, x, f):
            if x <= seq[0].x:
                return f(seq[0])
            for a_, b_ in zip(seq, seq[1:]):
                if x <= b_.x:
                    t = (x - a_.x) / ((b_.x - a_.x) or 1e-9)
                    return f(a_) * (1 - t) + f(b_) * t
            return f(seq[-1])
        e_up, e_lo = (lambda x: at(up, x, ang)), (lambda x: at(lo, x, ang))
        meet = lambda x, k: e_lo(x) + k * (e_up(x) - e_lo(x))
        # just over the ball, the upper over the lower; behind the face's skin, seen only through the eye opening.
        # (Sized to the opening's own edge they stood in front of the face as domes and boxes and never blended in)
        # (from the eye's mesh as built: its cornea bulges past the ball's radius and showed through a shell of 1.06 r)
        bulge = max([(v.co - c).length for b_, _bn, cc, _r in balls if (cc - c).length < 1e-6 for v in b_.data.vertices] or [r])
        R_lo, R_up = 1.02 * bulge, 1.05 * bulge
        # the face's skin, seen from the front: away from its edge a shell stays behind it
        fv = [face.matrix_world @ v.co for v in face.data.vertices]
        face.data.calc_loop_triangles()
        sbvh = BVHTree.FromPolygons(fv, [tuple(t.vertices) for t in face.data.loop_triangles])
        ymin_ = min(v.y for v in fv)

        def behind_skin(p, rmin):   # p pulled in toward the centre until the skin is in front of it (not inside rmin)
            h = sbvh.ray_cast(Vector((p.x, ymin_ - 20 * width, p.z)), Vector((0, 1, 0)), 80 * width)
            if h[0] is None or h[0].y >= p.y - 0.004 * width:
                return p
            q = p - c
            for k_ in range(12):
                L = q.length * (1 - 0.03 * (k_ + 1))
                if L <= rmin:
                    return c + q.normalized() * rmin
                p2 = c + q.normalized() * L
                h = sbvh.ray_cast(Vector((p2.x, ymin_ - 20 * width, p2.z)), Vector((0, 1, 0)), 80 * width)
                if h[0] is None or h[0].y < p2.y - 0.004 * width:
                    return p2
            return c + q.normalized() * rmin
        # the skin's colour over the eye (the face's own texture, round the upper lid and below the brow)
        cols = []
        if uvl is not None:
            for poly in face.data.polygons:
                q = face.matrix_world @ poly.center
                if not (up[0].x < q.x < up[-1].x) or q.y > c.y:
                    continue
                # under the brow and on the cheek under the eye (not just over it: the crease and the lashes are dark;
                # not one side only: a light patch over one eye made that lid pale)
                zu, zl_ = at(up, q.x, lambda p_: p_.z), at(lo, q.x, lambda p_: p_.z)
                if not (zu + 0.4 * r < q.z < zu + 1.3 * r or zl_ - 1.2 * r < q.z < zl_ - 0.4 * r):
                    continue
                pix = base_pixels(face.data.materials[poly.material_index] if poly.material_index < len(face.data.materials) else None)
                if pix is None:
                    continue
                arr, w_, h_ = pix[0], pix[1], pix[2]
                uv = sum((uvl.data[li].uv for li in poly.loop_indices), Vector((0, 0))) / poly.loop_total
                cols.append(arr[int(min(h_ - 1, max(0, (uv.y % 1.0) * h_))), int(min(w_ - 1, max(0, (uv.x % 1.0) * w_)))])
        col = [sorted(c_[k] for c_ in cols)[len(cols) // 2] for k in range(3)] if cols else [0.55, 0.45, 0.3]
        # the texture's pixels are sRGB, a material's colour is linear (taken as it is, the lid came out pale cream)
        col = [((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92 for v in col]
        NC, NR = 33, 10
        bm = bmesh.new()
        lay = []   # (column x, rows of verts) per shell
        for sgn, R, edge, far in ((1, R_up, e_up, math.radians(125)), (-1, R_lo, e_lo, math.radians(-110))):
            grid = []
            for i in range(NC):
                th = math.radians(-82 + 164 * i / (NC - 1))
                qx, rho = R * math.sin(th), R * math.cos(th)
                e = edge(c.x + qx)
                row = []
                for j in range(NR):
                    ph = e + (far - e) * (j / (NR - 1)) ** 1.3
                    p3 = c + Vector((qx, -rho * math.cos(ph), rho * math.sin(ph)))
                    row.append(bm.verts.new(p3 if j == 0 or not job.get("lid_tuck", False) else behind_skin(p3, 1.01 * r)))
                grid.append(row)
            for i in range(NC - 1):
                for j in range(NR - 1):
                    f = bm.faces.new((grid[i][j], grid[i + 1][j], grid[i + 1][j + 1], grid[i][j + 1]))
                    f.material_index = 1 if j == 0 else 0           # the edge row darker: the lid's rim, the lashes
                    f.smooth = True
            lay.append((sgn, R, grid))
        bm.normal_update()
        for f in bm.faces:   # outward, away from the ball
            if f.normal.dot(f.calc_center_median() - c) < 0:
                f.normal_flip()
        bm.verts.index_update()
        idx = [(sgn, [[v.index for v in col_] for col_ in grid]) for sgn, R, grid in lay]
        me = bpy.data.meshes.new(f"EyeLid_{side}")
        bm.to_mesh(me); bm.free()
        ob = bpy.data.objects.new(me.name, me); bpy.context.scene.collection.objects.link(ob)
        for name_, f_ in (("eyelid_skin", 1.0), ("eyelid_rim", 0.45)):
            m = bpy.data.materials.new(f"{name_}_{side}"); m.use_nodes = True
            bs = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
            bs.inputs["Base Color"].default_value = (col[0] * f_, col[1] * f_, col[2] * f_, 1.0)
            bs.inputs["Roughness"].default_value = 0.6
            me.materials.append(m)
        g = ob.vertex_groups.new(name=job["head_bone"])
        g.add(list(range(len(me.vertices))), 1.0, "REPLACE")
        md = ob.modifiers.new("Armature", "ARMATURE"); md.object = arm
        ob.parent = arm; ob.matrix_parent_inverse = arm.matrix_world.inverted()
        # keys: the upper shell turns down as far as the lid's middle needs to pass just under the line where the
        # lids meet (a quarter up from the lower lid), the lower up to that line
        ob.shape_key_add(name="Basis")
        name = {"L": "Left", "R": "Right"}.get(side, side)
        turns = {}
        for sgn, cols_i in idx:
            xs_ = [me.vertices[col_[0]].co.x for col_ in cols_i]
            # like a real blink: the upper lid goes all the way down to the lower lid's edge, the lower comes up a
            # little (an eighth of the opening); the upper, the bigger, closes over it (met in the middle, a white
            # slit showed between them on man_young)
            need = [(e_up(x) - meet(x, 0.0)) if sgn > 0 else (meet(x, 0.12) - e_lo(x)) for x in xs_]
            # one turn for the whole shell: per column (by the outline) the closing line came out wavy; turned whole,
            # it is the shell's smooth edge carried down - an arch, like a closed eye's
            top = sorted(need)[len(need) // 2] if sgn < 0 else max(need)
            turns[sgn] = [top] * len(need)
        for key, ku, kl in (("eyeBlink", 1.0, 1.0), ("eyeSquint", 0.18, 0.55), ("eyeWide", -0.35, -0.12)):
            kb = ob.shape_key_add(name=key + name, from_mix=False)
            for sgn, cols_i in idx:
                for i, col_ in enumerate(cols_i):
                    d = turns[sgn][i] * (ku if sgn > 0 else -kl)       # + = down
                    for vi in col_:
                        q = me.vertices[vi].co - c
                        rho_, ph = math.hypot(q.y, q.z), math.atan2(q.z, -q.y) - d
                        kb.data[vi].co = c + Vector((q.x, -rho_ * math.cos(ph), rho_ * math.sin(ph)))
            kb.value = 0.0
        made.append(me.name)
    return made


if face is not None and job.get("lid_shells", True):
    report["lid_shells"] = lid_shells()

# eye bones to the ball centres (only the balls are weighted to them)
bpy.ops.object.select_all(action="DESELECT"); arm.select_set(True); bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
ainv = arm.matrix_world.inverted()
for ball, bone, centre, r in balls:
    eb = arm.data.edit_bones.get(bone)
    if eb is not None and bone != job["head_bone"]:
        eb.head = ainv @ centre
        eb.tail = ainv @ (centre + Vector((0, -r, 0)))
bpy.ops.object.mode_set(mode="OBJECT")
for o in bpy.data.objects:   # rest = every shape key at 0 (Blender 5 adds new keys at 1; glTF stores these as default weights)
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
    sc.render.resolution_x, sc.render.resolution_y = 560, 300
    sc.render.image_settings.color_mode = "RGB"
    sc.world = bpy.data.worlds.new("bg"); sc.world.color = (0.82, 0.8, 0.77)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
    mid = sum((b[2] for b in balls), Vector()) / len(balls)
    span = max((balls[0][2] - balls[-1][2]).length, balls[0][3] * 4)
    cam.data.type = "ORTHO"; cam.data.ortho_scale = span * 2.6; cam.data.clip_end = span * 400
    cam.location = (mid.x, mid.y - span * 100, mid.z); cam.rotation_euler = (math.radians(90), 0, 0)
    shots = []
    for nm, yaw in (("eyes_ahead", 0), ("eyes_left", 25)):
        for ball, bone, centre, r in balls:
            pb = arm.pose.bones.get(bone)
            if pb is not None and bone != job["head_bone"]:
                pb.matrix_basis = Matrix()
                bpy.context.view_layer.update()
                h = pb.matrix.to_translation()
                pb.matrix = Matrix.Translation(h) @ Matrix.Rotation(math.radians(yaw), 4, "Z") @ Matrix.Translation(-h) @ pb.matrix
        bpy.context.view_layer.update()
        sc.render.filepath = job["preview"].replace(".png", f"_{nm}.png")
        bpy.ops.render.render(write_still=True)
        shots.append(sc.render.filepath)
    report["previews"] = shots
if job.get("report"):
    Path(job["report"]).write_text(json.dumps(report, indent=1), encoding="utf-8")
print("EYES_OK", json.dumps(report), flush=True)
