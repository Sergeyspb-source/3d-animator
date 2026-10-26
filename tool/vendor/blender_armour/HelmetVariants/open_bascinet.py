"""Open pointed bascinet with long cheeks and nape."""
import math
from helmet_geometry import skull
from helmet_fittings import lining_rivets, chinstrap

# //#GPT: Define a fully open face instead of retaining an obstructing hidden cap.
def build(p,mats,collection):
    def opening(a,z):
        return z < p["neck_z"] or (math.cos(a)>0.57 and z<0.045)
    skull(p,"Open_Bascinet_Shell",mats["steel"],collection,opening)
    skull(p,"Suspended_Liner",mats["liner"],collection,opening,liner=True)
    lining_rivets(p,mats,collection,front_z=0.056)
    chinstrap(p,mats,collection)
