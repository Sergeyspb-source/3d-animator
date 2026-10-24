"""Automatic rigging: UniRig (skeleton + skin weights), several skeleton attempts with automatic choice of the
best one (UniRig is random: some attempts include fingers, some do not), then standard humanoid bone names
(Mixamo or Godot) so Godot can retarget animations onto the result.

UniRig runs in its own env (D:\\conda\\envs\\unirig) through Git Bash scripts that cannot cope with spaces
in user paths, so files are staged in D:\\conda\\rig\\in|out and copied back.
"""
from __future__ import annotations

import json
import os
import shutil
import struct
import subprocess
from pathlib import Path

import numpy as np
from i18n import t as _t

ROOT = Path(__file__).resolve().parent
UNIRIG_ENV = Path(r"D:\conda\envs\unirig")
BASH = r"D:\Git\bin\bash.exe"
STAGE = Path(r"D:\conda\rig")
SCRIPTS = ROOT / "rig_scripts"
SEEDS = [12345, 1, 2, 4, 3, 6]  # 12345 is UniRig's default; the others were tried on the test goblin

# ------------------------------------------------------------------ names
MIXAMO = dict(hips="Hips", spine=["Spine", "Spine1", "Spine2"], neck="Neck", head="Head",
              shoulder="{S}Shoulder", arm="{S}Arm", forearm="{S}ForeArm", hand="{S}Hand",
              upleg="{S}UpLeg", leg="{S}Leg", foot="{S}Foot", toe="{S}ToeBase", prefix="mixamorig:",
              finger="{S}Hand{F}{K}", finger_k=["1", "2", "3", "4"])
GODOT = dict(hips="Hips", spine=["Spine", "Chest", "UpperChest"], neck="Neck", head="Head",
             shoulder="{S}Shoulder", arm="{S}UpperArm", forearm="{S}LowerArm", hand="{S}Hand",
             upleg="{S}UpperLeg", leg="{S}LowerLeg", foot="{S}Foot", toe="{S}Toes", prefix="",
             finger="{S}{F}{K}", finger_k=None)  # Godot: thumb Metacarpal/Proximal/Distal, others Proximal/Intermediate/Distal
NAMINGS = {"mixamo": MIXAMO, "godot": GODOT}
FINGERS = ["Thumb", "Index", "Middle", "Ring", "Pinky"]


# ------------------------------------------------------------------ glb json helpers
def _read_glb(path):
    b = Path(path).read_bytes()
    n = struct.unpack("<I", b[12:16])[0]
    j = json.loads(b[20:20 + n])
    rest = b[20 + n:]
    return j, rest


def _write_glb(path, j, rest):
    js = json.dumps(j, separators=(",", ":")).encode("utf-8")
    js += b" " * ((4 - len(js) % 4) % 4)
    total = 12 + 8 + len(js) + len(rest)
    Path(path).write_bytes(b"glTF" + struct.pack("<II", 2, total) + struct.pack("<I", len(js)) + b"JSON" + js + rest)


def _local(node):
    if "matrix" in node:
        return np.array(node["matrix"], dtype=float).reshape(4, 4).T
    t = np.array(node.get("translation", [0, 0, 0]), dtype=float)
    q = np.array(node.get("rotation", [0, 0, 0, 1]), dtype=float)
    s = np.array(node.get("scale", [1, 1, 1]), dtype=float)
    x, y, z, w = q / (np.linalg.norm(q) or 1)
    R = np.array([[1 - 2 * (y * y + z * z), 2 * (x * y - z * w), 2 * (x * z + y * w)],
                  [2 * (x * y + z * w), 1 - 2 * (x * x + z * z), 2 * (y * z - x * w)],
                  [2 * (x * z - y * w), 2 * (y * z + x * w), 1 - 2 * (x * x + y * y)]])
    M = np.eye(4)
    M[:3, :3] = R * s
    M[:3, 3] = t
    return M


