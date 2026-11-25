"""The landmark skeleton's build options (kept in work_dir) and the face-parts sets to build with: what the web UI
(tool/web/character.py, face.py) still reads from the former Gradio panel."""
import json
from pathlib import Path

from i18n import t as _t


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
