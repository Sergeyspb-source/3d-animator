"""Creatures (four paws, a tail, a muzzle; any skeleton that is not a humanoid's): which models are creatures, their
files and skeleton passport, and the skeleton viewer page (skeleton_view.html) - for any skinned model, a humanoid's too.

A model is a creature when its passport <name>_rig.json says "kind": "creature" (the creature skeleton writes it; a
model added in the «Creatures» section gets it at once, before its skeleton). Its files stay in export/character/<name>/
as a character's do: <name>.glb (the source), <name>_unirig.glb (UniRig's skeleton), <name>_auto.glb (turned; its
bones keep UniRig's names, the passport's "names" rename them - after a markup's rebuild they are named already),
<name>_rigged.glb (named, with the jaw: what the tools take), <name>_jaw_*.png (the jaw's pictures).
"""
import base64
import importlib.util
import json
import math
import os
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
    jaw = [(str(Path(d) / f"{name}_jaw_{k}.png"), v) for k, v in labels.items() if (Path(d) / f"{name}_jaw_{k}.png").exists()]
    return jaw + list(zip(eye_pictures(d, name), (_t("cr.eyes_front"), _t("cr.eyes_gaze"))))   # (and the eyes')


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
            "eyes": meta.get("eyes"), "req_target": REQ_ID, "req_go": REQ_GO}


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
            base = _noeyes(dst) if _noeyes(dst).exists() else dst   # (without the creature's eyes: they go back after)
            if "jaw" in bone_names(base):
                raise RuntimeError(_t("cr.jaw_there", dst.name))
            shutil.copy2(base, auto)
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
    if meta.get("eyes"):   # the model is new: its eyes cut and put in again
        _noeyes(dst).unlink(missing_ok=True)
        yield from set_eyes(cfg, d, name, meta["eyes"], rigged=dst)
    elif (d / f"{name}_clips.glb").exists():   # (the clips on the new jaw; the variants after them)
        yield from reclip(cfg, d, name)
    elif paint_variants(d, name):   # (the colouring's variants on the new model)
        yield _t("cr.paint_refreshed", len(paint_refresh(d, name)))


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
                "horse": ("horse-animations.glb", {"Idle", "Walk", "Trot", "Run", "Eating", "Sleep"}),
                # (more bodies: a dragon's wings, a bird's, a biped's arms, eight legs, none - blender_creature_retarget.py
                # maps them by kind: legs by their place front to back, wings to wings, a serpent's body from the head)
                "dragon": ("dragon-animations.glb", {"Idle", "Walk", "Fly Flap", "Fly Glide"}),
                "bird": ("bird-animations.glb", {"Idle", "Walk", "Flap", "Glide"}),
                "kaiju": ("kaiju-animations.glb", {"Idle", "Walk", "Walk RM", "Swim"}),
                "spider": ("spider-animations.glb", {"Idle", "Walk"}),
                "snake": ("snake-animations.glb", {"Idle", "Side winding", "Coiled", "Dance"}),
                "shark": ("shark-animations.glb", {"Idle", "Swim Horizontal", "Swim Vertical", "Dead Floating"})}
CLIP_DEFAULT = ("fox", "horse")   # (picked at first: the four-legged's; the others by hand, as the creature is)
# a creature's own clips keyed from key poses (creature_keys/<name>.py, creature_keyer.py in the same Blender session):
# the nurgle's leap, paw strike and wall climb read off the user's videos (the game project's); on any creature with four
# legs (leg_FL_.. leg_BR_), hips and jaw, scaled to its size
KEYED = {"nurgle": ROOT / "creature_keys" / "nurgle.py"}


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
    for k, p in KEYED.items():   # (a creature's own clips, keyed from key poses: named as they are)
        try:
            spec = importlib.util.spec_from_file_location(f"creature_keys_{k}", str(p))
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            out[k] = (p, [c["name"] for c in mod.CLIPS])
        except Exception:  # noqa: BLE001
            continue
    return out


def clip_key(source: str, clip: str) -> str:
    if source in KEYED:
        return clip
    return f"{source}_{clip}".lower().replace(" ", "_")


