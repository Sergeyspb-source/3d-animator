"""An image model through OpenRouter's Image API (https://openrouter.ai/api/v1/images) repainting a piece's unwrap
for «Texture by the unwrap»: the part's colours (its islands, <part>_color.png) given as the reference, a prompt that
keeps every island in place; the picture that comes back is that part's texture. The key is the app's own
(config.json: openrouter_key, set in «Settings»). Only the models that take a picture in (an edit) are offered.
"""
import base64
import json
import time
import urllib.error
import urllib.request
from pathlib import Path

API = "https://openrouter.ai/api/v1"
HEAD = {"User-Agent": "sf3d-tool", "X-Title": "SF3D game assets"}
DEFAULT = "google/gemini-3.1-flash-image"   # Nano Banana 2: follows the islands (the user's tests, 2026-11-11)
_MODELS = {"at": 0, "list": []}


def _get(url, key=None, body=None, timeout=60):
    h = dict(HEAD)
    if key:
        h["Authorization"] = f"Bearer {key}"
    if body is not None:
        h["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=None if body is None else json.dumps(body).encode(), headers=h)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenRouter {e.code}: {e.read().decode(errors='replace')[:400]}") from e


def models() -> list:
    """The image models that edit a picture given: [{id, name, params}], fetched once an hour."""
    if not _MODELS["list"] or time.time() - _MODELS["at"] > 3600:
        out = []
        for m in _get(f"{API}/images/models").get("data", []):
            a, sp = m.get("architecture") or {}, m.get("supported_parameters") or {}
            if "image" in (a.get("input_modalities") or []) and "input_references" in sp:
                out.append({"id": m["id"], "name": m.get("name") or m["id"], "params": sorted(sp)})
        _MODELS.update(at=time.time(), list=out)
    return _MODELS["list"]


def price(model: str) -> str:
    """About its price per picture, as its endpoints say it (the cheapest one)."""
    try:
        eps = _get(f"{API}/images/models/{model}/endpoints").get("endpoints", [])
    except (RuntimeError, OSError):
        return ""
    # per token: a 1K square is about 1290 of Google's tokens, 4200 of OpenAI's at «high»; the rest a guess (the real
    # cost is said after the picture)
    per = 4200 if model.startswith("openai/") else 1290 if model.startswith("google/") else 1500
    best = None
    for e in eps:
        for p in e.get("pricing") or []:
            if p.get("billable") != "output_image":
                continue
            c = float(p["cost_usd"]) * (1 if p.get("unit") == "image" else per if p.get("unit") == "token" else 0)
            if c and (best is None or c < best):
                best = c
    return f"${best:.3f}" if best else ""


def edit(key: str, model: str, prompt: str, image: Path, timeout: int = 600, refs=()) -> tuple:
    """The picture repainted by the model (refs: more pictures after it - a sample to follow): (png bytes, its cost in
    USD or None)."""
    if not key:
        raise RuntimeError("no key")
    m = next((x for x in models() if x["id"] == model), None)
    params = set(m["params"]) if m else {"aspect_ratio", "input_references"}
    def ref(pth):
        b = Path(pth).read_bytes()
        mime = "image/jpeg" if b[:3] == b"\xff\xd8\xff" else "image/png"
        return {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{base64.b64encode(b).decode()}"}}
    body = {"model": model, "prompt": prompt, "n": 1, "input_references": [ref(image), *(ref(r) for r in refs if r and Path(r).exists())]}
    if "aspect_ratio" in params:
        body["aspect_ratio"] = "1:1"
    if "resolution" in params:
        body["resolution"] = "1K"
    if "output_format" in params:
        body["output_format"] = "png"
    if "quality" in params:
        body["quality"] = "high"
    r = _get(f"{API}/images", key, body, timeout)
    if r.get("error"):
        raise RuntimeError(f"OpenRouter: {r['error']}")
    imgs = r.get("data") or []
    if not imgs or not imgs[0].get("b64_json"):
        raise RuntimeError(f"OpenRouter: {model} returned no picture")
    return base64.b64decode(imgs[0]["b64_json"]), (r.get("usage") or {}).get("cost")
