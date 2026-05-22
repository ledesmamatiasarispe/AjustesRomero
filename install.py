"""
Installer de AjustesRomero
Uso: python3 install.py   (Linux)
     python  install.py   (Windows)
"""

import os
import sys
import platform
import subprocess
import shutil
import zipfile
import tarfile
import tempfile
import importlib
from pathlib import Path

# ── Configuración ────────────────────────────────────────────────────────────

APP_NAME      = "AjustesRomero"
APP_DISPLAY   = "Ajustes Romero"
APP_DESC      = "Calculadora de Composición Química"
GITHUB_REPO   = "ledesmamatiasarispe/AjustesRomero"
GITHUB_BRANCH = "test"

# Cuando haya una release en GitHub, reemplazar None por la URL del asset
# Ejemplo: "https://github.com/.../releases/download/v1.0/AjustesRomero.zip"
RELEASE_URL   = None

INSTALL_DIR   = Path.home() / APP_NAME

PIP_PACKAGES = [
    ("matplotlib", "matplotlib"),
    ("numpy",      "numpy"),
    ("pandas",     "pandas"),
    ("PIL",        "Pillow"),
]


# ── Colores de terminal ───────────────────────────────────────────────────────

def _supports_color():
    return sys.stdout.isatty() and platform.system() != "Windows"

if _supports_color():
    OK   = "\033[32m✔\033[0m"
    FAIL = "\033[31m✘\033[0m"
    WARN = "\033[33m⚠\033[0m"
    INFO = "\033[36mℹ\033[0m"
    BOLD = lambda s: f"\033[1m{s}\033[0m"
else:
    OK   = "[OK]"
    FAIL = "[FALLO]"
    WARN = "[AVISO]"
    INFO = "[INFO]"
    BOLD = lambda s: s

def step(msg):  print(f"\n{BOLD(msg)}")
def ok(msg):    print(f"  {OK}  {msg}")
def fail(msg):  print(f"  {FAIL}  {msg}")
def warn(msg):  print(f"  {WARN}  {msg}")
def info(msg):  print(f"  {INFO}  {msg}")
def run(cmd, **kw): return subprocess.run(cmd, **kw)


# ── Perfil de OS (clase base extensible) ─────────────────────────────────────

class OSProfile:
    """Clase base. Crear una subclase para soportar un nuevo SO."""

    name = "Genérico"

    def check_tkinter(self) -> bool:
        try:
            import tkinter
            return True
        except ImportError:
            return False

    def install_tkinter(self):
        """Devuelve True=instalado, False=error, None=requiere reinicio."""
        warn("No sé cómo instalar tkinter en este sistema. Instalalo manualmente.")
        return False

    def pip_cmd(self) -> list:
        return [sys.executable, "-m", "pip", "install", "--break-system-packages"]

    def install_pip_package(self, pip_name: str) -> bool:
        return run(self.pip_cmd() + [pip_name], capture_output=True).returncode == 0

    def create_shortcut(self, app_dir: Path, icon_path: Path | None) -> bool:
        warn("Creación de acceso directo no implementada en este sistema.")
        return False

    def setup_autostart(self, updater_script: Path) -> bool:
        """Registra updater.py para ejecutarse al iniciar el OS."""
        warn("Autostart no implementado en este sistema.")
        return False

    def needs_reboot_for_tkinter(self) -> bool:
        return False


# ── Linux: helper para .desktop ──────────────────────────────────────────────

def _linux_shortcut(app_dir: Path, icon_path: Path | None) -> bool:
    desktop_dir = Path.home() / "Escritorio"
    if not desktop_dir.exists():
        desktop_dir = Path.home() / "Desktop"
    desktop_dir.mkdir(parents=True, exist_ok=True)
    icon_line = f"Icon={icon_path}" if icon_path and icon_path.exists() else "Icon=application-x-executable"
    shortcut = desktop_dir / f"{APP_NAME}.desktop"
    shortcut.write_text(f"""[Desktop Entry]
Version=1.0
Type=Application
Name={APP_DISPLAY}
Comment={APP_DESC}
Exec=python3 {app_dir}/app.py
{icon_line}
Path={app_dir}
Terminal=false
StartupNotify=true
""")
    shortcut.chmod(0o755)
    return True


def _linux_autostart(updater_script: Path) -> bool:
    autostart_dir = Path.home() / ".config" / "autostart"
    autostart_dir.mkdir(parents=True, exist_ok=True)
    entry = autostart_dir / f"{APP_NAME}-updater.desktop"
    entry.write_text(f"""[Desktop Entry]
Type=Application
Name={APP_NAME} Updater
Exec={sys.executable} {updater_script}
Hidden=false
NoDisplay=true
X-GNOME-Autostart-enabled=true
""")
    entry.chmod(0o755)
    return True


# ── Perfiles de SO ───────────────────────────────────────────────────────────

