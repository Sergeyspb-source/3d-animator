"""Runs INSIDE Blender (imported by blender_creature_retarget.py): a creature's procedural clips, made from its skeleton
alone - a quadruped's gaits with the paws planted by IK, a bird's step, wing beat and glide, a serpent's wave along the
body. The skeleton is read by its bones' names (creature_templates.py / blender_creature_auto.py: hips, spine_01..,
chest, neck_01.., head, jaw, tail_01.., leg_FL_1.. / leg_BL_1.., wing_L_1..; a serpent's spine_01 by the head back to
the tail's end), so a template's skeleton and UniRig's named one both take them.

Every clip is in place (the game moves the creature): `speed` in the clip list is how fast it must go for the paws not
to slide (model units a second). The gaits are sized by the legs (dynamic similarity: Froude number v^2 / (g h) per
gait, stride length 2.3 Fr^0.3 h - Alexander 1984), so a boar and a wolf of any size take the same steps for their
legs. Loops end on their first pose (seamless in Godot) and are named with Godot's `_loop` suffix (imported looping).

    make_clips(arm, meshes, names, fps=30, close_deg=None) -> [{name, frames, seconds, loop, speed}]

A quadruped's feet: lateral sequence walk (LH, LF, RH, RF a quarter apart), trot (diagonal pairs), transverse gallop
(hind pair, then the front pair); in stance the paw's ball stays on its spot sliding back at the body's speed, in swing
it lifts on an arc with the paw flipped back and the toe curled; the wrist / hock from the ball, the knee / elbow by
two-bone IK bending as at rest. A bird: the same two-legged, the head held then thrust, the wings beaten about the
body's long axis (folded at the wrist on the upstroke) or held out gliding, the legs tucked. A serpent: the body laid
along a serpenoid curve (heading = a sin(2 pi (s / wavelength - t / T))) travelling back along it.
"""
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from creature_templates import PROC_CLIPS as CLIPS, PROC_LOOPS as LOOPS, proc_name as clip_name  # noqa: E402
import creature_templates  # noqa: E402

G = 9.81


def body_kind(arm) -> str | None:
    return creature_templates.body_kind(b.name for b in arm.data.bones)


def smooth(x):
    x = min(1.0, max(0.0, x))
    return x * x * (3 - 2 * x)


def track(keys, t):
    """keys [(time, value)]: the value at t, eased between keys (floats or Vectors)"""
    if t <= keys[0][0]:
        return keys[0][1]
    for (t0, a), (t1, b) in zip(keys, keys[1:]):
        if t <= t1:
            u = smooth((t - t0) / max(t1 - t0, 1e-6))
            return a + (b - a) * u
    return keys[-1][1]


def rot_between(a: Vector, b: Vector) -> Quaternion:
    return a.normalized().rotation_difference(b.normalized())


