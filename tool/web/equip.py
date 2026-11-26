"""«Equipment» (and «Character → Looks») in the web UI: the procedural editor (tool/armour_gen_editor.html) as a page
of its own, its requests answered by armour_gen_ui.handle as in the former Gradio app.

The editor is not changed: it still writes a request into «the parent page's hidden field» and clicks «its hidden
button», then waits for the answer file (work/status/<model>/<stem>_<action>.wear.json) through /file=<path>. The shell
keeps that field and button (they post to /api/equip/action), the server serves /file= (the form Gradio had). The page gets
the shell's look and the steps' modes from adapters/armour_editor.css + .js, put into it here.

Long requests (a piece made in Blender, a generator's preview, the check in motion, learning an outline) go into the
GPU task queue and show in the dock; the quick ones run at once, one after another."""
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


def item_of(req: dict) -> str:
    return req.get("item") or (req.get("job") or {}).get("item") or ""


def title(req: dict, key: str) -> str:
    what = item_of(req) or req.get("style") or req.get("piece") or ""
    return _t(key) + (f" · {what}" if what else "")


def quick(text: str):
    return _quick.submit(run, text)


def parse(text: str) -> dict:
    req = json.loads(text)
    if not isinstance(req, dict) or not req.get("rigged"):
        raise ValueError("no rigged model in the request")
    return req


# ------------------------------------------------------------------ Check and Release: the pieces made, their checks
def _qa_file(cfg, rigged: Path, item: str) -> Path:
    """Where armour_gen_ui.qa leaves its report: work/armour_gen/<stem>_<item>/qa.json."""
    import re
    ag = _ag()
    it = re.sub(r"[^A-Za-z0-9_-]+", "_", item or "").strip("_")
    return Path(cfg["work_dir"]) / "armour_gen" / f"{ag.LM._stem(rigged)}_{it}" / "qa.json"


def _qa_rows(rep: dict) -> list:
    """Each clip of a check: the skin through the piece's middle, its holes, at its edge (shares 0..1), the worst frame;
    a held piece (a weapon, a shield, a sheath): the body going through it and where it faces wrong."""
    rows = []
    for c in rep.get("clips") or []:
        if "poke_share" in c:
            rows.append({"clip": c.get("clip"), "through": c.get("poke_share") or 0, "holes": c.get("hole_share") or 0,
                         "edge": c.get("edge_share") or 0, "frame": c.get("worst_frame"),
                         "bad": (c.get("poke_share") or 0) > .02 or (c.get("hole_share") or 0) > .05})
        else:
            rows.append({"clip": c.get("clip"), "through": c.get("through") or 0, "holes": None, "edge": None,
                         "frame": c.get("worst_frame"), "facing": c.get("facing"), "held": True,
                         "bad": bool(c.get("through")) or bool(c.get("facing"))})
    return rows


def qa_report(rigged: str, item: str) -> dict:
    """The last check of a piece: its clips, the worst frames' pictures, and whether the piece was made again since."""
    cfg = T.load_config()
    r = Path(rigged)
    f = _qa_file(cfg, r, item)
    glb = _ag().WF.path(r, item, ".glb")
    baked = int(glb.stat().st_mtime) if glb.is_file() else None
    if not f.is_file():
        return {"item": item, "made": glb.is_file(), "baked": baked, "checked": False}
    try:
        rep = json.loads(f.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"item": item, "made": glb.is_file(), "baked": baked, "checked": False}
    rows = _qa_rows(rep)
    return {"item": item, "made": glb.is_file(), "baked": baked, "checked": True, "when": int(f.stat().st_mtime), "rows": rows,
            "bad": any(x["bad"] for x in rows), "stale": glb.is_file() and glb.stat().st_mtime > f.stat().st_mtime + 1,
            "shots": [{"path": str(s[0]), "caption": str(s[1]) if len(s) > 1 else ""} if isinstance(s, (list, tuple)) else {"path": str(s), "caption": ""}
                      for s in rep.get("shots") or []]}


HAIRY = ("hair", "beard", "brows", "lashes")   # (Character → Looks, not the equipment)


def made(rigged: str, hair: bool = False) -> dict:
    """Every piece the character has (made here or fitted in «Armour»): its kind, layer, when it was made, whether the
    editor can open it again (made here), and its last check in short. hair: the hair and beards (Looks) instead."""
    r = Path(rigged)
    ag = _ag()
    saved = {s["item"]: s for s in ag.saved(r)}
    rows = []
    for w in ag.worn(r):
        item, kind = w["item"], w.get("piece")
        if (kind in HAIRY) != hair:
            continue
        q = qa_report(rigged, item)
        rows.append({"item": item, "piece": kind, "label": _t(f"ag.piece_{kind}") if kind in ag.PIECES else (kind or ""),
                     "style": (saved.get(item) or {}).get("style"), "layer": w.get("layer"), "glb": w.get("glb"),
                     "when": w.get("v"), "editable": item in saved,
                     "qa": None if not q.get("checked") else {"bad": q["bad"], "stale": q["stale"], "when": q["when"]}})
    rows.sort(key=lambda x: (x["layer"] if isinstance(x["layer"], (int, float)) else 99, x["item"]))
    folder = ag.WF.path(r, "x", ".glb").parent.parent
    return {"rows": rows, "folder": folder.as_posix()}
