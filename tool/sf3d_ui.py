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
PORT = 7861
_state = {"model": None, "rembg": None, "on_gpu": False}

HY_PY = r"D:\conda\envs\hunyuan\python.exe"
HY_SRC = r"D:\My projects\SF3D\hunyuan3d-src"
ENGINE_SF3D = "SF3D — одна картинка, около 20 секунд"
ENGINE_HY = "Hunyuan3D — 1–4 картинки, лучшая форма, около 7 минут"

# Ключ категории в config.json -> подпись в интерфейсе
CATEGORY_LABELS = {
    "item": "Предмет инвентаря",
    "prop": "Пропс / окружение",
    "building": "Здание",
    "character": "Персонаж",
    "vegetation": "Растительность (деревья, кусты, трава)",
}
LABEL_TO_KEY = {v: k for k, v in CATEGORY_LABELS.items()}
PIVOT_LABELS = {"авто (по категории)": None, "у основания": "bottom", "в центре": "center"}
COLLISION_LABELS = {"по категории": None, "нет": "none",
                    "выпуклая оболочка (предметы, пропсы)": "convex",
                    "упрощённый меш (здания)": "simplified"}


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
    return "Модель перенесена в оперативную память, видеопамять освобождена."


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
GPU_NEEDS = [("SF3D: предмет, пропс, персонаж", 6400),
             ("Hunyuan3D: форма", 6200),
             ("Hunyuan3D: покраска текстурой", 7000),
             ("Риггинг (UniRig)", 4500)]
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
            return "Это окно SF3D (его нельзя закрыть отсюда)", "self"
        if "gradio_app" in c:
            return "Старое демо SF3D (sf3d-gradio.bat)", "ours"
        if "hy_pipeline" in c or "hy_texture" in c or "hy_test" in c:
            return "Hunyuan3D (идёт генерация)", "ours"
        if "unirig" in c or "run.py" in c:
            return "UniRig (идёт риггинг)", "ours"
        if "batch_cli" in c:
            return "Пакетная обработка SF3D", "ours"
        return f"Python: {cmd[-70:] if cmd else name}", "other"
    if n == "blender":
        return "Blender" + (f" — {title}" if title else ""), "other"
    if n in ("chrome", "msedge", "firefox", "brave", "opera", "vivaldi"):
        return f"Браузер {name}" + (f" — {title[:50]}" if title else " (служебный процесс)"), "other"
    if n in PROTECTED:
        return "Системный процесс Windows (рабочий стол и т. п.)", "system"
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
            label, kind = "Это окно SF3D (его нельзя закрыть отсюда)", "self"
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
        return "Не удалось прочитать данные видеокарты (`nvidia-smi`).", gr.update(choices=[], value=None)
    lines = [f"**Видеопамять: занято {used / 1024:.1f} из {total / 1024:.1f} ГБ, свободно {free / 1024:.1f} ГБ.**", ""]
    for what, need in GPU_NEEDS:
        if free >= need + 500:
            mark = "✅ хватит"
        elif free >= need:
            mark = "⚠️ впритык, лучше освободить"
        else:
            mark = f"❌ не хватит (не хватает ещё {(need - free) / 1024:.1f} ГБ)"
        lines.append(f"- {what} (около {need / 1024:.1f} ГБ): {mark}")
    holders = gpu_holders()
    choices = []
    if holders:
        lines += ["", "**Что занимает память** (по данным Windows):", ""]
        for h in holders:
            size = f"{h['mb']} МБ" if h["mb"] is not None else "—"
            tag = {"system": " 🔒 системное", "self": " 🔒 это окно"}.get(h["kind"], "")
            lines.append(f"- {size}: {h['label']} (PID {h['pid']}){tag}")
            if h["kind"] in ("other", "ours"):
                choices.append((f"{h['label']} — {size} (PID {h['pid']})", h["pid"]))
    if _state["model"] is not None:
        lines += ["", f"Модель SF3D сейчас {'в видеопамяти' if _state['on_gpu'] else 'в оперативной памяти'}."]
    return "\n".join(lines), gr.update(choices=choices, value=None)


def gpu_close_proc(pid, force):
    """Close a program that holds GPU memory. Gentle by default (the program may ask to save its work)."""
    if not pid:
        return "Сначала выберите программу в списке.", *gpu_status()
    pid = int(pid)
    holders = {h["pid"]: h for h in gpu_holders()}
    h = holders.get(pid)
    if h is None:
        return "Эта программа уже не занимает видеопамять.", *gpu_status()
    if h["kind"] not in ("other", "ours") or (h["name"] or "").lower() in PROTECTED or pid == os.getpid():
        return f"«{h['label']}» закрывать нельзя.", *gpu_status()
    flags = ["/F"] if force else []
    subprocess.run(["taskkill", "/PID", str(pid), *flags], capture_output=True, text=True,
                   creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    for _ in range(12):  # up to ~6 s for a polite close
        time.sleep(0.5)
        if pid not in {x["pid"] for x in gpu_holders()}:
            return f"Закрыто: {h['label']}.", *gpu_status()
    msg = (f"«{h['label']}» не закрылась: возможно, она спрашивает про сохранение. Закройте её сами, либо отметьте "
           f"«Принудительно» (несохранённое пропадёт) и повторите." if not force
           else f"«{h['label']}» не удалось закрыть даже принудительно.")
    return msg, *gpu_status()


def vram_gate(need_mb, log, emit, label, timeout_s=900):
    """Wait until enough VRAM is free instead of crashing when another program holds the GPU.

    Use as:  ok = yield from vram_gate(...). Loading a model into a nearly full 8 GB card makes the
    driver/torch crash the whole process without a Python traceback, so it is better to wait.
    """
    free = gpu_free_mb()
    if free is None or free >= need_mb:
        return True
    names = ", ".join(f"{h['label']} ({h['mb']} МБ)" for h in gpu_holders()[:3] if h["mb"])
    log.append(f"{label}: свободно {free} МБ видеопамяти, нужно около {need_mb}. Жду, пока освободится."
               + (f" Сейчас её занимают: {names}." if names else "")
               + " Закройте лишнее или откройте блок «Видеопамять» вверху окна.")
    t0 = time.time()
    while time.time() - t0 < timeout_s:
        yield emit()
        time.sleep(10)
        free = gpu_free_mb()
        if free is None or free >= need_mb:
            log.append(f"{label}: видеопамять освободилась ({free} МБ), продолжаю.")
            return True
    log.append(f"{label}: видеопамять так и не освободилась за {timeout_s // 60} мин, пропускаю.")
    return False


def vram_text():
    try:
        import torch

        free, total = torch.cuda.mem_get_info()
        loaded = "загружена" if _state["model"] else "не загружена"
        return (f"Видеопамять: занято {(total - free) / 1024**3:.1f} из {total / 1024**3:.1f} ГБ "
                f"(модель {loaded})")
    except Exception as e:  # noqa: BLE001
        return f"Не удалось получить данные о GPU: {e}"


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
        log.append("Сначала добавьте хотя бы одну картинку.")
        yield emit()
        return
    paths = T.collect_images([f if isinstance(f, str) else f.name for f in files])
    preset = cfg["categories"][category]
    log.append(f"Картинок: {len(paths)}, категория «{category_label}».")
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
            log.append(f"[пропуск] {stem}: уже экспортировано (включите «Перезаписать», чтобы переделать).")
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
                log.append(f"[{stem}] удаляю фон...")
                yield emit()
                image = remove_background(image, _state["rembg"])
            image = resize_foreground(image, fg_ratio)
            image.save(work / "input.png")
            previews.append((str(work / "input.png"), stem))
            log.append(f"[{stem}] генерирую 3D (при первом запуске загружается модель, около минуты)...")
            yield emit()

            if not _state["on_gpu"] and not (yield from vram_gate(5500, log, emit, f"[{stem}]")):
                raise RuntimeError("не хватает свободной видеопамяти")
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
            log.append(f"[{stem}] готово за {stats['seconds']} с, пик видеопамяти {stats['peak_vram_mb']} МБ.")
            if make_preview:
                yield emit()
                previews += make_previews(final, work, stem, cfg, log)
            if auto_rig:
                if category == "character":
                    rig_queue.append((final, stem))
                else:
                    log.append(f"[{stem}] скелет делается только для категории «Персонаж», пропускаю.")
        except torch.cuda.OutOfMemoryError:
            torch.cuda.empty_cache()
            log.append(f"[{stem}] НЕ ХВАТИЛО ВИДЕОПАМЯТИ. Закройте другие программы, использующие GPU, "
                       f"уменьшите размер текстуры или нажмите «Выгрузить модель» и повторите.")
        except Exception as e:  # noqa: BLE001
            log.append(f"[{stem}] ОШИБКА: {type(e).__name__}: {e}")
        yield emit()
    if rig_queue:
        # this frame still references the SF3D model and its tensors; drop them or the VRAM is never released
        model = mesh = image = None
        log.append(f"Генерация закончена, делаю скелеты: {len(rig_queue)} шт.")
        yield emit()
        rigged = yield from rig_queue_run(rig_queue, cfg, rig_naming_label, rig_tries, log, emit)
        if rigged:
            last_glb = rigged[-1]
    log.append("Готово.")
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


VEG_KINDS = {"Дерево": "tree", "Куст": "bush", "Трава / цветы": "grass"}
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
        raise RuntimeError("ветер не добавлен: " + (r.stdout + r.stderr)[-300:])
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
        log.append(f"[{stem}] превью и иконка не созданы: {e}")
        return []
    log.append(f"[{stem}] иконка для инвентаря: {res['icon']}")
    return [(res["preview"], f"{stem}: 4 вида"), (res["icon"], f"{stem}: иконка")]


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
            if "генерация формы" in line:
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
        log.append("Нужна минимум картинка «Спереди».")
        yield emit()
        return
    stem = T.slug(name or Path(front).stem)
    work = Path(cfg["work_dir"]) / "hunyuan" / category / stem
    final = Path(cfg["export_dir"]) / category / stem / f"{stem}.glb"
    if final.exists() and not overwrite:
        log.append(f"[пропуск] {stem}: уже экспортировано (включите «Перезаписать», чтобы переделать).")
        last_glb = str(final)
        yield emit()
        return

    work.mkdir(parents=True, exist_ok=True)
    views = {k: v for k, v in (("front", front), ("back", back), ("left", left), ("right", right)) if v}
    for k, v in views.items():  # Gradio uploads live in a temp dir; keep our own copies
        shutil.copy2(v, work / f"source_{k}{Path(v).suffix.lower()}")
    log.append(f"Hunyuan3D, виды: {', '.join(views)}. Освобождаю видеопамять от SF3D...")
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
        log.append(f"Hunyuan упал при загрузке модели (код {code:#x}), повторяю ({attempt + 2} из 3)...")
        yield emit()
    live[0] = ""
    if code != 0 and paint and (work / "shape.glb").exists() and not (work / "textured.glb").exists():
        # the shape is done, only the paint stage fell over (it loads the heaviest models): paint it alone
        log.append(f"Покраска упала (код {code:#x}), форма готова. Докрашиваю отдельным процессом...")
        yield emit()
        for attempt in range(2):
            r = subprocess.run([HY_PY, str(T.ROOT / "hy_texture_mv.py"), str(work / "shape.glb"),
                                str(work / "view_front.png"), str(work / "textured.glb"), "--tex", str(int(hy_tex))],
                               cwd=HY_SRC, env=env, capture_output=True, text=True, encoding="utf-8",
                               errors="replace", creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            if (work / "textured.glb").exists():
                log.append("Текстура готова.")
                code = 0
                break
            tail = deque((r.stdout + r.stderr).splitlines()[-8:], maxlen=25)
        yield emit()
    if code != 0:
        log.append(f"ОШИБКА: процесс Hunyuan завершился с кодом {code}. Последние строки:")
        log += [f"  {x}" for x in list(tail)[-8:]]
        log.append("Частая причина — нехватка видеопамяти или оперативной памяти: закройте Blender, браузер и "
                   "другие тяжёлые программы.")
        yield emit()
        return

    src = work / "textured.glb"
    textured = src.exists()
    if not textured:
        src = work / "shape.glb"
    if not src.exists():
        log.append("ОШИБКА: модель не создана, смотрите сообщения выше.")
        yield emit()
        return
    if not textured and paint:
        log.append("Внимание: покраска не получилась, экспортирована форма без текстуры.")
    h = height if height and height > 0 else None
    if h is None and preset.get("height_m") is None:
        log.append("Высота не задана: размер остаётся как у модели (Hunyuan нормирует объект примерно до 2 единиц). "
                   "Задайте высоту в метрах в блоке «Размер и pivot».")
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
    log.append(f"Готово за {stats['seconds']} с: {stats['faces']} граней, "
               f"{'с текстурой' if textured else 'без текстуры'} → {final}")
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
            log.append(f"[{stem}] скелет делается только для категории «Персонаж», пропускаю.")
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
                     "Hunyuan3D" if j["kind"] == "hy" else "SF3D", src, "уже готово" if done else "в очереди"])
    return rows


