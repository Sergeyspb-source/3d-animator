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
    n = name.lower()
    if ours:
        m = re.match(r"leg_(fl|fr|bl|br)_\d+", n)
        if m:
            return m[1].upper()
        if n.startswith("tail"):
            return "tail"
        if n in ("head", "snout", "jaw"):
            return n
        if re.match(r"(hips|spine|chest|neck)", n):
            return "body"
        return None
    if n in ("root",) or re.search(r"(tip|leaf)([_.][lr])?$", n) or re.search(r"ear|eye|horn|ribcage|teeth|wing|stomach|drv_|anchor", n):
        return None
    side = "L" if re.search(r"[_.]l$", n) else "R" if re.search(r"[_.]r$", n) else ""
    if "tail" in n:
        return "tail"
    if side and re.search(r"front|fore|scapula|humerus|collar|hand|arm", n):
        return "F" + side
    if side and re.search(r"back|hind|pelvis|thigh|leg", n):
        return "B" + side
    if re.search(r"chin|jaw|mouth_lower", n) or n == "mouth":
        return "jaw"
    if re.search(r"nose|snout|muzzle|mouth_upper", n):
        return "snout"
    if n == "head":
        return "head"
    if re.search(r"hips|spine|neck|pelvis", n):
        return "body"
    return None


def chains(arm, ours):
    """{kind: [bones from the root outwards]}; the body: only the bones on the way from the hips to the head"""
    depth = lambda b: len(b.parent_recursive)  # noqa: E731
    out = {}
    for b in arm.data.bones:
        k = kind(b.name, ours)
        if k:
            out.setdefault(k, []).append(b)
    for k in out:
        out[k].sort(key=depth)
    head = (out.get("head") or [None])[0]
    if head is not None and "body" in out:
        way = {p.name for p in head.parent_recursive}
        out["body"] = [b for b in out["body"] if b.name in way]
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


def facing(arm, C):   # the hips to the head, level
    W = arm.matrix_world
    h = W @ C["body"][0].head_local if C.get("body") else W @ arm.data.bones[0].head_local
    e = W @ C["head"][0].head_local if C.get("head") else h + Vector((0, -1, 0))
    d = Vector((e.x - h.x, e.y - h.y, 0))
    return d.normalized() if d.length > 1e-6 else Vector((0, -1, 0))


TC = chains(tgt, True)
pair = {"body": "body", "head": "head", "snout": "snout", "jaw": "jaw", "tail": "tail",
        "FL": "FL", "FR": "FR", "BL": "BL", "BR": "BR"}
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
hips_t = TC["body"][0].name if TC.get("body") else order[0].name
h_t = (tgt.matrix_world @ tgt.data.bones[hips_t].head_local).z - min((tgt.matrix_world @ b.head_local).z for b in tgt.data.bones)
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
    driver = {}
    for k, bones in TC.items():
        sk = pair.get(k)
        if sk not in SC:
            continue
        sb = SC[sk]
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
    hips_s = SC["body"][0].name if SC.get("body") else src.data.bones[0].name
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
        src.animation_data.action = None
    sources[path] = dict(src=src, acts=acts, driver=driver, Y=Matrix.Rotation(yaw, 3, "Z"), hips_s=hips_s,
                         scale=h_t / h_s if h_s > 1e-6 else 1.0, Ws=Ws, rest_s=rest_s, rest_hips=rest_hips,
                         stance="idle" if idle is not None else "bind")
    print("RETARGET_SOURCE", Path(path).name, {k: len(v) for k, v in SC.items()}, "yaw", round(math.degrees(yaw), 1),
          "stance", sources[path]["stance"],
          json.dumps(driver), flush=True)
    return sources[path]


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
            rp = tot[b.parent.name] if b.parent else Matrix.Identity(3)
            rc = rp.inverted() @ tot[nm]
            pb = tgt.pose.bones[nm]
            pb.rotation_quaternion = (M[nm].inverted() @ rc @ M[nm]).to_quaternion()
            pb.keyframe_insert("rotation_quaternion", frame=fi + 1)
        d = (Y @ ((src.matrix_world @ src.pose.bones[hips_s].head) - S["rest_hips"])) * S["scale"]
        if first is None:
            first = d.copy()
        d = Vector((first.x, first.y, d.z))   # in place: the hips keep their height's move, not their travel
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
