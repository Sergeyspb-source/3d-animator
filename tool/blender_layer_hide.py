"""Runs INSIDE Blender (background): which parts of the lower layers come out over the higher ones, for the Godot
fitting room (the armour editor's hideUnder, the same rule).

    blender -b -P blender_layer_hide.py -- job.json

job.json: {"pieces": [{"item", "glb", "layer", "kind"}], "out": path}. Every piece is read at rest; a point of a piece
is out when the line from the bone inside the body that leads it (its rest line: the joint to its child's) to it
crosses a piece of a higher layer on the way (under a helmet's rim the line misses the helmet: the coif shows there).
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
    meshes = [o for o in new if o.type == "MESH"]
    arm = next((o for o in new if o.type == "ARMATURE"), None)
    pieces.append((p, meshes, arm))
size = max((max(o.dimensions) for _, ms, _ in pieces for o in ms), default=1.0)
eps = .0012 * size   # (about 2 mm on a person)


def solid_tree(p, meshes):   # its rest triangles in the world, but a helmet's ring mail
    verts, polys = [], []
    for o in meshes:
        W, base = o.matrix_world, len(verts)
        verts += [W @ v.co for v in o.data.vertices]
        mats = [m.name if m else "" for m in o.data.materials]
        for f in o.data.polygons:
            name = mats[f.material_index] if f.material_index < len(mats) else ""
            if p["kind"] == "helmet" and name.endswith("_mail"):
                continue
            polys.append([base + i for i in f.vertices])
    return BVHTree.FromPolygons(verts, polys) if polys else None


trees = {p["item"]: solid_tree(p, ms) for p, ms, _ in pieces}
out = {}
for p, meshes, arm in pieces:
    ups = [(q["item"], trees[q["item"]]) for q, _, _ in pieces if q["layer"] > p["layer"] and trees[q["item"]]]
    if not ups or arm is None:
        continue
    A = arm.matrix_world
    lines = {}
    for b in arm.data.bones:
        kid = b.children[0] if b.children else None
        lines[b.name] = (A @ b.head_local, A @ (kid.head_local if kid else b.tail_local))
    found = {}
    for o in meshes:
        names = [g.name for g in o.vertex_groups]
        W = o.matrix_world
        for v in o.data.vertices:
            if not v.groups:
                continue
            g = max(v.groups, key=lambda x: x.weight)
            a, b = lines.get(names[g.group], (None, None))
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
            for item, tree in ups:   # (under each one it comes out over: hidden while any of them is shown)
                if tree.ray_cast(c, d, L - eps)[0] is not None:
                    co = v.co
                    found.setdefault(item, set()).add((round(co.x * 1000), round(co.z * 1000), round(-co.y * 1000)))
    if found:
        out[p["item"]] = {k: [list(x) for x in sorted(s)] for k, s in found.items()}
Path(job["out"]).write_text(json.dumps(out), encoding="utf-8")
print("LAYER_HIDE", {k: sum(len(x) for x in v.values()) for k, v in out.items()}, flush=True)
