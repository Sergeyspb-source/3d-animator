"""Where a character's pieces live and what they are called.

export/character/<model>/ keeps the model, its skeleton and face; its pieces go into folders by what they are:
    armor/    the plates, mail, helmets, gloves, shoes (and pieces fitted in «Броня»)
    clothes/  clothes under the armour, trousers, a skirt, a tabard, a cloak
    weapons/  weapons, shields, scabbards and quivers
each as <item>.glb (the game's), <item>.mask.json (what of the body it hides), <item>.src.glb and <item>.fit.json (the
editors': the piece as made and its settings). <item> is <part>_<style>, «_2», «_3»… for another of the same: short,
the folder says whose it is (cuirass_steel, bracer_leather_2, helmet_barbute, sword, shield_round, undercloth_fitted).
The name is given once, when a piece is first made, and kept (the game and the fitting room know it by it).

The editors' answers (status files the pages wait for) go to work_dir/status/<category>_<model>/, not into the model's
folder. A character made before this layout (<stem>_wear_<item>.* next to the model) is moved over the first time its
pieces are listed (migrate): the files renamed by the rule, the names they reference in each other («under») too, the
old answers dropped.
"""
import json
import re
from pathlib import Path

CATS = ("armor", "clothes", "weapons")
CLOTHES = {"undercloth", "trousers", "skirt", "tabard", "cloak"}
WEAPONS = {"weapon", "shield", "sheath"}
SUFFIXES = (".glb", ".src.glb", ".mask.json", ".fit.json")
SURFACE_STYLES = ("mail", "scales", "lamellar", "brigandine", "splints", "quilt")   # a surface that names the piece over its material


def _stem(rigged) -> str:
    return re.sub(r"_(landmarks_)?rigged$", "", Path(rigged).stem)


def slug(text) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", str(text or "").lower()).strip("_")


def category(kind) -> str:
    return "clothes" if kind in CLOTHES else "weapons" if kind in WEAPONS else "armor"


def _folder(rigged, item: str, kind=None) -> Path:
    """The folder an item's files are in: where they already are, else its kind's."""
    d = Path(rigged).parent
    for cat in CATS:
        if any((d / cat / f"{item}{x}").exists() for x in (".fit.json", ".glb", ".src.glb")):
            return d / cat
    return d / category(kind)


def path(rigged, item: str, suffix: str, kind=None, make=False) -> Path:
    """An item's file (suffix: .glb, .src.glb, .mask.json, .fit.json); make: its folder made."""
    f = _folder(rigged, item, kind) / f"{item}{suffix}"
    if make:
        f.parent.mkdir(parents=True, exist_ok=True)
    return f


def items_in(char_dir) -> list:
    """Every piece in a character's folders: [(item, its .glb or None, its .fit.json or None)], by name."""
    d, out = Path(char_dir), {}
    for cat in CATS:
        for f in (d / cat).glob("*") if (d / cat).is_dir() else []:
            for x in (".src.glb", ".glb", ".fit.json"):   # (.src.glb first: «a.src.glb» is not the piece «a.src»)
                if f.name.endswith(x):
                    e = out.setdefault(f.name[:-len(x)], [None, None])
                    if x == ".glb":
                        e[0] = f
                    elif x == ".fit.json":
                        e[1] = f
                    break
    return [(k, g, fit) for k, (g, fit) in sorted(out.items())]


def pieces(rigged) -> list:
    """The pieces put on (their .glb), the character moved to the folders first."""
    migrate(rigged)
    return [g for _, g, _ in items_in(Path(rigged).parent) if g is not None]


def fits(rigged) -> list:
    """The pieces' settings (.fit.json), the character moved to the folders first."""
    migrate(rigged)
    return [f for _, _, f in items_in(Path(rigged).parent) if f is not None]


def is_piece_file(p) -> bool:
    """A file of a piece put on a character (in a model's armor/clothes/weapons folder, or the old <stem>_wear_ one)."""
    p = Path(p)
    return p.parent.name in CATS or "_wear_" in p.stem or p.name.endswith(".src.glb")


def status_dir(cfg, rigged) -> Path:
    d = Path(rigged).parent
    work = (cfg or __import__("sf3d_tool").load_config())["work_dir"]
    out = Path(work) / "status" / f"{d.parent.name}_{d.name}"
    out.mkdir(parents=True, exist_ok=True)
    return out


def status(cfg, rigged, name: str) -> Path:
    """An answer the page waits for: <status dir>/<stem><name>.wear.json (name: «_wear_<item>», «_qa_<item>»…)."""
    return status_dir(cfg, rigged) / f"{_stem(rigged)}{name}.wear.json"


