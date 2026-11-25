"""The shared procedural eyes, teeth and tongue (tool/blender_face_parts.py): the live preview and the saved set
(the web UI: Character -> Face, tool/web/face.py)."""
import hashlib
import json
import re
import shutil
import subprocess
from pathlib import Path

from i18n import t as _t

ROOT = Path(__file__).resolve().parent


def _rgb(hex_or_rgb):
    """Gradio colour (#rrggbb or rgba(...)) -> [r, g, b] 0..1."""
    s = str(hex_or_rgb or "").strip()
    if s.startswith("#") and len(s) >= 7:
        return [int(s[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    m = re.findall(r"[\d.]+", s)
    return [float(x) / 255 for x in m[:3]] if len(m) >= 3 else [0.5, 0.5, 0.5]


def _job(seed, iris, pupil, slit, sclera_yel, veins, per_side, missing, missing_rand, yellow, crooked, fangs, tongue_col,
         eye_style, iris_size, t_height, t_volume, canines):
    white, yel = [0.93, 0.91, 0.87], [0.95, 0.86, 0.55]
    sclera = [w + (y - w) * float(sclera_yel) for w, y in zip(white, yel)]
    return {"seed": int(seed or 0), "preview_glb": True,
            "eye": {"iris": _rgb(iris), "pupil": float(pupil), "slit": bool(slit), "sclera": sclera, "veins": float(veins),
                    "style": "anime" if eye_style == _t("face.anime") else "real", **({"iris_size": float(iris_size)} if iris_size else {})},
            "teeth": {"per_side": int(per_side), "missing": missing or "", "missing_random": float(missing_rand),
                      "yellow": float(yellow), "crooked": float(crooked), "fangs": float(fangs),
                      "height": float(t_height), "volume": float(t_volume), "canines": bool(canines)},
            "tongue": {"colour": _rgb(tongue_col)}}


def _cache_dir(cfg, job):
    """The live view's folder for these settings: a set already made is shown at once, not rebuilt."""
    key = hashlib.sha1(json.dumps(job, sort_keys=True).encode()).hexdigest()[:16]
    return Path(cfg["work_dir"]) / "face_parts_preview" / key


def _prune(root, keep=40):
    dirs = sorted((d for d in root.iterdir() if d.is_dir()), key=lambda d: d.stat().st_mtime, reverse=True)
    for d in dirs[keep:]:
        shutil.rmtree(d, ignore_errors=True)


def cached_preview(cfg, *a):
    """(picture, 3D) of an already made live view, or (None, None)."""
    out = _cache_dir(cfg, _job(*a))
    return ((str(out / "preview.png"), str(out / "preview.glb"))
            if (out / "preview.png").exists() and (out / "preview.glb").exists() else (None, None))


def _run(cfg, job, out):
    """Blender in the background; yields "glb" once the 3D is written, then ("ok", info) or ("fail", log)."""
    out.mkdir(parents=True, exist_ok=True)
    (out / "job.json").write_text(json.dumps({"out_dir": str(out), **job}, indent=1), encoding="utf-8")
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    p = subprocess.Popen([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_face_parts.py"), "--", str(out / "job.json")],
                         stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, encoding="utf-8", errors="replace",
                         creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    log = []
    for x in p.stdout:
        log.append(x)
        if x.startswith("FACE_PARTS_GLB"):
            yield "glb", None
        elif x.startswith("FACE_PARTS_OK"):
            p.wait()
            yield "ok", json.loads(x.split(" ", 1)[1])
            return
    p.wait()
    yield "fail", "".join(log)[-1500:]


def generate(cfg, name, iris, pupil, slit, sclera_yel, veins, per_side, missing, missing_rand, yellow, crooked, fangs,
             tongue_col, seed, eye_style=_t("face.realistic"), iris_size=0, t_height=1.0, t_volume=1.0, canines=True):
    """The set saved to export/face_parts/<name>."""
    name = re.sub(r"[^\w.-]+", "_", (name or "face_parts").strip()) or "face_parts"
    out = Path(cfg["export_dir"]) / "face_parts" / name
    job = _job(seed, iris, pupil, slit, sclera_yel, veins, per_side, missing, missing_rand, yellow, crooked, fangs, tongue_col,
               eye_style, iris_size, t_height, t_volume, canines)
    for kind, info in _run(cfg, job, out):
        if kind == "fail":
            return _t("face.failed") + info, None, None, None
        if kind == "ok":
            msg = (_t("face.done_eyes_radius_mm_teeth_per_half", out, info['eye_radius'] * 1000, info['teeth_per_side'], ', '.join(info['missing']) or 'нет', ' + случайные' if float(missing_rand) else ''))
            return msg, str(out / "preview.png"), [str(out / f) for f in ("eyes.glb", "teeth.glb", "tongue.glb", "parts.json")], str(out / "preview.glb")


def preview(cfg, *a):
    """The live view while the sliders move (work_dir, cached per settings): the 3D first, then the picture."""
    png, glb = cached_preview(cfg, *a)
    if png:
        yield _t("face.preview_updated"), png, glb
        return
    job = _job(*a)
    out = _cache_dir(cfg, job)
    for kind, info in _run(cfg, job, out):
        if kind == "glb":
            yield _t("face.preview_rendering"), None, str(out / "preview.glb")
        elif kind == "ok":
            yield _t("face.preview_updated"), str(out / "preview.png"), str(out / "preview.glb")
        else:
            shutil.rmtree(out, ignore_errors=True)
            yield _t("face.failed") + info, None, None
    _prune(out.parent)
