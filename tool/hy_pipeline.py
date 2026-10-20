"""Hunyuan3D multiview worker: views -> shape -> cleanup/decimate -> texture. Runs in the 'hunyuan' env.

The GUI starts it as a separate process, so all VRAM is returned when it exits.
Progress lines start with '@@ ' so the GUI can show them.

    python hy_pipeline.py --out DIR --front f.png [--back b.png] [--left l.png] [--right r.png]
                          [--faces 50000] [--tex 2048] [--steps 50] [--octree 380] [--seed 12345] [--no-texture]
"""
import argparse
import gc
import json
import os
import sys
import time
import traceback
from pathlib import Path

os.environ.setdefault("HY3DGEN_MODELS", r"D:\conda\hy3dgen")  # keep caches off C:
os.environ.setdefault("HF_HOME", r"D:\conda\hf")
os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("PYTHONWARNINGS", "ignore")

import torch  # noqa: E402  (must come before the native texgen extensions)
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402


def say(msg):
    print(f"@@ {msg}", flush=True)


def free_gpu():
    gc.collect()
    torch.cuda.empty_cache()


ap = argparse.ArgumentParser()
ap.add_argument("--out", required=True)
for v in ("front", "back", "left", "right"):
    ap.add_argument(f"--{v}")
ap.add_argument("--faces", type=int, default=50000)
ap.add_argument("--tex", type=int, default=2048)
ap.add_argument("--steps", type=int, default=50)
ap.add_argument("--octree", type=int, default=380)
ap.add_argument("--seed", type=int, default=12345)
ap.add_argument("--no-texture", action="store_true")
a = ap.parse_args()

out = Path(a.out)
out.mkdir(parents=True, exist_ok=True)
stats = {"views": [], "faces_target": a.faces}
T0 = time.time()

# ---------------------------------------------------------------- views
from hy3dgen.rembg import BackgroundRemover  # noqa: E402

say("подготовка картинок (удаление фона)")
remover = None


def flat_background_cut(im):
    """Plain one-colour background (our generated references): flood the background from the picture's border by
    colour. Returns an RGBA image, or None if the border is not one flat colour (then the neural remover is used).
    The neural remover tends to eat green foliage on grey, this does not."""
    import numpy as np
    from scipy import ndimage

    a = np.asarray(im.convert("RGB")).astype(np.float32)
    border = np.concatenate([a[0], a[-1], a[:, 0], a[:, -1]])
    ref = np.median(border, 0)
    if np.percentile(np.linalg.norm(border - ref, axis=1), 90) > 12:
        return None
    near = np.linalg.norm(a - ref, axis=2) < 26
    lab, _ = ndimage.label(near)
    edge_labels = np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))
    bg = np.isin(lab, edge_labels[edge_labels > 0])
    # gaps seen through a crown or between fence planks: enclosed background patches, if they are big enough
    # not to be a grey highlight on the object itself
    sizes = ndimage.sum(near, lab, index=np.arange(lab.max() + 1))
    big = np.flatnonzero(sizes > 0.0003 * near.size)
    bg |= np.isin(lab, big[big > 0])
    bg = ndimage.binary_opening(bg, iterations=1)
    fg = ~bg
    if fg.mean() < 0.02:
        return None
    alpha = ndimage.gaussian_filter(fg.astype(np.float32), 0.7)
    rgba = np.dstack([a, np.clip(alpha * 255, 0, 255)]).astype(np.uint8)
    return Image.fromarray(rgba, "RGBA")


images = {}
for name in ("front", "back", "left", "right"):
    p = getattr(a, name)
    if not p:
        continue
    im = Image.open(p).convert("RGBA")
    if im.getextrema()[3][0] == 255:  # no transparency yet -> cut the background
        cut = flat_background_cut(im)
        if cut is not None:
            im = cut
            say(f"{name}: фон однотонный, вырезан по цвету")
        else:
            remover = remover or BackgroundRemover()
            im = remover(im.convert("RGB"))
    im.save(out / f"view_{name}.png")
    images[name] = im
    stats["views"].append(name)
