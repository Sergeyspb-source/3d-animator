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
    out = {"hips": p + cfg["hips"], "neck": p + cfg["neck"], "head": p + cfg["head"], "jaw": p + "Jaw"}
    for k, jid in enumerate(["spine", "spine1", "spine2"]):
        out[jid] = p + cfg["spine"][k]
    for s, side in (("L", "Left"), ("R", "Right")):
        for jid, role in (("shoulder", "shoulder"), ("arm", "arm"), ("forearm", "forearm"), ("hand", "hand"),
                          ("upleg", "upleg"), ("leg", "leg"), ("foot", "foot"), ("toe", "toe")):
            out[f"{jid}_{s}"] = p + cfg[role].replace("{S}", side)
        out[f"heel_{s}"] = p + f"{side}Heel"   # helper, no weights
        out[f"eye_{s}"] = p + f"{side}Eye"
        for f in ("thumb", "index", "middle", "ring", "pinky"):
            F = f.capitalize()
            if naming == "mixamo":   # LeftHandIndex1..3, plus the Mixamo end bone 4 for reading FBX rigs
                for k in range(1, 5):
                    out[f"{f}{k}_{s}"] = p + f"{side}Hand{F}{k}"
            else:                    # Godot humanoid profile
                parts = ["Metacarpal", "Proximal", "Distal"] if f == "thumb" else ["Proximal", "Intermediate", "Distal"]
                for k, part in enumerate(parts, 1):
                    out[f"{f}{k}_{s}"] = p + f"{side}{F}{part}"
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


