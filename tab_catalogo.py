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
            "hard_min": src.get("hard_min", None),
            "hard_max": src.get("hard_max", None),
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

def _basic_alloys():
    def alloy(nombre, tipo, rendimiento, costo, comp, limites=None, especiales=None):
        cdict = {e: 0.0 for e in ELEMENTS}; cdict.update(comp)
        lim = {e: {"soft_min": None, "soft_max": None, "hard_min": None, "hard_max": None} for e in ELEMENTS}
        if limites:
            for e in ELEMENTS: lim[e].update(limites.get(e, {}))
        esp_default = {"CE_formula":"FUNDICION", "CE_min": None, "CE_max": None,
                       "CE_custom": {"C":1.0, "Si":1/3, "P":1/3, "S":0.0}}
        if especiales: esp_default.update(especiales)
        return {"nombre": nombre, "tipo": tipo, "rendimiento": rendimiento, "costo": costo,
                "composicion": cdict, "limites": lim, "especiales": esp_default}

    a1010 = {"C":0.10, "Mn":0.50, "P":0.02, "S":0.02}
    a1010["Fe"] = max(0.0, 100.0 - sum(a1010.values()))

    return [
        alloy("FeSi", "Ferroaleación", 90.0, 0.0, {"Si": 75.0}),
        alloy("FeMn", "Ferroaleación", 90.0, 0.0, {"Mn": 80.0}),
        alloy("FeCr", "Ferroaleación", 90.0, 0.0, {"Cr": 65.0}),
        alloy("Carbón de grafito", "Aditivo", 90.0, 0.0, {"C": 99.0}),
        alloy("Silicio", "Metal puro", 90.0, 0.0, {"Si": 100.0}),
        alloy("Acero 1010", "Retorno", 100.0, 0.0, a1010),
        alloy("Pirita de azufre", "Aditivo", 90.0, 0.0, {"S": 53.4, "Fe": 46.6}),
    ]

