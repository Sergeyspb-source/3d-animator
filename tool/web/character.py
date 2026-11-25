"""«Character» in the web UI: the current character's overview, its skeleton (UniRig / by landmarks, seams, body
parts, the pose and the fist, the bones and weights), weight repair and the Godot fitting room - all through the
Gradio app's own functions (sf3d_ui, landmarks, landmarks_ui, creatures, rwt_pipeline).

The three.js editors (landmark_editor.html, skeleton_view.html) are served as pages of their own with the shell's
look (adapters/forge.*); they write their markup into «the parent page's hidden field», which the shell keeps."""
import json
from datetime import datetime
from pathlib import Path

import sf3d_tool as T
import sf3d_ui as UI
import landmarks as LM
import landmarks_ui as LMU
import creatures as CR
from i18n import t as _t

from pages import inject


def _when(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime).strftime("%d.%m.%Y %H:%M")


def overview(value: str) -> dict | None:
    """What the character has, for the overview's cards: its files, the skeleton (which, bones, face), the clips, the
    pieces worn, the model the tools take."""
    f = UI._char_files(value)
    if not f:
        return None
    d: Path = f["dir"]
    rig = None
    for key in ("landmark", "auto"):
        p = f.get(key)
        if p:
            s = LM.rig_summary(p)
            rig = {"kind": key, "file": p.name, "when": _when(p), "bones": s.get("bones", 0), "mouth": s.get("mouth"),
                   "retopo": bool(s.get("retopo")), "eyes": bool(s.get("eyes")), "fingers": s.get("fingers"),
                   "face_edits": p.with_name(LM._stem(p) + "_face_edits.json").exists()}
            break
    speech, worn = UI._char_counts(f)
    clips = {}
    for suffix, key in (("_anim.glb", "procedural"), ("_fbx.glb", "mixamo")):
        p = d / f"{f['name']}{suffix}"
        if p.exists():
            n = None
            try:
                meta = json.loads(p.with_name(p.name + ".json").read_text(encoding="utf-8"))
                n = len(meta) if isinstance(meta, list) else len(meta.get("clips") or meta) if isinstance(meta, dict) else None
            except (OSError, ValueError):
                pass
            clips[key] = {"file": p.name, "when": _when(p), "count": n}
    hair = [x.name for x in (d / "clothes").glob("*.glb") if x.stem.split("_")[0] in ("hair", "beard", "brows", "lashes")
            and not x.name.endswith(".src.glb")] if (d / "clothes").is_dir() else []
    files = sorted((x for x in d.iterdir() if x.is_file()), key=lambda x: x.name)
    return {"id": value, "name": f["name"], "dir": d.as_posix(),
            "source": f["source"].as_posix() if f["source"] else None,
            "rigged": f["rigged"].as_posix() if f["rigged"] else None,
            "parts": f["parts"].as_posix() if f["parts"] else None,
            "rig": rig, "speech": speech, "worn": worn, "clips": clips, "hair": sorted(hair),
            "wardrobe": (Path(T.load_config()["work_dir"]) / "wardrobe").is_dir(),
            "files": [{"name": x.name, "when": _when(x), "kb": round(x.stat().st_size / 1024)} for x in files]}


def add(path: str) -> dict:
    src = Path(path)
    if UI.WF.is_piece_file(src):
        return {"ok": False, "log": _t("ui.char_add_piece", src.name)}
    value = UI._add_model(str(src))
    return {"ok": bool(value), "id": value, "log": value or ""}


def delete(value: str) -> dict:
    ok = UI._delete_model(value)   # (only a folder of export/character, checked there)
    return {"ok": bool(ok), "log": _t("web.char_deleted", value) if ok else _t("web.char_not_deleted", value)}


# ------------------------------------------------------------------ generator jobs of the Gradio app, as tasks
def gradio_job(gen_fn, *args):
    """A task's function from a Gradio generator yielding (log text, model path, ...)."""
    def run(task):
        last = None
        gen = gen_fn(*args)
        try:
            for out in gen:
                text, model = out[0], (out[1] if len(out) > 1 else None)
                task.set_lines(str(text or "").split("\n"))
                if model:
                    last = model
                    task.result = {"model": str(model)}
        finally:
            gen.close()
        return {"model": str(last) if last else None}
    return run


def naming_label(key: str) -> str:
    return next((k for k, v in UI.RIG_NAMINGS.items() if v == key), next(iter(UI.RIG_NAMINGS)))


def rig_task(value, naming="mixamo", tries=3):
    return gradio_job(UI.rig_run, None, value, naming_label(naming), int(tries))


def seams_task(value):
    return gradio_job(UI.seam_run, None, value)


def split_task(value):
    return gradio_job(UI.split_run, None, value)


# ------------------------------------------------------------------ skeleton by landmarks
def options() -> dict:
    cfg = T.load_config()
    opt = LMU._options(cfg)
    return {"naming": opt.get("naming", "mixamo"), "weld": opt.get("weld", True),
            "mouth": opt.get("mouth") if opt.get("mouth") in ("plate", "cut", "none") else "cut",
            "eyes": opt.get("eyes", True), "eye_colour": opt.get("eye_colour", True),
            "face_topo": bool(opt.get("face_topo", False)), "face_smooth": opt.get("face_smooth", 2), "kit": opt.get("kit", ""),
            "kits": [{"value": v, "label": lab} for lab, v in LMU._kit_choices(cfg, opt.get("kit", ""))]}


