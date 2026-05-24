# storage.py
import os
import json
import re
import sqlite3
import threading

DB_FILE            = os.path.join(os.path.expanduser("~"), "ajuste_comp.db")
QUALITY_IMAGES_DIR = os.path.join(os.path.expanduser("~"), "ajuste_comp_quality_images")

# Rutas JSON viejas — solo para migración automática
_ALLOYS_FILE   = os.path.join(os.path.expanduser("~"), "ajuste_comp_catalogo.json")
_HISTORY_FILE  = os.path.join(os.path.expanduser("~"), "ajuste_comp_history.json")
_QUALITY_FILE  = os.path.join(os.path.expanduser("~"), "ajuste_comp_quality_reports.json")
_FURNACE_FILE  = os.path.join(os.path.expanduser("~"), "ajuste_comp_pie_horno.json")
_LADLES_FILE   = os.path.join(os.path.expanduser("~"), "ajuste_comp_cucharas.json")
_DEVICES_FILE  = os.path.join(os.path.expanduser("~"), "ajuste_comp_devices.json")
_THERMAL_FILE  = os.path.join(os.path.expanduser("~"), "ajuste_comp_thermal_device.json")

COLADA_KEY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})(?:\s*-\s*.*)?\s*$")

_db_lock        = threading.RLock()
_db_initialized = False


class DuplicateColadaError(ValueError):
    pass


# ---------- Helpers puros (sin I/O) ----------

def normalize_colada_key(value):
    text = str(value or "").strip()
    m = COLADA_KEY_RE.match(text)
    if not m:
        return text
    return f"{int(m.group(1)):04d} /{m.group(2).zfill(2)}"


def _ensure_unique_history_colada(history, session, ignore_index=None):
    key = normalize_colada_key((session or {}).get("colada", ""))
    if not key:
        return
    for idx, item in enumerate(history or []):
        if ignore_index is not None and idx == ignore_index:
            continue
        if normalize_colada_key((item or {}).get("colada", "")) == key:
            raise DuplicateColadaError(f"Ya existe una sesion guardada para la colada {key}.")


def _empty_furnace_state():
    return {
        "updated_at": None,
        "ajuste": {
            "colada": "",
            "material_objetivo": "",
            "hora_actual": "",
            "ce_formula": "",
            "ce_actual": None,
            "ce_estimado": None,
            "materiales": [],
            "composicion_actual": [],
            "composicion_estimada": [],
        },
    }


def _empty_ladles_state():
    return {
        "updated_at": None,
        "current": {
            "colada": "",
            "material_objetivo": "",
            "counts": {},
            "events": {},
        },
        "history_by_colada": {},
    }


def _empty_devices_state():
    return {"devices": {}}


# ---------- SQLite init ----------

