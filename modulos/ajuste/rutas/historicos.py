# rutas/historicos.py -- puerto 1:1 de backend/routers/historicos.py de ajuste_comp_web. Cada colada guardada
# por Ajuste (datos.append_history) es una "sesión". Lista + detalle de sesión (ajustes, cálculos, lecturas de
# Carbono ya guardadas en la sesión, cucharas cargadas), editar colada/objetivo, marcar "sinterizado" (reinicia
# el contador de crisol), eliminar sesión, editar/eliminar un ajuste puntual (recalcula la composición vía
# calc.estimate_composition, mismo motor que Ajuste), exportar la composición final a CSV, exportar todo el
# historial a JSON.
#
# Cucharas: los datos los sigue escribiendo el kiosko físico (Pie de Horno/Raspberry) -- este dominio solo
# necesita poder LEERLOS (y opcionalmente corregirlos a mano) para mostrarlos en el detalle de sesión.
#
# QUEDA PENDIENTE (fases más adelante, no bloquean este corte): análisis térmico adjunto, generar informe de
# calidad desde una sesión, exportar a PDF (el CSV cubre el mismo contenido por ahora).
#
# OJO CON LOS ÍNDICES (mismo criterio que usa datos.py en toda la app): el "idx" de una sesión en las rutas
# /sessions/{idx} es su POSICIÓN REAL en la lista que devuelve datos.load_history() (ORDER BY id), no una
# posición visual -- el frontend nunca debe reordenar la lista y asumir que el idx sigue siendo válido.
import csv
import io
import json
import re
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import StreamingResponse

from .. import datos
from .. import dispositivos as devices
from .. import calc
from ..ce import ce_from_percent
from ..config import ELEMENTS
from ..utils import to_float

router = APIRouter(prefix="/api/historicos", tags=["historicos"])


def _alloy_by_name(alloys, name, prefer_type=None, require_adjust=False):
    items = [a for a in alloys if str(a.get("nombre", "")).strip() == str(name).strip()]
    if require_adjust:
        for a in items:
            if bool(a.get("ajuste", False)) and a.get("tipo", "") != "Aleación final":
                return a
        for a in items:
            if a.get("tipo", "") != "Aleación final":
                return a
    if prefer_type:
        for a in items:
            if a.get("tipo", "") == prefer_type:
                return a
    return items[0] if items else None


def _objective_comp(alloys, session):
    a = _alloy_by_name(alloys, session.get("objetivo", ""), prefer_type="Aleación propia")
    return (a or {}).get("composicion", {}) or {}


# ---------- Cucharas (solo lectura/corrección manual -- las escribe el kiosko) ----------

_COLADA_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})\s*-\s*(.+?)\s*$")


def _split_colada(s):
    m = _COLADA_RE.match(s or "")
    if not m:
        return ("", "", s or "")
    return (m.group(1), m.group(2), m.group(3))


def _ladle_colada_key(session):
    """history_by_colada usa como clave el número de colada normalizado "NNNN /AA" (sin el material), no el
    string completo de session["colada"] (que incluye el material, ej. "0004 /25 - FC200")."""
    idn, yy, _ = _split_colada(session.get("colada", ""))
    if not idn:
        return str(session.get("colada", "")).strip()
    return f"{int(idn):04d} /{str(yy).zfill(2)}"


