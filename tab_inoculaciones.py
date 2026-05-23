import tkinter as tk
from tkinter import ttk, messagebox

from storage import save_alloys
from config import BG_ENTRY, FG, ACCENT


SPECIAL_TYPE = "Aleación especial"


class TabInoculaciones(ttk.Frame):
    def __init__(self, master, alloys_model):
        super().__init__(master, padding=8)
        self.alloys = alloys_model

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Aleaciones especiales").pack(side="left")
        ttk.Button(top, text="Nueva",    command=self.add_special).pack(side="left", padx=(12, 2))
        ttk.Button(top, text="Editar",   command=self.edit_special).pack(side="left", padx=2)
        ttk.Button(top, text="Eliminar", command=self.delete_special).pack(side="left", padx=2)
        ttk.Button(top, text="Refrescar", command=self.refresh_catalog).pack(side="right")

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

        self.detail_text = tk.Text(right, height=18, wrap="word")
        self.detail_text.pack(fill="both", expand=True)
        self.detail_text.config(state="disabled")

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, foreground="#555555").pack(anchor="w", pady=(8, 0))
        self.refresh_catalog()

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _is_special(self, alloy):
        return str(alloy.get("tipo", "")).strip() == SPECIAL_TYPE

    def _special_entries(self):
        return [(idx, alloy) for idx, alloy in enumerate(self.alloys) if self._is_special(alloy)]

    def _base_names(self):
        return sorted(
            {str(a.get("nombre", "")).strip()
             for a in self.alloys
             if str(a.get("tipo", "")).strip() == "Aleación propia"
             and str(a.get("nombre", "")).strip()},
            key=lambda v: (0, int(v)) if v.isdigit() else (1, v.lower()),
        )

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
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", tk.END)
        if idx is None or idx < 0 or idx >= len(self.alloys):
            self.detail_text.insert("1.0", "Seleccioná una aleación especial.")
            self.detail_text.config(state="disabled")
            return
        alloy = self.alloys[idx]
        meta  = alloy.get("inoculacion_meta", {}) if isinstance(alloy.get("inoculacion_meta", {}), dict) else {}
        bases        = meta.get("bases", []) if isinstance(meta.get("bases", []), list) else []
        inoculacion  = self._meta_inoculacion_full(meta)
        def _fmt_entry(e):
            g   = self._gramos_cucharin1(e["nombre"])
            g_s = f"{g} g/dos" if g else "—"
            return f"  - {e['nombre']}  ×{e['cantidad_dosis']}  ({g_s})"
        lines = [
            f"Nombre: {alloy.get('nombre', '')}",
            "",
            "Bases permitidas:",
            *(f"  - {n}" for n in bases),
            "",
            "Inoculación:",
            *(_fmt_entry(e) for e in inoculacion),
        ]
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.config(state="disabled")

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
        self.status_var.set(f"Aleaciones especiales: {len(self._special_entries())}")

    # ── Acciones ──────────────────────────────────────────────────────────────

    def add_special(self):
        self._edit_dialog()

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
        item = self.alloys[idx] if idx is not None else {}
        meta = item.get("inoculacion_meta", {}) if isinstance(item.get("inoculacion_meta", {}), dict) else {}
        win  = tk.Toplevel(self)
        win.title("Aleación especial")
        win.transient(self)
        win.grab_set()
        win.geometry("720x620")
        win.minsize(620, 520)

        # Botones al fondo primero para que no queden ocultos
        actions = ttk.Frame(win, padding=8)
        actions.pack(side="bottom", fill="x")

        root = ttk.Frame(win, padding=10)
        root.pack(fill="both", expand=True)

        name_var = tk.StringVar(value=item.get("nombre", ""))
        row = ttk.Frame(root)
        row.pack(fill="x", pady=(0, 8))
        ttk.Label(row, text="Nombre", width=14).pack(side="left")
        ttk.Entry(row, textvariable=name_var, width=40).pack(side="left", padx=6)

        lists = ttk.Frame(root)
        lists.pack(fill="both", expand=True)
        bases_box = ttk.LabelFrame(lists, text="Bases permitidas (Aleación propia)", padding=6)
        conv_box  = ttk.LabelFrame(lists, text="Inoculación", padding=6)
        bases_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        conv_box.pack(side="left",  fill="both", expand=True)

        base_list = self._make_listbox(bases_box)

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

        def selected_bases():
            return [base_list.get(i) for i in base_list.curselection()]

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
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Validación", "El nombre es obligatorio.", parent=win)
                return
            bases      = selected_bases()
            converters = selected_converters()
            if not bases:
                messagebox.showerror("Validación", "Seleccioná al menos una base.", parent=win)
                return
            if not converters:
                messagebox.showerror("Validación", "Asigná cantidad > 0 a al menos un material de inoculación.", parent=win)
                return
            entry = dict(item or {})
            entry.update({
                "nombre":     name,
                "tipo":       SPECIAL_TYPE,
                "rendimiento": entry.get("rendimiento", 100.0),
                "costo":       entry.get("costo", 0.0),
                "composicion": entry.get("composicion", {}),
                "limites":     entry.get("limites", {}),
                "especiales":  entry.get("especiales", {}),
                "ajuste":      False,
                "inoculacion_meta": {
                    "bases":       bases,
                    "inoculacion": converters,
                },
            })
            if idx is None:
                self.alloys.append(entry)
            else:
                self.alloys[idx] = entry
            self._save_and_refresh()
            win.destroy()

        ttk.Button(actions, text="Guardar",  command=save).pack(side="right")
        ttk.Button(actions, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

    # ── Guardar ───────────────────────────────────────────────────────────────

    def _save_and_refresh(self):
        save_alloys(self.alloys)
        self.refresh_catalog()
        try:
            self.event_generate("<<CatalogUpdated>>", when="tail")
        except Exception:
            pass
