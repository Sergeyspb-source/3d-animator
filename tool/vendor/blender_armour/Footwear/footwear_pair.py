"""Anatomical origins and mirrored copies, with baked positive transforms."""
import bmesh
import bpy
from mathutils import Matrix

# //#GPT: Make the ankle centre the authoring origin and bake all primitive transforms.
def canonical_meshes(objects,p):
    bpy.context.view_layer.update()
    for obj in objects:
        world = obj.matrix_world.copy()
        for vertex in obj.data.vertices:
            vertex.co = world@vertex.co
            vertex.co.z -= p["ankle_height"]
        obj.matrix_world = Matrix.Identity(4)
        bm = bmesh.new()
        bm.from_mesh(obj.data)
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.to_mesh(obj.data)
        bm.free()
        obj.data.update()

# //#GPT: Reflect geometry and winding, not negative object scale, to preserve outward normals.
def mirrored_pair(objects,collection,p):
    roots = []
    for side in ("right","left"):
        root = bpy.data.objects.new("Footwear_"+side.title(),None)
        collection.objects.link(root)
        root["side"],root["units"],root["prototype"] = side,"metres",True
        root["anatomical_origin"] = "Ankle joint centre"
        root["front"],root["up"] = "-Y","+Z"
        for name,z in (("Ankle_Attach",0),("Sole_Attach",-p["ankle_height"])):
            socket = bpy.data.objects.new(f"{name}_{side}",None)
            collection.objects.link(socket)
            socket.parent = root
            socket.location.z = z
        roots.append(root)
    right_root,left_root = roots
    left = []
    for obj in objects:
        name = obj.name
        obj.name = "R_"+name
        obj.parent = right_root
        clone = obj.copy()
        clone.data = obj.data.copy()
        clone.name = "L_"+name
        collection.objects.link(clone)
        for vertex in clone.data.vertices:
            vertex.co.x *= -1
        bm = bmesh.new()
        bm.from_mesh(clone.data)
        bmesh.ops.reverse_faces(bm,faces=list(bm.faces))
        bmesh.ops.recalc_face_normals(bm,faces=list(bm.faces))
        bm.to_mesh(clone.data)
        bm.free()
        clone.data.update()
        clone.parent = left_root
        left.append(clone)
    return right_root,left_root,left
