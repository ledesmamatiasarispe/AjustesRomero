# raspberry_ssh.py -- control remoto por SSH de la Raspberry Pi que corre
# el navegador en modo kiosko en el piso de planta (Pie de Horno). Puerto
# de tab_pie_horno.py (los metodos _ssh_command/_raspberry_status_command/
# _apply_raspberry_status/_run_raspberry_action), sin cambios de
# comportamiento -- solo se reemplazan las variables Tkinter (StringVar)
# por un dict de retorno normal, ya que aca no hay widgets que actualizar.
# Requiere SSH con clave publica ya configurada hacia la Raspberry
# (BatchMode=yes = nunca pide contraseña; si no hay clave, el comando
# simplemente falla con "Sin conexion SSH").
import json
import subprocess

RASPBERRY_USER = "raspberry"
RASPBERRY_HOST = "192.168.0.121"
RASPBERRY_TARGET = f"{RASPBERRY_USER}@{RASPBERRY_HOST}"
RASPBERRY_CONNECT_TIMEOUT = 8
RASPBERRY_CMD_TIMEOUT = 18
RASPBERRY_SLEEP_CMD = "/home/raspberry/.local/bin/pie-sleep"
RASPBERRY_WAKE_CMD = "/home/raspberry/.local/bin/pie-wake"

RASPBERRY_ACTIONS = {
    "sleep": (RASPBERRY_SLEEP_CMD, "Mandando a reposo falso..."),
    "wake": (RASPBERRY_WAKE_CMD, "Despertando kiosk..."),
    "restart_kiosk": (
        f"killall -q chromium-browser chromium squeekboard || true; sleep 1; {RASPBERRY_WAKE_CMD}",
        "Reiniciando kiosk...",
    ),
    "reboot": ("sudo -n systemctl reboot", "Reiniciando Raspberry..."),
    "poweroff": ("sudo -n systemctl poweroff", "Apagando Raspberry..."),
}


def _fmt_seconds(seconds):
    try:
        total = max(0, int(float(seconds)))
    except Exception:
        return "-"
    hours = total // 3600
    minutes = (total % 3600) // 60
    secs = total % 60
    if hours:
        return f"{hours} h {minutes:02d} min"
    if minutes:
        return f"{minutes} min {secs:02d} s"
    return f"{secs} s"


def _ssh_command(command, timeout=RASPBERRY_CMD_TIMEOUT):
    return subprocess.run(
        ["ssh", "-o", "BatchMode=yes", "-o", f"ConnectTimeout={RASPBERRY_CONNECT_TIMEOUT}", RASPBERRY_TARGET, command],
        capture_output=True, text=True, timeout=timeout, check=False,
    )


def _status_command():
    # Un solo comando SSH que imprime todo el estado de una vez (mas rapido
    # que varias conexiones SSH separadas). __IDLE_BEGIN__/__IDLE_END__
    # delimitan el bloque JSON que devuelve pie-idle-manager (puede tener
    # saltos de linea/formato propio), y el resto son pares KEY=valor de
    # una sola linea -- por eso los dos formatos conviven en la misma salida.
    return r"""
printf '__IDLE_BEGIN__\n'
/home/raspberry/.local/bin/pie-idle-manager --status 2>/dev/null || true
printf '\n__IDLE_END__\n'
printf 'URL=%s\n' "$(cat /tmp/pie-de-horno-url.txt 2>/dev/null || true)"
printf 'HOST=%s\n' "$(hostname 2>/dev/null || true)"
printf 'IP=%s\n' "$(hostname -I 2>/dev/null || true)"
printf 'UPTIME=%s\n' "$(uptime -p 2>/dev/null || true)"
printf 'MEM=%s\n' "$(free -m 2>/dev/null | awk '/Mem:/ {print $3 "/" $2 " MiB"}')"
printf 'CHROMIUM=%s\n' "$(pgrep -fc 'chromium.*chromium-pie-horno' 2>/dev/null || true)"
printf 'SQUEEKBOARD=%s\n' "$(pgrep -fc '^squeekboard$' 2>/dev/null || true)"
printf 'IDLE_MANAGER=%s\n' "$(pgrep -fc 'pie-idle-manager' 2>/dev/null || true)"
printf 'SLEEPING=%s\n' "$(test -f /tmp/pie-horno-sleep.txt && echo yes || echo no)"
"""


