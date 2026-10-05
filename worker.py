"""Run beside Streamlit: uv run python worker.py (Ctrl+C to stop)."""
import argparse
import os
import time

from scheduler import tick
from state import Store, wall_now


def run(once=False):
    store = Store()
    lock = open(store.path.with_suffix(".worker.lock"), "a+b")
    lock.seek(0)
    lock.write(b"0")
    lock.flush()
    lock.seek(0)
    try:
        if os.name == "nt":
            import msvcrt
            msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        raise SystemExit("A worker is already running for this database.")
    while True:
        try:
            tick(store)
        except Exception as exc:
            # Log the type only; never a credential or external response body.
            store.set_setting("worker_status", {"last_tick": wall_now().isoformat(), "ok": False, "error_type": type(exc).__name__})
        if once:
            break
        time.sleep(30)
    lock.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--once", action="store_true")
    run(parser.parse_args().once)
