"""Comparison sheet for a write-up's img/: tiles in a grid, a caption above each, on dark grey.

    D:\\conda\\envs\\sf3d\\python.exe "docs/Solve problems/_tools/sheet.py" OUT.jpg "Caption A" a.png "Caption B" b.png ...
        [--cols 2] [--width 1920] [--title "..."] [--crop]

--crop cuts away the empty border (transparent, or the flat colour of the corners). Tiles of the same size are cut
by one common box, so a before/after pair stays aligned. OUT ending in .jpg -> JPG quality 88, else PNG.
"""
import argparse
import math
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont

BG = (43, 43, 47)
ap = argparse.ArgumentParser()
ap.add_argument("out")
ap.add_argument("items", nargs="+", help="caption path caption path ...")
ap.add_argument("--cols", type=int)
ap.add_argument("--width", type=int, default=1920)
ap.add_argument("--title")
ap.add_argument("--crop", action="store_true")
a = ap.parse_intermixed_args()
if len(a.items) % 2:
    ap.error("give captions and pictures in pairs")
caps, paths = a.items[0::2], a.items[1::2]
tiles = [Image.open(p).convert("RGBA") for p in paths]


def content_box(im):
    px = np.asarray(im)
    if px[..., 3].min() < 250:
        mask = px[..., 3] > 8
    else:
        corner = px[0, 0, :3].astype(int)
        mask = np.abs(px[..., :3].astype(int) - corner).max(axis=2) > 12
    ys, xs = np.nonzero(mask)
    if not len(xs):
        return 0, 0, im.width, im.height
    return xs.min(), ys.min(), xs.max() + 1, ys.max() + 1


if a.crop:
    boxes = [content_box(t) for t in tiles]
    if len({t.size for t in tiles}) == 1:
        u = (min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes))
        boxes = [u] * len(tiles)
    padded = []
    for t, (x0, y0, x1, y1) in zip(tiles, boxes):
        p = int(0.04 * max(x1 - x0, y1 - y0))
        padded.append(t.crop((max(0, x0 - p), max(0, y0 - p), min(t.width, x1 + p), min(t.height, y1 + p))))
    tiles = padded

flat = []
for t in tiles:
    base = Image.new("RGBA", t.size, BG + (255,))
    flat.append(Image.alpha_composite(base, t).convert("RGB"))

cols = a.cols or min(len(flat), 4)
rows = math.ceil(len(flat) / cols)
gap, cap_h = 16, 44
title_h = 60 if a.title else 0
cell_w = (a.width - gap * (cols + 1)) // cols
scaled = [im.resize((cell_w, round(im.height * cell_w / im.width)), Image.LANCZOS) for im in flat]
row_h = [max(s.height for s in scaled[r * cols:(r + 1) * cols]) for r in range(rows)]
height = title_h + sum(row_h) + rows * (cap_h + gap) + gap
sheet = Image.new("RGB", (a.width, height), BG)
dr = ImageDraw.Draw(sheet)
try:
    font, big = ImageFont.truetype("arial.ttf", 26), ImageFont.truetype("arialbd.ttf", 34)
except OSError:
    font = big = ImageFont.load_default()
if a.title:
    dr.text((gap, 12), a.title, fill=(240, 240, 240), font=big)
y = title_h + gap
for r in range(rows):
    for c in range(cols):
        k = r * cols + c
        if k >= len(scaled):
            break
        x = gap + c * (cell_w + gap)
        dr.text((x + 4, y + 8), caps[k], fill=(240, 200, 120), font=font)
        sheet.paste(scaled[k], (x, y + cap_h + (row_h[r] - scaled[k].height) // 2))
    y += cap_h + row_h[r] + gap
out = Path(a.out)
out.parent.mkdir(parents=True, exist_ok=True)
if out.suffix.lower() in (".jpg", ".jpeg"):
    sheet.save(out, quality=88, optimize=True)
else:
    sheet.save(out, optimize=True)
print(f"{out} {sheet.size[0]}x{sheet.size[1]} {out.stat().st_size // 1024} KB")