def on_scan(root, default_label):
    jobs = scan_batch(root, LABEL_TO_KEY[default_label])
    if not jobs:
        return [], "Ничего не найдено. Ожидается папка вида: <корень>\\<категория>\\картинка.png или <корень>\\<категория>\\<объект>\\front.png"
    n_hy = sum(j["kind"] == "hy" for j in jobs)
    est = (len(jobs) - n_hy) * 0.5 + n_hy * 10
    return batch_table(jobs), f"Найдено: {len(jobs)} (SF3D: {len(jobs) - n_hy}, Hunyuan3D: {n_hy}). Оценка времени: около {est:.0f} мин."


def batch_run(root, default_label, overwrite, make_preview, auto_materials=False,
              auto_rig=False, rig_naming_label=None, rig_tries=3, progress=None):
    """Run every job found under root, one after another; a failure does not stop the queue.
    With auto_rig, characters get a skeleton in a last phase (after every model is generated)."""
    cfg = T.load_config()
    jobs = scan_batch(root, LABEL_TO_KEY[default_label])
    log, results, last_glb, previews = [], [], None, []
    if not jobs:
        yield "Ничего не найдено. Проверьте папку и схему имён.", results, last_glb, previews
        return
    quiet = lambda *a, **k: None  # noqa: E731
    ok = skipped = failed = 0
    failed_names = []
    t_start = time.time()
    log.append(f"Пакет: {len(jobs)} задач. SF3D сначала, потом Hunyuan3D.")
    yield "\n".join(log), results, last_glb, previews
    for i, j in enumerate(jobs, 1):
        cat_label = CATEGORY_LABELS[j["category"]]
        final = Path(cfg["export_dir"]) / j["category"] / j["name"] / f"{j['name']}.glb"
        head = f"[{i}/{len(jobs)}] {j['name']} ({'Hunyuan3D' if j['kind'] == 'hy' else 'SF3D'}, {cat_label})"
        if final.exists() and not overwrite:
            log.append(f"{head}: уже готово, пропускаю")
            skipped += 1
            yield "\n".join(log), results, last_glb, previews
            continue
        log.append(f"{head}: начинаю")
        base = len(log)
        if j["kind"] == "sf3d":
            inner = generate(j["files"], cat_label, j["name"], 0, 0, 0, "авто (по категории)", "по категории",
                             False, 0.0, 0.8, cfg["texture_resolution"], cfg["foreground_ratio"], True, "none",
                             overwrite, make_preview, 0.0, 1.0, 1.0, auto_materials, progress=quiet)
        else:
            v = j["views"]
            inner = generate_hy(v.get("front"), v.get("back"), v.get("left"), v.get("right"), cat_label,
                                j["name"], 0, 0, 0, "авто (по категории)", "по категории", False, 0.0, 0.8,
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
            log.append(f"{head}: готово")
        else:
            failed += 1
            failed_names.append(j["name"])
            log.append(f"{head}: НЕ УДАЛОСЬ")
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
            log.append(f"Скелеты для персонажей: {len(todo)} шт.")
            yield "\n".join(log), results, last_glb, previews
            rig_log = log  # rig_core appends to it directly
            emit_b = lambda: ("\n".join(log), results, last_glb, previews)  # noqa: E731
            rigged = yield from rig_queue_run(todo, cfg, rig_naming_label, rig_tries, rig_log, emit_b)
            rig_ok = len(rigged)
            rig_failed = len(todo) - rig_ok
            if rigged:
                last_glb = rigged[-1]
    mins = (time.time() - t_start) / 60
    log.append(f"ИТОГО за {mins:.1f} мин: готово {ok}, пропущено {skipped}, ошибок {failed}"
               + (f" ({', '.join(failed_names)})" if failed_names else "")
               + (f"; скелеты: {rig_ok} из {rig_ok + rig_failed}" if auto_rig and (rig_ok + rig_failed) else ""))
    yield "\n".join(log), results, last_glb, previews


# ------------------------------------------------------------------ риггинг
RIG_NAMINGS = {"Mixamo (под анимации из Mixamo)": "mixamo", "Godot (профиль Humanoid)": "godot"}


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
        log.append(f"[{name}] в файле уже есть скелет, он будет удалён перед автоматическим риггингом.")
    log.append(f"[{name}] риггинг начат, это займёт 3–5 минут.")
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
            log.append(f"[{name}] скелет готов за {time.time() - t0:.0f} с: {info.get('bones', '?')} костей.")
            yield emit()
            return result
        fing = info.get("named_fingers", 0)
        log.append(f"[{name}] скелет готов за {time.time() - t0:.0f} с: {info.get('bones', '?')} костей, "
                   f"стандартные имена получили {len(result['mapping'])}"
                   + (f" (из них {fing} костей пальцев)." if fing else ". Пальцев в этом скелете нет: "
                      "можно повторить с большим числом попыток."))
        sm = info.get("seams")
        if sm:
            log.append(f"[{name}] стыки между частями сшиты: {sm['clusters']} мест, "
                       f"разрыв в тестовой позе {sm['gap_before_mm']:.1f} мм → {sm['gap_after_mm']:.1f} мм.")
        if info.get("warning"):
            log.append(f"[{name}] ВНИМАНИЕ: {info['warning']}")
        log.append(f"[{name}] файл со скелетом: {dst}")
        (dst.parent / f"{name}_rig.json").write_text(
            json.dumps(dict(source=str(src), naming=naming_key, **result), indent=2, ensure_ascii=False),
            encoding="utf-8")
    except Exception as e:  # noqa: BLE001
        log.append(f"[{name}] ОШИБКА риггинга: {type(e).__name__}: {e}")
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
        cat, nm = asset.split("/", 1)
        src = Path(cfg["export_dir"]) / cat / nm / f"{nm}.glb"
        if not src.exists():  # rigged exports are not in the dropdown, but allow typing/choosing a plain one
            src = src.with_name(f"{nm}_rigged.glb")
    else:
        log.append("Выберите готовую модель или загрузите GLB со скелетом.")
        yield emit()
        return
    dst = src.with_name(f"{src.stem}_seams.glb")
    log.append(f"Сшиваю стыки: {src.name} (около 30 секунд)...")
    yield emit()
    try:
        sm = RG.weld_seams(src, dst, cfg.get("blender_exe"))
    except Exception as e:  # noqa: BLE001
        sm = None
        log.append(f"ОШИБКА: {type(e).__name__}: {e}")
    if sm:
        log.append(f"Готово: стыков {sm['clusters']}, разрыв в тестовой позе {sm['gap_before_mm']:.1f} мм → "
                   f"{sm['gap_after_mm']:.1f} мм. Файл: {dst}")
        last[0] = str(dst)
    elif not log or not log[-1].startswith("ОШИБКА"):
        log.append("Стыков между частями не найдено (модель из одного куска или у частей нет общих вершин), "
                   "исправлять нечего.")
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
        cat, nm = asset.split("/", 1)
        base = Path(cfg["export_dir"]) / cat / nm
        src = base / f"{nm}_rigged.glb"
        if not src.exists():
            src = base / f"{nm}.glb"
    else:
        log.append("Выберите модель со скелетом или загрузите GLB.")
        yield emit()
        return
    dst = src.with_name(f"{src.stem.removesuffix('_rigged')}_parts.glb")
    log.append(f"Разбиваю на части: {src.name} (около 15 секунд)...")
    yield emit()
    try:
        parts = RG.split_parts(src, dst, cfg.get("blender_exe"))
        log.append(f"Готово: {len(parts)} частей на общем скелете: "
                   + ", ".join(f"{k.replace('Body_', '')} ({v} треуг.)" for k, v in parts.items()))
        log.append(f"Файл: {dst}")
        (dst.with_suffix(".parts.json")).write_text(
            json.dumps(dict(source=str(src), parts=parts), indent=2, ensure_ascii=False), encoding="utf-8")
        last[0] = str(dst)
    except Exception as e:  # noqa: BLE001
        log.append(f"ОШИБКА: {e}")
    yield emit()


SLOT_LABELS = {"Нагрудник": "chest", "Шлем": "helmet", "Перчатки": "gloves", "Сапоги": "boots",
               "Штаны / поножи": "pants", "Наручи": "bracers", "Наплечники": "pauldrons"}


def _parts_bodies():
    cfg = T.load_config()
    return [str(p) for p in sorted(Path(cfg["export_dir"]).rglob("*_parts.glb"))]


LENGTH_LABELS = {"по умолчанию для слота": "", "до груди": "chest", "до талии": "waist", "до бёдер": "hips",
                 "до колен": "knees", "до щиколоток": "ankles"}


FIT_MODES = {"только масштаб (пропорции брони сохраняются)": "uniform",
             "по ориентирам скелета (вписать между ориентирами)": "landmarks"}


def fit_run(body, armour_upload, armour_asset, slot_label, length_label="по умолчанию для слота",
            width=100, height=100, depth=100, up_cm=0, gap_mm=6, scale=100,
            mode_label="только масштаб (пропорции брони сохраняются)", hide_body=False, shrink_pct=0):
    """The 'Подогнать броню' button. Sliders are percentages / centimetres / millimetres."""
    import rigging as RG

    cfg = T.load_config()
    log, last, pics = [], [None], [[]]

    def emit():
        return "\n".join(log), last[0], pics[0]

    if not body:
        log.append("Выберите тело, разбитое на части (кнопка «Разбить тело на части» в блоке «Риггинг»).")
        yield emit()
        return
    if armour_upload:
        src = Path(armour_upload if isinstance(armour_upload, str) else armour_upload.name)
    elif armour_asset:
        cat, nm = armour_asset.split("/", 1)
        src = Path(cfg["export_dir"]) / cat / nm / f"{nm}.glb"
    else:
        log.append("Выберите модель брони или загрузите GLB.")
        yield emit()
        return
    slot = SLOT_LABELS[slot_label]
    body_name = Path(body).stem.removesuffix("_parts")
    dst = Path(cfg["export_dir"]) / "equipment" / body_name / f"{T.slug(src.stem)}_{slot}.glb"
    dst.parent.mkdir(parents=True, exist_ok=True)
    opts = dict(length=LENGTH_LABELS.get(length_label, ""), width=width / 100, height=height / 100,
                depth=depth / 100, up=up_cm / 100, offset=gap_mm / 1000, scale=scale / 100,
                mode=FIT_MODES.get(mode_label, "uniform"), shrink=(shrink_pct or 0) / 100)
    log.append(f"Подгоняю «{src.name}» как {slot_label.lower()} на {body_name} (около 30 секунд)...")
    yield emit()
    try:
        man = RG.fit_armour(body, src, slot, dst, cfg.get("blender_exe"), opts, hide_body=bool(hide_body))
        log += [f"  {x}" for x in man["log"]]
        log.append(f"Готово: {dst}. Прячет: {', '.join(man['hides']) or 'ничего (тело остаётся под бронёй)'}. "
                   f"Манифест: {dst.with_suffix('.item.json').name}")
        log.append("Не нравится посадка? Поменяйте длину или ползунки и нажмите кнопку ещё раз.")
        last[0] = str(dst)
        pics[0] = [(p, "спереди" if "front" in p else "сбоку") for p in man.get("previews", [])]
    except Exception as e:  # noqa: BLE001
        log.append(f"ОШИБКА: {e}")
    yield emit()


RIG_KINDS = {"Человекоподобный (две ноги, руки, пальцы)": "humanoid",
             "Существо (четыре лапы, хвост, морда с пастью)": "creature"}


def _src_of(upload, asset):
    """(path, name, dst folder) of the model chosen in a tab: an uploaded GLB or a ready model."""
    cfg = T.load_config()
    if upload:
        src = Path(upload if isinstance(upload, str) else upload.name)
        name = T.slug(src.stem)
        return src, name, Path(cfg["export_dir"]) / "character" / name
    if asset:
        cat, nm = asset.split("/", 1)
        src = Path(cfg["export_dir"]) / cat / nm / f"{nm}.glb"
        return src, T.slug(nm), src.parent
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
        log.append("Выберите готовую модель или загрузите GLB.")
        yield emit()
        return
    folder.mkdir(parents=True, exist_ok=True)
    raw = folder / f"{name}_unirig.glb"
    result = yield from rig_core(src, raw, name, cfg, "mixamo", 1, log, emit, kind="creature")
    if not result:
        yield emit()
        return
    log.append(f"[{name}] разбираю скелет: где лапы, голова и хвост; ищу линию рта...")
    yield emit()
    try:
        auto = folder / f"{name}_auto.glb"
        names, jaw = RG.creature_auto(raw, auto, cfg.get("blender_exe"))
        legs = sorted({v[:6] for v in names.values() if v.startswith("leg_")})
        tails = sum(1 for v in names.values() if v.startswith("tail_"))
        log.append(f"[{name}] лапы: {', '.join(x[4:] for x in legs)}; костей хвоста: {tails}; "
                   f"голова: {'есть' if 'head' in names.values() else 'не найдена'}.")
        state[0] = dict(auto=str(auto), names=names, jaw=jaw, folder=str(folder), name=name)
        yield from _creature_jaw(state[0], line_mm, hinge_mm, log, last, pics, emit)
    except Exception as e:  # noqa: BLE001
        log.append(f"[{name}] ОШИБКА: {e}")
    yield emit()


def _creature_jaw(st, line_mm, hinge_mm, log, last, pics, emit):
    import rigging as RG

    cfg = T.load_config()
    folder, name = Path(st["folder"]), st["name"]
    dst = folder / f"{name}_rigged.glb"
    log.append(f"[{name}] делаю челюсть (линия рта {line_mm:+.0f} мм, шарнир {hinge_mm:+.0f} мм) и превью...")
    yield emit()
    res = RG.creature_finish(st["auto"], dst, cfg.get("blender_exe"), st["names"], st["jaw"], line_mm, hinge_mm,
                             preview=str(folder / f"{name}_jaw.png"))
    log.append(f"[{name}] готово: {dst.name}. В челюсть вошло вершин: {res['jaw_vertices']}. Посмотрите превью: "
               "если пасть открывается не по линии губ, подвиньте ползунки и нажмите «Пересобрать челюсть».")
    labels = {"0_side": "закрыта, сбоку", "0_front": "закрыта, спереди", "30_side": "открыта, сбоку",
              "30_front": "открыта, спереди"}
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
        log.append("Сначала создайте скелет существа.")
        yield emit()
        return
    try:
        yield from _creature_jaw(state, line_mm, hinge_mm, log, last, pics, emit)
    except Exception as e:  # noqa: BLE001
        log.append(f"ОШИБКА: {e}")
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
        cat, nm = asset.split("/", 1)
        src = Path(cfg["export_dir"]) / cat / nm / f"{nm}.glb"
        name = T.slug(nm)
        dst = src.with_name(f"{nm}_rigged.glb")
    else:
        log.append("Выберите готовую модель или загрузите GLB.")
        yield emit()
        return
    if not src.exists():
        log.append(f"Файл не найден: {src}")
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
        return "Загрузите GLB одетой модели с сегментами (из Tripo).", [], [], "", *hidden
    model = Path(model if isinstance(model, str) else model.name)
    cfg = T.load_config()
    try:
        segs = OF.scan(model, _outfit_work(model), cfg.get("blender_exe"))
    except Exception as e:  # noqa: BLE001
        return f"ОШИБКА: {e}", [], [], "", *hidden
    segs = segs[:MAX_SEGS]
    dd = [gr.update(visible=True, value=s["label"], label=f"{s['name']} ({s['faces']} гр.)") for s in segs]
    dd += hidden[len(segs):]
    pics = [(s["thumb"], f"{s['name']}") for s in segs]
    note = (f"Сегментов: {len(segs)}. Проверьте слоты под картинками: несколько сегментов с одинаковым слотом "
            "станут одной вещью (лицо + шлем = голова целиком, обмотка + ботинок = сапог). "
            "Кожу и тело не берите.")
    return note, pics, [s["name"] for s in segs], T.slug(model.stem), *dd


def outfit_run(model, body, set_name, names, *labels):
    """The 'Перенести сет' button."""
    import outfit as OF

    cfg = T.load_config()
    log, last, pics = [], [None], [[]]

    def emit():
        return "\n".join(log), last[0], pics[0]

    if not model or not names:
        log.append("Сначала загрузите модель и нажмите «Разобрать на сегменты».")
        yield emit()
        return
    if not body:
        log.append("Выберите тело, на которое надевать (файл *_parts.glb).")
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

    log.append(f"Переношу сет «{out_dir.name}» на {body_name}. Первый раз с риггингом одетой модели это "
               "10–15 минут, повторно 3–5 минут.")
    yield emit()
    for x in OF.transfer(model, assign, body, out_dir, _outfit_work(model), blender, rig_dressed):
        if isinstance(x, str):
            log.append(x)
            yield emit()
        else:  # a progress tuple from the rigging step
            yield x
    prev = out_dir / "set_preview_front.png"
    if prev.exists():
        pics[0] = [(str(prev), "весь сет спереди"), (str(out_dir / "set_preview_side.png"), "сбоку")]
        pics[0] += [(str(p), p.stem.replace("_preview_front", ""))
                    for p in sorted(out_dir.glob("*_preview_front.png")) if not p.name.startswith("set_")]
        log.append("Для Godot: у каждой вещи рядом .item.json (слот, что прятать) и .mask.json (какие треугольники "
                   "тела убрать, пока вещь надета); весь сет описан в set.json.")
    yield emit()


# ------------------------------------------------------------------ референсы (картинки для 3D)
REF_PROVIDERS = {"Подписка ChatGPT через Codex (без ключа, ~2 мин на картинку)": "codex",
                 "OpenRouter (по ключу; Nano Banana и другие)": "openrouter"}
REF_CATEGORIES = {"Предмет / оружие": "item", "Объект окружения": "prop", "Здание": "building",
                  "Растение (дерево, куст, трава)": "vegetation",
                  "Персонаж (A-поза)": "character", "Существо / монстр": "creature"}
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
    return f"Стиль сохранён: описание {len(st['text'])} знаков, эталонных картинок {len(st['refs'])}."


def ref_describe(provider_label, files):
    import refgen as RF
    cfg = T.load_config()
    imgs = _paths(files)
    if not imgs:
        return gr.update(), "Добавьте 1–5 эталонных картинок стиля."
    try:
        if REF_PROVIDERS[provider_label] == "codex":
            text = RF.codex_describe(imgs, out_dir=Path(cfg["work_dir"]) / "refgen")
        else:
            text = RF.openrouter_describe(cfg.get("openrouter_key", ""),
                                          cfg.get("openrouter_text_model", "google/gemini-2.5-flash"), imgs)
    except Exception as e:  # noqa: BLE001
        return gr.update(), f"ОШИБКА: {e}"
    return text, "Описание стиля готово. Поправьте, если нужно, и нажмите «Сохранить стиль»."


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
        log.append("Опишите объект, например: «покосившийся деревянный забор с коваными накладками».")
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
        log.append(f"Вариант {k + 1} из {int(variants)}: генерирую...")
        yield emit()
        try:
            out = _ref_one(provider, prompt, refs, folder / f"front_{int(time.time())}.png")
            pics.append((str(out), f"вариант {len(pics) + 1}"))
            log[-1] = f"Вариант {k + 1} готов за {time.time() - t0:.0f} с."
        except Exception as e:  # noqa: BLE001
            log[-1] = f"Вариант {k + 1}: ОШИБКА: {e}"
            yield emit()
            return
        yield emit()
    log.append("Выберите лучший вариант щелчком, затем «Сделать виды сзади и сбоку» или сразу «Отправить в 3D».")
    yield emit()


def ref_pick(paths, evt: gr.SelectData):
    p = paths[evt.index] if paths and evt.index < len(paths) else None
    return p, (f"Выбран вариант {evt.index + 1}." if p else "")


def ref_views(provider_label, front, obj, cat_label, style_text, style_files, want):
    """Back / left / right views of the chosen front picture."""
    import refgen as RF
    cfg = T.load_config()
    log, views = [], {"front": front}

    def emit():
        return "\n".join(log), [(v, k) for k, v in views.items() if v], views

    if not front:
        log.append("Сначала выберите вариант (щелчок по картинке).")
        yield emit()
        return
    provider, category = REF_PROVIDERS[provider_label], REF_CATEGORIES[cat_label]
    refs = _paths(style_files)
    folder = Path(front).parent
    names = {"сзади": "back", "слева": "left", "справа": "right"}
    for label in want or []:
        v = names[label]
        t0 = time.time()
        log.append(f"Вид {label}: генерирую...")
        yield emit()
        prompt = RF.build_prompt(obj or "the object in the first picture", category, style_text, v,
                                 has_style_refs=bool(refs), has_front=True)
        try:
            views[v] = str(_ref_one(provider, prompt, [front] + refs, folder / f"{v}_{int(time.time())}.png"))
            log[-1] = f"Вид {label} готов за {time.time() - t0:.0f} с."
        except Exception as e:  # noqa: BLE001
            log[-1] = f"Вид {label}: ОШИБКА: {e}"
        yield emit()
    log.append("Проверьте, что на всех видах один и тот же объект, и нажмите «Отправить в 3D».")
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
            gr.Tabs(selected="gen"))


