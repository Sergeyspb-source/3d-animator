"""Runs INSIDE Blender (imported by blender_creature_retarget.py): a creature's own clips keyed from key poses - the hips'
offset, each bone's turn, the jaw, where each leg's wrist / ankle goes (on the ground, with the body, on a wall) - the legs
solved by two-bone IK, the paws kept flat on what they stand on while planted. From the game project's key_nurgle_clips.py
(the nurgle's leap, paw strike and wall climb read off the user's videos), made to work on the armature of the clips being
made: the leg chains found by their names (leg_FL_1 .. : the upper, lower, paw and toe bones are its 2nd .. 5th), every
bone keyed on every frame (30 fps; a channel left out keeps another clip's value in a game's bake).

A poses module (creature_keys/<name>.py) gives GROUND, WALL_Y, WALL_GAP, WALL_PAW, TOE_SHARE, WRIST_FLOOR, REF (the
heights of the hips and of the ground - the claws - on the rig they were made on) and CLIPS [{name, keys: [{t, ease,
hips, jaw, rot, legs}]}] (its own notes say how a key reads). A creature of another size gets every distance scaled by
its hips' height over its skin's lowest point against REF's, the ground at that point."""
import copy
import importlib.util
import math
from types import SimpleNamespace

import bpy
from mathutils import Matrix, Quaternion, Vector


