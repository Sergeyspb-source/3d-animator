"""Creatures (four paws, a tail, a muzzle; any skeleton that is not a humanoid's): which models are creatures, their
files and skeleton passport, and the skeleton viewer page (skeleton_view.html) - for any skinned model, a humanoid's too.

A model is a creature when its passport <name>_rig.json says "kind": "creature" (the creature skeleton writes it; a
model added in the «Creatures» section gets it at once, before its skeleton). Its files stay in export/character/<name>/
as a character's do: <name>.glb (the source), <name>_unirig.glb (UniRig's skeleton), <name>_auto.glb (turned; its
bones keep UniRig's names, the passport's "names" rename them - after a markup's rebuild they are named already),
<name>_rigged.glb (named, with the jaw: what the tools take), <name>_jaw_*.png (the jaw's pictures).
"""
import base64
import json
import math
import shutil
import subprocess
from pathlib import Path

import i18n
from i18n import t as _t

ROOT = Path(__file__).resolve().parent
VIEWER = ROOT / "skeleton_view.html"


def passport(d: Path, name: str) -> dict:
    """<name>_rig.json beside the skeleton ({} without one)."""
    try:
        v = json.loads((Path(d) / f"{name}_rig.json").read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def is_creature(d: Path, name: str) -> bool:
    return passport(d, name).get("kind") == "creature"


def mark(d: Path, name: str) -> None:
    """A model taken as a creature before it has a skeleton: its passport says so (kept as it is when it has one)."""
    p = Path(d) / f"{name}_rig.json"
    meta = passport(d, name)
    if meta.get("kind") != "creature":
        meta["kind"] = "creature"
        Path(d).mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def jaw_pictures(d: Path, name: str) -> list:
    """The jaw's pictures made with the skeleton: [(png, caption)] - a closed mouth at rest and open, an open one (its
    mouth marked) as made and closed - from the side and the front."""
    if (passport(d, name).get("jaw") or {}).get("method") == "marked":
        labels = {"0_side": _t("cr.jaw_as_made_side"), "0_front": _t("cr.jaw_as_made_front"),
                  "c_side": _t("cr.jaw_closed_side"), "c_front": _t("cr.jaw_closed_front")}
    else:
        labels = {"0_side": _t("ui.closed_side"), "0_front": _t("ui.closed_front"), "30_side": _t("ui.open_side"),
                  "30_front": _t("ui.open_front")}
    return [(str(Path(d) / f"{name}_jaw_{k}.png"), v) for k, v in labels.items() if (Path(d) / f"{name}_jaw_{k}.png").exists()]


# ------------------------------------------------------------------ the markup: the mouth's points, the joints moved
# Blender (the creature looking along -Y, Z up) <-> glTF (Y up, looking along +Z): the jaw's points are kept as Blender
# (y, z) on the middle plane x = cx (blender_creature_finish.py), the viewer's as glTF [x, y, z]
def _gl(yz, cx=0.0):
    return [cx, yz[1], -yz[0]]


def _yz(p):
    return [-p[2], p[1]]


def mouth_marks(meta: dict) -> dict | None:
    """The mouth's four points for the viewer (glTF): as marked, else from the first guess of the mouth line - the
    hinge, the corner, the lower jaw's front at the line's front and the upper one above it (the user moves them)."""
    jaw = meta.get("jaw") or {}
    if jaw.get("mouth"):
        return jaw["mouth"]
    if not (jaw.get("jaw_front") and jaw.get("jaw_corner") and jaw.get("hinge")):
        return None
    cx = float(jaw.get("cx", 0.0))
    f, h = jaw["jaw_front"], jaw["hinge"]
    gap = 0.35 * math.dist(f, h)
    return {"hinge": _gl(h, cx), "corner": _gl(jaw["jaw_corner"], cx), "lower": _gl([f[0], f[1] - gap / 3], cx),
            "upper": _gl([f[0], f[1] + gap], cx)}


def viewer_data(d: Path, name: str) -> dict:
    """What the viewer edits a creature's markup with: the mouth's points, the tips' ends as last set, the jaw's
    closing turn (degrees about the world X through the hinge), the hidden textbox and button it sends through."""
    meta = passport(d, name)
    jaw = meta.get("jaw") or {}
    return {"edit": True, "mouth": mouth_marks(meta), "ends": meta.get("ends") or {}, "close_deg": jaw.get("close_deg"),
            # (the jaw's limits as the first guess measured them on the snout: the viewer's red preview the same)
            "jaw_params": {k: jaw[k] for k in ("half_width", "fade", "floor") if k in jaw},
            "req_target": REQ_ID, "req_go": REQ_GO}


REQ_ID = "sf3d_creature_req"   # the hidden textbox the viewer writes its request into
REQ_GO = "sf3d_creature_go"    # the hidden button it clicks


def _run(cfg, script, args, ok, timeout=1800):
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / script), "--", *map(str, args)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    line = next((x for x in r.stdout.splitlines() if x.startswith(ok)), None)
    if line is None:
        raise RuntimeError((r.stdout + r.stderr)[-1500:])
    return line


