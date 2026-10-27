"""Графический интерфейс для обёртки SF3D (Gradio, локально на 127.0.0.1:7861).

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
import rwt_ui  # GPT: Mount isolated weight repair without extending rig generation.
import landmarks_ui  # hand-placed landmark skeleton (Mixamo-like)
import face_parts_ui  # procedural eyes, teeth, tongue
import armour_gen_ui  # procedural armour from the character's own skin
import i18n
from i18n import t as _t
PORT = 7861
_state = {"model": None, "rembg": None, "on_gpu": False}

HY_PY = r"D:\conda\envs\hunyuan\python.exe"
HY_SRC = r"D:\My projects\SF3D\hunyuan3d-src"
ENGINE_SF3D = _t("ui.sf3d_one_picture_about_20_seconds")
ENGINE_HY = _t("ui.hunyuan3d_1_4_pictures_the_best")

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
             (_t("ui.rigging_unirig"), 4500)]
GPU_SHORT = ["SF3D", _t("ui.hunyuan_shape"), _t("ui.hunyuan_paint"), _t("ui.rigging")]  # same order as GPU_NEEDS, for the status strip
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


def vram_text():
    try:
        import torch

        free, total = torch.cuda.mem_get_info()
        loaded = _t("ui.loaded") if _state["model"] else _t("ui.not_loaded")
        return (_t("ui.video_memory_of_gb_used_model", (total - free) / 1024**3, total / 1024**3, loaded))
    except Exception as e:  # noqa: BLE001
        return _t("ui.could_not_get_the_gpu_data", e)


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


VEG_KINDS = {_t("mat.wood"): "tree", _t("ui.bush"): "bush", _t("ui.grass_flowers"): "grass"}
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
                auto_rig=False, rig_naming_label=None, rig_tries=3, progress=None):
    """Hunyuan3D: runs hy_pipeline.py in the 'hunyuan' env as a separate process (VRAM is freed on exit)."""
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


def run(engine, files, f_front, f_back, f_left, f_right, category, name, height, width, depth, pivot,
        collision, override, metallic, roughness, tex_res, fg_ratio, remove_bg, remesh, overwrite,
        hy_tex, hy_faces, hy_steps, paint, make_preview, color_match, saturation, brightness,
        auto_materials, auto_rig, rig_naming_label, rig_tries, progress=gr.Progress()):
    if engine == ENGINE_HY:
        yield from generate_hy(f_front, f_back, f_left, f_right, category, name, height, width, depth, pivot,
                               collision, override, metallic, roughness, hy_tex, hy_faces, hy_steps, paint,
                               overwrite, make_preview, color_match, saturation, brightness, auto_materials,
                               auto_rig, rig_naming_label, rig_tries)
    else:
        yield from generate(files, category, name, height, width, depth, pivot, collision, override,
                            metallic, roughness,
                            tex_res, fg_ratio, remove_bg, remesh, overwrite, make_preview,
                            color_match, saturation, brightness, auto_materials,
                            auto_rig, rig_naming_label, rig_tries, progress=progress)


def on_engine(engine):
    hy = engine == ENGINE_HY
    return (gr.update(visible=not hy), gr.update(visible=hy),
            gr.update(visible=not hy), gr.update(visible=hy))


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
    return {"name": nm, "dir": d, "source": first(f"{nm}.glb"), "rigged": first(f"{nm}_landmarks_rigged.glb", f"{nm}_rigged.glb"),
            "parts": first(f"{nm}_parts.glb")}


def _characters():
    """[(label, "category/name")]: every folder of export/character with a model, and any other export folder with a
    skeleton or a body in parts."""
    ex, out = Path(T.load_config()["export_dir"]), []
    for d in sorted(x for x in ex.glob("*/*") if x.is_dir()):
        f = _char_files(f"{d.parent.name}/{d.name}")
        if f["rigged"] or f["parts"] or (d.parent.name == "character" and f["source"]):
            out.append((d.name if d.parent.name == "character" else f"{d.name} ({d.parent.name})", f"{d.parent.name}/{d.name}"))
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
    """What the character has, in one line, and its model for the 3D view (the skeleton's when it has one)."""
    f = _char_files(value)
    if not f:
        return _t("ui.char_none"), None
    yes = lambda x: "✓" if x else "—"  # noqa: E731
    clips = len(list(f["dir"].glob("*.face.json")))
    worn = len([x for x in f["dir"].glob("*_wear_*.glb") if not x.name.endswith(".src.glb")])
    return (_t("ui.char_has", yes(f["source"] or f["rigged"]), yes(f["rigged"]), yes(f["parts"]), clips, worn),
            str(f["rigged"] or f["source"] or f["parts"]) if (f["rigged"] or f["source"] or f["parts"]) else None)


def char_add(upload):
    """A model loaded as a new character: export/character/<name>/<name>.glb."""
    if not upload:
        return gr.update()
    src = Path(upload if isinstance(upload, str) else upload.name)
    name = T.slug(src.stem)
    d = Path(T.load_config()["export_dir"]) / "character" / name
    d.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, d / f"{name}.glb")
    return gr.update(choices=_characters(), value=f"character/{name}")


def char_for_tabs(value):
    """The current character's files, each in the form its tab's (hidden) picker takes."""
    f = _char_files(value) or {}
    rig = str(f["rigged"]) if f.get("rigged") else None
    return (value if f.get("source") or f.get("rigged") else None,   # skeleton, lipsync: "category/name"
            value if f.get("rigged") else None, value if f.get("rigged") else None,   # animations
            str(f["parts"]) if f.get("parts") else None, str(f["parts"]) if f.get("parts") else None,   # whole set, one piece
            rig)   # procedural, weights


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


def rig_refresh():
    return gr.update(choices=_export_assets())


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


SLOT_LABELS = {_t("ui.breastplate"): "chest", _t("ui.helmet"): "helmet", _t("ui.gloves"): "gloves", _t("ui.boots"): "boots",
               _t("ui.trousers_greaves"): "pants", _t("ui.bracers"): "bracers", _t("ui.pauldrons"): "pauldrons"}


# the slot a piece is for, from its name (generated pieces are named after what they are)
SLOT_NAMES = [(r"boot|shoe|sabaton|сапог|ботин", "boots"), (r"helm|hat|hood|шлем", "helmet"), (r"glove|gauntlet|перчат|рукавиц", "gloves"),
              (r"pauldron|spaulder|shoulder|наплеч", "pauldrons"), (r"bracer|vambrace|наруч", "bracers"),
              (r"greave|cuisse|pants|trouser|legging|понож|штан", "pants"), (r"chest|cuirass|breast|torso|нагруд|кирас", "chest")]


def fit_item_pick(upload, asset, slot_label):
    """The piece chosen: shown on its own at once, and its slot guessed from its name."""
    src = (upload if isinstance(upload, str) else getattr(upload, "name", None)) if upload else (asset if asset and Path(asset).is_file() else None)
    name = Path(src).stem.lower() if src else ""
    slot = next((k for re_, k in SLOT_NAMES if re.search(re_, name)), None)
    label = next((lb for lb, k in SLOT_LABELS.items() if k == slot), slot_label)
    return src, label


def _piece_assets():
    """[(path under export without .glb, the file)]: the pieces under export/equipment and export/item, whatever their
    depth (generated_armour/models/leather_boot/...), not the fitted or source copies of the character's own."""
    ex = Path(T.load_config()["export_dir"])
    out = []
    for root in ("equipment", "item"):
        for f in sorted((ex / root).rglob("*.glb")):
            if re.search(r"_rigged|_parts$|\.src$|_wear_", f.stem):
                continue
            out.append((f.relative_to(ex).with_suffix("").as_posix(), str(f)))
    return out


def fit_auto(body, upload, asset, *rest):
    """«Подогнать» right after a piece is chosen (nothing when none is)."""
    if upload or asset:
        yield from fit_run(body, upload, asset, *rest)


def _parts_bodies():
    cfg = T.load_config()
    return [str(p) for p in sorted(Path(cfg["export_dir"]).rglob("*_parts.glb"))]


LENGTH_LABELS = {_t("ui.slot_default"): "", _t("ui.to_the_chest"): "chest", _t("ui.to_the_waist"): "waist", _t("ui.to_the_hips"): "hips",
                 _t("ui.to_the_knees"): "knees", _t("ui.to_the_ankles"): "ankles"}


FIT_MODES = {_t("ui.scale_only_the_armour_keeps_its"): "uniform",
             _t("ui.by_the_skeleton_s_landmarks_fit"): "landmarks"}


def _on_body(body, piece, cfg):
    """The fitted piece together with the body it was fitted on, as one GLB for the 3D view (work_dir/fit_view);
    the piece alone when they cannot be put together."""
    try:
        import trimesh
        sc, pc = trimesh.load(str(body), force="scene"), trimesh.load(str(piece), force="scene")
        for node in pc.graph.nodes_geometry:   # each part where it is, with its material
            tf, geom = pc.graph[node]
            sc.add_geometry(pc.geometry[geom], node_name=f"piece_{node}", transform=tf)
        out = Path(cfg["work_dir"]) / "fit_view" / f"{Path(piece).stem}_on_body.glb"
        out.parent.mkdir(parents=True, exist_ok=True)
        sc.export(str(out))
        return str(out)
    except Exception:  # noqa: BLE001
        return str(piece)


