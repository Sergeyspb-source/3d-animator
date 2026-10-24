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
from i18n import t as _t

ROOT = Path(__file__).resolve().parent

# GUI label -> (item stem, fit slot, triangle budget, rigid)
SLOTS = {
    _t("outfit.skip_skin_body"): None,
    _t("outfit.whole_head_face_helmet_hair"): ("head", "head", 3500, True),
    _t("outfit.helmet"): ("helmet", "helmet", 2500, True),
    _t("outfit.breastplate_tunic_jacket"): ("chest", "chest", 6000, False),
    _t("outfit.belt_skirt"): ("belt", "belt", 3000, False),
    _t("outfit.trousers"): ("pants", "pants", 4000, False),
    _t("outfit.left_pauldron"): ("pauldron_L", "pauldrons", 1500, False),
    _t("outfit.right_pauldron"): ("pauldron_R", "pauldrons", 1500, False),
    _t("outfit.left_bracer"): ("bracer_L", "bracers", 1200, False),
    _t("outfit.right_bracer"): ("bracer_R", "bracers", 1200, False),
    _t("outfit.left_glove"): ("glove_L", "gloves", 1200, False),
    _t("outfit.right_glove"): ("glove_R", "gloves", 1200, False),
    _t("outfit.whole_left_arm_pauldron_bracer_glove"): ("arm_L", "arms", 6000, False),
    _t("outfit.whole_right_arm_pauldron_bracer"): ("arm_R", "arms", 6000, False),
    _t("outfit.left_thigh_cuisse"): ("thigh_L", "pants", 2500, False),
    _t("outfit.right_thigh_cuisse"): ("thigh_R", "pants", 2500, False),
    _t("outfit.left_boot_wrap_shoe"): ("boot_L", "boots", 2500, False),
    _t("outfit.right_boot_wrap_shoe"): ("boot_R", "boots", 2500, False),
}
GUESS_TO_LABEL = {
    "skip": _t("outfit.skip_skin_body"), "head": _t("outfit.whole_head_face_helmet_hair"), "helmet": _t("outfit.helmet"),
    "chest": _t("outfit.breastplate_tunic_jacket"), "belt": _t("outfit.belt_skirt"),
    "pauldron левый": _t("outfit.left_pauldron"), "pauldron правый": _t("outfit.right_pauldron"),
    "bracer левый": _t("outfit.left_bracer"), "bracer правый": _t("outfit.right_bracer"),
    "boot левый": _t("outfit.left_boot_wrap_shoe"), "boot правый": _t("outfit.right_boot_wrap_shoe"),
    "arm левый": _t("outfit.whole_left_arm_pauldron_bracer_glove"),
    "arm правый": _t("outfit.whole_right_arm_pauldron_bracer"),
    "thigh левый": _t("outfit.left_thigh_cuisse"), "thigh правый": _t("outfit.right_thigh_cuisse"),
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
        raise RuntimeError(_t("outfit.could_not_read_the_segments") + raw[-300:])
    for s in segs:
        s["label"] = GUESS_TO_LABEL.get(s["guess"], _t("outfit.skip_skin_body"))
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
        yield _t("outfit.no_segment_has_a_slot_nothing_to")
        return False
    t0 = time.time()

    # ---- 1. rigged dressed model, cached for this very source file
    stamp = f"{model.stat().st_size}:{int(model.stat().st_mtime)}"
    meta = work / "dressed.json"
    parts = work / "dressed_parts.glb"
    cached = parts.exists() and meta.exists() and json.loads(meta.read_text(encoding="utf-8")).get("stamp") == stamp
    if cached:
        yield _t("outfit.the_dressed_model_was_rigged_before")
    else:
        yield _t("outfit.joining_the_segments_into_one_model")
        full = work / "dressed_full.glb"
        lines, raw = _blender(blender, "blender_join.py", model, full)
        if not any(x.startswith("JOIN_OK") for x in lines):
            yield _t("outfit.error_joining") + raw[-300:]
            return False
        rigged = work / "dressed_rigged.glb"
        ok = yield from rig_dressed(full, rigged)
        if not ok:
            yield _t("outfit.error_the_dressed_model_could_not_be")
            return False
        yield _t("outfit.splitting_the_dressed_model_into")
        RG.split_parts(rigged, parts, blender)
        meta.write_text(json.dumps(dict(stamp=stamp, source=str(model))), encoding="utf-8")

    # ---- 2. items, decimated to their budgets
    pieces = work / "pieces"
    args = [f"{seg}={stem}:{budget}" for stem, (slot, budget, rigid, segs) in items.items() for seg in segs]
    yield _t("outfit.exporting_the_items", len(items)) + ", ".join(items) + "..."
    lines, raw = _blender(blender, "blender_export_segments.py", model, pieces, *args)
    for x in lines:
        if x.startswith(("SEG_DECIMATE", "SEG_MISSING")):
            yield "  " + x.replace("SEG_DECIMATE", _t("outfit.simplified")).replace("SEG_MISSING", _t("outfit.no_segment"))
    if not any(x.startswith("SEG_OK") for x in lines):
        yield _t("outfit.error_exporting_the_segments") + raw[-300:]
        return False

    # ---- 3. per item: dressed skeleton -> transfer -> fit on the base body
    done = []
    for stem, (slot, budget, rigid, segs) in items.items():
        yield _t("outfit.transfer", stem, slot)
        on_src, xfer, dst = work / f"{stem}_on_src.glb", work / f"{stem}_xfer.glb", out_dir / f"{stem}.glb"
        lines, raw = _blender(blender, "blender_fit_armor.py", parts, pieces / f"{stem}.glb", slot, on_src,
                              "mode=keep", "offset=0", "neck_plug=0", "fill=0", "mask=0")
        if not any(x.startswith("FIT_OK") for x in lines):
            yield _t("outfit.error_binding_to_the_dressed_model", stem) + raw[-300:]
            continue
        lines, raw = _blender(blender, "blender_transfer_armor.py", parts, on_src, base_parts, xfer,
                              f"armour_all={pieces / '_all_armour.glb'}", f"rigid={1 if rigid else 0}")
        rep = next((x for x in lines if x.startswith("XFER_REPORT")), None)
        if not any(x.startswith("XFER_OK") for x in lines):
            yield _t("outfit.transfer_error", stem) + raw[-300:]
            continue
        if rep and slot != "head":  # the base head is hidden whole under a replacement head
            yield f"[{stem}] " + rep.replace("XFER_REPORT armour off the body:", _t("outfit.gap_to_the_body")).replace(
                "body vertices under the armour", _t("outfit.body_vertices_under_the_armour")).replace("poking out", _t("outfit.poking_out"))
        try:
            man = RG.fit_armour(base_parts, xfer, slot, dst, blender, {"mode": "keep", "offset": 0.004},
                                hide_body=(slot == "head"))
        except Exception as e:  # noqa: BLE001
            yield _t("outfit.fitting_error", stem, e)
            continue
        man.update(set=out_dir.name, segments=segs, source=model.name)
        dst.with_suffix(".item.json").write_text(json.dumps(man, indent=2, ensure_ascii=False), encoding="utf-8")
        done.append((stem, slot, man))
        yield _t("outfit.done", stem, dst.name) + (_t("outfit.body_mask") if man.get("mask") else "")

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
    yield _t("outfit.the_set_is_ready_in_s_items_in", time.time() - t0, len(done), out_dir)
    return True
