"""Draws the shared emblems (heraldic heads: boar, bear, lion, dragon, werewolf, dog) and the digits 0-9 as white
silhouettes on transparency, the decals the «Paint» brush puts on a piece (armour_gen_editor.html, «Picture»).

    python make_decals.py [out_dir]

Each is drawn here from paths in a 100 x 100 box (y down), 4x oversampled and scaled down, so the set needs no font
or outside picture. A decal of one's own is any PNG put in export/decals (its alpha is the shape, its colours are used
when the look is «As drawn»)."""
import re
import sys
from pathlib import Path

from PIL import Image, ImageDraw

SIZE, OVER = 512, 4


def _bez(p0, p1, p2, p3, n=24):
    return [tuple((1 - t) ** 3 * a + 3 * (1 - t) ** 2 * t * b + 3 * (1 - t) * t * t * c + t ** 3 * d for a, b, c, d in zip(p0, p1, p2, p3))
            for t in (i / n for i in range(1, n + 1))]


def polys(d):
    """An SVG-like path (M, L, C, Q, Z, absolute) -> its closed polygons."""
    out, cur, pts = [], None, []
    tok = re.findall(r"[MLCQZ]|-?\d+(?:\.\d+)?", d)
    i, cmd = 0, None
    num = lambda: float(tok[i])
    while i < len(tok):
        if tok[i] in "MLCQZ":
            cmd = tok[i]; i += 1
            if cmd == "Z":
                if pts: out.append(pts)
                pts = []
                continue
        if cmd == "M":
            if pts: out.append(pts)
            cur = (float(tok[i]), float(tok[i + 1])); pts = [cur]; i += 2; cmd = "L"
        elif cmd == "L":
            cur = (float(tok[i]), float(tok[i + 1])); pts.append(cur); i += 2
        elif cmd == "C":
            c = [float(x) for x in tok[i:i + 6]]; i += 6
            pts += _bez(cur, c[0:2], c[2:4], c[4:6]); cur = tuple(c[4:6])
        elif cmd == "Q":
            c = [float(x) for x in tok[i:i + 4]]; i += 4
            q1 = (cur[0] + 2 / 3 * (c[0] - cur[0]), cur[1] + 2 / 3 * (c[1] - cur[1]))
            q2 = (c[2] + 2 / 3 * (c[0] - c[2]), c[3] + 2 / 3 * (c[1] - c[3]))
            pts += _bez(cur, q1, q2, c[2:4]); cur = tuple(c[2:4])
    if pts: out.append(pts)
    return out


def draw(shape, holes="", over="", strokes=(), width=0):
    """shape filled, holes cut out of it, over filled again on top (a tusk inside its own outline gap)."""
    big = SIZE * OVER
    im = Image.new("L", (big, big), 0)
    dr = ImageDraw.Draw(im)
    k = big / 100
    for p in polys(shape):
        dr.polygon([(x * k, y * k) for x, y in p], fill=255)
    for p in polys(holes):
        dr.polygon([(x * k, y * k) for x, y in p], fill=0)
    for p in polys(over):
        dr.polygon([(x * k, y * k) for x, y in p], fill=255)
    for d in strokes:   # thick lines (the digits)
        for p in polys(d):
            q = [(x * k, y * k) for x, y in p]
            dr.line(q, fill=255, width=int(width * k), joint="curve")
            r = width * k / 2
            for x, y in q:   # a round pen at every point: no notches where the line turns
                dr.ellipse((x - r, y - r, x + r, y + r), fill=255)
    a = im.resize((SIZE, SIZE), Image.LANCZOS)
    out = Image.new("RGBA", (SIZE, SIZE), (255, 255, 255, 0))
    out.putalpha(a)
    return out


# ---------------------------------------------------------------- the heads (profile, facing left), couped at the neck
BOAR = ("M 84 93 L 70 93 L 64 85 C 56 87 45 87 37 83 C 29 80 21 77 14 73 C 9 71 6 67 7 62 C 8 57 11 55 15 55 "
        "C 20 50 27 45 34 40 C 38 36 41 32 43 28 L 40 12 C 46 16 51 21 54 25 L 57 15 L 61 22 L 65 12 L 68 21 L 73 13 "
        "L 75 22 L 80 17 L 80 27 C 84 33 87 42 88 52 C 89 64 88 76 86 86 Z")
BOAR_HOLES = ("M 47 44 C 49 41 52 41 54 43 C 52 46 49 46 47 44 Z "     # the eye
              "M 9 61 C 10 59 12 59 13 61 C 12 63 10 63 9 61 Z "        # the nostril
              "M 14 68 C 22 70 30 72 38 72 L 38 74 C 30 74 21 73 13 70 Z "   # the mouth
              "M 30 73 C 25 66 23 58 25 49 C 27 46 30 46 31 49 C 29 56 31 64 35 71 Z "   # the tusk's gap
              "M 41 27 L 41 34 L 46 30 Z")   # the ear's inner side
