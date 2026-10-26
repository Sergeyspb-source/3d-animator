"""Approximate ring mail on the dorsum and a short ankle cuff, with analytic UVs."""
import math
import bmesh
import bpy
from mathutils import Vector
from footwear_fittings import plate_point
from footwear_last import profile,last_point

# //#GPT: Append a closed toroidal ring in a local tangent frame rather than a flat billboard.
def add_ring(vertices,faces,center,tangent,vertical,radius,tilt):
    tangent = Vector(tangent).normalized()
    vertical = (Vector(vertical)-tangent*Vector(vertical).dot(tangent)).normalized()
    normal = tangent.cross(vertical).normalized()
    vertical = vertical*math.cos(tilt)+normal*math.sin(tilt)
    normal = tangent.cross(vertical).normalized()
    start,major,minor = len(vertices),10,4
    for i in range(major):
        a = math.tau*i/major
        radial = tangent*math.cos(a)+vertical*math.sin(a)
        for j in range(minor):
            b = math.tau*j/minor
            vertices.append(tuple(center+radial*(radius+0.00055*math.cos(b))+normal*0.00055*math.sin(b)))
    for i in range(major):
        for j in range(minor):
            k,l = (i+1)%major,(j+1)%minor
            faces.append((start+i*minor+j,start+k*minor+j,start+k*minor+l,start+i*minor+l))

# //#GPT: Match dorsal rings to the same profile used by steel protection.
def foot_mail(p,mats,collection,cuff_only=False):
    vertices,faces = [],[]
    scale = p["foot_length"]/0.270
    if not cuff_only:
        for row in range(p["mail_rows"]):
            y = (-0.200+0.162*row/(p["mail_rows"]-1))*scale
            for j in range(p["mail_columns"]):
                a = -1.40+2.80*(j+0.5*(row%2))/(p["mail_columns"]-0.5)
                point = plate_point(p,y,a,0.005)
                normal = Vector((math.sin(a),-0.28,math.cos(a))).normalized()
                point += normal*0.001
                add_ring(vertices,faces,point,(math.cos(a),0,-math.sin(a)),
                         (0,1,0.36*math.cos(a)),p["ring_radius"],0.42*(-1 if row%2 else 1))
    rows = p["cuff_rows"]
    for row in range(rows):
        z = 0.082+(p["shaft_height"]-0.085)*row/(rows-1)
        front,back,width = profile(p,z)
        for j in range(40):
            a = math.tau*(j+0.5*(row%2))/40
            point = last_point(p,a,z)
            point += Vector((math.sin(a),-math.cos(a),0))*0.004
            add_ring(vertices,faces,point,(math.cos(a),math.sin(a),0),(0,0,1),
                     p["ring_radius"],0.45*(-1 if row%2 else 1))
    mesh = bpy.data.meshes.new("FootMail_Rings")
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
            local = mesh.loops[loop].vertex_index%40
            coords.append([local//4/10,local%4/4])
        for axis in (0,1):
            if max(v[axis] for v in coords)-min(v[axis] for v in coords)>0.5:
                for co in coords:
                    if co[axis]<0.5:
                        co[axis] += 1
        for co in coords:
            values.extend(co)
    uv.data.foreach_set("uv",values)
    obj = bpy.data.objects.new("FootMail_Rings",mesh)
    collection.objects.link(obj)
    mesh.materials.append(mats["steel"])
    for face in mesh.polygons:
        face.use_smooth = True
    obj["ring_count"] = len(vertices)//40
    obj["weave"] = "Approximate geometry; no rivet reconstruction, contact or cloth simulation"
