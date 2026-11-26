"""Skeleton templates by the number of supports: a quadruped (four legs, a tail, a neck), a bird (two legs, wings, a
tail), a serpent (a chain without legs). A template is a list of joints the user places on the model (the markup page
creature_markup.html) and the bones between them; blender_creature_template.py builds the skeleton and its heat
weights from them, creature_gait.py makes its clips.

The bones are named as the creature tools name them (blender_creature_auto.py): hips, spine_01.., chest, neck_01..,
head, tail_01.., leg_FL_1..5 / leg_BL_1..5 (a bird's legs are the hind ones, leg_BL / leg_BR), wing_L_1..3; a serpent's
body spine_01 by the head back to the tail's end. So the jaw, the eyes, the Mesh2Motion clips, the keyed clips, the
viewer and the Godot view take a template's skeleton as they take UniRig's. Every name is plain ASCII with the side
last (_L / _R in joints, FL / BR in legs): Godot keeps them as they are.

Coordinates are glTF (Y up), the creature turned to look along +Z (its left +X) by the markup's `yaw` (degrees about
the up axis), the same frame as <name>_auto.glb's.

    guess(glb, template, yaw=None) -> {"template", "yaw", "cx", "joints": {id: [x, y, z]}, "mouth": None, "height"}
"""
import math
from pathlib import Path

import numpy as np

# ---------------------------------------------------------------- the templates
# A joint: (id, kind) - kind "mid" (on the middle plane x = cx), "L" (its mirror "_R" made from it), "between"
# joints are placed on the line between two others at a share t (+ the user's offset) - the markup page keeps them there
# when their ends move. A bone: (name, head joint, tail joint, parent bone); "{s}" a side (L / R).
QUADRUPED = {
    "id": "quadruped",
    "joints": [
        ("hips", "mid"), ("spine_1", "mid"), ("spine_2", "mid"), ("chest", "mid"), ("neck_1", "mid"), ("neck_2", "mid"),
        ("head", "mid"), ("nose", "mid"),
        ("tail_1", "mid"), ("tail_2", "mid"), ("tail_3", "mid"), ("tail_4", "mid"), ("tail_end", "mid"),
        ("scapula_L", "L"), ("shoulder_L", "L"), ("elbow_L", "L"), ("wrist_L", "L"), ("fpaw_L", "L"), ("ftoe_L", "L"),
        ("pelvis_L", "L"), ("hip_L", "L"), ("knee_L", "L"), ("hock_L", "L"), ("hpaw_L", "L"), ("htoe_L", "L"),
    ],
    "between": {"spine_1": ("hips", "chest", 1 / 3), "spine_2": ("hips", "chest", 2 / 3), "neck_2": ("neck_1", "head", 0.5),
                "tail_2": ("tail_1", "tail_end", 0.25), "tail_3": ("tail_1", "tail_end", 0.5),
                "tail_4": ("tail_1", "tail_end", 0.75)},
    "bones": [
        ("hips", "hips", "spine_1", None), ("spine_01", "spine_1", "spine_2", "hips"),
        ("spine_02", "spine_2", "chest", "spine_01"), ("chest", "chest", "neck_1", "spine_02"),
        ("neck_01", "neck_1", "neck_2", "chest"), ("neck_02", "neck_2", "head", "neck_01"), ("head", "head", "nose", "neck_02"),
        ("tail_01", "tail_1", "tail_2", "hips"), ("tail_02", "tail_2", "tail_3", "tail_01"),
        ("tail_03", "tail_3", "tail_4", "tail_02"), ("tail_04", "tail_4", "tail_end", "tail_03"),
        ("leg_F{s}_1", "scapula_{s}", "shoulder_{s}", "chest"), ("leg_F{s}_2", "shoulder_{s}", "elbow_{s}", "leg_F{s}_1"),
        ("leg_F{s}_3", "elbow_{s}", "wrist_{s}", "leg_F{s}_2"), ("leg_F{s}_4", "wrist_{s}", "fpaw_{s}", "leg_F{s}_3"),
        ("leg_F{s}_5", "fpaw_{s}", "ftoe_{s}", "leg_F{s}_4"),
        ("leg_B{s}_1", "pelvis_{s}", "hip_{s}", "hips"), ("leg_B{s}_2", "hip_{s}", "knee_{s}", "leg_B{s}_1"),
        ("leg_B{s}_3", "knee_{s}", "hock_{s}", "leg_B{s}_2"), ("leg_B{s}_4", "hock_{s}", "hpaw_{s}", "leg_B{s}_3"),
        ("leg_B{s}_5", "hpaw_{s}", "htoe_{s}", "leg_B{s}_4"),
    ],
    # the bones' local Z: "up" (the spine, the neck, the tail, the head), "fwd" (the legs: they bend about X)
    "roll": {"leg_": "fwd"},
}