class Rig:
    """the armature's rest, its chains and measures, and a pose solved from body turns, leg targets, wing aims"""

    def __init__(self, arm, meshes):
        self.arm = arm
        bones = arm.data.bones
        self.bones = bones
        self.REST = {b.name: b.matrix_local.copy() for b in bones}
        self.H = {b.name: b.head_local.copy() for b in bones}
        self.T = {b.name: b.tail_local.copy() for b in bones}
        self.PAR = {b.name: b.parent.name if b.parent else None for b in bones}
        self.ORDER = sorted(self.REST, key=lambda n: len(bones[n].parent_recursive))
        names = set(self.REST)
        self.kind = body_kind(arm)
        # the axes (armature space): up +Z, forward from the hips (or the tail's end) to the head, left across
        inv = arm.matrix_world.inverted().to_3x3()
        self.UP = (inv @ Vector((0, 0, 1))).normalized()
        head = "head" if "head" in names else None
        if self.kind == "serpent":
            sp = sorted((n for n in names if n.startswith("spine_")), key=lambda n: int(n.split("_")[1]))
            back = self.T[sp[-1]]
            front = self.H[head] if head else self.H[sp[0]]
            self.spine = sp
        else:
            back = self.H["hips"] if "hips" in names else Vector()
            front = self.H[head] if head else back + Vector((0, -1, 0))
            self.spine = [n for n in ("hips", "spine_01", "spine_02", "spine_03", "chest") if n in names]
        f = front - back
        f -= self.UP * f.dot(self.UP)
        self.FWD = f.normalized() if f.length > 1e-6 else Vector((0, -1, 0))
        self.LAT = self.UP.cross(self.FWD).normalized()   # (the creature's left)
        self.neck = sorted((n for n in names if n.startswith("neck_")), key=lambda n: int(n.split("_")[1]))
        self.head = head
        self.jaw = "jaw" if "jaw" in names else None
        self.tail = sorted((n for n in names if n.startswith("tail_") and n[5:].isdigit()), key=lambda n: int(n[5:]))
        self.legs = {}
        for k in ("FL", "FR", "BL", "BR"):
            ch = sorted((n for n in names if n.startswith(f"leg_{k}_") and n.split("_")[-1].isdigit()),
                        key=lambda n: int(n.split("_")[-1]))
            if len(ch) < 3:
                continue
            total = sum((self.T[x] - self.H[x]).length for x in ch)
            root = ch[0] if len(ch) >= 5 or (len(ch) == 4 and (self.T[ch[0]] - self.H[ch[0]]).length < 0.2 * total) else None
            rest = ch[1:] if root else ch
            self.legs[k] = {"root": root, "upper": rest[0], "lower": rest[1], "paw": rest[2],
                            "toe": rest[3] if len(rest) > 3 else None}
        # a paw with no toe bone (a foot on the ground): its length along its own bone by the skin it leads (the GLB's
        # leaf bone length is a guess), so the heel can rise about the toes' tip when the leg would not reach
        self.foot = {}
        to_arm = arm.matrix_world.inverted()
        for k, c in self.legs.items():
            if c["toe"]:
                continue
            h0, d0 = self.H[c["paw"]], (self.T[c["paw"]] - self.H[c["paw"]]).normalized()
            proj = []
            for o in meshes:
                g = o.vertex_groups.get(c["paw"])
                if g is None:
                    continue
                mw = to_arm @ o.matrix_world
                for v in o.data.vertices:
                    if v.groups and max(v.groups, key=lambda x: x.weight).group == g.index:
                        proj.append((mw @ v.co - h0).dot(d0))
            proj.sort()
            ln = proj[int(0.95 * (len(proj) - 1))] if len(proj) > 10 else (self.T[c["paw"]] - h0).length
            self.foot[k] = d0 * max(ln, 1e-4)
        self.wings = {}
        for s in "LR":
            ch = sorted((n for n in names if n.startswith(f"wing_{s}_") and n.split("_")[-1].isdigit()), key=lambda n: int(n.split("_")[-1]))
            if ch:
                self.wings[s] = ch
        # measures: the ground (the skin's lowest point; a GLB keeps no leaf bone's length: a toe's tail is a guess),
        # the legs' heights
        if meshes:
            to_arm = arm.matrix_world.inverted()
            self.ground = min((to_arm @ (o.matrix_world @ Vector(c))).dot(self.UP) for o in meshes for c in o.bound_box)
        else:
            self.ground = min(p.dot(self.UP) for p in self.H.values())
        hts = [self.H[c["upper"]].dot(self.UP) - self.ground for c in self.legs.values()]
        self.leg_h = max(sum(hts) / len(hts), 1e-3) if hts else None
        span = [self.H[n] for n in names] + [self.T[n] for n in names]
        self.size = (Vector([max(p[i] for p in span) for i in range(3)]) - Vector([min(p[i] for p in span) for i in range(3)])).length
        self.length = max(p.dot(self.FWD) for p in span) - min(p.dot(self.FWD) for p in span)

    # ---- a pose: D[n] (armature space, rest -> pose) for every bone
    def fk(self, D, n, q=None, at=None):
        """bone n with its parent, turned by q (a rotation in the rest's armature axes) about its head"""
        p = self.PAR[n]
        Dp = D[p] if p else Matrix.Identity(4)
        h = self.H[n]
        if q is None:
            D[n] = Dp.copy()
        else:
            D[n] = Dp @ Matrix.Translation(h) @ q.to_matrix().to_4x4() @ Matrix.Translation(-h)
        if at is not None:   # (moved: its head at `at`, the turn kept)
            cur = D[n] @ h
            D[n] = Matrix.Translation(at - cur) @ D[n]

    def aim(self, D, n, head_at, direction, parent_rot=None):
        """bone n with its head at head_at pointing along direction (its rest direction as its parent carries it,
        turned the shortest way)"""
        p = self.PAR[n]
        Qp = parent_rot if parent_rot is not None else (D[p].to_quaternion() if p else Quaternion())
        d0 = Qp @ (self.T[n] - self.H[n])
        Q = rot_between(d0, direction) @ Qp
        D[n] = Matrix.Translation(head_at) @ Q.to_matrix().to_4x4() @ Matrix.Translation(-self.H[n])
        return Q

    def place(self, D, n, head_at, Q):
        D[n] = Matrix.Translation(head_at) @ Q.to_matrix().to_4x4() @ Matrix.Translation(-self.H[n])

    @staticmethod
    def two_bone(A, Tg, l1, l2, pole):
        d = Tg - A
        dist = d.length
        lo, hi = abs(l1 - l2) * 1.02 + 1e-6, (l1 + l2) * 0.999
        u = d.normalized() if dist > 1e-9 else Vector((0, 0, -1))
        dist_c = min(max(dist, lo), hi)
        Tr = A + u * dist_c
        p = pole - u * pole.dot(u)
        p = p.normalized() if p.length > 1e-9 else u.orthogonal().normalized()
        ca = (l1 * l1 + dist_c * dist_c - l2 * l2) / (2 * l1 * dist_c)
        a = math.acos(max(-1.0, min(1.0, ca)))
        K = A + (u * math.cos(a) + p * math.sin(a)) * l1
        return K, Tr

    def ball(self, k):
        """where leg k stands at rest: its toe's joint (the ball of a paw with a toe bone), else the paw's own head - a
        paw with no toe bone is the foot lying on the ground itself (UniRig's hind legs of four bones): it is kept flat,
        its ankle led (a GLB keeps no leaf bone's length either: its tip would be a guess)"""
        c = self.legs[k]
        return (self.H[c["toe"]] if c["toe"] else self.H[c["paw"]]).copy()

    def heel_rise(self, k, behind):
        """how high a foot with no toe bone lifts its ankle when it is `behind` (0 under the hip .. 1 the stride's back
        end) - the heel rising as the leg goes back (on a crouching beast the hock's skin went under the floor)"""
        if k not in self.foot:
            return 0.0
        return 0.3 * self.foot[k].length * min(1.0, max(0.0, behind)) ** 1.5

    def foot_len(self, k):
        """the length a paw curls by: its toe bone's parent part, or a whole foot (no toe bone)"""
        c = self.legs[k]
        if c["toe"]:
            return 0.4 * (self.H[c["toe"]] - self.H[c["paw"]]).length
        return 0.8 * self.foot[k].length

    def leg(self, D, k, ball, tilt=0.0, curl=0.0, root_q=None):
        """leg k with its paw's ball at `ball` (armature space), the paw tilted back by `tilt` radians about the left
        axis (a paw flipped in the swing), the toe curled by `curl`; the root bone (scapula / pelvis) turned by root_q.
        A paw with no toe bone: `ball` is its ankle, the foot kept flat, turned down by `tilt` in the swing."""
        c = self.legs[k]
        if c["root"]:
            self.fk(D, c["root"], root_q)
            Dp = D[c["root"]]
        else:
            p = self.PAR[c["upper"]]
            Dp = D[p] if p else Matrix.Identity(4)
        up_, lo_, paw_, toe_ = c["upper"], c["lower"], c["paw"], c["toe"]
        A0, K0, W0 = self.H[up_], self.H[lo_], self.H[paw_]
        A = Dp @ A0
        Qp = Dp.to_quaternion()
        e0 = (W0 - A0).normalized()
        pole0 = (K0 - A0) - e0 * (K0 - A0).dot(e0)
        # the knee / elbow bends along the body (its sideways part dropped: a leg splayed at rest bent its knee down
        # under the floor); a straight leg at rest: the front ones bend back, the hind ones forward
        pole0 -= self.LAT * pole0.dot(self.LAT)
        if pole0.length < 0.05 * (K0 - A0).length:
            pole0 = -self.FWD if k[0] == "F" else self.FWD
        if not toe_:   # the foot itself on the ground: the ankle to `ball`, the foot flat (turned down in the swing)
            l1, l2 = (K0 - A0).length, (W0 - K0).length
            heel = 0.0
            if (ball - A).length > 0.985 * (l1 + l2):   # out of reach: the heel up about the toes' tip
                tip = ball + self.foot[k]
                b_lo, b_hi = 0.0, math.radians(75)
                for _ in range(20):
                    mid = (b_lo + b_hi) / 2
                    if (tip + Quaternion(self.LAT, mid) @ (-self.foot[k]) - A).length > 0.985 * (l1 + l2):
                        b_lo = mid
                    else:
                        b_hi = mid
                if (tip + Quaternion(self.LAT, b_hi) @ (-self.foot[k]) - A).length < (ball - A).length:
                    heel = b_hi
                    ball = tip + Quaternion(self.LAT, heel) @ (-self.foot[k])
            K, W = self.two_bone(A, ball, l1, l2, Qp @ pole0)
            Qu = self.aim(D, up_, A, K - A, Qp)
            self.aim(D, lo_, K, W - K, Qu)
            self.place(D, paw_, W, Quaternion(self.LAT, max(tilt, curl, heel)))
            return (W - ball).length
        B0 = self.H[toe_]
        dm = B0 - W0
        Wt = ball - Quaternion(self.LAT, tilt) @ dm
        l1, l2 = (K0 - A0).length, (W0 - K0).length
        if (Wt - A).length > 0.985 * (l1 + l2):
            # out of reach with the paw's lower bone as asked: it turns about the ball toward the hip (a fetlock, a
            # pastern giving) just as far as needed
            def ang(v):
                return math.atan2(v.dot(self.UP), -v.dot(self.FWD))
            u = (A - ball).normalized()
            t_aim = tilt + ((ang(-u * dm.length) - ang(Quaternion(self.LAT, tilt) @ dm) + math.pi) % (2 * math.pi) - math.pi)
            b_lo, b_hi = 0.0, 1.0
            for _ in range(24):
                mid = (b_lo + b_hi) / 2
                Wm = ball - Quaternion(self.LAT, tilt + (t_aim - tilt) * mid) @ dm
                if (Wm - A).length > 0.985 * (l1 + l2):
                    b_lo = mid
                else:
                    b_hi = mid
            Wt = ball - Quaternion(self.LAT, tilt + (t_aim - tilt) * b_hi) @ dm
        K, W = self.two_bone(A, Wt, l1, l2, Qp @ pole0)
        Qu = self.aim(D, up_, A, K - A, Qp)
        Ql = self.aim(D, lo_, K, W - K, Qu)
        Qw = self.aim(D, paw_, W, ball - W, Ql)
        if toe_:
            B = W + Qw @ dm
            self.place(D, toe_, B, Quaternion(self.LAT, curl))
        return (W - Wt).length

    def basis(self, D):
        """the pose bones' local transforms (location, rotation) from D"""
        out = {}
        for n in self.ORDER:
            p = self.PAR[n]
            Dp = D[p] if p else Matrix.Identity(4)
            M = (Dp @ self.REST[n]).inverted() @ D[n] @ self.REST[n]
            loc, q, _ = M.decompose()
            out[n] = (loc, q)
        return out


