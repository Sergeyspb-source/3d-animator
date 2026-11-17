"""Runs INSIDE Blender (background): a creature's painted eyes cut out of its skin and eyeballs of its own put behind.

    blender -b -P blender_creature_eyes.py -- job.json

job.json: {"src": the rigged creature (its eyes not cut yet), "out": GLB, "eyes": {"L": [[x, y, z] x4], "R": ...} - each
eye's outline as marked in the skeleton viewer (glTF: inner corner, top, outer corner, bottom), "look": the eyeball's
picture (eye_tex.py: sclera, iris, pupil_color, iris_size, pupil, slit, veins, fibres) and "glow" (0..1: the eye shines
by itself), "size" (the ball's radius against the opening, default 1), "depth" (how far behind, in the opening's widths,
default 0), "level" (the gaze kept level, default true), "forward" (0..1: the gaze turned from the skin's way toward the creature's forward), "head_bone" (the bone when no skin near the eye says), "preview": png (optional)}.

Unlike a character's eye (blender_eye_insert.py: the face looks along -Y, the cut is seen from the front) a creature's
eye looks wherever its outline faces - forward on a wolf, out to the side on a horse: each eye has its own frame, the
outline's plane and its normal away from the head. In it: the four marks become a smooth closed curve (Catmull-Rom),
the skin's edges crossing it are split at the crossing and the faces inside it (near its plane: not the head's far
side) go - the opening's edge is the curve. The ball (UV mapped with its pole along the gaze, eye_tex.py's picture)
sits with its front just behind the eyelids' middle, radius 0.42 of the opening's width (a character's proportion)
times "size"; a dark cup behind it from the opening's edge (what shows round the ball in the corners is a shadowed
socket, not the inside of the head). Both are weighted 100 % to the bone that leads the skin round the eye.
Prints EYES_OK {report}.
"""
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

sys.path.insert(0, str(Path(__file__).resolve().parent))
import eye_tex as ET  # noqa: E402

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["src"])
scene = bpy.context.scene
arm = next(o for o in scene.objects if o.type == "ARMATURE")
for o in list(scene.objects):   # the importer's bone shapes; eyes from before (a copy made with them)
    if o.type == "MESH" and (not any(m.type == "ARMATURE" for m in o.modifiers) or o.name.startswith(("Eye_", "EyeSocket_"))):
        bpy.data.objects.remove(o, do_unlink=True)
meshes = [o for o in scene.objects if o.type == "MESH"]
arm.data.pose_position = "REST"
bpy.context.view_layer.update()
bl = lambda p: Vector((p[0], -p[2], p[1]))  # noqa: E731  glTF -> Blender
LOOK = job.get("look") or {}
report = {"eyes": {}}


def catmull(pts, n=12):
    out = []
    k = len(pts)
    for i in range(k):
        p0, p1, p2, p3 = pts[i - 1], pts[i], pts[(i + 1) % k], pts[(i + 2) % k]
        for s in range(n):
            t = s / n
            out.append(0.5 * ((2 * p1) + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t * t + (-p0 + 3 * p1 - 3 * p2 + p3) * t ** 3))
    return out


def inside(poly, x, y):
    c = False
    j = len(poly) - 1
    for i in range(len(poly)):
        xi, yi = poly[i]; xj, yj = poly[j]
        if (yi > y) != (yj > y) and x < (xj - xi) * (y - yi) / (yj - yi + 1e-12) + xi:
            c = not c
        j = i
    return c


