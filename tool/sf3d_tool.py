"""Image -> game-ready GLB wrapper around Stable Fast 3D.

Usage (via sf3d-tool.bat):
    sf3d-tool.bat generate <image|folder> --category prop [--name crate] [--height 1.2]
    sf3d-tool.bat post <file.glb> --category building [--height 6]

Pipeline: background removal (CPU) -> SF3D -> post-process (pivot, scale, material
fix, drop the empty 'world' node) -> <export_dir>/<category>/<name>/<name>.glb
The Godot project is never touched: point export_dir in config.json at it later.
"""
import argparse
import json
import math
import re
import shutil
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SF3D_SRC = ROOT.parent / "sf3d-src"
sys.path.insert(0, str(SF3D_SRC))

IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp"}


def load_config() -> dict:
    path = ROOT / "config.json"
    if not path.exists():  # fresh clone: start from the committed template
        path = ROOT / "config.example.json"
    return json.loads(path.read_text(encoding="utf-8-sig"))  # tolerate a BOM


def slug(text: str) -> str:
    return re.sub(r"[^a-z0-9_]+", "_", text.lower()).strip("_") or "asset"


def collect_images(paths: list[str]) -> list[Path]:
    found = []
    for p in map(Path, paths):
        if p.is_dir():
            found += sorted(f for f in p.iterdir() if f.suffix.lower() in IMAGE_EXT)
        elif p.suffix.lower() in IMAGE_EXT:
            found.append(p)
        else:
            print(f"skip (not an image): {p}")
    return found


def tune_colors(tex, saturation: float = 1.0, brightness: float = 1.0):
    """Manual grade of the albedo: scale Lab chroma (saturation) and lightness (brightness)."""
    import numpy as np
    from PIL import Image
    from skimage import color

    if abs(saturation - 1) < 1e-3 and abs(brightness - 1) < 1e-3:
        return tex
    lab = color.rgb2lab(np.asarray(tex.convert("RGB")) / 255.0)
    lab[..., 0] = np.clip(lab[..., 0] * brightness, 0, 100)
    lab[..., 1:] *= saturation
    return Image.fromarray((np.clip(color.lab2rgb(lab), 0, 1) * 255 + 0.5).astype(np.uint8))


def match_colors(tex, mesh, ref_paths, strength: float):
    """Pull the texture's colour statistics toward those of the reference images (Reinhard transfer in Lab).

    Only texels covered by UV islands are measured, and only opaque pixels of the references (the
    background-removed images the model was generated from). strength 0 = untouched, 1 = full transfer.
    """
    import numpy as np
    from PIL import Image, ImageDraw
    from skimage import color

    refs = []
    for p in ref_paths:
        im = Image.open(p).convert("RGBA")
        a = np.asarray(im)
        px = a[a[..., 3] > 200][:, :3]
        if len(px):
            refs.append(px)
    uv = getattr(mesh.visual, "uv", None)
    if not refs or uv is None or strength <= 0:
        return tex
    ref = np.concatenate(refs)
    ref = ref[np.random.default_rng(0).choice(len(ref), min(len(ref), 200_000), replace=False)]

    rgb = np.asarray(tex.convert("RGB"))
    H, W = rgb.shape[:2]
    mask_img = Image.new("L", (W, H), 0)
    draw = ImageDraw.Draw(mask_img)
    for tri in uv[mesh.faces]:
        draw.polygon([(float(u) * (W - 1), (1 - float(v)) * (H - 1)) for u, v in tri], fill=255)
    mask = np.asarray(mask_img) > 0
    if mask.sum() < 1000:
        return tex

    lab_ref = color.rgb2lab(ref.reshape(-1, 1, 3) / 255.0).reshape(-1, 3)
    lab_tex = color.rgb2lab(rgb / 255.0)
    used = lab_tex[mask]
    mu_t, sd_t = used.mean(0), used.std(0) + 1e-6
    mu_r, sd_r = lab_ref.mean(0), lab_ref.std(0) + 1e-6
    gain = np.clip(sd_r / sd_t, 0.6, 1.6)
    moved = (lab_tex - mu_t) * gain + mu_r
    out = lab_tex + strength * (moved - lab_tex)
    out_rgb = np.clip(color.lab2rgb(out), 0, 1)
    return Image.fromarray((out_rgb * 255 + 0.5).astype(np.uint8))