class Clip:
    def __init__(self, rig, name, frames, loop, speed=0.0):
        self.rig, self.name, self.frames, self.loop, self.speed = rig, name, frames, loop, speed


def key_clip(rig, name, n, loop, pose, fps):
    """the clip keyed: pose(t in seconds, phase 0..1) -> D; loops get n + 1 keys (the last one the first again)"""
    arm = rig.arm
    ad = arm.animation_data or arm.animation_data_create()
    for tr in [tr for tr in ad.nla_tracks if tr.name == name]:
        ad.nla_tracks.remove(tr)
    if name in bpy.data.actions:
        bpy.data.actions.remove(bpy.data.actions[name])
    act = bpy.data.actions.new(name)
    ad.action = act
    count = n + 1
    last = {}
    for pb in arm.pose.bones:
        pb.rotation_mode = "QUATERNION"
    for i in range(count):
        ph = (i % n) / n if loop else i / max(n, 1)
        B = rig.basis(pose(i / fps, ph))
        for nm, pb in arm.pose.bones.items():
            loc, q = B.get(nm, (Vector(), Quaternion()))
            if nm in last and q.dot(last[nm]) < 0:
                q.negate()
            last[nm] = q
            pb.location, pb.rotation_quaternion, pb.scale = loc, q, (1, 1, 1)
            for path in ("location", "rotation_quaternion", "scale"):
                pb.keyframe_insert(path, frame=i + 1)
    act.use_frame_range = True
    act.frame_start, act.frame_end = 1, count
    act.use_fake_user = True
    tr = ad.nla_tracks.new()
    tr.name = name
    tr.strips.new(name, 1, act).frame_end = count
    ad.action = None
    return count


# ---------------------------------------------------------------- a quadruped
SWEEP = 32.0  # the most a leg turns from under its shoulder / hip either way in a gait, degrees
LEAN = 0.7    # how much of the leg's sweep the paw's lower bone takes (1: the leg turns as one piece)
GAITS = {   # Froude number, duty factor (the share of the cycle a paw is down), touch-down phases, paw lift (of the leg)
    "walk": dict(fr=0.18, duty=0.68, phase={"BL": 0.0, "FL": 0.25, "BR": 0.5, "FR": 0.75}, lift=0.13, flip=0.9, crouch=0.03),
    "trot": dict(fr=0.75, duty=0.45, phase={"FL": 0.0, "BR": 0.0, "FR": 0.5, "BL": 0.5}, lift=0.2, flip=1.2, crouch=0.05),
    "run": dict(fr=2.2, duty=0.3, phase={"BL": 0.0, "BR": 0.1, "FL": 0.45, "FR": 0.55}, lift=0.3, flip=1.5, crouch=0.07),
}