def _duration_label(seconds):
    total = max(0, int(seconds or 0))
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _ladle_entry_for_session(ladles_state, session):
    """Normaliza la entrada de cucharas de esta colada a una forma común, soportando tanto el formato viejo
    (lista de snapshots) como el actual (un dict con counts/events/statistics ya resueltos)."""
    key = _ladle_colada_key(session)
    history_by_colada = ladles_state.get("history_by_colada", {}) if isinstance(ladles_state, dict) else {}
    entries = history_by_colada.get(key, [])

    if isinstance(entries, list):
        if not entries:
            return None
        latest = entries[-1] if isinstance(entries[-1], dict) else {}
        rows = latest.get("rows", []) if isinstance(latest.get("rows", []), list) else []
        return {
            "saved_at": latest.get("saved_at", ""),
            "material_objetivo": latest.get("material_objetivo", ""),
            "rows": rows,
            "events": {},
            "total_cucharas": latest.get("total_cucharas", sum(int(row.get("cantidad", 0) or 0) for row in rows)),
            "statistics": {},
        }
    if not isinstance(entries, dict):
        return None
    stats = entries.get("statistics", {}) if isinstance(entries.get("statistics", {}), dict) else {}
    stat_rows = stats.get("rows", []) if isinstance(stats.get("rows", []), list) else []
    if stat_rows:
        rows = [{"material_final": r.get("material_final", ""), "cantidad": r.get("total", 0)}
                for r in stat_rows if isinstance(r, dict)]
    else:
        counts = entries.get("counts", {}) if isinstance(entries.get("counts", {}), dict) else {}
        rows = [{"material_final": k, "cantidad": v} for k, v in sorted(counts.items())]
    return {
        "saved_at": entries.get("updated_at", ""),
        "material_objetivo": entries.get("material_objetivo", ""),
        "rows": rows,
        "events": entries.get("events", {}) if isinstance(entries.get("events", {}), dict) else {},
        "total_cucharas": stats.get("total_cucharas", sum(int(r.get("cantidad", 0) or 0) for r in rows)),
        "statistics": stats,
    }


def _all_ladle_events(entry):
    events = entry.get("events", {}) if isinstance(entry, dict) else {}
    out = []
    if not isinstance(events, dict):
        return out
    for material, raw in events.items():
        if not isinstance(raw, list):
            continue
        for item in raw:
            value = str((item.get("saved_at", "") if isinstance(item, dict) else item) or "").strip()
            if value:
                out.append({"material": str(material), "time": value})
    return sorted(out, key=lambda row: row.get("time", ""))


def _avg_ladle_interval_seconds(events):
    parsed = []
    for event in events or []:
        try:
            parsed.append(datetime.fromisoformat(str(event.get("time", ""))))
        except Exception:
            pass
    parsed.sort()
    if len(parsed) < 2:
        return None
    total_seconds = (parsed[-1] - parsed[0]).total_seconds()
    return total_seconds / max(1, len(parsed) - 1)


def _ladle_summary(ladles_state, session):
    entry = _ladle_entry_for_session(ladles_state, session)
    if not entry:
        return {"has_data": False, "rows": [], "events": [], "total_cucharas": 0,
                "first_saved_at": "", "last_saved_at": "", "duration_label": "", "avg_interval_label": ""}
    all_events = _all_ladle_events(entry)
    stats = entry.get("statistics", {}) or {}
    avg_seconds = _avg_ladle_interval_seconds(all_events)
    rows = [r for r in (entry.get("rows") or []) if int(r.get("cantidad", 0) or 0) > 0]
    return {
        "has_data": True,
        "material_objetivo": entry.get("material_objetivo", ""),
        "rows": rows,
        "events": all_events,
        "total_cucharas": entry.get("total_cucharas", 0),
        "first_saved_at": stats.get("first_saved_at", ""),
        "last_saved_at": stats.get("last_saved_at", ""),
        "duration_label": stats.get("duration_label") or _duration_label(stats.get("duration_seconds", 0)),
        "avg_interval_label": _duration_label(avg_seconds) if avg_seconds is not None else "",
    }


def _crisol_displays(hist):
    """Contador de coladas desde el último sinterizado (revestimiento nuevo del horno) -- no es un campo
    guardado, se recalcula recorriendo TODO el historial en orden y reiniciando en 1 cada vez que aparece una
    colada marcada primer_sinterizado."""
    counter = 0
    out = []
    for s in hist:
        if s.get("primer_sinterizado"):
            counter = 1
        else:
            counter += 1
        out.append(f"[S] {counter}" if s.get("primer_sinterizado") else str(counter))
    return out


def _coladas_con_traccion_lab():
    """Números de colada (clave normalizada "NNNN /AA", igual que _ladle_colada_key) que tienen AL MENOS UN
    informe de Calidad con "Tracción real Lab" cargada -- para el emoji 🔬 de list_sessions."""
    keys = set()
    for r in datos.load_quality_reports() or []:
        if not isinstance(r, dict) or not str(r.get("traccion_real", "") or "").strip():
            continue
        lote = str(r.get("lote", "") or "").strip()
        if lote:
            keys.add(datos.normalize_colada_key(lote))
    return keys


