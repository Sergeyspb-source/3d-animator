"""Blender helper (imported by other tool scripts): make the cut edges of separate mesh parts behave as one surface.

Vertices of different parts that sit at the same place (within eps, metres) get the same averaged skin weights and
the same normal and are snapped together, so the seam neither opens in motion nor shows as a shading line.
"""
import mathutils
from mathutils import Vector


def weld_parts(meshes, eps=0.0005):
    """meshes: Blender mesh objects (already skinned). Returns the number of seam clusters repaired."""
    objs = {o.name: o for o in meshes}
    rest = {o.name: [o.matrix_world @ v.co for v in o.data.vertices] for o in meshes}
    flat = [(name, i, p) for name, pts in rest.items() for i, p in enumerate(pts)]
    kd = mathutils.kdtree.KDTree(len(flat))
    for k, (_, _, p) in enumerate(flat):
        kd.insert(p, k)
    kd.balance()
    parent = list(range(len(flat)))

    def find(a):
        while parent[a] != a:
            parent[a] = parent[parent[a]]
            a = parent[a]
        return a

    for k, (name, _i, p) in enumerate(flat):
        for _, k2, _d in kd.find_range(p, eps):
            if k2 != k and flat[k2][0] != name:
                parent[find(k)] = find(k2)
    groups = {}
    for k in range(len(flat)):
        groups.setdefault(find(k), []).append(k)
    seam = [c for c in groups.values() if len({flat[k][0] for k in c}) > 1]

    def weights(obj, vi):
        names = {vg.index: vg.name for vg in obj.vertex_groups}
        return {names[g.group]: g.weight for g in obj.data.vertices[vi].groups if g.weight > 1e-5}

    normals = {name: [None] * len(rest[name]) for name in rest}
    for c in seam:
        ws = [weights(objs[flat[k][0]], flat[k][1]) for k in c]
        keys = set().union(*ws)
        avg = {b: sum(w.get(b, 0) for w in ws) / len(ws) for b in keys}
        tot = sum(avg.values()) or 1
        avg = {b: v / tot for b, v in avg.items() if v / tot > 1e-4}
        centre = sum((rest[flat[k][0]][flat[k][1]] for k in c), Vector()) / len(c)
        nrm = Vector((0, 0, 0))
        for k in c:
            o = objs[flat[k][0]]
            nrm += o.matrix_world.to_3x3() @ o.data.vertices[flat[k][1]].normal
        nrm.normalize()
        for k in c:
            name, vi, _ = flat[k]
            o = objs[name]
            for vg in o.vertex_groups:
                vg.remove([vi])
            for b, w in avg.items():
                vg = o.vertex_groups.get(b) or o.vertex_groups.new(name=b)
                vg.add([vi], w, "REPLACE")
            o.data.vertices[vi].co = o.matrix_world.inverted() @ centre
            normals[name][vi] = (o.matrix_world.to_3x3().inverted() @ nrm).normalized()
    for o in meshes:
        me = o.data
        me.update()
        nl = [normals[o.name][i] or me.vertices[i].normal.copy() for i in range(len(me.vertices))]
        try:
            me.normals_split_custom_set_from_vertices(nl)
        except Exception as e:  # noqa: BLE001
            print("WELD_WARN custom normals not set:", e)
    return len(seam)
