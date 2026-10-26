"""Cup shells, curved fastening bands and short overlapping elbow lames."""
import math
import bpy
from mathutils import Vector
from helmet_geometry import surface
from kettle_hat_details import tube

# //#GPT: Shape the point and integral lateral fan from a single connected shell.
def cup_point(p,a,r,wing=0,offset=0):
    fan = max(0,math.cos(a))**2
    x = (p["half_width"]+wing*fan*r*r)*r*math.cos(a)
    z = p["half_height"]*r*math.sin(a)*(1+0.16*fan*wing/0.04)
    y = 0.006-p["depth"]*max(0,1-r*r)**0.58
    y -= p["point"]*(1-r)**1.4
    y -= 0.008*fan*r*r*wing/0.04
    return Vector((x,y+offset,z))

# //#GPT: Preserve physical thickness, a continuous rolled edge and an open inner elbow.
def cup(name,p,material,collection,wing=0,thickness=0.002,offset=0,trim=0.001):
    count,rows = p["segments"],p["cup_rings"]
    vertices = [tuple(cup_point(p,0,0,wing,offset))]
    for row in range(1,rows+1):
        vertices += [tuple(cup_point(p,math.tau*j/count,row/rows,wing,offset))
                     for j in range(count)]
    faces = [(0,1+j,1+(j+1)%count) for j in range(count)]
    for row in range(rows-1):
        a,b = 1+row*count,1+(row+1)*count
        faces += [(a+j,b+j,b+(j+1)%count,a+(j+1)%count) for j in range(count)]
    return surface(name,vertices,faces,material,collection,thickness,trim)

# //#GPT: Use integer grid keys for repeatable real strap holes without Boolean slivers.
def ribbon(name,mapper,material,collection,columns=96,holes=(),thickness=0.002):
    vertices,faces,cache = [],[],{}
    rows = 3
    def vertex(x,y):
        key = (x,y)
        if key not in cache:
            cache[key] = len(vertices)
            vertices.append(tuple(mapper(x/(columns*2),y/(rows*2))))
        return cache[key]
    for col in range(columns):
        for row in range(rows):
            cx,cy = col*2+1,row*2+1
            keys = [(cx-1,cy-1),(cx,cy-1),(cx+1,cy-1),(cx+1,cy),
                    (cx+1,cy+1),(cx,cy+1),(cx-1,cy+1),(cx-1,cy)]
            outside = [vertex(x,y) for x,y in keys]
            if col in holes and row==1:
                inside = []
                for x,y in keys:
                    dx,dy = x-cx,y-cy
                    length = math.hypot(dx,dy)
                    inside.append(vertex(cx+dx/length*0.50,cy+dy/length*0.50))
                faces += [(outside[i],outside[(i+1)%8],inside[(i+1)%8],inside[i])
                          for i in range(8)]
            else:
                center = vertex(cx,cy)
                faces += [(center,outside[i],outside[(i+1)%8]) for i in range(8)]
    return surface(name,vertices,faces,material,collection,thickness,0)

# //#GPT: Make the small arm-connection lames distinct solids instead of a full vambrace.
def lame(name,p,sign,index,material,collection):
    vertices,faces = [],[]
    count,rows = 40,4
    for row in range(rows+1):
        t = row/rows
        for j in range(count+1):
            a = -1.25+2.50*j/count
            radius = 1-0.07*index-0.04*t
            x = p["arm_radius"]*radius*math.sin(a)
            y = 0.006-p["arm_radius"]*0.90*radius*math.cos(a)
            z = sign*(p["half_height"]*0.72+index*0.016+t*0.024)
            vertices.append((x,y,z))
    for row in range(rows):
        for j in range(count):
            k = row*(count+1)+j
            faces.append((k,k+1,k+count+2,k+count+1))
    return surface(name,vertices,faces,material,collection,p["steel_thickness"],0.0007)

# //#GPT: Keep many short seam stitches in one capped curve for efficient export.
def stitches(p,material,collection):
    curve = bpy.data.curves.new("Leather_Stitches","CURVE")
    curve.dimensions,curve.bevel_depth,curve.bevel_resolution = "3D",0.00045,1
    curve.use_fill_caps = True
    for i in range(48):
        a = math.tau*(i+0.15)/48
        spline = curve.splines.new("POLY")
        spline.points.add(1)
        for point,angle in zip(spline.points,(a,a+0.070)):
            co = cup_point(p,angle,0.92,offset=-0.0007)
            point.co = (*co,1)
    obj = bpy.data.objects.new("Leather_Stitches",curve)
    collection.objects.link(obj)
    curve.materials.append(material)
    return obj
