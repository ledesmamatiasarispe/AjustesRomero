import tkinter as tk
from tkinter import ttk, messagebox

from storage import save_alloys


SPECIAL_TYPE = "Aleación especial"


class TabInoculaciones(ttk.Frame):
    def __init__(self, master, alloys_model):
        super().__init__(master, padding=8)
        self.alloys = alloys_model

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Aleaciones especiales").pack(side="left")
        ttk.Button(top, text="Nueva", command=self.add_special).pack(side="left", padx=(12, 2))
        ttk.Button(top, text="Editar", command=self.edit_special).pack(side="left", padx=2)
        ttk.Button(top, text="Eliminar", command=self.delete_special).pack(side="left", padx=2)
        ttk.Button(top, text="Refrescar", command=self.refresh_catalog).pack(side="right")

        main = ttk.PanedWindow(self, orient="vertical")
        main.pack(fill="both", expand=True)

        inoc_box = ttk.LabelFrame(main, text="Inoculantes", padding=6)
        main.add(inoc_box, weight=1)

        inoc_btns = ttk.Frame(inoc_box)
        inoc_btns.pack(fill="x", pady=(0, 6))
        ttk.Button(inoc_btns, text="Nuevo inoculante", command=self.add_inoculant).pack(side="left")
        ttk.Button(inoc_btns, text="Editar inoculante", command=self.edit_inoculant).pack(side="left", padx=6)
        ttk.Button(inoc_btns, text="Eliminar inoculante", command=self.delete_inoculant).pack(side="left")

        self.inoc_tree = ttk.Treeview(inoc_box, columns=("nombre", "base", "medidas"), show="headings", height=7)
        for cid, title, width in (
            ("nombre", "Nombre", 220),
            ("base", "Basado en", 220),
            ("medidas", "Medidas", 360),
        ):
            self.inoc_tree.heading(cid, text=title)
            self.inoc_tree.column(cid, width=width, anchor="w")
        self.inoc_tree.pack(fill="both", expand=True)
        self.inoc_tree.bind("<Double-Button-1>", lambda _e: self.edit_inoculant())

        split = ttk.PanedWindow(main, orient="horizontal")
        main.add(split, weight=3)
        split.pack(fill="both", expand=True)

        left = ttk.LabelFrame(split, text="Especiales", padding=6)
        right = ttk.LabelFrame(split, text="Detalle", padding=6)
        split.add(left, weight=2)
        split.add(right, weight=3)

        self.tree = ttk.Treeview(left, columns=("nombre",), show="headings", height=16)
        for cid, title, width in (
            ("nombre", "Nombre", 300),
        ):
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda _e: self._show_selected_detail())
        self.tree.bind("<Double-Button-1>", lambda _e: self.edit_special())

        self.detail_text = tk.Text(right, height=18, wrap="word")
        self.detail_text.pack(fill="both", expand=True)
        self.detail_text.config(state="disabled")

        self.status_var = tk.StringVar(value="")
        ttk.Label(self, textvariable=self.status_var, foreground="#555555").pack(anchor="w", pady=(8, 0))
        self.refresh_catalog()

    def _is_inoculant(self, alloy):
        return (
            bool(alloy.get("inoculante", False))
            or str(alloy.get("subtipo", "")).strip() == "Inoculante"
            or str(alloy.get("tipo", "")).strip() == "Inoculante"
        )

    def _is_special(self, alloy):
        return str(alloy.get("tipo", "")).strip() == SPECIAL_TYPE

    def _inoculant_entries(self):
        return [(idx, alloy) for idx, alloy in enumerate(self.alloys) if self._is_inoculant(alloy)]

    def _material_names_for_inoculant_base(self, exclude_idx=None):
        names = []
        for idx, alloy in enumerate(self.alloys):
            if idx == exclude_idx:
                continue
            name = str(alloy.get("nombre", "")).strip()
            if name:
                names.append(name)
        return sorted(set(names), key=lambda value: (0, int(value)) if value.isdigit() else (1, value.lower()))

    def _base_names(self):
        return sorted(
            {str(a.get("nombre", "")).strip() for a in self.alloys if str(a.get("tipo", "")).strip() == "Aleación propia" and str(a.get("nombre", "")).strip()},
            key=lambda value: (0, int(value)) if value.isdigit() else (1, value.lower()),
        )

    def _converter_names(self):
        allowed = {"Ferroaleación", "Metal puro"}
        names = []
        for alloy in self.alloys:
            name = str(alloy.get("nombre", "")).strip()
            if not name:
                continue
            if str(alloy.get("tipo", "")).strip() in allowed or self._is_inoculant(alloy):
                names.append(name)
        return sorted(set(names), key=lambda value: (0, int(value)) if value.isdigit() else (1, value.lower()))

    def _meta_inoculacion(self, meta):
        values = meta.get("inoculacion", [])
        if not isinstance(values, list):
            values = []
        if not values:
            legacy = meta.get("convertidores", [])
            values = legacy if isinstance(legacy, list) else []
        return [str(value).strip() for value in values if str(value).strip()]

    def _special_entries(self):
        return [(idx, alloy) for idx, alloy in enumerate(self.alloys) if self._is_special(alloy)]

    def refresh_catalog(self):
        selected_name = self._selected_name()
        for item in self.inoc_tree.get_children():
            self.inoc_tree.delete(item)
        for idx, alloy in self._inoculant_entries():
            meta = alloy.get("inoculante_meta", {}) if isinstance(alloy.get("inoculante_meta", {}), dict) else {}
            medidas = meta.get("medidas", []) if isinstance(meta.get("medidas", []), list) else []
            medidas_txt = "; ".join(
                f"{str(med.get('nombre', '') or f'Medida {i + 1}')}: {med.get('gramos', '')} g"
                for i, med in enumerate(medidas)
                if isinstance(med, dict)
            )
            self.inoc_tree.insert(
                "",
                "end",
                iid=f"inoc-{idx}",
                values=(alloy.get("nombre", ""), meta.get("base_material", ""), medidas_txt),
            )
        for item in self.tree.get_children():
            self.tree.delete(item)
        selected_iid = None
        for idx, alloy in self._special_entries():
            iid = str(idx)
            name = alloy.get("nombre", "")
            self.tree.insert("", "end", iid=iid, values=(name,))
            if selected_name and selected_name == name:
                selected_iid = iid
        if selected_iid:
            self.tree.selection_set(selected_iid)
        self._show_selected_detail()
        self.status_var.set(f"Inoculantes: {len(self._inoculant_entries())} | Aleaciones especiales: {len(self._special_entries())}")

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

    def _selected_inoculant_index(self):
        sel = self.inoc_tree.selection()
        if not sel:
            return None
        raw = str(sel[0])
        if raw.startswith("inoc-"):
            raw = raw[5:]
        try:
            return int(raw)
        except Exception:
            return None

    def _show_selected_detail(self):
        idx = self._selected_index()
        self.detail_text.config(state="normal")
        self.detail_text.delete("1.0", tk.END)
        if idx is None or idx < 0 or idx >= len(self.alloys):
            self.detail_text.insert("1.0", "Seleccioná una aleación especial.")
            self.detail_text.config(state="disabled")
            return
        alloy = self.alloys[idx]
        meta = alloy.get("inoculacion_meta", {}) if isinstance(alloy.get("inoculacion_meta", {}), dict) else {}
        bases = meta.get("bases", []) if isinstance(meta.get("bases", []), list) else []
        inoculacion = self._meta_inoculacion(meta)
        lines = [
            f"Nombre: {alloy.get('nombre', '')}",
            "",
            "Bases permitidas:",
            *(f"- {name}" for name in bases),
            "",
            "Inoculación:",
            *(f"- {name}" for name in inoculacion),
        ]
        self.detail_text.insert("1.0", "\n".join(lines))
        self.detail_text.config(state="disabled")

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

    def add_inoculant(self):
        self._edit_inoculant_dialog()

    def edit_inoculant(self):
        idx = self._selected_inoculant_index()
        if idx is None:
            messagebox.showinfo("Inoculaciones", "Seleccioná un inoculante.")
            return
        self._edit_inoculant_dialog(idx)

    def delete_inoculant(self):
        idx = self._selected_inoculant_index()
        if idx is None:
            messagebox.showinfo("Inoculaciones", "Seleccioná un inoculante.")
            return
        name = self.alloys[idx].get("nombre", "")
        used_by = []
        for alloy in self.alloys:
            if not self._is_special(alloy):
                continue
            meta = alloy.get("inoculacion_meta", {}) if isinstance(alloy.get("inoculacion_meta", {}), dict) else {}
            if name in self._meta_inoculacion(meta):
                used_by.append(str(alloy.get("nombre", "")).strip())
        if used_by:
            messagebox.showerror("Eliminar inoculante", "No se puede eliminar: está usado por " + ", ".join(used_by), parent=self)
            return
        if not messagebox.askyesno("Eliminar", f"¿Eliminar el inoculante '{name}'?", parent=self):
            return
        self.alloys.pop(idx)
        self._save_and_refresh()

    def _edit_inoculant_dialog(self, idx=None):
        item = self.alloys[idx] if idx is not None else {}
        meta = item.get("inoculante_meta", {}) if isinstance(item.get("inoculante_meta", {}), dict) else {}
        win = tk.Toplevel(self)
        win.title("Inoculante")
        win.transient(self)
        win.grab_set()
        win.geometry("560x520")
        win.minsize(500, 440)

        root = ttk.Frame(win, padding=10)
        root.pack(fill="both", expand=True)

        name_var = tk.StringVar(value=item.get("nombre", ""))
        base_var = tk.StringVar(value=meta.get("base_material", ""))
        rend_var = tk.StringVar(value=str(item.get("rendimiento", 100.0)))
        costo_var = tk.StringVar(value=str(item.get("costo", 0.0)))
        medidas = []
        for i, med in enumerate(meta.get("medidas", []) if isinstance(meta.get("medidas", []), list) else [], start=1):
            if isinstance(med, dict):
                medidas.append({
                    "nombre": str(med.get("nombre", "") or f"Medida {i}"),
                    "gramos": float(med.get("gramos", 0.0) or 0.0),
                })

        for label, var, width in (
            ("Nombre", name_var, 34),
            ("Rendimiento %", rend_var, 12),
            ("Costo", costo_var, 12),
        ):
            row = ttk.Frame(root)
            row.pack(fill="x", pady=3)
            ttk.Label(row, text=label, width=16).pack(side="left")
            ttk.Entry(row, textvariable=var, width=width).pack(side="left", padx=6)

        row_base = ttk.Frame(root)
        row_base.pack(fill="x", pady=3)
        ttk.Label(row_base, text="Basado en", width=16).pack(side="left")
        cb_base = ttk.Combobox(row_base, textvariable=base_var, values=self._material_names_for_inoculant_base(idx), state="readonly", width=34)
        cb_base.pack(side="left", padx=6)

        box = ttk.LabelFrame(root, text="Medidas", padding=6)
        box.pack(fill="both", expand=True, pady=(10, 0))
        lb = tk.Listbox(box, height=8)
        lb.pack(fill="both", expand=True)

        def refresh_lb():
            lb.delete(0, tk.END)
            for med in medidas:
                lb.insert(tk.END, f"{med.get('nombre', '')}: {med.get('gramos', 0.0)} g")

        def edit_measure(existing=None):
            out = {"value": None}
            w = tk.Toplevel(win)
            w.title("Medida")
            w.transient(win)
            w.grab_set()
            w.resizable(False, False)
            frm = ttk.Frame(w, padding=10)
            frm.pack(fill="both", expand=True)
            v_name = tk.StringVar(value=(existing or {}).get("nombre", f"Medida {len(medidas) + 1}"))
            v_g = tk.StringVar(value=str((existing or {}).get("gramos", 150)))
            ttk.Label(frm, text="Nombre", width=10).grid(row=0, column=0, sticky="w", pady=3)
            ttk.Entry(frm, textvariable=v_name, width=24).grid(row=0, column=1, pady=3)
            ttk.Label(frm, text="Gramos", width=10).grid(row=1, column=0, sticky="w", pady=3)
            ttk.Entry(frm, textvariable=v_g, width=12).grid(row=1, column=1, sticky="w", pady=3)
            btns = ttk.Frame(frm)
            btns.grid(row=2, column=0, columnspan=2, sticky="e", pady=(8, 0))

            def ok():
                try:
                    grams = float(str(v_g.get()).replace(",", "."))
                    if grams <= 0:
                        raise ValueError("Los gramos deben ser > 0.")
                    out["value"] = {"nombre": v_name.get().strip() or f"Medida {len(medidas) + 1}", "gramos": grams}
                    w.destroy()
                except Exception as ex:
                    messagebox.showerror("Medida", str(ex), parent=w)

            ttk.Button(btns, text="Aceptar", command=ok).pack(side="right")
            ttk.Button(btns, text="Cancelar", command=w.destroy).pack(side="right", padx=6)
            w.wait_window()
            return out["value"]

        def add_measure():
            med = edit_measure()
            if med:
                medidas.append(med)
                refresh_lb()

        def update_measure():
            sel = lb.curselection()
            if not sel:
                return
            med = edit_measure(medidas[sel[0]])
            if med:
                medidas[sel[0]] = med
                refresh_lb()

        def delete_measure():
            sel = lb.curselection()
            if not sel:
                return
            del medidas[sel[0]]
            refresh_lb()

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(6, 0))
        ttk.Button(btns, text="Agregar", command=add_measure).pack(side="left")
        ttk.Button(btns, text="Editar", command=update_measure).pack(side="left", padx=6)
        ttk.Button(btns, text="Eliminar", command=delete_measure).pack(side="left")
        refresh_lb()

        def save():
            name = name_var.get().strip()
            base = base_var.get().strip()
            if not name:
                messagebox.showerror("Validación", "El nombre es obligatorio.", parent=win)
                return
            if not base:
                messagebox.showerror("Validación", "Seleccioná el material base.", parent=win)
                return
            if not medidas:
                messagebox.showerror("Validación", "Agregá al menos una medida.", parent=win)
                return
            base_item = next((a for i, a in enumerate(self.alloys) if i != idx and str(a.get("nombre", "")).strip() == base), None)
            if not base_item:
                messagebox.showerror("Validación", "No se encontró el material base.", parent=win)
                return
            try:
                rendimiento = float(str(rend_var.get()).replace(",", "."))
                costo = float(str(costo_var.get()).replace(",", "."))
            except Exception:
                messagebox.showerror("Validación", "Rendimiento/costo inválido.", parent=win)
                return
            entry = dict(item or {})
            entry.update({
                "nombre": name,
                "tipo": "Inoculante",
                "rendimiento": rendimiento,
                "costo": costo,
                "composicion": dict(base_item.get("composicion", {}) or {}),
                "limites": {},
                "especiales": {},
                "ajuste": False,
                "inoculante": True,
                "subtipo": "Inoculante",
                "inoculante_meta": {
                    "base_material": base,
                    "medidas": list(medidas),
                },
            })
            if idx is None:
                self.alloys.append(entry)
            else:
                self.alloys[idx] = entry
            self._save_and_refresh()
            win.destroy()

        actions = ttk.Frame(win, padding=8)
        actions.pack(fill="x")
        ttk.Button(actions, text="Guardar", command=save).pack(side="right")
        ttk.Button(actions, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

    def _edit_dialog(self, idx=None):
        item = self.alloys[idx] if idx is not None else {}
        meta = item.get("inoculacion_meta", {}) if isinstance(item.get("inoculacion_meta", {}), dict) else {}
        win = tk.Toplevel(self)
        win.title("Aleación especial")
        win.transient(self)
        win.grab_set()
        win.geometry("720x620")
        win.minsize(620, 520)

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
        conv_box = ttk.LabelFrame(lists, text="Inoculación", padding=6)
        bases_box.pack(side="left", fill="both", expand=True, padx=(0, 6))
        conv_box.pack(side="left", fill="both", expand=True)

        base_list = tk.Listbox(bases_box, selectmode=tk.MULTIPLE, exportselection=False)
        base_list.pack(fill="both", expand=True)
        conv_list = tk.Listbox(conv_box, selectmode=tk.MULTIPLE, exportselection=False)
        conv_list.pack(fill="both", expand=True)

        saved_bases = set(str(x).strip() for x in (meta.get("bases", []) or []))
        saved_converters = set(str(x).strip() for x in self._meta_inoculacion(meta))

        base_names = self._base_names()
        converter_names = self._converter_names()
        for i, name in enumerate(base_names):
            base_list.insert(tk.END, name)
            if name in saved_bases:
                base_list.selection_set(i)
        for i, name in enumerate(converter_names):
            conv_list.insert(tk.END, name)
            if name in saved_converters:
                conv_list.selection_set(i)

        def selected(lb):
            return [lb.get(i) for i in lb.curselection()]

        def save():
            name = name_var.get().strip()
            if not name:
                messagebox.showerror("Validación", "El nombre es obligatorio.", parent=win)
                return
            bases = selected(base_list)
            converters = selected(conv_list)
            if not bases:
                messagebox.showerror("Validación", "Seleccioná al menos una base.", parent=win)
                return
            if not converters:
                messagebox.showerror("Validación", "Seleccioná al menos un material de inoculación.", parent=win)
                return
            entry = dict(item or {})
            entry.update({
                "nombre": name,
                "tipo": SPECIAL_TYPE,
                "rendimiento": entry.get("rendimiento", 100.0),
                "costo": entry.get("costo", 0.0),
                "composicion": entry.get("composicion", {}),
                "limites": entry.get("limites", {}),
                "especiales": entry.get("especiales", {}),
                "ajuste": False,
                "inoculacion_meta": {
                    "bases": bases,
                    "inoculacion": converters,
                },
            })
            if idx is None:
                self.alloys.append(entry)
            else:
                self.alloys[idx] = entry
            self._save_and_refresh()
            win.destroy()

        actions = ttk.Frame(win, padding=8)
        actions.pack(fill="x")
        ttk.Button(actions, text="Guardar", command=save).pack(side="right")
        ttk.Button(actions, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

    def _save_and_refresh(self):
        save_alloys(self.alloys)
        self.refresh_catalog()
        try:
            self.event_generate("<<CatalogUpdated>>", when="tail")
        except Exception:
            pass
