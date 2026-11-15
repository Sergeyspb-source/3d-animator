"""Runs INSIDE Blender (background): a creature's skeleton moved to its edited markup and skinned again.

    blender -b -P blender_creature_rebuild.py -- job.json

job.json: {"src": the creature's skeleton before its jaw (<name>_auto.glb, or <name>_rigged.glb: its jaw goes), "out": GLB,
"names": {UniRig's name: the readable one} (the passport's: <name>_auto.glb keeps UniRig's names; the output is named),
"joints": {bone: [x, y, z]} (glTF world: Y up, the creature looking along +Z), "ends": {bone: [x, y, z]} (where a bone
with no child points: a paw's tip, the tail's end, the muzzle), "reweight": "local" | "all" | "none"}.
Every bone's head goes to its joint; its tail to its main child's joint (the chain it continues: spine_02 after
spine_01, the head after the chest) or, at a tip, to its end. The jaw bone, if there is one, goes with its weights
given back to its parent: blender_creature_finish.py makes it again from the mouth's marks. reweight: "local" - heat
weights (blender_heat.proxy_heat) only where a moved bone, its parent or a child leads the skin (before or after),
the old ones kept elsewhere (a furry creature's heat weights gave the shoulders' first bones the mane above: UniRig's
were neater there, and a snout moved has nothing to do with the paws); "all" - heat weights everywhere; "none" - the old
ones kept (a joint moved far then bends the skin where its old weights end). Prints REBUILD_OK {report}.
"""
import json
import re
import sys
from pathlib import Path

import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
import blender_heat  # noqa: E402

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=job["src"])
scene = bpy.context.scene
arm = next(o for o in scene.objects if o.type == "ARMATURE")
meshes = [o for o in scene.objects if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
for o in list(scene.objects):   # (the importer's own icosphere: the bones' display shape)
    if o.type == "MESH" and o not in meshes:
        bpy.data.objects.remove(o, do_unlink=True)
bl = lambda p: Vector((p[0], -p[2], p[1]))  # noqa: E731  glTF (x, y, z) -> Blender (x, -z, y)
joints, ends = job.get("joints", {}), job.get("ends", {})
report = {"moved": 0}
for b in arm.data.bones:   # the readable names first: the markup speaks them (the vertex groups follow)
    new = job.get("names", {}).get(b.name)
    if new and new != b.name:
        old = b.name
        b.name = new
        for o in meshes:
            g = o.vertex_groups.get(old)
            if g:
                g.name = new

# ---- the jaw goes (its weights back to its parent)
if "jaw" in arm.data.bones:
    parent = arm.data.bones["jaw"].parent.name if arm.data.bones["jaw"].parent else None
    for o in meshes:
        jg = o.vertex_groups.get("jaw")
        if jg is None:
            continue
        pg = o.vertex_groups.get(parent) or (o.vertex_groups.new(name=parent) if parent else None)
        for v in o.data.vertices:
            w = next((g.weight for g in v.groups if g.group == jg.index), 0.0)
            if w > 0 and pg is not None:
                old = next((g.weight for g in v.groups if g.group == pg.index), 0.0)
                pg.add([v.index], old + w, "REPLACE")
        o.vertex_groups.remove(jg)
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    arm.data.edit_bones.remove(arm.data.edit_bones["jaw"])
    bpy.ops.object.mode_set(mode="OBJECT")
    report["jaw_removed"] = True


def main_child(eb):
    """the child a bone's line goes on to: one of the same chain (spine_02 after spine_01, leg_FL_3 after leg_FL_2),
    else the body's line (spine, chest, neck, head, snout), else the first"""
    kids = list(eb.children)
    if len(kids) <= 1:
        return kids[0] if kids else None
    base = re.sub(r"_?\d+$", "", eb.name)
    for c in kids:
        if re.sub(r"_?\d+$", "", c.name) == base:
            return c
    for pref in ("spine", "chest", "neck", "head", "snout", "tail"):
        for c in kids:
            if c.name.startswith(pref):
                return c
    return kids[0]


bpy.context.view_layer.objects.active = arm
bpy.ops.object.mode_set(mode="EDIT")
inv = arm.matrix_world.inverted()
ebs = arm.data.edit_bones
old = {eb.name: (eb.head.copy(), eb.tail.copy(), eb.roll) for eb in ebs}
size = max((eb.head - ebs[0].head).length for eb in ebs) or 1.0
for eb in ebs:
    eb.use_connect = False
moved = set()
for eb in ebs:
    if eb.name in joints:
        eb.head = inv @ bl(joints[eb.name])
        if (eb.head - old[eb.name][0]).length > 0.002 * size:
            moved.add(eb.name)
for eb in ebs:
    h0, t0, roll = old[eb.name]
    kid = main_child(eb)
    if kid is not None:
        tail = kid.head.copy()
    elif eb.name in ends:
        tail = inv @ bl(ends[eb.name])
    else:   # a tip without an end: its old way and length from its new head
        tail = eb.head + (t0 - h0)
    if (tail - eb.head).length < 1e-4 * size:
        tail = eb.head + (t0 - h0).normalized() * max((t0 - h0).length, 0.01 * size)
    if kid is None and ((tail - eb.head) - (t0 - h0)).length > 0.002 * size:   # (a tip's end moved: its reach)
        moved.add(eb.name)
    eb.tail = tail
    eb.roll = roll
near = set(moved)   # the moved bones and the ones they meet: their skin is weighted again
for eb in ebs:
    if eb.name in moved:
        if eb.parent:
            near.add(eb.parent.name)
        near.update(c.name for c in eb.children)
bpy.ops.object.mode_set(mode="OBJECT")
report["moved"] = len(moved)

mode = job.get("reweight", "local")
mode = {True: "local", False: "none"}.get(mode, mode)
if mode in ("local", "all") and (moved or mode == "all"):
    before = [[{o.vertex_groups[g.group].name: g.weight for g in v.groups if g.weight > 0} for v in o.data.vertices] for o in meshes]
    report.update(blender_heat.proxy_heat(meshes, arm, smooth=int(job.get("smooth", 6))))
    if mode == "local":   # the heat's weights only where the moved bones (or the ones they meet) lead the skin
        kept = 0
        for o, old_w in zip(meshes, before):
            for v, ow in zip(o.data.vertices, old_w):
                nw = {o.vertex_groups[g.group].name: g.weight for g in v.groups if g.weight > 0}
                lead = lambda d: max(d, key=d.get) if d else None  # noqa: E731
                if not ow:
                    continue
                if lead(ow) in near or lead(nw) in near:
                    # weighted again - but only by the bones round the moved ones or its own before (heat gave a
                    # wolf's mane behind its head to the front paw's first bone)
                    allow = near | set(ow)
                    fw = {n: w for n, w in nw.items() if n in allow}
                    if fw:
                        if len(fw) < len(nw):
                            tot = sum(fw.values())
                            for g in list(v.groups):
                                o.vertex_groups[g.group].remove([v.index])
                            for n, w in fw.items():
                                o.vertex_groups[n].add([v.index], w / tot, "REPLACE")
                        continue
                for g in list(v.groups):
                    o.vertex_groups[g.group].remove([v.index])
                for n, w in ow.items():
                    (o.vertex_groups.get(n) or o.vertex_groups.new(name=n)).add([v.index], w, "REPLACE")
                kept += 1
        report["kept_old"] = kept
else:
    report["kept_weights"] = True
report["reweight"] = mode

bpy.ops.object.select_all(action="DESELECT")
for o in [arm] + meshes:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=job["out"], export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False)
print("REBUILD_OK " + json.dumps(report))
