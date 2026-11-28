"""«Models» chain of the web UI: picture -> model (SF3D / Hunyuan3D / TRELLIS.2) -> check -> release.

The generators are the app's own (sf3d_ui.generate, generate_hy, generate_trellis): called with the same
arguments its tab gives them. One difference: a model is made as a DRAFT - the run sees export_dir pointed at
<work_dir>/web_drafts/export (a thread-local config override), and «Release» moves the draft's folder into the real
export (a model there already is moved aside to web_drafts/replaced, never deleted)."""
import json
import shutil
import threading
import time
from pathlib import Path

import sf3d_tool as T
import sf3d_ui as UI
from i18n import t as _t

# ------------------------------------------------------------------ config: test copies and the draft override
_tls = threading.local()
_load = T.load_config
ENV_OVER = {}   # export_dir / work_dir from SF3D_EXPORT_DIR / SF3D_WORK_DIR (the test bench: never the user's export)


def load_config(*a, **k):
    c = dict(_load(*a, **k))
    c.update(ENV_OVER)
    c.update(getattr(_tls, "over", None) or {})
    return c


T.load_config = load_config   # (every module reads it as T.load_config(): sf3d_ui, armour_gen_ui, landmarks ...)


class config_override:
    def __init__(self, **over):
        self.over = over

    def __enter__(self):
        self.prev = getattr(_tls, "over", None)
        _tls.over = {**(self.prev or {}), **self.over}

    def __exit__(self, *exc):
        _tls.over = self.prev


def drafts_root(cfg=None) -> Path:
    cfg = cfg or T.load_config()
    return Path(cfg["work_dir"]) / "web_drafts" / "export"


# ------------------------------------------------------------------ choices: values and their text keys
CATEGORY_KEYS = {"item": "ui.inventory_item", "prop": "ui.prop_environment", "building": "ui.building",
                 "character": "ui.character", "vegetation": "ui.vegetation_trees_bushes_grass"}
PIVOTS = {"auto": ("ui.auto_by_category", None), "bottom": ("ui.at_the_base", "bottom"), "center": ("ui.at_the_centre", "center")}
COLLISIONS = {"auto": ("ui.by_category", None), "none": ("ui.none", "none"), "convex": ("ui.convex_hull_items_props", "convex"),
              "simplified": ("ui.simplified_mesh_buildings", "simplified")}
NAMINGS = {"mixamo": "lm.mixamo_for_mixamo_animations", "godot": "lm.godot_humanoid_profile"}
VEG = {"tree": "mat.wood", "bush": "ui.bush", "grass": "ui.grass_flowers"}
ENGINES = {"sf3d": "ui.sf3d_one_picture_about_20_seconds", "hunyuan": "ui.hunyuan3d_1_4_pictures_the_best",
           "trellis": "ui.trellis_one_picture"}


def _label(table: dict, value):
    """The label (in the process's language) that maps to value in one of sf3d_ui's label tables."""
    return next(k for k, v in table.items() if v == value)


def engines_ready(cfg) -> dict:
    """Which engines can run here, and why not."""
    tr_exe = Path(cfg.get("trellis_exe") or UI.TRELLIS_EXE)
    tr_models = Path(cfg.get("trellis_models") or UI.TRELLIS_MODELS)
    tr_missing = [w for w in UI.TRELLIS_WEIGHTS if not (tr_models / f"{w}.gguf").exists()]
    return {"sf3d": {"ok": True},
            "hunyuan": {"ok": Path(UI.HY_PY).exists(), "why": "" if Path(UI.HY_PY).exists() else UI.HY_PY},
            "trellis": {"ok": tr_exe.exists() and not tr_missing,
                        "why": "" if tr_exe.exists() and not tr_missing else (str(tr_exe) if not tr_exe.exists() else ", ".join(tr_missing))}}


def options(cfg) -> dict:
    """Everything the «Create a model» panel needs: choices with their text keys, presets, defaults."""
    cats = [k for k in cfg["categories"] if k in CATEGORY_KEYS]
    return {
        "engines": [{"id": k, "key": v, **engines_ready(cfg)[k]} for k, v in ENGINES.items()],
        "categories": [{"id": k, "key": CATEGORY_KEYS[k], "preset": cfg["categories"][k]} for k in cats],
        "pivots": [{"id": k, "key": v[0]} for k, v in PIVOTS.items()],
        "collisions": [{"id": k, "key": v[0]} for k, v in COLLISIONS.items()],
        "namings": [{"id": k, "key": v} for k, v in NAMINGS.items()],
        "veg": [{"id": k, "key": v} for k, v in VEG.items()],
        "hy_fast_categories": sorted(UI.HY_FAST_CATEGORIES),
        "defaults": {"foreground_ratio": cfg.get("foreground_ratio", 0.85), "trellis_color_match": UI.TRELLIS_COLOR_MATCH},
        "gpu_needs": {"sf3d": 6400, "hunyuan": 7000, "trellis": UI.TRELLIS_VRAM_MB},
    }


