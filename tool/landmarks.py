"""Hand-placed landmark rigging (Mixamo-like): the user marks chin, groin, shoulders, elbows, wrists, knees and
ankles on the front view in landmark_editor.html; derived joints (spine, neck, clavicles, hips, toes) are
computed there and stay editable. blender_landmark_rig.py builds the armature with standard humanoid names
(Mixamo or Godot, same tables as rigging.py) and skins the model with Blender heat weights.
"""
from __future__ import annotations

import base64
import glob
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
import i18n
from i18n import t as _t

ROOT = Path(__file__).resolve().parent
EDITOR = ROOT / "landmark_editor.html"
TARGET_ID = "sf3d_landmarks_json"   # Gradio textbox the editor writes into

REQUIRED = ["hips", "spine", "spine1", "spine2", "neck", "head", "head_top"] + [
    f"{k}_{s}" for s in "LR" for k in ("shoulder", "arm", "forearm", "hand", "hand_end",
                                       "upleg", "leg", "foot", "toe", "toe_end")]


def bone_names(naming="mixamo"):
    """Editor joint id -> bone name, from the same naming tables as UniRig's rename step."""
    from rigging import NAMINGS
    cfg = NAMINGS[naming]
    p = cfg["prefix"]
    out = {"hips": p + cfg["hips"], "neck": p + cfg["neck"], "head": p + cfg["head"], "jaw": p + "Jaw"}
    for k, jid in enumerate(["spine", "spine1", "spine2"]):
        out[jid] = p + cfg["spine"][k]
    for s, side in (("L", "Left"), ("R", "Right")):
        for jid, role in (("shoulder", "shoulder"), ("arm", "arm"), ("forearm", "forearm"), ("hand", "hand"),
                          ("upleg", "upleg"), ("leg", "leg"), ("foot", "foot"), ("toe", "toe")):
            out[f"{jid}_{s}"] = p + cfg[role].replace("{S}", side)
        out[f"heel_{s}"] = p + f"{side}Heel"   # helper, no weights
        out[f"eye_{s}"] = p + f"{side}Eye"
        for f in ("thumb", "index", "middle", "ring", "pinky"):
            F = f.capitalize()
            if naming == "mixamo":   # LeftHandIndex1..3, plus the Mixamo end bone 4 for reading FBX rigs
                for k in range(1, 5):
                    out[f"{f}{k}_{s}"] = p + f"{side}Hand{F}{k}"
            else:                    # Godot humanoid profile
                parts = ["Metacarpal", "Proximal", "Distal"] if f == "thumb" else ["Proximal", "Intermediate", "Distal"]
                for k, part in enumerate(parts, 1):
                    out[f"{f}{k}_{s}"] = p + f"{side}{F}{part}"
    return out


def source_path(upload, asset, export_dir):
    if upload:
        return Path(upload if isinstance(upload, str) else upload.name)
    if asset:   # "category/name": its source, else (a source loaded once and never kept) its skeleton's model
        cat, nm = asset.split("/", 1)
        d = Path(export_dir) / cat / nm
        return next((d / n for n in (f"{nm}.glb", f"{nm}_landmarks_rigged.glb", f"{nm}_rigged.glb") if (d / n).exists()), d / f"{nm}.glb")
    return None


def clean_glb(src: Path) -> Path:
    """A GLB the editor and Blender can read as a plain mesh. Tripo's own auto-rig ships inverse bind matrices of
    garbage (1e32): three.js and Blender skin the mesh with them and it explodes. The old rig is rebuilt anyway, so
    the skins go (the vertices are stored in the rest pose), and so do stray helper meshes (Tripo leaves a 42-vertex
    unit icosphere at the origin, which would set the model's size). Returns src itself when nothing needs cleaning."""
    import struct
    import tempfile
    if src.suffix.lower() != ".glb":
        return src
    b = src.read_bytes()
    if b[:4] != b"glTF":
        return src
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    counts = {}
    for mi, m in enumerate(j.get("meshes", [])):
        counts[mi] = sum(j["accessors"][p["attributes"]["POSITION"]]["count"] for p in m["primitives"] if "POSITION" in p["attributes"])
    big = max(counts.values(), default=0)
    stray = [nd for nd in j.get("nodes", []) if "mesh" in nd and counts.get(nd["mesh"], 0) < 200 and big > 5000]
    if not j.get("skins") and not stray:
        return src
    for nd in j.get("nodes", []):
        nd.pop("skin", None)
    for nd in stray:
        nd.pop("mesh")
    j.pop("skins", None)
    j.pop("animations", None)
    for m in j.get("meshes", []):
        for p in m["primitives"]:
            for k in [k for k in p["attributes"] if k.startswith(("JOINTS_", "WEIGHTS_"))]:
                p["attributes"].pop(k)
    js = json.dumps(j, separators=(",", ":")).encode("utf-8")
    js += b" " * (-len(js) % 4)
    rest = b[20 + n:]
    out = Path(tempfile.gettempdir()) / "sf3d_clean" / f"{src.stem}_{int(src.stat().st_mtime)}.glb"
    out.parent.mkdir(parents=True, exist_ok=True)
    body = struct.pack("<II", len(js), 0x4E4F534A) + js + rest
    out.write_bytes(b"glTF" + struct.pack("<II", 2, 12 + len(body)) + body)
    return out


