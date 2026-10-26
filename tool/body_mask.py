"""Runs INSIDE Blender: which of a character's body a worn piece hides, so that the game (godot/sf3d_equip.gd) and the
editors can take it away while the piece is on: the skin under it (it would poke through in motion), and small
things sticking out through it (cords hanging from trousers under a skirt, the ears under a helmet).

A body vertex is hidden when it moves mostly with the piece's own bones (a hand beside a skirt does not) and the piece
is close to it outward (it is under it) or inward (it pokes out through it); so is what grows thin out of the hidden
part (an ear through a helmet, cords hanging from under a skirt), and next to the hidden part, what the piece closes
round on most sides (a cord crossing the skirt from inside) — a face out of a helmet, a hand out of a bracer stay. The game takes away the triangles whose
three corners are all hidden, so the body's edge at the piece's rim stays.

The vertices are given by their positions, as the glTF mesh holds them (Y up, mesh-local), in thousandths of a unit
(integers): the index order differs between files, a position does not; Blender's import moves them by ~1e-5, so the
lookups (godot/sf3d_equip.gd, the editors) also try the next thousandth when a coordinate is near the cells' edge."""
from mathutils import Vector
from mathutils.bvhtree import BVHTree


def _bvh(objs):
    verts, polys = [], []
    for o in objs:
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in o.data.vertices]
        polys += [tuple(base + i for i in p.vertices) for p in o.data.polygons]
    return BVHTree.FromPolygons(verts, polys)