if "front" not in images:
    sys.exit("front view is required")
say(f"виды: {', '.join(images)}")

# ---------------------------------------------------------------- shape
from hy3dgen.shapegen import (  # noqa: E402
    DegenerateFaceRemover,
    FaceReducer,
    FloaterRemover,
    Hunyuan3DDiTFlowMatchingPipeline,
)

say("загрузка модели формы")
shape_pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
    "tencent/Hunyuan3D-2mv", subfolder="hunyuan3d-dit-v2-mv", variant="fp16"
)
say(f"генерация формы ({a.steps} шагов)")
torch.cuda.reset_peak_memory_stats()
t = time.time()
mesh = shape_pipe(
    image=images,
    num_inference_steps=a.steps,
    octree_resolution=a.octree,
    num_chunks=20000,
    generator=torch.manual_seed(a.seed),
    output_type="trimesh",
)[0]
stats["shape_seconds"] = round(time.time() - t, 1)
stats["shape_peak_vram_mb"] = round(torch.cuda.max_memory_allocated() / 1024**2)
stats["shape_faces_raw"] = int(len(mesh.faces))
del shape_pipe
free_gpu()
say(f"форма готова за {stats['shape_seconds']} с, {stats['shape_faces_raw']} граней")

say("очистка и упрощение меша")
try:
    mesh = FloaterRemover()(mesh)
    mesh = DegenerateFaceRemover()(mesh)
    mesh = FaceReducer()(mesh, max_facenum=a.faces)
except Exception:  # fall back to plain quadric decimation
    traceback.print_exc()
    import pymeshlab

    ms = pymeshlab.MeshSet()
    ms.add_mesh(pymeshlab.Mesh(vertex_matrix=mesh.vertices, face_matrix=mesh.faces))
    ms.meshing_decimation_quadric_edge_collapse(targetfacenum=a.faces, preservenormal=True, preserveboundary=True)
    m = ms.current_mesh()
    mesh = trimesh.Trimesh(m.vertex_matrix(), m.face_matrix(), process=False)
stats["faces"] = int(len(mesh.faces))
mesh.export(str(out / "shape.glb"))
say(f"меш: {stats['faces']} граней")

if a.no_texture:
    stats["total_seconds"] = round(time.time() - T0, 1)
    (out / "hy_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
    say("ГОТОВО (только форма)")
    sys.exit(0)

# ---------------------------------------------------------------- texture
say("загрузка моделей покраски")
from hy3dgen.texgen import Hunyuan3DPaintPipeline  # noqa: E402

try:
    t = time.time()
    paint = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2", subfolder="hunyuan3d-paint-v2-0")
    paint.config.texture_size = a.tex
    paint.render.set_default_texture_resolution(a.tex)
    # The multiview pipeline hard-codes 'cuda', so only the delight model can be offloaded to RAM.
    paint.models["delight_model"].pipeline.enable_model_cpu_offload()
    say("покраска (несколько минут)")
    torch.cuda.reset_peak_memory_stats()
    textured = paint(mesh, image=images["front"])
    stats["texture_seconds"] = round(time.time() - t, 1)
    stats["texture_peak_vram_mb"] = round(torch.cuda.max_memory_allocated() / 1024**2)
    textured.export(str(out / "textured.glb"))
    say(f"текстура готова за {stats['texture_seconds']} с")
except torch.cuda.OutOfMemoryError:
    stats["texture_error"] = "out of GPU memory"
    say("НЕ ХВАТИЛО ВИДЕОПАМЯТИ при покраске: сохранена форма без текстуры. Закройте другие программы "
        "(Blender, браузер) и повторите, либо уменьшите размер текстуры.")
except Exception as e:  # noqa: BLE001
    traceback.print_exc()
    stats["texture_error"] = f"{type(e).__name__}: {e}"
    say(f"ОШИБКА покраски: {type(e).__name__}: {e}")

stats["total_seconds"] = round(time.time() - T0, 1)
(out / "hy_stats.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
say("ГОТОВО")
