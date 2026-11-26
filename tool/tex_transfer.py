"""Texture transfer from a painted copy of a piece into OUR piece's unwrap (ROADMAP stage 5).

A piece made here (procedural armour, clothes, a weapon) has its own unwrap, masks, skin and fitting. To repaint it,
a copy of it is painted elsewhere - Hunyuan3D-Paint (our mesh, its own unwrap), TRELLIS.2 or Meshy (a new mesh from
a picture of the piece, normalised) - and its colour, metal and roughness are baked back into our unwrap
(blender_tex_transfer.py: the copy put over the piece by bounding boxes + ICP with scale, selected -> active per slot).
Here: the baked passes turned into the GLB's pictures - colour to sRGB, the texels no ray reached and the background
between islands filled from what was hit (tex_pad), metal/roughness as a glTF metallicRoughness map (G rough, B metal;
a pass the copy has no map for keeps the piece's own values) - swapped into the GLB itself: geometry, skin, weights,
morphs and the rest of the file stay byte for byte.

    D:\\conda\\envs\\sf3d\\python.exe tool/tex_transfer.py <piece.glb> <painted copy.glb> <out.glb>
        [--align auto|none] [--rotate-y DEG] [--keep-metal] [--keep-rough] [--also <piece.src.glb>]
"""
import argparse
import io
import json
import shutil
import struct
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
import tex_pad as TP  # noqa: E402


# ---------------------------------------------------------------- GLB in and out
def read_glb(path):
    raw = Path(path).read_bytes()
    magic, ver, _ = struct.unpack_from("<III", raw, 0)
    if magic != 0x46546C67:
        raise ValueError(f"not a GLB: {path}")
    jl = struct.unpack_from("<I", raw, 12)[0]
    J = json.loads(raw[20:20 + jl].decode("utf-8"))
    o = 20 + jl
    BIN = b""
    if o < len(raw):
        bl = struct.unpack_from("<I", raw, o)[0]
        BIN = raw[o + 8:o + 8 + bl]
    views = [BIN[v.get("byteOffset", 0):v.get("byteOffset", 0) + v["byteLength"]] for v in J.get("bufferViews", [])]
    return J, views


def write_glb(path, J, views):
    out = bytearray()
    for v, data in zip(J["bufferViews"], views):
        out += b"\0" * ((-len(out)) % 4)
        v["byteOffset"] = len(out)
        v["byteLength"] = len(data)
        out += data
    out += b"\0" * ((-len(out)) % 4)
    J["buffers"][0]["byteLength"] = len(out)
    js = json.dumps(J, separators=(",", ":")).encode("utf-8")
    js += b" " * ((-len(js)) % 4)
    Path(path).write_bytes(struct.pack("<III", 0x46546C67, 2, 12 + 8 + len(js) + 8 + len(out))
                           + struct.pack("<II", len(js), 0x4E4F534A) + js
                           + struct.pack("<II", len(out), 0x004E4942) + bytes(out))


def image_of(J, views, tex_info):
    """(image index, PIL image) of a textureInfo, or (None, None)"""
    if not tex_info or "index" not in tex_info:
        return None, None
    tex = J["textures"][tex_info["index"]]
    src = tex.get("source")
    for ext in (tex.get("extensions") or {}).values():
        src = ext.get("source", src)
    img = J["images"][src]
    if "bufferView" not in img:
        return None, None
    return src, Image.open(io.BytesIO(views[img["bufferView"]]))


