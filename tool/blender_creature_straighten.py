"""Runs INSIDE Blender (background): a creature's rest pose straightened - the paws under their shoulders and hips (no
splay to the sides), each pair level front to back, the spine, the neck, the head and the tail on the middle line -
and that pose made the rest: the skin deformed by its own weights, the skeleton's rest set to it.

    blender -b -P blender_creature_straighten.py -- job.json

job.json: {"src": the creature's skeleton before its jaw (<name>_auto.glb; a jaw there goes back to its parent), "out":
GLB, "names": {UniRig's name: readable} (the passport's)}.
A model made in a crouch or a stride keeps its bends seen from the side; what goes are the splay and the twist seen from
above and the front, which clips counted from the rest put into every frame (a splayed hind leg walked splayed).
Prints STRAIGHTEN_OK {"head": 4x4 world change of the head (the mouth's marks move with it), "turned": {bone: degrees}}.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Vector

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["src"])
sc = bpy.context.scene
arm = next(o for o in sc.objects if o.type == "ARMATURE")
meshes = [o for o in sc.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
for o in list(sc.objects):
    if o.type == "MESH" and o not in meshes:
        bpy.data.objects.remove(o, do_unlink=True)
for b in arm.data.bones:   # the readable names (the vertex groups follow)
    new = job.get("names", {}).get(b.name)
    if new and new != b.name:
        old = b.name
        b.name = new
        for o in meshes:
            g = o.vertex_groups.get(old)
            if g:
                g.name = new
if "jaw" in arm.data.bones:   # (made again from the mouth's marks: its weights back to its parent)
    parent = arm.data.bones["jaw"].parent.name
    for o in meshes:
        jg, pg = o.vertex_groups.get("jaw"), o.vertex_groups.get(parent)
        if jg is None:
            continue
        for v in o.data.vertices:
            w = next((g.weight for g in v.groups if g.group == jg.index), 0.0)
            if w > 0 and pg is not None:
                pg.add([v.index], next((g.weight for g in v.groups if g.group == pg.index), 0.0) + w, "REPLACE")
        o.vertex_groups.remove(jg)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    arm.data.edit_bones.remove(arm.data.edit_bones["jaw"])
    bpy.ops.object.mode_set(mode="OBJECT")

W = arm.matrix_world
P = arm.pose.bones
bones = {b.name for b in arm.data.bones}
chain = lambda pre: sorted((n for n in bones if n.startswith(pre)), key=lambda n: len(arm.data.bones[n].parent_recursive))  # noqa: E731
pos = lambda n, tail=False: W @ (P[n].tail if tail else P[n].head)  # noqa: E731
body = [n for n in ("hips",) if n in bones] + chain("spine") + chain("chest") + chain("neck") + [n for n in ("head", "snout") if n in bones]
hips = body[0]
up = Vector((0, 0, 1))
front = pos("chest") if "chest" in bones else pos(body[-1])
fwd = Vector((front.x - pos(hips).x, front.y - pos(hips).y, 0)).normalized()
lat = fwd.cross(up).normalized()   # the creature's right
cx = pos(hips)   # the middle plane goes through the hips, along fwd
turned = {}


def turn(n, q, about):
    """bone n (and everything below it) turned by q about the world point about"""
    m = W.inverted() @ Matrix.Translation(about) @ q.to_matrix().to_4x4() @ Matrix.Translation(-about) @ W @ P[n].matrix
    P[n].matrix = m
    bpy.context.view_layer.update()
    turned[n] = round(turned.get(n, 0.0) + math.degrees(q.angle), 1)


def aim(n, d_new):
    """bone n turned about its head so it points along d_new (the least turn)"""
    h, t = pos(n), pos(n, True)
    d = (t - h)
    if d.length < 1e-6 or d_new.length < 1e-6:
        return
    q = d.normalized().rotation_difference(d_new.normalized())
    if q.angle > math.radians(0.2):
        turn(n, q, h)


# ---- the middle line: every bone of the body and the tail without a sideways part (seen from above and the front)
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")
for n in body[1:] + chain("tail"):
    d = pos(n, True) - pos(n)
    aim(n, d - lat * d.dot(lat))
# the body bones' heads off the middle plane (a spine bent sideways at its first joint): their roots back onto it is
# what the turns above did along the chain; the hips' own tail too
d = pos(hips, True) - pos(hips)
aim(hips, d - lat * d.dot(lat))

# ---- the legs: each turned at its upper joint (the second bone: the first is the shoulder blade / the hip's own)
# about the body's forward line so its paw is right under that joint across, then the pair's paws as far forward of
# their joints as each other (their mean), turned about the across line
legs = {}
for k in ("FL", "FR", "BL", "BR"):
    c = chain(f"leg_{k}_")
    if c:
        legs[k] = c
for k, c in legs.items():
    j = c[1] if len(c) >= 3 else c[0]
    root, paw = pos(j), pos(c[-1], True)
    v = paw - root
    a = math.atan2(v.dot(lat), -v.dot(up))   # the splay: the paw's way out from straight down, about fwd
    turn(j, Matrix.Rotation(a, 4, fwd).to_quaternion(), root)   # (about fwd: down -> down + lat * sin)
for pair in (("FL", "FR"), ("BL", "BR")):
    if not all(k in legs for k in pair):
        continue
    reach = {}
    for k in pair:
        c = legs[k]
        j = c[1] if len(c) >= 3 else c[0]
        reach[k] = (j, pos(j), pos(c[-1], True))
    mean = sum((p - r).dot(fwd) for _, r, p in reach.values()) / 2
    for k, (j, r, p) in reach.items():
        v = p - r
        down = -v.dot(up)
        a = math.atan2(v.dot(fwd), down) - math.atan2(mean, down)
        turn(j, Matrix.Rotation(-a, 4, lat).to_quaternion(), r)   # (about lat: down -> down + fwd * sin)

head0 = W @ arm.data.bones["head"].matrix_local if "head" in bones else Matrix.Identity(4)
head1 = W @ P["head"].matrix if "head" in bones else Matrix.Identity(4)
bpy.ops.object.mode_set(mode="OBJECT")

# ---- the pose made the rest: the skin deformed by its weights, the skeleton's rest set to the pose
for o in meshes:
    bpy.context.view_layer.objects.active = o
    mod = next(m for m in o.modifiers if m.type == "ARMATURE")
    name = mod.name
    bpy.ops.object.modifier_apply(modifier=name)
    m = o.modifiers.new("Armature", "ARMATURE")
    m.object = arm
bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")
bpy.ops.pose.select_all(action="SELECT")
bpy.ops.pose.armature_apply(selected=False)
bpy.ops.object.mode_set(mode="OBJECT")
bpy.ops.object.select_all(action="DESELECT")
for o in [arm] + meshes:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False)
print("STRAIGHTEN_OK " + json.dumps({"head": [list(r) for r in (head1 @ head0.inverted())], "turned": turned}))
