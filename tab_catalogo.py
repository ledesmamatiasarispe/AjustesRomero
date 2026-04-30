# C:\Users\LABOR01\ajuste_comp\tab_catalogo.py
import tkinter as tk
from tkinter import ttk, messagebox, filedialog
import json, csv

# Módulos del proyecto
from widgets import ScrollFrame
from config import ELEMENTS
from storage import save_alloys
from utils import to_float, to_float_or_none, fmt, fmt_opt, _norm

# ---------------- Helpers locales (evita dependencias ocultas) ----------------
def _normalize_limites(lim_dict):
    out = {}
    for e in ELEMENTS:
        src = (lim_dict or {}).get(e, {})
        out[e] = {
            "soft_min": src.get("soft_min", None),
            "soft_max": src.get("soft_max", None),
            # hard eliminado en UI, se mantiene por compatibilidad
            "hard_min": None,
            "hard_max": None,
        }
    return out

def _normalize_especiales(esp_dict):
    esp = {"CE_formula":"FUNDICION", "CE_min": None, "CE_max": None,
           "CE_custom":{"C":1.0, "Si":1/3, "P":1/3, "S":0.0}}
    if esp_dict:
        esp["CE_formula"] = _norm(esp_dict.get("CE_formula","FUNDICION")) or "FUNDICION"
        esp["CE_min"] = esp_dict.get("CE_min", None)
        esp["CE_max"] = esp_dict.get("CE_max", None)
        raw = esp_dict.get("CE_custom", {})
        clean = {}
        if isinstance(raw, dict):
            for k,v in raw.items():
                if k in ELEMENTS:
                    vv = to_float_or_none(v)
                    if vv is not None: clean[k] = vv
        if clean: esp["CE_custom"] = clean
    return esp

def _catalog_entries_named(model, name):
    target = str(name or "").strip()
    if not target:
        return []
    return [a for a in model if str(a.get("nombre", "")).strip() == target]

def _find_limit_targets(model, name, alloy_type=None):
    matches = _catalog_entries_named(model, name)
    if not matches:
        return []
    wanted_type = str(alloy_type or "").strip()
    if wanted_type:
        return [a for a in matches if a.get("tipo", "") == wanted_type]
    preferred = [a for a in matches if a.get("tipo", "") in ("Aleación propia", "Aleación final")]
    return preferred or matches

def _basic_alloys():
    def alloy(nombre, tipo, rendimiento, costo, comp, limites=None, especiales=None, ajuste=False):
        cdict = {e: 0.0 for e in ELEMENTS}; cdict.update(comp)
        lim = {e: {"soft_min": None, "soft_max": None, "hard_min": None, "hard_max": None} for e in ELEMENTS}
        if limites:
            for e in ELEMENTS: lim[e].update(limites.get(e, {}))
        esp_default = {"CE_formula":"FUNDICION", "CE_min": None, "CE_max": None,
                       "CE_custom": {"C":1.0, "Si":1/3, "P":1/3, "S":0.0}}
        if especiales: esp_default.update(especiales)
        return {"nombre": nombre, "tipo": tipo, "rendimiento": rendimiento, "costo": costo,
                "composicion": cdict, "limites": lim, "especiales": esp_default, "ajuste": bool(ajuste)}

    a1010 = {"C":0.10, "Mn":0.50, "P":0.02, "S":0.02}
    a1010["Fe"] = max(0.0, 100.0 - sum(a1010.values()))
    fecr_alto_c = {"Cr": 62.5, "C": 7.5, "Si": 1.5, "S": 0.03, "P": 0.03}
    fecr_alto_c["Fe"] = max(0.0, 100.0 - sum(fecr_alto_c.values()))

    return [
        alloy("FeCr alto C", "Ferroaleación", 90.0, 0.0, fecr_alto_c, ajuste=True),
        alloy("FeSi", "Ferroaleación", 90.0, 0.0, {"Si": 75.0}, ajuste=True),
        alloy("FeMn", "Ferroaleación", 90.0, 0.0, {"Mn": 80.0}, ajuste=True),
        alloy("FeCr", "Ferroaleación", 90.0, 0.0, {"Cr": 65.0}, ajuste=True),
        alloy("Carbón de grafito", "Aditivo", 90.0, 0.0, {"C": 99.0}, ajuste=True),
        alloy("Silicio", "Metal puro", 90.0, 0.0, {"Si": 100.0}, ajuste=True),
        alloy("Acero 1010", "Retorno", 100.0, 0.0, a1010, ajuste=True),
        alloy("Pirita de azufre", "Aditivo", 90.0, 0.0, {"S": 53.4, "Fe": 46.6}, ajuste=True),
    ]

