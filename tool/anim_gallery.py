"""Animation gallery: the Mesh2Motion clips (Animations/Mesh2Motion, CC0), the Mixamo packs (Animations/Mixamo) and
SF3D's procedural two-handed and shield clips on one rigged character, as a single self-contained HTML page (the GLB
is inside): open it and pick a clip. The fitting room takes the same clips a block at a time (blocks, build_block).

    python anim_gallery.py <rigged.glb> <out.html>
    python anim_gallery.py block <rigged.glb> <group> [--gallery=<dir>]

Blender copies every clip onto the character's skeleton (blender_retarget_fbx.py, Unreal-style bone names mapped onto
Mixamo ones); the page is tool/viewer_anim.html with the weapons of the clip in the hands (sword, sword and shield,
two-handed sword). Work files go to work_dir/anim_gallery/<name>/.
"""
import base64
import json
import re
import subprocess
import sys
from pathlib import Path
import i18n
from i18n import t as _t

ROOT = Path(__file__).resolve().parent
M2M = ROOT.parent / "Animations" / "Mesh2Motion" / "glb"
SRC = {"base": M2M / "human-base-animations.glb", "addon": M2M / "human-addon-animations.glb",
       "mocap": M2M / "human-mocap-animations.glb"}
S, SS, GS = ["sword"], ["sword", "shield"], ["greatsword"]   # what is in the hands

