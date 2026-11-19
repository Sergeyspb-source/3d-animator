"""Runs INSIDE Blender (background): every clip of a skinned model checked - the floor, the feet's sliding, the loop's seam.

    blender -b -P blender_clip_check.py -- model.glb report.json

For each clip (its own action, played directly: the importer's NLA strips play nothing without their slot):
- sink: the skin's lowest point over the frames below the floor (the rest's lowest point is the floor), mm;
- hover: the lowest foot's height above the floor in the frames it should stand (its median over the frames), mm;
- slide: each foot's stands (a run of at least 4 frames with its bottom within 0.6 % of the height of the floor), its
  joint's way (not the lowest skin point's: on a flat sole that is any of them, from frame to frame): in
  place a standing foot goes back evenly (a treadmill), in the world it stays - either way a straight line at an even
  pace; how far it strays from that, the worst, mm (a foot passing low in its swing is no stand: its run is short);
- seam: a looping clip's last frame against its first (it plays on into it): the joints' largest jump, mm, and that
  against the clip's usual step between two frames (seam_x: about 1 - smooth, 3 and more - a visible jerk).
The feet: a creature's legs' last bones (leg_FL_5 ..), a humanoid's feet (Foot / ToeBase, Mixamo or Godot names), else
the lowest bones at rest. Writes report.json: {"height_mm", "clips": [{name, frames, loop, sink, hover, slide, seam}]};
prints CHECK_OK.
"""
import json
import math
import re
import statistics
import sys
from pathlib import Path

import bpy
from mathutils import Vector