def ref_save_keys(key, img_model, txt_model):
    cfg = T.load_config()
    if key and key.strip() and not set(key.strip()) <= {"•"}:
        cfg["openrouter_key"] = key.strip()
    cfg["openrouter_image_model"] = (img_model or "").strip() or "google/gemini-2.5-flash-image"
    cfg["openrouter_text_model"] = (txt_model or "").strip() or "google/gemini-2.5-flash"
    (T.ROOT / "config.json").write_text(json.dumps(cfg, indent=2, ensure_ascii=False), encoding="utf-8")
    return "Настройки OpenRouter сохранены." + (" Ключ задан." if cfg.get("openrouter_key") else " Ключ не задан.")

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
        log.append("Опишите поверхность (например: «утоптанная земля с травинками и мелкими камнями») "
                   "или загрузите свою картинку.")
        yield emit()
        return
    stem = T.slug(name or desc or Path(own).stem)[:40]
    folder = Path(cfg["work_dir"]) / "refgen" / f"surface_{stem}"
    folder.mkdir(parents=True, exist_ok=True)
    if own:
        src = Path(own)
        log.append(f"Беру вашу картинку: {src.name}")
    else:
        st = RF.load_style(cfg["work_dir"])
        prompt = RF.build_prompt(desc, "surface", st["text"], has_style_refs=bool(st["refs"]))
        (folder / "prompt.txt").write_text(prompt, encoding="utf-8")
        log.append("Генерирую текстуру (вид сверху)...")
        yield emit()
        t0 = time.time()
        try:
            src = _ref_one(REF_PROVIDERS[provider_label], prompt, st["refs"], folder / f"src_{int(time.time())}.png")
        except Exception as e:  # noqa: BLE001
            log.append(f"ОШИБКА: {e}")
            yield emit()
            return
        log[-1] = f"Текстура готова за {time.time() - t0:.0f} с."
    log.append("Делаю бесшовной и считаю карты (нормали, высота, шероховатость, затенение)...")
    yield emit()
    out = Path(cfg["export_dir"]) / "materials" / stem
    info = S.make_material(src, out, stem, size=int(size), strength=float(strength), tile_m=float(tile_m))
    fixed = info["seam_before"] > 1.15
    log.append(f"Готово: {out}. Шов на краях: {info['seam_before']} → {info['seam_after']} "
               f"({'сшит' if fixed else 'генератор сделал бесшовно сам'}; 1,0 — как внутри картинки).")
    log.append(f"В Godot: скопируйте папку «{stem}» в проект и назначьте {stem}.tres как материал. "
               f"Плитка повторяется каждые {tile_m:g} м (меняется в материале: uv1_scale).")
    pics.append((str(out / f"{stem}_preview.png"), "слева 3×3 плитки (швы видны бы сразу), справа рельеф под светом"))
    pics.append((str(out / info["files"]["normal"]), "карта нормалей"))
    pics.append((str(out / info["files"]["roughness"]), "шероховатость"))
    yield emit()

