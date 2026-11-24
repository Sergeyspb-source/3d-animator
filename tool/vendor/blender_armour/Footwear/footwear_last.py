"""Continuous hollow leather uppers and an independent thin leather sole."""
import math
from mathutils import Vector
from helmet_geometry import surface
from kettle_hat_details import tube

# (height, forward of the ankle, back of it, half width): a man's last 27 cm long. The toe low and rounded (its tip
# 1.5-2.5 cm up), the vamp rising evenly to the instep, the heel's back fullest 2-4 cm up and rounding under, the
# instep and the shaft round the leg. (Was a box: the toe a 3.5 cm wall, widest under the ankle.)
PROFILE = ((0.009,0.206,0.064,0.050),(0.015,0.206,0.064,0.050),
           (0.022,0.205,0.064,0.050),(0.030,0.199,0.064,0.050),
           (0.038,0.186,0.063,0.049),(0.046,0.166,0.061,0.048),
           (0.054,0.142,0.058,0.046),(0.062,0.118,0.055,0.045),
           (0.070,0.097,0.052,0.043),(0.078,0.080,0.049,0.041),
           (0.088,0.064,0.046,0.039),(0.100,0.052,0.044,0.037),
           (0.112,0.046,0.042,0.036),(0.140,0.043,0.042,0.037),
           (0.210,0.046,0.045,0.042))
BALL = 0.58   # the ball of the foot: the widest, this share of the way from the ankle to the toe's tip
HEEL = 0.72   # the heel's and the waist's half width against the ball's

# //#GPT: Interpolate the last so upper, tongue, seams and bindings share one measurable form.
def profile(p,z):
    for low,high in zip(PROFILE,PROFILE[1:]):
        if z<=high[0]:
            t = max(0,min(1,(z-low[0])/(high[0]-low[0])))
            result = [low[i]+(high[i]-low[i])*t for i in (1,2,3)]
            return (result[0]*p["foot_length"]/0.270,result[1]*p["foot_length"]/0.270,
                    result[2]*p["foot_width"]/0.100)
    raise ValueError("Shaft height exceeds last profile")

def plan(c,z):
    """The half width at a slice's point (a share of the slice's half width) by c: its place from the ankle's line to
    the toe's tip (0..1) or to the heel's back (0..-1). Low down a foot's outline: widest across the ball, narrower at
    the waist and the heel, the toe and the heel rounded; up the instep and the shaft more and more a round (|sin|)."""
    if c>=0:
        rise = HEEL+(1-HEEL)*min(1,c/BALL)**2*(3-2*min(1,c/BALL))
        u = max(0,(c-BALL)/(1-BALL))
        g = rise*max(0,1-u**2.6)**(1/2.6)
    else:
        g = HEEL*max(0,1-(-c)**2.4)**(1/2.4)
    k = max(0,min(1,(z-0.045)/0.055))
    k = k*k*(3-2*k)
    return g+(math.sqrt(max(0,1-c*c))-g)*k

# //#GPT: Offset the toe slightly toward the big toe to create genuinely handed footwear.
def last_point(p,a,z,scale=1):
    front,back,width = profile(p,z)
    c,s = math.cos(a),math.sin(a)
    x = width*math.copysign(plan(c,z),s)-0.005*max(0,c)**3*(1-z/0.22)
    y = -front*c if c>=0 else -back*c
    return Vector((x*scale,y*scale,z))

# //#GPT: Retain an actual top opening and a lacing throat, rather than a solid capped boot.
def upper(p,mats,collection,laced=True):
    count = p["segments"]
    zs = sorted(set([row[0] for row in PROFILE if row[0]<p["shaft_height"]]+[p["shaft_height"]]))
    for name,scale,material in (("Leather_Upper",1,mats["leather"]),("Inner_Lining",0.95,mats["liner"])):
        vertices = [tuple(last_point(p,math.tau*j/count,z,scale)) for z in zs for j in range(count)]
        faces = []
        for row in range(len(zs)-1):
            for j in range(count):
                a = math.tau*(j+0.5)/count
                throat = abs(math.atan2(math.sin(a),math.cos(a)))<0.16
                if laced and throat and (zs[row]+zs[row+1])/2>0.054:
                    continue
                k = row*count+j
                n = row*count+(j+1)%count
                faces.append((k,n,n+count,k+count))
        surface(name,vertices,faces,material,collection,
                p["leather_thickness"] if scale==1 else 0.0012,0.0006 if scale==1 else 0)
    points = [last_point(p,math.tau*j/count,0.022)+Vector((0,0,-0.006)) for j in range(count)]
    tube("Sole_Seam",points,0.00065,mats["liner"],collection,True)

# //#GPT: Close the bottom with a leather sole while keeping the leg entry open above.
def sole(p,mats,collection):
    count = p["segments"]
    vertices = []
    for j in range(count):
        point = last_point(p,math.tau*j/count,0.009,1.018)
        point.z = p["sole_thickness"]
        vertices.append(tuple(point))
    surface("Leather_Sole",vertices,[tuple(range(count))],mats["liner"],collection,
            p["sole_thickness"],0.0006)

# //#GPT: Place a separate tongue and sewn leather loops at the real throat boundary.
def laces(p,mats,collection):
    top = p["shaft_height"]-0.004
    rows = max(3,int((top-0.054)/0.016))
    vertices,faces = [],[]
    for row in range(17):
        z = 0.052+(top-0.052)*row/16
        for j in range(5):
            point = last_point(p,-0.34+0.68*j/4,z)
            point.y += 0.002
            vertices.append(tuple(point))
    for row in range(16):
        for j in range(4):
            k = row*5+j
            faces.append((k,k+1,k+6,k+5))
    surface("Leather_Tongue",vertices,faces,mats["leather"],collection,0.0018,0)
    for row in range(rows):
        z = 0.060+(top-0.060)*row/max(1,rows-1)
        a,b = last_point(p,-0.23,z),last_point(p,0.23,z+0.004)
        a.y -= 0.002
        b.y -= 0.002
        tube(f"Lace_{row}",[a,(a+b)/2+Vector((0,-0.003,0)),b],0.00085,mats["liner"],collection)
