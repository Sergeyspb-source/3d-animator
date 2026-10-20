"""Mixamo FBX animations (without skin) -> a rigged GLB with named clips, plus a viewer page for the app.

    rows = table_rows(folder)                      # one row per FBX, settings from <folder>/map.json
    save_map(folder, rows)                         # write the table back to map.json
    info = retarget(blender, model_glb, folder, out_glb)   # Blender: copy the FBX motions onto the model's skeleton
    html = viewer_html(out_glb, info)              # self-contained three.js page (GLB embedded), for an iframe srcdoc

The FBX and the model must share Mixamo bone names (mixamorig:Hips ...). map.json keys are file names without .fbx;
values: name (clip name in Godot), loop, speed (1 = as authored), inplace (remove ground travel), group (list heading).
"""
import base64
import io
import json
import re
import struct
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent
NOFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)
HEADERS = ["Файл", "Имя клипа", "Цикл", "Скорость", "На месте", "Группа"]
GROUPS = [("sword and shield", "Меч и щит"), ("great sword", "Двуручный меч")]
LOOP_WORDS = ("idle", "walk", "run", "walking", "running", "strafe")


def _slug(text):
    s = re.sub(r"[^0-9A-Za-z]+", "_", text).strip("_")
    return s[:40] or "clip"


def _is_mirror(stem):
    """a strafe file whose name ends with Right is the mirror image of the matching Left file (the retarget flips it)"""
    low = stem.lower()
    return "strafe" in low and low.endswith("right")


def _guess(stem):
    low = stem.lower()
    group = next((g for k, g in GROUPS if k in low), "Прочее")
    loop = any(w in low.split() or low.endswith(w) for w in LOOP_WORDS)
    return dict(name=_slug(stem), loop=loop, speed=1.0, inplace="death" not in low, group=group, **({"mirror": True} if _is_mirror(stem) else {}))


def table_rows(folder):
    folder = Path(folder)
    saved = {}
    if (folder / "map.json").exists():
        try:
            saved = json.loads((folder / "map.json").read_text(encoding="utf-8-sig"))
        except Exception:  # noqa: BLE001
            saved = {}
    rows = []
    for f in sorted(folder.glob("*.fbx")):
        spec = _guess(f.stem)
        spec.update(saved.get(f.stem, {}))
        rows.append([f.stem, spec["name"], bool(spec.get("loop")), float(spec.get("speed", 1.0)),
                     bool(spec.get("inplace", True)), spec.get("group", "Прочее")])
    return rows


def rows_to_map(rows):
    out = {}
    for r in rows:
        if r is None or len(r) < 6 or not str(r[0]).strip():
            continue
        try:
            speed = float(r[3])
        except (TypeError, ValueError):
            speed = 1.0
        out[str(r[0])] = dict(name=_slug(str(r[1])) if str(r[1]).strip() else _slug(str(r[0])), loop=bool(r[2]),
                              speed=speed if speed > 0 else 1.0, inplace=bool(r[4]), group=str(r[5] or "Прочее"))
        if _is_mirror(str(r[0])):
            out[str(r[0])]["mirror"] = True      # a copy of another clip's file named "... Right" is its mirror image
    return out


def save_map(folder, rows):
    m = rows_to_map(rows)
    (Path(folder) / "map.json").write_text(json.dumps(m, indent=1, ensure_ascii=False), encoding="utf-8")
    return m


def retarget(blender, model, folder, out):
    out = Path(out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.unlink(missing_ok=True)
    r = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_retarget_fbx.py"), "--", str(model), str(out),
                        str(Path(folder) / "map.json")], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=3600, creationflags=NOFLAGS)
    text = r.stdout + r.stderr
    if not out.exists():
        err = [x for x in text.splitlines() if "Error" in x or "Traceback" in x]
        raise RuntimeError("перенос не удался: " + (err[-1] if err else text[-400:]))
    info = json.loads(Path(str(out) + ".json").read_text(encoding="utf-8"))
    rest = [x for x in text.splitlines() if x.startswith("RETARGET_REST")]
    miss = sorted({m for c in info for m in c.get("missing", [])})
    return dict(clips=info, rest=rest[0] if rest else "", missing=miss, model=str(model))


