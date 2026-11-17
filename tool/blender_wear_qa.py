"""Runs INSIDE Blender (background): a piece put on, checked in the character's animations — where the skin comes
out through it and where the body taken away under it (its mask) shows a hole.

    blender -b -P blender_wear_qa.py -- job.json

job.json: {"character": the animated character GLB (the fitting room's: procedural or Mixamo clips),
           "piece": the piece's GLB (skinned to the same skeleton), "mask": its mask JSON or null, "out": report JSON,
           "step": every how many frames (3)}

The skin is checked where the piece covers it at rest (a ray along the skin's direction meets the piece near): in a
frame it has come out when the piece is behind it and not in front (its outer side passed), a «poke». The body the
mask takes away shows a «hole» when the piece is no longer in front of it. The report: per clip the worst frame and
how much of the covered skin came out there, the holes, and the rest positions (glTF axes) of the skin that came out
in any frame, for the editor to mark.
"""
import json
import sys
from pathlib import Path

import bpy
import numpy as np
from mathutils import Matrix, Vector
from mathutils.bvhtree import BVHTree

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
PARTS = ("Eye_", "EyeSocket", "Teeth_", "Gum_", "Tongue", "MouthCavity", "Icosphere")


def fail(msg):
    print("WEAR_QA_FAIL " + msg, flush=True)
    sys.exit(1)


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["character"])
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    fail("no skeleton")
body = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups and not o.name.startswith(PARTS)]
actions = [a for a in bpy.data.actions if any(fc.data_path.startswith("pose.bones") for fc in getattr(a, "fcurves", []))] or list(bpy.data.actions)
before = set(bpy.data.objects)
bpy.ops.import_scene.gltf(filepath=job["piece"])
new = [o for o in bpy.data.objects if o not in before]
pieces = [o for o in new if o.type == "MESH" and not o.name.startswith(PARTS)]   # (not the importer's bone shape: a 1 m Icosphere round the origin)
for o in pieces:   # onto the character's skeleton, by the bones' names
    for m in o.modifiers:
        if m.type == "ARMATURE":
            m.object = arm
    o.parent = arm
for o in new:
    if o.type == "ARMATURE":
        bpy.data.objects.remove(o)
for a in [a for a in bpy.data.actions if a not in actions]:   # the piece's own (none, or its rest)
    bpy.data.actions.remove(a)
if not pieces or not body:
    fail("no piece or no body")

mask = set()
if job.get("mask") and Path(job["mask"]).exists():
    mask = {tuple(x) for x in json.loads(Path(job["mask"]).read_text(encoding="utf-8"))}
key = lambda c: (round(c.x * 1000), round(c.z * 1000), round(-c.y * 1000))   # as body_mask.py


def near_key(c):   # the next thousandth too, as the lookups do
    k = key(c)
    return k in mask or any((k[0] + dx, k[1] + dy, k[2] + dz) in mask for dx in (-1, 0, 1) for dy in (-1, 0, 1) for dz in (-1, 0, 1))


def snapshot():
    """The body's vertices (world, normals) and the piece's tree in the current frame."""
    dg = bpy.context.evaluated_depsgraph_get()
    verts = []
    for o in body:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        W, N = ev.matrix_world, ev.matrix_world.to_3x3().inverted().transposed()
        verts.append([(W @ v.co, (N @ v.normal).normalized()) for v in me.vertices])
        ev.to_mesh_clear()
    pv, pf = [], []
    for o in pieces:
        ev = o.evaluated_get(dg)
        me = ev.to_mesh()
        base = len(pv)
        pv += [ev.matrix_world @ v.co for v in me.vertices]
        pf += [tuple(base + i for i in p.vertices) for p in me.polygons]
        ev.to_mesh_clear()
    return verts, BVHTree.FromPolygons(pv, pf), pv




def set_clip(act):
    arm.animation_data.action = act
    if hasattr(arm.animation_data, "action_slot") and act.slots:
        try:
            arm.animation_data.action_slot = act.slots[0]
        except Exception:   # noqa: BLE001
            pass
    return (int(x) for x in act.frame_range)


