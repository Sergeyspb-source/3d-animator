"""Runs INSIDE Blender (background): finish an auto-rigged creature: readable bone names and a jaw.

    blender -b -P blender_creature_finish.py -- rigged.glb out.glb [names=old:new,old:new,...]
            [jaw_front=y,z] [jaw_corner=y,z] [hinge=y,z] [chin=y,z] [jaw_parent=head] [preview=path.png]
            [angles=0,30] [tags=0,30] [paint=path.json: {"plus"/"minus": [[x, y, z] glTF]} - painted by hand]

Bone names: given pairs are applied as they are (vertex groups follow).
Jaw (Blender coordinates, the creature looking along -Y): the mouth line runs from jaw_front (tip of the lower
jaw, between the lips) to jaw_corner (corner of the mouth) and on to the hinge. Head vertices below that line
belong to the new bone "jaw" (optional jaw_tip=y,z: the line in front of the lower jaw, under the nose) (child of jaw_parent, pivot at the hinge, pointing to the chin: chin=y,z, else jaw_front); the weight fades out
over the last centimetres before the hinge so the cheeks stretch instead of tearing. Loose pieces (teeth, fangs)
go whole to the jaw or stay with the skull by their centre. preview renders the jaw at each of angles (degrees about
the bone's X, + opens), files <preview>_<tag>_<side|front>.png - a closed mouth's at rest and open (0, 30), an open
one's as it was made and closed (0 and minus its opening, tags 0, c).
Prints lines starting with CREATURE_.
"""
import math
import sys

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
src, dst = argv[0], argv[1]
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)


def pair(key):
    return tuple(float(x) for x in opt[key].split(",")) if key in opt else None


bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
arm = next(o for o in bpy.context.scene.objects if o.type == "ARMATURE")
me = next(o for o in bpy.context.scene.objects if o.type == "MESH" and o.vertex_groups)
for o in list(bpy.context.scene.objects):
    if o.type == "MESH" and not o.vertex_groups:
        bpy.data.objects.remove(o, do_unlink=True)  # the importer's bone-shape sphere

# ---- names
if opt.get("names"):
    ren = dict(p.split(":") for p in opt["names"].split(","))
    for b in arm.data.bones:
        if b.name in ren:
            old = b.name
            b.name = ren[old]
            vg = me.vertex_groups.get(old)
            if vg:
                vg.name = ren[old]
    print("CREATURE_NAMES", len(ren), "bones renamed")

