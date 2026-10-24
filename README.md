# 3D Animator: local game-asset toolkit

**English** · [Русский](README.ru.md)

A local Windows toolkit that turns pictures into game-ready 3D assets for Godot 4: models, skeletons, animations, equipment, PBR materials, tiling surfaces, VFX flipbooks, modular dungeon kits, destructible props and vegetation with wind.

Everything runs on your own GPU. The only cloud piece is the optional reference-image generator (your ChatGPT subscription through Codex CLI, or an OpenRouter key).

It glues several open-source models together (Stable Fast 3D, Hunyuan3D-2, UniRig) with Blender and Godot scripts. It has a Gradio GUI in English and Russian and two command-line tools.

> **Status: personal tool, shared as is.** It was built and tested on a single machine (Windows 11, RTX 4060 Laptop 8 GB VRAM, 31 GB RAM). Many paths are hardcoded, so read [Hardcoded paths](#hardcoded-paths) before installing.

![The main window](docs/images/en/ui_create.jpg)

---

## Contents

- [What it does](#what-it-does)
- [How to work with the tools](#how-to-work-with-the-tools) (screenshots)
- [Requirements](#requirements) · [Hardcoded paths](#hardcoded-paths) · [Installation](#installation) · [Running](#running)
- [Armour fitting in detail](#armour-fitting-in-detail) · [Animation gallery](#animation-gallery-1)
- [Repository layout](#repository-layout) · [Third-party licences](#third-party-licences)

---

## What it does

| GUI tab | What you get | Engine |
|---|---|---|
| Create → Reference | Style card + reference pictures (single view or front/back/left/right) for a model, built from a text prompt | Codex CLI (ChatGPT) or OpenRouter |
| Create → Make a model | GLB from 1 picture (~20 s) or from 1–4 views (7–10 min), with pivot, real-world scale, collision proxy, PBR factors, previews and an icon. Categories: item, prop, building, character, vegetation | SF3D / Hunyuan3D-2mv + Hunyuan3D-Paint |
| Character → Skeleton (automatic UniRig or by hand with landmarks) | Skeleton + skin for humanoids and creatures, Mixamo or Godot bone names, seam welding, body split into regions | UniRig + Blender |
| Character → Animations: procedural | 12 procedural clips for any rigged humanoid (idle, walk, run, jump, attacks, cast, block, hit, death…) | Blender |
| Character → Animations: Mixamo (FBX) | Retarget Mixamo FBX clips (without skin) onto your rig, in-place option, three.js viewer | Blender |
| Character → Equipment | Move an outfit from a dressed character onto the base body, or fit a single armour piece and skin it to the shared skeleton | Blender + Robust Weight Transfer |
| Skeleton by landmarks → Armour | Fit a piece (bracer, greave, cuisse, boot, breastplate, helmet) onto the built character in the editor, skin it in Blender, save the fitting, try it on in a Godot fitting room with the character's clips | three.js + Blender + Godot |
| Environment → Surfaces | Seamless ground/floor/wall materials (albedo, normal, height, roughness, AO) | numpy |
| Environment → Effects | Particle flipbooks (explosion, fire, smoke, magic) + ready Godot scenes | numpy + Godot |
| Environment → Modular kits | Procedural dungeon kit (walls, arches, stairs, doors) + ASCII plan → Godot scene | Blender + Godot |
| Environment → Destructible objects | Voronoi-fractured props + Godot scene that breaks on hit | Blender + Godot |
| Create → Materials | Recognises metal/wood/stone/cloth on an existing GLB and writes a metallic-roughness map | CLIP |
| Create → Batch processing (also the File menu) | Whole folder of pictures in one run (overnight) | all of the above |
| Options menu + GPU strip | Paths, OpenRouter key, who holds GPU memory, unload models; live VRAM strip at the top | – |
| Character → Weight fixing, Face parts, Lipsync | Weight repair, shared eyes/teeth/tongue kit, lip-sync clip for the speech mouth | Blender |

Outputs go to `export\<category>\<name>\` (GLB + JSON stats + icon). Scratch files go to `work\`. Neither folder is in the repository.

---

## How to work with the tools

### Interface language

The **🌐** menu at the top switches between English and Russian. The choice is saved in `tool/config.json` (`"lang"`), the server restarts by itself, and the page comes back in the new language after a few seconds. All texts live in `tool/lang/en.json` and `tool/lang/ru.json`; to add a language, copy one of them, translate the values and add the code to `LANGS` in `tool/i18n.py`.

![The language menu](docs/images/en/ui_language.jpg)

### Skeleton by landmarks

Character → Skeleton → «By hand with landmarks», then «Open the markup». Click the landmarks on the front view (chin, groin, shoulder, elbow, wrist, knee, ankle); the pelvis, spine, neck, clavicles, hips and feet are computed. Orange joints are landmarks, blue ones are computed; any joint can be moved or turned with the gizmo (G / R) or by numbers. «Mark the fingers» and «Mark the face» add fingers, jaw and eyes. Then «Build the skeleton and weights from the markup».

![Landmark markup](docs/images/en/03_markup.jpg)

**Pose** shows the built model with its skeleton. Drag an arm or a leg to bend it; «Check pose» bends every limb at once, so creases and bad weights show.

| Pose mode | «Check pose» |
|---|---|
| ![Pose mode](docs/images/en/01_pose.jpg) | ![Check pose](docs/images/en/02_pose_check.jpg) |

### Armour: place, put on, check

**Armour** opens the fitting panel. Choose the piece's GLB: a piece without its own skeleton gets its body part from the file name (cuisse → thigh, chest → torso, …), or choose it yourself. The piece is placed and fitted to the skin by its whole inner wall at once. The dots are the nodes of the inner wall: red — under the skin, green — on it, blue — air.

«Put on» sends the piece to Blender: it is pushed out of the skin, given the character's bones and weights, and saved next to the character. «Check pose» bends the body, and the piece must follow it.

| 1. Placed (fit nodes) | 2. «Put on» | 3. «Check pose» |
|---|---|---|
| ![Placed](docs/images/en/04_armour_placed.jpg) | ![Put on](docs/images/en/05_armour_fitted.jpg) | ![Check pose](docs/images/en/06_armour_pose.jpg) |

The sliders correct what the automatic fit got wrong: position along the limb, length, girth, wall thickness, twist about the axis, gap to the skin, fit to the body and rigidity. «Points» pulls the surface by hand, and «Fit to the skin» runs the automatic fit again after manual changes.

### Openings: an arm hole drawn in

«Opening»: click 3 or more points around the edge of an arm hole or a neck. «Narrow the opening» draws the edge and the surface around it toward the circle's centre, both walls together; «And the symmetric opening» does the other side too. Here the arm hole of a breastplate was too wide and left the armpit open.

| Before | «Narrow the opening» 0.25 |
|---|---|
| ![Before](docs/images/en/07_opening_before.jpg) | ![After](docs/images/en/08_opening_after.jpg) |

### Repaint for the shape

Drawing an opening in, points and the wall slider all stretch the texture. «Repaint for the shape» sends the reshaped piece to Hunyuan3D-Paint with the front picture it was made from (found by itself for generated armour, or chosen in «Piece picture»). The texture is painted anew on the new shape, sides not seen in the picture included (3–6 min on the GPU).

| The piece as generated | Arm hole narrowed and repainted |
|---|---|
| ![As generated](docs/images/repaint_before.jpg) | ![Repainted](docs/images/repaint_after.jpg) |

### Opening up a closed end

A generated piece is sometimes closed at an end: SF3D caps a bracer at both ends, and a Hunyuan cuisse may have a knee cop curling under it. Choose the end (lower — away from the body, upper, or both) and press «Open up». Blender cuts that end off with the texture kept; the piece's own wall stays, and a solid blank gets a wall inwards. The piece is then placed again.

### Saving and the Godot fitting room

Every «Put on» also saves the fitting (`<character>_wear_<item>.fit.json`); «Open» brings it back with all the sliders and points. «Fitting room in Godot» builds a small Godot project with the character, its clips and every piece put on, and opens it.

### Animation gallery

`tool/anim_gallery.py` puts about 90 clips (Mesh2Motion, CC0, plus procedural two-handed and shield clips) on a rigged character and writes one HTML page that opens with a double click. The clips are grouped: locomotion, jumps, dodges, sword, sword and shield, two-handed sword, defence, magic, unarmed, bow and throwing, hits and deaths, emotes.

![Animation gallery](docs/images/en/gallery.jpg)

---

## Requirements

**Hardware:** an NVIDIA GPU with **8 GB VRAM** or more (CUDA 12.x driver), 32 GB RAM recommended, and about **60 GB** of free disk for environments, model weights and caches.

**Software you must install yourself** (none of it is bundled):

| What | Version used | Needed for |
|---|---|---|
| Windows 10/11 x64 | 11 | everything (scripts are `.bat`/`.ps1`) |
| [Miniconda](https://docs.anaconda.com/miniconda/) | any recent | the three Python environments |
| [Git for Windows](https://git-scm.com/download/win) | any | cloning; **its `bash.exe` runs UniRig** |
| [Visual Studio 2022 Build Tools](https://visualstudio.microsoft.com/visual-cpp-build-tools/) with "Desktop development with C++" | 2022 | compiling SF3D, Hunyuan3D-Paint and UniRig native extensions |
| [CUDA Toolkit 12.1](https://developer.nvidia.com/cuda-12-1-0-download-archive) | 12.1 | compiling SF3D's `texture_baker` (Hunyuan gets its own `nvcc` from conda) |
| [Blender](https://www.blender.org/download/) | 5.2 | rigging, animation, equipment, kits, destructibles, previews |
| [Godot](https://godotengine.org/download) (console exe) | 4.7.2 | building FX / kit / destructible scenes, the fitting room |
| [Hugging Face account](https://huggingface.co/join) | – | SF3D weights are **gated**: accept the licence at [stabilityai/stable-fast-3d](https://huggingface.co/stabilityai/stable-fast-3d) and log in |
| [Codex CLI](https://github.com/openai/codex) (`npm i -g @openai/codex`, then `codex login`) | 0.160 | *optional*: Reference tab with a ChatGPT subscription |
| OpenRouter API key | – | *optional*: Reference tab without Codex |

---

## Hardcoded paths

The scripts assume this layout. The easiest route is to reproduce it. Otherwise, edit the places listed below.

| Path | Purpose | Where it is set |
|---|---|---|
| `D:\conda\envs\sf3d`, `...\hunyuan`, `...\unirig` | Python environments | `sf3d-env.bat`, `tool\launch_ui.ps1`, `tool\sf3d_ui.py` (`HY_PY`), `tool\rigging.py` (`UNIRIG_ENV`), install scripts |
| `D:\conda\hf`, `D:\conda\hy3dgen` | Hugging Face / Hunyuan model cache | same files + `tool\hy_pipeline.py`, `tool\hy_texture_mv.py` |
| `D:\conda\tmp`, `D:\conda\pip-cache`, `D:\conda\pkgs` | temp files and caches (kept off C:) | launchers and install scripts |
| `D:\conda\rig` | staging folder for UniRig (its bash scripts break on spaces in paths) | `tool\rigging.py` (`STAGE`) |
| `D:\Git\bin\bash.exe` | Git Bash for UniRig | `tool\rigging.py` (`BASH`) |
| `<repo>\hunyuan3d-src` | Hunyuan3D source | `tool\sf3d_ui.py` (`HY_SRC`) |
| Blender, Godot, export/work/input folders, interface language | | `tool\config.json` (also editable in the Settings window) |

The repository itself can live anywhere. The original lives at `D:\My projects\SF3D`; paths with spaces are fine for everything except UniRig staging.

---

## Installation

Run everything from an **Anaconda/Miniconda PowerShell prompt** at the repository root.

### 1. Clone this repository and the three model repositories next to it

The model repositories are **not** included here. Clone them into these exact folder names:

```powershell
git clone https://github.com/Sergeyspb-source/3d-animator.git
cd 3d-animator

git clone https://github.com/Stability-AI/stable-fast-3d.git sf3d-src
git clone https://github.com/Tencent-Hunyuan/Hunyuan3D-2.git hunyuan3d-src
git clone https://github.com/VAST-AI-Research/UniRig.git unirig-src

# UniRig: use the community Windows support PR #70
git -C unirig-src fetch origin pull/70/head:pr70
git -C unirig-src checkout pr70
```

### 2. Apply the local patches (folder `patches\`)

```powershell
# Hunyuan3D-Paint: load the UNet from .safetensors so the 3.5 GB .bin is not needed
git -C hunyuan3d-src apply ..\patches\hunyuan3d-paint-safetensors.patch

# UniRig: low-memory skeleton configs for 8 GB GPUs
Copy-Item -Recurse -Force patches\unirig\configs\* unirig-src\configs\
```

### 3. SF3D environment (`sf3d`): GUI, SF3D, materials, glue code

There is no install script for this step yet. Run these commands by hand. Open the "x64 Native Tools Command Prompt for VS 2022" first, so the C++/CUDA extensions compile:

```powershell
conda create -p D:\conda\envs\sf3d python=3.10 -y
$py = 'D:\conda\envs\sf3d\python.exe'
& $py -m pip install torch==2.4.1 torchvision==0.19.1 --index-url https://download.pytorch.org/whl/cu121
& $py -m pip install setuptools==69.5.1 wheel
cd sf3d-src
& $py -m pip install -r requirements.txt          # builds texture_baker and uv_unwrapper
& $py -m pip install -r requirements-demo.txt     # gradio 4.41.0
cd ..
# extra modules used by this toolkit (not in SF3D's requirements)
& $py -m pip install scikit-image scipy matplotlib fast-simplification onnxruntime-gpu
# log in so the gated SF3D weights can download on first run
& $py -m huggingface_hub.commands.huggingface_cli login
```

### 4. Robust Weight Transfer dependencies (equipment tab)

`tool\vendor\rwt\weighttransfer.py` is vendored (GPL-3.0, see `tool\vendor\rwt\LICENSE` and `source_manifest.json`). Its compiled dependencies are **not** in git. Install them into the vendor folder:

```powershell
D:\conda\envs\sf3d\python.exe -m pip install --target tool\vendor\rwt\deps libigl==2.6.1 robust_laplacian==1.0.0
```

### 4b. Lip sync (optional, Character → Lipsync)

Self-contained: `tool\vendor\lipsync\transcribe.py` (local Whisper) and `lipsync.py` (ARKit face curves) run in the
`sf3d` env (numpy, scipy, torch, transformers; `soundfile` or ffmpeg for mp3/ogg). The `openai/whisper-small` model
(~1 GB) is downloaded on the first run into `hf_home` from `tool\config.json` (default `D:/conda/hf`); an existing
Hugging Face cache is reused. Output: `<model folder>\<voice>.face.json` + the audio copy.

In Godot: copy `tool\godot\face_curves_clip.gd` and `face_curves_player.gd` into your project, add a
`FaceCurvesPlayer` node (`audio` = the voice `AudioStreamPlayer3D`, `face_root` = the character, `clip_path` = the
`.face.json`). It drives the blend shapes of the character's mouth plate (`jawOpen`, `mouthSmile`, …) from the audio clock.

### 5. Hunyuan3D-2 environment (`hunyuan`): multi-view models and texturing

```powershell
powershell -ExecutionPolicy Bypass -File hunyuan3d-install.ps1        # env + PyTorch 2.4.1 cu121 + hy3dgen
powershell -ExecutionPolicy Bypass -File hunyuan3d-texgen-install.ps1 # nvcc 12.1 from conda + builds custom_rasterizer / mesh_processor (needs VS 2022 Build Tools)
powershell -ExecutionPolicy Bypass -File hunyuan3d-weights.ps1        # shape model tencent/Hunyuan3D-2mv (fp16)
powershell -ExecutionPolicy Bypass -File hunyuan3d-texgen-weights.ps1 # delight + paint models
```

The build script `hunyuan3d-texgen-build.bat` has `TORCH_CUDA_ARCH_LIST=8.9` (RTX 40xx). **Change it to match your GPU** (8.6 for RTX 30xx, 12.0 for RTX 50xx).

### 6. UniRig environment (`unirig`): auto-rigging

```powershell
powershell -ExecutionPolicy Bypass -File unirig-install.ps1   # env py3.11 + torch cu128 + spconv + flash-attn shim
unirig-build-ext.bat                                          # only if torch_scatter / torch_cluster failed to install
```

UniRig weights (`VAST-AI/UniRig`) download from Hugging Face on the first rig.

### 7. Configure

On first start, `tool\config.example.json` is used. To change the paths or the language, copy it to `tool\config.json` (this file is git-ignored) and set `lang` (`en` or `ru`), `blender_exe`, `godot_exe`, `export_dir`, `work_dir` and `input_dir`. You can also do it in the Settings window and the 🌐 menu.

---

## Running

| How | What |
|---|---|
| `sf3d-ui.vbs` (double-click) | GUI with no console, opens an app window at `http://127.0.0.1:7861`. Closing the window stops the server and frees VRAM |
| `sf3d-ui.bat` | same GUI with a visible console (for debugging) |
| `sf3d-tool.bat generate <image or folder> --category prop` | one-off CLI: image(s) → game-ready GLB |
| `sf3d-tool.bat post work\item\axe\raw.glb --category item --name axe` | re-run post-processing only |
| `sf3d-batch.bat <folder> [--force] [--no-preview]` | batch: `<folder>\<category>\pic.png` → SF3D; `<folder>\<category>\<asset>\front.png [back/left/right.png]` → Hunyuan3D |
| `sf3d-gradio.bat` | the original SF3D demo UI (port 7860) |

**Run one GPU job at a time.** Approximate peak VRAM: SF3D 6.2 GB, Hunyuan shape 5.8 GB, Hunyuan paint 7.4 GB, UniRig 4.5 GB. The GUI checks free memory before each job.

---

## Armour fitting in detail

In the landmark editor's pose mode, **Armour** opens the armour panel:

1. Pick the piece's GLB and the body part. A piece without its own skeleton gets the part from its file name (cuisse/thigh → thigh, greave → shin, bracer/vambrace → forearm, rerebrace → upper arm, gauntlet → hand, boot → «Boot», helmet → head, chest/cuirass → torso, in English or Russian); otherwise the choice stays as it was. The tube axis of a piece without a skeleton is the way it is open (rays from its middle pass straight through; the piece's own x/y/z are tried as well as its principal axes, since a short wide piece has no clear ones). The piece is placed along the limb's real middle line, then fitted by its whole inner wall. Nodes, one per cell of the piece (12 along × 24 around), are matched to the skin by ICP with a one-sided penalty: shift, tilt, scale across the limb and oval-ness change, the shape does not. «Fit to the skin» runs it again after manual changes. The nodes are shown red (under the skin), green (on it) and blue (air).
2. Adjust it with the sliders, the gizmo (G / R / S) or surface points. The sliders are position, length, «Girth» (the whole piece wider or narrower), «Wall thickness» (the inner wall stays, only the outer surface moves; the same about the piece's own axis in the editor and in Blender), twist and gap. The info line shows the air and the wall thickness as shares of the limb's radius.
3. **«Put on»** runs `tool/blender_wear_fit.py`. The piece is scaled away from the limb axis cell by cell, so the inner wall clears the skin and the wall keeps its shape. What is still under the skin is then pushed out along the skin's normal, spread over its neighbours, so the inner and outer wall move together. «Fit to the body» (conform) draws loose parts in towards the limb. Skin weights come only from the limb's own bones and are smoothed over the piece. «Rigidity» makes it move with the bone (0.8 for bracers and greaves, 0.2 for gloves). The result is `<character>_wear_<item>.glb`: the character's skeleton plus the skinned piece.
   - A piece made on another body that carries its own skeleton (the Tripo extractions in `export/equipment`) is read with it. On one limb segment it is placed as above; over several segments (a boot over the shin and the foot, a whole arm) the part «The whole piece by its own skeleton» is chosen. Then each vertex moves from the piece's bones onto the character's same bones by its own weights, the way skinning moves skin, and the other side is the mirror with Left and Right swapped. Blender gets the moved copies, pushes them out of the skin, and weights them only to the bones the piece used.
   - Upright pieces as generated keep their own vertical as their axis and their proportions: «Torso (breastplate)» — no mirror, weights on the spine, never on the arms; «Head (helmet)» — the helmet's top at the top of the head, rigid on the head bone; «Boot» — the shaft on the shin, sized by it; the toe turned along the foot (the long axis of its sole, at the end farther from the shaft); the sole at the heel.
   - «Opening»: clicks around the rim of an arm hole or a neck give its circle. «Narrow the opening» draws the rim and the surface near it towards the circle's axis, both walls together, with a smooth falloff; «And the symmetric opening» does the other side too. This happens in the piece's own space, so the editor, the mirrored copy and Blender get the same shape.
   - «Open up» (lower end / upper end / both ends): a generated piece closed at an end is cut open there by `blender_armour_hollow.py`, texture and all, and placed again. On a limb the lower end is the one away from the body (the wrist, the knee); an upright piece goes by its own vertical. The piece's own wall stays; a solid blank gets one inwards (rays from the middle out pass two surfaces when it has a wall).
   - «Repaint for the shape»: Hunyuan3D-Paint paints the reshaped piece anew from its reference picture (found in `refs_mv`, or chosen in «Piece picture»), so the texture follows the new shape instead of being stretched (3–6 min on the GPU). The result becomes the fitting's source piece.
   - Hunyuan3D from four views (Codex draws them: `export/equipment/generated_armour/make_refs_mv.py`) gives hollow armour that sits without any opening step. A piece generated from one picture is usually a closed solid; `tool/blender_armour_hollow.py in.glb out.glb [open=both|top|bottom] [axis=auto|z|x,y,z] [wall=0.08|auto]` is the same cut from the command line.
4. Every fitting is saved next to the character as `<character>_wear_<item>.fit.json` + `.src.glb`. «Open» brings it back with all the sliders and points, and «Save» saves without fitting.
5. **«Fitting room in Godot»** builds `work/wardrobe/<character>/`: the character with its clips (the procedural ones are made if none exist), every fitted piece on, pieces on/off, and an orbit camera. It then opens the project in Godot.

In your own Godot project, copy `tool/godot/sf3d_equip.gd` and the GLBs, then:

```gdscript
var bracers := SF3DEquip.wear($Goblin, preload("res://goblin_wear_bracer.glb"))   # put on (meshes move under the character's Skeleton3D)
SF3DEquip.take_off(bracers)                                                      # take off
```

The piece follows every animation of the character by bone names. It must come from the same rigged model.

---

## Animation gallery

`tool/anim_gallery.py` puts the Mesh2Motion clips (`Animations/Mesh2Motion`, CC0) and the procedural two-handed and shield clips on a rigged character. The result is one self-contained HTML page with about 90 clips in groups (see [the screenshot above](#animation-gallery)). The page holds the GLB inside, so it opens with a double click. Its texts are in the interface language.

```powershell
D:\conda\envs\sf3d\python.exe tool\anim_gallery.py "<character>_landmarks_rigged.glb" Animations\goblin_gallery.html
```

`blender_retarget_fbx.py` reads the clips straight from the Mesh2Motion GLBs: Unreal-style bone names are mapped onto Mixamo ones. The weapons in the hands are approximate, because their presets were set on another goblin; the «Weapons in hand» checkbox hides them.

---

## Repository layout

```
sf3d-ui.vbs / sf3d-ui.bat     GUI launchers
sf3d-tool.bat / sf3d-batch.bat CLI launchers
sf3d-env.bat                  environment for the sf3d env
*-install.ps1, *-weights.ps1, *-build.bat   installers for Hunyuan3D and UniRig
patches/                      changes applied on top of the third-party repos
docs/images/                  README screenshots (en/, ru/)
tool/
  sf3d_ui.py                  Gradio GUI (all tabs)
  i18n.py, lang/*.json        interface language: every text by key (English, Russian)
  sf3d_tool.py, batch_cli.py  CLI and post-processing (pivot, scale, collision, materials)
  hy_*.py                     Hunyuan3D workers (run in the hunyuan env)
  rigging.py, outfit.py, hanim.py, fbxanim.py, materials.py, surfaces.py,
  fx_flipbook.py, modkit.py, destruct.py, refgen.py, anim_gallery.py, rwt_*.py   feature modules
  landmarks*.py, landmark_editor.html   skeleton from hand-placed landmarks and armour fitting (three.js editor)
  blender_*.py                headless Blender scripts (blender -b -P tool\blender_x.py -- args)
  godot/                      Godot scripts and shaders used by generated scenes (incl. FaceCurvesPlayer for lip sync,
                              SF3DEquip to put fitted armour on, the armour fitting room)
  rig_scripts/                Git-Bash wrappers for UniRig
  vendor/rwt/                 Robust Weight Transfer (GPL-3.0)
  vendor/lipsync/             Whisper word timings + lip-sync curves (vendored, see its README)
  config.example.json         settings template
```

Not in git (created locally): `sf3d-src/`, `hunyuan3d-src/`, `unirig-src/`, `export/`, `work/`, `input/`, `tool/config.json`, `tool/vendor/rwt/deps/`, all model weights.

---

## Third-party licences

This repository holds only the glue code. Each model keeps its own licence, so **check them before any commercial use**:

- **Stable Fast 3D**: [Stability AI Community License](https://huggingface.co/stabilityai/stable-fast-3d) (free under USD 1M annual revenue).
- **Hunyuan3D-2**: [Tencent Hunyuan 3D 2.0 Community License](https://github.com/Tencent-Hunyuan/Hunyuan3D-2/blob/main/LICENSE). **Not licensed in the EU, the UK and South Korea.**
- **UniRig**: MIT.
- **Robust Weight Transfer** (`tool/vendor/rwt`): GPL-3.0.
- **CLIP weights** (open_clip, LAION ViT-B/32): MIT.
- **Mesh2Motion animations** (gallery): CC0.
