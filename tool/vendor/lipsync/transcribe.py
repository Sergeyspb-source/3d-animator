"""Speech audio (mp3/wav/ogg/...) -> text + per-word timings with Whisper via Hugging Face transformers.

Outputs (next to --out-dir, named by the audio stem unless overridden):
  <stem>.txt         recognised text, one line
  <stem>.words.json  [{"w": word, "t0": sec, "t1": sec}, ...]  -- the format of 3d-animator lipsync.py --words
  <stem>.srt         optional subtitles (--srt), one cue per sentence-ish chunk

Usage
  python -I -X utf8 transcribe.py take.mp3 --lang ru --out-dir out/
  python -I -X utf8 transcribe.py a.mp3 b.wav --lang en --srt
  python -I -X utf8 transcribe.py take.mp3 --model openai/whisper-medium --online   # download another model

Runs offline by default (HF_HUB_OFFLINE=1): only models already in ~/.cache/huggingface are used.
"""
import argparse, json, os, sys
from pathlib import Path

DEFAULT_MODEL = "openai/whisper-small"
LANGS = {"ru": "russian", "en": "english"}
MIN_WORD = 0.05      # seconds; a word with no end timestamp gets at least this


def parse_args():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", nargs="+", help="audio files (anything ffmpeg can decode)")
    ap.add_argument("--lang", default="auto", help="ru, en, any Whisper language name, or auto (default)")
    ap.add_argument("--model", default=DEFAULT_MODEL, help=f"HF model id (default {DEFAULT_MODEL})")
    ap.add_argument("--out-dir", help="output folder (default: next to each audio file)")
    ap.add_argument("--srt", action="store_true", help="also write an .srt subtitle file")
    ap.add_argument("--cpu", action="store_true", help="force CPU even when CUDA is available")
    ap.add_argument("--online", action="store_true", help="allow downloading the model from Hugging Face")
    return ap.parse_args()


def load_pipeline(model, cpu):
    import torch
    from transformers import pipeline
    use_cuda = torch.cuda.is_available() and not cpu
    pipe = pipeline("automatic-speech-recognition", model=model, device=0 if use_cuda else -1,
                    torch_dtype=torch.float16 if use_cuda else torch.float32)
    return pipe, ("cuda" if use_cuda else "cpu")


def clean_words(chunks, duration):
    """Pipeline chunks -> [{w,t0,t1}], monotonic, every word with a finite end."""
    out = []
    for i, c in enumerate(chunks):
        word = c["text"].strip()
        if not word:
            continue
        t0, t1 = c["timestamp"]
        t0 = float(t0 if t0 is not None else (out[-1]["t1"] if out else 0.0))
        if t1 is None:          # the last word often has no end: stop at the next word or the audio end
            nxt = next((n["timestamp"][0] for n in chunks[i + 1:] if n["timestamp"][0] is not None), None)
            t1 = nxt if nxt is not None else duration
        t1 = max(float(t1), t0 + MIN_WORD)
        if out and t0 < out[-1]["t1"]:
            t0 = out[-1]["t1"]
            t1 = max(t1, t0 + MIN_WORD)
        out.append({"w": word, "t0": round(t0, 3), "t1": round(t1, 3)})
    return out


def srt_time(t):
    ms = int(round(t * 1000))
    h, ms = divmod(ms, 3600000)
    m, ms = divmod(ms, 60000)
    s, ms = divmod(ms, 1000)
    return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"


def to_srt(words, max_words=10):
    cues, cur = [], []
    for w in words:
        cur.append(w)
        if w["w"][-1:] in ".!?…" or len(cur) >= max_words:
            cues.append(cur)
            cur = []
    if cur:
        cues.append(cur)
    lines = []
    for i, cue in enumerate(cues, 1):
        text = " ".join(w["w"] for w in cue)
        lines += [str(i), f"{srt_time(cue[0]['t0'])} --> {srt_time(cue[-1]['t1'])}", text, ""]
    return "\n".join(lines)


def transcribe(pipe, path, lang):
    import numpy as np
    from transformers.pipelines.audio_utils import ffmpeg_read
    sr = pipe.feature_extractor.sampling_rate
    audio = ffmpeg_read(Path(path).read_bytes(), sr)
    duration = len(audio) / sr
    gen = {"task": "transcribe"}
    if lang != "auto":
        gen["language"] = LANGS.get(lang, lang)
    r = pipe({"raw": np.asarray(audio), "sampling_rate": sr}, return_timestamps="word",
             chunk_length_s=30, batch_size=8, generate_kwargs=gen)
    return r["text"].strip(), clean_words(r.get("chunks", []), duration), duration


def main():
    a = parse_args()
    if not a.online:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
    try:
        pipe, dev = load_pipeline(a.model, a.cpu)
    except ImportError as e:
        sys.exit(f"needs torch + transformers (use D:/conda/envs/sf3d/python.exe): {e}")
    except OSError as e:
        sys.exit(f"model {a.model} is not in the local cache; rerun with --online to download it\n{e}")
    print(f"model {a.model} on {dev}")
    failed = 0
    for src in a.audio:
        p = Path(src)
        if not p.is_file():
            print(f"FAIL {src}: file not found")
            failed += 1
            continue
        try:
            text, words, dur = transcribe(pipe, p, a.lang)
        except Exception as e:  # noqa: BLE001 - report and continue with the other files
            print(f"FAIL {src}: {e}")
            failed += 1
            continue
        out = Path(a.out_dir) if a.out_dir else p.parent
        out.mkdir(parents=True, exist_ok=True)
        (out / f"{p.stem}.txt").write_text(text + "\n", encoding="utf-8")
        (out / f"{p.stem}.words.json").write_text(json.dumps(words, ensure_ascii=False, indent=1), encoding="utf-8")
        if a.srt:
            (out / f"{p.stem}.srt").write_text(to_srt(words), encoding="utf-8")
        print(f"ok   {src}: {dur:.2f}s, {len(words)} words -> {out / p.stem}.*")
        print(f"     {text}")
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