def body_mask(body, pieces, share=.5, reach=.1, through=.1, thin=.04, around=.12, beside=.06, erode=0):
    """body: the character's skinned meshes (rest pose); pieces: the piece's meshes (rest pose, weighted). reach: how
    far out the piece may be over the skin, through: how close behind a thing poking out of it, thin: what is thin (an
    ear, a cord; not an arm beside a cuirass), around: how near the piece is round a thing it closes round, beside: how near past the piece the body is
    when a thing is beside it, not under it, all as
    shares of the piece's size; erode: rings of vertices given back at the hidden part's edge.
    Returns [[x, y, z], ...]: the hidden vertices' glTF positions in thousandths (integers)."""
    # the bones it really moves with (an imported skin lists every joint of the skeleton as a group, most of them empty)
    bones = {o.vertex_groups[g.group].name for o in pieces for v in o.data.vertices for g in v.groups if g.weight > .05}
    if not bones:
        return []
    lo = Vector((min(min((o.matrix_world @ v.co)[i] for v in o.data.vertices) for o in pieces) for i in range(3)))
    hi = Vector((max(max((o.matrix_world @ v.co)[i] for v in o.data.vertices) for o in pieces) for i in range(3)))
    size = (hi - lo).length
    far = reach * size
    tree = _bvh(pieces)
    body_tree = _bvh(body)
    out = set()
    for o in body:
        names = [g.name for g in o.vertex_groups]
        W, N = o.matrix_world, o.matrix_world.to_3x3().inverted().transposed()
        me = o.data
        cand = [False] * len(me.vertices)
        hidden = [False] * len(me.vertices)
        for v in me.vertices:
            tot = sum(g.weight for g in v.groups)
            on = sum(g.weight for g in v.groups if names[g.group] in bones)
            if tot <= 1e-9 or on / tot < share:
                continue
            cand[v.index] = True   # its own: the flood below may go far (a long ear), the rays only near the piece
            p = W @ v.co
            if not (lo.x - far <= p.x <= hi.x + far and lo.y - far <= p.y <= hi.y + far and lo.z - far <= p.z <= hi.z + far):
                continue
            n = (N @ v.normal).normalized()
            e = 1e-4 * far
            h = tree.ray_cast(p + n * e, n, far)
            if h[0] is not None:   # under it, unless the body goes on right past it (an arm beside a cuirass sees its side)
                b = body_tree.ray_cast(h[0] + n * e, n, beside * size)
                if b[0] is None:
                    hidden[v.index] = True
            if not hidden[v.index] and tree.ray_cast(p - n * e, -n, through * size)[0] is not None:
                hidden[v.index] = True
        # out of the hidden part, along the mesh, into what is thin (its other side close behind it)
        thick = thin * size
        nb = [[] for _ in me.vertices]
        for ed in me.edges:
            a, b2 = ed.vertices
            nb[a].append(b2)
            nb[b2].append(a)
        front = [i for i, h in enumerate(hidden) if h]
        while front:
            nxt = []
            for i in front:
                for j in nb[i]:
                    if hidden[j] or not cand[j]:
                        continue
                    v = me.vertices[j]
                    p, n = W @ v.co, (N @ v.normal).normalized()
                    h = body_tree.ray_cast(p - n * 1e-4 * far, -n, thick)
                    if h[0] is not None:
                        hidden[j] = True
                        nxt.append(j)
            front = nxt
        # next to the hidden part, what the piece closes round (it meets at least half of 14 directions near)
        dirs = [Vector(d).normalized() for d in ((1, 0, 0), (-1, 0, 0), (0, 1, 0), (0, -1, 0), (0, 0, 1), (0, 0, -1),
                                                  (1, 1, 1), (1, 1, -1), (1, -1, 1), (1, -1, -1), (-1, 1, 1), (-1, 1, -1), (-1, -1, 1), (-1, -1, -1))]
        for _ in range(2):
            grow = [j for j in range(len(hidden)) if not hidden[j] and cand[j] and any(hidden[k] for k in nb[j])]
            for j in grow:
                p = W @ me.vertices[j].co
                if sum(tree.ray_cast(p, d, around * size)[0] is not None for d in dirs) >= 7:
                    hidden[j] = True
        # thin things the piece is round on a third of the sides at least (cords hanging over a skirt, an ear by a
        # helmet); a finger beyond a bracer sees it on one side only
        for j, v in enumerate(me.vertices):
            if hidden[j] or not cand[j]:
                continue
            p, n = W @ v.co, (N @ v.normal).normalized()
            if not (lo.x - far <= p.x <= hi.x + far and lo.y - far <= p.y <= hi.y + far and lo.z - far <= p.z <= hi.z + far):
                continue
            if body_tree.ray_cast(p - n * 1e-4 * far, -n, thick)[0] is None:
                continue
            if sum(tree.ray_cast(p, d, around * size)[0] is not None for d in dirs) >= 5:
                hidden[j] = True
        # erode: the hidden part kept that many rings of vertices in from its edge (a piece that turns over a joint
        # uncovers the skin near its rim as it bends)
        for _ in range(erode):
            edge = [j for j in range(len(hidden)) if hidden[j] and any(not hidden[k] for k in nb[j])]
            for j in edge:
                hidden[j] = False
        for v in me.vertices:
            if hidden[v.index]:
                c = v.co
                out.add((round(c.x * 1000), round(c.z * 1000), round(-c.y * 1000)))   # Blender -> glTF axes, mesh-local
    return [list(x) for x in sorted(out)]


