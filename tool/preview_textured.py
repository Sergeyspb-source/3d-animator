"""Quick 4-view preview PNG of a textured GLB (no Blender needed).

    python preview_textured.py model.glb preview.png
Face colour = texture sampled at each triangle's UV centroid; flat shaded, so it is
only a rough check, not a render.
"""
import sys

import matplotlib
import numpy as np
import trimesh

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.collections import PolyCollection  # noqa: E402

glb, out = sys.argv[1], sys.argv[2]
scene = trimesh.load(glb, force="scene")
mesh = trimesh.util.concatenate(list(scene.dump()))
mat = mesh.visual.material
tex_img = getattr(mat, "baseColorTexture", None) or getattr(mat, "image", None)
v, f, n = mesh.vertices, mesh.faces, mesh.face_normals
if tex_img is not None and getattr(mesh.visual, "uv", None) is not None:
    tex = np.asarray(tex_img.convert("RGB"))
    H, W = tex.shape[:2]
    uv = mesh.visual.uv[f].mean(axis=1)
    col = tex[np.clip(((1 - uv[:, 1]) * (H - 1)).astype(int), 0, H - 1),
              np.clip((uv[:, 0] * (W - 1)).astype(int), 0, W - 1)] / 255.0
else:
    col = np.tile([0.8, 0.75, 0.7], (len(f), 1))

views = {"+Z": (0, 0), "-Z": (180, 0), "+X": (90, 0), "3/4": (35, 25)}
fig, axes = plt.subplots(1, 4, figsize=(18, 6), facecolor="#d9d9d9")
for ax, (name, (az, el)) in zip(axes, views.items()):
    a, e = np.radians(az), np.radians(el)
    Ry = np.array([[np.cos(a), 0, np.sin(a)], [0, 1, 0], [-np.sin(a), 0, np.cos(a)]])
    Rx = np.array([[1, 0, 0], [0, np.cos(e), -np.sin(e)], [0, np.sin(e), np.cos(e)]])
    R = Rx @ Ry
    pv, pn = v @ R.T, n @ R.T
    tri = pv[f]
    vis = np.where(pn[:, 2] > 0)[0]
    vis = vis[np.argsort(tri[vis][:, :, 2].mean(axis=1))]
    shade = (0.7 + 0.3 * np.clip(pn[vis, 2], 0, 1))[:, None]
    ax.add_collection(PolyCollection(tri[vis][:, :, :2], facecolors=np.clip(col[vis] * shade, 0, 1), edgecolors="none"))
    ax.set_xlim(pv[:, 0].min() - 0.05, pv[:, 0].max() + 0.05)
    ax.set_ylim(pv[:, 1].min() - 0.05, pv[:, 1].max() + 0.05)
    ax.set_aspect("equal"); ax.axis("off"); ax.set_title(name)
plt.tight_layout()
plt.savefig(out, dpi=70)
print("saved", out)