BIRD = {
    "id": "bird",
    "joints": [
        ("hips", "mid"), ("spine_1", "mid"), ("chest", "mid"), ("neck_1", "mid"), ("neck_2", "mid"), ("neck_3", "mid"),
        ("head", "mid"), ("beak", "mid"), ("tail_1", "mid"), ("tail_2", "mid"), ("tail_end", "mid"),
        ("pelvis_L", "L"), ("hip_L", "L"), ("knee_L", "L"), ("ankle_L", "L"), ("foot_L", "L"), ("toe_L", "L"),
        ("wshoulder_L", "L"), ("welbow_L", "L"), ("wwrist_L", "L"), ("wtip_L", "L"),
    ],
    "between": {"spine_1": ("hips", "chest", 0.5), "neck_2": ("neck_1", "head", 1 / 3), "neck_3": ("neck_1", "head", 2 / 3),
                "tail_2": ("tail_1", "tail_end", 0.5)},
    "bones": [
        ("hips", "hips", "spine_1", None), ("spine_01", "spine_1", "chest", "hips"), ("chest", "chest", "neck_1", "spine_01"),
        ("neck_01", "neck_1", "neck_2", "chest"), ("neck_02", "neck_2", "neck_3", "neck_01"),
        ("neck_03", "neck_3", "head", "neck_02"), ("head", "head", "beak", "neck_03"),
        ("tail_01", "tail_1", "tail_2", "hips"), ("tail_02", "tail_2", "tail_end", "tail_01"),
        ("leg_B{s}_1", "pelvis_{s}", "hip_{s}", "hips"), ("leg_B{s}_2", "hip_{s}", "knee_{s}", "leg_B{s}_1"),
        ("leg_B{s}_3", "knee_{s}", "ankle_{s}", "leg_B{s}_2"), ("leg_B{s}_4", "ankle_{s}", "foot_{s}", "leg_B{s}_3"),
        ("leg_B{s}_5", "foot_{s}", "toe_{s}", "leg_B{s}_4"),
        ("wing_{s}_1", "wshoulder_{s}", "welbow_{s}", "chest"), ("wing_{s}_2", "welbow_{s}", "wwrist_{s}", "wing_{s}_1"),
        ("wing_{s}_3", "wwrist_{s}", "wtip_{s}", "wing_{s}_2"),
    ],
    "roll": {"leg_": "fwd", "wing_": "fwd"},
}

SERPENT_N = 12   # the body's bones from the neck to the tail's end
SERPENT = {
    "id": "serpent",
    # the user places the head (its base and its tip) and points along the body (body_1 .. body_7, tail_end); the
    # bones are spaced evenly along a smooth line through them
    "joints": [("nose", "mid"), ("head", "mid")] + [(f"body_{i}", "free") for i in range(1, 8)] + [("tail_end", "free")],
    "between": {},
    "bones": [],   # made along the line (blender_creature_template.py: spine_01 .. spine_NN, the head under spine_01)
    "roll": {},
    "segments": SERPENT_N,
}

TEMPLATES = {"quadruped": QUADRUPED, "bird": BIRD, "serpent": SERPENT}

# ---------------------------------------------------------------- the procedural clips (creature_gait.py) by body kind
PROC_CLIPS = {"quadruped": ["idle", "walk", "trot", "run", "attack"],
              "bird": ["idle", "walk", "run", "flap", "glide", "attack"],
              "serpent": ["idle", "walk", "run", "attack"]}
PROC_LOOPS = {"idle", "walk", "trot", "run", "flap", "glide"}


