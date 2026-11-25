"""Работа приложения SF3D: модели, персонажи, существа, окружение. Эти функции вызывает веб-интерфейс
(tool/web/server.py, http://127.0.0.1:7890); прежние вкладки Gradio убраны, сами функции пока отвечают в его форме
(gr.update, gr.Progress).

Запуск: sf3d-ui.vbs (без консоли) или sf3d-ui.bat (с консолью для отладки).
Постобработка и настройки общие с sf3d_tool.py.
"""
import json
import os
import re
import shutil
import subprocess
import sys
import time
from collections import deque
from pathlib import Path

import gradio as gr

sys.path.insert(0, str(Path(__file__).resolve().parent))
import materials as MT  # noqa: E402
import sf3d_tool as T  # noqa: E402  (заодно добавляет sf3d-src в sys.path)
import landmarks  # any skeleton: what the tools read off it
import landmarks_ui  # hand-placed landmark skeleton (Mixamo-like)
import face_parts_ui  # noqa: F401  procedural eyes, teeth, tongue (imported here before the web server patches the config)
import armour_gen_ui  # noqa: F401  procedural armour from the character's own skin (the web server: UI.armour_gen_ui)
import wear_files as WF
import creatures as CR  # the «Creatures» section: which models are creatures, the skeleton viewer
from i18n import t as _t
_state = {"model": None, "rembg": None, "on_gpu": False}

HY_PY = r"D:\conda\envs\hunyuan\python.exe"
# categories whose Hunyuan shape defaults to the turbo model (hy_pipeline --fast): a character in 28 s instead of
# 254 s with the same detail; buildings came out lumpier and no faster, so they keep the base model
HY_FAST_CATEGORIES = {"character", "item", "prop"}
HY_SRC = r"D:\My projects\SF3D\hunyuan3d-src"
ENGINE_HY = _t("ui.hunyuan3d_1_4_pictures_the_best")
ENGINE_TR = _t("ui.trellis_one_picture")
# TRELLIS.2 (trellis.cpp, MIT): one picture -> GLB with base colour + metal/roughness maps, a separate process like
# Hunyuan. trellis2-install.ps1 builds it, trellis2-weights.ps1 fetches the weights; config.json keys
# trellis_exe / trellis_models / trellis_cuda_bin point elsewhere. Peak 2.7-5.3 GB in the 24.11 test (res 512).
TRELLIS_EXE = r"D:\conda\trellis\trellis-cli.exe"
TRELLIS_MODELS = r"D:\conda\hf\trellis2-gguf\q8"
TRELLIS_CUDA_BIN = r"D:\conda\envs\hunyuan\bin"  # the CUDA 12.1 runtime + cuBLAS it was built against
TRELLIS_WEIGHTS = ("ss_flow", "ss_dec", "shape_flow_512", "shape_dec", "tex_flow_512", "tex_dec", "dinov3", "birefnet")
TRELLIS_VRAM_MB = 5500
# its albedo comes out 1.4-2.2x darker (Lab L) than the picture; the palette pulled 0.7 of the way to the picture
# lands at Hunyuan's lightness (work/trellis_test/REPORT.md)
TRELLIS_COLOR_MATCH = 0.7

# Ключ категории в config.json -> подпись в интерфейсе
CATEGORY_LABELS = {
    "item": _t("ui.inventory_item"),
    "prop": _t("ui.prop_environment"),
    "building": _t("ui.building"),
    "character": _t("ui.character"),
    "vegetation": _t("ui.vegetation_trees_bushes_grass"),
}
LABEL_TO_KEY = {v: k for k, v in CATEGORY_LABELS.items()}
PIVOT_LABELS = {_t("ui.auto_by_category"): None, _t("ui.at_the_base"): "bottom", _t("ui.at_the_centre"): "center"}
COLLISION_LABELS = {_t("ui.by_category"): None, _t("ui.none"): "none",
                    _t("ui.convex_hull_items_props"): "convex",
                    _t("ui.simplified_mesh_buildings"): "simplified"}


# ------------------------------------------------------------------ модель
def get_model():
    from sf3d.system import SF3D
    from sf3d.utils import get_device

    if _state["model"] is None:
        m = SF3D.from_pretrained(
            "stabilityai/stable-fast-3d", config_name="config.yaml", weight_name="model.safetensors"
        )
        m.to(get_device())
        m.eval()
        _state["model"] = m
        _state["on_gpu"] = True
    elif not _state["on_gpu"]:  # parked in RAM by unload_model(): bring it back, takes a few seconds
        _state["model"].to(get_device())
        _state["on_gpu"] = True
    return _state["model"]


def unload_model():
    """Free the GPU: park the SF3D model in system RAM (3.8 GB). Dropping the Python reference is not enough:
    the library keeps a frame alive, so the weights would stay in VRAM."""
    import gc

    import torch

    m = _state["model"]
    if m is not None and _state["on_gpu"]:
        m.to("cpu")
        _state["on_gpu"] = False
    gc.collect()
    torch.cuda.empty_cache()
    return _t("ui.the_model_moved_to_ram_video_memory")


def gpu_free_mb():
    """Free GPU memory in MB, or None if nvidia-smi is not available."""
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.free", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=15,
                             creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
        return int(out.strip().splitlines()[0])
    except Exception:  # noqa: BLE001
        return None


# ------------------------------------------------------------------ кто занимает видеопамять
GPU_NEEDS = [(_t("ui.sf3d_item_prop_character"), 6400),
             (_t("ui.hunyuan3d_shape"), 6200),
             (_t("ui.hunyuan3d_texture_painting"), 7000),
             (_t("ui.trellis_gpu_need"), TRELLIS_VRAM_MB),
             (_t("ui.rigging_unirig"), 4500)]
# never offered for closing: Windows itself and the things that would log the user out or break the GPU driver
PROTECTED = {"claude", "system", "idle", "registry", "dwm", "csrss", "winlogon", "wininit", "services", "lsass", "smss",
             "svchost", "explorer", "fontdrvhost", "audiodg", "memory compression", "nvcontainer",
             "nvidia web helper", "msmpeng", "sihost", "ctfmon", "searchhost", "startmenuexperiencehost",
             "shellexperiencehost", "textinputhost", "applicationframehost", "runtimebroker"}
_GPU_PS = r"""
$s = Get-Counter '\GPU Process Memory(*)\Dedicated Usage' -ErrorAction SilentlyContinue | Select-Object -ExpandProperty CounterSamples
$rows = foreach ($x in $s) {
  if ($x.CookedValue -gt 40MB -and $x.InstanceName -match '^pid_(\d+)_') {
    $id = [int]$Matches[1]
    $p = Get-Process -Id $id -ErrorAction SilentlyContinue
    $c = (Get-CimInstance Win32_Process -Filter "ProcessId=$id" -ErrorAction SilentlyContinue).CommandLine
    [pscustomobject]@{ pid = $id; mb = [int]($x.CookedValue / 1MB); name = [string]$p.ProcessName; title = [string]$p.MainWindowTitle; cmd = [string]$c }
  }
}
if ($rows) { @($rows) | ConvertTo-Json -Compress } else { '[]' }
"""


def _friendly(name, cmd, title):
    n = (name or "").lower()
    c = (cmd or "").lower()
    if n.startswith("python"):
        if "sf3d_ui" in c:
            return _t("ui.this_sf3d_window_it_cannot_be_closed"), "self"
        if "gradio_app" in c:
            return _t("ui.old_sf3d_demo_sf3d_gradio_bat"), "ours"
        if "hy_pipeline" in c or "hy_texture" in c or "hy_test" in c:
            return _t("ui.hunyuan3d_generating"), "ours"
        if "unirig" in c or "run.py" in c:
            return _t("ui.unirig_rigging"), "ours"
        if "batch_cli" in c:
            return _t("ui.sf3d_batch_processing"), "ours"
        return f"Python: {cmd[-70:] if cmd else name}", "other"
    if n == "blender":
        return "Blender" + (f" — {title}" if title else ""), "other"
    if n in ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi"):
        return _t("ui.browser", name) + (f" — {title[:50]}" if title else _t("ui.service_process")), "other"
    if n in PROTECTED:
        return _t("ui.windows_system_process_desktop_and"), "system"
    return name + (f" — {title[:50]}" if title else ""), "other"


def gpu_holders():
    """[{pid, mb, name, label, kind}] of programs using GPU memory (Windows counters), biggest first."""
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", _GPU_PS], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=60,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        data = json.loads(r.stdout.strip() or "[]")
    except Exception:  # noqa: BLE001
        return []
    if isinstance(data, dict):
        data = [data]
    out = []
    for d in data:
        label, kind = _friendly(d.get("name"), d.get("cmd"), d.get("title"))
        if d.get("pid") == os.getpid():
            label, kind = _t("ui.this_sf3d_window_it_cannot_be_closed"), "self"
        # the counter of the desktop compositor counts virtual surfaces and is far above the card size: not trusted
        reliable = kind != "system" and d["mb"] < 8200
        out.append(dict(pid=d["pid"], mb=d["mb"] if reliable else None, name=d.get("name"), label=label, kind=kind))
    out.sort(key=lambda x: -(x["mb"] or 0))
    return out


def gpu_status():
    """Markdown report: free VRAM, will each task fit, who holds the memory; plus the 'close' dropdown."""
    free = gpu_free_mb()
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        used, total = (int(x) for x in r.stdout.strip().splitlines()[0].split(","))
    except Exception:  # noqa: BLE001
        return _t("ui.could_not_read_the_gpu_data_nvidia"), gr.update(choices=[], value=None)
    lines = [_t("ui.video_memory_of_gb_used_gb_free", used / 1024, total / 1024, free / 1024), ""]
    for what, need in GPU_NEEDS:
        if free >= need + 500:
            mark = _t("ui.fits")
        elif free >= need:
            mark = _t("ui.tight_better_free_some")
        else:
            mark = _t("ui.will_not_fit_another_gb_short", (need - free) / 1024)
        lines.append(_t("ui.about_gb", what, need / 1024, mark))
    holders = gpu_holders()
    choices = []
    if holders:
        lines += ["", _t("ui.what_uses_the_memory_according_to"), ""]
        for h in holders:
            size = _t("ui.mb_2", h['mb']) if h["mb"] is not None else "—"
            tag = {"system": _t("ui.system"), "self": _t("ui.this_window")}.get(h["kind"], "")
            lines.append(f"- {size}: {h['label']} (PID {h['pid']}){tag}")
            if h["kind"] in ("other", "ours"):
                choices.append((f"{h['label']} — {size} (PID {h['pid']})", h["pid"]))
    if _state["model"] is not None:
        lines += ["", _t("ui.the_sf3d_model_is_now", 'в видеопамяти' if _state['on_gpu'] else 'в оперативной памяти')]
    return "\n".join(lines), gr.update(choices=choices, value=None)


