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

    def _meta_inoculacion(self, meta):
        values = meta.get("inoculacion", [])
        if not isinstance(values, list):
            values = []
        if not values:
            legacy = meta.get("convertidores", [])
            values = legacy if isinstance(legacy, list) else []
        return [str(v).strip() for v in values if str(v).strip()]

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
        bases      = meta.get("bases", []) if isinstance(meta.get("bases", []), list) else []
        inoculacion = self._meta_inoculacion(meta)
        lines = [
            f"Nombre: {alloy.get('nombre', '')}",
            "",
            "Bases permitidas:",
            *(f"  - {n}" for n in bases),
            "",
            "Inoculación:",
            *(f"  - {n}" for n in inoculacion),
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
        top = self.winfo_toplevel()
        bg  = getattr(top, "_input_bg",  "#2b2b2b")
        fg  = getattr(top, "_input_fg",  "#e6e6e6")
        sb  = tk.Scrollbar(parent, orient="vertical")
        lb  = tk.Listbox(
            parent,
            selectmode=tk.MULTIPLE,
            exportselection=False,
            bg=bg, fg=fg,
            selectbackground="#3a7bd5",
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
        conv_list = self._make_listbox(conv_box)

        saved_bases      = {str(x).strip() for x in (meta.get("bases", []) or [])}
        saved_converters = set(self._meta_inoculacion(meta))

        for i, name in enumerate(self._base_names()):
            base_list.insert(tk.END, name)
            if name in saved_bases:
                base_list.selection_set(i)
        for i, name in enumerate(self._converter_names()):
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
            bases      = selected(base_list)
            converters = selected(conv_list)
            if not bases:
                messagebox.showerror("Validación", "Seleccioná al menos una base.", parent=win)
                return
            if not converters:
                messagebox.showerror("Validación", "Seleccioná al menos un material de inoculación.", parent=win)
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
