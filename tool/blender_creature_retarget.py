"""Runs INSIDE Blender (background): a quadruped's clips (Mesh2Motion's fox, horse ... GLB) put on a creature's skeleton
(blender_creature_auto.py's names: hips, spine_01.., chest, neck_.., head, snout, jaw, leg_FL_1.., leg_BR_n, tail_01..).

    blender -b -P blender_creature_retarget.py -- job.json

job.json: {"target": the creature's GLB, "clips": [{"source": the clips' GLB, "action": its name there, "name": the
clip's name here, "loop": bool}], "out": GLB, "close_deg": the creature's jaw closing turn (a marked open mouth: the
clips' jaw moves from closed), "mesh": true}.
By chains, not by names: the body (the hips to the bone before the head), the head, the muzzle, the jaw, each leg (front
or back, left or right), the tail. Every bone of a creature's chain takes the turn - the change from its rest, in the
world - of the source bone at its place in the chain: one by one when the chains have as many bones, else the first
from the first, the last (the paw) from the last and the middle ones by their share of the length (a 4-bone hind leg
from a 6-bone one); the body by its share of the length (a creature's chest bone spans the fox's neck). Turned about
the upright when the two face different ways. The creature keeps its own rest shape (a crouching werewolf crouches in the
fox's walk); the hips' move is scaled by the hips' heights, its travel over the ground left out (in place).
Prints RETARGET_CLIP name frames, RETARGET_OK.
"""
import json
import math
import re
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
FPS = 30
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.render.fps = FPS


