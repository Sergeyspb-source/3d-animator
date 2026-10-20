"""Lip-sync clip for a rigged character: voice + script line -> <model folder>/<stem>.face.json (+ the audio copy).

Uses the game project's own tools instead of copies (paths from config.json, key "lipsync_skills_dir", default the
game's .claude/skills): whisper-transcribe/scripts/transcribe.py for word timings, 3d-animator/scripts/lipsync.py for
the 52 ARKit curves ("face-curves/1"). The curves are then reduced to the shape keys the model really has (read from
the GLB), Left/Right pairs averaged and every opening key scaled by (1 - mouthClose) so p/b/m closures show, exactly
like the game's make_face_clip.py for the beggar. The output is what game/characters/face_curves_player.gd plays.
"""
from __future__ import annotations

import json
import shutil
import struct
import subprocess
from pathlib import Path

PY = r"D:\conda\envs\sf3d\python.exe"
DEFAULT_SKILLS = r"D:\My projects\game-project-godot\.claude\skills"


def shape_keys(glb: Path) -> list[str]:
    """Morph target names of every mesh in a GLB (Blender writes them to mesh.extras.targetNames)."""
    b = Path(glb).read_bytes()
    doc = json.loads(b[20:20 + struct.unpack_from("<I", b, 12)[0]])
    names = []
    for m in doc.get("meshes", []):
        for n in (m.get("extras") or {}).get("targetNames", []):
            if n not in names:
                names.append(n)
    return names


def _run(args, timeout):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.returncode, r.stdout + r.stderr


def reduce_curves(d: dict, keys: list[str]) -> dict:
    """face-curves/1 (52 ARKit) -> compact clip with only the model's keys (game make_face_clip.py rules)."""
    c, n = d["curves"], d["frames"]
    close = c.get("mouthClose", [0.0] * n)
    out = {}
    for k in keys:
        if k in c:
            src = c[k]
        elif k + "Left" in c and k + "Right" in c:
            src = [(a + b) * 0.5 for a, b in zip(c[k + "Left"], c[k + "Right"])]
        else:
            continue
        seal = k.startswith(("jaw", "mouth")) and k != "mouthClose"
        out[k] = [round(max(0.0, min(1.0, v * (1.0 - s if seal else 1.0))), 3) for v, s in zip(src, close)]
    return {"format": "face-curves/1", "id": d["id"], "fps": d["fps"], "lead_in": d["lead_in"], "tail": d["tail"],
            "frames": n, "duration": d["duration"], "source": "SF3D lipsync_link", "curves": out,
            "qa": {k: d["qa"][k] for k in ("ok", "pp_ok", "pp_closures", "max_jaw", "chatter") if k in d.get("qa", {})}}


def make_clip(audio: Path, text: str, lang: str, model_glb: Path, cfg: dict):
    """Generator of log lines; the last item is a dict {clip, audio, keys, qa}."""
    skills = Path(cfg.get("lipsync_skills_dir") or DEFAULT_SKILLS)
    tr, ls = skills / "whisper-transcribe" / "scripts" / "transcribe.py", skills / "3d-animator" / "scripts" / "lipsync.py"
    for f in (tr, ls):
        if not f.exists():
            raise RuntimeError(f"Не найден скрипт липсинка: {f}. Укажите папку в config.json (lipsync_skills_dir).")
    keys = shape_keys(model_glb)
    if not keys:
        raise RuntimeError("В модели нет ключей формы: соберите скелет с размеченным лицом и галочкой «Рот для речи».")
    out_dir = Path(model_glb).parent
    stem = Path(audio).stem
    work = Path(cfg["work_dir"]) / "lipsync" / stem
    work.mkdir(parents=True, exist_ok=True)
    audio_copy = out_dir / Path(audio).name
    if Path(audio).resolve() != audio_copy.resolve():
        shutil.copyfile(audio, audio_copy)
    yield "Whisper: тайминги слов (видеокарта, около 1 ГБ)…"
    code, log = _run([PY, "-I", "-X", "utf8", str(tr), str(audio_copy), "--lang", lang, "--out-dir", str(work)], 900)
    words = work / f"{stem}.words.json"
    if code != 0 or not words.exists():
        raise RuntimeError("Whisper не распознал запись:\n" + log[-1500:])
    heard = (work / f"{stem}.txt").read_text(encoding="utf-8").strip() if (work / f"{stem}.txt").exists() else ""
    yield f"Whisper услышал: «{heard}»"
    yield "Строю кривые лица (фонемы, визем, моргания)…"
    raw = work / f"{stem}.lipsync.json"
    code, log = _run([PY, "-I", "-X", "utf8", str(ls), "--audio", str(audio_copy), "--text", text or heard,
                      "--lang", lang, "--words", str(words), "--out", str(raw)], 900)
    if not raw.exists():
        raise RuntimeError("lipsync.py не построил кривые:\n" + log[-1500:])
    d = json.loads(raw.read_text(encoding="utf-8"))
    clip = reduce_curves(d, keys)
    dst = out_dir / f"{stem}.face.json"
    dst.write_text(json.dumps(clip, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
    qa = clip["qa"]
    used = list(clip["curves"])
    yield (f"Клип: {clip['frames']} кадров @ {clip['fps']} fps, ключи: {', '.join(used)}. "
           f"QA: {'ok' if qa.get('ok') else 'есть замечания'}, смыкания п/б/м {qa.get('pp_closures', '?')}, "
           f"макс. открытие {qa.get('max_jaw', '?')}" + ("" if code == 0 else " (lipsync.py вернул код 1 — см. QA)"))
    yield {"clip": str(dst), "audio": str(audio_copy), "keys": used, "qa": qa}
