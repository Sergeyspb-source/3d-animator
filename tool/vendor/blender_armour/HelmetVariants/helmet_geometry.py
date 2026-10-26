"""Explicit mesh operations shared by the five real helmet constructions."""
import math

import bmesh
import bpy
from mathutils import Vector

from kettle_hat_details import tube

# //#GPT: Trace actual open borders before adding physical wall thickness.
def boundary_paths(bm):
    pending = {edge for edge in bm.edges if edge.is_boundary}
    paths = []
    while pending:
        edge = min(pending, key=lambda e: e.index)
        pending.remove(edge)
        first, current = edge.verts
        path = [first.co.copy(), current.co.copy()]
        while current != first:
            candidates = sorted((e for e in current.link_edges if e in pending), key=lambda e:e.index)
            if not candidates:
                raise ValueError("Unclosed surface border")
            edge = candidates[0]
            pending.remove(edge)
            current = edge.other_vert(current)
            if current != first:
                path.append(current.co.copy())
        paths.append(path)
    return paths

# //#GPT: Build a solid manifold plate directly, with optional rolled border.
def surface(name, vertices, faces, material, collection, thickness=0.002, trim=0):
    mesh = bpy.data.meshes.new(name)
    mesh.from_pydata(vertices, [], faces)
    mesh.update()
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.remove_doubles(bm, verts=list(bm.verts), dist=1e-7)
    bmesh.ops.delete(bm, geom=[v for v in bm.verts if not v.link_faces], context="VERTS")
    bmesh.ops.dissolve_degenerate(bm,edges=list(bm.edges),dist=1e-8)
    bmesh.ops.recalc_face_normals(bm, faces=list(bm.faces))
    paths = boundary_paths(bm) if trim else []
    bm.to_mesh(mesh)
    bm.free()
    obj = bpy.data.objects.new(name, mesh)
    collection.objects.link(obj)
    obj.data.materials.append(material)
    for face in mesh.polygons:
        face.use_smooth = True
    bpy.context.view_layer.objects.active = obj
    obj.select_set(True)
    wall = obj.modifiers.new("Physical wall", "SOLIDIFY")
    wall.thickness, wall.offset = thickness, -1
    bpy.ops.object.modifier_apply(modifier=wall.name)
    obj.select_set(False)
    for index, points in enumerate(paths):
        tube(f"{name}_Border_{index}", points, trim, material, collection, True)
    return obj

# //#GPT: Use a connected polar skull plus explicit lower rows, retaining face apertures.
def skull(p, name, material, collection, exclude, liner=False, tail=False, bottom=None):
    count, rows = p["segments"], p["crown_rings"]
    vertices = [(0, p["peak_sweep"], p["brow_z"]+p["height"]+p["crest"])]
    levels = [("cap", i/rows) for i in range(1, rows+1)]
    zs = [0.057,0.052,0.045,0.038,0.030,0.022,0.012,0,-0.018,-0.035,
          -0.055,-0.075,-0.095,-0.110,-0.125]
    levels += [("body", z) for z in zs if z < p["brow_z"]-1e-6 and (bottom is None or z>=0.030)]
    if bottom is not None:
        levels += [("lower",i/8) for i in range(1,9)]
    for kind, value in levels:
        for j in range(count):
            angle = math.tau*j/count
            if kind == "cap":
                r = math.sin(value*math.pi/2)
                z = p["brow_z"]+p["height"]*math.cos(value*math.pi/2)
                x, y = p["rx"]*r*math.sin(angle), -p["ry"]*r*math.cos(angle)
                y += p["peak_sweep"]*(1-r)**2
                z += p["crest"]*math.exp(-(x/0.008)**2)*math.cos(value*math.pi/2)**1.4
            else:
                z = 0.030+(bottom(angle)-0.030)*value if kind=="lower" else value
                x, y = body_point(p, angle, z, tail)[:2]
            if liner:
                x, y, z = x*0.95, y*0.95, z-0.004
            vertices.append((x,y,z))
    if liner:
        vertices[0] = (0,p["peak_sweep"]*0.95,vertices[0][2]-0.004)
    faces = [(0,1+j,1+(j+1)%count) for j in range(count)]
    for row in range(len(levels)-1):
        a,b = 1+row*count,1+(row+1)*count
        for j in range(count):
            ids = (a+j,b+j,b+(j+1)%count,a+(j+1)%count)
            z = sum(vertices[k][2] for k in ids)/4 + (0.004 if liner else 0)
            angle = math.tau*(j+0.5)/count
            if not exclude(angle,z):
                faces.append(ids)
    return surface(name,vertices,faces,material,collection,
                   0.001 if liner else p["thickness"],0 if liner else 0.0008)

