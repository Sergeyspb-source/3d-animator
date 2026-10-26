"""Small physical fittings; reuses the tested kettle-hat strap construction."""
import math

import bpy
from mathutils import Vector

from kettle_hat_details import relocate, leather_strip, buckle, tube
from helmet_geometry import body_point

# //#GPT: Orient round hardware to a real plate surface.
def rivet(name, point, normal, radius, material, collection, depth=0.0018):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=16,ring_count=8,radius=1,location=point)
    obj = relocate(bpy.context.object,collection,material)
    obj.name = name
    obj.rotation_mode = "QUATERNION"
    obj.rotation_quaternion = Vector(normal).normalized().to_track_quat("Z","Y")
    obj.scale = (radius,radius,depth)
    for face in obj.data.polygons:
        face.use_smooth = True
    obj.select_set(False)
    return obj

# //#GPT: Place lining rivets along the lower metal coverage while keeping face clear.
def lining_rivets(p,mats,collection,front_z=0.060,tail=False,bottom=None):
    for i in range(18):
        a = math.tau*(i+0.5)/18
        front = max(0,math.cos(a))**0.3
        z = (p["neck_z"]+0.020)*(1-front)+front_z*front
        if bottom is not None:
            z = max(bottom(a)+0.012,front_z if math.cos(a)>0.25 else -1)
        point = body_point(p,a,z,tail)
        normal = Vector((math.sin(a),-math.cos(a),0.10)).normalized()
        rivet(f"Lining_Rivet_{i:02}",point+normal*0.0005,normal,0.0025,
              mats["steel"],collection)

# //#GPT: Retain the proven physically perforated chinstrap with one adjustable buckle.
def chinstrap(p,mats,collection,rise=0):
    previous = set(collection.objects)
    strap = {"crown_radius_x":p["rx"],"strap_width":p["strap_width"],
             "strap_drop":p["strap_drop"]}
    leather_strip("Chinstrap_Main",strap,0.64,math.pi,mats["leather"],collection)
    leather_strip("Chinstrap_Tail",strap,0,1.04,mats["leather"],collection,
                  lift=0.0025,holes=True)
    buckle(strap,mats["steel"],collection)
    for obj in set(collection.objects)-previous:
        obj.location.z += rise

# //#GPT: Use an actual transform parent for the visor rather than an inert hinge decoration.
def pivot(name,location,collection,axis="X"):
    obj = bpy.data.objects.new(name,None)
    collection.objects.link(obj)
    obj.location = location
    obj["rotation_axis"] = axis
    return obj

# //#GPT: Preserve current world placement when assigning a local mechanical pivot.
def parent_at_pivot(objects,empty):
    bpy.context.view_layer.update()
    for obj in objects:
        world = obj.matrix_world.copy()
        obj.parent = empty
        obj.matrix_world = world

# //#GPT: Connect the visor front to its transverse axle with separate solid side arms.
def visor_hardware(p,mats,collection,visor,y_edge,top_z):
    from helmet_geometry import surface
    axis_y, axis_z = -0.020,top_z
    hinge = pivot("Visor_Pivot",(0,axis_y,axis_z),collection)
    parts = [visor]
    for side in (-1,1):
        x = side*p["rx"]
        arm = surface(f"Visor_Arm_{side}",[(x,axis_y,axis_z+0.013),
                      (x,y_edge,top_z),(x,y_edge,top_z-0.025),
                      (x,axis_y,axis_z-0.013)],[(0,1,2,3)],mats["steel"],collection)
        parts.append(arm)
        rivet(f"Visor_Axle_{side}",(x,axis_y,axis_z),(side,0,0),0.009,
              mats["steel"],collection,0.003)
    parent_at_pivot(parts,hinge)
    hinge.rotation_euler.x = -math.radians(p["visor_angle"])
    return hinge

# //#GPT: Construct a modest buckle at the rear wrapper strap.
def rear_buckle(p,mats,collection,z=-0.075):
    y = p["ry"]*1.05
    points = [Vector((x,y,z+dz)) for x,dz in
              ((-0.012,-0.009),(0.012,-0.009),(0.012,0.009),(-0.012,0.009))]
    tube("Wrapper_Buckle",points,0.0015,mats["steel"],collection,True)
    tube("Wrapper_Tongue",[Vector((0,y,z)),Vector((0.010,y,z))],
         0.001,mats["steel"],collection)
