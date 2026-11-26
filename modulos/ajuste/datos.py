"""Capa de datos del módulo "ajuste" -- puerto de backend/core/storage.py de ajuste_comp_web completo (salvo la
parte de dispositivos, que ya tiene su propio archivo propio, dispositivos.py). Mismas funciones, mismos nombres,
mismo contrato con quien las llama (los routers que se van portando las usan casi copiando y pegando) -- lo que
cambia es CÓMO llegan a la base:

  - nucleo.db.transaccion() (BEGIN IMMEDIATE + reentrante) en vez de un RLock de módulo + conexión nueva por llamada.
    Mismo dato, mejor disciplina de escritura concurrente -- esto es justamente lo que ganaba la app al pasar al
    núcleo (ver nucleo/db.py).
  - Lo que la app vieja guardaba como fila única de la tabla "meta" (settings/thermal_ips/camera_calibrations) o
    como JSON suelto en el home del usuario (inoc_momentos/inoc_units) ahora vive en la tabla "config" del núcleo
    -- mismo key/value, un solo lugar en vez de dos. La migración de datos existentes la hace esquema.migrar().

ADVERTENCIA sobre índices (heredada tal cual de storage.py): update_session()/delete_session()/
update_adjustment()/delete_adjustment() reciben un "index" ENTERO que se resuelve contra "ORDER BY id" (orden de
creación, no el orden en que se muestra en la UI). Quien llama tiene que asegurarse de que ese índice siga siendo
el mismo en el momento de la llamada."""
import datetime
import json
import re

from nucleo import db

COLADA_KEY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})(?:\s*-\s*.*)?\s*$")


class DuplicateColadaError(ValueError):
    """Se lanza al intentar guardar/renombrar una sesión con un número de colada que ya existe (comparando por
    normalize_colada_key, no por texto literal -- "50 /26" y "0050 /26" son la misma colada)."""
    pass


def normalize_colada_key(value):
    """Normaliza "NNNN /YY[- lo que sea]" a una clave canónica "NNNN /YY" con el número siempre en 4 dígitos.
    Si el texto no matchea el patrón esperado, se devuelve tal cual (fallback)."""
    text = str(value or "").strip()
    m = COLADA_KEY_RE.match(text)
    if not m:
        return text
    return f"{int(m.group(1)):04d} /{m.group(2).zfill(2)}"


# ---------- config (settings/thermal_ips/camera_calibrations/inoc_momentos): helpers genéricos ----------

def _config_get(c, clave, default):
    fila = c.execute("SELECT valor FROM config WHERE clave=?", (clave,)).fetchone()
    if fila is None:
        return default
    try:
        return json.loads(fila["valor"])
    except Exception:
        return default


def _config_set(c, clave, valor) -> None:
    c.execute(
        "INSERT INTO config (clave, valor) VALUES (?, ?) ON CONFLICT(clave) DO UPDATE SET valor=excluded.valor",
        (clave, json.dumps(valor, ensure_ascii=False)),
    )


# ---------- Catálogo: aleaciones/materiales (tabla "alloys") ----------

def load_alloys():
    """Lista completa del catálogo, en el orden guardado (columna "position"). Los campos "conocidos" salen de
    columnas propias; cualquier otro campo que el catálogo haya guardado viaja en "extra" como JSON."""
    with db.transaccion() as c:
        rows = c.execute("SELECT * FROM alloys ORDER BY position").fetchall()
        result = []
        for row in rows:
            a = {
                "nombre": row["nombre"], "tipo": row["tipo"],
                "rendimiento": row["rendimiento"], "costo": row["costo"],
                "composicion": json.loads(row["composicion"] or "{}"),
                "limites": json.loads(row["limites"] or "{}"),
                "especiales": json.loads(row["especiales"] or "{}"),
                "ajuste": bool(row["ajuste"]),
            }
            a.update(json.loads(row["extra"] or "{}"))
            result.append(a)
        return result