def ears(body, bones, centre, radius, zlo, zhi, out=1.3, share=.5):
    """What sticks out of the head sideways (a goblin's or an elf's ears), to go under a helmet with the head even where
    the helmet does not reach (a kettle hat's brim is above them): the body's vertices moving mostly with the head's
    bones (bones), between the heights zlo and zhi, further than out x radius to the side (x) from the head's middle
    centre (not the nose, forward), and from there, along the mesh, what is thin (its other side close behind it) down
    to the head.
    Returns the hidden vertices' glTF positions in thousandths, as body_mask."""
    body_tree = _bvh(body)
    out_keys = set()
    for o in body:
        names = [g.name for g in o.vertex_groups]
        W, N = o.matrix_world, o.matrix_world.to_3x3().inverted().transposed()
        me = o.data
        cand = [False] * len(me.vertices)
        hidden = [False] * len(me.vertices)
        for v in me.vertices:
            tot = sum(g.weight for g in v.groups)
            on = sum(g.weight for g in v.groups if names[g.group] in bones)
            p = W @ v.co
            if tot <= 1e-9 or on / tot < share or not zlo <= p.z <= zhi:
                continue
            cand[v.index] = True
            if abs(p.x - centre.x) > out * radius:
                hidden[v.index] = True
        nb = [[] for _ in me.vertices]
        for ed in me.edges:
            a, b2 = ed.vertices
            nb[a].append(b2)
            nb[b2].append(a)
        thin = .2 * radius
        front = [i for i, h in enumerate(hidden) if h]
        while front:
            nxt = []
            for i in front:
                for j in nb[i]:
                    if hidden[j] or not cand[j]:
                        continue
                    v = me.vertices[j]
                    p, n = W @ v.co, (N @ v.normal).normalized()
                    if body_tree.ray_cast(p - n * 1e-4 * radius, -n, thin)[0] is not None:
                        hidden[j] = True
                        nxt.append(j)
            front = nxt
        for v in me.vertices:
            if hidden[v.index]:
                c = v.co
                out_keys.add((round(c.x * 1000), round(c.z * 1000), round(-c.y * 1000)))
    return [list(x) for x in sorted(out_keys)]


def where(body, bones, test, share=.5):
    """The body's vertices moving mostly with the bones for which test(world position) holds. As body_mask's."""
    out = set()
    for o in body:
        names = [g.name for g in o.vertex_groups]
        W = o.matrix_world
        for v in o.data.vertices:
            tot = sum(g.weight for g in v.groups)
            on = sum(g.weight for g in v.groups if names[g.group] in bones)
            if tot > 1e-9 and on / tot >= share and test(W @ v.co):
                c = v.co
                out.add((round(c.x * 1000), round(c.z * 1000), round(-c.y * 1000)))
    return [list(x) for x in sorted(out)]


def held(body, bones, piece, centre, share=.5):
    """What a piece closed round a part holds (a coif round the head: the hair under it): the body's vertices moving
    mostly with the bones from which a ray going out (away from centre, the part's middle) meets the piece. Through its
    openings (the face) and past it (an ear's tip) the rays go out: those stay. As body_mask's."""
    tree = _bvh(piece)
    return where(body, bones, lambda p: tree.ray_cast(p, (p - centre).normalized())[0] is not None, share)


def above(body, bones, z, share=.5):
    """What a helmet takes the place of on the head: the body's vertices moving mostly with the head's bones (bones)
    higher than z (the brow): the hair, a hat or a crown modelled on the character. As body_mask's."""
    return where(body, bones, lambda p: p.z > z, share)


if __name__ == "__main__":   # a piece put on before masks were made: blender -b -P body_mask.py -- rigged.glb piece.glb out.json
    import json
    import sys
    from pathlib import Path
    import bpy
    rig, piece, out = sys.argv[sys.argv.index("--") + 1:][:3]
    PARTS = ("Eye_", "EyeSocket", "Teeth_", "Gum_", "Tongue", "MouthCavity", "Icosphere")
    bpy.ops.wm.read_factory_settings(use_empty=True)
    bpy.ops.import_scene.gltf(filepath=rig)
    for a in bpy.data.objects:
        if a.type == "ARMATURE":
            a.data.pose_position = "REST"
    body = [o for o in bpy.data.objects if o.type == "MESH" and o.vertex_groups and not o.name.startswith(PARTS)]
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=piece)
    pcs = [o for o in bpy.data.objects if o not in before and o.type == "MESH" and o.vertex_groups]
    bpy.context.view_layer.update()
    Path(out).write_text(json.dumps(body_mask(body, pcs)), encoding="utf-8")
    print("BODY_MASK_OK", len(json.loads(Path(out).read_text(encoding="utf-8"))), flush=True)
