"""Imported by Blender scripts (tool/ on sys.path): skin meshes to a rig with Blender's heat weights on a welded proxy -
the landmark rig's way (blender_landmark_rig.py does the same inline). Tripo / Hunyuan models come in parts split
along seams and heat fails on many separate open parts and on small models, so: copies of all the meshes joined,
the seams welded, scaled to ~10 units, heat-weighted against a scaled copy of the rig, smoothed along the surface,
and the weights copied back to every original vertex from the nearest proxy vertex. What heat leaves unweighted (holes,
self-intersections) takes the two nearest bones by distance. 4 influences, normalised.
"""
import bpy
from mathutils import Matrix, Vector
from mathutils.kdtree import KDTree


def _seg_dist(p, a, c):
    ab = c - a
    t = max(0.0, min(1.0, (p - a).dot(ab) / max(ab.length_squared, 1e-12)))
    return (p - (a + ab * t)).length


def proxy_heat(meshes, rig, skip=(), smooth=6, size="height"):
    """meshes: the skinned meshes (their vertex groups are replaced); rig: their armature object; skip: bone names that
    get no heat weights (set later by other rules); size: what is brought to ~10 units - "height", or "max" (the
    largest side: a snake lying flat is long and low). Returns a report {proxy_vertices, heat_failed, fallback_vertices}."""
    scene = bpy.context.scene
    corners = [o.matrix_world @ Vector(c) for o in meshes for c in o.bound_box]
    sides = [max(p[i] for p in corners) - min(p[i] for p in corners) for i in range(3)]
    height = max(sides) if size == "max" else sides[2]
    scale = 10.0 / max(height, 1e-6)
    if bpy.context.object and bpy.context.object.mode != "OBJECT":
        bpy.ops.object.mode_set(mode="OBJECT")
    bpy.ops.object.select_all(action="DESELECT")
    copies = []
    for o in meshes:
        c = o.copy()
        c.data = o.data.copy()
        scene.collection.objects.link(c)
        c.parent = None
        c.matrix_world = o.matrix_world.copy()
        c.modifiers.clear()
        c.vertex_groups.clear()
        c.select_set(True)
        copies.append(c)
    bpy.context.view_layer.objects.active = copies[0]
    if len(copies) > 1:
        bpy.ops.object.join()
    proxy = bpy.context.view_layer.objects.active
    proxy.data.materials.clear()
    proxy.matrix_world = Matrix.Scale(scale, 4) @ proxy.matrix_world
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bpy.ops.object.mode_set(mode="EDIT")
    bpy.ops.mesh.select_all(action="SELECT")
    bpy.ops.mesh.remove_doubles(threshold=0.005)   # 0.05 % of the height
    bpy.ops.object.mode_set(mode="OBJECT")
    prig = rig.copy()
    prig.data = rig.data.copy()
    scene.collection.objects.link(prig)
    prig.matrix_world = Matrix.Scale(scale, 4) @ rig.matrix_world
    bpy.ops.object.select_all(action="DESELECT")
    prig.select_set(True)
    bpy.context.view_layer.objects.active = prig
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    for name in skip:
        if name in prig.data.bones:
            prig.data.bones[name].use_deform = False
    bpy.ops.object.select_all(action="DESELECT")
    proxy.select_set(True)
    prig.select_set(True)
    bpy.context.view_layer.objects.active = prig
    bpy.ops.object.parent_set(type="ARMATURE_AUTO")
    if smooth:   # heat weights change sharply at the shoulders and hips: a few passes along the surface
        bpy.ops.object.select_all(action="DESELECT")
        proxy.select_set(True)
        bpy.context.view_layer.objects.active = proxy
        bpy.ops.object.mode_set(mode="WEIGHT_PAINT")
        bpy.ops.object.vertex_group_smooth(group_select_mode="ALL", factor=0.5, repeat=smooth)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
        bpy.ops.object.mode_set(mode="OBJECT")
    pv = proxy.data.vertices
    tree = KDTree(len(pv))
    for v in pv:
        tree.insert(v.co, v.index)
    tree.balance()
    pnames = {g.index: g.name for g in proxy.vertex_groups}
    failed = sum(1 for v in pv if not any(g.weight > 1e-4 for g in v.groups))
    deform = [b for b in rig.data.bones if b.use_deform and b.name not in skip]
    segs = [(b.name, rig.matrix_world @ b.head_local, rig.matrix_world @ b.tail_local) for b in deform]
    fallback = 0
    for o in meshes:
        o.vertex_groups.clear()
        for b in rig.data.bones:
            o.vertex_groups.new(name=b.name)
        mw = o.matrix_world
        for v in o.data.vertices:
            p = mw @ v.co
            _, j, _ = tree.find(p * scale)
            got = False
            for g in pv[j].groups:
                if g.weight > 1e-4:
                    o.vertex_groups[pnames[g.group]].add([v.index], g.weight, "REPLACE")
                    got = True
            if not got:   # heat left it out: the two nearest bones by distance
                d = sorted((_seg_dist(p, a, c), n) for n, a, c in segs)[:2]
                w = [1.0 / max(x, 1e-4) ** 4 for x, _ in d]
                for (_, n), wi in zip(d, w):
                    o.vertex_groups[n].add([v.index], wi / sum(w), "REPLACE")
                fallback += 1
        bpy.ops.object.select_all(action="DESELECT")
        o.select_set(True)
        bpy.context.view_layer.objects.active = o
        bpy.ops.object.vertex_group_limit_total(group_select_mode="ALL", limit=4)
        bpy.ops.object.vertex_group_normalize_all(group_select_mode="ALL", lock_active=False)
    for ob in (proxy, prig):
        bpy.data.objects.remove(ob, do_unlink=True)
    return {"proxy_vertices": len(pv), "heat_failed": failed, "fallback_vertices": fallback}
