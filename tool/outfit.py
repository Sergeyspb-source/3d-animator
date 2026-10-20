"""Carry a whole outfit from a dressed, segmented character (Tripo: "goblin in armour" + Smart Segment) onto the
rigged base body. Used by the GUI section "Перенести сет с одетой модели".

scan()      lists the segments with a guessed slot and a small picture of each,
transfer()  (generator of log lines) does the rest:
  1) join the segments and rig the dressed model (UniRig, cached per source file), split it into body regions,
  2) write each item (segments with the same slot are joined, e.g. face + helmet, wrap + shoe), decimated to a
     triangle budget,
  3) per item: skin it on the dressed skeleton, carry it over to the base body by the skeletons and bare skin
     (rigid for heads and helmets), fit it there (push-out, inner wall down to the body, body mask, skin weights),
  4) manifests (<item>.item.json, <item>.mask.json), previews, set.json and a picture of the whole set.
"""
import json
import subprocess
import time
from pathlib import Path

import rigging as RG

ROOT = Path(__file__).resolve().parent

# GUI label -> (item stem, fit slot, triangle budget, rigid)
SLOTS = {
    "— не брать (кожа, тело)": None,
    "голова целиком (лицо + шлем / волосы)": ("head", "head", 3500, True),
    "шлем": ("helmet", "helmet", 2500, True),
    "нагрудник / туника / куртка": ("chest", "chest", 6000, False),
    "пояс / юбка": ("belt", "belt", 3000, False),
    "штаны": ("pants", "pants", 4000, False),
    "наплечник левый": ("pauldron_L", "pauldrons", 1500, False),
    "наплечник правый": ("pauldron_R", "pauldrons", 1500, False),
    "наруч левый": ("bracer_L", "bracers", 1200, False),
    "наруч правый": ("bracer_R", "bracers", 1200, False),
    "перчатка левая": ("glove_L", "gloves", 1200, False),
    "перчатка правая": ("glove_R", "gloves", 1200, False),
    "рука целиком левая (наплечник + наруч + перчатка)": ("arm_L", "arms", 6000, False),
    "рука целиком правая (наплечник + наруч + перчатка)": ("arm_R", "arms", 6000, False),
    "бедро левое (набедренник)": ("thigh_L", "pants", 2500, False),
    "бедро правое (набедренник)": ("thigh_R", "pants", 2500, False),
    "сапог левый (обмотка, ботинок)": ("boot_L", "boots", 2500, False),
    "сапог правый (обмотка, ботинок)": ("boot_R", "boots", 2500, False),
}
GUESS_TO_LABEL = {
    "skip": "— не брать (кожа, тело)", "head": "голова целиком (лицо + шлем / волосы)", "helmet": "шлем",
    "chest": "нагрудник / туника / куртка", "belt": "пояс / юбка",
    "pauldron левый": "наплечник левый", "pauldron правый": "наплечник правый",
    "bracer левый": "наруч левый", "bracer правый": "наруч правый",
    "boot левый": "сапог левый (обмотка, ботинок)", "boot правый": "сапог правый (обмотка, ботинок)",
    "arm левый": "рука целиком левая (наплечник + наруч + перчатка)",
    "arm правый": "рука целиком правая (наплечник + наруч + перчатка)",
    "thigh левый": "бедро левое (набедренник)", "thigh правый": "бедро правое (набедренник)",
}