def held_check():
    """A held thing (job "held": {"skip": the holding arm's bones, "fore", "hips": those bones' names in either naming, "shield": bool}):
    where the body (not the arm holding it) has gone into it — a shield: or through it, to its front — or it into the
    body (a blade through a leg), in each clip's frames, and how far it would have to move out along its face for none of it to (a shield: also the frames it faces
    the body). The face: the thing's thinnest axis, away from the arm. Per clip {worst_frame, through (vertices),
    need (the shift, metres), facing (frames)}."""
    h = job["held"]
    skip = set(h.get("skip") or [])
    hips = next((arm.pose.bones[n] for n in h.get("hips") or [] if n in arm.pose.bones), None)   # either naming
    fore = next((arm.pose.bones[n] for n in h.get("fore") or [] if n in arm.pose.bones), None)
    keep = []   # per body object: the vertices that count (their strongest bone not the holding arm's)
    for o in body:
        names = {g.index: g.name for g in o.vertex_groups}
        ks = []
        for v in o.data.vertices:
            g = max(v.groups, key=lambda x: x.weight, default=None)
            if g is None or names.get(g.group) not in skip:
                ks.append(v.index)
        keep.append(ks)

    kept_faces = []   # per body object: its faces all of whose corners count (the holding hand round a grip is not)
    for o, ks in zip(body, keep):
        kk = set(ks)
        kept_faces.append([tuple(pl.vertices) for pl in o.data.polygons if all(v in kk for v in pl.vertices)])

    def in_body(verts, pv):   # which of the thing's points are inside the body (a blade through a leg)
        pts, faces = [], []
        for vs, fs in zip(verts, kept_faces):
            base = len(pts)
            pts += [p for p, _ in vs]
            faces += [tuple(base + i for i in f) for f in fs]
        if not faces:
            return []
        bt = BVHTree.FromPolygons(pts, faces)
        up = Vector((0, 0, 1))
        out = []
        for i, p in enumerate(pv):
            hit = bt.ray_cast(p, up, 10.0)
            if hit[0] is not None and hit[1].dot(up) > 0 and bt.find_nearest(p)[3] > tol:   # inside: going out meets the skin first
                out.append(i)
        return out

    def frame_state():
        verts, tree, pv = snapshot()
        frame_state.pv = pv
        P = np.array([[p.x, p.y, p.z] for p in pv])
        c = P.mean(axis=0)
        w, V = np.linalg.eigh(np.cov((P - c).T))
        A = Vector(V[:, 0])   # its thinnest axis: the face
        W = arm.matrix_world
        if fore is not None:   # away from the arm holding it
            j = W @ fore.head
            if A.dot(Vector(c) - j) < 0:
                A = -A
        return verts, tree, Vector(c), A, float(np.sqrt(w[-1]) * 2.5)

    def need_at(tree, p, A, far):   # how far the thing must move along A for p to be behind it, or None
        hit = tree.ray_cast(p, -A, far)
        if hit[0] is None:
            return None
        if hit[1].dot(A) < 0:   # inside it
            return hit[3]
        if not h.get("shield"):   # a blade's flat: the body beside it is not in it
            return None
        d = hit[3]   # in front of it: on through it
        q = hit[0] - A * e
        for _ in range(8):
            nh = tree.ray_cast(q, -A, far)
            if nh[0] is None:
                return None
            d += nh[3] + e
            if nh[1].dot(A) < 0:
                return d
            q = nh[0] - A * e
        return None

    # unlike a worn piece, a held one is placed by its sliders: what is wrong at rest counts too
    arm.animation_data_create()
    arm.animation_data.action = None
    for pb in arm.pose.bones:
        pb.matrix_basis.identity()
    bpy.context.view_layer.update()
    rest = frame_state()
    rest_pv = list(frame_state.pv)
    e = 1e-4 * rest[4]
    zs = [p.z for vs in rest[0] for p, _ in vs]
    tol = .005 * (max(zs) - min(zs))   # a strap lying close on the body grazes it as the body moves: only deeper counts
    clips, out_pts, need_all = [], set(), []
    step = max(1, int(job.get("step", 3)))
    for act in actions:
        if any(act.name.lower().startswith(x + "_") for x in job.get("skip_clips") or []):   # (another weapon's clip)
            continue
        f0, f1 = set_clip(act)
        worst, need, facing = (0, f0), 0.0, 0
        for f in range(f0, f1 + 1, step):
            bpy.context.scene.frame_set(f)
            verts, tree, c, A, size = frame_state()
            if h.get("shield") and hips is not None and A.dot(c - arm.matrix_world @ hips.head) < 0:
                facing += 1
            n, fn = 0, 0.0
            for oi, ks in enumerate(keep):
                for vi in ks:
                    p = verts[oi][vi][0]
                    if (p - c).length > size:
                        continue
                    d = need_at(tree, p, A, .3 * size)
                    if d is None or d < tol:
                        continue
                    n += 1
                    fn = max(fn, d)
                    co = body[oi].data.vertices[vi].co
                    out_pts.add((round(co.x, 4), round(co.z, 4), round(-co.y, 4)))
            inside = in_body(verts, frame_state.pv)
            n += len(inside)
            for i in inside:   # marked where the thing is at rest (glTF axes)
                q = rest_pv[i]
                out_pts.add((round(q.x, 4), round(q.z, 4), round(-q.y, 4)))
            if n > worst[0]:
                worst = (n, f)
            need = max(need, fn)
        need_all.append(need)
        clips.append({"clip": act.name, "frames": [f0, f1], "worst_frame": worst[1], "through": worst[0],
                      "need": round(need, 4), "facing": facing})
    report = {"held": True, "clips": clips, "need": round(max(need_all, default=0), 4),
              "points": [list(x) for x in sorted(out_pts)][:3000]}
    Path(job["out"]).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
    print("WEAR_QA_OK " + json.dumps({k: report[k] for k in ("clips", "need")}), flush=True)
    sys.exit(0)


