"""
Actualizador automático de AjustesRomero.
Se ejecuta al iniciar el OS. Comprueba si hay cambios en GitHub y actualiza.
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
from datetime import datetime

# ── Configuración ─────────────────────────────────────────────────────────────

APP_NAME    = "AjustesRomero"
APP_DIR     = Path(__file__).resolve().parent
GITHUB_REPO = "ledesmamatiasarispe/AjustesRomero"
GITHUB_BRANCH = "test"

# Cuando haya releases en GitHub, cambiar a True
USE_RELEASES = False

LOG_FILE = Path.home() / f".{APP_NAME}_updater.log"


# ── Logging ───────────────────────────────────────────────────────────────────

logging.basicConfig(
    filename=LOG_FILE,
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
log = logging.getLogger(__name__)


# ── Notificaciones de escritorio ──────────────────────────────────────────────

def notify(title: str, message: str, urgency: str = "normal"):
    """Envía una notificación de escritorio según el SO."""
    system = platform.system()
    try:
        if system == "Linux":
            if shutil.which("notify-send"):
                subprocess.run(
                    ["notify-send", "-u", urgency, "-a", APP_NAME, title, message],
                    timeout=5
                )
        elif system == "Windows":
            # Notificación via PowerShell (sin dependencias externas)
            ps_script = f"""
Add-Type -AssemblyName System.Windows.Forms
$n = New-Object System.Windows.Forms.NotifyIcon
$n.Icon = [System.Drawing.SystemIcons]::Information
$n.BalloonTipTitle = '{title}'
$n.BalloonTipText = '{message}'
$n.Visible = $True
$n.ShowBalloonTip(5000)
Start-Sleep -s 6
$n.Dispose()
"""
            subprocess.run(
                ["powershell", "-WindowStyle", "Hidden", "-Command", ps_script],
                timeout=10, capture_output=True
            )
    except Exception as e:
        log.warning(f"No se pudo enviar notificación: {e}")


# ── Actualización por git pull ────────────────────────────────────────────────

def get_local_hash() -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(APP_DIR), "rev-parse", "HEAD"],
            capture_output=True, text=True, timeout=10
        )
        return r.stdout.strip() if r.returncode == 0 else None
    except Exception:
        return None


def get_remote_hash() -> str | None:
    try:
        r = subprocess.run(
            ["git", "-C", str(APP_DIR), "ls-remote", "origin", f"refs/heads/{GITHUB_BRANCH}"],
            capture_output=True, text=True, timeout=15
        )
        if r.returncode == 0 and r.stdout.strip():
            return r.stdout.split()[0]
        return None
    except Exception:
        return None


def update_via_git() -> bool:
    """Hace git pull. Devuelve True si hubo cambios."""
    local  = get_local_hash()
    remote = get_remote_hash()

    if local is None or remote is None:
        log.warning("No se pudo comparar versiones (sin acceso a git o a internet).")
        return False

    if local == remote:
        log.info("La app ya está en la última versión.")
        return False

    log.info(f"Actualización disponible: {local[:8]} → {remote[:8]}")
    r = subprocess.run(
        ["git", "-C", str(APP_DIR), "pull", "--ff-only", "origin", GITHUB_BRANCH],
        capture_output=True, text=True, timeout=60
    )
    if r.returncode == 0:
        log.info("Actualización aplicada correctamente.")
        return True
    else:
        log.error(f"Error al aplicar actualización: {r.stderr.strip()}")
        return False


# ── Actualización por GitHub Releases ────────────────────────────────────────

def get_latest_release() -> dict | None:
    try:
        url = f"https://api.github.com/repos/{GITHUB_REPO}/releases/latest"
        req = urllib.request.Request(url, headers={"User-Agent": APP_NAME})
        with urllib.request.urlopen(req, timeout=10) as resp:
            return json.loads(resp.read())
    except Exception as e:
        log.warning(f"No se pudo consultar releases: {e}")
        return None


def get_installed_version() -> str | None:
    version_file = APP_DIR / "version.txt"
    if version_file.exists():
        return version_file.read_text().strip()
    return None


def update_via_release() -> bool:
    """Descarga e instala la última release si es más nueva."""
    release = get_latest_release()
    if not release:
        return False

    latest_tag = release.get("tag_name", "")
    installed  = get_installed_version()

    if installed and installed == latest_tag:
        log.info(f"Ya está instalada la versión {installed}.")
        return False

    log.info(f"Nueva versión disponible: {latest_tag} (instalada: {installed or 'desconocida'})")

    # Buscar asset descargable (.zip o .tar.gz)
    assets = release.get("assets", [])
    asset  = next((a for a in assets if a["name"].endswith((".zip", ".tar.gz", ".tgz"))), None)
    if not asset:
        log.warning("No se encontró archivo descargable en la release.")
        return False

    # Delegar al installer
    installer = APP_DIR / "install.py"
    if installer.exists():
        r = subprocess.run([sys.executable, str(installer)], timeout=120)
        return r.returncode == 0

    return False


# ── Verificar que la app no esté corriendo ────────────────────────────────────

def app_is_running() -> bool:
    try:
        result = subprocess.run(
            ["pgrep", "-f", "app.py"] if platform.system() != "Windows"
            else ["tasklist", "/fi", "imagename eq python.exe"],
            capture_output=True, text=True
        )
        if platform.system() == "Windows":
            return "python.exe" in result.stdout
        return bool(result.stdout.strip())
    except Exception:
        return False


# ── Main ──────────────────────────────────────────────────────────────────────

def relaunch_app():
    """Reabre app.py después de actualizar."""
    app_script = APP_DIR / "app.py"
    if not app_script.exists():
        log.error(f"No se encontró app.py en {APP_DIR}")
        return
    log.info(f"Relanzando app: {app_script}")
    try:
        if platform.system() == "Windows":
            subprocess.Popen([sys.executable, str(app_script)],
                             creationflags=subprocess.DETACHED_PROCESS)
        else:
            subprocess.Popen([sys.executable, str(app_script)],
                             start_new_session=True)
    except Exception as e:
        log.error(f"No se pudo relanzar la app: {e}")


def main():
    relaunch_mode = "--relaunch-app" in sys.argv

    log.info(f"=== Actualizador {APP_NAME} {'(modo relaunch)' if relaunch_mode else '(modo autostart)'} ===")

    if not shutil.which("git") and not USE_RELEASES:
        log.warning("git no encontrado. No se puede verificar actualizaciones.")
        if relaunch_mode:
            relaunch_app()
        return

    try:
        if USE_RELEASES:
            updated = update_via_release()
        else:
            updated = update_via_git()

        if relaunch_mode:
            # Siempre relanzar la app en este modo (fue invocado por la propia app)
            if updated:
                log.info("Actualización aplicada. Relanzando app.")
                notify(f"{APP_NAME} actualizado", "La app fue actualizada. Reabriendo...", urgency="normal")
            else:
                log.info("Sin cambios. Relanzando app.")
            relaunch_app()
        else:
            # Modo autostart normal: notificar si hay cambios, no relanzar
            if updated:
                if app_is_running():
                    notify(
                        f"{APP_NAME} actualizado",
                        "Hay una actualización disponible. Reiniciá la app para aplicarla.",
                        urgency="normal"
                    )
                else:
                    notify(
                        f"{APP_NAME} actualizado",
                        "La app fue actualizada automáticamente.",
                        urgency="normal"
                    )
                log.info("Notificación enviada al usuario.")

    except Exception as e:
        log.error(f"Error inesperado en el updater: {e}")
        if relaunch_mode:
            relaunch_app()


if __name__ == "__main__":
    main()
