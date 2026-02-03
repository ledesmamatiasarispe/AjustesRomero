# tab_historicos.py
import tkinter as tk
from tkinter import ttk, filedialog, messagebox
import json
import re

from storage import load_history, save_history, update_session, delete_session, update_adjustment, delete_adjustment
from widgets import ScrollFrame
from config import ELEMENTS
from utils import fmt, to_float
from ce import ce_from_percent

COLADA_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})\s*-\s*(.+?)\s*$")

def split_colada(s):
    m = COLADA_RE.match(s or "")
    if not m:
        return ("", "", s or "")
    return (m.group(1), m.group(2), m.group(3))


class TabHistoricos(ttk.Frame):
    def __init__(self, master, alloys_model):
        super().__init__(master, padding=8)
        self.alloys = alloys_model

        # ---- Cabecera
        top = ttk.Frame(self); top.pack(fill="x")
        ttk.Label(top, text="Historial de coladas guardadas").pack(side="left")
        ttk.Button(top, text="Refrescar", command=self.refresh).pack(side="right")
        ttk.Button(top, text="Exportar JSON", command=self.export_json).pack(side="right", padx=6)

        # ---- Acciones sobre sesión
        act = ttk.Frame(self); act.pack(fill="x", pady=(6, 0))
        ttk.Button(act, text="Editar colada", command=self.edit_session_meta).pack(side="left")
        ttk.Button(act, text="Eliminar sesión", command=self.delete_session).pack(side="left", padx=6)

        # ---- Tabla de sesiones (coladas)
        cols = ("id", "year", "material", "inicio", "fin", "cant")
        self.tree = ttk.Treeview(self, columns=cols, show="headings", height=12)
        for cid, title, w in (
            ("id", "ID", 90),
            ("year", "Año", 60),
            ("material", "Material objetivo", 220),
            ("inicio", "Inicio", 170),
            ("fin", "Fin", 170),
            ("cant", "# ajustes", 90),
        ):
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=w, anchor="w")
        self.tree.pack(fill="both", expand=True, pady=(6, 6))

        # ---- Lista de ajustes de la sesión seleccionada
        adj_act = ttk.Frame(self); adj_act.pack(fill="x", pady=(0, 2))
        ttk.Button(adj_act, text="Editar ajuste", command=self.edit_adjustment).pack(side="left")
        ttk.Button(adj_act, text="Eliminar ajuste", command=self.delete_adjustment).pack(side="left", padx=6)

        ttk.Label(self, text="Ajustes de la sesión").pack(anchor="w")
        adj_cols = ("fecha", "resumen")
        self.tree_adj = ttk.Treeview(self, columns=adj_cols, show="headings", height=6)
        for cid, title, w in (("fecha", "Fecha/Hora", 160), ("resumen", "Materiales", 560)):
            self.tree_adj.heading(cid, text=title)
            self.tree_adj.column(cid, width=w, anchor="w")
        self.tree_adj.pack(fill="both", expand=True, pady=(0, 6))

        # ---- Composición completa (Inicial, Estimado, Objetivo)
        box = ttk.LabelFrame(self, text="Composición del ajuste seleccionado (%)", padding=6)
        box.pack(fill="both", expand=True)
        self.sf = ScrollFrame(box); self.sf.pack(fill="both", expand=True)
        head = ttk.Frame(self.sf.inner)
        head.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Label(head, text="Elemento", font=("Segoe UI", 10, "bold")).grid(row=0, column=0, padx=6)
        ttk.Label(head, text="Inicial",   font=("Segoe UI", 10, "bold")).grid(row=0, column=1, padx=6)
        ttk.Label(head, text="Estimado",  font=("Segoe UI", 10, "bold")).grid(row=0, column=2, padx=6)
        ttk.Label(head, text="Objetivo",  font=("Segoe UI", 10, "bold")).grid(row=0, column=3, padx=6)

        self.comp_rows = []
        for i, el in enumerate(ELEMENTS, start=1):
            r = ttk.Frame(self.sf.inner); r.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            ttk.Label(r, text=el, width=6).grid(row=0, column=0, padx=4)
            e_ini = ttk.Entry(r, width=12, state="readonly")
            e_est = ttk.Entry(r, width=12, state="readonly")
            e_obj = ttk.Entry(r, width=12, state="readonly")
            e_ini.grid(row=0, column=1, padx=4); e_est.grid(row=0, column=2, padx=4); e_obj.grid(row=0, column=3, padx=4)
            self.comp_rows.append((el, e_ini, e_est, e_obj))

        self.tree.bind("<<TreeviewSelect>>", lambda e: self._show_session_details())
        self.tree_adj.bind("<<TreeviewSelect>>", lambda e: self._show_adjustment_composition())

        # Permitir que TabAjuste dispare refresco
        self.bind("<<HistoryUpdated>>", lambda e: self.refresh())

        self.refresh()

    # ---------------------------- helpers catálogo -------------------------
    def _alloy_by_name(self, name):
        for a in self.alloys:
            if a.get("nombre", "") == name: return a
        return None

    def _effective_total_perkg(self, alloy):
        return to_float(alloy.get("rendimiento", 100.0)) / 100.0

    def _effective_add(self, alloy, kg):
        rend = self._effective_total_perkg(alloy)
        out = {e: 0.0 for e in ELEMENTS}
        for e in ELEMENTS:
            out[e] = kg * (to_float(alloy["composicion"].get(e, 0.0)) / 100.0) * rend
        return out

    def _simulate_with_plan(self, M0, comp0, plan):
        masses = {e: M0 * to_float(comp0.get(e, 0.0)) / 100.0 for e in ELEMENTS}
        add_total_eff = 0.0
        for name, kg in (plan or {}).items():
            if kg <= 0: continue
            a = self._alloy_by_name(name)
            if not a: raise ValueError(f"Material '{name}' no existe en catálogo.")
            eff = self._effective_add(a, kg)
            for e in ELEMENTS: masses[e] += eff[e]
            add_total_eff += kg * self._effective_total_perkg(a)
        Mnew = M0 + add_total_eff
        comp_pct = {e: (100.0 * masses[e] / Mnew if Mnew > 0 else 0.0) for e in ELEMENTS}
        return (Mnew, comp_pct)

    # ---------------------------- data load --------------------------------
    def refresh(self):
        self.hist = load_history()
        for i in self.tree.get_children(): self.tree.delete(i)
        for s in self.hist:
            idn, yy, mat = split_colada(s.get("colada", ""))
            self.tree.insert("", "end", values=(idn, yy, mat, s.get("started_at",""), s.get("ended_at",""), len(s.get("ajustes",[]))))
        self._show_session_details()

    def _show_session_details(self):
        for i in self.tree_adj.get_children(): self.tree_adj.delete(i)
        sel = self.tree.selection()
        if not sel: 
            self._clear_comp_panel()
            return
        idx = self.tree.index(sel[0])
        if idx < 0 or idx >= len(getattr(self, "hist", [])): 
            self._clear_comp_panel()
            return
        s = self.hist[idx]
        for it in s.get("ajustes", []):
            self.tree_adj.insert("", "end", values=(it.get("fecha",""), it.get("resumen","")))
        self._show_adjustment_composition()

    def _clear_comp_panel(self):
        for el, e_ini, e_est, e_obj in self.comp_rows:
            for w in (e_ini, e_est, e_obj):
                w.config(state="normal"); w.delete(0, tk.END); w.config(state="readonly")

    def _show_adjustment_composition(self):
        sel_s = self.tree.selection()
        if not sel_s: return
        idx_s = self.tree.index(sel_s[0])
        if idx_s < 0 or idx_s >= len(self.hist): return
        session = self.hist[idx_s]

        sel_a = self.tree_adj.selection()
        if not sel_a:
            self._clear_comp_panel(); return
        idx_a = self.tree_adj.index(sel_a[0])
        ajustes = session.get("ajustes", [])
        if idx_a < 0 or idx_a >= len(ajustes): return
        it = ajustes[idx_a]

        comp_ini = (it.get("inicial") or {}).get("comp", {}) or {}
        comp_est = (it.get("estimado") or {}).get("comp", {}) or {}
        comp_obj = it.get("objetivo_comp", {}) or {}

        for el, e_ini, e_est, e_obj in self.comp_rows:
            v1 = comp_ini.get(el, 0.0); v2 = comp_est.get(el, 0.0); v3 = comp_obj.get(el, 0.0)
            for w, val in ((e_ini, v1), (e_est, v2), (e_obj, v3)):
                w.config(state="normal"); w.delete(0, tk.END); w.insert(0, fmt(val)); w.config(state="readonly")

    # ---------------------------- acciones sesión ---------------------------
    def _selected_session_index(self):
        sel = self.tree.selection()
        if not sel: return None
        return self.tree.index(sel[0])

    def edit_session_meta(self):
        idx = self._selected_session_index()
        if idx is None: 
            messagebox.showinfo("Editar", "Seleccioná una sesión.")
            return
        s = self.hist[idx]
        win = tk.Toplevel(self); win.title("Editar colada"); win.transient(self); win.grab_set(); win.resizable(False, False)
        ttk.Label(win, text="Colada (formato: ID /YY - MATERIAL)").pack(anchor="w", padx=10, pady=(10, 4))
        v = tk.StringVar(value=s.get("colada",""))
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
            messagebox.showinfo("Eliminar", "Seleccioná una sesión.")
            return
        if not messagebox.askyesno("Eliminar", "¿Eliminar la sesión seleccionada?"): 
            return
        delete_session(idx)
        self.refresh()

    # ---------------------------- acciones ajuste ---------------------------
    def _selected_adjust_indices(self):
        si = self._selected_session_index()
        if si is None: return (None, None)
        sel = self.tree_adj.selection()
        if not sel: return (si, None)
        return (si, self.tree_adj.index(sel[0]))

    def edit_adjustment(self):
        si, ai = self._selected_adjust_indices()
        if si is None or ai is None:
            messagebox.showinfo("Editar", "Seleccioná un ajuste.")
            return
        session = self.hist[si]; adj = session.get("ajustes", [])[ai]
        self._edit_adjust_dialog(session_index=si, adj_index=ai, adj_entry=adj)

    def _edit_adjust_dialog(self, session_index, adj_index, adj_entry):
        win = tk.Toplevel(self); win.title("Editar ajuste"); win.transient(self); win.grab_set(); win.resizable(False, False)
        win.geometry("540x560")

        ttk.Label(win, text=f"Fecha: {adj_entry.get('fecha','')}").pack(anchor="w", padx=10, pady=(10, 4))
        ttk.Label(win, text=f"Objetivo: {adj_entry.get('objetivo','')}").pack(anchor="w", padx=10, pady=(0, 6))

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

        res = ttk.Label(win, text="Estimado: pendiente…")
        res.pack(anchor="w", padx=10, pady=(4, 0))

        btns = ttk.Frame(win); btns.pack(fill="x", padx=8, pady=8)

        def recalc():
            try:
                plan = {n: to_float(v.get()) for n, v in var_map.items() if to_float(v.get()) > 0}
                M0  = adj_entry.get("inicial",{}).get("masa", 0.0)
                comp0 = adj_entry.get("inicial",{}).get("comp", {})
                Mnew, comp_est = self._simulate_with_plan(M0, comp0, plan)
                ce_formula = adj_entry.get('ce_formula','FUNDICION')
                ce_custom = adj_entry.get("ce_custom", {}) or {}
                ce_est = ce_from_percent(comp_est, ce_formula, ce_custom)
                res.config(text=f"Estimado: masa {fmt(Mnew)} kg | CE {fmt(ce_est,4)}")
                return (Mnew, comp_est, plan, ce_est, ce_custom)
            except Exception as ex:
                messagebox.showerror("Editar", str(ex), parent=win)
                return None

        def save():
            out = recalc()
            if not out: return
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

    def delete_adjustment(self):
        si, ai = self._selected_adjust_indices()
        if si is None or ai is None:
            messagebox.showinfo("Eliminar", "Seleccioná un ajuste.")
            return
        if not messagebox.askyesno("Eliminar", "¿Eliminar el ajuste seleccionado?"):
            return
        delete_adjustment(si, ai)
        self.refresh()

    # ---------------------------- export -----------------------------------
    def export_json(self):
        hist = load_history()
        fp = filedialog.asksaveasfilename(defaultextension=".json", filetypes=[("JSON","*.json")], title="Exportar historial a JSON")
        if not fp: return
        with open(fp, "w", encoding="utf-8") as f:
            json.dump(hist, f, ensure_ascii=False, indent=2)