BOAR_OVER = "M 31 72 C 27 66 26 58 27 50 C 28 49 29 49 29 50 C 28 57 30 65 33 71 Z"   # the tusk

BEAR = ("M 84 93 L 66 93 L 62 85 C 54 86 45 84 37 80 C 31 77 24 74 18 72 C 12 70 8 67 8 62 C 8 57 12 54 17 54 "
        "C 22 51 27 47 32 42 C 36 37 40 33 45 30 C 43 24 45 18 50 16 C 55 14 60 17 61 22 C 65 22 69 23 72 25 "
        "C 74 20 79 17 84 19 C 88 21 89 27 86 31 C 89 38 90 48 90 58 C 90 70 88 82 84 93 Z")
BEAR_HOLES = ("M 47 41 C 49 39 52 39 53 41 C 52 43 49 43 47 41 Z "
              "M 14 67 C 22 69 29 70 36 70 L 36 72 C 28 72 21 71 13 69 Z "
              "M 49 24 C 50 21 54 20 56 22 C 55 25 52 27 50 27 Z "
              "M 77 27 C 78 24 82 23 84 25 C 83 28 80 29 78 29 Z")
BEAR_OVER = "M 6 59 C 6 55 10 53 14 54 C 16 56 16 61 14 63 C 10 64 6 63 6 59 Z"   # the nose

LION = ("M 80 94 L 64 94 L 58 88 C 50 90 42 88 35 84 C 30 81 26 78 22 76 C 17 75 13 72 13 68 C 13 64 16 62 19 62 "
        "C 16 59 12 57 11 53 C 10 49 13 46 17 46 C 21 43 25 40 28 35 C 30 29 34 25 39 22 "
        "L 36 12 L 45 18 L 46 6 L 53 15 L 58 4 L 61 15 L 69 6 L 69 17 L 78 11 L 76 22 L 86 19 L 82 29 L 92 30 "
        "L 85 38 L 94 42 L 86 47 L 94 54 L 85 57 L 92 65 L 83 67 L 89 75 L 80 76 L 85 84 L 77 84 Z")
LION_HOLES = ("M 33 38 C 35 35 39 35 41 37 C 39 40 35 40 33 38 Z "
              "M 18 66 C 24 66 30 68 34 71 L 33 73 C 28 70 23 69 17 69 Z "
              "M 44 26 C 50 30 54 38 55 47 C 56 56 54 66 50 74 L 47 72 C 51 64 52 56 51 48 C 50 40 47 33 42 28 Z")
LION_OVER = "M 18 70 C 22 72 26 75 28 79 C 25 80 21 78 19 75 Z"   # the tongue

DRAGON = ("M 84 95 L 70 95 L 66 86 C 58 84 50 80 44 75 C 38 72 30 70 22 70 C 16 70 10 69 6 66 L 14 63 "
          "C 20 63 26 63 32 62 C 26 60 18 58 10 58 C 8 56 8 53 10 51 C 18 49 26 46 33 41 C 37 37 41 33 45 30 "
          "L 40 14 C 46 18 50 22 53 26 L 58 8 C 60 16 61 22 62 27 L 70 22 L 69 31 L 78 30 L 75 38 L 85 40 L 79 47 "
          "L 89 51 L 81 56 L 90 62 L 82 66 L 89 74 L 80 76 L 86 85 L 78 85 Z")
DRAGON_HOLES = ("M 40 41 C 43 37 47 37 49 40 C 47 43 43 44 40 41 Z "      # the eye
                "M 12 54 C 13 52 15 52 16 54 C 15 56 13 56 12 54 Z "      # the nostril
                "M 12 59 C 20 60 27 61 33 62 L 32 64 C 26 64 19 63 12 62 Z "   # between the jaws
                "M 47 31 C 48 27 51 22 55 18 C 54 24 53 29 51 33 Z")     # under the horn
DRAGON_OVER = ("M 15 59 L 16 61 L 17 59 Z M 20 60 L 21 62 L 22 60 Z M 25 61 L 26 63 L 27 61 Z "   # teeth
               "M 17 63 L 18 61 L 19 63 Z M 22 63 L 23 61 L 24 63 Z M 27 63 L 28 61 L 29 63 Z")

WEREWOLF = ("M 82 95 L 66 95 L 62 87 C 54 86 47 82 41 77 L 30 77 C 22 77 14 76 8 73 L 16 69 C 22 68 28 68 33 69 "
            "C 27 66 18 64 9 63 C 6 61 5 58 6 55 C 14 53 22 50 29 46 C 33 42 37 38 40 34 L 36 12 L 46 25 "
            "L 52 8 L 56 26 C 61 26 66 28 70 31 L 78 26 L 77 35 L 87 35 L 81 42 L 91 45 L 84 50 L 93 56 L 85 59 "
            "L 92 66 L 84 68 L 90 76 L 81 77 L 86 86 L 78 86 Z")
