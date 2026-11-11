"""Gradio panel «Equipment: procedural»: a piece of armour made for a rigged character out of its own skin. The editor
page (armour_gen_editor.html) builds the piece and its weights live over the character from the parameters, so the
result is seen (and posed) before it is made; «Generate» sends that geometry here and Blender (blender_armour_gen.py)
bakes its materials and exports it. The result lies next to the character like a piece put on in the «Armour» mode
(<model>/<armor|clothes|weapons>/<item>.glb with its fit.json: wear_files), so the Godot fitting room and the editor's
other pieces see it."""
import base64
import html as _html
import json
import os
import re
import glob
import shutil
import threading
import subprocess
from datetime import datetime
from pathlib import Path

import gradio as gr
import i18n
from i18n import t as _t

import landmarks as LM
import matlib
import texgen_ai
import wear_files as WF

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
          # a codpiece: a cup over the groin on a belt, rigid on the hips (built in the editor: armour_gen_editor codpiece)
          "codpiece": ("hips", "spine", "hips", (), "hips", "groin", (0, 0, 0, 0),
                       dict(codpiece="cod_plate", material="steel", trim="steel", cod_size=100, cod_proj=100, cod_top=0, straps=0, rigidity=1,
                            surface="plain")),
          # the same generator's cups on the knees (poleyns): the thigh, the knee, the shin
          "poleyn": ("upleg", "leg", "leg", (), "knee", "joint", (0, 0, 0, 0), dict(poleyn="poleyn_winged_plate", limb_gap=8, wing=100)),
          # of the hand's own skin, offset (each finger with its bones), and a cuff round the wrist
          "glove": ("forearm", "hand", "hand", ("Spine", "Hips", "Chest", "UpLeg", "UpperLeg"), "hand", "glove", (0, 0, 0, 0),
                    dict(glove="plain_leather", cuff=14, flare=.2, gap=2, thickness=6, straps=1, strap_width=10, buckle=False,
                         material="leather", surface="plain", rigidity=.3)),
          # under the armour: clothes cut on the body (a shirt, an aketon, a gambeson, doublets, a vest, braies) and a coif
          "undercloth": ("hips", "neck", "spine1", (), "torso", "cloth", (0, 0, 0, 0),
                         dict(cloth_style="shirt", cloth_quilt=False, quilt_lines=False, material="cloth", cloth="#d2c6aa", gap=4, thickness=2, straps=0,
                              surface="plain", rigidity=0)),
          # held: a weapon in the hand (rigid on the hand's bone, its grip in the fist), a shield on the forearm
          "weapon": ("forearm", "hand", "hand", (), "hand", "held", (0, 0, 0, 0),
                     dict(weapon="sword", material="steel", trim="steel", tint="#4a2c18", cloth="#6b4a2a", straps=0, rigidity=1)),
          "shield": ("forearm", "hand", "forearm", (), "forearm", "held", (0, 0, 0, 0),
                     dict(shield="round", material="wood", trim="steel", tint="#4a2c18", cloth="#6b4a2a", straps=0, rigidity=1)),
          # a cloak: from the neck over the shoulders and the back; Blender hangs it on chains of cloth bones, the game swings it
          "cloak": ("spine2", "neck", "spine2", (), "torso", "cloak", (0, 0, 0, 0),
                    dict(material="cloth", cloth="#4a3326", surface="plain", trim="", straps=0, rigidity=.5, gap=3, thickness=1.5)),
          # a skirt: the same cloth from the waist down over the hips and the legs (Blender's chains on the hips' bone)
          "skirt": ("hips", "spine", "hips", (), "hips", "cloak", (0, 0, 0, 0),
                    dict(material="cloth", cloth="#5a4630", surface="plain", trim="", straps=0, rigidity=.5, gap=3, thickness=1.5)),
          # a tabard: two panels from the shoulders, open at the sides, a belt round the waist (the same cloth on chains)
          "tabard": ("spine2", "neck", "spine2", (), "torso", "cloak", (0, 0, 0, 0),
                     dict(material="cloth", cloth="#6a2a24", surface="plain", trim="", straps=0, rigidity=.5, gap=3, thickness=1.5)),
          # at the belt: a scabbard on a hip (rigid on the hips), a quiver on the back (on the chest's bone)
          "sheath": ("hips", "spine1", "hips", (), "hips", "held", (0, 0, 0, 0),
                     dict(sheath="scabbard", material="leather", trim="steel", tint="#4a2c18", cloth="#6b4a2a", straps=0, rigidity=1))}
WEAPONS = ("sword", "dagger", "axe", "mace", "spear", "staff", "bow", "greatsword", "greataxe", "warhammer", "club")
SHIELDS = ("round", "kite", "heater", "tower", "scutum")
SHEATHS = ("scabbard", "dagger", "quiver", "quiver_hip")
CLOTHS = ("cloth_fitted", "cloth_shirt", "cloth_aketon", "cloth_gambeson", "cloth_doublet", "cloth_voider", "cloth_vest", "cloth_braies", "cloth_braies_long",
          "cloth_coif")
GLOVES = ("glove_plain_leather", "glove_reinforced_leather", "glove_mail_mitten", "glove_hourglass", "glove_plate_mitten", "glove_hybrid")
HELMETS = ("kettle_hat", "open_bascinet", "barbute", "visored_bascinet", "sallet", "armet")
FOOTWEAR = ("foot_leather_shoe", "foot_ankle_boot", "foot_mail_foot", "foot_round_sabaton", "foot_pointed_sabaton", "foot_hybrid_boot")
ELBOWS = ("elbow_leather", "elbow_mail", "elbow_early_plate", "elbow_winged_plate", "elbow_articulated_plate", "elbow_plate_mail_hybrid")
POLEYNS = tuple("poleyn_" + x[len("elbow_"):] for x in ELBOWS)


