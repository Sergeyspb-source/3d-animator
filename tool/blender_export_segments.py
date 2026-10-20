"""Runs INSIDE Blender (background): write chosen segments of a segmented model (Tripo "parts") as separate GLBs,
in the model's own coordinates (not moved), dropping stray specks.

    blender -b -P blender_export_segments.py -- model.glb out_dir seg=name [seg=name ...] [min_island=0.02]

seg is the mesh name in the file (tripo_part_7), name the output file stem (pauldron_R), optionally with a
triangle budget: tripo_part_0=tunic:6000 (edge-collapse decimation, UVs kept). Several segments may share one name
(they are joined). Loose islands smaller than min_island of the piece are dropped.
Also writes out_dir/_all_armour.glb with every exported piece together. Prints SEG_ lines.
"""
import sys
from pathlib import Path

import bmesh
import bpy

argv = sys.argv[sys.argv.index("--") + 1:]
src, out = argv[0], Path(argv[1])
pairs = [a.split("=", 1) for a in argv[2:] if "=" in a and not a.startswith("min_island=")]
min_island = float(next((a.split("=")[1] for a in argv[2:] if a.startswith("min_island=")), 0.02))
out.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=src)
objs = {o.name: o for o in bpy.context.scene.objects if o.type == "MESH"}
for o in objs.values():
    mw = o.matrix_world.copy()
    o.parent = None
    o.matrix_world = mw
groups, budget = {}, {}
for seg, name in pairs:
    if ":" in name:
        name, n = name.split(":", 1)
        budget[name] = int(n)
    if seg in objs:
        groups.setdefault(name, []).append(objs[seg])
    else:
        print("SEG_MISSING", seg)
pieces = []
for name, obs in groups.items():
    bpy.ops.object.select_all(action="DESELECT")
    for o in obs:
        o.select_set(True)
    bpy.context.view_layer.objects.active = obs[0]
    if len(obs) > 1:
        bpy.ops.object.join()
    ob = bpy.context.view_layer.objects.active
    bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    bm = bmesh.new()
    bm.from_mesh(ob.data)
    bmesh.ops.remove_doubles(bm, verts=bm.verts, dist=1e-5)
    bm.faces.ensure_lookup_table()
    seen, islands = set(), []
    for f in bm.faces:
        if f.index in seen:
            continue
        st, isl = [f], []
        seen.add(f.index)
        while st:
            a = st.pop()
            isl.append(a)
            for e in a.edges:
                for g in e.link_faces:
                    if g.index not in seen:
                        seen.add(g.index)
                        st.append(g)
        islands.append(isl)
    big = max(len(i) for i in islands)
    drop = [f for i in islands if len(i) < min_island * big for f in i]
    bmesh.ops.delete(bm, geom=drop, context="FACES")
    bm.to_mesh(ob.data)
    bm.free()
    ob.name = name
    n_before = len(ob.data.polygons)
    if name in budget and n_before > budget[name]:
        # generated meshes are dense and even; a game item needs a fraction of that
        bpy.ops.object.select_all(action="DESELECT")
        ob.select_set(True)
        bpy.context.view_layer.objects.active = ob
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.mesh.quads_convert_to_tris()
        bpy.ops.object.mode_set(mode="OBJECT")
        mod = ob.modifiers.new("budget", "DECIMATE")
        mod.decimate_type = "COLLAPSE"
        mod.ratio = budget[name] / len(ob.data.polygons)
        mod.use_collapse_triangulate = True
        bpy.ops.object.modifier_apply(modifier=mod.name)
        print(f"SEG_DECIMATE {name} {n_before} -> {len(ob.data.polygons)} faces")
    pieces.append(ob)
    bpy.ops.object.select_all(action="DESELECT")
    ob.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(out / f"{name}.glb"), export_format="GLB", use_selection=True)
    print(f"SEG_PIECE {name} faces={len(ob.data.polygons)} dropped_specks={len(drop)}")
bpy.ops.object.select_all(action="DESELECT")
for o in pieces:
    o.select_set(True)
bpy.ops.export_scene.gltf(filepath=str(out / "_all_armour.glb"), export_format="GLB", use_selection=True)
print("SEG_OK", len(pieces))
