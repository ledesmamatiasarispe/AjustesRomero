# rutas/termico.py -- puerto 1:1 de backend/routers/termico.py de ajuste_comp_web. Pestaña "Análisis
# Térmico": lee las curvas de enfriamiento (Carbono / Microestructura) exportadas por el equipo Carbomax a la
# MISMA carpeta compartida que usaba la app de escritorio (THERMAL_ANALYSIS_DIR), las vincula a coladas de
# Históricos por cercanía de horario, y calcula los indicadores (TSE/TRE/REC/expansión gráfica).
#
# Además de la carpeta, también se puede descargar en vivo desde la página web que hostea el propio equipo
# Carbomax en su IP (HistIndex.dat + dadoshist.cgi) -- ver POST /download, que reusa ..device_sync tal cual.
#
# Cambio deliberado respecto del original: _parse_excel usaba win32com.client (automatizaba una instancia
# real de Excel) -- acá se usa openpyxl (Python puro, no necesita Excel instalado, mucho más rápido). Por
# ser mucho más rápido, "needs_review" se calcula EAGER para todos los archivos no vinculados en cada
# listado, en vez de depender de una cache que solo se llena a medida que el operario hace click en cada
# archivo -- mejora deliberada, no un recorte.
import csv
import os
import subprocess
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException, Query

from .. import datos
from .. import device_sync
from .. import dispositivos as devices
from ..ws import hub

router = APIRouter(prefix="/api/termico", tags=["termico"])

THERMAL_ANALYSIS_DIR = Path(r"C:\Users\LABOR01\Desktop\microestructura anialisis carbo2\exels")
THERMAL_EXTENSIONS = {".xlsx", ".csv"}
THERMAL_MODE_OPTIONS = ("Microestructura", "Carbono", "Todos")
DEFAULT_THERMAL_DEVICE_IP = "192.168.0.180"
THERMAL_MATCH_MAX_DELTA = timedelta(hours=6)
THERMAL_CHART_MAX_POINTS_PER_CURVE = 1400
THERMAL_RESULTS_NOTE = (
    "Supuesto de tiempos: se usa tag1=TL, tag2=TSE, tag3=TRE y tag4=TF, y esos tags estan en segundos. "
    "Si el equipo usa otra correspondencia, ajustamos la formula."
)

# OJO: las variantes con "Ã", "Ã§Ã£", etc. no son errores de tipeo -- son
# formas mojibake reales que aparecen en archivos exportados por el equipo
# Carbomax (software en portugues) cuando Excel/Windows los reabre con una
# codificacion distinta a la original.
THERMAL_FIELD_ALIASES_V2 = {
    "ID": ("ID",),
    "IP": ("IP",),
    "Equipamento": ("Equipamento", "Equipamiento"),
    "Modo": ("Modo",),
    "Canal": ("Canal",),
    "Material": ("Material",),
    "Lote": ("Lote",),
    "Observacion": ("Observacao", "Observação", "Observacion", "ObservaÃ§Ã£o", "ObservaÃƒÂ§ÃƒÂ£o"),
    "Dt Inicio": ("Dt Inicio", "Dt Início", "Dt InÃ­cio", "Dt InÃƒÂ­cio"),
    "Dt Termino": ("Dt Termino", "Dt Término", "Dt TÃ©rmino", "Dt TÃƒÂ©rmino"),
    "Pico": ("Pico",),
    "TL": ("TL",),
    "CE %": ("CE %",),
    "TS": ("TS", "Solidus"),
    "C %": ("C %", "Carbono %"),
    "Si %": ("Si %", "Silicio %", "Silicon %"),
    "TSE": ("TSE",),
    "TRE": ("TRE",),
    "REC": ("REC",),
    "Delta REC C/s": ("Delta REC C/s", "Δ REC °C/s", "âˆ† REC Â°C/s", "Ã¢Ë†â€  REC Ã‚Â°C/s"),
    "TF": ("TF",),
    "tag1 / TL (s)": ("tag1",),
    "tag2 / TSE (s)": ("tag2",),
    "tag3 / TRE (s)": ("tag3",),
    "tag4 / TF (s)": ("tag4",),
}
THERMAL_INFO_COMMON_V2 = (
    "ID", "IP", "Equipamento", "Modo", "Canal", "Material", "Lote", "Observacion", "Dt Inicio", "Dt Termino",
)
THERMAL_INFO_MICRO_V2 = THERMAL_INFO_COMMON_V2 + (
    "Pico", "TL", "CE %", "TSE", "TRE", "REC", "Delta REC C/s", "TF",
    "tag1 / TL (s)", "tag2 / TSE (s)", "tag3 / TRE (s)", "tag4 / TF (s)",
)
THERMAL_INFO_CARBON_V2 = THERMAL_INFO_COMMON_V2 + (
    "Pico", "TL", "CE %", "TS", "C %", "Si %", "TF",
    "tag1 / TL (s)", "tag2 / TSE (s)", "tag3 / TRE (s)", "tag4 / TF (s)",
)


# ---------- helpers puros (parseo/formato) ----------

