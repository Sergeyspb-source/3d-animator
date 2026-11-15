"""Runs INSIDE Blender (background): a creature's rest pose straightened - the paws under their shoulders and hips (no
splay to the sides), each pair level front to back, the spine, the neck, the head and the tail on the middle line -
and that pose made the rest: the skin deformed by its own weights, the skeleton's rest set to it.

    blender -b -P blender_creature_straighten.py -- job.json

job.json: {"src": the creature's skeleton before its jaw (<name>_auto.glb; a jaw there goes back to its parent), "out":
GLB, "names": {UniRig's name: readable} (the passport's), "pose": {bone: [x, y, z, w]} (optional: the pose set by hand in
the skeleton viewer - each bone's turn in the world from its rest, glTF axes - made the rest instead of the straightening)}.
A model made in a crouch or a stride keeps its bends seen from the side; what goes are the splay and the twist seen from
above and the front, which clips counted from the rest put into every frame (a splayed hind leg walked splayed).
Prints STRAIGHTEN_OK {"head": 4x4 world change of the head (the mouth's marks move with it), "turned": {bone: degrees}}.
"""
import json
import math
import sys
from pathlib import Path

import bpy
from mathutils import Matrix, Quaternion, Vector

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


bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="POSE")
if job.get("pose"):   # the pose set by hand: each bone's world turn (glTF -> Blender: (x, y, z) -> (x, -z, y))
    A = Matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))
    order = []

    def walk(b):
        order.append(b.name)
        for c in b.children:
            walk(c)

    for b in arm.data.bones:
        if b.parent is None:
            walk(b)
    for n in order:
        q = job["pose"].get(n)
        if not q:
            continue
        D = A @ Quaternion((q[3], q[0], q[1], q[2])).to_matrix() @ A.transposed()
        rest = (W @ arm.data.bones[n].matrix_local).to_3x3().normalized()
        head = pos(n)
        P[n].matrix = W.inverted() @ (Matrix.Translation(head) @ (D @ rest).to_4x4())
        bpy.context.view_layer.update()
        ang = round(math.degrees(D.to_quaternion().angle), 1)
        if ang > 0.2:
            turned[n] = ang
    body_done = True
else:
    body_done = False
# ---- the middle line: every bone of the body and the tail without a sideways part (seen from above and the front)
for n in ([] if body_done else body[1:] + chain("tail")):
    d = pos(n, True) - pos(n)
    aim(n, d - lat * d.dot(lat))
# the body bones' heads off the middle plane (a spine bent sideways at its first joint): their roots back onto it is
# what the turns above did along the chain; the hips' own tail too
if not body_done:
    d = pos(hips, True) - pos(hips)
    aim(hips, d - lat * d.dot(lat))

# ---- the paws' bottoms: the lowest point of the skin each leg's last bone leads, as the pose has it now
lead = {}
for o in meshes:
    names = {g.index: g.name for g in o.vertex_groups}
    lead[o] = [names[max(v.groups, key=lambda g: g.weight).group] if v.groups else None for v in o.data.vertices]


def bottoms(tips):
    dg = bpy.context.evaluated_depsgraph_get()
    out = {}
    for o in meshes:
        ev = o.evaluated_get(dg)
        m = ev.to_mesh()
        for v, n in zip(m.vertices, lead[o]):
            if n in tips:
                z = (o.matrix_world @ v.co).z
                out[n] = min(out.get(n, z), z)
        ev.to_mesh_clear()
    return out


size = max((W @ b.head_local - W @ arm.data.bones[hips].head_local).length for b in arm.data.bones) or 1.0
tips = {chain(f"leg_{k}_")[-1] for k in ("FL", "FR", "BL", "BR") if chain(f"leg_{k}_")}
before = bottoms(tips)
floor0 = min(before.values()) if before else 0.0   # the ground: the lowest paw as the model stands


def rot(n, ang):   # bone n (and what is below it) turned about the across line through its head (not counted)
    h = pos(n)
    P[n].matrix = W.inverted() @ Matrix.Translation(h) @ Matrix.Rotation(ang, 4, lat) @ Matrix.Translation(-h) @ W @ P[n].matrix
    bpy.context.view_layer.update()


# ---- the legs: each turned at its upper joint (the second bone: the first is the shoulder blade / the hip's own)
# about the body's forward line so its paw is right under that joint across, then the pair's paws as far forward of
# their joints as each other (their mean), turned about the across line
legs = {}
for k in ("FL", "FR", "BL", "BR"):
    c = chain(f"leg_{k}_")
    if c and not body_done:
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

# every paw back on the ground (a splayed leg stood straight reaches lower: its paw went under the floor, the others
# seemed to hang over it): its knee and its upper joint turned about the across line - the paw's joint to the height
# that puts its bottom on the floor, as far forward as it is - and the paw turned back as it was (flat)
for k, c in legs.items():
    if len(c) < 4:
        continue
    j1, j2, last = c[1], c[2], c[-1]
    total = 0.0
    for it in range(3):   # (the bottom measured again: the paw's own turn moves it a little)
        drop = floor0 - bottoms({last}).get(last, floor0)
        if abs(drop) < 1e-3 * size:
            break
        J0 = pos(last)
        zt, ft = J0.z + drop, J0.dot(fwd)
        for _ in range(12):
            J = pos(last)
            e1, e2 = zt - J.z, ft - J.dot(fwd)
            if math.hypot(e1, e2) < 2e-4 * size:
                break
            h = math.radians(1.0)
            cols = []
            for jj in (j1, j2):
                rot(jj, h)
                Jp = pos(last)
                rot(jj, -h)
                cols.append(((Jp.z - J.z) / h, (Jp.dot(fwd) - J.dot(fwd)) / h))
            (a, cc), (b, d) = cols   # [[a, b], [cc, d]] · [x1, x2] = [e1, e2]
            det = a * d - b * cc
            if abs(det) < 1e-9:
                break
            x1 = max(-0.17, min(0.17, (e1 * d - b * e2) / det))
            x2 = max(-0.17, min(0.17, (a * e2 - cc * e1) / det))
            rot(j1, x1)
            rot(j2, x2)
            total += x1 + x2
            turned[j2] = round(turned.get(j2, 0.0) + abs(math.degrees(x2)), 1)
        rot(last, -total)   # the paw flat again
        total = 0.0
# the ground at zero: the whole lowered (or raised) by the lowest paw's bottom
after = bottoms(tips)
lift = -(min(after.values()) if after else floor0)
if abs(lift) > 1e-5:
    P[hips].matrix = W.inverted() @ Matrix.Translation((0, 0, lift)) @ W @ P[hips].matrix
    bpy.context.view_layer.update()
paws = {k: round((v + lift) * 1000) for k, v in bottoms(tips).items()}

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
print("STRAIGHTEN_OK " + json.dumps({"head": [list(r) for r in (head1 @ head0.inverted())], "turned": turned, "paws_mm": paws,
                                     "lift_mm": round(lift * 1000)}))
