"""«Character → Face» in the web UI: the face marked and built on an auto-rig (a landmark rig gets its face with the
skeleton), the shared procedural eyes / teeth / tongue (face_parts_ui, live preview), the lip-sync lines (lipsync_link)
- the app's own functions; long ones are tasks of the shared queue."""
import json
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sf3d_tool as T
import sf3d_ui as UI
import landmarks as LM
import landmarks_ui as LMU
import face_parts_ui as FP
from i18n import t as _t
from pages import inject


def rigged_of(value: str) -> Path | None:
    r = (UI._char_files(value) or {}).get("rigged")
    return Path(r) if r else None


def state(value: str) -> dict:
    """What the Face step can do on this character: its skeleton's kind, the lines it has."""
    r = rigged_of(value)
    src = LM.source_path(None, value, T.load_config()["export_dir"])
    lm = LM.output_paths(src, T.load_config()["export_dir"])[0] if src and src.exists() else None
    return {"rigged": r.as_posix() if r else None, "landmark": bool(r and LM.is_landmark_rig(r)),
            "auto": bool(r and LM.is_rig(r) and not LM.is_landmark_rig(r)),
            "summary": LM.rig_summary(r) if r else {},
            "speech_model": lm.as_posix() if lm and lm.exists() else None,
            "clips": [c["name"] for c in LM.face_clips(lm)] if lm and lm.exists() else []}


# ------------------------------------------------------------------ the face on an auto-rig
def mark_page(value: str) -> str:
    r = rigged_of(value)
    if not r or not LM.is_rig(r):
        raise ValueError(_t("lm.rig_pose_needs_a_skeleton"))
    if LM.is_landmark_rig(r):
        raise ValueError(_t("lm.rig_face_landmark"))
    plain = r.with_name(LM._stem(r) + "_rigged.noface.glb")   # marked on the rig as it came
    return inject(LM.editor_page(plain if plain.exists() else r, LM.rig_face_state(r), r, target=LM.TARGET_ID + "_rigface"))


def build_task(value: str, markup: str):
    def run(task):
        r = rigged_of(value)
        if not r or not LM.is_rig(r) or LM.is_landmark_rig(r):
            raise ValueError(_t("lm.rig_face_landmark") if r and LM.is_landmark_rig(r) else _t("lm.rig_pose_needs_a_skeleton"))
        cfg = T.load_config()
        opt = LMU._options(cfg)
        marks = json.loads(markup) if (markup or "").strip() else LM.rig_face_state(r)
        lines, res = [], None
        for step in LM.build_face_on_rig(r, marks, cfg, (opt.get("kit") or "").strip(), bool(opt.get("eyes", True)),
                                         bool(opt.get("eye_colour", True)), int(opt.get("face_smooth", 1))):
            if isinstance(step, dict):
                res = {"model": str(step.get("glb")), "shots": [str(x) for x in step.get("images") or []]}
                task.result = res
            else:
                lines.append(str(step))
                task.set_lines(lines)
        return res
    return run


# ------------------------------------------------------------------ eyes, teeth, tongue
EYE_STYLES = {"real": "face.realistic", "anime": "face.anime"}


def _args(p: dict) -> list:
    """The panel's settings in face_parts_ui's order (seed first: its live view's)."""
    return [int(p.get("seed", 1) or 0), p.get("iris", "#4d8033"), float(p.get("pupil", .42)), bool(p.get("slit")),
            float(p.get("sclera", 0)), float(p.get("veins", .35)), int(p.get("per_side", 7)), str(p.get("missing", "") or ""),
            float(p.get("missing_rand", 0)), float(p.get("yellow", .15)), float(p.get("crooked", .2)), float(p.get("fangs", 0)),
            p.get("tongue", "#b8545c"), _t(EYE_STYLES.get(p.get("eye_style"), "face.realistic")), float(p.get("iris_size", 0)),
            float(p.get("t_height", 1)), float(p.get("t_volume", 1)), bool(p.get("canines", True))]


_preview_pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="face-preview")
_latest = {"n": 0}
_lock = threading.Lock()


def preview(p: dict) -> dict:
    """The live view for these settings: at once when made before, else made in Blender (a few seconds); a request
    overtaken by a newer one while waiting is skipped."""
    cfg = T.load_config()
    a = _args(p)
    png, glb = FP.cached_preview(cfg, *a)
    if png:
        return {"png": png, "glb": glb, "log": _t("face.preview_updated")}
    with _lock:
        _latest["n"] += 1
        n = _latest["n"]

    def make():
        if n != _latest["n"]:
            return {"skipped": True}
        last = {}
        for msg, pic, model in FP.preview(cfg, *a):
            last = {"log": msg, "png": pic if isinstance(pic, str) else last.get("png"), "glb": model if isinstance(model, str) else last.get("glb")}
        return last
    return _preview_pool.submit(make)


def save_task(p: dict, name: str):
    def run(task):
        a = _args(p)
        seed, rest = a[0], a[1:13]   # (generate takes the seed after the tongue's colour)
        log, png, files, glb = FP.generate(T.load_config(), name, *rest, seed, *a[13:])
        task.set_lines(str(log or "").splitlines())
        if not files:
            raise RuntimeError(str(log or ""))
        return {"png": png, "glb": glb, "files": files}
    return run


# ------------------------------------------------------------------ lip-sync lines
def say_page(value: str, clip: str) -> str:
    cfg = T.load_config()
    src = LM.source_path(None, value, cfg["export_dir"])
    if not src or not src.exists():
        raise ValueError(_t("lm.first_choose_a_model_in_block_1"))
    rigged = LM.output_paths(src, cfg["export_dir"])[0]
    if not rigged.exists():
        raise ValueError(_t("lm.build_the_skeleton_from_the_markup"))
    clips = [c["name"] for c in LM.face_clips(rigged)]
    if not clips:
        raise ValueError(_t("lm.no_lipsync_clips_yet"))
    clip = clip if clip in clips else max(clips, key=lambda c: (rigged.parent / f"{c}.face.json").stat().st_mtime)
    return inject(LM.editor_page(src, LM.initial_state(src, cfg["export_dir"], ""), rigged, mode="say", say=clip))


def lipsync_task(value: str, audio: str, text: str, lang: str):
    def run(task):
        import lipsync_link as LL
        cfg = T.load_config()
        src = LM.source_path(None, value, cfg["export_dir"])
        rigged = LM.output_paths(src, cfg["export_dir"])[0] if src else None
        if not rigged or not rigged.exists():
            raise ValueError(_t("lm.build_the_skeleton_from_the_markup"))
        lines, res = [], None
        for step in LL.make_clip(Path(audio), (text or "").strip(), lang or "ru", rigged, cfg):
            if isinstance(step, dict):
                lines.append(_t("lm.done_open_pose_line", step["clip"]))
                res = {"clip": Path(step["clip"]).name[:-len(".face.json")]}
                task.result = res
            else:
                lines.append(str(step))
            task.set_lines(lines)
        return res
    return run
