"""Modular dungeon kit: build the pieces in Blender, turn a text plan into a placement list, build Godot scenes.

    build_kit(blender, out_dir, mat_dir, cell, height, seed, preview)   -> pieces + kit.glb + kit.json (+ preview png)
    parse_plan(text)                                                    -> placements for the Godot builder
    build_godot(godot, kit_dir, work_dir, plan)                         -> pieces/*.tscn, dungeon_kit.meshlib, demo scene

Plan: rows of characters (north is up), levels separated by a line `---` (the second level is one floor above).
    .  floor       P  floor and a pillar     D  doorway with a door    A  open arch
    W  floor whose outer walls have windows  ^ > v <  stairs going up towards that side (the next level starts there)
    #  or space  nothing (solid)
"""
import json
import shutil
import subprocess
from pathlib import Path
from i18n import t as _t

ROOT = Path(__file__).resolve().parent
NOFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

# sides in the order N, W, S, E: rotation (quarter turns) of a piece made for the north edge, and neighbour offsets
SIDES = {"N": (0, 0, -1), "W": (1, -1, 0), "S": (2, 0, 1), "E": (3, 1, 0)}
STAIRS = {"^": "N", "<": "W", "v": "S", ">": "E"}
CORNER_ROT = {("N", "E"): 0, ("N", "W"): 1, ("S", "W"): 2, ("E", "S"): 3}
SAMPLE = """###########
#.........#
#...P.....#
#.........W
#####D#####
#####.#####
#####A#####
#####.#####
#####v#####
---
###########
###########
###########
###########
###########
###########
###########
###########
###########
###.....###
###.....###
###.....###
"""


def build_kit(blender, out_dir, mat_dir, cell=4.0, height=3.0, seed=1, preview=None, wall="dungeon_wall",
              floor="dungeon_floor", wood="dungeon_wood"):
    out_dir = Path(out_dir)
    args = [str(out_dir), str(mat_dir), f"cell={cell}", f"height={height}", f"seed={seed}", f"wall={wall}",
            f"floor={floor}", f"wood={wood}"]
    if preview:
        args.append(f"preview={preview}")
    r = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_modkit.py"), "--", *args], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=1200, creationflags=NOFLAGS)
    if not (out_dir / "kit.glb").exists():
        raise RuntimeError(_t("kit.blender_did_not_build_the_kit") + (r.stdout + r.stderr)[-600:])
    return [x for x in r.stdout.splitlines() if x.startswith("KIT_")]


def parse_plan(text):
    levels = [[]]
    for line in text.replace("\r", "").split("\n"):
        if line.strip() == "---":
            levels.append([])
        elif line.strip() or levels[-1]:
            levels[-1].append(line)
    levels = [[r for r in lv] for lv in levels if any(r.strip() for r in lv)]
    if not levels:
        raise ValueError(_t("kit.the_plan_is_empty"))

    def cell(lv, x, z):
        if lv < 0 or lv >= len(levels) or z < 0 or z >= len(levels[lv]) or x < 0 or x >= len(levels[lv][z]):
            return "#"
        c = levels[lv][z][x]
        return "#" if c in " #" else c

    stair_void = set()                    # cells above a staircase: open air, no floor
    for lv in range(len(levels)):
        for z, row in enumerate(levels[lv]):
            for x, ch in enumerate(row):
                if ch in STAIRS:
                    stair_void.add((lv + 1, x, z))

    def is_open(lv, x, z):
        return cell(lv, x, z) != "#" or (lv, x, z) in stair_void

    out, lights, doors = [], [], 0
    count = 0
    for lv in range(len(levels)):
        w = max(len(r) for lv2 in levels for r in lv2)
        nz = max([len(levels[lv])] + [z + 1 for (l2, _, z) in stair_void if l2 == lv])
        for z in range(nz):
            for x in range(w):
                ch = cell(lv, x, z)
                void = (lv, x, z) in stair_void and ch == "#"
                if ch == "#" and not void:
                    continue

                def put(piece, rot=0):
                    out.append(dict(piece=piece, x=x, y=lv, z=z, rot=rot))

                stairs_dir = STAIRS.get(ch)
                if stairs_dir:
                    put("stairs", SIDES[stairs_dir][0])
                elif not void:
                    put("floor")
                if ch == "P":
                    put("pillar")
                if not is_open(lv + 1, x, z) and not stairs_dir:
                    put("ceiling")
                elif not is_open(lv + 1, x, z) and stairs_dir:
                    pass
                walls = {}
                for s, (rot, dx, dz) in SIDES.items():
                    if stairs_dir and s in (stairs_dir, {"N": "S", "S": "N", "W": "E", "E": "W"}[stairs_dir]):
                        continue
                    if not is_open(lv, x + dx, z + dz):
                        walls[s] = "wall_window" if ch == "W" else ("wall" if (x * 3 + z * 5 + lv) % 3 else "wall_b")
                    elif ch in "DA" and not void:
                        # doorway on the side of the lower-numbered neighbour along the passage
                        open_sides = [t for t, (_, ex, ez) in SIDES.items() if is_open(lv, x + ex, z + ez)]
                        if s == sorted(open_sides, key="NWSE".index)[0] and len(open_sides) == 2:
                            walls[s] = "wall_door" if ch == "D" else "wall_arch"
                done = set()
                for a, b in CORNER_ROT:
                    if a in walls and b in walls and walls[a] not in ("wall_window",) and \
                            walls[b] not in ("wall_window",) and not ({a, b} & done) and \
                            walls[a] in ("wall", "wall_b") and walls[b] in ("wall", "wall_b"):
                        put("corner", CORNER_ROT[(a, b)])
                        done |= {a, b}
                for s, piece in walls.items():
                    if s in done:
                        continue
                    put(piece, SIDES[s][0])
                    if piece == "wall_door":
                        put("door", SIDES[s][0])
                        doors += 1
                # posts on reflex corners: both side neighbours open, the diagonal one solid
                if not void and not stairs_dir:
                    for a, b, r in (("N", "E", 0), ("N", "W", 1), ("S", "W", 2), ("E", "S", 3)):
                        da, db = SIDES[a], SIDES[b]
                        if is_open(lv, x + da[1], z + da[2]) and is_open(lv, x + db[1], z + db[2]) and \
                                not is_open(lv, x + da[1] + db[1], z + da[2] + db[2]):
                            put("corner_inner", r)
                count += 1
                if not void and (count % 3 == 0 or ch == "P"):
                    lights.append(dict(x=x, y=lv, z=z))
    return dict(pieces=out, lights=lights, levels=len(levels), doors=doors)