# ------------------------------------------------------------------ эффекты (листы для частиц, спрайты, сцены Godot)
FX_KINDS = {"Взрыв (один раз)": "explosion", "Дым (один раз)": "smoke", "Огонь (цикл)": "fire",
            "Магическая вспышка (один раз)": "magic", "Искра / уголёк (один кадр)": "spark"}
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
    note = (f"Готово: {out}. Кадров {info['frames']} ({info['grid']}×{info['grid']})"
            + (", лист зациклен" if info.get("loop") else "") + ". В Godot у материала частиц: "
            f"Particles Anim H/V Frames = {info['grid']}, у частиц Anim Speed = 1.")
    if stem in ("explosion", "smoke", "fire", "magic", "spark"):
        note += " Имя совпадает со стандартным: после «Собрать сцены» эффекты подхватят новый лист."
    return note, [(str(view), stem)]


def fx_sprite_run(provider_label, desc, name):
    """A glowing sprite (rune, spark, spell symbol) generated on black; brightness becomes transparency."""
    import numpy as np
    from PIL import Image
    if not (desc or "").strip():
        return "Опишите спрайт, например: «светящаяся руна огня», «круг призыва с рунами».", []
    stem = T.slug(name or desc)[:40]
    work = Path(T.load_config()["work_dir"]) / "refgen" / f"fx_{stem}"
    work.mkdir(parents=True, exist_ok=True)
    prompt = (f"A glowing spell effect sprite for a fantasy ARPG: {desc.strip()}. Bright luminous lines and glow on a "
              "pure black background, nothing else, centred, fills about 90 % of the square picture, flat, seen "
              "straight on, no text.")
    try:
        src = _ref_one(REF_PROVIDERS[provider_label], prompt, [], work / f"src_{int(time.time())}.png")
    except Exception as e:  # noqa: BLE001
        return f"ОШИБКА: {e}", []
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
    note = f"Готово: {out}. Чёрный фон стал прозрачностью: в Godot используйте сложение (Blend Mode = Add)."
    if stem == "magic_circle":
        note += " Имя стандартное: «Собрать сцены» подставит его в magic_circle.tscn."
    return note, [(str(view), stem)]


def fx_build_scenes():
    """Build the Godot scenes from the textures in export/fx/sf3d_fx with headless Godot (in a scratch project)."""
    cfg = T.load_config()
    godot = cfg.get("godot_exe")
    if not godot or not Path(godot).exists():
        return "Не найден Godot: укажите godot_exe в tool/config.json.", []
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
            return ("Нет текстуры magic_circle.png: сделайте спрайт с именем «magic_circle» (например, «круг призыва "
                    "с рунами») и нажмите ещё раз."), []
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
        "# Эффекты SF3D\n\nСкопируйте папку `sf3d_fx` в корень проекта Godot (путь должен быть `res://sf3d_fx/`).\n"
        "Сцены: explosion, fire, smoke, magic_circle, hit_sparks. Перетащите сцену в уровень или создайте из кода:\n"
        "`var fx = preload(\"res://sf3d_fx/explosion.tscn\").instantiate(); add_child(fx)`.\n"
        "У корня сцены свойство Auto Free: одноразовый эффект удалится сам после окончания.\n"
        "Цвет и размер меняются в инспекторе у частиц (Draw Pass, Process Material).\n", encoding="utf-8")
    if not built:
        return "Сцены не собрались: " + (r.stdout + r.stderr)[-400:], []
    return (f"Собрано сцен: {len(built)} ({', '.join(built)}) в {src}. Скопируйте папку sf3d_fx в корень "
            "проекта Godot (res://sf3d_fx/)."), []

# ------------------------------------------------------------------ модульные наборы (подземелье)
KIT_PROC = "(процедурный камень)"


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
        log.append("Выберите материалы пола и дерева (их можно сделать во вкладке «Поверхности»).")
        yield emit()
        return
    if not wall or wall == KIT_PROC:
        wall = "dungeon_block"
        if not (mats / wall / f"{wall}_albedo.png").exists():
            log.append("Делаю процедурный камень для блоков...")
            yield emit()
            src = S.procedural_stone(Path(cfg["work_dir"]) / "refgen" / "dungeon_block_src.png", 1024, 3,
                                     (0.32, 0.303, 0.26))
            S.make_material(src, mats / wall, wall, size=1024, strength=0.45, tile_m=2.0)
    out = _kit_dir()
    out.mkdir(parents=True, exist_ok=True)
    log.append("Blender собирает детали набора (около минуты)...")
    yield emit()
    pv = out / "preview.png"
    try:
        lines = MK.build_kit(cfg["blender_exe"], out, mats, cell=float(cell), height=float(height), seed=int(seed),
                             preview=str(pv), wall=wall, floor=floor, wood=wood)
    except Exception as e:  # noqa: BLE001
        log.append(f"ОШИБКА: {e}")
        yield emit()
        return
    n = sum(1 for x in lines if x.startswith("KIT_PIECE"))
    log[-1] = (f"Готово: {n} деталей в {out} (kit.glb + kit.json). Теперь «Построить сцену» по плану ниже. "
               "Ячейка {:g} м, этаж {:g} м.".format(float(cell), float(height)))
    yield emit([(str(pv), "детали набора: пол, потолок, стены, дверной проём, арка, окно, углы, колонна, лестница, дверь")]
               if pv.exists() else [])


def kit_scene(plan_text, ceilings):
    """'Построить сцену': a text plan -> placements -> Godot builds piece scenes, MeshLibrary and a demo scene."""
    import modkit as MK
    cfg = T.load_config()
    kit = _kit_dir()
    if not (kit / "kit.glb").exists():
        return "Сначала соберите детали набора (кнопка выше).", []
    godot = cfg.get("godot_exe")
    if not godot or not Path(godot).exists():
        return "Не найден Godot: укажите godot_exe в tool/config.json.", []
    try:
        plan = MK.parse_plan(plan_text)
    except ValueError as e:
        return str(e), []
    if not ceilings:
        plan["pieces"] = [p for p in plan["pieces"] if p["piece"] != "ceiling"]
    try:
        ok, raw = MK.build_godot(godot, kit, cfg["work_dir"], plan)
    except Exception as e:  # noqa: BLE001
        return f"ОШИБКА: {e}", []
    shots = []
    try:
        shots = MK.render_shots(godot, kit, cfg["work_dir"], plan)
    except Exception:  # noqa: BLE001
        pass
    MK.write_readme(kit)
    from collections import Counter
    cnt = Counter(p["piece"] for p in plan["pieces"])
    txt = ", ".join(f"{k} ×{v}" for k, v in cnt.most_common())
    return (f"Готово: {kit}\nВ плане {plan['levels']} эт., деталей {len(plan['pieces'])}: {txt}. "
            f"Дверей {plan['doors']}, факелов {len(plan['lights'])}.\n"
            "Скопируйте папку dungeon_kit в проект Godot (res://dungeon_kit/). Откройте dungeon_demo.tscn; "
            "детали лежат в pieces/, библиотека для GridMap: dungeon_kit.meshlib."), [(s, Path(s).stem) for s in shots]


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
        log.append("Выберите готовую модель или загрузите GLB (бочка, ящик, ваза...).")
        yield emit()
        return
    stem = T.slug(name or nm)
    log.append("Работаю...")
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
        log.append(f"ОШИБКА: {e}")
        yield emit()
        return
    r = res["r"]
    log.append(f"Готово: {r['scene']}\nСкопируйте папку {r['folder']} в корень проекта Godot "
               "(res://sf3d_destructibles/). Пример кода и свойства — в README рядом.")
    cap = ["цел", "0,12 с после удара", "0,4 с", "через 1,4 с"]
    yield emit([(p, cap[i] if i < len(cap) else "") for i, p in enumerate(r["shots"])])