# ---- names
def style_of(kind: str, params: dict, style=None) -> str:
    """The style part of a name: the kind's own choice (a weapon's, a shield's, a helmet's, a cloth's…), else the
    style chosen in the editor, else the surface that names it (mail, lamellar…) or the material."""
    p = params or {}
    own = {"weapon": p.get("weapon"), "shield": p.get("shield"), "helmet": p.get("helmet"), "glove": p.get("glove"),
           "elbow": re.sub(r"^elbow_", "", str(p.get("elbow") or "")), "footwear": re.sub(r"^foot_", "", str(p.get("footwear") or "")),
           "poleyn": re.sub(r"^poleyn_", "", str(p.get("poleyn") or "")),
           "codpiece": re.sub(r"^cod_", "", str(p.get("codpiece") or "")),
           "rondel": re.sub(r"^rondel_", "", str(p.get("rondel") or "")),
           "hauberk": re.sub(r"^hauberk_", "", str(p.get("hauberk") or "")), "coif": re.sub(r"^coif_", "", str(p.get("coif") or "")),
           "undercloth": p.get("cloth_style"), "sheath": p.get("sheath")}.get(kind)
    if own:
        return slug(own)
    if style:
        return slug(re.sub(r"^(cloth|shield|weapon|sheath|glove|foot|elbow|poleyn)_", "", str(style)))
    if p.get("surface") in SURFACE_STYLES:
        return p["surface"]
    return slug(p.get("material") or "") or "piece"


def base_name(kind: str, params: dict, style=None) -> str:
    st = style_of(kind, params, style)
    return st if kind == "weapon" else f"{slug(kind)}_{st}"   # a weapon is its kind: «sword», not «weapon_sword»


def free_name(base: str, taken) -> str:
    """base, else base_2, base_3… — the first not taken."""
    taken = set(taken)
    if base not in taken:
        return base
    n = 2
    while f"{base}_{n}" in taken:
        n += 1
    return f"{base}_{n}"


# ---- the old layout moved over
def migrate(rigged) -> dict:
    """<stem>_wear_<item>.* next to the model -> <category>/<new item>.*; {old item: new item}. Nothing to do: {}."""
    d, stem = Path(rigged).parent, _stem(rigged)
    pre = f"{stem}_wear_"
    old = sorted({f.name[len(pre):-len(x)] for f in d.glob(f"{glob_escape(pre)}*") for x in SUFFIXES
                  if f.name.endswith(x) and not (x == ".glb" and f.name.endswith(".src.glb"))})
    old = [o for o in old if not o.endswith(".src")]
    if not old:
        _drop_answers(d, stem)
        return {}
    taken = {k for k, _, _ in items_in(d)}
    names, kinds = {}, {}
    for item in old:
        fit = d / f"{pre}{item}.fit.json"
        try:
            js = json.loads(fit.read_text(encoding="utf-8")) if fit.exists() else {}
        except (OSError, ValueError):
            js = {}
        pr = js.get("procedural") or {}
        kind = pr.get("piece") or (js.get("state") or {}).get("part") or "piece"
        base = base_name(kind, pr.get("params") or {}, pr.get("style")) if pr else f"{slug(kind)}_{slug(item)}"
        names[item] = free_name(base, taken)
        taken.add(names[item]); kinds[item] = pr.get("piece") if pr else None
    for item, new in names.items():
        folder = d / category(kinds[item])
        folder.mkdir(exist_ok=True)
        for x in SUFFIXES:
            f = d / f"{pre}{item}{x}"
            if f.exists():
                f.replace(folder / f"{new}{x}")
        fit = folder / f"{new}.fit.json"
        if fit.exists():   # the names inside: its own, its source's, the pieces it was made over
            try:
                js = json.loads(fit.read_text(encoding="utf-8"))
                js["item"], js["src"] = new, f"{new}.src.glb"
                st = js.get("state") or {}
                if isinstance(st.get("under"), list):
                    st["under"] = [names.get(u, u) for u in st["under"]]
                fit.write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
            except (OSError, ValueError):
                pass
    for _, _, fit in items_in(d):   # the pieces moved before (another run) may name these too
        try:
            js = json.loads(fit.read_text(encoding="utf-8"))
            st = js.get("state") or {}
            if isinstance(st.get("under"), list) and any(u in names for u in st["under"]):
                st["under"] = [names.get(u, u) for u in st["under"]]
                fit.write_text(json.dumps(js, ensure_ascii=False, indent=1), encoding="utf-8")
        except (OSError, ValueError):
            pass
    _drop_answers(d, stem)
    return names


def _drop_answers(d: Path, stem: str):
    """The editors' old answers next to the model (<stem>_….wear.json): read long ago, they go."""
    for f in d.glob(f"{glob_escape(stem)}_*.wear.json"):
        f.unlink(missing_ok=True)


def glob_escape(s: str) -> str:
    import glob
    return glob.escape(s)
