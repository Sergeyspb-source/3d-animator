"""Runs INSIDE Blender (from blender_helmet_gen.py): five more helmets in the frame and with the materials of the
vendored HelmetVariants generator (metres, the front -Y, the eye slits at about z .041, the brow at brow_z, the shell
ending at neck_z), so blender_helmet_gen fits them to the head as it does those:

    nasal_helm   a Norman helm: a conical skull a little forward, a brow band and a nasal down over the nose
    spangenhelm  a framed helm: a rounded cone of four plates under four bands from the apex, a brow band, a nasal and
                 cheek plates on the sides
    great_helm   a great helm (a «pot»): flat-topped, round down to the neck, two eye slits over a cross of bands
                 and breaths on the right
    morion       a morion: a dome under a high comb from front to back, its brim swept up before and behind
    close_helm   a close helmet: the armet's skull, cheeks and visor under a comb

Each is made of shells of rows (ring by ring from the apex down), openings cut as the generator's are (cells left out),
solidified with a rolled border (helmet_geometry.surface). Our own constructions, on the generator's shared pieces.
"""
import math

import bpy
from mathutils import Vector

from helmet_geometry import surface, sector, skull
from helmet_fittings import rivet, lining_rivets, chinstrap
from kettle_hat_details import make_materials, tube
from generate_kettle_hat import prepare_meshes

STYLES = {
    "nasal_helm": {"height": 0.150, "peak_sweep": 0.022, "neck_z": 0.050, "crest": 0.0},   # (ending over the eyes)
    "spangenhelm": {"height": 0.135, "peak_sweep": 0.010, "neck_z": 0.050, "crest": 0.0},
    "great_helm": {"height": 0.090, "peak_sweep": 0.0, "neck_z": -0.115, "crest": 0.0},
    "morion": {"height": 0.110, "peak_sweep": 0.0, "neck_z": 0.030, "crest": 0.0},
    "close_helm": {"height": 0.109, "peak_sweep": 0.002, "neck_z": -0.075, "visor_projection": 0.039, "crest": 0.002},
}


def shell(p, name, mat, coll, rows, exclude=lambda a, z: False, extra=None, thickness=None, trim=.0008):
    """A shell from its apex down: rows [(k, z)] - k the ring's size against the head's ellipse (rx, ry), z its height;
    extra(a, z) -> (dx, dy) moves a ring's point (a peak forward, a brim swept); the cells exclude(a, z) left open."""
    n = p["segments"]
    top = rows[0]
    verts = [(0, p["peak_sweep"], top[1])]
    for k, z in rows[1:]:
        for j in range(n):
            a = math.tau * j / n
            x, y = p["rx"] * k * math.sin(a), -p["ry"] * k * math.cos(a)
            if extra:
                dx, dy = extra(a, z)
                x, y = x + dx, y + dy
            verts.append((x, y, z))
    faces = [(0, 1 + j, 1 + (j + 1) % n) for j in range(n)] if not exclude(0, top[1]) else []
    for r in range(len(rows) - 2):
        a0, b0 = 1 + r * n, 1 + (r + 1) * n
        for j in range(n):
            ids = (a0 + j, b0 + j, b0 + (j + 1) % n, a0 + (j + 1) % n)
            z = sum(verts[i][2] for i in ids) / 4
            if not exclude(math.tau * (j + .5) / n, z):
                faces.append(ids)
    return surface(name, verts, faces, mat, coll, thickness or p["thickness"], trim)


def band(p, name, mat, coll, a0, a1, z0, z1, out=1.02, thickness=.0025):
    """A strip round the shell between the angles a0..a1 (from the front), the heights z0 (top) .. z1."""
    return sector(name, p, a0, a1, z0, z1, mat, coll, radius_scale=out, thickness=thickness, flare=0)


def rivets_round(p, mats, coll, z, n, out=1.03, skip=None):
    for i in range(n):
        a = math.tau * (i + .5) / n
        if skip and skip(a):
            continue
        nrm = Vector((math.sin(a), -math.cos(a), 0)).normalized()
        rivet(f"Band_Rivet_{i:02}", Vector((p["rx"] * out * math.sin(a), -p["ry"] * out * math.cos(a), z)), nrm, .0022, mats["steel"], coll)


def cone_rows(p, z_bot, sharp=1.0, steps=26):
    """A cone's rows from its apex (brow_z + height) down to z_bot: straight sides (sharp 1) to a dome (sharp 0)."""
    zt, zb = p["brow_z"] + p["height"], p["brow_z"]
    rows = []
    for i in range(steps + 1):
        v = i / steps   # 0 the apex .. 1 the brow: a cone's straight line, a dome's quarter circle
        k = v * sharp + math.sin(v * math.pi / 2) * (1 - sharp)
        z = zb + (zt - zb) * ((1 - v) * sharp + math.cos(v * math.pi / 2) * (1 - sharp))
        rows.append((max(k, 1e-4) if i else 0, z))
    for z in (p["brow_z"] - .012, p["brow_z"] - .025, 0.045, 0.035, 0.028, 0.022, 0.012, 0.0, -0.02, -0.04, -0.06, -0.08, -0.1, -0.115):
        if z < rows[-1][1] - 1e-6 and z >= z_bot - 1e-6:
            rows.append((1.0, z))
    return rows


