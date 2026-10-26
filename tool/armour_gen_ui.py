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
                      dict(t0=20, t1=100, sector=360, plates=2, straps=1, rigidity=.5, anatomy=0, waist=.9, gap=3, thickness=6)),
          "pauldron": ("arm", "forearm", "shoulder", ("Head", "Hand"), "pauldron", "limb", (-60, 0, 10, 80),
                       dict(t0=-30, t1=45, sector=200, plates=4, straps=0, rigidity=.4, cap=1.8)),
          "tassets": ("hips", "neck", "hips", ("Arm", "Hand"), "torso", "hips", (-80, 0, -10, 30),
                      dict(t0=-45, t1=10, sector=360, plates=4, straps=1, rigidity=.4, gap=16, splits=4, flare=.3)),
          "trousers": ("upleg", "foot", "upleg", ("Arm", "Hand"), "upleg", "legs", (-10, 30, 30, 100),
                       dict(t0=8, t1=92, straps=1, rigidity=.1, gap=3, thickness=5, relief=.6, surface="plain", material="cloth",
                            loose=.3, folds=.3, cuffs=False, buckle=True)),
          "brayette": ("upleg", "foot", "upleg", ("Arm", "Hand"), "upleg", "legs", (-10, 30, 4, 40),
                       dict(t0=8, t1=8, straps=1, rigidity=.15, gap=4, thickness=6, relief=.4, surface="mail", material="iron", loose=.05,
                            folds=0, cuffs=False, buckle=True, strap_width=25)),
          # made by the helmet and elbow generators (vendor/blender_armour) in Blender (MADE), not of the skin
          "helmet": ("head", "head", "head", (), "head", "head", (0, 0, 0, 0),
                     dict(helmet="barbute", head_gap=7, visor_angle=0, cheek_angle=0, tail=100, brim=100)),
          "elbow": ("arm", "forearm", "forearm", (), "elbow", "joint", (0, 0, 0, 0),
                    dict(elbow="elbow_winged_plate", limb_gap=8, wing=100)),
          "footwear": ("leg", "foot", "foot", (), "foot", "joint", (0, 0, 0, 0), dict(footwear="foot_ankle_boot", foot_gap=6)),
          # of the hand's own skin, offset (each finger with its bones), and a cuff round the wrist
          "glove": ("forearm", "hand", "hand", ("Spine", "Hips", "Chest", "UpLeg", "UpperLeg"), "hand", "glove", (0, 0, 0, 0),
                    dict(glove="plain_leather", cuff=14, flare=.2, gap=2, thickness=6, straps=1, strap_width=10, buckle=False,
                         material="leather", surface="plain", rigidity=.3)),
          # under the armour: clothes cut on the body (a shirt, an aketon, a gambeson, doublets, a vest, braies) and a coif
          "undercloth": ("hips", "neck", "spine1", (), "torso", "cloth", (0, 0, 0, 0),
                         dict(cloth_style="shirt", cloth_quilt=False, quilt_lines=False, material="cloth", cloth="#d2c6aa", gap=4, thickness=2, straps=0,
                              surface="plain", rigidity=0))}
CLOTHS = ("cloth_shirt", "cloth_aketon", "cloth_gambeson", "cloth_doublet", "cloth_voider", "cloth_vest", "cloth_braies", "cloth_braies_long",
          "cloth_coif")
GLOVES = ("glove_plain_leather", "glove_reinforced_leather", "glove_mail_mitten", "glove_hourglass", "glove_plate_mitten", "glove_hybrid")
HELMETS = ("kettle_hat", "open_bascinet", "barbute", "visored_bascinet", "sallet", "armet")
FOOTWEAR = ("foot_leather_shoe", "foot_ankle_boot", "foot_mail_foot", "foot_round_sabaton", "foot_pointed_sabaton", "foot_hybrid_boot")
ELBOWS = ("elbow_leather", "elbow_mail", "elbow_early_plate", "elbow_winged_plate", "elbow_articulated_plate", "elbow_plate_mail_hybrid")