def frame(pts, tris, span):
    """the eye's frame: centre, ex (across the eye), ey (up it), n (its gaze, away from the head). The gaze is the
    skin's own way round the eye (its triangles' normals within 0.8 of the outline's span, by area, each turned
    outward), not the four points' plane: one point dragged off swung that one sideways and the ball went to a
    shoulder; level at rest (the werewolf's outline, under a heavy brow, faced 43 deg down)"""
    c0 = sum(pts, Vector()) / len(pts)
    u, w = pts[2] - pts[0], pts[1] - pts[3]
    mid = sum((sum(tr, Vector()) / 3 for tr in tris), Vector()) / max(len(tris), 1)   # the head round the eye
    out0 = c0 - mid
    n = Vector()
    for a, b, c in tris:
        if ((a + b + c) / 3 - c0).length > 0.8 * span:
            continue
        f = (b - a).cross(c - a)
        n += -f if f.dot(out0) < 0 else f
    n = n.normalized() if n.length > 0 else (out0.normalized() if out0.length > 0 else Vector((0, -1, 0)))
    fw = float(job.get("forward", 0.0))   # toward the creature's forward (Blender -Y): the pupils not out to the sides
    if fw > 0:
        n = (n * (1 - fw) + Vector((0, -fw, 0))).normalized()
    flat = Vector((n.x, n.y, 0.0))
    if job.get("level", True) and flat.length > 0.2:
        n = flat.normalized()
    ex = u - n * u.dot(n)
    if ex.length < 1e-12:
        ex = Vector((0, 0, 1)).cross(n)
    ex.normalize()
    ey = n.cross(ex)
    if ey.dot(w) < 0:   # (the ball's picture upright: ex turned so that ey = n x ex points up the eye)
        ex = -ex
        ey = n.cross(ex)
    return c0, ex, ey, n


def eye_material():
    img_arr = ET.eye_texture(LOOK, int(job.get("seed", 1)), 1024, 512)
    h, w, _ = img_arr.shape
    img = bpy.data.images.new("creature_eye", w, h, alpha=False)
    img.pixels.foreach_set(np.concatenate([img_arr[::-1], np.ones((h, w, 1))], axis=2).astype(np.float32).ravel())
    img.pack()
    m = bpy.data.materials.new("creature_eye"); m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    t = m.node_tree.nodes.new("ShaderNodeTexImage"); t.image = img
    m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    b.inputs["Roughness"].default_value = 0.12
    for k in ("Specular IOR Level", "Specular"):
        if k in b.inputs:
            b.inputs[k].default_value = 0.35
            break
    glow = float(LOOK.get("glow", 0.0))
    if glow > 0:   # it shines by itself: the picture as its light (glTF emissive + its strength)
        key = "Emission Color" if "Emission Color" in b.inputs else "Emission"
        m.node_tree.links.new(t.outputs["Color"], b.inputs[key])
        if "Emission Strength" in b.inputs:
            b.inputs["Emission Strength"].default_value = 3.0 * glow
    return m


def ball_mesh(name, r):
    """a UV sphere, its pole along -Y (eye_tex.py's picture: row = the angle from the gaze), the cornea bulging"""
    bm = bmesh.new()
    bmesh.ops.create_uvsphere(bm, u_segments=48, v_segments=24, radius=r)
    bmesh.ops.rotate(bm, verts=bm.verts, cent=(0, 0, 0), matrix=Matrix.Rotation(math.radians(90), 3, "X"))
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        for l in f.loops:
            v = l.vert.co.normalized()
            th = math.acos(max(-1, min(1, -v.y)))
            ph = math.atan2(v.z, v.x) % (2 * math.pi)
            l[uv].uv = (ph / (2 * math.pi), 1 - th / math.pi)
    for v in bm.verts:
        th = math.acos(max(-1, min(1, -v.co.normalized().y)))
        if th < math.radians(38):
            v.co += Vector((0, -1, 0)) * r * 0.08 * math.cos(th / math.radians(38) * math.pi / 2) ** 2
    for f in bm.faces:
        us = [l[uv].uv.x for l in f.loops]
        if max(us) - min(us) > 0.5:
            for l in f.loops:
                if l[uv].uv.x < 0.5:
                    l[uv].uv.x += 1.0
    me = bpy.data.meshes.new(name)
    bm.to_mesh(me); bm.free()
    for p in me.polygons:
        p.use_smooth = True
    return me


def lead_bone(o, idx):
    """the bone the eye goes with: of the head and the bones below it (not the jaw), the one leading these vertices'
    skin (their weights summed), else the head itself. Never a bone outside the head: the test nurgl's skin round its
    eyes was weighted more to the shoulders than to the head, and an eye on a shoulder bone left the face when moved"""
    head = arm.data.bones.get(job.get("head_bone") or "") or next((b for b in arm.data.bones if b.name.lower().endswith("head")), None)
    if head is None:
        return None
    ok = {head.name} | {b.name for b in head.children_recursive if "jaw" not in b.name.lower()}
    tot = {}
    for i in idx:
        for g in o.data.vertices[i].groups:
            nm = o.vertex_groups[g.group].name
            if nm in ok:
                tot[nm] = tot.get(nm, 0.0) + g.weight
    return max(tot, key=tot.get) if tot else head.name


