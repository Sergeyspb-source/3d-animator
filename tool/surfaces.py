"""Seamless ground / floor materials: a generated top-down picture -> tileable albedo + normal, height, roughness
and ambient-occlusion maps + a Godot StandardMaterial3D (.tres) + previews.

    make_material(src_png, out_dir, name, size=1024, strength=1.0, rough=(0.55, 0.95), tile_m=4.0)

Everything is computed with wrap-around filters, so the maps tile exactly like the albedo.
"""
import json
from pathlib import Path

import numpy as np
from PIL import Image
from scipy import ndimage


def _square(im, size):
    w, h = im.size
    s = min(w, h)
    im = im.crop(((w - s) // 2, (h - s) // 2, (w - s) // 2 + s, (h - s) // 2 + s))
    return im.resize((size, size), Image.LANCZOS)


def make_tileable(a, band=0.18):
    """Cross-fade the picture with a copy shifted by half: the copy's borders come from the original's middle and
    are continuous across the tile edge; the weight keeps the original in the centre, the copy near the borders."""
    n = a.shape[0]
    shifted = np.roll(np.roll(a, n // 2, 0), n // 2, 1)
    t = np.linspace(0, 1, n)
    d = np.minimum(t, 1 - t)                              # distance to the nearest edge, 0..0.5
    w1 = np.clip(d / band, 0, 1)
    w1 = w1 * w1 * (3 - 2 * w1)
    w = np.minimum.outer(w1, w1)[..., None]              # 1 inside, 0 at the edges
    out = a * w + shifted * (1 - w)
    # keep the contrast where the two layers are mixed 50/50 (mixing flattens the detail)
    mix = 4 * w * (1 - w)
    mean = ndimage.uniform_filter(out, size=(n // 16, n // 16, 1), mode="wrap")
    out = mean + (out - mean) * (1 + 0.35 * mix)
    return np.clip(out, 0, 1)


def seam_error(a):
    """mean colour jump across the tile edges, relative to the jump between neighbouring pixels inside"""
    inner = np.abs(np.diff(a, axis=1)).mean() + np.abs(np.diff(a, axis=0)).mean()
    edge = np.abs(a[:, 0] - a[:, -1]).mean() + np.abs(a[0] - a[-1]).mean()
    return float(edge / max(inner, 1e-6))


def maps_from_albedo(a, strength=1.0, rough=(0.55, 0.95)):
    lum = (a[..., 0] * 0.3 + a[..., 1] * 0.59 + a[..., 2] * 0.11)
    n = lum.shape[0]
    # height: luminance with the large-scale lighting removed (dark cracks low, light stones high)
    big = ndimage.gaussian_filter(lum, n / 24, mode="wrap")
    h = lum - big
    h = ndimage.gaussian_filter(h, 1.0, mode="wrap")
    h = (h - h.min()) / max(h.max() - h.min(), 1e-6)
    # normal map (OpenGL style, +Y up, what Godot expects)
    gx = ndimage.sobel(h, 1, mode="wrap")
    gy = ndimage.sobel(h, 0, mode="wrap")
    k = 6.0 * strength
    nx, ny, nz = -gx * k, gy * k, np.ones_like(h)
    ln = np.sqrt(nx * nx + ny * ny + nz * nz)
    normal = np.dstack([nx / ln, ny / ln, nz / ln]) * 0.5 + 0.5
    # ambient occlusion: how much lower a texel is than its neighbourhood
    ao = 1 - np.clip((ndimage.gaussian_filter(h, n / 128, mode="wrap") - h) * 3.0, 0, 1)
    ao = ndimage.gaussian_filter(ao, 1.0, mode="wrap")
    # roughness: cracks and dirt rough, raised worn parts a bit smoother
    r0, r1 = rough
    roughness = r1 - (r1 - r0) * h
    return h, normal, roughness, ao


def _save(arr, path, mode="RGB"):
    a = np.clip(arr * 255 + 0.5, 0, 255).astype(np.uint8)
    Image.fromarray(a, mode if a.ndim == 3 else "L").save(path)


def godot_tres(name, files, tile_m, strength):
    """A StandardMaterial3D that uses the maps; triplanar so it tiles by world size on any mesh. Texture paths are
    relative to the .tres, so the folder can be copied anywhere in the Godot project."""
    scale = 1.0 / tile_m
    return f"""[gd_resource type="StandardMaterial3D" load_steps=5 format=3]

[ext_resource type="Texture2D" path="{files['albedo']}" id="1"]
[ext_resource type="Texture2D" path="{files['normal']}" id="2"]
[ext_resource type="Texture2D" path="{files['roughness']}" id="3"]
[ext_resource type="Texture2D" path="{files['ao']}" id="4"]

[resource]
albedo_texture = ExtResource("1")
roughness_texture = ExtResource("3")
roughness_texture_channel = 0
normal_enabled = true
normal_scale = {strength:.2f}
normal_texture = ExtResource("2")
ao_enabled = true
ao_texture = ExtResource("4")
ao_texture_channel = 0
uv1_scale = Vector3({scale:.3f}, {scale:.3f}, {scale:.3f})
uv1_triplanar = true
uv1_world_triplanar = true
texture_filter = 5
"""


def preview(albedo, normal, ao, path):
    """3x3 tiles (the seams would show) next to a lit sample (light from the top left, shows the relief)."""
    tiles = np.tile(albedo, (3, 3, 1))
    n = normal * 2 - 1
    light = np.array([-0.5, 0.5, 0.7])
    light /= np.linalg.norm(light)
    lamb = np.clip((n * light).sum(-1), 0, 1)
    lit = albedo * (0.35 + 0.75 * lamb[..., None]) * (0.6 + 0.4 * ao[..., None])
    lit = np.tile(lit, (2, 2, 1))
    t = Image.fromarray((np.clip(tiles, 0, 1) * 255).astype(np.uint8)).resize((600, 600), Image.LANCZOS)
    l = Image.fromarray((np.clip(lit, 0, 1) * 255).astype(np.uint8)).resize((600, 600), Image.LANCZOS)
    out = Image.new("RGB", (1220, 600), (235, 235, 238))
    out.paste(t, (0, 0))
    out.paste(l, (620, 0))
    out.save(path)


def make_material(src_png, out_dir, name, size=1024, strength=1.0, rough=(0.55, 0.95), tile_m=4.0):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    im = _square(Image.open(src_png).convert("RGB"), size)
    a = np.asarray(im).astype(np.float32) / 255.0
    before = seam_error(a)
    if before > 1.15:
        a = make_tileable(a)
    after = seam_error(a)
    h, normal, roughness, ao = maps_from_albedo(a, strength, rough)
    files = {k: f"{name}_{k}.png" for k in ("albedo", "normal", "roughness", "ao", "height")}
    _save(a, out_dir / files["albedo"])
    _save(normal, out_dir / files["normal"])
    _save(roughness, out_dir / files["roughness"])
    _save(ao, out_dir / files["ao"])
    _save(h, out_dir / files["height"])
    (out_dir / f"{name}.tres").write_text(godot_tres(name, files, tile_m, strength), encoding="utf-8")
    preview(a, normal, ao, out_dir / f"{name}_preview.png")
    info = dict(name=name, source=str(src_png), size=size, tile_m=tile_m, normal_strength=strength,
                seam_before=round(before, 2), seam_after=round(after, 2), files=files)
    (out_dir / f"{name}.json").write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    return info


def _periodic(n, slope, seed):
    """seamless noise in [0,1]: random phases with a power-law spectrum (exactly periodic in both axes)"""
    rng = np.random.default_rng(seed)
    f = np.fft.fftfreq(n) * n
    k = np.sqrt(f[:, None] ** 2 + f[None, :] ** 2)
    k[0, 0] = 1
    amp = 1.0 / k ** slope
    amp[0, 0] = 0
    z = np.real(np.fft.ifft2(amp * np.exp(2j * np.pi * rng.random((n, n)))))
    return (z - z.min()) / max(z.max() - z.min(), 1e-9)


def procedural_stone(out_png, size=1024, seed=1, base=(0.40, 0.39, 0.37), moss=0.35):
    """rough natural stone without joints (for 3D blocks that already have their own joints): seamless albedo"""
    h = 0.18 * _periodic(size, 2.6, seed) + 0.42 * _periodic(size, 1.5, seed + 1) + 0.4 * _periodic(size, 0.9, seed + 2)
    h = (h - h.min()) / (h.max() - h.min())
    pits = np.clip((0.1 - _periodic(size, 1.0, seed + 3)) * 8, 0, 1)
    col = np.array(base, np.float32)
    a = col * (0.78 + 0.5 * h[..., None]) * (1 - 0.4 * pits[..., None])
    m = np.clip((_periodic(size, 2.2, seed + 4) - 0.62) * 4, 0, 1) * np.clip(1.2 - h * 1.6, 0, 1) * moss
    a = a * (1 - m[..., None]) + np.array([0.20, 0.27, 0.12], np.float32) * (0.5 + h[..., None]) * m[..., None]
    Image.fromarray((np.clip(a, 0, 1) * 255).astype(np.uint8)).save(out_png)
    return out_png
