"""Parametric kettle hat. Run in an isolated Blender background process."""
import argparse
import json
import math
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kettle_hat_details import add_fittings, make_materials, tube
from kettle_hat_review import review_and_export

DEFAULTS = {
    "crown_radius_x": 0.096,
    "crown_radius_y": 0.114,
    "crown_height": 0.145,
    "brim_width": 0.058,
    "brim_drop": 0.030,
    "front_point": 0.010,
    "rear_extension": 0.008,
    "crest_height": 0.009,
    "crest_width": 0.008,
    "steel_thickness": 0.002,
    "rim_radius": 0.0018,
    "strap_width": 0.015,
    "strap_drop": 0.133,
    "segments": 96,
    "crown_rings": 24,
    "brim_rings": 10,
    "rivet_count": 16,
}

# //#GPT: Validate dimensions before constructing an inward solidified shell.
def validate_config(config):
    unknown = set(config) - set(DEFAULTS)
    if unknown:
        raise ValueError(f"Unknown parameters: {sorted(unknown)}")
    p = DEFAULTS | config
    ranges = {
        "crown_radius_x": (0.075, 0.15), "crown_radius_y": (0.085, 0.17),
        "crown_height": (0.09, 0.22), "brim_width": (0.02, 0.10),
        "brim_drop": (0.005, 0.065), "front_point": (0.0, 0.025),
        "rear_extension": (0.0, 0.035), "crest_height": (0.0, 0.02),
        "crest_width": (0.004, 0.025), "steel_thickness": (0.001, 0.004),
        "rim_radius": (0.001, 0.003), "strap_width": (0.01, 0.022),
        "strap_drop": (0.09, 0.18),
    }
    for key, (low, high) in ranges.items():
        value = p[key]
        if isinstance(value, bool) or not isinstance(value, (int, float)):
            raise ValueError(f"{key} must be numeric")
        if not math.isfinite(value) or not low <= value <= high:
            raise ValueError(f"{key} must be in [{low}, {high}] metres")
    for key, low, high in (("segments", 48, 192), ("crown_rings", 16, 48),
                           ("brim_rings", 6, 24), ("rivet_count", 8, 24)):
        if type(p[key]) is not int or not low <= p[key] <= high:
            raise ValueError(f"{key} must be an integer in [{low}, {high}]")
    if p["segments"] % 4:
        raise ValueError("segments must be divisible by four")
    return p

# //#GPT: Define one continuous dome-to-brim surface with an integrated sagittal ridge.
def surface_point(p, angle, radius, brim=False):
    c, s = math.cos(angle), math.sin(angle)
    if not brim:
        phi = radius * math.pi / 2
        r = math.sin(phi)
        x, y = p["crown_radius_x"] * r * c, p["crown_radius_y"] * r * s
        ridge = p["crest_height"] * math.exp(-(x / p["crest_width"]) ** 2)
        z = p["crown_height"] * math.cos(phi) + ridge * math.cos(phi) ** 1.4
    else:
        t = radius
        x = (p["crown_radius_x"] + p["brim_width"] * t) * c
        y = (p["crown_radius_y"] + p["brim_width"] * t) * s
        y -= p["front_point"] * max(0.0, -s) ** 24 * t ** 2
        y += p["rear_extension"] * max(0.0, s) ** 4 * t ** 2
        z = -p["brim_drop"] * (1 + 0.22 * s) * t ** 1.15
    return Vector((x, y, z))

# //#GPT: Create a connected manifold mesh; head space stays open after solidifying.
def shell_mesh(p, name, material, collection, liner=False):
    count = p["segments"]
    rings = [(False, i / p["crown_rings"])
             for i in range(1, p["crown_rings"] + 1)]
    if not liner:
        rings += [(True, i / p["brim_rings"])
                  for i in range(1, p["brim_rings"] + 1)]
    vertices = [(0, 0, p["crown_height"] + p["crest_height"])]
    for brim, radius in rings:
        for j in range(count):
            point = surface_point(p, math.tau * j / count, radius, brim)
            if liner:
                point.x *= 0.955
                point.y *= 0.955
                point.z -= 0.005
            vertices.append(tuple(point))
    if liner:
        vertices[0] = (0, 0, vertices[0][2] - 0.005)
    faces = [(0, 1 + j, 1 + (j + 1) % count) for j in range(count)]
    for row in range(len(rings) - 1):
        a, b = 1 + row * count, 1 + (row + 1) * count
        faces += [(a + j, b + j, b + (j + 1) % count, a + (j + 1) % count)
                  for j in range(count)]
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    solid = obj.modifiers.new("Physical thickness", "SOLIDIFY")
    solid.thickness = 0.001 if liner else p["steel_thickness"]
    solid.offset = -1
    bpy.ops.object.modifier_apply(modifier=solid.name)
    for face in mesh.polygons:
        face.use_smooth = True
    obj.select_set(False)
    return obj