WEAR_ID = "sf3d_wear_json"      # textbox the editor's armour mode writes into
WEAR_GO = "sf3d_wear_go"        # hidden button the editor clicks


def _stem(rigged: Path) -> str:
    return re.sub(r"_landmarks_rigged$", "", Path(rigged).stem)


def wear(cfg, text):
    """The editor's armour mode (mode «Броня») asks through a hidden textbox. text: JSON {id, action, rigged, ...}:
    action "wear" (default): put the piece on as placed — {item, glb (base64 of the piece), placements, offset,
    conform, rigidity, deforms, state}; writes <stem>_wear_<item>.glb and saves the fitting. "save": only save the
    fitting (<stem>_wear_<item>.fit.json with the editor state + the piece as <stem>_wear_<item>.src.glb, so it opens
    again for corrections). "wardrobe": build and open the Godot fitting room with every piece put on. "repaint": paint
    the reshaped piece anew (_repaint). "hollow": cut a closed end of the piece open (_hollow).
    The answer goes to a status file next to the character (the editor waits for it): <stem>_wear_<item>.wear.json,
    <stem>_wardrobe.wear.json. Returns the log text."""
    req = json.loads(text)
    rigged = Path(req["rigged"])
    action = req.get("action") or "wear"
    item = re.sub(r"[^\w-]+", "_", req.get("item") or "item").strip("_") or "item"
    status = rigged.parent / f"{_stem(rigged)}_{'wardrobe' if action == 'wardrobe' else 'wear_' + item}.wear.json"
    try:
        res = (wardrobe(cfg, rigged) if action == "wardrobe" else _repaint(cfg, req, rigged, item) if action == "repaint"
               else _hollow(cfg, req, rigged, item) if action == "hollow" else _wear(cfg, req, rigged, item, action == "wear"))
    except Exception as e:  # noqa: BLE001  (the editor must hear back, or it waits for minutes)
        res = {"ok": False, "log": _t("lm.error", e)}
    status.write_text(json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
    return res["log"]


def _save_fit(rigged: Path, item: str, piece: bytes, state) -> dict:
    stem = _stem(rigged)
    src = rigged.parent / f"{stem}_wear_{item}.src.glb"
    fit = rigged.parent / f"{stem}_wear_{item}.fit.json"
    src.write_bytes(piece)
    try:   # a piece made in «Equipment: procedural» and corrected here keeps its parameters (it opens there again)
        made = json.loads(fit.read_text(encoding="utf-8")).get("procedural") if fit.exists() else None
    except (OSError, ValueError):
        made = None
    fit.write_text(json.dumps({"item": item, "src": src.name, "saved": datetime.now().isoformat(timespec="seconds"),
                               **({"procedural": made} if made else {}), "state": state}, ensure_ascii=False, indent=1), encoding="utf-8")
    return _fit_entry(fit)


def _fit_entry(fit: Path) -> dict:
    """{item, fit, src, glb} for the editor's list of saved pieces (glb: the fitted result, None if not put on)."""
    base = fit.name[:-len(".fit.json")]
    glb = fit.with_name(base + ".glb")
    saved = json.loads(fit.read_text(encoding="utf-8"))
    return {"item": saved.get("item") or base, "fit": fit.resolve().as_posix(),
            "src": fit.with_name(base + ".src.glb").resolve().as_posix(), "glb": glb.resolve().as_posix() if glb.exists() else None,
            "under": (saved.get("state") or {}).get("under") or [],   # the pieces it was put on over
            "part": (saved.get("state") or {}).get("part"),
            "procedural": bool(saved.get("procedural"))}   # made in «Equipment: procedural»: opened as made (its own weights)


def saved_fits(rigged: Path) -> list:
    out = []
    for f in sorted(Path(rigged).parent.glob(glob.escape(_stem(rigged)) + "_wear_*.fit.json")):
        try:
            if f.with_name(f.name[:-len(".fit.json")] + ".src.glb").exists():
                out.append(_fit_entry(f))
        except (OSError, ValueError):
            continue
    return out


def _wear(cfg, req, rigged: Path, item: str, put_on: bool) -> dict:
    stem = _stem(rigged)
    piece_bytes = base64.b64decode(req["glb"])   # by the skeleton: the copies as the editor placed them
    entry = _save_fit(rigged, item, base64.b64decode(req["src_glb"]) if req.get("src_glb") else piece_bytes, req.get("state"))
    if not put_on:
        return {"ok": True, "log": _t("lm.saved_wear_fit_json", stem, item), "fit": entry}
    work = Path(cfg["work_dir"]) / "wear" / f"{stem}_{item}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    work.mkdir(parents=True, exist_ok=True)
    piece = work / "piece.glb"
    piece.write_bytes(piece_bytes)
    out = rigged.parent / f"{stem}_wear_{item}.glb"
    keep = bool(req.get("keep_weights"))   # a procedural piece corrected by hand: its own skin, weights and mask stay
    mask_keep = rigged.parent / f"{stem}_wear_{item}.mask.json"
    if keep and mask_keep.exists():   # what it hid as made (ears under a helmet...): kept aside, the new one adds to it
        shutil.copy2(mask_keep, work / "mask_made.json")
    job = {"character": str(rigged), "armour": str(piece if keep else clean_glb(piece)), "out": str(out), "item": item,
           "keep_weights": keep, "mask_keep": str(work / "mask_made.json") if keep else None,
           "placements": req["placements"], "offset": float(req.get("offset", 0.0)), "deforms": req.get("deforms", []),
           "conform": float(req.get("conform", 0.5)), "rigidity": float(req.get("rigidity", 0.8)), "wall": req.get("wall"),
           "rings": req.get("rings", []), "under": _under(rigged, item, req.get("under") or []),
           "report": str(work / "report.json"), "mask": str(work / "mask.json")}
    (work / "job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_wear_fit.py"), "--", str(work / "job.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    line = next((x for x in r.stdout.splitlines() if x.startswith("WEAR_OK")), None)
    if not line:
        return {"ok": False, "fit": entry,
                "log": _t("lm.failed") + next((x for x in r.stdout.splitlines() if x.startswith("WEAR_FAIL")), (r.stdout + r.stderr)[-600:])}
    rep = json.loads(line.split(" ", 1)[1])
    if (work / "mask.json").exists():   # what of the body it hides: SF3DEquip.wear() takes it away while it is on
        shutil.copy2(work / "mask.json", rigged.parent / f"{stem}_wear_{item}.mask.json")
    equip = ROOT / "godot" / "sf3d_equip.gd"   # the folder goes into a Godot project as is: SF3DEquip.wear() puts it on
    if equip.exists():
        (rigged.parent / equip.name).write_bytes(equip.read_bytes())
    parts = []
    for k, v in rep.items():
        if not isinstance(v, dict):
            continue
        near = _t("lm.vertices_left_at_the_skin", v['close_to_skin']) if v.get("close_to_skin") else ""
        if v.get("over_cells"):
            near += _t("lm.over_other_pieces_cells", v["over_cells"])
        parts.append(_t("lm.vertices_bones", k, v['vertices'], near, ', '.join(b.split(':')[-1] for b in v['bones'][:4])))
    return {"ok": True, "glb": out.resolve().as_posix(), "fit": _fit_entry(rigged.parent / f"{stem}_wear_{item}.fit.json"),
            "log": _t("lm.put_on_and_saved", out.name) + "; ".join(parts)}


HY_PY = r"D:\conda\envs\hunyuan\python.exe"     # the same as sf3d_ui.HY_PY / HY_SRC
HY_SRC = r"D:\My projects\SF3D\hunyuan3d-src"


def _under(rigged: Path, item: str, items) -> list:
    """The fitted results of the pieces this one goes over: only this character's, put on, and not the piece itself."""
    stem = _stem(rigged)
    out = []
    for name in items:
        name = re.sub(r"[^\w-]+", "_", str(name)).strip("_")
        glb = rigged.parent / f"{stem}_wear_{name}.glb"
        if name and name != item and glb.exists():
            out.append(str(glb))
    return out


def _reference(cfg, item: str):
    """The front view a piece was generated from: export/equipment/**/refs_mv/<item>/front.png (the 4-view armour)."""
    base = Path(cfg["export_dir"]) / "equipment"
    for name in (item, re.sub(r"^(mv|gen|sc|kp|cm)_", "", item)):
        found = sorted(base.rglob(f"refs_mv/{glob.escape(name)}/front.png")) if base.exists() else []
        if found:
            return found[0]
    return None


def _repaint(cfg, req, rigged: Path, item: str) -> dict:
    """«Перекрасить по форме»: the piece as reshaped in the editor (openings drawn in, wall, points; its own space) is
    painted anew by Hunyuan3D-Paint from its reference picture, so the texture follows the new shape instead of being
    stretched over it, and the sides the picture does not show are made up by the model. The result becomes the
    fitting's source piece (<stem>_wear_<item>.src.glb)."""
    stem = _stem(rigged)
    work = Path(cfg["work_dir"]) / "wear" / f"{stem}_{item}_repaint_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "shape.glb").write_bytes(base64.b64decode(req["glb"]))
    if req.get("image"):
        ref = work / "reference.png"
        ref.write_bytes(base64.b64decode(req["image"].split(",", 1)[-1]))
    else:
        ref = _reference(cfg, item)
    if ref is None:
        return {"ok": False, "log": _t("lm.no_picture_of_the_piece_choose_it_in")}
    env = dict(__import__("os").environ, HF_HOME=cfg.get("hf_home") or r"D:\conda\hf", HF_HUB_OFFLINE="1",
               HY3DGEN_MODELS=r"D:\conda\hy3dgen", TMP=r"D:\conda\tmp", TEMP=r"D:\conda\tmp", PYTHONIOENCODING="utf-8")
    out = work / "textured.glb"
    for _ in range(2):   # a native crash while the paint models load now and then goes away on a retry
        r = subprocess.run([HY_PY, str(ROOT / "hy_texture_mv.py"), str(work / "shape.glb"), str(ref), str(out), "--tex", "2048"],
                           cwd=HY_SRC, env=env, capture_output=True, text=True, encoding="utf-8", errors="replace",
                           timeout=1800, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (work / "paint.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        if out.exists():
            break
    if not out.exists():
        return {"ok": False, "log": _t("lm.hunyuan3d_paint_did_not_repaint_the") + (r.stdout + r.stderr)[-400:]}
    from glbfix import set_metallic
    set_metallic(out, 0.3, 0.8)   # the painter leaves no metallic factor: a viewer would show the piece as a dark mirror
    src = rigged.parent / f"{stem}_wear_{item}.src.glb"
    src.write_bytes(out.read_bytes())
    return {"ok": True, "src": src.resolve().as_posix(),
            "log": _t("lm.repainted_for_the_new_shape_the", ref.name)}


def _hollow(cfg, req, rigged: Path, item: str) -> dict:
    """«Вскрыть»: a generated piece closed at an end (Hunyuan3D sometimes makes a cuisse like a pot, SF3D caps a
    bracer at both ends) is cut open there by blender_armour_hollow.py, texture and all. req: {glb (base64 of the
    piece as loaded), open: "top" (one end: the one axis points to) | "both", axis: [x, y, z] in the piece's space}.
    The wall is left as it is when the piece has one, else one is made inwards. The result becomes the fitting's source
    piece (<stem>_wear_<item>.src.glb)."""
    stem = _stem(rigged)
    work = Path(cfg["work_dir"]) / "wear" / f"{stem}_{item}_open_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "piece.glb").write_bytes(base64.b64decode(req["glb"]))
    out = work / "open.glb"
    args = [f"open={req.get('open') or 'both'}", "wall=auto"]
    if req.get("axis"):
        args.append("axis=" + ",".join(f"{float(x):.6f}" for x in req["axis"]))
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_armour_hollow.py"), "--",
                        str(work / "piece.glb"), str(out), *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (work / "blender.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    line = next((x for x in r.stdout.splitlines() if x.startswith("HOLLOW_OK")), None)
    if not line or not out.exists():
        return {"ok": False, "log": _t("lm.could_not_open_it") + (r.stdout + r.stderr)[-400:]}
    rep = json.loads(line.split(" ", 1)[1])
    src = rigged.parent / f"{stem}_wear_{item}.src.glb"
    src.write_bytes(out.read_bytes())
    wall = _t("lm.its_own_wall_kept") if not rep["wall"] else _t("lm.a_wall_added_inwards")
    return {"ok": True, "src": src.resolve().as_posix(),
            "log": _t("lm.opened_faces_removed_the_piece_is", rep['caps_removed'], wall)}


def _slug(text: str) -> str:   # the same as sf3d_tool.slug: how the animation tabs name their outputs
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "asset"


def _animated_model(cfg, rigged: Path, work: Path) -> Path:
    """The character with animations for the fitting room: the procedural clips (tab «Анимации») or the retargeted
    Mixamo clips if they were made for this model, else the procedural clips are made now (about 10 s)."""
    import hanim as HA
    export = Path(cfg["export_dir"]) / "character"
    names = {_slug(n) for n in (rigged.stem.replace("_rigged", ""), _stem(rigged))}
    found = [p for n in names for p in (export / n / f"{n}_anim.glb", export / n / f"{n}_fbx.glb") if p.exists()]
    if found:
        return max(found, key=lambda p: p.stat().st_mtime)
    out = work.parent / f"{work.name}_anim.glb"   # outside the Godot project: only its copy is imported
    if not out.exists() or out.stat().st_mtime < rigged.stat().st_mtime:
        HA.animate(cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe", rigged, out,
                   ["idle_loop", "walk_loop", "run_loop", "attack_slash", "attack_overhead", "cast", "block_loop", "hit"])
    return out


def wardrobe(cfg, rigged: Path) -> dict:
    """A small Godot project (work_dir/wardrobe/<stem>) with the character, every fitted piece put on through
    SF3DEquip (godot/sf3d_equip.gd) and godot/sf3d_wardrobe.gd: clips to play, pieces on/off, an orbiting camera.
    Godot imports it headless, then opens it."""
    import shutil
    godot = cfg.get("godot_exe")
    if not godot or not Path(godot).exists():
        raise RuntimeError(_t("lm.godot_not_found_set_godot_exe_in_the"))
    stem = _stem(rigged)
    pieces = [p for p in sorted(rigged.parent.glob(glob.escape(stem) + "_wear_*.glb")) if re.fullmatch(re.escape(stem) + r"_wear_[\w-]+\.glb", p.name)]
    if not pieces:
        raise RuntimeError(_t("lm.no_piece_is_put_on_yet_fit_a_piece"))
    proj = Path(cfg["work_dir"]) / "wardrobe" / _slug(stem)
    proj.mkdir(parents=True, exist_ok=True)
    model = _animated_model(cfg, rigged, proj)
    files = {"character.glb": model, **{f"wear_{p.name[len(stem) + 6:]}": p for p in pieces}}
    for p in pieces:   # what of the body each one hides: SF3DEquip.wear() reads it beside the piece
        if p.with_suffix(".mask.json").exists():
            files[f"wear_{p.name[len(stem) + 6:-4]}.mask.json"] = p.with_suffix(".mask.json")
    for old in [*proj.glob("wear_*.glb"), *proj.glob("wear_*.mask.json")]:   # a piece taken off since the last time
        if old.name not in files:
            old.unlink()
            Path(str(old) + ".import").unlink(missing_ok=True)
    for name, srcp in files.items():
        dst = proj / name
        if srcp.resolve() != dst.resolve() and (not dst.exists() or dst.stat().st_mtime < srcp.stat().st_mtime or dst.stat().st_size != srcp.stat().st_size):
            shutil.copy2(srcp, dst)
    for gd in ("sf3d_equip.gd", "sf3d_wardrobe.gd"):   # the texts in the interface language
        (proj / gd).write_text(i18n.fill((ROOT / "godot" / gd).read_text(encoding="utf-8")), encoding="utf-8")
    (proj / "project.godot").write_text(f"""config_version=5

[application]

config/name="{_t('lm.fitting_room_name', stem)}"
run/main_scene="res://wardrobe.tscn"

[display]

window/size/viewport_width=1280
window/size/viewport_height=800
""", encoding="utf-8")
    names = [n for n in files if n.startswith("wear_") and n.endswith(".glb")]
    ext = "\n".join(f'[ext_resource type="PackedScene" path="res://{n}" id="{i + 3}"]' for i, n in enumerate(names))
    (proj / "wardrobe.tscn").write_text(f"""[gd_scene load_steps={len(names) + 3} format=3]

[ext_resource type="Script" path="res://sf3d_wardrobe.gd" id="1"]
[ext_resource type="PackedScene" path="res://character.glb" id="2"]
{ext}

[node name="Wardrobe" type="Node3D"]
script = ExtResource("1")
character = ExtResource("2")
pieces = Array[PackedScene]([{", ".join(f'ExtResource("{i + 3}")' for i in range(len(names)))}])
""", encoding="utf-8")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    r = subprocess.run([godot, "--headless", "--path", str(proj), "--import"], capture_output=True, text=True,
                       encoding="utf-8", errors="replace", timeout=600, creationflags=flags)
    if not (proj / ".godot" / "imported").exists():
        raise RuntimeError(_t("lm.godot_did_not_import_the_models") + (r.stdout + r.stderr)[-600:])
    gui = Path(godot).with_name(Path(godot).name.replace("_console", ""))   # the window build, without a console
    subprocess.Popen([str(gui if gui.exists() else godot), "--path", str(proj)], cwd=str(proj))
    return {"ok": True, "log": _t("lm.the_fitting_room_is_open_in_godot", len(names), model.name, proj)}


def godot_scene(glb: Path) -> Path | None:
    """<stem>.tscn next to the rigged GLB: the model instanced under a Node3D with sf3d_face_rig.gd (blinking on a
    timer, say(line) for the lip-sync clips saved in the same folder). Paths are relative, so the folder can be
    copied anywhere into a Godot project. Rewritten on every build (settings go on an instance of it)."""
    script = ROOT / "godot" / "sf3d_face_rig.gd"
    if not script.exists():
        return None
    stem = re.sub(r"_landmarks_rigged$", "", glb.stem)
    (glb.parent / script.name).write_bytes(script.read_bytes())
    node = re.sub(r"\W+", "_", stem).strip("_") or "Character"
    out = glb.parent / f"{stem}.tscn"
    out.write_text(f"""[gd_scene load_steps=3 format=3]

[ext_resource type="Script" path="{script.name}" id="1"]
[ext_resource type="PackedScene" path="{glb.name}" id="2"]

[node name="{node}" type="Node3D"]
script = ExtResource("1")

[node name="Model" parent="." instance=ExtResource("2")]
""", encoding="utf-8")
    return out


def output_paths(src: Path, export_dir) -> tuple[Path, Path]:
    """(<name>_landmarks_rigged.glb, <name>_landmarks.json): next to an exported model, else export/character/<name>/."""
    export_dir = Path(export_dir).resolve()
    stem = re.sub(r"_(landmarks_)?rigged$", "", src.stem)
    folder = src.parent if export_dir in src.resolve().parents else export_dir / "character" / stem
    return folder / f"{stem}_landmarks_rigged.glb", folder / f"{stem}_landmarks.json"


def parse(text):
    """Validate the editor JSON; returns the dict or raises ValueError with a Russian message."""
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError:
        raise ValueError(_t("lm.the_markup_is_empty_or_damaged_open"))
    joints = data.get("joints") or {}
    missing = [j for j in REQUIRED if j not in joints]
    if missing:
        raise ValueError(_t("lm.the_markup_has_no_joints") + ", ".join(missing))
    for j in REQUIRED:
        v = joints[j]
        if not (isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v)):
            raise ValueError(_t("lm.bad_coordinates_of_joint", j))
    return data


def editor_page(src: Path, state: dict | None, rigged: Path | None = None, mode: str | None = None, say: str | None = None,
                wear_ids: tuple[str, str] = (WEAR_ID, WEAR_GO)):
    """rigged: built GLB for the pose mode (fetched by the page through Gradio's /file= route, so it must lie in
    an allowed path such as export_dir); mode='pose' opens the page straight in the pose mode, mode='say' only
    looks: the face close with the lip-sync clip say (its name) chosen and played, mode='wear' opens it straight in the
    armour mode («Броня»). wear_ids: the hidden textbox and button its armour mode sends through (each tab its own)."""
    page = i18n.fill(EDITOR.read_text(encoding="utf-8"))
    data = {"state": state, "target": TARGET_ID, "wear_target": wear_ids[0], "wear_go": wear_ids[1], "source": str(src), "mode": mode, "say": say,
            "rigged": Path(rigged).resolve().as_posix() if rigged and Path(rigged).exists() else None,
            "rigged_v": int(Path(rigged).stat().st_mtime) if rigged and Path(rigged).exists() else 0,
            "names": {"mixamo": bone_names("mixamo"), "godot": bone_names("godot")},
            "clips": face_clips(rigged) if rigged and Path(rigged).exists() else [],
            "emotions": emotion_presets() if rigged and Path(rigged).exists() else [],
            "fits": saved_fits(Path(rigged)) if rigged and Path(rigged).exists() else []}
    # </script> inside JSON would end the tag early
    return (page.replace("@@DATA@@", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
                .replace("@@GLB@@", base64.b64encode((src if mode == "view" else clean_glb(src)).read_bytes()).decode("ascii")))


def viewable(src: Path, cfg) -> tuple[Path, dict]:
    """Copy a rigged GLB, or convert a rigged FBX with Blender, into work_dir/rig_view so the browser viewer can
    fetch it through Gradio's /file= route (work_dir is an allowed path). Returns (glb, summary)."""
    out_dir = Path(cfg["work_dir"]) / "rig_view"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (re.sub(r"[^\w.-]+", "_", src.stem) + "_" + datetime.now().strftime("%H%M%S") + ".glb")
    if src.suffix.lower() == ".glb":
        dst.write_bytes(src.read_bytes())
        return dst, {}
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_fbx_to_glb.py"), "--", str(src), str(dst)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    line = next((x for x in r.stdout.splitlines() if x.startswith("FBX2GLB_OK")), None)
    if line is None:
        raise RuntimeError(_t("lm.blender_could_not_read_the_fbx") + (r.stdout + r.stderr)[-1500:])
    info = json.loads(line.split(" ", 1)[1])
    if not info["meshes"]:
        raise RuntimeError(_t("lm.the_fbx_holds_only_a_skeleton_and"))
    return dst, info


EMOTION_RU = {"calm": _t("lm.calm"), "dry": _t("lm.dry"), "smirk": _t("lm.smirk"), "firm": _t("lm.firm"), "excited": _t("lm.excited"),
              "awe": _t("lm.awe"), "mesmerized": _t("lm.mesmerized"), "nervous": _t("lm.nervous"), "nervous_laugh": _t("lm.nervous_laugh"),
              "puzzled": _t("lm.puzzled"), "hushed": _t("lm.whispering"), "fear": _t("lm.fear"), "fear_freeze": _t("lm.frozen_with_fear"),
              "terror": _t("lm.terror"), "shout": _t("lm.shout"), "alarm": _t("lm.alarm"), "pain": _t("lm.pain"), "sobbing": _t("lm.sobbing"),
              "hysterical": _t("lm.hysterics"), "breathless": _t("lm.out_of_breath"), "strain": _t("lm.strain"), "weak": _t("lm.weakness"),
              "stunned": _t("lm.stunned")}


def emotion_presets():
    """[{name, label, keys: {ARKit control: value}}] from the vendored lipsync.py, the same offsets the game's lip
    sync adds per emotion (paired names already split into Left/Right); [] when the script cannot be read."""
    import importlib.util
    try:
        spec = importlib.util.spec_from_file_location("sf3d_lipsync_presets", ROOT / "vendor" / "lipsync" / "lipsync.py")
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return [{"name": k, "label": EMOTION_RU.get(k, k), "keys": mod.expand(v.get("offsets", {}))}
                for k, v in mod.EMOTION_PRESETS.items()]
    except Exception:
        return []


def face_clips(rigged: Path):
    """Lip-sync clips next to a built model: <stem>.face.json with its audio <stem>.(mp3|wav|ogg)."""
    out = []
    for f in sorted(Path(rigged).parent.glob("*.face.json")):
        stem = f.name[:-len(".face.json")]
        audio = next((f.with_name(stem + e) for e in (".mp3", ".wav", ".ogg") if f.with_name(stem + e).exists()), None)
        if audio:
            out.append({"name": stem, "clip": f.resolve().as_posix(), "audio": audio.resolve().as_posix()})
    return out


def initial_state(src: Path, export_dir, textbox: str):
    """Editor start state: unsaved edits for the same model, else the saved landmarks next to the export."""
    try:
        data = json.loads(textbox or "")
        if data.get("source") == str(src) and data.get("joints"):
            return data
    except json.JSONDecodeError:
        pass
    saved = output_paths(src, export_dir)[1]
    if saved.exists():
        try:
            return json.loads(saved.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def _dist(a, b):
    return sum((x - y) ** 2 for x, y in zip(a, b)) ** 0.5 if a and b else None


def face_kit(cfg, kit, work):
    """(folder, parts.json) of a face-parts set (export/face_parts/<kit>); a default set is generated when there is none."""
    if kit and (Path(cfg["export_dir"]) / "face_parts" / kit / "eyes.glb").exists():
        d = Path(cfg["export_dir"]) / "face_parts" / kit
    else:
        d = work / "face_parts_default"
        if not (d / "eyes.glb").exists():
            face_kit_eyes(cfg, "", work)
    info = json.loads((d / "parts.json").read_text(encoding="utf-8")) if (d / "parts.json").exists() else {}
    return d, info


def face_kit_eyes(cfg, kit, work):
    """eyes.glb of a face-parts set (export/face_parts/<kit>); a default set is generated when there is none."""
    if kit:
        f = Path(cfg["export_dir"]) / "face_parts" / kit / "eyes.glb"
        if f.exists():
            return f, json.loads((f.parent / "parts.json").read_text(encoding="utf-8")).get("eye_radius", 0.012)
    out = work / "face_parts_default"
    (work / "face_parts_job.json").write_text(json.dumps({"out_dir": str(out), "seed": 1}), encoding="utf-8")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_face_parts.py"), "--",
                    str(work / "face_parts_job.json")], capture_output=True, timeout=600,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return out / "eyes.glb", 0.012


def build(src: Path, landmarks: dict, naming, cfg, weld=True, mouth=True, eyes=True, kit="", face_topo=False, smooth=1,
          eye_colour=True):
    """Generator of log lines; the last item is a dict with the result paths."""
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    final, saved = output_paths(src, cfg["export_dir"])
    work = Path(cfg["work_dir"]) / "landmark_rig" / (src.stem + "_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    work.mkdir(parents=True, exist_ok=True)
    job = {"source": str(clean_glb(src)), "out_dir": str(work), "landmarks": landmarks, "names": bone_names(naming)}
    (work / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    yield _t("lm.blender_building_the_skeleton_and")
    with (work / "blender.log").open("w", encoding="utf-8") as log:
        r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_landmark_rig.py"), "--",
                            str(work / "job.json")], stdout=log, stderr=subprocess.STDOUT, timeout=1200,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = (work / "blender.log").read_text(encoding="utf-8", errors="replace")
    line = next((x for x in text.splitlines() if x.startswith("LANDMARK_RIG_OK")), None)
    if r.returncode != 0 or line is None or not (work / "model.glb").exists():
        raise RuntimeError(_t("lm.blender_did_not_build_the_skeleton") + text[-2500:])
    report = json.loads(line.split(" ", 1)[1])
    fb = report["fallback_vertices"]
    extra = []
    if report.get("heel_bones"):
        extra.append(_t("lm.heel_bones_without_weights_for_foot", report['heel_bones']))
    if report.get("prebend"):
        extra.append(_t("lm.nearly_straight_elbows_knees_are") + ", ".join(report["prebend"]))
    yield (_t("lm.skeleton_bones_vertices", report['bones'] + report.get('heel_bones', 0), report['vertices'])
           + ("; ".join(extra) + ". " if extra else "")
           + (_t("lm.blender_s_automatic_weights_failed", fb)
              if fb else _t("lm.blender_s_automatic_weights_worked")))
    model = work / "model.glb"
    if weld:
        from rigging import weld_seams
        yield _t("lm.stitching_the_seams_between_the")
        st = weld_seams(model, work / "model_seams.glb", blender, eps=0.0005 * max(report.get("height", 1.0), 1e-6))
        if st:
            model = work / "model_seams.glb"
            yield _t("lm.seams_found_their_weights_evened_out", st['clusters'])
        else:
            yield _t("lm.no_seams_between_parts")
    face = landmarks.get("face") or {}
    images_extra = []
    mouth = "plate" if mouth is True else (mouth or "none")
    topo_done = False
    has_mouth = all(face.get(k) for k in ("mouth_c", "mouth_corner_L", "mouth_corner_R"))
    if face_topo and mouth == "cut" and has_mouth and not (face.get("eye_L") and face.get("eye_R")):
        yield _t("lm.face_retopology_skipped_the_markup")
    if face_topo and mouth != "cut":
        yield _t("lm.face_retopology_works_only_with_the")
    if mouth == "cut" and has_mouth:
        yield _t("lm.cutting_the_mouth_along_the_lip_line")
        names = bone_names(naming)
        kd, kinfo = face_kit(cfg, kit, work)
        cj = {"source": str(model), "out": str(work / "model_cut.glb"), "mouth_c": face["mouth_c"],
              "corner_L": face["mouth_corner_L"], "corner_R": face["mouth_corner_R"],
              "mid_L": face.get("mouth_mid_L"), "mid_R": face.get("mouth_mid_R"),
              "lip_top": face.get("lip_top"), "lip_bot": face.get("lip_bot"), "limit_top": face.get("mouth_limit_top"),
              "open_top": face.get("mouth_open_top"), "open_bot": face.get("mouth_open_bot"),
              "face_topo": bool(face_topo and face.get("eye_L") and face.get("eye_R")), "face_top": face.get("face_top"),
              "face_smooth": 1 if int(smooth) > 0 else 0, "face_relax": [0, 8, 16, 30][max(0, min(3, int(smooth)))],
              "eyes_open": bool(eyes and face.get("eye_in_L") and face.get("eye_bot_L")),
              "eye_L": face.get("eye_L"), "eye_R": face.get("eye_R"), "chin": landmarks.get("marks", {}).get("chin"),
              "eye_rim_L": [face.get(k + "_L") for k in ("eye_in", "eye_top", "eye_out", "eye_bot")] if face.get("eye_in_L") else None,
              "eye_rim_R": [face.get(k + "_R") for k in ("eye_in", "eye_top", "eye_out", "eye_bot")] if face.get("eye_in_R") else None,
              "hinge": landmarks["joints"].get("jaw"), "head_bone": names["head"],
              "jaw_bone": names["jaw"] if "jaw" in landmarks["joints"] else "",
              "teeth_glb": str(kd / "teeth.glb"), "tongue_glb": str(kd / "tongue.glb"),
              "kit": {"arch_width": kinfo.get("arch_width", 0.05)}, "report": str(work / "cut_report.json"),
              "preview": str(work / "mouth_cut.png")}
        (work / "cut_job.json").write_text(json.dumps(cj, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_mouth_cut.py"), "--",
                            str(work / "cut_job.json")], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = next((x for x in r.stdout.splitlines() if x.startswith("CUT_OK")), None)
        if line:
            model = work / "model_cut.glb"
            topo_done = bool(cj["face_topo"])
            cr = json.loads(line.split(" ", 1)[1])
            images_extra += cr.get("previews", [])
            yield (_t("lm.mouth_cut_lips_turned_in_a_cavity", ', '.join(cr.get('inserted', []))))
        else:
            fail = next((x for x in r.stdout.splitlines() if x.startswith("CUT_FAIL")), (r.stdout + r.stderr)[-600:])
            yield _t("lm.the_mouth_cut_failed_the_model_is") + fail
    if mouth == "plate" and has_mouth:
        yield _t("lm.adding_the_speech_mouth_a_plate_with")
        names = bone_names(naming)
        mj = {"source": str(model), "out": str(work / "model_mouth.glb"), "mouth_c": face["mouth_c"],
              "corner_L": face["mouth_corner_L"], "corner_R": face["mouth_corner_R"], "head_bone": names["head"],
              "mid_L": face.get("mouth_mid_L"), "mid_R": face.get("mouth_mid_R"),
              "jaw_bone": names["jaw"] if "jaw" in landmarks["joints"] else "", "report": str(work / "mouth_report.json"),
              "preview": str(work / "mouth.png")}
        (work / "mouth_job.json").write_text(json.dumps(mj, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_mouth_plate.py"), "--",
                            str(work / "mouth_job.json")], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = next((x for x in r.stdout.splitlines() if x.startswith("MOUTH_OK")), None)
        if line:
            model = work / "model_mouth.glb"
            mr = json.loads(line.split(" ", 1)[1])
            images_extra = mr.get("previews", [])
            yield _t("lm.speech_mouth_ready_shape_keys", len(mr['keys']), ', '.join(mr['keys']))
        else:
            fail = next((x for x in r.stdout.splitlines() if x.startswith("MOUTH_FAIL")), (r.stdout + r.stderr)[-600:])
            yield _t("lm.the_speech_mouth_failed_the_model_is") + fail
    rim = {s: [face.get(f"{k}_{s}") for k in ("eye_in", "eye_top", "eye_out", "eye_bot")] for s in "LR"}
    rim = {s: pts for s, pts in rim.items() if all(pts)}
    if eyes and not rim and face:
        yield (_t("lm.eyeballs_not_inserted_the_face"))
    if eyes and rim:
        yield _t("lm.cutting_out_the_painted_eyes_and")
        names = bone_names(naming)
        eyes_glb, kit_r = face_kit_eyes(cfg, kit, work)
        ej = {"source": str(model), "out": str(work / "model_eyes.glb"), "eyes_glb": str(eyes_glb), "kit_r": kit_r,
              "open_rim": topo_done,   # the face retopology already cut the eye openings
              # the iris colour is read from the painted eyes of the rigged model, before any cut
              "iris_from": str(work / "model.glb") if eye_colour else "",
              "head_bone": names["head"], "sym": bool(landmarks.get("sym", True)), "report": str(work / "eyes_report.json"),
              "preview": str(work / "eyes.png"),
              "sides": {s: {"outline": pts, "bone": names[f"eye_{s}"] if f"eye_{s}" in landmarks["joints"] else "",
                            # the eye joint is the ball centre, its end joint the cornea
                            "ball": landmarks["joints"].get(f"eye_{s}"),
                            "ball_r": _dist(landmarks["joints"].get(f"eye_{s}"), landmarks["joints"].get(f"eye_end_{s}"))}
                        for s, pts in rim.items()}}
        (work / "eyes_job.json").write_text(json.dumps(ej, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_eye_insert.py"), "--",
                            str(work / "eyes_job.json")], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = next((x for x in r.stdout.splitlines() if x.startswith("EYES_OK")), None)
        if line:
            model = work / "model_eyes.glb"
            er = json.loads(line.split(" ", 1)[1])
            images_extra += er.get("previews", [])
            yield _t("lm.eyeballs") + ", ".join(_t("lm.radius", s, v['radius']) for s, v in er["eyes"].items()) + "."
        else:
            fail = next((x for x in r.stdout.splitlines() if x.startswith("EYES_FAIL")), (r.stdout + r.stderr)[-600:])
            yield _t("lm.eyeballs_failed_the_model_is_without") + fail
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(model.read_bytes())
    scene = godot_scene(final)
    saved.write_text(json.dumps({**landmarks, "source": str(src), "naming": naming}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    yield (_t("lm.done_markup_saved_it_opens_in_the", final, saved.name)
           + (_t("lm.scene_for_godot_the_model_blinking", scene.name)
              if scene else ""))
    yield {"glb": str(final), "landmarks": str(saved), "work": str(work),
           "images": [str(work / n) for n in ("rest.png", "pose_front.png", "pose_side.png", "hand_fist.png", "face_jaw.png")
                      if (work / n).exists()] + [p for p in images_extra if Path(p).exists()]}
