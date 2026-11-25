"""«Character → Animations» in the web UI: the 12 procedural clips (hanim), Mixamo FBX motions retargeted (fbxanim),
the clip check (clipcheck) and the clip viewer (viewer_anim.html) - the Gradio app's own functions, long ones as
tasks of the shared queue."""
import json
from pathlib import Path

import sf3d_tool as T
import sf3d_ui as UI
import hanim as HA
import fbxanim as FA
from i18n import t as _t
from pages import inject


def _files(value: str) -> dict:
    """The character's clip files: {"anim": path | None, "fbx": path | None} (beside its skeleton's model)."""
    src = UI._rigged_path(value)
    out = {}
    for kind in ("anim", "fbx"):
        p = UI._clips_file(src, kind) if src else None
        out[kind] = p if p and p.exists() else None
    return out


def _meta(glb: Path) -> list:
    try:
        m = json.loads(glb.with_name(glb.name + ".json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return m if isinstance(m, list) else (m.get("clips") or [])


def options() -> dict:
    return {"clips": [{"id": k, "label": v} for k, v in HA.CLIPS.items()],
            "manners": [{"id": k, "key": f"hanim.manner_{k}"} for k in HA.MANNERS],
            "deaths": [{"id": k, "key": f"hanim.death_{k}"} for k in HA.DEATHS],
            "weapons": list(FA.WEAPON_SETS), "fbx_dir": UI._fbx_dir()}


def state(value: str) -> dict:
    f = _files(value)
    return {k: ({"path": p.as_posix(), "when": p.stat().st_mtime, "clips": [c.get("name") for c in _meta(p)]} if p else None)
            for k, p in f.items()}


def procedural_task(value: str, clips: list, manner: str, seed: str, death: str):
    def run(task):
        labels = [HA.CLIPS[k] for k in clips if k in HA.CLIPS]
        res = None
        gen = UI.hanim_run(None, value, labels, _t(f"hanim.manner_{manner}") if manner in HA.MANNERS else None,
                           (seed or "").strip() or None, _t(f"hanim.death_{death}") if death in HA.DEATHS else None)
        try:
            for text, pics, dst in gen:
                task.set_lines(str(text or "").split("\n"))
                if dst:
                    res = {"model": str(dst), "shots": [str(p[0] if isinstance(p, (list, tuple)) else p) for p in pics or []]}
                    task.result = res
        finally:
            gen.close()
        if not res:
            raise RuntimeError(task.lines[-1] if task.lines else "no clips made")
        return res
    return run


def check_task(value: str, kind: str):
    def run(task):
        import clipcheck
        glb = _files(value).get(kind)
        if not glb:
            raise ValueError(_t("cc.none"))
        cfg = T.load_config()
        task.set_lines([_t("cc.running", glb.name)])
        md = clipcheck.check(cfg, glb, Path(cfg["work_dir"]) / "clip_check")[0]
        task.set_lines(str(md).splitlines())
        return {"md": md, "kind": kind}
    return run


def fbx_table(folder: str) -> dict:
    p = Path((folder or "").strip() or UI._fbx_dir())
    if not p.exists():
        return {"rows": [], "log": _t("ui.folder_not_found", p)}
    rows = FA.table_rows(p)
    return {"rows": rows, "log": _t("ui.files_found_the_clip_name_and_group", len(rows)) if rows else _t("ui.the_folder_has_no_fbx_download", p)}


def fbx_save(folder: str, rows: list) -> dict:
    p = Path((folder or "").strip() or UI._fbx_dir())
    FA.save_map(p, rows)
    return {"ok": True, "log": _t("ui.settings_saved_to", p / "map.json")}


def fbx_task(value: str, folder: str, rows: list, weapon: str):
    def run(task):
        res = None
        gen = UI.fbx_run(None, value, folder, rows, weapon if weapon in FA.WEAPON_SETS else _t("fbx.none"))
        try:
            for text, _page, dst in gen:
                task.set_lines(str(text or "").split("\n"))
                if dst:
                    res = {"model": str(dst)}
                    task.result = res
        finally:
            gen.close()
        if not res:
            raise RuntimeError(task.lines[-1] if task.lines else "no clips made")
        return res
    return run


def viewer_page(value: str, kind: str, weapon: str = "") -> str:
    glb = _files(value).get(kind)
    if not glb:
        raise ValueError(_t("cc.none"))
    rows = FA.table_rows(Path(UI._fbx_dir())) if kind == "fbx" and Path(UI._fbx_dir()).exists() else None
    return inject(FA.viewer_html(glb, {"clips": _meta(glb)}, rows, weapon if weapon in FA.WEAPON_SETS else _t("fbx.none")))
