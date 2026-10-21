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
        face = max(meshes, key=lambda o: sum(1 for v in o.data.vertices if ((o.matrix_world @ v.co) - Vector((cx, rim3[0].y, cz))).length < width * 2))
        fw = face.matrix_world
    # the painted surface in front of the aperture centre (before cutting)
    face.data.calc_loop_triangles()
    wv = [fw @ v.co for v in face.data.vertices]
    bvh = BVHTree.FromPolygons(wv, [tuple(t.vertices) for t in face.data.loop_triangles])
    ymin = min(v.y for v in wv)
    hit = bvh.ray_cast(Vector((cx, ymin - width * 20, cz)), Vector((0, 1, 0)), width * 80)
    if hit[0] is None and not job.get("open_rim"):
        fail(f"нет поверхности перед глазом {side}: проверьте контур глаза")
    front_y = hit[0].y if hit[0] is not None else 0.0
    rim_surf = []
    for p in curve:
        h = bvh.ray_cast(Vector((p.x, ymin - width * 20, p.z)), Vector((0, 1, 0)), width * 80)
        if h[0] is not None:
            rim_surf.append(h[0])
    if len(rim_surf) < len(curve) * 0.7:
        fail(f"контур глаза {side} выходит за модель")
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
                        ball=spec.get("ball"), ball_r=spec.get("ball_r"))
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
    rim_err = [abs((p - centre).length - r) for p in rim_surf]
    # dark socket behind the ball: what shows in the corners of the opening is a shadowed orbit, not the background
    bpy.ops.mesh.primitive_uv_sphere_add(segments=32, ring_count=16, radius=r * 1.12, location=centre)
    sock = bpy.context.active_object; sock.name = sock.data.name = f"EyeSocket_{side}"
    bm = bmesh.new(); bm.from_mesh(sock.data)
    bmesh.ops.delete(bm, geom=[f for f in bm.faces if (sock.matrix_world @ f.calc_center_median()).y < centre.y - r * 0.35], context="FACES")
    bmesh.ops.reverse_faces(bm, faces=bm.faces[:])            # seen from inside
    bm.to_mesh(sock.data); bm.free()
    if "eye_socket" not in bpy.data.materials:
        sm = bpy.data.materials.new("eye_socket"); sm.use_nodes = True
        sb = next(n for n in sm.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        sb.inputs["Base Color"].default_value = (0.05, 0.02, 0.02, 1); sb.inputs["Roughness"].default_value = 0.8
    sock.data.materials.append(bpy.data.materials["eye_socket"])
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    sg = sock.vertex_groups.new(name=job["head_bone"]); sg.add(list(range(len(sock.data.vertices))), 1.0, "REPLACE")
    sm_ = sock.modifiers.new("Armature", "ARMATURE"); sm_.object = arm
    sock.parent = arm; sock.matrix_parent_inverse = arm.matrix_world.inverted()
    report["eyes"][side] = {"radius": round(r, 4), "opening_width": round(width, 4), "deleted_faces": sv["kill"],
                            "rim_off_ball_mean": round(sum(rim_err) / len(rim_err), 4)}
bpy.data.objects.remove(kit, do_unlink=True)

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
                          export_animations=False, export_morph=True, export_morph_normal=False, export_influence_nb=4)

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
