"""Runs INSIDE Blender (background): add a library of procedural animations to a rigged humanoid GLB.

    blender -b -P blender_humanoid_anim.py -- rigged.glb out.glb [clips=idle,walk,...] [fps=30] [preview=dir]

The skeleton may use Mixamo names (mixamorig:Hips ...) or Godot's humanoid names (Hips, LeftUpperArm ...). Poses are
computed in the character's own frame (forward / right / up measured from the bones), so any rest pose works; the arms
are normalised to a relaxed stance first. Clips (Godot makes `_loop` clips loop and strips the suffix):
  idle_loop walk_loop run_loop jump fall_loop land attack_slash attack_overhead cast block_loop hit death
Adds bone `rotation_quaternion` keys (and hips location), one NLA track per clip, exports GLB with the NLA tracks.
Prints ANIM_ lines; preview=dir also renders 6 side-view frames of every clip (dir/<clip>_<n>.png).
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = Path(argv[0]), Path(argv[1])
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
FPS = int(opt.get("fps", 30))
PREVIEW = opt.get("preview")
ALL = ["idle_loop", "walk_loop", "run_loop", "jump", "fall_loop", "land", "attack_slash", "attack_overhead", "cast",
       "block_loop", "hit", "death"]
TWOHAND = opt.get("twohand", "0") == "1"    # both hands on one sword: the left arm is solved to the grip of the right hand
TILT = float(opt.get("sword_tilt", "-55"))  # degrees, blade tilt in the right hand's frame (same value as the Godot socket)
HAND_GAP = float(opt.get("hand_gap", "0.22"))   # metres between the two hands along the handle
AIM = opt.get("aim", "0") == "1" or TWOHAND   # the right hand turns so the sword points where the pose says (blade key)
SHIELD = opt.get("shield", "0") == "1"      # the left arm carries a shield: held in front in every clip but death
# blade=fingers: the sword lies across the palm, from the little finger's knuckle to the index finger's, whatever the
# hand bone's roll (TILT is set for one rig's roll and twists the wrist of another); the palm and the gap between the
# hands then scale with the character's height instead of being metres (the animation gallery)
FINGER_BLADE = opt.get("blade") == "fingers"
print("ANIM_OPT twohand", TWOHAND, "shield", SHIELD, flush=True)
WANT = [c.strip() for c in opt.get("clips", ",".join(ALL)).split(",") if c.strip()]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=str(src))
arm = next((o for o in bpy.context.scene.objects if o.type == "ARMATURE"), None)
if arm is None:
    raise SystemExit("ANIM_ERROR no armature in the model")
bpy.context.view_layer.objects.active = arm
bones = arm.data.bones
bpy.context.scene.render.fps = FPS
bpy.context.scene.render.fps_base = 1.0

# ---------------------------------------------------------------- bone names
SEM = {"hips": ["Hips"], "spine": ["Spine"], "spine1": ["Spine1", "Chest"], "spine2": ["Spine2", "UpperChest"],
       "neck": ["Neck"], "head": ["Head"]}
for s, (m, g) in {"L": ("Left", "Left"), "R": ("Right", "Right")}.items():
    SEM[f"arm_{s}"] = [f"{m}Arm", f"{g}UpperArm"]
    SEM[f"forearm_{s}"] = [f"{m}ForeArm", f"{g}LowerArm"]
    SEM[f"hand_{s}"] = [f"{m}Hand"]
    SEM[f"thigh_{s}"] = [f"{m}UpLeg", f"{g}UpperLeg"]
    SEM[f"shin_{s}"] = [f"{m}Leg", f"{g}LowerLeg"]
    SEM[f"foot_{s}"] = [f"{m}Foot"]
    SEM[f"toe_{s}"] = [f"{m}ToeBase", f"{g}Toes"]
NAME = {}
for key, cands in SEM.items():
    for c in cands:
        for b in bones:
            if b.name == c or b.name == "mixamorig:" + c or b.name.endswith(":" + c) or b.name.endswith("_" + c):
                NAME[key] = b.name
                break
        if key in NAME:
            break
need = ["hips", "spine", "head", "arm_L", "arm_R", "forearm_L", "forearm_R", "thigh_L", "thigh_R", "shin_L",
        "shin_R", "foot_L", "foot_R"]
missing = [k for k in need if k not in NAME]
if missing:
    raise SystemExit("ANIM_ERROR bones not found: " + ",".join(missing))
SPINE_KEYS = [k for k in ("spine", "spine1", "spine2") if k in NAME and
              NAME[k] not in [NAME[j] for j in ("spine", "spine1", "spine2") if j in NAME and j < k]]
NSP = len(SPINE_KEYS)

# ---------------------------------------------------------------- the character's frame, in armature space
B = lambda k: bones[NAME[k]]
hips_h = B("hips").head_local.copy()
up = (B("head").tail_local - hips_h)
up = up.normalized() if up.length > 1e-6 else Vector((0, 0, 1))
up = Vector((0, 0, 1)) if abs(up.z) > 0.7 else up
# the hip line gives the sideways axis; the toes tell which way is forward
right = (B("thigh_R").head_local - B("thigh_L").head_local)
right = (right - up * right.dot(up))
right = right.normalized() if right.length > 1e-6 else Vector((1, 0, 0))
fwd = up.cross(right).normalized()
toe = (B("toe_L").tail_local if "toe_L" in NAME else B("foot_L").tail_local) - B("foot_L").head_local
if toe.dot(fwd) < 0:
    fwd, right = -fwd, -right
HEIGHT = max(0.2, (B("head").tail_local - min((B("foot_L").tail_local, B("foot_R").tail_local),
                                                key=lambda v: v.dot(up))).dot(up))
LEG = (B("thigh_L").head_local - B("foot_L").head_local).length
print("ANIM_FRAME fwd", [round(x, 2) for x in fwd], "right", [round(x, 2) for x in right], "height", round(HEIGHT, 3))

REST = {n: bones[n].matrix_local.to_3x3() for n in NAME.values()}


def abduction(key, side):
    """rest angle of a limb away from straight down, in the frontal plane (degrees, + = away from the body)"""
    b = B(key)
    d = (b.tail_local - b.head_local).normalized()
    out = d.dot(-right if side == "L" else right)
    down = d.dot(-up)
    return math.degrees(math.atan2(out, down))


REST_ABD = {k: abduction(k, k[-1]) for k in ("arm_L", "arm_R", "thigh_L", "thigh_R")}

# ---------------------------------------------------------------- pose model
UPRIGHT = {"hips", "spine", "spine1", "spine2", "neck", "head"}
LIMB_ABS = {"arm_L", "arm_R", "thigh_L", "thigh_R"}       # roll = absolute angle away from the body
D = math.radians


def rot(axis, deg):
    return Matrix.Rotation(D(deg), 3, axis)


def bone_rotation(key, pitch, roll, yaw):
    """armature-space rotation increment for a bone given in the character's terms (see the module notes):
    upright chains: pitch + = lean forward, roll + = lean to the right, yaw + = turn left;
    limbs: pitch + = distal end swings forward, roll + = away from the body (arms and thighs absolute), yaw + = turn left"""
    if key in UPRIGHT:
        return rot(up, yaw) @ rot(fwd, roll) @ rot(right, -pitch)
    side = 1.0 if key.endswith("_L") else -1.0
    if key in LIMB_ABS:
        roll = roll - REST_ABD[key]
    return rot(up, yaw) @ rot(right, pitch) @ rot(fwd, side * roll)


BASE = {k: (0.0, 0.0, 0.0) for k in SEM if k in NAME}
# where the blade points, in the character's terms (forward, up, right); only used with aim / twohand
BASE["blade"] = (0.3, 0.93, 0.0) if TWOHAND else (0.85, 0.45, 0.0)
for k in ("arm_L", "arm_R"):
    BASE[k] = (0.0, 9.0, 0.0)
for k in ("thigh_L", "thigh_R"):
    BASE[k] = (0.0, 2.0, 0.0)


def pose(**kw):
    p = dict(BASE)
    ht = kw.pop("hip_t", (0.0, 0.0, 0.0))
    for k, v in kw.items():
        if k not in p:                       # a bone this skeleton does not have
            continue
        if not isinstance(v, (tuple, list)):
            v = (v,)
        p[k] = tuple(v) + (0.0,) * (3 - len(v))
    p["hip_t"] = tuple(ht)                   # (right, forward, up) in units of the character's height
    return p


def mix(a, b, t):
    out = {}
    for k in a:
        if k == "hip_t":
            out[k] = tuple(x + (y - x) * t for x, y in zip(a[k], b[k]))
        else:
            out[k] = tuple(x + (y - x) * t for x, y in zip(a[k], b[k]))
    return out


def smooth(x):
    x = max(0.0, min(1.0, x))
    return x * x * (3 - 2 * x)


def keyed(keys, ease=None):
    """keys = [(time 0..1, pose)] -> function of time. Monotone cubic (PCHIP) through the keys: no stops at the keys
    (a smoothstep per segment stops the body at every key), no overshoot, holds stay still."""
    ts = [k[0] for k in keys]
    names = list(keys[0][1].keys())
    tang = {}
    for nme in names:
        for c in range(3):
            ys = [k[1][nme][c] for k in keys]
            n = len(ys)
            d = [(ys[i + 1] - ys[i]) / max(ts[i + 1] - ts[i], 1e-6) for i in range(n - 1)]
            m = [0.0] * n
            for i in range(1, n - 1):
                if d[i - 1] * d[i] > 0:
                    w1 = 2 * (ts[i + 1] - ts[i]) + (ts[i] - ts[i - 1])
                    w2 = (ts[i + 1] - ts[i]) + 2 * (ts[i] - ts[i - 1])
                    m[i] = (w1 + w2) / (w1 / d[i - 1] + w2 / d[i])
            tang[(nme, c)] = m

    def f(t):
        t = min(max(t, ts[0]), ts[-1])
        i = 0
        while i < len(ts) - 2 and t > ts[i + 1]:
            i += 1
        h = max(ts[i + 1] - ts[i], 1e-6)
        s_ = (t - ts[i]) / h
        h00, h10 = 2 * s_ ** 3 - 3 * s_ ** 2 + 1, s_ ** 3 - 2 * s_ ** 2 + s_
        h01, h11 = -2 * s_ ** 3 + 3 * s_ ** 2, s_ ** 3 - s_ ** 2
        out = {}
        for nme in names:
            vals = []
            for c in range(3):
                y0, y1 = keys[i][1][nme][c], keys[i + 1][1][nme][c]
                m0, m1 = tang[(nme, c)][i], tang[(nme, c)][i + 1]
                vals.append(h00 * y0 + h10 * h * m0 + h01 * y1 + h11 * h * m1)
            out[nme] = tuple(vals)
        return out
    return f


S = math.sin
C = math.cos
TAU = 2 * math.pi


def spine_split(total_pitch=0.0, total_roll=0.0, total_yaw=0.0):
    """share a bend between the spine bones (the upper ones take more); keys of missing bones are ignored later"""
    w = {1: [1.0], 2: [0.4, 0.6], 3: [0.25, 0.35, 0.4]}[max(1, min(3, NSP))]
    return {k: (total_pitch * wi, total_roll * wi, total_yaw * wi) for k, wi in zip(SPINE_KEYS, w)}


def gait(ph, amp, knee_max, arm_amp, elbow, lean, bob, sway, hip_yaw, arm_abd=9.0):
    """one phase of a walk / run; ph in 0..1"""
    a = ph * TAU
    leg = {}
    for s, off in (("L", 0.0), ("R", math.pi)):
        sw = amp * S(a + off)
        kn = 6 + knee_max * max(0.0, C(a + off)) ** 1.4
        foot_ang = (kn - sw) * 0.85
        leg[f"thigh_{s}"] = (sw, 2.0, 0)
        leg[f"shin_{s}"] = (-kn, 0, 0)
        leg[f"foot_{s}"] = (foot_ang, 0, 0)
    arms = {}
    for s, off in (("L", math.pi), ("R", 0.0)):
        sw = arm_amp * S(a + off)
        arms[f"arm_{s}"] = (sw, arm_abd, 0)
        arms[f"forearm_{s}"] = (elbow + 12 * max(0.0, S(a + off + 0.6)), 0, 0)
    sp = spine_split(lean, sway * 0.6 * S(a), -hip_yaw * 1.2 * S(a))
    p = pose(hips=(0, sway * S(a), hip_yaw * S(a)), head=(-lean * 0.6, -sway * 0.4 * S(a), hip_yaw * 0.7 * S(a)),
             hip_t=(0.0, 0.0, -bob * (0.5 + 0.5 * C(2 * a))), **leg, **arms, **sp)
    return p


# ---------------------------------------------------------------- the clips: name -> (seconds, function(t in 0..1))
def idle(t):
    a = t * TAU
    br = S(a)
    sp = spine_split(1.0 * br, 0.6 * S(a * 0.5), 1.2 * S(a * 0.5 + 1))
    return pose(hips=(0, 1.2 * S(a * 0.5), 0), head=(-1.0 * br + 1.0, 0, 5 * S(a * 0.5 + 0.5)),
                neck=(0.5, 0, 2 * S(a * 0.5 + 0.5)),
                arm_L=(2 + 1.5 * br, 9 + 1.0 * br, 0), arm_R=(2 - 1.5 * br, 9 + 1.0 * br, 0),
                forearm_L=(14 + 2 * br, 0, 0), forearm_R=(14 + 2 * br, 0, 0),
                thigh_L=(0, 2, 0), thigh_R=(0, 2, 0),
                hip_t=(0.006 * S(a * 0.5), 0, -0.002 * (1 - C(a))), **sp)


def walk(t):
    return gait(t, amp=26, knee_max=48, arm_amp=22, elbow=18, lean=4, bob=0.022, sway=3.0, hip_yaw=5)


def run(t):
    return gait(t, amp=44, knee_max=92, arm_amp=42, elbow=82, lean=14, bob=0.045, sway=4.0, hip_yaw=9, arm_abd=7)


def land_pose(c):
    sp = spine_split(14 * c, 0, 0)
    return pose(hips=(10 * c, 0, 0), thigh_L=(32 * c, 4, 0), thigh_R=(32 * c, 4, 0), shin_L=(-62 * c, 0, 0),
                shin_R=(-62 * c, 0, 0), foot_L=(30 * c, 0, 0), foot_R=(30 * c, 0, 0),
                arm_L=(25 * c, 22, 0), arm_R=(25 * c, 22, 0), forearm_L=(25 * c, 0, 0), forearm_R=(25 * c, 0, 0),
                head=(-8 * c, 0, 0), hip_t=(0, 0, -0.1 * c), **sp)


TUCK = pose(hips=(0, 0, 0), thigh_L=(38, 4, 0), thigh_R=(12, 4, 0), shin_L=(-70, 0, 0), shin_R=(-30, 0, 0),
            foot_L=(15, 0, 0), foot_R=(10, 0, 0), arm_L=(-38, 40, 0), arm_R=(-38, 40, 0),
            forearm_L=(15, 0, 0), forearm_R=(15, 0, 0), **spine_split(-4, 0, 0))
JUMP = keyed([
    (0.00, pose()),
    (0.18, land_pose(1.0) | {"arm_L": (-50, 14, 0), "arm_R": (-50, 14, 0)}),         # crouch, arms back
    (0.34, pose(hips=(-4, 0, 0), thigh_L=(-8, 3, 0), thigh_R=(-8, 3, 0), shin_L=(-6, 0, 0), shin_R=(-6, 0, 0),
                foot_L=(-30, 0, 0), foot_R=(-30, 0, 0), arm_L=(150, 20, 0), arm_R=(150, 20, 0),
                head=(-10, 0, 0), hip_t=(0, 0, 0.14), **spine_split(-8, 0, 0))),        # push off, arms up
    (0.55, TUCK | {"hip_t": (0, 0, 0.30)}),                                              # top of the jump
    (0.78, land_pose(0.8) | {"hip_t": (0, 0, -0.02)}),                                   # landing
    (1.00, pose()),
])


def fall(t):
    a = t * TAU
    return TUCK | {"arm_L": (-20 + 8 * S(a), 60 + 6 * S(a), 0), "arm_R": (-20 - 8 * S(a), 60 - 6 * S(a), 0),
                   "thigh_L": (28 + 6 * S(a), 6, 0), "thigh_R": (14 - 6 * S(a), 6, 0),
                   "hip_t": (0, 0, 0.02 * S(a))}


LAND = keyed([(0.0, land_pose(0.0) | {"hip_t": (0, 0, 0)}), (0.2, land_pose(1.0)), (0.55, land_pose(0.55)), (1.0, pose())])
_READY = pose(arm_L=(30, 20, 0), arm_R=(24, 14, 0), forearm_L=(55, 0, 0), forearm_R=(80, 0, 0),
              thigh_L=(8, 6, 0), thigh_R=(-10, 6, 0), shin_L=(-14, 0, 0), shin_R=(-18, 0, 0), foot_L=(4, 0, 0),
              foot_R=(8, 0, 0), hips=(0, 0, 8), **spine_split(4, 0, 0))
_WIND = pose(hips=(0, 0, -14), thigh_L=(14, 6, 0), thigh_R=(-24, 8, 0), shin_L=(-34, 0, 0), shin_R=(-28, 0, 0),
             foot_L=(10, 0, 0), foot_R=(16, 0, 0),
             arm_R=(125, 52, 0), forearm_R=(105, 0, 0), hand_R=(-35, 0, 0), blade=(-0.25, 0.92, -0.25), arm_L=(24, 36, 0), forearm_L=(60, 0, 0),
             head=(0, 0, 10), hip_t=(0.0, -0.03, -0.03), **spine_split(-4, 4, -42))
_STRIKE = pose(hips=(4, 0, 18), thigh_L=(-14, 6, 0), thigh_R=(30, 5, 0), shin_L=(-16, 0, 0), shin_R=(-52, 0, 0),
               foot_L=(4, 0, 0), foot_R=(18, 0, 0),
               arm_R=(78, 12, 28), forearm_R=(16, 0, 0), hand_R=(45, 0, 0), blade=(0.85, -0.05, -0.5), arm_L=(-34, 34, 0), forearm_L=(44, 0, 0),
               head=(4, 0, -12), hip_t=(0.0, 0.08, -0.07), **spine_split(14, -2, 46))
_FOLLOW = pose(hips=(3, 0, 12), thigh_L=(-10, 6, 0), thigh_R=(24, 5, 0), shin_L=(-14, 0, 0), shin_R=(-40, 0, 0),
               arm_R=(48, -2, 38), forearm_R=(28, 0, 0), hand_R=(35, 0, 0), blade=(0.35, -0.3, -0.9), arm_L=(-24, 30, 0), forearm_L=(40, 0, 0),
               hip_t=(0.0, 0.06, -0.05), **spine_split(10, -1, 36))
ATTACK_SLASH = keyed([(0.0, _READY), (0.28, _WIND), (0.42, _WIND), (0.52, _STRIKE), (0.62, _FOLLOW), (1.0, _READY)])
_OH_UP = pose(hips=(-6, 0, 0), thigh_L=(10, 6, 0), thigh_R=(-14, 6, 0), shin_L=(-22, 0, 0), shin_R=(-26, 0, 0),
              arm_R=(168, 14, 0), forearm_R=(70, 0, 0), hand_R=(-30, 0, 0), blade=(-0.55, 0.83, 0.0), arm_L=(160, 18, 0), forearm_L=(64, 0, 0),
              head=(-12, 0, 0), hip_t=(0, -0.02, -0.02), **spine_split(-16, 0, 0))
_OH_HIT = pose(hips=(6, 0, 0), thigh_L=(-6, 6, 0), thigh_R=(34, 5, 0), shin_L=(-14, 0, 0), shin_R=(-58, 0, 0),
               foot_R=(14, 0, 0),
               arm_R=(58, 10, 0), forearm_R=(10, 0, 0), hand_R=(75, 0, 0), blade=(0.85, -0.5, 0.0), arm_L=(54, 14, 0), forearm_L=(12, 0, 0),
               head=(10, 0, 0), hip_t=(0, 0.10, -0.1), **spine_split(34, 0, 0))
ATTACK_OVERHEAD = keyed([(0.0, _READY), (0.34, _OH_UP), (0.46, _OH_UP), (0.58, _OH_HIT), (0.76, _OH_HIT | {"hip_t": (0, 0.10, -0.1)}),
                         (1.0, _READY)])


def cast(t):
    ks = keyed([(0.0, pose()),
                (0.30, pose(arm_L=(70, 26, 0), arm_R=(70, 26, 0), forearm_L=(70, 0, 0), forearm_R=(70, 0, 0),
                            head=(-8, 0, 0), thigh_L=(4, 6, 0), thigh_R=(-6, 6, 0), shin_L=(-8, 0, 0),
                            shin_R=(-10, 0, 0), **spine_split(-8, 0, 0))),
                (0.60, pose(arm_L=(96, 14, 0), arm_R=(96, 14, 0), forearm_L=(30, 0, 0), forearm_R=(30, 0, 0),
                            head=(-4, 0, 0), thigh_L=(4, 6, 0), thigh_R=(-6, 6, 0), shin_L=(-8, 0, 0),
                            shin_R=(-10, 0, 0), hip_t=(0, 0.02, -0.01), **spine_split(8, 0, 0))),
                (0.85, pose(arm_L=(88, 12, 0), arm_R=(88, 12, 0), forearm_L=(24, 0, 0), forearm_R=(24, 0, 0),
                            thigh_L=(4, 6, 0), thigh_R=(-6, 6, 0), shin_L=(-8, 0, 0), shin_R=(-10, 0, 0),
                            **spine_split(4, 0, 0))),
                (1.0, pose())])
    p = ks(t)
    sh = 1.8 * S(t * TAU * 9) * smooth(1 - abs(t - 0.5) * 3) if 0.3 < t < 0.8 else 0.0
    p = dict(p)
    p["hand_L"] = (sh * 3, 0, 0)
    p["hand_R"] = (-sh * 3, 0, 0)
    return p


def block(t):
    a = t * TAU
    sp = spine_split(-5 + 1 * S(a), 0, -10)
    return pose(hips=(0, 0, 6), thigh_L=(10, 6, 0), thigh_R=(-14, 6, 0), shin_L=(-26, 0, 0), shin_R=(-22, 0, 0),
                foot_L=(6, 0, 0), foot_R=(8, 0, 0),
                arm_L=(78, 20, 14), forearm_L=(100, 0, 0), arm_R=(54, 22, 0), forearm_R=(96, 0, 0),
                head=(2, 0, 4), hip_t=(0, -0.02, -0.05 + 0.004 * S(a)), **sp)


HIT = keyed([(0.0, pose()),
             (0.18, pose(hips=(-6, 0, 6), arm_L=(-12, 28, 0), arm_R=(-18, 30, 0), forearm_L=(26, 0, 0),
                         forearm_R=(30, 0, 0), thigh_L=(8, 4, 0), thigh_R=(-6, 4, 0), shin_L=(-12, 0, 0),
                         shin_R=(-10, 0, 0), head=(-18, 0, 10), neck=(-6, 0, 0), hip_t=(0, -0.05, -0.02),
                         **spine_split(-20, 2, 8))),
             (0.45, pose(hips=(-2, 0, 2), arm_L=(-4, 16, 0), arm_R=(-6, 16, 0), forearm_L=(22, 0, 0),
                         forearm_R=(22, 0, 0), head=(-6, 0, 2), hip_t=(0, -0.02, -0.01), **spine_split(-6, 0, 2))),
             (1.0, pose())])
_DEATH_STAG = pose(hips=(-8, 0, 10), thigh_L=(16, 4, 0), thigh_R=(-10, 4, 0), shin_L=(-34, 0, 0), shin_R=(-40, 0, 0),
                   arm_L=(-26, 50, 0), arm_R=(-34, 54, 0), forearm_L=(34, 0, 0), forearm_R=(30, 0, 0),
                   head=(-22, 0, 14), hip_t=(0, -0.10, -0.12), **spine_split(-22, 4, 14))
_DEATH_FALL = pose(hips=(-52, 0, 8), thigh_L=(30, 6, 0), thigh_R=(8, 10, 0), shin_L=(-70, 0, 0), shin_R=(-30, 0, 0),
                   arm_L=(-46, 66, 0), arm_R=(-58, 76, 0), forearm_L=(36, 0, 0), forearm_R=(22, 0, 0),
                   head=(-20, 0, 18), hip_t=(0, -0.32, -0.34), **spine_split(-14, 0, 0))
_DEATH_END = pose(hips=(-90, 0, 14), thigh_L=(22, 8, 0), thigh_R=(-4, 14, 0), shin_L=(-34, 0, 0), shin_R=(-16, 0, 0),
                  arm_L=(-20, 78, 0), arm_R=(-34, 84, 0), forearm_L=(24, 0, 0), forearm_R=(12, 0, 0),
                  head=(-10, 0, 22), hip_t=(0, -0.44, -0.455), **spine_split(-4, 0, 0))
DEATH = keyed([(0.0, pose()), (0.22, _DEATH_STAG), (0.55, _DEATH_FALL), (0.8, _DEATH_END),
               (1.0, _DEATH_END | {"hips": (-90, 0, 14)})])

CLIPS = {"idle_loop": (3.0, idle, True), "walk_loop": (1.0, walk, True), "run_loop": (0.68, run, True),
         "jump": (1.0, JUMP, False), "fall_loop": (0.8, fall, True), "land": (0.5, LAND, False),
         "attack_slash": (0.95, ATTACK_SLASH, False), "attack_overhead": (1.1, ATTACK_OVERHEAD, False),
         "cast": (1.5, cast, False), "block_loop": (1.0, block, True), "hit": (0.5, HIT, False),
         "death": (1.7, DEATH, False)}


# ---------------------------------------------------------------- apply a pose to the armature
for pb in arm.pose.bones:
    pb.rotation_mode = "QUATERNION"


def set_pose(p):
    for key, (pitch, roll, yaw) in p.items():
        if key == "hip_t" or key not in NAME:
            continue
        name = NAME[key]
        Rc = bone_rotation(key, pitch, roll, yaw)
        M = REST[name]
        arm.pose.bones[name].rotation_quaternion = (M.inverted() @ Rc @ M).to_quaternion()
    r_, f_, u_ = p["hip_t"]
    T = (right * r_ + fwd * f_ + up * u_) * HEIGHT
    M = REST[NAME["hips"]]
    arm.pose.bones[NAME["hips"]].location = M.inverted() @ T


def reset_pose():
    for pb in arm.pose.bones:
        pb.rotation_quaternion = (1, 0, 0, 0)
        pb.location = (0, 0, 0)


TWO_READY = {"arm_R": (46, 14, 0), "forearm_R": (82, 0, 0), "hand_R": (0, 0, 0)}
ONE_READY = {"arm_R": (40, 12, 0), "forearm_R": (80, 0, 0)}
PALM = 0.075
if FINGER_BLADE:   # the presets are for a 1 m goblin: a character in other units scales them by its height
    PALM *= HEIGHT
    HAND_GAP *= HEIGHT

if TWOHAND:
    _L1 = (B("forearm_L").head_local - B("arm_L").head_local).length
    _L2 = (B("hand_L").head_local - B("forearm_L").head_local).length
    _dir_up = (B("forearm_L").head_local - B("arm_L").head_local).normalized()
    _dir_fa = (B("hand_L").head_local - B("forearm_L").head_local).normalized()
    _palm_local = (REST[NAME["hand_R"]].inverted() @ (B("hand_R").head_local - B("forearm_R").head_local).normalized()) * PALM
    _blade_local = Vector((0, math.cos(D(TILT)), math.sin(D(TILT))))
    _left_palm_local = _palm_local - _blade_local * HAND_GAP
    _POLE = -up * 0.7 - right * 0.5 - fwd * 0.2        # the left elbow points down, out and back


if AIM:
    _blade_local = Vector((0, math.cos(D(TILT)), math.sin(D(TILT))))
if AIM and FINGER_BLADE:
    _ix = next((b for b in bones if b.name.endswith("RightHandIndex1")), None)
    _pk = next((b for b in bones if b.name.endswith("RightHandPinky1")), None)
    if _ix and _pk:
        _blade_local = (REST[NAME["hand_R"]].inverted() @ (_ix.head_local - _pk.head_local)).normalized()
        HAND_GAP = 1.3 * (_ix.head_local - _pk.head_local).length   # the left hand right under the right one
        if TWOHAND:
            _left_palm_local = _palm_local - _blade_local * HAND_GAP
    _lix = next((b for b in bones if b.name.endswith("LeftHandIndex1")), None)
    _lpk = next((b for b in bones if b.name.endswith("LeftHandPinky1")), None)
    _left_across_local = (REST[NAME["hand_L"]].inverted() @ (_lix.head_local - _lpk.head_local)).normalized() \
        if TWOHAND and _lix and _lpk and "hand_L" in NAME else None
    def _palm_normal_local(side):   # the palm's outward normal (on the thumb's side), in the hand bone's rest frame
        S_ = "Left" if side == "L" else "Right"
        g_ = lambda suf: next((b for b in bones if b.name.endswith(S_ + "Hand" + suf)), None)
        h_, i_, p_, m_, t_ = g_(""), g_("Index1"), g_("Pinky1"), g_("Middle1"), g_("Thumb1") or g_("Thumb2")
        n_ = (m_.head_local - h_.head_local).cross(i_.head_local - p_.head_local).normalized()
        if t_ is not None and n_.dot(t_.head_local - h_.head_local) < 0:
            n_ = -n_
        return REST[NAME["hand_" + side]].inverted() @ n_
    if _left_across_local is not None:
        _right_palm_n_local = _palm_normal_local("R")
        _left_palm_n_local = _palm_normal_local("L")
    if _left_across_local is not None:   # wrist -> the middle of the left palm (its knuckles), in the hand's rest frame
        _left_palm_off_local = REST[NAME["hand_L"]].inverted() @ ((_lix.head_local + _lpk.head_local) * .5 - B("hand_L").head_local)


def aim_blade(vec):
    """turn the right hand (a swing, no twist) so the sword axis points along vec = (forward, up, right)"""
    bpy.context.view_layer.update()
    pb = arm.pose.bones
    hn = NAME["hand_R"]
    cur = (pb[hn].matrix.to_3x3() @ _blade_local).normalized()
    want = (fwd * vec[0] + up * vec[1] + right * vec[2]).normalized()
    tot_new = cur.rotation_difference(want).to_matrix() @ (pb[hn].matrix.to_3x3() @ REST[hn].inverted())
    par = pb[hn].parent
    rp = par.matrix.to_3x3() @ par.bone.matrix_local.to_3x3().inverted()
    m = REST[hn]
    pb[hn].rotation_quaternion = (m.inverted() @ (rp.inverted() @ tot_new) @ m).to_quaternion()


def solve_left_arm(palm_off=None):
    """two-bone IK in code: put the left palm on the handle, below the right hand (both hands on the sword).
    palm_off: the wrist-to-palm vector of the left hand as it will be turned (else the palm is taken along the reach)"""
    bpy.context.view_layer.update()
    pb = arm.pose.bones
    palm = pb[NAME["hand_R"]].matrix @ _left_palm_local
    shoulder = pb[NAME["arm_L"]].head.copy()
    reach = (palm - shoulder).normalized()
    target = palm - (palm_off if palm_off is not None else reach * PALM)   # the wrist
    d = target - shoulder
    dist = min(max(d.length, abs(_L1 - _L2) + 1e-4), _L1 + _L2 - 1e-4)
    dirv = d.normalized()
    a_ = (_L1 * _L1 - _L2 * _L2 + dist * dist) / (2 * dist)
    h_ = math.sqrt(max(_L1 * _L1 - a_ * a_, 0.0))
    perp = _POLE - dirv * _POLE.dot(dirv)
    perp = perp.normalized() if perp.length > 1e-6 else Vector((0, 0, -1))
    elbow = shoulder + dirv * a_ + perp * h_
    wrist = elbow + (target - elbow).normalized() * _L2
    tot_up = _dir_up.rotation_difference((elbow - shoulder).normalized()).to_matrix()
    tot_fa = _dir_fa.rotation_difference((wrist - elbow).normalized()).to_matrix()
    par = pb[NAME["arm_L"]].parent
    rp = (par.matrix.to_3x3() @ par.bone.matrix_local.to_3x3().inverted()) if par else Matrix.Identity(3)
    m_up, m_fa = REST[NAME["arm_L"]], REST[NAME["forearm_L"]]
    pb[NAME["arm_L"]].rotation_quaternion = (m_up.inverted() @ (rp.inverted() @ tot_up) @ m_up).to_quaternion()
    pb[NAME["forearm_L"]].rotation_quaternion = (m_fa.inverted() @ (tot_up.inverted() @ tot_fa) @ m_fa).to_quaternion()


def centre_right_hand(share=.75, pull=0.0, push=0.0):
    """both hands on one handle: the right wrist pulled towards the body's middle (the clip keeps its height and its
    forward reach), so the left arm can reach the handle; a two-bone solve of the right arm, its hand turned as before"""
    bpy.context.view_layer.update()
    pb = arm.pose.bones
    hand_m = pb[NAME["hand_R"]].matrix.to_3x3() @ REST[NAME["hand_R"]].inverted()   # the hand's world turn, kept
    sh = pb[NAME["arm_R"]].head.copy()
    w = pb[NAME["hand_R"]].head.copy()
    mid = (pb[NAME["arm_L"]].head + sh) * .5
    side_off = (w - mid).dot(right)
    target = w - right * (side_off * share)
    # and never farther from the left shoulder than the left arm reaches (a swing's follow-through would leave the
    # left hand behind, the arm stretched straight through the body)
    shl = pb[NAME["arm_L"]].head
    reach_l = .9 * ((B("forearm_L").head_local - B("arm_L").head_local).length
                    + (B("hand_L").head_local - B("forearm_L").head_local).length) - 1.3 * PALM
    reach_l -= pull   # pull: how much more the left palm's place on the handle was out of reach last time
    if (target - shl).length > reach_l:
        target = shl + (target - shl).normalized() * reach_l
    if (target - shl).length < .5 * reach_l:   # nor so close that the left elbow folds shut (hands over the shoulder)
        dv = (target - shl).normalized() + fwd * .8
        target = shl + dv.normalized() * (.5 * reach_l)
    target = target + fwd * push   # push: the left palm's place came too close to the left shoulder last time
    L1 = (B("forearm_R").head_local - B("arm_R").head_local).length
    L2 = (B("hand_R").head_local - B("forearm_R").head_local).length
    d = target - sh
    dist = min(max(d.length, abs(L1 - L2) + 1e-4), L1 + L2 - 1e-4)
    dirv = d.normalized()
    a_ = (L1 * L1 - L2 * L2 + dist * dist) / (2 * dist)
    h_ = math.sqrt(max(L1 * L1 - a_ * a_, 0.0))
    pole = -up * .7 + right * .5 - fwd * .2          # the right elbow down, out and back
    perp = pole - dirv * pole.dot(dirv)
    perp = perp.normalized() if perp.length > 1e-6 else Vector((0, 0, -1))
    elbow = sh + dirv * a_ + perp * h_
    wrist = elbow + (sh + dirv * dist - elbow).normalized() * L2
    du = (B("forearm_R").head_local - B("arm_R").head_local).normalized()
    df = (B("hand_R").head_local - B("forearm_R").head_local).normalized()
    tot_up = du.rotation_difference((elbow - sh).normalized()).to_matrix()
    tot_fa = df.rotation_difference((wrist - elbow).normalized()).to_matrix()
    par = pb[NAME["arm_R"]].parent
    rp = (par.matrix.to_3x3() @ par.bone.matrix_local.to_3x3().inverted()) if par else Matrix.Identity(3)
    m_up, m_fa, m_h = REST[NAME["arm_R"]], REST[NAME["forearm_R"]], REST[NAME["hand_R"]]
    pb[NAME["arm_R"]].rotation_quaternion = (m_up.inverted() @ (rp.inverted() @ tot_up) @ m_up).to_quaternion()
    pb[NAME["forearm_R"]].rotation_quaternion = (m_fa.inverted() @ (tot_up.inverted() @ tot_fa) @ m_fa).to_quaternion()
    pb[NAME["hand_R"]].rotation_quaternion = (m_h.inverted() @ (tot_fa.inverted() @ hand_m) @ m_h).to_quaternion()


def set_hand_world(hn, m_des):
    """give the hand bone hn this world (armature) 3x3 orientation, whatever its forearm does"""
    bpy.context.view_layer.update()
    pb = arm.pose.bones
    par = pb[hn].parent
    rp = par.matrix.to_3x3() @ par.bone.matrix_local.to_3x3().inverted()
    m = REST[hn]
    pb[hn].rotation_quaternion = (m.inverted() @ (rp.inverted() @ (m_des @ m.inverted())) @ m).to_quaternion()


def grip_left_hand():
    """the left hand closes on the handle like the right one: its knuckle line (little finger to index) along the
    blade, turned by a swing (blade=fingers only; otherwise the left hand keeps its pose and looks twisted)"""
    bpy.context.view_layer.update()
    pb = arm.pose.bones
    hn = NAME["hand_L"]
    cur = (pb[hn].matrix.to_3x3() @ _left_across_local).normalized()
    want = (pb[NAME["hand_R"]].matrix.to_3x3() @ _blade_local).normalized()
    tot_new = cur.rotation_difference(want).to_matrix() @ (pb[hn].matrix.to_3x3() @ REST[hn].inverted())
    par = pb[hn].parent
    rp = par.matrix.to_3x3() @ par.bone.matrix_local.to_3x3().inverted()
    m = REST[hn]
    pb[hn].rotation_quaternion = (m.inverted() @ (rp.inverted() @ tot_new) @ m).to_quaternion()


def _fist_rot(side, deg=30):
    """rest-space local rotations that close the four fingers of one hand around a handle (deg per joint, three joints
    make a fist): every joint turns about
    the knuckle line towards the palm (the palm is on the thumb's side), whatever the bones' rolls"""
    S = "Left" if side == "L" else "Right"
    get = lambda suf: next((b for b in bones if b.name.endswith(S + "Hand" + suf)), None)
    hand, ix, pk, md, th = get(""), get("Index1"), get("Pinky1"), get("Middle1"), get("Thumb1") or get("Thumb2")
    if not (hand and ix and pk and md):
        return {}
    across = (ix.head_local - pk.head_local).normalized()
    along = (md.head_local - hand.head_local).normalized()
    palm = along.cross(across).normalized()
    if th is not None and palm.dot(th.head_local - hand.head_local) < 0:
        palm = -palm
    tip = md.tail_local - md.head_local
    R = Matrix.Rotation(D(deg), 3, across)
    if (R @ tip - tip).dot(palm) < 0:   # the way that moves the fingertip towards the palm
        R = Matrix.Rotation(D(-deg), 3, across)
    out = {}
    for f in ("Index", "Middle", "Ring", "Pinky"):
        for k in (1, 2, 3):
            b = get(f + str(k))
            if b is not None:
                M = b.matrix_local.to_3x3()
                out[b.name] = (M.inverted() @ R @ M).to_quaternion()
    return out


FIST = {}
if FINGER_BLADE and AIM:
    FIST.update(_fist_rot("R"))
    if TWOHAND:
        FIST.update(_fist_rot("L"))


GUARD = {"arm_L": (34, 24, 0), "forearm_L": (86, 0, 0), "hand_L": (0, 0, 0)}


def key_clip(name, seconds, fn, loop):
    n = max(2, int(round(seconds * FPS)))
    act = bpy.data.actions.new(name)
    ad = arm.animation_data_create()
    ad.action = act
    for i in range(n):               # loops: n poses, the next cycle starts again at pose 0; one-shots end on the last pose
        reset_pose()
        pose_i = fn(i / n if loop else i / (n - 1))
        if SHIELD and name != "death":
            pose_i = dict(pose_i)
            for k_, v_ in GUARD.items():
                if k_ in pose_i:
                    pose_i[k_] = v_
        if TWOHAND and name != "death":
            if name in ("idle_loop", "walk_loop", "run_loop", "hit", "block_loop"):
                pose_i = dict(pose_i)
                for k_, v_ in TWO_READY.items():
                    pose_i[k_] = v_
        if AIM and not TWOHAND and name != "death" and name in ("idle_loop", "walk_loop", "run_loop", "hit", "block_loop"):
            pose_i = dict(pose_i)
            for k_, v_ in ONE_READY.items():
                pose_i[k_] = v_
        set_pose(pose_i)
        if TWOHAND and FINGER_BLADE and name != "death":
            # the left palm's place on the handle (below the right hand, along the turned blade) must be in the left
            # arm's reach: the right hand comes in closer until it is
            pull = push = 0.0
            for _ in range(5):
                set_pose(pose_i)
                centre_right_hand(pull=pull, push=push)
                aim_blade(pose_i["blade"])
                bpy.context.view_layer.update()
                pb_ = arm.pose.bones
                lp = pb_[NAME["hand_R"]].matrix @ _left_palm_local
                dl = (lp - pb_[NAME["arm_L"]].head).length
                over, under = dl - .92 * (_L1 + _L2 + PALM), .55 * (_L1 + _L2) - dl
                if over <= 0 and under <= 0:
                    break
                if over > 0:
                    pull += over * 1.1
                else:
                    push += under * 1.1
        if AIM and name != "death":
            aim_blade(pose_i["blade"])
        if TWOHAND and name != "death":
            solve_left_arm()
            if FINGER_BLADE and _left_across_local is not None:
                # the hand's turn along the handle, in the world, is fixed first; the arm is then solved for the palm of
                # the hand so turned, and the hand finally given that world turn (a turn set before the arm moves would
                # move with the forearm, and the palm would slide off the handle)
                bpy.context.view_layer.update()
                # the left hand's turn follows the right hand's: its knuckles along the blade too, its palm the other
                # way round (as the two hands close on one handle), so it never flips about the handle between frames
                mr = arm.pose.bones[NAME["hand_R"]].matrix.to_3x3()
                bw = (mr @ _blade_local).normalized()
                pw = -(mr @ _right_palm_n_local)
                pw = (pw - bw * pw.dot(bw)).normalized()
                al = _left_across_local.normalized()
                pl = _left_palm_n_local - al * _left_palm_n_local.dot(al)
                pl.normalize()
                Wd = Matrix((bw, pw, bw.cross(pw))).transposed()
                Lc = Matrix((al, pl, al.cross(pl))).transposed()
                m_des = Wd @ Lc.inverted()
                solve_left_arm(m_des @ _left_palm_off_local)
                set_hand_world(NAME["hand_L"], m_des)
        if name != "death":   # the hands holding the sword close on its handle (blade=fingers only)
            for bn_, q_ in FIST.items():
                arm.pose.bones[bn_].rotation_quaternion = q_
        f = 1 + i
        for bn in {NAME[k] for k in NAME} | set(FIST):
            pb = arm.pose.bones[bn]
            pb.keyframe_insert("rotation_quaternion", frame=f)
            if bn == NAME["hips"]:
                pb.keyframe_insert("location", frame=f)
    act.use_frame_range = True
    act.frame_start, act.frame_end = 1, n
    return act, n


if PREVIEW:
    scn = bpy.context.scene
    scn.render.engine = "BLENDER_WORKBENCH"
    scn.display.shading.light = "STUDIO"
    scn.display.shading.color_type = "TEXTURE"
    scn.render.resolution_x, scn.render.resolution_y = 360, 460
    cam = bpy.data.objects.new("pcam", bpy.data.cameras.new("pcam"))
    scn.collection.objects.link(cam)
    scn.camera = cam
    cam.data.type = "ORTHO"
    wm = arm.matrix_world
    w3 = wm.to_3x3()
    sc_ = wm.to_scale()[0]
    cam.data.ortho_scale = HEIGHT * sc_ * 1.6
    c0 = wm @ (hips_h + up * HEIGHT * 0.12)
    view = (w3 @ right).normalized()          # look from the character's left side towards its right
    z_ = -view                                # camera looks along -Z
    up_w = (w3 @ up).normalized()
    y_ = (up_w - z_ * up_w.dot(z_)).normalized()
    x_ = y_.cross(z_)
    cam.matrix_world = Matrix(((x_.x, y_.x, z_.x, (c0 - view * 6).x), (x_.y, y_.y, z_.y, (c0 - view * 6).y),
                               (x_.z, y_.z, z_.z, (c0 - view * 6).z), (0, 0, 0, 1)))
    Path(PREVIEW).mkdir(parents=True, exist_ok=True)

done = []
for name in WANT:
    if name not in CLIPS:
        print("ANIM_SKIP", name)
        continue
    sec, fn, loop = CLIPS[name]
    act, n = key_clip(name, sec, fn, loop)
    if PREVIEW:
        for j, frac in enumerate((0.0, 0.2, 0.4, 0.6, 0.8, 1.0)):
            bpy.context.scene.frame_set(1 + int(round(frac * (n - 1))))
            bpy.context.scene.render.filepath = str(Path(PREVIEW) / f"{name}_{j}.png")
            bpy.ops.render.render(write_still=True)
    ad = arm.animation_data
    tr = ad.nla_tracks.new()
    tr.name = name
    st = tr.strips.new(name, 1, act)
    st.frame_end = n
    ad.action = None
    done.append(dict(name=name, seconds=n / FPS, frames=n, loop=loop))
    print("ANIM_CLIP", name, n, "frames")
reset_pose()

amp_walk, T_walk = 26, CLIPS["walk_loop"][0]
step = 2 * LEG * math.sin(D(amp_walk)) * 0.9
info = dict(clips=done, height=HEIGHT, leg=LEG, walk_speed=round(2 * step / T_walk, 2),
            run_speed=round(2 * 2 * LEG * math.sin(D(44)) * 0.9 / CLIPS["run_loop"][0], 2), fps=FPS)
dst.parent.mkdir(parents=True, exist_ok=True)
Path(str(dst) + ".json").write_text(json.dumps(info, indent=1), encoding="utf-8")
bpy.ops.object.select_all(action="DESELECT")
for o in bpy.context.scene.objects:
    if o.type in ("ARMATURE", "MESH"):
        o.select_set(True)
try:
    bpy.ops.export_scene.gltf(filepath=str(dst), export_format="GLB", use_selection=True,
                              export_animation_mode="NLA_TRACKS", export_force_sampling=True)
except TypeError:
    bpy.ops.export_scene.gltf(filepath=str(dst), export_format="GLB", use_selection=True,
                              export_animation_mode="NLA_TRACKS")
print("ANIM_GLB", dst, json.dumps(info))
