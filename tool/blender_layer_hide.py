"""Runs INSIDE Blender (background): which parts of the lower layers come out over the higher ones, for the Godot
fitting room (the armour editor's hideUnder, the same rule).

    blender -b -P blender_layer_hide.py -- job.json

job.json: {"pieces": [{"item", "glb", "layer", "kind"}], "out": path}. Every piece is read at rest; a point of a piece
is out when the line from the bone inside the body that leads it (its rest line: the joint to its child's) to it
crosses a piece of a higher layer on the way (under a helmet's rim the line misses the helmet: the coif shows there) -
where that piece is led by the same bone or the next one up or down the chain (they move nearly together: a coif on the
neck under a helmet on the head; a bracer under a pauldron would leave a hole when the arm rises), the point at most POKE of the height past it (not a part far beyond), and the
line from that piece's own bone to the point crossing it too (a cuirass's point behind a pauldron's edge: the line
from the spine goes under the edge, the one from the collarbone misses the pauldron - not hidden), and all round it
(EDGE of the height four ways across) either that piece or the lower one itself: by the higher one's edge the hidden
part must not open on nothing (a coif over a pelerine's neckline, its own opening past it: the throat), while past a
helmet's rim the coif goes on and hiding it there is safe.
A helmet's mail is rings with gaps (an aventail): seen through, nothing hidden under it. The out file:
{lower item: {higher item: [[x, y, z] in thousandths, the glTF mesh's own axes - the body masks' keys]}}; SF3DEquip
hides a lower piece's triangles with a corner among a shown higher piece's keys. Prints LAYER_HIDE.
"""
import json
import sys
from pathlib import Path

import bpy
from mathutils import Vector
from mathutils.bvhtree import BVHTree

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
bpy.ops.wm.read_factory_settings(use_empty=True)

pieces = []
for p in job["pieces"]:
    before = set(bpy.data.objects)
    bpy.ops.import_scene.gltf(filepath=p["glb"])
    new = [o for o in bpy.data.objects if o not in before]
    # (its skinned meshes only: the importer adds an icosphere of its own - the bones' display shape, 2 m across)
    meshes = [o for o in new if o.type == "MESH" and any(m.type == "ARMATURE" for m in o.modifiers)]
    arm = next((o for o in new if o.type == "ARMATURE"), None)
    pieces.append((p, meshes, arm))
arms = [a for _, _, a in pieces if a]
size = max((max(b.tail_local.z for b in a.data.bones) - min(b.head_local.z for b in a.data.bones) for a in arms), default=1.0)
eps = .0012 * size   # (about 2 mm on a person)
POKE = .05   # of the height: how far past a higher piece a point of a lower one may be and still be its poking out
EDGE = .015   # of the height: how far all round a hidden point the higher piece, or the lower one itself, must be


def lead(o, v):   # the bone that leads a vertex most
    names = [g.name for g in o.vertex_groups]
    return names[max(v.groups, key=lambda x: x.weight).group] if v.groups else None


def solid_tree(p, meshes):   # its rest triangles in the world, but a helmet's ring mail; each face's leading bone
    verts, polys, bones = [], [], []
    for o in meshes:
        W, base = o.matrix_world, len(verts)
        verts += [W @ v.co for v in o.data.vertices]
        vb = [lead(o, v) for v in o.data.vertices]
        mats = [m.name if m else "" for m in o.data.materials]
        for f in o.data.polygons:
            name = mats[f.material_index] if f.material_index < len(mats) else ""
            if p["kind"] == "helmet" and name.endswith("_mail"):
                continue
            polys.append([base + i for i in f.vertices])
            got = {}
            for i in f.vertices:
                got[vb[i]] = got.get(vb[i], 0) + 1
            bones.append(max(got, key=got.get))
    return (BVHTree.FromPolygons(verts, polys), bones) if polys else None


trees = {p["item"]: solid_tree(p, ms) for p, ms, _ in pieces}
own = {p["item"]: solid_tree({**p, "kind": ""}, ms) for p, ms, _ in pieces}   # (each piece whole: is it there past an edge)
out = {}
for p, meshes, arm in pieces:
    cape = lambda x: x["kind"] in ("coif", "pelerine")   # (one mail cape worn at a time: not one under the other)
    ups = [(q["item"], trees[q["item"]]) for q, _, _ in pieces if q["layer"] > p["layer"] and trees[q["item"]] and not (cape(p) and cape(q))]
    if not ups or arm is None:
        continue
    A = arm.matrix_world
    lines = {}
    for b in arm.data.bones:
        kid = b.children[0] if b.children else None
        lines[b.name] = (A @ b.head_local, A @ (kid.head_local if kid else b.tail_local))
    par = {b.name: (b.parent.name if b.parent else None) for b in arm.data.bones}
    near = lambda x, y: x == y or par.get(x) == y or par.get(y) == x
    found = {}
    me = own[p["item"]][0] if own[p["item"]] else None
    for o in meshes:
        W = o.matrix_world
        for v in o.data.vertices:
            bone = lead(o, v)
            a, b = lines.get(bone, (None, None))
            if a is None:
                continue
            P = W @ v.co
            ab = b - a
            t = max(0.0, min(1.0, (P - a).dot(ab) / ab.length_squared)) if ab.length_squared > 1e-12 else 0.0
            c = a + ab * t
            L = (P - c).length
            if L < 2 * eps:
                continue
            d = (P - c) / L
            for item, (tree, fb) in ups:   # (under each one it comes out over: hidden while any of them is shown)
                loc, _, fi, dist = tree.ray_cast(c, d, L - eps)
                if loc is None or not near(fb[fi], bone) or L - dist >= POKE * size:
                    continue
                if fb[fi] != bone:   # (its own bone's line to the point crosses it too)
                    a2, b2 = lines.get(fb[fi], (None, None))
                    if a2 is None:
                        continue
                    ab2 = b2 - a2
                    t2 = max(0.0, min(1.0, (P - a2).dot(ab2) / ab2.length_squared)) if ab2.length_squared > 1e-12 else 0.0
                    c2 = a2 + ab2 * t2
                    L2 = (P - c2).length
                    if L2 < 2 * eps or tree.ray_cast(c2, (P - c2) / L2, L2 - eps)[0] is None:
                        continue
                u1 = d.orthogonal().normalized()
                u2 = d.cross(u1)

                def covered(w):   # past it that way: the higher piece over, or the lower one going on there
                    q = P + w * EDGE * size
                    lq = (q - c).length
                    dq = (q - c) / lq
                    if tree.ray_cast(c, dq, lq - eps)[0] is not None:
                        return True
                    h = me.ray_cast(c, dq, lq + POKE * size) if me else (None,)
                    return h[0] is not None and h[3] > lq - POKE * size
                if not all(covered(w) for w in (u1, -u1, u2, -u2)):   # (by an edge opening on nothing: kept)
                    continue
                co = v.co
                found.setdefault(item, set()).add((round(co.x * 1000), round(co.z * 1000), round(-co.y * 1000)))
    if found:
        out[p["item"]] = {k: [list(x) for x in sorted(s)] for k, s in found.items()}
Path(job["out"]).write_text(json.dumps(out), encoding="utf-8")
print("LAYER_HIDE", {k: sum(len(x) for x in v.values()) for k, v in out.items()}, flush=True)
