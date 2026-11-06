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


OPTIONS_FILE = "landmark_build_options.json"   # in work_dir: the build options as last chosen


def _options(cfg) -> dict:
    try:
        d = json.loads((Path(cfg["work_dir"]) / OPTIONS_FILE).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _kit_choices(cfg, keep=""):
    """The face-parts sets to build with: «Standard» (the value "": made for the build) and every set saved in
    export/face_parts (the tab «Детали лица»), each with its folder."""
    d = Path(cfg["export_dir"]) / "face_parts"
    names = sorted(p.name for p in d.iterdir() if (p / "eyes.glb").exists()) if d.exists() else []
    if keep and keep not in names:
        names.append(keep)
    return [(_t("lm.face_parts_standard"), "")] + [(f"{n}  ({d.name}/{n})", n) for n in names]


def mount(config_loader, asset, upload, accordion=True):
    """asset / upload: the model pickers of the rigging tab, reused here. Returns (data, editor) for mount_lipsync."""
    opt = _options(config_loader())   # the build options come back as they were left
    name_of = {v: k for k, v in NAMINGS.items()}
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
                naming = gr.Radio(list(NAMINGS), value=name_of.get(opt.get("naming"), list(NAMINGS)[0]), label=_t("lm.bone_names"))
                weld = gr.Checkbox(value=opt.get("weld", True), label=_t("lm.stitch_the_seams_between_parts"))
                m0 = opt.get("mouth") if opt.get("mouth") in ("plate", "cut", "none") else "cut"
                mouth = gr.Radio([(_t("lm.plate_fast_for_distant_shots"), "plate"), (_t("lm.cut_lips_cavity_teeth_tongue"), "cut"),
                                  (_t("fbx.none"), "none")], value=m0, label=_t("lm.speech_mouth_if_the_face_is_marked"))
                eyes = gr.Checkbox(value=opt.get("eyes", True), label=_t("lm.insert_eyeballs_if_the_eyes_are"))
                eyecol = gr.Checkbox(value=opt.get("eye_colour", True), label=_t("lm.iris_colour_from_the_model_s_painted"),
                                     info=_t("lm.off_the_colour_from_the_face_parts"))
            with gr.Row():
                ftopo = gr.Checkbox(value=bool(opt.get("face_topo", False)) and m0 == "cut", interactive=m0 == "cut",
                                    label=_t("lm.face_retopology_an_even_mesh_around"), info=_t("lm.rebuilds_the_face_mesh_in_rings"))
                fsmooth = gr.Slider(0, 3, value=opt.get("face_smooth", 2), step=1, label=_t("lm.face_mesh_smoothing_0_off"))
                kit = gr.Dropdown(choices=_kit_choices(config_loader(), opt.get("kit", "")), value=opt.get("kit", ""),
                                  label=_t("lm.face_parts_set_empty_the_standard"), allow_custom_value=True)
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

        def open_editor(up, name, text, kit_name=""):
            cfg = config_loader()
            src = LM.source_path(up, name, cfg["export_dir"])
            if not src or not src.exists():
                return _t("lm.first_choose_a_model_in_block_1")
            return _frame(LM.editor_page(src, LM.initial_state(src, cfg["export_dir"], text),
                                         LM.output_paths(src, cfg["export_dir"])[0],
                                         eyes=LM.editor_eyes(cfg, (kit_name or "").strip())))   # the set's eyes, as built

        def run(up, name, text, nm, do_weld, do_mouth, do_eyes, kit_name, do_topo, smooth_lvl, eye_col=True):
            cfg = config_loader()
            src = LM.source_path(up, name, cfg["export_dir"])
            lines = []
            if not src or not src.exists():
                yield _t("lm.choose_a_model_first"), None, None, None, gr.update()
                return
            try:
                marks = LM.parse(text)
                bad = LM.markup_mismatch(src, marks)   # the editor was open on another model
                if bad:
                    raise ValueError(bad)
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
            return gr.update(choices=_kit_choices(config_loader()))

        def do_wear(text):
            try:
                return LM.wear(config_loader(), text)
            except Exception as e:
                return _t("lm.error_2") + str(e)

        wear_btn.click(do_wear, wear_req, wear_log, concurrency_id="landmark_rig", concurrency_limit=1, show_progress="minimal")
        def keep_fist(up, name, text):   # «Remember the fist» reaches the built rig at once: no rebuild for it
            try:
                cfg = config_loader()
                src = LM.source_path(up, name, cfg["export_dir"])
                if src and src.exists():
                    LM.keep_fist(src, cfg["export_dir"], text)
            except Exception:   # noqa: BLE001 — the markup's own textbox: never in the way of editing
                pass

        # the markup open follows the model: a GLB loaded or another character chosen opens it again on that one
        # (else the «Модель» view showed the new model and the markup the old one)
        opened = gr.State(False)
        open_btn.click(open_editor, [upload, asset, data, kit], editor).then(lambda: True, None, opened)

        def reopen(up, name, text, kit_name, was):
            return open_editor(up, name, text, kit_name) if was else gr.update()

        upload.change(reopen, [upload, asset, data, kit, opened], editor, show_progress="hidden")
        asset.change(reopen, [upload, asset, data, kit, opened], editor, show_progress="hidden")
        kit.change(reopen, [upload, asset, data, kit, opened], editor, show_progress="hidden")   # its eyes in the markup
        data.change(keep_fist, [upload, asset, data], None, show_progress="hidden")
        open_btn.click(kits, None, kit)
        ref_btn.click(open_view, ref_file, editor)
        # retopology needs the cut mouth: keep the two consistent
        # the retopology needs the cut mouth: off (and greyed) without it, back to the last choice with it
        mouth.change(lambda m: gr.update(interactive=m == "cut", value=bool(_options(config_loader()).get("face_topo", False)) and m == "cut"),
                     mouth, ftopo, show_progress="hidden")

        def _store(**kv):
            cfg = config_loader()
            old = _options(cfg)
            new = {**old, **kv}
            if new != old:
                try:
                    (Path(cfg["work_dir"]) / OPTIONS_FILE).write_text(json.dumps(new, ensure_ascii=False, indent=1), encoding="utf-8")
                except OSError:
                    pass

        def remember(nm, do_weld, do_mouth, do_eyes, eye_col, smooth_lvl, kit_name):   # every build option but the retopology
            _store(naming=NAMINGS.get(nm, "mixamo"), weld=bool(do_weld), mouth=do_mouth, eyes=bool(do_eyes),
                   eye_colour=bool(eye_col), face_smooth=smooth_lvl, kit=(kit_name or "").strip())

        def remember_topo(do_topo, do_mouth):
            """The retopology as chosen: only from its own box and with a cut mouth (without one it is off by force,
            not by choice; on the way back to «cut» the box is still off for a moment)."""
            if do_mouth == "cut":
                _store(face_topo=bool(do_topo))

        opts = [naming, weld, mouth, eyes, eyecol, fsmooth, kit]
        for c in opts:
            c.change(remember, opts, None, show_progress="hidden")
        ftopo.input(remember_topo, [ftopo, mouth], None, show_progress="hidden")   # the user's own click only
        ftopo.change(lambda t, m: gr.update(value="cut") if t and m != "cut" else gr.update(), [ftopo, mouth], mouth,
                     show_progress="hidden")
        go.click(run, [upload, asset, data, naming, weld, mouth, eyes, kit, ftopo, fsmooth, eyecol], [log, view, files, shots, editor], concurrency_id="landmark_rig",
                 concurrency_limit=1)
        return data, editor


def mount_wear(config_loader, char, tab, active):
    """«Equipment: fitting a piece»: the markup editor's armour mode («Броня») opened at once on the current character
    (char: its model with a landmark skeleton), with its own hidden textbox and button to send through. The editor (a
    heavy 3D page) opens when the tab is entered (tab), and on a new character only while the tab is shown (active: the
    label of the tab shown); else it goes, not to run hidden."""
    gr.Markdown(_t("lm.wear_tab_intro"))
    reopen = gr.Button(_t("lm.wear_reopen"))
    editor = gr.HTML()
    ids = (LM.WEAR_ID + "_tab", LM.WEAR_GO + "_tab")
    gr.HTML("<style>.sf3d-hidden{display:none!important}</style>")
    req = gr.Textbox(elem_id=ids[0], elem_classes=["sf3d-hidden"], show_label=False)
    btn = gr.Button("wear", elem_id=ids[1], elem_classes=["sf3d-hidden"])
    # the page's own state goes here, not into the markup's textbox of the «Skeleton» tab (nothing reads it)
    gr.Textbox(elem_id=LM.TARGET_ID + "_wear", elem_classes=["sf3d-hidden"], show_label=False)
    log = gr.Textbox(label=_t("lm.armour"), lines=2, interactive=False)

    def open_editor(rigged):
        rigged = Path(rigged) if rigged else None
        if not LM.is_rig(rigged):
            return _t("lm.wear_needs_landmarks")
        # the built model stands for the source here: only the armour mode is used; the joints a piece is placed
        # between are the markup's, or read off the bones of an auto-rig
        return _frame(LM.editor_page(rigged, LM.rig_state(rigged), rigged, mode="wear", wear_ids=ids, target=LM.TARGET_ID + "_wear"))

    def do_wear(text):
        try:
            return LM.wear(config_loader(), text)
        except Exception as e:  # noqa: BLE001
            return _t("lm.error_2") + str(e)

    opened = gr.State("")
    here = _t("ui.equipment_fitting")
    char.change(lambda r, act: (open_editor(r), r) if act == here else ("", ""), [char, active], [editor, opened], show_progress="hidden")
    tab.select(lambda r, op: (open_editor(r), r) if r != op else (gr.update(), op), [char, opened], [editor, opened], show_progress="hidden")
    reopen.click(open_editor, char, editor)
    btn.click(do_wear, req, log, concurrency_id="landmark_rig", concurrency_limit=1, show_progress="minimal")


def mount_rig_pose(config_loader, char):
    """The pose check of the current character's skeleton, whichever made it (the auto-rigger too): bend the joints,
    play its clips, and the fist: close the fingers («Free», «Fist») and «Remember the fist» — kept with the skeleton
    (an auto-rig's <name>_rig.json, the markup of a landmark one) for the procedural editor, «Броня» and Godot."""
    open_btn = gr.Button(_t("lm.rig_pose_open"))
    gr.Markdown(_t("lm.rig_pose_info"))
    editor = gr.HTML()
    data = gr.Textbox(elem_id=LM.TARGET_ID + "_pose", elem_classes=["sf3d-hidden"], show_label=False)
    note = gr.Markdown()

    def open_editor(rigged):
        rigged = Path(rigged) if rigged else None
        if not LM.is_rig(rigged):
            return _t("lm.rig_pose_needs_a_skeleton"), ""
        return (_frame(LM.editor_page(rigged, LM.rig_state(rigged), rigged, mode="view", target=LM.TARGET_ID + "_pose")),
                "" if LM.is_landmark_rig(rigged) else _t("lm.rig_pose_no_face"))

    def keep(rigged, text):
        try:
            if rigged and LM.keep_rig_fist(Path(rigged), text):
                return _t("lm.rig_pose_fist_kept", LM.rig_meta(Path(rigged)).name)
        except Exception:   # noqa: BLE001 — never in the way of posing
            pass
        return gr.update()

    open_btn.click(open_editor, char, [editor, note])
    char.change(lambda r: ("", ""), char, [editor, note], show_progress="hidden")   # another character: open it anew
    data.change(keep, [char, data], note, show_progress="hidden")


def _say_frame(page):   # the lipsync viewer: it may play the line's sound at once (the click was on this page)
    return ('<iframe allow="autoplay" srcdoc="%s" style="width:100%%;height:max(560px,62vh);border:0;border-radius:10px"></iframe>'
            % _html.escape(page, quote=True))


def mount_lipsync(config_loader, asset, upload, data, editor, accordion=True):
    """Lip-sync clip for the mouth plate. asset / upload: the pickers of the rigging tab; data / editor: from mount().
    The clip made (or one made before) is shown right here: the face close, the line played."""
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
        with gr.Row():
            ls_clip = gr.Dropdown([], label=_t("lm.lipsync_clips"), scale=4, allow_custom_value=False)
            ls_show = gr.Button(_t("lm.watch_the_line"), variant="primary", scale=1)
        ls_view = gr.HTML()

        def model(up, name):   # (the source, the built model) or (None, None)
            cfg = config_loader()
            src = LM.source_path(up, name, cfg["export_dir"])
            if not src or not src.exists():
                return None, None, cfg
            rigged = LM.output_paths(src, cfg["export_dir"])[0]
            return src, (rigged if rigged.exists() else None), cfg

        def view(src, rigged, cfg, clip, state_text):
            return _say_frame(LM.editor_page(src, LM.initial_state(src, cfg["export_dir"], state_text), rigged, mode="say", say=clip))

        def show(up, name, clip, state_text):
            src, rigged, cfg = model(up, name)
            if not rigged:
                return gr.update(), _t("lm.build_the_skeleton_from_the_markup"), gr.update()
            clips = [c["name"] for c in LM.face_clips(rigged)]
            if not clips:
                return gr.update(choices=[], value=None), _t("lm.no_lipsync_clips_yet"), ""
            clip = clip if clip in clips else max(clips, key=lambda c: (rigged.parent / f"{c}.face.json").stat().st_mtime)
            return gr.update(choices=clips, value=clip), gr.update(), view(src, rigged, cfg, clip, state_text)

        def lipsync(up, name, audio, text, lang, state_text):
            import lipsync_link as LL
            src, rigged, cfg = model(up, name)
            if not src or not audio:
                yield _t("lm.a_model_tab_skeleton_and_audio_are"), gr.update(), gr.update(), gr.update()
                return
            if not rigged:
                yield _t("lm.build_the_skeleton_from_the_markup"), gr.update(), gr.update(), gr.update()
                return
            lines = []
            try:
                for step in LL.make_clip(Path(audio), text.strip(), lang, rigged, cfg):
                    if isinstance(step, dict):
                        lines.append(_t("lm.done_open_pose_line", step['clip']))
                        clip = Path(step["clip"]).name[:-len(".face.json")]
                        yield ("\n".join(lines), _frame(LM.editor_page(src, LM.initial_state(src, cfg["export_dir"], state_text), rigged, mode="pose")),
                               gr.update(choices=[c["name"] for c in LM.face_clips(rigged)], value=clip), view(src, rigged, cfg, clip, state_text))
                    else:
                        lines.append(step)
                        yield "\n".join(lines), gr.update(), gr.update(), gr.update()
            except Exception as e:
                lines.append(_t("lm.error_2") + str(e))
                yield "\n".join(lines), gr.update(), gr.update(), gr.update()

        ls_btn.click(lipsync, [upload, asset, ls_audio, ls_text, ls_lang, data], [ls_log, editor, ls_clip, ls_view], concurrency_id="lipsync",
                     concurrency_limit=1)
        ls_show.click(show, [upload, asset, ls_clip, data], [ls_clip, ls_log, ls_view])
