"""Deep barbute with a real T-shaped face opening and nasal."""
import math
from helmet_geometry import skull
from helmet_fittings import lining_rivets, chinstrap

# //#GPT: The T cut leaves connected cheek plates and a short central nasal.
def build(p,mats,collection):
    def opening(a,z):
        if z<p["neck_z"]:
            return True
        x = abs(p["rx"]*math.sin(a))
        if math.cos(a)<0.2:
            return False
        return (x<0.026 and z<0.022) or (x<0.026 and x>0.009 and z<0.052) or (0.009<x<0.075 and 0.030<z<0.052)
    skull(p,"Barbute_Shell",mats["steel"],collection,opening)
    skull(p,"Suspended_Liner",mats["liner"],collection,opening,liner=True)
    lining_rivets(p,mats,collection,front_z=0.064)
    chinstrap(p,mats,collection)
