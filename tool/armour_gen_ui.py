"""Gradio panel «Equipment: procedural»: a piece of armour made for a rigged character out of its own skin. The editor
page (armour_gen_editor.html) builds the piece and its weights live over the character from the parameters, so the
result is seen (and posed) before it is made; «Generate» sends that geometry here and Blender (blender_armour_gen.py)
bakes its materials and exports it. The result lies next to the character like a piece put on in the «Armour» mode
(<stem>_wear_<item>.glb with its fit.json), so the Godot fitting room and the editor's other pieces see it."""
import base64
import html as _html
import json
import re
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

import gradio as gr
import i18n
from i18n import t as _t

import landmarks as LM

ROOT = Path(__file__).resolve().parent
EDITOR = ROOT / "armour_gen_editor.html"
TARGET_ID = "sf3d_ag_json"   # the textbox the editor writes its requests into
GO_ID = "sf3d_ag_go"         # the hidden button it clicks

# piece -> (first joint, next joint, the joint whose bone it follows, bone name words of skin that is not this limb's,
#           the editor's body part (for its list of pieces), the bones it may follow (limb: its own, its children and
#           parent; torso: the body's; hips: and the thighs; legs: and the legs), the range of «from» and «to» (% along the
#           part: a limb from its first joint to the next; the torso from the hips to the neck, below the hips negative;
#           trousers: the waist on the torso, the length on the leg), the defaults the editor switches to)
PIECES = {"bracer": ("forearm", "hand", "forearm", ("Spine", "Hips", "Chest", "UpLeg", "UpperLeg"), "forearm", "limb", (0, 60, 40, 100),
                     dict(t0=15, t1=85, sector=360, plates=3, straps=2, rigidity=.8)),
          "rerebrace": ("arm", "forearm", "arm", ("Spine", "Hips", "Chest", "Neck", "Shoulder"), "arm", "limb", (0, 60, 40, 100),
                        dict(t0=30, t1=90, sector=360, plates=2, straps=2, rigidity=.8)),
          "greave": ("leg", "foot", "leg", ("Arm", "Hand"), "leg", "limb", (0, 60, 40, 100),
                     dict(t0=10, t1=85, sector=240, plates=2, straps=2, rigidity=.8)),
          "cuisse": ("upleg", "leg", "upleg", ("Arm", "Hand"), "upleg", "limb", (0, 60, 40, 100),
                     dict(t0=25, t1=85, sector=220, plates=3, straps=2, rigidity=.8)),
          "cuirass": ("hips", "neck", "spine1", ("Arm", "Hand"), "torso", "torso", (-10, 60, 40, 100),
                      dict(t0=6, t1=95, sector=360, plates=2, straps=1, rigidity=.5, anatomy=0, waist=.6)),
          "tassets": ("hips", "neck", "hips", ("Arm", "Hand"), "torso", "hips", (-80, 0, -10, 30),
                      dict(t0=-45, t1=10, sector=360, plates=4, straps=1, rigidity=.4, gap=16, splits=4, flare=.3)),
          "trousers": ("upleg", "foot", "upleg", ("Arm", "Hand"), "upleg", "legs", (-10, 30, 30, 100),
                       dict(t0=8, t1=92, straps=1, rigidity=.1, gap=3, thickness=5, relief=.6, surface="plain", material="cloth",
                            loose=.3, folds=.3, cuffs=False, buckle=True))}
# «from» / «to» labels: a limb's along it, a torso piece's bottom and top, trousers' waist and leg length
T_LABELS = {"limb": ("ag.from", "ag.to", "ag.from_info"), "torso": ("ag.bottom", "ag.top", "ag.bottom_info"),
            "hips": ("ag.bottom", "ag.top", "ag.tassets_info"), "legs": ("ag.waist", "ag.leg_length", "ag.waist_info")}
# (linear colour, roughness, metallic): metallic kept moderate, a game scene without reflections shows a full metal black
PRESETS = {"iron": ((.34, .34, .35), .55, .55), "steel": ((.56, .58, .61), .35, .65),
           "bronze": ((.55, .36, .17), .42, .6), "leather": ((.30, .17, .09), .72, 0.0), "cloth": ((.25, .27, .3), .9, 0.0)}