def build_godot(godot, kit_dir, work_dir, plan=None):
    kit_dir = Path(kit_dir)
    proj = Path(work_dir) / "kit_build"
    dst = proj / "dungeon_kit"
    if dst.exists():
        shutil.rmtree(dst)
    dst.mkdir(parents=True)
    if not (proj / "project.godot").exists():
        (proj / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="sf3d_kit_build"\n',
                                            encoding="utf-8")
    for f in ("kit.glb", "kit.json"):
        shutil.copy2(kit_dir / f, dst / f)
    shutil.copy2(ROOT / "godot" / "dungeon_door.gd", dst / "dungeon_door.gd")
    shutil.copy2(ROOT / "godot" / "build_kit.gd", proj / "build_kit.gd")
    if plan is not None:
        (dst / "plan.json").write_text(json.dumps(plan), encoding="utf-8")
    subprocess.run([godot, "--headless", "--path", str(proj), "--import"], capture_output=True, timeout=900,
                   creationflags=NOFLAGS)
    r = subprocess.run([godot, "--headless", "--path", str(proj), "--script", "res://build_kit.gd"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                       creationflags=NOFLAGS)
    for f in ("plan.json",):
        (dst / f).unlink(missing_ok=True)
    ok = [x for x in r.stdout.splitlines() if x.startswith("KIT_") and x.strip().endswith(" 0")]
    if not (dst / "dungeon_kit.meshlib").exists():
        raise RuntimeError(_t("kit.godot_did_not_build_the_kit") + (r.stdout + r.stderr)[-600:])
    # publish: everything except the import cache
    if kit_dir.exists():
        for p in dst.rglob("*"):
            if p.suffix in (".import", ".uid") or ".godot" in p.parts:
                continue
            rel = p.relative_to(dst)
            if p.is_dir():
                (kit_dir / rel).mkdir(parents=True, exist_ok=True)
            else:
                (kit_dir / rel).parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(p, kit_dir / rel)
    return ok, r.stdout + r.stderr


README = _t("kit.sf3d_modular_dungeon_kit_copy_the")


def write_readme(kit_dir):
    info = json.loads((Path(kit_dir) / "kit.json").read_text(encoding="utf-8"))
    (Path(kit_dir) / "README.md").write_text(README.format(cell=info["cell"], height=info["height"]),
                                             encoding="utf-8")


def render_shots(godot, kit_dir, work_dir, plan):
    """overview from above (no ceilings) and one view from inside, rendered by Godot; returns png paths"""
    kit_dir = Path(kit_dir)
    proj = Path(work_dir) / "kit_build"
    info = json.loads((kit_dir / "kit.json").read_text(encoding="utf-8"))
    c, h = info["cell"], info["height"]
    pcs = plan["pieces"]
    xs = [(p["x"] + 0.5) * c for p in pcs]
    zs = [(p["z"] + 0.5) * c for p in pcs]
    ys = [p["y"] * h for p in pcs]
    cx, cz = (min(xs) + max(xs)) / 2, (min(zs) + max(zs)) / 2
    span = max(max(xs) - min(xs), max(zs) - min(zs), 8.0)
    top = max(ys) + h
    floors = [p for p in pcs if p["piece"] == "floor" and p["y"] == 0]
    f0 = floors[0] if floors else pcs[0]
    inside = [(f0["x"] + 0.5) * c, 1.7, (f0["z"] + 0.5) * c]
    views = [dict(name="overview", pos=[cx, top + span * 0.6, cz + span * 0.65], look=[cx, top * 0.3, cz],
                  hide_ceiling=True, sun=True),
             dict(name="inside", pos=inside, look=[cx, 1.4, cz], hide_ceiling=False, sun=False)]
    out = kit_dir / "shots"
    out.mkdir(exist_ok=True)
    (proj / "dungeon_kit" / "shots.json").write_text(json.dumps(dict(out=str(out), views=views)), encoding="utf-8")
    shutil.copy2(ROOT / "godot" / "kit_shots.gd", proj / "kit_shots.gd")
    subprocess.run([godot, "--rendering-driver", "opengl3", "--path", str(proj), "--script", "res://kit_shots.gd"],
                   capture_output=True, timeout=300, creationflags=NOFLAGS)
    return [str(out / f"{v['name']}.png") for v in views if (out / f"{v['name']}.png").exists()]
