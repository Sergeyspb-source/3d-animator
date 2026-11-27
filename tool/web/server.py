"""3d-animator's web UI: the app's Python (sf3d_ui and the other modules) behind a FastAPI server, the page built by Vite
(tool/web/front -> front/dist). The app's interface, on its own port (7890 by default; 3d-animator.vbs / 3d-animator.bat start it):

    D:\\conda\\envs\\sf3d\\python.exe tool\\web\\server.py [--port 7890]

Test bench: SF3D_EXPORT_DIR / SF3D_WORK_DIR point export and work elsewhere (the user's export is never touched),
and the language is then not saved into config.json.

API: /api/state, /api/i18n, /api/gpu, /api/events (SSE: task, log, gpu), /api/tasks, /api/upload, /api/file,
/api/open, /api/objects, /api/models/... ."""
import argparse
import asyncio
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
TOOL = HERE.parent
sys.path.insert(0, str(TOOL))
sys.path.insert(0, str(HERE))

import uvicorn  # noqa: E402
from fastapi import FastAPI, File, HTTPException, Request, UploadFile  # noqa: E402
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import models as M  # noqa: E402  (patches sf3d_tool.load_config first)
import equip as EQ  # noqa: E402
import character as CH  # noqa: E402
import face as FC  # noqa: E402
import anims as AN  # noqa: E402
import creature as CRW  # noqa: E402
import env as EV  # noqa: E402
import tools_api as TA  # noqa: E402

for k, env in (("export_dir", "SF3D_EXPORT_DIR"), ("work_dir", "SF3D_WORK_DIR")):
    if os.environ.get(env):
        M.ENV_OVER[k] = os.environ[env]
TEST_BENCH = bool(M.ENV_OVER)

import i18n  # noqa: E402
import sf3d_tool as T  # noqa: E402
import sf3d_ui as UI  # noqa: E402
from i18n import t as _t  # noqa: E402
from tasks import Bus, Task, TaskQueue, NO_WINDOW  # noqa: E402

DIST = HERE / "front" / "dist"
bus = Bus()
tasks = TaskQueue(bus)
app = FastAPI(title="3d-animator", docs_url=None, redoc_url=None)
for ext, typ in ((".glb", "model/gltf-binary"), (".gltf", "model/gltf+json"), (".webp", "image/webp"), (".json", "application/json")):
    mimetypes.add_type(typ, ext)


# ------------------------------------------------------------------ paths the page may read
def _roots():
    cfg = T.load_config()
    roots = [Path(cfg["export_dir"]), Path(cfg["work_dir"])]
    if cfg.get("input_dir"):
        roots.append(Path(cfg["input_dir"]))
    return [r.resolve() for r in roots]


def _allowed(path: str) -> Path:
    try:
        p = Path(path).resolve()
    except (OSError, ValueError):
        raise HTTPException(400, "bad path")
    if not any(p == r or r in p.parents for r in _roots()):
        raise HTTPException(403, "outside export / work / input")
    return p


# ------------------------------------------------------------------ GPU
GPU = {"used": None, "total": None, "free": None, "util": None, "sf3d": False, "t": 0}


def _gpu_read():
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=memory.used,memory.total,utilization.gpu", "--format=csv,noheader,nounits"],
                             capture_output=True, text=True, timeout=10, creationflags=NO_WINDOW).stdout
        used, total, util = (int(x) for x in out.strip().splitlines()[0].split(","))
        return {"used": used, "total": total, "free": total - used, "util": util}
    except Exception:  # noqa: BLE001
        return {"used": None, "total": None, "free": None, "util": None}


def _gpu_loop():
    while True:
        g = {**_gpu_read(), "sf3d": bool(UI._state.get("model") is not None and UI._state.get("on_gpu"))}
        changed = any(g[k] != GPU.get(k) for k in g)
        GPU.update(g, t=time.time())
        if changed:
            bus.publish({"type": "gpu", "gpu": dict(GPU)})
        time.sleep(3)


threading.Thread(target=_gpu_loop, name="gpu-monitor", daemon=True).start()


