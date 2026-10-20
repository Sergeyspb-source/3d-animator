"""Runs INSIDE Blender (background): describe a rigged GLB and render rest + posed views.

    blender -b -P blender_rig_inspect.py -- rigged.glb out_dir

Prints the bone tree (name, parent, head position in metres, Z up), skin statistics, and writes
out_dir/rest.png, out_dir/posed.png (arms raised, one leg lifted) with bones drawn as lines.
"""
import math
import sys

import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
glb, out = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=glb)
scene = bpy.context.scene
bpy.context.view_layer.update()  # world matrices are stale right after import
arm = next((o for o in scene.objects if o.type == "ARMATURE"), None)
meshes = [o for o in scene.objects if o.type == "MESH" and o.vertex_groups]  # not the bone-shape Icosphere
if arm is None:
    print("RIG_INFO no armature")
    raise SystemExit

bones = arm.data.bones
roots = [b for b in bones if b.parent is None]
print(f"RIG_INFO bones={len(bones)} roots={[b.name for b in roots]} meshes={len(meshes)}")


def depth(b):
    d = 0
    while b.parent:
        b, d = b.parent, d + 1
    return d


mat = arm.matrix_world
for b in bones:
    h = mat @ b.head_local
    if len(bones) <= 80 or depth(b) <= 6:
        print(f"RIG_BONE {'  ' * depth(b)}{b.name} ({h.x:+.2f},{h.y:+.2f},{h.z:+.2f}) children={len(b.children)}")

# skin statistics
tot = bad = 0
for m in meshes:
    names = {vg.index: vg.name for vg in m.vertex_groups}
    for v in m.data.vertices:
        s = sum(g.weight for g in v.groups)
        tot += 1
        bad += (s < 0.99 or s > 1.01)
print(f"RIG_SKIN vertices={tot} not_normalised={bad} vertex_groups={sum(len(m.vertex_groups) for m in meshes)}")

# ---- render helpers
allv = [m.matrix_world @ v.co for m in meshes for v in list(m.data.vertices)[::25]]
lo = Vector((min(p.x for p in allv), min(p.y for p in allv), min(p.z for p in allv)))
hi = Vector((max(p.x for p in allv), max(p.y for p in allv), max(p.z for p in allv)))
center, size = (lo + hi) / 2, max(hi - lo)
size0 = size
if len(argv) >= 5:  # close-up: blender ... -- rigged.glb out_dir - - <bone name> (camera looks at that bone)
    fb = arm.pose.bones.get(argv[4])
    if fb is not None:
        center = arm.matrix_world @ fb.head
        size = size * 0.22
        for m in meshes:  # see-through skin so the bones inside are visible
            for slot in m.material_slots:
                mt = slot.material
                if mt and mt.use_nodes:
                    for n in mt.node_tree.nodes:
                        if n.type == "BSDF_PRINCIPLED":
                            n.inputs["Alpha"].default_value = 0.22
                    try:
                        mt.surface_render_method = "BLENDED"
                    except Exception:  # noqa: BLE001
                        pass
r = scene.render
r.resolution_x, r.resolution_y = 640, 640
try:
    r.engine = "BLENDER_EEVEE"
except TypeError:
    r.engine = "BLENDER_WORKBENCH"
scene.view_settings.view_transform = "Standard"
world = bpy.data.worlds.new("w")
scene.world = world
world.use_nodes = True
bg = next(n for n in world.node_tree.nodes if n.type == "BACKGROUND")
bg.inputs["Color"].default_value = (0.85, 0.85, 0.87, 1)
sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
sun.data.energy = 3.0
sun.rotation_euler = (math.radians(50), 0, math.radians(35))
scene.collection.objects.link(sun)
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
cam.data.type = "ORTHO"
cam.data.ortho_scale = size * 1.2
scene.collection.objects.link(cam)
scene.camera = cam
cam.location = center + Vector((0, -size * 3, 0))
cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()