def _get_conn():
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _create_tables(conn):
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS meta (
            key   TEXT PRIMARY KEY,
            value TEXT
        );
        CREATE TABLE IF NOT EXISTS alloys (
            position    INTEGER PRIMARY KEY,
            nombre      TEXT,
            tipo        TEXT,
            rendimiento REAL,
            costo       REAL,
            composicion TEXT,
            limites     TEXT,
            especiales  TEXT,
            ajuste      INTEGER,
            extra       TEXT
        );
        CREATE TABLE IF NOT EXISTS sessions (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            colada_key TEXT UNIQUE,
            colada_raw TEXT,
            objetivo   TEXT,
            started_at TEXT,
            ended_at   TEXT,
            data       TEXT
        );
        CREATE TABLE IF NOT EXISTS quality_reports (
            id     TEXT PRIMARY KEY,
            colada TEXT,
            data   TEXT
        );
        CREATE TABLE IF NOT EXISTS furnace_state (
            id         INTEGER PRIMARY KEY,
            updated_at TEXT,
            ajuste     TEXT
        );
        CREATE TABLE IF NOT EXISTS ladles_current (
            id                INTEGER PRIMARY KEY,
            updated_at        TEXT,
            colada            TEXT,
            material_objetivo TEXT,
            counts            TEXT,
            events            TEXT
        );
        CREATE TABLE IF NOT EXISTS ladles_history (
            colada_key TEXT PRIMARY KEY,
            updated_at TEXT,
            data       TEXT
        );
        CREATE TABLE IF NOT EXISTS devices (
            device_id  TEXT PRIMARY KEY,
            name       TEXT,
            status     TEXT,
            role       TEXT,
            first_seen TEXT,
            last_seen  TEXT,
            ip         TEXT,
            user_agent TEXT
        );
        CREATE TABLE IF NOT EXISTS thermal_records (
            id   INTEGER PRIMARY KEY AUTOINCREMENT,
            data TEXT
        );
    """)


def _load_json_safe(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _migrate_from_json(conn):
    row = conn.execute("SELECT value FROM meta WHERE key='migrated'").fetchone()
    if row and row[0] == "1":
        return
    # Si la DB ya tiene datos (entrada manual o migración parcial), no reimportar
    if conn.execute("SELECT COUNT(*) FROM alloys").fetchone()[0] > 0:
        conn.execute("INSERT OR REPLACE INTO meta VALUES('migrated','1')")
        conn.commit()
        return

    migrated_any = False

    # Catálogo
    alloys = _load_json_safe(_ALLOYS_FILE)
    if isinstance(alloys, list) and alloys:
        known = {"nombre", "tipo", "rendimiento", "costo", "composicion", "limites", "especiales", "ajuste"}
        for i, a in enumerate(alloys):
            if not isinstance(a, dict):
                continue
            extra = {k: v for k, v in a.items() if k not in known}
            conn.execute("""
                INSERT OR IGNORE INTO alloys
                    (position, nombre, tipo, rendimiento, costo, composicion, limites, especiales, ajuste, extra)
                VALUES (?,?,?,?,?,?,?,?,?,?)
            """, (
                i,
                a.get("nombre", ""),
                a.get("tipo", ""),
                a.get("rendimiento", 0),
                a.get("costo", 0),
                json.dumps(a.get("composicion", {}), ensure_ascii=False),
                json.dumps(a.get("limites", {}), ensure_ascii=False),
                json.dumps(a.get("especiales", {}), ensure_ascii=False),
                1 if a.get("ajuste") else 0,
                json.dumps(extra, ensure_ascii=False),
            ))
        migrated_any = True

    # Histórico de sesiones
    history = _load_json_safe(_HISTORY_FILE)
    if isinstance(history, list) and history:
        for session in history:
            if not isinstance(session, dict):
                continue
            conn.execute("""
                INSERT OR IGNORE INTO sessions
                    (colada_key, colada_raw, objetivo, started_at, ended_at, data)
                VALUES (?,?,?,?,?,?)
            """, (
                normalize_colada_key(session.get("colada", "")),
                session.get("colada", ""),
                session.get("objetivo", ""),
                session.get("started_at", ""),
                session.get("ended_at", ""),
                json.dumps(session, ensure_ascii=False),
            ))
        migrated_any = True

    # Informes de calidad
    reports = _load_json_safe(_QUALITY_FILE)
    if isinstance(reports, list) and reports:
        import uuid as _uuid
        seen_rids = set()
        for r in reports:
            if not isinstance(r, dict):
                continue
            rid = r.get("id", "") or ""
            if not rid or rid in seen_rids:
                rid = _uuid.uuid4().hex
                r["id"] = rid
            seen_rids.add(rid)
            conn.execute("""
                INSERT OR IGNORE INTO quality_reports (id, colada, data) VALUES (?,?,?)
            """, (
                rid,
                r.get("colada", ""),
                json.dumps(r, ensure_ascii=False),
            ))
        migrated_any = True

    # Estado horno
    furnace = _load_json_safe(_FURNACE_FILE)
    if isinstance(furnace, dict):
        ajuste = furnace.get("ajuste", {})
        conn.execute("""
            INSERT OR REPLACE INTO furnace_state (id, updated_at, ajuste) VALUES (1,?,?)
        """, (
            furnace.get("updated_at"),
            json.dumps(ajuste if isinstance(ajuste, dict) else {}, ensure_ascii=False),
        ))
        migrated_any = True

    # Cucharas
    ladles = _load_json_safe(_LADLES_FILE)
    if isinstance(ladles, dict):
        current = ladles.get("current", {})
        if isinstance(current, dict):
            conn.execute("""
                INSERT OR REPLACE INTO ladles_current
                    (id, updated_at, colada, material_objetivo, counts, events)
                VALUES (1,?,?,?,?,?)
            """, (
                ladles.get("updated_at"),
                current.get("colada", ""),
                current.get("material_objetivo", ""),
                json.dumps(current.get("counts", {}), ensure_ascii=False),
                json.dumps(current.get("events", {}), ensure_ascii=False),
            ))
        history_by = ladles.get("history_by_colada", {})
        if isinstance(history_by, dict):
            for key, hdata in history_by.items():
                conn.execute("""
                    INSERT OR IGNORE INTO ladles_history (colada_key, updated_at, data)
                    VALUES (?,?,?)
                """, (
                    normalize_colada_key(key),
                    hdata.get("updated_at") if isinstance(hdata, dict) else None,
                    json.dumps(hdata, ensure_ascii=False),
                ))
        migrated_any = True

    # Dispositivos
    devices_state = _load_json_safe(_DEVICES_FILE)
    if isinstance(devices_state, dict):
        devices = devices_state.get("devices", {})
        if isinstance(devices, dict):
            for dev_id, dev in devices.items():
                if not isinstance(dev, dict):
                    continue
                conn.execute("""
                    INSERT OR IGNORE INTO devices
                        (device_id, name, status, role, first_seen, last_seen, ip, user_agent)
                    VALUES (?,?,?,?,?,?,?,?)
                """, (
                    dev_id,
                    dev.get("name", ""),
                    dev.get("status", ""),
                    dev.get("role", ""),
                    dev.get("first_seen", ""),
                    dev.get("last_seen", ""),
                    dev.get("ip", ""),
                    dev.get("user_agent", ""),
                ))
            migrated_any = True

    # Cache análisis térmico
    thermal = _load_json_safe(_THERMAL_FILE)
    if isinstance(thermal, list) and thermal:
        for rec in thermal:
            conn.execute(
                "INSERT INTO thermal_records (data) VALUES (?)",
                (json.dumps(rec, ensure_ascii=False),)
            )
        migrated_any = True

    conn.execute("INSERT OR REPLACE INTO meta VALUES('migrated','1')")
    conn.commit()

    if migrated_any:
        for path in [_ALLOYS_FILE, _HISTORY_FILE, _QUALITY_FILE,
                     _FURNACE_FILE, _LADLES_FILE, _DEVICES_FILE, _THERMAL_FILE]:
            if os.path.exists(path):
                try:
                    os.rename(path, path + ".bak")
                except Exception:
                    pass


def _init_db():
    global _db_initialized
    if _db_initialized:
        return
    with _db_lock:
        if _db_initialized:
            return
        conn = _get_conn()
        try:
            _create_tables(conn)
            _migrate_from_json(conn)
            _migrate_types(conn)
        finally:
            conn.close()
        _db_initialized = True


def _migrate_types(conn):
    """Elimina tipos obsoletos. Idempotente."""
    n = conn.execute(
        "SELECT COUNT(*) FROM alloys WHERE tipo='Aleación especial'"
    ).fetchone()[0]
    if n:
        conn.execute("DELETE FROM alloys WHERE tipo='Aleación especial'")
        conn.commit()


# ---------- Catálogo ----------

def load_alloys():
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT * FROM alloys ORDER BY position").fetchall()
            result = []
            for row in rows:
                a = {
                    "nombre":      row["nombre"],
                    "tipo":        row["tipo"],
                    "rendimiento": row["rendimiento"],
                    "costo":       row["costo"],
                    "composicion": json.loads(row["composicion"] or "{}"),
                    "limites":     json.loads(row["limites"] or "{}"),
                    "especiales":  json.loads(row["especiales"] or "{}"),
                    "ajuste":      bool(row["ajuste"]),
                }
                extra = json.loads(row["extra"] or "{}")
                a.update(extra)
                result.append(a)
            return result
        finally:
            conn.close()


def save_alloys(alloys):
    _init_db()
    alloys = alloys or []
    known = {"nombre", "tipo", "rendimiento", "costo", "composicion", "limites", "especiales", "ajuste"}
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute("DELETE FROM alloys")
                for i, a in enumerate(alloys):
                    if not isinstance(a, dict):
                        continue
                    extra = {k: v for k, v in a.items() if k not in known}
                    conn.execute("""
                        INSERT INTO alloys
                            (position, nombre, tipo, rendimiento, costo,
                             composicion, limites, especiales, ajuste, extra)
                        VALUES (?,?,?,?,?,?,?,?,?,?)
                    """, (
                        i,
                        a.get("nombre", ""),
                        a.get("tipo", ""),
                        a.get("rendimiento", 0),
                        a.get("costo", 0),
                        json.dumps(a.get("composicion", {}), ensure_ascii=False),
                        json.dumps(a.get("limites", {}), ensure_ascii=False),
                        json.dumps(a.get("especiales", {}), ensure_ascii=False),
                        1 if a.get("ajuste") else 0,
                        json.dumps(extra, ensure_ascii=False),
                    ))
        finally:
            conn.close()


# ---------- Históricos ----------

def _session_to_row(session):
    return (
        normalize_colada_key(session.get("colada", "")),
        session.get("colada", ""),
        session.get("objetivo", ""),
        session.get("started_at", ""),
        session.get("ended_at", ""),
        json.dumps(session, ensure_ascii=False),
    )


def _get_session_id_at(conn, index):
    rows = conn.execute("SELECT id FROM sessions ORDER BY id").fetchall()
    if 0 <= index < len(rows):
        return rows[index]["id"]
    return None


def load_history():
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT data FROM sessions ORDER BY id").fetchall()
            result = []
            for row in rows:
                try:
                    result.append(json.loads(row["data"] or "{}"))
                except Exception:
                    pass
            return result
        finally:
            conn.close()


def append_history(session):
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            key = normalize_colada_key((session or {}).get("colada", ""))
            if key and conn.execute(
                "SELECT id FROM sessions WHERE colada_key=?", (key,)
            ).fetchone():
                raise DuplicateColadaError(f"Ya existe una sesion guardada para la colada {key}.")
            with conn:
                conn.execute("""
                    INSERT INTO sessions (colada_key, colada_raw, objetivo, started_at, ended_at, data)
                    VALUES (?,?,?,?,?,?)
                """, _session_to_row(session))
        finally:
            conn.close()


def save_history(history_list):
    _init_db()
    history_list = history_list or []
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute("DELETE FROM sessions")
                for session in history_list:
                    if not isinstance(session, dict):
                        continue
                    conn.execute("""
                        INSERT OR REPLACE INTO sessions
                            (colada_key, colada_raw, objetivo, started_at, ended_at, data)
                        VALUES (?,?,?,?,?,?)
                    """, _session_to_row(session))
        finally:
            conn.close()


def update_session(index, session_obj):
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            row_id = _get_session_id_at(conn, index)
            if row_id is None:
                return
            key = normalize_colada_key((session_obj or {}).get("colada", ""))
            if key and conn.execute(
                "SELECT id FROM sessions WHERE colada_key=? AND id!=?", (key, row_id)
            ).fetchone():
                raise DuplicateColadaError(f"Ya existe una sesion guardada para la colada {key}.")
            with conn:
                conn.execute("""
                    UPDATE sessions
                    SET colada_key=?, colada_raw=?, objetivo=?, started_at=?, ended_at=?, data=?
                    WHERE id=?
                """, _session_to_row(session_obj) + (row_id,))
        finally:
            conn.close()


def delete_session(index):
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            row_id = _get_session_id_at(conn, index)
            if row_id is None:
                return
            row = conn.execute("SELECT colada_raw FROM sessions WHERE id=?", (row_id,)).fetchone()
            colada = row["colada_raw"] if row else ""
            with conn:
                conn.execute("DELETE FROM sessions WHERE id=?", (row_id,))
        finally:
            conn.close()
        delete_ladles_for_colada(colada)


def update_adjustment(session_index, adj_index, new_adj):
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            row_id = _get_session_id_at(conn, session_index)
            if row_id is None:
                return
            row = conn.execute("SELECT data FROM sessions WHERE id=?", (row_id,)).fetchone()
            session = json.loads(row["data"] or "{}")
            ajustes = session.get("ajustes", [])
            if 0 <= adj_index < len(ajustes):
                ajustes[adj_index] = new_adj
                session["ajustes"] = ajustes
                with conn:
                    conn.execute(
                        "UPDATE sessions SET data=? WHERE id=?",
                        (json.dumps(session, ensure_ascii=False), row_id)
                    )
        finally:
            conn.close()


def delete_adjustment(session_index, adj_index):
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            row_id = _get_session_id_at(conn, session_index)
            if row_id is None:
                return
            row = conn.execute("SELECT data FROM sessions WHERE id=?", (row_id,)).fetchone()
            session = json.loads(row["data"] or "{}")
            ajustes = session.get("ajustes", [])
            if 0 <= adj_index < len(ajustes):
                del ajustes[adj_index]
                session["ajustes"] = ajustes
                with conn:
                    conn.execute(
                        "UPDATE sessions SET data=? WHERE id=?",
                        (json.dumps(session, ensure_ascii=False), row_id)
                    )
        finally:
            conn.close()


def attach_thermal_analysis(colada, analysis_obj):
    _init_db()
    key = normalize_colada_key(colada)
    if not key:
        raise ValueError("Colada vacia.")
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT id, data FROM sessions ORDER BY id").fetchall()
            for i, row in enumerate(rows):
                session = json.loads(row["data"] or "{}")
                if normalize_colada_key(session.get("colada", "")) != key:
                    continue
                analyses = session.get("thermal_analysis", [])
                if not isinstance(analyses, list):
                    analyses = []
                analyses.append(analysis_obj)
                session["thermal_analysis"] = analyses
                with conn:
                    conn.execute(
                        "UPDATE sessions SET data=? WHERE id=?",
                        (json.dumps(session, ensure_ascii=False), row["id"])
                    )
                return i
            raise ValueError(f"No existe una sesion historica para la colada {key}.")
        finally:
            conn.close()


# ---------- Cache análisis térmico del dispositivo ----------

def load_thermal_device_records():
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT data FROM thermal_records ORDER BY id").fetchall()
            result = []
            for row in rows:
                try:
                    result.append(json.loads(row["data"] or "{}"))
                except Exception:
                    pass
            return result
        finally:
            conn.close()


def save_thermal_device_records(records):
    _init_db()
    records = records or []
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute("DELETE FROM thermal_records")
                for rec in records:
                    conn.execute(
                        "INSERT INTO thermal_records (data) VALUES (?)",
                        (json.dumps(rec, ensure_ascii=False),)
                    )
        finally:
            conn.close()


# ---------- Informes de calidad ----------

def load_quality_reports():
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT data FROM quality_reports").fetchall()
            result = []
            for row in rows:
                try:
                    result.append(json.loads(row["data"] or "{}"))
                except Exception:
                    pass
            return result
        finally:
            conn.close()


def save_quality_reports(reports):
    import uuid as _uuid
    _init_db()
    reports = reports or []
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute("DELETE FROM quality_reports")
                seen_ids = set()
                for r in reports:
                    if not isinstance(r, dict):
                        continue
                    rid = r.get("id", "") or ""
                    if not rid or rid in seen_ids:
                        rid = _uuid.uuid4().hex
                        r["id"] = rid
                    seen_ids.add(rid)
                    conn.execute(
                        "INSERT INTO quality_reports (id, colada, data) VALUES (?,?,?)",
                        (rid, r.get("colada", ""), json.dumps(r, ensure_ascii=False))
                    )
        finally:
            conn.close()


def ensure_quality_images_dir():
    os.makedirs(QUALITY_IMAGES_DIR, exist_ok=True)
    return QUALITY_IMAGES_DIR


# ---------- Estado pie de horno ----------

def load_furnace_state():
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            row = conn.execute("SELECT * FROM furnace_state WHERE id=1").fetchone()
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
        finally:
            conn.close()


def save_furnace_state(state):
    _init_db()
    base = _empty_furnace_state()
    if isinstance(state, dict):
        base.update(state)
        ajuste = state.get("ajuste", {})
        if isinstance(ajuste, dict):
            base["ajuste"].update(ajuste)
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO furnace_state (id, updated_at, ajuste) VALUES (1,?,?)
                """, (base.get("updated_at"), json.dumps(base["ajuste"], ensure_ascii=False)))
        finally:
            conn.close()


