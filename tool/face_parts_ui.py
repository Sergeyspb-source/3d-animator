"""Gradio panel: the shared procedural eyes, teeth and tongue (tool/blender_face_parts.py)."""
import contextlib
import json
import re
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


def generate(cfg, name, iris, pupil, slit, sclera_yel, veins, per_side, missing, missing_rand, yellow, crooked, fangs,
             tongue_col, seed, eye_style=_t("face.realistic"), iris_size=0, t_height=1.0, t_volume=1.0, canines=True):
    name = re.sub(r"[^\w.-]+", "_", (name or "face_parts").strip()) or "face_parts"
    out = Path(cfg["export_dir"]) / "face_parts" / name
    out.mkdir(parents=True, exist_ok=True)
    white, yel = [0.93, 0.91, 0.87], [0.95, 0.86, 0.55]
    sclera = [w + (y - w) * float(sclera_yel) for w, y in zip(white, yel)]
    job = {"out_dir": str(out), "seed": int(seed),
           "eye": {"iris": _rgb(iris), "pupil": float(pupil), "slit": bool(slit), "sclera": sclera, "veins": float(veins),
                   "style": "anime" if eye_style == _t("face.anime") else "real", **({"iris_size": float(iris_size)} if iris_size else {})},
           "teeth": {"per_side": int(per_side), "missing": missing or "", "missing_random": float(missing_rand),
                     "yellow": float(yellow), "crooked": float(crooked), "fangs": float(fangs),
                     "height": float(t_height), "volume": float(t_volume), "canines": bool(canines)},
           "tongue": {"colour": _rgb(tongue_col)}}
    (out / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_face_parts.py"), "--", str(out / "job.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    line = next((x for x in r.stdout.splitlines() if x.startswith("FACE_PARTS_OK")), None)
    if not line:
        return _t("face.failed") + (r.stdout + r.stderr)[-1500:], None, None
    info = json.loads(line.split(" ", 1)[1])
    msg = (_t("face.done_eyes_radius_mm_teeth_per_half", out, info['eye_radius'] * 1000, info['teeth_per_side'], ', '.join(info['missing']) or 'нет', ' + случайные' if float(missing_rand) else ''))
    return msg, str(out / "preview.png"), [str(out / f) for f in ("eyes.glb", "teeth.glb", "tongue.glb", "parts.json")]


def mount(config_loader, accordion=True):
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
        with gr.Row():
            log = gr.Textbox(label=_t("face.progress"), lines=4, interactive=False)
            pic = gr.Image(label=_t("face.preview"), type="filepath", height=260)
        files = gr.File(label=_t("face.files"), file_count="multiple", interactive=False)
        go.click(lambda *a: generate(config_loader(), *a),
                 [name, iris, pupil, slit, sclera, veins, per, missing, mrand, yellow, crooked, fangs, tongue, seed,
                  eye_style, iris_size, t_height, t_volume, canines],
                 [log, pic, files], concurrency_id="face_parts", concurrency_limit=1)
