# tab_historicos.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import csv
import html
import json
import re
from datetime import datetime

from storage import DuplicateColadaError, load_history, load_ladles_state, save_ladles_state, prune_ladles_history_for_sessions, update_session, delete_session, update_adjustment, delete_adjustment, detach_thermal_analysis, set_thermal_analysis_field, load_inoc_momentos
from widgets import ScrollFrame
from config import ELEMENTS
from utils import fmt, to_float, simulate_with_plan
from ce import ce_from_percent

COLADA_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})\s*-\s*(.+?)\s*$")


def split_colada(s):
    m = COLADA_RE.match(s or "")
    if not m:
        return ("", "", s or "")
    return (m.group(1), m.group(2), m.group(3))


def _thermal_mode_group(mode_value):
    mode = str(mode_value or "").upper()
    if "MICR" in mode:
        return "Microestructura"
    if "CARB" in mode:
        return "Carbono"
    return "Todos"


class TabHistoricos(ttk.Frame):
    def __init__(self, master, alloys_model):
        super().__init__(master, padding=8)
        self.alloys = alloys_model
        self.hist = []
        self.ladles = {}
        self._session_tabs = {}
        self._alloy_cache = None
        self._root_notebook = None
        self._quality_tab = None
        self._thermal_tab = None
        self._adjust_tab = None

        # ---- Layout principal (dock)
        root = ttk.PanedWindow(self, orient="horizontal")
        root.pack(fill="both", expand=True)

        left = ttk.Frame(root)
        right = ttk.Frame(root)
        root.add(left, weight=1)
        root.add(right, weight=3)

        # ---- Cabecera
        top = ttk.Frame(left); top.pack(fill="x")
        ttk.Label(top, text="Historial de coladas guardadas").pack(side="left")
        ttk.Button(top, text="Refrescar", command=self.refresh).pack(side="right")
        ttk.Button(top, text="Exportar JSON", command=self.export_json).pack(side="right", padx=6)

        # ---- Acciones sobre sesion
        act = ttk.Frame(left); act.pack(fill="x", pady=(6, 0))
        ttk.Button(act, text="Editar colada", command=self.edit_session_meta).pack(side="left")
        ttk.Button(act, text="Eliminar sesion", command=self.delete_session).pack(side="left", padx=6)
        ttk.Button(act, text="Visualizar en Ajuste", command=self.view_selected_in_adjust).pack(side="left", padx=6)
        ttk.Button(act, text="Generar informe de calidad", command=self.generate_quality_report_for_selected).pack(side="left")
        ttk.Button(act, text="Marcar sinterizado", command=self._toggle_sinterizado).pack(side="left", padx=6)

        # ---- Tabla de sesiones (coladas)
        cols = ("id", "objetivo", "guardado", "inicio", "fin", "crisol", "cant")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=20)
        for cid, title, w in (
            ("id",       "ID",        220),
            ("objetivo", "Objetivo",   80),
            ("guardado", "Guardado",   70),
            ("inicio",   "Inicio",    150),
            ("fin",      "Fin",       150),
            ("crisol",   "Crisol",     60),
            ("cant",     "# ajustes",  70),
        ):
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(6, 6))

        self.tree.bind("<Double-Button-1>", lambda e: self._open_session_tab())

        # ---- Dock de sesiones (tabs)
        self.nb = ttk.Notebook(right)
        self.nb.pack(fill="both", expand=True)

        # Permitir que TabAjuste dispare refresco
        self.bind("<<HistoryUpdated>>", lambda e: self.refresh())

        self.refresh()

    def set_quality_target(self, notebook, quality_tab):
        self._root_notebook = notebook
        self._quality_tab = quality_tab

    def set_thermal_target(self, notebook, thermal_tab):
        self._root_notebook = notebook
        self._thermal_tab = thermal_tab

    def set_adjust_view_target(self, notebook, adjust_tab):
        self._root_notebook = notebook
        self._adjust_tab = adjust_tab

    # ---------------------------- helpers catalogo -------------------------
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
            cache = {}
            for alloy in self.alloys:
                cache.setdefault(alloy.get("nombre", ""), []).append(alloy)
            self._alloy_cache = cache
            items = list(self._alloy_cache.get(name, []))
        return items

    def _alloy_by_name(self, name, prefer_type=None, require_adjust=False):
        items = self._alloys_named(name)
        if require_adjust:
            for alloy in items:
                if bool(alloy.get("ajuste", False)) and alloy.get("tipo", "") != "Aleación final":
                    return alloy
            for alloy in items:
                if alloy.get("tipo", "") != "Aleación final":
                    return alloy
        if prefer_type:
            for alloy in items:
                if alloy.get("tipo", "") == prefer_type:
                    return alloy
        return items[0] if items else None

    def _objective_comp(self, session):
        name = session.get("objetivo", "")
        a = self._alloy_by_name(name, prefer_type="Aleación propia")
        return (a or {}).get("composicion", {}) or {}

    def _effective_total_perkg(self, alloy):
        return to_float(alloy.get("rendimiento", 100.0)) / 100.0

    def _effective_add(self, alloy, kg):
        rend = self._effective_total_perkg(alloy)
        out = {e: 0.0 for e in ELEMENTS}
        for e in ELEMENTS:
            out[e] = kg * (to_float(alloy["composicion"].get(e, 0.0)) / 100.0) * rend
        return out

    def _simulate_with_plan(self, M0, comp0, plan):
        return simulate_with_plan(
            M0,
            comp0,
            plan,
            ELEMENTS,
            lambda name: self._alloy_by_name(name, require_adjust=True),
            self._effective_add,
            self._effective_total_perkg,
        )

    # ---------------------------- data load --------------------------------
    def refresh(self):
        self.hist = load_history()
        prune_ladles_history_for_sessions(self.hist)
        self.ladles = load_ladles_state()
        self._alloy_cache = None
        for i in self.tree.get_children():
            self.tree.delete(i)
        crisol_counter = 0
        crisol_displays = []
        for s in self.hist:
            if s.get("primer_sinterizado"):
                crisol_counter = 1
            else:
                crisol_counter += 1
            crisol_displays.append(f"[S] {crisol_counter}" if s.get("primer_sinterizado") else str(crisol_counter))

        # Se muestra de mas reciente a mas antigua (id mayor arriba de todo), pero el
        # iid de cada fila es su indice real en self.hist/DB, no la posicion visual.
        for idx in range(len(self.hist) - 1, -1, -1):
            s = self.hist[idx]
            colada_raw = s.get("colada", "")
            idn, yy, mat = split_colada(colada_raw)
            id_show = idn if idn else colada_raw
            self.tree.insert(
                "",
                "end",
                iid=str(idx),
                values=(
                    id_show,
                    s.get("objetivo", ""),
                    "Auto" if s.get("auto_saved") else "",
                    s.get("started_at", ""),
                    s.get("ended_at", ""),
                    crisol_displays[idx],
                    len(s.get("ajustes", [])),
                ),
            )
        self._refresh_open_tabs()

    def refresh_catalog(self):
        self._alloy_cache = None
        self._refresh_open_tabs()

    def _refresh_open_tabs(self):
        for idx, data in list(self._session_tabs.items()):
            if idx < 0 or idx >= len(self.hist):
                self._close_session_tab(idx)
                continue
            self._fill_session_tab(idx)

    def generate_quality_report_for_selected(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Historial", "Selecciona una colada primero.", parent=self)
            return
        idx = int(sel[0])
        self._generate_quality_report(idx)

    def view_selected_in_adjust(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Historial", "Selecciona una colada primero.", parent=self)
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.hist):
            return
        if self._adjust_tab is None or self._root_notebook is None:
            messagebox.showerror("Historial", "La pestaña Ajuste no esta disponible.", parent=self)
            return
        try:
            self._adjust_tab.enter_view_session(self.hist[idx], history_index=idx)
            self._root_notebook.select(self._adjust_tab)
        except Exception as ex:
            messagebox.showerror("Historial", f"No se pudo visualizar la sesion en Ajuste.\n\n{ex}", parent=self)

    def _generate_quality_report(self, idx):
        if idx < 0 or idx >= len(self.hist):
            return
        if self._quality_tab is None or self._root_notebook is None:
            messagebox.showerror("Historial", "La pesta?a de Calidad no esta disponible.", parent=self)
            return
        session = self.hist[idx]
        try:
            selected = self._pick_quality_materials(session)
            if selected is None:
                return
            if not selected:
                messagebox.showinfo("Historial", "No seleccionaste materiales para generar.", parent=self)
                return
            count = self._quality_tab.generate_reports_from_history_session(session, selected_materials=selected)
            self._root_notebook.select(self._quality_tab)
            if count:
                messagebox.showinfo("Historial", f"Se generaron/actualizaron {count} informes de calidad.", parent=self)
        except Exception as ex:
            messagebox.showerror("Historial", f"No se pudo generar el informe de calidad.\n\n{ex}", parent=self)

    def _pick_quality_materials(self, session):
        info = self._quality_tab.get_material_options_for_session(session)
        materials = info.get("materials", [])
        if not materials:
            return []

        picked = {"value": None}
        win = tk.Toplevel(self)
        win.title("Generar informe de calidad")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(False, False)

        box = ttk.Frame(win, padding=12)
        box.pack(fill="both", expand=True)

        family = info.get("family", "")
        lote = info.get("lote", "")
        base = info.get("base", "")
        base_display = info.get("base_display", base)
        material_base = str(info.get("material_base", "") or "").strip()
        material_inferido = str(info.get("material_inferido", "") or "").strip()
        default_materials = set(str(m) for m in (info.get("default_materials", []) or []))
        ttk.Label(box, text=f"Base {base_display} - {family}".strip(" -")).pack(anchor="w")
        if lote:
            ttk.Label(box, text=lote).pack(anchor="w", pady=(0, 8))
        ttk.Label(box, text="Selecciona los materiales a generar:").pack(anchor="w", pady=(0, 6))

        checks = ttk.LabelFrame(box, text="Materiales", padding=8)
        checks.pack(fill="x", expand=True)
        # Materiales que tienen cucharas cargadas en esta sesion
        ladle_entry = self._ladle_entry_for_session(session)
        ladle_materials = set()
        if ladle_entry:
            for row in ladle_entry.get("rows", []):
                mat = str(row.get("material_final", "") or "").strip()
                qty = int(row.get("cantidad", 0) or 0)
                if mat and qty > 0:
                    ladle_materials.add(mat)

        vars_by_material = []
        for material in materials:
            if ladle_materials:
                checked = material in ladle_materials
            elif default_materials:
                checked = material in default_materials
            else:
                checked = (
                    (material == material_base and material_base in materials)
                    or (material == material_inferido and material_inferido in materials)
                )
            var = tk.BooleanVar(value=checked)
            ttk.Checkbutton(checks, text=f"Material {material}", variable=var).pack(anchor="w")
            vars_by_material.append((material, var))

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(10, 0))

        def accept():
            picked["value"] = [material for material, var in vars_by_material if var.get()]
            win.destroy()

        def cancel():
            picked["value"] = None
            win.destroy()

        ttk.Button(btns, text="Aceptar", command=accept).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=cancel).pack(side="right", padx=6)

        win.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_width()) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{x}+{y}")
        win.wait_window()
        return picked["value"]

    # ---------------------------- dock tabs --------------------------------
    def _open_session_tab(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = int(sel[0])
        if idx < 0 or idx >= len(self.hist):
            return

        if idx in self._session_tabs:
            tab = self._session_tabs[idx]["frame"]
            self.nb.select(tab)
            self._fill_session_tab(idx)
            return

        s = self.hist[idx]
        tab = ttk.Frame(self.nb, padding=8)
        self.nb.add(tab, text=self._session_title(s))
        self.nb.select(tab)

        colada_display = ttk.Label(tab, text="", font=("TkDefaultFont", 22, "bold"))
        colada_display.pack(anchor="w", pady=(0, 4))

        summary = ttk.Label(tab, text="", justify="left")
        summary.pack(anchor="w", pady=(0, 6))

        session_nb = ttk.Notebook(tab)
        session_nb.pack(fill="both", expand=True)

        tab_activity = ttk.Frame(session_nb, padding=0)
        tab_carbon = ttk.Frame(session_nb, padding=6)
        tab_ladles = ttk.Frame(session_nb, padding=6)
        tab_thermal = ttk.Frame(session_nb, padding=6)
        session_nb.add(tab_activity, text="Ajustes / Calculos")
        session_nb.add(tab_carbon, text="Carbono")
        session_nb.add(tab_ladles, text="Cucharas")
        session_nb.add(tab_thermal, text="Analisis termico")

        # Split solo para Ajustes / Calculos + detalle.
        split = ttk.PanedWindow(tab_activity, orient="vertical")
        split.pack(fill="both", expand=True)

        top = ttk.Frame(split)
        bottom = ttk.Frame(split)
        split.add(top, weight=3)
        split.add(bottom, weight=2)

        top_nb = ttk.Notebook(top)
        top_nb.pack(fill="both", expand=True)

        tab_adj = ttk.Frame(top_nb, padding=6)
        top_nb.add(tab_adj, text="Ajustes aplicados")
        tree_adj = ttk.Treeview(tab_adj, columns=("fecha", "porc", "ce_est", "resumen"), show="headings", height=12)
        for cid, title, w in (
            ("fecha", "Fecha/Hora", 160),
            ("porc", "%", 40),
            ("ce_est", "CE est.", 80),
            ("resumen", "Materiales", 520),
        ):
            tree_adj.heading(cid, text=title)
            tree_adj.column(cid, width=w, anchor="w")
        tree_adj.pack(fill="both", expand=True)

        tab_calc = ttk.Frame(top_nb, padding=6)
        top_nb.add(tab_calc, text="Calculos")
        tree_calc = ttk.Treeview(tab_calc, columns=("fecha", "porc", "ce_est", "resumen"), show="headings", height=12)
        for cid, title, w in (
            ("fecha", "Fecha/Hora", 160),
            ("porc", "%", 40),
            ("ce_est", "CE est.", 80),
            ("resumen", "Materiales", 520),
        ):
            tree_calc.heading(cid, text=title)
            tree_calc.column(cid, width=w, anchor="w")
        tree_calc.pack(fill="both", expand=True)

        carbon_summary = ttk.Label(tab_carbon, text="", justify="left")
        carbon_summary.pack(anchor="w", pady=(0, 8))
        carbon_box = ttk.LabelFrame(tab_carbon, text="Carbomax aplicado durante la sesion", padding=6)
        carbon_box.pack(fill="both", expand=True)
        tree_carbon = ttk.Treeview(
            carbon_box,
            columns=("fecha", "inicio", "fuente", "c", "si", "ce", "ajuste", "resumen"),
            show="headings",
            height=14,
        )
        for cid, title, w in (
            ("fecha", "Aplicado", 150),
            ("inicio", "Analisis", 140),
            ("fuente", "Fuente", 180),
            ("c", "C %", 70),
            ("si", "Si %", 70),
            ("ce", "CE %", 70),
            ("ajuste", "Ajuste", 150),
            ("resumen", "Materiales", 360),
        ):
            tree_carbon.heading(cid, text=title)
            tree_carbon.column(cid, width=w, anchor="w")
        tree_carbon.pack(fill="both", expand=True)

        ladles_summary_box = ttk.LabelFrame(tab_ladles, text="Cantidad total por material", padding=6)
        ladles_summary_box.pack(fill="x")
        tree_ladles_summary = ttk.Treeview(
            ladles_summary_box,
            columns=("material", "total"),
            show="headings",
            height=5,
        )
        for cid, title, w in (
            ("material", "Material", 180),
            ("total", "cantidad total de cada material", 260),
        ):
            tree_ladles_summary.heading(cid, text=title)
            tree_ladles_summary.column(cid, width=w, anchor="w")
        tree_ladles_summary.pack(fill="x", expand=True)

        ladles_metrics = ttk.Frame(tab_ladles)
        ladles_metrics.pack(fill="x", pady=(12, 12))
        ladle_metric_values = {}
        for col, (key, title) in enumerate((
            ("first", "tiempo primera"),
            ("last", "tiempo ultima"),
            ("duration", "tiempo entre primera y ultima"),
            ("avg", "tiempo promedio entre cada una"),
        )):
            box = ttk.LabelFrame(ladles_metrics, text=title, padding=8)
            box.grid(row=0, column=col, sticky="nsew", padx=(0, 6))
            value = ttk.Label(box, text="", font=("TkDefaultFont", 10, "bold"))
            value.pack(anchor="w")
            ladle_metric_values[key] = value
            ladles_metrics.columnconfigure(col, weight=1)

        ladles_events_box = ttk.LabelFrame(tab_ladles, text="Registro cronologico", padding=6)
        ladles_events_box.pack(fill="both", expand=True)
        tree_ladles_events = ttk.Treeview(
            ladles_events_box,
            columns=("material", "tiempo"),
            show="headings",
            height=14,
        )
        for cid, title, w in (
            ("material", "material", 180),
            ("tiempo", "tiempo", 240),
        ):
            tree_ladles_events.heading(cid, text=title)
            tree_ladles_events.column(cid, width=w, anchor="w")
        tree_ladles_events.pack(fill="both", expand=True)
        ladles_btns = ttk.Frame(tab_ladles)
        ladles_btns.pack(fill="x", pady=(6, 0))
        ttk.Button(ladles_btns, text="Editar cucharas",
                   command=lambda i=idx: self._edit_ladles_dialog(i)).pack(side="left")
        ttk.Button(ladles_btns, text="Cerrar pestaña",
                   command=lambda: self._close_session_tab(idx)).pack(side="right")

        thermal_summary = ttk.Label(tab_thermal, text="", justify="left")
        thermal_summary.pack(anchor="w", pady=(0, 8))
        thermal_box = ttk.LabelFrame(tab_thermal, text="Analisis adjuntos", padding=6)
        thermal_box.pack(fill="both", expand=True)
        tree_thermal = ttk.Treeview(
            thermal_box,
            columns=("fecha", "modo", "base", "obs", "archivo", "tse", "tre", "rec", "tf", "pts"),
            show="headings",
            height=14,
        )
        for cid, title, w in (
            ("fecha", "Adjuntado", 150),
            ("modo", "Modo", 120),
            ("base", "Material base", 110),
            ("obs", "Observacion", 180),
            ("archivo", "Archivo", 160),
            ("tse", "TSE", 70),
            ("tre", "TRE", 70),
            ("rec", "REC", 70),
            ("tf", "TF", 70),
            ("pts", "Puntos", 70),
        ):
            tree_thermal.heading(cid, text=title)
            tree_thermal.column(cid, width=w, anchor="w")
        tree_thermal.pack(fill="both", expand=True)
        tree_thermal.bind("<Double-Button-1>", lambda e: self._open_thermal_in_analysis_tab(idx))
        thermal_btns = ttk.Frame(tab_thermal)
        thermal_btns.pack(fill="x", pady=(6, 0))
        ttk.Button(thermal_btns, text="Desvincular", command=lambda i=idx: self._detach_thermal_from_session(i)).pack(side="left")
        ttk.Button(thermal_btns, text="Editar", command=lambda i=idx: self._edit_thermal_in_session(i)).pack(side="left", padx=(6, 0))
        ttk.Button(thermal_btns, text="Cerrar pestaÃ±a", command=lambda: self._close_session_tab(idx)).pack(side="right")

        # Detalle (dock interno)
        detail_nb = ttk.Notebook(bottom)
        detail_nb.pack(fill="both", expand=True)
        detail_tab = ttk.Frame(detail_nb, padding=6)
        detail_nb.add(detail_tab, text="Detalle")

        # Detalle contenido
        d_split = ttk.PanedWindow(detail_tab, orient="horizontal")
        d_split.pack(fill="both", expand=True)
        d_left = ttk.Frame(d_split)
        d_right = ttk.Frame(d_split)
        d_split.add(d_left, weight=2)
        d_split.add(d_right, weight=1)

        # Composicion (izq)
        box = ttk.LabelFrame(d_left, text="Composicion (%)", padding=6)
        box.pack(fill="both", expand=True)
        sf = ScrollFrame(box); sf.pack(fill="both", expand=True)
        head = ttk.Frame(sf.inner)
        head.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Label(head, text="Elemento", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=6)
        ttk.Label(head, text="Inicial", font=("Segoe UI", 10, "bold")).grid(row=0, column=1, padx=6)
        ttk.Label(head, text="Estimado", font=("Segoe UI", 10, "bold")).grid(row=0, column=2, padx=6)
        ttk.Label(head, text="Objetivo", font=("Segoe UI", 10, "bold")).grid(row=0, column=3, padx=6)
        comp_rows = []
        for i, el in enumerate(ELEMENTS, start=1):
            r = ttk.Frame(sf.inner); r.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            ttk.Label(r, text=el, width=6).grid(row=0, column=0, padx=4)
            e_ini = ttk.Entry(r, width=12, state="readonly")
            e_est = ttk.Entry(r, width=12, state="readonly")
            e_obj = ttk.Entry(r, width=12, state="readonly")
            e_ini.grid(row=0, column=1, padx=4); e_est.grid(row=0, column=2, padx=4); e_obj.grid(row=0, column=3, padx=4)
            comp_rows.append((el, e_ini, e_est, e_obj))

        # Cambios + Materiales (der)
        box_changes = ttk.LabelFrame(d_right, text="Cambios", padding=6)
        box_changes.pack(fill="both", expand=True)
        tree_changes = ttk.Treeview(box_changes, columns=("el", "ini", "fin"), show="headings", height=12)
        for cid, title, w in (("el", "Elemento", 80), ("ini", "Inicial", 120), ("fin", "Final", 120)):
            tree_changes.heading(cid, text=title)
            tree_changes.column(cid, width=w, anchor="w")
        tree_changes.pack(fill="both", expand=True)

        box_mats = ttk.LabelFrame(d_right, text="Materiales", padding=6)
        box_mats.pack(fill="both", expand=True, pady=(6, 0))
        tree_mats = ttk.Treeview(box_mats, columns=("mat", "kg"), show="headings", height=10)
        tree_mats.heading("mat", text="Material")
        tree_mats.heading("kg", text="kg")
        tree_mats.column("mat", width=200, anchor="w")
        tree_mats.column("kg", width=80, anchor="e")
        tree_mats.pack(fill="both", expand=True)

        # Botones solo para Ajustes / Calculos
        btns = ttk.Frame(tab_activity)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Editar ajuste", command=lambda: self._edit_adjustment_in_session(idx)).pack(side="left")
        ttk.Button(btns, text="Eliminar ajuste", command=lambda: self._delete_adjustment_in_session(idx)).pack(side="left", padx=6)
        ttk.Button(btns, text="Resumen de ajustes", command=lambda: self._show_resumen_ajustes(idx)).pack(side="left", padx=6)
        ttk.Button(btns, text="PDF composicion final", command=lambda: self._export_final_composition_pdf_for_session(idx)).pack(side="left", padx=6)
        ttk.Button(btns, text="CSV composicion final", command=lambda: self._export_final_composition_csv_for_session(idx)).pack(side="left", padx=6)
        ttk.Button(btns, text="Cerrar pestaña", command=lambda: self._close_session_tab(idx)).pack(side="right")

        tree_adj.bind(
            "<Double-Button-1>",
            lambda e: self._open_detail_in_tab(idx, "ajuste", tree_adj.index(tree_adj.selection()[0]) if tree_adj.selection() else None),
        )
        tree_calc.bind(
            "<Double-Button-1>",
            lambda e: self._open_detail_in_tab(idx, "calculo", tree_calc.index(tree_calc.selection()[0]) if tree_calc.selection() else None),
        )

        self._session_tabs[idx] = {
            "frame": tab,
            "colada_display": colada_display,
            "summary": summary,
            "tree_adj": tree_adj,
            "tree_calc": tree_calc,
            "carbon_summary": carbon_summary,
            "tree_carbon": tree_carbon,
            "tree_ladles_summary": tree_ladles_summary,
            "tree_ladles_events": tree_ladles_events,
            "ladle_metric_values": ladle_metric_values,
            "thermal_summary": thermal_summary,
            "tree_thermal": tree_thermal,
            "thermal_items": [],
            "detail_nb": detail_nb,
            "detail_tab": detail_tab,
            "comp_rows": comp_rows,
            "tree_changes": tree_changes,
            "tree_mats": tree_mats,
            "detail_kind": None,
            "detail_row": None,
        }
        self._fill_session_tab(idx)

    def _close_session_tab(self, idx):
        data = self._session_tabs.pop(idx, None)
        if not data:
            return
        tab = data.get("frame")
        if tab:
            self.nb.forget(tab)

    def _session_title(self, session):
        colada = session.get("colada", "")
        start = session.get("started_at", "")
        return f"{colada} - {start}"

    def _detail_title(self, session, kind, entry, row_idx=None):
        colada = session.get("colada", "")
        fecha = entry.get("fecha", "")
        label = "ajuste" if kind == "ajuste" else "calculo"
        num = f" {row_idx + 1}" if isinstance(row_idx, int) else ""
        return f"{colada} - {label}{num} {fecha}"

    def _fill_session_tab(self, idx):
        if idx < 0 or idx >= len(self.hist):
            return
        s = self.hist[idx]
        data = self._session_tabs.get(idx)
        if not data:
            return
        data["colada_display"].config(text=s.get("colada", ""))
        data["summary"].config(text=self._summary_text(s))
        try:
            self.nb.tab(data["frame"], text=self._session_title(s))
        except Exception:
            pass
        tree_adj = data["tree_adj"]
        tree_calc = data["tree_calc"]
        carbon_summary = data["carbon_summary"]
        tree_carbon = data["tree_carbon"]
        tree_ladles_summary = data["tree_ladles_summary"]
        tree_ladles_events = data["tree_ladles_events"]
        ladle_metric_values = data["ladle_metric_values"]
        thermal_summary = data["thermal_summary"]
        tree_thermal = data["tree_thermal"]
        for i in tree_adj.get_children():
            tree_adj.delete(i)
        for it in s.get("ajustes", []):
            ce_est = it.get("ce_estimado", "")
            ce_est = fmt(ce_est, 4) if isinstance(ce_est, (int, float)) else (ce_est or "")
            tree_adj.insert("", "end", values=(it.get("fecha", ""), it.get("porcentaje", ""), ce_est, it.get("resumen", "")))
        for i in tree_calc.get_children():
            tree_calc.delete(i)
        for it in s.get("calculos", []):
            ce_est = it.get("ce_estimado", "")
            ce_est = fmt(ce_est, 4) if isinstance(ce_est, (int, float)) else (ce_est or "")
            tree_calc.insert("", "end", values=(it.get("fecha", ""), it.get("porcentaje", ""), ce_est, it.get("resumen", "")))
        for tree in (tree_carbon, tree_ladles_summary, tree_ladles_events, tree_thermal):
            for item in tree.get_children():
                tree.delete(item)
        carbon_items = s.get("carbono", []) if isinstance(s.get("carbono", []), list) else []
        for item in carbon_items:
            if not isinstance(item, dict):
                continue
            ce_val = item.get("ce", "")
            ce_val = fmt(ce_val, 4) if isinstance(ce_val, (int, float)) else (ce_val or "")
            tree_carbon.insert(
                "",
                "end",
                values=(
                    item.get("fecha", ""),
                    item.get("dt_inicio", "") or item.get("dt_termino", ""),
                    item.get("source_name", ""),
                    fmt(item.get("carbono", 0), 4),
                    fmt(item.get("silicio", 0), 4),
                    ce_val,
                    item.get("ajuste_fecha", ""),
                    item.get("ajuste_resumen", ""),
                ),
            )
        if carbon_items:
            latest = carbon_items[-1] if isinstance(carbon_items[-1], dict) else {}
            carbon_summary.config(
                text=(
                    f"Analisis Carbono aplicados: {len(carbon_items)}\n"
                    f"Ultimo: {latest.get('source_name', '')} | "
                    f"C={fmt(latest.get('carbono', 0), 4)} | Si={fmt(latest.get('silicio', 0), 4)}"
                )
            )
        else:
            carbon_summary.config(text="Sin analisis Carbono aplicados por Carbomax automatico.")
        for label in ladle_metric_values.values():
            label.config(text="")
        ladle_entry = self._ladle_entry_for_session(s)
        if ladle_entry:
            all_events = self._all_ladle_events(ladle_entry)
            stats = ladle_entry.get("statistics", {})
            ladle_metric_values["first"].config(text=str(stats.get("first_saved_at", "") or ""))
            ladle_metric_values["last"].config(text=str(stats.get("last_saved_at", "") or ""))
            ladle_metric_values["duration"].config(text=str(stats.get("duration_label", "") or ""))
            ladle_metric_values["avg"].config(text=self._avg_ladle_interval_label(all_events))
            rows = ladle_entry.get("rows", []) if isinstance(ladle_entry.get("rows", []), list) else []
            for row in rows:
                material = str(row.get("material_final", "") or "")
                cantidad = int(row.get("cantidad", 0) or 0)
                if cantidad <= 0:
                    continue
                tree_ladles_summary.insert("", "end", values=(material, cantidad))
            for event in all_events:
                tree_ladles_events.insert("", "end", values=(event.get("material", ""), event.get("time", "")))
        if not tree_ladles_summary.get_children():
            tree_ladles_summary.insert("", "end", values=("Sin cucharas cargadas", ""))
        if not tree_ladles_events.get_children():
            tree_ladles_events.insert("", "end", values=("", ""))

        thermal_items = s.get("thermal_analysis", []) if isinstance(s.get("thermal_analysis", []), list) else []
        data["thermal_items"] = list(thermal_items)
        for item in thermal_items:
            if not isinstance(item, dict):
                continue
            info = item.get("info", {}) if isinstance(item.get("info"), dict) else {}
            tree_thermal.insert(
                "",
                "end",
                values=(
                    item.get("attached_at", ""),
                    info.get("Modo", ""),
                    item.get("material_base", ""),
                    item.get("observacion", ""),
                    item.get("source_name", ""),
                    info.get("TSE", ""),
                    info.get("TRE", ""),
                    info.get("REC", ""),
                    info.get("TF", ""),
                    item.get("point_count", ""),
                ),
            )
        if thermal_items:
            latest = thermal_items[-1] if isinstance(thermal_items[-1], dict) else {}
            latest_info = latest.get("info", {}) if isinstance(latest.get("info"), dict) else {}
            thermal_summary.config(
                text=(
                    f"Analisis termicos adjuntos: {len(thermal_items)}\n"
                    f"Ultimo archivo: {latest.get('source_name', '')}\n"
                    f"TSE: {latest_info.get('TSE', '')} | TRE: {latest_info.get('TRE', '')} | "
                    f"REC: {latest_info.get('REC', '')} | TF: {latest_info.get('TF', '')}"
                )
            )
        else:
            thermal_summary.config(text="Sin analisis termicos adjuntos.")

        # Si habia detalle seleccionado, re-pintar
        if data["detail_kind"] is not None and data["detail_row"] is not None:
            self._open_detail_in_tab(idx, data["detail_kind"], data["detail_row"])

    def _summary_text(self, session):
        ladle_entry = self._ladle_entry_for_session(session)
        ladles_count = int((ladle_entry or {}).get("total_cucharas", 0) or 0)
        return (
            f"Objetivo: {session.get('objetivo', '')}\n"
            f"Guardado: {'Automatico' if session.get('auto_saved') else 'Manual'}\n"
            f"Inicio: {session.get('started_at', '')}\n"
            f"Fin: {session.get('ended_at', '')}\n"
            f"Ajustes: {len(session.get('ajustes', []))} | Calculos: {len(session.get('calculos', []))} | "
            f"Carbono: {len(session.get('carbono', []) or [])} | Cucharas: {ladles_count} | "
            f"Analisis termico: {len(session.get('thermal_analysis', []) or [])}"
        )

    def _open_thermal_in_analysis_tab(self, idx):
        data = self._session_tabs.get(idx)
        if not data:
            return
        tree_thermal = data.get("tree_thermal")
        if tree_thermal is None:
            return
        selection = tree_thermal.selection()
        if not selection:
            return
        row_idx = tree_thermal.index(selection[0])
        thermal_items = data.get("thermal_items", [])
        if row_idx < 0 or row_idx >= len(thermal_items):
            return
        item = thermal_items[row_idx]
        if not isinstance(item, dict):
            return
        source_file = str(item.get("source_file", "") or "").strip()
        if not source_file:
            messagebox.showinfo("Historial", "Este analisis termico no tiene origen vinculado.", parent=self)
            return
        if self._thermal_tab is None or self._root_notebook is None:
            messagebox.showerror("Historial", "La pestaÃ±a de Analisis termico no esta disponible.", parent=self)
            return
        if not self._thermal_tab.open_records([source_file], additive=True):
            messagebox.showerror(
                "Historial",
                "No se pudo encontrar ese analisis en la pestaÃ±a de Analisis termico.",
                parent=self,
            )
            return
        self._root_notebook.select(self._thermal_tab)

    def _detach_thermal_from_session(self, idx):
        data = self._session_tabs.get(idx)
        if not data:
            return
        tree_thermal = data.get("tree_thermal")
        if tree_thermal is None:
            return
        selection = tree_thermal.selection()
        if not selection:
            messagebox.showinfo("Historial", "Selecciona un analisis termico para desvincular.", parent=self)
            return
        row_idx = tree_thermal.index(selection[0])
        thermal_items = data.get("thermal_items", [])
        if row_idx < 0 or row_idx >= len(thermal_items):
            return
        if idx < 0 or idx >= len(self.hist):
            return
        session = self.hist[idx]
        if not messagebox.askyesno(
            "Historial",
            "¿Desvincular el analisis termico seleccionado de esta colada?",
            parent=self,
        ):
            return
        try:
            detach_thermal_analysis(session.get("colada", ""), row_idx)
        except Exception as ex:
            messagebox.showerror("Historial", f"No se pudo desvincular el analisis termico.\n\n{ex}", parent=self)
            return
        self.refresh()
        try:
            self.event_generate("<<HistoryUpdated>>", when="tail")
        except Exception:
            pass

    def _edit_thermal_in_session(self, idx):
        data = self._session_tabs.get(idx)
        if not data:
            return
        tree_thermal = data.get("tree_thermal")
        if tree_thermal is None:
            return
        selection = tree_thermal.selection()
        if not selection:
            messagebox.showinfo("Historial", "Selecciona un analisis termico para editar.", parent=self)
            return
        row_idx = tree_thermal.index(selection[0])
        thermal_items = data.get("thermal_items", [])
        if row_idx < 0 or row_idx >= len(thermal_items):
            return
        entry = thermal_items[row_idx]
        if not isinstance(entry, dict):
            return
        if idx < 0 or idx >= len(self.hist):
            return
        session = self.hist[idx]
        colada = str(session.get("colada", "") or "").strip()
        source_file = str(entry.get("source_file", "") or "").strip()
        if not colada or not source_file:
            messagebox.showinfo("Historial", "Este analisis no tiene origen vinculado para editar.", parent=self)
            return
        self._open_thermal_edit_dialog(colada, source_file, entry)

    def _open_thermal_edit_dialog(self, colada, source_file, entry):
        info = entry.get("info", {}) if isinstance(entry.get("info"), dict) else {}
        mode_group = _thermal_mode_group(info.get("Modo", ""))

        win = tk.Toplevel(self)
        win.title("Editar vinculo de analisis termico")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(False, False)

        box = ttk.Frame(win, padding=12)
        box.pack(fill="both", expand=True)

        ttk.Label(box, text=f"Colada: {colada}").grid(row=0, column=0, columnspan=2, sticky="w", pady=(0, 4))
        ttk.Label(box, text=f"Modo: {mode_group or 'Desconocido'}").grid(
            row=1, column=0, columnspan=2, sticky="w", pady=(0, 8)
        )

        var_orden = tk.StringVar()
        var_etapa = tk.StringVar()
        var_obs = tk.StringVar(value=str(entry.get("observacion", "") or ""))

        if mode_group == "Carbono":
            ttk.Label(box, text="Orden").grid(row=2, column=0, sticky="w", pady=(0, 6))
            orden = entry.get("orden")
            var_orden.set(str(int(orden)) if isinstance(orden, (int, float)) else "")
            ttk.Entry(box, textvariable=var_orden, width=10).grid(row=2, column=1, sticky="w", pady=(0, 6))
        else:
            ttk.Label(box, text="Etapa").grid(row=2, column=0, sticky="w", pady=(0, 6))
            var_etapa.set(str(entry.get("etapa_muestra", "") or ""))
            momentos = load_inoc_momentos()
            etapas = [str(m.get("label", "") or "").strip() for m in momentos if isinstance(m, dict)]
            etapas = [e for e in etapas if e]
            ttk.Combobox(box, textvariable=var_etapa, values=etapas, state="readonly", width=22).grid(
                row=2, column=1, sticky="ew", pady=(0, 6)
            )

        ttk.Label(box, text="Observacion").grid(row=3, column=0, sticky="w", pady=(0, 6))
        ttk.Entry(box, textvariable=var_obs, width=32).grid(row=3, column=1, sticky="ew", pady=(0, 6))

        def _save():
            patch = {"observacion": var_obs.get().strip()}
            if mode_group == "Carbono":
                raw = var_orden.get().strip()
                if raw:
                    try:
                        patch["orden"] = int(raw)
                    except ValueError:
                        messagebox.showwarning("Historial", "El orden debe ser un numero entero.", parent=win)
                        return
                else:
                    patch["orden"] = None
            else:
                patch["etapa_muestra"] = var_etapa.get().strip()
            try:
                set_thermal_analysis_field(colada, source_file, patch)
            except Exception as ex:
                messagebox.showerror("Historial", f"No se pudo guardar el vinculo.\n\n{ex}", parent=win)
                return
            win.destroy()
            self.refresh()
            try:
                self.event_generate("<<HistoryUpdated>>", when="tail")
            except Exception:
                pass

        footer = ttk.Frame(box)
        footer.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(10, 0))
        ttk.Button(footer, text="Cancelar", command=win.destroy).pack(side="right", padx=(6, 0))
        ttk.Button(footer, text="Guardar", command=_save).pack(side="right")

        win.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_width()) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{x}+{y}")
        win.wait_window()

    def _ladle_entries_for_session(self, session):
        entry = self._ladle_entry_for_session(session)
        return [entry] if entry else []

    def _ladle_colada_key(self, session):
        idn, yy, _ = split_colada(session.get("colada", ""))
        if not idn:
            return str(session.get("colada", "")).strip()
        return f"{int(idn):04d} /{str(yy).zfill(2)}"

    def _edit_ladles_dialog(self, idx):
        if idx < 0 or idx >= len(self.hist):
            return
        session = self.hist[idx]
        ladle_entry = self._ladle_entry_for_session(session)
        colada_key  = self._ladle_colada_key(session)

        # Obtener materiales disponibles (de la entrada existente o vacío)
        rows = (ladle_entry or {}).get("rows", [])
        if not rows:
            from tkinter import messagebox
            messagebox.showinfo("Editar cucharas",
                                "No hay registro de cucharas para esta sesión.",
                                parent=self)
            return

        dlg = tk.Toplevel(self)
        dlg.title(f"Editar cucharas — {session.get('colada', '')}")
        dlg.resizable(False, False)
        dlg.grab_set()

        ttk.Label(dlg, text=f"Sesión: {session.get('colada', '')}",
                  font=("TkDefaultFont", 10, "bold")).pack(anchor="w", padx=14, pady=(12, 2))
        ttk.Label(dlg, text="Modificá la cantidad de cucharas por material.",
                  foreground="#666").pack(anchor="w", padx=14, pady=(0, 8))

        frame = ttk.Frame(dlg, padding=(14, 0, 14, 0))
        frame.pack(fill="x")

        count_vars = {}
        for i, row in enumerate(rows):
            mat = str(row.get("material_final", "") or "")
            qty = int(row.get("cantidad", 0) or 0)
            ttk.Label(frame, text=mat, width=22, anchor="w").grid(row=i, column=0, padx=(0, 8), pady=3)
            var = tk.IntVar(value=qty)
            count_vars[mat] = var
            spin = ttk.Spinbox(frame, from_=0, to=9999, textvariable=var, width=6)
            spin.grid(row=i, column=1, pady=3)
            # Botones +/-
            ttk.Button(frame, text="−", width=2,
                       command=lambda v=var: v.set(max(0, v.get() - 1))).grid(row=i, column=2, padx=2)
            ttk.Button(frame, text="+", width=2,
                       command=lambda v=var: v.set(v.get() + 1)).grid(row=i, column=3)

        ttk.Separator(dlg, orient="horizontal").pack(fill="x", padx=10, pady=10)

        btn_frame = ttk.Frame(dlg)
        btn_frame.pack(fill="x", padx=14, pady=(0, 12))

        def _save():
            new_counts = {mat: max(0, var.get()) for mat, var in count_vars.items()}
            self._save_ladle_counts(colada_key, new_counts, ladle_entry)
            dlg.destroy()
            self._fill_session_tab(idx)

        ttk.Button(btn_frame, text="Guardar", command=_save).pack(side="left")
        ttk.Button(btn_frame, text="Cancelar", command=dlg.destroy).pack(side="left", padx=(6, 0))

        dlg.update_idletasks()
        try:
            rx = self.winfo_rootx() + (self.winfo_width()  - dlg.winfo_width())  // 2
            ry = self.winfo_rooty() + (self.winfo_height() - dlg.winfo_height()) // 2
            dlg.geometry(f"+{rx}+{ry}")
        except Exception:
            pass

    def _save_ladle_counts(self, colada_key, new_counts, old_entry):
        """Actualiza history_by_colada con los nuevos conteos y recalcula estadísticas."""
        from datetime import datetime as _dt
        state = load_ladles_state()
        if not isinstance(state, dict):
            state = {}
        history = state.get("history_by_colada", {})
        if not isinstance(history, dict):
            history = {}

        old = history.get(colada_key, {})
        if isinstance(old, list):
            # Legacy: convertir a dict
            old = {}

        # Reconstruir events a partir de los nuevos counts
        saved_at = _dt.now().isoformat(timespec="seconds")
        old_events = old.get("events", {}) if isinstance(old, dict) else {}
        new_events = {}
        for mat, qty in new_counts.items():
            existing = [e for e in (old_events.get(mat) or []) if isinstance(e, dict) and e.get("saved_at")]
            if len(existing) > qty:
                existing = existing[:qty]
            while len(existing) < qty:
                existing.append({"saved_at": saved_at})
            if existing:
                new_events[mat] = existing

        total = sum(new_counts.values())
        rows  = [{"material_final": m, "cantidad": c} for m, c in new_counts.items() if c > 0]

        # Recalcular estadísticas básicas
        all_times = []
        stat_rows = []
        for mat, evts in new_events.items():
            times = [e.get("saved_at", "") for e in evts if e.get("saved_at")]
            from datetime import datetime as _dt2
            parsed = []
            for t in times:
                try:
                    parsed.append(_dt2.fromisoformat(t))
                except Exception:
                    pass
            first = min(parsed).isoformat(timespec="seconds") if parsed else ""
            last  = max(parsed).isoformat(timespec="seconds") if parsed else ""
            dur   = int((max(parsed) - min(parsed)).total_seconds()) if len(parsed) >= 2 else 0
            all_times.extend(parsed)
            stat_rows.append({
                "material_final": mat, "total": len(evts),
                "first_saved_at": first, "last_saved_at": last,
                "duration_seconds": dur,
            })

        total_dur = int((max(all_times) - min(all_times)).total_seconds()) if len(all_times) >= 2 else 0
        statistics = {
            "rows": stat_rows,
            "total_cucharas": total,
            "first_saved_at": min(all_times).isoformat(timespec="seconds") if all_times else "",
            "last_saved_at":  max(all_times).isoformat(timespec="seconds") if all_times else "",
            "duration_seconds": total_dur,
        }

        history[colada_key] = {
            "updated_at":       saved_at,
            "colada":           colada_key,
            "material_objetivo": (old.get("material_objetivo", "") if isinstance(old, dict) else ""),
            "counts":           new_counts,
            "events":           new_events,
            "statistics":       statistics,
        }
        state["history_by_colada"] = history
        save_ladles_state(state)
        self.ladles = state   # refrescar cache local

    def _ladle_entry_for_session(self, session):
        idn, yy, _ = split_colada(session.get("colada", ""))
        if not idn:
            key = str(session.get("colada", "")).strip()
        else:
            key = f"{int(idn):04d} /{str(yy).zfill(2)}"
        history_by_colada = self.ladles.get("history_by_colada", {}) if isinstance(self.ladles, dict) else {}
        entries = history_by_colada.get(key, [])
        if isinstance(entries, list):
            if not entries:
                return None
            latest = entries[-1] if isinstance(entries[-1], dict) else {}
            rows = latest.get("rows", []) if isinstance(latest.get("rows", []), list) else []
            return {
                "saved_at": latest.get("saved_at", ""),
                "material_objetivo": latest.get("material_objetivo", ""),
                "rows": rows,
                "events": {},
                "total_cucharas": latest.get("total_cucharas", sum(int(row.get("cantidad", 0) or 0) for row in rows)),
                "statistics": {},
            }
        if not isinstance(entries, dict):
            return None
        stats = entries.get("statistics", {}) if isinstance(entries.get("statistics", {}), dict) else {}
        stat_rows = stats.get("rows", []) if isinstance(stats.get("rows", []), list) else []
        rows = []
        if stat_rows:
            for row in stat_rows:
                if not isinstance(row, dict):
                    continue
                rows.append({
                    "material_final": row.get("material_final", ""),
                    "cantidad": row.get("total", 0),
                })
        else:
            counts = entries.get("counts", {}) if isinstance(entries.get("counts", {}), dict) else {}
            rows = [{"material_final": key, "cantidad": value} for key, value in sorted(counts.items())]
        return {
            "saved_at": entries.get("updated_at", ""),
            "material_objetivo": entries.get("material_objetivo", ""),
            "rows": rows,
            "events": entries.get("events", {}) if isinstance(entries.get("events", {}), dict) else {},
            "total_cucharas": stats.get("total_cucharas", sum(int(row.get("cantidad", 0) or 0) for row in rows)),
            "statistics": stats,
        }

    def _ladle_event_times(self, entry, material):
        events = entry.get("events", {}) if isinstance(entry, dict) else {}
        raw = events.get(material, []) if isinstance(events, dict) else []
        if not isinstance(raw, list):
            return []
        out = []
        for item in raw:
            if isinstance(item, dict):
                value = str(item.get("saved_at", "") or "").strip()
            else:
                value = str(item or "").strip()
            if value:
                out.append(value)
        return out

    def _all_ladle_events(self, entry):
        events = entry.get("events", {}) if isinstance(entry, dict) else {}
        out = []
        if not isinstance(events, dict):
            return out
        for material, raw in events.items():
            if not isinstance(raw, list):
                continue
            for item in raw:
                if isinstance(item, dict):
                    value = str(item.get("saved_at", "") or "").strip()
                else:
                    value = str(item or "").strip()
                if value:
                    out.append({"material": str(material), "time": value})
        return sorted(out, key=lambda row: row.get("time", ""))

    def _avg_ladle_interval_label(self, events):
        parsed = []
        for event in events or []:
            try:
                parsed.append(datetime.fromisoformat(str(event.get("time", ""))))
            except Exception:
                pass
        parsed.sort()
        if len(parsed) < 2:
            return ""
        total_seconds = (parsed[-1] - parsed[0]).total_seconds()
        avg_seconds = total_seconds / max(1, len(parsed) - 1)
        return self._duration_label(avg_seconds)

    def _duration_label(self, seconds):
        total = max(0, int(seconds or 0))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    def _open_detail_in_tab(self, session_idx, kind, row_idx):
        if row_idx is None:
            return
        if session_idx < 0 or session_idx >= len(self.hist):
            return
        s = self.hist[session_idx]
        entries = s.get("calculos", []) if kind == "calculo" else s.get("ajustes", [])
        if row_idx < 0 or row_idx >= len(entries):
            return
        entry = entries[row_idx]
        data = self._session_tabs.get(session_idx)
        if not data:
            return

        # Actualizar titulo del tab detalle
        data["detail_nb"].tab(data["detail_tab"], text=self._detail_title(s, kind, entry, row_idx=row_idx))
        data["detail_kind"] = kind
        data["detail_row"] = row_idx

        comp_ini = (entry.get("inicial") or {}).get("comp", {}) or {}
        comp_est = (entry.get("estimado") or {}).get("comp", {}) or {}
        comp_obj = entry.get("objetivo_comp", {}) or self._objective_comp(s)
        for el, e_ini, e_est, e_obj in data["comp_rows"]:
            v1 = comp_ini.get(el, 0.0); v2 = comp_est.get(el, 0.0); v3 = comp_obj.get(el, 0.0)
            for w, val in ((e_ini, v1), (e_est, v2), (e_obj, v3)):
                w.config(state="normal"); w.delete(0, tk.END); w.insert(0, fmt(val)); w.config(state="readonly")

        tree_changes = data["tree_changes"]
        for i in tree_changes.get_children():
            tree_changes.delete(i)
        changes = entry.get("cambios_list", [])
        if not changes:
            for e in ELEMENTS:
                v0 = to_float(comp_ini.get(e, 0.0))
                v1 = to_float(comp_est.get(e, 0.0))
                if abs(v1 - v0) > 1e-12:
                    changes.append((e, v0, v1, v1 - v0))
        for e, v0, v1, _ in changes:
            tree_changes.insert("", "end", values=(e, fmt(v0, 4), fmt(v1, 4)))

        tree_mats = data["tree_mats"]
        for i in tree_mats.get_children():
            tree_mats.delete(i)
        for n, kg in sorted((entry.get("materiales") or {}).items()):
            tree_mats.insert("", "end", values=(n, fmt(kg, 3)))

    # ---------------------------- resumen ajustes --------------------------
    def _show_resumen_ajustes(self, session_idx):
        if session_idx < 0 or session_idx >= len(self.hist):
            return
        s = self.hist[session_idx]
        mats_sum = {}
        for adj in s.get("ajustes", []):
            for name, kg in (adj.get("materiales") or {}).items():
                mats_sum[name] = mats_sum.get(name, 0.0) + to_float(kg)

        win = tk.Toplevel(self)
        win.title(f"Resumen ajustes - {self._session_title(s)}")
        win.transient(self)
        win.geometry("420x420")

        if not mats_sum:
            ttk.Label(win, text="No hay materiales en ajustes.").pack(padx=12, pady=12)
            ttk.Button(win, text="Cerrar", command=win.destroy).pack(pady=(0, 12))
            return

        tree = ttk.Treeview(win, columns=("mat", "kg"), show="headings", height=16)
        tree.heading("mat", text="Material")
        tree.heading("kg", text="kg total")
        tree.column("mat", width=260, anchor="w")
        tree.column("kg", width=100, anchor="e")
        tree.pack(fill="both", expand=True, padx=8, pady=8)

        for name, kg in sorted(mats_sum.items(), key=lambda x: x[1], reverse=True):
            tree.insert("", "end", values=(name, fmt(kg, 3)))

        ttk.Button(win, text="Cerrar", command=win.destroy).pack(pady=(0, 8))

    # ---------------------------- acciones sesion ---------------------------
    def _selected_session_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        return int(sel[0])

    def edit_session_meta(self):
        idx = self._selected_session_index()
        if idx is None:
            messagebox.showinfo("Editar", "Selecciona una sesion.")
            return
        s = self.hist[idx]
        win = tk.Toplevel(self); win.title("Editar colada"); win.transient(self); win.grab_set(); win.resizable(False, False)
        ttk.Label(win, text="Colada (formato: ID /YY - MATERIAL)").pack(anchor="w", padx=10, pady=(10, 4))
        v = tk.StringVar(value=s.get("colada", ""))
        e = ttk.Entry(win, textvariable=v, width=40); e.pack(fill="x", padx=10)
        btns = ttk.Frame(win); btns.pack(fill="x", padx=10, pady=8)
        def save():
            s2 = dict(s); s2["colada"] = v.get().strip()
            try:
                update_session(idx, s2)
            except DuplicateColadaError as ex:
                messagebox.showerror("Editar", str(ex), parent=win)
                return
            self.refresh(); win.destroy()
        ttk.Button(btns, text="Guardar", command=save).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side="right", padx=6)
        e.focus_set(); win.wait_window()

    def _toggle_sinterizado(self):
        idx = self._selected_session_index()
        if idx is None:
            messagebox.showinfo("Sinterizado", "Selecciona una colada primero.", parent=self)
            return
        s = dict(self.hist[idx])
        new_flag = not s.get("primer_sinterizado", False)
        s["primer_sinterizado"] = new_flag
        try:
            update_session(idx, s)
        except DuplicateColadaError as ex:
            messagebox.showerror("Error", str(ex), parent=self)
            return
        self.refresh()
        action = "marcada" if new_flag else "desmarcada"
        messagebox.showinfo(
            "Sinterizado",
            f"Colada {action} como primer horno post-sinterizado.\n"
            f"El conteo de crisol se reinicia desde esta colada.",
            parent=self,
        )

    def delete_session(self):
        idx = self._selected_session_index()
        if idx is None:
            messagebox.showinfo("Eliminar", "Selecciona una sesion.")
            return
        if not messagebox.askyesno("Eliminar", "¿Eliminar la sesion seleccionada?"):
            return
        delete_session(idx)
        self.refresh()

    # ---------------------------- acciones ajuste ---------------------------
    def _edit_adjustment_in_session(self, session_idx):
        data = self._session_tabs.get(session_idx)
        if not data:
            return
        tree = data["tree_adj"]
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Editar", "Selecciona un ajuste.")
            return
        ai = tree.index(sel[0])
        session = self.hist[session_idx]
        adj = session.get("ajustes", [])[ai]
        self._edit_adjust_dialog(session_index=session_idx, adj_index=ai, adj_entry=adj)

    def _delete_adjustment_in_session(self, session_idx):
        data = self._session_tabs.get(session_idx)
        if not data:
            return
        tree = data["tree_adj"]
        sel = tree.selection()
        if not sel:
            messagebox.showinfo("Eliminar", "Selecciona un ajuste.")
            return
        ai = tree.index(sel[0])
        if not messagebox.askyesno("Eliminar", "¿Eliminar el ajuste seleccionado?"):
            return
        delete_adjustment(session_idx, ai)
        self.refresh()

    def _edit_adjust_dialog(self, session_index, adj_index, adj_entry):
        win = tk.Toplevel(self); win.title("Editar ajuste"); win.transient(self); win.grab_set(); win.resizable(False, False)
        win.geometry("540x560")

        ttk.Label(win, text=f"Fecha: {adj_entry.get('fecha', '')}").pack(anchor="w", padx=10, pady=(10, 4))
        ttk.Label(win, text=f"Objetivo: {adj_entry.get('objetivo', '')}").pack(anchor="w", padx=10, pady=(0, 6))

        mats_frame = ttk.LabelFrame(win, text="Materiales (kg)", padding=6)
        mats_frame.pack(fill="both", expand=True, padx=8, pady=6)

        mats = dict(adj_entry.get("materiales", {}))
        var_map = {}
        for name in sorted(mats.keys()):
            row = ttk.Frame(mats_frame); row.pack(fill="x", pady=2)
            ttk.Label(row, text=name, width=28).pack(side="left")
            v = tk.StringVar(value=fmt(to_float(mats.get(name, 0.0)), 3))
            ttk.Entry(row, textvariable=v, width=10).pack(side="left", padx=4)
            var_map[name] = v

        res = ttk.Label(win, text="Estimado: pendiente...")
        res.pack(anchor="w", padx=10, pady=(4, 0))

        btns = ttk.Frame(win); btns.pack(fill="x", padx=8, pady=8)

        def recalc():
            try:
                plan = {n: to_float(v.get()) for n, v in var_map.items() if to_float(v.get()) > 0}
                M0 = adj_entry.get("inicial", {}).get("masa", 0.0)
                comp0 = adj_entry.get("inicial", {}).get("comp", {})
                Mnew, comp_est = self._simulate_with_plan(M0, comp0, plan)
                ce_formula = adj_entry.get("ce_formula", "FUNDICION")
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
            update_adjustment(session_index, adj_index, new_adj)
            self.refresh()
            win.destroy()

        ttk.Button(btns, text="Recalcular estimado", command=recalc).pack(side="left")
        ttk.Button(btns, text="Guardar cambios", command=save).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

    # ---------------------------- export -----------------------------------
    def _selected_adjustment_index(self, session_idx):
        data = self._session_tabs.get(session_idx)
        ajustes = self.hist[session_idx].get("ajustes", []) if 0 <= session_idx < len(self.hist) else []
        tree = data.get("tree_adj") if data else None
        if tree is not None:
            sel = tree.selection()
            if sel:
                return tree.index(sel[0])
        if ajustes:
            return len(ajustes) - 1
        return None

    def _safe_filename_part(self, value):
        text = str(value or "").strip()
        text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
        return text.strip("_") or "sesion"

    def _export_final_composition_pdf_for_session(self, session_idx):
        if session_idx < 0 or session_idx >= len(self.hist):
            return
        session = self.hist[session_idx]
        ajustes = self._session_adjustments(session)
        if not ajustes:
            messagebox.showinfo("Exportar PDF", "Esta sesion no tiene ajustes guardados.", parent=self)
            return
        adj_idx = self._selected_adjustment_index(session_idx)
        if adj_idx is None or adj_idx < 0 or adj_idx >= len(ajustes):
            adj_idx = len(ajustes) - 1
        adj = ajustes[adj_idx]

        colada = self._safe_filename_part(session.get("colada", ""))
        fecha = self._safe_filename_part(adj.get("fecha", ""))
        initialfile = f"composicion_final_{colada}_ajuste_{adj_idx + 1}_{fecha}.pdf"
        fp = filedialog.asksaveasfilename(
            defaultextension=".pdf",
            filetypes=[("PDF", "*.pdf")],
            title="Exportar composicion final a PDF",
            initialfile=initialfile,
            parent=self,
        )
        if not fp:
            return
        try:
            self._write_final_composition_pdf(fp, session, adj, adj_idx)
        except ImportError:
            messagebox.showerror(
                "Exportar PDF",
                "No se pudo importar reportlab. Instala reportlab para exportar PDF.",
                parent=self,
            )
        except Exception as ex:
            messagebox.showerror("Exportar PDF", f"No se pudo generar el PDF.\n\n{ex}", parent=self)
        else:
            messagebox.showinfo("Exportar PDF", f"PDF generado:\n{fp}", parent=self)

    def _export_final_composition_csv_for_session(self, session_idx):
        if session_idx < 0 or session_idx >= len(self.hist):
            return
        session = self.hist[session_idx]
        ajustes = self._session_adjustments(session)
        if not ajustes:
            messagebox.showinfo("Exportar CSV", "Esta sesion no tiene ajustes guardados.", parent=self)
            return
        adj_idx = self._selected_adjustment_index(session_idx)
        if adj_idx is None or adj_idx < 0 or adj_idx >= len(ajustes):
            adj_idx = len(ajustes) - 1
        adj = ajustes[adj_idx]

        colada = self._safe_filename_part(session.get("colada", ""))
        fecha = self._safe_filename_part(adj.get("fecha", ""))
        initialfile = f"composicion_final_{colada}_ajuste_{adj_idx + 1}_{fecha}.csv"
        fp = filedialog.asksaveasfilename(
            defaultextension=".csv",
            filetypes=[("CSV", "*.csv")],
            title="Exportar composicion final a CSV",
            initialfile=initialfile,
            parent=self,
        )
        if not fp:
            return
        try:
            self._write_final_composition_csv(fp, session, adj, adj_idx)
        except Exception as ex:
            messagebox.showerror("Exportar CSV", f"No se pudo generar el CSV.\n\n{ex}", parent=self)
        else:
            messagebox.showinfo("Exportar CSV", f"CSV generado:\n{fp}", parent=self)

    def _session_adjustments(self, session):
        ajustes = session.get("ajustes", [])
        return ajustes if isinstance(ajustes, list) else []

    def _final_composition_export_data(self, session, adj, adj_idx):
        inicial = adj.get("inicial", {}) if isinstance(adj.get("inicial", {}), dict) else {}
        estimado = adj.get("estimado", {}) if isinstance(adj.get("estimado", {}), dict) else {}
        comp_ini = inicial.get("comp", {}) if isinstance(inicial.get("comp", {}), dict) else {}
        comp_fin = estimado.get("comp", {}) if isinstance(estimado.get("comp", {}), dict) else {}
        comp_obj = adj.get("objetivo_comp", {}) if isinstance(adj.get("objetivo_comp", {}), dict) else {}
        if not comp_obj:
            comp_obj = self._objective_comp(session)

        info_rows = [
            ["Campo", "Valor"],
            ["Colada", session.get("colada", "")],
            ["Objetivo", session.get("objetivo", "") or adj.get("objetivo", "")],
            ["Inicio sesion", session.get("started_at", "")],
            ["Fin sesion", session.get("ended_at", "")],
            ["Ajuste", str(adj_idx + 1)],
            ["Fecha ajuste", adj.get("fecha", "")],
            ["Masa inicial kg", fmt(inicial.get("masa", 0), 3)],
            ["Masa final kg", fmt(estimado.get("masa", 0), 3)],
            ["CE inicial", fmt(adj.get("ce_inicial", ""), 4) if adj.get("ce_inicial", "") != "" else ""],
            ["CE final", fmt(adj.get("ce_estimado", ""), 4) if adj.get("ce_estimado", "") != "" else ""],
            ["CE objetivo", fmt(adj.get("ce_objetivo", ""), 4) if adj.get("ce_objetivo", "") != "" else ""],
            ["Formula CE", adj.get("ce_formula", "")],
        ]

        comp_rows = [["Elemento", "Inicial %", "Final %", "Objetivo %", "Delta final-objetivo"]]
        for el in ELEMENTS:
            v_ini = to_float(comp_ini.get(el, 0.0))
            v_fin = to_float(comp_fin.get(el, 0.0))
            v_obj = to_float(comp_obj.get(el, 0.0))
            if abs(v_ini) > 1e-12 or abs(v_fin) > 1e-12 or abs(v_obj) > 1e-12:
                comp_rows.append([el, fmt(v_ini, 4), fmt(v_fin, 4), fmt(v_obj, 4), fmt(v_fin - v_obj, 4)])
        if len(comp_rows) == 1:
            comp_rows.append(["Sin datos", "", "", "", ""])

        mats = adj.get("materiales", {}) if isinstance(adj.get("materiales", {}), dict) else {}
        mat_rows = [["Material", "kg"]]
        for name, kg in sorted(mats.items()):
            mat_rows.append([str(name), fmt(kg, 3)])
        if len(mat_rows) == 1:
            mat_rows.append(["Sin materiales", ""])
        return info_rows, comp_rows, mat_rows

    def _write_final_composition_csv(self, fp, session, adj, adj_idx):
        info_rows, comp_rows, mat_rows = self._final_composition_export_data(session, adj, adj_idx)
        with open(fp, "w", encoding="utf-8-sig", newline="") as f:
            writer = csv.writer(f, delimiter=";")
            writer.writerow(["Composicion quimica final"])
            writer.writerows(info_rows)
            writer.writerow([])
            writer.writerow(["Composicion"])
            writer.writerows(comp_rows)
            writer.writerow([])
            writer.writerow(["Materiales aplicados"])
            writer.writerows(mat_rows)
            resumen = str(adj.get("resumen", "") or "").strip()
            if resumen:
                writer.writerow([])
                writer.writerow(["Resumen", resumen])
            writer.writerow([])
            writer.writerow(["Generado", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])

    def _write_final_composition_pdf(self, fp, session, adj, adj_idx):
        from reportlab.lib import colors
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet
        from reportlab.lib.units import mm
        from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

        styles = getSampleStyleSheet()
        doc = SimpleDocTemplate(
            fp,
            pagesize=A4,
            leftMargin=14 * mm,
            rightMargin=14 * mm,
            topMargin=14 * mm,
            bottomMargin=14 * mm,
        )
        story = []
        story.append(Paragraph("Composicion quimica final", styles["Title"]))
        story.append(Paragraph(f"Sesion: {html.escape(str(session.get('colada', '') or ''))}", styles["Heading2"]))
        story.append(Spacer(1, 6))
        info_rows, comp_rows, mat_rows = self._final_composition_export_data(session, adj, adj_idx)
        story.append(self._pdf_table(info_rows, colors.HexColor("#eef2f7")))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Composicion", styles["Heading2"]))
        story.append(self._pdf_table(comp_rows, colors.HexColor("#e8f5ef"), repeat_rows=1))
        story.append(Spacer(1, 10))

        story.append(Paragraph("Materiales aplicados", styles["Heading2"]))
        story.append(self._pdf_table(mat_rows, colors.HexColor("#fff4df"), repeat_rows=1))

        resumen = str(adj.get("resumen", "") or "").strip()
        if resumen:
            story.append(Spacer(1, 8))
            story.append(Paragraph(f"Resumen: {html.escape(resumen)}", styles["BodyText"]))

        story.append(Spacer(1, 12))
        story.append(Paragraph(f"Generado: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}", styles["BodyText"]))
        doc.build(story)

    def _pdf_table(self, rows, header_color, repeat_rows=0):
        from reportlab.lib import colors
        from reportlab.platypus import Table, TableStyle

        table = Table(rows, hAlign="LEFT", repeatRows=repeat_rows)
        table.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, 0), header_color),
            ("TEXTCOLOR", (0, 0), (-1, 0), colors.HexColor("#1f2937")),
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTSIZE", (0, 0), (-1, -1), 8),
            ("GRID", (0, 0), (-1, -1), 0.25, colors.HexColor("#d1d5db")),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 5),
            ("RIGHTPADDING", (0, 0), (-1, -1), 5),
            ("TOPPADDING", (0, 0), (-1, -1), 4),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 4),
        ]))
        return table

    def export_json(self):
        hist = load_history()
        fp = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON", "*.json")],
            title="Exportar historial a JSON",
        )
        if not fp:
            return
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