# ---- jaw
front, corner, hinge = pair("jaw_front"), pair("jaw_corner"), pair("hinge")
if front and corner and hinge:
    parent = opt.get("jaw_parent", "head")
    mw = arm.matrix_world
    inv = mw.inverted()
    bpy.context.view_layer.objects.active = arm
    bpy.ops.object.mode_set(mode="EDIT")
    eb = arm.data.edit_bones.new("jaw")
    eb.head = inv @ Vector((0.0, hinge[0], hinge[1]))
    tip = pair("chin") or front   # (an open mouth: the lower jaw's front, below the mouth line's front in the gap)
    eb.tail = inv @ Vector((0.0, tip[0], tip[1]))
    eb.parent = arm.data.edit_bones[parent]
    eb.use_deform = True
    bpy.ops.object.mode_set(mode="OBJECT")

    def line_z(y):
        """height of the mouth line at depth y (piecewise: front -> corner -> hinge)"""
        pts = sorted([front, corner, hinge] + ([pair("jaw_tip")] if pair("jaw_tip") else []))  # by y
        if y <= pts[0][0]:
            return pts[0][1]
        for (y0, z0), (y1, z1) in zip(pts, pts[1:]):
            if y <= y1:
                return z0 + (z1 - z0) * (y - y0) / max(y1 - y0, 1e-6)
        return pts[-1][1]

    fade = float(opt.get("fade", 0.03))   # metres before the hinge over which the jaw weight goes to 0
    floor = float(opt.get("floor", 0.12))  # nothing below this height (front paws)
    half_w = float(opt.get("half_width", 0.12))
    cx = float(opt.get("cx", 0.0))
    P = [me.matrix_world @ v.co for v in me.data.vertices]

    def weight(p):
        if p.y > hinge[0] or p.z < floor or abs(p.x - cx) > half_w or p.z > line_z(p.y):
            return 0.0
        if p.y > hinge[0] - fade:
            return (hinge[0] - p.y) / fade
        return 1.0

    w = [weight(p) for p in P]
    # the islands, the seams welded (a model split along its UV seams is one skin): a loose piece (teeth, a tongue, a
    # fur card) moves whole, by its centre; on the skin itself, with the mouth marked (chin=), the jaw is only what is
    # reached from the lower jaw's front over the skin below the line - the bottom of a long open jaw low under the
    # head goes with it, a front paw below it does not (its way up the leg passes behind the hinge)
    bm = bmesh.new()
    bm.from_mesh(me.data)
    bm.verts.ensure_lookup_table()
    same = {}
    for i, p in enumerate(P):
        same.setdefault((round(p.x, 5), round(p.y, 5), round(p.z, 5)), []).append(i)
    twins = lambda i: same[(round(P[i].x, 5), round(P[i].y, 5), round(P[i].z, 5))]  # noqa: E731

    def near(i):
        for e in bm.verts[i].link_edges:
            yield e.other_vert(bm.verts[i]).index
        yield from twins(i)

    seen = set()
    teeth = 0
    body = []
    for v in bm.verts:
        if v.index in seen:
            continue
        st, isl = [v.index], []
        seen.add(v.index)
        while st:
            a = st.pop()
            isl.append(a)
            for b in near(a):
                if b not in seen:
                    seen.add(b)
                    st.append(b)
        if len(isl) > 2000:
            body += isl   # the skin itself
            continue
        c = sum((P[i] for i in isl), Vector()) / len(isl)
        if c.y < hinge[0] and abs(c.x - cx) < half_w and c.z > floor:
            # (with the jaw when it reaches further below the mouth line than above it: a lower tusk is rooted in the
            # jaw, its tip up past the line - by its centre it went with the skull)
            lz = line_z(c.y)
            ww = 1.0 if (lz - min(P[i].z for i in isl)) > (max(P[i].z for i in isl) - lz) else 0.0
            for i in isl:
                w[i] = ww
            teeth += 1
    chin = pair("chin")
    if chin:
        cands = [i for i in body if w[i] > 0]
        if cands:
            start = min(cands, key=lambda i: (P[i].y - chin[0]) ** 2 + (P[i].z - chin[1]) ** 2 + (P[i].x - cx) ** 2)
            reach, st = {start}, [start]
            while st:
                a = st.pop()
                for b in near(a):
                    if b not in reach and w[b] > 0:
                        reach.add(b)
                        st.append(b)
            cut = 0
            for i in body:
                if w[i] > 0 and i not in reach:
                    w[i] = 0.0
                    cut += 1
            print(f"CREATURE_JAW_REACH kept={len(reach)} cut={cut}")
    bm.free()
    if opt.get("paint"):   # painted by hand in the markup (glTF points): with the jaw (plus) or not (minus), whatever the rule
        import json as _json
        from mathutils.kdtree import KDTree
        pt = _json.loads(open(opt["paint"], encoding="utf-8").read())
        kd = KDTree(len(P))
        for i, p_ in enumerate(P):
            kd.insert(p_, i)
        kd.balance()
        eps = 1e-4 * max((max(p_.z for p_ in P) - min(p_.z for p_ in P)), 1e-3)
        got = 0
        for key, val in (("plus", 1.0), ("minus", 0.0)):
            for q in pt.get(key, []):
                for _, i, _ in kd.find_range(Vector((q[0], -q[2], q[1])), eps):
                    w[i] = val
                    got += 1
        print(f"CREATURE_JAW_PAINT {got}")
    jg = me.vertex_groups.new(name="jaw")
    n = 0
    for v, x in zip(me.data.vertices, w):
        if x <= 0:
            continue
        for g in v.groups:  # make room: scale the old weights by (1 - x)
            g.weight *= (1.0 - x)
        jg.add([v.index], x, "REPLACE")
        n += 1
    print(f"CREATURE_JAW vertices={n} loose pieces judged={teeth} hinge=({hinge[0]:.3f},{hinge[1]:.3f})")

    if opt.get("preview"):
        sc = bpy.context.scene
        r = sc.render
        r.resolution_x, r.resolution_y = 520, 420
        try:
            r.engine = "BLENDER_EEVEE"
        except TypeError:
            r.engine = "BLENDER_WORKBENCH"
        sc.view_settings.view_transform = "Standard"
        wd = bpy.data.worlds.new("w")
        sc.world = wd
        wd.use_nodes = True
        next(x for x in wd.node_tree.nodes if x.type == "BACKGROUND").inputs["Color"].default_value = (0.8, 0.8, 0.82, 1)
        sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
        sun.data.energy = 3
        sun.rotation_euler = (math.radians(50), 0, math.radians(-35))
        sc.collection.objects.link(sun)
        cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
        cam.data.type = "ORTHO"
        cam.data.ortho_scale = max(0.32, 2.6 * math.dist(front, hinge))   # (a big creature's head in the picture too)
        sc.collection.objects.link(cam)
        sc.camera = cam
        c = Vector((cx, (front[0] + hinge[0]) / 2, (front[1] + hinge[1]) / 2 + 0.02))
        pb = arm.pose.bones["jaw"]
        pb.rotation_mode = "XYZ"
        angles = [float(x) for x in opt.get("angles", "0,30").split(",")]
        tags = opt.get("tags", ",".join(str(int(a)) for a in angles)).split(",")
        for ang, tag in zip(angles, tags):
            pb.rotation_euler = (0, 0, 0)
            # open: turn the jaw down around the hinge (axis = the bone's local X)
            pb.rotation_euler.x = math.radians(ang)
            bpy.context.view_layer.update()
            for nm, d in (("side", (-1, 0, 0.1)), ("front", (-0.5, -1, 0.2))):
                cam.location = c + Vector(d).normalized() * 2
                cam.rotation_euler = (c - cam.location).to_track_quat("-Z", "Y").to_euler()
                r.filepath = opt["preview"].replace(".png", f"_{tag}_{nm}.png")
                bpy.ops.render.render(write_still=True)
        pb.rotation_euler = (0, 0, 0)
        print("CREATURE_PREVIEW done")

bpy.ops.object.select_all(action="SELECT")
for o in list(bpy.context.scene.objects):
    if o.type not in ("MESH", "ARMATURE"):
        o.select_set(False)
bpy.ops.export_scene.gltf(filepath=dst, export_format="GLB", use_selection=True, export_skins=True,
                          export_animations=False)
print("CREATURE_OK", dst)