# --------------------------------- Catálogo -----------------------------------
class TabCatalogo(ttk.Frame):
    BASE_COLS = ("Nombre","Tipo","Rendimiento %","Costo","Límites")
    COLS = BASE_COLS + tuple(ELEMENTS)
    TYPES = ["Ferroaleación", "Metal puro", "Recorte", "Retorno", "Aditivo", "Aleación propia", "Otro"]

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
            if any(d.get(k) is not None for k in ("soft_min","soft_max","hard_min","hard_max")):
                return True
        return False

    def reset_basics(self):
        if messagebox.askyesno("Restablecer básicos", "Reemplaza TODO el catálogo por las aleaciones básicas. ¿Continuar?"):
            self.model.clear(); self.model.extend(_basic_alloys()); save_alloys(self.model); self.apply_filter()

    def refresh(self):
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
            self.model.append(new_item); save_alloys(self.model); self.apply_filter()
    def del_item(self):
        idx = self._selected_index()
        if idx is not None and messagebox.askyesno("Eliminar", "¿Eliminar la aleación seleccionada?"):
            self.model.pop(idx); save_alloys(self.model); self.apply_filter()

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
                save_alloys(self.model); self.apply_filter()
        except Exception as ex:
            messagebox.showerror("Importar", f"No se pudo importar:\n{ex}")

    # ---------------------- import/export límites -----------------------------
    def export_limits_csv(self):
        fp = filedialog.asksaveasfilename(defaultextension=".csv", filetypes=[("CSV","*.csv")], title="Exportar límites (Aleación propia)")
        if not fp: return
        try:
            with open(fp, "w", newline="", encoding="utf-8") as f:
                w = csv.writer(f)
                header = ["nombre","CE_formula","CE_min","CE_max"]
                for e in ELEMENTS:
                    header += [f"{e}_soft_min", f"{e}_soft_max", f"{e}_hard_min", f"{e}_hard_max"]
                w.writerow(header)
                for a in self.model:
                    if a.get("tipo","") != "Aleación propia": continue
                    row = [a.get("nombre","")]
                    esp = a.get("especiales", {})
                    row += [esp.get("CE_formula","FUNDICION"), fmt_opt(esp.get("CE_min")), fmt_opt(esp.get("CE_max"))]
                    lim = a.get("limites", {})
                    for e in ELEMENTS:
                        d = lim.get(e, {})
                        row += [fmt_opt(d.get("soft_min")), fmt_opt(d.get("soft_max")),
                                fmt_opt(d.get("hard_min")), fmt_opt(d.get("hard_max"))]
                    w.writerow(row)
            messagebox.showinfo("Exportar límites", "Límites exportados.")
        except Exception as ex:
            messagebox.showerror("Exportar límites", f"No se pudo exportar:\n{ex}")

    def import_limits_csv(self):
        fp = filedialog.askopenfilename(filetypes=[("CSV","*.csv")], title="Importar límites (Aleación propia)")
        if not fp: return
        try:
            updated = 0; skipped = 0
            with open(fp, "r", encoding="utf-8") as f:
                r = csv.DictReader(f)
                for row in r:
                    name = (row.get("nombre","") or "").strip()
                    if not name: skipped += 1; continue
                    found = None
                    for a in self.model:
                        if a.get("nombre","") == name: found = a; break
                    if not found: skipped += 1; continue
                    # especiales
                    esp = found.get("especiales", {})
                    esp["CE_formula"] = _norm(row.get("CE_formula","FUNDICION")) or "FUNDICION"
                    esp["CE_min"] = to_float_or_none(row.get("CE_min",""))
                    esp["CE_max"] = to_float_or_none(row.get("CE_max",""))
                    found["especiales"] = _normalize_especiales(esp)
                    # límites
                    lim = found.get("limites", {})
                    for e in ELEMENTS:
                        lim_e = lim.get(e, {"soft_min":None,"soft_max":None,"hard_min":None,"hard_max":None})
                        lim_e["soft_min"] = to_float_or_none(row.get(f"{e}_soft_min", ""))
                        lim_e["soft_max"] = to_float_or_none(row.get(f"{e}_soft_max", ""))
                        lim_e["hard_min"] = to_float_or_none(row.get(f"{e}_hard_min", ""))
                        lim_e["hard_max"] = to_float_or_none(row.get(f"{e}_hard_max", ""))
                        lim[e] = lim_e
                    found["limites"] = lim
                    if found.get("tipo","") != "Aleación propia": found["tipo"] = "Aleación propia"
                    updated += 1
            save_alloys(self.model); self.apply_filter()
            messagebox.showinfo("Importar límites", f"Actualizadas: {updated}\nIgnoradas: {skipped}")
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

        row0 = ttk.Frame(form); row0.pack(fill="x", pady=4)
        ttk.Label(row0, text="Nombre", width=16).pack(side="left")
        ttk.Entry(row0, textvariable=nombre, width=40).pack(side="left", padx=6)

        row1 = ttk.Frame(form); row1.pack(fill="x", pady=4)
        ttk.Label(row1, text="Tipo", width=16).pack(side="left")
        cb_tipo = ttk.Combobox(row1, textvariable=tipo, values=self.TYPES, state="readonly", width=37)
        cb_tipo.pack(side="left", padx=6)

        row2 = ttk.Frame(form); row2.pack(fill="x", pady=4)
        ttk.Label(row2, text="Rendimiento (%)", width=16).pack(side="left")
        ttk.Entry(row2, textvariable=rend, width=12).pack(side="left", padx=6)
        ttk.Label(row2, text="Costo (opcional)", width=16).pack(side="left", padx=(20,0))
        ttk.Entry(row2, textvariable=costo, width=12).pack(side="left", padx=6)

        ttk.Label(form, text="Composición (% en peso)", font=("Segoe UI", 10, "bold")).pack(anchor="w", pady=(8,2))
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

        # --- Límites (solo Aleación propia) ---
        limits_frame = ttk.LabelFrame(form, text="Límites (solo Aleación propia)", padding=8)
        limits_frame.pack(fill="both", expand=True, pady=(12,0))

        sf_lim = ScrollFrame(limits_frame); sf_lim.pack(fill="both", expand=True)
        head = ttk.Frame(sf_lim.inner); head.grid(row=0, column=0, sticky="ew", padx=2, pady=2)
        for j, c in enumerate(("Elemento","Soft min","Soft max","Hard min","Hard max")):
            ttk.Label(head, text=c, font=("Segoe UI",10,"bold")).grid(row=0, column=j, padx=6, pady=2)

        limit_vars = {}
        existing_limits = _normalize_limites((item or {}).get("limites", {}))
        for i, el in enumerate(ELEMENTS, start=1):
            r = ttk.Frame(sf_lim.inner); r.grid(row=i, column=0, sticky="ew", padx=2, pady=1)
            ttk.Label(r, text=el, width=6).grid(row=0, column=0, padx=4)
            v_sm = tk.StringVar(value=fmt_opt(existing_limits[el]["soft_min"]))
            v_sM = tk.StringVar(value=fmt_opt(existing_limits[el]["soft_max"]))
            v_hm = tk.StringVar(value=fmt_opt(existing_limits[el]["hard_min"]))
            v_hM = tk.StringVar(value=fmt_opt(existing_limits[el]["hard_max"]))
            e_sm = ttk.Entry(r, textvariable=v_sm, width=10)
            e_sM = ttk.Entry(r, textvariable=v_sM, width=10)
            e_hm = ttk.Entry(r, textvariable=v_hm, width=10)
            e_hM = ttk.Entry(r, textvariable=v_hM, width=10)
            e_sm.grid(row=0, column=1, padx=4); e_sM.grid(row=0, column=2, padx=4)
            e_hm.grid(row=0, column=3, padx=4); e_hM.grid(row=0, column=4, padx=4)
            limit_vars[el] = (v_sm, v_sM, v_hm, v_hM, e_sm, e_sM, e_hm, e_hM)

        def _toggle_limits_state(*_):
            state = "normal" if tipo.get() == "Aleación propia" else "disabled"
            for el in ELEMENTS:
                _, _, _, _, e_sm, e_sM, e_hm, e_hM = limit_vars[el]
                e_sm.config(state=state); e_sM.config(state=state); e_hm.config(state=state); e_hM.config(state=state)
        cb_tipo.bind("<<ComboboxSelected>>", lambda e: _toggle_limits_state())
        _toggle_limits_state()

        # --- Valores especiales (CE) ---
        esp = _normalize_especiales((item or {}).get("especiales", {}))
        esp_frame = ttk.LabelFrame(form, text="Valores especiales (solo Aleación propia)", padding=8)
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

        # --- Guardar/Cancelar ---
        actions = ttk.Frame(form); actions.pack(fill="x", pady=(10,0))
        def accept():
            try:
                a = {
                    "nombre": nombre.get().strip(),
                    "tipo": (tipo.get().strip() or "Ferroaleación"),
                    "rendimiento": to_float(rend.get()),
                    "costo": to_float(costo.get()),
                    "composicion": {el: to_float(comp_vars[el].get()) for el in ELEMENTS},
                    "limites": {},
                    "especiales": {}
                }
                if not a["nombre"]:
                    raise ValueError("El nombre es obligatorio.")
                if not (0 < a["rendimiento"] <= 100):
                    raise ValueError("Rendimiento debe estar entre 0 y 100.")

                # límites
                for el in ELEMENTS:
                    v_sm, v_sM, v_hm, v_hM, *_ = limit_vars[el]
                    sm = to_float_or_none(v_sm.get()); sM = to_float_or_none(v_sM.get())
                    hm = to_float_or_none(v_hm.get()); hM = to_float_or_none(v_hM.get())
                    if hm is not None and hM is not None and hm > hM: raise ValueError(f"[{el}] Hard min > Hard max")
                    if sm is not None and sM is not None and sm > sM: raise ValueError(f"[{el}] Soft min > Soft max")
                    if hm is not None and sm is not None and sm < hm: raise ValueError(f"[{el}] Soft min < Hard min")
                    if hM is not None and sM is not None and sM > hM: raise ValueError(f"[{el}] Soft max > Hard max")
                    a["limites"][el] = {"soft_min": sm, "soft_max": sM, "hard_min": hm, "hard_max": hM}

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
                save_alloys(self.model); self.apply_filter(); win.destroy()
            except Exception as ex:
                messagebox.showerror("Validación", str(ex))

        ttk.Button(actions, text="Guardar", command=accept).pack(side="right")
        ttk.Button(actions, text="Cancelar", command=win.destroy).pack(side="right")