def _helmet_params(params) -> dict:
    """The editor's helmet parameters (percent) as blender_helmet_gen.py's."""
    return {"gap": float(params.get("head_gap", 7)) / 100, "visor_angle": float(params.get("visor_angle", 0)),
            "cheek_angle": float(params.get("cheek_angle", 0)), "tail": float(params.get("tail", 100)) / 100,
            "brim": float(params.get("brim", 100)) / 100, "strap": float(params.get("strap", 0)) / 100,
            "strap_fwd": float(params.get("strap_fwd", 0)) / 100}


def _elbow_params(params) -> dict:
    return {"gap": float(params.get("limb_gap", 8)) / 100, "wing": float(params.get("wing", 100)) / 100}


def _poleyn_params(params) -> dict:
    return {**_elbow_params(params), "limb": "leg"}


def _foot_params(params) -> dict:
    return {"gap": float(params.get("foot_gap", 6)) / 100}


# pieces the generators make: piece -> (the Blender script, its styles (the editor's keys), the style key's prefix in
# them, the editor's parameters -> the script's, the parameters a style's preview depends on besides the gap)
MADE = {"helmet": ("blender_helmet_gen.py", HELMETS, "", _helmet_params,
                   {"visored_bascinet": ("visor_angle",), "armet": ("visor_angle", "cheek_angle"), "sallet": ("tail", "strap", "strap_fwd"),
                    "kettle_hat": ("brim", "strap", "strap_fwd"), "barbute": ("strap", "strap_fwd"), "open_bascinet": ("strap", "strap_fwd")}),
        "elbow": ("blender_elbow_gen.py", ELBOWS, "elbow_", _elbow_params,
                  {k: ("wing",) for k in ("elbow_winged_plate", "elbow_articulated_plate", "elbow_plate_mail_hybrid")}),
        "footwear": ("blender_footwear_gen.py", FOOTWEAR, "foot_", _foot_params, {}),
        "poleyn": ("blender_elbow_gen.py", POLEYNS, "poleyn_", _poleyn_params,
                   {k: ("wing",) for k in ("poleyn_winged_plate", "poleyn_articulated_plate", "poleyn_plate_mail_hybrid")})}
# «from» / «to» labels: a limb's along it, a torso piece's bottom and top, trousers' waist and leg length
T_LABELS = {"limb": ("ag.from", "ag.to", "ag.from_info"), "torso": ("ag.bottom", "ag.top", "ag.bottom_info"),
            "cuirass": ("ag.bottom", "ag.neck_top", "ag.bottom_info"), "pauldron": ("ag.pauldron_from", "ag.sp_reach", "ag.pauldron_info"),
            "hips": ("ag.bottom", "ag.top", "ag.tassets_info"), "legs": ("ag.waist", "ag.leg_length", "ag.waist_info"),
            "head": ("ag.from", "ag.to", "ag.from_info"), "joint": ("ag.from", "ag.to", "ag.from_info"),
            "glove": ("ag.from", "ag.to", "ag.from_info"), "cloth": ("ag.from", "ag.to", "ag.from_info"),
            "held": ("ag.from", "ag.to", "ag.from_info"), "cloak": ("ag.from", "ag.to", "ag.from_info"),
            "groin": ("ag.from", "ag.to", "ag.from_info")}
# (linear colour, roughness, metallic): metallic kept moderate, a game scene without reflections shows a full metal black
PRESETS = {"iron": ((.34, .34, .35), .55, .55), "steel": ((.56, .58, .61), .35, .65),
           "bronze": ((.55, .36, .17), .42, .6), "leather": ((.30, .17, .09), .72, 0.0), "cloth": ((.25, .27, .3), .9, 0.0),
           "brass": ((.62, .46, .2), .35, .65), "gold": ((.83, .6, .24), .3, .7), "wood": ((.24, .14, .07), .78, 0.0)}
SURFACES = ("plates", "scales", "lamellar", "mail", "quilt", "plain", "splints", "brigandine")
# the editor's choices with labels: where a cuirass opens, how an opening fastens, what goes over its shoulders, the
# reference styles
CHOICES = {"opening_labels": ("none", "left", "right", "back", "front"), "closure_labels": ("across", "lace", "round"),
           "shoulder_labels": ("straps", "yoke", "none"),
           "style_labels": ("leather", "steel", "mail", "splints", "covered", "plate_mail", "lamellar", "brigandine", "tights", "wool", "leather_tr",
                            "mail_chausses", "plate_cuisses", "hidden_plate", "plate_and_mail", "compact", "extended", "carrier",
                            "short_mail", "wrap_mail", "carrier_mail", "lames", *HELMETS, *ELBOWS, *POLEYNS, "cod_plate", "cod_leather", "cod_cloth", *FOOTWEAR, *GLOVES, *CLOTHS,
                            *(f"weapon_{w}" for w in WEAPONS), *(f"shield_{x}" for x in SHIELDS), *(f"sheath_{x}" for x in SHEATHS)),
           "thigh_labels": ("none", "mail", "plate", "panels", "plate_mail"), "knee_labels": ("none", "patch", "cop")}


def characters(cfg):
    """Every character with a skeleton under the export folder (built from the markup or by the auto-rigger; the
    markup's first where a folder has both): (its name, the rigged GLB)."""
    out = {}
    for p in sorted(Path(cfg["export_dir"]).rglob("*_rigged.glb")):
        key = (p.parent, LM._stem(p))
        if key not in out or LM.is_landmark_rig(p):
            out[key] = p
    return [(LM._stem(p), p.resolve().as_posix()) for p in sorted(out.values())]


