"""Deleting models from the app: a draft, a model released into export, a character or a creature - with every trace
the app keeps of it, so it shows nowhere any more:

- its folder (export/<category>/<name>, or the draft's work/web_drafts/export/<category>/<name>) and the copies put
  aside before (web_drafts/replaced|discarded/<category>/<name>-<time>);
- the generation's work folder (the one its <name>.json «source» points at: work/hunyuan|trellis|<category>/...),
  «Improve»'s (work/improve/<category>/<name>), the viewer's cache (work/_viewer/<name>__*), the page's pictures
  (work/web_tmp/*_<category>_<name>.*);
- what was made for it as a character or a creature: its procedural pieces (work/armour_gen/<name>_<item>), fittings
  (work/wear/<name>_*), the skeleton's work (work/landmark_rig/<name>), status, poses, clips and checks.

Everything goes to the Windows Recycle Bin (SHFileOperation with «allow undo»), never deleted for good: it can be put
back from there. A model a task is working on (a generation, a rig, a bake) is not touched. The game's own copy of a
model (in the game's project) is never touched either: the plan only says it is there.
A trace named by a prefix (<name>_...) is the longest known model name's: deleting «archer_1» never takes
«archer_1_v2»'s pieces."""
import ctypes
import json
import os
import re
from ctypes import wintypes
from pathlib import Path

import sf3d_tool as T
from i18n import t as _t
from models import CATEGORY_KEYS, drafts_root

GAME_DEFAULT = Path(r"D:\My projects\game-project-godot")
GAME_DIRS = ("assets", "source_assets", "game")   # where the game keeps models (its other folders: code, docs)
PREFIXED = ("armour_gen", "wear", "creature_rebuild", "creature_clips", "clip_check", "hanim")   # <name>_<what> in these
EXACT = ("landmark_rig", "creature_view", "hanim")                                               # <name> itself in these


def _cfg():
    return T.load_config()


def _split(mid: str):
    cat, _, name = (mid or "").partition("/")
    if not name or "/" in name or "\\" in name or name.startswith(".") or not re.fullmatch(r"[\w.-]+", cat):
        return None
    return cat, name


def _known(cfg) -> set:
    """Every model name the app has (export and drafts, every category): to tell whose a prefixed trace is."""
    out = set()
    for root in (Path(cfg["export_dir"]), drafts_root(cfg)):
        if root.is_dir():
            for c in root.iterdir():
                if c.is_dir():
                    out.update(x.name for x in c.iterdir() if x.is_dir())
    return out


def _owner(stem: str, known: set) -> str | None:
    """The longest known name this file or folder name starts with (<name>_... or <name>.)."""
    best = None
    for n in known:
        if (stem == n or stem.startswith(n + "_") or stem.startswith(n + ".")) and (best is None or len(n) > len(best)):
            best = n
    return best


def _source_dir(folder: Path, name: str, work: Path) -> Path | None:
    """The generation's work folder its <name>.json names (only one inside work_dir, never work_dir itself)."""
    try:
        src = Path(json.loads((folder / f"{name}.json").read_text(encoding="utf-8"))["source"]).parent
    except (OSError, ValueError, KeyError, TypeError):
        return None
    try:
        rel = src.resolve().relative_to(work.resolve())
    except ValueError:
        return None
    return src if len(rel.parts) >= 2 and src.is_dir() else None


def _size(p: Path) -> int:
    if p.is_file():
        return p.stat().st_size
    n = 0
    for root, _, files in os.walk(p):
        for f in files:
            try:
                n += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return n


def traces(mid: str, draft: bool, cfg=None) -> list[Path]:
    """Every existing file and folder of the model, the folders first (nothing twice, nothing inside another)."""
    cfg = cfg or _cfg()
    cn = _split(mid)
    if not cn:
        return []
    cat, name = cn
    work, export = Path(cfg["work_dir"]), Path(cfg["export_dir"])
    own = (drafts_root(cfg) if draft else export) / cat / name
    other = (export if draft else drafts_root(cfg)) / cat / name   # the same name's other copy: its traces stay
    keep = {p.resolve() for p in [other, _source_dir(other, name, work)] if p and p.exists()}
    known = _known(cfg)
    out = [own] if own.is_dir() else []
    out += [p for p in [_source_dir(own, name, work) if own.is_dir() else None] if p]
    for kind in ("replaced", "discarded"):
        d = work / "web_drafts" / kind / cat
        if d.is_dir():
            out += [x for x in d.iterdir() if x.is_dir() and re.fullmatch(re.escape(name) + r"-\d{8}-\d{6}", x.name)]
    for eng in ("hunyuan", "trellis", "improve"):
        out.append(work / eng / cat / name)
    out.append(work / cat / name)   # (SF3D's own work folder, by category)
    v = work / "_viewer"
    if v.is_dir():
        out += [x for x in v.iterdir() if x.name.startswith(name + "__")]
    t = work / "web_tmp"
    if t.is_dir():
        out += [x for x in t.iterdir() if x.is_file() and x.stem.endswith(f"_{cat}_{name}")]
    if not other.exists():   # a character's or a creature's own work: only when no other copy of the name stays
        for d in PREFIXED:
            dd = work / d
            if dd.is_dir():
                out += [x for x in dd.iterdir() if x.name != name and _owner(x.name, known | {name}) == name]
        for d in EXACT:
            out.append(work / d / name)
        out += [work / "status" / f"{cat}_{name}", work / "poses" / f"{cat}_{name}.json",
                work / "creature_clips" / f"{name}.json", work / "creature_rebuild" / f"{name}.json"]
    seen, res = set(), []
    for p in out:
        if not p.exists():
            continue
        r = p.resolve()
        if r in seen or r in keep or r == work.resolve() or r == export.resolve():
            continue
        seen.add(r)
        res.append(p)
    # nothing inside a folder already listed
    res = [p for p in res if not any(q != p and q.is_dir() and q.resolve() in p.resolve().parents for q in res)]
    return sorted(res, key=lambda p: (not p.is_dir(), str(p).lower()))