def load(path):
    before, acts = set(bpy.context.scene.objects), set(bpy.data.actions)
    bpy.ops.import_scene.gltf(filepath=str(path))
    new = [o for o in bpy.context.scene.objects if o not in before]
    arm = next(o for o in new if o.type == "ARMATURE")
    meshes = [o for o in new if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
    for o in new:   # (the importer's icosphere, loose empties)
        if o.type == "MESH" and o not in meshes:
            bpy.data.objects.remove(o, do_unlink=True)
    return arm, meshes, {re.sub(r"\.\d{3}$", "", a.name): a for a in bpy.data.actions if a not in acts}


tgt, tmeshes, _ = load(job["target"])
for a in list(bpy.data.actions):
    bpy.data.actions.remove(a)
if tgt.animation_data:
    tgt.animation_data_clear()
for pb in tgt.pose.bones:
    pb.rotation_mode = "QUATERNION"


# ---- what each bone is (None: not carried - ears, tips, helpers)
def kind(name, ours):
    """a bone's kind: body, head, snout, jaw, tail, a leg's side (legL / legR: the legs of a side are told apart by
    their chains, front to back), a wing's main way (WL / WR)"""
    n = name.lower()
    if ours:
        m = re.match(r"leg_(fl|bl|l\d+|fr|br|r\d+)_\d+", n)
        if m:
            return "leg" + ("L" if "l" in m[1] else "R")
        m = re.match(r"wing_([lr])_\d+$", n)
        if m:
            return "W" + m[1].upper()
        if n.startswith("tail"):
            return "tail"
        if n in ("head", "snout", "jaw"):
            return n
        if re.match(r"(hips|spine|chest|neck)", n):
            return "body"
        return None
    if n in ("root",) or re.search(r"(tip|leaf)([_.][lr])?$", n):
        return None
    side = "L" if re.search(r"[_.]l(\.\d+)?$", n) else "R" if re.search(r"[_.]r(\.\d+)?$", n) else ""
    if side and re.match(r"wing_\d+_[lr]$", n):   # (a dragon's, a bird's wing: its main way, not the feathers)
        return "W" + side
    if re.search(r"ear|eye|horn|ribcage|teeth|wing|stomach|drv_|anchor|thumb|finger|toes_tip", n):
        return None
    if "tail" in n:
        return "tail"
    if side and re.search(r"front|fore|scapula|humerus|collar|hand|arm|back|hind|pelvis|thigh|leg|fin|foot|ankle|toe", n):
        return "leg" + side
    if re.search(r"chin|jaw|mouth_lower", n) or n == "mouth":
        return "jaw"
    if re.search(r"nose|snout|muzzle|mouth_upper", n):
        return "snout"
    if n == "head":
        return "head"
    if re.search(r"hips|spine|neck|pelvis", n):
        return "body"
    return None


def facing(arm, C):   # the hips to the head, level
    W = arm.matrix_world
    h = W @ C["body"][0].head_local if C.get("body") else W @ arm.data.bones[0].head_local
    e = W @ C["head"][0].head_local if C.get("head") else h + Vector((0, -1, 0))
    d = Vector((e.x - h.x, e.y - h.y, 0))
    return d.normalized() if d.length > 1e-6 else Vector((0, -1, 0))


def hops(arm, start):
    """each bone's distance from `start` over the skeleton's links (up and down: a serpent's root may sit mid-body)"""
    nb = {b.name: [c.name for c in b.children] + ([b.parent.name] if b.parent else []) for b in arm.data.bones}
    d, todo = {start: 0}, [start]
    while todo:
        x = todo.pop(0)
        for y in nb[x]:
            if y not in d:
                d[y] = d[x] + 1
                todo.append(y)
    return d


def chains(arm, ours):
    """{kind: [bones from the root outwards]}; the body: only the bones on the way from the hips to the head. A side's
    legs split into their chains (leg_L0 the front one ..); no legs (a snake): the body - with its tail - from the head
    back (spine_01 by the head on ours)"""
    depth = lambda b: len(b.parent_recursive)  # noqa: E731
    out = {}
    for b in arm.data.bones:
        k = kind(b.name, ours)
        if k:
            out.setdefault(k, []).append(b)
    for k in out:
        out[k].sort(key=depth)
    head = (out.get("head") or [None])[0]
    serpent = not any(k.startswith("leg") for k in out)
    if serpent and head is not None:
        body = out.pop("body", []) + out.pop("tail", [])
        d = hops(arm, head.name)
        out["body"] = sorted(body, key=lambda b: d.get(b.name, 1e9))
    elif head is not None and "body" in out:
        way = {p.name for p in head.parent_recursive}
        out["body"] = [b for b in out["body"] if b.name in way]
    W = arm.matrix_world
    fwd = facing(arm, out)
    for side in ("L", "R"):
        bs = out.pop("leg" + side, [])
        names = {b.name for b in bs}
        comps = []
        for b in bs:   # (each leg: its bones linked to each other, from its own root)
            if b.parent is not None and b.parent.name in names:
                continue
            comp, todo = [], [b]
            while todo:
                x = todo.pop(0)
                comp.append(x)
                todo += [c for c in x.children if c.name in names]
            comps.append(sorted(comp, key=depth))
        comps.sort(key=lambda c: -(W @ c[-1].head_local).dot(fwd))   # (front first: by where its paw is)
        for i, c in enumerate(comps):
            out[f"leg{side}{i}"] = c
    out["_serpent"] = serpent
    return out


def spans(bones, arm):
    """each bone's share of its chain: [(start, end)] by the joints' distances (the last one: its own length)"""
    W = arm.matrix_world
    pts = [W @ b.head_local for b in bones] + [W @ bones[-1].tail_local]
    seg = [(pts[i + 1] - pts[i]).length for i in range(len(bones))]
    tot = sum(seg) or 1.0
    out, s = [], 0.0
    for x in seg:
        out.append((s / tot, (s + x) / tot))
        s += x
    return out


TC = chains(tgt, True)
T_SERP = TC.pop("_serpent")


def leg_pairs(TC, SC):
    """each target leg its source leg: a side's legs by their place front to back (the front by the front, a single
    one a side is a hind leg - a bird's); none when no source leg stands near (a bird's clips give a dog no front legs)"""
    out = {}
    for side in ("L", "R"):
        tl = sorted(k for k in TC if k.startswith("leg" + side))
        sl = sorted(k for k in SC if k.startswith("leg" + side))
        if not tl or not sl:
            continue
        pos = lambda i, n: (i / (n - 1)) if n > 1 else 1.0  # noqa: E731
        for i, tk in enumerate(tl):
            p = pos(i, len(tl))
            j = min(range(len(sl)), key=lambda j: abs(pos(j, len(sl)) - p))
            if abs(pos(j, len(sl)) - p) <= 0.34:
                out[tk] = sl[j]
    return out
Wt = tgt.matrix_world.to_3x3().normalized()
M = {b.name: b.matrix_local.to_3x3().normalized() for b in tgt.data.bones}
order = []


def walk(b):
    order.append(b)
    for c in b.children:
        walk(c)


for b in tgt.data.bones:
    if b.parent is None:
        walk(b)
hips_t = "hips" if "hips" in tgt.data.bones else (order[0].name if T_SERP else (TC["body"][0].name if TC.get("body") else order[0].name))
paws_t = {k: TC[k][-1].name for k in TC if k.startswith("leg")}
stand_t = {k: (tgt.matrix_world @ tgt.data.bones[n].head_local).z for k, n in paws_t.items()}
tip_t = {k: (tgt.matrix_world @ tgt.data.bones[n].tail_local).z for k, n in paws_t.items()}   # (the claws: a paw tipped down)
_zs = [(tgt.matrix_world @ b.head_local).z for b in tgt.data.bones]
h_t = (tgt.matrix_world @ tgt.data.bones[hips_t].head_local).z - min(_zs)
if h_t < 0.05 * (max(_zs) - min(_zs)) and TC.get("body"):   # (a root on the ground: the body's own height)
    h_t = max((tgt.matrix_world @ b.head_local).z for b in TC["body"][:2]) - min(_zs)
h_t = max(h_t, 1e-4)
# a marked open mouth: the clips' jaw from closed (its closing turn about the world X through the hinge, glTF ->
# Blender: the world X is the same)
close = Matrix.Rotation(math.radians(job["close_deg"]), 3, "X") if job.get("close_deg") and "jaw" in TC else None
sources = {}


def source(path):
    """a clips' GLB loaded once: its armature, its clips, each creature bone's driver, the turn between the two"""
    if path in sources:
        return sources[path]
    src, smeshes, acts = load(path)
    for o in smeshes:
        bpy.data.objects.remove(o, do_unlink=True)
    if src.animation_data:   # (the importer's tracks, every clip at once under the one played: gone)
        for t in list(src.animation_data.nla_tracks):
            src.animation_data.nla_tracks.remove(t)
    SC = chains(src, False)
    s_serp = SC.pop("_serpent")
    pair = {k: k for k in ("body", "head", "snout", "jaw", "tail", "WL", "WR")}
    pair.update(leg_pairs(TC, SC))
    driver = {}
    for k, bones in TC.items():
        sk = pair.get(k)
        if sk not in SC:
            continue
        sb = SC[sk]
        if k == "body" and T_SERP != s_serp:   # (a snake's body from the head, a beast's from the hips)
            sb = sb[::-1]
        if len(bones) == len(sb):   # one by one
            for b, c in zip(bones, sb):
                driver[b.name] = c.name
            continue
        ts, ss = spans(bones, tgt), spans(sb, src)
        got = []
        for i, (b, (a, c)) in enumerate(zip(bones, ts)):
            if k != "body" and len(bones) > 1 and i == 0:
                driver[b.name] = sb[0].name
            elif k != "body" and len(bones) > 1 and i == len(bones) - 1:
                driver[b.name] = sb[-1].name   # (the paw from the paw)
            else:
                u = (a + c) / 2
                pool = list(range(len(sb))) if k == "body" or len(sb) < 3 else list(range(1, len(sb) - 1))
                j = next((x for x in pool if ss[x][0] <= u <= ss[x][1]), min(pool, key=lambda x: abs((ss[x][0] + ss[x][1]) / 2 - u)))
                driver[b.name] = sb[j].name
            got.append(sb.index(next(x for x in sb if x.name == driver[b.name])))
        for i in range(1, len(got)):   # (two from one long bone - a horse's shin: the earlier one from the bone before)
            if got[i] <= got[i - 1] and k != "body":
                if got[i - 1] - 1 > (got[i - 2] if i > 1 else -1) and got[i - 1] - 1 >= 0:
                    got[i - 1] -= 1
                elif got[i - 1] + 1 < len(sb):
                    got[i] = got[i - 1] + 1
        for b, j in zip(bones, got):
            driver[b.name] = sb[j].name
    ft, fs = facing(tgt, TC), facing(src, SC)
    yaw = math.atan2(ft.y, ft.x) - math.atan2(fs.y, fs.x)
    hips_s = (min(SC["body"], key=lambda b: len(b.parent_recursive)).name if s_serp and SC.get("body")
              else SC["body"][0].name if SC.get("body") else src.data.bones[0].name)
    h_s = (src.matrix_world @ src.data.bones[hips_s].head_local).z - min((src.matrix_world @ b.head_local).z for b in src.data.bones)
    Ws = src.matrix_world.to_3x3().normalized()
    # the turns are counted from the source's own stance - its idle's first pose - not its bind pose: the creature's
    # rest is how it stands (a fox bound with straight legs stands with them bent: counted from the bind pose, a
    # crouching werewolf's paws, reaching forward at rest already, went up to level in a walk)
    rest_s = {b.name: Ws @ b.matrix_local.to_3x3().normalized() for b in src.data.bones}
    rest_hips = src.matrix_world @ src.data.bones[hips_s].head_local
    idle = next((a for n, a in acts.items() if n.lower() == "idle"), None)
    if idle is not None:
        src.animation_data_create()
        src.animation_data.action = idle
        if hasattr(src.animation_data, "action_slot") and idle.slots and src.animation_data.action_slot is None:
            src.animation_data.action_slot = idle.slots[0]
        bpy.context.scene.frame_set(int(idle.frame_range[0]))
        bpy.context.view_layer.update()
        rest_s = {pb.name: Ws @ pb.matrix.to_3x3().normalized() for pb in src.pose.bones}
        rest_hips = src.matrix_world @ src.pose.bones[hips_s].head
    # its paws' joints (each leg's last bone) as it stands: how high a paw is above that is how far off the ground
    paws_s = {tk: SC[sk][-1].name for tk, sk in pair.items() if tk.startswith("leg") and sk in SC}   # (by the target's legs)
    stand_s = {k: (src.matrix_world @ (src.pose.bones[n].head if idle is not None else src.data.bones[n].head_local)).z
               for k, n in paws_s.items()}
    if idle is not None:
        src.animation_data.action = None
    sources[path] = dict(src=src, acts=acts, driver=driver, Y=Matrix.Rotation(yaw, 3, "Z"), hips_s=hips_s,
                         scale=h_t / h_s if h_s > 1e-6 else 1.0, Ws=Ws, rest_s=rest_s, rest_hips=rest_hips,
                         paws_s=paws_s, stand_s=stand_s,
                         stance="idle" if idle is not None else "bind")
    print("RETARGET_SOURCE", Path(path).name, {k: len(v) for k, v in SC.items()}, "yaw", round(math.degrees(yaw), 1),
          "stance", sources[path]["stance"],
          json.dumps(driver), flush=True)
    return sources[path]


# ---- the creature's joints from the bones' turns (no scene update: a frame's legs are set many times)
HL = {b.name: b.head_local.copy() for b in tgt.data.bones}
TL = {b.name: b.tail_local.copy() for b in tgt.data.bones}
SUB = {}   # each bone and every bone below it
for b in tgt.data.bones:
    SUB[b.name] = [b.name] + [c.name for c in b.children_recursive]
WM = tgt.matrix_world
wz = lambda p: (WM @ p).z  # noqa: E731


def fk(tot, move):
    """every bone's head in the armature's space: the parent's turn carries its children; `move` - the hips' shift"""
    P = {}
    for b in order:
        if b.parent is None:
            P[b.name] = HL[b.name] + (move if b.name == hips_t else Vector())
        else:
            P[b.name] = P[b.parent.name] + tot[b.parent.name] @ (HL[b.name] - HL[b.parent.name])
            if b.name == hips_t:
                P[b.name] = P[b.name] + move
    return P


def tip_of(P, tot, n):
    return P[n] + tot[n] @ (TL[n] - HL[n])


# each paw's own skin (led by the leg's last bone): its points about that bone's head, so a frame's paw bottom is had
# without the skinning (a tilted hoof's rim went 9 cm below its bone's end)
PAW_SKIN = {}
_inv = tgt.matrix_world.inverted()
for k, n in paws_t.items():
    pts = []
    for o in tmeshes:
        gi = o.vertex_groups.get(n)
        if gi is None:
            continue
        for v in o.data.vertices:
            if v.groups and max(v.groups, key=lambda g: g.weight).group == gi.index:
                pts.append(_inv @ (o.matrix_world @ v.co) - HL[n])
    if pts:
        pts.sort(key=lambda q: (WM.to_3x3() @ q).z)
        PAW_SKIN[n] = pts[:max(40, len(pts) // 3)]   # (its lower part: what can touch the ground)
SKIN_REST = {n: min(wz(HL[n] + q) for q in qs) for n, qs in PAW_SKIN.items()}


def paw_bottom(P, tot, n, stand, tip):
    """how far the paw's lowest point is above where it is at rest: its skin's, else its joint's or its bone's end"""
    if n in PAW_SKIN:
        return min(wz(P[n] + tot[n] @ q) for q in PAW_SKIN[n]) - SKIN_REST[n]
    return min(wz(P[n]) - stand, wz(tip_of(P, tot, n)) - tip)


def plant(chain, tot, P, dz):
    """the leg's last joint moved dz up (in the world): the knee bent (its two lengths as they are) to reach, the leg
    turned at its upper joint onto the spot, the paw (the chain's last bone and below) kept as it was turned"""
    if len(chain) < 3:
        return
    j1, j2, paw = (chain[1].name, chain[2].name, chain[-1].name) if len(chain) >= 4 else (chain[0].name, chain[1].name, chain[-1].name)
    up = WM.inverted().to_3x3() @ Vector((0, 0, 1))
    A, B, C = P[j1], P[j2], P[paw]
    T = C + up.normalized() * (dz / max((WM.to_3x3() @ up.normalized()).length, 1e-9))
    a, bl = (B - A).length, (C - B).length
    if a < 1e-9 or bl < 1e-9:
        return
    dT = min(max((T - A).length, abs(a - bl) + 1e-4 * (a + bl)), (a + bl) * 0.999)
    keep = {x: tot[x].copy() for x in SUB[paw]}
    # the knee: its angle for the new reach, about the leg's own bend axis
    nrm = (B - A).cross(C - B)
    if nrm.length < 1e-9:
        nrm = (B - A).cross(up)
    if nrm.length < 1e-9:
        return
    nrm.normalize()
    cur = (B - A).angle(C - B)
    want = math.pi - math.acos(max(-1.0, min(1.0, (a * a + bl * bl - dT * dT) / (2 * a * bl))))
    R2, C1 = None, None
    for sg in (1.0, -1.0):   # (the knee's turn either way: the one that gives the reach)
        R = Matrix.Rotation(sg * (want - cur), 3, nrm)
        Cx = B + R @ (C - B)
        if R2 is None or abs((Cx - A).length - dT) < abs((C1 - A).length - dT):
            R2, C1 = R, Cx
    for x in SUB[j2]:
        tot[x] = R2 @ tot[x]
    # the whole leg turned at its upper joint: the paw's joint onto the spot
    R1 = (C1 - A).rotation_difference(T - A).to_matrix()
    for x in SUB[j1]:
        tot[x] = R1 @ tot[x]
    for x, m in keep.items():   # (the paw and its toes: as they were turned)
        tot[x] = m


done = []
for clip in job["clips"]:
    S = source(clip["source"])
    src, driver, Y, Ws, rest_s, hips_s = S["src"], S["driver"], S["Y"], S["Ws"], S["rest_s"], S["hips_s"]
    for other in sources.values():   # (only this clip's source moves)
        if other["src"] is not src and other["src"].animation_data:
            other["src"].animation_data.action = None
    act_s = S["acts"].get(clip["action"])
    if act_s is None:
        print("RETARGET_MISSING", clip["action"])
        continue
    src.animation_data_create()
    src.animation_data.action = act_s
    if hasattr(src.animation_data, "action_slot") and act_s.slots and src.animation_data.action_slot is None:
        src.animation_data.action_slot = act_s.slots[0]
    f0, f1 = int(act_s.frame_range[0]), int(act_s.frame_range[1])
    act = bpy.data.actions.new(clip["name"])
    ad = tgt.animation_data_create()
    ad.action = act
    n = f1 - f0 + 1
    if clip.get("loop") and n > 8:
        n -= 1   # (a loop starts again at its first pose)
    first = None
    for fi in range(n):
        bpy.context.scene.frame_set(f0 + fi)
        bpy.context.view_layer.update()
        tot = {}
        for b in order:
            nm = b.name
            if nm in driver:
                ps = src.pose.bones[driver[nm]]
                D = (Ws @ ps.matrix.to_3x3().normalized()) @ rest_s[driver[nm]].inverted()   # its turn in the world
                tw = Y @ D @ Y.inverted()
                if nm == "jaw" and close is not None:
                    tw = tw @ close
                tot[nm] = Wt.inverted() @ tw @ Wt
            else:   # not carried: with its parent as at rest
                tot[nm] = tot[b.parent.name] if b.parent else Matrix.Identity(3)
        d = (Y @ ((src.matrix_world @ src.pose.bones[hips_s].head) - S["rest_hips"])) * S["scale"]
        if first is None:
            first = d.copy()
        d = Vector((first.x, first.y, d.z))   # in place: the hips keep their height's move, not their travel
        # the ground: the creature's lowest paw as far off it as the source's lowest (scaled) - turned the same, legs
        # of other lengths put a sitting werewolf's hind paws into the floor, a standing one's in the air
        common = [k for k in paws_t if k in S["paws_s"]]
        if common:
            P = fk(tot, Wt.inverted() @ d)
            g_s = min((src.matrix_world @ src.pose.bones[S["paws_s"][k]].head).z - S["stand_s"][k] for k in common)
            g_t = min(paw_bottom(P, tot, paws_t[k], stand_t[k], tip_t[k]) for k in common)
            d.z += g_s * S["scale"] - g_t
            # each paw on its own ground (the lowest one alone left the others in the floor or in the air - a horse's
            # trot dipped 7 cm): where the source's paw stands, the creature's goes to the same height above its own
            # stance (scaled) by its knee and its upper joint, the paw itself kept as turned; fading as the paw lifts
            P = fk(tot, Wt.inverted() @ d)
            for k in common:
                hs = ((src.matrix_world @ src.pose.bones[S["paws_s"][k]].head).z - S["stand_s"][k]) * S["scale"]
                w = 1.0 if hs < 0.02 * h_t else max(0.0, 1.0 - (hs - 0.02 * h_t) / (0.1 * h_t))
                bottom = paw_bottom(P, tot, paws_t[k], stand_t[k], tip_t[k])   # (its skin: the claws, a hoof's rim)
                dz = (hs - bottom) * w
                if bottom + dz < 0:   # (never into the floor: a lifted paw of another leg's length swung through it)
                    dz = -bottom
                if abs(dz) > 1e-4 * h_t:
                    plant(TC[k], tot, P, dz)
                    P = fk(tot, Wt.inverted() @ d)
        for b in order:
            nm = b.name
            rp = tot[b.parent.name] if b.parent else Matrix.Identity(3)
            rc = rp.inverted() @ tot[nm]
            pb = tgt.pose.bones[nm]
            pb.rotation_quaternion = (M[nm].inverted() @ rc @ M[nm]).to_quaternion()
            pb.keyframe_insert("rotation_quaternion", frame=fi + 1)
        pb = tgt.pose.bones[hips_t]
        pb.location = M[hips_t].inverted() @ (Wt.inverted() @ d)
        pb.keyframe_insert("location", frame=fi + 1)
    act.use_frame_range = True
    act.frame_start, act.frame_end = 1, n
    tr = ad.nla_tracks.new()
    tr.name = clip["name"]
    st = tr.strips.new(clip["name"], 1, act)
    st.frame_end = n
    ad.action = None
    done.append(dict(name=clip["name"], frames=n, seconds=round(n / FPS, 3), loop=bool(clip.get("loop"))))
    print("RETARGET_CLIP", clip["name"], n, flush=True)

for pb in tgt.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.location = (0, 0, 0)
for S in sources.values():
    bpy.data.objects.remove(S["src"], do_unlink=True)
bpy.ops.object.select_all(action="DESELECT")
tgt.select_set(True)
if job.get("mesh", True):
    for o in tmeshes:
        o.select_set(True)
Path(job["out"]).parent.mkdir(parents=True, exist_ok=True)
Path(str(job["out"]) + ".json").write_text(json.dumps(done, indent=1, ensure_ascii=False), encoding="utf-8")
bpy.ops.export_scene.gltf(filepath=str(job["out"]), export_format="GLB", use_selection=True, export_animation_mode="NLA_TRACKS",
                          export_force_sampling=True)
print("RETARGET_OK", job["out"])
