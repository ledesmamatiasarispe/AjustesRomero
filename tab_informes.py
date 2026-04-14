import tkinter as tk
from tkinter import ttk
from datetime import datetime

from storage import load_history
from utils import to_float, fmt
from widgets import ScrollFrame


class TabInformes(ttk.Frame):
    def __init__(self, master, alloys_model):
        super().__init__(master, padding=8)
        self.alloys = alloys_model
        self.hist = []
        self.section_vars = {}
        self.section_frames = {}

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
        self.scroll = ScrollFrame(content_host)
        self.scroll.pack(fill="both", expand=True)
        self.content = self.scroll.inner

        self._build_sections()

        self.bind("<<HistoryUpdated>>", lambda e: self.refresh())
        self.bind("<<CatalogUpdated>>", lambda e: self.refresh())
        self.refresh()

    def _add_sidebar_toggle(self, key, label, default=True):
        var = tk.BooleanVar(value=default)
        self.section_vars[key] = var
        ttk.Checkbutton(
            self.sidebar,
            text=label,
            variable=var,
            command=self._render_sections,
        ).pack(anchor="w", fill="x", pady=2)

    def _build_sections(self):
        self._add_sidebar_toggle("summary", "Resumen general")
        self._add_sidebar_toggle("materials", "Materiales mas usados")
        self._add_sidebar_toggle("targets", "Objetivos mas usados")
        self._add_sidebar_toggle("elements", "Elementos mas ajustados")
        self._add_sidebar_toggle("ce", "CE y formulas")
        self._add_sidebar_toggle("days", "Produccion por fecha")
        self._add_sidebar_toggle("durations", "Duracion de sesiones")

        box = ttk.LabelFrame(self.content, text="Resumen general", padding=8)
        self.lbl_summary = ttk.Label(box, text="", justify="left")
        self.lbl_summary.pack(anchor="w")
        self.section_frames["summary"] = box

        box = ttk.LabelFrame(self.content, text="Materiales mas usados", padding=6)
        self.tree_materials = self._make_tree(
            box,
            columns=(("material", "Material", 240, "w"), ("kg", "kg total", 110, "e")),
            height=10,
        )
        self.section_frames["materials"] = box

        box = ttk.LabelFrame(self.content, text="Objetivos mas usados", padding=6)
        self.tree_targets = self._make_tree(
            box,
            columns=(("objetivo", "Objetivo", 240, "w"), ("cant", "Ajustes", 90, "e")),
            height=8,
        )
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
        self.section_frames["days"] = box

        box = ttk.LabelFrame(self.content, text="Duracion de sesiones", padding=8)
        self.lbl_durations = ttk.Label(box, text="", justify="left")
        self.lbl_durations.pack(anchor="w")
        self.section_frames["durations"] = box

        self._render_sections()

    def _make_tree(self, parent, columns, height=8):
        tree = ttk.Treeview(parent, columns=tuple(col[0] for col in columns), show="headings", height=height)
        for cid, title, width, anchor in columns:
            tree.heading(cid, text=title)
            tree.column(cid, width=width, anchor=anchor)
        tree.pack(fill="both", expand=True)
        return tree

    def _render_sections(self):
        order = ["summary", "materials", "targets", "elements", "ce", "days", "durations"]
        for frame in self.section_frames.values():
            frame.pack_forget()
        for key in order:
            if self.section_vars[key].get():
                self.section_frames[key].pack(fill="both", expand=True, pady=(0, 8))

    def refresh(self):
        self.hist = load_history()
        self._fill_summary()
        self._fill_materials()
        self._fill_targets()
        self._fill_elements()
        self._fill_ce()
        self._fill_days()
        self._fill_durations()

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
            return

        avg = sum(durations) / len(durations)
        text = (
            f"Duracion promedio: {fmt(avg, 1)} min\n"
            f"Duracion minima: {fmt(min(durations), 1)} min\n"
            f"Duracion maxima: {fmt(max(durations), 1)} min\n"
            f"Sesiones con duracion valida: {len(durations)}"
        )
        self.lbl_durations.config(text=text)