def clips_had(d: Path, name: str) -> dict | None:
    """{source: [its clips]} the creature's <name>_clips.glb has (None: no clips made yet) - the picks to show."""
    made = Path(str(Path(d) / f"{name}_clips.glb") + ".json")
    try:
        had = {c["name"] for c in json.loads(made.read_text(encoding="utf-8"))}
    except (OSError, ValueError, KeyError, TypeError):
        return None
    return {k: [c for c in cs if clip_key(k, c) in had] for k, (_p, cs) in clip_sources().items()}


def reclip(cfg, d: Path, name: str):
    """The clips made again on the model as it is now (its eyes, its jaw), the same ones as before (<name>_clips.glb's
    list): the clips' model is the rigged one of its time - eyes put in later were missing from it, in Godot too. Yields
    log lines; nothing when there are no clips yet."""
    d = Path(d)
    made = Path(str(d / f"{name}_clips.glb") + ".json")
    if not made.exists():
        return
    try:
        had = {c["name"] for c in json.loads(made.read_text(encoding="utf-8"))}
    except (OSError, ValueError, KeyError, TypeError):
        return
    picks = {k: [c for c in cs if clip_key(k, c) in had] for k, (_p, cs) in clip_sources().items()}
    picks = {k: v for k, v in picks.items() if v}
    if picks:
        yield _t("cr.reclip")
        yield from animate(cfg, d, name, picks)