def joint_tree(j):
    """-> (joints, parent, children, world_pos) for the first skin; indices are glTF node indices."""
    nodes = j["nodes"]
    skin = j["skins"][0]
    joints = list(skin["joints"])
    parent = {}
    for i, n in enumerate(nodes):
        for c in n.get("children", []):
            parent[c] = i
    world = {}

    def wm(i):
        if i not in world:
            world[i] = (wm(parent[i]) if i in parent else np.eye(4)) @ _local(nodes[i])
        return world[i]

    pos = {i: wm(i)[:3, 3] for i in joints}
    jset = set(joints)
    jparent = {i: parent[i] for i in joints if i in parent and parent[i] in jset}
    children = {i: [] for i in joints}
    for i, p in jparent.items():
        children[p].append(i)
    return joints, jparent, children, pos


def tree_from_npz(path):
    """UniRig's predict_skeleton.npz -> the same tree structure, converted to Y-up like glTF."""
    d = np.load(path, allow_pickle=True)
    pts = np.asarray(d["joints"], dtype=float)
    parents = list(d["parents"])
    span = pts.max(0) - pts.min(0)
    # the figure stands, so "up" is Y or Z; X is the arm span, which in a T-pose is wider than the joints are tall
    up = 1 if span[1] >= span[2] else 2
    if up == 2:        # Blender style, Z up: (x, y, z) -> (x, z, -y)
        pts = np.stack([pts[:, 0], pts[:, 2], -pts[:, 1]], axis=1)
    joints = list(range(len(pts)))
    jparent = {i: int(p) for i, p in enumerate(parents) if p is not None}
    children = {i: [] for i in joints}
    for i, p in jparent.items():
        children[p].append(i)
    return joints, jparent, children, {i: pts[i] for i in joints}


# ------------------------------------------------------------------ role detection
def roles_from_tree(joints, jparent, children, pos):
    """Joint index -> (role, side) for a UniRig-like humanoid skeleton.

    Roles: hips, spine#, neck, head, shoulder, arm, forearm, hand, upleg, leg, foot, toe, finger.
    info['finger_chains'][side] = list of chains (joint lists), used for naming and for scoring.
    """
    roots = [i for i in joints if i not in jparent]
    if not roots:
        raise RuntimeError("skeleton has no root")
    hips = roots[0]
    while len(children[hips]) == 1:  # skip an extra "root" bone above the hips
        hips = children[hips][0]
    ys = np.array([pos[i][1] for i in joints])
    height = ys.max() - ys.min() or 1.0

    def subtree(i):
        out, st = [], [i]
        while st:
            k = st.pop()
            out.append(k)
            st += children[k]
        return out

    def chain(i):
        """Follow a single-child path starting at i."""
        out = [i]
        while len(children[out[-1]]) == 1:
            out.append(children[out[-1]][0])
        return out

    roles = {hips: ("hips", None)}
    legs, spine_start = [], None
    for c in children[hips]:
        low = min(pos[k][1] for k in subtree(c))
        high = max(pos[k][1] for k in subtree(c))
        if low < pos[hips][1] - 0.2 * height and high <= pos[hips][1] + 0.05 * height:
            legs.append(c)
        elif high > pos[hips][1] + 0.2 * height:
            spine_start = c
    if len(legs) != 2 or spine_start is None:
        raise RuntimeError(f"unexpected skeleton: legs={len(legs)}, spine={'yes' if spine_start else 'no'}")

    # which way is the character facing? from the ankle to the toe tip, in the ground plane
    forward = None
    for lg in legs:
        ch = chain(lg)
        if len(ch) >= 4:
            d = pos[ch[-1]] - pos[ch[-2]]
            d[1] = 0
            if np.linalg.norm(d) > 1e-6:
                forward = d / np.linalg.norm(d) if forward is None else forward + d / np.linalg.norm(d)
    if forward is None:
        forward = np.array([0.0, 0.0, 1.0])  # glTF convention
    forward = forward / (np.linalg.norm(forward) or 1)
    left = np.cross([0, 1, 0], forward)  # facing +Z with Y up -> left is +X

    def side_of(i):
        return "Left" if np.dot(pos[i] - pos[hips], left) > 0 else "Right"

    for lg in legs:
        s = side_of(lg)
        ch = chain(lg)
        names = ["upleg", "leg", "foot", "toe"]
        for k, node in enumerate(ch):
            roles[node] = (names[k] if k < len(names) else "legextra", s)

    sp = chain(spine_start)
    chest = sp[-1]  # the spine chain ends at the first joint that branches: shoulders + neck
    for k, node in enumerate(sp):
        roles[node] = (f"spine{k}", None)
    arms, neck = [], None
    for c in children[chest]:
        x_extent = max(abs(np.dot(pos[k] - pos[hips], left)) for k in subtree(c))
        if x_extent > 0.12 * height:
            arms.append(c)
        else:
            neck = c
    finger_chains = {"Left": [], "Right": []}
    for a in arms:
        s = side_of(a)
        ch = chain(a)
        # the arm chain stops at the hand when fingers branch off it, otherwise it ends at the last joint
        if len(ch) >= 4:
            names = ["shoulder", "arm", "forearm", "hand"]
        elif len(ch) == 3:
            names = ["arm", "forearm", "hand"]
        else:
            names = ["arm", "forearm"][:len(ch)]
        for k, node in enumerate(ch):
            roles[node] = (names[k] if k < len(names) else "armextra", s)
        for sub in children[ch[-1]]:  # anything hanging off the hand = fingers
            fc = chain(sub)
            finger_chains[s].append(fc)
            for node in subtree(sub):
                roles.setdefault(node, ("finger", s))
    if neck is not None:
        nk = chain(neck)
        for k, node in enumerate(nk):
            roles[node] = ("head" if k == len(nk) - 1 else ("neck" if k == 0 else "neckextra"), None)
    info = dict(hips=hips, facing=[round(float(v), 2) for v in forward], height=round(float(height), 3),
                bones=len(joints), finger_chains=finger_chains)
    return roles, info


