"""Run Blender in the machine-wide heavy lane, so parallel Claude sessions do not take the whole CPU at once.

When several sessions render or bake with Blender on all 12 threads, the VPN/proxy gets no CPU time and every session
drops with "API Error: ECONNREFUSED / ENOTFOUND". This waits for the "heavy" lane shared with the game project's
sessions (named mutex Local\\GameProjectGodot_Lane_heavy, the same as the game's tools\\run_queued.ps1 -Lane heavy):
one heavy job at a time on the machine, the rest wait their turn. Blender then runs with THREADS threads and
below-normal priority.

    D:\\conda\\envs\\sf3d\\python.exe tool\\blender_queue.py [--threads 6] [--wait-minutes 180] -- -b -P script.py -- args
    D:\\conda\\envs\\sf3d\\python.exe tool\\blender_queue.py --status

Everything after the first "--" goes to blender.exe unchanged; the exit code is Blender's (124: the lane stayed busy).
A holder that dies leaves the mutex "abandoned" and the next waiter takes it, so nothing sticks.
Other heavy jobs (Hunyuan, UniRig, TRELLIS, big Python) and Godot runs go through the game's queue:
    powershell -NoProfile -ExecutionPolicy Bypass -File "D:\\My projects\\game-project-godot\\tools\\run_queued.ps1" -Lane heavy|godot -Exe <program> <args>
Env: BLENDER_QUEUE_THREADS, BLENDER_EXE.
"""
import ctypes
import os
import subprocess
import sys
import time
from ctypes import wintypes
from pathlib import Path

BLENDER = os.environ.get("BLENDER_EXE", r"D:\Blender 5.2\blender.exe")
LANE = r"Local\GameProjectGodot_Lane_heavy"
INFO = Path(r"D:\conda\tmp\blender_queue\holder.txt")
BELOW_NORMAL = 0x00004000
WAIT_OBJECT_0, WAIT_ABANDONED, WAIT_TIMEOUT = 0x0, 0x80, 0x102

k32 = ctypes.WinDLL("kernel32", use_last_error=True)
k32.CreateMutexW.restype = wintypes.HANDLE
k32.CreateMutexW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.LPCWSTR]
k32.WaitForSingleObject.restype = wintypes.DWORD
k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
k32.ReleaseMutex.argtypes = [wintypes.HANDLE]
k32.CloseHandle.argtypes = [wintypes.HANDLE]


def main():
    argv = sys.argv[1:]
    opts, rest = (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, [])
    threads = int(os.environ.get("BLENDER_QUEUE_THREADS", 6))
    wait_minutes = 180
    for i, o in enumerate(opts):
        if o == "--threads":
            threads = int(opts[i + 1])
        elif o == "--wait-minutes":
            wait_minutes = int(opts[i + 1])
    lane = k32.CreateMutexW(None, False, LANE)
    if not lane:
        sys.exit(f"cannot open the lane mutex ({ctypes.get_last_error()})")

    if "--status" in opts:
        r = k32.WaitForSingleObject(lane, 0)
        if r in (WAIT_OBJECT_0, WAIT_ABANDONED):
            k32.ReleaseMutex(lane)
            print("heavy lane: free")
        else:
            who = INFO.read_text(encoding="utf-8") if INFO.exists() else ""
            print("heavy lane: busy" + (f" - last taken by blender_queue: {who}" if who else " (a game job or another tool)"))
        return
    if not rest:
        sys.exit(__doc__)

    t0 = told = time.time()
    while True:
        r = k32.WaitForSingleObject(lane, 3000)
        if r in (WAIT_OBJECT_0, WAIT_ABANDONED):
            break
        if r != WAIT_TIMEOUT:
            sys.exit(f"waiting for the lane failed ({ctypes.get_last_error()})")
        if time.time() - t0 > wait_minutes * 60:
            print(f"[blender_queue] heavy lane still busy after {wait_minutes} min", flush=True)
            sys.exit(124)
        if time.time() - told >= 30 or told == t0:
            print(f"[blender_queue] heavy lane busy, waiting ({int(time.time() - t0)} s)", flush=True)
            told = time.time()
    try:
        INFO.parent.mkdir(parents=True, exist_ok=True)
        INFO.write_text(f"pid {os.getpid()} since {time.strftime('%H:%M:%S')} cwd {os.getcwd()} :: {' '.join(rest)[:300]}",
                        encoding="utf-8")
        waited = int(time.time() - t0)
        if waited:
            print(f"[blender_queue] lane taken after {waited} s", flush=True)
        p = subprocess.Popen([BLENDER, "-t", str(threads)] + rest, creationflags=BELOW_NORMAL)
        try:
            code = p.wait()
        except KeyboardInterrupt:
            p.terminate()
            code = p.wait()
    finally:
        k32.ReleaseMutex(lane)
        k32.CloseHandle(lane)
    sys.exit(code)


if __name__ == "__main__":
    main()