def load_poses(path):
    spec = importlib.util.spec_from_file_location("creature_poses", str(path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def legs_of(arm):
    """{FL: (upper, lower, paw, toe or None)} from the leg chains' names; the ones not there left out"""
    out = {}
    for k in ("FL", "FR", "BL", "BR"):
        ch = sorted((b.name for b in arm.data.bones if b.name.startswith(f"leg_{k}_")), key=lambda n: int(n.rsplit("_", 1)[1]))
        if len(ch) >= 4:
            out[k] = (ch[1], ch[2], ch[3], ch[4] if len(ch) >= 5 else None)
    return out


def turn(pyr):
    """A turn in the rig's axes (X the creature's left, -Y forward, Z up) from (pitch up, yaw left, roll) degrees."""
    p, y, r = (math.radians(v) for v in pyr)
    return Quaternion((0, 0, 1), y) @ Quaternion((1, 0, 0), -p) @ Quaternion((0, 1, 0), r)


def hermite(keys, t, value):
    """`keys`: [(time, ease, v)], v a float or Vector; holds ("hold") stop, others pass through (Catmull-Rom tangents)."""
    if t <= keys[0][0] or len(keys) == 1:
        return value(keys[0][2], 0), 0, 0.0
    if t >= keys[-1][0]:
        return value(keys[-1][2], len(keys) - 1), len(keys) - 2, 1.0
    k = max(i for i in range(len(keys) - 1) if keys[i][0] <= t)
    t0, t1 = keys[k][0], keys[k + 1][0]
    h = t1 - t0
    u = (t - t0) / h
    vals = {i: value(keys[i][2], i) for i in range(max(0, k - 1), min(len(keys), k + 3))}

    def tangent(i):
        if keys[i][1] == "hold" or i == 0 or i == len(keys) - 1:
            return vals[i] * 0.0
        return (vals[i + 1] - vals[i - 1]) * (h / (keys[i + 1][0] - keys[i - 1][0]))
    m0, m1 = tangent(k), tangent(k + 1)
    a, b, c, d = 2 * u ** 3 - 3 * u ** 2 + 1, u ** 3 - 2 * u ** 2 + u, -2 * u ** 3 + 3 * u ** 2, u ** 3 - u ** 2
    return vals[k] * a + m0 * b + vals[k + 1] * c + m1 * d, k, u


def two_bone(A, T, l1, l2, bend):
    d = T - A
    dist = min(max(d.length, abs(l1 - l2) + 1e-4), l1 + l2 - 1e-4)
    e = d.normalized()
    n = (bend - e * bend.dot(e)).normalized()
    cos_a = (l1 * l1 + dist * dist - l2 * l2) / (2 * l1 * dist)
    M = A + e * (l1 * cos_a) + n * (l1 * math.sqrt(max(0.0, 1 - cos_a * cos_a)))
    return M, A + e * dist


def aim(base, head, to):
    """`base` (a bone's matrix with no turn of its own) turned the least so its Y axis points from `head` at `to`."""
    q = base.to_3x3().col[1].normalized().rotation_difference((to - head).normalized())
    return Matrix.LocRotScale(head, q @ base.to_quaternion(), None)


def scaled(P, arm, meshes):
    """The poses for this rig: as they are on the rig they were made on, else every distance scaled (see above)."""
    bones = arm.data.bones
    ref = getattr(P, "REF", None)
    if not ref or "hips" not in bones or not meshes:
        return P, 1.0
    inv = arm.matrix_world.inverted()
    ground = min((inv @ o.matrix_world @ v.co).z for o in meshes for v in o.data.vertices)   # (the claws, at rest)
    k = (bones["hips"].head_local.z - ground) / max(ref["hips"] - ref["ground"], 1e-6)
    if abs(k - 1) < 0.03 and abs(ground - P.GROUND) < 0.03 * (ref["hips"] - ref["ground"]):
        return P, 1.0
    out = SimpleNamespace(**{n: getattr(P, n) for n in dir(P) if n.isupper()})
    out.GROUND = ground
    out.WALL_Y, out.WALL_GAP = P.WALL_Y * k, P.WALL_GAP * k
    out.WRIST_FLOOR = {n: v * k for n, v in P.WRIST_FLOOR.items()}
    out.CLIPS = copy.deepcopy(P.CLIPS)
    for c in out.CLIPS:
        for key in c["keys"]:
            if key.get("hips") is not None:
                key["hips"] = tuple(v * k for v in key["hips"])
            for spec in (key.get("legs") or {}).values():
                for n in ("f", "s", "u", "lift", "away"):
                    if n in spec:
                        spec[n] *= k
    return out, k


def make_clips(arm, poses_path, names, fps=30, meshes=()):
    """The poses module's clips named (all when names is empty) keyed onto `arm` as actions with NLA tracks of their
    names (`meshes`: the creature's skin, its size). Returns [{name, frames, seconds, loop}] and prints KEYED name frames
    {missed}."""
    POSES, size = scaled(load_poses(poses_path), arm, meshes)
    if size != 1.0:
        print("KEYED_SCALE", round(size, 3), flush=True)
    bones = arm.data.bones
    LEGS = legs_of(arm)
    need = {"hips", "jaw"} | {n for c in POSES.CLIPS for k in c["keys"] for n in (k.get("rot") or {})}
    missing = sorted(n for n in need if n not in bones) + sorted(set(("FL", "FR", "BL", "BR")) - set(LEGS))
    if missing:
        raise RuntimeError("the creature has no " + ", ".join(missing))
    REST = {b.name: b.matrix_local.copy() for b in bones}
    PARENT = {b.name: b.parent.name if b.parent else None for b in bones}
    ORDER = sorted(REST, key=lambda n: len(bones[n].parent_recursive))
    IK = {u: leg for leg, (u, lo, paw, toe) in LEGS.items()}
    MISS = {}

    def track(clip, pick):
        out = [(k["t"], k.get("ease", "flow"), pick(k)) for k in clip["keys"] if pick(k) is not None]
        assert out and out[0][0] == 0.0 and out[-1][0] == clip["keys"][-1]["t"], "%s: a channel must be keyed first and last" % clip["name"]
        return out

    def leg_target(leg, spec, A, Dp):
        u, lo = LEGS[leg][0], LEGS[leg][1]
        T0, A0 = bones[lo].tail_local, bones[u].head_local
        side = 1.0 if leg[1] == "L" else -1.0
        f, up, s = spec.get("f", 0.0), spec.get("u", 0.0), spec.get("s", 0.0) * side
        if spec["sp"] == "g":
            return Vector((T0.x + s, T0.y - f, T0.z + up))
        if spec["sp"] == "w":
            return Vector((T0.x + s, POSES.WALL_Y + POSES.WALL_GAP, POSES.GROUND + up))
        return A + Dp @ (T0 - A0 + Vector((s, -f, up)))

    def pose_at(clip, tracks, t):
        P, B = {}, {}
        for n in ORDER:
            p = PARENT[n]
            free = (P[p] @ REST[p].inverted() @ REST[n]) if p else REST[n].copy()
            if n in B:
                pass
            elif n in IK:
                leg = IK[n]
                u, lo, paw, toe = LEGS[leg]
                Dp = (P[p].to_3x3() @ REST[p].to_3x3().inverted()).to_quaternion().to_matrix()
                A = free.translation
                spec_keys = tracks["leg_" + leg]
                T, k, s = hermite(spec_keys, t, lambda sp, i: leg_target(leg, sp, A, Dp))
                nxt = spec_keys[min(k + 1, len(spec_keys) - 1)][2]
                arc = math.sin(math.pi * s)
                T = T + Vector((0, nxt.get("away", 0.0), nxt.get("lift", 0.0))) * arc
                T.z = max(T.z, POSES.GROUND + POSES.WRIST_FLOOR[leg[0]])
                plant = min(1.0, max(0.0, hermite(spec_keys, t, lambda sp, i: sp.get("w", 0.0))[0]))
                curl = hermite(spec_keys, t, lambda sp, i: sp.get("c", 0.0))[0]
                A0, M0, T0 = bones[u].head_local, bones[u].tail_local, bones[lo].tail_local
                e0 = (T0 - A0).normalized()
                bend = Dp @ (M0 - A0 - e0 * (M0 - A0).dot(e0)).normalized()
                M, reached = two_bone(A, T, bones[u].length, bones[lo].length, bend)
                if plant > 0.5:
                    MISS[leg] = max(MISS.get(leg, (0.0, 0.0)), ((reached - T).length, round(t, 2)))
                T = reached
                Pu = aim(free, A, M)
                Pl = aim(Pu @ REST[u].inverted() @ REST[lo], M, T)
                across = Dp @ Vector((1, 0, 0))
                fk = Quaternion(across, math.radians(curl)) @ (Pl @ REST[lo].inverted() @ REST[paw]).to_quaternion()
                flat = [REST[paw].to_quaternion(), Quaternion((1, 0, 0), math.radians(POSES.WALL_PAW)) @ REST[paw].to_quaternion()]
                on = flat[spec_keys[k][2]["sp"] == "w"].slerp(flat[nxt["sp"] == "w"], s * s * (3 - 2 * s))
                Pp = Matrix.LocRotScale(T, fk.slerp(on, plant), None)
                for name, mat, par in ((u, Pu, free), (lo, Pl, Pu @ REST[u].inverted() @ REST[lo]), (paw, Pp, Pl @ REST[lo].inverted() @ REST[paw])):
                    B[name] = par.inverted() @ mat
                if toe:
                    base = Pp @ REST[paw].inverted() @ REST[toe]
                    bent = Quaternion(across, math.radians(curl * POSES.TOE_SHARE)) @ base.to_quaternion()
                    B[toe] = base.inverted() @ Matrix.LocRotScale(base.translation, bent, None)
                P[u] = Pu
                continue
            else:
                q = turn(hermite(tracks["rot_" + n], t, lambda v, i: Vector(v))[0]) if ("rot_" + n) in tracks else Quaternion()
                R3 = REST[n].to_3x3()
                basis = (R3.inverted() @ q.to_matrix() @ R3).to_4x4()
                if n == "jaw":
                    basis = Matrix.Rotation(math.radians(hermite(tracks["jaw"], t, lambda v, i: v)[0]), 4, "X")
                if n == "hips":
                    basis = Matrix.Translation(R3.inverted() @ hermite(tracks["hips"], t, lambda v, i: Vector(v))[0]) @ basis
                B[n] = basis
            P[n] = free @ B[n]
        return B

    def make(clip):
        tracks = {"hips": track(clip, lambda k: k.get("hips")), "jaw": track(clip, lambda k: k.get("jaw"))}
        for n in REST:
            if any(n in k.get("rot", {}) for k in clip["keys"]):
                tracks["rot_" + n] = track(clip, lambda k, n=n: k.get("rot", {}).get(n, (0, 0, 0) if k is clip["keys"][0] or k is clip["keys"][-1] else None))
        for leg in LEGS:
            tracks["leg_" + leg] = track(clip, lambda k, leg=leg: k.get("legs", {}).get(leg))
        ad = arm.animation_data or arm.animation_data_create()
        for tr in [tr for tr in ad.nla_tracks if tr.name == clip["name"]]:   # (made again: the old one replaced)
            ad.nla_tracks.remove(tr)
        if clip["name"] in bpy.data.actions:
            bpy.data.actions.remove(bpy.data.actions[clip["name"]])
        act = bpy.data.actions.new(clip["name"])
        ad.action = act
        count = int(round(clip["keys"][-1]["t"] * fps)) + 1
        last = {}
        MISS.clear()
        for i in range(count):
            B = pose_at(clip, tracks, i / fps)
            for n, pb in arm.pose.bones.items():
                loc, q, _ = B[n].decompose() if n in B else (Vector(), Quaternion(), None)
                if n in last and q.dot(last[n]) < 0:
                    q.negate()
                last[n] = q
                pb.rotation_mode = "QUATERNION"
                pb.location, pb.rotation_quaternion, pb.scale = loc, q, (1, 1, 1)
                for path in ("location", "rotation_quaternion", "scale"):
                    pb.keyframe_insert(path, frame=i + 1)
        act.use_frame_range = True
        act.frame_start, act.frame_end = 1, count
        act.use_fake_user = True
        tr = ad.nla_tracks.new()
        tr.name = clip["name"]
        tr.strips.new(clip["name"], 1, act).frame_end = count
        ad.action = None
        print("KEYED", clip["name"], count, {k: (round(v[0], 3), v[1]) for k, v in MISS.items()}, flush=True)
        return dict(name=clip["name"], frames=count, seconds=round(count / fps, 3), loop=False)

    made = [make(c) for c in POSES.CLIPS if not names or c["name"] in names]
    for pb in arm.pose.bones:
        pb.rotation_quaternion, pb.location, pb.scale = (1, 0, 0, 0), (0, 0, 0), (1, 1, 1)
    return made
