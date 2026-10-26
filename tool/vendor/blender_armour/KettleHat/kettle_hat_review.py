"""Structural validation, portable export and studio review for helmet assets."""
import hashlib
import json
import math
import struct

import bmesh
import bpy
from mathutils import Vector

# //#GPT: Validate actual meshes, not just a successful Blender process exit.
def mesh_report(objects):
    report = {"objects": [], "triangles": 0}
    fingerprint = hashlib.sha256()
    for obj in sorted(objects, key=lambda o: o.name):
        mesh = obj.data
        mesh.calc_loop_triangles()
        bm = bmesh.new()
        bm.from_mesh(mesh)
        non_manifold = sum(not edge.is_manifold for edge in bm.edges)
        degenerate = sum(face.calc_area() < 1e-14 for face in bm.faces)
        volume = bm.calc_volume(signed=True) * obj.matrix_world.determinant()
        bm.free()
        coordinates = [obj.matrix_world @ v.co for v in mesh.vertices]
        if not coordinates or not all(math.isfinite(c) for v in coordinates for c in v):
            raise ValueError(f"Nonfinite or empty mesh: {obj.name}")
        if non_manifold or degenerate or volume <= 0:
            raise ValueError(f"Invalid mesh {obj.name}: "
                             f"non_manifold={non_manifold}, zero_faces={degenerate}, volume={volume}")
        if not mesh.uv_layers:
            raise ValueError(f"Missing UV map: {obj.name}")
        fingerprint.update(obj.name.encode())
        for point in coordinates:
            fingerprint.update(struct.pack("<3d", *(round(c, 9) for c in point)))
        report["objects"].append({"name": obj.name, "vertices": len(mesh.vertices),
                                  "triangles": len(mesh.loop_triangles),
                                  "non_manifold_edges": non_manifold,
                                  "degenerate_faces": degenerate, "volume_m3": volume})
        report["triangles"] += len(mesh.loop_triangles)
    report["geometry_sha256"] = fingerprint.hexdigest()
    points = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    report["bounds_min_m"] = [min(p[i] for p in points) for i in range(3)]
    report["bounds_max_m"] = [max(p[i] for p in points) for i in range(3)]
    report["dimensions_m"] = [report["bounds_max_m"][i] - report["bounds_min_m"][i]
                              for i in range(3)]
    return report

# //#GPT: Catch leaked cameras, lights and missing packed PBR images in the actual GLB.
def validate_glb(path, expected_meshes):
    data = path.read_bytes()
    magic, version, length = struct.unpack_from("<4sII", data)
    if magic != b"glTF" or version != 2 or length != len(data):
        raise ValueError("Invalid GLB header")
    size, kind = struct.unpack_from("<II", data, 12)
    if kind != 0x4E4F534A:
        raise ValueError("Missing JSON chunk")
    doc = json.loads(data[20:20+size])
    if len(doc.get("meshes", [])) != expected_meshes:
        raise ValueError("GLB mesh count mismatch")
    if doc.get("cameras") or doc.get("skins"):
        raise ValueError("Unexpected cameras or skins in static equipment")
    if "KHR_lights_punctual" in doc.get("extensionsUsed", []):
        raise ValueError("Studio lights leaked into GLB")
    images = doc.get("images", [])
    if len(images) < 6 or any("bufferView" not in item for item in images):
        raise ValueError("PBR images must be embedded")
    return {"mesh_count": len(doc["meshes"]), "embedded_images": len(images),
            "bytes": len(data), "static": True}