def proc_name(c: str) -> str:
    """the clip's name in the GLB: loops end in Godot's «_loop» (imported looping, the suffix taken off)"""
    return c + "_loop" if c in PROC_LOOPS else c


def body_kind(names) -> str | None:
    """a skeleton's body by its bones' names: four legs - a quadruped; two hind legs and wings - a bird; no legs and a
    long spine - a serpent"""
    names = set(names)
    legs = {n[4:6] for n in names if n.startswith("leg_") and len(n) > 6}
    if {"FL", "FR", "BL", "BR"} <= legs:
        return "quadruped"
    if {"BL", "BR"} <= legs and any(n.startswith("wing_L_") for n in names):
        return "bird"
    if not legs and sum(n.startswith("spine_") for n in names) >= 6:
        return "serpent"
    return None


def mirror_id(j: str) -> str | None:
    return j[:-2] + "_R" if j.endswith("_L") else j[:-2] + "_L" if j.endswith("_R") else None


def joint_ids(tpl: dict) -> list:
    """every joint, the right side's too"""
    out = []
    for j, kind in tpl["joints"]:
        out.append(j)
        if kind == "L":
            out.append(mirror_id(j))
    return out


def bones(tpl: dict) -> list:
    """[(name, head, tail, parent)] with both sides"""
    out = []
    for name, h, t, p in tpl["bones"]:
        if "{s}" in name or "{s}" in h:
            for s in "LR":
                out.append((name.format(s=s), h.format(s=s), t.format(s=s), p.format(s=s) if p else None))
        else:
            out.append((name, h, t, p))
    return out


def mirrored(joints: dict, cx: float) -> dict:
    """the right side made from the left one (x mirrored about cx) where the right is missing"""
    out = dict(joints)
    for j, p in joints.items():
        m = mirror_id(j)
        if m and j.endswith("_L") and m not in joints:
            out[m] = [2 * cx - p[0], p[1], p[2]]
    return out


# ---------------------------------------------------------------- the model's points
def load_points(glb: Path):
    """(vertices N x 3, face areas' share per vertex N) of every mesh of a GLB in glTF world space (scene transforms
    applied), skinned or not."""
    import trimesh
    sc = trimesh.load(str(glb), force="scene", process=False, skip_materials=True)
    vs, ws = [], []
    for node in sc.graph.nodes_geometry:
        T, gname = sc.graph[node]
        g = sc.geometry[gname]
        if not hasattr(g, "vertices") or len(g.vertices) == 0:
            continue
        v = trimesh.transform_points(np.asarray(g.vertices, dtype=np.float64), T)
        w = np.zeros(len(v))
        if hasattr(g, "faces") and len(g.faces):
            a = trimesh.triangles.area(v[g.faces])
            np.add.at(w, g.faces.ravel(), np.repeat(a / 3, 3))
        else:
            w[:] = 1.0
        vs.append(v)
        ws.append(w)
    if not vs:
        raise RuntimeError("no meshes")
    return np.concatenate(vs), np.concatenate(ws)


def turn(P: np.ndarray, yaw: float) -> np.ndarray:
    """points turned about +Y by yaw degrees (glTF): the markup's frame"""
    a = math.radians(yaw)
    c, s = math.cos(a), math.sin(a)
    out = P.copy()
    out[:, 0] = c * P[:, 0] + s * P[:, 2]
    out[:, 2] = -s * P[:, 0] + c * P[:, 2]
    return out


