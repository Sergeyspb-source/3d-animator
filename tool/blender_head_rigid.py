"""Runs INSIDE Blender (background): a creature's head moved by its Head bone as one piece.

    blender -b -P blender_head_rigid.py -- rigged.glb out.glb centre=x,y,z radii=rx,ry_front,ry_back,rz_up,rz_down
        [core=0.85] [edge=1.2] [paint=prefix]

Heat weights on a hunched creature (the head low between big shoulders) give the face a mix of the shoulders and the
head: when a clip turns the head the face hardly follows, and eyes weighted to Head slide off it (2026-11-18, the user
on the D-rank nurgle: «с привязкой глаз тут явная проблема»). Inside an ellipsoid round the head (`centre`, world units
of the file; separate radii forward/back in y and up/down in z) the body's weight goes over to Head: fully within
`core` (normalised distance), blending back to the old weights by `edge` (the neck, the mane's root). What a vertex had
on a jaw bone stays on it. The eye meshes are left as they are (100 % Head). With `paint` it renders the new Head
weight (red), shoulders (blue), neck (green) from the front and the side. Prints HEAD_ lines.
"""
import sys

import bpy
import numpy as np
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
C = np.array([float(x) for x in opt["centre"].split(",")])
RX, RYF, RYB, RZU, RZD = [float(x) for x in opt["radii"].split(",")]
CORE = float(opt.get("core", 0.85))
EDGE = float(opt.get("edge", 1.2))

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
bones = [b.name for b in arm.data.bones]
head = next(b for b in bones if b.endswith("Head"))
jaws = [b for b in bones if "jaw" in b.lower()]
body = max((o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups), key=lambda o: len(o.data.vertices))
m = body.data
P = np.array([tuple(body.matrix_world @ v.co) for v in m.vertices])
d = P - C
ny = np.where(d[:, 1] < 0.0, d[:, 1] / RYF, d[:, 1] / RYB)
nz = np.where(d[:, 2] > 0.0, d[:, 2] / RZU, d[:, 2] / RZD)
dist = np.sqrt((d[:, 0] / RX) ** 2 + ny ** 2 + nz ** 2)
t = np.clip((EDGE - dist) / (EDGE - CORE), 0.0, 1.0)
t = t * t * (3.0 - 2.0 * t)
if head not in body.vertex_groups:
    body.vertex_groups.new(name=head)
gi = {g.name: g.index for g in body.vertex_groups}
changed = 0
for i in np.flatnonzero(t > 0.0):
    v = m.vertices[int(i)]
    old = {body.vertex_groups[g.group].name: g.weight for g in v.groups if body.vertex_groups[g.group].name in bones}
    total = sum(old.values()) or 1.0
    old = {k: w / total for k, w in old.items()}
    jaw = sum(old.get(j, 0.0) for j in jaws)
    new = {k: w * (1.0 - t[i]) for k, w in old.items()}
    for j in jaws:                                                # the jaw keeps its share
        if j in old:
            new[j] = old[j]
    new[head] = new.get(head, 0.0) + t[i] * (1.0 - jaw)
    s = sum(new.values())
    for g in list(v.groups):
        body.vertex_groups[g.group].remove([int(i)])
    for k, w in new.items():
        if w / s > 0.001:
            body.vertex_groups[gi[k]].add([int(i)], w / s, "REPLACE")
    changed += 1
print("HEAD_WEIGHTS", body.name, "head", head, "jaws", jaws, "changed", changed, "rigid", int((t >= 0.999).sum()))

if "paint" in opt:
    def weight(v, key):
        return sum(g.weight for g in v.groups if key in body.vertex_groups[g.group].name)
    cols = np.array([[min(1.0, weight(v, "Head") + weight(v, "jaw")), weight(v, "Neck"), weight(v, "Shoulder"), 1.0] for v in m.vertices], np.float32)
    ca = m.color_attributes.new("w", "FLOAT_COLOR", "POINT")
    ca.data.foreach_set("color", cols.ravel())
    mat = bpy.data.materials.new("w")
    mat.use_nodes = True
    nt = mat.node_tree
    bsdf = next(x for x in nt.nodes if x.type == "BSDF_PRINCIPLED")
    vc = nt.nodes.new("ShaderNodeVertexColor")
    vc.layer_name = "w"
    nt.links.new(vc.outputs["Color"], bsdf.inputs["Base Color"])
    keep = [s.material for s in body.material_slots]
    body.data.materials.clear()
    body.data.materials.append(mat)
    scn = bpy.context.scene
    scn.render.engine = "BLENDER_EEVEE"
    scn.render.resolution_x, scn.render.resolution_y = 600, 600
    world = bpy.data.worlds.new("w")
    scn.world = world
    world.color = (0.9, 0.9, 0.9)
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    scn.collection.objects.link(sun)
    sun.rotation_euler = (0.6, 0.0, 0.3)
    sun.data.energy = 3
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    scn.collection.objects.link(cam)
    scn.camera = cam
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = 40
    centre = Vector((0.0, C[1], C[2] - 6.0))
    for name, dv in [("front", Vector((0, -1, 0))), ("side", Vector((1, 0, 0))), ("back", Vector((0.3, 1, 0.2)).normalized())]:
        cam.location = centre + dv * 150
        cam.rotation_euler = (-dv).to_track_quat("-Z", "Y").to_euler()
        scn.render.filepath = opt["paint"] + "_" + name + ".png"
        bpy.ops.render.render(write_still=True)
    body.data.materials.clear()
    for mt in keep:
        body.data.materials.append(mt)
    m.color_attributes.remove(m.color_attributes["w"])
    for o in [sun, cam]:
        bpy.data.objects.remove(o, do_unlink=True)

bpy.ops.object.select_all(action="DESELECT")
for o in bpy.context.scene.objects:
    if o.type in ("MESH", "ARMATURE"):
        o.select_set(True)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=len(bpy.data.actions) > 0)
print("HEAD_OK", dst)
