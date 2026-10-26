"""Surface materials and wearable fittings for the kettle-hat prototype."""
import math
from array import array

import bpy
from mathutils import Quaternion, Vector

# //#GPT: Embed deterministic PBR textures instead of losing procedural nodes in GLB.
def make_materials(directory):
    directory.mkdir(parents=True, exist_ok=True)
    materials = {}
    for name, color, metal, rough in (
        ("steel", (0.40, 0.42, 0.45), 1.0, 0.49),
        ("leather", (0.19, 0.075, 0.029), 0.0, 0.66),
        ("liner", (0.045, 0.027, 0.016), 0.0, 0.87),
    ):
        mat = bpy.data.materials.new(name.title())
        mat.use_nodes = True
        shader = next(n for n in mat.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
        shader.inputs["Metallic"].default_value = metal
        shader.inputs["Roughness"].default_value = rough
        for channel in ("color", "roughness", "normal"):
            size = 256
            pixels = array("f")
            for y in range(size):
                for x in range(size):
                    a, b = math.tau * x / size, math.tau * y / size
                    hashed = math.sin(x*127.1 + y*311.7) * 43758.5453
                    grain = 2 * (hashed - math.floor(hashed)) - 1
                    if channel == "color":
                        rgba = tuple(c * (1 + (0.018 if metal else 0.055) * grain) for c in color) + (1,)
                    elif channel == "roughness":
                        v = rough + 0.045 * grain
                        rgba = (v, v, v, 1)
                    else:
                        strength = 0.008 if metal else 0.025
                        rgba = (0.5 + strength * math.sin(31*a + 17*b),
                                0.5 + strength * math.sin(13*a - 29*b), 1, 1)
                    pixels.extend(rgba)
            img = bpy.data.images.new(f"{name}_{channel}", size, size, alpha=True)
            if channel != "color":
                img.colorspace_settings.name = "Non-Color"
            img.pixels.foreach_set(pixels)
            path = directory / f"{name}_{channel}.png"
            img.filepath_raw = str(path)
            img.file_format = "PNG"
            img.save()
            loaded = bpy.data.images.load(str(path), check_existing=False)
            if channel != "color":
                loaded.colorspace_settings.name = "Non-Color"
                if loaded.pixels[0] < 0.1 or loaded.pixels[2] < 0.1:
                    raise ValueError(f"Blank PBR map after save: {path}")
            loaded.pack()
            bpy.data.images.remove(img)
            tex = mat.node_tree.nodes.new("ShaderNodeTexImage")
            tex.image = loaded
            if channel == "normal":
                normal = mat.node_tree.nodes.new("ShaderNodeNormalMap")
                normal.inputs["Strength"].default_value = 0.35
                mat.node_tree.links.new(tex.outputs["Color"], normal.inputs["Color"])
                mat.node_tree.links.new(normal.outputs["Normal"], shader.inputs["Normal"])
            else:
                socket = "Base Color" if channel == "color" else "Roughness"
                mat.node_tree.links.new(tex.outputs["Color"], shader.inputs[socket])
        materials[name] = mat
    return materials

# //#GPT: Link only newly created fittings to the isolated model collection.
def relocate(obj, collection, material):
    for old in list(obj.users_collection):
        old.objects.unlink(obj)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    return obj

# //#GPT: Use closed/capped tubular curves for rolled edges, buckles and their tongues.
def tube(name, points, radius, material, collection, cyclic=False):
    curve = bpy.data.curves.new(name, "CURVE")
    curve.dimensions = "3D"
    curve.resolution_u = 1
    curve.bevel_depth = radius
    curve.bevel_resolution = 2
    curve.use_fill_caps = True
    spline = curve.splines.new("POLY")
    spline.points.add(len(points) - 1)
    for point, co in zip(spline.points, points):
        point.co = (*co, 1)
    spline.use_cyclic_u = cyclic
    obj = bpy.data.objects.new(name, curve)
    collection.objects.link(obj)
    curve.materials.append(material)
    return obj

# //#GPT: Build one continuous strap path with a gradual physical twist under the chin.
def strap_frame(p, t):
    def position(a):
        return Vector((p["crown_radius_x"] * 0.87 * math.cos(a),
                       -0.008 - 0.024 * math.sin(a),
                       -0.004 - p["strap_drop"] * math.sin(a)))
    point = position(t)
    tangent = (position(t + 0.001) - position(t - 0.001)).normalized()
    width = Vector((0, 1, 0))
    width = (width - tangent * width.dot(tangent)).normalized()
    width = Quaternion(tangent, math.radians(52) * math.cos(t) ** 2) @ width
    normal = tangent.cross(width).normalized()
    return point, tangent, width, normal

# //#GPT: Make adjustment holes directly in the ribbon grid, avoiding fragile Boolean slivers.
def strap_grid(p, start, end, holes):
    vertices, faces, lookup = [], [], {}
    def vertex(t, across):
        key = (round(t, 11), round(across, 11))
        if key not in lookup:
            lookup[key] = len(vertices)
            vertices.append((t, across))
        return lookup[key]
    radius, half = 0.00125, p["strap_width"] / 2
    length = radius * 2.5
    corner = math.atan2(half, length)
    corners = [corner, math.pi-corner, math.pi+corner, math.tau-corner]
    angles = sorted(corners + [math.tau*i/24 for i in range(24)
                    if all(abs(math.atan2(math.sin(math.tau*i/24-c),
                                         math.cos(math.tau*i/24-c))) > 0.025 for c in corners)])
    outer = []
    for a in angles:
        c, s = math.cos(a), math.sin(a)
        scale = min(length/max(abs(c), 1e-12), half/max(abs(s), 1e-12))
        outer.append((scale*c, scale*s))
    across_values = sorted({round(s, 11) for u,s in outer if abs(abs(u)-length) < 1e-9})
    def bridge(a, b):
        steps = max(1, math.ceil((b-a)/0.025))
        for i in range(steps):
            t0, t1 = a+(b-a)*i/steps, a+(b-a)*(i+1)/steps
            for s0,s1 in zip(across_values, across_values[1:]):
                faces.append((vertex(t0,s0),vertex(t1,s0),vertex(t1,s1),vertex(t0,s1)))
    previous = start
    for center in ((0.30,0.43,0.56,0.69,0.82) if holes else ()):
        before = strap_frame(p, center-0.0001)[0]
        after = strap_frame(p, center+0.0001)[0]
        speed = (after-before).length/0.0002
        left, right = center-length/speed, center+length/speed
        bridge(previous, left)
        inside = [vertex(center+radius*math.cos(a)/speed, radius*math.sin(a)) for a in angles]
        outside = [vertex(center+u/speed, s) for u,s in outer]
        for i in range(len(angles)):
            j = (i+1) % len(angles)
            faces.append((outside[i],outside[j],inside[j],inside[i]))
        previous = right
    bridge(previous, end)
    return vertices, faces

# //#GPT: Give directly perforated leather a closed wall and retain the adjustable overlap.
def leather_strip(name, p, start, end, material, collection, lift=0, holes=False):
    coordinates, faces = strap_grid(p, start, end, holes)
    vertices = []
    for t, across in coordinates:
        point, _, width, normal = strap_frame(p, t)
        vertices.append(tuple(point + normal*lift + width*across))
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    mesh.materials.append(material)
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    solid = obj.modifiers.new("Leather thickness", "SOLIDIFY")
    solid.thickness = 0.0022
    solid.offset = 0
    bpy.ops.object.modifier_apply(modifier=solid.name)
    obj.select_set(False)
    return obj

# //#GPT: Model a small period-style buckle in the strap's local tangent frame.
def buckle(p, material, collection):
    center, tangent, width, normal = strap_frame(p, 0.69)
    center += normal * 0.004
    points = []
    for cx, cy, offset in ((-0.009, -0.008, math.pi),
                           (0.009, -0.008, 1.5*math.pi),
                           (0.009, 0.008, 0),
                           (-0.009, 0.008, 0.5*math.pi)):
        for j in range(5):
            a = offset + j * math.pi / 8
            points.append(center + tangent*(cx + 0.0025*math.cos(a))
                          + width*(cy + 0.0025*math.sin(a)))
    tube("Buckle_Frame", points, 0.0015, material, collection, True)
    tube("Buckle_Pin", [center - width*0.009, center + width*0.009],
         0.001, material, collection)
    tube("Buckle_Tongue", [center, center - tangent*0.010 - normal*0.002],
         0.0009, material, collection)
    keeper_center, _, _, _ = strap_frame(p, 0.91)
    keeper = [keeper_center + tangent*x + width*y + normal*0.001
              for x, y in ((-0.003,-0.011),(0.003,-0.011),(0.003,0.011),(-0.003,0.011))]
    tube("Leather_Keeper", keeper, 0.0018,
         next(m for m in bpy.data.materials if m.name == "Leather"), collection, True)

# //#GPT: Keep rivets separate and orient their flattened heads to the dome surface.
def add_fittings(p, mats, collection, surface_point):
    for i in range(p["rivet_count"]):
        angle = math.tau * (i + 0.5) / p["rivet_count"]
        point = surface_point(p, angle, 0.90)
        normal = Vector((point.x / p["crown_radius_x"]**2,
                         point.y / p["crown_radius_y"]**2,
                         point.z / p["crown_height"]**2)).normalized()
        bpy.ops.mesh.primitive_uv_sphere_add(segments=16, ring_count=8,
                                            radius=1, location=point + normal*0.0004)
        obj = relocate(bpy.context.object, collection, mats["steel"])
        obj.name = f"Liner_Rivet_{i+1:02}"
        obj.rotation_mode = "QUATERNION"
        obj.rotation_quaternion = normal.to_track_quat("Z", "Y")
        obj.scale = (0.003, 0.003, 0.0018)
        for face in obj.data.polygons:
            face.use_smooth = True
        obj.select_set(False)
    leather_strip("Chinstrap_Main", p, 0.64, math.pi, mats["leather"], collection)
    leather_strip("Chinstrap_Tail", p, 0, 1.04, mats["leather"], collection,
                  lift=0.0025, holes=True)
    buckle(p, mats["steel"], collection)
