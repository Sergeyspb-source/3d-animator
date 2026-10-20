"""Texture a Hunyuan3D shape with Hunyuan3D-Paint, in 8 GB of VRAM (CPU offload).

    python hy_texture_mv.py shape.glb reference.png out.glb [--turbo] [--tex 2048]

The shape should already be decimated (~40-60k faces); the reference image is the
front view (RGBA or RGB, the background is removed if there is no alpha).
"""
import argparse
import os
import time

os.environ.setdefault("HY3DGEN_MODELS", r"D:\conda\hy3dgen")  # keep caches off C:

import torch  # noqa: E402  (must be imported before the native extensions)
import trimesh  # noqa: E402
from PIL import Image  # noqa: E402

ap = argparse.ArgumentParser()
ap.add_argument("shape")
ap.add_argument("reference")
ap.add_argument("out")
ap.add_argument("--turbo", action="store_true", help="faster, slightly lower quality paint model")
ap.add_argument("--tex", type=int, default=2048, help="texture size")
ap.add_argument("--render", type=int, default=2048, help="render size for projection")
ap.add_argument("--no-offload", action="store_true")
a = ap.parse_args()

from hy3dgen.texgen import Hunyuan3DPaintPipeline  # noqa: E402

img = Image.open(a.reference).convert("RGBA")
if img.getextrema()[3][0] == 255:
    from hy3dgen.rembg import BackgroundRemover
    img = BackgroundRemover()(img.convert("RGB"))

mesh = trimesh.load(a.shape, force="mesh")
print(f"shape: {len(mesh.vertices)} verts / {len(mesh.faces)} faces")

sub = "hunyuan3d-paint-v2-0-turbo" if a.turbo else "hunyuan3d-paint-v2-0"
t0 = time.time()
pipe = Hunyuan3DPaintPipeline.from_pretrained("tencent/Hunyuan3D-2", subfolder=sub)
pipe.config.texture_size = a.tex
pipe.config.render_size = a.render
pipe.render.set_default_render_resolution(a.render) if hasattr(pipe.render, "set_default_render_resolution") else None
pipe.render.set_default_texture_resolution(a.tex) if hasattr(pipe.render, "set_default_texture_resolution") else None
if not a.no_offload:
    # The multiview pipeline hard-codes 'cuda' and reads weights inside its unet, so full CPU offload
    # breaks it (device mismatch). Offload only the delight model; multiview (~4 GB fp16) stays on GPU.
    pipe.models["delight_model"].pipeline.enable_model_cpu_offload()
print(f"models loaded in {time.time() - t0:.0f}s; VRAM now {torch.cuda.memory_allocated() / 1024**2:.0f} MB")

torch.cuda.reset_peak_memory_stats()
t0 = time.time()
out = pipe(mesh, image=img)
print(f"texture: {time.time() - t0:.0f}s, peak VRAM {torch.cuda.max_memory_allocated() / 1024**2:.0f} MB")
out.export(a.out)
print("saved", a.out)
