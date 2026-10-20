"""Runs INSIDE Blender (background): builds a modular dungeon kit procedurally and exports it as one GLB.

    blender -b -P blender_modkit.py -- out_dir mat_dir [cell=4] [height=3] [thick=0.5] [seed=1] [preview=png]
                                       [wall=dungeon_wall] [floor=dungeon_floor] [wood=dungeon_wood]

Every piece fits a cell x cell square (pivot: centre of the cell, at floor level, floor top at z=0); wall pieces stand at
the +Y edge of the cell (rotate by 90 degrees for the other edges). Pieces are separate objects of one scene:
floor ceiling wall wall_b wall_door wall_arch wall_window corner corner_inner pillar stairs door.
Writes kit.glb and kit.json (collision boxes per piece in Godot axes: x, y up, z) and prints KIT_ lines.
"""
import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
from mathutils import Vector

argv = sys.argv[sys.argv.index("--") + 1:]
out_dir, mat_dir = Path(argv[0]), Path(argv[1])
opt = dict(a.split("=", 1) for a in argv[2:] if "=" in a)
C = float(opt.get("cell", 4))
H = float(opt.get("height", 3))
T = float(opt.get("thick", 0.5))
SEED = int(opt.get("seed", 1))
TILE = 2.0
FLOOR_T = 0.3
NC = max(2, round(H / 0.38))        # block courses per wall
CH = H / NC                         # course height
GAP = 0.02
out_dir.mkdir(parents=True, exist_ok=True)

bpy.ops.wm.read_factory_settings(use_empty=True)


# ---------------------------------------------------------------- materials
def make_material(name, folder, stem, flat=None):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    nt = m.node_tree
    bsdf = next(n for n in nt.nodes if n.type == "BSDF_PRINCIPLED")
    if flat:
        bsdf.inputs["Base Color"].default_value = (*flat, 1)
        bsdf.inputs["Roughness"].default_value = 0.95
        return m

    def tex(fn, nonc):
        n = nt.nodes.new("ShaderNodeTexImage")
        n.image = bpy.data.images.load(str(Path(folder) / stem / f"{stem}_{fn}.png"))
        if nonc:
            n.image.colorspace_settings.name = "Non-Color"
        return n

    a, r, nr = tex("albedo", False), tex("roughness", True), tex("normal", True)
    nt.links.new(a.outputs["Color"], bsdf.inputs["Base Color"])
    nt.links.new(r.outputs["Color"], bsdf.inputs["Roughness"])
    nm = nt.nodes.new("ShaderNodeNormalMap")
    nt.links.new(nr.outputs["Color"], nm.inputs["Color"])
    nt.links.new(nm.outputs["Normal"], bsdf.inputs["Normal"])
    return m


MATS = [make_material("stone", mat_dir, opt.get("wall", "dungeon_wall")),
        make_material("mortar", mat_dir, "", flat=(0.13, 0.12, 0.11)),
        make_material("floor", mat_dir, opt.get("floor", "dungeon_floor")),
        make_material("wood", mat_dir, opt.get("wood", "dungeon_wood"))]
M_STONE, M_MORTAR, M_FLOOR, M_WOOD = range(4)


