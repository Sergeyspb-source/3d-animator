"""Gradio panel: skeleton from hand-placed landmarks (the editor page writes its JSON into a textbox here)."""
import html as _html
import json
from pathlib import Path

import gradio as gr

import landmarks as LM

NAMINGS = {"Mixamo (под анимации из Mixamo)": "mixamo", "Godot (профиль Humanoid)": "godot"}


def _frame(page):
    return ('<iframe srcdoc="%s" style="width:100%%;height:720px;border:0;border-radius:10px"></iframe>'
            % _html.escape(page, quote=True))


def mount(config_loader, asset, upload):
    """asset / upload: the model pickers of the rigging tab, reused here."""
    with gr.Accordion("Скелет по ориентирам (вручную, как в Mixamo)", open=False):
        gr.Markdown(
            "Модель выбирается выше, в блоке **1. Модель**. Нажмите «Открыть разметку» и кликайте по модели на виде "
            "спереди: подбородок, пах, плечо, локоть, запястье, колено, щиколотка (при симметрии — только левая "
            "сторона персонажа, она справа на экране). Глубину узла программа находит сама, по толщине модели. "
            "Затем таз, позвоночник, шея, ключицы, бёдра и стопы рассчитываются автоматически, и любой узел можно "
            "выделить мышкой и сдвинуть или повернуть: стрелками в окне (G — перемещение, R — поворот) или "
            "числами, как в Blender. У локтей, коленей, запястий и щиколоток зелёный сектор показывает, куда сустав "
            "сгибается, красный — куда нет; поле «Сгиб» гнёт сустав точно по его оси. Справа вверху окна — схема-подсказка, "
            "где должен стоять выбранный узел (можно подложить свою картинку). Пальцы: кнопка «Разметить пальцы» — "
            "камера подъедет к кисти, кликните кончики пальцев (лишние отметьте «нет»), суставы рассчитаются сами. "
            "Лицо: «Разметить лицо» — центр глаза, уголок рта, середина рта; появятся челюсть и глаза. "
            "Рот для речи: пластина с ключами ARKit поверх губ или настоящий разрез с полостью, зубами и языком из "
            "набора «Детали лица» — ключи одинаковые, липсинк игры работает с обоими.")
        with gr.Row():
            open_btn = gr.Button("Открыть разметку", variant="secondary")
            naming = gr.Radio(list(NAMINGS), value=list(NAMINGS)[0], label="Имена костей")
            weld = gr.Checkbox(value=True, label="Сшить стыки между частями")
            mouth = gr.Radio([("Пластина (быстро, для дальних планов)", "plate"), ("Разрез: губы, полость, зубы, язык", "cut"),
                              ("Нет", "none")], value="plate", label="Рот для речи (если размечено лицо)")
            eyes = gr.Checkbox(value=True, label="Вставить глаза-шары (если обведены глаза)")
            ftopo = gr.Checkbox(value=False, label="Ретопология лица (эксперимент, только с «Разрез»)")
            fsmooth = gr.Slider(0, 3, value=2, step=1, label="Сглаживание сетки лица (0 — выкл.)")
            kit = gr.Dropdown(choices=[""], value="", label="Набор деталей лица (пусто — стандартный)", allow_custom_value=True)
        editor = gr.HTML()
        data = gr.Textbox(label="Разметка (заполняется редактором автоматически; можно вставить сохранённую)",
                          lines=2, max_lines=4, elem_id=LM.TARGET_ID)
        with gr.Row():
            ref_file = gr.File(label="Посмотреть готовую модель со скелетом: FBX (Mixamo, With Skin) или GLB",
                               file_types=[".fbx", ".glb"], type="filepath", scale=3)
            ref_btn = gr.Button("Открыть в просмотре: кости, веса, анимация", scale=1)
        with gr.Accordion("Липсинк реплики (для модели с ртом для речи)", open=False):
            gr.Markdown("Аудио реплики + её точный текст (из субтитров: Whisper путает имена) → клип `<имя>.face.json` "
                        "рядом с моделью. В игре его проигрывает `FaceCurvesPlayer`; здесь — кнопка «▶ Реплика» в режиме "
                        "«Поза». Инструменты берутся из игрового проекта (`lipsync_skills_dir` в config.json).")
            with gr.Row():
                ls_audio = gr.File(label="Голос (mp3, wav, ogg)", file_types=[".mp3", ".wav", ".ogg"], type="filepath")
                with gr.Column():
                    ls_text = gr.Textbox(label="Точный текст реплики (пусто — как услышит Whisper)", lines=2)
                    ls_lang = gr.Radio(["ru", "en"], value="ru", label="Язык")
                    ls_btn = gr.Button("Сделать клип липсинка")
            ls_log = gr.Textbox(label="Липсинк: ход работы", lines=5, interactive=False)
        go = gr.Button("Построить скелет и веса по разметке (около минуты, без видеокарты)", variant="primary")
        with gr.Row():
            with gr.Column():
                log = gr.Textbox(label="Ход работы", lines=7, interactive=False)
                files = gr.File(label="Результат", file_count="multiple", interactive=False)
            with gr.Column():
                view = gr.Model3D(label="Модель со скелетом", height=380, clear_color=(0.9, 0.9, 0.9, 1))
        shots = gr.Gallery(label="Проверка: покой, поза спереди, поза сбоку", columns=3, height=300)

        def open_editor(up, name, text):
            cfg = config_loader()
            src = LM.source_path(up, name, cfg["export_dir"])
            if not src or not src.exists():
                return '<div style="padding:16px">Сначала выберите модель в блоке «1. Модель» или загрузите GLB.</div>'
            return _frame(LM.editor_page(src, LM.initial_state(src, cfg["export_dir"], text),
                                         LM.output_paths(src, cfg["export_dir"])[0]))

        def run(up, name, text, nm, do_weld, do_mouth, do_eyes, kit_name, do_topo, smooth_lvl):
            cfg = config_loader()
            src = LM.source_path(up, name, cfg["export_dir"])
            lines = []
            if not src or not src.exists():
                yield "Сначала выберите модель.", None, None, None, gr.update()
                return
            try:
                marks = LM.parse(text)
                for step in LM.build(src, marks, NAMINGS[nm], cfg, do_weld, do_mouth, do_eyes, (kit_name or "").strip(), do_topo, smooth_lvl):
                    if isinstance(step, dict):  # reopen the editor in the pose mode on the fresh build
                        lines.append("Редактор открыт в режиме «Поза»: тяните мышью руки и ноги, чтобы проверить сгибы.")
                        state = json.loads(Path(step["landmarks"]).read_text(encoding="utf-8"))
                        yield ("\n".join(lines), step["glb"], [step["glb"], step["landmarks"]], step["images"],
                               _frame(LM.editor_page(src, state, Path(step["glb"]), mode="pose")))
                    else:
                        lines.append(step)
                        yield "\n".join(lines), None, None, None, gr.update()
            except Exception as e:  # shown to the user; details are in work/landmark_rig/*/blender.log
                lines.append("Ошибка: " + str(e))
                yield "\n".join(lines), None, None, None, gr.update()

        def open_view(path):
            if not path:
                return '<div style="padding:16px">Загрузите FBX или GLB со скелетом.</div>'
            try:
                glb, info = LM.viewable(Path(path), config_loader())
            except Exception as e:
                return f'<div style="padding:16px">Не удалось открыть: {_html.escape(str(e))}</div>'
            return _frame(LM.editor_page(glb, None, glb, mode="view"))

        def lipsync(up, name, audio, text, lang, state_text):
            import lipsync_link as LL
            cfg = config_loader()
            src = LM.source_path(up, name, cfg["export_dir"])
            if not src or not src.exists() or not audio:
                yield "Нужны модель (блок «1. Модель») и аудио.", gr.update()
                return
            rigged = LM.output_paths(src, cfg["export_dir"])[0]
            if not rigged.exists():
                yield "Сначала соберите скелет по разметке (с лицом и «Рот для речи»).", gr.update()
                return
            lines = []
            try:
                for step in LL.make_clip(Path(audio), text.strip(), lang, rigged, cfg):
                    if isinstance(step, dict):
                        lines.append(f"Готово: {step['clip']}. Откройте «Поза» → «▶ Реплика».")
                        yield "\n".join(lines), _frame(LM.editor_page(
                            src, LM.initial_state(src, cfg["export_dir"], state_text), rigged, mode="pose"))
                    else:
                        lines.append(step)
                        yield "\n".join(lines), gr.update()
            except Exception as e:
                lines.append("Ошибка: " + str(e))
                yield "\n".join(lines), gr.update()

        def kits():
            d = Path(config_loader()["export_dir"]) / "face_parts"
            names = sorted(p.name for p in d.iterdir() if (p / "eyes.glb").exists()) if d.exists() else []
            return gr.update(choices=[""] + names)

        open_btn.click(open_editor, [upload, asset, data], editor)
        open_btn.click(kits, None, kit)
        ls_btn.click(lipsync, [upload, asset, ls_audio, ls_text, ls_lang, data], [ls_log, editor], concurrency_id="lipsync",
                     concurrency_limit=1)
        ref_btn.click(open_view, ref_file, editor)
        go.click(run, [upload, asset, data, naming, weld, mouth, eyes, kit, ftopo, fsmooth], [log, view, files, shots, editor], concurrency_id="landmark_rig",
                 concurrency_limit=1)
