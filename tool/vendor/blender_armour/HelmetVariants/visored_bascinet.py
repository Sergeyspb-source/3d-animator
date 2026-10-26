"""Pointed bascinet, projecting visor, vervelles and geometric aventail."""
import math
from mathutils import Vector
from kettle_hat_details import tube
from helmet_geometry import skull,perforated_patch,sector
from helmet_fittings import visor_hardware,rivet
from helmet_mail import aventail

# //#GPT: Construct slit and right-side breaths as real perforations.
def visor(p,mats,collection,short=False):
    top = 0.070 if short else 0.054
    height = 0.105 if short else 0.142
    width = p["rx"]*0.98
    def mapper(u,v):
        ridge = (1-abs(u))**1.3
        x = width*u*(1-0.12*v)
        y = -p["ry"]*math.sqrt(max(0.02,1-(x/(p["rx"]*1.02))**2))
        y -= p["visor_projection"]*ridge*math.sin(math.pi*v)**0.75
        return (x,y,top-height*v+0.018*abs(u)*v)
    def eye(u,v):
        return 0.075<v<0.14 and 0.05<abs(u)<0.86
    def breaths(u,v):
        return u>0 and any(abs(u-c)<0.021 for c in (0.325,0.475,0.625)) and any(abs(v-r)<0.018 for r in (0.354,0.479,0.604,0.729))
    obj = perforated_patch("Visor",mapper,mats["steel"],collection,eye,breaths)
    edge_y = -p["ry"]*math.sqrt(1-(0.98/1.02)**2)
    return visor_hardware(p,mats,collection,obj,edge_y,top)

# //#GPT: Suspend the aventail on a leather carrier with visible pins and lacing.
def build(p,mats,collection):
    def opening(a,z):
        return z<p["neck_z"] or (math.cos(a)>0.48 and z<0.057)
    skull(p,"Visored_Bascinet_Shell",mats["steel"],collection,opening)
    skull(p,"Suspended_Liner",mats["liner"],collection,opening,liner=True)
    visor(p,mats,collection)
    sector("Aventail_Carrier",p,0.97,math.tau-0.97,-0.040,-0.058,
           mats["leather"],collection,radius_scale=1.01,thickness=0.002)
    cord = []
    for i in range(30):
        a = 0.98+(math.tau-1.96)*i/29
        point = Vector((p["rx"]*1.025*math.sin(a),-p["ry"]*1.025*math.cos(a),-0.048))
        normal = Vector((math.sin(a),-math.cos(a),0))
        rivet(f"Vervelle_{i:02}",point,normal,0.0022,mats["steel"],collection)
        cord.append(point+normal*0.0018)
    tube("Aventail_Lacing",cord,0.00075,mats["leather"],collection)
    aventail(p,mats,collection)