def guess_yaw(P: np.ndarray, W: np.ndarray, kind: str) -> float:
    """which way the creature looks: the body's long horizontal axis (0 / 90 degrees), then its end with more mass
    beyond the legs (the head and neck weigh more than a rump and a tail); a serpent's head is the thicker end"""
    best = None
    for yaw in (0.0, 90.0, 180.0, 270.0):
        Q = turn(P, yaw)
        if kind == "bird":
            # (spread wings are longer than the body: the body is the middle strip's long axis; the head's end is
            # the higher one - a standing bird holds its head over its tail)
            cxq = (Q[:, 0].min() + Q[:, 0].max()) / 2
            strip = Q[np.abs(Q[:, 0] - cxq) < 0.12 * np.ptp(Q[:, 0])]
            if len(strip) < 20:
                continue
            z0s, z1s = strip[:, 2].min(), strip[:, 2].max()
            k = 0.2 * (z1s - z0s)
            front, back = strip[strip[:, 2] > z1s - k], strip[strip[:, 2] < z0s + k]
            if np.ptp(strip[:, 2]) < np.ptp(strip[:, 0]):
                continue
            score = np.percentile(front[:, 1], 90) - np.percentile(back[:, 1], 90)
            if best is None or score > best[0]:
                best = (score, yaw)
            continue
        lx, lz = np.ptp(Q[:, 0]), np.ptp(Q[:, 2])
        if lz < lx * 0.8:   # (the long axis across: not this way)
            continue
        y0, H = Q[:, 1].min(), np.ptp(Q[:, 1])
        z0, z1 = Q[:, 2].min(), Q[:, 2].max()
        if kind == "serpent":
            # the head's end: thicker (its cross-section) than the tail's tapering end
            k = 0.12 * (z1 - z0)
            front = Q[Q[:, 2] > z1 - k]
            back = Q[Q[:, 2] < z0 + k]
            score = (np.ptp(front[:, 1]) + np.ptp(front[:, 0])) - (np.ptp(back[:, 1]) + np.ptp(back[:, 0])) if len(front) and len(back) else 0
        else:
            low = Q[Q[:, 1] < y0 + 0.12 * H]
            if len(low) < 8:
                continue
            lf, lb = np.percentile(low[:, 2], 95), np.percentile(low[:, 2], 5)
            score = W[Q[:, 2] > lf].sum() - W[Q[:, 2] < lb].sum()
        if best is None or score > best[0]:
            best = (score, yaw)
    return best[1] if best else 0.0


def _kmeans(X, init, iters=30):
    C = np.array(init, dtype=float)
    for _ in range(iters):
        d = ((X[:, None, :] - C[None, :, :]) ** 2).sum(-1)
        lab = d.argmin(1)
        for k in range(len(C)):
            if (lab == k).any():
                C[k] = X[lab == k].mean(0)
    return C, lab


def _slice(P, z, half):
    return P[np.abs(P[:, 2] - z) < half]


def _spine_y(P, z, half, cx, lo=None):
    """the height of the spine at z: 72 % from the body's underside to its top (robust: percentiles, the mid strip)"""
    S = _slice(P, z, half)
    if lo is not None:
        S = S[S[:, 1] > lo]
    w = np.ptp(P[:, 0])
    S2 = S[np.abs(S[:, 0] - cx) < 0.25 * w] if len(S) else S
    S = S2 if len(S2) > 10 else S
    if not len(S):
        return None, None, None
    top, bot = np.percentile(S[:, 1], 97), np.percentile(S[:, 1], 3)
    return bot + 0.72 * (top - bot), bot, top


def _column(P, x, z, y, r):
    """the leg's middle at height y: the vertices within r of (x, z) in a thin band"""
    band = P[np.abs(P[:, 1] - y) < r * 0.5]
    near = band[(band[:, 0] - x) ** 2 + (band[:, 2] - z) ** 2 < r * r]
    if len(near) < 4:
        return x, z
    return float(near[:, 0].mean()), float(near[:, 2].mean())


def _legs(Q, y0, H, cx, n_front=2, n_back=2):
    """the paws on the ground: the lowest band of vertices in four groups (k-means from the corners) - their middles,
    toe tips and widths; a bird's two feet the same with two"""
    low = Q[Q[:, 1] < y0 + 0.08 * H]
    if len(low) < 8:
        low = Q[Q[:, 1] < y0 + 0.15 * H]
    X = low[:, [0, 2]]
    xs, zs = np.percentile(X[:, 0], [10, 90]), np.percentile(X[:, 1], [10, 90])
    init = []
    if n_front:
        init += [(xs[1], zs[1]), (xs[0], zs[1])]
    if n_back:
        init += [(xs[1], zs[0]), (xs[0], zs[0])]
    C, lab = _kmeans(X, init)
    out = []
    for k in range(len(C)):
        pts = low[lab == k]
        if not len(pts):
            out.append(None)
            continue
        out.append({"x": float(pts[:, 0].mean()), "z": float(pts[:, 2].mean()), "toe_z": float(np.percentile(pts[:, 2], 97)),
                    "w": float(max(np.ptp(pts[:, 0]), np.ptp(pts[:, 2]), 1e-3))})
    return out