# ------------------------------------------------------------------ the generation task
def _num(p, k, d=0.0):
    try:
        return float(p.get(k, d) or 0)
    except (TypeError, ValueError):
        return d


def _progress(task):
    def progress(value, desc=None, *a, **k):   # the handlers' progress call: a fraction or (i, n)
        if isinstance(value, (tuple, list)) and len(value) == 2 and value[1]:
            task.set_progress(value[0] / value[1])
        elif isinstance(value, (int, float)):
            task.set_progress(value)
    return progress


def generate_task(p: dict):
    """The task's function for /api/models/generate: p is the panel's form (ids, not labels)."""
    def run(task):
        cfg = T.load_config()
        cat = p.get("category") or "prop"
        args = dict(category_label=UI.CATEGORY_LABELS[cat], name=(p.get("name") or "").strip(),
                    height=_num(p, "height"), width=_num(p, "width"), depth=_num(p, "depth"),
                    pivot_label=_label(UI.PIVOT_LABELS, PIVOTS[p.get("pivot") or "auto"][1]),
                    collision_label=_label(UI.COLLISION_LABELS, COLLISIONS[p.get("collision") or "auto"][1]),
                    override=bool(p.get("override")), metallic=_num(p, "metallic", 0.0), roughness=_num(p, "roughness", 0.8),
                    overwrite=bool(p.get("overwrite")), make_preview=bool(p.get("preview", True)),
                    color_match=_num(p, "color_match"), saturation=_num(p, "saturation", 1.0) or 1.0,
                    brightness=_num(p, "brightness", 1.0) or 1.0, auto_materials=bool(p.get("auto_materials")),
                    auto_rig=bool(p.get("auto_rig")) and cat == "character",
                    rig_naming_label=_label(UI.RIG_NAMINGS, p.get("naming") or "mixamo"), rig_tries=int(_num(p, "rig_tries", 3) or 3))
        if cat == "vegetation":
            UI.VEG_STATE["kind"] = p.get("veg") or "tree"
        engine = p.get("engine") or "sf3d"
        files = [f for f in (p.get("files") or []) if f]
        with config_override(export_dir=str(drafts_root(cfg))):
            if engine == "trellis":
                gen = UI.generate_trellis(files, **args, tr_faces=int(_num(p, "tr_faces", 50000)), tr_seed=int(_num(p, "tr_seed", 42)),
                                           tr_res=int(_num(p, "tr_res", 0)) or None)
            elif engine == "hunyuan":
                v = p.get("views") or {}
                gen = UI.generate_hy(v.get("front"), v.get("back"), v.get("left"), v.get("right"), **args,
                                     hy_tex=int(_num(p, "hy_tex", 2048)), hy_faces=int(_num(p, "hy_faces", 50000)),
                                     hy_steps=int(_num(p, "hy_steps", 50)), paint=bool(p.get("paint", True)),
                                     hy_fast=bool(p.get("hy_fast")))
            else:
                gen = UI.generate(files, **args, tex_res=int(_num(p, "tex_res", 1024)),
                                  fg_ratio=_num(p, "fg_ratio", 0.85), remove_bg=bool(p.get("remove_bg", True)),
                                  remesh=p.get("remesh") or "none", progress=_progress(task))
            made, last = [], None
            try:
                for log_text, results, last_glb, _previews in gen:
                    task.set_lines(log_text.split("\n"))
                    made, last = results, last_glb
                    task.result = {"made": [r[0] for r in made], "category": cat, "last": last}
            finally:
                gen.close()
            if engine == "sf3d" and not any(t.meta.get("engine") == "sf3d" for t in task.queue.waiting()):
                UI.unload_model()   # (parked in RAM: the next SF3D job brings it back in seconds, others get the card)
        return {"made": [r[0] for r in made], "category": cat, "last": last,
                "drafts": [d for d in drafts(cfg) if d["stem"] in {r[0] for r in made}]}
    return run


# ------------------------------------------------------------------ drafts and released models
def source_work(src) -> Path | None:
    """The generation's work folder from a model's <name>.json «source»: the source picture's folder, or the folder
    itself (Hunyuan from several views writes its work folder there, not a picture)."""
    if not src:
        return None
    src = Path(src)
    return src if src.is_dir() else src.parent


