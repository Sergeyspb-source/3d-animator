"""Closed geometric rings on a short sleeve fragment or an inner-elbow gusset."""
import math
import bmesh
import bpy
from mathutils import Vector

# //#GPT: Generate a bounded ring count with analytic UVs; physical weaving is approximate.
def mail(p,mats,collection,gusset=False):
    vertices,faces = [],[]
    columns,rows,major,minor = p["mail_columns"],p["mail_rows"],12,6
    for row in range(rows):
        z = (row/(rows-1)-0.5)*p["half_height"]*1.9
        radius = p["arm_radius"]+0.002+0.003*math.cos(row/(rows-1)*math.pi)
        for col in range(columns):
            a = math.pi+0.14+(math.tau-0.28)*(col+0.5*(row%2))/columns
            if gusset:
                a = math.tau*(col+0.5*(row%2))/columns
            if gusset and math.cos(a)>-0.15:
                continue
            center = Vector((radius*math.sin(a),0.008-radius*0.88*math.cos(a),z))
            tangent = Vector((math.cos(a),0.88*math.sin(a),0)).normalized()
            radial = Vector((math.sin(a),-math.cos(a),0))
            vertical = Vector((0,0,1))
            b = vertical*math.cos(0.55)+radial*math.sin(0.55)*(-1 if row%2 else 1)
            normal = tangent.cross(b).normalized()
            start = len(vertices)
            for i in range(major):
                q = math.tau*i/major
                outward = tangent*math.cos(q)+b*math.sin(q)
                for j in range(minor):
                    t = math.tau*j/minor
                    point = center+outward*(p["ring_radius"]+0.0006*math.cos(t))+normal*0.0006*math.sin(t)
                    vertices.append(tuple(point))
            for i in range(major):
                for j in range(minor):
                    k,l = (i+1)%major,(j+1)%minor
                    faces.append((start+i*minor+j,start+k*minor+j,
                                  start+k*minor+l,start+i*minor+l))
    mesh = bpy.data.meshes.new("Mail_Rings")
    mesh.from_pydata(vertices,[],faces)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm,faces=list(bm.faces))
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    uv = mesh.uv_layers.new(name="Ring_UV")
    values = []
    for face in mesh.polygons:
        coords = []
        for loop in face.loop_indices:
            local = mesh.loops[loop].vertex_index%(major*minor)
            coords.append([local//minor/major,local%minor/minor])
        for axis in (0,1):
            if max(v[axis] for v in coords)-min(v[axis] for v in coords)>0.5:
                for co in coords:
                    if co[axis]<0.5:
                        co[axis] += 1
        for co in coords:
            values.extend(co)
    uv.data.foreach_set("uv",values)
    obj = bpy.data.objects.new("Mail_Rings",mesh)
    collection.objects.link(obj)
    mesh.materials.append(mats["steel"])
    for face in mesh.polygons:
        face.use_smooth = True
    obj["ring_count"] = len(vertices)//(major*minor)
    obj["weave"] = "Approximate ring geometry; contact and collision are not simulated"
    return obj
