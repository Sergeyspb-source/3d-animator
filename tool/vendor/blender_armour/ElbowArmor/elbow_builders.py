"""The six actual constructions; metal cups remain separate from neighbouring armour."""
import math
from mathutils import Vector
from helmet_geometry import surface
from kettle_hat_details import tube
from elbow_geometry import cup,cup_point,lame,stitches,ribbon
from elbow_fittings import fastening_band,suspension,cup_rivets,lame_rivets
from elbow_mail import mail

# //#GPT: Keep the lining inside the shell and leave the crook open for the fastening straps.
def lining(p,mats,collection,wing):
    q = {**p,"half_width":p["half_width"]*0.95,
         "half_height":p["half_height"]*0.95,"depth":p["depth"]*0.92}
    cup("Padded_Liner",q,mats["liner"],collection,wing*0.95,0.0025,0.0025,0)

# //#GPT: Isolate a mail-sleeve fragment with binding at both cut module boundaries.
def mail_sleeve(p,mats,collection):
    vertices,faces = [],[]
    count = 64
    for z in (-p["half_height"],p["half_height"]):
        for j in range(count):
            a = math.tau*j/count
            vertices.append((p["arm_radius"]*0.94*math.sin(a),
                             0.008-p["arm_radius"]*0.82*math.cos(a),z))
    faces = [(j,(j+1)%count,count+(j+1)%count,count+j) for j in range(count)]
    surface("Textile_Sleeve_Fragment",vertices,faces,mats["liner"],collection,0.0015,0)
    mail(p,mats,collection)
    for sign in (-1,1):
        z = sign*p["half_height"]
        def mapper(u,v):
            a = math.tau*u
            return ((p["arm_radius"]+0.003)*math.sin(a),
                    0.008-(p["arm_radius"]+0.003)*0.88*math.cos(a),
                    z+(v-0.5)*0.009)
        ribbon(f"Mail_Edge_Binding_{sign}",mapper,mats["leather"],collection,64,(),0.0018)
    y = 0.008+p["arm_radius"]*0.88
    for i in range(7):
        z = -p["half_height"]*0.85+i*p["half_height"]*1.7/6
        tube(f"Mail_Seam_Lacing_{i}",[Vector((-0.007,y,z-0.002)),
             Vector((0.007,y+0.002,z+0.002))],0.00085,mats["leather"],collection)

# //#GPT: Keep the forms materially and structurally different rather than recolouring one model.
def build(kind,p,mats,collection):
    if kind=="mail":
        mail_sleeve(p,mats,collection)
        return
    wing = p["wing_width"]
    leather = kind=="leather"
    thickness = p["leather_thickness"] if leather else p["steel_thickness"]
    material = mats["leather"] if leather else mats["steel"]
    cup("Formed_Leather" if leather else "Steel_Couter",p,material,collection,
        wing,thickness,0,0.0012 if leather else 0.0009)
    lining(p,mats,collection,wing)
    if leather:
        stitches(p,mats["liner"],collection)
    else:
        cup_rivets(p,wing,mats,collection)
    articulated = kind in {"articulated_plate","plate_mail_hybrid"}
    suspension(p,mats,collection,articulated)
    for z in (-p["half_height"]*0.52,p["half_height"]*0.52):
        fastening_band(p,z,mats,collection,"Lower_Strap" if z<0 else "Upper_Strap")
    if articulated:
        for sign in (-1,1):
            for index in range(2):
                lame(f"Lame_{sign}_{index}",p,sign,index,mats["steel"],collection)
        lame_rivets(p,mats,collection)
    if kind=="plate_mail_hybrid":
        mail(p,mats,collection,gusset=True)
        for sign in (-1,1):
            def mapper(u,v):
                a = 1.72+(math.tau-3.44)*u
                r = p["arm_radius"]+0.003
                return (r*math.sin(a),0.008-r*0.88*math.cos(a),
                        sign*p["half_height"]*0.95+(v-0.5)*0.007)
            ribbon(f"Gusset_Binding_{sign}",mapper,mats["leather"],collection,40,(),0.0018)