WEREWOLF_HOLES = ("M 39 43 C 42 40 46 41 48 44 C 45 46 41 46 39 43 Z "     # the eye, narrowed
                  "M 9 66 C 18 66 26 67 33 69 L 32 71 C 25 70 17 70 9 69 Z "  # between the jaws
                  "M 43 24 L 44 33 L 49 30 Z")                              # the ear's inner side
WEREWOLF_OVER = ("M 13 66 L 15 69 L 17 66 Z M 20 66 L 22 69 L 24 66 Z "     # fangs above
                 "M 15 70 L 17 67 L 19 70 Z M 23 70 L 25 67 L 27 70 Z")     # and below

DOG = ("M 80 94 L 64 94 L 60 85 C 52 85 44 83 37 79 C 31 76 24 73 18 71 C 12 70 7 66 7 61 C 7 56 11 53 16 53 "
       "C 22 50 28 46 33 41 C 37 35 42 30 48 27 C 54 24 62 24 68 26 C 76 29 82 36 85 45 C 88 55 88 68 86 80 "
       "C 85 86 83 90 80 94 Z")
DOG_HOLES = ("M 44 40 C 46 37 49 37 51 39 C 49 42 46 42 44 40 Z "
             "M 13 67 C 21 69 28 70 35 70 L 35 72 C 27 72 20 71 12 69 Z "
             "M 56 31 C 64 30 70 34 72 42 C 74 52 72 62 67 70 C 64 64 61 56 58 48 C 56 42 55 36 56 31 Z "   # the ear's gap
             "M 62 80 C 68 78 76 78 84 80 L 83 85 C 76 83 69 83 63 85 Z")   # the collar's gap
DOG_OVER = ("M 58 33 C 64 33 68 37 69 43 C 70 51 69 59 66 66 C 63 60 61 53 60 47 C 59 41 58 37 58 33 Z "   # the ear
            "M 5 58 C 6 54 10 53 13 54 C 15 56 15 60 13 62 C 10 63 6 62 5 58 Z "   # the nose
            "M 63 81 C 69 79 76 79 83 81 L 83 84 C 76 82 69 82 63 84 Z")   # the collar


# ---------------------------------------------------------------- the digits: thick strokes with round ends
DIGITS = {
    "0": ["M 50 14 C 30 14 26 34 26 50 C 26 66 30 86 50 86 C 70 86 74 66 74 50 C 74 34 70 14 50 14 Z"],
    "1": ["M 36 26 L 54 14 L 54 86", "M 38 86 L 70 86"],
    "2": ["M 28 30 C 30 18 40 14 50 14 C 62 14 72 22 72 34 C 72 50 52 62 28 86 L 74 86"],
    "3": ["M 28 22 C 34 16 42 14 50 14 C 62 14 70 22 70 32 C 70 42 62 48 48 48 C 64 48 74 56 74 68 C 74 80 64 86 50 86 C 40 86 32 83 26 76"],
    "4": ["M 62 86 L 62 14 L 24 66 L 78 66"],
    "5": ["M 70 14 L 34 14 L 30 46 C 36 42 44 40 50 40 C 64 40 74 50 74 63 C 74 78 63 86 50 86 C 40 86 32 83 26 77"],
    "6": ["M 68 18 C 62 15 56 14 50 14 C 34 14 26 32 26 54 C 26 74 34 86 50 86 C 64 86 74 76 74 63 C 74 50 64 42 51 42 C 40 42 31 48 27 58"],
    "7": ["M 26 14 L 74 14 L 42 86"],
    "8": ["M 50 48 C 38 48 30 40 30 31 C 30 21 38 14 50 14 C 62 14 70 21 70 31 C 70 40 62 48 50 48 C 36 48 26 56 26 67 C 26 79 36 86 50 86 C 64 86 74 79 74 67 C 74 56 64 48 50 48 Z"],
    "9": ["M 32 82 C 38 85 44 86 50 86 C 66 86 74 68 74 46 C 74 26 66 14 50 14 C 36 14 26 24 26 37 C 26 50 36 58 49 58 C 60 58 69 52 73 42"],
}

HEADS = {"boar": BOAR, "bear": BEAR, "lion": LION, "dragon": DRAGON, "werewolf": WEREWOLF, "dog": DOG}


def main(out):
    out.mkdir(parents=True, exist_ok=True)
    for name, shape in HEADS.items():
        u = name.upper()
        draw(shape, globals().get(u + "_HOLES", ""), globals().get(u + "_OVER", "")).save(out / f"{name}.png")
    for d, strokes in DIGITS.items():
        draw("", strokes=strokes, width=12).save(out / f"digit_{d}.png")


if __name__ == "__main__":
    main(Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent)
