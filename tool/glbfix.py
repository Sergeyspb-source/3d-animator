"""Small in-place fixes of GLB material JSON (no mesh changes)."""
import json
import struct
from pathlib import Path


def set_metallic(path, metallic=0.2, roughness=None):
    """glTF assumes metallicFactor 1 when it is absent: a model without the field renders as a black mirror"""
    p = Path(path)
    b = p.read_bytes()
    jlen = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + jlen])
    rest = b[20 + jlen:]
    changed = 0
    for m in j.get("materials", []):
        pbr = m.setdefault("pbrMetallicRoughness", {})
        if "metallicFactor" not in pbr or pbr["metallicFactor"] > metallic:
            pbr["metallicFactor"] = metallic
            changed += 1
        if roughness is not None:
            pbr["roughnessFactor"] = roughness
    data = json.dumps(j, separators=(",", ":")).encode("utf-8")
    data += b" " * ((4 - len(data) % 4) % 4)
    out = b[:8] + struct.pack("<I", 12 + 8 + len(data) + len(rest)) + struct.pack("<I", len(data)) + b[16:20] + data + rest
    p.write_bytes(out)
    return changed
