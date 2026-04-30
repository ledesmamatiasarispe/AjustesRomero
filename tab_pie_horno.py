import json
import socket
import subprocess
import threading
import tkinter as tk
from datetime import datetime
from tkinter import ttk, messagebox

from host_api import get_host_api_port, notify_data_changed
from pie_horno_config import PUBLIC_TUNNEL_URL
from storage import load_devices_state, save_devices_state

RASPBERRY_USER = "raspberry"
RASPBERRY_HOST = "192.168.0.133"
RASPBERRY_TARGET = f"{RASPBERRY_USER}@{RASPBERRY_HOST}"
RASPBERRY_REFRESH_MS = 30000
RASPBERRY_MAX_STATUS_FAILURES = 3
RASPBERRY_CONNECT_TIMEOUT = 8
RASPBERRY_CMD_TIMEOUT = 18
RASPBERRY_SLEEP_CMD = "/home/raspberry/.local/bin/pie-sleep"
RASPBERRY_WAKE_CMD = "/home/raspberry/.local/bin/pie-wake"
RASPBERRY_IDLE_CMD = "/home/raspberry/.local/bin/pie-idle-manager"


def _local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _status_label(status):
    labels = {
        "pending": "Pendiente",
        "approved": "Aprobado",
        "revoked": "Revocado",
    }
    return labels.get(str(status or ""), "Desconocido")


def _role_label(role):
    labels = {
        "editor": "Pie editor",
        "viewer": "Solo ver",
    }
    return labels.get(str(role or ""), "Solo ver")


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