def _parse_decimal(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    raw = raw.replace(" ", "")
    if "," in raw and "." in raw:
        raw = raw.replace(".", "").replace(",", ".")
    else:
        raw = raw.replace(",", ".")
    try:
        return float(raw)
    except Exception:
        return None


def _device_mode_group(mode_value):
    mode = str(mode_value or "").upper()
    if "MICR" in mode:
        return "Microestructura"
    if "CARB" in mode:
        return "Carbono"
    return "Todos"


def _info_alias_value(info, *aliases):
    for alias in aliases:
        value = str((info or {}).get(alias, "") or "").strip()
        if value:
            return value
    return ""


def _pick_info_value(info, aliases):
    for alias in aliases:
        value = str(info.get(alias, "") or "").strip()
        if value:
            return value
    return ""


def _payload_carbon_silicon(payload):
    """Extrae C/Si de un payload de dispositivo (acepta coma o punto decimal, con los alias en portugues
    del equipo) -- único lugar que hace este parseo; usado tanto por _check_current_session_carbon como por
    el loop de Carbomax automático de red (..carbomax_auto, todavía no activo -- ver decisión del
    11/09/2026)."""
    info = payload.get("info", {}) if isinstance(payload, dict) else {}
    if not isinstance(info, dict):
        return None, None
    carbon = _parse_decimal(_info_alias_value(info, "C %", "Carbono %"))
    silicon = _parse_decimal(_info_alias_value(info, "Si %", "Silicio %"))
    return carbon, silicon


def _canonicalize_info(raw_info):
    out = {}
    for display, aliases in THERMAL_FIELD_ALIASES_V2.items():
        for alias in aliases:
            value = str(raw_info.get(alias, "") or "").strip()
            if value:
                out[display] = value
                break
    return out


def _parse_device_info_datetime(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S", "%Y-%m-%d %H:%M:%S", "%d%m%Y %H%M%S", "%d%m%Y%H%M%S"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            pass
    return None


def _parse_session_datetime(value):
    raw = str(value or "").strip()
    if not raw:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S", "%d/%m/%Y %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            return datetime.strptime(raw, fmt)
        except Exception:
            pass
    return None


def _payload_datetime(payload):
    if not isinstance(payload, dict):
        return None
    info = payload.get("info", {}) if isinstance(payload.get("info"), dict) else {}
    return (
        _parse_device_info_datetime(info.get("Dt Termino"))
        or _parse_device_info_datetime(info.get("Dt Inicio"))
        or _parse_device_info_datetime(payload.get("modified", ""))
    )


def _best_match_for_datetime(curve_dt, history):
    best_colada = ""
    best_delta = None
    for session in history:
        if not isinstance(session, dict):
            continue
        colada = str(session.get("colada", "") or "").strip()
        if not colada:
            continue
        start_dt = _parse_session_datetime(session.get("started_at"))
        if start_dt is None:
            continue
        end_dt = _parse_session_datetime(session.get("ended_at")) or datetime.now()
        if end_dt < start_dt:
            end_dt = start_dt
        if start_dt <= curve_dt <= end_dt:
            delta = timedelta(0)
        elif curve_dt < start_dt:
            delta = start_dt - curve_dt
        else:
            delta = curve_dt - end_dt
        if best_delta is None or delta < best_delta:
            best_delta = delta
            best_colada = colada
    return best_colada, best_delta


# ---------- parseo de archivos ----------

def _cell_text(value):
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%d/%m/%Y %H:%M:%S")
    if isinstance(value, float):
        return str(int(value)) if value.is_integer() else str(value)
    return str(value).strip()


def _parse_excel(path):
    import openpyxl
    wb = openpyxl.load_workbook(str(path), read_only=True, data_only=True)
    try:
        ws = wb.worksheets[0]
        rows_iter = ws.iter_rows(values_only=True)
        try:
            header_row = next(rows_iter)
        except StopIteration:
            return {}, []
        try:
            value_row = next(rows_iter)
        except StopIteration:
            value_row = ()
        raw_headers = [_cell_text(c).strip() for c in header_row]
        raw_values = [_cell_text(c).strip() for c in value_row]
        raw_info = {raw_headers[i]: raw_values[i] for i in range(min(len(raw_headers), len(raw_values))) if raw_headers[i]}
        info = _canonicalize_info(raw_info)

        series = []
        for r_idx, row in enumerate(rows_iter, start=3):
            if r_idx < 5:
                continue
            periodo = _parse_decimal(_cell_text(row[0]) if len(row) > 0 else None)
            temperatura = _parse_decimal(_cell_text(row[1]) if len(row) > 1 else None)
            derivada = _parse_decimal(_cell_text(row[2]) if len(row) > 2 else None)
            if periodo is None or temperatura is None or derivada is None:
                continue
            series.append({"periodo": periodo, "temperatura": temperatura, "derivada": derivada})
        return info, series
    finally:
        wb.close()


def _parse_csv(path):
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        sample = fh.read(2048)
        fh.seek(0)
        try:
            dialect = csv.Sniffer().sniff(sample, delimiters=";,")
        except Exception:
            dialect = csv.excel
            dialect.delimiter = ","
        reader = csv.reader(fh, dialect)
        rows = [row for row in reader]
    if len(rows) < 5:
        raise ValueError("El CSV no tiene el formato esperado.")

    raw_headers = [str(cell).strip() for cell in rows[0]]
    raw_values = [str(cell).strip() for cell in rows[1]] if len(rows) > 1 else []
    raw_info = {raw_headers[i]: raw_values[i] for i in range(min(len(raw_headers), len(raw_values))) if raw_headers[i]}
    info = _canonicalize_info(raw_info)

    series = []
    for row in rows[4:]:
        if len(row) < 3:
            continue
        periodo = _parse_decimal(row[0])
        temperatura = _parse_decimal(row[1])
        derivada = _parse_decimal(row[2])
        if periodo is None or temperatura is None or derivada is None:
            continue
        series.append({"periodo": periodo, "temperatura": temperatura, "derivada": derivada})
    return info, series


def _parse_file_plain(path):
    if path.suffix.lower() == ".csv":
        info, series = _parse_csv(path)
    else:
        info, series = _parse_excel(path)
    return {"info": info, "series": series}


# Cache en memoria del proceso, invalidada por mtime -- con chequeo de "el archivo cambio".
_PARSE_CACHE = {}


def _device_records_by_path():
    """Ya hay 1300+ registros REALES de dispositivo en la base compartida (bajados en su momento por la
    app de escritorio) -- su "payload" (info+series) ya viene armado y hay que usarlo tal cual, nunca
    intentar leerlo como si "path" fuera un archivo en disco (son URIs "device://IP/local/xxx", no rutas
    reales)."""
    out = {}
    for item in datos.load_thermal_device_records() or []:
        if not isinstance(item, dict):
            continue
        path = str(item.get("path", "") or "").strip()
        if path:
            out[path] = item
    return out


def _get_or_parse_payload(path_str, device_by_path=None):
    if device_by_path is None:
        device_by_path = _device_records_by_path()
    device_item = device_by_path.get(path_str)
    if device_item is not None:
        payload = device_item.get("payload")
        if not isinstance(payload, dict):
            return None
        series = payload.get("series")
        # Un puñado de registros viejos (de una version anterior del sync) tienen "series" como lista plana
        # de numeros en vez de {"periodo","temperatura","derivada"} -- no son usables, se descartan en vez
        # de romper.
        if not isinstance(series, list) or (series and not isinstance(series[0], dict)):
            return None
        clean = dict(payload)
        clean.setdefault("path", path_str)
        clean.setdefault("name", device_item.get("name", ""))
        return clean

    path = Path(path_str)
    try:
        mtime = path.stat().st_mtime
    except OSError:
        return None
    cached = _PARSE_CACHE.get(path_str)
    if cached is not None and cached[0] == mtime:
        return cached[1]
    try:
        payload = _parse_file_plain(path)
    except Exception:
        return None
    payload["path"] = path_str
    payload["name"] = path.name
    _PARSE_CACHE[path_str] = (mtime, payload)
    return payload


def _payload_mode_group(payload):
    info = payload.get("info", {}) if isinstance(payload, dict) else {}
    return _device_mode_group((info or {}).get("Modo", ""))


# ---------- resultados / metricas ----------

def _derive_tags_from_series(series, tl, tse, tre, tf):
    """tag1-4 (tiempo en segundos de TL/TSE/TRE/TF) llegan en 0 para TODO registro bajado por
    HistIndex.dat/dadoshist.cgi -- el protocolo HTTP de descarga del equipo no los expone, a diferencia del
    Excel exportado a mano. Se derivan de la curva temperatura-tiempo que el equipo SI manda completa: el
    tiempo en que la temperatura cruza cada punto ya conocido (TL/TSE/TRE/TF), buscando siempre hacia
    adelante desde el cruce anterior y en el mismo orden físico en que ocurren -- TL bajando, TSE como
    mínimo local antes de la recalescencia, TRE como máximo local de la recalescencia, TF bajando de nuevo.
    Devuelve (tag1, tag2, tag3, tag4), cada uno None si falta el punto de partida o la curva nunca llega a
    ese nivel."""
    if not series:
        return None, None, None, None

    def cross(start_idx, target, rising):
        if target is None or start_idx is None:
            return None
        if not rising:
            for i in range(start_idx, len(series)):
                if series[i]["temperatura"] <= target:
                    return i
            return None
        # TRE es un máximo local (fin de la recalescencia) -- la curva real, redondeada a 0.1 C, a veces se
        # queda unas décimas por debajo del TRE que informa el equipo (calculado sobre datos sin redondear)
        # y nunca cruza el umbral exacto. Ante eso se usa el máximo real alcanzado en el tramo como mejor
        # aproximación, en vez de devolver None y perder tag3/tag4 por una diferencia de décimas.
        best_idx, best_val = start_idx, series[start_idx]["temperatura"]
        for i in range(start_idx, len(series)):
            temp = series[i]["temperatura"]
            if temp >= target:
                return i
            if temp > best_val:
                best_val, best_idx = temp, i
        return best_idx

    idx_tl = cross(0, tl, rising=False)
    idx_tse = cross(idx_tl, tse, rising=False) if idx_tl is not None else None
    idx_tre = cross(idx_tse, tre, rising=True) if idx_tse is not None else None
    idx_tf = cross(idx_tre, tf, rising=False) if idx_tre is not None else None

    def periodo_at(idx):
        return series[idx]["periodo"] if idx is not None else None

    return periodo_at(idx_tl), periodo_at(idx_tse), periodo_at(idx_tre), periodo_at(idx_tf)


def _result_metrics(info, series=None):
    tl = _parse_decimal(_info_alias_value(info, "TL"))
    tse = _parse_decimal(_info_alias_value(info, "TSE", "TS"))
    tre = _parse_decimal(_info_alias_value(info, "TRE"))
    rec = _parse_decimal(_info_alias_value(info, "REC"))
    tf = _parse_decimal(_info_alias_value(info, "TF"))
    tag1 = _parse_decimal(_info_alias_value(info, "tag1", "tag1 / TL (s)"))
    tag2 = _parse_decimal(_info_alias_value(info, "tag2", "tag2 / TSE (s)"))
    tag3 = _parse_decimal(_info_alias_value(info, "tag3", "tag3 / TRE (s)"))
    tag4 = _parse_decimal(_info_alias_value(info, "tag4", "tag4 / TF (s)"))
    tags_derived = False
    if series and (tag1 is None or tag2 is None or tag3 is None or tag4 is None):
        d1, d2, d3, d4 = _derive_tags_from_series(series, tl, tse, tre, tf)
        if tag1 is None and d1 is not None:
            tag1, tags_derived = d1, True
        if tag2 is None and d2 is not None:
            tag2, tags_derived = d2, True
        if tag3 is None and d3 is not None:
            tag3, tags_derived = d3, True
        if tag4 is None and d4 is not None:
            tag4, tags_derived = d4, True
    if rec is None and tre is not None and tse is not None:
        rec = tre - tse
    solid_interval = (tl - tse) if tl is not None and tse is not None else None
    solid_interval_time = (tag2 - tag1) if tag1 is not None and tag2 is not None else None
    gray_expansion = None
    nodular_expansion = None
    if tag1 is not None and tag2 is not None and tag4 is not None and tag4 != tag1:
        gray_expansion = (tag4 - tag2) / (tag4 - tag1)
    if tag1 is not None and tag3 is not None and tag4 is not None and tag4 != tag1:
        nodular_expansion = (tag4 - tag3) / (tag4 - tag1)
    return {
        "tl": tl, "tse": tse, "tre": tre, "rec": rec, "tf": tf,
        "tag1": tag1, "tag2": tag2, "tag3": tag3, "tag4": tag4,
        "tags_derived": tags_derived,
        "solid_interval": solid_interval, "solid_interval_time": solid_interval_time,
        "gray_expansion": gray_expansion, "nodular_expansion": nodular_expansion,
    }


def _compute_vps(series, tag4_time, n_points=15):
    import math
    if not series or tag4_time is None:
        return None
    idx = min(range(len(series)), key=lambda i: abs(series[i]["periodo"] - tag4_time))

    def slope(pts):
        xs = [p["periodo"] for p in pts]
        ys = [p["derivada"] for p in pts]
        n = len(xs)
        if n < 2:
            return None
        sx, sy = sum(xs), sum(ys)
        sxy = sum(x * y for x, y in zip(xs, ys))
        sx2 = sum(x * x for x in xs)
        d = n * sx2 - sx * sx
        if abs(d) < 1e-12:
            return None
        return (n * sxy - sx * sy) / d

    m1 = slope(series[max(0, idx - n_points): idx + 1])
    m2 = slope(series[idx: min(len(series), idx + n_points + 1)])
    if m1 is None or m2 is None:
        return None
    denom = 1.0 + m1 * m2
    if abs(denom) < 1e-10:
        return 90.0
    return abs(math.degrees(math.atan((m2 - m1) / denom)))


def _fmt_or_nd(value, suffix=""):
    return "N/D" if value is None else f"{value:.2f}{suffix}"


def _fmt_tag_time_or_nd(tag_value, temp_value):
    """"N/D" a secas no distingue entre "el equipo nunca detectó este punto" y "lo detectó (la temperatura
    ya está en la métrica del equipo) pero ocurrió después de que la curva dejó de grabarse" -- el equipo
    tiene una duración máxima de grabación de la curva detallada y a veces TSE/TRE/TF de un ensayo caen
    después de ese corte, aunque el equipo los siga reportando como métrica resumen. El segundo caso es
    normal (no un bug de la app) y conviene decirlo explícito en vez de un "N/D" ambiguo."""
    if tag_value is not None:
        return f"{tag_value:.2f} s"
    if temp_value is not None:
        return "N/D (detectado, pero después de que terminó de grabarse la curva)"
    return "N/D"


def _fmt_pct_or_nd(value):
    return "N/D" if value is None else f"{value * 100.0:.2f}%"


def _range_status(value, minimum=None, maximum=None):
    if value is None:
        return "N/D"
    if minimum is not None and value < minimum:
        return f"Bajo ({value:.2f})"
    if maximum is not None and value > maximum:
        return f"Alto ({value:.2f})"
    return f"OK ({value:.2f})"


def _ratio_status(value, minimum):
    if value is None:
        return "N/D"
    pct = value * 100.0
    return f"OK ({pct:.2f}%)" if value >= minimum else f"Bajo ({pct:.2f}%)"


def _build_carbon_results_text(info, series):
    tl = _parse_decimal(_info_alias_value(info, "TL"))
    ts = _parse_decimal(_info_alias_value(info, "TS", "TSE"))
    tf = _parse_decimal(_info_alias_value(info, "TF"))
    ce = _parse_decimal(_info_alias_value(info, "CE %"))
    c_pct = _parse_decimal(_info_alias_value(info, "C %", "Carbono %"))
    si_pct = _parse_decimal(_info_alias_value(info, "Si %", "Silicio %"))
    tag1 = _parse_decimal(_info_alias_value(info, "tag1", "tag1 / TL (s)"))
    tag2 = _parse_decimal(_info_alias_value(info, "tag2", "tag2 / TSE (s)"))
    solid_interval = (tl - ts) if tl is not None and ts is not None else None
    solid_interval_time = (tag2 - tag1) if tag1 is not None and tag2 is not None else None
    lines = [
        "Resumen calculado (Carbono)", "",
        "Temperaturas",
        f"- TL: {_fmt_or_nd(tl, ' C')}",
        f"- TS (solidus): {_fmt_or_nd(ts, ' C')}",
        f"- TF: {_fmt_or_nd(tf, ' C')}", "",
        "Composicion",
        f"- CE: {_fmt_or_nd(ce, ' %')}",
        f"- C: {_fmt_or_nd(c_pct, ' %')}",
        f"- Si: {_fmt_or_nd(si_pct, ' %')}", "",
        "Tiempos (segundos)",
        f"- Tiempo TL / tag1: {_fmt_tag_time_or_nd(tag1, tl)}",
        f"- Tiempo TS / tag2: {_fmt_tag_time_or_nd(tag2, ts)}", "",
        "Indicadores calculados",
        f"Intervalo de solidificacion (TL - TS): {_fmt_or_nd(solid_interval, ' C')} "
        f"| tiempo: {_fmt_or_nd(solid_interval_time, ' s')}",
        f"Puntos de curva: {len(series)}",
    ]
    return "\n".join(lines).strip()


def _build_results_text(info, series):
    if _device_mode_group(info.get("Modo", "")) == "Carbono":
        return _build_carbon_results_text(info, series)
    metrics = _result_metrics(info, series)
    lines = [
        "Resumen calculado", "",
        "Temperaturas",
        f"- TL: {_fmt_or_nd(metrics['tl'], ' C')}",
        f"- TSE: {_fmt_or_nd(metrics['tse'], ' C')}",
        f"- TRE: {_fmt_or_nd(metrics['tre'], ' C')}",
        f"- REC: {_fmt_or_nd(metrics['rec'], ' C')}",
        f"- TF: {_fmt_or_nd(metrics['tf'], ' C')}", "",
        "Tiempos (segundos)",
        f"- Tiempo TL / tag1: {_fmt_tag_time_or_nd(metrics['tag1'], metrics['tl'])}",
        f"- Tiempo TSE / tag2: {_fmt_tag_time_or_nd(metrics['tag2'], metrics['tse'])}",
        f"- Tiempo TRE / tag3: {_fmt_tag_time_or_nd(metrics['tag3'], metrics['tre'])}",
        f"- Tiempo TF / tag4: {_fmt_tag_time_or_nd(metrics['tag4'], metrics['tf'])}", "",
        "Indicadores calculados",
        f"Intervalo de solidificacion (TL - TSE): {_fmt_or_nd(metrics['solid_interval'], ' C')} "
        f"| tiempo: {_fmt_or_nd(metrics['solid_interval_time'], ' s')}",
        f"Puntos de curva: {len(series)}",
        f"Expansion gris por tiempo ((tag4-tag2)/(tag4-tag1)): {_fmt_pct_or_nd(metrics['gray_expansion'])}",
        f"Expansion nodular por tiempo ((tag4-tag3)/(tag4-tag1)): {_fmt_pct_or_nd(metrics['nodular_expansion'])}",
        f"VPS — angulo entre tramos de derivada en TF: {_fmt_or_nd(_compute_vps(series, metrics['tag4']), '°')}",
        "", THERMAL_RESULTS_NOTE, "",
        "Hierro fundido gris",
        f"- TSE recomendado en horno y cuchara: > 1140 C. Estado: {_range_status(metrics['tse'], 1140.0, None)}",
        f"- REC recomendado en cuchara: 4 a 7 C. Estado: {_range_status(metrics['rec'], 4.0, 7.0)}",
        f"- Expansion grafitica final recomendada: > 60%. Estado: {_ratio_status(metrics['gray_expansion'], 0.60)}",
        "- El intervalo de solidificacion grande (TL - TSE) empeora la alimentacion y puede favorecer rechupes.", "",
        "Hierro fundido nodular",
        f"- TSE recomendado en horno y cuchara: > 1140 C. Estado: {_range_status(metrics['tse'], 1140.0, None)}",
        f"- REC recomendado en cuchara: 1 a 4 C. Estado: {_range_status(metrics['rec'], 1.0, 4.0)}",
        f"- Expansion grafitica final recomendada: > 70%. Estado: {_ratio_status(metrics['nodular_expansion'], 0.70)}",
        "- En nodular, la expansion final esperada debe ser mayor que en gris.",
    ]
    return "\n".join(lines).strip()


def _chart_series_arrays(series):
    total = len(series or [])
    if total <= THERMAL_CHART_MAX_POINTS_PER_CURVE:
        sampled = series or []
    else:
        step = max(1, total // THERMAL_CHART_MAX_POINTS_PER_CURVE)
        sampled = list(series[::step])
        last = series[-1]
        if sampled and sampled[-1] is not last:
            sampled.append(last)
    return {
        "periodos": [p["periodo"] for p in sampled],
        "temperaturas": [p["temperatura"] for p in sampled],
        "derivadas": [p["derivada"] for p in sampled],
    }


# ---------- vinculo con Historicos ----------

def _active_session_pseudo():
    """La sesion activa de Ajuste (colada en curso, todavia sin guardar en Historicos) representada como
    un item mas de "historial" -- sin esto, ninguna curva nueva puede vincularse a la colada actual hasta
    que el operario apriete "Guardar sesión". Devuelve None si no hay colada/sesion en curso. "ended_at":
    None hace que _best_match_for_datetime la trate como abierta hasta "ahora"."""
    st = datos.load_ajuste_session()
    colada = str(st.get("colada", "") or "").strip()
    started_at = st.get("session_started_at")
    if not colada or not started_at:
        return None
    return {
        "colada": colada,
        "started_at": started_at,
        "ended_at": None,
        "thermal_analysis": list(st.get("thermal_analysis") or []),
    }


def _history_with_active(history=None):
    """history + la sesion activa (si hay una en curso), para pasarle a _build_history_link_map/
    _best_match_for_datetime sin que les importe si un item es una sesion real de Historicos o la colada
    actual."""
    if history is None:
        history = datos.load_history()
    active = _active_session_pseudo()
    return list(history) + [active] if active else list(history)


def _build_history_link_map(history):
    links = {}
    for session in history:
        if not isinstance(session, dict):
            continue
        colada = str(session.get("colada", "") or "").strip()
        if not colada:
            continue
        analyses = session.get("thermal_analysis", [])
        if not isinstance(analyses, list):
            continue
        for entry in analyses:
            if not isinstance(entry, dict):
                continue
            source_file = str(entry.get("source_file", "") or "").strip()
            if not source_file:
                continue
            entry_info = entry.get("info", {}) if isinstance(entry.get("info"), dict) else {}
            mode_group = _device_mode_group(entry_info.get("Modo", ""))
            if mode_group == "Carbono":
                orden = entry.get("orden")
                etapa_display = f"#{int(orden)}" if isinstance(orden, (int, float)) else "(sin orden)"
            else:
                etapa = str(entry.get("etapa_muestra", "") or "").strip()
                etapa_display = etapa if etapa else "(pendiente)"
            info = links.setdefault(source_file, {"coladas": [], "etapas": [], "auto_linked": False})
            if colada not in info["coladas"]:
                info["coladas"].append(colada)
            if etapa_display not in info["etapas"]:
                info["etapas"].append(etapa_display)
            if entry.get("auto_linked"):
                info["auto_linked"] = True
    return links


def _thermal_needs_review(path, link_info, history, device_by_path=None):
    if link_info is not None:
        return False
    payload = _get_or_parse_payload(path, device_by_path)
    if payload is None:
        return False
    mode_group = _payload_mode_group(payload)
    if mode_group not in ("Carbono", "Microestructura"):
        return False
    curve_dt = _payload_datetime(payload)
    if curve_dt is None:
        return True
    colada, delta = _best_match_for_datetime(curve_dt, history)
    if not colada or delta is None or delta > THERMAL_MATCH_MAX_DELTA:
        return True
    return False


def _scan_files():
    items = []
    if not THERMAL_ANALYSIS_DIR.exists():
        return items
    for path in sorted(THERMAL_ANALYSIS_DIR.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
        if not path.is_file() or path.name.startswith("~$") or path.suffix.lower() not in THERMAL_EXTENSIONS:
            continue
        items.append({
            "name": path.name,
            "path": str(path),
            "modified": datetime.fromtimestamp(path.stat().st_mtime).strftime("%d/%m/%Y %H:%M"),
            "source": "file",
        })
    return items


def _record_sort_datetime(item):
    """Fecha para ordenar la lista (más nuevo primero): usa "modified" tal cual quedó armado en
    _scan_files/_filtered_device_records -- para archivos de carpeta es el mtime real, para registros de
    dispositivo es Dt Termino/Dt Inicio ya formateado. Los que no se puedan parsear quedan al final."""
    return _parse_device_info_datetime(item.get("modified", "")) or datetime.min


def _filtered_device_records(mode):
    records = datos.load_thermal_device_records()
    out = []
    for item in records or []:
        if not isinstance(item, dict):
            continue
        payload = item.get("payload", {}) if isinstance(item.get("payload"), dict) else {}
        info = payload.get("info", {}) if isinstance(payload, dict) else {}
        mode_group = str(item.get("mode_group", "") or _device_mode_group(info.get("Modo", ""))).strip()
        if mode != "Todos" and mode_group != mode:
            continue
        out.append({
            "name": item.get("name", ""),
            "path": str(item.get("path", "") or ""),
            "modified": item.get("modified", ""),
            "source": "device",
            "ip": str(info.get("IP", "") or ""),
        })
    return sorted(out, key=_record_sort_datetime, reverse=True)


def _etapa_muestra_options():
    momentos = datos.load_inoc_momentos()
    labels = [str(m.get("label", "") or "").strip() for m in momentos if isinstance(m, dict)]
    return [label for label in labels if label]


def _build_history_analysis(payload, colada, material_base, observacion="", etapa="", orden=None, auto_linked=False):
    info = dict(payload.get("info", {}) or {})
    series = list(payload.get("series", []) or [])
    entry = {
        "attached_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "colada": str(colada or "").strip(),
        "material_base": str(material_base or "").strip(),
        "observacion": str(observacion or "").strip(),
        "etapa_muestra": str(etapa or "").strip(),
        "source_file": str(payload.get("path", "") or "").strip(),
        "source_name": str(payload.get("name", "") or "").strip(),
        "info": info,
        "series": series,
        "point_count": len(series),
        "result_metrics": _result_metrics(info, series),
        "result_text": _build_results_text(info, series),
        "auto_linked": bool(auto_linked),
    }
    if orden is not None:
        entry["orden"] = orden
    return entry


# ---------- endpoints ----------

@router.get("/records")
def list_records(mode: str = Query("Microestructura"), _: dict = Depends(devices.require_approved_device)):
    if mode not in THERMAL_MODE_OPTIONS:
        mode = "Microestructura"
    history = _history_with_active()
    link_map = _build_history_link_map(history)
    device_by_path = _device_records_by_path()

    # Los archivos de carpeta se listan SIEMPRE completos; solo el cache de dispositivo se filtra por el
    # combo, porque ese sí trae su mode_group ya resuelto sin necesidad de parsear nada. Se reordena la
    # lista combinada por fecha (más nuevo primero) en vez de solo concatenar "archivos primero, dispositivo
    # después" -- con las dos fuentes mezcladas, orden por fecha real es lo que efectivamente importa.
    records = sorted(_scan_files() + _filtered_device_records(mode), key=_record_sort_datetime, reverse=True)

    seen = set()
    out = []
    for item in records:
        path = item["path"]
        if path in seen:
            continue
        seen.add(path)
        link_info = link_map.get(path)
        colada_display = ", ".join(link_info["coladas"]) if link_info else ""
        etapa_display = ", ".join(link_info["etapas"]) if link_info else ""
        auto_linked = bool(link_info and link_info["auto_linked"])
        needs_review = _thermal_needs_review(path, link_info, history, device_by_path)
        out.append({
            "name": item["name"],
            "path": path,
            "modified": item["modified"],
            "source": item["source"],
            "ip": item.get("ip", ""),
            "colada_display": colada_display,
            "etapa_display": etapa_display,
            "auto_linked": auto_linked,
            "needs_review": needs_review,
        })
    return {
        "records": out,
        "folder": str(THERMAL_ANALYSIS_DIR),
        "folder_exists": THERMAL_ANALYSIS_DIR.exists(),
    }


@router.get("/curve")
def get_curve(path: list[str] = Query(...), _: dict = Depends(devices.require_approved_device)):
    history = _history_with_active()
    link_map = _build_history_link_map(history)
    device_by_path = _device_records_by_path()
    out = []
    for p in path:
        payload = _get_or_parse_payload(p, device_by_path)
        if payload is None:
            raise HTTPException(status_code=404, detail={"error": "no_se_pudo_leer", "path": p})
        info = payload.get("info", {}) or {}
        series = payload.get("series", []) or []
        mode_group = _device_mode_group(info.get("Modo", ""))
        row_order = THERMAL_INFO_CARBON_V2 if mode_group == "Carbono" else THERMAL_INFO_MICRO_V2
        info_rows = [
            {"campo": display, "valor": _pick_info_value(info, THERMAL_FIELD_ALIASES_V2.get(display, (display,)))}
            for display in row_order
            if _pick_info_value(info, THERMAL_FIELD_ALIASES_V2.get(display, (display,)))
        ]
        metrics = _result_metrics(info, series)
        vps = _compute_vps(series, metrics["tag4"]) if mode_group == "Microestructura" else None
        curve_dt = _payload_datetime(payload)
        suggested_colada, _delta = _best_match_for_datetime(curve_dt, history) if curve_dt else ("", None)
        link_info = link_map.get(p)
        out.append({
            "path": p,
            "name": payload.get("name", ""),
            "mode_group": mode_group,
            "info_rows": info_rows,
            "chart": _chart_series_arrays(series),
            "point_count": len(series),
            "metrics": metrics,
            "vps": vps,
            "result_text": _build_results_text(info, series),
            "suggested_colada": suggested_colada,
            "suggested_material_base": str(info.get("Material", "") or "").strip(),
            "linked": {
                "coladas": link_info["coladas"] if link_info else [],
                "etapas": link_info["etapas"] if link_info else [],
                "auto_linked": bool(link_info and link_info["auto_linked"]),
            },
        })
    return {"curves": out}


@router.get("/carbon-tse-options")
def carbon_tse_options(path: str = Query(...), _: dict = Depends(devices.require_approved_device)):
    """Dado el path de una curva de Microestructura ya vinculada, busca los TS/TL de Carbono vinculados a
    la(s) misma(s) colada(s), para overlayear como líneas de referencia."""
    history = datos.load_history()
    link_map = _build_history_link_map(history)
    link_info = link_map.get(path)
    coladas = link_info["coladas"] if link_info else []
    if not coladas:
        return {"options": []}
    sessions_by_colada = {
        str(s.get("colada", "") or "").strip(): s for s in history if isinstance(s, dict)
    }
    options = []
    for colada in coladas:
        session = sessions_by_colada.get(colada)
        if not isinstance(session, dict):
            continue
        for entry in session.get("thermal_analysis", []) or []:
            if not isinstance(entry, dict):
                continue
            entry_info = entry.get("info", {}) if isinstance(entry.get("info"), dict) else {}
            if _device_mode_group(entry_info.get("Modo", "")) != "Carbono":
                continue
            ts = _parse_decimal(_info_alias_value(entry_info, "TS", "TSE"))
            if ts is None:
                continue
            tl = _parse_decimal(_info_alias_value(entry_info, "TL"))
            orden = entry.get("orden")
            orden_label = f"#{int(orden)}" if isinstance(orden, (int, float)) else "(sin orden)"
            source_name = str(entry.get("source_name", "") or "").strip()
            tl_text = f"{tl:.1f}" if tl is not None else "N/D"
            label = f"{colada} - {orden_label} - {source_name} - TS {ts:.1f} - TL {tl_text}"
            options.append({"label": label, "ts": ts, "tl": tl})
    return {"options": options}


@router.post("/compare")
def compare_curves(payload: dict = Body(...), _: dict = Depends(devices.require_approved_device)):
    paths = [str(p or "").strip() for p in (payload.get("paths") or []) if str(p or "").strip()]
    if len(paths) < 2:
        raise HTTPException(status_code=400, detail={"error": "se_necesitan_2_o_mas_curvas"})
    device_by_path = _device_records_by_path()
    payloads = []
    for p in paths:
        item = _get_or_parse_payload(p, device_by_path)
        if item is None:
            raise HTTPException(status_code=404, detail={"error": "no_se_pudo_leer", "path": p})
        payloads.append(item)

    metrics_per_curve = [_result_metrics(pl.get("info", {}), pl.get("series", [])) for pl in payloads]

    def fmt_n(v, suffix=""):
        return "N/D" if v is None else f"{v:.2f}{suffix}"

    row_defs = [
        ("TL", lambda m, pl: fmt_n(m["tl"], " C")),
        ("TSE", lambda m, pl: fmt_n(m["tse"], " C")),
        ("TRE", lambda m, pl: fmt_n(m["tre"], " C")),
        ("REC", lambda m, pl: fmt_n(m["rec"], " C")),
        ("TF", lambda m, pl: fmt_n(m["tf"], " C")),
        ("Tiempo TL / tag1", lambda m, pl: fmt_n(m["tag1"], " s")),
        ("Tiempo TSE / tag2", lambda m, pl: fmt_n(m["tag2"], " s")),
        ("Tiempo TRE / tag3", lambda m, pl: fmt_n(m["tag3"], " s")),
        ("Tiempo TF / tag4", lambda m, pl: fmt_n(m["tag4"], " s")),
        ("Intervalo de solidificacion (TL - TSE)", lambda m, pl: fmt_n(m["solid_interval"], " C")),
        ("Intervalo de solidificacion (tiempo)", lambda m, pl: fmt_n(m["solid_interval_time"], " s")),
        ("Expansion gris", lambda m, pl: _fmt_pct_or_nd(m["gray_expansion"])),
        ("Expansion nodular", lambda m, pl: _fmt_pct_or_nd(m["nodular_expansion"])),
        ("VPS (°)", lambda m, pl: fmt_n(_compute_vps(pl.get("series", []), m["tag4"]), "°")),
        ("Puntos", lambda m, pl: str(len(pl.get("series", [])))),
    ]
    columns = [Path(str(pl.get("name", "") or f"Curva {i + 1}")).stem for i, pl in enumerate(payloads)]
    rows = [
        {"metrica": label, "valores": [fn(m, pl) for m, pl in zip(metrics_per_curve, payloads)]}
        for label, fn in row_defs
    ]

    text = None
    if len(payloads) == 2:
        m1, m2 = metrics_per_curve[0], metrics_per_curve[1]
        pl1, pl2 = payloads[0], payloads[1]

        def compare_line(label, a, b, suffix):
            if a is None and b is None:
                return f"{label}: N/D"
            if a is None or b is None:
                return f"{label}: A={fmt_n(a, suffix)} | B={fmt_n(b, suffix)} | Delta=N/D"
            return f"{label}: A={fmt_n(a, suffix)} | B={fmt_n(b, suffix)} | Delta={b - a:.2f}{suffix}"

        vps1 = _compute_vps(pl1.get("series", []), m1["tag4"])
        vps2 = _compute_vps(pl2.get("series", []), m2["tag4"])
        ge1 = m1["gray_expansion"] * 100.0 if m1["gray_expansion"] is not None else None
        ge2 = m2["gray_expansion"] * 100.0 if m2["gray_expansion"] is not None else None
        ne1 = m1["nodular_expansion"] * 100.0 if m1["nodular_expansion"] is not None else None
        ne2 = m2["nodular_expansion"] * 100.0 if m2["nodular_expansion"] is not None else None
        lines = [
            f"A: {pl1.get('name', '')}", f"B: {pl2.get('name', '')}", "",
            compare_line("TL", m1["tl"], m2["tl"], " C"),
            compare_line("TSE", m1["tse"], m2["tse"], " C"),
            compare_line("TRE", m1["tre"], m2["tre"], " C"),
            compare_line("REC", m1["rec"], m2["rec"], " C"),
            compare_line("TF", m1["tf"], m2["tf"], " C"),
            compare_line("Intervalo de solidificacion (TL - TSE)", m1["solid_interval"], m2["solid_interval"], " C"),
            compare_line("Intervalo de solidificacion (tiempo)", m1["solid_interval_time"], m2["solid_interval_time"], " s"),
            compare_line("Expansion gris", ge1, ge2, "%"),
            compare_line("Expansion nodular", ne1, ne2, "%"),
            compare_line("VPS", vps1, vps2, "°"),
            compare_line("Puntos", float(len(pl1.get("series", []))), float(len(pl2.get("series", []))), ""),
            "",
            f"Estado gris A: TSE {_range_status(m1['tse'], 1140.0, None)} | REC {_range_status(m1['rec'], 4.0, 7.0)} | Expansion {_ratio_status(m1['gray_expansion'], 0.60)}",
            f"Estado gris B: TSE {_range_status(m2['tse'], 1140.0, None)} | REC {_range_status(m2['rec'], 4.0, 7.0)} | Expansion {_ratio_status(m2['gray_expansion'], 0.60)}",
            f"Estado nodular A: TSE {_range_status(m1['tse'], 1140.0, None)} | REC {_range_status(m1['rec'], 1.0, 4.0)} | Expansion {_ratio_status(m1['nodular_expansion'], 0.70)}",
            f"Estado nodular B: TSE {_range_status(m2['tse'], 1140.0, None)} | REC {_range_status(m2['rec'], 1.0, 4.0)} | Expansion {_ratio_status(m2['nodular_expansion'], 0.70)}",
        ]
        text = "\n".join(lines).strip()

    return {"columns": columns, "rows": rows, "text": text}


@router.get("/etapas")
def get_etapas(_: dict = Depends(devices.require_approved_device)):
    return {"etapas": _etapa_muestra_options()}


@router.get("/coladas")
def get_coladas(_: dict = Depends(devices.require_approved_device)):
    history = datos.load_history()
    coladas = [str(s.get("colada", "") or "").strip() for s in history if isinstance(s, dict) and str(s.get("colada", "") or "").strip()]
    coladas = list(dict.fromkeys(reversed(coladas)))
    active = _active_session_pseudo()
    if active and active["colada"] not in coladas:
        coladas.insert(0, active["colada"])
    return {"coladas": coladas}


@router.get("/link")
def get_link(path: str = Query(...), _: dict = Depends(devices.require_approved_device)):
    history = _history_with_active()
    entries = []
    for session in history:
        if not isinstance(session, dict):
            continue
        colada = str(session.get("colada", "") or "").strip()
        if not colada:
            continue
        for entry in session.get("thermal_analysis", []) or []:
            if isinstance(entry, dict) and str(entry.get("source_file", "") or "").strip() == path:
                entry_info = entry.get("info", {}) if isinstance(entry.get("info"), dict) else {}
                entries.append({
                    "colada": colada,
                    "mode_group": _device_mode_group(entry_info.get("Modo", "")),
                    "observacion": entry.get("observacion", ""),
                    "orden": entry.get("orden"),
                    "etapa_muestra": entry.get("etapa_muestra", ""),
                })
    return {"entries": entries}


@router.patch("/link")
def patch_link(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    colada = str(payload.get("colada") or "").strip()
    source_file = str(payload.get("source_file") or "").strip()
    patch = payload.get("patch") or {}
    if not colada or not source_file:
        raise HTTPException(status_code=400, detail={"error": "colada_y_source_file_requeridos"})
    try:
        updated = _set_thermal_analysis_field_smart(colada, source_file, patch)
    except ValueError as ex:
        raise HTTPException(status_code=404, detail={"error": str(ex)})
    if not updated:
        raise HTTPException(status_code=404, detail={"error": "vinculo_no_encontrado"})
    return {"ok": True}


@router.post("/attach")
def attach_to_history(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    paths = [str(p or "").strip() for p in (payload.get("paths") or []) if str(p or "").strip()]
    colada = str(payload.get("colada") or "").strip()
    material_base = str(payload.get("material_base") or "").strip()
    observations = payload.get("observations") or {}
    etapas = payload.get("etapas") or {}
    if not paths:
        raise HTTPException(status_code=400, detail={"error": "sin_curvas"})
    if not colada:
        raise HTTPException(status_code=400, detail={"error": "colada_requerida"})

    device_by_path = _device_records_by_path()
    attached = 0
    for p in paths:
        payload_obj = _get_or_parse_payload(p, device_by_path)
        if payload_obj is None:
            raise HTTPException(status_code=404, detail={"error": "no_se_pudo_leer", "path": p})
        observation = str(observations.get(p, "") or "").strip()
        etapa = str(etapas.get(p, "") or "").strip()
        try:
            _attach_thermal_analysis_smart(
                colada, _build_history_analysis(payload_obj, colada, material_base, observation, etapa),
            )
        except ValueError as ex:
            raise HTTPException(status_code=404, detail={"error": str(ex)})
        attached += 1
    return {"ok": True, "attached": attached, "colada": colada}


def _run_auto_link(mode_group, history=None):
    """Lógica compartida por POST /auto-link (botón manual) y por el post-proceso de POST /download (auto-
    vincula Carbono y Microestructura después de cada descarga exitosa). Incluye la colada activa (todavía
    sin guardar en Históricos) como destino posible -- ver _history_with_active."""
    if history is None:
        history = datos.load_history()
    pool = _history_with_active(history)
    if not pool:
        return {"attached": 0, "unmatched": 0, "errors": [], "message": "No hay coladas guardadas ni sesión activa para vincular."}

    link_map = _build_history_link_map(pool)
    device_by_path = _device_records_by_path()
    all_records = _scan_files() + _filtered_device_records("Todos")
    seen_paths = set()
    candidates = []
    for item in all_records:
        path = item["path"]
        if not path or path in seen_paths:
            continue
        seen_paths.add(path)
        if path in link_map:
            continue
        payload = _get_or_parse_payload(path, device_by_path)
        if payload is None:
            continue
        if _payload_mode_group(payload) != mode_group:
            continue
        candidates.append((path, payload))

    if not candidates:
        return {"attached": 0, "unmatched": 0, "errors": [], "message": f"No hay curvas de {mode_group} sin vincular."}

    matched_by_colada = {}
    unmatched = 0
    for path, payload in candidates:
        curve_dt = _payload_datetime(payload)
        if curve_dt is None:
            unmatched += 1
            continue
        colada, delta = _best_match_for_datetime(curve_dt, pool)
        if not colada or delta is None or delta > THERMAL_MATCH_MAX_DELTA:
            unmatched += 1
            continue
        matched_by_colada.setdefault(colada, []).append((path, payload, curve_dt))

    attached = 0
    errors = []
    for colada, items in matched_by_colada.items():
        try:
            if mode_group == "Carbono":
                attached += _attach_carbon_group(colada, items, pool)
            else:
                attached += _attach_microstructure_group(colada, items)
        except Exception as ex:
            errors.append(f"{colada}: {ex}")

    return {
        "attached": attached, "unmatched": unmatched, "errors": errors,
        "message": f"{attached} curva(s) de {mode_group} vinculada(s). "
                   f"{unmatched} sin coincidencia de horario (marcadas para revisar).",
    }


@router.post("/auto-link")
def auto_link(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    mode_group = str(payload.get("mode_group") or "").strip()
    if mode_group not in ("Carbono", "Microestructura"):
        raise HTTPException(status_code=400, detail={"error": "mode_group_invalido"})
    return _run_auto_link(mode_group)


def _attach_thermal_analysis_smart(colada, analysis_obj):
    """Como datos.attach_thermal_analysis, pero si "colada" es la sesión de Ajuste activa (todavía sin
    guardar en Históricos), escribe en session["thermal_analysis"] de esa sesión en vez de buscar una fila
    ya guardada -- datos.attach_thermal_analysis busca SOLO en sesiones ya guardadas y tira ValueError si no
    encuentra ninguna."""
    active = _active_session_pseudo()
    if active and datos.normalize_colada_key(colada) == datos.normalize_colada_key(active["colada"]):
        st = datos.load_ajuste_session()
        analyses = list(st.get("thermal_analysis") or [])
        analyses.append(analysis_obj)
        st["thermal_analysis"] = analyses
        datos.save_ajuste_session(st)
        return
    datos.attach_thermal_analysis(colada, analysis_obj)


def _set_thermal_analysis_field_smart(colada, source_file, patch):
    """Versión de datos.set_thermal_analysis_field consciente de la sesión activa, mismo criterio que
    _attach_thermal_analysis_smart."""
    active = _active_session_pseudo()
    if active and datos.normalize_colada_key(colada) == datos.normalize_colada_key(active["colada"]):
        st = datos.load_ajuste_session()
        analyses = list(st.get("thermal_analysis") or [])
        updated = False
        for entry in analyses:
            if isinstance(entry, dict) and str(entry.get("source_file", "") or "").strip() == source_file:
                entry.update(patch)
                updated = True
        if updated:
            st["thermal_analysis"] = analyses
            datos.save_ajuste_session(st)
        return updated
    return datos.set_thermal_analysis_field(colada, source_file, patch)


def _attach_carbon_group(colada, items, history):
    session = next(
        (s for s in history if isinstance(s, dict) and str(s.get("colada", "") or "").strip() == colada), None,
    )
    existing = []
    if isinstance(session, dict):
        for entry in session.get("thermal_analysis", []) or []:
            if not isinstance(entry, dict):
                continue
            entry_info = entry.get("info", {}) if isinstance(entry.get("info"), dict) else {}
            if _device_mode_group(entry_info.get("Modo", "")) != "Carbono":
                continue
            source_file = str(entry.get("source_file", "") or "").strip()
            if not source_file:
                continue
            entry_dt = (
                _parse_device_info_datetime(entry_info.get("Dt Termino"))
                or _parse_device_info_datetime(entry_info.get("Dt Inicio"))
            )
            existing.append({"source_file": source_file, "dt": entry_dt or datetime.min, "orden": entry.get("orden")})

    combined = existing + [
        {"path": path, "payload": payload, "dt": curve_dt or datetime.min} for path, payload, curve_dt in items
    ]
    combined.sort(key=lambda x: x["dt"])

    attached = 0
    for order_idx, entry in enumerate(combined, start=1):
        if "payload" in entry:
            payload = entry["payload"]
            material_base = str((payload.get("info", {}) or {}).get("Material", "") or "").strip()
            analysis = _build_history_analysis(
                payload, colada, material_base, observacion="", etapa="", orden=order_idx, auto_linked=True,
            )
            _attach_thermal_analysis_smart(colada, analysis)
            attached += 1
        elif entry.get("orden") != order_idx:
            _set_thermal_analysis_field_smart(colada, entry["source_file"], {"orden": order_idx})
    return attached


def _attach_microstructure_group(colada, items):
    attached = 0
    for path, payload, _curve_dt in items:
        material_base = str((payload.get("info", {}) or {}).get("Material", "") or "").strip()
        analysis = _build_history_analysis(payload, colada, material_base, observacion="", etapa="", auto_linked=True)
        _attach_thermal_analysis_smart(colada, analysis)
        attached += 1
    return attached


@router.delete("/records")
def delete_records(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    paths = [str(p or "").strip() for p in (payload.get("paths") or []) if str(p or "").strip()]
    if not paths:
        raise HTTPException(status_code=400, detail={"error": "sin_registros"})
    errors = []
    deleted = 0
    for p in paths:
        try:
            path_obj = Path(p)
            if path_obj.exists():
                path_obj.unlink()
            deleted += 1
            _PARSE_CACHE.pop(p, None)
        except Exception as ex:
            errors.append(f"{p}: {ex}")
    return {"deleted": deleted, "errors": errors}


@router.post("/open-folder")
def open_folder(_: dict = Depends(devices.require_approved_device)):
    try:
        os.startfile(str(THERMAL_ANALYSIS_DIR))
    except Exception:
        try:
            subprocess.Popen(["explorer", str(THERMAL_ANALYSIS_DIR)])
        except Exception as ex:
            raise HTTPException(status_code=500, detail={"error": str(ex)})
    return {"ok": True}


@router.get("/device-ips")
def device_ips(_: dict = Depends(devices.require_approved_device)):
    ips = datos.load_thermal_ips()
    return {"ips": ips, "default": DEFAULT_THERMAL_DEVICE_IP}


def _check_current_session_carbon(new_paths, device_by_path):
    """Si alguno de los análisis RECIÉN detectados (recién descargados en esta llamada, no cualquiera de
    los ya existentes) es de Carbono, avisa por WebSocket para que el operador confirme cargar C/Si en
    "Actual". Dos casos:
    - Ya hay una sesión en curso (session_started_at seteado): el análisis tiene que caer dentro de su
      ventana de horario (desde que arrancó hasta ahora).
    - Todavía NO hay sesión en curso: no hay ventana de horario contra que comparar, así que se usa
      "reciente" (últimas THERMAL_MATCH_MAX_DELTA horas) como proxy, y el aviso se manda con
      no_session=True para que el frontend, además de C/Si, le ofrezca al operador elegir el material
      final.
    Este caso es DISTINTO del auto-vinculado por horario a Históricos (_run_auto_link): la colada en curso
    todavía no está guardada ahí, así que nunca podría encontrarse por ese camino.

    Si Carbomax automático (Modbus) está prendido, ESTE aviso manual se omite -- ese loop ya procesa cada
    análisis de Carbono nuevo por su cuenta (calcula/aplica un plan de ajuste, no solo carga C/Si en
    "Actual"), avisar los dos caminos a la vez confundiría al operario con dos popups compitiendo por el
    mismo análisis."""
    ajuste_session = datos.load_ajuste_session()
    if bool(ajuste_session.get("carbomax_auto")):
        return
    started_raw = ajuste_session.get("session_started_at")
    colada = str(ajuste_session.get("colada", "") or "").strip()
    if not colada:
        return
    now = datetime.now()
    start_dt = _parse_session_datetime(started_raw) if started_raw else None
    no_session = start_dt is None
    for path in new_paths:
        item = device_by_path.get(path)
        if not item or str(item.get("mode_group", "")) != "Carbono":
            continue
        payload = item.get("payload") or {}
        curve_dt = _payload_datetime(payload)
        if curve_dt is None:
            continue
        if no_session:
            if (now - curve_dt) > THERMAL_MATCH_MAX_DELTA:
                continue
        elif not (start_dt <= curve_dt <= now):
            continue
        carbon, silicon = _payload_carbon_silicon(payload)
        if carbon is None or silicon is None:
            continue
        hub.broadcast_threadsafe("ajuste", {
            "type": "carbon_detected",
            "colada": colada,
            "carbon": carbon,
            "silicon": silicon,
            "source_name": str(item.get("name", "") or ""),
            "path": path,
            "no_session": no_session,
        })
        return  # un aviso por descarga alcanza


@router.post("/download")
def download_from_device(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    """Baja el índice+detalle desde la página web del equipo (device_sync.sync_once, HistIndex.dat/
    dadoshist.cgi, sin rutas alternativas), persiste en la misma tabla que ya se lee en /records, y
    auto-vincula lo nuevo por horario (Carbono y Microestructura). Es un "def" sincrono a propósito: FastAPI
    lo corre en un threadpool aparte, así que el bloqueo de red (puede tardar bastante si hay muchos
    análisis nuevos) no traba el resto del servidor."""
    ip = str(payload.get("ip") or "").strip() or DEFAULT_THERMAL_DEVICE_IP
    before_paths = {
        str(r.get("path", "") or "") for r in (datos.load_thermal_device_records() or []) if isinstance(r, dict)
    }
    result = device_sync.sync_once(ip)
    if not result.get("ok"):
        raise HTTPException(status_code=502, detail={"error": result.get("error") or "fallo_desconocido", "ip": ip})

    history_ips = [ip] + [h for h in datos.load_thermal_ips() if h != ip]
    datos.save_thermal_ips(history_ips[:10])

    _PARSE_CACHE.clear()
    auto_linked_total = 0
    if result.get("new"):
        after_records = [r for r in (datos.load_thermal_device_records() or []) if isinstance(r, dict)]
        device_by_path = {str(r.get("path", "") or ""): r for r in after_records}
        new_paths = [p for p in device_by_path if p and p not in before_paths]
        _check_current_session_carbon(new_paths, device_by_path)

        history = datos.load_history()
        for mode_group in ("Carbono", "Microestructura"):
            link_result = _run_auto_link(mode_group, history=history)
            auto_linked_total += link_result["attached"]

    return {
        "ok": True,
        "ip": ip,
        "new": result["new"],
        "reused": result["reused"],
        "total": result["total"],
        "auto_linked": auto_linked_total,
        "message": (
            f"{result['new']} análisis nuevo(s), {result['reused']} ya existían. "
            f"Total en esta PC: {result['total']}."
            + (f" {auto_linked_total} vinculado(s) automáticamente a su colada." if auto_linked_total else "")
        ),
    }
