"""Animation library for rigged humanoids: Blender adds procedural clips (blender_humanoid_anim.py) and exports a GLB;
preview sheets (6 side-view frames per clip) are stitched here.

    animate(blender, src_glb, dst_glb, clips, preview_dir)  -> info dict (clips, speeds ...)
    sheets(preview_dir, clips, out_dir)                      -> [(png path, caption)]
"""
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

CLIPS = {
    "idle_loop": "Покой (idle): дыхание, лёгкие покачивания",
    "walk_loop": "Ходьба (цикл)",
    "run_loop": "Бег (цикл)",
    "jump": "Прыжок: присед, толчок, воздух, приземление (с подъёмом корпуса)",
    "fall_loop": "Падение (цикл, поза в воздухе)",
    "land": "Приземление",
    "attack_slash": "Удар по диагонали (правая рука)",
    "attack_overhead": "Удар сверху двумя руками",
    "cast": "Заклинание (руки вперёд, свечение руками)",
    "block_loop": "Блок (цикл)",
    "hit": "Получение удара",
    "death": "Смерть (падает на спину и остаётся лежать)",
}


def animate(blender, src, dst, clips=None, preview_dir=None, fps=30, shield=False, twohand=False, aim=False, tilt=None,
            blade=None):
    src, dst = Path(src), Path(dst)
    dst.unlink(missing_ok=True)       # a failed run must not leave an old result looking like a new one
    args = [str(src), str(dst), f"fps={fps}"]
    if shield:
        args.append("shield=1")
    if twohand:
        args.append("twohand=1")
    if aim:
        args.append("aim=1")
    if tilt is not None:
        args.append(f"sword_tilt={tilt}")
    if blade:   # "fingers": the sword across the palm by the finger bones (see blender_humanoid_anim.py)
        args.append(f"blade={blade}")
    if clips:
        args.append("clips=" + ",".join(clips))
    if preview_dir:
        Path(preview_dir).mkdir(parents=True, exist_ok=True)
        args.append(f"preview={preview_dir}")
    r = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_humanoid_anim.py"), "--", *args],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=1800,
                       creationflags=NOFLAGS)
    out = r.stdout + r.stderr
    if not dst.exists():
        err = [x for x in out.splitlines() if "ANIM_ERROR" in x or "Error" in x]
        raise RuntimeError("не удалось добавить анимации: " + (err[-1] if err else out[-400:]))
    return json.loads(Path(str(dst) + ".json").read_text(encoding="utf-8"))


def sheets(preview_dir, clips, out_dir, per_sheet=4):
    from PIL import Image
    preview_dir, out_dir = Path(preview_dir), Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    res = []
    clips = [c for c in clips if (preview_dir / f"{c}_0.png").exists()]
    for s in range(0, len(clips), per_sheet):
        group = clips[s:s + per_sheet]
        rows = []
        for c in group:
            ims = [Image.open(preview_dir / f"{c}_{j}.png").convert("RGB") for j in range(6)]
            w, h = ims[0].size
            row = Image.new("RGB", (w * 3, h // 2))
            for j, im in enumerate(ims):
                row.paste(im.resize((w // 2, h // 2)), (j * w // 2, 0))
            rows.append(row)
        sheet = Image.new("RGB", (rows[0].width, rows[0].height * len(rows)), (24, 26, 34))
        for i, r in enumerate(rows):
            sheet.paste(r, (0, i * r.height))
        p = out_dir / f"sheet_{s // per_sheet + 1}.png"
        sheet.save(p)
        res.append((str(p), ", ".join(c.replace("_loop", "") for c in group) + " (сверху вниз)"))
    return res
