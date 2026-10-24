"""Gradio panel: skeleton from hand-placed landmarks (the editor page writes its JSON into a textbox here)."""
import contextlib
import html as _html
import json
from pathlib import Path

import gradio as gr

import landmarks as LM
from i18n import t as _t

NAMINGS = {_t("lm.mixamo_for_mixamo_animations"): "mixamo", _t("lm.godot_humanoid_profile"): "godot"}


def _frame(page):
    return ('<iframe srcdoc="%s" style="width:100%%;height:max(760px,84vh);border:0;border-radius:10px"></iframe>'
            % _html.escape(page, quote=True))


def mount(config_loader, asset, upload, accordion=True):
    """asset / upload: the model pickers of the rigging tab, reused here. Returns (data, editor) for mount_lipsync."""
    with (gr.Accordion(_t("lm.skeleton_by_landmarks_by_hand_like"), open=False) if accordion
          else contextlib.nullcontext()):
        gr.Markdown(_t("lm.choose_a_model_above_on_this_tab_and"))
        open_btn = gr.Button(_t("lm.open_the_markup"), variant="secondary")
        editor = gr.HTML()
        data = gr.Textbox(label=_t("lm.markup_the_editor_fills_it_in_a"),
                          lines=2, max_lines=4, elem_id=LM.TARGET_ID)
        # the editor's armour mode: it writes the request here and clicks the button (both kept out of sight)
        gr.HTML("<style>.sf3d-hidden{display:none!important}</style>")
        wear_req = gr.Textbox(elem_id=LM.WEAR_ID, elem_classes=["sf3d-hidden"], show_label=False)
        wear_btn = gr.Button("wear", elem_id=LM.WEAR_GO, elem_classes=["sf3d-hidden"])
        wear_log = gr.Textbox(label=_t("lm.armour"), lines=2, interactive=False)
        with gr.Accordion(_t("lm.build_options"), open=False):
            with gr.Row():
                naming = gr.Radio(list(NAMINGS), value=list(NAMINGS)[0], label=_t("lm.bone_names"))
                weld = gr.Checkbox(value=True, label=_t("lm.stitch_the_seams_between_parts"))
                mouth = gr.Radio([(_t("lm.plate_fast_for_distant_shots"), "plate"), (_t("lm.cut_lips_cavity_teeth_tongue"), "cut"),
                                  (_t("fbx.none"), "none")], value="cut", label=_t("lm.speech_mouth_if_the_face_is_marked"))
                eyes = gr.Checkbox(value=True, label=_t("lm.insert_eyeballs_if_the_eyes_are"))
                eyecol = gr.Checkbox(value=True, label=_t("lm.iris_colour_from_the_model_s_painted"),
                                     info=_t("lm.off_the_colour_from_the_face_parts"))
            with gr.Row():
                ftopo = gr.Checkbox(value=True, label=_t("lm.face_retopology_an_even_mesh_around"),
                                    info=_t("lm.rebuilds_the_face_mesh_in_rings"))
                fsmooth = gr.Slider(0, 3, value=2, step=1, label=_t("lm.face_mesh_smoothing_0_off"))
                kit = gr.Dropdown(choices=[""], value="", label=_t("lm.face_parts_set_empty_the_standard"), allow_custom_value=True)
        go = gr.Button(_t("lm.build_the_skeleton_and_weights_from"), variant="primary")
        with gr.Row():
            with gr.Column():
                log = gr.Textbox(label=_t("face.progress"), lines=7, interactive=False)
                files = gr.File(label=_t("lm.result"), file_count="multiple", interactive=False)
            with gr.Column():
                view = gr.Model3D(label=_t("lm.model_with_a_skeleton"), height=380, clear_color=(0.9, 0.9, 0.9, 1))
        shots = gr.Gallery(label=_t("lm.check_rest_front_pose_side_pose"), columns=3, height=300)
        with gr.Accordion(_t("lm.how_the_markup_works"), open=False):
            gr.Markdown(
                _t("lm.the_model_is_chosen_above_in_block_1"))
        with gr.Accordion(_t("lm.view_a_finished_model_with_a"), open=False):
            with gr.Row():
                ref_file = gr.File(label=_t("lm.fbx_mixamo_with_skin_or_glb"), file_types=[".fbx", ".glb"], type="filepath", scale=3)
                ref_btn = gr.Button(_t("lm.open_in_the_viewer_bones_weights"), scale=1)

        def open_editor(up, name, text):
            cfg = config_loader()
            src = LM.source_path(up, name, cfg["export_dir"])
            if not src or not src.exists():
                return _t("lm.first_choose_a_model_in_block_1")
            return _frame(LM.editor_page(src, LM.initial_state(src, cfg["export_dir"], text),
                                         LM.output_paths(src, cfg["export_dir"])[0]))

        def run(up, name, text, nm, do_weld, do_mouth, do_eyes, kit_name, do_topo, smooth_lvl, eye_col=True):
            cfg = config_loader()
            src = LM.source_path(up, name, cfg["export_dir"])
            lines = []
            if not src or not src.exists():
                yield _t("lm.choose_a_model_first"), None, None, None, gr.update()
                return
            try:
                marks = LM.parse(text)
                for step in LM.build(src, marks, NAMINGS[nm], cfg, do_weld, do_mouth, do_eyes, (kit_name or "").strip(), do_topo, smooth_lvl,
                                     eye_col):
                    if isinstance(step, dict):  # reopen the editor in the pose mode on the fresh build
                        lines.append(_t("lm.the_editor_is_open_in_pose_mode_drag"))
                        state = json.loads(Path(step["landmarks"]).read_text(encoding="utf-8"))
                        yield ("\n".join(lines), step["glb"], [step["glb"], step["landmarks"]], step["images"],
                               _frame(LM.editor_page(src, state, Path(step["glb"]), mode="pose")))
                    else:
                        lines.append(step)
                        yield "\n".join(lines), None, None, None, gr.update()
            except Exception as e:  # shown to the user; details are in work/landmark_rig/*/blender.log
                lines.append(_t("lm.error_2") + str(e))
                yield "\n".join(lines), None, None, None, gr.update()

        def open_view(path):
            if not path:
                return _t("lm.load_an_fbx_or_glb_with_a_skeleton")
            try:
                glb, info = LM.viewable(Path(path), config_loader())
            except Exception as e:
                return _t("lm.could_not_open", _html.escape(str(e)))
            return _frame(LM.editor_page(glb, None, glb, mode="view"))

        def kits():
            d = Path(config_loader()["export_dir"]) / "face_parts"
            names = sorted(p.name for p in d.iterdir() if (p / "eyes.glb").exists()) if d.exists() else []
            return gr.update(choices=[""] + names)

        def do_wear(text):
            try:
                return LM.wear(config_loader(), text)
            except Exception as e:
                return _t("lm.error_2") + str(e)

        wear_btn.click(do_wear, wear_req, wear_log, concurrency_id="landmark_rig", concurrency_limit=1, show_progress="minimal")
        open_btn.click(open_editor, [upload, asset, data], editor)
        open_btn.click(kits, None, kit)
        ref_btn.click(open_view, ref_file, editor)
        # retopology needs the cut mouth: keep the two consistent
        mouth.change(lambda m: gr.update(interactive=m == "cut", value=(m == "cut")), mouth, ftopo, show_progress="hidden")
        ftopo.change(lambda t, m: gr.update(value="cut") if t and m != "cut" else gr.update(), [ftopo, mouth], mouth,
                     show_progress="hidden")
        go.click(run, [upload, asset, data, naming, weld, mouth, eyes, kit, ftopo, fsmooth, eyecol], [log, view, files, shots, editor], concurrency_id="landmark_rig",
                 concurrency_limit=1)
        return data, editor