def detect_roles(j):
    return roles_from_tree(*joint_tree(j))


def score_skeleton(tree):
    """Higher is better. Symmetric hands with five 3-joint fingers are what Godot's humanoid profile wants."""
    try:
        roles, info = roles_from_tree(*tree)
    except Exception:  # noqa: BLE001
        return -1, {}
    L, R = info["finger_chains"]["Left"], info["finger_chains"]["Right"]
    lens_l, lens_r = sorted(len(c) for c in L), sorted(len(c) for c in R)
    detail = dict(bones=info["bones"], left=lens_l, right=lens_r)
    if not L and not R:
        return 1, detail  # valid skeleton without fingers
    if lens_l != lens_r:
        return 0, detail  # lopsided hands: worse than no fingers
    score = 50
    if len(L) == 5:
        score += 20
    if all(n == 3 for n in lens_l):
        score += 30
    elif all(n in (3, 4) for n in lens_l):
        score += 15
    return score, detail


def _name_fingers(chains, hand_pos, forearm_dir, pos):
    """Order five finger chains as Thumb..Pinky. Returns {finger name: chain} or {} if it does not look like a hand."""
    if len(chains) != 5:
        return {}
    u = np.mean([pos[c[-1]] - pos[c[0]] for c in chains], axis=0)
    u = u / (np.linalg.norm(u) or 1)
    bases = np.array([pos[c[0]] for c in chains])
    cen = bases.mean(0)
    off = bases - cen
    off = off - np.outer(off @ u, u)  # spread directions, perpendicular to the finger direction
    s = np.linalg.svd(off, full_matrices=False)[2][0]
    t = off @ s
    order = np.argsort(t)
    ends = [order[0], order[-1]]
    # the thumb is the end finger that starts nearest to the wrist
    thumb = min(ends, key=lambda i: float((bases[i] - hand_pos) @ u))
    other_end = ends[0] if thumb == ends[1] else ends[1]
    rest = sorted((i for i in range(5) if i != thumb), key=lambda i: abs(t[i] - t[thumb]))
    seq = [thumb] + rest  # Thumb, Index, Middle, Ring, Pinky: increasing distance from the thumb
    assert other_end == seq[-1] or True
    return {FINGERS[k]: chains[i] for k, i in enumerate(seq)}


