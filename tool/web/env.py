"""«Environment» (surfaces, effects, dungeons, destructibles), «Models → Reference» and «Models → Model materials» in
the web UI: the app's own handlers (they give back a log and a gallery of pictures), called with the labels
their tabs used; long ones as tasks of the shared queue."""
import json
import types
from pathlib import Path

import sf3d_tool as T
import sf3d_ui as UI
from i18n import t as _t

# choices by id, their text keys (as the former Gradio tabs' labels)
PROVIDERS = [("codex", "ui.chatgpt_subscription_through_codex"), ("openrouter", "ui.openrouter_with_a_key_nano_banana")]
REF_CATS = [("item", "ui.item_weapon"), ("prop", "ui.environment_object"), ("building", "ui.building"),
            ("vegetation", "ui.plant_tree_bush_grass"), ("character", "ui.character_a_pose"), ("creature", "ui.creature_monster")]
FX = [("explosion", "ui.explosion_once"), ("smoke", "ui.smoke_once"), ("fire", "ui.fire_loop"), ("magic", "ui.magic_flash_once"),
      ("spark", "ui.spark_ember_one_frame")]
VIEWS = [("back", "ui.back"), ("left", "ui.left"), ("right", "ui.right")]


def _label(table: dict, value):
    return next(k for k, v in table.items() if v == value)


def options() -> dict:
    cfg = T.load_config()
    import refgen as RF
    ready = {"codex": bool(RF.codex_exe()), "openrouter": bool(cfg.get("openrouter_key"))}   # (whether each can work now)
    model = {"openrouter": cfg.get("openrouter_image_model", "google/gemini-2.5-flash-image")}
    return {"providers": [{"id": i, "key": k, "ok": ready[i], "model": model.get(i)} for i, k in PROVIDERS], "ref_cats": [{"id": i, "key": k} for i, k in REF_CATS],
            "fx": [{"id": i, "key": k} for i, k in FX], "views": [{"id": i, "key": k} for i, k in VIEWS],
            "materials": UI._mat_folders(), "kit_sample": UI._kit_sample(), "assets": UI._export_assets(),
            "mat_assets": UI._mat_assets(), "mat_choices": [{"id": k, "label": lab} for lab, k in UI.MAT_CHOICES],
            "has_key": bool(cfg.get("openrouter_key")), "style": dict(zip(("text", "refs"), UI.ref_style_load()))}


def _pics(g) -> list:
    out = []
    for p in g or []:
        if isinstance(p, (list, tuple)):
            out.append({"path": str(p[0]), "caption": str(p[1]) if len(p) > 1 and p[1] is not None else ""})
        elif isinstance(p, str):
            out.append({"path": p, "caption": ""})
    return out


def gallery_job(fn, *args, extra=None):
    """A task's function from a handler giving (log, gallery, ...) once or as a generator."""
    def run(task):
        res = {"pics": []}
        out = fn(*args)
        steps = out if isinstance(out, types.GeneratorType) else [out]
        try:
            for o in steps:
                task.set_lines(str(o[0] or "").split("\n"))
                if len(o) > 1 and isinstance(o[1], (list, tuple)):
                    res["pics"] = _pics(o[1])
                if extra:
                    res.update(extra(o))
                task.result = res
        finally:
            if isinstance(out, types.GeneratorType):
                out.close()
        return res
    return run


# ------------------------------------------------------------------ the jobs
def surface_task(p):
    return gallery_job(UI.surface_run, _label(UI.REF_PROVIDERS, p.get("provider") or "codex"), p.get("desc") or "",
                       p.get("own") or None, float(p.get("tile", 4)), float(p.get("strength", 1)), int(p.get("size", 1024)), p.get("name") or "")


def fx_flip_task(p):
    return gallery_job(UI.fx_flip_run, _label(UI.FX_KINDS, p.get("kind") or "explosion"), p.get("color") or "#ffffff",
                       int(p.get("grid", 8)), int(p.get("size", 128)), int(p.get("seed", 1)), float(p.get("speed", 1)), p.get("name") or "")


