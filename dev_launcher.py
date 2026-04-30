import os
import subprocess
import sys
import time
from pathlib import Path


ROOT = Path(__file__).resolve().parent
APP_FILE = ROOT / "app.py"
RELOAD_FLAG = ROOT / ".dev_reload.flag"
WATCH_EXTENSIONS = {".py", ".html", ".css", ".js"}
IGNORE_DIRS = {"__pycache__", ".git", ".venv", "venv", "node_modules"}
SCAN_INTERVAL_SECONDS = 0.8
RESTART_TIMEOUT_SECONDS = 8.0


def iter_watch_files():
    for path in ROOT.rglob("*"):
        if not path.is_file():
            continue
        if any(part in IGNORE_DIRS for part in path.parts):
            continue
        if path.name.startswith(".dev_reload"):
            continue
        if path.suffix.lower() in WATCH_EXTENSIONS:
            yield path


def snapshot_files():
    snap = {}
    for path in iter_watch_files():
        try:
            stat = path.stat()
            snap[str(path)] = (stat.st_mtime, stat.st_size)
        except OSError:
            continue
    return snap


def detect_changes(previous, current):
    changed = []
    all_paths = set(previous) | set(current)
    for path in sorted(all_paths):
        if previous.get(path) != current.get(path):
            changed.append(path)
    return changed


def touch_reload_flag():
    RELOAD_FLAG.write_text(str(time.time()), encoding="utf-8")


def launch_app():
    env = os.environ.copy()
    env["AJUSTE_COMP_DEV_RELOAD_FILE"] = str(RELOAD_FLAG)
    command = [sys.executable, str(APP_FILE)]
    creationflags = getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    return subprocess.Popen(command, cwd=str(ROOT), env=env, creationflags=creationflags)


def stop_app(proc):
    if proc is None:
        return
    try:
        if proc.poll() is None:
            proc.terminate()
            deadline = time.time() + RESTART_TIMEOUT_SECONDS
            while time.time() < deadline:
                if proc.poll() is not None:
                    return
                time.sleep(0.2)
            proc.kill()
    except Exception:
        pass


def main():
    if not APP_FILE.exists():
        raise FileNotFoundError(f"No encontre {APP_FILE}")

    touch_reload_flag()
    last_snapshot = snapshot_files()
    app_proc = launch_app()
    restart_requested = False
    restart_started_at = 0.0

    print("[DEV] Launcher iniciado. Vigilando cambios de codigo...")
    print(f"[DEV] App: {APP_FILE.name}")

    try:
        while True:
            time.sleep(SCAN_INTERVAL_SECONDS)

            current_snapshot = snapshot_files()
            changed = detect_changes(last_snapshot, current_snapshot)
            if changed:
                last_snapshot = current_snapshot
                print("[DEV] Cambios detectados:")
                for path in changed[:12]:
                    print(f"       - {Path(path).relative_to(ROOT)}")
                if len(changed) > 12:
                    print(f"       - +{len(changed) - 12} archivos mas")
                touch_reload_flag()
                restart_requested = True
                restart_started_at = time.time()

            if app_proc.poll() is not None:
                if restart_requested:
                    print("[DEV] Relanzando app...")
                    app_proc = launch_app()
                    restart_requested = False
                    restart_started_at = 0.0
                    last_snapshot = snapshot_files()
                    continue
                print("[DEV] La app se cerro. Saliendo del launcher.")
                break

            if restart_requested and (time.time() - restart_started_at) > RESTART_TIMEOUT_SECONDS:
                print("[DEV] La app no se cerro a tiempo. Forzando cierre...")
                stop_app(app_proc)
    except KeyboardInterrupt:
        print("\n[DEV] Launcher detenido por usuario.")
    finally:
        stop_app(app_proc)


if __name__ == "__main__":
    main()
