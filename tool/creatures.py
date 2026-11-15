"""Creatures (four paws, a tail, a muzzle; any skeleton that is not a humanoid's): which models are creatures, their
files and skeleton passport, and the skeleton viewer page (skeleton_view.html) - for any skinned model, a humanoid's too.

A model is a creature when its passport <name>_rig.json says "kind": "creature" (the creature skeleton writes it; a
model added in the «Creatures» section gets it at once, before its skeleton). Its files stay in export/character/<name>/
as a character's do: <name>.glb (the source), <name>_unirig.glb (UniRig's skeleton), <name>_auto.glb (turned, bones
named), <name>_rigged.glb (with the jaw: what the tools take), <name>_jaw_*.png (the jaw closed and open).
"""
import base64
import json
from pathlib import Path

import i18n

ROOT = Path(__file__).resolve().parent
VIEWER = ROOT / "skeleton_view.html"


def passport(d: Path, name: str) -> dict:
    """<name>_rig.json beside the skeleton ({} without one)."""
    try:
        v = json.loads((Path(d) / f"{name}_rig.json").read_text(encoding="utf-8"))
        return v if isinstance(v, dict) else {}
    except (OSError, ValueError):
        return {}


def is_creature(d: Path, name: str) -> bool:
    return passport(d, name).get("kind") == "creature"


def mark(d: Path, name: str) -> None:
    """A model taken as a creature before it has a skeleton: its passport says so (kept as it is when it has one)."""
    p = Path(d) / f"{name}_rig.json"
    meta = passport(d, name)
    if meta.get("kind") != "creature":
        meta["kind"] = "creature"
        Path(d).mkdir(parents=True, exist_ok=True)
        p.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def jaw_state(d: Path, name: str) -> dict | None:
    """What «Rebuild the jaw» needs - the named skeleton before the jaw and the jaw's first guess - read off the
    creature's files (after a restart too), or None before its skeleton."""
    d = Path(d)
    meta, auto = passport(d, name), d / f"{name}_auto.glb"
    if meta.get("kind") != "creature" or not meta.get("names") or not auto.exists():
        return None
    return dict(auto=str(auto), names=meta["names"], jaw=meta.get("jaw"), folder=str(d), name=name)


def jaw_pictures(d: Path, name: str) -> list:
    """The jaw's pictures made with the skeleton: [(png, caption)] closed and open, from the side and the front."""
    from i18n import t as _t
    labels = {"0_side": _t("ui.closed_side"), "0_front": _t("ui.closed_front"), "30_side": _t("ui.open_side"),
              "30_front": _t("ui.open_front")}
    return [(str(Path(d) / f"{name}_jaw_{k}.png"), v) for k, v in labels.items() if (Path(d) / f"{name}_jaw_{k}.png").exists()]


def summary(rigged: Path) -> dict:
    """The skeleton's bones by their names, read off the GLB's JSON: {bones, paws: {FL: n, ...}, tail, head, jaw}."""
    import landmarks
    try:
        j = landmarks._glb_json(rigged)
    except Exception:  # noqa: BLE001
        return {}
    joints = {i for sk in j.get("skins", []) for i in sk.get("joints", [])}
    names = [j["nodes"][i].get("name", "") for i in joints]
    paws = {}
    for n in names:
        if n.startswith("leg_") and len(n) > 6:
            paws[n[4:6]] = paws.get(n[4:6], 0) + 1
    return {"bones": len(names), "paws": paws, "tail": sum(n.startswith("tail") for n in names),
            "head": "head" in names, "jaw": "jaw" in names}


def viewer_page(glb: Path, title: str = "", kind: str = "", badge: str = "") -> str:
    """The skeleton viewer on this model (embedded whole: the page is an iframe's srcdoc)."""
    page = i18n.fill(VIEWER.read_text(encoding="utf-8"))
    data = {"title": title or Path(glb).stem, "kind": kind, "badge": badge}
    return (page.replace("@@DATA@@", json.dumps(data, ensure_ascii=False).replace("</", "<\\/"))
                .replace("@@GLB@@", base64.b64encode(Path(glb).read_bytes()).decode("ascii")))
