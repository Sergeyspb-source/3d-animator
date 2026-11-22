"""Runs INSIDE Blender (background): give a rigged character with a jetpack its own nozzle bones, so the game can swing
the side nozzles in flight like real thrusters.

    blender -b -P blender_jet_nozzles.py -- rigged.glb out.glb top=x,y,z bottom=x,y,z [radius=3.6] [ymin=4.0]
        [vote=0.45] [top_max=71.5] [inner=7.2] [collar=top.z-0.3] [blend=3.0] [parent=Spine2] [preview=path_prefix]

`top` / `bottom` are the right nozzle's axis in world units of the imported file (top = where it hangs from the pack,
the pivot; bottom = its exit); the left one is the mirror in x. A nozzle is every connected piece of the mesh at
least `vote` of whose vertices lie in the capsule round that axis (radius `radius`, behind `ymin`, outside |x| `inner`,
below the pivot plane, no piece reaching above `top_max`, none centred above `collar` - the ring it hangs from stays
with the pack): whole pieces, so nothing tears. Each side gets a bone
JetNozzle_L / JetNozzle_R from the pivot to the exit, parented to `parent`; its pieces are weighted to it, blended with
`parent` over the first `blend` units from the pivot (so the mount bends rather than opens a gap).
With `preview` it renders the nozzles at rest and swung (front, back, forward, out) to <prefix>_<pose>.png.
Prints JET_ lines.
"""
import math
import sys

import bmesh
import bpy
import numpy as np
from mathutils import Euler, Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
T = np.array([float(x) for x in opt["top"].split(",")])
B = np.array([float(x) for x in opt["bottom"].split(",")])
R = float(opt.get("radius", 3.6))
YMIN = float(opt.get("ymin", 4.0))
VOTE = float(opt.get("vote", 0.45))
TOP_MAX = float(opt.get("top_max", 71.5))
INNER = float(opt.get("inner", 7.2))
COLLAR = float(opt.get("collar", T[2] - 0.3))   # small pieces centred above the pivot are the pack's collar: they stay

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
me = next(o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups)
m = me.data
pre = "mixamorig:" if any(b.name.startswith("mixamorig:") for b in arm.data.bones) else ""
parent = pre + opt.get("parent", "Spine2") if pre + opt.get("parent", "Spine2") in arm.data.bones else opt.get("parent", "Spine2")
P = np.array([tuple(me.matrix_world @ v.co) for v in m.vertices])

bm = bmesh.new()
bm.from_mesh(m)
bm.verts.ensure_lookup_table()
comp = -np.ones(len(P), int)
count = 0
for v in bm.verts:
    if comp[v.index] >= 0:
        continue
    stack = [v]
    comp[v.index] = count
    while stack:
        a = stack.pop()
        for e in a.link_edges:
            b = e.other_vert(a)
            if comp[b.index] < 0:
                comp[b.index] = count
                stack.append(b)
    count += 1
bm.free()


def capsule(top, bottom):
    ax = bottom - top
    length = np.linalg.norm(ax)
    ax = ax / length
    d = P - top
    t0 = d @ ax
    t = np.clip(t0, 0.0, length)
    r = np.linalg.norm(d - np.outer(t, ax), axis=1)
    return (r < R) & (P[:, 1] > YMIN) & (t0 >= 0.0) & (np.abs(P[:, 0]) > INNER)


def pieces(raw):
    out = np.zeros(len(P), bool)
    for c in np.unique(comp[raw]):
        idx = np.flatnonzero(comp == c)
        if raw[idx].mean() >= VOTE and P[idx][:, 2].max() < TOP_MAX and P[idx][:, 2].mean() < COLLAR:
            out[idx] = True
    return out


sides = {"R": (T, B), "L": (T * [-1, 1, 1], B * [-1, 1, 1])}
picked = {}
for side, (top, bottom) in sides.items():
    picked[side] = pieces(capsule(top, bottom))
    q = P[picked[side]]
    print("JET_PICK %s vertices=%d min=%s max=%s" % (side, len(q), q.min(0).round(2), q.max(0).round(2)))
overlap = picked["R"] & picked["L"]
assert not overlap.any(), "the two nozzles share vertices"

bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
inv = arm.matrix_world.inverted()
names = {"R": "JetNozzle_R", "L": "JetNozzle_L"}
for side, (top, bottom) in sides.items():
    ax = (bottom - top) / np.linalg.norm(bottom - top)
    exit_t = (P[picked[side]] - top) @ ax
    tip = top + ax * float(exit_t.max())                      # the exit: as far along the axis as the nozzle goes
    eb = arm.data.edit_bones.new(names[side])
    eb.head = inv @ Vector(tuple(top))
    eb.tail = inv @ Vector(tuple(tip))
    eb.roll = 0.0
    eb.parent = arm.data.edit_bones[parent]
    eb.use_deform = True
    print("JET_BONE %s head=%s tail=%s parent=%s" % (names[side], top.round(2), tip.round(2), parent))
bpy.ops.object.mode_set(mode="OBJECT")

# weights: the nozzle's bone below `blend` units from the pivot, the pack's (parent) bone at the pivot, smoothly between: the nozzle bends at
# its mount instead of opening a gap there when it swings (2026-11-18, the user: «есть отставания от сопел» at the mounts)
BLEND = float(opt.get("blend", 3.0))
for side, (top, bottom) in sides.items():
    group = me.vertex_groups.new(name=names[side])
    ax = (bottom - top) / np.linalg.norm(bottom - top)
    idx = [int(i) for i in np.flatnonzero(picked[side])]
    along = (P[idx] - top) @ ax
    for i, a in zip(idx, along):
        for g in list(m.vertices[i].groups):
            me.vertex_groups[g.group].remove([i])
        x = float(np.clip(a / BLEND, 0.0, 1.0)) if BLEND > 0 else 1.0
        w = x * x * (3.0 - 2.0 * x)
        if w > 0.0:
            group.add([i], w, "REPLACE")
        if w < 1.0:
            me.vertex_groups[parent].add([i], 1.0 - w, "REPLACE")
print("JET_WEIGHTS R=%d L=%d blended over %.2f from the pivot" % (int(picked["R"].sum()), int(picked["L"].sum()), BLEND))

if "preview" in opt:
    scn = bpy.context.scene
    scn.render.engine = "BLENDER_EEVEE"
    scn.render.resolution_x, scn.render.resolution_y = 700, 700
    world = bpy.data.worlds.new("w")
    scn.world = world
    world.color = (0.75, 0.75, 0.78)
    for rot in [(0.8, 0.2, 0.5), (0.9, 0.1, 3.4)]:
        sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
        scn.collection.objects.link(sun)
        sun.rotation_euler = rot
        sun.data.energy = 3.0
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scn.collection.objects.link(cam)
    scn.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = float(opt.get("preview_scale", 40))
    centre = Vector((0.0, 8.0, (T[2] + B[2]) * 0.5 + 2.0))
    view = Vector((0.35, 1.0, 0.25)).normalized()          # behind and a little to the side
    cam.location = centre + view * 200.0
    cam.rotation_euler = (-view).to_track_quat("-Z", "Y").to_euler()
    for o in list(scn.objects):
        if o.type == "MESH" and o is not me:
            o.hide_render = True
    poses = {"rest": (0, 0, 0), "forward": (35, 0, 0), "back": (-35, 0, 0), "out": (0, 0, 30), "in": (0, 0, -20)}
    for pose, deg in poses.items():
        for side in sides:
            pb = arm.pose.bones[names[side]]
            pb.rotation_mode = "XYZ"
            sign = 1.0 if side == "R" else -1.0
            pb.rotation_euler = Euler((math.radians(deg[0]), math.radians(deg[1]), math.radians(deg[2] * sign)))
        bpy.context.view_layer.update()
        scn.render.filepath = opt["preview"] + "_" + pose + ".png"
        bpy.ops.render.render(write_still=True)
    for side in sides:
        arm.pose.bones[names[side]].rotation_euler = Euler((0, 0, 0))
        arm.pose.bones[names[side]].rotation_mode = "QUATERNION"

bpy.ops.object.select_all(action="DESELECT")
for o in bpy.context.scene.objects:
    if o.type in ("MESH", "ARMATURE"):
        o.hide_render = False
        o.select_set(True)                                   # everything the file had: only the bones and weights change
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=len(bpy.data.actions) > 0)
print("JET_OK", dst, "actions", len(bpy.data.actions))