def attach(o, bone):
    g = o.vertex_groups.new(name=bone)
    g.add(list(range(len(o.data.vertices))), 1.0, "REPLACE")
    md = o.modifiers.new("Armature", "ARMATURE"); md.object = arm
    o.parent = arm; o.matrix_parent_inverse = arm.matrix_world.inverted()


_px = {}


def base_pixels(mat):
    """(pixels HxWx3 as stored - sRGB, w, h) of the picture behind a material's base colour, or None"""
    if mat is None or not mat.use_nodes:
        return None
    if mat.name not in _px:
        _px[mat.name] = None
        bsdf = next((nd for nd in mat.node_tree.nodes if nd.type == "BSDF_PRINCIPLED"), None)
        stack = [l.from_node for l in bsdf.inputs["Base Color"].links] if bsdf else []
        while stack:
            nd = stack.pop()
            if nd.type == "TEX_IMAGE" and nd.image and nd.image.size[0]:
                w, h = nd.image.size
                a = np.empty(w * h * 4, dtype=np.float32)
                nd.image.pixels.foreach_get(a)
                _px[mat.name] = (a.reshape(h, w, 4)[..., :3], w, h)
                break
            stack += [l.from_node for i in nd.inputs for l in i.links]
    return _px[mat.name]


def rim_colour(o, tris, lts, hits):
    """the socket's colour: the skin's along the opening's edge (its picture at the edge's UVs, the median), a little
    darker - a dark socket showed as a hole in the corners the ball does not fill (the user's nurgl). Linear."""
    from mathutils.geometry import barycentric_transform
    uvl = o.data.uv_layers.active
    cols = []
    for k, p in hits:
        lt = lts[k]
        px = base_pixels(o.data.materials[lt.material_index] if lt.material_index < len(o.data.materials) else None)
        if px is None or uvl is None:
            continue
        a, b, c = tris[k]
        bc = barycentric_transform(p, a, b, c, Vector((1, 0, 0)), Vector((0, 1, 0)), Vector((0, 0, 1)))
        uv = sum((uvl.data[li].uv * max(0.0, w) for w, li in zip(bc, lt.loops)), Vector((0, 0)))
        arr, w_, h_ = px
        cols.append(arr[int(min(h_ - 1, (uv.y % 1) * h_)), int(min(w_ - 1, (uv.x % 1) * w_))])
    if not cols:
        return (0.06, 0.03, 0.025)
    med = np.median(np.array(cols), axis=0) * 0.7
    return tuple(float(((v + 0.055) / 1.055) ** 2.4 if v > 0.04045 else v / 12.92) for v in med)


def socket_material(col):
    m = bpy.data.materials.new("eye_socket"); m.use_nodes = True
    b = next(nd for nd in m.node_tree.nodes if nd.type == "BSDF_PRINCIPLED")
    b.inputs["Base Color"].default_value = (*col, 1); b.inputs["Roughness"].default_value = 0.85
    m.diffuse_color = (*col, 1)   # (the preview's Workbench draws this one, not the nodes)
    return m


