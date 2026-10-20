"""Hand-placed landmark rigging (Mixamo-like): the user marks chin, groin, shoulders, elbows, wrists, knees and
ankles on the front view in landmark_editor.html; derived joints (spine, neck, clavicles, hips, toes) are
computed there and stay editable. blender_landmark_rig.py builds the armature with standard humanoid names
(Mixamo or Godot, same tables as rigging.py) and skins the model with Blender heat weights.
"""
from __future__ import annotations

import base64
import json
import re
import subprocess
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent
EDITOR = ROOT / "landmark_editor.html"
TARGET_ID = "sf3d_landmarks_json"   # Gradio textbox the editor writes into

REQUIRED = ["hips", "spine", "spine1", "spine2", "neck", "head", "head_top"] + [
    f"{k}_{s}" for s in "LR" for k in ("shoulder", "arm", "forearm", "hand", "hand_end",
                                       "upleg", "leg", "foot", "toe", "toe_end")]


def bone_names(naming="mixamo"):
    """Editor joint id -> bone name, from the same naming tables as UniRig's rename step."""
    from rigging import NAMINGS
    cfg = NAMINGS[naming]
    p = cfg["prefix"]
    out = {"hips": p + cfg["hips"], "neck": p + cfg["neck"], "head": p + cfg["head"]}
    for k, jid in enumerate(["spine", "spine1", "spine2"]):
        out[jid] = p + cfg["spine"][k]
    for s, side in (("L", "Left"), ("R", "Right")):
        for jid, role in (("shoulder", "shoulder"), ("arm", "arm"), ("forearm", "forearm"), ("hand", "hand"),
                          ("upleg", "upleg"), ("leg", "leg"), ("foot", "foot"), ("toe", "toe")):
            out[f"{jid}_{s}"] = p + cfg[role].replace("{S}", side)
    return out


def source_path(upload, asset, export_dir):
    if upload:
        return Path(upload if isinstance(upload, str) else upload.name)
    if asset:
        cat, nm = asset.split("/", 1)
        return Path(export_dir) / cat / nm / f"{nm}.glb"
    return None


def output_paths(src: Path, export_dir) -> tuple[Path, Path]:
    """(<name>_landmarks_rigged.glb, <name>_landmarks.json): next to an exported model, else export/character/<name>/."""
    export_dir = Path(export_dir).resolve()
    stem = re.sub(r"_(landmarks_)?rigged$", "", src.stem)
    folder = src.parent if export_dir in src.resolve().parents else export_dir / "character" / stem
    return folder / f"{stem}_landmarks_rigged.glb", folder / f"{stem}_landmarks.json"


def parse(text):
    """Validate the editor JSON; returns the dict or raises ValueError with a Russian message."""
    try:
        data = json.loads(text or "")
    except json.JSONDecodeError:
        raise ValueError("Разметка пуста или повреждена: откройте редактор и расставьте ориентиры.")
    joints = data.get("joints") or {}
    missing = [j for j in REQUIRED if j not in joints]
    if missing:
        raise ValueError("В разметке нет узлов: " + ", ".join(missing))
    for j in REQUIRED:
        v = joints[j]
        if not (isinstance(v, list) and len(v) == 3 and all(isinstance(x, (int, float)) for x in v)):
            raise ValueError(f"Неверные координаты узла {j}")
    return data


def editor_page(src: Path, state: dict | None):
    page = EDITOR.read_text(encoding="utf-8")
    data = {"state": state, "target": TARGET_ID, "source": str(src)}
    # </script> inside JSON would end the tag early
    return (page.replace("@@DATA@@", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
                .replace("@@GLB@@", base64.b64encode(src.read_bytes()).decode("ascii")))


def initial_state(src: Path, export_dir, textbox: str):
    """Editor start state: unsaved edits for the same model, else the saved landmarks next to the export."""
    try:
        data = json.loads(textbox or "")
        if data.get("source") == str(src) and data.get("joints"):
            return data
    except json.JSONDecodeError:
        pass
    saved = output_paths(src, export_dir)[1]
    if saved.exists():
        try:
            return json.loads(saved.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return None
    return None


def build(src: Path, landmarks: dict, naming, cfg, weld=True):
    """Generator of log lines; the last item is a dict with the result paths."""
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    final, saved = output_paths(src, cfg["export_dir"])
    work = Path(cfg["work_dir"]) / "landmark_rig" / (src.stem + "_" + datetime.now().strftime("%Y%m%d_%H%M%S"))
    work.mkdir(parents=True, exist_ok=True)
    job = {"source": str(src), "out_dir": str(work), "landmarks": landmarks, "names": bone_names(naming)}
    (work / "job.json").write_text(json.dumps(job, ensure_ascii=False, indent=1), encoding="utf-8")
    yield "Blender: строю скелет и считаю веса (около минуты)…"
    with (work / "blender.log").open("w", encoding="utf-8") as log:
        r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_landmark_rig.py"), "--",
                            str(work / "job.json")], stdout=log, stderr=subprocess.STDOUT, timeout=1200,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = (work / "blender.log").read_text(encoding="utf-8", errors="replace")
    line = next((x for x in text.splitlines() if x.startswith("LANDMARK_RIG_OK")), None)
    if r.returncode != 0 or line is None or not (work / "model.glb").exists():
        raise RuntimeError("Blender не построил скелет:\n" + text[-2500:])
    report = json.loads(line.split(" ", 1)[1])
    fb = report["fallback_vertices"]
    yield (f"Скелет: {report['bones']} костей, вершин {report['vertices']}. "
           + (f"Автовеса Blender не справились с {fb} вершинами — им веса даны по ближайшим костям."
              if fb else "Автовеса Blender сработали на всех частях."))
    model = work / "model.glb"
    if weld:
        from rigging import weld_seams
        yield "Сшиваю стыки между частями модели…"
        st = weld_seams(model, work / "model_seams.glb", blender)
        if st:
            model = work / "model_seams.glb"
            yield f"Стыков найдено: {st['clusters']}, веса на них выровнены."
        else:
            yield "Стыков между частями нет."
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(model.read_bytes())
    saved.write_text(json.dumps({**landmarks, "source": str(src), "naming": naming}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    yield f"Готово: {final}\nРазметка сохранена: {saved.name} (откроется в редакторе в следующий раз)."
    yield {"glb": str(final), "landmarks": str(saved), "work": str(work),
           "images": [str(work / n) for n in ("rest.png", "pose_front.png", "pose_side.png") if (work / n).exists()]}