def peak_forward(p):
    return lambda a, z: (0, p["peak_sweep"] * max(0, (z - p["brow_z"]) / max(p["height"], 1e-6)) ** 2)


def nasal(p, mats, coll, top, bottom, width=.010):
    pts = []
    for i in range(9):
        t = i / 8
        z = top + (bottom - top) * t
        pts.append((z, -p["ry"] * 1.03 - .004 * t))
    verts = []
    for z, y in pts:
        w = width * (1 - .25 * (z < 0.03))
        verts += [(-w, y, z), (w, y, z)]
    faces = [(2 * i, 2 * i + 1, 2 * i + 3, 2 * i + 2) for i in range(len(pts) - 1)]
    return surface("Nasal", verts, faces, mats["steel"], coll, .003, .0008)


# ---------------------------------------------------------------- the constructions
def nasal_helm(p, mats, coll):
    rows = cone_rows(p, p["neck_z"], sharp=.75)
    shell(p, "Nasal_Helm_Shell", mats["steel"], coll, rows, extra=peak_forward(p))
    shell(p, "Suspended_Liner", mats["liner"], coll, [(k * .95, z - .004) for k, z in rows], extra=peak_forward(p), thickness=.001, trim=0)
    band(p, "Brow_Band", mats["steel"], coll, -math.pi, math.pi, p["neck_z"] + .016, p["neck_z"], out=1.025)
    rivets_round(p, mats, coll, p["neck_z"] + .008, 16, out=1.05)
    nasal(p, mats, coll, p["neck_z"] + .016, -0.012)
    chinstrap(p, mats, coll, rise=0.04)


def spangenhelm(p, mats, coll):
    rows = cone_rows(p, p["neck_z"], sharp=.45)
    shell(p, "Spangen_Shell", mats["steel"], coll, rows, extra=peak_forward(p))
    shell(p, "Suspended_Liner", mats["liner"], coll, [(k * .95, z - .004) for k, z in rows], extra=peak_forward(p), thickness=.001, trim=0)
    zt = p["brow_z"] + p["height"]
    for i, a in enumerate((math.pi / 4, 3 * math.pi / 4, -3 * math.pi / 4, -math.pi / 4)):   # the frame's bands from the apex
        pts = []
        for r, (k, z) in enumerate(rows):
            if z < p["neck_z"] + .012:
                break
            pts.append(Vector((p["rx"] * k * 1.03 * math.sin(a), -p["ry"] * k * 1.03 * math.cos(a) + p["peak_sweep"] * max(0, (z - p["brow_z"]) / p["height"]) ** 2, z + .001)))
        tube(f"Spangen_Band_{i}", pts, .004, mats["steel"], coll, False)
        for q in pts[3::4]:
            rivet(f"Spangen_Rivet_{i}_{len(pts)}_{q.z:.3f}", q, Vector((math.sin(a), -math.cos(a), .4)), .0024, mats["steel"], coll)
    rivet("Apex_Boss", Vector((0, p["peak_sweep"], zt + .002)), Vector((0, 0, 1)), .009, mats["steel"], coll, .004)
    band(p, "Brow_Band", mats["steel"], coll, -math.pi, math.pi, p["neck_z"] + .018, p["neck_z"], out=1.03)
    rivets_round(p, mats, coll, p["neck_z"] + .009, 20, out=1.055)
    nasal(p, mats, coll, p["neck_z"] + .016, -0.008, width=.008)
    for side in (-1, 1):   # cheek plates, hung at the band
        a0, a1 = (0.75, 1.95) if side == 1 else (-1.95, -0.75)
        sector(f"Cheek_Plate_{side}", p, a0, a1, p["neck_z"] + .004, -0.07, mats["steel"], coll, radius_scale=1.0, thickness=.002, flare=-0.12)
    chinstrap(p, mats, coll, rise=0.03)