def _side_pair(a, b, cx):
    """(left, right) of two paws: left is +X; one missing - the other's mirror"""
    if a is None and b is None:
        return None, None
    if a is None:
        a = {**b, "x": 2 * cx - b["x"]}
    if b is None:
        b = {**a, "x": 2 * cx - a["x"]}
    return (a, b) if a["x"] >= b["x"] else (b, a)


def guess(glb: Path, template: str, yaw: float | None = None) -> dict:
    """the template's joints placed on the model by its shape (a first guess the user moves on the markup page)"""
    P0, W = load_points(Path(glb))
    if yaw is None:
        yaw = guess_yaw(P0, W, template)
    Q = turn(P0, yaw)
    lo, hi = Q.min(0), Q.max(0)
    cx = float((lo[0] + hi[0]) / 2)
    y0, H = float(lo[1]), float(hi[1] - lo[1])
    z0, z1 = float(lo[2]), float(hi[2])
    L = z1 - z0
    J = {}
    fn = {"quadruped": _guess_quadruped, "bird": _guess_bird, "serpent": _guess_serpent}[template]
    fn(Q, J, cx, y0, H, z0, z1, L)
    J = {k: [round(float(v[0]), 5), round(float(v[1]), 5), round(float(v[2]), 5)] for k, v in J.items()}
    return {"template": template, "yaw": yaw, "cx": round(cx, 5), "joints": mirrored(J, cx), "mouth": None,
            "height": round(H, 5), "length": round(L, 5)}


def _lerp(a, b, t):
    return [a[i] + (b[i] - a[i]) * t for i in range(3)]