# (group: its anim.<key> text, source, clip in the source, label, loop, weapons); "twohand" / "shield": SF3D's procedural
# clips made with both hands on one sword / a shield on the left arm
CLIPS = [
    ("locomotion", "base", "Idle_A", _t("anim.idle"), True, []),
    ("locomotion", "addon", "Idle_Subtle", _t("anim.idle_restrained"), True, []),
    ("locomotion", "base", "Walk", _t("anim.walk"), True, []),
    ("locomotion", "addon", "Walk_Large", _t("anim.heavy_walk"), True, []),
    ("locomotion", "base", "Jog", _t("anim.jog"), True, []),
    ("locomotion", "base", "Sprint", _t("anim.sprint"), True, []),
    ("locomotion", "addon", "Walk_Backwards", _t("anim.step_back"), True, []),
    ("locomotion", "addon", "Strafe_left", _t("anim.side_step_left"), True, []),
    ("locomotion", "addon", "Strafe_right", _t("anim.side_step_right"), True, []),
    ("locomotion", "base", "Crouch_Idle", _t("anim.crouch"), True, []),
    ("locomotion", "base", "Crouch_Walk", _t("anim.crouch_walk"), True, []),
    ("locomotion", "addon", "Walk_Stealth", _t("anim.sneak"), True, []),
    ("locomotion", "addon", "Run_Stealth", _t("anim.sneak_run"), True, []),
    ("locomotion", "addon", "Crawl", _t("anim.crawl"), True, []),
    ("locomotion", "mocap", "Turn_Left_90", _t("anim.turn_left_90"), False, []),
    ("locomotion", "mocap", "Turn_Right_90", _t("anim.turn_right_90"), False, []),
    ("locomotion", "mocap", "Turn_Left_180", _t("anim.turn_around_180"), False, []),
    ("jumps", "base", "Jump_Start", _t("anim.jump_take_off"), False, []),
    ("jumps", "base", "Jump_air", _t("anim.jump_in_the_air"), True, []),
    ("jumps", "base", "Jump_Land", _t("anim.jump_landing"), False, []),
    ("jumps", "addon", "Jump_2", _t("anim.standing_jump"), False, []),
    ("jumps", "addon", "Run Jump", _t("anim.running_jump"), False, []),
    ("jumps", "base", "NinjaJump_Start", _t("anim.high_jump_take_off"), False, []),
    ("jumps", "base", "NinjaJump_Idle", _t("anim.high_jump_in_the_air"), True, []),
    ("jumps", "base", "NinjaJump_Land", _t("anim.high_jump_landing"), False, []),
    ("jumps", "addon", "Backflip", _t("anim.backflip"), False, []),
    ("jumps", "addon", "Land_Three_Point", _t("anim.three_point_landing"), False, []),
    ("dodges_and_rolls", "addon", "Dodge_back", _t("anim.hop_back"), False, []),
    ("dodges_and_rolls", "addon", "Dodge_left", _t("anim.dodge_left"), False, []),
    ("dodges_and_rolls", "addon", "Dodge_right", _t("anim.dodge_right"), False, []),
    ("dodges_and_rolls", "base", "Roll", _t("anim.roll"), False, []),
    ("dodges_and_rolls", "base", "Slide_Start", _t("anim.slide_start"), False, []),
    ("dodges_and_rolls", "base", "Slide", _t("anim.slide"), True, []),
    ("dodges_and_rolls", "base", "Slide_Exit", _t("anim.slide_exit"), False, []),
    ("sword", "base", "Idle_Sword", _t("anim.sword_stance"), True, S),
    ("sword", "base", "Sword_Attack", _t("anim.sword_strike"), False, S),
    ("sword", "base", "Sword_Regular_A", _t("anim.combo_strike_1"), False, S),
    ("sword", "base", "Sword_Regular_B", _t("anim.combo_strike_2"), False, S),
    ("sword", "base", "Sword_Regular_C", _t("anim.combo_strike_3"), False, S),
    ("sword", "base", "Sword_Regular_Combo", _t("anim.three_strike_combo"), False, S),
    ("sword", "addon", "Sword_Attack_Air_Vertical", _t("anim.jumping_overhead_strike"), False, S),
    ("sword", "base", "Sword_Block", _t("anim.sword_block"), False, S),
    ("sword_and_shield", "base", "Idle_Shield", _t("anim.shield_stance"), True, SS),
    ("sword_and_shield", "base", "Shield_OneShot", _t("anim.shield_bash"), False, SS),
    ("sword_and_shield", "base", "Idle_Shield_Break", _t("anim.shield_broken"), False, SS),
    ("sword_and_shield", "shield", "idle_loop", _t("anim.stance_procedural"), True, SS),
    ("sword_and_shield", "shield", "walk_loop", _t("anim.walk_with_shield"), True, SS),
    ("sword_and_shield", "shield", "attack_slash", _t("anim.strike_from_behind_the_shield"), False, SS),
    ("sword_and_shield", "shield", "block_loop", _t("anim.shield_block"), True, SS),
    ("two_handed_sword", "twohand", "idle_loop", _t("anim.stance"), True, GS),
    ("two_handed_sword", "twohand", "walk_loop", _t("anim.walk"), True, GS),
    ("two_handed_sword", "twohand", "run_loop", _t("anim.run"), True, GS),
    ("two_handed_sword", "twohand", "attack_slash", _t("anim.diagonal_strike"), False, GS),
    ("two_handed_sword", "twohand", "attack_overhead", _t("anim.overhead_strike"), False, GS),
    ("two_handed_sword", "twohand", "block_loop", _t("anim.block"), True, GS),
    ("two_handed_sword", "twohand", "hit", _t("anim.hit"), False, GS),
    ("defence", "addon", "Defend", _t("anim.cover_with_arms"), False, []),
    ("defence", "base", "Hit_Knockback", _t("anim.knocked_back"), False, []),
    ("magic", "base", "Spell_Simple_Enter", _t("anim.spell_wind_up"), False, []),
    ("magic", "base", "Spell_Simple_Idle", _t("anim.spell_hold"), True, []),
    ("magic", "base", "Spell_Simple_Shoot", _t("anim.spell_release"), False, []),
    ("magic", "base", "Spell_Simple_Exit", _t("anim.spell_finish"), False, []),
    ("magic", "addon", "Two-hand Blast", _t("anim.two_handed_force_blast"), False, []),
    ("magic", "addon", "Power Up", _t("anim.charging_power"), False, []),
    ("magic", "addon", "Levitate Entrance", _t("anim.levitation_lift_off"), False, []),
    ("magic", "addon", "Levitate Idle", _t("anim.levitation"), True, []),
    ("magic", "addon", "Meditate", _t("anim.meditation"), True, []),
    ("unarmed", "addon", "Fighting Idle", _t("anim.fighting_stance"), True, []),
    ("unarmed", "addon", "Fighting Left Jab", _t("anim.left_jab"), False, []),
    ("unarmed", "addon", "Fighting Right Jab", _t("anim.right_jab"), False, []),
    ("unarmed", "base", "Punch_Cross", _t("anim.straight_punch"), False, []),
    ("unarmed", "base", "Melee_Hook", _t("anim.hook"), False, []),
    ("unarmed", "mocap", "Kick_Breach", _t("anim.kick"), False, []),
    ("unarmed", "addon", "Attack_Ground_Pound", _t("anim.ground_slam"), False, []),
    ("bow_and_throwing", "addon", "Bow Pull Back", _t("anim.bow_draw"), False, []),
    ("bow_and_throwing", "addon", "Bow Pull Hold", _t("anim.bow_hold"), True, []),
    ("bow_and_throwing", "addon", "Bow Release", _t("anim.bow_shoot"), False, []),
    ("bow_and_throwing", "base", "OverhandThrow", _t("anim.overhand_throw"), False, []),
    ("bow_and_throwing", "addon", "Throw Object", _t("anim.item_throw"), False, []),
    ("damage_and_death", "base", "Hit_Chest", _t("anim.hit_in_the_chest"), False, []),
    ("damage_and_death", "base", "Hit_Head", _t("anim.hit_in_the_head"), False, []),
    ("damage_and_death", "addon", "Idle Hurt", _t("anim.wounded"), True, []),
    ("damage_and_death", "addon", "Dizzy", _t("anim.stunned"), True, []),
    ("damage_and_death", "addon", "Death_A", _t("anim.death_1"), False, []),
    ("damage_and_death", "addon", "Death_B", _t("anim.death_2"), False, []),
    ("damage_and_death", "addon", "Death_C", _t("anim.death_3"), False, []),
    ("damage_and_death", "base", "Death_D", _t("anim.death_4"), False, []),
    ("emotes", "addon", "Victory", _t("anim.victory"), False, []),
    ("emotes", "addon", "Victory Fist Pump", _t("anim.victory_fist_up"), False, []),
    ("emotes", "addon", "Greeting", _t("anim.greeting"), False, []),
    ("emotes", "addon", "Angry", _t("anim.angry"), False, []),
    ("emotes", "mocap", "Insult", _t("anim.taunt"), False, []),
    ("emotes", "mocap", "Cheer_One_arm", _t("anim.cheering"), False, []),
]
PROC = {"twohand": dict(twohand=True, blade="fingers"), "shield": dict(shield=True, blade="fingers")}