# ---------------------------------------------------------------- mesh builder
class Piece:
    def __init__(self, name, seed):
        self.name = name
        self.bm = bmesh.new()
        self.uv = self.bm.loops.layers.uv.new("UVMap")
        self.rng = random.Random(seed)
        self.boxes = []          # collision boxes (min xyz, max xyz) in Blender axes

    def _add(self, tmp, mat, uv_mode, off):
        bm = self.bm
        vm = {v: bm.verts.new(v.co) for v in tmp.verts}
        new = []
        for f in tmp.faces:
            try:
                nf = bm.faces.new([vm[v] for v in f.verts])
            except ValueError:
                continue
            nf.material_index = mat
            new.append(nf)
        bm.normal_update()
        for nf in new:
            n = nf.normal
            ax = max(range(3), key=lambda i: abs(n[i]))
            for lp in nf.loops:
                c = lp.vert.co
                u, v = [(c.y, c.z), (c.x, c.z), (c.x, c.y)][ax]
                if uv_mode == "block":              # texture follows the face, random shift per block
                    lp[self.uv].uv = (u / TILE + off[0], v / TILE + off[1])
                else:                               # world aligned (floor tiles join across cells)
                    lp[self.uv].uv = (u / TILE, v / TILE)

    def box(self, x0, x1, y0, y1, z0, z1, mat=M_STONE, bevel=0.035, rough=0.012, relief=0.025, uv="block"):
        """one chiselled block: bevelled, with a slightly uneven front and back and a little vertex noise"""
        r = self.rng
        tmp = bmesh.new()
        bmesh.ops.create_cube(tmp, size=1.0)
        for v in tmp.verts:
            v.co = Vector(((x0, x1)[v.co.x > 0], (y0, y1)[v.co.y > 0], (z0, z1)[v.co.z > 0]))
        if bevel > 0:
            bmesh.ops.bevel(tmp, geom=list(tmp.edges), offset=min(bevel, min(x1 - x0, y1 - y0, z1 - z0) * 0.3),
                            segments=2, affect="EDGES")
        ry0, ry1 = r.uniform(-relief, relief), r.uniform(-relief, relief)
        ym = (y0 + y1) / 2
        for v in tmp.verts:
            if rough:
                v.co += Vector((r.uniform(-rough, rough), r.uniform(-rough, rough), r.uniform(-rough, rough)))
            if relief:
                v.co.y += ry1 if v.co.y > ym else ry0
        self._add(tmp, mat, uv, (r.random(), r.random()))
        tmp.free()

    def cyl(self, cx, cy, z0, z1, r0, sides=8, mat=M_STONE, rot=0.0, rough=0.01):
        tmp = bmesh.new()
        bmesh.ops.create_cone(tmp, cap_ends=True, segments=sides, radius1=r0, radius2=r0, depth=z1 - z0)
        for v in tmp.verts:
            x, y = v.co.x, v.co.y
            v.co = Vector((cx + x * math.cos(rot) - y * math.sin(rot) + self.rng.uniform(-rough, rough),
                           cy + x * math.sin(rot) + y * math.cos(rot) + self.rng.uniform(-rough, rough),
                           v.co.z + (z0 + z1) / 2))
        self._add(tmp, mat, "block", (self.rng.random(), self.rng.random()))
        tmp.free()

    def wedge(self, cx, cz, r0, r1, a0, a1, y0, y1, mat=M_STONE):
        """one arch stone between two radii and two angles (angle 0 = +x, in the x-z plane)"""
        tmp = bmesh.new()
        for rr, aa in ((r0, a0), (r0, a1), (r1, a1), (r1, a0)):
            for yy in (y0, y1):
                tmp.verts.new((cx + rr * math.cos(aa), yy, cz + rr * math.sin(aa)))
        bmesh.ops.convex_hull(tmp, input=list(tmp.verts))
        c = sum((v.co for v in tmp.verts), Vector()) / len(tmp.verts)
        for v in tmp.verts:                 # inset so the mortar shows between neighbours
            v.co = c + (v.co - c) * 0.985
        self._add(tmp, mat, "block", (self.rng.random(), self.rng.random()))
        tmp.free()

    def finish(self):
        me = bpy.data.meshes.new(self.name)
        self.bm.normal_update()
        self.bm.to_mesh(me)
        self.bm.free()
        for m in MATS:
            me.materials.append(m)
        ob = bpy.data.objects.new(self.name, me)
        bpy.context.scene.collection.objects.link(ob)
        return ob


def segments(x0, x1, r, lo=0.45, hi=1.0):
    """random cut points for blocks between x0 and x1 (each block lo..hi long)"""
    out, x = [], x0
    while x1 - x > hi + lo:
        step = r.uniform(lo, hi)
        out.append((x, x + step))
        x += step
    last = x1 - x
    if last > hi:
        out.append((x, x + last / 2))
        out.append((x + last / 2, x1))
    else:
        out.append((x, x1))
    return out


def cut(spans, hole):
    """remove the x range of `hole` from spans [(a, b)]"""
    hx0, hx1 = hole
    out = []
    for a, b in spans:
        if hx1 <= a or hx0 >= b:
            out.append((a, b))
            continue
        if hx0 - a > 0.05:
            out.append((a, hx0))
        if b - hx1 > 0.05:
            out.append((hx1, b))
    return out


def wall_courses(p, x0, x1, y0, y1, holes=(), spans_fn=None):
    """courses of blocks between x0..x1; holes = [(hx0, hx1, hz0, hz1)] stay open (hz aligned to courses)"""
    for i in range(NC):
        za, zb = i * CH, (i + 1) * CH
        spans = [(x0, x1)]
        if spans_fn:
            spans = spans_fn(za, zb)
        for hx0, hx1, hz0, hz1 in holes:
            if zb > hz0 + 1e-6 and za < hz1 - 1e-6:
                spans = cut(spans, (hx0, hx1))
        for a, b in spans:
            if b - a < 0.2:
                continue
            for s0, s1 in segments(a, b, p.rng):
                p.box(s0 + GAP / 2, s1 - GAP / 2, y0, y1, za + GAP / 2, zb - GAP / 2)