def save_alloys(alloys):
    """Reemplaza TODO el catálogo de una: borra la tabla entera y reinserta la lista completa en orden (el índice
    de la lista pasa a ser "position"). No hay upsert/merge parcial."""
    alloys = alloys or []
    known = {"nombre", "tipo", "rendimiento", "costo", "composicion", "limites", "especiales", "ajuste"}
    with db.transaccion() as c:
        c.execute("DELETE FROM alloys")
        for i, a in enumerate(alloys):
            if not isinstance(a, dict):
                continue
            extra = {k: v for k, v in a.items() if k not in known}
            c.execute("""
                INSERT INTO alloys (position, nombre, tipo, rendimiento, costo, composicion, limites, especiales,
                                     ajuste, extra)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                i, a.get("nombre", ""), a.get("tipo", ""), a.get("rendimiento", 0), a.get("costo", 0),
                json.dumps(a.get("composicion", {}), ensure_ascii=False),
                json.dumps(a.get("limites", {}), ensure_ascii=False),
                json.dumps(a.get("especiales", {}), ensure_ascii=False),
                1 if a.get("ajuste") else 0, json.dumps(extra, ensure_ascii=False),
            ))


# ---------- Históricos: sesiones de ajuste guardadas (una fila por colada) ----------

def _session_to_row(session):
    return (
        normalize_colada_key(session.get("colada", "")), session.get("colada", ""),
        session.get("objetivo", ""), session.get("started_at", ""), session.get("ended_at", ""),
        json.dumps(session, ensure_ascii=False),
    )


def _get_session_id_at(c, index):
    rows = c.execute("SELECT id FROM sessions ORDER BY id").fetchall()
    return rows[index]["id"] if 0 <= index < len(rows) else None


def load_history():
    """Todas las sesiones guardadas, en orden de creación (mismo orden que usan los índices de
    update_session/delete_session/etc)."""
    with db.transaccion() as c:
        rows = c.execute("SELECT data FROM sessions ORDER BY id").fetchall()
    out = []
    for row in rows:
        try:
            out.append(json.loads(row["data"] or "{}"))
        except Exception:
            pass
    return out


def append_history(session):
    """Guarda una sesión nueva. Tira DuplicateColadaError si ya existe una fila con la misma colada normalizada
    (la tabla además tiene colada_key UNIQUE como segunda línea de defensa a nivel DB)."""
    with db.transaccion() as c:
        key = normalize_colada_key((session or {}).get("colada", ""))
        if key and c.execute("SELECT id FROM sessions WHERE colada_key=?", (key,)).fetchone():
            raise DuplicateColadaError(f"Ya existe una sesion guardada para la colada {key}.")
        c.execute("""
            INSERT INTO sessions (colada_key, colada_raw, objetivo, started_at, ended_at, data)
            VALUES (?,?,?,?,?,?)
        """, _session_to_row(session))


def update_session(index, session_obj):
    """Reemplaza la sesión en la posición `index` (ver advertencia de índices arriba) por `session_obj`
    completo. Vuelve a chequear duplicados de colada, excluyendo la propia fila que se está editando."""
    with db.transaccion() as c:
        row_id = _get_session_id_at(c, index)
        if row_id is None:
            return
        key = normalize_colada_key((session_obj or {}).get("colada", ""))
        if key and c.execute("SELECT id FROM sessions WHERE colada_key=? AND id!=?", (key, row_id)).fetchone():
            raise DuplicateColadaError(f"Ya existe una sesion guardada para la colada {key}.")
        c.execute("""
            UPDATE sessions SET colada_key=?, colada_raw=?, objetivo=?, started_at=?, ended_at=?, data=?
            WHERE id=?
        """, _session_to_row(session_obj) + (row_id,))


def delete_session(index):
    """Borra la sesión en la posición `index` y, en cascada, su registro de cucharas asociado -- una colada
    borrada no debe dejar conteos de cucharas huérfanos dando vueltas."""
    with db.transaccion() as c:
        row_id = _get_session_id_at(c, index)
        if row_id is None:
            return
        row = c.execute("SELECT colada_raw FROM sessions WHERE id=?", (row_id,)).fetchone()
        colada = row["colada_raw"] if row else ""
        c.execute("DELETE FROM sessions WHERE id=?", (row_id,))
    delete_ladles_for_colada(colada)


def update_adjustment(session_index, adj_index, new_adj):
    """Edita UN ajuste puntual dentro de session["ajustes"][adj_index], sin tocar el resto de la sesión."""
    with db.transaccion() as c:
        row_id = _get_session_id_at(c, session_index)
        if row_id is None:
            return
        row = c.execute("SELECT data FROM sessions WHERE id=?", (row_id,)).fetchone()
        session = json.loads(row["data"] or "{}")
        ajustes = session.get("ajustes", [])
        if 0 <= adj_index < len(ajustes):
            ajustes[adj_index] = new_adj
            session["ajustes"] = ajustes
            c.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(session, ensure_ascii=False), row_id))


def delete_adjustment(session_index, adj_index):
    """Como update_adjustment pero borra el ajuste en vez de reemplazarlo."""
    with db.transaccion() as c:
        row_id = _get_session_id_at(c, session_index)
        if row_id is None:
            return
        row = c.execute("SELECT data FROM sessions WHERE id=?", (row_id,)).fetchone()
        session = json.loads(row["data"] or "{}")
        ajustes = session.get("ajustes", [])
        if 0 <= adj_index < len(ajustes):
            del ajustes[adj_index]
            session["ajustes"] = ajustes
            c.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(session, ensure_ascii=False), row_id))


def attach_thermal_analysis(colada, analysis_obj):
    """Vincula un análisis térmico a la sesión de la colada dada (busca POR COLADA, no por índice posicional).
    Devuelve la posición (índice) de la sesión encontrada."""
    key = normalize_colada_key(colada)
    if not key:
        raise ValueError("Colada vacia.")
    with db.transaccion() as c:
        rows = c.execute("SELECT id, data FROM sessions ORDER BY id").fetchall()
        for i, row in enumerate(rows):
            session = json.loads(row["data"] or "{}")
            if normalize_colada_key(session.get("colada", "")) != key:
                continue
            analyses = session.get("thermal_analysis", [])
            if not isinstance(analyses, list):
                analyses = []
            analyses.append(analysis_obj)
            session["thermal_analysis"] = analyses
            c.execute("UPDATE sessions SET data=? WHERE id=?", (json.dumps(session, ensure_ascii=False), row["id"]))
            return i
        raise ValueError(f"No existe una sesion historica para la colada {key}.")


def detach_thermal_analysis(colada, analysis_index):
    """Inverso de attach_thermal_analysis: saca el análisis en la posición `analysis_index` (no borra la curva
    original, solo el vínculo)."""
    key = normalize_colada_key(colada)
    if not key:
        raise ValueError("Colada vacia.")
    with db.transaccion() as c:
        rows = c.execute("SELECT id, data FROM sessions ORDER BY id").fetchall()
        for row in rows:
            session = json.loads(row["data"] or "{}")
            if normalize_colada_key(session.get("colada", "")) != key:
                continue
            analyses = session.get("thermal_analysis", [])
            if not isinstance(analyses, list):
                analyses = []
            if 0 <= analysis_index < len(analyses):
                del analyses[analysis_index]
                session["thermal_analysis"] = analyses
                c.execute("UPDATE sessions SET data=? WHERE id=?",
                          (json.dumps(session, ensure_ascii=False), row["id"]))
            return
        raise ValueError(f"No existe una sesion historica para la colada {key}.")


def set_thermal_analysis_field(colada, source_file, patch):
    """Actualiza campos puntuales de un análisis térmico ya vinculado, identificándolo por colada + source_file
    en vez de por índice."""
    key = normalize_colada_key(colada)
    if not key:
        raise ValueError("Colada vacia.")
    source_file = str(source_file or "").strip()
    if not source_file:
        raise ValueError("Archivo de origen vacio.")
    with db.transaccion() as c:
        rows = c.execute("SELECT id, data FROM sessions ORDER BY id").fetchall()
        for row in rows:
            session = json.loads(row["data"] or "{}")
            if normalize_colada_key(session.get("colada", "")) != key:
                continue
            analyses = session.get("thermal_analysis", [])
            if not isinstance(analyses, list):
                analyses = []
            updated = False
            for entry in analyses:
                if isinstance(entry, dict) and str(entry.get("source_file", "") or "").strip() == source_file:
                    entry.update(patch)
                    updated = True
            if updated:
                session["thermal_analysis"] = analyses
                c.execute("UPDATE sessions SET data=? WHERE id=?",
                          (json.dumps(session, ensure_ascii=False), row["id"]))
            return updated
        raise ValueError(f"No existe una sesion historica para la colada {key}.")


# ---------- Cache de análisis térmico del dispositivo ----------

def load_thermal_device_records():
    with db.transaccion() as c:
        rows = c.execute("SELECT data FROM thermal_records ORDER BY id").fetchall()
    out = []
    for row in rows:
        try:
            out.append(json.loads(row["data"] or "{}"))
        except Exception:
            pass
    return out


def save_thermal_device_records(records):
    """Reemplaza toda la cache de curvas (borra e inserta de nuevo la lista completa)."""
    records = records or []
    with db.transaccion() as c:
        c.execute("DELETE FROM thermal_records")
        for rec in records:
            c.execute("INSERT INTO thermal_records (data) VALUES (?)", (json.dumps(rec, ensure_ascii=False),))


# ---------- config: historial de IPs térmicas / settings / calibraciones de cámara / inoculación ----------

def load_thermal_ips():
    with db.transaccion() as c:
        ips = _config_get(c, "thermal_ips", [])
    return [str(ip).strip() for ip in ips if str(ip).strip()] if isinstance(ips, list) else []


def save_thermal_ips(ips):
    clean = [str(ip).strip() for ip in (ips or []) if str(ip).strip()]
    with db.transaccion() as c:
        _config_set(c, "thermal_ips", clean)


def _default_settings():
    return {"auto_save_hours": 3.0, "debug_mode": False}


def load_settings():
    with db.transaccion() as c:
        saved = _config_get(c, "settings", {})
    out = _default_settings()
    if isinstance(saved, dict):
        out.update({k: v for k, v in saved.items() if k in out})
    return out


def save_settings(settings):
    base = _default_settings()
    if isinstance(settings, dict):
        base.update({k: v for k, v in settings.items() if k in base})
    with db.transaccion() as c:
        _config_set(c, "settings", base)
    return base


def load_camera_calibrations():
    with db.transaccion() as c:
        cals = _config_get(c, "camera_calibrations", [])
    return cals if isinstance(cals, list) else []


def save_camera_calibrations(calibrations):
    with db.transaccion() as c:
        _config_set(c, "camera_calibrations", calibrations or [])


# ---------- Inoculación: etapas y unidades configurables (Catálogo) ----------

_DEFAULT_INOC_MOMENTOS = [
    {"key": "horno", "label": "Horno", "masa_default": 50},
    {"key": "cuchara_transp", "label": "C. transp.", "masa_default": 50},
    {"key": "cuchara_colar", "label": "C. colar", "masa_default": 50},
]
_DEFAULT_INOC_UNITS = ["cucharín", "porción", "sobre", "g", "kg"]


def resolve_inoc_protocol(inoculacion_meta, base=None):
    """Lista de entradas de protocolo para el material+base dados. Si existe un protocolo específico para
    'base' en por_base, lo usa; si no, el protocolo por defecto. Retrocompatible si no hay por_base."""
    if not isinstance(inoculacion_meta, dict):
        return []
    if base:
        base = str(base).strip()
        por_base = inoculacion_meta.get("por_base", {})
        if isinstance(por_base, dict) and base in por_base:
            return list(por_base[base])
    return list(inoculacion_meta.get("inoculacion", []))


def load_inoc_momentos():
    with db.transaccion() as c:
        data = _config_get(c, "inoc_momentos", None)
    if isinstance(data, list):
        result = [
            {"key": str(m["key"]), "label": str(m["label"]),
             "masa_default": float(m["masa_default"]) if m.get("masa_default") else 50}
            for m in data if isinstance(m, dict) and m.get("key") and m.get("label")
        ]
        if result:
            return result
    return [dict(m) for m in _DEFAULT_INOC_MOMENTOS]


def save_inoc_momentos(momentos):
    with db.transaccion() as c:
        _config_set(c, "inoc_momentos", momentos)


def load_inoc_units():
    with db.transaccion() as c:
        data = _config_get(c, "inoc_units", None)
    if isinstance(data, list) and data:
        return [str(u) for u in data if str(u).strip()]
    return list(_DEFAULT_INOC_UNITS)


def save_inoc_units(units):
    with db.transaccion() as c:
        _config_set(c, "inoc_units", units)


# ---------- Informes de calidad ----------

def load_quality_reports():
    with db.transaccion() as c:
        rows = c.execute("SELECT data FROM quality_reports").fetchall()
    out = []
    for row in rows:
        try:
            out.append(json.loads(row["data"] or "{}"))
        except Exception:
            pass
    return out


def save_quality_reports(reports):
    """Reemplaza todos los informes. A cada informe sin "id" (o con un id repetido dentro de la misma lista) se
    le asigna un UUID nuevo acá mismo, mutando el dict `r` in-place."""
    import uuid as _uuid
    reports = reports or []
    with db.transaccion() as c:
        c.execute("DELETE FROM quality_reports")
        seen_ids = set()
        for r in reports:
            if not isinstance(r, dict):
                continue
            rid = r.get("id", "") or ""
            if not rid or rid in seen_ids:
                rid = _uuid.uuid4().hex
                r["id"] = rid
            seen_ids.add(rid)
            c.execute("INSERT INTO quality_reports (id, colada, data) VALUES (?,?,?)",
                      (rid, r.get("colada", ""), json.dumps(r, ensure_ascii=False)))


def ensure_quality_images_dir():
    """Carpeta donde se copian las imágenes adjuntas a los informes de Calidad. A diferencia de la app vieja
    (~/ajuste_comp_quality_images, compartida con el escritorio), esta vive DENTRO de data/ de esta app -- las
    imágenes reales de producción se copian aparte al momento del corte final (ver plan de migración), no antes."""
    import os
    from nucleo import db as _db
    out = _db.DB_PATH.parent / "quality_images"
    os.makedirs(out, exist_ok=True)
    return str(out)


# ---------- Estado "pie de horno" (snapshot en vivo para el kiosco Raspberry) ----------

def _empty_furnace_state():
    return {
        "updated_at": None,
        "ajuste": {
            "colada": "", "material_objetivo": "", "hora_actual": "", "ce_formula": "",
            "ce_actual": None, "ce_estimado": None, "materiales": [],
            "composicion_actual": [], "composicion_estimada": [],
        },
    }


def load_furnace_state():
    with db.transaccion() as c:
        row = c.execute("SELECT * FROM furnace_state WHERE id=1").fetchone()
        if not row:
            return _empty_furnace_state()
        out = _empty_furnace_state()
        out["updated_at"] = row["updated_at"]
        try:
            ajuste = json.loads(row["ajuste"] or "{}")
            if isinstance(ajuste, dict):
                out["ajuste"].update(ajuste)
        except Exception:
            pass
        return out


def save_furnace_state(state):
    base = _empty_furnace_state()
    if isinstance(state, dict):
        base.update(state)
        ajuste = state.get("ajuste", {})
        if isinstance(ajuste, dict):
            base["ajuste"].update(ajuste)
    with db.transaccion() as c:
        c.execute("INSERT OR REPLACE INTO furnace_state (id, updated_at, ajuste) VALUES (1,?,?)",
                  (base.get("updated_at"), json.dumps(base["ajuste"], ensure_ascii=False)))


def clear_furnace_state():
    """Vuelve la fila única de furnace_state a su forma vacía (se usa al resetear/cancelar la sesión en Ajuste)."""
    empty = _empty_furnace_state()
    with db.transaccion() as c:
        c.execute("INSERT OR REPLACE INTO furnace_state (id, updated_at, ajuste) VALUES (1,?,?)",
                  (empty["updated_at"], json.dumps(empty["ajuste"], ensure_ascii=False)))


# ---------- Sesión de trabajo de Ajuste (UNA fila compartida por todos los dispositivos) ----------

def _empty_ajuste_session():
    return {
        "mass": 1000.0, "actual": {}, "objective": "", "adjust_list": [], "kg": {},
        "method": "Greedy", "partial_pct": 100, "colada": "", "session_started_at": None,
        "ajustes_log": [], "calc_log": [], "thermal_analysis": [],
        "carbomax_auto": False, "carbomax_auto_apply": True, "carbomax_max_mass_factor": 1.25,
        "carbomax_base_names": [], "carbomax_device_ip": "", "carbomax_poll_seconds": 15.0,
        "carbomax_busy_poll_seconds": 5.0, "carbomax_timeout": 4.0, "carbomax_auto_armed_at": None,
        "carbomax_last_ts": "", "carbomax_last_consumed": "", "carbomax_consumed_paths": [],
        "carbomax_recent_records": [], "carbomax_device_busy": False,
        "carbomax_modbus_poll_seconds": 60.0, "carbomax_modbus_last_stand3": None,
        "carbomax_modbus_last_stand4": None,
        "spectro_auto": False, "spectro_host": "", "spectro_commands_port": 11000,
        "spectro_events_port": 11001, "spectro_recent_results": [], "spectro_disabled_keys": [],
        "spectro_alerts": [], "spectro_hide_measure": False, "spectro_measuring": False,
        "spectro_connected": False,
    }


def load_ajuste_session():
    with db.transaccion() as c:
        row = c.execute("SELECT data FROM ajuste_session WHERE id=1").fetchone()
    out = _empty_ajuste_session()
    if row:
        try:
            saved = json.loads(row["data"] or "{}")
            if isinstance(saved, dict):
                out.update({k: v for k, v in saved.items() if k in out})
        except Exception:
            pass
    return out


def save_ajuste_session(state):
    base = _empty_ajuste_session()
    if isinstance(state, dict):
        base.update({k: v for k, v in state.items() if k in base})
    with db.transaccion() as c:
        c.execute("INSERT OR REPLACE INTO ajuste_session (id, data) VALUES (1,?)",
                  (json.dumps(base, ensure_ascii=False),))
    return base


# ---------- Cargas guardadas (herramienta "Cálculo de carga") ----------

def load_cargas():
    """Todas las cargas guardadas, más nuevas primero."""
    with db.transaccion() as c:
        rows = c.execute(
            "SELECT id, nombre, created_at, materiales FROM cargas_guardadas ORDER BY id DESC"
        ).fetchall()
    out = []
    for row in rows:
        try:
            materiales = json.loads(row["materiales"] or "[]")
        except Exception:
            materiales = []
        out.append({"id": row["id"], "nombre": row["nombre"], "created_at": row["created_at"],
                     "materiales": materiales})
    return out


def save_carga(nombre, materiales):
    """Guarda una carga nueva (lista de {"nombre": str, "kg": float}). Devuelve el registro creado, con su id.
    Mismo formato de fecha que la app vieja ("%Y-%m-%d %H:%M:%S", con espacio) -- no el de nucleo.db.ahora()
    (isoformat con "T"), para no mezclar dos formatos distintos en la misma columna con las filas reales ya
    guardadas."""
    with db.transaccion() as c:
        ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        cur = c.execute(
            "INSERT INTO cargas_guardadas (nombre, created_at, materiales) VALUES (?,?,?)",
            (nombre, ts, json.dumps(materiales, ensure_ascii=False)),
        )
        return {"id": cur.lastrowid, "nombre": nombre, "created_at": ts, "materiales": materiales}


def delete_carga(carga_id):
    with db.transaccion() as c:
        c.execute("DELETE FROM cargas_guardadas WHERE id=?", (carga_id,))


# ---------- Conteo de cucharas (Pie de Horno / Raspberry) ----------

def _empty_ladles_state():
    return {"updated_at": None, "current": {"colada": "", "material_objetivo": "", "counts": {}, "events": {}},
            "history_by_colada": {}}


def load_ladles_state():
    with db.transaccion() as c:
        out = _empty_ladles_state()
        cur_row = c.execute("SELECT * FROM ladles_current WHERE id=1").fetchone()
        if cur_row:
            out["updated_at"] = cur_row["updated_at"]
            try:
                counts = json.loads(cur_row["counts"] or "{}")
                events = json.loads(cur_row["events"] or "{}")
            except Exception:
                counts, events = {}, {}
            out["current"] = {
                "colada": cur_row["colada"] or "", "material_objetivo": cur_row["material_objetivo"] or "",
                "counts": counts if isinstance(counts, dict) else {},
                "events": events if isinstance(events, dict) else {},
            }
        hist_rows = c.execute("SELECT colada_key, data FROM ladles_history").fetchall()
        history_by = {}
        for row in hist_rows:
            try:
                history_by[row["colada_key"]] = json.loads(row["data"] or "{}")
            except Exception:
                pass
        out["history_by_colada"] = history_by
        return out


def save_ladles_state(state):
    """Guarda "current" (siempre se pisa entera) y sincroniza "history_by_colada" contra la tabla con upsert/
    delete selectivo en vez de borrar todo y reinsertar (puede tener muchas entradas)."""
    base = _empty_ladles_state()
    if isinstance(state, dict):
        base.update(state)
        if not isinstance(base.get("current"), dict):
            base["current"] = {"colada": "", "material_objetivo": "", "counts": {}, "events": {}}
        cur = base["current"]
        if not isinstance(cur.get("counts"), dict):
            cur["counts"] = {}
        if not isinstance(cur.get("events"), dict):
            cur["events"] = {}
        if not isinstance(base.get("history_by_colada"), dict):
            base["history_by_colada"] = {}

    cur = base["current"]
    history_by = base.get("history_by_colada", {})

    with db.transaccion() as c:
        c.execute("""
            INSERT OR REPLACE INTO ladles_current (id, updated_at, colada, material_objetivo, counts, events)
            VALUES (1,?,?,?,?,?)
        """, (base.get("updated_at"), cur.get("colada", ""), cur.get("material_objetivo", ""),
              json.dumps(cur.get("counts", {}), ensure_ascii=False),
              json.dumps(cur.get("events", {}), ensure_ascii=False)))
        existing = {row["colada_key"] for row in c.execute("SELECT colada_key FROM ladles_history")}
        new_keys = set()
        for key, hdata in history_by.items():
            nkey = normalize_colada_key(key)
            new_keys.add(nkey)
            c.execute("""
                INSERT OR REPLACE INTO ladles_history (colada_key, updated_at, data) VALUES (?,?,?)
            """, (nkey, hdata.get("updated_at") if isinstance(hdata, dict) else None,
                  json.dumps(hdata, ensure_ascii=False)))
        for old_key in existing - new_keys:
            c.execute("DELETE FROM ladles_history WHERE colada_key=?", (old_key,))


def delete_ladles_for_colada(colada):
    """Borra el registro de cucharas de una colada específica y, si es la activa ahora mismo, limpia sus
    contadores también. Prueba tanto la clave normalizada como el texto crudo por las dudas."""
    key = normalize_colada_key(colada)
    if not key:
        return False
    with db.transaccion() as c:
        removed = False
        for candidate in {key, str(colada or "").strip()}:
            if candidate and c.execute("DELETE FROM ladles_history WHERE colada_key=?", (candidate,)).rowcount > 0:
                removed = True
        cur_row = c.execute("SELECT colada FROM ladles_current WHERE id=1").fetchone()
        if cur_row and normalize_colada_key(cur_row["colada"] or "") == key:
            c.execute("UPDATE ladles_current SET counts=?, events=? WHERE id=1",
                      (json.dumps({}, ensure_ascii=False), json.dumps({}, ensure_ascii=False)))
            removed = True
        return removed


def load_cucharas_base_config(base: str) -> dict:
    """Devuelve {material_final: bool} para la base dada. Vacío si no hay config guardada."""
    with db.transaccion() as c:
        rows = c.execute(
            "SELECT material_final, active FROM cucharas_base_config WHERE base = ?", (base,)
        ).fetchall()
    return {r["material_final"]: bool(r["active"]) for r in rows}


def save_cucharas_base_config(base: str, material_final: str, active: bool) -> None:
    with db.transaccion() as c:
        c.execute(
            "INSERT INTO cucharas_base_config (base, material_final, active) VALUES (?,?,?) "
            "ON CONFLICT(base, material_final) DO UPDATE SET active = excluded.active",
            (base, material_final, int(active)),
        )


def prune_ladles_history_for_sessions(sessions):
    """Borra de ladles_history cualquier colada que ya NO tenga una sesión correspondiente en `sessions`."""
    valid_keys = {
        normalize_colada_key((s or {}).get("colada", "")) for s in (sessions or [])
        if normalize_colada_key((s or {}).get("colada", ""))
    }
    with db.transaccion() as c:
        rows = c.execute("SELECT colada_key FROM ladles_history").fetchall()
        to_delete = [row["colada_key"] for row in rows if normalize_colada_key(row["colada_key"]) not in valid_keys]
        for key in to_delete:
            c.execute("DELETE FROM ladles_history WHERE colada_key=?", (key,))
        return len(to_delete)
