"""Destructible objects: Voronoi fracture in Blender, a Godot scene (intact model + rigid-body pieces + script).

    make_destructible(blender, godot, src_glb, name, export_dir, work_dir, chunks, seed, interior, mass, health,
                      burst) -> dict(scene, folder, shots, chunks)

Output: <export_dir>/destructible/sf3d_destructibles/<name>/ (glb, fracture.json, <name>.tscn, shots/) and the shared
destructible.gd one level up. The user copies the folder `sf3d_destructibles` into the Godot project.
"""
import json
import shutil
import subprocess
from pathlib import Path
from i18n import t as _t

ROOT = Path(__file__).resolve().parent
NOFLAGS = getattr(subprocess, "CREATE_NO_WINDOW", 0)

README = _t("destr.sf3d_destructible_objects_copy_the")


def _run(cmd, timeout):
    return subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                          creationflags=NOFLAGS)


def make_destructible(blender, godot, src_glb, name, export_dir, work_dir, chunks=12, seed=1, interior="auto",
                      mass=20.0, health=20.0, burst=3.5, log=None):
    log = log or (lambda s: None)
    base = Path(export_dir) / "destructible" / "sf3d_destructibles"
    out = base / name
    out.mkdir(parents=True, exist_ok=True)
    log(_t("destr.blender_is_cutting_the_model_into"))
    r = _run([blender, "-b", "-P", str(ROOT / "blender_fracture.py"), "--", str(src_glb), str(out),
              f"chunks={int(chunks)}", f"seed={int(seed)}", f"interior={interior}", f"name={name}"], 1200)
    glb = out / f"{name}_destructible.glb"
    if not glb.exists():
        raise RuntimeError(_t("destr.blender_did_not_cut_the_model") + (r.stdout + r.stderr)[-500:])
    fj = out / "fracture.json"
    info = json.loads(fj.read_text(encoding="utf-8"))
    info["props"] = dict(mass_total=float(mass), max_health=float(health), burst_impulse=float(burst))
    fj.write_text(json.dumps(info, indent=1), encoding="utf-8")
    n = len(info["chunks"])
    log(_t("destr.chunks_godot_is_building_the_scene", n))
    proj = Path(work_dir) / "destr_build"
    pdst = proj / "sf3d_destructibles"
    if (pdst / name).exists():
        shutil.rmtree(pdst / name)
    (pdst / name).mkdir(parents=True, exist_ok=True)
    if not (proj / "project.godot").exists():
        (proj / "project.godot").write_text('config_version=5\n\n[application]\nconfig/name="sf3d_destr_build"\n',
                                            encoding="utf-8")
    shutil.copy2(ROOT / "godot" / "destructible.gd", pdst / "destructible.gd")
    shutil.copy2(ROOT / "godot" / "build_destructible.gd", proj / "build_destructible.gd")
    shutil.copy2(ROOT / "godot" / "destr_shots.gd", proj / "destr_shots.gd")
    for f in (glb, fj):
        shutil.copy2(f, pdst / name / f.name)
    # the effects and a floor material make the preview look like the game (optional)
    fx = Path(export_dir) / "fx" / "sf3d_fx"
    if fx.exists() and not (proj / "sf3d_fx").exists():
        shutil.copytree(fx, proj / "sf3d_fx")
    cob = Path(export_dir) / "materials" / "cobblestone"
    if cob.exists() and not (proj / "mats" / "cobblestone").exists():
        shutil.copytree(cob, proj / "mats" / "cobblestone")
    _run([godot, "--headless", "--path", str(proj), "--import"], 900)
    r = _run([godot, "--headless", "--path", str(proj), "--script", "res://build_destructible.gd", "--", name], 900)
    scene = pdst / name / f"{name}.tscn"
    if not scene.exists():
        raise RuntimeError(_t("destr.godot_did_not_build_the_scene") + (r.stdout + r.stderr)[-500:])
    shutil.copy2(scene, out / scene.name)
    shutil.copy2(ROOT / "godot" / "destructible.gd", base / "destructible.gd")
    (base / "README.md").write_text(README, encoding="utf-8")
    log(_t("destr.recording_the_destruction_for_a"))
    shots = out / "shots"
    shots.mkdir(exist_ok=True)
    _run([godot, "--rendering-driver", "opengl3", "--path", str(proj), "--script", "res://destr_shots.gd", "--",
          name, str(shots), f"{info['height']:.3f}"], 300)
    pics = [str(shots / f) for f in ("before.png", "break_0.12.png", "break_0.4.png", "break_1.4.png")
            if (shots / f).exists()]
    return dict(scene=str(out / scene.name), folder=str(base), shots=pics, chunks=n)
