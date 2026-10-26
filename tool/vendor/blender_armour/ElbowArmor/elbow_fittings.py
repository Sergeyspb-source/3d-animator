"""Readable attachment details on the inner side of a modular elbow guard."""
import math
from mathutils import Vector
from helmet_geometry import surface
from helmet_fittings import rivet
from kettle_hat_details import tube
from elbow_geometry import ribbon,cup_point

# //#GPT: Curve a closed strap around the arm and expose real adjustment holes at the rear.
def fastening_band(p,z,mats,collection,name):
    rx,ry = p["arm_radius"],p["arm_radius"]*0.82
    def mapper(u,v):
        a = math.tau*u
        return (rx*math.sin(a),0.002-ry*math.cos(a),z+p["strap_width"]*(v-0.5))
    ribbon(name,mapper,mats["leather"],collection,holes=(53,56,59))
    y = 0.002+ry+0.002
    x = -0.012
    frame = [Vector((x+dx,y,z+dz)) for dx,dz in
             ((-0.010,-0.009),(0.010,-0.009),(0.010,0.009),(-0.010,0.009))]
    tube(name+"_Buckle",frame,0.0012,mats["steel"],collection,True)
    tube(name+"_Tongue",[Vector((x-0.008,y,z)),Vector((x+0.009,y,z))],
         0.0009,mats["steel"],collection)
    for side in (-1,1):
        a = math.pi/2*side
        point = Vector((side*rx,0.002,z))
        rivet(name+f"_Anchor_{side}",point,(side,0,0),0.0028,mats["steel"],collection)

# //#GPT: Put the suspension leathers inside the cup rather than on top of its metal face.
def suspension(p,mats,collection,articulated=False):
    half = p["half_height"]*(1.45 if articulated else 0.84)
    for side in (-1,1):
        vertices,faces = [],[]
        for row in range(25):
            z = -half+2*half*row/24
            for edge in (-1,1):
                x = side*0.021+edge*0.005
                r = min(1,math.hypot(x/p["half_width"],z/p["half_height"]))
                y = 0.006-p["depth"]*max(0,1-r*r)**0.58-p["point"]*(1-r)**1.4+0.005
                if articulated:
                    blend = max(0,min(1,(abs(z)/p["half_height"]-0.65)/0.35))
                    target = 0.010-p["arm_radius"]*0.83*math.sqrt(1-(x/p["arm_radius"])**2)
                    y = y*(1-blend)+target*blend
                vertices.append((x,y,z))
        for row in range(24):
            k = row*2
            faces.append((k,k+1,k+3,k+2))
        surface(f"Internal_Leather_{side}",vertices,faces,mats["leather"],collection,0.002,0)

# //#GPT: Locate the lining rivets on the actual curved surface.
def cup_rivets(p,wing,mats,collection):
    for i,a in enumerate((0.45,1.25,2.25,3.95,5.05,5.80)):
        point = cup_point(p,a,0.86,wing,offset=-0.001)
        rivet(f"Cup_Rivet_{i}",point,(point.x,-0.08,point.z),0.0025,
              mats["steel"],collection,0.0016)

# //#GPT: Expose the short lame attachment rows without claiming a completed mechanical rig.
def lame_rivets(p,mats,collection):
    for sign in (-1,1):
        for index in range(2):
            radius = 1-0.07*index-0.02
            z = sign*(p["half_height"]*0.72+index*0.016+0.012)
            for side in (-1,1):
                a = side*1.10
                point = Vector((p["arm_radius"]*radius*math.sin(a),
                                0.006-p["arm_radius"]*0.90*radius*math.cos(a),z))
                rivet(f"Lame_Rivet_{sign}_{index}_{side}",point,(math.sin(a),-math.cos(a),0),
                      0.0026,mats["steel"],collection,0.0016)
