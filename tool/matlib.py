"""A library of ready materials for the pieces, as an alternative to the procedural look: ambientCG and Poly Haven, both
CC0 (anything may be done with them, a game included) and with open APIs. Searched from the armour editor; a material
chosen is downloaded once (1K JPG: its colour, its normal map in OpenGL's convention, its roughness, its metalness if
it has one) into export/materials/<source>_<id>/ with material.json, its real size (the side of the sample, cm) kept
for the tiling. The editor shows it on the piece, Blender bakes it (blender_armour_gen.node_mat: box-projected by that
size, the wear over it).
"""
import io
import json
import re
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

UA = {"User-Agent": "sf3d-tool"}
ACG = "https://ambientcg.com/api/v2/full_json"
PH = "https://api.polyhaven.com"
_PH_LIST = None   # Poly Haven's textures, fetched once: {id: info}


def _get(url, timeout=60) -> bytes:
    import time
    for k in range(4):   # (a dropped connection now and then: again)
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=timeout) as r:
                return r.read()
        except OSError:
            if k == 3:
                raise
            time.sleep(1 + k)


def _json(url):
    return json.loads(_get(url).decode("utf-8"))


def search(source: str, q: str, limit: int = 24) -> list:
    """[{source, id, name, thumb, size_cm}] for the words q."""
    q = (q or "").strip()
    if source == "polyhaven":
        global _PH_LIST
        if _PH_LIST is None:
            _PH_LIST = _json(f"{PH}/assets?t=textures")
        words = [w for w in re.split(r"\W+", q.lower()) if w]
        def hit(k, a):
            text = " ".join([k, a.get("name", ""), *a.get("categories", []), *a.get("tags", [])]).lower()
            return all(w in text for w in words)
        found = [(k, a) for k, a in _PH_LIST.items() if hit(k, a)]
        found.sort(key=lambda x: -int(x[1].get("download_count") or 0))
        return [{"source": "polyhaven", "id": k, "name": a.get("name", k),
                 "thumb": f"https://cdn.polyhaven.com/asset_img/thumbs/{k}.png?width=256&height=256",
                 "size_cm": round(float((a.get("dimensions") or [1000])[0]) / 10) or 100} for k, a in found[:limit]]
    url = f"{ACG}?" + urllib.parse.urlencode({"type": "Material", "q": q, "limit": limit, "include": "imageData", "sort": "Popular"})
    out = []
    for a in _json(url).get("foundAssets", []):
        out.append({"source": "ambientcg", "id": a["assetId"], "name": a.get("displayName") or a["assetId"],
                    "thumb": (a.get("previewImage") or {}).get("256-PNG", ""), "size_cm": int(a.get("dimensionX") or 0) or 50})
    return out


def get(folder: Path, source: str, mid: str, size_cm: float = 0) -> dict:
    """The material's maps on disk (downloaded the first time): {source, id, name, color, normal, rough, metal?, size_cm}."""
    mid = re.sub(r"[^A-Za-z0-9_-]+", "_", mid)
    d = Path(folder) / f"{source}_{mid}"
    meta = d / "material.json"
    if meta.exists():
        return json.loads(meta.read_text(encoding="utf-8"))
    d.mkdir(parents=True, exist_ok=True)
    out = {"source": source, "id": mid, "name": mid, "size_cm": size_cm or 50}
    if source == "polyhaven":
        files, info = _json(f"{PH}/files/{mid}"), _json(f"{PH}/info/{mid}")
        out["name"] = info.get("name", mid)
        out["size_cm"] = size_cm or round(float((info.get("dimensions") or [1000])[0]) / 10) or 100
        for key, name in (("Diffuse", "color"), ("nor_gl", "normal"), ("Rough", "rough"), ("Metal", "metal")):
            url = (((files.get(key) or {}).get("1k") or {}).get("jpg") or {}).get("url")
            if url:
                (d / f"{name}.jpg").write_bytes(_get(url, 120))
                out[name] = (d / f"{name}.jpg").resolve().as_posix()
    else:
        z = zipfile.ZipFile(io.BytesIO(_get(f"https://ambientcg.com/get?file={mid}_1K-JPG.zip", 180)))
        for suffix, name in (("_Color.jpg", "color"), ("_NormalGL.jpg", "normal"), ("_Roughness.jpg", "rough"), ("_Metalness.jpg", "metal")):
            m = next((n for n in z.namelist() if n.endswith(suffix)), None)
            if m:
                (d / f"{name}.jpg").write_bytes(z.read(m))
                out[name] = (d / f"{name}.jpg").resolve().as_posix()
        out["name"] = re.sub(r"(\D)(\d)", r"\1 \2", mid, count=1)
    if "color" not in out:
        raise RuntimeError(f"{source} {mid}: no colour map")
    meta.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    return out