# --------------------------------- Catálogo -----------------------------------
class TabCatalogo(ttk.Frame):
    BASE_COLS = ("Nombre","Tipo","Rendimiento %","Costo","Límites")
    COLS = BASE_COLS + tuple(ELEMENTS)
    TYPES = ["Ferroaleación", "Metal puro", "Recorte", "Retorno", "Aditivo", "Aleación propia", "Aleación final", "Otro"]

    def __init__(self, master, model):
        super().__init__(master, padding=8)
        self.model = model
        self.filtered_idx = list(range(len(self.model)))

        top = ttk.Frame(self); top.pack(fill="x", pady=(0,8))
        ttk.Label(top, text="Buscar:").pack(side="left")
        self.q = tk.StringVar()
        ent = ttk.Entry(top, textvariable=self.q, width=30); ent.pack(side="left", padx=6)
        ent.bind("<KeyRelease>", lambda e: self.apply_filter())
        ttk.Button(top, text="Nuevo",    command=self.add_item).pack(side="left", padx=2)
        ttk.Button(top, text="Editar",   command=self.edit_item).pack(side="left", padx=2)
        ttk.Button(top, text="Duplicar", command=self.dup_item).pack(side="left", padx=2)
        ttk.Button(top, text="Eliminar", command=self.del_item).pack(side="left", padx=2)
        ttk.Button(top, text="Restablecer básicos", command=self.reset_basics).pack(side="left", padx=12)

        right = ttk.Frame(top); right.pack(side="right")
        ttk.Button(right, text="Exportar límites", command=self.export_limits_csv).pack(side="right", padx=2)
        ttk.Button(right, text="Importar límites", command=self.import_limits_csv).pack(side="right", padx=2)
        ttk.Button(right, text="Exportar CSV",     command=self.export_csv).pack(side="right", padx=2)
        ttk.Button(right, text="Importar CSV",     command=self.import_csv).pack(side="right", padx=2)

        grid_frame = ttk.Frame(self); grid_frame.pack(fill="both", expand=True)
        xsb = ttk.Scrollbar(grid_frame, orient='horizontal')
        ysb = ttk.Scrollbar(grid_frame, orient='vertical')
        self.tree = ttk.Treeview(grid_frame, columns=self.COLS, show="headings", height=16,
                                 xscrollcommand=xsb.set, yscrollcommand=ysb.set)
        xsb.config(command=self.tree.xview); ysb.config(command=self.tree.yview)

        for c in self.COLS:
            self.tree.heading(c, text=c)
            self.tree.column(c, width=(120 if c in self.BASE_COLS else 70), anchor="center")

        self.tree.grid(row=0, column=0, sticky="nsew")
        ysb.grid(row=0, column=1, sticky="ns")
        xsb.grid(row=1, column=0, sticky="ew")
        grid_frame.rowconfigure(0, weight=1); grid_frame.columnconfigure(0, weight=1)

        self.refresh()

        bot = ttk.Frame(self); bot.pack(fill="x", pady=(8,0))
        ttk.Label(bot, text="Tip: 'Recalcular Fe' ajusta Fe = 100 - suma(resto).").pack(side="left")

    # --------------------- acciones básicas de grilla -------------------------
    def _has_any_limits(self, a):
        lim = a.get("limites", {})
        for e in ELEMENTS:
            d = lim.get(e, {})
            if any(d.get(k) is not None for k in ("soft_min","soft_max")):
                return True
        return False

    def reset_basics(self):
        if messagebox.askyesno("Restablecer básicos", "Reemplaza TODO el catálogo por las aleaciones básicas. ¿Continuar?"):
            self.model.clear(); self.model.extend(_basic_alloys()); self._save_and_refresh()

    def refresh(self):
        valid_idx = [i for i in self.filtered_idx if 0 <= i < len(self.model)]
        if len(valid_idx) != len(self.model) and not self.q.get().strip():
            self.filtered_idx = list(range(len(self.model)))
        else:
            self.filtered_idx = valid_idx
        for i in self.tree.get_children(): self.tree.delete(i)
        for idx in self.filtered_idx:
            a = self.model[idx]
            row = [
                a.get("nombre",""),
                a.get("tipo",""),
                fmt(to_float(a.get("rendimiento",0)), 6),
                fmt(to_float(a.get("costo",0)), 6),
                "Sí" if self._has_any_limits(a) else "",
            ] + [fmt(to_float(a["composicion"].get(e,0)), 6) for e in ELEMENTS]
            self.tree.insert("", "end", iid=str(idx), values=tuple(row))

    def apply_filter(self):
        q = self.q.get().strip().lower()
        self.filtered_idx = []
        for i, a in enumerate(self.model):
            limits_text = json.dumps(a.get("limites", {}), ensure_ascii=False)
            row = " ".join([
                a.get("nombre",""), a.get("tipo",""),
                str(a.get("rendimiento","")), str(a.get("costo","")), limits_text,
                json.dumps(a.get("especiales", {}), ensure_ascii=False)
            ] + [str(a["composicion"].get(e,"")) for e in ELEMENTS]).lower()
            if q in row: self.filtered_idx.append(i)
        self.refresh()

    def _selected_index(self):
        sel = self.tree.selection()
        if not sel:
            messagebox.showinfo("Catálogo", "Seleccioná una aleación primero."); return None
        return int(sel[0])

    def add_item(self): self._edit_dialog()
    def edit_item(self):
        idx = self._selected_index()
        if idx is not None: self._edit_dialog(self.model[idx], idx)
    def dup_item(self):
        idx = self._selected_index()
        if idx is not None:
            new_item = json.loads(json.dumps(self.model[idx]))
            new_item["nombre"] = (new_item.get("nombre","") + " (copia)").strip()
            self.model.append(new_item); self._save_and_refresh()
    def del_item(self):
        idx = self._selected_index()
        if idx is not None and messagebox.askyesno("Eliminar", "¿Eliminar la aleación seleccionada?"):
            self.model.pop(idx); self._save_and_refresh()

    # ---------------------- import/export catálogo ----------------------------
    def export_csv(self):
        fp = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], title="Exportar catálogo a CSV")
        if not fp: return
        with open(fp, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f)
            w.writerow(["nombre","tipo","rendimiento","costo"] + ELEMENTS)
            for a in self.model:
                row = [a.get("nombre",""), a.get("tipo",""), a.get("rendimiento",0), a.get("costo",0)]
                row += [a["composicion"].get(e,0) for e in ELEMENTS]
                w.writerow(row)
        messagebox.showinfo("Exportar", "Catálogo exportado.")

    def import_csv(self):
        fp = filedialog.askopenfilename(filetypes=[("CSV","*.csv")], title="Importar catálogo desde CSV")
        if not fp: return
        try:
            new_list = []
            with open(fp, "r", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    comp = {e: to_float(row.get(e,0)) for e in ELEMENTS}
                    new_list.append({
                        "nombre": row.get("nombre",""),
                        "tipo": row.get("tipo","Ferroaleación"),
                        "rendimiento": to_float(row.get("rendimiento",90)),
                        "costo": to_float(row.get("costo",0)),
                        "composicion": comp,
                        "limites": _normalize_limites(None),
                        "especiales": _normalize_especiales(None),
                    })
            if messagebox.askyesno("Importar", "Esto reemplazará el catálogo actual. ¿Continuar?"):
                self.model.clear(); self.model.extend(new_list)
                self._save_and_refresh()
        except Exception as ex:
            messagebox.showerror("Importar", f"No se pudo importar:\n{ex}")

    # ---------------------- import/export límites -----------------------------
    def export_limits_csv(self):
        fp = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], title="Exportar límites (Aleación propia/final)")
        if not fp: return
        try:
            with open(fp, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                header = ["nombre","tipo","CE_formula","CE_min","CE_max"]
                for e in ELEMENTS:
                    header += [f"{e}_soft_min", f"{e}_soft_max"]
                w.writerow(header)
                for a in self.model:
                    if a.get("tipo","") not in ("Aleación propia", "Aleación final"):
                        continue
                    row = [a.get("nombre",""), a.get("tipo","")]
                    esp = a.get("especiales", {})
                    row += [esp.get("CE_formula","FUNDICION"), fmt_opt(esp.get("CE_min")), fmt_opt(esp.get("CE_max"))]
                    lim = a.get("limites", {})
                    for e in ELEMENTS:
                        d = lim.get(e, {})
                        row += [fmt_opt(d.get("soft_min")), fmt_opt(d.get("soft_max"))]
                    w.writerow(row)
            messagebox.showinfo("Exportar límites", "Límites exportados.")
        except Exception as ex:
            messagebox.showerror("Exportar límites", f"No se pudo exportar:\n{ex}")

    def import_limits_csv(self):
        fp = filedialog.askopenfilename(filetypes=[("CSV","*.csv")], title="Importar límites (Aleación propia/final)")
        if not fp: return
        try:
            updated = 0; skipped = 0; ambiguous = 0
            with open(fp, "r", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    name = (row.get("nombre","") or "").strip()
                    if not name: skipped += 1; continue
                    alloy_type = (row.get("tipo", "") or "").strip()
                    targets = _find_limit_targets(self.model, name, alloy_type=alloy_type)
                    if alloy_type:
                        if not targets:
                            skipped += 1
                            continue
                    else:
                        if len(targets) != 1:
                            skipped += 1
                            if len(targets) > 1:
                                ambiguous += 1
                            continue
                    for found in targets:
                        # especiales
                        esp = found.get("especiales", {})
                        esp["CE_formula"] = _norm(row.get("CE_formula","FUNDICION")) or "FUNDICION"
                        esp["CE_min"] = to_float_or_none(row.get("CE_min",""))
                        esp["CE_max"] = to_float_or_none(row.get("CE_max",""))
                        found["especiales"] = _normalize_especiales(esp)
                        # límites (soft)
                        lim = found.get("limites", {})
                        for e in ELEMENTS:
                            lim_e = lim.get(e, {"soft_min":None,"soft_max":None,"hard_min":None,"hard_max":None})
                            lim_e["soft_min"] = to_float_or_none(row.get(f"{e}_soft_min", ""))
                            lim_e["soft_max"] = to_float_or_none(row.get(f"{e}_soft_max", ""))
                            lim_e["hard_min"] = None
                            lim_e["hard_max"] = None
                            lim[e] = lim_e
                        found["limites"] = lim
                        if found.get("tipo","") not in ("Aleación propia", "Aleación final"):
                            found["tipo"] = "Aleación propia"
                        updated += 1
            self._save_and_refresh()
            msg = f"Actualizadas: {updated}\nIgnoradas: {skipped}"
            if ambiguous:
                msg += f"\nAmbiguas sin tipo: {ambiguous}"
            messagebox.showinfo("Importar límites", msg)
        except Exception as ex:
            messagebox.showerror("Importar límites", f"No se pudo importar:\n{ex}")

    # -------------------------- Editor de aleación ----------------------------
    def _edit_dialog(self, item=None, idx=None):
        win = tk.Toplevel(self); win.title("Aleación"); win.transient(self); win.grab_set()
        win.update_idletasks()
        sw, sh = win.winfo_screenwidth(), win.winfo_screenheight()
        w = min(1020, int(sw*0.92)); h = min(840, int(sh*0.92))
        x = (sw - w)//2; y = (sh - h)//2
        win.geometry(f"{w}x{h}+{x}+{y}")
        win.minsize(860, 620)
        win.rowconfigure(0, weight=1); win.columnconfigure(0, weight=1)

        container = ScrollFrame(win); container.grid(row=0, column=0, sticky="nsew")
        form = ttk.Frame(container.inner, padding=10); form.pack(fill="both", expand=True)

        nombre = tk.StringVar(value=(item or {}).get("nombre",""))
        tipo   = tk.StringVar(value=(item or {}).get("tipo","Ferroaleación"))
        rend   = tk.StringVar(value=fmt(to_float((item or {}).get("rendimiento",90)),6))
        costo  = tk.StringVar(value=fmt(to_float((item or {}).get("costo",0)),6))
        v_ajuste = tk.BooleanVar(value=bool((item or {}).get("ajuste", False)))
        calidad_meta = (item or {}).get("calidad_meta", {}) or {}
        q_defaults = calidad_meta.get("defaults", {}) if isinstance(calidad_meta.get("defaults", {}), dict) else {}
        base_candidates = []
        for a in self.model:
            if a is item:
                continue
            if a.get("tipo", "") != "Aleación propia":
                continue
            name = str(a.get("nombre", "")).strip()
            if name:
                base_candidates.append(name)
        for b in (calidad_meta.get("bases") or []):
            if str(b).strip():
                base_candidates.append(str(b).strip())
        base_candidates = sorted(set(base_candidates), key=lambda v: (0, int(v)) if str(v).isdigit() else (1, str(v)))

        row0 = ttk.Frame(form); row0.pack(fill="x", pady=4)
        ttk.Label(row0, text="Nombre", width=16).pack(side="left")
        ttk.Entry(row0, textvariable=nombre, width=40).pack(side="left", padx=6)

        row1 = ttk.Frame(form); row1.pack(fill="x", pady=4)
        ttk.Label(row1, text="Tipo", width=16).pack(side="left")
        cb_tipo = ttk.Combobox(row1, textvariable=tipo, values=self.TYPES, state="readonly", width=37)
        cb_tipo.pack(side="left", padx=6)
        ttk.Checkbutton(row1, text="Material de ajuste", variable=v_ajuste).pack(side="left", padx=(12, 0))

        row2 = ttk.Frame(form); row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="Rendimiento (%)", width=16).pack(side="left")
        ttk.Entry(row2, textvariable=rend, width=12).pack(side="left", padx=6)
        ttk.Label(row2, text="Costo (opcional)", width=16).pack(side="left", padx=(20,0))
        ttk.Entry(row2, textvariable=costo, width=12).pack(side="left", padx=6)

        final_frame = ttk.LabelFrame(form, text="Ficha de calidad (Aleación final)", padding=8)
        saved_bases = [str(b).strip() for b in (calidad_meta.get("bases") or []) if str(b).strip()]
        if not saved_bases:
            base_ref_seed = str(calidad_meta.get("base_ref", "")).strip()
            saved_bases = [base_ref_seed] if base_ref_seed else []
        base_vars = {base: tk.BooleanVar(value=(base in saved_bases)) for base in base_candidates}
        final_family = tk.StringVar(value=str(calidad_meta.get("family", "")))
        final_traccion = tk.StringVar(value=str(q_defaults.get("traccion", "")))
        final_seccion = tk.StringVar(value=str((calidad_meta.get("section_options") or ["", "", ""])[0] if len(calidad_meta.get("section_options") or []) == 1 else q_defaults.get("seccion", "")))
        final_dureza = tk.StringVar(value=str(q_defaults.get("dureza", "")))
        final_tam = tk.StringVar(value=str(q_defaults.get("tam_grafito", "")))
        final_morf = tk.StringVar(value=str(q_defaults.get("morfologia", "")))
        final_tipo_graf = tk.StringVar(value=str(q_defaults.get("tipo_grafito", "")))
        final_conteo = tk.StringVar(value=str(q_defaults.get("conteo_nodulos", "")))
        final_pct_nod = tk.StringVar(value=str(q_defaults.get("pct_nodularizacion", "")))
        final_alarg = tk.StringVar(value=str(q_defaults.get("alargamiento", "")))
        final_perlita = tk.StringVar(value=str(q_defaults.get("perlita", "")))
        final_ferrita = tk.StringVar(value=str(q_defaults.get("ferrita", "")))
        final_cementita = tk.StringVar(value=str(q_defaults.get("cementita", "0")))

        rowf0 = ttk.Frame(final_frame); rowf0.pack(fill="x", pady=2)
        ttk.Label(rowf0, text="Bases válidas", width=16).pack(side="left")
        for base in base_candidates:
            ttk.Checkbutton(rowf0, text=base, variable=base_vars[base]).pack(side="left", padx=(0, 6))
        ttk.Label(rowf0, text="Familia", width=10).pack(side="left", padx=(20,0))
        cb_final_family = ttk.Combobox(rowf0, textvariable=final_family, values=("Gris", "Nodular"), state="readonly", width=16)
        cb_final_family.pack(side="left", padx=6)

        rowf1 = ttk.Frame(final_frame); rowf1.pack(fill="x", pady=2)
        ttk.Label(rowf1, text="Tracción", width=16).pack(side="left")
        ttk.Entry(rowf1, textvariable=final_traccion, width=12).pack(side="left", padx=6)
        ttk.Label(rowf1, text="Sección muestra", width=16).pack(side="left", padx=(20,0))
        ttk.Entry(rowf1, textvariable=final_seccion, width=18).pack(side="left", padx=6)
        ttk.Label(rowf1, text="Dureza", width=10).pack(side="left", padx=(20,0))
        ttk.Entry(rowf1, textvariable=final_dureza, width=12).pack(side="left", padx=6)

        rowf2 = ttk.Frame(final_frame); rowf2.pack(fill="x", pady=2)
        ttk.Label(rowf2, text="Tamaño grafito", width=16).pack(side="left")
        ttk.Entry(rowf2, textvariable=final_tam, width=12).pack(side="left", padx=6)
        final_morf_label = ttk.Label(rowf2, text="Morfología", width=16)
        final_morf_label.pack(side="left", padx=(20,0))
        final_morf_entry = ttk.Entry(rowf2, textvariable=final_morf, width=18)
        final_morf_entry.pack(side="left", padx=6)
        final_tipo_label = ttk.Label(rowf2, text="Tipo grafito", width=10)
        final_tipo_label.pack(side="left", padx=(20,0))
        ttk.Entry(rowf2, textvariable=final_tipo_graf, width=18).pack(side="left", padx=6)

        rowf3 = ttk.Frame(final_frame); rowf3.pack(fill="x", pady=2)
        ttk.Label(rowf3, text="Conteo nódulos", width=16).pack(side="left")
        ttk.Entry(rowf3, textvariable=final_conteo, width=12).pack(side="left", padx=6)
        ttk.Label(rowf3, text="% nodularización", width=16).pack(side="left", padx=(20,0))
        ttk.Entry(rowf3, textvariable=final_pct_nod, width=18).pack(side="left", padx=6)
        ttk.Label(rowf3, text="Alargamiento", width=10).pack(side="left", padx=(20,0))
        ttk.Entry(rowf3, textvariable=final_alarg, width=12).pack(side="left", padx=6)

        rowf4 = ttk.Frame(final_frame); rowf4.pack(fill="x", pady=2)
        ttk.Label(rowf4, text="Perlita", width=16).pack(side="left")
        ttk.Entry(rowf4, textvariable=final_perlita, width=12).pack(side="left", padx=6)
        ttk.Label(rowf4, text="Ferrita", width=16).pack(side="left", padx=(20,0))
        ttk.Entry(rowf4, textvariable=final_ferrita, width=18).pack(side="left", padx=6)
        ttk.Label(rowf4, text="Cementita", width=10).pack(side="left", padx=(20,0))
        ttk.Entry(rowf4, textvariable=final_cementita, width=12).pack(side="left", padx=6)

        comp_title = ttk.Label(form, text="Composición (% en peso)", font=("Segoe UI", 10, "bold"))
        comp_title.pack(anchor="w", pady=(8,2))
        comp_vars = {}
        grid = ttk.Frame(form); grid.pack(fill="x")
        ncols = 4
        for i, el in enumerate(ELEMENTS):
            r = i // ncols; c = i % ncols
            fr = ttk.Frame(grid, padding=2); fr.grid(row=r, column=c, sticky="w")
            ttk.Label(fr, text=f"{el}:", width=4).pack(side="left")
            v = tk.StringVar(value=fmt(to_float((item or {}).get("composicion", {}).get(el,0)),6))
            ttk.Entry(fr, textvariable=v, width=8).pack(side="left")
            comp_vars[el] = v

        btns = ttk.Frame(form); btns.pack(fill="x", pady=(8,0))
        def recalc_fe():
            try:
                s = sum(to_float(comp_vars[e].get()) for e in ELEMENTS if e != "Fe")
                comp_vars["Fe"].set(fmt(max(0.0, 100.0 - s), 6))
            except Exception as ex:
                messagebox.showerror("Recalcular Fe", str(ex))
        ttk.Button(btns, text="Recalcular Fe", command=recalc_fe).pack(side="left")
        def auto_limits():
            win = tk.Toplevel(self)
            win.title("Auto-límites")
            win.transient(self)
            win.grab_set()
            win.resizable(False, False)
            frm = ttk.Frame(win, padding=10)
            frm.pack(fill="both", expand=True)

            ttk.Label(frm, text="Rango ± absoluto").grid(row=0, column=0, sticky="w")
            v_abs = tk.StringVar(value="0.10")
            e_abs = ttk.Entry(frm, textvariable=v_abs, width=8)
            e_abs.grid(row=0, column=1, padx=6)

            ttk.Label(frm, text="Elementos a aplicar").grid(row=1, column=0, columnspan=2, sticky="w", pady=(10,0))
            lb = tk.Listbox(frm, selectmode=tk.MULTIPLE, height=8, exportselection=False)
            lb.grid(row=2, column=0, columnspan=2, sticky="we", pady=(4,0))
            for el in ELEMENTS:
                lb.insert(tk.END, el)
                lb.selection_set(tk.END)

            sel_btns = ttk.Frame(frm)
            sel_btns.grid(row=3, column=0, columnspan=2, sticky="e", pady=(4,0))
            def select_all():
                lb.selection_set(0, tk.END)
            def select_none():
                lb.selection_clear(0, tk.END)
            ttk.Button(sel_btns, text="Todos", command=select_all).pack(side="right")
            ttk.Button(sel_btns, text="Ninguno", command=select_none).pack(side="right", padx=6)

            btns2 = ttk.Frame(frm)
            btns2.grid(row=4, column=0, columnspan=2, pady=(10,0), sticky="e")

            def apply():
                try:
                    abs_rng = to_float_or_none(v_abs.get())
                    if abs_rng is None or abs_rng < 0:
                        raise ValueError("Rango inválido.")
                    sel_idx = set(lb.curselection())
                    for i, el in enumerate(ELEMENTS):
                        if sel_idx and i not in sel_idx:
                            continue
                        ideal = to_float_or_none(comp_vars[el].get())
                        if ideal is None or ideal <= 0:
                            v_rng, *_ = limit_vars[el]
                            v_rng.set("")
                            continue
                        v_rng, *_ = limit_vars[el]
                        v_rng.set(fmt_opt(abs_rng))
                    win.destroy()
                except Exception as ex:
                    messagebox.showerror("Auto-límites", str(ex), parent=win)

            ttk.Button(btns2, text="Aplicar", command=apply).pack(side="right")
            ttk.Button(btns2, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

            e_abs.focus_set()
            win.wait_window()

        ttk.Button(btns, text="Auto-límites...", command=auto_limits).pack(side="left", padx=6)

        # --- Límites (solo Aleación propia/final) ---
        limits_frame = ttk.LabelFrame(form, text="Rango ± (solo Aleación propia/final)", padding=8)
        limits_frame.pack(fill="both", expand=True, pady=(12,0))

        sf_lim = ScrollFrame(limits_frame); sf_lim.pack(fill="both", expand=True)
        head = ttk.Frame(sf_lim.inner); head.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        for j, c in enumerate(("Elemento","± absoluto")):
            ttk.Label(head, text=c, font=("Segoe UI",10,"bold")).grid(row=0, column=j, padx=6, pady=2)

        limit_vars = {}
        existing_limits = _normalize_limites((item or {}).get("limites", {}))
        for i, el in enumerate(ELEMENTS, start=1):
            r = ttk.Frame(sf_lim.inner); r.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            ttk.Label(r, text=el, width=6).grid(row=0, column=0, padx=4)
            ideal = to_float_or_none(comp_vars[el].get())
            sm = existing_limits[el]["soft_min"]
            sM = existing_limits[el]["soft_max"]
            delta = ""
            if ideal is not None and sm is not None and sM is not None:
                d1 = ideal - sm
                d2 = sM - ideal
                if d1 >= 0 and d2 >= 0:
                    delta = fmt_opt(min(d1, d2))
            v_rng = tk.StringVar(value=delta)
            e_rng = ttk.Entry(r, textvariable=v_rng, width=10)
            e_rng.grid(row=0, column=1, padx=4)
            limit_vars[el] = (v_rng, e_rng)

        def _toggle_limits_state(*_):
            state = "normal" if tipo.get() in ("Aleación propia", "Aleación final") else "disabled"
            for el in ELEMENTS:
                _, e_rng = limit_vars[el]
                e_rng.config(state=state)
        cb_tipo.bind("<<ComboboxSelected>>", lambda e: _toggle_limits_state())
        _toggle_limits_state()

        # --- Valores especiales (CE) ---
        esp = _normalize_especiales((item or {}).get("especiales", {}))
        esp_frame = ttk.LabelFrame(form, text="Valores especiales (solo Aleación propia/final)", padding=8)
        esp_frame.pack(fill="x", pady=(12,0))

        ttk.Label(esp_frame, text="Carbono equivalente (CE)").grid(row=0, column=0, columnspan=6, sticky="w", padx=4, pady=(0,4))
        ttk.Label(esp_frame, text="Fórmula").grid(row=1, column=0, sticky="e", padx=4)
        v_ce_formula = tk.StringVar(value=esp.get("CE_formula","FUNDICION"))
        cbf = ttk.Combobox(esp_frame, textvariable=v_ce_formula, state="readonly",
                           values=["FUNDICION","IIW","IIW+Si/24","CET","PERSONALIZADA"], width=14)
        cbf.grid(row=1, column=1, sticky="w", padx=4)

        ttk.Label(esp_frame, text="CE min").grid(row=1, column=2, sticky="e", padx=4)
        ttk.Label(esp_frame, text="CE max").grid(row=1, column=4, sticky="e", padx=4)
        v_ce_min = tk.StringVar(value=fmt_opt(esp.get("CE_min")))
        v_ce_max = tk.StringVar(value=fmt_opt(esp.get("CE_max")))
        e_ce_min = ttk.Entry(esp_frame, textvariable=v_ce_min, width=10); e_ce_min.grid(row=1, column=3, sticky="w", padx=4)
        e_ce_max = ttk.Entry(esp_frame, textvariable=v_ce_max, width=10); e_ce_max.grid(row=1, column=5, sticky="w", padx=4)

        cust = esp.get("CE_custom", {"C":1.0,"Si":1/3,"P":1/3,"S":0.0})
        cust_frame = ttk.LabelFrame(esp_frame, text="Coeficientes CE (CE = Σ coef × %elem)", padding=6)
        cust_vars = {}
        cust_frame.grid(row=2, column=0, columnspan=6, sticky="ew", padx=2, pady=(6,2))

        sf_ce = ScrollFrame(cust_frame); sf_ce.pack(fill="both", expand=True)
        head_ce = ttk.Frame(sf_ce.inner); head_ce.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        ttk.Label(head_ce, text="Elemento", font=("Segoe UI",10,"bold")).grid(row=0, column=0, padx=6)
        ttk.Label(head_ce, text="Coef.", font=("Segoe UI",10,"bold")).grid(row=0, column=1, padx=6)
        for i, el in enumerate(ELEMENTS, start=1):
            rr = ttk.Frame(sf_ce.inner); rr.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            ttk.Label(rr, text=el, width=6).grid(row=0, column=0, padx=4)
            v = tk.StringVar(value=fmt_opt(cust.get(el, 0.0)))
            ttk.Entry(rr, textvariable=v, width=10).grid(row=0, column=1, padx=4)
            cust_vars[el] = v

        def _toggle_cust():
            if _norm(v_ce_formula.get()) == "PERSONALIZADA":
                cust_frame.grid()
            else:
                cust_frame.grid_remove()
        cbf.bind("<<ComboboxSelected>>", lambda e: _toggle_cust())
        _toggle_cust()

        def _selected_final_bases():
            return [base for base, var in base_vars.items() if var.get()]
        if not final_family.get().strip():
            final_family.set("Gris")

        def _toggle_final_family_fields(*_):
            if final_family.get().strip() == "Nodular":
                final_morf.set("")
                final_morf_label.pack_forget()
                final_morf_entry.pack_forget()
            else:
                if not final_morf_label.winfo_manager():
                    final_morf_label.pack(side="left", padx=(20,0), before=final_tipo_label)
                if not final_morf_entry.winfo_manager():
                    final_morf_entry.pack(side="left", padx=6, before=final_tipo_label)

        cb_final_family.bind("<<ComboboxSelected>>", _toggle_final_family_fields)
        _toggle_final_family_fields()

        final_frame.pack(fill="x", pady=(12, 0))

        def _toggle_dialog_mode(*_):
            is_final = (tipo.get().strip() == "Aleación final")
            if is_final:
                comp_title.pack_forget()
                grid.pack_forget()
                btns.pack_forget()
                limits_frame.pack_forget()
                esp_frame.pack_forget()
                final_frame.pack(fill="x", pady=(12, 0))
                v_ajuste.set(False)
            else:
                final_frame.pack_forget()
                if not comp_title.winfo_manager():
                    comp_title.pack(anchor="w", pady=(8,2))
                if not grid.winfo_manager():
                    grid.pack(fill="x")
                if not btns.winfo_manager():
                    btns.pack(fill="x", pady=(8,0))
                if not limits_frame.winfo_manager():
                    limits_frame.pack(fill="both", expand=True, pady=(12,0))
                if not esp_frame.winfo_manager():
                    esp_frame.pack(fill="x", pady=(12,0))
            _toggle_limits_state()

        cb_tipo.bind("<<ComboboxSelected>>", lambda e: (_toggle_limits_state(), _toggle_dialog_mode()))
        _toggle_dialog_mode()

        # --- Guardar/Cancelar ---
        def accept():
            try:
                a = {
                    "nombre": nombre.get().strip(),
                    "tipo": (tipo.get().strip() or "Ferroaleación"),
                    "rendimiento": to_float(rend.get()),
                    "costo": to_float(costo.get()),
                    "composicion": {el: to_float(comp_vars[el].get()) for el in ELEMENTS},
                    "limites": {},
                    "especiales": {},
                    "ajuste": bool(v_ajuste.get()),
                }
                src_item = item or {}
                for extra_key, extra_val in src_item.items():
                    if extra_key not in a:
                        a[extra_key] = extra_val
                if not a["nombre"]:
                    raise ValueError("El nombre es obligatorio.")
                if not (0 < a["rendimiento"] <= 100):
                    raise ValueError("Rendimiento debe estar entre 0 y 100.")

                if a["tipo"] == "Aleación final":
                    bases = [base for base, var in base_vars.items() if var.get()]
                    if not bases:
                        raise ValueError("Seleccioná al menos una base válida.")
                    family = final_family.get().strip()
                    if family not in ("Gris", "Nodular"):
                        raise ValueError("Seleccioná una familia válida.")
                    base_ref = bases[0]
                    defaults = {
                        "traccion": final_traccion.get().strip(),
                        "seccion": final_seccion.get().strip(),
                        "dureza": final_dureza.get().strip(),
                        "tam_grafito": final_tam.get().strip(),
                        "morfologia": "" if family == "Nodular" else final_morf.get().strip(),
                        "tipo_grafito": final_tipo_graf.get().strip(),
                        "conteo_nodulos": final_conteo.get().strip(),
                        "pct_nodularizacion": final_pct_nod.get().strip(),
                        "alargamiento": final_alarg.get().strip(),
                        "perlita": final_perlita.get().strip(),
                        "ferrita": final_ferrita.get().strip(),
                        "cementita": final_cementita.get().strip(),
                    }
                    src_item = item or {}
                    prev_meta = src_item.get("calidad_meta", {}) if isinstance(src_item.get("calidad_meta", {}), dict) else {}
                    a["ajuste"] = False
                    a["composicion"] = src_item.get("composicion", {})
                    a["limites"] = src_item.get("limites", {})
                    a["especiales"] = src_item.get("especiales", {})
                    a["calidad_meta"] = {
                        "es_material_final": True,
                        "codigo": a["nombre"],
                        "base_ref": base_ref,
                        "bases": bases,
                        "family": family,
                        "section_options": prev_meta.get("section_options", []),
                        "defaults": defaults,
                    }
                    if idx is None:
                        self.model.append(a)
                    else:
                        self.model[idx] = a
                    self._save_and_refresh()
                    win.destroy()
                    return

                # limites (solo soft por rango ± absoluto)
                for el in ELEMENTS:
                    v_rng, *_ = limit_vars[el]
                    rng = to_float_or_none(v_rng.get())
                    ideal = to_float_or_none(comp_vars[el].get())
                    if rng is None or ideal is None or ideal <= 0:
                        sm = None; sM = None
                    else:
                        if rng < 0:
                            raise ValueError(f"[{el}] Rango inválido.")
                        sm = ideal - rng
                        sM = ideal + rng
                        if sm > sM:
                            raise ValueError(f"[{el}] Rango inválido.")
                    a["limites"][el] = {"soft_min": sm, "soft_max": sM, "hard_min": None, "hard_max": None}

                # CE
                ce_min = to_float_or_none(v_ce_min.get()); ce_max = to_float_or_none(v_ce_max.get())
                if ce_min is not None and ce_max is not None and ce_min > ce_max:
                    raise ValueError("CE min > CE max")
                ce_formula = _norm(v_ce_formula.get() or "FUNDICION")
                esp_out = {"CE_formula": ce_formula, "CE_min": ce_min, "CE_max": ce_max}
                if ce_formula == "PERSONALIZADA":
                    coefs = {}
                    for el, var in cust_vars.items():
                        val = to_float_or_none(var.get())
                        if val is not None and abs(val) > 0.0:
                            coefs[el] = val
                    if "C" not in coefs: coefs["C"] = 1.0
                    esp_out["CE_custom"] = coefs
                a["especiales"] = esp_out

                # suma composición
                s = sum(a["composicion"].values())
                if s > 100.000001 and not messagebox.askyesno("Composición", f"La suma da {fmt(s)}%. ¿Guardar igual?"):
                    return

                if idx is None:
                    self.model.append(a)
                else:
                    self.model[idx] = a
                self._save_and_refresh(); win.destroy()
            except Exception as ex:
                messagebox.showerror("Validación", str(ex))

        actions = ttk.Frame(win, padding=8)
        actions.grid(row=1, column=0, sticky="ew")
        actions.columnconfigure(0, weight=1)
        ttk.Button(actions, text="Guardar", command=accept).pack(side="right")
        ttk.Button(actions, text="Cancelar", command=win.destroy).pack(side="right", padx=6)

    # -------------------------- helpers ----------------------------
    def _save_and_refresh(self):
        save_alloys(self.model)
        self.apply_filter()
        try:
            self.event_generate("<<CatalogUpdated>>", when="tail")
        except Exception:
            pass