def _coladas_con_informe_creado():
    """Números de colada que tienen AL MENOS UN informe de Calidad ACTIVO (no archivado) -- para el icono 📋."""
    keys = set()
    for r in datos.load_quality_reports() or []:
        if not isinstance(r, dict) or r.get("archived"):
            continue
        lote = str(r.get("lote", "") or "").strip()
        if lote:
            keys.add(datos.normalize_colada_key(lote))
    return keys


def _coladas_con_informe_archivado():
    """Números de colada que tienen AL MENOS UN informe de Calidad ARCHIVADO -- para el icono 🗄️."""
    keys = set()
    for r in datos.load_quality_reports() or []:
        if not isinstance(r, dict) or not r.get("archived"):
            continue
        lote = str(r.get("lote", "") or "").strip()
        if lote:
            keys.add(datos.normalize_colada_key(lote))
    return keys


def _ensayos_reales_para_colada(colada_key):
    """Informes de Calidad de esta colada (join por lote normalizado) que tienen AL MENOS UNO de los 4
    "ensayos reales" cargado -- para la sub-pestaña "Ensayos" del detalle."""
    out = []
    for r in datos.load_quality_reports() or []:
        if not isinstance(r, dict):
            continue
        lote = str(r.get("lote", "") or "").strip()
        if not lote or datos.normalize_colada_key(lote) != colada_key:
            continue
        traccion_real = str(r.get("traccion_real", "") or "").strip()
        estiramiento_real = str(r.get("estiramiento_real", "") or "").strip()
        tension_real_lim_prop = str(r.get("tension_real_lim_prop", "") or "").strip()
        mg_disuelto = str(r.get("mg_disuelto", "") or "").strip()
        if not (traccion_real or estiramiento_real or tension_real_lim_prop or mg_disuelto):
            continue
        out.append({
            "material": r.get("material", ""),
            "traccion_real": traccion_real,
            "estiramiento_real": estiramiento_real,
            "tension_real_lim_prop": tension_real_lim_prop,
            "mg_disuelto": mg_disuelto,
        })
    out.sort(key=lambda e: str(e["material"]))
    return out


def _summary(session):
    return {
        "objetivo": session.get("objetivo", ""),
        "auto_saved": bool(session.get("auto_saved")),
        "started_at": session.get("started_at", ""),
        "ended_at": session.get("ended_at", ""),
        "n_ajustes": len(session.get("ajustes", []) or []),
        "n_calculos": len(session.get("calculos", []) or []),
        "n_carbono": len(session.get("carbono", []) or []),
        "n_spectro": len(session.get("spectro_resultados", []) or []),
    }


@router.get("/sessions")
def list_sessions(_: dict = Depends(devices.require_approved_device)):
    hist = datos.load_history()
    crisol = _crisol_displays(hist)
    traccion_lab_keys = _coladas_con_traccion_lab()
    informe_creado_keys = _coladas_con_informe_creado()
    informe_archivado_keys = _coladas_con_informe_archivado()
    out = []
    for idx, s in enumerate(hist):
        colada_key = _ladle_colada_key(s)
        out.append({
            "idx": idx,
            "colada": s.get("colada", ""),
            "primer_sinterizado": bool(s.get("primer_sinterizado")),
            "crisol": crisol[idx],
            "has_traccion_lab": colada_key in traccion_lab_keys,
            "tiene_informe_creado": colada_key in informe_creado_keys,
            "tiene_informe_archivado": colada_key in informe_archivado_keys,
            **_summary(s),
        })
    out.reverse()  # más reciente primero, igual que el Treeview del original
    return {"sessions": out}


@router.get("/sessions/{idx}")
def get_session(idx: int, _: dict = Depends(devices.require_approved_device)):
    hist = datos.load_history()
    if idx < 0 or idx >= len(hist):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    s = hist[idx]
    ladles_state = datos.load_ladles_state()
    return {
        "idx": idx,
        "colada": s.get("colada", ""),
        "primer_sinterizado": bool(s.get("primer_sinterizado")),
        **_summary(s),
        "ensayos": _ensayos_reales_para_colada(_ladle_colada_key(s)),
        "ajustes": s.get("ajustes", []) or [],
        "calculos": s.get("calculos", []) or [],
        "carbono": s.get("carbono", []) or [],
        "spectro_resultados": s.get("spectro_resultados", []) or [],
        "cucharas": _ladle_summary(ladles_state, s),
    }


