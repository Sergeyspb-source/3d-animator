"""Face bones on a skeleton made without the face (an auto-rig): blender -b -P blender_face_bones.py -- job.json

job: {source (skinned GLB), out (GLB), joints: {jaw, jaw_end, eye_L, eye_end_L, eye_R, eye_end_R} (glTF space, from
the face marked in the editor), face: {mouth_c, mouth_corner_L/R}, names: {head, neck, jaw, eye_L, eye_R} (the
skeleton's own naming), report}.

The jaw bone goes from its hinge (in front of the ear) to the chin, the eye bones from the ball centres to the
corneas, all children of the head; a bone already there is moved to the marked place. The jaw takes the head's (or
the neck's) weight below the mouth line, fading out before the hinge and under the chin - as the skeleton built from
the markup does it (blender_landmark_rig.py), so the mouth cut that follows opens the chin with the jaw. The eyes get
no skin: the eyeballs put in later are weighted to their bones. Prints FACEBONES_OK <report json>.
"""
import json
import sys

import bpy
from mathutils import Vector

a = sys.argv[sys.argv.index("--") + 1:]
job = json.load(open(a[0], encoding="utf-8"))
bl = lambda p: Vector((p[0], -p[2], p[1]))   # glTF (y up) -> Blender (z up)
J, FCE, NAMES = job["joints"], job.get("face") or {}, job["names"]
report = {}

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["source"])
arm = next((o for o in bpy.data.objects if o.type == "ARMATURE"), None)
if arm is None:
    print("FACEBONES_FAIL no skeleton in the model", flush=True)
    sys.exit(1)
meshes = [o for o in bpy.data.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
if NAMES["head"] not in arm.data.bones:
    print("FACEBONES_FAIL no head bone " + NAMES["head"], flush=True)
    sys.exit(1)

# ---- the bones
bpy.ops.object.select_all(action="DESELECT")
arm.select_set(True); bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
inv = arm.matrix_world.inverted()
eb = arm.data.edit_bones
head_b = eb[NAMES["head"]]
made = []
for key, tail in (("jaw", "jaw_end"), ("eye_L", "eye_end_L"), ("eye_R", "eye_end_R")):
    if key not in J or tail not in J or key not in NAMES:
        continue
    b = eb.get(NAMES[key]) or eb.new(NAMES[key])
    b.head, b.tail = inv @ bl(J[key]), inv @ bl(J[tail])
    if (b.tail - b.head).length < 1e-5:
        b.tail = b.head + Vector((0, 0, 0.01))
    b.roll = 0.0
    b.parent = head_b; b.use_connect = False; b.use_deform = True
    made.append(NAMES[key])
bpy.ops.object.mode_set(mode="OBJECT")
report["bones"] = made

# ---- the jaw's skin: the head weight below the mouth line (blender_landmark_rig.py's rule)
if "jaw" in J and "jaw_end" in J and FCE.get("mouth_c"):
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
    half_w = abs(eyes[0].x - eyes[1].x) * 1.1 if len(eyes) == 2 else (hinge - front).length
    fade = max(abs(hinge.y - front.y) * 0.5, 1e-6)
    jlen = (hinge - bl(J["jaw_end"])).length
    floor_z, fz = bl(J["jaw_end"]).z - jlen * 0.5, jlen * 0.3
    donors = (NAMES["head"], NAMES.get("neck", ""))
    moved = 0
    for o in meshes:
        dg = [g for g in (o.vertex_groups.get(n) for n in donors if n) if g is not None]
        jg = o.vertex_groups.get(NAMES["jaw"]) or o.vertex_groups.new(name=NAMES["jaw"])
        if not dg:
            continue
        idx = {g.index: g for g in dg}
        mw = o.matrix_world
        for v in o.data.vertices:
            ws = {g.group: g.weight for g in v.groups if g.group in idx}
            total = sum(ws.values())
            if total <= 0.3:
                continue
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
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True); bpy.context.view_layer.objects.active = o
        bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    report["jaw_vertices"] = moved

arm.data.pose_position = "POSE"
bpy.ops.object.select_all(action="DESELECT")
for o in bpy.data.objects:
    o.select_set(o.type in ("ARMATURE", "MESH"))
bpy.context.view_layer.objects.active = arm
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False, export_morph=True, export_morph_normal=True, export_influence_nb=4)
if job.get("report"):
    json.dump(report, open(job["report"], "w", encoding="utf-8"), indent=1)
print("FACEBONES_OK " + json.dumps(report), flush=True)