# Mixamo packs downloaded into Animations/Mixamo/<pack>/ (FBX, without skin): every clip of a pack into a group;
# a pack there replaces the procedural clips of its kind (REPLACES). Labels are the files' names, the pack's words off.
MIXAMO = ROOT.parent / "Animations" / "Mixamo"
PACKS = {"Great Sword": ("two_handed_sword", GS), "Sword and Shield": ("sword_and_shield", SS),
         "Axe": ("axe", ["axe"]), "Longbow": ("bow_and_throwing", ["bow"]), "Magic": ("magic", []),
         "Male unarmed": ("unarmed_male", []), "Female unarmed": ("unarmed_female", []), "Creatures": ("creatures", [])}
REPLACES = {"Great Sword": "twohand", "Sword and Shield": "shield"}
_LOOPS = ("idle", "walk", "walking", "run", "running", "strafe", "loop", "breathing")
_ONCE = ("stop", "turn", "land", "draw", "equip", "disarm", "to ")


def _mixamo():
    """[(group, source, clip, label, loop, weapons, fbx path)] of the packs found"""
    out = []
    for pack, (group, weapons) in PACKS.items():
        folder = MIXAMO / pack
        for f in sorted(folder.glob("*.fbx")) if folder.is_dir() else []:
            stem = f.stem
            if stem.lower().startswith("tripo"):   # a model sent to Mixamo, not a clip
                continue
            low = stem.lower()
            label = re.sub(r"^(great sword|sword and shield|two handed sword|standing|mutant)\s+", "", low).strip() or low
            loop = any(re.search(rf"\b{w}\b", low) for w in _LOOPS) and not any(w in low for w in _ONCE)
            out.append((group, "mixamo_" + pack, stem, label, loop, weapons, str(f)))
    return out


def all_clips():
    """CLIPS with the Mixamo packs' clips (an fbx path last; None for the others), the procedural ones a pack
    replaces left out"""
    mx = _mixamo()
    gone = {REPLACES[p] for p in REPLACES if any(c[1] == "mixamo_" + p for c in mx)}
    return [(*c, None) for c in CLIPS if c[1] not in gone] + mx


def _key(group, source, clip):   # the clip's name in the GLB and the page: unique, ASCII
    return re.sub(r"[^0-9A-Za-z]+", "_", f"{source}_{clip}").strip("_")


def build(cfg, rigged, out_html, log=print):
    out_glb, name, work = clips_glb(cfg, rigged, log)
    return _page(out_glb, Path(out_html), name, work, log)


def _name(rigged):
    return re.sub(r"[^\w-]+", "_", re.sub(r"_landmarks_rigged$|_rigged$", "", Path(rigged).stem)).strip("_") or "character"


def _work(cfg, name):   # (cfg["gallery_dir"]: another place for the retargeted clips, the tests' shared one)
    return Path(cfg.get("gallery_dir") or Path(cfg["work_dir"]) / "anim_gallery") / name


