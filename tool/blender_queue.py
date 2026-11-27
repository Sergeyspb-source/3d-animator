"""Run Blender in the shared queue, so parallel Claude sessions do not take the whole CPU at once.

When several sessions render or bake with Blender on all 12 threads, the VPN/proxy gets no CPU time and every session
drops with "API Error: ECONNREFUSED / ENOTFOUND". Through this queue at most SLOTS Blenders run at a time (the rest
wait their turn), each with THREADS threads and below-normal priority.

    D:\\conda\\envs\\sf3d\\python.exe tool\\blender_queue.py [--slots 2] [--threads 4] -- -b -P script.py -- args
    D:\\conda\\envs\\sf3d\\python.exe tool\\blender_queue.py --status

Everything after the first "--" goes to blender.exe unchanged. A slot is a locked byte in
D:\\conda\\tmp\\blender_queue\\slotN.lock; Windows frees it when the process ends, even after a crash, so nothing sticks.
Env: BLENDER_QUEUE_SLOTS, BLENDER_QUEUE_THREADS, BLENDER_EXE.
"""
import msvcrt
import os
import subprocess
import sys
import time
from pathlib import Path

BLENDER = os.environ.get("BLENDER_EXE", r"D:\Blender 5.2\blender.exe")
LOCKS = Path(r"D:\conda\tmp\blender_queue")
BELOW_NORMAL = 0x00004000


def try_slot(k):
    fd = os.open(str(LOCKS / f"slot{k}.lock"), os.O_RDWR | os.O_CREAT)
    os.lseek(fd, 0, 0)
    try:
        msvcrt.locking(fd, msvcrt.LK_NBLCK, 1)
        return fd
    except OSError:
        os.close(fd)
        return None


def status(slots):
    for k in range(slots):
        fd = try_slot(k)
        info = LOCKS / f"slot{k}.txt"
        if fd is not None:
            os.close(fd)
            print(f"slot {k}: free")
        else:
            print(f"slot {k}: busy - {info.read_text(encoding='utf-8') if info.exists() else '?'}")


def main():
    argv = sys.argv[1:]
    opts, rest = (argv[:argv.index("--")], argv[argv.index("--") + 1:]) if "--" in argv else (argv, [])
    slots = int(os.environ.get("BLENDER_QUEUE_SLOTS", 2))
    threads = int(os.environ.get("BLENDER_QUEUE_THREADS", 4))
    for i, o in enumerate(opts):
        if o == "--slots":
            slots = int(opts[i + 1])
        elif o == "--threads":
            threads = int(opts[i + 1])
    LOCKS.mkdir(parents=True, exist_ok=True)
    if "--status" in opts:
        return status(slots)
    if not rest:
        sys.exit(__doc__)

    t0 = told = time.time()
    fd = slot = None
    while fd is None:
        for k in range(slots):
            fd = try_slot(k)
            if fd is not None:
                slot = k
                break
        if fd is None:
            if time.time() - told >= 30 or told == t0:
                print(f"[blender_queue] all {slots} slots busy, waiting ({int(time.time() - t0)} s)", flush=True)
                told = time.time()
            time.sleep(3)
    waited = int(time.time() - t0)
    (LOCKS / f"slot{slot}.txt").write_text(
        f"pid {os.getpid()} since {time.strftime('%H:%M:%S')} cwd {os.getcwd()} :: {' '.join(rest)[:300]}", encoding="utf-8")
    if waited:
        print(f"[blender_queue] slot {slot} after {waited} s", flush=True)
    p = subprocess.Popen([BLENDER, "-t", str(threads)] + rest, creationflags=BELOW_NORMAL)
    try:
        code = p.wait()
    except KeyboardInterrupt:
        p.terminate()
        code = p.wait()
    os.close(fd)
    sys.exit(code)


if __name__ == "__main__":
    main()