def _guess_quadruped(Q, J, cx, y0, H, z0, z1, L):
    legs = _legs(Q, y0, H, cx)
    fl, fr = _side_pair(legs[0], legs[1], cx)
    bl, br = _side_pair(legs[2], legs[3], cx)
    if fl is None or bl is None:
        raise RuntimeError("no legs found")
    zf, zb = (fl["z"] + fr["z"]) / 2, (bl["z"] + br["z"]) / 2
    half = 0.04 * L
    # the underside between the legs (the belly) and the back's line
    mid = _slice(Q, (zf + zb) / 2, half)
    belly = float(np.percentile(mid[np.abs(mid[:, 0] - cx) < 0.3 * np.ptp(Q[:, 0])][:, 1], 3)) if len(mid) else y0 + 0.45 * H
    belly = min(max(belly, y0 + 0.2 * H), y0 + 0.7 * H)
    yf, _, top_f = _spine_y(Q, zf, half, cx, lo=belly)
    yb, _, top_b = _spine_y(Q, zb, half, cx, lo=belly)
    yf = yf if yf is not None else y0 + 0.8 * H
    yb = yb if yb is not None else y0 + 0.8 * H
    top_f = top_f if top_f is not None else y0 + H
    top_b = top_b if top_b is not None else y0 + H
    J["chest"] = [cx, yf, zf + 0.02 * L]
    J["hips"] = [cx, yb, zb + 0.02 * L]
    J["spine_1"] = _lerp(J["hips"], J["chest"], 1 / 3)
    J["spine_2"] = _lerp(J["hips"], J["chest"], 2 / 3)
    # the head: the front-most part of the model (the snout's tip on the middle line), its base a head's length back
    front = Q[Q[:, 2] > z1 - 0.03 * L]
    nose_y = float(np.median(front[:, 1])) if len(front) else yf
    J["nose"] = [cx, nose_y, z1 - 0.01 * L]
    head_len = max(0.22 * L, min(0.32 * L, (z1 - zf) * 0.6))
    zh = z1 - head_len
    yh, bh, th = _spine_y(Q, zh, half, cx, lo=y0 + 0.25 * H)
    J["head"] = [cx, (bh + 0.6 * (th - bh)) if yh is not None else nose_y, zh]
    # the neck: on the line from the withers to the head, a little above it (a neck's top arches)
    J["neck_1"] = _lerp(J["chest"], J["head"], 0.4)
    J["neck_1"][1] += 0.02 * H
    J["neck_2"] = _lerp(J["neck_1"], J["head"], 0.5)
    # the tail: from the rump's top-back to the furthest point behind it
    rear = Q[Q[:, 2] < z0 + 0.06 * L]
    t1 = [cx, yb + 0.05 * H, max(z0 + 0.04 * L, zb - 0.16 * L)]
    behind = Q[(Q[:, 2] < t1[2]) & (np.abs(Q[:, 0] - cx) < 0.12 * np.ptp(Q[:, 0]) + 0.02 * L)]
    if len(behind):
        d = np.linalg.norm(behind - np.array(t1), axis=1)
        tip = behind[int(d.argmax())]
        J["tail_end"] = [cx, float(tip[1]), float(tip[2])]
    else:
        J["tail_end"] = [cx, t1[1] - 0.05 * H, t1[2] - 0.1 * L]
    if len(rear) and J["tail_end"][2] > t1[2] - 0.03 * L:
        J["tail_end"][2] = t1[2] - 0.05 * L
    J["tail_1"] = t1
    for k, t in (("tail_2", .25), ("tail_3", .5), ("tail_4", .75)):
        J[k] = _lerp(t1, J["tail_end"], t)
    # the legs: front - the scapula's top under the back, the shoulder joint, the elbow at the chest's underside, the
    # wrist a quarter up, the paw's ball and the toe's tip; hind - the pelvis, the hip joint, the knee (forward), the
    # hock (back), the paw and the toe
    hf, hb = top_f - y0, top_b - y0
    for paw, s in ((fl, "L"),):
        x, zp = paw["x"], paw["z"]
        r = max(paw["w"] * 0.9, 0.04 * L)
        xw, zw = _column(Q, x, zp, y0 + 0.25 * hf, r)
        xe, ze = _column(Q, x, zp, belly + 0.02 * H, r * 1.4)
        J[f"ftoe_{s}"] = [x, y0, max(paw["toe_z"], zp + 0.02 * L)]
        J[f"fpaw_{s}"] = [x, y0 + 0.05 * hf, zp]
        J[f"wrist_{s}"] = [xw, y0 + 0.25 * hf, zw]
        xe = 0.75 * x + 0.25 * xe
        J[f"elbow_{s}"] = [xe, belly + 0.02 * H, ze - 0.03 * L]
        J[f"shoulder_{s}"] = [xe * 0.95 + cx * 0.05, belly + 0.45 * (yf - belly) + 0.05 * H, ze + 0.06 * L]
        J[f"scapula_{s}"] = [cx + (xe - cx) * 0.55, yf + 0.04 * H, ze - 0.02 * L]
    for paw, s in ((bl, "L"),):
        x, zp = paw["x"], paw["z"]
        r = max(paw["w"] * 0.9, 0.04 * L)
        xh, zk = _column(Q, x, zp, y0 + 0.3 * hb, r)
        xk, zkn = _column(Q, x, zp, belly + 0.02 * H, r * 1.4)
        J[f"htoe_{s}"] = [x, y0, max(paw["toe_z"], zp + 0.02 * L)]
        J[f"hpaw_{s}"] = [x, y0 + 0.05 * hb, zp]
        xk = 0.75 * x + 0.25 * xk
        xh = 0.75 * x + 0.25 * xh
        J[f"hock_{s}"] = [xh, y0 + 0.3 * hb, zk - 0.03 * L]
        J[f"knee_{s}"] = [xk, belly + 0.02 * H, zkn + 0.05 * L]
        J[f"hip_{s}"] = [xk * 0.95 + cx * 0.05, belly + 0.55 * (yb - belly), zkn - 0.02 * L]
        J[f"pelvis_{s}"] = [cx + (xk - cx) * 0.5, yb, zkn]


