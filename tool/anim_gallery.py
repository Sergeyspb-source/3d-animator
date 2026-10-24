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

ROOT = Path(__file__).resolve().parent
M2M = ROOT.parent / "Animations" / "Mesh2Motion" / "glb"
SRC = {"base": M2M / "human-base-animations.glb", "addon": M2M / "human-addon-animations.glb",
       "mocap": M2M / "human-mocap-animations.glb"}
S, SS, GS = ["sword"], ["sword", "shield"], ["greatsword"]   # what is in the hands

# (group, source, clip in the source, label, loop, weapons); "twohand" / "shield": SF3D's procedural clips made with
# both hands on one sword / a shield on the left arm
CLIPS = [
    ("Передвижение", "base", "Idle_A", "Покой", True, []),
    ("Передвижение", "addon", "Idle_Subtle", "Покой, сдержанно", True, []),
    ("Передвижение", "base", "Walk", "Ходьба", True, []),
    ("Передвижение", "addon", "Walk_Large", "Ходьба тяжёлая", True, []),
    ("Передвижение", "base", "Jog", "Лёгкий бег", True, []),
    ("Передвижение", "base", "Sprint", "Спринт", True, []),
    ("Передвижение", "addon", "Walk_Backwards", "Шаг назад", True, []),
    ("Передвижение", "addon", "Strafe_left", "Приставной шаг влево", True, []),
    ("Передвижение", "addon", "Strafe_right", "Приставной шаг вправо", True, []),
    ("Передвижение", "base", "Crouch_Idle", "Присед", True, []),
    ("Передвижение", "base", "Crouch_Walk", "Шаг вприсядку", True, []),
    ("Передвижение", "addon", "Walk_Stealth", "Крадучись", True, []),
    ("Передвижение", "addon", "Run_Stealth", "Бег крадучись", True, []),
    ("Передвижение", "addon", "Crawl", "Ползком", True, []),
    ("Передвижение", "mocap", "Turn_Left_90", "Поворот влево 90°", False, []),
    ("Передвижение", "mocap", "Turn_Right_90", "Поворот вправо 90°", False, []),
    ("Передвижение", "mocap", "Turn_Left_180", "Разворот 180°", False, []),
    ("Прыжки", "base", "Jump_Start", "Прыжок: толчок", False, []),
    ("Прыжки", "base", "Jump_air", "Прыжок: в воздухе", True, []),
    ("Прыжки", "base", "Jump_Land", "Прыжок: приземление", False, []),
    ("Прыжки", "addon", "Jump_2", "Прыжок с места", False, []),
    ("Прыжки", "addon", "Run Jump", "Прыжок с разбега", False, []),
    ("Прыжки", "base", "NinjaJump_Start", "Высокий прыжок: толчок", False, []),
    ("Прыжки", "base", "NinjaJump_Idle", "Высокий прыжок: в воздухе", True, []),
    ("Прыжки", "base", "NinjaJump_Land", "Высокий прыжок: приземление", False, []),
    ("Прыжки", "addon", "Backflip", "Сальто назад", False, []),
    ("Прыжки", "addon", "Land_Three_Point", "Приземление на три точки", False, []),
    ("Уклонения и перекаты", "addon", "Dodge_back", "Отскок назад", False, []),
    ("Уклонения и перекаты", "addon", "Dodge_left", "Уклон влево", False, []),
    ("Уклонения и перекаты", "addon", "Dodge_right", "Уклон вправо", False, []),
    ("Уклонения и перекаты", "base", "Roll", "Перекат", False, []),
    ("Уклонения и перекаты", "base", "Slide_Start", "Подкат: начало", False, []),
    ("Уклонения и перекаты", "base", "Slide", "Подкат", True, []),
    ("Уклонения и перекаты", "base", "Slide_Exit", "Подкат: выход", False, []),
    ("Меч", "base", "Idle_Sword", "Стойка с мечом", True, S),
    ("Меч", "base", "Sword_Attack", "Удар мечом", False, S),
    ("Меч", "base", "Sword_Regular_A", "Серия: удар 1", False, S),
    ("Меч", "base", "Sword_Regular_B", "Серия: удар 2", False, S),
    ("Меч", "base", "Sword_Regular_C", "Серия: удар 3", False, S),
    ("Меч", "base", "Sword_Regular_Combo", "Серия из трёх ударов", False, S),
    ("Меч", "addon", "Sword_Attack_Air_Vertical", "Удар сверху в прыжке", False, S),
    ("Меч", "base", "Sword_Block", "Блок мечом", False, S),
    ("Меч и щит", "base", "Idle_Shield", "Стойка со щитом", True, SS),
    ("Меч и щит", "base", "Shield_OneShot", "Удар щитом", False, SS),
    ("Меч и щит", "base", "Idle_Shield_Break", "Щит пробит", False, SS),
    ("Меч и щит", "shield", "idle_loop", "Стойка (процедурная)", True, SS),
    ("Меч и щит", "shield", "walk_loop", "Ходьба со щитом", True, SS),
    ("Меч и щит", "shield", "attack_slash", "Удар из-за щита", False, SS),
    ("Меч и щит", "shield", "block_loop", "Блок щитом", True, SS),
    ("Двуручный меч", "twohand", "idle_loop", "Стойка", True, GS),
    ("Двуручный меч", "twohand", "walk_loop", "Ходьба", True, GS),
    ("Двуручный меч", "twohand", "run_loop", "Бег", True, GS),
    ("Двуручный меч", "twohand", "attack_slash", "Удар наискось", False, GS),
    ("Двуручный меч", "twohand", "attack_overhead", "Удар сверху", False, GS),
    ("Двуручный меч", "twohand", "block_loop", "Блок", True, GS),
    ("Двуручный меч", "twohand", "hit", "Получил удар", False, GS),
    ("Защита", "addon", "Defend", "Закрыться руками", False, []),
    ("Защита", "base", "Hit_Knockback", "Отброшен ударом", False, []),
    ("Магия", "base", "Spell_Simple_Enter", "Заклинание: подготовка", False, []),
    ("Магия", "base", "Spell_Simple_Idle", "Заклинание: удержание", True, []),
    ("Магия", "base", "Spell_Simple_Shoot", "Заклинание: выпуск", False, []),
    ("Магия", "base", "Spell_Simple_Exit", "Заклинание: завершение", False, []),
    ("Магия", "addon", "Two-hand Blast", "Удар силой двумя руками", False, []),
    ("Магия", "addon", "Power Up", "Накопление силы", False, []),
    ("Магия", "addon", "Levitate Entrance", "Левитация: взлёт", False, []),
    ("Магия", "addon", "Levitate Idle", "Левитация", True, []),
    ("Магия", "addon", "Meditate", "Медитация", True, []),
    ("Рукопашная", "addon", "Fighting Idle", "Боевая стойка", True, []),
    ("Рукопашная", "addon", "Fighting Left Jab", "Джеб левой", False, []),
    ("Рукопашная", "addon", "Fighting Right Jab", "Джеб правой", False, []),
    ("Рукопашная", "base", "Punch_Cross", "Прямой удар", False, []),
    ("Рукопашная", "base", "Melee_Hook", "Хук", False, []),
    ("Рукопашная", "mocap", "Kick_Breach", "Удар ногой", False, []),
    ("Рукопашная", "addon", "Attack_Ground_Pound", "Удар по земле", False, []),
    ("Лук и метание", "addon", "Bow Pull Back", "Лук: натянуть", False, []),
    ("Лук и метание", "addon", "Bow Pull Hold", "Лук: держать", True, []),
    ("Лук и метание", "addon", "Bow Release", "Лук: выстрел", False, []),
    ("Лук и метание", "base", "OverhandThrow", "Бросок сверху", False, []),
    ("Лук и метание", "addon", "Throw Object", "Бросок предмета", False, []),
    ("Урон и смерть", "base", "Hit_Chest", "Удар в грудь", False, []),
    ("Урон и смерть", "base", "Hit_Head", "Удар в голову", False, []),
    ("Урон и смерть", "addon", "Idle Hurt", "Ранен", True, []),
    ("Урон и смерть", "addon", "Dizzy", "Оглушён", True, []),
    ("Урон и смерть", "addon", "Death_A", "Смерть 1", False, []),
    ("Урон и смерть", "addon", "Death_B", "Смерть 2", False, []),
    ("Урон и смерть", "addon", "Death_C", "Смерть 3", False, []),
    ("Урон и смерть", "base", "Death_D", "Смерть 4", False, []),
    ("Эмоции", "addon", "Victory", "Победа", False, []),
    ("Эмоции", "addon", "Victory Fist Pump", "Победа: кулак вверх", False, []),
    ("Эмоции", "addon", "Greeting", "Приветствие", False, []),
    ("Эмоции", "addon", "Angry", "Злится", False, []),
    ("Эмоции", "mocap", "Insult", "Насмешка", False, []),
    ("Эмоции", "mocap", "Cheer_One_arm", "Ликование", False, []),
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
            log(f"процедурные клипы ({kind}): {', '.join(want)}")
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
        log("клипы уже перенесены, собираю страницу")
    else:
        _retarget(blender, rigged, out_glb, work, len(spec), log)
    return _page(out_glb, out_html, name, work, log)


def _retarget(blender, rigged, out_glb, work, n, log):
    log(f"Blender переносит {n} клипов на скелет…")
    r = subprocess.run([blender, "-b", "--factory-startup", "-P", str(ROOT / "blender_retarget_fbx.py"), "--", str(rigged),
                        str(out_glb), str(work / "map.json")], capture_output=True, text=True, encoding="utf-8",
                       errors="replace", timeout=3600, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    if "RETARGET_GLB" not in r.stdout:
        raise RuntimeError("ретаргет не удался: " + (r.stdout + r.stderr)[-1500:])


def _page(out_glb, out_html, name, work, log):
    import fbxanim as FA
    from glbfix import set_metallic
    done = {c["name"] for c in json.loads(Path(str(out_glb) + ".json").read_text(encoding="utf-8"))}
    clips = [dict(id=_key(g, s, c), label=lab, group=g, loop=lp, weapons=w)
             for g, s, c, lab, lp, w in CLIPS if _key(g, s, c) in done]
    weapons = []   # the goblin presets of the Mixamo tab for the models and their sizes; placed by the hand (fit)
    for wid, preset in (("sword", FA.WEAPON_SETS["Гоблин: меч и щит"][0]), ("shield", dict(FA.WEAPON_SETS["Гоблин: меч и щит"][1], bone="LeftForeArm")),
                        ("greatsword", FA.WEAPON_SETS["Гоблин: двуручный меч"][0])):
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
    tpl = (ROOT / "viewer_anim.html").read_text(encoding="utf-8")
    # the weapon presets were set on goblin_hero, 1 unit tall: the page scales them by this character's height
    page = (tpl.replace("@@DATA@@", json.dumps(dict(clips=clips, ref_height=1.0), ensure_ascii=False))
               .replace("@@GLB@@", base64.b64encode(FA.shrink_glb(out_glb, 1024)).decode())
               .replace("@@WEAPONS@@", json.dumps(weapons))
               .replace("<title>Просмотр анимаций</title>", f"<title>Анимации: {name}</title>"))
    out_html.parent.mkdir(parents=True, exist_ok=True)
    out_html.write_text(page, encoding="utf-8")
    missing = [c[2] for c in CLIPS if _key(*c[:3]) not in done]
    log(f"готово: {out_html} — {len(clips)} клипов" + (f"; не перенеслись: {', '.join(missing)}" if missing else ""))
    return out_html


if __name__ == "__main__":
    sys.path.insert(0, str(ROOT))
    import sf3d_tool as T
    build(T.load_config(), sys.argv[1], sys.argv[2])
