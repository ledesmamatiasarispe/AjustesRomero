# rutas/informes.py -- puerto 1:1 de backend/routers/informes.py de ajuste_comp_web. Pestaña "Informes":
# dashboard de solo lectura, puerto de tab_informes.py. Un solo endpoint (GET /data) carga históricos +
# cucharas + calidad UNA vez y arma los 13 bloques (en vez de 13 endpoints que repetirían esas lecturas) --
# mismo patrón que refresh() + los 13 _fill_* de la version Tkinter, que recorrian self.hist/self.ladles/
# self.quality_reports una vez y les pasaban esos datos ya cargados a cada _fill_*.
#
# Dos imports del original no existen todavía en esta app (routers.historicos/routers.ajuste no son módulos
# separados acá, todo vive bajo modulos/ajuste) -- se portan como helpers locales en vez de crear una
# dependencia cruzada entre archivos de rutas/: _ladle_colada_key (duplicado tal cual en rutas/historicos.py
# también -- 9 líneas de lógica pura, no vale la pena una dependencia compartida por esto) y una versión
# simple de _alloy_by_name (la de rutas/historicos.py tiene parámetros require_adjust/prefer_type para
# desambiguar que esta pantalla no necesita -- aquí solo hace falta "el material con este nombre").
import re
from datetime import datetime

from fastapi import APIRouter, Depends

from .. import datos
from .. import dispositivos as devices
from ..ce import ce_from_percent
from ..config import ELEMENTS
from ..utils import to_float, fmt

router = APIRouter(prefix="/api/informes", tags=["informes"])

# Equivalencias aproximadas para reportar "kg de hierro colado" a partir de conteos que la app SI tiene con
# precision (cucharas, sesiones/coladas) pero sin pesada real de cada una -- son estimaciones de planta, no
# medidas.
LADLE_KG_PER_COUNT = 50.0
FURNACE_KG_PER_SESSION = 1000.0


def _alloy_by_name(alloys, name):
    name = str(name or "").strip()
    return next((a for a in alloys if str(a.get("nombre", "")).strip() == name), None)


_COLADA_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})\s*-\s*(.+?)\s*$")


def _ladle_colada_key(session):
    m = _COLADA_RE.match(session.get("colada", "") or "")
    if not m:
        return str(session.get("colada", "")).strip()
    idn, yy = m.group(1), m.group(2)
    return f"{int(idn):04d} /{str(yy).zfill(2)}"


# ---------- helpers generales ----------

def _session_month(session):
    for key in ("ended_at", "started_at", "fecha"):
        text = str(session.get(key, "") or "").strip()
        if len(text) >= 7 and text[:4].isdigit() and text[4] == "-":
            return text[:7]
    return "Sin fecha"


def _session_target_material(session):
    text = str(session.get("material_objetivo", "") or session.get("objetivo", "") or "").strip()
    if not text:
        colada = str(session.get("colada", "") or "")
        match = re.search(r"\bmat\s*([A-Za-z0-9_-]+)", colada, flags=re.IGNORECASE)
        if match:
            text = match.group(1)
    return text or "Sin material"