def shrink_glb(src, max_side=1024, quality=84):
    """the same GLB with textures re-encoded as JPEG no wider than max_side (the viewer page stays small)"""
    from PIL import Image
    b = Path(src).read_bytes()
    jl = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + jl])
    bl = struct.unpack("<I", b[20 + jl:24 + jl])[0]
    bin0 = b[28 + jl:28 + jl + bl]
    img_views = {im["bufferView"] for im in j.get("images", []) if "bufferView" in im}
    parts, off = [], 0
    for i, bv in enumerate(j["bufferViews"]):
        data = bin0[bv.get("byteOffset", 0):bv.get("byteOffset", 0) + bv["byteLength"]]
        if i in img_views:
            im = Image.open(io.BytesIO(data)).convert("RGB")
            if max(im.size) > max_side:
                k = max_side / max(im.size)
                im = im.resize((round(im.width * k), round(im.height * k)), Image.LANCZOS)
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=quality)
            data = buf.getvalue()
            for img in j["images"]:
                if img.get("bufferView") == i:
                    img["mimeType"] = "image/jpeg"
        pad = (4 - len(data) % 4) % 4
        bv["byteOffset"], bv["byteLength"] = off, len(data)
        parts.append(data + b"\0" * pad)
        off += len(data) + pad
    j["buffers"][0]["byteLength"] = off
    binout = b"".join(parts)
    js = json.dumps(j, separators=(",", ":")).encode()
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + 8 + len(binout)
    return (b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I", len(js)) + b"JSON" + js
            + struct.pack("<I", len(binout)) + b"BIN\0" + binout)


# Held weapon presets for the viewer (numbers are those of the game's WeaponProfile / skeleton specs; rotations are Godot
# Euler YXZ degrees in the bone's own frame, scale/grip/offset in rig units).
WEAPON_SETS = {
    "Нет": [],
    "Гоблин: меч и щит": [
        dict(model="weapon_rusty_sword", bone="RightHand", scale=0.30, rot=[33.3, 131.6, 71.1], grip=[0, -0.62, 0], palm=True),
        dict(model="weapon_rusty_shield", bone="LeftForeArm", scale=0.17, rot=[-13.5, -2.1, -104.6], grip=[0, 0, 0],
             offset=[0, 0.085, 0])],
    "Гоблин: двуручный меч": [
        dict(model="weapon_rusty_greatsword", bone="RightHand", scale=0.45, rot=[54.7, -8.9, -73.8], grip=[0, -0.60, 0], palm=True)],
    "Скелет-воин: меч и щит": [
        dict(model="weapon_rusty_sword", bone="RightHand", scale=0.5, rot=[-18.3, 87.2, -71.2], grip=[0, -0.62, 0], palm=True),
        dict(model="weapon_rusty_shield", bone="LeftForeArm", scale=0.38, rot=[-13.5, 69.7, -104.6], grip=[0, 0, 0],
             offset=[0, 0.127, 0])],
    "Скелет-рыцарь: двуручный меч": [
        dict(model="weapon_rusty_greatsword", bone="RightHand", scale=0.8, rot=[-8.1, 125.1, -78.0], grip=[0, -0.60, 0], palm=True)],
}


def _weapon_glb(name):
    for base in (Path(r"D:/My projects/game-project-godot/assets/models/weapons"),
                 ROOT.parent / "export" / "item" / name):
        f = base / f"{name}.glb" if base.name != name else base / f"{name}.glb"
        if f.exists():
            return f
    raise FileNotFoundError(name)


def _weapons_json(weapon_set):
    out = []
    for w in WEAPON_SETS.get(weapon_set or "Нет", []):
        from glbfix import set_metallic  # noqa: PLC0415  (the exported item GLBs lack metallicFactor: they render as mirrors)
        import tempfile  # noqa: PLC0415
        src = _weapon_glb(w["model"])
        tmp = Path(tempfile.gettempdir()) / f"viewer_{src.name}"
        tmp.write_bytes(src.read_bytes())
        set_metallic(tmp, 0.25, 0.85)
        out.append(dict(bone=w["bone"], scale=w["scale"], rot=w["rot"], grip=w["grip"], offset=w.get("offset", [0, 0, 0]),
                        palm=bool(w.get("palm")), glb=base64.b64encode(shrink_glb(tmp, 512)).decode()))
    return json.dumps(out)


def viewer_html(glb, info, map_rows=None, weapon_set=None):
    """standalone page with the GLB embedded; clips come from `info` (retarget result) and the table (labels/groups)"""
    spec = rows_to_map(map_rows) if map_rows else {}
    by_name = {v["name"]: v for v in spec.values()}
    clips = []
    for c in info["clips"]:
        s = by_name.get(c["name"], {})
        clips.append(dict(id=c["name"], label=c["name"], group=s.get("group", "Прочее"), loop=bool(c.get("loop"))))
    clips.sort(key=lambda c: ([g for _, g in GROUPS].index(c["group"]) if c["group"] in [g for _, g in GROUPS] else 99))
    tpl = (ROOT / "viewer_anim.html").read_text(encoding="utf-8")
    data = base64.b64encode(shrink_glb(glb)).decode()
    return (tpl.replace("@@DATA@@", json.dumps(dict(clips=clips), ensure_ascii=False)).replace("@@GLB@@", data)
            .replace("@@WEAPONS@@", _weapons_json(weapon_set)))
