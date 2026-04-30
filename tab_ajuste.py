# tab_ajuste.py
import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import time
import re
import uuid

from config import ELEMENTS, COLOR_OK, COLOR_FAIL, COLOR_WARN, TOL_NO_LIMITS, BG_ENTRY, FG, ACCENT
from utils import to_float, fmt, _norm, simulate_with_plan
from ce import ce_from_percent
from storage import DuplicateColadaError, append_history, save_alloys, load_furnace_state, save_furnace_state, clear_furnace_state
from widgets import ScrollFrame


class TabAjuste(ttk.Frame):
    DEFAULT_ADJUST = ["Carbón de grafito", "Silicio", "Acero 1010", "FeCr alto C"]
    CARBOMAX_AUTO_NAMES = ["Carbón de grafito", "Silicio", "Acero 1010"]
    CARBOMAX_POLL_SECONDS = 15.0

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

        # ---------- CONFIG GRID PRINCIPAL ----------
        # Fila 0: barra superior
        # Fila 1: pan_cols con 4 paneles (Actual, Estimado, Objetivo, Materiales)
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

        # ===================== fila 1: 4 columnas redimensionables =====================
        pan_cols = ttk.Panedwindow(self, orient="horizontal")
        pan_cols.grid(row=1, column=0, sticky="nsew", pady=(0, 8))

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
            e.bind("<KeyRelease>", lambda _e: (self._recalc_fe_actual(), self._schedule_auto(), self._fire_save()))
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

        # Sashes iniciales para 4 paneles
        def _place_sashes_cols():
            try:
                w = pan_cols.winfo_width()
                pan_cols.sashpos(0, int(w * 0.25))
                pan_cols.sashpos(1, int(w * 0.50))
                pan_cols.sashpos(2, int(w * 0.75))
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

        # --------- Datos iniciales de materiales / hist ----------
        self.kg_vars = {}
        self._ensure_adjusters_in_catalog()
        self.adjust_list = [n for n in self.DEFAULT_ADJUST if self._adjuster_alloy(n)]
        self._rebuild_adjust_ui()

        self._refresh_hist()

        self._update_objective_selector_state()
        self.calc_prediction()
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

    def set_save_callback(self, cb):
        self._save_cb = cb

    def set_thermal_source(self, source):
        self._thermal_source = source

    def _fire_save(self):
        if self._save_cb and not self._restoring:
            self._save_cb()

    def get_state(self):
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
                self._carbomax_auto_armed_at = datetime.now().strftime("%Y-%m-%d 00:00:00")
            self._refresh_session_timer_labels()
            self._update_objective_selector_state()
        finally:
            self._restoring = False
            self._schedule_auto()
            self.after(100, self._ensure_furnace_context_published)

    # ------------------------------- helpers generales ----------------------
    def _status(self, msg):
        try:
            self.lbl_status.config(text=msg or "")
        except Exception:
            pass

    def _schedule_auto(self):
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
        delta = datetime.now() - started
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
            self._thermal_source.poll_latest_carbon_async(
                self.session_started_at or self._carbomax_auto_armed_at,
                sorted(consumed_paths),
                self._on_carbomax_poll_result,
            )
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
                ent.bind("<KeyRelease>", lambda _e: (self._schedule_auto(), self._fire_save()))
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
