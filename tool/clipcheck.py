"""The clips of a model checked (blender_clip_check.py): into the floor, hovering, the feet's sliding, the loop's seam -
a table for the log, each clip with its verdict. Used by the creatures' «Animations» and the characters' procedural
animations."""
import json
import subprocess
from pathlib import Path

from i18n import t as _t

ROOT = Path(__file__).resolve().parent
# where a number becomes «visible» and «bad»: the floor and sliding against the model's height, the seam against the
# clip's usual step between two frames
SINK = (0.01, 0.03)      # under the floor
HOVER = (0.02, 0.05)     # the standing feet over it
SLIDE = (0.04, 0.10)     # a standing foot off its even way
SEAM = (2.0, 3.5)        # the last frame's jump to the first, in steps


def _grade(v, lim):
    return 0 if v < lim[0] else 1 if v < lim[1] else 2


def check(cfg, glb: Path, work: Path) -> tuple[str, dict]:
    """(a markdown table of the clips, the report). Raises RuntimeError when Blender cannot read the model."""
    glb = Path(glb)
    work = Path(work)
    work.mkdir(parents=True, exist_ok=True)
    out = work / (glb.stem + "_check.json")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_clip_check.py"), "--", str(glb), str(out)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=3600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if "CHECK_OK" not in r.stdout or not out.exists():
        raise RuntimeError((r.stdout + r.stderr)[-1200:])
    rep = json.loads(out.read_text(encoding="utf-8"))
    h = max(rep.get("height_mm", 1), 1)
    marks = [_t("cc.ok"), _t("cc.visible"), _t("cc.bad")]
    rows = [f"| {_t('cc.col_clip')} | {_t('cc.col_sink')} | {_t('cc.col_hover')} | {_t('cc.col_slide')} | {_t('cc.col_seam')} | {_t('cc.col_verdict')} |",
            "|---|---:|---:|---:|---:|---|"]
    worst_all = 0
    for c in rep["clips"]:
        if c["name"].lower() in ("rest pose", "rest_pose", "reset"):
            continue
        g = [_grade(-c["sink"] / h, SINK), _grade(max(c["hover"], 0) / h, HOVER), _grade(c["slide"] / h, SLIDE),
             _grade(c["seam_x"] or 0, SEAM) if c.get("loop") else 0]
        what = [w for w, x in zip((_t("cc.w_sink"), _t("cc.w_hover"), _t("cc.w_slide"), _t("cc.w_seam")), g) if x]
        worst = max(g)
        worst_all = max(worst_all, worst)
        seam = f"{c['seam_x']}×" if c.get("loop") and c.get("seam_x") is not None else "—"
        rows.append(f"| {c['name']} | {c['sink']} | {c['hover']} | {round(100 * c['slide'] / h, 1)} % | {seam} | "
                    f"{marks[worst]}{(': ' + ', '.join(what)) if what else ''} |")
    head = _t("cc.head", glb.name, len(rep["clips"]), rep.get("height_mm"), ", ".join(rep.get("feet", [])))
    return head + "\n\n" + "\n".join(rows) + "\n\n" + _t("cc.legend"), rep
