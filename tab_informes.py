import tkinter as tk
from tkinter import ttk
from datetime import datetime
import re

import matplotlib
matplotlib.use("Agg")
from matplotlib.figure import Figure
from matplotlib.backends.backend_tkagg import FigureCanvasTkAgg, NavigationToolbar2Tk

matplotlib.rcParams.update({
    "axes.spines.top": False,
    "axes.spines.right": False,
    "font.size": 8,
    "axes.labelsize": 8,
    "xtick.labelsize": 7,
    "ytick.labelsize": 7,
})

from storage import load_history, load_ladles_state, load_quality_reports, prune_ladles_history_for_sessions
from utils import to_float, fmt
from widgets import ScrollFrame

LADLE_KG_PER_COUNT = 50.0
FURNACE_KG_PER_SESSION = 1000.0


class TabInformes(ttk.Frame):
    def __init__(self, master, alloys_model):
        super().__init__(master, padding=8)
        self.alloys = alloys_model
        self.hist = []
        self.ladles = {}
        self.quality_reports = []
        self.section_frames = {}
        self._section_items = []   # [(key, label), ...] en orden
        self.monthly_furnace_summary_var = tk.StringVar(value="")
        self._monthly_furnace_data = []
        self.monthly_hornos_summary_var = tk.StringVar(value="")
        self._monthly_hornos_data = []
        self._timeline_available_days = []
        self._timeline_day_idx = -1
        self._timeline_corrected = tk.BooleanVar(value=False)

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Estadisticas").pack(side="left")
        ttk.Button(top, text="Refrescar", command=self.refresh).pack(side="right")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        sidebar = ttk.LabelFrame(body, text="Paneles", padding=8)
        content_host = ttk.Frame(body)
        body.add(sidebar, weight=0)
        body.add(content_host, weight=1)

        self.sidebar = sidebar
        self.content = content_host

        self._build_sections()

        self.bind("<<HistoryUpdated>>", lambda e: self.refresh())
        self.bind("<<CatalogUpdated>>", lambda e: self.refresh())
        self.refresh()

    def _add_sidebar_toggle(self, key, label, default=True):
        self._section_items.append((key, label))

    def _build_sections(self):
        self._add_sidebar_toggle("summary", "Resumen general")
        self._add_sidebar_toggle("materials", "Materiales mas usados")
        self._add_sidebar_toggle("monthly_furnace", "Hierro fundido mensual")
        self._add_sidebar_toggle("monthly_hornos", "Hierro mensual por hornos")
        self._add_sidebar_toggle("targets", "Objetivos mas usados")
        self._add_sidebar_toggle("elements", "Elementos mas ajustados")
        self._add_sidebar_toggle("ce", "CE y formulas")
        self._add_sidebar_toggle("days", "Produccion por fecha")
        self._add_sidebar_toggle("durations", "Duracion de sesiones")
        self._add_sidebar_toggle("cucharas", "Cucharas")
        self._add_sidebar_toggle("quality_reports", "Informes de calidad")
        self._add_sidebar_toggle("inoculantes", "Uso de inoculantes")
        self._add_sidebar_toggle("timeline", "Linea de tiempo diaria")

        box = ttk.LabelFrame(self.content, text="Resumen general", padding=8)
        self.lbl_summary = ttk.Label(box, text="", justify="left")
        self.lbl_summary.pack(anchor="w")
        self.fig_summary, self.mpl_summary = self._make_mpl_canvas(box, figsize=(7, 1.6))
        self.section_frames["summary"] = box

        box = ttk.LabelFrame(self.content, text="Materiales mas usados", padding=6)
        self.tree_materials = self._make_tree(
            box,
            columns=(("material", "Material", 240, "w"), ("kg", "kg total", 110, "e")),
            height=10,
        )
        self.fig_materials, self.mpl_materials = self._make_mpl_canvas(box, figsize=(7, 3.0))
        self.section_frames["materials"] = box

        box = ttk.LabelFrame(self.content, text="Hierro fundido mensual por material", padding=8)
        ttk.Label(
            box,
            textvariable=self.monthly_furnace_summary_var,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        self.fig_monthly_furnace, self.mpl_monthly_furnace = self._make_mpl_canvas(box, figsize=(7, 3.2))
        self.section_frames["monthly_furnace"] = box

        box = ttk.LabelFrame(self.content, text="Hierro fundido mensual por hornos", padding=8)
        ttk.Label(
            box,
            textvariable=self.monthly_hornos_summary_var,
            justify="left",
        ).pack(anchor="w", pady=(0, 8))
        self.fig_monthly_hornos, self.mpl_monthly_hornos = self._make_mpl_canvas(box, figsize=(7, 3.2))
        self.section_frames["monthly_hornos"] = box

        box = ttk.LabelFrame(self.content, text="Objetivos mas usados", padding=6)
        self.tree_targets = self._make_tree(
            box,
            columns=(("objetivo", "Objetivo", 240, "w"), ("cant", "Ajustes", 90, "e")),
            height=8,
        )
        self.fig_targets, self.mpl_targets = self._make_mpl_canvas(box, figsize=(7, 2.4))
        self.section_frames["targets"] = box

        box = ttk.LabelFrame(self.content, text="Elementos mas ajustados", padding=6)
        self.tree_elements = self._make_tree(
            box,
            columns=(
                ("elemento", "Elemento", 140, "w"),
                ("veces", "Veces", 80, "e"),
                ("delta", "Delta abs total", 140, "e"),
            ),
            height=10,
        )
        self.fig_elements, self.mpl_elements = self._make_mpl_canvas(box, figsize=(7, 2.4))
        self.section_frames["elements"] = box

        box = ttk.LabelFrame(self.content, text="CE y formulas", padding=6)
        self.tree_ce = self._make_tree(
            box,
            columns=(
                ("formula", "Formula", 180, "w"),
                ("veces", "Usos", 70, "e"),
                ("ce_ini", "CE inicial prom", 120, "e"),
                ("ce_est", "CE final prom", 120, "e"),
            ),
            height=8,
        )
        self.fig_ce, self.mpl_ce = self._make_mpl_canvas(box, figsize=(7, 2.4))
        self.section_frames["ce"] = box

        box = ttk.LabelFrame(self.content, text="Produccion por fecha", padding=6)
        self.tree_days = self._make_tree(
            box,
            columns=(
                ("fecha", "Fecha", 120, "w"),
                ("sesiones", "Sesiones", 80, "e"),
                ("ajustes", "Ajustes", 80, "e"),
                ("kg", "kg agregados", 110, "e"),
            ),
            height=8,
        )
        self.fig_days, self.mpl_days = self._make_mpl_canvas(box, figsize=(7, 2.8))
        self.section_frames["days"] = box

        box = ttk.LabelFrame(self.content, text="Duracion de sesiones", padding=8)
        self.lbl_durations = ttk.Label(box, text="", justify="left")
        self.lbl_durations.pack(anchor="w")
        self.fig_durations, self.mpl_durations = self._make_mpl_canvas(box, figsize=(7, 2.4))
        self.section_frames["durations"] = box

        box = ttk.LabelFrame(self.content, text="Cucharas", padding=8)
        self.lbl_cucharas_summary = ttk.Label(box, text="", justify="left")
        self.lbl_cucharas_summary.pack(anchor="w", pady=(0, 8))

        mats_box = ttk.LabelFrame(box, text="Totales por material", padding=6)
        mats_box.pack(fill="both", expand=True, pady=(0, 8))
        self.tree_cucharas_materials = self._make_tree(
            mats_box,
            columns=(
                ("material", "Material", 140, "w"),
                ("total", "Total cucharas", 110, "e"),
                ("coladas", "Coladas", 80, "e"),
                ("pct", "% del total", 90, "e"),
                ("prom", "Prom/colada", 90, "e"),
            ),
            height=8,
        )
        self.fig_cucharas_pie, self.mpl_cucharas_pie = self._make_mpl_canvas(mats_box, figsize=(5, 2.4))

        coladas_box = ttk.LabelFrame(box, text="Resumen por colada", padding=6)
        coladas_box.pack(fill="both", expand=True, pady=(0, 8))
        self.tree_cucharas_coladas = self._make_tree(
            coladas_box,
            columns=(
                ("colada", "Colada", 150, "w"),
                ("objetivo", "Material", 90, "w"),
                ("total", "Total", 70, "e"),
                ("primera", "Primera", 150, "w"),
                ("ultima", "Ultima", 150, "w"),
                ("duracion", "Duracion", 90, "e"),
                ("prom", "Prom entre cuch.", 120, "e"),
                ("topmat", "Material mas usado", 150, "w"),
            ),
            height=8,
        )

        hours_box = ttk.LabelFrame(box, text="Actividad por hora", padding=6)
        hours_box.pack(fill="both", expand=True)
        self.tree_cucharas_hours = self._make_tree(
            hours_box,
            columns=(
                ("hora", "Hora", 90, "w"),
                ("total", "Cucharas", 90, "e"),
                ("material", "Material dominante", 160, "w"),
            ),
            height=8,
        )
        self.fig_cucharas_hours, self.mpl_cucharas_hours = self._make_mpl_canvas(hours_box, figsize=(7, 2.4))
        self.section_frames["cucharas"] = box

        box = ttk.LabelFrame(self.content, text="Informes de calidad", padding=8)
        self.lbl_quality_summary = ttk.Label(box, text="", justify="left")
        self.lbl_quality_summary.pack(anchor="w", pady=(0, 8))

        props_box = ttk.LabelFrame(box, text="Promedios de propiedades", padding=6)
        props_box.pack(fill="both", expand=True, pady=(0, 8))
        self.tree_quality_props = self._make_tree(
            props_box,
            columns=(
                ("campo", "Campo", 190, "w"),
                ("prom", "Promedio", 100, "e"),
                ("min", "Min", 90, "e"),
                ("max", "Max", 90, "e"),
                ("cant", "Cant.", 70, "e"),
            ),
            height=9,
        )
        self.fig_quality, self.mpl_quality = self._make_mpl_canvas(props_box, figsize=(7, 2.8))

        mats_box = ttk.LabelFrame(box, text="Informes por material", padding=6)
        mats_box.pack(fill="both", expand=True, pady=(0, 8))
        self.tree_quality_materials = self._make_tree(
            mats_box,
            columns=(
                ("material", "Material", 120, "w"),
                ("informes", "Informes", 80, "e"),
                ("bases", "Bases", 120, "w"),
                ("traccion", "Traccion prom", 110, "e"),
                ("dureza", "Dureza prom", 100, "e"),
                ("ce", "CE prom", 90, "e"),
            ),
            height=8,
        )

        bases_box = ttk.LabelFrame(box, text="Informes por base", padding=6)
        bases_box.pack(fill="both", expand=True, pady=(0, 8))
        self.tree_quality_bases = self._make_tree(
            bases_box,
            columns=(
                ("base", "Base", 120, "w"),
                ("informes", "Informes", 80, "e"),
                ("materiales", "Materiales", 220, "w"),
                ("traccion", "Traccion prom", 110, "e"),
                ("dureza", "Dureza prom", 100, "e"),
            ),
            height=8,
        )

        micro_box = ttk.LabelFrame(box, text="Metalografia / matriz", padding=6)
        micro_box.pack(fill="both", expand=True, pady=(0, 8))
        self.tree_quality_micro = self._make_tree(
            micro_box,
            columns=(
                ("tipo", "Tipo", 170, "w"),
                ("valor", "Valor", 220, "w"),
                ("informes", "Informes", 80, "e"),
                ("pct", "%", 70, "e"),
            ),
            height=10,
        )

        days_box = ttk.LabelFrame(box, text="Informes por fecha", padding=6)
        days_box.pack(fill="both", expand=True)
        self.tree_quality_days = self._make_tree(
            days_box,
            columns=(
                ("fecha", "Fecha", 110, "w"),
                ("informes", "Informes", 80, "e"),
                ("lotes", "Lotes", 80, "e"),
                ("materiales", "Materiales", 180, "w"),
            ),
            height=8,
        )
        self.section_frames["quality_reports"] = box

        box = ttk.LabelFrame(self.content, text="Uso de inoculantes", padding=8)

        cfg_box = ttk.LabelFrame(box, text="Configuracion actual", padding=6)
        cfg_box.pack(fill="both", expand=True, pady=(0, 8))
        self.tree_inoc_config = self._make_tree(
            cfg_box,
            columns=(
                ("inoc", "Inoculante", 180, "w"),
                ("unidad", "Unidad", 90, "w"),
                ("gramos", "g/unidad", 90, "e"),
                ("materiales", "Materiales que lo usan", 260, "w"),
                ("etapas", "Etapas", 200, "w"),
            ),
            height=6,
        )

        recent_box = ttk.LabelFrame(box, text="Colada mas reciente", padding=6)
        recent_box.pack(fill="both", expand=True, pady=(0, 8))
        self.lbl_inoc_recent_colada = ttk.Label(recent_box, text="")
        self.lbl_inoc_recent_colada.pack(anchor="w", pady=(0, 4))
        self.tree_inoc_recent = self._make_tree(
            recent_box,
            columns=(
                ("inoc", "Inoculante", 180, "w"),
                ("dosis", "Total dosis", 100, "e"),
                ("gramos_u", "g/unidad", 90, "e"),
                ("total_g", "Total kg estimado", 130, "e"),
            ),
            height=6,
        )

        hist_box = ttk.LabelFrame(box, text="Consumo historico acumulado", padding=6)
        hist_box.pack(fill="both", expand=True)
        self.tree_inoc_hist = self._make_tree(
            hist_box,
            columns=(
                ("inoc", "Inoculante", 180, "w"),
                ("coladas", "Coladas", 80, "e"),
                ("dosis", "Total dosis", 110, "e"),
                ("total_g", "Total kg estimado", 140, "e"),
                ("prom_g", "Prom g/colada", 130, "e"),
            ),
            height=8,
        )
        self.fig_inoc, self.mpl_inoc = self._make_mpl_canvas(hist_box, figsize=(7, 2.4))

        self.section_frames["inoculantes"] = box

        box = ttk.LabelFrame(self.content, text="Linea de tiempo diaria  (5:00 — 18:00)", padding=8)
        nav = ttk.Frame(box)
        nav.pack(fill="x", pady=(0, 6))
        self.btn_timeline_prev = ttk.Button(nav, text="◀", width=3, command=self._timeline_prev_day)
        self.btn_timeline_prev.pack(side="left")
        self.lbl_timeline_day = ttk.Label(nav, text="Sin datos", width=22, anchor="center",
                                          font=("TkDefaultFont", 9, "bold"))
        self.lbl_timeline_day.pack(side="left", padx=6)
        self.btn_timeline_next = ttk.Button(nav, text="▶", width=3, command=self._timeline_next_day)
        self.btn_timeline_next.pack(side="left")
        ttk.Checkbutton(
            nav, text="Horarios corregidos",
            variable=self._timeline_corrected,
            command=self._fill_timeline_diaria,
        ).pack(side="left", padx=(18, 0))

        self.fig_timeline, self.mpl_timeline = self._make_mpl_canvas(box, figsize=(9, 3.2))
        self.section_frames["timeline"] = box

        # Listbox de selección de sección (reemplaza los checkboxes)
        self.section_listbox = tk.Listbox(
            self.sidebar,
            selectmode="single",
            activestyle="dotbox",
            font=("TkDefaultFont", 9),
            relief="flat",
            borderwidth=0,
            highlightthickness=0,
        )
        for _, label in self._section_items:
            self.section_listbox.insert(tk.END, label)
        self.section_listbox.pack(fill="both", expand=True)
        self.section_listbox.bind("<<ListboxSelect>>", self._on_section_select)
        # Mostrar la primera sección por defecto
        self.section_listbox.selection_set(0)
        self._render_sections()

    def _make_tree(self, parent, columns, height=8):
        tree = ttk.Treeview(parent, columns=tuple(col[0] for col in columns), show="headings", height=height)
        for cid, title, width, anchor in columns:
            tree.heading(cid, text=title)
            tree.column(cid, width=width, anchor=anchor)
        tree.pack(fill="both", expand=True)
        return tree

    def _make_mpl_canvas(self, parent, figsize=(7, 2.8)):
        fig = Figure(figsize=figsize, dpi=88, tight_layout=True)
        fig.patch.set_facecolor("#f0f0f0")
        mpl = FigureCanvasTkAgg(fig, master=parent)
        mpl.get_tk_widget().pack(fill="both", expand=True)
        tb = NavigationToolbar2Tk(mpl, parent, pack_toolbar=False)
        tb.pack(fill="x", pady=(2, 0))
        return fig, mpl

    def _mpl_colors(self, n):
        cmap = matplotlib.colormaps.get_cmap("tab20")
        return [cmap(i / max(n, 1)) for i in range(n)]

    def _on_section_select(self, event=None):
        self._render_sections()

    def _render_sections(self):
        sel = self.section_listbox.curselection()
        idx = sel[0] if sel else 0
        key = self._section_items[idx][0] if idx < len(self._section_items) else None
        for frame in self.section_frames.values():
            frame.pack_forget()
        if key and key in self.section_frames:
            self.section_frames[key].pack(fill="both", expand=True)

    def refresh(self):
        self.hist = load_history()
        prune_ladles_history_for_sessions(self.hist)
        self.ladles = load_ladles_state()
        self.quality_reports = load_quality_reports()
        self._fill_summary()
        self._fill_materials()
        self._fill_monthly_furnace()
        self._fill_monthly_hornos()
        self._fill_targets()
        self._fill_elements()
        self._fill_ce()
        self._fill_days()
        self._fill_durations()
        self._fill_cucharas()
        self._fill_quality_reports()
        self._fill_inoculantes()
        self._fill_timeline_diaria()

    def _fill_summary(self):
        total_sessions = len(self.hist)
        total_ajustes = sum(len(s.get("ajustes", [])) for s in self.hist)
        total_calculos = sum(len(s.get("calculos", [])) for s in self.hist)
        total_catalog = len(self.alloys)
        total_adjusters = sum(1 for a in self.alloys if a.get("ajuste"))
        total_kg = 0.0
        total_targets = set()
        for session in self.hist:
            if session.get("objetivo"):
                total_targets.add(session.get("objetivo"))
            for ajuste in session.get("ajustes", []):
                total_kg += sum(to_float(kg) for kg in (ajuste.get("materiales") or {}).values())
        text = (
            f"Materiales en catalogo: {total_catalog}\n"
            f"Materiales de ajuste: {total_adjusters}\n"
            f"Sesiones guardadas: {total_sessions}\n"
            f"Ajustes aplicados: {total_ajustes}\n"
            f"Calculos guardados: {total_calculos}\n"
            f"Objetivos distintos: {len(total_targets)}\n"
            f"kg agregados acumulados: {fmt(total_kg, 3)}"
        )
        self.lbl_summary.config(text=text)
        # Gráfico resumen
        self.fig_summary.clear()
        ax = self.fig_summary.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        labels = ["Sesiones", "Ajustes", "Calculos", "Calc. sin guardar"]
        values = [total_sessions, total_ajustes, total_calculos, total_calculos - total_ajustes]
        values = [max(0, v) for v in values]
        colors = self._mpl_colors(4)
        bars = ax.barh(labels, values, color=colors)
        for bar, val in zip(bars, values):
            if val > 0:
                ax.text(bar.get_width() + max(values) * 0.01, bar.get_y() + bar.get_height() / 2,
                        str(int(val)), va="center", fontsize=7)
        ax.set_xlabel("Cantidad")
        ax.set_title("Totales generales", fontsize=9)
        self.mpl_summary.draw()

    def _clear_tree(self, tree):
        for item in tree.get_children():
            tree.delete(item)

    def _fill_materials(self):
        self._clear_tree(self.tree_materials)
        totals = {}
        for session in self.hist:
            for ajuste in session.get("ajustes", []):
                for name, kg in (ajuste.get("materiales") or {}).items():
                    totals[name] = totals.get(name, 0.0) + to_float(kg)
        for name, kg in sorted(totals.items(), key=lambda x: x[1], reverse=True)[:25]:
            self.tree_materials.insert("", "end", values=(name, fmt(kg, 3)))
        # Gráfico materiales
        self.fig_materials.clear()
        ax = self.fig_materials.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        top = sorted(totals.items(), key=lambda x: x[1], reverse=True)[:15]
        if top:
            mats, kgs = zip(*reversed(top))
            colors = self._mpl_colors(len(mats))
            ax.barh(list(mats), list(kgs), color=colors)
            ax.set_xlabel("kg total")
            ax.set_title("Materiales mas usados", fontsize=9)
        self.mpl_materials.draw()

    def _ladle_record_month(self, record):
        text = str(record.get("updated_at", "") or "").strip()
        if len(text) >= 7 and text[:4].isdigit() and text[4] == "-":
            return text[:7]
        events = record.get("events", []) if isinstance(record.get("events", []), list) else []
        event_dates = [event.get("dt") for event in events if isinstance(event.get("dt"), datetime)]
        if event_dates:
            return max(event_dates).strftime("%Y-%m")
        return "Sin fecha"

    def _session_month(self, session):
        for key in ("ended_at", "started_at", "fecha"):
            text = str(session.get(key, "") or "").strip()
            if len(text) >= 7 and text[:4].isdigit() and text[4] == "-":
                return text[:7]
        return "Sin fecha"

    def _session_target_material(self, session):
        text = str(session.get("material_objetivo", "") or session.get("objetivo", "") or "").strip()
        if not text:
            colada = str(session.get("colada", "") or "")
            match = re.search(r"\bmat\s*([A-Za-z0-9_-]+)", colada, flags=re.IGNORECASE)
            if match:
                text = match.group(1)
        return text or "Sin material"

    def _fill_monthly_furnace(self):
        months = {}
        material_totals = {}
        ladle_coladas = 0
        total_cucharas = 0

        for record in self._ladle_records():
            counts = record.get("counts", {}) if isinstance(record.get("counts", {}), dict) else {}
            month = self._ladle_record_month(record)
            bucket = months.setdefault(month, {})
            record_used = False
            for material, qty in counts.items():
                try:
                    count = max(0, int(qty or 0))
                except Exception:
                    count = 0
                if count <= 0:
                    continue
                material = str(material)
                kg = count * LADLE_KG_PER_COUNT
                bucket[material] = bucket.get(material, 0.0) + kg
                material_totals[material] = material_totals.get(material, 0.0) + kg
                total_cucharas += count
                record_used = True
            if not bucket:
                months.pop(month, None)
            if record_used:
                ladle_coladas += 1

        ordered_months = sorted(months)
        ordered_materials = [
            material for material, _kg in sorted(material_totals.items(), key=lambda item: item[1], reverse=True)
        ]
        self._monthly_furnace_data = [
            {
                "month": month,
                "materials": {material: months[month].get(material, 0.0) for material in ordered_materials},
                "total": sum(months[month].values()),
            }
            for month in ordered_months
        ]
        top_material = ""
        if material_totals:
            mat, kg = max(material_totals.items(), key=lambda item: item[1])
            top_material = f"{mat}: {fmt(kg / LADLE_KG_PER_COUNT, 0)} cucharas"
        self.monthly_furnace_summary_var.set(
            f"Cucharas registradas: {total_cucharas} | Equivalencia usada: {fmt(LADLE_KG_PER_COUNT, 0)} kg aprox/cuchara | "
            f"Meses: {len(ordered_months)} | "
            f"Materiales: {len(ordered_materials)} | Material principal: {top_material or 'N/D'}"
            f" | Coladas con cucharas: {ladle_coladas}"
        )
        # Gráfico barras apiladas mensual
        self.fig_monthly_furnace.clear()
        ax = self.fig_monthly_furnace.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        data = self._monthly_furnace_data
        if data:
            months_labels = [d["month"][5:] + "/" + d["month"][:4] for d in data]
            all_mats = list({m for d in data for m in d["materials"] if d["materials"][m] > 0})
            colors = {m: c for m, c in zip(all_mats, self._mpl_colors(len(all_mats)))}
            bottoms = [0.0] * len(data)
            for mat in all_mats:
                vals = [d["materials"].get(mat, 0.0) for d in data]
                ax.bar(months_labels, vals, bottom=bottoms, label=mat, color=colors[mat])
                bottoms = [b + v for b, v in zip(bottoms, vals)]
            ax.set_ylabel("kg")
            ax.set_title("Hierro fundido mensual", fontsize=9)
            if len(all_mats) <= 10:
                ax.legend(fontsize=6, loc="upper left")
            ax.tick_params(axis="x", rotation=45)
        self.mpl_monthly_furnace.draw()

    def _fill_monthly_hornos(self):
        months = {}
        hornos_by_month = {}
        material_totals = {}
        hornos = 0

        for session in self.hist:
            kg = FURNACE_KG_PER_SESSION
            month = self._session_month(session)
            material = self._session_target_material(session)
            bucket = months.setdefault(month, {})
            bucket[material] = bucket.get(material, 0.0) + kg
            hornos_by_month[month] = hornos_by_month.get(month, 0) + 1
            material_totals[material] = material_totals.get(material, 0.0) + kg
            hornos += 1

        ordered_months = sorted(months)
        ordered_materials = [
            material for material, _kg in sorted(material_totals.items(), key=lambda item: item[1], reverse=True)
        ]
        self._monthly_hornos_data = [
            {
                "month": month,
                "materials": {material: months[month].get(material, 0.0) for material in ordered_materials},
                "total": sum(months[month].values()),
                "hornos": hornos_by_month.get(month, 0),
            }
            for month in ordered_months
        ]
        total_kg = sum(item["total"] for item in self._monthly_hornos_data)
        top_material = ""
        if material_totals:
            mat, kg = max(material_totals.items(), key=lambda item: item[1])
            top_material = f"{mat}: {fmt(kg / FURNACE_KG_PER_SESSION, 0)} hornos"
        self.monthly_hornos_summary_var.set(
            f"Hornos registrados: {hornos} | Equivalencia usada: {fmt(FURNACE_KG_PER_SESSION, 0)} kg/horno | "
            f"Total por hornos: {fmt(total_kg, 0)} kg | "
            f"Meses: {len(ordered_months)} | Materiales: {len(ordered_materials)} | "
            f"Material principal: {top_material or 'N/D'}"
        )
        # Gráfico barras apiladas mensual por hornos
        self.fig_monthly_hornos.clear()
        ax = self.fig_monthly_hornos.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        data = self._monthly_hornos_data
        if data:
            months_labels = [d["month"][5:] + "/" + d["month"][:4] for d in data]
            all_mats = list({m for d in data for m in d["materials"] if d["materials"][m] > 0})
            colors = {m: c for m, c in zip(all_mats, self._mpl_colors(len(all_mats)))}
            bottoms = [0.0] * len(data)
            for mat in all_mats:
                vals = [d["materials"].get(mat, 0.0) for d in data]
                ax.bar(months_labels, vals, bottom=bottoms, label=mat, color=colors[mat])
                bottoms = [b + v for b, v in zip(bottoms, vals)]
            ax.set_ylabel("kg")
            ax.set_title("Hierro mensual por hornos", fontsize=9)
            if len(all_mats) <= 10:
                ax.legend(fontsize=6, loc="upper left")
            ax.tick_params(axis="x", rotation=45)
        self.mpl_monthly_hornos.draw()

    def _fill_targets(self):
        self._clear_tree(self.tree_targets)
        counts = {}
        for session in self.hist:
            for ajuste in session.get("ajustes", []):
                name = ajuste.get("objetivo", "") or session.get("objetivo", "")
                if not name:
                    continue
                counts[name] = counts.get(name, 0) + 1
        for name, qty in sorted(counts.items(), key=lambda x: x[1], reverse=True)[:25]:
            self.tree_targets.insert("", "end", values=(name, qty))
        self.fig_targets.clear()
        ax = self.fig_targets.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        if counts:
            top = sorted(counts.items(), key=lambda x: x[1], reverse=True)[:10]
            labels, vals = zip(*reversed(top))
            ax.barh(list(labels), list(vals), color=self._mpl_colors(len(vals)))
            ax.set_xlabel("Ajustes")
            ax.set_title("Objetivos mas usados", fontsize=9)
        self.mpl_targets.draw()

    def _fill_elements(self):
        self._clear_tree(self.tree_elements)
        stats = {}
        for session in self.hist:
            for ajuste in session.get("ajustes", []):
                for change in ajuste.get("cambios_list", []):
                    if len(change) < 4:
                        continue
                    element = change[0]
                    delta_abs = abs(to_float(change[3]))
                    entry = stats.setdefault(element, {"veces": 0, "delta": 0.0})
                    entry["veces"] += 1
                    entry["delta"] += delta_abs
        ordered = sorted(stats.items(), key=lambda x: (x[1]["delta"], x[1]["veces"]), reverse=True)
        for element, data in ordered[:25]:
            self.tree_elements.insert("", "end", values=(element, data["veces"], fmt(data["delta"], 4)))
        self.fig_elements.clear()
        ax = self.fig_elements.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        if stats:
            top = sorted(stats.items(), key=lambda x: x[1].get("delta", 0), reverse=True)[:12]
            labels = [e for e, _ in reversed(top)]
            deltas = [d.get("delta", 0) for _, d in reversed(top)]
            ax.barh(labels, deltas, color=self._mpl_colors(len(labels)))
            ax.set_xlabel("Delta absoluto total")
            ax.set_title("Elementos mas ajustados", fontsize=9)
        self.mpl_elements.draw()

    def _fill_ce(self):
        self._clear_tree(self.tree_ce)
        stats = {}
        for session in self.hist:
            for ajuste in session.get("ajustes", []):
                formula = ajuste.get("ce_formula", "") or "N/D"
                entry = stats.setdefault(formula, {"veces": 0, "ce_ini": 0.0, "ce_est": 0.0})
                entry["veces"] += 1
                entry["ce_ini"] += to_float(ajuste.get("ce_inicial", 0.0))
                entry["ce_est"] += to_float(ajuste.get("ce_estimado", 0.0))
        ordered = sorted(stats.items(), key=lambda x: x[1]["veces"], reverse=True)
        for formula, data in ordered:
            veces = max(data["veces"], 1)
            self.tree_ce.insert(
                "",
                "end",
                values=(formula, data["veces"], fmt(data["ce_ini"] / veces, 4), fmt(data["ce_est"] / veces, 4)),
            )
        self.fig_ce.clear()
        ax = self.fig_ce.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        if stats:
            ce_data = {f: {"ce_ini": d["ce_ini"] / max(d["veces"], 1), "ce_fin": d["ce_est"] / max(d["veces"], 1)} for f, d in stats.items()}
            formulas = list(ce_data.keys())
            ini = [ce_data[f].get("ce_ini", 0) for f in formulas]
            fin = [ce_data[f].get("ce_fin", 0) for f in formulas]
            x = range(len(formulas))
            w = 0.35
            ax.bar([i - w / 2 for i in x], ini, width=w, label="CE inicial", color="#5B9BD5")
            ax.bar([i + w / 2 for i in x], fin, width=w, label="CE final", color="#ED7D31")
            ax.set_xticks(list(x))
            ax.set_xticklabels(formulas, rotation=20, ha="right")
            ax.set_ylabel("CE promedio")
            ax.set_title("CE por formula", fontsize=9)
            ax.legend(fontsize=7)
        self.mpl_ce.draw()

    def _fill_days(self):
        self._clear_tree(self.tree_days)
        per_day = {}
        for session in self.hist:
            ended = str(session.get("ended_at", "") or "")
            day = ended[:10] if len(ended) >= 10 else "Sin fecha"
            entry = per_day.setdefault(day, {"sesiones": 0, "ajustes": 0, "kg": 0.0})
            entry["sesiones"] += 1
            entry["ajustes"] += len(session.get("ajustes", []))
            for ajuste in session.get("ajustes", []):
                entry["kg"] += sum(to_float(kg) for kg in (ajuste.get("materiales") or {}).values())
        for day, data in sorted(per_day.items(), key=lambda x: x[0], reverse=True)[:25]:
            self.tree_days.insert("", "end", values=(day, data["sesiones"], data["ajustes"], fmt(data["kg"], 3)))
        self.fig_days.clear()
        ax = self.fig_days.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        valid_days = {f: d for f, d in per_day.items() if f != "Sin fecha"}
        if valid_days:
            fechas = sorted(valid_days.keys())[-30:]
            kgs = [valid_days[f].get("kg", 0) for f in fechas]
            sesiones = [valid_days[f].get("sesiones", 0) for f in fechas]
            ax2 = ax.twinx()
            ax.plot(fechas, kgs, color="#5B9BD5", linewidth=1.5, label="kg")
            ax.fill_between(fechas, kgs, alpha=0.15, color="#5B9BD5")
            ax2.bar(fechas, sesiones, alpha=0.35, color="#ED7D31", label="sesiones")
            ax.set_ylabel("kg", color="#5B9BD5")
            ax2.set_ylabel("sesiones", color="#ED7D31")
            ax.set_title("Produccion por fecha (ultimas 30)", fontsize=9)
            ax.tick_params(axis="x", rotation=45, labelsize=6)
        self.mpl_days.draw()

    def _fill_durations(self):
        durations = []
        for session in self.hist:
            start = str(session.get("started_at", "") or "")
            end = str(session.get("ended_at", "") or "")
            try:
                dt0 = datetime.strptime(start[:19], "%Y-%m-%d %H:%M:%S")
                dt1 = datetime.strptime(end[:19], "%Y-%m-%d %H:%M:%S")
                mins = max((dt1 - dt0).total_seconds() / 60.0, 0.0)
                durations.append(mins)
            except Exception:
                pass

        if not durations:
            self.lbl_durations.config(text="No hay suficientes fechas validas para calcular duraciones.")
            self.fig_durations.clear()
            self.mpl_durations.draw()
            return

        avg = sum(durations) / len(durations)
        text = (
            f"Duracion promedio: {fmt(avg, 1)} min\n"
            f"Duracion minima: {fmt(min(durations), 1)} min\n"
            f"Duracion maxima: {fmt(max(durations), 1)} min\n"
            f"Sesiones con duracion valida: {len(durations)}"
        )
        self.lbl_durations.config(text=text)
        self.fig_durations.clear()
        ax = self.fig_durations.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        ax.hist(durations, bins="auto", color="#5B9BD5", edgecolor="white", alpha=0.85)
        ax.axvline(avg, color="#ED7D31", linewidth=1.5, linestyle="--", label=f"Prom: {avg:.0f} min")
        ax.set_xlabel("Minutos")
        ax.set_ylabel("Sesiones")
        ax.set_title("Distribucion duracion de sesiones", fontsize=9)
        ax.legend(fontsize=7)
        self.mpl_durations.draw()

    def _parse_ladle_time(self, value):
        text = str(value or "").strip()
        if not text:
            return None
        try:
            return datetime.fromisoformat(text)
        except Exception:
            pass
        try:
            return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
        except Exception:
            return None

    def _duration_label(self, seconds):
        total = max(0, int(seconds or 0))
        hours, rem = divmod(total, 3600)
        minutes, secs = divmod(rem, 60)
        if hours:
            return f"{hours}h {minutes:02d}m"
        if minutes:
            return f"{minutes}m {secs:02d}s"
        return f"{secs}s"

    def _ladle_records(self):
        history = self.ladles.get("history_by_colada", {}) if isinstance(self.ladles, dict) else {}
        if not isinstance(history, dict):
            return []
        records = []
        for colada, raw in history.items():
            if isinstance(raw, list):
                if not raw:
                    continue
                raw = raw[-1] if isinstance(raw[-1], dict) else {}
                rows = raw.get("rows", []) if isinstance(raw.get("rows", []), list) else []
                counts = {}
                for row in rows:
                    if not isinstance(row, dict):
                        continue
                    material = str(row.get("material_final", "") or "").strip()
                    if not material:
                        continue
                    counts[material] = int(row.get("cantidad", 0) or 0)
                records.append({
                    "colada": str(colada),
                    "material_objetivo": str(raw.get("material_objetivo", "") or ""),
                    "counts": counts,
                    "events": [],
                    "updated_at": str(raw.get("saved_at", "") or ""),
                })
                continue
            if not isinstance(raw, dict):
                continue
            counts = raw.get("counts", {}) if isinstance(raw.get("counts", {}), dict) else {}
            clean_counts = {}
            for material, qty in counts.items():
                try:
                    clean_counts[str(material)] = max(0, int(qty))
                except Exception:
                    clean_counts[str(material)] = 0
            events = []
            raw_events = raw.get("events", {}) if isinstance(raw.get("events", {}), dict) else {}
            for material, items in raw_events.items():
                if not isinstance(items, list):
                    continue
                for item in items:
                    saved_at = str(item.get("saved_at", "") if isinstance(item, dict) else item).strip()
                    if saved_at:
                        events.append({
                            "material": str(material),
                            "saved_at": saved_at,
                            "dt": self._parse_ladle_time(saved_at),
                        })
            events.sort(key=lambda item: item["dt"] or datetime.max)
            records.append({
                "colada": str(colada),
                "material_objetivo": str(raw.get("material_objetivo", "") or ""),
                "counts": clean_counts,
                "events": events,
                "updated_at": str(raw.get("updated_at", "") or ""),
            })
        return records

    def _fill_cucharas(self):
        self._clear_tree(self.tree_cucharas_materials)
        self._clear_tree(self.tree_cucharas_coladas)
        self._clear_tree(self.tree_cucharas_hours)

        records = self._ladle_records()
        total_by_material = {}
        coladas_by_material = {}
        hour_stats = {}
        total_cucharas = 0
        timed_records = []
        interval_values = []
        event_count = 0

        for record in records:
            counts = record.get("counts", {})
            total = sum(max(0, int(qty or 0)) for qty in counts.values())
            if total <= 0:
                continue
            total_cucharas += total
            for material, qty in counts.items():
                qty = max(0, int(qty or 0))
                if qty <= 0:
                    continue
                total_by_material[material] = total_by_material.get(material, 0) + qty
                coladas_by_material.setdefault(material, set()).add(record["colada"])

            parsed_events = [event for event in record.get("events", []) if event.get("dt") is not None]
            event_count += len(parsed_events)
            if parsed_events:
                first = parsed_events[0]["dt"]
                last = parsed_events[-1]["dt"]
                duration = max(0, (last - first).total_seconds())
                avg_interval = duration / max(1, len(parsed_events) - 1) if len(parsed_events) >= 2 else 0
                if len(parsed_events) >= 2:
                    interval_values.append(avg_interval)
                timed_records.append({
                    "colada": record["colada"],
                    "total": total,
                    "duration": duration,
                    "avg_interval": avg_interval,
                })
                for event in parsed_events:
                    hour = event["dt"].strftime("%H:00")
                    bucket = hour_stats.setdefault(hour, {"total": 0, "materials": {}})
                    bucket["total"] += 1
                    mat = event.get("material", "")
                    bucket["materials"][mat] = bucket["materials"].get(mat, 0) + 1

            top_material = ""
            if counts:
                top_material, top_qty = max(counts.items(), key=lambda item: int(item[1] or 0))
                top_material = f"{top_material} ({top_qty})"
            self.tree_cucharas_coladas.insert(
                "",
                "end",
                values=(
                    record["colada"],
                    record.get("material_objetivo", ""),
                    total,
                    parsed_events[0]["saved_at"] if parsed_events else "",
                    parsed_events[-1]["saved_at"] if parsed_events else "",
                    self._duration_label(duration) if parsed_events and len(parsed_events) >= 2 else "",
                    self._duration_label(avg_interval) if parsed_events and len(parsed_events) >= 2 else "",
                    top_material,
                ),
            )

        for material, qty in sorted(total_by_material.items(), key=lambda item: item[1], reverse=True):
            coladas = len(coladas_by_material.get(material, set()))
            pct = (qty / total_cucharas * 100.0) if total_cucharas else 0.0
            prom = (qty / coladas) if coladas else 0.0
            self.tree_cucharas_materials.insert(
                "",
                "end",
                values=(material, qty, coladas, f"{pct:.1f}%", fmt(prom, 2)),
            )

        for hour, data in sorted(hour_stats.items()):
            dominant = ""
            if data["materials"]:
                mat, qty = max(data["materials"].items(), key=lambda item: item[1])
                dominant = f"{mat} ({qty})"
            self.tree_cucharas_hours.insert("", "end", values=(hour, data["total"], dominant))

        coladas_con_cucharas = sum(1 for record in records if sum(int(q or 0) for q in record.get("counts", {}).values()) > 0)
        material_top = ""
        if total_by_material:
            mat, qty = max(total_by_material.items(), key=lambda item: item[1])
            material_top = f"{mat} ({qty})"
        avg_per_colada = total_cucharas / coladas_con_cucharas if coladas_con_cucharas else 0.0
        avg_duration = sum(item["duration"] for item in timed_records) / len(timed_records) if timed_records else 0
        avg_interval = sum(interval_values) / len(interval_values) if interval_values else 0
        fastest = min(timed_records, key=lambda item: item["duration"], default=None)
        slowest = max(timed_records, key=lambda item: item["duration"], default=None)
        fastest_text = f"{fastest['colada']} ({self._duration_label(fastest['duration'])})" if fastest else ""
        slowest_text = f"{slowest['colada']} ({self._duration_label(slowest['duration'])})" if slowest else ""

        self.lbl_cucharas_summary.config(text=(
            f"Coladas con cucharas: {coladas_con_cucharas}\n"
            f"Total cucharas cargadas: {total_cucharas}\n"
            f"Materiales distintos usados: {len(total_by_material)}\n"
            f"Material mas usado: {material_top or 'N/D'}\n"
            f"Promedio cucharas por colada: {fmt(avg_per_colada, 2)}\n"
            f"Eventos con horario exacto: {event_count}\n"
            f"Duracion promedio primera-ultima: {self._duration_label(avg_duration) if timed_records else 'N/D'}\n"
            f"Promedio entre cucharas: {self._duration_label(avg_interval) if interval_values else 'N/D'}\n"
            f"Colada mas rapida: {fastest_text or 'N/D'}\n"
            f"Colada mas lenta: {slowest_text or 'N/D'}"
        ))
        # Torta por material
        self.fig_cucharas_pie.clear()
        ax = self.fig_cucharas_pie.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        if total_by_material:
            sorted_mats = sorted(total_by_material.items(), key=lambda x: x[1], reverse=True)
            top8 = sorted_mats[:8]
            otros = sum(v for _, v in sorted_mats[8:])
            if otros > 0:
                top8.append(("Otros", otros))
            labels, vals = zip(*top8)
            colors = self._mpl_colors(len(labels))
            ax.pie(vals, labels=labels, colors=colors, autopct="%1.0f%%", textprops={"fontsize": 7})
            ax.set_title("Cucharas por material", fontsize=9)
        self.mpl_cucharas_pie.draw()
        # Barras por hora
        self.fig_cucharas_hours.clear()
        ax = self.fig_cucharas_hours.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        if hour_stats:
            hours_sorted = sorted(hour_stats.keys())
            counts_hrs = [hour_stats[h]["total"] for h in hours_sorted]
            ax.bar(hours_sorted, counts_hrs, color="#5B9BD5")
            ax.set_xlabel("Hora")
            ax.set_ylabel("Cucharas")
            ax.set_title("Actividad por hora del dia", fontsize=9)
            ax.tick_params(axis="x", rotation=45, labelsize=6)
        self.mpl_cucharas_hours.draw()

    def _optional_float(self, value):
        text = str(value or "").strip().replace(",", ".")
        if not text:
            return None
        try:
            return float(text)
        except Exception:
            return None

    def _text_field(self, report, field, default=""):
        return str(report.get(field, "") or default).strip()

    def _display_code_label(self, prefix, value):
        text = str(value or "").strip()
        if not text:
            return ""
        if text.lower().startswith(prefix.lower() + " "):
            return text
        if text.isdigit():
            return f"{prefix} {text}"
        return text

    def _material_label(self, report_or_value):
        if isinstance(report_or_value, dict):
            value = self._text_field(report_or_value, "material")
        else:
            value = str(report_or_value or "").strip()
        return self._display_code_label("Material", value) or "Sin material"

    def _base_label(self, report):
        base_display = str(report.get("base_display", "") or "").strip()
        base_value = str(report.get("base", "") or "").strip()
        return (
            self._display_code_label("Base", base_display)
            or self._display_code_label("Base", base_value)
            or "Sin base"
        )

    def _report_family(self, report):
        explicit = self._text_field(report, "family")
        if explicit:
            return explicit
        morphology = self._text_field(report, "morfologia").lower()
        graphite_type = self._text_field(report, "tipo_grafito")
        nodules = self._text_field(report, "conteo_nodulos") or self._text_field(report, "pct_nodularizacion")
        if "nod" in morphology or nodules:
            return "Nodular"
        if "laminar" in morphology or graphite_type:
            return "Gris"
        return "Sin dato"

    def _numeric_values(self, reports, field):
        values = [self._optional_float(report.get(field, "")) for report in reports]
        return [value for value in values if value is not None]

    def _avg_field(self, reports, field):
        values = self._numeric_values(reports, field)
        if not values:
            return ""
        return fmt(sum(values) / len(values), 2)

    def _counter_add(self, counter, key, amount=1):
        if isinstance(key, tuple):
            clean_key = tuple(str(part or "").strip() or "Sin dato" for part in key)
        else:
            clean_key = str(key or "").strip() or "Sin dato"
        counter[clean_key] = counter.get(clean_key, 0) + amount

    def _top_counter_label(self, counter):
        if not counter:
            return "N/D"
        key, count = max(counter.items(), key=lambda item: item[1])
        return f"{key} ({count})"

    def _fill_quality_reports(self):
        self._clear_tree(self.tree_quality_props)
        self._clear_tree(self.tree_quality_materials)
        self._clear_tree(self.tree_quality_bases)
        self._clear_tree(self.tree_quality_micro)
        self._clear_tree(self.tree_quality_days)

        reports = [report for report in self.quality_reports if isinstance(report, dict)]
        total = len(reports)
        active = [report for report in reports if not report.get("archived")]
        archived = [report for report in reports if report.get("archived")]
        drafts = [report for report in reports if report.get("_draft_pending")]

        lots = {self._text_field(report, "lote") for report in reports if self._text_field(report, "lote")}
        bases = {self._base_label(report) for report in reports if self._base_label(report) != "Sin base"}
        materials = {self._text_field(report, "material") for report in reports if self._text_field(report, "material")}
        informes_named = sum(1 for report in reports if str(report.get("informe", "") or "").strip())
        with_observations = sum(1 for report in reports if str(report.get("datos", "") or "").strip())
        with_ce = len(self._numeric_values(reports, "ce_final"))
        with_traccion = len(self._numeric_values(reports, "traccion"))
        with_dureza = len(self._numeric_values(reports, "dureza"))
        avg_reports_per_lot = total / len(lots) if lots else 0.0

        material_counter = {}
        base_counter = {}
        family_counter = {}
        dates = []
        for report in reports:
            material = self._material_label(report)
            if material:
                self._counter_add(material_counter, material)
            base = self._base_label(report)
            if base != "Sin base":
                self._counter_add(base_counter, base)
            self._counter_add(family_counter, self._report_family(report))
            date_label = self._text_field(report, "fecha")[:10]
            if date_label:
                dates.append(date_label)
        date_range = f"{min(dates)} a {max(dates)}" if dates else "N/D"

        self.lbl_quality_summary.config(text=(
            f"Informes totales: {total}\n"
            f"Informes activos: {len(active)}\n"
            f"Informes archivados: {len(archived)}\n"
            f"Borradores pendientes: {len(drafts)}\n"
            f"Rango de fechas: {date_range}\n"
            f"Lotes / coladas con informe: {len(lots)}\n"
            f"Bases distintas: {len(bases)}\n"
            f"Materiales distintos: {len(materials)}\n"
            f"Material mas informado: {self._top_counter_label(material_counter)}\n"
            f"Base mas informada: {self._top_counter_label(base_counter)}\n"
            f"Familia mas frecuente: {self._top_counter_label(family_counter)}\n"
            f"Informes con nombre/codigo: {informes_named}\n"
            f"Informes con observaciones: {with_observations}\n"
            f"Informes con CE / traccion / dureza: {with_ce} / {with_traccion} / {with_dureza}\n"
            f"Promedio informes por lote: {fmt(avg_reports_per_lot, 2)}"
        ))

        prop_defs = (
            ("ce_final", "CE final"),
            ("c_final", "C final"),
            ("si_final", "Si final"),
            ("traccion", "Traccion"),
            ("dureza", "Dureza"),
            ("conteo_nodulos", "Conteo nodulos"),
            ("pct_nodularizacion", "% nodularizacion"),
            ("alargamiento", "Alargamiento"),
            ("perlita", "Perlita %"),
            ("ferrita", "Ferrita %"),
            ("cementita", "Cementita %"),
        )
        for field, label in prop_defs:
            values = self._numeric_values(reports, field)
            if not values:
                continue
            self.tree_quality_props.insert(
                "",
                "end",
                values=(label, fmt(sum(values) / len(values), 2), fmt(min(values), 2), fmt(max(values), 2), len(values)),
            )

        by_material = {}
        by_base = {}
        micro_counts = {}
        day_stats = {}
        for report in reports:
            material = self._material_label(report)
            base = self._base_label(report)
            by_material.setdefault(material, []).append(report)
            by_base.setdefault(base, []).append(report)
            self._counter_add(micro_counts, ("Familia", self._report_family(report)))

            for kind, field in (
                ("Matriz", "matriz"),
                ("Morfologia", "morfologia"),
                ("Tipo grafito", "tipo_grafito"),
                ("Seccion", "seccion"),
            ):
                if field == "morfologia" and self._report_family(report) == "Nodular":
                    continue
                value = str(report.get(field, "") or "").strip()
                if value:
                    self._counter_add(micro_counts, (kind, value))

            fecha = self._text_field(report, "fecha")[:10] or "Sin fecha"
            day = day_stats.setdefault(fecha, {"informes": 0, "lotes": set(), "materials": set()})
            day["informes"] += 1
            lote = self._text_field(report, "lote")
            if lote:
                day["lotes"].add(lote)
            if material and material != "Sin material":
                day["materials"].add(material)

        for material, items in sorted(by_material.items(), key=lambda item: len(item[1]), reverse=True):
            bases_for_material = sorted({self._base_label(report) for report in items if self._base_label(report) != "Sin base"})
            self.tree_quality_materials.insert(
                "",
                "end",
                values=(
                    material,
                    len(items),
                    ", ".join(bases_for_material[:4]),
                    self._avg_field(items, "traccion"),
                    self._avg_field(items, "dureza"),
                    self._avg_field(items, "ce_final"),
                ),
            )

        for base, items in sorted(by_base.items(), key=lambda item: len(item[1]), reverse=True):
            materials_for_base = sorted({self._material_label(report) for report in items if self._material_label(report) != "Sin material"})
            self.tree_quality_bases.insert(
                "",
                "end",
                values=(
                    base,
                    len(items),
                    ", ".join(materials_for_base[:8]),
                    self._avg_field(items, "traccion"),
                    self._avg_field(items, "dureza"),
                ),
            )

        for (kind, value), count in sorted(micro_counts.items(), key=lambda item: (item[0][0], -item[1], item[0][1])):
            pct = (count / total * 100.0) if total else 0.0
            self.tree_quality_micro.insert("", "end", values=(kind, value, count, f"{pct:.1f}%"))

        for fecha, data in sorted(day_stats.items(), key=lambda item: item[0], reverse=True):
            self.tree_quality_days.insert(
                "",
                "end",
                values=(
                    fecha,
                    data["informes"],
                    len(data["lotes"]),
                    ", ".join(sorted(data["materials"])[:8]),
                ),
            )
        self.fig_quality.clear()
        ax = self.fig_quality.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        mat_quality_data = {
            mat: {
                "traccion": sum(self._numeric_values(items, "traccion")) / len(self._numeric_values(items, "traccion")) if self._numeric_values(items, "traccion") else 0,
                "dureza": sum(self._numeric_values(items, "dureza")) / len(self._numeric_values(items, "dureza")) if self._numeric_values(items, "dureza") else 0,
            }
            for mat, items in by_material.items()
        }
        if mat_quality_data:
            mats = list(mat_quality_data.keys())[:8]
            tracciones = [mat_quality_data[m].get("traccion", 0) for m in mats]
            durezas = [mat_quality_data[m].get("dureza", 0) for m in mats]
            x = range(len(mats))
            w = 0.35
            ax.bar([i - w / 2 for i in x], tracciones, width=w, label="Traccion", color="#5B9BD5")
            ax2 = ax.twinx()
            ax2.bar([i + w / 2 for i in x], durezas, width=w, label="Dureza", color="#70AD47")
            ax.set_xticks(list(x))
            ax.set_xticklabels(mats, rotation=20, ha="right")
            ax.set_ylabel("Traccion (MPa)")
            ax2.set_ylabel("Dureza (HB)")
            ax.set_title("Calidad por material", fontsize=9)
        self.mpl_quality.draw()

    def _fill_inoculantes(self):
        # Mapa nombre_inoc -> {unidad, gramos}
        inoc_info = {}
        for a in self.alloys:
            if a.get("inoculante") or a.get("subtipo") == "Inoculante" or a.get("tipo") == "Inoculante":
                nombre = str(a.get("nombre", "") or "").strip()
                if nombre:
                    inoc_info[nombre] = {
                        "unidad": a.get("unidad_inoculacion") or "cucharín",
                        "gramos": to_float(a.get("gramos_cucharin1", 0)),
                    }

        # Mapa nombre_final -> [{nombre, cantidad_dosis, momento}]
        # Incluye protocolos por base cuando existen; la clave puede ser
        # "NombreFinal" (default) o "NombreFinal|Base" (específico por base).
        from storage import resolve_inoc_protocol

        def _normalize_entries(raw_list):
            out = []
            for e in raw_list:
                if isinstance(e, str):
                    out.append({"nombre": e, "cantidad_dosis": 1, "momento": "horno"})
                elif isinstance(e, dict):
                    out.append({
                        "nombre": str(e.get("nombre", "") or ""),
                        "cantidad_dosis": max(1, int(e.get("cantidad_dosis", 1) or 1)),
                        "momento": str(e.get("momento", "horno") or "horno"),
                    })
            return out

        final_inoc_map = {}
        for a in self.alloys:
            if a.get("tipo") != "Aleación final":
                continue
            nombre_final = str(a.get("nombre", "") or "").strip()
            inoc_meta = a.get("inoculacion_meta") or {}
            # Protocolo por defecto
            default_entries = _normalize_entries(resolve_inoc_protocol(inoc_meta))
            if default_entries and nombre_final:
                final_inoc_map[nombre_final] = default_entries
            # Protocolos por base
            por_base = inoc_meta.get("por_base", {}) if isinstance(inoc_meta, dict) else {}
            if isinstance(por_base, dict):
                for base, raw in por_base.items():
                    entries = _normalize_entries(raw if isinstance(raw, list) else [])
                    if entries:
                        final_inoc_map[f"{nombre_final}|{base}"] = entries

        # Sub-caja 1: configuración
        self._clear_tree(self.tree_inoc_config)
        config_data = {}
        for mat, entries in final_inoc_map.items():
            for e in entries:
                inoc = e["nombre"]
                if inoc not in config_data:
                    config_data[inoc] = {"materiales": set(), "etapas": set()}
                config_data[inoc]["materiales"].add(mat)
                config_data[inoc]["etapas"].add(e["momento"])
        for inoc, data in sorted(config_data.items()):
            info = inoc_info.get(inoc, {})
            g = info.get("gramos", 0)
            self.tree_inoc_config.insert("", "end", values=(
                inoc,
                info.get("unidad", "—"),
                fmt(g, 4) if g else "—",
                ", ".join(sorted(data["materiales"])),
                ", ".join(sorted(data["etapas"])),
            ))

        # Sub-caja 2: colada más reciente
        self._clear_tree(self.tree_inoc_recent)
        records = self._ladle_records()
        if records:
            recent = max(records, key=lambda r: r.get("updated_at", "") or "")
            self.lbl_inoc_recent_colada.config(text=f"Colada: {recent['colada']}")
            acc = {}
            for mat, qty in recent.get("counts", {}).items():
                qty = max(0, int(qty or 0))
                for e in final_inoc_map.get(mat, []):
                    inoc = e["nombre"]
                    dosis = qty * e["cantidad_dosis"]
                    g = inoc_info.get(inoc, {}).get("gramos", 0)
                    if inoc not in acc:
                        acc[inoc] = {"dosis": 0, "total_g": 0.0}
                    acc[inoc]["dosis"] += dosis
                    acc[inoc]["total_g"] += dosis * g
            for inoc, data in sorted(acc.items()):
                g = inoc_info.get(inoc, {}).get("gramos", 0)
                self.tree_inoc_recent.insert("", "end", values=(
                    inoc,
                    data["dosis"],
                    fmt(g, 4) if g else "—",
                    fmt(data["total_g"] / 1000, 3),
                ))
        else:
            self.lbl_inoc_recent_colada.config(text="Sin datos de cucharas")

        # Sub-caja 3: histórico acumulado
        self._clear_tree(self.tree_inoc_hist)
        hist_acc = {}
        for record in records:
            for mat, qty in record.get("counts", {}).items():
                qty = max(0, int(qty or 0))
                for e in final_inoc_map.get(mat, []):
                    inoc = e["nombre"]
                    dosis = qty * e["cantidad_dosis"]
                    g = inoc_info.get(inoc, {}).get("gramos", 0)
                    if inoc not in hist_acc:
                        hist_acc[inoc] = {"dosis": 0, "total_g": 0.0, "coladas": set()}
                    hist_acc[inoc]["dosis"] += dosis
                    hist_acc[inoc]["total_g"] += dosis * g
                    hist_acc[inoc]["coladas"].add(record["colada"])
        for inoc, data in sorted(hist_acc.items(), key=lambda x: x[1]["total_g"], reverse=True):
            n_coladas = len(data["coladas"])
            prom_kg = (data["total_g"] / n_coladas / 1000) if n_coladas else 0.0
            self.tree_inoc_hist.insert("", "end", values=(
                inoc,
                n_coladas,
                data["dosis"],
                fmt(data["total_g"] / 1000, 3),
                fmt(prom_kg, 3),
            ))
        self.fig_inoc.clear()
        ax = self.fig_inoc.add_subplot(111)
        ax.set_facecolor("#f0f0f0")
        if hist_acc:
            top = sorted(hist_acc.items(), key=lambda x: x[1]["total_g"], reverse=True)[:12]
            if top:
                labels, data_vals = zip(*reversed(top))
                vals = [d["total_g"] / 1000 for d in data_vals]
                ax.barh(list(labels), vals, color=self._mpl_colors(len(vals)))
                ax.set_xlabel("Total kg estimado")
                ax.set_title("Consumo historico de inoculantes", fontsize=9)
        self.mpl_inoc.draw()

    # ── Línea de tiempo diaria ────────────────────────────────────────────────

    _TL_WIN_START = 5 * 60    # 300 min desde medianoche
    _TL_WIN_END   = 18 * 60   # 1080 min

    def _timeline_colada_key(self, colada):
        """Normaliza la clave de colada para buscar en history_by_colada."""
        raw = str(colada or "").strip()
        m = re.match(r"^\s*(\d+)\s*/\s*(\d{2,4})", raw)
        if m:
            return f"{int(m.group(1)):04d} /{m.group(2).zfill(2)}"
        return raw

    def _timeline_to_min(self, ts):
        """Convierte timestamp a minutos (float con segundos) desde medianoche. Acepta 'T' o espacio."""
        try:
            dt = datetime.strptime(str(ts or "")[:19].replace("T", " "), "%Y-%m-%d %H:%M:%S")
            return dt.hour * 60 + dt.minute + dt.second / 60.0
        except Exception:
            return None

    def _timeline_prev_day(self):
        if self._timeline_day_idx < len(self._timeline_available_days) - 1:
            self._timeline_day_idx += 1
            self._fill_timeline_diaria()

    def _timeline_next_day(self):
        if self._timeline_day_idx > 0:
            self._timeline_day_idx -= 1
            self._fill_timeline_diaria()


    def _fill_timeline_diaria(self):
        # Agrupar sesiones por fecha de started_at
        by_day = {}
        for s in self.hist:
            ts = str(s.get("started_at", "") or "")
            if len(ts) < 10:
                continue
            day = ts[:10]
            by_day.setdefault(day, []).append(s)

        self._timeline_available_days = sorted(by_day.keys(), reverse=True)

        if not self._timeline_available_days:
            self.lbl_timeline_day.config(text="Sin datos")
            self.fig_timeline.clear()
            self.mpl_timeline.draw()
            return

        if self._timeline_day_idx < 0 or self._timeline_day_idx >= len(self._timeline_available_days):
            self._timeline_day_idx = 0

        day = self._timeline_available_days[self._timeline_day_idx]
        total = len(self._timeline_available_days)
        pos   = total - self._timeline_day_idx
        self.lbl_timeline_day.config(text=f"{day}  ({pos}/{total})")
        self.btn_timeline_prev.config(state="normal" if self._timeline_day_idx < total - 1 else "disabled")
        self.btn_timeline_next.config(state="normal" if self._timeline_day_idx > 0 else "disabled")

        sessions = sorted(by_day[day], key=lambda s: str(s.get("started_at", "") or ""))
        self._draw_timeline_chart(sessions, corrected=self._timeline_corrected.get())

    def _draw_timeline_chart(self, sessions, corrected=False):
        WIN_START = self._TL_WIN_START
        WIN_END   = self._TL_WIN_END
        WIN_SPAN  = WIN_END - WIN_START

        ladle_history = {}
        if isinstance(self.ladles, dict):
            ladle_history = self.ladles.get("history_by_colada", {}) or {}

        colors = self._mpl_colors(max(len(sessions), 1))

        self.fig_timeline.clear()
        ax = self.fig_timeline.add_subplot(111)
        ax.set_facecolor("#f8f8f8")
        ax.set_xlim(0, WIN_SPAN)
        ax.set_ylim(-0.8, max(len(sessions) - 0.2, 0.8))

        if not sessions:
            ax.text(WIN_SPAN / 2, 0, "Sin coladas para este día",
                    ha="center", va="center", fontsize=9, color="#888")
            self.mpl_timeline.draw()
            return

        # ── Precalcular start/end corregidos ──────────────────────────────────
        FIRST_START = 5 * 60 + 30   # 5:30 am en minutos desde medianoche
        corrected_starts = {}   # row_idx → minuto inicio corregido
        corrected_ends   = {}   # row_idx → minuto fin corregido

        if corrected:
            prev_end = FIRST_START
            for row_idx, session in enumerate(sessions):
                colada = str(session.get("colada", "") or "")
                key = self._timeline_colada_key(colada)
                ladle_rec = ladle_history.get(key)

                # Fin = último evento de cuchara
                last_cuchara = None
                if isinstance(ladle_rec, dict):
                    events_raw = ladle_rec.get("events", {}) if isinstance(ladle_rec.get("events"), dict) else {}
                    for mat_events in events_raw.values():
                        if not isinstance(mat_events, list):
                            continue
                        for ev in mat_events:
                            saved = str(ev.get("saved_at", "") if isinstance(ev, dict) else ev).strip()
                            t = self._timeline_to_min(saved) if saved else None
                            if t is not None:
                                if last_cuchara is None or t > last_cuchara:
                                    last_cuchara = t

                # Fallback: último ajuste, o inicio + 90 min
                if last_cuchara is None:
                    ajuste_times = [
                        self._timeline_to_min(aj.get("fecha"))
                        for aj in session.get("ajustes", [])
                    ]
                    valid = [t for t in ajuste_times if t is not None]
                    last_cuchara = max(valid) if valid else prev_end + 90

                corrected_starts[row_idx] = prev_end
                corrected_ends[row_idx]   = max(last_cuchara, prev_end + 1)
                prev_end = corrected_ends[row_idx]

        legend_done = {"sesion": False, "ajuste": False, "cuchara": False, "inicio": False}

        for row_idx, session in enumerate(sessions):
            y        = row_idx
            color    = colors[row_idx % len(colors)]
            colada   = str(session.get("colada", "") or "")
            objetivo = str(session.get("objetivo", "") or "")

            # Tiempos de sesión (raw o corregidos)
            if corrected:
                start_m = corrected_starts[row_idx]
                end_m   = corrected_ends[row_idx]
            else:
                start_m = self._timeline_to_min(session.get("started_at"))
                end_m   = self._timeline_to_min(session.get("ended_at"))
                if end_m is None:
                    ajuste_times = [
                        self._timeline_to_min(aj.get("fecha"))
                        for aj in session.get("ajustes", [])
                    ]
                    valid = [t for t in ajuste_times if t is not None]
                    end_m = max(valid) + 5 if valid else ((start_m or WIN_START) + 60)
                if start_m is None:
                    start_m = WIN_START

            # Clipear a ventana
            s = max(start_m, WIN_START) - WIN_START
            e = min(end_m,   WIN_END)   - WIN_START
            dur = max(e - s, 3)

            # Barra de sesión
            lbl = "Sesión" if not legend_done["sesion"] else "_"
            legend_done["sesion"] = True
            ax.broken_barh(
                [(s, dur)], (y - 0.35, 0.7),
                facecolors=color, edgecolors="white", linewidth=0.5,
                alpha=0.85, label=lbl,
            )

            # Línea verde de inicio de sesión (ambos modos)
            lbl_ini = "Inicio sesión" if not legend_done["inicio"] else "_"
            legend_done["inicio"] = True
            ax.vlines(s, y - 0.42, y + 0.42, colors="#2ecc71",
                      linewidth=2.0, label=lbl_ini, zorder=5)
            # Objetivo de la sesión sobre la línea de inicio
            obj_sesion = str(session.get("objetivo", "") or "").strip()
            if obj_sesion:
                ax.text(s, y + 0.44, obj_sesion,
                        ha="center", va="bottom", fontsize=6,
                        color="#27ae60", rotation=90,
                        clip_on=True, zorder=6)

            # Label de colada a la izquierda
            label_txt = colada if colada else objetivo
            ax.text(-4, y, label_txt, ha="right", va="center", fontsize=7,
                    color="#333", clip_on=False)

            # Objetivo debajo del nombre
            if objetivo and objetivo != label_txt:
                ax.text(-4, y - 0.28, objetivo, ha="right", va="center",
                        fontsize=6, color="#888", clip_on=False)

            # Marcadores de ajustes
            for aj_idx, aj in enumerate(session.get("ajustes", []), start=1):
                t = self._timeline_to_min(aj.get("fecha"))
                if t is None or t < WIN_START or t > WIN_END:
                    continue
                x = t - WIN_START
                lbl_aj = "Ajuste" if not legend_done["ajuste"] else "_"
                legend_done["ajuste"] = True
                ax.vlines(x, y - 0.35, y + 0.35, colors="#e05252",
                          linewidth=1.6, label=lbl_aj, zorder=3)
                # Material objetivo en ambos modos
                obj_txt = str(aj.get("objetivo", "") or "").strip()
                if obj_txt:
                    ax.text(x, y + 0.38, obj_txt,
                            ha="center", va="bottom", fontsize=6,
                            color="#c0392b", rotation=90,
                            clip_on=True, zorder=4)

            # Cucharas PDH: líneas verticales amarillas individuales
            key = self._timeline_colada_key(colada)
            ladle_rec = ladle_history.get(key)
            total_cucharas = 0
            if isinstance(ladle_rec, dict):
                events_raw = ladle_rec.get("events", {}) if isinstance(ladle_rec.get("events"), dict) else {}
                for mat_events in events_raw.values():
                    if not isinstance(mat_events, list):
                        continue
                    for ev in mat_events:
                        saved = str(ev.get("saved_at", "") if isinstance(ev, dict) else ev).strip()
                        t = self._timeline_to_min(saved) if saved else None
                        if t is None or t < WIN_START or t > WIN_END:
                            continue
                        x = t - WIN_START
                        lbl_cu = "Cuchara (PDH)" if not legend_done["cuchara"] else "_"
                        legend_done["cuchara"] = True
                        ax.vlines(x, y - 0.35, y + 0.35, colors="#f1c40f",
                                  linewidth=1.2, label=lbl_cu, zorder=3)
                        total_cucharas += 1
                if not events_raw:
                    counts = ladle_rec.get("counts", {}) if isinstance(ladle_rec.get("counts"), dict) else {}
                    total_cucharas = sum(max(0, int(v or 0)) for v in counts.values())

            # Total cucharas al final de la barra
            if total_cucharas > 0:
                x_end = min(e + 2, WIN_SPAN - 2)
                ax.text(x_end, y, f"  {total_cucharas}🥄",
                        va="center", fontsize=7, color="#d4ac0d", zorder=5)

        # Eje X: ticks cada 60 min (label) y 15 min (minor)
        major_ticks  = list(range(0, WIN_SPAN + 1, 60))
        minor_ticks  = [t for t in range(0, WIN_SPAN + 1, 15) if t % 60 != 0]
        major_labels = [f"{(t + WIN_START) // 60:02d}:00" for t in major_ticks]
        ax.set_xticks(major_ticks)
        ax.set_xticklabels(major_labels, fontsize=7)
        ax.set_xticks(minor_ticks, minor=True)
        ax.tick_params(axis="x", which="minor", length=3, color="#aaa")
        ax.set_xlabel("Hora del día  (usar toolbar para zoom/pan)", fontsize=8)

        # Eje Y: ocultar ticks
        ax.set_yticks([])
        ax.tick_params(left=False)

        # Grilla
        for t in major_ticks:
            ax.axvline(t, color="#ccc", linewidth=0.6, zorder=0)
        for t in minor_ticks:
            ax.axvline(t, color="#e8e8e8", linewidth=0.4, linestyle=":", zorder=0)

        # Leyenda
        handles = [h for h in ax.get_legend_handles_labels()[0]]
        labels_lg = [l for l in ax.get_legend_handles_labels()[1] if not l.startswith("_")]
        if handles:
            ax.legend(handles[:3], labels_lg[:3], loc="upper right",
                      fontsize=7, framealpha=0.8)

        ax.set_title(
            f"{len(sessions)} colada(s) — Ajustes y cucharas PDH",
            fontsize=9,
        )
        self.mpl_timeline.draw()
