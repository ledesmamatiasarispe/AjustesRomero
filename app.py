# app.py
import os
import sys
import json
import subprocess
import threading
import tkinter as tk
import urllib.error
import urllib.request
from datetime import datetime
from tkinter import ttk, messagebox, colorchooser

from tab_catalogo import TabCatalogo
from tab_ajuste import TabAjuste
from tab_historicos import TabHistoricos
from tab_informes import TabInformes
from tab_calidad import TabCalidad
from tab_analisis_termico import TabAnalisisTermico
from tab_pie_horno import TabPieHorno

from storage import load_alloys, save_alloys
from config import THEME, BG, FG, BG_ENTRY, ACCENT
from host_api import HOST_API_PORT, HOST_API_PUBLIC_PORT, HostAPIServer, get_host_api_port
from pie_horno_config import PUBLIC_TUNNEL_SUBDOMAIN, PUBLIC_TUNNEL_URL

APP_TITLE = "Ajuste de Composición"
STATE_FILENAME = "ajuste_comp_ui.json"
TUNNEL_WATCHDOG_INTERVAL_MS = 10000
TUNNEL_WATCHDOG_START_DELAY_MS = 12000
TUNNEL_HEALTH_TIMEOUT_SECONDS = 8
TUNNEL_RESTART_AFTER_FAILURES = 1
TUNNEL_ALERT_AFTER_RESTARTS = 3
DEV_RELOAD_POLL_MS = 800
INPUT_COLOR_PRESETS = {
    "Celeste base": ACCENT,
    "Azul profundo": "#285c9b",
    "Turquesa oscuro": "#217a8a",
    "Verde petroleo": "#2d6f73",
    "Celeste suave": "#9ec5f8",
    "Arena clara": "#d9c7a3",
}
DEFAULT_INPUT_COLOR = "Celeste base"
CUSTOM_INPUT_COLOR = "Personalizado actual"
BG_COLOR_PRESETS = {
    "Oscuro clasico": BG,
    "Gris grafito": "#25282d",
    "Azul noche": "#1d2733",
    "Verde pizarra": "#22312e",
    "Bordo": "#4b1f24",
}
DEFAULT_BG_COLOR = "Oscuro clasico"
CUSTOM_BG_COLOR = "Personalizado actual"
HIGHLIGHT_INPUT = "#fff2a8"
HIGHLIGHT_COLOR_PRESETS = {
    "Amarillo suave": HIGHLIGHT_INPUT,
    "Verde suave": "#cfe8b4",
    "Naranja suave": "#ffd3a6",
    "Rosa suave": "#f6c1cf",
    "Celeste suave": "#c7e6ff",
}
DEFAULT_HIGHLIGHT_COLOR = "Amarillo suave"
CUSTOM_HIGHLIGHT_COLOR = "Personalizado actual"
PRINT_GROUP_COLOR_PRESETS = {
    "Azul": "#1f4ea3",
    "Rojo": "#b03a2e",
    "Verde": "#2e8b57",
    "Negro": "#111111",
    "Violeta": "#6c4ba8",
    "Marron": "#7a4b2f",
}
DEFAULT_PRINT_GROUP_COLORS = ["Azul", "Rojo", "Verde"]
CUSTOM_PRINT_GROUP_COLOR = "Personalizado actual"
INPUT_FG_DARK = "#101820"
INPUT_FG_LIGHT = "#f5f7fa"


def _state_path():
    return os.path.join(os.path.expanduser("~"), STATE_FILENAME)


def _norm_hex(value):
    return str(value or "").strip().lower()


def _hex_rgb(value):
    raw = str(value or "").strip().lstrip("#")
    if len(raw) == 3:
        raw = "".join(ch * 2 for ch in raw)
    if len(raw) != 6:
        return (0, 0, 0)
    try:
        return tuple(int(raw[i:i + 2], 16) for i in (0, 2, 4))
    except Exception:
        return (0, 0, 0)


def _best_input_fg(input_bg):
    r, g, b = _hex_rgb(input_bg)
    luminance = (0.299 * r + 0.587 * g + 0.114 * b) / 255.0
    return INPUT_FG_DARK if luminance >= 0.62 else INPUT_FG_LIGHT


def _refresh_input_widgets(widget, input_bg, input_fg):
    top = widget.winfo_toplevel() if hasattr(widget, "winfo_toplevel") else None
    highlight = _norm_hex(getattr(top, "_highlight_bg", HIGHLIGHT_INPUT))
    try:
        if isinstance(widget, tk.Entry):
            current_bg = _norm_hex(widget.cget("bg"))
            current_ro = _norm_hex(widget.cget("readonlybackground"))
            if current_bg != highlight:
                widget.configure(bg=input_bg, fg=input_fg, insertbackground=input_fg)
            if current_ro != highlight:
                try:
                    widget.configure(readonlybackground=input_bg)
                except Exception:
                    pass
            try:
                widget.configure(disabledbackground=input_bg, disabledforeground=input_fg)
            except Exception:
                pass
        elif isinstance(widget, tk.Text):
            current_bg = _norm_hex(widget.cget("bg"))
            if current_bg != highlight:
                widget.configure(bg=input_bg, fg=input_fg, insertbackground=input_fg)
        elif isinstance(widget, tk.Listbox):
            widget.configure(bg=input_bg, fg=input_fg, selectbackground=BG_ENTRY, selectforeground=FG)
    except Exception:
        pass

    try:
        for child in widget.winfo_children():
            _refresh_input_widgets(child, input_bg, input_fg)
    except Exception:
        pass


def _apply_app_palette(root, app_bg):
    root._app_bg = app_bg
    root._app_fg = _best_input_fg(app_bg)
    app_fg = root._app_fg
    try:
        root.configure(bg=app_bg)
    except Exception:
        pass

    try:
        root.tk_setPalette(
            background=app_bg,
            foreground=app_fg,
            activeBackground=ACCENT,
            activeForeground=app_fg,
            highlightColor=ACCENT,
            selectBackground=ACCENT,
            selectForeground=app_fg,
            insertBackground=app_fg,
        )
    except Exception:
        pass

    try:
        style = ttk.Style(root)
        style.theme_use("clam")
        style.configure(".", background=app_bg, foreground=app_fg)
        style.configure("TFrame", background=app_bg)
        style.configure("TLabel", background=app_bg, foreground=app_fg)
        style.configure("TButton", background=app_bg, foreground=app_fg)
        style.configure("TCheckbutton", background=app_bg, foreground=app_fg)
        style.configure("TRadiobutton", background=app_bg, foreground=app_fg)
        style.configure("TNotebook", background=app_bg)
        style.configure("TNotebook.Tab", background=app_bg, foreground=app_fg)
        style.configure("Treeview", background=app_bg, fieldbackground=app_bg, foreground=app_fg)
        style.configure("Treeview.Heading", background=app_bg, foreground=app_fg)
        style.map("TNotebook.Tab",
                  background=[("selected", BG_ENTRY)],
                  foreground=[("selected", FG)])
        style.map("TButton",
                  background=[("active", BG_ENTRY)],
                  foreground=[("active", FG)])
    except Exception:
        pass

    try:
        root.event_generate("<<AppBgChanged>>")
    except Exception:
        pass