# //#GPT: Keep the nape shape and sallet tail explicit rather than scaling another helmet.
def body_point(p, angle, z, tail=False):
    down = max(0,min(1,(p["brow_z"]-z)/(p["brow_z"]-p["neck_z"])))
    r = 1-0.08*down+0.025*down**4
    rear = max(0,-math.cos(angle))**5 * down**2
    x = p["rx"]*r*math.sin(angle)*(1-0.5*rear if tail else 1)
    y = -p["ry"]*r*math.cos(angle)
    if tail:
        y += p["tail_length"]*rear
    return Vector((x,y,z))

# //#GPT: Perforate a curved plate using shared-edge cells, avoiding Boolean slivers.
def perforated_patch(name, mapper, material, collection, exclude=None, vents=None):
    us = sorted({round(v,10) for v in [-1+2*i/40 for i in range(41)]+[-0.86,-0.05,0.05,0.86]})
    vs = sorted({round(v,10) for v in [i/24 for i in range(25)]+[0.075,0.14]})
    vertices, faces, cache = [], [], {}
    def vertex(u,v):
        key = (round(u,10),round(v,10))
        if key not in cache:
            cache[key] = len(vertices)
            vertices.append(tuple(mapper(u,v)))
        return cache[key]
    for u0,u1 in zip(us,us[1:]):
        for v0,v1 in zip(vs,vs[1:]):
            u,v = (u0+u1)/2,(v0+v1)/2
            if exclude and exclude(u,v):
                continue
            border = [(u0,v0),(u,v0),(u1,v0),(u1,v),(u1,v1),(u,v1),(u0,v1),(u0,v)]
            outside = [vertex(a,b) for a,b in border]
            if vents and vents(u,v):
                inside = []
                for a,b in border:
                    du,dv = (a-u)/(u1-u0),(b-v)/(v1-v0)
                    length = math.hypot(du,dv)
                    inside.append(vertex(u+du/length*(u1-u0)*0.30,
                                         v+dv/length*(v1-v0)*0.30))
                for i in range(8):
                    j = (i+1)%8
                    faces.append((outside[i],outside[j],inside[j],inside[i]))
            else:
                center = vertex(u,v)
                faces += [(center,outside[i],outside[(i+1)%8]) for i in range(8)]
    return surface(name,vertices,faces,material,collection,0.002,0)

# //#GPT: Create smooth curved strips for cheek pieces, wrappers and their leather straps.
def sector(name, p, theta0,theta1,top,bottom,material,collection,
           radius_scale=1,thickness=0.002,flare=0.10):
    vertices, faces = [], []
    steps, rows = 48,8
    for row in range(rows+1):
        t = row/rows
        for i in range(steps+1):
            a = theta0+(theta1-theta0)*i/steps
            top_z = top(a) if callable(top) else top
            z = top_z+(bottom-top_z)*t
            radius = 1+flare*t*t
            vertices.append((p["rx"]*radius_scale*radius*math.sin(a),
                             -p["ry"]*radius_scale*radius*math.cos(a),z))
    for row in range(rows):
        for i in range(steps):
            a = row*(steps+1)+i
            faces.append((a,a+1,a+steps+2,a+steps+1))
    return surface(name,vertices,faces,material,collection,thickness,0)
