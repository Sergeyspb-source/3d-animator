"""Lip-sync clip for a rigged character: voice + script line -> <model folder>/<stem>.face.json (+ the audio copy).

Self-contained: runs the vendored copies in tool/vendor/lipsync (transcribe.py = local Whisper word timings,
lipsync.py = the 52 ARKit curves, "face-curves/1"); config key "lipsync_skills_dir" can point at another copy laid out
as whisper-transcribe/scripts/transcribe.py + 3d-animator/scripts/lipsync.py. The Whisper model is taken from an
existing Hugging Face cache, otherwise downloaded once (~1 GB) into config "hf_home" (default D:/conda/hf). The curves are then reduced to the shape keys the model really has (read from
the GLB), Left/Right pairs averaged and every opening key scaled by (1 - mouthClose) so p/b/m closures show, exactly
like the game's make_face_clip.py for the beggar. The output is what game/characters/face_curves_player.gd plays.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

import sys
from i18n import t as _t

PY = sys.executable if sys.executable.lower().endswith("python.exe") else r"D:\conda\envs\sf3d\python.exe"
VENDOR = Path(__file__).resolve().parent / "vendor" / "lipsync"
WHISPER = "models--openai--whisper-small"


def tools(cfg):
    """(transcribe.py, lipsync.py): an explicit lipsync_skills_dir from config, else the vendored copies."""
    d = (cfg.get("lipsync_skills_dir") or "").strip()
    if d:
        return Path(d) / "whisper-transcribe" / "scripts" / "transcribe.py", Path(d) / "3d-animator" / "scripts" / "lipsync.py"
    return VENDOR / "transcribe.py", VENDOR / "lipsync.py"


def whisper_env(cfg):
    """(env, online): reuse a Hugging Face cache that already has whisper-small, else allow one download."""
    env = dict(os.environ)
    homes = [os.environ.get("HF_HOME"), cfg.get("hf_home"), r"D:\conda\hf", str(Path.home() / ".cache" / "huggingface")]
    for h in [h for h in homes if h]:
        if (Path(h) / "hub" / WHISPER).exists():
            env["HF_HOME"] = h
            return env, False
    env["HF_HOME"] = cfg.get("hf_home") or r"D:\conda\hf"
    return env, True


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


def _run(args, timeout, env=None):
    r = subprocess.run(args, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       env=env, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
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
    tr, ls = tools(cfg)
    for f in (tr, ls):
        if not f.exists():
            raise RuntimeError(_t("lip.the_lipsync_script_was_not_found", f))
    env, online = whisper_env(cfg)
    keys = shape_keys(model_glb)
    if not keys:
        raise RuntimeError(_t("lip.the_model_has_no_shape_keys_build"))
    out_dir = Path(model_glb).parent
    stem = Path(audio).stem
    work = Path(cfg["work_dir"]) / "lipsync" / stem
    work.mkdir(parents=True, exist_ok=True)
    audio_copy = out_dir / Path(audio).name
    if Path(audio).resolve() != audio_copy.resolve():
        shutil.copyfile(audio, audio_copy)
    yield (_t("lip.whisper_first_run_downloading_the") + env["HF_HOME"] + "…" if online
           else _t("lip.whisper_word_timings_gpu_about_1_gb"))
    code, log = _run([PY, "-I", "-X", "utf8", str(tr), str(audio_copy), "--lang", lang, "--out-dir", str(work)]
                     + (["--online"] if online else []), 1800, env)
    words = work / f"{stem}.words.json"
    if code != 0 or not words.exists():
        raise RuntimeError(_t("lip.whisper_could_not_recognise_the") + log[-1500:])
    heard = (work / f"{stem}.txt").read_text(encoding="utf-8").strip() if (work / f"{stem}.txt").exists() else ""
    yield _t("lip.whisper_heard", heard)
    yield _t("lip.building_the_face_curves_phonemes")
    raw = work / f"{stem}.lipsync.json"
    code, log = _run([PY, "-I", "-X", "utf8", str(ls), "--audio", str(audio_copy), "--text", text or heard,
                      "--lang", lang, "--words", str(words), "--out", str(raw)], 900)
    if not raw.exists():
        raise RuntimeError(_t("lip.lipsync_py_did_not_build_the_curves") + log[-1500:])
    d = json.loads(raw.read_text(encoding="utf-8"))
    clip = reduce_curves(d, keys)
    dst = out_dir / f"{stem}.face.json"
    dst.write_text(json.dumps(clip, ensure_ascii=False, separators=(",", ":")), encoding="utf-8", newline="\n")
    qa = clip["qa"]
    used = list(clip["curves"])
    yield (_t("lip.clip_frames_fps_keys_qa_p_b_m", clip['frames'], clip['fps'], ', '.join(used), 'ok' if qa.get('ok') else 'есть замечания', qa.get('pp_closures', '?'), qa.get('max_jaw', '?')) + ("" if code == 0 else _t("lip.lipsync_py_returned_code_1_see_qa")))
    yield {"clip": str(dst), "audio": str(audio_copy), "keys": used, "qa": qa}