def mount_lipsync(config_loader, asset, upload, data, editor, accordion=True):
    """Lip-sync clip for the mouth plate. asset / upload: the pickers of the rigging tab; data / editor: from mount()."""
    with (gr.Accordion(_t("lm.line_lipsync_for_a_model_with_a"), open=False) if accordion
          else contextlib.nullcontext()):
        gr.Markdown(_t("lm.the_model_is_taken_from_the_skeleton"))
        with gr.Row():
            ls_audio = gr.File(label=_t("lm.voice_mp3_wav_ogg"), file_types=[".mp3", ".wav", ".ogg"], type="filepath")
            with gr.Column():
                ls_text = gr.Textbox(label=_t("lm.the_exact_text_of_the_line_empty_as"), lines=2)
                ls_lang = gr.Radio(["ru", "en"], value="ru", label=_t("face.tongue"))
                ls_btn = gr.Button(_t("lm.make_the_lipsync_clip"), variant="primary")
        ls_log = gr.Textbox(label=_t("face.progress"), lines=5, interactive=False)

        def lipsync(up, name, audio, text, lang, state_text):
            import lipsync_link as LL
            cfg = config_loader()
            src = LM.source_path(up, name, cfg["export_dir"])
            if not src or not src.exists() or not audio:
                yield _t("lm.a_model_tab_skeleton_and_audio_are"), gr.update()
                return
            rigged = LM.output_paths(src, cfg["export_dir"])[0]
            if not rigged.exists():
                yield _t("lm.build_the_skeleton_from_the_markup"), gr.update()
                return
            lines = []
            try:
                for step in LL.make_clip(Path(audio), text.strip(), lang, rigged, cfg):
                    if isinstance(step, dict):
                        lines.append(_t("lm.done_open_pose_line", step['clip']))
                        yield "\n".join(lines), _frame(LM.editor_page(
                            src, LM.initial_state(src, cfg["export_dir"], state_text), rigged, mode="pose"))
                    else:
                        lines.append(step)
                        yield "\n".join(lines), gr.update()
            except Exception as e:
                lines.append(_t("lm.error_2") + str(e))
                yield "\n".join(lines), gr.update()

        ls_btn.click(lipsync, [upload, asset, ls_audio, ls_text, ls_lang, data], [ls_log, editor], concurrency_id="lipsync",
                     concurrency_limit=1)