def quad_pose_fn(rig, gait, close, turn=0):
    """(pose(t, phase), frames, speed, turn rate in degrees a second) of a gait; turn: +1 a left turn, -1 a right one
    (on a circle of 1.6 body lengths: a planted paw goes round its centre - the inner paws step shorter - the body bent
    and leaning into the turn, the head looking into it)"""
    g = GAITS[gait]
    h = rig.leg_h
    lam = 2.3 * g["fr"] ** 0.3                         # stride length / leg height
    v = math.sqrt(g["fr"] * G * h)
    E = g["duty"] * lam * h                            # the paw's sweep under the body in a stance
    balls = {k: rig.ball(k) for k in rig.legs}
    hip_h = {k: max((rig.H[c["upper"]] - balls[k]).dot(rig.UP), 0.2 * h) for k, c in rig.legs.items()}

    crouch = g["crouch"] * h

    # each paw's sweep where its leg reaches it: along the forward line through its rest place the shoulder / hip
    # (crouched) reaches x0 +- r; the stride is the shortest leg's, centred at the rest place when it fits, else moved
    # toward the shoulder (a crouching beast's paws, far forward at rest, step under it)
    reach = {}
    for k, c in rig.legs.items():
        A0, K0, W0 = rig.H[c["upper"]], rig.H[c["lower"]], rig.H[c["paw"]]
        far = ((K0 - A0).length + (W0 - K0).length + (balls[k] - W0).length
               + (0.5 * rig.foot[k].length if k in rig.foot else 0.0)) * 0.97   # (a foot: the heel rises)
        rel = (A0 - rig.UP * crouch) - balls[k]
        x0 = rel.dot(rig.FWD)
        perp = (rel - rig.FWD * x0).length
        # (and no further than 32 degrees either way from under the shoulder / hip: a leg swept further back laid a
        # crouching beast's shin on the floor)
        reach[k] = (x0, min(math.sqrt(max(far * far - perp * perp, 0.0)), perp * math.tan(math.radians(SWEEP))))
    E = max(min(E, 0.95 * min(2 * r for _x, r in reach.values())), 0.3 * h)
    mid = {k: min(max(0.0, x0 - r + E / 2), x0 + r - E / 2) if 2 * r > E else x0 for k, (x0, r) in reach.items()}
    T = E / (g["duty"] * v)
    fps = 30
    n = max(8, int(round(T * fps)))
    T = n / fps
    v = E / (g["duty"] * T)
    F, U, L = rig.FWD, rig.UP, rig.LAT
    R = 1.6 * max(rig.length, h)
    omega = turn * v / R                               # (radians a second, + to the left)
    centre = sum(balls.values(), Vector()) / max(len(balls), 1)
    centre -= U * centre.dot(U)
    C = centre + L * (R * turn)

    def at(k, u):   # a planted paw's place at the stance's share u (a circle's arc about C; straight without a turn)
        b = balls[k] + F * mid[k]
        if not turn:
            return b + F * (E / 2 - E * u)
        a = omega * g["duty"] * T * (0.5 - u)
        return C + Quaternion(U, a) @ (b - C)

    def foot(k, ph):
        """(the paw's ball offset from its rest, lift, flip, stance share or -1)"""
        p = (ph - g["phase"][k]) % 1.0
        if p < g["duty"]:
            u = p / g["duty"]
            return at(k, u) - balls[k], 0.0, 0.0, u
        u = (p - g["duty"]) / (1 - g["duty"])
        a, b = at(k, 1.0), at(k, 0.0)
        lift = g["lift"] * h * math.sin(math.pi * min(1.0, u * 1.15)) ** 1.2
        return a + (b - a) * smooth(u) - balls[k], lift, math.sin(math.pi * u), -1.0

    def pose(t, ph):
        D = {}
        w = 2 * math.pi * ph
        off = Vector()
        q_h = Quaternion()
        spine_q, neck_q, head_q, tail_q = [], [], Quaternion(), []
        level = 0.4
        if gait == "walk":
            off = U * (-0.012 * h * (0.5 + 0.5 * math.cos(2 * w))) + L * (0.012 * h * math.sin(w))
            q_h = Quaternion(F, math.radians(2.0) * math.sin(w)) @ Quaternion(U, math.radians(2.5) * math.sin(w))
            spine_q = [Quaternion(U, math.radians(-2.0) * math.sin(w))] * 3
            neck_q = [Quaternion(L, math.radians(2.5) * math.sin(2 * w + 0.6))]
            head_q = Quaternion(L, math.radians(-2.0) * math.sin(2 * w + 0.6)) @ Quaternion(U, math.radians(3) * math.sin(w))
            tail_q = [Quaternion(U, math.radians(9) * math.sin(w - 0.7 * i)) for i in range(len(rig.tail))]
        elif gait == "trot":
            off = U * (-0.03 * h * (0.5 + 0.5 * math.cos(2 * w - 0.6)))
            q_h = Quaternion(F, math.radians(2.5) * math.sin(w))
            spine_q = [Quaternion(U, math.radians(1.5) * math.sin(w))] * 3
            neck_q = [Quaternion(L, math.radians(3) * math.sin(2 * w))]
            head_q = Quaternion(L, math.radians(-3) * math.sin(2 * w))
            tail_q = [Quaternion(L, math.radians(6)) @ Quaternion(U, math.radians(8) * math.sin(w - 0.8 * i)) for i in range(len(rig.tail))]
        else:   # the gallop: one rise and fall, the back flexed as the hind legs gather, the body pitching
            off = U * (0.045 * h * math.sin(w - 1.2)) + F * (0.015 * h * math.sin(w))
            flex = math.cos(w - 2 * math.pi * 0.85)          # +1 the back rounded (the legs gathered), -1 stretched
            n_sp = max(len(rig.spine) - 1, 1)
            q_h = Quaternion(L, math.radians(-4.0) * flex + math.radians(-3.0) * math.sin(w - 0.4))
            spine_q = [Quaternion(L, math.radians(8.0) * flex / n_sp)] * 3
            neck_q = [Quaternion(L, math.radians(-3) * math.sin(w + 0.5))]
            head_q = Quaternion(L, math.radians(3) * math.sin(w + 0.5))
            level = 0.7
            tail_q = [Quaternion(L, math.radians(8) + math.radians(10) * math.sin(w - 0.8 * i)) for i in range(len(rig.tail))]
        if turn:   # bent into the turn, leaning into it (the centripetal lean, at most 10 degrees), looking into it
            lean = min(math.atan(v * v / (G * R)), math.radians(10))
            q_h = Quaternion(F, -turn * lean) @ Quaternion(U, turn * math.radians(3)) @ q_h
            spine_q = [Quaternion(U, turn * math.radians(3)) @ q for q in (spine_q or [Quaternion()])]
            neck_q = [Quaternion(U, turn * math.radians(5)) @ q for q in (neck_q or [Quaternion()])]
            head_q = Quaternion(U, turn * math.radians(8)) @ head_q
            tail_q = [Quaternion(U, -turn * math.radians(6)) @ q for q in (tail_q or [Quaternion()] * len(rig.tail))]
        body(rig, D, off - U * crouch, q_h, spine_q, neck_q, head_q, tail_q, close, level=level)
        for k, c in rig.legs.items():
            d, lift, flip, st = foot(k, ph)
            x = d.dot(F) - mid[k]
            # the paw leans with the leg's sweep (a leg turns at its top as a whole), flipped back in the swing; the
            # ball raised as much as the lean would press the heel into the ground; the toe curled no lower than the
            # ground (a GLB keeps no toe's length: about 0.4 of the paw's lower bone)
            lean = -LEAN * math.atan2(x, hip_h[k])
            tilt = lean + g["flip"] * flip * (0.75 if k[0] == "B" else 1.0)
            if not c["toe"]:   # (a foot with no toe bone: it lies flat, no lean of a lower paw bone; behind the hip
                tilt = g["flip"] * flip * 0.6   # the heel rises - the hock's skin went under the floor there)
                lift += rig.heel_rise(k, -x / max(E / 2, 1e-6))
            lift += 0.3 * (balls[k] - rig.H[c["paw"]]).length * abs(math.sin(lean))
            curl = min(0.9 * flip, math.asin(min(1.0, lift / max(rig.foot_len(k), 1e-6))))
            if not c["toe"]:
                tilt = min(tilt, curl)
            sweep = max(-1.0, min(1.0, x / max(E / 2, 1e-6)))
            root_q = Quaternion(L, math.radians(-12 if k[0] == "F" else -4) * sweep) if c["root"] else None
            rig.leg(D, k, balls[k] + d + U * lift, tilt=tilt, curl=curl, root_q=root_q)
        rest_fk(rig, D)
        return D

    return pose, n, v, math.degrees(omega)


