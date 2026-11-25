"""«Creatures» in the web UI: the current creature's overview, its skeleton (UniRig, names, jaw; the markup viewer's
requests: the joints moved, the rest pose straightened, the jaw, the eyes), its clips (by body kind, own keyed ones,
the check, Godot), its colouring (variants, holes and normals mended) - the Gradio app's own functions (sf3d_ui,
creatures), long ones as tasks of the shared queue. The viewer and the colouring page are served as pages of their
own; their requests reach the shell's hidden fields as they reached Gradio's."""
import json
from datetime import datetime
from pathlib import Path

import sf3d_tool as T
import sf3d_ui as UI
import creatures as CR
from i18n import t as _t
from pages import inject


def _f(value: str) -> dict:
    f = UI._char_files(value)
    if not f:
        raise ValueError(_t("cr.none"))
    return f


def _when(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%d.%m.%Y %H:%M")


def overview(value: str) -> dict:
    f = _f(value)
    d, nm, r = f["dir"], f["name"], f["rigged"]
    sm = CR.summary(r) if r else {}
    clips = d / f"{nm}_clips.glb"
    try:
        n_clips = len(json.loads(Path(str(clips) + ".json").read_text(encoding="utf-8"))) if clips.exists() else 0
    except (OSError, ValueError):
        n_clips = 0
    paints = CR.paint_variants(d, nm) if r else {}
    return {"id": value, "name": nm, "dir": d.as_posix(),
            "source": f["source"].as_posix() if f["source"] else None, "rigged": r.as_posix() if r else None,
            "rig": ({"file": r.name, "when": _when(r), "bones": sm.get("bones", 0), "paws": sm.get("paws") or {},
                     "tail": sm.get("tail", 0), "head": bool(sm.get("head")), "jaw": bool(sm.get("jaw"))} if r else None),
            "humanoid": bool(r and CR.is_humanoid(r)),
            "clips": n_clips, "clips_file": clips.as_posix() if clips.exists() else None,
            "paints": [{"id": k, "title": (v or {}).get("title", k)} for k, v in (paints or {}).items()],
            "jaw_pictures": [str(p[0] if isinstance(p, (list, tuple)) else p) for p in CR.jaw_pictures(d, nm)],
            "files": [{"name": x.name, "when": _when(x)} for x in sorted(d.iterdir()) if x.is_file()]}


def add(path: str) -> dict:
    value = UI._add_model(path)
    if not value:
        return {"ok": False, "log": _t("ui.char_add_piece", Path(path).name)}
    f = UI._char_files(value)
    CR.mark(f["dir"], f["name"])
    return {"ok": True, "id": value}


# ------------------------------------------------------------------ jobs: generators of (log, model, pictures)
def _job(gen_fn, *args):
    def run(task):
        res = None
        gen = gen_fn(*args)
        try:
            for out in gen:
                task.set_lines(str(out[0] or "").split("\n"))
                if len(out) > 1 and isinstance(out[1], str) and out[1]:
                    res = {"model": out[1]}
                    task.result = res
        finally:
            gen.close()
        return res or {}
    return run


def rig_task(value):
    return _job(UI.creature_rig, value)


def straighten_task(value):
    return _job(UI.creature_straighten, value)


def restore_task(value):
    def run(task):
        log, model, _pics = UI.creature_steps(value, "restore")
        task.set_lines(str(log or "").split("\n"))
        return {"model": model if isinstance(model, str) else None}
    return run


def request_task(value, text):
    """The skeleton viewer's request: rebuild / rest / eyes / eyes_off / the jaw (creature_request)."""
    return _job(UI.creature_request, value, text)


def viewer_page(value: str) -> str:
    f = _f(value)
    r = f.get("rigged")
    if not r:
        raise ValueError(_t("cr.view_needs_skeleton"))
    return inject(CR.viewer_page(Path(r), title=f["name"], kind=_t("cr.kind_creature"), edit=CR.viewer_data(f["dir"], f["name"])))


# ------------------------------------------------------------------ clips
def clip_options(value: str) -> dict:
    f = _f(value)
    srcs = CR.clip_sources()
    had = CR.clips_had(f["dir"], f["name"])
    return {"sources": [{"id": k, "key": "cr.anim_src_" + k, "clips": names,
                         "picked": (had.get(k, []) if had is not None else (names if k in CR.CLIP_DEFAULT else []))}
                        for k, (_p, names) in srcs.items()]}


def animate_task(value, picks: dict):
    def run(task):
        keys = list(CR.clip_sources())
        res = None
        gen = UI.creature_animate(value, keys, [picks.get(k) or [] for k in keys])
        try:
            for log, _view in gen:
                task.set_lines(str(log or "").split("\n"))
        finally:
            gen.close()
        f = _f(value)
        clips = f["dir"] / f"{f['name']}_clips.glb"
        if clips.exists():
            res = {"model": clips.as_posix()}
        return res
    return run


def clips_page(value: str) -> str:
    f = _f(value)
    clips = f["dir"] / f"{f['name']}_clips.glb"
    if not clips.exists():
        raise ValueError(_t("cr.anim_view_none"))
    return inject(CR.viewer_page(clips, title=f["name"], kind=_t("cr.kind_creature"), edit={"play": "walk"}))


def check_task(value):
    def run(task):
        import clipcheck
        f = _f(value)
        glb = f["dir"] / f"{f['name']}_clips.glb"
        if not glb.exists():
            raise ValueError(_t("cr.anim_view_none"))
        cfg = T.load_config()
        task.set_lines([_t("cc.running", glb.name)])
        md = clipcheck.check(cfg, glb, Path(cfg["work_dir"]) / "clip_check")[0]
        task.set_lines(str(md).splitlines())
        return {"md": md}
    return run


def godot_task(value):
    def run(task):
        f = _f(value)
        log = CR.godot_view(T.load_config(), f["dir"], f["name"])
        task.set_lines(str(log or "").splitlines())
        return {"log": log}
    return run


# ------------------------------------------------------------------ colouring
def paint_page(value: str, current: str = "") -> str:
    f = _f(value)
    if not f.get("rigged"):
        raise ValueError(_t("cr.view_needs_skeleton"))
    return inject(CR.paint_page(f["dir"], f["name"], current))


def paint_task(value, text):
    def run(task):
        res, lines = None, []
        gen = UI.creature_paint_request(value, text)
        try:
            for log, _page in gen:
                task.set_lines(str(log or "").split("\n"))
        finally:
            gen.close()
        req = json.loads(text or "{}")
        cur = (req.get("variant") or CR.paint_slug(req.get("title") or "")) if req.get("action") == "save" else ""
        return {"variant": cur}
    return run


def mend_task(value, what):
    def run(task):
        f = _f(value)
        lines = []
        for line in CR.mend(f["dir"], f["name"], what):
            lines.append(str(line))
            task.set_lines(lines)
        return {}
    return run