def put_image(J, views, mat, slot, pil, fmt):
    """mat's textureInfo `slot` (baseColorTexture / metallicRoughnessTexture) pointed at pil: the picture replaced
    in place when nothing else uses it, else a new image + texture"""
    pbr = mat.setdefault("pbrMetallicRoughness", {})
    buf = io.BytesIO()
    pil.save(buf, fmt, **({"quality": 92} if fmt == "JPEG" else {}))
    data, mime = buf.getvalue(), "image/" + fmt.lower()
    info = pbr.get(slot)
    if info is not None:
        src, _ = image_of(J, views, info)
        users = sum(1 for m in J.get("materials", []) for k in ("baseColorTexture", "metallicRoughnessTexture")
                    if ((m.get("pbrMetallicRoughness") or {}).get(k) or {}).get("index") is not None
                    and image_of(J, views, m["pbrMetallicRoughness"][k])[0] == src)
        users += sum(1 for m in J.get("materials", []) for k in ("normalTexture", "occlusionTexture", "emissiveTexture")
                     if (m.get(k) or {}).get("index") is not None and image_of(J, views, m[k])[0] == src)
        tex = J["textures"][info["index"]]
        if src is not None and users == 1 and "extensions" not in tex:
            img = J["images"][src]
            views[img["bufferView"]] = data
            img["mimeType"] = mime
            return
    J.setdefault("bufferViews", []).append({"buffer": 0, "byteLength": len(data)})
    views.append(data)
    J.setdefault("images", []).append({"bufferView": len(J["bufferViews"]) - 1, "mimeType": mime})
    sampler = {}
    if info is not None and "sampler" in J["textures"][info["index"]]:
        sampler = {"sampler": J["textures"][info["index"]]["sampler"]}
    J.setdefault("textures", []).append({"source": len(J["images"]) - 1, **sampler})
    pbr[slot] = {**(info or {}), "index": len(J["textures"]) - 1}


def to_srgb(lin):
    lin = np.clip(lin, 0, 1)
    return np.where(lin <= 0.0031308, lin * 12.92, 1.055 * np.power(lin, 1 / 2.4) - 0.055)


