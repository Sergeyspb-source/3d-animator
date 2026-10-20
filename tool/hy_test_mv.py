"""Shape-only multiview test for Hunyuan3D-2mv (runs in the 'hunyuan' env).

    python hy_test_mv.py out_dir front.png [back.png] [left.png] [right.png]
    python hy_test_mv.py out_dir --views front=a.png back=b.png left=c.png
"""
import sys
import time
from pathlib import Path

import torch
from PIL import Image

out = Path(sys.argv[1])
out.mkdir(parents=True, exist_ok=True)
names = ["front", "back", "left", "right"]
args = sys.argv[2:]
if args and args[0] == "--views":
    views = dict(a.split("=", 1) for a in args[1:])
else:
    views = dict(zip(names, args))

from hy3dgen.rembg import BackgroundRemover  # noqa: E402
from hy3dgen.shapegen import Hunyuan3DDiTFlowMatchingPipeline  # noqa: E402

rembg = BackgroundRemover()
images = {}
for k, p in views.items():
    im = Image.open(p).convert("RGBA")
    # only cut the background if the image is not already transparent
    if im.getextrema()[3][0] == 255:
        im = rembg(im.convert("RGB"))
    images[k] = im
    im.save(out / f"view_{k}.png")
print("views:", list(images))

pipe = Hunyuan3DDiTFlowMatchingPipeline.from_pretrained(
    "tencent/Hunyuan3D-2mv", subfolder="hunyuan3d-dit-v2-mv", variant="fp16"
)
torch.cuda.reset_peak_memory_stats()
t0 = time.time()
mesh = pipe(
    image=images,
    num_inference_steps=50,
    octree_resolution=380,
    num_chunks=20000,
    generator=torch.manual_seed(12345),
    output_type="trimesh",
)[0]
print(f"shape: {time.time() - t0:.1f}s, peak VRAM {torch.cuda.max_memory_allocated() / 1024**2:.0f} MB, "
      f"{len(mesh.vertices)} verts / {len(mesh.faces)} faces")
mesh.export(str(out / "shape.glb"))
print("saved", out / "shape.glb")
