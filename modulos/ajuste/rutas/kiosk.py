# rutas/kiosk.py -- puerto 1:1 de backend/routers/kiosk.py de ajuste_comp_web. API de la SPA "Pie de Horno"
# que corre la Raspberry Pi en el piso de planta (kiosk.html/kiosk.js) -- ladle/"cucharas" counters,
# materiales por cuchara, inoculación.
#
# Además de /api/kiosk/*, este archivo sirve la página standalone /kiosk.html: a diferencia de TODAS las
# demás pantallas de este módulo (que son VISTAS.* dentro del shell del núcleo), esta corre a pantalla
# completa en una Raspberry Pi táctil sin lugar para el menú normal -- es una página HTML propia, sin
# relación con index.html del núcleo. kiosk.js/kiosk.css viven en frontend/ como cualquier otro archivo
# estático del módulo (nucleo ya los sirve en /static/ajuste/kiosk.js), pero la PÁGINA en sí tiene que
# quedar en la raíz /kiosk.html -- es la URL que rutas/pie_horno.py::local_url ya devuelve y la que el
# operario escribe en el navegador de la Raspberry.
from datetime import datetime
from pathlib import Path

from fastapi import APIRouter, Body, Depends, HTTPException
from fastapi.responses import FileResponse

from .. import datos
from .. import dispositivos as devices
from ..ws import hub
from .calidad import _family_for_material, _load_final_catalog

router = APIRouter(tags=["kiosk"])
api_router = APIRouter(prefix="/api/kiosk", tags=["kiosk"])

_KIOSK_HTML = Path(__file__).resolve().parent.parent / "frontend" / "kiosk.html"

MAX_CUCHARAS_MATERIALS = 200
MAX_CUCHARAS_COUNT = 9999


class CucharasContextError(ValueError):
    pass


@router.get("/kiosk.html", include_in_schema=False)
def kiosk_page():
    """Página standalone (no pasa por devices.* -- servir el HTML es público, igual que lo era con
    StaticFiles en la app vieja; las llamadas a la API que esta página hace después sí van protegidas)."""
    return FileResponse(_KIOSK_HTML, media_type="text/html")


# ---------- helpers: materiales finales validos para la base/objetivo actual ----------

def _ladle_material_options(material_objetivo):
    target = str(material_objetivo or "").strip()
    if not target:
        return []
    _, base_to_materials, _, _ = _load_final_catalog()
    all_mats = list(base_to_materials.get(target, []))
    config = datos.load_cucharas_base_config(target)
    if not config:
        return all_mats
    return [m for m in all_mats if config.get(m, True)]


def _family_for_material_objetivo(material_objetivo):
    target = str(material_objetivo or "").strip()
    if not target:
        return ""
    final_materials, base_to_materials, _, _ = _load_final_catalog()
    materials = base_to_materials.get(target, [])
    return _family_for_material(final_materials, materials[0]) if materials else ""


# ---------- helpers: eventos de cucharas ----------
# Cada +1/-1 de cuchara queda registrado como un evento individual con su timestamp; el conteo visible es
# simplemente la cantidad de eventos. Esto es lo que permite después calcular estadísticas (primera/última
# cuchara, duración) sin guardar un número "pelado".

def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _event_list(raw):
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        saved_at = str((item.get("saved_at", "") if isinstance(item, dict) else item) or "")
        if saved_at:
            out.append({"saved_at": saved_at})
    return out


def _counts_from_events(events, valid_materials=None):
    if not isinstance(events, dict):
        return {}
    valid = set(valid_materials or [])
    return {
        str(code).strip(): len(_event_list(values))
        for code, values in events.items()
        if str(code).strip() and (not valid or str(code).strip() in valid)
    }


