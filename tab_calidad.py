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

from storage import load_quality_reports, save_quality_reports, ensure_quality_images_dir, load_history
from utils import fmt, simulate_with_plan, to_float
from config import BG_ENTRY, FG, ACCENT, ELEMENTS
from widgets import ScrollFrame
from ce import ce_from_percent

_FIJI_PATH_FILE   = Path.home() / "ajuste_comp_fiji_path.txt"
_CAL_FILE         = Path.home() / "ajuste_comp_calibraciones.json"
_CAL_IMAGES_SUBDIR = "calibraciones"

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
IMAGEJ_RESOLUCION_PX_MM = 1655  # x100 — calibración por defecto
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
        ttk.Button(top, text="Archivar", command=self._archive_groups).pack(side="right", padx=(0, 6))

        action_bar = ttk.Frame(self, padding=(0, 4))
        action_bar.pack(fill="x", pady=(0, 8))
        ttk.Button(action_bar, text="Guardar", command=self._save_report).pack(side="left")
        ttk.Button(action_bar, text="Cancelar", command=self._cancel_draft).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Agregar", command=self._add_report_to_selected_group).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Cargar en Access", command=self._load_current_report_in_access).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Abrir en Access", command=self._open_current_report_in_access_for_review).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Ver comp. estimada", command=self._ver_comp_estimada_grupo).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Camara", command=self._open_camera_popup).pack(side="left", padx=(6, 0))
        ttk.Button(action_bar, text="Calibraciones", command=self._open_calibrations_manager).pack(side="left", padx=(6, 0))
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
        self.var_traccion_real = tk.StringVar()
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
        ttk.Label(props, text="Traccion real Lab (kg/mm2)").grid(row=0, column=2, sticky="w", pady=2)
        self.ent_traccion_real = ttk.Entry(props, textvariable=self.var_traccion_real, width=14)
        self.ent_traccion_real.grid(row=0, column=3, sticky="ew", pady=2)

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
        ttk.Label(props, text="Seccion muestra").grid(row=6, column=2, sticky="w", pady=2)
        self.cb_seccion = ttk.Combobox(props, textvariable=self.var_seccion, state="readonly", width=14)
        self.cb_seccion.grid(row=6, column=3, sticky="ew", pady=2)

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
        self.images_tree = ttk.Treeview(images_box, columns=("archivo", "comentario"), show="tree headings", height=4, selectmode="extended")
        self.images_tree.heading("#0", text="")
        self.images_tree.column("#0", width=18, stretch=False, minwidth=18)
        self.images_tree.heading("archivo", text="Archivo")
        self.images_tree.heading("comentario", text="Comentario")
        self.images_tree.column("archivo", width=158, anchor="w")
        self.images_tree.column("comentario", width=190, anchor="w")
        self.images_tree.grid(row=0, column=0, sticky="ew")
        self.images_tree.bind("<<TreeviewSelect>>", lambda e: self._update_image_preview())
        self.images_tree.bind("<Double-Button-1>", lambda e: self._edit_selected_image_comment())
        image_btns = ttk.Frame(images_box)
        image_btns.grid(row=0, column=1, sticky="ns", padx=(8, 0))
        ttk.Button(image_btns, text="Importar ImageJ", command=self._import_imagej_analysis).pack(fill="x")
        ttk.Button(image_btns, text="Agregar imagen", command=self._add_images).pack(fill="x")
        ttk.Button(image_btns, text="Abrir en ImageJ", command=self._open_in_imagej).pack(fill="x", pady=(4, 0))
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
            self.var_traccion, self.var_traccion_real, self.var_seccion, self.var_dureza, self.var_tam_grafito,
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
            "traccion_real": self.ent_traccion_real,
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

    def _ver_comp_estimada_grupo(self):
        sel = self.tree.selection()
        if not sel:
            return
        parent_iid = str(sel[0])
        if not parent_iid.startswith("group:"):
            # si seleccionó un informe hijo, usar su grupo padre
            parent_iid = self.tree.parent(parent_iid)
        if not parent_iid or not parent_iid.startswith("group:"):
            return

        children   = self.tree.get_children(parent_iid)
        group_rpts = [self.reports[self._item_to_index[c]]
                      for c in children if c in self._item_to_index]
        if not group_rpts:
            return

        lote     = group_rpts[0].get("lote", "")
        base_disp = group_rpts[0].get("base_display", group_rpts[0].get("base", ""))

        base_comp = {}
        session = next((s for s in load_history() if s.get("colada", "") == lote), None)
        if session and session.get("ajustes"):
            base_comp = session["ajustes"][-1].get("estimado", {}).get("comp", {}) or {}

        def _eff_add(alloy, kg):
            rend = to_float(alloy.get("rendimiento", 100)) / 100
            return {e: kg * (to_float(alloy.get("composicion", {}).get(e, 0)) / 100) * rend
                    for e in ELEMENTS}

        def _get_alloy(name):
            for a in self.alloys:
                if str(a.get("nombre", "")).strip() == name:
                    return a
            return None

        def _gramos(nombre):
            a = _get_alloy(nombre)
            return (a.get("gramos_cucharin1", 0) or 0) if a else 0

        # Calcular composición por material
        results = {}  # material → comp_dict
        for rpt in group_rpts:
            mat      = rpt.get("material", "")
            snapshot = rpt.get("inoculacion_snapshot", {})
            if not isinstance(snapshot, dict):
                snapshot = {}
            inoc = snapshot.get("protocolo", [])
            if not inoc:
                results[mat] = dict(base_comp)
                continue
            plan = {}
            for e in inoc:
                if isinstance(e, str):
                    nombre, cant = e, 1.0
                elif isinstance(e, dict):
                    nombre = e.get("nombre", "")
                    try:
                        cant = float(e.get("cantidad_dosis", 1) or 1)
                    except Exception:
                        cant = 1.0
                else:
                    continue
                g = _gramos(nombre)
                if g and cant:
                    plan[nombre] = (g * cant) / 1000
            if plan:
                try:
                    _, comp = simulate_with_plan(
                        50, base_comp, plan, ELEMENTS,
                        get_alloy=_get_alloy,
                        effective_add=_eff_add,
                        effective_total_perkg=lambda a: to_float(a.get("rendimiento",100))/100,
                    )
                    results[mat] = comp
                except Exception:
                    results[mat] = dict(base_comp)
            else:
                results[mat] = dict(base_comp)

        if not results:
            messagebox.showinfo("Composición estimada", "No hay datos de inoculación para este grupo.")
            return

        # Diálogo resultado
        win = tk.Toplevel(self)
        win.title(f"Composición estimada — Base {base_disp} / {lote}")
        win.transient(self)
        win.grab_set()
        win.resizable(True, True)

        frm = ttk.Frame(win, padding=12)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        # La columna "Hierro base" va primero, luego cada material inoculado
        BASE_COL = "Hierro base"
        all_cols  = [BASE_COL] + list(results.keys())
        col_ids   = ("el",) + tuple(f"c{i}" for i in range(len(all_cols)))

        tv = ttk.Treeview(frm, columns=col_ids, show="headings", height=16, selectmode="none")
        tv.heading("el", text="Elemento")
        tv.column("el", width=80, anchor="w")
        for cid, label in zip(col_ids[1:], all_cols):
            tv.heading(cid, text=label)
            tv.column(cid, width=max(90, len(label) * 8), anchor="center")


        tv_sb_y = ttk.Scrollbar(frm, orient="vertical",   command=tv.yview)
        tv_sb_x = ttk.Scrollbar(frm, orient="horizontal", command=tv.xview)
        tv.configure(yscrollcommand=tv_sb_y.set, xscrollcommand=tv_sb_x.set)
        tv_sb_y.grid(row=0, column=1, sticky="ns")
        tv_sb_x.grid(row=1, column=0, sticky="ew")
        tv.grid(row=0, column=0, sticky="nsew")

        def _row_vals(el):
            base_v = to_float(base_comp.get(el, 0))
            mat_vs = [to_float(results[m].get(el, 0)) for m in results]
            return [base_v] + mat_vs

        # Filas de elementos
        for el in ELEMENTS:
            vals = _row_vals(el)
            if any(v > 0.001 for v in vals):
                tv.insert("", "end", values=(el,) + tuple(fmt(v, 4) for v in vals))
        # Fila CE
        ce_base = ce_from_percent(base_comp)
        ce_mats = [ce_from_percent(results[m]) for m in results]
        tv.insert("", "end", values=("CE",) + tuple(fmt(v, 4) for v in ([ce_base] + ce_mats)))

        ttk.Button(frm, text="Cerrar", command=win.destroy).grid(
            row=2, column=0, columnspan=2, pady=(10, 0))

    def _build_inoc_snapshot(self, material_code, base=None):
        from storage import resolve_inoc_protocol
        alloy = self._get_final_alloy_by_code(str(material_code or "").strip()) or {}
        meta = alloy.get("inoculacion_meta", {})
        return {
            "inoculacion_meta": meta,
            "base_resuelta": str(base or "").strip(),
            "protocolo": resolve_inoc_protocol(meta, base=base),
        }

    def _get_final_alloy_by_code(self, code):
        """Busca la Aleación final en el catálogo por su código (calidad_meta.codigo o nombre)."""
        for a in self.alloys:
            meta = a.get("calidad_meta", {}) if isinstance(a, dict) else {}
            if not isinstance(meta, dict) or not meta.get("es_material_final"):
                continue
            c = str(meta.get("codigo") or a.get("nombre", "")).strip()
            if c == str(code).strip():
                return a
        return None

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
            _KNOWN = {"id", "nombre", "path", "comentario", "comment", "added_at", "archivo"}
            extra = {k: v for k, v in item.items() if k not in _KNOWN}
            normalized.append({
                "id": image_id,
                "nombre": nombre,
                "path": path,
                "comentario": str(item.get("comentario") or item.get("comment") or "").strip(),
                "added_at": str(item.get("added_at") or ""),
                **extra,
            })
        return normalized

    def _refresh_images_ui(self):
        try:
            self.images_tree.delete(*self.images_tree.get_children())
            seen_groups = {}
            for image in self._report_images:
                iid = str(image.get("id") or uuid.uuid4().hex)
                gid = image.get("scan_group_id")
                nombre = image.get("nombre", "")
                comentario = image.get("comentario", "")
                if gid:
                    if gid not in seen_groups:
                        label = image.get("scan_group_label", "Grupo")
                        parent_iid = f"grp:{gid}"
                        self.images_tree.insert("", "end", iid=parent_iid, text="", values=(label, ""), open=True)
                        seen_groups[gid] = parent_iid
                    self.images_tree.insert(seen_groups[gid], "end", iid=iid, values=(nombre, comentario))
                else:
                    self.images_tree.insert("", "end", iid=iid, values=(nombre, comentario))
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
        if target_id.startswith("grp:"):
            children = self.images_tree.get_children(target_id)
            if not children:
                return None
            target_id = children[0]
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

    # ── Calibraciones persistentes ────────────────────────────────────────────

    def _make_zoom_pan_preview(self, parent, preview_w, preview_h,
                               cursor="crosshair", on_redraw=None):
        """Canvas con zoom (rueda) y pan (botón derecho arrastrado).
        Devuelve (canvas, show_frame_fn, reset_fn, canvas_to_img_fn, img_to_canvas_fn).
        - show_frame: BGR numpy array o PIL Image
        - on_redraw(canvas): callback opcional llamado después de cada render
          para dibujar anotaciones encima de la imagen
        El zoom mínimo es 1.0 para evitar márgenes negros."""
        canvas = tk.Canvas(parent, width=preview_w, height=preview_h,
                           bg="#111", cursor=cursor)
        zoom  = [1.0]
        pan   = [0.0, 0.0]
        last  = [None]
        photo = [None]

        def _clamp(fw, fh):
            vw = preview_w / zoom[0]; vh = preview_h / zoom[0]
            pan[0] = max(0.0, min(pan[0], max(0.0, fw - vw)))
            pan[1] = max(0.0, min(pan[1], max(0.0, fh - vh)))

        def _render(pil_img):
            fw, fh = pil_img.size
            _clamp(fw, fh)
            vw = preview_w / zoom[0]; vh = preview_h / zoom[0]
            box = (pan[0], pan[1], pan[0] + vw, pan[1] + vh)
            resample = Image.NEAREST if zoom[0] > 3 else Image.LANCZOS
            cropped = pil_img.crop(box).resize((preview_w, preview_h), resample)
            ph = ImageTk.PhotoImage(cropped)
            canvas.delete("all")
            canvas.create_image(0, 0, anchor="nw", image=ph)
            photo[0] = ph
            if on_redraw:
                on_redraw(canvas)

        def show_frame(frame):
            if frame is None:
                return
            if isinstance(frame, Image.Image):
                pil = frame.convert("RGB")
            else:
                import cv2 as _cv2
                pil = Image.fromarray(_cv2.cvtColor(frame, _cv2.COLOR_BGR2RGB))
            last[0] = pil
            _render(pil)

        def reset():
            zoom[0] = 1.0; pan[0] = 0.0; pan[1] = 0.0
            if last[0]:
                _render(last[0])

        def canvas_to_img(cx, cy):
            return pan[0] + cx / zoom[0], pan[1] + cy / zoom[0]

        def img_to_canvas(ix, iy):
            return (ix - pan[0]) * zoom[0], (iy - pan[1]) * zoom[0]

        def on_scroll(event):
            if last[0] is None:
                return
            up = (event.num == 4) or (getattr(event, "delta", 0) > 0)
            factor = 1.2 if up else 1 / 1.2
            fw, fh = last[0].size
            mx = pan[0] + event.x / zoom[0]
            my = pan[1] + event.y / zoom[0]
            # mínimo 1.0 para que la imagen siempre llene el canvas sin márgenes
            zoom[0] = max(1.0, min(20.0, zoom[0] * factor))
            pan[0] = mx - event.x / zoom[0]
            pan[1] = my - event.y / zoom[0]
            _clamp(fw, fh)
            _render(last[0])

        drag = [None]; pan0 = [None]

        def on_r_press(event):
            drag[0] = (event.x, event.y)
            pan0[0] = (pan[0], pan[1])
            canvas.config(cursor="fleur")

        def on_r_drag(event):
            if drag[0] is None or last[0] is None:
                return
            dx = (event.x - drag[0][0]) / zoom[0]
            dy = (event.y - drag[0][1]) / zoom[0]
            pan[0] = pan0[0][0] - dx
            pan[1] = pan0[0][1] - dy
            _clamp(*last[0].size)
            _render(last[0])

        def on_r_release(event):
            drag[0] = None
            canvas.config(cursor=cursor)

        canvas.bind("<MouseWheel>",       on_scroll)
        canvas.bind("<Button-4>",         on_scroll)
        canvas.bind("<Button-5>",         on_scroll)
        canvas.bind("<Button-3>",         on_r_press)
        canvas.bind("<B3-Motion>",        on_r_drag)
        canvas.bind("<ButtonRelease-3>",  on_r_release)
        canvas.bind("<Double-Button-1>",  lambda e: reset())

        return canvas, show_frame, reset, canvas_to_img, img_to_canvas

    def _cal_load(self):
        try:
            import json as _json
            return _json.loads(_CAL_FILE.read_text(encoding="utf-8"))
        except Exception:
            return []

    def _cal_save(self, cals):
        import json as _json
        _CAL_FILE.write_text(_json.dumps(cals, ensure_ascii=False, indent=2), encoding="utf-8")

    def _cal_images_dir(self):
        d = Path(ensure_quality_images_dir()) / _CAL_IMAGES_SUBDIR
        d.mkdir(exist_ok=True)
        return d

    def _cal_get_default_id(self):
        return next((c["id"] for c in self._cal_load() if c.get("is_default")), None)

    def _cal_set_default(self, cal_id):
        data = self._cal_load()
        for c in data:
            c.pop("is_default", None)
            if c["id"] == cal_id:
                c["is_default"] = True
        self._cal_save(data)

    def _cal_default_label(self):
        default_id = self._cal_get_default_id()
        if not default_id:
            return "x100 (por defecto)"
        cal = next((c for c in self._cal_load() if c.get("id") == default_id), None)
        return f"{cal['nombre']} (por defecto)" if cal else "x100 (por defecto)"

    def _cal_get_px_per_mm(self, cal_id):
        effective_id = cal_id or self._cal_get_default_id()
        if not effective_id:
            return None
        cal = next((c for c in self._cal_load() if c.get("id") == effective_id), None)
        if not cal or not cal.get("px_per_unit"):
            return None
        unit = cal.get("unit", "µm")
        v = float(cal["px_per_unit"])
        if unit == "µm":
            return v * 1000.0
        if unit == "cm":
            return v / 10.0
        return v  # mm

    def _ask_image_metadata(self, parent, filename=""):
        """Muestra un dialogo que pide comentario y calibracion para una imagen.
        Devuelve (comentario, calibration_id) o (None, None) si se cancela."""
        cals = self._cal_load()
        result = {"comment": None, "cal_id": None, "cancelled": True}

        dlg = tk.Toplevel(parent)
        dlg.title("Datos de la imagen")
        dlg.transient(parent)
        dlg.grab_set()
        dlg.resizable(False, False)

        f = ttk.Frame(dlg, padding=14)
        f.pack(fill="both")
        f.columnconfigure(1, weight=1)

        if filename:
            ttk.Label(f, text=filename, foreground="#555").grid(
                row=0, column=0, columnspan=2, sticky="w", pady=(0, 8))

        ttk.Label(f, text="Observacion:").grid(row=1, column=0, sticky="w", pady=3)
        comment_var = tk.StringVar()
        ttk.Entry(f, textvariable=comment_var, width=34).grid(
            row=1, column=1, sticky="ew", pady=3, padx=(8, 0))

        ttk.Label(f, text="Calibracion:").grid(row=2, column=0, sticky="w", pady=3)
        default_label = self._cal_default_label()
        cal_names = [default_label] + [c["nombre"] for c in cals]
        cal_var = tk.StringVar(value=cal_names[0])
        ttk.Combobox(f, textvariable=cal_var, values=cal_names,
                     state="readonly", width=28).grid(
            row=2, column=1, sticky="ew", pady=3, padx=(8, 0))

        bf = ttk.Frame(f)
        bf.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(10, 0))

        def _accept():
            chosen = cal_var.get()
            cal_obj = next((c for c in cals if c["nombre"] == chosen), None)
            result["comment"] = comment_var.get().strip()
            result["cal_id"] = cal_obj["id"] if cal_obj else None
            result["cancelled"] = False
            dlg.destroy()

        ttk.Button(bf, text="Aceptar", command=_accept).pack(side="right")
        ttk.Button(bf, text="Cancelar", command=dlg.destroy).pack(side="right", padx=6)

        dlg.bind("<Return>", lambda e: _accept())
        dlg.wait_window()

        if result["cancelled"]:
            return None, None
        return result["comment"], result["cal_id"]

    def _open_calibrations_manager(self):
        if Image is None or ImageTk is None:
            messagebox.showinfo("Calibraciones", "Pillow no esta disponible.", parent=self)
            return
        win = tk.Toplevel(self)
        win.title("Calibraciones de escala")
        win.transient(self.winfo_toplevel())
        win.resizable(True, True)

        frm = ttk.Frame(win, padding=10)
        frm.pack(fill="both", expand=True)
        frm.columnconfigure(0, weight=1)
        frm.rowconfigure(0, weight=1)

        cols = ("nombre", "escala", "unidad", "fecha")
        tv = ttk.Treeview(frm, columns=cols, show="headings", height=10, selectmode="browse")
        for cid, title, w in (("nombre","Nombre",200),("escala","Escala (px/unidad)",160),
                               ("unidad","Unidad",70),("fecha","Creada",130)):
            tv.heading(cid, text=title)
            tv.column(cid, width=w, anchor="w")
        tv_sb = ttk.Scrollbar(frm, orient="vertical", command=tv.yview)
        tv.configure(yscrollcommand=tv_sb.set)
        tv.grid(row=0, column=0, sticky="nsew")
        tv_sb.grid(row=0, column=1, sticky="ns")

        cals = [None]

        def _refresh():
            tv.delete(*tv.get_children())
            cals[0] = self._cal_load()
            for c in cals[0]:
                nombre = ("★ " if c.get("is_default") else "") + c["nombre"]
                tv.insert("", "end", iid=c["id"],
                          values=(nombre,
                                  f"{c['px_per_unit']:.4f}" if c.get("px_per_unit") else "—",
                                  c.get("unit","µm"),
                                  c.get("created_at","")[:10]))

        def _selected():
            s = tv.selection()
            if not s:
                return None
            return next((c for c in (cals[0] or []) if c["id"] == s[0]), None)

        def _new():
            result = self._calibration_wizard(win)
            if result:
                data = self._cal_load()
                data.append(result)
                self._cal_save(data)
                _refresh()

        def _delete():
            c = _selected()
            if not c:
                return
            if not messagebox.askyesno("Calibraciones",
                    f"Eliminar '{c['nombre']}'?", parent=win):
                return
            img = c.get("image_path", "")
            if img and Path(img).exists():
                try:
                    Path(img).unlink()
                except Exception:
                    pass
            data = [x for x in self._cal_load() if x["id"] != c["id"]]
            self._cal_save(data)
            _refresh()

        def _rename():
            c = _selected()
            if not c:
                return
            nuevo = simpledialog.askstring("Renombrar", "Nuevo nombre:",
                                           initialvalue=c["nombre"], parent=win)
            if nuevo and nuevo.strip():
                data = self._cal_load()
                for x in data:
                    if x["id"] == c["id"]:
                        x["nombre"] = nuevo.strip()
                self._cal_save(data)
                _refresh()

        def _view_image():
            c = _selected()
            if not c:
                return
            img_path = c.get("image_path", "")
            if not img_path or not Path(img_path).exists():
                messagebox.showinfo("Calibraciones", "Imagen de referencia no encontrada.", parent=win)
                return
            self._show_calibration_reference(win, c, img_path)

        def _set_default():
            c = _selected()
            if not c:
                messagebox.showinfo("Calibraciones", "Selecciona una calibracion primero.", parent=win)
                return
            self._cal_set_default(c["id"])
            _refresh()

        def _recalibrate():
            c = _selected()
            if not c:
                messagebox.showinfo("Calibraciones",
                    "Selecciona una calibracion para recalibrar.", parent=win)
                return
            new_data = self._calibration_wizard(win)
            if new_data is None:
                return
            # Eliminar imagen anterior si se reemplazó
            old_img = c.get("image_path", "")
            new_img = new_data.get("image_path", "")
            if old_img and old_img != new_img and Path(old_img).exists():
                try:
                    Path(old_img).unlink()
                except Exception:
                    pass
            # Actualizar preservando ID y nombre original
            data = self._cal_load()
            for x in data:
                if x["id"] == c["id"]:
                    x.update({k: v for k, v in new_data.items()
                               if k not in ("id", "nombre")})
                    break
            self._cal_save(data)
            _refresh()

        btn_row = ttk.Frame(frm)
        btn_row.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(btn_row, text="Nueva calibracion", command=_new).pack(side="left")
        ttk.Button(btn_row, text="Recalibrar", command=_recalibrate).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Predeterminar ★", command=_set_default).pack(side="left")
        ttk.Button(btn_row, text="Renombrar", command=_rename).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Ver imagen ref.", command=_view_image).pack(side="left")
        ttk.Button(btn_row, text="Eliminar", command=_delete).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cerrar", command=win.destroy).pack(side="right")

        _refresh()

    def _show_calibration_reference(self, parent, cal_data, img_path):
        try:
            pil_img = Image.open(img_path).convert("RGB")
        except Exception as ex:
            messagebox.showerror("Calibraciones", f"No se pudo abrir la imagen:\n{ex}", parent=parent)
            return
        CANVAS_W, CANVAS_H = 820, 560
        img_w, img_h = pil_img.size
        ds = min(CANVAS_W / img_w, CANVAS_H / img_h, 1.0)
        disp_img = pil_img.resize((int(img_w*ds), int(img_h*ds)), Image.LANCZOS)

        win = tk.Toplevel(parent)
        win.title(f"Referencia — {cal_data['nombre']}")
        win.transient(parent)
        win.resizable(True, True)

        def _draw_ref(cv):
            for key in ("ref_x1", "ref_y1", "ref_x2", "ref_y2"):
                if cal_data.get(key) is None:
                    return
            x1c, y1c = _i2c_ref(cal_data["ref_x1"] * ds, cal_data["ref_y1"] * ds)
            x2c, y2c = _i2c_ref(cal_data["ref_x2"] * ds, cal_data["ref_y2"] * ds)
            cv.create_line(x1c, y1c, x2c, y2c, fill="#ffcc00", width=2)
            for px, py in ((x1c, y1c), (x2c, y2c)):
                cv.create_oval(px-4, py-4, px+4, py+4, fill="#ffcc00", outline="")
            mx, my = (x1c + x2c) / 2, (y1c + y2c) / 2
            lbl = (f"{cal_data['ref_real_dist']} {cal_data.get('unit','µm')}"
                   f" = {cal_data['ref_px_dist']:.1f} px")
            cv.create_text(mx+1, my-11, text=lbl, fill="#000", font=("TkDefaultFont", 9, "bold"))
            cv.create_text(mx,   my-12, text=lbl, fill="#ffcc00", font=("TkDefaultFont", 9, "bold"))

        canvas, _show_ref, _reset_ref, _c2i_ref, _i2c_ref = self._make_zoom_pan_preview(
            win, CANVAS_W, CANVAS_H, on_redraw=_draw_ref)
        canvas.pack(fill="both", expand=True)

        info_row = ttk.Frame(win, padding=(8, 4))
        info_row.pack(fill="x")
        ttk.Label(info_row,
            text=(f"{cal_data['nombre']}  |  {cal_data.get('px_per_unit',0):.4f} px/{cal_data.get('unit','µm')}"
                  f"  |  {1/cal_data['px_per_unit']:.4f} {cal_data.get('unit','µm')}/px"
                  if cal_data.get("px_per_unit") else "Sin datos de escala"),
            anchor="w").pack(side="left")
        ttk.Button(info_row, text="Reset zoom", command=_reset_ref).pack(side="right")
        ttk.Button(info_row, text="Cerrar", command=win.destroy).pack(side="right", padx=6)

        _show_ref(disp_img)

    def _capture_for_calibration(self, parent):
        """Abre un mini-popup de camara y devuelve (PIL Image, Path destino) o (None, None)."""
        try:
            import cv2
        except ImportError:
            messagebox.showinfo("Camara", "OpenCV no esta instalado.", parent=parent)
            return None, None
        if Image is None or ImageTk is None:
            messagebox.showinfo("Camara", "Pillow no esta disponible.", parent=parent)
            return None, None

        cap = None
        for idx in range(3):
            for backend in [cv2.CAP_DSHOW, cv2.CAP_MSMF, 0]:
                try:
                    c = cv2.VideoCapture(idx, backend) if backend else cv2.VideoCapture(idx)
                    if c.isOpened():
                        ret, _ = c.read()
                        if ret:
                            cap = c
                            break
                    c.release()
                except Exception:
                    pass
            if cap:
                break
        if cap is None:
            messagebox.showinfo("Camara", "No se pudo abrir la camara.", parent=parent)
            return None, None

        for res in ((3840, 2160), (1920, 1080), (1280, 720)):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  res[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])
            ret, test = cap.read()
            if ret and test is not None:
                break
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        _cw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        _ch = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        PREV_W, PREV_H = 820, 616

        def _fill_cal(bgr):
            return cv2.resize(bgr, (PREV_W, PREV_H), interpolation=cv2.INTER_LINEAR)
        captured = [None]
        live = [True]
        result_path = [None]

        win = tk.Toplevel(parent)
        win.title("Capturar imagen de referencia")
        win.transient(parent)
        win.grab_set()
        win.resizable(False, False)

        lbl, _show_cal, _reset_cal, _c2i_cal, _i2c_cal = self._make_zoom_pan_preview(win, PREV_W, PREV_H)
        lbl.pack()
        status_var = tk.StringVar(value="Previsualizacion en vivo — apunta a la barra de escala")
        ttk.Label(win, textvariable=status_var, anchor="center").pack(fill="x", pady=(2, 0))

        _cals_cap  = self._cal_load()
        _cap_names = ["(nueva calibracion)"] + [c["nombre"] for c in _cals_cap]
        cap_cal_var = tk.StringVar(value=_cap_names[0])
        cal_row_cap = ttk.Frame(win, padding=(8, 2))
        cal_row_cap.pack(fill="x")
        ttk.Label(cal_row_cap, text="Aumento / calibracion:").pack(side="left")
        ttk.Combobox(cal_row_cap, textvariable=cap_cal_var, values=_cap_names,
                     state="readonly", width=28).pack(side="left", padx=(6, 0))

        btn_row = ttk.Frame(win, padding=(8, 6))
        btn_row.pack(fill="x")
        btn_cap = ttk.Button(btn_row, text="Capturar")
        btn_cap.pack(side="left")
        btn_use = ttk.Button(btn_row, text="Usar esta foto", state="disabled")
        btn_use.pack(side="left", padx=6)
        ttk.Button(btn_row, text="Cancelar", command=lambda: _close()).pack(side="right")
        ttk.Button(btn_row, text="Reset zoom", command=_reset_cal).pack(side="right", padx=6)

        def _show(frame_bgr):
            _show_cal(_fill_cal(frame_bgr))

        def _update():
            if not live[0] or not win.winfo_exists():
                return
            ret, frame = cap.read()
            if ret:
                _show(frame)
            win.after(33, _update)

        def _do_capture():
            # Vaciar buffer para obtener el frame mas reciente
            frame = None
            for _ in range(3):
                ret, f = cap.read()
                if ret:
                    frame = f
            if frame is None:
                return
            live[0] = False
            captured[0] = frame
            h, w = frame.shape[:2]
            _show(frame)
            status_var.set(f"Capturada {w}×{h}. Usa 'Usar esta foto' o 'Repetir'.")
            btn_cap.config(text="Repetir")
            btn_use.config(state="normal")

        def _do_use():
            frame = captured[0]
            if frame is None:
                return
            dest = self._cal_images_dir() / \
                f"cal_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:6]}.jpg"
            cv2.imwrite(str(dest), frame, [cv2.IMWRITE_JPEG_QUALITY, 97])
            result_path[0] = dest
            _close()

        def _close():
            live[0] = False
            try: cap.release()
            except Exception: pass
            try: win.destroy()
            except Exception: pass

        btn_cap.config(command=_do_capture)
        btn_use.config(command=_do_use)
        win.protocol("WM_DELETE_WINDOW", _close)
        _update()
        win.wait_window()

        if result_path[0] is None:
            return None, None
        try:
            pil = Image.open(result_path[0]).convert("RGB")
            return pil, result_path[0]
        except Exception:
            return None, None

    def _calibration_wizard(self, parent):
        """Abre el wizard para crear una nueva calibracion. Devuelve el dict o None."""
        # Elegir fuente de imagen
        source = {"v": None}
        dlg = tk.Toplevel(parent)
        dlg.title("Nueva calibracion")
        dlg.transient(parent)
        dlg.grab_set()
        dlg.resizable(False, False)
        f = ttk.Frame(dlg, padding=18)
        f.pack()
        ttk.Label(f, text="Origen de la imagen de referencia:", font=("TkDefaultFont", 9, "bold")).pack(pady=(0, 12))
        ttk.Button(f, text="Capturar desde camara",
                   command=lambda: (source.__setitem__("v", "camera"), dlg.destroy()),
                   width=28).pack(pady=4)
        ttk.Button(f, text="Cargar desde archivo",
                   command=lambda: (source.__setitem__("v", "file"), dlg.destroy()),
                   width=28).pack(pady=4)
        ttk.Button(f, text="Cancelar",
                   command=dlg.destroy, width=28).pack(pady=(10, 0))
        dlg.wait_window()

        if source["v"] is None:
            return None

        if source["v"] == "camera":
            pil_img, src = self._capture_for_calibration(parent)
            if pil_img is None:
                return None
            src = Path(src)
            already_copied = True
        else:
            img_path_str = filedialog.askopenfilename(
                parent=parent,
                title="Imagen de referencia para calibracion",
                filetypes=(("Imagenes", "*.png *.jpg *.jpeg *.bmp *.tif *.tiff"),
                           ("Todos los archivos", "*.*")),
            )
            if not img_path_str:
                return None
            src = Path(img_path_str)
            already_copied = False

        if not already_copied:
            try:
                pil_img = Image.open(src).convert("RGB")
            except Exception as ex:
                messagebox.showerror("Calibraciones", f"No se pudo abrir la imagen:\n{ex}", parent=parent)
                return None

        CANVAS_W, CANVAS_H = 820, 560
        img_w, img_h = pil_img.size
        ds = min(CANVAS_W / img_w, CANVAS_H / img_h, 1.0)
        disp_w, disp_h = int(img_w * ds), int(img_h * ds)
        disp_img = pil_img.resize((disp_w, disp_h), Image.LANCZOS)

        result  = [None]
        pending = []
        ref     = {}

        win = tk.Toplevel(parent)
        win.title("Nueva calibracion — marca la distancia de referencia")
        win.transient(parent)
        win.grab_set()
        win.resizable(True, True)

        instr_var = tk.StringVar(value="Paso 1: clic en el primer punto de la referencia conocida")
        ttk.Label(win, textvariable=instr_var, anchor="center",
                  font=("TkDefaultFont", 9, "bold")).pack(fill="x", pady=(4, 2))

        # Anotaciones dibujadas encima del canvas tras cada render.
        # ref y pending almacenan coords en espacio de imagen original.
        # _i2c espera coords en espacio disp_img (= original × ds).
        def _draw_annotations(cv):
            if pending:
                px, py = _i2c(pending[0][0] * ds, pending[0][1] * ds)
                cv.create_oval(px-5, py-5, px+5, py+5, fill="#ff4444", outline="white", width=1)
            if ref:
                x1c, y1c = _i2c(ref["x1"] * ds, ref["y1"] * ds)
                x2c, y2c = _i2c(ref["x2"] * ds, ref["y2"] * ds)
                cv.create_line(x1c, y1c, x2c, y2c, fill="#ffcc00", width=2)
                for px, py in ((x1c, y1c), (x2c, y2c)):
                    cv.create_oval(px-4, py-4, px+4, py+4, fill="#ffcc00", outline="")
                mx, my = (x1c + x2c) / 2, (y1c + y2c) / 2
                lbl = f"{ref.get('real_dist','?')} {ref.get('unit','µm')} = {ref['px_dist']:.1f} px"
                cv.create_text(mx+1, my-11, text=lbl, fill="#000", font=("TkDefaultFont", 9, "bold"))
                cv.create_text(mx,   my-12, text=lbl, fill="#ffcc00", font=("TkDefaultFont", 9, "bold"))

        canvas, _show_wiz, _reset_wiz, _c2i, _i2c = self._make_zoom_pan_preview(
            win, CANVAS_W, CANVAS_H, on_redraw=_draw_annotations)
        canvas.pack(fill="both", expand=True)

        def _redraw():
            _show_wiz(disp_img)

        unit_var = tk.StringVar(value="µm")

        def _on_click(event):
            if ref:
                return
            # Convertir coords del canvas a coords en disp_img, luego a imagen original
            dx, dy = _c2i(event.x, event.y)
            ix, iy = dx / ds, dy / ds
            if not (0 <= ix <= img_w and 0 <= iy <= img_h):
                return
            pending.append((ix, iy))
            _redraw()
            if len(pending) < 2:
                instr_var.set("Paso 2: clic en el segundo punto")
                return
            x1, y1 = pending[0]; x2, y2 = pending[1]
            pending.clear()
            px_d = ((x2-x1)**2 + (y2-y1)**2) ** 0.5
            real = simpledialog.askfloat(
                "Distancia de referencia",
                f"Distancia real entre los dos puntos ({unit_var.get()}):",
                parent=win, minvalue=1e-6)
            if real is None:
                instr_var.set("Cancelado. Vuelve a marcar los puntos.")
                _redraw()
                return
            ref.update({"x1": x1, "y1": y1, "x2": x2, "y2": y2,
                        "px_dist": px_d, "real_dist": real, "unit": unit_var.get()})
            instr_var.set(
                f"Referencia marcada: {real} {unit_var.get()} = {px_d:.1f} px  |  Completar y guardar.")
            _redraw()

        canvas.bind("<Button-1>", _on_click)

        ctrl = ttk.Frame(win, padding=(8, 4)); ctrl.pack(fill="x")
        ttk.Label(ctrl, text="Unidad:").pack(side="left")
        ttk.Combobox(ctrl, textvariable=unit_var,
                     values=["µm", "mm", "cm"], width=5, state="readonly").pack(side="left", padx=(4, 0))
        ttk.Button(ctrl, text="Reiniciar puntos",
                   command=lambda: (ref.clear(), pending.clear(),
                                    instr_var.set("Paso 1: clic en el primer punto"),
                                    _redraw())).pack(side="left", padx=(12, 0))
        ttk.Button(ctrl, text="Reset zoom", command=_reset_wiz).pack(side="left", padx=(12, 0))

        form = ttk.LabelFrame(win, text="Datos de la calibracion", padding=8)
        form.pack(fill="x", padx=8, pady=(0,4))
        nombre_var = tk.StringVar(value="")
        notas_var  = tk.StringVar(value="")
        ttk.Label(form, text="Nombre (ej: Objetivo 10x):").grid(row=0,column=0,sticky="w",pady=2)
        ttk.Entry(form, textvariable=nombre_var, width=28).grid(row=0,column=1,sticky="ew",pady=2,padx=(6,0))
        ttk.Label(form, text="Notas:").grid(row=1,column=0,sticky="w",pady=2)
        ttk.Entry(form, textvariable=notas_var, width=28).grid(row=1,column=1,sticky="ew",pady=2,padx=(6,0))
        form.columnconfigure(1,weight=1)

        def _save():
            if not ref:
                messagebox.showinfo("Calibraciones","Marca primero los dos puntos de referencia.",parent=win)
                return
            nombre = nombre_var.get().strip()
            if not nombre:
                messagebox.showinfo("Calibraciones","Ingresa un nombre para la calibracion.",parent=win)
                return
            if already_copied:
                dest = src
            else:
                dest_dir = self._cal_images_dir()
                dest = dest_dir / f"cal_{uuid.uuid4().hex[:8]}{src.suffix.lower()}"
                shutil.copy2(str(src), str(dest))
            px_per_unit = ref["px_dist"] / ref["real_dist"]
            result[0] = {
                "id": uuid.uuid4().hex,
                "nombre": nombre,
                "px_per_unit": px_per_unit,
                "unit": ref["unit"],
                "created_at": datetime.now().isoformat(timespec="seconds"),
                "image_path": str(dest),
                "ref_x1": ref["x1"], "ref_y1": ref["y1"],
                "ref_x2": ref["x2"], "ref_y2": ref["y2"],
                "ref_px_dist": ref["px_dist"],
                "ref_real_dist": ref["real_dist"],
                "notas": notas_var.get().strip(),
            }
            win.destroy()

        br = ttk.Frame(win, padding=(8,4)); br.pack(fill="x")
        ttk.Button(br, text="Guardar calibracion", command=_save).pack(side="left")
        ttk.Button(br, text="Cancelar", command=win.destroy).pack(side="right")

        _redraw()
        win.wait_window()
        return result[0]


    # ── Abrir imagen en ImageJ / Fiji (Opción B) ──────────────────────────────

    def _fiji_path_load(self):
        try:
            p = _FIJI_PATH_FILE.read_text(encoding="utf-8").strip()
            return p if p and Path(p).exists() else None
        except Exception:
            return None

    def _fiji_path_save(self, path):
        try:
            _FIJI_PATH_FILE.write_text(str(path), encoding="utf-8")
        except Exception:
            pass

    def _fiji_find(self):
        saved = self._fiji_path_load()
        if saved:
            return saved
        candidates = [
            Path.home() / "Fiji.app" / "ImageJ-win64.exe",
            Path("C:/Fiji.app/ImageJ-win64.exe"),
            Path("C:/Program Files/Fiji.app/ImageJ-win64.exe"),
            Path.home() / "Desktop" / "Fiji.app" / "ImageJ-win64.exe",
            Path.home() / "Downloads" / "Fiji.app" / "ImageJ-win64.exe",
        ]
        for p in candidates:
            if p.exists():
                return str(p)
        return None

    def _open_in_imagej(self):
        image_item = self._selected_report_image()
        if image_item is None:
            messagebox.showinfo("ImageJ", "Selecciona una imagen de la lista primero.", parent=self)
            return
        img_path = Path(str(image_item.get("path", "") or ""))
        if not img_path.exists():
            messagebox.showinfo("ImageJ", "El archivo de imagen no existe.", parent=self)
            return

        fiji = self._fiji_find()
        if fiji is None:
            fiji = filedialog.askopenfilename(
                parent=self,
                title="Localizar ImageJ / Fiji (ImageJ-win64.exe)",
                filetypes=(("Ejecutables", "*.exe"), ("Todos los archivos", "*.*")),
            )
            if not fiji:
                return
            self._fiji_path_save(fiji)

        try:
            subprocess.Popen([fiji, str(img_path)])
        except Exception as ex:
            messagebox.showerror("ImageJ", f"No se pudo abrir ImageJ:\n{ex}", parent=self)

    def _open_camera_popup(self):
        try:
            import cv2
        except ImportError:
            messagebox.showinfo("Camara",
                "OpenCV no esta instalado.\nEjecutar en terminal: pip install opencv-python",
                parent=self)
            return
        if Image is None or ImageTk is None:
            messagebox.showinfo("Camara", "Pillow (PIL) no esta disponible.", parent=self)
            return

        cap = None
        backends = [cv2.CAP_DSHOW, cv2.CAP_MSMF, 0]
        for idx in range(3):
            for backend in backends:
                try:
                    c = cv2.VideoCapture(idx, backend) if backend else cv2.VideoCapture(idx)
                    if c.isOpened():
                        ret, _ = c.read()
                        if ret:
                            cap = c
                            break
                    c.release()
                except Exception:
                    pass
            if cap is not None:
                break
        if cap is None:
            messagebox.showinfo("Camara",
                "No se pudo abrir la camara.\n"
                "Verificar que no este siendo usada por otra aplicacion.",
                parent=self)
            return

        # Solicitar máxima resolución y buffer mínimo
        for res in ((3840, 2160), (1920, 1080), (1280, 720)):
            cap.set(cv2.CAP_PROP_FRAME_WIDTH,  res[0])
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, res[1])
            ret, test = cap.read()
            if ret and test is not None:
                break
        cap.set(cv2.CAP_PROP_BUFFERSIZE, 1)
        cam_w = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        cam_h = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))

        PREVIEW_W, PREVIEW_H = 820, 616

        def _fill(bgr):
            """Redimensiona el frame al tamaño del canvas sin recortar."""
            return cv2.resize(bgr, (PREVIEW_W, PREVIEW_H),
                              interpolation=cv2.INTER_LINEAR)
        captured_frame = [None]
        live = [True]
        contours_cache = [None]
        stats_cache = [None]
        frame_counter = [0]
        show_contours_var   = tk.BooleanVar(value=False)
        show_binary_var     = tk.BooleanVar(value=False)
        analysis_mode_var   = tk.StringVar(value="nodular")   # "nodular" | "laminar"
        thresh_var        = tk.IntVar(value=0)
        min_area_var      = tk.IntVar(value=getattr(self, "_cam_min_area", IMAGEJ_AREA_UMBRAL))
        measure_var       = tk.BooleanVar(value=False)
        meas_pending_cam  = []   # primer punto pendiente (coords originales de cámara)
        meas_list_cam     = []   # medidas completadas
        _cnt_computing    = [False]   # flag hilo de detección de contornos
        import queue as _queue
        _stats_queue = _queue.Queue()   # resultados de stats pasan por queue (thread-safe)

        win = tk.Toplevel(self)
        win.title(f"Camara — Calidad  [{cam_w}×{cam_h}]")
        win.resizable(True, True)   # transient removido: permite el boton de maximizar

        hovered_particle = [None]   # índice en contours_cache[0] del nódulo bajo el cursor

        # ── Layout principal: PanedWindow → stats | preview | medidas ──────────
        main_pane = ttk.PanedWindow(win, orient="horizontal")
        main_pane.pack(fill="both", expand=True)

        # Panel de stats (visible siempre, muestra area; conteo se agrega al activar)
        stats_panel = ttk.LabelFrame(main_pane, text="Conteo de nodulos", padding=(8, 6))
        main_pane.add(stats_panel, weight=0)

        # Fila siempre visible: área analizada (depende solo de calibración)
        area_row = ttk.Frame(stats_panel)
        area_row.pack(fill="x", pady=(0, 4))
        ttk.Label(area_row, text="Area analizada:", anchor="w", width=16).pack(side="left")
        area_var = tk.StringVar(value="Sin calibrar")
        ttk.Label(area_row, textvariable=area_var, foreground="#ffcc44", anchor="w").pack(side="left")
        ttk.Separator(stats_panel, orient="horizontal").pack(fill="x", pady=(0, 4))

        def _update_area_var():
            px_mm = _cam_px_mm()
            if px_mm:
                area = (cam_w / px_mm) * (cam_h / px_mm)
                area_var.set(f"{area:.2f} mm²  ({cam_w}×{cam_h} px)")
            else:
                area_var.set("Sin calibrar")

        # _update_area_var() se llama después de que cam_cal_var y _cam_px_mm estén definidos

        # ── Sección stats Nodular ─────────────────────────────────────────────
        nod_section = ttk.Frame(stats_panel)
        nod_section.pack(fill="x")
        _STAT_ROWS = [
            ("n_total",          "Nodulos totales"),
            ("n_mm2",            "Nodulos/mm²"),
            ("nodularidad",      "Nodularidad"),
            ("vermicular",       "Vermicular"),
            ("tam_grafito_clase","Tamano grafito"),
            ("diam_prom_um",     "Diam. promedio"),
            ("diam_max_um",      "Diam. max"),
            ("diam_min_um",      "Diam. min"),
        ]
        stat_vars = {}
        for key, label in _STAT_ROWS:
            rf = ttk.Frame(nod_section)
            rf.pack(fill="x", pady=1)
            ttk.Label(rf, text=label + ":", anchor="w", width=16).pack(side="left")
            sv = tk.StringVar(value="—")
            stat_vars[key] = sv
            ttk.Label(rf, textvariable=sv, foreground="#66bbff", anchor="w").pack(side="left")
        ttk.Separator(nod_section, orient="horizontal").pack(fill="x", pady=(8, 4))
        ttk.Label(nod_section, text="Distribucion por clase:", anchor="w").pack(fill="x")
        dist_vars = {}
        for category, _, _ in IMAGEJ_LIMITS:
            rf = ttk.Frame(nod_section)
            rf.pack(fill="x", pady=1)
            short = category.split("(")[0].strip()
            ttk.Label(rf, text=short + ":", anchor="w", width=9).pack(side="left")
            sv = tk.StringVar(value="—")
            dist_vars[category] = sv
            ttk.Label(rf, textvariable=sv, foreground="#66bbff", anchor="w").pack(side="left")

        # ── Sección stats Laminar (ISO 945) ───────────────────────────────────
        lam_section = ttk.Frame(stats_panel)
        # lam_section empieza oculta
        _LAM_ROWS = [
            ("n_total",            "Laminillas"),
            ("n_mm2",              "Laminillas/mm²"),
            ("long_prom_um",       "Long. promedio"),
            ("long_max_um",        "Long. max"),
            ("long_min_um",        "Long. min"),
            ("aspect_ratio_prom",  "Largo/ancho"),
            ("morfologia_iso",     "Morfología ISO"),
            ("tam_clase",          "Tamaño clase"),
            ("n_mns",              "Posibles MnS"),
        ]
        lam_stat_vars = {}
        for key, label in _LAM_ROWS:
            rf = ttk.Frame(lam_section)
            rf.pack(fill="x", pady=1)
            ttk.Label(rf, text=label + ":", anchor="w", width=16).pack(side="left")
            sv = tk.StringVar(value="—")
            lam_stat_vars[key] = sv
            ttk.Label(rf, textvariable=sv, foreground="#66bbff", anchor="w").pack(side="left")
        ttk.Separator(lam_section, orient="horizontal").pack(fill="x", pady=(8, 4))
        ttk.Label(lam_section, text="Distribucion por longitud:", anchor="w").pack(fill="x")
        lam_dist_vars = {}
        for category, _, _ in IMAGEJ_LIMITS:
            rf = ttk.Frame(lam_section)
            rf.pack(fill="x", pady=1)
            short = category.split("(")[0].strip()
            ttk.Label(rf, text=short + ":", anchor="w", width=9).pack(side="left")
            sv = tk.StringVar(value="—")
            lam_dist_vars[category] = sv
            ttk.Label(rf, textvariable=sv, foreground="#66bbff", anchor="w").pack(side="left")

        def _update_stats_panel(stats):
            dash = "—"
            if stats is None:
                for v in stat_vars.values():
                    v.set("...")
                for v in dist_vars.values():
                    v.set("...")
                return
            fmt = self._format_metric
            stat_vars["n_total"].set(str(stats["n_total"]))
            stat_vars["n_mm2"].set(fmt(stats["n_mm2"], 2))
            stat_vars["nodularidad"].set(f"{fmt(stats['nodularidad'], 1)}%")
            stat_vars["vermicular"].set(f"{fmt(stats['vermicular'], 1)}%")
            stat_vars["tam_grafito_clase"].set(stats.get("tam_grafito_clase", "") or dash)
            stat_vars["diam_prom_um"].set(f"{fmt(stats['diam_prom_um'], 1)} µm")
            stat_vars["diam_max_um"].set(f"{fmt(stats['diam_max_um'], 1)} µm")
            stat_vars["diam_min_um"].set(f"{fmt(stats['diam_min_um'], 1)} µm")
            counts = stats.get("counts", {})
            for category, sv in dist_vars.items():
                sv.set(str(counts.get(category, 0)))

        def _update_laminar_stats_panel(stats):
            dash = "—"
            if stats is None:
                for v in lam_stat_vars.values():
                    v.set("...")
                for v in lam_dist_vars.values():
                    v.set("...")
                return
            fmt = self._format_metric
            lam_stat_vars["n_total"].set(str(stats["n_total"]))
            lam_stat_vars["n_mm2"].set(fmt(stats["n_mm2"], 2))
            lam_stat_vars["long_prom_um"].set(f"{fmt(stats['long_prom_um'], 1)} µm")
            lam_stat_vars["long_max_um"].set(f"{fmt(stats['long_max_um'], 1)} µm")
            lam_stat_vars["long_min_um"].set(f"{fmt(stats['long_min_um'], 1)} µm")
            lam_stat_vars["aspect_ratio_prom"].set(fmt(stats["aspect_ratio_prom"], 2))
            morph = stats.get("morfologia_iso", "—")
            lam_stat_vars["morfologia_iso"].set(morph)
            lam_stat_vars["tam_clase"].set(stats.get("tam_clase", "") or dash)
            n_mns = stats.get("n_mns", 0)
            lam_stat_vars["n_mns"].set(f"{n_mns}  ({stats.get('n_mns_mm2', 0):.1f}/mm²)" if n_mns else "0")
            counts = stats.get("counts", {})
            for category, sv in lam_dist_vars.items():
                sv.set(str(counts.get(category, 0)))

        def _switch_analysis_mode(mode):
            analysis_mode_var.set(mode)
            contours_cache[0] = None
            stats_cache[0] = None
            if mode == "nodular":
                lam_section.pack_forget()
                nod_section.pack(fill="x")
                stats_panel.config(text="Conteo de nodulos")
                btn_save_count.config(text="Guardar y contar nodulos")
                btn_contours.config(text="Conteo nodulos")
            else:
                nod_section.pack_forget()
                lam_section.pack(fill="x")
                stats_panel.config(text="Analisis grafito laminar (ISO 945)")
                btn_save_count.config(text="Guardar y analizar laminar")
                btn_contours.config(text="Ver laminillas")

        # on_redraw para overlay de mediciones y nódulo hover
        # Las medidas van PRIMERO: si el hover lanza excepción las medidas siguen visibles
        def _cam_on_redraw(cv):
            sx = PREVIEW_W / max(cam_w, 1); sy = PREVIEW_H / max(cam_h, 1)
            # ── Medidas (siempre se dibujan primero) ──────────────────────────
            if meas_pending_cam:
                dx = meas_pending_cam[0][0] * sx; dy = meas_pending_cam[0][1] * sy
                cx, cy = _i2c_prev(dx, dy)
                cv.create_oval(cx-5, cy-5, cx+5, cy+5, fill="#ff4444", outline="white", width=1)
            for m in meas_list_cam:
                if m.get("type") == "particle" or "x1" not in m:
                    continue   # partículas no tienen coordenadas de línea
                cx1, cy1 = _i2c_prev(m["x1"] * sx, m["y1"] * sy)
                cx2, cy2 = _i2c_prev(m["x2"] * sx, m["y2"] * sy)
                cv.create_line(cx1, cy1, cx2, cy2, fill="#00dd88", width=2)
                for px, py in ((cx1, cy1), (cx2, cy2)):
                    cv.create_oval(px-3, py-3, px+3, py+3, fill="#00dd88", outline="")
                mx, my = (cx1 + cx2) / 2, (cy1 + cy2) / 2
                lbl = m.get("label", "")
                cv.create_text(mx+1, my-9, text=lbl, fill="#000", font=("TkDefaultFont", 8, "bold"))
                cv.create_text(mx,   my-10, text=lbl, fill="#00dd88", font=("TkDefaultFont", 8, "bold"))
            # ── Nódulos guardados en tabla (contorno + número de fila) ───────────
            try:
                import numpy as np
                for row_n, m in enumerate(meas_list_cam, 1):
                    cnt = m.get("contour")
                    if m.get("type") != "particle" or cnt is None:
                        continue
                    scaled = cnt.astype(np.float32).copy()
                    scaled[..., 0] *= sx; scaled[..., 1] *= sy
                    pts = [_i2c_prev(float(x), float(y)) for x, y in scaled.reshape(-1, 2)]
                    flat = [c for xy in pts for c in xy]
                    if len(flat) >= 4:
                        cv.create_polygon(flat, outline="#44aaff", fill="", width=2)
                    if pts:
                        cx = sum(p[0] for p in pts) / len(pts)
                        cy = sum(p[1] for p in pts) / len(pts)
                        cv.create_text(cx+1, cy+1, text=str(row_n), fill="#000",
                                       font=("TkDefaultFont", 8, "bold"))
                        cv.create_text(cx,   cy,   text=str(row_n), fill="#44aaff",
                                       font=("TkDefaultFont", 8, "bold"))
            except Exception:
                pass
            # ── Nódulo resaltado (hover) ───────────────────────────────────────
            try:
                hi = hovered_particle[0]
                cnts = contours_cache[0] or []
                if hi is not None and 0 <= hi < len(cnts):
                    import numpy as np
                    p = cnts[hi]
                    scaled = p["contour"].astype(np.float32).copy()
                    scaled[..., 0] *= sx; scaled[..., 1] *= sy
                    pts_canvas = [_i2c_prev(x, y) for x, y in scaled.reshape(-1, 2)]
                    flat = [c for xy in pts_canvas for c in xy]
                    if len(flat) >= 4:
                        cv.create_polygon(flat, outline="#ffff00", fill="", width=2)
            except Exception:
                pass

        # Preview con zoom/pan
        preview_frame = ttk.Frame(main_pane)
        main_pane.add(preview_frame, weight=1)
        lbl_preview, _show_preview, _reset_preview, _c2i_prev, _i2c_prev = self._make_zoom_pan_preview(
            preview_frame, PREVIEW_W, PREVIEW_H, on_redraw=_cam_on_redraw)
        lbl_preview.pack(fill="both", expand=True)

        # ── Panel derecho: tabla de medidas + info de nódulo hover ─────────────
        meas_panel = ttk.LabelFrame(main_pane, text="Mediciones", padding=4)
        main_pane.add(meas_panel, weight=1)
        meas_tv = ttk.Treeview(meas_panel, columns=("tipo",), show="headings", height=12,
                               selectmode="browse")
        meas_tv.heading("tipo", text="T")
        meas_tv.column("tipo", width=22, minwidth=22, stretch=False, anchor="center")
        meas_sb_x = ttk.Scrollbar(meas_panel, orient="horizontal", command=meas_tv.xview)
        meas_tv.configure(xscrollcommand=meas_sb_x.set)
        meas_tv.pack(fill="both", expand=True)
        meas_sb_x.pack(fill="x")

        ttk.Label(meas_panel, text="Shift+clic = agregar nodulo", foreground="#888",
                  font=("TkDefaultFont", 7)).pack(anchor="w")

        hover_lbl = ttk.Label(meas_panel, text="", justify="left",
                              foreground="#0077cc", wraplength=148)
        hover_lbl.pack(fill="x", pady=(4, 0))

        # Columnas dinámicas según los tipos de datos presentes
        # Líneas → columna Distancia; Partículas → Diam, Area, Circ, Clase
        _COL_LINE = [("dist", "Distancia", 90, "w")]
        _COL_PART = [
            ("diam",  "Diám",  68, "e"),
            ("area",  "Área",  72, "e"),
            ("circ",  "Circ",  46, "e"),
            ("clase", "Clase", 52, "w"),
        ]

        def _rebuild_meas_table():
            has_lines = any(m.get("type") != "particle" for m in meas_list_cam)
            has_part  = any(m.get("type") == "particle"  for m in meas_list_cam)
            cols = [("tipo", "T", 22, "center")]
            if has_lines: cols += _COL_LINE
            if has_part:  cols += _COL_PART
            col_ids = [c[0] for c in cols]
            meas_tv.configure(columns=col_ids)
            for cid, title, w, anch in cols:
                meas_tv.heading(cid, text=title)
                meas_tv.column(cid, width=w, minwidth=w, anchor=anch, stretch=False)
            meas_tv.delete(*meas_tv.get_children())
            for m in meas_list_cam:
                is_p  = m.get("type") == "particle"
                tipo  = "P" if is_p else "→"
                row   = {"tipo": tipo}
                if has_lines:
                    row["dist"] = "" if is_p else m.get("label", "")
                if has_part:
                    if is_p:
                        unit = m.get("unit", "")
                        row["diam"]  = f"{m.get('diam',0):.2f}{unit}"
                        row["area"]  = f"{m.get('area',0):.3f}"
                        row["circ"]  = f"{m.get('circ',0):.2f}"
                        row["clase"] = m.get("clase", "")
                    else:
                        row["diam"] = row["area"] = row["circ"] = row["clase"] = ""
                meas_tv.insert("", "end", values=[row.get(c, "") for c in col_ids])

            # Auto-sizing: ajustar ancho de cada columna al contenido
            try:
                import tkinter.font as _tkfont
                f = _tkfont.nametofont("TkDefaultFont")
                for cid, title, min_w, anch in cols:
                    max_w = f.measure(title) + 14
                    for iid in meas_tv.get_children():
                        cell = str(meas_tv.set(iid, cid))
                        max_w = max(max_w, f.measure(cell) + 14)
                    meas_tv.column(cid, width=max(min_w, max_w))
            except Exception:
                pass

        def _refresh_meas_tv():
            _rebuild_meas_table()

        status_var = tk.StringVar(value=f"En vivo  {cam_w}×{cam_h}")
        ttk.Label(win, textvariable=status_var, anchor="center").pack(fill="x", pady=(2, 0))

        # ── Selector de calibración ──────────────────────────────────────────
        _cals_cam  = self._cal_load()
        _cal_names = ["(sin calibrar)"] + [c["nombre"] for c in _cals_cam]
        cam_cal_var = tk.StringVar(value=_cal_names[1] if len(_cal_names) > 1 else _cal_names[0])

        def _cam_cal_id():
            name = cam_cal_var.get()
            c = next((x for x in _cals_cam if x["nombre"] == name), None)
            return c["id"] if c else None

        def _cam_px_mm():
            return self._cal_get_px_per_mm(_cam_cal_id())

        # Ahora que cam_cal_var y _cam_px_mm están definidos, conectar el trace del área
        cam_cal_var.trace_add("write", lambda *_: _update_area_var())
        _update_area_var()

        cal_row = ttk.Frame(win, padding=(8, 2))
        cal_row.pack(fill="x")
        ttk.Label(cal_row, text="Aumento / calibracion:").pack(side="left")
        ttk.Combobox(cal_row, textvariable=cam_cal_var, values=_cal_names,
                     state="readonly", width=28).pack(side="left", padx=(6, 0))

        mode_row = ttk.Frame(win, padding=(8, 2))
        mode_row.pack(fill="x")
        ttk.Label(mode_row, text="Modo:").pack(side="left")
        ttk.Radiobutton(mode_row, text="Nodular", variable=analysis_mode_var, value="nodular",
                        command=lambda: _switch_analysis_mode("nodular")).pack(side="left", padx=(6, 0))
        ttk.Radiobutton(mode_row, text="Laminar (ISO 945)", variable=analysis_mode_var, value="laminar",
                        command=lambda: _switch_analysis_mode("laminar")).pack(side="left", padx=(6, 0))

        btn_row = ttk.Frame(win, padding=(8, 6))
        btn_row.pack(fill="x")
        btn_cap_live = ttk.Button(btn_row, text="Capturar")
        btn_cap_live.pack(side="left")
        btn_file = ttk.Button(btn_row, text="Abrir archivo")
        btn_file.pack(side="left", padx=(6, 0))
        btn_save = ttk.Button(btn_row, text="Guardar en informe")
        btn_save.pack(side="left", padx=6)
        btn_save_count = ttk.Button(btn_row, text="Guardar y contar nodulos")
        btn_save_count.pack(side="left")
        btn_contours = ttk.Checkbutton(btn_row, text="Conteo nodulos", variable=show_contours_var)
        btn_contours.pack(side="left", padx=6)
        ttk.Checkbutton(btn_row, text="Ver binario", variable=show_binary_var).pack(side="left")
        ttk.Button(btn_row, text="Cerrar", command=lambda: _on_close()).pack(side="right")
        ttk.Button(btn_row, text="Reset zoom", command=_reset_preview).pack(side="right", padx=6)

        meas_row = ttk.Frame(win, padding=(8, 2))
        meas_row.pack(fill="x")
        ttk.Label(meas_row, text="Clic = medir linea  |  Shift+clic = agregar nodulo",
                  foreground="#666").pack(side="left")
        btn_del_meas = ttk.Button(meas_row, text="Borrar ultima")
        btn_del_meas.pack(side="right", padx=(0, 4))
        btn_del_all_meas = ttk.Button(meas_row, text="Borrar todas")
        btn_del_all_meas.pack(side="left", padx=(4, 0))
        meas_status_var = tk.StringVar(value="")
        ttk.Label(meas_row, textvariable=meas_status_var, foreground="#00dd88").pack(side="left", padx=(12, 0))

        thresh_row = ttk.Frame(win, padding=(8, 2))
        thresh_row.pack(fill="x")
        ttk.Label(thresh_row, text="Umbral:").pack(side="left")
        thresh_scale = ttk.Scale(thresh_row, from_=0, to=255, orient="horizontal",
                                 variable=thresh_var, length=220)
        thresh_scale.pack(side="left", padx=(6, 4))
        thresh_lbl = ttk.Label(thresh_row, text="Auto (Otsu)", width=12)
        thresh_lbl.pack(side="left")

        def _on_thresh_change(*_):
            v = thresh_var.get()
            thresh_lbl.config(text=f"Auto (Otsu)" if v <= 0 else str(v))
            contours_cache[0] = None
            stats_cache[0] = None

        thresh_var.trace_add("write", _on_thresh_change)
        ttk.Button(thresh_row, text="Reset Otsu",
                   command=lambda: thresh_var.set(0)).pack(side="left", padx=(8, 0))

        ttk.Label(thresh_row, text="Area min (px):").pack(side="left", padx=(20, 4))
        min_area_sb = tk.Spinbox(thresh_row, from_=1, to=10000, increment=10,
                                 textvariable=min_area_var, width=7, justify="center")
        min_area_sb.pack(side="left")

        def _on_min_area_change(*_):
            contours_cache[0] = None
            stats_cache[0] = None
            try:
                self._cam_min_area = int(min_area_var.get())
            except Exception:
                pass

        min_area_var.trace_add("write", _on_min_area_change)

        def _make_binary(frame_bgr, blur_sz=5):
            import numpy as np
            gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
            k = blur_sz if blur_sz % 2 == 1 else blur_sz + 1
            blurred = cv2.GaussianBlur(gray, (k, k), 0)
            tval = thresh_var.get()
            if tval <= 0:
                _, binary = cv2.threshold(
                    blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
            else:
                _, binary = cv2.threshold(blurred, tval, 255, cv2.THRESH_BINARY_INV)
            return binary

        def _lam_contour_color(flake):
            """Colorea por tipo: amarillo=MnS, rojo/verde/azul/gris=grafito por tamaño."""
            if flake.get("particle_type") == "mns":
                return (0, 220, 220)   # amarillo (BGR) — posible MnS
            length_um = flake.get("length_um") or (flake["length_px"] / max(_cam_px_mm() or IMAGEJ_RESOLUCION_PX_MM, 1)) * 1000
            if length_um >= 250:   # Clase 3
                return (0, 60, 220)    # rojo-anaranjado (grandes)
            elif length_um >= 60:  # Clase 5-4
                return (0, 200, 0)     # verde (medianos)
            elif length_um >= 15:  # Clase 7-6
                return (220, 120, 0)   # azul (finos)
            else:                  # Clase 8
                return (180, 180, 180) # gris (muy finos)

        def _show_frame(frame_bgr):
            px_mm = _cam_px_mm()
            do_contours = show_contours_var.get()
            mode = analysis_mode_var.get()

            if live[0]:
                frame_counter[0] += 1
                if do_contours and frame_counter[0] % 25 == 1 and not _cnt_computing[0]:
                    _cnt_computing[0] = True
                    _fbg = frame_bgr.copy()
                    _t = thresh_var.get(); _ma = min_area_var.get(); _pmm = px_mm; _mode = mode
                    def _cnt_worker():
                        try:
                            if _mode == "laminar":
                                cnts = self._get_laminar_contours(_fbg, threshold=_t,
                                                                  min_area=_ma, blur_size=11)
                                # inyectar length_um para el color
                                _s = float(_pmm) if _pmm else IMAGEJ_RESOLUCION_PX_MM
                                for f in cnts:
                                    f["length_um"] = (f["length_px"] / _s) * 1000
                                sts = self._count_laminar_opencv(_fbg, px_per_mm=_pmm,
                                                                 threshold=_t, min_area=_ma)
                            else:
                                cnts = self._get_nodule_contours(_fbg, blur_size=11,
                                                                 threshold=_t, min_area=_ma)
                                sts  = self._count_nodules_opencv(_fbg, px_per_mm=_pmm,
                                                                  threshold=_t, min_area=_ma)
                        except Exception:
                            cnts = []; sts = None
                        finally:
                            _cnt_computing[0] = False
                        contours_cache[0] = cnts
                        _stats_queue.put(sts)
                    import threading as _th; _th.Thread(target=_cnt_worker, daemon=True).start()
            else:
                if do_contours and contours_cache[0] is None:
                    try:
                        if mode == "laminar":
                            cnts = self._get_laminar_contours(frame_bgr, threshold=thresh_var.get(),
                                                              min_area=min_area_var.get())
                            _s = float(px_mm) if px_mm else IMAGEJ_RESOLUCION_PX_MM
                            for f in cnts:
                                f["length_um"] = (f["length_px"] / _s) * 1000
                            contours_cache[0] = cnts
                        else:
                            contours_cache[0] = self._get_nodule_contours(
                                frame_bgr, threshold=thresh_var.get(),
                                min_area=min_area_var.get())
                    except Exception:
                        contours_cache[0] = []
                if do_contours and stats_cache[0] is None:
                    try:
                        if mode == "laminar":
                            stats_cache[0] = self._count_laminar_opencv(
                                frame_bgr, px_per_mm=px_mm, threshold=thresh_var.get(),
                                min_area=min_area_var.get())
                            _update_laminar_stats_panel(stats_cache[0])
                        else:
                            stats_cache[0] = self._count_nodules_opencv(
                                frame_bgr, px_per_mm=px_mm, threshold=thresh_var.get(),
                                min_area=min_area_var.get())
                            _update_stats_panel(stats_cache[0])
                    except Exception:
                        stats_cache[0] = None

            if show_binary_var.get():
                blur_sz = 11 if live[0] else 5
                binary = _make_binary(frame_bgr, blur_sz)
                display_bgr = _fill(cv2.cvtColor(binary, cv2.COLOR_GRAY2BGR))
            else:
                display_bgr = _fill(frame_bgr)

            if do_contours:
                import numpy as np
                fh, fw = frame_bgr.shape[:2]
                sx = PREVIEW_W / max(fw, 1); sy = PREVIEW_H / max(fh, 1)
                for p in (contours_cache[0] or []):
                    cnt = p["contour"].astype(np.float32).copy()
                    cnt[..., 0] *= sx; cnt[..., 1] *= sy
                    if mode == "laminar":
                        color = _lam_contour_color(p)
                    else:
                        color = (0, 220, 0) if p["circ"] >= 0.5 else (0, 140, 255)
                    cv2.drawContours(display_bgr, [cnt.astype(np.int32)], -1, color, 2)

            _show_preview(display_bgr)

        def _update_live():
            if not live[0] or not win.winfo_exists():
                return
            ret, frame = cap.read()
            if ret:
                try:
                    _show_frame(frame)
                except Exception:
                    pass   # nunca dejar morir el loop por una excepción en _show_frame
            # Leer stats que vienen del hilo de detección (thread-safe via queue)
            try:
                sts = _stats_queue.get_nowait()
                stats_cache[0] = sts
                if analysis_mode_var.get() == "laminar":
                    _update_laminar_stats_panel(sts)
                else:
                    _update_stats_panel(sts)
            except _queue.Empty:
                pass
            # Hover: sondear posición del mouse cada 3 frames (~100ms) sin <Motion>
            if show_contours_var.get() and frame_counter[0] % 3 == 0:
                try:
                    mx = lbl_preview.winfo_pointerx() - lbl_preview.winfo_rootx()
                    my = lbl_preview.winfo_pointery() - lbl_preview.winfo_rooty()
                    if 0 <= mx < PREVIEW_W and 0 <= my < PREVIEW_H:
                        _launch_hover(mx, my)
                except Exception:
                    pass
            win.after(33, _update_live)

        def _enter_frozen():
            """Activa el estado de frame congelado (captura o archivo)."""
            live[0] = False
            btn_cap_live.config(text="Nueva foto")

        def _do_capture_live():
            if captured_frame[0] is not None:
                # Ya congelado: volver a live
                live[0] = True
                captured_frame[0] = None
                meas_pending_cam.clear()
                meas_list_cam.clear()
                meas_status_var.set("")
                status_var.set(f"En vivo  {cam_w}×{cam_h}")
                btn_cap_live.config(text="Capturar")
                contours_cache[0] = None
                stats_cache[0] = None
                _update_live()
                return
            # Capturar frame actual
            frame = None
            for _ in range(3):
                ret, f = cap.read()
                if ret: frame = f
            if frame is None:
                return
            captured_frame[0] = frame
            _show_frame(frame)
            h, w = frame.shape[:2]
            status_var.set(f"Congelado {w}×{h} — usa Medir o guarda")
            _enter_frozen()

        btn_cap_live.config(command=_do_capture_live)

        def _on_canvas_click(event):
            frame = captured_frame[0]   # None si está en live (el overlay se dibuja igual)
            dx, dy = _c2i_prev(event.x, event.y)
            orig_x = dx * cam_w / PREVIEW_W
            orig_y = dy * cam_h / PREVIEW_H
            if not (0 <= orig_x <= cam_w and 0 <= orig_y <= cam_h):
                return
            if not meas_pending_cam:
                meas_pending_cam.append((orig_x, orig_y))
                if frame is not None: _show_frame(frame)
                meas_status_var.set("Clic en el segundo punto…")
                return
            x1, y1 = meas_pending_cam[0]
            meas_pending_cam.clear()
            x2, y2 = orig_x, orig_y
            px_d = ((x2-x1)**2 + (y2-y1)**2) ** 0.5
            cal = next((c for c in _cals_cam if c["nombre"] == cam_cal_var.get()), None)
            if cal and cal.get("px_per_unit"):
                real = px_d / cal["px_per_unit"]
                label = f"{real:.2f} {cal.get('unit','µm')}"
            else:
                label = f"{px_d:.1f} px"
            meas_list_cam.append({"x1":x1,"y1":y1,"x2":x2,"y2":y2,"px_dist":px_d,"label":label})
            meas_status_var.set(f"{len(meas_list_cam)} medida(s) — {label}")
            _refresh_meas_tv()
            if frame is not None: _show_frame(frame)

        import threading as _threading
        _hover_computing = [False]

        def _launch_hover(ex, ey):
            """Lanza detección de hover en hilo de fondo con las coords dadas."""
            if _hover_computing[0]:
                return
            cnts = list(contours_cache[0] or [])
            if not cnts:
                if hovered_particle[0] is not None:
                    hovered_particle[0] = None
                    hover_lbl.config(text="")
                return
            try:
                dx0, dy0 = _c2i_prev(ex, ey)
                ox = dx0 * cam_w / PREVIEW_W
                oy = dy0 * cam_h / PREVIEW_H
            except Exception:
                return
            _hover_computing[0] = True
            def _worker():
                try:
                    import cv2 as _cv2
                    best_idx = None; best_dist = -9999.0
                    for i, p in enumerate(cnts):
                        d = _cv2.pointPolygonTest(p["contour"], (float(ox), float(oy)), True)
                        if d >= 0:
                            best_idx = i; best_dist = d; break
                        if d > best_dist:
                            best_idx = i; best_dist = d
                    idx = best_idx if best_dist is not None and best_dist >= -15 else None
                except Exception:
                    idx = None
                finally:
                    _hover_computing[0] = False
                if idx == hovered_particle[0]:
                    return
                hovered_particle[0] = idx
                if not win.winfo_exists():
                    return
                def _ui():
                    if idx is not None and 0 <= idx < len(cnts):
                        p = cnts[idx]
                        cal = next((c for c in _cals_cam if c["nombre"] == cam_cal_var.get()), None)
                        if cal and cal.get("px_per_unit"):
                            pu = cal["px_per_unit"]; unit = cal.get("unit", "µm")
                            diam = p.get("diam_px", 0) / pu
                            area = p.get("area_px", 0) / (pu ** 2)
                            hover_lbl.config(text=(
                                f"Diam: {diam:.2f} {unit}\n"
                                f"Area: {area:.4f} {unit}²\n"
                                f"Circ: {p['circ']:.3f}  "
                                f"{'Nodular' if p['circ']>=0.5 else 'Vermicular'}"
                            ))
                        else:
                            hover_lbl.config(text=(
                                f"Diam: {p.get('diam_px',0):.1f} px\n"
                                f"Area: {p.get('area_px',0):.0f} px²\n"
                                f"Circ: {p['circ']:.3f}"
                            ))
                    else:
                        hover_lbl.config(text="")
                    if captured_frame[0] is not None:
                        _show_frame(captured_frame[0])
                win.after(0, _ui)
            _threading.Thread(target=_worker, daemon=True).start()

        def _on_shift_click(event):
            """Shift+clic: agrega el nódulo bajo el cursor a la tabla sin pausar."""
            idx = hovered_particle[0]
            cnts = contours_cache[0] or []
            if idx is None or idx >= len(cnts):
                return
            p = cnts[idx]
            cal = next((c for c in _cals_cam if c["nombre"] == cam_cal_var.get()), None)
            if cal and cal.get("px_per_unit"):
                pu = cal["px_per_unit"]; unit = cal.get("unit", "µm")
                diam_v = p.get("diam_px", 0) / pu
                area_v = p.get("area_px", 0) / (pu ** 2)
            else:
                unit = "px"
                diam_v = p.get("diam_px", 0)
                area_v = p.get("area_px", 0)
            clase = "Nod" if p["circ"] >= 0.5 else "Verm"
            meas_list_cam.append({
                "type": "particle",
                "diam": diam_v, "area": area_v,
                "circ": p["circ"], "clase": clase, "unit": unit,
                "label": f"D:{diam_v:.2f}{unit}",
                "contour": p["contour"].copy(),   # para dibujar en canvas con número
            })
            meas_status_var.set(f"{len(meas_list_cam)} entrada(s)")
            _refresh_meas_tv()
            return "break"   # evita que <Button-1> también se dispare

        lbl_preview.bind("<Button-1>", _on_canvas_click)
        lbl_preview.bind("<Shift-Button-1>", _on_shift_click)
        lbl_preview.bind("<Double-Button-1>", lambda e: None)
        # <Motion> eliminado: hover se sondea dentro de _update_live

        def _del_last():
            if meas_list_cam: meas_list_cam.pop()
            meas_pending_cam.clear()
            meas_status_var.set(f"{len(meas_list_cam)} medida(s)" if meas_list_cam else "")
            _refresh_meas_tv()
            if captured_frame[0] is not None: _show_frame(captured_frame[0])
        def _del_all():
            meas_list_cam.clear(); meas_pending_cam.clear()
            meas_status_var.set(""); _refresh_meas_tv()
            if captured_frame[0] is not None: _show_frame(captured_frame[0])
        btn_del_meas.config(command=_del_last)
        btn_del_all_meas.config(command=_del_all)

        def _load_from_file():
            from tkinter import filedialog
            path = filedialog.askopenfilename(
                parent=win,
                title="Seleccionar imagen",
                filetypes=(
                    ("Imagenes", "*.jpg *.jpeg *.png *.bmp *.tif *.tiff"),
                    ("Todos los archivos", "*.*"),
                ),
            )
            if not path:
                return
            frame = cv2.imread(path)
            if frame is None:
                messagebox.showerror("Error", f"No se pudo leer la imagen:\n{path}", parent=win)
                return
            live[0] = False
            contours_cache[0] = None
            stats_cache[0] = None
            captured_frame[0] = frame
            _show_frame(frame)
            status_var.set(f"Archivo: {Path(path).name}")
            _enter_frozen()

        def _toggle_contours():
            contours_cache[0] = None
            stats_cache[0] = None
            frame_counter[0] = 0
            if captured_frame[0] is not None:
                _show_frame(captured_frame[0])
            elif not show_contours_var.get():
                _update_stats_panel(None)

        btn_file.config(command=_load_from_file)
        btn_contours.config(command=_toggle_contours)

        def _pick_material():
            if self._selected_index is not None:
                return self.reports[self._selected_index].get("material", "") or None
            if self._selected_group is None:
                return None
            base = self._selected_group["base"]
            lote = self._selected_group["lote"]
            indexes = self._group_report_indexes(base, lote)
            materials = [self.reports[i].get("material", "") for i in indexes
                         if self.reports[i].get("material", "")]
            if not materials:
                return None
            if len(materials) == 1:
                return materials[0]
            picked = {"v": None}
            dlg = tk.Toplevel(win)
            dlg.title("Guardar para material")
            dlg.transient(win)
            dlg.grab_set()
            dlg.resizable(False, False)
            f = ttk.Frame(dlg, padding=14)
            f.pack(fill="both")
            ttk.Label(f, text="En que material guardar la foto?").pack(anchor="w", pady=(0, 8))
            var = tk.StringVar(value=materials[0])
            for m in materials:
                ttk.Radiobutton(f, text=m, variable=var, value=m).pack(anchor="w")
            bf = ttk.Frame(f)
            bf.pack(fill="x", pady=(10, 0))
            def _accept():
                picked["v"] = var.get()
                dlg.destroy()
            ttk.Button(bf, text="Guardar aqui", command=_accept).pack(side="right")
            ttk.Button(bf, text="Cancelar", command=dlg.destroy).pack(side="right", padx=6)
            dlg.wait_window()
            return picked["v"]

        def _fresh_frame():
            """Lee 3 frames para vaciar el buffer y devuelve el más reciente."""
            f = None
            for _ in range(3):
                ret, fr = cap.read()
                if ret:
                    f = fr
            return f

        def _do_save():
            frame = captured_frame[0]
            if frame is None:
                frame = _fresh_frame()
                if frame is None:
                    messagebox.showinfo("Camara", "No se pudo obtener imagen.", parent=win)
                    return
            material = _pick_material()
            if material is None:
                return
            fname = f"camara_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
            comment = simpledialog.askstring("Observacion", "Comentario para la foto:", parent=win)
            if comment is None:
                return
            dest_dir = Path(ensure_quality_images_dir())
            dest = dest_dir / fname
            cv2.imwrite(str(dest), frame, [cv2.IMWRITE_JPEG_QUALITY, 97])
            cal_id = _cam_cal_id()
            item = {
                "id": uuid.uuid4().hex,
                "nombre": fname,
                "path": str(dest),
                "comentario": comment.strip(),
                "added_at": datetime.now().isoformat(timespec="seconds"),
            }
            if cal_id:
                item["calibration_id"] = cal_id
            if meas_list_cam:
                item["measurements"] = list(meas_list_cam)
                item["px_per_unit"] = (next((c for c in _cals_cam if c["nombre"] == cam_cal_var.get()), {}) or {}).get("px_per_unit")
                item["meas_unit"]   = (next((c for c in _cals_cam if c["nombre"] == cam_cal_var.get()), {}) or {}).get("unit", "µm")
            if self._selected_index is not None:
                self._report_images.append(item)
                self._report_images = self._normalize_report_images(self._report_images)
                self._refresh_images_ui()
                self._images_changed()
            elif self._selected_group is not None:
                indexes = self._group_report_indexes(
                    self._selected_group["base"], self._selected_group["lote"])
                for idx in indexes:
                    if self.reports[idx].get("material", "") == material:
                        imgs = self._normalize_report_images(self.reports[idx].get("imagenes", []))
                        imgs.append(item)
                        self.reports[idx]["imagenes"] = imgs
                        save_quality_reports(self.reports)
                        break
            status_var.set(f"Guardado en '{material}'")

        def _do_save_and_count():
            frame = captured_frame[0]
            if frame is None:
                frame = _fresh_frame()
                if frame is None:
                    messagebox.showinfo("Camara", "No se pudo obtener imagen.", parent=win)
                    return
            material = _pick_material()
            if material is None:
                return
            mode = analysis_mode_var.get()
            fname = f"camara_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.jpg"
            comment = simpledialog.askstring("Observacion", "Comentario para la foto:", parent=win)
            if comment is None:
                return
            dest_dir = Path(ensure_quality_images_dir())
            dest = dest_dir / fname
            cv2.imwrite(str(dest), frame, [cv2.IMWRITE_JPEG_QUALITY, 97])
            cal_id = _cam_cal_id()
            sample_item = {
                "id": uuid.uuid4().hex,
                "nombre": fname,
                "path": str(dest),
                "comentario": comment.strip(),
                "added_at": datetime.now().isoformat(timespec="seconds"),
            }
            if cal_id:
                sample_item["calibration_id"] = cal_id
            px_per_mm = _cam_px_mm()
            status_var.set("Analizando...")
            win.update_idletasks()

            # ── Análisis según modo ───────────────────────────────────────────
            if mode == "laminar":
                try:
                    stats = self._count_laminar_opencv(frame, px_per_mm=px_per_mm)
                except Exception as ex:
                    messagebox.showerror("Analisis laminar", f"Error al analizar:\n{ex}", parent=win)
                    status_var.set("Error en analisis")
                    return
                if stats is None:
                    messagebox.showinfo("Analisis laminar",
                        "No se encontraron laminillas en la imagen.\n"
                        "Verificar imagen de microestructura con fondo claro.",
                        parent=win)
                    status_var.set("Sin particulas detectadas")
                    return
                # stats_key: subset serializable (sin "flakes" que tiene arrays numpy)
                sample_item["opencv_stats"] = {
                    "mode":              "laminar",
                    "n_total":           stats["n_total"],
                    "n_mm2":             stats["n_mm2"],
                    "long_prom_um":      stats["long_prom_um"],
                    "long_max_um":       stats["long_max_um"],
                    "long_min_um":       stats["long_min_um"],
                    "aspect_ratio_prom": stats["aspect_ratio_prom"],
                    "morfologia_iso":    stats["morfologia_iso"],
                    "morfologia_label":  stats.get("morfologia_label", ""),
                    "tam_clase":         stats.get("tam_clase", ""),
                    "counts":            dict(stats["counts"]),
                    "n_mns":             stats.get("n_mns", 0),
                    "n_mns_mm2":         stats.get("n_mns_mm2", 0),
                    "px_per_mm":         stats.get("px_per_mm", IMAGEJ_RESOLUCION_PX_MM),
                    # campos que _merge_imagej_stats necesita (dummy para compatibilidad)
                    "nodularidad": 0, "vermicular": 0,
                    "diam_prom_um": stats["long_prom_um"],
                    "diam_max_um":  stats["long_max_um"],
                    "diam_min_um":  stats["long_min_um"],
                }
            else:
                try:
                    stats = self._count_nodules_opencv(frame, px_per_mm=px_per_mm)
                except Exception as ex:
                    messagebox.showerror("Conteo de nodulos", f"Error al analizar:\n{ex}", parent=win)
                    status_var.set("Error en analisis")
                    return
                if stats is None:
                    messagebox.showinfo("Conteo de nodulos",
                        "No se encontraron particulas en la imagen.\n"
                        "Verificar imagen de microestructura con fondo claro.",
                        parent=win)
                    status_var.set("Sin particulas detectadas")
                    return
                sample_item["opencv_stats"] = {
                    "mode":             "nodular",
                    "n_total":          stats["n_total"],
                    "n_mm2":            stats["n_mm2"],
                    "nodularidad":      stats["nodularidad"],
                    "vermicular":       stats["vermicular"],
                    "diam_prom_um":     stats["diam_prom_um"],
                    "diam_max_um":      stats["diam_max_um"],
                    "diam_min_um":      stats["diam_min_um"],
                    "counts":           dict(stats["counts"]),
                    "tam_grafito_clase": stats.get("tam_grafito_clase", ""),
                    "px_per_mm":        stats.get("px_per_mm", IMAGEJ_RESOLUCION_PX_MM),
                }

            # ── Acumular y promediar escaneos del mismo modo ──────────────────
            attached_ids = []
            errors = []
            self._report_images.append(sample_item)
            attached_ids.append(sample_item["id"])
            if self._selected_group is not None and self._selected_index is None:
                indexes = self._group_report_indexes(
                    self._selected_group["base"], self._selected_group["lote"])
                for idx in indexes:
                    if self.reports[idx].get("material", "") == material:
                        imgs = self._normalize_report_images(self.reports[idx].get("imagenes", []))
                        imgs.append(sample_item)
                        self.reports[idx]["imagenes"] = imgs
                        save_quality_reports(self.reports)
                        break

            all_opencv = [
                img["opencv_stats"]
                for img in self._normalize_report_images(self._report_images)
                if img.get("opencv_stats") and img["opencv_stats"].get("mode", "nodular") == mode
            ]
            n_scans = len(all_opencv)
            avg_stats = self._merge_imagej_stats(all_opencv, [""] * n_scans) if n_scans > 1 else dict(stats)
            avg_stats.setdefault("source_count", n_scans)

            scan_group_id = uuid.uuid4().hex[:12]
            scan_group_label = f"Escaneo {n_scans} ({mode[:3]}) — {datetime.now().strftime('%H:%M:%S')}"
            sample_item["scan_group_id"] = scan_group_id
            sample_item["scan_group_label"] = scan_group_label

            # ── Actualizar campos del informe ────────────────────────────────
            cal_note = (
                f"Calibracion: {stats['px_per_mm']:.1f} px/mm (calibracion aplicada)"
                if px_per_mm
                else f"Calibracion: {IMAGEJ_RESOLUCION_PX_MM} px/mm (x100 por defecto)"
            )
            fmt = self._format_metric
            if mode == "laminar":
                morph_label = self._LAMINAR_MORPH_LABELS.get(
                    avg_stats.get("morfologia_iso", ""), avg_stats.get("morfologia_iso", ""))
                self.var_morfologia.set(f"Laminar {morph_label}")
                self.var_tam_grafito.set(avg_stats.get("tam_clase", "") or avg_stats.get("tam_grafito_clase", ""))
                avg_counts_lines = [
                    f"  {cat}: {int(round(float(cnt)))}"
                    for cat, cnt in avg_stats["counts"].items() if cnt
                ]
                avg_block_lines = [
                    f"Morfologia ISO: {morph_label}",
                    f"Laminillas/mm2: {fmt(avg_stats['n_mm2'], 2)}",
                    f"Longitud promedio: {fmt(avg_stats.get('long_prom_um', avg_stats.get('diam_prom_um', 0)), 1)} um",
                    f"Long. max: {fmt(avg_stats.get('long_max_um', avg_stats.get('diam_max_um', 0)), 1)} um  "
                    f"min: {fmt(avg_stats.get('long_min_um', avg_stats.get('diam_min_um', 0)), 1)} um",
                    f"Relacion largo/ancho: {fmt(avg_stats.get('aspect_ratio_prom', 0), 2)}",
                    f"Tamano clase: {avg_stats.get('tam_clase', avg_stats.get('tam_grafito_clase', ''))}",
                    "Distribucion por longitud:",
                    *avg_counts_lines,
                ]
                self._replace_or_prepend_observation_block(
                    f"=== Promedio laminar camara ({n_scans} escaneo{'s' if n_scans > 1 else ''}) ===",
                    avg_block_lines,
                )
                mns_line = (f"Posibles inclusiones MnS: {stats.get('n_mns', 0)}"
                            f"  ({stats.get('n_mns_mm2', 0):.1f}/mm²)"
                            if stats.get("n_mns") else "")
                self._append_observation_block(
                    f"Analisis laminar ISO 945 (camara) — escaneo {n_scans}",
                    [
                        f"Imagen: {fname}",
                        cal_note,
                        f"Morfologia: {self._LAMINAR_MORPH_LABELS.get(stats.get('morfologia_iso',''), stats.get('morfologia_iso',''))}",
                        f"Laminillas/mm2: {fmt(stats['n_mm2'], 2)}",
                        f"Long. promedio: {fmt(stats.get('long_prom_um', 0), 1)} um",
                        f"Tamano predominante: {stats.get('tam_clase', '')}",
                        mns_line,
                    ],
                )
                title_msg = "Analisis laminar"
            else:
                is_nodular = self._family_for_material(self.var_material.get()) == "Nodular"
                nodule_count_value = IMAGEJ_NODULAR_DEFAULT_NODULES if is_nodular else fmt(avg_stats["n_mm2"], 2)
                self.var_conteo_nodulos.set(nodule_count_value)
                self.var_pct_nod.set(fmt(avg_stats["nodularidad"], 2))
                self.var_tam_grafito.set(avg_stats.get("tam_grafito_clase", ""))
                if not is_nodular:
                    self.var_morfologia.set(
                        f"Nodular {fmt(avg_stats['nodularidad'], 2)}% / "
                        f"Vermicular {fmt(avg_stats['vermicular'], 2)}%"
                    )
                self._prompt_quality_value_if_empty(self.var_ce_final, "Carbono equivalente", "CE:")
                self._prompt_quality_value_if_empty(self.var_c_final, "Carbono total", "C (%):")
                self._prompt_quality_value_if_empty(self.var_si_final, "Silicio", "Si (%):")
                avg_counts_lines = [
                    f"  {cat}: {int(round(float(cnt)))}"
                    for cat, cnt in avg_stats["counts"].items() if cnt
                ]
                avg_block_lines = [
                    f"Nodulos/mm2: {fmt(avg_stats['n_mm2'], 2)}",
                    f"Nodulos/mm2 informado: {nodule_count_value}" if is_nodular else "",
                    f"Nodularidad: {fmt(avg_stats['nodularidad'], 2)}%",
                    f"Vermiculares: {fmt(avg_stats['vermicular'], 2)}%",
                    f"Tamano grafito: {avg_stats.get('tam_grafito_clase', '')}",
                    f"Diametro promedio: {fmt(avg_stats['diam_prom_um'], 2)} um",
                    f"Max: {fmt(avg_stats['diam_max_um'], 2)} um  Min: {fmt(avg_stats['diam_min_um'], 2)} um",
                    "Distribucion por clase:",
                    *avg_counts_lines,
                ]
                self._replace_or_prepend_observation_block(
                    f"=== Promedio OpenCV camara ({n_scans} escaneo{'s' if n_scans > 1 else ''}) ===",
                    avg_block_lines,
                )
                self._append_observation_block(
                    f"Analisis OpenCV (camara) — escaneo {n_scans}",
                    [
                        f"Imagen: {fname}",
                        cal_note,
                        f"Area minima: {IMAGEJ_AREA_UMBRAL} px",
                        f"Nodulos/mm2: {fmt(stats['n_mm2'], 2)}",
                        f"Nodularidad: {fmt(stats['nodularidad'], 2)}%",
                        f"Tamano predominante: {stats.get('tam_grafito_clase', '')}",
                    ],
                )
                title_msg = "Conteo de nodulos"

            # ── Imágenes del grupo (gráfico + tabla) ─────────────────────────
            try:
                chart_stats = avg_stats.copy()
                if mode == "laminar":
                    chart_stats.setdefault("tam_grafito_clase", avg_stats.get("tam_clase", ""))
                chart = self._create_imagej_distribution_chart(chart_stats, f"Camara {fname[:16]}")
                if chart:
                    chart["scan_group_id"] = scan_group_id
                    chart["scan_group_label"] = scan_group_label
                    self._report_images.append(chart)
                    attached_ids.append(chart["id"])
            except Exception as ex:
                errors.append(f"Grafico de distribucion: {ex}")
            try:
                tbl_img = self._create_opencv_stats_table_image(stats, avg_stats, n_scans)
                if tbl_img:
                    tbl_img["scan_group_id"] = scan_group_id
                    tbl_img["scan_group_label"] = scan_group_label
                    self._report_images.append(tbl_img)
                    attached_ids.append(tbl_img["id"])
            except Exception as ex:
                errors.append(f"Tabla de resultados: {ex}")

            self._report_images = self._normalize_report_images(self._report_images)
            self._refresh_images_ui()
            if attached_ids:
                try:
                    group_iid = f"grp:{scan_group_id}"
                    self.images_tree.selection_set(group_iid)
                    self.images_tree.focus(group_iid)
                    self._update_image_preview()
                except Exception:
                    pass
                self._images_changed()
            unit_word = "laminillas" if mode == "laminar" else "nodulos"
            if n_scans == 1:
                status_var.set(f"Escaneo 1 guardado — {stats['n_total']} {unit_word}")
                msg = "Analisis guardado en el informe."
            else:
                status_var.set(f"Promedio de {n_scans} escaneos actualizado")
                msg = f"Escaneo {n_scans} guardado.\nPromedio de {n_scans} escaneos aplicado al informe."
            if errors:
                messagebox.showwarning(title_msg, msg + "\n\nAvisos:\n" + "\n".join(errors), parent=win)
            else:
                messagebox.showinfo(title_msg, msg, parent=win)

        btn_save.config(command=_do_save)
        btn_save_count.config(command=_do_save_and_count)

        def _on_close():
            live[0] = False
            try:
                cap.release()
            except Exception:
                pass
            try:
                win.destroy()
            except Exception:
                pass

        win.protocol("WM_DELETE_WINDOW", _on_close)
        _update_live()

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
                comment, cal_id = self._ask_image_metadata(self, Path(path).name)
                if comment is None:
                    continue
                item["comentario"] = comment
                if cal_id:
                    item["calibration_id"] = cal_id
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
        ids_to_remove = set()
        for sel in selected:
            if sel.startswith("grp:"):
                for child_iid in self.images_tree.get_children(sel):
                    ids_to_remove.add(child_iid)
            else:
                ids_to_remove.add(sel)
        self._report_images = [image for image in self._report_images if str(image.get("id")) not in ids_to_remove]
        self._refresh_images_ui()
        self._update_image_preview()
        self._images_changed()

    def _open_selected_image(self):
        selected = self.images_tree.selection()
        if not selected:
            return
        target_id = selected[0]
        if target_id.startswith("grp:"):
            children = self.images_tree.get_children(target_id)
            if not children:
                return
            target_id = children[0]
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

    def _replace_or_prepend_observation_block(self, title, lines):
        block_lines = [title, *lines]
        new_block = "\n".join(str(line) for line in block_lines if str(line).strip())
        current = self.txt_data.get("1.0", tk.END).strip()
        if current:
            blocks = current.split("\n\n")
            blocks = [b for b in blocks if not b.strip().startswith(title)]
            remaining = "\n\n".join(b for b in blocks if b.strip())
        else:
            remaining = ""
        new_text = f"{new_block}\n\n{remaining}" if remaining else new_block
        self.txt_data.delete("1.0", tk.END)
        self.txt_data.insert("1.0", new_text)
        if self._selected_index is not None:
            self._draft_fields.add("datos")
            self._schedule_draft_save()

    def _create_opencv_stats_table_image(self, stats, avg_stats, n_scans):
        try:
            import matplotlib
            matplotlib.use("Agg", force=True)
            import matplotlib.pyplot as plt
        except Exception:
            return None

        display = avg_stats if n_scans > 1 else stats
        rows = []
        if n_scans > 1:
            rows.append(["— Promedio de escaneos —", ""])
        rows += [
            ["Nodulos/mm²", f"{display['n_mm2']:.2f}"],
            ["Nodularidad", f"{display['nodularidad']:.1f}%"],
            ["Vermiculares", f"{display['vermicular']:.1f}%"],
            ["Tam. grafito", display.get("tam_grafito_clase", "") or "—"],
            ["Diám. promedio", f"{display['diam_prom_um']:.1f} µm"],
            ["Diám. max", f"{display['diam_max_um']:.1f} µm"],
            ["Diám. min", f"{display['diam_min_um']:.1f} µm"],
            ["— Distribución —", ""],
        ]
        for label, count in display.get("counts", {}).items():
            if count:
                rows.append([label, str(int(round(float(count))))])
        if n_scans > 1:
            rows += [
                ["— Este escaneo —", ""],
                ["Nodulos/mm²", f"{stats['n_mm2']:.2f}"],
                ["Nodularidad", f"{stats['nodularidad']:.1f}%"],
            ]

        n_rows = len(rows)
        fig_h = max(2.5, n_rows * 0.32 + 0.9)
        fig, ax = plt.subplots(figsize=(5, fig_h))
        ax.axis("off")
        tbl = ax.table(cellText=rows, colLabels=["Parámetro", "Valor"], loc="center", cellLoc="left")
        tbl.auto_set_font_size(False)
        tbl.set_fontsize(8)
        tbl.scale(1.0, 1.25)
        title_txt = f"Resultados conteo — escaneo {n_scans}"
        if n_scans > 1:
            title_txt += f"  (promedio {n_scans} esc.)"
        ax.set_title(title_txt, fontsize=9, pad=6)
        dest = Path(ensure_quality_images_dir()) / f"opencv_tabla_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{uuid.uuid4().hex[:8]}.png"
        fig.savefig(str(dest), dpi=100, bbox_inches="tight", facecolor="white")
        plt.close(fig)
        return {
            "id": uuid.uuid4().hex,
            "nombre": f"tabla_conteo_esc{n_scans}.png",
            "path": str(dest),
            "comentario": f"Tabla de resultados — escaneo {n_scans}",
            "added_at": datetime.now().isoformat(timespec="seconds"),
        }

    def _prompt_quality_value_if_empty(self, var, title, label):
        if var.get().strip():
            return
        value = simpledialog.askfloat(title, label, parent=self)
        if value is not None:
            var.set(self._format_metric(value, 3))

    def _get_nodule_contours(self, image_bgr, blur_size=5, threshold=0, min_area=None):
        import numpy as np
        import cv2 as _cv2
        area_min = int(min_area) if min_area is not None else IMAGEJ_AREA_UMBRAL
        gray = _cv2.cvtColor(image_bgr, _cv2.COLOR_BGR2GRAY)
        k = blur_size if blur_size % 2 == 1 else blur_size + 1
        blur = _cv2.GaussianBlur(gray, (k, k), 0)
        if threshold and threshold > 0:
            _, thresh = _cv2.threshold(blur, int(threshold), 255, _cv2.THRESH_BINARY_INV)
        else:
            _, thresh = _cv2.threshold(blur, 0, 255, _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
        kernel = np.ones((3, 3), np.uint8)
        thresh = _cv2.morphologyEx(thresh, _cv2.MORPH_OPEN, kernel, iterations=1)
        thresh = _cv2.morphologyEx(thresh, _cv2.MORPH_CLOSE, kernel, iterations=1)
        contours, _ = _cv2.findContours(thresh, _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_SIMPLE)
        result = []
        for cnt in contours:
            area = _cv2.contourArea(cnt)
            if area < area_min:
                continue
            perimeter = _cv2.arcLength(cnt, True)
            circ = (4 * np.pi * area / perimeter ** 2) if perimeter > 0 else 0
            result.append({"contour": cnt, "circ": float(circ),
                           "area_px": area, "diam_px": (4 * area / np.pi) ** 0.5})
        return result

    def _count_nodules_opencv(self, image_bgr, px_per_mm=None, threshold=0, min_area=None):
        import numpy as np
        import cv2 as _cv2

        area_min = int(min_area) if min_area is not None else IMAGEJ_AREA_UMBRAL
        scale = float(px_per_mm) if px_per_mm else IMAGEJ_RESOLUCION_PX_MM
        h, w = image_bgr.shape[:2]
        analysis_area_mm2 = (w / scale) * (h / scale)

        gray = _cv2.cvtColor(image_bgr, _cv2.COLOR_BGR2GRAY)
        blur = _cv2.GaussianBlur(gray, (5, 5), 0)
        if threshold and threshold > 0:
            _, thresh = _cv2.threshold(blur, int(threshold), 255, _cv2.THRESH_BINARY_INV)
        else:
            _, thresh = _cv2.threshold(blur, 0, 255, _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
        kernel = np.ones((3, 3), np.uint8)
        thresh = _cv2.morphologyEx(thresh, _cv2.MORPH_OPEN, kernel, iterations=1)
        thresh = _cv2.morphologyEx(thresh, _cv2.MORPH_CLOSE, kernel, iterations=1)

        contours, _ = _cv2.findContours(thresh, _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_SIMPLE)
        particles = []
        for cnt in contours:
            area = _cv2.contourArea(cnt)
            if area < area_min:
                continue
            perimeter = _cv2.arcLength(cnt, True)
            circularity = (4 * np.pi * area / (perimeter ** 2)) if perimeter > 0 else 0
            diam_mm = np.sqrt((4 * area) / np.pi) / scale
            particles.append({"area": area, "circ": float(circularity), "diam_mm": float(diam_mm)})

        if not particles:
            return None

        area_total = sum(p["area"] for p in particles)
        nod_area = sum(p["area"] for p in particles if p["circ"] >= 0.5)

        counts = {}
        for category, min_d, max_d in IMAGEJ_LIMITS:
            c = sum(1 for p in particles if min_d <= p["diam_mm"] <= max_d)
            if c:
                counts[category] = c
        fuera = sum(
            1 for p in particles
            if not any(min_d <= p["diam_mm"] <= max_d for _, min_d, max_d in IMAGEJ_LIMITS)
        )
        if fuera:
            counts["Fuera de clase"] = fuera

        diams = [p["diam_mm"] for p in particles]
        return {
            "n_total": len(particles),
            "n_mm2": round(len(particles) / analysis_area_mm2, 2),
            "nodularidad": round(nod_area / area_total * 100, 2) if area_total else 0,
            "vermicular": round((area_total - nod_area) / area_total * 100, 2) if area_total else 0,
            "diam_prom_um": round(float(np.mean(diams)) * 1000, 2),
            "diam_max_um": round(float(max(diams)) * 1000, 2),
            "diam_min_um": round(float(min(diams)) * 1000, 2),
            "counts": counts,
            "tam_grafito_clase": self._imagej_majority_size_text(counts),
            "px_per_mm": round(scale, 4),
        }

    def _calculate_imagej_stats(self, csv_path, px_per_mm=None):
        try:
            import numpy as np
            import pandas as pd
        except Exception as ex:
            raise RuntimeError(f"Faltan dependencias para leer ImageJ: {ex}") from ex

        scale = float(px_per_mm) if px_per_mm else IMAGEJ_RESOLUCION_PX_MM

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

        df["Diametro_mm"] = np.sqrt((4 * df["Area"]) / np.pi) / scale
        df["Categoria"] = ""
        for category, min_d, max_d in IMAGEJ_LIMITS:
            mask = df["Diametro_mm"].between(min_d, max_d, inclusive="both")
            df.loc[mask, "Categoria"] = category

        area_total = float(df["Area"].sum())
        nodular = df[df["Circ."] >= 0.5]
        vermicular = df[df["Circ."] < 0.5]
        analysis_area_mm2 = IMAGEJ_AREA_ANALISIS_PX / (scale ** 2)
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
            "px_per_mm": round(scale, 4),
        }

    # ── Análisis grafito laminar (ISO 945) ────────────────────────────────────

    _LAMINAR_MORPH_LABELS = {
        "A": "A — Distribución uniforme aleatoria",
        "B": "B — Distribución en rosetas",
        "C": "C — Grafito Kish (laminillas grandes)",
        "D": "D — Interdendrítico aleatorio",
        "E": "E — Interdendrítico orientado",
    }

    def _get_laminar_contours(self, image_bgr, threshold=0, min_area=100, blur_size=5):
        import numpy as np
        import cv2 as _cv2
        gray = _cv2.cvtColor(image_bgr, _cv2.COLOR_BGR2GRAY)
        k = blur_size if blur_size % 2 == 1 else blur_size + 1
        blur = _cv2.GaussianBlur(gray, (k, k), 0)
        if threshold > 0:
            _, thresh = _cv2.threshold(blur, threshold, 255, _cv2.THRESH_BINARY_INV)
        else:
            _, thresh = _cv2.threshold(blur, 0, 255, _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
        kernel = np.ones((2, 2), np.uint8)
        thresh = _cv2.morphologyEx(thresh, _cv2.MORPH_OPEN, kernel, iterations=1)
        contours, _ = _cv2.findContours(thresh, _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_SIMPLE)
        result = []
        for cnt in contours:
            area = _cv2.contourArea(cnt)
            if area < min_area:
                continue
            perimeter = _cv2.arcLength(cnt, True)
            circ = (4 * np.pi * area / perimeter ** 2) if perimeter > 0 else 0
            rect = _cv2.minAreaRect(cnt)
            (_, _), (rw, rh), angle = rect
            length_px = float(max(rw, rh))
            width_px  = float(min(rw, rh))
            if rw < rh:
                angle = angle + 90
            angle = float(angle % 180)
            aspect = length_px / max(width_px, 1.0)
            # Clasificacion preliminar por forma:
            # MnS son compactas/redondas; el grafito laminar es alargado
            if circ >= 0.5 and aspect < 2.0:
                ptype = "mns"
            else:
                ptype = "graphite"
            result.append({
                "contour":       cnt,
                "circ":          float(circ),
                "length_px":     length_px,
                "width_px":      width_px,
                "aspect_ratio":  float(aspect),
                "angle":         angle,
                "area_px":       float(area),
                "particle_type": ptype,
            })
        return result

    def _classify_laminar_morphology(self, flakes):
        import numpy as np
        if not flakes:
            return "—"
        elongated = [f for f in flakes if f.get("aspect_ratio", 1) >= 2.0]
        if not elongated:
            return "D"
        lengths = [f["length_um"] for f in elongated]
        mean_len  = float(np.mean(lengths))
        std_len   = float(np.std(lengths))
        cv_len    = std_len / mean_len if mean_len > 0 else 0
        norm_angles = [f["angle"] % 90 for f in elongated]
        std_angle   = float(np.std(norm_angles)) if norm_angles else 90.0
        # Tipo C: Kish — laminillas muy grandes o distribución muy variable en tamaño
        if mean_len > 400 or (mean_len > 150 and cv_len > 0.9):
            return "C"
        # Tipo E: interdendrítico orientado — ángulos concentrados
        if std_angle < 18 and mean_len < 180:
            return "E"
        # Tipo D: muy fino y aleatorio
        if mean_len < 35:
            return "D"
        # Tipo B: rosetas — alta variabilidad de tamaños en rango medio
        if cv_len > 0.6 and 35 <= mean_len <= 200:
            return "B"
        # Tipo A por defecto
        return "A"

    def _count_laminar_opencv(self, image_bgr, px_per_mm=None, threshold=0, min_area=None):
        import numpy as np
        if min_area is None:
            min_area = getattr(self, "_cam_min_area", IMAGEJ_AREA_UMBRAL)
        scale = float(px_per_mm) if px_per_mm else IMAGEJ_RESOLUCION_PX_MM
        h, w = image_bgr.shape[:2]
        area_mm2 = (w / scale) * (h / scale)
        flakes = self._get_laminar_contours(image_bgr, threshold=threshold,
                                            min_area=min_area, blur_size=5)
        if not flakes:
            return None
        MNS_MAX_DIAM_UM = 30.0   # inclusiones MnS tipicas < 30 µm de diametro equivalente
        for f in flakes:
            f["length_um"] = (f["length_px"] / scale) * 1000.0
            f["width_um"]  = (f["width_px"]  / scale) * 1000.0
            equiv_diam_um  = 2.0 * (f["area_px"] / 3.14159) ** 0.5 / scale * 1000.0
            f["equiv_diam_um"] = equiv_diam_um
            # Refinamiento por tamaño: solo son MnS si son pequeñas
            if f["particle_type"] == "mns" and equiv_diam_um > MNS_MAX_DIAM_UM:
                f["particle_type"] = "graphite"

        graphite = [f for f in flakes if f["particle_type"] == "graphite"]
        mns      = [f for f in flakes if f["particle_type"] == "mns"]

        # Si no hay grafito laminar pero si hay MnS, devolver igual con n_total=0
        if not graphite:
            return None

        n_total = len(graphite)
        n_mm2   = n_total / area_mm2 if area_mm2 > 0 else 0
        lengths = [f["length_um"] for f in graphite]
        counts  = {}
        for label, lo, hi in IMAGEJ_LIMITS:
            lo_um = lo * 1000; hi_um = hi * 1000
            n = sum(1 for f in graphite if lo_um <= f["length_um"] < hi_um)
            if n:
                counts[label] = n
        fuera = sum(1 for f in graphite
                    if not any(lo*1000 <= f["length_um"] < hi*1000
                               for _, lo, hi in IMAGEJ_LIMITS))
        if fuera:
            counts["Fuera de clase"] = fuera
        tam_clase  = self._imagej_majority_size_text(counts)
        morph_type = self._classify_laminar_morphology(graphite)
        aspects    = [f["aspect_ratio"] for f in graphite]
        n_mns      = len(mns)
        n_mns_mm2  = n_mns / area_mm2 if area_mm2 > 0 else 0
        return {
            "n_total":           n_total,
            "n_mm2":             round(n_mm2, 2),
            "long_prom_um":      round(float(np.mean(lengths)), 2),
            "long_max_um":       round(float(np.max(lengths)), 2),
            "long_min_um":       round(float(np.min(lengths)), 2),
            "aspect_ratio_prom": round(float(np.mean(aspects)), 2),
            "morfologia_iso":    morph_type,
            "morfologia_label":  self._LAMINAR_MORPH_LABELS.get(morph_type, morph_type),
            "tam_clase":         tam_clase,
            "counts":            counts,
            "n_mns":             n_mns,
            "n_mns_mm2":         round(n_mns_mm2, 2),
            "px_per_mm":         round(scale, 4),
            "flakes":            flakes,   # incluye grafito + MnS para el overlay
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

        cals = self._cal_load()
        imagej_cal_id = None
        if cals:
            default_label = self._cal_default_label()
            cal_names = [default_label] + [c["nombre"] for c in cals]
            dlg = tk.Toplevel(self)
            dlg.title("Calibracion para ImageJ")
            dlg.transient(self)
            dlg.grab_set()
            dlg.resizable(False, False)
            f = ttk.Frame(dlg, padding=14)
            f.pack(fill="both")
            ttk.Label(f, text="Seleccionar calibracion de escala:").pack(anchor="w", pady=(0, 6))
            cal_var = tk.StringVar(value=cal_names[0])
            ttk.Combobox(f, textvariable=cal_var, values=cal_names, state="readonly", width=34).pack(anchor="w")
            ttk.Label(f, text=f"(x100 por defecto: {IMAGEJ_RESOLUCION_PX_MM} px/mm)",
                      foreground="#888").pack(anchor="w", pady=(4, 10))
            bf = ttk.Frame(f); bf.pack(fill="x")
            def _accept_cal():
                chosen = cal_var.get()
                obj = next((c for c in cals if c["nombre"] == chosen), None)
                nonlocal imagej_cal_id
                imagej_cal_id = obj["id"] if obj else None
                dlg.destroy()
            ttk.Button(bf, text="Continuar", command=_accept_cal).pack(side="right")
            ttk.Button(bf, text="Cancelar", command=lambda: dlg.destroy()).pack(side="right", padx=6)
            dlg.wait_window()

        imagej_px_per_mm = self._cal_get_px_per_mm(imagej_cal_id)

        try:
            stats_list = [self._calculate_imagej_stats(path, px_per_mm=imagej_px_per_mm) for path in csv_paths]
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
                (f"Calibracion: {stats['px_per_mm']:.1f} px/mm (calibracion aplicada)"
                 if imagej_px_per_mm
                 else f"Calibracion: {IMAGEJ_RESOLUCION_PX_MM} px/mm (x100 por defecto)"),
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
            "traccion_real": self.var_traccion_real.get().strip(),
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
        self.var_traccion_real.set(first.get("traccion_real", ""))
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
            "traccion_real": self.var_traccion_real.get().strip(),
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
            "inoculacion_snapshot": self._build_inoc_snapshot(
                self.var_material.get().strip(),
                self.var_base.get().strip(),
            ),
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
                "traccion_real": "",
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
                "inoculacion_snapshot": self._build_inoc_snapshot(material, base),
            }
            existing_idx = next(
                (
                    i for i, it in enumerate(self.reports)
                    if it.get("base") == base and it.get("material") == material and it.get("lote") == data["lote"]
                ),
                None,
            )
            if existing_idx is None:
                if not report.get("id"):
                    report["id"] = uuid.uuid4().hex
                self.reports.append(report)
            else:
                if not report.get("id"):
                    report["id"] = self.reports[existing_idx].get("id") or uuid.uuid4().hex
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
        self.var_traccion_real.set("")
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
                "traccion_real": "",
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
            ("Traccion real Lab (kg/mm2)", report.get("traccion_real", "")),
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

    def _pick_groups_to_print(self, title="Imprimir grupos", label="Selecciona hasta 3 grupos para imprimir:"):
        groups = self._group_choices()
        if not groups:
            return None
        default_selected = {(base, lote) for base, lote, _, _ in groups[-3:]}

        picked = {"value": None}
        win = tk.Toplevel(self)
        win.title(title)
        win.transient(self.winfo_toplevel())
        win.grab_set()
        win.resizable(True, True)

        box = ttk.Frame(win, padding=12)
        box.pack(fill="both", expand=True)
        box.columnconfigure(0, weight=1)
        box.rowconfigure(1, weight=1)

        ttk.Label(box, text=label).grid(row=0, column=0, sticky="w", pady=(0, 8))

        checks_frame = ttk.LabelFrame(box, text="Grupos", padding=8)
        checks_frame.grid(row=1, column=0, sticky="nsew")
        checks_frame.columnconfigure(0, weight=1)
        checks_frame.rowconfigure(0, weight=1)

        scroll = ScrollFrame(checks_frame)
        scroll.pack(fill="both", expand=True)

        vars_by_group = []
        for base, lote, reports, latest_fecha in groups:
            checked = (base, lote) in default_selected
            var = tk.BooleanVar(value=checked)
            family = self._family_for_reports(reports)
            row_label = f"Base {base} - {family} - {lote} ({len(reports)} informes, {latest_fecha})"
            ttk.Checkbutton(scroll.inner, text=row_label, variable=var).pack(anchor="w")
            vars_by_group.append(((base, lote, reports), var))

        btns = ttk.Frame(box)
        btns.grid(row=2, column=0, sticky="ew", pady=(10, 0))

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
        # Altura máxima: 75% de la pantalla
        max_h = int(root.winfo_screenheight() * 0.75)
        win_w = win.winfo_reqwidth()
        win_h = min(win.winfo_reqheight(), max_h)
        x = root.winfo_rootx() + max(0, (root.winfo_width() - win_w) // 2)
        y = root.winfo_rooty() + max(0, (root.winfo_height() - win_h) // 2)
        win.geometry(f"{win_w}x{win_h}+{x}+{y}")
        win.minsize(win_w, 200)
        win.wait_window()
        return picked["value"]

    def _archive_groups(self):
        chosen = self._pick_groups_to_print(
            title="Archivar grupos",
            label="Selecciona los grupos a archivar:",
        )
        if chosen is None:
            return
        if not chosen:
            messagebox.showinfo("Calidad", "No seleccionaste grupos para archivar.", parent=self)
            return
        archived = self._archive_printed_groups(chosen)
        messagebox.showinfo(
            "Calidad",
            f"Grupos archivados correctamente.\nInformes archivados: {archived}",
            parent=self,
        )

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
        self.var_traccion_real.set(report.get("traccion_real", ""))
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
            if not report.get("id"):
                report["id"] = uuid.uuid4().hex
            self.reports.append(report)
        else:
            if not report.get("id"):
                report["id"] = self.reports[self._selected_index].get("id") or uuid.uuid4().hex
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