class FedoraAtomicProfile(OSProfile):
    """Bazzite, Fedora Silverblue y derivados (usan rpm-ostree)."""

    name = "Fedora Atomic (Bazzite/Silverblue)"

    def install_tkinter(self):
        info("Instalando python3-tkinter con rpm-ostree (requiere reinicio)...")
        r = run(["rpm-ostree", "install", "python3-tkinter"], capture_output=True, text=True)
        if r.returncode == 0:
            ok("python3-tkinter instalado. Reiniciá el sistema y volvé a ejecutar el installer.")
            return None
        fail(f"Error: {r.stderr.strip()}")
        return False

    def needs_reboot_for_tkinter(self): return True
    def create_shortcut(self, app_dir, icon_path): return _linux_shortcut(app_dir, icon_path)
    def setup_autostart(self, updater_script): return _linux_autostart(updater_script)


class FedoraProfile(OSProfile):
    """Fedora Workstation clásico (usa dnf)."""

    name = "Fedora"

    def install_tkinter(self):
        r = run(["sudo", "dnf", "install", "-y", "python3-tkinter"], capture_output=True, text=True)
        return r.returncode == 0

    def create_shortcut(self, app_dir, icon_path): return _linux_shortcut(app_dir, icon_path)
    def setup_autostart(self, updater_script): return _linux_autostart(updater_script)


class DebianUbuntuProfile(OSProfile):
    """Ubuntu, Debian, Linux Mint y derivados (usan apt)."""

    name = "Debian/Ubuntu"

    def install_tkinter(self):
        ver = f"{sys.version_info.major}.{sys.version_info.minor}"
        for pkg in [f"python{ver}-tk", "python3-tk"]:
            r = run(["sudo", "apt", "install", "-y", pkg], capture_output=True, text=True)
            if r.returncode == 0:
                return True
        return False

    def create_shortcut(self, app_dir, icon_path): return _linux_shortcut(app_dir, icon_path)
    def setup_autostart(self, updater_script): return _linux_autostart(updater_script)


class WindowsProfile(OSProfile):
    """Windows 10/11."""

    name = "Windows"

    def install_tkinter(self):
        warn("En Windows, tkinter viene incluido con Python.")
        warn("Descargá Python desde https://python.org y marcá 'tcl/tk and IDLE'.")
        return False

    def pip_cmd(self) -> list:
        return [sys.executable, "-m", "pip", "install"]

    def create_shortcut(self, app_dir: Path, icon_path: Path | None) -> bool:
        desktop = Path(os.environ.get("USERPROFILE", Path.home())) / "Desktop"
        desktop.mkdir(parents=True, exist_ok=True)
        bat = desktop / f"{APP_NAME}.bat"
        bat.write_text(f'@echo off\ncd /d "{app_dir}"\npython app.py\n', encoding="utf-8")
        ok(f"Acceso directo creado: {bat}")
        return True

    def setup_autostart(self, updater_script: Path) -> bool:
        task_name = f"{APP_NAME}Updater"
        cmd = (
            f'schtasks /create /f /tn "{task_name}" '
            f'/tr "\\"{sys.executable}\\" \\"{updater_script}\\"" '
            f'/sc onlogon /rl highest'
        )
        r = run(cmd, shell=True, capture_output=True, text=True)
        if r.returncode == 0:
            ok(f"Tarea programada '{task_name}' creada (ejecuta al iniciar sesión).")
            return True
        fail(f"No se pudo crear la tarea: {r.stderr.strip()}")
        return False


# ── Detección de OS ───────────────────────────────────────────────────────────

def detect_os() -> OSProfile:
    system = platform.system()

    if system == "Windows":
        return WindowsProfile()

    if system == "Linux":
        os_release = {}
        try:
            for line in Path("/etc/os-release").read_text().splitlines():
                if "=" in line:
                    k, v = line.split("=", 1)
                    os_release[k] = v.strip('"')
        except FileNotFoundError:
            pass

        distro_id   = os_release.get("ID", "").lower()
        distro_like = os_release.get("ID_LIKE", "").lower()

        if shutil.which("rpm-ostree"):
            return FedoraAtomicProfile()
        if distro_id == "fedora" or "fedora" in distro_like:
            return FedoraProfile()
        if distro_id in ("ubuntu", "debian", "linuxmint", "pop", "elementary", "zorin") \
                or "debian" in distro_like or "ubuntu" in distro_like:
            return DebianUbuntuProfile()

    return OSProfile()


# ── Descarga de la app ────────────────────────────────────────────────────────

def download_app(target_dir: Path) -> bool:
    return _download_release(target_dir) if RELEASE_URL else _clone_repo(target_dir)


