import tkinter as tk
from tkinter import ttk, messagebox
from datetime import datetime
import re
import html
import tempfile
import webbrowser
from pathlib import Path

from storage import load_quality_reports, save_quality_reports
from utils import fmt
from config import BG_ENTRY, FG, ACCENT

DEFAULT_SECTION_OPTIONS = ["Hasta 13 mm", "De 12 a 25 mm", "De 20 a 50 mm"]
GRAPHITE_TYPE_OPTIONS = (
    "A 100%",
    "A 95% / B 5%",
    "A 90% / B 10%",
    "A 85% / B 15%",
)


def _unique_keep_order(items):
    out = []
    seen = set()
    for item in items:
        if item in seen:
            continue
        seen.add(item)
        out.append(item)
    return out


class TabCalidad(ttk.Frame):
    def __init__(self, master, alloys_model):
        super().__init__(master, padding=8)
        self.alloys = alloys_model
        self.reports = []
        self._selected_index = None
        self._item_to_index = {}
        self._updating_micro = False
        self._last_micro_field = None
        self._draft_job = None
        self._suspend_autosave = False
        self._confirmed_snapshot = None
        self._draft_fields = set()
        self._selected_group = None
        self._group_baselines = {}
        self.var_show_archived = tk.BooleanVar(value=False)
        self._catalog_dirty = False
        self._final_materials = {}
        self._base_to_materials = {}
        self._material_to_bases = {}

        self._reload_final_material_catalog()

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Informes de calidad").pack(side="left")
        ttk.Checkbutton(top, text="Mostrar archivados", variable=self.var_show_archived, command=self.refresh).pack(side="right", padx=(0, 8))
        ttk.Button(top, text="Refrescar", command=self.refresh).pack(side="right")

        help_box = ttk.LabelFrame(self, text="Bases y materiales", padding=8)
        help_box.pack(fill="x", pady=(0, 8))
        self.lbl_bases_help = ttk.Label(
            help_box,
            text=self._bases_help_text(),
            justify="left",
        )
        self.lbl_bases_help.pack(anchor="w")

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=2)

        form = ttk.LabelFrame(left, text="Carga de informe", padding=8)
        form.pack(fill="both", expand=True)

        self.var_fecha = tk.StringVar(value=datetime.now().strftime("%Y-%m-%d"))
        self.var_base = tk.StringVar(value=(self._base_codes()[0] if self._base_codes() else ""))
        self.var_material = tk.StringVar()
        self.var_lote = tk.StringVar()
        self.var_informe = tk.StringVar()
        self.var_ce_final = tk.StringVar()
        self.var_c_final = tk.StringVar()
        self.var_si_final = tk.StringVar()

        self._init_highlight_styles()

        ttk.Label(form, text="Fecha").grid(row=0, column=0, sticky="w", pady=2)
        self.ent_fecha = ttk.Entry(form, textvariable=self.var_fecha, width=18)
        self.ent_fecha.grid(row=0, column=1, sticky="ew", pady=2)

        ttk.Label(form, text="Base").grid(row=1, column=0, sticky="w", pady=2)
        self.cb_base = ttk.Combobox(form, textvariable=self.var_base, values=tuple(self._base_codes()), state="readonly", width=16)
        self.cb_base.grid(row=1, column=1, sticky="ew", pady=2)
        self.cb_base.bind("<<ComboboxSelected>>", lambda e: self._sync_materials())

        ttk.Label(form, text="Material").grid(row=2, column=0, sticky="w", pady=2)
        self.cb_material = ttk.Combobox(form, textvariable=self.var_material, state="readonly", width=16)
        self.cb_material.grid(row=2, column=1, sticky="ew", pady=2)
        self.cb_material.bind("<<ComboboxSelected>>", lambda e: self._apply_material_defaults())

        ttk.Label(form, text="Lote / colada").grid(row=3, column=0, sticky="w", pady=2)
        self.ent_lote = ttk.Entry(form, textvariable=self.var_lote, width=18)
        self.ent_lote.grid(row=3, column=1, sticky="ew", pady=2)

        ttk.Label(form, text="Informe").grid(row=4, column=0, sticky="w", pady=2)
        self.ent_informe = ttk.Entry(form, textvariable=self.var_informe, width=18)
        self.ent_informe.grid(row=4, column=1, sticky="ew", pady=2)

        finals = ttk.LabelFrame(form, text="Valores finales", padding=6)
        finals.grid(row=5, column=0, columnspan=2, sticky="ew", pady=(8, 6))
        finals.columnconfigure(1, weight=1)
        finals.columnconfigure(3, weight=1)

        ttk.Label(finals, text="CE final").grid(row=0, column=0, sticky="w", pady=2)
        self.ent_ce_final = ttk.Entry(finals, textvariable=self.var_ce_final, width=14)
        self.ent_ce_final.grid(row=0, column=1, sticky="ew", pady=2, padx=(0, 8))
        ttk.Label(finals, text="C final").grid(row=0, column=2, sticky="w", pady=2)
        self.ent_c_final = ttk.Entry(finals, textvariable=self.var_c_final, width=14)
        self.ent_c_final.grid(row=0, column=3, sticky="ew", pady=2)
        ttk.Label(finals, text="Si final").grid(row=1, column=0, sticky="w", pady=2)
        self.ent_si_final = ttk.Entry(finals, textvariable=self.var_si_final, width=14)
        self.ent_si_final.grid(row=1, column=1, sticky="ew", pady=2, padx=(0, 8))

        props = ttk.LabelFrame(form, text="Propiedades", padding=6)
        props.grid(row=6, column=0, columnspan=2, sticky="ew", pady=(8, 6))
        props.columnconfigure(1, weight=1)
        props.columnconfigure(3, weight=1)

        self.var_traccion = tk.StringVar()
        self.var_seccion = tk.StringVar()
        self.var_dureza = tk.StringVar()
        self.var_tam_grafito = tk.StringVar()
        self.var_morfologia = tk.StringVar()
        self.var_tipo_grafito = tk.StringVar()
        self.var_conteo_nodulos = tk.StringVar()
        self.var_pct_nod = tk.StringVar()
        self.var_alargamiento = tk.StringVar()
        self.var_perlita = tk.StringVar()
        self.var_ferrita = tk.StringVar()
        self.var_cementita = tk.StringVar(value="0")
        self.var_matriz = tk.StringVar()

        ttk.Label(props, text="Traccion (kg/mm2)").grid(row=0, column=0, sticky="w", pady=2)
        self.ent_traccion = ttk.Entry(props, textvariable=self.var_traccion, width=14)
        self.ent_traccion.grid(row=0, column=1, sticky="ew", pady=2, padx=(0, 8))
        ttk.Label(props, text="Seccion muestra").grid(row=0, column=2, sticky="w", pady=2)
        self.cb_seccion = ttk.Combobox(props, textvariable=self.var_seccion, state="readonly", width=14)
        self.cb_seccion.grid(row=0, column=3, sticky="ew", pady=2)

        ttk.Label(props, text="Dureza").grid(row=1, column=0, sticky="w", pady=2)
        self.ent_dureza = ttk.Entry(props, textvariable=self.var_dureza, width=14)
        self.ent_dureza.grid(row=1, column=1, sticky="ew", pady=2, padx=(0, 8))
        ttk.Label(props, text="Tam grafito").grid(row=1, column=2, sticky="w", pady=2)
        self.ent_tam_grafito = ttk.Entry(props, textvariable=self.var_tam_grafito, width=14)
        self.ent_tam_grafito.grid(row=1, column=3, sticky="ew", pady=2)
        ttk.Label(props, text="Morfologia").grid(row=2, column=0, sticky="w", pady=2)
        self.ent_morfologia = ttk.Entry(props, textvariable=self.var_morfologia, width=14, state="readonly")
        self.ent_morfologia.grid(row=2, column=1, sticky="ew", pady=2, padx=(0, 8))

        self.lbl_tipo_grafito = ttk.Label(props, text="Tipo grafito")
        self.lbl_tipo_grafito.grid(row=2, column=2, sticky="w", pady=2)
        self.ent_tipo_grafito = ttk.Combobox(props, textvariable=self.var_tipo_grafito, values=GRAPHITE_TYPE_OPTIONS, state="readonly", width=14)
        self.ent_tipo_grafito.grid(row=2, column=3, sticky="ew", pady=2, padx=(0, 8))
        self.lbl_conteo_nodulos = ttk.Label(props, text="Conteo nodulos")
        self.lbl_conteo_nodulos.grid(row=3, column=2, sticky="w", pady=2)
        self.ent_conteo_nodulos = ttk.Entry(props, textvariable=self.var_conteo_nodulos, width=14)
        self.ent_conteo_nodulos.grid(row=3, column=3, sticky="ew", pady=2)

        self.lbl_pct_nod = ttk.Label(props, text="% nodularizacion")
        self.lbl_pct_nod.grid(row=3, column=0, sticky="w", pady=2)
        self.ent_pct_nod = ttk.Entry(props, textvariable=self.var_pct_nod, width=14)
        self.ent_pct_nod.grid(row=3, column=1, sticky="ew", pady=2, padx=(0, 8))
        ttk.Label(props, text="Perlita %").grid(row=4, column=2, sticky="w", pady=2)
        self.ent_perlita = ttk.Entry(props, textvariable=self.var_perlita, width=14)
        self.ent_perlita.grid(row=4, column=3, sticky="ew", pady=2)

        ttk.Label(props, text="Ferrita %").grid(row=4, column=0, sticky="w", pady=2)
        self.ent_ferrita = ttk.Entry(props, textvariable=self.var_ferrita, width=14)
        self.ent_ferrita.grid(row=4, column=1, sticky="ew", pady=2, padx=(0, 8))
        ttk.Label(props, text="Matriz prevalente").grid(row=5, column=2, sticky="w", pady=2)
        self.ent_matriz = ttk.Entry(props, textvariable=self.var_matriz, width=14, state="readonly")
        self.ent_matriz.grid(row=5, column=3, sticky="ew", pady=2)
        self.lbl_alargamiento = ttk.Label(props, text="Alargamiento (%)")
        self.lbl_alargamiento.grid(row=5, column=0, sticky="w", pady=2)
        self.ent_alargamiento = ttk.Entry(props, textvariable=self.var_alargamiento, width=14)
        self.ent_alargamiento.grid(row=5, column=1, sticky="ew", pady=2, padx=(0, 8))
        ttk.Label(props, text="Cementita %").grid(row=6, column=0, sticky="w", pady=2)
        self.ent_cementita = ttk.Entry(props, textvariable=self.var_cementita, width=14)
        self.ent_cementita.grid(row=6, column=1, sticky="ew", pady=2, padx=(0, 8))

        ttk.Label(form, text="Datos / observaciones").grid(row=7, column=0, columnspan=2, sticky="w", pady=(8, 2))
        self.txt_data = tk.Text(
            form,
            height=14,
            wrap="word",
            bg=self._default_input_bg(),
            fg=self._default_input_fg(),
            insertbackground=self._default_input_fg(),
        )
        self.txt_data.grid(row=8, column=0, columnspan=2, sticky="nsew", pady=(0, 8))

        btns = ttk.Frame(form)
        btns.grid(row=9, column=0, columnspan=2, sticky="ew")
        ttk.Button(btns, text="Guardar", command=self._save_report).pack(side="left")
        ttk.Button(btns, text="Cancelar", command=self._cancel_draft).pack(side="left", padx=6)
        ttk.Button(btns, text="Agregar", command=self._add_report_to_selected_group).pack(side="left", padx=6)
        ttk.Button(btns, text="Imprimir", command=self._print_groups).pack(side="left", padx=6)
        ttk.Button(btns, text="Eliminar grupo", command=self._delete_selected_group).pack(side="right")
        ttk.Button(btns, text="Eliminar", command=self._delete_selected).pack(side="right")

        form.columnconfigure(1, weight=1)
        form.rowconfigure(8, weight=1)

        table_box = ttk.LabelFrame(right, text="Informes cargados", padding=6)
        table_box.pack(fill="both", expand=True)

        cols = ("fecha", "tipo", "informe")
        self.tree = ttk.Treeview(table_box, columns=cols, show="tree headings", height=20)
        self.tree.heading("#0", text="Horno base / material")
        self.tree.column("#0", width=220, anchor="w")
        for cid, title, width in (
            ("fecha", "Fecha", 110),
            ("tipo", "Tipo", 100),
            ("informe", "Informe", 240),
        ):
            self.tree.heading(cid, text=title)
            self.tree.column(cid, width=width, anchor="w")
        self.tree.pack(fill="both", expand=True)
        self.tree.bind("<<TreeviewSelect>>", lambda e: self._load_selected())
        try:
            self.tree.tag_configure("draft", background=self._highlight_bg(), foreground=self._highlight_fg())
        except Exception:
            pass

        self.var_base.trace_add("write", lambda *_: self._sync_family_fields())
        self.var_perlita.trace_add("write", lambda *_: self._update_microstructure())
        self.var_ferrita.trace_add("write", lambda *_: self._update_microstructure())
        self.var_cementita.trace_add("write", lambda *_: self._update_microstructure())
        self.ent_perlita.bind("<FocusIn>", lambda e: self._remember_micro_field("perlita"))
        self.ent_ferrita.bind("<FocusIn>", lambda e: self._remember_micro_field("ferrita"))
        self.ent_cementita.bind("<FocusIn>", lambda e: self._remember_micro_field("cementita"))
        self.txt_data.bind("<<Modified>>", self._on_text_modified)

        self.lbl_draft = tk.Label(form, text="", anchor="w", bg="#6b5500", fg="white")
        self.lbl_draft.grid(row=10, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.lbl_draft.grid_remove()

        self.lbl_mode = tk.Label(form, text="", anchor="w", bg="#5a2f00", fg="white")
        self.lbl_mode.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        self.lbl_mode.grid_remove()

        for var in (
            self.var_fecha, self.var_base, self.var_material, self.var_lote, self.var_informe,
            self.var_ce_final, self.var_c_final, self.var_si_final,
            self.var_traccion, self.var_seccion, self.var_dureza, self.var_tam_grafito,
            self.var_morfologia, self.var_tipo_grafito, self.var_conteo_nodulos,
            self.var_pct_nod, self.var_alargamiento, self.var_perlita,
            self.var_ferrita, self.var_cementita,
        ):
            var.trace_add("write", lambda *_: self._schedule_draft_save())

        self._sync_materials()
        self._sync_family_fields()
        self._field_widgets = {
            "fecha": self.ent_fecha,
            "base": self.cb_base,
            "material": self.cb_material,
            "lote": self.ent_lote,
            "informe": self.ent_informe,
            "ce_final": self.ent_ce_final,
            "c_final": self.ent_c_final,
            "si_final": self.ent_si_final,
            "traccion": self.ent_traccion,
            "seccion": self.cb_seccion,
            "dureza": self.ent_dureza,
            "tam_grafito": self.ent_tam_grafito,
            "morfologia": self.ent_morfologia,
            "tipo_grafito": self.ent_tipo_grafito,
            "conteo_nodulos": self.ent_conteo_nodulos,
            "pct_nodularizacion": self.ent_pct_nod,
            "alargamiento": self.ent_alargamiento,
            "perlita": self.ent_perlita,
            "ferrita": self.ent_ferrita,
            "cementita": self.ent_cementita,
            "matriz": self.ent_matriz,
        }
        self.refresh()

    def _catalog_final_entry(self, alloy):
        meta = alloy.get("calidad_meta", {}) if isinstance(alloy, dict) else {}
        if not isinstance(meta, dict) or not meta.get("es_material_final"):
            return None
        code = str(meta.get("codigo") or alloy.get("nombre", "")).strip()
        if not code:
            return None
        bases = [str(b).strip() for b in (meta.get("bases") or []) if str(b).strip()]
        family = str(meta.get("family") or "").strip()
        defaults = meta.get("defaults", {}) if isinstance(meta.get("defaults", {}), dict) else {}
        section_options = [str(opt).strip() for opt in (meta.get("section_options") or []) if str(opt).strip()]
        return {
            "code": code,
            "name": alloy.get("nombre", code),
            "bases": _unique_keep_order(bases),
            "family": family,
            "defaults": dict(defaults),
            "section_options": section_options or list(DEFAULT_SECTION_OPTIONS),
            "alloy": alloy,
        }

    def _reload_final_material_catalog(self):
        self._final_materials = {}
        self._base_to_materials = {}
        self._material_to_bases = {}
        for alloy in self.alloys:
            entry = self._catalog_final_entry(alloy)
            if not entry:
                continue
            code = entry["code"]
            self._final_materials[code] = entry
            for base in entry["bases"]:
                self._base_to_materials.setdefault(base, []).append(code)
                self._material_to_bases.setdefault(code, []).append(base)
        for base, mats in list(self._base_to_materials.items()):
            self._base_to_materials[base] = sorted(_unique_keep_order(mats), key=lambda val: (int(val) if str(val).isdigit() else 9999, str(val)))
        for mat, bases in list(self._material_to_bases.items()):
            self._material_to_bases[mat] = sorted(_unique_keep_order(bases), key=lambda val: (int(val) if str(val).isdigit() else 9999, str(val)))

    def refresh_catalog(self):
        self._reload_final_material_catalog()
        try:
            self.lbl_bases_help.configure(text=self._bases_help_text())
        except Exception:
            pass
        try:
            self.cb_base.configure(values=tuple(self._base_codes()))
        except Exception:
            pass
        current_base = self.var_base.get().strip()
        if current_base not in self._base_to_materials:
            self.var_base.set(self._base_codes()[0] if self._base_codes() else "")
        self._sync_materials()
        self._sync_family_fields()

    def _base_codes(self):
        return sorted(self._base_to_materials.keys(), key=lambda val: (int(val) if str(val).isdigit() else 9999, str(val)))

    def _materials_for_base(self, base):
        return list(self._base_to_materials.get((base or "").strip(), []))

    def _bases_help_text(self):
        parts = []
        for base in self._base_codes():
            mats = ", ".join(self._materials_for_base(base))
            parts.append(f"base {base} -> {mats}")
        return " | ".join(parts) if parts else "No hay materiales finales configurados en el catálogo."

    def _default_input_bg(self):
        top = self.winfo_toplevel()
        return getattr(top, "_input_bg", ACCENT)

    def _default_input_fg(self):
        top = self.winfo_toplevel()
        return getattr(top, "_input_fg", FG)

    def _highlight_bg(self):
        top = self.winfo_toplevel()
        return getattr(top, "_highlight_bg", "#fff2a8")

    def _highlight_fg(self):
        top = self.winfo_toplevel()
        return getattr(top, "_highlight_fg", "black")

    def _parse_optional_float(self, value):
        raw = (value or "").strip().replace(",", ".")
        if not raw:
            return None
        try:
            return float(raw)
        except Exception:
            return None

    def _init_highlight_styles(self):
        try:
            style = ttk.Style(self)
            bg = self._highlight_bg()
            fg = self._highlight_fg()
            style.configure("QualityChanged.TEntry", fieldbackground=bg, foreground=fg)
            style.map("QualityChanged.TEntry",
                      fieldbackground=[("readonly", bg), ("!disabled", bg)],
                      foreground=[("readonly", fg), ("!disabled", fg)])
            style.configure("QualityChanged.TCombobox", fieldbackground=bg, background=bg, foreground=fg, arrowcolor=fg)
            style.map("QualityChanged.TCombobox",
                      fieldbackground=[("readonly", bg), ("!disabled", bg)],
                      foreground=[("readonly", fg), ("!disabled", fg)])
        except Exception:
            pass

    def _normalize_report_payload(self, report):
        clean = dict(report or {})
        clean.pop("_draft_pending", None)
        clean.pop("_draft_base", None)
        clean.pop("_draft_fields", None)
        return clean

    def _baseline_from_report(self, report):
        if report.get("_draft_pending") and isinstance(report.get("_draft_base"), dict):
            return self._normalize_report_payload(report.get("_draft_base"))
        return self._normalize_report_payload(report)

    def _current_form_payload(self):
        return self._normalize_report_payload(self._build_report_from_form(pending=False))

    def _group_report_indexes(self, base, lote):
        return [i for i, report in enumerate(self.reports) if report.get("base", "") == base and report.get("lote", "") == lote]

    def _group_materials(self, base, lote):
        return [self.reports[i].get("material", "") for i in self._group_report_indexes(base, lote)]

    def _group_info_from_item(self, item_id):
        if item_id.startswith("report:"):
            parent = self.tree.parent(item_id)
            if not parent:
                return None
            item_id = parent
        if not item_id.startswith("group:"):
            return None
        _, base, lote = item_id.split(":", 2)
        return {"item_id": item_id, "base": base, "lote": lote}

    def _informe_group_base(self, report):
        text = str(report.get("informe", "") or "")
        return re.sub(r"\s*-\s*mat\s+\S+\s*$", "", text).strip()

    def _set_mode_ui(self):
        if self._selected_group is not None and self._selected_index is None:
            mats = ", ".join(sorted(m for m in self._group_materials(self._selected_group["base"], self._selected_group["lote"]) if m))
            self.lbl_mode.config(
                text=f"Modo grupo: estas editando TODO el grupo Base {self._selected_group['base']} / {self._selected_group['lote']}. "
                     f"Los cambios se aplican a todos los materiales: {mats}"
            )
            self.lbl_mode.grid()
            try:
                self.cb_material.configure(state="disabled")
            except Exception:
                pass
        else:
            self.lbl_mode.grid_remove()
            try:
                self.cb_material.configure(state="readonly")
            except Exception:
                pass

    def _apply_group_form_to_report(self, report):
        updated = dict(report)
        changed = self._group_changed_values()
        material = updated.get("material", "")

        for key, value in changed.items():
            if key == "informe":
                updated["informe"] = f"{value} - mat {material}" if value else updated.get("informe", "")
            else:
                updated[key] = value
        return updated

    def _group_form_payload(self):
        return {
            "fecha": self.var_fecha.get().strip(),
            "base": self._selected_group["base"] if self._selected_group else self.var_base.get().strip(),
            "lote": self.var_lote.get().strip(),
            "informe": self.var_informe.get().strip(),
            "ce_final": self.var_ce_final.get().strip(),
            "c_final": self.var_c_final.get().strip(),
            "si_final": self.var_si_final.get().strip(),
            "datos": self.txt_data.get("1.0", tk.END).strip(),
            "traccion": self.var_traccion.get().strip(),
            "seccion": self.var_seccion.get().strip(),
            "dureza": self.var_dureza.get().strip(),
            "tam_grafito": self.var_tam_grafito.get().strip(),
            "morfologia": self.var_morfologia.get().strip(),
            "tipo_grafito": self.var_tipo_grafito.get().strip(),
            "conteo_nodulos": self.var_conteo_nodulos.get().strip(),
            "pct_nodularizacion": self.var_pct_nod.get().strip(),
            "alargamiento": self.var_alargamiento.get().strip(),
            "perlita": self.var_perlita.get().strip(),
            "ferrita": self.var_ferrita.get().strip(),
            "cementita": self.var_cementita.get().strip(),
            "matriz": self.var_matriz.get().strip(),
        }

    def _group_changed_values(self):
        current = self._group_form_payload()
        base = self._confirmed_snapshot or {}
        changed = {}
        for key, value in current.items():
            if str(base.get(key, "") or "") != str(value or ""):
                changed[key] = value
        self._draft_fields = set(changed.keys())
        return changed

    def _load_group_selection(self, base, lote, item_id=None):
        indexes = self._group_report_indexes(base, lote)
        if not indexes:
            return
        first = self.reports[indexes[0]]
        self._suspend_autosave = True
        self._selected_index = None
        self._selected_group = {"base": base, "lote": lote, "item_id": item_id}
        self.var_fecha.set(first.get("fecha", ""))
        self.var_base.set(base)
        self._sync_materials()
        self.var_material.set(first.get("material", ""))
        self.var_seccion.set(first.get("seccion", ""))
        self._sync_section_options()
        self.var_lote.set(lote)
        self.var_informe.set(self._informe_group_base(first))
        self.var_ce_final.set(first.get("ce_final", ""))
        self.var_c_final.set(first.get("c_final", ""))
        self.var_si_final.set(first.get("si_final", ""))
        self.var_traccion.set(first.get("traccion", ""))
        self.var_dureza.set(first.get("dureza", ""))
        self.var_tam_grafito.set(first.get("tam_grafito", ""))
        self.var_morfologia.set(first.get("morfologia", ""))
        self.var_tipo_grafito.set(first.get("tipo_grafito", ""))
        self.var_conteo_nodulos.set(first.get("conteo_nodulos", ""))
        self.var_pct_nod.set(first.get("pct_nodularizacion", ""))
        self.var_alargamiento.set(first.get("alargamiento", ""))
        self.var_perlita.set(first.get("perlita", ""))
        self.var_ferrita.set(first.get("ferrita", ""))
        self.var_cementita.set(first.get("cementita", ""))
        self.var_matriz.set(first.get("matriz", ""))
        self._sync_family_fields()
        self._update_microstructure()
        self.txt_data.delete("1.0", tk.END)
        self.txt_data.insert("1.0", first.get("datos", ""))
        try:
            self.txt_data.edit_modified(False)
        except Exception:
            pass
        self._confirmed_snapshot = self._normalize_report_payload(first)
        self._draft_fields = set()
        self._group_baselines = {i: self._baseline_from_report(self.reports[i]) for i in indexes}
        self._suspend_autosave = False
        self._set_mode_ui()
        self._set_draft_ui(any(self.reports[i].get("_draft_pending") for i in indexes))

    def _focused_field_key(self):
        focus_widget = self.focus_get()
        for key, widget in getattr(self, "_field_widgets", {}).items():
            if widget == focus_widget:
                return key
        return None

    def _apply_field_highlights(self):
        for key, widget in getattr(self, "_field_widgets", {}).items():
            changed = self._selected_index is not None and key in self._draft_fields
            try:
                if isinstance(widget, ttk.Combobox):
                    widget.configure(style="QualityChanged.TCombobox" if changed else "TCombobox")
                else:
                    widget.configure(style="QualityChanged.TEntry" if changed else "TEntry")
            except Exception:
                pass
        try:
            text_changed = self._selected_index is not None and "datos" in self._draft_fields
            self.txt_data.configure(
                bg=self._highlight_bg() if text_changed else self._default_input_bg(),
                fg=self._highlight_fg() if text_changed else self._default_input_fg(),
                insertbackground=self._highlight_fg() if text_changed else self._default_input_fg(),
            )
        except Exception:
            pass

    def _material_defaults(self, material):
        return dict(self._final_materials.get((material or "").strip(), {}).get("defaults", {}))

    def _section_options_for_material(self, material):
        mat = (material or "").strip()
        entry = self._final_materials.get(mat, {})
        return list(entry.get("section_options", DEFAULT_SECTION_OPTIONS))

    def _default_section_for_material(self, material):
        options = self._section_options_for_material(material)
        if not options:
            return ""
        return options[1] if len(options) > 1 else options[0]

    def _sync_section_options(self):
        options = self._section_options_for_material(self.var_material.get())
        self.cb_seccion["values"] = options
        current = self.var_seccion.get().strip()
        if current not in options:
            self.var_seccion.set(self._default_section_for_material(self.var_material.get()))

    def _apply_material_defaults(self, force=False):
        defaults = self._material_defaults(self.var_material.get())
        self._sync_section_options()
        if force or not self.var_traccion.get().strip():
            self.var_traccion.set(defaults.get("traccion", ""))
        if force or not self.var_seccion.get().strip():
            self.var_seccion.set(defaults.get("seccion", self._default_section_for_material(self.var_material.get())))
        if force or not self.var_dureza.get().strip():
            self.var_dureza.set(defaults.get("dureza", ""))
        if force or not self.var_alargamiento.get().strip():
            self.var_alargamiento.set(defaults.get("alargamiento", ""))
        if force or not self.var_conteo_nodulos.get().strip():
            self.var_conteo_nodulos.set(defaults.get("conteo_nodulos", ""))
        if force or not self.var_pct_nod.get().strip():
            self.var_pct_nod.set(defaults.get("pct_nodularizacion", ""))
        if force or not self.var_tam_grafito.get().strip():
            self.var_tam_grafito.set(defaults.get("tam_grafito", ""))
        if force or not self.var_morfologia.get().strip():
            self.var_morfologia.set(defaults.get("morfologia", ""))
        if force or not self.var_tipo_grafito.get().strip():
            self.var_tipo_grafito.set(defaults.get("tipo_grafito", ""))
        if force or not self.var_perlita.get().strip():
            self.var_perlita.set(defaults.get("perlita", ""))
        if force or not self.var_ferrita.get().strip():
            self.var_ferrita.set(defaults.get("ferrita", ""))
        if force or not self.var_cementita.get().strip():
            self.var_cementita.set(defaults.get("cementita", "0"))
        self._update_microstructure()

    def _family_for_material(self, material):
        return str(self._final_materials.get((material or "").strip(), {}).get("family", "")).strip()

    def _family_for_report(self, report):
        if not isinstance(report, dict):
            return ""
        family = str(report.get("family", "")).strip()
        if family:
            return family
        return self._family_for_material(report.get("material", ""))

    def _family_for_reports(self, reports):
        families = _unique_keep_order(self._family_for_report(report) for report in reports if self._family_for_report(report))
        if not families:
            return ""
        if len(families) == 1:
            return families[0]
        return "Mixto"

    def _remember_micro_field(self, field_name):
        self._last_micro_field = field_name

    def _on_text_modified(self, _event=None):
        try:
            if self.txt_data.edit_modified():
                self.txt_data.edit_modified(False)
                self._draft_fields.add("datos")
                self._schedule_draft_save()
        except Exception:
            pass

    def _schedule_draft_save(self):
        if self._suspend_autosave or (self._selected_index is None and self._selected_group is None):
            return
        field_key = self._focused_field_key()
        if field_key:
            self._draft_fields.add(field_key)
        try:
            if self._draft_job is not None:
                self.after_cancel(self._draft_job)
        except Exception:
            pass
        self._draft_job = self.after(350, self._autosave_draft)

    def _set_draft_ui(self, pending):
        if pending:
            self.lbl_draft.config(text="Cambios autosalvados sin confirmar. Toca Guardar para cerrar el borrador.")
            self.lbl_draft.grid()
        else:
            self.lbl_draft.grid_remove()
        self._mark_selected_tree_draft(pending)
        self._apply_field_highlights()

    def _mark_selected_tree_draft(self, pending):
        if self._selected_group is not None and self._selected_index is None:
            target_iid = self._selected_group.get("item_id")
            if target_iid:
                try:
                    self.tree.item(target_iid, tags=("draft",) if pending else ())
                except Exception:
                    pass
            return
        if self._selected_index is None:
            return
        target_iid = None
        for iid, idx in self._item_to_index.items():
            if idx == self._selected_index:
                target_iid = iid
                break
        if target_iid:
            try:
                self.tree.item(target_iid, tags=("draft",) if pending else ())
            except Exception:
                pass

    def _build_report_from_form(self, pending=False):
        return {
            "fecha": self.var_fecha.get().strip(),
            "base": self.var_base.get().strip(),
            "material": self.var_material.get().strip(),
            "family": self._family_for_material(self.var_material.get().strip()),
            "lote": self.var_lote.get().strip(),
            "informe": self.var_informe.get().strip(),
            "ce_final": self.var_ce_final.get().strip(),
            "c_final": self.var_c_final.get().strip(),
            "si_final": self.var_si_final.get().strip(),
            "datos": self.txt_data.get("1.0", tk.END).strip(),
            "traccion": self.var_traccion.get().strip(),
            "seccion": self.var_seccion.get().strip(),
            "dureza": self.var_dureza.get().strip(),
            "tam_grafito": self.var_tam_grafito.get().strip(),
            "morfologia": self.var_morfologia.get().strip(),
            "tipo_grafito": self.var_tipo_grafito.get().strip(),
            "conteo_nodulos": self.var_conteo_nodulos.get().strip(),
            "pct_nodularizacion": self.var_pct_nod.get().strip(),
            "alargamiento": self.var_alargamiento.get().strip(),
            "perlita": self.var_perlita.get().strip(),
            "ferrita": self.var_ferrita.get().strip(),
            "cementita": self.var_cementita.get().strip(),
            "matriz": self.var_matriz.get().strip(),
            "_draft_pending": bool(pending),
            "_draft_fields": sorted(self._draft_fields) if pending else [],
        }

    def _autosave_draft(self):
        self._draft_job = None
        if self._suspend_autosave:
            return
        if self._selected_group is not None and self._selected_index is None:
            indexes = self._group_report_indexes(self._selected_group["base"], self._selected_group["lote"])
            if not indexes:
                return
            changed = self._group_changed_values()
            if not changed:
                had_pending = False
                for idx in indexes:
                    report = self.reports[idx]
                    base_report = report.get("_draft_base") if report.get("_draft_pending") and isinstance(report.get("_draft_base"), dict) else None
                    if base_report:
                        restored = dict(base_report)
                        restored["_draft_pending"] = False
                        restored["_draft_base"] = None
                        restored["_draft_fields"] = []
                        self.reports[idx] = restored
                        had_pending = True
                if had_pending:
                    save_quality_reports(self.reports)
                    self.refresh()
                    self._load_group_selection(self._selected_group["base"], self._selected_group["lote"], item_id=self._selected_group.get("item_id"))
                self._set_draft_ui(False)
                return
            for idx in indexes:
                current_report = self.reports[idx]
                base_report = current_report.get("_draft_base") if current_report.get("_draft_pending") else self._normalize_report_payload(current_report)
                draft = self._apply_group_form_to_report(current_report)
                draft["_draft_pending"] = True
                draft["_draft_base"] = base_report
                draft["_draft_fields"] = sorted(changed.keys())
                self.reports[idx] = draft
            self._group_baselines = {idx: self._baseline_from_report(self.reports[idx]) for idx in indexes}
            self._confirmed_snapshot = self._group_baselines.get(indexes[0], {})
            save_quality_reports(self.reports)
            self._set_draft_ui(True)
            return
        if self._selected_index is None:
            return
        if self._selected_index < 0 or self._selected_index >= len(self.reports):
            return
        current_report = self.reports[self._selected_index]
        base_report = current_report.get("_draft_base") if current_report.get("_draft_pending") else self._normalize_report_payload(current_report)
        draft = self._build_report_from_form(pending=True)
        draft["_draft_base"] = base_report
        self.reports[self._selected_index] = draft
        self._confirmed_snapshot = self._normalize_report_payload(base_report)
        save_quality_reports(self.reports)
        self._set_draft_ui(True)

    def _cancel_draft(self):
        if self._selected_group is not None and self._selected_index is None:
            indexes = self._group_report_indexes(self._selected_group["base"], self._selected_group["lote"])
            for idx in indexes:
                report = self.reports[idx]
                base_report = report.get("_draft_base") if report.get("_draft_pending") and isinstance(report.get("_draft_base"), dict) else None
                if base_report:
                    restored = dict(base_report)
                    restored["_draft_pending"] = False
                    restored["_draft_base"] = None
                    restored["_draft_fields"] = []
                    self.reports[idx] = restored
            save_quality_reports(self.reports)
            self.refresh()
            self._draft_fields = set()
            self._load_group_selection(self._selected_group["base"], self._selected_group["lote"], item_id=self._selected_group.get("item_id"))
            return
        if self._selected_index is None:
            return
        if self._selected_index < 0 or self._selected_index >= len(self.reports):
            return
        report = self.reports[self._selected_index]
        base_report = report.get("_draft_base") if report.get("_draft_pending") and isinstance(report.get("_draft_base"), dict) else None
        if not base_report:
            self._load_selected()
            return
        restored = dict(base_report)
        restored["_draft_pending"] = False
        restored["_draft_base"] = None
        restored["_draft_fields"] = []
        idx = self._selected_index
        self.reports[idx] = restored
        save_quality_reports(self.reports)
        self.refresh()
        target = f"report:{idx}"
        if target in self.tree.get_children() or any(target in self.tree.get_children(parent) for parent in self.tree.get_children()):
            try:
                self.tree.selection_set(target)
            except Exception:
                pass
        self._load_selected()

    def _sync_family_fields(self):
        family = self._family_for_material(self.var_material.get())
        gris = family == "Gris"
        nod = family == "Nodular"
        if gris:
            self.lbl_tipo_grafito.grid()
            self.ent_tipo_grafito.grid()
            self.ent_tipo_grafito.configure(state="normal")
        else:
            self.lbl_tipo_grafito.grid_remove()
            self.ent_tipo_grafito.grid_remove()
        if nod:
            self.lbl_conteo_nodulos.grid()
            self.ent_conteo_nodulos.grid()
            self.lbl_pct_nod.grid()
            self.ent_pct_nod.grid()
            self.ent_conteo_nodulos.configure(state="normal")
            self.ent_pct_nod.configure(state="normal")
        else:
            self.lbl_conteo_nodulos.grid_remove()
            self.ent_conteo_nodulos.grid_remove()
            self.lbl_pct_nod.grid_remove()
            self.ent_pct_nod.grid_remove()
        if nod:
            self.lbl_alargamiento.grid()
            self.ent_alargamiento.grid()
            self.ent_alargamiento.configure(state="normal")
        else:
            self.lbl_alargamiento.grid_remove()
            self.ent_alargamiento.grid_remove()
        if not gris:
            self.var_tipo_grafito.set("")
        if not nod:
            self.var_conteo_nodulos.set("")
            self.var_pct_nod.set("")
            self.var_alargamiento.set("")

    def _update_microstructure(self):
        if self._updating_micro:
            return
        self._updating_micro = True
        try:
            cementita = self._parse_optional_float(self.var_cementita.get())
            perlita = self._parse_optional_float(self.var_perlita.get())
            ferrita = self._parse_optional_float(self.var_ferrita.get())
            cementita = 0.0 if cementita is None else max(0.0, min(100.0, cementita))
            if self.var_cementita.get().strip():
                self.var_cementita.set(fmt(cementita, 2))

            restante = max(0.0, 100.0 - cementita)
            focus_widget = self.focus_get()
            field = self._last_micro_field
            if focus_widget == self.ent_perlita:
                field = "perlita"
            elif focus_widget == self.ent_ferrita:
                field = "ferrita"
            elif focus_widget == self.ent_cementita:
                field = "cementita"

            if field == "perlita" and perlita is not None:
                perlita = max(0.0, min(restante, perlita))
                ferrita = max(0.0, restante - perlita)
                self.var_perlita.set(fmt(perlita, 2))
                self.var_ferrita.set(fmt(ferrita, 2))
            elif field == "ferrita" and ferrita is not None:
                ferrita = max(0.0, min(restante, ferrita))
                perlita = max(0.0, restante - ferrita)
                self.var_ferrita.set(fmt(ferrita, 2))
                self.var_perlita.set(fmt(perlita, 2))
            elif field == "cementita":
                if perlita is not None:
                    perlita = max(0.0, min(restante, perlita))
                    ferrita = max(0.0, restante - perlita)
                    self.var_perlita.set(fmt(perlita, 2))
                    self.var_ferrita.set(fmt(ferrita, 2))
                elif ferrita is not None:
                    ferrita = max(0.0, min(restante, ferrita))
                    perlita = max(0.0, restante - ferrita)
                    self.var_ferrita.set(fmt(ferrita, 2))
                    self.var_perlita.set(fmt(perlita, 2))

            perlita = self._parse_optional_float(self.var_perlita.get())
            ferrita = self._parse_optional_float(self.var_ferrita.get())
            matriz = ""
            if perlita is not None and ferrita is not None and abs((perlita + ferrita + cementita) - 100.0) <= 1e-6:
                if perlita >= 100.0 - 1e-6:
                    matriz = "Perlitico"
                elif ferrita >= 100.0 - 1e-6:
                    matriz = "Ferritico"
                elif perlita >= ferrita:
                    matriz = "Perlita"
                else:
                    matriz = "Ferrita"
            self.var_matriz.set(matriz)
        finally:
            self._updating_micro = False

    def _extract_material_code(self, *texts):
        valid = set(self._material_to_bases.keys()) | set(self._base_to_materials.keys())
        for text in texts:
            raw = (text or "").strip()
            if not raw:
                continue
            if raw in valid:
                return raw
            lowered = raw.lower()
            explicit_patterns = [
                r"\bmaterial\s*[:\-]?\s*0*(\d+)\b",
                r"\bmat\s*[:\-]?\s*0*(\d+)\b",
                r"\bbase\s*[:\-]?\s*0*(\d+)\b",
            ]
            for pattern in explicit_patterns:
                match = re.search(pattern, lowered)
                if not match:
                    continue
                token = match.group(1)
                if token in valid:
                    return token
                compact = token.lstrip("0") or "0"
                if compact in valid:
                    return compact

            found = re.findall(r"\d+", raw)
            for token in found:
                if token in valid:
                    return token
                compact = token.lstrip("0") or "0"
                if compact in valid:
                    return compact
        return ""

    def _infer_base_for_material(self, material):
        bases = self._material_to_bases.get(material, [])
        if len(bases) == 1:
            return bases[0]
        if bases:
            return sorted(
                bases,
                key=lambda base: (-len(self._materials_for_base(base)), str(base))
            )[0]
        base_codes = self._base_codes()
        return base_codes[0] if base_codes else ""

    def _infer_base_material_from_session(self, session):
        ajuste_objectives = []
        for entry in session.get("ajustes", []) or []:
            obj = entry.get("objetivo", "")
            if obj:
                ajuste_objectives.append(obj)

        base_materials = []
        for text in ajuste_objectives:
            mat = self._extract_material_code(text)
            if mat in self._base_to_materials:
                base_materials.append(mat)
        base_materials = _unique_keep_order(base_materials)

        if not base_materials:
            raise ValueError("No se puede crear informe: el material no tiene ajustes validos.")

        union_materials = []
        for base in base_materials:
            union_materials.extend(self._materials_for_base(base))
        union_materials = _unique_keep_order(union_materials)

        if not union_materials:
            raise ValueError("No se puede crear informe: el material no tiene ajustes validos.")

        actual_base = next(
            (base for base, mats in self._base_to_materials.items() if list(mats) == union_materials),
            base_materials[0],
        )
        display_base = "-".join(base_materials)
        return {
            "actual_base": actual_base,
            "display_base": display_base,
            "base_materials": base_materials,
            "materials": union_materials,
            "material_inferido": base_materials[-1] if base_materials else "",
        }

    def _history_common_data(self, session):
        ajustes = session.get("ajustes", []) or []
        calculos = session.get("calculos", []) or []
        entry = ajustes[-1] if ajustes else (calculos[-1] if calculos else {})

        fecha_full = session.get("ended_at") or entry.get("fecha") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        objective = session.get("objetivo", "")
        colada = session.get("colada", "")
        base_info = self._infer_base_material_from_session(session)
        base = base_info["actual_base"]
        base_display = base_info["display_base"]
        material = base_info["material_inferido"]

        comp_fin = (entry.get("estimado") or {}).get("comp", {}) or {}
        ce_fin = entry.get("ce_estimado", "")

        lines = [
            f"Colada: {colada}",
            f"Objetivo: {objective}",
            f"Fecha cierre: {session.get('ended_at', '')}",
        ]
        if not material:
            lines.extend(["", "Revision manual:", "No se pudo inferir automaticamente el material/base desde la colada u objetivo."])

        family_names = _unique_keep_order(self._family_for_material(material) for material in base_info["materials"] if self._family_for_material(material))
        family = family_names[0] if len(family_names) == 1 else ("Mixto" if family_names else "")
        prefix = f"Informe calidad {family}" if family else "Informe calidad"
        return {
            "fecha": fecha_full[:10],
            "base": base,
            "base_display": base_display,
            "material_inferido": material,
            "material_base": base_info["base_materials"][0] if len(base_info["base_materials"]) == 1 else "",
            "default_materials": list(base_info["base_materials"]),
            "materials": list(base_info["materials"]),
            "lote": colada,
            "informe_base": f"{prefix} base {base_display} {colada}".strip(),
            "datos": "\n".join(lines).strip(),
            "ce_final": fmt(ce_fin, 2),
            "c_final": fmt(comp_fin.get('C', 0.0), 2),
            "si_final": fmt(comp_fin.get('Si', 0.0), 2),
            "family": family,
        }

    def get_material_options_for_session(self, session):
        data = self._history_common_data(session)
        base = data["base"]
        return {
            "base": base,
            "base_display": data.get("base_display", base),
            "family": data.get("family", ""),
            "materials": list(data.get("materials", self._materials_for_base(base))),
            "material_base": data.get("material_base", ""),
            "material_inferido": data.get("material_inferido", ""),
            "default_materials": list(data.get("default_materials", [])),
            "lote": data["lote"],
        }

    def load_from_history_session(self, session):
        self._selected_index = None
        data = self._history_common_data(session)
        base = data["base"]
        material = data["material_inferido"]
        self.var_fecha.set(data["fecha"])
        self.var_base.set(base)
        self._sync_materials()
        if material and material in self._materials_for_base(base):
            self.var_material.set(material)
        self._apply_material_defaults(force=True)
        self.var_lote.set(data["lote"])
        self.var_informe.set(data["informe_base"])
        self.var_ce_final.set(data["ce_final"])
        self.var_c_final.set(data["c_final"])
        self.var_si_final.set(data["si_final"])

        self.txt_data.delete("1.0", tk.END)
        self.txt_data.insert("1.0", data["datos"])
        try:
            self.tree.selection_remove(self.tree.selection())
        except Exception:
            pass

    def generate_reports_from_history_session(self, session, selected_materials=None):
        # Releer materiales finales desde el catálogo antes de generar,
        # por si el usuario acaba de cambiar defaults en Catálogo.
        self._reload_final_material_catalog()
        data = self._history_common_data(session)
        base = data["base"]
        materials = list(selected_materials) if selected_materials is not None else list(self._materials_for_base(base))
        if not materials:
            self.load_from_history_session(session)
            return 0

        updated = 0
        for material in materials:
            defaults = self._material_defaults(material)
            report = {
                "fecha": data["fecha"],
                "base": base,
                "base_display": data.get("base_display", base),
                "material": material,
                "family": self._family_for_material(material),
                "lote": data["lote"],
                "informe": f"{data['informe_base']} - mat {material}",
                "datos": data["datos"],
                "ce_final": data["ce_final"],
                "c_final": data["c_final"],
                "si_final": data["si_final"],
                "traccion": defaults.get("traccion", ""),
                "seccion": defaults.get("seccion", self._default_section_for_material(material)),
                "dureza": defaults.get("dureza", ""),
                "tam_grafito": defaults.get("tam_grafito", ""),
                "morfologia": defaults.get("morfologia", ""),
                "tipo_grafito": defaults.get("tipo_grafito", ""),
                "conteo_nodulos": defaults.get("conteo_nodulos", ""),
                "pct_nodularizacion": defaults.get("pct_nodularizacion", ""),
                "alargamiento": defaults.get("alargamiento", ""),
                "perlita": defaults.get("perlita", ""),
                "ferrita": defaults.get("ferrita", ""),
                "cementita": defaults.get("cementita", "0"),
                "matriz": "",
                "archived": False,
                "archived_at": "",
                "_draft_pending": False,
                "_draft_base": None,
                "_draft_fields": [],
            }
            existing_idx = next(
                (
                    i for i, it in enumerate(self.reports)
                    if it.get("base") == base and it.get("material") == material and it.get("lote") == data["lote"]
                ),
                None,
            )
            if existing_idx is None:
                self.reports.append(report)
            else:
                self.reports[existing_idx] = report
            updated += 1

        save_quality_reports(self.reports)
        self.refresh()

        first_idx = next(
            (
                i for i, it in enumerate(self.reports)
                if it.get("base") == base and it.get("material") == materials[0] and it.get("lote") == data["lote"]
            ),
            None,
        )
        if first_idx is not None:
            child_iid = f"report:{first_idx}"
            try:
                self.tree.selection_set(child_iid)
                self.tree.focus(child_iid)
            except Exception:
                pass
            self._load_selected()
        else:
            self._selected_index = None
            self.var_fecha.set(data["fecha"])
            self.var_base.set(base)
            self._sync_materials()
            self.var_material.set(materials[0])
            self._apply_material_defaults(force=True)
            self.var_lote.set(data["lote"])
            self.var_informe.set(f"{data['informe_base']} - mat {materials[0]}")
            self.var_ce_final.set(data["ce_final"])
            self.var_c_final.set(data["c_final"])
            self.var_si_final.set(data["si_final"])
            self.txt_data.delete("1.0", tk.END)
            self.txt_data.insert("1.0", data["datos"])
        return updated

    def _sync_materials(self):
        base = self.var_base.get().strip()
        materials = self._materials_for_base(base)
        self.cb_material["values"] = materials
        if self.var_material.get() not in materials:
            self.var_material.set(materials[0] if materials else "")
        self._sync_section_options()
        self._sync_family_fields()

    def _visible_reports(self):
        if self.var_show_archived.get():
            return list(enumerate(self.reports))
        return [(idx, report) for idx, report in enumerate(self.reports) if not report.get("archived")]

    def refresh(self):
        self.reports = load_quality_reports()
        self._item_to_index = {}
        for item in self.tree.get_children():
            self.tree.delete(item)
        groups = {}
        for idx, report in self._visible_reports():
            base = report.get("base", "")
            lote = report.get("lote", "")
            key = (base, lote)
            groups.setdefault(key, []).append((idx, report))

        def group_sort_key(item):
            (base, lote), reports = item
            fecha = ""
            if reports:
                fecha = reports[0][1].get("fecha", "")
            return (lote, base, fecha)

        for (base, lote), items in sorted(groups.items(), key=group_sort_key):
            family = self._family_for_reports([report for _, report in items])
            parent_iid = f"group:{base}:{lote}"
            base_display = items[0][1].get("base_display", base)
            title = f"Base {base_display} - {lote}".strip(" -")
            info = f"{len(items)} informe(s)"
            self.tree.insert(
                "",
                "end",
                iid=parent_iid,
                text=title,
                values=(items[0][1].get("fecha", ""), family, info),
                tags=("draft",) if any(r.get("_draft_pending") for _, r in items) else (),
                open=True,
            )
            for idx, report in sorted(items, key=lambda x: x[1].get("material", "")):
                child_iid = f"report:{idx}"
                self.tree.insert(
                    parent_iid,
                    "end",
                    iid=child_iid,
                    text=f"Material {report.get('material', '')}",
                    values=(
                        report.get("fecha", ""),
                        family,
                        report.get("informe", ""),
                    ),
                    tags=("draft",) if report.get("_draft_pending") else (),
                )
                self._item_to_index[child_iid] = idx

    def _clear_form(self):
        self._suspend_autosave = True
        self._selected_index = None
        self._selected_group = None
        self.var_fecha.set(datetime.now().strftime("%Y-%m-%d"))
        self.var_base.set(self._base_codes()[0] if self._base_codes() else "")
        self._sync_materials()
        self._apply_material_defaults(force=True)
        self.var_lote.set("")
        self.var_informe.set("")
        self.var_ce_final.set("")
        self.var_c_final.set("")
        self.var_si_final.set("")
        self.var_traccion.set("")
        self.var_seccion.set("")
        self.var_dureza.set("")
        self.var_tam_grafito.set("")
        self.var_morfologia.set("")
        self.var_tipo_grafito.set("")
        self.var_conteo_nodulos.set("")
        self.var_pct_nod.set("")
        self.var_alargamiento.set("")
        self.var_perlita.set("")
        self.var_ferrita.set("")
        self.var_cementita.set("0")
        self.var_matriz.set("")
        self.txt_data.delete("1.0", tk.END)
        self.tree.selection_remove(self.tree.selection())
        self._draft_fields = set()
        self._confirmed_snapshot = None
        self._group_baselines = {}
        try:
            self.txt_data.edit_modified(False)
        except Exception:
            pass
        self._suspend_autosave = False
        self._set_mode_ui()
        self._set_draft_ui(False)

    def _selected_group_info(self):
        sel = self.tree.selection()
        if not sel:
            return None
        item_id = sel[0]
        if item_id.startswith("report:"):
            parent = self.tree.parent(item_id)
            if not parent:
                return None
            item_id = parent
        if not item_id.startswith("group:"):
            return None
        _, base, lote = item_id.split(":", 2)
        return {"item_id": item_id, "base": base, "lote": lote}

    def _pick_materials_to_add(self, base, missing_materials):
        picked = {"value": None}
        win = tk.Toplevel(self)
        win.title("Agregar materiales")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(False, False)

        box = ttk.Frame(win, padding=12)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text=f"Base {base}").pack(anchor="w", pady=(0, 8))
        ttk.Label(box, text="Selecciona los materiales a agregar:").pack(anchor="w", pady=(0, 6))

        checks = ttk.LabelFrame(box, text="Materiales faltantes", padding=8)
        checks.pack(fill="x", expand=True)
        vars_by_material = []
        for material in missing_materials:
            var = tk.BooleanVar(value=True)
            ttk.Checkbutton(checks, text=f"Material {material}", variable=var).pack(anchor="w")
            vars_by_material.append((material, var))

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(10, 0))

        def accept():
            picked["value"] = [material for material, var in vars_by_material if var.get()]
            win.destroy()

        def cancel():
            picked["value"] = None
            win.destroy()

        ttk.Button(btns, text="Aceptar", command=accept).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=cancel).pack(side="right", padx=6)

        win.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_width()) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{x}+{y}")
        win.wait_window()
        return picked["value"]

    def _add_report_to_selected_group(self):
        self._reload_final_material_catalog()
        sel = self.tree.selection()
        info = self._group_info_from_item(sel[0]) if sel else None
        if not info:
            messagebox.showinfo("Calidad", "Selecciona un grupo o un material dentro del grupo.", parent=self)
            return

        base = info["base"]
        lote = info["lote"]
        existing = [it for it in self.reports if it.get("base", "") == base and it.get("lote", "") == lote]
        if not existing:
            messagebox.showinfo("Calidad", "No se encontro informacion base para ese grupo.", parent=self)
            return

        existing_materials = {it.get("material", "") for it in existing}
        missing = [m for m in self._materials_for_base(base) if m not in existing_materials]
        if not missing:
            messagebox.showinfo("Calidad", "Ese grupo ya tiene todos los materiales posibles.", parent=self)
            return

        selected = self._pick_materials_to_add(base, missing)
        if selected is None:
            return
        if not selected:
            messagebox.showinfo("Calidad", "No seleccionaste materiales para agregar.", parent=self)
            return

        template = existing[0]
        added_indexes = []
        for material in selected:
            defaults = self._material_defaults(material)
            report = {
                "fecha": template.get("fecha", ""),
                "base": base,
                "base_display": template.get("base_display", base),
                "material": material,
                "family": self._family_for_material(material),
                "lote": lote,
                "informe": f"Informe calidad {self._family_for_material(material)} {lote} - mat {material}".strip(),
                "ce_final": template.get("ce_final", ""),
                "c_final": template.get("c_final", ""),
                "si_final": template.get("si_final", ""),
                "datos": template.get("datos", ""),
                "traccion": defaults.get("traccion", ""),
                "seccion": defaults.get("seccion", self._default_section_for_material(material)),
                "dureza": defaults.get("dureza", ""),
                "tam_grafito": defaults.get("tam_grafito", ""),
                "morfologia": defaults.get("morfologia", ""),
                "tipo_grafito": defaults.get("tipo_grafito", ""),
                "conteo_nodulos": defaults.get("conteo_nodulos", ""),
                "pct_nodularizacion": defaults.get("pct_nodularizacion", ""),
                "alargamiento": defaults.get("alargamiento", ""),
                "perlita": defaults.get("perlita", ""),
                "ferrita": defaults.get("ferrita", ""),
                "cementita": defaults.get("cementita", "0"),
                "matriz": "",
                "archived": False,
                "archived_at": "",
                "_draft_pending": False,
                "_draft_base": None,
                "_draft_fields": [],
            }
            self.reports.append(report)
            added_indexes.append(len(self.reports) - 1)

        save_quality_reports(self.reports)
        self.refresh()
        if added_indexes:
            child_id = f"report:{added_indexes[0]}"
            try:
                self.tree.selection_set(child_id)
                self.tree.focus(child_id)
            except Exception:
                pass
            self._load_selected()

    def _report_print_fields(self, report):
        family = self._family_for_report(report)
        fields = [
            ("Fecha", report.get("fecha", "")),
            ("Base", report.get("base_display", report.get("base", ""))),
            ("Familia", family),
            ("Material", report.get("material", "")),
            ("Lote / colada", report.get("lote", "")),
            ("CE final", report.get("ce_final", "")),
            ("C final", report.get("c_final", "")),
            ("Si final", report.get("si_final", "")),
            ("Traccion (kg/mm2)", report.get("traccion", "")),
            ("Seccion muestra", report.get("seccion", "")),
            ("Dureza", report.get("dureza", "")),
            ("Tam grafito", report.get("tam_grafito", "")),
            ("Morfologia", report.get("morfologia", "")),
            ("Tipo grafito", report.get("tipo_grafito", "")),
            ("Conteo nodulos", report.get("conteo_nodulos", "")),
            ("% nodularizacion", report.get("pct_nodularizacion", "")),
            ("Alargamiento (%)", report.get("alargamiento", "")),
            ("Perlita %", report.get("perlita", "")),
            ("Ferrita %", report.get("ferrita", "")),
            ("Cementita %", report.get("cementita", "")),
            ("Matriz prevalente", report.get("matriz", "")),
        ]
        return [(label, value) for label, value in fields if str(value or "").strip()]

    def _render_print_report_html(self, report):
        title = html.escape(str(report.get("informe", "") or f"Material {report.get('material', '')}"))
        rows = "".join(
            f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>"
            for label, value in self._report_print_fields(report)
        )
        obs = html.escape(str(report.get("datos", "") or "")).replace("\n", "<br>")
        obs_block = f"<div class='obs'><div class='obs-title'>Observaciones</div><div>{obs}</div></div>" if obs else ""
        return f"""
        <section class="material-report">
          <div class="material-header">{title}</div>
          <table>{rows}</table>
          {obs_block}
        </section>
        """

    def _print_micro_rows(self, report):
        def _num(name):
            raw = str(report.get(name, "") or "").strip().replace(",", ".")
            try:
                return float(raw)
            except Exception:
                return None

        def _pct_text(label, value):
            rounded = round(value)
            if abs(value - rounded) < 0.0001:
                return f"{label} {int(rounded)}%"
            return f"{label} {value:.1f}%"

        perlita = _num("perlita")
        ferrita = _num("ferrita")

        if perlita is None and ferrita is None:
            return ["", ""]
        if perlita == 100:
            return ["Perlitico", ""]
        if ferrita == 100:
            return ["Ferritico", ""]

        items = []
        if perlita is not None:
            items.append(("Perlita", perlita, 0))
        if ferrita is not None:
            items.append(("Ferrita", ferrita, 1))
        items.sort(key=lambda item: (-item[1], item[2]))

        lines = [_pct_text(label, value) for label, value, _ in items if value is not None]
        while len(lines) < 2:
            lines.append("")
        return lines[:2]

    def _render_print_group_html(self, base, lote, reports):
        return self._render_print_group_html_with_color(base, lote, reports, "#111111")

    def _render_print_group_html_with_color(self, base, lote, reports, group_color):
        def darker(hex_color, factor=0.65):
            try:
                raw = str(hex_color or "").strip().lstrip("#")
                if len(raw) != 6:
                    return "#111111"
                r = max(0, min(255, int(int(raw[0:2], 16) * factor)))
                g = max(0, min(255, int(int(raw[2:4], 16) * factor)))
                b = max(0, min(255, int(int(raw[4:6], 16) * factor)))
                return f"#{r:02x}{g:02x}{b:02x}"
            except Exception:
                return "#111111"

        base_display = reports[0].get("base_display", base) if reports else base
        family = self._family_for_reports(reports)
        left_rows = [
            ("base", str(base_display)),
            ("ce", str((reports[0].get("ce_final", "") if reports else ""))),
            ("c", str((reports[0].get("c_final", "") if reports else ""))),
            ("si", str((reports[0].get("si_final", "") if reports else ""))),
        ]
        material_rows = []
        for report in reports:
            graphite_text = str(report.get("tipo_grafito", "") or report.get("morfologia", "") or "")
            micro_1, micro_2 = self._print_micro_rows(report)
            material_rows.extend([
                (f"material {report.get('material', '')}", "", "Tamano", str(report.get("tam_grafito", ""))),
                ("tipo grafito", graphite_text, micro_1, ""),
                ("HB", str(report.get("dureza", "")), micro_2, ""),
            ])

        row_count = max(len(left_rows), len(material_rows))
        rows_html = []
        for i in range(row_count):
            left_label, left_value = left_rows[i] if i < len(left_rows) else ("", "")
            mat_label, mat_value, right_label, right_value = material_rows[i] if i < len(material_rows) else ("", "", "", "")
            if i == 0:
                left_block = (
                    f"<th class='group-title' colspan='2'>colada {html.escape(str(lote))}</th>"
                    f"<td class='mat-cell'><span class='cell-label'>{html.escape(mat_label)}</span>"
                    f"<span class='cell-value'>{html.escape(mat_value)}</span></td>"
                    f"<td class='prop-cell'><span class='cell-label'>{html.escape(right_label)}</span>"
                    f"<span class='cell-value'>{html.escape(right_value)}</span></td>"
                )
            else:
                left_block = (
                    f"<th class='left-label'>{html.escape(left_label)}</th>"
                    f"<td class='left-value'>{html.escape(left_value)}</td>"
                    f"<td class='mat-cell'><span class='cell-label'>{html.escape(mat_label)}</span>"
                    f"<span class='cell-value'>{html.escape(mat_value)}</span></td>"
                    f"<td class='prop-cell'><span class='cell-label'>{html.escape(right_label)}</span>"
                    f"<span class='cell-value'>{html.escape(right_value)}</span></td>"
                )
            row_class = " class='material-sep'" if i > 0 and (i % 3 == 0) else ""
            rows_html.append(f"<tr{row_class}>{left_block}</tr>")

        family_line = f"<div class='group-family'>{html.escape(family)}</div>" if family else ""
        return f"""
        <section class="group-report" style="color:{html.escape(group_color)}; --group-line:{html.escape(darker(group_color))};">
          {family_line}
          <table class="group-table">
            {''.join(rows_html)}
          </table>
        </section>
        """

    def _build_groups_print_html(self, group_items):
        top = self.winfo_toplevel()
        group_colors = list(getattr(top, "_print_group_colors", ["#1f4ea3", "#b03a2e", "#2e8b57"]))
        pages = []
        previous_date = None
        for start in range(0, len(group_items), 3):
            chunk = group_items[start:start + 3]
            parts = []
            for idx, (base, lote, reports) in enumerate(chunk):
                group_date = str((reports[0].get("fecha", "") if reports else "") or "")[:10]
                if group_date and group_date != previous_date:
                    parts.append(f"<div class='date-header'>{html.escape(group_date)}</div>")
                    previous_date = group_date
                parts.append(
                    self._render_print_group_html_with_color(
                        base,
                        lote,
                        reports,
                        group_colors[idx] if idx < len(group_colors) else "#111111",
                    )
                )
            content = "".join(parts)
            pages.append(f"<div class='page'>{content}</div>")
        return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Informes de calidad</title>
  <style>
    @page {{ size: A4 portrait; margin: 14mm 8mm 8mm 8mm; }}
    body {{ margin: 0; font-family: Segoe UI, Arial, sans-serif; color: #111; background: #f2f2f2; }}
    .page {{
      width: 194mm;
      min-height: 281mm;
      margin: 0 auto 6mm auto;
      background: white;
      display: block;
      box-sizing: border-box;
      page-break-after: always;
      padding: 4mm 0 0 0;
    }}
    .page:last-child {{ page-break-after: auto; }}
    .date-header {{
      margin: 0;
      padding: 1mm 1.5mm;
      font-size: 18px;
      font-weight: 700;
      text-align: right;
      border-top: 2px solid #111;
      border-bottom: 1px solid #777;
      background: #f5f5f5;
    }}
    .page .date-header:first-child {{
      border-top: 0;
    }}
    .group-report {{
      border: 0;
      padding: 0;
      box-sizing: border-box;
      overflow: hidden;
    }}
    .group-report + .group-report {{
      border-top: 3px solid #111;
    }}
    .group-family {{
      font-size: 15px;
      font-weight: 700;
      text-transform: uppercase;
      margin: 0;
      padding: 0;
      line-height: 1;
      color: #444;
    }}
    .group-table {{ width: 100%; margin: 0; border-collapse: collapse; font-size: 15px; table-layout: fixed; }}
    .group-table th, .group-table td {{ border: 1px solid #b9b9b9; padding: 1.2mm 1.6mm; text-align: left; vertical-align: middle; }}
    .group-title {{ font-size: 17px; font-weight: 700; background: #fafafa; }}
    .left-label {{ width: 10%; font-weight: 700; background: #fafafa; text-transform: lowercase; }}
    .left-value {{ width: 18%; }}
    .mat-cell {{ width: 42%; border-left: 3px solid var(--group-line, #111111) !important; }}
    .prop-cell {{ width: 30%; }}
    .material-sep .mat-cell, .material-sep .prop-cell {{ border-top: 3px solid var(--group-line, #111111) !important; }}
    .cell-label {{ display: inline-block; min-width: 96px; font-weight: 700; color: var(--group-line, #111111); }}
    .cell-value {{ display: inline-block; }}
  </style>
</head>
<body>
  {''.join(pages)}
</body>
</html>"""

    def _group_choices(self):
        groups = {}
        reports_source = self.reports if self.var_show_archived.get() else [r for r in self.reports if not r.get("archived")]
        for report in reports_source:
            base = report.get("base", "")
            lote = report.get("lote", "")
            key = (base, lote)
            groups.setdefault(key, []).append(report)
        items = []
        for (base, lote), reports in sorted(groups.items(), key=lambda item: (item[0][1], item[0][0])):
            ordered_reports = sorted(reports, key=lambda r: str(r.get("material", "")))
            latest_fecha = max(str(r.get("fecha", "") or "") for r in ordered_reports) if ordered_reports else ""
            items.append((base, lote, ordered_reports, latest_fecha))
        items.sort(key=lambda item: (item[3], item[1], item[0]))
        return items

    def _archive_printed_groups(self, chosen):
        if not chosen:
            return 0
        keys = {(base, lote) for base, lote, _ in chosen}
        if not keys:
            return 0
        archived = 0
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        for report in self.reports:
            key = (report.get("base", ""), report.get("lote", ""))
            if key not in keys:
                continue
            if report.get("archived"):
                continue
            report["archived"] = True
            report["archived_at"] = stamp
            archived += 1
        if archived:
            save_quality_reports(self.reports)
            self.refresh()
            self._clear_form()
        return archived

    def _pick_groups_to_print(self):
        groups = self._group_choices()
        if not groups:
            return None
        default_selected = {(base, lote) for base, lote, _, _ in groups[-3:]}

        picked = {"value": None}
        win = tk.Toplevel(self)
        win.title("Imprimir grupos")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(False, False)

        box = ttk.Frame(win, padding=12)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="Selecciona hasta 3 grupos para imprimir:").pack(anchor="w", pady=(0, 8))

        checks = ttk.LabelFrame(box, text="Grupos", padding=8)
        checks.pack(fill="x", expand=True)
        vars_by_group = []
        for base, lote, reports, latest_fecha in groups:
            checked = (base, lote) in default_selected
            var = tk.BooleanVar(value=checked)
            family = self._family_for_reports(reports)
            label = f"Base {base} - {family} - {lote} ({len(reports)} informes, {latest_fecha})"
            ttk.Checkbutton(checks, text=label, variable=var).pack(anchor="w")
            vars_by_group.append(((base, lote, reports), var))

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(10, 0))

        def accept():
            chosen = [group for group, var in vars_by_group if var.get()]
            if len(chosen) > 3:
                messagebox.showinfo("Calidad", "Puedes seleccionar hasta 3 grupos.", parent=win)
                return
            picked["value"] = chosen
            win.destroy()

        def cancel():
            picked["value"] = None
            win.destroy()

        ttk.Button(btns, text="Aceptar", command=accept).pack(side="right")
        ttk.Button(btns, text="Cancelar", command=cancel).pack(side="right", padx=6)

        win.update_idletasks()
        root = self.winfo_toplevel()
        x = root.winfo_rootx() + max(0, (root.winfo_width() - win.winfo_width()) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win.winfo_height()) // 2)
        win.geometry(f"+{x}+{y}")
        win.wait_window()
        return picked["value"]

    def _print_groups(self):
        chosen = self._pick_groups_to_print()
        if chosen is None:
            return
        if not chosen:
            messagebox.showinfo("Calidad", "No seleccionaste grupos para imprimir.", parent=self)
            return
        html_text = self._build_groups_print_html(chosen)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        out_path = Path(tempfile.gettempdir()) / f"ajuste_comp_calidad_grupos_{stamp}.html"
        out_path.write_text(html_text, encoding="utf-8")
        try:
            webbrowser.open_new_tab(out_path.as_uri())
            archived = self._archive_printed_groups(chosen)
            messagebox.showinfo(
                "Calidad",
                f"Se genero la hoja lista para imprimir.\n\n{out_path}\n\nInformes archivados: {archived}",
                parent=self,
            )
        except Exception as ex:
            messagebox.showwarning("Calidad", f"Se genero el archivo, pero no se pudo abrir automaticamente.\n\n{out_path}\n\n{ex}", parent=self)

    def _load_selected(self):
        sel = self.tree.selection()
        if not sel:
            return
        group_info = self._group_info_from_item(sel[0])
        if group_info and sel[0].startswith("group:"):
            self._load_group_selection(group_info["base"], group_info["lote"], item_id=sel[0])
            return
        idx = self._item_to_index.get(sel[0])
        if idx is None:
            self._selected_index = None
            return
        if idx < 0 or idx >= len(self.reports):
            return
        report = self.reports[idx]
        self._suspend_autosave = True
        self._selected_index = idx
        self._selected_group = None
        self.var_fecha.set(report.get("fecha", ""))
        self.var_base.set(report.get("base", "5"))
        self._sync_materials()
        self.var_material.set(report.get("material", ""))
        self.var_seccion.set(report.get("seccion", ""))
        self._sync_section_options()
        self.var_lote.set(report.get("lote", ""))
        self.var_informe.set(report.get("informe", ""))
        self.var_ce_final.set(report.get("ce_final", ""))
        self.var_c_final.set(report.get("c_final", ""))
        self.var_si_final.set(report.get("si_final", ""))
        self.var_traccion.set(report.get("traccion", ""))
        self.var_seccion.set(report.get("seccion", ""))
        self.var_dureza.set(report.get("dureza", ""))
        self.var_tam_grafito.set(report.get("tam_grafito", ""))
        self.var_morfologia.set(report.get("morfologia", ""))
        self.var_tipo_grafito.set(report.get("tipo_grafito", ""))
        self.var_conteo_nodulos.set(report.get("conteo_nodulos", ""))
        self.var_pct_nod.set(report.get("pct_nodularizacion", ""))
        self.var_alargamiento.set(report.get("alargamiento", ""))
        self.var_perlita.set(report.get("perlita", ""))
        self.var_ferrita.set(report.get("ferrita", ""))
        self.var_cementita.set(report.get("cementita", ""))
        self.var_matriz.set(report.get("matriz", ""))
        self._sync_family_fields()
        self._update_microstructure()
        self.txt_data.delete("1.0", tk.END)
        self.txt_data.insert("1.0", report.get("datos", ""))
        try:
            self.txt_data.edit_modified(False)
        except Exception:
            pass
        self._confirmed_snapshot = self._baseline_from_report(report)
        self._draft_fields = set(report.get("_draft_fields", []))
        self._group_baselines = {}
        self._suspend_autosave = False
        self._set_mode_ui()
        self._set_draft_ui(bool(report.get("_draft_pending")))

    def _save_report(self):
        if self._selected_group is not None and self._selected_index is None:
            indexes = self._group_report_indexes(self._selected_group["base"], self._selected_group["lote"])
            if not indexes:
                return
            changed = self._group_changed_values()
            if not changed:
                restored_any = False
                for idx in indexes:
                    report = self.reports[idx]
                    base_report = report.get("_draft_base") if report.get("_draft_pending") and isinstance(report.get("_draft_base"), dict) else None
                    if base_report:
                        restored = dict(base_report)
                        restored["_draft_pending"] = False
                        restored["_draft_base"] = None
                        restored["_draft_fields"] = []
                        self.reports[idx] = restored
                        restored_any = True
                if restored_any:
                    save_quality_reports(self.reports)
                    self.refresh()
                    self._load_group_selection(self._selected_group["base"], self._selected_group["lote"], item_id=self._selected_group.get("item_id"))
                self._set_draft_ui(False)
                return
            for idx in indexes:
                report = self._apply_group_form_to_report(self.reports[idx])
                report["_draft_pending"] = False
                report["_draft_base"] = None
                report["_draft_fields"] = []
                self.reports[idx] = report
            self._confirmed_snapshot = self._normalize_report_payload(self.reports[indexes[0]])
            self._draft_fields = set()
            save_quality_reports(self.reports)
            self.refresh()
            self._load_group_selection(self._selected_group["base"], self._selected_group["lote"], item_id=self._selected_group.get("item_id"))
            self._set_draft_ui(False)
            return

        base = self.var_base.get().strip()
        material = self.var_material.get().strip()
        if base not in self._base_to_materials:
            messagebox.showerror("Calidad", "Base invalida.", parent=self)
            return
        if material not in self._materials_for_base(base):
            messagebox.showerror("Calidad", "El material no corresponde a la base elegida.", parent=self)
            return
        perlita = self._parse_optional_float(self.var_perlita.get())
        ferrita = self._parse_optional_float(self.var_ferrita.get())
        cementita = self._parse_optional_float(self.var_cementita.get())
        cementita = 0.0 if cementita is None else cementita
        any_micro = perlita is not None or ferrita is not None or abs(cementita) > 1e-6
        if any_micro and ((perlita is None) or (ferrita is None)):
            messagebox.showerror("Calidad", "Perlita y ferrita deben quedar completas.", parent=self)
            return
        if perlita is not None and ferrita is not None and abs((perlita + ferrita + cementita) - 100.0) > 1e-6:
            messagebox.showerror("Calidad", "Perlita + ferrita + cementita deben sumar 100%.", parent=self)
            return
        self._update_microstructure()
        report = self._build_report_from_form(pending=False)
        report["_draft_base"] = None
        report["_draft_fields"] = []
        if self._selected_index is None:
            self.reports.append(report)
        else:
            self.reports[self._selected_index] = report
        self._confirmed_snapshot = self._normalize_report_payload(report)
        self._draft_fields = set()
        save_quality_reports(self.reports)
        self.refresh()
        self._set_draft_ui(False)
        self._clear_form()

    def _delete_selected(self):
        if self._selected_index is None:
            return
        if not messagebox.askyesno("Calidad", "Eliminar el informe seleccionado?", parent=self):
            return
        del self.reports[self._selected_index]
        save_quality_reports(self.reports)
        self.refresh()
        self._clear_form()

    def _delete_selected_group(self):
        sel = self.tree.selection()
        if not sel:
            return
        item_id = sel[0]
        if item_id.startswith("report:"):
            parent = self.tree.parent(item_id)
            if not parent:
                return
            item_id = parent
        if not item_id.startswith("group:"):
            return
        _, base, lote = item_id.split(":", 2)
        count = sum(1 for it in self.reports if it.get("base", "") == base and it.get("lote", "") == lote)
        if count <= 0:
            return
        if not messagebox.askyesno("Calidad", f"Eliminar el grupo completo ({count} informes)?", parent=self):
            return
        self.reports = [it for it in self.reports if not (it.get("base", "") == base and it.get("lote", "") == lote)]
        save_quality_reports(self.reports)
        self.refresh()
        self._clear_form()
