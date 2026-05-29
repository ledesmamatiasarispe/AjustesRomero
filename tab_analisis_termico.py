import csv
import hashlib
import http.client
import json
import os
import re
import socket
import subprocess
import threading
import time
import tkinter as tk
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path
from tkinter import ttk, messagebox

from config import BG_ENTRY, FG, ACCENT
from storage import attach_thermal_analysis, load_history, load_thermal_device_records, save_thermal_device_records, load_thermal_ips, save_thermal_ips
from widgets import ScrollFrame
from device_sync import DeviceSyncService, WatchService

THERMAL_ANALYSIS_DIR = Path(r"C:\Users\LABOR01\Desktop\microestructura anialisis carbo2\exels")
THERMAL_EXTENSIONS = {".xlsx", ".xls", ".csv"}
DEFAULT_THERMAL_DEVICE_IP = "192.168.0.180"
THERMAL_MODE_OPTIONS = ("Microestructura", "Carbono", "Todos")
THERMAL_DEVICE_TIMEOUT = 45
THERMAL_DEVICE_RETRIES = 3
THERMAL_AUTO_POLL_TIMEOUT = 8
THERMAL_AUTO_POLL_RETRIES = 1
THERMAL_INFO_ROWS = (
    ("ID", ("ID",)),
    ("IP", ("IP",)),
    ("Equipamento", ("Equipamento", "Equipamiento")),
    ("Modo", ("Modo",)),
    ("Canal", ("Canal",)),
    ("Material", ("Material",)),
    ("Lote", ("Lote",)),
    ("Observacion", ("Observação", "Observacion", "ObservaÃ§Ã£o")),
    ("Dt Inicio", ("Dt Início", "Dt Inicio", "Dt InÃ­cio")),
    ("Dt Termino", ("Dt Término", "Dt Termino", "Dt TÃ©rmino")),
    ("Pico", ("Pico",)),
    ("TL", ("TL",)),
    ("CE %", ("CE %",)),
    ("Carbono %", ("Carbono %",)),
    ("Silicio %", ("Silicio %",)),
    ("TSE", ("TSE",)),
    ("TRE", ("TRE",)),
    ("REC", ("REC",)),
    ("Delta REC C/s", ("∆ REC °C/s", "Delta REC C/s", "âˆ† REC Â°C/s")),
    ("TF", ("TF",)),
    ("tag1 / TL (s)", ("tag1",)),
    ("tag2 / TSE (s)", ("tag2",)),
    ("tag3 / TRE (s)", ("tag3",)),
    ("tag4 / TF (s)", ("tag4",)),
)
THERMAL_RESULTS_NOTE = (
    "Supuesto de tiempos: se usa tag1=TL, tag2=TSE, tag3=TRE y tag4=TF, y esos tags estan en segundos. "
    "Si el equipo usa otra correspondencia, ajustamos la formula."
)
THERMAL_FIELD_ALIASES_V2 = {
    "ID": ("ID",),
    "IP": ("IP",),
    "Equipamento": ("Equipamento", "Equipamiento"),
    "Modo": ("Modo",),
    "Canal": ("Canal",),
    "Material": ("Material",),
    "Lote": ("Lote",),
    "Observacion": ("Observacao", "Observação", "Observacion", "ObservaÃ§Ã£o", "ObservaÃƒÂ§ÃƒÂ£o"),
    "Dt Inicio": ("Dt Inicio", "Dt Início", "Dt InÃ­cio", "Dt InÃƒÂ­cio"),
    "Dt Termino": ("Dt Termino", "Dt Término", "Dt TÃ©rmino", "Dt TÃƒÂ©rmino"),
    "Pico": ("Pico",),
    "TL": ("TL",),
    "CE %": ("CE %",),
    "TS": ("TS", "Solidus"),
    "C %": ("C %", "Carbono %"),
    "Si %": ("Si %", "Silicio %", "Silicon %"),
    "TSE": ("TSE",),
    "TRE": ("TRE",),
    "REC": ("REC",),
    "Delta REC C/s": ("Delta REC C/s", "Δ REC °C/s", "âˆ† REC Â°C/s", "Ã¢Ë†â€  REC Ã‚Â°C/s"),
    "TF": ("TF",),
    "tag1 / TL (s)": ("tag1",),
    "tag2 / TSE (s)": ("tag2",),
    "tag3 / TRE (s)": ("tag3",),
    "tag4 / TF (s)": ("tag4",),
}
THERMAL_INFO_COMMON_V2 = (
    "ID", "IP", "Equipamento", "Modo", "Canal", "Material", "Lote", "Observacion", "Dt Inicio", "Dt Termino",
)
THERMAL_INFO_MICRO_V2 = THERMAL_INFO_COMMON_V2 + (
    "Pico", "TL", "CE %", "TSE", "TRE", "REC", "Delta REC C/s", "TF",
    "tag1 / TL (s)", "tag2 / TSE (s)", "tag3 / TRE (s)", "tag4 / TF (s)",
)
THERMAL_INFO_CARBON_V2 = THERMAL_INFO_COMMON_V2 + (
    "Pico", "TL", "CE %", "TS", "C %", "Si %", "TF",
    "tag1 / TL (s)", "tag2 / TSE (s)", "tag3 / TRE (s)", "tag4 / TF (s)",
)
THERMAL_COLORS = ("#4ea1ff", "#ff9f43", "#7bd389", "#d17dd7", "#f45b69", "#8d99ae")
THERMAL_CHART_WIDTH = 820
THERMAL_CHART_HEIGHT = 520
THERMAL_CHART_MAX_POINTS_PER_CURVE = 1400


def _darken_hex(color, factor=0.68):
    raw = str(color or "").strip().lstrip("#")
    if len(raw) != 6:
        return color
    try:
        r = int(raw[0:2], 16)
        g = int(raw[2:4], 16)
        b = int(raw[4:6], 16)
    except Exception:
        return color
    r = max(0, min(255, int(r * factor)))
    g = max(0, min(255, int(g * factor)))
    b = max(0, min(255, int(b * factor)))
    return f"#{r:02x}{g:02x}{b:02x}"


