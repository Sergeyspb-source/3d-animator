"""Runs INSIDE Blender (background): procedural eyes, teeth and tongue, the shared base for every character.

    blender -b -P blender_face_parts.py -- job.json

job.json (all optional except out_dir):
  out_dir, seed
  eye:    iris [r,g,b], iris_dark [r,g,b], pupil (0.25..0.7 of the iris), slit (bool, cat/creature pupil),
          sclera [r,g,b], veins (0..1), radius (m, default 0.012)
  teeth:  per_side (4..8 per half arch, default 7), missing ("2,5" indices from the middle, upper U / lower L prefix
          allowed: "U1,L3"), missing_random (0..1), yellow (0..1), crooked (0..1), fangs (0..1 extra canine length),
          arch_width (m, default 0.05), gum [r,g,b]
  tongue: colour [r,g,b], length (m, default 0.055)

Real-world sizes in metres; the fitting step scales them into the skull. Writes eyes.glb (Eye_L, Eye_R with the iris
along -Y, Blender forward), teeth.glb (Teeth_Upper, Teeth_Lower, Gum_Upper, Gum_Lower), tongue.glb, preview.png and
parts.json. Textures are generated here (numpy), so Godot shows them without any shader work.
"""
import json
import math
import random
import sys
from pathlib import Path

import bmesh
import bpy
import numpy as np
from mathutils import Matrix, Vector

job = json.loads(Path(sys.argv[sys.argv.index("--") + 1]).read_text(encoding="utf-8"))
OUT = Path(job["out_dir"]); OUT.mkdir(parents=True, exist_ok=True)
rng = random.Random(job.get("seed", 1))
E, T, G = job.get("eye", {}), job.get("teeth", {}), job.get("tongue", {})

bpy.ops.wm.read_factory_settings(use_empty=True)
scene = bpy.context.scene


def image(name, arr):
    """numpy HxWx3 (0..1, row 0 = top) -> packed Blender image."""
    h, w, _ = arr.shape
    img = bpy.data.images.new(name, w, h, alpha=False)
    rgba = np.concatenate([arr[::-1], np.ones((h, w, 1))], axis=2).astype(np.float32)
    img.pixels.foreach_set(rgba.ravel())
    img.pack()
    return img


def material(name, img=None, color=(1, 1, 1), rough=0.5, spec=0.5, sss=0.0):
    m = bpy.data.materials.new(name)
    m.use_nodes = True
    b = next(n for n in m.node_tree.nodes if n.type == "BSDF_PRINCIPLED")
    if img is not None:
        t = m.node_tree.nodes.new("ShaderNodeTexImage"); t.image = img
        m.node_tree.links.new(t.outputs["Color"], b.inputs["Base Color"])
    else:
        b.inputs["Base Color"].default_value = (*color, 1)
    b.inputs["Roughness"].default_value = rough
    for k in ("Specular IOR Level", "Specular"):
        if k in b.inputs:
            b.inputs[k].default_value = spec
            break
    return m