import hanim as HA  # noqa: E402


# ------------------------------------------------------------------ библиотека анимаций человекоподобных
def _rigged_assets():
    cfg = T.load_config()
    out = []
    for p in sorted(Path(cfg["export_dir"]).rglob("*_rigged*.glb")):
        out.append(f"{p.parent.parent.name}/{p.stem}")
    return out


def _rigged_path(asset):
    cat, nm = asset.split("/", 1)
    return Path(T.load_config()["export_dir"]) / cat / nm.split("_rigged")[0] / f"{nm}.glb"


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
        yield "Выберите модель со скелетом (из вкладки «Скелет») или загрузите свой GLB со скелетом.", [], None
        return
    inv = {v: k for k, v in HA.CLIPS.items()}
    clips = [inv[c] for c in clip_labels if c in inv] or list(HA.CLIPS)
    name = T.slug(src.stem.replace("_rigged", "").replace("_wings", ""))
    dst = Path(cfg["export_dir"]) / "character" / name / f"{name}_anim.glb"
    prev = Path(cfg["work_dir"]) / "hanim" / name / "prev"
    log = [f"Добавляю {len(clips)} анимаций к «{src.name}» (около минуты)..."]
    yield "\n".join(log), [], None
    try:
        info = HA.animate(cfg["blender_exe"], src, dst, clips, prev)
    except Exception as e:  # noqa: BLE001
        yield f"ОШИБКА: {e}", [], None
        return
    pics = HA.sheets(prev, clips, Path(cfg["work_dir"]) / "hanim" / name / "sheets")
    names = ", ".join(c["name"].replace("_loop", "") for c in info["clips"])
    log = [f"Готово: {dst}", f"Клипы: {names}.",
           "В Godot импорт сам включит зацикливание у idle, walk, run, fall, block (по суффиксу _loop в файле). "
           f"Скорость, под которую рассчитаны шаги: ходьба ≈ {info['walk_speed']} м/с, бег ≈ {info['run_speed']} м/с "
           f"(для роста {info['height']:.2f} м). Анимация прыжка включает подъём корпуса: не поднимайте персонажа "
           "физикой в тот же момент либо берите fall и land отдельно.",
           "Анимации «на месте»: перемещение делает ваш код (CharacterBody3D)."]
    yield "\n".join(log), pics, str(dst)


# ------------------------------------------------------------------ анимации Mixamo (FBX без скина)
def _fbx_dir():
    return str(Path(T.load_config()["export_dir"]) / "fbx")


def fbx_scan(folder):
    """'Прочитать папку': one table row per FBX, with the settings saved in map.json."""
    import fbxanim as FA
    p = Path((folder or "").strip() or _fbx_dir())
    if not p.exists():
        return [], f"Папка не найдена: {p}"
    rows = FA.table_rows(p)
    if not rows:
        return [], f"В папке {p} нет .fbx. Скачайте анимации из Mixamo (формат FBX, Without Skin) и положите сюда."
    return rows, (f"Найдено файлов: {len(rows)}. Имя клипа и группу можно править, «Цикл» отмечайте у стоек, шага и бега, "
                  "«Скорость» больше 1 ускоряет клип (например подбор с земли), «На месте» убирает смещение корпуса по земле.")


def _viewer_frame(page):
    import html as _html
    return ('<iframe srcdoc="%s" style="width:100%%;height:660px;border:0;border-radius:10px" '
            'allow="fullscreen"></iframe>' % _html.escape(page, quote=True))


def fbx_run(upload, asset, folder, rows, weapon_set="Нет"):
    """'Перенести на модель': Blender copies the FBX motions onto the chosen skeleton; the result opens in the viewer."""
    import fbxanim as FA
    cfg = T.load_config()
    p = Path((folder or "").strip() or _fbx_dir())
    src = Path(upload if isinstance(upload, str) else upload.name) if upload else (
        _rigged_path(asset) if asset else None)
    if not src or not src.exists():
        yield "Выберите модель со скелетом (из списка или свой GLB).", gr.update(), None
        return
    if not rows or not len(rows):
        yield "Сначала нажмите «Прочитать папку».", gr.update(), None
        return
    rows = [list(r) for r in (rows.values.tolist() if hasattr(rows, "values") else rows)]
    FA.save_map(p, rows)
    name = T.slug(src.stem.replace("_rigged", "").replace("_wings", ""))
    dst = Path(cfg["export_dir"]) / "character" / name / f"{name}_fbx.glb"
    yield f"Blender переносит {len(rows)} анимаций на «{src.name}» (около минуты)...", gr.update(), None
    try:
        info = FA.retarget(cfg["blender_exe"], src, p, dst)
    except Exception as e:  # noqa: BLE001
        yield f"ОШИБКА: {e}", gr.update(), None
        return
    log = [f"Готово: {dst}", "Клипы: " + ", ".join(f"{c['name']} ({c['seconds']:.2f} с)" for c in info["clips"]) + "."]
    if info["missing"]:
        log.append("У модели нет костей, которые есть в FBX, они остаются в покое: " + ", ".join(info["missing"][:8]))
    if info["rest"]:
        m = re.search(r"max head difference ([0-9.]+) m", info["rest"])
        if m:
            log.append("Позы покоя модели и FBX различаются на %s м (у Mixamo T-поза): это учтено при переносе."
                       % m.group(1).replace(".", ","))
    log.append("Справа можно смотреть каждый клип. Тот же GLB уже можно подключать в Godot (имена клипов — из таблицы).")
    yield "\n".join(log), _viewer_frame(FA.viewer_html(dst, info, rows, weapon_set)), str(dst)


def fbx_save(folder, rows):
    import fbxanim as FA
    p = Path((folder or "").strip() or _fbx_dir())
    if not rows or not len(rows):
        return "Таблица пуста."
    rows = [list(r) for r in (rows.values.tolist() if hasattr(rows, "values") else rows)]
    FA.save_map(p, rows)
    return f"Настройки сохранены в {p / 'map.json'}"


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
        return (None, "Выберите ассет из списка (нажмите «Обновить список»). В списке есть только то, что создано "
                      "этой версией программы.", *_hidden_groups())
    import trimesh

    scene = trimesh.load(d["src"], force="scene")
    g = next((g for g in scene.geometry.values()
              if getattr(getattr(g.visual, "material", None), "baseColorTexture", None) is not None
              and getattr(g.visual, "uv", None) is not None), None)
    if g is None:
        return None, "У этой модели нет цветной текстуры, распознавать нечего.", *_hidden_groups()
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
                label=f"Группа {j + 1} — {st['share'] * 100:.0f}% текстуры, средний цвет ({r}, {gg}, {b}); "
                      f"предложено: {MT.MATERIALS[key][0]} ({conf:.0%})"))
        else:
            groups.append(gr.update(visible=False, value=None))
    note = (f"Найдено групп: {an['k']}. Цвета на картинке слева соответствуют номерам групп. "
            f"Проверьте названия и нажмите «Применить».")
    return MT.overlay(tex, an), note, *groups


def mat_apply(asset, *values):
    work, d = _mat_params(asset)
    if d is None:
        return "Сначала выберите ассет и нажмите «Проанализировать».", None, []
    assign = [v for v in values if v]
    if not assign:
        return "Нет групп: нажмите «Проанализировать».", None, []
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
    return f"Применено ({rows}). Файл обновлён: {final}", str(final), previews


# ------------------------------------------------------------------ настройки
def save_settings(export_dir):
    export_dir = (export_dir or "").strip().strip('"')
    if not export_dir:
        return "Путь к папке экспорта пуст."
    cfg = T.load_config()
    cfg["export_dir"] = export_dir.replace("\\", "/")
    (T.ROOT / "config.json").write_text(json.dumps(cfg, indent=2), encoding="utf-8")
    return f"Сохранено. Теперь экспорт идёт в: {export_dir}"


def open_export(export_dir):
    p = Path((export_dir or T.load_config()["export_dir"]).strip().strip('"'))
    p.mkdir(parents=True, exist_ok=True)
    os.startfile(str(p))
    return f"Открыта папка {p}"


def on_category(category_label):
    p = T.load_config()["categories"][LABEL_TO_KEY[category_label]]
    pivot = {"bottom": "у основания", "center": "в центре"}[p["pivot"]]
    h = f"{p['height_m']} м" if p["height_m"] else "не меняется"
    m = p["metallic"] if p["metallic"] is not None else "как сгенерировано"
    r = p["roughness"] if p["roughness"] is not None else "как сгенерировано"
    return f"Пресет: pivot {pivot}, высота {h}, металличность {m}, шероховатость {r}"


# ------------------------------------------------------------------ интерфейс
UI_CSS = """
.gradio-container { max-width: 1400px !important; }
.tab-nav button { font-size: 15px; font-weight: 600; }
"""