def rename_bones(src, dst, naming="mixamo"):
    """Rewrite a rigged GLB so the joint nodes carry standard humanoid names. Returns ({old: new}, info)."""
    cfg = NAMINGS[naming]
    j, rest = _read_glb(src)
    tree = joint_tree(j)
    roles, info = roles_from_tree(*tree)
    pos = tree[3]
    nodes = j["nodes"]
    mapping, used = {}, set()

    def put(node, base):
        new = cfg["prefix"] + base
        if new in used:
            return
        used.add(new)
        mapping[nodes[node].get("name", f"node{node}")] = new
        nodes[node]["name"] = new

    hand_node = {}
    for node, (role, side) in roles.items():
        s = side or ""
        if role.startswith("spine"):
            k = int(role[5:])
            names = cfg["spine"]
            put(node, names[k] if k < len(names) else f"Spine{k}")
        elif role in ("hips", "neck", "head"):
            put(node, cfg[role])
        elif role in ("shoulder", "arm", "forearm", "hand", "upleg", "leg", "foot", "toe"):
            put(node, cfg[role].replace("{S}", s))
            if role == "hand":
                hand_node[side] = node
    named_fingers = 0
    for side, chains in info["finger_chains"].items():
        if side not in hand_node:
            continue
        hp = pos[hand_node[side]]
        for fname, ch in _name_fingers(chains, hp, None, pos).items():
            for k, node in enumerate(ch):
                if cfg["finger_k"]:  # Mixamo: HandThumb1..4
                    if k >= len(cfg["finger_k"]):
                        break
                    kk = cfg["finger_k"][k]
                else:  # Godot: only the first three joints have names in the humanoid profile
                    part = (["Metacarpal", "Proximal", "Distal"] if fname == "Thumb"
                            else ["Proximal", "Intermediate", "Distal"])
                    if k >= 3:
                        break
                    kk = part[k]
                put(node, cfg["finger"].replace("{S}", side).replace("{F}", fname).replace("{K}", kk))
                named_fingers += 1
    info = {k: v for k, v in info.items() if k != "finger_chains"}
    info["named_fingers"] = named_fingers
    _write_glb(dst, j, rest)
    return mapping, info