def quad_jump(rig, close):
    """a jump (in place, the game carries it forward in the air): a crouch, the push - the front paws off first, the
    hind ones extending - a flight on a parabola (the paws tucked, then the front ones reaching), the landing on the
    front paws, then the hind ones, the body absorbing it and standing up. Times scale with the leg (sqrt(h))."""
    h, fps = rig.leg_h, 30
    F, U, L = rig.FWD, rig.UP, rig.LAT
    k_t = math.sqrt(h / 0.45)
    tc, tf_off, tp = 0.30 * k_t, 0.38 * k_t, 0.45 * k_t          # crouched, the front paws off, the hind paws off
    rise = 0.3 * h
    t_fl = 2 * math.sqrt(2 * rise / G)                         # (the flight's time from its height)
    tl = tp + t_fl                                             # the front paws down
    th = tl + 0.08 * k_t                                       # the hind paws down
    end = tl + 0.45 * k_t
    n = int(round(end * fps))
    balls = {k: rig.ball(k) for k in rig.legs}
    y_push = 0.08 * h
    v0 = G * t_fl / 2

    def hips_y(t):
        if t <= tp:
            return track([(0.0, 0.0), (tc, -0.12 * h), (tp, y_push)], t)
        if t <= tl:
            s_ = t - tp
            return y_push + v0 * s_ - G / 2 * s_ * s_
        return track([(tl, y_push), (tl + 0.15 * k_t, -0.10 * h), (end, 0.0)], t)

    def pitch(t):   # degrees, + nose down
        return track([(0.0, 0.0), (tc, 4.0), (tp, -12.0), (tl, 10.0), (tl + 0.15 * k_t, 3.0), (end, 0.0)], t)

    def body_target(D, k, ang, shrink):
        c = rig.legs[k]
        par = rig.PAR[c["root"] or c["upper"]]
        Dp = D[par] if par in D else Matrix.Identity(4)
        A = Dp @ rig.H[c["upper"]]
        r0 = Dp.to_quaternion() @ (balls[k] - rig.H[c["upper"]])
        return A + (Quaternion(L, math.radians(ang)) @ r0) * shrink

    def pose(t, ph):
        D = {}
        tt = ph * end
        off = U * hips_y(tt)
        q_h = Quaternion(L, math.radians(pitch(tt)))
        flex = track([(0.0, 0.0), (tc, 1.0), (tp, -1.0), (tl, 0.6), (end, 0.0)], tt)
        n_sp = max(len(rig.spine) - 1, 1)
        spine_q = [Quaternion(L, math.radians(7.0) * flex / n_sp)]
        tail_q = [Quaternion(L, math.radians(track([(0.0, 0.0), (tp, 20.0), (tl, -5.0), (end, 0.0)], tt)))] * len(rig.tail)
        body(rig, D, off, q_h, spine_q, [Quaternion()], Quaternion(), tail_q, close, level=0.6)
        for k, c in rig.legs.items():
            front = k[0] == "F"
            off_t, on_t = (tf_off, tl) if front else (tp, th)
            planted = balls[k]
            if front:   # tucked back, then reaching forward for the landing
                ang = track([(off_t, 0.0), (off_t + 0.12 * k_t, 55.0), (on_t - 0.12 * k_t, 40.0), (on_t, -10.0)], tt)
                shrink = track([(off_t, 1.0), (off_t + 0.12 * k_t, 0.7), (on_t - 0.12 * k_t, 0.8), (on_t, 1.0)], tt)
            else:       # extended back with the push, then tucked forward
                ang = track([(off_t, 0.0), (off_t + 0.1 * k_t, 35.0), (on_t - 0.15 * k_t, -25.0), (on_t, 0.0)], tt)
                shrink = track([(off_t, 1.0), (off_t + 0.1 * k_t, 0.95), (on_t - 0.15 * k_t, 0.72), (on_t, 1.0)], tt)
            if tt <= off_t or tt >= on_t:   # (planted: a hind foot's heel rising as the body goes over it)
                ball, flip = planted + U * (rig.heel_rise(k, -(pitch(tt)) / 12.0) if not front else 0.0), 0.0
            else:
                air = body_target(D, k, ang, shrink)
                w = min(smooth((tt - off_t) / (0.06 * k_t)), smooth((on_t - tt) / (0.06 * k_t)))
                ball = planted.lerp(air, w)
                flip = w * (1.0 if front else 0.6)
                ball = ball if ball.dot(U) >= planted.dot(U) else ball + U * (planted.dot(U) - ball.dot(U))
            lift = (ball - planted).dot(U)
            curl = min(0.8 * flip, math.asin(min(1.0, max(0.0, lift) / max(rig.foot_len(k), 1e-6))))
            if not c["toe"]:
                flip = min(flip, curl)
            rig.leg(D, k, ball, tilt=flip, curl=curl, root_q=Quaternion() if c["root"] else None)
        rest_fk(rig, D)
        return D
    return pose, n, math.sqrt(0.75 * G * h), {"air": [round(tp, 3), round(tl, 3)]}