def _normalize_events_for_counts(events, counts, fallback_time):
    normalized = {}
    for code, qty in (counts or {}).items():
        key = str(code or "").strip()
        if not key:
            continue
        try:
            count = max(0, int(qty))
        except Exception:
            count = 0
        existing = _event_list((events or {}).get(key, []))
        if len(existing) > count:
            existing = existing[:count]
        while len(existing) < count:
            existing.append({"saved_at": fallback_time or _now_iso()})
        normalized[key] = existing
    return normalized


def _parse_iso(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _duration_label(seconds):
    try:
        total = max(0, int(seconds))
    except Exception:
        total = 0
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _statistics_from_events(events, materials):
    rows = []
    all_times = []
    for code in materials:
        items = _event_list((events or {}).get(code, []))
        parsed = [dt for dt in (_parse_iso(item.get("saved_at")) for item in items) if dt is not None]
        first = min(parsed).isoformat(timespec="seconds") if parsed else ""
        last = max(parsed).isoformat(timespec="seconds") if parsed else ""
        duration_seconds = int((max(parsed) - min(parsed)).total_seconds()) if len(parsed) >= 2 else 0
        all_times.extend(parsed)
        rows.append({
            "material_final": code, "total": len(items),
            "first_saved_at": first, "last_saved_at": last,
            "duration_seconds": duration_seconds,
            "duration_label": _duration_label(duration_seconds) if len(parsed) >= 2 else "",
        })
    total_duration = int((max(all_times) - min(all_times)).total_seconds()) if len(all_times) >= 2 else 0
    return {
        "rows": rows,
        "total_cucharas": sum(row["total"] for row in rows),
        "first_saved_at": min(all_times).isoformat(timespec="seconds") if all_times else "",
        "last_saved_at": max(all_times).isoformat(timespec="seconds") if all_times else "",
        "duration_seconds": total_duration,
        "duration_label": _duration_label(total_duration) if len(all_times) >= 2 else "",
    }


def _empty_ladles_current():
    return {"colada": "", "material_objetivo": "", "counts": {}, "events": {}}


def _normalize_ladles_state(state):
    base = {"updated_at": None, "current": _empty_ladles_current(), "history_by_colada": {}}
    if isinstance(state, dict):
        base.update(state)
    current = base.get("current", {})
    if not isinstance(current, dict):
        current = {}
    base["current"] = {
        "colada": str(current.get("colada", "")).strip(),
        "material_objetivo": str(current.get("material_objetivo", "")).strip(),
        "counts": current.get("counts", {}) if isinstance(current.get("counts", {}), dict) else {},
        "events": current.get("events", {}) if isinstance(current.get("events", {}), dict) else {},
    }
    if not isinstance(base.get("history_by_colada"), dict):
        base["history_by_colada"] = {}
    return base


def _host_context():
    """Colada/material objetivo actuales -- leídos de furnace_state (ya lo mantiene actualizado
    rutas/ajuste.py::_publish_furnace_context/_publish_furnace_snapshot) en vez de un payload que el
    cliente manda."""
    furnace = datos.load_furnace_state()
    ajuste = furnace.get("ajuste", {}) if isinstance(furnace, dict) else {}
    if not isinstance(ajuste, dict):
        ajuste = {}
    return {
        "colada": str(ajuste.get("colada", "") or "").strip(),
        "material_objetivo": str(ajuste.get("material_objetivo", "") or "").strip(),
    }, furnace


def _sync_ladles_current_with_host(state):
    out = _normalize_ladles_state(state)
    current = out["current"]
    host_ctx, _ = _host_context()
    changed = False
    if not current.get("colada") and host_ctx["colada"]:
        current["colada"] = host_ctx["colada"]
        changed = True
    if not current.get("material_objetivo") and host_ctx["material_objetivo"]:
        current["material_objetivo"] = host_ctx["material_objetivo"]
        changed = True
    out["current"] = current
    return out, changed


def _cucharas_payload_from_state(state):
    normalized = _normalize_ladles_state(state)
    current = normalized["current"]
    target = current.get("material_objetivo", "")
    colada = current.get("colada", "")
    materials = _ladle_material_options(target)
    events = _normalize_events_for_counts(current.get("events", {}), current.get("counts", {}), normalized.get("updated_at") or _now_iso())
    history_by_colada = normalized.get("history_by_colada", {})
    saved_record = history_by_colada.get(colada, {}) if isinstance(history_by_colada, dict) else {}
    if isinstance(saved_record, dict):
        saved_count = sum(_counts_from_events(saved_record.get("events", {}), materials).values())
        last_saved_at = str(saved_record.get("updated_at", "") or "")
    else:
        saved_count = 0
        last_saved_at = ""
    rows = []
    total = 0
    for code in materials:
        count = len(events.get(code, []))
        total += count
        rows.append({"material_final": code, "cantidad": count})
    return {
        "colada": colada,
        "material_objetivo": target,
        "rows": rows,
        "total_cucharas": total,
        "updated_at": normalized.get("updated_at"),
        "statistics": _statistics_from_events(events, materials),
        "saved_count": saved_count,
        "already_saved": saved_count > 0,
        "last_saved_at": last_saved_at,
        "family": _family_for_material_objetivo(target),
    }


def _persist_cucharas_events(state, current, target, valid_materials, events, saved_at):
    clean_counts = _counts_from_events(events, valid_materials)
    history_by_colada = state.get("history_by_colada", {})
    if not isinstance(history_by_colada, dict):
        history_by_colada = {}
    colada_key = str(current.get("colada", "")).strip()
    if colada_key:
        history_by_colada[colada_key] = {
            "updated_at": saved_at, "colada": colada_key, "material_objetivo": target,
            "counts": clean_counts, "events": events,
            "statistics": _statistics_from_events(events, sorted(valid_materials)),
        }
    state["history_by_colada"] = history_by_colada

    host_ctx, _ = _host_context()
    current["counts"] = clean_counts
    current["events"] = events
    if host_ctx["colada"] and (host_ctx["colada"] != current.get("colada") or host_ctx["material_objetivo"] != current.get("material_objetivo")):
        current = {"colada": host_ctx["colada"], "material_objetivo": host_ctx["material_objetivo"], "counts": {}, "events": {}}
    state["current"] = current
    state["updated_at"] = saved_at
    datos.save_ladles_state(state)
    return _cucharas_payload_from_state(state)


# ---------- helpers: snapshot combinado (furnace + cucharas + carbomax pendiente) ----------

def _furnace_rows_nonzero(rows):
    return [r for r in (rows or []) if isinstance(r, dict) and abs(float(r.get("valor", 0) or 0)) > 1e-12]


def _carbomax_recent_payload():
    """Lista de últimos análisis de Carbono detectados (ver ..carbomax_auto._append_recent_record) para la
    pantalla de Pie de Horno -- misma lista que ve la pantalla de Ajuste. El kiosk solo la muestra; "usar"
    una fila pega al mismo endpoint que la pantalla de Ajuste (/api/ajuste/carbomax-auto/use-record)."""
    st = datos.load_ajuste_session()
    return list(st.get("carbomax_recent_records") or [])


def build_kiosk_snapshot(device):
    furnace = datos.load_furnace_state()
    ladles, changed = _sync_ladles_current_with_host(datos.load_ladles_state())
    if changed:
        datos.save_ladles_state(ladles)
    ajuste = furnace.get("ajuste", {}) if isinstance(furnace, dict) else {}
    if not isinstance(ajuste, dict):
        ajuste = {}
    role = str((device or {}).get("role") or "viewer")
    can_edit = role == "editor"
    return {
        "updated_at": furnace.get("updated_at"),
        "ajuste": {
            **ajuste,
            "composicion_actual": _furnace_rows_nonzero(ajuste.get("composicion_actual")),
            "composicion_estimada": _furnace_rows_nonzero(ajuste.get("composicion_estimada")),
        },
        "cucharas": _cucharas_payload_from_state(ladles),
        "carbomax_recent": _carbomax_recent_payload(),
        "permissions": {"role": role, "can_edit_cucharas": can_edit, "can_edit_ajuste": can_edit},
    }


# ---------- endpoints ----------

# Solo lectura: además del kiosco (dispositivo aprobado, sin login) la lee el contador de cucharas de la pestaña Ajuste,
# donde el que entra es un usuario logueado desde una PC que no tiene por qué estar aprobada -- por eso require_acceso
# y no require_approved_device. El kiosco no manda sesión, así que para él sigue valiendo la aprobación del dispositivo.
@api_router.get("/snapshot")
def get_snapshot(device: dict = Depends(devices.require_acceso)):
    return build_kiosk_snapshot(device)


@api_router.post("/materiales")
async def save_materiales(payload: dict = Body(...), device: dict = Depends(devices.require_editor_device)):
    """Confirmar cuánto de cada material del plan de Ajuste va efectivamente a ESTE horno
    (porcentaje_horno)."""
    state = datos.load_furnace_state()
    ajuste = state.get("ajuste", {}) if isinstance(state, dict) else {}
    if not isinstance(ajuste, dict):
        ajuste = {}
    current_rows = [r for r in (ajuste.get("materiales") or []) if isinstance(r, dict) and str(r.get("nombre", "")).strip() and float(r.get("kg", 0) or 0) > 0]
    if not current_rows:
        return build_kiosk_snapshot(device)

    def _clamp_pct(value, default=100):
        try:
            pct = int(round(float(value)))
        except Exception:
            pct = int(default)
        return max(0, min(100, pct))

    pct_map = {}
    for row in payload.get("rows") or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("nombre", "") or "").strip()
        if name:
            pct_map[name] = _clamp_pct(row.get("porcentaje_horno", 100))

    general_pct = payload.get("general_pct")
    shared_pct = None if general_pct is None else _clamp_pct(general_pct)
    updated_rows = []
    for row in current_rows:
        name = str(row.get("nombre", "")).strip()
        pct = _clamp_pct(pct_map.get(name, shared_pct if shared_pct is not None else row.get("porcentaje_horno", 100)))
        kg = round(float(row.get("kg", 0) or 0), 3)
        updated_rows.append({"nombre": name, "kg": kg, "porcentaje_horno": pct, "kg_horno": round(kg * pct / 100.0, 3)})

    confirmed_at = _now_iso()
    ajuste["materiales"] = updated_rows
    ajuste["porcentaje_general_horno"] = shared_pct if shared_pct is not None else _clamp_pct(ajuste.get("porcentaje_general_horno", 100))
    ajuste["materiales_confirmados"] = True
    ajuste["confirmado_at"] = confirmed_at
    state["updated_at"] = confirmed_at
    state["ajuste"] = ajuste
    datos.save_furnace_state(state)
    await hub.broadcast("furnace", {"type": "furnace_changed"})
    return build_kiosk_snapshot(device)