def fit_run(body, armour_upload, armour_asset, slot_label, length_label=_t("ui.slot_default"),
            width=100, height=100, depth=100, up_cm=0, gap_mm=6, scale=100,
            mode_label=_t("ui.scale_only_the_armour_keeps_its"), hide_body=False, shrink_pct=0):
    """The 'Подогнать броню' button. Sliders are percentages / centimetres / millimetres."""
    import rigging as RG

    cfg = T.load_config()
    log, last, pics = [], [None], [[]]

    def emit():
        return "\n".join(log), last[0], pics[0]

    if not body:
        log.append(_t("ui.choose_a_body_split_into_parts_the"))
        yield emit()
        return
    if armour_upload:
        src = Path(armour_upload if isinstance(armour_upload, str) else armour_upload.name)
    elif armour_asset and Path(armour_asset).is_file():   # a file from the list of pieces
        src = Path(armour_asset)
    elif armour_asset:
        cat, nm = armour_asset.split("/", 1)
        src = Path(cfg["export_dir"]) / cat / nm / f"{nm}.glb"
    else:
        log.append(_t("ui.choose_an_armour_model_or_load_a_glb"))
        yield emit()
        return
    slot = SLOT_LABELS[slot_label]
    body_name = Path(body).stem.removesuffix("_parts")
    dst = Path(cfg["export_dir"]) / "equipment" / body_name / f"{T.slug(src.stem)}_{slot}.glb"
    dst.parent.mkdir(parents=True, exist_ok=True)
    opts = dict(length=LENGTH_LABELS.get(length_label, ""), width=width / 100, height=height / 100,
                depth=depth / 100, up=up_cm / 100, offset=gap_mm / 1000, scale=scale / 100,
                mode=FIT_MODES.get(mode_label, "uniform"), shrink=(shrink_pct or 0) / 100)
    log.append(_t("ui.fitting_as_onto_about_30_seconds", src.name, slot_label.lower(), body_name))
    yield emit()
    try:
        man = RG.fit_armour(body, src, slot, dst, cfg.get("blender_exe"), opts, hide_body=bool(hide_body))
        log += [f"  {x}" for x in man["log"]]
        log.append(_t("ui.done_hides_manifest", dst, ', '.join(man['hides']) or 'ничего (тело остаётся под бронёй)', dst.with_suffix('.item.json').name))
        log.append(_t("ui.don_t_like_the_fit_change_the_length"))
        last[0] = _on_body(body, dst, cfg)
        pics[0] = [(p, _t("ui.front") if "front" in p else _t("ui.side")) for p in man.get("previews", [])]
    except Exception as e:  # noqa: BLE001
        log.append(_t("ui.error_2", e))
    yield emit()


RIG_KINDS = {_t("ui.humanoid_two_legs_arms_fingers"): "humanoid",
             _t("ui.creature_four_paws_a_tail_a_muzzle"): "creature"}


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
    """Show the chosen model in the tab's 3D view right away."""
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
    log.append(_t("ui.done_vertices_in_the_jaw_look_at_the", name, dst.name, res['jaw_vertices']))
    labels = {"0_side": _t("ui.closed_side"), "0_front": _t("ui.closed_front"), "30_side": _t("ui.open_side"),
              "30_front": _t("ui.open_front")}
    pics[0] = [(p, labels.get(Path(p).stem.split("_jaw_")[-1], "")) for p in res["previews"]]
    last[0] = str(dst)
    (folder / f"{name}_rig.json").write_text(json.dumps(dict(kind="creature", names=st["names"], jaw=st["jaw"],
                                                            line_mm=line_mm, hinge_mm=hinge_mm), indent=2,
                                                       ensure_ascii=False), encoding="utf-8")
    yield emit()


def creature_rejaw(state, line_mm, hinge_mm):
    """'Пересобрать челюсть': the skeleton stays, only the mouth line changes."""
    log, last, pics, st = [], [None], [[]], [state]

    def emit():
        return "\n".join(log), last[0], pics[0], st[0]

    if not state:
        log.append(_t("ui.make_the_creature_s_skeleton_first"))
        yield emit()
        return
    try:
        yield from _creature_jaw(state, line_mm, hinge_mm, log, last, pics, emit)
    except Exception as e:  # noqa: BLE001
        log.append(_t("ui.error_2", e))
    yield emit()


def rig_dispatch(upload, asset, naming_label, tries, kind_label, line_mm, hinge_mm):
    """The 'Создать скелет' button: humanoid or creature."""
    if RIG_KINDS.get(kind_label) == "creature":
        yield from creature_run(upload, asset, line_mm, hinge_mm)
        return
    for log, glb in rig_run(upload, asset, naming_label, tries):
        yield log, glb, [], None


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


def ref_pick(paths, evt: gr.SelectData):
    p = paths[evt.index] if paths and evt.index < len(paths) else None
    return p, (_t("ui.variant_chosen", evt.index + 1) if p else "")


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


def ref_send(views, front, cat_label, obj):
    """Fill the generation tab: one picture -> SF3D, several views -> Hunyuan3D."""
    views = dict(views or {})
    if front and not views.get("front"):
        views["front"] = front
    cat = CATEGORY_LABELS[REF_TO_GEN[REF_CATEGORIES[cat_label]]]
    multi = sum(1 for k in ("back", "left", "right") if views.get(k)) > 0
    return (gr.update(value=ENGINE_HY if multi else ENGINE_SF3D),
            gr.update(value=[views["front"]] if views.get("front") and not multi else None),
            views.get("front") if multi else None, views.get("back"), views.get("left"), views.get("right"),
            gr.update(value=cat), T.slug(obj or "")[:40] or "",
            gr.Tabs(selected="g_create"), gr.Tabs(selected="gen"))


