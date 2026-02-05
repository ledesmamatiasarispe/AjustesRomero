# tab_historicos.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import re

from storage import load_history, update_session, delete_session, update_adjustment, delete_adjustment
from widgets import ScrollFrame
from config import ELEMENTS
from utils import fmt, to_float, simulate_with_plan
from ce import ce_from_percent

COLADA_RE = re.compile(r"^\\s*(\\d+)\\s*/\\s*(\\d{2})\\s*-\\s*(.+?)\\s*$")


def split_colada(s):
    m = COLADA_RE.match(s or "")
    if not m:
        return ("", "", s or "")
    return (m.group(1), m.group(2), m.group(3))


class TabHistoricos(ttk.Frame):
    def __init__(self, master, alloys_model):
        super().__init__(master, padding=8)
        self.alloys = alloys_model
        self.hist = []
        self._session_tabs = {}
        self._alloy_cache = None

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

        # ---- Tabla de sesiones (coladas)
        cols = ("id", "inicio", "fin", "cant")
        self.tree = ttk.Treeview(left, columns=cols, show="headings", height=20)
        for cid, title, w in (
            ("id", "ID", 260),
            ("inicio", "Inicio", 170),
            ("fin", "Fin", 170),
            ("cant", "# ajustes", 90),
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

    # ---------------------------- helpers catalogo -------------------------
    def _alloy_by_name(self, name):
        if not name:
            return None
        if self._alloy_cache is None:
            self._alloy_cache = {a.get("nombre", ""): a for a in self.alloys}
        a = self._alloy_cache.get(name)
        if a is None:
            self._alloy_cache = {a.get("nombre", ""): a for a in self.alloys}
            a = self._alloy_cache.get(name)
        return a

    def _objective_comp(self, session):
        name = session.get("objetivo", "")
        a = self._alloy_by_name(name)
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
            M0, comp0, plan, ELEMENTS, self._alloy_by_name, self._effective_add, self._effective_total_perkg
        )

    # ---------------------------- data load --------------------------------
    def refresh(self):
        self.hist = load_history()
        for i in self.tree.get_children():
            self.tree.delete(i)
        for s in self.hist:
            colada_raw = s.get("colada", "")
            idn, yy, mat = split_colada(colada_raw)
            id_show = idn if idn else colada_raw
            self.tree.insert(
                "",
                "end",
                values=(id_show, s.get("started_at", ""), s.get("ended_at", ""), len(s.get("ajustes", []))),
            )
        self._refresh_open_tabs()

    def _refresh_open_tabs(self):
        for idx, data in list(self._session_tabs.items()):
            if idx < 0 or idx >= len(self.hist):
                self._close_session_tab(idx)
                continue
            self._fill_session_tab(idx)

    # ---------------------------- dock tabs --------------------------------
    def _open_session_tab(self):
        sel = self.tree.selection()
        if not sel:
            return
        idx = self.tree.index(sel[0])
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

        summary = ttk.Label(tab, text="", justify="left")
        summary.pack(anchor="w", pady=(0, 6))

        # Split inside session tab
        split = ttk.PanedWindow(tab, orient="vertical")
        split.pack(fill="both", expand=True)

        top = ttk.Frame(split)
        bottom = ttk.Frame(split)
        split.add(top, weight=3)
        split.add(bottom, weight=2)

        # Dock interno para Ajustes / Calculos
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

        # Botones
        btns = ttk.Frame(tab)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Editar ajuste", command=lambda: self._edit_adjustment_in_session(idx)).pack(side="left")
        ttk.Button(btns, text="Eliminar ajuste", command=lambda: self._delete_adjustment_in_session(idx)).pack(side="left", padx=6)
        ttk.Button(btns, text="Resumen de ajustes", command=lambda: self._show_resumen_ajustes(idx)).pack(side="left", padx=6)
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
            "summary": summary,
            "tree_adj": tree_adj,
            "tree_calc": tree_calc,
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
        data["summary"].config(text=self._summary_text(s))
        try:
            self.nb.tab(data["frame"], text=self._session_title(s))
        except Exception:
            pass
        tree_adj = data["tree_adj"]
        tree_calc = data["tree_calc"]
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

        # Si habia detalle seleccionado, re-pintar
        if data["detail_kind"] is not None and data["detail_row"] is not None:
            self._open_detail_in_tab(idx, data["detail_kind"], data["detail_row"])

    def _summary_text(self, session):
        return (
            f"Colada: {session.get('colada', '')}\\n"
            f"Objetivo: {session.get('objetivo', '')}\\n"
            f"Inicio: {session.get('started_at', '')}\\n"
            f"Fin: {session.get('ended_at', '')}\\n"
            f"Ajustes: {len(session.get('ajustes', []))} | Calculos: {len(session.get('calculos', []))}"
        )

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
        return self.tree.index(sel[0])

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
            update_session(idx, s2)
            self.refresh(); win.destroy()
        ttk.Button(btns, text="Guardar", command=save).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=win.destroy).pack(side="right", padx=6)
        e.focus_set(); win.wait_window()

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