def _info(folder: Path, cat: str, draft: bool) -> dict | None:
    stem = folder.name
    glb = folder / f"{stem}.glb"
    if not glb.exists():
        return None
    try:
        stats = json.loads((folder / f"{stem}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        stats = {}
    src = Path(stats["source"]) if stats.get("source") else None
    work = source_work(src)
    preview = work / "preview.png" if work and (work / "preview.png").exists() else None
    if src and src.is_dir():   # Hunyuan from several views: «source» is its work folder; the picture is the front view
        src = next((src / n for n in ("source_front.png", "view_front.png") if (src / n).exists()), None)
    icon = folder / f"{stem}_icon.png"
    rigged = folder / f"{stem}_rigged.glb"
    eng = str(stats.get("engine") or ("hunyuan" if work and "hunyuan" in work.parts else "sf3d")).lower()
    eng = "hunyuan" if eng.startswith("hunyuan") else "trellis" if eng.startswith("trellis") else eng
    peaks = [stats.get(k) for k in ("peak_vram_mb", "shape_peak_vram_mb", "texture_peak_vram_mb") if stats.get(k)]
    return {"stem": stem, "category": cat, "draft": draft, "glb": glb.as_posix(), "dir": folder.as_posix(),
            "time": glb.stat().st_mtime, "stats": stats,
            "faces": stats.get("faces"), "size_m": stats.get("size_m"),
            "seconds": stats.get("seconds") or stats.get("total_seconds"), "peak_vram_mb": max(peaks) if peaks else None,
            "engine": eng,
            "icon": icon.as_posix() if icon.exists() else None, "preview": preview.as_posix() if preview else None,
            "source": src.as_posix() if src and src.exists() else None,
            "rigged": rigged.as_posix() if rigged.exists() else None,
            "files": sorted(x.name for x in folder.iterdir() if x.is_file())}


def _scan(root: Path, draft: bool, cats) -> list:
    out = []
    for cat in cats:
        d = root / cat
        if d.is_dir():
            out += [x for x in (_info(f, cat, draft) for f in d.iterdir() if f.is_dir()) if x]
    return sorted(out, key=lambda x: -x["time"])


def drafts(cfg=None) -> list:
    cfg = cfg or T.load_config()
    real = Path(cfg["export_dir"])
    out = _scan(drafts_root(cfg), True, CATEGORY_KEYS)
    for d in out:
        d["in_export"] = (real / d["category"] / d["stem"] / f"{d['stem']}.glb").exists()
    return out


def released(cfg=None, limit=80) -> list:
    cfg = cfg or T.load_config()
    return _scan(Path(cfg["export_dir"]), False, CATEGORY_KEYS)[:limit]


def _aside(folder: Path, kind: str, cfg) -> Path:
    """Moves a folder into web_drafts/<kind>/<category>/<name>-<time> (nothing is deleted)."""
    dst = Path(cfg["work_dir"]) / "web_drafts" / kind / folder.parent.name / f"{folder.name}-{time.strftime('%Y%m%d-%H%M%S')}"
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(folder), str(dst))
    return dst


def release(cat: str, stem: str, replace: bool = False) -> dict:
    cfg = T.load_config()
    if cat not in CATEGORY_KEYS or not stem or "/" in stem or "\\" in stem or stem.startswith("."):
        return {"ok": False, "log": _t("web.bad_name")}
    src = drafts_root(cfg) / cat / stem
    dst = Path(cfg["export_dir"]) / cat / stem
    if not (src / f"{stem}.glb").exists():
        return {"ok": False, "log": _t("web.no_draft", stem)}
    old = None
    if dst.exists():
        if not replace:
            return {"ok": False, "exists": True, "log": _t("web.release_exists", f"{cat}/{stem}")}
        old = _aside(dst, "replaced", cfg)
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    # the post-processing's record (re-run later by «sf3d-tool post») points at the released model now
    try:
        stats = json.loads((dst / f"{stem}.json").read_text(encoding="utf-8"))
        pp = source_work(stats["source"]) / "pp_params.json"
        if Path(cfg["work_dir"]).resolve() not in pp.resolve().parents:   # (only this work_dir's own records)
            raise ValueError(pp)
        rec = json.loads(pp.read_text(encoding="utf-8"))
        rec["final"] = str(dst / f"{stem}.glb")
        pp.write_text(json.dumps(rec, indent=2, ensure_ascii=False), encoding="utf-8")
    except (OSError, ValueError, KeyError, TypeError):
        pass
    msg = _t("web.released", f"{cat}/{stem}", dst)
    if old:
        msg += " " + _t("web.released_old", old)
    return {"ok": True, "log": msg, "dir": dst.as_posix()}


def discard(cat: str, stem: str) -> dict:
    cfg = T.load_config()
    src = drafts_root(cfg) / cat / stem
    if cat not in CATEGORY_KEYS or not (src / f"{stem}.glb").exists() or src.parent.parent != drafts_root(cfg):
        return {"ok": False, "log": _t("web.no_draft", stem)}
    dst = _aside(src, "discarded", cfg)
    return {"ok": True, "log": _t("web.discarded", stem, dst)}


def release_all() -> dict:
    """Every draft not in export yet released (one already there is left as a draft, to be replaced by hand)."""
    done, kept = [], []
    for d in drafts():
        if d["in_export"]:
            kept.append(f"{d['category']}/{d['stem']}")
            continue
        r = release(d["category"], d["stem"])
        (done if r.get("ok") else kept).append(f"{d['category']}/{d['stem']}")
    return {"ok": True, "log": _t("web.released_all", len(done), ", ".join(kept) or "—"), "released": done, "kept": kept}