mat_eye = eye_material()
size, depth = float(job.get("size", 1.0)), float(job.get("depth", 0.0))
balls = []
for side, marks in job["eyes"].items():
    pts = [bl(p) for p in marks]
    c0 = sum(pts, Vector()) / 4
    span = max((pts[2] - pts[0]).length, (pts[1] - pts[3]).length, 1e-4)
    # the skin round the eye only: its triangles within reach, on the mesh that has most of them (Blender's «face»)
    best = None
    for o in meshes:
        o.data.calc_loop_triangles()
        wv = [o.matrix_world @ v.co for v in o.data.vertices]
        loc = [(tuple(wv[i] for i in lt.vertices), lt) for lt in o.data.loop_triangles]
        loc = [(tr, lt) for tr, lt in loc if ((tr[0] + tr[1] + tr[2]) / 3 - c0).length < 2.5 * span]
        if loc and (best is None or len(loc) > len(best[1])):
            best = (o, [tr for tr, _ in loc], [lt for _, lt in loc])
    if best is None:
        print(f"EYES_FAIL {side}: no skin near the eye", flush=True)
        sys.exit(1)
    face, tris, lts = best
    c0, ex, ey, n = frame(pts, tris, span)
    q2 = lambda p: ((p - c0).dot(ex), (p - c0).dot(ey))  # noqa: E731
    dn = lambda p: (p - c0).dot(n)  # noqa: E731
    curve = catmull(pts, 12)
    poly = [q2(p) for p in curve]
    xs, ys = [p[0] for p in poly], [p[1] for p in poly]
    width, height = (max(xs) - min(xs)) or span, (max(ys) - min(ys)) or span
    mid2 = (sum(xs) / len(xs), sum(ys) / len(ys))
    centre0 = c0 + ex * mid2[0] + ey * mid2[1]
    # the skin along the gaze (the near triangles only): in front of the eye's middle and on its outline
    fw = face.matrix_world
    # (the rays' skin: within 1.3 of the span - the edge lies within ~0.6 of it; the viewer the same)
    near_k = [k for k, tr in enumerate(tris) if ((tr[0] + tr[1] + tr[2]) / 3 - c0).length < 1.3 * span]
    fw_pts = [p for k in near_k for p in tris[k]]
    bvh = BVHTree.FromPolygons(fw_pts, [(3 * j, 3 * j + 1, 3 * j + 2) for j in range(len(near_k))])
    far = 3 * max(width, height)
    hit = bvh.ray_cast(centre0 + n * far, -n, 2 * far)
    d_front = dn(hit[0]) if hit[0] is not None else 0.0
    if abs(d_front) > span:
        d_front = 0.0
    rim, rim_hits = [], []
    for p in curve:
        h = bvh.ray_cast(p + n * far, -n, 2 * far)
        if h[0] is not None and abs(dn(h[0]) - d_front) < max(width, height):
            rim.append(h[0])
            rim_hits.append((near_k[h[2]], h[0]))
    sock_col = rim_colour(face, tris, lts, rim_hits)   # (before the cut: its UVs as they are)
    if len(rim) < len(curve) * 0.6:
        print(f"EYES_FAIL {side}: outline off the skin ({len(rim)}/{len(curve)})", flush=True)
        sys.exit(1)
    d_lids = sum(dn(p) for p in rim) / len(rim)
    # the cut: edges crossing the outline split there, the faces inside it near its plane deleted
    ins = lambda p: inside(poly, *q2(p))  # noqa: E731
    reach = 2 * max(width, height)   # (and near the eye: the head's far side, an arm, never cut)
    near_plane = lambda p: d_front - 0.6 * width < dn(p) < d_front + 1.0 * width and (p - centre0).length < reach  # noqa: E731
    bm = bmesh.new(); bm.from_mesh(face.data)
    cuts = set()
    for e in list(bm.edges):
        a_, b_ = fw @ e.verts[0].co, fw @ e.verts[1].co
        if ins(a_) == ins(b_) or not (near_plane(a_) or near_plane(b_)):
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
            except Exception:  # noqa: BLE001
                pass
    kill = [f for f in bm.faces if near_plane(fw @ f.calc_center_median()) and ins(fw @ f.calc_center_median())]
    bmesh.ops.delete(bm, geom=kill, context="FACES")
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bm.to_mesh(face.data); bm.free()
    # the bone round the eye: the skin's within the opening's width of its edge
    fw_now = [fw @ v.co for v in face.data.vertices]
    ring = [i for i, p in enumerate(fw_now) if abs(dn(p) - d_lids) < width and
            min((p - q).length for q in rim[::4]) < 0.5 * width]
    bone = lead_bone(face, ring) or job.get("head_bone") or "head"
    # the ball: its front just behind the lids' middle (or the painted eye, whichever is further out)
    r = 0.42 * max(width, height) * size
    gap = 0.02 * width + depth * width
    centre = centre0 + n * (max(d_front, d_lids) - gap - r)
    me = ball_mesh(f"Eye_{side}", r)
    ball = bpy.data.objects.new(me.name, me); scene.collection.objects.link(ball)
    rot = Matrix((ex, -n, ey)).transposed()   # local X -> ex, -Y (the pole) -> n, Z -> ey
    me.transform(Matrix.Translation(centre) @ rot.to_4x4())
    me.materials.append(mat_eye)
    attach(ball, bone)
    # the socket: a dark cup from the opening's edge (just behind the skin) back round the ball to its back pole
    sm = bpy.data.meshes.new(f"EyeSocket_{side}")
    sock = bpy.data.objects.new(sm.name, sm); scene.collection.objects.link(sock)
    bm = bmesh.new()
    R1 = r * 1.12
    mer = []
    for p in rim[::max(1, len(rim) // 40)]:
        d = p - centre
        lat = d - n * d.dot(n)
        if lat.length < 1e-9:
            continue
        ax = lat.normalized()
        th0 = math.atan2(lat.length, d.dot(n))
        rho0 = max(d.length - 0.04 * width, R1 * 0.98)
        col = []
        for k in range(9):
            t = k / 8
            th = th0 + (math.pi * 0.92 - th0) * t
            rho = rho0 + (R1 - rho0) * min(1.0, t * 2.5)
            col.append(bm.verts.new(centre + (n * math.cos(th) + ax * math.sin(th)) * rho))
        mer.append(col)
    pole = bm.verts.new(centre - n * R1)
    for i in range(len(mer)):
        a_, b_ = mer[i], mer[(i + 1) % len(mer)]
        for k in range(len(a_) - 1):
            bm.faces.new((a_[k], b_[k], b_[k + 1], a_[k + 1]))
        bm.faces.new((a_[-1], b_[-1], pole))
    bm.normal_update()
    for f in bm.faces:   # seen from inside: toward the ball
        if f.normal.dot(centre - f.calc_center_median()) < 0:
            f.normal_flip()
    bm.to_mesh(sm); bm.free()
    for pl in sm.polygons:
        pl.use_smooth = True
    sm.materials.append(socket_material(sock_col))
    attach(sock, bone)
    balls.append((side, centre, r, n))
    report["eyes"][side] = {"radius": round(r, 5), "opening": [round(width, 5), round(height, 5)],   # (the model's units)
                            "deleted_faces": len(kill), "bone": bone, "mesh": face.name, "socket": [round(v, 3) for v in sock_col],
                            "gaze": [round(n.x, 3), round(n.z, 3), round(-n.y, 3)]}   # (glTF)
arm.data.pose_position = "POSE"
bpy.ops.object.select_all(action="DESELECT")
for o in scene.objects:
    o.select_set(o.type in ("ARMATURE", "MESH"))
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_morph=True)

if job.get("preview") and balls:   # the head from the front and from the first eye's gaze
    sc = scene
    try:
        sc.render.engine = "BLENDER_WORKBENCH"
        sc.display.shading.light = "STUDIO"; sc.display.shading.color_type = "TEXTURE"
    except (TypeError, AttributeError):
        pass
    sc.render.resolution_x, sc.render.resolution_y = 520, 400
    sc.render.film_transparent = False
    sc.world = bpy.data.worlds.new("bg"); sc.world.color = (0.8, 0.8, 0.78)
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); sc.collection.objects.link(cam); sc.camera = cam
    mid = sum((b[1] for b in balls), Vector()) / len(balls)
    span = max(max((balls[0][1] - b[1]).length for b in balls), balls[0][2] * 6) * 2.2
    cam.data.type = "ORTHO"; cam.data.ortho_scale = span; cam.data.clip_start = 0.001; cam.data.clip_end = 100
    shots = []
    for nm, d in (("front", Vector((0, -1, 0))), ("eye", balls[0][3])):
        cam.location = mid + d * span * 4 if nm == "front" else balls[0][1] + d * span * 4
        cam.rotation_euler = (-d).to_track_quat("-Z", "Z").to_euler()
        sc.render.filepath = job["preview"].replace(".png", f"_{nm}.png")
        bpy.ops.render.render(write_still=True)
        shots.append(sc.render.filepath)
    report["previews"] = shots
print("EYES_OK " + json.dumps(report), flush=True)
