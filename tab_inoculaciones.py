import tkinter as tk
from tkinter import ttk, messagebox

from storage import save_alloys, load_history
from config import BG_ENTRY, FG, ACCENT, ELEMENTS
from utils import simulate_with_plan, to_float, fmt
from ce import ce_from_percent


SPECIAL_TYPE = "Aleación final"


class TabInoculaciones(ttk.Frame):
    def __init__(self, master, alloys_model):
        super().__init__(master, padding=8)
        self.alloys = alloys_model

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Aleaciones finales — Inoculación").pack(side="left")
        ttk.Button(top, text="Editar inoculación", command=self.edit_special).pack(side="left", padx=(12, 2))
        ttk.Button(top, text="Refrescar",          command=self.refresh_catalog).pack(side="right")
        self._btn_real = ttk.Button(top, text="Ver comp. real",     command=self._ver_comp_real,     state="disabled")
        self._btn_real.pack(side="right", padx=(0, 6))
        self._btn_est  = ttk.Button(top, text="Ver comp. estimada", command=self._ver_comp_estimada, state="disabled")
        self._btn_est.pack(side="right", padx=(0, 6))

        split = ttk.PanedWindow(self, orient="horizontal")
        split.pack(fill="both", expand=True)

        left  = ttk.LabelFrame(split, text="Especiales", padding=6)
        right = ttk.LabelFrame(split, text="Detalle",    padding=6)
        split.add(left,  weight=2)
        split.add(right, weight=3)

        self.tree = ttk.Treeview(left, columns=("nombre",), show="headings", height=16)
        self.tree.heading("nombre", text="Nombre")
        self.tree.column("nombre", width=300, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected_detail())
        self.tree.bind("<Double-Button-1>", lambda _e: self.edit_special())

        # Panel de detalle estructurado
        self._detail_nombre = ttk.Label(right, text="", font=("Segoe UI", 11, "bold"))
        self._detail_nombre.pack(anchor="w", pady=(0, 6))

        ttk.Label(right, text="Bases permitidas", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        self._detail_bases = ttk.Label(right, text="—", foreground="#888888", wraplength=260)
        self._detail_bases.pack(anchor="w", pady=(2, 10))

        ttk.Label(right, text="Inoculación", font=("Segoe UI", 9, "bold")).pack(anchor="w")
        inoc_frame = ttk.Frame(right)
        inoc_frame.pack(fill="both", expand=True, pady=(2, 0))

        self._detail_tv = ttk.Treeview(
            inoc_frame,
            columns=("material", "cantidad", "gramos", "total"),
            show="headings",
            height=10,
            selectmode="none",
        )
        self._detail_tv.heading("material", text="Material")
        self._detail_tv.heading("cantidad", text="Cant.")
        self._detail_tv.heading("gramos",   text="g/cucharin1")
        self._detail_tv.heading("total",    text="Total g")
        self._detail_tv.column("material", width=130, anchor="w")
        self._detail_tv.column("cantidad", width=55,  anchor="center")
        self._detail_tv.column("gramos",   width=75,  anchor="center")
        self._detail_tv.column("total",    width=65,  anchor="center")
        detail_sb = ttk.Scrollbar(inoc_frame, orient="vertical", command=self._detail_tv.yview)
        self._detail_tv.configure(yscrollcommand=detail_sb.set)
        detail_sb.pack(side="right", fill="y")
        self._detail_tv.pack(fill="both", expand=True)

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, foreground="#555555").pack(anchor="w", pady=(8, 0))
        self.refresh_catalog()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _is_special(self, alloy):
        return str(alloy.get("tipo", "")).strip() == SPECIAL_TYPE

    def _special_entries(self):
        return [(idx, alloy) for idx, alloy in enumerate(self.alloys) if self._is_special(alloy)]

    def _converter_names(self):
        names = [
            str(a.get("nombre", "")).strip()
            for a in self.alloys
            if str(a.get("nombre", "")).strip()
        ]
        return sorted(set(names), key=lambda v: (0, int(v)) if v.isdigit() else (1, v.lower()))

    def _gramos_cucharin1(self, nombre):
        for a in self.alloys:
            if str(a.get("nombre", "")).strip() == nombre:
                return a.get("gramos_cucharin1", 0) or 0
        return 0

    def _meta_inoculacion(self, meta):
        """Devuelve lista de nombres (compatibilidad con código existente)."""
        return [e["nombre"] for e in self._meta_inoculacion_full(meta)]

    def _meta_inoculacion_full(self, meta):
        """Devuelve lista de dicts {nombre, cantidad_dosis}. Normaliza formatos viejos."""
        raw = meta.get("inoculacion", [])
        if not isinstance(raw, list):
            raw = []
        if not raw:
            raw = meta.get("convertidores", [])
            if not isinstance(raw, list):
                raw = []
        result = []
        for v in raw:
            if isinstance(v, str) and v.strip():
                result.append({"nombre": v.strip(), "cantidad_dosis": 1})
            elif isinstance(v, dict) and str(v.get("nombre", "")).strip():
                result.append({
                    "nombre":         str(v["nombre"]).strip(),
                    "cantidad_dosis": int(v.get("cantidad_dosis", 1) or 1),
                })
        return result

    # ── Selección ─────────────────────────────────────────────────────────────

    def _selected_index(self):
        sel = self.tree.selection()
        if not sel:
            return None
        try:
            return int(sel[0])
        except Exception:
            return None

    def _selected_name(self):
        idx = self._selected_index()
        if idx is None or idx < 0 or idx >= len(self.alloys):
            return ""
        return str(self.alloys[idx].get("nombre", "")).strip()

    # ── Detalle ───────────────────────────────────────────────────────────────

    def _show_selected_detail(self):
        idx = self._selected_index()
        # Limpiar panel
        self._detail_nombre.config(text="")
        self._detail_bases.config(text="—")
        for row in self._detail_tv.get_children():
            self._detail_tv.delete(row)

        if idx is None or idx < 0 or idx >= len(self.alloys):
            self._detail_nombre.config(text="Seleccioná una aleación especial.")
            self._btn_est.config(state="disabled")
            self._btn_real.config(state="disabled")
            return

        self._btn_est.config(state="normal")
        self._btn_real.config(state="normal")

        alloy        = self.alloys[idx]
        meta         = alloy.get("inoculacion_meta", {}) if isinstance(alloy.get("inoculacion_meta", {}), dict) else {}
        calidad_meta = alloy.get("calidad_meta", {}) if isinstance(alloy.get("calidad_meta", {}), dict) else {}
        bases        = calidad_meta.get("bases", []) if isinstance(calidad_meta.get("bases", []), list) else []
        inoculacion  = self._meta_inoculacion_full(meta)

        self._detail_nombre.config(text=alloy.get("nombre", ""))
        self._detail_bases.config(text="  /  ".join(bases) if bases else "—")

        for e in inoculacion:
            g     = self._gramos_cucharin1(e["nombre"])
            cant  = e["cantidad_dosis"]
            total = round(g * cant, 2) if g and cant else "—"
            self._detail_tv.insert("", "end", values=(
                e["nombre"],
                cant,
                f"{g} g" if g else "—",
                f"{total} g" if total != "—" else "—",
            ))

    # ── Refresh ───────────────────────────────────────────────────────────────

    def refresh_catalog(self):
        selected_name = self._selected_name()
        for item in self.tree.get_children():
            self.tree.delete(item)
        selected_iid = None
        for idx, alloy in self._special_entries():
            iid  = str(idx)
            name = alloy.get("nombre", "")
            self.tree.insert("", "end", iid=iid, values=(name,))
            if selected_name and selected_name == name:
                selected_iid = iid
        if selected_iid:
            self.tree.selection_set(selected_iid)
        self._show_selected_detail()
        self.status_var.set(f"Aleaciones finales con inoculación: {len(self._special_entries())}")

    # ── Acciones ──────────────────────────────────────────────────────────────

    def edit_special(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Inoculaciones", "Seleccioná una aleación especial.")
            return
        self._edit_dialog(idx)

    def delete_special(self):
        idx = self._selected_index()
        if idx is None:
            messagebox.showinfo("Inoculaciones", "Seleccioná una aleación especial.")
            return
        name = self.alloys[idx].get("nombre", "")
        if not messagebox.askyesno("Eliminar", f"¿Eliminar la aleación especial '{name}'?", parent=self):
            return
        self.alloys.pop(idx)
        self._save_and_refresh()

    # ── Diálogo de edición ────────────────────────────────────────────────────

    def _make_listbox(self, parent):
        sb = tk.Scrollbar(parent, orient="vertical")
        lb = tk.Listbox(
            parent,
            selectmode=tk.MULTIPLE,
            exportselection=False,
            bg=BG_ENTRY,
            fg=FG,
            selectbackground=ACCENT,
            selectforeground="#ffffff",
            activestyle="none",
            yscrollcommand=sb.set,
        )
        sb.config(command=lb.yview)
        sb.pack(side="right", fill="y")
        lb.pack(side="left", fill="both", expand=True)
        return lb

    def _edit_dialog(self, idx=None):
        if idx is None:
            messagebox.showinfo("Inoculaciones", "Seleccioná una Aleación final para editar su inoculación.")
            return
        item = self.alloys[idx]
        meta = item.get("inoculacion_meta", {}) if isinstance(item.get("inoculacion_meta", {}), dict) else {}

        # Bases desde calidad_meta
        calidad_meta = item.get("calidad_meta", {}) if isinstance(item.get("calidad_meta", {}), dict) else {}
        bases_str = "  /  ".join(calidad_meta.get("bases", [])) or "—"

        win  = tk.Toplevel(self)
        win.title(f"Inoculación — {item.get('nombre', '')}")
        win.transient(self)
        win.grab_set()
        win.geometry("560x580")
        win.minsize(480, 460)

        actions = ttk.Frame(win, padding=8)
        actions.pack(side="bottom", fill="x")

        root = ttk.Frame(win, padding=10)
        root.pack(fill="both", expand=True)

        # Nombre (readonly)
        row = ttk.Frame(root)
        row.pack(fill="x", pady=(0, 4))
        ttk.Label(row, text="Aleación final:", width=16).pack(side="left")
        ttk.Label(row, text=item.get("nombre", ""), font=("Segoe UI", 10, "bold")).pack(side="left", padx=6)

        # Bases (readonly, desde calidad_meta)
        row_b = ttk.Frame(root)
        row_b.pack(fill="x", pady=(0, 10))
        ttk.Label(row_b, text="Bases (propias):", width=16).pack(side="left")
        ttk.Label(row_b, text=bases_str, foreground="#888888").pack(side="left", padx=6)

        conv_box = ttk.LabelFrame(root, text="Inoculación", padding=6)
        conv_box.pack(fill="both", expand=True)

        # Treeview para inoculación con columnas g/cucharin1 y cant. dosis
        conv_tv = ttk.Treeview(
            conv_box,
            columns=("material", "gramos", "cantidad"),
            show="headings",
            selectmode="browse",
        )
        conv_tv.heading("material", text="Material")
        conv_tv.heading("gramos",   text="g/cucharin1")
        conv_tv.heading("cantidad", text="Cant. dosis")
        conv_tv.column("material", width=170, anchor="w")
        conv_tv.column("gramos",   width=85,  anchor="center")
        conv_tv.column("cantidad", width=85,  anchor="center")
        conv_sb = ttk.Scrollbar(conv_box, orient="vertical", command=conv_tv.yview)
        conv_tv.configure(yscrollcommand=conv_sb.set)
        conv_sb.pack(side="right", fill="y")
        conv_tv.pack(fill="both", expand=True)

        saved_bases     = {str(x).strip() for x in (meta.get("bases", []) or [])}
        saved_inoc_full = {e["nombre"]: e["cantidad_dosis"]
                           for e in self._meta_inoculacion_full(meta)}

        for i, name in enumerate(self._base_names()):
            base_list.insert(tk.END, name)
            if name in saved_bases:
                base_list.selection_set(i)

        for name in self._converter_names():
            g    = self._gramos_cucharin1(name)
            cant = saved_inoc_full.get(name, 0)
            conv_tv.insert("", "end", iid=name,
                           values=(name, f"{g} g" if g else "—", cant if cant else 0))

        # Edición inline con doble clic (columna 2 = gramos, columna 3 = cantidad)
        _inline_entry = {}

        def _close_inline():
            e = _inline_entry.pop("widget", None)
            if e:
                try: e.destroy()
                except Exception: pass

        def _on_tv_double_click(event):
            _close_inline()
            region = conv_tv.identify_region(event.x, event.y)
            col    = conv_tv.identify_column(event.x)
            iid    = conv_tv.identify_row(event.y)
            if region != "cell" or col not in ("#2", "#3") or not iid:
                return
            x, y, w, h = conv_tv.bbox(iid, col)
            nombre = iid
            vals   = conv_tv.item(iid, "values")  # (material, gramos, cantidad)

            if col == "#2":
                g_actual = self._gramos_cucharin1(nombre)
                init_val = str(g_actual) if g_actual else ""
            else:
                init_val = str(vals[2]) if len(vals) > 2 else "1"

            var   = tk.StringVar(value=init_val)
            entry = tk.Entry(conv_tv, textvariable=var, justify="center",
                             bg=BG_ENTRY, fg=FG, insertbackground=FG,
                             relief="flat", highlightthickness=1,
                             highlightbackground=ACCENT)
            entry.place(x=x, y=y, width=w, height=h)
            entry.focus_set()
            entry.select_range(0, tk.END)
            _inline_entry["widget"] = entry

            def _commit(event=None):
                txt = var.get().strip().replace(",", ".")
                if col == "#2":
                    try:
                        g = float(txt) if txt else 0.0
                        if g < 0: raise ValueError
                    except ValueError:
                        _close_inline(); return
                    for alloy in self.alloys:
                        if str(alloy.get("nombre", "")).strip() == nombre:
                            alloy["gramos_cucharin1"] = g
                            break
                    save_alloys(self.alloys)
                    conv_tv.item(iid, values=(nombre, f"{g} g" if g else "—", vals[2]))
                else:
                    try:
                        cant = max(0, int(float(txt))) if txt else 0
                    except ValueError:
                        _close_inline(); return
                    conv_tv.item(iid, values=(nombre, vals[1], cant))
                _close_inline()

            def _cancel(event=None):
                _close_inline()

            entry.bind("<Return>",   _commit)
            entry.bind("<KP_Enter>", _commit)
            entry.bind("<Escape>",   _cancel)
            entry.bind("<FocusOut>", _commit)

        conv_tv.bind("<Double-Button-1>", _on_tv_double_click)

        def _on_tv_scroll(event):
            _close_inline()
            col = conv_tv.identify_column(event.x)
            iid = conv_tv.identify_row(event.y)
            if col != "#3" or not iid:
                return "break" if col == "#3" else None
            delta = -1 if (getattr(event, "delta", 0) < 0 or getattr(event, "num", 0) == 5) else 1
            vals = conv_tv.item(iid, "values")
            try:
                cant = int(float(vals[2])) if vals[2] else 0
            except (ValueError, IndexError):
                cant = 0
            cant = max(0, cant + delta)
            conv_tv.item(iid, values=(vals[0], vals[1], cant))
            return "break"

        conv_tv.bind("<MouseWheel>", _on_tv_scroll)
        conv_tv.bind("<Button-4>",   _on_tv_scroll)
        conv_tv.bind("<Button-5>",   _on_tv_scroll)

        def selected_converters():
            result = []
            for iid in conv_tv.get_children():
                vals = conv_tv.item(iid, "values")
                try:
                    cant = int(float(vals[2])) if vals[2] else 0
                except (ValueError, IndexError):
                    cant = 0
                if cant > 0:
                    result.append({"nombre": vals[0], "cantidad_dosis": cant})
            return result

        def save():
            converters = selected_converters()
            if not converters:
                messagebox.showerror("Validación", "Asigná cantidad > 0 a al menos un material de inoculación.", parent=win)
                return
            self.alloys[idx]["inoculacion_meta"] = {"inoculacion": converters}
            self._save_and_refresh()
            win.destroy()

        ttk.Button(actions, text="Guardar",  command=save).pack(side="right")
        ttk.Button(actions, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

    # ── Helpers de composición ────────────────────────────────────────────────

    def _get_alloy_by_name(self, nombre):
        for a in self.alloys:
            if str(a.get("nombre", "")).strip() == nombre:
                return a
        return None

    @staticmethod
    def _effective_add(alloy, kg):
        rend = to_float(alloy.get("rendimiento", 100)) / 100
        return {e: kg * (to_float(alloy.get("composicion", {}).get(e, 0)) / 100) * rend
                for e in ELEMENTS}

    def _show_comp_dialog(self, titulo, comp, extras=None):
        win = tk.Toplevel(self)
        win.title(titulo)
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        tv = ttk.Treeview(frm, columns=("el", "pct"), show="headings", height=14, selectmode="none")
        tv.heading("el",  text="Elemento")
        tv.heading("pct", text="%")
        tv.column("el",  width=100, anchor="w")
        tv.column("pct", width=110, anchor="center")
        tv.pack(fill="both", expand=True)

        for el in ELEMENTS:
            v = to_float(comp.get(el, 0))
            if v > 0.001:
                tv.insert("", "end", values=(el, fmt(v, 4)))

        if extras:
            for label, value in extras.items():
                ttk.Label(frm, text=f"{label}: {value}", foreground="#888888").pack(anchor="w", pady=(6, 0))

        ttk.Button(frm, text="Cerrar", command=win.destroy).pack(pady=(10, 0))

    # ── Ver composición estimada ──────────────────────────────────────────────

    def _ver_comp_estimada(self):
        idx = self._selected_index()
        if idx is None:
            return
        alloy        = self.alloys[idx]
        meta         = alloy.get("inoculacion_meta", {}) if isinstance(alloy.get("inoculacion_meta", {}), dict) else {}
        calidad_meta = alloy.get("calidad_meta", {}) if isinstance(alloy.get("calidad_meta", {}), dict) else {}
        bases        = calidad_meta.get("bases", []) if isinstance(calidad_meta.get("bases", []), list) else []
        inoculacion  = self._meta_inoculacion_full(meta)

        if not bases:
            messagebox.showinfo("Estimada", "Esta aleación no tiene bases permitidas configuradas.")
            return

        win = tk.Toplevel(self)
        win.title("Composición estimada")
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        row0 = ttk.Frame(frm); row0.pack(fill="x", pady=(0, 6))
        ttk.Label(row0, text="Base:", width=12).pack(side="left")
        base_var = tk.StringVar(value=bases[0])
        ttk.Combobox(row0, textvariable=base_var, values=bases, state="readonly", width=18).pack(side="left", padx=4)

        row1 = ttk.Frame(frm); row1.pack(fill="x", pady=(0, 10))
        ttk.Label(row1, text="Masa baño (kg):", width=16).pack(side="left")
        masa_var = tk.StringVar(value="50")
        ttk.Entry(row1, textvariable=masa_var, width=10).pack(side="left", padx=4)

        tv = ttk.Treeview(frm, columns=("el", "pct"), show="headings", height=14, selectmode="none")
        tv.heading("el",  text="Elemento")
        tv.heading("pct", text="%")
        tv.column("el",  width=100, anchor="w")
        tv.column("pct", width=110, anchor="center")
        tv.pack(fill="both", expand=True)

        ce_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=ce_var, foreground="#888888").pack(anchor="w", pady=(6, 0))

        def calcular():
            for row in tv.get_children():
                tv.delete(row)
            base_alloy = self._get_alloy_by_name(base_var.get())
            if not base_alloy:
                messagebox.showerror("Error", f"Base '{base_var.get()}' no encontrada en catálogo.", parent=win)
                return
            try:
                M0 = to_float(masa_var.get().replace(",", "."))
                if M0 <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Error", "Masa inválida.", parent=win)
                return

            plan = {}
            for e in inoculacion:
                if e["cantidad_dosis"] > 0:
                    g = self._gramos_cucharin1(e["nombre"])
                    if g:
                        plan[e["nombre"]] = (g * e["cantidad_dosis"]) / 1000

            try:
                _, comp_est = simulate_with_plan(
                    M0,
                    base_alloy.get("composicion", {}),
                    plan,
                    ELEMENTS,
                    get_alloy=self._get_alloy_by_name,
                    effective_add=self._effective_add,
                    effective_total_perkg=lambda a: to_float(a.get("rendimiento", 100)) / 100,
                )
            except Exception as ex:
                messagebox.showerror("Error de cálculo", str(ex), parent=win)
                return

            for el in ELEMENTS:
                v = to_float(comp_est.get(el, 0))
                if v > 0.001:
                    tv.insert("", "end", values=(el, fmt(v, 4)))

            ce = ce_from_percent(comp_est)
            ce_var.set(f"CE (Fundición): {fmt(ce, 4)}")

        base_var.trace_add("write", lambda *_: calcular())
        ttk.Button(frm, text="Calcular", command=calcular).pack(pady=(8, 0))
        ttk.Button(frm, text="Cerrar",   command=win.destroy).pack(pady=(4, 0))
        calcular()

    # ── Ver composición real ──────────────────────────────────────────────────

    def _ver_comp_real(self):
        idx = self._selected_index()
        if idx is None:
            return
        alloy        = self.alloys[idx]
        calidad_meta = alloy.get("calidad_meta", {}) if isinstance(alloy.get("calidad_meta", {}), dict) else {}
        bases_perm   = {str(b).strip() for b in (calidad_meta.get("bases", []) or [])}

        history = load_history()
        sesiones = [
            s for s in history
            if str(s.get("objetivo", "")).strip() in bases_perm
            and s.get("ajustes")
        ]

        if not sesiones:
            messagebox.showinfo("Comp. real", "No hay coladas registradas para las bases de esta aleación.")
            return

        opciones = [f"{s['colada']}  ({s.get('objetivo','')})" for s in sesiones]

        win = tk.Toplevel(self)
        win.title("Composición real")
        win.transient(self)
        win.grab_set()
        win.resizable(False, False)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)

        row0 = ttk.Frame(frm); row0.pack(fill="x", pady=(0, 10))
        ttk.Label(row0, text="Colada:", width=10).pack(side="left")
        sel_var = tk.StringVar(value=opciones[-1])
        ttk.Combobox(row0, textvariable=sel_var, values=opciones, state="readonly", width=32).pack(side="left", padx=4)

        tv = ttk.Treeview(frm, columns=("el", "pct"), show="headings", height=14, selectmode="none")
        tv.heading("el",  text="Elemento")
        tv.heading("pct", text="%")
        tv.column("el",  width=100, anchor="w")
        tv.column("pct", width=110, anchor="center")
        tv.pack(fill="both", expand=True)

        ce_var = tk.StringVar(value="")
        ttk.Label(frm, textvariable=ce_var, foreground="#888888").pack(anchor="w", pady=(6, 0))

        def mostrar(*_):
            for row in tv.get_children():
                tv.delete(row)
            sel_idx = opciones.index(sel_var.get()) if sel_var.get() in opciones else -1
            if sel_idx < 0:
                return
            session = sesiones[sel_idx]
            ajustes = session.get("ajustes", [])
            if not ajustes:
                return
            ultimo = ajustes[-1]
            comp = (ultimo.get("estimado") or {}).get("comp") or \
                   (ultimo.get("inicial") or {}).get("comp") or {}

            for el in ELEMENTS:
                v = to_float(comp.get(el, 0))
                if v > 0.001:
                    tv.insert("", "end", values=(el, fmt(v, 4)))

            ce = ce_from_percent(comp)
            ce_var.set(f"CE (Fundición): {fmt(ce, 4)}")

        sel_var.trace_add("write", mostrar)
        ttk.Button(frm, text="Cerrar", command=win.destroy).pack(pady=(8, 0))
        mostrar()

    # ── Guardar ───────────────────────────────────────────────────────────────

    def _save_and_refresh(self):
        save_alloys(self.alloys)
        self.refresh_catalog()
        try:
            self.event_generate("<<CatalogUpdated>>", when="tail")
        except Exception:
            pass