def _helmet_params(params) -> dict:
    """The editor's helmet parameters (percent) as blender_helmet_gen.py's."""
    return {"gap": float(params.get("head_gap", 7)) / 100, "visor_angle": float(params.get("visor_angle", 0)),
            "cheek_angle": float(params.get("cheek_angle", 0)), "tail": float(params.get("tail", 100)) / 100,
            "brim": float(params.get("brim", 100)) / 100}


def _elbow_params(params) -> dict:
    return {"gap": float(params.get("limb_gap", 8)) / 100, "wing": float(params.get("wing", 100)) / 100}


def _foot_params(params) -> dict:
    return {"gap": float(params.get("foot_gap", 6)) / 100}


# pieces the generators make: piece -> (the Blender script, its styles (the editor's keys), the style key's prefix in
# them, the editor's parameters -> the script's, the parameters a style's preview depends on besides the gap)
MADE = {"helmet": ("blender_helmet_gen.py", HELMETS, "", _helmet_params,
                   {"visored_bascinet": ("visor_angle",), "armet": ("visor_angle", "cheek_angle"), "sallet": ("tail",),
                    "kettle_hat": ("brim",)}),
        "elbow": ("blender_elbow_gen.py", ELBOWS, "elbow_", _elbow_params,
                  {k: ("wing",) for k in ("elbow_winged_plate", "elbow_articulated_plate", "elbow_plate_mail_hybrid")}),
        "footwear": ("blender_footwear_gen.py", FOOTWEAR, "foot_", _foot_params, {})}
# «from» / «to» labels: a limb's along it, a torso piece's bottom and top, trousers' waist and leg length
T_LABELS = {"limb": ("ag.from", "ag.to", "ag.from_info"), "torso": ("ag.bottom", "ag.top", "ag.bottom_info"),
            "cuirass": ("ag.bottom", "ag.neck_top", "ag.bottom_info"), "pauldron": ("ag.pauldron_from", "ag.sp_reach", "ag.pauldron_info"),
            "hips": ("ag.bottom", "ag.top", "ag.tassets_info"), "legs": ("ag.waist", "ag.leg_length", "ag.waist_info"),
            "head": ("ag.from", "ag.to", "ag.from_info"), "joint": ("ag.from", "ag.to", "ag.from_info"),
            "glove": ("ag.from", "ag.to", "ag.from_info"), "cloth": ("ag.from", "ag.to", "ag.from_info")}
# (linear colour, roughness, metallic): metallic kept moderate, a game scene without reflections shows a full metal black
PRESETS = {"iron": ((.34, .34, .35), .55, .55), "steel": ((.56, .58, .61), .35, .65),
           "bronze": ((.55, .36, .17), .42, .6), "leather": ((.30, .17, .09), .72, 0.0), "cloth": ((.25, .27, .3), .9, 0.0),
           "brass": ((.62, .46, .2), .35, .65), "gold": ((.83, .6, .24), .3, .7)}
SURFACES = ("plates", "scales", "lamellar", "mail", "quilt", "plain", "splints", "brigandine")
# the editor's choices with labels: where a cuirass opens, how an opening fastens, what goes over its shoulders, the
# reference styles
CHOICES = {"opening_labels": ("none", "left", "right", "back", "front"), "closure_labels": ("across", "lace", "round"),
           "shoulder_labels": ("straps", "yoke", "none"),
           "style_labels": ("leather", "steel", "mail", "splints", "covered", "plate_mail", "lamellar", "brigandine", "wool", "leather_tr",
                            "mail_chausses", "plate_cuisses", "hidden_plate", "plate_and_mail", "compact", "extended", "carrier",
                            "short_mail", "wrap_mail", "carrier_mail", "lames", *HELMETS, *ELBOWS, *FOOTWEAR, *GLOVES, *CLOTHS),
           "thigh_labels": ("none", "mail", "plate", "panels", "plate_mail"), "knee_labels": ("none", "patch", "cop")}


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