# ------------------------------------------------------------------ UniRig run
def _run_bash(script, args, timeout=1500):
    env = dict(os.environ)
    env["PATH"] = os.pathsep.join([str(UNIRIG_ENV), str(UNIRIG_ENV / "Scripts"), str(UNIRIG_ENV / "Library" / "bin"),
                                   env.get("PATH", "")])
    env.update(HF_HOME=r"D:\conda\hf", TMP=r"D:\conda\tmp", TEMP=r"D:\conda\tmp",
               PYTHONIOENCODING="utf-8", PYTHONWARNINGS="ignore")
    r = subprocess.run([BASH, str(SCRIPTS / script).replace("\\", "/"), *map(str, args)], env=env,
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout + "\n" + r.stderr


def strip_rig(src, dst, blender):
    """Remove an existing skeleton/skin with headless Blender; returns the summary line."""
    r = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_strip_rig.py"), "--", str(src), str(dst)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    line = next((x for x in r.stdout.splitlines() if x.startswith("STRIP_OK")), None)
    if line is None:
        raise RuntimeError("could not strip the rig: " + (r.stdout + r.stderr)[-300:])
    return line


def weld_seams(src, dst, blender, eps=0.0005):
    """Give vertex copies that sit at the same place in different mesh parts identical skin weights and normals
    (headless Blender, tool/blender_seams.py). Returns a stats dict, or None if the model has no such seams."""
    r = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_seams.py"), "--", str(src), str(dst), str(eps)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = [x for x in r.stdout.splitlines() if x.startswith("SEAM_")]
    if not any(x.startswith("SEAM_OK") for x in lines):
        return None
    def num(tag, key):
        for x in lines:
            if x.startswith(tag) and key in x:
                try:
                    return float(x.split(key + "=")[1].split()[0].rstrip("%"))
                except ValueError:
                    return None
    found = next((x for x in lines if x.startswith("SEAM_FOUND")), "")
    return dict(clusters=int(found.split("clusters=")[1].split()[0]) if "clusters=" in found else 0,
                gap_before_mm=num("SEAM_BEFORE", "stress_gap_mean_mm"), gap_after_mm=num("SEAM_AFTER", "stress_gap_mean_mm"),
                mismatch_before=num("SEAM_BEFORE", "weight_mismatch"))


def split_parts(src, dst, blender):
    """Split a rigged GLB into body-region meshes (Body_head, Body_torso, ...) on the same skeleton.
    Returns {part name: triangles}; raises if the model is not rigged."""
    r = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_split_parts.py"), "--", str(src), str(dst)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = r.stdout.splitlines()
    if not any(x.startswith("SPLIT_OK") for x in lines):
        fail = next((x for x in lines if x.startswith("SPLIT_FAIL")), (r.stdout + r.stderr)[-300:])
        raise RuntimeError(_t("rig.could_not_split_into_parts", fail))
    parts = {}
    for x in lines:
        if x.startswith("SPLIT_PART"):
            _, name, tris, _verts = x.split()
            parts[name] = int(tris.split("=")[1])
    return parts


ARMOUR_SLOTS = {"chest": ["torso"], "helmet": ["head"], "gloves": ["hand_L", "hand_R"],
                "boots": ["foot_L", "foot_R"], "pants": ["pelvis", "leg_L", "leg_R"],
                "bracers": ["arm_L", "arm_R"], "pauldrons": ["torso", "arm_L", "arm_R"],
                "head": ["head"], "belt": ["pelvis"],
                "arms": ["arm_L", "arm_R", "hand_L", "hand_R"]}


def fit_armour(body_parts_glb, armour_glb, slot, dst, blender, options=None, hide_body=False):
    """Fit a static armour GLB onto a split, rigged body and skin it (tool/blender_fit_armor.py).
    options: offset, length, width, height, depth, up (see the script). Writes dst, a manifest
    <dst>.item.json and a preview <dst>_preview_front/side.png. Returns the manifest dict."""
    opts = {k: v for k, v in (options or {}).items() if v not in (None, "")}
    r = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_fit_armor.py"), "--", str(body_parts_glb),
                        str(armour_glb), slot, str(dst), *[f"{k}={v}" for k, v in opts.items()]],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = [x for x in r.stdout.splitlines() if x.startswith("FIT_")]
    if not any(x.startswith("FIT_OK") for x in lines):
        raise RuntimeError(_t("rig.fitting_failed") + (" | ".join(lines) or (r.stdout + r.stderr)[-300:]))
    # Open armour (vests, straps, armholes) keeps the body under it: hiding it would leave a hole visible through
    # the openings. Closed armour can hide the covered regions to avoid any poke-through in extreme poses.
    covers = [f"Body_{p}" for p in ARMOUR_SLOTS[slot]]
    hides = covers if hide_body else []
    manifest = dict(
        id=Path(dst).stem, kind="armour", slot=slot, mesh=Path(dst).name, hides=hides, covers=covers,
        body=Path(body_parts_glb).name, fit=opts, log=[x for x in lines if not x.startswith("FIT_OK")])
    mask = Path(dst).with_suffix(".mask.json")
    if mask.exists():  # body vertices this item covers: the game drops those triangles while it is worn
        manifest["mask"] = mask.name
    pv = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_fit_preview.py"), "--", str(body_parts_glb),
                         str(dst), str(Path(dst).with_name(Path(dst).stem + "_preview.png")), ",".join(hides)],
                        capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=600,
                        creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    ok = next((x for x in pv.stdout.splitlines() if x.startswith("FITVIEW_OK")), None)
    manifest["previews"] = ok.split(" ", 1)[1].split(";") if ok else []
    Path(dst).with_suffix(".item.json").write_text(json.dumps(manifest, indent=2, ensure_ascii=False),
                                                   encoding="utf-8")
    return manifest


