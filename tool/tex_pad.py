"""Texture padding: the empty background between a texture's UV islands filled from the islands round it (numpy only:
imported inside Blender by blender_texbake.py and by plain Python scripts).

A baked texture has its islands and a few pixels of margin; the rest is black (and a roughness map's black is 0: a
mirror). Seen from afar the GPU reads smaller copies of the texture (mipmaps), each pixel the mean of many: along every
seam the islands' edges took in the background - dark, glossy, ragged lines over cloth and armour (the archers in the
game). Here every background pixel gets the colour of the islands nearest it: pull-push (each smaller level the mean
of the covered pixels under it, then down again, the empty pixels from the level above), the islands themselves untouched.
"""
import io
import json
import struct

import numpy as np


def pad_fill(img, mask):
    """img: (H, W, C) floats or uint8; mask: (H, W) bool - the islands' pixels. -> img with every other pixel filled from
    the islands round it (smoothly; the same dtype)."""
    dt = img.dtype
    a = img.astype(np.float32)
    if a.ndim == 2:
        a = a[..., None]
    m = mask.astype(np.float32)
    if not m.any() or m.all():
        return img
    levels = []
    c, w = a * m[..., None], m
    while True:
        levels.append((c, w))
        h_, w_ = w.shape
        if h_ <= 1 and w_ <= 1:
            break
        H2, W2 = (h_ + 1) // 2, (w_ + 1) // 2
        cp = np.zeros((H2 * 2, W2 * 2, c.shape[2]), np.float32); cp[:h_, :w_] = c
        wp = np.zeros((H2 * 2, W2 * 2), np.float32); wp[:h_, :w_] = w
        c = cp.reshape(H2, 2, W2, 2, -1).sum(axis=(1, 3))
        w = wp.reshape(H2, 2, W2, 2).sum(axis=(1, 3))
    fill = None
    for c, w in reversed(levels):
        col = c / np.maximum(w, 1e-8)[..., None]
        if fill is not None:
            up = np.repeat(np.repeat(fill, 2, axis=0), 2, axis=1)[:c.shape[0], :c.shape[1]]
            col = np.where(w[..., None] > 0, col, up)
        fill = col
    out = np.where(mask[..., None], a, fill)
    if img.ndim == 2:
        out = out[..., 0]
    if np.issubdtype(dt, np.integer):
        out = np.clip(np.round(out), 0, np.iinfo(dt).max)
    return out.astype(dt)


# ---------------------------------------------------------------- a GLB's textures padded by its own UVs
def _accessor(j, bin0, i):
    acc = j["accessors"][i]
    bv = j["bufferViews"][acc["bufferView"]]
    comp = {5120: np.int8, 5121: np.uint8, 5122: np.int16, 5123: np.uint16, 5125: np.uint32, 5126: np.float32}[acc["componentType"]]
    n = {"SCALAR": 1, "VEC2": 2, "VEC3": 3, "VEC4": 4}[acc["type"]]
    start = bv.get("byteOffset", 0) + acc.get("byteOffset", 0)
    stride = bv.get("byteStride", 0) or np.dtype(comp).itemsize * n
    raw = np.frombuffer(bin0, np.uint8, count=stride * (acc["count"] - 1) + np.dtype(comp).itemsize * n, offset=start)
    if stride == np.dtype(comp).itemsize * n:
        return raw.view(comp).reshape(acc["count"], n)
    return np.lib.stride_tricks.as_strided(raw, (acc["count"], np.dtype(comp).itemsize * n), (stride, 1)).copy().view(comp).reshape(acc["count"], n)


def glb_image_uvs(j, bin0):
    """{image index: [(uv (N, 2), triangles (M, 3)), ...]} - every primitive whose material samples that image (its
    colour, roughness or normal texture, by the texCoord set it names)"""
    out = {}
    for mesh in j.get("meshes", []):
        for p in mesh.get("primitives", []):
            if p.get("mode", 4) != 4 or "material" not in p:
                continue
            mat = j["materials"][p["material"]]
            refs = [t for t in ((mat.get("pbrMetallicRoughness") or {}).get("baseColorTexture"),
                                (mat.get("pbrMetallicRoughness") or {}).get("metallicRoughnessTexture"),
                                mat.get("normalTexture"), mat.get("occlusionTexture"), mat.get("emissiveTexture")) if t]
            if not refs:
                continue
            if "indices" in p:
                tri = _accessor(j, bin0, p["indices"]).reshape(-1, 3).astype(np.int64)
            else:
                n = j["accessors"][p["attributes"]["POSITION"]]["count"]
                tri = np.arange(n - n % 3).reshape(-1, 3)
            for t in refs:
                key = f"TEXCOORD_{t.get('texCoord', 0)}"
                if key not in p["attributes"]:
                    continue
                uv = _accessor(j, bin0, p["attributes"][key]).astype(np.float32)
                src = j["textures"][t["index"]].get("source")
                if src is not None:
                    out.setdefault(src, []).append((uv, tri))
    return out


def uv_mask(parts, W, H, grow=1):
    """the pixels the triangles cover (UVs 0..1, glTF's: v down the image), a pixel or so grown (PIL draws them)"""
    from PIL import Image, ImageDraw, ImageFilter
    im = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(im)
    for uv, tri in parts:
        px = np.empty_like(uv)
        px[:, 0] = (uv[:, 0] % 1.0) * W
        px[:, 1] = (uv[:, 1] % 1.0) * H
        for a, b, c in tri:
            d.polygon([tuple(px[a]), tuple(px[b]), tuple(px[c])], fill=255)
    if grow:
        im = im.filter(ImageFilter.MaxFilter(2 * grow + 1))
    return np.asarray(im) > 0


def pad_glb_image(data, parts):
    """an image's bytes (PNG/JPEG) padded by the UVs that sample it -> (PIL image, padded); returns the image as it was
    when nothing samples it"""
    from PIL import Image
    im = Image.open(io.BytesIO(data))
    if not parts:
        return im, False
    mode = im.mode
    rgb = im.convert("RGBA" if "A" in mode else "RGB")
    a = np.asarray(rgb)
    mask = uv_mask(parts, rgb.width, rgb.height)
    if mask.all() or not mask.any():
        return im, False
    padded = pad_fill(a[..., :3], mask)
    if a.shape[2] == 4:
        padded = np.concatenate([padded, a[..., 3:]], axis=2)
    return Image.fromarray(padded, "RGBA" if a.shape[2] == 4 else "RGB"), True


def read_glb(b):
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + jl])
    bl = struct.unpack("<I", b[20 + jl:24 + jl])[0]
    return j, b[28 + jl:28 + jl + bl]
