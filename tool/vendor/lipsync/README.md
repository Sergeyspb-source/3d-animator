# Lip-sync tools (vendored)

Copies of the author's own scripts from the game project, so SF3D works without it:

- `transcribe.py` - word timings with local Whisper (`openai/whisper-small` via `transformers`, GPU if available).
- `lipsync.py` - voice + script line -> 60 fps ARKit blendshape curves (`face-curves/1`).

`tool/lipsync_link.py` runs them; set `lipsync_skills_dir` in `tool/config.json` only to use another copy (a folder with
`whisper-transcribe/scripts/transcribe.py` and `3d-animator/scripts/lipsync.py`). Hashes of the copied versions:
`source_manifest.json`. Needs numpy, scipy, torch, transformers and soundfile or ffmpeg for mp3/ogg (all in the `sf3d`
env). The Whisper model (~1 GB) is downloaded on the first run.