def save_options(o: dict) -> dict:
    cfg = T.load_config()
    keep = {k: o[k] for k in ("naming", "weld", "mouth", "eyes", "eye_colour", "face_topo", "face_smooth", "kit") if k in o}
    new = {**LMU._options(cfg), **keep}
    (Path(cfg["work_dir"]) / LMU.OPTIONS_FILE).write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
    return options()


def source(value: str) -> Path | None:
    return LM.source_path(None, value, T.load_config()["export_dir"])


def landmarks_page(value: str, mode: str = "markup", markup: str = "") -> str:
    """markup: the markup editor on the character's source (the unsaved markup kept by the shell, else the saved
    one); pose: the same after a build, on the fresh skeleton; view: the pose check of any skeleton (the fist)."""
    cfg = T.load_config()
    if mode == "view":
        rigged = (UI._char_files(value) or {}).get("rigged")
        if not rigged or not LM.is_rig(rigged):
            raise ValueError(_t("lm.rig_pose_needs_a_skeleton"))
        page = LM.editor_page(rigged, LM.rig_state(rigged), rigged, mode="view", target=LM.TARGET_ID + "_pose")
    else:
        src = source(value)
        if not src or not src.exists():
            raise ValueError(_t("lm.first_choose_a_model_in_block_1"))
        final, saved = LM.output_paths(src, cfg["export_dir"])
        if mode == "pose" and final.exists() and saved.exists():
            page = LM.editor_page(src, json.loads(saved.read_text(encoding="utf-8")), final, mode="pose")
        else:
            page = LM.editor_page(src, LM.initial_state(src, cfg["export_dir"], markup), final,
                                  eyes=LM.editor_eyes(cfg, (options().get("kit") or "").strip()))
    return inject(page)


def landmark_build_task(value: str, markup: str, o: dict):
    def run(task):
        cfg = T.load_config()
        src = source(value)
        if not src or not src.exists():
            raise ValueError(_t("lm.choose_a_model_first"))
        marks = LM.parse(markup)
        bad = LM.markup_mismatch(src, marks)   # the editor was open on another model
        if bad:
            raise ValueError(bad)
        lines, res = [], None
        for step in LM.build(src, marks, o.get("naming") or "mixamo", cfg, bool(o.get("weld", True)), o.get("mouth") or "cut",
                             bool(o.get("eyes", True)), (o.get("kit") or "").strip(), bool(o.get("face_topo")),
                             int(o.get("face_smooth", 2)), bool(o.get("eye_colour", True))):
            if isinstance(step, dict):
                res = {"model": str(step["glb"]), "landmarks": str(step["landmarks"]), "shots": [str(x) for x in step.get("images") or []]}
                task.result = res
            else:
                lines.append(str(step))
                task.set_lines(lines)
        return res
    return run


def keep_fist(value: str, markup: str) -> bool:
    src = source(value)
    return bool(src and src.exists() and LM.keep_fist(src, T.load_config()["export_dir"], markup))


def keep_rig_fist(value: str, markup: str) -> str:
    rigged = (UI._char_files(value) or {}).get("rigged")
    if rigged and LM.keep_rig_fist(Path(rigged), markup):
        return _t("lm.rig_pose_fist_kept", LM.rig_meta(Path(rigged)).name)
    return ""


def bones_page(value: str) -> str:
    rigged = (UI._char_files(value) or {}).get("rigged")
    if not rigged or not LM.is_rig(rigged):
        raise ValueError(_t("lm.rig_pose_needs_a_skeleton"))
    return inject(CR.viewer_page(Path(rigged), title=LM._stem(Path(rigged))))


# ------------------------------------------------------------------ weights, the fitting room
def weights_task(value: str, mesh="", group="", strength=1.0, size=1.0):
    from rwt_strings import TEXT as S

    def run(task):
        rigged = (UI._char_files(value) or {}).get("rigged")
        if not rigged:
            raise ValueError(S["missing"])
        from rwt_pipeline import run as rwt
        lines, res = [S["start"]], None
        task.set_lines(lines)
        for step, info in rwt(str(rigged), T.load_config(), mesh or "", group or "", float(strength), float(size)):
            if step == "done":
                out = Path(info["glb"]).parent
                lines.append(S["done"])
                res = {"model": (out / "model.glb").as_posix(), "files": [(out / n).as_posix() for n in ("model.glb", "review.blend", "report.json")]}
                task.result = res
            else:
                lines.append(S[{"extract": "extract", "solve": "apply", "apply": "apply"}[step]])
            task.set_lines(lines)
        return res
    return run


def wardrobe_task(value: str):
    def run(task):
        rigged = (UI._char_files(value) or {}).get("rigged")
        if not rigged:
            raise ValueError(_t("lm.rig_pose_needs_a_skeleton"))
        log = LM.wear(T.load_config(), json.dumps({"id": 0, "action": "wardrobe", "rigged": Path(rigged).as_posix()}))
        task.set_lines(str(log or "").splitlines())
        return {"log": log}
    return run
