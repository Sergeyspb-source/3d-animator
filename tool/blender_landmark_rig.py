"""Runs INSIDE Blender (background): build a humanoid skeleton from hand-placed landmarks and skin the model.

    blender -b -P blender_landmark_rig.py -- job.json

job.json: {"source": in.glb, "out_dir": dir, "landmarks": {...editor JSON...}, "names": {joint_id: bone name}}
Joint coordinates in the landmarks are glTF space (Y up, +Z forward) after the editor's yaw turn.
Writes <out_dir>/model.glb (rest pose, 4 influences), rest.png, pose_front.png, pose_side.png, rig_report.json.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
L = job["landmarks"]
NAMES = job["names"]
OUT = Path(job["out_dir"])
OUT.mkdir(parents=True, exist_ok=True)

# head -> tail joint for every bone; the bone takes its head joint's name
TAIL = {"hips": "spine", "spine": "spine1", "spine1": "spine2", "spine2": "neck", "neck": "head", "head": "head_top"}
for s in "LR":
    TAIL.update({f"shoulder_{s}": f"arm_{s}", f"arm_{s}": f"forearm_{s}", f"forearm_{s}": f"hand_{s}",
                 f"hand_{s}": f"hand_end_{s}", f"upleg_{s}": f"leg_{s}", f"leg_{s}": f"foot_{s}",
                 f"foot_{s}": f"toe_{s}", f"toe_{s}": f"toe_end_{s}"})


import re

FINGER = re.compile(r"^(thumb|index|middle|ring|pinky)([123])_([LR])$")
for jid in L["joints"]:   # optional finger chains: 1 -> 2 -> 3 -> 4 (tip, no bone)
    m = FINGER.match(jid)
    if m and f"{m[1]}{int(m[2]) + 1}_{m[3]}" in L["joints"]:
        TAIL[jid] = f"{m[1]}{int(m[2]) + 1}_{m[3]}"


if "jaw" in L["joints"] and "jaw_end" in L["joints"]:
    TAIL["jaw"] = "jaw_end"
for s_ in "LR":
    if f"eye_{s_}" in L["joints"] and f"eye_end_{s_}" in L["joints"]:
        TAIL[f"eye_{s_}"] = f"eye_end_{s_}"


def bl(p):  # glTF (x, y, z) -> Blender (x, -z, y)
    return Vector((p[0], -p[2], p[1]))


# ------------------------------------------------------------------ load and clean the model
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["source"])
scene = bpy.context.scene
meshes = [o for o in scene.objects if o.type == "MESH"]
if not meshes:
    raise SystemExit("no meshes in the source")
world = {o: o.matrix_world.copy() for o in meshes}
for o in meshes:
    for m in list(o.modifiers):
        if m.type == "ARMATURE":
            o.modifiers.remove(m)
    o.vertex_groups.clear()
    o.parent = None
    o.matrix_world = Matrix.Rotation(math.radians(L.get("yaw", 0)), 4, "Z") @ world[o]
for o in list(scene.objects):
    if o.type != "MESH":
        bpy.data.objects.remove(o, do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
bpy.context.view_layer.objects.active = meshes[0]
bpy.ops.object.make_single_user(object=True, obdata=True)
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)

# ------------------------------------------------------------------ armature
J = {k: list(v) for k, v in L["joints"].items()}
# IK-friendly rest: a nearly straight elbow/knee gets a small bend toward its flex side (elbow joint a little behind
# the shoulder-wrist line, knee a little in front of the hip-ankle line), so Godot's IK always bends it correctly.
prebend = {}
for up, mid, low, flex in [(f"arm_{s}", f"forearm_{s}", f"hand_{s}", (0, 0, 1)) for s in "LR"] + \
                          [(f"upleg_{s}", f"leg_{s}", f"foot_{s}", (0, 0, -1)) for s in "LR"]:
    a, m, c = (Vector(J[k]) for k in (up, mid, low))
    u = (c - a).normalized()
    f = Vector(flex) * float(L.get("bend", {}).get(mid, 1))
    fp = f - u * f.dot(u)
    if fp.length < 1e-6:
        continue
    fp.normalize()
    want = -(c - a).length * 0.5 * math.tan(math.radians(4))   # ~8 deg total bend
    off = (m - a).dot(fp)
    if off > want:
        J[mid] = list(m + fp * (want - off))
        prebend[mid] = round((want - off), 4)
arm_data = bpy.data.armatures.new("Armature")
rig = bpy.data.objects.new("Armature", arm_data)
scene.collection.objects.link(rig)
bpy.ops.object.select_all(action="DESELECT")
bpy.context.view_layer.objects.active = rig
rig.select_set(True)
bpy.ops.object.mode_set(mode="EDIT")
eb = {}
for jid, tail in TAIL.items():
    b = arm_data.edit_bones.new(NAMES[jid])
    b.head, b.tail = bl(J[jid]), bl(J[tail])
    if (b.tail - b.head).length < 1e-4:
        b.tail = b.head + Vector((0, 0, 0.01))
    eb[jid] = b
for jid, b in eb.items():
    par = L["parents"].get(jid)
    if par:
        b.parent = eb[par]

# a consistent roll: bones' local Z points backwards (+Y in Blender) for limbs/spine, like most humanoid rigs
for b in arm_data.edit_bones:
    b.align_roll(Vector((0, 1, 0)) if abs((b.tail - b.head).normalized().y) < 0.9 else Vector((0, 0, 1)))
bpy.ops.object.mode_set(mode="OBJECT")

# ------------------------------------------------------------------ skin: Blender heat weights on a welded proxy
# Tripo models come in parts split along seams; heat weighting fails on many separate open parts and on small
# models. So: join copies of all parts, weld the seams, scale x10, heat-weight that proxy against a scaled copy of
# the rig, and copy the weights back to every original vertex from the nearest proxy vertex.
# models arrive in metres or in centimetres (Tripo exports ~1 or ~100 units tall): bring the proxy to ~10 units
lows = [(o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box]
height = max(lows) - min(lows)
SCALE = 10.0 / max(height, 1e-6)
bpy.ops.object.select_all(action="DESELECT")
copies = []
for o in meshes:
    c = o.copy()
    c.data = o.data.copy()
    scene.collection.objects.link(c)
    c.select_set(True)
    copies.append(c)
bpy.context.view_layer.objects.active = copies[0]
if len(copies) > 1:
    bpy.ops.object.join()
proxy = bpy.context.view_layer.objects.active
proxy.data.materials.clear()
proxy.matrix_world = Matrix.Scale(SCALE, 4) @ proxy.matrix_world
bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
bpy.ops.object.mode_set(mode="EDIT")
bpy.ops.mesh.select_all(action="SELECT")
bpy.ops.mesh.remove_doubles(threshold=0.005)  # 0.05 % of the height
bpy.ops.object.mode_set(mode="OBJECT")
prig = rig.copy()
prig.data = rig.data.copy()
scene.collection.objects.link(prig)
prig.matrix_world = Matrix.Scale(SCALE, 4)
bpy.ops.object.select_all(action="DESELECT")
prig.select_set(True)
bpy.context.view_layer.objects.active = prig
bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
for k in ("jaw", "eye_L", "eye_R"):   # face bones get their weights from the mouth line / loose eyeballs, not heat
    if k in TAIL:
        prig.data.bones[NAMES[k]].use_deform = False
bpy.ops.object.select_all(action="DESELECT")
proxy.select_set(True)
prig.select_set(True)
bpy.context.view_layer.objects.active = prig
bpy.ops.object.parent_set(type="ARMATURE_AUTO")
SMOOTH = int(job.get("smooth", 6))
if SMOOTH:  # heat weights change sharply at shoulders/hips: a few smoothing passes along the surface
    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    bpy.context.view_layer.objects.active = proxy
    bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
    bpy.ops.object.vertex_group_smooth(group_select_mode="ALL", factor=0.5, repeat=SMOOTH)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    bpy.ops.object.mode_set(mode="OBJECT")

pv = proxy.data.vertices
tree = KDTree(len(pv))
for v in pv:
    tree.insert(v.co, v.index)
tree.balance()
pnames = {g.index: g.name for g in proxy.vertex_groups}
proxy_heat_failed = sum(1 for v in pv if not any(g.weight > 1e-4 for g in v.groups))
for o in meshes:
    for b in arm_data.bones:
        o.vertex_groups.new(name=b.name)
    mw = o.matrix_world
    for v in o.data.vertices:
        _, j, _ = tree.find((mw @ v.co) * SCALE)
        for g in pv[j].groups:
            if g.weight > 1e-4:
                o.vertex_groups[pnames[g.group]].add([v.index], g.weight, "REPLACE")
    mod = o.modifiers.new("Armature", "ARMATURE")
    mod.object = rig
    o.parent = rig
    o.matrix_parent_inverse = rig.matrix_world.inverted()
for ob in (proxy, prig):
    bpy.data.objects.remove(ob, do_unlink=True)

segs = []
for b in arm_data.bones:
    if not b.use_deform:
        continue
    segs.append((b.name, rig.matrix_world @ b.head_local, rig.matrix_world @ b.tail_local))


def seg_dist(p, a, c):
    ab = c - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return (p - (a + ab * t)).length


report = {"meshes": {}, "bones": len(arm_data.bones), "deform_bones": len(segs), "prebend": prebend, "height": height, "proxy_vertices": len(pv), "proxy_heat_failed": proxy_heat_failed}
for o in meshes:
    groups = {g.index for g in o.vertex_groups}
    missing = [v.index for v in o.data.vertices if not any(g.group in groups and g.weight > 1e-4 for g in v.groups)]
    if missing:  # heat failed for this part (holes, self-intersections): inverse-distance to the 2 nearest bones
        for name, _, _ in segs:
            if o.vertex_groups.get(name) is None:
                o.vertex_groups.new(name=name)
        mw = o.matrix_world
        for i in missing:
            p = mw @ o.data.vertices[i].co
            d = sorted((seg_dist(p, a, c), n) for n, a, c in segs)[:2]
            w = [1.0 / max(x, 1e-4) ** 4 for x, _ in d]
            for (x, n), wi in zip(d, w):
                o.vertex_groups[n].add([i], wi / sum(w), "REPLACE")
    bpy.ops.object.select_all(action="DESELECT")
    o.select_set(True)
    bpy.context.view_layer.objects.active = o
    bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
    bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    report["meshes"][o.name] = {"vertices": len(o.data.vertices), "fallback_vertices": len(missing)}
report["fallback_vertices"] = sum(m["fallback_vertices"] for m in report["meshes"].values())
report["vertices"] = sum(m["vertices"] for m in report["meshes"].values())

# ---- face: the jaw takes the head weight below the mouth line (fading out before the hinge); eyes get weights
# only when they are separate pieces of the mesh (otherwise they are look-at helpers and do not bend the eyelids)
if "jaw" in TAIL and L.get("face", {}).get("mouth_c"):
    FCE = L["face"]
    hinge, front = bl(J["jaw"]), bl(FCE["mouth_c"])
    corners = [bl(FCE[k]) for k in ("mouth_corner_L", "mouth_corner_R") if FCE.get(k)]
    corner = sum(corners, Vector()) / len(corners) if corners else (front + hinge) / 2
    prof = sorted([(front.y, front.z), (corner.y, corner.z), (hinge.y, hinge.z)])

    def mouth_z(y):
        if y <= prof[0][0]:
            return prof[0][1]
        for (y0, z0), (y1, z1) in zip(prof, prof[1:]):
            if y <= y1:
                return z0 + (z1 - z0) * (y - y0) / max(y1 - y0, 1e-9)
        return prof[-1][1]

    eyes = [bl(J[k]) for k in ("eye_L", "eye_R") if k in J]
    half_w = (abs(eyes[0].x - eyes[1].x) * 1.1 if len(eyes) == 2 else (hinge - front).length)
    fade = max(abs(hinge.y - front.y) * 0.5, 1e-6)   # wide fade toward the hinge: cheeks and throat stretch smoothly
    jaw_name = NAMES["jaw"]
    donors = (NAMES["head"], NAMES["neck"])   # the chin can sit below the head joint and belong to the neck
    jlen = (hinge - bl(J["jaw_end"])).length
    floor_z, fz = bl(J["jaw_end"]).z - jlen * 0.5, jlen * 0.3   # soft lower edge under the chin, toward the neck
    moved = 0
    for o in meshes:
        dg = [o.vertex_groups.get(n) for n in donors]
        dg = [g for g in dg if g is not None]
        jg = o.vertex_groups.get(jaw_name) or o.vertex_groups.new(name=jaw_name)
        if not dg:
            continue
        idx = {g.index: g for g in dg}
        mw = o.matrix_world
        for v in o.data.vertices:
            ws = {g.group: g.weight for g in v.groups if g.group in idx}
            total = sum(ws.values())
            if total <= 0.3:
                continue   # mostly body/arms (a hand near the face stays put)
            p = mw @ v.co
            if p.y > hinge.y or abs(p.x - hinge.x) > half_w or p.z > mouth_z(p.y) or p.z < floor_z:
                continue
            w = 1.0 if p.y < hinge.y - fade else (hinge.y - p.y) / fade
            w *= min(1.0, (p.z - floor_z) / fz) * min(1.0, (half_w - abs(p.x - hinge.x)) / (half_w * 0.3))
            if w <= 0:
                continue
            for gi, gw in ws.items():
                idx[gi].add([v.index], gw * (1 - w), "REPLACE")
            jg.add([v.index], total * w, "REPLACE")
            moved += 1
    report["jaw_vertices"] = moved
if any(f"eye_{s_}" in TAIL for s_ in "LR"):
    eye_hits = 0
    for o in meshes:
        # islands of the welded surface: Tripo meshes are cut along UV seams, so copies at one position are joined
        n = len(o.data.vertices); parent = list(range(n))

        def find(i):
            while parent[i] != i:
                parent[i] = parent[parent[i]]; i = parent[i]
            return i
        for e in o.data.edges:
            a, b = find(e.vertices[0]), find(e.vertices[1])
            if a != b:
                parent[a] = b
        key = {}
        q = max(height * 1e-5, 1e-9)
        for v in o.data.vertices:
            k = tuple(round(c / q) for c in v.co)
            if k in key:
                a, b = find(v.index), find(key[k])
                if a != b:
                    parent[a] = b
            else:
                key[k] = v.index
        groups = {}
        for i in range(n):
            groups.setdefault(find(i), []).append(i)
        mw = o.matrix_world
        for isl in groups.values():
            c = sum((mw @ o.data.vertices[i].co for i in isl), Vector()) / len(isl)
            for s_ in "LR":
                if f"eye_{s_}" not in TAIL:
                    continue
                ec, ee = bl(J[f"eye_{s_}"]), bl(J[f"eye_end_{s_}"])
                if (c - ec).length < (ee - ec).length * 1.3 and len(isl) < 5000:   # a loose eyeball
                    eg = o.vertex_groups.get(NAMES[f"eye_{s_}"]) or o.vertex_groups.new(name=NAMES[f"eye_{s_}"])
                    for i in isl:
                        for g in list(o.data.vertices[i].groups):
                            o.vertex_groups[g.group].remove([i])
                        eg.add([i], 1.0, "REPLACE")
                    eye_hits += 1
    report["loose_eyes"] = eye_hits
if "jaw" in TAIL or any(f"eye_{s_}" in TAIL for s_ in "LR"):
    for o in meshes:
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)

# ---- heel helpers, added after skinning so they get no weights; kept as deform bones so glTF lists them in the
# skin and Godot imports them as real skeleton bones (for foot IK / roll)
heels = [s for s in "LR" if f"heel_{s}" in J]
if heels:
    bpy.ops.object.select_all(action="DESELECT")
    rig.select_set(True)
    bpy.context.view_layer.objects.active = rig
    bpy.ops.object.mode_set(mode="EDIT")
    for s in heels:
        foot = arm_data.edit_bones[NAMES[f"foot_{s}"]]
        hb = arm_data.edit_bones.new(NAMES[f"heel_{s}"])
        hb.head = bl(J[f"heel_{s}"])
        hb.tail = hb.head + Vector((0, 0, max(foot.length * 0.3, 1e-4)))
        hb.parent = foot
    bpy.ops.object.mode_set(mode="OBJECT")
    report["heel_bones"] = len(heels)

# ------------------------------------------------------------------ export (rest pose)
bpy.ops.object.select_all(action="DESELECT")
for o in meshes:
    o.select_set(True)
rig.select_set(True)
bpy.context.view_layer.objects.active = rig
bpy.ops.export_scene.gltf(filepath=str(OUT / "model.glb"), export_format="GLB", use_selection=True,
                          export_animations=False, export_skins=True, export_influence_nb=4)

# ------------------------------------------------------------------ check renders: rest and a stress pose
lo = Vector((min((o.matrix_world @ Vector(c)).x for o in meshes for c in o.bound_box),
             min((o.matrix_world @ Vector(c)).y for o in meshes for c in o.bound_box),
             min((o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box)))
hi = Vector((max((o.matrix_world @ Vector(c)).x for o in meshes for c in o.bound_box),
             max((o.matrix_world @ Vector(c)).y for o in meshes for c in o.bound_box),
             max((o.matrix_world @ Vector(c)).z for o in meshes for c in o.bound_box)))
mid, size = (lo + hi) / 2, hi - lo
try:
    scene.render.engine = "BLENDER_WORKBENCH"
    scene.display.shading.color_type = "TEXTURE"
    scene.display.shading.light = "STUDIO"
except (TypeError, AttributeError):
    pass
scene.render.resolution_x, scene.render.resolution_y = 560, 640
scene.render.film_transparent = False
scene.render.image_settings.color_mode = "RGB"
scene.world = bpy.data.worlds.new("bg")
scene.world.color = (0.82, 0.8, 0.77)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
scene.collection.objects.link(cam)
scene.camera = cam
cam.data.type = "ORTHO"
cam.data.ortho_scale = max(size.x, size.z, size.y) * 1.45


far = max(size.x, size.y, size.z) * 3  # camera outside the model at any unit scale (m or cm)


def shot(name, side=False):
    if side:
        cam.location = (mid.x + far, mid.y, mid.z)
        cam.rotation_euler = (math.radians(90), 0, math.radians(90))
    else:
        cam.location = (mid.x, mid.y - far, mid.z)
        cam.rotation_euler = (math.radians(90), 0, 0)
    cam.data.clip_end = far * 3
    scene.render.filepath = str(OUT / name)
    bpy.ops.render.render(write_still=True)


shot("rest.png")


def turn(jid, axis, deg):
    pb = rig.pose.bones[NAMES[jid]]
    m = pb.matrix.copy()
    h = m.to_translation()
    pb.matrix = Matrix.Translation(h) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-h) @ m
    bpy.context.view_layer.update()


def bend(jid, toward, deg):
    """Swing a bone's tip toward a world direction (anatomical flexion), whatever its roll or rest direction."""
    pb = rig.pose.bones[NAMES[jid]]
    d = ((rig.matrix_world @ pb.tail) - (rig.matrix_world @ pb.head)).normalized()
    axis = d.cross(Vector(toward))
    if axis.length > 1e-6:
        turn(jid, axis.normalized(), deg)


