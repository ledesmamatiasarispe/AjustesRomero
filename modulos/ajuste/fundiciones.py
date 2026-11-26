# fundiciones.py -- Automatizacion COM de Access para "Fundiciones-2010PRG".
# Puerto de tab_calidad.py (bloque _fundiciones_*), la parte mas sensible y
# fragil de toda la migracion: controla una instancia YA ABIERTA (o recien
# lanzada) de Access via win32com.client.GetActiveObject, con nombres EXACTOS
# de formularios/controles de una base externa que no se puede probar sin la
# base real -- por eso la logica interna (combo resolver, orden de campos,
# reintentos, SendKeys de confirmacion) se porta sin cambios de comportamiento
# respecto al original.
#
# Adaptaciones respecto al original (obligatorias por el cambio de runtime,
# no cambios de comportamiento):
#   - El canal de status de Tkinter (StringVar) se reemplaza por _STATUS
#     (variable de modulo protegida con lock), leible via get_status().
#   - El logging de debug (print a stdout) se mantiene igual.
#   - Los reintentos que el original hace con self.after(1000, ...) (no
#     bloqueante en el hilo de Tkinter) se vuelven un loop bloqueante con
#     time.sleep -- este modulo corre en el threadpool de FastAPI (un hilo
#     de verdad, no el hilo de UI), asi que bloquear ese hilo es correcto y
#     equivalente en tiempos de espera al original.
#   - Las credenciales de Access quedan hardcodeadas igual que el original
#     (confirmado con el usuario: no es un secreto de esta app).
#   - Se agrega un lock a nivel de proceso (ver routers/fundiciones.py) para
#     serializar llamadas concurrentes desde distintos dispositivos web --
#     el original era de un solo usuario/hilo de Tkinter, la version web no.
#
# Deliberadamente NO portado (codigo muerto en el original, sin boton que lo
# dispare en la UI real -- confirmado revisando tab_calidad.py): el dialogo
# "_open_fundiciones_preview", el macro "Pegar por Tab"
# (_send_fundiciones_tab_macro) y "Pegar por controles"
# (_paste_fundiciones_by_controls/_fundiciones_control_values/_fundiciones_fields).
# La UI real solo tiene dos botones: "Cargar en Access" y "Abrir en Access"
# (ver load_report_in_access / open_report_for_review mas abajo).

import os
import re
import subprocess
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

from .utils import fmt, to_float_or_none

_parse_optional_float = to_float_or_none

# ---------- constantes (copiadas tal cual de tab_calidad.py) ----------

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