def saved(rigged: Path) -> list:
    """The character's pieces made here before: [{item, piece, sides, params}] (the editor opens them again)."""
    out = []
    for f in WF.fits(rigged):
        try:
            js = json.loads(f.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        pr = js.get("procedural")
        if isinstance(pr, dict) and pr.get("piece") in PIECES and isinstance(pr.get("params"), dict):
            out.append({"item": f.name[:-len(".fit.json")], "piece": pr["piece"], "style": pr.get("style"),
                        "sides": pr.get("sides") or [], "params": pr["params"],
                        "under": (js.get("state") or {}).get("under") or []})   # (what it was made over)
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
    return [{"item": f.name[:-4], "glb": f.resolve().as_posix(), "v": int(f.stat().st_mtime), "piece": _kind(f),
             "mask": f.with_suffix(".mask.json").resolve().as_posix() if f.with_suffix(".mask.json").exists() else None}
            for f in WF.pieces(rigged)]


def remove_piece(cfg, rigged: Path, item: str) -> dict:
    """A piece taken off the character for good (asked first in the page): its files (<folder>/<item>.*, by the exact
    name: «a» is not «a_2»; its answers) deleted. The Godot fitting room drops its copy when next opened."""
    files = [WF.path(rigged, item, x) for x in WF.SUFFIXES] + [WF.status(cfg, rigged, f"_qa_{item}"), WF.status(cfg, rigged, f"_wear_{item}")]
    files = [f for f in files if f.is_file()]
    if not item or not files:
        return {"ok": False, "log": _t("ag.remove_none", item)}
    for f in files:
        f.unlink()
    folder = WF.path(rigged, item, ".glb").parent
    if folder.parent == rigged.parent and folder.name in WF.CATS and folder.is_dir() and not any(folder.iterdir()):
        folder.rmdir()   # its kind's folder, now empty
    return {"ok": True, "log": _t("ag.removed", item)}


DECALS = ROOT / "decals"   # the shared emblems and digits (decals/make_decals.py draws them)


def decals(folder: Path) -> list:
    """The pictures the «Paint» brush can put on (export/decals): the shared set is copied there the first time, and
    any PNG put there is offered too. [{name, path, label}]"""
    if not any(DECALS.glob("*.png")):   # the repository keeps the script, not the pictures: drawn once here
        import importlib.util
        spec = importlib.util.spec_from_file_location("make_decals", DECALS / "make_decals.py")
        md = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(md)
        md.main(DECALS)
    if not folder.exists():
        folder.mkdir(parents=True, exist_ok=True)
        for f in DECALS.glob("*.png"):
            shutil.copy2(f, folder / f.name)
    own = {f.stem for f in DECALS.glob("*.png")}
    key = lambda f: (f.stem not in own, f.stem.startswith("digit_"), f.stem)   # the set's heads, its digits, then one's own
    return [{"name": f.stem, "path": f.resolve().as_posix(),
             "label": f.stem[6:] if f.stem.startswith("digit_") else _t(f"ag.decal_{f.stem}") if f.stem in own else f.stem}
            for f in sorted(folder.glob("*.png"), key=key)]


VENDOR = Path(__file__).resolve().parent / "vendor"
GEN_WORDS = ("or", "argent", "gules", "azure", "vert", "sable", "purpure", "murrey", "tenne",   # the painting generator's choices
             "none", "lattice", "scales", "vines", "drops", "checks", "stars", "arms", "cross", "saltire")


def web_assets(cfg=None) -> dict:
    """The painting generator's libraries for the page (the app serves files only from export/ and work/): copied to
    work/web when newer - Armoria's generator and renderer (MIT) with its CC0 charges, FastNoiseLite (MIT). {name: path}"""
    work = Path((cfg or __import__("sf3d_tool").load_config())["work_dir"]) / "web"
    out = {}
    for name, src, dst in (("armoria", VENDOR / "armoria" / "armoria.mjs", work / "armoria" / "armoria.js"),
                           ("noise", VENDOR / "fastnoiselite" / "FastNoiseLite.js", work / "fastnoiselite" / "FastNoiseLite.js")):
        if not src.exists():
            continue
        dst.parent.mkdir(parents=True, exist_ok=True)
        if not dst.exists() or dst.stat().st_mtime < src.stat().st_mtime:
            shutil.copy2(src, dst)
        out[name] = dst.resolve().as_posix()
    charges = VENDOR / "armoria" / "charges"
    if charges.is_dir():
        to = work / "armoria" / "charges"
        to.mkdir(parents=True, exist_ok=True)
        for f in charges.glob("*.svg"):
            if not (to / f.name).exists():
                shutil.copy2(f, to / f.name)
        out["charges"] = to.resolve().as_posix() + "/"
    return out


def save_decal(cfg, req) -> dict:
    """A picture made in the page (the painting generator) as a PNG among the «Paint» pictures (export/decals)."""
    import base64
    name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(req.get("name") or "")).strip("_")[:60]
    data = str(req.get("png") or "")
    ext = ".png" if data.startswith("data:image/png;base64,") else ".jpg" if data.startswith("data:image/jpeg;base64,") else None
    if not name or not ext:
        return {"ok": False, "log": _t("ag.decal_bad")}
    folder = Path(req.get("dir") or Path(cfg["export_dir"]) / "decals").resolve()   # the folder the page's pictures are from
    roots = [Path(cfg["export_dir"]).resolve(), Path(cfg["work_dir"]).resolve()]
    if not any(folder == r or r in folder.parents for r in roots):
        return {"ok": False, "log": _t("ag.decal_bad")}
    folder.mkdir(parents=True, exist_ok=True)
    f = folder / f"{name}{ext}"
    f.write_bytes(base64.b64decode(data.split(",", 1)[1]))
    return {"ok": True, "log": _t("ag.decal_saved", f.name), "decal": {"name": name, "path": f.resolve().as_posix(), "label": name}}


def uv_dir(rigged: Path, item: str, piece=None) -> Path:
    """«Texture by the unwrap»: the piece's unwrap pictures and the textures painted on them, next to it."""
    item = re.sub(r"[^A-Za-z0-9_-]+", "_", item or "").strip("_")
    return WF.path(rigged, item, ".glb", piece).parent / f"{item}_uv"


