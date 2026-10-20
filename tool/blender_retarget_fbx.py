"""Runs INSIDE Blender (background): copy Mixamo FBX animations (same bone names) onto a rigged GLB character.

    blender -b -P blender_retarget_fbx.py -- character.glb out.glb map.json [mesh=0|1]

map.json: {"<fbx file name without .fbx>": {"name": "Slash", "loop": false}, ...}
Each bone of the target gets the same *world-space* rotation change from its rest pose that the FBX bone has, so the
FBX file may use another bone orientation, scale or axis convention (Mixamo FBX is in centimetres, Y-up, rotated),
as long as both skeletons share the rest pose. Hips translation is scaled by the ratio of the hips heights.
A clip with "mirror": true is the mirror image of the FBX (a left strafe becomes a right strafe): every bone takes the reflected motion of its
left/right partner, reflected across the sagittal plane of the FBX skeleton.
Exports a GLB with one NLA track per clip. Prints RETARGET_ lines.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst, mapfile = Path(argv[0]), Path(argv[1]), Path(argv[2])
opt = dict(a.split("=", 1) for a in argv[3:] if "=" in a)
CLIPS = json.loads(mapfile.read_text(encoding="utf-8"))
FBX_DIR = Path(opt.get("fbx", str(mapfile.parent)))
FPS = 30

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.render.fps = FPS
bpy.ops.import_scene.gltf(filepath=str(src))
gob = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
if gob.animation_data:
    gob.animation_data_clear()
for a in list(bpy.data.actions):
    bpy.data.actions.remove(a)
for pb in gob.pose.bones:
    pb.rotation_mode = "QUATERNION"
Wg = gob.matrix_world.to_3x3().normalized()
order = []                     # bones, parents first


def walk(b):
    order.append(b)
    for c in b.children:
        walk(c)


for b in gob.data.bones:
    if b.parent is None:
        walk(b)
M = {b.name: b.matrix_local.to_3x3().normalized() for b in gob.data.bones}
HIPS = next(b.name for b in gob.data.bones if b.name.endswith("Hips"))
hips_h = (gob.matrix_world @ gob.data.bones[HIPS].head_local).z


PREFER = ["Spine", "Spine1", "Spine2", "Neck", "Head", "HeadTop_End", "Arm", "ForeArm", "Hand", "Middle1", "Leg", "Foot",
          "ToeBase", "Toe_End"]


def dir_child(bone):
    """the child that defines the bone's direction (the next joint down the chain)"""
    kids = list(bone.children)
    if not kids:
        return None
    for suffix in PREFER:
        for c in kids:
            if c.name.endswith(suffix) and not c.name.endswith("Shoulder"):
                return c
    return kids[0]


def frame(d, x):
    """orthonormal frame (columns: x, d, z) from a bone direction and a roll reference"""
    d = d.normalized()
    x = (x - d * x.dot(d))
    x = x.normalized() if x.length > 1e-6 else d.orthogonal().normalized()
    return Matrix((x, d, x.cross(d))).transposed()