def animate(cfg, d: Path, name: str, picks: dict):
    """The clips picked ({source: [clip names]}) put on the creature (blender_creature_retarget.py) into
    <name>_clips.glb, the model with them, named <source>_<clip>. Yields log lines."""
    d = Path(d)
    rigged = d / f"{name}_rigged.glb"
    if not rigged.exists():
        raise RuntimeError(_t("cr.view_needs_skeleton"))
    src = clip_sources()
    clips = [{"source": str(src[k][0]), "action": c, "name": clip_key(k, c), "loop": c in CLIP_SOURCES[k][1]}
             for k, cs in picks.items() if k in src and k in CLIP_SOURCES for c in cs]
    keyed = [{"poses": str(src[k][0]), "clips": list(cs)} for k, cs in picks.items() if k in src and k in KEYED and cs]
    if not clips and not keyed:
        raise RuntimeError(_t("cr.anim_none_picked"))
    work = Path(cfg["work_dir"]) / "creature_clips"
    work.mkdir(parents=True, exist_ok=True)
    out = d / f"{name}_clips.glb"
    job = work / f"{name}.json"
    job.write_text(json.dumps({"target": str(rigged), "clips": clips, "keyed": keyed, "out": str(out), "mesh": True,
                               "close_deg": (passport(d, name).get("jaw") or {}).get("close_deg")}), encoding="utf-8")
    yield _t("cr.anim_running", len(clips) + sum(len(k["clips"]) for k in keyed))
    _run(cfg, "blender_creature_retarget.py", [job], "RETARGET_OK")
    made = json.loads(Path(str(out) + ".json").read_text(encoding="utf-8"))
    lost = [c for k in keyed for c in k["clips"] if c not in {m["name"] for m in made}]
    if lost:   # (the creature has not the bones the key poses turn: four legs, hips, jaw ...)
        yield _t("cr.anim_keyed_skipped", ", ".join(lost))
    yield _t("cr.anim_done", out.name, len(made), ", ".join(c["name"] for c in made))
    if paint_variants(d, name):   # (the colouring's variants on the new model)
        yield _t("cr.paint_refreshed", len(paint_refresh(d, name)))


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
    if meta.get("eyes"):
        meta["eyes"] = {**meta["eyes"], **{s: [move(p) for p in meta["eyes"][s]] for s in ("L", "R") if meta["eyes"].get(s)}}
    (d / f"{name}_rig.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    if not mouth and meta.get("eyes"):   # (no jaw to make again: the eyes on the straightened model)
        rigged = d / f"{name}_rigged.glb"
        shutil.copy2(auto, rigged)
        _noeyes(rigged).unlink(missing_ok=True)
        yield from set_eyes(cfg, d, name, meta["eyes"], rigged=rigged)
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


# ---------------------------------------------------------------- the eyes
# A creature's painted eyes cut out and eyeballs put in (blender_creature_eyes.py), coloured as asked: the white, the
# iris, the pupil (eye_tex.py; the viewer draws the same live). The model before its eyes is kept beside it
# (<stem>.noeyes.glb): every change of the eyes starts from it, a new jaw or a straightened rest makes the model anew
# and puts them back. The passport keeps them: "eyes": {"L": [4 points], "R": [4 points], "look": {...}, "size": k}.
EYE_LOOK = {"sclera": [0.93, 0.91, 0.87], "iris": [0.85, 0.62, 0.12], "pupil_color": [0.015, 0.012, 0.012],
            "iris_size": 40, "pupil": 0.42, "slit": "round", "veins": 0.2, "fibres": 1.0, "glow": 0.0}


def _noeyes(rigged: Path) -> Path:
    return Path(rigged).with_name(Path(rigged).stem + ".noeyes.glb")


def set_eyes(cfg, d: Path, name: str, eyes: dict, rigged: Path | None = None):
    """The eyes cut and put in from their marks (eyes: L, R - glTF outlines: inner corner, top, outer corner, bottom;
    look, size). Yields log lines; writes the model and the passport."""
    d = Path(d)
    rigged = Path(rigged) if rigged else d / f"{name}_rigged.glb"
    if not rigged.exists():
        raise RuntimeError(_t("cr.view_needs_skeleton"))
    sides = {s: eyes[s] for s in ("L", "R") if eyes.get(s) and len(eyes[s]) == 4}
    if not sides:
        raise RuntimeError(_t("cr.eyes_none"))
    base = _noeyes(rigged)
    if not base.exists():
        shutil.copy2(rigged, base)
    meta = passport(d, name)
    look = {**EYE_LOOK, **(eyes.get("look") or {})}
    jaw = meta.get("jaw") or {}
    work = Path(cfg["work_dir"]) / "creature_rebuild"
    work.mkdir(parents=True, exist_ok=True)
    job = work / f"{name}_eyes.json"
    job.write_text(json.dumps({"src": str(base), "out": str(rigged), "eyes": sides, "look": look,
                               "size": float(eyes.get("size", 1.0)), "forward": float(eyes.get("forward", 0.5)), "head_bone": jaw.get("jaw_parent") or "head",
                               "preview": str(d / f"{name}_eyes.png")}), encoding="utf-8")
    yield _t("cr.eyes_running")
    try:
        rep = json.loads(_run(cfg, "blender_creature_eyes.py", [job], "EYES_OK").split(" ", 1)[1])
    except RuntimeError as e:
        shutil.copy2(base, rigged)   # (a failed cut: the model without eyes, not half made)
        raise RuntimeError(_t("cr.eyes_failed", str(e)[-400:])) from e
    meta["eyes"] = {**sides, "look": look, "size": float(eyes.get("size", 1.0)), "forward": float(eyes.get("forward", 0.5)),
                    "mirror": bool(eyes.get("mirror", True))}
    meta["kind"] = "creature"
    (d / f"{name}_rig.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    yield _t("cr.eyes_done", ", ".join(f"{s} r {v['radius']:.3g} · {v['bone']}" for s, v in rep["eyes"].items()))
    if (d / f"{name}_clips.glb").exists():   # (the clips' model again: with the eyes; the variants after it)
        yield from reclip(cfg, d, name)
    elif paint_variants(d, name):   # (the colouring's variants on the new model)
        yield _t("cr.paint_refreshed", len(paint_refresh(d, name)))


def eyes_off(cfg, d: Path, name: str, rigged: Path | None = None):
    """The creature's own painted eyes back (the model before its eyes), the marks forgotten. Yields log lines."""
    d = Path(d)
    rigged = Path(rigged) if rigged else d / f"{name}_rigged.glb"
    base = _noeyes(rigged)
    meta = passport(d, name)
    if base.exists():
        shutil.copy2(base, rigged)
        base.unlink()
    meta.pop("eyes", None)
    (d / f"{name}_rig.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / f"{name}_eyes_front.png").unlink(missing_ok=True)
    (d / f"{name}_eyes_eye.png").unlink(missing_ok=True)
    yield _t("cr.eyes_off_done")
    if (d / f"{name}_clips.glb").exists():   # (the clips' model again: with the eyes; the variants after it)
        yield from reclip(cfg, d, name)
    elif paint_variants(d, name):   # (the colouring's variants on the new model)
        yield _t("cr.paint_refreshed", len(paint_refresh(d, name)))


def eye_pictures(d: Path, name: str) -> list:
    return [str(p) for p in (Path(d) / f"{name}_eyes_front.png", Path(d) / f"{name}_eyes_eye.png") if p.exists()]


# ---------------------------------------------------------------- colouring: variants of the creature's skin
# The «Colouring» tab's page (creature_paint.html) paints the skin live and bakes each base colour picture of a
# variant itself (the same rule in UV space); the pictures come up through Gradio's upload and are kept in
# <name>_paint/<variant>/; the variant's model <name>_v_<variant>.glb is the creature's (its clips' model, else the
# rigged one) with those pictures in place of its own - swapped in the GLB itself, so the clips stay as they are. The
# base model is never changed. A new model (clips, jaw, eyes) makes every variant's model again.
PAINT_PAGE = ROOT / "creature_paint.html"
PAINT_ID = "sf3d_paint_req"   # the colouring page's hidden textbox and button
PAINT_GO = "sf3d_paint_go"
_TR = dict(zip("абвгдеёжзийклмнопрстуфхцчшщъыьэюя",
               "a b v g d e e zh z i y k l m n o p r s t u f h ts ch sh sch _ y _ e yu ya".split()))


def paint_slug(title: str) -> str:
    import re
    s = "".join(_TR.get(c, c) for c in title.lower())
    return re.sub(r"[^a-z0-9]+", "_", s).strip("_")[:40] or "variant"


def paint_base(d: Path, name: str) -> Path | None:
    """the model a variant is made from: the clips' (the game's), else the rigged one"""
    d = Path(d)
    return next((p for p in (d / f"{name}_clips.glb", d / f"{name}_rigged.glb", d / f"{name}_landmarks_rigged.glb")
                 if p.exists()), None)


def paint_variants(d: Path, name: str) -> dict:
    return passport(d, name).get("paints") or {}


def paint_page(d: Path, name: str, current: str = "") -> str:
    """the colouring page on the creature's rigged model (its pictures as made: variants never change it)"""
    d = Path(d)
    glb = next((p for p in (d / f"{name}_rigged.glb", d / f"{name}_landmarks_rigged.glb") if p.exists()), None)
    if glb is None:
        raise RuntimeError(_t("cr.view_needs_skeleton"))
    page = i18n.fill(PAINT_PAGE.read_text(encoding="utf-8"))
    data = {"title": name, "variants": paint_variants(d, name), "current": current, "req_target": PAINT_ID,
            "req_go": PAINT_GO, "upload": "/upload"}
    return (page.replace("@@DATA@@", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
                .replace("@@GLB@@", base64.b64encode(glb.read_bytes()).decode("ascii")))


def glb_swap_images(src: Path, out: Path, images: dict) -> list:
    """the GLB with some of its pictures replaced ({image or texture name: file}), everything else byte for byte:
    the binary chunk laid out again view by view (4-byte aligned). Returns the names replaced."""
    import struct
    raw = Path(src).read_bytes()
    magic, ver, _total = struct.unpack_from("<III", raw, 0)
    if magic != 0x46546C67:
        raise RuntimeError(f"not a GLB: {src}")
    off, js, bin_ = 12, None, b""
    while off < len(raw):
        ln, kind = struct.unpack_from("<II", raw, off)
        chunk = raw[off + 8: off + 8 + ln]
        if kind == 0x4E4F534A:
            js = json.loads(chunk.decode("utf-8"))
        elif kind == 0x004E4942:
            bin_ = chunk
        off += 8 + ln
    by_name = {}
    for i, im in enumerate(js.get("images", [])):
        if im.get("name"):
            by_name[im["name"]] = i
    for tx in js.get("textures", []):
        if tx.get("name") and tx.get("source") is not None:
            by_name.setdefault(tx["name"], tx["source"])
    new_data = {}
    done = []
    for nm, f in images.items():
        i = by_name.get(nm)
        if i is None or "bufferView" not in js["images"][i]:
            continue
        data = Path(f).read_bytes()
        new_data[js["images"][i]["bufferView"]] = data
        js["images"][i]["mimeType"] = "image/png" if data[:4] == b"\x89PNG" else "image/jpeg"
        done.append(nm)
    out_bin = bytearray()
    for vi, bv in enumerate(js.get("bufferViews", [])):
        data = new_data.get(vi)
        if data is None:
            s = bv.get("byteOffset", 0)
            data = bin_[s: s + bv["byteLength"]]
        while len(out_bin) % 4:
            out_bin.append(0)
        bv["byteOffset"] = len(out_bin)
        bv["byteLength"] = len(data)
        bv["buffer"] = 0
        out_bin += data
    while len(out_bin) % 4:
        out_bin.append(0)
    js["buffers"] = [{"byteLength": len(out_bin)}]
    jb = json.dumps(js, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    jb += b" " * (-len(jb) % 4)
    body = struct.pack("<II", len(jb), 0x4E4F534A) + jb + struct.pack("<II", len(out_bin), 0x004E4942) + bytes(out_bin)
    Path(out).write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + len(body)) + body)
    return done


def _variant_files(d: Path, name: str, slug: str) -> dict:
    v = paint_variants(d, name).get(slug) or {}
    folder = Path(d) / f"{name}_paint" / slug
    return {k: str(folder / f) for k, f in (v.get("images") or {}).items() if (folder / f).exists()}


def paint_refresh(d: Path, name: str) -> list:
    """every variant's model made again from the creature's model now (after its clips, jaw or eyes changed)"""
    base = paint_base(d, name)
    made = []
    if base is None:
        return made
    for slug in paint_variants(d, name):
        glb_swap_images(base, Path(d) / f"{name}_v_{slug}.glb", _variant_files(d, name, slug))
        made.append(slug)
    return made


def upload_root() -> Path:
    """Where the web interface's /upload puts the files its pages send (the colouring page's baked pictures; paint_save
    takes them only from there): SF3D_UPLOAD_DIR, else <temp>/sf3d_uploads."""
    import tempfile
    return Path(os.environ.get("SF3D_UPLOAD_DIR") or Path(tempfile.gettempdir()) / "sf3d_uploads")


def paint_save(cfg, d: Path, name: str, req: dict):
    """A variant kept: its baked pictures (uploaded files) into <name>_paint/<slug>/, its params in the passport,
    its model <name>_v_<slug>.glb. Yields log lines."""
    d = Path(d)
    title = (req.get("title") or "").strip()
    if not title:
        raise RuntimeError(_t("cr.paint_need_name"))
    slug = req.get("variant") or paint_slug(title)
    imgs = req.get("images") or {}
    if not imgs:
        raise RuntimeError(_t("cr.paint_no_images"))
    # (only the interface's own uploads: the page's paths are taken from nowhere else)
    up_root = upload_root().resolve()
    folder = d / f"{name}_paint" / slug
    folder.mkdir(parents=True, exist_ok=True)
    files = {}
    for k, (nm, src) in enumerate(imgs.items()):
        sp = Path(src).resolve()
        if up_root not in sp.parents or not sp.exists():
            raise RuntimeError(_t("cr.paint_bad_upload", src))
        dst = folder / f"{k:02d}{sp.suffix.lower() or '.png'}"
        shutil.copy2(sp, dst)
        files[nm] = dst.name
    meta = passport(d, name)
    paints = meta.get("paints") or {}
    paints[slug] = {"title": title, "params": req.get("params") or {}, "images": files}
    meta["paints"] = paints
    (d / f"{name}_rig.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    base = paint_base(d, name)
    out = d / f"{name}_v_{slug}.glb"
    done = glb_swap_images(base, out, {k: str(folder / f) for k, f in files.items()})
    yield _t("cr.paint_saved", title, out.name, len(done), base.name)
    if len(done) < len(files):
        yield _t("cr.paint_missed", ", ".join(sorted(set(files) - set(done))))


def paint_delete(d: Path, name: str, slug: str):
    d = Path(d)
    meta = passport(d, name)
    v = (meta.get("paints") or {}).pop(slug, None)
    (d / f"{name}_rig.json").write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")
    (d / f"{name}_v_{slug}.glb").unlink(missing_ok=True)
    folder = d / f"{name}_paint" / slug
    if folder.is_dir() and folder.parent == d / f"{name}_paint":
        shutil.rmtree(folder)
    yield _t("cr.paint_deleted", (v or {}).get("title", slug))


# ---------------------------------------------------------------- the model's defects mended (glb_fix.py)
def mend(d: Path, name: str, what: str):
    """Every model of the creature mended in place (its source, skeleton, clips, colouring variants, the copies the
    tools start from): what - "holes" (small holes in the skin closed: Tripo leaves some, seen as dark or light
    squares) or "normals" (the vertex normals made again from the faces). Each file changed is copied once into
    <name>_backup/ first. Yields log lines."""
    import glb_fix
    d = Path(d)
    files = sorted(p for p in d.glob("*.glb") if p.is_file())
    if not files:
        raise RuntimeError(_t("cr.none"))
    bak = d / f"{name}_backup"
    total = 0
    for f in files:
        tmp = f.with_name(f.stem + ".mending.tmp")
        try:
            if what == "holes":
                n, tris = glb_fix.fill_holes(f, tmp)
                line = _t("cr.mend_holes_file", f.name, n, tris) if n else None
            else:
                n = glb_fix.fix_normals(f, tmp, mode="all")
                line = _t("cr.mend_normals_file", f.name, n) if n else None
        except Exception as e:  # noqa: BLE001 - one odd file does not stop the rest
            tmp.unlink(missing_ok=True)
            yield _t("cr.mend_skip", f.name, e)
            continue
        if not tmp.exists():
            continue
        bak.mkdir(exist_ok=True)
        if not (bak / f.name).exists():
            shutil.copy2(f, bak / f.name)
        tmp.replace(f)
        total += 1
        yield line
    yield _t("cr.mend_done", total, bak.name) if total else _t("cr.mend_none")


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
    # the colouring's variants beside it (variant_<slug>.glb), switched in the window
    vs = {s: v for s, v in paint_variants(d, name).items() if (d / f"{name}_v_{s}.glb").exists()}
    for old in proj.glob("variant_*.glb"):
        if old.stem[len("variant_"):] not in vs:
            old.unlink()
    for s in vs:
        src, vd = d / f"{name}_v_{s}.glb", proj / f"variant_{s}.glb"
        if not vd.exists() or vd.stat().st_mtime < src.stat().st_mtime or vd.stat().st_size != src.stat().st_size:
            shutil.copy2(src, vd)
    ext = "".join(f'[ext_resource type="PackedScene" path="res://variant_{s}.glb" id="v{i}"]\n' for i, s in enumerate(vs))
    arr = ", ".join(f'ExtResource("v{i}")' for i in range(len(vs)))
    names = ", ".join(json.dumps(v.get("title") or s, ensure_ascii=False) for s, v in vs.items())
    (proj / "creature.tscn").write_text(f"""[gd_scene load_steps={3 + len(vs)} format=3]

[ext_resource type="Script" path="res://sf3d_creature.gd" id="1"]
[ext_resource type="PackedScene" path="res://creature.glb" id="2"]
{ext}
[node name="Creature" type="Node3D"]
script = ExtResource("1")
creature = ExtResource("2")
variants = [{arr}]
variant_names = PackedStringArray({names})
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
