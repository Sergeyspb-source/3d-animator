"""Animation gallery: the Mesh2Motion clips (Animations/Mesh2Motion, CC0) and SF3D's procedural two-handed and shield
clips on one rigged character, as a single self-contained HTML page (the GLB is inside): open it and pick a clip.

    python anim_gallery.py <rigged.glb> <out.html>

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

# (group, source, clip in the source, label, loop, weapons); "twohand" / "shield": SF3D's procedural clips made with
# both hands on one sword / a shield on the left arm
CLIPS = [
    (_t("anim.locomotion"), "base", "Idle_A", _t("anim.idle"), True, []),
    (_t("anim.locomotion"), "addon", "Idle_Subtle", _t("anim.idle_restrained"), True, []),
    (_t("anim.locomotion"), "base", "Walk", _t("anim.walk"), True, []),
    (_t("anim.locomotion"), "addon", "Walk_Large", _t("anim.heavy_walk"), True, []),
    (_t("anim.locomotion"), "base", "Jog", _t("anim.jog"), True, []),
    (_t("anim.locomotion"), "base", "Sprint", _t("anim.sprint"), True, []),
    (_t("anim.locomotion"), "addon", "Walk_Backwards", _t("anim.step_back"), True, []),
    (_t("anim.locomotion"), "addon", "Strafe_left", _t("anim.side_step_left"), True, []),
    (_t("anim.locomotion"), "addon", "Strafe_right", _t("anim.side_step_right"), True, []),
    (_t("anim.locomotion"), "base", "Crouch_Idle", _t("anim.crouch"), True, []),
    (_t("anim.locomotion"), "base", "Crouch_Walk", _t("anim.crouch_walk"), True, []),
    (_t("anim.locomotion"), "addon", "Walk_Stealth", _t("anim.sneak"), True, []),
    (_t("anim.locomotion"), "addon", "Run_Stealth", _t("anim.sneak_run"), True, []),
    (_t("anim.locomotion"), "addon", "Crawl", _t("anim.crawl"), True, []),
    (_t("anim.locomotion"), "mocap", "Turn_Left_90", _t("anim.turn_left_90"), False, []),
    (_t("anim.locomotion"), "mocap", "Turn_Right_90", _t("anim.turn_right_90"), False, []),
    (_t("anim.locomotion"), "mocap", "Turn_Left_180", _t("anim.turn_around_180"), False, []),
    (_t("anim.jumps"), "base", "Jump_Start", _t("anim.jump_take_off"), False, []),
    (_t("anim.jumps"), "base", "Jump_air", _t("anim.jump_in_the_air"), True, []),
    (_t("anim.jumps"), "base", "Jump_Land", _t("anim.jump_landing"), False, []),
    (_t("anim.jumps"), "addon", "Jump_2", _t("anim.standing_jump"), False, []),
    (_t("anim.jumps"), "addon", "Run Jump", _t("anim.running_jump"), False, []),
    (_t("anim.jumps"), "base", "NinjaJump_Start", _t("anim.high_jump_take_off"), False, []),
    (_t("anim.jumps"), "base", "NinjaJump_Idle", _t("anim.high_jump_in_the_air"), True, []),
    (_t("anim.jumps"), "base", "NinjaJump_Land", _t("anim.high_jump_landing"), False, []),
    (_t("anim.jumps"), "addon", "Backflip", _t("anim.backflip"), False, []),
    (_t("anim.jumps"), "addon", "Land_Three_Point", _t("anim.three_point_landing"), False, []),
    (_t("anim.dodges_and_rolls"), "addon", "Dodge_back", _t("anim.hop_back"), False, []),
    (_t("anim.dodges_and_rolls"), "addon", "Dodge_left", _t("anim.dodge_left"), False, []),
    (_t("anim.dodges_and_rolls"), "addon", "Dodge_right", _t("anim.dodge_right"), False, []),
    (_t("anim.dodges_and_rolls"), "base", "Roll", _t("anim.roll"), False, []),
    (_t("anim.dodges_and_rolls"), "base", "Slide_Start", _t("anim.slide_start"), False, []),
    (_t("anim.dodges_and_rolls"), "base", "Slide", _t("anim.slide"), True, []),
    (_t("anim.dodges_and_rolls"), "base", "Slide_Exit", _t("anim.slide_exit"), False, []),
    (_t("anim.sword"), "base", "Idle_Sword", _t("anim.sword_stance"), True, S),
    (_t("anim.sword"), "base", "Sword_Attack", _t("anim.sword_strike"), False, S),
    (_t("anim.sword"), "base", "Sword_Regular_A", _t("anim.combo_strike_1"), False, S),
    (_t("anim.sword"), "base", "Sword_Regular_B", _t("anim.combo_strike_2"), False, S),
    (_t("anim.sword"), "base", "Sword_Regular_C", _t("anim.combo_strike_3"), False, S),
    (_t("anim.sword"), "base", "Sword_Regular_Combo", _t("anim.three_strike_combo"), False, S),
    (_t("anim.sword"), "addon", "Sword_Attack_Air_Vertical", _t("anim.jumping_overhead_strike"), False, S),
    (_t("anim.sword"), "base", "Sword_Block", _t("anim.sword_block"), False, S),
    (_t("anim.sword_and_shield"), "base", "Idle_Shield", _t("anim.shield_stance"), True, SS),
    (_t("anim.sword_and_shield"), "base", "Shield_OneShot", _t("anim.shield_bash"), False, SS),
    (_t("anim.sword_and_shield"), "base", "Idle_Shield_Break", _t("anim.shield_broken"), False, SS),
    (_t("anim.sword_and_shield"), "shield", "idle_loop", _t("anim.stance_procedural"), True, SS),
    (_t("anim.sword_and_shield"), "shield", "walk_loop", _t("anim.walk_with_shield"), True, SS),
    (_t("anim.sword_and_shield"), "shield", "attack_slash", _t("anim.strike_from_behind_the_shield"), False, SS),
    (_t("anim.sword_and_shield"), "shield", "block_loop", _t("anim.shield_block"), True, SS),
    (_t("anim.two_handed_sword"), "twohand", "idle_loop", _t("anim.stance"), True, GS),
    (_t("anim.two_handed_sword"), "twohand", "walk_loop", _t("anim.walk"), True, GS),
    (_t("anim.two_handed_sword"), "twohand", "run_loop", _t("anim.run"), True, GS),
    (_t("anim.two_handed_sword"), "twohand", "attack_slash", _t("anim.diagonal_strike"), False, GS),
    (_t("anim.two_handed_sword"), "twohand", "attack_overhead", _t("anim.overhead_strike"), False, GS),
    (_t("anim.two_handed_sword"), "twohand", "block_loop", _t("anim.block"), True, GS),
    (_t("anim.two_handed_sword"), "twohand", "hit", _t("anim.hit"), False, GS),
    (_t("anim.defence"), "addon", "Defend", _t("anim.cover_with_arms"), False, []),
    (_t("anim.defence"), "base", "Hit_Knockback", _t("anim.knocked_back"), False, []),
    (_t("anim.magic"), "base", "Spell_Simple_Enter", _t("anim.spell_wind_up"), False, []),
    (_t("anim.magic"), "base", "Spell_Simple_Idle", _t("anim.spell_hold"), True, []),
    (_t("anim.magic"), "base", "Spell_Simple_Shoot", _t("anim.spell_release"), False, []),
    (_t("anim.magic"), "base", "Spell_Simple_Exit", _t("anim.spell_finish"), False, []),
    (_t("anim.magic"), "addon", "Two-hand Blast", _t("anim.two_handed_force_blast"), False, []),
    (_t("anim.magic"), "addon", "Power Up", _t("anim.charging_power"), False, []),
    (_t("anim.magic"), "addon", "Levitate Entrance", _t("anim.levitation_lift_off"), False, []),
    (_t("anim.magic"), "addon", "Levitate Idle", _t("anim.levitation"), True, []),
    (_t("anim.magic"), "addon", "Meditate", _t("anim.meditation"), True, []),
    (_t("anim.unarmed"), "addon", "Fighting Idle", _t("anim.fighting_stance"), True, []),
    (_t("anim.unarmed"), "addon", "Fighting Left Jab", _t("anim.left_jab"), False, []),
    (_t("anim.unarmed"), "addon", "Fighting Right Jab", _t("anim.right_jab"), False, []),
    (_t("anim.unarmed"), "base", "Punch_Cross", _t("anim.straight_punch"), False, []),
    (_t("anim.unarmed"), "base", "Melee_Hook", _t("anim.hook"), False, []),
    (_t("anim.unarmed"), "mocap", "Kick_Breach", _t("anim.kick"), False, []),
    (_t("anim.unarmed"), "addon", "Attack_Ground_Pound", _t("anim.ground_slam"), False, []),
    (_t("anim.bow_and_throwing"), "addon", "Bow Pull Back", _t("anim.bow_draw"), False, []),
    (_t("anim.bow_and_throwing"), "addon", "Bow Pull Hold", _t("anim.bow_hold"), True, []),
    (_t("anim.bow_and_throwing"), "addon", "Bow Release", _t("anim.bow_shoot"), False, []),
    (_t("anim.bow_and_throwing"), "base", "OverhandThrow", _t("anim.overhand_throw"), False, []),
    (_t("anim.bow_and_throwing"), "addon", "Throw Object", _t("anim.item_throw"), False, []),
    (_t("anim.damage_and_death"), "base", "Hit_Chest", _t("anim.hit_in_the_chest"), False, []),
    (_t("anim.damage_and_death"), "base", "Hit_Head", _t("anim.hit_in_the_head"), False, []),
    (_t("anim.damage_and_death"), "addon", "Idle Hurt", _t("anim.wounded"), True, []),
    (_t("anim.damage_and_death"), "addon", "Dizzy", _t("anim.stunned"), True, []),
    (_t("anim.damage_and_death"), "addon", "Death_A", _t("anim.death_1"), False, []),
    (_t("anim.damage_and_death"), "addon", "Death_B", _t("anim.death_2"), False, []),
    (_t("anim.damage_and_death"), "addon", "Death_C", _t("anim.death_3"), False, []),
    (_t("anim.damage_and_death"), "base", "Death_D", _t("anim.death_4"), False, []),
    (_t("anim.emotes"), "addon", "Victory", _t("anim.victory"), False, []),
    (_t("anim.emotes"), "addon", "Victory Fist Pump", _t("anim.victory_fist_up"), False, []),
    (_t("anim.emotes"), "addon", "Greeting", _t("anim.greeting"), False, []),
    (_t("anim.emotes"), "addon", "Angry", _t("anim.angry"), False, []),
    (_t("anim.emotes"), "mocap", "Insult", _t("anim.taunt"), False, []),
    (_t("anim.emotes"), "mocap", "Cheer_One_arm", _t("anim.cheering"), False, []),
]
PROC = {"twohand": dict(twohand=True, blade="fingers"), "shield": dict(shield=True, blade="fingers")}


def _key(group, source, clip):   # the clip's name in the GLB and the page: unique, ASCII
    return re.sub(r"[^0-9A-Za-z]+", "_", f"{source}_{clip}").strip("_")


def build(cfg, rigged, out_html, log=print):
    import hanim as HA
    rigged, out_html = Path(rigged), Path(out_html)
    blender = cfg.get("blender_exe") or r"D:\Blender 5.2\blender.exe"
    name = re.sub(r"[^\w-]+", "_", re.sub(r"_landmarks_rigged$|_rigged$", "", rigged.stem)).strip("_") or "character"
    work = Path(cfg["work_dir"]) / "anim_gallery" / name
    work.mkdir(parents=True, exist_ok=True)
    srcs = {k: str(v) for k, v in SRC.items()}
    for kind, kw in PROC.items():   # the procedural clips this page needs, on the character's own skeleton
        want = sorted({c[2] for c in CLIPS if c[1] == kind})
        glb = work / f"proc_{kind}.glb"
        if not glb.exists() or glb.stat().st_mtime < rigged.stat().st_mtime:
            log(_t("anim.procedural_clips", kind, ', '.join(want)))
            HA.animate(blender, rigged, glb, want, **kw)
        srcs[kind] = str(glb)
    spec = {}
    for group, source, clip, label, loop, weapons in CLIPS:
        k = _key(group, source, clip)
        spec[k] = {"name": k, "loop": loop, "glb": srcs[source], "action": clip, **({"bones": "ue"} if source in SRC else {})}
    text = json.dumps(spec, ensure_ascii=False, indent=1)
    out_glb = work / "gallery.glb"
    fresh = (out_glb.exists() and (work / "map.json").exists() and (work / "map.json").read_text(encoding="utf-8") == text
             and out_glb.stat().st_mtime > max([rigged.stat().st_mtime, (ROOT / "blender_retarget_fbx.py").stat().st_mtime]
                                               + [Path(srcs[k]).stat().st_mtime for k in PROC]))
    (work / "map.json").write_text(text, encoding="utf-8")
    if fresh:   # the same clips on the same character: only the page is rebuilt
        log(_t("anim.clips_are_already_retargeted"))
    else:
        _retarget(blender, rigged, out_glb, work, len(spec), log)
    return _page(out_glb, out_html, name, work, log)


def _retarget(blender, rigged, out_glb, work, n, log):
    log(_t("anim.blender_is_retargeting_clips_onto", n))
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_retarget_fbx.py"), "--", str(rigged),
                        str(out_glb), str(work / "map.json")], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if "RETARGET_GLB" not in r.stdout:
        raise RuntimeError(_t("anim.retargeting_failed") + (r.stdout + r.stderr)[-1500:])


def _page(out_glb, out_html, name, work, log):
    import fbxanim as FA
    from glbfix import set_metallic
    done = {c["name"] for c in json.loads(Path(str(out_glb) + ".json").read_text(encoding="utf-8"))}
    clips = [dict(id=_key(g, s, c), label=lab, group=g, loop=lp, weapons=w)
             for g, s, c, lab, lp, w in CLIPS if _key(g, s, c) in done]
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
    missing = [c[2] for c in CLIPS if _key(*c[:3]) not in done]
    log(_t("anim.done_clips", out_html, len(clips)) + (_t("anim.not_retargeted", ', '.join(missing)) if missing else ""))
    return out_html


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    import sf3d_tool as T
    build(T.load_config(), sys.argv[1], sys.argv[2])