@api_router.post("/cucharas")
async def cucharas_action(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    """start/save/restore_previous/delta: los 4 caminos de escritura del conteo de cucharas."""
    action = str(payload.get("action", "") or "").strip().lower()

    if action == "start":
        host_ctx, _furnace = _host_context()
        colada, target = host_ctx["colada"], host_ctx["material_objetivo"]
        if not colada or not target:
            raise HTTPException(status_code=409, detail={
                "error": "missing_ajuste_context",
                "message": "Inicia la sesion en Ajuste con numero de colada y material objetivo.",
            })
        state, _changed = _sync_ladles_current_with_host(datos.load_ladles_state())
        current = state.get("current", {})
        valid_materials = sorted(_ladle_material_options(target))
        same_colada = str(current.get("colada", "")).strip() == colada
        if same_colada:
            existing_counts = current.get("counts", {})
            existing_events = current.get("events", {})
            state["current"] = {
                "colada": colada, "material_objetivo": target,
                "counts": {c: existing_counts.get(c, 0) for c in valid_materials},
                "events": {c: list(existing_events.get(c, [])) for c in valid_materials},
            }
        else:
            state["current"] = {
                "colada": colada, "material_objetivo": target,
                "counts": {c: 0 for c in valid_materials},
                "events": {c: [] for c in valid_materials},
            }
            history_by_colada = state.get("history_by_colada", {})
            if isinstance(history_by_colada, dict):
                history_by_colada.pop(colada, None)
        state["updated_at"] = _now_iso()
        datos.save_ladles_state(state)
        await hub.broadcast("kiosk", {"type": "kiosk_changed"})
        return {"ok": True, "cucharas": _cucharas_payload_from_state(state)}

    if action == "save":
        state, _changed = _sync_ladles_current_with_host(datos.load_ladles_state())
        current = state.get("current", {})
        target = str(current.get("material_objetivo", "") or "").strip()
        valid_materials = set(_ladle_material_options(target))
        saved_at = _now_iso()
        events = _normalize_events_for_counts(current.get("events", {}), current.get("counts", {}), state.get("updated_at") or saved_at)
        result = _persist_cucharas_events(state, current, target, valid_materials, events, saved_at)
        await hub.broadcast("kiosk", {"type": "kiosk_changed"})
        return {"ok": True, "cucharas": result}

    if action == "restore_previous":
        saved_at = _now_iso()
        counts = payload.get("previous_counts") or {}
        valid_counts = {}
        for k, v in (counts.items() if isinstance(counts, dict) else []):
            key = str(k or "").strip()
            if key:
                try:
                    valid_counts[key] = max(0, int(v))
                except Exception:
                    valid_counts[key] = 0
        events = _normalize_events_for_counts({}, valid_counts, saved_at)
        state = _normalize_ladles_state(datos.load_ladles_state())
        state["current"] = {
            "colada": str(payload.get("previous_colada", "") or "").strip(),
            "material_objetivo": str(payload.get("previous_material", "") or "").strip(),
            "counts": valid_counts, "events": events,
        }
        state["updated_at"] = saved_at
        datos.save_ladles_state(state)
        await hub.broadcast("kiosk", {"type": "kiosk_changed"})
        return {"ok": True, "cucharas": _cucharas_payload_from_state(state)}

    if "delta" in payload:
        material = str(payload.get("material_final") or payload.get("material") or "").strip()
        try:
            delta = max(-100, min(100, int(payload.get("delta", 0))))
        except Exception:
            delta = 0
        if not material or delta == 0:
            raise HTTPException(status_code=400, detail={"error": "invalid_delta"})
        state, _changed = _sync_ladles_current_with_host(datos.load_ladles_state())
        colada_override = str(payload.get("colada_override", "") or "").strip()
        if colada_override:
            current_colada = str(state["current"].get("colada", "") or "").strip()
            if colada_override != current_colada:
                history = state.get("history_by_colada", {})
                if colada_override in history:
                    hist_rec = history[colada_override]
                    state["current"] = {
                        "colada": colada_override,
                        "material_objetivo": str(hist_rec.get("material_objetivo", "") or ""),
                        "counts": dict(hist_rec.get("counts", {})),
                        "events": {k: list(v) for k, v in hist_rec.get("events", {}).items()},
                    }
                else:
                    state["current"]["colada"] = colada_override
        current = state["current"]
        target = current.get("material_objetivo", "")
        valid_materials = set(_ladle_material_options(target))
        if material not in valid_materials:
            return {"ok": True, "cucharas": _cucharas_payload_from_state(state)}
        saved_at = _now_iso()
        events = _normalize_events_for_counts(current.get("events", {}), current.get("counts", {}), state.get("updated_at") or saved_at)
        current_events = events.setdefault(material, [])
        if delta > 0:
            for _i in range(delta):
                current_events.append({"saved_at": saved_at})
        else:
            del current_events[max(0, len(current_events) + delta):]
        result = _persist_cucharas_events(state, current, target, valid_materials, events, saved_at)
        await hub.broadcast("kiosk", {"type": "kiosk_changed"})
        return {"ok": True, "cucharas": result}

    raise HTTPException(status_code=409, detail={
        "error": "snapshot_counts_disabled",
        "message": "Usa delta/start/save. No se aceptan snapshots completos para evitar pisar conteos desde clientes viejos.",
    })


@api_router.get("/inoculaciones")
def get_inoculaciones(_: dict = Depends(devices.require_approved_device)):
    """Procedimiento de inoculación (con overrides por base) resuelto para cada material final."""
    alloys = datos.load_alloys()
    gramos_map = {a.get("nombre", ""): a.get("gramos_cucharin1", 0) or 0 for a in alloys}
    unidad_map = {a.get("nombre", ""): str(a.get("unidad_inoculacion", "") or "cucharín") for a in alloys}
    color_map = {a.get("nombre", ""): a.get("color_inoculacion") or None for a in alloys}
    momentos_cfg = datos.load_inoc_momentos()
    momento_label_map = {m["key"]: m["label"] for m in momentos_cfg}
    momento_idx_map = {m["key"]: i for i, m in enumerate(momentos_cfg)}

    def _build_procedimiento(entries):
        out = []
        for e in entries or []:
            if isinstance(e, str):
                nombre, cant, momento = e, 1, "horno"
            elif isinstance(e, dict):
                nombre = e.get("nombre", "")
                try:
                    cant = float(e.get("cantidad_dosis", 1) or 1)
                except Exception:
                    cant = 1.0
                momento = str(e.get("momento", "horno") or "horno")
            else:
                continue
            g = gramos_map.get(nombre, 0)
            out.append({
                "nombre": nombre, "cant": cant, "gramos": g,
                "total": round(g * cant, 2) if g and cant else None,
                "momento": momento, "momento_label": momento_label_map.get(momento, momento),
                "momento_idx": momento_idx_map.get(momento, 999),
                "unidad": unidad_map.get(nombre, "cucharín"), "color": color_map.get(nombre),
            })
        return out

    result = []
    for a in alloys:
        meta = a.get("inoculacion_meta", {})
        if not isinstance(meta, dict):
            continue
        default_inoc = datos.resolve_inoc_protocol(meta)
        por_base = meta.get("por_base", {}) if isinstance(meta.get("por_base"), dict) else {}
        if not default_inoc and not por_base:
            continue
        calidad_meta = a.get("calidad_meta", {}) if isinstance(a.get("calidad_meta"), dict) else {}
        all_bases = [str(b).strip() for b in (calidad_meta.get("bases") or []) if str(b).strip()]
        entry = {"nombre": a.get("nombre", ""), "bases": all_bases, "procedimiento": _build_procedimiento(default_inoc)}
        if por_base:
            entry["procedimiento_por_base"] = {
                base: _build_procedimiento(datos.resolve_inoc_protocol(meta, base=base)) for base in por_base
            }
        result.append(entry)
    return {"ok": True, "inoculaciones": result}


@api_router.get("/cucharas-base-config")
def get_cucharas_base_config(base: str, _: dict = Depends(devices.require_approved_device)):
    config = datos.load_cucharas_base_config(base)
    return {"base": base, "config": config}


@api_router.post("/cucharas-base-config")
def set_cucharas_base_config(body: dict = Body(...), _: dict = Depends(devices.require_approved_device)):
    base = str(body.get("base", "")).strip()
    material_final = str(body.get("material_final", "")).strip()
    active = bool(body.get("active", True))
    if not base or not material_final:
        raise HTTPException(status_code=400, detail="base y material_final requeridos")
    datos.save_cucharas_base_config(base, material_final, active)
    return {"ok": True}


router.include_router(api_router)
