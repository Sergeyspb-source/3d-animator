"""Reference pictures for 3D generation: a style card, prompt assembly and two image providers.

Providers:
  codex       the user's ChatGPT subscription through the official Codex CLI (`codex exec`, its image tool);
              no API key, uses the plan's limits, about 2 minutes per picture,
  openrouter  OpenRouter chat completions with an image-output model (e.g. Google's Nano Banana), by API key.
The style card (work_dir/refgen/style.json) holds a style text and reference pictures; every request is
"style + object + technical requirements for 3D", so pictures of different objects share one look.
"""
import base64
import json
import os
import shutil
import subprocess
import time
import urllib.request
from pathlib import Path

CATEGORY_RULES = {
    "item": "a single game item or weapon, fully visible, centred, seen from the front, slightly from above",
    "prop": "a single prop object, fully visible, centred, seen straight from the front at eye level",
    "building": "a single building, fully visible including the roof and the base, seen from the front, "
                "slightly from above, no surrounding terrain",
    "vegetation": "a single plant standing on its own (a tree, a bush or a tuft of grass), fully visible from the "
                  "roots to the top of the crown, seen from the front at eye level, leaves in clear dense clumps",
    "surface": "a seamless tileable texture of the surface seen exactly from above (orthographic top view), "
               "filling the whole square frame edge to edge, the same density everywhere, no perspective, no "
               "horizon, no single big object, no border, no vignette",
    "character": "a single character standing in a relaxed A-pose (arms slightly away from the body, legs apart), "
                 "full body from head to feet, seen straight from the front, neutral face",
    "creature": "a single creature standing on all its legs in a neutral pose, full body, seen from the side "
                "slightly in front, mouth slightly open (20-30 degrees) showing the teeth",
}
TECH = ("Requirements for turning the picture into a 3D model: one object only, nothing else in the picture, "
        "plain light grey background, soft even lighting without strong shadows or reflections, no ground plane, "
        "no text, no watermark, no frame.")
SURFACE_TECH = ("Requirements for a game texture: square picture, soft uniform top lighting with no cast shadows from "
                "one side and no bright highlights, the pattern continues across the left/right and top/bottom "
                "edges so the picture tiles without a seam, no text, no watermark.")
VIEW_RULES = {
    "front": "",
    "back": "Show exactly the same object from behind (rotated 180 degrees), same scale, pose and lighting.",
    "left": "Show exactly the same object from its left side (rotated 90 degrees), same scale, pose and lighting.",
    "right": "Show exactly the same object from its right side (rotated 90 degrees), same scale, pose and lighting.",
}


def codex_exe():
    for name in ("codex.cmd", "codex"):
        p = shutil.which(name)
        if p:
            return p
    p = Path(os.environ.get("APPDATA", "")) / "npm" / "codex.cmd"
    return str(p) if p.exists() else None


# ------------------------------------------------------------------ style card
def style_path(work_dir):
    p = Path(work_dir) / "refgen"
    p.mkdir(parents=True, exist_ok=True)
    return p / "style.json"


def load_style(work_dir):
    p = style_path(work_dir)
    if p.exists():
        try:
            return json.loads(p.read_text(encoding="utf-8"))
        except Exception:  # noqa: BLE001
            pass
    return {"text": "", "refs": []}


def save_style(work_dir, text, refs):
    folder = style_path(work_dir).parent / "style_refs"
    folder.mkdir(exist_ok=True)
    kept = []
    for r in refs or []:
        r = Path(r)
        if not r.exists():
            continue
        dst = folder / r.name
        if r.resolve() != dst.resolve():
            shutil.copy2(r, dst)
        kept.append(str(dst))
    data = {"text": text or "", "refs": kept}
    style_path(work_dir).write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    return data


def build_prompt(obj, category, style_text, view="front", has_style_refs=False, has_front=False):
    parts = []
    if style_text:
        parts.append(f"Art style: {style_text.strip()}")
    if has_style_refs:
        parts.append("Match the art style, materials, colours and level of detail of the attached style "
                     "reference pictures exactly; do not copy their objects.")
    parts.append(f"Subject: {obj.strip()}.")
    parts.append("Framing: " + CATEGORY_RULES.get(category, CATEGORY_RULES["prop"]) + ".")
    if view != "front":
        parts.append(VIEW_RULES[view] + (" The first attached picture is the front view of this object."
                                          if has_front else ""))
    parts.append(SURFACE_TECH if category == "surface" else TECH)
    return "\n".join(parts)


