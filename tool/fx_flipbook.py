"""Procedural flipbook sheets for Godot particles (frames in a grid on one PNG with alpha), stylised for an ARPG.

    make_flipbook(kind, out_png, grid=8, size=256, seed=1, tint=(1,1,1), speed=1.0)

kind:
  explosion  fireball that swells, cools to smoke and erodes away (one-shot)
  smoke      a puff that grows, drifts up and dissolves (one-shot)
  fire       a flame that licks upward; the sheet loops seamlessly (noise is periodic in time)
  magic      a swirling glowing burst for spells (one-shot; tint it)
  spark      a single soft glow dot with a short streak (one frame, for spark / ember particles)
All noise is fractal value noise (a few octaves of smoothly upsampled random grids); volume is faked by shading
the density as a height field lit from the top left.
"""
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def _fbm(shape, octaves, seed, wrap_t=False, base=4):
    """fractal noise in [0,1] of shape (T, S, S); each octave doubles the frequency"""
    rng = np.random.default_rng(seed)
    T, S, _ = shape
    out = np.zeros(shape, np.float32)
    amp, tot = 1.0, 0.0
    for o in range(octaves):
        n = base * 2 ** o
        nt = max(2, min(T, int(n * T / S) + 2))
        g = rng.random((nt, n, n)).astype(np.float32)
        if wrap_t:
            g = np.concatenate([g, g[:3]], 0)
        z = ndimage.zoom(g, ((T + (3 * T // nt if wrap_t else 0)) / g.shape[0], S / n, S / n), order=3,
                         mode="grid-wrap")
        out += amp * z[:T, :S, :S]
        tot += amp
        amp *= 0.5
    out /= tot
    return (out - out.min()) / max(out.max() - out.min(), 1e-6)


def _spectral(shape, seed, slope=2.2, min_k=0.0):
    """noise that is exactly periodic along every axis (random phases with a power-law spectrum), in [0,1]"""
    rng = np.random.default_rng(seed)
    freqs = np.meshgrid(*[np.fft.fftfreq(n) * n for n in shape], indexing="ij")
    k = np.sqrt(sum(f * f for f in freqs))
    k[(0,) * len(shape)] = 1
    amp = 1.0 / k ** slope
    amp[(0,) * len(shape)] = 0
    if min_k:
        ks = np.sqrt(sum(f * f for f in freqs[1:]))     # spatial frequency only (axis 0 is time)
        amp[ks < min_k] = 0
    spec = amp * np.exp(2j * np.pi * rng.random(shape))
    n = np.real(np.fft.ifftn(spec)).astype(np.float32)
    return (n - n.min()) / max(n.max() - n.min(), 1e-6)


def _grad(stops):
    """colour ramp: list of (position, (r,g,b,a)) -> function of an array in [0,1]"""
    pos = np.array([p for p, _ in stops])
    col = np.array([c for _, c in stops], np.float32)

    def f(x):
        x = np.clip(x, 0, 1)
        return np.stack([np.interp(x, pos, col[:, i]) for i in range(4)], -1)
    return f


FIRE = _grad([(0.0, (0.25, 0.04, 0.0, 0.0)), (0.25, (0.65, 0.12, 0.02, 0.6)), (0.5, (1.0, 0.42, 0.06, 0.9)),
              (0.75, (1.0, 0.78, 0.3, 1.0)), (1.0, (1.0, 0.97, 0.85, 1.0))])


def _shade(dens, light=(-0.6, -0.7, 0.9)):
    """fake volume lighting: the density as a height field, Lambert from the top left (rows grow downwards)"""
    h = ndimage.gaussian_filter(dens, 1.2)
    gy, gx = np.gradient(h)
    n = np.stack([-gx * 6, -gy * 6, np.ones_like(h)], -1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    lvec = np.array(light, np.float32)
    lvec /= np.linalg.norm(lvec)
    return np.clip((n * lvec).sum(-1), 0, 1)


def _frames(kind, n, size, seed, tint, speed):
    yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / size - 0.5   # -0.5..0.5, rows down
    r = np.hypot(xx, yy)
    t = np.linspace(0, 1, n, endpoint=(kind != "fire"))
    out = []
    if kind == "fire":
        # periodic in time (the sheet loops) and in height (the noise scrolls up and wraps)
        small = 96
        noise = _spectral((n, small, small), seed, slope=1.9, min_k=3.0)
        noise = ndimage.zoom(noise, (1, size / small, size / small), order=1, mode="grid-wrap")
        h = np.clip(0.45 - yy, 0, 1) / 0.95                        # 0 at the bottom .. 1 at the top
        width = 0.28 * (1 - h) ** 0.7 + 0.015
        body = np.clip(1 - np.abs(xx) / width, 0, 1) * np.clip((yy + 0.48) * 8, 0, 1)
        for i in range(n):
            nz = np.roll(noise[i], -int(round(i / n * size)), axis=0)
            nz = 0.5 + (nz - nz.mean()) / max(nz.std(), 1e-6) * 0.18   # steady brightness frame to frame
            d = body * (0.35 + 1.1 * nz) - 0.42 - 0.5 * h ** 1.3
            heat = np.clip(d * 2.0, 0, 1)
            c = FIRE(heat)
            c[..., :3] *= np.array(tint, np.float32)
            out.append(c)
        return out
    noise = _fbm((n, size, size), 5, seed, base=4)
    for i, ti in enumerate(t):
        nz = noise[i]
        if kind == "explosion":
            rad = 0.14 + 0.30 * (1 - np.exp(-ti * 7 * speed))
            lift = 0.10 * ti
            rr = np.hypot(xx, (yy + lift) * 1.05) / rad
            dens = np.clip(1.25 - rr + (nz - 0.5) * 0.9, 0, 1)
            erode = np.clip((ti - 0.35) / 0.65, 0, 1) ** 1.2
            dens = np.clip((dens - erode * 0.9) / max(1 - erode * 0.9, 0.05), 0, 1)
            heat = np.clip(dens * (1.6 - 2.4 * ti) + (nz - 0.5) * 0.4, 0, 1)
            lit = _shade(dens)
            smoke = np.empty(dens.shape + (4,), np.float32)
            g = 0.22 + 0.5 * lit
            smoke[..., 0], smoke[..., 1], smoke[..., 2] = g * 0.95, g * 0.9, g * 0.86
            smoke[..., 3] = np.clip(dens * 1.8, 0, 1)
            fire = FIRE(heat)
            w = np.clip(heat * 1.6, 0, 1)[..., None]
            c = smoke * (1 - w) + fire * w
            c[..., 3] = np.maximum(smoke[..., 3], fire[..., 3] * w[..., 0])
        elif kind == "smoke":
            rad = 0.12 + 0.28 * (1 - np.exp(-ti * 4 * speed))
            rr = np.hypot(xx, (yy + 0.12 * ti) * 1.1) / rad
            dens = np.clip(1.2 - rr + (nz - 0.5) * 1.0, 0, 1)
            erode = np.clip((ti - 0.25) / 0.75, 0, 1)
            dens = np.clip((dens - erode * 0.95) / max(1 - erode * 0.95, 0.05), 0, 1)
            lit = _shade(dens)
            g = 0.35 + 0.55 * lit
            c = np.stack([g * 0.92, g * 0.9, g * 0.88, np.clip(dens * 1.5, 0, 1) * (1 - 0.3 * ti)], -1)
        elif kind == "magic":
            ang = np.arctan2(yy, xx)
            rad = 0.1 + 0.32 * (1 - np.exp(-ti * 5 * speed))
            swirl = np.sin(ang * 3 + r * 25 - ti * 9 + (nz - 0.5) * 3)
            ring = np.exp(-((r - rad) / 0.06) ** 2)
            core = np.exp(-(r / (0.08 + 0.1 * (1 - ti))) ** 2) * (1 - ti)
            v = np.clip(ring * (0.6 + 0.4 * swirl) + core + (nz - 0.5) * 0.3 * ring, 0, 1) * (1 - ti ** 2)
            c = np.stack([v, v, v, v], -1)
            c[..., :3] = np.clip(c[..., :3] * 0.6 + v[..., None] ** 2 * 0.6, 0, 1)
        c[..., :3] *= np.array(tint, np.float32)
        if kind == "explosion" and i >= n - 4:
            c[..., 3] *= (n - i) / 5
        out.append(np.clip(c, 0, 1))
    return out


def make_flipbook(kind, out_png, grid=8, size=256, seed=1, tint=(1.0, 1.0, 1.0), speed=1.0):
    out_png = Path(out_png)
    out_png.parent.mkdir(parents=True, exist_ok=True)
    if kind == "spark":
        yy, xx = np.mgrid[0:size, 0:size].astype(np.float32) / size - 0.5
        glow = np.exp(-(np.hypot(xx, yy) / 0.08) ** 2) + 0.35 * np.exp(-(np.hypot(xx * 0.25, yy) / 0.05) ** 2)
        v = np.clip(glow, 0, 1)
        c = np.stack([np.clip(v * 1.3, 0, 1) * tint[0], np.clip(v * 1.1, 0, 1) * tint[1], v * tint[2], v], -1)
        Image.fromarray((c * 255).astype(np.uint8), "RGBA").save(out_png)
        return dict(kind=kind, grid=1, frames=1, size=size, file=str(out_png))
    frames = _frames(kind, grid * grid, size, seed, tint, speed)
    sheet = np.zeros((grid * size, grid * size, 4), np.float32)
    for i, f in enumerate(frames):
        y, x = divmod(i, grid)
        sheet[y * size:(y + 1) * size, x * size:(x + 1) * size] = f
    # straight (not premultiplied) alpha, what Godot expects for a mix blend
    Image.fromarray((np.clip(sheet, 0, 1) * 255).astype(np.uint8), "RGBA").save(out_png)
    return dict(kind=kind, grid=grid, frames=grid * grid, size=size, loop=kind == "fire", file=str(out_png))


def preview(png, out, grid):
    """the sheet on a dark ground (for the UI)"""
    a = Image.open(png).convert("RGBA")
    bg = Image.new("RGBA", a.size, (34, 38, 52, 255))
    bg.alpha_composite(a)
    bg = bg.convert("RGB")
    bg.thumbnail((900, 900))
    bg.save(out)
    return out