def clear_furnace_state():
    _init_db()
    empty = _empty_furnace_state()
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO furnace_state (id, updated_at, ajuste) VALUES (1,?,?)
                """, (empty["updated_at"], json.dumps(empty["ajuste"], ensure_ascii=False)))
        finally:
            conn.close()


# ---------- Conteo de cucharas ----------

def load_ladles_state():
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            out = _empty_ladles_state()
            cur_row = conn.execute("SELECT * FROM ladles_current WHERE id=1").fetchone()
            if cur_row:
                out["updated_at"] = cur_row["updated_at"]
                try:
                    counts = json.loads(cur_row["counts"] or "{}")
                    events = json.loads(cur_row["events"] or "{}")
                except Exception:
                    counts, events = {}, {}
                out["current"] = {
                    "colada":            cur_row["colada"] or "",
                    "material_objetivo": cur_row["material_objetivo"] or "",
                    "counts": counts if isinstance(counts, dict) else {},
                    "events": events if isinstance(events, dict) else {},
                }
            hist_rows = conn.execute("SELECT colada_key, data FROM ladles_history").fetchall()
            history_by = {}
            for row in hist_rows:
                try:
                    history_by[row["colada_key"]] = json.loads(row["data"] or "{}")
                except Exception:
                    pass
            out["history_by_colada"] = history_by
            return out
        finally:
            conn.close()


def save_ladles_state(state):
    _init_db()
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

    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute("""
                    INSERT OR REPLACE INTO ladles_current
                        (id, updated_at, colada, material_objetivo, counts, events)
                    VALUES (1,?,?,?,?,?)
                """, (
                    base.get("updated_at"),
                    cur.get("colada", ""),
                    cur.get("material_objetivo", ""),
                    json.dumps(cur.get("counts", {}), ensure_ascii=False),
                    json.dumps(cur.get("events", {}), ensure_ascii=False),
                ))
                # Sincronizar historial: upsert entradas nuevas/modificadas, borrar eliminadas
                existing = {
                    row["colada_key"]
                    for row in conn.execute("SELECT colada_key FROM ladles_history")
                }
                new_keys = set()
                for key, hdata in history_by.items():
                    nkey = normalize_colada_key(key)
                    new_keys.add(nkey)
                    conn.execute("""
                        INSERT OR REPLACE INTO ladles_history (colada_key, updated_at, data)
                        VALUES (?,?,?)
                    """, (
                        nkey,
                        hdata.get("updated_at") if isinstance(hdata, dict) else None,
                        json.dumps(hdata, ensure_ascii=False),
                    ))
                for old_key in existing - new_keys:
                    conn.execute("DELETE FROM ladles_history WHERE colada_key=?", (old_key,))
        finally:
            conn.close()


def delete_ladles_for_colada(colada):
    _init_db()
    key = normalize_colada_key(colada)
    if not key:
        return False
    with _db_lock:
        conn = _get_conn()
        try:
            removed = False
            with conn:
                for candidate in {key, str(colada or "").strip()}:
                    if candidate and conn.execute(
                        "DELETE FROM ladles_history WHERE colada_key=?", (candidate,)
                    ).rowcount > 0:
                        removed = True
                cur_row = conn.execute("SELECT colada FROM ladles_current WHERE id=1").fetchone()
                if cur_row and normalize_colada_key(cur_row["colada"] or "") == key:
                    conn.execute("""
                        UPDATE ladles_current SET counts=?, events=? WHERE id=1
                    """, (
                        json.dumps({}, ensure_ascii=False),
                        json.dumps({}, ensure_ascii=False),
                    ))
                    removed = True
            return removed
        finally:
            conn.close()


def prune_ladles_history_for_sessions(sessions):
    _init_db()
    valid_keys = {
        normalize_colada_key((s or {}).get("colada", ""))
        for s in (sessions or [])
        if normalize_colada_key((s or {}).get("colada", ""))
    }
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT colada_key FROM ladles_history").fetchall()
            to_delete = [
                row["colada_key"] for row in rows
                if normalize_colada_key(row["colada_key"]) not in valid_keys
            ]
            if not to_delete:
                return 0
            with conn:
                for key in to_delete:
                    conn.execute("DELETE FROM ladles_history WHERE colada_key=?", (key,))
            return len(to_delete)
        finally:
            conn.close()


# ---------- Dispositivos Pie de Horno ----------

def load_devices_state():
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT * FROM devices").fetchall()
            devices = {}
            for row in rows:
                devices[row["device_id"]] = {
                    "id":         row["device_id"],
                    "name":       row["name"],
                    "status":     row["status"],
                    "role":       row["role"],
                    "first_seen": row["first_seen"],
                    "last_seen":  row["last_seen"],
                    "ip":         row["ip"],
                    "user_agent": row["user_agent"],
                }
            return {"devices": devices}
        finally:
            conn.close()


def save_devices_state(state):
    _init_db()
    devices = {}
    if isinstance(state, dict) and isinstance(state.get("devices"), dict):
        devices = state["devices"]
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute("DELETE FROM devices")
                for dev_id, dev in devices.items():
                    if not isinstance(dev, dict):
                        continue
                    conn.execute("""
                        INSERT INTO devices
                            (device_id, name, status, role, first_seen, last_seen, ip, user_agent)
                        VALUES (?,?,?,?,?,?,?,?)
                    """, (
                        dev_id,
                        dev.get("name", ""),
                        dev.get("status", ""),
                        dev.get("role", ""),
                        dev.get("first_seen", ""),
                        dev.get("last_seen", ""),
                        dev.get("ip", ""),
                        dev.get("user_agent", ""),
                    ))
        finally:
            conn.close()


_INOC_UNITS_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_inoc_units.json")
_DEFAULT_INOC_UNITS = ["cucharín", "porción", "sobre", "g", "kg"]

def load_inoc_units():
    if os.path.exists(_INOC_UNITS_FILE):
        try:
            with open(_INOC_UNITS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list) and data:
                return [str(u) for u in data if str(u).strip()]
        except Exception:
            pass
    return list(_DEFAULT_INOC_UNITS)

def save_inoc_units(units):
    tmp = _INOC_UNITS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(units, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _INOC_UNITS_FILE)
