"""Sallet with its own smoothly extended nape and narrow eye aperture."""
import math
from helmet_geometry import skull
from helmet_fittings import lining_rivets, chinstrap

# //#GPT: Follow a continuous lower border instead of cutting stepped rows from a cylinder.
def build(p,mats,collection):
    def bottom(a):
        return 0.022-0.110*max(0,-math.cos(a))
    def opening(a,z):
        return math.cos(a)>0.55 and 0.038<z<0.052
    skull(p,"Sallet_Shell",mats["steel"],collection,opening,tail=True,bottom=bottom)
    skull(p,"Suspended_Liner",mats["liner"],collection,opening,
          liner=True,tail=True,bottom=bottom)
    lining_rivets(p,mats,collection,front_z=0.063,tail=True,bottom=bottom)
    chinstrap(p,mats,collection,rise=0.043)