def wall_core(p, x0, x1, y0, y1, holes=()):
    """dark mortar core a bit thinner than the blocks, with the same openings"""
    cuts = [(x0, x1, 0.0, H)]
    for hx0, hx1, hz0, hz1 in holes:
        nc = []
        for a, b, c, d in cuts:
            if hx1 <= a or hx0 >= b or hz1 <= c or hz0 >= d:
                nc.append((a, b, c, d))
                continue
            if hx0 > a:
                nc.append((a, hx0, c, d))
            if hx1 < b:
                nc.append((hx1, b, c, d))
            if hz1 < d:
                nc.append((max(a, hx0), min(b, hx1), hz1, d))
            if hz0 > c:
                nc.append((max(a, hx0), min(b, hx1), c, hz0))
        cuts = nc
    for a, b, c, d in cuts:
        if b - a > 0.02 and d - c > 0.02:
            p.box(a, b, y0 + 0.07, y1 - 0.07, c, d, mat=M_MORTAR, bevel=0, rough=0, relief=0)


pieces = {}
W0, W1 = -C / 2, C / 2
Y1 = C / 2
Y0 = Y1 - T


def new(name):
    p = Piece(name, SEED * 1000 + len(pieces) * 17)
    pieces[name] = p
    return p


# ---- floor and ceiling
p = new("floor")
p.box(W0, W1, -C / 2, C / 2, -FLOOR_T, 0, mat=M_FLOOR, bevel=0, rough=0, relief=0, uv="world")
p.boxes = [(W0, -C / 2, -FLOOR_T, W1, C / 2, 0)]
p = new("ceiling")
p.box(W0, W1, -C / 2, C / 2, H - 0.25, H, mat=M_FLOOR, bevel=0, rough=0, relief=0, uv="world")
for bx in (-C / 4, C / 4):                       # two cross beams
    p.box(-C / 2, C / 2, bx - 0.15, bx + 0.15, H - 0.5, H - 0.25, mat=M_WOOD, bevel=0.02, rough=0.005, relief=0)
p.boxes = [(W0, -C / 2, H - 0.25, W1, C / 2, H)]


# ---- plain walls (two block layouts)
def plain_wall(name, holes=()):
    p = new(name)
    wall_core(p, W0, W1, Y0, Y1, holes)
    wall_courses(p, W0, W1, Y0, Y1, holes)
    return p


p = plain_wall("wall")
p.boxes = [(W0, Y0, 0, W1, Y1, H)]
p = plain_wall("wall_b")
p.boxes = [(W0, Y0, 0, W1, Y1, H)]

# ---- door opening: coursed jambs and one heavy lintel stone
DW = 1.7
DH = 6 * CH if NC >= 7 else 2.2        # opening height = whole courses
dx0, dx1 = -DW / 2, DW / 2
lint = (dx0 - 0.15, dx1 + 0.15)
p = plain_wall("wall_door", holes=[(lint[0], lint[1], 0, DH + CH)])
p.box(lint[0], lint[1], Y0 - 0.03, Y1 + 0.03, DH, DH + CH - GAP / 2, bevel=0.04, relief=0.02)
p.boxes = [(W0, Y0, 0, lint[0], Y1, H), (lint[1], Y0, 0, W1, Y1, H), (lint[0], Y0, DH, lint[1], Y1, H)]

# ---- window: sill and lintel around a rectangular opening aligned to the courses
WX0, WX1 = -0.6, 0.6
WZ0, WZ1 = 3 * CH, 6 * CH
p = plain_wall("wall_window", holes=[(WX0, WX1, WZ0, WZ1)])
p.box(WX0 - 0.1, WX1 + 0.1, Y0 - 0.05, Y1 + 0.05, WZ0 - 0.02, WZ0 + 0.12, bevel=0.03)        # sill
p.box(WX0 - 0.1, WX1 + 0.1, Y0 - 0.02, Y1 + 0.02, WZ1 - 0.15, WZ1 - GAP / 2, bevel=0.03)     # lintel
for bx in (-0.3, 0.0, 0.3):                                                                    # bars
    p.box(bx - 0.02, bx + 0.02, (Y0 + Y1) / 2 - 0.02, (Y0 + Y1) / 2 + 0.02, WZ0, WZ1 - 0.15, mat=M_MORTAR,
          bevel=0, rough=0, relief=0)