a = sys.argv[sys.argv.index("--") + 1:]
src, out = a[0], a[1]
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.context.scene.render.fps = 30   # (before the import: the clips' keys land on their own frames, 30 fps)
bpy.ops.import_scene.gltf(filepath=src)
sc = bpy.context.scene
arm = next(o for o in sc.objects if o.type == "ARMATURE")
meshes = [o for o in sc.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
skin = max(meshes, key=lambda o: len(o.data.vertices))
ad = arm.animation_data_create()
loops = {}
try:   # (the clips' loop flags: written beside a creature's clips by the retargeting)
    listing = json.loads(Path(src + ".json").read_text(encoding="utf-8"))
    for c in listing.get("clips", []) if isinstance(listing, dict) else listing:   # (procedural clips: {"clips": [...], ...})
        loops[c["name"]] = bool(c.get("loop"))
except (OSError, ValueError, AttributeError, KeyError):
    pass
for t in list(ad.nla_tracks):
    ad.nla_tracks.remove(t)
ad.action = None
for pb in arm.pose.bones:
    pb.rotation_quaternion = (1, 0, 0, 0)
    pb.rotation_euler = (0, 0, 0)
    pb.location = (0, 0, 0)
bpy.context.view_layer.update()
W = arm.matrix_world

# ---- the feet
names = [b.name for b in arm.data.bones]
feet = []
legs = {}
for n in names:
    m = re.match(r"(leg_[A-Z0-9]+)_(\d+)$", n)
    if m:
        legs.setdefault(m[1], []).append((int(m[2]), n))
if legs:
    feet = [max(v)[1] for v in legs.values()]
if not feet:
    feet = [n for n in names if re.search(r"(left|right)(foot|toebase|toes)$|(foot|toe|paw|hoof)(_\d+)?[._]?[lr]$", n.replace("mixamorig:", "").lower())]
    by_leg = {}
    for n in feet:   # (a leg's toe if it has one: it is what stands; each leg its own - front and back)
        key = re.sub(r"(foot|toebase|toes|toe|paw|hoof)(_\d+)?", "", n.lower())
        if key not in by_leg or "toe" in n.lower():
            by_leg[key] = n
    feet = list(by_leg.values())
if not feet:
    zs = sorted(names, key=lambda n: (W @ arm.data.bones[n].head_local).z)
    feet = zs[:2]

# each foot's skin (led by it or the bone above it): its bottom, every frame
vg = {g.index: g.name for g in skin.vertex_groups}
own = {f: [] for f in feet}
near = {f: {f, arm.data.bones[f].parent.name if arm.data.bones[f].parent else f} for f in feet}
for v in skin.data.vertices:
    if v.groups:
        g = vg[max(v.groups, key=lambda g: g.weight).group]
        for f, s in near.items():
            if g in s:
                own[f].append(v.index)


def frame_points():
    dg = bpy.context.evaluated_depsgraph_get()
    ev = skin.evaluated_get(dg)
    me = ev.to_mesh()
    M = skin.matrix_world
    low = min((M @ v.co).z for v in me.vertices)
    fb = {}
    for f, ids in own.items():
        if ids:
            pts = [M @ me.vertices[i].co for i in ids]
            lowp = min(pts, key=lambda p: p.z)
            fb[f] = lowp
        else:
            fb[f] = W @ arm.pose.bones[f].head
    joints = [W @ pb.head for pb in arm.pose.bones]
    ev.to_mesh_clear()
    for f in feet:   # (the foot's own joint: where a flat sole stands, its lowest skin point is any of them)
        fb[f + "@"] = W @ arm.pose.bones[f].head
    return low, fb, joints


low0, _, j0 = frame_points()
zs = [p.z for p in j0]
height = max(max(zs) - min(zs), 1e-6)
floor = low0
fps = sc.render.fps or 30
report = {"height_mm": round(height * 1000), "feet": feet, "clips": []}
for act in sorted(bpy.data.actions, key=lambda x: x.name):
    ad.action = act
    if getattr(act, "slots", None) and len(act.slots) and getattr(ad, "action_slot", None) is None:
        ad.action_slot = act.slots[0]
    f0, f1 = int(act.frame_range[0]), int(act.frame_range[1])
    lows, fbs, jts = [], [], []
    for f in range(f0, f1 + 1):
        sc.frame_set(f)
        low, fb, js = frame_points()
        lows.append(low)
        fbs.append(fb)
        jts.append(js)
    sink = min(0.0, min(lows) - floor) * 1000
    stand = 0.02 * height
    hov = [min(fb[f].z for f in feet) - floor for fb in fbs]
    # sliding: each foot's stands (a run of frames, at least 4, its bottom within 0.6 % of the height of the floor);
    # in place a standing foot goes back evenly (a treadmill), in the world it stays: either way its way is a straight
    # line walked at an even pace - how far it strays from that is its slide
    stand = 0.006 * height
    worst = 0.0
    for f in feet:
        on = [fb[f].z - floor < stand for fb in fbs]
        i = 0
        while i < len(on):
            if not on[i]:
                i += 1
                continue
            j = i
            while j + 1 < len(on) and on[j + 1]:
                j += 1
            if j - i >= 3:
                p0, p1 = fbs[i][f + "@"], fbs[j][f + "@"]
                for k in range(i, j + 1):
                    q = p0.lerp(p1, (k - i) / (j - i))
                    worst = max(worst, math.hypot(fbs[k][f + "@"].x - q.x, fbs[k][f + "@"].y - q.y))
            i = j + 1
    loop = loops.get(act.name, bool(re.search(r"walk|run|trot|idle|sneak|swim|flap|glide|loop|cycle|winding", act.name.lower())))
    jump = lambda A, B: max((p - q).length for p, q in zip(A, B))  # noqa: E731
    seam = jump(jts[-1], jts[0]) * 1000 if loop and len(jts) > 2 else None
    step = statistics.median(jump(jts[i], jts[i + 1]) for i in range(len(jts) - 1)) * 1000 if len(jts) > 2 else 0
    report["clips"].append({"name": act.name, "frames": f1 - f0 + 1, "loop": loop, "sink": round(sink),
                            "hover": round(statistics.median(hov) * 1000), "slide": round(worst * 1000),
                            "seam": round(seam) if seam is not None else None,
                            "seam_x": round(seam / max(step, 1e-6), 1) if seam is not None else None})
Path(out).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
print("CHECK_OK " + json.dumps({"clips": len(report["clips"]), "feet": feet}), flush=True)