# ================================================================== eye
def eye_texture(w=1024, h=512):
    """Equirect map of a sphere whose pole faces forward: row = angle from the gaze axis, column = azimuth."""
    iris = np.array(E.get("iris", [0.32, 0.45, 0.22])); dark = np.array(E.get("iris_dark", (iris * 0.35).tolist()))
    sclera = np.array(E.get("sclera", [0.93, 0.91, 0.87])); veins = float(E.get("veins", 0.35))
    pupil = float(E.get("pupil", 0.42)); slit = bool(E.get("slit", False))
    theta = (np.arange(h)[:, None] + 0.5) / h * math.pi          # 0 = front pole
    phi = (np.arange(w)[None, :] + 0.5) / w * 2 * math.pi
    TH, PH = np.broadcast_arrays(theta, phi)
    iris_r = math.radians(32)                                     # iris disc seen from the centre
    r = TH / iris_r                                               # 0 centre .. 1 limbus
    out = np.empty((h, w, 3))
    # sclera: slightly pinker toward the back, thin red veins growing from the back
    back = np.clip((TH - iris_r) / (math.pi - iris_r), 0, 1)
    out[:] = sclera[None, None] * (1 - 0.18 * back[..., None]) + np.array([0.12, 0.0, 0.0]) * back[..., None] * 0.5
    vr = np.random.default_rng(job.get("seed", 1))
    for _ in range(int(24 * veins)):
        ph0, amp, freq = vr.uniform(0, 2 * math.pi), vr.uniform(0.02, 0.08), vr.uniform(3, 9)
        path = ph0 + amp * np.sin(TH * freq + vr.uniform(0, 6))
        d = np.abs(((PH - path + math.pi) % (2 * math.pi)) - math.pi) * np.sin(TH)
        m = np.exp(-(d / 0.004) ** 2) * np.clip((TH - iris_r * 1.3) / 0.6, 0, 1) * vr.uniform(0.3, 0.8)
        out = out * (1 - m[..., None]) + np.array([0.62, 0.12, 0.12]) * m[..., None]
    # iris: radial fibres, darker rim (limbal ring), lighter collarette around the pupil
    fib = 0.5 + 0.5 * np.sin(PH * 90 + 3 * np.sin(PH * 7)) * np.sin(PH * 41 + r * 6)
    col = dark[None, None] + (iris - dark)[None, None] * (0.55 + 0.45 * fib[..., None]) * (1.1 - 0.5 * r[..., None])
    col = col * np.clip(1.25 - 0.35 * r, 0.6, 1.25)[..., None]
    limbus = np.clip((r - 0.86) / 0.14, 0, 1)
    col = col * (1 - 0.75 * limbus[..., None])
    inside = r < 1.0
    out[inside] = col[inside]
    edge = (r >= 1.0) & (r < 1.08)                                 # soft blend into the sclera
    t = ((r - 1.0) / 0.08)[edge][:, None]
    out[edge] = col[edge] * (1 - t) * 0.3 + out[edge] * (0.7 + 0.3 * t)
    # pupil (round, or a vertical slit for creatures)
    if slit:
        x = np.sin(TH) * np.cos(PH); y = np.sin(TH) * np.sin(PH)
        pup = (np.abs(x) / (math.sin(iris_r) * pupil * 0.35)) ** 2 + (np.abs(y) / (math.sin(iris_r) * 0.95)) ** 2 < 1
    else:
        pup = r < pupil
    out[pup] = np.array([0.015, 0.012, 0.012])
    return np.clip(out, 0, 1)


def make_eye(name, radius, x):
    bpy.ops.mesh.primitive_uv_sphere_add(segments=48, ring_count=24, radius=radius)
    o = bpy.context.active_object; o.name = name
    # pole -> forward (-Y); UVs follow (row = angle from the gaze)
    o.data.transform(Matrix.Rotation(math.radians(90), 4, "X"))
    bm = bmesh.new(); bm.from_mesh(o.data)
    uv = bm.loops.layers.uv.verify()
    for f in bm.faces:
        for l in f.loops:
            v = l.vert.co.normalized()
            th = math.acos(max(-1, min(1, -v.y)))                    # angle from the front pole
            ph = math.atan2(v.z, v.x) % (2 * math.pi)
            l[uv].uv = (ph / (2 * math.pi), 1 - th / math.pi)
        # cornea bulge: the front cap a little forward, like a real eye
    for v in bm.verts:
        th = math.acos(max(-1, min(1, -v.co.normalized().y)))
        if th < math.radians(38):
            v.co += Vector((0, -1, 0)) * radius * 0.08 * math.cos(th / math.radians(38) * math.pi / 2) ** 2
    # fix the seam: faces crossing phi=0 get u+1 on the low side
    for f in bm.faces:
        us = [l[uv].uv.x for l in f.loops]
        if max(us) - min(us) > 0.5:
            for l in f.loops:
                if l[uv].uv.x < 0.5:
                    l[uv].uv.x += 1.0
    bm.to_mesh(o.data); bm.free()
    for p in o.data.polygons:
        p.use_smooth = True
    o.location.x = x
    return o


eye_r = float(E.get("radius", 0.012))
eye_img = image("eye_texture", eye_texture())
eye_mat = material("eye", eye_img, rough=0.12, spec=0.25)
eyes = []
for name, x in (("Eye_L", eye_r * 2.7), ("Eye_R", -eye_r * 2.7)):
    o = make_eye(name, eye_r, x)
    o.data.materials.append(eye_mat)
    eyes.append(o)

