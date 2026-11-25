"""«Equipment» (and «Character → Looks») in the web UI: the procedural editor (tool/armour_gen_editor.html) as a page
of its own, its requests answered by armour_gen_ui.handle as in the former Gradio app.

The editor is not changed: it still writes a request into «the parent page's hidden field» and clicks «its hidden
button», then waits for the answer file (work/status/<model>/<stem>_<action>.wear.json) through /file=<path>. The shell
keeps that field and button (they post to /api/equip/action), the server serves /file= like Gradio did. The page gets
the shell's look and the steps' modes from adapters/armour_editor.css + .js, put into it here.

Long requests (a piece made in Blender, a generator's preview, the check in motion, learning an outline) go into the
GPU task queue and show in the dock; the quick ones run at once, one after another (as Gradio ran them)."""
import json
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import sf3d_tool as T
from i18n import t as _t
from pages import inject

HERE = Path(__file__).resolve().parent
ADAPTER_CSS = HERE / "adapters" / "armour_editor.css"
ADAPTER_JS = HERE / "adapters" / "armour_editor.js"
HEAVY = {None: "web.eq_generate", "generate": "web.eq_generate", "made_preview": "web.eq_preview", "qa": "web.eq_qa",
         "contour_learn": "web.eq_learn"}
_quick = ThreadPoolExecutor(max_workers=1, thread_name_prefix="equip-quick")


def _ag():
    import armour_gen_ui as AG   # (imported by sf3d_ui already; late here so the config patch is in place first)
    return AG


def page(rigged: str) -> str:
    cfg = T.load_config()
    r = Path(rigged)
    return inject(_ag().editor_page(r, Path(cfg["export_dir"]) / "decals"), css=[ADAPTER_CSS], js=[ADAPTER_JS])


def _shots(shots) -> list:
    out = []
    for s in shots or []:
        if isinstance(s, (list, tuple)):
            out.append({"path": str(s[0]), "caption": str(s[1]) if len(s) > 1 else ""})
        elif s:
            out.append({"path": str(s), "caption": ""})
    return out


def run(text: str) -> dict:
    log, shots = _ag().handle(T.load_config(), text)
    return {"log": log, "shots": _shots(shots)}


def heavy(req: dict) -> str | None:
    """The text key of a long request's task title, None for a quick one."""
    return HEAVY.get(req.get("action"), None) if req.get("action") in HEAVY else None


def title(req: dict, key: str) -> str:
    what = req.get("item") or req.get("style") or (req.get("job") or {}).get("item") or req.get("piece") or ""
    return _t(key) + (f" · {what}" if what else "")


def quick(text: str):
    return _quick.submit(run, text)


def parse(text: str) -> dict:
    req = json.loads(text)
    if not isinstance(req, dict) or not req.get("rigged"):
        raise ValueError("no rigged model in the request")
    return req