def gpu_close_proc(pid, force):
    """Close a program that holds GPU memory. Gentle by default (the program may ask to save its work)."""
    if not pid:
        return _t("ui.first_choose_a_program_in_the_list"), *gpu_status()
    pid = int(pid)
    holders = {h["pid"]: h for h in gpu_holders()}
    h = holders.get(pid)
    if h is None:
        return _t("ui.this_program_no_longer_uses_video"), *gpu_status()
    if h["kind"] not in ("other", "ours") or (h["name"] or "").lower() in PROTECTED or pid == os.getpid():
        return _t("ui.must_not_be_closed", h['label']), *gpu_status()
    flags = ["/F"] if force else []
    subprocess.run(["taskkill", "/PID", str(pid), *flags], capture_output=True, text=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(12):  # up to ~6 s for a polite close
        time.sleep(0.5)
        if pid not in {x["pid"] for x in gpu_holders()}:
            return _t("ui.closed", h['label']), *gpu_status()
    msg = (_t("ui.did_not_close_it_may_be_asking_about", h['label']) if not force
           else _t("ui.could_not_be_closed_even_by_force", h['label']))
    return msg, *gpu_status()


def vram_gate(need_mb, log, emit, label, timeout_s=900):
    """Wait until enough VRAM is free instead of crashing when another program holds the GPU.

    Use as:  ok = yield from vram_gate(...). Loading a model into a nearly full 8 GB card makes the
    driver/torch crash the whole process without a Python traceback, so it is better to wait.
    """
    free = gpu_free_mb()
    if free is None or free >= need_mb:
        return True
    names = ", ".join(_t("ui.mb", h['label'], h['mb']) for h in gpu_holders()[:3] if h["mb"])
    log.append(_t("ui.mb_of_video_memory_free_about_needed", label, free, need_mb)
               + (_t("ui.now_it_is_used_by", names) if names else "")
               + _t("ui.close_what_you_do_not_need_or_open"))
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        yield emit()
        time.sleep(10)
        free = gpu_free_mb()
        if free is None or free >= need_mb:
            log.append(_t("ui.video_memory_freed_mb_continuing", label, free))
            return True
    log.append(_t("ui.the_video_memory_was_not_freed", label, timeout_s // 60))
    return False


# ------------------------------------------------------------------ генерация
def generate(files, category_label, name, height, width, depth, pivot_label, collision_label, override,
             metallic, roughness,
             tex_res, fg_ratio, remove_bg, remesh, overwrite, make_preview=False,
             color_match=0.0, saturation=1.0, brightness=1.0, auto_materials=False,
             auto_rig=False, rig_naming_label=None, rig_tries=3, progress=gr.Progress()):
    cfg = T.load_config()
    category = LABEL_TO_KEY[category_label]
    log, results, last_glb, previews = [], [], None, []
    rig_queue = []  # characters to rig once every picture is generated (keeps the SF3D model loaded until then)

    def emit():
        return "\n".join(log), results, last_glb, previews

    if not files:
        log.append(_t("ui.add_at_least_one_picture_first"))
        yield emit()
        return
    paths = T.collect_images([f if isinstance(f, str) else f.name for f in files])
    preset = cfg["categories"][category]
    log.append(_t("ui.pictures_category", len(paths), category_label))
    yield emit()

    import rembg
    import torch
    from PIL import Image

    from sf3d.utils import remove_background, resize_foreground

    for i, img_path in enumerate(paths):
        stem = T.slug(name if (name and len(paths) == 1) else img_path.stem)
        progress((i, len(paths)), desc=f"{stem}")
        work = Path(cfg["work_dir"]) / category / stem
        final = Path(cfg["export_dir"]) / category / stem / f"{stem}.glb"
        if final.exists() and not overwrite:
            log.append(_t("ui.skip_already_exported_turn_on", stem))
            last_glb = str(final)
            yield emit()
            continue
        try:
            t0 = time.time()
            work.mkdir(parents=True, exist_ok=True)
            # Gradio uploads live in a temp dir that gets cleaned, so keep our own copy of the source.
            src_copy = work / f"source{img_path.suffix.lower()}"
            shutil.copy2(img_path, src_copy)
            image = Image.open(img_path).convert("RGBA")
            if remove_bg:
                _state["rembg"] = _state["rembg"] or rembg.new_session(providers=["CPUExecutionProvider"])
                log.append(_t("ui.removing_the_background", stem))
                yield emit()
                image = remove_background(image, _state["rembg"])
            image = resize_foreground(image, fg_ratio)
            image.save(work / "input.png")
            previews.append((str(work / "input.png"), stem))
            log.append(_t("ui.generating_3d_on_the_first_run_the", stem))
            yield emit()

            if not _state["on_gpu"] and not (yield from vram_gate(5500, log, emit, f"[{stem}]")):
                raise RuntimeError(_t("ui.not_enough_free_video_memory"))
            model = get_model()
            torch.cuda.reset_peak_memory_stats()
            with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
                mesh, _ = model.run_image([image], bake_resolution=int(tex_res), remesh=remesh, vertex_count=-1)
            peak = torch.cuda.max_memory_allocated() / 1024**2
            raw = work / "raw.glb"
            mesh.export(str(raw), include_normals=True)

            pp = dict(
                height=height if height and height > 0 else None,
                pivot=PIVOT_LABELS[pivot_label],
                metallic=metallic if override else None,
                roughness=roughness if override else None,
                width=width if width and width > 0 else None,
                depth=depth if depth and depth > 0 else None,
                collision=COLLISION_LABELS[collision_label],
                collision_faces=cfg.get("collision_faces", 800),
                rotate_y=180.0,  # SF3D output faces -Z; make it face +Z like glTF and Hunyuan
                color_refs=[str(work / "input.png")], color_strength=color_match,
                saturation=saturation, brightness=brightness,
                materials="auto" if auto_materials else None, category=category)
            stats = pp_call(raw, final, preset, pp)
            save_pp(work, stem, category, raw, final, pp)
            stats.update(source=str(src_copy), category=category,
                         seconds=round(time.time() - t0, 1), peak_vram_mb=round(peak))
            (final.parent / f"{stem}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
            last_glb = str(final)
            results.append([stem, category_label, stats["faces"],
                            " x ".join(map(str, stats["size_m"])), stats["seconds"], str(final)])
            log.append(_t("ui.done_in_s_peak_video_memory_mb", stem, stats['seconds'], stats['peak_vram_mb']))
            if make_preview:
                yield emit()
                previews += make_previews(final, work, stem, cfg, log)
            if auto_rig:
                if category == "character":
                    rig_queue.append((final, stem))
                else:
                    log.append(_t("ui.skeletons_are_made_only_for_the", stem))
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            log.append(_t("ui.out_of_video_memory_close_other", stem))
        except Exception as e:  # noqa: BLE001
            log.append(_t("ui.error_4", stem, type(e).__name__, e))
        yield emit()
    if rig_queue:
        # this frame still references the SF3D model and its tensors; drop them or the VRAM is never released
        model = mesh = image = None
        log.append(_t("ui.generation_finished_making_skeletons", len(rig_queue)))
        yield emit()
        rigged = yield from rig_queue_run(rig_queue, cfg, rig_naming_label, rig_tries, log, emit)
        if rigged:
            last_glb = rigged[-1]
    log.append(_t("ui.done"))
    yield emit()


def rig_queue_run(queue, cfg, naming_label, tries, log, emit):
    """Rig several exported GLBs one after another. Generator; returns the list of rigged file paths."""
    naming_key = RIG_NAMINGS.get(naming_label) or list(RIG_NAMINGS.values())[0]
    out = []
    for final, stem in queue:
        dst = Path(final).with_name(f"{stem}_rigged.glb")
        res = yield from rig_core(final, dst, stem, cfg, naming_key, tries, log, emit)
        if res:
            out.append(str(dst))
    return out


def pp_call(src, final, preset, pp, materials=None):
    """T.postprocess driven by a JSON-able dict, so the same call can be repeated later (material editor)."""
    veg = pp.get("category") == "vegetation"
    stats = T.postprocess(
        Path(src), Path(final), preset, pp.get("height"), pp.get("pivot"), pp.get("metallic"), pp.get("roughness"),
        width=pp.get("width"), depth=pp.get("depth"), collision="none" if veg else pp.get("collision"),
        collision_faces=pp.get("collision_faces", 800), rotate_y=pp.get("rotate_y", 0.0),
        color_refs=[Path(x) for x in pp.get("color_refs", [])], color_strength=pp.get("color_strength", 0.0),
        saturation=pp.get("saturation", 1.0), brightness=pp.get("brightness", 1.0),
        materials=materials if materials is not None else pp.get("materials"),
        category=pp.get("category"))
    if veg:
        stats["wind"] = vegetation_pass(Path(final), pp.get("veg_kind") or VEG_STATE["kind"])
    return stats


VEG_STATE = {"kind": "tree"}  # chosen in the generation tab; one user, one generation at a time


def vegetation_pass(final, kind="tree"):
    """Wind map in the vertex colours + trunk collision (tool/blender_vegetation.py), in place."""
    cfg = T.load_config()
    tmp = final.with_name(final.stem + "_veg.glb")
    r = subprocess.run([cfg["blender_exe"], "-b", "-P", str(T.ROOT / "blender_vegetation.py"), "--", str(final),
                        str(tmp), f"kind={kind}"], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = [x for x in r.stdout.splitlines() if x.startswith("VEG_")]
    if not tmp.exists() or not any(x.startswith("VEG_OK") for x in lines):
        raise RuntimeError(_t("ui.wind_not_added") + (r.stdout + r.stderr)[-300:])
    os.replace(tmp, final)
    # the Godot side: shader + script next to the export folder, copied once
    gd = Path(cfg["export_dir"]) / "_godot"
    gd.mkdir(parents=True, exist_ok=True)
    for f in ("wind_foliage.gdshader", "wind_foliage.gd"):
        shutil.copy2(T.ROOT / "godot" / f, gd / f)
    return " ".join(x for x in lines if x.startswith(("VEG_WIND", "VEG_COLLISION")))


def save_pp(work, name, category, src, final, pp):
    (Path(work) / "pp_params.json").write_text(
        json.dumps(dict(name=name, category=category, src=str(src), final=str(final), pp=pp),
                   indent=2, ensure_ascii=False), encoding="utf-8")


def make_previews(final, work, stem, cfg, log):
    """Blender renders the contact sheet and the inventory icon; returns gallery entries."""
    try:
        res = T.render_previews(final, work, final.parent / f"{stem}_icon.png", cfg)
    except Exception as e:  # noqa: BLE001
        log.append(_t("ui.preview_and_icon_not_made", stem, e))
        return []
    log.append(_t("ui.inventory_icon", stem, res['icon']))
    return [(res["preview"], _t("ui.4_views", stem)), (res["icon"], _t("ui.icon", stem))]


def _hy_run(cmd, env, log, live, emit):
    """One run of the Hunyuan worker with progress lines; returns (exit code, tail, crashed before the shape)."""
    tail = deque(maxlen=25)
    last_pct = {"Diffusion Sampling": -1, "Volume Decoding": -1}
    started = False
    proc = subprocess.Popen(cmd, cwd=HY_SRC, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in proc.stdout:
        line = line.rstrip()
        if line.startswith("@@ "):
            live[0] = ""
            log.append(line[3:])
            if _t("ui.generating_the_shape") in line:
                started = True
            yield emit()
            continue
        m = re.search(r"(Diffusion Sampling|Volume Decoding)::?\s+(\d+)%", line)
        if m:
            started = True
            what, pct = m.group(1), int(m.group(2))
            if pct != last_pct[what]:
                last_pct[what] = pct
                live[0] = f"  {'шаги диффузии' if what.startswith('Diff') else 'построение меша'}: {pct}%"
                yield emit()
            continue
        if line and not re.search(r"it/s|Warning|warn|Loading pipeline", line):
            tail.append(line)
    code = proc.wait()
    crashed = code in (3221225477, 3221226505, -1073741819, -1073740791)
    return code, tail, crashed and not started

def generate_hy(front, back, left, right, category_label, name, height, width, depth, pivot_label,
                collision_label, override,
                metallic, roughness, hy_tex, hy_faces, hy_steps, paint, overwrite, make_preview=False,
                color_match=0.0, saturation=1.0, brightness=1.0, auto_materials=False,
                auto_rig=False, rig_naming_label=None, rig_tries=3, progress=None, hy_fast=False):
    """Hunyuan3D: runs hy_pipeline.py in the 'hunyuan' env as a separate process (VRAM is freed on exit).
    hy_fast: the shape from the turbo model (hy_pipeline --fast, ~30 s instead of ~4 min)."""
    cfg = T.load_config()
    category = LABEL_TO_KEY[category_label]
    preset = cfg["categories"][category]
    log, results, last_glb, previews = [], [], None, []
    live = [""]

    def emit():
        lines = log + ([live[0]] if live[0] else [])
        return "\n".join(lines), results, last_glb, previews

    if not front:
        log.append(_t("ui.at_least_the_front_picture_is_needed"))
        yield emit()
        return
    stem = T.slug(name or Path(front).stem)
    work = Path(cfg["work_dir"]) / "hunyuan" / category / stem
    final = Path(cfg["export_dir"]) / category / stem / f"{stem}.glb"
    if final.exists() and not overwrite:
        log.append(_t("ui.skip_already_exported_turn_on", stem))
        last_glb = str(final)
        yield emit()
        return

    work.mkdir(parents=True, exist_ok=True)
    views = {k: v for k, v in (("front", front), ("back", back), ("left", left), ("right", right)) if v}
    for k, v in views.items():  # Gradio uploads live in a temp dir; keep our own copies
        shutil.copy2(v, work / f"source_{k}{Path(v).suffix.lower()}")
    log.append(_t("ui.hunyuan3d_views_freeing_video_memory", ', '.join(views)))
    yield emit()
    unload_model()
    if not (yield from vram_gate(5500, log, emit, stem)):
        yield emit()
        return

    cmd = [HY_PY, str(T.ROOT / "hy_pipeline.py"), "--out", str(work),
           "--faces", str(int(hy_faces)), "--tex", str(int(hy_tex)), "--steps", str(int(hy_steps))]
    for k, v in views.items():
        cmd += [f"--{k}", v]
    if not paint:
        cmd.append("--no-texture")
    if hy_fast:
        cmd.append("--fast")
    env = dict(os.environ, HF_HOME=r"D:\conda\hf", HF_HUB_OFFLINE="1", HY3DGEN_MODELS=r"D:\conda\hy3dgen",
               TMP=r"D:\conda\tmp", TEMP=r"D:\conda\tmp", PYTHONIOENCODING="utf-8", PYTHONUNBUFFERED="1")
    t0 = time.time()
    for attempt in range(3):
        code, tail, crashed_early = yield from _hy_run(cmd, env, log, live, emit)
        if code == 0 or not crashed_early:
            break
        # a native crash (0xC0000005 / 0xC0000409) while the model loads happens now and then on this machine and
        # goes away on a plain retry; the shape itself was not started, so nothing is lost
        log.append(_t("ui.hunyuan_crashed_while_loading_the", code, attempt + 2))
        yield emit()
    live[0] = ""
    if code != 0 and paint and (work / "shape.glb").exists() and not (work / "textured.glb").exists():
        # the shape is done, only the paint stage fell over (it loads the heaviest models): paint it alone
        log.append(_t("ui.painting_crashed_code_the_shape_is", code))
        yield emit()
        for attempt in range(2):
            r = subprocess.run([HY_PY, str(T.ROOT / "hy_texture_mv.py"), str(work / "shape.glb"),
                                str(work / "view_front.png"), str(work / "textured.glb"), "--tex", str(int(hy_tex))],
                               cwd=HY_SRC, env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if (work / "textured.glb").exists():
                log.append(_t("ui.texture_ready"))
                code = 0
                break
            tail = deque((r.stdout + r.stderr).splitlines()[-8:], maxlen=25)
        yield emit()
    if code != 0:
        log.append(_t("ui.error_the_hunyuan_process_ended_with", code))
        log += [f"  {x}" for x in list(tail)[-8:]]
        log.append(_t("ui.a_frequent_cause_is_too_little_video"))
        yield emit()
        return

    src = work / "textured.glb"
    textured = src.exists()
    if not textured:
        src = work / "shape.glb"
    if not src.exists():
        log.append(_t("ui.error_the_model_was_not_made_see_the"))
        yield emit()
        return
    if not textured and paint:
        log.append(_t("ui.warning_painting_failed_the_shape"))
    h = height if height and height > 0 else None
    if h is None and preset.get("height_m") is None:
        log.append(_t("ui.no_height_set_the_size_stays_as_the"))
    pp = dict(
        height=h, pivot=PIVOT_LABELS[pivot_label],
        metallic=metallic if override else None, roughness=roughness if override else None,
        width=width if width and width > 0 else None, depth=depth if depth and depth > 0 else None,
        collision=COLLISION_LABELS[collision_label], collision_faces=cfg.get("collision_faces", 800),
        color_refs=[str(work / f"view_{k}.png") for k in views],
        color_strength=color_match, saturation=saturation, brightness=brightness,
        materials="auto" if auto_materials else None, category=category)
    stats = pp_call(src, final, preset, pp)
    save_pp(work, stem, category, src, final, pp)
    try:
        stats.update(json.loads((work / "hy_stats.json").read_text(encoding="utf-8")))
    except Exception:  # noqa: BLE001
        pass
    stats.update(engine="hunyuan3d-2mv", textured=textured, category=category, source=str(work),
                 seconds=round(time.time() - t0, 1))
    (final.parent / f"{stem}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    previews = [(str(work / f"view_{k}.png"), k) for k in views if (work / f"view_{k}.png").exists()]
    last_glb = str(final)
    results.append([stem, category_label, stats["faces"], " x ".join(map(str, stats["size_m"])),
                    stats["seconds"], str(final)])
    log.append(_t("ui.done_in_s_faces", stats['seconds'], stats['faces'], 'с текстурой' if textured else 'без текстуры', final))
    if make_preview:
        yield emit()
        previews = make_previews(final, work, stem, cfg, log) + previews
    if auto_rig:
        if category == "character":
            yield emit()
            rigged = yield from rig_queue_run([(final, stem)], cfg, rig_naming_label, rig_tries, log, emit)
            if rigged:
                last_glb = rigged[-1]
        else:
            log.append(_t("ui.skeletons_are_made_only_for_the", stem))
    yield emit()


def _tr_run(cmd, env, cwd, log, live, emit, t0):
    """One trellis-cli run: its stages into the log, the flow's steps as the live line.
    Generator; returns (exit code, the last lines of its output)."""
    tail = deque(maxlen=25)
    stage = re.compile(r"^\[(\d)/\d\]\s")
    step = re.compile(r"\[flow\]\s+\[[#.]*\]\s+(\d+)/(\d+)")
    proc = subprocess.Popen(cmd, cwd=str(cwd), env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, encoding="utf-8", errors="replace",
                            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for line in proc.stdout:
        s = line.strip()
        m = stage.match(s)
        if m:
            live[0] = ""
            log.append(_t("ui.trellis_stage", time.time() - t0, _t(f"ui.trellis_stage_{m.group(1)}")))
            yield emit()
            continue
        m = step.search(s)
        if m:
            live[0] = _t("ui.trellis_step", m.group(1), m.group(2))
            yield emit()
            continue
        if s and not s.startswith("[trellis:dbg]"):
            tail.append(s)
    return proc.wait(), tail


def generate_trellis(files, category_label, name, height, width, depth, pivot_label, collision_label, override,
                     metallic, roughness, overwrite, make_preview=False, color_match=TRELLIS_COLOR_MATCH,
                     saturation=1.0, brightness=1.0, auto_materials=False, auto_rig=False, rig_naming_label=None,
                     rig_tries=3, tr_faces=50000, tr_seed=42):
    """TRELLIS.2 (trellis.cpp): one picture -> a textured GLB with its own metal/roughness map. A separate process
    per picture (VRAM is freed on exit); res 512 path, the 1024 cascade needs a 16 GB card. A picture with alpha is
    kept as cut out, others go through its BiRefNet; that cutout is the palette reference."""
    cfg = T.load_config()
    category = LABEL_TO_KEY[category_label]
    preset = cfg["categories"][category]
    log, results, last_glb, previews = [], [], None, []
    live = [""]
    rig_queue = []

    def emit():
        lines = log + ([live[0]] if live[0] else [])
        return "\n".join(lines), results, last_glb, previews

    if not files:
        log.append(_t("ui.add_at_least_one_picture_first"))
        yield emit()
        return
    exe = Path(cfg.get("trellis_exe") or TRELLIS_EXE)
    models = Path(cfg.get("trellis_models") or TRELLIS_MODELS)
    missing = [f"{w}.gguf" for w in TRELLIS_WEIGHTS if not (models / f"{w}.gguf").exists()]
    if not exe.exists():
        log.append(_t("ui.trellis_no_exe", exe))
        yield emit()
        return
    if missing:
        log.append(_t("ui.trellis_no_weights", models, ", ".join(missing)))
        yield emit()
        return
    paths = T.collect_images([f if isinstance(f, str) else f.name for f in files])
    log.append(_t("ui.trellis_pictures", len(paths), category_label))
    if category == "building":
        log.append(_t("ui.trellis_building_note"))
    yield emit()
    unload_model()
    env = dict(os.environ, TMP=r"D:\conda\tmp", TEMP=r"D:\conda\tmp",
               PATH=str(cfg.get("trellis_cuda_bin") or TRELLIS_CUDA_BIN) + os.pathsep + os.environ.get("PATH", ""))

    for img_path in paths:
        stem = T.slug(name if (name and len(paths) == 1) else img_path.stem)
        work = Path(cfg["work_dir"]) / "trellis" / category / stem
        final = Path(cfg["export_dir"]) / category / stem / f"{stem}.glb"
        if final.exists() and not overwrite:
            log.append(_t("ui.skip_already_exported_turn_on", stem))
            last_glb = str(final)
            yield emit()
            continue
        try:
            t0 = time.time()
            work.mkdir(parents=True, exist_ok=True)
            src_copy = work / f"source{img_path.suffix.lower()}"  # Gradio's upload folder gets cleaned
            shutil.copy2(img_path, src_copy)
            raw = work / "raw.glb"
            cutout = work / "raw_cutout.png"  # --dump-bg: the picture as the model saw it
            for old in (raw, cutout):
                if old.exists():
                    old.unlink()
            if not (yield from vram_gate(TRELLIS_VRAM_MB, log, emit, stem)):
                raise RuntimeError(_t("ui.not_enough_free_video_memory"))
            cmd = [str(exe), str(src_copy), str(raw), "--models", str(models), "--res", "512",
                   "--faces", str(int(tr_faces)), "--seed", str(int(tr_seed)), "--webp", "off",
                   "--require-gpu", "--dump-bg"]
            log.append(_t("ui.trellis_generating", stem))
            yield emit()
            code, tail = yield from _tr_run(cmd, env, work, log, live, emit, t0)
            live[0] = ""
            if code != 0 or not raw.exists():
                log.append(_t("ui.trellis_failed", stem, code))
                log += [f"  {x}" for x in list(tail)[-8:]]
                yield emit()
                continue
            if (work / "raw.ply").exists():  # trellis-cli always dumps the raw mesh too (28-150 MB), nothing reads it
                (work / "raw.ply").unlink()
            ref = cutout if cutout.exists() else src_copy
            previews.append((str(ref), stem))
            pp = dict(
                height=height if height and height > 0 else None, pivot=PIVOT_LABELS[pivot_label],
                metallic=metallic if override else None, roughness=roughness if override else None,
                width=width if width and width > 0 else None, depth=depth if depth and depth > 0 else None,
                collision=COLLISION_LABELS[collision_label], collision_faces=cfg.get("collision_faces", 800),
                rotate_y=0.0,  # faces +Z already, like glTF and Hunyuan
                color_refs=[str(ref)], color_strength=color_match, saturation=saturation, brightness=brightness,
                materials="auto" if auto_materials else None, category=category)
            stats = pp_call(raw, final, preset, pp)
            save_pp(work, stem, category, raw, final, pp)
            stats.update(engine="trellis2", source=str(src_copy), category=category,
                         seconds=round(time.time() - t0, 1), faces_target=int(tr_faces), seed=int(tr_seed))
            (final.parent / f"{stem}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
            last_glb = str(final)
            results.append([stem, category_label, stats["faces"], " x ".join(map(str, stats["size_m"])),
                            stats["seconds"], str(final)])
            log.append(_t("ui.done_in_s_faces", stats["seconds"], stats["faces"], _t("ui.trellis_textured"), final))
            if make_preview:
                yield emit()
                previews += make_previews(final, work, stem, cfg, log)
            if auto_rig:
                if category == "character":
                    rig_queue.append((final, stem))
                else:
                    log.append(_t("ui.skeletons_are_made_only_for_the", stem))
        except Exception as e:  # noqa: BLE001
            log.append(_t("ui.error_4", stem, type(e).__name__, e))
        yield emit()
    if rig_queue:
        log.append(_t("ui.generation_finished_making_skeletons", len(rig_queue)))
        yield emit()
        rigged = yield from rig_queue_run(rig_queue, cfg, rig_naming_label, rig_tries, log, emit)
        if rigged:
            last_glb = rigged[-1]
    log.append(_t("ui.done"))
    yield emit()


COLLISION_SUFFIXES = ("-colonly", "-convcolonly")


def viewer_glb(path):
    """The model as the result viewer should show it. The viewer draws every mesh of the file, and a prop's
    collision proxy (`<name>-convcolonly` / `-colonly`: Godot makes a StaticBody of it and never draws it) covered
    the model with a grey hull - a character came out as «a geometric figure». A copy in work_dir/_viewer with
    those nodes unhooked from the scene (the export itself stays as it is); the path as it was when there are none."""
    if not path or not str(path).lower().endswith(".glb"):
        return path
    try:
        import struct
        b = Path(path).read_bytes()
        jl = struct.unpack("<I", b[12:16])[0]
        j = json.loads(b[20:20 + jl])
        col = {i for i, n in enumerate(j.get("nodes", [])) if str(n.get("name", "")).endswith(COLLISION_SUFFIXES)}
        if not col:
            return path
        for n in j["nodes"]:
            if "children" in n:
                n["children"] = [c for c in n["children"] if c not in col]
                if not n["children"]:
                    del n["children"]
        for s in j.get("scenes", []):
            s["nodes"] = [c for c in s.get("nodes", []) if c not in col]
        js = json.dumps(j, separators=(",", ":")).encode("utf-8")
        js += b" " * (-len(js) % 4)
        out = bytearray(b[:12] + struct.pack("<I", len(js)) + b"JSON" + js + b[20 + jl:])
        out[8:12] = struct.pack("<I", len(out))
        p = Path(path)
        dst = Path(T.load_config()["work_dir"]) / "_viewer" / f"{p.parent.name}__{p.name}"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(bytes(out))
        return str(dst)
    except Exception:   # (the viewer then shows the file as it is)
        return path


def _viewer_outputs(gen):
    """A generator of (log, table, model, gallery) with the model swapped for viewer_glb's copy"""
    for out in gen:
        out = list(out)
        out[2] = viewer_glb(out[2])
        yield tuple(out)


def run(engine, files, f_front, f_back, f_left, f_right, category, name, height, width, depth, pivot,
        collision, override, metallic, roughness, tex_res, fg_ratio, remove_bg, remesh, overwrite,
        hy_tex, hy_faces, hy_steps, paint, make_preview, color_match, saturation, brightness,
        auto_materials, auto_rig, rig_naming_label, rig_tries, hy_fast=False, tr_faces=50000, tr_seed=42,
        progress=gr.Progress()):
    if engine == ENGINE_TR:
        yield from _viewer_outputs(generate_trellis(
            files, category, name, height, width, depth, pivot, collision, override, metallic, roughness,
            overwrite, make_preview, color_match, saturation, brightness, auto_materials,
            auto_rig, rig_naming_label, rig_tries, tr_faces=tr_faces, tr_seed=tr_seed))
    elif engine == ENGINE_HY:
        yield from _viewer_outputs(generate_hy(
            f_front, f_back, f_left, f_right, category, name, height, width, depth, pivot,
            collision, override, metallic, roughness, hy_tex, hy_faces, hy_steps, paint,
            overwrite, make_preview, color_match, saturation, brightness, auto_materials,
            auto_rig, rig_naming_label, rig_tries, hy_fast=hy_fast))
    else:
        yield from _viewer_outputs(generate(
            files, category, name, height, width, depth, pivot, collision, override,
            metallic, roughness,
            tex_res, fg_ratio, remove_bg, remesh, overwrite, make_preview,
            color_match, saturation, brightness, auto_materials,
            auto_rig, rig_naming_label, rig_tries, progress=progress))


# ------------------------------------------------------------------ пакетная обработка
IMAGE_EXT = T.IMAGE_EXT
VIEW_NAMES = ("front", "back", "left", "right")


def scan_batch(root, default_category="prop"):
    """Find jobs under root.

    Layout:  <root>/<category>/<image>            -> SF3D job (one picture)
             <root>/<category>/<asset>/front.png  -> Hunyuan job (front/back/left/right.png)
    <category> is item / prop / building / character. Folders with other names use default_category.
    """
    cfg = T.load_config()
    cats = set(cfg["categories"])
    root = Path(root)
    jobs = []

    def views_in(d):
        found = {}
        for f in sorted(d.iterdir()):
            if f.suffix.lower() in IMAGE_EXT and f.stem.lower() in VIEW_NAMES:
                found[f.stem.lower()] = str(f)
        return found

    def scan_dir(d, category):
        for f in sorted(d.iterdir()):
            if f.is_file() and f.suffix.lower() in IMAGE_EXT and f.stem.lower() not in VIEW_NAMES:
                jobs.append(dict(kind="sf3d", category=category, name=T.slug(f.stem), files=[str(f)]))
            elif f.is_dir():
                v = views_in(f)
                if "front" in v:
                    jobs.append(dict(kind="hy", category=category, name=T.slug(f.name), views=v))

    if not root.is_dir():
        return jobs
    scan_dir(root, default_category)  # loose images and asset folders directly in root
    for d in sorted(p for p in root.iterdir() if p.is_dir()):
        if d.name.lower() in cats:
            scan_dir(d, d.name.lower())
    # an asset folder placed directly in root was already picked up by scan_dir(root, ...)
    # drop duplicates (a category folder is never itself an asset)
    jobs = [j for j in jobs if not (j["kind"] == "hy" and j["name"] in cats)]
    jobs.sort(key=lambda j: j["kind"] != "sf3d")  # all SF3D jobs first: one model load, then Hunyuan
    return jobs


def batch_table(jobs):
    cfg = T.load_config()
    rows = []
    for j in jobs:
        done = (Path(cfg["export_dir"]) / j["category"] / j["name"] / f"{j['name']}.glb").exists()
        src = ", ".join(j["views"]) if j["kind"] == "hy" else Path(j["files"][0]).name
        rows.append([j["name"], CATEGORY_LABELS[j["category"]],
                     "Hunyuan3D" if j["kind"] == "hy" else "SF3D", src, _t("ui.already_done") if done else _t("ui.queued")])
    return rows


def on_scan(root, default_label):
    jobs = scan_batch(root, LABEL_TO_KEY[default_label])
    if not jobs:
        return [], _t("ui.nothing_found_a_folder_like_this_is")
    n_hy = sum(j["kind"] == "hy" for j in jobs)
    est = (len(jobs) - n_hy) * 0.5 + n_hy * 10
    return batch_table(jobs), _t("ui.found_sf3d_hunyuan3d_estimated_time", len(jobs), len(jobs) - n_hy, n_hy, est)


def batch_run(root, default_label, overwrite, make_preview, auto_materials=False,
              auto_rig=False, rig_naming_label=None, rig_tries=3, progress=None):
    """Run every job found under root, one after another; a failure does not stop the queue.
    With auto_rig, characters get a skeleton in a last phase (after every model is generated)."""
    cfg = T.load_config()
    jobs = scan_batch(root, LABEL_TO_KEY[default_label])
    log, results, last_glb, previews = [], [], None, []
    if not jobs:
        yield _t("ui.nothing_found_check_the_folder_and"), results, last_glb, previews
        return
    quiet = lambda *a, **k: None  # noqa: E731
    ok = skipped = failed = 0
    failed_names = []
    t_start = time.time()
    log.append(_t("ui.batch_jobs_sf3d_first_then_hunyuan3d", len(jobs)))
    yield "\n".join(log), results, last_glb, previews
    for i, j in enumerate(jobs, 1):
        cat_label = CATEGORY_LABELS[j["category"]]
        final = Path(cfg["export_dir"]) / j["category"] / j["name"] / f"{j['name']}.glb"
        head = f"[{i}/{len(jobs)}] {j['name']} ({'Hunyuan3D' if j['kind'] == 'hy' else 'SF3D'}, {cat_label})"
        if final.exists() and not overwrite:
            log.append(_t("ui.already_done_skipping", head))
            skipped += 1
            yield "\n".join(log), results, last_glb, previews
            continue
        log.append(_t("ui.starting", head))
        base = len(log)
        if j["kind"] == "sf3d":
            inner = generate(j["files"], cat_label, j["name"], 0, 0, 0, _t("ui.auto_by_category"), _t("ui.by_category"),
                             False, 0.0, 0.8, cfg["texture_resolution"], cfg["foreground_ratio"], True, "none",
                             overwrite, make_preview, 0.0, 1.0, 1.0, auto_materials, progress=quiet)
        else:
            v = j["views"]
            inner = generate_hy(v.get("front"), v.get("back"), v.get("left"), v.get("right"), cat_label,
                                j["name"], 0, 0, 0, _t("ui.auto_by_category"), _t("ui.by_category"), False, 0.0, 0.8,
                                2048, 50000, 50, True, overwrite, make_preview, 0.0, 1.0, 1.0, auto_materials)
        for ilog, irows, iglb, iprev in inner:
            live = log[:base] + [f"   {x}" for x in ilog.splitlines()[-3:]]
            yield "\n".join(live), results, last_glb, previews
            inner_state = (ilog, irows, iglb, iprev)
        ilog, irows, iglb, iprev = inner_state
        if final.exists():
            ok += 1
            results += irows
            last_glb = str(final)
            previews = iprev
            log.append(_t("ui.done_3", head))
        else:
            failed += 1
            failed_names.append(j["name"])
            log.append(_t("ui.failed", head))
            log += [f"   {x}" for x in ilog.splitlines()[-4:]]
        yield "\n".join(log), results, last_glb, previews
    rig_ok = rig_failed = 0
    if auto_rig:
        todo = []
        for j in jobs:
            if j["category"] != "character":
                continue
            fin = Path(cfg["export_dir"]) / j["category"] / j["name"] / f"{j['name']}.glb"
            if fin.exists() and (overwrite or not fin.with_name(f"{j['name']}_rigged.glb").exists()):
                todo.append((fin, j["name"]))
        if todo:
            log.append(_t("ui.skeletons_for_characters", len(todo)))
            yield "\n".join(log), results, last_glb, previews
            rig_log = log  # rig_core appends to it directly
            emit_b = lambda: ("\n".join(log), results, last_glb, previews)  # noqa: E731
            rigged = yield from rig_queue_run(todo, cfg, rig_naming_label, rig_tries, rig_log, emit_b)
            rig_ok = len(rigged)
            rig_failed = len(todo) - rig_ok
            if rigged:
                last_glb = rigged[-1]
    mins = (time.time() - t_start) / 60
    log.append(_t("ui.total_in_min_done_skipped_errors", mins, ok, skipped, failed)
               + (f" ({', '.join(failed_names)})" if failed_names else "")
               + (_t("ui.skeletons_of", rig_ok, rig_ok + rig_failed) if auto_rig and (rig_ok + rig_failed) else ""))
    yield "\n".join(log), results, last_glb, previews


# ------------------------------------------------------------------ риггинг
RIG_NAMINGS = {_t("lm.mixamo_for_mixamo_animations"): "mixamo", _t("lm.godot_humanoid_profile"): "godot"}


# ---------------------------------------------------------------- the current character: one choice for every tool
# of the «Character» tab. A character is a folder export/<category>/<name>/ with its model: <name>.glb (the source),
# <name>_landmarks_rigged.glb / <name>_rigged.glb (with a skeleton), <name>_parts.glb (the body in parts, for whole
# sets), its lip-sync clips and the pieces put on. Every tab takes its file from it; a tab's own «load a file» stays
# for a one-off job on a model that is not a character
def _char_files(value):
    """{name, dir, source, rigged, parts} of the character "category/name" (None for what it lacks)."""
    if not value or "/" not in value:
        return None
    cat, nm = value.split("/", 1)
    d = Path(T.load_config()["export_dir"]) / cat / nm
    first = lambda *ns: next((d / n for n in ns if (d / n).exists()), None)  # noqa: E731
    src = first(f"{nm}.glb")
    landmark, auto = first(f"{nm}_landmarks_rigged.glb"), first(f"{nm}_rigged.glb")
    rigged = landmark or auto
    if rigged is None and src is not None and landmarks.has_skin(src):   # a model loaded with its skeleton: it is the rig
        rigged = auto = src
    return {"name": nm, "dir": d, "source": src, "rigged": rigged, "landmark": landmark, "auto": auto,
            "parts": first(f"{nm}_parts.glb")}


def _char_counts(f):
    return (len(list(f["dir"].glob("*.face.json"))),
            len([g for _, g, _ in WF.items_in(f["dir"]) if g is not None]) + len([x for x in f["dir"].glob("*_wear_*.glb") if not x.name.endswith(".src.glb")]))


# what a character has, as icons (the list shows plain text: emoji); the legend is under the list's label
ICON = {"landmark": "🦴", "auto": "🤖", "parts": "🧩", "none": "○", "cut": "👄", "plate": "💬", "retopo": "🕸", "eyes": "👁",
        "clips": "🎙", "worn": "🛡"}
CR_ICON = {"rig": "🐾"}   # a creature with its skeleton (the «Creatures» section's list)


def _face_icons(s):
    """The face of a built model: its mouth (cut / plate), the retopology and the eyes, as icons ('' without a face)."""
    return "".join(ICON[k] for k, on in (("cut", s.get("mouth") == "cut"), ("plate", s.get("mouth") == "plate"),
                                          ("retopo", s.get("retopo")), ("eyes", s.get("eyes"))) if on)


def _char_tags(f):
    """What the character has, for its line in the list: «🦴👄🕸👁 🤖 🎙2 🛡4»."""
    tags = []
    if f.get("landmark"):
        tags.append(ICON["landmark"] + _face_icons(landmarks.rig_summary(f["landmark"])))
    if f.get("auto"):
        tags.append(ICON["auto"])
    if f.get("parts"):
        tags.append(ICON["parts"])
    if not tags:
        tags.append(ICON["none"])
    clips, worn = _char_counts(f)
    if clips:
        tags.append(f"{ICON['clips']}{clips}")
    if worn:
        tags.append(f"{ICON['worn']}{worn}")
    return " ".join(tags)


def _characters(creatures=False):
    """[(label, "category/name")]: every folder of export/character with a model, and any other export folder with a
    skeleton or a body in parts - but the creatures (their skeleton's passport says so: the «Creatures» section).
    creatures=True: the creatures, and the models of export/character with no skeleton yet (either may take them)."""
    ex, out = Path(T.load_config()["export_dir"]), []
    for d in sorted(x for x in ex.glob("*/*") if x.is_dir()):
        f = _char_files(f"{d.parent.name}/{d.name}")
        crt = CR.is_creature(d, d.name)
        if creatures:
            if d.parent.name != "character" or not (f["rigged"] or f["source"]) or not (crt or not f["rigged"]):
                continue
            out.append((f"{d.name}   {CR_ICON['rig'] if crt and f['rigged'] else ICON['none']}", f"character/{d.name}"))
        elif (not crt or (f["rigged"] and CR.is_humanoid(f["rigged"]))) and (f["rigged"] or f["parts"] or (d.parent.name == "character" and f["source"])):
            # (a creature with a humanoid's skeleton: in both lists - its jaw there, its clips and armour here)
            nm = d.name if d.parent.name == "character" else f"{d.name} ({d.parent.name})"
            out.append((f"{nm}   {_char_tags(f)}", f"{d.parent.name}/{d.name}"))
    return out


def _char_memo():
    return Path(T.load_config()["work_dir"]) / "current_character.txt"


def _char_default():
    """The character chosen last time (kept in work_dir), else the first with a skeleton."""
    chars = _characters()
    try:
        last = _char_memo().read_text(encoding="utf-8").strip()
    except OSError:
        last = ""
    if any(v == last for _, v in chars):
        return last
    return next((v for _, v in chars if (_char_files(v) or {}).get("rigged")), chars[0][1] if chars else None)


def char_remember(value):
    if value:
        try:
            _char_memo().write_text(value, encoding="utf-8")
        except OSError:
            pass


def char_info(value):
    """What the character has - its folder, every file with its date and what it is (for a built skeleton: its
    bones and face), which model the tools take - and that model for the 3D view (the skeleton's when it has one)."""
    f = _char_files(value)
    if not f:
        return _t("ui.char_none"), None
    from datetime import datetime
    when = lambda p: datetime.fromtimestamp(p.stat().st_mtime).strftime("%d.%m %H:%M")  # noqa: E731
    lines = [_t("ui.char_folder", f["dir"])]
    if f["source"] and f["source"] != f.get("auto"):
        lines.append(_t("ui.char_file_source", f["source"].name, when(f["source"])))
    for key, label in (("landmark", "ui.char_file_landmarks"), ("auto", "ui.char_file_auto")):
        p = f.get(key)
        if p:
            s = landmarks.rig_summary(p)
            fw = _face_icons(s)
            lines.append(_t(label, p.name, when(p), s.get("bones", 0)) + (" · " + fw if fw else "")
                         + (" · " + _t("ui.char_face_edits") if p.with_name(landmarks._stem(p) + "_face_edits.json").exists() else ""))
    if f["parts"]:
        lines.append(_t("ui.char_file_parts", f["parts"].name, when(f["parts"])))
    clips, worn = _char_counts(f)
    lines.append(_t("ui.char_counts", clips, worn))
    if f["rigged"]:
        lines.append(_t("ui.char_tools_take", f["rigged"].name))
    return ("\n".join("- " + x if i else x for i, x in enumerate(lines)),
            str(f["rigged"] or f["source"] or f["parts"]) if (f["rigged"] or f["source"] or f["parts"]) else None)


def _delete_model(value) -> bool:
    """A character's or a creature's folder under export/ deleted for good (its «Delete» confirmed in the page): the
    models, skeleton, face, pieces and clips made here; the file it was loaded from stays where it was."""
    f = _char_files(value)
    root = Path(T.load_config()["export_dir"]).resolve()
    if not f or not f["dir"].is_dir() or f["dir"].resolve().parent.parent != root:   # only a character's own folder
        return False
    shutil.rmtree(f["dir"])
    return True


def _add_model(upload):
    """A model loaded: export/character/<name>/<name>.glb ("character/<name>", or None)."""
    if not upload:
        return None
    src = Path(upload if isinstance(upload, str) else upload.name)
    if WF.is_piece_file(src):   # a piece put on a character (its result, its source): not a character
        gr.Warning(_t("ui.char_add_piece", src.name))
        return None
    stem = re.sub(r"_(landmarks_)?rigged$", "", src.stem)
    root = Path(T.load_config()["export_dir"]) / "character"
    # its folder: one of the file's own name if there is one already (a build of the same file made it), else the
    # name made safe
    name = stem if (root / stem).is_dir() else T.slug(stem)
    d = root / name
    rigged = stem != src.stem and landmarks.has_skin(src)   # a skeleton made here: the same character, not a new one
    dst = d / (f"{name}{src.stem[len(stem):]}.glb" if rigged else f"{name}.glb")
    if src.resolve() != dst.resolve() and not (dst.exists() and dst.stat().st_size == src.stat().st_size
                                               and dst.read_bytes() == src.read_bytes()):
        d.mkdir(parents=True, exist_ok=True)
        if dst.exists():   # another file of the same name: the old one kept beside it
            shutil.copy2(dst, dst.with_name(dst.stem + ".prev.glb"))
        shutil.copy2(src, dst)
    return f"character/{name}"


def _asset_src(asset):
    """A model picked as "category/name": its source, else its skeleton's model (a source loaded once and never kept)."""
    f = _char_files(asset)
    if not f:
        return None
    return f["source"] or f["rigged"] or f["dir"] / f"{f['name']}.glb"


def _export_assets():
    cfg = T.load_config()
    out = []
    for p in sorted(Path(cfg["export_dir"]).rglob("*.glb")):
        if p.stem.endswith("_rigged"):
            continue
        out.append(f"{p.parent.parent.name}/{p.stem}")
    return out


def rig_core(src, dst, name, cfg, naming_key, tries, log, emit, kind="humanoid"):
    """Skeleton + weights + standard names for one GLB. Shared by the rigging accordion, the generation flow
    and the batch. A generator (use `yield from`); returns the result dict, or None if it failed."""
    import rigging as RG

    src, dst = Path(src), Path(dst)
    unload_model()  # free the SF3D copy: UniRig needs ~3.5 GB of the 8
    if not (yield from vram_gate(4500, log, emit, name)):
        return None
    try:
        j, _ = RG._read_glb(src)
        has_rig = bool(j.get("skins"))
    except Exception:  # noqa: BLE001
        has_rig = False
    if has_rig:
        log.append(_t("ui.the_file_already_has_a_skeleton_it", name))
    log.append(_t("ui.rigging_started_it_takes_3_5_minutes", name))
    yield emit()
    t0 = time.time()
    result = None
    try:
        for item, done in RG.rig_steps(src, dst, naming_key, name, strip=has_rig,
                                       blender=cfg.get("blender_exe"), tries=int(tries), kind=kind):
            if done:
                result = item
            else:
                log.append(f"[{name}] {item}")
                yield emit()
        info = result["info"]
        if kind != "humanoid":
            log.append(_t("ui.skeleton_ready_in_s_bones", name, time.time() - t0, info.get('bones', '?')))
            yield emit()
            return result
        fing = info.get("named_fingers", 0)
        log.append(_t("ui.skeleton_ready_in_s_bones_standard", name, time.time() - t0, info.get('bones', '?'), len(result['mapping']))
                   + (_t("ui.of_them_finger_bones", fing) if fing else _t("ui.this_skeleton_has_no_fingers_you_can")))
        sm = info.get("seams")
        if sm:
            log.append(_t("ui.seams_between_parts_stitched_places", name, sm['clusters'], sm['gap_before_mm'], sm['gap_after_mm']))
        if info.get("warning"):
            log.append(_t("ui.warning", name, info['warning']))
        log.append(_t("ui.file_with_the_skeleton", name, dst))
        (dst.parent / f"{name}_rig.json").write_text(
            json.dumps(dict(source=str(src), naming=naming_key, **result), indent=2, ensure_ascii=False),
            encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.append(_t("ui.rigging_error", name, type(e).__name__, e))
        result = None
    yield emit()
    return result


def seam_run(upload, asset):
    """The 'Починить стыки' button: for any rigged GLB (e.g. from Tripo/Mixamo) with several mesh parts."""
    import rigging as RG

    cfg = T.load_config()
    log, last = [], [None]

    def emit():
        return "\n".join(log), last[0]

    if upload:
        src = Path(upload if isinstance(upload, str) else upload.name)
    elif asset:
        src = _asset_src(asset)
    else:
        log.append(_t("ui.choose_a_finished_model_or_load_a_3"))
        yield emit()
        return
    dst = src.with_name(f"{src.stem}_seams.glb")
    log.append(_t("ui.stitching_the_seams_about_30_seconds", src.name))
    yield emit()
    try:
        sm = RG.weld_seams(src, dst, cfg.get("blender_exe"))
    except Exception as e:  # noqa: BLE001
        sm = None
        log.append(_t("ui.error", type(e).__name__, e))
    if sm:
        log.append(_t("ui.done_seams_gap_in_the_test_pose_mm", sm['clusters'], sm['gap_before_mm'], sm['gap_after_mm'], dst))
        last[0] = str(dst)
    elif not log or not log[-1].startswith(_t("ui.error_5")):
        log.append(_t("ui.no_seams_between_parts_found_the"))
    yield emit()


def split_run(upload, asset):
    """The 'Разбить на части' button: body regions as separate meshes on one skeleton (for modular armour)."""
    import rigging as RG

    cfg = T.load_config()
    log, last = [], [None]

    def emit():
        return "\n".join(log), last[0]

    if upload:
        src = Path(upload if isinstance(upload, str) else upload.name)
    elif asset:
        f = _char_files(asset)
        src = f["rigged"] or f["source"] or f["dir"] / f"{f['name']}.glb"
    else:
        log.append(_t("ui.choose_a_model_with_a_skeleton_or"))
        yield emit()
        return
    dst = src.with_name(f"{src.stem.removesuffix('_rigged')}_parts.glb")
    log.append(_t("ui.splitting_into_parts_about_15", src.name))
    yield emit()
    try:
        parts = RG.split_parts(src, dst, cfg.get("blender_exe"))
        log.append(_t("ui.done_parts_on_a_shared_skeleton", len(parts))
                   + ", ".join(_t("ui.tris", k.replace('Body_', ''), v) for k, v in parts.items()))
        log.append(_t("ui.file", dst))
        (dst.with_suffix(".parts.json")).write_text(
            json.dumps(dict(source=str(src), parts=parts), indent=2, ensure_ascii=False), encoding="utf-8")
        last[0] = str(dst)
    except Exception as e:  # noqa: BLE001
        log.append(_t("ui.error_2", e))
    yield emit()


def _src_of(upload, asset):
    """(path, name, dst folder) of the model chosen in a tab: an uploaded GLB or a ready model."""
    cfg = T.load_config()
    if upload:
        src = Path(upload if isinstance(upload, str) else upload.name)
        name = T.slug(src.stem)
        return src, name, Path(cfg["export_dir"]) / "character" / name
    if asset:
        src = _asset_src(asset)
        return src, T.slug(asset.split("/", 1)[1]), src.parent
    return None, None, None


def preview_pick(upload, asset):
    """Show the chosen model in the tab's 3D view right away: the GLB loaded, else the character as the bar shows it."""
    if not upload:
        return char_info(asset)[1] if asset and "/" in asset else None
    src, _, _ = _src_of(upload, asset)
    return str(src) if src and src.exists() else None


def creature_run(upload, asset, line_mm=0, hinge_mm=0):
    """'Создать скелет' for creatures: UniRig skeleton, automatic bone names, a jaw from the mouth line."""
    import rigging as RG

    cfg = T.load_config()
    log, last, pics, state = [], [None], [[]], [None]

    def emit():
        return "\n".join(log), last[0], pics[0], state[0]

    src, name, folder = _src_of(upload, asset)
    if not src or not src.exists():
        log.append(_t("ui.choose_a_finished_model_or_load_a"))
        yield emit()
        return
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f"{name}_unirig.glb"
    result = yield from rig_core(src, raw, name, cfg, "mixamo", 1, log, emit, kind="creature")
    if not result:
        yield emit()
        return
    log.append(_t("ui.reading_the_skeleton_where_the_paws", name))
    yield emit()
    try:
        auto = folder / f"{name}_auto.glb"
        names, jaw = RG.creature_auto(raw, auto, cfg.get("blender_exe"))
        legs = sorted({v[:6] for v in names.values() if v.startswith("leg_")})
        tails = sum(1 for v in names.values() if v.startswith("tail_"))
        log.append(_t("ui.paws_tail_bones_head", name, ', '.join(x[4:] for x in legs), tails, 'есть' if 'head' in names.values() else 'не найдена'))
        state[0] = dict(auto=str(auto), names=names, jaw=jaw, folder=str(folder), name=name)
        yield from _creature_jaw(state[0], line_mm, hinge_mm, log, last, pics, emit)
    except Exception as e:  # noqa: BLE001
        log.append(_t("ui.error_3", name, e))
    yield emit()


def _creature_jaw(st, line_mm, hinge_mm, log, last, pics, emit):
    import rigging as RG

    cfg = T.load_config()
    folder, name = Path(st["folder"]), st["name"]
    dst = folder / f"{name}_rigged.glb"
    log.append(_t("ui.making_the_jaw_mouth_line_mm_hinge", name, line_mm, hinge_mm))
    yield emit()
    res = RG.creature_finish(st["auto"], dst, cfg.get("blender_exe"), st["names"], st["jaw"], line_mm, hinge_mm,
                             preview=str(folder / f"{name}_jaw.png"))
    CR._noeyes(dst).unlink(missing_ok=True)   # (a new skeleton: the eyes made before it are of the old model)
    log.append(_t("ui.done_vertices_in_the_jaw_look_at_the", name, dst.name, res['jaw_vertices']))
    labels = {"0_side": _t("ui.closed_side"), "0_front": _t("ui.closed_front"), "30_side": _t("ui.open_side"),
              "30_front": _t("ui.open_front")}
    pics[0] = [(p, labels.get(Path(p).stem.split("_jaw_")[-1], "")) for p in res["previews"]]
    last[0] = str(dst)
    (folder / f"{name}_rig.json").write_text(json.dumps(dict(kind="creature", names=st["names"], jaw=st["jaw"],
                                                            line_mm=line_mm, hinge_mm=hinge_mm), indent=2,
                                                       ensure_ascii=False), encoding="utf-8")
    yield emit()


# ------------------------------------------------------------------ the «Creatures» section: the current creature
def _creature_memo():
    return Path(T.load_config()["work_dir"]) / "current_creature.txt"


def creature_remember(value):
    if value:
        try:
            _creature_memo().write_text(value, encoding="utf-8")
        except OSError:
            pass


def creature_rig(value):
    """«Create the skeleton» of the «Creatures» section: on the current creature (its log, its model, the jaw)."""
    for log, glb, pics, _ in creature_run(None, value):
        yield log, (glb or gr.update()), pics


def creature_steps(value, what):
    """A step on the current creature's skeleton (what: "restore"): the log, the model, the jaw's pictures."""
    f = _char_files(value) or {}
    lines = []
    try:
        if not f.get("rigged"):
            raise RuntimeError(_t("cr.view_needs_skeleton"))
        for line in {"restore": CR.restore}[what](T.load_config(), f["dir"], f["name"]):
            lines.append(line)
        return "\n".join(lines), str(f["dir"] / f"{f['name']}_rigged.glb"), CR.jaw_pictures(f["dir"], f["name"])
    except Exception as e:  # noqa: BLE001
        lines.append(_t("ui.error_2", e))
        return "\n".join(lines), gr.update(), gr.update()


def creature_straighten(value):
    """«Straighten the rest pose» of the current creature: the log, the model, the jaw's pictures."""
    f = _char_files(value) or {}
    lines = []
    try:
        if not f.get("rigged"):
            raise RuntimeError(_t("cr.view_needs_skeleton"))
        for line in CR.straighten(T.load_config(), f["dir"], f["name"]):
            lines.append(line)
            yield "\n".join(lines), gr.update(), gr.update()
        yield "\n".join(lines), str(f["dir"] / f"{f['name']}_rigged.glb"), CR.jaw_pictures(f["dir"], f["name"])
    except Exception as e:  # noqa: BLE001
        lines.append(_t("ui.error_2", e))
        yield "\n".join(lines), gr.update(), gr.update()


def creature_request(value, text):
    """The markup's request (its hidden textbox): the skeleton moved to the edited joints and skinned again, then its
    jaw - or only the jaw from the mouth's four points. Yields the log, the model, the jaw's pictures."""
    f = _char_files(value) or {}
    lines = []
    try:
        req = json.loads(text or "{}")
        if not f or not f.get("rigged"):
            raise RuntimeError(_t("cr.view_needs_skeleton"))
        cfg = T.load_config()
        act = req.get("action")
        steps = (CR.rebuild(cfg, f["dir"], f["name"], req) if act == "rebuild"
                 else CR.straighten(cfg, f["dir"], f["name"], req.get("pose") or {}) if act == "rest"
                 else CR.set_eyes(cfg, f["dir"], f["name"], req.get("eyes") or {}, rigged=f["rigged"]) if act == "eyes"
                 else CR.eyes_off(cfg, f["dir"], f["name"], rigged=f["rigged"]) if act == "eyes_off"
                 else CR.mark_jaw(cfg, f["dir"], f["name"], req.get("mouth") or {}, rigged=f["rigged"]))
        for line in steps:
            lines.append(line)
            yield "\n".join(lines), gr.update(), gr.update()
        yield "\n".join(lines), str(_char_files(value)["rigged"]), CR.jaw_pictures(f["dir"], f["name"])
    except Exception as e:  # noqa: BLE001
        lines.append(_t("ui.error_2", e))
        yield "\n".join(lines), gr.update(), gr.update()


def creature_clips_viewer(value):
    """The viewer on the creature's clips (<name>_clips.glb), its walk playing - or why there is none."""
    f = _char_files(value) or {}
    clips = f["dir"] / f"{f['name']}_clips.glb" if f else None
    if not clips or not clips.exists():
        return _t("cr.anim_view_none")
    return landmarks_ui._frame(CR.viewer_page(clips, title=f["name"], kind=_t("cr.kind_creature"), edit={"play": "walk"}))


def creature_animate(value, keys, picks):
    """«Put the clips on the creature»: the picked clips of every source; the log, then the viewer playing them."""
    f = _char_files(value) or {}
    lines = []
    try:
        if not f.get("rigged"):
            raise RuntimeError(_t("cr.view_needs_skeleton"))
        if CR.is_humanoid(f["rigged"]):
            raise RuntimeError(_t("cr.anim_humanoid"))
        for line in CR.animate(T.load_config(), f["dir"], f["name"], {k: list(p or []) for k, p in zip(keys, picks)}):
            lines.append(line)
            yield "\n".join(lines), gr.update()
        yield "\n".join(lines), creature_clips_viewer(value)
    except Exception as e:  # noqa: BLE001
        lines.append(_t("ui.error_2", e))
        yield "\n".join(lines), gr.update()


def creature_paint_view(value, current=""):
    """The colouring page on the current creature (or why there is none)."""
    f = _char_files(value) or {}
    if not f or not f.get("rigged"):
        return _t("cr.view_needs_skeleton")
    try:
        return landmarks_ui._frame(CR.paint_page(f["dir"], f["name"], current))
    except Exception as e:  # noqa: BLE001
        return _t("ui.error_2", e)


def creature_paint_request(value, text):
    """The colouring page's request (its hidden textbox): a variant kept (its baked pictures) or deleted. Yields the
    log, then the page again (the variant picked)."""
    f = _char_files(value) or {}
    lines = []
    try:
        req = json.loads(text or "{}")
        if not f:
            raise RuntimeError(_t("cr.none"))
        act = req.get("action")
        steps = (CR.paint_save(T.load_config(), f["dir"], f["name"], req) if act == "save"
                 else CR.paint_delete(f["dir"], f["name"], req.get("variant") or ""))
        for line in steps:
            lines.append(line)
            yield "\n".join(lines), gr.update()
        cur = (req.get("variant") or CR.paint_slug(req.get("title") or "")) if act == "save" else ""
        yield "\n".join(lines), creature_paint_view(value, cur)
    except Exception as e:  # noqa: BLE001
        lines.append(_t("ui.error_2", e))
        yield "\n".join(lines), gr.update()


def rig_run(upload, asset, naming_label, tries=3):
    """The 'Создать скелет' button."""
    cfg = T.load_config()
    log, last = [], [None]

    def emit():
        return "\n".join(log), last[0]

    if upload:
        src = Path(upload if isinstance(upload, str) else upload.name)
        name = T.slug(src.stem)
        dst = Path(cfg["export_dir"]) / "character" / name / f"{name}_rigged.glb"
    elif asset:
        nm = asset.split("/", 1)[1]
        src = _asset_src(asset)
        name = T.slug(nm)
        dst = src.with_name(f"{nm}_rigged.glb")
    else:
        log.append(_t("ui.choose_a_finished_model_or_load_a"))
        yield emit()
        return
    if not src.exists():
        log.append(_t("ui.file_not_found", src))
        yield emit()
        return
    result = yield from rig_core(src, dst, name, cfg, RIG_NAMINGS[naming_label], tries, log, emit)
    if result:
        last[0] = str(dst)
    yield emit()


# ------------------------------------------------------------------ перенос сета с одетой модели
MAX_SEGS = 24


def _outfit_work(model):
    cfg = T.load_config()
    return Path(cfg["work_dir"]) / "outfit" / T.slug(Path(model).stem)


def outfit_scan(model):
    """The 'Разобрать на сегменты' button: pictures of the segments and a slot guess for each."""
    import outfit as OF

    hidden = [gr.update(visible=False, value=None) for _ in range(MAX_SEGS)]
    if not model:
        return _t("ui.load_the_glb_of_a_dressed_model_with"), [], [], "", *hidden
    model = Path(model if isinstance(model, str) else model.name)
    cfg = T.load_config()
    try:
        segs = OF.scan(model, _outfit_work(model), cfg.get("blender_exe"))
    except Exception as e:  # noqa: BLE001
        return _t("ui.error_2", e), [], [], "", *hidden
    segs = segs[:MAX_SEGS]
    dd = [gr.update(visible=True, value=s["label"], label=_t("ui.faces", s['name'], s['faces'])) for s in segs]
    dd += hidden[len(segs):]
    pics = [(s["thumb"], f"{s['name']}") for s in segs]
    note = (_t("ui.segments_check_the_slots_under_the", len(segs)))
    return note, pics, [s["name"] for s in segs], T.slug(model.stem), *dd


def outfit_run(model, body, set_name, names, *labels):
    """The 'Перенести сет' button."""
    import outfit as OF

    cfg = T.load_config()
    log, last, pics = [], [None], [[]]

    def emit():
        return "\n".join(log), last[0], pics[0]

    if not model or not names:
        log.append(_t("ui.load_a_model_first_and_press_split"))
        yield emit()
        return
    if not body:
        log.append(_t("ui.choose_the_body_to_dress_a_parts_glb"))
        yield emit()
        return
    model = Path(model if isinstance(model, str) else model.name)
    assign = dict(zip(names, labels))
    body_name = Path(body).stem.removesuffix("_parts")
    out_dir = Path(cfg["export_dir"]) / "equipment" / body_name / T.slug(set_name or model.stem)
    blender = cfg.get("blender_exe")

    def rig_dressed(src, dst):
        result = yield from rig_core(src, dst, "dressed_" + T.slug(model.stem), cfg,
                                     RIG_NAMINGS[list(RIG_NAMINGS)[0]], 3, log, emit)
        return bool(result)

    log.append(_t("ui.transferring_the_set_onto_the_first", out_dir.name, body_name))
    yield emit()
    for x in OF.transfer(model, assign, body, out_dir, _outfit_work(model), blender, rig_dressed):
        if isinstance(x, str):
            log.append(x)
            yield emit()
        else:  # a progress tuple from the rigging step
            yield x
    prev = out_dir / "set_preview_front.png"
    if prev.exists():
        pics[0] = [(str(prev), _t("ui.the_whole_set_from_the_front")), (str(out_dir / "set_preview_side.png"), _t("ui.side"))]
        pics[0] += [(str(p), p.stem.replace("_preview_front", ""))
                    for p in sorted(out_dir.glob("*_preview_front.png")) if not p.name.startswith("set_")]
        log.append(_t("ui.for_godot_each_piece_has_a_item_json"))
    yield emit()


# ------------------------------------------------------------------ референсы (картинки для 3D)
REF_PROVIDERS = {_t("ui.chatgpt_subscription_through_codex"): "codex",
                 _t("ui.openrouter_with_a_key_nano_banana"): "openrouter"}
REF_CATEGORIES = {_t("ui.item_weapon"): "item", _t("ui.environment_object"): "prop", _t("ui.building"): "building",
                  _t("ui.plant_tree_bush_grass"): "vegetation",
                  _t("ui.character_a_pose"): "character", _t("ui.creature_monster"): "creature"}
REF_TO_GEN = {"item": "item", "prop": "prop", "building": "building", "character": "character", "vegetation": "vegetation",
              "creature": "character"}


def _paths(files):
    out = []
    for f in files or []:
        p = f if isinstance(f, str) else (f[0] if isinstance(f, (list, tuple)) else getattr(f, "name", None))
        if p:
            out.append(str(p))
    return out


def ref_style_load():
    import refgen as RF
    st = RF.load_style(T.load_config()["work_dir"])
    return st["text"], st["refs"] or None


def ref_style_save(text, files):
    import refgen as RF
    st = RF.save_style(T.load_config()["work_dir"], text, _paths(files))
    return _t("ui.style_saved_description_characters", len(st['text']), len(st['refs']))


def ref_describe(provider_label, files):
    import refgen as RF
    cfg = T.load_config()
    imgs = _paths(files)
    if not imgs:
        return gr.update(), _t("ui.add_1_5_style_reference_pictures")
    try:
        if REF_PROVIDERS[provider_label] == "codex":
            text = RF.codex_describe(imgs, out_dir=Path(cfg["work_dir"]) / "refgen")
        else:
            text = RF.openrouter_describe(cfg.get("openrouter_key", ""),
                                          cfg.get("openrouter_text_model", "google/gemini-2.5-flash"), imgs)
    except Exception as e:  # noqa: BLE001
        return gr.update(), _t("ui.error_2", e)
    return text, _t("ui.the_style_description_is_ready")


def _ref_one(provider, prompt, images, out_png):
    import refgen as RF
    cfg = T.load_config()
    if provider == "codex":
        return RF.codex_image(prompt, images, out_png)
    return RF.openrouter_image(cfg.get("openrouter_key", ""),
                               cfg.get("openrouter_image_model", "google/gemini-2.5-flash-image"),
                               prompt, images, out_png)


def ref_generate(provider_label, obj, cat_label, variants, style_text, style_files):
    """'Сгенерировать': N front-view variants of the object in the project's style."""
    import refgen as RF
    cfg = T.load_config()
    log, pics = [], []

    def emit():
        return "\n".join(log), pics, [p for p, _ in pics]

    if not (obj or "").strip():
        log.append(_t("ui.describe_the_object_for_example_a"))
        yield emit()
        return
    provider, category = REF_PROVIDERS[provider_label], REF_CATEGORIES[cat_label]
    refs = _paths(style_files)
    folder = Path(cfg["work_dir"]) / "refgen" / T.slug(obj)[:40]
    folder.mkdir(parents=True, exist_ok=True)
    prompt = RF.build_prompt(obj, category, style_text, "front", has_style_refs=bool(refs))
    (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
    for k in range(int(variants)):
        t0 = time.time()
        log.append(_t("ui.variant_of_generating", k + 1, int(variants)))
        yield emit()
        try:
            out = _ref_one(provider, prompt, refs, folder / f"front_{int(time.time())}.png")
            pics.append((str(out), _t("ui.variant", len(pics) + 1)))
            log[-1] = _t("ui.variant_ready_in_s", k + 1, time.time() - t0)
        except Exception as e:  # noqa: BLE001
            log[-1] = _t("ui.variant_error", k + 1, e)
            yield emit()
            return
        yield emit()
    log.append(_t("ui.pick_the_best_variant_with_a_click"))
    yield emit()


def ref_views(provider_label, front, obj, cat_label, style_text, style_files, want):
    """Back / left / right views of the chosen front picture."""
    import refgen as RF
    cfg = T.load_config()
    log, views = [], {"front": front}

    def emit():
        return "\n".join(log), [(v, k) for k, v in views.items() if v], views

    if not front:
        log.append(_t("ui.first_choose_a_variant_click_a"))
        yield emit()
        return
    provider, category = REF_PROVIDERS[provider_label], REF_CATEGORIES[cat_label]
    refs = _paths(style_files)
    folder = Path(front).parent
    names = {_t("ui.back"): "back", _t("ui.left"): "left", _t("ui.right"): "right"}
    for label in want or []:
        v = names[label]
        t0 = time.time()
        log.append(_t("ui.view_generating", label))
        yield emit()
        prompt = RF.build_prompt(obj or "the object in the first picture", category, style_text, v,
                                 has_style_refs=bool(refs), has_front=True)
        try:
            views[v] = str(_ref_one(provider, prompt, [front] + refs, folder / f"{v}_{int(time.time())}.png"))
            log[-1] = _t("ui.view_ready_in_s", label, time.time() - t0)
        except Exception as e:  # noqa: BLE001
            log[-1] = _t("ui.view_error", label, e)
        yield emit()
    log.append(_t("ui.check_that_all_views_show_the_same"))
    yield emit()


# ------------------------------------------------------------------ бесшовные материалы поверхностей
def surface_run(provider_label, desc, own_file, tile_m, strength, size, name):
    """'Сделать материал': a generated (or own) top-down picture -> seamless maps + Godot material."""
    import refgen as RF
    import surfaces as S
    cfg = T.load_config()
    log, pics = [], []

    def emit():
        return "\n".join(log), pics

    own = _paths([own_file])[0] if own_file else None
    if not own and not (desc or "").strip():
        log.append(_t("ui.describe_the_surface_for_example"))
        yield emit()
        return
    stem = T.slug(name or desc or Path(own).stem)[:40]
    folder = Path(cfg["work_dir"]) / "refgen" / f"surface_{stem}"
    folder.mkdir(parents=True, exist_ok=True)
    if own:
        src = Path(own)
        log.append(_t("ui.taking_your_picture", src.name))
    else:
        st = RF.load_style(cfg["work_dir"])
        prompt = RF.build_prompt(desc, "surface", st["text"], has_style_refs=bool(st["refs"]))
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        log.append(_t("ui.generating_the_texture_top_view"))
        yield emit()
        t0 = time.time()
        try:
            src = _ref_one(REF_PROVIDERS[provider_label], prompt, st["refs"], folder / f"src_{int(time.time())}.png")
        except Exception as e:  # noqa: BLE001
            log.append(_t("ui.error_2", e))
            yield emit()
            return
        log[-1] = _t("ui.texture_ready_in_s", time.time() - t0)
    log.append(_t("ui.making_it_seamless_and_computing_the"))
    yield emit()
    out = Path(cfg["export_dir"]) / "materials" / stem
    info = S.make_material(src, out, stem, size=int(size), strength=float(strength), tile_m=float(tile_m))
    fixed = info["seam_before"] > 1.15
    log.append(_t("ui.done_seam_at_the_edges_1_0_as_inside", out, info['seam_before'], info['seam_after'], 'сшит' if fixed else 'генератор сделал бесшовно сам'))
    log.append(_t("ui.in_godot_copy_the_folder_into_the", stem, stem, tile_m))
    pics.append((str(out / f"{stem}_preview.png"), _t("ui.left_3_3_tiles_seams_would_show_at")))
    pics.append((str(out / info["files"]["normal"]), _t("ui.normal_map")))
    pics.append((str(out / info["files"]["roughness"]), _t("ui.roughness")))
    yield emit()

# ------------------------------------------------------------------ эффекты (листы для частиц, спрайты, сцены Godot)
FX_KINDS = {_t("ui.explosion_once"): "explosion", _t("ui.smoke_once"): "smoke", _t("ui.fire_loop"): "fire",
            _t("ui.magic_flash_once"): "magic", _t("ui.spark_ember_one_frame"): "spark"}


def _fx_dir():
    d = Path(T.load_config()["export_dir"]) / "fx" / "sf3d_fx"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _hex_rgb(h):
    h = (h or "#ffffff").lstrip("#")
    if h.startswith("rgb"):
        return (1.0, 1.0, 1.0)
    return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)) if len(h) >= 6 else (1.0, 1.0, 1.0)


def fx_flip_run(kind_label, color, grid, size, seed, speed, name):
    import fx_flipbook as F
    kind = FX_KINDS[kind_label]
    stem = T.slug(name or kind)
    out = _fx_dir() / f"{stem}.png"
    info = F.make_flipbook(kind, out, grid=int(grid), size=int(size), seed=int(seed), tint=_hex_rgb(color),
                           speed=float(speed))
    view = F.preview(out, Path(T.load_config()["work_dir"]) / f"fx_{stem}_view.png", int(grid))
    note = (_t("ui.done_frames", out, info['frames'], info['grid'], info['grid'])
            + (_t("ui.the_sheet_loops") if info.get("loop") else "") + _t("ui.in_godot_on_the_particle_material", info['grid']))
    if stem in ("explosion", "smoke", "fire", "magic", "spark"):
        note += _t("ui.the_name_matches_the_standard_one")
    return note, [(str(view), stem)]


def fx_sprite_run(provider_label, desc, name):
    """A glowing sprite (rune, spark, spell symbol) generated on black; brightness becomes transparency."""
    import numpy as np
    from PIL import Image
    if not (desc or "").strip():
        return _t("ui.describe_the_sprite_for_example_a"), []
    stem = T.slug(name or desc)[:40]
    work = Path(T.load_config()["work_dir"]) / "refgen" / f"fx_{stem}"
    work.mkdir(parents=True, exist_ok=True)
    prompt = (f"A glowing spell effect sprite for a fantasy ARPG: {desc.strip()}. Bright luminous lines and glow on a "
              "pure black background, nothing else, centred, fills about 90 % of the square picture, flat, seen "
              "straight on, no text.")
    try:
        src = _ref_one(REF_PROVIDERS[provider_label], prompt, [], work / f"src_{int(time.time())}.png")
    except Exception as e:  # noqa: BLE001
        return _t("ui.error_2", e), []
    a = np.asarray(Image.open(src).convert("RGB")).astype(np.float32) / 255
    alpha = np.clip((a.max(-1) - 0.04) / 0.96, 0, 1)
    rgb = np.where(alpha[..., None] > 1e-3, a / np.maximum(alpha[..., None], 1e-3), 0)
    im = Image.fromarray((np.dstack([np.clip(rgb, 0, 1), alpha]) * 255).astype(np.uint8), "RGBA")
    s = min(im.size)
    im = im.crop(((im.width - s) // 2, (im.height - s) // 2, (im.width + s) // 2, (im.height + s) // 2))
    im = im.resize((1024, 1024), Image.LANCZOS)
    out = _fx_dir() / f"{stem}.png"
    im.save(out)
    bg = Image.new("RGBA", im.size, (40, 46, 60, 255))
    bg.alpha_composite(im)
    view = work / "view.png"
    bg.convert("RGB").resize((600, 600)).save(view)
    note = _t("ui.done_the_black_background_became", out)
    if stem == "magic_circle":
        note += _t("ui.the_name_is_standard_build_the")
    return note, [(str(view), stem)]


def fx_build_scenes():
    """Build the Godot scenes from the textures in export/fx/sf3d_fx with headless Godot (in a scratch project)."""
    cfg = T.load_config()
    godot = cfg.get("godot_exe")
    if not godot or not Path(godot).exists():
        return _t("ui.godot_not_found_set_godot_exe_in"), []
    src = _fx_dir()
    need = ["explosion.png", "smoke.png", "fire.png", "magic.png", "spark.png", "magic_circle.png"]
    missing = [n for n in need if not (src / n).exists()]
    if missing:
        import fx_flipbook as F
        for n in missing:
            k = n[:-4]
            if k in ("explosion", "smoke", "fire", "magic", "spark"):
                F.make_flipbook(k, src / n, grid=8 if k != "spark" else 1, size=128,
                                tint=(0.55, 0.85, 1.0) if k == "magic" else (1.0, 0.85, 0.55) if k == "spark" else
                                (1, 1, 1))
        if not (src / "magic_circle.png").exists():
            return (_t("ui.no_magic_circle_png_texture_make_a")), []
    proj = Path(cfg["work_dir"]) / "fx_build"
    (proj / "sf3d_fx").mkdir(parents=True, exist_ok=True)
    if not (proj / "project.godot").exists():
        (proj / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="sf3d_fx_build"\n',
                                            encoding="utf-8")
    for n in need:
        shutil.copy2(src / n, proj / "sf3d_fx" / n)
    shutil.copy2(T.ROOT / "godot" / "fx_player.gd", proj / "sf3d_fx" / "fx_player.gd")
    shutil.copy2(T.ROOT / "godot" / "build_fx.gd", proj / "build_fx.gd")
    flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    subprocess.run([godot, "--headless", "--path", str(proj), "--import"], capture_output=True, timeout=600,
                   creationflags=flags)
    r = subprocess.run([godot, "--headless", "--path", str(proj), "--script", "res://build_fx.gd"],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                       creationflags=flags)
    built = [x.split()[1] for x in r.stdout.splitlines() if x.startswith("FX_SCENE") and x.strip().endswith(" 0")]
    for f in built:
        shutil.copy2(proj / "sf3d_fx" / f, src / f)
    shutil.copy2(T.ROOT / "godot" / "fx_player.gd", src / "fx_player.gd")
    (src / "README.md").write_text(
        _t("ui.sf3d_effects_copy_the_sf3d_fx_folder"), encoding="utf-8")
    if not built:
        return _t("ui.the_scenes_were_not_built") + (r.stdout + r.stderr)[-400:], []
    return (_t("ui.scenes_built_in_copy_the_sf3d_fx", len(built), ', '.join(built), src)), []

# ------------------------------------------------------------------ модульные наборы (подземелье)
KIT_PROC = _t("ui.procedural_stone")


def _mat_folders():
    d = Path(T.load_config()["export_dir"]) / "materials"
    if not d.exists():
        return []
    return sorted(p.name for p in d.iterdir() if (p / f"{p.name}_albedo.png").exists())


def _kit_sample():
    import modkit as MK
    return MK.SAMPLE


def _kit_dir():
    return Path(T.load_config()["export_dir"]) / "modkit" / "dungeon_kit"


def kit_build(cell, height, seed, wall, floor, wood):
    """'Собрать детали': Blender builds the pieces (blocks, arches, stairs...) and exports kit.glb + kit.json."""
    import modkit as MK
    import surfaces as S
    cfg = T.load_config()
    mats = Path(cfg["export_dir"]) / "materials"
    log = []

    def emit(pics=None):
        return "\n".join(log), pics or []

    if not floor or not wood:
        log.append(_t("ui.choose_the_floor_and_wood_materials"))
        yield emit()
        return
    if not wall or wall == KIT_PROC:
        wall = "dungeon_block"
        if not (mats / wall / f"{wall}_albedo.png").exists():
            log.append(_t("ui.making_procedural_stone_for_the"))
            yield emit()
            src = S.procedural_stone(Path(cfg["work_dir"]) / "refgen" / "dungeon_block_src.png", 1024, 3,
                                     (0.32, 0.303, 0.26))
            S.make_material(src, mats / wall, wall, size=1024, strength=0.45, tile_m=2.0)
    out = _kit_dir()
    out.mkdir(parents=True, exist_ok=True)
    log.append(_t("ui.blender_is_building_the_kit_pieces"))
    yield emit()
    pv = out / "preview.png"
    try:
        lines = MK.build_kit(cfg["blender_exe"], out, mats, cell=float(cell), height=float(height), seed=int(seed),
                             preview=str(pv), wall=wall, floor=floor, wood=wood)
    except Exception as e:  # noqa: BLE001
        log.append(_t("ui.error_2", e))
        yield emit()
        return
    n = sum(1 for x in lines if x.startswith("KIT_PIECE"))
    log[-1] = (_t("ui.done_pieces_in_kit_glb_kit_json_now", n, out).format(float(cell), float(height)))
    yield emit([(str(pv), _t("ui.kit_pieces_floor_ceiling_walls"))]
               if pv.exists() else [])


def kit_scene(plan_text, ceilings):
    """'Построить сцену': a text plan -> placements -> Godot builds piece scenes, MeshLibrary and a demo scene."""
    import modkit as MK
    cfg = T.load_config()
    kit = _kit_dir()
    if not (kit / "kit.glb").exists():
        return _t("ui.build_the_kit_pieces_first_the"), []
    godot = cfg.get("godot_exe")
    if not godot or not Path(godot).exists():
        return _t("ui.godot_not_found_set_godot_exe_in"), []
    try:
        plan = MK.parse_plan(plan_text)
    except ValueError as e:
        return str(e), []
    if not ceilings:
        plan["pieces"] = [p for p in plan["pieces"] if p["piece"] != "ceiling"]
    try:
        ok, raw = MK.build_godot(godot, kit, cfg["work_dir"], plan)
    except Exception as e:  # noqa: BLE001
        return _t("ui.error_2", e), []
    shots = []
    try:
        shots = MK.render_shots(godot, kit, cfg["work_dir"], plan)
    except Exception:  # noqa: BLE001
        pass
    MK.write_readme(kit)
    from collections import Counter
    cnt = Counter(p["piece"] for p in plan["pieces"])
    txt = ", ".join(f"{k} ×{v}" for k, v in cnt.most_common())
    return (_t("ui.done_the_plan_has_storey_s_pieces", kit, plan['levels'], len(plan['pieces']), txt, plan['doors'], len(plan['lights']))), [(s, Path(s).stem) for s in shots]


# ------------------------------------------------------------------ разрушаемые объекты
def destr_run(upload, asset, chunks, seed, auto_in, in_color, mass, health, burst, name):
    """'Сделать разрушаемым': Voronoi fracture in Blender, a Godot scene with the pieces, a test render of the break."""
    import destruct as DS
    cfg = T.load_config()
    src, nm, _ = _src_of(upload, asset)
    log = []

    def emit(pics=None):
        return "\n".join(log), pics or []

    if not src or not Path(src).exists():
        log.append(_t("ui.choose_a_finished_model_or_load_a_2"))
        yield emit()
        return
    stem = T.slug(name or nm)
    log.append(_t("ui.working"))
    yield emit()
    lines = []

    def say(s):
        lines.append(s)
        log[:] = lines
    try:
        import queue
        import threading
        q = queue.Queue()
        res = {}

        def job():
            try:
                res["r"] = DS.make_destructible(cfg["blender_exe"], cfg.get("godot_exe"), src, stem,
                                                cfg["export_dir"], cfg["work_dir"], chunks=int(chunks),
                                                seed=int(seed), interior="auto" if auto_in else in_color,
                                                mass=float(mass), health=float(health), burst=float(burst), log=q.put)
            except Exception as e:  # noqa: BLE001
                res["e"] = e
            q.put(None)
        th = threading.Thread(target=job, daemon=True)
        th.start()
        while True:
            m = q.get()
            if m is None:
                break
            say(m)
            yield emit()
        if "e" in res:
            raise res["e"]
    except Exception as e:  # noqa: BLE001
        log.append(_t("ui.error_2", e))
        yield emit()
        return
    r = res["r"]
    log.append(_t("ui.done_copy_the_folder_into_the_root", r['scene'], r['folder']))
    cap = [_t("ui.intact"), _t("ui.0_12_s_after_the_hit"), _t("ui.0_4_s"), _t("ui.after_1_4_s")]
    yield emit([(p, cap[i] if i < len(cap) else "") for i, p in enumerate(r["shots"])])


# ------------------------------------------------------------------ библиотека анимаций человекоподобных
def _clips_file(src: Path, kind: str) -> Path:
    """Where a character's clips go (kind: "anim" - the procedural ones, "fbx" - Mixamo's): beside its skeleton's model,
    in its own folder, named after it (<name>_landmarks_rigged.glb -> <name>_fbx.glb); a model loaded once from
    elsewhere: export/character/<its name>/ as before."""
    src = Path(src)
    ex = Path(T.load_config()["export_dir"]).resolve()
    try:
        inside = src.resolve().parent.parent.parent == ex
    except OSError:
        inside = False
    if inside:
        return src.parent / f"{landmarks._stem(src)}_{kind}.glb"
    name = T.slug(src.stem.replace("_rigged", "").replace("_wings", ""))
    return ex / "character" / name / f"{name}_{kind}.glb"


def _rigged_path(asset):   # "category/name" (the current character) or "category/<name>_rigged" (a file)
    f = _char_files(asset)
    if f and f["rigged"]:
        return f["rigged"]
    cat, nm = asset.split("/", 1)
    return Path(T.load_config()["export_dir"]) / cat / re.sub(r"(_landmarks)?_rigged.*$", "", nm) / f"{nm}.glb"


def hanim_run(upload, asset, clip_labels, manner=None, seed=None, death=None):
    """'Добавить анимации': Blender adds the chosen clips to a rigged humanoid and exports <name>_anim.glb."""
    import hanim as HA
    cfg = T.load_config()
    src = Path(upload if isinstance(upload, str) else upload.name) if upload else (
        _rigged_path(asset) if asset else None)
    if not src or not src.exists():
        yield _t("ui.choose_a_model_with_a_skeleton_from"), [], None
        return
    inv = {v: k for k, v in HA.CLIPS.items()}
    clips = [inv[c] for c in clip_labels if c in inv] or list(HA.CLIPS)
    name = T.slug(src.stem.replace("_rigged", "").replace("_wings", ""))
    dst = _clips_file(src, "anim")
    prev = Path(cfg["work_dir"]) / "hanim" / name / "prev"
    log = [_t("ui.adding_animations_to_about_a_minute", len(clips), src.name)]
    yield "\n".join(log), [], None
    try:
        inv_m = {_t(f"hanim.manner_{k}"): k for k in HA.MANNERS}
        inv_d = {_t(f"hanim.death_{k}"): k for k in HA.DEATHS}
        info = HA.animate(cfg["blender_exe"], src, dst, clips, prev, style=inv_m.get(manner), seed=seed, death=inv_d.get(death))
    except Exception as e:  # noqa: BLE001
        yield _t("ui.error_2", e), [], None
        return
    pics = HA.sheets(prev, clips, Path(cfg["work_dir"]) / "hanim" / name / "sheets")
    names = ", ".join(c["name"].replace("_loop", "") for c in info["clips"])
    log = [_t("ui.done_2", dst), _t("ui.clips", names),
           _t("ui.on_import_godot_turns_on_looping_for", info['walk_speed'], info['run_speed'], info['height']),
           _t("ui.in_place_animations_your_code_moves")]
    yield "\n".join(log), pics, str(dst)


# ------------------------------------------------------------------ анимации Mixamo (FBX без скина)
def _fbx_dir():
    return str(Path(T.load_config()["export_dir"]) / "fbx")


def _viewer_frame(page):
    import html as _html
    return ('<iframe srcdoc="%s" style="width:100%%;height:660px;border:0;border-radius:10px" '
            'allow="fullscreen"></iframe>' % _html.escape(page, quote=True))


def fbx_run(upload, asset, folder, rows, weapon_set=_t("fbx.none")):
    """'Перенести на модель': Blender copies the FBX motions onto the chosen skeleton; the result opens in the viewer."""
    import fbxanim as FA
    cfg = T.load_config()
    p = Path((folder or "").strip() or _fbx_dir())
    src = Path(upload if isinstance(upload, str) else upload.name) if upload else (
        _rigged_path(asset) if asset else None)
    if not src or not src.exists():
        yield _t("ui.choose_a_model_with_a_skeleton_from_2"), gr.update(), None
        return
    if not rows or not len(rows):
        yield _t("ui.first_press_read_the_folder"), gr.update(), None
        return
    rows = [list(r) for r in (rows.values.tolist() if hasattr(rows, "values") else rows)]
    FA.save_map(p, rows)
    dst = _clips_file(src, "fbx")
    yield _t("ui.blender_is_retargeting_animations", len(rows), src.name), gr.update(), None
    try:
        info = FA.retarget(cfg["blender_exe"], src, p, dst)
    except Exception as e:  # noqa: BLE001
        yield _t("ui.error_2", e), gr.update(), None
        return
    log = [_t("ui.done_2", dst), _t("ui.clips_2") + ", ".join(_t("ui.s", c['name'], c['seconds']) for c in info["clips"]) + "."]
    if info["missing"]:
        log.append(_t("ui.the_model_lacks_bones_that_are_in") + ", ".join(info["missing"][:8]))
    if info["rest"]:
        m = re.search(r"max head difference ([0-9.]+) m", info["rest"])
        if m:
            log.append(_t("ui.the_rest_poses_of_the_model_and_the")
                       % m.group(1).replace(".", ","))
    log.append(_t("ui.each_clip_can_be_watched_on_the"))
    yield "\n".join(log), _viewer_frame(FA.viewer_html(dst, info, rows, weapon_set)), str(dst)


def fbx_save(folder, rows):
    import fbxanim as FA
    p = Path((folder or "").strip() or _fbx_dir())
    if not rows or not len(rows):
        return _t("ui.the_table_is_empty")
    rows = [list(r) for r in (rows.values.tolist() if hasattr(rows, "values") else rows)]
    FA.save_map(p, rows)
    return _t("ui.settings_saved_to", p / 'map.json')


# ------------------------------------------------------------------ редактор материалов
MAT_CHOICES = [(v[0], k) for k, v in MT.MATERIALS.items()]
MAX_GROUPS = 8


def _mat_assets():
    cfg = T.load_config()
    out = []
    for p in sorted(Path(cfg["work_dir"]).rglob("pp_params.json")):
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
            out.append(f"{d['category']}/{d['name']}")
        except Exception:  # noqa: BLE001
            pass
    return out


def _mat_params(asset):
    cfg = T.load_config()
    for p in Path(cfg["work_dir"]).rglob("pp_params.json"):
        try:
            d = json.loads(p.read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            continue
        if f"{d['category']}/{d['name']}" == asset:
            return p.parent, d
    return None, None


def _hidden_groups():
    return [gr.update(visible=False, value=None) for _ in range(MAX_GROUPS)]


def mat_analyze(asset):
    work, d = _mat_params(asset)
    if d is None:
        return (None, _t("ui.choose_an_asset_from_the_list_press"), *_hidden_groups())
    import trimesh

    scene = trimesh.load(d["src"], force="scene")
    g = next((g for g in scene.geometry.values()
              if getattr(getattr(g.visual, "material", None), "baseColorTexture", None) is not None
              and getattr(g.visual, "uv", None) is not None), None)
    if g is None:
        return None, _t("ui.this_model_has_no_colour_texture"), *_hidden_groups()
    tex = g.visual.material.baseColorTexture
    an = MT.analyze(tex, g.visual.uv, g.faces, k=6, category=d["category"])
    groups = []
    for j in range(MAX_GROUPS):
        if j < an["k"]:
            key, conf = an["suggestions"][j]
            st = an["stats"][j]
            r, gg, b = (int(v) for v in st["rgb"])
            groups.append(gr.update(
                visible=True, value=key,
                label=_t("ui.group_of_the_texture_mean_colour", j + 1, st['share'] * 100, r, gg, b, MT.MATERIALS[key][0], conf)))
        else:
            groups.append(gr.update(visible=False, value=None))
    note = (_t("ui.groups_found_the_colours_in_the", an['k']))
    return MT.overlay(tex, an), note, *groups


def mat_apply(asset, *values):
    work, d = _mat_params(asset)
    if d is None:
        return _t("ui.first_choose_an_asset_and_press"), None, []
    assign = [v for v in values if v]
    if not assign:
        return _t("ui.no_groups_press_analyse"), None, []
    cfg = T.load_config()
    preset = cfg["categories"][d["category"]]
    final = Path(d["final"])
    stats = pp_call(d["src"], final, preset, d["pp"], materials=assign)
    try:  # keep the sidecar JSON in step with the new GLB
        side = final.parent / f"{d['name']}.json"
        info = json.loads(side.read_text(encoding="utf-8-sig")) if side.exists() else {}
        info["materials"] = stats["materials"]
        side.write_text(json.dumps(info, indent=2, ensure_ascii=False), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    d["pp"]["materials"] = assign  # later re-exports keep the edited materials
    save_pp(work, d["name"], d["category"], d["src"], d["final"], d["pp"])
    log = []
    previews = make_previews(final, work, d["name"], cfg, log) if cfg.get("blender_exe") else []
    rows = "; ".join(f"{m['cluster']}: {m['label']}" for m in stats["materials"])
    return _t("ui.applied_file_updated", rows, final), str(final), previews


# ------------------------------------------------------------------ настройки
def save_settings(export_dir):
    export_dir = (export_dir or "").strip().strip('"')
    if not export_dir:
        return _t("ui.the_export_folder_path_is_empty")
    cfg = T.load_config()
    cfg["export_dir"] = export_dir.replace("\\", "/")
    (T.ROOT / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return _t("ui.saved_export_now_goes_to", export_dir)