def _busy(mid: str, active) -> str | None:
    """The title of a queued or running task on this model, if there is one (active: the queue's tasks)."""
    name = mid.split("/", 1)[-1]
    pat = re.compile(r"(?<![\w-])" + re.escape(name) + r"(?![\w-])")
    for t in active:
        if t.status in ("queued", "running") and pat.search(json.dumps(t.meta, ensure_ascii=False) + " " + t.title):
            return t.title
    return None


def _game_copies(name: str, cfg, limit=6) -> list[str]:
    """Where the game's project has a file or folder of this name (read only; the game is never touched)."""
    root = Path(cfg.get("game_dir") or GAME_DEFAULT)
    hits = []
    for d in GAME_DIRS:
        base = root / d
        if not base.is_dir():
            continue
        for dirpath, dirs, files in os.walk(base):
            dirs[:] = [x for x in dirs if not x.startswith(".")]
            for x in dirs + files:
                stem = x.split(".", 1)[0]
                if stem == name:
                    hits.append(os.path.join(dirpath, x))
                    if len(hits) >= limit:
                        return hits
    return hits


def plan(items: list[dict], active=()) -> dict:
    """What deleting these models takes: per model its paths and sizes, a task on it, the game's copies."""
    cfg = _cfg()
    out, total = [], 0
    for it in items:
        mid, draft = it.get("id") or "", bool(it.get("draft"))
        ps = traces(mid, draft, cfg)
        sizes = [_size(p) for p in ps]
        n = sum(sizes)
        total += n
        out.append({"id": mid, "draft": draft, "busy": _busy(mid, active), "bytes": n,
                    "paths": [{"path": p.as_posix(), "bytes": s, "dir": p.is_dir()} for p, s in zip(ps, sizes)],
                    "game": [] if draft else _game_copies(mid.split("/", 1)[-1], cfg)})
    return {"items": out, "bytes": total}


# ------------------------------------------------------------------ the Recycle Bin: SHFileOperationW, FO_DELETE + allow undo
class _SHFILEOPSTRUCTW(ctypes.Structure):
    _fields_ = [("hwnd", wintypes.HWND), ("wFunc", wintypes.UINT), ("pFrom", wintypes.LPCWSTR), ("pTo", wintypes.LPCWSTR),
                ("fFlags", ctypes.c_ushort), ("fAnyOperationsAborted", wintypes.BOOL), ("hNameMappings", ctypes.c_void_p),
                ("lpszProgressTitle", wintypes.LPCWSTR)]


def to_bin(paths: list[Path]) -> None:
    """The paths into the Recycle Bin at once (no dialogs); raises when Windows says no."""
    if not paths:
        return
    FO_DELETE, FOF_SILENT, FOF_NOCONFIRMATION, FOF_ALLOWUNDO, FOF_NOERRORUI, FOF_WANTNUKEWARNING = 3, 4, 0x10, 0x40, 0x400, 0x4000
    buf = "\0".join(str(Path(p).resolve()) for p in paths) + "\0\0"
    op = _SHFILEOPSTRUCTW(None, FO_DELETE, buf, None, FOF_SILENT | FOF_NOCONFIRMATION | FOF_ALLOWUNDO | FOF_NOERRORUI | FOF_WANTNUKEWARNING,
                          False, None, None)
    rc = ctypes.windll.shell32.SHFileOperationW(ctypes.byref(op))
    if rc or op.fAnyOperationsAborted:
        raise OSError(f"SHFileOperation {rc:#x}")
    left = [p for p in paths if Path(p).exists()]
    if left:
        raise OSError("still there: " + ", ".join(str(p) for p in left[:3]))


def remove(items: list[dict], active=()) -> dict:
    """Each model's traces into the Recycle Bin (a model a task works on is left); the current objects that were it
    are cleared, so the page picks another."""
    cfg = _cfg()
    work = Path(cfg["work_dir"])
    done, left, lines = [], [], []
    for it in items:
        mid, draft = it.get("id") or "", bool(it.get("draft"))
        busy = _busy(mid, active)
        if busy:
            left.append(mid)
            lines.append(_t("web.rm_busy", mid, busy))
            continue
        ps = traces(mid, draft, cfg)
        if not ps:
            left.append(mid)
            lines.append(_t("web.rm_nothing", mid))
            continue
        try:
            to_bin(ps)
        except OSError as e:
            left.append(mid)
            lines.append(_t("web.rm_failed", mid, e))
            continue
        done.append(mid)
        lines.append(_t("web.rm_done", mid, len(ps)))
        if not draft:
            for memo in ("web_current_object.txt", "current_character.txt", "current_creature.txt"):
                f = work / memo
                try:
                    if f.read_text(encoding="utf-8").strip() == mid:
                        f.write_text("", encoding="utf-8")
                except OSError:
                    pass
    return {"ok": not left, "done": done, "left": left, "log": "\n".join(lines)}
