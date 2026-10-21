"""Gradio panel: the shared procedural eyes, teeth and tongue (tool/blender_face_parts.py)."""
import contextlib
import json
import re
import subprocess
from pathlib import Path

import gradio as gr

ROOT = Path(__file__).resolve().parent


def _rgb(hex_or_rgb):
    """Gradio colour (#rrggbb or rgba(...)) -> [r, g, b] 0..1."""
    s = str(hex_or_rgb or "").strip()
    if s.startswith("#") and len(s) >= 7:
        return [int(s[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    m = re.findall(r"[\d.]+", s)
    return [float(x) / 255 for x in m[:3]] if len(m) >= 3 else [0.5, 0.5, 0.5]


def generate(cfg, name, iris, pupil, slit, sclera_yel, veins, per_side, missing, missing_rand, yellow, crooked, fangs,
             tongue_col, seed):
    name = re.sub(r"[^\w.-]+", "_", (name or "face_parts").strip()) or "face_parts"
    out = Path(cfg["export_dir"]) / "face_parts" / name
    out.mkdir(parents=True, exist_ok=True)
    white, yel = [0.93, 0.91, 0.87], [0.95, 0.86, 0.55]
    sclera = [w + (y - w) * float(sclera_yel) for w, y in zip(white, yel)]
    job = {"out_dir": str(out), "seed": int(seed),
           "eye": {"iris": _rgb(iris), "pupil": float(pupil), "slit": bool(slit), "sclera": sclera, "veins": float(veins)},
           "teeth": {"per_side": int(per_side), "missing": missing or "", "missing_random": float(missing_rand),
                     "yellow": float(yellow), "crooked": float(crooked), "fangs": float(fangs)},
           "tongue": {"colour": _rgb(tongue_col)}}
    (out / "job.json").write_text(json.dumps(job, indent=1), encoding="utf-8")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_face_parts.py"), "--", str(out / "job.json")],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    line = next((x for x in r.stdout.splitlines() if x.startswith("FACE_PARTS_OK")), None)
    if not line:
        return "Не получилось:\n" + (r.stdout + r.stderr)[-1500:], None, None
    info = json.loads(line.split(" ", 1)[1])
    msg = (f"Готово: {out}\nГлаза (радиус {info['eye_radius'] * 1000:.0f} мм), зубы ({info['teeth_per_side']} на половину "
           f"дуги, пропуски: {', '.join(info['missing']) or 'нет'}{' + случайные' if float(missing_rand) else ''}), язык.\n"
           "Размеры — реальные (метры); при установке в голову набор масштабируется под череп.")
    return msg, str(out / "preview.png"), [str(out / f) for f in ("eyes.glb", "teeth.glb", "tongue.glb", "parts.json")]


def mount(config_loader, accordion=True):
    with (gr.Accordion("Детали лица: глаза, зубы, язык (общий набор для всех моделей)", open=False) if accordion
          else contextlib.nullcontext()):
        gr.Markdown("Процедурные глаза (шар с роговицей и нарисованной радужкой), зубы с дёснами и язык. Один набор "
                    "подходит всем персонажам: при установке в голову он масштабируется. Пропуски зубов — номера от "
                    "середины дуги: `U2` — второй верхний, `L4` — четвёртый нижний, `3` — третий в обоих рядах.")
        with gr.Row():
            with gr.Column():
                name = gr.Textbox(value="goblin", label="Имя набора (папка export/face_parts/<имя>)")
                with gr.Row():
                    iris = gr.ColorPicker(value="#4d8033", label="Радужка")
                    tongue = gr.ColorPicker(value="#b8545c", label="Язык")
                pupil = gr.Slider(0.25, 0.7, value=0.42, step=0.01, label="Зрачок (доля радужки)")
                slit = gr.Checkbox(value=False, label="Вертикальный зрачок (существа)")
                sclera = gr.Slider(0, 1, value=0.0, step=0.05, label="Желтизна белка")
                veins = gr.Slider(0, 1, value=0.35, step=0.05, label="Сосуды на белке")
            with gr.Column():
                per = gr.Slider(4, 8, value=7, step=1, label="Зубов на половину дуги")
                missing = gr.Textbox(label="Выбитые зубы (например U2, L4)")
                mrand = gr.Slider(0, 0.6, value=0.0, step=0.05, label="Случайные пропуски (доля)")
                yellow = gr.Slider(0, 1, value=0.15, step=0.05, label="Желтизна зубов (1 — гнилые, коричневые)")
                crooked = gr.Slider(0, 1, value=0.2, step=0.05, label="Кривизна зубов")
                fangs = gr.Slider(0, 1, value=0.0, step=0.05, label="Длина клыков")
                seed = gr.Number(value=1, precision=0, label="Вариант (случайное зерно)")
                go = gr.Button("Сгенерировать набор", variant="primary")
        with gr.Row():
            log = gr.Textbox(label="Ход работы", lines=4, interactive=False)
            pic = gr.Image(label="Предпросмотр", type="filepath", height=260)
        files = gr.File(label="Файлы", file_count="multiple", interactive=False)
        go.click(lambda *a: generate(config_loader(), *a),
                 [name, iris, pupil, slit, sclera, veins, per, missing, mrand, yellow, crooked, fangs, tongue, seed],
                 [log, pic, files], concurrency_id="face_parts", concurrency_limit=1)