if job.get("held"):
    held_check()

# at rest: what the piece covers, what the mask takes away
arm.animation_data_create()
arm.animation_data.action = None
for pb in arm.pose.bones:
    pb.matrix_basis.identity()
bpy.context.view_layer.update()
verts0, tree0, pv0 = snapshot()
lo = Vector((min(p[i] for p in pv0) for i in range(3)))
hi = Vector((max(p[i] for p in pv0) for i in range(3)))
size = (hi - lo).length
reach, depth, e, far = .06 * size, .08 * size, 1e-4 * size, .1 * size   # far: the mask's own reach (body_mask)


def poked(tree, p, n):   # the piece behind the skin and not in front of it: the skin has come out
    return tree.ray_cast(p - n * e, -n, depth)[0] is not None and tree.ray_cast(p + n * e, n, reach)[0] is None


# only what is right at rest is watched: what goes wrong in motion is the piece's, not the fit's
covered, hidden = [], []   # (object, vertex)
for oi, (o, vs) in enumerate(zip(body, verts0)):
    me = o.data
    for vi, (p, n) in enumerate(vs):
        if not all(lo[i] - far <= p[i] <= hi[i] + far for i in range(3)):
            continue
        if mask and near_key(me.vertices[vi].co):
            if tree0.ray_cast(p + n * e, n, far)[0] is not None:
                hidden.append((oi, vi))
        elif tree0.ray_cast(p + n * e, n, reach)[0] is not None and not poked(tree0, p, n):
            covered.append((oi, vi))

# the covered skin by the piece's edge (a few cm in from where it stops covering) apart from its middle: skin peeping out
# at a cuff's rim as the joint bends is the edge's, a body through the middle of a plate is the real fault
from mathutils.kdtree import KDTree
free = [(oi, vi) for oi, vs in enumerate(verts0) for vi, (p, n) in enumerate(vs)
        if all(lo[i] - far <= p[i] <= hi[i] + far for i in range(3))]
cov_set = set(covered) | set(hidden)
free = [x for x in free if x not in cov_set]
kd = KDTree(max(1, len(free)))
for k, (oi, vi) in enumerate(free):
    kd.insert(verts0[oi][vi][0], k)
kd.balance()
edge_r = .025 * size
edge = {x for x in covered if free and kd.find(verts0[x[0]][x[1]][0])[2] < edge_r}

