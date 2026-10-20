"""Run a whole folder through the pipeline without the GUI (e.g. overnight).

    sf3d-batch.bat [folder] [--category prop] [--force] [--no-preview] [--scan]

Folder layout: see scan_batch() in sf3d_ui.py (<folder>/<category>/<image> for SF3D,
<folder>/<category>/<asset>/front.png [back/left/right.png] for Hunyuan3D).
"""
import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import sf3d_ui as U  # noqa: E402
import sf3d_tool as T  # noqa: E402

cfg = T.load_config()
ap = argparse.ArgumentParser()
ap.add_argument("folder", nargs="?", default=cfg.get("input_dir"))
ap.add_argument("--category", default="prop", choices=list(cfg["categories"]), help="for items outside category folders")
ap.add_argument("--force", action="store_true", help="redo already exported assets")
ap.add_argument("--no-preview", action="store_true")
ap.add_argument("--scan", action="store_true", help="only list what would run")
ap.add_argument("--materials", action="store_true", help="recognise materials and write roughness/metallic maps")
ap.add_argument("--rig", action="store_true", help="auto-rig characters in a last phase (UniRig)")
ap.add_argument("--rig-tries", type=int, default=3, help="skeleton attempts per character (1-6)")
ap.add_argument("--rig-names", choices=["mixamo", "godot"], default="mixamo")
a = ap.parse_args()

label = U.CATEGORY_LABELS[a.category]
if a.scan:
    for row in U.batch_table(U.scan_batch(a.folder, a.category)):
        print(" | ".join(map(str, row)))
    sys.exit(0)

printed = 0
final_table = []
rig_label = next(k for k, v in U.RIG_NAMINGS.items() if v == a.rig_names)
for log, table, glb, prev in U.batch_run(a.folder, label, a.force, not a.no_preview, a.materials,
                                         a.rig, rig_label, a.rig_tries):
    lines = log.splitlines()
    # print only lines that are new; the last few lines of a running job are rewritten, so skip those
    stable = lines if not lines or not lines[-1].startswith("   ") else [x for x in lines if not x.startswith("   ")]
    for x in stable[printed:]:
        print(x, flush=True)
    printed = max(printed, len(stable))
    final_table = table
print(f"Exported this run: {len(final_table)}")