def _uv_fit(src: Path, mask: Path, size: int) -> tuple:
    """A texture given back made to fit the unwrap: its size, and the holes in it - where an island of the mask meets
    its empty background (a picture painted on another layout, as an image model draws its own) - filled from the
    colour round them (push-pull: averaged down a pyramid, taken back up where empty). Saved as <slot>_user_fit.png,
    the given one kept. -> (that file, the share of the islands that were holes)"""
    import numpy as np
    from PIL import Image, ImageFilter
    im = Image.open(src).convert("RGB")
    if im.size != (size, size):
        im = im.resize((size, size), Image.LANCZOS)
    a = np.asarray(im, np.float32)
    m = np.asarray(Image.open(mask).convert("L").resize((size, size)), np.float32) > 127
    corners = np.concatenate([a[:24, :24].reshape(-1, 3), a[:24, -24:].reshape(-1, 3), a[-24:, :24].reshape(-1, 3), a[-24:, -24:].reshape(-1, 3)])
    bg = np.median(corners, axis=0)   # its background: what its corners are
    far = np.linalg.norm(a - bg, axis=2) > 22
    cont = np.asarray(Image.fromarray((far * 255).astype(np.uint8)).filter(ImageFilter.MaxFilter(3)).filter(ImageFilter.MinFilter(5)), np.float32) > 127
    if corners.std(axis=0).mean() > 8:   # its corners not one flat colour: a picture over the whole square, no background
        cont = np.ones_like(m)
    holes = m & ~cont
    share = float(holes.sum() / max(1, m.sum()))
    aligned = cont.sum() > 0 and (cont & m).sum() / cont.sum() > .9 and not cont.all()
    if aligned:   # painted on this unwrap (its islands within ours): inside them as it is; only the rim the bake's margin adds
        # round each island (its background there would show as a seam on the model) takes the island's colour
        inner = np.asarray(Image.fromarray((m * 255).astype(np.uint8)).filter(ImageFilter.MinFilter(17)), np.float32) > 127
        holes = m & ~cont & ~inner
        share = 0.
    if holes.any() and not aligned:   # first the texture itself, from places moved by a few steps that have it; what is left: push-pull
        rest, orig = holes.copy(), a.copy()
        for dy, dx in ((0, 37), (41, 0), (-29, 53), (61, -17), (0, -83), (-97, 0), (113, 71), (-71, -127), (151, -43), (-167, 149), (211, 0), (0, -233)):
            if not rest.any():
                break
            ok_s = np.roll(np.roll(cont, dy, 0), dx, 1)
            take = rest & ok_s
            a[take] = np.roll(np.roll(orig, dy, 0), dx, 1)[take]
            rest &= ~take
        cont = cont | (holes & ~rest)
    if holes.any() and (m & ~cont).any():
        ok = cont.astype(np.float32)
        levels = [(a * ok[..., None], ok)]
        while levels[-1][1].shape[0] > 1:
            c, w = levels[-1]
            h2 = c.shape[0] // 2
            c = c[:h2 * 2, :h2 * 2].reshape(h2, 2, h2, 2, 3).sum(axis=(1, 3)); w = w[:h2 * 2, :h2 * 2].reshape(h2, 2, h2, 2).sum(axis=(1, 3))
            levels.append((c, w))
        fill = levels[-1][0] / np.maximum(levels[-1][1], 1e-6)[..., None]
        for c, w in reversed(levels[:-1]):
            up = np.repeat(np.repeat(fill, 2, axis=0), 2, axis=1)[:c.shape[0], :c.shape[1]]
            have = w > 0
            fill = np.where(have[..., None], c / np.maximum(w, 1e-6)[..., None], up)
        a = np.where(cont[..., None], a, fill)
    out = src.with_name(src.stem + "_fit.png")
    Image.fromarray(a.clip(0, 255).astype(np.uint8)).save(out)
    return out, share


def uv_action(cfg, req) -> dict:
    """uv_info: the unwrap given out with the piece made last ({folder, size, slots: {slot: {hash}}, user: {slot: path}});
    uv_put: a texture for a slot (a data URL) saved as <slot>_user.png there, or (no data) the <slot>_user.png files
    found there (painted elsewhere) - each with its unwrap's hash, for the next «Generate»; uv_open: the folder shown."""
    rigged = Path(req["rigged"])
    d = uv_dir(rigged, req.get("item") or "", req.get("piece"))
    info = d / "uv.json"
    if not info.exists():
        return {"ok": False, "log": _t("ag.uv_none"), "folder": d.resolve().as_posix()}
    j = json.loads(info.read_text(encoding="utf-8"))
    user = {f.stem[:-5]: f.resolve().as_posix() for f in d.glob("*_user.png") if f.stem[:-5] in j["slots"]}   # (not *_user_fit.png)
    out = {"ok": True, "folder": d.resolve().as_posix(), "size": j["size"], "slots": j["slots"], "user": user}
    if req["action"] == "uv_open":
        import os
        os.startfile(str(d))   # (the app runs on Windows)
        out["log"] = _t("ag.uv_opened", d)
    elif req["action"] in ("uv_put", "ai_texture"):
        if req["action"] == "ai_texture":   # the part's colours repainted by an image model (OpenRouter), kept as its texture
            sl = str(req.get("slot") or "")
            if sl not in j["slots"]:
                return {"ok": False, "log": _t("ag.uv_bad_slot", sl)}
            key = cfg.get("openrouter_key") or os.environ.get("OPENROUTER_API_KEY", "")
            if not key:
                return {"ok": False, "log": _t("ag.ai_no_key")}
            model = str(req.get("model") or texgen_ai.DEFAULT)
            t0 = datetime.now()
            png, cost = texgen_ai.edit(key, model, str(req.get("prompt") or ""), d / f"{sl}_color.png")
            keep = d / f"{sl}_ai_{re.sub(r'[^A-Za-z0-9_.-]+', '_', model.split('/')[-1])}_{t0:%H%M%S}.png"   # (each one kept)
            keep.write_bytes(png)
            from PIL import Image
            Image.open(keep).convert("RGB").save(d / f"{sl}_user.png")
            user = {sl: (d / f"{sl}_user.png").resolve().as_posix()}
            out["ai"] = {"model": model, "cost": cost, "file": keep.name, "seconds": (datetime.now() - t0).seconds}
        elif req.get("data"):
            from PIL import Image
            import io as _io
            sl = str(req.get("slot") or "")
            if sl not in j["slots"]:
                return {"ok": False, "log": _t("ag.uv_bad_slot", sl)}
            im = Image.open(_io.BytesIO(base64.b64decode(str(req["data"]).split(",", 1)[1]))).convert("RGB")
            im.save(d / f"{sl}_user.png")
            user = {sl: (d / f"{sl}_user.png").resolve().as_posix()}   # (the one loaded: the others as they are)
        fits, notes = {}, []
        for sl, p in user.items():
            f, share = _uv_fit(Path(p), d / f"{sl}_mask.png", j["size"])
            fits[sl] = f.resolve().as_posix()
            if share > .03:   # painted on another layout: its background fell on the islands
                notes.append(_t("ag.uv_holes", _t(f"ag.lib_slot_{sl}"), round(share * 100)))
        out["user"] = user
        out["uvtex"] = {sl: {"path": p, "hash": j["slots"][sl]["hash"]} for sl, p in fits.items()}
        out["log"] = (_t("ag.uv_taken", ", ".join(_t(f"ag.lib_slot_{s}") for s in user)) if user else _t("ag.uv_no_user", d)) + "".join("\n" + x for x in notes)
        if out.get("ai"):
            a = out["ai"]
            out["log"] = _t("ag.ai_done", a["model"], a["seconds"], f"${a['cost']:.3f}" if isinstance(a["cost"], (int, float)) else "?", a["file"]) + "\n" + out["log"]
    else:
        out["log"] = _t("ag.uv_ready", d)
    return out


