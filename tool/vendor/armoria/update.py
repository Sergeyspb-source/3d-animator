"""Armoria (Azgaar): a procedural heraldry generator - its generator and renderer (armoria-api, MIT) for the editor's
«Painting generator», and the charges whose licence lets a game use them freely (CC0 only: the WappenWiki ones are
non-commercial, the CC BY-SA and GFDL ones share alike). Downloads the pinned files, keeps the CC0 charges, writes
source_manifest.json and builds armoria.mjs: the five CommonJS files wrapped as one ES module for the browser, their
two Node calls replaced (a charge read from disk -> fetched from charges/; node-html-parser -> DOMParser).

    python update.py            (run in this folder; needs the network)
"""
import hashlib
import json
import re
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
API = ("Azgaar/armoria-api", "f4c9b191e3540104c780145e42b431cfa636345d")   # app/: the generator and the renderer (MIT)
APP = ("Azgaar/Armoria", "b0bb9b8c37db43e462b90a1e8603e93aae483123")   # public/charges: the charges' SVG
SRC = ("alea", "dataModel", "generator", "renderer", "templates")
FREE = ("creativecommons.org/publicdomain/zero",)   # the charges kept: CC0


def get(url: str) -> bytes:
    import time
    for k in range(5):   # (a dropped connection now and then: again)
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "sf3d-tool"})
            with urllib.request.urlopen(req, timeout=60) as r:
                return r.read()
        except OSError:
            if k == 4:
                raise
            time.sleep(1 + k)


def raw(repo, path):
    return f"https://raw.githubusercontent.com/{repo[0]}/{repo[1]}/{path}"


def main():
    manifest = []
    def keep(rel, url, data):
        f = HERE / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(data)
        manifest.append({"file": rel, "url": url, "sha256": hashlib.sha256(data).hexdigest()})
    for name in SRC:
        url = raw(API, f"app/{name}.js")
        keep(f"src/{name}.js", url, get(url))
    url = raw(API, "LICENSE")
    keep("LICENSE", url, get(url))
    listing = json.loads(get(f"https://api.github.com/repos/{APP[0]}/contents/public/charges?ref={APP[1]}"))
    kept = []
    for f in (HERE / "charges").glob("*.svg") if (HERE / "charges").exists() else []:
        f.unlink()
    for e in listing:
        if not e["name"].endswith(".svg"):
            continue
        url = raw(APP, f"public/charges/{e['name']}")
        data = get(url)
        m = re.search(rb'license="([^"]*)"', data)
        if m and any(x.encode() in m.group(1) for x in FREE):
            keep(f"charges/{e['name']}", url, data)
            kept.append(e["name"][:-4])
    (HERE / "source_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    build(sorted(kept))
    print(f"{len(kept)} CC0 charges of {len(listing)}; armoria.mjs built")


def build(kept):
    """The five CommonJS files as one ES module: a small require() over them, the Node calls replaced."""
    parts = []
    for name in SRC:
        s = (HERE / "src" / f"{name}.js").read_text(encoding="utf-8")
        if name == "renderer":
            s = s.replace('const HTMLParser = require("node-html-parser");\n', "")
            s = s.replace('const fs = require("fs");\n', "")
            s = re.sub(r'const text = fs\.readFileSync\("public/charges/" \+ charge \+ "\.svg", "utf8"\);\s*const root = HTMLParser\.parse\(text\);',
                       'const res = await fetch(CHARGES + charge + ".svg"); if (!res.ok) return "";\n  const text = await res.text();\n'
                       '  const root = new DOMParser().parseFromString(text, "image/svg+xml");', s)
            assert "fs." not in s and "HTMLParser" not in s, "renderer: the Node calls not all replaced"
        parts.append(f"__def({json.dumps(name)}, function (module, exports, require) {{\n{s}\n}});")
    head = ("// Built by update.py from Azgaar/armoria-api (MIT, see LICENSE): do not edit, run update.py\n"
            "let CHARGES = './charges/';\n"
            "export const setCharges = (base) => { CHARGES = base; };\n"
            "const __mods = {};\n"
            "const __def = (name, fn) => { __mods[name] = { fn, exports: null }; };\n"
            "const require = (name) => { const m = __mods[name.replace('./', '')]; if (!m.exports) { const module = { exports: {} }; m.exports = module.exports; m.fn(module, module.exports, require); m.exports = module.exports; } return m.exports; };\n")
    tail = (f"export const AVAILABLE = {json.dumps(kept)};\n"
            "// the generator offered only the charges kept (the others are not here): a type's charges cut to them, a type with\n"
            "// none of them left out\n"
            "export function restrict(names = AVAILABLE) {\n"
            "  const { charges } = require('dataModel'), have = new Set(names);\n"
            "  for (const [type, w] of Object.entries(charges.types)) {\n"
            "    const set = charges[type]; if (!set || typeof set !== 'object') continue;\n"
            "    for (const k of Object.keys(set)) if (!have.has(k)) delete set[k];\n"
            "    if (!Object.keys(set).length) { delete charges.types[type]; delete charges.single[type]; }\n"
            "  }\n"
            "  for (const k of Object.keys(charges.conventional || {})) if (!have.has(k)) delete charges.conventional[k];\n"
            "}\n"
            "export const generate = (...a) => require('generator')(...a);\n"
            "export const draw = (...a) => require('renderer')(...a);\n"
            "export const model = () => require('dataModel');\n")
    (HERE / "armoria.mjs").write_text(head + "\n".join(parts) + "\n" + tail, encoding="utf-8")


if __name__ == "__main__":
    main()
