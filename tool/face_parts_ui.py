"""Gradio panel: the shared procedural eyes, teeth and tongue (tool/blender_face_parts.py)."""
import contextlib
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

import gradio as gr
from i18n import t as _t

ROOT = Path(__file__).resolve().parent


def _rgb(hex_or_rgb):
    """Gradio colour (#rrggbb or rgba(...)) -> [r, g, b] 0..1."""
    s = str(hex_or_rgb or "").strip()
    if s.startswith("#") and len(s) >= 7:
        return [int(s[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    m = re.findall(r"[\d.]+", s)
    return [float(x) / 255 for x in m[:3]] if len(m) >= 3 else [0.5, 0.5, 0.5]


def _job(seed, iris, pupil, slit, sclera_yel, veins, per_side, missing, missing_rand, yellow, crooked, fangs, tongue_col,
         eye_style, iris_size, t_height, t_volume, canines):
    white, yel = [0.93, 0.91, 0.87], [0.95, 0.86, 0.55]
    sclera = [w + (y - w) * float(sclera_yel) for w, y in zip(white, yel)]
    return {"seed": int(seed or 0), "preview_glb": True,
            "eye": {"iris": _rgb(iris), "pupil": float(pupil), "slit": bool(slit), "sclera": sclera, "veins": float(veins),
                    "style": "anime" if eye_style == _t("face.anime") else "real", **({"iris_size": float(iris_size)} if iris_size else {})},
            "teeth": {"per_side": int(per_side), "missing": missing or "", "missing_random": float(missing_rand),
                      "yellow": float(yellow), "crooked": float(crooked), "fangs": float(fangs),
                      "height": float(t_height), "volume": float(t_volume), "canines": bool(canines)},
            "tongue": {"colour": _rgb(tongue_col)}}


def _cache_dir(cfg, job):
    """The live view's folder for these settings: a set already made is shown at once, not rebuilt."""
    key = hashlib.sha1(json.dumps(job, sort_keys=True).encode()).hexdigest()[:16]
    return Path(cfg["work_dir"]) / "face_parts_preview" / key


def _prune(root, keep=40):
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)


def cached_preview(cfg, *a):
    """(picture, 3D) of an already made live view, or (None, None)."""
    out = _cache_dir(cfg, _job(*a))
    return ((str(out / "preview.png"), str(out / "preview.glb"))
            if (out / "preview.png").exists() and (out / "preview.glb").exists() else (None, None))


def _run(cfg, job, out):
    """Blender in the background; yields "glb" once the 3D is written, then ("ok", info) or ("fail", log)."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "job.json").write_text(json.dumps({"out_dir": str(out), **job}, indent=1), encoding="utf-8")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    p = subprocess.Popen([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_face_parts.py"), "--", str(out / "job.json")],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log = []
    for x in p.stdout:
        log.append(x)
        if x.startswith("FACE_PARTS_GLB"):
            yield "glb", None
        elif x.startswith("FACE_PARTS_OK"):
            p.wait()
            yield "ok", json.loads(x.split(" ", 1)[1])
            return
    p.wait()
    yield "fail", "".join(log)[-1500:]


def generate(cfg, name, iris, pupil, slit, sclera_yel, veins, per_side, missing, missing_rand, yellow, crooked, fangs,
             tongue_col, seed, eye_style=_t("face.realistic"), iris_size=0, t_height=1.0, t_volume=1.0, canines=True):
    """The set saved to export/face_parts/<name>."""
    name = re.sub(r"[^\w.-]+", "_", (name or "face_parts").strip()) or "face_parts"
    out = Path(cfg["export_dir"]) / "face_parts" / name
    job = _job(seed, iris, pupil, slit, sclera_yel, veins, per_side, missing, missing_rand, yellow, crooked, fangs, tongue_col,
               eye_style, iris_size, t_height, t_volume, canines)
    for kind, info in _run(cfg, job, out):
        if kind == "fail":
            return _t("face.failed") + info, None, None, None
        if kind == "ok":
            msg = (_t("face.done_eyes_radius_mm_teeth_per_half", out, info['eye_radius'] * 1000, info['teeth_per_side'], ', '.join(info['missing']) or 'нет', ' + случайные' if float(missing_rand) else ''))
            return msg, str(out / "preview.png"), [str(out / f) for f in ("eyes.glb", "teeth.glb", "tongue.glb", "parts.json")], str(out / "preview.glb")


def preview(cfg, *a):
    """The live view while the sliders move (work_dir, cached per settings): the 3D first, then the picture."""
    png, glb = cached_preview(cfg, *a)
    if png:
        yield _t("face.preview_updated"), png, glb
        return
    job = _job(*a)
    out = _cache_dir(cfg, job)
    for kind, info in _run(cfg, job, out):
        if kind == "glb":
            yield _t("face.preview_rendering"), gr.update(), str(out / "preview.glb")
        elif kind == "ok":
            yield _t("face.preview_updated"), str(out / "preview.png"), str(out / "preview.glb")
        else:
            shutil.rmtree(out, ignore_errors=True)
            yield _t("face.failed") + info, gr.update(), gr.update()
    _prune(out.parent)


def mount(config_loader, accordion=True, tab=None):
    with (gr.Accordion(_t("face.face_parts_eyes_teeth_tongue_one_set"), open=False) if accordion
          else contextlib.nullcontext()):
        gr.Markdown(_t("face.procedural_eyes_a_ball_with_a_cornea"))
        with gr.Row():
            with gr.Column():
                name = gr.Textbox(value="goblin", label=_t("face.set_name_folder_export_face_parts"))
                with gr.Row():
                    iris = gr.ColorPicker(value="#4d8033", label=_t("face.iris"))
                    tongue = gr.ColorPicker(value="#b8545c", label=_t("face.tongue"))
                eye_style = gr.Radio([_t("face.realistic"), _t("face.anime")], value=_t("face.realistic"), label=_t("face.eye_style"),
                                     info=_t("face.anime_a_large_even_iris_darker_at"))
                iris_size = gr.Slider(0, 70, value=0, step=1, label=_t("face.iris_size_0_by_the_style_32_50"))
                pupil = gr.Slider(0.25, 0.7, value=0.42, step=0.01, label=_t("face.pupil_share_of_the_iris"))
                slit = gr.Checkbox(value=False, label=_t("face.vertical_pupil_creatures"))
                sclera = gr.Slider(0, 1, value=0.0, step=0.05, label=_t("face.yellowness_of_the_white"))
                veins = gr.Slider(0, 1, value=0.35, step=0.05, label=_t("face.veins_on_the_white"))
            with gr.Column():
                per = gr.Slider(4, 8, value=7, step=1, label=_t("face.teeth_per_half_arch"))
                missing = gr.Textbox(label=_t("face.missing_teeth_e_g_u2_l4"))
                mrand = gr.Slider(0, 0.6, value=0.0, step=0.05, label=_t("face.random_gaps_share"))
                yellow = gr.Slider(0, 1, value=0.15, step=0.05, label=_t("face.teeth_yellowness_1_rotten_brown"))
                crooked = gr.Slider(0, 1, value=0.2, step=0.05, label=_t("face.teeth_crookedness"))
                t_height = gr.Slider(0.5, 1.6, value=1.0, step=0.05, label=_t("face.teeth_height"))
                t_volume = gr.Slider(0, 1, value=1.0, step=0.05, label=_t("face.teeth_volume"),
                                     info=_t("face.0_a_solid_white_strip_1_separate"))
                canines = gr.Checkbox(value=True, label=_t("face.fangs_off_fangs_like_incisors"))
                fangs = gr.Slider(0, 1, value=0.0, step=0.05, label=_t("face.fang_length"))
                seed = gr.Number(value=1, precision=0, label=_t("face.variant_random_seed"))
                go = gr.Button(_t("face.generate_the_set"), variant="primary")
        args = [name, iris, pupil, slit, sclera, veins, per, missing, mrand, yellow, crooked, fangs, tongue, seed,
                eye_style, iris_size, t_height, t_volume, canines]
        live = [seed, iris, pupil, slit, sclera, veins, per, missing, mrand, yellow, crooked, fangs, tongue,
                eye_style, iris_size, t_height, t_volume, canines]
        png0, glb0 = cached_preview(config_loader(), *(c.value for c in live))   # the default set, if made before
        with gr.Row():
            pic = gr.Image(png0, label=_t("face.preview"), type="filepath", height=300)
            view = gr.Model3D(glb0, label=_t("face.preview_3d"), height=300, clear_color=(0.75, 0.74, 0.72, 1), camera_position=(90, 75, 0.15))
        log = gr.Textbox(label=_t("face.progress"), lines=3, interactive=False)
        files = gr.File(label=_t("face.files"), file_count="multiple", interactive=False)
        go.click(lambda *a: generate(config_loader(), *a),
                 args, [log, pic, files, view], concurrency_id="face_parts", concurrency_limit=1)
        # the live view: remade while a slider moves or a choice changes (the newest request wins; seen settings are cached)
        def remake(*a):
            yield from preview(config_loader(), *a)
        live_kw = dict(fn=remake, inputs=live, outputs=[log, pic, view],
                       concurrency_id="face_parts", concurrency_limit=1, trigger_mode="always_last", show_progress="minimal")
        for c in live:
            (c.input if isinstance(c, (gr.ColorPicker, gr.Textbox, gr.Number)) else c.change)(**live_kw)
        if tab is not None:   # the current settings shown as soon as the tab is opened (the first time they are built)
            tab.select(**live_kw)
