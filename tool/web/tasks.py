"""The web UI's task queue: every job that may use the GPU (SF3D, Hunyuan, TRELLIS.2, UniRig, Blender bakes) runs on
one worker thread, one at a time, in the order asked; the page sees each task's state and log as events.

The jobs themselves are the app's own functions (sf3d_ui.generate ... - generators). A task's
function gets the Task and reports through it: set_lines (the whole log as it is now: the diff goes to the page),
set_progress, result. Cancelling a running task stops its generator at its next step and kills the programs it
started (Hunyuan's python, trellis-cli, Blender): subprocess.Popen is wrapped to know whose they are."""
import asyncio
import itertools
import queue
import re
import subprocess
import threading
import time
import traceback
from collections import OrderedDict

NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_ids = itertools.count(1)
_current = threading.local()   # the task the thread runs (the worker's)


class Cancelled(Exception):
    pass


class Bus:
    """Events to every open page (SSE): publish from any thread, each page reads its own asyncio queue."""

    def __init__(self):
        self._subs = []
        self._lock = threading.Lock()

    def subscribe(self, loop):
        q = asyncio.Queue(maxsize=2000)
        with self._lock:
            self._subs.append((loop, q))
        return q

    def unsubscribe(self, q):
        with self._lock:
            self._subs = [(lp, x) for lp, x in self._subs if x is not q]

    def publish(self, event):
        with self._lock:
            subs = list(self._subs)
        for loop, q in subs:
            try:
                loop.call_soon_threadsafe(_put, q, event)
            except RuntimeError:   # (that page's loop is gone)
                self.unsubscribe(q)


def _put(q, event):
    if q.full():   # a page that stopped reading: drop its oldest
        try:
            q.get_nowait()
        except asyncio.QueueEmpty:
            pass
    q.put_nowait(event)


_PCT = re.compile(r"(\d{1,3})\s?%")
_STEP = re.compile(r"(\d+)\s*(?:из|of|/)\s*(\d+)")   # «шаг 6 из 12», «step 6 of 12», «3/8»


class Task:
    def __init__(self, kind, title, fn, gpu=True, meta=None):
        self.id = str(next(_ids))
        self.kind, self.title, self.fn, self.gpu, self.meta = kind, title, fn, gpu, meta or {}
        self.status = "queued"
        self.created, self.started, self.finished = time.time(), None, None
        self.progress = None   # 0..1, None: unknown
        self.lines, self._sent = [], []
        self.result, self.error = None, None
        self.cancel = threading.Event()
        self.procs = []
        self.bus = None

    def summary(self):
        return {"id": self.id, "kind": self.kind, "title": self.title, "status": self.status, "gpu": self.gpu,
                "created": self.created, "started": self.started, "finished": self.finished,
                "progress": self.progress, "result": self.result, "error": self.error, "meta": self.meta,
                "last": self.lines[-1] if self.lines else ""}

    # ------------------------------------------------------------------ reporting (from the task's thread)
    def set_lines(self, lines):
        self.lines = list(lines)
        if self.progress is None or self._pct_from_log:
            for ln in reversed(self.lines[-2:]):
                m, s = _PCT.search(ln), _STEP.search(ln)
                if m or (s and 0 < int(s.group(2)) <= 1000):
                    self._pct_from_log = True
                    self.progress = min(1.0, int(m.group(1)) / 100 if m else int(s.group(1)) / int(s.group(2)))
                    break
        self.check()

    _pct_from_log = False

    def set_progress(self, value):
        self._pct_from_log = False
        self.progress = None if value is None else max(0.0, min(1.0, float(value)))
        self.check()

    def check(self):
        """Raises Cancelled once the task was cancelled (called at every report)."""
        if self.cancel.is_set():
            raise Cancelled()

    def diff(self):
        """The log's change since the last one sent: (first changed line, lines from it) or None."""
        new, old = self.lines, self._sent
        if new == old:
            return None
        i = 0
        n = min(len(new), len(old))
        while i < n and new[i] == old[i]:
            i += 1
        self._sent = list(new)
        return i, new[i:]


class _TrackedPopen(subprocess.Popen):
    """subprocess.Popen that remembers the programs a task started (to stop them when it is cancelled)."""

    def __init__(self, *a, **k):
        super().__init__(*a, **k)
        t = getattr(_current, "task", None)
        if t is not None:
            t.procs.append(self)


subprocess.Popen = _TrackedPopen   # (subprocess.run and check_output build theirs through this name too)


def kill_tree(p):
    if p.poll() is None:
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(p.pid)], capture_output=True, creationflags=NO_WINDOW)


class TaskQueue:
    KEEP = 60   # finished tasks kept for the page

    def __init__(self, bus):
        self.bus = bus
        self.tasks = OrderedDict()
        self._q = queue.Queue()
        self._lock = threading.Lock()
        self.running = None
        threading.Thread(target=self._worker, name="gpu-worker", daemon=True).start()
        threading.Thread(target=self._flusher, name="log-flusher", daemon=True).start()

    def submit(self, task):
        task.bus, task.queue = self.bus, self
        with self._lock:
            self.tasks[task.id] = task
            done = [k for k, t in self.tasks.items() if t.finished]
            for k in done[:-self.KEEP]:
                del self.tasks[k]
        self._q.put(task)
        self._publish(task)
        return task

    def list(self):
        with self._lock:
            return [t.summary() for t in self.tasks.values()]

    def get(self, tid):
        return self.tasks.get(tid)

    def cancel(self, tid):
        t = self.tasks.get(tid)
        if t is None or t.finished:
            return False
        t.cancel.set()
        if t.status == "queued":
            t.status, t.finished = "cancelled", time.time()
            self._publish(t)
        else:
            for p in list(t.procs):
                kill_tree(p)
        return True

    def waiting(self):
        return [t for t in self.tasks.values() if t.status == "queued"]

    # ------------------------------------------------------------------ the worker
    def _worker(self):
        while True:
            t = self._q.get()
            if t.status != "queued":
                continue
            self.running = t
            _current.task = t
            t.status, t.started = "running", time.time()
            self._publish(t)
            try:
                res = t.fn(t)
                if res is not None:
                    t.result = res
                t.status = "cancelled" if t.cancel.is_set() else "done"
            except Cancelled:
                t.status = "cancelled"
            except Exception as e:  # noqa: BLE001  (the page must hear what went wrong)
                t.status, t.error = "error", f"{type(e).__name__}: {e}"
                t.lines.append(traceback.format_exc(limit=6))
            finally:
                if t.cancel.is_set():   # (a finished job's programs stay: the Godot fitting room is a window it opened)
                    for p in list(t.procs):
                        kill_tree(p)
                t.procs.clear()
                _current.task = None
                t.finished = time.time()
                if t.progress is not None and t.status == "done":
                    t.progress = 1.0
                self.running = None
                self._flush(t)
                self._publish(t)

    def _publish(self, t):
        self.bus.publish({"type": "task", "task": t.summary()})

    def _flush(self, t):
        d = t.diff()
        if d is not None:
            self.bus.publish({"type": "log", "id": t.id, "at": d[0], "lines": d[1]})

    def _flusher(self):
        last = {}
        while True:
            time.sleep(0.25)
            t = self.running
            if t is None:
                continue
            self._flush(t)
            key = (t.progress, t.lines[-1] if t.lines else "")
            if last.get(t.id) != key:   # (the progress bar and the last line in the task list)
                last[t.id] = key
                self._publish(t)