def _download_release(target_dir: Path) -> bool:
    import urllib.request
    step("Descargando release...")
    info(f"URL: {RELEASE_URL}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        filename = RELEASE_URL.split("/")[-1]
        dest = tmp_path / filename
        try:
            urllib.request.urlretrieve(RELEASE_URL, dest)
        except Exception as e:
            fail(f"No se pudo descargar: {e}")
            return False
        if filename.endswith(".zip"):
            with zipfile.ZipFile(dest) as z:
                z.extractall(tmp_path)
        elif filename.endswith((".tar.gz", ".tgz")):
            with tarfile.open(dest) as t:
                t.extractall(tmp_path)
        else:
            fail(f"Formato no reconocido: {filename}")
            return False
        extracted = [p for p in tmp_path.iterdir() if p.is_dir()]
        if not extracted:
            fail("No se encontró carpeta en el archivo descargado.")
            return False
        if target_dir.exists():
            shutil.rmtree(target_dir)
        shutil.copytree(extracted[0], target_dir)
    ok(f"App instalada en: {target_dir}")
    return True


def _clone_repo(target_dir: Path) -> bool:
    step("Descargando app desde GitHub...")
    if not shutil.which("git"):
        fail("git no está instalado. Instalalo y volvé a intentar.")
        return False
    if target_dir.exists():
        info(f"La carpeta {target_dir} ya existe, actualizando...")
        r = run(["git", "-C", str(target_dir), "pull"], capture_output=True, text=True)
    else:
        r = run(
            ["git", "clone", "--branch", GITHUB_BRANCH,
             f"https://github.com/{GITHUB_REPO}.git", str(target_dir)],
            capture_output=True, text=True
        )
    if r.returncode == 0:
        ok(f"App descargada en: {target_dir}")
        return True
    fail(f"Error de git: {r.stderr.strip()}")
    return False


# ── Lógica principal ──────────────────────────────────────────────────────────

def main():
    print(f"\n{'='*55}")
    print(f"  Installer de {APP_DISPLAY}")
    print(f"{'='*55}")

    profile = detect_os()
    info(f"Sistema detectado: {profile.name}")

    needs_reboot = False
    errors = []

    # 1. Python
    step("Verificando Python...")
    major, minor = sys.version_info.major, sys.version_info.minor
    if major < 3 or (major == 3 and minor < 10):
        fail(f"Python {major}.{minor} — se requiere 3.10 o superior.")
        errors.append("python")
    else:
        ok(f"Python {major}.{minor} — OK")

    # 2. tkinter
    step("Verificando tkinter (interfaz gráfica)...")
    if profile.check_tkinter():
        ok("tkinter disponible")
    else:
        warn("tkinter no encontrado, intentando instalar...")
        result = profile.install_tkinter()
        if result is None:
            warn("Reiniciá el sistema y volvé a ejecutar el installer.")
            needs_reboot = True
        elif result:
            ok("tkinter instalado")
        else:
            fail("No se pudo instalar tkinter.")
            errors.append("tkinter")

    if not needs_reboot:
        # 3. Paquetes pip
        step("Verificando paquetes Python...")
        for import_name, pip_name in PIP_PACKAGES:
            try:
                importlib.import_module(import_name)
                ok(pip_name)
            except ImportError:
                warn(f"{pip_name} no encontrado, instalando...")
                if profile.install_pip_package(pip_name):
                    ok(f"{pip_name} instalado")
                else:
                    fail(f"No se pudo instalar {pip_name}")
                    errors.append(pip_name)

        # 4. Backend TkAgg
        step("Verificando matplotlib + tkinter (TkAgg)...")
        try:
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            ok("Backend TkAgg disponible")
        except ImportError as e:
            warn(f"TkAgg no disponible ({e}), reinstalando Pillow...")
            if profile.install_pip_package("--force-reinstall Pillow"):
                ok("Pillow reinstalado")
            else:
                fail("No se pudo corregir el backend TkAgg")
                errors.append("matplotlib-tkagg")

        # 5. Descargar app
        if not download_app(INSTALL_DIR):
            errors.append("descarga")

        if "descarga" not in errors:
            # 6. Acceso directo
            step("Creando acceso directo en el escritorio...")
            icon = next(INSTALL_DIR.glob("*.png"), None)
            if profile.create_shortcut(INSTALL_DIR, icon):
                ok("Acceso directo creado")
            else:
                warn("No se pudo crear el acceso directo automáticamente.")

            # 7. Autostart del updater
            step("Configurando actualizaciones automáticas al inicio del OS...")
            updater = INSTALL_DIR / "updater.py"
            if updater.exists():
                if profile.setup_autostart(updater):
                    ok("Updater configurado para ejecutarse al iniciar sesión")
                else:
                    warn("No se pudo configurar el autostart del updater.")
            else:
                warn(f"No se encontró {updater}")

    # Resumen
    print(f"\n{'='*55}")
    if needs_reboot:
        print(f"  {WARN}  Reiniciá el sistema y volvé a ejecutar el installer.")
    elif errors:
        print(f"  {FAIL}  Instalación incompleta. Problemas: {', '.join(errors)}")
        sys.exit(1)
    else:
        print(f"  {OK}  {APP_DISPLAY} instalado correctamente en:")
        print(f"       {INSTALL_DIR}")
        print(f"\n  Para iniciar la app:")
        if platform.system() == "Windows":
            print(f"       Doble clic en el acceso directo del escritorio")
            print(f"       o: python {INSTALL_DIR / 'app.py'}")
        else:
            print(f"       Doble clic en el ícono del escritorio")
            print(f"       o: python3 {INSTALL_DIR / 'app.py'}")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
