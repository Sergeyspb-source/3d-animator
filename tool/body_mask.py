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
import heapq
import math

from mathutils import Vector
from mathutils.bvhtree import BVHTree


def _bvh(objs):
    verts, polys = [], []
    for o in objs:
        base = len(verts)
        verts += [o.matrix_world @ v.co for v in o.data.vertices]
        polys += [tuple(base + i for i in p.vertices) for p in o.data.polygons]
    return BVHTree.FromPolygons(verts, polys)


def _cone(n, deg):
    """n and four directions turned deg from it (to its sides): a vertex the piece covers sees it along all of them."""
    t = n.orthogonal().normalized()
    b = n.cross(t).normalized()
    c, s = math.cos(math.radians(deg)), math.sin(math.radians(deg))
    return [n] + [(n * c + d * s).normalized() for d in (t, -t, b, -b)]


def body_mask(body, pieces, share=.5, reach=.1, through=.1, thin=.04, around=.12, beside=.06, erode=0, cover=0):
    """body: the character's skinned meshes (rest pose); pieces: the piece's meshes (rest pose, weighted). reach: how
    far out the piece may be over the skin, through: how close behind a thing poking out of it, thin: what is thin (an
    ear, a cord; not an arm beside a cuirass), around: how near the piece is round a thing it closes round, beside: how near past the piece the body is
    when a thing is beside it, not under it, all as
    shares of the piece's size; erode: rings of vertices given back at the hidden part's edge; cover: when set (degrees),
    a vertex is hidden only when the piece is over it along its direction and also turned that much to each side, so
    the skin beside a narrow strap or above a plate's rim (its ray meets them aslant) stays: the game would show a hole
    there.
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
            if h[0] is not None and cover and any(tree.ray_cast(p + n * e, d, far)[0] is None for d in _cone(n, cover)[1:]):
                h = (None,)   # only beside it
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
                if cover and any(tree.ray_cast(p, d, far)[0] is None for d in _cone((N @ me.vertices[j].normal).normalized(), cover)):
                    continue
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
            if cover and any(tree.ray_cast(p, d, far)[0] is None for d in _cone(n, cover)):
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


def where_thin(body, bones, test, thick, share=.5):
    """As where, of what is also thin there: its other side within `thick` behind it (an ear, not the back of a skull)."""
    tree = _bvh(body)
    out = set()
    for o in body:
        names = [g.name for g in o.vertex_groups]
        W, N = o.matrix_world, o.matrix_world.to_3x3().inverted().transposed()
        for v in o.data.vertices:
            tot = sum(g.weight for g in v.groups)
            on = sum(g.weight for g in v.groups if names[g.group] in bones)
            if tot <= 1e-9 or on / tot < share:
                continue
            p = W @ v.co
            if test(p):
                n = (N @ v.normal).normalized()
                if tree.ray_cast(p - n * 1e-4 * thick, -n, thick)[0] is not None:
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


def _hemisphere(count=192):
    """Directions evenly over the sphere (a vertex uses those on its outer side: about half)."""
    out = []
    gold = math.pi * (3 - math.sqrt(5))
    for i in range(count):
        z = 1 - 2 * (i + .5) / count
        r = math.sqrt(max(0, 1 - z * z))
        out.append(Vector((r * math.cos(i * gold), r * math.sin(i * gold), z)))
    return out


def head_cover(body, pieces, keys, poke_keys, centre, rings=1, shell=None, ear_keys=(), press=0.0, radii=(1, 1, 1), root=.1):
    """What a helmet does to the head. keys: what it may hide (under it, over the brow); poke_keys: what is taken off where
    it comes out through the shell (the head behind the face, over the brow); ear_keys: the ears; press: how far off the
    skull an ear may stay; radii: the head's half sizes (x, y, z) round centre; root: how far along the ear, from where
    it starts, the move grows from nothing. An ear that meets the shell is laid against the head, under it: each of that
    side's ear vertices comes in along its line to the head's middle, its height over the skull eased to at most `press`. Kept is all the skin that can be seen: a ray from it reaches the open past the
    helmet and the body - through an eye slit, under a rim - so no hole shows there. Hidden is what is closed in and what
    still comes out. `rings` of closed-in vertices next to the kept are given back; crumbs cut off from the rest go.
    shell: a BVH of the helmet without its straps. Returns body_mask's list, and [x, y, z, dx, dy, dz] for each vertex
    moved (where it is, how far: glTF axes, thousandths): readers of the hidden ones take the entries of three."""
    tree, body_tree = _bvh(pieces), _bvh(body)
    wall = shell or tree
    ear_keys = set(ear_keys)
    poke_keys = set(poke_keys) | ear_keys
    if not keys and not poke_keys:
        return []
    lo = Vector((min(min((o.matrix_world @ v.co)[i] for v in o.data.vertices) for o in pieces) for i in range(3)))
    hi = Vector((max(max((o.matrix_world @ v.co)[i] for v in o.data.vertices) for o in pieces) for i in range(3)))
    size = (hi - lo).length
    e, near = 1e-3 * size, .25 * size   # (the body further off than that - the chest under the chin - hides nothing from a camera)
    dirs = _hemisphere()
    key_of = lambda c: (round(c.x * 1000), round(c.z * 1000), round(-c.y * 1000))  # noqa: E731
    through = lambda p: wall.ray_cast(p, (centre - p).normalized(), (centre - p).length)[0] is not None  # noqa: E731

    # ---- the ears that meet the shell (each side on its own), laid against the head
    meets, moved, still = set(), {}, set()
    for o in body:
        W = o.matrix_world
        me = o.data
        for v in me.vertices:
            if key_of(v.co) in ear_keys and through(W @ v.co):
                meets.add((W @ v.co).x > centre.x)
        for ed in me.edges:
            a, b = ed.vertices
            if key_of(me.vertices[a].co) in ear_keys and key_of(me.vertices[b].co) in ear_keys:
                pa, pb = W @ me.vertices[a].co, W @ me.vertices[b].co
                if (pb - pa).length > 1e-9 and wall.ray_cast(pa, (pb - pa).normalized(), (pb - pa).length)[0] is not None:
                    meets.add(pa.x > centre.x)
    if press > 0 and meets:
        for o in body:
            W = o.matrix_world
            Wi = W.inverted()
            me = o.data
            at = {key_of(v.co): v.co for v in me.vertices}
            adj = {}
            for ed in me.edges:
                ka, kb = key_of(me.vertices[ed.vertices[0]].co), key_of(me.vertices[ed.vertices[1]].co)
                if ka != kb:
                    adj.setdefault(ka, set()).add(kb)
                    adj.setdefault(kb, set()).add(ka)
            ear = {k for k in at if k in ear_keys and ((W @ at[k]).x > centre.x) in meets}
            # how far along the skin from where the ear starts: its root stays joined to the head
            dist, heap = {}, []
            for k in ear:
                for j in adj.get(k, ()):
                    if j not in ear:
                        L = (W @ at[k] - W @ at[j]).length
                        if L < dist.get(k, 1e9):
                            dist[k] = L
                            heapq.heappush(heap, (L, k))
            while heap:
                dk, k = heapq.heappop(heap)
                if dk > dist.get(k, 1e9):
                    continue
                for j in adj.get(k, ()):
                    if j in ear:
                        nd = dk + (W @ at[k] - W @ at[j]).length
                        if nd < dist.get(j, 1e9):
                            dist[j] = nd
                            heapq.heappush(heap, (nd, j))
            for k in ear:
                p = W @ at[k]
                d = p - centre
                far = d.length
                d = d.normalized()
                # the skull there: a ball of the head's own sizes (through an ear's root the mesh has no wall)
                skull = 1 / math.sqrt((d.x / radii[0]) ** 2 + (d.y / radii[1]) ** 2 + (d.z / radii[2]) ** 2)
                if far <= skull:
                    continue
                t = dist.get(k, 1e9) / root
                w = 1.0 if t >= 1 else t * t * (3 - 2 * t)
                to = p.lerp(centre + d * (skull + press * (1 - math.exp(-(far - skull) / press))), w)
                if through(to):   # (the shell closer in there than the skull's ball: just inside its inner wall)
                    way = (centre - to).normalized()
                    left = (centre - to).length
                    h = wall.ray_cast(to, way, left)
                    first, last = h[3], h[3]
                    while True:
                        h = wall.ray_cast(to + way * (last + 1e-5), way, left - last - 1e-5)
                        if h[0] is None or last + h[3] - first > .5 * root:
                            break
                        last += h[3] + 1e-5
                    to = to + way * min(left, last + .5 * press)
                dl = Wi @ to - at[k]
                if dl.length > 1e-5:
                    moved[k] = (round(dl.x * 1000, 2), round(dl.z * 1000, 2), round(-dl.y * 1000, 2))
                    if through(to):
                        still.add(k)
    keys = set(keys) - set(moved)
    ear_set = poke_keys - set(moved)

    state = {}   # key -> "keep" / "hide" / "out" (came out through the helmet); a seam's twins: kept if either is
    rank = {"out": 0, "hide": 1, "keep": 2}
    for o in body:
        W, N = o.matrix_world, o.matrix_world.to_3x3().inverted().transposed()
        for v in o.data.vertices:
            k = key_of(v.co)
            if k not in keys and k not in ear_set:
                continue
            p, n = W @ v.co, (N @ v.normal).normalized()
            q = p + n * e
            st = "hide"
            if k in ear_set and wall.ray_cast(q, (centre - p).normalized(), (centre - p).length)[0] is not None:
                st = "out"
            if st == "hide":
                for d in dirs:
                    if d.dot(n) > .05 and tree.ray_cast(q, d)[0] is None and body_tree.ray_cast(q, d, near)[0] is None:
                        st = "keep"
                        break
            if k not in state or rank[st] > rank[state[k]]:
                state[k] = st
    hide = {k for k, st in state.items() if st != "keep"} | still
    out = {k for k, st in state.items() if st == "out"} | still
    for o in body:
        me = o.data
        ks = [key_of(v.co) for v in me.vertices]
        nb = [[] for _ in me.vertices]
        for ed in me.edges:
            a, b = ed.vertices
            nb[a].append(b)
            nb[b].append(a)
        # (what an edge of the skin pierces the shell with: both its ends, however they lie)
        W = o.matrix_world
        for ed in me.edges:
            a, b = ed.vertices
            if ks[a] in ear_set or ks[b] in ear_set:
                pa, pb = W @ me.vertices[a].co, W @ me.vertices[b].co
                if (pb - pa).length > 1e-9 and wall.ray_cast(pa, (pb - pa).normalized(), (pb - pa).length)[0] is not None:
                    for k in (ks[a], ks[b]):
                        if k in ear_set:
                            hide.add(k)
                            out.add(k)
        # (the triangles through the shell go too: the vertices next to what came out)
        for j in range(len(ks)):
            if (ks[j] in ear_set or ks[j] in moved) and ks[j] not in out and any(ks[i] in out for i in nb[j]):
                hide.add(ks[j])
        for _ in range(rings):
            back = {ks[j] for j in range(len(ks)) if ks[j] in hide and ks[j] not in out and any(ks[i] not in hide for i in nb[j])
                    and not ((ks[j] in ear_set or ks[j] in moved) and any(ks[i] in out for i in nb[j]))}
            hide -= back

        def parts(ok):   # the connected pieces of the vertices for which ok holds
            seen, res = [False] * len(ks), []
            for s0 in range(len(ks)):
                if seen[s0] or not ok(s0):
                    continue
                seen[s0] = True
                stack, cur = [s0], []
                while stack:
                    i = stack.pop()
                    cur.append(i)
                    for j in nb[i]:
                        if not seen[j] and ok(j):
                            seen[j] = True
                            stack.append(j)
                res.append(cur)
            return res
        for island in parts(lambda i: True):   # (islands the mesh has of its own stay: only what the hiding cut off goes)
            members = set(island)
            bits = parts(lambda i: i in members and ks[i] not in hide)
            if len(bits) > 1:
                big = max(map(len, bits))
                for b in bits:
                    if len(b) < .01 * big:   # (crumbs only: a face parted by the hidden skin keeps both halves)
                        hide |= {ks[i] for i in b}
    return [list(x) for x in sorted(hide)] + [[*k, *d] for k, d in sorted(moved.items())]   # (a hidden one moves too: its triangles with the others)


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