def body(rig, D, off, q_h, spine_q, neck_q, head_q, tail_q, close, jaw_open=0.0, neck_all=None, level=0.0):
    """the hips moved and turned, the spine, the neck, the head, the jaw (closed by `close` radians, opened by jaw_open)
    and the tail turned (rotations in the rest's axes about each bone's head); level: how much of the body's turn the
    head takes back (0 none, 1 the head keeps its rest bearing in the world)"""
    if "hips" in rig.REST:
        h = rig.H["hips"]
        D["hips"] = Matrix.Translation(h + off) @ q_h.to_matrix().to_4x4() @ Matrix.Translation(-h)
    for i, n in enumerate(x for x in rig.spine if x != "hips"):
        rig.fk(D, n, spine_q[min(i, len(spine_q) - 1)] if spine_q else None)
    for i, n in enumerate(rig.neck):
        q = neck_all[i] if neck_all else (neck_q[min(i, len(neck_q) - 1)] if neck_q else None)
        rig.fk(D, n, q)
    if rig.head:
        p = rig.PAR[rig.head]
        Qp = D[p].to_quaternion() if p in D else Quaternion()
        rig.fk(D, rig.head, Qp.inverted() @ Qp.slerp(Quaternion(), level) @ head_q if level else head_q)
    if rig.jaw:   # (close: the marked open mouth's closing turn about the world X; opened about the left axis)
        rig.fk(D, rig.jaw, Quaternion(rig.LAT, jaw_open) @ Quaternion(Vector((1, 0, 0)), close))
    for i, n in enumerate(rig.tail):
        rig.fk(D, n, tail_q[i] if i < len(tail_q) else None)


def rest_fk(rig, D):
    """every bone not posed yet: with its parent"""
    for n in rig.ORDER:
        if n not in D:
            rig.fk(D, n)


def quad_idle(rig, close):
    h, n = rig.leg_h, 90
    F, U, L = rig.FWD, rig.UP, rig.LAT
    balls = {k: rig.ball(k) for k in rig.legs}

    def pose(t, ph):
        D = {}
        w = 2 * math.pi * ph
        off = U * (0.006 * h * math.sin(2 * w)) + L * (0.012 * h * math.sin(w))
        q_h = Quaternion(F, math.radians(1.2) * math.sin(w))
        spine_q = [Quaternion(L, math.radians(0.8) * math.sin(2 * w))]
        head_q = Quaternion(U, math.radians(14) * math.sin(w)) @ Quaternion(L, math.radians(4) * math.sin(2 * w + 1.0))
        neck_q = [Quaternion(U, math.radians(4) * math.sin(w - 0.3))]
        tail_q = [Quaternion(U, math.radians(10) * math.sin(2 * w - 0.6 * i)) for i in range(len(rig.tail))]
        body(rig, D, off, q_h, spine_q, neck_q, head_q, tail_q, close)
        for k in rig.legs:
            rig.leg(D, k, balls[k], root_q=Quaternion() if rig.legs[k]["root"] else None)
        rest_fk(rig, D)
        return D
    return pose, n, 0.0


def quad_attack(rig, close, open_deg):
    """a lunge: drawn back and low, the head down; thrust forward, the head swung up (a gore / a bite, the jaw open);
    back - the paws planted"""
    h, fps = rig.leg_h, 30
    n = 36
    F, U, L = rig.FWD, rig.UP, rig.LAT
    balls = {k: rig.ball(k) for k in rig.legs}
    T_ = [0.0, 0.35, 0.52, 0.7, 1.2]
    offs = [Vector(), -F * 0.07 * h - U * 0.06 * h, F * 0.14 * h + U * 0.01 * h, F * 0.06 * h, Vector()]
    pitch = [0.0, 6.0, -8.0, -2.0, 0.0]          # the hips' (+ nose down)
    neck = [0.0, 14.0, -12.0, -4.0, 0.0]
    headp = [0.0, 10.0, -28.0, -6.0, 0.0]
    jaw = [0.0, 0.0, open_deg, 0.0, 0.0]

    def pose(t, ph):
        D = {}
        tt = ph * T_[-1]
        val = lambda arr: track(list(zip(T_, arr)), tt)  # noqa: E731
        off = track(list(zip(T_, offs)), tt)
        q_h = Quaternion(L, math.radians(val(pitch)))
        neck_q = [Quaternion(L, math.radians(val(neck)) / max(len(rig.neck), 1))]
        head_q = Quaternion(L, math.radians(val(headp)))
        tail_q = [Quaternion(L, math.radians(-12) * smooth(tt / 0.4)) for _ in rig.tail]
        body(rig, D, off, q_h, [Quaternion(L, math.radians(-val(pitch)) / 3)], neck_q, head_q, tail_q, close,
             jaw_open=math.radians(val(jaw)))
        for k in rig.legs:   # (a foot's heel rising as the body goes forward over it)
            heel = rig.heel_rise(k, off.dot(F) / (0.1 * h)) if k[0] == "B" else 0.0
            rig.leg(D, k, balls[k] + U * heel, root_q=Quaternion() if rig.legs[k]["root"] else None)
        rest_fk(rig, D)
        return D
    return pose, n, 0.0