p.boxes = [(W0, Y0, 0, W1, Y1, WZ0), (W0, Y0, WZ1, W1, Y1, H), (W0, Y0, WZ0, WX0, Y1, WZ1),
           (WX1, Y0, WZ0, W1, Y1, WZ1)]

# ---- arch: coursed jambs + a ring of wedge-shaped stones
AR = 0.95                  # inner radius
RING = 0.42                # ring thickness
ASP = 1.3                  # springline height
OUT = AR + RING
p = new("wall_arch")
wall_core(p, W0, W1, Y0, Y1, [(-AR, AR, 0, ASP + AR)])


def arch_spans(za, zb):
    if za < ASP:
        hx = AR if zb <= ASP + 0.01 else OUT
    else:
        d = (za + zb) / 2 - ASP
        hx = math.sqrt(OUT * OUT - d * d) if d < OUT else 0.0
    return [(W0, -hx), (hx, W1)] if hx > 0 else [(W0, W1)]


wall_courses(p, W0, W1, Y0, Y1, spans_fn=arch_spans)
NV = 9
for k in range(NV):
    p.wedge(0, ASP, AR, OUT, math.pi * k / NV, math.pi * (k + 1) / NV, Y0 - 0.03, Y1 + 0.03)
p.boxes = [(W0, Y0, 0, -AR, Y1, H), (AR, Y0, 0, W1, Y1, H), (-AR, Y0, ASP + AR, AR, Y1, H)]

# ---- corner: the +Y wall plus the +X wall; and a square post for reflex corners
p = new("corner")
wall_core(p, W0, W1, Y0, Y1)
p.box(Y0 + 0.07, Y1 - 0.07, -C / 2, Y0, 0, H, mat=M_MORTAR, bevel=0, rough=0, relief=0)
wall_courses(p, W0, W1, Y0, Y1)
for i in range(NC):
    za, zb = i * CH, (i + 1) * CH
    for s0, s1 in segments(-C / 2, Y0, p.rng):
        p.box(Y0, Y1, s0 + GAP / 2, s1 - GAP / 2, za + GAP / 2, zb - GAP / 2)
p.boxes = [(W0, Y0, 0, W1, Y1, H), (Y0, -C / 2, 0, Y1, Y0, H)]

p = new("corner_inner")
for i in range(NC):
    p.box(Y0, Y1, Y0, Y1, i * CH + GAP / 2, (i + 1) * CH - GAP / 2, bevel=0.04, relief=0.0)
p.boxes = [(Y0, Y0, 0, Y1, Y1, H)]

# ---- pillar
p = new("pillar")
p.box(-0.5, 0.5, -0.5, 0.5, 0, 0.3, bevel=0.05)
n = 5
for i in range(n):
    za = 0.3 + (H - 0.6) * i / n
    zb = 0.3 + (H - 0.6) * (i + 1) / n
    p.cyl(0, 0, za + 0.01, zb - 0.01, 0.34, sides=8, rot=p.rng.uniform(0, 0.8))
p.box(-0.55, 0.55, -0.55, 0.55, H - 0.3, H, bevel=0.05)
p.boxes = [(-0.45, -0.45, 0, 0.45, 0.45, H)]

# ---- stairs rising along +Y from z=0 (at y=-C/2) to z=H (at y=+C/2)
p = new("stairs")
ns = 12
rise = H / ns
run = C / ns
for i in range(ns):
    ya, yb = -C / 2 + i * run, -C / 2 + (i + 1) * run
    p.box(W0, W1, ya, yb + 0.002, -FLOOR_T, rise * (i + 1), mat=M_FLOOR, bevel=0.02, rough=0.004, relief=0,
          uv="world")
p.boxes = []        # the walkable ramp is added in the Godot builder

# ---- door leaf: the pivot is the hinge axis, so the door swings when rotated about Y
p = new("door")
dw = DW - 0.08
nb = 6
bw = dw / nb
for i in range(nb):
    p.box(i * bw + 0.004, (i + 1) * bw - 0.004, -0.05, 0.05, 0.02, DH - 0.03, mat=M_WOOD, bevel=0.012,
          rough=0.004, relief=0.01)