def _parse_ladle_time(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        pass
    try:
        return datetime.strptime(text[:19], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def _ladle_record_month(record):
    text = str(record.get("updated_at", "") or "").strip()
    if len(text) >= 7 and text[:4].isdigit() and text[4] == "-":
        return text[:7]
    events = record.get("events", []) if isinstance(record.get("events", []), list) else []
    event_dates = [e["dt"] for e in events if e.get("dt") is not None]
    if event_dates:
        return max(event_dates).strftime("%Y-%m")
    return "Sin fecha"


def _ladle_records(ladles):
    """Mismo dual legacy-lista/dict-actual que tab_historicos.py/tab_informes.py -- normaliza ambos formatos a
    la misma forma de "record" para que el resto de los reportes no distinga cuál es cuál."""
    history = ladles.get("history_by_colada", {}) if isinstance(ladles, dict) else {}
    if not isinstance(history, dict):
        return []
    records = []
    for colada, raw in history.items():
        if isinstance(raw, list):
            if not raw:
                continue
            raw = raw[-1] if isinstance(raw[-1], dict) else {}
            rows = raw.get("rows", []) if isinstance(raw.get("rows", []), list) else []
            counts = {}
            for row in rows:
                if not isinstance(row, dict):
                    continue
                material = str(row.get("material_final", "") or "").strip()
                if not material:
                    continue
                counts[material] = int(row.get("cantidad", 0) or 0)
            records.append({
                "colada": str(colada),
                "material_objetivo": str(raw.get("material_objetivo", "") or ""),
                "counts": counts,
                "events": [],
                "updated_at": str(raw.get("saved_at", "") or ""),
            })
            continue
        if not isinstance(raw, dict):
            continue
        counts = raw.get("counts", {}) if isinstance(raw.get("counts", {}), dict) else {}
        clean_counts = {}
        for material, qty in counts.items():
            try:
                clean_counts[str(material)] = max(0, int(qty))
            except Exception:
                clean_counts[str(material)] = 0
        events = []
        raw_events = raw.get("events", {}) if isinstance(raw.get("events", {}), dict) else {}
        for material, items in raw_events.items():
            if not isinstance(items, list):
                continue
            for item in items:
                saved_at = str(item.get("saved_at", "") if isinstance(item, dict) else item).strip()
                if saved_at:
                    events.append({
                        "material": str(material),
                        "saved_at": saved_at,
                        "dt": _parse_ladle_time(saved_at),
                    })
        events.sort(key=lambda e: e["dt"] or datetime.max)
        records.append({
            "colada": str(colada),
            "material_objetivo": str(raw.get("material_objetivo", "") or ""),
            "counts": clean_counts,
            "events": events,
            "updated_at": str(raw.get("updated_at", "") or ""),
        })
    return records


def _duration_label(seconds):
    total = max(0, int(seconds or 0))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


# ---------- helpers de calidad ----------

def _optional_float(value):
    text = str(value or "").strip().replace(",", ".")
    if not text:
        return None
    try:
        return float(text)
    except Exception:
        return None


def _text_field(report, field, default=""):
    return str(report.get(field, "") or default).strip()


def _display_code_label(prefix, value):
    text = str(value or "").strip()
    if not text:
        return ""
    if text.lower().startswith(prefix.lower() + " "):
        return text
    if text.isdigit():
        return f"{prefix} {text}"
    return text


def _material_label(report_or_value):
    if isinstance(report_or_value, dict):
        value = _text_field(report_or_value, "material")
    else:
        value = str(report_or_value or "").strip()
    return _display_code_label("Material", value) or "Sin material"


def _base_label(report):
    base_display = str(report.get("base_display", "") or "").strip()
    base_value = str(report.get("base", "") or "").strip()
    return (
        _display_code_label("Base", base_display)
        or _display_code_label("Base", base_value)
        or "Sin base"
    )


def _report_family(report):
    explicit = _text_field(report, "family")
    if explicit:
        return explicit
    morphology = _text_field(report, "morfologia").lower()
    graphite_type = _text_field(report, "tipo_grafito")
    nodules = _text_field(report, "conteo_nodulos") or _text_field(report, "pct_nodularizacion")
    if "nod" in morphology or nodules:
        return "Nodular"
    if "laminar" in morphology or graphite_type:
        return "Gris"
    return "Sin dato"


def _numeric_values(reports, field):
    values = [_optional_float(r.get(field, "")) for r in reports]
    return [v for v in values if v is not None]


def _avg_field(reports, field):
    values = _numeric_values(reports, field)
    if not values:
        return None
    return round(sum(values) / len(values), 2)


def _counter_add(counter, key, amount=1):
    if isinstance(key, tuple):
        clean_key = tuple(str(part or "").strip() or "Sin dato" for part in key)
    else:
        clean_key = str(key or "").strip() or "Sin dato"
    counter[clean_key] = counter.get(clean_key, 0) + amount


def _top_counter_label(counter):
    if not counter:
        return "N/D"
    key, count = max(counter.items(), key=lambda item: item[1])
    return f"{key} ({count})"


# ---------- helpers de inoculantes ----------

def _normalize_inoc_entries(raw_list):
    out = []
    for e in raw_list:
        if isinstance(e, str):
            out.append({"nombre": e, "cantidad_dosis": 1, "momento": "horno"})
        elif isinstance(e, dict):
            out.append({
                "nombre": str(e.get("nombre", "") or ""),
                "cantidad_dosis": max(1, int(e.get("cantidad_dosis", 1) or 1)),
                "momento": str(e.get("momento", "horno") or "horno"),
            })
    return out


# ---------- helpers de línea de tiempo ----------

def _timeline_colada_key(colada):
    raw = str(colada or "").strip()
    m = re.match(r"^\s*(\d+)\s*/\s*(\d{2,4})", raw)
    if m:
        return f"{int(m.group(1)):04d} /{m.group(2).zfill(2)}"
    return raw


# ---------- panel builders ----------

def _build_summary(hist, alloys):
    total_sessions = len(hist)
    total_ajustes = sum(len(s.get("ajustes", [])) for s in hist)
    total_calculos = sum(len(s.get("calculos", [])) for s in hist)
    total_catalog = len(alloys)
    total_adjusters = sum(1 for a in alloys if a.get("ajuste"))
    total_kg = 0.0
    total_targets = set()
    for session in hist:
        if session.get("objetivo"):
            total_targets.add(session.get("objetivo"))
        for ajuste in session.get("ajustes", []):
            total_kg += sum(to_float(kg) for kg in (ajuste.get("materiales") or {}).values())
    return {
        "total_catalog": total_catalog,
        "total_adjusters": total_adjusters,
        "total_sessions": total_sessions,
        "total_ajustes": total_ajustes,
        "total_calculos": total_calculos,
        "total_targets": len(total_targets),
        "total_kg": round(total_kg, 3),
        "chart": {
            "labels": ["Sesiones", "Ajustes", "Calculos", "Calc. sin guardar"],
            "values": [
                total_sessions, total_ajustes, total_calculos,
                max(0, total_calculos - total_ajustes),
            ],
        },
    }


def _build_materials(hist):
    totals = {}
    for session in hist:
        for ajuste in session.get("ajustes", []):
            for name, kg in (ajuste.get("materiales") or {}).items():
                totals[name] = totals.get(name, 0.0) + to_float(kg)
    ordered = sorted(totals.items(), key=lambda x: x[1], reverse=True)
    return {
        "rows": [{"material": n, "kg": round(kg, 3)} for n, kg in ordered[:25]],
        "chart_top15": [{"material": n, "kg": round(kg, 3)} for n, kg in ordered[:15]],
    }


def _build_monthly_furnace(ladle_records):
    months = {}
    material_totals = {}
    ladle_coladas = 0
    total_cucharas = 0

    for record in ladle_records:
        counts = record.get("counts", {}) if isinstance(record.get("counts", {}), dict) else {}
        month = _ladle_record_month(record)
        bucket = months.setdefault(month, {})
        record_used = False
        for material, qty in counts.items():
            try:
                count = max(0, int(qty or 0))
            except Exception:
                count = 0
            if count <= 0:
                continue
            material = str(material)
            kg = count * LADLE_KG_PER_COUNT
            bucket[material] = bucket.get(material, 0.0) + kg
            material_totals[material] = material_totals.get(material, 0.0) + kg
            total_cucharas += count
            record_used = True
        if not bucket:
            months.pop(month, None)
        if record_used:
            ladle_coladas += 1

    ordered_months = sorted(months)
    ordered_materials = [m for m, _ in sorted(material_totals.items(), key=lambda i: i[1], reverse=True)]
    data = [
        {
            "month": month,
            "materials": {m: round(months[month].get(m, 0.0), 3) for m in ordered_materials},
            "total": round(sum(months[month].values()), 3),
        }
        for month in ordered_months
    ]
    top_material = ""
    if material_totals:
        mat, kg = max(material_totals.items(), key=lambda i: i[1])
        top_material = f"{mat}: {fmt(kg / LADLE_KG_PER_COUNT, 0)} cucharas"
    return {
        "data": data,
        "materials_order": ordered_materials,
        "summary": {
            "total_cucharas": total_cucharas,
            "kg_per_count": LADLE_KG_PER_COUNT,
            "months": len(ordered_months),
            "materials": len(ordered_materials),
            "top_material": top_material or "N/D",
            "coladas_con_cucharas": ladle_coladas,
        },
    }


def _build_monthly_hornos(hist):
    months = {}
    hornos_by_month = {}
    material_totals = {}
    hornos = 0

    for session in hist:
        kg = FURNACE_KG_PER_SESSION
        month = _session_month(session)
        material = _session_target_material(session)
        bucket = months.setdefault(month, {})
        bucket[material] = bucket.get(material, 0.0) + kg
        hornos_by_month[month] = hornos_by_month.get(month, 0) + 1
        material_totals[material] = material_totals.get(material, 0.0) + kg
        hornos += 1

    ordered_months = sorted(months)
    ordered_materials = [m for m, _ in sorted(material_totals.items(), key=lambda i: i[1], reverse=True)]
    data = [
        {
            "month": month,
            "materials": {m: round(months[month].get(m, 0.0), 3) for m in ordered_materials},
            "total": round(sum(months[month].values()), 3),
            "hornos": hornos_by_month.get(month, 0),
        }
        for month in ordered_months
    ]
    total_kg = sum(item["total"] for item in data)
    top_material = ""
    if material_totals:
        mat, kg = max(material_totals.items(), key=lambda i: i[1])
        top_material = f"{mat}: {fmt(kg / FURNACE_KG_PER_SESSION, 0)} hornos"
    return {
        "data": data,
        "materials_order": ordered_materials,
        "summary": {
            "hornos": hornos,
            "kg_per_session": FURNACE_KG_PER_SESSION,
            "total_kg": round(total_kg, 0),
            "months": len(ordered_months),
            "materials": len(ordered_materials),
            "top_material": top_material or "N/D",
        },
    }


def _build_targets(hist):
    counts = {}
    for session in hist:
        for ajuste in session.get("ajustes", []):
            name = ajuste.get("objetivo", "") or session.get("objetivo", "")
            if not name:
                continue
            counts[name] = counts.get(name, 0) + 1
    ordered = sorted(counts.items(), key=lambda x: x[1], reverse=True)
    return {
        "rows": [{"objetivo": n, "cant": c} for n, c in ordered[:25]],
        "chart_top10": [{"objetivo": n, "cant": c} for n, c in ordered[:10]],
    }


def _build_elements(hist):
    stats = {}
    for session in hist:
        for ajuste in session.get("ajustes", []):
            for change in ajuste.get("cambios_list", []):
                element = change.get("elemento") if isinstance(change, dict) else None
                if not element:
                    continue
                delta_abs = abs(to_float(change.get("delta", 0.0)))
                entry = stats.setdefault(element, {"veces": 0, "delta": 0.0})
                entry["veces"] += 1
                entry["delta"] += delta_abs
    ordered = sorted(stats.items(), key=lambda x: (x[1]["delta"], x[1]["veces"]), reverse=True)
    return {
        "rows": [
            {"elemento": e, "veces": d["veces"], "delta": round(d["delta"], 4)}
            for e, d in ordered[:25]
        ],
        "chart_top12": [
            {"elemento": e, "delta": round(d["delta"], 4)}
            for e, d in sorted(stats.items(), key=lambda x: x[1].get("delta", 0), reverse=True)[:12]
        ],
    }


def _build_ce(hist):
    stats = {}
    for session in hist:
        for ajuste in session.get("ajustes", []):
            formula = ajuste.get("ce_formula", "") or "N/D"
            entry = stats.setdefault(formula, {"veces": 0, "ce_ini": 0.0, "ce_est": 0.0})
            entry["veces"] += 1
            entry["ce_ini"] += to_float(ajuste.get("ce_inicial", 0.0))
            entry["ce_est"] += to_float(ajuste.get("ce_estimado", 0.0))
    ordered = sorted(stats.items(), key=lambda x: x[1]["veces"], reverse=True)
    rows = []
    chart = {"formulas": [], "ini": [], "fin": []}
    for formula, data in ordered:
        veces = max(data["veces"], 1)
        ce_ini = round(data["ce_ini"] / veces, 4)
        ce_est = round(data["ce_est"] / veces, 4)
        rows.append({"formula": formula, "veces": data["veces"], "ce_ini": ce_ini, "ce_est": ce_est})
        chart["formulas"].append(formula)
        chart["ini"].append(ce_ini)
        chart["fin"].append(ce_est)
    return {"rows": rows, "chart": chart}


def _build_days(hist):
    per_day = {}
    for session in hist:
        ended = str(session.get("ended_at", "") or "")
        day = ended[:10] if len(ended) >= 10 else "Sin fecha"
        entry = per_day.setdefault(day, {"sesiones": 0, "ajustes": 0, "kg": 0.0})
        entry["sesiones"] += 1
        entry["ajustes"] += len(session.get("ajustes", []))
        for ajuste in session.get("ajustes", []):
            entry["kg"] += sum(to_float(kg) for kg in (ajuste.get("materiales") or {}).values())
    rows = [
        {"fecha": d, "sesiones": v["sesiones"], "ajustes": v["ajustes"], "kg": round(v["kg"], 3)}
        for d, v in sorted(per_day.items(), key=lambda x: x[0], reverse=True)[:25]
    ]
    valid_days = {f: d for f, d in per_day.items() if f != "Sin fecha"}
    chart = {"fechas": [], "kg": [], "sesiones": []}
    if valid_days:
        fechas = sorted(valid_days.keys())[-30:]
        chart["fechas"] = fechas
        chart["kg"] = [round(valid_days[f].get("kg", 0), 3) for f in fechas]
        chart["sesiones"] = [valid_days[f].get("sesiones", 0) for f in fechas]
    return {"rows": rows, "chart": chart}


def _build_durations(hist):
    durations = []
    for session in hist:
        start = str(session.get("started_at", "") or "")
        end = str(session.get("ended_at", "") or "")
        try:
            dt0 = datetime.strptime(start[:19], "%Y-%m-%d %H:%M:%S")
            dt1 = datetime.strptime(end[:19], "%Y-%m-%d %H:%M:%S")
            mins = max((dt1 - dt0).total_seconds() / 60.0, 0.0)
            durations.append(round(mins, 2))
        except Exception:
            pass
    if not durations:
        return {"durations": [], "avg": None, "min": None, "max": None, "count": 0}
    avg = sum(durations) / len(durations)
    return {
        "durations": durations,
        "avg": round(avg, 1),
        "min": round(min(durations), 1),
        "max": round(max(durations), 1),
        "count": len(durations),
    }


def _build_cucharas(ladle_records):
    total_by_material = {}
    coladas_by_material = {}
    hour_stats = {}
    total_cucharas = 0
    timed_records = []
    interval_values = []
    event_count = 0
    coladas_rows = []

    for record in ladle_records:
        counts = record.get("counts", {})
        total = sum(max(0, int(qty or 0)) for qty in counts.values())
        if total <= 0:
            continue
        total_cucharas += total
        for material, qty in counts.items():
            qty = max(0, int(qty or 0))
            if qty <= 0:
                continue
            total_by_material[material] = total_by_material.get(material, 0) + qty
            coladas_by_material.setdefault(material, set()).add(record["colada"])

        parsed_events = [e for e in record.get("events", []) if e.get("dt") is not None]
        event_count += len(parsed_events)
        duration = None
        avg_interval = None
        if parsed_events:
            first = parsed_events[0]["dt"]
            last = parsed_events[-1]["dt"]
            duration = max(0, (last - first).total_seconds())
            if len(parsed_events) >= 2:
                avg_interval = duration / (len(parsed_events) - 1)
                interval_values.append(avg_interval)
                timed_records.append({"colada": record["colada"], "total": total, "duration": duration, "avg_interval": avg_interval})
            for event in parsed_events:
                hour = event["dt"].strftime("%H:00")
                bucket = hour_stats.setdefault(hour, {"total": 0, "materials": {}})
                bucket["total"] += 1
                mat = event.get("material", "")
                bucket["materials"][mat] = bucket["materials"].get(mat, 0) + 1

        top_material = ""
        if counts:
            top_mat, top_qty = max(counts.items(), key=lambda i: int(i[1] or 0))
            top_material = f"{top_mat} ({top_qty})"
        coladas_rows.append({
            "colada": record["colada"],
            "objetivo": record.get("material_objetivo", ""),
            "total": total,
            "primera": parsed_events[0]["saved_at"] if parsed_events else "",
            "ultima": parsed_events[-1]["saved_at"] if parsed_events else "",
            "duracion": _duration_label(duration) if duration is not None and len(parsed_events) >= 2 else "",
            "prom_entre": _duration_label(avg_interval) if avg_interval is not None else "",
            "top_material": top_material,
        })

    materials_rows = []
    for material, qty in sorted(total_by_material.items(), key=lambda i: i[1], reverse=True):
        coladas = len(coladas_by_material.get(material, set()))
        pct = (qty / total_cucharas * 100.0) if total_cucharas else 0.0
        prom = (qty / coladas) if coladas else 0.0
        materials_rows.append({
            "material": material, "total": qty, "coladas": coladas,
            "pct": round(pct, 1), "prom": round(prom, 2),
        })

    hours_rows = []
    for hour, data in sorted(hour_stats.items()):
        dominant = ""
        if data["materials"]:
            mat, qty = max(data["materials"].items(), key=lambda i: i[1])
            dominant = f"{mat} ({qty})"
        hours_rows.append({"hora": hour, "total": data["total"], "material": dominant})

    coladas_con_cucharas = sum(1 for r in ladle_records if sum(int(q or 0) for q in r.get("counts", {}).values()) > 0)
    material_top = ""
    if total_by_material:
        mat, qty = max(total_by_material.items(), key=lambda i: i[1])
        material_top = f"{mat} ({qty})"
    avg_per_colada = total_cucharas / coladas_con_cucharas if coladas_con_cucharas else 0.0
    avg_duration = sum(r["duration"] for r in timed_records) / len(timed_records) if timed_records else 0
    avg_interval = sum(interval_values) / len(interval_values) if interval_values else 0
    fastest = min(timed_records, key=lambda r: r["duration"], default=None)
    slowest = max(timed_records, key=lambda r: r["duration"], default=None)

    sorted_mats = sorted(total_by_material.items(), key=lambda x: x[1], reverse=True)
    top8 = sorted_mats[:8]
    otros = sum(v for _, v in sorted_mats[8:])
    pie = [{"label": m, "value": v} for m, v in top8]
    if otros > 0:
        pie.append({"label": "Otros", "value": otros})

    return {
        "summary": {
            "coladas_con_cucharas": coladas_con_cucharas,
            "total_cucharas": total_cucharas,
            "materiales_distintos": len(total_by_material),
            "material_top": material_top or "N/D",
            "prom_por_colada": round(avg_per_colada, 2),
            "eventos_con_horario": event_count,
            "duracion_prom": _duration_label(avg_duration) if timed_records else "N/D",
            "prom_entre_cucharas": _duration_label(avg_interval) if interval_values else "N/D",
            "colada_mas_rapida": f"{fastest['colada']} ({_duration_label(fastest['duration'])})" if fastest else "N/D",
            "colada_mas_lenta": f"{slowest['colada']} ({_duration_label(slowest['duration'])})" if slowest else "N/D",
        },
        "materials": materials_rows,
        "coladas": coladas_rows,
        "hours": hours_rows,
        "pie": pie,
        "hours_chart": {"horas": [h for h, _ in sorted(hour_stats.items())], "totales": [d["total"] for _, d in sorted(hour_stats.items())]},
    }


def _build_quality(quality_reports):
    reports = [r for r in quality_reports if isinstance(r, dict)]
    total = len(reports)
    active = [r for r in reports if not r.get("archived")]
    archived = [r for r in reports if r.get("archived")]
    drafts = [r for r in reports if r.get("_draft_pending")]

    lots = {_text_field(r, "lote") for r in reports if _text_field(r, "lote")}
    bases = {_base_label(r) for r in reports if _base_label(r) != "Sin base"}
    materials = {_text_field(r, "material") for r in reports if _text_field(r, "material")}
    informes_named = sum(1 for r in reports if str(r.get("informe", "") or "").strip())
    with_observations = sum(1 for r in reports if str(r.get("datos", "") or "").strip())
    with_ce = len(_numeric_values(reports, "ce_final"))
    with_traccion = len(_numeric_values(reports, "traccion"))
    with_dureza = len(_numeric_values(reports, "dureza"))
    avg_reports_per_lot = total / len(lots) if lots else 0.0

    material_counter, base_counter, family_counter = {}, {}, {}
    dates = []
    for r in reports:
        material = _material_label(r)
        if material:
            _counter_add(material_counter, material)
        base = _base_label(r)
        if base != "Sin base":
            _counter_add(base_counter, base)
        _counter_add(family_counter, _report_family(r))
        date_label = _text_field(r, "fecha")[:10]
        if date_label:
            dates.append(date_label)
    date_range = f"{min(dates)} a {max(dates)}" if dates else "N/D"

    summary = {
        "total": total, "active": len(active), "archived": len(archived), "drafts": len(drafts),
        "date_range": date_range, "lots": len(lots), "bases": len(bases), "materials": len(materials),
        "top_material": _top_counter_label(material_counter), "top_base": _top_counter_label(base_counter),
        "top_family": _top_counter_label(family_counter), "informes_named": informes_named,
        "with_observations": with_observations, "with_ce": with_ce, "with_traccion": with_traccion,
        "with_dureza": with_dureza, "avg_reports_per_lot": round(avg_reports_per_lot, 2),
    }

    prop_defs = (
        ("ce_final", "CE final"), ("c_final", "C final"), ("si_final", "Si final"),
        ("traccion", "Traccion"), ("dureza", "Dureza"), ("conteo_nodulos", "Conteo nodulos"),
        ("pct_nodularizacion", "% nodularizacion"), ("alargamiento", "Alargamiento"),
        ("perlita", "Perlita %"), ("ferrita", "Ferrita %"),
    )
    props_rows = []
    for field, label in prop_defs:
        values = _numeric_values(reports, field)
        if not values:
            continue
        props_rows.append({
            "campo": label, "prom": round(sum(values) / len(values), 2),
            "min": round(min(values), 2), "max": round(max(values), 2), "cant": len(values),
        })

    by_material, by_base, micro_counts, day_stats = {}, {}, {}, {}
    for r in reports:
        material = _material_label(r)
        base = _base_label(r)
        by_material.setdefault(material, []).append(r)
        by_base.setdefault(base, []).append(r)
        _counter_add(micro_counts, ("Familia", _report_family(r)))
        for kind, field in (("Matriz", "matriz"), ("Morfologia", "morfologia"), ("Tipo grafito", "tipo_grafito"), ("Seccion", "seccion")):
            if field == "morfologia" and _report_family(r) == "Nodular":
                continue
            value = str(r.get(field, "") or "").strip()
            if value:
                _counter_add(micro_counts, (kind, value))
        fecha = _text_field(r, "fecha")[:10] or "Sin fecha"
        day = day_stats.setdefault(fecha, {"informes": 0, "lotes": set(), "materials": set()})
        day["informes"] += 1
        lote = _text_field(r, "lote")
        if lote:
            day["lotes"].add(lote)
        if material and material != "Sin material":
            day["materials"].add(material)

    materials_rows = []
    for material, items in sorted(by_material.items(), key=lambda i: len(i[1]), reverse=True):
        bases_for_material = sorted({_base_label(r) for r in items if _base_label(r) != "Sin base"})
        materials_rows.append({
            "material": material, "informes": len(items), "bases": ", ".join(bases_for_material[:4]),
            "traccion": _avg_field(items, "traccion"), "dureza": _avg_field(items, "dureza"),
            "ce": _avg_field(items, "ce_final"),
        })

    bases_rows = []
    for base, items in sorted(by_base.items(), key=lambda i: len(i[1]), reverse=True):
        materials_for_base = sorted({_material_label(r) for r in items if _material_label(r) != "Sin material"})
        bases_rows.append({
            "base": base, "informes": len(items), "materiales": ", ".join(materials_for_base[:8]),
            "traccion": _avg_field(items, "traccion"), "dureza": _avg_field(items, "dureza"),
        })

    micro_rows = []
    for (kind, value), count in sorted(micro_counts.items(), key=lambda i: (i[0][0], -i[1], i[0][1])):
        pct = (count / total * 100.0) if total else 0.0
        micro_rows.append({"tipo": kind, "valor": value, "informes": count, "pct": round(pct, 1)})

    days_rows = []
    for fecha, data in sorted(day_stats.items(), key=lambda i: i[0], reverse=True):
        days_rows.append({
            "fecha": fecha, "informes": data["informes"], "lotes": len(data["lotes"]),
            "materiales": ", ".join(sorted(data["materials"])[:8]),
        })

    chart_mats = list(by_material.keys())[:8]
    chart = {
        "materiales": chart_mats,
        "traccion": [_avg_field(by_material[m], "traccion") or 0 for m in chart_mats],
        "dureza": [_avg_field(by_material[m], "dureza") or 0 for m in chart_mats],
    }

    return {
        "summary": summary, "props": props_rows, "materials": materials_rows,
        "bases": bases_rows, "micro": micro_rows, "days": days_rows, "chart": chart,
    }


def _build_inoculantes(alloys, ladle_records):
    inoc_info = {}
    for a in alloys:
        if a.get("inoculante") or a.get("subtipo") == "Inoculante" or a.get("tipo") == "Inoculante":
            nombre = str(a.get("nombre", "") or "").strip()
            if nombre:
                inoc_info[nombre] = {
                    "unidad": a.get("unidad_inoculacion") or "cucharín",
                    "gramos": to_float(a.get("gramos_cucharin1", 0)),
                }

    final_inoc_map = {}
    for a in alloys:
        if a.get("tipo") != "Aleación final":
            continue
        nombre_final = str(a.get("nombre", "") or "").strip()
        inoc_meta = a.get("inoculacion_meta") or {}
        default_entries = _normalize_inoc_entries(datos.resolve_inoc_protocol(inoc_meta))
        if default_entries and nombre_final:
            final_inoc_map[nombre_final] = default_entries
        por_base = inoc_meta.get("por_base", {}) if isinstance(inoc_meta, dict) else {}
        if isinstance(por_base, dict):
            for base, raw in por_base.items():
                entries = _normalize_inoc_entries(raw if isinstance(raw, list) else [])
                if entries:
                    final_inoc_map[f"{nombre_final}|{base}"] = entries

    def inoc_entries_for(mat, base):
        base = str(base or "").strip()
        if base:
            specific = final_inoc_map.get(f"{mat}|{base}")
            if specific is not None:
                return specific
        return final_inoc_map.get(mat, [])

    # Configuracion
    config_data = {}
    for mat, entries in final_inoc_map.items():
        for e in entries:
            inoc = e["nombre"]
            if inoc not in config_data:
                config_data[inoc] = {"materiales": set(), "etapas": set()}
            config_data[inoc]["materiales"].add(mat)
            config_data[inoc]["etapas"].add(e["momento"])
    config_rows = []
    for inoc, data in sorted(config_data.items()):
        info = inoc_info.get(inoc, {})
        g = info.get("gramos", 0)
        config_rows.append({
            "inoc": inoc, "unidad": info.get("unidad", "—"),
            "gramos": round(g, 4) if g else None,
            "materiales": ", ".join(sorted(data["materiales"])),
            "etapas": ", ".join(sorted(data["etapas"])),
        })

    # Colada mas reciente
    recent_colada = None
    recent_rows = []
    if ladle_records:
        recent = max(ladle_records, key=lambda r: r.get("updated_at", "") or "")
        recent_colada = recent["colada"]
        recent_base = recent.get("material_objetivo", "")
        acc = {}
        for mat, qty in recent.get("counts", {}).items():
            qty = max(0, int(qty or 0))
            for e in inoc_entries_for(mat, recent_base):
                inoc = e["nombre"]
                dosis = qty * e["cantidad_dosis"]
                g = inoc_info.get(inoc, {}).get("gramos", 0)
                if inoc not in acc:
                    acc[inoc] = {"dosis": 0, "total_g": 0.0}
                acc[inoc]["dosis"] += dosis
                acc[inoc]["total_g"] += dosis * g
        for inoc, data in sorted(acc.items()):
            g = inoc_info.get(inoc, {}).get("gramos", 0)
            recent_rows.append({
                "inoc": inoc, "dosis": data["dosis"],
                "gramos_u": round(g, 4) if g else None,
                "total_kg": round(data["total_g"] / 1000, 3),
            })

    # Historico acumulado
    hist_acc = {}
    for record in ladle_records:
        record_base = record.get("material_objetivo", "")
        for mat, qty in record.get("counts", {}).items():
            qty = max(0, int(qty or 0))
            for e in inoc_entries_for(mat, record_base):
                inoc = e["nombre"]
                dosis = qty * e["cantidad_dosis"]
                g = inoc_info.get(inoc, {}).get("gramos", 0)
                if inoc not in hist_acc:
                    hist_acc[inoc] = {"dosis": 0, "total_g": 0.0, "coladas": set()}
                hist_acc[inoc]["dosis"] += dosis
                hist_acc[inoc]["total_g"] += dosis * g
                hist_acc[inoc]["coladas"].add(record["colada"])
    hist_rows = []
    for inoc, data in sorted(hist_acc.items(), key=lambda x: x[1]["total_g"], reverse=True):
        n_coladas = len(data["coladas"])
        prom_kg = (data["total_g"] / n_coladas / 1000) if n_coladas else 0.0
        hist_rows.append({
            "inoc": inoc, "coladas": n_coladas, "dosis": data["dosis"],
            "total_kg": round(data["total_g"] / 1000, 3), "prom_kg": round(prom_kg, 3),
        })

    # Consumo mensual
    monthly = {}
    for record in ladle_records:
        updated = str(record.get("updated_at", "") or "").replace("T", " ")
        month = updated[:7]
        if len(month) < 7:
            continue
        record_base = record.get("material_objetivo", "")
        for mat, qty in record.get("counts", {}).items():
            qty = max(0, int(qty or 0))
            for e in inoc_entries_for(mat, record_base):
                inoc = e["nombre"]
                dosis = qty * e["cantidad_dosis"]
                g = inoc_info.get(inoc, {}).get("gramos", 0)
                monthly.setdefault(month, {}).setdefault(inoc, 0.0)
                monthly[month][inoc] += dosis * g

    all_inocs = sorted({inoc for m_data in monthly.values() for inoc in m_data})
    months_sorted = sorted(monthly.keys())
    monthly_table = []
    col_totals = {inoc: 0.0 for inoc in all_inocs}
    for month in months_sorted:
        row = {"mes": month}
        for inoc in all_inocs:
            v = monthly[month].get(inoc, 0.0) / 1000
            col_totals[inoc] += v
            row[inoc] = round(v, 3)
        monthly_table.append(row)

    return {
        "config": config_rows,
        "recent": {"colada": recent_colada, "rows": recent_rows},
        "historico": hist_rows,
        "monthly": {
            "meses": months_sorted, "inoculantes": all_inocs, "rows": monthly_table,
            "totales": {inoc: round(v, 3) for inoc, v in col_totals.items()},
        },
    }


def _build_timeline(hist, ladle_records):
    ladle_history = {_timeline_colada_key(r["colada"]): r for r in ladle_records}

    by_day = {}
    for s in hist:
        ts = str(s.get("started_at", "") or "")
        if len(ts) < 10:
            continue
        day = ts[:10]
        by_day.setdefault(day, []).append(s)

    available_days = sorted(by_day.keys(), reverse=True)
    days_out = {}
    for day, sessions in by_day.items():
        sessions_sorted = sorted(sessions, key=lambda s: str(s.get("started_at", "") or ""))
        rows = []
        for session in sessions_sorted:
            colada = str(session.get("colada", "") or "")
            key = _timeline_colada_key(colada)
            ladle_rec = ladle_history.get(key)
            cucharas = []
            total_cucharas = 0
            if ladle_rec:
                events = ladle_rec.get("events", [])
                for ev in events:
                    if ev.get("dt") is not None:
                        cucharas.append(ev["saved_at"])
                if events:
                    total_cucharas = len(events)
                else:
                    total_cucharas = sum(max(0, int(v or 0)) for v in ladle_rec.get("counts", {}).values())
            rows.append({
                "colada": colada,
                "objetivo": str(session.get("objetivo", "") or ""),
                "started_at": session.get("started_at"),
                "ended_at": session.get("ended_at"),
                "ajustes": [
                    {"fecha": aj.get("fecha"), "objetivo": aj.get("objetivo", "")}
                    for aj in session.get("ajustes", [])
                ],
                "cucharas": cucharas,
                "total_cucharas": total_cucharas,
            })
        days_out[day] = rows

    return {"available_days": available_days, "days": days_out}


def _session_final_composition(session):
    """Composición/masa/CE final de una colada: la del ÚLTIMO ajuste aplicado antes de guardar la sesión
    (ajustes_log[-1].estimado) -- no existe un campo "composicion_final" aparte. Es la composición del HORNO,
    antes de la cuchara/inoculación -- ver _synthesize_final_composition para sumarle el inoculante. None si
    la colada no tiene ningún ajuste aplicado."""
    ajustes = session.get("ajustes", [])
    if not ajustes:
        return None
    last = ajustes[-1]
    estimado = last.get("estimado", {}) if isinstance(last.get("estimado"), dict) else {}
    comp = estimado.get("comp", {}) if isinstance(estimado.get("comp"), dict) else {}
    if not comp:
        return None
    return {
        "comp": comp,
        "masa": to_float(estimado.get("masa", 0.0)),
        "ce_formula": last.get("ce_formula") or "FUNDICION",
        "ce_custom": last.get("ce_custom") or {},
        "ce_estimado": last.get("ce_estimado"),
    }


def _synthesize_final_composition(alloys, base_comp, bath_kg, final_alloy, base_name):
    """Composición REAL final (horno + inoculación en cuchara) -- reparte bath_kg entre "lo que ya estaba en
    el horno" (base_comp) y "lo que trajo el inoculante" (su propia composición), pesado por gramos reales de
    cada dosis. None si no hay protocolo de inoculación resuelto para esa combinación (se usa la composición
    de horno tal cual)."""
    if not isinstance(final_alloy, dict) or bath_kg <= 0:
        return None
    inoc_list = datos.resolve_inoc_protocol(final_alloy.get("inoculacion_meta"), base=base_name)
    inoc_grams = {}
    for e in (inoc_list or []):
        if isinstance(e, str):
            iname, dosis = e, 1
        elif isinstance(e, dict):
            iname = str(e.get("nombre", ""))
            dosis = int(e.get("cantidad_dosis", 1) or 1)
        else:
            continue
        if not iname or dosis <= 0:
            continue
        ia = _alloy_by_name(alloys, iname)
        if ia:
            g = to_float(ia.get("gramos_cucharin1", 0) or 0)
            if g:
                inoc_grams[iname] = inoc_grams.get(iname, 0.0) + dosis * g
    if not inoc_grams:
        return None
    total_inoc_kg = sum(v / 1000.0 for v in inoc_grams.values())
    base_kg = max(0.0, bath_kg - total_inoc_kg)
    comp = {}
    for el in ELEMENTS:
        contrib = base_kg * to_float(base_comp.get(el, 0)) / 100.0
        for iname, grams in inoc_grams.items():
            ia = _alloy_by_name(alloys, iname)
            if ia:
                contrib += (grams / 1000.0) * to_float(ia.get("composicion", {}).get(el, 0)) / 100.0
        comp[el] = contrib / bath_kg * 100.0
    return comp


def _build_composicion_traccion(hist, quality_reports, alloys):
    """Compara la composición química final de cada horno (horno + inoculación en cuchara cuando se puede
    resolver el protocolo; si no, la del horno sola) contra la tracción real medida en Calidad para esa misma
    colada -- una fila por informe de Calidad que tenga traccion_real cargada Y cuya colada tenga composición
    final conocida."""
    final_by_name = {a.get("nombre", ""): a for a in alloys if a.get("tipo") == "Aleación final"}

    comp_by_key = {}
    for session in hist:
        final = _session_final_composition(session)
        if final is None:
            continue
        comp_by_key[_ladle_colada_key(session)] = {"colada": session.get("colada", ""), **final}

    rows = []
    for r in quality_reports:
        if not isinstance(r, dict):
            continue
        lote = _text_field(r, "lote")
        if not lote:
            continue
        entry = comp_by_key.get(datos.normalize_colada_key(lote))
        if entry is None:
            continue
        traccion_real = _optional_float(r.get("traccion_real", ""))
        if traccion_real is None:
            continue

        material_raw = _text_field(r, "material")
        base_raw = _text_field(r, "base")
        final_alloy = final_by_name.get(material_raw)
        comp_inoc = _synthesize_final_composition(alloys, entry["comp"], entry["masa"], final_alloy, base_raw)
        incluye_inoc = comp_inoc is not None
        comp = comp_inoc if incluye_inoc else entry["comp"]
        ce_final = ce_from_percent(comp, entry["ce_formula"], entry["ce_custom"]) if incluye_inoc else entry["ce_estimado"]

        rows.append({
            "colada": entry["colada"],
            "material": _material_label(r),
            "family": _report_family(r),
            "fecha": _text_field(r, "fecha"),
            "comp": {e: round(to_float(v), 4) for e, v in comp.items()},
            "ce_final": round(to_float(ce_final), 4) if ce_final is not None else None,
            "traccion_real": traccion_real,
            "incluye_inoculacion": incluye_inoc,
        })
    rows.sort(key=lambda row: row["fecha"], reverse=True)
    # Resumen y puntos del gráfico se calculan en el frontend, no acá -- hay un selector de material que
    # filtra ambos en el cliente, así que un resumen fijo del lado del servidor quedaría desactualizado apenas
    # alguien cambia el filtro.
    return {"rows": rows}


@router.get("/data")
def get_informes_data(_: dict = Depends(devices.require_acceso)):
    hist = datos.load_history()
    datos.prune_ladles_history_for_sessions(hist)
    ladles = datos.load_ladles_state()
    quality_reports = datos.load_quality_reports()
    alloys = datos.load_alloys()
    ladle_records = _ladle_records(ladles)

    return {
        "summary": _build_summary(hist, alloys),
        "materials": _build_materials(hist),
        "monthly_furnace": _build_monthly_furnace(ladle_records),
        "monthly_hornos": _build_monthly_hornos(hist),
        "targets": _build_targets(hist),
        "elements": _build_elements(hist),
        "ce": _build_ce(hist),
        "days": _build_days(hist),
        "durations": _build_durations(hist),
        "cucharas": _build_cucharas(ladle_records),
        "quality_reports": _build_quality(quality_reports),
        "inoculantes": _build_inoculantes(alloys, ladle_records),
        "timeline": _build_timeline(hist, ladle_records),
        "composicion_traccion": _build_composicion_traccion(hist, quality_reports, alloys),
    }