# ---------------------------------------------------------------- a bird
def bird_fns(rig, clip, close):
    h = rig.leg_h or 0.3 * rig.size
    F, U, L = rig.FWD, rig.UP, rig.LAT
    balls = {k: rig.ball(k) for k in rig.legs}
    fps = 30

    def legs_down(D, ph=None, gait=None):
        for k, c in rig.legs.items():
            if gait is None:
                rig.leg(D, k, balls[k], root_q=Quaternion() if c["root"] else None)
                continue
            duty, E, lift = gait
            p = (ph - (0.0 if k == "BL" else 0.5)) % 1.0
            if p < duty:
                x, up, flip = E / 2 - E * p / duty, 0.0, 0.0
            else:
                u = (p - duty) / (1 - duty)
                x, up, flip = -E / 2 + E * smooth(u), lift * math.sin(math.pi * u), math.sin(math.pi * u)
            rig.leg(D, k, balls[k] + F * x + U * up, tilt=1.1 * flip, curl=0.8 * flip, root_q=Quaternion() if c["root"] else None)

    def legs_tucked(D):
        for k, c in rig.legs.items():
            p = rig.PAR[c["root"] or c["upper"]]
            Dp = D[p] if p else Matrix.Identity(4)
            hip = Dp @ rig.H[c["upper"]]
            rig.leg(D, k, hip - F * 0.55 * h - U * 0.35 * h, tilt=1.4, curl=1.2, root_q=Quaternion() if c["root"] else None)

    def wings(D, elev, fold, sweep=0.0):
        """the wings held out from the body: elevation about the long axis (+ up), the forearm and hand folded back"""
        for s, ch in rig.wings.items():
            sg = 1.0 if s == "L" else -1.0
            out = L * sg
            Qp = D[rig.PAR[ch[0]]].to_quaternion() if rig.PAR[ch[0]] else Quaternion()
            body_q = Qp   # (the chest's turn: the wing goes with it)
            d1 = body_q @ (Quaternion(F, sg * elev) @ Quaternion(U, sg * (0.12 + sweep)) @ out)
            at = D[rig.PAR[ch[0]]] @ rig.H[ch[0]] if rig.PAR[ch[0]] else rig.H[ch[0]]
            Q = rig.aim(D, ch[0], at, d1, Qp)
            prev = ch[0]
            for i, b in enumerate(ch[1:]):
                bend = fold * (0.9 if i == 0 else 1.3)
                d = body_q @ (Quaternion(F, sg * elev * (1.0 + 0.12 * i)) @ Quaternion(U, sg * (0.12 + sweep + bend)) @ out)
                at = D[prev] @ rig.H[b]
                Q = rig.aim(D, b, at, d, Q)
                prev = b

    if clip == "idle":
        n = 120

        def pose(t, ph):
            D = {}
            w = 2 * math.pi * ph
            # the head turns in snaps: held, then a quick turn to the next look
            looks = [0, 25, -10, -30, 15, 0]
            k = ph * (len(looks) - 1)
            i = int(k)
            u = smooth(min(1.0, (k - i) / 0.15))
            yaw = looks[i] + (looks[min(i + 1, len(looks) - 1)] - looks[i]) * u
            body(rig, D, U * 0.01 * h * math.sin(2 * w), Quaternion(), [Quaternion(L, math.radians(1) * math.sin(2 * w))],
                 [Quaternion()], Quaternion(U, math.radians(yaw)), [Quaternion(L, math.radians(4) * math.sin(3 * w))] * len(rig.tail), close)
            legs_down(D)
            rest_fk(rig, D)
            return D
        return pose, n, 0.0

    if clip in ("walk", "run"):
        fr, duty, lift = (0.15, 0.62, 0.22) if clip == "walk" else (0.6, 0.4, 0.35)
        lam = 2.3 * fr ** 0.3
        v = math.sqrt(fr * G * h)
        E = duty * lam * h
        T = E / (duty * v)
        n = max(8, int(round(T * fps)))
        v = E / (duty * n / fps)

        def pose(t, ph):
            D = {}
            w = 2 * math.pi * ph
            off = U * (-0.025 * h * (0.5 + 0.5 * math.cos(2 * w))) + L * (0.04 * h * math.sin(w))
            q_h = Quaternion(F, math.radians(4) * math.sin(w)) @ Quaternion(U, math.radians(4) * math.sin(w))
            # the head held still in the world, then thrust forward (twice a cycle): the neck pitched back and forth
            saw = (2 * ph) % 1.0
            hold = saw / 0.7 if saw < 0.7 else 1.0 - (saw - 0.7) / 0.3
            neck_all = [Quaternion(L, math.radians(10) * (hold - 0.5) * (1 if i == 0 else -0.6)) for i in range(len(rig.neck))]
            head_q = Quaternion(L, -math.radians(10) * (hold - 0.5) * 0.4)
            body(rig, D, off, q_h, [Quaternion()], [], head_q, [Quaternion(L, math.radians(5) * math.sin(2 * w))] * len(rig.tail),
                 close, neck_all=neck_all)
            legs_down(D, ph, (duty, E, lift * h))
            rest_fk(rig, D)
            return D
        return pose, n, v

    if clip == "flap":
        T = min(1.0, max(0.3, 0.4 * math.sqrt(rig.size / 0.4)))
        n = max(8, int(round(T * fps)))

        def pose(t, ph):
            D = {}
            w = 2 * math.pi * ph
            stroke = math.sin(w)                      # + up
            elev = math.radians(36) * stroke + math.radians(6)
            fold = math.radians(35) * max(0.0, math.cos(w)) ** 1.5   # (the upstroke: the wrist folded)
            off = U * (-0.04 * h * stroke)
            q_h = Quaternion(L, math.radians(-6))   # (the body level for flight: nose a little up)
            body(rig, D, off, q_h, [Quaternion()], [Quaternion(L, math.radians(8))], Quaternion(L, math.radians(-8)),
                 [Quaternion(L, math.radians(-4) * stroke)] * len(rig.tail), close)
            wings(D, elev, fold, sweep=math.radians(6) * math.cos(w))
            legs_tucked(D)
            rest_fk(rig, D)
            return D
        return pose, n, 0.0

    if clip == "glide":
        n = 120

        def pose(t, ph):
            D = {}
            w = 2 * math.pi * ph
            q_h = Quaternion(F, math.radians(5) * math.sin(w)) @ Quaternion(L, math.radians(-4 + 2 * math.sin(2 * w)))
            body(rig, D, Vector(), q_h, [Quaternion()], [Quaternion(L, math.radians(8))], Quaternion(L, math.radians(-8)) @ Quaternion(F, math.radians(-4) * math.sin(w)),
                 [Quaternion(U, math.radians(4) * math.sin(w))] * len(rig.tail), close)
            wings(D, math.radians(6) + math.radians(3) * math.sin(2 * w), math.radians(3))
            legs_tucked(D)
            rest_fk(rig, D)
            return D
        return pose, n, 0.0

    # attack: a peck - drawn up and back, struck down and forward, the wings flared
    n = 27
    T_ = [0.0, 0.35, 0.5, 0.9]

    def pose(t, ph):
        D = {}
        tt = ph * T_[-1]
        neckp = track(list(zip(T_, [0.0, -22.0, 30.0, 0.0])), tt)
        headp = track(list(zip(T_, [0.0, -10.0, 25.0, 0.0])), tt)
        flare = track(list(zip(T_, [0.0, 0.5, 1.0, 0.0])), tt)
        jaw = track(list(zip(T_, [0.0, 0.0, 30.0, 0.0])), tt)
        body(rig, D, -F * 0.05 * h * flare, Quaternion(L, math.radians(neckp) * 0.25), [Quaternion()],
             [Quaternion(L, math.radians(neckp) / max(len(rig.neck), 1))], Quaternion(L, math.radians(headp)),
             [Quaternion(L, math.radians(-15) * flare)] * len(rig.tail), close, jaw_open=math.radians(jaw))
        for s, ch in rig.wings.items():   # (the rest wing lifted from the body: its own way, not a set direction)
            sg = 1.0 if s == "L" else -1.0
            rig.fk(D, ch[0], Quaternion(F, sg * math.radians(35) * flare))
        legs_down(D)
        rest_fk(rig, D)
        return D
    return pose, n, 0.0