def _apply_input_palette(root, input_bg):
    root._input_bg = input_bg
    root._input_fg = _best_input_fg(input_bg)
    input_fg = root._input_fg
    try:
        style = ttk.Style(root)
        style.configure("TEntry", fieldbackground=input_bg, foreground=input_fg)
        style.map("TEntry",
                  fieldbackground=[("readonly", input_bg), ("disabled", input_bg)],
                  foreground=[("readonly", input_fg), ("disabled", input_fg)])
        style.configure("TCombobox", fieldbackground=input_bg, foreground=input_fg, background=input_bg, arrowcolor=input_fg)
        style.map("TCombobox",
                  fieldbackground=[("readonly", input_bg), ("disabled", input_bg), ("!disabled", input_bg)],
                  foreground=[("readonly", input_fg), ("disabled", input_fg), ("!disabled", input_fg)])
    except Exception:
        pass

    try:
        root.option_add("*Entry*Background", input_bg)
        root.option_add("*Entry*Foreground", input_fg)
        root.option_add("*Entry*insertBackground", input_fg)
        root.option_add("*Text*Background", input_bg)
        root.option_add("*Text*Foreground", input_fg)
        root.option_add("*Text*insertBackground", input_fg)
        root.option_add("*TCombobox*Listbox*Background", input_bg)
        root.option_add("*TCombobox*Listbox*Foreground", input_fg)
        root.option_add("*TCombobox*Listbox*selectBackground", BG_ENTRY)
        root.option_add("*TCombobox*Listbox*selectForeground", FG)
        root.option_add("*Listbox*Background", input_bg)
        root.option_add("*Listbox*Foreground", input_fg)
        root.option_add("*Listbox*selectBackground", BG_ENTRY)
        root.option_add("*Listbox*selectForeground", FG)
    except Exception:
        pass

    _refresh_input_widgets(root, input_bg, input_fg)

    try:
        root.event_generate("<<InputColorChanged>>")
    except Exception:
        pass


def _apply_highlight_palette(root, highlight_bg):
    root._highlight_bg = highlight_bg
    root._highlight_fg = _best_input_fg(highlight_bg)
    try:
        root.event_generate("<<HighlightColorChanged>>")
    except Exception:
        pass


def _apply_print_group_colors(root, colors):
    root._print_group_colors = list(colors or [])
    try:
        root.event_generate("<<PrintGroupColorsChanged>>")
    except Exception:
        pass


def _apply_theme(root, input_bg=None):
    if THEME != "dark":
        return
    input_bg = input_bg or ACCENT
    _apply_app_palette(root, BG)
    _apply_input_palette(root, input_bg)