step = max(1, int(job.get("step", 3)))
clips, out_pts, worst_mid = [], set(), {}
for act in actions:
    f0, f1 = set_clip(act)
    worst = (0, f0, 0, 0)   # pokes in the middle, frame, holes, pokes by the edge
    holes_max = 0
    for f in range(f0, f1 + 1, step):
        bpy.context.scene.frame_set(f)
        verts, tree, _ = snapshot()
        pokes = []
        for oi, vi in covered:
            if poked(tree, *verts[oi][vi]):
                pokes.append((oi, vi))
        holes = sum(1 for oi, vi in hidden if tree.ray_cast(verts[oi][vi][0] + verts[oi][vi][1] * e, verts[oi][vi][1], far)[0] is None)
        holes_max = max(holes_max, holes)
        mid = [x for x in pokes if x not in edge]
        if len(mid) > worst[0] or (worst[0] == 0 and len(pokes) - len(mid) > worst[3]):
            worst = (len(mid), f, holes, len(pokes) - len(mid))
            if mid:
                worst_mid[act.name] = (f, [verts[oi][vi] for oi, vi in mid])
        for oi, vi in pokes:
            c = body[oi].data.vertices[vi].co   # the rest position, glTF axes, mesh-local as the editor's
            out_pts.add((round(c.x, 4), round(c.z, 4), round(-c.y, 4)))
    n_mid = max(1, len(covered) - len(edge))
    clips.append({"clip": act.name, "frames": [f0, f1], "worst_frame": worst[1], "pokes": worst[0], "edge_pokes": worst[3],
                  "poke_share": round(worst[0] / n_mid, 4), "edge_share": round(worst[3] / max(1, len(edge)), 4),
                  "holes": holes_max, "hole_share": round(holes_max / max(1, len(hidden)), 4)})
# the worst frames, pictured: the three clips with most skin through the piece's middle, at their worst frame, the
# skin that came out marked red, the camera looking at it from outside
shots = []
if job.get("shots", True) and worst_mid:
    import bmesh
    sc = bpy.context.scene
    try:
        sc.render.engine = "BLENDER_WORKBENCH"
        sc.display.shading.light = "STUDIO"
        sc.display.shading.color_type = "MATERIAL"
    except (TypeError, AttributeError):
        pass
    sc.render.resolution_x, sc.render.resolution_y = 420, 420
    sc.world = bpy.data.worlds.new("qa_bg")
    sc.world.color = (0.82, 0.8, 0.77)
    for o, col in [(o, (0.72, 0.68, 0.62, 1)) for o in body] + [(o, (0.35, 0.45, 0.6, 1)) for o in pieces]:
        m = bpy.data.materials.new("qa_" + o.name)
        m.diffuse_color = col
        o.data.materials.clear()
        o.data.materials.append(m)
    red = bpy.data.materials.new("qa_red")
    red.diffuse_color = (0.9, 0.08, 0.05, 1)
    cam = bpy.data.objects.new("qa_cam", bpy.data.cameras.new("qa_cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    cam.data.type = "ORTHO"
    cam.data.clip_end = size * 100
    by_clip = {c["clip"]: c for c in clips}
    for name in sorted(worst_mid, key=lambda k: -by_clip[k]["pokes"])[:3]:
        f, pts = worst_mid[name]
        act = next(a for a in actions if a.name == name)
        set_clip(act)
        sc.frame_set(f)
        mk = bpy.data.meshes.new("qa_marks")
        bm = bmesh.new()
        r = .011 * size
        for p_, n_ in pts[:400]:
            bmesh.ops.create_icosphere(bm, subdivisions=1, radius=r, matrix=Matrix.Translation(p_ + n_ * r))
        bm.to_mesh(mk)
        bm.free()
        mo = bpy.data.objects.new("qa_marks", mk)
        mo.data.materials.append(red)
        mo.show_in_front = True   # (seen through what is in front: an armpit's skin under the arm)
        sc.collection.objects.link(mo)
        c = sum((p_ for p_, _ in pts), Vector()) / len(pts)
        nn = sum((n_ for _, n_ in pts), Vector())
        d = nn.normalized() if nn.length > 1e-9 else Vector((0, -1, 0))
        d = (d + Vector((0, 0, .25))).normalized()
        span = max(max((p_ - c).length for p_, _ in pts) * 2.6, .25 * size)
        cam.data.ortho_scale = span
        cam.location = c + d * size * 4
        cam.rotation_euler = (-d).to_track_quat("-Z", "Y").to_euler()
        fn = str(Path(job["out"]).with_name("qa_" + "".join(ch if ch.isalnum() else "_" for ch in name)[:40] + ".png"))
        sc.render.filepath = fn
        bpy.ops.render.render(write_still=True)
        shots.append([fn, f"{name} · {f}"])
        bpy.data.objects.remove(mo, do_unlink=True)
report = {"covered": len(covered), "edge": len(edge), "hidden": len(hidden), "clips": clips, "shots": shots,
          "points": [list(x) for x in sorted(out_pts)][:3000]}
Path(job["out"]).write_text(json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")
print("WEAR_QA_OK " + json.dumps({k: report[k] for k in ("covered", "hidden", "clips")}), flush=True)