def build():
    cfg = T.load_config()
    labels = [CATEGORY_LABELS[k] for k in cfg["categories"]]
    default_cat = CATEGORY_LABELS["prop"]
    import outfit as OF
    with gr.Blocks(title="SF3D — игровые ассеты", theme=gr.themes.Soft(), css=UI_CSS) as ui:
        gr.Markdown("## SF3D — игровые ассеты\n"
                    "Порядок работы слева направо по вкладкам: **референс** → **создать модель** → **скелет и анимация** → "
                    "**экипировка**. В каждой вкладке справа 3D-просмотр: модель появляется сразу, как только "
                    "вы её выбрали или загрузили. Крутите мышью, колесо приближает.")
        with gr.Tabs() as main_tabs:
            # ---------------------------------------------------------------- 0. reference pictures
            with gr.Tab("Референс", id="ref"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("**1. Что нужно.** Опишите объект своими словами. Стиль, ракурс, фон и требования "
                                    "для 3D программа добавит сама.")
                        ref_obj = gr.Textbox(label="Объект", lines=2,
                                             placeholder="например: покосившийся деревянный забор с коваными накладками")
                        with gr.Row():
                            ref_cat = gr.Dropdown(list(REF_CATEGORIES), value="Объект окружения", label="Тип", scale=2)
                            ref_n = gr.Slider(1, 4, value=1, step=1, label="Вариантов", scale=1)
                        ref_provider = gr.Radio(list(REF_PROVIDERS), value=list(REF_PROVIDERS)[0],
                                                label="Чем генерировать")
                        ref_go = gr.Button("Сгенерировать", variant="primary")
                        with gr.Accordion("Стиль проекта (общий для всех референсов)", open=False):
                            gr.Markdown("Эталонные картинки (3–5 удачных ассетов) прикладываются к каждому запросу, "
                                        "описание стиля добавляется в текст. «Описать по картинкам» составит описание "
                                        "само.")
                            ref_style_text = gr.Textbox(label="Описание стиля (по-английски точнее)", lines=4)
                            ref_style_files = gr.File(label="Эталонные картинки стиля", file_count="multiple",
                                                      file_types=["image"], type="filepath")
                            with gr.Row():
                                ref_describe_btn = gr.Button("Описать по картинкам")
                                ref_style_save_btn = gr.Button("Сохранить стиль")
                            ref_style_note = gr.Markdown("")
                        ref_log = gr.Textbox(label="Ход работы", lines=5, interactive=False)
                    with gr.Column(scale=1):
                        ref_gallery = gr.Gallery(label="Варианты (щёлкните лучший)", columns=2, height=420,
                                                 allow_preview=True)
                        ref_choice_note = gr.Markdown("")
                        ref_want = gr.CheckboxGroup(["сзади", "слева", "справа"], value=["сзади", "слева", "справа"],
                                                    label="Дополнительные виды (для Hunyuan3D, лучшая форма)")
                        with gr.Row():
                            ref_views_btn = gr.Button("Сделать виды по выбранному варианту")
                            ref_send_btn = gr.Button("Отправить в 3D", variant="primary")
                        ref_views_gallery = gr.Gallery(label="Виды", columns=4, height=200)
                ref_paths = gr.State([])
                ref_front = gr.State(None)
                ref_views_state = gr.State({})

            # ---------------------------------------------------------------- 1. generation
            with gr.Tab("1. Создать модель", id="gen"):
                with gr.Row():
                    with gr.Column(scale=1):
                        engine = gr.Radio([ENGINE_SF3D, ENGINE_HY], value=ENGINE_SF3D, label="Движок")
                        files = gr.File(label="Картинки (одна или несколько)", file_count="multiple",
                                        file_types=["image"], type="filepath")
                        with gr.Group(visible=False) as hy_views:
                            gr.Markdown("**Виды объекта** (одна и та же модель с разных сторон; обязателен «Спереди»). "
                                        "«Слева» и «справа» — со стороны левой и правой руки объекта.")
                            with gr.Row():
                                v_front = gr.Image(label="Спереди *", type="filepath", sources=["upload"], height=150)
                                v_back = gr.Image(label="Сзади", type="filepath", sources=["upload"], height=150)
                            with gr.Row():
                                v_left = gr.Image(label="Слева", type="filepath", sources=["upload"], height=150)
                                v_right = gr.Image(label="Справа", type="filepath", sources=["upload"], height=150)
                        with gr.Row():
                            category = gr.Dropdown(labels, value=default_cat, label="Категория", scale=1)
                            name = gr.Textbox(label="Имя (если картинка одна; иначе — имя файла)", scale=1)
                        preset_note = gr.Markdown(on_category(default_cat))
                        veg_kind = gr.Radio(list(VEG_KINDS), value="Дерево", visible=False,
                                            label="Что за растение (для ветра в Godot: как гнётся и где листва)")
                        with gr.Accordion("Размер и pivot", open=False):
                            height = gr.Number(label="Высота модели в метрах (0 — по умолчанию для категории)",
                                               value=0)
                            with gr.Row():
                                width = gr.Number(label="Ширина (по X), м; 0 — не менять", value=0)
                                depth = gr.Number(label="Глубина (по Z), м; 0 — не менять", value=0)
                            pivot = gr.Radio(list(PIVOT_LABELS), value="авто (по категории)",
                                             label="Точка привязки (pivot)")
                            collision = gr.Dropdown(list(COLLISION_LABELS), value="по категории",
                                                    label="Коллизия для Godot (создаётся при импорте автоматически)")
                        with gr.Accordion("Материал и цвет", open=False):
                            override = gr.Checkbox(label="Задать металличность и шероховатость вручную", value=False)
                            metallic = gr.Slider(0, 1, value=0.0, step=0.05, label="Металличность")
                            roughness = gr.Slider(0, 1, value=0.8, step=0.05, label="Шероховатость")
                            color_match = gr.Slider(0, 1, value=0.0, step=0.05,
                                                    label="Подгонка палитры под ваши картинки (0 — выкл.)")
                            saturation = gr.Slider(0.3, 1.5, value=1.0, step=0.05,
                                                   label="Насыщенность (1 — без изменений)")
                            brightness = gr.Slider(0.5, 1.5, value=1.0, step=0.05, label="Яркость (1 — без изменений)")
                            auto_materials = gr.Checkbox(label="Распознать материалы (дерево, металл, камень…) и "
                                                               "построить карты шероховатости и металличности",
                                                         value=False)
                        with gr.Accordion("Параметры Hunyuan3D", open=False, visible=False) as hy_params:
                            paint = gr.Checkbox(label="Красить текстурой (без неё — серая форма, быстрее)", value=True)
                            hy_tex = gr.Dropdown([1024, 2048], value=2048, label="Размер текстуры")
                            hy_faces = gr.Slider(10000, 100000, value=50000, step=5000,
                                                 label="Целевое число граней после упрощения")
                            hy_steps = gr.Slider(20, 50, value=50, step=5, label="Шагов диффузии (меньше — быстрее)")
                        with gr.Accordion("Параметры генерации SF3D", open=False) as sf_params:
                            tex_res = gr.Dropdown([512, 1024, 2048], value=1024,
                                                  label="Размер текстуры (2048 может не поместиться в 8 ГБ)")
                            fg_ratio = gr.Slider(0.5, 1.0, value=cfg["foreground_ratio"], step=0.01,
                                                 label="Доля предмета в кадре")
                            remove_bg = gr.Checkbox(label="Удалять фон (выключите, если фон уже прозрачный)",
                                                    value=True)
                            remesh = gr.Dropdown(["none", "triangle", "quad"], value="none",
                                                 label="Ремеш (none — без изменений)")
                        with gr.Row():
                            make_preview = gr.Checkbox(label="Превью и иконка (Blender, ~10 с)", value=True)
                            overwrite = gr.Checkbox(label="Перезаписать уже готовое", value=False)
                        auto_rig = gr.Checkbox(label="Сразу создать скелет человекоподобному персонажу "
                                                     "(категория «Персонаж», ещё 3–5 минут)", value=False)
                        go = gr.Button("Создать модель", variant="primary", size="lg")
                    with gr.Column(scale=1):
                        viewer = gr.Model3D(label="Результат", height=460, clear_color=(0.9, 0.9, 0.9, 1))
                        inputs_gallery = gr.Gallery(label="Подготовленные картинки, превью и иконка",
                                                    columns=4, height=150)
                        logbox = gr.Textbox(label="Журнал", lines=6, interactive=False)
                table = gr.Dataframe(headers=["имя", "категория", "граней", "размер (м)", "секунд", "файл"],
                                     label="Создано за эту сессию", interactive=False, wrap=True)

            # ---------------------------------------------------------------- 2. rigging
            with gr.Tab("2. Скелет и анимация"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("**1. Модель.** Выберите созданную или загрузите свою (например, из Tripo). "
                                    "Она сразу появится справа. Если в файле уже есть скелет, он будет заменён.")
                        with gr.Row():
                            rig_asset = gr.Dropdown(_export_assets(), label="Готовая модель (категория/имя)",
                                                    scale=4)
                            rig_refresh_btn = gr.Button("Обновить", scale=1)
                        rig_upload = gr.File(label="…или загрузите GLB", file_types=[".glb"], type="filepath")
                        gr.Markdown("**2. Тип.**")
                        rig_kind = gr.Radio(list(RIG_KINDS), value=list(RIG_KINDS)[0], label="Какой скелет нужен")
                        with gr.Group() as rig_human:
                            rig_naming = gr.Radio(list(RIG_NAMINGS), value=list(RIG_NAMINGS)[0],
                                                  label="Имена костей")
                            rig_tries = gr.Slider(1, 6, value=3, step=1,
                                                  label="Попыток подобрать скелет с пальцами (каждая около минуты)")
                        with gr.Group(visible=False) as rig_creature:
                            gr.Markdown("Кости получат понятные имена (`hips`, `spine`, `head`, `leg_FL…`, `tail…`), "
                                        "модель развернётся мордой вперёд, а по линии рта появится кость `jaw`. "
                                        "Лучше всего, если пасть на модели приоткрыта.")
                            with gr.Row():
                                jaw_line = gr.Slider(-40, 40, value=0, step=1,
                                                     label="Линия рта: выше (+) / ниже (−), мм")
                                jaw_hinge = gr.Slider(-40, 40, value=0, step=1,
                                                      label="Шарнир челюсти: дальше (+) / ближе к носу (−), мм")
                        rig_btn = gr.Button("Создать скелет (3–6 минут, ~3,5 ГБ видеопамяти)", variant="primary")
                        with gr.Group(visible=False) as rig_creature_after:
                            rejaw_btn = gr.Button("Пересобрать челюсть с новыми ползунками (около 30 секунд)")
                        with gr.Accordion("Для человекоподобных: стыки и части тела под броню", open=False) as rig_extra:
                            seam_btn = gr.Button("Починить стыки между частями (модель уже со скелетом)")
                            split_btn = gr.Button("Разбить тело на части для брони (голова, торс, таз, руки, ноги…)")
                        rig_log = gr.Textbox(label="Ход работы", lines=8, interactive=False)
                    with gr.Column(scale=1):
                        rig_view = gr.Model3D(label="Модель", height=460, clear_color=(0.9, 0.9, 0.9, 1))
                        jaw_gallery = gr.Gallery(label="Челюсть: закрыта и открыта", columns=4, height=220)
                creature_state = gr.State(None)
                landmarks_ui.mount(T.load_config, rig_asset, rig_upload)
                rwt_ui.mount(T.load_config)  # GPT: Optional repair retains the skeleton.
            # ---------------------------------------------------------------- humanoid animation library
            with gr.Tab("Анимации (человекоподобные)", id="hanim"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("Набор готовых клипов для человекоподобного персонажа **со скелетом** (вкладка "
                                    "«Скелет и анимация», тип «Человекоподобный»): покой, ходьба, бег, прыжок, "
                                    "падение, приземление, два удара, заклинание, блок, получение удара, смерть. "
                                    "Клипы считаются по костям модели, поэтому подходят и гоблину, и фее. Результат — "
                                    "один GLB с моделью и всеми анимациями. Анимации «на месте»: двигает персонажа "
                                    "ваш код.")
                        with gr.Row():
                            ha_asset = gr.Dropdown(_rigged_assets(), label="Модель со скелетом", scale=4)
                            ha_refresh_btn = gr.Button("Обновить", scale=1)
                        ha_upload = gr.File(label="…или загрузите GLB со скелетом", file_types=[".glb"],
                                            type="filepath")
                        ha_clips = gr.CheckboxGroup(list(HA.CLIPS.values()), value=list(HA.CLIPS.values()),
                                                    label="Какие клипы добавить")
                        ha_btn = gr.Button("Добавить анимации", variant="primary")
                        ha_log = gr.Textbox(label="Ход работы", lines=8, interactive=False)
                    with gr.Column(scale=1):
                        ha_view = gr.Model3D(label="Результат (поза покоя)", height=320,
                                             clear_color=(0.9, 0.9, 0.9, 1))
                        ha_gallery = gr.Gallery(label="Кадры клипов (вид сбоку, 6 кадров на клип)", columns=1,
                                                height=420)

            # ---------------------------------------------------------------- Mixamo FBX animations
            with gr.Tab("Анимации Mixamo (FBX)", id="fbxanim"):
                with gr.Row():
                    with gr.Column(scale=4):
                        gr.Markdown("Анимации из Mixamo (**FBX, Without Skin**, по возможности «In Place») переносятся на "
                                    "скелет вашей модели. Кости должны называться как в Mixamo (`mixamorig:...`): так "
                                    "называет их вкладка «Скелет». Результат — один GLB с именованными клипами, он "
                                    "открывается справа, и там же его можно проиграть.")
                        with gr.Row():
                            fx_asset = gr.Dropdown(_rigged_assets(), label="Модель со скелетом", scale=4)
                            fx_refresh = gr.Button("Обновить", scale=1)
                        fx_upload = gr.File(label="…или свой GLB со скелетом", file_types=[".glb"], type="filepath")
                        fx_folder = gr.Textbox(value=_fbx_dir(), label="Папка с FBX")
                        with gr.Row():
                            fx_scan_btn = gr.Button("Прочитать папку")
                            fx_save_btn = gr.Button("Сохранить настройки")
                        fx_table = gr.Dataframe(headers=["Файл", "Имя клипа", "Цикл", "Скорость", "На месте", "Группа"],
                                                datatype=["str", "str", "bool", "number", "bool", "str"],
                                                col_count=(6, "fixed"), interactive=True, type="array", wrap=True)
                        fx_weapon = gr.Dropdown(list(__import__("fbxanim").WEAPON_SETS), value="Нет",
                                                label="Оружие в руках (только для просмотра)")
                        fx_go = gr.Button("Перенести на модель", variant="primary")
                        fx_log = gr.Textbox(label="Ход работы", lines=7, interactive=False)
                        fx_file = gr.File(label="Готовый GLB", interactive=False)
                    with gr.Column(scale=6):
                        fx_view = gr.HTML(value='<div style="padding:24px;color:#888">Здесь появится окно просмотра: '
                                                'выберите модель и нажмите «Перенести на модель».</div>')

            # ---------------------------------------------------------------- 3. equipment
            with gr.Tab("3. Экипировка"):
                with gr.Tabs():
                    with gr.Tab("Перенести сет с одетой модели"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown(
                                    "Сгенерируйте **того же персонажа в сете** (A-поза), в Tripo разбейте на сегменты "
                                    "так, чтобы каждая вещь была своим сегментом, и экспортируйте GLB. **1.** Загрузите "
                                    "его и нажмите «Разобрать». **2.** Проверьте слоты под картинками. "
                                    "**3.** «Перенести сет».")
                                out_model = gr.File(label="GLB одетой модели с сегментами", file_types=[".glb"],
                                                    type="filepath")
                                with gr.Row():
                                    out_body = gr.Dropdown(_parts_bodies(), label="На какое тело (*_parts.glb)",
                                                           scale=3)
                                    out_refresh = gr.Button("Обновить", scale=1)
                                out_name = gr.Textbox(label="Название сета (папка в equipment/<тело>/)")
                                out_scan_btn = gr.Button("Разобрать на сегменты")
                            with gr.Column(scale=1):
                                out_m3d = gr.Model3D(label="Модель", height=420, clear_color=(0.9, 0.9, 0.9, 1))
                        out_note = gr.Markdown("")
                        out_thumbs = gr.Gallery(label="Сегменты", columns=8, height=260)
                        out_names = gr.State([])
                        out_dd = []
                        for _row in range(MAX_SEGS // 4):
                            with gr.Row():
                                for _ in range(4):
                                    out_dd.append(gr.Dropdown(list(OF.SLOTS), visible=False, label=""))
                        out_btn = gr.Button("Перенести сет", variant="primary")
                        out_log = gr.Textbox(label="Ход работы", lines=8, interactive=False)
                        out_view = gr.Gallery(label="Результат на базовом теле", columns=4, height=420)
                    with gr.Tab("Подогнать одну вещь"):
                        with gr.Row():
                            with gr.Column(scale=1):
                                gr.Markdown("Сажает отдельно сгенерированную вещь на тело и привязывает к его скелету. "
                                            "Для вещей, сделанных под другую фигуру, лучше «Перенести сет».")
                                with gr.Row():
                                    fit_body = gr.Dropdown(_parts_bodies(), label="Тело (*_parts.glb)", scale=4)
                                    fit_refresh = gr.Button("Обновить", scale=1)
                                with gr.Row():
                                    fit_asset = gr.Dropdown(_export_assets(), label="Вещь из готовых моделей", scale=3)
                                    fit_slot = gr.Dropdown(list(SLOT_LABELS), value="Нагрудник", label="Слот",
                                                           scale=2)
                                fit_upload = gr.File(label="…или загрузите GLB вещи", file_types=[".glb"],
                                                     type="filepath")
                                fit_mode = gr.Radio(list(FIT_MODES), value=list(FIT_MODES)[0], label="Посадка")
                                with gr.Accordion("Тонкая настройка", open=False):
                                    fit_scale = gr.Slider(50, 150, value=100, step=1, label="Масштаб, %")
                                    fit_hide = gr.Checkbox(label="Прятать часть тела под вещью целиком "
                                                                 "(только для закрытой брони)", value=False)
                                    fit_length = gr.Dropdown(list(LENGTH_LABELS), value="по умолчанию для слота",
                                                             label="Длина (нагрудник: от воротника до…)")
                                    fit_gap = gr.Slider(0, 20, value=6, step=1, label="Зазор до тела, мм")
                                    fit_shrink = gr.Slider(0, 100, value=0, step=5,
                                                           label="Усадка к телу, % (подтягивает повисшие участки, форма деталей сохраняется)")
                                    with gr.Row():
                                        fit_w = gr.Slider(70, 140, value=100, step=1, label="Ширина, %")
                                        fit_h = gr.Slider(60, 160, value=100, step=1, label="Длина, %")
                                    with gr.Row():
                                        fit_d = gr.Slider(70, 150, value=100, step=1, label="Глубина, %")
                                        fit_up = gr.Slider(-10, 10, value=0, step=0.5, label="Вверх/вниз, см")
                                fit_btn = gr.Button("Подогнать", variant="primary")
                                fit_log = gr.Textbox(label="Ход работы", lines=4, interactive=False)
                            with gr.Column(scale=1):
                                fit_m3d = gr.Model3D(label="Модель", height=420, clear_color=(0.9, 0.9, 0.9, 1))
                                fit_view = gr.Gallery(label="Как сидит (спереди и сбоку)", columns=2, height=300)

            # ---------------------------------------------------------------- surfaces
            with gr.Tab("Поверхности (земля, пол, стены)", id="surf"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("Бесшовный материал для ландшафта, полов, дорог и стен: текстура вида сверху, "
                                    "карты рельефа и готовый материал Godot (`.tres`). Стиль берётся из карточки "
                                    "стиля во вкладке «Референс».")
                        surf_desc = gr.Textbox(label="Поверхность", lines=2,
                                               placeholder="например: старая булыжная дорога, мох и грязь между камнями")
                        surf_own = gr.File(label="…или своя картинка (вид сверху)", file_types=["image"],
                                           type="filepath")
                        surf_provider = gr.Radio(list(REF_PROVIDERS), value=list(REF_PROVIDERS)[0],
                                                 label="Чем генерировать")
                        with gr.Row():
                            surf_tile = gr.Slider(0.5, 10, value=4, step=0.5, label="Плитка повторяется каждые, м")
                            surf_strength = gr.Slider(0.2, 3, value=1.0, step=0.1, label="Сила рельефа")
                        with gr.Row():
                            surf_size = gr.Dropdown([512, 1024, 2048], value=1024, label="Размер текстур")
                            surf_name = gr.Textbox(label="Имя (папка в materials/)")
                        surf_btn = gr.Button("Сделать материал", variant="primary")
                        surf_log = gr.Textbox(label="Ход работы", lines=6, interactive=False)
                    with gr.Column(scale=1):
                        surf_gallery = gr.Gallery(label="Результат", columns=1, height=520)

            # ---------------------------------------------------------------- effects
            with gr.Tab("Эффекты (частицы)", id="fx"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("**1. Анимированный лист** для частиц Godot: взрыв, дым, огонь (зациклен), "
                                    "магическая вспышка, искра. Рисуется программно, за секунды.")
                        fx_kind = gr.Dropdown(list(FX_KINDS), value=list(FX_KINDS)[0], label="Что нарисовать")
                        with gr.Row():
                            fx_color = gr.ColorPicker(value="#ffffff", label="Оттенок")
                            fx_grid = gr.Dropdown([4, 8], value=8, label="Сетка кадров")
                            fx_size = gr.Dropdown([64, 128, 256], value=128, label="Размер кадра, px")
                        with gr.Row():
                            fx_seed = gr.Number(value=1, precision=0, label="Вариант (seed)")
                            fx_speed = gr.Slider(0.5, 2.0, value=1.0, step=0.1, label="Скорость")
                            fx_name = gr.Textbox(label="Имя файла (пусто — по виду)")
                        fx_flip_btn = gr.Button("Сделать лист", variant="primary")
                        gr.Markdown("**2. Светящийся спрайт по описанию** (руны, символы, круг призыва). Чёрный фон "
                                    "становится прозрачностью.")
                        fx_provider = gr.Radio(list(REF_PROVIDERS), value=list(REF_PROVIDERS)[0],
                                               label="Чем генерировать")
                        fx_desc = gr.Textbox(label="Описание", lines=2, placeholder="круг призыва с рунами, голубое свечение")
                        fx_sname = gr.Textbox(label="Имя файла (magic_circle — для стандартной сцены)")
                        fx_sprite_btn = gr.Button("Сгенерировать спрайт")
                        gr.Markdown("**3. Сцены Godot** из листов: explosion, fire, smoke, magic_circle, hit_sparks "
                                    "(папка `sf3d_fx`, копируется в `res://sf3d_fx/`).")
                        fx_scene_btn = gr.Button("Собрать сцены Godot")
                        fx_log = gr.Textbox(label="Результат", lines=5, interactive=False)
                    with gr.Column(scale=1):
                        fx_gallery = gr.Gallery(label="Предпросмотр", columns=1, height=560)

            # ---------------------------------------------------------------- modular kits
            with gr.Tab("Модульные наборы (подземелье)", id="kit"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("Набор деталей, которые стыкуются по сетке: пол, потолок, стены (глухая, с дверью, "
                                    "с аркой, с окном), углы, колонна, лестница и дверь. Блоки, арка и ступени "
                                    "строятся процедурно, поэтому стыки сходятся точно. Материалы берутся из "
                                    "вкладки «Поверхности».")
                        gr.Markdown("**1. Детали набора**")
                        with gr.Row():
                            kit_cell = gr.Number(value=4, label="Ячейка, м")
                            kit_height = gr.Number(value=3, label="Высота этажа, м")
                            kit_seed = gr.Number(value=1, precision=0, label="Вариант кладки")
                        _mats = _mat_folders()
                        with gr.Row():
                            kit_wall = gr.Dropdown([KIT_PROC] + _mats, value=KIT_PROC, label="Камень стен")
                            kit_floor = gr.Dropdown(_mats, value="dungeon_floor" if "dungeon_floor" in _mats
                                                    else (_mats[0] if _mats else None), label="Пол и лестница")
                            kit_wood = gr.Dropdown(_mats, value="dungeon_wood" if "dungeon_wood" in _mats
                                                   else (_mats[0] if _mats else None), label="Дерево (дверь, балки)")
                            kit_mats_btn = gr.Button("Обновить список", scale=0)
                        kit_build_btn = gr.Button("Собрать детали", variant="primary")
                        gr.Markdown("**2. План этажа → сцена Godot.** Строки — вид сверху, север вверху. "
                                    "`.` пол · `P` колонна · `D` проём с дверью · `A` арка · `W` пол с окнами в "
                                    "наружных стенах · `^ > v <` лестница (вверх в эту сторону; дальше начинается "
                                    "следующий этаж) · `#` или пробел — ничего. Этажи разделяет строка `---`. "
                                    "Дверь и арка ставятся в клетку, где проход идёт между двумя открытыми соседями.")
                        kit_plan = gr.Textbox(value=_kit_sample(), lines=16, label="План", max_lines=40,
                                              elem_classes=["mono"])
                        kit_ceil = gr.Checkbox(value=True, label="Потолки")
                        kit_scene_btn = gr.Button("Построить сцену")
                        kit_log = gr.Textbox(label="Ход работы", lines=6, interactive=False)
                    with gr.Column(scale=1):
                        kit_gallery = gr.Gallery(label="Результат", columns=1, height=620)

            # ---------------------------------------------------------------- destructibles
            with gr.Tab("Разрушаемые объекты", id="destr"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("Модель (бочка, ящик, ваза, столб) режется на осколки с гранями «изнутри». "
                                    "В Godot получается сцена: цельный объект, который по команде рассыпается "
                                    "на твёрдые тела, с пылью, исчезновением осколков и сигналом `destroyed` "
                                    "для выпадения добычи.")
                        with gr.Row():
                            dst_asset = gr.Dropdown(_export_assets(), label="Готовая модель (категория/имя)", scale=4)
                            dst_refresh_btn = gr.Button("Обновить", scale=1)
                        dst_upload = gr.File(label="…или загрузите GLB", file_types=[".glb"], type="filepath")
                        with gr.Row():
                            dst_chunks = gr.Slider(4, 40, value=14, step=1, label="Осколков")
                            dst_seed = gr.Number(value=1, precision=0, label="Вариант разлома")
                        with gr.Row():
                            dst_auto = gr.Checkbox(value=True, label="Цвет излома по текстуре")
                            dst_color = gr.ColorPicker(value="#6b4a2e", label="…или свой цвет излома")
                        with gr.Row():
                            dst_mass = gr.Number(value=20, label="Масса, кг")
                            dst_health = gr.Number(value=20, label="Прочность")
                            dst_burst = gr.Number(value=3.5, label="Скорость разлёта, м/с")
                        dst_name = gr.Textbox(label="Имя (пусто — как у модели)")
                        dst_btn = gr.Button("Сделать разрушаемым", variant="primary")
                        dst_log = gr.Textbox(label="Ход работы", lines=6, interactive=False)
                    with gr.Column(scale=1):
                        dst_view = gr.Model3D(label="Модель", height=300, clear_color=(0.9, 0.9, 0.9, 1))
                        dst_gallery = gr.Gallery(label="Проверка в Godot: цел → разрушение", columns=2, height=380)

            # ---------------------------------------------------------------- 4. materials
            with gr.Tab("Материалы"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("**1.** Выберите модель. **2.** «Проанализировать»: текстура делится на цветовые "
                                    "группы с предложенным материалом. **3.** Поправьте, если ошиблась. "
                                    "**4.** «Применить».")
                        with gr.Row():
                            mat_asset = gr.Dropdown(_mat_assets(), label="Модель (категория/имя)", scale=4)
                            mat_refresh_btn = gr.Button("Обновить", scale=1)
                        mat_analyze_btn = gr.Button("Проанализировать")
                        mat_note = gr.Markdown("")
                        mat_dd = [gr.Dropdown(MAT_CHOICES, value=None, visible=False, label=f"Группа {j + 1}")
                                  for j in range(MAX_GROUPS)]
                        mat_apply_btn = gr.Button("Применить материалы", variant="primary")
                        mat_status = gr.Textbox(label="Результат", interactive=False)
                    with gr.Column(scale=1):
                        mat_m3d = gr.Model3D(label="Модель", height=380, clear_color=(0.9, 0.9, 0.9, 1))
                        mat_overlay = gr.Image(label="Группы на текстуре", height=260, interactive=False)
                        mat_gallery = gr.Gallery(label="Превью", columns=4, height=150)

            # ---------------------------------------------------------------- 5. batch
            with gr.Tab("Пакетная обработка"):
                gr.Markdown("Схема папок: `<корень>\\<категория>\\картинка.png` — SF3D; "
                            "`<корень>\\<категория>\\<объект>\\front.png` (+ `back`, `left`, `right`) — Hunyuan3D. "
                            "Готовое пропускается, ошибка в одной задаче не останавливает очередь.")
                with gr.Row():
                    batch_dir = gr.Textbox(label="Корневая папка",
                                           value=cfg.get("input_dir", r"D:\My projects\SF3D\input"), scale=3)
                    batch_cat = gr.Dropdown(labels, value=default_cat, label="Категория по умолчанию", scale=2)
                with gr.Row():
                    batch_over = gr.Checkbox(label="Перезаписать готовое", value=False)
                    batch_prev = gr.Checkbox(label="Превью и иконки", value=True)
                    batch_mat = gr.Checkbox(label="Распознавать материалы", value=False)
                    batch_rig = gr.Checkbox(label="Скелеты для персонажей (в конце)", value=False)
                with gr.Row():
                    scan_btn = gr.Button("Сканировать папку")
                    batch_btn = gr.Button("Запустить пакет", variant="primary")
                batch_info = gr.Textbox(label="Найдено", interactive=False)
                batch_jobs = gr.Dataframe(headers=["имя", "категория", "движок", "источник", "статус"],
                                          label="Очередь", interactive=False, wrap=True)
                with gr.Row():
                    batch_log = gr.Textbox(label="Журнал", lines=8, interactive=False, scale=1)
                    batch_view = gr.Model3D(label="Последняя модель", height=320, clear_color=(0.9, 0.9, 0.9, 1),
                                            scale=1)
                batch_table = gr.Dataframe(headers=["имя", "категория", "граней", "размер (м)", "секунд", "файл"],
                                           label="Готово", interactive=False, wrap=True)
                batch_gallery = gr.Gallery(label="Превью", columns=6, height=150)

            # ---------------------------------------------------------------- 6. settings
            with gr.Tab("Настройки и видеопамять"):
                with gr.Row():
                    with gr.Column(scale=1):
                        gr.Markdown("**Видеопамять.** Перед генерацией закройте программы, нагружающие видеокарту: "
                                    "SF3D нужно около 6,2 ГБ, Hunyuan3D при покраске до 7,5 ГБ, риггинг около 3,5 ГБ.")
                        gpu_btn = gr.Button("Показать занятость видеопамяти")
                        gpu_md = gr.Markdown("")
                        with gr.Row():
                            gpu_proc = gr.Dropdown([], label="Программа, которую можно закрыть", scale=3)
                            gpu_force = gr.Checkbox(label="Принудительно (несохранённое пропадёт)", scale=2)
                        gpu_close = gr.Button("Закрыть выбранную программу")
                        gpu_msg = gr.Markdown("")
                        with gr.Row():
                            unload_btn = gr.Button("Выгрузить SF3D из видеопамяти")
                            vram_btn = gr.Button("Коротко: сколько занято")
                    with gr.Column(scale=1):
                        export_dir = gr.Textbox(label="Папка экспорта (потом укажите папку assets проекта Godot)",
                                                value=cfg["export_dir"])
                        with gr.Row():
                            save_btn = gr.Button("Сохранить папку")
                            open_btn = gr.Button("Открыть папку")
                        info = gr.Textbox(label="Статус", interactive=False)
                        gr.Markdown("**OpenRouter** (для референсов по ключу). Ключ хранится только в "
                                    "`tool/config.json` на этом компьютере.")
                        or_key = gr.Textbox(label="Ключ OpenRouter", type="password",
                                            value=("•" * 12) if cfg.get("openrouter_key") else "")
                        with gr.Row():
                            or_img = gr.Textbox(label="Модель для картинок",
                                                value=cfg.get("openrouter_image_model", "google/gemini-2.5-flash-image"))
                            or_txt = gr.Textbox(label="Модель для описания стиля",
                                                value=cfg.get("openrouter_text_model", "google/gemini-2.5-flash"))
                        or_save = gr.Button("Сохранить настройки OpenRouter")
                        or_note = gr.Markdown("")

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
            return gr.update(choices=_parts_bodies()), gr.update(choices=_export_assets())

        fit_refresh.click(refresh_bodies, None, [fit_body, fit_asset])
        out_refresh.click(lambda: gr.update(choices=_parts_bodies()), None, out_body)
        fit_body.change(lambda p: p or None, fit_body, fit_m3d, show_progress="hidden")
        fit_asset.change(preview_pick, [fit_upload, fit_asset], fit_m3d, show_progress="hidden")
        fit_upload.change(preview_pick, [fit_upload, fit_asset], fit_m3d, show_progress="hidden")
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
                           [engine, files, v_front, v_back, v_left, v_right, category, name, main_tabs])
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
        unload_btn.click(unload_model, None, info)
        vram_btn.click(vram_text, None, info)
    return ui


if __name__ == "__main__":
    ui = build()
    ui.queue(default_concurrency_limit=1).launch(
        server_name="127.0.0.1", server_port=PORT, inbrowser=False, show_api=False,
        allowed_paths=[T.load_config()["export_dir"], T.load_config()["work_dir"]],
    )