# ---------------------------------------------------------------- the transfer
def transfer(target, source, out, align="auto", rotate_y=0.0, keep_metal=False, keep_rough=False, blender=None,
             work=None, log=print):
    """-> stats {materials: {name: {hit, colour, metal, rough}}, fit_error, scale}"""
    cfg_path = ROOT / "config.json"
    cfg = json.loads((cfg_path if cfg_path.exists() else ROOT / "config.example.json").read_text(encoding="utf-8-sig"))
    blender = blender or cfg["blender_exe"]
    J, views = read_glb(target)
    mats = J.get("materials", [])
    if not mats:
        raise RuntimeError("the piece has no materials")
    tmp = Path(work or tempfile.mkdtemp(prefix="tex_transfer_", dir=r"D:\conda\tmp" if Path(r"D:\conda\tmp").exists() else None))
    tmp.mkdir(parents=True, exist_ok=True)
    # the piece's materials named for the bake (their real names may repeat or be missing)
    J2 = json.loads(json.dumps(J))
    sizes = {}
    for i, m in enumerate(J2["materials"]):
        name = f"sf3dmat_{i}"
        m["name"] = name
        _, im = image_of(J, views, (m.get("pbrMetallicRoughness") or {}).get("baseColorTexture"))
        sizes[name] = max(im.size) if im is not None else 1024
    named = tmp / "target_named.glb"
    write_glb(named, J2, list(views))
    passes = tmp / "passes"
    cmd = [blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_tex_transfer.py"), "--", str(named),
           str(source), str(passes), f"align={align}", f"rotate_y={rotate_y}",
           "sizes=" + ",".join(f"{k}:{v}" for k, v in sizes.items())]
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace",
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if "TT_OK" not in r.stdout:
        raise RuntimeError("the bake failed: " + (r.stdout + r.stderr)[-1500:])
    info = json.loads((passes / "transfer.json").read_text(encoding="utf-8"))
    stats = {"fit_error": info["fit_error"], "scale": info["scale"], "passes": info["passes"], "materials": {}}
    log(f"fit: error {info['fit_error'] if info['fit_error'] is None else round(info['fit_error'] * 100, 2)}% of the "
        f"size, scale {info['scale']:.3f}, passes {info['passes']}")
    for i, m in enumerate(mats):
        name = f"sf3dmat_{i}"
        f = lambda k: passes / f"{name}_{k}.npy"  # noqa: E731
        if not f("color").exists():
            continue
        cover, hit = np.load(f("cover")), np.load(f("hit"))
        got = hit & cover
        share = float(got.sum() / max(cover.sum(), 1))
        st = {"hit": round(share, 3)}
        if share < 0.05:
            log(f"{m.get('name') or name}: the copy was not found over this part ({share:.0%}), left as it was")
            st["skipped"] = True
            stats["materials"][m.get("name") or name] = st
            continue
        n = cover.shape[0]
        # colour: what was hit kept, the rest (missed texels, background) from the nearest hit
        col = TP.pad_fill(np.load(f("color")).astype(np.float32), got)
        rgb = (to_srgb(col) * 255 + .5).astype(np.uint8)
        pbr = m.setdefault("pbrMetallicRoughness", {})
        _, old_col = image_of(J, views, pbr.get("baseColorTexture"))
        if m.get("alphaMode", "OPAQUE") != "OPAQUE" and old_col is not None and "A" in old_col.getbands():
            # (hair, a mail's rings: the piece's own cut-out stays, only its colour is new)
            a = np.asarray(old_col.getchannel("A").resize((n, n), Image.BILINEAR))
            put_image(J, views, m, "baseColorTexture", Image.fromarray(np.dstack([rgb, a]), "RGBA"), "PNG")
        else:
            put_image(J, views, m, "baseColorTexture", Image.fromarray(rgb, "RGB"), "JPEG")
        pbr.pop("baseColorFactor", None)   # (the colour is in the picture now)
        st["colour"] = True
        do_metal = "metal" in info["passes"] and not keep_metal
        do_rough = "rough" in info["passes"] and not keep_rough
        if do_metal or do_rough:
            # the piece's own metal / roughness, as values per texel (factor x its map), for the pass not taken
            _, mr_old = image_of(J, views, pbr.get("metallicRoughnessTexture"))
            mf, rf = float(pbr.get("metallicFactor", 1.0)), float(pbr.get("roughnessFactor", 1.0))
            if mr_old is not None:
                a = np.asarray(mr_old.convert("RGB").resize((n, n), Image.BILINEAR), np.float32) / 255
                old_rough, old_metal = a[..., 1] * rf, a[..., 2] * mf
            else:
                old_rough, old_metal = np.full((n, n), rf, np.float32), np.full((n, n), mf, np.float32)
            metal = TP.pad_fill(np.load(f("metal")).astype(np.float32), got) if do_metal else old_metal
            rough = TP.pad_fill(np.load(f("rough")).astype(np.float32), got) if do_rough else old_rough
            mr = np.stack([np.ones((n, n), np.float32), np.clip(rough, 0, 1), np.clip(metal, 0, 1)], -1)
            put_image(J, views, m, "metallicRoughnessTexture", Image.fromarray((mr * 255 + .5).astype(np.uint8), "RGB"), "PNG")
            pbr["metallicFactor"] = pbr["roughnessFactor"] = 1.0
            st["metal"], st["rough"] = do_metal, do_rough
            st["metal_mean"] = round(float(metal[cover].mean()), 3)
            st["rough_mean"] = round(float(rough[cover].mean()), 3)
        stats["materials"][m.get("name") or name] = st
        log(f"{m.get('name') or name}: {share:.0%} of its texels hit the copy; colour"
            + (", metal" if st.get("metal") else "") + (", roughness" if st.get("rough") else ""))
    write_glb(out, J, views)
    if not work:
        shutil.rmtree(tmp, ignore_errors=True)
    return stats


def transfer_piece(glb, source, also=(), **kw):
    """a fitted piece and its source copy (.src.glb, same unwrap) repainted alike, each in place (a .bak beside it)"""
    res = {}
    for p in [glb, *also]:
        p = Path(p)
        if not p.exists():
            continue
        bak = p.with_suffix(".glb.bak")
        if not bak.exists():
            shutil.copy2(p, bak)
        res[str(p)] = transfer(p, source, p, **kw)
    return res


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("piece")
    ap.add_argument("copy")
    ap.add_argument("out")
    ap.add_argument("--align", choices=["auto", "none"], default="auto",
                    help="auto: boxes + ICP (a generator's normalised copy); none: the copy already sits on the piece")
    ap.add_argument("--rotate-y", type=float, default=0.0, help="the copy turned about the vertical before fitting")
    ap.add_argument("--keep-metal", action="store_true", help="keep the piece's own metal")
    ap.add_argument("--keep-rough", action="store_true", help="keep the piece's own roughness")
    ap.add_argument("--work", help="keep the bake's passes in this folder")
    a = ap.parse_args()
    s = transfer(a.piece, a.copy, a.out, a.align, a.rotate_y, a.keep_metal, a.keep_rough, work=a.work)
    print(json.dumps(s, indent=1))