# ------------------------------------------------------------------ providers
def _codex_run(prompt, images, out_dir, timeout=900):
    exe = codex_exe()
    if not exe:
        raise RuntimeError("Codex CLI не найден. Установите его и войдите командой codex login.")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    last = out_dir / f"_codex_{int(time.time() * 1000)}.txt"
    cmd = [exe, "exec", "--skip-git-repo-check", "--ephemeral", "--sandbox", "workspace-write", "-C", str(out_dir),
           "-o", str(last)]
    for im in images:
        cmd += ["--image", str(im)]
    cmd.append("-")  # the prompt comes on stdin: --image would swallow it otherwise
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       timeout=timeout, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    text = last.read_text(encoding="utf-8", errors="replace").strip() if last.exists() else ""
    last.unlink(missing_ok=True)
    if r.returncode != 0 and not text:
        tail = (r.stderr or r.stdout)[-400:]
        if "login" in tail.lower() or "auth" in tail.lower():
            raise RuntimeError("Codex не авторизован: выполните codex login в терминале. " + tail)
        raise RuntimeError("Codex завершился с ошибкой: " + tail)
    return text


def codex_image(prompt, images, out_png, timeout=900):
    out_png = Path(out_png)
    full = (f"Generate ONE image with your image generation tool and save it as the PNG file \"{out_png}\". "
            "Do not write or run any other code and do not change any other files. "
            "When done, reply with the full path of the saved file only.\n\n" + prompt)
    _codex_run(full, images, out_png.parent, timeout)
    if not out_png.exists() or out_png.stat().st_size < 1000:
        raise RuntimeError("Codex не сохранил картинку (возможно, исчерпан лимит подписки на картинки).")
    return out_png


def codex_describe(images, timeout=600, out_dir=None):
    prompt = ("Describe the visual art style of the attached pictures so that an image generator can reproduce it "
              "for completely different objects. Cover: rendering style (painted, stylised 3D, realistic), "
              "palette and saturation, materials and how they are worn, proportions and shape language, "
              "level of detail, lighting. Do not describe what the objects are. Answer with one paragraph in "
              "English, at most 90 words, no lists, no preface. Do not create or change any files.")
    return _codex_run(prompt, images, out_dir or Path(os.environ.get("TEMP", ".")) / "sf3d_refgen", timeout)


OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"


def _or_call(key, model, prompt, images, want_image, timeout=300):
    content = [{"type": "text", "text": prompt}]
    for im in images:
        b = base64.b64encode(Path(im).read_bytes()).decode()
        ext = Path(im).suffix.lower().lstrip(".") or "png"
        mime = "jpeg" if ext in ("jpg", "jpeg") else ext
        content.append({"type": "image_url", "image_url": {"url": f"data:image/{mime};base64,{b}"}})
    body = {"model": model, "messages": [{"role": "user", "content": content}]}
    if want_image:
        body["modalities"] = ["image", "text"]
    req = urllib.request.Request(OPENROUTER_URL, data=json.dumps(body).encode(),
                                 headers={"Authorization": f"Bearer {key}", "Content-Type": "application/json",
                                          "X-Title": "SF3D game assets"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"OpenRouter ответил {e.code}: {e.read().decode(errors='replace')[:300]}") from e
    if "error" in data:
        raise RuntimeError(f"OpenRouter: {data['error']}")
    return data["choices"][0]["message"]


def openrouter_image(key, model, prompt, images, out_png):
    if not key:
        raise RuntimeError("Не задан ключ OpenRouter (вкладка «Настройки»).")
    msg = _or_call(key, model, prompt, images, True)
    for im in msg.get("images") or []:
        url = (im.get("image_url") or {}).get("url", "")
        if url.startswith("data:"):
            Path(out_png).write_bytes(base64.b64decode(url.split(",", 1)[1]))
            return Path(out_png)
    raise RuntimeError(f"Модель {model} не вернула картинку. Ответ: {str(msg.get('content'))[:200]}")


def openrouter_describe(key, model, images):
    prompt = ("Describe the visual art style of the attached pictures so that an image generator can reproduce it "
              "for different objects: rendering style, palette, materials and wear, shape language, detail, "
              "lighting. Do not describe the objects. One English paragraph, at most 90 words.")
    msg = _or_call(key, model, prompt, images, False)
    return (msg.get("content") or "").strip()