# ================================================================== teeth
per = max(4, min(8, int(T.get("per_side", 7))))
KINDS = ["incisor", "incisor", "canine", "premolar", "premolar", "molar", "molar", "molar"][:per]
yellow = float(T.get("yellow", 0.0)); crooked = float(T.get("crooked", 0.0)); fangs = float(T.get("fangs", 0.0))
arch_w = float(T.get("arch_width", 0.05))
missing = set()
for tok in str(T.get("missing", "")).replace(" ", "").split(","):
    if tok:
        jaw = tok[0].upper() if tok[0].upper() in "UL" else "*"
        idx = int(tok[1:] if jaw != "*" else tok)
        missing.add((jaw, idx))
mrand = float(T.get("missing_random", 0.0))


def tooth_color():
    """white -> yellow -> brown with yellow; a slight random tint per tooth."""
    base = np.array([0.94, 0.92, 0.86]); yel = np.array([0.86, 0.74, 0.45]); brown = np.array([0.55, 0.42, 0.25])
    c = base + (yel - base) * min(1, yellow * 1.6) + (brown - yel) * max(0, yellow - 0.6) / 0.4 * (yellow > 0.6)
    return np.clip(c * (1 + rng.uniform(-0.04, 0.04)), 0, 1)


def tooth_mesh(kind, size):
    """crown + short root as a deformed low-poly sphere; +Z is the biting edge direction."""
    bpy.ops.mesh.primitive_uv_sphere_add(segments=12, ring_count=8, radius=1)
    o = bpy.context.active_object
    w, d, h = {"incisor": (0.0046, 0.0020, 0.0058), "canine": (0.0040, 0.0036, 0.0062),
               "premolar": (0.0036, 0.0042, 0.0045), "molar": (0.0050, 0.0052, 0.0040)}[kind]
    if kind == "canine":
        h *= 1 + 1.4 * fangs
    for v in o.data.vertices:
        x, y, z = v.co
        t = (z + 1) / 2                                     # 0 root .. 1 edge
        if kind == "incisor":
            sx, sy = 1.0 - 0.1 * t, 1.0 - 0.55 * t          # flat chisel edge
            x = max(-1.0, min(1.0, x * 1.25))               # squarer outline
        elif kind == "canine":
            sx = sy = 1.0 - 0.75 * t ** 1.5                 # point
        else:
            sx = sy = 1.0 - 0.15 * t
        z2 = z * h
        if kind in ("premolar", "molar") and z > 0.6:       # cusps on the chewing surface
            z2 -= h * 0.15 * (1 - abs(math.sin(x * 2.2) * math.sin(y * 2.2)))
        v.co = Vector((x * w * sx, y * d * sy, z2)) * size
    for p in o.data.polygons:
        p.use_smooth = True
    return o