def great_helm(p, mats, coll):
    zt = p["brow_z"] + p["height"]
    # a low dome on top, the sides a little in towards it (a «sugarloaf»'s start), round and straight down to the neck
    rows = [(0, zt + .012)] + [(.9 * k, zt + .012 * (1 - k * k)) for k in (.2, .4, .6, .8, .92, .98)] + [(.91, zt - .006)]
    zs = [zt - .02] + [z for z in (0.12, 0.10, 0.085, 0.07, 0.060, 0.052, 0.046, 0.040, 0.034, 0.025, 0.012, 0.0, -0.02, -0.04, -0.06, -0.08, -0.1) if z < zt - .02] + [p["neck_z"]]
    taper = lambda z: .92 + .08 * max(0, min(1, (zt - z) / max(zt - p["brow_z"], 1e-6)))
    rows += [(taper(z) + .04 * max(0, (0.0 - z) / .1), z) for z in zs]   # (and a little wider going down)
    def opening(a, z):   # two eye slits either side of the front bar, breaths on the right below
        x = p["rx"] * math.sin(a)
        if math.cos(a) > .45 and 0.034 < z < 0.046 and .008 < abs(x) < .072:
            return True
        return math.cos(a) > .2 and x > .012 and -0.04 < z < 0.0 and (int((z + 0.04) / 0.01) % 2 == 0) and (int(x / 0.01) % 2 == 0)
    shell(p, "Great_Helm_Shell", mats["steel"], coll, rows, opening)
    shell(p, "Suspended_Liner", mats["liner"], coll, [(k * .95, z - .004) for k, z in rows], opening, thickness=.001, trim=0)
    # the cross: a band over the front from the top down past the mouth, one across under the slits
    band(p, "Cross_Upright", mats["steel"], coll, -.09, .09, zt - .01, -0.06, out=1.03, thickness=.003)
    band(p, "Cross_Bar", mats["steel"], coll, -1.1, 1.1, 0.034, 0.024, out=1.035, thickness=.003)
    band(p, "Brow_Band", mats["steel"], coll, -math.pi, math.pi, 0.058, 0.048, out=1.02, thickness=.002)
    rivets_round(p, mats, coll, 0.053, 22, out=1.04, skip=lambda a: math.cos(a) > .5)


def morion(p, mats, coll):
    rows = cone_rows(p, p["brow_z"] - .008, sharp=.0)
    shell(p, "Morion_Skull", mats["steel"], coll, rows)
    shell(p, "Suspended_Liner", mats["liner"], coll, [(k * .95, z - .004) for k, z in rows], thickness=.001, trim=0)
    zb = p["brow_z"] - .008
    brim = []   # its brim: out and swept up before and behind (a boat)
    for i in range(7):
        t = i / 6
        brim.append((1.0 + .45 * t, zb - .006 * t))
    n = p["segments"]
    verts, faces = [], []
    for r, (k, _) in enumerate(brim):
        t = r / (len(brim) - 1)
        for j in range(n):
            a = math.tau * j / n
            up = .055 * t ** 1.5 * abs(math.cos(a)) ** 3   # up before and behind
            verts.append((p["rx"] * k * math.sin(a), -p["ry"] * (k + .25 * t * abs(math.cos(a)) ** 2) * math.cos(a), zb - .006 * t + up))
    for r in range(len(brim) - 1):
        for j in range(n):
            faces.append((r * n + j, r * n + (j + 1) % n, (r + 1) * n + (j + 1) % n, (r + 1) * n + j))
    surface("Morion_Brim", verts, faces, mats["steel"], coll, p["thickness"], .0012)
    # the comb: a thin plate along the middle from the front to the back over the skull
    zt = p["brow_z"] + p["height"]
    cv, cf = [], []
    m = 24
    for i in range(m + 1):
        t = i / m
        y = -p["ry"] * .98 * math.cos(math.pi * t)
        k = math.sqrt(max(0.0, 1 - (y / p["ry"]) ** 2))
        z0 = p["brow_z"] + (zt - p["brow_z"]) * k   # (on the dome's line along the middle)
        cv += [(0, y, z0 - .004), (0, y, z0 + .055 * math.sin(math.pi * t) ** .8)]
    for i in range(m):
        cf.append((2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1))
    surface("Morion_Comb", cv, cf, mats["steel"], coll, .003, .001)
    rivets_round(p, mats, coll, zb + .008, 14, out=1.02)
    chinstrap(p, mats, coll, rise=0.05)


def close_helm(p, mats, coll):
    import armet
    armet.build(p, mats, coll)
    # a comb over the skull from the brow to the nape
    zt = p["brow_z"] + p["height"]
    cv, cf, m = [], [], 24
    for i in range(m + 1):
        t = i / m
        y = -p["ry"] * .95 * math.cos(math.pi * t)
        k = math.sqrt(max(0.0, 1 - (y / p["ry"]) ** 2))
        z0 = p["brow_z"] + (zt - p["brow_z"]) * k   # (the skull's dome along its middle)
        cv += [(0, y, z0 - .004), (0, y, z0 + .022 * math.sin(math.pi * t) ** .7)]
    for i in range(m):
        cf.append((2 * i, 2 * i + 2, 2 * i + 3, 2 * i + 1))
    surface("Close_Comb", cv, cf, mats["steel"], coll, .003, .001)


BUILDERS = {"nasal_helm": nasal_helm, "spangenhelm": spangenhelm, "great_helm": great_helm, "morion": morion, "close_helm": close_helm}


def build(kind, p, texture_dir):
    """As generate_helmet.build: (root, its meshes)."""
    coll = bpy.data.collections.new(f"{kind}_Model")
    bpy.context.scene.collection.children.link(coll)
    root = bpy.data.objects.new(kind, None)
    coll.objects.link(root)
    mats = make_materials(texture_dir)
    BUILDERS[kind](p, mats, coll)
    geometry = [o for o in coll.objects if o.type in {"MESH", "CURVE"}]
    prepare_meshes([o for o in geometry if o.name != "Aventail_Rings"])
    for obj in coll.objects:
        if obj != root and obj.parent is None:
            obj.parent = root
    bpy.context.view_layer.update()
    return root, [o for o in coll.objects if o.type == "MESH"]