class TabAnalisisTermico(ttk.Frame):
    def __init__(self, master):
        super().__init__(master, padding=8)
        self.folder = THERMAL_ANALYSIS_DIR
        self._records = []
        self._record_map = {}
        self._selected_paths = []
        self._chart_canvas = None
        self._chart_widget = None
        self._load_token = 0
        self._parsed_cache = {}
        self._device_records = self._normalize_device_records(load_thermal_device_records())
        self._linked_history_by_path = {}
        self._payloads_by_token = {}
        self._current_payloads = []
        self._curve_visibility = {}
        self._curve_var_map = {}
        self._left_pane_visible = True
        self._ajuste_target = None
        self._device_poll_running = False
        self._selection_after_job = None

        self.folder_var = tk.StringVar(value=str(self.folder))
        self.device_ip_var = tk.StringVar(value=DEFAULT_THERMAL_DEVICE_IP)
        self.mode_var = tk.StringVar(value="Microestructura")
        self.status_var = tk.StringVar(value="Sin archivos detectados.")
        self.selection_var = tk.StringVar(value="Selecciona uno o mas archivos para ver curvas y resultados.")
        self.toggle_list_var = tk.StringVar(value="Ocultar lista")

        # Servicio de sincronización automática en background
        self._sync_service = DeviceSyncService(
            ip=DEFAULT_THERMAL_DEVICE_IP,
            on_done=self._on_sync_done,
            on_log=self._log_backend,
        )

        # Servicio de vigilancia para auto ajuste
        self._watch_service = WatchService(
            ip=DEFAULT_THERMAL_DEVICE_IP,
            on_carbon=self._on_watch_carbon,
            on_status=self._log_backend,
            interval=20,
        )
        self._auto_ajuste_var = tk.BooleanVar(value=False)

        self._build_ui()
        self.refresh()

        # Arranca sync al abrir la pestaña (no bloquea la UI)
        self._sync_service.start_once()

    def _log_backend(self, message):
        top = self.winfo_toplevel() if hasattr(self, "winfo_toplevel") else None
        if top is not None and not bool(getattr(top, "_debug_mode", False)):
            return
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{stamp}][AnalisisTermico] {message}", flush=True)

    def _on_sync_done(self, result):
        """Callback del DeviceSyncService — corre en el thread de sync, usa after() para la UI."""
        if not result.get("ok"):
            self._log_backend(f"[sync] Error: {result.get('error','?')}")
            return
        new = result.get("new", 0)
        total = result.get("total", 0)
        self._log_backend(f"[sync] Completado — nuevos={new} total={total}")
        if new > 0:
            # Recargar registros desde DB y refrescar la lista en el hilo principal
            def _apply():
                try:
                    self._device_records = self._normalize_device_records(load_thermal_device_records())
                    self.refresh()
                    self.status_var.set(
                        f"{len(self._records)} archivo(s) detectado(s). "
                        f"Sync automático: {new} nuevo(s) descargado(s)."
                    )
                except Exception:
                    pass
            try:
                self.after(0, _apply)
            except Exception:
                pass

    # ---------- auto ajuste ----------

    def _toggle_auto_ajuste(self):
        if self._watch_service.is_running:
            self._watch_service.stop()
            self._auto_ajuste_var.set(False)
            self.status_var.set("Auto Ajuste desactivado.")
        else:
            if self._ajuste_target is None:
                import tkinter.messagebox as _mb
                _mb.showwarning(
                    "Auto Ajuste",
                    "La pestaña Ajuste no está disponible.\nAbrí la pestaña Ajuste primero.",
                    parent=self,
                )
                return
            # Actualizar IP desde el campo antes de arrancar
            ip = str(self.device_ip_var.get() or "").strip() or DEFAULT_THERMAL_DEVICE_IP
            self._watch_service.ip = ip
            self._save_ip_to_history(ip)
            # Sembrar IDs actuales para no disparar en registros viejos
            self._watch_service.reset_seed()
            self._watch_service.start()
            self._auto_ajuste_var.set(True)
            self.status_var.set(f"● Auto Ajuste activo — vigilando {ip}")
        self._update_auto_ajuste_btn()

    def _update_auto_ajuste_btn(self):
        if not hasattr(self, "_auto_ajuste_btn"):
            return
        if self._watch_service.is_running:
            self._auto_ajuste_btn.config(
                text="● Auto Ajuste ON",
                background="#2ecc71",
                foreground="#ffffff",
                activebackground="#27ae60",
                activeforeground="#ffffff",
            )
        else:
            self._auto_ajuste_btn.config(
                text="Auto Ajuste",
                background="#d9d9d9",
                foreground="#1a1a1a",
                activebackground="#c8c8c8",
                activeforeground="#1a1a1a",
            )

    def _on_watch_carbon(self, info):
        """
        Callback del WatchService — corre en el thread de vigilancia.
        Usa after(0, ...) para interactuar con la UI.
        """
        carbon  = info.get("C %")
        silicon = info.get("Si %")
        label   = info.get("_label", "Carbomax auto")

        if carbon is None or silicon is None:
            return

        def _apply():
            if self._ajuste_target is None:
                return
            try:
                self._ajuste_target.load_carbon_silicon(
                    carbon, silicon, source_label=label, force_estimate=True
                )
            except Exception as ex:
                self._log_backend(f"[watch] Error cargando C/Si en Ajuste: {ex}")
                return

            # Cambiar a la pestaña Ajuste automáticamente
            try:
                top = self.winfo_toplevel()
                top.nb.select(top.tab_ajuste)
            except Exception:
                pass

            self.status_var.set(
                f"● Auto Ajuste — C={carbon:.2f}%  Si={silicon:.2f}%  [{label}]"
            )

        try:
            self.after(0, _apply)
        except Exception:
            pass

    def _build_ui(self):
        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Analisis termico").pack(side="left")
        ttk.Button(top, text="Actualizar", command=self.refresh).pack(side="right")
        ttk.Button(top, text="Abrir carpeta", command=self._open_folder).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Descargar dispositivo", command=self._download_from_device).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Cargar C/Si en Ajuste", command=self._send_carbon_to_ajuste_v2).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Adjuntar a Historicos", command=self._attach_selected_to_history).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Eliminar", command=self._delete_selected).pack(side="right", padx=(0, 6))
        # Botón Auto Ajuste (toggle): verde cuando está activo
        self._auto_ajuste_btn = tk.Button(
            top,
            text="Auto Ajuste",
            command=self._toggle_auto_ajuste,
            relief="raised",
            bd=1,
        )
        self._auto_ajuste_btn.pack(side="right", padx=(0, 6))
        self._update_auto_ajuste_btn()
        ttk.Combobox(
            top,
            textvariable=self.mode_var,
            values=THERMAL_MODE_OPTIONS,
            state="readonly",
            width=16,
        ).pack(side="right", padx=(0, 6))
        self.mode_var.trace_add("write", lambda *_: self.refresh())
        ttk.Label(top, text="Modo").pack(side="right", padx=(0, 6))
        self._ip_combo = ttk.Combobox(
            top, textvariable=self.device_ip_var, width=17,
            values=load_thermal_ips() or [DEFAULT_THERMAL_DEVICE_IP],
        )
        self._ip_combo.pack(side="right", padx=(0, 6))
        ttk.Label(top, text="IP equipo").pack(side="right", padx=(0, 6))
        ttk.Button(top, textvariable=self.toggle_list_var, command=self._toggle_files_pane).pack(side="right", padx=(0, 6))

        folder_box = ttk.Frame(self)
        folder_box.pack(fill="x", pady=(0, 8))
        ttk.Label(folder_box, text="Carpeta").pack(side="left")
        ttk.Entry(folder_box, textvariable=self.folder_var, state="readonly").pack(side="left", fill="x", expand=True, padx=(8, 0))

        body = ttk.Panedwindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)
        self.body_pane = body

        left = ttk.LabelFrame(body, text="Archivos detectados", padding=8)
        right = ttk.Frame(body)
        self.left_pane = left
        self.right_pane = right
        body.add(left, weight=1)
        body.add(right, weight=4)

        self.files_tree = ttk.Treeview(
            left,
            columns=("archivo", "ip", "fecha"),
            show="headings",
            height=18,
            selectmode="extended",
        )
        self.files_tree.heading("archivo", text="Archivo")
        self.files_tree.heading("ip", text="IP")
        self.files_tree.heading("fecha", text="Modificado")
        self.files_tree.column("archivo", width=160, anchor="w")
        self.files_tree.column("ip", width=110, anchor="w")
        self.files_tree.column("fecha", width=110, anchor="w")
        self.files_tree.pack(side="left", fill="both", expand=True)
        self.files_tree.bind("<<TreeviewSelect>>", lambda e: self._on_select_files())

        files_scroll = ttk.Scrollbar(left, orient="vertical", command=self.files_tree.yview)
        files_scroll.pack(side="right", fill="y")
        self.files_tree.configure(yscrollcommand=files_scroll.set)

        detail_top = ttk.Frame(right)
        detail_top.pack(fill="both", expand=True)
        detail_bottom = ttk.LabelFrame(right, text="Estado", padding=8)
        detail_bottom.pack(fill="x", pady=(8, 0))

        chart_box = ttk.LabelFrame(detail_top, text="Grafico", padding=8)
        chart_box.pack(side="left", fill="both", expand=True)
        self.side_nb = ttk.Notebook(detail_top)
        self.side_nb.pack(side="left", fill="both", expand=True, padx=(8, 0))

        info_box = ttk.Frame(self.side_nb, padding=8)
        compare_box = ttk.Frame(self.side_nb, padding=8)
        stats_box = ttk.Frame(self.side_nb, padding=8)
        self.info_box = info_box
        self.compare_box = compare_box
        self.stats_box = stats_box
        self.side_nb.add(info_box, text="Informacion")
        self.side_nb.add(compare_box, text="Comparacion")
        self.side_nb.add(stats_box, text="Estadisticas")

        self.curves_box = ttk.LabelFrame(chart_box, text="Curvas visibles", padding=6)
        self.curves_box.pack(fill="x", pady=(0, 8))
        self.curves_inner = ttk.Frame(self.curves_box)
        self.curves_inner.pack(fill="x")

        self.chart_host = ttk.Frame(chart_box, width=THERMAL_CHART_WIDTH, height=THERMAL_CHART_HEIGHT)
        self.chart_host.pack(fill="both", expand=True)
        self.chart_host.pack_propagate(False)
        self.chart_placeholder = ttk.Label(
            self.chart_host,
            text="Selecciona uno o mas archivos de la lista para dibujar el grafico.",
            justify="left",
        )
        self.chart_placeholder.pack(anchor="center", expand=True)

        self.info_tree = ttk.Treeview(info_box, columns=("campo", "valor"), show="headings", height=20)
        self.info_tree.heading("campo", text="Campo")
        self.info_tree.heading("valor", text="Valor")
        self.info_tree.column("campo", width=140, anchor="w")
        self.info_tree.column("valor", width=210, anchor="w")
        self.info_tree.pack(side="left", fill="both", expand=True)
        info_scroll = ttk.Scrollbar(info_box, orient="vertical", command=self.info_tree.yview)
        info_scroll.pack(side="right", fill="y")
        self.info_tree.configure(yscrollcommand=info_scroll.set)

        compare_top = ttk.Frame(compare_box)
        compare_top.pack(fill="both", expand=True)
        self.compare_tree = ttk.Treeview(compare_top, columns=("metrica",), show="headings", height=17)
        self.compare_tree.heading("metrica", text="Metrica")
        self.compare_tree.column("metrica", width=220, anchor="w")
        self.compare_tree.pack(side="left", fill="both", expand=True)
        compare_scroll = ttk.Scrollbar(compare_top, orient="vertical", command=self.compare_tree.yview)
        compare_scroll.pack(side="right", fill="y")
        self.compare_tree.configure(yscrollcommand=compare_scroll.set)
        self.compare_text = tk.Text(
            compare_box,
            width=54,
            height=10,
            wrap="word",
            bg=BG_ENTRY,
            fg=FG,
            insertbackground=FG,
            relief="flat",
        )
        self.compare_text.pack(fill="both", expand=False, pady=(8, 0))
        self.compare_text.configure(state="disabled")

        stats_top = ttk.Frame(stats_box)
        stats_top.pack(fill="both", expand=True)
        self.stats_tree = ttk.Treeview(stats_top, columns=("metrica", "carbono", "micro"), show="headings", height=18)
        for cid, title, width in (
            ("metrica", "Metrica", 210),
            ("carbono", "Carbono", 170),
            ("micro", "Microestructura", 170),
        ):
            self.stats_tree.heading(cid, text=title)
            self.stats_tree.column(cid, width=width, anchor="w")
        self.stats_tree.pack(side="left", fill="both", expand=True)
        stats_scroll = ttk.Scrollbar(stats_top, orient="vertical", command=self.stats_tree.yview)
        stats_scroll.pack(side="right", fill="y")
        self.stats_tree.configure(yscrollcommand=stats_scroll.set)
        self.stats_text = tk.Text(
            stats_box,
            width=54,
            height=8,
            wrap="word",
            bg=BG_ENTRY,
            fg=FG,
            insertbackground=FG,
            relief="flat",
        )
        self.stats_text.pack(fill="both", expand=False, pady=(8, 0))
        self.stats_text.configure(state="disabled")

        ttk.Label(detail_bottom, textvariable=self.selection_var).pack(anchor="w")
        ttk.Label(detail_bottom, textvariable=self.status_var, foreground="#666666").pack(anchor="w", pady=(6, 0))

    def set_adjust_target(self, target):
        self._ajuste_target = target

    def _payload_mode_group(self, payload):
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        return self._device_mode_group((info or {}).get("Modo", ""))

    def open_records(self, paths, additive=True):
        wanted = [str(path or "").strip() for path in (paths or []) if str(path or "").strip()]
        if not wanted:
            return False
        self.refresh()
        existing = [path for path in wanted if path in self._record_map]
        if not existing and self.mode_var.get() != "Todos":
            self.mode_var.set("Todos")
            self.refresh()
            existing = [path for path in wanted if path in self._record_map]
        if not existing:
            return False
        selected = []
        if additive:
            selected.extend(str(path) for path in self._selected_paths if str(path) in self._record_map)
        for path in existing:
            if path not in selected:
                selected.append(path)
        self.files_tree.selection_set(selected)
        self.files_tree.focus(existing[-1])
        self.files_tree.see(existing[-1])
        self._load_selection(selected)
        return True

    def _make_text_panel(self, parent):
        widget = tk.Text(
            parent,
            width=54,
            height=22,
            wrap="word",
            bg=BG_ENTRY,
            fg=FG,
            insertbackground=FG,
            relief="flat",
        )
        widget.pack(side="left", fill="both", expand=True)
        widget.configure(state="disabled")
        scroll = ttk.Scrollbar(parent, orient="vertical", command=widget.yview)
        scroll.pack(side="right", fill="y")
        widget.configure(yscrollcommand=scroll.set)
        return widget

    def refresh(self):
        self._log_backend(f"Refresh vista. Modo={self.mode_var.get()} cache_dispositivo={len(self._device_records)}")
        self._records = self._scan_files() + self._filtered_device_records()
        self._record_map = {item["path"]: item for item in self._records}
        selected = [path for path in self._selected_paths if path in self._record_map]

        self.files_tree.delete(*self.files_tree.get_children())
        seen_iids = set()
        for item in self._records:
            iid = item["path"]
            if iid in seen_iids:
                continue
            seen_iids.add(iid)
            self.files_tree.insert("", "end", iid=iid, values=(item["name"], self._record_ip(item), item["modified"]))

        self.status_var.set(f"{len(self._records)} archivo(s) detectado(s) en {self.folder}.")
        self._refresh_stats_tab()

        if selected:
            self.files_tree.selection_set(selected)
            if selected:
                self.files_tree.focus(selected[0])
            self._load_selection(selected)
        else:
            self._selected_paths = []
            self._clear_detail()

    def _scan_files(self):
        items = []
        if not self.folder.exists():
            self.status_var.set(f"La carpeta no existe: {self.folder}")
            return items
        for path in sorted(self.folder.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
            if not path.is_file() or path.name.startswith("~$") or path.suffix.lower() not in THERMAL_EXTENSIONS:
                continue
            stamp = tk_time_string(path.stat().st_mtime)
            items.append({"name": path.name, "path": str(path), "modified": stamp, "source": "file"})
        return items

    def _filtered_device_records(self):
        selected_mode = str(self.mode_var.get() or "Microestructura").strip()
        if selected_mode == "Todos":
            return sorted(self._device_records, key=self._record_sort_datetime, reverse=True)
        out = []
        for item in self._device_records:
            mode = str(item.get("mode_group", "") or "").strip()
            if mode == selected_mode:
                out.append(item)
        return sorted(out, key=self._record_sort_datetime, reverse=True)

    def _normalize_device_records(self, records):
        out = []
        seen_paths = set()
        for item in records or []:
            if not isinstance(item, dict):
                continue
            payload = item.get("payload", {})
            info = payload.get("info", {}) if isinstance(payload, dict) else {}
            mode_group = str(item.get("mode_group", "") or self._device_mode_group(info.get("Modo", ""))).strip()
            clean = dict(item)
            clean["source"] = "device"
            clean["mode_group"] = mode_group
            if isinstance(payload, dict):
                identity = str(self._device_payload_identity(payload) or clean.get("identity", "") or "").strip()
                if identity:
                    clean["identity"] = identity
                    clean["local_id"] = self._device_local_id(identity)
                legacy_path = str(clean.get("legacy_path", "") or payload.get("legacy_path", "") or "").strip()
                if legacy_path:
                    clean["legacy_path"] = legacy_path
                local_id = str(clean.get("local_id", "") or "").strip()
                if local_id:
                    payload = dict(payload)
                    payload["identity"] = identity
                    payload["local_id"] = local_id
                    clean["path"] = self._make_device_payload_path(info.get("IP", ""), local_id)
                    payload["path"] = clean["path"]
                    if legacy_path:
                        payload["legacy_path"] = legacy_path
                    clean["payload"] = payload
            # Dedup: skip records whose path already appeared (prevents Treeview iid collision)
            record_path = str(clean.get("path", "") or "").strip()
            if record_path and record_path in seen_paths:
                continue
            if record_path:
                seen_paths.add(record_path)
            out.append(clean)
        return sorted(out, key=self._record_sort_datetime, reverse=True)

    def _download_from_device(self):
        ip = str(self.device_ip_var.get() or "").strip()
        if not ip:
            messagebox.showwarning("Analisis termico", "Ingresa la IP del equipo.", parent=self)
            return
        self._save_ip_to_history(ip)
        self._log_backend(f"Inicio descarga desde dispositivo {ip}")
        self.status_var.set(f"Descargando analisis termicos desde {ip}...")
        self.selection_var.set("Consultando el equipo...")
        worker = threading.Thread(target=self._download_from_device_worker, args=(ip,), daemon=True)
        worker.start()

    def poll_latest_carbon_async(self, session_started_at, consumed_paths, callback, timeout=None, after_ts=""):
        if self._device_poll_running:
            return False
        ip = str(self.device_ip_var.get() or "").strip()
        if not ip:
            return False
        self._device_poll_running = True
        worker = threading.Thread(
            target=self._poll_latest_carbon_worker,
            args=(ip, session_started_at, consumed_paths, callback, timeout, after_ts),
            daemon=True,
        )
        worker.start()
        return True

    def _poll_latest_carbon_worker(self, ip, session_started_at, consumed_paths, callback, timeout=None, after_ts=""):
        try:
            try:
                records = self._fetch_latest_carbon_records(ip, session_started_at, consumed_paths, timeout=timeout, after_ts=after_ts)
                source = "device"
            except Exception as ex:
                self._log_backend(f"Poll Carbono: consulta directa fallo; usando cache de Analisis termico: {ex}")
                cached = self._normalize_device_records(load_thermal_device_records())
                if not cached:
                    cached = list(self._device_records)
                records = cached
                source = "cache"
            latest = self._pick_latest_carbon_record(records, session_started_at, consumed_paths)
            def finish_ok():
                self._device_records = self._normalize_device_records(records)
                if source == "device":
                    save_thermal_device_records(self._device_records)
                try:
                    callback(latest, None)
                except Exception:
                    pass
            self.after(0, finish_ok)
        except Exception as ex:
            self.after(0, lambda err=ex: callback(None, err))
        finally:
            self.after(0, self._clear_device_poll_flag)

    def _clear_device_poll_flag(self):
        self._device_poll_running = False

    def _download_from_device_worker(self, ip):
        try:
            self._log_backend(f"Worker dispositivo activo para {ip}")
            records = self._fetch_device_records(ip)
        except Exception as ex:
            self._log_backend(f"ERROR descarga dispositivo {ip}: {ex}")
            self.after(0, lambda err=ex, addr=ip: self._finish_download_device_error(addr, err))
            return
        self._log_backend(f"Descarga dispositivo finalizada. Registros obtenidos={len(records)}")
        self.after(0, lambda: self._finish_download_device_ok(ip, records))

    def _finish_download_device_error(self, ip, ex):
        self.status_var.set(f"No se pudo descargar desde {ip}.")
        self.selection_var.set("Fallo la consulta al dispositivo.")
        messagebox.showerror("Analisis termico", f"No se pudo consultar el dispositivo {ip}.\n\n{ex}", parent=self)

    def _finish_download_device_ok(self, ip, records):
        self._log_backend(f"Persistiendo {len(records)} analisis descargados desde {ip}")
        self._device_records = self._normalize_device_records(records)
        save_thermal_device_records(self._device_records)
        self.refresh()
        if records:
            visible_records = self._filtered_device_records()
            if visible_records:
                first_path = visible_records[0]["path"]
                self.files_tree.selection_remove(self.files_tree.selection())
                self.files_tree.focus(first_path)
                self.files_tree.see(first_path)
            self._selected_paths = []
            self._clear_detail()
            self.selection_var.set("Analisis descargados del equipo. Elige uno o mas desde la lista.")
            self.status_var.set(
                f"{len(self._records)} archivo(s)/curva(s) detectado(s). "
                f"{len(records)} analisis termico(s) descargado(s) y guardados en esta PC desde {ip}."
            )
        else:
            self.selection_var.set("No se encontraron analisis termicos en el dispositivo.")
            self.status_var.set(f"El equipo {ip} respondio, pero no devolvio analisis termicos utilizables.")

    def _fetch_latest_carbon_records(self, ip, session_started_at=None, consumed_paths=None, timeout=None, after_ts=""):
        cached = self._normalize_device_records(load_thermal_device_records() or self._device_records)
        started_dt = self._parse_session_datetime(session_started_at)
        consumed = set()
        if isinstance(consumed_paths, (list, tuple, set)):
            consumed = {str(path).strip() for path in consumed_paths if str(path).strip()}
        elif consumed_paths:
            consumed = {str(consumed_paths).strip()}

        _timeout = timeout if timeout is not None else THERMAL_AUTO_POLL_TIMEOUT
        index_json = self._http_get_json(
            ip,
            "/getallidx.cgi",
            timeout=_timeout,
            retries=THERMAL_AUTO_POLL_RETRIES,
        )
        all_rows = self._extract_json_rows(index_json)

        # Filtrar por timestamp: solo registros posteriores al último procesado.
        # Esto es correcto con buffers circulares (el ID puede reiniciarse, el tiempo no).
        after_dt = self._parse_device_info_datetime(after_ts) if after_ts else None
        if after_dt:
            filtered = []
            for row in all_rows:
                row_dt = self._parse_device_info_datetime(
                    self._format_device_index_datetime(row.get("date"))
                )
                if row_dt and row_dt > after_dt:
                    filtered.append(row)
            all_rows = filtered

        index_rows = sorted(all_rows, key=self._index_row_sort_datetime, reverse=True)
        carbon_rows = [
            row for row in index_rows
            if "CARB" in str(row.get("mode", "") or "").upper()
        ]
        carbon_rows.sort(key=self._index_row_sort_datetime, reverse=True)

        existing_by_path = {}
        existing_by_index_hint = {}
        existing_by_device_id = {}
        existing_by_identity = {}
        for item in cached:
            payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
            info = payload.get("info", {}) if isinstance(payload, dict) else {}
            for candidate in (
                str(item.get("path", "") or payload.get("path", "") or "").strip(),
                str(item.get("legacy_path", "") or payload.get("legacy_path", "") or "").strip(),
            ):
                if candidate:
                    existing_by_path[candidate] = item
            hint = self._device_record_index_hint(item)
            if hint:
                existing_by_index_hint[hint] = item
            identity = self._device_record_identity(item)
            if identity:
                existing_by_identity[identity] = item
            device_id = (str(info.get("IP", "") or "").strip(), str(info.get("ID", "") or "").strip())
            if device_id[0] and device_id[1]:
                existing_by_device_id.setdefault(device_id, []).append(item)

        records_by_identity = {
            self._device_record_identity(item): item
            for item in cached
            if self._device_record_identity(item)
        }
        records_without_identity = [item for item in cached if not self._device_record_identity(item)]

        checked = 0
        for row in carbon_rows:
            row_dt = self._parse_device_info_datetime(self._format_device_index_datetime(row.get("date")))
            if started_dt and row_dt and row_dt < started_dt:
                break
            row_id = str(row.get("id", "") if row.get("id", "") is not None else "").strip()
            if not row_id:
                continue
            checked += 1
            existing = self._find_cached_device_record(ip, row_id, row, existing_by_path, existing_by_index_hint, existing_by_device_id)
            if existing and not self._device_record_needs_refresh(existing, row):
                if checked >= 8:
                    break
                continue

            detail_json = self._http_get_json(
                ip,
                f"/getdata.cgi?btrqh={urllib.parse.quote(row_id)}",
                timeout=_timeout,
                retries=THERMAL_AUTO_POLL_RETRIES,
            )
            detail_rows = self._extract_json_rows(detail_json)
            if not detail_rows:
                continue
            payload = self._build_device_payload(ip, row, detail_rows[0])
            if not payload.get("series"):
                continue
            identity = self._device_payload_identity(payload)
            local_id = self._device_local_id(identity)
            if local_id:
                payload["path"] = self._make_device_payload_path(ip, local_id)
                payload["local_id"] = local_id
                payload["identity"] = identity
            record = {
                "name": payload.get("name", f"{row_id}.json"),
                "path": payload.get("path", f"device://{ip}/{row_id}"),
                "legacy_path": payload.get("legacy_path", f"device://{ip}/{row_id}"),
                "identity": identity,
                "local_id": local_id,
                "modified": str(
                    self._format_device_index_datetime(row.get("date"))
                    or payload.get("info", {}).get("Dt Inicio", "")
                    or tk_time_string(datetime.now().timestamp())
                ),
                "source": "device",
                "mode_group": self._device_mode_group(payload.get("info", {}).get("Modo", "")),
                "payload": payload,
            }
            if identity:
                records_by_identity[identity] = record
            else:
                records_without_identity.append(record)
            records = list(records_by_identity.values()) + records_without_identity
            latest = self._pick_latest_carbon_record(records, session_started_at, consumed)
            if latest:
                return self._normalize_device_records(records)
            if checked >= 8:
                break

        return self._normalize_device_records(list(records_by_identity.values()) + records_without_identity)

    def _fetch_device_records(self, ip):
        self._log_backend(f"Solicitando indice getallidx.cgi a {ip}")
        index_json = self._http_get_json(ip, "/getallidx.cgi")
        index_rows = sorted(self._extract_json_rows(index_json), key=self._index_row_sort_datetime, reverse=True)
        self._log_backend(f"Indice recibido desde {ip}: {len(index_rows)} registro(s)")
        existing_by_path = {}
        existing_by_identity = {}
        existing_by_index_hint = {}
        existing_by_device_id = {}
        for item in self._device_records:
            if str(item.get("source", "") or "") != "device":
                continue
            payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
            path = str(item.get("path", "") or payload.get("path", "") or "").strip()
            legacy_path = str(item.get("legacy_path", "") or payload.get("legacy_path", "") or "").strip()
            for candidate in (path, legacy_path):
                if candidate:
                    existing_by_path[candidate] = item
            identity = self._device_record_identity(item)
            if identity:
                existing_by_identity[identity] = item
            hint = self._device_record_index_hint(item)
            if hint:
                existing_by_index_hint[hint] = item
            info = payload.get("info", {}) if isinstance(payload, dict) else {}
            device_id = (str(info.get("IP", "") or "").strip(), str(info.get("ID", "") or "").strip())
            if device_id[0] and device_id[1]:
                existing_by_device_id.setdefault(device_id, []).append(item)
        records = []
        seen_identities = set()
        reused = 0
        downloaded = 0
        for idx, row in enumerate(index_rows, start=1):
            row_id_value = row.get("id", "")
            row_id = str(row_id_value).strip() if row_id_value is not None else ""
            if row_id == "":
                self._log_backend(f"Fila indice {idx}: sin id, se omite")
                continue
            existing = self._find_cached_device_record(ip, row_id, row, existing_by_path, existing_by_index_hint, existing_by_device_id)
            if existing and not self._device_record_needs_refresh(existing, row):
                reused += 1
                reused_record = dict(existing)
                payload = reused_record.get("payload", {}) if isinstance(reused_record.get("payload"), dict) else {}
                info = payload.get("info", {}) if isinstance(payload, dict) else {}
                stamp = str(info.get("Dt Inicio", "") or info.get("Dt Termino", "") or "").strip()
                identity = self._device_record_identity(reused_record)
                local_id = str(reused_record.get("local_id", "") or self._device_local_id(identity)).strip()
                if local_id:
                    reused_record["local_id"] = local_id
                    reused_record["path"] = self._make_device_payload_path(ip, local_id)
                    reused_record["legacy_path"] = f"device://{ip}/{row_id}"
                    if isinstance(payload, dict):
                        payload = dict(payload)
                        payload["path"] = reused_record["path"]
                        payload["legacy_path"] = reused_record["legacy_path"]
                        reused_record["payload"] = payload
                reused_record["modified"] = self._format_device_index_datetime(row.get("date")) or str(
                    reused_record.get("modified", "") or ""
                )
                if identity:
                    seen_identities.add(identity)
                records.append(reused_record)
                self._log_backend(f"id={row_id}: ya existe en cache local, se reutiliza")
                continue
            if existing:
                self._log_backend(f"id={row_id}: cache incompleto para este modo, se redescarga detalle")
            self._log_backend(f"Descargando detalle {idx}/{len(index_rows)} id={row_id}")
            detail_json = self._http_get_json(ip, f"/getdata.cgi?btrqh={urllib.parse.quote(row_id)}")
            detail_rows = self._extract_json_rows(detail_json)
            if not detail_rows:
                self._log_backend(f"id={row_id}: detalle vacio")
                continue
            detail = detail_rows[0]
            payload = self._build_device_payload(ip, row, detail)
            if not payload.get("series"):
                self._log_backend(f"id={row_id}: sin puntos de curva, se omite")
                continue
            identity = self._device_payload_identity(payload)
            local_id = self._device_local_id(identity)
            if local_id:
                payload["path"] = self._make_device_payload_path(ip, local_id)
            if identity:
                seen_identities.add(identity)
            record = {
                "name": payload.get("name", f"{row_id}.json"),
                "path": payload.get("path", f"device://{ip}/{row_id}"),
                "legacy_path": payload.get("legacy_path", f"device://{ip}/{row_id}"),
                "identity": identity,
                "local_id": local_id,
                "modified": str(
                    self._format_device_index_datetime(row.get("date"))
                    or payload.get("info", {}).get("Dt Inicio", "")
                    or tk_time_string(datetime.now().timestamp())
                ),
                "source": "device",
                "mode_group": self._device_mode_group(payload.get("info", {}).get("Modo", "")),
                "payload": payload,
            }
            self._log_backend(
                f"id={row_id}: modo={record['mode_group']} puntos={len(payload.get('series', []))} "
                f"material={payload.get('info', {}).get('Material', '')}"
            )
            downloaded += 1
            records.append(record)
        for identity, item in existing_by_identity.items():
            if identity in seen_identities:
                continue
            records.append(item)
        records.sort(key=self._record_sort_datetime, reverse=True)
        self._log_backend(
            f"Total sincronizado desde {ip}: {len(records)} | nuevos={downloaded} | reutilizados={reused}"
        )
        return records

    def _find_cached_device_record(self, ip, row_id, index_row, existing_by_path, existing_by_index_hint, existing_by_device_id):
        hint = self._device_index_identity_hint(ip, index_row)
        if hint and hint in existing_by_index_hint:
            return existing_by_index_hint[hint]
        payload_path = f"device://{ip}/{row_id}"
        existing = existing_by_path.get(payload_path)
        candidates = list(existing_by_device_id.get((str(ip), str(row_id)), []))
        if existing and existing not in candidates:
            candidates.append(existing)
        index_dt = None
        if isinstance(index_row, dict):
            index_dt = self._parse_device_info_datetime(self._format_device_index_datetime(index_row.get("date")))
        if index_dt:
            for candidate in candidates:
                payload = candidate.get("payload", {}) if isinstance(candidate, dict) else {}
                info = payload.get("info", {}) if isinstance(payload, dict) else {}
                record_dt = (
                    self._parse_device_info_datetime(info.get("Dt Inicio"))
                    or self._parse_device_info_datetime(info.get("Dt Termino"))
                )
                if record_dt and abs((index_dt - record_dt).total_seconds()) <= 60:
                    return candidate
        return existing

    def _device_index_identity_hint(self, ip, row):
        if not isinstance(row, dict):
            return ""
        dt = self._parse_device_info_datetime(self._format_device_index_datetime(row.get("date")))
        stamp = dt.strftime("%Y-%m-%d %H:%M") if dt else str(row.get("date", "") or "").strip()
        parts = (
            str(ip or "").strip(),
            stamp,
            self._clean_device_text(row.get("mode", "")).upper(),
            self._clean_device_text(row.get("material", "")).upper(),
            self._clean_device_text(row.get("lot", "")).upper(),
        )
        if not parts[0] or not parts[1]:
            return ""
        return "|".join(parts)

    def _device_record_index_hint(self, record):
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        dt = self._parse_device_info_datetime(info.get("Dt Inicio")) or self._parse_device_info_datetime(info.get("Dt Termino"))
        stamp = dt.strftime("%Y-%m-%d %H:%M") if dt else str(info.get("Dt Inicio", "") or info.get("Dt Termino", "") or "").strip()
        parts = (
            str(info.get("IP", "") or "").strip(),
            stamp,
            self._clean_device_text(info.get("Modo", "")).upper(),
            self._clean_device_text(info.get("Material", "")).upper(),
            self._clean_device_text(info.get("Lote", "")).upper(),
        )
        if not parts[0] or not parts[1]:
            return ""
        return "|".join(parts)

    def _device_payload_identity(self, payload):
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        parts = (
            str(info.get("Dt Inicio", "") or info.get("Dt Termino", "") or "").strip(),
            str(info.get("Dt Termino", "") or "").strip(),
            str(info.get("Modo", "") or "").strip().upper(),
            str(info.get("Material", "") or "").strip().upper(),
            str(info.get("Lote", "") or "").strip().upper(),
            str(info.get("Canal", "") or "").strip(),
            str(info.get("tag1", "") or "").strip(),
            str(info.get("tag2", "") or "").strip(),
            str(info.get("tag3", "") or "").strip(),
            str(info.get("tag4", "") or "").strip(),
            str(info.get("Pico", "") or "").strip(),
            str(info.get("TL", "") or "").strip(),
            str(info.get("CE %", "") or "").strip(),
            str(info.get("TS", "") or "").strip(),
            str(info.get("C %", "") or "").strip(),
            str(info.get("Si %", "") or "").strip(),
            str(info.get("TSE", "") or "").strip(),
            str(info.get("TRE", "") or "").strip(),
            str(info.get("REC", "") or "").strip(),
            str(info.get("Delta REC C/s", "") or "").strip(),
            str(info.get("TF", "") or "").strip(),
        )
        if not parts[0]:
            return ""
        return "|".join(parts)

    def _device_local_id(self, identity):
        text = str(identity or "").strip()
        if not text:
            return ""
        return hashlib.sha1(text.encode("utf-8", errors="ignore")).hexdigest()[:16]

    def _device_record_identity(self, record):
        if not isinstance(record, dict):
            return ""
        identity = str(record.get("identity", "") or "").strip()
        if identity:
            return identity
        payload = record.get("payload", {}) if isinstance(record.get("payload"), dict) else {}
        return self._device_payload_identity(payload)

    def _record_sort_datetime(self, item):
        payload = item.get("payload", {}) if isinstance(item, dict) else {}
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        dt = (
            self._parse_device_info_datetime(info.get("Dt Termino"))
            or self._parse_device_info_datetime(info.get("Dt Inicio"))
            or self._parse_device_info_datetime(item.get("modified", "") if isinstance(item, dict) else "")
        )
        return dt or datetime.min

    def _index_row_sort_datetime(self, row):
        if not isinstance(row, dict):
            return datetime.min
        return self._parse_device_info_datetime(self._format_device_index_datetime(row.get("date"))) or datetime.min

    def _device_record_needs_refresh(self, record, index_row=None):
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        if isinstance(index_row, dict):
            index_dt = self._parse_device_info_datetime(self._format_device_index_datetime(index_row.get("date")))
            record_dt = (
                self._parse_device_info_datetime(info.get("Dt Inicio"))
                or self._parse_device_info_datetime(info.get("Dt Termino"))
            )
            if index_dt and record_dt and abs((index_dt - record_dt).total_seconds()) > 60:
                return True
        mode_hint = str(info.get("Modo", "") or "")
        if not mode_hint and isinstance(index_row, dict):
            mode_hint = str(index_row.get("mode", "") or "")
        group = self._device_mode_group(mode_hint)
        if group == "Carbono":
            return not (
                str(info.get("C %", "") or "").strip()
                and str(info.get("Si %", "") or "").strip()
                and str(info.get("TS", "") or "").strip()
            )
        if group == "Microestructura":
            return not (
                str(info.get("TSE", "") or "").strip()
                and str(info.get("TRE", "") or "").strip()
                and str(info.get("REC", "") or "").strip()
            )
        return False

    def _pick_latest_carbon_record(self, records, session_started_at, consumed_paths):
        started_dt = self._parse_session_datetime(session_started_at)
        consumed = set()
        if isinstance(consumed_paths, (list, tuple, set)):
            consumed = {str(path).strip() for path in consumed_paths if str(path).strip()}
        elif consumed_paths:
            consumed = {str(consumed_paths).strip()}
        candidates = []
        for record in records or []:
            if str(record.get("mode_group", "") or "") != "Carbono":
                continue
            payload = record.get("payload", {}) if isinstance(record.get("payload"), dict) else {}
            info = payload.get("info", {}) if isinstance(payload, dict) else {}
            dt = self._parse_device_info_datetime(info.get("Dt Termino")) or self._parse_device_info_datetime(info.get("Dt Inicio"))
            if started_dt and not dt:
                continue
            if started_dt and dt and dt < started_dt:
                continue
            if not (
                str(info.get("C %", "") or info.get("Carbono %", "") or "").strip()
                and str(info.get("Si %", "") or info.get("Silicio %", "") or "").strip()
            ):
                continue
            path = str(record.get("path", "") or "").strip()
            legacy_path = str(record.get("legacy_path", "") or payload.get("legacy_path", "") or "").strip()
            identity = self._device_record_identity(record)
            local_id = str(record.get("local_id", "") or payload.get("local_id", "") or "").strip()
            local_key = f"local_id:{local_id}" if local_id else ""
            if (
                (path and path in consumed)
                or (legacy_path and legacy_path in consumed)
                or (identity and identity in consumed)
                or (local_id and local_id in consumed)
                or (local_key and local_key in consumed)
            ):
                continue
            candidates.append((dt or datetime.min, record))
        candidates.sort(key=lambda item: item[0], reverse=True)
        if not candidates:
            return None
        _, record = candidates[0]
        return record

    def _http_get_json(self, ip, endpoint, timeout=None, retries=None):
        url = f"http://{ip}{endpoint}"
        last_error = None
        timeout = THERMAL_DEVICE_TIMEOUT if timeout is None else timeout
        retries = THERMAL_DEVICE_RETRIES if retries is None else retries
        for attempt in range(1, retries + 1):
            try:
                self._log_backend(f"HTTP GET intento {attempt}/{retries}: {url}")
                req = urllib.request.Request(url, headers={"User-Agent": "AjusteComp/1.0"})
                with urllib.request.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read()
                self._log_backend(f"HTTP OK {url} bytes={len(raw)}")
                return self._parse_device_json_bytes(raw, url)
            except http.client.BadStatusLine as ex:
                last_error = ex
                self._log_backend(f"HTTP no estandar {url}: {ex}")
                try:
                    return self._http_get_json_raw_socket(ip, endpoint, timeout=timeout)
                except Exception as raw_ex:
                    last_error = raw_ex
                    self._log_backend(f"Fallback socket fallo {url}: {raw_ex}")
            except (urllib.error.URLError, TimeoutError, socket.timeout, json.JSONDecodeError) as ex:
                last_error = ex
                self._log_backend(f"HTTP fallo {url}: {ex}")
                if attempt < retries:
                    time.sleep(1.2)
                continue
        if isinstance(last_error, json.JSONDecodeError):
            raise RuntimeError(f"Respuesta JSON invalida en {url}: {last_error}") from last_error
        raise RuntimeError(
            f"No hubo respuesta util de {url} despues de {retries} intento(s) "
            f"de {timeout}s."
        ) from last_error

    def _http_get_json_raw_socket(self, ip, endpoint, timeout=None):
        timeout = THERMAL_DEVICE_TIMEOUT if timeout is None else timeout
        request = (
            f"GET {endpoint} HTTP/1.0\r\n"
            f"Host: {ip}\r\n"
            "User-Agent: AjusteComp/1.0\r\n"
            "Connection: close\r\n\r\n"
        ).encode("ascii", errors="ignore")
        with socket.create_connection((ip, 80), timeout=timeout) as sock:
            sock.settimeout(timeout)
            sock.sendall(request)
            chunks = []
            while True:
                chunk = sock.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
        raw = b"".join(chunks)
        self._log_backend(f"Socket crudo OK http://{ip}{endpoint} bytes={len(raw)}")
        return self._parse_device_json_bytes(raw, f"http://{ip}{endpoint}")

    def _parse_device_json_bytes(self, raw, url):
        text = raw.decode("utf-8", errors="replace").replace("00011900", "01011900").replace("\\", "/").strip()
        if text.startswith("HTTP/"):
            sep = "\r\n\r\n"
            pos = text.find(sep)
            if pos >= 0:
                text = text[pos + len(sep):].strip()
            else:
                pos = text.find("\n\n")
                if pos >= 0:
                    text = text[pos + 2:].strip()
        lowered = text[:300].lower()
        if lowered.startswith("<!doctype") or lowered.startswith("<html") or "<html" in lowered:
            title = ""
            match = re.search(r"<title>\s*(.*?)\s*</title>", text, flags=re.IGNORECASE | re.DOTALL)
            if match:
                title = re.sub(r"\s+", " ", match.group(1)).strip()
            suffix = f" ({title})" if title else ""
            raise RuntimeError(
                f"El equipo devolvio HTML{suffix}, no JSON, en {url}. "
                "Verifica que el Carbomax este en la pantalla/servicio correcto o reintenta la conexion."
            )
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            line = text.splitlines()[0].strip() if text else ""
            if line.startswith("{") or line.startswith("["):
                return json.loads(line)
            preview = re.sub(r"\s+", " ", text[:120]).strip()
            raise RuntimeError(f"Respuesta JSON invalida en {url}: {preview}...")

    def _extract_json_rows(self, obj):
        if isinstance(obj, list):
            if obj and isinstance(obj[0], dict):
                return obj
            return []
        if isinstance(obj, dict):
            if obj and all(not isinstance(v, (list, dict)) for v in obj.values()):
                return [obj]
            for value in obj.values():
                rows = self._extract_json_rows(value)
                if rows:
                    return rows
        return []

    def _build_device_payload(self, ip, index_row, detail):
        mode = self._clean_device_text(detail.get("test_mode", ""))
        model = str(detail.get("product", "") or "").strip()
        row_id = str(detail.get("id", "") or index_row.get("id", "") or "").strip()
        period_step = 0.1 if "LAN" in mode.upper() else 0.5
        temps = self._coerce_number_list(detail.get("data_temp"))
        derivs = self._coerce_number_list(detail.get("data_deriv"))
        series = []
        total = min(len(temps), len(derivs))
        period = period_step
        for idx in range(total):
            series.append(
                {
                    "periodo": round(period, 2),
                    "temperatura": round(temps[idx] / 10.0, 1),
                    "derivada": round(derivs[idx] / 100.0, 2),
                }
            )
            period += period_step

        info = {
            "ID": row_id,
            "IP": ip,
            "Equipamento": "DELTA",
            "Modo": mode,
            "Canal": str(detail.get("channel", "") or "").strip(),
            "Material": self._clean_device_text(detail.get("material", "")),
            "Lote": self._clean_device_text(detail.get("lot", "")),
            "Observacion": self._clean_device_text(detail.get("obsevation", "")),
            "Dt Inicio": self._format_device_datetime(detail.get("start_date")),
            "Dt Termino": self._format_device_datetime(detail.get("stop_date")),
            "tag1": self._stringify_device_value(detail.get("tag1")),
            "tag2": self._stringify_device_value(detail.get("tag2")),
            "tag3": self._stringify_device_value(detail.get("tag3")),
            "tag4": self._stringify_device_value(detail.get("tag4")),
            "Modelo": model,
        }
        mode_upper = mode.upper()
        if "MICR" in mode_upper:
            info["Pico"] = self._scaled_device_value(detail.get("peak"), 10.0, 1)
            info["TL"] = self._scaled_device_value(detail.get("liquidus"), 10.0, 1)
            info["CE %"] = self._scaled_device_value(detail.get("carbon_eq"), 100.0, 2)
            info["TSE"] = self._scaled_device_value(detail.get("tse"), 10.0, 1)
            info["TRE"] = self._scaled_device_value(detail.get("tre"), 10.0, 1)
            info["REC"] = self._scaled_device_value(detail.get("recalec"), 10.0, 1)
            info["Delta REC C/s"] = self._scaled_device_value(detail.get("delta_rec"), 10.0, 1)
            info["TF"] = self._scaled_device_value(detail.get("final"), 10.0, 1)
        elif "CARB" in mode_upper:
            info["Pico"] = self._scaled_device_value(detail.get("peak"), 10.0, 1)
            info["TL"] = self._scaled_device_value(detail.get("liquidus"), 10.0, 1)
            info["CE %"] = self._scaled_device_value(detail.get("carbon_eq"), 100.0, 2)
            info["TS"] = self._scaled_device_value(detail.get("solidus"), 10.0, 1)
            info["C %"] = self._scaled_device_value(detail.get("carbon"), 100.0, 2)
            info["Si %"] = self._scaled_device_value(detail.get("silicon"), 100.0, 2)
            info["TF"] = self._scaled_device_value(detail.get("final"), 10.0, 1)
        else:
            info["Pico"] = self._scaled_device_value(detail.get("peak"), 10.0, 1)
            info["TL"] = self._scaled_device_value(detail.get("liquidus"), 10.0, 1)
            info["TF"] = self._scaled_device_value(detail.get("final"), 10.0, 1)

        stamp = info.get("Dt Inicio") or info.get("Dt Termino") or ""
        label_parts = [f"[{ip}]", row_id]
        if mode:
            label_parts.append(mode)
        if stamp:
            label_parts.append(stamp)
        identity_preview = self._device_payload_identity({"info": info})
        local_id = self._device_local_id(identity_preview)
        payload_path = self._make_device_payload_path(ip, local_id) if local_id else f"device://{ip}/{row_id}"
        payload_name = " ".join(part for part in label_parts if part).strip()
        return {
            "info": info,
            "series": series,
            "path": payload_path,
            "legacy_path": f"device://{ip}/{row_id}",
            "local_id": local_id,
            "identity": identity_preview,
            "name": payload_name,
            "source": "device",
        }

    def _make_device_payload_path(self, ip, local_id):
        key = re.sub(r"[^0-9A-Za-z]+", "", str(local_id or ""))[:24]
        if key:
            return f"device://{ip}/local/{key}"
        return f"device://{ip}/local"

    def _device_mode_group(self, mode_value):
        mode = str(mode_value or "").upper()
        if "MICR" in mode:
            return "Microestructura"
        if "CARB" in mode:
            return "Carbono"
        return "Todos"

    def _coerce_number_list(self, value):
        if isinstance(value, list):
            return [self._parse_decimal(item) or 0.0 for item in value]
        if isinstance(value, tuple):
            return [self._parse_decimal(item) or 0.0 for item in value]
        if isinstance(value, str):
            raw = value.strip()
            if raw.startswith("[") and raw.endswith("]"):
                try:
                    data = json.loads(raw)
                    if isinstance(data, list):
                        return [self._parse_decimal(item) or 0.0 for item in data]
                except Exception:
                    pass
        return []

    def _clean_device_text(self, value):
        return str(value or "").replace("\ufffd", "").replace("\u0003", "").strip()

    def _stringify_device_value(self, value):
        if value is None or value == "":
            return ""
        if isinstance(value, (int, float)):
            return str(int(value)) if float(value).is_integer() else str(value)
        return str(value).strip()

    def _scaled_device_value(self, value, divisor, decimals):
        number = self._parse_decimal(value)
        if number is None:
            return ""
        return f"{round(number / divisor, decimals):.{decimals}f}"

    def _format_device_datetime(self, value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        for fmt in ("%d/%m/%Y %H:%M:%S", "%d/%m/%Y", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%d%m%Y %H%M%S", "%d%m%Y%H%M%S"):
            try:
                return datetime.strptime(raw, fmt).strftime("%d/%m/%Y %H:%M")
            except Exception:
                pass
        return raw

    def _format_device_index_datetime(self, value):
        raw = str(value or "").strip()
        if not raw:
            return ""
        for fmt in ("%d%m%Y %H%M%S", "%d%m%Y%H%M%S"):
            try:
                return datetime.strptime(raw, fmt).strftime("%d/%m/%Y %H:%M")
            except Exception:
                pass
        return raw

    def _parse_device_info_datetime(self, value):
        raw = str(value or "").strip()
        if not raw:
            return None
        for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d%m%Y %H%M%S", "%d%m%Y%H%M%S"):
            try:
                return datetime.strptime(raw, fmt)
            except Exception:
                pass
        return None

    def _parse_session_datetime(self, value):
        raw = str(value or "").strip()
        if not raw:
            return None
        for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
            try:
                return datetime.strptime(raw, fmt)
            except Exception:
                pass
        return None

    def _save_ip_to_history(self, ip):
        ip = str(ip or "").strip()
        if not ip:
            return
        history = [ip] + [h for h in load_thermal_ips() if h != ip]
        history = history[:10]
        save_thermal_ips(history)
        if hasattr(self, "_ip_combo"):
            self._ip_combo.configure(values=history)

    def _record_ip(self, item):
        if str(item.get("source", "") or "") != "device":
            return ""
        payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        return str(info.get("IP", "") or "").strip()

    def _delete_selected(self):
        if not self._selected_paths:
            messagebox.showinfo("Eliminar", "No hay registros seleccionados.", parent=self)
            return
        to_delete = [self._record_map[p] for p in self._selected_paths if p in self._record_map]
        if not to_delete:
            return
        names = [r["name"] for r in to_delete]
        preview = "\n".join(f"  - {n}" for n in names[:6])
        if len(names) > 6:
            preview += f"\n  ... y {len(names) - 6} más"
        if not messagebox.askyesno(
            "Eliminar registros",
            f"¿Eliminar {len(to_delete)} registro(s)?\n\n{preview}",
            parent=self,
        ):
            return
        errors = []
        device_paths_removed = set()
        for record in to_delete:
            source = str(record.get("source", "") or "")
            path = str(record.get("path", "") or "")
            if source == "file":
                try:
                    Path(path).unlink()
                except Exception as ex:
                    errors.append(f"{record['name']}: {ex}")
            elif source == "device":
                device_paths_removed.add(path)
        if device_paths_removed:
            self._device_records = [
                r for r in self._device_records
                if str(r.get("path", "") or "") not in device_paths_removed
            ]
            save_thermal_device_records(self._device_records)
        if errors:
            messagebox.showwarning(
                "Eliminar",
                f"Eliminados con errores:\n" + "\n".join(errors),
                parent=self,
            )
        self._selected_paths = []
        self._parsed_cache = {k: v for k, v in self._parsed_cache.items() if k not in device_paths_removed}
        self.refresh()

    def _toggle_files_pane(self):
        if self._left_pane_visible:
            try:
                self.body_pane.forget(self.left_pane)
            except Exception:
                pass
            self._left_pane_visible = False
            self.toggle_list_var.set("Mostrar lista")
        else:
            try:
                self.body_pane.insert(0, self.left_pane, weight=1)
            except Exception:
                try:
                    self.body_pane.add(self.left_pane, weight=1)
                except Exception:
                    pass
            self._left_pane_visible = True
            self.toggle_list_var.set("Ocultar lista")

    def _on_select_files(self):
        if self._selection_after_job is not None:
            try:
                self.after_cancel(self._selection_after_job)
            except Exception:
                pass
            self._selection_after_job = None
        self._selection_after_job = self.after(180, self._apply_files_selection)

    def _apply_files_selection(self):
        self._selection_after_job = None
        paths = list(self.files_tree.selection())
        if not paths:
            self._selected_paths = []
            self._clear_detail()
            return
        self._load_selection(paths)

    def _load_selection(self, paths):
        self._selected_paths = list(paths)
        self._load_token += 1
        token = self._load_token
        names = [self._record_map[path]["name"] for path in paths if path in self._record_map]
        self._log_backend(f"Cargando seleccion token={token} curvas={len(paths)}")
        self._show_loading(names)
        worker = threading.Thread(target=self._load_selection_worker, args=(token, list(paths)), daemon=True)
        worker.start()

    def _load_selection_worker(self, token, paths):
        com_ready = False
        pythoncom = None
        try:
            try:
                import pythoncom  # type: ignore
                pythoncom.CoInitialize()
                com_ready = True
            except Exception:
                pythoncom = None

            payloads = []
            total = max(1, len(paths))
            for index, raw_path in enumerate(paths, start=1):
                path = Path(raw_path)
                record = self._record_map.get(raw_path, {})
                payload = self._parsed_cache.get(str(path))
                if payload is None:
                    if record.get("source") == "device" and isinstance(record.get("payload"), dict):
                        self._log_backend(f"token={token} curva {index}/{total}: usando cache dispositivo {raw_path}")
                        payload = dict(record["payload"])
                    else:
                        self._log_backend(f"token={token} curva {index}/{total}: parseando archivo {raw_path}")
                        payload = self._parse_file_plain(path)
                        payload["path"] = str(path)
                        payload["name"] = path.name
                    self._parsed_cache[str(path)] = payload
                else:
                    self._log_backend(f"token={token} curva {index}/{total}: usando cache local {raw_path}")
                payloads.append(payload)
                if index == 1:
                    self.after(0, lambda p=payload, i=index, t=total: self._finish_selection_info(token, p, i, t))
            self._payloads_by_token[token] = payloads
        except Exception as ex:
            self._log_backend(f"ERROR carga seleccion token={token}: {ex}")
            self.after(0, lambda: self._finish_selection_error(token, ex))
            return
        finally:
            if com_ready and pythoncom is not None:
                try:
                    pythoncom.CoUninitialize()
                except Exception:
                    pass
        self.after(0, lambda: self._finish_selection_ready(token))

    def _show_loading(self, names):
        self.info_tree.delete(*self.info_tree.get_children())
        if len(names) == 1:
            self.selection_var.set(f"{names[0]} - cargando grafico...")
        else:
            self.selection_var.set(f"{len(names)} archivos seleccionados - cargando grafico...")
        self.status_var.set("Cargando datos y preparando grafico...")
        self._current_payloads = []
        self._curve_visibility = {}
        self._rebuild_curve_controls([])
        self._clear_chart()
        self._clear_compare_table()
        self._set_text(self.compare_text, "")
        self.chart_placeholder.configure(text="Cargando grafico...")

    def _finish_selection_info(self, token, payload, index, total):
        if token != self._load_token:
            return
        self._fill_info([payload], loading_summary=(index, total))
        self.status_var.set("Datos cargados. Calculando grafico...")

    def _finish_selection_error(self, token, ex):
        if token != self._load_token:
            return
        self._clear_detail()
        self.selection_var.set("No se pudo leer la seleccion")
        self.status_var.set("Error al cargar archivos.")
        messagebox.showerror("Analisis termico", f"No se pudieron abrir los archivos.\n\n{ex}", parent=self)

    def _finish_selection_ready(self, token):
        if token != self._load_token:
            return
        payloads = self._payloads_by_token.pop(token, [])
        if not payloads:
            self._clear_detail()
            return
        self.selection_var.set(self._selection_label(payloads))
        self._current_payloads = list(payloads)
        self._sync_curve_visibility(payloads)
        self._rebuild_curve_controls(payloads)
        self._draw_chart(payloads)
        self._fill_info(payloads)
        self._apply_mode_tabs(payloads)
        self._fill_results_tabs(payloads)
        self.status_var.set(
            f"{len(self._records)} archivo(s) detectado(s) en {self.folder}. "
            f"{len(payloads)} curva(s) cargada(s)."
        )

    def _selection_label(self, payloads):
        names = [payload.get("name", "") for payload in payloads]
        if len(names) == 1:
            return names[0]
        preview = ", ".join(names[:2])
        if len(names) > 2:
            preview += f", +{len(names) - 2} mas"
        return preview

    def _clear_detail(self):
        self.info_tree.delete(*self.info_tree.get_children())
        self.selection_var.set("Selecciona uno o mas archivos para ver curvas y resultados.")
        self._current_payloads = []
        self._curve_visibility = {}
        self._rebuild_curve_controls([])
        self._clear_chart()
        self._clear_compare_table()
        self._set_text(self.compare_text, "")
        self.status_var.set(f"{len(self._records)} archivo(s) detectado(s) en {self.folder}.")

    def _fill_info(self, payloads, loading_summary=None):
        self.info_tree.delete(*self.info_tree.get_children())
        if not payloads:
            return
        first = payloads[0]
        mode_group = self._payload_mode_group(first)
        row_order = THERMAL_INFO_CARBON_V2 if mode_group == "Carbono" else THERMAL_INFO_MICRO_V2
        self.info_tree.insert("", "end", values=("Archivo", first.get("name", "")))
        source = str(first.get("source", "") or "")
        if source == "device":
            self.info_tree.insert("", "end", values=("Origen", "Dispositivo"))
        if len(payloads) > 1:
            self.info_tree.insert("", "end", values=("Curvas seleccionadas", str(len(payloads))))
            compare_text = ", ".join(item.get("name", "") for item in payloads[1:3])
            if len(payloads) > 3:
                compare_text += f", +{len(payloads) - 3} mas"
            self.info_tree.insert("", "end", values=("Comparando con", compare_text))
        if loading_summary is not None:
            self.info_tree.insert("", "end", values=("Carga", f"{loading_summary[0]} / {loading_summary[1]}"))
        for display in row_order:
            value = self._pick_info_value(first.get("info", {}), THERMAL_FIELD_ALIASES_V2.get(display, (display,)))
            if value:
                self.info_tree.insert("", "end", values=(display, value))

    def _apply_mode_tabs(self, payloads):
        if not payloads:
            return
        all_carbon = all(self._payload_mode_group(payload) == "Carbono" for payload in payloads)
        compare_id = str(self.compare_box)
        tabs = self.side_nb.tabs()
        if all_carbon:
            if compare_id in tabs:
                self.side_nb.hide(self.compare_box)
            try:
                self.side_nb.select(self.info_box)
            except Exception:
                pass
        else:
            try:
                self.side_nb.add(self.compare_box, text="Comparacion")
            except Exception:
                pass

    def _set_text(self, widget, text):
        widget.configure(state="normal")
        widget.delete("1.0", "end")
        if text:
            widget.insert("1.0", text)
        widget.configure(state="disabled")

    def _clear_compare_table(self):
        self.compare_tree.configure(columns=("metrica",))
        self.compare_tree.heading("metrica", text="Metrica")
        self.compare_tree.column("metrica", width=220, anchor="w")
        for item in self.compare_tree.get_children():
            self.compare_tree.delete(item)

    def _fill_comparison_table(self, payloads):
        self._clear_compare_table()
        if not payloads:
            return

        curve_cols = [f"curva_{i + 1}" for i in range(len(payloads))]
        self.compare_tree.configure(columns=("metrica", *curve_cols))
        self.compare_tree.heading("metrica", text="Metrica")
        self.compare_tree.column("metrica", width=180, anchor="w")

        metrics_per_curve = [self._result_metrics(payload.get("info", {})) for payload in payloads]
        for index, payload in enumerate(payloads):
            cid = curve_cols[index]
            title = Path(str(payload.get("name", "") or f"Curva {index + 1}")).stem
            self.compare_tree.heading(cid, text=title)
            self.compare_tree.column(cid, width=125, anchor="center")

        rows = [
            ("TL", lambda metric, payload: self._fmt_nullable(metric["tl"], " C")),
            ("TSE", lambda metric, payload: self._fmt_nullable(metric["tse"], " C")),
            ("TRE", lambda metric, payload: self._fmt_nullable(metric["tre"], " C")),
            ("REC", lambda metric, payload: self._fmt_nullable(metric["rec"], " C")),
            ("TF", lambda metric, payload: self._fmt_nullable(metric["tf"], " C")),
            ("Tiempo TL / tag1", lambda metric, payload: self._fmt_nullable(metric["tag1"], " s")),
            ("Tiempo TSE / tag2", lambda metric, payload: self._fmt_nullable(metric["tag2"], " s")),
            ("Tiempo TRE / tag3", lambda metric, payload: self._fmt_nullable(metric["tag3"], " s")),
            ("Tiempo TF / tag4", lambda metric, payload: self._fmt_nullable(metric["tag4"], " s")),
            ("TL - TSE", lambda metric, payload: self._fmt_nullable(metric["solid_interval"], " C")),
            ("Expansion gris", lambda metric, payload: self._fmt_pct_or_nd(metric["gray_expansion"])),
            ("Expansion nodular", lambda metric, payload: self._fmt_pct_or_nd(metric["nodular_expansion"])),
            ("Puntos", lambda metric, payload: str(len(payload.get("series", [])))),
        ]

        for label, formatter in rows:
            values = [label]
            for metric, payload in zip(metrics_per_curve, payloads):
                values.append(formatter(metric, payload))
            self.compare_tree.insert("", "end", values=values)

    def _refresh_stats_tab(self):
        if not hasattr(self, "stats_tree"):
            return
        for item in self.stats_tree.get_children():
            self.stats_tree.delete(item)
        carbon = self._thermal_stats_for_group("Carbono")
        micro = self._thermal_stats_for_group("Microestructura")

        rows = [
            ("Cantidad analisis", self._fmt_count(carbon["count"]), self._fmt_count(micro["count"])),
            ("Temperatura solido", self._fmt_stat(carbon, "ts"), self._fmt_stat(micro, "tse")),
            ("Promedio TL", self._fmt_stat(carbon, "tl"), self._fmt_stat(micro, "tl")),
            ("Promedio TF", self._fmt_stat(carbon, "tf"), self._fmt_stat(micro, "tf")),
            ("Tiempo TS/TSE", self._fmt_stat(carbon, "tag2", " s"), self._fmt_stat(micro, "tag2", " s")),
            ("Tiempo final", self._fmt_stat(carbon, "tag3", " s"), self._fmt_stat(micro, "tag4", " s")),
            ("Promedio CE", self._fmt_stat(carbon, "ce", ""), ""),
            ("Promedio C", self._fmt_stat(carbon, "c", "%"), ""),
            ("Promedio Si", self._fmt_stat(carbon, "si", "%"), ""),
            ("Promedio TRE", "", self._fmt_stat(micro, "tre")),
            ("Promedio REC", "", self._fmt_stat(micro, "rec")),
            ("Intervalo TL-TSE", "", self._fmt_stat(micro, "solid_interval")),
            ("Expansion gris", "", self._fmt_stat(micro, "gray_expansion", "%", scale=100.0)),
            ("Expansion nodular", "", self._fmt_stat(micro, "nodular_expansion", "%", scale=100.0)),
        ]
        for values in rows:
            self.stats_tree.insert("", "end", values=values)

        lines = []
        if carbon["values"].get("ts"):
            max_item = carbon["max_items"].get("ts", {})
            lines.append(
                "Carbono: TS promedio "
                f"{self._fmt_number(carbon['avg'].get('ts'))} C; maximo "
                f"{self._fmt_number(carbon['max'].get('ts'))} C en {max_item.get('name', '')}."
            )
        if carbon["values"].get("tag2"):
            max_time = carbon["max_items"].get("tag2", {})
            lines.append(
                "Carbono: tiempo TS promedio "
                f"{self._fmt_number(carbon['avg'].get('tag2'))} s; mas largo "
                f"{self._fmt_number(carbon['max'].get('tag2'))} s en {max_time.get('name', '')}."
            )
        if micro["values"].get("tse"):
            max_item = micro["max_items"].get("tse", {})
            lines.append(
                "Microestructura: TSE promedio "
                f"{self._fmt_number(micro['avg'].get('tse'))} C; maximo "
                f"{self._fmt_number(micro['max'].get('tse'))} C en {max_item.get('name', '')}."
            )
        if carbon["values"].get("ts") and micro["values"].get("tse"):
            delta = carbon["avg"].get("ts") - micro["avg"].get("tse")
            lines.append(f"Diferencia promedio Carbono TS vs Micro TSE: {delta:.2f} C.")
        self._set_text(self.stats_text, "\n".join(lines) if lines else "Sin datos estadisticos suficientes.")

    def _thermal_stats_for_group(self, group):
        stats = {
            "count": 0,
            "values": {},
            "avg": {},
            "min": {},
            "max": {},
            "max_items": {},
        }
        metric_aliases = {
            "tl": ("TL",),
            "ts": ("TS", "TSE"),
            "tse": ("TSE",),
            "tre": ("TRE",),
            "rec": ("REC",),
            "tf": ("TF",),
            "ce": ("CE %",),
            "c": ("C %", "Carbono %"),
            "si": ("Si %", "Silicio %"),
            "tag1": ("tag1", "tag1 / TL (s)"),
            "tag2": ("tag2", "tag2 / TSE (s)"),
            "tag3": ("tag3", "tag3 / TRE (s)"),
            "tag4": ("tag4", "tag4 / TF (s)"),
            "solid_interval": (),
            "gray_expansion": (),
            "nodular_expansion": (),
        }
        for item in self._device_records:
            if str(item.get("mode_group", "") or "") != group:
                continue
            payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
            info = payload.get("info", {}) if isinstance(payload.get("info"), dict) else {}
            metrics = self._result_metrics(info)
            stats["count"] += 1
            for key, aliases in metric_aliases.items():
                if key in ("solid_interval", "gray_expansion", "nodular_expansion"):
                    value = metrics.get(key)
                else:
                    value = self._parse_decimal(self._info_alias_value(info, *aliases))
                if value is None:
                    continue
                stats["values"].setdefault(key, []).append(value)
                if key not in stats["max"] or value > stats["max"][key]:
                    stats["max"][key] = value
                    stats["max_items"][key] = {
                        "name": item.get("name", ""),
                        "path": item.get("path", ""),
                        "date": info.get("Dt Inicio", "") or item.get("modified", ""),
                    }
                if key not in stats["min"] or value < stats["min"][key]:
                    stats["min"][key] = value
        for key, values in stats["values"].items():
            stats["avg"][key] = sum(values) / len(values)
        return stats

    def _fmt_count(self, value):
        return str(int(value or 0))

    def _fmt_number(self, value, decimals=2):
        if value is None:
            return "N/D"
        return f"{float(value):.{decimals}f}"

    def _fmt_stat(self, stats, key, suffix=" C", scale=1.0):
        values = stats["values"].get(key, [])
        if not values:
            return "N/D"
        avg = stats["avg"].get(key) * scale
        mn = stats["min"].get(key) * scale
        mx = stats["max"].get(key) * scale
        return f"prom {avg:.2f}{suffix} | min {mn:.2f} | max {mx:.2f}"

    def _fill_results_tabs(self, payloads):
        first = payloads[0] if payloads else None
        second = payloads[1] if len(payloads) > 1 else None
        if first and self._payload_mode_group(first) == "Carbono":
            self._clear_compare_table()
            self._set_text(self.compare_text, "")
            return
        self._fill_comparison_table(payloads)
        if first and second:
            self._set_text(self.compare_text, self._build_comparison_text(first, second, extra_count=max(0, len(payloads) - 2)))
        elif first:
            header = f"Archivo: {first.get('name', '')}\n\n"
            self._set_text(self.compare_text, header + self._build_results_text(first.get("info", {}), first.get("series", [])))
        else:
            self._set_text(self.compare_text, "Selecciona al menos una curva para ver el resultado.")

    def _clear_chart(self):
        if self._chart_widget is not None:
            try:
                self._chart_widget.destroy()
            except Exception:
                pass
        self._chart_widget = None
        self._chart_canvas = None
        if self.chart_placeholder.winfo_exists():
            self.chart_placeholder.pack(anchor="center", expand=True)

    def _sync_curve_visibility(self, payloads):
        active_paths = {str(item.get("path", "") or "") for item in payloads}
        self._curve_visibility = {
            path: visible
            for path, visible in self._curve_visibility.items()
            if path in active_paths
        }
        for payload in payloads:
            path = str(payload.get("path", "") or "")
            if path and path not in self._curve_visibility:
                self._curve_visibility[path] = True

    def _rebuild_curve_controls(self, payloads):
        for child in self.curves_inner.winfo_children():
            child.destroy()
        self._curve_var_map = {}
        if not payloads:
            ttk.Label(self.curves_inner, text="Sin curvas seleccionadas.").pack(anchor="w")
            return
        for index, payload in enumerate(payloads):
            path = str(payload.get("path", "") or "")
            name = str(payload.get("name", "") or f"Curva {index + 1}")
            color = THERMAL_COLORS[index % len(THERMAL_COLORS)]
            row = ttk.Frame(self.curves_inner)
            row.pack(fill="x", anchor="w", pady=1)
            swatch = tk.Label(row, text="  ", bg=color, relief="solid", bd=1)
            swatch.pack(side="left", padx=(0, 6))
            var = tk.BooleanVar(value=self._curve_visibility.get(path, True))
            chk = ttk.Checkbutton(
                row,
                text=name,
                variable=var,
                command=lambda p=path, v=var: self._toggle_curve_visibility(p, v.get()),
            )
            chk.pack(side="left", anchor="w")
            self._curve_var_map[path] = var

    def _toggle_curve_visibility(self, path, visible):
        self._curve_visibility[path] = bool(visible)
        if self._current_payloads:
            self._draw_chart(self._current_payloads)

    def _chart_series_arrays(self, series):
        total = len(series or [])
        if total <= THERMAL_CHART_MAX_POINTS_PER_CURVE:
            sampled = series or []
        else:
            step = max(1, total // THERMAL_CHART_MAX_POINTS_PER_CURVE)
            sampled = list(series[::step])
            last = series[-1]
            if sampled and sampled[-1] is not last:
                sampled.append(last)
        periodos = []
        temperaturas = []
        derivadas = []
        for row in sampled:
            try:
                periodos.append(row["periodo"])
                temperaturas.append(row["temperatura"])
                derivadas.append(row["derivada"])
            except Exception:
                continue
        return periodos, temperaturas, derivadas

    def _draw_chart(self, payloads):
        self._clear_chart()
        if not payloads:
            self.chart_placeholder.configure(text="No hay curvas para graficar.")
            return
        self.chart_placeholder.pack_forget()
        try:
            import matplotlib
            matplotlib.use("TkAgg")
            from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg
            from matplotlib.figure import Figure
        except Exception as ex:
            self.chart_placeholder.configure(text=f"No se pudo cargar matplotlib.\n{ex}")
            self.chart_placeholder.pack(anchor="center", expand=True)
            return

        fig = Figure(
            figsize=(THERMAL_CHART_WIDTH / 100.0, THERMAL_CHART_HEIGHT / 100.0),
            dpi=100,
            facecolor=BG_ENTRY,
        )
        ax_temp = fig.add_subplot(111)
        ax_temp.set_facecolor(BG_ENTRY)
        ax_der = ax_temp.twinx()

        handles = []
        labels = []
        plotted = 0
        temp_y_max = None
        for index, payload in enumerate(payloads):
            path = str(payload.get("path", "") or "")
            if not self._curve_visibility.get(path, True):
                continue
            series = payload.get("series", []) or []
            if not series:
                continue
            periodos, temperaturas, derivadas = self._chart_series_arrays(series)
            if not periodos:
                continue
            plotted += 1
            color = THERMAL_COLORS[index % len(THERMAL_COLORS)]
            deriv_color = _darken_hex(color)
            short = Path(str(payload.get("name", ""))).stem
            line_temp, = ax_temp.plot(periodos, temperaturas, color=color, linewidth=2.0, label=f"{short} T")
            line_der, = ax_der.plot(periodos, derivadas, color=deriv_color, linewidth=0.9, linestyle="-", alpha=0.95, label=f"{short} D")
            if temperaturas:
                current_max = max(temperaturas)
                temp_y_max = current_max if temp_y_max is None else max(temp_y_max, current_max)
            info = payload.get("info", {}) or {}
            tag_specs = (
                ("tag1", "TL"),
                ("tag2", "TSE"),
                ("tag3", "TRE"),
                ("tag4", "TF"),
            )
            for tag_key, tag_label in tag_specs:
                tag_value = self._parse_decimal(self._info_alias_value(info, tag_key, f"{tag_key} / {tag_label} (s)"))
                if tag_value is None:
                    continue
                ax_temp.axvline(
                    tag_value,
                    color=color,
                    linewidth=1.35,
                    linestyle=(0, (3, 3)),
                    alpha=0.98,
                    zorder=6,
                )
            handles.extend((line_temp, line_der))
            labels.extend((f"{short} T", f"{short} D"))

        if plotted == 0:
            self.chart_placeholder.configure(text="Todas las curvas estan ocultas. Activa alguna casilla para ver el grafico.")
            self.chart_placeholder.pack(anchor="center", expand=True)
            return

        ax_temp.set_xlabel("Periodo", color=FG)
        ax_temp.set_ylabel("Temperatura", color=FG)
        ax_der.set_ylabel("Derivada", color=FG)
        ax_temp.tick_params(axis="x", colors=FG)
        ax_temp.tick_params(axis="y", colors=FG)
        ax_der.tick_params(axis="y", colors=FG)
        ax_temp.grid(True, color="#555555", alpha=0.25, linewidth=0.7)
        for spine in ax_temp.spines.values():
            spine.set_color(FG)
        for spine in ax_der.spines.values():
            spine.set_color(FG)
        ax_temp.set_title(self._selection_label(payloads), color=FG)

        if temp_y_max is None:
            temp_y_max = ax_temp.get_ylim()[1]
        tag_label_y = temp_y_max
        for index, payload in enumerate(payloads):
            path = str(payload.get("path", "") or "")
            if not self._curve_visibility.get(path, True):
                continue
            color = THERMAL_COLORS[index % len(THERMAL_COLORS)]
            info = payload.get("info", {}) or {}
            for tag_key, tag_label in (("tag1", "TL"), ("tag2", "TSE"), ("tag3", "TRE"), ("tag4", "TF")):
                tag_value = self._parse_decimal(self._info_alias_value(info, tag_key, f"{tag_key} / {tag_label} (s)"))
                if tag_value is None:
                    continue
                ax_temp.text(
                    tag_value,
                    tag_label_y,
                    tag_label,
                    color=color,
                    fontsize=7,
                    rotation=90,
                    va="bottom",
                    ha="center",
                    zorder=7,
                    clip_on=False,
                )
        if handles:
            legend = ax_temp.legend(handles, labels, loc="upper right", frameon=False, fontsize=8)
            for text in legend.get_texts():
                text.set_color(FG)
        fig.tight_layout()

        self._chart_canvas = FigureCanvasTkAgg(fig, master=self.chart_host)
        self._chart_canvas.draw()
        self._chart_widget = self._chart_canvas.get_tk_widget()
        self._chart_widget.configure(width=THERMAL_CHART_WIDTH, height=THERMAL_CHART_HEIGHT)
        self._chart_widget.pack(fill="both", expand=True)

    def _parse_file_plain(self, path):
        if path.suffix.lower() == ".csv":
            info, series = self._parse_csv(path)
        else:
            info, series = self._parse_excel(path)
        return {"info": info, "series": series}

    def _parse_excel(self, path):
        try:
            import win32com.client  # type: ignore
        except Exception as ex:
            raise RuntimeError(f"No esta disponible win32com para leer Excel: {ex}") from ex

        excel = None
        wb = None
        try:
            excel = win32com.client.DispatchEx("Excel.Application")
            excel.Visible = False
            excel.DisplayAlerts = False
            wb = excel.Workbooks.Open(str(path), ReadOnly=True)
            ws = wb.Worksheets(1)
            used = ws.UsedRange
            rows = int(used.Rows.Count)
            cols = int(used.Columns.Count)

            raw_headers = [str(ws.Cells(1, c).Text).strip() for c in range(1, cols + 1)]
            raw_values = [str(ws.Cells(2, c).Text).strip() for c in range(1, cols + 1)]
            raw_info = {raw_headers[i]: raw_values[i] for i in range(min(len(raw_headers), len(raw_values))) if raw_headers[i]}
            info = self._canonicalize_info(raw_info)

            series = []
            for r in range(5, rows + 1):
                periodo = str(ws.Cells(r, 1).Text).strip()
                temperatura = str(ws.Cells(r, 2).Text).strip()
                derivada = str(ws.Cells(r, 3).Text).strip()
                if not periodo and not temperatura and not derivada:
                    continue
                period_num = self._parse_decimal(periodo)
                temp_num = self._parse_decimal(temperatura)
                der_num = self._parse_decimal(derivada)
                if period_num is None or temp_num is None or der_num is None:
                    continue
                series.append({"periodo": period_num, "temperatura": temp_num, "derivada": der_num})
            return info, series
        finally:
            try:
                if wb is not None:
                    wb.Close(False)
            except Exception:
                pass
            try:
                if excel is not None:
                    excel.Quit()
            except Exception:
                pass

    def _parse_csv(self, path):
        with path.open("r", encoding="utf-8-sig", newline="") as fh:
            sample = fh.read(2048)
            fh.seek(0)
            try:
                dialect = csv.Sniffer().sniff(sample, delimiters=";,")
            except Exception:
                dialect = csv.excel
                dialect.delimiter = ","
            reader = csv.reader(fh, dialect)
            rows = [row for row in reader]
        if len(rows) < 5:
            raise ValueError("El CSV no tiene el formato esperado.")

        raw_headers = [str(cell).strip() for cell in rows[0]]
        raw_values = [str(cell).strip() for cell in rows[1]] if len(rows) > 1 else []
        raw_info = {raw_headers[i]: raw_values[i] for i in range(min(len(raw_headers), len(raw_values))) if raw_headers[i]}
        info = self._canonicalize_info(raw_info)

        series = []
        for row in rows[4:]:
            if len(row) < 3:
                continue
            period_num = self._parse_decimal(row[0])
            temp_num = self._parse_decimal(row[1])
            der_num = self._parse_decimal(row[2])
            if period_num is None or temp_num is None or der_num is None:
                continue
            series.append({"periodo": period_num, "temperatura": temp_num, "derivada": der_num})
        return info, series

    def _canonicalize_info(self, raw_info):
        out = {}
        for display, aliases in THERMAL_FIELD_ALIASES_V2.items():
            for alias in aliases:
                value = str(raw_info.get(alias, "") or "").strip()
                if value:
                    out[display] = value
                    break
        return out

    def _info_alias_value(self, info, *aliases):
        for alias in aliases:
            value = str((info or {}).get(alias, "") or "").strip()
            if value:
                return value
        return ""

    def _pick_info_value(self, info, aliases):
        for alias in aliases:
            value = str(info.get(alias, "") or "").strip()
            if value:
                return value
        return ""

    def _attach_selected_to_history(self):
        paths = [str(path or "").strip() for path in self._selected_paths if str(path or "").strip()]
        if not paths:
            messagebox.showwarning("Analisis termico", "Selecciona una o mas curvas para adjuntar.", parent=self)
            return
        payloads = self._payloads_for_paths(paths)
        if not payloads:
            messagebox.showwarning("Analisis termico", "No se pudieron preparar las curvas seleccionadas.", parent=self)
            return

        picked = self._prompt_history_attach_data(payloads)
        if not picked:
            return
        colada = str(picked.get("colada") or "").strip()
        material_base = str(picked.get("material_base") or "").strip()
        observations = picked.get("observations", {}) if isinstance(picked.get("observations", {}), dict) else {}
        if not colada:
            return

        attached = 0
        try:
            for payload in payloads:
                path = str(payload.get("path", "") or "").strip()
                observation = str(observations.get(path, "") or "").strip()
                attach_thermal_analysis(colada, self._build_history_analysis(payload, colada, material_base, observation))
                if path:
                    self._linked_history_by_path[path] = {"colada": colada, "material_base": material_base}
                attached += 1
        except Exception as ex:
            messagebox.showerror("Analisis termico", f"No se pudo adjuntar en Historicos.\n\n{ex}", parent=self)
            return

        self.status_var.set(f"{attached} curva(s) adjuntada(s) a Historicos: colada {colada}.")
        try:
            self.event_generate("<<HistoryUpdated>>", when="tail")
        except Exception:
            pass

    def _payloads_for_paths(self, paths):
        current_by_path = {
            str(payload.get("path", "") or "").strip(): payload
            for payload in getattr(self, "_current_payloads", [])
            if isinstance(payload, dict)
        }
        payloads = []
        for raw_path in paths:
            payload = current_by_path.get(raw_path) or self._parsed_cache.get(raw_path)
            if payload is None:
                record = self._record_map.get(raw_path, {})
                if record.get("source") == "device" and isinstance(record.get("payload"), dict):
                    payload = dict(record["payload"])
                else:
                    payload = self._parse_file_plain(Path(raw_path))
                    payload["path"] = raw_path
                    payload["name"] = Path(raw_path).name
                self._parsed_cache[raw_path] = payload
            payloads.append(payload)
        return payloads

    def _prompt_history_attach_data(self, payloads):
        history = load_history()
        coladas = [
            str((session or {}).get("colada", "") or "").strip()
            for session in history
            if str((session or {}).get("colada", "") or "").strip()
        ]
        coladas = list(dict.fromkeys(reversed(coladas)))
        suggested_colada = ""
        try:
            target = getattr(self, "_ajuste_target", None)
            if target is not None:
                suggested_colada = str(target.colada.get() or "").strip()
        except Exception:
            suggested_colada = ""
        if not suggested_colada and coladas:
            suggested_colada = coladas[0]

        first_info = (payloads[0].get("info", {}) if payloads and isinstance(payloads[0], dict) else {}) or {}
        suggested_base = str(first_info.get("Material", "") or "").strip()
        picked = None

        win = tk.Toplevel(self)
        win.title("Adjuntar a Historicos")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(True, True)
        win.minsize(680, 420)

        footer = ttk.Frame(win, padding=(12, 8, 12, 12))
        footer.pack(side="bottom", fill="x")
        ttk.Separator(win, orient="horizontal").pack(side="bottom", fill="x")

        content = ttk.Frame(win, padding=(12, 12, 12, 8))
        content.pack(side="top", fill="both", expand=True)
        content.columnconfigure(1, weight=1)
        content.rowconfigure(3, weight=1)

        ttk.Label(content, text=f"Adjuntar {len(payloads)} curva(s) termica(s)").grid(row=0, column=0, columnspan=2, sticky="w")
        ttk.Label(content, text="Colada").grid(row=1, column=0, sticky="w", pady=(10, 0))
        var_colada = tk.StringVar(value=suggested_colada)
        cb_colada = ttk.Combobox(content, textvariable=var_colada, values=coladas, width=32)
        cb_colada.grid(row=1, column=1, sticky="ew", padx=(8, 0), pady=(10, 0))
        ttk.Label(content, text="Material base").grid(row=2, column=0, sticky="w", pady=(8, 0))
        var_base = tk.StringVar(value=suggested_base)
        ttk.Entry(content, textvariable=var_base, width=32).grid(row=2, column=1, sticky="ew", padx=(8, 0), pady=(8, 0))

        obs_box = ttk.LabelFrame(content, text="Observacion por curva", padding=6)
        obs_box.grid(row=3, column=0, columnspan=2, sticky="nsew", pady=(10, 0))
        obs_frame = ScrollFrame(obs_box)
        obs_frame.pack(fill="both", expand=True)
        obs_frame.canvas.configure(height=220)
        obs_vars = {}
        for row_idx, payload in enumerate(payloads):
            path = str(payload.get("path", "") or "").strip()
            name = str(payload.get("name", "") or Path(path).name or f"Curva {row_idx + 1}")
            ttk.Label(obs_frame.inner, text=name, wraplength=260).grid(row=row_idx, column=0, sticky="w", padx=(0, 8), pady=2)
            var_obs = tk.StringVar()
            ttk.Entry(obs_frame.inner, textvariable=var_obs, width=48).grid(row=row_idx, column=1, sticky="ew", pady=2)
            obs_vars[path] = var_obs
        obs_frame.inner.columnconfigure(1, weight=1)

        def accept():
            nonlocal picked
            picked = {
                "colada": var_colada.get().strip(),
                "material_base": var_base.get().strip(),
                "observations": {path: var.get().strip() for path, var in obs_vars.items()},
            }
            win.destroy()

        ttk.Button(footer, text="Cancelar", command=win.destroy).pack(side="right")
        ttk.Button(footer, text="Guardar / Adjuntar", command=accept).pack(side="right", padx=(0, 6))

        win.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_width()) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"680x460+{x}+{y}")
        win.bind("<Return>", lambda _event: accept())
        win.bind("<Escape>", lambda _event: win.destroy())
        win.wait_window()
        if not picked or not picked.get("colada"):
            return None
        return picked

    def _build_history_analysis(self, payload, colada, material_base, observacion=""):
        info = dict(payload.get("info", {}) or {})
        series = list(payload.get("series", []) or [])
        return {
            "attached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "colada": str(colada or "").strip(),
            "material_base": str(material_base or "").strip(),
            "observacion": str(observacion or "").strip(),
            "source_file": str(payload.get("path", "") or "").strip(),
            "source_name": str(payload.get("name", "") or "").strip(),
            "info": info,
            "series": series,
            "point_count": len(series),
            "result_metrics": self._result_metrics(info),
            "result_text": self._build_results_text(info, series),
        }

    def _build_results_text(self, info, series):
        metrics = self._result_metrics(info)
        lines = [
            "Resumen calculado",
            "",
            "Temperaturas",
            f"- TL: {self._fmt_or_nd(metrics['tl'], ' C')}",
            f"- TSE: {self._fmt_or_nd(metrics['tse'], ' C')}",
            f"- TRE: {self._fmt_or_nd(metrics['tre'], ' C')}",
            f"- REC: {self._fmt_or_nd(metrics['rec'], ' C')}",
            f"- TF: {self._fmt_or_nd(metrics['tf'], ' C')}",
            "",
            "Tiempos (segundos)",
            f"- Tiempo TL / tag1: {self._fmt_or_nd(metrics['tag1'], ' s')}",
            f"- Tiempo TSE / tag2: {self._fmt_or_nd(metrics['tag2'], ' s')}",
            f"- Tiempo TRE / tag3: {self._fmt_or_nd(metrics['tag3'], ' s')}",
            f"- Tiempo TF / tag4: {self._fmt_or_nd(metrics['tag4'], ' s')}",
            "",
            "Indicadores calculados",
            f"Intervalo de solidificacion (TL - TSE): {self._fmt_or_nd(metrics['solid_interval'], ' C')}",
            f"Puntos de curva: {len(series)}",
            f"Expansion gris por tiempo ((tag4-tag2)/(tag4-tag1)): {self._fmt_pct_or_nd(metrics['gray_expansion'])}",
            f"Expansion nodular por tiempo ((tag4-tag3)/(tag4-tag1)): {self._fmt_pct_or_nd(metrics['nodular_expansion'])}",
            "",
            THERMAL_RESULTS_NOTE,
            "",
            "Hierro fundido gris",
            f"- TSE recomendado en horno y cuchara: > 1140 C. Estado: {self._range_status(metrics['tse'], 1140.0, None)}",
            f"- REC recomendado en cuchara: 4 a 7 C. Estado: {self._range_status(metrics['rec'], 4.0, 7.0)}",
            f"- Expansion grafitica final recomendada: > 60%. Estado: {self._ratio_status(metrics['gray_expansion'], 0.60)}",
            "- El intervalo de solidificacion grande (TL - TSE) empeora la alimentacion y puede favorecer rechupes.",
            "",
            "Hierro fundido nodular",
            f"- TSE recomendado en horno y cuchara: > 1140 C. Estado: {self._range_status(metrics['tse'], 1140.0, None)}",
            f"- REC recomendado en cuchara: 1 a 4 C. Estado: {self._range_status(metrics['rec'], 1.0, 4.0)}",
            f"- Expansion grafitica final recomendada: > 70%. Estado: {self._ratio_status(metrics['nodular_expansion'], 0.70)}",
            "- En nodular, la expansion final esperada debe ser mayor que en gris.",
        ]
        return "\n".join(lines).strip()

    def _build_comparison_text(self, first, second, extra_count=0):
        m1 = self._result_metrics(first.get("info", {}))
        m2 = self._result_metrics(second.get("info", {}))
        lines = [
            f"A: {first.get('name', '')}",
            f"B: {second.get('name', '')}",
        ]
        if extra_count > 0:
            lines.append(f"Hay {extra_count} curva(s) extra en el grafico; la comparacion usa solo A y B.")
        lines.extend([
            "",
            self._compare_metric_line("TL", m1["tl"], m2["tl"], " C"),
            self._compare_metric_line("TSE", m1["tse"], m2["tse"], " C"),
            self._compare_metric_line("TRE", m1["tre"], m2["tre"], " C"),
            self._compare_metric_line("REC", m1["rec"], m2["rec"], " C"),
            self._compare_metric_line("TF", m1["tf"], m2["tf"], " C"),
            self._compare_metric_line("TL - TSE", m1["solid_interval"], m2["solid_interval"], " C"),
            self._compare_metric_line("Expansion gris", self._to_pct(m1["gray_expansion"]), self._to_pct(m2["gray_expansion"]), "%"),
            self._compare_metric_line("Expansion nodular", self._to_pct(m1["nodular_expansion"]), self._to_pct(m2["nodular_expansion"]), "%"),
            self._compare_metric_line("Puntos", float(len(first.get("series", []))), float(len(second.get("series", []))), ""),
            "",
            f"Estado gris A: TSE {self._range_status(m1['tse'], 1140.0, None)} | REC {self._range_status(m1['rec'], 4.0, 7.0)} | Expansion {self._ratio_status(m1['gray_expansion'], 0.60)}",
            f"Estado gris B: TSE {self._range_status(m2['tse'], 1140.0, None)} | REC {self._range_status(m2['rec'], 4.0, 7.0)} | Expansion {self._ratio_status(m2['gray_expansion'], 0.60)}",
            f"Estado nodular A: TSE {self._range_status(m1['tse'], 1140.0, None)} | REC {self._range_status(m1['rec'], 1.0, 4.0)} | Expansion {self._ratio_status(m1['nodular_expansion'], 0.70)}",
            f"Estado nodular B: TSE {self._range_status(m2['tse'], 1140.0, None)} | REC {self._range_status(m2['rec'], 1.0, 4.0)} | Expansion {self._ratio_status(m2['nodular_expansion'], 0.70)}",
        ])
        return "\n".join(lines).strip()

    def _compare_metric_line(self, label, a, b, suffix):
        if a is None and b is None:
            return f"{label}: N/D"
        if a is None or b is None:
            return f"{label}: A={self._fmt_nullable(a, suffix)} | B={self._fmt_nullable(b, suffix)} | Delta=N/D"
        delta = b - a
        return f"{label}: A={self._fmt_nullable(a, suffix)} | B={self._fmt_nullable(b, suffix)} | Delta={delta:.2f}{suffix}"

    def _result_metrics(self, info):
        tl = self._parse_decimal(self._info_alias_value(info, "TL"))
        tse = self._parse_decimal(self._info_alias_value(info, "TSE"))
        tre = self._parse_decimal(self._info_alias_value(info, "TRE"))
        rec = self._parse_decimal(self._info_alias_value(info, "REC"))
        tf = self._parse_decimal(self._info_alias_value(info, "TF"))
        tag1 = self._parse_decimal(self._info_alias_value(info, "tag1", "tag1 / TL (s)"))
        tag2 = self._parse_decimal(self._info_alias_value(info, "tag2", "tag2 / TSE (s)"))
        tag3 = self._parse_decimal(self._info_alias_value(info, "tag3", "tag3 / TRE (s)"))
        tag4 = self._parse_decimal(self._info_alias_value(info, "tag4", "tag4 / TF (s)"))
        if rec is None and tre is not None and tse is not None:
            rec = tre - tse
        solid_interval = (tl - tse) if tl is not None and tse is not None else None
        gray_expansion = None
        nodular_expansion = None
        if tag1 is not None and tag2 is not None and tag4 is not None and tag4 != tag1:
            gray_expansion = (tag4 - tag2) / (tag4 - tag1)
        if tag1 is not None and tag3 is not None and tag4 is not None and tag4 != tag1:
            nodular_expansion = (tag4 - tag3) / (tag4 - tag1)
        return {
            "tl": tl,
            "tse": tse,
            "tre": tre,
            "rec": rec,
            "tf": tf,
            "tag1": tag1,
            "tag2": tag2,
            "tag3": tag3,
            "tag4": tag4,
            "solid_interval": solid_interval,
            "gray_expansion": gray_expansion,
            "nodular_expansion": nodular_expansion,
        }

    def _fmt_or_nd(self, value, suffix=""):
        if value is None:
            return "N/D"
        return f"{value:.2f}{suffix}"

    def _fmt_pct_or_nd(self, value):
        if value is None:
            return "N/D"
        return f"{value * 100.0:.2f}%"

    def _fmt_nullable(self, value, suffix=""):
        if value is None:
            return "N/D"
        return f"{value:.2f}{suffix}"

    def _to_pct(self, value):
        if value is None:
            return None
        return value * 100.0

    def _range_status(self, value, minimum=None, maximum=None):
        if value is None:
            return "N/D"
        if minimum is not None and value < minimum:
            return f"Bajo ({value:.2f})"
        if maximum is not None and value > maximum:
            return f"Alto ({value:.2f})"
        return f"OK ({value:.2f})"

    def _ratio_status(self, value, minimum):
        if value is None:
            return "N/D"
        pct = value * 100.0
        return f"OK ({pct:.2f}%)" if value >= minimum else f"Bajo ({pct:.2f}%)"

    def _parse_decimal(self, value):
        raw = str(value or "").strip()
        if not raw:
            return None
        raw = raw.replace(" ", "")
        if "," in raw and "." in raw:
            raw = raw.replace(".", "").replace(",", ".")
        else:
            raw = raw.replace(",", ".")
        try:
            return float(raw)
        except Exception:
            return None

    def _open_folder(self):
        try:
            os.startfile(str(self.folder))
        except Exception:
            try:
                subprocess.Popen(["explorer", str(self.folder)])
            except Exception as ex:
                messagebox.showerror("Analisis termico", f"No se pudo abrir la carpeta.\n\n{ex}", parent=self)

    def _send_carbon_to_ajuste(self):
        if self._ajuste_target is None:
            messagebox.showwarning("Analisis termico", "No se encontró la pestaña Ajuste para recibir datos.", parent=self)
            return
        if len(self._current_payloads) != 1:
            messagebox.showwarning("Analisis termico", "Selecciona un solo análisis de Carbono para cargar C/Si en Ajuste.", parent=self)
            return
        payload = self._current_payloads[0]
        info = payload.get("info", {}) if isinstance(payload.get("info"), dict) else {}
        mode = str(info.get("Modo", "") or "").upper()
        if "CARB" not in mode:
            messagebox.showwarning("Analisis termico", "La carga automática a Ajuste sólo aplica a análisis del modo Carbono.", parent=self)
            return
        carbon = self._parse_decimal(self._info_alias_value(info, "C %"))
        silicon = self._parse_decimal(self._info_alias_value(info, "Si %"))
        if carbon is None or silicon is None:
            messagebox.showwarning("Analisis termico", "Este análisis no trae Carbono y Silicio listos para cargar.", parent=self)
            return
        source_name = str(payload.get("name", "") or info.get("ID", "") or "análisis Carbono").strip()
        try:
            self._ajuste_target.load_carbon_silicon(carbon, silicon, source_label=source_name)
        except Exception as ex:
            messagebox.showerror("Analisis termico", f"No se pudo cargar C/Si en Ajuste.\n\n{ex}", parent=self)
            return
        top = self.winfo_toplevel()
        try:
            top.nb.select(top.tab_ajuste)
        except Exception:
            pass
        self.status_var.set(f"Datos de Carbono cargados en Ajuste: C={carbon:.2f} / Si={silicon:.2f}")

    def _send_carbon_to_ajuste_v2(self):
        if self._ajuste_target is None:
            messagebox.showwarning("Analisis termico", "No se encontro la pestana Ajuste para recibir datos.", parent=self)
            return
        if len(self._current_payloads) != 1:
            messagebox.showwarning("Analisis termico", "Selecciona un solo analisis de Carbono para cargar C/Si en Ajuste.", parent=self)
            return
        payload = self._current_payloads[0]
        info = payload.get("info", {}) if isinstance(payload.get("info"), dict) else {}
        mode = str(info.get("Modo", "") or "").upper()
        if "CARB" not in mode:
            messagebox.showwarning("Analisis termico", "La carga automatica a Ajuste solo aplica a analisis del modo Carbono.", parent=self)
            return
        carbon = self._parse_decimal(self._info_alias_value(info, "C %", "Carbono %"))
        silicon = self._parse_decimal(self._info_alias_value(info, "Si %", "Silicio %"))
        if carbon is None or silicon is None:
            refreshed = self._refresh_selected_device_payload_v2(payload)
            if refreshed is not None:
                payload = refreshed
                self._current_payloads[0] = payload
                info = payload.get("info", {}) if isinstance(payload.get("info"), dict) else {}
                carbon = self._parse_decimal(self._info_alias_value(info, "C %", "Carbono %"))
                silicon = self._parse_decimal(self._info_alias_value(info, "Si %", "Silicio %"))
                self._fill_info(self._current_payloads)
        if carbon is None or silicon is None:
            messagebox.showwarning("Analisis termico", "Este analisis no trae Carbono y Silicio listos para cargar.", parent=self)
            return
        source_name = str(payload.get("name", "") or info.get("ID", "") or "analisis Carbono").strip()
        try:
            self._ajuste_target.load_carbon_silicon(carbon, silicon, source_label=source_name)
        except Exception as ex:
            messagebox.showerror("Analisis termico", f"No se pudo cargar C/Si en Ajuste.\n\n{ex}", parent=self)
            return
        top = self.winfo_toplevel()
        try:
            top.nb.select(top.tab_ajuste)
        except Exception:
            pass
        self.status_var.set(f"Datos de Carbono cargados en Ajuste: C={carbon:.2f} / Si={silicon:.2f}")

    def _refresh_selected_device_payload_v2(self, payload):
        path = str(payload.get("path", "") or "").strip()
        source = str(payload.get("source", "") or "").strip()
        if source != "device" or not path.startswith("device://"):
            return None
        try:
            rest = path[len("device://"):]
            parts = rest.split("/", 2)
            ip = parts[0]
            info = payload.get("info", {}) if isinstance(payload.get("info"), dict) else {}
            row_id = str(info.get("ID", "") or "").strip()
            if not row_id:
                legacy = str(payload.get("legacy_path", "") or "").strip()
                if legacy.startswith("device://"):
                    legacy_parts = legacy[len("device://"):].split("/", 2)
                    if len(legacy_parts) >= 2:
                        row_id = legacy_parts[1]
            if not ip or not row_id:
                return None
        except Exception:
            return None
        self._log_backend(f"Refrescando payload puntual desde dispositivo: {path}")
        try:
            detail_json = self._http_get_json(ip, f"/getdata.cgi?btrqh={urllib.parse.quote(row_id)}")
            detail_rows = self._extract_json_rows(detail_json)
            if not detail_rows:
                return None
            detail = detail_rows[0]
            refreshed = self._build_device_payload(ip, {"id": row_id}, detail)
            refreshed["path"] = path
            refreshed["name"] = str(payload.get("name", "") or refreshed.get("name", "")).strip()
            refreshed["source"] = "device"
            self._parsed_cache[path] = refreshed
            for idx, item in enumerate(self._device_records):
                if str(item.get("path", "") or "").strip() != path:
                    continue
                updated = dict(item)
                updated["payload"] = refreshed
                updated["mode_group"] = self._device_mode_group(refreshed.get("info", {}).get("Modo", ""))
                self._device_records[idx] = updated
                break
            save_thermal_device_records(self._device_records)
            return refreshed
        except Exception as ex:
            self._log_backend(f"Refresh puntual FALLO {path}: {ex}")
            return None


def tk_time_string(timestamp):
    try:
        import datetime as _dt
        return _dt.datetime.fromtimestamp(timestamp).strftime("%d/%m/%Y %H:%M")
    except Exception:
        return ""