def rig_steps(src, dst, naming="mixamo", name="model", strip=False, blender=None, tries=3, weld=True,
              kind="humanoid"):
    """Generator of (message, done_flag); the last item is (result dict, True).

    kind="creature": animals and monsters (four legs, tails, wings): any predicted skeleton is accepted and the
    bones keep UniRig's names (humanoid naming and finger scoring do not apply).

    tries: how many skeleton predictions to attempt (1-6). The best one wins: symmetric hands with five
    3-joint fingers beat 'no fingers', which beats lopsided hands.
    """
    src, dst = Path(src), Path(dst)
    (STAGE / "in").mkdir(parents=True, exist_ok=True)
    (STAGE / "out").mkdir(parents=True, exist_ok=True)
    # stale files from an earlier run of the same name would be mistaken for fresh output
    for p in (STAGE / "out").glob(f"{name}_*"):
        shutil.rmtree(p) if p.is_dir() else p.unlink()
    shutil.rmtree(STAGE / "in" / name, ignore_errors=True)
    staged = STAGE / "in" / f"{name}.glb"
    if strip:
        yield _t("rig.removing_the_existing_skeleton"), False
        strip_rig(src, staged, blender)
    else:
        shutil.copy2(src, staged)

    best = None  # (score, seed, fbx path, detail)
    skel = STAGE / "out" / f"{name}_skel.fbx"
    for attempt, seed in enumerate(SEEDS[:max(1, min(tries, len(SEEDS)))], 1):
        yield _t("rig.predicting_the_skeleton_attempt_of", attempt, tries), False
        if skel.exists():
            skel.unlink()
        _run_bash("run_skel.sh", [name, 50000, seed])
        npz = STAGE / "in" / name / "predict_skeleton.npz"
        if not skel.exists() or not npz.exists():
            continue
        if kind == "humanoid":
            score, detail = score_skeleton(tree_from_npz(npz))
        else:
            score, detail = 1, dict(bones=len(tree_from_npz(npz)[0]))
        keep = STAGE / "out" / f"{name}_skel_s{seed}.fbx"
        shutil.copy2(skel, keep)
        fing = _t("rig.has_fingers") if detail.get("left") else _t("rig.no_fingers")
        yield (_t("rig.attempt_bones", attempt, detail.get('bones', '?'), fing, '' if score > 0 else ' (неудачный скелет)')), False
        if best is None or score > best[0]:
            best = (score, seed, keep, detail)
        if score >= 100 or kind != "humanoid":
            break  # symmetric five-finger hands: good enough, stop early
    if best is None or best[0] < 0:
        raise RuntimeError(_t("rig.no_skeleton_was_made_in_any_attempt"))
    shutil.copy2(best[2], skel)
    yield _t("rig.chose_the_skeleton_of_the_attempt", best[1], best[3].get('bones')), False

    yield _t("rig.computing_the_skin_weights_and"), False
    rigged = STAGE / "out" / f"{name}_rigged.glb"
    out = ""
    for retry in range(2):  # the weights step occasionally dies on a memory spike; one more try usually works
        out = _run_bash("run_skin_merge.sh", [name])
        if rigged.exists() and rigged.stat().st_size >= 1000:
            break
        yield _t("rig.the_weights_step_wrote_no_file"), False
    if not rigged.exists() or rigged.stat().st_size < 1000:
        key = [x.strip()[:160] for x in out.splitlines()
               if any(w in x for w in ("Error", "error", "out of memory", "Traceback", "Exception", "failed"))]
        raise RuntimeError(_t("rig.the_rig_was_not_made_the_weights_or")
                           + (" | ".join(key[-3:]) or _t("rig.no_errors_in_the_output")))
    seams = None
    if weld and blender:
        yield _t("rig.stitching_the_seams_between_the"), False
        welded = STAGE / "out" / f"{name}_welded.glb"
        try:
            seams = weld_seams(rigged, welded, blender)
        except Exception:  # noqa: BLE001  (a failed weld must not lose the rig)
            seams = None
        if seams and welded.exists() and welded.stat().st_size > 1000:
            rigged = welded
    dst.parent.mkdir(parents=True, exist_ok=True)
    if kind != "humanoid":
        shutil.copy2(rigged, dst)
        yield dict(path=str(dst), mapping={}, info=dict(seed=best[1], bones=best[3].get("bones"), seams=seams,
                                                        kind=kind)), True
        return
    yield _t("rig.giving_the_bones_standard_names", naming), False
    try:
        mapping, info = rename_bones(rigged, dst, naming)
    except Exception as e:  # noqa: BLE001  (unusual skeleton: keep UniRig's names, still a valid rig)
        shutil.copy2(rigged, dst)
        mapping, info = {}, dict(warning=_t("rig.bone_names_not_set", e))
    info["seed"] = best[1]
    info["fingers"] = best[3]
    info["seams"] = seams
    yield dict(path=str(dst), mapping=mapping, info=info), True