def render_previews(glb: Path, work: Path, icon_dest: Path, cfg: dict) -> dict:
    """Headless Blender: 4-view contact sheet (kept in work/) and a 256 px inventory icon next to the GLB."""
    import subprocess

    from PIL import Image

    blender = cfg.get("blender_exe")
    if not blender or not Path(blender).exists():
        raise RuntimeError("blender_exe in config.json is not set or not found")
    out = work / "preview"
    out.mkdir(parents=True, exist_ok=True)
    r = subprocess.run(
        [blender, "-b", "-P", str(ROOT / "blender_preview_script.py"), "--", str(glb), str(out), "512"],
        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=300,
        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if "PREVIEW_OK" not in r.stdout:
        raise RuntimeError((r.stdout + r.stderr)[-400:])
    views = [Image.open(out / f"view_{n}.png").convert("RGB").resize((384, 384), Image.LANCZOS)
             for n in ("front", "right", "back", "left")]
    sheet = Image.new("RGB", (384 * 4, 384))
    for k, v in enumerate(views):
        sheet.paste(v, (k * 384, 0))
    sheet.save(work / "preview.png")
    icon = Image.open(out / "icon.png").convert("RGBA")
    box = icon.getbbox() or (0, 0, *icon.size)
    icon = icon.crop(box)
    side = int(max(icon.size) * 1.12)  # square canvas with a small margin
    canvas = Image.new("RGBA", (side, side), (0, 0, 0, 0))
    canvas.paste(icon, ((side - icon.width) // 2, (side - icon.height) // 2), icon)
    canvas.resize((256, 256), Image.LANCZOS).save(icon_dest)
    return {"preview": str(work / "preview.png"), "icon": str(icon_dest)}


def make_collision(meshes, mode: str, faces: int):
    """Collision proxy from the visual meshes (already scaled and positioned).

    'convex'     -> convex hull, for props and inventory items (RigidBody-friendly)
    'simplified' -> heavily decimated concave mesh, for static buildings
    """
    import trimesh

    pts = trimesh.util.concatenate([trimesh.Trimesh(m.vertices, m.faces, process=False) for m in meshes])
    if mode == "convex":
        return pts.convex_hull
    if mode == "simplified":
        pts.merge_vertices()
        pts.update_faces(pts.nondegenerate_faces())
        pts.remove_unreferenced_vertices()
        import fast_simplification

        target = min(int(faces), len(pts.faces))
        v, f = fast_simplification.simplify(
            pts.vertices.astype("float32"), pts.faces.astype("int32"),
            target_reduction=max(0.0, 1.0 - target / len(pts.faces)))
        return trimesh.Trimesh(v, f, process=True)
    raise ValueError(f"unknown collision mode: {mode}")


def postprocess(src: Path, dst: Path, preset: dict, height, pivot, metallic, roughness,
                width=None, depth=None, collision=None, collision_faces=800, rotate_y=0.0,
                color_refs=None, color_strength=0.0, saturation=1.0, brightness=1.0,
                materials=None, material_k=6, category=None) -> dict:
    """Normalise a GLB: scale, pivot, material factors. Returns a stats dict.

    height scales uniformly (Y is up). width / depth (metres, X / Z extents) then stretch the model
    non-uniformly; use them to fix footprint proportions. None or 0 leaves that axis alone.

    collision: None | 'convex' | 'simplified' (None falls back to the category preset). A proxy mesh is
    added as an extra node named '<name>-convcolonly' / '<name>-colonly'; Godot turns such nodes into a
    StaticBody3D with the matching shape on import and drops the visual mesh.
    """
    import numpy as np
    import trimesh

    scene = trimesh.load(str(src), force="scene")
    meshes = [g for g in scene.geometry.values() if isinstance(g, trimesh.Trimesh)]
    if not meshes:
        raise RuntimeError(f"no mesh in {src}")
    # Bake the scene graph into the meshes and rebuild a clean single-node scene,
    # which drops the empty 'world' node the exporter leaves behind.
    merged = [m.copy() for m in scene.dump()]
    if rotate_y:
        # SF3D models face -Z; glTF (and Hunyuan output) face +Z. Turn them so every asset agrees.
        rot = trimesh.transformations.rotation_matrix(math.radians(rotate_y), [0, 1, 0])
        for m in merged:
            m.apply_transform(rot)
    height = height if height is not None else preset.get("height_m")
    pivot = pivot or preset.get("pivot", "center")
    metallic = metallic if metallic is not None else preset.get("metallic")
    roughness = roughness if roughness is not None else preset.get("roughness")

    lo = np.min([m.bounds[0] for m in merged], axis=0)
    hi = np.max([m.bounds[1] for m in merged], axis=0)
    uniform = (height / (hi[1] - lo[1])) if height else 1.0  # Y is up in glTF
    lo, hi = lo * uniform, hi * uniform
    # per-axis factors on top of the uniform scale: [x, y, z]
    stretch = np.array([(width / (hi[0] - lo[0])) if width else 1.0, 1.0,
                        (depth / (hi[2] - lo[2])) if depth else 1.0])
    scale = uniform * stretch
    lo, hi = lo * stretch, hi * stretch
    if pivot == "bottom":
        offset = np.array([-(lo[0] + hi[0]) / 2, -lo[1], -(lo[2] + hi[2]) / 2])
    else:
        offset = -(lo + hi) / 2

    out = trimesh.Scene(base_frame=dst.stem)  # root node named after the asset, not 'world'
    material_report = []
    for i, m in enumerate(merged):
        m.apply_scale(scale)
        m.apply_translation(offset)
        mat = getattr(m.visual, "material", None)
        if mat is not None and hasattr(mat, "metallicFactor"):
            if metallic is not None:
                mat.metallicFactor = float(metallic)
            if roughness is not None:
                mat.roughnessFactor = float(roughness)
            base = getattr(mat, "baseColorTexture", None)
            if materials and base is not None and getattr(m.visual, "uv", None) is not None:
                # recognise materials on the original albedo, then write a glTF metallicRoughness map
                import materials as MT

                an = MT.analyze(base, m.visual.uv, m.faces, k=material_k, category=category)
                names = [s for s, _ in an["suggestions"]] if materials == "auto" else list(materials)
                names = (names + [names[-1] if names else "other"] * an["k"])[:an["k"]]
                mat.metallicRoughnessTexture = MT.build_maps(an, names)
                mat.metallicFactor = mat.roughnessFactor = 1.0  # factors multiply the map, keep it as is
                material_report = [dict(cluster=j + 1, share=round(st["share"], 3), material=names[j],
                                        label=MT.MATERIALS[names[j]][0], confidence=round(an["suggestions"][j][1], 2))
                                   for j, st in enumerate(an["stats"])]
            # trimesh writes PNG unless the image says otherwise; JPEG is ~4x smaller
            for attr in ("baseColorTexture", "normalTexture"):
                tex = getattr(mat, attr, None)
                if tex is not None:
                    if attr == "baseColorTexture" and color_refs and color_strength > 0:
                        tex = match_colors(tex, m, color_refs, color_strength)
                    if attr == "baseColorTexture":
                        tex = tune_colors(tex, saturation, brightness)
                    tex = tex.convert("RGB")
                    tex.format = "JPEG"
                    setattr(mat, attr, tex)
        mesh_name = f"{dst.stem}_mesh" if len(merged) == 1 else f"{dst.stem}_mesh{i}"
        out.add_geometry(m, node_name=mesh_name, geom_name=mesh_name)
    collision = collision or preset.get("collision")
    col_faces = 0
    if collision and collision != "none":
        col = make_collision(merged, collision, collision_faces)
        col_faces = int(len(col.faces))
        suffix = "-convcolonly" if collision == "convex" else "-colonly"
        out.add_geometry(col, node_name=f"{dst.stem}{suffix}", geom_name=f"{dst.stem}{suffix}")
    dst.parent.mkdir(parents=True, exist_ok=True)
    out.export(str(dst), include_normals=True)

    size = (hi - lo)
    return {
        "size_m": [round(float(v), 3) for v in size],
        "vertices": int(sum(len(m.vertices) for m in merged)),
        "faces": int(sum(len(m.faces) for m in merged)),
        "pivot": pivot,
        "scale_applied": [round(float(v), 4) for v in np.broadcast_to(scale, 3)],
        "collision": collision if collision and collision != "none" else None,
        "collision_faces": col_faces,
        "materials": material_report,
    }


def cmd_generate(args, cfg):
    import rembg
    import torch
    from PIL import Image

    from sf3d.system import SF3D
    from sf3d.utils import get_device, remove_background, resize_foreground

    images = collect_images(args.input)
    if not images:
        sys.exit("no images found")
    preset = cfg["categories"][args.category]
    device = get_device()
    if device == "cpu":
        print("WARNING: no CUDA - texture baking will fail")

    # Prepare all inputs first (CPU), so the GPU model is loaded only when needed.
    jobs = []
    session = None
    for img_path in images:
        name = slug(args.name if (args.name and len(images) == 1) else img_path.stem)
        work = Path(cfg["work_dir"]) / args.category / name
        final = Path(cfg["export_dir"]) / args.category / name / f"{name}.glb"
        if final.exists() and not args.force:
            print(f"skip {name}: already exported (use --force)")
            continue
        work.mkdir(parents=True, exist_ok=True)
        shutil.copy2(img_path, work / f"source{img_path.suffix.lower()}")
        image = Image.open(img_path).convert("RGBA")
        if not args.no_remove_bg:
            session = session or rembg.new_session(providers=["CPUExecutionProvider"])
            image = remove_background(image, session)
        image = resize_foreground(image, args.foreground_ratio or cfg["foreground_ratio"])
        image.save(work / "input.png")
        jobs.append((name, img_path, work, final, image))
    if not jobs:
        return

    model = SF3D.from_pretrained(
        "stabilityai/stable-fast-3d", config_name="config.yaml", weight_name="model.safetensors"
    )
    model.to(device)
    model.eval()

    for name, img_path, work, final, image in jobs:
        t0 = time.time()
        torch.cuda.reset_peak_memory_stats()
        with torch.no_grad(), torch.autocast(device_type="cuda", dtype=torch.bfloat16):
            mesh, _ = model.run_image(
                [image],
                bake_resolution=args.texture_resolution or cfg["texture_resolution"],
                remesh=args.remesh,
                vertex_count=args.vertices,
            )
        peak = torch.cuda.max_memory_allocated() / 1024**2
        raw = work / "raw.glb"
        mesh.export(str(raw), include_normals=True)
        stats = postprocess(raw, final, preset, args.height, args.pivot, args.metallic, args.roughness,
                            args.width, args.depth, args.collision, cfg.get("collision_faces", 800),
                            rotate_y=180.0,  # SF3D output faces -Z
                            saturation=args.saturation, brightness=args.brightness,
                            materials="auto" if args.materials else None, category=args.category)
        stats.update(
            source=str(img_path),
            category=args.category,
            seconds=round(time.time() - t0, 1),
            peak_vram_mb=round(peak),
        )
        (final.parent / f"{name}.json").write_text(json.dumps(stats, indent=2), encoding="utf-8")
        print(f"[ok] {name}: {stats['faces']} faces, {stats['size_m']} m, "
              f"{stats['seconds']}s, peak {stats['peak_vram_mb']} MB -> {final}")
        if not args.no_preview:
            try:
                res = render_previews(final, work, final.parent / f"{name}_icon.png", cfg)
                print(f"     preview: {res['preview']}  icon: {res['icon']}")
            except Exception as e:  # noqa: BLE001
                print(f"     preview skipped: {e}")


def cmd_post(args, cfg):
    src = Path(args.glb)
    name = slug(args.name or src.stem)
    final = Path(cfg["export_dir"]) / args.category / name / f"{name}.glb"
    stats = postprocess(src, final, cfg["categories"][args.category],
                        args.height, args.pivot, args.metallic, args.roughness, args.width, args.depth,
                        args.collision, cfg.get("collision_faces", 800), rotate_y=args.rotate_y,
                        saturation=args.saturation, brightness=args.brightness,
                        materials="auto" if args.materials else None, category=args.category)
    print(f"[ok] {name}: {stats} -> {final}")


def main():
    cfg = load_config()
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p):
        p.add_argument("--category", choices=list(cfg["categories"]), default="prop")
        p.add_argument("--name", help="asset name (single input only)")
        p.add_argument("--height", type=float, help="scale so the model is this tall, in metres")
        p.add_argument("--materials", action="store_true",
                       help="recognise materials (wood, metal, stone...) and write roughness/metallic maps")
        p.add_argument("--saturation", type=float, default=1.0, help="albedo saturation multiplier (1 = unchanged)")
        p.add_argument("--brightness", type=float, default=1.0, help="albedo brightness multiplier (1 = unchanged)")
        p.add_argument("--collision", choices=["none", "convex", "simplified"],
                       help="collision proxy for Godot (default: per category in config.json)")
        p.add_argument("--width", type=float, help="then stretch X (left-right) to this many metres")
        p.add_argument("--depth", type=float, help="then stretch Z (front-back) to this many metres")
        p.add_argument("--pivot", choices=["bottom", "center"], help="override category pivot")
        p.add_argument("--metallic", type=float, help="override material metallic factor 0..1")
        p.add_argument("--roughness", type=float, help="override material roughness factor 0..1")

    g = sub.add_parser("generate", help="image(s) or folder -> exported GLB")
    g.add_argument("input", nargs="+")
    common(g)
    g.add_argument("--texture-resolution", type=int)
    g.add_argument("--foreground-ratio", type=float)
    g.add_argument("--remesh", choices=["none", "triangle", "quad"], default="none")
    g.add_argument("--vertices", type=int, default=-1, help="target vertex count, -1 = off")
    g.add_argument("--no-remove-bg", action="store_true", help="image already has alpha")
    g.add_argument("--force", action="store_true", help="overwrite existing export")
    g.add_argument("--no-preview", action="store_true", help="skip the Blender preview and icon")
    g.set_defaults(fn=cmd_generate)

    p = sub.add_parser("post", help="re-run post-processing on an existing GLB")
    p.add_argument("glb")
    p.add_argument("--rotate-y", type=float, default=0.0,
                   help="turn the model around the vertical axis, degrees (use 180 for raw SF3D output)")
    common(p)
    p.set_defaults(fn=cmd_post)

    args = ap.parse_args()
    args.fn(args, cfg)


if __name__ == "__main__":
    main()