def ref_save_keys(key, img_model, txt_model):
    cfg = T.load_config()
    if key and key.strip() and not set(key.strip()) <= {"•"}:
        cfg["openrouter_key"] = key.strip()
    cfg["openrouter_image_model"] = (img_model or "").strip() or "google/gemini-2.5-flash-image"
    cfg["openrouter_text_model"] = (txt_model or "").strip() or "google/gemini-2.5-flash"
    (T.ROOT / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return _t("ui.openrouter_settings_saved") + (_t("ui.key_set") if cfg.get("openrouter_key") else _t("ui.key_not_set"))

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
FX_SCENES = ["explosion", "fire", "smoke", "magic_circle", "hit_sparks"]


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


def kit_refresh_mats():
    names = _mat_folders()
    return (gr.update(choices=[KIT_PROC] + names), gr.update(choices=names), gr.update(choices=names))


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



import hanim as HA  # noqa: E402


# ------------------------------------------------------------------ библиотека анимаций человекоподобных
def _rigged_assets():
    cfg = T.load_config()
    out = []
    for p in sorted(Path(cfg["export_dir"]).rglob("*_rigged*.glb")):
        out.append(f"{p.parent.parent.name}/{p.stem}")
    return out


def _rigged_path(asset):   # "category/name" (the current character) or "category/<name>_rigged" (a file)
    f = _char_files(asset)
    if f and f["rigged"]:
        return f["rigged"]
    cat, nm = asset.split("/", 1)
    return Path(T.load_config()["export_dir"]) / cat / re.sub(r"(_landmarks)?_rigged.*$", "", nm) / f"{nm}.glb"


def hanim_pick(upload, asset):
    src = Path(upload if isinstance(upload, str) else upload.name) if upload else (_rigged_path(asset) if asset else None)
    return str(src) if src and src.exists() else None


def hanim_run(upload, asset, clip_labels):
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
    dst = Path(cfg["export_dir"]) / "character" / name / f"{name}_anim.glb"
    prev = Path(cfg["work_dir"]) / "hanim" / name / "prev"
    log = [_t("ui.adding_animations_to_about_a_minute", len(clips), src.name)]
    yield "\n".join(log), [], None
    try:
        info = HA.animate(cfg["blender_exe"], src, dst, clips, prev)
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


def fbx_scan(folder):
    """'Прочитать папку': one table row per FBX, with the settings saved in map.json."""
    import fbxanim as FA
    p = Path((folder or "").strip() or _fbx_dir())
    if not p.exists():
        return [], _t("ui.folder_not_found", p)
    rows = FA.table_rows(p)
    if not rows:
        return [], _t("ui.the_folder_has_no_fbx_download", p)
    return rows, (_t("ui.files_found_the_clip_name_and_group", len(rows)))


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
    name = T.slug(src.stem.replace("_rigged", "").replace("_wings", ""))
    dst = Path(cfg["export_dir"]) / "character" / name / f"{name}_fbx.glb"
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


def mat_refresh():
    return gr.update(choices=_mat_assets())


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


def open_export(export_dir):
    p = Path((export_dir or T.load_config()["export_dir"]).strip().strip('"'))
    p.mkdir(parents=True, exist_ok=True)
    os.startfile(str(p))
    return _t("ui.opened_folder", p)


def on_category(category_label):
    p = T.load_config()["categories"][LABEL_TO_KEY[category_label]]
    pivot = {"bottom": _t("ui.at_the_base"), "center": _t("ui.at_the_centre")}[p["pivot"]]
    h = _t("ui.m", p['height_m']) if p["height_m"] else _t("ui.unchanged")
    m = p["metallic"] if p["metallic"] is not None else _t("ui.as_generated")
    r = p["roughness"] if p["roughness"] is not None else _t("ui.as_generated")
    return _t("ui.preset_pivot_height_metallic", pivot, h, m, r)


# ------------------------------------------------------------------ интерфейс
UI_CSS = """
.gradio-container { max-width: 1400px !important; }
.tab-nav button { font-size: 15px; font-weight: 600; }
/* two levels of tabs: sections big, the tools inside them smaller */
#maintabs > .tab-nav button { font-size: 17px; font-weight: 700; padding: 8px 18px; }
#maintabs .tabs .tab-nav button { font-size: 14px; font-weight: 500; padding: 5px 12px; }
/* menu bar: File / Options / Help, GPU status on the right */
#topbar { align-items: center; flex-wrap: nowrap !important; gap: 0 !important; padding: 2px 8px;
  border: 1px solid var(--border-color-primary); border-radius: 10px; background: var(--background-fill-secondary);
  margin-bottom: 8px; overflow: visible !important; }
#topbar .brand-box { flex: 0 0 auto !important; width: auto !important; min-width: 0 !important; padding: 0 12px 0 4px; border: none !important;
  background: none !important; }
#topbar .brand { font-weight: 800; font-size: 16px; letter-spacing: .04em; }
.menu { position: relative; flex: 0 0 auto !important; overflow: visible !important; }
.menu-title { background: transparent !important; border: none !important; box-shadow: none !important;
  padding: 4px 12px !important; font-weight: 600 !important; }
.menu:hover .menu-title { background: var(--background-fill-primary) !important; }
.menu-drop { display: none !important; position: absolute; top: 100%; left: 0; z-index: 1500; width: max-content !important;
  min-width: 250px !important; background: var(--background-fill-primary); border: 1px solid var(--border-color-primary);
  border-radius: 8px; box-shadow: 0 8px 24px rgba(0,0,0,.25); padding: 4px; gap: 0 !important; }
.menu:hover .menu-drop { display: flex !important; }
.menu-drop button { justify-content: flex-start !important; text-align: left; background: transparent !important;
  border: none !important; box-shadow: none !important; font-weight: 400 !important; }
.menu-drop button:hover { background: var(--background-fill-secondary) !important; }
#gpustat { flex: 1 1 auto !important; width: auto !important; height: 30px; overflow: hidden !important; opacity: 1 !important; text-align: right; border: none !important; background: none !important; padding: 0 !important; min-width: 0 !important; }
#gpustat .wrap, #gpustat .progress-text { display: none !important; }
.gpu-in { display: inline-flex; align-items: center; gap: 8px; flex-wrap: wrap; justify-content: flex-end; font-size: 13px; }
.gpu-bar { display: inline-block; width: 110px; height: 8px; border-radius: 4px; background: var(--border-color-primary);
  overflow: hidden; }
.gpu-bar i { display: block; height: 100%; }
.gpu-bar i.ok { background: #2f9e5f; } .gpu-bar i.warn { background: #e0a800; } .gpu-bar i.bad { background: #e5484d; }
.gpu-chip { padding: 1px 8px; border-radius: 10px; border: 1px solid var(--border-color-primary); font-size: 12px; }
.gpu-chip.ok { color: #2f9e5f; } .gpu-chip.warn { color: #b88a00; } .gpu-chip.bad { color: #e5484d; }
.gpu-sf { color: var(--body-text-color-subdued); font-size: 12px; }
/* dialogs opened from the menu */
.dlg { position: fixed !important; top: 6vh; left: 50%; transform: translateX(-50%); width: min(780px, 94vw) !important;
  max-height: 86vh; overflow: auto; z-index: 2000; background: var(--background-fill-primary);
  border: 1px solid var(--border-color-primary); border-radius: 12px; padding: 14px;
  box-shadow: 0 0 0 100vmax rgba(0,0,0,.4), 0 20px 60px rgba(0,0,0,.4); }
"""

UI_HEAD = """<script>document.addEventListener('keydown', (e) => {
  if (e.key !== 'Escape') return;
  for (const b of document.querySelectorAll('.dlg-close')) if (b.offsetParent) { b.click(); break; } });</script>
<script>/* Gradio's own texts (upload areas, buttons) follow the browser's language: make it the interface's */
for (const k of ['language', 'languages']) Object.defineProperty(navigator, k, { get: () => k === 'language' ? '@@LANG@@' : ['@@LANG@@'] });</script>""".replace("@@LANG@@", i18n.LANG)

RIG_MODES = [_t("ui.automatic_unirig_needs_a_gpu"), _t("ui.by_hand_with_landmarks_like_mixamo")]

HELP_TEXT = _t("ui.the_window_has_three_sections_inside")


def status_html():
    """The always-visible GPU strip next to the menu: usage bar, which tasks fit now, where the SF3D model sits."""
    try:
        r = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
                           capture_output=True, text=True, timeout=10,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        used, total = (int(x) for x in r.stdout.strip().splitlines()[0].split(","))
    except Exception:  # noqa: BLE001
        return _t("ui.gpu_no_data_nvidia_smi")
    free = total - used
    frac = used / total
    level = "ok" if frac < 0.6 else "warn" if frac < 0.85 else "bad"
    chips = []
    for (short, (_, need)) in zip(GPU_SHORT, GPU_NEEDS):
        if short == "SF3D" and _state["model"] is not None and _state["on_gpu"]:
            cls, mark, tip = "ok", "✓", _t("ui.the_model_is_already_in_video_memory")
        elif free >= need + 500:
            cls, mark, tip = "ok", "✓", _t("ui.needs_about_gb_fits", need / 1024)
        elif free >= need:
            cls, mark, tip = "warn", "≈", _t("ui.needs_about_gb_tight", need / 1024)
        else:
            cls, mark, tip = "bad", "✗", _t("ui.needs_about_gb_not_enough", need / 1024)
        chips.append(f'<span class="gpu-chip {cls}" title="{tip}">{short} {mark}</span>')
    sf = ""
    if _state["model"] is not None:
        sf = f'<span class="gpu-sf">SF3D: {"в видеопамяти" if _state["on_gpu"] else "в оперативной памяти"}</span>'
    return (_t("ui.video_memory_gb_free", used / 1024, total / 1024, level, frac * 100, used / 1024, total / 1024, free / 1024, "".join(chips), sf))

def _restart():
    """A new copy of this server (it waits for the port), then this one ends: the interface is built once, in one
    language, so a new language needs a new process. The copy shares the console (or the launcher's hidden one)."""
    import threading
    subprocess.Popen([sys.executable, *sys.argv], cwd=os.getcwd(), env={**os.environ, "SF3D_WAIT_PORT": "1"})
    threading.Timer(1.0, lambda: os._exit(0)).start()


def switch_language(code):
    i18n.set_lang(code)
    _restart()


# the page waits for the new server and reloads (both languages: the old one is still on the screen)
RESTART_JS = """() => {
  document.body.insertAdjacentHTML('beforeend', '<div style="position:fixed;inset:0;z-index:9999;display:flex;align-items:center;'
    + 'justify-content:center;background:rgba(0,0,0,.55);color:#fff;font:20px sans-serif">Перезапуск… / Restarting…</div>');
  const go = () => fetch(location.href, { cache: 'no-store' }).then((r) => r.ok ? location.reload() : setTimeout(go, 1000))
    .catch(() => setTimeout(go, 1000));
  setTimeout(go, 4000);
}"""


def _wait_port(port, seconds=40):
    """After a restart the old server may still hold the port for a moment."""
    import socket
    for _ in range(seconds * 2):
        with socket.socket() as sk:
            try:
                sk.bind(("127.0.0.1", port))
                return
            except OSError:
                time.sleep(0.5)


def build():
    cfg = T.load_config()
    labels = [CATEGORY_LABELS[k] for k in cfg["categories"]]
    default_cat = CATEGORY_LABELS["prop"]
    import outfit as OF
    with gr.Blocks(title=_t("ui.sf3d_game_assets"), theme=gr.themes.Soft(), css=UI_CSS, head=UI_HEAD) as ui:
        with gr.Row(elem_id="topbar"):
            gr.HTML('<span class="brand">SF3D</span>', elem_classes="brand-box")
            with gr.Column(elem_classes="menu", min_width=0, scale=0):
                gr.Button(_t("fbx.file"), elem_classes="menu-title", size="sm")
                with gr.Column(elem_classes="menu-drop", min_width=0):
                    mi_open_export = gr.Button(_t("ui.open_the_export_folder"), size="sm")
                    mi_open_input = gr.Button(_t("ui.open_the_input_pictures_folder"), size="sm")
                    mi_batch = gr.Button(_t("ui.batch_processing"), size="sm")
            with gr.Column(elem_classes="menu", min_width=0, scale=0):
                gr.Button(_t("ui.options"), elem_classes="menu-title", size="sm")
                with gr.Column(elem_classes="menu-drop", min_width=0):
                    mi_vram = gr.Button(_t("ui.video_memory_2"), size="sm")
                    mi_settings = gr.Button(_t("ui.settings_2"), size="sm")
                    mi_unload = gr.Button(_t("ui.unload_sf3d_from_video_memory"), size="sm")
            with gr.Column(elem_classes="menu", min_width=0, scale=0):
                gr.Button(_t("ui.help"), elem_classes="menu-title", size="sm")
                with gr.Column(elem_classes="menu-drop", min_width=0):
                    mi_help = gr.Button(_t("ui.order_of_work_2"), size="sm")
            with gr.Column(elem_classes="menu", min_width=0, scale=0):
                gr.Button("🌐 " + i18n.LANGS[i18n.LANG], elem_classes="menu-title", size="sm")
                with gr.Column(elem_classes="menu-drop", min_width=0):
                    mi_langs = [(code, gr.Button(name, size="sm")) for code, name in i18n.LANGS.items()]
            gpu_stat = gr.HTML("", elem_id="gpustat")
            gpu_timer = gr.Timer(5)

        with gr.Tabs(elem_id="maintabs") as main_tabs:
            with gr.Tab(_t("ui.create"), id="g_create"):
                with gr.Tabs() as tabs_create:
                    # ---------------------------------------------------------------- 0. reference pictures
                    with gr.Tab(_t("ui.reference"), id="ref"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(_t("ui.1_what_is_needed_describe_the_object"))
                                ref_obj = gr.Textbox(label=_t("ui.object"), lines=2,
                                                     placeholder=_t("ui.for_example_a_crooked_wooden_fence"))
                                with gr.Row():
                                    ref_cat = gr.Dropdown(list(REF_CATEGORIES), value=_t("ui.environment_object"), label=_t("ui.type"), scale=2)
                                    ref_n = gr.Slider(1, 4, value=1, step=1, label=_t("ui.variants"), scale=1)
                                ref_provider = gr.Radio(list(REF_PROVIDERS), value=list(REF_PROVIDERS)[0],
                                                        label=_t("ui.generate_with"))
                                ref_go = gr.Button(_t("ui.generate"), variant="primary")
                                with gr.Accordion(_t("ui.project_style_shared_by_all"), open=False):
                                    gr.Markdown(_t("ui.reference_pictures_3_5_good_assets"))
                                    ref_style_text = gr.Textbox(label=_t("ui.style_description_more_precise_in"), lines=4)
                                    ref_style_files = gr.File(label=_t("ui.style_reference_pictures"), file_count="multiple",
                                                              file_types=["image"], type="filepath")
                                    with gr.Row():
                                        ref_describe_btn = gr.Button(_t("ui.describe_from_the_pictures"))
                                        ref_style_save_btn = gr.Button(_t("ui.save_the_style"))
                                    ref_style_note = gr.Markdown("")
                                ref_log = gr.Textbox(label=_t("face.progress"), lines=5, interactive=False)
                            with gr.Column(scale=1):
                                ref_gallery = gr.Gallery(label=_t("ui.variants_click_the_best"), columns=2, height=420,
                                                         allow_preview=True)
                                ref_choice_note = gr.Markdown("")
                                ref_want = gr.CheckboxGroup([_t("ui.back"), _t("ui.left"), _t("ui.right")], value=[_t("ui.back"), _t("ui.left"), _t("ui.right")],
                                                            label=_t("ui.extra_views_for_hunyuan3d_the_best"))
                                with gr.Row():
                                    ref_views_btn = gr.Button(_t("ui.make_views_of_the_chosen_variant"))
                                    ref_send_btn = gr.Button(_t("ui.send_to_3d"), variant="primary")
                                ref_views_gallery = gr.Gallery(label=_t("ui.views"), columns=4, height=200)
                        ref_paths = gr.State([])
                        ref_front = gr.State(None)
                        ref_views_state = gr.State({})

                    # ---------------------------------------------------------------- 1. generation
                    with gr.Tab(_t("ui.make_a_model"), id="gen"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                engine = gr.Radio([ENGINE_SF3D, ENGINE_HY], value=ENGINE_SF3D, label=_t("ui.engine_2"))
                                files = gr.File(label=_t("ui.pictures_one_or_several"), file_count="multiple",
                                                file_types=["image"], type="filepath")
                                with gr.Group(visible=False) as hy_views:
                                    gr.Markdown(_t("ui.object_views_the_same_model_from"))
                                    with gr.Row():
                                        v_front = gr.Image(label=_t("ui.front_2"), type="filepath", sources=["upload"], height=150)
                                        v_back = gr.Image(label=_t("ui.back_2"), type="filepath", sources=["upload"], height=150)
                                    with gr.Row():
                                        v_left = gr.Image(label=_t("ui.left_2"), type="filepath", sources=["upload"], height=150)
                                        v_right = gr.Image(label=_t("ui.right_2"), type="filepath", sources=["upload"], height=150)
                                with gr.Row():
                                    category = gr.Dropdown(labels, value=default_cat, label=_t("ui.category_2"), scale=1)
                                    name = gr.Textbox(label=_t("ui.name_if_there_is_one_picture"), scale=1)
                                preset_note = gr.Markdown(on_category(default_cat))
                                veg_kind = gr.Radio(list(VEG_KINDS), value=_t("mat.wood"), visible=False,
                                                    label=_t("ui.what_plant_it_is_for_the_wind_in"))
                                with gr.Accordion(_t("ui.size_and_pivot"), open=False):
                                    height = gr.Number(label=_t("ui.model_height_in_metres_0_the"),
                                                       value=0)
                                    with gr.Row():
                                        width = gr.Number(label=_t("ui.width_along_x_m_0_unchanged"), value=0)
                                        depth = gr.Number(label=_t("ui.depth_along_z_m_0_unchanged"), value=0)
                                    pivot = gr.Radio(list(PIVOT_LABELS), value=_t("ui.auto_by_category"),
                                                     label=_t("ui.pivot_point"))
                                    collision = gr.Dropdown(list(COLLISION_LABELS), value=_t("ui.by_category"),
                                                            label=_t("ui.collision_for_godot_made"))
                                with gr.Accordion(_t("ui.material_and_colour"), open=False):
                                    override = gr.Checkbox(label=_t("ui.set_metallic_and_roughness_by_hand"), value=False)
                                    metallic = gr.Slider(0, 1, value=0.0, step=0.05, label=_t("ui.metallic"))
                                    roughness = gr.Slider(0, 1, value=0.8, step=0.05, label=_t("ui.roughness_2"))
                                    color_match = gr.Slider(0, 1, value=0.0, step=0.05,
                                                            label=_t("ui.match_the_palette_to_your_pictures_0"))
                                    saturation = gr.Slider(0.3, 1.5, value=1.0, step=0.05,
                                                           label=_t("ui.saturation_1_unchanged"))
                                    brightness = gr.Slider(0.5, 1.5, value=1.0, step=0.05, label=_t("ui.brightness_1_unchanged"))
                                    auto_materials = gr.Checkbox(label=_t("ui.recognise_materials_wood_metal_stone"),
                                                                 value=False)
                                with gr.Accordion(_t("ui.hunyuan3d_options"), open=False, visible=False) as hy_params:
                                    paint = gr.Checkbox(label=_t("ui.paint_a_texture_without_it_a_grey"), value=True)
                                    hy_tex = gr.Dropdown([1024, 2048], value=2048, label=_t("ui.texture_size"))
                                    hy_faces = gr.Slider(10000, 100000, value=50000, step=5000,
                                                         label=_t("ui.target_face_count_after_simplifying"))
                                    hy_steps = gr.Slider(20, 50, value=50, step=5, label=_t("ui.diffusion_steps_fewer_faster"))
                                with gr.Accordion(_t("ui.sf3d_generation_options"), open=False) as sf_params:
                                    tex_res = gr.Dropdown([512, 1024, 2048], value=1024,
                                                          label=_t("ui.texture_size_2048_may_not_fit_into_8"))
                                    fg_ratio = gr.Slider(0.5, 1.0, value=cfg["foreground_ratio"], step=0.01,
                                                         label=_t("ui.object_s_share_of_the_frame"))
                                    remove_bg = gr.Checkbox(label=_t("ui.remove_the_background_turn_off_if"),
                                                            value=True)
                                    remesh = gr.Dropdown(["none", "triangle", "quad"], value="none",
                                                         label=_t("ui.remesh_none_unchanged"))
                                with gr.Row():
                                    make_preview = gr.Checkbox(label=_t("ui.preview_and_icon_blender_10_s"), value=True)
                                    overwrite = gr.Checkbox(label=_t("ui.overwrite_finished_ones_2"), value=False)
                                auto_rig = gr.Checkbox(label=_t("ui.make_a_skeleton_for_a_humanoid"), value=False)
                                go = gr.Button(_t("ui.make_a_model"), variant="primary", size="lg")
                            with gr.Column(scale=1):
                                viewer = gr.Model3D(label=_t("lm.result"), height=460, clear_color=(0.9, 0.9, 0.9, 1))
                                inputs_gallery = gr.Gallery(label=_t("ui.prepared_pictures_preview_and_icon"),
                                                            columns=4, height=150)
                                logbox = gr.Textbox(label=_t("ui.log"), lines=6, interactive=False)
                        table = gr.Dataframe(headers=[_t("ui.name"), _t("ui.category"), _t("ui.faces_2"), _t("ui.size_m"), _t("ui.seconds"), _t("ui.file_2")],
                                             label=_t("ui.made_in_this_session"), interactive=False, wrap=True)

                    # ---------------------------------------------------------------- 4. materials
                    with gr.Tab(_t("ui.materials"), id="mat"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(_t("ui.1_choose_a_model_2_analyse_the"))
                                with gr.Row():
                                    mat_asset = gr.Dropdown(_mat_assets(), label=_t("ui.model_category_name"), scale=4)
                                    mat_refresh_btn = gr.Button(_t("ui.refresh"), scale=1)
                                mat_analyze_btn = gr.Button(_t("ui.analyse"))
                                mat_note = gr.Markdown("")
                                mat_dd = [gr.Dropdown(MAT_CHOICES, value=None, visible=False, label=_t("ui.group", j + 1))
                                          for j in range(MAX_GROUPS)]
                                mat_apply_btn = gr.Button(_t("ui.apply_the_materials"), variant="primary")
                                mat_status = gr.Textbox(label=_t("lm.result"), interactive=False)
                            with gr.Column(scale=1):
                                mat_m3d = gr.Model3D(label=_t("ui.model"), height=380, clear_color=(0.9, 0.9, 0.9, 1))
                                mat_overlay = gr.Image(label=_t("ui.groups_on_the_texture"), height=260, interactive=False)
                                mat_gallery = gr.Gallery(label=_t("ui.preview"), columns=4, height=150)

                    # ---------------------------------------------------------------- 5. batch
                    with gr.Tab(_t("ui.batch_processing_2"), id="batch"):
                        gr.Markdown(_t("ui.folder_scheme_picture_png_sf3d_front"))
                        with gr.Row():
                            batch_dir = gr.Textbox(label=_t("ui.root_folder"),
                                                   value=cfg.get("input_dir", r"D:\My projects\SF3D\input"), scale=3)
                            batch_cat = gr.Dropdown(labels, value=default_cat, label=_t("ui.default_category"), scale=2)
                        with gr.Row():
                            batch_over = gr.Checkbox(label=_t("ui.overwrite_finished_ones"), value=False)
                            batch_prev = gr.Checkbox(label=_t("ui.previews_and_icons"), value=True)
                            batch_mat = gr.Checkbox(label=_t("ui.recognise_materials"), value=False)
                            batch_rig = gr.Checkbox(label=_t("ui.skeletons_for_characters_at_the_end"), value=False)
                        with gr.Row():
                            scan_btn = gr.Button(_t("ui.scan_the_folder"))
                            batch_btn = gr.Button(_t("ui.run_the_batch"), variant="primary")
                        batch_info = gr.Textbox(label=_t("ui.found"), interactive=False)
                        batch_jobs = gr.Dataframe(headers=[_t("ui.name"), _t("ui.category"), _t("ui.engine"), _t("ui.source"), _t("ui.status_2")],
                                                  label=_t("ui.queue"), interactive=False, wrap=True)
                        with gr.Row():
                            batch_log = gr.Textbox(label=_t("ui.log"), lines=8, interactive=False, scale=1)
                            batch_view = gr.Model3D(label=_t("ui.last_model"), height=320, clear_color=(0.9, 0.9, 0.9, 1),
                                                    scale=1)
                        batch_table = gr.Dataframe(headers=[_t("ui.name"), _t("ui.category"), _t("ui.faces_2"), _t("ui.size_m"), _t("ui.seconds"), _t("ui.file_2")],
                                                   label=_t("ui.done_4"), interactive=False, wrap=True)
                        batch_gallery = gr.Gallery(label=_t("ui.preview"), columns=6, height=150)

            with gr.Tab(_t("ui.character"), id="g_char"):
                with gr.Row(elem_classes=["char-bar"]):   # the current character: every tool below works on it
                    with gr.Column(scale=3):
                        with gr.Row():
                            char_dd = gr.Dropdown(_characters(), value=_char_default(), label=_t("ui.current_character"), scale=4)
                            char_refresh = gr.Button(_t("ui.refresh"), scale=1)
                            char_up = gr.UploadButton(_t("ui.char_add"), file_types=[".glb"], type="filepath", scale=2)
                        char_md = gr.Markdown(char_info(_char_default())[0])
                    with gr.Column(scale=2):
                        char_view = gr.Model3D(value=char_info(_char_default())[1], label=_t("ui.model"), height=230,
                                               clear_color=(0.9, 0.9, 0.9, 1))
                char_rig = gr.Textbox(visible=False)   # its model with a skeleton, for the tools that take a path
                with gr.Tabs() as tabs_char:
                    with gr.Tab(_t("ui.skeleton"), id="rig"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(_t("ui.1_model_choose_one_you_made_or_load"))
                                with gr.Row(visible=False):   # the current character's (above)
                                    rig_asset = gr.Dropdown(_export_assets(), label=_t("ui.finished_model_category_name"),
                                                            scale=4, allow_custom_value=True)
                                    rig_refresh_btn = gr.Button(_t("ui.refresh"), scale=1)
                                rig_upload = gr.File(label=_t("ui.or_load_a_glb"), file_types=[".glb"], type="filepath")
                                rig_mode = gr.Radio(list(RIG_MODES), value=list(RIG_MODES)[0], label=_t("ui.2_how_to_build_the_skeleton"))
                                with gr.Column() as rig_auto_box:
                                    rig_kind = gr.Radio(list(RIG_KINDS), value=list(RIG_KINDS)[0], label=_t("ui.which_skeleton_is_needed"))
                                    with gr.Group() as rig_human:
                                        rig_naming = gr.Radio(list(RIG_NAMINGS), value=list(RIG_NAMINGS)[0],
                                                              label=_t("lm.bone_names"))
                                        rig_tries = gr.Slider(1, 6, value=3, step=1,
                                                              label=_t("ui.attempts_to_get_a_skeleton_with"))
                                    with gr.Group(visible=False) as rig_creature:
                                        gr.Markdown(_t("ui.the_bones_get_clear_names_hips_spine"))
                                        with gr.Row():
                                            jaw_line = gr.Slider(-40, 40, value=0, step=1,
                                                                 label=_t("ui.mouth_line_higher_lower_mm"))
                                            jaw_hinge = gr.Slider(-40, 40, value=0, step=1,
                                                                  label=_t("ui.jaw_hinge_further_nearer_to_the_nose"))
                                    rig_btn = gr.Button(_t("ui.make_the_skeleton_3_6_minutes_3_5_gb"), variant="primary")
                                    with gr.Group(visible=False) as rig_creature_after:
                                        rejaw_btn = gr.Button(_t("ui.rebuild_the_jaw_with_the_new_sliders"))
                                    with gr.Accordion(_t("ui.for_humanoids_seams_and_body_parts"), open=False) as rig_extra:
                                        seam_btn = gr.Button(_t("ui.fix_the_seams_between_parts_the"))
                                        split_btn = gr.Button(_t("ui.split_the_body_into_parts_for_armour"))
                                    rig_log = gr.Textbox(label=_t("face.progress"), lines=8, interactive=False)
                            with gr.Column(scale=1):
                                rig_view = gr.Model3D(label=_t("ui.model"), height=460, clear_color=(0.9, 0.9, 0.9, 1))
                                jaw_gallery = gr.Gallery(label=_t("ui.jaw_closed_and_open"), columns=4, height=220)
                        creature_state = gr.State(None)
                        with gr.Column(visible=False) as rig_manual_box:
                            lm_data, lm_editor = landmarks_ui.mount(T.load_config, rig_asset, rig_upload, accordion=False)

                    # ---------------------------------------------------------------- humanoid animation library
                    with gr.Tab(_t("ui.animations_procedural"), id="hanim"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(_t("ui.a_set_of_ready_clips_for_a_humanoid"))
                                with gr.Row(visible=False):   # the current character's (above)
                                    ha_asset = gr.Dropdown(_rigged_assets(), label=_t("lm.model_with_a_skeleton"), scale=4, allow_custom_value=True)
                                    ha_refresh_btn = gr.Button(_t("ui.refresh"), scale=1)
                                ha_upload = gr.File(label=_t("ui.or_load_a_glb_with_a_skeleton"), file_types=[".glb"],
                                                    type="filepath")
                                ha_clips = gr.CheckboxGroup(list(HA.CLIPS.values()), value=list(HA.CLIPS.values()),
                                                            label=_t("ui.which_clips_to_add"))
                                ha_btn = gr.Button(_t("ui.add_the_animations"), variant="primary")
                                ha_log = gr.Textbox(label=_t("face.progress"), lines=8, interactive=False)
                            with gr.Column(scale=1):
                                ha_view = gr.Model3D(label=_t("ui.result_rest_pose"), height=320,
                                                     clear_color=(0.9, 0.9, 0.9, 1))
                                ha_gallery = gr.Gallery(label=_t("ui.clip_frames_side_view_6_frames_per"), columns=1,
                                                        height=420)

                    # ---------------------------------------------------------------- Mixamo FBX animations
                    with gr.Tab(_t("ui.animations_mixamo_fbx"), id="fbxanim"):
                        with gr.Row():
                            with gr.Column(scale=4):
                                gr.Markdown(_t("ui.animations_from_mixamo_fbx_without"))
                                with gr.Row(visible=False):   # the current character's (above)
                                    fx_asset = gr.Dropdown(_rigged_assets(), label=_t("lm.model_with_a_skeleton"), scale=4, allow_custom_value=True)
                                    fx_refresh = gr.Button(_t("ui.refresh"), scale=1)
                                fx_upload = gr.File(label=_t("ui.or_your_own_glb_with_a_skeleton"), file_types=[".glb"], type="filepath")
                                fx_folder = gr.Textbox(value=_fbx_dir(), label=_t("ui.folder_with_fbx"))
                                with gr.Row():
                                    fx_scan_btn = gr.Button(_t("ui.read_the_folder"))
                                    fx_save_btn = gr.Button(_t("ui.save_the_settings"))
                                fx_table = gr.Dataframe(headers=[_t("fbx.file"), _t("fbx.clip_name"), _t("fbx.loop"), _t("fbx.speed"), _t("fbx.in_place"), _t("fbx.group")],
                                                        datatype=["str", "str", "bool", "number", "bool", "str"],
                                                        col_count=(6, "fixed"), interactive=True, type="array", wrap=True)
                                fx_weapon = gr.Dropdown(list(__import__("fbxanim").WEAPON_SETS), value=_t("fbx.none"),
                                                        label=_t("ui.weapons_in_hand_only_for_viewing"))
                                fx_go = gr.Button(_t("ui.retarget_onto_the_model"), variant="primary")
                                fx_log = gr.Textbox(label=_t("face.progress"), lines=7, interactive=False)
                                fx_file = gr.File(label=_t("ui.ready_glb"), interactive=False)
                            with gr.Column(scale=6):
                                fx_view = gr.HTML(value=_t("ui.the_viewer_appears_here_choose_a"))

                    # ---------------------------------------------------------------- 3. equipment
                    with gr.Tab(_t("ui.equipment_whole_set")):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(
                                    _t("ui.generate_the_same_character_in_the"))
                                out_model = gr.File(label=_t("ui.glb_of_the_dressed_model_with"), file_types=[".glb"],
                                                    type="filepath")
                                with gr.Row(visible=False):   # the current character's body in parts (above)
                                    out_body = gr.Dropdown(_parts_bodies(), label=_t("ui.onto_which_body_parts_glb"),
                                                           scale=3, allow_custom_value=True)
                                    out_refresh = gr.Button(_t("ui.refresh"), scale=1)
                                out_name = gr.Textbox(label=_t("ui.set_name_folder_in_equipment"))
                                out_scan_btn = gr.Button(_t("ui.split_into_segments"))
                            with gr.Column(scale=1):
                                out_m3d = gr.Model3D(label=_t("ui.model"), height=420, clear_color=(0.9, 0.9, 0.9, 1))
                        out_note = gr.Markdown("")
                        out_thumbs = gr.Gallery(label=_t("ui.segments"), columns=8, height=260)
                        out_names = gr.State([])
                        out_dd = []
                        for _row in range(MAX_SEGS // 4):
                            with gr.Row():
                                for _ in range(4):
                                    out_dd.append(gr.Dropdown(list(OF.SLOTS), visible=False, label=""))
                        out_btn = gr.Button(_t("ui.transfer_the_set"), variant="primary")
                        out_log = gr.Textbox(label=_t("face.progress"), lines=8, interactive=False)
                        out_view = gr.Gallery(label=_t("ui.result_on_the_base_body"), columns=4, height=420)
                    with gr.Tab(_t("ui.equipment_one_piece")):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(_t("ui.puts_a_separately_generated_piece_on"))
                                with gr.Row(visible=False):   # the current character's body in parts (above)
                                    fit_body = gr.Dropdown(_parts_bodies(), label=_t("ui.body_parts_glb"), scale=4, allow_custom_value=True)
                                    fit_refresh = gr.Button(_t("ui.refresh"), scale=1)
                                with gr.Row():
                                    fit_asset = gr.Dropdown(_piece_assets(), label=_t("ui.piece_from_finished_models"), scale=3)
                                    fit_items_refresh = gr.Button(_t("ui.refresh"), scale=1)
                                    fit_slot = gr.Dropdown(list(SLOT_LABELS), value=_t("ui.breastplate"), label=_t("ui.slot"),
                                                           scale=2)
                                fit_upload = gr.File(label=_t("ui.or_load_the_piece_s_glb"), file_types=[".glb"],
                                                     type="filepath")
                                fit_item = gr.Model3D(label=_t("ui.the_piece"), height=220, clear_color=(0.9, 0.9, 0.9, 1))
                                fit_mode = gr.Radio(list(FIT_MODES), value=list(FIT_MODES)[0], label=_t("ui.fit_2"))
                                with gr.Accordion(_t("ui.fine_tuning"), open=False):
                                    fit_scale = gr.Slider(50, 150, value=100, step=1, label=_t("ui.scale"))
                                    fit_hide = gr.Checkbox(label=_t("ui.hide_the_body_part_under_the_piece"), value=False)
                                    fit_length = gr.Dropdown(list(LENGTH_LABELS), value=_t("ui.slot_default"),
                                                             label=_t("ui.length_breastplate_from_the_collar"))
                                    fit_gap = gr.Slider(0, 20, value=6, step=1, label=_t("ui.gap_to_the_body_mm"))
                                    fit_shrink = gr.Slider(0, 100, value=0, step=5,
                                                           label=_t("ui.shrink_to_the_body_pulls_in_hanging"))
                                    with gr.Row():
                                        fit_w = gr.Slider(70, 140, value=100, step=1, label=_t("ui.width"))
                                        fit_h = gr.Slider(60, 160, value=100, step=1, label=_t("ui.length"))
                                    with gr.Row():
                                        fit_d = gr.Slider(70, 150, value=100, step=1, label=_t("ui.depth"))
                                        fit_up = gr.Slider(-10, 10, value=0, step=0.5, label=_t("ui.up_down_cm"))
                                fit_btn = gr.Button(_t("ui.fit"), variant="primary")
                                fit_log = gr.Textbox(label=_t("face.progress"), lines=4, interactive=False)
                            with gr.Column(scale=1):
                                fit_m3d = gr.Model3D(label=_t("ui.model"), height=420, clear_color=(0.9, 0.9, 0.9, 1))
                                fit_view = gr.Gallery(label=_t("ui.how_it_sits_front_and_side"), columns=2, height=300)

                    with gr.Tab(_t("ui.equipment_procedural"), id="proc_armour"):
                        armour_gen_ui.mount(T.load_config, char_rig)

                    with gr.Tab(_t("ui.weight_fixing"), id="rwt"):
                        rwt_ui.mount(T.load_config, accordion=False, char=char_rig)  # GPT: Optional repair retains the skeleton.
                    with gr.Tab(_t("ui.face_parts"), id="face"):
                        face_parts_ui.mount(T.load_config, accordion=False)
                    with gr.Tab(_t("ui.lipsync"), id="lipsync"):
                        landmarks_ui.mount_lipsync(T.load_config, rig_asset, rig_upload, lm_data, lm_editor, accordion=False)

            with gr.Tab(_t("ui.environment"), id="g_env"):
                with gr.Tabs():
                    # ---------------------------------------------------------------- surfaces
                    with gr.Tab(_t("ui.surfaces_ground_floor_walls"), id="surf"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(_t("ui.a_seamless_material_for_terrain"))
                                surf_desc = gr.Textbox(label=_t("ui.surface"), lines=2,
                                                       placeholder=_t("ui.for_example_an_old_cobbled_road_moss"))
                                surf_own = gr.File(label=_t("ui.or_your_own_picture_top_view"), file_types=["image"],
                                                   type="filepath")
                                surf_provider = gr.Radio(list(REF_PROVIDERS), value=list(REF_PROVIDERS)[0],
                                                         label=_t("ui.generate_with"))
                                with gr.Row():
                                    surf_tile = gr.Slider(0.5, 10, value=4, step=0.5, label=_t("ui.the_tile_repeats_every_m"))
                                    surf_strength = gr.Slider(0.2, 3, value=1.0, step=0.1, label=_t("ui.relief_strength"))
                                with gr.Row():
                                    surf_size = gr.Dropdown([512, 1024, 2048], value=1024, label=_t("ui.texture_size_2"))
                                    surf_name = gr.Textbox(label=_t("ui.name_folder_in_materials"))
                                surf_btn = gr.Button(_t("ui.make_the_material"), variant="primary")
                                surf_log = gr.Textbox(label=_t("face.progress"), lines=6, interactive=False)
                            with gr.Column(scale=1):
                                surf_gallery = gr.Gallery(label=_t("lm.result"), columns=1, height=520)

                    # ---------------------------------------------------------------- effects
                    with gr.Tab(_t("ui.effects_particles"), id="fx"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(_t("ui.1_an_animated_sheet_for_godot"))
                                fx_kind = gr.Dropdown(list(FX_KINDS), value=list(FX_KINDS)[0], label=_t("ui.what_to_draw"))
                                with gr.Row():
                                    fx_color = gr.ColorPicker(value="#ffffff", label=_t("ui.hue"))
                                    fx_grid = gr.Dropdown([4, 8], value=8, label=_t("ui.frame_grid"))
                                    fx_size = gr.Dropdown([64, 128, 256], value=128, label=_t("ui.frame_size_px"))
                                with gr.Row():
                                    fx_seed = gr.Number(value=1, precision=0, label=_t("ui.variant_seed"))
                                    fx_speed = gr.Slider(0.5, 2.0, value=1.0, step=0.1, label=_t("fbx.speed"))
                                    fx_name = gr.Textbox(label=_t("ui.file_name_empty_by_the_kind"))
                                fx_flip_btn = gr.Button(_t("ui.make_the_sheet"), variant="primary")
                                gr.Markdown(_t("ui.2_a_glowing_sprite_from_a"))
                                fx_provider = gr.Radio(list(REF_PROVIDERS), value=list(REF_PROVIDERS)[0],
                                                       label=_t("ui.generate_with"))
                                fx_desc = gr.Textbox(label=_t("ui.description"), lines=2, placeholder=_t("ui.a_summoning_circle_with_runes_blue"))
                                fx_sname = gr.Textbox(label=_t("ui.file_name_magic_circle_for_the"))
                                fx_sprite_btn = gr.Button(_t("ui.generate_the_sprite"))
                                gr.Markdown(_t("ui.3_godot_scenes_from_the_sheets"))
                                fx_scene_btn = gr.Button(_t("ui.build_the_godot_scenes"))
                                fx_log = gr.Textbox(label=_t("lm.result"), lines=5, interactive=False)
                            with gr.Column(scale=1):
                                fx_gallery = gr.Gallery(label=_t("face.preview"), columns=1, height=560)

                    # ---------------------------------------------------------------- modular kits
                    with gr.Tab(_t("ui.modular_kits_dungeon"), id="kit"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(_t("ui.a_set_of_pieces_that_join_on_a_grid"))
                                gr.Markdown(_t("ui.1_kit_pieces"))
                                with gr.Row():
                                    kit_cell = gr.Number(value=4, label=_t("ui.cell_m"))
                                    kit_height = gr.Number(value=3, label=_t("ui.storey_height_m"))
                                    kit_seed = gr.Number(value=1, precision=0, label=_t("ui.masonry_variant"))
                                _mats = _mat_folders()
                                with gr.Row():
                                    kit_wall = gr.Dropdown([KIT_PROC] + _mats, value=KIT_PROC, label=_t("ui.wall_stone"))
                                    kit_floor = gr.Dropdown(_mats, value="dungeon_floor" if "dungeon_floor" in _mats
                                                            else (_mats[0] if _mats else None), label=_t("ui.floor_and_stairs"))
                                    kit_wood = gr.Dropdown(_mats, value="dungeon_wood" if "dungeon_wood" in _mats
                                                           else (_mats[0] if _mats else None), label=_t("ui.wood_door_beams"))
                                    kit_mats_btn = gr.Button(_t("ui.refresh_the_list"), scale=0)
                                kit_build_btn = gr.Button(_t("ui.build_the_pieces"), variant="primary")
                                gr.Markdown(_t("ui.2_floor_plan_godot_scene_rows_are"))
                                kit_plan = gr.Textbox(value=_kit_sample(), lines=16, label=_t("ui.plan"), max_lines=40,
                                                      elem_classes=["mono"])
                                kit_ceil = gr.Checkbox(value=True, label=_t("ui.ceilings"))
                                kit_scene_btn = gr.Button(_t("ui.build_the_scene"))
                                kit_log = gr.Textbox(label=_t("face.progress"), lines=6, interactive=False)
                            with gr.Column(scale=1):
                                kit_gallery = gr.Gallery(label=_t("lm.result"), columns=1, height=620)

                    # ---------------------------------------------------------------- destructibles
                    with gr.Tab(_t("ui.destructible_objects"), id="destr"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(_t("ui.the_model_a_barrel_a_crate_a_vase_a"))
                                with gr.Row():
                                    dst_asset = gr.Dropdown(_export_assets(), label=_t("ui.finished_model_category_name"), scale=4)
                                    dst_refresh_btn = gr.Button(_t("ui.refresh"), scale=1)
                                dst_upload = gr.File(label=_t("ui.or_load_a_glb"), file_types=[".glb"], type="filepath")
                                with gr.Row():
                                    dst_chunks = gr.Slider(4, 40, value=14, step=1, label=_t("ui.chunks"))
                                    dst_seed = gr.Number(value=1, precision=0, label=_t("ui.fracture_variant"))
                                with gr.Row():
                                    dst_auto = gr.Checkbox(value=True, label=_t("ui.fracture_colour_from_the_texture"))
                                    dst_color = gr.ColorPicker(value="#6b4a2e", label=_t("ui.or_your_own_fracture_colour"))
                                with gr.Row():
                                    dst_mass = gr.Number(value=20, label=_t("ui.mass_kg"))
                                    dst_health = gr.Number(value=20, label=_t("ui.toughness"))
                                    dst_burst = gr.Number(value=3.5, label=_t("ui.fly_apart_speed_m_s"))
                                dst_name = gr.Textbox(label=_t("ui.name_empty_as_the_model_s"))
                                dst_btn = gr.Button(_t("ui.make_destructible"), variant="primary")
                                dst_log = gr.Textbox(label=_t("face.progress"), lines=6, interactive=False)
                            with gr.Column(scale=1):
                                dst_view = gr.Model3D(label=_t("ui.model"), height=300, clear_color=(0.9, 0.9, 0.9, 1))
                                dst_gallery = gr.Gallery(label=_t("ui.check_in_godot_intact_destruction"), columns=2, height=380)


        # ---------------------------------------------------------------- dialogs opened from the menu bar
        with gr.Column(visible=False, elem_classes="dlg") as dlg_vram:
            with gr.Row():
                gr.Markdown(_t("ui.video_memory"))
                dlg_vram_x = gr.Button(_t("ui.close"), scale=0, min_width=110, elem_classes="dlg-close")
            gr.Markdown(_t("ui.before_generating_close_programs"))
            gpu_btn = gr.Button(_t("ui.refresh_show_the_video_memory_use"))
            gpu_md = gr.Markdown("")
            with gr.Row():
                gpu_proc = gr.Dropdown([], label=_t("ui.a_program_that_can_be_closed"), scale=3)
                gpu_force = gr.Checkbox(label=_t("ui.force_unsaved_work_is_lost"), scale=2)
            gpu_close = gr.Button(_t("ui.close_the_chosen_program"))
            unload_btn = gr.Button(_t("ui.unload_sf3d_from_video_memory"))
            gpu_msg = gr.Markdown("")
        with gr.Column(visible=False, elem_classes="dlg") as dlg_settings:
            with gr.Row():
                gr.Markdown(_t("ui.settings"))
                dlg_settings_x = gr.Button(_t("ui.close"), scale=0, min_width=110, elem_classes="dlg-close")
            export_dir = gr.Textbox(label=_t("ui.export_folder_later_point_it_to_the"),
                                    value=cfg["export_dir"])
            with gr.Row():
                save_btn = gr.Button(_t("ui.save_the_folder"))
                open_btn = gr.Button(_t("ui.open_the_folder"))
            info = gr.Textbox(label=_t("ui.status"), interactive=False)
            gr.Markdown(_t("ui.openrouter_for_references_with_a_key"))
            or_key = gr.Textbox(label=_t("ui.openrouter_key"), type="password",
                                value=("•" * 12) if cfg.get("openrouter_key") else "")
            with gr.Row():
                or_img = gr.Textbox(label=_t("ui.model_for_pictures"),
                                    value=cfg.get("openrouter_image_model", "google/gemini-2.5-flash-image"))
                or_txt = gr.Textbox(label=_t("ui.model_for_the_style_description"),
                                    value=cfg.get("openrouter_text_model", "google/gemini-2.5-flash"))
            or_save = gr.Button(_t("ui.save_the_openrouter_settings"))
            or_note = gr.Markdown("")
        with gr.Column(visible=False, elem_classes="dlg") as dlg_help:
            with gr.Row():
                gr.Markdown(_t("ui.order_of_work"))
                dlg_help_x = gr.Button(_t("ui.close"), scale=0, min_width=110, elem_classes="dlg-close")
            gr.Markdown(HELP_TEXT)

        # ---------------------------------------------------------------- events
        category.change(on_category, category, preset_note, show_progress="hidden")
        category.change(lambda c: gr.update(visible=LABEL_TO_KEY.get(c) == "vegetation"), category, veg_kind,
                        show_progress="hidden")
        veg_kind.change(lambda k: VEG_STATE.update(kind=VEG_KINDS[k]), veg_kind, None, show_progress="hidden")
        engine.change(on_engine, engine, [files, hy_views, sf_params, hy_params], show_progress="hidden")
        go.click(run,
                 [engine, files, v_front, v_back, v_left, v_right, category, name, height, width, depth, pivot,
                  collision, override,
                  metallic, roughness, tex_res, fg_ratio, remove_bg, remesh, overwrite,
                  hy_tex, hy_faces, hy_steps, paint, make_preview, color_match, saturation, brightness,
                  auto_materials, auto_rig, rig_naming, rig_tries],
                 [logbox, table, viewer, inputs_gallery])
        gpu_btn.click(gpu_status, None, [gpu_md, gpu_proc])
        gpu_close.click(gpu_close_proc, [gpu_proc, gpu_force], [gpu_msg, gpu_md, gpu_proc])

        # the current character: its view, what it has, its files in every tab
        char_dd.change(char_info, char_dd, [char_md, char_view], show_progress="hidden")
        char_dd.change(char_remember, char_dd, None, show_progress="hidden")
        char_dd.change(char_for_tabs, char_dd, [rig_asset, ha_asset, fx_asset, out_body, fit_body, char_rig], show_progress="hidden")
        char_refresh.click(lambda v: gr.update(choices=_characters(), value=v), char_dd, char_dd)
        char_up.upload(char_add, char_up, char_dd)
        ui.load(char_for_tabs, char_dd, [rig_asset, ha_asset, fx_asset, out_body, fit_body, char_rig], show_progress="hidden")

        # rigging
        rig_refresh_btn.click(rig_refresh, None, rig_asset)
        rig_asset.change(preview_pick, [rig_upload, rig_asset], rig_view, show_progress="hidden")
        rig_upload.change(preview_pick, [rig_upload, rig_asset], rig_view, show_progress="hidden")

        def on_kind(label):
            c = RIG_KINDS.get(label) == "creature"
            return gr.update(visible=not c), gr.update(visible=c), gr.update(visible=not c)

        rig_kind.change(on_kind, rig_kind, [rig_human, rig_creature, rig_extra], show_progress="hidden")
        rig_btn.click(rig_dispatch, [rig_upload, rig_asset, rig_naming, rig_tries, rig_kind, jaw_line, jaw_hinge],
                      [rig_log, rig_view, jaw_gallery, creature_state])
        creature_state.change(lambda s: gr.update(visible=bool(s)), creature_state, rig_creature_after,
                              show_progress="hidden")
        rejaw_btn.click(creature_rejaw, [creature_state, jaw_line, jaw_hinge],
                        [rig_log, rig_view, jaw_gallery, creature_state])
        seam_btn.click(seam_run, [rig_upload, rig_asset], [rig_log, rig_view])
        split_btn.click(split_run, [rig_upload, rig_asset], [rig_log, rig_view])

        # equipment
        def refresh_bodies():
            return gr.update(choices=_parts_bodies()), gr.update(choices=_piece_assets())

        fit_refresh.click(refresh_bodies, None, [fit_body, fit_asset])
        fit_items_refresh.click(lambda: gr.update(choices=_piece_assets()), None, fit_asset)
        out_refresh.click(lambda: gr.update(choices=_parts_bodies()), None, out_body)
        fit_body.change(lambda p: p or None, fit_body, fit_m3d, show_progress="hidden")
        # a piece chosen: shown on its own, its slot guessed, then put on the character at once (on the right)
        fit_inputs = [fit_body, fit_upload, fit_asset, fit_slot, fit_length, fit_w, fit_h, fit_d, fit_up, fit_gap, fit_scale, fit_mode, fit_hide, fit_shrink]
        for _src in (fit_asset, fit_upload):
            _src.change(fit_item_pick, [fit_upload, fit_asset, fit_slot], [fit_item, fit_slot], show_progress="hidden").then(
                fit_auto, fit_inputs, [fit_log, fit_m3d, fit_view])
        fit_btn.click(fit_run, [fit_body, fit_upload, fit_asset, fit_slot, fit_length, fit_w, fit_h, fit_d,
                                fit_up, fit_gap, fit_scale, fit_mode, fit_hide, fit_shrink], [fit_log, fit_m3d, fit_view])
        out_model.change(lambda f: (f if isinstance(f, str) else getattr(f, "name", None)) if f else None,
                         out_model, out_m3d, show_progress="hidden")
        out_scan_btn.click(outfit_scan, out_model, [out_note, out_thumbs, out_names, out_name, *out_dd])
        out_btn.click(outfit_run, [out_model, out_body, out_name, out_names, *out_dd], [out_log, out_m3d, out_view])

        # materials
        mat_refresh_btn.click(mat_refresh, None, mat_asset)
        mat_asset.change(lambda a: preview_pick(None, a), mat_asset, mat_m3d, show_progress="hidden")
        mat_analyze_btn.click(mat_analyze, mat_asset, [mat_overlay, mat_note, *mat_dd])
        mat_apply_btn.click(mat_apply, [mat_asset, *mat_dd], [mat_status, mat_m3d, mat_gallery])

        # reference pictures
        ui.load(ref_style_load, None, [ref_style_text, ref_style_files])
        ref_describe_btn.click(ref_describe, [ref_provider, ref_style_files], [ref_style_text, ref_style_note])
        ref_style_save_btn.click(ref_style_save, [ref_style_text, ref_style_files], ref_style_note)
        ref_go.click(ref_generate, [ref_provider, ref_obj, ref_cat, ref_n, ref_style_text, ref_style_files],
                     [ref_log, ref_gallery, ref_paths])
        ref_gallery.select(ref_pick, ref_paths, [ref_front, ref_choice_note])
        ref_views_btn.click(ref_views, [ref_provider, ref_front, ref_obj, ref_cat, ref_style_text, ref_style_files,
                                        ref_want], [ref_log, ref_views_gallery, ref_views_state])
        ref_send_btn.click(ref_send, [ref_views_state, ref_front, ref_cat, ref_obj],
                           [engine, files, v_front, v_back, v_left, v_right, category, name, main_tabs, tabs_create])
        or_save.click(ref_save_keys, [or_key, or_img, or_txt], or_note)

        # surfaces, effects, modular kits
        surf_btn.click(surface_run, [surf_provider, surf_desc, surf_own, surf_tile, surf_strength, surf_size, surf_name],
                       [surf_log, surf_gallery])
        fx_flip_btn.click(fx_flip_run, [fx_kind, fx_color, fx_grid, fx_size, fx_seed, fx_speed, fx_name],
                          [fx_log, fx_gallery])
        fx_sprite_btn.click(fx_sprite_run, [fx_provider, fx_desc, fx_sname], [fx_log, fx_gallery])
        fx_scene_btn.click(fx_build_scenes, None, [fx_log, fx_gallery])
        kit_mats_btn.click(kit_refresh_mats, None, [kit_wall, kit_floor, kit_wood])
        kit_build_btn.click(kit_build, [kit_cell, kit_height, kit_seed, kit_wall, kit_floor, kit_wood],
                            [kit_log, kit_gallery])
        kit_scene_btn.click(kit_scene, [kit_plan, kit_ceil], [kit_log, kit_gallery])

        # Mixamo FBX animations
        fx_refresh.click(lambda: gr.update(choices=_rigged_assets()), None, fx_asset)
        fx_scan_btn.click(fbx_scan, fx_folder, [fx_table, fx_log])
        fx_save_btn.click(fbx_save, [fx_folder, fx_table], fx_log)
        fx_go.click(fbx_run, [fx_upload, fx_asset, fx_folder, fx_table, fx_weapon], [fx_log, fx_view, fx_file])
        ui.load(fbx_scan, fx_folder, [fx_table, fx_log])

        # humanoid animations
        ha_refresh_btn.click(lambda: gr.update(choices=_rigged_assets()), None, ha_asset)
        ha_asset.change(hanim_pick, [ha_upload, ha_asset], ha_view, show_progress="hidden")
        ha_upload.change(hanim_pick, [ha_upload, ha_asset], ha_view, show_progress="hidden")
        ha_btn.click(hanim_run, [ha_upload, ha_asset, ha_clips], [ha_log, ha_gallery, ha_view])

        # destructibles
        dst_refresh_btn.click(lambda: gr.update(choices=_export_assets()), None, dst_asset)
        dst_asset.change(preview_pick, [dst_upload, dst_asset], dst_view, show_progress="hidden")
        dst_upload.change(preview_pick, [dst_upload, dst_asset], dst_view, show_progress="hidden")
        dst_btn.click(destr_run, [dst_upload, dst_asset, dst_chunks, dst_seed, dst_auto, dst_color, dst_mass,
                                  dst_health, dst_burst, dst_name], [dst_log, dst_gallery])

        # batch, settings
        scan_btn.click(on_scan, [batch_dir, batch_cat], [batch_jobs, batch_info])
        batch_btn.click(batch_run, [batch_dir, batch_cat, batch_over, batch_prev, batch_mat, batch_rig,
                                    rig_naming, rig_tries],
                        [batch_log, batch_table, batch_view, batch_gallery])
        save_btn.click(save_settings, export_dir, info)
        open_btn.click(open_export, export_dir, info)
        unload_btn.click(unload_model, None, gpu_msg).then(status_html, None, gpu_stat, show_progress="hidden")

        # skeleton: one of two ways at a time
        rig_mode.change(lambda m: (gr.update(visible=m == RIG_MODES[0]), gr.update(visible=m != RIG_MODES[0])),
                        rig_mode, [rig_auto_box, rig_manual_box], show_progress="hidden")

        # menu bar, dialogs, GPU strip
        def open_folder_toast(key, fallback):
            p = Path(T.load_config().get(key) or fallback)
            p.mkdir(parents=True, exist_ok=True)
            os.startfile(str(p))
            gr.Info(_t("ui.opened_folder", p))

        def unload_toast():
            gr.Info(unload_model())
            return status_html()

        def show_dialog(which):
            return [gr.update(visible=i == which) for i in range(3)]

        dialogs = [dlg_vram, dlg_settings, dlg_help]
        mi_open_export.click(lambda: open_folder_toast("export_dir", T.ROOT / "export"), None, None)
        mi_open_input.click(lambda: open_folder_toast("input_dir", T.ROOT / "input"), None, None)
        mi_batch.click(lambda: (gr.Tabs(selected="g_create"), gr.Tabs(selected="batch")), None,
                       [main_tabs, tabs_create], show_progress="hidden")
        mi_vram.click(lambda: show_dialog(0), None, dialogs, show_progress="hidden") \
            .then(gpu_status, None, [gpu_md, gpu_proc])
        mi_settings.click(lambda: show_dialog(1), None, dialogs, show_progress="hidden")
        mi_help.click(lambda: show_dialog(2), None, dialogs, show_progress="hidden")
        mi_unload.click(unload_toast, None, gpu_stat, show_progress="hidden")
        for code, btn in mi_langs:
            if code != i18n.LANG:
                btn.click(lambda c=code: switch_language(c), None, None, show_progress="hidden").then(None, None, None, js=RESTART_JS)
        for close_btn in (dlg_vram_x, dlg_settings_x, dlg_help_x):
            close_btn.click(lambda: show_dialog(None), None, dialogs, show_progress="hidden")
        ui.load(status_html, None, gpu_stat, show_progress="hidden")
        gpu_timer.tick(status_html, None, gpu_stat, show_progress="hidden", concurrency_id="gpu_strip",
                       concurrency_limit=1)
    return ui


if __name__ == "__main__":
    if os.environ.pop("SF3D_WAIT_PORT", None):
        _wait_port(PORT)
    ui = build()
    ui.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=PORT, inbrowser=False, show_api=False,
        allowed_paths=[T.load_config()["export_dir"], T.load_config()["work_dir"]],
    )
