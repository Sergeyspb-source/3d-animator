"""A geometrical ring aventail; approximate weave, not a cloth simulation."""
import math
import bpy
import bmesh
from mathutils import Vector

# //#GPT: Model every ring with a closed toroidal mesh and alternating row tilt.
def aventail(p,mats,collection):
    vertices, faces = [], []
    columns, rows, major, minor = 80,13,12,6
    for row in range(rows):
        z = -0.060-row*0.0073
        flare = row/(rows-1)
        rx,ry = p["rx"]+0.004+0.032*flare**2,p["ry"]+0.009+0.029*flare**2
        for col in range(columns):
            a = math.tau*(col+0.5*(row%2))/columns
            center = Vector((rx*math.sin(a),-ry*math.cos(a),z))
            tangent = Vector((math.cos(a),math.sin(a),0))
            radial = Vector((math.sin(a),-math.cos(a),0))
            vertical = Vector((0,0,1))
            b = vertical*math.cos(math.radians(32))+radial*math.sin(math.radians(32))*(-1 if row%2 else 1)
            normal = tangent.cross(b).normalized()
            start = len(vertices)
            for i in range(major):
                q = math.tau*i/major
                outward = tangent*math.cos(q)+b*math.sin(q)
                for j in range(minor):
                    t = math.tau*j/minor
                    point = center+outward*(0.0052+0.00065*math.cos(t))+normal*0.00065*math.sin(t)
                    vertices.append(tuple(point))
            for i in range(major):
                for j in range(minor):
                    k,l = (i+1)%major,(j+1)%minor
                    faces.append((start+i*minor+j,start+k*minor+j,
                                  start+k*minor+l,start+i*minor+l))
    print("MAIL_VERTICES_READY",len(vertices),flush=True)
    mesh = bpy.data.meshes.new("Aventail_Rings")
    mesh.from_pydata(vertices,[],faces)
    mesh.update()
    print("MAIL_MESH_READY",flush=True)
    bm = bmesh.new()
    bm.from_mesh(mesh)
    bmesh.ops.triangulate(bm,faces=list(bm.faces))
    bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
    bm.to_mesh(mesh)
    bm.free()
    print("MAIL_TRIANGLES_READY",flush=True)
    uv = mesh.uv_layers.new(name="Ring_UV")
    for face in mesh.polygons:
        values = []
        for loop in face.loop_indices:
            local = mesh.loops[loop].vertex_index%(major*minor)
            values.append([local//minor/major,local%minor/minor])
        for axis in (0,1):
            if max(v[axis] for v in values)-min(v[axis] for v in values)>0.5:
                for value in values:
                    if value[axis]<0.5:
                        value[axis] += 1
        for loop,value in zip(face.loop_indices,values):
            uv.data[loop].uv = value
    print("MAIL_UV_READY",flush=True)
    obj = bpy.data.objects.new("Aventail_Rings",mesh)
    collection.objects.link(obj)
    mesh.materials.append(mats["steel"])
    for face in mesh.polygons:
        face.use_smooth = True
    obj["weave"] = "Approximate alternating rings; contacts and interpenetration not simulated"
    obj["ring_count"] = columns*rows
    return obj
