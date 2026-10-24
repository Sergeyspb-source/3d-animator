"""The interface language: every text the user sees lives in lang/<code>.json (key -> text), the code asks for it by
key with t(). The language comes from "lang" in config.json (ru by default) and is fixed for the process: switching
it in the UI saves the setting and restarts the server. A key missing in the chosen language falls back to Russian,
then to the key itself.

    t("ui.done")                      -> the text as is (a plain string literal was there: .format / % may follow)
    t("ui.done_in_s", secs)           -> the text .format()-ed with the arguments (an f-string was there)
    fill("... {{ui.done}} ...")       -> an HTML/JS/GDScript template with its markers replaced ({{js:key}} escapes
                                         quotes and backslashes for a JS string, {{raw:key}} puts the text as is,
                                         {{key}} escapes it for HTML)

Works in plain Python and inside Blender (no imports beyond the standard library)."""
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
LANGS = {"ru": "Русский", "en": "English"}
DEFAULT = "ru"


def _config_lang() -> str:
    try:
        code = json.loads((ROOT / "config.json").read_text(encoding="utf-8")).get("lang") or DEFAULT
    except (OSError, ValueError):
        code = DEFAULT
    return code if code in LANGS else DEFAULT


def _load(code: str) -> dict:
    try:
        return json.loads((ROOT / "lang" / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


LANG = _config_lang()
_TEXT = _load(LANG)
_BASE = _TEXT if LANG == DEFAULT else _load(DEFAULT)


def t(key: str, *args, **kw) -> str:
    text = _TEXT.get(key) or _BASE.get(key) or key
    return text.format(*args, **kw) if args or kw else text


def catalog() -> dict:
    """Every key in the current language (the fallback filled in): for pages that look texts up themselves."""
    return {**_BASE, **_TEXT}


_MARK = re.compile(r"\{\{(js:|raw:)?([A-Za-z0-9_.]+)\}\}")


def _js(s: str) -> str:
    return s.replace("\\", "\\\\").replace("'", "\\'").replace('"', '\\"').replace("`", "\\`").replace("\n", "\\n")


def fill(template: str) -> str:
    def one(m):
        kind, text = m.group(1), t(m.group(2))
        return _js(text) if kind == "js:" else text if kind == "raw:" else html.escape(text, quote=True)
    return _MARK.sub(one, template)


def set_lang(code: str) -> None:
    """Saves the language into config.json; it takes effect when the server starts again."""
    if code not in LANGS:
        return
    p = ROOT / "config.json"
    try:
        cfg = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        cfg = {}
    cfg["lang"] = code
    p.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