def _blender(blender, script, *args, timeout=1800):
    r = subprocess.run([blender, "-b", "-P", str(ROOT / script), "--", *map(str, args)], capture_output=True,
                       text=True, encoding="utf-8", errors="replace", timeout=timeout,
                       creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
    return r.stdout.splitlines(), r.stdout + r.stderr


def scan(model, work, blender):
    """[{name, faces, guess label, thumb, ...}] for the segments of the dressed model."""
    lines, raw = _blender(blender, "blender_outfit_scan.py", model, Path(work) / "scan", timeout=600)
    segs = [json.loads(x.split(" ", 1)[1]) for x in lines if x.startswith("SCAN_SEG ")]
    if not segs:
        raise RuntimeError("не удалось прочитать сегменты: " + raw[-300:])
    for s in segs:
        s["label"] = GUESS_TO_LABEL.get(s["guess"], "— не брать (кожа, тело)")
    return segs


def items_from(assign):
    """{segment: label} -> {item stem: (slot, budget, rigid, [segments])}"""
    items = {}
    for seg, label in assign.items():
        spec = SLOTS.get(label)
        if not spec:
            continue
        stem, slot, budget, rigid = spec
        items.setdefault(stem, (slot, budget, rigid, []))[3].append(seg)
    return items


def transfer(model, assign, base_parts, out_dir, work, blender, rig_dressed):
    """Generator of log lines. rig_dressed(src, dst) must rig src into dst (a generator of log lines, returning
    True on success); the GUI passes its own rigging (VRAM gate, retries)."""
    model, base_parts, out_dir, work = Path(model), Path(base_parts), Path(out_dir), Path(work)
    out_dir.mkdir(parents=True, exist_ok=True)
    work.mkdir(parents=True, exist_ok=True)
    items = items_from(assign)
    if not items:
        yield "Ни одному сегменту не назначен слот: нечего переносить."
        return False
    t0 = time.time()

    # ---- 1. rigged dressed model, cached for this very source file
    stamp = f"{model.stat().st_size}:{int(model.stat().st_mtime)}"
    meta = work / "dressed.json"
    parts = work / "dressed_parts.glb"
    cached = parts.exists() and meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("stamp") == stamp
    if cached:
        yield "Одетая модель уже заригана раньше, беру готовый скелет."
    else:
        yield "Склеиваю сегменты в одну модель..."
        full = work / "dressed_full.glb"
        lines, raw = _blender(blender, "blender_join.py", model, full)
        if not any(x.startswith("JOIN_OK") for x in lines):
            yield "ОШИБКА склейки: " + raw[-300:]
            return False
        rigged = work / "dressed_rigged.glb"
        ok = yield from rig_dressed(full, rigged)
        if not ok:
            yield "ОШИБКА: одетую модель не удалось заригать."
            return False
        yield "Разбиваю одетую модель на области тела..."
        RG.split_parts(rigged, parts, blender)
        meta.write_text(json.dumps(dict(stamp=stamp, source=str(model))), encoding="utf-8")

    # ---- 2. items, decimated to their budgets
    pieces = work / "pieces"
    args = [f"{seg}={stem}:{budget}" for stem, (slot, budget, rigid, segs) in items.items() for seg in segs]
    yield f"Выгружаю предметы ({len(items)}): " + ", ".join(items) + "..."
    lines, raw = _blender(blender, "blender_export_segments.py", model, pieces, *args)
    for x in lines:
        if x.startswith(("SEG_DECIMATE", "SEG_MISSING")):
            yield "  " + x.replace("SEG_DECIMATE", "упрощено:").replace("SEG_MISSING", "нет сегмента:")
    if not any(x.startswith("SEG_OK") for x in lines):
        yield "ОШИБКА выгрузки сегментов: " + raw[-300:]
        return False

    # ---- 3. per item: dressed skeleton -> transfer -> fit on the base body
    done = []
    for stem, (slot, budget, rigid, segs) in items.items():
        yield f"[{stem}] перенос ({slot})..."
        on_src, xfer, dst = work / f"{stem}_on_src.glb", work / f"{stem}_xfer.glb", out_dir / f"{stem}.glb"
        lines, raw = _blender(blender, "blender_fit_armor.py", parts, pieces / f"{stem}.glb", slot, on_src,
                              "mode=keep", "offset=0", "neck_plug=0", "fill=0", "mask=0")
        if not any(x.startswith("FIT_OK") for x in lines):
            yield f"[{stem}] ОШИБКА привязки к одетой модели: " + raw[-300:]
            continue
        lines, raw = _blender(blender, "blender_transfer_armor.py", parts, on_src, base_parts, xfer,
                              f"armour_all={pieces / '_all_armour.glb'}", f"rigid={1 if rigid else 0}")
        rep = next((x for x in lines if x.startswith("XFER_REPORT")), None)
        if not any(x.startswith("XFER_OK") for x in lines):
            yield f"[{stem}] ОШИБКА переноса: " + raw[-300:]
            continue
        if rep and slot != "head":  # the base head is hidden whole under a replacement head
            yield f"[{stem}] " + rep.replace("XFER_REPORT armour off the body:", "зазор до тела:").replace(
                "body vertices under the armour", "вершин тела под бронёй").replace("poking out", "вылезает")
        try:
            man = RG.fit_armour(base_parts, xfer, slot, dst, blender, {"mode": "keep", "offset": 0.004},
                                hide_body=(slot == "head"))
        except Exception as e:  # noqa: BLE001
            yield f"[{stem}] ОШИБКА подгонки: {e}"
            continue
        man.update(set=out_dir.name, segments=segs, source=model.name)
        dst.with_suffix(".item.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
        done.append((stem, slot, man))
        yield f"[{stem}] готово: {dst.name}" + (" (+ маска тела)" if man.get("mask") else "")

    # ---- 4. the whole set
    if not done:
        return False
    hides = sorted({h for _, _, m in done for h in m.get("hides", [])})
    (out_dir / "set.json").write_text(json.dumps(dict(
        name=out_dir.name, body=base_parts.name, source=str(model),
        items=[dict(id=s, slot=sl, mesh=f"{s}.glb", manifest=f"{s}.item.json") for s, sl, _ in done],
        hides=hides), indent=2, ensure_ascii=False), encoding="utf-8")
    lines, _ = _blender(blender, "blender_fit_preview.py", base_parts,
                        ";".join(str(out_dir / f"{s}.glb") for s, _, _ in done), out_dir / "set_preview.png",
                        ",".join(hides), timeout=600)
    yield f"Сет готов за {time.time() - t0:.0f} с: {len(done)} предметов в {out_dir}"
    return True