SURFACES = ("plates", "scales", "lamellar", "mail", "quilt", "plain")


def characters(cfg):
    """Every character with a landmark skeleton under the export folder: (its name, the rigged GLB)."""
    return [(LM._stem(p), p.resolve().as_posix()) for p in sorted(Path(cfg["export_dir"]).rglob("*_landmarks_rigged.glb"))]


def saved(rigged: Path) -> list:
    """The character's pieces made here before: [{item, piece, sides, params}] (the editor opens them again)."""
    out = []
    for f in sorted(rigged.parent.glob(f"{LM._stem(rigged)}_wear_*.fit.json")):
        try:
            pr = json.loads(f.read_text(encoding="utf-8")).get("procedural")
        except (OSError, ValueError):
            continue
        if isinstance(pr, dict) and pr.get("piece") in PIECES and isinstance(pr.get("params"), dict):
            out.append({"item": f.name[len(LM._stem(rigged)) + 6:-len(".fit.json")], "piece": pr["piece"],
                        "sides": pr.get("sides") or [], "params": pr["params"]})
    return out


def editor_page(rigged: Path) -> str:
    page = i18n.fill(EDITOR.read_text(encoding="utf-8"))
    data = {"rigged": rigged.resolve().as_posix(), "rigged_v": int(rigged.stat().st_mtime), "stem": LM._stem(rigged),
            "target": TARGET_ID, "go": GO_ID, "names": {n: LM.bone_names(n) for n in ("mixamo", "godot")},
            "pieces": {k: {"joints": v[:3], "foreign": v[3], "part": v[4], "family": v[5], "range": v[6], "defaults": v[7],
                           "label": _t(f"ag.piece_{k}"), "tlabels": [_t(x) for x in T_LABELS[v[5]][:2]], "tinfo": _t(T_LABELS[v[5]][2])}
                       for k, v in PIECES.items()},
            "presets": PRESETS, "mat_labels": {k: _t(f"ag.mat_{k}") for k in PRESETS},
            "surface_labels": {k: _t(f"ag.surf_{k}") for k in SURFACES}, "saved": saved(rigged)}
    return page.replace("@@DATA@@", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


def generate(cfg, req) -> dict:
    """The editor's request {rigged, item, piece, sides, params, mesh}: Blender finishes the piece, it is put on."""
    rigged = Path(req["rigged"])
    piece, params = req.get("piece"), req.get("params") or {}
    if piece not in PIECES:
        return {"ok": False, "log": _t("ag.unknown_piece", piece)}
    stem = LM._stem(rigged)
    item = re.sub(r"[^A-Za-z0-9_-]+", "_", req.get("item") or f"proc_{piece}").strip("_") or f"proc_{piece}"
    out = rigged.parent / f"{stem}_wear_{item}.glb"
    work = Path(cfg["work_dir"]) / "armour_gen" / f"{stem}_{item}"
    work.mkdir(parents=True, exist_ok=True)
    (work / "mesh.json").write_text(json.dumps(req["mesh"]), encoding="utf-8")
    sides = [s for s in req.get("sides") or [] if s in ("L", "R")] if PIECES[piece][5] == "limb" else []
    job = {"character": str(rigged), "out": str(work / "piece.glb"), "preview": str(work / "preview"), "work": str(work),
           "item": item, "names": {n: LM.bone_names(n) for n in ("mixamo", "godot")}, "piece": piece, "sides": sides,
           "mesh": str(work / "mesh.json"), "wear": float(params.get("wear", .35)), "tex": int(params.get("tex", 1024)),
           "seed": int(params.get("seed", 1))}
    (work / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    t = datetime.now()
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_armour_gen.py"), "--", str(work / "job.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (work / "blender.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    line = next((x for x in r.stdout.splitlines() if x.startswith("ARMOUR_GEN_OK")), None)
    if not line:
        bad = next((x[len("ARMOUR_GEN_FAIL "):] for x in r.stdout.splitlines() if x.startswith("ARMOUR_GEN_FAIL")), None)
        return {"ok": False, "log": _t("ag.failed") + (bad or (r.stdout + r.stderr)[-1500:])}
    info = json.loads(line.split(" ", 1)[1])
    shutil.copy2(work / "piece.glb", out)
    # the editor's list of pieces: a fit.json and a source next to the result (marked: it is changed here, not there)
    shutil.copy2(work / "piece.glb", rigged.parent / f"{stem}_wear_{item}.src.glb")
    (rigged.parent / f"{stem}_wear_{item}.fit.json").write_text(json.dumps(
        {"item": item, "src": f"{stem}_wear_{item}.src.glb", "saved": datetime.now().isoformat(timespec="seconds"),
         "procedural": {"piece": piece, "sides": sides, "params": params},
         "state": {"part": PIECES[piece][4], "under": []}}, ensure_ascii=False, indent=1), encoding="utf-8")
    shots = [str(work / f"preview_{v}.png") for v in ("front", "side", "close") if (work / f"preview_{v}.png").exists()]
    msg = _t("ag.done", out.name, info["vertices"], ", ".join(info["bones"]), (datetime.now() - t).seconds)
    if info.get("over_clothes"):
        msg += "\n" + _t("ag.over_clothes")
    return {"ok": True, "log": msg, "glb": out.resolve().as_posix(), "shots": shots}


def handle(cfg, text):
    """A request from the editor page. The answer also goes to a status file next to the character, which the page
    waits for: <stem>_wear_<item>.wear.json (the Godot fitting room: LM.wear's own, <stem>_wardrobe.wear.json).
    Returns (log, renders)."""
    req = json.loads(text)
    if req.get("action") == "wardrobe":
        return LM.wear(cfg, text), None
    rigged = Path(req["rigged"])
    item = re.sub(r"[^A-Za-z0-9_-]+", "_", req.get("item") or "").strip("_") or f"proc_{req.get('piece')}"
    try:
        res = generate(cfg, req)
    except Exception as e:  # noqa: BLE001  (the page must hear back, or it waits for minutes)
        res = {"ok": False, "log": _t("lm.error", e)}
    (rigged.parent / f"{LM._stem(rigged)}_wear_{item}.wear.json").write_text(
        json.dumps({"id": req.get("id"), **{k: v for k, v in res.items() if k != "shots"}}, ensure_ascii=False), encoding="utf-8")
    return res["log"], res.get("shots")


def _frame(page):
    return ('<iframe srcdoc="%s" style="width:100%%;height:max(780px,86vh);border:0;border-radius:10px"></iframe>'
            % _html.escape(page, quote=True))


def mount(config_loader):
    cfg0 = config_loader()
    gr.Markdown(_t("ag.intro"))
    with gr.Row():
        rig = gr.Dropdown(characters(cfg0), value=(characters(cfg0) or [(None, None)])[0][1], label=_t("ag.character"), scale=4)
        refresh = gr.Button(_t("ui.refresh"), scale=1)
        open_btn = gr.Button(_t("ag.open_editor"), variant="primary", scale=2)
    editor = gr.HTML()
    gr.HTML("<style>.sf3d-hidden{display:none!important}</style>")
    req = gr.Textbox(elem_id=TARGET_ID, elem_classes=["sf3d-hidden"], show_label=False)
    go = gr.Button("go", elem_id=GO_ID, elem_classes=["sf3d-hidden"])
    with gr.Row():
        log = gr.Textbox(label=_t("face.progress"), lines=3, interactive=False, scale=1)
        shots = gr.Gallery(label=_t("ag.previews"), columns=3, height=240, scale=2)

    def open_editor(r):
        if not r or not Path(r).exists():
            return _t("ag.choose_a_character")
        return _frame(editor_page(Path(r)))

    def run(text):
        try:
            return handle(config_loader(), text)
        except Exception as e:  # noqa: BLE001
            return _t("lm.error_2") + str(e), None

    refresh.click(lambda: gr.update(choices=characters(config_loader())), None, rig)
    open_btn.click(open_editor, rig, editor)
    go.click(lambda: _t("ag.working"), None, log).then(run, req, [log, shots], concurrency_id="armour_gen", concurrency_limit=1,
                                                         show_progress="minimal")