for zz in (0.35, DH - 0.55):
    p.box(0.0, dw, 0.05, 0.085, zz, zz + 0.12, mat=M_MORTAR, bevel=0.01, rough=0, relief=0)
p.boxes = [(0, -0.06, 0, dw, 0.06, DH)]
door_offset = [dx0 + 0.04, (Y0 + Y1) / 2]       # where the hinge sits in the doorway (x, y of the cell)

# ---------------------------------------------------------------- objects, preview layout, export
objs = {k: v.finish() for k, v in pieces.items()}


def to_godot(b):
    x0, y0, z0, x1, y1, z1 = b
    return [(x0 + x1) / 2, (z0 + z1) / 2, -(y0 + y1) / 2, x1 - x0, z1 - z0, y1 - y0]


info = dict(cell=C, height=H, thick=T, floor_thick=FLOOR_T, door=dict(width=DW, height=DH, hinge_x=door_offset[0],
                                                                         hinge_z=-door_offset[1]),
            pieces={k: dict(boxes=[to_godot(b) for b in v.boxes], faces=len(objs[k].data.polygons))
                    for k, v in pieces.items()})
(out_dir / "kit.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
for k, v in info["pieces"].items():
    print("KIT_PIECE", k, v["faces"], "faces", len(v["boxes"]), "collision boxes")

bpy.ops.object.select_all(action="DESELECT")
for ob in objs.values():
    ob.select_set(True)
bpy.context.view_layer.objects.active = next(iter(objs.values()))
bpy.ops.export_scene.gltf(filepath=str(out_dir / "kit.glb"), export_format="GLB", use_selection=True,
                          export_yup=True, export_apply=True)
print("KIT_GLB", out_dir / "kit.glb")

pv = opt.get("preview")
if pv:
    names = list(objs)
    cols = 4
    step = C + 1.5
    for i, k in enumerate(names):
        objs[k].location = ((i % cols) * step, -(i // cols) * step, 0)
    sc = bpy.context.scene
    cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    rows = (len(names) + cols - 1) // cols
    cx, cy = (cols - 1) * step / 2, -(rows - 1) * step / 2
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = max(cols, rows) * step * 1.15
    cam.location = (cx + 14, cy - 14, 14)
    d = Vector((cx, cy, 1.0)) - cam.location
    cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
    sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
    sun.data.energy = 3.5
    sun.rotation_euler = (math.radians(50), 0, math.radians(30))
    sc.collection.objects.link(sun)
    sc.world = bpy.data.worlds.new("w")
    sc.world.use_nodes = True
    next(n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND").inputs["Strength"].default_value = 0.9
    try:
        sc.render.engine = "BLENDER_EEVEE"
    except TypeError:
        sc.render.engine = "BLENDER_EEVEE_NEXT"
    sc.render.resolution_x, sc.render.resolution_y = 1500, 1100
    sc.render.filepath = pv
    bpy.ops.render.render(write_still=True)
    print("KIT_PREVIEW", pv)

close = opt.get("closeup")
if close:
    sc = bpy.context.scene
    for k, ob in objs.items():
        ob.location = (0, 0, 0)
    cam = bpy.data.objects.new("cam2", bpy.data.cameras.new("cam2"))
    sc.collection.objects.link(cam)
    sc.camera = cam
    if not pv:
        sun = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN"))
        sun.data.energy = 3.5
        sun.rotation_euler = (math.radians(60), 0, math.radians(20))
        sc.collection.objects.link(sun)
        sc.world = bpy.data.worlds.new("w")
        sc.world.use_nodes = True
        next(n for n in sc.world.node_tree.nodes if n.type == "BACKGROUND").inputs["Strength"].default_value = 0.9
        try:
            sc.render.engine = "BLENDER_EEVEE"
        except TypeError:
            sc.render.engine = "BLENDER_EEVEE_NEXT"
    sc.render.resolution_x, sc.render.resolution_y = 900, 700
    cam.data.type = "ORTHO"
    cam.data.ortho_scale = C * 1.15
    for name in close.split(","):
        for k, ob in objs.items():
            ob.hide_render = k != name
        cam.location = (-5.5, -8.0, 4.0)
        d = Vector((0, 0.8, H / 2)) - cam.location
        cam.rotation_euler = d.to_track_quat("-Z", "Y").to_euler()
        sc.render.filepath = str(Path(out_dir).parent.parent.parent / "work" / f"modkit_close_{name}.png")
        bpy.ops.render.render(write_still=True)
        print("KIT_CLOSE", sc.render.filepath)
