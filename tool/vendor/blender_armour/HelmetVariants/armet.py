"""Armet: compact skull, separate hinged cheek plates, visor and wrapper."""
import math
from mathutils import Vector
from kettle_hat_details import tube
from helmet_geometry import skull,sector
from helmet_fittings import pivot,parent_at_pivot,rivet,rear_buckle
from visored_bascinet import visor

# //#GPT: Keep the visor and cheek halves editable around explicit local pivots.
def build(p,mats,collection):
    def opening(a,z):
        return z<p["neck_z"] or (math.cos(a)>-0.05 and z<0.070)
    skull(p,"Armet_Skull",mats["steel"],collection,opening)
    skull(p,"Suspended_Liner",mats["liner"],collection,opening,liner=True)
    def cheek_top(a):
        return 0.044+0.026*max(0,min(1,(abs(a)-0.85)/0.5))
    for side in (-1,1):
        angles = (0.025,2.0) if side==1 else (-2.0,-0.025)
        cheek = sector(f"Cheek_Plate_{side}",p,*angles,cheek_top,-0.084,
                       mats["steel"],collection,radius_scale=0.98,flare=-0.15)
        hinge = pivot(f"Cheek_Pivot_{side}",(side*p["rx"],0.015,0.025),collection,"Z")
        parent_at_pivot([cheek],hinge)
        hinge.rotation_euler.z = side*math.radians(p["cheek_angle"])
        rivet(f"Cheek_Hinge_{side}",(side*p["rx"],0.015,0.025),(side,0,0),
              0.006,mats["steel"],collection,0.0025)
    visor(p,mats,collection,short=True)
    sector("Wrapper",p,-1.80,1.80,-0.040,-0.122,mats["steel"],collection,
           radius_scale=1.04,flare=-0.18)
    sector("Wrapper_Rear_Strap",p,1.80,math.tau-1.80,-0.066,-0.083,
           mats["leather"],collection,radius_scale=1.05,flare=0)
    rear_buckle(p,mats,collection)
    tube("Rondel_Stem",[Vector((0,p["ry"]*0.91,-0.027)),
         Vector((0,p["ry"]+0.010,-0.027))],0.0025,mats["steel"],collection)
    rivet("Rear_Rondel",(0,p["ry"]+0.010,-0.027),(0,1,0),0.016,
          mats["steel"],collection,0.003)
