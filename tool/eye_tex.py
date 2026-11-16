"""The eyeball's picture (numpy only): an equirect map of a sphere whose pole looks forward - row = the angle from the
gaze (row 0 = the front pole), column = the azimuth about it (0 = the eye's lateral side, a quarter turn = up).

Used by blender_face_parts.py (the characters' face-parts set) and blender_creature_eyes.py (a creature's eyes); the
skeleton viewer (skeleton_view.html, eyeTexture) draws the same for its live preview.

E (all optional): sclera, iris, iris_dark, pupil_color [r, g, b] 0..1; iris_size (degrees of the iris disc from the
centre, default 32, anime 50); pupil (its share of the iris, default 0.42); slit (false / true / "round" / "slit" -
upright, a cat's / "hslit" - level, a goat's); veins (0..1); fibres (0..1: the iris's fibres and dark rim, 0 = one flat
colour); style ("real" / "anime").
"""
import math

import numpy as np


def eye_texture(E: dict, seed=1, w=1024, h=512):
    iris = np.array(E.get("iris", [0.32, 0.45, 0.22])); dark = np.array(E.get("iris_dark", (iris * 0.35).tolist()))
    sclera = np.array(E.get("sclera", [0.93, 0.91, 0.87])); veins = float(E.get("veins", 0.35))
    pupil = float(E.get("pupil", 0.42)); slit = E.get("slit", False)
    slit = {True: "slit", False: "round", None: "round"}.get(slit, slit) if not isinstance(slit, str) else slit
    pupil_col = np.array(E.get("pupil_color", [0.015, 0.012, 0.012]))
    fibres = float(E.get("fibres", 1.0))
    anime = E.get("style") == "anime"
    theta = (np.arange(h)[:, None] + 0.5) / h * math.pi          # 0 = front pole
    phi = (np.arange(w)[None, :] + 0.5) / w * 2 * math.pi
    TH, PH = np.broadcast_arrays(theta, phi)
    iris_r = math.radians(float(E.get("iris_size", 50 if anime else 32)))   # iris disc seen from the centre
    r = TH / iris_r                                               # 0 centre .. 1 limbus
    out = np.empty((h, w, 3))
    # sclera: slightly pinker toward the back, thin red veins growing from the back
    back = np.clip((TH - iris_r) / max(math.pi - iris_r, 1e-6), 0, 1)
    out[:] = sclera[None, None] * (1 - 0.18 * back[..., None]) + np.array([0.12, 0.0, 0.0]) * back[..., None] * 0.5
    vr = np.random.default_rng(seed)
    for _ in range(int(24 * veins * (not anime))):
        ph0, amp, freq = vr.uniform(0, 2 * math.pi), vr.uniform(0.02, 0.08), vr.uniform(3, 9)
        path = ph0 + amp * np.sin(TH * freq + vr.uniform(0, 6))
        d = np.abs(((PH - path + math.pi) % (2 * math.pi)) - math.pi) * np.sin(TH)
        m = np.exp(-(d / 0.004) ** 2) * np.clip((TH - iris_r * 1.3) / 0.6, 0, 1) * vr.uniform(0.3, 0.8)
        out = out * (1 - m[..., None]) + np.array([0.62, 0.12, 0.12]) * m[..., None]
    # iris: radial fibres, darker rim (limbal ring), lighter collarette around the pupil
    fib = 0.5 + 0.5 * np.sin(PH * 90 + 3 * np.sin(PH * 7)) * np.sin(PH * 41 + r * 6)
    col = dark[None, None] + (iris - dark)[None, None] * (0.55 + 0.45 * fib[..., None]) * (1.1 - 0.5 * r[..., None])
    col = col * np.clip(1.25 - 0.35 * r, 0.6, 1.25)[..., None]
    if anime:   # flat colour, dark at the top (the lid's shadow), lighter at the bottom, no fibres
        up = np.sin(TH) * np.sin(PH)                                  # +1 at the top of the eye (UV v = +Z)
        flat = dark[None, None] + (iris - dark)[None, None] * (0.75 + 0.25 * fib[..., None] * 0.3)
        col = flat * np.clip(1.0 - 0.9 * np.clip(up / math.sin(iris_r), 0, 1) ** 1.3 + 0.25 * np.clip(-up / math.sin(iris_r), 0, 1), 0.15, 1.3)[..., None]
    limbus = np.clip((r - 0.86) / 0.14, 0, 1)
    col = col * (1 - 0.75 * limbus[..., None])
    if fibres < 1.0:   # toward one flat colour (a monster's eye all red, all white)
        col = iris[None, None] * (1 - fibres) + col * fibres
    inside = r < 1.0
    out[inside] = col[inside]
    edge = (r >= 1.0) & (r < 1.08)                                 # soft blend into the sclera
    t = ((r - 1.0) / 0.08)[edge][:, None]
    k = 0.3 * fibres + (1 - fibres) * 1.0
    out[edge] = col[edge] * (1 - t) * k + out[edge] * (1 - k + k * t)
    # pupil (round, or a slit: upright for a cat, level for a goat)
    x = np.sin(TH) * np.cos(PH); y = np.sin(TH) * np.sin(PH)
    if slit == "slit":
        pup = (np.abs(x) / (math.sin(iris_r) * pupil * 0.35)) ** 2 + (np.abs(y) / (math.sin(iris_r) * 0.95)) ** 2 < 1
    elif slit == "hslit":
        pup = (np.abs(y) / (math.sin(iris_r) * pupil * 0.35)) ** 2 + (np.abs(x) / (math.sin(iris_r) * 0.95)) ** 2 < 1
    else:
        pup = r < pupil
    pup &= TH < math.pi / 2
    out[pup] = pupil_col
    if anime:   # two painted highlights, upper side (they turn with the eye: fine at game distance)
        R = math.sin(iris_r)
        for cx_, cy_, rr in ((-0.38, 0.38, 0.24), (0.32, -0.32, 0.11)):
            m = np.clip(1.4 - np.hypot(x / R - cx_, y / R - cy_) / rr, 0, 1) ** 0.6
            out = out * (1 - m[..., None]) + m[..., None]
    return np.clip(out, 0, 1)
