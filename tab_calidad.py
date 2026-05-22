import tkinter as tk
from tkinter import ttk, messagebox, filedialog, simpledialog
from datetime import datetime
import os
import re
import html
import shutil
import subprocess
import tempfile
import time
import uuid
import webbrowser
from pathlib import Path

from storage import load_quality_reports, save_quality_reports, ensure_quality_images_dir
from utils import fmt
from config import BG_ENTRY, FG, ACCENT
from widgets import ScrollFrame

try:
    from PIL import Image, ImageOps, ImageTk
except Exception:
    Image = None
    ImageOps = None
    ImageTk = None

DEFAULT_SECTION_OPTIONS = ["Hasta 13 mm", "De 12 a 25 mm", "De 20 a 50 mm"]
GRAPHITE_TYPE_OPTIONS = (
    "A 100%",
    "A",
    "A-B",
    "A80/B20",
    "A85/B15",
    "A90",
    "A90/B10",
    "A90/C10",
    "A 95% / B 5%",
    "A95/B05",
    "A95/C05",
    "A 90% / B 10%",
    "A 85% / B 15%",
)
GRAPHITE_SIZE_OPTIONS = (
    "1",
    "1-2",
    "2",
    "2-1",
    "2-3",
    "3",
    "3-2",
    "3-4",
    "4",
    "4-3",
    "4-5",
    "4-6",
    "5",
    "5-4",
    "5-6",
    "6",
    "6-4",
    "6-5",
    "6-7",
    "7",
    "7-6",
    "7-8",
    "8",
    "8-7",
)
IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".bmp", ".gif", ".webp"}
IMAGEJ_RESOLUCION_PX_MM = 1655
IMAGEJ_AREA_ANALISIS_PX = 1655 * 820
IMAGEJ_AREA_UMBRAL = 100
IMAGEJ_NODULAR_DEFAULT_NODULES = "300"
IMAGEJ_LIMITS = (
    ("Clase 3 (0.25-0.50mm)", 0.25, 0.50),
    ("Clase 4 (0.12-0.25mm)", 0.12, 0.25),
    ("Clase 5 (0.06-0.12mm)", 0.06, 0.12),
    ("Clase 6 (0.03-0.06mm)", 0.03, 0.06),
    ("Clase 7 (0.015-0.03mm)", 0.015, 0.03),
    ("Clase 8 (<0.015mm)", 0.0001, 0.015),
)
FUNDICIONES_APP_PATH = r"\\LABORATORIO\Bases\2011\PGR en PC-2011\Fundiciones-2010PRG.accde"
FUNDICIONES_SHORTCUT_PATH = r"C:\Users\LABOR01\Desktop\Fundiciones.lnk"
FUNDICIONES_MSACCESS_PATH = r"C:\Program Files (x86)\Microsoft Office\Root\Office16\MSACCESS.EXE"
FUNDICIONES_WRKGRP_PATH = r"\\LABORATORIO\Bases\Eejcutables\db2.mdw"
FUNDICIONES_DEFAULT_USER = "andrés"
FUNDICIONES_DEFAULT_PASSWORD = "qwerty9225"
FUNDICIONES_DEFAULT_RESP_CODE = "290"
FUNDICIONES_DEFAULT_RESP_NAME = "Andrés"
FUNDICIONES_MAPPED_BACKEND_PATH = r"M:\Bases\2011\Datos\DatosUnificado2010.accdb"
FUNDICIONES_DRIVE_ROOT = r"\\LABORATORIO"
FUNDICIONES_WINDOW_HINT = "Fundiciones-2010PRG"
FUNDICIONES_TARGET_FORM = "frmCargaInformesFundiciones"
FUNDICIONES_COLADA_CONTROL = "cmbElegirFundición"
FUNDICIONES_RESP_CONTROL = "txtCódRespInforme"
FUNDICIONES_RESP_COMBO = "cmbNomRespInforme"
FUNDICIONES_APPROVAL_DATE_CONTROL = "txtFechaAprobInfMat"
FUNDICIONES_MATERIAL_RESP_CONTROL = "txtCódRespInforme"
FUNDICIONES_MATERIAL_RESP_COMBO = "cmbNomRespInforme"
FUNDICIONES_MATERIALS_SUBFORM = "SubfrmFrmCargaInformesMateriales"
FUNDICIONES_MATERIAL_CONTROL = "cmbCódMaterial"
FUNDICIONES_MATERIAL_FIELD_CANDIDATES = ("CódMaterial", "InformesMateriales.CódMaterial")
FUNDICIONES_MATERIAL_NEXT_CONTROL = "cmdMaterialSiguiente"
FUNDICIONES_MATERIAL_PREV_CONTROL = "cmdMaterialAnterior"
FUNDICIONES_GRAPHITE_CONTROL = "cmbMorfologíaGrafito"
FUNDICIONES_GRAPHITE_TYPE_CONTROL = "cmbTipoMorfologíaGrafito"
FUNDICIONES_DENSITY_MIN_CONTROL = "txtDensidadMínima"
FUNDICIONES_DENSITY_MAX_CONTROL = "txtDensidadMáxima"
FUNDICIONES_MATRIX_CONTROL = "cmbMatriz"
FUNDICIONES_MATRIX_PERCENT_CONTROL = "cmbPorcentajeMatrizPredominante"
FUNDICIONES_CE_CONTROL = "txtCarbonoEquivalente"
FUNDICIONES_RESISTANCE_CONTROL = "txtValorResistencia"
FUNDICIONES_ELONGATION_CONTROL = "txtValorAlargamiento"
FUNDICIONES_REPORT_OBS_CONTROL = "txtObservacionesInforme"
FUNDICIONES_REPORT_OBS_MAX_CHARS = 180
FUNDICIONES_MATERIAL_OBS_CONTROL = "txtObservacionesMaterial"
FUNDICIONES_THICKNESS_SUBFORM = "SubfrmCargaInformesEspesores"
FUNDICIONES_THICKNESS_CONTROL = "cmbEspesor"
FUNDICIONES_HARDNESS_CONTROL = "txtValorDureza"
FUNDICIONES_HARDNESS_CONTROL_ALIASES = ("txtValorDureza", "txtDureza")
FUNDICIONES_GRAPHITE_SIZE_CONTROL = "cmbTamañoGrafito"
FUNDICIONES_GRAPHITE_SIZE_CONTROL_ALIASES = ("cmbTamañoGrafito", "txtTamañoGrafito")
FUNDICIONES_EXACT_CONTROL_NAMES = (
    "cmbElegirFundición",
    "TxtCódFundición",
    "txtCódRespInforme",
    "cmbNomRespInforme",
    "cmbCódMaterial",
    "cmdMaterialSiguiente",
    "cmdMaterialAnterior",
    "cmbMorfologíaGrafito",
    "cmbTipoMorfologíaGrafito",
    "txtDensidadMínima",
    "txtDensidadMáxima",
    "cmbMatriz",
    "cmbPorcentajeMatrizPredominante",
    "txtCarbonoEquivalente",
    "txtValorResistencia",
    "txtValorAlargamiento",
    "txtObservacionesInforme",
    "txtObservacionesMaterial",
    "cmbEspesor",
    "txtValorDureza",
    "txtDureza",
    "cmbTamañoGrafito",
    "txtTamañoGrafito",
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
        self._report_images = []
        self._image_preview_photo = None

        self._reload_final_material_catalog()

        top = ttk.Frame(self)
        top.pack(fill="x", pady=(0, 8))
        ttk.Label(top, text="Informes de calidad").pack(side="left")
        ttk.Checkbutton(top, text="Mostrar archivados", variable=self.var_show_archived, command=self.refresh).pack(side="right", padx=(0, 8))
        ttk.Button(top, text="Refrescar", command=self.refresh).pack(side="right")
        ttk.Button(top, text="Imprimir con imagenes", command=lambda: self._print_groups(include_images=True)).pack(side="right", padx=(0, 6))
        ttk.Button(top, text="Imprimir", command=lambda: self._print_groups(include_images=False)).pack(side="right", padx=(0, 6))

        action_bar = ttk.Frame(self, padding=(0, 4))
        action_bar.pack(fill="x", pady=(0, 8))
        ttk.Button(action_bar, text="Guardar", command=self._save_report).pack(side="left")
        ttk.Button(action_bar, text="Cancelar", command=self._cancel_draft).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Agregar", command=self._add_report_to_selected_group).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Cargar en Access", command=self._load_current_report_in_access).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Abrir en Access", command=self._open_current_report_in_access_for_review).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Eliminar", command=self._delete_selected).pack(side="right")
        ttk.Button(action_bar, text="Eliminar grupo", command=self._delete_selected_group).pack(side="right", padx=(0, 6))
        self.lbl_bases_help = None

        body = ttk.PanedWindow(self, orient="horizontal")
        body.pack(fill="both", expand=True)

        left = ttk.Frame(body)
        right = ttk.Frame(body)
        body.add(left, weight=1)
        body.add(right, weight=2)

        form_box = ttk.LabelFrame(left, text="Carga de informe", padding=4)
        form_box.pack(fill="both", expand=True)
        self.form_scroll = ScrollFrame(form_box)
        self.form_scroll.pack(fill="both", expand=True)
        form = self.form_scroll.inner

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
        self.cb_material.bind("<<ComboboxSelected>>", lambda e: (self._apply_material_defaults(), self._sync_family_fields()))

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
        self.ent_tam_grafito = ttk.Combobox(
            props,
            textvariable=self.var_tam_grafito,
            values=GRAPHITE_SIZE_OPTIONS,
            state="readonly",
            width=14,
        )
        self.ent_tam_grafito.grid(row=1, column=3, sticky="ew", pady=2)
        self.lbl_morfologia = ttk.Label(props, text="Morfologia")
        self.lbl_morfologia.grid(row=2, column=0, sticky="w", pady=2)
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

        images_box = ttk.LabelFrame(form, text="Imagenes del informe", padding=6)
        images_box.grid(row=9, column=0, columnspan=2, sticky="ew", pady=(0, 10), padx=(0, 4))
        images_box.columnconfigure(0, weight=1)
        self.images_tree = ttk.Treeview(images_box, columns=("archivo", "comentario"), show="headings", height=4, selectmode="extended")
        self.images_tree.heading("archivo", text="Archivo")
        self.images_tree.heading("comentario", text="Comentario")
        self.images_tree.column("archivo", width=170, anchor="w")
        self.images_tree.column("comentario", width=190, anchor="w")
        self.images_tree.grid(row=0, column=0, sticky="ew")
        self.images_tree.bind("<<TreeviewSelect>>", lambda e: self._update_image_preview())
        self.images_tree.bind("<Double-Button-1>", lambda e: self._edit_selected_image_comment())
        image_btns = ttk.Frame(images_box)
        image_btns.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ttk.Button(image_btns, text="Importar ImageJ", command=self._import_imagej_analysis).pack(fill="x")
        ttk.Button(image_btns, text="Agregar imagen", command=self._add_images).pack(fill="x")
        ttk.Button(image_btns, text="Comentario", command=self._edit_selected_image_comment).pack(fill="x", pady=(4, 0))
        ttk.Button(image_btns, text="Abrir", command=self._open_selected_image).pack(fill="x", pady=(4, 0))
        ttk.Button(image_btns, text="Quitar", command=self._remove_selected_images).pack(fill="x", pady=(4, 0))
        self.lbl_image_preview = tk.Label(
            images_box,
            text="Sin imagen seleccionada",
            anchor="center",
            bg="#f6f6f6",
            fg="#555555",
            relief="sunken",
            width=32,
            height=8,
        )
        self.lbl_image_preview.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 2), padx=8, ipady=6)

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
        self.lbl_draft.grid(row=11, column=0, columnspan=2, sticky="ew", pady=(6, 0))
        self.lbl_draft.grid_remove()

        self.lbl_mode = tk.Label(form, text="", anchor="w", bg="#5a2f00", fg="white")
        self.lbl_mode.grid(row=12, column=0, columnspan=2, sticky="ew", pady=(4, 0))
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

    def _normalize_report_images(self, images):
        normalized = []
        used_ids = set()
        for item in images or []:
            if not isinstance(item, dict):
                continue
            path = str(item.get("path") or item.get("archivo") or "").strip()
            if not path:
                continue
            nombre = str(item.get("nombre") or Path(path).name).strip() or Path(path).name
            image_id = str(item.get("id") or uuid.uuid4().hex)
            while image_id in used_ids:
                image_id = uuid.uuid4().hex
            used_ids.add(image_id)
            normalized.append({
                "id": image_id,
                "nombre": nombre,
                "path": path,
                "comentario": str(item.get("comentario") or item.get("comment") or "").strip(),
                "added_at": str(item.get("added_at") or ""),
            })
        return normalized

    def _refresh_images_ui(self):
        try:
            self.images_tree.delete(*self.images_tree.get_children())
            for image in self._report_images:
                iid = str(image.get("id") or uuid.uuid4().hex)
                self.images_tree.insert("", "end", iid=iid, values=(image.get("nombre", ""), image.get("comentario", "")))
            self._set_image_preview_message("Selecciona una imagen para verla aca." if self._report_images else "Sin imagen seleccionada")
        except Exception:
            pass

    def _set_image_preview_message(self, message):
        if not hasattr(self, "lbl_image_preview"):
            return
        self._image_preview_photo = None
        try:
            self.lbl_image_preview.configure(image="", text=message, width=32, height=8)
        except Exception:
            pass

    def _selected_report_image(self):
        if not hasattr(self, "images_tree"):
            return None
        selected = self.images_tree.selection()
        if not selected:
            return None
        target_id = selected[0]
        return next((item for item in self._report_images if str(item.get("id")) == target_id), None)

    def _update_image_preview(self):
        image = self._selected_report_image()
        if not image:
            self._set_image_preview_message("Selecciona una imagen para verla aca." if self._report_images else "Sin imagen seleccionada")
            return
        path = Path(str(image.get("path") or ""))
        if not path.exists():
            self._set_image_preview_message("Imagen no encontrada.")
            return
        if Image is None or ImageTk is None:
            self._set_image_preview_message("Vista previa no disponible.\nUsa Abrir.")
            return
        try:
            with Image.open(path) as source:
                img = ImageOps.exif_transpose(source) if ImageOps is not None else source.copy()
                img = img.copy()
            img.thumbnail((360, 220), Image.LANCZOS)
            self._image_preview_photo = ImageTk.PhotoImage(img)
            self.lbl_image_preview.configure(
                image=self._image_preview_photo,
                text="",
                width=self._image_preview_photo.width() + 24,
                height=self._image_preview_photo.height() + 16,
            )
        except Exception:
            self._set_image_preview_message("No se pudo mostrar la vista previa.\nUsa Abrir.")

    def _copy_image_attachment(self, source_path):
        source = Path(source_path)
        suffix = source.suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            raise ValueError("Formato de imagen no permitido.")
        if not source.exists() or not source.is_file():
            raise FileNotFoundError("No se encontro la imagen seleccionada.")
        dest_dir = Path(ensure_quality_images_dir())
        dest_name = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}{suffix}"
        dest = dest_dir / dest_name
        shutil.copy2(str(source), str(dest))
        return {
            "id": uuid.uuid4().hex,
            "nombre": source.name,
            "path": str(dest),
            "comentario": "",
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _images_changed(self):
        if self._suspend_autosave:
            return
        if self._selected_group is not None and self._selected_index is None:
            return
        if self._selected_index is not None:
            self._draft_fields.add("imagenes")
            self._schedule_draft_save()

    def _add_images(self):
        if self._selected_group is not None and self._selected_index is None:
            messagebox.showinfo("Calidad", "Selecciona un material del grupo para adjuntar imagenes a ese informe.", parent=self)
            return
        paths = filedialog.askopenfilenames(
            parent=self,
            title="Agregar imagenes al informe",
            filetypes=(
                ("Imagenes", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"),
                ("Todos los archivos", "*.*"),
            ),
        )
        if not paths:
            return
        added = 0
        errors = []
        last_added_id = None
        for path in paths:
            try:
                item = self._copy_image_attachment(path)
                comment = simpledialog.askstring(
                    "Comentario de imagen",
                    f"Comentario para {Path(path).name}:",
                    parent=self,
                )
                if comment is not None:
                    item["comentario"] = comment.strip()
                self._report_images.append(item)
                last_added_id = item["id"]
                added += 1
            except Exception as ex:
                errors.append(f"{Path(path).name}: {ex}")
        self._report_images = self._normalize_report_images(self._report_images)
        self._refresh_images_ui()
        if last_added_id:
            try:
                self.images_tree.selection_set(last_added_id)
                self.images_tree.focus(last_added_id)
                self._update_image_preview()
            except Exception:
                pass
        if added:
            self._images_changed()
        if errors:
            messagebox.showwarning("Calidad", "Algunas imagenes no se pudieron agregar:\n\n" + "\n".join(errors), parent=self)

    def _edit_selected_image_comment(self):
        image = self._selected_report_image()
        if not image:
            messagebox.showinfo("Calidad", "Selecciona una imagen para editar su comentario.", parent=self)
            return
        current = str(image.get("comentario", "") or "")
        value = simpledialog.askstring(
            "Comentario de imagen",
            f"Comentario para {image.get('nombre', 'imagen')}:",
            initialvalue=current,
            parent=self,
        )
        if value is None:
            return
        image["comentario"] = value.strip()
        self._report_images = self._normalize_report_images(self._report_images)
        self._refresh_images_ui()
        try:
            self.images_tree.selection_set(str(image.get("id")))
            self.images_tree.focus(str(image.get("id")))
        except Exception:
            pass
        self._images_changed()

    def _remove_selected_images(self):
        selected = set(self.images_tree.selection())
        if not selected:
            return
        self._report_images = [image for image in self._report_images if str(image.get("id")) not in selected]
        self._refresh_images_ui()
        self._update_image_preview()
        self._images_changed()

    def _open_selected_image(self):
        selected = self.images_tree.selection()
        if not selected:
            return
        target_id = selected[0]
        image = next((item for item in self._report_images if str(item.get("id")) == target_id), None)
        if not image:
            return
        path = Path(str(image.get("path") or ""))
        if not path.exists():
            messagebox.showwarning("Calidad", "No se encontro el archivo de imagen guardado.", parent=self)
            return
        try:
            os.startfile(str(path))
        except Exception:
            webbrowser.open_new_tab(path.resolve().as_uri())

    def _format_metric(self, value, digits=2):
        try:
            return f"{float(value):.{digits}f}".rstrip("0").rstrip(".")
        except Exception:
            return str(value or "")

    def _append_observation_block(self, title, lines):
        block_lines = [title, *lines]
        block = "\n".join(str(line) for line in block_lines if str(line).strip())
        current = self.txt_data.get("1.0", tk.END).strip()
        new_text = f"{current}\n\n{block}" if current else block
        self.txt_data.delete("1.0", tk.END)
        self.txt_data.insert("1.0", new_text)
        if self._selected_index is not None:
            self._draft_fields.add("datos")
            self._schedule_draft_save()

    def _prompt_quality_value_if_empty(self, var, title, label):
        if var.get().strip():
            return
        value = simpledialog.askfloat(title, label, parent=self)
        if value is not None:
            var.set(self._format_metric(value, 3))

    def _calculate_imagej_stats(self, csv_path):
        try:
            import numpy as np
            import pandas as pd
        except Exception as ex:
            raise RuntimeError(f"Faltan dependencias para leer ImageJ: {ex}") from ex

        df = pd.read_csv(csv_path, sep=None, engine="python")
        missing = [col for col in ("Area", "Circ.") if col not in df.columns]
        if missing:
            raise ValueError("El CSV no tiene las columnas necesarias: " + ", ".join(missing))
        df = df.copy()
        df["Area"] = pd.to_numeric(df["Area"], errors="coerce")
        df["Circ."] = pd.to_numeric(df["Circ."], errors="coerce")
        df = df.dropna(subset=["Area", "Circ."])
        df = df[df["Area"] >= IMAGEJ_AREA_UMBRAL]
        if df.empty:
            raise ValueError(f"No quedaron particulas con Area >= {IMAGEJ_AREA_UMBRAL}.")

        df["Diametro_mm"] = np.sqrt((4 * df["Area"]) / np.pi) / IMAGEJ_RESOLUCION_PX_MM
        df["Categoria"] = ""
        for category, min_d, max_d in IMAGEJ_LIMITS:
            mask = df["Diametro_mm"].between(min_d, max_d, inclusive="both")
            df.loc[mask, "Categoria"] = category

        area_total = float(df["Area"].sum())
        nodular = df[df["Circ."] >= 0.5]
        vermicular = df[df["Circ."] < 0.5]
        analysis_area_mm2 = IMAGEJ_AREA_ANALISIS_PX / (IMAGEJ_RESOLUCION_PX_MM ** 2)
        counts = {category: int((df["Categoria"] == category).sum()) for category, _, _ in IMAGEJ_LIMITS}
        fuera_clase = int((df["Categoria"] == "").sum())
        if fuera_clase:
            counts["Fuera de clase"] = fuera_clase
        tam_grafito = self._imagej_majority_size_text(counts)

        return {
            "df": df,
            "n_total": int(len(df)),
            "n_mm2": round(len(df) / analysis_area_mm2, 2),
            "nodularidad": round(float(nodular["Area"].sum()) / area_total * 100, 2),
            "vermicular": round(float(vermicular["Area"].sum()) / area_total * 100, 2),
            "diam_prom_um": round(float(df["Diametro_mm"].mean()) * 1000, 2),
            "diam_max_um": round(float(df["Diametro_mm"].max()) * 1000, 2),
            "diam_min_um": round(float(df["Diametro_mm"].min()) * 1000, 2),
            "counts": counts,
            "tam_grafito_clase": tam_grafito,
        }

    def _imagej_class_code(self, label):
        match = re.search(r"Clase\s+(\d+)", str(label or ""))
        return match.group(1) if match else str(label or "").strip()

    def _imagej_majority_size_text(self, counts):
        class_counts = [
            (idx, label, int(round(float(counts.get(label, 0) or 0))))
            for idx, (label, _, _) in enumerate(IMAGEJ_LIMITS)
            if float(counts.get(label, 0) or 0) > 0
        ]
        if not class_counts:
            return ""
        total = sum(count for _, _, count in class_counts)
        ordered = sorted(class_counts, key=lambda item: (-item[2], item[0]))
        selected = [ordered[0]]
        if len(ordered) > 1:
            top_count = ordered[0][2]
            second = ordered[1]
            second_ratio = second[2] / total if total else 0
            close_to_top = second[2] >= (top_count * 0.5)
            if second_ratio >= 0.20 or close_to_top:
                selected.append(second)
        selected = sorted(selected, key=lambda item: item[0])
        return "-".join(self._imagej_class_code(label) for _, label, _ in selected)

    def _merge_imagej_stats(self, stats_list, csv_paths):
        if not stats_list:
            raise ValueError("No hay estadisticas de ImageJ para combinar.")
        if len(stats_list) == 1:
            merged = dict(stats_list[0])
            merged["source_count"] = 1
            merged["csv_names"] = [Path(csv_paths[0]).name]
            return merged

        count = float(len(stats_list))
        count_labels = [label for label, _, _ in IMAGEJ_LIMITS] + ["Fuera de clase"]
        avg_counts = {}
        for label in count_labels:
            avg_value = sum(float(stats.get("counts", {}).get(label, 0) or 0) for stats in stats_list) / count
            if avg_value > 0:
                avg_counts[label] = round(avg_value, 2)

        merged = {
            "source_count": int(count),
            "csv_names": [Path(path).name for path in csv_paths],
            "n_total": round(sum(float(stats.get("n_total", 0) or 0) for stats in stats_list) / count, 2),
            "n_mm2": round(sum(float(stats.get("n_mm2", 0) or 0) for stats in stats_list) / count, 2),
            "nodularidad": round(sum(float(stats.get("nodularidad", 0) or 0) for stats in stats_list) / count, 2),
            "vermicular": round(sum(float(stats.get("vermicular", 0) or 0) for stats in stats_list) / count, 2),
            "diam_prom_um": round(sum(float(stats.get("diam_prom_um", 0) or 0) for stats in stats_list) / count, 2),
            "diam_max_um": round(sum(float(stats.get("diam_max_um", 0) or 0) for stats in stats_list) / count, 2),
            "diam_min_um": round(sum(float(stats.get("diam_min_um", 0) or 0) for stats in stats_list) / count, 2),
            "counts": avg_counts,
        }
        merged["tam_grafito_clase"] = self._imagej_majority_size_text(avg_counts)
        return merged

    def _create_imagej_distribution_chart(self, stats, csv_label):
        try:
            import matplotlib
            matplotlib.use("Agg", force=True)
            import matplotlib.pyplot as plt
        except Exception:
            return None

        counts = stats.get("counts", {})
        labels = [label for label, _, _ in IMAGEJ_LIMITS if counts.get(label, 0)]
        values = [counts.get(label, 0) for label in labels]
        if counts.get("Fuera de clase", 0):
            labels.append("Fuera de clase")
            values.append(counts.get("Fuera de clase", 0))
        if not labels:
            return None

        dest = Path(ensure_quality_images_dir()) / f"imagej_distribucion_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex}.png"
        fig, ax = plt.subplots(figsize=(7, 4.2))
        ax.bar(labels, values, color="#2f6f9f")
        if int(stats.get("source_count", 1) or 1) > 1:
            ax.set_title("Distribucion promedio de nodulos por clase")
        else:
            ax.set_title("Distribucion de nodulos por clase")
        ax.set_ylabel("Cantidad")
        ax.tick_params(axis="x", labelrotation=35)
        fig.tight_layout()
        fig.savefig(dest, dpi=150)
        plt.close(fig)
        chart_label = str(csv_label or "").strip() or "ImageJ"
        return {
            "id": uuid.uuid4().hex,
            "nombre": f"Distribucion {chart_label}.png",
            "path": str(dest),
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _attach_imagej_file(self, path):
        if not path:
            return None
        item = self._copy_image_attachment(path)
        self._report_images.append(item)
        return item

    def _import_imagej_analysis(self):
        if self._selected_group is not None and self._selected_index is None:
            messagebox.showinfo("Calidad", "Selecciona un material del grupo para cargar el analisis ImageJ.", parent=self)
            return

        csv_paths = filedialog.askopenfilenames(
            parent=self,
            title="Seleccionar CSV de ImageJ",
            filetypes=(("CSV de ImageJ", "*.csv"), ("Todos los archivos", "*.*")),
        )
        csv_paths = [str(path) for path in csv_paths if str(path).strip()]
        if not csv_paths:
            return
        img_path = filedialog.askopenfilename(
            parent=self,
            title="Seleccionar imagen de muestra (opcional)",
            filetypes=(("Imagenes", "*.png *.jpg *.jpeg *.bmp *.gif *.webp"), ("Todos los archivos", "*.*")),
        )

        try:
            stats_list = [self._calculate_imagej_stats(path) for path in csv_paths]
            stats = self._merge_imagej_stats(stats_list, csv_paths)
        except Exception as ex:
            messagebox.showerror("ImageJ", f"No se pudo analizar el/los CSV.\n\n{ex}", parent=self)
            return

        self._prompt_quality_value_if_empty(self.var_ce_final, "Carbono equivalente", "CE:")
        self._prompt_quality_value_if_empty(self.var_c_final, "Carbono total", "C (%):")
        self._prompt_quality_value_if_empty(self.var_si_final, "Silicio", "Si (%):")

        is_nodular = self._family_for_material(self.var_material.get()) == "Nodular"
        nodule_count_value = IMAGEJ_NODULAR_DEFAULT_NODULES if is_nodular else self._format_metric(stats["n_mm2"], 2)
        self.var_conteo_nodulos.set(nodule_count_value)
        self.var_pct_nod.set(self._format_metric(stats["nodularidad"], 2))
        self.var_tam_grafito.set(stats.get("tam_grafito_clase", ""))
        if not is_nodular:
            self.var_morfologia.set(
                f"Nodular {self._format_metric(stats['nodularidad'], 2)}% / "
                f"Vermicular {self._format_metric(stats['vermicular'], 2)}%"
            )

        attached_ids = []
        errors = []
        if img_path:
            try:
                item = self._attach_imagej_file(img_path)
                if item:
                    attached_ids.append(item["id"])
            except Exception as ex:
                errors.append(f"Imagen de muestra: {ex}")
        try:
            chart_label = (
                f"ImageJ promedio {len(csv_paths)} CSV"
                if len(csv_paths) > 1
                else f"ImageJ {Path(csv_paths[0]).stem}"
            )
            chart = self._create_imagej_distribution_chart(stats, chart_label)
            if chart:
                self._report_images.append(chart)
                attached_ids.append(chart["id"])
        except Exception as ex:
            errors.append(f"Grafico de distribucion: {ex}")

        multiple = len(csv_paths) > 1
        csv_names = [Path(path).name for path in csv_paths]
        counts_lines = [
            f"- {category}: {self._format_metric(count, 2) if multiple else int(round(float(count)))}"
            for category, count in stats["counts"].items()
            if count
        ]
        csv_text = ", ".join(csv_names[:6])
        if len(csv_names) > 6:
            csv_text += f", +{len(csv_names) - 6} mas"
        self._append_observation_block(
            "Analisis ImageJ",
            [
                f"CSV analizados: {len(csv_paths)}" if multiple else f"CSV: {csv_names[0]}",
                f"Archivos: {csv_text}" if multiple else "",
                f"Imagen: {Path(img_path).name if img_path else 'sin imagen adjunta'}",
                f"Area minima considerada: {IMAGEJ_AREA_UMBRAL} px",
                f"Nodulos totales promedio: {self._format_metric(stats['n_total'], 2)}" if multiple else f"Nodulos totales: {int(round(float(stats['n_total'])))}",
                f"Nodulos/mm2 promedio: {self._format_metric(stats['n_mm2'], 2)}" if multiple else f"Nodulos/mm2: {self._format_metric(stats['n_mm2'], 2)}",
                f"Nodulos/mm2 informado: {nodule_count_value}" if is_nodular else "",
                f"Nodularidad promedio: {self._format_metric(stats['nodularidad'], 2)}%" if multiple else f"Nodularidad: {self._format_metric(stats['nodularidad'], 2)}%",
                f"Vermiculares promedio: {self._format_metric(stats['vermicular'], 2)}%" if multiple else f"Vermiculares: {self._format_metric(stats['vermicular'], 2)}%",
                f"Tamano grafito por clase predominante: {stats.get('tam_grafito_clase', '')}",
                f"Diametro promedio tecnico: {self._format_metric(stats['diam_prom_um'], 2)} um",
                (
                    f"Max promedio: {self._format_metric(stats['diam_max_um'], 2)} um - Min promedio: {self._format_metric(stats['diam_min_um'], 2)} um"
                    if multiple
                    else f"Max: {self._format_metric(stats['diam_max_um'], 2)} um - Min: {self._format_metric(stats['diam_min_um'], 2)} um"
                ),
                "Distribucion promedio por clase:" if multiple else "Distribucion por clase:",
                *counts_lines,
            ],
        )

        self._report_images = self._normalize_report_images(self._report_images)
        self._refresh_images_ui()
        if attached_ids:
            try:
                self.images_tree.selection_set(attached_ids[-1])
                self.images_tree.focus(attached_ids[-1])
                self._update_image_preview()
            except Exception:
                pass
        if attached_ids:
            self._images_changed()
        if errors:
            messagebox.showwarning("ImageJ", "El analisis se cargo, pero hubo avisos:\n\n" + "\n".join(errors), parent=self)
        else:
            messagebox.showinfo("ImageJ", "Analisis ImageJ cargado en el informe.", parent=self)

    def _image_file_uri(self, path):
        try:
            p = Path(str(path or "")).resolve()
            if not p.exists():
                return ""
            return p.as_uri()
        except Exception:
            return ""

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
        clean["imagenes"] = self._normalize_report_images(clean.get("imagenes", []))
        return clean

    def _baseline_from_report(self, report):
        if report.get("_draft_pending") and isinstance(report.get("_draft_base"), dict):
            return self._normalize_report_payload(report.get("_draft_base"))
        return self._normalize_report_payload(report)

    def _current_form_payload(self):
        return self._normalize_report_payload(self._build_report_from_form(pending=False))

    def _fundiciones_report_payload(self):
        if self._selected_group is not None and self._selected_index is None:
            messagebox.showinfo("Fundiciones", "Selecciona un material del grupo para enviar ese informe.", parent=self)
            return None
        report = self._current_form_payload()
        if not str(report.get("lote", "") or "").strip():
            messagebox.showinfo("Fundiciones", "Completa el lote / colada antes de enviar.", parent=self)
            return None
        if not str(report.get("material", "") or "").strip():
            messagebox.showinfo("Fundiciones", "Completa el material antes de enviar.", parent=self)
            return None
        return report

    def _fundiciones_graphite_text(self, report):
        family = self._family_for_report(report)
        if family == "Nodular":
            parts = ["Nodular"]
            pct = str(report.get("pct_nodularizacion", "") or "").strip()
            count = str(report.get("conteo_nodulos", "") or "").strip()
            tam = str(report.get("tam_grafito", "") or "").strip()
            if pct:
                parts[0] = f"Nodular {pct}%"
            if count:
                parts.append(f"nod/mm2 {count}")
            if tam:
                parts.append(f"tam {tam}")
            return " - ".join(parts)
        parts = [
            str(report.get("morfologia", "") or "").strip(),
            str(report.get("tipo_grafito", "") or "").strip(),
            str(report.get("tam_grafito", "") or "").strip(),
        ]
        return " - ".join(part for part in parts if part)

    def _fundiciones_graphite_combo_text(self, report):
        family = self._family_for_report(report)
        if family == "Nodular":
            return "Nodular"
        return "Laminar"

    def _fundiciones_graphite_type_text(self, report):
        if self._family_for_report(report) == "Nodular":
            return ""
        raw = str(report.get("tipo_grafito", "") or "").strip()
        if not raw:
            return ""

        allowed = {"A", "A-B", "A85/B15", "A80/B20", "A90/B10", "A90", "A90/C10", "A95/B05", "A95/C05"}
        compact = (
            raw.upper()
            .replace(" ", "")
            .replace("%", "")
            .replace('"', "")
            .replace("'", "")
            .replace("TIPO", "")
            .replace(":", "")
        )
        if compact in allowed:
            return compact
        if compact == "A100":
            return "A"
        if compact in {"AB", "A/B"}:
            return "A-B"

        pairs = re.findall(r"([ABC])\s*[:\-]?\s*(\d+(?:[,.]\d+)?)", raw.upper())
        if len(pairs) >= 2:
            first_letter, first_value = pairs[0]
            second_letter, second_value = pairs[1]
            first_num = int(round(float(first_value.replace(",", "."))))
            second_num = int(round(float(second_value.replace(",", "."))))
            candidate = f"{first_letter}{first_num}/{second_letter}{second_num:02d}"
            if candidate in allowed:
                return candidate
            return candidate
        if len(pairs) == 1:
            letter, value = pairs[0]
            number = int(round(float(value.replace(",", "."))))
            if letter == "A" and number == 100:
                return "A"
            candidate = f"{letter}{number}"
            if candidate in allowed:
                return candidate
            return candidate
        return raw

    def _fundiciones_nodular_density_values(self, report):
        raw = str(report.get("conteo_nodulos", "") or "").strip()
        if not raw:
            return "", ""
        numbers = re.findall(r"\d+(?:[,.]\d+)?", raw)
        if not numbers:
            return raw, raw

        def clean(value):
            numeric = self._parse_optional_float(value)
            if numeric is None:
                digits = re.sub(r"\D", "", str(value))
                if not digits:
                    return ""
                numeric = float(digits)
            # Si viene como 55099 por un decimal perdido, Access debe recibir 551, no 55099.
            if numeric > 5000:
                numeric = numeric / 100.0
            return int(round(numeric))

        if len(numbers) >= 2:
            return clean(numbers[0]), clean(numbers[1])
        value = clean(numbers[0])
        return value, value

    def _fundiciones_graphite_detail_text(self, report):
        family = self._family_for_report(report)
        if family == "Nodular":
            return self._fundiciones_graphite_text(report)
        morfologia = str(report.get("morfologia", "") or "").strip()
        tipo = str(report.get("tipo_grafito", "") or "").strip()
        if tipo:
            tipo = re.sub(r"\b([AB])\s+(\d+(?:[,.]\d+)?%)", r'"\1": \2', tipo)
            return f"{morfologia} Tipo {tipo}".strip()
        return morfologia

    def _printed_graphite_text(self, report):
        family = self._family_for_report(report)
        if family == "Nodular":
            count_nod = str(report.get("conteo_nodulos", "") or "").strip()
            text = "Nodular"
            if count_nod:
                text += f"    nodulos/mm2 = {count_nod}"
            return text
        return str(report.get("tipo_grafito", "") or report.get("morfologia", "") or "").strip()

    def _fundiciones_structure_text(self, report):
        parts = []
        matriz = str(report.get("matriz", "") or "").strip()
        if matriz:
            parts.append(matriz)
        for label, key in (("Perlita", "perlita"), ("Ferrita", "ferrita"), ("Cementita", "cementita")):
            value = str(report.get(key, "") or "").strip()
            if value:
                parts.append(f"{label} {value}%")
        return " - ".join(parts)

    def _fundiciones_observations_text(self, report):
        parts = []
        seccion = str(report.get("seccion", "") or "").strip()
        datos = str(report.get("datos", "") or "").strip()
        if seccion:
            parts.append(f"Seccion: {seccion}")
        if datos:
            parts.append(datos)
        text = " | ".join(part.replace("\r", " ").replace("\n", " ") for part in parts if part)
        return text[:255]

    def _fundiciones_access_short_text(self, text, max_chars):
        clean = " ".join(str(text or "").replace("\r", " ").replace("\n", " ").split())
        if len(clean) <= max_chars:
            return clean
        return clean[:max_chars].rstrip(" .,;:-") + "..."

    def _fundiciones_report_observation_access_text(self, report):
        return "--"

    def _fundiciones_matrix_key(self, report):
        matriz = str(report.get("matriz", "") or "").strip().lower()
        matriz = matriz.replace("í", "i").replace("á", "a").replace("é", "e").replace("ó", "o").replace("ú", "u")
        if matriz.startswith("ferr"):
            return "ferrita"
        if matriz.startswith("perl"):
            return "perlita"

        perlita = self._parse_optional_float(report.get("perlita", ""))
        ferrita = self._parse_optional_float(report.get("ferrita", ""))
        if perlita is None and ferrita is None:
            return ""
        if ferrita is None:
            return "perlita"
        if perlita is None:
            return "ferrita"
        return "perlita" if perlita >= ferrita else "ferrita"

    def _fundiciones_matrix_combo_text(self, report):
        key = self._fundiciones_matrix_key(report)
        if key == "ferrita":
            return "Ferr."
        if key == "perlita":
            return "Perl."
        return str(report.get("matriz", "") or "").strip()

    def _fundiciones_predominant_matrix_percent(self, report):
        key = self._fundiciones_matrix_key(report)
        if not key:
            return ""
        raw = str(report.get(key, "") or "").strip()
        if not raw:
            return ""
        numeric = self._parse_optional_float(raw.rstrip("%"))
        if numeric is None:
            return raw.rstrip("%").strip()
        return f"{numeric:.0f}"

    def _fundiciones_carbon_equivalent_text(self, report):
        if self._family_for_report(report) == "Nodular":
            return "0.00"
        raw = str(report.get("ce_final", "") or "").strip()
        numeric = self._parse_optional_float(raw.rstrip("%"))
        if numeric is None:
            return raw
        return f"{numeric:.2f}".replace(".", ",") + "%."

    def _fundiciones_carbon_equivalent_access_value(self, report):
        if self._family_for_report(report) == "Nodular":
            return 0.0
        raw = str(report.get("ce_final", "") or "").strip()
        cleaned = raw.replace("%", "").rstrip(".").strip()
        numeric = self._parse_optional_float(cleaned)
        if numeric is None:
            return cleaned
        return round(numeric, 2)

    def _fundiciones_resistance_text(self, report):
        raw = str(report.get("traccion", "") or "").strip()
        numeric = self._parse_optional_float(raw)
        if numeric is None:
            return raw
        return f"{numeric:.0f}" if abs(numeric - round(numeric)) < 1e-9 else fmt(numeric, 2)

    def _fundiciones_elongation_text(self, report):
        raw = str(report.get("alargamiento", "") or "").strip()
        numeric = self._parse_optional_float(raw.rstrip("%"))
        if numeric is None:
            return raw.rstrip("%").strip()
        return f"{numeric:.0f}" if abs(numeric - round(numeric)) < 1e-9 else fmt(numeric, 2)

    def _fundiciones_thickness_text(self, report):
        return str(report.get("seccion", "") or "").strip()

    def _fundiciones_thickness_aliases(self, thickness):
        raw = str(thickness or "").strip()
        nums = re.findall(r"\d+(?:[,.]\d+)?", raw)
        aliases = []
        if len(nums) >= 2:
            a, b = nums[0], nums[1]
            aliases.extend((f"{a}-{b}", f"{a} a {b}", f"{a} {b}", f"{a}/{b}", f"De {a} a {b}"))
        elif len(nums) == 1:
            a = nums[0]
            aliases.extend((a, f"0-{a}", f"Hasta {a}", f"<={a}", f"Menor a {a}"))
        return aliases

    def _fundiciones_hardness_text(self, report):
        raw = str(report.get("dureza", "") or "").strip()
        numeric = self._parse_optional_float(raw)
        if numeric is None:
            return raw
        return f"{numeric:.0f}" if abs(numeric - round(numeric)) < 1e-9 else fmt(numeric, 2)

    def _fundiciones_graphite_size_text(self, report):
        raw = str(report.get("tam_grafito", "") or "").strip()
        if not raw:
            return ""
        if raw in GRAPHITE_SIZE_OPTIONS:
            return raw

        normalized = raw.replace("–", "-").replace("—", "-")
        classes = re.findall(r"Clase\s*(\d+)", normalized, flags=re.IGNORECASE)
        if classes:
            return "-".join(classes[:2])

        pair = re.search(r"\b([1-8])\s*[-/]\s*([1-8])\b", normalized)
        if pair:
            return f"{pair.group(1)}-{pair.group(2)}"

        single = re.search(r"\b([1-8])\b", normalized)
        if single:
            return single.group(1)
        return raw

    def _fundiciones_matrix_display_text(self, report):
        key = self._fundiciones_matrix_key(report)
        pct = self._fundiciones_predominant_matrix_percent(report)
        if key == "ferrita":
            label = "Ferrítica"
        elif key == "perlita":
            label = "Perlítica"
        else:
            label = str(report.get("matriz", "") or "").strip()
        return f"{label} {pct}%".strip() if pct else label

    def _fundiciones_secondary_matrix_text(self, report):
        primary = self._fundiciones_matrix_key(report)
        parts = []
        for label, key in (("Perlita", "perlita"), ("Ferrita", "ferrita"), ("Cementita", "cementita")):
            if key == primary:
                continue
            value = str(report.get(key, "") or "").strip()
            numeric = self._parse_optional_float(value)
            if numeric is not None and abs(numeric) < 1e-9:
                continue
            if value:
                parts.append(f"{label} {value}%")
        return " - ".join(parts)

    def _fundiciones_material_observation_text(self, report):
        primary = self._fundiciones_matrix_key(report)
        if primary not in {"ferrita", "perlita"}:
            return ""
        secondary = "perlita" if primary == "ferrita" else "ferrita"
        label = "Perlita" if secondary == "perlita" else "Ferrita"
        raw = str(report.get(secondary, "") or "").strip()
        if not raw:
            return ""
        numeric = self._parse_optional_float(raw.rstrip("%"))
        if numeric is not None:
            if abs(numeric) < 1e-9:
                return ""
            value = f"{numeric:.0f}" if abs(numeric - round(numeric)) < 1e-9 else fmt(numeric, 2)
        else:
            value = raw.rstrip("%").strip()
        if not value:
            return ""
        return f"{label} {value}%"

    def _fundiciones_access_date(self, report):
        raw = str(report.get("fecha", "") or "").strip()
        if not raw:
            return ""
        for fmt_text in ("%Y-%m-%d", "%d/%m/%Y", "%d-%m-%Y", "%d/%m/%y", "%d-%m-%y"):
            try:
                dt = datetime.strptime(raw, fmt_text)
                months = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
                return f"{dt.day:02d}-{months[dt.month - 1]}.-{dt.strftime('%y')}"
            except ValueError:
                pass
        return raw

    def _fundiciones_cod_fundicion(self, report):
        raw = str(report.get("lote", "") or "").strip()
        match = re.search(r"(\d+)\s*/\s*(\d{2})", raw)
        if match:
            return f"{int(match.group(1)):04d}{match.group(2)}"

        numbers = re.findall(r"\d+", raw)
        if len(numbers) >= 2 and len(numbers[1]) == 2:
            return f"{int(numbers[0]):04d}{numbers[1]}"
        if not numbers:
            return raw

        digits = numbers[0]
        if len(digits) == 6:
            return digits
        current_yy = datetime.now().strftime("%y")
        if len(digits) > 2 and digits.endswith(current_yy):
            return f"{int(digits[:-2]):04d}{digits[-2:]}"
        if len(digits) <= 4:
            return f"{int(digits):04d}{current_yy}"
        return f"{int(digits[:-2]):04d}{digits[-2:]}"

    def _fundiciones_colada_code_from_report(self, report):
        code = self._fundiciones_cod_fundicion(report)
        return str(code or "").strip()

    def _fundiciones_fields(self, report):
        return self._fundiciones_control_values(report)

    def _fundiciones_control_values(self, report):
        material = str(report.get("material", "") or "").strip()
        resistencia = str(report.get("traccion", "") or "").strip()
        alargamiento = str(report.get("alargamiento", "") or "").strip()
        observaciones = self._fundiciones_observations_text(report) or "--"
        report_obs_access = self._fundiciones_report_observation_access_text(report)
        density_min, density_max = self._fundiciones_nodular_density_values(report)
        ce_text = self._fundiciones_carbon_equivalent_text(report)
        resistance_text = self._fundiciones_resistance_text(report)
        elongation_text = self._fundiciones_elongation_text(report) if self._family_for_report(report) == "Nodular" else ""
        material_obs = self._fundiciones_material_observation_text(report)
        thickness_text = self._fundiciones_thickness_text(report)
        hardness_text = self._fundiciones_hardness_text(report)
        graphite_size_text = self._fundiciones_graphite_size_text(report)
        values = {
            "CódFundición": self._fundiciones_cod_fundicion(report),
            "cmbElegirFundición": self._fundiciones_cod_fundicion(report),
            "TxtCódFundición": self._fundiciones_cod_fundicion(report),
            "cmbCódMaterial": material,
            "InformesMateriales.CódMaterial": material,
            "txtCódRespInforme": FUNDICIONES_DEFAULT_RESP_CODE,
            "cmbNomRespInforme": FUNDICIONES_DEFAULT_RESP_CODE,
            "Responsable Informes": FUNDICIONES_DEFAULT_RESP_NAME,
            "txtCódVBInforme": "",
            "cmbNomVBInforme": "",
            "V°B° Informe": "",
            "cmbMorfologíaGrafito": self._fundiciones_graphite_combo_text(report),
            "cmbTipoMorfologíaGrafito": self._fundiciones_graphite_type_text(report),
            "TipoGrafito": str(report.get("tipo_grafito", "") or "").strip(),
            "Densidad (nód./mm²)": str(report.get("conteo_nodulos", "") or "").strip(),
            "txtDensidadMínima": density_min,
            "txtDensidadMáxima": density_max,
            "&MorfologíaGrafito": self._fundiciones_graphite_detail_text(report),
            "cmbMatriz": self._fundiciones_matrix_combo_text(report),
            "cmbPorcentajeMatrizPredominante": self._fundiciones_predominant_matrix_percent(report),
            "Matriz": self._fundiciones_matrix_display_text(report),
            "txtCarbonoEquivalente": ce_text,
            "txtValorResistencia": resistance_text,
            "txtValorAlargamiento": elongation_text,
            "Alarg. (%)": alargamiento,
            "Resistencia": f"{resistencia} Kg/mm²" if resistencia else "",
            "Alargamiento": alargamiento or "--",
            "ObservacionesInforme": observaciones,
            "txtObservacionesInforme": report_obs_access,
            "ObservacionesMaterial": material_obs,
            "txtObservacionesMaterial": material_obs,
            "cmbEspesor": thickness_text,
            "txtValorDureza": hardness_text,
            "txtDureza": hardness_text,
            "cmbTamañoGrafito": graphite_size_text,
            "txtTamañoGrafito": graphite_size_text,
            "FechaCarga": self._fundiciones_access_date(report),
            "txtFechaAprobación": "",
            "txtFechaAprobInfMat": "",
        }
        return [(name, values.get(name, "")) for name in FUNDICIONES_EXACT_CONTROL_NAMES]

    def _clipboard_set(self, text):
        root = self.winfo_toplevel()
        root.clipboard_clear()
        root.clipboard_append(str(text or ""))
        root.update()

    def _fundiciones_row_text(self, fields):
        return "\t".join(str(value or "").replace("\r", " ").replace("\n", " ") for _, value in fields)

    def _copy_fundiciones_row(self, fields):
        self._clipboard_set(self._fundiciones_row_text(fields))
        messagebox.showinfo("Fundiciones", "Fila copiada al portapapeles.", parent=self)

    def _ensure_fundiciones_drive(self):
        if os.path.exists(FUNDICIONES_MAPPED_BACKEND_PATH):
            return True
        try:
            subprocess.run(
                ["net", "use", "M:", FUNDICIONES_DRIVE_ROOT, "/persistent:no"],
                check=False,
                capture_output=True,
                text=True,
                timeout=8,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception:
            pass
        return os.path.exists(FUNDICIONES_MAPPED_BACKEND_PATH)

    def _prompt_fundiciones_credentials(self):
        return FUNDICIONES_DEFAULT_USER, FUNDICIONES_DEFAULT_PASSWORD

    def _fundiciones_debug(self, message):
        try:
            stamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{stamp}][Fundiciones] {message}", flush=True)
        except Exception:
            pass

    def _focus_fundiciones_form_control(self, form_name, control_name):
        self._fundiciones_debug(f"SetFocus solicitado: {form_name}.{control_name}")
        try:
            if self._access_modal_dialog_open():
                self._fundiciones_debug("SetFocus cancelado: Access tiene aviso modal abierto")
                self._set_fundiciones_test_status("Access tiene un aviso abierto.")
                return False
            if not self._activate_fundiciones_window():
                self._fundiciones_debug("SetFocus cancelado: no encontre ventana Fundiciones")
                self._set_fundiciones_test_status("No encontre la ventana de Fundiciones.")
                return False
            import win32com.client
            app = win32com.client.GetActiveObject("Access.Application")
            app.Forms.Item(form_name).Controls.Item(control_name).SetFocus()
            self._fundiciones_debug(f"SetFocus OK: {form_name}.{control_name}")
            self._set_fundiciones_test_status(f"OK SetFocus: {form_name}.{control_name}")
            return True
        except Exception as ex:
            self._fundiciones_debug(f"SetFocus ERROR: {form_name}.{control_name}: {ex}")
            self._log_fundiciones_error("_focus_fundiciones_form_control", f"{form_name}.{control_name}: {ex}")
            self._set_fundiciones_test_status(f"No funciono: {form_name}.{control_name}")
            return False

    def _fundiciones_form(self):
        self._fundiciones_debug(f"Buscando formulario: {FUNDICIONES_TARGET_FORM}")
        try:
            if self._access_modal_dialog_open():
                self._fundiciones_debug("Formulario cancelado: Access tiene aviso modal abierto")
                self._set_fundiciones_test_status("Access tiene un aviso abierto.")
                return None
            if not self._activate_fundiciones_window():
                self._fundiciones_debug("Formulario cancelado: no encontre ventana Fundiciones")
                self._set_fundiciones_test_status("No encontre la ventana de Fundiciones.")
                return None
            import win32com.client
            app = win32com.client.GetActiveObject("Access.Application")
            form = app.Forms.Item(FUNDICIONES_TARGET_FORM)
            self._fundiciones_debug(f"Formulario OK: {FUNDICIONES_TARGET_FORM}")
            return form
        except Exception as ex:
            self._fundiciones_debug(f"Formulario ERROR: {FUNDICIONES_TARGET_FORM}: {ex}")
            self._log_fundiciones_error("_fundiciones_form", ex)
            self._set_fundiciones_test_status(f"No esta abierto {FUNDICIONES_TARGET_FORM}.")
            return None

    def _fundiciones_control(self, form, control_name):
        try:
            form_name = form.Name
        except Exception:
            form_name = FUNDICIONES_TARGET_FORM
        self._fundiciones_debug(f"Buscando control: {form_name}.{control_name}")
        try:
            control = form.Controls.Item(control_name)
            self._fundiciones_debug(f"Control OK: {form_name}.{control_name}")
            return control
        except Exception as ex:
            self._fundiciones_debug(f"Control ERROR: {form_name}.{control_name}: {ex}")
            self._log_fundiciones_error("_fundiciones_control", f"{form_name}.{control_name}: {ex}")
            self._set_fundiciones_test_status(f"No existe {form_name}.{control_name}.")
            return None

    def _fundiciones_control_any(self, form, control_names):
        for control_name in control_names:
            control = self._fundiciones_control(form, control_name)
            if control is not None:
                return control, control_name
        return None, ""

    def _fundiciones_materials_subform(self, form):
        self._fundiciones_debug(f"Entrando a subformulario: {FUNDICIONES_MATERIALS_SUBFORM}")
        control = self._fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
        if control is None:
            return None
        try:
            subform = control.Form
            self._fundiciones_debug(f"Subformulario OK: {FUNDICIONES_MATERIALS_SUBFORM}")
            return subform
        except Exception as ex:
            self._fundiciones_debug(f"Subformulario ERROR: {FUNDICIONES_MATERIALS_SUBFORM}: {ex}")
            self._log_fundiciones_error("_fundiciones_materials_subform", ex)
            self._set_fundiciones_test_status(f"No pude entrar a {FUNDICIONES_MATERIALS_SUBFORM}.")
            return None

    def _fundiciones_thickness_subform(self, materials_subform):
        self._fundiciones_debug(f"Entrando a subformulario: {FUNDICIONES_THICKNESS_SUBFORM}")
        control = self._fundiciones_control(materials_subform, FUNDICIONES_THICKNESS_SUBFORM)
        if control is None:
            return None
        try:
            try:
                control.SetFocus()
                self._fundiciones_debug(f"SetFocus OK: {FUNDICIONES_THICKNESS_SUBFORM}")
            except Exception as focus_ex:
                self._fundiciones_debug(f"SetFocus omitido para {FUNDICIONES_THICKNESS_SUBFORM}: {focus_ex}")
            subform = control.Form
            try:
                subform.Requery()
                self._fundiciones_debug(f"Requery OK: {FUNDICIONES_THICKNESS_SUBFORM}")
            except Exception as requery_ex:
                self._fundiciones_debug(f"Requery omitido para {FUNDICIONES_THICKNESS_SUBFORM}: {requery_ex}")
            self._fundiciones_debug(f"Subformulario OK: {FUNDICIONES_THICKNESS_SUBFORM}")
            return subform
        except Exception as ex:
            self._fundiciones_debug(f"Subformulario ERROR: {FUNDICIONES_THICKNESS_SUBFORM}: {ex}")
            self._log_fundiciones_error("_fundiciones_thickness_subform", ex)
            self._set_fundiciones_test_status(f"No pude entrar a {FUNDICIONES_THICKNESS_SUBFORM}.")
            return None

    def _fundiciones_combo_targets(self, display_text, aliases=None):
        values = [str(display_text or "").strip()]
        values.extend(str(alias or "").strip() for alias in (aliases or ()))
        return _unique_keep_order([value for value in values if value])

    def _fundiciones_combo_norm(self, text):
        raw = str(text or "").strip().casefold()
        raw = raw.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
        raw = raw.replace("ñ", "n")
        return re.sub(r"[^a-z0-9]+", "", raw)

    def _fundiciones_combo_number_key(self, text):
        nums = re.findall(r"\d+(?:[,.]\d+)?", str(text or ""))
        cleaned = []
        for num in nums:
            try:
                value = float(num.replace(",", "."))
                cleaned.append(str(int(value)) if abs(value - round(value)) < 1e-9 else str(value))
            except Exception:
                cleaned.append(num)
        return tuple(cleaned)

    def _fundiciones_combo_bound_value(self, combo, display_text, aliases=None):
        target_texts = self._fundiciones_combo_targets(display_text, aliases)
        self._fundiciones_debug(f"Resolviendo combo para texto visible: {display_text!r}, alias={target_texts[1:]!r}")
        if not target_texts:
            return ""
        target_exact = {text.casefold() for text in target_texts}
        target_norm = {self._fundiciones_combo_norm(text) for text in target_texts}
        target_numbers = {self._fundiciones_combo_number_key(text) for text in target_texts if self._fundiciones_combo_number_key(text)}
        try:
            bound_index = max(0, int(combo.BoundColumn) - 1)
        except Exception:
            bound_index = 0
        rows = []
        try:
            column_count = max(1, int(combo.ColumnCount))
            list_count = max(0, int(combo.ListCount))
            self._fundiciones_debug(f"Combo columnas={column_count}, filas={list_count}, bound_col={bound_index + 1}")
            for row in range(list_count):
                bound_value = combo.Column(bound_index, row)
                row_values = []
                for col in range(column_count):
                    value = combo.Column(col, row)
                    row_values.append(value)
                    text = str(value or "").strip()
                    if text.casefold() in target_exact:
                        self._fundiciones_debug(
                            f"Combo resuelto: texto={display_text!r}, fila={row}, valor_interno={bound_value!r}"
                        )
                        return bound_value
                    if self._fundiciones_combo_norm(text) in target_norm:
                        self._fundiciones_debug(
                            f"Combo resuelto normalizado: texto={display_text!r}, fila={row}, valor_interno={bound_value!r}, celda={text!r}"
                        )
                        return bound_value
                rows.append((row, bound_value, row_values))
            for row, bound_value, row_values in rows:
                for value in row_values:
                    number_key = self._fundiciones_combo_number_key(value)
                    if number_key and number_key in target_numbers:
                        self._fundiciones_debug(
                            f"Combo resuelto por numeros: texto={display_text!r}, fila={row}, valor_interno={bound_value!r}, celda={value!r}"
                        )
                        return bound_value
        except Exception as ex:
            self._fundiciones_debug(f"Combo ERROR resolviendo {display_text!r}: {ex}")
            self._log_fundiciones_error("_fundiciones_combo_bound_value", ex)
        for row, bound_value, row_values in rows:
            preview = " | ".join(str(value or "") for value in row_values)
            self._fundiciones_debug(f"Combo opcion {row}: bound={bound_value!r}; {preview}")
        self._fundiciones_debug(f"Combo NO resuelto: {display_text!r}")
        return None

    def _fundiciones_assign_control(self, control, control_name, value, enter=True, focus=True):
        self._fundiciones_debug(f"Asignando {control_name} = {value!r}")
        focus_ok = False
        if focus:
            try:
                control.SetFocus()
                focus_ok = True
                self._fundiciones_debug(f"SetFocus OK antes de asignar: {control_name}")
            except Exception as ex:
                self._fundiciones_debug(f"SetFocus omitido para {control_name}: {ex}")
                self._log_fundiciones_error("_fundiciones_assign_control.focus", f"{control_name}: {ex}")
        try:
            control.Value = value
        except Exception as ex:
            self._fundiciones_debug(f"Asignacion ERROR {control_name}: {ex}")
            self._log_fundiciones_error("_fundiciones_assign_control.value", f"{control_name}: {ex}")
            raise
        if enter and focus_ok:
            try:
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
                time.sleep(0.08)
                self._fundiciones_debug(f"Enter confirmacion: {control_name}")
                shell.SendKeys("{ENTER}")
                time.sleep(0.12)
            except Exception as ex:
                self._fundiciones_debug(f"Enter ERROR {control_name}: {ex}")
                self._log_fundiciones_error("_fundiciones_assign_control.enter", f"{control_name}: {ex}")
        elif enter:
            self._fundiciones_debug(f"Enter omitido sin foco valido: {control_name}")
        return True

    def _open_fundiciones_target_form_direct(self):
        self._fundiciones_debug(f"Abrir formulario solicitado: {FUNDICIONES_TARGET_FORM}")
        if self._access_modal_dialog_open():
            self._fundiciones_debug("Abrir formulario cancelado: aviso modal abierto")
            return False
        try:
            try:
                grab = self.grab_current()
                if grab is not None:
                    grab.grab_release()
            except Exception:
                pass
            if not self._activate_fundiciones_window():
                self._fundiciones_debug("Abrir formulario cancelado: no encontre ventana Fundiciones")
                return False
            import win32com.client
            app = win32com.client.GetActiveObject("Access.Application")
            self._fundiciones_debug(f"DoCmd.OpenForm: {FUNDICIONES_TARGET_FORM}")
            app.DoCmd.OpenForm(FUNDICIONES_TARGET_FORM)
            if self._wait_fundiciones_target_form(timeout=4.0):
                self._fundiciones_debug(f"Formulario abierto confirmado: {FUNDICIONES_TARGET_FORM}")
                self._focus_fundiciones_colada_field()
                return True
            self._fundiciones_debug(f"Formulario no aparecio a tiempo: {FUNDICIONES_TARGET_FORM}")
            return False
        except Exception as ex:
            self._fundiciones_debug(f"Abrir formulario ERROR: {FUNDICIONES_TARGET_FORM}: {ex}")
            self._log_fundiciones_error("_open_fundiciones_target_form_direct", ex)
            self._set_fundiciones_test_status(f"No pude abrir {FUNDICIONES_TARGET_FORM}: {ex}")
            return False

    def _wait_fundiciones_target_form(self, timeout=4.0):
        self._fundiciones_debug(f"Esperando formulario {FUNDICIONES_TARGET_FORM} hasta {timeout:.1f}s")
        deadline = time.time() + timeout
        while time.time() < deadline:
            if self._fundiciones_target_form_is_open():
                self._fundiciones_debug(f"Formulario detectado: {FUNDICIONES_TARGET_FORM}")
                return True
            try:
                self.update_idletasks()
            except Exception:
                pass
            time.sleep(0.25)
        self._fundiciones_debug(f"Timeout esperando formulario: {FUNDICIONES_TARGET_FORM}")
        return False

    def _open_fundiciones_target_form_retry(self, report=None, enter_colada=True, attempt=0, review=False):
        self._fundiciones_debug(f"Reintento abrir formulario: intento={attempt}, enter_colada={enter_colada}, review={review}")
        if self._open_fundiciones_target_form():
            if review:
                self._review_current_report_in_access(report)
            elif enter_colada:
                self._enter_fundiciones_colada(report)
            return
        if attempt < 8:
            self.after(1000, lambda: self._open_fundiciones_target_form_retry(report, enter_colada, attempt + 1, review))

    def _fundiciones_target_form_is_open(self):
        try:
            import win32com.client
            app = win32com.client.GetActiveObject("Access.Application")
            app.Forms.Item(FUNDICIONES_TARGET_FORM)
            return True
        except Exception:
            return False

    def _focus_fundiciones_colada_field(self):
        self._fundiciones_debug(f"Foco colada solicitado: {FUNDICIONES_COLADA_CONTROL}")
        if not self._fundiciones_target_form_is_open():
            self._fundiciones_debug(f"Foco colada cancelado: no esta {FUNDICIONES_TARGET_FORM}")
            self._set_fundiciones_test_status(f"Todavia no esta abierto {FUNDICIONES_TARGET_FORM}.")
            return False
        return self._focus_fundiciones_form_control(FUNDICIONES_TARGET_FORM, FUNDICIONES_COLADA_CONTROL)

    def _select_fundiciones_colada(self, report=None):
        self._fundiciones_debug("Inicio paso colada")
        if report is None:
            report = self._current_form_payload()
        code = self._fundiciones_colada_code_from_report(report)
        self._fundiciones_debug(f"Colada calculada formato Access: {code!r}")
        if not code:
            self._set_fundiciones_test_status("No hay numero de colada para ingresar.")
            return False
        if not self._focus_fundiciones_colada_field():
            return False
        try:
            form = self._fundiciones_form()
            if form is None:
                return False
            colada_control = self._fundiciones_control(form, FUNDICIONES_COLADA_CONTROL)
            current_colada_control = self._fundiciones_control(form, "TxtCódFundición")
            if colada_control is None or current_colada_control is None:
                return False
            self._fundiciones_debug(f"Asignando {FUNDICIONES_COLADA_CONTROL} = {code!r}")
            colada_control.Value = code
            safe_code = code.replace('"', '""')
            rs = form.RecordsetClone
            self._fundiciones_debug(f"Buscando RecordsetClone: [CódFundición] = {code!r}")
            rs.FindFirst(f'[CódFundición] = "{safe_code}"')
            if bool(rs.NoMatch):
                self._fundiciones_debug(f"Colada NO encontrada: {code!r}")
                self._set_fundiciones_test_status(f"No encontre la colada: {code}")
                return False
            self._fundiciones_debug(f"Colada encontrada, moviendo Bookmark: {code!r}")
            form.Bookmark = rs.Bookmark
            self._fundiciones_debug(f"Limpiando {FUNDICIONES_COLADA_CONTROL}")
            colada_control.Value = None
            self._fundiciones_debug("SetFocus: TxtCódFundición")
            current_colada_control.SetFocus()
            self._set_fundiciones_test_status(f"Colada seleccionada: {code}")
            return True
        except Exception as ex:
            self._log_fundiciones_error("_select_fundiciones_colada", ex)
            self._set_fundiciones_test_status(f"No pude ingresar la colada: {code}")
            return False

    def _enter_fundiciones_colada(self, report=None):
        if not self._select_fundiciones_colada(report):
            return False
        if not self._enter_fundiciones_responsible():
            return False
        if not self._enter_fundiciones_completion_date():
            return False
        self._enter_fundiciones_material(report)
        return True

    def _enter_fundiciones_responsible(self):
        self._fundiciones_debug("Inicio paso responsable")
        if not self._fundiciones_target_form_is_open():
            self._set_fundiciones_test_status(f"Todavia no esta abierto {FUNDICIONES_TARGET_FORM}.")
            return False
        try:
            form = self._fundiciones_form()
            if form is None:
                return False
            resp_control = self._fundiciones_control(form, FUNDICIONES_RESP_CONTROL)
            if resp_control is None:
                return False
            self._fundiciones_debug(f"Asignando {FUNDICIONES_RESP_CONTROL} = {FUNDICIONES_DEFAULT_RESP_CODE!r}")
            resp_control.Value = FUNDICIONES_DEFAULT_RESP_CODE
            try:
                resp_combo = self._fundiciones_control(form, FUNDICIONES_RESP_COMBO)
                if resp_combo is not None:
                    self._fundiciones_debug(f"Asignando {FUNDICIONES_RESP_COMBO} = {FUNDICIONES_DEFAULT_RESP_CODE!r}")
                    resp_combo.Value = FUNDICIONES_DEFAULT_RESP_CODE
            except Exception as ex:
                self._log_fundiciones_error("_enter_fundiciones_responsible.combo", ex)

            try:
                subform = self._fundiciones_materials_subform(form)
                if subform is not None:
                    rs = subform.RecordsetClone
                    updated = 0
                    if rs.RecordCount > 0:
                        rs.MoveFirst()
                        while not bool(rs.EOF):
                            rs.Edit()
                            rs.Fields.Item("CódRespInformeMaterial").Value = FUNDICIONES_DEFAULT_RESP_CODE
                            rs.Update()
                            updated += 1
                            rs.MoveNext()
                    self._fundiciones_debug(f"Subform responsable actualizado en registros: {updated}")
            except Exception as ex:
                self._log_fundiciones_error("_enter_fundiciones_responsible.subform", ex)

            self._set_fundiciones_test_status(f"Responsable ingresado: {FUNDICIONES_DEFAULT_RESP_CODE}")
            return True
        except Exception as ex:
            self._log_fundiciones_error("_enter_fundiciones_responsible", ex)
            self._set_fundiciones_test_status(f"No pude ingresar responsable: {FUNDICIONES_DEFAULT_RESP_CODE}")
            return False

    def _enter_fundiciones_completion_date(self):
        self._fundiciones_debug("Inicio paso fecha aprobacion informe materiales")
        if not self._fundiciones_target_form_is_open():
            self._set_fundiciones_test_status(f"Todavia no esta abierto {FUNDICIONES_TARGET_FORM}.")
            return False
        try:
            form = self._fundiciones_form()
            if form is None:
                return False
            date_control = self._fundiciones_control(form, FUNDICIONES_APPROVAL_DATE_CONTROL)
            if date_control is None:
                return False
            approval_date = datetime.now().strftime("%d/%m/%Y")
            try:
                date_control.Enabled = True
                date_control.Locked = False
                self._fundiciones_debug(f"Habilitado temporalmente {FUNDICIONES_APPROVAL_DATE_CONTROL}")
            except Exception as ex:
                self._fundiciones_debug(f"No pude habilitar {FUNDICIONES_APPROVAL_DATE_CONTROL}: {ex}")
            self._fundiciones_assign_control(
                date_control,
                FUNDICIONES_APPROVAL_DATE_CONTROL,
                approval_date,
                enter=False,
                focus=False,
            )
            self._set_fundiciones_test_status(f"Fecha de aprobacion ingresada: {approval_date}")
            return True
        except Exception as ex:
            self._fundiciones_debug(f"Fecha aprobacion ERROR: {ex}")
            self._log_fundiciones_error("_enter_fundiciones_completion_date", ex)
            self._set_fundiciones_test_status(f"No pude ingresar {FUNDICIONES_APPROVAL_DATE_CONTROL}.")
            return False

    def _fundiciones_recordset_field_names(self, recordset):
        names = []
        try:
            for idx in range(int(recordset.Fields.Count)):
                names.append(str(recordset.Fields.Item(idx).Name))
        except Exception as ex:
            self._fundiciones_debug(f"No pude listar campos del recordset: {ex}")
        return names

    def _fundiciones_material_field_name(self, recordset):
        names = self._fundiciones_recordset_field_names(recordset)
        folded = {name.casefold(): name for name in names}
        for candidate in FUNDICIONES_MATERIAL_FIELD_CANDIDATES:
            found = folded.get(candidate.casefold())
            if found:
                return found
        for name in names:
            if "códmaterial" in name.casefold() or "codmaterial" in name.casefold():
                return name
        self._fundiciones_debug(f"Campos disponibles material: {', '.join(names)}")
        return ""

    def _fundiciones_find_material_in_recordset(self, recordset, material):
        field_name = self._fundiciones_material_field_name(recordset)
        if not field_name:
            return False
        safe_field = field_name.replace("]", "]]")
        safe_material = str(material or "").replace('"', '""')
        criteria_options = [f'[{safe_field}] = "{safe_material}"']
        if str(material or "").strip().isdigit():
            criteria_options.append(f"[{safe_field}] = {int(str(material).strip())}")
        for criteria in criteria_options:
            try:
                self._fundiciones_debug(f"Buscando material en RecordsetClone: {criteria}")
                recordset.FindFirst(criteria)
                if not bool(recordset.NoMatch):
                    return True
            except Exception as ex:
                self._fundiciones_debug(f"Criterio material fallo {criteria!r}: {ex}")
        return False

    def _fundiciones_current_material_from_recordset(self, materials_subform):
        try:
            field_name = self._fundiciones_material_field_name(materials_subform.Recordset)
            if not field_name:
                return ""
            return str(materials_subform.Recordset.Fields.Item(field_name).Value or "").strip()
        except Exception as ex:
            self._fundiciones_debug(f"No pude leer material actual desde recordset: {ex}")
            return ""

    def _fundiciones_current_material_record_is_empty(self, materials_subform):
        try:
            if bool(materials_subform.NewRecord):
                self._fundiciones_debug("Registro material actual es NewRecord")
                return True
        except Exception:
            pass
        current = self._fundiciones_current_material_from_recordset(materials_subform)
        self._fundiciones_debug(f"Material actual para detectar espacio libre: {current!r}")
        return not current

    def _select_fundiciones_empty_material_record(self, materials_subform):
        self._fundiciones_debug("Buscando espacio libre para cargar informe de material")
        try:
            if self._fundiciones_current_material_record_is_empty(materials_subform):
                self._fundiciones_debug("Uso registro actual: material vacio")
                return True
        except Exception as ex:
            self._fundiciones_debug(f"No pude evaluar registro actual: {ex}")

        try:
            rs = materials_subform.RecordsetClone
            field_name = self._fundiciones_material_field_name(rs)
            if field_name and rs.RecordCount > 0:
                rs.MoveFirst()
                while not bool(rs.EOF):
                    value = str(rs.Fields.Item(field_name).Value or "").strip()
                    if not value:
                        materials_subform.Bookmark = rs.Bookmark
                        self._fundiciones_debug("Registro material vacio encontrado en RecordsetClone")
                        return True
                    rs.MoveNext()
        except Exception as ex:
            self._fundiciones_debug(f"Busqueda de registro material vacio omitida: {ex}")
            self._log_fundiciones_error("_select_fundiciones_empty_material_record.find", ex)

        try:
            import win32com.client
            app = win32com.client.GetActiveObject("Access.Application")
            try:
                materials_subform.SetFocus()
            except Exception as focus_ex:
                self._fundiciones_debug(f"SetFocus subform antes de registro nuevo omitido: {focus_ex}")
            self._fundiciones_debug("No habia registro material vacio; yendo a registro nuevo interno")
            app.DoCmd.GoToRecord(None, None, 5)
            return True
        except Exception as ex:
            self._fundiciones_debug(f"No pude ir a registro nuevo libre de material: {ex}")
            self._log_fundiciones_error("_select_fundiciones_empty_material_record.new", ex)
            self._set_fundiciones_test_status(
                f"No pude navegar a un espacio libre. Usa {FUNDICIONES_MATERIAL_NEXT_CONTROL} y reintenta."
            )
            return False

    def _select_fundiciones_material_record(self, materials_subform, material, create_if_missing=True):
        material = str(material or "").strip()
        if not material:
            return True
        self._fundiciones_debug(f"Seleccionando registro material interno: {material!r}")

        try:
            rs = materials_subform.RecordsetClone
            if rs.RecordCount > 0:
                if self._fundiciones_find_material_in_recordset(rs, material):
                    materials_subform.Bookmark = rs.Bookmark
                    self._fundiciones_debug(f"Registro material encontrado por CódMaterial: {material!r}")
                    return True
        except Exception as ex:
            self._fundiciones_debug(f"Busqueda de material existente omitida: {ex}")
            self._log_fundiciones_error("_select_fundiciones_material_record.find", ex)

        try:
            current = self._fundiciones_current_material_from_recordset(materials_subform)
            self._fundiciones_debug(f"Material actual por recordset antes de navegar: {current!r}")
            if current == material:
                return True
            if create_if_missing and not current:
                return True
        except Exception as ex:
            self._fundiciones_debug(f"No pude leer material actual: {ex}")

        if not create_if_missing:
            self._set_fundiciones_test_status(f"No encontre el material {material} en la colada.")
            return False

        try:
            import win32com.client
            app = win32com.client.GetActiveObject("Access.Application")
            try:
                materials_subform.SetFocus()
            except Exception as focus_ex:
                self._fundiciones_debug(f"SetFocus subform antes de nuevo registro omitido: {focus_ex}")
            self._fundiciones_debug("Material no encontrado; yendo a registro nuevo interno")
            app.DoCmd.GoToRecord(None, None, 5)
            return True
        except Exception as ex:
            self._fundiciones_debug(f"No pude ir a registro nuevo de material: {ex}")
            self._log_fundiciones_error("_select_fundiciones_material_record.new", ex)
            self._set_fundiciones_test_status(
                f"No pude navegar a un espacio libre para material {material}. Usa {FUNDICIONES_MATERIAL_NEXT_CONTROL}."
            )
            return False

    def _focus_fundiciones_materials_subform_control(self, form, subform_control=None, subform=None, control_name=None):
        self._fundiciones_debug(
            f"Enfocando subform material: {FUNDICIONES_MATERIALS_SUBFORM}"
            + (f".{control_name}" if control_name else "")
        )
        if not self._activate_fundiciones_window():
            self._fundiciones_debug("No pude activar ventana para enfocar subform material")
            return None
        if subform_control is None:
            subform_control = self._fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
        if subform is None and subform_control is not None:
            try:
                subform = subform_control.Form
            except Exception as ex:
                self._fundiciones_debug(f"No pude obtener Form del subform material: {ex}")
                return None
        if subform_control is None or subform is None:
            return None
        try:
            subform_control.SetFocus()
            self._fundiciones_debug(f"SetFocus OK contenedor: {FUNDICIONES_MATERIALS_SUBFORM}")
        except Exception as ex:
            self._fundiciones_debug(f"SetFocus contenedor omitido: {FUNDICIONES_MATERIALS_SUBFORM}: {ex}")
        if not control_name:
            return None
        control = self._fundiciones_control(subform, control_name)
        if control is None:
            return None
        try:
            control.SetFocus()
            self._fundiciones_debug(f"SetFocus OK interno: {FUNDICIONES_MATERIALS_SUBFORM}.{control_name}")
        except Exception as ex:
            self._fundiciones_debug(f"SetFocus interno ERROR: {FUNDICIONES_MATERIALS_SUBFORM}.{control_name}: {ex}")
            self._log_fundiciones_error(
                "_focus_fundiciones_materials_subform_control",
                f"{FUNDICIONES_MATERIALS_SUBFORM}.{control_name}: {ex}",
            )
        return control

    def _go_fundiciones_material_record(self, direction="next"):
        self._fundiciones_debug(f"Navegacion material solicitada: {direction}")
        form = self._fundiciones_form()
        if form is None:
            return False
        subform_control = self._fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
        subform = self._fundiciones_materials_subform(form)
        if subform_control is None or subform is None:
            return False
        button_name = FUNDICIONES_MATERIAL_NEXT_CONTROL if direction == "next" else FUNDICIONES_MATERIAL_PREV_CONTROL
        button = self._focus_fundiciones_materials_subform_control(form, subform_control, subform, button_name)
        if button is not None:
            try:
                button.Click()
                self._set_fundiciones_test_status(f"Navegado con {button_name}.")
                return True
            except Exception as ex:
                self._fundiciones_debug(f"Click {button_name} fallo: {ex}")
                self._log_fundiciones_error("_go_fundiciones_material_record.click", ex)
                try:
                    import win32com.client
                    shell = win32com.client.Dispatch("WScript.Shell")
                    shell.SendKeys("{ENTER}")
                    self._set_fundiciones_test_status(f"Navegado con Enter sobre {button_name}.")
                    return True
                except Exception as send_ex:
                    self._fundiciones_debug(f"Enter {button_name} fallo: {send_ex}")
                    self._log_fundiciones_error("_go_fundiciones_material_record.enter", send_ex)
        try:
            import win32com.client
            app = win32com.client.GetActiveObject("Access.Application")
            self._focus_fundiciones_materials_subform_control(form, subform_control, subform, FUNDICIONES_MATERIAL_CONTROL)
            app.DoCmd.GoToRecord(None, None, 1 if direction == "next" else 0)
            self._set_fundiciones_test_status(f"Navegado material {direction}.")
            return True
        except Exception as ex:
            self._fundiciones_debug(f"Navegacion material ERROR: {ex}")
            self._log_fundiciones_error("_go_fundiciones_material_record", ex)
            self._set_fundiciones_test_status(f"No pude navegar material {direction}.")
            return False

    def _focus_fundiciones_material_review_position(self, form, subform_control, subform):
        self._fundiciones_debug("Enfocando posicion de revision de material")
        try:
            if not self._activate_fundiciones_window():
                return False
            try:
                subform_control.SetFocus()
                self._fundiciones_debug(f"SetFocus OK contenedor revision: {FUNDICIONES_MATERIALS_SUBFORM}")
                return True
            except Exception as ex:
                self._fundiciones_debug(f"SetFocus contenedor revision omitido: {ex}")
            for control_name in (
                FUNDICIONES_MATERIAL_NEXT_CONTROL,
                FUNDICIONES_MATERIAL_PREV_CONTROL,
                FUNDICIONES_REPORT_OBS_CONTROL,
                FUNDICIONES_RESISTANCE_CONTROL,
            ):
                control = self._fundiciones_control(subform, control_name)
                if control is None:
                    continue
                try:
                    control.SetFocus()
                    self._fundiciones_debug(f"SetFocus OK revision: {FUNDICIONES_MATERIALS_SUBFORM}.{control_name}")
                    return True
                except Exception as ex:
                    self._fundiciones_debug(f"SetFocus revision omitido {control_name}: {ex}")
            current_colada_control = self._fundiciones_control(form, "TxtCódFundición")
            if current_colada_control is not None:
                try:
                    current_colada_control.SetFocus()
                    self._fundiciones_debug("SetFocus OK fallback revision: TxtCódFundición")
                    return True
                except Exception as ex:
                    self._fundiciones_debug(f"SetFocus fallback TxtCódFundición omitido: {ex}")
            return False
        except Exception as ex:
            self._fundiciones_debug(f"Foco revision material ERROR: {ex}")
            self._log_fundiciones_error("_focus_fundiciones_material_review_position", ex)
            return False

    def _enter_fundiciones_thickness_fields(self, materials_subform, report):
        material = str(report.get("material", "") or "").strip()
        thickness = self._fundiciones_thickness_text(report)
        hardness = self._fundiciones_hardness_text(report)
        graphite_size = self._fundiciones_graphite_size_text(report)
        self._fundiciones_debug(
            "Inicio paso espesores: "
            f"espesor={thickness!r}, dureza={hardness!r}, tam_grafito={graphite_size!r}"
        )
        if not any((thickness, hardness, graphite_size)):
            self._fundiciones_debug("Paso espesores omitido: no hay datos para cargar")
            return True

        self._prepare_fundiciones_thickness_subform(materials_subform, material)
        thickness_subform = self._fundiciones_thickness_subform(materials_subform)
        if thickness_subform is None:
            return False

        if thickness:
            thickness_control = self._fundiciones_control(thickness_subform, FUNDICIONES_THICKNESS_CONTROL)
            if thickness_control is None:
                return False
            thickness_value = self._fundiciones_combo_bound_value(
                thickness_control,
                thickness,
                aliases=self._fundiciones_thickness_aliases(thickness),
            )
            if thickness_value is None:
                self._set_fundiciones_test_status(f"No pude resolver {FUNDICIONES_THICKNESS_CONTROL} = {thickness}.")
                return False
            self._fundiciones_debug(f"{FUNDICIONES_THICKNESS_CONTROL}: visible {thickness!r} -> interno {thickness_value!r}")
            self._fundiciones_assign_control(thickness_control, FUNDICIONES_THICKNESS_CONTROL, thickness_value)

        if hardness:
            hardness_control, hardness_control_name = self._fundiciones_control_any(
                thickness_subform,
                FUNDICIONES_HARDNESS_CONTROL_ALIASES,
            )
            if hardness_control is None:
                return False
            self._fundiciones_assign_control(hardness_control, hardness_control_name, hardness)

        if graphite_size:
            graphite_size_control, graphite_size_control_name = self._fundiciones_control_any(
                thickness_subform,
                FUNDICIONES_GRAPHITE_SIZE_CONTROL_ALIASES,
            )
            if graphite_size_control is None:
                return False
            graphite_size_value = self._fundiciones_combo_bound_value(graphite_size_control, graphite_size)
            if graphite_size_value is None:
                self._set_fundiciones_test_status(
                    f"No pude resolver {graphite_size_control_name} = {graphite_size}."
                )
                return False
            self._fundiciones_debug(
                f"{graphite_size_control_name}: visible {graphite_size!r} -> interno {graphite_size_value!r}"
            )
            self._fundiciones_assign_control(graphite_size_control, graphite_size_control_name, graphite_size_value)

        return True

    def _enter_fundiciones_material_responsible(self, materials_subform):
        self._fundiciones_debug("Inicio paso responsable material")
        try:
            resp_control = self._fundiciones_control(materials_subform, FUNDICIONES_MATERIAL_RESP_CONTROL)
            if resp_control is not None:
                self._fundiciones_assign_control(
                    resp_control,
                    FUNDICIONES_MATERIAL_RESP_CONTROL,
                    FUNDICIONES_DEFAULT_RESP_CODE,
                    enter=False,
                    focus=False,
                )
            resp_combo = self._fundiciones_control(materials_subform, FUNDICIONES_MATERIAL_RESP_COMBO)
            if resp_combo is not None:
                self._fundiciones_assign_control(
                    resp_combo,
                    FUNDICIONES_MATERIAL_RESP_COMBO,
                    FUNDICIONES_DEFAULT_RESP_CODE,
                    enter=False,
                    focus=False,
                )
            return True
        except Exception as ex:
            self._fundiciones_debug(f"Responsable material ERROR: {ex}")
            self._log_fundiciones_error("_enter_fundiciones_material_responsible", ex)
            self._set_fundiciones_test_status(f"No pude ingresar responsable material: {FUNDICIONES_DEFAULT_RESP_CODE}")
            return False

    def _prepare_fundiciones_thickness_subform(self, materials_subform, material):
        self._fundiciones_debug(f"Preparando subform espesores para material={material!r}")
        control = self._fundiciones_control(materials_subform, FUNDICIONES_THICKNESS_SUBFORM)
        if control is None:
            return False
        try:
            control.Enabled = True
            control.Locked = False
            control.Visible = True
        except Exception as ex:
            self._fundiciones_debug(f"No pude habilitar {FUNDICIONES_THICKNESS_SUBFORM}: {ex}")
        try:
            subform = control.Form
            subform.AllowDeletions = True
            if material:
                safe_material = material.replace('"', '""')
                row_source = (
                    "SELECT DISTINCTROW Espesores.[CódEspesor], Espesores.[DefEspesor] "
                    "FROM Espesores INNER JOIN EspesoresPorMaterial "
                    "ON Espesores.[CódEspesor] = EspesoresPorMaterial.[CódEspesor] "
                    f'WHERE (((EspesoresPorMaterial.[CódMaterial])="{safe_material}"));'
                )
                cmb = subform.Controls.Item(FUNDICIONES_THICKNESS_CONTROL)
                cmb.RowSource = row_source
                cmb.Requery()
                self._fundiciones_debug(f"RowSource filtrado {FUNDICIONES_THICKNESS_CONTROL}: material={material!r}")
            subform.Requery()
            return True
        except Exception as ex:
            self._fundiciones_debug(f"Preparar espesores ERROR: {ex}")
            self._log_fundiciones_error("_prepare_fundiciones_thickness_subform", ex)
            return False

    def _save_fundiciones_material_record(self, materials_subform):
        self._fundiciones_debug("Intentando guardar registro de material para habilitar espesores")
        try:
            if bool(materials_subform.Dirty):
                materials_subform.Dirty = False
                self._fundiciones_debug("Registro de material guardado con Dirty=False")
            else:
                self._fundiciones_debug("Registro de material no estaba Dirty")
            return True
        except Exception as ex:
            self._fundiciones_debug(f"Guardar material ERROR: {ex}")
            self._log_fundiciones_error("_save_fundiciones_material_record", ex)
            self._set_fundiciones_test_status(f"No pude guardar material antes de espesores: {ex}")
            return False

    def _enter_fundiciones_material(self, report=None):
        self._fundiciones_debug("Inicio paso subform material/morfologia/matriz")
        if report is None:
            report = self._current_form_payload()
        material = str(report.get("material", "") or "").strip()
        family = self._family_for_report(report)
        graphite = self._fundiciones_graphite_combo_text(report)
        graphite_type = self._fundiciones_graphite_type_text(report)
        density_min, density_max = self._fundiciones_nodular_density_values(report)
        matrix = self._fundiciones_matrix_combo_text(report)
        matrix_percent = self._fundiciones_predominant_matrix_percent(report)
        carbon_equivalent = self._fundiciones_carbon_equivalent_access_value(report)
        resistance = self._fundiciones_resistance_text(report)
        elongation = self._fundiciones_elongation_text(report) if family == "Nodular" else ""
        report_obs = self._fundiciones_report_observation_access_text(report)
        material_obs = self._fundiciones_material_observation_text(report)
        thickness = self._fundiciones_thickness_text(report)
        hardness = self._fundiciones_hardness_text(report)
        graphite_size = self._fundiciones_graphite_size_text(report)
        self._fundiciones_debug(
            "Datos calculados: "
            f"material={material!r}, family={family!r}, graphite={graphite!r}, "
            f"graphite_type={graphite_type!r}, density_min={density_min!r}, "
            f"density_max={density_max!r}, matrix={matrix!r}, matrix_percent={matrix_percent!r}, "
            f"carbon_equivalent={carbon_equivalent!r}, resistance={resistance!r}, elongation={elongation!r}, "
            f"report_obs={report_obs!r}, material_obs={material_obs!r}, thickness={thickness!r}, hardness={hardness!r}, "
            f"graphite_size={graphite_size!r}"
        )
        if not material:
            self._set_fundiciones_test_status("No hay material final para ingresar.")
            return False
        if not self._fundiciones_target_form_is_open():
            self._set_fundiciones_test_status(f"Todavia no esta abierto {FUNDICIONES_TARGET_FORM}.")
            return False
        try:
            form = self._fundiciones_form()
            if form is None:
                return False
            subform_control = self._fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
            subform = self._fundiciones_materials_subform(form)
            if subform_control is None or subform is None:
                return False
            if not self._select_fundiciones_empty_material_record(subform):
                return False
            material_control = self._fundiciones_control(subform, FUNDICIONES_MATERIAL_CONTROL)
            if material_control is None:
                return False
            graphite_control = self._fundiciones_control(subform, FUNDICIONES_GRAPHITE_CONTROL)
            if graphite_control is None:
                return False
            subform_control.SetFocus()
            self._fundiciones_assign_control(material_control, FUNDICIONES_MATERIAL_CONTROL, material)
            graphite_value = self._fundiciones_combo_bound_value(graphite_control, graphite)
            if graphite_value is None:
                self._set_fundiciones_test_status(f"No pude resolver {FUNDICIONES_GRAPHITE_CONTROL} = {graphite}.")
                return False
            self._fundiciones_debug(f"{FUNDICIONES_GRAPHITE_CONTROL}: visible {graphite!r} -> interno {graphite_value!r}")
            self._fundiciones_assign_control(graphite_control, FUNDICIONES_GRAPHITE_CONTROL, graphite_value)
            if family == "Nodular":
                self._fundiciones_debug("Rama especifica: Nodular -> densidades")
                if not density_min or not density_max:
                    self._set_fundiciones_test_status("No hay densidad de nodulos para nodular.")
                    return False
                density_min_control = self._fundiciones_control(subform, FUNDICIONES_DENSITY_MIN_CONTROL)
                density_max_control = self._fundiciones_control(subform, FUNDICIONES_DENSITY_MAX_CONTROL)
                if density_min_control is None or density_max_control is None:
                    return False
                self._fundiciones_assign_control(density_min_control, FUNDICIONES_DENSITY_MIN_CONTROL, density_min)
                self._fundiciones_assign_control(density_max_control, FUNDICIONES_DENSITY_MAX_CONTROL, density_max)
            else:
                self._fundiciones_debug("Rama especifica: Laminar/Gris -> tipo morfologia")
                if not graphite_type:
                    self._set_fundiciones_test_status("No hay tipo de morfologia grafito para gris/laminar.")
                    return False
                graphite_type_control = self._fundiciones_control(subform, FUNDICIONES_GRAPHITE_TYPE_CONTROL)
                if graphite_type_control is None:
                    return False
                graphite_type_value = self._fundiciones_combo_bound_value(graphite_type_control, graphite_type)
                if graphite_type_value is None:
                    self._set_fundiciones_test_status(
                        f"No pude resolver {FUNDICIONES_GRAPHITE_TYPE_CONTROL} = {graphite_type}."
                    )
                    return False
                self._fundiciones_debug(
                    f"{FUNDICIONES_GRAPHITE_TYPE_CONTROL}: visible {graphite_type!r} -> interno {graphite_type_value!r}"
                )
                self._fundiciones_assign_control(graphite_type_control, FUNDICIONES_GRAPHITE_TYPE_CONTROL, graphite_type_value)
            if matrix:
                self._fundiciones_debug("Inicio paso matriz")
                matrix_control = self._fundiciones_control(subform, FUNDICIONES_MATRIX_CONTROL)
                if matrix_control is None:
                    return False
                matrix_value = self._fundiciones_combo_bound_value(matrix_control, matrix)
                if matrix_value is None:
                    self._set_fundiciones_test_status(f"No pude resolver {FUNDICIONES_MATRIX_CONTROL} = {matrix}.")
                    return False
                self._fundiciones_debug(f"{FUNDICIONES_MATRIX_CONTROL}: visible {matrix!r} -> interno {matrix_value!r}")
                self._fundiciones_assign_control(matrix_control, FUNDICIONES_MATRIX_CONTROL, matrix_value)
            if matrix_percent:
                matrix_percent_control = self._fundiciones_control(subform, FUNDICIONES_MATRIX_PERCENT_CONTROL)
                if matrix_percent_control is None:
                    return False
                matrix_percent_value = self._fundiciones_combo_bound_value(matrix_percent_control, matrix_percent)
                if matrix_percent_value is None:
                    self._set_fundiciones_test_status(
                        f"No pude resolver {FUNDICIONES_MATRIX_PERCENT_CONTROL} = {matrix_percent}."
                    )
                    return False
                self._fundiciones_debug(
                    f"{FUNDICIONES_MATRIX_PERCENT_CONTROL}: visible {matrix_percent!r} -> interno {matrix_percent_value!r}"
                )
                self._fundiciones_assign_control(
                    matrix_percent_control,
                    FUNDICIONES_MATRIX_PERCENT_CONTROL,
                    matrix_percent_value,
                )
            if carbon_equivalent not in ("", None):
                ce_control = self._fundiciones_control(subform, FUNDICIONES_CE_CONTROL)
                if ce_control is None:
                    return False
                self._fundiciones_assign_control(ce_control, FUNDICIONES_CE_CONTROL, carbon_equivalent)
            if resistance:
                resistance_control = self._fundiciones_control(subform, FUNDICIONES_RESISTANCE_CONTROL)
                if resistance_control is None:
                    return False
                self._fundiciones_assign_control(resistance_control, FUNDICIONES_RESISTANCE_CONTROL, resistance)
            if family == "Nodular" and elongation:
                elongation_control = self._fundiciones_control(subform, FUNDICIONES_ELONGATION_CONTROL)
                if elongation_control is None:
                    return False
                self._fundiciones_assign_control(elongation_control, FUNDICIONES_ELONGATION_CONTROL, elongation)
            if report_obs:
                report_obs_control = self._fundiciones_control(subform, FUNDICIONES_REPORT_OBS_CONTROL)
                if report_obs_control is None:
                    return False
                self._fundiciones_assign_control(
                    report_obs_control,
                    FUNDICIONES_REPORT_OBS_CONTROL,
                    report_obs,
                    enter=False,
                    focus=False,
                )
            if material_obs:
                material_obs_control = self._fundiciones_control(subform, FUNDICIONES_MATERIAL_OBS_CONTROL)
                if material_obs_control is None:
                    return False
                self._fundiciones_assign_control(material_obs_control, FUNDICIONES_MATERIAL_OBS_CONTROL, material_obs)
            if not self._enter_fundiciones_material_responsible(subform):
                return False
            if not self._save_fundiciones_material_record(subform):
                return False
            if not self._enter_fundiciones_thickness_fields(subform, report):
                return False
            self._set_fundiciones_test_status(
                f"Paso hasta espesores completo: material {material}; grafito {graphite}; matriz {matrix} {matrix_percent}; CE {carbon_equivalent}; R {resistance}"
            )
            return True
        except Exception as ex:
            self._log_fundiciones_error("_enter_fundiciones_material", ex)
            self._set_fundiciones_test_status(f"No pude ingresar material/grafito/matriz: {material}")
            return False

    def _open_fundiciones_target_form(self):
        if self._access_modal_dialog_open():
            messagebox.showwarning(
                "Fundiciones",
                "Access tiene un aviso abierto. Cerralo primero y vuelve a intentar.",
                parent=self,
            )
            return False
        if self._fundiciones_target_form_is_open() and self._focus_fundiciones_colada_field():
            return True
        if self._open_fundiciones_target_form_direct():
            return True
        self._set_fundiciones_test_status(f"No pude abrir {FUNDICIONES_TARGET_FORM}.")
        return False

    def _log_fundiciones_error(self, context, ex):
        try:
            path = Path(tempfile.gettempdir()) / "ajuste_comp_fundiciones_error.log"
            stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            with path.open("a", encoding="utf-8") as fh:
                fh.write(f"[{stamp}] {context}: {repr(ex)}\n")
        except Exception:
            pass

    def _set_fundiciones_test_status(self, text):
        if hasattr(self, "_fundiciones_test_status") and self._fundiciones_test_status is not None:
            try:
                self._fundiciones_test_status.set(text)
            except Exception:
                pass

    def _goto_fundiciones_control(self, control_name):
        try:
            if self._access_modal_dialog_open():
                self._set_fundiciones_test_status("Access tiene un aviso abierto.")
                return False
            if not self._activate_fundiciones_window():
                self._set_fundiciones_test_status("No encontre la ventana de Fundiciones.")
                return False
            import win32com.client
            app = win32com.client.GetActiveObject("Access.Application")
            errors = []
            try:
                app.DoCmd.GoToControl(control_name)
                self._set_fundiciones_test_status(f"OK GoToControl: {control_name}")
                return True
            except Exception as ex:
                errors.append(f"GoToControl: {ex}")
            for form_name in ("frmInicial", "frmCargaInformesFundiciones", "frmCargaInformesMateriales"):
                try:
                    app.Forms.Item(form_name).Controls.Item(control_name).SetFocus()
                    self._set_fundiciones_test_status(f"OK SetFocus: {form_name}.{control_name}")
                    return True
                except Exception as ex:
                    errors.append(f"{form_name}.{control_name}: {ex}")
            try:
                target_form = app.Forms.Item(FUNDICIONES_TARGET_FORM)
                materials_control = target_form.Controls.Item(FUNDICIONES_MATERIALS_SUBFORM)
                materials_control.SetFocus()
                materials_subform = materials_control.Form
                materials_subform.Controls.Item(control_name).SetFocus()
                self._set_fundiciones_test_status(f"OK SetFocus: {FUNDICIONES_MATERIALS_SUBFORM}.{control_name}")
                return True
            except Exception as ex:
                errors.append(f"{FUNDICIONES_MATERIALS_SUBFORM}.{control_name}: {ex}")
            try:
                target_form = app.Forms.Item(FUNDICIONES_TARGET_FORM)
                materials_control = target_form.Controls.Item(FUNDICIONES_MATERIALS_SUBFORM)
                materials_control.SetFocus()
                materials_subform = materials_control.Form
                thickness_control = materials_subform.Controls.Item(FUNDICIONES_THICKNESS_SUBFORM)
                thickness_control.SetFocus()
                thickness_subform = thickness_control.Form
                thickness_subform.Controls.Item(control_name).SetFocus()
                self._set_fundiciones_test_status(f"OK SetFocus: {FUNDICIONES_THICKNESS_SUBFORM}.{control_name}")
                return True
            except Exception as ex:
                errors.append(f"{FUNDICIONES_THICKNESS_SUBFORM}.{control_name}: {ex}")
            try:
                app.Screen.ActiveForm.Controls.Item(control_name).SetFocus()
                self._set_fundiciones_test_status(f"OK ActiveForm.SetFocus: {control_name}")
                return True
            except Exception as ex:
                errors.append(f"ActiveForm.{control_name}: {ex}")
            self._set_fundiciones_test_status(f"No funciono: {control_name}")
            self._log_fundiciones_error("_goto_fundiciones_control", "; ".join(errors[-3:]))
            return False
        except Exception as ex:
            self._log_fundiciones_error("_goto_fundiciones_control", ex)
            self._set_fundiciones_test_status(f"Error: {control_name}")
            return False

    def _paste_fundiciones_by_controls(self):
        report = self._fundiciones_report_payload()
        if report is None:
            return
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
        except Exception as ex:
            self._log_fundiciones_error("_paste_fundiciones_by_controls", ex)
            self._set_fundiciones_test_status(f"No pude iniciar SendKeys: {ex}")
            return

        filled = 0
        skipped = []
        for control_name, value in self._fundiciones_control_values(report):
            text = str(value or "").strip()
            if not text:
                continue
            if not self._goto_fundiciones_control(control_name):
                skipped.append(control_name)
                continue
            self._clipboard_set(text)
            time.sleep(0.08)
            shell.SendKeys("^a")
            time.sleep(0.04)
            shell.SendKeys("^v")
            time.sleep(0.12)
            filled += 1
        status = f"Pegar por controles: {filled} campos"
        if skipped:
            status += f"; fallaron: {', '.join(skipped[:4])}"
        self._set_fundiciones_test_status(status)

    def _detect_fundiciones_active_control(self):
        try:
            if not self._activate_fundiciones_window():
                self._set_fundiciones_test_status("No encontre la ventana de Fundiciones.")
                return
            import win32com.client
            app = win32com.client.GetActiveObject("Access.Application")
            form_name = ""
            control_name = ""
            control_source = ""
            try:
                form_name = app.Screen.ActiveForm.Name
            except Exception:
                form_name = "sin formulario"
            try:
                control = app.Screen.ActiveControl
                control_name = control.Name
                try:
                    control_source = str(control.ControlSource or "")
                except Exception:
                    control_source = ""
            except Exception:
                control_name = "sin control"
            detail = f"Activo: {form_name}.{control_name}"
            if control_source:
                detail += f" -> {control_source}"
            self._set_fundiciones_test_status(detail)
        except Exception as ex:
            self._log_fundiciones_error("_detect_fundiciones_active_control", ex)
            self._set_fundiciones_test_status(f"No pude detectar activo: {ex}")

    def _open_fundiciones_control_tester(self):
        win = tk.Toplevel(self)
        win.title("Probar campos Fundiciones")
        win.attributes("-topmost", True)
        win.resizable(True, True)
        if not hasattr(self, "_fundiciones_control_test_marks"):
            self._fundiciones_control_test_marks = {}
        if not hasattr(self, "_fundiciones_custom_control_names"):
            self._fundiciones_custom_control_names = []
        self._fundiciones_control_test_vars = {}

        box = ttk.Frame(win, padding=10)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="Botones GoToControl / SetFocus para probar nombres de casillas. Marca OK cuando funcione.").pack(anchor="w")
        self._fundiciones_test_status = tk.StringVar(value="Listo para probar.")
        ttk.Label(box, textvariable=self._fundiciones_test_status, foreground="#444444").pack(anchor="w", pady=(4, 8))

        actions = ttk.Frame(box)
        actions.pack(fill="x", pady=(0, 8))
        ttk.Button(actions, text="Abrir Fundiciones", command=lambda: self._open_fundiciones_app(enter_colada=False)).pack(side="left")
        ttk.Button(actions, text="Detectar activo", command=self._detect_fundiciones_active_control).pack(side="left", padx=6)
        ttk.Button(actions, text="Click colada", command=self._focus_fundiciones_colada_field).pack(side="left", padx=6)
        ttk.Button(actions, text="Forzar fecha inf", command=self._force_current_report_completion_date).pack(side="left", padx=6)
        ttk.Button(actions, text="Material anterior", command=lambda: self._go_fundiciones_material_record("prev")).pack(side="left", padx=6)
        ttk.Button(actions, text="Material siguiente", command=lambda: self._go_fundiciones_material_record("next")).pack(side="left", padx=6)
        ttk.Button(actions, text="Pegar por controles", command=self._paste_fundiciones_by_controls).pack(side="left", padx=6)

        custom_name = tk.StringVar()
        custom_box = ttk.Frame(box)
        custom_box.pack(fill="x", pady=(0, 8))
        custom_entry = ttk.Entry(custom_box, textvariable=custom_name)
        custom_entry.pack(side="left", fill="x", expand=True)

        scroll = ScrollFrame(box)
        scroll.pack(fill="both", expand=True)
        cols = 2

        def save_mark(control_name, var):
            self._fundiciones_control_test_marks[control_name] = bool(var.get())

        def test_control(control_name):
            control_name = str(control_name or "").strip()
            if not control_name:
                self._set_fundiciones_test_status("Escribi un nombre de control para probar.")
                return
            ok = self._goto_fundiciones_control(control_name)
            var = self._fundiciones_control_test_vars.get(control_name)
            if var is not None:
                var.set(bool(ok))
                save_mark(control_name, var)

        def add_control_button(name):
            name = str(name or "").strip()
            if not name or name in self._fundiciones_control_test_vars:
                return
            idx = len(self._fundiciones_control_test_vars)
            cell = ttk.Frame(scroll.inner)
            cell.grid(row=idx // cols, column=idx % cols, sticky="ew", padx=3, pady=3)
            cell.columnconfigure(1, weight=1)
            var = tk.BooleanVar(value=bool(self._fundiciones_control_test_marks.get(name, False)))
            self._fundiciones_control_test_vars[name] = var
            ttk.Checkbutton(
                cell,
                text="OK",
                variable=var,
                command=lambda control=name, check_var=var: save_mark(control, check_var),
            ).grid(row=0, column=0, sticky="w", padx=(0, 4))
            btn = ttk.Button(
                cell,
                text=name,
                command=lambda value=name: test_control(value),
            )
            btn.grid(row=0, column=1, sticky="ew")

        def add_custom_control():
            name = custom_name.get().strip()
            if not name:
                self._set_fundiciones_test_status("Escribi un nombre para agregar.")
                return
            if name not in FUNDICIONES_EXACT_CONTROL_NAMES and name not in self._fundiciones_custom_control_names:
                self._fundiciones_custom_control_names.append(name)
            add_control_button(name)
            custom_name.set("")
            self._set_fundiciones_test_status(f"Agregado: {name}")

        ttk.Button(custom_box, text="Probar escrito", command=lambda: test_control(custom_name.get())).pack(side="left", padx=(6, 0))
        ttk.Button(custom_box, text="Agregar botón", command=add_custom_control).pack(side="left", padx=(6, 0))
        custom_entry.bind("<Return>", lambda _event: test_control(custom_name.get()))

        names = list(FUNDICIONES_EXACT_CONTROL_NAMES) + [
            name for name in self._fundiciones_custom_control_names if name not in FUNDICIONES_EXACT_CONTROL_NAMES
        ]
        for name in names:
            add_control_button(name)
        for col in range(cols):
            scroll.inner.columnconfigure(col, weight=1)

        bottom = ttk.Frame(box)
        bottom.pack(fill="x", pady=(8, 0))
        ttk.Button(bottom, text="Cerrar", command=win.destroy).pack(side="right")

        root = self.winfo_toplevel()
        win.update_idletasks()
        width = 760
        height = 560
        x = root.winfo_rootx() + max(0, root.winfo_width() - width - 30)
        y = root.winfo_rooty() + 60
        win.geometry(f"{width}x{height}+{x}+{y}")

    def _force_current_report_completion_date(self):
        report = self._current_form_payload()
        if not str(report.get("lote", "") or "").strip():
            self._set_fundiciones_test_status("Completa el lote / colada antes de forzar la fecha.")
            return False
        if not self._fundiciones_target_form_is_open():
            self._open_fundiciones_app(report, enter_colada=False)
            self._set_fundiciones_test_status("Abri Fundiciones y reintenta forzar la fecha.")
            return False
        if not self._select_fundiciones_colada(report):
            return False
        return self._enter_fundiciones_completion_date()

    def _open_fundiciones_app(self, report=None, enter_colada=True, review=False):
        self._fundiciones_debug(f"Boton Fundiciones: enter_colada={enter_colada}, review={review}")
        try:
            if self._activate_fundiciones_window():
                self._fundiciones_debug("Ventana Fundiciones ya abierta/activada")
                if self._open_fundiciones_target_form():
                    if review:
                        self._review_current_report_in_access(report)
                    elif enter_colada:
                        self._enter_fundiciones_colada(report)
                return
            self._fundiciones_debug("Ventana Fundiciones no encontrada; preparando apertura")
            self._ensure_fundiciones_drive()
            credentials = self._prompt_fundiciones_credentials()
            if credentials is None:
                self._fundiciones_debug("Apertura cancelada: credenciales no disponibles")
                return
            user, password = credentials
            if os.path.exists(FUNDICIONES_MSACCESS_PATH):
                self._fundiciones_debug(f"Abriendo MSACCESS: {FUNDICIONES_APP_PATH}")
                subprocess.Popen(
                    [
                        FUNDICIONES_MSACCESS_PATH,
                        FUNDICIONES_APP_PATH,
                        "/WRKGRP",
                        FUNDICIONES_WRKGRP_PATH,
                        "/USER",
                        user,
                        "/PWD",
                        password,
                    ],
                    cwd=os.path.dirname(FUNDICIONES_APP_PATH),
                    creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
                self.after(0, lambda: self._open_fundiciones_target_form_retry(report, enter_colada, review=review))
            else:
                self._fundiciones_debug("MSACCESS path no encontrado; usando acceso directo/app")
                os.startfile(FUNDICIONES_SHORTCUT_PATH if os.path.exists(FUNDICIONES_SHORTCUT_PATH) else FUNDICIONES_APP_PATH)
                self.after(0, lambda: self._open_fundiciones_target_form_retry(report, enter_colada, review=review))
        except Exception as ex:
            self._fundiciones_debug(f"Abrir Fundiciones ERROR: {ex}")
            self._log_fundiciones_error("_open_fundiciones_app", ex)
            messagebox.showerror("Fundiciones", f"No se pudo abrir Fundiciones.\n\n{ex}", parent=self)

    def _activate_fundiciones_window(self):
        try:
            import win32con
            import win32gui

            matches = []

            def enum_handler(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd)
                if FUNDICIONES_WINDOW_HINT.lower() in title.lower():
                    matches.append(hwnd)

            win32gui.EnumWindows(enum_handler, None)
            if not matches:
                return False
            hwnd = matches[0]
            try:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
            except Exception:
                pass
            win32gui.SetForegroundWindow(hwnd)
            return True
        except Exception:
            try:
                import win32com.client
                shell = win32com.client.Dispatch("WScript.Shell")
                return bool(shell.AppActivate(FUNDICIONES_WINDOW_HINT))
            except Exception:
                return False

    def _access_modal_dialog_open(self):
        try:
            import win32gui
            found = []

            def enum_handler(hwnd, _):
                if not win32gui.IsWindowVisible(hwnd):
                    return
                title = win32gui.GetWindowText(hwnd).strip()
                if title == "Microsoft Access":
                    found.append(hwnd)

            win32gui.EnumWindows(enum_handler, None)
            return bool(found)
        except Exception:
            return False

    def _send_fundiciones_tab_macro(self, fields):
        if not messagebox.askyesno(
            "Fundiciones",
            "Deja el cursor en el primer campo del formulario de Fundiciones.\n\n"
            "La macro pegara los valores con Tab y no guardara el registro.\n\n"
            "Continuar?",
            parent=self,
        ):
            return
        try:
            grab = self.grab_current()
            if grab is not None:
                grab.grab_release()
        except Exception:
            pass
        if self._access_modal_dialog_open():
            messagebox.showwarning(
                "Fundiciones",
                "Access tiene un aviso abierto. Cerralo primero con Aceptar y deja el cursor en el formulario.",
                parent=self,
            )
            return
        if not self._activate_fundiciones_window():
            messagebox.showwarning(
                "Fundiciones",
                "No encontre una ventana abierta de Fundiciones. Abri la app y volve a intentar.",
                parent=self,
            )
            return
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
        except Exception as ex:
            messagebox.showerror("Fundiciones", f"No se pudo inicializar el envio de teclas.\n\n{ex}", parent=self)
            return

        self.update_idletasks()
        time.sleep(0.35)
        for _, value in fields:
            value = str(value or "").replace("\r", " ").replace("\n", " ")
            if value:
                self._clipboard_set(value)
                shell.SendKeys("^v")
                time.sleep(0.08)
            shell.SendKeys("{TAB}")
            time.sleep(0.08)

    def _fundiciones_read_control_value(self, control):
        try:
            return control.Value
        except Exception:
            return ""

    def _fundiciones_compare_key(self, value):
        text = str(value if value is not None else "").strip()
        text = text.replace("\r", " ").replace("\n", " ")
        text = " ".join(text.split())
        text = text.replace("Kg/mm²", "").replace("Kg/mm2", "").replace("HB", "").replace("%", "")
        text = text.rstrip(".").strip()
        numeric = self._parse_optional_float(text)
        if numeric is not None:
            return ("num", round(numeric, 3))
        return ("txt", text.casefold())

    def _fundiciones_values_match(self, actual, expected):
        return self._fundiciones_compare_key(actual) == self._fundiciones_compare_key(expected)

    def _fundiciones_review_add_value(self, diffs, label, control, expected, expected_label=None):
        actual = self._fundiciones_read_control_value(control)
        if not self._fundiciones_values_match(actual, expected):
            diffs.append(f"{label}: Access={actual!r} / App={expected_label if expected_label is not None else expected!r}")

    def _fundiciones_review_add_combo(self, diffs, label, form, control_name, expected_text, aliases=None):
        if not expected_text:
            return
        control = self._fundiciones_control(form, control_name)
        if control is None:
            diffs.append(f"{label}: no existe {control_name} en Access")
            return
        expected_value = self._fundiciones_combo_bound_value(control, expected_text, aliases=aliases)
        if expected_value is None:
            diffs.append(f"{label}: no pude resolver opcion {expected_text!r} en {control_name}")
            return
        self._fundiciones_review_add_value(diffs, label, control, expected_value, expected_text)

    def _review_current_report_in_access(self, report=None):
        self._fundiciones_debug("Inicio abrir informe en Access")
        if report is None:
            report = self._current_form_payload()
        material = str(report.get("material", "") or "").strip()
        if not material:
            self._set_fundiciones_test_status("Completa el material antes de abrir en Access.")
            return False
        if not self._select_fundiciones_colada(report):
            return False
        try:
            form = self._fundiciones_form()
            if form is None:
                return False
            subform_control = self._fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
            subform = self._fundiciones_materials_subform(form)
            if subform_control is None or subform is None:
                return False
            if not self._select_fundiciones_material_record(subform, material, create_if_missing=False):
                self._set_fundiciones_test_status(f"Access abierto, pero no encontre el material {material}.")
                return False
            self._focus_fundiciones_material_review_position(form, subform_control, subform)
            self._set_fundiciones_test_status(f"Access abierto en material {material}.")
            return True
        except Exception as ex:
            self._fundiciones_debug(f"Abrir Access material ERROR: {ex}")
            self._log_fundiciones_error("_review_current_report_in_access", ex)
            self._set_fundiciones_test_status(f"No pude abrir material en Access: {ex}")
            return False

    def _load_current_report_in_access(self):
        report = self._fundiciones_report_payload()
        if report is None:
            return
        self._open_fundiciones_app(report)

    def _open_current_report_in_access_for_review(self):
        report = self._fundiciones_report_payload()
        if report is None:
            return
        self._open_fundiciones_app(report, enter_colada=False, review=True)

    def _open_fundiciones_preview(self):
        report = self._fundiciones_report_payload()
        if report is None:
            return
        fields = self._fundiciones_fields(report)

        win = tk.Toplevel(self)
        win.title("Enviar a Fundiciones")
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(True, True)

        box = ttk.Frame(win, padding=12)
        box.pack(fill="both", expand=True)
        ttk.Label(box, text="Revisa el orden y los valores antes de pegarlos en Fundiciones.").pack(anchor="w", pady=(0, 8))

        tree = ttk.Treeview(box, columns=("campo", "valor"), show="headings", height=min(14, max(6, len(fields))))
        tree.heading("campo", text="Campo")
        tree.heading("valor", text="Valor")
        tree.column("campo", width=170, anchor="w")
        tree.column("valor", width=520, anchor="w")
        tree.pack(fill="both", expand=True)
        for label, value in fields:
            tree.insert("", "end", values=(label, value))

        ttk.Label(
            box,
            text="El pegado por Tab no presiona Guardar: queda cargado para revisar en Access.",
            foreground="#555555",
        ).pack(anchor="w", pady=(8, 0))

        btns = ttk.Frame(box)
        btns.pack(fill="x", pady=(10, 0))
        ttk.Button(btns, text="Completar hasta espesores", command=lambda current=report: self._open_fundiciones_app(current)).pack(side="left")
        ttk.Button(btns, text="Forzar fecha inf", command=self._force_current_report_completion_date).pack(side="left", padx=6)
        ttk.Button(btns, text="Probar campos", command=self._open_fundiciones_control_tester).pack(side="left", padx=6)
        ttk.Button(btns, text="Pegar por controles", command=self._paste_fundiciones_by_controls).pack(side="left", padx=6)
        ttk.Button(btns, text="Copiar fila", command=lambda: self._copy_fundiciones_row(fields)).pack(side="left", padx=6)
        ttk.Button(btns, text="Pegar por Tab", command=lambda: self._send_fundiciones_tab_macro(fields)).pack(side="left", padx=6)
        ttk.Button(btns, text="Cerrar", command=win.destroy).pack(side="right")

        win.update_idletasks()
        root = self.winfo_toplevel()
        width = min(760, max(640, win.winfo_width()))
        height = min(520, max(360, win.winfo_height()))
        x = root.winfo_rootx() + max(0, (root.winfo_width() - width) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - height) // 2)
        win.geometry(f"{width}x{height}+{x}+{y}")

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
            "morfologia": self._form_morfologia_value(),
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
        self._report_images = []
        self._refresh_images_ui()
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
        if self._family_for_material(self.var_material.get()) == "Nodular":
            self.var_morfologia.set("")
        elif force or not self.var_morfologia.get().strip():
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

    def _form_morfologia_value(self):
        if self._family_for_material(self.var_material.get()) == "Nodular":
            return ""
        return self.var_morfologia.get().strip()

    def _default_morfologia_value(self, material, defaults):
        if self._family_for_material(material) == "Nodular":
            return ""
        return defaults.get("morfologia", "")

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
            "morfologia": self._form_morfologia_value(),
            "tipo_grafito": self.var_tipo_grafito.get().strip(),
            "conteo_nodulos": self.var_conteo_nodulos.get().strip(),
            "pct_nodularizacion": self.var_pct_nod.get().strip(),
            "alargamiento": self.var_alargamiento.get().strip(),
            "perlita": self.var_perlita.get().strip(),
            "ferrita": self.var_ferrita.get().strip(),
            "cementita": self.var_cementita.get().strip(),
            "matriz": self.var_matriz.get().strip(),
            "imagenes": self._normalize_report_images(self._report_images),
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
        if nod:
            self.lbl_morfologia.grid_remove()
            self.ent_morfologia.grid_remove()
            self.var_morfologia.set("")
        else:
            self.lbl_morfologia.grid()
            self.ent_morfologia.grid()
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
        self._report_images = []
        self._refresh_images_ui()
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
                "morfologia": self._default_morfologia_value(material, defaults),
                "tipo_grafito": defaults.get("tipo_grafito", ""),
                "conteo_nodulos": defaults.get("conteo_nodulos", ""),
                "pct_nodularizacion": defaults.get("pct_nodularizacion", ""),
                "alargamiento": defaults.get("alargamiento", ""),
                "perlita": defaults.get("perlita", ""),
                "ferrita": defaults.get("ferrita", ""),
                "cementita": defaults.get("cementita", "0"),
                "matriz": "",
                "imagenes": [],
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
            self._report_images = []
            self._refresh_images_ui()
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
        self._report_images = []
        self._refresh_images_ui()
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
                "morfologia": self._default_morfologia_value(material, defaults),
                "tipo_grafito": defaults.get("tipo_grafito", ""),
                "conteo_nodulos": defaults.get("conteo_nodulos", ""),
                "pct_nodularizacion": defaults.get("pct_nodularizacion", ""),
                "alargamiento": defaults.get("alargamiento", ""),
                "perlita": defaults.get("perlita", ""),
                "ferrita": defaults.get("ferrita", ""),
                "cementita": defaults.get("cementita", "0"),
                "matriz": "",
                "imagenes": [],
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
            ("Tipo grafito", self._printed_graphite_text(report)),
            ("Conteo nodulos", report.get("conteo_nodulos", "")),
            ("Alargamiento (%)", report.get("alargamiento", "")),
            ("Perlita %", report.get("perlita", "")),
            ("Ferrita %", report.get("ferrita", "")),
            ("Cementita %", report.get("cementita", "")),
            ("Matriz prevalente", report.get("matriz", "")),
        ]
        if family == "Nodular":
            fields = [(label, value) for label, value in fields if label != "Conteo nodulos"]
        else:
            fields.insert(13, ("% nodularizacion", report.get("pct_nodularizacion", "")))
        if family != "Nodular":
            fields.insert(12, ("Morfologia", report.get("morfologia", "")))
        return [(label, value) for label, value in fields if str(value or "").strip()]

    def _render_print_images_html(self, reports):
        figures = []
        for report in reports or []:
            material = str(report.get("material", "") or "").strip()
            for image in self._normalize_report_images(report.get("imagenes", [])):
                uri = self._image_file_uri(image.get("path", ""))
                if not uri:
                    continue
                caption_parts = []
                if material:
                    caption_parts.append(f"Mat {material}")
                comment = str(image.get("comentario", "") or "").strip()
                caption_parts.append(comment or str(image.get("nombre", "") or "Imagen"))
                caption = " - ".join(caption_parts)
                figures.append(
                    "<figure>"
                    f"<img src=\"{html.escape(uri, quote=True)}\" alt=\"{html.escape(caption, quote=True)}\">"
                    f"<figcaption>{html.escape(caption)}</figcaption>"
                    "</figure>"
                )
        if not figures:
            return ""
        return f"<div class='images-block'><div class='images-title'>Imagenes adjuntas</div>{''.join(figures)}</div>"

    def _render_print_report_html(self, report, include_images=False):
        title = html.escape(str(report.get("informe", "") or f"Material {report.get('material', '')}"))
        rows = "".join(
            f"<tr><th>{html.escape(label)}</th><td>{html.escape(str(value))}</td></tr>"
            for label, value in self._report_print_fields(report)
        )
        obs = html.escape(str(report.get("datos", "") or "")).replace("\n", "<br>")
        obs_block = f"<div class='obs'><div class='obs-title'>Observaciones</div><div>{obs}</div></div>" if obs else ""
        images_block = self._render_print_images_html([report]) if include_images else ""
        return f"""
        <section class="material-report">
          <div class="material-header">{title}</div>
          <table>{rows}</table>
          {obs_block}
          {images_block}
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

    def _render_print_group_html(self, base, lote, reports, include_images=False):
        return self._render_print_group_html_with_color(base, lote, reports, "#111111", include_images=include_images)

    def _render_print_group_html_with_color(self, base, lote, reports, group_color, include_images=False):
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
            family = self._family_for_report(report)
            graphite_text = self._printed_graphite_text(report)
            graphite_right_label = ""
            graphite_right_value = ""
            micro_1, micro_2 = self._print_micro_rows(report)
            rows = [
                (f"material {report.get('material', '')}", "", "Tamano", str(report.get("tam_grafito", ""))),
                ("tipo grafito", graphite_text, graphite_right_label or micro_1, graphite_right_value),
                ("HB", str(report.get("dureza", "")), micro_2, ""),
            ]
            material_rows.extend(rows)

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
            row_class = " class='material-sep'" if i > 0 and mat_label.startswith("material ") else ""
            rows_html.append(f"<tr{row_class}>{left_block}</tr>")

        family_line = f"<div class='group-family'>{html.escape(family)}</div>" if family else ""
        images_block = self._render_print_images_html(reports) if include_images else ""
        return f"""
        <section class="group-report" style="color:{html.escape(group_color)}; --group-line:{html.escape(darker(group_color))};">
          {family_line}
          <table class="group-table">
            {''.join(rows_html)}
          </table>
          {images_block}
        </section>
        """

    def _build_groups_print_html(self, group_items, include_images=False):
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
                        include_images=include_images,
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
      border-top: 3px solid var(--group-line, #111111);
      border-bottom: 3px solid var(--group-line, #111111);
      padding: 0;
      box-sizing: border-box;
      overflow: hidden;
    }}
    .group-report + .group-report {{
      margin-top: -3px;
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
    .images-block {{
      display: flex;
      flex-wrap: wrap;
      gap: 3mm;
      padding: 2mm 1.5mm 3mm 1.5mm;
      border-top: 1px solid #b9b9b9;
      color: #111;
    }}
    .images-title {{
      flex: 0 0 100%;
      font-size: 12px;
      font-weight: 700;
      text-transform: uppercase;
      color: var(--group-line, #111111);
    }}
    .images-block figure {{ margin: 0; width: 45mm; break-inside: avoid; }}
    .images-block img {{
      width: 45mm;
      max-height: 38mm;
      object-fit: contain;
      border: 1px solid #999;
      background: #fff;
    }}
    .images-block figcaption {{ font-size: 10px; line-height: 1.15; color: #333; word-break: break-word; }}
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

    def _print_groups(self, include_images=False):
        chosen = self._pick_groups_to_print()
        if chosen is None:
            return
        if not chosen:
            messagebox.showinfo("Calidad", "No seleccionaste grupos para imprimir.", parent=self)
            return
        html_text = self._build_groups_print_html(chosen, include_images=include_images)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        suffix = "_con_imagenes" if include_images else ""
        out_path = Path(tempfile.gettempdir()) / f"ajuste_comp_calidad_grupos{suffix}_{stamp}.html"
        out_path.write_text(html_text, encoding="utf-8")
        try:
            webbrowser.open_new_tab(out_path.as_uri())
            archived = self._archive_printed_groups(chosen)
            messagebox.showinfo(
                "Calidad",
                f"Se genero la hoja lista para imprimir{' con imagenes' if include_images else ''}.\n\n{out_path}\n\nInformes archivados: {archived}",
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
        self._report_images = self._normalize_report_images(report.get("imagenes", []))
        self._refresh_images_ui()
        if self._report_images:
            try:
                first_id = str(self._report_images[0].get("id"))
                self.images_tree.selection_set(first_id)
                self.images_tree.focus(first_id)
                self._update_image_preview()
            except Exception:
                pass
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