# ---------------------------------------------------------------- a serpent
def serp_fns(rig, clip, close):
    sp = rig.spine
    F, U, L = rig.FWD, rig.UP, rig.LAT
    lens = [(rig.T[n] - rig.H[n]).length for n in sp]
    total = sum(lens)
    s_mid, acc = [], 0.0
    for ln in lens:
        s_mid.append(acc + ln / 2)
        acc += ln
    heights = [rig.H[n].dot(U) for n in sp] + [rig.T[sp[-1]].dot(U)]
    rest_pts = [rig.H[n] for n in sp] + [rig.T[sp[-1]]]
    centre = sum(rest_pts, Vector()) / len(rest_pts)
    fps = 30

    def lay(psis, rise=None, anchor_head=False):
        """the body laid along headings psis (radians about the up axis, 0 straight back) from the head; rise: per bone
        elevation (radians, + the head end up); centred on the rest's middle (in place)"""
        mean = sum(p * ln for p, ln in zip(psis, lens)) / total
        pts = [Vector()]   # (the head's end first)
        for i, (p, ln) in enumerate(zip(psis, lens)):
            e = rise[i] if rise else 0.0
            d = Quaternion(U, p - mean) @ (-F)
            d = d * math.cos(e) - U * math.sin(e)   # (the bone runs from the head end back and down when risen)
            pts.append(pts[-1] + d * ln)
        if anchor_head:
            shift = rig.H[sp[0]] - pts[0]
        else:
            c = sum(pts, Vector()) / len(pts)
            shift = centre - c
        pts = [p + shift for p in pts]
        if not rise:
            pts = [p - U * p.dot(U) + U * hgt for p, hgt in zip(pts, heights)]
        return pts

    def apply(D, pts, head_yaw=0.0, head_pitch=0.0, jaw_open=0.0):
        for i, n in enumerate(sp):
            d0 = rig.T[n] - rig.H[n]
            Q = rot_between(d0, pts[i + 1] - pts[i])
            rig.place(D, n, pts[i], Q)
        if rig.head:
            Qs = D[sp[0]].to_quaternion()
            rig.fk(D, rig.head, Qs.inverted() @ Quaternion(U, head_yaw) @ Quaternion(L, -head_pitch))
        if rig.jaw:
            rig.fk(D, rig.jaw, Quaternion(L, close - jaw_open))
        rest_fk(rig, D)

    def wave(amp_deg, wavelength, T):
        n = max(8, int(round(T * fps)))

        def pose(t, ph):
            D = {}
            psis = [math.radians(amp_deg) * math.sin(2 * math.pi * (s / wavelength - ph)) for s in s_mid]
            pts = lay(psis)
            apply(D, pts, head_yaw=-0.35 * psis[0])
            return D
        mean_cos = sum(math.cos(math.radians(amp_deg) * math.sin(2 * math.pi * i / 64)) for i in range(64)) / 64
        return pose, n, wavelength * mean_cos / (n / fps)

    if clip == "idle":
        n = 120

        def pose(t, ph):
            D = {}
            w = 2 * math.pi * ph
            apply(D, lay([math.radians(7) * math.sin(2 * math.pi * (s / (0.9 * total) - ph)) for s in s_mid]),
                  head_yaw=math.radians(18) * math.sin(w), head_pitch=math.radians(6) * math.sin(2 * w))
            return D
        return pose, n, 0.0
    if clip == "walk":
        return wave(32, 0.55 * total, 1.8)
    if clip == "run":
        return wave(42, 0.6 * total, 0.9)

    # attack: the front third reared in an S, struck forward and down, the jaw open; back
    n = 39
    T_ = [0.0, 0.45, 0.62, 0.85, 1.3]
    front = 0.38 * total

    def pose(t, ph):
        D = {}
        tt = ph * T_[-1]
        rear = track(list(zip(T_, [0.0, 1.0, 0.25, 0.25, 0.0])), tt)
        strike = track(list(zip(T_, [0.0, 0.0, 1.0, 0.6, 0.0])), tt)
        jaw = track(list(zip(T_, [0.0, 10.0, 40.0, 0.0, 0.0])), tt)
        rise = []
        for s in s_mid:
            u = max(0.0, 1.0 - s / front)          # 1 at the head, 0 where the rearing starts
            e = rear * math.radians(75) * math.sin(math.pi * u) * (1 - 0.6 * u) + strike * math.radians(-12) * u
            rise.append(e)
        psis = [math.radians(10) * (1 - rear) * math.sin(2 * math.pi * s / total) for s in s_mid]
        # the rest of the body on the ground: laid from the tail's end forward, the front part risen from there
        pts = lay(psis, rise)
        tail_end = pts[-1]
        rest_tail = rig.T[sp[-1]]
        shift = rest_tail - tail_end + F * (strike * 0.12 * total)
        pts = [p + shift for p in pts]
        ground = min(heights)
        pts = [p + U * max(0.0, (ground - p.dot(U))) for p in pts]
        apply(D, pts, head_pitch=math.radians(25) * rear - math.radians(10) * strike, jaw_open=math.radians(jaw))
        return D
    return pose, n, 0.0


# ---------------------------------------------------------------- all
def make_clips(arm, meshes, names=None, fps=30, close_deg=None):
    """the creature's procedural clips (names: the clips' ids - idle, walk, run ...; all of its body kind when empty)
    keyed as actions with NLA tracks named as clip_name() gives. Returns [{name, frames, seconds, loop, speed}]."""
    rig = Rig(arm, meshes)
    if rig.kind is None:
        raise RuntimeError("not a quadruped, a bird or a serpent by its bones' names")
    close = math.radians(close_deg) if close_deg else 0.0
    open_deg = 28.0 if rig.jaw else 0.0
    out = []
    for c in (names or CLIPS[rig.kind]):
        if c not in CLIPS[rig.kind]:
            continue
        extra = {}
        if rig.kind == "quadruped":
            if c == "idle":
                pose, n, v = quad_idle(rig, close)
            elif c == "attack":
                pose, n, v = quad_attack(rig, close, open_deg)
            elif c == "jump":
                pose, n, v, extra = quad_jump(rig, close)
            else:   # walk, trot, run and their turns (walk_left ...)
                gait, _, side = c.partition("_")
                pose, n, v, deg = quad_pose_fn(rig, gait, close, turn={"left": 1, "right": -1}.get(side, 0))
                if deg:
                    extra = {"turn": round(deg, 2)}   # (degrees a second the body turns: + to the left)
        elif rig.kind == "bird":
            pose, n, v = bird_fns(rig, c, close)
        else:
            pose, n, v = serp_fns(rig, c, close)
        loop = c in LOOPS
        name = clip_name(c)
        count = key_clip(rig, name, n, loop, pose, fps)
        out.append(dict(name=name, frames=count, seconds=round((count - 1) / fps, 3), loop=loop, speed=round(v, 4),
                        gait=c, body=rig.kind, **extra))
        print("GAIT_CLIP", name, count, round(v, 3), flush=True)
    for pb in arm.pose.bones:
        pb.rotation_quaternion, pb.location, pb.scale = (1, 0, 0, 0), (0, 0, 0), (1, 1, 1)
    return out
