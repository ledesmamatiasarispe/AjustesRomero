# tab_ajuste.py
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import time
import re
import uuid
import threading
import queue
import math

from config import ELEMENTS, COLOR_OK, COLOR_FAIL, COLOR_WARN, TOL_NO_LIMITS, BG_ENTRY, FG, ACCENT
from utils import to_float, fmt, _norm, simulate_with_plan
from ce import ce_from_percent
from storage import DuplicateColadaError, append_history, load_history, save_alloys, load_furnace_state, save_furnace_state, clear_furnace_state
from widgets import ScrollFrame


class TabAjuste(ttk.Frame):
    DEFAULT_ADJUST = ["Carbón de grafito", "Silicio", "Acero 1010", "FeCr alto C"]
    CARBOMAX_AUTO_NAMES = ["Carbón de grafito", "Silicio", "Acero 1010"]
    CARBOMAX_POLL_SECONDS = 15.0
    CARBOMAX_AUTO_MAX_MASS_FACTOR = 1.25

    def __init__(self, master, alloys_model):
        super().__init__(master, padding=10)
        self.alloys = alloys_model

        self._auto_job = None
        self._busy = False
        self._save_cb = None
        self._thermal_source = None
        self._restoring = False
        self.ajustes_log = []  # ajustes de la colada actual
        self.carbon_log = []
        self.calc_log = []     # cálculos temporales (solo botón Calcular)
        self._calc_log_win = None
        self._calc_log_tree = None
        self._changes_win = None
        self._changes_idx = None
        self._alloy_cache = None
        self._ajustes_sorted = []
        self._ajustes_id_index = {}
        self._carbomax_poll_running = False
        self._carbomax_last_poll_monotonic = 0.0
        self._carbomax_last_consumed = ""
        self._carbomax_consumed_paths = set()
        self._carbomax_pending_record = None
        self._carbomax_auto_armed_at = None
        self._view_mode = False
        self._view_restore_state = None
        self._view_hidden_buttons = []
        self._view_disabled_widgets = []
        self._view_session_ended_at = None
        self._view_hidden_panes = []
        self._view_history_index = None
        self._graph_zoom = 1.0
        self._graph_pan_dx = 0.0
        self._graph_pan_dy = 0.0
        self._graph_last_data = None
        self._graph_drag_start = None
        self.show_blue_stat_points = tk.BooleanVar(value=False)
        self.show_orange_stat_points = tk.BooleanVar(value=False)

        # ---------- CONFIG GRID PRINCIPAL ----------
        # Fila 0: barra superior
        # Fila 1: pan_cols con 5 paneles (Actual, Estimado, Objetivo, Materiales, Grafico)
        # Fila 2: Historial (tabla + botones)
        # Fila 3: Botonera inferior (calcular, aplicar, etc.)
        self.grid_rowconfigure(1, weight=4)
        self.grid_rowconfigure(2, weight=2)
        self.grid_columnconfigure(0, weight=1)

        # ---------- Top bar (fila 0) ----------
        self.mass = tk.StringVar(value="1000")
        top = ttk.Frame(self)
        top.grid(row=0, column=0, sticky="ew", pady=(0, 8))
        top.grid_columnconfigure(99, weight=1)

        ttk.Label(top, text="Masa del baño (kg):").pack(side="left")
        self.mass_entry = ttk.Entry(top, textvariable=self.mass, width=10)
        self.mass_entry.pack(side="left", padx=5)
        self.mass_entry.bind("<KeyRelease>", lambda e: (self._schedule_auto(), self._fire_save()))

        ttk.Label(top, text="Aleación actual:", padding=(20, 0)).pack(side="left")
        ttk.Button(top, text="Cargar desde catálogo...",
                   command=lambda: (self.pick_actual(), self._fire_save())).pack(side="left")

        ttk.Label(top, text="Aleación objetivo (Aleación propia):", padding=(20, 0)).pack(side="left")
        self.cb_obj = ttk.Combobox(top, values=self._own_alloy_names(), width=28, state="readonly")
        self.cb_obj.pack(side="left", padx=5)
        self.cb_obj.bind("<<ComboboxSelected>>", self._on_objective_selected)
        if not self.cb_obj["values"]:
            messagebox.showinfo("Objetivo", "No hay 'Aleación propia' en el Catálogo. Creá una y volvé a esta pestaña.")

        ttk.Label(top, text="N° colada:", padding=(20, 0)).pack(side="left")
        self.colada = tk.StringVar(value="")  # solo "NNNN /YY"
        ttk.Label(top, textvariable=self.colada).pack(side="left", padx=4)
        ttk.Button(top, text="Editar...", command=self.edit_colada).pack(side="left")
        self.session_started_at = None
        self.session_start_var = tk.StringVar(value="Inicio: -")
        self.session_elapsed_var = tk.StringVar(value="Transcurrido: -")
        ttk.Label(top, textvariable=self.session_start_var, padding=(14, 0)).pack(side="left")
        ttk.Label(top, textvariable=self.session_elapsed_var, padding=(10, 0)).pack(side="left")

        # ===================== fila 1: 5 columnas redimensionables =====================
        pan_cols = ttk.Panedwindow(self, orient="horizontal")
        pan_cols.grid(row=1, column=0, sticky="nsew", pady=(0, 8))
        self.pan_cols = pan_cols
        self._pan_cols_sash_positions = []
        self._pan_cols_restore_pending = []
        pan_cols.bind("<ButtonRelease-1>", lambda _e: self._save_pan_cols_positions())

        # = Pane A (Actual)
        paneA = ttk.Frame(pan_cols)
        pan_cols.add(paneA)
        try:
            pan_cols.paneconfigure(paneA, weight=1, minsize=240)
        except Exception:
            pass

        boxA = ttk.LabelFrame(paneA, text="Aleación actual (%)", padding=6)
        boxA.pack(fill="both", expand=True)
        self.ceA = tk.Label(boxA, text="CE actual: -", anchor="w", bg=BG_ENTRY, fg=FG, padx=6, pady=2)
        self.ceA.pack(anchor="w", padx=2, pady=(2, 0))
        self.sfA = ScrollFrame(boxA)
        self.sfA.pack(fill="both", expand=True)
        headA = ttk.Frame(self.sfA.inner)
        headA.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Label(headA, text="Elemento", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=6)
        ttk.Label(headA, text="% actual", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, padx=6)
        self.actual_rows = []
        for i, el in enumerate(ELEMENTS, start=1):
            r = ttk.Frame(self.sfA.inner)
            r.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            ttk.Label(r, text=el, width=6).grid(row=0, column=0, padx=4)
            e = ttk.Entry(r, width=12)
            e.grid(row=0, column=1, padx=4)
            e.bind("<KeyRelease>", lambda _e: (self._recalc_fe_actual(), self._schedule_auto(), self._schedule_graph_update(), self._fire_save()))
            self.actual_rows.append((el, e))

        # = Pane E (Estimado)
        paneE = ttk.Frame(pan_cols)
        pan_cols.add(paneE)
        try:
            pan_cols.paneconfigure(paneE, weight=1, minsize=240)
        except Exception:
            pass

        boxE = ttk.LabelFrame(paneE, text="Estimado con ajuste (%)", padding=6)
        boxE.pack(fill="both", expand=True)
        self.ceE = tk.Label(boxE, text="CE estimado: -", anchor="w", bg=BG_ENTRY, fg=FG, padx=6, pady=2)
        self.ceE.pack(anchor="w", padx=2, pady=(2, 0))
        self.massE = ttk.Label(boxE, text="Masa estimada (efectiva): - kg")
        self.massE.pack(anchor="w", padx=2, pady=(0, 4))
        self.sfE = ScrollFrame(boxE)
        self.sfE.pack(fill="both", expand=True)
        headE = ttk.Frame(self.sfE.inner)
        headE.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Label(headE, text="Elemento", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=6)
        ttk.Label(headE, text="% estimado", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, padx=6)
        self.est_rows = []
        for i, el in enumerate(ELEMENTS, start=1):
            r = ttk.Frame(self.sfE.inner)
            r.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            ttk.Label(r, text=el, width=6).grid(row=0, column=0, padx=4)
            t = tk.Entry(r, width=12, state="readonly", readonlybackground=ACCENT,
                         fg=FG, bg=ACCENT, insertbackground=FG)
            t.grid(row=0, column=1, padx=4)
            self.est_rows.append((el, t))

        # = Pane T (Objetivo)
        paneT = ttk.Frame(pan_cols)
        pan_cols.add(paneT)
        try:
            pan_cols.paneconfigure(paneT, weight=1, minsize=240)
        except Exception:
            pass

        boxT = ttk.LabelFrame(paneT, text="Aleación objetivo (%)", padding=6)
        boxT.pack(fill="both", expand=True)
        self.ceT = tk.Label(boxT, text="CE objetivo: -", anchor="w", bg=BG_ENTRY, fg=FG, padx=6, pady=2)
        self.ceT.pack(anchor="w", padx=2, pady=(2, 0))
        self.sfT = ScrollFrame(boxT)
        self.sfT.pack(fill="both", expand=True)
        headT = ttk.Frame(self.sfT.inner)
        headT.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Label(headT, text="Elemento", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=6)
        ttk.Label(headT, text="% objetivo", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, padx=6)
        ttk.Label(headT, text="min", font=("Segoe UI", 10, "bold")).grid(row=0, column=2, padx=6)
        ttk.Label(headT, text="max", font=("Segoe UI", 10, "bold")).grid(row=0, column=3, padx=6)
        self.target_rows = []
        for i, el in enumerate(ELEMENTS, start=1):
            r = ttk.Frame(self.sfT.inner)
            r.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            ttk.Label(r, text=el, width=6).grid(row=0, column=0, padx=4)
            t_obj = ttk.Entry(r, width=10, state="readonly")
            t_min = ttk.Entry(r, width=8, state="readonly")
            t_max = ttk.Entry(r, width=8, state="readonly")
            t_obj.grid(row=0, column=1, padx=4)
            t_min.grid(row=0, column=2, padx=4)
            t_max.grid(row=0, column=3, padx=4)
            self.target_rows.append((el, t_obj, t_min, t_max))

        # = Pane M (Materiales de ajuste)
        paneM = ttk.Frame(pan_cols)
        pan_cols.add(paneM)
        try:
            pan_cols.paneconfigure(paneM, weight=1, minsize=260)
        except Exception:
            pass

        self.adjust_panel = ttk.LabelFrame(paneM, text="Materiales de ajuste (kg)", padding=8)
        self.adjust_panel.pack(fill="both", expand=True)
        ttk.Button(self.adjust_panel, text="Elegir materiales de ajuste...",
                   command=self._open_adjusters_dialog).pack(anchor="w", pady=(0, 6))
        self.adjust_scroller = ScrollFrame(self.adjust_panel)
        self.adjust_scroller.pack(fill="both", expand=True)
        self.adjust_list_area = self.adjust_scroller.inner

        # = Pane G (Grafico)
        paneG = ttk.Frame(pan_cols)
        pan_cols.add(paneG)
        try:
            pan_cols.paneconfigure(paneG, weight=1, minsize=240)
        except Exception:
            pass

        self.graph_panel = ttk.LabelFrame(paneG, text="Grafico", padding=8)
        self.graph_panel.pack(fill="both", expand=True)
        self.graph_canvas = tk.Canvas(self.graph_panel, background="#ffffff", highlightthickness=0)
        self.graph_canvas.pack(fill="both", expand=True)
        self.graph_canvas.bind("<Configure>", lambda _e: self._schedule_graph_update())
        self.graph_canvas.bind("<MouseWheel>", self._on_graph_mousewheel)
        self.graph_canvas.bind("<Button-4>", self._on_graph_mousewheel)
        self.graph_canvas.bind("<Button-5>", self._on_graph_mousewheel)
        self.graph_canvas.bind("<ButtonPress-1>", self._on_graph_drag_start)
        self.graph_canvas.bind("<B1-Motion>", self._on_graph_drag_move)
        self.graph_canvas.bind("<ButtonRelease-1>", self._on_graph_drag_end)
        self.graph_canvas.bind("<Double-Button-1>", self._reset_graph_view)
        self._pan_cols_panes = [paneA, paneE, paneT, paneM, paneG]
        self._graph_req_seq = 0
        self._graph_drawn_seq = 0
        self._graph_jobs = queue.Queue()
        self._graph_results = queue.Queue()
        self._graph_thread = threading.Thread(target=self._graph_worker_loop, daemon=True)
        self._graph_thread.start()
        self.after(150, self._poll_graph_results)

        # Sashes iniciales para 5 paneles
        def _place_sashes_cols():
            try:
                if self._restore_pan_cols_positions():
                    return
                w = pan_cols.winfo_width()
                pan_cols.sashpos(0, int(w * 0.20))
                pan_cols.sashpos(1, int(w * 0.40))
                pan_cols.sashpos(2, int(w * 0.60))
                pan_cols.sashpos(3, int(w * 0.80))
            except Exception:
                pass
        self.after(350, _place_sashes_cols)

        # ===================== fila 2: Historial =====================
        hist_section = ttk.LabelFrame(self, text="Ajustes de la colada (resumen)", padding=6)
        hist_section.grid(row=2, column=0, sticky="nsew")

        self.tree_hist = ttk.Treeview(hist_section, columns=("fecha", "objetivo", "cambios", "resumen"),
                                      show="headings", height=8)
        for cid, title, w in (("fecha", "Fecha/Hora", 160),
                              ("objetivo", "Objetivo", 160),
                              ("cambios", "Cambios", 120),
                              ("resumen", "Materiales", 500)):
            self.tree_hist.heading(cid, text=title)
            self.tree_hist.column(cid, width=w, anchor="w")
        self.tree_hist.pack(fill="both", expand=True)
        self.tree_hist.bind("<Double-Button-1>", lambda e: self._open_selected_changes())

        hist_btns = ttk.Frame(hist_section)
        hist_btns.pack(fill="x", pady=(6, 0))
        ttk.Button(hist_btns, text="Editar ajuste", command=self._edit_selected_adjustment).pack(side="left")
        ttk.Button(hist_btns, text="Eliminar ajuste", command=self._delete_selected_adjustment).pack(side="left", padx=6)
        ttk.Button(hist_btns, text="Ver cálculos", command=self._open_calc_log).pack(side="right")

        # ---------- fila 3: Controles inferiores ----------
        side = ttk.Frame(self)
        side.grid(row=3, column=0, sticky="ew", pady=(8, 0))
        side.grid_columnconfigure(0, weight=1)

        left_opts = ttk.Frame(side)
        left_opts.pack(side="left")
        self.auto_est = tk.BooleanVar(value=False)
        ttk.Checkbutton(left_opts, text="Auto-estimar", variable=self.auto_est,
                        command=lambda: (self._schedule_auto(), self._fire_save())).pack(side="left")
        self.carbomax_auto = tk.BooleanVar(value=False)
        ttk.Checkbutton(left_opts, text="Modo Carbomax automático", variable=self.carbomax_auto,
                        command=self._on_carbomax_auto_toggle).pack(side="left", padx=(10, 0))

        ttk.Label(left_opts, text="Método", padding=(10, 0)).pack(side="left")
        self.method = tk.StringVar(value="Greedy")
        self.cb_method = ttk.Combobox(left_opts, textvariable=self.method,
                                      values=("Greedy", "Lineal"),
                                      state="readonly", width=10)
        self.cb_method.pack(side="left", padx=6)
        self.cb_method.bind("<<ComboboxSelected>>", lambda e: (self._schedule_auto(), self._fire_save()))

        ttk.Label(left_opts, text="Progreso (%)", padding=(10, 0)).pack(side="left")
        self.partial_pct = tk.IntVar(value=30)
        s = ttk.Scale(left_opts, from_=1, to=100, orient="horizontal",
                      variable=self.partial_pct, length=160)
        s.pack(side="left", padx=6)
        self.lbl_partial = ttk.Label(left_opts, text="30%")
        self.lbl_partial.pack(side="left")
        self.partial_pct.trace_add(
            "write",
            lambda *_: (
                self.lbl_partial.config(text=f"{int(self.partial_pct.get())}%"),
                self._schedule_auto(),
                self._fire_save()
            )
        )

        for pct in (30, 50, 75, 100):
            ttk.Button(left_opts, text=f"{pct}%", width=4,
                       command=lambda p=pct: self.partial_pct.set(p)).pack(side="left", padx=2)

        btns = ttk.Frame(side)
        btns.pack(side="right")
        self.btn_calcular = ttk.Button(
            btns,
            text="Calcular",
            command=lambda: self.estimate_to_target(show_message=False, reset_kgs=True, log_it=False, log_calc=True),
        )
        self.btn_calcular.pack(side="left")
        ttk.Button(btns, text="Calculadora de composicion por dilucion",
                   command=self.open_dilution_calculator).pack(side="left", padx=(6, 0))
        self.btn_calcular_pct = ttk.Button(btns, text="Calcular %", command=self.calculate_partial)
        self.btn_calcular_pct.pack(side="left", padx=6)
        self.btn_aplicar = ttk.Button(btns, text="Aplicar", command=self.apply_adjustment)
        self.btn_aplicar.pack(side="left")
        ttk.Button(btns, text="Cancelar sesión", command=self.cancel_session_start).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Guardar sesión", command=self.save_current_session).pack(side="left", padx=6)
        ttk.Button(btns, text="Limpiar kg",
                   command=lambda: (self.clear_adjust_kgs(), self._fire_save())).pack(side="left", padx=(6, 0))
        ttk.Button(btns, text="Reset ajuste", command=self.reset_adjustment).pack(side="left", padx=(6, 0))

        self.lbl_status = ttk.Label(self, text="", foreground="#444")
        self.lbl_status.grid(row=4, column=0, sticky="ew", pady=(3, 0))
        self.view_bar = ttk.Frame(self)
        self.view_label = ttk.Label(self.view_bar, text="", font=("Segoe UI", 10, "bold"))
        self.view_label.pack(side="left")
        self.view_points_frame = ttk.Frame(self.view_bar)
        self.view_points_frame.pack(side="left", padx=(16, 0))
        self.view_blue_points_chk = ttk.Checkbutton(
            self.view_points_frame,
            text="Puntos azul",
            variable=self.show_blue_stat_points,
            command=self._redraw_graph_view,
        )
        self.view_blue_points_chk.pack(side="left")
        self.view_orange_points_chk = ttk.Checkbutton(
            self.view_points_frame,
            text="Puntos naranja",
            variable=self.show_orange_stat_points,
            command=self._redraw_graph_view,
        )
        self.view_orange_points_chk.pack(side="left", padx=(8, 0))
        self.view_close_btn = ttk.Button(self.view_bar, text="Cerrar visualizacion", command=self.close_view_session)
        self.view_close_btn.pack(side="right")
        self.view_nav_frame = ttk.Frame(self.view_bar)
        self.view_nav_frame.pack(side="right", padx=(0, 6))
        self.view_prev_btn = ttk.Button(self.view_nav_frame, text="Sesion anterior", command=self.view_previous_session)
        self.view_prev_btn.pack(side="left")
        self.view_next_btn = ttk.Button(self.view_nav_frame, text="Siguiente sesion", command=self.view_next_session)
        self.view_next_btn.pack(side="left", padx=(6, 0))

        # --------- Datos iniciales de materiales / hist ----------
        self.kg_vars = {}
        self._ensure_adjusters_in_catalog()
        self.adjust_list = [n for n in self.DEFAULT_ADJUST if self._adjuster_alloy(n)]
        self._rebuild_adjust_ui()

        self._refresh_hist()

        self._update_objective_selector_state()
        self.calc_prediction()
        self._schedule_graph_update()
        self.after(300, self.ensure_colada)

    # ------------------------- estado / guardado -------------------------
    def refresh_objectives(self):
        # called when catalog changes
        self._alloy_cache = None
        values = self._own_alloy_names()
        prev = self.cb_obj.get().strip()
        self.cb_obj["values"] = values
        if prev and prev in values:
            self.cb_obj.set(prev)
            self.load_objective()
        else:
            self.cb_obj.set("")
            self.load_objective()
        self._update_objective_selector_state()
        # ajustar lista de materiales de ajuste si quedaron huérfanos
        self.adjust_list = [n for n in self.adjust_list if self._adjuster_alloy(n)]
        self._rebuild_adjust_ui()
        self._schedule_auto()
        self._schedule_graph_update()

    def set_save_callback(self, cb):
        self._save_cb = cb

    def set_thermal_source(self, source):
        self._thermal_source = source

    def _fire_save(self):
        if getattr(self, "_view_mode", False):
            return
        if self._save_cb and not self._restoring:
            self._save_cb()

    def _current_pan_cols_positions(self):
        if not hasattr(self, "pan_cols"):
            return []
        positions = []
        for idx in range(4):
            try:
                positions.append(int(self.pan_cols.sashpos(idx)))
            except Exception:
                break
        return positions

    def _save_pan_cols_positions(self):
        positions = self._current_pan_cols_positions()
        if len(positions) == 4 and positions != getattr(self, "_pan_cols_sash_positions", []):
            self._pan_cols_sash_positions = positions
            self._fire_save()

    def _restore_pan_cols_positions(self):
        positions = list(getattr(self, "_pan_cols_restore_pending", []) or [])
        if len(positions) != 4 or not hasattr(self, "pan_cols"):
            return False
        try:
            width = self.pan_cols.winfo_width()
            if width <= 1:
                self.after(100, self._restore_pan_cols_positions)
                return True
            min_gap = 80
            if width < min_gap * 5:
                return False
            cleaned = []
            prev = 0
            for idx, pos in enumerate(positions):
                min_allowed = prev + min_gap
                max_allowed = width - (min_gap * (4 - idx))
                pos = max(min_allowed, min(int(pos), max_allowed))
                cleaned.append(pos)
                prev = pos
            for idx, pos in enumerate(cleaned):
                self.pan_cols.sashpos(idx, pos)
            self._pan_cols_sash_positions = cleaned
            self._pan_cols_restore_pending = []
            return True
        except Exception:
            return False

    def get_state(self):
        if getattr(self, "_view_mode", False) and self._view_restore_state:
            return dict(self._view_restore_state)
        return {
            "mass": to_float(self.mass.get()),
            "actual": self._current_comp(),
            "objective": self.cb_obj.get().strip(),
            "adjust_list": list(self.adjust_list),
            "kg": {name: to_float(var.get()) for name, var in self.kg_vars.items()},
            "auto": bool(self.auto_est.get()),
            "carbomax_auto": bool(self.carbomax_auto.get()),
            "method": self.method.get(),
            "partial_pct": int(self.partial_pct.get()),
            "colada": self.colada.get(),  # solo "NNNN /YY"
            "session_started_at": self.session_started_at,
            "ajustes_log": self.ajustes_log,
            "calc_log": self.calc_log,
            "carbon_log": self.carbon_log,
            "carbomax_last_consumed": self._carbomax_last_consumed,
            "carbomax_consumed_paths": sorted(self._carbomax_consumed_paths),
            "carbomax_pending_record": self._carbomax_pending_record,
            "carbomax_auto_armed_at": self._carbomax_auto_armed_at,
            "pan_cols_sash_positions": self._current_pan_cols_positions() or getattr(self, "_pan_cols_sash_positions", []),
        }

    def set_state(self, st):
        if not st:
            return
        try:
            self._restoring = True
            self.mass.set(fmt(to_float(st.get("mass", 0))))
            actual = st.get("actual", {})
            for el, e in self.actual_rows:
                e.delete(0, tk.END)
                e.insert(0, fmt(to_float(actual.get(el, 0.0))))
            self._recalc_fe_actual()

            obj = st.get("objective", "")
            if obj and obj in list(self.cb_obj["values"]):
                self.cb_obj.set(obj)
                self.load_objective()

            adj = st.get("adjust_list", [])
            if adj:
                self.adjust_list = [n for n in adj if self._adjuster_alloy(n)]
                self._rebuild_adjust_ui()

            kg = st.get("kg", {})
            for name, var in self.kg_vars.items():
                var.set(fmt(to_float(kg.get(name, 0.0))))

            self.auto_est.set(bool(st.get("auto", False)))
            self.carbomax_auto.set(bool(st.get("carbomax_auto", False)))
            method = st.get("method", "Greedy")
            if method in ("Greedy", "Lineal"):
                self.method.set(method)
            self.partial_pct.set(int(st.get("partial_pct", 30)))

            self.colada.set(st.get("colada", ""))
            saved_sashes = st.get("pan_cols_sash_positions", [])
            if isinstance(saved_sashes, (list, tuple)):
                self._pan_cols_restore_pending = [int(to_float(pos)) for pos in saved_sashes if to_float(pos) > 0][:4]
                self._pan_cols_sash_positions = list(self._pan_cols_restore_pending)
            self.session_started_at = st.get("session_started_at", None)
            self.ajustes_log = st.get("ajustes_log", [])
            self._refresh_hist()
            self.calc_log = st.get("calc_log", [])
            carbon_log = st.get("carbon_log", [])
            self.carbon_log = carbon_log if isinstance(carbon_log, list) else []
            self._carbomax_last_consumed = str(st.get("carbomax_last_consumed", "") or "")
            consumed_paths = st.get("carbomax_consumed_paths", [])
            if isinstance(consumed_paths, (list, tuple, set)):
                self._carbomax_consumed_paths = {str(path).strip() for path in consumed_paths if str(path).strip()}
            else:
                self._carbomax_consumed_paths = set()
            if self._carbomax_last_consumed:
                self._carbomax_consumed_paths.add(self._carbomax_last_consumed)
            pending = st.get("carbomax_pending_record")
            self._carbomax_pending_record = pending if isinstance(pending, dict) else None
            self._carbomax_auto_armed_at = st.get("carbomax_auto_armed_at", None)
            if self.carbomax_auto.get() and not self._carbomax_auto_armed_at:
                self._carbomax_auto_armed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._refresh_session_timer_labels()
            self._update_objective_selector_state()
        finally:
            self._restoring = False
            self._schedule_auto()
            self._schedule_graph_update()
            self.after(150, self._restore_pan_cols_positions)
            if not getattr(self, "_view_mode", False):
                self.after(100, self._ensure_furnace_context_published)

    def _session_to_view_state(self, session):
        session = session if isinstance(session, dict) else {}
        ajustes = session.get("ajustes", []) if isinstance(session.get("ajustes", []), list) else []
        calculos = session.get("calculos", []) if isinstance(session.get("calculos", []), list) else []
        carbono = session.get("carbono", []) if isinstance(session.get("carbono", []), list) else []
        first = ajustes[0] if ajustes and isinstance(ajustes[0], dict) else {}
        last = ajustes[-1] if ajustes and isinstance(ajustes[-1], dict) else {}
        initial = first.get("inicial", {}) if isinstance(first.get("inicial", {}), dict) else {}
        final = last.get("estimado", {}) if isinstance(last.get("estimado", {}), dict) else {}
        actual_comp = initial.get("comp", {}) if isinstance(initial.get("comp", {}), dict) else {}
        mass = initial.get("masa", 0.0)
        kg_names = {}
        for adj in ajustes:
            mats = adj.get("materiales", {}) if isinstance(adj, dict) else {}
            if isinstance(mats, dict):
                for name in mats:
                    kg_names[str(name)] = 0.0
        return {
            "mass": to_float(mass),
            "actual": dict(actual_comp),
            "objective": str(session.get("objetivo") or first.get("objetivo") or "").strip(),
            "adjust_list": list(kg_names.keys()) or list(getattr(self, "adjust_list", [])),
            "kg": kg_names,
            "auto": False,
            "carbomax_auto": False,
            "method": self.method.get() if hasattr(self, "method") else "Greedy",
            "partial_pct": int(self.partial_pct.get()) if hasattr(self, "partial_pct") else 30,
            "colada": session.get("colada", ""),
            "session_started_at": session.get("started_at", None),
            "ajustes_log": list(ajustes),
            "calc_log": list(calculos),
            "carbon_log": list(carbono),
            "carbomax_last_consumed": "",
            "carbomax_consumed_paths": [],
            "carbomax_pending_record": None,
            "carbomax_auto_armed_at": None,
            "pan_cols_sash_positions": self._current_pan_cols_positions() or getattr(self, "_pan_cols_sash_positions", []),
        }

    def enter_view_session(self, session, history_index=None):
        if getattr(self, "_view_mode", False):
            self.close_view_session()
        self._view_restore_state = self.get_state()
        self._view_mode = True
        self._view_history_index = history_index
        self._view_session_ended_at = (session or {}).get("ended_at", None)
        self.set_state(self._session_to_view_state(session))
        title = f"Visualizando sesion: {session.get('colada', '')} | Objetivo: {session.get('objetivo', '')}"
        self._apply_view_mode_ui(title)
        self._update_view_nav_buttons()
        self._refresh_session_timer_labels()
        self._status("Modo visualizacion: la sesion historica no se puede modificar.")

    def close_view_session(self):
        restore_state = self._view_restore_state
        self._restore_view_mode_ui()
        self._view_mode = False
        self._view_restore_state = None
        self._view_session_ended_at = None
        self._view_history_index = None
        if restore_state:
            self.set_state(restore_state)
        self._status("Visualizacion cerrada.")

    def _load_view_history_index(self, index):
        try:
            sessions = load_history()
        except Exception:
            sessions = []
        if index is None or index < 0 or index >= len(sessions):
            return False
        restore_state = self._view_restore_state
        self._view_session_ended_at = sessions[index].get("ended_at", None)
        self._view_history_index = index
        self.set_state(self._session_to_view_state(sessions[index]))
        self._view_restore_state = restore_state
        title = f"Visualizando sesion: {sessions[index].get('colada', '')} | Objetivo: {sessions[index].get('objetivo', '')}"
        self._apply_view_mode_ui(title)
        self._update_view_nav_buttons()
        self._refresh_session_timer_labels()
        return True

    def view_previous_session(self):
        if not getattr(self, "_view_mode", False):
            return
        idx = self._view_history_index
        if idx is not None and self._load_view_history_index(idx - 1):
            return
        self._status("No hay sesion anterior para visualizar.")

    def view_next_session(self):
        if not getattr(self, "_view_mode", False):
            return
        idx = self._view_history_index
        if idx is not None and self._load_view_history_index(idx + 1):
            return
        self._status("No hay siguiente sesion para visualizar.")

    def _walk_widgets(self, widget):
        for child in widget.winfo_children():
            yield child
            yield from self._walk_widgets(child)

    def _apply_view_mode_ui(self, title):
        self.view_label.config(text=title)
        self._update_view_nav_buttons()
        self.view_bar.grid(row=4, column=0, sticky="ew", pady=(3, 4))
        self.lbl_status.grid(row=5, column=0, sticky="ew", pady=(3, 0))
        first_apply = not self._view_hidden_buttons and not self._view_disabled_widgets and not self._view_hidden_panes
        if first_apply:
            try:
                panes = list(getattr(self, "_pan_cols_panes", []) or [])
                graph_pane = panes[-1] if panes else None
                for idx, pane in enumerate(panes[:-1]):
                    try:
                        self._view_hidden_panes.append((idx, pane))
                        self.pan_cols.forget(pane)
                    except Exception:
                        pass
                if graph_pane is not None:
                    try:
                        self.pan_cols.paneconfigure(graph_pane, weight=1, minsize=320)
                    except Exception:
                        pass
            except Exception:
                pass
            self._apply_view_readonly_widgets()

    def _update_view_nav_buttons(self):
        try:
            sessions = load_history()
        except Exception:
            sessions = []
        idx = self._view_history_index
        prev_state = "normal" if isinstance(idx, int) and idx > 0 else "disabled"
        next_state = "normal" if isinstance(idx, int) and idx < len(sessions) - 1 else "disabled"
        try:
            self.view_prev_btn.configure(state=prev_state)
            self.view_next_btn.configure(state=next_state)
        except Exception:
            pass

    def _apply_view_readonly_widgets(self):
        for widget in self._walk_widgets(self):
            if widget in (
                self.view_close_btn,
                self.view_prev_btn,
                self.view_next_btn,
                self.view_bar,
                self.view_label,
                self.view_points_frame,
                self.view_blue_points_chk,
                self.view_orange_points_chk,
            ):
                continue
            if isinstance(widget, ttk.Button):
                manager = widget.winfo_manager()
                if not manager:
                    continue
                info = widget.pack_info() if manager == "pack" else widget.grid_info() if manager == "grid" else widget.place_info()
                self._view_hidden_buttons.append((widget, manager, info))
                if manager == "pack":
                    widget.pack_forget()
                elif manager == "grid":
                    widget.grid_remove()
                elif manager == "place":
                    widget.place_forget()
            elif isinstance(widget, (ttk.Entry, ttk.Combobox, ttk.Checkbutton, ttk.Scale, tk.Entry)):
                try:
                    self._view_disabled_widgets.append((widget, widget.cget("state")))
                    widget.configure(state="disabled")
                except Exception:
                    pass

    def _restore_view_mode_ui(self):
        try:
            hidden = sorted(getattr(self, "_view_hidden_panes", []), key=lambda item: item[0])
            for idx, pane in hidden:
                try:
                    self.pan_cols.insert(idx, pane)
                    self.pan_cols.paneconfigure(pane, weight=1, minsize=240 if idx < 3 else 260)
                except Exception:
                    try:
                        self.pan_cols.add(pane)
                    except Exception:
                        pass
            self._view_hidden_panes = []
            self.after(100, self._restore_pan_cols_positions)
        except Exception:
            pass
        for widget, state in getattr(self, "_view_disabled_widgets", []):
            try:
                widget.configure(state=state)
            except Exception:
                pass
        for widget, manager, info in getattr(self, "_view_hidden_buttons", []):
            try:
                if manager == "pack":
                    widget.pack(**info)
                elif manager == "grid":
                    widget.grid(**info)
                elif manager == "place":
                    widget.place(**info)
            except Exception:
                pass
        self._view_disabled_widgets = []
        self._view_hidden_buttons = []
        try:
            self.view_bar.grid_remove()
            self.lbl_status.grid(row=4, column=0, sticky="ew", pady=(3, 0))
        except Exception:
            pass

    # ------------------------------- grafico C/Si --------------------------
    def _graph_worker_loop(self):
        while True:
            snapshot = self._graph_jobs.get()
            try:
                while True:
                    snapshot = self._graph_jobs.get_nowait()
            except queue.Empty:
                pass
            try:
                target = snapshot.get("target", {}) or {}
                current = snapshot.get("current", {}) or {}
                adjustments = snapshot.get("adjustments", []) or []
                transitions = []
                plot_points = []
                for idx, item in enumerate(adjustments, start=1):
                    if not isinstance(item, dict):
                        continue
                    initial = item.get("initial", {}) or {}
                    final = item.get("final", {}) or {}
                    if not isinstance(initial, dict) or not isinstance(final, dict):
                        continue
                    start = {
                        "kind": "initial",
                        "label": str(idx),
                        "c": to_float(initial.get("C", 0.0)),
                        "si": to_float(initial.get("Si", 0.0)),
                    }
                    end = {
                        "kind": "final",
                        "label": str(idx),
                        "c": to_float(final.get("C", 0.0)),
                        "si": to_float(final.get("Si", 0.0)),
                    }
                    transitions.append({"label": str(idx), "start": start, "end": end})
                    plot_points.extend([start, end])
                current_point = {
                    "kind": "current",
                    "label": "Actual",
                    "c": to_float(current.get("C", 0.0)),
                    "si": to_float(current.get("Si", 0.0)),
                }
                if not snapshot.get("view_mode"):
                    plot_points.append(current_point)
                estimated_point = None
                predicted = snapshot.get("predicted", {}) or {}
                if not snapshot.get("view_mode") and snapshot.get("has_live_prediction") and isinstance(predicted, dict):
                    estimated_point = {
                        "kind": "estimated",
                        "label": "Estimado",
                        "c": to_float(predicted.get("C", 0.0)),
                        "si": to_float(predicted.get("Si", 0.0)),
                    }
                    plot_points.append(estimated_point)

                target_c = to_float(target.get("C", 0.0))
                target_si = to_float(target.get("Si", 0.0))
                for pt in plot_points:
                    pt["dx"] = pt["c"] - target_c
                    pt["dy"] = pt["si"] - target_si

                stat_circles = self._graph_history_stat_circles(str(snapshot.get("objective_name", "") or "").strip())
                for st in stat_circles:
                    st["dx"] = to_float(st.get("c", 0.0)) - target_c
                    st["dy"] = to_float(st.get("si", 0.0)) - target_si
                    st["plot_points"] = [
                        {"dx": to_float(p.get("c", 0.0)) - target_c, "dy": to_float(p.get("si", 0.0)) - target_si}
                        for p in st.get("points", [])
                    ]
                    st["polygon"] = [
                        {"dx": to_float(p.get("dx", 0.0)) - target_c, "dy": to_float(p.get("dy", 0.0)) - target_si}
                        for p in st.get("polygon", [])
                    ]
                step_delta = self._graph_history_step_delta_circle(str(snapshot.get("objective_name", "") or "").strip())
                step_circles = []
                for tr in transitions:
                    if step_delta:
                        end = tr.get("end", {})
                        step_circles.append({
                            "label": tr.get("label", ""),
                            "count": step_delta.get("count", 0),
                            "raw_count": step_delta.get("raw_count", 0),
                            "dx": (to_float(end.get("c", 0.0)) + to_float(step_delta.get("dc", 0.0))) - target_c,
                            "dy": (to_float(end.get("si", 0.0)) + to_float(step_delta.get("dsi", 0.0))) - target_si,
                            "major": step_delta.get("major", 0.03),
                            "minor": step_delta.get("minor", 0.03),
                            "angle": step_delta.get("angle", 0.0),
                            "plot_points": [
                                {
                                    "dx": (to_float(end.get("c", 0.0)) + to_float(p.get("dc", 0.0))) - target_c,
                                    "dy": (to_float(end.get("si", 0.0)) + to_float(p.get("dsi", 0.0))) - target_si,
                                }
                                for p in step_delta.get("points", [])
                            ],
                        })
                target_limit_area = snapshot.get("target_limit_area") or None
                max_abs = max(
                    [abs(pt["dx"]) for pt in plot_points]
                    + [abs(pt["dy"]) for pt in plot_points]
                    + [abs(st["dx"]) + self._graph_ellipse_extent(st)[0] for st in stat_circles]
                    + [abs(st["dy"]) + self._graph_ellipse_extent(st)[1] for st in stat_circles]
                    + [abs(st["dx"]) + self._graph_ellipse_extent(st)[0] for st in step_circles]
                    + [abs(st["dy"]) + self._graph_ellipse_extent(st)[1] for st in step_circles]
                    + ([to_float(target_limit_area.get("major", 0.0)), to_float(target_limit_area.get("minor", 0.0))] if isinstance(target_limit_area, dict) else [])
                    + [0.05]
                )
                span = max_abs * 1.20
                self._graph_results.put({
                    "seq": snapshot.get("seq", 0),
                    "has_objective": bool(snapshot.get("has_objective")),
                    "target_c": target_c,
                    "target_si": target_si,
                    "transitions": transitions,
                    "current": None if snapshot.get("view_mode") else current_point,
                    "estimated": estimated_point,
                    "target_limit_area": target_limit_area,
                    "stat_circles": stat_circles,
                    "step_circles": step_circles,
                    "span": span,
                })
            except Exception as ex:
                self._graph_results.put({
                    "seq": snapshot.get("seq", 0) if isinstance(snapshot, dict) else 0,
                    "error": str(ex),
                })

    def _graph_material_key(self, value):
        key = _norm(value)
        if key.startswith("mat") and key[3:].isdigit():
            return key[3:]
        return key

    def _graph_robust_points(self, points):
        if len(points) < 4:
            return points
        xs = sorted(p[0] for p in points)
        ys = sorted(p[1] for p in points)

        def median(vals):
            n = len(vals)
            mid = n // 2
            if n % 2:
                return vals[mid]
            return (vals[mid - 1] + vals[mid]) / 2

        mx = median(xs)
        my = median(ys)
        distances = sorted(((p[0] - mx) ** 2 + (p[1] - my) ** 2) ** 0.5 for p in points)
        md = median(distances)
        deviations = sorted(abs(d - md) for d in distances)
        mad = median(deviations)
        if mad <= 1e-12:
            limit = md + 0.05
        else:
            limit = md + (3.0 * 1.4826 * mad)
        filtered = [
            p for p in points
            if ((p[0] - mx) ** 2 + (p[1] - my) ** 2) ** 0.5 <= limit
        ]
        return filtered if filtered else points

    def _graph_circle_stats(self, points):
        if not points:
            return None
        raw_count = len(points)
        points = self._graph_robust_points(points)
        n = len(points)
        mx = sum(p[0] for p in points) / n
        my = sum(p[1] for p in points) / n
        if n == 1:
            major = minor = 0.03
            angle = 0.0
        else:
            var_x = sum((p[0] - mx) ** 2 for p in points) / n
            var_y = sum((p[1] - my) ** 2 for p in points) / n
            cov_xy = sum((p[0] - mx) * (p[1] - my) for p in points) / n
            trace = var_x + var_y
            diff = var_x - var_y
            root = ((diff * diff) + (4.0 * cov_xy * cov_xy)) ** 0.5
            lambda_major = max(0.0, (trace + root) / 2.0)
            lambda_minor = max(0.0, (trace - root) / 2.0)
            major = max(0.03, lambda_major ** 0.5)
            minor = max(0.03, lambda_minor ** 0.5)
            angle = 0.5 * math.atan2(2.0 * cov_xy, diff) if abs(cov_xy) > 1e-12 or abs(diff) > 1e-12 else 0.0
        return mx, my, major, minor, angle, n, raw_count, points

    def _graph_axis_deviation_stats(self, points):
        if not points:
            return None
        raw_count = len(points)
        points = self._graph_robust_points(points)
        n = len(points)
        mx = sum(p[0] for p in points) / n
        my = sum(p[1] for p in points) / n
        if n == 1:
            dev_x = dev_y = 0.03
        else:
            dev_x = sum(abs(p[0] - mx) for p in points) / n
            dev_y = sum(abs(p[1] - my) for p in points) / n
        major = max(0.03, dev_x)
        minor = max(0.03, dev_y)
        return mx, my, major, minor, 0.0, n, raw_count, points

    def _graph_hull_shape_stats(self, points):
        if not points:
            return None
        raw_count = len(points)
        points = self._graph_robust_points(points)
        n = len(points)
        mx = sum(p[0] for p in points) / n
        my = sum(p[1] for p in points) / n

        def cross(o, a, b):
            return ((a[0] - o[0]) * (b[1] - o[1])) - ((a[1] - o[1]) * (b[0] - o[0]))

        unique = sorted(set(points))
        if len(unique) <= 2:
            polygon = [{"dx": p[0], "dy": p[1]} for p in unique]
        else:
            lower = []
            for p in unique:
                while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                    lower.pop()
                lower.append(p)
            upper = []
            for p in reversed(unique):
                while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                    upper.pop()
                upper.append(p)
            hull = lower[:-1] + upper[:-1]
            margin = 0.02
            polygon = []
            for x, y in hull:
                vx = x - mx
                vy = y - my
                dist = (vx * vx + vy * vy) ** 0.5
                if dist > 1e-12:
                    x += (vx / dist) * margin
                    y += (vy / dist) * margin
                polygon.append({"dx": x, "dy": y})
        if len(polygon) < 3:
            major = minor = 0.03
            angle = 0.0
        else:
            xs = [to_float(p.get("dx", 0.0)) for p in polygon]
            ys = [to_float(p.get("dy", 0.0)) for p in polygon]
            major = max(0.03, max(abs(x - mx) for x in xs))
            minor = max(0.03, max(abs(y - my) for y in ys))
            angle = 0.0
        return mx, my, major, minor, angle, n, raw_count, points, polygon

    def _graph_ellipse_extent(self, item):
        major = to_float(item.get("major", item.get("radius", 0.03)))
        minor = to_float(item.get("minor", item.get("radius", 0.03)))
        angle = to_float(item.get("angle", 0.0))
        ca = math.cos(angle)
        sa = math.sin(angle)
        x_extent = ((major * ca) ** 2 + (minor * sa) ** 2) ** 0.5
        y_extent = ((major * sa) ** 2 + (minor * ca) ** 2) ** 0.5
        return max(0.03, x_extent), max(0.03, y_extent)

    def _graph_history_stat_circles(self, objective_name=""):
        grouped = {}
        objective_key = self._graph_material_key(objective_name)
        try:
            sessions = load_history()
        except Exception:
            sessions = []
        for session in sessions or []:
            if not isinstance(session, dict):
                continue
            adjustments = session.get("ajustes", [])
            if not isinstance(adjustments, list) or not adjustments:
                continue
            first = adjustments[0] if isinstance(adjustments[0], dict) else {}
            material = str(session.get("objetivo") or first.get("objetivo") or "").strip()
            if not material:
                continue
            if objective_key and self._graph_material_key(material) != objective_key:
                continue
            initial = ((first.get("inicial") or {}).get("comp") or {})
            if not isinstance(initial, dict):
                continue
            grouped.setdefault(material, []).append((
                to_float(initial.get("C", 0.0)),
                to_float(initial.get("Si", 0.0)),
            ))

        circles = []
        for material, points in grouped.items():
            stats = self._graph_hull_shape_stats(points)
            if not stats:
                continue
            mx, my, major, minor, angle, n, raw_count, used_points, polygon = stats
            circles.append({
                "material": material,
                "count": n,
                "raw_count": raw_count,
                "c": mx,
                "si": my,
                "major": major,
                "minor": minor,
                "angle": angle,
                "points": [{"c": p[0], "si": p[1]} for p in used_points],
                "polygon": polygon,
            })
        circles.sort(key=lambda item: (-item["count"], item["material"].lower()))
        return circles

    def _graph_history_step_delta_circle(self, objective_name=""):
        objective_key = self._graph_material_key(objective_name)
        points = []
        try:
            sessions = load_history()
        except Exception:
            sessions = []
        for session in sessions or []:
            if not isinstance(session, dict):
                continue
            adjustments = session.get("ajustes", [])
            if not isinstance(adjustments, list) or len(adjustments) < 2:
                continue
            first = adjustments[0] if isinstance(adjustments[0], dict) else {}
            material = str(session.get("objetivo") or first.get("objetivo") or "").strip()
            if not material:
                continue
            if objective_key and self._graph_material_key(material) != objective_key:
                continue
            for prev, nxt in zip(adjustments, adjustments[1:]):
                if not isinstance(prev, dict) or not isinstance(nxt, dict):
                    continue
                prev_final = ((prev.get("estimado") or {}).get("comp") or {})
                next_initial = ((nxt.get("inicial") or {}).get("comp") or {})
                if not isinstance(prev_final, dict) or not isinstance(next_initial, dict):
                    continue
                points.append((
                    to_float(next_initial.get("C", 0.0)) - to_float(prev_final.get("C", 0.0)),
                    to_float(next_initial.get("Si", 0.0)) - to_float(prev_final.get("Si", 0.0)),
                ))
        stats = self._graph_axis_deviation_stats(points)
        if not stats:
            return None
        dc, dsi, major, minor, angle, n, raw_count, used_points = stats
        return {
            "dc": dc,
            "dsi": dsi,
            "major": major,
            "minor": minor,
            "angle": angle,
            "count": n,
            "raw_count": raw_count,
            "points": [{"dc": p[0], "dsi": p[1]} for p in used_points],
        }

    def _schedule_graph_update(self):
        if not hasattr(self, "_graph_jobs"):
            return
        try:
            self._graph_req_seq += 1
            adjustments = []
            for it in sorted(getattr(self, "ajustes_log", []), key=lambda x: x.get("fecha", "")):
                initial = ((it.get("inicial") or {}).get("comp") or {})
                final = ((it.get("estimado") or {}).get("comp") or {})
                if initial and final:
                    adjustments.append({"initial": dict(initial), "final": dict(final)})
            predicted = {}
            if hasattr(self, "_predicted") and isinstance(getattr(self, "_predicted", None), tuple):
                predicted = dict((getattr(self, "_predicted", (None, {}))[1] or {}))
            has_live_prediction = any(to_float(var.get()) > 0 for var in getattr(self, "kg_vars", {}).values())
            self._graph_jobs.put_nowait({
                "seq": self._graph_req_seq,
                "has_objective": bool(self.cb_obj.get().strip()),
                "view_mode": bool(getattr(self, "_view_mode", False)),
                "objective_name": self.cb_obj.get().strip(),
                "target": self._target_comp(),
                "target_limit_area": self._graph_target_limit_area(),
                "current": self._current_comp(),
                "predicted": predicted,
                "has_live_prediction": has_live_prediction,
                "adjustments": adjustments,
            })
        except Exception:
            pass

    def _graph_target_limit_area(self):
        try:
            target = self._target_comp()
            if not target:
                return None
            c_bounds = self._graph_limit_bounds("C", target.get("C", 0.0))
            si_bounds = self._graph_limit_bounds("Si", target.get("Si", 0.0))
            if c_bounds is None and si_bounds is None:
                return None
            c_bounds = c_bounds or (-0.03, 0.03)
            si_bounds = si_bounds or (-0.03, 0.03)
            polygon = [
                {"dx": c_bounds[0], "dy": si_bounds[0]},
                {"dx": c_bounds[1], "dy": si_bounds[0]},
                {"dx": c_bounds[1], "dy": si_bounds[1]},
                {"dx": c_bounds[0], "dy": si_bounds[1]},
            ]

            ce_min, ce_max, ce_formula, ce_custom = self._objective_ce_data()
            ce_target = ce_from_percent(target, ce_formula, ce_custom)
            coeffs = self._ce_coeffs(ce_formula, ce_custom)
            c_coef = to_float(coeffs.get("C", 0.0))
            si_coef = to_float(coeffs.get("Si", 0.0))

            def clip_halfplane(poly, a, b, limit):
                if not poly:
                    return []

                def value(pt):
                    return (a * to_float(pt.get("dx", 0.0))) + (b * to_float(pt.get("dy", 0.0)))

                def intersect(p1, p2):
                    v1 = value(p1)
                    v2 = value(p2)
                    denom = v2 - v1
                    if abs(denom) <= 1e-12:
                        return dict(p2)
                    t = (limit - v1) / denom
                    return {
                        "dx": to_float(p1.get("dx", 0.0)) + t * (to_float(p2.get("dx", 0.0)) - to_float(p1.get("dx", 0.0))),
                        "dy": to_float(p1.get("dy", 0.0)) + t * (to_float(p2.get("dy", 0.0)) - to_float(p1.get("dy", 0.0))),
                    }

                out = []
                prev = poly[-1]
                prev_inside = value(prev) <= limit + 1e-12
                for curr in poly:
                    curr_inside = value(curr) <= limit + 1e-12
                    if curr_inside:
                        if not prev_inside:
                            out.append(intersect(prev, curr))
                        out.append(dict(curr))
                    elif prev_inside:
                        out.append(intersect(prev, curr))
                    prev = curr
                    prev_inside = curr_inside
                return out

            if abs(c_coef) > 1e-12 or abs(si_coef) > 1e-12:
                if ce_max is not None:
                    polygon = clip_halfplane(polygon, c_coef, si_coef, to_float(ce_max) - ce_target)
                if ce_min is not None:
                    polygon = clip_halfplane(polygon, -c_coef, -si_coef, -(to_float(ce_min) - ce_target))
            if len(polygon) < 3:
                return None
            x_extent = max(abs(to_float(pt.get("dx", 0.0))) for pt in polygon)
            y_extent = max(abs(to_float(pt.get("dy", 0.0))) for pt in polygon)
            return {
                "dx": 0.0,
                "dy": 0.0,
                "major": max(0.001, x_extent),
                "minor": max(0.001, y_extent),
                "angle": 0.0,
                "polygon": polygon,
            }
        except Exception:
            return None

    def _graph_limit_bounds(self, element, target_value):
        mn, mx = self._objective_limits(element)
        has_min = mn is not None
        has_max = mx is not None
        if not has_min and not has_max:
            return None
        target_value = to_float(target_value)
        lower = to_float(mn) - target_value if has_min else -0.03
        upper = to_float(mx) - target_value if has_max else 0.03
        if lower > upper:
            lower, upper = upper, lower
        return (lower, upper)

    def _graph_limit_radius(self, element, target_value):
        mn, mx = self._objective_limits(element)
        distances = []
        if mn is not None:
            distances.append(abs(to_float(mn) - to_float(target_value)))
        if mx is not None:
            distances.append(abs(to_float(mx) - to_float(target_value)))
        return max(distances) if distances else None

    def _poll_graph_results(self):
        latest = None
        try:
            while True:
                latest = self._graph_results.get_nowait()
        except queue.Empty:
            pass
        if latest and latest.get("seq", 0) >= self._graph_drawn_seq:
            self._graph_drawn_seq = latest.get("seq", 0)
            self._draw_graph(latest)
        try:
            self.after(150, self._poll_graph_results)
        except Exception:
            pass

    def _draw_graph(self, data):
        self._graph_last_data = data
        if not hasattr(self, "graph_canvas"):
            return
        c = self.graph_canvas
        c.delete("all")
        w = max(c.winfo_width(), 220)
        h = max(c.winfo_height(), 180)
        if data.get("error"):
            c.create_text(w / 2, h / 2, text=f"Error grafico: {data.get('error')}", fill="#8a1f1f")
            return
        if not data.get("has_objective"):
            c.create_text(w / 2, h / 2, text="Seleccione aleacion objetivo", fill="#666666")
            return

        left, right, top, bottom = 42, 18, 22, 36
        x0, x1 = left, w - right
        y0, y1 = top, h - bottom
        cx = (x0 + x1) / 2
        cy = (y0 + y1) / 2
        plot_w = max(1, x1 - x0)
        plot_h = max(1, y1 - y0)
        span = max(to_float(data.get("span")), 0.05) / max(0.1, to_float(getattr(self, "_graph_zoom", 1.0)))
        pan_dx = to_float(getattr(self, "_graph_pan_dx", 0.0))
        pan_dy = to_float(getattr(self, "_graph_pan_dy", 0.0))

        c.create_rectangle(x0, y0, x1, y1, outline="#d5d5d5", fill="#ffffff")
        for step in (-1.0, -0.5, 0.5, 1.0):
            gx = cx + step * (plot_w / 2)
            gy = cy - step * (plot_h / 2)
            c.create_line(gx, y0, gx, y1, fill="#eeeeee")
            c.create_line(x0, gy, x1, gy, fill="#eeeeee")
        zero_x = cx - (pan_dx / span) * (plot_w / 2)
        zero_y = cy + (pan_dy / span) * (plot_h / 2)
        c.create_line(x0, zero_y, x1, zero_y, fill="#333333", width=2)
        c.create_line(zero_x, y0, zero_x, y1, fill="#333333", width=2)

        tick = span / 2
        target_c = to_float(data.get("target_c"))
        target_si = to_float(data.get("target_si"))
        c.create_text(x0 + 2, zero_y + 12, text=f"{target_c + pan_dx - span:.3f}", anchor="w", fill="#666666", font=("Segoe UI", 8))
        c.create_text(cx + (plot_w / 4), zero_y + 12, text=f"{target_c + pan_dx + tick:.3f}", fill="#666666", font=("Segoe UI", 8))
        c.create_text(cx - (plot_w / 4), zero_y + 12, text=f"{target_c + pan_dx - tick:.3f}", fill="#666666", font=("Segoe UI", 8))
        c.create_text(x1 - 2, zero_y + 12, text=f"{target_c + pan_dx + span:.3f}", anchor="e", fill="#666666", font=("Segoe UI", 8))
        c.create_text(zero_x + 6, y0 + 8, text=f"{target_si + pan_dy + span:.3f}", anchor="w", fill="#666666", font=("Segoe UI", 8))
        c.create_text(zero_x + 6, y1 - 8, text=f"{target_si + pan_dy - span:.3f}", anchor="w", fill="#666666", font=("Segoe UI", 8))

        c.create_text((x0 + x1) / 2, h - 12, text="C (%)", fill="#222222", font=("Segoe UI", 9))
        c.create_text(12, (y0 + y1) / 2, text="Si (%)", fill="#222222", font=("Segoe UI", 9), angle=90)
        c.create_text(x0 + 4, y0 + 4,
                      text=f"centro = obj C {fmt(target_c, 4)} / Si {fmt(target_si, 4)}",
                      anchor="nw", fill="#555555", font=("Segoe UI", 8))

        def xy(pt):
            px = cx + ((to_float(pt.get("dx")) - pan_dx) / span) * (plot_w / 2)
            py = cy - ((to_float(pt.get("dy")) - pan_dy) / span) * (plot_h / 2)
            return px, py

        def draw_ellipse(center_dx, center_dy, major, minor, angle, outline, dash):
            px = cx + ((to_float(center_dx) - pan_dx) / span) * (plot_w / 2)
            py = cy - ((to_float(center_dy) - pan_dy) / span) * (plot_h / 2)
            scale_x = plot_w / (2 * span)
            scale_y = plot_h / (2 * span)
            ca = math.cos(to_float(angle))
            sa = math.sin(to_float(angle))
            coords = []
            for i in range(64):
                t = (2.0 * math.pi * i) / 64
                ex = (to_float(major) * math.cos(t) * ca) - (to_float(minor) * math.sin(t) * sa)
                ey = (to_float(major) * math.cos(t) * sa) + (to_float(minor) * math.sin(t) * ca)
                coords.extend([px + ex * scale_x, py - ey * scale_y])
            c.create_polygon(coords, outline=outline, fill="", width=2, dash=dash, smooth=True)
            x_extent, y_extent = self._graph_ellipse_extent({"major": major, "minor": minor, "angle": angle})
            rx = max(6, x_extent * scale_x)
            ry = max(6, y_extent * scale_y)
            return px, py, rx, ry

        target_area = data.get("target_limit_area") or {}
        if target_area:
            polygon = target_area.get("polygon", [])
            coords = []
            for pt in polygon:
                px_pt, py_pt = xy(pt)
                coords.extend([px_pt, py_pt])
            if len(coords) >= 6:
                c.create_polygon(coords, outline="#2e7d32", fill="#e8f5e9", width=2, dash=(6, 3))
            px, py = xy({"dx": 0.0, "dy": 0.0})
            rx = max(6, self._graph_ellipse_extent(target_area)[0] * (plot_w / (2 * span)))
            c.create_text(px + rx + 4, py, text="limites objetivo", anchor="w", fill="#2e7d32", font=("Segoe UI", 8))

        for st in data.get("stat_circles", []):
            polygon = st.get("polygon", [])
            coords = []
            for pt in polygon:
                px_pt, py_pt = xy(pt)
                coords.extend([px_pt, py_pt])
            if len(coords) >= 6:
                c.create_polygon(coords, outline="#7e57c2", fill="", width=2, dash=(4, 3), smooth=True)
                px, py = xy(st)
                rx = max(6, self._graph_ellipse_extent(st)[0] * (plot_w / (2 * span)))
            else:
                px, py, rx, _ry = draw_ellipse(
                    st.get("dx", 0.0), st.get("dy", 0.0),
                    st.get("major", 0.03), st.get("minor", 0.03), st.get("angle", 0.0),
                    "#7e57c2", (4, 3)
                )
            if self.show_blue_stat_points.get():
                for pt in st.get("plot_points", []):
                    ptx, pty = xy(pt)
                    c.create_oval(ptx - 2, pty - 2, ptx + 2, pty + 2, fill="#1e88e5", outline="")
            count = int(st.get("count", 0) or 0)
            raw_count = int(st.get("raw_count", count) or count)
            count_label = str(count) if raw_count == count else f"{count}/{raw_count}"
            label = f"{st.get('material', '')} ({count_label})"
            c.create_text(px + rx + 4, py, text=label, anchor="w", fill="#5e35b1", font=("Segoe UI", 8))

        for st in data.get("step_circles", []):
            px, py, rx, _ry = draw_ellipse(
                st.get("dx", 0.0), st.get("dy", 0.0),
                st.get("major", 0.03), st.get("minor", 0.03), st.get("angle", 0.0),
                "#fb8c00", (2, 3)
            )
            if self.show_orange_stat_points.get():
                for pt in st.get("plot_points", []):
                    ptx, pty = xy(pt)
                    c.create_oval(ptx - 2, pty - 2, ptx + 2, pty + 2, fill="#fb8c00", outline="")
            count = int(st.get("count", 0) or 0)
            raw_count = int(st.get("raw_count", count) or count)
            count_label = str(count) if raw_count == count else f"{count}/{raw_count}"
            c.create_text(px + rx + 4, py, text=f"sig {st.get('label', '')} ({count_label})",
                          anchor="w", fill="#e65100", font=("Segoe UI", 8))

        for tr in data.get("transitions", []):
            start = tr.get("start", {})
            end = tr.get("end", {})
            sx, sy = xy(start)
            ex, ey = xy(end)
            label = str(tr.get("label", ""))
            c.create_line(sx, sy, ex, ey, fill="#555555", width=2, arrow=tk.LAST, arrowshape=(10, 12, 4))
            c.create_oval(sx - 5, sy - 5, sx + 5, sy + 5, fill="#e53935", outline="#7f1715", width=2)
            c.create_oval(ex - 5, ey - 5, ex + 5, ey + 5, fill="#1e88e5", outline="#0d47a1", width=2)
            lx = ex + 8 if ex >= sx else ex - 8
            anchor = "w" if ex >= sx else "e"
            c.create_text(lx, ey, text=label, anchor=anchor, fill="#111111", font=("Segoe UI", 9, "bold"))

        current = data.get("current") or {}
        estimated = data.get("estimated") or {}
        if current and estimated:
            sx, sy = xy(current)
            ex, ey = xy(estimated)
            c.create_line(sx, sy, ex, ey, fill="#2e7d32", width=2, arrow=tk.LAST, arrowshape=(10, 12, 4))
            c.create_oval(ex - 6, ey - 6, ex + 6, ey + 6,
                          fill="#43a047", outline="#1b5e20", width=2)
            c.create_text(ex + 8, ey + 8, text="Estimado", anchor="nw", fill="#1b5e20", font=("Segoe UI", 8, "bold"))
        if current:
            px, py = xy(current)
            radius = 6
            c.create_oval(px - radius, py - radius, px + radius, py + radius,
                          fill="#ffd200", outline="#6f5c00", width=2)
            c.create_text(px + 8, py - 8, text="Actual", anchor="sw", fill="#333333", font=("Segoe UI", 8, "bold"))

    def _redraw_graph_view(self):
        if getattr(self, "_graph_last_data", None):
            self._draw_graph(self._graph_last_data)

    def _on_graph_mousewheel(self, event):
        old_zoom = max(0.1, to_float(getattr(self, "_graph_zoom", 1.0)))
        if getattr(event, "num", None) == 5 or getattr(event, "delta", 0) < 0:
            factor = 1 / 1.15
        else:
            factor = 1.15
        new_zoom = max(0.2, min(12.0, old_zoom * factor))
        if abs(new_zoom - old_zoom) <= 1e-12:
            return "break"
        self._graph_zoom = new_zoom
        self._redraw_graph_view()
        return "break"

    def _on_graph_drag_start(self, event):
        self._graph_drag_start = (event.x, event.y, to_float(self._graph_pan_dx), to_float(self._graph_pan_dy))

    def _on_graph_drag_move(self, event):
        if not self._graph_drag_start or not getattr(self, "_graph_last_data", None):
            return
        start_x, start_y, base_dx, base_dy = self._graph_drag_start
        c = self.graph_canvas
        w = max(c.winfo_width(), 220)
        h = max(c.winfo_height(), 180)
        plot_w = max(1, w - 42 - 18)
        plot_h = max(1, h - 22 - 36)
        span = max(to_float(self._graph_last_data.get("span")), 0.05) / max(0.1, to_float(self._graph_zoom))
        self._graph_pan_dx = base_dx - ((event.x - start_x) / plot_w) * (2 * span)
        self._graph_pan_dy = base_dy + ((event.y - start_y) / plot_h) * (2 * span)
        self._redraw_graph_view()

    def _on_graph_drag_end(self, _event):
        self._graph_drag_start = None

    def _reset_graph_view(self, _event=None):
        self._graph_zoom = 1.0
        self._graph_pan_dx = 0.0
        self._graph_pan_dy = 0.0
        self._redraw_graph_view()
        return "break"

    # ------------------------------- helpers generales ----------------------
    def _status(self, msg):
        try:
            self.lbl_status.config(text=msg or "")
        except Exception:
            pass

    def _schedule_auto(self):
        if getattr(self, "_view_mode", False):
            if self._auto_job is not None:
                try:
                    self.after_cancel(self._auto_job)
                except Exception:
                    pass
                self._auto_job = None
            return
        try:
            delay_ms = int(getattr(self.winfo_toplevel(), "_auto_refresh_ms", 250))
        except Exception:
            delay_ms = 250
        if delay_ms < 100:
            delay_ms = 100
        if self._auto_job is not None:
            try:
                self.after_cancel(self._auto_job)
            except Exception:
                pass
        self._auto_job = self.after(delay_ms, self._auto_run)

    def _refresh_session_timer_labels(self):
        started_raw = self.session_started_at
        if not started_raw:
            self.session_start_var.set("Inicio: -")
            self.session_elapsed_var.set("Transcurrido: -")
            return
        try:
            started = datetime.fromisoformat(str(started_raw))
        except Exception:
            self.session_start_var.set(f"Inicio: {started_raw}")
            self.session_elapsed_var.set("Transcurrido: -")
            return
        self.session_start_var.set(f"Inicio: {started.strftime('%d/%m %H:%M')}")
        end_dt = None
        if getattr(self, "_view_mode", False) and self._view_session_ended_at:
            try:
                end_dt = datetime.fromisoformat(str(self._view_session_ended_at))
            except Exception:
                end_dt = None
        delta = (end_dt or datetime.now()) - started
        total_min = max(0, int(delta.total_seconds() // 60))
        hours = total_min // 60
        minutes = total_min % 60
        self.session_elapsed_var.set(f"Transcurrido: {hours} h {minutes:02d} min")

    def _update_objective_selector_state(self):
        try:
            top = self.winfo_toplevel()
            style = ttk.Style(top)
            alert_bg = getattr(top, "_highlight_bg", "#ffd966")
            alert_fg = getattr(top, "_highlight_fg", "#000000")
            style.configure(
                "ObjectiveRequired.TCombobox",
                fieldbackground=alert_bg,
                foreground=alert_fg,
                background=alert_bg,
                arrowcolor=alert_fg,
            )
            style.map(
                "ObjectiveRequired.TCombobox",
                fieldbackground=[("readonly", alert_bg), ("disabled", alert_bg), ("!disabled", alert_bg)],
                foreground=[("readonly", alert_fg), ("disabled", alert_fg), ("!disabled", alert_fg)],
            )
            self.cb_obj.configure(style="ObjectiveRequired.TCombobox" if not self.cb_obj.get().strip() else "TCombobox")
        except Exception:
            pass
        started = bool(self.cb_obj.get().strip())
        for btn in (
            getattr(self, "btn_calcular", None),
            getattr(self, "btn_calcular_pct", None),
            getattr(self, "btn_aplicar", None),
        ):
            if btn is None:
                continue
            try:
                btn.configure(state="normal" if started else "disabled")
            except Exception:
                pass

    def _clear_objective_selection(self):
        try:
            self.cb_obj.set("")
        except Exception:
            pass
        self.load_objective()
        self._update_objective_selector_state()

    def cancel_session_start(self):
        self.session_started_at = None
        self.carbon_log = []
        self._carbomax_last_consumed = ""
        self._carbomax_consumed_paths.clear()
        self._carbomax_pending_record = None
        self._clear_objective_selection()
        self._clear_furnace_snapshot()
        self._refresh_session_timer_labels()
        self._schedule_graph_update()
        self._fire_save()
        self._status("Inicio de sesión cancelado.")

    def _ensure_session_started_from_objective(self):
        name = self.cb_obj.get().strip()
        if not name:
            self._update_objective_selector_state()
            self._status("Seleccioná o modificá el material objetivo para iniciar la sesión.")
            return False
        if not self.session_started_at:
            self.session_started_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._refresh_session_timer_labels()
            self._update_objective_selector_state()
            self._schedule_auto()
            self._fire_save()
            self._status("Temporizador de sesión iniciado por material objetivo.")
        self._publish_furnace_context()
        return True

    def _require_started_session(self):
        return self._ensure_session_started_from_objective()

    def _on_objective_selected(self, _evt=None):
        self.load_objective()
        if self.cb_obj.get().strip():
            if self.session_started_at:
                self._status("Material objetivo actualizado. La sesión continúa.")
            else:
                self._ensure_session_started_from_objective()
        self._refresh_session_timer_labels()
        self._update_objective_selector_state()
        self._schedule_auto()
        if self.cb_obj.get().strip() and self.session_started_at:
            self._publish_furnace_context()
        self._schedule_graph_update()
        self._fire_save()

    def _auto_run(self):
        self._auto_job = None
        try:
            if self._busy:
                return
            if self.auto_est.get() and self.cb_obj.get().strip() and self.session_started_at:
                try:
                    self._busy = True
                    plan = self._estimate_core(reset_kgs=True, log_it=False, silent=True, return_plan=True)
                    if plan:
                        pct = max(1, min(100, int(self.partial_pct.get())))
                        p = pct / 100.0
                        plan_scaled = {k: v * p for k, v in plan.items()}
                        for name in plan_scaled.keys():
                            self._ensure_adjuster_present(name)
                        for v in self.kg_vars.values():
                            v.set("0")
                        for name, kg in plan_scaled.items():
                            self.kg_vars[name].set(fmt(kg, 3))
                finally:
                    self._busy = False
            self._maybe_consume_pending_carbomax()
            self._maybe_schedule_carbomax_auto()
            self.calc_prediction()
            self._maybe_auto_save_session()
            self._refresh_session_timer_labels()
        finally:
            self._schedule_auto()

    def _on_carbomax_auto_toggle(self):
        if self.carbomax_auto.get():
            if not self._carbomax_auto_armed_at:
                self._carbomax_auto_armed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            self._carbomax_last_poll_monotonic = 0.0
            self._status("Carbomax automatico armado; esperando analisis Carbono.")
        else:
            self._carbomax_auto_armed_at = None
            self._carbomax_pending_record = None
            self._status("Carbomax automatico desactivado.")
        self._schedule_auto()
        self._fire_save()

    def _maybe_schedule_carbomax_auto(self):
        if not self.carbomax_auto.get():
            return
        if self._thermal_source is None or self._carbomax_poll_running:
            return
        if not self.session_started_at and not self._carbomax_auto_armed_at:
            self._carbomax_auto_armed_at = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        now = time.monotonic()
        if now - self._carbomax_last_poll_monotonic < self.CARBOMAX_POLL_SECONDS:
            return
        self._carbomax_last_poll_monotonic = now
        self._carbomax_poll_running = True
        try:
            consumed_paths = set(self._carbomax_consumed_paths)
            if self._carbomax_last_consumed:
                consumed_paths.add(self._carbomax_last_consumed)
            started = self._thermal_source.poll_latest_carbon_async(
                self.session_started_at or self._carbomax_auto_armed_at,
                sorted(consumed_paths),
                self._on_carbomax_poll_result,
            )
            if not started:
                self._carbomax_poll_running = False
                self._carbomax_last_poll_monotonic = 0.0
        except Exception as ex:
            self._carbomax_poll_running = False
            self._status(f"Carbomax automático: {ex}")

    def _maybe_consume_pending_carbomax(self):
        pending = self._carbomax_pending_record
        if not pending or not self.carbomax_auto.get():
            return
        if not self._ensure_carbomax_session_context(pending, interactive=False):
            return
        record = pending
        self._carbomax_pending_record = None
        self._consume_carbomax_record(record)

    def _on_carbomax_poll_result(self, record, error=None):
        self._carbomax_poll_running = False
        if error:
            self._status(f"Carbomax automático: {error}")
            return
        if not record:
            return
        try:
            if not self.cb_obj.get().strip():
                self._carbomax_pending_record = record
                self._status("Carbomax automatico: carbono capturado, esperando material objetivo.")
                self._fire_save()
                return
            if not self._ensure_carbomax_session_context(record, interactive=True):
                self._carbomax_pending_record = record
                self._status("Carbomax automático: carbono capturado, esperando material objetivo.")
                self._fire_save()
                return
            self._consume_carbomax_record(record)
        except Exception as ex:
            self._status(f"Carbomax automático: {ex}")

    def _ensure_carbomax_session_context(self, record, interactive):
        if not self.colada.get().strip():
            try:
                self.ensure_colada()
            except Exception:
                pass
        if not self.cb_obj.get().strip():
            if not interactive:
                return False
            objective = self._select_alloy_name(
                title="Material objetivo para Carbomax",
                only_type="Aleación propia",
            )
            if not objective:
                return False
            self.cb_obj.set(objective)
            self.load_objective()
        if not self._ensure_session_started_from_objective():
            return False
        self._fire_save()
        return True

    def _consume_carbomax_record(self, record):
        record_key = self._carbomax_record_key(record)
        record_keys = self._carbomax_record_keys(record)
        if record_keys and record_keys.intersection(self._carbomax_consumed_paths):
            self._carbomax_pending_record = None
            return
        if not self._carbomax_record_belongs_to_session(record):
            self._mark_carbomax_consumed(record_keys or record_key)
            self._carbomax_pending_record = None
            self._status("Carbomax automÃ¡tico: se omitio un analisis anterior al inicio de la sesion.")
            self._fire_save()
            return
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        carbon = to_float(info.get("C %") or info.get("Carbono %"))
        silicon = to_float(info.get("Si %") or info.get("Silicio %"))
        if carbon <= 0 and silicon <= 0:
            raise ValueError("análisis Carbono sin C/Si utilizables")
        source_name = str(payload.get("name", "") or record.get("name", "") or info.get("ID", "") or "Carbomax").strip()
        self.load_carbon_silicon(carbon, silicon, source_label=source_name)
        base_names = [name for name in self.CARBOMAX_AUTO_NAMES if self._adjuster_alloy(name)]
        if len(base_names) < 3:
            raise ValueError("faltan materiales base C/Si/Fe para el modo Carbomax automático")
        plan = self._estimate_core(
            reset_kgs=True,
            log_it=False,
            log_calc=False,
            silent=True,
            return_plan=True,
            adjust_names_override=base_names,
        )
        if not plan:
            raise ValueError("no se pudo calcular el ajuste automático de C/Si")
        base_mass = self._bath_mass()
        predicted_mass = self._predicted_mass_for_plan(base_mass, plan)
        max_auto_mass = base_mass * self.CARBOMAX_AUTO_MAX_MASS_FACTOR
        if base_mass > 0 and predicted_mass > max_auto_mass:
            self._mark_carbomax_consumed(record_keys or record_key)
            self._carbomax_pending_record = None
            self.clear_adjust_kgs()
            self.calc_prediction()
            self._status(
                "Carbomax automatico bloqueado: el plan llevaria la masa "
                f"de {fmt(base_mass, 1)} kg a {fmt(predicted_mass, 1)} kg. "
                "Revisar C/Si o ajustar manualmente."
            )
            self._fire_save()
            return
        try:
            self._busy = True
            for v in self.kg_vars.values():
                v.set("0")
            for name in plan.keys():
                self._ensure_adjuster_present(name)
            for name, kg in plan.items():
                self.kg_vars[name].set(fmt(kg, 3))
            self.calc_prediction()
            self.apply_adjustment()
        finally:
            self._busy = False
        self._mark_carbomax_consumed(record_keys or record_key)
        self._log_carbon_record(record, carbon, silicon, source_name, record_key)
        self._carbomax_pending_record = None
        self._status(f"Carbomax automático aplicado desde {source_name}.")
        self._fire_save()

    def _predicted_mass_for_plan(self, base_mass, plan):
        mass = to_float(base_mass)
        for name, kg in (plan or {}).items():
            alloy = self._get_adjuster(name)
            if not alloy:
                continue
            mass += to_float(kg) * self._effective_total_perkg(alloy)
        return mass

    def _carbomax_record_key(self, record):
        keys = self._carbomax_record_keys(record)
        if not keys:
            return ""
        for key in keys:
            if key.startswith("local_id:"):
                return key
        return sorted(keys)[0]

    def _carbomax_record_keys(self, record):
        if not isinstance(record, dict):
            return set()
        payload = record.get("payload", {}) if isinstance(record.get("payload"), dict) else {}
        info = payload.get("info", {}) if isinstance(payload.get("info"), dict) else {}
        keys = set()
        for value in (
            record.get("path", ""),
            payload.get("path", ""),
            record.get("legacy_path", ""),
            payload.get("legacy_path", ""),
            record.get("identity", ""),
            payload.get("identity", ""),
        ):
            text = str(value or "").strip()
            if text:
                keys.add(text)
        for value in (record.get("local_id", ""), payload.get("local_id", "")):
            text = str(value or "").strip()
            if text:
                keys.add(text)
                keys.add(f"local_id:{text}")
        extractor_id = str(record.get("extractor_db_id", "") or payload.get("extractor_db_id", "") or "").strip()
        if extractor_id:
            keys.add(f"extractor:{extractor_id}")
        return keys

    def _mark_carbomax_consumed(self, record_key):
        if isinstance(record_key, (set, list, tuple)):
            keys = {str(key or "").strip() for key in record_key if str(key or "").strip()}
        else:
            keys = {str(record_key or "").strip()} if str(record_key or "").strip() else set()
        if not keys:
            return
        preferred = sorted(keys, key=lambda key: (not key.startswith("local_id:"), key))[0]
        self._carbomax_last_consumed = preferred
        self._carbomax_consumed_paths.update(keys)

    def _carbomax_record_belongs_to_session(self, record):
        started = self._parse_carbomax_datetime(self.session_started_at)
        armed = self._parse_carbomax_datetime(self._carbomax_auto_armed_at)
        if started and armed:
            started = min(started, armed)
        elif armed:
            started = armed
        if not started:
            return False
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        record_dt = (
            self._parse_carbomax_datetime(info.get("Dt Termino"))
            or self._parse_carbomax_datetime(info.get("Dt Inicio"))
            or self._parse_carbomax_datetime(record.get("modified", "") if isinstance(record, dict) else "")
        )
        if not record_dt:
            return False
        return record_dt >= started

    def _parse_carbomax_datetime(self, value):
        raw = str(value or "").strip()
        if not raw:
            return None
        for pattern in (
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M:%S",
            "%d/%m/%Y %H:%M",
            "%d/%m/%Y %H:%M:%S",
            "%Y-%m-%d",
            "%d/%m/%Y",
        ):
            try:
                return datetime.strptime(raw, pattern)
            except Exception:
                pass
        return None

    def _log_carbon_record(self, record, carbon, silicon, source_name, record_key):
        payload = record.get("payload", {}) if isinstance(record, dict) else {}
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        last_adjustment = self.ajustes_log[-1] if self.ajustes_log else {}
        entry = {
            "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "source_name": source_name,
            "record_key": record_key,
            "local_id": str(record.get("local_id", "") or payload.get("local_id", "") or "").strip(),
            "identity": str(record.get("identity", "") or payload.get("identity", "") or "").strip(),
            "path": str(record.get("path", "") or payload.get("path", "") or "").strip(),
            "legacy_path": str(record.get("legacy_path", "") or payload.get("legacy_path", "") or "").strip(),
            "carbomax_id": info.get("ID", ""),
            "carbono": to_float(carbon),
            "silicio": to_float(silicon),
            "modo": info.get("Modo", ""),
            "dt_inicio": info.get("Dt Inicio", ""),
            "dt_termino": info.get("Dt Termino", ""),
            "ce": to_float(info.get("CE %")),
            "tl": info.get("TL", ""),
            "ts": info.get("TS", ""),
            "tf": info.get("TF", ""),
            "ajuste_id": last_adjustment.get("id", ""),
            "ajuste_fecha": last_adjustment.get("fecha", ""),
            "ajuste_resumen": last_adjustment.get("resumen", ""),
        }
        self.carbon_log.append(entry)

    def clear_adjust_kgs(self):
        try:
            self._busy = True
            for v in self.kg_vars.values():
                v.set("0")
        finally:
            self._busy = False

    def reset_adjustment(self):
        try:
            self._busy = True
            self.mass.set("1000")
            for v in self.kg_vars.values():
                v.set("0")
            for _, t in self.est_rows:
                t.config(state="normal")
                t.delete(0, tk.END)
                t.config(state="readonly")
            self.ajustes_log = []
            self._refresh_hist()
            self.calc_log = []
            self.carbon_log = []
            self._predicted = None
            self._clear_furnace_snapshot()
            self._schedule_graph_update()
            self._status("Ajuste reiniciado.")
            self._fire_save()
        finally:
            self._busy = False

    def _reset_session_workspace(self, clear_furnace_snapshot=True):
        self.mass.set("1000")
        for _, e in self.actual_rows:
            e.config(state="normal")
            e.delete(0, tk.END)
        for _, t in self.est_rows:
            t.config(state="normal")
            t.delete(0, tk.END)
            t.config(state="readonly")
        for v in self.kg_vars.values():
            v.set("0")
        self.ajustes_log = []
        self.calc_log = []
        self.carbon_log = []
        self._predicted = None
        self.session_started_at = None
        self._carbomax_last_consumed = ""
        self._carbomax_consumed_paths.clear()
        self._carbomax_pending_record = None
        self._carbomax_auto_armed_at = None
        self._clear_objective_selection()
        if clear_furnace_snapshot:
            self._clear_furnace_snapshot()
        self._refresh_session_timer_labels()
        self._refresh_hist()
        self._refresh_calc_log_window()
        self.ceA.config(text="CE actual: -")
        self.ceE.config(text="CE estimado: -")
        self.massE.config(text="Masa estimada (efectiva): -")
        self._set_ce_widget_color(self.ceA, BG_ENTRY)
        self._set_ce_widget_color(self.ceE, BG_ENTRY)
        self._set_ce_widget_color(self.ceT, BG_ENTRY)
        self._schedule_graph_update()

    def _own_alloy_names(self):
        return [a["nombre"] for a in self.alloys if (a.get("tipo", "") == "Aleación propia")]

    def _alloys_named(self, name):
        if not name:
            return []
        if self._alloy_cache is None:
            cache = {}
            for alloy in self.alloys:
                cache.setdefault(alloy.get("nombre", ""), []).append(alloy)
            self._alloy_cache = cache
        items = list(self._alloy_cache.get(name, []))
        if not items:
            # Rebuild in case the catalog changed
            cache = {}
            for alloy in self.alloys:
                cache.setdefault(alloy.get("nombre", ""), []).append(alloy)
            self._alloy_cache = cache
            items = list(self._alloy_cache.get(name, []))
        return items

    def _alloy_by_name(self, name, prefer_type=None):
        items = self._alloys_named(name)
        if prefer_type:
            for alloy in items:
                if alloy.get("tipo", "") == prefer_type:
                    return alloy
        return items[0] if items else None

    def _objective_alloy(self):
        name = self.cb_obj.get()
        return self._alloy_by_name(name, prefer_type="Aleación propia") if name else None

    def _adjuster_alloy(self, name):
        items = self._alloys_named(name)
        for alloy in items:
            if bool(alloy.get("ajuste", False)) and alloy.get("tipo", "") != "Aleación final":
                return alloy
        for alloy in items:
            if alloy.get("tipo", "") != "Aleación final":
                return alloy
        return None

    def _objective_limits(self, element):
        a = self._objective_alloy()
        if not a:
            return (None, None)
        lim = (a.get("limites") or {}).get(element, {})
        return (lim.get("soft_min"), lim.get("soft_max"))

    def _objective_limits_full(self, element):
        a = self._objective_alloy()
        if not a:
            return (None, None)
        lim = (a.get("limites") or {}).get(element, {}) or {}
        return (lim.get("soft_min"), lim.get("soft_max"))

    def _objective_ce_data(self):
        a = self._objective_alloy()
        esp = (a or {}).get("especiales", {})
        frm = esp.get("CE_formula", "FUNDICION") or "FUNDICION"
        return (esp.get("CE_min", None), esp.get("CE_max", None), _norm(frm), esp.get("CE_custom", {}) or {})

    def _ce_coeffs(self, formula, custom_coefs=None):
        f = _norm(formula or "FUNDICION")
        if f in ("PERSONALIZADA", "CUSTOM", "PERSONAL"):
            coefs = {}
            for e in ELEMENTS:
                v = to_float((custom_coefs or {}).get(e, 0.0))
                if v != 0.0:
                    coefs[e] = v
            return coefs
        if f in ("FUNDICION", "FUNDICION GRIS", "CAST", "CASTIRON", "CAST_IRON", "FOUNDRY"):
            return {"C": 1.0, "Si": 1.0/3.0, "P": 1.0/3.0}
        if f == "CET":
            return {"C": 1.0, "Mn": 1.0/10.0, "Mo": 1.0/10.0, "Cr": 1.0/20.0, "Cu": 1.0/20.0, "Ni": 1.0/40.0}
        # IIW base (con opcion Si/24)
        coefs = {"C": 1.0, "Mn": 1.0/6.0, "Cr": 1.0/5.0, "Mo": 1.0/5.0, "V": 1.0/5.0, "Ni": 1.0/15.0, "Cu": 1.0/15.0}
        if f in ("IIW+SI/24", "IIW_SI", "IIW+SI"):
            coefs["Si"] = 1.0/24.0
        return coefs

    def _ce_impact_perkg(self, alloy, ce_coeffs):
        rend = to_float(alloy.get("rendimiento", 100.0)) / 100.0
        impact = 0.0
        comp = alloy.get("composicion", {}) or {}
        for e, coef in (ce_coeffs or {}).items():
            pct = to_float(comp.get(e, 0.0))
            if pct != 0.0:
                impact += abs(coef) * pct * rend
        return impact

    def _solve_linear(self, A, b):
        # Resuelve (A^T A) x = A^T b con eliminación gaussiana simple
        if not A or not A[0]:
            return None
        m = len(A)
        n = len(A[0])
        # Construir normal equations
        ATA = [[0.0 for _ in range(n)] for _ in range(n)]
        ATb = [0.0 for _ in range(n)]
        for i in range(n):
            for j in range(n):
                s = 0.0
                for k in range(m):
                    s += A[k][i] * A[k][j]
                ATA[i][j] = s
            sb = 0.0
            for k in range(m):
                sb += A[k][i] * b[k]
            ATb[i] = sb

        # Gauss
        for i in range(n):
            pivot = ATA[i][i]
            if abs(pivot) < 1e-12:
                return None
            inv = 1.0 / pivot
            for j in range(i, n):
                ATA[i][j] *= inv
            ATb[i] *= inv
            for r in range(n):
                if r == i:
                    continue
                factor = ATA[r][i]
                if abs(factor) < 1e-12:
                    continue
                for c in range(i, n):
                    ATA[r][c] -= factor * ATA[i][c]
                ATb[r] -= factor * ATb[i]
        return ATb

    def _effective_add_perkg(self, alloy, element):
        rend = to_float(alloy.get("rendimiento", 100.0)) / 100.0
        pct = to_float(alloy["composicion"].get(element, 0.0)) / 100.0
        return rend * pct

    def _effective_total_perkg(self, alloy):
        return to_float(alloy.get("rendimiento", 100.0)) / 100.0

    def _effective_add(self, alloy, kg):
        rend = self._effective_total_perkg(alloy)
        out = {e: 0.0 for e in ELEMENTS}
        for e in ELEMENTS:
            out[e] = kg * (to_float(alloy["composicion"].get(e, 0.0)) / 100.0) * rend
        return out

    def _pick_base_adjusters(self, adjust_names):
        # Selecciona materiales base de forma dinámica usando la lista de ajuste
        best_c = (None, 0.0)   # (alloy, %C)
        best_si = (None, 0.0)  # (alloy, %Si)
        best_fe = (None, -1.0) # (alloy, %Fe)
        for nm in adjust_names:
            a = self._adjuster_alloy(nm)
            if not a:
                continue
            comp = a.get("composicion", {}) or {}
            c = to_float(comp.get("C", 0.0))
            si = to_float(comp.get("Si", 0.0))
            fe = to_float(comp.get("Fe", 0.0))
            if c > best_c[1]:
                best_c = (a, c)
            if si > best_si[1]:
                best_si = (a, si)
            if fe > best_fe[1]:
                best_fe = (a, fe)
        return (best_c[0], best_si[0], best_fe[0])

    def _bath_mass(self):
        M = to_float(self.mass.get())
        if M <= 0:
            raise ValueError("La masa del baño debe ser > 0.")
        return M

    def _get_adjuster(self, name):
        a = self._adjuster_alloy(name)
        if not a:
            messagebox.showerror("Catálogo", f"No se encontró un material de ajuste válido para {name}.")
        return a

    # ----------------------- calculadora por dilucion -----------------------
    def open_dilution_calculator(self):
        win = tk.Toplevel(self)
        win.title("Calculadora de composicion por dilucion")
        win.transient(self)
        win.geometry("920x680")
        win.minsize(780, 560)

        root = ttk.Frame(win, padding=10)
        root.pack(fill="both", expand=True)

        top = ttk.LabelFrame(root, text="Masas", padding=8)
        top.pack(fill="x", pady=(0, 8))
        known_mass = tk.StringVar(value="")
        mass_total = tk.StringVar(value="")
        mode = tk.StringVar(value="A")

        known_mass_label = ttk.Label(top, text="Peso A (kg):")
        known_mass_label.pack(side="left")
        ttk.Entry(top, textvariable=known_mass, width=12).pack(side="left", padx=6)
        ttk.Label(top, text="Peso A+B (kg):").pack(side="left", padx=(16, 0))
        ttk.Entry(top, textvariable=mass_total, width=12).pack(side="left", padx=6)
        ttk.Radiobutton(top, text="Calcular composicion de A", variable=mode, value="A").pack(side="left", padx=(18, 0))
        ttk.Radiobutton(top, text="Calcular composicion de B", variable=mode, value="B").pack(side="left", padx=8)

        table = ttk.Frame(root)
        table.pack(fill="both", expand=True)
        mix_box = ttk.LabelFrame(table, text="Composicion medida de A+B (%)", padding=6)
        known_box = ttk.LabelFrame(table, text="Composicion conocida de B (%)", padding=6)
        result_box = ttk.LabelFrame(table, text="Resultado calculado (%)", padding=6)
        mix_box.grid(row=0, column=0, sticky="nsew", padx=(0, 6))
        known_box.grid(row=0, column=1, sticky="nsew", padx=6)
        result_box.grid(row=0, column=2, sticky="nsew", padx=(6, 0))
        for col in range(3):
            table.columnconfigure(col, weight=1)
        table.rowconfigure(0, weight=1)

        def build_column(parent, editable=True):
            sf = ScrollFrame(parent)
            sf.pack(fill="both", expand=True)
            rows = {}
            for i, el in enumerate(ELEMENTS):
                row = ttk.Frame(sf.inner)
                row.grid(row=i, column=0, sticky="ew", pady=1)
                ttk.Label(row, text=el, width=5).pack(side="left")
                var = tk.StringVar(value="")
                ent = ttk.Entry(row, textvariable=var, width=12)
                ent.pack(side="left", padx=4)
                if not editable:
                    ent.config(state="readonly")
                rows[el] = (var, ent)
            return rows

        mix_rows = build_column(mix_box, editable=True)
        known_rows = build_column(known_box, editable=True)
        result_rows = build_column(result_box, editable=False)
        status = tk.StringVar(value="")
        ttk.Label(root, textvariable=status, foreground="#555555").pack(fill="x", pady=(8, 0))

        def refresh_mode_labels(*_):
            if mode.get() == "A":
                known_mass_label.config(text="Peso A (kg):")
                known_box.config(text="Composicion conocida de B (%)")
                result_box.config(text="Composicion calculada de A (%)")
            else:
                known_mass_label.config(text="Peso B (kg):")
                known_box.config(text="Composicion conocida de A (%)")
                result_box.config(text="Composicion calculada de B (%)")

        mode.trace_add("write", refresh_mode_labels)
        refresh_mode_labels()

        def set_result(el, value):
            var, ent = result_rows[el]
            ent.config(state="normal")
            var.set("" if value == "" else fmt(value, 6))
            ent.config(state="readonly")

        def calculate():
            try:
                known = to_float(known_mass.get())
                mt = to_float(mass_total.get())
                if known <= 0:
                    raise ValueError("El peso conocido debe ser > 0.")
                if mt <= known:
                    raise ValueError("Peso A+B debe ser mayor que el peso conocido.")
                for el in ELEMENTS:
                    mix = to_float(mix_rows[el][0].get())
                    known_comp = to_float(known_rows[el][0].get())
                    if mode.get() == "A":
                        ma = known
                        mb = mt - ma
                        value = ((mix * mt) - (known_comp * mb)) / ma
                    else:
                        mb = known
                        ma = mt - mb
                        value = ((mix * mt) - (known_comp * ma)) / mb
                    set_result(el, value)
                if mode.get() == "A":
                    status.set(f"Calculado. Peso B = {fmt(mt - known, 3)} kg.")
                else:
                    status.set(f"Calculado. Peso A = {fmt(mt - known, 3)} kg.")
            except Exception as ex:
                messagebox.showerror("Dilucion", str(ex), parent=win)

        def clear():
            for rows in (mix_rows, known_rows):
                for var, _ent in rows.values():
                    var.set("")
            for el in ELEMENTS:
                set_result(el, "")
            status.set("")

        actions = ttk.Frame(root)
        actions.pack(fill="x", pady=(8, 0))
        ttk.Button(actions, text="Calcular", command=calculate).pack(side="right")
        ttk.Button(actions, text="Limpiar", command=clear).pack(side="right", padx=6)
        ttk.Button(actions, text="Cerrar", command=win.destroy).pack(side="right")

    # ------------------------------- UI auxiliares --------------------------
    def _rebuild_adjust_ui(self):
        for w in self.adjust_list_area.winfo_children():
            w.destroy()
        if not hasattr(self, "kg_vars"):
            self.kg_vars = {}

        old_vals = {name: self.kg_vars.get(name, tk.StringVar(value="0")).get()
                    for name in getattr(self, "adjust_list", [])}
        self.kg_vars = {}

        if not self.adjust_list:
            ttk.Label(self.adjust_list_area, text="(Sin materiales de ajuste seleccionados)").pack(anchor="w")
        else:
            for name in self.adjust_list:
                fr = ttk.Frame(self.adjust_list_area)
                fr.pack(fill="x", pady=3)
                ttk.Label(fr, text=name, width=28).pack(side="left")
                v = tk.StringVar(value=old_vals.get(name, "0"))
                ent = ttk.Entry(fr, textvariable=v, width=10)
                ent.pack(side="left", padx=4)
                ent.bind("<KeyRelease>", lambda _e: (self.calc_prediction(), self._schedule_auto(), self._fire_save()))
                self.kg_vars[name] = v
        self._schedule_auto()

    def _ensure_adjusters_in_catalog(self):
        existing = set(a["nombre"] for a in self.alloys)
        to_add = []
        if "Carbón de grafito" not in existing:
            comp = {e: 0.0 for e in ELEMENTS}
            comp["C"] = 99.0
            to_add.append({
                "nombre": "Carbón de grafito",
                "tipo": "Aditivo",
                "rendimiento": 90.0,
                "costo": 0.0,
                "composicion": comp,
                "limites": {e: {"soft_min": None, "soft_max": None, "hard_min": None, "hard_max": None} for e in ELEMENTS},
                "especiales": {"CE_formula": "FUNDICION", "CE_min": None, "CE_max": None,
                               "CE_custom": {"C": 1.0, "Si": 1/3, "P": 1/3, "S": 0.0}},
                "ajuste": True
            })
        if "Silicio" not in existing:
            comp = {e: 0.0 for e in ELEMENTS}
            comp["Si"] = 100.0
            to_add.append({
                "nombre": "Silicio",
                "tipo": "Metal puro",
                "rendimiento": 90.0,
                "costo": 0.0,
                "composicion": comp,
                "limites": {e: {"soft_min": None, "soft_max": None, "hard_min": None, "hard_max": None} for e in ELEMENTS},
                "especiales": {"CE_formula": "FUNDICION", "CE_min": None, "CE_max": None,
                               "CE_custom": {"C": 1.0, "Si": 1/3, "P": 1/3, "S": 0.0}},
                "ajuste": True
            })
        if "Acero 1010" not in existing:
            comp = {e: 0.0 for e in ELEMENTS}
            comp.update({"C": 0.10, "Mn": 0.50, "P": 0.02, "S": 0.02})
            comp["Fe"] = max(0.0, 100.0 - sum(v for k, v in comp.items() if k != "Fe"))
            to_add.append({
                "nombre": "Acero 1010",
                "tipo": "Retorno",
                "rendimiento": 100.0,
                "costo": 0.0,
                "composicion": comp,
                "limites": {e: {"soft_min": None, "soft_max": None, "hard_min": None, "hard_max": None} for e in ELEMENTS},
                "especiales": {"CE_formula": "FUNDICION", "CE_min": None, "CE_max": None,
                               "CE_custom": {"C": 1.0, "Si": 1/3, "P": 1/3, "S": 0.0}},
                "ajuste": True
            })
        if "FeCr alto C" not in existing:
            comp = {e: 0.0 for e in ELEMENTS}
            comp.update({"Cr": 62.5, "C": 7.5, "Si": 1.5, "S": 0.03, "P": 0.03})
            comp["Fe"] = max(0.0, 100.0 - sum(v for k, v in comp.items() if k != "Fe"))
            to_add.append({
                "nombre": "FeCr alto C",
                "tipo": "Ferroaleación",
                "rendimiento": 90.0,
                "costo": 0.0,
                "composicion": comp,
                "limites": {e: {"soft_min": None, "soft_max": None, "hard_min": None, "hard_max": None} for e in ELEMENTS},
                "especiales": {"CE_formula": "FUNDICION", "CE_min": None, "CE_max": None,
                               "CE_custom": {"C": 1.0, "Si": 1/3, "P": 1/3, "S": 0.0}},
                "ajuste": True
            })
        if to_add:
            self.alloys.extend(to_add)
            save_alloys(self.alloys)

    def _ensure_adjuster_present(self, name):
        if name not in self.adjust_list:
            if not self._adjuster_alloy(name):
                self._status(f"'{name}' no es un material de ajuste válido en catálogo.")
                return False
            self.adjust_list.append(name)
            self._rebuild_adjust_ui()
            self._fire_save()
        return True

    def _open_adjusters_dialog(self):
        win = tk.Toplevel(self)
        win.title("Materiales de ajuste")
        win.transient(self)
        win.grab_set()
        win.geometry("628x676")
        win.resizable(False, False)
        style = ttk.Style(win)
        style.configure("AdjustDialog.TButton", padding=(4, 2))

        ttk.Label(win, text="Materiales de ajuste actuales:").pack(anchor="w", padx=10, pady=(10, 4))
        lb = tk.Listbox(win, selectmode=tk.EXTENDED, height=18)
        lb.pack(fill="both", expand=True, padx=10, pady=(0, 8))
        for n in self.adjust_list:
            lb.insert(tk.END, n)

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=10, pady=(0, 10))

        def refresh_from_adjust_list(selected=None):
            lb.delete(0, tk.END)
            for item in self.adjust_list:
                lb.insert(tk.END, item)
            for idx in selected or []:
                if 0 <= idx < lb.size():
                    lb.selection_set(idx)
            if selected:
                lb.see(selected[0])

        def do_add():
            valid_adjusters = sorted(
                {
                    a.get("nombre", "")
                    for a in self.alloys
                    if a.get("nombre", "") and a.get("tipo", "") != "Aleación final"
                },
                key=lambda val: (0, int(val)) if str(val).isdigit() else (1, str(val).lower()),
            )
            name = self._select_alloy_name(
                title="Agregar material de ajuste (desde catálogo)",
                names=valid_adjusters,
            )
            if not name:
                return
            if name in self.adjust_list:
                messagebox.showinfo("Agregar", f"'{name}' ya está en la lista.", parent=win)
                return
            if not self._adjuster_alloy(name):
                messagebox.showerror("Catálogo", f"'{name}' no es un material válido para ajuste.", parent=win)
                return
            self.adjust_list.append(name)
            refresh_from_adjust_list(selected=[len(self.adjust_list) - 1])
            self._rebuild_adjust_ui()
            self._fire_save()

        def do_del():
            sel = list(lb.curselection())
            if not sel:
                messagebox.showinfo("Eliminar", "Seleccioná uno o más materiales en la lista.", parent=win)
                return
            for i in reversed(sel):
                name = lb.get(i)
                if name in self.adjust_list:
                    self.adjust_list.remove(name)
            refresh_from_adjust_list()
            self._rebuild_adjust_ui()
            self._fire_save()

        def do_move(step):
            sel = list(lb.curselection())
            if not sel:
                messagebox.showinfo("Orden", "Seleccioná uno o más materiales para reordenar.", parent=win)
                return
            if step < 0 and sel[0] == 0:
                return
            if step > 0 and sel[-1] == lb.size() - 1:
                return
            items = list(self.adjust_list)
            if step < 0:
                for idx in sel:
                    items[idx - 1], items[idx] = items[idx], items[idx - 1]
                new_sel = [idx - 1 for idx in sel]
            else:
                for idx in reversed(sel):
                    items[idx + 1], items[idx] = items[idx], items[idx + 1]
                new_sel = [idx + 1 for idx in sel]
            self.adjust_list = items
            refresh_from_adjust_list(selected=new_sel)
            self._rebuild_adjust_ui()
            self._fire_save()

        ttk.Button(btns, text="Agregar nuevo material...", command=do_add, style="AdjustDialog.TButton").pack(side="left")
        ttk.Button(btns, text="Eliminar material de ajuste", command=do_del, style="AdjustDialog.TButton").pack(side="left", padx=6)
        ttk.Button(btns, text="Subir", command=lambda: do_move(-1), style="AdjustDialog.TButton").pack(side="left", padx=(18, 6))
        ttk.Button(btns, text="Bajar", command=lambda: do_move(1), style="AdjustDialog.TButton").pack(side="left")
        win.wait_window()

    # ---------------------------- selección actual --------------------------
    def _select_alloy_name(self, title="Seleccionar aleación", only_type=None, names=None):
        if names is None:
            names = [a["nombre"] for a in self.alloys if (only_type is None or a.get("tipo", "") == only_type)]
        names = list(dict.fromkeys([str(name).strip() for name in names if str(name).strip()]))
        sel = {"name": None}
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        win.grab_set()
        win.geometry("460x520")
        win.minsize(420, 480)
        win.resizable(False, False)

        tk.Label(win, text="Buscar:").pack(anchor="w", padx=8, pady=(8, 2))
        q = tk.StringVar()
        ent = ttk.Entry(win, textvariable=q)
        ent.pack(fill="x", padx=8)
        lb = tk.Listbox(win, height=14)
        lb.pack(fill="both", expand=True, padx=8, pady=8)

        def refresh_list():
            term = q.get().strip().lower()
            lb.delete(0, tk.END)
            for name in names:
                if term in name.lower():
                    lb.insert(tk.END, name)

        refresh_list()

        def accept():
            idx = lb.curselection()
            if not idx:
                messagebox.showinfo("Seleccionar", "Elegí una aleación.", parent=win)
                return
            sel["name"] = lb.get(idx[0])
            win.destroy()

        lb.bind("<Double-Button-1>", lambda _e: accept())
        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="Aceptar", command=accept).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side="right", padx=6)
        ent.bind("<Return>", lambda e: accept())
        ent.focus_set()
        q.trace_add("write", lambda *_: refresh_list())
        win.wait_window()
        return sel["name"]

    def pick_actual(self):
        name = self._select_alloy_name(title="Seleccionar aleación actual", only_type="Aleación propia")
        if name:
            self.load_actual_by_name(name)

    def load_actual_by_name(self, name):
        a = self._alloy_by_name(name, prefer_type="Aleación propia")
        for el, e in self.actual_rows:
            e.config(state="normal")
        if not a:
            for el, e in self.actual_rows:
                e.delete(0, tk.END)
            return
        for el, e in self.actual_rows:
            e.delete(0, tk.END)
            e.insert(0, fmt(a["composicion"].get(el, 0.0)))
        for el, t in self.est_rows:
            t.config(state="normal")
            t.delete(0, tk.END)
            t.config(state="readonly")
        self._recalc_fe_actual()
        self._schedule_auto()
        self._schedule_graph_update()
        if self.cb_obj.get().strip() and self.session_started_at:
            self._publish_furnace_context()
        self._fire_save()

    def load_carbon_silicon(self, carbon_pct, silicon_pct, source_label=""):
        values = {"C": to_float(carbon_pct), "Si": to_float(silicon_pct)}
        for el, e in self.actual_rows:
            if el not in values:
                continue
            e.config(state="normal")
            e.delete(0, tk.END)
            e.insert(0, fmt(values[el]))
        self._recalc_fe_actual()
        self._schedule_auto()
        self._schedule_graph_update()
        if self.cb_obj.get().strip() and self.session_started_at:
            self._publish_furnace_context()
        self._fire_save()
        src = f" desde {source_label}" if source_label else ""
        self._status(f"Composición actual actualizada{src}: C={fmt(values['C'])} / Si={fmt(values['Si'])}")

    # ------------------------------ objetivo --------------------------------
    def load_objective(self):
        a = self._objective_alloy()
        if not a:
            for el, t_obj, t_min, t_max in self.target_rows:
                for w in (t_obj, t_min, t_max):
                    w.config(state="normal")
                    w.delete(0, tk.END)
                    w.config(state="readonly")
            self.ceT.config(text="CE objetivo: -")
            self._set_ce_widget_color(self.ceT, BG_ENTRY)
            self._set_ce_widget_color(self.ceA, BG_ENTRY)
            self._set_ce_widget_color(self.ceE, BG_ENTRY)
            self._schedule_graph_update()
            return
        for el, t_obj, t_min, t_max in self.target_rows:
            t_obj.config(state="normal")
            t_min.config(state="normal")
            t_max.config(state="normal")
            t_obj.delete(0, tk.END)
            t_min.delete(0, tk.END)
            t_max.delete(0, tk.END)
            t_obj.insert(0, fmt(a["composicion"].get(el, 0.0)))
            mn, mx = self._objective_limits(el)
            if mn is not None:
                t_min.insert(0, fmt(mn))
            if mx is not None:
                t_max.insert(0, fmt(mx))
            t_obj.config(state="readonly")
            t_min.config(state="readonly")
            t_max.config(state="readonly")
        comp_tgt = {e: a["composicion"].get(e, 0.0) for e in ELEMENTS}
        ce_min, ce_max, ce_formula, ce_custom = self._objective_ce_data()
        ce_tgt = ce_from_percent(comp_tgt, ce_formula, ce_custom)
        smin = "" if ce_min is None else f" | min: {fmt(ce_min, 4)}"
        smax = "" if ce_max is None else f" | max: {fmt(ce_max, 4)}"
        self.ceT.config(text=f"CE objetivo ({ce_formula}): {fmt(ce_tgt, 4)}{smin}{smax}")
        ce_now = ce_from_percent(self._current_comp(), ce_formula, ce_custom)
        ce_est = ce_from_percent(getattr(self, "_predicted", (0.0, self._current_comp()))[1], ce_formula, ce_custom)
        self._apply_ce_colors(ce_now, ce_est, ce_tgt, ce_min, ce_max)
        self._schedule_graph_update()
        self._fire_save()

    # --------------------------- baño y colores -----------------------------
    def _current_comp(self):
        return {el: to_float(e.get()) for el, e in self.actual_rows}

    def _target_comp(self):
        out = {}
        for el, t_obj, *_ in self.target_rows:
            s = t_obj.get().strip().replace(",", ".")
            out[el] = float(s) if s else 0.0
        return out

    def _recalc_fe_actual(self):
        try:
            total_others, fe_entry = 0.0, None
            for el, e in self.actual_rows:
                if el == "Fe":
                    fe_entry = e
                else:
                    total_others += to_float(e.get())
            fe_val = max(0.0, 100.0 - total_others)
            if fe_entry is not None:
                fe_entry.delete(0, tk.END)
                fe_entry.insert(0, fmt(fe_val))
        except Exception:
            pass

    def _apply_estimated_colors(self, pred_pct):
        tgt = self._target_comp()
        for (el, t) in self.est_rows:
            val = pred_pct.get(el, 0.0)
            mn, mx = self._objective_limits(el)
            if mn is not None or mx is not None:
                bad = (mn is not None and val < mn - 1e-12) or (mx is not None and val > mx + 1e-12)
                color = COLOR_FAIL if bad else COLOR_OK
            else:
                color = COLOR_OK if abs(val - tgt.get(el, 0.0)) <= TOL_NO_LIMITS else COLOR_WARN
            try:
                t.config(state="normal")
                t.configure(readonlybackground=color)
                t.config(state="readonly")
            except Exception:
                pass

    def _ce_display_color(self, ce_val, ce_min, ce_max, ce_tgt):
        if ce_min is not None or ce_max is not None:
            bad = (ce_min is not None and ce_val < ce_min - 1e-12) or (ce_max is not None and ce_val > ce_max + 1e-12)
            return COLOR_FAIL if bad else COLOR_OK
        return COLOR_OK if abs(ce_val - ce_tgt) <= TOL_NO_LIMITS else COLOR_WARN

    def _ce_text_color(self, bg_color):
        try:
            bg = (bg_color or "").lstrip("#")
            if len(bg) != 6:
                return FG
            r = int(bg[0:2], 16)
            g = int(bg[2:4], 16)
            b = int(bg[4:6], 16)
            luminance = (0.299 * r) + (0.587 * g) + (0.114 * b)
            return "#000000" if luminance >= 160 else "#ffffff"
        except Exception:
            return FG

    def _set_ce_widget_color(self, widget, bg_color):
        try:
            widget.configure(bg=bg_color, fg=self._ce_text_color(bg_color))
        except Exception:
            pass

    def _apply_ce_colors(self, ce_now, ce_est, ce_tgt, ce_min, ce_max):
        self._set_ce_widget_color(self.ceA, self._ce_display_color(ce_now, ce_min, ce_max, ce_tgt))
        self._set_ce_widget_color(self.ceE, self._ce_display_color(ce_est, ce_min, ce_max, ce_tgt))
        self._set_ce_widget_color(self.ceT, BG_ENTRY)

    # ------------------------ cálculo continuo ------------------------------
    def calc_prediction(self):
        try:
            M = self._bath_mass()
            comp = self._current_comp()
            mass_e = {e: M * comp.get(e, 0.0) / 100.0 for e in ELEMENTS}
            add_total_eff = 0.0
            for name in getattr(self, "adjust_list", []):
                kg = to_float(self.kg_vars.get(name, tk.StringVar(value="0")).get())
                if kg <= 0:
                    continue
                a = self._get_adjuster(name)
                if not a:
                    continue
                eff = self._effective_add(a, kg)
                for e in ELEMENTS:
                    mass_e[e] += eff[e]
                add_total_eff += kg * self._effective_total_perkg(a)
            Mnew = M + add_total_eff
            pred_pct = {e: (100.0 * mass_e[e] / Mnew if Mnew > 0 else 0.0) for e in ELEMENTS}

            for el, t in self.est_rows:
                t.config(state="normal")
                t.delete(0, tk.END)
                t.insert(0, fmt(pred_pct.get(el, 0.0)))
                t.config(state="readonly")

            ce_min, ce_max, ce_formula, ce_custom = self._objective_ce_data()
            ce_now = ce_from_percent(self._current_comp(), ce_formula, ce_custom)
            ce_est = ce_from_percent(pred_pct, ce_formula, ce_custom)
            ce_tgt = ce_from_percent(self._target_comp(), ce_formula, ce_custom)
            self.ceA.config(text=f"CE actual ({ce_formula}): {fmt(ce_now, 4)}")
            self.ceE.config(text=f"CE estimado ({ce_formula}): {fmt(ce_est, 4)}")
            self.massE.config(text=f"Masa estimada (efectiva): {fmt(Mnew)} kg")
            self._apply_ce_colors(ce_now, ce_est, ce_tgt, ce_min, ce_max)
            self._apply_estimated_colors(pred_pct)
            self._predicted = (Mnew, pred_pct)
            self._schedule_graph_update()
        except Exception as ex:
            self._status(f"Error de cálculo: {ex}")

    # ----------------------- solver / planificación -------------------------
    def _solve_kg_for_target(self, M, m_elem, T_frac, add_elem_perkg, add_total_perkg):
        denom = add_elem_perkg - T_frac * add_total_perkg
        num = T_frac * M - m_elem
        if abs(denom) < 1e-12:
            return None
        return num / denom

    def estimate_to_target(self, show_message=True, reset_kgs=True, return_plan=False, log_it=False, log_calc=False):
        ok = self._estimate_core(reset_kgs=reset_kgs, log_it=log_it, log_calc=log_calc,
                                 silent=not show_message, return_plan=return_plan)
        if return_plan:
            return ok
        if not ok and show_message:
            messagebox.showerror("Estimar", "No se pudo calcular el plan. Revisá objetivo y materiales.")

    def _estimate_core(self, reset_kgs=True, log_it=False, log_calc=False, silent=False, return_plan=False, adjust_names_override=None):
        try:
            name = self.cb_obj.get().strip()
            if not name:
                self._status("Definí una aleación objetivo (propia).")
                return {} if return_plan else False
            if not self._ensure_session_started_from_objective():
                return {} if return_plan else False

            if reset_kgs:
                self.clear_adjust_kgs()

            M0 = self._bath_mass()
            comp0 = self._current_comp()
            masses = {e: M0 * comp0.get(e, 0.0) / 100.0 for e in ELEMENTS}
            M = M0

            tgt_pct = self._target_comp()
            # target base
            T_C = tgt_pct.get("C", 0.0) / 100.0
            T_Si = tgt_pct.get("Si", 0.0) / 100.0
            T_frac = {e: tgt_pct.get(e, 0.0) / 100.0 for e in ELEMENTS}

            adjust_names = list(adjust_names_override if adjust_names_override is not None else getattr(self, "adjust_list", []))
            a_graph, a_sil, a_steel = self._pick_base_adjusters(adjust_names)
            method = self.method.get() if hasattr(self, "method") else "Greedy"
            skip_csi = False
            if not skip_csi and not (a_graph and a_sil and a_steel):
                self._status("Faltan materiales base en la lista de ajuste (C/Si/Fe).")
                return {} if return_plan else False

            # 1) Subir elementos != C,Si,Fe con los materiales elegidos
            eps = 1e-12
            kg_other = {}
            missing_elems = []
            warn_msg = None
            ce_min, ce_max, ce_formula, ce_custom = self._objective_ce_data()
            ce_coeffs = self._ce_coeffs(ce_formula, ce_custom)
            other_adjusters = [n for n in adjust_names if n]
            best_for_elem = {}
            for el in [e for e in ELEMENTS if e not in ("C", "Si", "Fe")]:
                best_name = None
                best_rE = 0.0
                for nm in other_adjusters:
                    a = self._get_adjuster(nm)
                    if not a:
                        continue
                    rE = self._effective_add_perkg(a, el)
                    if rE > best_rE + 1e-16:
                        best_name = nm
                        best_rE = rE
                if best_name:
                    best_for_elem[el] = best_name
            if method == "Lineal":
                target_elems = [e for e in ELEMENTS if e not in ("C", "Si", "Fe") and (tgt_pct.get(e, 0.0) > 0)]
                mats = [nm for nm in other_adjusters if any(self._effective_add_perkg(self._get_adjuster(nm), e) > eps for e in target_elems)]
                if target_elems and mats:
                    A = []
                    b = []
                    for e in target_elems:
                        row = []
                        for nm in mats:
                            a = self._get_adjuster(nm)
                            row.append(self._effective_add_perkg(a, e))
                        A.append(row)
                        b.append(T_frac.get(e, 0.0) * M - masses[e])
                    sol = self._solve_linear(A, b)
                    if sol:
                        for nm, kg in zip(mats, sol):
                            if kg and kg > 0:
                                eff = self._effective_add(self._get_adjuster(nm), kg)
                                for e in ELEMENTS:
                                    masses[e] += eff[e]
                                M += kg * self._effective_total_perkg(self._get_adjuster(nm))
                                kg_other[nm] = kg_other.get(nm, 0.0) + kg
                # fallback greedy for elements not reached
                for el in [e for e in ELEMENTS if e not in ("C", "Si", "Fe")]:
                    T_E = tgt_pct.get(el, 0.0) / 100.0
                    if T_E <= 0:
                        continue
                    fE = masses[el] / M if M > 0 else 0.0
                    if fE < T_E - 1e-12:
                        nm = best_for_elem.get(el)
                        if not nm:
                            missing_elems.append(el)
                            continue
                        a = self._get_adjuster(nm)
                        if not a:
                            missing_elems.append(el)
                            continue
                        rE = self._effective_add_perkg(a, el)
                        rTOT = self._effective_total_perkg(a)
                        if rTOT <= 0 or rE <= eps:
                            missing_elems.append(el)
                            continue
                        k = self._solve_kg_for_target(M, masses[el], T_E, rE, rTOT)
                        if k is None or k <= 0:
                            missing_elems.append(el)
                            continue
                        eff = self._effective_add(a, k)
                        for e in ELEMENTS:
                            masses[e] += eff[e]
                        M += k * rTOT
                        kg_other[nm] = kg_other.get(nm, 0.0) + k
            else:
                for el in [e for e in ELEMENTS if e not in ("C", "Si", "Fe")]:
                    T_E = tgt_pct.get(el, 0.0) / 100.0
                    if T_E <= 0:
                        continue
                    fE = masses[el] / M if M > 0 else 0.0
                    if fE < T_E - 1e-12:
                        best_name, best_a, best_k, best_rTOT, best_rE = None, None, None, 0.0, None
                        best_group = 2
                        nm = best_for_elem.get(el)
                        if nm:
                            a = self._get_adjuster(nm)
                            if not a:
                                continue
                            rE = self._effective_add_perkg(a, el)
                            rTOT = self._effective_total_perkg(a)
                            if rTOT <= 0:
                                continue
                            if rE <= eps:
                                continue
                            impact = self._ce_impact_perkg(a, ce_coeffs)
                            group = 0 if impact <= 1e-9 else 1
                            k = self._solve_kg_for_target(M, masses[el], T_E, rE, rTOT)
                            if k is None or k <= 0:
                                continue
                            eff = self._effective_add(a, k)
                            Mnew = M + k * rTOT
                            ok = True
                            for e in ELEMENTS:
                                T_e = T_frac.get(e, 0.0)
                                if T_e > 0:
                                    f_new = (masses[e] + eff[e]) / Mnew if Mnew > 0 else 0.0
                                    if f_new > T_e + 1e-12:
                                        ok = False
                                        break
                            if not ok:
                                continue
                            if group > best_group:
                                continue
                            if group < best_group or best_rE is None or rE > best_rE + 1e-16 or (abs(rE - best_rE) <= 1e-16 and (best_k is None or k < best_k)):
                                best_group = group
                                best_name, best_a, best_k, best_rTOT, best_rE = nm, a, k, rTOT, rE
                        if best_a and best_k and best_k > 0:
                            eff = self._effective_add(best_a, best_k)
                            for e in ELEMENTS:
                                masses[e] += eff[e]
                            M += best_k * best_rTOT
                            kg_other[best_name] = kg_other.get(best_name, 0.0) + best_k
                        else:
                            missing_elems.append(el)

            if missing_elems:
                msg = "No hay material de ajuste que eleve sin pasarse para: " + ", ".join(missing_elems)
                if not silent:
                    messagebox.showwarning("Ajuste", msg + ". Crea un material nuevo en Catálogo.")
                warn_msg = msg
                self._status(msg)

            # 2) Bajar con acero si C/Si por encima
            kg_steel = kg_C = kg_Si = 0.0
            if not skip_csi:
                rTOT_s = self._effective_total_perkg(a_steel)
                rC_s = self._effective_add_perkg(a_steel, "C")
                rSi_s = self._effective_add_perkg(a_steel, "Si")
                rTOT_g = self._effective_total_perkg(a_graph)
                rC_g = self._effective_add_perkg(a_graph, "C")
                rTOT_si = self._effective_total_perkg(a_sil)
                rSi = self._effective_add_perkg(a_sil, "Si")

            def fracC():
                return masses["C"] / M if M > 0 else 0.0

            def fracSi():
                return masses["Si"] / M if M > 0 else 0.0

            def _pick_target_down(_el, T_base):
                return T_base

            def _pick_target_up(_el, T_base):
                return T_base

            if not skip_csi:
                T_C_down = _pick_target_down("C", T_C)
                T_Si_down = _pick_target_down("Si", T_Si)
                T_C_up = _pick_target_up("C", T_C)
                T_Si_up = _pick_target_up("Si", T_Si)

                need_down_C = fracC() > T_C_down + 1e-12
                need_down_Si = fracSi() > T_Si_down + 1e-12
                if need_down_C and need_down_Si:
                    kC = self._solve_kg_for_target(M, masses["C"], T_C_down, rC_s, rTOT_s)
                    kSi = self._solve_kg_for_target(M, masses["Si"], T_Si_down, rSi_s, rTOT_s)
                    k = max((kC or 0.0), (kSi or 0.0))
                    if k and k > 0:
                        eff = self._effective_add(a_steel, k)
                        for e in ELEMENTS:
                            masses[e] += eff[e]
                        M += k * rTOT_s
                        kg_steel += k
                elif need_down_C:
                    k = self._solve_kg_for_target(M, masses["C"], T_C_down, rC_s, rTOT_s)
                    if k and k > 0:
                        eff = self._effective_add(a_steel, k)
                        for e in ELEMENTS:
                            masses[e] += eff[e]
                        M += k * rTOT_s
                        kg_steel += k
                elif need_down_Si:
                    k = self._solve_kg_for_target(M, masses["Si"], T_Si_down, rSi_s, rTOT_s)
                    if k and k > 0:
                        eff = self._effective_add(a_steel, k)
                        for e in ELEMENTS:
                            masses[e] += eff[e]
                        M += k * rTOT_s
                        kg_steel += k

            # 3) Subir lo que falte de C y Si
            if not skip_csi:
                if fracC() < T_C_up - 1e-12 and rC_g > eps:
                    k = self._solve_kg_for_target(M, masses["C"], T_C_up, rC_g, rTOT_g)
                    if k and k > 0:
                        eff = self._effective_add(a_graph, k)
                        for e in ELEMENTS:
                            masses[e] += eff[e]
                        M += k * rTOT_g
                        kg_C += k
                if fracSi() < T_Si_up - 1e-12 and rSi > eps:
                    k = self._solve_kg_for_target(M, masses["Si"], T_Si_up, rSi, rTOT_si)
                    if k and k > 0:
                        eff = self._effective_add(a_sil, k)
                        for e in ELEMENTS:
                            masses[e] += eff[e]
                        M += k * rTOT_si
                        kg_Si += k


            # Plan final
            plan = {}
            for n, kg in kg_other.items():
                if kg > 0:
                    plan[n] = plan.get(n, 0.0) + kg
            if kg_steel > 0 and a_steel:
                nm = a_steel.get("nombre","Acero 1010")
                plan[nm] = plan.get(nm, 0.0) + kg_steel
            if kg_C > 0 and a_graph:
                nm = a_graph.get("nombre","Carbón de grafito")
                plan[nm] = plan.get(nm, 0.0) + kg_C
            if kg_Si > 0 and a_sil:
                nm = a_sil.get("nombre","Silicio")
                plan[nm] = plan.get(nm, 0.0) + kg_Si

            # Refuerzo: si algún elemento objetivo queda por debajo, agregar con el mejor material de ajuste
            try:
                M_sim = M0
                masses_sim = {e: M0 * comp0.get(e, 0.0) / 100.0 for e in ELEMENTS}
                for nm, kg in plan.items():
                    if kg <= 0:
                        continue
                    a = self._get_adjuster(nm)
                    if not a:
                        continue
                    eff = self._effective_add(a, kg)
                    for e in ELEMENTS:
                        masses_sim[e] += eff[e]
                    M_sim += kg * self._effective_total_perkg(a)
                for el in [e for e in ELEMENTS if e not in ("C", "Si", "Fe")]:
                    T_E = tgt_pct.get(el, 0.0) / 100.0
                    if T_E <= 0:
                        continue
                    fE = masses_sim[el] / M_sim if M_sim > 0 else 0.0
                    if fE < T_E - 1e-12:
                        nm = best_for_elem.get(el)
                        if not nm:
                            continue
                        a = self._get_adjuster(nm)
                        if not a:
                            continue
                        rE = self._effective_add_perkg(a, el)
                        rTOT = self._effective_total_perkg(a)
                        if rTOT <= 0 or rE <= eps:
                            continue
                        k = self._solve_kg_for_target(M_sim, masses_sim[el], T_E, rE, rTOT)
                        if k is None or k <= 0:
                            continue
                        eff = self._effective_add(a, k)
                        for e in ELEMENTS:
                            masses_sim[e] += eff[e]
                        M_sim += k * rTOT
                        plan[nm] = plan.get(nm, 0.0) + k
            except Exception:
                pass

            if log_it or log_calc:
                pred_pct_snapshot = {e: (100.0 * masses[e] / M if M > 0 else 0.0) for e in ELEMENTS}
                ce_min, ce_max, ce_formula, ce_custom = self._objective_ce_data()
                ce_now = ce_from_percent(comp0, ce_formula, ce_custom)
                ce_pred = ce_from_percent(pred_pct_snapshot, ce_formula, ce_custom)
                if log_it:
                    self._log_ajuste(plan, 100.0, comp0, M0, pred_pct_snapshot, M, name,
                                     ce_formula, ce_now, ce_pred, self._target_comp())
                if log_calc:
                    self._log_calc(plan, 100.0, comp0, M0, pred_pct_snapshot, M, name,
                                   ce_formula, ce_now, ce_pred)

            if return_plan:
                return plan

            for n, kg in plan.items():
                if self._ensure_adjuster_present(n) and kg >= 0:
                    self.kg_vars[n].set(fmt(kg, 3))

            self.calc_prediction()
            if warn_msg:
                self._status(warn_msg)
            else:
                self._status("")
            return True
        except Exception as ex:
            if not silent:
                self._status(f"Error en estimación: {ex}")
            return {} if return_plan else False

    def calculate_partial(self):
        if self.auto_est.get():
            # Evita que auto-estimar sobrescriba el cálculo parcial
            self.auto_est.set(False)
        plan = self._estimate_core(reset_kgs=True, log_it=False, log_calc=False, silent=True, return_plan=True)
        if not plan:
            self._status("No hay plan para calcular %. Revisá objetivo/materiales.")
            return
        M0 = self._bath_mass()
        comp0 = self._current_comp()
        pct = max(1, min(100, int(self.partial_pct.get())))
        p = pct / 100.0
        plan_scaled = {k: v * p for k, v in plan.items()}

        try:
            self._busy = True
            for name in plan_scaled.keys():
                self._ensure_adjuster_present(name)
            for v in self.kg_vars.values():
                v.set("0")
            for name, kg in plan_scaled.items():
                self.kg_vars[name].set(fmt(kg, 3))

            if self._auto_job is not None:
                try:
                    self.after_cancel(self._auto_job)
                except Exception:
                    pass
                self._auto_job = None

            self.calc_prediction()
            pred_M, pred_pct = getattr(self, "_predicted", (M0, self._current_comp()))
            ce_min, ce_max, ce_formula, ce_custom = self._objective_ce_data()
            ce_now = ce_from_percent(comp0, ce_formula, ce_custom)
            ce_pred = ce_from_percent(pred_pct, ce_formula, ce_custom)

            self._log_calc(plan_scaled, float(pct), comp0, M0, pred_pct, pred_M,
                           self.cb_obj.get().strip(), ce_formula, ce_now, ce_pred)
            self._status(f"Calculado {pct}% del plan.")
        finally:
            self._busy = False
        self._fire_save()

    def apply_adjustment(self):
        try:
            if not self._require_started_session():
                return
            if not hasattr(self, "_predicted"):
                self.calc_prediction()
                if not hasattr(self, "_predicted"):
                    return
            # Guardar el ajuste aplicado en historial principal
            try:
                M0 = self._bath_mass()
                comp0 = self._current_comp()
                plan = {n: to_float(v.get()) for n, v in self.kg_vars.items() if to_float(v.get()) > 0}
                Mnew, pred_pct = self._predicted
                ce_min, ce_max, ce_formula, ce_custom = self._objective_ce_data()
                ce_now = ce_from_percent(comp0, ce_formula, ce_custom)
                ce_pred = ce_from_percent(pred_pct, ce_formula, ce_custom)
                applied_at = datetime.now()
                self._log_ajuste(plan, 100.0, comp0, M0, pred_pct, Mnew,
                                 self.cb_obj.get().strip(), ce_formula, ce_now, ce_pred, self._target_comp())
                self._publish_furnace_snapshot(
                    plan,
                    comp0,
                    pred_pct,
                    self.cb_obj.get().strip(),
                    ce_formula,
                    ce_now,
                    ce_pred,
                    applied_at=applied_at,
                )
            except Exception:
                pass
            Mnew, pred_pct = self._predicted
            for el, e in self.actual_rows:
                e.delete(0, tk.END)
                e.insert(0, fmt(pred_pct.get(el, 0.0)))
            self.mass.set(fmt(Mnew))
            for v in self.kg_vars.values():
                v.set("0")
            self._schedule_graph_update()
            self._status("Aplicado.")
            self._fire_save()
        except Exception as ex:
            self._status(f"Error al aplicar: {ex}")

    # ------------------------------ Log / hist ------------------------------
    def _summarize_plan(self, plan):
        if not plan:
            return ""
        return "; ".join(f"{k}: {fmt(v, 3)} kg" for k, v in sorted(plan.items()))

    def _furnace_material_rows(self, plan):
        items = {str(name): round(to_float(kg), 3) for name, kg in (plan or {}).items() if to_float(kg) > 0}
        rows = []
        seen = set()
        for name in getattr(self, "adjust_list", []):
            if name in items:
                kg = items[name]
                rows.append({
                    "nombre": name,
                    "kg": kg,
                    "porcentaje_horno": 100,
                    "kg_horno": kg,
                })
                seen.add(name)
        for name in sorted(items):
            if name not in seen:
                kg = items[name]
                rows.append({
                    "nombre": name,
                    "kg": kg,
                    "porcentaje_horno": 100,
                    "kg_horno": kg,
                })
        return rows

    def _furnace_comp_rows(self, comp):
        if not comp:
            return []
        rows = []
        for el in ELEMENTS:
            value = round(to_float(comp.get(el, 0.0)), 6)
            if abs(value) <= 1e-12:
                continue
            rows.append({"elemento": el, "valor": value})
        return rows

    def _publish_furnace_snapshot(self, plan, comp0, pred_pct, objetivo_name, ce_formula, ce_now, ce_pred, applied_at=None):
        ts = applied_at or datetime.now()
        save_furnace_state({
            "updated_at": ts.isoformat(timespec="seconds"),
            "ajuste": {
                "colada": self.colada.get().strip(),
                "material_objetivo": str(objetivo_name or "").strip(),
                "hora_actual": ts.strftime("%H:%M"),
                "ce_formula": str(ce_formula or "").strip(),
                "ce_actual": round(to_float(ce_now), 6),
                "ce_estimado": round(to_float(ce_pred), 6),
                "porcentaje_general_horno": 100,
                "materiales_confirmados": False,
                "confirmado_at": None,
                "materiales": self._furnace_material_rows(plan),
                "composicion_actual": self._furnace_comp_rows(comp0),
                "composicion_estimada": self._furnace_comp_rows(pred_pct),
            },
        })
        self._notify_pie_horno_changed()

    def _publish_furnace_context(self):
        colada = self.colada.get().strip()
        objetivo_name = self.cb_obj.get().strip()
        if not colada or not objetivo_name:
            return
        ts = datetime.now()
        comp0 = self._current_comp()
        ce_formula = ""
        ce_now = None
        try:
            _, _, ce_formula, ce_custom = self._objective_ce_data()
            ce_now = ce_from_percent(comp0, ce_formula, ce_custom)
        except Exception:
            ce_formula = ""
            ce_now = None
        save_furnace_state({
            "updated_at": ts.isoformat(timespec="seconds"),
            "ajuste": {
                "colada": colada,
                "material_objetivo": str(objetivo_name or "").strip(),
                "hora_actual": ts.strftime("%H:%M"),
                "ce_formula": str(ce_formula or "").strip(),
                "ce_actual": round(to_float(ce_now), 6) if ce_now is not None else None,
                "ce_estimado": None,
                "materiales": [],
                "composicion_actual": self._furnace_comp_rows(comp0),
                "composicion_estimada": [],
            },
        })
        self._notify_pie_horno_changed()

    def _ensure_furnace_context_published(self):
        colada = self.colada.get().strip()
        objetivo_name = self.cb_obj.get().strip()
        if not colada or not objetivo_name or not self.session_started_at:
            return
        try:
            current = load_furnace_state()
            ajuste = current.get("ajuste", {}) if isinstance(current, dict) else {}
            if not isinstance(ajuste, dict):
                ajuste = {}
            same_context = (
                str(ajuste.get("colada", "") or "").strip() == colada
                and str(ajuste.get("material_objetivo", "") or "").strip() == objetivo_name
            )
            has_payload = bool(
                ajuste.get("materiales")
                or ajuste.get("composicion_actual")
                or ajuste.get("composicion_estimada")
                or ajuste.get("ce_actual") is not None
            )
            if same_context and has_payload:
                self._notify_pie_horno_changed()
                return
        except Exception:
            pass
        self._publish_furnace_context()

    def _clear_furnace_snapshot(self):
        clear_furnace_state()
        self._notify_pie_horno_changed()

    def _notify_pie_horno_changed(self):
        try:
            from host_api import notify_data_changed
            notify_data_changed()
        except Exception:
            pass

    def _summarize_changes(self, comp0, comp1):
        out = []
        for e in ELEMENTS:
            v0 = to_float(comp0.get(e, 0.0))
            v1 = to_float(comp1.get(e, 0.0))
            d = v1 - v0
            if abs(d) > 1e-12:
                out.append((e, v0, v1, d))
        return out

    def _changes_preview(self, changes):
        if not changes:
            return ""
        ordered = sorted(changes, key=lambda x: abs(x[3]), reverse=True)
        top = ordered[:4]
        labels = [f"{e}: {fmt(v0, 4)} → {fmt(v1, 4)}" for e, v0, v1, _ in top]
        if len(ordered) > 4:
            labels[-1] = "Ver más…"
        return "; ".join(labels)

    def _refresh_hist(self):
        if not hasattr(self, "tree_hist"):
            return
        changed = False
        for it in getattr(self, "ajustes_log", []):
            if not it.get("id"):
                it["id"] = uuid.uuid4().hex
                changed = True
        for i in self.tree_hist.get_children():
            self.tree_hist.delete(i)
        items = sorted(getattr(self, "ajustes_log", []), key=lambda x: x.get("fecha", ""))
        self._ajustes_sorted = items
        self._ajustes_id_index = {it.get("id"): i for i, it in enumerate(self.ajustes_log) if it.get("id")}
        for it in items:
            preview = self._changes_preview(it.get("cambios_list", []))
            self.tree_hist.insert(
                "",
                "end",
                values=(it.get("fecha", ""), it.get("objetivo", ""), preview, it.get("resumen", "")),
            )
        if changed:
            self._fire_save()
        self._refresh_changes_window()
        self._schedule_graph_update()

    def _log_ajuste(self, plan, porcentaje, comp0, M0, pred_pct, Mnew, objetivo_name,
                     ce_formula, ce_now, ce_pred, objetivo_comp):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # La sesión comienza cuando se registra el primer ajuste real
            _, _, _, ce_custom = self._objective_ce_data()
            ce_obj = ce_from_percent(objetivo_comp or {}, ce_formula, ce_custom)
            cambios = self._summarize_changes(comp0, pred_pct)
            entry = {
                "id": uuid.uuid4().hex,
                "fecha": ts,
                "colada": self.colada.get(),
                "objetivo": objetivo_name or "",
                "porcentaje": porcentaje,
                "inicial": {"masa": M0, "comp": comp0},
                "estimado": {"masa": Mnew, "comp": pred_pct},
                "objetivo_comp": objetivo_comp,
                "materiales": plan,
                "resumen": self._summarize_plan(plan),
                "cambios_list": cambios,
                "cambios": self._changes_preview(cambios),
                "ce_formula": ce_formula,
                "ce_custom": ce_custom or {},
                "ce_inicial": ce_now,
                "ce_estimado": ce_pred,
                "ce_objetivo": ce_obj,
            }
            self.ajustes_log.append(entry)
            self._refresh_hist()
            self._fire_save()
        except Exception:
            pass

    def _log_calc(self, plan, porcentaje, comp0, M0, pred_pct, Mnew, objetivo_name, ce_formula, ce_now, ce_pred):
        try:
            ts = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            cambios = self._summarize_changes(comp0, pred_pct)
            entry = {
                "fecha": ts,
                "objetivo": objetivo_name or "",
                "porcentaje": porcentaje,
                "inicial": {"masa": M0, "comp": comp0},
                "estimado": {"masa": Mnew, "comp": pred_pct},
                "materiales": plan,
                "resumen": self._summarize_plan(plan),
                "cambios_list": cambios,
                "cambios": self._changes_preview(cambios),
                "ce_formula": ce_formula,
                "ce_inicial": ce_now,
                "ce_estimado": ce_pred,
            }
            self.calc_log.append(entry)
            self._fire_save()
            self._refresh_calc_log_window()
        except Exception:
            pass

    def _open_calc_log(self):
        win = tk.Toplevel(self)
        win.title("Historial de cálculos")
        win.transient(self)
        win.geometry("760x480")
        self._calc_log_win = win

        cols = ("fecha", "objetivo", "porcentaje", "cambios", "resumen")
        tree = ttk.Treeview(win, columns=cols, show="headings", height=14)
        self._calc_log_tree = tree
        for cid, title, w in (
            ("fecha", "Fecha/Hora", 160),
            ("objetivo", "Objetivo", 180),
            ("porcentaje", "%", 60),
            ("cambios", "Cambios", 120),
            ("resumen", "Materiales", 440),
        ):
            tree.heading(cid, text=title)
            tree.column(cid, width=w, anchor="w")
        tree.pack(fill="both", expand=True, padx=8, pady=8)

        self._refresh_calc_log_window()

        def on_open_changes(_evt=None):
            sel = tree.selection()
            if not sel:
                return
            idx = tree.index(sel[0])
            if idx < 0 or idx >= len(self.calc_log):
                return
            entry = self.calc_log[idx]
            changes_list = entry.get("cambios_list", [])
            changes = entry.get("cambios", "")
            w2 = tk.Toplevel(win)
            w2.title("Cambios de composición")
            w2.transient(win)
            w2.geometry("520x420")
            self._changes_win = w2
            self._changes_idx = ("calc", idx)
            txt = tk.Text(w2, wrap="word")
            txt.pack(fill="both", expand=True, padx=8, pady=8)
            if changes_list:
                lines = [f"{e}: {fmt(v0, 4)} → {fmt(v1, 4)}" for e, v0, v1, _ in changes_list]
                txt.insert("1.0", "\n".join(lines))
            else:
                txt.insert("1.0", changes or "(Sin cambios)")
            txt.config(state="disabled")
            ttk.Button(w2, text="Cerrar", command=w2.destroy).pack(pady=(0, 8))

        tree.bind("<Double-Button-1>", on_open_changes)

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=8, pady=(0, 8))
        ttk.Button(btns, text="Cerrar", command=win.destroy).pack(side="right")
        win.protocol("WM_DELETE_WINDOW", lambda: (setattr(self, "_calc_log_win", None), setattr(self, "_calc_log_tree", None), win.destroy()))

    # --------- editar / eliminar ajuste seleccionado en esta pestaña ---
    def _selected_hist_index(self):
        sel = self.tree_hist.selection()
        if not sel:
            return None
        idx = self.tree_hist.index(sel[0])
        items = self._ajustes_sorted or sorted(self.ajustes_log, key=lambda x: x.get("fecha", ""))
        if idx >= len(items):
            return None
        picked = items[idx]
        picked_id = picked.get("id")
        if picked_id and picked_id in self._ajustes_id_index:
            return self._ajustes_id_index[picked_id]
        fecha = picked.get("fecha")
        for i, it in enumerate(self.ajustes_log):
            if it.get("fecha") == fecha:
                return i
        return None

    def _open_selected_changes(self):
        idx = self._selected_hist_index()
        if idx is None:
            self._status("Seleccioná un ajuste para ver cambios.")
            return
        entry = self.ajustes_log[idx]
        changes_list = entry.get("cambios_list", [])
        changes = entry.get("cambios", "")
        win = tk.Toplevel(self)
        win.title("Cambios de composición")
        win.transient(self)
        win.geometry("520x420")
        self._changes_win = win
        self._changes_idx = ("applied", idx)

        txt = tk.Text(win, wrap="word")
        txt.pack(fill="both", expand=True, padx=8, pady=8)
        if changes_list:
            lines = [f"{e}: {fmt(v0, 4)} → {fmt(v1, 4)}" for e, v0, v1, _ in changes_list]
            txt.insert("1.0", "\n".join(lines))
        else:
            txt.insert("1.0", changes or "(Sin cambios)")
        txt.config(state="disabled")

        ttk.Button(win, text="Cerrar", command=win.destroy).pack(pady=(0, 8))
        win.protocol("WM_DELETE_WINDOW", lambda: (setattr(self, "_changes_win", None), setattr(self, "_changes_idx", None), win.destroy()))

    def _refresh_calc_log_window(self):
        if not self._calc_log_win or not self._calc_log_tree:
            return
        tree = self._calc_log_tree
        for i in tree.get_children():
            tree.delete(i)
        for it in self.calc_log:
            tree.insert(
                "", "end",
                values=(
                    it.get("fecha", ""),
                    it.get("objetivo", ""),
                    it.get("porcentaje", ""),
                    it.get("cambios", ""),
                    it.get("resumen", ""),
                ),
            )

    def _refresh_changes_window(self):
        if not self._changes_win or not self._changes_idx:
            return
        kind, idx = self._changes_idx
        if kind == "calc":
            if idx < 0 or idx >= len(self.calc_log):
                return
            entry = self.calc_log[idx]
        else:
            if idx < 0 or idx >= len(self.ajustes_log):
                return
            entry = self.ajustes_log[idx]
        changes_list = entry.get("cambios_list", [])
        changes = entry.get("cambios", "")
        # reemplaza el contenido del Text
        for w in self._changes_win.winfo_children():
            if isinstance(w, tk.Text):
                w.config(state="normal")
                w.delete("1.0", tk.END)
                if changes_list:
                    lines = [f"{e}: {fmt(v0, 4)} → {fmt(v1, 4)}" for e, v0, v1, _ in changes_list]
                    w.insert("1.0", "\n".join(lines))
                else:
                    w.insert("1.0", changes or "(Sin cambios)")
                w.config(state="disabled")

    def _edit_selected_adjustment(self):
        idx = self._selected_hist_index()
        if idx is None:
            self._status("Seleccioná un ajuste para editar.")
            return
        entry = self.ajustes_log[idx]
        self._edit_adjust_dialog(entry, lambda new_entry: self._apply_edit_adjust(idx, new_entry))

    def _apply_edit_adjust(self, idx, new_entry):
        self.ajustes_log[idx] = new_entry
        self._refresh_hist()
        self._fire_save()
        self._status("Ajuste editado.")

    def _delete_selected_adjustment(self):
        idx = self._selected_hist_index()
        if idx is None:
            self._status("Seleccioná un ajuste para eliminar.")
            return
        if not messagebox.askyesno("Eliminar", "¿Eliminar el ajuste seleccionado?"):
            return
        del self.ajustes_log[idx]
        self._refresh_hist()
        self._fire_save()
        self._status("Ajuste eliminado.")

    # -------- editor simple de ajuste (en esta pestaña) ----------
    def _simulate_with_plan(self, M0, comp0, plan):
        return simulate_with_plan(
            M0, comp0, plan, ELEMENTS, self._adjuster_alloy, self._effective_add, self._effective_total_perkg
        )

    def _edit_adjust_dialog(self, adj_entry, on_save):
        win = tk.Toplevel(self)
        win.title("Editar ajuste")
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        win.geometry("540x560")

        ttk.Label(win, text=f"Fecha: {adj_entry.get('fecha','')}").pack(anchor="w", padx=10, pady=(10, 4))
        ttk.Label(win, text=f"Objetivo: {adj_entry.get('objetivo','')}").pack(anchor="w", padx=10, pady=(0, 6))

        mats_frame = ttk.LabelFrame(win, text="Materiales (kg)", padding=6)
        mats_frame.pack(fill="both", expand=True, padx=8, pady=6)

        mats = dict(adj_entry.get("materiales", {}))
        var_map = {}
        for name in sorted(mats.keys()):
            row = ttk.Frame(mats_frame)
            row.pack(fill="x", pady=2)
            ttk.Label(row, text=name, width=28).pack(side="left")
            v = tk.StringVar(value=fmt(to_float(mats.get(name, 0.0)), 3))
            ttk.Entry(row, textvariable=v, width=10).pack(side="left", padx=4)
            var_map[name] = v

        res = ttk.Label(win, text="Estimado: pendiente…")
        res.pack(anchor="w", padx=10, pady=(4, 0))

        btns = ttk.Frame(win)
        btns.pack(fill="x", padx=8, pady=8)

        def recalc():
            try:
                plan = {n: to_float(v.get()) for n, v in var_map.items() if to_float(v.get()) > 0}
                M0 = adj_entry.get("inicial", {}).get("masa", 0.0)
                comp0 = adj_entry.get("inicial", {}).get("comp", {})
                Mnew, comp_est = self._simulate_with_plan(M0, comp0, plan)
                ce_formula = adj_entry.get('ce_formula', 'FUNDICION')
                ce_custom = adj_entry.get("ce_custom", {}) or {}
                ce_est = ce_from_percent(comp_est, ce_formula, ce_custom)
                res.config(text=f"Estimado: masa {fmt(Mnew)} kg | CE {fmt(ce_est, 4)}")
                return (Mnew, comp_est, plan, ce_est, ce_custom)
            except Exception as ex:
                messagebox.showerror("Editar", str(ex), parent=win)
                return None

        def save():
            out = recalc()
            if not out:
                return
            Mnew, comp_est, plan, ce_est, ce_custom = out
            new_adj = dict(adj_entry)
            new_adj["estimado"] = {"masa": Mnew, "comp": comp_est}
            new_adj["materiales"] = plan
            new_adj["resumen"] = "; ".join(f"{k}: {fmt(v, 3)} kg" for k, v in sorted(plan.items()))
            new_adj["ce_custom"] = ce_custom or {}
            new_adj["ce_estimado"] = ce_est
            on_save(new_adj)
            win.destroy()

        ttk.Button(btns, text="Recalcular estimado", command=recalc).pack(side="left")
        ttk.Button(btns, text="Guardar cambios", command=save).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

    # -------------------------- Colada (ID/YY en UI) -----------------------
    COLADA_IDYY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})\s*$")

    @staticmethod
    def parse_colada_idyy(s):
        m = TabAjuste.COLADA_IDYY_RE.match(s or "")
        if not m:
            return (None, None)
        try:
            return (int(m.group(1)), m.group(2))
        except Exception:
            return (None, None)

    @staticmethod
    def build_colada_idyy(id_num, yy):
        return f"{int(id_num):04d} /{str(yy).zfill(2)}"

    def _next_colada_idyy(self):
        cur_id, _ = self.parse_colada_idyy(self.colada.get())
        next_id = (cur_id + 1) if cur_id is not None else 1
        next_yy = datetime.now().strftime("%y")
        return self.build_colada_idyy(next_id, next_yy)

    def build_colada_full(self):
        material = self.cb_obj.get().strip()
        base = self.colada.get().strip()
        if not base:
            return material or ""
        return f"{base} - {material}" if material else base

    def _prompt_colada_idyy(self, title="Número de colada"):
        cur_id, _ = self.parse_colada_idyy(self.colada.get())
        sug_id = (cur_id + 1) if cur_id is not None else 1
        yy = datetime.now().strftime("%y")

        sel = {"val": None}
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)
        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)

        row1 = ttk.Frame(frm)
        row1.pack(fill="x", pady=4)
        ttk.Label(row1, text="ID:").pack(side="left")
        v_id = tk.StringVar(value=str(sug_id))
        e_id = ttk.Entry(row1, textvariable=v_id, width=8)
        e_id.pack(side="left", padx=6)

        ttk.Label(row1, text="/").pack(side="left")
        ttk.Label(row1, text="YY:").pack(side="left", padx=(6, 0))
        v_yy = tk.StringVar(value=yy)
        e_yy = ttk.Entry(row1, textvariable=v_yy, width=4)
        e_yy.pack(side="left", padx=6)

        btns = ttk.Frame(frm)
        btns.pack(fill="x", pady=(10, 0))

        def ok():
            try:
                idn = int(v_id.get().strip())
                yys = v_yy.get().strip().zfill(2)
                sel["val"] = self.build_colada_idyy(idn, yys)
                win.destroy()
            except Exception:
                messagebox.showerror("Colada", "Datos inválidos.", parent=win)

        ttk.Button(btns, text="Aceptar", command=ok).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

        e_id.focus_set()
        e_id.select_range(0, tk.END)
        win.wait_window()
        return sel["val"]

    def ensure_colada(self):
        if not self.colada.get():
            new_val = self._prompt_colada_idyy()
            if new_val:
                self.colada.set(new_val)
                if self.cb_obj.get().strip() and self.session_started_at:
                    self._publish_furnace_context()
                self._fire_save()

    def edit_colada(self):
        new_val = self._prompt_colada_idyy(title="Editar N° de colada")
        if new_val:
            self.colada.set(new_val)
            if self.cb_obj.get().strip() and self.session_started_at:
                self._publish_furnace_context()
            self._fire_save()

    # -------------------------- Guardar sesión ------------------------------
    def _append_current_session_to_history(self, ended_at=None, auto=False):
        if not self.ajustes_log:
            return False
        ended_ts = ended_at or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        started_at = self.session_started_at or self.ajustes_log[0].get("fecha") or ended_ts
        session = {
            "colada": self.build_colada_full(),
            "objetivo": self.cb_obj.get().strip(),
            "started_at": started_at,
            "ended_at": ended_ts,
            "ajustes": list(self.ajustes_log),
            "calculos": list(self.calc_log),
            "carbono": list(self.carbon_log),
            "auto_saved": bool(auto),
        }
        try:
            append_history(session)
        except DuplicateColadaError as ex:
            self._status(str(ex))
            return False
        try:
            self.event_generate("<<HistoryUpdated>>", when="tail")
        except Exception:
            pass
        return True

    def _maybe_auto_save_session(self):
        if not self.ajustes_log or not self.session_started_at:
            return
        try:
            started = datetime.fromisoformat(str(self.session_started_at))
        except Exception:
            return
        try:
            limit_hours = float(getattr(self.winfo_toplevel(), "_auto_save_hours", 3.0))
        except Exception:
            limit_hours = 3.0
        if limit_hours <= 0:
            limit_hours = 3.0
        now = datetime.now()
        if (now - started).total_seconds() < (limit_hours * 3600.0):
            return
        ended_ts = now.strftime("%Y-%m-%d %H:%M:%S")
        if not self._append_current_session_to_history(ended_at=ended_ts, auto=True):
            return
        self.colada.set(self._next_colada_idyy())
        self._reset_session_workspace(clear_furnace_snapshot=False)
        self._fire_save()
        self._status("Sesión guardada automáticamente por superar 3 horas.")

    def save_current_session(self):
        try:
            if not self.ajustes_log:
                self._status("No hay ajustes para guardar.")
                return
            if not self._append_current_session_to_history():
                return
            self.colada.set(self._next_colada_idyy())
            self._reset_session_workspace(clear_furnace_snapshot=False)
            self._fire_save()
            self._status("Sesión guardada.")
        except Exception as ex:
            self._status(f"No se pudo guardar: {ex}")
