"""Ankle straps and plate rivets, with fasteners on the outside of each foot."""
import math
from mathutils import Vector
from elbow_geometry import ribbon
from helmet_fittings import rivet
from kettle_hat_details import tube
from footwear_last import profile

# //#GPT: Keep the leather strap curved around the real shaft and expose the outer buckle.
def ankle_strap(p,z,mats,collection,name):
    front,back,width = profile(p,z)
    rx,ry = width+0.003,max(front,back)+0.002
    def mapper(u,v):
        a = math.tau*u
        return (rx*math.sin(a),-ry*math.cos(a),z+(v-0.5)*0.012)
    ribbon(name,mapper,mats["leather"],collection,96,(29,32,35),0.0018)
    x = rx+0.0015
    points = [Vector((x,y,z+dz)) for y,dz in
              ((-0.010,-0.009),(0.010,-0.009),(0.010,0.009),(-0.010,0.009))]
    tube(name+"_Buckle",points,0.0012,mats["steel"],collection,True)
    tube(name+"_Tongue",[Vector((x,-0.008,z)),Vector((x,0.009,z))],
         0.00085,mats["steel"],collection)
    rivet(name+"_Rivet",(x,0.014,z),(1,0,0),0.002,mats["steel"],collection,0.0012)

# //#GPT: Use the same plate profile for fasteners and the actual steel shell.
def plate_point(p,y,a,lift=0):
    from footwear_last import PROFILE,last_point
    target = max(0.0431*p["foot_length"]/0.270,-y)
    centre_z = 0.105
    for low,high in zip(PROFILE[:7],PROFILE[1:8]):
        front0,front1 = low[1]*p["foot_length"]/0.270,high[1]*p["foot_length"]/0.270
        if front0>=target>=front1 and front0!=front1:
            centre_z = low[0]+(high[0]-low[0])*(front0-target)/(front0-front1)
            break
    z = 0.012+(centre_z-0.012)*math.cos(a)
    front,_,width = profile(p,z)
    c = max(0,min(1,-y/front))
    theta = math.acos(c)*(1 if a>=0 else -1)
    point = last_point(p,theta,z)
    point.x += 0.0025*math.sin(a)
    point.y = y
    point.z += lift
    return point

# //#GPT: Make transverse plates with independent, inspectable rivet attachments.
def steel_lame(p,mats,collection,index,start,end):
    from helmet_geometry import surface
    vertices,faces = [],[]
    for row in range(5):
        y = start+(end-start)*row/4
        for j in range(33):
            a = -1.56+3.12*j/32
            vertices.append(tuple(plate_point(p,y,a,0.003+index*0.0006)))
    for row in range(4):
        for j in range(32):
            k = row*33+j
            faces.append((k,k+1,k+34,k+33))
    surface(f"Steel_Lame_{index}",vertices,faces,mats["steel"],collection,
            p["steel_thickness"],0.0006)
    for side in (-1,1):
        a = side*1.20
        point = plate_point(p,(start+end)/2,a,0.004+index*0.0006)
        rivet(f"Lame_Rivet_{index}_{side}",point,(math.sin(a),0,math.cos(a)),
              0.0023,mats["steel"],collection,0.0012)
