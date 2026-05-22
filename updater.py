"""
Actualizador automático de AjustesRomero.
Se ejecuta al iniciar el OS o cuando la app detecta una nueva versión.
"""

import os
import sys
import platform
import subprocess
import shutil
import logging
import urllib.request
import json
from pathlib import Path

APP_NAME      = "AjustesRomero"
APP_DISPLAY   = "Ajustes Romero"
APP_DIR       = Path(__file__).resolve().parent
GITHUB_REPO   = "ledesmamatiasarispe/AjustesRomero"
GITHUB_BRANCH = "test"
USE_RELEASES  = False
LOG_FILE      = Path.home() / f".{APP_NAME}_updater.log"

logging.basicConfig(
    filename=LOG_FILE, level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


class UpdaterWindow:
    BG = "#1e1e1e"; FG = "#e6e6e6"; ACCENT = "#3a7bd5"
    SUCCESS = "#2e7d32"; ERROR = "#c62828"

    def __init__(self):
        import tkinter as tk
        from tkinter import ttk
        self._tk = tk
        self.root = tk.Tk()
        self.root.title(f"{APP_DISPLAY} — Actualizador")
        self.root.configure(bg=self.BG)
        self.root.resizable(False, False)
        self.root.protocol("WM_DELETE_WINDOW", lambda: None)
        w, h = 460, 200
        self.root.geometry(f"{w}x{h}")
        self.root.update_idletasks()
        x = (self.root.winfo_screenwidth()  - w) // 2
        y = (self.root.winfo_screenheight() - h) // 2
        self.root.geometry(f"{w}x{h}+{x}+{y}")
        tk.Label(self.root, text=f"🔄  {APP_DISPLAY}  —  Actualizador",
                 bg=self.BG, fg=self.FG, font=("Segoe UI", 13, "bold"), pady=12).pack(fill="x")
        self._status_var = tk.StringVar(value="Iniciando...")
        self._status_lbl = tk.Label(self.root, textvariable=self._status_var,
                                    bg=self.BG, fg=self.FG, font=("Segoe UI", 11), wraplength=420)
        self._status_lbl.pack(fill="x", padx=20)
        style = ttk.Style(self.root)
        style.theme_use("clam")
        style.configure("Up.Horizontal.TProgressbar",
                        troughcolor=self.BG, background=self.ACCENT,
                        bordercolor=self.BG, lightcolor=self.ACCENT, darkcolor=self.ACCENT)
        self._pb = ttk.Progressbar(self.root, style="Up.Horizontal.TProgressbar",
                                   mode="indeterminate", length=420)
        self._pb.pack(padx=20, pady=14)
        self._pb.start(12)
        self._detail_var = tk.StringVar(value="")
        tk.Label(self.root, textvariable=self._detail_var,
                 bg=self.BG, fg="#888888", font=("Segoe UI", 9)).pack()
        self.root.lift()
        self.root.attributes("-topmost", True)

    def set_status(self, msg, detail="", color=None):
        self._status_var.set(msg)
        self._detail_var.set(detail)
        if color:
            self._status_lbl.configure(fg=color)
        self.root.update()

    def set_done(self, msg, detail="", success=True):
        self._pb.stop()
        self._pb.configure(mode="determinate", value=100)
        self.set_status(msg, detail, color=self.SUCCESS if success else self.ERROR)

    def close_after(self, ms=2500):
        self.root.after(ms, self.root.destroy)
        self.root.mainloop()

    def destroy(self):
        try: self.root.destroy()
        except Exception: pass


def notify(title, message, urgency="normal"):
    try:
        if platform.system() == "Linux" and shutil.which("notify-send"):
            subprocess.run(["notify-send", "-u", urgency, "-a", APP_NAME, title, message], timeout=5)
        elif platform.system() == "Windows":
            ps = f"""Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.BalloonTipTitle = '{title}'
$n.BalloonTipText = '{message}'
$n.Visible = $True
$n.ShowBalloonTip(5000)
Start-Sleep -s 6
$n.Dispose()"""
            subprocess.run(["powershell", "-WindowStyle", "Hidden", "-Command", ps],
                           timeout=10, capture_output=True)
    except Exception as e:
        log.warning(f"No se pudo enviar notificación: {e}")


def get_local_hash():
    try:
        r = subprocess.run(["git", "-C", str(APP_DIR), "rev-parse", "HEAD"],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception: return None


def get_remote_hash():
    try:
        r = subprocess.run(
            ["git", "-C", str(APP_DIR), "ls-remote", "origin", f"refs/heads/{GITHUB_BRANCH}"],
            capture_output=True, text=True, timeout=15)
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.split()[0]
        return None
    except Exception: return None


def do_git_pull():
    r = subprocess.run(
        ["git", "-C", str(APP_DIR), "pull", "--ff-only", "origin", GITHUB_BRANCH],
        capture_output=True, text=True, timeout=60)
    return (True, r.stdout.strip()) if r.returncode == 0 else (False, r.stderr.strip())


def get_latest_release():
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning(f"No se pudo consultar releases: {e}"); return None


def get_installed_version():
    v = APP_DIR / "version.txt"
    return v.read_text().strip() if v.exists() else None


def relaunch_app():
    app_script = APP_DIR / "app.py"
    if not app_script.exists():
        log.error(f"No se encontró app.py en {APP_DIR}"); return
    log.info(f"Relanzando app: {app_script}")
    try:
        env = os.environ.copy()
        if platform.system() == "Windows":
            subprocess.Popen([sys.executable, str(app_script)],
                             creationflags=subprocess.DETACHED_PROCESS, env=env)
        else:
            subprocess.Popen([sys.executable, str(app_script)],
                             start_new_session=True, env=env, cwd=str(APP_DIR))
        log.info("App relanzada.")
    except Exception as e:
        log.error(f"No se pudo relanzar la app: {e}")


def app_is_running():
    try:
        r = subprocess.run(
            ["pgrep", "-f", "app.py"] if platform.system() != "Windows"
            else ["tasklist", "/fi", "imagename eq python.exe"],
            capture_output=True, text=True)
        return bool(r.stdout.strip()) if platform.system() != "Windows" \
               else "python.exe" in r.stdout
    except Exception: return False


def _has_tkinter():
    try: import tkinter; return True
    except ImportError: return False


def main():
    relaunch_mode = "--relaunch-app" in sys.argv
    use_gui       = _has_tkinter()
    log.info(f"=== Actualizador {APP_NAME} {'(relaunch)' if relaunch_mode else '(autostart)'} ===")

    win = UpdaterWindow() if use_gui else None

    def status(msg, detail="", color=None):
        log.info(f"{msg} {detail}".strip())
        if win: win.set_status(msg, detail, color)

    def finish(msg, detail="", success=True, close_ms=2500, do_relaunch=False):
        log.info(f"{'OK' if success else 'ERR'}: {msg} {detail}".strip())
        if win:
            win.set_done(msg, detail, success)
            if do_relaunch:
                win.root.after(close_ms, relaunch_app)
                win.root.after(close_ms, win.root.destroy)
                win.root.mainloop()
            else:
                win.close_after(close_ms)
        elif do_relaunch:
            relaunch_app()

    if not shutil.which("git") and not USE_RELEASES:
        finish("git no encontrado. No se puede actualizar.",
               success=False, do_relaunch=relaunch_mode)
        return

    try:
        if USE_RELEASES:
            status("Consultando última versión en GitHub...")
            release = get_latest_release()
            if not release:
                finish("No se pudo consultar GitHub.", success=False, do_relaunch=relaunch_mode)
                return
            latest_tag = release.get("tag_name", "")
            installed  = get_installed_version()
            if installed == latest_tag:
                finish(f"Ya tenés la versión más reciente  ({installed})",
                       do_relaunch=relaunch_mode, close_ms=1800)
                return
            status(f"Nueva versión: {latest_tag}", f"Instalada: {installed or 'desconocida'}")
            installer = APP_DIR / "install.py"
            ok = installer.exists() and subprocess.run(
                [sys.executable, str(installer)], timeout=120).returncode == 0
            finish(f"Versión {latest_tag} instalada." if ok else "Error al instalar.",
                   success=ok, close_ms=3000, do_relaunch=relaunch_mode)
        else:
            status("Verificando versión local...")
            local = get_local_hash()
            status("Consultando GitHub...")
            remote = get_remote_hash()
            if local is None or remote is None:
                finish("Sin conexión o git no disponible.", success=False, do_relaunch=relaunch_mode)
                return
            if local == remote:
                finish("Ya tenés la versión más reciente.", close_ms=1800, do_relaunch=relaunch_mode)
                return
            status("Actualizando...", f"{local[:8]}  →  {remote[:8]}")
            ok, msg = do_git_pull()
            if ok:
                log.info(f"git pull: {msg}")
                if relaunch_mode:
                    finish("Actualización completada. Reabriendo la app...",
                           close_ms=2000, do_relaunch=True)
                else:
                    notify(f"{APP_NAME} actualizado", "La app fue actualizada automáticamente.")
                    finish("Actualización completada.", close_ms=2500)
            else:
                finish(f"Error al actualizar: {msg}", success=False, do_relaunch=relaunch_mode)

    except Exception as e:
        log.error(f"Error inesperado: {e}")
        finish(f"Error inesperado: {e}", success=False, close_ms=4000, do_relaunch=relaunch_mode)


if __name__ == "__main__":
    main()
