"""The menu's bottom in the web UI: batch processing (a folder of pictures into drafts), the video memory (who holds it,
closing a program), the settings (export folder, OpenRouter) - the app's own functions where they do not write
the config; the config is written here from the file as it is (never from the web server's overridden view of it)."""
import json
from pathlib import Path

import sf3d_tool as T
import sf3d_ui as UI
import models as M
from i18n import t as _t

CONFIG = T.ROOT / "config.json"


def batch_scan(root: str, category: str) -> dict:
    rows, info = UI.on_scan(root, UI.CATEGORY_LABELS.get(category, UI.CATEGORY_LABELS["prop"]))
    return {"rows": rows, "log": info}


def batch_task(p: dict):
    """The whole folder, one job after another, made as drafts (like «Make a model»): checked and released there."""
    def run(task):
        cfg = T.load_config()
        cat = p.get("category") or "prop"
        made = []
        with M.config_override(export_dir=str(M.drafts_root(cfg))):
            gen = UI.batch_run(p.get("root") or cfg.get("input_dir") or "", UI.CATEGORY_LABELS.get(cat, UI.CATEGORY_LABELS["prop"]),
                               bool(p.get("overwrite")), bool(p.get("preview", True)), bool(p.get("materials")),
                               bool(p.get("rig")), next((k for k, v in UI.RIG_NAMINGS.items() if v == (p.get("naming") or "mixamo")), None),
                               int(p.get("tries", 3)))
            try:
                for log, results, _last, _pics in gen:
                    task.set_lines(str(log or "").split("\n"))
                    made = [r[0] for r in results or []]
                    task.result = {"made": made}
            finally:
                gen.close()
        return {"made": made}
    return run


def gpu_holders() -> list:
    return UI.gpu_holders()


def gpu_close(pid: int, force: bool) -> dict:
    msg = UI.gpu_close_proc(int(pid), bool(force))[0]
    return {"log": msg}


def _read_config() -> dict:
    return json.loads(CONFIG.read_text(encoding="utf-8-sig")) if CONFIG.exists() else M._load()


def settings() -> dict:
    cfg = _read_config()
    return {"export_dir": cfg.get("export_dir", ""), "input_dir": cfg.get("input_dir", ""),
            "has_key": bool(cfg.get("openrouter_key")),
            "image_model": cfg.get("openrouter_image_model", "google/gemini-2.5-flash-image"),
            "text_model": cfg.get("openrouter_text_model", "google/gemini-2.5-flash"),
            "godot_exe": cfg.get("godot_exe", ""), "blender_exe": cfg.get("blender_exe", ""),
            "codex": _codex()}


def _codex():
    import refgen as RF
    return RF.codex_exe()


def openrouter_models() -> dict:
    """OpenRouter's public catalogue (no key needed), for the model fields: the ones that make pictures and the ones that
    read pictures and answer in text, ids with their names."""
    import urllib.request
    req = urllib.request.Request("https://openrouter.ai/api/v1/models", headers={"User-Agent": "sf3d-toolkit"})
    with urllib.request.urlopen(req, timeout=20) as r:
        data = json.loads(r.read().decode("utf-8")).get("data") or []
    image, text = [], []
    for m in data:
        arch = m.get("architecture") or {}
        ins, outs = arch.get("input_modalities") or [], arch.get("output_modalities") or []
        row = {"id": m.get("id"), "name": m.get("name") or m.get("id")}
        if "image" in outs:
            image.append(row)
        elif "image" in ins and "text" in outs:
            text.append(row)
    key = lambda r: r["id"] or ""
    return {"image": sorted(image, key=key), "text": sorted(text, key=key)}


def save_settings(p: dict, test_bench: bool) -> dict:
    if test_bench:
        return {"ok": False, "log": _t("web.settings_test_bench")}
    cfg = _read_config()
    if p.get("export_dir") is not None:
        d = str(p["export_dir"]).strip().strip('"')
        if not d:
            return {"ok": False, "log": _t("ui.the_export_folder_path_is_empty")}
        cfg["export_dir"] = d.replace("\\", "/")
    key = (p.get("key") or "").strip()
    if key:   # (the key is never sent back to the page: an empty field keeps the one saved)
        cfg["openrouter_key"] = key
    if p.get("image_model") is not None:
        cfg["openrouter_image_model"] = (p.get("image_model") or "").strip() or "google/gemini-2.5-flash-image"
    if p.get("text_model") is not None:
        cfg["openrouter_text_model"] = (p.get("text_model") or "").strip() or "google/gemini-2.5-flash"
    CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return {"ok": True, "log": _t("web.settings_saved")}