def arch(upper):
    """teeth and a gum strip along a parabolic arch; upper teeth point down, lower up."""
    jaw = "U" if upper else "L"
    sgn = -1 if upper else 1
    teeth, cols = [], []
    half = arch_w / 2
    depth = arch_w * 0.85
    pos = []
    s = 0.0
    widths = [{"incisor": 0.0046, "canine": 0.0044, "premolar": 0.0040, "molar": 0.0055}[k] for k in KINDS]
    total = sum(widths)
    for i, (k, wdt) in enumerate(zip(KINDS, widths)):
        u = (s + wdt / 2) / total                            # 0 front .. 1 back
        s += wdt
        x = half * math.sin(u * math.pi / 2) ** 0.9
        y = depth * u ** 1.8                                  # back = +Y
        pos.append((i, k, u, x, y))
    for side in (1, -1):
        for i, k, u, x, y in pos:
            idx = i + 1
            if (jaw, idx) in missing or ("*", idx) in missing or rng.random() < mrand:
                continue
            o = tooth_mesh(k, 1.0 if upper else 0.92)
            # width along the arch tangent: front teeth face forward, back teeth turn with the arch
            du = 1e-3
            x1, y1 = half * math.sin(min(1, u + du) * math.pi / 2) ** 0.9, depth * min(1, u + du) ** 1.8
            ang = math.atan2(y1 - y, x1 - x)
            o.rotation_euler = (math.radians(180) if upper else 0, 0, side * ang if not upper else -side * ang)
            o.location = (side * x, y, 0)
            if crooked:
                o.rotation_euler.z += rng.uniform(-0.35, 0.35) * crooked
                o.rotation_euler.x += rng.uniform(-0.2, 0.2) * crooked
                o.location.x += rng.uniform(-0.0008, 0.0008) * crooked
                o.location.y += rng.uniform(-0.0012, 0.0012) * crooked
                o.location.z += sgn * rng.uniform(0, 0.0012) * crooked
            teeth.append(o); cols.append(tooth_color())
    # gum: a tube-ish strip along the arch above (upper) / below (lower) the crowns
    bm = bmesh.new()
    rows = []
    n = 24
    for j in range(-n, n + 1):
        u = abs(j) / n
        side = 1 if j >= 0 else -1
        x = side * half * math.sin(u * math.pi / 2) ** 0.9 * 1.04
        y = depth * u ** 1.8 - 0.0008
        ring = []
        for a in range(8):
            t = a / 8 * 2 * math.pi
            r = 0.0032
            ring.append(bm.verts.new((x + 0.0 * math.cos(t), y + r * math.cos(t), -sgn * (0.0045 + r * 0.6 * math.sin(t)))))
        rows.append(ring)
    for r0, r1 in zip(rows, rows[1:]):
        for a in range(8):
            bm.faces.new((r0[a], r0[(a + 1) % 8], r1[(a + 1) % 8], r1[a]))
    gum_me = bpy.data.meshes.new("Gum_" + ("Upper" if upper else "Lower"))
    bm.to_mesh(gum_me); bm.free()
    gum = bpy.data.objects.new(gum_me.name, gum_me); scene.collection.objects.link(gum)
    for p in gum_me.polygons:
        p.use_smooth = True
    gum_me.materials.append(material("gum", color=tuple(T.get("gum", [0.62, 0.27, 0.28])), rough=0.45, spec=0.4))
    # join the teeth into one mesh, per-tooth colour through a small palette texture (Godot reads base colour maps)
    if teeth:
        pal = np.array([np.linspace(c * 0.82, c, 8) for c in cols])          # root darker -> edge lighter
        pal_img = image("teeth_palette_" + jaw, pal.reshape(len(cols), 8, 3))
        tm = material("teeth_" + jaw, pal_img, rough=0.32, spec=0.5)
        for ti, o in enumerate(teeth):
            uvl = o.data.uv_layers.active or o.data.uv_layers.new()
            for poly in o.data.polygons:
                for li in poly.loop_indices:
                    z = o.data.vertices[o.data.loops[li].vertex_index].co.z
                    zz = max(0.0, min(1.0, z / 0.012 + 0.5))
                    uvl.data[li].uv = (zz * 0.99, 1 - (ti + 0.5) / len(teeth))
            o.data.materials.clear(); o.data.materials.append(tm)
        bpy.ops.object.select_all(action="DESELECT")
        for o in teeth:
            o.select_set(True)
        bpy.context.view_layer.objects.active = teeth[0]
        bpy.ops.object.join()
        tj = bpy.context.active_object
        tj.name = tj.data.name = "Teeth_" + ("Upper" if upper else "Lower")
        bpy.ops.object.transform_apply(location=True, rotation=True, scale=True)
    else:
        tj = None
    return tj, gum


tu, gu = arch(True)
tl, gl = arch(False)
gap = 0.0007                                            # upper edge just in front of / over the lower one
for o in (tu, gu):
    if o:
        o.location = (0, -0.0006, gap)
for o in (tl, gl):
    if o:
        o.location = (0, 0.0006, -gap)

