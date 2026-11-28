"""«Models → Improve»: a draft made closer to its pictures before release (the work itself: tool/model_improve.py).

The step's panel reads status(); «Improve» and «Draw the sides (ChatGPT)» run as queued tasks (gpu=False: the CPU and
Blender's CPU bake, Codex in the cloud - they still wait their turn so two heavy jobs never share the laptop); the pins
editor reads align() (the picture, the model drawn from the fitted camera) and saves pins(); pictures and Codex
candidates are switched per view. The draft's own GLB is replaced in place (Check / Release see it as it is), the
generator's file kept in work_dir/improve/<category>/<name>/before.glb for «Undo»."""
import time
from pathlib import Path

import model_improve as MI
import sf3d_tool as T
from models import drafts_root
from tasks import Task

VIEW_KEY = {"front": "web.imp_front", "back": "web.imp_back", "left": "web.imp_left", "right": "web.imp_right"}


def _draft(cat: str, stem: str):
    cfg = T.load_config()
    d = drafts_root(cfg) / cat / stem
    if not (d / f"{stem}.glb").exists():
        raise FileNotFoundError(f"no draft {cat}/{stem}")
    return cfg, d


def status(cat: str, stem: str) -> dict:
    cfg, d = _draft(cat, stem)
    return MI.status(cat, stem, cfg, d)


def _logger(task, lines):
    names = {"A": "web.imp_log_project", "D": "web.imp_log_relief", "C/D": "web.imp_log_blender",
             "A (for the render)": "web.imp_log_project"}

    def say(msg):
        from i18n import t as _t
        key = names.get(msg)
        if msg.startswith("fit "):
            txt = _t("web.imp_log_fit", _t(VIEW_KEY.get(msg[4:], msg[4:])))
        elif msg.startswith("Codex "):
            txt = _t("web.imp_log_codex", _t(VIEW_KEY.get(msg[6:], msg[6:])))
        else:
            txt = _t(key) if key else msg
        lines.append(f"{time.strftime('%H:%M:%S')}  {txt}")
        task.set_lines(lines)
    return say


def run_task(p: dict) -> Task:
    cat, stem = p.get("category") or "", p.get("stem") or ""
    opts = {k: p.get(k) for k in ("project", "mirror", "sharp", "delight", "sym", "relief") if k in p}

    def run(task):
        cfg, d = _draft(cat, stem)
        lines = []
        say = _logger(task, lines)
        r = MI.run(cat, stem, cfg, d, opts, log=say)
        from i18n import t as _t
        lines.append(_t("web.imp_done", r["seconds"]["total"]))
        task.set_lines(lines)
        return {"category": cat, "stem": stem, "improved": r}
    return Task("improve", f"{stem}", run, gpu=False, meta={"category": cat, "stem": stem})


def codex_task(p: dict) -> Task:
    cat, stem = p.get("category") or "", p.get("stem") or ""
    views = [v for v in (p.get("views") or []) if v in MI.VIEWS]

    def run(task):
        cfg, d = _draft(cat, stem)
        lines = []
        say = _logger(task, lines)
        r = MI.codex_sides(cat, stem, cfg, d, views, log=say)
        return {"category": cat, "stem": stem, "codex": r}
    return Task("improve_codex", f"ChatGPT · {stem}", run, gpu=False, meta={"category": cat, "stem": stem})


def align(cat: str, stem: str, view: str) -> dict:
    cfg, d = _draft(cat, stem)
    return MI.align(cat, stem, cfg, d, view)


def pins(cat: str, stem: str, view: str, pin_list: list, marks=None, brush=None) -> dict:
    """the view's free pins, (when given) its landmarks' picture points {name: [x, y]} and a skin's brush strokes"""
    cfg, _ = _draft(cat, stem)
    MI.set_pins(cat, stem, cfg, view, pin_list)
    if marks is not None:
        MI.set_marks(cat, stem, cfg, view, marks)
    if brush is not None:
        MI.set_brush(cat, stem, cfg, view, brush)
    return status(cat, stem)


def mark3d(cat: str, stem: str, view: str, name: str, x: float, y: float, mirror: bool) -> dict:
    """a landmark's model point moved in one view -> that view's editor data again"""
    cfg, d = _draft(cat, stem)
    return MI.set_mark3d(cat, stem, cfg, d, view, name, float(x), float(y), bool(mirror))


def picture(cat: str, stem: str, view: str, path) -> dict:
    cfg, _ = _draft(cat, stem)
    MI.set_picture(cat, stem, cfg, view, path)
    return status(cat, stem)


def codex_accept(cat: str, stem: str, view: str, accept: bool) -> dict:
    cfg, _ = _draft(cat, stem)
    MI.codex_accept(cat, stem, cfg, view, accept)
    return status(cat, stem)


def undo(cat: str, stem: str) -> dict:
    cfg, d = _draft(cat, stem)
    ok = MI.undo(cat, stem, cfg, d)
    return {"ok": ok, **status(cat, stem)}