def _guess_bird(Q, J, cx, y0, H, z0, z1, L):
    legs = _legs(Q, y0, H, cx, n_front=2, n_back=0)
    fl, fr = _side_pair(legs[0], legs[1], cx)
    if fl is None:
        fl = {"x": cx + 0.08 * L, "z": (z0 + z1) / 2, "toe_z": (z0 + z1) / 2 + 0.05 * L, "w": 0.03 * L}
    zl = fl["z"]
    W = np.ptp(Q[:, 0])
    # the body: the bulk above the legs; the hips over the feet, the chest in front of them
    body = Q[Q[:, 1] > y0 + 0.3 * H]
    by = float(np.percentile(body[:, 1], 50)) if len(body) else y0 + 0.55 * H
    J["hips"] = [cx, by, zl - 0.02 * L]
    J["chest"] = [cx, by + 0.05 * H, zl + 0.16 * L]
    J["spine_1"] = _lerp(J["hips"], J["chest"], 0.5)
    # the head: the highest part in front (a standing bird's) - its top's front, the beak its front-most point
    upper = Q[(Q[:, 1] > y0 + 0.65 * H) & (Q[:, 2] > zl)]
    if len(upper) > 10:
        hz = float(np.percentile(upper[:, 2], 50))
        hy = float(np.percentile(upper[:, 1], 50))
        tip = upper[int(upper[:, 2].argmax())]
        J["head"] = [cx, hy, hz]
        J["beak"] = [cx, float(tip[1]), float(tip[2])]
    else:
        J["head"] = [cx, y0 + 0.85 * H, z1 - 0.15 * L]
        J["beak"] = [cx, y0 + 0.85 * H, z1]
    J["neck_1"] = _lerp(J["chest"], J["head"], 0.25)
    J["neck_2"] = _lerp(J["neck_1"], J["head"], 1 / 3)
    J["neck_3"] = _lerp(J["neck_1"], J["head"], 2 / 3)
    back = Q[(Q[:, 2] < z0 + 0.1 * L)]
    ty = float(np.median(back[:, 1])) if len(back) else by
    J["tail_1"] = [cx, by, zl - 0.12 * L]
    J["tail_end"] = [cx, ty, z0]
    J["tail_2"] = _lerp(J["tail_1"], J["tail_end"], 0.5)
    x = fl["x"]
    J["toe_L"] = [x, y0, max(fl["toe_z"], fl["z"] + 0.03 * L)]
    J["foot_L"] = [x, y0 + 0.02 * H, fl["z"]]
    J["ankle_L"] = [x, y0 + 0.22 * H, fl["z"] - 0.02 * L]
    J["knee_L"] = [cx + (x - cx) * 0.9, by - 0.12 * H, fl["z"] + 0.06 * L]
    J["hip_L"] = [cx + (x - cx) * 0.8, by, fl["z"] - 0.04 * L]
    J["pelvis_L"] = [cx + (x - cx) * 0.4, by + 0.03 * H, fl["z"] - 0.04 * L]
    # the wings: the furthest point to the left above the legs is the wing's tip (a spread wing), else folded along
    # the body's side
    side = Q[(Q[:, 0] > cx) & (Q[:, 1] > y0 + 0.3 * H)]
    tipw = side[int(side[:, 0].argmax())] if len(side) else np.array([cx + W / 2, by, zl])
    sh = [cx + 0.35 * (W / 2 if np.ptp(Q[:, 0]) < 0.6 * L else 0.12 * L), by + 0.12 * H, J["chest"][2] - 0.02 * L]
    J["wshoulder_L"] = sh
    if tipw[0] - cx > 0.4 * L:   # spread
        J["wtip_L"] = [float(tipw[0]), float(tipw[1]), float(tipw[2])]
        J["welbow_L"] = _lerp(sh, J["wtip_L"], 0.3)
        J["wwrist_L"] = _lerp(sh, J["wtip_L"], 0.58)
    else:   # folded along the side, the tip back
        J["welbow_L"] = [sh[0] + 0.03 * L, sh[1] - 0.06 * H, sh[2] - 0.08 * L]
        J["wwrist_L"] = [sh[0] + 0.03 * L, sh[1] - 0.02 * H, sh[2] + 0.02 * L]
        J["wtip_L"] = [sh[0] + 0.02 * L, sh[1] + 0.02 * H, z0 + 0.1 * L]