def fx_sprite_task(p):
    return gallery_job(UI.fx_sprite_run, _label(UI.REF_PROVIDERS, p.get("provider") or "codex"), p.get("desc") or "", p.get("name") or "")


def fx_scenes_task(_p):
    return gallery_job(UI.fx_build_scenes)


def kit_build_task(p):
    wall = p.get("wall") or "proc"
    return gallery_job(UI.kit_build, float(p.get("cell", 4)), float(p.get("height", 3)), int(p.get("seed", 1)),
                       UI.KIT_PROC if wall == "proc" else wall, p.get("floor"), p.get("wood"))


def kit_scene_task(p):
    return gallery_job(UI.kit_scene, p.get("plan") or UI._kit_sample(), bool(p.get("ceilings", True)))


def destr_task(p):
    return gallery_job(UI.destr_run, None, p.get("asset"), int(p.get("chunks", 14)), int(p.get("seed", 1)),
                       bool(p.get("auto", True)), p.get("color") or "#6b4a2e", float(p.get("mass", 20)),
                       float(p.get("health", 20)), float(p.get("burst", 3.5)), p.get("name") or "")


def asset_model(asset: str) -> str | None:
    """The model of «category/name»: the file its post-processing record writes (a draft too), else the export's."""
    _work, d = UI._mat_params(asset)
    if d and d.get("final") and Path(d["final"]).exists():
        return str(d["final"])
    return UI.preview_pick(None, asset)


# ------------------------------------------------------------------ reference pictures
def ref_task(p):
    return gallery_job(UI.ref_generate, _label(UI.REF_PROVIDERS, p.get("provider") or "codex"), p.get("obj") or "",
                       _label(UI.REF_CATEGORIES, p.get("cat") or "prop"), int(p.get("n", 1)), p.get("style_text") or "",
                       p.get("style_files") or None)


def ref_views_task(p):
    want = [_t(k) for i, k in VIEWS if i in (p.get("want") or [])]
    return gallery_job(UI.ref_views, _label(UI.REF_PROVIDERS, p.get("provider") or "codex"), p.get("front"), p.get("obj") or "",
                       _label(UI.REF_CATEGORIES, p.get("cat") or "prop"), p.get("style_text") or "", p.get("style_files") or None,
                       want, extra=lambda o: {"views": o[2] if len(o) > 2 and isinstance(o[2], dict) else {}})


def ref_describe(p) -> dict:
    text, note = UI.ref_describe(_label(UI.REF_PROVIDERS, p.get("provider") or "codex"), p.get("files") or None)
    return {"text": text if isinstance(text, str) else None, "log": note}


def ref_style_save(p) -> dict:
    return {"log": UI.ref_style_save(p.get("text") or "", p.get("files") or None)}


def ref_to_generator(cat: str) -> str:
    return UI.REF_TO_GEN.get(cat, "prop")


# ------------------------------------------------------------------ model materials (PBR by colour groups)
def mat_analyze(asset: str) -> dict:
    out = UI.mat_analyze(asset)
    img, note, groups = out[0], out[1], out[2:]
    path = None
    if img is not None:
        from PIL import Image
        import numpy as np
        d = Path(T.load_config()["work_dir"]) / "web_tmp"
        d.mkdir(parents=True, exist_ok=True)
        path = d / f"mat_overlay_{T.slug(asset)}.png"
        (img if hasattr(img, "save") else Image.fromarray(np.asarray(img))).save(path)
    gs = [{"value": g.get("value"), "label": g.get("label", "")} for g in groups if isinstance(g, dict) and g.get("visible")]
    return {"overlay": path.as_posix() if path else None, "log": note, "groups": gs}


def mat_apply_task(asset: str, values: list):
    def run(task):
        status, final, previews = UI.mat_apply(asset, *values)
        task.set_lines(str(status or "").split("\n"))
        return {"model": final, "pics": _pics(previews)}
    return run