def editor_page(rigged: Path, decals_dir: Path | None = None) -> str:
    page = i18n.fill(EDITOR.read_text(encoding="utf-8"))
    data = {"rigged": rigged.resolve().as_posix(), "rigged_v": int(rigged.stat().st_mtime), "stem": LM._stem(rigged),
            "status_dir": WF.status_dir(None, rigged).resolve().as_posix(),   # where the answers to the page go
            "target": TARGET_ID, "go": GO_ID, "names": {n: LM.bone_names(n) for n in ("mixamo", "godot")},
            "pieces": {k: {"joints": v[:3], "foreign": v[3], "part": v[4], "family": v[5], "range": v[6], "defaults": v[7],
                           "label": _t(f"ag.piece_{k}"), "tlabels": [_t(x) for x in T_LABELS.get(k, T_LABELS[v[5]])[:2]], "tinfo": _t(T_LABELS.get(k, T_LABELS[v[5]])[2])}
                       for k, v in PIECES.items()},
            "presets": PRESETS, "mat_labels": {k: _t(f"ag.mat_{k}") for k in PRESETS},
            "surface_labels": {k: _t(f"ag.surf_{k}") for k in SURFACES}, "saved": saved(rigged), "worn": worn(rigged),
            "decals": decals(decals_dir) if decals_dir else [], "decals_dir": decals_dir.resolve().as_posix() if decals_dir else "",
            "materials_dir": (decals_dir.parent / "materials").resolve().as_posix() if decals_dir else "",   # the library's downloads
            "concepts_dir": (decals_dir.parent / "concepts").resolve().as_posix() if decals_dir else "",   # «Texture from a picture»'s pictures
            "fist": LM.fist_hand(rigged), "web": web_assets(),
            "gen_labels": {k: _t(f"ag.gen_{k}") for k in GEN_WORDS},
            "proj_views": {k: _t(f"ag.proj_{k}") for k in ("front", "back", "left", "right")},
            "lib_slots": {k: _t(f"ag.lib_slot_{k}") for k in ("plate", "strap", "detail", "mail", "quilt", "trim", "wood")},
            "lib_cats": {k: _t(f"ag.lib_cat_{k}") for k in ("wood", "planks", "leather", "fabric", "metal", "rust", "paint", "gold")},
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
    out = WF.path(rigged, item, ".glb", piece, make=True)
    work = Path(cfg["work_dir"]) / "armour_gen" / f"{stem}_{item}"
    work.mkdir(parents=True, exist_ok=True)
    # another kind's piece of this name (a bracer) is not made over (as a greave) unless the editor asked and was told so
    fit = WF.path(rigged, item, ".fit.json", piece)
    try:
        had = (json.loads(fit.read_text(encoding="utf-8")).get("procedural") or {}).get("piece") if fit.exists() else None
    except (OSError, ValueError):
        had = None
    if had and had != piece and not req.get("replace"):
        return {"ok": False, "log": _t("ag.other_kind", item, had, piece)}
    made = MADE.get(piece)
    if not made:
        (work / "mesh.json").write_text(json.dumps(req["mesh"]), encoding="utf-8")
    sides = [s for s in req.get("sides") or [] if s in ("L", "R")] if PIECES[piece][5] in ("limb", "joint", "glove", "held") else []
    job = {"character": str(rigged), "out": str(work / "piece.glb"), "preview": str(work / "preview"), "work": str(work),
           "item": item, "names": {n: LM.bone_names(n) for n in ("mixamo", "godot")}, "piece": piece, "sides": sides,
           "mesh": str(work / "mesh.json"), "mask": str(work / "mask.json"), "wear": float(params.get("wear", .35)), "tex": int(params.get("tex", 1024)),
           "seed": int(params.get("seed", 1)), "fist": LM.fist_hand(rigged),
           "two": req.get("two") if re.fullmatch(r"[LR](_-?\d+){9}", str(req.get("two") or "")) else "",
           "point": req.get("point") if re.fullmatch(r"-?\d+(_-?\d+){2}", str(req.get("point") or "")) else "",
           "fist_grip": piece == "shield" and bool(params.get("s_hand")),   # a shield held by its bar: the fingers close as on a weapon
           "uv_out": str(work / "uv"), "uvtex": params.get("uvtex") or {},   # «Texture by the unwrap»: given out, taken back
           "uv_prev": str(uv_dir(rigged, item, piece))}   # (its unwrap kept there: the same mesh unwrapped as before)
    if piece == "undercloth":
        job["style"] = params.get("cloth_style")
    if PIECES[piece][5] in ("held", "cloak"):   # held, not worn (the fingers round a grip stay); a cloak swings off the body
        job.pop("mask")
        (work / "mask.json").unlink(missing_ok=True)
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
    if (work / "uv").exists():   # the unwrap's pictures next to the piece (<item>_uv/), a texture painted there kept
        ud = uv_dir(rigged, item, piece)
        ud.mkdir(parents=True, exist_ok=True)
        for f in (work / "uv").iterdir():
            shutil.copy2(f, ud / f.name)
    if (work / "mask.json").exists():   # what of the body it hides: SF3DEquip.wear() takes it away while it is on
        shutil.copy2(work / "mask.json", WF.path(rigged, item, ".mask.json", piece))
    else:   # a held piece hides nothing: an older piece's mask of that name goes
        WF.path(rigged, item, ".mask.json", piece).unlink(missing_ok=True)
    # the editor's list of pieces: a fit.json and a source next to the result (marked: it is changed here, not there)
    shutil.copy2(work / "piece.glb", WF.path(rigged, item, ".src.glb", piece))
    WF.path(rigged, item, ".fit.json", piece).write_text(json.dumps(
        {"item": item, "src": f"{item}.src.glb", "saved": datetime.now().isoformat(timespec="seconds"),
         "procedural": {"piece": piece, "sides": sides, "params": params, "style": req.get("style")},
         "state": {"part": PIECES[piece][4], "under": [str(x) for x in req.get("under") or []]}}, ensure_ascii=False, indent=1),
        encoding="utf-8")
    shots = [str(work / f"preview_{v}.png") for v in ("front", "side", "close") if (work / f"preview_{v}.png").exists()]
    msg = _t("ag.done", out.name, info["vertices"], ", ".join(info["bones"]), (datetime.now() - t).seconds)
    for sl, st in (info.get("uvtex") or {}).items():
        msg += "\n" + _t("ag.uv_applied" if st == "ok" else "ag.uv_changed", _t(f"ag.lib_slot_{sl}"))
    if info.get("over_clothes"):
        msg += "\n" + _t("ag.over_clothes")
    mask = WF.path(rigged, item, ".mask.json", piece)
    return {"ok": True, "log": msg, "glb": out.resolve().as_posix(), "mask": mask.resolve().as_posix() if mask.exists() else None, "shots": shots}


def qa(cfg, req) -> dict:
    """The piece made last of this item checked in the character's animations (blender_wear_qa.py): where the skin
    comes out through it, where its mask shows a hole. {ok, log, report}"""
    rigged = Path(req["rigged"])
    stem = LM._stem(rigged)
    item = re.sub(r"[^A-Za-z0-9_-]+", "_", req.get("item") or "").strip("_")
    piece = WF.path(rigged, item, ".glb")
    if not piece.exists():
        return {"ok": False, "log": _t("ag.qa_no_piece")}
    work = Path(cfg["work_dir"]) / "armour_gen" / f"{stem}_{item}"
    work.mkdir(parents=True, exist_ok=True)
    anim = LM._animated_model(cfg, rigged, Path(cfg["work_dir"]) / "wardrobe" / LM._slug(stem))
    mask = piece.with_suffix(".mask.json")
    job = {"character": str(anim), "piece": str(piece), "mask": str(mask) if mask.exists() else None, "out": str(work / "qa.json"), "step": 3}
    kind = req.get("piece")
    if kind in PIECES and PIECES[kind][5] == "cloak":   # swung by the game's cloth (SF3DEquip.Cloth): Blender's clips cannot show it
        return {"ok": True, "log": _t("ag.cloak_qa")}
    held = kind in PIECES and PIECES[kind][5] == "held"
    if held:   # the body going into it, not the arm holding it (a shield strapped on catches its upper arm by the elbow)
        sides = [x for x in req.get("sides") or [] if x in ("L", "R")] or ["R"]
        tables = [LM.bone_names(n) for n in ("mixamo", "godot")]
        ids = [] if kind == "sheath" else [f"{j}_{sd}" for sd in sides for j in ("arm", "forearm", "hand", *(f"{f}{k}" for f in LM.FIST_FINGERS for k in (1, 2, 3, 4)))]
        # the spear's and the bow's clips hold the off hand on the shaft or the bow: not what a shield's arm (or another
        # weapon's) does, so not checked for it
        made = WF.path(rigged, item, ".fit.json")
        w = ((json.loads(made.read_text(encoding="utf-8")).get("procedural") or {}).get("params") or {}).get("weapon") if made.exists() else None
        job["skip_clips"] = [x for x in ("spear", "bow") if not (kind == "weapon" and w == x)]
        job["held"] = {"skip": sorted({t[i] for t in tables for i in ids if i in t}), "shield": kind == "shield",
                       "fore": [t["hips" if kind == "sheath" else f"forearm_{sides[0]}"] for t in tables], "hips": [t["hips"] for t in tables]}
    (work / "qa_job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    t = datetime.now()
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_wear_qa.py"), "--", str(work / "qa_job.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    (work / "qa.log").write_text(r.stdout + r.stderr, encoding="utf-8")
    if not any(x.startswith("WEAR_QA_OK") for x in r.stdout.splitlines()):
        return {"ok": False, "log": _t("ag.failed") + (r.stdout + r.stderr)[-1200:]}
    rep = json.loads((work / "qa.json").read_text(encoding="utf-8"))
    if held:
        lines = [_t("ag.qa_held_line", c["clip"], c["through"], c["worst_frame"]) + (_t("ag.qa_held_facing", c["facing"]) if c["facing"] else "")
                 for c in rep["clips"]]
        bad = any(c["through"] for c in rep["clips"]) or any(c["facing"] for c in rep["clips"])
        msg = _t("ag.qa_summary", len(rep["clips"]), (datetime.now() - t).seconds) + "\n" + "\n".join(lines) + "\n" + (
            (_t("ag.qa_held_bad") if kind == "shield" else _t("ag.qa_held_bad_sheath") if kind == "sheath" else _t("ag.qa_held_bad_weapon"))
            if bad else _t("ag.qa_held_good"))
        return {"ok": True, "log": msg, "report": (work / "qa.json").resolve().as_posix(), "points": len(rep["points"]), "need": rep["need"]}
    lines = [_t("ag.qa_line", c["clip"], c["poke_share"] * 100, c["worst_frame"], c["hole_share"] * 100) for c in rep["clips"]]
    bad = [c for c in rep["clips"] if c["poke_share"] > .02 or c["hole_share"] > .05]
    msg = _t("ag.qa_summary", len(rep["clips"]), (datetime.now() - t).seconds) + "\n" + "\n".join(lines) + "\n" + (
        _t("ag.qa_bad") if bad else _t("ag.qa_good"))
    return {"ok": True, "log": msg, "report": (work / "qa.json").resolve().as_posix(), "points": len(rep["points"])}


# «Rebuild by layers» in the background: the editor works out every piece's shape at once (inside out, each over the
# ones under it) and queues them here; a thread makes them in Blender one after another while the editor stays free.
# Its state is in <stem>_bake.wear.json, which the editor reads: {batch, queue, current, done: [{item, ok, log, glb,
# mask}], running, stopped}. «Stop» empties the queue: the piece in Blender is finished, the ones made stay.
_BAKES, _BAKE_LOCK = {}, threading.Lock()


def _bake_write(rigged: Path, b: dict):
    WF.status(None, rigged, "_bake").write_text(json.dumps(
        {"batch": b["batch"], "queue": [j["item"] for j in b["q"]], "current": b["current"], "done": b["done"],
         "running": b["running"], "stopped": b["stopped"]}, ensure_ascii=False), encoding="utf-8")


def _bake_run(cfg, rigged: Path, b: dict):
    while True:
        with _BAKE_LOCK:
            if not b["q"]:
                b["current"], b["running"] = None, False
                _bake_write(rigged, b)
                return
            job = b["q"].pop(0)
            b["current"] = job["item"]
            _bake_write(rigged, b)
        try:
            res = generate(cfg, job)
        except Exception as e:  # noqa: BLE001  (the next ones still go)
            res = {"ok": False, "log": _t("lm.error", e)}
        with _BAKE_LOCK:
            b["done"].append({"item": job["item"], "ok": bool(res.get("ok")), "log": res.get("log", ""), "glb": res.get("glb"), "mask": res.get("mask")})


def bake(cfg, req) -> dict:
    """One piece of a batch queued (req: {rigged, batch, job: the «generate» request}), or the batch stopped
    (req.stop). Starts the thread when none runs."""
    rigged = Path(req["rigged"])
    with _BAKE_LOCK:
        b = _BAKES.setdefault(str(rigged), {"batch": 0, "q": [], "current": None, "done": [], "running": False, "stopped": False})
        if req.get("stop"):
            b["q"].clear(); b["stopped"] = True
            _bake_write(rigged, b)
            return {"ok": True, "log": _t("ag.bake_stopping")}
        if req.get("batch") != b["batch"]:   # a new batch: what the last one made is not reported again
            b["batch"], b["done"], b["stopped"] = req.get("batch"), [], False
        b["q"].append({**req["job"], "rigged": req["rigged"]})
        if not b["running"]:
            b["running"] = True
            threading.Thread(target=_bake_run, args=(cfg, rigged, b), daemon=True).start()
        _bake_write(rigged, b)
    return {"ok": True, "log": _t("ag.bake_queued", req["job"].get("item"))}


def handle(cfg, text):
    """A request from the editor page. The answer also goes to a status file next to the character, which the page
    waits for: work/status/<model>/<stem>_wear_<item>.wear.json (the Godot fitting room: LM.wear's own, <stem>_wardrobe.wear.json).
    Returns (log, renders)."""
    req = json.loads(text)
    if req.get("action") == "wardrobe":
        return LM.wear(cfg, text), None
    if req.get("action") in ("matlib_search", "matlib_get", "matlib_custom"):   # the materials' library: answered in <stem>_<action>.wear.json
        rigged = Path(req["rigged"])
        try:
            folder = Path(req.get("dir") or Path(cfg["export_dir"]) / "materials").resolve()
            roots = [Path(cfg["export_dir"]).resolve(), Path(cfg["work_dir"]).resolve()]
            if not any(folder == r or r in folder.parents for r in roots):
                raise ValueError(folder)
            if req["action"] == "matlib_search":
                if req.get("source") == "custom":   # your own: made here, filtered by the words
                    words = [w for w in re.split(r"\W+", (req.get("q") or "").lower()) if w]
                    found = [x for x in matlib.customs(folder) if all(w in x["name"].lower() for w in words)]
                else:
                    found = matlib.search(req.get("source") or "ambientcg", req.get("q") or "")
                res = {"ok": True, "found": found, "log": _t("ag.lib_found", len(found))}
            elif req["action"] == "matlib_custom":
                mat = matlib.custom(folder, str(req.get("name") or "material"), req.get("files") or [], float(req.get("size_cm") or 30),
                                    bool(req.get("seamless", True)), bool(req.get("metal")))
                res = {"ok": True, "material": mat, "log": _t("ag.lib_custom_made", mat["name"])}
            else:
                mat = matlib.get(folder, req.get("source") or "ambientcg", str(req.get("id") or ""), float(req.get("size_cm") or 0))
                res = {"ok": True, "material": mat, "log": _t("ag.lib_got", mat["name"])}
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": _t("lm.error", e)}
        WF.status(cfg, rigged, "_" + req["action"]).write_text(json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
    if req.get("action") in ("ai_models", "ai_price"):   # OpenRouter's image models (that edit a picture), a model's price
        rigged = Path(req["rigged"])
        try:
            if req["action"] == "ai_models":
                cfg_model = cfg.get("openrouter_image_model") or ""
                ms = texgen_ai.models()
                res = {"ok": True, "models": [{"id": m["id"], "name": m["name"]} for m in ms], "log": _t("ag.ai_models", len(ms)),
                       "default": texgen_ai.DEFAULT, "has_key": bool(cfg.get("openrouter_key") or os.environ.get("OPENROUTER_API_KEY")),
                       "cfg_model": cfg_model}
            else:
                res = {"ok": True, "price": texgen_ai.price(str(req.get("model") or "")), "log": ""}
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": _t("lm.error", e)}
        WF.status(cfg, rigged, "_" + req["action"]).write_text(json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
    if req.get("action") in ("uv_info", "uv_put", "uv_open", "ai_texture"):   # answered in <stem>_<action>.wear.json
        rigged = Path(req["rigged"])
        try:
            res = uv_action(cfg, req)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": _t("lm.error", e)}
        WF.status(cfg, rigged, "_" + req["action"]).write_text(json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
    if req.get("action") == "decal_save":   # answered in <stem>_decal_<name>.wear.json
        rigged = Path(req["rigged"])
        try:
            res = save_decal(cfg, req)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": _t("lm.error", e)}
        name = re.sub(r"[^A-Za-z0-9_-]+", "_", str(req.get("name") or "")).strip("_")[:60]
        WF.status(cfg, rigged, f"_decal_{name}").write_text(json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
    if req.get("action") == "qa":   # answered in <stem>_qa_<item>.wear.json
        rigged = Path(req["rigged"])
        try:
            res = qa(cfg, req)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": _t("lm.error", e)}
        item = re.sub(r"[^A-Za-z0-9_-]+", "_", req.get("item") or "").strip("_")
        WF.status(cfg, rigged, f"_qa_{item}").write_text(
            json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
    if req.get("action") == "bake":   # answered in <stem>_bakeq_<item>.wear.json (the queue's state: <stem>_bake.wear.json)
        rigged = Path(req["rigged"])
        item = re.sub(r"[^A-Za-z0-9_-]+", "_", (req.get("job") or {}).get("item") or "stop").strip("_")
        try:
            res = bake(cfg, req)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": _t("lm.error", e)}
        WF.status(cfg, rigged, f"_bakeq_{item}").write_text(
            json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
    if req.get("action") == "remove":   # answered in <stem>_remove_<item>.wear.json
        rigged = Path(req["rigged"])
        item = re.sub(r"[^A-Za-z0-9_-]+", "_", req.get("item") or "").strip("_")
        for old in WF.status_dir(cfg, rigged).glob(f"{glob.escape(LM._stem(rigged))}_remove_*.wear.json"):   # the answers to earlier ones: read
            old.unlink(missing_ok=True)
        try:
            res = remove_piece(cfg, rigged, item)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": _t("lm.error", e)}
        WF.status(cfg, rigged, f"_remove_{item}").write_text(
            json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
    if req.get("action") == "made_preview":   # answered in <stem>_helmet_<style>.wear.json
        rigged = Path(req["rigged"])
        try:
            res = made_preview(cfg, req)
        except Exception as e:  # noqa: BLE001
            res = {"ok": False, "log": _t("lm.error", e)}
        WF.status(cfg, rigged, f"_helmet_{req.get('style')}").write_text(
            json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
    if req.get("action") not in (None, "generate"):   # a page newer than this code (the app not restarted after an update)
        res = {"ok": False, "log": _t("ag.unknown_action", req.get("action"))}
        if req.get("rigged"):   # (answered where most actions are: the page stops waiting)
            WF.status(cfg, Path(req["rigged"]), "_" + re.sub(r"[^A-Za-z0-9_-]+", "_", str(req["action"]))).write_text(
                json.dumps({"id": req.get("id"), **res}, ensure_ascii=False), encoding="utf-8")
        return res["log"], None
    rigged = Path(req["rigged"])
    item = re.sub(r"[^A-Za-z0-9_-]+", "_", req.get("item") or "").strip("_") or f"proc_{req.get('piece')}"
    try:
        res = generate(cfg, req)
    except Exception as e:  # noqa: BLE001  (the page must hear back, or it waits for minutes)
        res = {"ok": False, "log": _t("lm.error", e)}
    WF.status(cfg, rigged, f"_wear_{item}").write_text(
        json.dumps({"id": req.get("id"), **{k: v for k, v in res.items() if k != "shots"}}, ensure_ascii=False), encoding="utf-8")
    return res["log"], res.get("shots")


def _frame(page):
    return ('<iframe srcdoc="%s" style="width:100%%;height:max(780px,86vh);border:0;border-radius:10px"></iframe>'
            % _html.escape(page, quote=True))


def mount(config_loader, char=None, tab=None, active=None):
    """char: the app's current character (its model with a skeleton); without it the tab has its own choice. tab: this
    tab, active: the label of the tab shown: the editor (a heavy 3D page) opens when the tab is entered, and on a new
    character only while the tab is shown (else it goes, not to run hidden)."""
    cfg0 = config_loader()
    gr.Markdown(_t("ag.intro"))
    with gr.Row():
        rig = gr.Dropdown(characters(cfg0), value=(characters(cfg0) or [(None, None)])[0][1], label=_t("ag.character"), scale=4,
                          visible=char is None, allow_custom_value=True)
        refresh = gr.Button(_t("ui.refresh"), scale=1, visible=char is None)
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
        return _frame(editor_page(Path(r), Path(config_loader()["export_dir"]) / "decals"))

    def run(text):
        try:
            return handle(config_loader(), text)
        except Exception as e:  # noqa: BLE001
            return _t("lm.error_2") + str(e), None

    refresh.click(lambda: gr.update(choices=characters(config_loader())), None, rig)
    open_btn.click(open_editor, rig, editor)
    if char is not None:   # the current character: on it as soon as the tab is seen
        opened = gr.State("")
        here = _t("ui.equipment_procedural")
        ok = lambda r: LM.is_rig(r)  # noqa: E731  (any skeleton: from the markup or the auto-rigger)
        char.change(lambda r, act: (r, open_editor(r) if ok(r) else _t("ag.choose_a_character"), r) if act == here else (r, "", ""),
                    [char, active], [rig, editor, opened], show_progress="hidden")
        tab.select(lambda r, op: (open_editor(r) if ok(r) else _t("ag.choose_a_character"), r) if r != op else (gr.update(), op),
                   [char, opened], [editor, opened], show_progress="hidden")
    go.click(lambda: _t("ag.working"), None, log).then(run, req, [log, shots], concurrency_id="armour_gen", concurrency_limit=1,
                                                         show_progress="minimal")