def _guess_serpent(Q, J, cx, y0, H, z0, z1, L):
    # the body's middle line: slices along the long axis, each slice's middle (a stretched or wavy snake)
    n = 40
    zs = np.linspace(z0, z1, n + 1)
    mids = []
    for a, b in zip(zs[:-1], zs[1:]):
        S = Q[(Q[:, 2] >= a) & (Q[:, 2] < b)]
        if len(S):
            mids.append([float(np.median(S[:, 0])), float(np.median(S[:, 1])), float((a + b) / 2)])
    mids = np.array(mids)
    # arc length along the middles, the points spaced evenly from the head (the front) to the tail's end
    mids = mids[::-1]
    seg = np.r_[0, np.cumsum(np.linalg.norm(np.diff(mids, axis=0), axis=1))]
    total = seg[-1]
    at = lambda s: [float(np.interp(s, seg, mids[:, i])) for i in range(3)]  # noqa: E731
    head_len = 0.07 * total
    J["nose"] = [mids[0][0], mids[0][1], z1]
    J["head"] = at(head_len)
    for i in range(1, 8):
        J[f"body_{i}"] = at(head_len + (total - head_len) * i / 8)
    J["tail_end"] = [mids[-1][0], mids[-1][1], z0]


# ---------------------------------------------------------------- a serpent's bones along its line
def catmull(pts: list, n: int) -> list:
    """n + 1 points spaced evenly (by arc length) along a Catmull-Rom line through pts"""
    P = [np.array(p, dtype=float) for p in pts]
    P = [2 * P[0] - P[1]] + P + [2 * P[-1] - P[-2]]
    dense = []
    for i in range(1, len(P) - 2):
        p0, p1, p2, p3 = P[i - 1], P[i], P[i + 1], P[i + 2]
        for t in np.linspace(0, 1, 24, endpoint=False):
            t2, t3 = t * t, t * t * t
            dense.append(0.5 * (2 * p1 + (-p0 + p2) * t + (2 * p0 - 5 * p1 + 4 * p2 - p3) * t2 + (-p0 + 3 * p1 - 3 * p2 + p3) * t3))
    dense.append(P[-2])
    D = np.array(dense)
    s = np.r_[0, np.cumsum(np.linalg.norm(np.diff(D, axis=0), axis=1))]
    return [[float(np.interp(v, s, D[:, i])) for i in range(3)] for v in np.linspace(0, s[-1], n + 1)]


def serpent_bones(joints: dict, n: int = SERPENT_N) -> list:
    """[(name, head point, tail point, parent)]: spine_01 .. spine_NN from the head's base back to the tail's end,
    the head bone from its base to the nose under spine_01"""
    line = [joints["head"]] + [joints[f"body_{i}"] for i in range(1, 8) if f"body_{i}" in joints] + [joints["tail_end"]]
    pts = catmull(line, n)
    out = [("head", joints["head"], joints["nose"], "spine_01")]
    for i in range(n):
        out.append((f"spine_{i + 1:02d}", pts[i], pts[i + 1], f"spine_{i:02d}" if i else None))
    return out


def build_list(tpl_id: str, joints: dict) -> list:
    """the bones to build: [(name, head [x,y,z], tail [x,y,z], parent)]"""
    if tpl_id == "serpent":
        return serpent_bones(joints, TEMPLATES["serpent"].get("segments", SERPENT_N))
    return [(n, joints[h], joints[t], p) for n, h, t, p in bones(TEMPLATES[tpl_id])]


def page_data(tpl_id: str) -> dict:
    """the template as the markup page draws it: joints (id, kind), lines between them, the in-between rules"""
    tpl = TEMPLATES[tpl_id]
    if tpl_id == "serpent":
        ids = [j for j, _ in tpl["joints"]]
        lines = [["nose", "head"], ["head", "body_1"]] + [[f"body_{i}", f"body_{i + 1}"] for i in range(1, 7)] + [["body_7", "tail_end"]]
    else:
        lines = [[h, t] for _n, h, t, _p in bones(tpl)]
        ids = joint_ids(tpl)
    return {"id": tpl_id, "joints": [{"id": j, "kind": k} for j, k in tpl["joints"]], "all": ids, "lines": lines,
            "between": {k: list(v) for k, v in tpl.get("between", {}).items()}}


if __name__ == "__main__":
    import json
    import sys
    print(json.dumps(guess(Path(sys.argv[1]), sys.argv[2] if len(sys.argv) > 2 else "quadruped"), indent=1))