def editor_page(src: Path, state: dict | None, rigged: Path | None = None, mode: str | None = None):
    """rigged: built GLB for the pose mode (fetched by the page through Gradio's /file= route, so it must lie in
    an allowed path such as export_dir); mode='pose' opens the page straight in the pose mode."""
    page = EDITOR.read_text(encoding="utf-8")
    data = {"state": state, "target": TARGET_ID, "source": str(src), "mode": mode,
            "rigged": Path(rigged).resolve().as_posix() if rigged and Path(rigged).exists() else None,
            "rigged_v": int(Path(rigged).stat().st_mtime) if rigged and Path(rigged).exists() else 0,
            "names": {"mixamo": bone_names("mixamo"), "godot": bone_names("godot")},
            "clips": face_clips(rigged) if rigged and Path(rigged).exists() else []}
    # </script> inside JSON would end the tag early
    return (page.replace("@@DATA@@", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
                .replace("@@GLB@@", base64.b64encode(src.read_bytes()).decode("ascii")))


def viewable(src: Path, cfg) -> tuple[Path, dict]:
    """Copy a rigged GLB, or convert a rigged FBX with Blender, into work_dir/rig_view so the browser viewer can
    fetch it through Gradio's /file= route (work_dir is an allowed path). Returns (glb, summary)."""
    out_dir = Path(cfg["work_dir"]) / "rig_view"
    out_dir.mkdir(parents=True, exist_ok=True)
    dst = out_dir / (re.sub(r"[^\w.-]+", "_", src.stem) + "_" + datetime.now().strftime("%H%M%S") + ".glb")
    if src.suffix.lower() == ".glb":
        dst.write_bytes(src.read_bytes())
        return dst, {}
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_fbx_to_glb.py"), "--", str(src), str(dst)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    line = next((x for x in r.stdout.splitlines() if x.startswith("FBX2GLB_OK")), None)
    if line is None:
        raise RuntimeError("Blender не прочитал FBX:\n" + (r.stdout + r.stderr)[-1500:])
    info = json.loads(line.split(" ", 1)[1])
    if not info["meshes"]:
        raise RuntimeError("В FBX только скелет и анимация, модели нет. В Mixamo скачайте с параметром With Skin.")
    return dst, info


def face_clips(rigged: Path):
    """Lip-sync clips next to a built model: <stem>.face.json with its audio <stem>.(mp3|wav|ogg)."""
    out = []
    for f in sorted(Path(rigged).parent.glob("*.face.json")):
        stem = f.name[:-len(".face.json")]
        audio = next((f.with_name(stem + e) for e in (".mp3", ".wav", ".ogg") if f.with_name(stem + e).exists()), None)
        if audio:
            out.append({"name": stem, "clip": f.resolve().as_posix(), "audio": audio.resolve().as_posix()})
    return out


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


def build(src: Path, landmarks: dict, naming, cfg, weld=True, mouth=True):
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
    extra = []
    if report.get("heel_bones"):
        extra.append(f"+{report['heel_bones']} кости пяток без весов (для IK стопы)")
    if report.get("prebend"):
        extra.append("почти прямые локти/колени чуть согнуты для IK: " + ", ".join(report["prebend"]))
    yield (f"Скелет: {report['bones'] + report.get('heel_bones', 0)} костей, вершин {report['vertices']}. "
           + ("; ".join(extra) + ". " if extra else "")
           + (f"Автовеса Blender не справились с {fb} вершинами — им веса даны по ближайшим костям."
              if fb else "Автовеса Blender сработали на всех частях."))
    model = work / "model.glb"
    if weld:
        from rigging import weld_seams
        yield "Сшиваю стыки между частями модели…"
        st = weld_seams(model, work / "model_seams.glb", blender, eps=0.0005 * max(report.get("height", 1.0), 1e-6))
        if st:
            model = work / "model_seams.glb"
            yield f"Стыков найдено: {st['clusters']}, веса на них выровнены."
        else:
            yield "Стыков между частями нет."
    face = landmarks.get("face") or {}
    images_extra = []
    if mouth and all(face.get(k) for k in ("mouth_c", "mouth_corner_L", "mouth_corner_R")):
        yield "Кладу рот для речи: пластина с ключами jawOpen, mouthSmile, mouthFunnel и др. (для липсинка)…"
        names = bone_names(naming)
        mj = {"source": str(model), "out": str(work / "model_mouth.glb"), "mouth_c": face["mouth_c"],
              "corner_L": face["mouth_corner_L"], "corner_R": face["mouth_corner_R"], "head_bone": names["head"],
              "jaw_bone": names["jaw"] if "jaw" in landmarks["joints"] else "", "report": str(work / "mouth_report.json"),
              "preview": str(work / "mouth.png")}
        (work / "mouth_job.json").write_text(json.dumps(mj, ensure_ascii=False), encoding="utf-8")
        r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_mouth_plate.py"), "--",
                            str(work / "mouth_job.json")], capture_output=True, text=True, encoding="utf-8",
                           errors="replace", timeout=900, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
        line = next((x for x in r.stdout.splitlines() if x.startswith("MOUTH_OK")), None)
        if line:
            model = work / "model_mouth.glb"
            mr = json.loads(line.split(" ", 1)[1])
            images_extra = mr.get("previews", [])
            yield f"Рот для речи готов: {len(mr['keys'])} ключей формы ({', '.join(mr['keys'])})."
        else:
            fail = next((x for x in r.stdout.splitlines() if x.startswith("MOUTH_FAIL")), (r.stdout + r.stderr)[-600:])
            yield "Рот для речи не получился, модель сохранена без него: " + fail
    final.parent.mkdir(parents=True, exist_ok=True)
    final.write_bytes(model.read_bytes())
    saved.write_text(json.dumps({**landmarks, "source": str(src), "naming": naming}, ensure_ascii=False, indent=1),
                     encoding="utf-8")
    yield f"Готово: {final}\nРазметка сохранена: {saved.name} (откроется в редакторе в следующий раз)."
    yield {"glb": str(final), "landmarks": str(saved), "work": str(work),
           "images": [str(work / n) for n in ("rest.png", "pose_front.png", "pose_side.png", "hand_fist.png", "face_jaw.png")
                      if (work / n).exists()] + [p for p in images_extra if Path(p).exists()]}