FWD, UP = (0, -1, 0), (0, 0, 1)                             # Blender: the character faces -Y
clav = job.get("clavicle", 25)                               # the collarbone takes part of an overhead raise
bend("shoulder_L", UP, clav); bend("arm_L", UP, 140 - clav); bend("forearm_L", FWD, 35)  # left arm over the head
bend("arm_R", FWD, 75); bend("forearm_R", UP, 80)           # right arm forward, elbow flexed up (guard)
bend("upleg_L", FWD, 60); bend("leg_L", (0, 1, 0), 90)      # left knee up, shin folded back
bend("upleg_R", (0, 1, 0), 20)                              # right leg back
turn("spine1", "Z", 20)                                     # torso twist
shot("pose_front.png")
shot("pose_side.png", side=True)
if job.get("closeup"):
    sh = rig.matrix_world @ rig.pose.bones[NAMES["arm_L"]].head
    cam.data.ortho_scale = size.z * 0.35
    cam.location = (sh.x, mid.y - far, sh.z); cam.rotation_euler = (math.radians(90), 0, 0)
    scene.render.filepath = str(OUT / "shoulder.png"); bpy.ops.render.render(write_still=True)

# ---- fist close-up of the left hand when fingers are rigged
if "middle1_L" in TAIL:
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix()
    bpy.context.view_layer.update()
    W, M = bl(J["hand_L"]), bl(J["middle1_L"])
    I, P5 = bl(J.get("index1_L", J["middle1_L"])), bl(J.get("pinky1_L", J.get("ring1_L", J["middle1_L"])))
    palm = (M - W).normalized().cross(I - P5)
    palm = palm.normalized() if palm.length > 1e-9 else Vector((-1, 0, 0))
    for f in ("thumb", "index", "middle", "ring", "pinky"):
        for k, a in enumerate((25, 40, 50) if f == "thumb" else (80, 95, 70), 1):
            if f"{f}{k}_L" in TAIL:
                bend(f"{f}{k}_L", palm, a)
    pts = [bl(v) for k, v in J.items() if k.endswith("_L") and (FINGER.match(k) or k.startswith(("thumb4", "index4", "middle4", "ring4", "pinky4")))]
    c = sum(pts, Vector()) / len(pts)
    span = max((p - c).length for p in pts)
    cam.data.ortho_scale = span * 3.2
    cam.location = (c.x + far, c.y, c.z); cam.rotation_euler = (math.radians(90), 0, math.radians(90))
    scene.render.filepath = str(OUT / "hand_fist.png")
    bpy.ops.render.render(write_still=True)
    report["finger_bones"] = sum(1 for k in TAIL if FINGER.match(k))

# ---- open-mouth close-up when the jaw is rigged
if "jaw" in TAIL:
    for pb in rig.pose.bones:
        pb.matrix_basis = Matrix()
    bpy.context.view_layer.update()
    bend("jaw", (0, 0, -1), 25)
    hd, top = bl(J["head"]), bl(J["head_top"])
    span = (top - bl(J["jaw_end"])).length
    cam.data.ortho_scale = span * 1.6
    cam.location = (hd.x, hd.y - far, (top.z + bl(J["jaw_end"]).z) / 2); cam.rotation_euler = (math.radians(90), 0, 0)
    scene.render.filepath = str(OUT / "face_jaw.png")
    bpy.ops.render.render(write_still=True)

(OUT / "rig_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")
print("LANDMARK_RIG_OK", json.dumps(report), flush=True)