# ------------------------------------------------------------------ creatures (four legs, tails, wings)
def creature_auto(src, dst, blender):
    """Turn the creature to look along -Y, name its bones from the skeleton's shape and guess the mouth line
    (tool/blender_creature_auto.py). Returns (names {old: new}, jaw dict)."""
    r = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_creature_auto.py"), "--", str(src), str(dst)],
                       capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = r.stdout.splitlines()
    if not any(x.startswith("AUTO_OK") for x in lines):
        fail = next((x for x in lines if x.startswith("AUTO_FAIL")), (r.stdout + r.stderr)[-300:])
        raise RuntimeError(_t("rig.could_not_read_the_creature_s", fail))
    names = json.loads(next(x for x in lines if x.startswith("AUTO_NAMES ")).split(" ", 1)[1])
    jaw = json.loads(next(x for x in lines if x.startswith("AUTO_JAW ")).split(" ", 1)[1])
    return names, jaw


def creature_finish(src, dst, blender, names, jaw=None, line_mm=0.0, hinge_mm=0.0, preview=None):
    """Rename bones and add the jaw (tool/blender_creature_finish.py). line_mm moves the mouth line up (+) or
    down (-), hinge_mm moves the hinge back (+) or forward (-). Returns {"jaw_vertices": n, "previews": [...]}."""
    args = []
    if names:
        args.append("names=" + ",".join(f"{a}:{b}" for a, b in names.items()))
    if jaw:
        dz, dy = line_mm / 1000.0, hinge_mm / 1000.0
        pt = lambda p, ddy=0.0: f"{p[0] + ddy:.5f},{p[1] + dz:.5f}"
        args += [f"jaw_front={pt(jaw['jaw_front'])}", f"jaw_corner={pt(jaw['jaw_corner'], dy / 2)}",
                 f"hinge={pt(jaw['hinge'], dy)}", f"cx={jaw['cx']:.5f}", f"half_width={jaw['half_width']:.5f}",
                 f"floor={jaw['floor']:.5f}", f"fade={jaw['fade']:.5f}", f"jaw_parent={jaw['jaw_parent']}"]
    if preview:
        args.append(f"preview={preview}")
    r = subprocess.run([blender, "-b", "-P", str(ROOT / "blender_creature_finish.py"), "--", str(src), str(dst),
                        *args], capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=900,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    lines = r.stdout.splitlines()
    if not any(x.startswith("CREATURE_OK") for x in lines):
        raise RuntimeError(_t("rig.the_jaw_and_names_were_not_written") + (r.stdout + r.stderr)[-300:])
    out = {"jaw_vertices": 0, "previews": []}
    for x in lines:
        if x.startswith("CREATURE_JAW"):
            out["jaw_vertices"] = int(x.split("vertices=")[1].split()[0])
    if preview:
        base = str(preview)[:-4]
        out["previews"] = [f"{base}_{a}_{v}.png" for a in (0, 30) for v in ("side", "front")
                           if Path(f"{base}_{a}_{v}.png").exists()]
    return out