class TabPieHorno(ttk.Frame):
    def __init__(self, parent):
        super().__init__(parent, padding=12)
        self._refresh_job = None
        self._raspberry_refresh_job = None
        self._raspberry_busy = False
        self._raspberry_status_failures = 0
        self._raspberry_auto_refresh_enabled = True
        self._tunnel_pause_callback = None
        self.tunnel_pause_text_var = tk.StringVar(value="Pausar tunnel")
        self.local_url_var = tk.StringVar(value=self._local_url_text())
        self._build()
        self.refresh()
        self._schedule_refresh()
        self.refresh_raspberry_status(manual=False)
        self._schedule_raspberry_refresh()

    def _build(self):
        top = ttk.LabelFrame(self, text="Acceso Pie de Horno", padding=12)
        top.pack(fill="x", pady=(0, 12))

        ttk.Label(top, text="URL publica para Raspberry / celular:").grid(row=0, column=0, sticky="w")
        ttk.Label(top, text=PUBLIC_TUNNEL_URL, font=("TkDefaultFont", 10, "bold")).grid(row=0, column=1, sticky="w", padx=(10, 0))
        ttk.Label(top, text="URL dentro de la red:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(top, textvariable=self.local_url_var).grid(row=1, column=1, sticky="w", padx=(10, 0), pady=(6, 0))
        ttk.Label(top, text="Estado tunnel publico:").grid(row=2, column=0, sticky="w", pady=(8, 0))
        self.tunnel_status_var = tk.StringVar(value="Iniciando...")
        tunnel_row = ttk.Frame(top)
        tunnel_row.grid(row=2, column=1, sticky="ew", padx=(10, 0), pady=(8, 0))
        tunnel_row.columnconfigure(0, weight=1)
        self.tunnel_status_label = ttk.Label(tunnel_row, textvariable=self.tunnel_status_var, foreground="#9a6a00")
        self.tunnel_status_label.grid(row=0, column=0, sticky="w")
        ttk.Button(
            tunnel_row,
            textvariable=self.tunnel_pause_text_var,
            command=self._toggle_tunnel_pause,
        ).grid(row=0, column=1, sticky="e", padx=(10, 0))
        ttk.Label(
            top,
            text="Un dispositivo aprobado normal solo ve datos. Marca como Pie editor a los dispositivos que pueden sumar/restar cucharas.",
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=(10, 0))
        top.columnconfigure(1, weight=1)

        raspberry_box = ttk.LabelFrame(self, text="Raspberry Pie de Horno", padding=12)
        raspberry_box.pack(fill="x", pady=(0, 12))
        raspberry_box.columnconfigure(1, weight=1)
        raspberry_box.columnconfigure(3, weight=1)

        self.raspberry_state_var = tk.StringVar(value="Sin consultar")
        self.raspberry_url_var = tk.StringVar(value="-")
        self.raspberry_idle_var = tk.StringVar(value="-")
        self.raspberry_detail_var = tk.StringVar(value="-")
        self.raspberry_action_var = tk.StringVar(value="")

        ttk.Label(raspberry_box, text="Conexion:").grid(row=0, column=0, sticky="w")
        self.raspberry_state_label = ttk.Label(raspberry_box, textvariable=self.raspberry_state_var, foreground="#9a6a00")
        self.raspberry_state_label.grid(row=0, column=1, sticky="w", padx=(8, 16))
        ttk.Label(raspberry_box, text="URL kiosk:").grid(row=0, column=2, sticky="w")
        ttk.Label(raspberry_box, textvariable=self.raspberry_url_var).grid(row=0, column=3, sticky="w", padx=(8, 0))

        ttk.Label(raspberry_box, text="Inactividad:").grid(row=1, column=0, sticky="w", pady=(6, 0))
        ttk.Label(raspberry_box, textvariable=self.raspberry_idle_var).grid(row=1, column=1, sticky="w", padx=(8, 16), pady=(6, 0))
        ttk.Label(raspberry_box, text="Detalle:").grid(row=1, column=2, sticky="w", pady=(6, 0))
        ttk.Label(raspberry_box, textvariable=self.raspberry_detail_var).grid(row=1, column=3, sticky="w", padx=(8, 0), pady=(6, 0))

        raspberry_buttons = ttk.Frame(raspberry_box)
        raspberry_buttons.grid(row=2, column=0, columnspan=4, sticky="ew", pady=(10, 0))
        ttk.Button(raspberry_buttons, text="Actualizar estado", command=self.refresh_raspberry_status).pack(side="left")
        ttk.Button(raspberry_buttons, text="Reposo falso", command=lambda: self._run_raspberry_action("sleep")).pack(side="left", padx=(8, 0))
        ttk.Button(raspberry_buttons, text="Despertar kiosk", command=lambda: self._run_raspberry_action("wake")).pack(side="left", padx=(8, 0))
        ttk.Button(raspberry_buttons, text="Reiniciar kiosk", command=lambda: self._run_raspberry_action("restart_kiosk")).pack(side="left", padx=(8, 0))
        ttk.Button(raspberry_buttons, text="Reiniciar Raspberry", command=lambda: self._run_raspberry_action("reboot")).pack(side="left", padx=(18, 0))
        ttk.Button(raspberry_buttons, text="Apagar completo", command=lambda: self._run_raspberry_action("poweroff")).pack(side="left", padx=(8, 0))
        ttk.Label(raspberry_buttons, textvariable=self.raspberry_action_var).pack(side="right")

        devices_box = ttk.LabelFrame(self, text="Dispositivos", padding=12)
        devices_box.pack(fill="both", expand=True)
        devices_box.rowconfigure(0, weight=1)
        devices_box.columnconfigure(0, weight=1)

        columns = ("name", "status", "role", "last_seen", "ip", "id")
        self.tree = ttk.Treeview(devices_box, columns=columns, show="headings", height=14)
        self.tree.heading("name", text="Dispositivo")
        self.tree.heading("status", text="Estado")
        self.tree.heading("role", text="Permiso")
        self.tree.heading("last_seen", text="Ultima conexion")
        self.tree.heading("ip", text="IP")
        self.tree.heading("id", text="ID corto")
        self.tree.column("name", width=230, anchor="w")
        self.tree.column("status", width=120, anchor="center")
        self.tree.column("role", width=120, anchor="center")
        self.tree.column("last_seen", width=170, anchor="center")
        self.tree.column("ip", width=140, anchor="center")
        self.tree.column("id", width=110, anchor="center")
        self.tree.grid(row=0, column=0, sticky="nsew")

        yscroll = ttk.Scrollbar(devices_box, orient="vertical", command=self.tree.yview)
        yscroll.grid(row=0, column=1, sticky="ns")
        self.tree.configure(yscrollcommand=yscroll.set)

        buttons = ttk.Frame(devices_box)
        buttons.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(buttons, text="Aprobar", command=self.approve_selected).pack(side="left")
        ttk.Button(buttons, text="Revocar", command=self.revoke_selected).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Hacer editor", command=self.make_editor_selected).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Solo ver", command=self.make_viewer_selected).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Eliminar", command=self.delete_selected).pack(side="left", padx=(8, 0))
        ttk.Button(buttons, text="Actualizar", command=self.refresh).pack(side="right")

        self.info_var = tk.StringVar(value="")
        ttk.Label(devices_box, textvariable=self.info_var).grid(row=2, column=0, columnspan=2, sticky="w", pady=(8, 0))

    def _local_url_text(self):
        return f"http://{_local_ip()}:{get_host_api_port()}/"

    def set_tunnel_pause_callback(self, callback):
        self._tunnel_pause_callback = callback

    def _toggle_tunnel_pause(self):
        if callable(self._tunnel_pause_callback):
            self._tunnel_pause_callback()

    def set_tunnel_status(self, info):
        if not isinstance(info, dict):
            return
        self.local_url_var.set(self._local_url_text())
        message = str(info.get("message") or "").strip()
        checked_at = str(info.get("checked_at") or "").strip()
        restarts = int(info.get("restarts") or 0)
        if checked_at:
            message = f"{message} | {checked_at}"
        if restarts:
            message = f"{message} | reinicios: {restarts}"
        self.tunnel_status_var.set(message or "Sin datos")

        state = str(info.get("state") or "").lower()
        paused = bool(info.get("paused")) or state == "paused"
        try:
            self.tunnel_pause_text_var.set("Reanudar tunnel" if paused else "Pausar tunnel")
        except Exception:
            pass
        color = "#1c7c35"
        if state == "paused":
            color = "#555555"
        elif state in ("warning", "starting", "restarting"):
            color = "#9a6a00"
        elif state == "error":
            color = "#b00020"
        try:
            self.tunnel_status_label.configure(foreground=color)
        except Exception:
            pass

    def _schedule_raspberry_refresh(self):
        if not self._raspberry_auto_refresh_enabled:
            return
        try:
            if self._raspberry_refresh_job is not None:
                self.after_cancel(self._raspberry_refresh_job)
        except Exception:
            pass
        self._raspberry_refresh_job = self.after(RASPBERRY_REFRESH_MS, self._raspberry_refresh_tick)

    def _raspberry_refresh_tick(self):
        self._raspberry_refresh_job = None
        if not self._raspberry_auto_refresh_enabled:
            return
        if self._raspberry_busy:
            self._schedule_raspberry_refresh()
            return
        self.refresh_raspberry_status(manual=False)

    def _ssh_command(self, command, timeout=RASPBERRY_CMD_TIMEOUT):
        return subprocess.run(
            [
                "ssh",
                "-o", "BatchMode=yes",
                "-o", f"ConnectTimeout={RASPBERRY_CONNECT_TIMEOUT}",
                RASPBERRY_TARGET,
                command,
            ],
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )

    def _raspberry_status_command(self):
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

    def refresh_raspberry_status(self, manual=True):
        if self._raspberry_busy:
            return False
        if manual:
            self._raspberry_auto_refresh_enabled = True
            self._raspberry_status_failures = 0
        self._raspberry_busy = True
        self.raspberry_action_var.set("Consultando...")

        def worker():
            try:
                result = self._ssh_command(self._raspberry_status_command(), timeout=RASPBERRY_CMD_TIMEOUT)
                output = result.stdout or ""
                error = (result.stderr or "").strip()
                self.after(0, lambda: self._apply_raspberry_status(result.returncode, output, error, manual))
            except Exception as ex:
                self.after(0, lambda: self._apply_raspberry_status(1, "", str(ex), manual))

        threading.Thread(target=worker, daemon=True).start()
        return True

    def _apply_raspberry_status(self, returncode, output, error, manual=False):
        self._raspberry_busy = False
        self.raspberry_action_var.set("")
        if returncode != 0 and not output:
            self._raspberry_status_failures += 1
            self.raspberry_state_var.set("Sin conexion SSH")
            self.raspberry_url_var.set("-")
            self.raspberry_idle_var.set("-")
            detail = error or "No responde"
            if self._raspberry_status_failures >= RASPBERRY_MAX_STATUS_FAILURES:
                self._raspberry_auto_refresh_enabled = False
                self.raspberry_detail_var.set(
                    f"{detail} | consultas automaticas detenidas tras {self._raspberry_status_failures} fallos"
                )
                self.raspberry_action_var.set("Automatico detenido. Usa Actualizar estado para reintentar.")
            else:
                self.raspberry_detail_var.set(
                    f"{detail} | fallo {self._raspberry_status_failures}/{RASPBERRY_MAX_STATUS_FAILURES}"
                )
            try:
                self.raspberry_state_label.configure(foreground="#b00020")
            except Exception:
                pass
            if self._raspberry_auto_refresh_enabled:
                self._schedule_raspberry_refresh()
            return

        self._raspberry_status_failures = 0
        self._raspberry_auto_refresh_enabled = True

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

        sleeping = details.get("SLEEPING") == "yes" or bool(idle.get("sleeping"))
        chromium_count = int(details.get("CHROMIUM") or 0)
        idle_manager_count = int(details.get("IDLE_MANAGER") or 0)
        if sleeping:
            state = "En reposo falso"
            color = "#9a6a00"
        elif chromium_count > 0:
            state = "Kiosk activo"
            color = "#1c7c35"
        else:
            state = "Conectada, kiosk cerrado"
            color = "#9a6a00"
        if idle_manager_count <= 0:
            state += " | idle manager detenido"
            color = "#b00020"

        self.raspberry_state_var.set(state)
        self.raspberry_url_var.set(details.get("URL") or "-")
        idle_text = _fmt_seconds(idle.get("idle_seconds"))
        sleep_after = _fmt_seconds(idle.get("sleep_after_seconds"))
        shutdown_after = _fmt_seconds(idle.get("shutdown_after_seconds"))
        self.raspberry_idle_var.set(f"{idle_text} sin tocar | reposo {sleep_after} | apagado {shutdown_after}")
        host = details.get("HOST") or "raspberry"
        mem = details.get("MEM") or "-"
        uptime = details.get("UPTIME") or "-"
        ip = details.get("IP") or RASPBERRY_HOST
        squeek = "si" if int(details.get("SQUEEKBOARD") or 0) > 0 else "no"
        self.raspberry_detail_var.set(f"{host} | {ip} | RAM {mem} | {uptime} | teclado {squeek}")
        try:
            self.raspberry_state_label.configure(foreground=color)
        except Exception:
            pass
        if self._raspberry_auto_refresh_enabled:
            self._schedule_raspberry_refresh()

    def _run_raspberry_action(self, action):
        if self._raspberry_busy:
            return
        commands = {
            "sleep": (RASPBERRY_SLEEP_CMD, "Mandando a reposo falso..."),
            "wake": (RASPBERRY_WAKE_CMD, "Despertando kiosk..."),
            "restart_kiosk": (
                f"killall -q chromium-browser chromium squeekboard || true; sleep 1; {RASPBERRY_WAKE_CMD}",
                "Reiniciando kiosk...",
            ),
            "reboot": ("sudo -n systemctl reboot", "Reiniciando Raspberry..."),
            "poweroff": ("sudo -n systemctl poweroff", "Apagando Raspberry..."),
        }
        if action not in commands:
            return
        if action == "reboot" and not messagebox.askyesno("Raspberry", "Reiniciar la Raspberry ahora?"):
            return
        if action == "poweroff" and not messagebox.askyesno(
            "Raspberry",
            "Apagar completamente la Raspberry?\n\nDespues no se puede despertar por SSH hasta que vuelva la energia.",
        ):
            return
        command, label = commands[action]
        self._raspberry_busy = True
        self.raspberry_action_var.set(label)

        def worker():
            try:
                timeout = 8 if action in ("reboot", "poweroff") else RASPBERRY_CMD_TIMEOUT
                result = self._ssh_command(command, timeout=timeout)
                err = (result.stderr or "").strip()
                out = (result.stdout or "").strip()
                msg = out or err or "Comando enviado."
                self.after(0, lambda: self._finish_raspberry_action(action, result.returncode, msg))
            except Exception as ex:
                self.after(0, lambda: self._finish_raspberry_action(action, 1, str(ex)))

        threading.Thread(target=worker, daemon=True).start()

    def _finish_raspberry_action(self, action, returncode, message):
        self._raspberry_busy = False
        if returncode == 0 or action in ("reboot", "poweroff"):
            self.raspberry_action_var.set(message[:120] if message else "Listo.")
        else:
            self.raspberry_action_var.set(f"Error: {message[:100]}")
        delay = 12000 if action == "reboot" else 2500
        self.after(delay, self.refresh_raspberry_status)

    def _schedule_refresh(self):
        try:
            if self._refresh_job is not None:
                self.after_cancel(self._refresh_job)
        except Exception:
            pass
        self._refresh_job = self.after(5000, self._refresh_tick)

    def _refresh_tick(self):
        self._refresh_job = None
        self.refresh(keep_selection=True)
        self._schedule_refresh()

    def _selected_id(self):
        selection = self.tree.selection()
        return selection[0] if selection else ""

    def _load_devices(self):
        state = load_devices_state()
        devices = state.get("devices", {})
        return devices if isinstance(devices, dict) else {}

    def refresh(self, keep_selection=False):
        self.local_url_var.set(self._local_url_text())
        selected = self._selected_id() if keep_selection else ""
        for item in self.tree.get_children():
            self.tree.delete(item)

        devices = self._load_devices()
        rows = sorted(
            devices.items(),
            key=lambda item: (
                0 if (item[1] or {}).get("status") == "pending" else 1,
                str((item[1] or {}).get("last_seen") or ""),
            ),
            reverse=False,
        )
        for device_id, data in rows:
            if not isinstance(data, dict):
                continue
            self.tree.insert(
                "",
                "end",
                iid=device_id,
                values=(
                    data.get("name", ""),
                    _status_label(data.get("status")),
                    _role_label(data.get("role")),
                    data.get("last_seen", ""),
                    data.get("ip", ""),
                    str(device_id)[:12],
                ),
            )

        if selected and self.tree.exists(selected):
            self.tree.selection_set(selected)
        pending = sum(1 for data in devices.values() if isinstance(data, dict) and data.get("status") == "pending")
        approved = sum(1 for data in devices.values() if isinstance(data, dict) and data.get("status") == "approved")
        editors = sum(1 for data in devices.values() if isinstance(data, dict) and data.get("status") == "approved" and data.get("role") == "editor")
        self.info_var.set(f"Pendientes: {pending} | Aprobados: {approved} | Pie editor: {editors}")

    def _set_selected_status(self, status):
        device_id = self._selected_id()
        if not device_id:
            messagebox.showinfo("Pie de Horno", "Selecciona un dispositivo primero.")
            return

        state = load_devices_state()
        devices = state.get("devices", {})
        if not isinstance(devices, dict) or device_id not in devices:
            self.refresh()
            return

        device = devices[device_id] if isinstance(devices[device_id], dict) else {}
        device["status"] = status
        if status == "approved":
            device["role"] = device.get("role") if device.get("role") in ("viewer", "editor") else "viewer"
            device["approved_at"] = _now_iso()
        elif status == "revoked":
            device["role"] = "viewer"
            device["revoked_at"] = _now_iso()
        devices[device_id] = device
        state["devices"] = devices
        save_devices_state(state)
        notify_data_changed()
        self.refresh(keep_selection=True)

    def approve_selected(self):
        self._set_selected_status("approved")

    def revoke_selected(self):
        self._set_selected_status("revoked")

    def _set_selected_role(self, role):
        device_id = self._selected_id()
        if not device_id:
            messagebox.showinfo("Pie de Horno", "Selecciona un dispositivo primero.")
            return

        state = load_devices_state()
        devices = state.get("devices", {})
        if not isinstance(devices, dict) or device_id not in devices:
            self.refresh()
            return

        if role == "editor":
            device = devices[device_id] if isinstance(devices[device_id], dict) else {}
            device["role"] = "editor"
            device["status"] = "approved"
            device["approved_at"] = device.get("approved_at") or _now_iso()
            device["editor_at"] = _now_iso()
            devices[device_id] = device
        else:
            device = devices[device_id] if isinstance(devices[device_id], dict) else {}
            device["role"] = "viewer"
            devices[device_id] = device

        state["devices"] = devices
        save_devices_state(state)
        notify_data_changed()
        self.refresh(keep_selection=True)

    def make_editor_selected(self):
        self._set_selected_role("editor")

    def make_viewer_selected(self):
        self._set_selected_role("viewer")

    def delete_selected(self):
        device_id = self._selected_id()
        if not device_id:
            messagebox.showinfo("Pie de Horno", "Selecciona un dispositivo primero.")
            return
        if not messagebox.askyesno("Pie de Horno", "Eliminar este dispositivo de la lista?"):
            return
        state = load_devices_state()
        devices = state.get("devices", {})
        if isinstance(devices, dict):
            devices.pop(device_id, None)
            state["devices"] = devices
            save_devices_state(state)
            notify_data_changed()
        self.refresh()