# //#GPT: Create a review-only studio whose objects never enter the equipment export.
def studio(objects):
    scene = bpy.context.scene
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except TypeError:
        scene.render.engine = "CYCLES"
        scene.cycles.device = "CPU"
        scene.cycles.samples = 32
    scene.render.resolution_x = scene.render.resolution_y = 900
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGBA"
    scene.render.film_transparent = False
    scene.view_settings.view_transform = "AgX"
    scene.world = bpy.data.worlds.new("StudioWorld")
    scene.world.use_nodes = True
    bg = next(n for n in scene.world.node_tree.nodes if n.type == "BACKGROUND")
    bg.inputs["Color"].default_value = (0.55, 0.55, 0.55, 1)
    bg.inputs["Strength"].default_value = 0.5
    points = [o.matrix_world @ Vector(c) for o in objects for c in o.bound_box]
    low = Vector(tuple(min(p[i] for p in points) for i in range(3)))
    high = Vector(tuple(max(p[i] for p in points) for i in range(3)))
    center = (low + high) / 2
    for name, location, energy, size in (
        ("Key", (-0.6, -0.7, 0.8), 35, 0.65),
        ("Fill", (0.6, -0.2, 0.35), 18, 0.5),
        ("Rim", (0.1, 0.5, 0.65), 40, 0.6),
    ):
        light = bpy.data.lights.new(name, "AREA")
        light.energy, light.shape, light.size = energy, "DISK", size
        obj = bpy.data.objects.new(name, light)
        scene.collection.objects.link(obj)
        obj.location = location
        obj.rotation_euler = (center - obj.location).to_track_quat("-Z", "Y").to_euler()
    camera = bpy.data.objects.new("ReviewCamera", bpy.data.cameras.new("ReviewCamera"))
    scene.collection.objects.link(camera)
    scene.camera = camera
    camera.data.type = "ORTHO"
    camera.data.ortho_scale = max(high - low) * 1.27
    camera.data.clip_start, camera.data.clip_end = 0.01, 50
    return center

# //#GPT: Use measured bounds and orthographic cameras for honest silhouette comparison.
def render_views(objects, directory):
    center = studio(objects)
    camera = bpy.context.scene.camera
    directory.mkdir(exist_ok=True)
    views = {"front": (0, -1, 0.05), "side": (1, 0, 0.05),
             "back": (0, 1, 0.05), "hero": (0.85, -1, 0.65),
             "inside": (0.3, -0.5, -1)}
    for name, direction in views.items():
        camera.location = center + Vector(direction).normalized() * 1.3
        camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()
        bpy.context.scene.render.filepath = str(directory / f"{name}.png")
        bpy.ops.render.render(write_still=True)
        print("RENDER_OK", name, flush=True)
    camera.location = center + Vector(views["hero"]).normalized() * 1.3
    camera.rotation_euler = (center - camera.location).to_track_quat("-Z", "Y").to_euler()

# //#GPT: Keep selectable mechanical parents and an optional asset filename; preserve kettle defaults.
def review_and_export(root, objects, output, reference, render, stem="kettle_hat"):
    bpy.context.view_layer.update()
    report = mesh_report(objects)
    report["blender_version"] = bpy.app.version_string
    report["reference"] = str(reference.resolve()) if reference else None
    if reference and reference.is_file():
        img = bpy.data.images.load(str(reference.resolve()), check_existing=False)
        img.name = f"{stem}_Reference"
        img.pack()
    for obj in bpy.context.scene.objects:
        obj.select_set(False)
    root.select_set(True)
    for obj in objects:
        obj.select_set(True)
        parent = obj.parent
        while parent:
            parent.select_set(True)
            parent = parent.parent
    bpy.context.view_layer.objects.active = root
    glb = output / f"{stem}.glb"
    bpy.ops.export_scene.gltf(filepath=str(glb), export_format="GLB",
                              use_selection=True, use_active_scene=True,
                              export_apply=True, export_texcoords=True,
                              export_normals=True, export_materials="EXPORT",
                              export_extras=True, export_cameras=False,
                              export_lights=False)
    report["glb"] = validate_glb(glb, len(objects))
    if render:
        render_views(objects, output / "renders")
    bpy.ops.wm.save_as_mainfile(filepath=str(output / f"{stem}.blend"))
    (output / "validation.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("VALIDATION_OK", report["triangles"], "triangles", flush=True)