@router.put("/sessions/{idx}/cucharas")
def edit_cucharas(idx: int, payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    """Cuerpo: {"counts": {material: cantidad, ...}}. Corrige a mano el conteo de cucharas de esta colada
    (solo permite ajustar materiales que YA tenían registro; no crea columnas de material nuevas). Reconstruye
    "events" recortando/completando con la hora actual para que total(events) siga coincidiendo con el conteo
    nuevo, y recalcula "statistics" (con duration_label incluido)."""
    hist = datos.load_history()
    if idx < 0 or idx >= len(hist):
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    session = hist[idx]
    colada_key = _ladle_colada_key(session)
    ladles_state = datos.load_ladles_state()
    entry = _ladle_entry_for_session(ladles_state, session)
    if not entry or not entry.get("rows"):
        raise HTTPException(status_code=400, detail={"error": "sin_registro_de_cucharas"})

    new_counts = {}
    for mat, qty in (payload.get("counts") or {}).items():
        try:
            new_counts[str(mat)] = max(0, int(qty))
        except (TypeError, ValueError):
            continue

    history_by_colada = ladles_state.get("history_by_colada", {}) if isinstance(ladles_state.get("history_by_colada"), dict) else {}
    old = history_by_colada.get(colada_key, {})
    if isinstance(old, list):
        old = {}
    old_events = old.get("events", {}) if isinstance(old, dict) else {}

    saved_at = datetime.now().isoformat(timespec="seconds")
    new_events = {}
    for mat, qty in new_counts.items():
        existing = [e for e in (old_events.get(mat) or []) if isinstance(e, dict) and e.get("saved_at")]
        if len(existing) > qty:
            existing = existing[:qty]
        while len(existing) < qty:
            existing.append({"saved_at": saved_at})
        if existing:
            new_events[mat] = existing

    stat_rows = []
    all_times = []
    for mat, evts in new_events.items():
        parsed = []
        for e in evts:
            try:
                parsed.append(datetime.fromisoformat(e.get("saved_at", "")))
            except Exception:
                pass
        first = min(parsed).isoformat(timespec="seconds") if parsed else ""
        last = max(parsed).isoformat(timespec="seconds") if parsed else ""
        dur = int((max(parsed) - min(parsed)).total_seconds()) if len(parsed) >= 2 else 0
        all_times.extend(parsed)
        stat_rows.append({
            "material_final": mat, "total": len(evts),
            "first_saved_at": first, "last_saved_at": last,
            "duration_seconds": dur, "duration_label": _duration_label(dur) if len(parsed) >= 2 else "",
        })
    total_dur = int((max(all_times) - min(all_times)).total_seconds()) if len(all_times) >= 2 else 0
    statistics = {
        "rows": stat_rows,
        "total_cucharas": sum(new_counts.values()),
        "first_saved_at": min(all_times).isoformat(timespec="seconds") if all_times else "",
        "last_saved_at": max(all_times).isoformat(timespec="seconds") if all_times else "",
        "duration_seconds": total_dur,
        "duration_label": _duration_label(total_dur) if len(all_times) >= 2 else "",
    }

    history_by_colada[colada_key] = {
        "updated_at": saved_at,
        "colada": colada_key,
        "material_objetivo": old.get("material_objetivo", "") if isinstance(old, dict) else "",
        "counts": new_counts,
        "events": new_events,
        "statistics": statistics,
    }
    ladles_state["history_by_colada"] = history_by_colada
    datos.save_ladles_state(ladles_state)
    return {"ok": True, "cucharas": _ladle_summary(ladles_state, session)}


@router.put("/sessions/{idx}")
def edit_session(idx: int, payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    """Edita la colada (formato libre "ID /YY - MATERIAL", igual que el original)."""
    hist = datos.load_history()
    if idx < 0 or idx >= len(hist):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    session = dict(hist[idx])
    if "colada" in payload:
        session["colada"] = str(payload.get("colada", "")).strip()
    try:
        datos.update_session(idx, session)
    except datos.DuplicateColadaError as ex:
        raise HTTPException(status_code=409, detail={"error": "colada_duplicada", "message": str(ex)}) from ex
    return {"ok": True}


@router.post("/sessions/{idx}/toggle-sinterizado")
def toggle_sinterizado(idx: int, _: dict = Depends(devices.require_editor_device)):
    """Marca/desmarca esta colada como el primer horno post-sinterizado. El contador de "crisol" que devuelve
    GET /sessions se reinicia en 1 a partir de esta colada."""
    hist = datos.load_history()
    if idx < 0 or idx >= len(hist):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    session = dict(hist[idx])
    session["primer_sinterizado"] = not bool(session.get("primer_sinterizado"))
    try:
        datos.update_session(idx, session)
    except datos.DuplicateColadaError as ex:
        raise HTTPException(status_code=409, detail={"error": "colada_duplicada", "message": str(ex)}) from ex
    return {"ok": True, "primer_sinterizado": session["primer_sinterizado"]}


@router.delete("/sessions/{idx}")
def remove_session(idx: int, _: dict = Depends(devices.require_editor_device)):
    hist = datos.load_history()
    if idx < 0 or idx >= len(hist):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    datos.delete_session(idx)
    return {"ok": True}


@router.put("/sessions/{idx}/adjustments/{adj_idx}")
def edit_adjustment(idx: int, adj_idx: int, payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    """Cuerpo: {"materiales": {nombre: kg, ...}}. Recalcula "estimado"/"resumen"/"ce_estimado" a partir del
    nuevo plan de materiales (cada nombre tiene que resolver a un material con flag "ajuste"), dejando
    "inicial"/"objetivo_comp" intactos (el punto de partida de ese ajuste no cambia, solo el plan aplicado)."""
    hist = datos.load_history()
    if idx < 0 or idx >= len(hist):
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    ajustes = hist[idx].get("ajustes", []) or []
    if adj_idx < 0 or adj_idx >= len(ajustes):
        raise HTTPException(status_code=404, detail={"error": "adjustment_not_found"})
    adj = ajustes[adj_idx]

    alloys = datos.load_alloys()
    plan_materiales = []
    plan_kg = {}
    for name, kg in (payload.get("materiales") or {}).items():
        kg = to_float(kg)
        if kg <= 0:
            continue
        alloy = _alloy_by_name(alloys, name, require_adjust=True)
        if not alloy:
            raise HTTPException(status_code=400, detail={"error": "material_invalido", "material": name})
        plan_materiales.append({"alloy": alloy, "kg": kg})
        plan_kg[name] = kg

    inicial = adj.get("inicial", {}) or {}
    result = calc.estimate_composition(inicial.get("comp", {}), inicial.get("masa", 0.0), plan_materiales)
    ce_formula = adj.get("ce_formula", "FUNDICION")
    ce_custom = adj.get("ce_custom", {}) or {}
    ce_est = ce_from_percent(result["composicion"], ce_formula, ce_custom)

    new_adj = dict(adj)
    new_adj["estimado"] = {"masa": result["mass"], "comp": result["composicion"]}
    new_adj["materiales"] = plan_kg
    new_adj["resumen"] = "; ".join(f"{k}: {round(v, 3)} kg" for k, v in sorted(plan_kg.items()))
    new_adj["ce_estimado"] = ce_est
    datos.update_adjustment(idx, adj_idx, new_adj)
    return {"ok": True, "estimado": new_adj["estimado"], "ce_estimado": ce_est, "resumen": new_adj["resumen"]}


@router.delete("/sessions/{idx}/adjustments/{adj_idx}")
def remove_adjustment(idx: int, adj_idx: int, _: dict = Depends(devices.require_editor_device)):
    hist = datos.load_history()
    if idx < 0 or idx >= len(hist):
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    ajustes = hist[idx].get("ajustes", []) or []
    if adj_idx < 0 or adj_idx >= len(ajustes):
        raise HTTPException(status_code=404, detail={"error": "adjustment_not_found"})
    datos.delete_adjustment(idx, adj_idx)
    return {"ok": True}


@router.get("/sessions/{idx}/adjustments/{adj_idx}/export.csv")
def export_adjustment_csv(idx: int, adj_idx: int, _: dict = Depends(devices.require_approved_device)):
    """Reporte de composición final de un ajuste puntual (tres secciones: datos generales, composición
    inicial/final/objetivo, materiales aplicados)."""
    hist = datos.load_history()
    if idx < 0 or idx >= len(hist):
        raise HTTPException(status_code=404, detail={"error": "session_not_found"})
    session = hist[idx]
    ajustes = session.get("ajustes", []) or []
    if adj_idx < 0 or adj_idx >= len(ajustes):
        raise HTTPException(status_code=404, detail={"error": "adjustment_not_found"})
    adj = ajustes[adj_idx]

    inicial = adj.get("inicial", {}) or {}
    estimado = adj.get("estimado", {}) or {}
    comp_ini = inicial.get("comp", {}) or {}
    comp_fin = estimado.get("comp", {}) or {}
    comp_obj = adj.get("objetivo_comp", {}) or {}
    if not comp_obj:
        alloys = datos.load_alloys()
        comp_obj = _objective_comp(alloys, session)

    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Composicion quimica final"])
    w.writerows([
        ["Campo", "Valor"],
        ["Colada", session.get("colada", "")],
        ["Objetivo", session.get("objetivo", "") or adj.get("objetivo", "")],
        ["Inicio sesion", session.get("started_at", "")],
        ["Fin sesion", session.get("ended_at", "")],
        ["Ajuste", str(adj_idx + 1)],
        ["Fecha ajuste", adj.get("fecha", "")],
        ["Masa inicial kg", round(to_float(inicial.get("masa", 0)), 3)],
        ["Masa final kg", round(to_float(estimado.get("masa", 0)), 3)],
        ["CE inicial", round(to_float(adj.get("ce_inicial", 0)), 4) if adj.get("ce_inicial", "") != "" else ""],
        ["CE final", round(to_float(adj.get("ce_estimado", 0)), 4) if adj.get("ce_estimado", "") != "" else ""],
        ["CE objetivo", round(to_float(adj.get("ce_objetivo", 0)), 4) if adj.get("ce_objetivo", "") != "" else ""],
        ["Formula CE", adj.get("ce_formula", "")],
    ])
    w.writerow([])
    w.writerow(["Composicion"])
    w.writerow(["Elemento", "Inicial %", "Final %", "Objetivo %", "Delta final-objetivo"])
    any_row = False
    for el in ELEMENTS:
        v_ini, v_fin, v_obj = to_float(comp_ini.get(el, 0)), to_float(comp_fin.get(el, 0)), to_float(comp_obj.get(el, 0))
        if abs(v_ini) > 1e-12 or abs(v_fin) > 1e-12 or abs(v_obj) > 1e-12:
            w.writerow([el, round(v_ini, 4), round(v_fin, 4), round(v_obj, 4), round(v_fin - v_obj, 4)])
            any_row = True
    if not any_row:
        w.writerow(["Sin datos", "", "", "", ""])
    w.writerow([])
    w.writerow(["Materiales aplicados"])
    w.writerow(["Material", "kg"])
    mats = adj.get("materiales", {}) or {}
    for name, kg in sorted(mats.items()):
        w.writerow([name, round(to_float(kg), 3)])
    if not mats:
        w.writerow(["Sin materiales", ""])
    resumen = str(adj.get("resumen", "") or "").strip()
    if resumen:
        w.writerow([])
        w.writerow(["Resumen", resumen])
    w.writerow([])
    w.writerow(["Generado", datetime.now().strftime("%Y-%m-%d %H:%M:%S")])

    filename = f"composicion_final_{session.get('colada', 'colada').replace('/', '-')}_{adj_idx + 1}.csv"
    return StreamingResponse(
        iter(["﻿" + buf.getvalue()]), media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/export.json")
def export_history_json(_: dict = Depends(devices.require_approved_device)):
    hist = datos.load_history()
    return StreamingResponse(
        iter([json.dumps(hist, ensure_ascii=False, indent=2)]),
        media_type="application/json",
        headers={"Content-Disposition": 'attachment; filename="historicos.json"'},
    )