class App(tk.Frame):
    def __init__(self, master):
        super().__init__(master)
        self.master.title(APP_TITLE)
        self.pack(fill="both", expand=True)
        self._closing = False
        self._dev_reload_job = None
        self._dev_reload_file = os.environ.get("AJUSTE_COMP_DEV_RELOAD_FILE", "").strip()
        self._dev_reload_stamp = self._dev_reload_file_mtime()
        self._bg_color_name = DEFAULT_BG_COLOR
        self._custom_bg_color = None
        self._input_color_name = DEFAULT_INPUT_COLOR
        self._custom_input_color = None
        self._highlight_color_name = DEFAULT_HIGHLIGHT_COLOR
        self._custom_highlight_color = None
        self._print_group_color_names = list(DEFAULT_PRINT_GROUP_COLORS)
        self._custom_print_group_colors = [None, None, None]
        self._bg_color_var = tk.StringVar(value=self._bg_color_name)
        self._auto_save_hours = 3.0
        self._auto_refresh_seconds = 0.25
        self._debug_mode = False
        self._input_color_var = tk.StringVar(value=self._input_color_name)
        self._highlight_color_var = tk.StringVar(value=self._highlight_color_name)
        self._print_group_color_vars = [tk.StringVar(value=name) for name in self._print_group_color_names]
        self._auto_save_hours_var = tk.StringVar(value="3")
        self._auto_refresh_seconds_var = tk.StringVar(value="0.25")
        self._debug_mode_var = tk.BooleanVar(value=False)
        self._host_api = None
        self._host_api_public = None
        self._tunnel_proc = None
        self._tunnel_watchdog_job = None
        self._tunnel_checking = False
        self._tunnel_failure_count = 0
        self._tunnel_restart_count = 0
        self._tunnel_status = {}
        self._tunnel_paused = False
        self._orphan_tunnel_cleanup_running = False

        self.alloys = load_alloys()

        dock = ttk.Frame(self)
        dock.pack(fill="both", expand=True, padx=8, pady=(8, 8))

        nb = ttk.Notebook(dock)
        nb.pack(fill="both", expand=True)
        self.nb = nb

        self.tab_catalogo = TabCatalogo(nb, self.alloys)
        self.tab_ajuste   = TabAjuste(nb, self.alloys)
        self.tab_ajuste.set_save_callback(self.schedule_save)
        self.tab_hist     = TabHistoricos(nb, self.alloys)
        self.tab_info     = TabInformes(nb, self.alloys)
        self.tab_calidad  = TabCalidad(nb, self.alloys)
        self.tab_analisis_termico = TabAnalisisTermico(nb)
        self.tab_analisis_termico.set_adjust_target(self.tab_ajuste)
        self.tab_ajuste.set_thermal_source(self.tab_analisis_termico)
        self.tab_pie_horno = TabPieHorno(nb)
        self.tab_pie_horno.set_tunnel_pause_callback(self.toggle_public_tunnel_pause)
        self.tab_options  = ttk.Frame(nb, padding=12)
        self.tab_hist.set_quality_target(nb, self.tab_calidad)
        self.tab_hist.set_thermal_target(nb, self.tab_analisis_termico)
        self.tab_hist.set_adjust_view_target(nb, self.tab_ajuste)
        self.tab_catalogo.refresh()
        self.tab_ajuste.refresh_objectives()
        self.tab_hist.refresh_catalog()
        self.tab_calidad.refresh_catalog()

        nb.add(self.tab_ajuste,   text="Ajuste")
        nb.add(self.tab_hist,     text="Históricos")

        nb.add(self.tab_info,     text="Estadisticas")
        nb.add(self.tab_calidad,  text="Calidad")
        nb.add(self.tab_analisis_termico, text="Analisis termico")
        nb.add(self.tab_pie_horno, text="PIE DE HORNO")
        nb.add(self.tab_catalogo, text="Catálogo")
        nb.add(self.tab_options,  text="Opciones")

        self._build_options_tab()

        self.tab_ajuste.bind("<<HistoryUpdated>>", lambda e: (self.tab_hist.refresh(), self.tab_info.refresh()))
        self.tab_analisis_termico.bind("<<HistoryUpdated>>", lambda e: self.tab_hist.refresh())
        self.tab_catalogo.bind("<<CatalogUpdated>>", lambda e: (self.tab_ajuste.refresh_objectives(), self.tab_hist.refresh_catalog(), self.tab_info.refresh(), self.tab_calidad.refresh_catalog()))

        self._save_job = None
        self.master.bind("<<AppBgChanged>>", lambda e: self._on_app_bg_changed(), add="+")
        self.master.bind("<<InputColorChanged>>", lambda e: self._on_input_color_changed(), add="+")
        self.master.bind("<<HighlightColorChanged>>", lambda e: self._on_highlight_color_changed(), add="+")
        self.master.bind("<<PrintGroupColorsChanged>>", lambda e: self._on_print_group_colors_changed(), add="+")
        self.master._auto_save_hours = self._auto_save_hours
        self.master._auto_refresh_ms = int(self._auto_refresh_seconds * 1000)
        self.master._debug_mode = self._debug_mode
        _apply_print_group_colors(self.master, self._current_print_group_colors())
        self.master.protocol("WM_DELETE_WINDOW", self._on_close)
        self._restore_state()
        self._start_host_api()
        if not self._tunnel_paused:
            self._set_tunnel_status("starting", f"Preparando tunnel publico: {PUBLIC_TUNNEL_URL}")
            self._stop_orphan_public_tunnels(
                on_done=lambda: (
                    self._start_public_tunnel(),
                    self._schedule_tunnel_watchdog(TUNNEL_WATCHDOG_START_DELAY_MS),
                )
            )
        self._schedule_dev_reload_watch()
        self.after(6000, self._start_update_check)

    def _current_input_bg(self):
        if self._input_color_name == CUSTOM_INPUT_COLOR and self._custom_input_color:
            return self._custom_input_color
        return INPUT_COLOR_PRESETS.get(self._input_color_name, ACCENT)

    def _current_input_fg(self):
        return getattr(self.master, "_input_fg", _best_input_fg(self._current_input_bg()))

    def _current_app_bg(self):
        if self._bg_color_name == CUSTOM_BG_COLOR and self._custom_bg_color:
            return self._custom_bg_color
        return BG_COLOR_PRESETS.get(self._bg_color_name, BG)

    def _current_app_fg(self):
        return getattr(self.master, "_app_fg", _best_input_fg(self._current_app_bg()))

    def _current_highlight_bg(self):
        if self._highlight_color_name == CUSTOM_HIGHLIGHT_COLOR and self._custom_highlight_color:
            return self._custom_highlight_color
        return HIGHLIGHT_COLOR_PRESETS.get(self._highlight_color_name, HIGHLIGHT_INPUT)

    def _current_highlight_fg(self):
        return getattr(self.master, "_highlight_fg", _best_input_fg(self._current_highlight_bg()))

    def _current_print_group_color(self, index):
        name = self._print_group_color_names[index]
        if name == CUSTOM_PRINT_GROUP_COLOR and self._custom_print_group_colors[index]:
            return self._custom_print_group_colors[index]
        return PRINT_GROUP_COLOR_PRESETS.get(name, PRINT_GROUP_COLOR_PRESETS[DEFAULT_PRINT_GROUP_COLORS[index]])

    def _current_print_group_colors(self):
        return [self._current_print_group_color(i) for i in range(3)]

    def _apply_selected_bg_color(self, color_name, save=True):
        if color_name == CUSTOM_BG_COLOR:
            if not self._custom_bg_color:
                color_name = DEFAULT_BG_COLOR
        elif color_name not in BG_COLOR_PRESETS:
            color_name = DEFAULT_BG_COLOR
        self._bg_color_name = color_name
        self._bg_color_var.set(color_name)
        _apply_app_palette(self.master, self._current_app_bg())
        _apply_input_palette(self.master, self._current_input_bg())
        if save:
            self.schedule_save()

    def _apply_selected_input_color(self, color_name, save=True):
        if color_name == CUSTOM_INPUT_COLOR:
            if not self._custom_input_color:
                color_name = DEFAULT_INPUT_COLOR
        elif color_name not in INPUT_COLOR_PRESETS:
            color_name = DEFAULT_INPUT_COLOR
        self._input_color_name = color_name
        self._input_color_var.set(color_name)
        _apply_input_palette(self.master, self._current_input_bg())
        if save:
            self.schedule_save()

    def _apply_selected_highlight_color(self, color_name, save=True):
        if color_name == CUSTOM_HIGHLIGHT_COLOR:
            if not self._custom_highlight_color:
                color_name = DEFAULT_HIGHLIGHT_COLOR
        elif color_name not in HIGHLIGHT_COLOR_PRESETS:
            color_name = DEFAULT_HIGHLIGHT_COLOR
        self._highlight_color_name = color_name
        self._highlight_color_var.set(color_name)
        _apply_highlight_palette(self.master, self._current_highlight_bg())
        if save:
            self.schedule_save()

    def _apply_selected_print_group_color(self, index, color_name, save=True):
        if color_name == CUSTOM_PRINT_GROUP_COLOR:
            if not self._custom_print_group_colors[index]:
                color_name = DEFAULT_PRINT_GROUP_COLORS[index]
        elif color_name not in PRINT_GROUP_COLOR_PRESETS:
            color_name = DEFAULT_PRINT_GROUP_COLORS[index]
        self._print_group_color_names[index] = color_name
        self._print_group_color_vars[index].set(color_name)
        _apply_print_group_colors(self.master, self._current_print_group_colors())
        if save:
            self.schedule_save()

    def _available_input_colors(self):
        values = list(INPUT_COLOR_PRESETS.keys())
        if self._custom_input_color:
            values.append(CUSTOM_INPUT_COLOR)
        return tuple(values)

    def _available_bg_colors(self):
        values = list(BG_COLOR_PRESETS.keys())
        if self._custom_bg_color:
            values.append(CUSTOM_BG_COLOR)
        return tuple(values)

    def _available_highlight_colors(self):
        values = list(HIGHLIGHT_COLOR_PRESETS.keys())
        if self._custom_highlight_color:
            values.append(CUSTOM_HIGHLIGHT_COLOR)
        return tuple(values)

    def _available_print_group_colors(self, index):
        values = list(PRINT_GROUP_COLOR_PRESETS.keys())
        if self._custom_print_group_colors[index]:
            values.append(CUSTOM_PRINT_GROUP_COLOR)
        return tuple(values)

    def _choose_custom_input_color(self):
        current = self._current_input_bg()
        try:
            _, hex_color = colorchooser.askcolor(color=current, parent=self.master, title="Elegir color de casillas")
        except Exception:
            hex_color = None
        if not hex_color:
            return
        self._custom_input_color = hex_color
        self._input_color_name = CUSTOM_INPUT_COLOR
        self._input_color_var.set(CUSTOM_INPUT_COLOR)
        try:
            if hasattr(self, "_options_combo") and self._options_combo.winfo_exists():
                self._options_combo.configure(values=self._available_input_colors())
        except Exception:
            pass
        _apply_input_palette(self.master, self._custom_input_color)
        self.schedule_save()

    def _choose_custom_bg_color(self):
        current = self._current_app_bg()
        try:
            _, hex_color = colorchooser.askcolor(color=current, parent=self.master, title="Elegir color de fondo")
        except Exception:
            hex_color = None
        if not hex_color:
            return
        self._custom_bg_color = hex_color
        self._bg_color_name = CUSTOM_BG_COLOR
        self._bg_color_var.set(CUSTOM_BG_COLOR)
        try:
            if hasattr(self, "_options_bg_combo") and self._options_bg_combo.winfo_exists():
                self._options_bg_combo.configure(values=self._available_bg_colors())
        except Exception:
            pass
        _apply_app_palette(self.master, self._custom_bg_color)
        _apply_input_palette(self.master, self._current_input_bg())
        self.schedule_save()

    def _choose_custom_highlight_color(self):
        current = self._current_highlight_bg()
        try:
            _, hex_color = colorchooser.askcolor(color=current, parent=self.master, title="Elegir color de resaltado")
        except Exception:
            hex_color = None
        if not hex_color:
            return
        self._custom_highlight_color = hex_color
        self._highlight_color_name = CUSTOM_HIGHLIGHT_COLOR
        self._highlight_color_var.set(CUSTOM_HIGHLIGHT_COLOR)
        try:
            if hasattr(self, "_options_highlight_combo") and self._options_highlight_combo.winfo_exists():
                self._options_highlight_combo.configure(values=self._available_highlight_colors())
        except Exception:
            pass
        _apply_highlight_palette(self.master, self._custom_highlight_color)
        self.schedule_save()

    def _choose_custom_print_group_color(self, index):
        current = self._current_print_group_color(index)
        try:
            _, hex_color = colorchooser.askcolor(color=current, parent=self.master, title=f"Elegir color del grupo {index + 1}")
        except Exception:
            hex_color = None
        if not hex_color:
            return
        self._custom_print_group_colors[index] = hex_color
        self._print_group_color_names[index] = CUSTOM_PRINT_GROUP_COLOR
        self._print_group_color_vars[index].set(CUSTOM_PRINT_GROUP_COLOR)
        try:
            combo = getattr(self, f"_options_print_group_combo_{index}", None)
            if combo and combo.winfo_exists():
                combo.configure(values=self._available_print_group_colors(index))
        except Exception:
            pass
        _apply_print_group_colors(self.master, self._current_print_group_colors())
        self.schedule_save()

    def _build_options_tab(self):
        box = ttk.Frame(self.tab_options)
        box.pack(fill="both", expand=True)

        intro = ttk.LabelFrame(box, text="Apariencia", padding=12)
        intro.pack(fill="x", pady=(0, 12))
        ttk.Label(intro, text="Color de fondo").pack(anchor="w")
        cb_bg = ttk.Combobox(
            intro,
            textvariable=self._bg_color_var,
            state="readonly",
            values=self._available_bg_colors(),
            width=24,
        )
        self._options_bg_combo = cb_bg
        cb_bg.pack(fill="x", pady=(6, 10))
        cb_bg.bind("<<ComboboxSelected>>", lambda e: self._apply_selected_bg_color(self._bg_color_var.get()))
        ttk.Button(intro, text="Personalizado...", command=self._choose_custom_bg_color).pack(anchor="w", pady=(0, 10))

        self._bg_preview = tk.Label(
            intro,
            text="Vista previa del fondo general",
            anchor="w",
            padx=10,
            pady=8,
            bg=self._current_app_bg(),
            fg=self._current_app_fg(),
        )
        self._bg_preview.pack(fill="x", pady=(0, 10))

        ttk.Label(intro, text="Color de casillas").pack(anchor="w")
        cb = ttk.Combobox(
            intro,
            textvariable=self._input_color_var,
            state="readonly",
            values=self._available_input_colors(),
            width=24,
        )
        self._options_combo = cb
        cb.pack(fill="x", pady=(6, 10))
        cb.bind("<<ComboboxSelected>>", lambda e: self._apply_selected_input_color(self._input_color_var.get()))
        ttk.Button(intro, text="Personalizado...", command=self._choose_custom_input_color).pack(anchor="w", pady=(0, 10))

        self._preview = tk.Label(
            intro,
            text="Vista previa de entradas y combos",
            anchor="w",
            padx=10,
            pady=8,
            bg=self._current_input_bg(),
            fg=self._current_input_fg(),
        )
        self._preview.pack(fill="x", pady=(0, 10))

        ttk.Label(intro, text="El cambio se aplica al instante y se ajusta el contraste de la letra.").pack(anchor="w")

        debug_box = ttk.LabelFrame(box, text="Diagnostico", padding=12)
        debug_box.pack(fill="x", pady=(12, 12))
        ttk.Checkbutton(
            debug_box,
            text="Modo debug (mostrar mensajes de backend en consola)",
            variable=self._debug_mode_var,
            command=self._apply_debug_mode_from_ui,
        ).pack(anchor="w")
        ttk.Label(debug_box, text="Sirve para revisar descargas, llamadas HTTP y pasos internos sin dejarlo siempre encendido.").pack(anchor="w", pady=(6, 0))

        auto_box = ttk.LabelFrame(box, text="Guardado automatico", padding=12)
        auto_box.pack(fill="x", pady=(12, 12))
        ttk.Label(auto_box, text="Horas maximas antes de guardar sola una sesion").pack(anchor="w")
        auto_row = ttk.Frame(auto_box)
        auto_row.pack(fill="x", pady=(6, 8))
        self._auto_save_spin = tk.Spinbox(
            auto_row,
            from_=1.0,
            to=24.0,
            increment=0.5,
            textvariable=self._auto_save_hours_var,
            width=8,
        )
        self._auto_save_spin.pack(side="left")
        ttk.Button(auto_row, text="Aplicar", command=self._apply_auto_save_hours_from_ui).pack(side="left", padx=(8, 0))
        ttk.Label(auto_box, text="Se usa para cortar la sesion actual y guardarla en Historicos automaticamente.").pack(anchor="w")

        refresh_box = ttk.LabelFrame(box, text="Actualizacion en tiempo real", padding=12)
        refresh_box.pack(fill="x", pady=(12, 12))
        ttk.Label(refresh_box, text="Cada cuantos segundos se actualiza el temporizador").pack(anchor="w")
        refresh_row = ttk.Frame(refresh_box)
        refresh_row.pack(fill="x", pady=(6, 8))
        self._auto_refresh_spin = tk.Spinbox(
            refresh_row,
            from_=0.25,
            to=5.0,
            increment=0.25,
            textvariable=self._auto_refresh_seconds_var,
            width=8,
        )
        self._auto_refresh_spin.pack(side="left")
        ttk.Button(refresh_row, text="Aplicar", command=self._apply_auto_refresh_seconds_from_ui).pack(side="left", padx=(8, 0))
        ttk.Label(refresh_box, text="Tambien afecta la frecuencia del auto-estimar y del chequeo de guardado automatico.").pack(anchor="w")

        highlight_box = ttk.LabelFrame(box, text="Resaltado de cambios en Calidad", padding=12)
        highlight_box.pack(fill="x")
        ttk.Label(highlight_box, text="Color de resaltado").pack(anchor="w")
        cb_highlight = ttk.Combobox(
            highlight_box,
            textvariable=self._highlight_color_var,
            state="readonly",
            values=self._available_highlight_colors(),
            width=24,
        )
        self._options_highlight_combo = cb_highlight
        cb_highlight.pack(fill="x", pady=(6, 10))
        cb_highlight.bind("<<ComboboxSelected>>", lambda e: self._apply_selected_highlight_color(self._highlight_color_var.get()))
        ttk.Button(highlight_box, text="Personalizado...", command=self._choose_custom_highlight_color).pack(anchor="w", pady=(0, 10))

        self._highlight_preview = tk.Label(
            highlight_box,
            text="Vista previa del resaltado de cambios",
            anchor="w",
            padx=10,
            pady=8,
            bg=self._current_highlight_bg(),
            fg=self._current_highlight_fg(),
        )
        self._highlight_preview.pack(fill="x", pady=(0, 10))
        ttk.Label(highlight_box, text="Se usa para casillas modificadas y borradores del historial de Calidad.").pack(anchor="w")

        print_box = ttk.LabelFrame(box, text="Colores de impresion por grupo", padding=12)
        print_box.pack(fill="x", pady=(12, 0))
        ttk.Label(print_box, text="Se aplican al 1ro, 2do y 3er grupo impreso, de arriba hacia abajo.").pack(anchor="w", pady=(0, 8))
        self._print_group_previews = []
        for i in range(3):
            row = ttk.Frame(print_box)
            row.pack(fill="x", pady=(0, 8))
            ttk.Label(row, text=f"Grupo {i + 1}", width=10).pack(side="left")
            cb_group = ttk.Combobox(
                row,
                textvariable=self._print_group_color_vars[i],
                state="readonly",
                values=self._available_print_group_colors(i),
                width=20,
            )
            setattr(self, f"_options_print_group_combo_{i}", cb_group)
            cb_group.pack(side="left", padx=(0, 8))
            cb_group.bind("<<ComboboxSelected>>", lambda e, idx=i: self._apply_selected_print_group_color(idx, self._print_group_color_vars[idx].get()))
            ttk.Button(row, text="Personalizado...", command=lambda idx=i: self._choose_custom_print_group_color(idx)).pack(side="left", padx=(0, 8))
            preview = tk.Label(row, text="Texto de impresion", anchor="w", padx=8, pady=4,
                               bg="white", fg=self._current_print_group_color(i), relief="solid", bd=1)
            preview.pack(side="left", fill="x", expand=True)
            self._print_group_previews.append(preview)

    def _on_input_color_changed(self):
        try:
            if hasattr(self, "_preview") and self._preview.winfo_exists():
                self._preview.configure(bg=self._current_input_bg(), fg=self._current_input_fg())
        except Exception:
            pass
        try:
            if hasattr(self, "tab_ajuste"):
                self.tab_ajuste._update_objective_selector_state()
        except Exception:
            pass
        try:
            if hasattr(self, "tab_calidad"):
                self.tab_calidad._apply_field_highlights()
        except Exception:
            pass
        self._on_highlight_color_changed()
        self._on_print_group_colors_changed()

    def _on_app_bg_changed(self):
        try:
            if hasattr(self, "_bg_preview") and self._bg_preview.winfo_exists():
                self._bg_preview.configure(bg=self._current_app_bg(), fg=self._current_app_fg())
        except Exception:
            pass

    def _on_highlight_color_changed(self):
        try:
            if hasattr(self, "_highlight_preview") and self._highlight_preview.winfo_exists():
                self._highlight_preview.configure(bg=self._current_highlight_bg(), fg=self._current_highlight_fg())
        except Exception:
            pass
        try:
            if hasattr(self, "tab_ajuste"):
                self.tab_ajuste._update_objective_selector_state()
        except Exception:
            pass

    def _on_print_group_colors_changed(self):
        try:
            for i, preview in enumerate(getattr(self, "_print_group_previews", [])):
                if preview and preview.winfo_exists():
                    preview.configure(fg=self._current_print_group_color(i))
        except Exception:
            pass
        try:
            if hasattr(self, "tab_calidad"):
                self.tab_calidad._init_highlight_styles()
                self.tab_calidad._apply_field_highlights()
                try:
                    self.tab_calidad.tree.tag_configure("draft", background=self._current_highlight_bg(), foreground=self._current_highlight_fg())
                except Exception:
                    pass
        except Exception:
            pass

    def _apply_auto_save_hours(self, hours, save=True):
        try:
            value = float(hours)
        except Exception:
            value = self._auto_save_hours
        if value < 1.0:
            value = 1.0
        if value > 24.0:
            value = 24.0
        self._auto_save_hours = value
        self._auto_save_hours_var.set(f"{value:g}")
        self.master._auto_save_hours = value
        if save:
            self.schedule_save()

    def _apply_auto_save_hours_from_ui(self):
        self._apply_auto_save_hours(self._auto_save_hours_var.get())

    def _apply_auto_refresh_seconds(self, seconds, save=True):
        try:
            value = float(seconds)
        except Exception:
            value = self._auto_refresh_seconds
        if value < 0.25:
            value = 0.25
        if value > 5.0:
            value = 5.0
        self._auto_refresh_seconds = value
        self._auto_refresh_seconds_var.set(f"{value:g}")
        self.master._auto_refresh_ms = max(100, int(value * 1000))
        if save:
            self.schedule_save()

    def _apply_auto_refresh_seconds_from_ui(self):
        self._apply_auto_refresh_seconds(self._auto_refresh_seconds_var.get())

    def _apply_debug_mode(self, enabled, save=True):
        self._debug_mode = bool(enabled)
        self._debug_mode_var.set(self._debug_mode)
        self.master._debug_mode = self._debug_mode
        if save:
            self.schedule_save()

    def _apply_debug_mode_from_ui(self):
        self._apply_debug_mode(self._debug_mode_var.get())

    # ------------------ Guardado programado del estado ------------------
    def schedule_save(self, delay_ms: int = 400):
        try:
            if self._save_job is not None:
                self.after_cancel(self._save_job)
        except Exception:
            pass
        self._save_job = self.after(delay_ms, self._save_all)

    def _save_all(self):
        self._save_job = None
        try:
            save_alloys(self.alloys)
        except Exception as ex:
            print(f"[WARN] No se pudo guardar el catálogo: {ex}")

        try:
            st = {
                "window": {
                    "geometry": self.master.winfo_geometry(),
                    "selected_tab": self.nb.index("current")
                },
                "options": {
                    "bg_color_name": self._bg_color_name,
                    "custom_bg_color": self._custom_bg_color,
                    "input_color_name": self._input_color_name,
                    "custom_input_color": self._custom_input_color,
                    "highlight_color_name": self._highlight_color_name,
                    "custom_highlight_color": self._custom_highlight_color,
                    "print_group_color_names": self._print_group_color_names,
                    "custom_print_group_colors": self._custom_print_group_colors,
                    "auto_save_hours": self._auto_save_hours,
                    "auto_refresh_seconds": self._auto_refresh_seconds,
                    "debug_mode": self._debug_mode,
                    "thermal_device_ip": self.tab_analisis_termico.device_ip_var.get().strip(),
                },
                "ajuste_state": self.tab_ajuste.get_state()
            }
            path = _state_path()
            tmp = path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=2)
            os.replace(tmp, path)
        except Exception as ex:
            print(f"[WARN] No se pudo guardar el estado de la UI: {ex}")

    # ------------------ Restauración del estado ------------------
    def _restore_state(self):
        path = _state_path()
        if not os.path.exists(path):
            self._apply_default_layout(); return
        try:
            with open(path, "r", encoding="utf-8") as f:
                st = json.load(f)
        except Exception as ex:
            try:
                if messagebox.askyesno(
                    "Estado de la app",
                    f"No se pudo leer el archivo de estado.\n\n{ex}\n\n¿Borrar archivo de estado viejo?"
                ):
                    try: os.remove(path)
                    except Exception: pass
                    self._apply_default_layout()
                    return
            except Exception:
                pass
            self._apply_default_layout()
            return

        geom = (st.get("window") or {}).get("geometry")
        opts = st.get("options") or {}
        self._custom_bg_color = opts.get("custom_bg_color") or None
        self._custom_input_color = opts.get("custom_input_color") or None
        self._custom_highlight_color = opts.get("custom_highlight_color") or None
        self._apply_auto_save_hours(opts.get("auto_save_hours", 3.0), save=False)
        self._apply_auto_refresh_seconds(opts.get("auto_refresh_seconds", 0.25), save=False)
        self._apply_debug_mode(opts.get("debug_mode", False), save=False)
        saved_print_names = list(opts.get("print_group_color_names") or DEFAULT_PRINT_GROUP_COLORS)
        saved_print_custom = list(opts.get("custom_print_group_colors") or [None, None, None])
        while len(saved_print_names) < 3:
            saved_print_names.append(DEFAULT_PRINT_GROUP_COLORS[len(saved_print_names)])
        while len(saved_print_custom) < 3:
            saved_print_custom.append(None)
        self._print_group_color_names = saved_print_names[:3]
        self._custom_print_group_colors = saved_print_custom[:3]
        for i in range(3):
            self._print_group_color_vars[i].set(self._print_group_color_names[i])
        self._apply_selected_bg_color(opts.get("bg_color_name", DEFAULT_BG_COLOR), save=False)
        self._apply_selected_input_color(opts.get("input_color_name", DEFAULT_INPUT_COLOR), save=False)
        self._apply_selected_highlight_color(opts.get("highlight_color_name", DEFAULT_HIGHLIGHT_COLOR), save=False)
        try:
            self.tab_analisis_termico.device_ip_var.set(str(opts.get("thermal_device_ip") or self.tab_analisis_termico.device_ip_var.get()).strip())
        except Exception:
            pass
        _apply_print_group_colors(self.master, self._current_print_group_colors())
        if geom:
            try: self.master.geometry(geom)
            except Exception: pass
        else:
            self._apply_default_layout()

        sel_tab = (st.get("window") or {}).get("selected_tab", 1)
        try: self.nb.select(sel_tab)
        except Exception: pass

        try:
            self.tab_ajuste.set_state(st.get("ajuste_state", {}))
        except Exception as ex:
            print(f"[WARN] No se pudo restaurar el estado de Ajuste: {ex}")

    def _apply_default_layout(self):
        try: self.master.geometry("1200x720")
        except Exception: pass
        try: self.nb.select(1)
        except Exception: pass

    def _start_host_api(self):
        try:
            self._host_api = HostAPIServer(port=HOST_API_PORT).start()
            self._host_api_public = HostAPIServer(port=HOST_API_PUBLIC_PORT).start()
            print(f"[HOST API] LAN escuchando en {self._host_api.url()}")
            print(f"[HOST API] PUBLIC escuchando en http://127.0.0.1:{self._host_api_public.port}")
        except Exception as ex:
            self._host_api = None
            self._host_api_public = None
            print(f"[HOST API] No se pudo iniciar: {ex}")

    def _public_tunnel_command(self):
        port = self._host_api_public.port if self._host_api_public is not None else HOST_API_PUBLIC_PORT
        appdata = os.environ.get("APPDATA", "")
        lt_cmd = os.path.join(appdata, "npm", "lt.cmd") if appdata else ""
        lt_js = os.path.join(appdata, "npm", "node_modules", "localtunnel", "bin", "lt.js") if appdata else ""
        if os.path.exists(lt_js):
            command = ["node", lt_js, "--port", str(port), "--subdomain", PUBLIC_TUNNEL_SUBDOMAIN]
        else:
            command = [lt_cmd if os.path.exists(lt_cmd) else "lt", "--port", str(port), "--subdomain", PUBLIC_TUNNEL_SUBDOMAIN]
        env = os.environ.copy()
        node_dir = r"C:\Program Files\nodejs"
        if os.path.isdir(node_dir):
            env["PATH"] = node_dir + os.pathsep + env.get("PATH", "")
        creationflags = subprocess.CREATE_NO_WINDOW if hasattr(subprocess, "CREATE_NO_WINDOW") else 0
        return command, env, creationflags

    def _set_tunnel_status(self, state, message, error=""):
        info = {
            "state": state,
            "message": message,
            "error": error,
            "url": PUBLIC_TUNNEL_URL,
            "checked_at": datetime.now().isoformat(timespec="seconds"),
            "failures": self._tunnel_failure_count,
            "restarts": self._tunnel_restart_count,
            "paused": self._tunnel_paused,
        }
        self._tunnel_status = info
        try:
            self.tab_pie_horno.set_tunnel_status(info)
        except Exception:
            pass

    def _start_public_tunnel(self):
        if self._tunnel_paused:
            self._set_tunnel_status("paused", f"Tunnel publico pausado: {PUBLIC_TUNNEL_URL}")
            return
        if self._tunnel_proc is not None and self._tunnel_proc.poll() is None:
            return

        command, env, creationflags = self._public_tunnel_command()

        try:
            self._tunnel_proc = subprocess.Popen(
                command,
                cwd=os.path.dirname(os.path.abspath(__file__)),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                creationflags=creationflags,
            )
            self._set_tunnel_status("starting", f"Tunnel publico iniciando: {PUBLIC_TUNNEL_URL}")
            print(f"[LOCAL TUNNEL] URL publica: {PUBLIC_TUNNEL_URL}")
        except FileNotFoundError:
            self._tunnel_proc = None
            self._set_tunnel_status("error", "No se encontro localtunnel.", "Instalar con: npm install -g localtunnel")
            print("[LOCAL TUNNEL] No se encontro localtunnel. Instalar con: npm install -g localtunnel")
        except Exception as ex:
            self._tunnel_proc = None
            self._set_tunnel_status("error", "No se pudo iniciar el tunnel publico.", str(ex))
            print(f"[LOCAL TUNNEL] No se pudo iniciar: {ex}")

    def toggle_public_tunnel_pause(self):
        self._set_public_tunnel_paused(not self._tunnel_paused)

    def _set_public_tunnel_paused(self, paused):
        paused = bool(paused)
        if paused == self._tunnel_paused:
            return
        self._tunnel_paused = paused
        self._tunnel_failure_count = 0
        if paused:
            try:
                if self._tunnel_watchdog_job is not None:
                    self.after_cancel(self._tunnel_watchdog_job)
                    self._tunnel_watchdog_job = None
            except Exception:
                pass
            self._stop_public_tunnel()
            self._stop_orphan_public_tunnels()
            self._set_tunnel_status("paused", f"Tunnel publico pausado: {PUBLIC_TUNNEL_URL}")
            print("[LOCAL TUNNEL] Pausado por usuario.")
            return

        self._set_tunnel_status("starting", f"Reanudando tunnel publico: {PUBLIC_TUNNEL_URL}")
        self._start_public_tunnel()
        self._schedule_tunnel_watchdog(TUNNEL_WATCHDOG_START_DELAY_MS)
        print("[LOCAL TUNNEL] Reanudado por usuario.")

    def _stop_public_tunnel(self):
        proc = self._tunnel_proc
        self._tunnel_proc = None
        if proc is None:
            return

        def worker():
            try:
                if proc.poll() is None:
                    proc.terminate()
                    try:
                        proc.wait(timeout=5)
                    except subprocess.TimeoutExpired:
                        proc.kill()
            except Exception:
                pass

        threading.Thread(target=worker, name="localtunnel-stop", daemon=True).start()

    def _stop_orphan_public_tunnels(self, on_done=None):
        if self._orphan_tunnel_cleanup_running:
            if callable(on_done):
                self.after(500, lambda: self._stop_orphan_public_tunnels(on_done=on_done))
            return
        self._orphan_tunnel_cleanup_running = True

        def worker():
            try:
                port = self._host_api_public.port if self._host_api_public is not None else HOST_API_PUBLIC_PORT
                script = (
                    "Get-CimInstance Win32_Process -Filter \"name='node.exe'\" | "
                    f"Where-Object {{ $_.CommandLine -like '*localtunnel*--port {port}*' }} | "
                    "ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
                )
                subprocess.run(
                    ["powershell", "-NoProfile", "-Command", script],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=8,
                    check=False,
                )
            except Exception:
                pass
            finally:
                def finish():
                    self._orphan_tunnel_cleanup_running = False
                    if callable(on_done) and not self._closing:
                        on_done()
                try:
                    self.after(0, finish)
                except Exception:
                    self._orphan_tunnel_cleanup_running = False

        threading.Thread(target=worker, name="localtunnel-orphan-cleanup", daemon=True).start()

    def _public_tunnel_health_url(self):
        return PUBLIC_TUNNEL_URL.rstrip("/") + "/api/health"

    def _check_public_tunnel_health(self):
        if self._tunnel_proc is None or self._tunnel_proc.poll() is not None:
            return False, "El proceso de LocalTunnel no esta corriendo."
        req = urllib.request.Request(
            self._public_tunnel_health_url(),
            headers={
                "Accept": "application/json",
                "Cache-Control": "no-cache",
                "User-Agent": "ajuste_comp_tunnel_watchdog/1.0",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=TUNNEL_HEALTH_TIMEOUT_SECONDS) as resp:
                body = resp.read(4096).decode("utf-8", errors="replace")
                if 200 <= int(resp.status) < 300 and "ajuste_comp_host" in body:
                    return True, ""
                return False, f"Respuesta inesperada HTTP {resp.status}."
        except urllib.error.HTTPError as ex:
            return False, f"HTTP {ex.code}"
        except urllib.error.URLError as ex:
            return False, str(ex.reason or ex)
        except Exception as ex:
            return False, str(ex)

    def _schedule_tunnel_watchdog(self, delay_ms=TUNNEL_WATCHDOG_INTERVAL_MS):
        if self._tunnel_paused:
            return
        try:
            if self._tunnel_watchdog_job is not None:
                self.after_cancel(self._tunnel_watchdog_job)
        except Exception:
            pass
        self._tunnel_watchdog_job = self.after(delay_ms, self._run_tunnel_watchdog)

    def _run_tunnel_watchdog(self):
        self._tunnel_watchdog_job = None
        if self._tunnel_paused:
            return
        if self._tunnel_checking:
            self._schedule_tunnel_watchdog()
            return
        self._tunnel_checking = True

        def worker():
            ok, error = self._check_public_tunnel_health()
            try:
                self.after(0, lambda: self._finish_tunnel_watchdog(ok, error))
            except Exception:
                pass

        threading.Thread(target=worker, daemon=True).start()

    def _finish_tunnel_watchdog(self, ok, error):
        self._tunnel_checking = False
        if self._tunnel_paused:
            self._set_tunnel_status("paused", f"Tunnel publico pausado: {PUBLIC_TUNNEL_URL}")
            return
        if ok:
            self._tunnel_failure_count = 0
            self._set_tunnel_status("ok", f"Tunnel publico OK: {PUBLIC_TUNNEL_URL}")
            self._schedule_tunnel_watchdog()
            return

        self._tunnel_failure_count += 1
        if self._tunnel_failure_count >= TUNNEL_RESTART_AFTER_FAILURES:
            self._tunnel_restart_count += 1
            print(f"[LOCAL TUNNEL] Reiniciando por fallo de salud: {error}")
            self._set_tunnel_status("restarting", f"Reiniciando tunnel publico. Fallo: {error}")
            self._stop_public_tunnel()
            self._stop_orphan_public_tunnels(on_done=self._start_public_tunnel)
            self._tunnel_failure_count = 0
            if self._tunnel_restart_count >= TUNNEL_ALERT_AFTER_RESTARTS:
                self._set_tunnel_status(
                    "error",
                    f"Tunnel publico falla seguido. Reinicios: {self._tunnel_restart_count}.",
                    error,
                )
        else:
            self._set_tunnel_status("warning", f"Tunnel publico no responde. Reintentando: {error}", error)
        self._schedule_tunnel_watchdog()

    def _dev_reload_file_mtime(self):
        if not self._dev_reload_file:
            return 0.0
        try:
            return os.path.getmtime(self._dev_reload_file)
        except OSError:
            return 0.0

    def _schedule_dev_reload_watch(self):
        if not self._dev_reload_file or self._closing:
            return
        try:
            if self._dev_reload_job is not None:
                self.after_cancel(self._dev_reload_job)
        except Exception:
            pass
        self._dev_reload_job = self.after(DEV_RELOAD_POLL_MS, self._check_dev_reload)

    def _check_dev_reload(self):
        self._dev_reload_job = None
        if not self._dev_reload_file or self._closing:
            return
        current_stamp = self._dev_reload_file_mtime()
        if current_stamp > self._dev_reload_stamp:
            self._dev_reload_stamp = current_stamp
            print("[DEV] Cambio detectado. Reiniciando aplicacion...")
            self._on_close()
            return
        self._schedule_dev_reload_watch()

    # ------------------ Actualizaciones automáticas ------------------
    def _start_update_check(self):
        threading.Thread(target=self._run_update_check, daemon=True, name="update-check").start()

    def _run_update_check(self):
        import shutil, subprocess
        from pathlib import Path
        if not shutil.which("git"):
            return
        app_dir = Path(__file__).resolve().parent
        try:
            local = subprocess.run(
                ["git", "-C", str(app_dir), "rev-parse", "HEAD"],
                capture_output=True, text=True, timeout=10
            ).stdout.strip()
            r = subprocess.run(
                ["git", "-C", str(app_dir), "ls-remote", "origin", "HEAD"],
                capture_output=True, text=True, timeout=15
            )
            if r.returncode != 0 or not r.stdout.strip():
                return
            remote = r.stdout.split()[0]
            if local and remote and local != remote:
                self.after(0, self._prompt_and_update)
        except Exception:
            pass

    def _prompt_and_update(self):
        if self._closing:
            return
        if not messagebox.askyesno(
            "Actualización disponible",
            "Hay una nueva versión de la app disponible.\n\n"
            "¿Actualizar ahora? La app se cerrará, se actualizará y se reabrirá automáticamente."
        ):
            return
        from pathlib import Path
        updater = Path(__file__).resolve().parent / "updater.py"
        if not updater.exists():
            messagebox.showerror("Error", f"No se encontró el updater en:\n{updater}")
            return
        try:
            import subprocess
            subprocess.Popen(
                [sys.executable, str(updater), "--relaunch-app"],
                start_new_session=True,
                cwd=str(updater.parent),
            )
        except Exception as ex:
            messagebox.showerror("Error al actualizar", f"No se pudo iniciar el updater:\n{ex}")
            return
        self._on_close()

    # ------------------ Cierre ------------------
    def _on_close(self):
        if self._closing:
            return
        self._closing = True
        self._save_all()
        try:
            if self._dev_reload_job is not None:
                self.after_cancel(self._dev_reload_job)
                self._dev_reload_job = None
        except Exception:
            pass
        try:
            if self._tunnel_watchdog_job is not None:
                self.after_cancel(self._tunnel_watchdog_job)
                self._tunnel_watchdog_job = None
        except Exception:
            pass
        try:
            if self._host_api is not None:
                self._host_api.stop()
        except Exception:
            pass
        try:
            if self._host_api_public is not None:
                self._host_api_public.stop()
        except Exception:
            pass
        try:
            self._stop_public_tunnel()
        except Exception:
            pass
        self.master.destroy()


def main():
    root = tk.Tk()
    _apply_theme(root)
    root.rowconfigure(0, weight=1)
    root.columnconfigure(0, weight=1)
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