def get_status():
    """Puerto de refresh_raspberry_status + _apply_raspberry_status
    fusionados (aca no hace falta separar "disparar" de "aplicar
    resultado" porque no hay un hilo de UI que proteger). Bloqueante --
    el llamador (router) lo corre en threadpool."""
    try:
        result = _ssh_command(_status_command(), timeout=RASPBERRY_CMD_TIMEOUT)
        output = result.stdout or ""
        error = (result.stderr or "").strip()
        returncode = result.returncode
    except Exception as ex:
        returncode, output, error = 1, "", str(ex)

    if returncode != 0 and not output:
        return {
            "connected": False,
            "state": "Sin conexion SSH",
            "state_color": "#b00020",
            "url": "-",
            "idle_text": "-",
            "detail": error or "No responde",
        }

    idle = {}
    details = {}
    in_idle = False
    idle_lines = []
    for line in (output or "").splitlines():
        if line.strip() == "__IDLE_BEGIN__":
            in_idle = True
            continue
        if line.strip() == "__IDLE_END__":
            in_idle = False
            try:
                idle = json.loads("\n".join(idle_lines).strip() or "{}")
            except Exception:
                idle = {}
            continue
        if in_idle:
            idle_lines.append(line)
            continue
        if "=" in line:
            key, value = line.split("=", 1)
            details[key.strip()] = value.strip()

    # Prioridad del estado mostrado: reposo falso primero (aunque chromium
    # siga corriendo, el kiosko lo pausa en vez de cerrarlo), despues si
    # chromium esta vivo, y si no ninguno de los dos. El idle manager caido
    # se agrega como sufijo de advertencia sobre cualquiera de esos tres
    # estados (en rojo), porque sin el la Raspberry no entra en reposo/
    # apagado automatico sola.
    sleeping = details.get("SLEEPING") == "yes" or bool(idle.get("sleeping"))
    chromium_count = int(details.get("CHROMIUM") or 0)
    idle_manager_count = int(details.get("IDLE_MANAGER") or 0)
    if sleeping:
        state, color = "En reposo falso", "#9a6a00"
    elif chromium_count > 0:
        state, color = "Kiosk activo", "#1c7c35"
    else:
        state, color = "Conectada, kiosk cerrado", "#9a6a00"
    if idle_manager_count <= 0:
        state += " | idle manager detenido"
        color = "#b00020"

    idle_text = _fmt_seconds(idle.get("idle_seconds"))
    sleep_after = _fmt_seconds(idle.get("sleep_after_seconds"))
    shutdown_after = _fmt_seconds(idle.get("shutdown_after_seconds"))
    host = details.get("HOST") or "raspberry"
    mem = details.get("MEM") or "-"
    uptime = details.get("UPTIME") or "-"
    ip = details.get("IP") or RASPBERRY_HOST
    squeek = "si" if int(details.get("SQUEEKBOARD") or 0) > 0 else "no"

    return {
        "connected": True,
        "state": state,
        "state_color": color,
        "url": details.get("URL") or "-",
        "idle_text": f"{idle_text} sin tocar | reposo {sleep_after} | apagado {shutdown_after}",
        "detail": f"{host} | {ip} | RAM {mem} | {uptime} | teclado {squeek}",
    }


def run_action(action):
    """Puerto de _run_raspberry_action (sin la confirmacion de
    reboot/poweroff -- eso lo pide el frontend con confirm() antes de
    pegarle al endpoint, mismo criterio que el resto de la app web).
    Bloqueante -- el llamador lo corre en threadpool."""
    if action not in RASPBERRY_ACTIONS:
        return {"ok": False, "message": "Accion invalida."}
    command, _label = RASPBERRY_ACTIONS[action]
    try:
        timeout = 8 if action in ("reboot", "poweroff") else RASPBERRY_CMD_TIMEOUT
        result = _ssh_command(command, timeout=timeout)
        err = (result.stderr or "").strip()
        out = (result.stdout or "").strip()
        message = out or err or "Comando enviado."
        ok = result.returncode == 0 or action in ("reboot", "poweroff")
        return {"ok": ok, "message": message[:200]}
    except Exception as ex:
        return {"ok": False, "message": str(ex)}