def _srcs(cfg, rigged, work, clips, log, make=True):
    """The clips' source GLBs by source: Mesh2Motion's, the procedural ones on this character's skeleton (made now
    when make and they are older than the character or their script)"""
    import hanim as HA
    srcs = {k: str(v) for k, v in SRC.items()}
    for kind, kw in PROC.items():
        want = sorted({c[2] for c in clips if c[1] == kind})
        if not want:
            continue
        glb = work / f"proc_{kind}.glb"
        made_by = max(Path(rigged).stat().st_mtime, (ROOT / "blender_humanoid_anim.py").stat().st_mtime)
        if make and (not glb.exists() or glb.stat().st_mtime < made_by):
            log(_t("anim.procedural_clips", kind, ', '.join(want)))
            HA.animate(cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe", rigged, glb, want, **kw)
        srcs[kind] = str(glb)
    return srcs


def _spec(clips, srcs):
    spec = {}
    for group, source, clip, label, loop, weapons, fbx in clips:
        k = _key(group, source, clip)
        spec[k] = ({"name": k, "loop": loop, "fbx": fbx} if fbx else
                   {"name": k, "loop": loop, "glb": srcs[source], "action": clip, **({"bones": "ue"} if source in SRC else {})})
    return json.dumps(spec, ensure_ascii=False, indent=1)


def _fresh(out_glb, mapf, text, rigged, srcs):   # the same clips on the same character, made after their sources
    if not (out_glb.exists() and mapf.exists() and mapf.read_text(encoding="utf-8") == text):
        return False
    deps = [Path(rigged), ROOT / "blender_retarget_fbx.py"] + [Path(srcs[k]) for k in PROC if k in srcs]
    return all(d.exists() and out_glb.stat().st_mtime > d.stat().st_mtime for d in deps)


def clips_glb(cfg, rigged, log=print):
    """Every clip on this character in one GLB (the page's): (the GLB, the character's name, the work folder).
    Retargeted once; again only when the character, the retargeting or the procedural clips change."""
    rigged = Path(rigged)
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    name = _name(rigged)
    work = _work(cfg, name)
    work.mkdir(parents=True, exist_ok=True)
    clips = all_clips()
    srcs = _srcs(cfg, rigged, work, clips, log)
    text = _spec(clips, srcs)
    out_glb = work / "gallery.glb"
    fresh = _fresh(out_glb, work / "map.json", text, rigged, srcs)
    (work / "map.json").write_text(text, encoding="utf-8")
    if fresh:   # the same clips on the same character: only the page is rebuilt
        log(_t("anim.clips_are_already_retargeted"))
    else:
        _retarget(blender, rigged, out_glb, work / "map.json", text.count('"name"'), log)
    return out_glb, name, work


def _groups(clips):
    out = {}
    for c in clips:
        out.setdefault(c[0], []).append(c)
    return out


def blocks(cfg, rigged):
    """The gallery's blocks for the fitting room, nothing made here: [{key, label, weapons, clips: [{id, label, loop,
    weapons}], glb: its block's clips (no mesh), ready: made and fresh, cmd: what makes it (build_block)}].
    sf3d_wardrobe.gd loads a block when it is picked, running cmd first when it is not ready."""
    rigged = Path(rigged)
    work = _work(cfg, _name(rigged))
    clips = all_clips()
    srcs = _srcs(cfg, rigged, work, clips, print, make=False)
    out = []
    for g, cl in _groups(clips).items():
        glb = work / "blocks" / f"{g}.glb"
        ready = (_fresh(glb, glb.with_suffix(".map.json"), _spec(cl, srcs), rigged, srcs)
                 and Path(str(glb) + ".done").exists())
        out.append(dict(key=g, label=_t("anim." + g), weapons=sorted({w for c in cl for w in c[5]}),
                        clips=[dict(id=_key(*c[:3]), label=c[3], loop=c[4], weapons=c[5]) for c in cl],
                        glb=str(glb), ready=ready,
                        cmd=[sys.executable, str(ROOT / "anim_gallery.py"), "block", str(rigged), g,
                             f"--gallery={work.parent}"]))
    return out


def build_block(cfg, rigged, key, log=print):
    """One block's clips retargeted onto the character, without its mesh: work/blocks/<key>.glb, then <key>.glb.done
    (or <key>.glb.error with the reason) for the fitting room waiting for it"""
    rigged = Path(rigged)
    work = _work(cfg, _name(rigged))
    glb = work / "blocks" / f"{key}.glb"
    glb.parent.mkdir(parents=True, exist_ok=True)
    done, err = Path(str(glb) + ".done"), Path(str(glb) + ".error")
    done.unlink(missing_ok=True)
    err.unlink(missing_ok=True)
    try:
        cl = [c for c in all_clips() if c[0] == key]
        if not cl:
            raise ValueError(key)
        srcs = _srcs(cfg, rigged, work, cl, log)
        text = _spec(cl, srcs)
        mapf = glb.with_suffix(".map.json")
        if not _fresh(glb, mapf, text, rigged, srcs):
            mapf.write_text(text, encoding="utf-8")
            _retarget(cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe", rigged, glb, mapf, len(cl), log, mesh=False)
        done.write_text("ok", encoding="utf-8")
    except Exception as e:
        err.write_text(str(e)[-1500:], encoding="utf-8")
        raise
    return glb


def clip_list(out_glb):
    """The clips made into out_glb, in CLIPS' order: {id, label, group (its key), group_label, loop, weapons}."""
    done = {c["name"] for c in json.loads(Path(str(out_glb) + ".json").read_text(encoding="utf-8"))}
    return [dict(id=_key(g, s, c), label=lab, group=g, group_label=_t("anim." + g), loop=lp, weapons=w)
            for g, s, c, lab, lp, w, _ in all_clips() if _key(g, s, c) in done]


def _retarget(blender, rigged, out_glb, mapf, n, log, mesh=True):
    log(_t("anim.blender_is_retargeting_clips_onto", n))
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_retarget_fbx.py"), "--", str(rigged),
                        str(out_glb), str(mapf), *([] if mesh else ["mesh=0"])], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if "RETARGET_GLB" not in r.stdout:
        raise RuntimeError(_t("anim.retargeting_failed") + (r.stdout + r.stderr)[-1500:])


def _page(out_glb, out_html, name, work, log):
    import fbxanim as FA
    from glbfix import set_metallic
    clips = [dict(c, group=c["group_label"]) for c in clip_list(out_glb)]
    done = {c["id"] for c in clips}
    weapons = []   # the goblin presets of the Mixamo tab for the models and their sizes; placed by the hand (fit)
    for wid, preset in (("sword", FA.WEAPON_SETS[_t("anim.goblin_sword_and_shield")][0]), ("shield", dict(FA.WEAPON_SETS[_t("anim.goblin_sword_and_shield")][1], bone="LeftForeArm")),
                        ("greatsword", FA.WEAPON_SETS[_t("anim.goblin_two_handed_sword")][0])):
        src = FA._weapon_glb(preset["model"])
        if src is None:
            continue
        tmp = work / f"weapon_{wid}.glb"
        tmp.write_bytes(src.read_bytes())
        set_metallic(tmp, 0.25, 0.85)
        weapons.append(dict(id=wid, bone=preset["bone"], scale=preset["scale"], rot=preset["rot"], grip=preset["grip"],
                            offset=preset.get("offset", [0, 0, 0]), palm=bool(preset.get("palm")),
                            fit="forearm" if wid == "shield" else "grip",   # by this rig's own hand, not the preset angles
                            glb=base64.b64encode(FA.shrink_glb(tmp, 512)).decode()))
    tpl = i18n.fill((ROOT / "viewer_anim.html").read_text(encoding="utf-8"))
    # the weapon presets were set on goblin_hero, 1 unit tall: the page scales them by this character's height
    page = (tpl.replace("@@DATA@@", json.dumps(dict(clips=clips, ref_height=1.0), ensure_ascii=False))
               .replace("@@GLB@@", base64.b64encode(FA.shrink_glb(out_glb, 1024)).decode())
               .replace("@@WEAPONS@@", json.dumps(weapons))
               .replace(_t("anim.animation_viewer"), _t("anim.animations", name)))
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(page, encoding="utf-8")
    missing = [c[2] for c in all_clips() if _key(*c[:3]) not in done]
    log(_t("anim.done_clips", out_html, len(clips)) + (_t("anim.not_retargeted", ', '.join(missing)) if missing else ""))
    return out_html


if __name__ == "__main__":
    #   python anim_gallery.py <rigged.glb> <out.html>                       the page
    #   python anim_gallery.py block <rigged.glb> <group> [--gallery=<dir>]  one block for the fitting room
    sys.path.insert(0, str(ROOT))
    import sf3d_tool as T
    cfg = T.load_config()
    args = [a for a in sys.argv[1:] if not a.startswith("--gallery=")]
    for a in sys.argv[1:]:
        if a.startswith("--gallery="):
            cfg["gallery_dir"] = a.split("=", 1)[1]
    if args[0] == "block":
        build_block(cfg, args[1], args[2])
    else:
        build(cfg, args[0], args[1])