def bone_names(glb: Path) -> list:
    import landmarks
    try:
        j = landmarks._glb_json(glb)
    except Exception:  # noqa: BLE001
        return []
    return [j["nodes"][i].get("name", "") for sk in j.get("skins", []) for i in sk.get("joints", [])]


def is_humanoid(glb: Path) -> bool:
    """A humanoid's skeleton (Mixamo / Godot names: arms, legs): an anthropomorphic creature rigged in «Character»."""
    names = bone_names(glb)
    return any(n.endswith(("LeftArm", "LeftUpperArm")) for n in names) and any(n.endswith(("LeftUpLeg", "LeftUpperLeg")) for n in names)


def mark_jaw(cfg, d: Path, name: str, mouth: dict, rigged: Path | None = None):
    """The jaw made again from the mouth's four points (glTF [x, y, z]: hinge, corner, upper and lower front): the mouth
    line runs from the middle of the gap in front through the corner to the hinge, the jaw bone from the hinge to the
    lower front; with the mouth open the lower jaw is below the gap already - nothing is cut through. Its closing turn
    (the lower front onto the upper one) is kept for the viewer's slider and the clips. Yields log lines; writes
    <name>_rigged.glb, its pictures as made and closed, the passport.
    A skeleton made elsewhere (a humanoid's from «Character»: rigged, no <name>_auto.glb): the jaw goes onto it in place,
    from its copy without the jaw (<stem>.nojaw.glb, made the first time), under its head bone."""
    import rigging as RG
    d = Path(d)
    meta = passport(d, name)
    auto = d / f"{name}_auto.glb"
    dst = d / f"{name}_rigged.glb"
    names = meta.get("names") or {}
    if not auto.exists():
        if rigged is None or not Path(rigged).exists():
            raise RuntimeError(_t("cr.no_auto", auto.name))
        dst = Path(rigged)
        auto = dst.with_name(dst.stem + ".nojaw.glb")
        if not auto.exists():
            if "jaw" in bone_names(dst):
                raise RuntimeError(_t("cr.jaw_there", dst.name))
            shutil.copy2(dst, auto)
        names = {}
    h, c, up, lo = (mouth[k] for k in ("hinge", "corner", "upper", "lower"))
    cx = h[0]   # (the middle plane: the hinge's; the corner may stand off it, at the mouth's real corner)
    H, C, U, L = _yz(h), _yz(c), _yz(up), _yz(lo)
    gap = [(U[0] + L[0]) / 2, (U[1] + L[1]) / 2]
    # the closing turn: the lower front onto the upper one about the world X through the hinge (glTF: a turn about +X
    # takes +Y to +Z)
    a_lo = math.atan2(lo[2] - h[2], lo[1] - h[1])
    a_up = math.atan2(up[2] - h[2], up[1] - h[1])
    close = math.degrees((a_up - a_lo + math.pi) % (2 * math.pi) - math.pi)
    old = meta.get("jaw") or {}
    span = math.dist(gap, H)
    jaw = {"jaw_front": gap, "jaw_corner": C, "hinge": H, "chin": L, "cx": cx,
           # the jaw's width: out to the mouth's corner (marked off the middle) and a little past it, else as guessed
           "half_width": round(max(abs(c[0] - h[0]) * 1.3, 0.35 * span), 4) if abs(c[0] - h[0]) > 0.05 * span
           else (old.get("half_width") or round(0.7 * span, 4)),
           # (no floor to speak of: the jaw is the skin reached from its front - blender_creature_finish.py)
           "floor": round(min(L[1], H[1]) - 2.5 * span, 4),
           "fade": old.get("fade") or round(0.3 * span, 4),
           "jaw_parent": old.get("jaw_parent") or next((n for n in bone_names(auto) if n.lower().endswith("head")), "head"),
           "method": "marked", "mouth": mouth, "close_deg": round(close, 2), "open_deg": round(abs(close), 2)}
    paint = mouth.get("paint") if "paint" in mouth else (old.get("mouth") or {}).get("paint")   # (a request without one: kept)
    if paint is not None:
        mouth = {**mouth, "paint": paint}
        jaw["mouth"] = mouth
    if paint and (paint.get("plus") or paint.get("minus")):   # (painted by hand: a file for Blender, kept with the marks)
        pf = Path(cfg["work_dir"]) / "creature_rebuild" / f"{name}_paint.json"
        pf.parent.mkdir(parents=True, exist_ok=True)
        pf.write_text(json.dumps(paint), encoding="utf-8")
        jaw["paint_file"] = str(pf)
    yield _t("cr.jaw_marked", round(abs(close), 1))
    res = RG.creature_finish(auto, dst, cfg.get("blender_exe"), names, jaw, preview=str(d / f"{name}_jaw.png"),
                             angles=[0.0, -abs(close)], tags=["0", "c"])
    meta["kind"] = "creature"
    jaw.pop("paint_file", None)
    meta["jaw"] = jaw
    (d / f"{name}_rig.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    yield _t("cr.jaw_done", dst.name, res["jaw_vertices"])


def rebuild(cfg, d: Path, name: str, req: dict):
    """The skeleton moved to the edited markup (req: joints, ends - glTF; reweight) and skinned again, then its jaw
    from the mouth's points. The named skeleton before the first edit is kept (<name>_auto.unirig.glb). Yields log
    lines."""
    d = Path(d)
    auto, rigged = d / f"{name}_auto.glb", d / f"{name}_rigged.glb"
    src = auto if auto.exists() else rigged
    keep = d / f"{name}_auto.unirig.glb"
    if auto.exists() and not keep.exists():
        shutil.copy2(auto, keep)
    work = Path(cfg["work_dir"]) / "creature_rebuild"
    work.mkdir(parents=True, exist_ok=True)
    job = work / f"{name}.json"
    reweight = req.get("reweight", "local")
    reweight = {True: "local", False: "none"}.get(reweight, reweight)
    job.write_text(json.dumps({"src": str(src), "out": str(auto), "joints": req.get("joints", {}), "ends": req.get("ends", {}),
                               "reweight": reweight, "names": passport(d, name).get("names") or {}}), encoding="utf-8")
    yield _t("cr.rebuilding", _t("cr.weights_" + reweight))
    rep = json.loads(_run(cfg, "blender_creature_rebuild.py", [job], "REBUILD_OK").split(" ", 1)[1])
    yield _t("cr.rebuilt", rep.get("moved", 0), rep.get("fallback_vertices", 0), rep.get("kept_old", 0))
    meta = passport(d, name)
    meta["ends"] = {**(meta.get("ends") or {}), **req.get("ends", {})}
    meta["kind"] = "creature"
    (d / f"{name}_rig.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    mouth = req.get("mouth") or mouth_marks(meta)
    if mouth:
        yield from mark_jaw(cfg, d, name, mouth)


def summary(rigged: Path) -> dict:
    """The skeleton's bones by their names, read off the GLB's JSON: {bones, paws: {FL: n, ...}, tail, head, jaw}."""
    import landmarks
    try:
        j = landmarks._glb_json(rigged)
    except Exception:  # noqa: BLE001
        return {}
    joints = {i for sk in j.get("skins", []) for i in sk.get("joints", [])}
    names = [j["nodes"][i].get("name", "") for i in joints]
    paws = {}
    for n in names:
        if n.startswith("leg_") and len(n) > 6:
            paws[n[4:6]] = paws.get(n[4:6], 0) + 1
    return {"bones": len(names), "paws": paws, "tail": sum(n.startswith("tail") for n in names),
            "head": "head" in names, "jaw": "jaw" in names}


def viewer_page(glb: Path, title: str = "", kind: str = "", badge: str = "", edit: dict | None = None) -> str:
    """The skeleton viewer on this model (embedded whole: the page is an iframe's srcdoc); edit: viewer_data(), the
    creature's markup to edit (its joints, its mouth), else only looked at."""
    page = i18n.fill(VIEWER.read_text(encoding="utf-8"))
    data = {"title": title or Path(glb).stem, "kind": kind, "badge": badge, **(edit or {})}
    return (page.replace("@@DATA@@", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
                .replace("@@GLB@@", base64.b64encode(Path(glb).read_bytes()).decode("ascii")))


# ------------------------------------------------------------------ clips: a quadruped's (Mesh2Motion) on the creature
M2M = ROOT.parent / "Animations" / "Mesh2Motion" / "glb"
# the sources of quadrupeds' clips: their GLB and the clips that loop
CLIP_SOURCES = {"fox": ("fox-animations.glb", {"Idle", "Idle Alert", "Walk", "Run", "Sneak"}),
                "horse": ("horse-animations.glb", {"Idle", "Walk", "Trot", "Run", "Eating", "Sleep"})}


def clip_sources() -> dict:
    """{key: (GLB path, [its clips])} of the sources there are (their rest pose left out)."""
    out = {}
    for k, (f, _) in CLIP_SOURCES.items():
        p = M2M / f
        if not p.exists():
            continue
        try:
            import landmarks
            names = [a.get("name", "") for a in landmarks._glb_json(p).get("animations", [])]
        except Exception:  # noqa: BLE001
            continue
        out[k] = (p, [n for n in names if n and "rest" not in n.lower()])
    return out


def clip_key(source: str, clip: str) -> str:
    return f"{source}_{clip}".lower().replace(" ", "_")


def animate(cfg, d: Path, name: str, picks: dict):
    """The clips picked ({source: [clip names]}) put on the creature (blender_creature_retarget.py) into
    <name>_clips.glb, the model with them, named <source>_<clip>. Yields log lines."""
    d = Path(d)
    rigged = d / f"{name}_rigged.glb"
    if not rigged.exists():
        raise RuntimeError(_t("cr.view_needs_skeleton"))
    src = clip_sources()
    clips = [{"source": str(src[k][0]), "action": c, "name": clip_key(k, c), "loop": c in CLIP_SOURCES[k][1]}
             for k, cs in picks.items() if k in src for c in cs]
    if not clips:
        raise RuntimeError(_t("cr.anim_none_picked"))
    work = Path(cfg["work_dir"]) / "creature_clips"
    work.mkdir(parents=True, exist_ok=True)
    out = d / f"{name}_clips.glb"
    job = work / f"{name}.json"
    job.write_text(json.dumps({"target": str(rigged), "clips": clips, "out": str(out), "mesh": True,
                               "close_deg": (passport(d, name).get("jaw") or {}).get("close_deg")}), encoding="utf-8")
    yield _t("cr.anim_running", len(clips))
    _run(cfg, "blender_creature_retarget.py", [job], "RETARGET_OK")
    made = json.loads(Path(str(out) + ".json").read_text(encoding="utf-8"))
    yield _t("cr.anim_done", out.name, len(made), ", ".join(c["name"] for c in made))


def straighten(cfg, d: Path, name: str, pose: dict | None = None):
    """The rest pose straightened (blender_creature_straighten.py: the paws under their shoulders and hips, the pairs
    level, the body on the middle line) and made the rest; the mouth's marks moved with the head, the jaw made again;
    the tips' ends set before forgotten (the legs moved). The skeleton before the first change is kept
    (<name>_auto.unirig.glb). Yields log lines."""
    d = Path(d)
    auto = d / f"{name}_auto.glb"
    if not auto.exists():
        raise RuntimeError(_t("cr.no_auto", auto.name))
    keep = d / f"{name}_auto.unirig.glb"
    if not keep.exists():
        shutil.copy2(auto, keep)
    meta = passport(d, name)
    work = Path(cfg["work_dir"]) / "creature_rebuild"
    work.mkdir(parents=True, exist_ok=True)
    job = work / f"{name}_straighten.json"
    job.write_text(json.dumps({"src": str(auto), "out": str(auto), "names": meta.get("names") or {}, "pose": pose or {}}),
                   encoding="utf-8")
    yield _t("cr.rest_from_pose") if pose else _t("cr.straightening")
    rep = json.loads(_run(cfg, "blender_creature_straighten.py", [job], "STRAIGHTEN_OK").split(" ", 1)[1])
    yield _t("cr.straightened", ", ".join(f"{k} {v}°" for k, v in rep["turned"].items()) or "—")
    if rep.get("paws_mm") is not None:
        yield _t("cr.on_ground", ", ".join(f"{k.replace('leg_', '')[:2]} {v}" for k, v in rep["paws_mm"].items()), rep.get("lift_mm", 0))
    # the mouth's marks with the head (Blender world <-> glTF: (x, y, z) -> (x, -z, y))
    Hm = rep["head"]
    def move(p):
        b = [p[0], -p[2], p[1]]
        q = [sum(Hm[i][k] * b[k] for k in range(3)) + Hm[i][3] for i in range(3)]
        return [q[0], q[2], -q[1]]
    mouth = mouth_marks(meta)
    meta.pop("ends", None)
    (d / f"{name}_rig.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    if mouth:
        moved = {k: move(v) for k, v in mouth.items() if k != "paint"}
        if mouth.get("paint"):
            moved["paint"] = {k: [move(p) for p in v] for k, v in mouth["paint"].items()}
        yield from mark_jaw(cfg, d, name, moved)


def restore(cfg, d: Path, name: str):
    """The skeleton UniRig made back (<name>_auto.unirig.glb, kept by the first rebuild or straightening): the joints'
    edits, the evening, the mirroring and the straightened pose undone; the jaw made again from the mouth's marks.
    Yields log lines."""
    d = Path(d)
    keep, auto = d / f"{name}_auto.unirig.glb", d / f"{name}_auto.glb"
    if not keep.exists():
        raise RuntimeError(_t("cr.restore_none"))
    shutil.copy2(keep, auto)
    meta = passport(d, name)
    meta.pop("ends", None)
    (d / f"{name}_rig.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    yield _t("cr.restored", keep.name)
    mouth = mouth_marks(meta)
    if mouth:
        yield from mark_jaw(cfg, d, name, mouth)


def godot_view(cfg, d: Path, name: str) -> str:
    """The creature in Godot (godot/sf3d_creature.gd): a small project work_dir/creature_view/<name> with its clips'
    model (<name>_clips.glb, else the rigged one), imported headless, then opened. Returns the log line."""
    import landmarks
    godot = cfg.get("godot_exe")
    if not godot or not Path(godot).exists():
        raise RuntimeError(_t("lm.godot_not_found_set_godot_exe_in_the"))
    d = Path(d)
    clips = d / f"{name}_clips.glb"
    rigged = next((p for p in (clips, d / f"{name}_rigged.glb", d / f"{name}_landmarks_rigged.glb") if p.exists()), None)
    if rigged is None:
        raise RuntimeError(_t("cr.view_needs_skeleton"))
    proj = Path(cfg["work_dir"]) / "creature_view" / landmarks._slug(name)
    proj.mkdir(parents=True, exist_ok=True)
    dst = proj / "creature.glb"
    if not dst.exists() or dst.stat().st_mtime < rigged.stat().st_mtime or dst.stat().st_size != rigged.stat().st_size:
        shutil.copy2(rigged, dst)
    (proj / "sf3d_creature.gd").write_text(i18n.fill((ROOT / "godot" / "sf3d_creature.gd").read_text(encoding="utf-8")), encoding="utf-8")
    (proj / "project.godot").write_text(f"""config_version=5

[application]

config/name="{_t('cr.godot_title', name)}"
run/main_scene="res://creature.tscn"

[display]

window/size/viewport_width=1280
window/size/viewport_height=800
""", encoding="utf-8")
    (proj / "creature.tscn").write_text("""[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="res://sf3d_creature.gd" id="1"]
[ext_resource type="PackedScene" path="res://creature.glb" id="2"]

[node name="Creature" type="Node3D"]
script = ExtResource("1")
creature = ExtResource("2")
""", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([godot, "--headless", "--path", str(proj), "--import"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600, creationflags=flags)
    if not (proj / ".godot" / "imported").exists():
        raise RuntimeError(_t("lm.godot_did_not_import_the_models") + (r.stdout + r.stderr)[-600:])
    if cfg.get("_no_window"):   # (tests: the project made and imported, opened by them)
        return str(proj)
    gui = Path(godot).with_name(Path(godot).name.replace("_console", ""))   # the window build, without a console
    subprocess.Popen([str(gui if gui.exists() else godot), "--path", str(proj)], cwd=str(proj))
    return _t("cr.godot_open", rigged.name, proj)