def _kind(glb: Path):
    """What a piece put on is: the procedural piece it was made as, or the body part it was fitted to («torso»...)."""
    try:
        fit = json.loads(glb.with_suffix(".fit.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return (fit.get("procedural") or {}).get("piece") or (fit.get("state") or {}).get("part")


def worn(rigged: Path) -> list:
    """Every piece put on the character so far (made here or fitted in «Armour»): [{item, glb, piece}] — the editor
    shows them and fits a new piece over the ones ticked (under the ones that go over it: a cuirass over a skirt)."""
    stem = LM._stem(rigged)
    return [{"item": f.name[len(stem) + 6:-4], "glb": f.resolve().as_posix(), "v": int(f.stat().st_mtime), "piece": _kind(f),
             "mask": f.with_suffix(".mask.json").resolve().as_posix() if f.with_suffix(".mask.json").exists() else None}
            for f in sorted(rigged.parent.glob(f"{stem}_wear_*.glb")) if not f.name.endswith(".src.glb")]


def editor_page(rigged: Path) -> str:
    page = i18n.fill(EDITOR.read_text(encoding="utf-8"))
    data = {"rigged": rigged.resolve().as_posix(), "rigged_v": int(rigged.stat().st_mtime), "stem": LM._stem(rigged),
            "target": TARGET_ID, "go": GO_ID, "names": {n: LM.bone_names(n) for n in ("mixamo", "godot")},
            "pieces": {k: {"joints": v[:3], "foreign": v[3], "part": v[4], "family": v[5], "range": v[6], "defaults": v[7],
                           "label": _t(f"ag.piece_{k}"), "tlabels": [_t(x) for x in T_LABELS.get(k, T_LABELS[v[5]])[:2]], "tinfo": _t(T_LABELS.get(k, T_LABELS[v[5]])[2])}
                       for k, v in PIECES.items()},
            "presets": PRESETS, "mat_labels": {k: _t(f"ag.mat_{k}") for k in PRESETS},
            "surface_labels": {k: _t(f"ag.surf_{k}") for k in SURFACES}, "saved": saved(rigged), "worn": worn(rigged),
            **{grp: {k: _t(f"ag.{grp.split('_')[0]}_{k}") for k in keys} for grp, keys in CHOICES.items()}}
    return page.replace("@@DATA@@", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))


def made_preview(cfg, req) -> dict:
    """A piece the generators make (MADE: a helmet, elbows), of a style, made for the character to look at while it is
    chosen (as «Generate» makes it, 5-20 s): work/helmets/<character>/<style>_<the parameters>.glb with its mask, made
    once. {ok, log, preview: {glb, mask, v}}."""
    piece, style, rigged = req.get("piece", "helmet"), req.get("style"), Path(req["rigged"])
    if piece not in MADE or style not in MADE[piece][1]:
        return {"ok": False, "log": _t("ag.unknown_piece", style)}
    script, _, prefix, to_job, own = MADE[piece]
    hp = to_job(req.get("params") or {})
    sides = [x for x in req.get("sides") or [] if x in ("L", "R")]
    tag = "".join(f"_{k[0]}{round(hp[k] * (1 if 'angle' in k else 100))}" for k in ("gap", *own.get(style, ()))) + ("_" + "".join(sides) if sides else "")
    d = Path(cfg["work_dir"]) / "helmets" / LM._slug(LM._stem(rigged))
    d.mkdir(parents=True, exist_ok=True)
    glb, mask = d / f"{style}{tag}.glb", d / f"{style}{tag}.mask.json"
    if not (glb.exists() and mask.exists() and glb.stat().st_mtime > max(rigged.stat().st_mtime, (ROOT / script).stat().st_mtime)):
        job = {"style": style[len(prefix):], "params": hp, "sides": sides, "out": str(glb), "work": str(d), "character": str(rigged),
               "names": {n: LM.bone_names(n) for n in ("mixamo", "godot")}, "mask": str(mask)}
        (d / f"{style}{tag}.job.json").write_text(json.dumps(job, ensure_ascii=False), encoding="utf-8")
        blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
        r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / script), "--", str(d / f"{style}{tag}.job.json")],
                           capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        (d / f"{style}{tag}.log").write_text(r.stdout + r.stderr, encoding="utf-8")
        if not any(x.startswith("ARMOUR_GEN_OK") for x in r.stdout.splitlines()):
            bad = next((x[len("ARMOUR_GEN_FAIL "):] for x in r.stdout.splitlines() if x.startswith("ARMOUR_GEN_FAIL")), None)
            return {"ok": False, "log": _t("ag.failed") + (bad or (r.stdout + r.stderr)[-1500:])}
    return {"ok": True, "log": _t("ag.helmet_ready"),
            "preview": {"glb": glb.resolve().as_posix(), "mask": mask.resolve().as_posix(), "v": int(glb.stat().st_mtime)}}


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
    made = MADE.get(piece)
    if not made:
        (work / "mesh.json").write_text(json.dumps(req["mesh"]), encoding="utf-8")
    sides = [s for s in req.get("sides") or [] if s in ("L", "R")] if PIECES[piece][5] in ("limb", "joint", "glove") else []
    job = {"character": str(rigged), "out": str(work / "piece.glb"), "preview": str(work / "preview"), "work": str(work),
           "item": item, "names": {n: LM.bone_names(n) for n in ("mixamo", "godot")}, "piece": piece, "sides": sides,
           "mesh": str(work / "mesh.json"), "mask": str(work / "mask.json"), "wear": float(params.get("wear", .35)), "tex": int(params.get("tex", 1024)),
           "seed": int(params.get("seed", 1))}
    if piece == "undercloth":
        job["style"] = params.get("cloth_style")
    if made:
        style = params.get(piece) if params.get(piece) in made[1] else made[1][0]
        job.update(style=style[len(made[2]):], params=made[3](params))
    (work / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    t = datetime.now()
    script = made[0] if made else "blender_armour_gen.py"
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / script), "--", str(work / "job.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (work / "blender.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    line = next((x for x in r.stdout.splitlines() if x.startswith("ARMOUR_GEN_OK")), None)
    if not line:
        bad = next((x[len("ARMOUR_GEN_FAIL "):] for x in r.stdout.splitlines() if x.startswith("ARMOUR_GEN_FAIL")), None)
        return {"ok": False, "log": _t("ag.failed") + (bad or (r.stdout + r.stderr)[-1500:])}
    info = json.loads(line.split(" ", 1)[1])
    shutil.copy2(work / "piece.glb", out)
    if (work / "mask.json").exists():   # what of the body it hides: SF3DEquip.wear() takes it away while it is on
        shutil.copy2(work / "mask.json", rigged.parent / f"{stem}_wear_{item}.mask.json")
    # the editor's list of pieces: a fit.json and a source next to the result (marked: it is changed here, not there)
    shutil.copy2(work / "piece.glb", rigged.parent / f"{stem}_wear_{item}.src.glb")
    (rigged.parent / f"{stem}_wear_{item}.fit.json").write_text(json.dumps(
        {"item": item, "src": f"{stem}_wear_{item}.src.glb", "saved": datetime.now().isoformat(timespec="seconds"),
         "procedural": {"piece": piece, "sides": sides, "params": params},
         "state": {"part": PIECES[piece][4], "under": [str(x) for x in req.get("under") or []]}}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    shots = [str(work / f"preview_{v}.png") for v in ("front", "side", "close") if (work / f"preview_{v}.png").exists()]
    msg = _t("ag.done", out.name, info["vertices"], ", ".join(info["bones"]), (datetime.now() - t).seconds)
    if info.get("over_clothes"):
        msg += "\n" + _t("ag.over_clothes")
    mask = rigged.parent / f"{stem}_wear_{item}.mask.json"
    return {"ok": True, "log": msg, "glb": out.resolve().as_posix(), "mask": mask.resolve().as_posix() if mask.exists() else None, "shots": shots}


def handle(cfg, text):
    """A request from the editor page. The answer also goes to a status file next to the character, which the page
    waits for: <stem>_wear_<item>.wear.json (the Godot fitting room: LM.wear's own, <stem>_wardrobe.wear.json).
    Returns (log, renders)."""
    req = json.loads(text)
    if req.get("action") == "wardrobe":
        return LM.wear(cfg, text), None
    if req.get("action") == "made_preview":   # answered in <stem>_helmet_<style>.wear.json
        rigged = Path(req["rigged"])
        try:
            res = made_preview(cfg, req)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": _t("lm.error", e)}
        (rigged.parent / f"{LM._stem(rigged)}_helmet_{req.get('style')}.wear.json").write_text(
            json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
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