# ================================================================== tongue
tlen = float(G.get("length", 0.055))
bpy.ops.mesh.primitive_uv_sphere_add(segments=24, ring_count=12, radius=1)
tongue = bpy.context.active_object; tongue.name = tongue.data.name = "Tongue"
for v in tongue.data.vertices:
    x, y, z = v.co
    t = (y + 1) / 2                                          # 0 tip (front, -Y) .. 1 root
    wdt = 0.62 + 0.38 * math.sin(min(1, t * 1.4) * math.pi / 2)   # rounded tip, widest in the middle
    zz = z * (0.28 if z > 0 else 0.22)
    if z > 0:
        zz -= 0.10 * math.exp(-(x / 0.16) ** 2) * max(0.0, min(1.0, (t - 0.25) / 0.4))   # groove, not at the tip
    v.co = Vector((x * 0.42 * wdt, y * 0.5, zz)) * tlen
for p in tongue.data.polygons:
    p.use_smooth = True
tcol = np.array(G.get("colour", [0.72, 0.33, 0.36]))
tex = np.empty((64, 64, 3))
grain = np.random.default_rng(3).random((64, 64))
tex[:] = tcol * (0.9 + 0.12 * grain[..., None])
tongue.data.materials.append(material("tongue", image("tongue_texture", tex), rough=0.4, spec=0.35))
uvl = tongue.data.uv_layers.active or tongue.data.uv_layers.new()
tongue.location = (0, tlen * 0.55, -0.006)
bpy.ops.object.select_all(action="DESELECT"); tongue.select_set(True)
bpy.context.view_layer.objects.active = tongue
bpy.ops.object.transform_apply(location=True)


# ================================================================== export + preview
def export(objs, name):
    bpy.ops.object.select_all(action="DESELECT")
    for o in objs:
        if o:
            o.select_set(True)
    bpy.ops.export_scene.gltf(filepath=str(OUT / name), export_format="GLB", use_selection=True, export_animations=False)


export(eyes, "eyes.glb")
export([tu, tl, gu, gl], "teeth.glb")
export([tongue], "tongue.glb")

try:
    scene.render.engine = "BLENDER_EEVEE_NEXT"
except TypeError:
    try:
        scene.render.engine = "BLENDER_EEVEE"
    except TypeError:
        scene.render.engine = "BLENDER_WORKBENCH"
scene.render.resolution_x, scene.render.resolution_y = 900, 420
scene.render.image_settings.color_mode = "RGB"
w = bpy.data.worlds.new("w"); scene.world = w; w.use_nodes = True
next(n for n in w.node_tree.nodes if n.type == "BACKGROUND").inputs["Color"].default_value = (0.75, 0.74, 0.72, 1)
for rot, en in (((math.radians(60), 0, math.radians(-30)), 3.0), ((math.radians(70), 0, math.radians(160)), 1.2)):
    s = bpy.data.objects.new("sun", bpy.data.lights.new("sun", "SUN")); s.data.energy = en; s.rotation_euler = rot
    scene.collection.objects.link(s)
# layout for the picture: eyes left, teeth (open) centre, tongue right
eyes[0].location = (-0.07, 0, 0.0); eyes[1].location = (-0.07, 0.3, 0.0)   # one eye in the picture
for o in (tu, gu):
    if o:
        o.location = (0.0, o.location.y, 0.012)
for o in (tl, gl):
    if o:
        o.location = (0.0, o.location.y, -0.012)
tongue.location = (0.075, 0, 0); tongue.rotation_euler = (math.radians(-25), 0, math.radians(55))   # shown three-quarter
cam = bpy.data.objects.new("cam", bpy.data.cameras.new("cam")); scene.collection.objects.link(cam); scene.camera = cam
cam.data.type = "ORTHO"; cam.data.ortho_scale = 0.2
cam.location = (0, -0.3, 0.12); cam.rotation_euler = (math.radians(68), 0, 0)
scene.render.filepath = str(OUT / "preview.png")
bpy.ops.render.render(write_still=True)

info = {"eye_radius": eye_r, "teeth_per_side": per, "teeth_upper": len(tu.data.polygons) if tu else 0,
        "missing": sorted(f"{a}{b}" for a, b in missing), "yellow": yellow, "crooked": crooked, "fangs": fangs,
        "tongue_length": tlen, "files": ["eyes.glb", "teeth.glb", "tongue.glb", "preview.png"]}
(OUT / "parts.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
print("FACE_PARTS_OK", json.dumps(info), flush=True)