def import_fbx(path):
    before = set(bpy.context.scene.objects)
    bpy.ops.import_scene.fbx(filepath=str(path))
    new = [o for o in bpy.context.scene.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    for o in new:
        if o.type != "ARMATURE":
            bpy.data.objects.remove(o)
    return arm


def partner(name):
    """the same bone on the other side (Mixamo names: LeftArm <-> RightArm), itself for the middle ones"""
    if "Left" in name:
        return name.replace("Left", "Right")
    return name.replace("Right", "Left") if "Right" in name else name


done = []
for stem, spec in CLIPS.items():
    fbx = FBX_DIR / f"{stem}.fbx"
    if not fbx.exists():
        print("RETARGET_MISSING", stem)
        continue
    af = import_fbx(fbx)
    act_f = af.animation_data.action
    f0, f1 = int(act_f.frame_range[0]), int(act_f.frame_range[1])
    Wf = af.matrix_world.to_3x3().normalized()
    names_f = {b.name for b in af.data.bones}
    common = [b for b in order if b.name in names_f]
    missing = [b.name for b in order if b.name not in names_f]
    rest_f = {b.name: Wf @ b.matrix_local.to_3x3().normalized() for b in af.data.bones}
    hips_f = (Wf @ af.data.bones[HIPS].head_local).z      # armature-local units: the importer also scales the object
    k = hips_h / hips_f if abs(hips_f) > 1e-6 else 1.0
    rest_head_f = Wf @ af.data.bones[HIPS].head_local
    if not done:             # how well do the two rest poses agree? (world positions of the bone heads, scaled)
        err = 0.0
        for b in common:
            pg = gob.matrix_world @ gob.data.bones[b.name].head_local
            pf = (Wf @ af.data.bones[b.name].head_local) * k
            err = max(err, (pg - pf).length)
        print("RETARGET_REST max head difference %.3f m (hips %.3f vs %.3f)" % (err, hips_h, hips_f))
    mirror = bool(spec.get("mirror"))
    lateral = Vector((1, 0, 0))
    if mirror:   # the sagittal plane: normal = from the left hip to the right hip of the FBX skeleton, horizontal
        lateral = (Wf @ (af.data.bones[partner(next(n for n in names_f if n.endswith("LeftUpLeg")))].head_local
                         - af.data.bones[next(n for n in names_f if n.endswith("LeftUpLeg"))].head_local))
        lateral.z = 0.0
        lateral.normalize()
    S = (Matrix.Identity(3) - 2.0 * Matrix(((lateral.x * lateral.x, lateral.x * lateral.y, lateral.x * lateral.z),
                                           (lateral.y * lateral.x, lateral.y * lateral.y, lateral.y * lateral.z),
                                           (lateral.z * lateral.x, lateral.z * lateral.y, lateral.z * lateral.z)))) if mirror else Matrix.Identity(3)

    def rv(v):
        return S @ v

    def src_of(name):
        return partner(name) if mirror else name
    first_delta = None
    act = bpy.data.actions.new(spec["name"])
    ad = gob.animation_data_create()
    ad.action = act
    speed = float(spec.get("speed", 1.0))
    n = max(2, int(round((f1 - f0 + 1) / speed)))
    if spec.get("loop") and n > 8:
        n -= 1                 # a loop starts again at its first pose: drop the duplicate closing frame
    for fi in range(n):
        ff = f0 + fi * speed
        f = int(math.floor(ff))
        bpy.context.scene.frame_set(f, subframe=ff - f)
        f = f0 + fi
        bpy.context.view_layer.update()
        tot = {}
        for b in order:
            nm = b.name
            tw = Matrix.Identity(3)
            sn = src_of(nm)                                                    # the FBX bone that drives this one (its partner when mirrored)
            if sn in names_f:
                pf = af.pose.bones[sn]
                tw = S @ ((Wf @ pf.matrix.to_3x3().normalized()) @ rest_f[sn].inverted()) @ S      # world rotation change of the FBX bone
            kid = dir_child(b)
            if sn in names_f and kid is not None and src_of(kid.name) in names_f:
                # two-vector retarget: the bone axis follows the FBX bone, and the roll about it follows the FBX roll
                # corrected by the constant roll offset between the two rigs (their rest rolls differ)
                bf_ = af.data.bones[sn]
                kf = af.data.bones[src_of(kid.name)]
                d_f_rest = rv(Wf @ (kf.head_local - bf_.head_local)).normalized()
                d_g_rest = (Wg @ (gob.data.bones[kid.name].head_local - b.head_local)).normalized()
                x_f_rest = rv((Wf @ bf_.matrix_local.to_3x3()).col[0]).normalized()
                x_g_rest = (Wg @ b.matrix_local.to_3x3()).col[0].normalized()
                x_g_al = d_g_rest.rotation_difference(d_f_rest).to_matrix() @ x_g_rest
                cs = (x_f_rest - d_f_rest * x_f_rest.dot(d_f_rest)).normalized()
                ca = (x_g_al - d_f_rest * x_g_al.dot(d_f_rest)).normalized()
                c = math.atan2(d_f_rest.dot(cs.cross(ca)), cs.dot(ca))               # rest roll offset
                d_now = rv(Wf @ (af.pose.bones[src_of(kid.name)].head - af.pose.bones[sn].head)).normalized()
                x_now = rv((Wf @ af.pose.bones[sn].matrix.to_3x3()).col[0]).normalized()
                x_now = (x_now - d_now * x_now.dot(d_now)).normalized()
                x_tgt = Quaternion(d_now, c).to_matrix() @ x_now
                tw_g = frame(d_now, x_tgt) @ frame(d_g_rest, x_g_rest).inverted()
            else:
                tw_g = tw                                             # leaf bones: the plain rotation change
            tot[nm] = Wg.inverted() @ tw_g @ Wg                       # in the target's armature axes
            par = b.parent
            rp = tot[par.name] if par else Matrix.Identity(3)
            rc = rp.inverted() @ tot[nm]
            m = M[nm]
            pg = gob.pose.bones[nm]
            pg.rotation_quaternion = (m.inverted() @ rc @ m).to_quaternion()
            pg.keyframe_insert("rotation_quaternion", frame=f - f0 + 1)
        pf_h = af.pose.bones[HIPS]
        delta = rv((Wf @ pf_h.head) - rest_head_f) * k
        if spec.get("inplace", True):
            if first_delta is None:
                first_delta = Vector(delta)
            delta = Vector((first_delta.x, first_delta.y, delta.z))     # hips keep their height, not their ground travel
        pg_h = gob.pose.bones[HIPS]
        pg_h.location = M[HIPS].inverted() @ (Wg.inverted() @ delta)
        pg_h.keyframe_insert("location", frame=f - f0 + 1)
    act.use_frame_range = True
    act.frame_start, act.frame_end = 1, n
    tr = ad.nla_tracks.new()
    tr.name = spec["name"]
    st = tr.strips.new(spec["name"], 1, act)
    st.frame_end = n
    ad.action = None
    bpy.data.objects.remove(af)
    done.append(dict(name=spec["name"], frames=n, seconds=round(n / FPS, 3), loop=bool(spec.get("loop")),
                     missing=missing))
    print("RETARGET_CLIP", spec["name"], n, "frames", "missing bones:" if missing else "", len(missing))

for pb in gob.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.location = (0, 0, 0)
bpy.ops.object.select_all(action="DESELECT")
for o in bpy.context.scene.objects:
    if o.type == "ARMATURE" or (o.type == "MESH" and opt.get("mesh", "1") == "1"):
        o.select_set(True)
dst.parent.mkdir(parents=True, exist_ok=True)
Path(str(dst) + ".json").write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
try:
    bpy.ops.export_scene.gltf(filepath=str(dst), export_format="GLB", use_selection=True,
                              export_animation_mode="NLA_TRACKS", export_force_sampling=True)
except TypeError:
    bpy.ops.export_scene.gltf(filepath=str(dst), export_format="GLB", use_selection=True,
                              export_animation_mode="NLA_TRACKS")
print("RETARGET_GLB", dst)