# bones as thin cylinders so they show up in the render
mat_bone = bpy.data.materials.new("bone")
mat_bone.diffuse_color = (1, 0.1, 0.1, 1)
mat_bone.use_nodes = True
mat_bone.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (1, 0.1, 0.1, 1)
mat_bone.node_tree.nodes["Principled BSDF"].inputs["Emission Color"].default_value = (1, 0.1, 0.1, 1)
mat_bone.node_tree.nodes["Principled BSDF"].inputs["Emission Strength"].default_value = 2.0
bone_objs = []


def draw_bones():
    for o in bone_objs:
        bpy.data.objects.remove(o, do_unlink=True)
    bone_objs.clear()
    for pb in arm.pose.bones:
        a, b = arm.matrix_world @ pb.head, arm.matrix_world @ pb.tail
        if (b - a).length < 1e-4:
            continue
        bpy.ops.mesh.primitive_cylinder_add(radius=size0 * 0.0016, depth=(b - a).length, location=(a + b) / 2)
        o = bpy.context.active_object
        o.rotation_euler = (b - a).to_track_quat("Z", "Y").to_euler()
        o.data.materials.append(mat_bone)
        o.display_type = "SOLID"
        bone_objs.append(o)
    bpy.context.view_layer.update()


def render(path, with_bones):
    for o in bone_objs:
        o.hide_render = not with_bones
    r.filepath = path
    bpy.ops.render.render(write_still=True)


def look_from(direction):
    cam.location = center + Vector(direction).normalized() * size * 3
    cam.rotation_euler = (center - cam.location).to_track_quat("-Z", "Y").to_euler()


def rotate_world(pb, axis, deg):
    """Rotate a pose bone around its own head, about a WORLD axis ('X' side-to-side, 'Y' depth)."""
    from mathutils import Matrix

    A = arm.matrix_world
    head = A @ pb.head
    R = Matrix.Translation(head) @ Matrix.Rotation(math.radians(deg), 4, axis) @ Matrix.Translation(-head)
    pb.matrix = A.inverted() @ R @ A @ pb.matrix
    bpy.context.view_layer.update()


draw_bones()
look_from((0, -1, 0))
render(f"{out}/rest.png", True)

# ---- pose test (roles taken from the bone tree, not from names):
# leg = chain from the root that goes down; arm = side branch of the chest bone (first bone after the clavicle).
def tip_z(b):
    return (arm.matrix_world @ b.tail).z - (arm.matrix_world @ b.head).z


root = roots[0]
W = arm.matrix_world


def wz(b):
    return (W @ b.head).z


def wx(b):
    return (W @ b.head).x


# hips: root children that sit off-centre and have a chain below them
legs = [c for c in root.children if c.children and abs(wx(c)) > 0.02 * size]
arms_ = []
branching = [b for b in bones if len(b.children) >= 3 and b is not root]
chest_bones = [max(branching, key=wz)] if branching else []  # highest 3-way branch = chest
for b in chest_bones:
    if True:
        for c in b.children:
            hx = (arm.matrix_world @ c.head).x
            if abs(hx) > 0.02 * size and c.children:
                arms_.append(c.children[0])  # first bone after the clavicle = upper arm
if len(argv) >= 4:  # explicit override: blender ... -- rigged.glb out_dir arm1,arm2 leg1
    def _b(n):  # Blender may turn ':' into '_' or '.' in bone names
        for cand in (n, n.replace(":", "_"), n.replace(":", ".")):
            if cand in bones:
                return bones[cand]
        return None

    arms_ = [b for b in map(_b, argv[2].split(",")) if b]
    legs = [b for b in map(_b, argv[3].split(",")) if b]
print("RIG_POSE arms:", [a.name for a in arms_], " legs:", [l.name for l in legs])
for b in arms_:
    side = 1 if (arm.matrix_world @ b.head).x > 0 else -1
    rotate_world(arm.pose.bones[b.name], "Y", -80 * side)  # raise the arm sideways
if legs:
    rotate_world(arm.pose.bones[legs[0].name], "X", -70)  # swing one leg forward (-Y is forward)
draw_bones()
look_from((0, -1, 0))
render(f"{out}/posed_front.png", False)
look_from((1 if (arm.matrix_world @ legs[0].head).x > 0 else -1, 0, 0) if legs else (1, 0, 0))
render(f"{out}/posed_side.png", False)
print("RIG_RENDER_OK")
