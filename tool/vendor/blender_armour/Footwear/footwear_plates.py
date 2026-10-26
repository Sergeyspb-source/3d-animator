"""Separate toecaps, overlapping dorsal lames and a short ankle/heel guard."""
import math
from helmet_geometry import surface
from footwear_fittings import steel_lame,ankle_strap,plate_point
from footwear_last import last_point

# //#GPT: Keep pointed extensions hollow and separate, without adding a steel walking sole.
def toe_cap(p,mats,collection):
    scale = p["foot_length"]/0.270
    start,end = -0.210*scale-p["toe_extension"],-0.163*scale
    vertices,faces = [],[]
    for row in range(13):
        t = row/12
        taper = math.sin(t*math.pi/2)**0.70
        y = start+(end-start)*t
        for j in range(33):
            a = -1.56+3.12*j/32
            rear = plate_point(p,end,a,0.003)
            if y>=-0.205*scale:
                point = plate_point(p,y,a,0.004)
                vertices.append(tuple(point))
            else:
                edge = plate_point(p,-0.205*scale,a,0.004)
                blend = (y-start)/(-0.205*scale-start)
                x = edge.x*math.sin(blend*math.pi/2)+0.001*math.sin(a)*(1-blend)
                z = 0.015+(edge.z-0.015)*blend+0.006*(1-blend)*math.cos(a)
                vertices.append((x,y,z))
    for row in range(12):
        for j in range(32):
            k = row*33+j
            faces.append((k,k+1,k+34,k+33))
    surface("Steel_Toe_Cap",vertices,faces,mats["steel"],collection,
            p["steel_thickness"],0.0007)

# //#GPT: Cover the heel and ankle while leaving the leg-entry opening unobstructed.
def heel_guard(p,mats,collection):
    vertices,faces = [],[]
    for row in range(6):
        t = row/5
        z = 0.030+0.077*t
        for j in range(49):
            a = 1.02+(math.tau-2.04)*j/48
            point = last_point(p,a,z)
            point.x += 0.0035*math.sin(a)
            point.y -= 0.0035*math.cos(a)
            vertices.append(tuple(point))
    for row in range(5):
        for j in range(48):
            k = row*49+j
            faces.append((k,k+1,k+50,k+49))
    surface("Steel_Heel_Guard",vertices,faces,mats["steel"],collection,
            p["steel_thickness"],0.0007)
    ankle_strap(p,0.098,mats,collection,"Ankle_Fastening")

# //#GPT: Restrict the hybrid to the forefoot so its leather and mail construction remains visible.
def plate_foot(p,mats,collection,hybrid=False):
    toe_cap(p,mats,collection)
    scale = p["foot_length"]/0.270
    for i in range(3 if hybrid else 6):
        start = (-0.177+i*0.021)*scale
        steel_lame(p,mats,collection,i,start,start+0.026*scale)
    if not hybrid:
        heel_guard(p,mats,collection)