# ------------------------------------------------------------------ state, texts, events
@app.get("/api/state")
def state():
    cfg = T.load_config()
    return {"lang": i18n.LANG, "langs": i18n.LANGS, "test_bench": TEST_BENCH,
            "export_dir": cfg["export_dir"], "work_dir": cfg["work_dir"], "input_dir": cfg.get("input_dir"),
            "drafts_dir": M.drafts_root(cfg).as_posix(),
            "has_openrouter_key": bool(cfg.get("openrouter_key") or os.environ.get("OPENROUTER_API_KEY")),
            "gpu": dict(GPU), "tasks": tasks.list(),
            "bridges": {"equip": [UI.armour_gen_ui.TARGET_ID, UI.armour_gen_ui.GO_ID],
                        "markup": UI.landmarks.TARGET_ID, "pose": UI.landmarks.TARGET_ID + "_pose",
                        "rigface": UI.landmarks.TARGET_ID + "_rigface",
                        "creature": [UI.CR.REQ_ID, UI.CR.REQ_GO], "paint": [UI.CR.PAINT_ID, UI.CR.PAINT_GO],
                        "wear": list(CH.wear_ids())}}


def _lang_file(code):
    try:
        return json.loads((TOOL / "lang" / f"{code}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


@app.get("/api/i18n")
def texts(lang: str = ""):
    code = lang if lang in i18n.LANGS else i18n.LANG
    return {"lang": code, "text": {**_lang_file(i18n.DEFAULT), **_lang_file(code)}}


@app.post("/api/lang")
async def set_lang(req: Request):
    code = (await req.json()).get("lang")
    if code not in i18n.LANGS:
        raise HTTPException(400, "unknown language")
    # the server's own messages switch at once; the setting is config.json "lang" (the handler modules read it too)
    i18n.LANG = code
    i18n._TEXT = i18n._load(code)
    i18n._BASE = i18n._TEXT if code == i18n.DEFAULT else i18n._load(i18n.DEFAULT)
    if not TEST_BENCH:
        i18n.set_lang(code)
    return {"ok": True, "lang": code}


@app.get("/api/gpu")
def gpu():
    return dict(GPU)


@app.post("/api/gpu/unload")
def gpu_unload():
    if tasks.running is not None and tasks.running.meta.get("engine") == "sf3d":
        return {"ok": False, "log": _t("web.busy")}
    return {"ok": True, "log": UI.unload_model()}


@app.get("/api/events")
async def events(request: Request):
    loop = asyncio.get_running_loop()
    q = bus.subscribe(loop)

    async def stream():
        try:
            yield "retry: 2000\n\n"
            yield "data: " + json.dumps({"type": "hello", "tasks": tasks.list(), "gpu": dict(GPU)}, ensure_ascii=False) + "\n\n"
            while True:
                if await request.is_disconnected():
                    break
                try:
                    ev = await asyncio.wait_for(q.get(), timeout=15)
                    yield "data: " + json.dumps(ev, ensure_ascii=False) + "\n\n"
                except asyncio.TimeoutError:
                    yield ": ping\n\n"
        finally:
            bus.unsubscribe(q)

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-store", "X-Accel-Buffering": "no"})


# ------------------------------------------------------------------ tasks
@app.get("/api/tasks")
def task_list():
    return tasks.list()


@app.get("/api/tasks/{tid}")
def task_get(tid: str):
    t = tasks.get(tid)
    if t is None:
        raise HTTPException(404, "no such task")
    return {**t.summary(), "lines": t.lines}


@app.post("/api/tasks/{tid}/cancel")
def task_cancel(tid: str):
    return {"ok": tasks.cancel(tid)}


# ------------------------------------------------------------------ files
@app.post("/api/upload")
async def upload(files: list[UploadFile] = File(...)):
    cfg = T.load_config()
    folder = Path(cfg["work_dir"]) / "web_uploads" / time.strftime("%Y%m%d") / uuid.uuid4().hex[:8]
    folder.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        name = Path(f.filename or "file").name
        stem, suf = Path(name).stem, Path(name).suffix.lower()
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in stem)[:60] or "file"
        dst = folder / f"{safe}{suf}"
        dst.write_bytes(await f.read())
        out.append({"name": name, "path": dst.as_posix()})
    return out


@app.get("/api/file")
def file(path: str):
    p = _allowed(path)
    if not p.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(p, headers={"Cache-Control": "no-cache"}, content_disposition_type="inline")


@app.post("/api/open")
async def open_folder(req: Request):
    p = _allowed((await req.json()).get("path") or "")
    if p.is_file():
        p = p.parent
    if not p.exists():
        raise HTTPException(404, "no such folder")
    os.startfile(str(p))  # noqa: S606  (Windows: the folder in Explorer)
    return {"ok": True}


# ------------------------------------------------------------------ the current object (character / creature)
def _obj(value, as_character=False, as_creature=False):
    """One model of the scene, once: «creature» is what its passport says (the group it is listed under);
    as_character / as_creature: the sections it works in. A model can be both: one of export/character with no
    skeleton yet (either may take it), a creature with a humanoid's skeleton (its jaw there, its clips and armour here)."""
    f = UI._char_files(value)
    if not f:
        return None
    creature = UI.CR.is_creature(f["dir"], f["name"])
    clips, worn = UI._char_counts(f)
    return {"id": value, "name": f["name"], "creature": creature, "as_character": as_character, "as_creature": as_creature,
            "dir": f["dir"].as_posix(),
            "rigged": f["rigged"].as_posix() if f["rigged"] else None,
            "source": f["source"].as_posix() if f["source"] else None,
            "landmark": bool(f["landmark"]), "auto": bool(f["auto"]), "parts": bool(f["parts"]),
            "speech": clips, "worn": worn,
            "tags": UI._char_tags(f) if not creature else (UI.CR_ICON["rig"] if f["rigged"] else UI.ICON["none"])}


def _kinds() -> tuple:
    """The ids the «Character» sections take and the ids the «Creatures» section takes (they may share some)."""
    return [v for _, v in UI._characters()], [v for _, v in UI._characters(True)]


@app.get("/api/objects")
def objects():
    chars, crs = _kinds()
    sc, sr = set(chars), set(crs)
    objs = [o for o in (_obj(v, v in sc, v in sr) for v in dict.fromkeys(chars + crs)) if o]
    ids = {o["id"] for o in objs}
    try:   # the one current object of the web UI (a character or a creature), else the handler modules' current character
        cur = _web_memo().read_text(encoding="utf-8").strip()
    except OSError:
        cur = ""
    return {"characters": [o for o in objs if not o["creature"]], "creatures": [o for o in objs if o["creature"]],
            "current": cur if cur in ids else UI._char_default()}


def _web_memo() -> Path:
    return Path(T.load_config()["work_dir"]) / "web_current_object.txt"


@app.post("/api/objects/current")
async def object_current(req: Request):
    v = (await req.json()).get("id")
    if not v:
        return {"ok": False}
    _web_memo().write_text(v, encoding="utf-8")
    # the handler modules' own memo of each kind it is (their «current character» / «current creature»)
    chars, crs = _kinds()
    if v in crs:
        UI.creature_remember(v)
    if v in chars or v not in crs:
        UI.char_remember(v)
    return {"ok": True}


# ------------------------------------------------------------------ «Models»
ENGINE_NAMES = {"sf3d": "SF3D", "hunyuan": "Hunyuan3D", "trellis": "TRELLIS.2"}


@app.get("/api/models/options")
def model_options():
    return M.options(T.load_config())


@app.post("/api/models/generate")
async def model_generate(req: Request):
    p = await req.json()
    engine = p.get("engine") or "sf3d"
    if engine not in M.ENGINES:
        raise HTTPException(400, "unknown engine")
    for f in [*(p.get("files") or []), *((p.get("views") or {}).values())]:
        if f:
            _allowed(f)
    if engine == "hunyuan" and not (p.get("views") or {}).get("front"):
        return JSONResponse({"ok": False, "log": _t("ui.at_least_the_front_picture_is_needed")})
    if engine != "hunyuan" and not p.get("files"):
        return JSONResponse({"ok": False, "log": _t("ui.add_at_least_one_picture_first")})
    name = (p.get("name") or "").strip() or Path((p.get("files") or [None])[0] or (p.get("views") or {}).get("front") or "model").stem
    title = f"{ENGINE_NAMES[engine]} · {name}"
    t = tasks.submit(Task("model", title, M.generate_task(p), meta={"engine": engine, "name": name, "category": p.get("category")}))
    return {"ok": True, "task": t.summary()}


@app.get("/api/models/drafts")
def model_drafts():
    return M.drafts()


@app.get("/api/models/released")
def model_released():
    return M.released()


@app.post("/api/models/release")
async def model_release(req: Request):
    p = await req.json()
    return M.release(p.get("category") or "", p.get("stem") or "", bool(p.get("replace")))


@app.post("/api/models/discard")
async def model_discard(req: Request):
    p = await req.json()
    return M.discard(p.get("category") or "", p.get("stem") or "")


# ------------------------------------------------------------------ «Models → Improve» (web/improve.py, tool/model_improve.py)
import improve as IM  # noqa: E402


@app.get("/api/models/improve/status")
def improve_status(category: str, stem: str):
    return IM.status(category, stem)


@app.post("/api/models/improve/run")
async def improve_run(req: Request):
    t = tasks.submit(IM.run_task(await req.json()))
    return {"ok": True, "task": t.summary()}


@app.post("/api/models/improve/codex")
async def improve_codex(req: Request):
    p = await req.json()
    if not p.get("views"):
        return JSONResponse({"ok": False, "log": ""})
    t = tasks.submit(IM.codex_task(p))
    return {"ok": True, "task": t.summary()}


@app.get("/api/models/improve/align")
async def improve_align(category: str, stem: str, view: str):
    return await asyncio.to_thread(IM.align, category, stem, view)


@app.post("/api/models/improve/pins")
async def improve_pins(req: Request):
    p = await req.json()
    return IM.pins(p["category"], p["stem"], p["view"], p.get("pins") or [])


@app.post("/api/models/improve/picture")
async def improve_picture(req: Request):
    p = await req.json()
    path = p.get("path")
    if path:
        _allowed(path)
    return IM.picture(p["category"], p["stem"], p["view"], path)


@app.post("/api/models/improve/codex_accept")
async def improve_codex_accept(req: Request):
    p = await req.json()
    return IM.codex_accept(p["category"], p["stem"], p["view"], bool(p.get("accept")))


@app.post("/api/models/improve/undo")
async def improve_undo(req: Request):
    p = await req.json()
    return IM.undo(p["category"], p["stem"])


# ------------------------------------------------------------------ «Equipment» and «Looks»: the procedural editor
@app.get("/editor/equip")
def editor_equip(rigged: str):
    p = _allowed(rigged)
    if not p.is_file():
        raise HTTPException(404, "no such model")
    return HTMLResponse(EQ.page(str(p)), headers={"Cache-Control": "no-store"})


@app.get("/api/equip/made")
def equip_made(rigged: str):
    _allowed(rigged)
    return EQ.made(rigged)


@app.get("/api/equip/qa")
def equip_qa(rigged: str, item: str):
    _allowed(rigged)
    return EQ.qa_report(rigged, item)


@app.post("/api/equip/action")
async def equip_action(req: Request):
    text = (await req.body()).decode("utf-8")
    try:
        r = EQ.parse(text)
    except ValueError as e:
        raise HTTPException(400, str(e))
    _allowed(r["rigged"])
    key = EQ.heavy(r)
    if key:   # long: into the GPU queue (the editor waits for its answer file meanwhile)
        def job(task):
            res = EQ.run(text)
            task.set_lines(str(res.get("log") or "").splitlines())   # (the editor's answer, in the dock's log too)
            return res
        t = tasks.submit(Task("equip", EQ.title(r, key), job,
                              meta={"action": r.get("action") or "generate", "rigged": r["rigged"], "item": EQ.item_of(r)}))
        return {"ok": True, "queued": True, "task": t.summary()}
    return {"ok": True, **(await asyncio.wrap_future(EQ.quick(text)))}


# ------------------------------------------------------------------ «Character»
def _char(value: str) -> str:
    if not value or UI._char_files(value) is None or not UI._char_files(value)["dir"].is_dir():
        raise HTTPException(404, "no such character")
    return value


def _page_or_note(make):
    """An editor's page, or a short page saying why it cannot open (shown in the frame)."""
    try:
        return HTMLResponse(make(), headers={"Cache-Control": "no-store"})
    except ValueError as e:
        return HTMLResponse(f"<!doctype html><meta charset=utf-8><body style='background:#1d2126;color:#dde1e5;"
                            f"font:14px system-ui;display:grid;place-items:center;height:100vh;margin:0'>{e}</body>")


def _char_task(key, value, fn, what):
    t = tasks.submit(Task("char", _t(key) + " · " + value.split("/", 1)[-1], fn, meta={"char": value, "what": what}))
    return {"ok": True, "task": t.summary()}


@app.get("/api/char/overview")
def char_overview(id: str):
    return CH.overview(_char(id))


@app.post("/api/char/add")
async def char_add(req: Request):
    return CH.add(str(_allowed((await req.json()).get("path") or "")))


@app.post("/api/char/delete")
async def char_delete(req: Request):
    return CH.delete(_char((await req.json()).get("id") or ""))


@app.post("/api/char/rig")
async def char_rig(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    return _char_task("web.task_rig", v, CH.rig_task(v, p.get("naming") or "mixamo", p.get("tries") or 3), "rig")


@app.post("/api/char/seams")
async def char_seams(req: Request):
    v = _char((await req.json()).get("id") or "")
    return _char_task("web.task_seams", v, CH.seams_task(v), "seams")


@app.post("/api/char/split")
async def char_split(req: Request):
    v = _char((await req.json()).get("id") or "")
    return _char_task("web.task_split", v, CH.split_task(v), "split")


@app.get("/api/char/options")
def char_options():
    return CH.options()


@app.post("/api/char/options")
async def char_options_save(req: Request):
    return CH.save_options(await req.json())


@app.get("/editor/landmarks")
def editor_landmarks(id: str, mode: str = "markup"):
    v = _char(id)
    return _page_or_note(lambda: CH.landmarks_page(v, mode if mode in ("markup", "pose", "view") else "markup"))


@app.post("/api/char/landmark_build")
async def char_landmark_build(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    return _char_task("web.task_landmarks", v, CH.landmark_build_task(v, p.get("markup") or "", p.get("options") or {}), "landmarks")


@app.post("/api/char/keep_fist")
async def char_keep_fist(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    try:
        if p.get("rig"):
            return {"ok": True, "log": CH.keep_rig_fist(v, p.get("markup") or "")}
        return {"ok": CH.keep_fist(v, p.get("markup") or "")}
    except Exception as e:  # noqa: BLE001  (the markup's own field: never in the way of editing)
        return {"ok": False, "log": str(e)}


@app.get("/editor/wear")
def editor_wear(id: str):
    v = _char(id)
    return _page_or_note(lambda: CH.wear_page(v))


@app.post("/api/char/wear")
async def char_wear(req: Request):
    text = (await req.body()).decode("utf-8")
    try:
        r = json.loads(text)
    except ValueError:
        raise HTTPException(400, "bad request")
    _allowed(r.get("rigged") or "")
    v = next((c for _, c in UI._characters() if (UI._char_files(c) or {}).get("rigged") and
              Path(UI._char_files(c)["rigged"]).resolve() == Path(r["rigged"]).resolve()), "")
    key = "web.task_wardrobe" if r.get("action") == "wardrobe" else "web.task_wear"
    t = tasks.submit(Task("char", _t(key) + " · " + str(r.get("item") or Path(r["rigged"]).stem), CH.wear_task(text),
                          meta={"char": v, "what": "wear"}))
    return {"ok": True, "task": t.summary()}


@app.post("/api/outfit/scan")
async def outfit_scan(req: Request):
    model = str(_allowed((await req.json()).get("model") or ""))
    return await asyncio.to_thread(CH.outfit_scan, model)


@app.post("/api/outfit/run")
async def outfit_run(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    model = str(_allowed(p.get("model") or ""))
    return _char_task("web.task_outfit", v, CH.outfit_task(v, model, p.get("set_name") or "", p.get("names") or [], p.get("slots") or []), "outfit")


@app.get("/editor/bones")
def editor_bones(id: str):
    v = _char(id)
    return _page_or_note(lambda: CH.bones_page(v))


@app.post("/api/char/weights")
async def char_weights(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    return _char_task("web.task_weights", v, CH.weights_task(v, p.get("mesh") or "", p.get("group") or "",
                                                            p.get("strength", 1.0), p.get("size", 1.0)), "weights")


@app.post("/api/char/wardrobe")
async def char_wardrobe(req: Request):
    v = _char((await req.json()).get("id") or "")
    return _char_task("web.task_wardrobe", v, CH.wardrobe_task(v), "wardrobe")


# ------------------------------------------------------------------ «Character → Face»
@app.get("/api/face/state")
def face_state(id: str):
    return FC.state(_char(id))


@app.get("/editor/face")
def editor_face(id: str, mode: str = "mark", clip: str = ""):
    v = _char(id)
    return _page_or_note(lambda: FC.say_page(v, clip) if mode == "say" else FC.mark_page(v))


@app.post("/api/face/build")
async def face_build(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    return _char_task("web.task_face", v, FC.build_task(v, p.get("markup") or ""), "face")


@app.post("/api/face/parts/preview")
async def face_parts_preview(req: Request):
    r = FC.preview(await req.json())
    return r if isinstance(r, dict) else await asyncio.wrap_future(r)


@app.post("/api/face/parts/save")
async def face_parts_save(req: Request):
    p = await req.json()
    name = (p.get("name") or "face_parts").strip()
    t = tasks.submit(Task("face_parts", _t("web.task_face_parts") + " · " + name, FC.save_task(p.get("params") or {}, name),
                          meta={"name": name}))
    return {"ok": True, "task": t.summary()}


@app.post("/api/face/lipsync")
async def face_lipsync(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    audio = str(_allowed(p.get("audio") or ""))
    return _char_task("web.task_lipsync", v, FC.lipsync_task(v, audio, p.get("text") or "", p.get("lang") or "ru"), "lipsync")


# ------------------------------------------------------------------ «Character → Animations»
@app.get("/api/anim/options")
def anim_options():
    return AN.options()


@app.get("/api/anim/state")
def anim_state(id: str):
    return AN.state(_char(id))


@app.post("/api/anim/procedural")
async def anim_procedural(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    return _char_task("web.task_anim", v, AN.procedural_task(v, p.get("clips") or [], p.get("manner") or "normal",
                                                              str(p.get("seed") or ""), p.get("death") or "back"), "anim")


@app.post("/api/anim/check")
async def anim_check(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    kind = "fbx" if p.get("kind") == "fbx" else "anim"
    return _char_task("web.task_clipcheck", v, AN.check_task(v, kind), "clipcheck")


@app.get("/api/anim/fbx_table")
def anim_fbx_table(folder: str = ""):
    if folder:
        _allowed(folder)
    return AN.fbx_table(folder)


@app.post("/api/anim/fbx_save")
async def anim_fbx_save(req: Request):
    p = await req.json()
    if p.get("folder"):
        _allowed(p["folder"])
    return AN.fbx_save(p.get("folder") or "", p.get("rows") or [])


@app.post("/api/anim/fbx")
async def anim_fbx(req: Request):
    p = await req.json()
    v = _char(p.get("id") or "")
    if p.get("folder"):
        _allowed(p["folder"])
    return _char_task("web.task_fbx", v, AN.fbx_task(v, p.get("folder") or "", p.get("rows") or [], p.get("weapon") or ""), "fbx")


@app.get("/editor/clips")
def editor_clips(id: str, kind: str = "fbx", weapon: str = ""):
    v = _char(id)
    return _page_or_note(lambda: AN.viewer_page(v, "anim" if kind == "anim" else "fbx", weapon))


# ------------------------------------------------------------------ «Creatures»
@app.get("/api/cr/overview")
def cr_overview(id: str):
    return CRW.overview(_char(id))


@app.post("/api/cr/add")
async def cr_add(req: Request):
    return CRW.add(str(_allowed((await req.json()).get("path") or "")))


def _cr_post(key, what, make):
    async def handler(req: Request):
        p = await req.json()
        v = _char(p.get("id") or "")
        return _char_task(key, v, make(v, p), what)
    return handler


app.post("/api/cr/rig")(_cr_post("web.task_cr_rig", "rig", lambda v, p: CRW.rig_task(v)))
app.post("/api/cr/straighten")(_cr_post("web.task_cr_straighten", "straighten", lambda v, p: CRW.straighten_task(v)))
app.post("/api/cr/restore")(_cr_post("web.task_cr_restore", "restore", lambda v, p: CRW.restore_task(v)))
app.post("/api/cr/request")(_cr_post("web.task_cr_markup", "markup", lambda v, p: CRW.request_task(v, p.get("text") or "{}")))
app.post("/api/cr/animate")(_cr_post("web.task_cr_clips", "clips", lambda v, p: CRW.animate_task(v, p.get("picks") or {})))
app.post("/api/cr/check")(_cr_post("web.task_clipcheck", "clipcheck", lambda v, p: CRW.check_task(v)))
app.post("/api/cr/godot")(_cr_post("web.task_cr_godot", "godot", lambda v, p: CRW.godot_task(v)))
app.post("/api/cr/paint")(_cr_post("web.task_cr_paint", "paint", lambda v, p: CRW.paint_task(v, p.get("text") or "{}")))
app.post("/api/cr/mend")(_cr_post("web.task_cr_mend", "mend", lambda v, p: CRW.mend_task(v, "normals" if p.get("what") == "normals" else "holes")))
app.post("/api/cr/template")(_cr_post("ct.task_template", "template", lambda v, p: CRW.template_task(v, p.get("text") or "{}")))


@app.get("/api/cr/clip_options")
def cr_clip_options(id: str):
    return CRW.clip_options(_char(id))


@app.get("/editor/creature")
def editor_creature(id: str, what: str = "viewer", current: str = ""):
    v = _char(id)
    make = {"viewer": lambda: CRW.viewer_page(v), "clips": lambda: CRW.clips_page(v),
            "paint": lambda: CRW.paint_page(v, current), "template": lambda: CRW.template_page(v)}.get(what, lambda: CRW.viewer_page(v))
    return _page_or_note(make)


@app.post("/upload")
async def page_upload(files: list[UploadFile] = File(...)):
    """/upload as the colouring page uses it (the form Gradio had): the files land in creatures.upload_root()
    (paint_save takes pictures only from there) and their paths come back as a list."""
    import creatures as CR
    root = CR.upload_root() / uuid.uuid4().hex[:12]
    root.mkdir(parents=True, exist_ok=True)
    out = []
    for f in files:
        name = "".join(c if c.isalnum() or c in "-_." else "_" for c in Path(f.filename or "file").name)[:80] or "file"
        dst = root / name
        dst.write_bytes(await f.read())
        out.append(str(dst))
    return out


# ------------------------------------------------------------------ «Environment», «Models → Reference / Model materials»
ENV_JOBS = {"surface": ("web.task_surface", EV.surface_task), "fx_flip": ("web.task_fx", EV.fx_flip_task),
            "fx_sprite": ("web.task_fx_sprite", EV.fx_sprite_task), "fx_scenes": ("web.task_fx_scenes", EV.fx_scenes_task),
            "kit_build": ("web.task_kit", EV.kit_build_task), "kit_scene": ("web.task_kit_scene", EV.kit_scene_task),
            "destr": ("web.task_destr", EV.destr_task), "ref": ("web.task_ref", EV.ref_task), "ref_views": ("web.task_ref_views", EV.ref_views_task)}


@app.get("/api/env/options")
def env_options():
    return EV.options()


@app.post("/api/env/{job}")
async def env_job(job: str, req: Request):
    if job not in ENV_JOBS:
        raise HTTPException(404, "no such job")
    p = await req.json()
    for k in ("own", "front"):
        if p.get(k):
            _allowed(p[k])
    for f in p.get("style_files") or []:
        _allowed(f)
    key, make = ENV_JOBS[job]
    what = (p.get("name") or p.get("asset") or p.get("obj") or p.get("desc") or "").strip()[:40]
    t = tasks.submit(Task("env", _t(key) + (f" · {what}" if what else ""), make(p), meta={"job": job}))
    return {"ok": True, "task": t.summary()}


@app.get("/api/env/asset_model")
def env_asset_model(asset: str):
    return {"model": EV.asset_model(asset)}


@app.post("/api/ref/describe")
async def ref_describe(req: Request):
    p = await req.json()
    for f in p.get("files") or []:
        _allowed(f)
    return await asyncio.to_thread(EV.ref_describe, p)


@app.post("/api/ref/style_save")
async def ref_style_save(req: Request):
    p = await req.json()
    for f in p.get("files") or []:
        _allowed(f)
    return EV.ref_style_save(p)


@app.get("/api/mat/analyze")
def mat_analyze(asset: str):
    return EV.mat_analyze(asset)


@app.post("/api/mat/apply")
async def mat_apply(req: Request):
    p = await req.json()
    t = tasks.submit(Task("env", _t("web.task_mat") + " · " + (p.get("asset") or ""), EV.mat_apply_task(p.get("asset") or "", p.get("values") or []),
                          meta={"job": "mat"}))
    return {"ok": True, "task": t.summary()}


# ------------------------------------------------------------------ batch, video memory, settings
@app.post("/api/models/release_all")
def model_release_all():
    return M.release_all()


@app.get("/api/batch/scan")
def batch_scan(root: str = "", category: str = "prop"):
    if root:
        _allowed(root)
    return TA.batch_scan(root or (T.load_config().get("input_dir") or ""), category)


@app.post("/api/batch/run")
async def batch_run(req: Request):
    p = await req.json()
    if p.get("root"):
        _allowed(p["root"])
    t = tasks.submit(Task("model", _t("web.task_batch") + " · " + Path(p.get("root") or "").name, TA.batch_task(p), meta={"engine": "batch"}))
    return {"ok": True, "task": t.summary()}


@app.get("/api/gpu/holders")
async def gpu_holders():
    return await asyncio.to_thread(TA.gpu_holders)


@app.post("/api/gpu/close")
async def gpu_close(req: Request):
    p = await req.json()
    return await asyncio.to_thread(TA.gpu_close, int(p.get("pid") or 0), bool(p.get("force")))


@app.get("/api/settings")
def settings_get():
    return TA.settings()


@app.post("/api/settings")
async def settings_save(req: Request):
    return TA.save_settings(await req.json(), TEST_BENCH)


@app.get("/api/settings/openrouter_models")
async def openrouter_models():
    try:
        return await asyncio.to_thread(TA.openrouter_models)
    except Exception as e:  # noqa: BLE001
        return JSONResponse({"error": str(e)}, status_code=502)


@app.get("/file={rest:path}")
def page_file(rest: str):
    """The paths the app's editors ask for (/file=<absolute path>, the form Gradio had): export, work, input only."""
    p = _allowed(rest)
    if not p.is_file():
        raise HTTPException(404, "no such file")
    return FileResponse(p, headers={"Cache-Control": "no-cache"}, content_disposition_type="inline")


# ------------------------------------------------------------------ the page
if (DIST / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")


@app.get("/{rest:path}")
def page(rest: str = ""):
    f = DIST / rest
    if rest and f.is_file() and DIST in f.resolve().parents:
        return FileResponse(f)
    index = DIST / "index.html"
    if not index.exists():
        return JSONResponse({"error": "the page is not built: cd tool\\web\\front && npm install && npm run build"}, 503)
    return FileResponse(index, headers={"Cache-Control": "no-cache"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=int(os.environ.get("SF3D_WEB_PORT", 7890)))
    ap.add_argument("--host", default="127.0.0.1")
    a = ap.parse_args()
    uvicorn.run(app, host=a.host, port=a.port, log_level="warning")


if __name__ == "__main__":
    main()