# //#GPT: Unwrap each actual export mesh so the same PBR maps work in GLB and Blender.
def prepare_meshes(objects):
    for obj in objects:
        if obj.type == "CURVE":
            bpy.context.view_layer.objects.active = obj
            obj.select_set(True)
            bpy.ops.object.convert(target="MESH")
            obj = bpy.context.view_layer.objects.active
            bm = bmesh.new()
            bm.from_mesh(obj.data)
            bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.000001)
            bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
            bm.to_mesh(obj.data)
            bm.free()
            obj.select_set(False)
        if obj.type != "MESH":
            continue
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=0.000001)
        bmesh.ops.dissolve_degenerate(bm, edges=list(bm.edges), dist=0.000001)
        bmesh.ops.triangulate(bm, faces=list(bm.faces),
                             quad_method="BEAUTY", ngon_method="EAR_CLIP")
        bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        bpy.context.view_layer.objects.active = obj
        obj.select_set(True)
        bpy.ops.object.mode_set(mode="EDIT")
        bpy.ops.mesh.select_all(action="SELECT")
        bpy.ops.uv.smart_project(angle_limit=math.radians(66), island_margin=0.02)
        bpy.ops.object.mode_set(mode="OBJECT")
        obj.select_set(False)

# //#GPT: Keep the complete reproducible asset under one static equipment root.
def build(p, texture_dir):
    collection = bpy.data.collections.new("KettleHat_Model")
    bpy.context.scene.collection.children.link(collection)
    root = bpy.data.objects.new("KettleHat", None)
    collection.objects.link(root)
    mats = make_materials(texture_dir)
    shell = shell_mesh(p, "Steel_Shell", mats["steel"], collection)
    shell["wall_thickness_m"] = p["steel_thickness"]
    shell_mesh(p, "Suspended_Liner", mats["liner"], collection, liner=True)
    rim = [surface_point(p, math.tau * j / p["segments"], 1, True)
           for j in range(p["segments"])]
    tube("Rolled_Edge", rim, p["rim_radius"], mats["steel"], collection, True)
    add_fittings(p, mats, collection, surface_point)
    objects = [o for o in collection.objects if o.type in {"MESH", "CURVE"}]
    prepare_meshes(objects)
    objects = [o for o in collection.objects if o.type == "MESH"]
    for obj in objects:
        obj.parent = root
    root["units"] = "metres"
    root["front_blender"] = "-Y"
    root["prototype"] = True
    return root, objects

# //#GPT: Isolate generation from the user's open scene and refuse accidental overwrite.
def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--skip-render", action="store_true")
    args = parser.parse_args(sys.argv[sys.argv.index("--") + 1:])
    if not bpy.app.background:
        raise RuntimeError("Use a separate Blender --background process")
    config = json.loads(args.config.read_text(encoding="utf-8")) if args.config else {}
    p = validate_config(config)
    args.out.mkdir(parents=True, exist_ok=True)
    if any((args.out / name).exists() for name in ("kettle_hat.blend", "kettle_hat.glb")):
        raise FileExistsError("Choose a new --out directory; existing assets are preserved")
    bpy.ops.wm.read_homefile(use_empty=True)
    bpy.context.scene.unit_settings.system = "METRIC"
    bpy.context.scene.unit_settings.scale_length = 1.0
    print("KETTLE_BUILD_START", json.dumps(p), flush=True)
    root, objects = build(p, args.out / "textures")
    (args.out / "parameters.json").write_text(json.dumps(p, indent=2), encoding="utf-8")
    review_and_export(root, objects, args.out, args.reference, not args.skip_render)
    print("KETTLE_BUILD_OK", str(args.out.resolve()), flush=True)


if __name__ == "__main__":
    main()