GRAPHITE_SIZE_OPTIONS = (
    "1", "1-2", "2", "2-1", "2-3", "3", "3-2", "3-4", "4", "4-3", "4-5",
    "4-6", "5", "5-4", "5-6", "6", "6-5", "6-7", "7", "7-6", "7-8", "8", "8-7",
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


# ---------- status / debug (reemplaza StringVar de Tkinter) ----------

_STATUS_LOCK = threading.Lock()
_STATUS = {"text": "Listo."}


def _set_status(text):
    with _STATUS_LOCK:
        _STATUS["text"] = str(text)


def get_status():
    with _STATUS_LOCK:
        return _STATUS["text"]


def _debug(message):
    try:
        stamp = datetime.now().strftime("%H:%M:%S")
        print(f"[{stamp}][Fundiciones] {message}", flush=True)
    except Exception:
        pass


def _log_error(context, ex):
    try:
        path = Path(tempfile.gettempdir()) / "ajuste_comp_fundiciones_error.log"
        stamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with path.open("a", encoding="utf-8") as fh:
            fh.write(f"[{stamp}] {context}: {repr(ex)}\n")
    except Exception:
        pass


# ---------- family (informe ya trae "family" guardado; fallback al catalogo
# solo si un informe viejo no lo tuviera) ----------

def _family_for_report(report):
    family = str((report or {}).get("family", "") or "").strip()
    if family:
        return family
    try:
        from .rutas.calidad import _family_for_material, _load_final_catalog
        final_materials, _, _, _ = _load_final_catalog()
        return _family_for_material(final_materials, (report or {}).get("material", ""))
    except Exception:
        return ""


# ---------- helpers de formato de campos (puros, sin COM) ----------

def _fundiciones_graphite_text(report):
    family = _family_for_report(report)
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


def _fundiciones_graphite_combo_text(report):
    family = _family_for_report(report)
    if family == "Nodular":
        return "Nodular"
    return "Laminar"


def _fundiciones_graphite_type_text(report):
    if _family_for_report(report) == "Nodular":
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


def _fundiciones_nodular_density_values(report):
    raw = str(report.get("conteo_nodulos", "") or "").strip()
    if not raw:
        return "", ""
    numbers = re.findall(r"\d+(?:[,.]\d+)?", raw)
    if not numbers:
        return raw, raw

    def clean(value):
        numeric = _parse_optional_float(value)
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


def _fundiciones_graphite_detail_text(report):
    family = _family_for_report(report)
    if family == "Nodular":
        return _fundiciones_graphite_text(report)
    morfologia = str(report.get("morfologia", "") or "").strip()
    tipo = str(report.get("tipo_grafito", "") or "").strip()
    if tipo:
        tipo = re.sub(r"\b([AB])\s+(\d+(?:[,.]\d+)?%)", r'"\1": \2', tipo)
        return f"{morfologia} Tipo {tipo}".strip()
    return morfologia


def _fundiciones_observations_text(report):
    parts = []
    seccion = str(report.get("seccion", "") or "").strip()
    datos = str(report.get("datos", "") or "").strip()
    if seccion:
        parts.append(f"Seccion: {seccion}")
    if datos:
        parts.append(datos)
    text = " | ".join(part.replace("\r", " ").replace("\n", " ") for part in parts if part)
    return text[:255]


def _fundiciones_report_observation_access_text(report):
    return "--"


def _fundiciones_matrix_key(report):
    matriz = str(report.get("matriz", "") or "").strip().lower()
    matriz = matriz.replace("í", "i").replace("á", "a").replace("é", "e").replace("ó", "o").replace("ú", "u")
    if matriz.startswith("ferr"):
        return "ferrita"
    if matriz.startswith("perl"):
        return "perlita"

    perlita = _parse_optional_float(report.get("perlita", ""))
    ferrita = _parse_optional_float(report.get("ferrita", ""))
    if perlita is None and ferrita is None:
        return ""
    if ferrita is None:
        return "perlita"
    if perlita is None:
        return "ferrita"
    return "perlita" if perlita >= ferrita else "ferrita"


def _fundiciones_matrix_combo_text(report):
    key = _fundiciones_matrix_key(report)
    if key == "ferrita":
        return "Ferr."
    if key == "perlita":
        return "Perl."
    return str(report.get("matriz", "") or "").strip()


def _fundiciones_predominant_matrix_percent(report):
    key = _fundiciones_matrix_key(report)
    if not key:
        return ""
    raw = str(report.get(key, "") or "").strip()
    if not raw:
        return ""
    numeric = _parse_optional_float(raw.rstrip("%"))
    if numeric is None:
        return raw.rstrip("%").strip()
    return f"{numeric:.0f}"


def _fundiciones_carbon_equivalent_text(report):
    if _family_for_report(report) == "Nodular":
        return "0.00"
    raw = str(report.get("ce_final", "") or "").strip()
    numeric = _parse_optional_float(raw.rstrip("%"))
    if numeric is None:
        return raw
    return f"{numeric:.2f}".replace(".", ",") + "%."


def _fundiciones_carbon_equivalent_access_value(report):
    if _family_for_report(report) == "Nodular":
        return 0.0
    raw = str(report.get("ce_final", "") or "").strip()
    cleaned = raw.replace("%", "").rstrip(".").strip()
    numeric = _parse_optional_float(cleaned)
    if numeric is None:
        return cleaned
    return round(numeric, 2)


def _fundiciones_resistance_text(report):
    raw = str(report.get("traccion", "") or "").strip()
    numeric = _parse_optional_float(raw)
    if numeric is None:
        return raw
    return f"{numeric:.0f}" if abs(numeric - round(numeric)) < 1e-9 else fmt(numeric, 2)


def _fundiciones_elongation_text(report):
    raw = str(report.get("alargamiento", "") or "").strip()
    numeric = _parse_optional_float(raw.rstrip("%"))
    if numeric is None:
        return raw.rstrip("%").strip()
    return f"{numeric:.0f}" if abs(numeric - round(numeric)) < 1e-9 else fmt(numeric, 2)


def _fundiciones_thickness_text(report):
    return str(report.get("seccion", "") or "").strip()


def _fundiciones_thickness_aliases(thickness):
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


def _fundiciones_hardness_text(report):
    raw = str(report.get("dureza", "") or "").strip()
    numeric = _parse_optional_float(raw)
    if numeric is None:
        return raw
    return f"{numeric:.0f}" if abs(numeric - round(numeric)) < 1e-9 else fmt(numeric, 2)


def _fundiciones_graphite_size_text(report):
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


def _fundiciones_matrix_display_text(report):
    key = _fundiciones_matrix_key(report)
    pct = _fundiciones_predominant_matrix_percent(report)
    if key == "ferrita":
        label = "Ferrítica"
    elif key == "perlita":
        label = "Perlítica"
    else:
        label = str(report.get("matriz", "") or "").strip()
    return f"{label} {pct}%".strip() if pct else label


def _fundiciones_material_observation_text(report):
    primary = _fundiciones_matrix_key(report)
    if primary not in {"ferrita", "perlita"}:
        return ""
    secondary = "perlita" if primary == "ferrita" else "ferrita"
    label = "Perlita" if secondary == "perlita" else "Ferrita"
    raw = str(report.get(secondary, "") or "").strip()
    if not raw:
        return ""
    numeric = _parse_optional_float(raw.rstrip("%"))
    if numeric is not None:
        if abs(numeric) < 1e-9:
            return ""
        value = f"{numeric:.0f}" if abs(numeric - round(numeric)) < 1e-9 else fmt(numeric, 2)
    else:
        value = raw.rstrip("%").strip()
    if not value:
        return ""
    return f"{label} {value}%"


def _fundiciones_access_date(report):
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


def _fundiciones_cod_fundicion(report):
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


def _fundiciones_colada_code_from_report(report):
    code = _fundiciones_cod_fundicion(report)
    return str(code or "").strip()


# ---------- helpers de bajo nivel COM ----------

def _ensure_fundiciones_drive():
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


def _prompt_fundiciones_credentials():
    return FUNDICIONES_DEFAULT_USER, FUNDICIONES_DEFAULT_PASSWORD


def _fundiciones_app_running():
    """Chequeo COM real de si Access ya esta corriendo -- a diferencia de
    _activate_fundiciones_window (heuristica de titulo de ventana via
    EnumWindows/AppActivate), esto no depende de que el titulo contenga
    FUNDICIONES_WINDOW_HINT ni de que la ventana este visible/al frente: si
    GetActiveObject tiene exito, Access esta corriendo sin importar que
    formulario tenga abierto o si esta minimizado. Evita el bug reportado
    (no encuentra la ventana por titulo -> asume que Access esta cerrado ->
    lanza una SEGUNDA instancia con subprocess.Popen mientras la primera
    sigue abierta)."""
    try:
        import win32com.client
        win32com.client.GetActiveObject("Access.Application")
        return True
    except Exception:
        return False


def _activate_fundiciones_window():
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


def _access_modal_dialog_open():
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


def _focus_fundiciones_form_control(form_name, control_name):
    _debug(f"SetFocus solicitado: {form_name}.{control_name}")
    try:
        if _access_modal_dialog_open():
            _debug("SetFocus cancelado: Access tiene aviso modal abierto")
            _set_status("Access tiene un aviso abierto.")
            return False
        if not _activate_fundiciones_window():
            _debug("SetFocus cancelado: no encontre ventana Fundiciones")
            _set_status("No encontre la ventana de Fundiciones.")
            return False
        import win32com.client
        app = win32com.client.GetActiveObject("Access.Application")
        app.Forms.Item(form_name).Controls.Item(control_name).SetFocus()
        _debug(f"SetFocus OK: {form_name}.{control_name}")
        _set_status(f"OK SetFocus: {form_name}.{control_name}")
        return True
    except Exception as ex:
        _debug(f"SetFocus ERROR: {form_name}.{control_name}: {ex}")
        _log_error("_focus_fundiciones_form_control", f"{form_name}.{control_name}: {ex}")
        _set_status(f"No funciono: {form_name}.{control_name}")
        return False


def _fundiciones_form():
    _debug(f"Buscando formulario: {FUNDICIONES_TARGET_FORM}")
    try:
        if _access_modal_dialog_open():
            _debug("Formulario cancelado: Access tiene aviso modal abierto")
            _set_status("Access tiene un aviso abierto.")
            return None
        if not _activate_fundiciones_window():
            _debug("Formulario cancelado: no encontre ventana Fundiciones")
            _set_status("No encontre la ventana de Fundiciones.")
            return None
        import win32com.client
        app = win32com.client.GetActiveObject("Access.Application")
        form = app.Forms.Item(FUNDICIONES_TARGET_FORM)
        _debug(f"Formulario OK: {FUNDICIONES_TARGET_FORM}")
        return form
    except Exception as ex:
        _debug(f"Formulario ERROR: {FUNDICIONES_TARGET_FORM}: {ex}")
        _log_error("_fundiciones_form", ex)
        _set_status(f"No esta abierto {FUNDICIONES_TARGET_FORM}.")
        return None


def _fundiciones_control(form, control_name):
    try:
        form_name = form.Name
    except Exception:
        form_name = FUNDICIONES_TARGET_FORM
    _debug(f"Buscando control: {form_name}.{control_name}")
    try:
        control = form.Controls.Item(control_name)
        _debug(f"Control OK: {form_name}.{control_name}")
        return control
    except Exception as ex:
        _debug(f"Control ERROR: {form_name}.{control_name}: {ex}")
        _log_error("_fundiciones_control", f"{form_name}.{control_name}: {ex}")
        _set_status(f"No existe {form_name}.{control_name}.")
        return None


def _fundiciones_control_any(form, control_names):
    for control_name in control_names:
        control = _fundiciones_control(form, control_name)
        if control is not None:
            return control, control_name
    return None, ""


def _fundiciones_materials_subform(form):
    _debug(f"Entrando a subformulario: {FUNDICIONES_MATERIALS_SUBFORM}")
    control = _fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
    if control is None:
        return None
    try:
        subform = control.Form
        _debug(f"Subformulario OK: {FUNDICIONES_MATERIALS_SUBFORM}")
        return subform
    except Exception as ex:
        _debug(f"Subformulario ERROR: {FUNDICIONES_MATERIALS_SUBFORM}: {ex}")
        _log_error("_fundiciones_materials_subform", ex)
        _set_status(f"No pude entrar a {FUNDICIONES_MATERIALS_SUBFORM}.")
        return None


def _fundiciones_thickness_subform(materials_subform):
    _debug(f"Entrando a subformulario: {FUNDICIONES_THICKNESS_SUBFORM}")
    control = _fundiciones_control(materials_subform, FUNDICIONES_THICKNESS_SUBFORM)
    if control is None:
        return None
    try:
        try:
            control.SetFocus()
            _debug(f"SetFocus OK: {FUNDICIONES_THICKNESS_SUBFORM}")
        except Exception as focus_ex:
            _debug(f"SetFocus omitido para {FUNDICIONES_THICKNESS_SUBFORM}: {focus_ex}")
        subform = control.Form
        try:
            subform.Requery()
            _debug(f"Requery OK: {FUNDICIONES_THICKNESS_SUBFORM}")
        except Exception as requery_ex:
            _debug(f"Requery omitido para {FUNDICIONES_THICKNESS_SUBFORM}: {requery_ex}")
        _debug(f"Subformulario OK: {FUNDICIONES_THICKNESS_SUBFORM}")
        return subform
    except Exception as ex:
        _debug(f"Subformulario ERROR: {FUNDICIONES_THICKNESS_SUBFORM}: {ex}")
        _log_error("_fundiciones_thickness_subform", ex)
        _set_status(f"No pude entrar a {FUNDICIONES_THICKNESS_SUBFORM}.")
        return None


def _fundiciones_combo_targets(display_text, aliases=None):
    values = [str(display_text or "").strip()]
    values.extend(str(alias or "").strip() for alias in (aliases or ()))
    return _unique_keep_order([value for value in values if value])


def _fundiciones_combo_norm(text):
    raw = str(text or "").strip().casefold()
    raw = raw.replace("á", "a").replace("é", "e").replace("í", "i").replace("ó", "o").replace("ú", "u")
    raw = raw.replace("ñ", "n")
    return re.sub(r"[^a-z0-9]+", "", raw)


def _fundiciones_combo_number_key(text):
    nums = re.findall(r"\d+(?:[,.]\d+)?", str(text or ""))
    cleaned = []
    for num in nums:
        try:
            value = float(num.replace(",", "."))
            cleaned.append(str(int(value)) if abs(value - round(value)) < 1e-9 else str(value))
        except Exception:
            cleaned.append(num)
    return tuple(cleaned)


def _fundiciones_combo_bound_value(combo, display_text, aliases=None):
    target_texts = _fundiciones_combo_targets(display_text, aliases)
    _debug(f"Resolviendo combo para texto visible: {display_text!r}, alias={target_texts[1:]!r}")
    if not target_texts:
        return ""
    target_exact = {text.casefold() for text in target_texts}
    target_norm = {_fundiciones_combo_norm(text) for text in target_texts}
    target_numbers = {_fundiciones_combo_number_key(text) for text in target_texts if _fundiciones_combo_number_key(text)}
    try:
        bound_index = max(0, int(combo.BoundColumn) - 1)
    except Exception:
        bound_index = 0
    rows = []
    try:
        column_count = max(1, int(combo.ColumnCount))
        list_count = max(0, int(combo.ListCount))
        _debug(f"Combo columnas={column_count}, filas={list_count}, bound_col={bound_index + 1}")
        for row in range(list_count):
            bound_value = combo.Column(bound_index, row)
            row_values = []
            for col in range(column_count):
                value = combo.Column(col, row)
                row_values.append(value)
                text = str(value or "").strip()
                if text.casefold() in target_exact:
                    _debug(f"Combo resuelto: texto={display_text!r}, fila={row}, valor_interno={bound_value!r}")
                    return bound_value
                if _fundiciones_combo_norm(text) in target_norm:
                    _debug(
                        f"Combo resuelto normalizado: texto={display_text!r}, fila={row}, "
                        f"valor_interno={bound_value!r}, celda={text!r}"
                    )
                    return bound_value
            rows.append((row, bound_value, row_values))
        for row, bound_value, row_values in rows:
            for value in row_values:
                number_key = _fundiciones_combo_number_key(value)
                if number_key and number_key in target_numbers:
                    _debug(
                        f"Combo resuelto por numeros: texto={display_text!r}, fila={row}, "
                        f"valor_interno={bound_value!r}, celda={value!r}"
                    )
                    return bound_value
    except Exception as ex:
        _debug(f"Combo ERROR resolviendo {display_text!r}: {ex}")
        _log_error("_fundiciones_combo_bound_value", ex)
    for row, bound_value, row_values in rows:
        preview = " | ".join(str(value or "") for value in row_values)
        _debug(f"Combo opcion {row}: bound={bound_value!r}; {preview}")
    # Si el combo quedo con una sola fila disponible (caso real: cmbEspesor
    # viene con su RowSource filtrado por material via EspesoresPorMaterial,
    # ver _fundiciones_thickness_subform), no hay ambiguedad que resolver
    # aunque el texto no haya matcheado ni por alias ni por numeros -- esa
    # es la UNICA opcion que Access deja elegir para este material, asi que
    # es la que corresponde (confirmado con el usuario: material '12' solo
    # tenia 'Mayor a 20 mm' en su combo y el reporte decia 'De 12 a 25 mm',
    # un texto que no iba a matchear nunca pero que no cambia que esa fila
    # es la unica valida para ese material).
    if len(rows) == 1:
        row, bound_value, row_values = rows[0]
        preview = " | ".join(str(value or "") for value in row_values)
        _debug(f"Combo resuelto por unica opcion disponible: texto={display_text!r}; {preview}")
        return bound_value
    _debug(f"Combo NO resuelto: {display_text!r}")
    return None


def _fundiciones_assign_control(control, control_name, value, enter=True, focus=True):
    _debug(f"Asignando {control_name} = {value!r}")
    focus_ok = False
    if focus:
        try:
            control.SetFocus()
            focus_ok = True
            _debug(f"SetFocus OK antes de asignar: {control_name}")
        except Exception as ex:
            _debug(f"SetFocus omitido para {control_name}: {ex}")
            _log_error("_fundiciones_assign_control.focus", f"{control_name}: {ex}")
    try:
        control.Value = value
    except Exception as ex:
        _debug(f"Asignacion ERROR {control_name}: {ex}")
        _log_error("_fundiciones_assign_control.value", f"{control_name}: {ex}")
        raise
    if enter and focus_ok:
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            time.sleep(0.08)
            _debug(f"Enter confirmacion: {control_name}")
            shell.SendKeys("{ENTER}")
            time.sleep(0.12)
        except Exception as ex:
            _debug(f"Enter ERROR {control_name}: {ex}")
            _log_error("_fundiciones_assign_control.enter", f"{control_name}: {ex}")
    elif enter:
        _debug(f"Enter omitido sin foco valido: {control_name}")
    return True


def _fundiciones_read_control_value(control):
    try:
        return control.Value
    except Exception:
        return ""


def _fundiciones_compare_key(value):
    text = str(value if value is not None else "").strip()
    text = text.replace("\r", " ").replace("\n", " ")
    text = " ".join(text.split())
    text = text.replace("Kg/mm²", "").replace("Kg/mm2", "").replace("HB", "").replace("%", "")
    text = text.rstrip(".").strip()
    numeric = _parse_optional_float(text)
    if numeric is not None:
        return ("num", round(numeric, 3))
    return ("txt", text.casefold())


def _fundiciones_values_match(actual, expected):
    return _fundiciones_compare_key(actual) == _fundiciones_compare_key(expected)


def _fundiciones_verify_control_value(control, expected_value):
    actual = _fundiciones_read_control_value(control)
    return _fundiciones_values_match(actual, expected_value)


# ---------- abrir/detectar el formulario objetivo ----------

def _fundiciones_target_form_is_open():
    try:
        import win32com.client
        app = win32com.client.GetActiveObject("Access.Application")
        app.Forms.Item(FUNDICIONES_TARGET_FORM)
        return True
    except Exception:
        return False


def _open_fundiciones_target_form_direct():
    _debug(f"Abrir formulario solicitado: {FUNDICIONES_TARGET_FORM}")
    if _access_modal_dialog_open():
        _debug("Abrir formulario cancelado: aviso modal abierto")
        return False
    try:
        if not _activate_fundiciones_window():
            _debug("Abrir formulario cancelado: no encontre ventana Fundiciones")
            return False
        import win32com.client
        app = win32com.client.GetActiveObject("Access.Application")
        _debug(f"DoCmd.OpenForm: {FUNDICIONES_TARGET_FORM}")
        app.DoCmd.OpenForm(FUNDICIONES_TARGET_FORM)
        if _wait_fundiciones_target_form(timeout=4.0):
            _debug(f"Formulario abierto confirmado: {FUNDICIONES_TARGET_FORM}")
            _focus_fundiciones_colada_field()
            return True
        _debug(f"Formulario no aparecio a tiempo: {FUNDICIONES_TARGET_FORM}")
        return False
    except Exception as ex:
        _debug(f"Abrir formulario ERROR: {FUNDICIONES_TARGET_FORM}: {ex}")
        _log_error("_open_fundiciones_target_form_direct", ex)
        _set_status(f"No pude abrir {FUNDICIONES_TARGET_FORM}: {ex}")
        return False


def _wait_fundiciones_target_form(timeout=4.0):
    _debug(f"Esperando formulario {FUNDICIONES_TARGET_FORM} hasta {timeout:.1f}s")
    deadline = time.time() + timeout
    while time.time() < deadline:
        if _fundiciones_target_form_is_open():
            _debug(f"Formulario detectado: {FUNDICIONES_TARGET_FORM}")
            return True
        time.sleep(0.25)
    _debug(f"Timeout esperando formulario: {FUNDICIONES_TARGET_FORM}")
    return False


def _open_fundiciones_target_form():
    if _access_modal_dialog_open():
        _set_status("Access tiene un aviso abierto. Cerralo primero y vuelve a intentar.")
        return False
    if _fundiciones_target_form_is_open() and _focus_fundiciones_colada_field():
        return True
    if _open_fundiciones_target_form_direct():
        return True
    _set_status(f"No pude abrir {FUNDICIONES_TARGET_FORM}.")
    return False


def _open_fundiciones_target_form_retry(report=None, enter_colada=True, review=False):
    """Puerto bloqueante de _open_fundiciones_target_form_retry: el original
    usaba self.after(1000, ...) para reintentar sin bloquear el hilo de
    Tkinter mientras Access recien lanzado termina de arrancar. Ese modulo
    corre en el threadpool de FastAPI (hilo dedicado), asi que un loop con
    time.sleep es equivalente -- mismos tiempos de espera (hasta 8
    reintentos de 1s, 9 intentos en total)."""
    for attempt in range(9):
        _debug(f"Reintento abrir formulario: intento={attempt}, enter_colada={enter_colada}, review={review}")
        if _open_fundiciones_target_form():
            if review:
                return bool(_review_current_report_in_access(report))
            if enter_colada:
                return bool(_enter_fundiciones_colada(report))
            return True
        if attempt < 8:
            time.sleep(1.0)
    return False


def open_fundiciones_app(report=None, enter_colada=True, review=False):
    """Puerto de _open_fundiciones_app: punto de entrada principal. Si Access
    ya esta corriendo (chequeo COM, no de ventana) lo activa y entra directo
    -- nunca lanza una segunda instancia en ese caso, aunque no encuentre o
    no pueda abrir el formulario de carga. Solo si Access de verdad no esta
    corriendo lo lanza con las credenciales hardcodeadas (igual que el
    original) y espera con reintentos a que aparezca el formulario
    objetivo."""
    _debug(f"Abrir Fundiciones: enter_colada={enter_colada}, review={review}")
    try:
        if _fundiciones_app_running():
            _debug("Access ya esta corriendo (COM); evito lanzar una segunda instancia")
            _activate_fundiciones_window()  # intento best-effort de traerlo al frente; no condiciona nada
            if _open_fundiciones_target_form():
                if review:
                    return bool(_review_current_report_in_access(report))
                if enter_colada:
                    return bool(_enter_fundiciones_colada(report))
                return True
            _debug(f"Access esta corriendo pero no pude abrir {FUNDICIONES_TARGET_FORM}")
            _set_status(
                f"Access ya esta abierto pero no pude abrir {FUNDICIONES_TARGET_FORM}. "
                "Revisa si hay un aviso modal o si esta en otra pantalla, y probá de nuevo."
            )
            return False
        _debug("Access no esta corriendo; preparando apertura")
        _ensure_fundiciones_drive()
        user, password = _prompt_fundiciones_credentials()
        if os.path.exists(FUNDICIONES_MSACCESS_PATH):
            _debug(f"Abriendo MSACCESS: {FUNDICIONES_APP_PATH}")
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
        else:
            _debug("MSACCESS path no encontrado; usando acceso directo/app")
            os.startfile(FUNDICIONES_SHORTCUT_PATH if os.path.exists(FUNDICIONES_SHORTCUT_PATH) else FUNDICIONES_APP_PATH)
        return _open_fundiciones_target_form_retry(report, enter_colada, review=review)
    except Exception as ex:
        _debug(f"Abrir Fundiciones ERROR: {ex}")
        _log_error("open_fundiciones_app", ex)
        _set_status(f"No se pudo abrir Fundiciones: {ex}")
        return False


# ---------- colada / responsable / fecha ----------

def _focus_fundiciones_colada_field():
    _debug(f"Foco colada solicitado: {FUNDICIONES_COLADA_CONTROL}")
    if not _fundiciones_target_form_is_open():
        _debug(f"Foco colada cancelado: no esta {FUNDICIONES_TARGET_FORM}")
        _set_status(f"Todavia no esta abierto {FUNDICIONES_TARGET_FORM}.")
        return False
    return _focus_fundiciones_form_control(FUNDICIONES_TARGET_FORM, FUNDICIONES_COLADA_CONTROL)


def _select_fundiciones_colada(report):
    _debug("Inicio paso colada")
    code = _fundiciones_colada_code_from_report(report)
    _debug(f"Colada calculada formato Access: {code!r}")
    if not code:
        _set_status("No hay numero de colada para ingresar.")
        return False
    if not _focus_fundiciones_colada_field():
        return False
    try:
        form = _fundiciones_form()
        if form is None:
            return False
        colada_control = _fundiciones_control(form, FUNDICIONES_COLADA_CONTROL)
        current_colada_control = _fundiciones_control(form, "TxtCódFundición")
        if colada_control is None or current_colada_control is None:
            return False
        current_code = str(_fundiciones_read_control_value(current_colada_control) or "").strip()
        if current_code and _fundiciones_values_match(current_code, code):
            # El formulario PADRE ya esta posicionado en esta colada (p.ej.
            # el usuario ya cargo un material y ahora carga OTRO de la
            # MISMA colada con un click individual, no con el boton de
            # grupo). Reasignar form.Bookmark aqui, aunque sea al mismo
            # registro, reposiciona el formulario y ESO reinicia el
            # subformulario de materiales a su primer registro -- el mismo
            # problema que el boton de grupo ya resuelve evitando
            # reseleccionar la colada en cada material (ver
            # load_report_group_in_access). Sin este atajo, el segundo
            # material individual terminaba pisando al primero o colgando
            # la automatizacion a mitad de camino. Nada que mover: nos
            # vamos derecho a buscar el proximo material vacio.
            _debug(f"Colada ya posicionada en {code!r}; evito reposicionar Bookmark")
            _set_status(f"Colada ya seleccionada: {code}")
            return True
        _debug(f"Asignando {FUNDICIONES_COLADA_CONTROL} = {code!r}")
        colada_control.Value = code
        safe_code = code.replace('"', '""')
        rs = form.RecordsetClone
        _debug(f"Buscando RecordsetClone: [CódFundición] = {code!r}")
        rs.FindFirst(f'[CódFundición] = "{safe_code}"')
        if bool(rs.NoMatch):
            _debug(f"Colada NO encontrada: {code!r}")
            _set_status(f"No encontre la colada: {code}")
            return False
        _debug(f"Colada encontrada, moviendo Bookmark: {code!r}")
        form.Bookmark = rs.Bookmark
        _debug(f"Limpiando {FUNDICIONES_COLADA_CONTROL}")
        colada_control.Value = None
        _debug("SetFocus: TxtCódFundición")
        current_colada_control.SetFocus()
        _set_status(f"Colada seleccionada: {code}")
        return True
    except Exception as ex:
        _log_error("_select_fundiciones_colada", ex)
        _set_status(f"No pude ingresar la colada: {code}")
        return False


def _enter_fundiciones_responsible():
    _debug("Inicio paso responsable")
    if not _fundiciones_target_form_is_open():
        _set_status(f"Todavia no esta abierto {FUNDICIONES_TARGET_FORM}.")
        return False
    try:
        form = _fundiciones_form()
        if form is None:
            return False
        resp_control = _fundiciones_control(form, FUNDICIONES_RESP_CONTROL)
        if resp_control is None:
            return False
        _debug(f"Asignando {FUNDICIONES_RESP_CONTROL} = {FUNDICIONES_DEFAULT_RESP_CODE!r}")
        resp_control.Value = FUNDICIONES_DEFAULT_RESP_CODE
        try:
            resp_combo = _fundiciones_control(form, FUNDICIONES_RESP_COMBO)
            if resp_combo is not None:
                _debug(f"Asignando {FUNDICIONES_RESP_COMBO} = {FUNDICIONES_DEFAULT_RESP_CODE!r}")
                resp_combo.Value = FUNDICIONES_DEFAULT_RESP_CODE
        except Exception as ex:
            _log_error("_enter_fundiciones_responsible.combo", ex)

        try:
            subform = _fundiciones_materials_subform(form)
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
                _debug(f"Subform responsable actualizado en registros: {updated}")
        except Exception as ex:
            _log_error("_enter_fundiciones_responsible.subform", ex)

        _set_status(f"Responsable ingresado: {FUNDICIONES_DEFAULT_RESP_CODE}")
        return True
    except Exception as ex:
        _log_error("_enter_fundiciones_responsible", ex)
        _set_status(f"No pude ingresar responsable: {FUNDICIONES_DEFAULT_RESP_CODE}")
        return False


def _enter_fundiciones_completion_date():
    _debug("Inicio paso fecha aprobacion informe materiales")
    if not _fundiciones_target_form_is_open():
        _set_status(f"Todavia no esta abierto {FUNDICIONES_TARGET_FORM}.")
        return False
    try:
        form = _fundiciones_form()
        if form is None:
            return False
        date_control = _fundiciones_control(form, FUNDICIONES_APPROVAL_DATE_CONTROL)
        if date_control is None:
            return False
        approval_date = datetime.now().strftime("%d/%m/%Y")
        try:
            date_control.Enabled = True
            date_control.Locked = False
            _debug(f"Habilitado temporalmente {FUNDICIONES_APPROVAL_DATE_CONTROL}")
        except Exception as ex:
            _debug(f"No pude habilitar {FUNDICIONES_APPROVAL_DATE_CONTROL}: {ex}")
        _fundiciones_assign_control(
            date_control,
            FUNDICIONES_APPROVAL_DATE_CONTROL,
            approval_date,
            enter=False,
            focus=False,
        )
        _set_status(f"Fecha de aprobacion ingresada: {approval_date}")
        return True
    except Exception as ex:
        _debug(f"Fecha aprobacion ERROR: {ex}")
        _log_error("_enter_fundiciones_completion_date", ex)
        _set_status(f"No pude ingresar {FUNDICIONES_APPROVAL_DATE_CONTROL}.")
        return False


def _enter_fundiciones_colada(report):
    if not _select_fundiciones_colada(report):
        return False
    if not _enter_fundiciones_responsible():
        return False
    if not _enter_fundiciones_completion_date():
        return False
    _enter_fundiciones_material(report)
    return True


# ---------- subform de materiales ----------

def _fundiciones_recordset_field_names(recordset):
    names = []
    try:
        for idx in range(int(recordset.Fields.Count)):
            names.append(str(recordset.Fields.Item(idx).Name))
    except Exception as ex:
        _debug(f"No pude listar campos del recordset: {ex}")
    return names


def _fundiciones_material_field_name(recordset):
    names = _fundiciones_recordset_field_names(recordset)
    folded = {name.casefold(): name for name in names}
    for candidate in FUNDICIONES_MATERIAL_FIELD_CANDIDATES:
        found = folded.get(candidate.casefold())
        if found:
            return found
    for name in names:
        if "códmaterial" in name.casefold() or "codmaterial" in name.casefold():
            return name
    _debug(f"Campos disponibles material: {', '.join(names)}")
    return ""


def _fundiciones_find_material_in_recordset(recordset, material):
    field_name = _fundiciones_material_field_name(recordset)
    if not field_name:
        return False
    safe_field = field_name.replace("]", "]]")
    safe_material = str(material or "").replace('"', '""')
    criteria_options = [f'[{safe_field}] = "{safe_material}"']
    if str(material or "").strip().isdigit():
        criteria_options.append(f"[{safe_field}] = {int(str(material).strip())}")
    for criteria in criteria_options:
        try:
            _debug(f"Buscando material en RecordsetClone: {criteria}")
            recordset.FindFirst(criteria)
            if not bool(recordset.NoMatch):
                return True
        except Exception as ex:
            _debug(f"Criterio material fallo {criteria!r}: {ex}")
    return False


def _fundiciones_current_material_from_recordset(materials_subform):
    try:
        field_name = _fundiciones_material_field_name(materials_subform.Recordset)
        if not field_name:
            return ""
        return str(materials_subform.Recordset.Fields.Item(field_name).Value or "").strip()
    except Exception as ex:
        _debug(f"No pude leer material actual desde recordset: {ex}")
        return ""


def _fundiciones_current_material_record_is_empty(materials_subform):
    try:
        if bool(materials_subform.NewRecord):
            _debug("Registro material actual es NewRecord")
            return True
    except Exception:
        pass
    current = _fundiciones_current_material_from_recordset(materials_subform)
    _debug(f"Material actual para detectar espacio libre: {current!r}")
    return not current


def _select_fundiciones_empty_material_record(materials_subform):
    _debug("Buscando espacio libre para cargar informe de material")
    try:
        if _fundiciones_current_material_record_is_empty(materials_subform):
            _debug("Uso registro actual: material vacio")
            return True
    except Exception as ex:
        _debug(f"No pude evaluar registro actual: {ex}")

    try:
        rs = materials_subform.RecordsetClone
        field_name = _fundiciones_material_field_name(rs)
        if field_name and rs.RecordCount > 0:
            rs.MoveFirst()
            while not bool(rs.EOF):
                value = str(rs.Fields.Item(field_name).Value or "").strip()
                if not value:
                    materials_subform.Bookmark = rs.Bookmark
                    _debug("Registro material vacio encontrado en RecordsetClone")
                    return True
                rs.MoveNext()
    except Exception as ex:
        _debug(f"Busqueda de registro material vacio omitida: {ex}")
        _log_error("_select_fundiciones_empty_material_record.find", ex)

    try:
        try:
            materials_subform.SetFocus()
        except Exception as focus_ex:
            _debug(f"SetFocus subform antes de registro nuevo omitido: {focus_ex}")
        _debug("No habia registro material vacio; agregando registro nuevo directo sobre el subformulario")
        # ANTES esto hacia app.DoCmd.GoToRecord(pythoncom.Missing,
        # pythoncom.Missing, acNewRec=5): sin ObjectType/ObjectName,
        # GoToRecord actua sobre el "objeto activo" segun el foco de
        # Access. Si el SetFocus de arriba fallaba -- silencioso, atrapado
        # a proposito porque no siempre hace falta -- GoToRecord terminaba
        # creando el registro nuevo en el formulario PADRE (otra COLADA en
        # blanco) en vez del subformulario de materiales: el material
        # quedaba cargado en otra colada en vez del siguiente lugar vacio
        # de la MISMA colada (confirmado por el usuario, reproducible
        # cuando ya hay un material cargado y se carga un segundo de forma
        # individual). .Recordset.AddNew() -- el Recordset VIVO del
        # subformulario (NO RecordsetClone, que es de solo lectura para
        # esto) -- apunta siempre al objeto correcto sin pasar por DoCmd ni
        # depender de que ventana/control tenga el foco.
        materials_subform.Recordset.AddNew()
        return True
    except Exception as ex:
        _debug(f"No pude ir a registro nuevo libre de material: {ex}")
        _log_error("_select_fundiciones_empty_material_record.new", ex)
        _set_status(f"No pude navegar a un espacio libre. Usa {FUNDICIONES_MATERIAL_NEXT_CONTROL} y reintenta.")
        return False


def _select_fundiciones_material_record(materials_subform, material, create_if_missing=True):
    material = str(material or "").strip()
    if not material:
        return True
    _debug(f"Seleccionando registro material interno: {material!r}")

    try:
        rs = materials_subform.RecordsetClone
        if rs.RecordCount > 0:
            if _fundiciones_find_material_in_recordset(rs, material):
                materials_subform.Bookmark = rs.Bookmark
                _debug(f"Registro material encontrado por CódMaterial: {material!r}")
                return True
    except Exception as ex:
        _debug(f"Busqueda de material existente omitida: {ex}")
        _log_error("_select_fundiciones_material_record.find", ex)

    try:
        current = _fundiciones_current_material_from_recordset(materials_subform)
        _debug(f"Material actual por recordset antes de navegar: {current!r}")
        if current == material:
            return True
        if create_if_missing and not current:
            return True
    except Exception as ex:
        _debug(f"No pude leer material actual: {ex}")

    if not create_if_missing:
        _set_status(f"No encontre el material {material} en la colada.")
        return False

    try:
        import pythoncom
        import win32com.client
        app = win32com.client.GetActiveObject("Access.Application")
        try:
            materials_subform.SetFocus()
        except Exception as focus_ex:
            _debug(f"SetFocus subform antes de nuevo registro omitido: {focus_ex}")
        _debug("Material no encontrado; yendo a registro nuevo interno")
        app.DoCmd.GoToRecord(pythoncom.Missing, pythoncom.Missing, 5)
        return True
    except Exception as ex:
        _debug(f"No pude ir a registro nuevo de material: {ex}")
        _log_error("_select_fundiciones_material_record.new", ex)
        _set_status(f"No pude navegar a un espacio libre para material {material}. Usa {FUNDICIONES_MATERIAL_NEXT_CONTROL}.")
        return False


def _focus_fundiciones_materials_subform_control(form, subform_control=None, subform=None, control_name=None):
    _debug(
        f"Enfocando subform material: {FUNDICIONES_MATERIALS_SUBFORM}"
        + (f".{control_name}" if control_name else "")
    )
    if not _activate_fundiciones_window():
        _debug("No pude activar ventana para enfocar subform material")
        return None
    if subform_control is None:
        subform_control = _fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
    if subform is None and subform_control is not None:
        try:
            subform = subform_control.Form
        except Exception as ex:
            _debug(f"No pude obtener Form del subform material: {ex}")
            return None
    if subform_control is None or subform is None:
        return None
    try:
        subform_control.SetFocus()
        _debug(f"SetFocus OK contenedor: {FUNDICIONES_MATERIALS_SUBFORM}")
    except Exception as ex:
        _debug(f"SetFocus contenedor omitido: {FUNDICIONES_MATERIALS_SUBFORM}: {ex}")
    if not control_name:
        return None
    control = _fundiciones_control(subform, control_name)
    if control is None:
        return None
    try:
        control.SetFocus()
        _debug(f"SetFocus OK interno: {FUNDICIONES_MATERIALS_SUBFORM}.{control_name}")
        return control
    except Exception as ex:
        # Antes esto devolvia `control` igual aunque SetFocus fallara --
        # el llamador (_go_fundiciones_material_record) lo tomaba como
        # "conseguido" y le hacia .Click(), que ademas ni siquiera es un
        # metodo valido en un boton de Access via COM (confirmado en la
        # practica). None es lo correcto: "no se pudo enfocar este control".
        _debug(f"SetFocus interno ERROR: {FUNDICIONES_MATERIALS_SUBFORM}.{control_name}: {ex}")
        _log_error("_focus_fundiciones_materials_subform_control", f"{FUNDICIONES_MATERIALS_SUBFORM}.{control_name}: {ex}")
        return None


def _go_fundiciones_material_record(direction="next"):
    """Avanza/retrocede un registro en el subform de materiales -- via el
    boton cmdMaterialSiguiente/cmdMaterialAnterior si acepta foco (se lo
    "aprieta" con Enter, no con .Click() -- eso NO es un metodo valido en
    un boton de Access via COM automation, confirmado en la practica con
    un AttributeError que dejaba el formulario roto), o via
    DoCmd.GoToRecord si el boton no acepta foco."""
    _debug(f"Navegacion material solicitada: {direction}")
    form = _fundiciones_form()
    if form is None:
        return False
    subform_control = _fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
    subform = _fundiciones_materials_subform(form)
    if subform_control is None or subform is None:
        return False
    button_name = FUNDICIONES_MATERIAL_NEXT_CONTROL if direction == "next" else FUNDICIONES_MATERIAL_PREV_CONTROL
    button = _focus_fundiciones_materials_subform_control(form, subform_control, subform, button_name)
    if button is not None:
        try:
            import win32com.client
            shell = win32com.client.Dispatch("WScript.Shell")
            time.sleep(0.08)
            shell.SendKeys("{ENTER}")
            time.sleep(0.12)
            _set_status(f"Navegado con Enter sobre {button_name}.")
            return True
        except Exception as ex:
            _debug(f"Enter sobre {button_name} fallo: {ex}")
            _log_error("_go_fundiciones_material_record.enter", ex)
    else:
        _debug(f"No pude dar foco a {button_name}; pruebo GoToRecord")
    try:
        import pythoncom
        import win32com.client
        app = win32com.client.GetActiveObject("Access.Application")
        _focus_fundiciones_materials_subform_control(form, subform_control, subform, FUNDICIONES_MATERIAL_CONTROL)
        app.DoCmd.GoToRecord(pythoncom.Missing, pythoncom.Missing, 1 if direction == "next" else 0)
        _set_status(f"Navegado material {direction}.")
        return True
    except Exception as ex:
        _debug(f"Navegacion material ERROR: {ex}")
        _log_error("_go_fundiciones_material_record", ex)
        _set_status(f"No pude navegar material {direction}.")
        return False


def _focus_fundiciones_material_review_position(form, subform_control, subform):
    _debug("Enfocando posicion de revision de material")
    try:
        if not _activate_fundiciones_window():
            return False
        try:
            subform_control.SetFocus()
            _debug(f"SetFocus OK contenedor revision: {FUNDICIONES_MATERIALS_SUBFORM}")
            return True
        except Exception as ex:
            _debug(f"SetFocus contenedor revision omitido: {ex}")
        for control_name in (
            FUNDICIONES_MATERIAL_NEXT_CONTROL,
            FUNDICIONES_MATERIAL_PREV_CONTROL,
            FUNDICIONES_REPORT_OBS_CONTROL,
            FUNDICIONES_RESISTANCE_CONTROL,
        ):
            control = _fundiciones_control(subform, control_name)
            if control is None:
                continue
            try:
                control.SetFocus()
                _debug(f"SetFocus OK revision: {FUNDICIONES_MATERIALS_SUBFORM}.{control_name}")
                return True
            except Exception as ex:
                _debug(f"SetFocus revision omitido {control_name}: {ex}")
        current_colada_control = _fundiciones_control(form, "TxtCódFundición")
        if current_colada_control is not None:
            try:
                current_colada_control.SetFocus()
                _debug("SetFocus OK fallback revision: TxtCódFundición")
                return True
            except Exception as ex:
                _debug(f"SetFocus fallback TxtCódFundición omitido: {ex}")
        return False
    except Exception as ex:
        _debug(f"Foco revision material ERROR: {ex}")
        _log_error("_focus_fundiciones_material_review_position", ex)
        return False


# ---------- espesores ----------

def _prepare_fundiciones_thickness_subform(materials_subform, material):
    _debug(f"Preparando subform espesores para material={material!r}")
    control = _fundiciones_control(materials_subform, FUNDICIONES_THICKNESS_SUBFORM)
    if control is None:
        return False
    try:
        control.Enabled = True
        control.Locked = False
        control.Visible = True
    except Exception as ex:
        _debug(f"No pude habilitar {FUNDICIONES_THICKNESS_SUBFORM}: {ex}")
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
            _debug(f"RowSource filtrado {FUNDICIONES_THICKNESS_CONTROL}: material={material!r}")
        subform.Requery()
        return True
    except Exception as ex:
        _debug(f"Preparar espesores ERROR: {ex}")
        _log_error("_prepare_fundiciones_thickness_subform", ex)
        return False


def _save_fundiciones_material_record(materials_subform):
    _debug("Intentando guardar registro de material para habilitar espesores")
    try:
        if bool(materials_subform.Dirty):
            materials_subform.Dirty = False
            _debug("Registro de material guardado con Dirty=False")
        else:
            _debug("Registro de material no estaba Dirty")
        return True
    except Exception as ex:
        _debug(f"Guardar material ERROR: {ex}")
        _log_error("_save_fundiciones_material_record", ex)
        _set_status(f"No pude guardar material antes de espesores: {ex}")
        return False


def _enter_fundiciones_material_responsible(materials_subform):
    _debug("Inicio paso responsable material")
    try:
        resp_control = _fundiciones_control(materials_subform, FUNDICIONES_MATERIAL_RESP_CONTROL)
        if resp_control is not None:
            _fundiciones_assign_control(
                resp_control, FUNDICIONES_MATERIAL_RESP_CONTROL, FUNDICIONES_DEFAULT_RESP_CODE, enter=False, focus=False,
            )
        resp_combo = _fundiciones_control(materials_subform, FUNDICIONES_MATERIAL_RESP_COMBO)
        if resp_combo is not None:
            _fundiciones_assign_control(
                resp_combo, FUNDICIONES_MATERIAL_RESP_COMBO, FUNDICIONES_DEFAULT_RESP_CODE, enter=False, focus=False,
            )
        return True
    except Exception as ex:
        _debug(f"Responsable material ERROR: {ex}")
        _log_error("_enter_fundiciones_material_responsible", ex)
        _set_status(f"No pude ingresar responsable material: {FUNDICIONES_DEFAULT_RESP_CODE}")
        return False


def _enter_fundiciones_thickness_fields(materials_subform, report):
    material = str(report.get("material", "") or "").strip()
    thickness = _fundiciones_thickness_text(report)
    hardness = _fundiciones_hardness_text(report)
    graphite_size = _fundiciones_graphite_size_text(report)
    _debug(
        "Inicio paso espesores: "
        f"espesor={thickness!r}, dureza={hardness!r}, tam_grafito={graphite_size!r}"
    )
    if not any((thickness, hardness, graphite_size)):
        _debug("Paso espesores omitido: no hay datos para cargar")
        return True

    _prepare_fundiciones_thickness_subform(materials_subform, material)
    thickness_subform = _fundiciones_thickness_subform(materials_subform)
    if thickness_subform is None:
        return False

    if thickness:
        thickness_control = _fundiciones_control(thickness_subform, FUNDICIONES_THICKNESS_CONTROL)
        if thickness_control is None:
            return False
        thickness_value = _fundiciones_combo_bound_value(
            thickness_control, thickness, aliases=_fundiciones_thickness_aliases(thickness),
        )
        if thickness_value is None:
            _set_status(f"No pude resolver {FUNDICIONES_THICKNESS_CONTROL} = {thickness}.")
            return False
        _debug(f"{FUNDICIONES_THICKNESS_CONTROL}: visible {thickness!r} -> interno {thickness_value!r}")
        _fundiciones_assign_control(thickness_control, FUNDICIONES_THICKNESS_CONTROL, thickness_value)

    if hardness:
        hardness_control, hardness_control_name = _fundiciones_control_any(
            thickness_subform, FUNDICIONES_HARDNESS_CONTROL_ALIASES,
        )
        if hardness_control is None:
            return False
        _fundiciones_assign_control(hardness_control, hardness_control_name, hardness)

    if graphite_size:
        graphite_size_control, graphite_size_control_name = _fundiciones_control_any(
            thickness_subform, FUNDICIONES_GRAPHITE_SIZE_CONTROL_ALIASES,
        )
        if graphite_size_control is None:
            return False
        graphite_size_value = _fundiciones_combo_bound_value(graphite_size_control, graphite_size)
        if graphite_size_value is None:
            _set_status(f"No pude resolver {graphite_size_control_name} = {graphite_size}.")
            return False
        _debug(f"{graphite_size_control_name}: visible {graphite_size!r} -> interno {graphite_size_value!r}")
        # Sin Enter en el primer intento: a diferencia de los otros combos
        # de este formulario, este es el ULTIMO control de la fila del
        # subformulario de espesores (continuo) -- el Enter no solo
        # confirma el valor, tambien avanza el subformulario a una fila
        # NUEVA (comportamiento estandar de Access en formularios
        # continuos al tabular/Enter en el ultimo campo). Eso hacia que la
        # verificacion de abajo leyera el valor de la fila nueva (vacia) en
        # vez de la que se acababa de llenar, viera "distinto" el 100% de
        # las veces, y el reintento terminara escribiendo el tamaño una
        # segunda vez -- confirmado en logs reales (07/10/2026, reporte
        # del usuario "el tamaño lo ingresa dos veces"). .Value ya deja el
        # valor puesto en el campo bound sin que haga falta Enter.
        _fundiciones_assign_control(graphite_size_control, graphite_size_control_name, graphite_size_value, enter=False)
        if not _fundiciones_verify_control_value(graphite_size_control, graphite_size_value):
            _debug(f"{graphite_size_control_name}: quedo distinto al asignar sin Enter, reintento CON Enter de confirmacion")
            _fundiciones_assign_control(graphite_size_control, graphite_size_control_name, graphite_size_value, enter=True)
            if not _fundiciones_verify_control_value(graphite_size_control, graphite_size_value):
                actual = _fundiciones_read_control_value(graphite_size_control)
                _debug(
                    f"{graphite_size_control_name}: verificacion fallo. "
                    f"esperado={graphite_size_value!r} actual={actual!r}"
                )
                _set_status(f"{graphite_size_control_name} quedo en {actual!r} en vez de {graphite_size!r}. Revisalo en Access.")
                return False

    return True


# ---------- material (grafito / matriz / CE / resistencia / elongacion) ----------

def _enter_fundiciones_material(report):
    """Carga los campos de UN material en el subformulario -- usada tanto
    por la carga individual como por cada vuelta del loop de carga de
    grupo (load_report_group_in_access), que solo selecciona la colada
    una vez y despues llama esto una vez por material, en orden, sin
    volver a tocar la colada -- eso es lo que evita que el subformulario
    se reposicione entre un material y el siguiente."""
    _debug("Inicio paso subform material/morfologia/matriz")
    material = str(report.get("material", "") or "").strip()
    family = _family_for_report(report)
    graphite = _fundiciones_graphite_combo_text(report)
    graphite_type = _fundiciones_graphite_type_text(report)
    density_min, density_max = _fundiciones_nodular_density_values(report)
    matrix = _fundiciones_matrix_combo_text(report)
    matrix_percent = _fundiciones_predominant_matrix_percent(report)
    carbon_equivalent = _fundiciones_carbon_equivalent_access_value(report)
    resistance = _fundiciones_resistance_text(report)
    elongation = _fundiciones_elongation_text(report) if family == "Nodular" else ""
    report_obs = _fundiciones_report_observation_access_text(report)
    material_obs = _fundiciones_material_observation_text(report)
    thickness = _fundiciones_thickness_text(report)
    hardness = _fundiciones_hardness_text(report)
    graphite_size = _fundiciones_graphite_size_text(report)
    _debug(
        "Datos calculados: "
        f"material={material!r}, family={family!r}, graphite={graphite!r}, "
        f"graphite_type={graphite_type!r}, density_min={density_min!r}, "
        f"density_max={density_max!r}, matrix={matrix!r}, matrix_percent={matrix_percent!r}, "
        f"carbon_equivalent={carbon_equivalent!r}, resistance={resistance!r}, elongation={elongation!r}, "
        f"report_obs={report_obs!r}, material_obs={material_obs!r}, thickness={thickness!r}, hardness={hardness!r}, "
        f"graphite_size={graphite_size!r}"
    )
    if not material:
        _set_status("No hay material final para ingresar.")
        return False
    if not _fundiciones_target_form_is_open():
        _set_status(f"Todavia no esta abierto {FUNDICIONES_TARGET_FORM}.")
        return False
    try:
        form = _fundiciones_form()
        if form is None:
            return False
        subform_control = _fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
        subform = _fundiciones_materials_subform(form)
        if subform_control is None or subform is None:
            return False
        if not _select_fundiciones_empty_material_record(subform):
            return False
        material_control = _fundiciones_control(subform, FUNDICIONES_MATERIAL_CONTROL)
        if material_control is None:
            return False
        graphite_control = _fundiciones_control(subform, FUNDICIONES_GRAPHITE_CONTROL)
        if graphite_control is None:
            return False
        subform_control.SetFocus()
        _fundiciones_assign_control(material_control, FUNDICIONES_MATERIAL_CONTROL, material)
        graphite_value = _fundiciones_combo_bound_value(graphite_control, graphite)
        if graphite_value is None:
            _set_status(f"No pude resolver {FUNDICIONES_GRAPHITE_CONTROL} = {graphite}.")
            return False
        _debug(f"{FUNDICIONES_GRAPHITE_CONTROL}: visible {graphite!r} -> interno {graphite_value!r}")
        _fundiciones_assign_control(graphite_control, FUNDICIONES_GRAPHITE_CONTROL, graphite_value)
        if family == "Nodular":
            _debug("Rama especifica: Nodular -> densidades")
            if not density_min or not density_max:
                _set_status("No hay densidad de nodulos para nodular.")
                return False
            density_min_control = _fundiciones_control(subform, FUNDICIONES_DENSITY_MIN_CONTROL)
            density_max_control = _fundiciones_control(subform, FUNDICIONES_DENSITY_MAX_CONTROL)
            if density_min_control is None or density_max_control is None:
                return False
            _fundiciones_assign_control(density_min_control, FUNDICIONES_DENSITY_MIN_CONTROL, density_min)
            _fundiciones_assign_control(density_max_control, FUNDICIONES_DENSITY_MAX_CONTROL, density_max)
        else:
            _debug("Rama especifica: Laminar/Gris -> tipo morfologia")
            if not graphite_type:
                _set_status("No hay tipo de morfologia grafito para gris/laminar.")
                return False
            graphite_type_control = _fundiciones_control(subform, FUNDICIONES_GRAPHITE_TYPE_CONTROL)
            if graphite_type_control is None:
                return False
            graphite_type_value = _fundiciones_combo_bound_value(graphite_type_control, graphite_type)
            if graphite_type_value is None:
                _set_status(f"No pude resolver {FUNDICIONES_GRAPHITE_TYPE_CONTROL} = {graphite_type}.")
                return False
            _debug(f"{FUNDICIONES_GRAPHITE_TYPE_CONTROL}: visible {graphite_type!r} -> interno {graphite_type_value!r}")
            _fundiciones_assign_control(graphite_type_control, FUNDICIONES_GRAPHITE_TYPE_CONTROL, graphite_type_value)
        if matrix:
            _debug("Inicio paso matriz")
            matrix_control = _fundiciones_control(subform, FUNDICIONES_MATRIX_CONTROL)
            if matrix_control is None:
                return False
            matrix_value = _fundiciones_combo_bound_value(matrix_control, matrix)
            if matrix_value is None:
                _set_status(f"No pude resolver {FUNDICIONES_MATRIX_CONTROL} = {matrix}.")
                return False
            _debug(f"{FUNDICIONES_MATRIX_CONTROL}: visible {matrix!r} -> interno {matrix_value!r}")
            _fundiciones_assign_control(matrix_control, FUNDICIONES_MATRIX_CONTROL, matrix_value)
        if matrix_percent:
            matrix_percent_control = _fundiciones_control(subform, FUNDICIONES_MATRIX_PERCENT_CONTROL)
            if matrix_percent_control is None:
                return False
            matrix_percent_value = _fundiciones_combo_bound_value(matrix_percent_control, matrix_percent)
            if matrix_percent_value is None:
                _set_status(f"No pude resolver {FUNDICIONES_MATRIX_PERCENT_CONTROL} = {matrix_percent}.")
                return False
            _debug(f"{FUNDICIONES_MATRIX_PERCENT_CONTROL}: visible {matrix_percent!r} -> interno {matrix_percent_value!r}")
            _fundiciones_assign_control(matrix_percent_control, FUNDICIONES_MATRIX_PERCENT_CONTROL, matrix_percent_value)
        if carbon_equivalent not in ("", None):
            ce_control = _fundiciones_control(subform, FUNDICIONES_CE_CONTROL)
            if ce_control is None:
                return False
            _fundiciones_assign_control(ce_control, FUNDICIONES_CE_CONTROL, carbon_equivalent)
        if resistance:
            resistance_control = _fundiciones_control(subform, FUNDICIONES_RESISTANCE_CONTROL)
            if resistance_control is None:
                return False
            _fundiciones_assign_control(resistance_control, FUNDICIONES_RESISTANCE_CONTROL, resistance)
        if family == "Nodular" and elongation:
            elongation_control = _fundiciones_control(subform, FUNDICIONES_ELONGATION_CONTROL)
            if elongation_control is None:
                return False
            _fundiciones_assign_control(elongation_control, FUNDICIONES_ELONGATION_CONTROL, elongation)
        if report_obs:
            report_obs_control = _fundiciones_control(subform, FUNDICIONES_REPORT_OBS_CONTROL)
            if report_obs_control is None:
                return False
            _fundiciones_assign_control(report_obs_control, FUNDICIONES_REPORT_OBS_CONTROL, report_obs, enter=False, focus=False)
        if material_obs:
            material_obs_control = _fundiciones_control(subform, FUNDICIONES_MATERIAL_OBS_CONTROL)
            if material_obs_control is None:
                return False
            _fundiciones_assign_control(material_obs_control, FUNDICIONES_MATERIAL_OBS_CONTROL, material_obs)
        if not _enter_fundiciones_material_responsible(subform):
            return False
        if not _save_fundiciones_material_record(subform):
            return False
        if not _enter_fundiciones_thickness_fields(subform, report):
            return False
        _set_status(
            f"Paso hasta espesores completo: material {material}; grafito {graphite}; "
            f"matriz {matrix} {matrix_percent}; CE {carbon_equivalent}; R {resistance}"
        )
        return True
    except Exception as ex:
        _log_error("_enter_fundiciones_material", ex)
        _set_status(f"No pude ingresar material/grafito/matriz: {material}")
        return False


# ---------- revision (abrir sin cargar datos) ----------

def _review_current_report_in_access(report):
    _debug("Inicio abrir informe en Access")
    material = str(report.get("material", "") or "").strip()
    if not material:
        _set_status("Completa el material antes de abrir en Access.")
        return False
    if not _select_fundiciones_colada(report):
        return False
    try:
        form = _fundiciones_form()
        if form is None:
            return False
        subform_control = _fundiciones_control(form, FUNDICIONES_MATERIALS_SUBFORM)
        subform = _fundiciones_materials_subform(form)
        if subform_control is None or subform is None:
            return False
        if not _select_fundiciones_material_record(subform, material, create_if_missing=False):
            _set_status(f"Access abierto, pero no encontre el material {material}.")
            return False
        _focus_fundiciones_material_review_position(form, subform_control, subform)
        _set_status(f"Access abierto en material {material}.")
        return True
    except Exception as ex:
        _debug(f"Abrir Access material ERROR: {ex}")
        _log_error("_review_current_report_in_access", ex)
        _set_status(f"No pude abrir material en Access: {ex}")
        return False


# ---------- puntos de entrada publicos (botones "Cargar en Access" / "Abrir en Access") ----------

def load_report_in_access(report):
    """Puerto de _load_current_report_in_access -- boton real 'Cargar en
    Access' de la pestaña Calidad: abre/activa Fundiciones, entra la colada,
    responsable, fecha, y carga el material completo hasta espesores."""
    lote = str((report or {}).get("lote", "") or "").strip()
    material = str((report or {}).get("material", "") or "").strip()
    if not lote:
        _set_status("Completa el lote / colada antes de enviar.")
        return False
    if not material:
        _set_status("Completa el material antes de enviar.")
        return False
    return bool(open_fundiciones_app(report, enter_colada=True, review=False))


def load_report_group_in_access(reports):
    """Boton 'Cargar en Access' aplicado a un GRUPO completo (los N
    materiales de una misma colada) -- pedido del usuario: "poder cargar
    los 3 grupos de informes de calidad de un solo click" en vez de tener
    que seleccionar cada material a mano y apretar el boton una vez por
    cada uno.

    Colada + responsable + fecha se entran UNA sola vez -- y esa es la
    parte que en los hechos resuelve el reclamo original ("no sabe pasar
    de material adentro de una colada"): el flujo viejo hacia
    _select_fundiciones_colada (que reposiciona el formulario PADRE con
    Bookmark) una vez por CADA click en "Cargar en Access", y eso
    reinicia el subformulario de materiales a su primer registro cada
    vez -- por eso el segundo/tercer material terminaba pisando al
    primero en vez de agregarse. Aca la colada se selecciona UNA sola vez
    y los N materiales se cargan en el mismo posicionamiento, todos con
    _enter_fundiciones_material (la MISMA busqueda de espacio vacio /
    GoToRecord(acNewRec) que ya usaba la carga individual -- sin cambios
    ahi, es codigo probado). Se descarto a proposito una version que
    avanzaba con cmdMaterialSiguiente via Click(): ese metodo no existe
    en la automatizacion COM de un boton de Access (AttributeError
    'Item.Click' confirmado en la practica) y dejaba el formulario en un
    estado roto -- no reintentar esa via sin poder probarla en la maquina
    real.

    `reports` tiene que ser la lista de informes de la MISMA colada
    (mismo lote), en el orden en que se quieren cargar -- el router los
    ordena por nombre de material, igual que la pantalla. Si un material
    falla se corta ahi: no tiene sentido seguir con los que quedan sobre
    una posicion del formulario que ya no se sabe cual es."""
    if not reports:
        _set_status("No hay materiales para cargar.")
        return False
    lote = str((reports[0] or {}).get("lote", "") or "").strip()
    if not lote:
        _set_status("Completa el lote / colada antes de enviar.")
        return False
    for report in reports:
        if not str((report or {}).get("material", "") or "").strip():
            _set_status("Hay un material sin completar en el grupo.")
            return False

    if not open_fundiciones_app(None, enter_colada=False, review=False):
        return False
    if not _select_fundiciones_colada(reports[0]):
        return False
    if not _enter_fundiciones_responsible():
        return False
    if not _enter_fundiciones_completion_date():
        return False

    for idx, report in enumerate(reports):
        material = str(report.get("material", "") or "")
        _debug(f"Grupo: cargando material {idx + 1}/{len(reports)}: {material!r}")
        ok = _enter_fundiciones_material(report)
        if not ok:
            _set_status(
                f"Se cargaron {idx} de {len(reports)} materiales del grupo (lote {lote}) -- "
                f"fallo en {material}: {get_status()}"
            )
            return False
    _set_status(f"Cargados los {len(reports)} materiales del grupo (lote {lote}).")
    return True


def open_report_for_review(report):
    """Puerto de _open_current_report_in_access_for_review -- boton real
    'Abrir en Access': navega hasta el material sin volver a cargar datos,
    para revisar a ojo lo ya cargado."""
    lote = str((report or {}).get("lote", "") or "").strip()
    material = str((report or {}).get("material", "") or "").strip()
    if not lote:
        _set_status("Completa el lote / colada antes de enviar.")
        return False
    if not material:
        _set_status("Completa el material antes de enviar.")
        return False
    return bool(open_fundiciones_app(report, enter_colada=False, review=True))


# ---------- diagnostico (sin equivalente de UI en produccion, pero util para
# depurar nombres de controles contra la base real sin poder probarlo yo
# mismo -- puerto de _goto_fundiciones_control / _detect_fundiciones_active_control,
# las mismas que alimentaban la ventana "Probar campos Fundiciones") ----------

def goto_control(control_name):
    try:
        if _access_modal_dialog_open():
            _set_status("Access tiene un aviso abierto.")
            return False
        if not _activate_fundiciones_window():
            _set_status("No encontre la ventana de Fundiciones.")
            return False
        import win32com.client
        app = win32com.client.GetActiveObject("Access.Application")
        errors = []
        try:
            app.DoCmd.GoToControl(control_name)
            _set_status(f"OK GoToControl: {control_name}")
            return True
        except Exception as ex:
            errors.append(f"GoToControl: {ex}")
        for form_name in ("frmInicial", "frmCargaInformesFundiciones", "frmCargaInformesMateriales"):
            try:
                app.Forms.Item(form_name).Controls.Item(control_name).SetFocus()
                _set_status(f"OK SetFocus: {form_name}.{control_name}")
                return True
            except Exception as ex:
                errors.append(f"{form_name}.{control_name}: {ex}")
        try:
            target_form = app.Forms.Item(FUNDICIONES_TARGET_FORM)
            materials_control = target_form.Controls.Item(FUNDICIONES_MATERIALS_SUBFORM)
            materials_control.SetFocus()
            materials_subform = materials_control.Form
            materials_subform.Controls.Item(control_name).SetFocus()
            _set_status(f"OK SetFocus: {FUNDICIONES_MATERIALS_SUBFORM}.{control_name}")
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
            _set_status(f"OK SetFocus: {FUNDICIONES_THICKNESS_SUBFORM}.{control_name}")
            return True
        except Exception as ex:
            errors.append(f"{FUNDICIONES_THICKNESS_SUBFORM}.{control_name}: {ex}")
        try:
            app.Screen.ActiveForm.Controls.Item(control_name).SetFocus()
            _set_status(f"OK ActiveForm.SetFocus: {control_name}")
            return True
        except Exception as ex:
            errors.append(f"ActiveForm.{control_name}: {ex}")
        _set_status(f"No funciono: {control_name}")
        _log_error("goto_control", "; ".join(errors[-3:]))
        return False
    except Exception as ex:
        _log_error("goto_control", ex)
        _set_status(f"Error: {control_name}")
        return False


def detect_active_control():
    try:
        if not _activate_fundiciones_window():
            _set_status("No encontre la ventana de Fundiciones.")
            return None
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
        _set_status(detail)
        return {"form": form_name, "control": control_name, "control_source": control_source}
    except Exception as ex:
        _log_error("detect_active_control", ex)
        _set_status(f"No pude detectar activo: {ex}")
        return None


def go_material_record(direction="next"):
    return bool(_go_fundiciones_material_record(direction))
