# storage.py
#
# Capa de persistencia de toda la app. Todo vive en UNA base SQLite en la
# carpeta del usuario (~/ajuste_comp.db) - no en el repo, y no en los
# archivos JSON que estan en la carpeta del proyecto (esos son legacy/no se
# usan mas, ver mas abajo). Cada "dominio" (catalogo, historial de coladas,
# informes de calidad, pie de horno, cucharas, dispositivos, cache de
# analisis termico) tiene su propia tabla y sus propias funciones
# load_x()/save_x() (o CRUD mas granular cuando conviene, como en
# Historicos). Los blobs complejos (composicion, limites, sesion completa,
# etc) se guardan como texto JSON dentro de una columna, no normalizados en
# columnas separadas - mas simple de mantener a costa de no poder hacer
# queries SQL sobre esos campos internos.
#
# Migracion: la primera vez que corre la app contra una DB nueva,
# _migrate_from_json() importa los JSON viejos (~/ajuste_comp_*.json) que
# dejaba la version anterior (pre-SQLite) de la app, y los renombra a .bak.
# Esto es un paso UNICO, protegido por una fila en la tabla "meta"
# (meta.migrated = '1'); despues de la primera vez no vuelve a tocar esos
# archivos.
#
# Concurrencia: la app abre/cierra una conexion SQLite nueva en cada
# funcion (no hay una conexion global compartida) y todo el acceso esta
# serializado por _db_lock (un RLock), asi que dos threads nunca escriben
# a la vez aunque SQLite ya sea razonablemente seguro para esto.
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
_THERMAL_IPS_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_thermal_ips.json")

COLADA_KEY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})(?:\s*-\s*.*)?\s*$")

_db_lock        = threading.RLock()
_db_initialized = False


class DuplicateColadaError(ValueError):
    """Se lanza al intentar guardar/renombrar una sesion con un numero de
    colada que ya existe (comparando por normalize_colada_key, no por texto
    literal - "50 /26" y "0050 /26" son la misma colada)."""
    pass


# ---------- Helpers puros (sin I/O) ----------

def normalize_colada_key(value):
    """Normaliza "NNNN /YY[- lo que sea]" a una clave canonica "NNNN /YY"
    con el numero siempre en 4 digitos (ej. "50 /26 - Bloque" -> "0050 /26").
    Es la clave que se usa para detectar coladas duplicadas y para el join
    entre sesiones de Historicos y el registro de cucharas por colada. Si el
    texto no matchea el patron esperado, se devuelve tal cual (fallback)."""
    text = str(value or "").strip()
    m = COLADA_KEY_RE.match(text)
    if not m:
        return text
    return f"{int(m.group(1)):04d} /{m.group(2).zfill(2)}"


# Nota: existia una funcion _ensure_unique_history_colada() que chequeaba
# duplicados recorriendo una lista en memoria - era de la epoca pre-SQLite
# (cuando el historial vivia en un JSON). Se elimino por no tener ningun
# caller (verificado en todo el repo): la unicidad de colada hoy la
# garantiza la propia base (columna sessions.colada_key con UNIQUE) mas los
# chequeos explicitos en append_history()/update_session() mas abajo.


def _empty_furnace_state():
    """Snapshot vacio del "pie de horno" (lo que Ajuste publica para que el
    kiosco Raspberry / web muestre colada, objetivo y composicion actual en
    vivo). Se usa como valor por defecto cuando no hay nada guardado, y para
    "limpiar" el estado al resetear una sesion."""
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
    """Estado vacio del conteo de cucharas: "current" es la colada que se
    esta contando ahora mismo (contadores + eventos con timestamp por
    material), "history_by_colada" acumula el conteo final de cada colada ya
    cerrada, indexado por colada normalizada."""
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


# ---------- SQLite init: conexion, esquema de tablas, migracion, arranque ----------

def _get_conn():
    """Abre una conexion SQLite nueva (no hay pool ni conexion global: cada
    funcion publica abre la suya y la cierra en su propio finally). WAL
    permite lecturas concurrentes mientras se escribe."""
    conn = sqlite3.connect(DB_FILE, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _create_tables(conn):
    """Crea (si no existen) todas las tablas de la app. "meta" es una tabla
    key/value chica usada solo para flags internos (hoy: "migrated"). Casi
    todas las demas tablas guardan la mayoria de sus datos como JSON en una
    columna "data"/"extra"/etc, y solo separan en columnas propias los campos
    por los que hace falta filtrar/ordenar con SQL (colada_key, started_at,
    position...)."""
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
    """Lee un JSON legacy si existe y es valido; None en cualquier otro
    caso (archivo ausente, corrupto, etc) - nunca tira excepcion, porque
    solo se usa durante la migracion y un JSON viejo roto no debe impedir
    que arranque la app."""
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return None


def _migrate_from_json(conn):
    """Migracion unica desde los JSON de la version pre-SQLite hacia las
    tablas de la DB. Se salta por completo si meta.migrated ya es '1', o si
    la tabla alloys ya tiene datos (evita reimportar sobre una DB que ya se
    uso). Por cada dominio con JSON viejo presente: lo lee, lo inserta en su
    tabla con INSERT OR IGNORE/REPLACE (para no duplicar si se corre dos
    veces por alguna razon), y al final renombra los .json migrados a
    ".json.bak" para que no se vuelvan a leer."""
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
    """Punto de entrada que corre TODA funcion publica de este modulo antes
    de tocar la DB (crear tablas + migrar si hace falta + arrancar). Usa
    _db_initialized como flag para no repetir el trabajo en cada llamada;
    el chequeo esta duplicado antes y despues de tomar _db_lock (patron
    "double-checked locking") para no pagar el costo del lock en el camino
    comun (ya inicializado)."""
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


# ---------- Catálogo: aleaciones/materiales del catalogo (tabla "alloys") ----------

def load_alloys():
    """Devuelve la lista completa del catalogo, en el orden guardado
    (columna "position"). Los campos "conocidos" salen de columnas propias;
    cualquier otro campo que el catalogo haya guardado (ej. metadata de
    Calidad como calidad_meta) viaja en la columna "extra" como JSON y se
    mezcla de vuelta en el dict con a.update(extra)."""
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
    """Reemplaza TODO el catalogo de una: borra la tabla entera y vuelve a
    insertar la lista completa, en orden (el indice de la lista pasa a ser
    "position"). No hay upsert/merge parcial - quien llama siempre manda la
    lista completa del catalogo, no un delta."""
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


# ---------- Históricos: sesiones de ajuste guardadas (una fila por colada) ----------
#
# Cada sesion (colada completa) se guarda como UN blob JSON en la columna
# "data" - contiene ajustes aplicados, calculos, carbono, analisis termico
# adjuntado, etc (ver tab_ajuste.py get_state()/set_state() para la forma
# exacta). Las columnas sueltas (colada_key, objetivo, started_at, ended_at)
# son una copia rapida de acceso para poder buscar/ordenar sin tener que
# parsear el JSON de cada fila.
#
# ADVERTENCIA sobre indices: update_session()/delete_session()/
# update_adjustment()/delete_adjustment() reciben un "index" ENTERO que se
# resuelve via _get_session_id_at() contra "ORDER BY id" (orden de creacion,
# no el orden en que se muestra en la UI). Quien llama a estas funciones
# tiene que asegurarse de que ese indice siga siendo el mismo en el momento
# de la llamada (por eso tab_historicos.py usa el iid de cada fila del
# Treeview en vez de su posicion visual - ver ese archivo para el porque).

def _session_to_row(session):
    """Arma la tupla de valores (colada_key, colada_raw, objetivo,
    started_at, ended_at, data_json) que usan los INSERT/UPDATE de
    sessions - evita repetir el mismo mapeo dict->columnas en cada funcion."""
    return (
        normalize_colada_key(session.get("colada", "")),
        session.get("colada", ""),
        session.get("objetivo", ""),
        session.get("started_at", ""),
        session.get("ended_at", ""),
        json.dumps(session, ensure_ascii=False),
    )


def _get_session_id_at(conn, index):
    """Traduce una posicion "index" (0-based, en orden de creacion) al id
    real de fila en sessions. None si el indice esta fuera de rango."""
    rows = conn.execute("SELECT id FROM sessions ORDER BY id").fetchall()
    if 0 <= index < len(rows):
        return rows[index]["id"]
    return None


def load_history():
    """Todas las sesiones guardadas, en orden de creacion (mismo orden que
    usan los indices de update_session/delete_session/etc)."""
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
    """Guarda una sesion nueva. Tira DuplicateColadaError si ya existe una
    fila con la misma colada normalizada (la tabla ademas tiene
    colada_key UNIQUE como segunda linea de defensa a nivel DB)."""
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


def update_session(index, session_obj):
    """Reemplaza la sesion en la posicion `index` (ver advertencia sobre
    indices arriba) por `session_obj` completo. Vuelve a chequear
    duplicados de colada, excluyendo la propia fila que se esta editando
    (por eso el "AND id!=?")."""
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
    """Borra la sesion en la posicion `index` y, en cascada, su registro de
    cucharas asociado (delete_ladles_for_colada) - una colada borrada no
    debe dejar conteos de cucharas huerfanos dando vueltas."""
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
    """Edita UN ajuste puntual dentro de session["ajustes"][adj_index], sin
    tocar el resto de la sesion. Hay que leer el JSON completo, modificar la
    lista en memoria y reescribir el JSON entero (no hay forma de editar
    "un elemento de una lista dentro de una columna JSON" directo en SQL)."""
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
    """Como update_adjustment pero borra el ajuste en vez de reemplazarlo."""
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
    """Vincula un analisis termico (curva de Carbono o Microestructura, ya
    armada por tab_analisis_termico.py) a la sesion de la colada dada,
    agregandolo a session["thermal_analysis"]. A diferencia de
    update_session/delete_session, aca se busca la sesion POR COLADA (no por
    indice posicional) porque quien llama (Analisis termico) no tiene ni
    necesita saber en que posicion esta esa sesion en la lista de
    Historicos. Devuelve la posicion (indice) de la sesion encontrada."""
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


def detach_thermal_analysis(colada, analysis_index):
    """Inverso de attach_thermal_analysis: saca el analisis en la posicion
    `analysis_index` dentro de session["thermal_analysis"] de esa colada
    (no borra la curva original, solo el vinculo)."""
    _init_db()
    key = normalize_colada_key(colada)
    if not key:
        raise ValueError("Colada vacia.")
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT id, data FROM sessions ORDER BY id").fetchall()
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
                    with conn:
                        conn.execute(
                            "UPDATE sessions SET data=? WHERE id=?",
                            (json.dumps(session, ensure_ascii=False), row["id"])
                        )
                return
            raise ValueError(f"No existe una sesion historica para la colada {key}.")
        finally:
            conn.close()


def set_thermal_analysis_field(colada, source_file, patch):
    """Actualiza campos puntuales (dict `patch`, ej. {"orden": 2} o
    {"etapa_muestra": "Cuchara colar"}) de un analisis termico ya vinculado,
    identificandolo por colada + source_file (la ruta/id de la curva
    original) en vez de por indice - mas robusto para editar desde un
    dialogo que no sabe la posicion exacta dentro de la lista."""
    _init_db()
    key = normalize_colada_key(colada)
    if not key:
        raise ValueError("Colada vacia.")
    source_file = str(source_file or "").strip()
    if not source_file:
        raise ValueError("Archivo de origen vacio.")
    with _db_lock:
        conn = _get_conn()
        try:
            rows = conn.execute("SELECT id, data FROM sessions ORDER BY id").fetchall()
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
                    with conn:
                        conn.execute(
                            "UPDATE sessions SET data=? WHERE id=?",
                            (json.dumps(session, ensure_ascii=False), row["id"])
                        )
                return updated
            raise ValueError(f"No existe una sesion historica para la colada {key}.")
        finally:
            conn.close()


# ---------- Cache análisis térmico del dispositivo ----------
# Copia local de las curvas (Carbono/Microestructura) ya descargadas del
# equipo Carbomax, para no tener que volver a pedirlas por red cada vez que
# se abre la pestaña Analisis termico. tab_analisis_termico.py hace el merge
# entre esta cache y lo que hay en el dispositivo (reusa lo que ya esta
# fresco, descarga solo lo nuevo/desactualizado).

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
    """Reemplaza toda la cache de curvas (borra e inserta de nuevo la lista
    completa) - igual patron que save_alloys()."""
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


# ---------- Historial de IPs del dispositivo térmico ----------
# Lista de IPs usadas antes, para autocompletar el combo de IP en Analisis
# termico. Vive en la tabla "meta" (clave 'thermal_ips', valor JSON) -
# antes era un archivo JSON aparte (~/ajuste_comp_thermal_ips.json), igual
# que el resto de los dominios antes de migrar a SQLite. La primera vez
# que se llama a load_thermal_ips() despues de este cambio, si ese archivo
# legacy todavia existe se importa a la DB y se renombra a ".bak" (mismo
# patron que _migrate_from_json), para no perder el historial ya guardado.

def load_thermal_ips():
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='thermal_ips'").fetchone()
            if row is None:
                legacy = _load_json_safe(_THERMAL_IPS_FILE)
                ips = [str(ip).strip() for ip in legacy if str(ip).strip()] if isinstance(legacy, list) else []
                with conn:
                    conn.execute(
                        "INSERT OR REPLACE INTO meta VALUES('thermal_ips', ?)",
                        (json.dumps(ips, ensure_ascii=False),),
                    )
                if os.path.exists(_THERMAL_IPS_FILE):
                    try:
                        os.replace(_THERMAL_IPS_FILE, _THERMAL_IPS_FILE + ".bak")
                    except Exception:
                        pass
                return ips
            try:
                data = json.loads(row["value"])
            except Exception:
                return []
            return [str(ip).strip() for ip in data if str(ip).strip()] if isinstance(data, list) else []
        finally:
            conn.close()


def save_thermal_ips(ips):
    _init_db()
    clean = [str(ip).strip() for ip in (ips or []) if str(ip).strip()]
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES('thermal_ips', ?)",
                    (json.dumps(clean, ensure_ascii=False),),
                )
        finally:
            conn.close()


# ---------- Espectrometro LMX06 (host/puertos + historial de IPs) ----------
# Mismo patron que thermal_ips arriba (tabla "meta", valor JSON), sin
# migracion legacy porque es un dominio nuevo -- nunca existio como archivo
# JSON aparte.

_SPECTRO_SETTINGS_DEFAULTS = {"commands_port": 11000, "events_port": 11001}


def load_spectro_ips():
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='spectro_ips'").fetchone()
            if row is None:
                return []
            try:
                data = json.loads(row["value"])
            except Exception:
                return []
            return [str(ip).strip() for ip in data if str(ip).strip()] if isinstance(data, list) else []
        finally:
            conn.close()


def save_spectro_ips(ips):
    _init_db()
    clean = [str(ip).strip() for ip in (ips or []) if str(ip).strip()]
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES('spectro_ips', ?)",
                    (json.dumps(clean, ensure_ascii=False),),
                )
        finally:
            conn.close()


def load_spectro_settings():
    """Devuelve {commands_port, events_port} -- siempre las dos keys
    presentes, mergeadas con default si no estan guardadas (mismo criterio
    que load_furnace_state: el llamador nunca necesita chequear ausencia)."""
    _init_db()
    with _db_lock:
        conn = _get_conn()
        try:
            row = conn.execute("SELECT value FROM meta WHERE key='spectro_settings'").fetchone()
            data = {}
            if row is not None:
                try:
                    data = json.loads(row["value"])
                except Exception:
                    data = {}
            merged = dict(_SPECTRO_SETTINGS_DEFAULTS)
            if isinstance(data, dict):
                merged.update({k: v for k, v in data.items() if k in _SPECTRO_SETTINGS_DEFAULTS})
            return merged
        finally:
            conn.close()


def save_spectro_settings(settings):
    _init_db()
    merged = dict(_SPECTRO_SETTINGS_DEFAULTS)
    if isinstance(settings, dict):
        merged.update({k: v for k, v in settings.items() if k in _SPECTRO_SETTINGS_DEFAULTS})
    with _db_lock:
        conn = _get_conn()
        try:
            with conn:
                conn.execute(
                    "INSERT OR REPLACE INTO meta VALUES('spectro_settings', ?)",
                    (json.dumps(merged, ensure_ascii=False),),
                )
        finally:
            conn.close()


# ---------- Informes de calidad (Calidad > informes finales por material) ----------

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
    """Reemplaza todos los informes (igual patron delete+reinsert que
    save_alloys/save_thermal_device_records). A cada informe sin "id" (o con
    un id repetido dentro de la misma lista) se le asigna un UUID nuevo acá
    mismo, mutando el dict `r` in-place - por eso el llamador puede terminar
    viendo ids nuevos despues de guardar."""
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
    """Crea (si hace falta) y devuelve la carpeta donde se copian las
    imagenes adjuntas a los informes de Calidad (~/ajuste_comp_quality_images) -
    esas imagenes viven como archivos sueltos en disco, no dentro de la DB."""
    os.makedirs(QUALITY_IMAGES_DIR, exist_ok=True)
    return QUALITY_IMAGES_DIR


# ---------- Estado pie de horno (snapshot en vivo para el kiosco Raspberry) ----------
# Fila unica (id=1) que Ajuste sobreescribe cada vez que cambia colada/
# objetivo/composicion - es lo que consume host_api.py para servirselo al
# cliente web del Pie de Horno.

def load_furnace_state():
    """Siempre devuelve la forma completa de _empty_furnace_state(), aunque
    no haya nada guardado todavia o el JSON guardado le falten campos (el
    dict vacio se usa como base y se le pisan encima los campos que si
    estan guardados) - asi el llamador nunca tiene que chequear claves
    faltantes."""
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
    """Vuelve la fila unica de furnace_state a su forma vacia (se usa al
    resetear/cancelar la sesion en Ajuste, para que el kiosco deje de
    mostrar datos de una colada que ya no esta activa)."""
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


# ---------- Conteo de cucharas (Pie de Horno / Raspberry) ----------
# "current" (tabla ladles_current, fila unica id=1) es el conteo de la
# colada que se esta llenando AHORA - contadores por material mas una lista
# de eventos con timestamp (cada +/- del operador). Cuando una colada se
# cierra, ese conteo pasa a "history_by_colada" (tabla ladles_history,
# indexada por colada normalizada) para consulta posterior desde
# Historicos/Estadisticas.

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
    """Guarda "current" (siempre se pisa entera) y sincroniza
    "history_by_colada" contra la tabla: a diferencia de otras funciones de
    este archivo, ACA SI se hace upsert/delete selectivo en vez de borrar
    todo y reinsertar, porque history_by_colada puede tener muchas entradas
    y el llamador (tab_historicos.py) solo manda el dict completo en
    memoria - conviene diffear contra lo que ya esta en la tabla en vez de
    reescribir todo el historial de cucharas en cada guardado."""
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
    """Borra el registro de cucharas de una colada especifica (llamado por
    delete_session al borrar una sesion de Historicos) y, si esa colada es
    la que esta activa ahora mismo en ladles_current, limpia sus contadores
    tambien. Prueba tanto la clave normalizada como el texto crudo de
    colada por las dudas de que algun registro viejo se haya guardado sin
    normalizar."""
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
    """Borra de ladles_history cualquier colada que ya NO tenga una sesion
    correspondiente en `sessions` (la lista de Historicos). Es una limpieza
    de huerfanos "de respaldo" ademas de delete_ladles_for_colada: cubre el
    caso de coladas borradas por otra via (edicion manual de la DB, o un
    borrado que no paso por delete_session)."""
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


# ---------- Dispositivos Pie de Horno (clientes web aprobados del kiosco) ----------
# Cada navegador/tablet que se conecta a la web del Pie de Horno se registra
# aca (host_api.py) como "pending" hasta que un operador lo aprueba desde el
# tab Pie de Horno; el "role" (viewer/editor) controla si puede solo mirar o
# tambien tocar los botones +/- de cucharas.

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
    """Reemplaza toda la tabla de dispositivos (delete+reinsert, igual
    patron que save_alloys)."""
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


# ---------- Inoculación: etapas y unidades configurables (Catalogo) ----------
# Al igual que el historial de IPs mas arriba, esto vive en JSON sueltos
# (~/ajuste_comp_inoc_momentos.json, ~/ajuste_comp_inoc_units.json) en vez
# de SQLite - son listas chicas de configuracion (que tan lejos esta el
# molde/horno/cuchara y en que unidad se dosifica el inoculante) editadas
# ocasionalmente desde Catalogo, no datos operativos de alto volumen.
# save_inoc_momentos/save_inoc_units escriben con archivo temporal +
# os.replace (escritura atomica: si se corta la luz a mitad de escritura no
# queda un JSON corrupto a medio escribir) - un patron mas prolijo que el
# usado para el historial de IPs.

_INOC_MOMENTOS_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_inoc_momentos.json")
_DEFAULT_INOC_MOMENTOS = [
    {"key": "horno",          "label": "Horno",      "masa_default": 50},
    {"key": "cuchara_transp", "label": "C. transp.", "masa_default": 50},
    {"key": "cuchara_colar",  "label": "C. colar",   "masa_default": 50},
]

def resolve_inoc_protocol(inoculacion_meta, base=None):
    """
    Devuelve la lista de entradas de protocolo para el material+base dados.
    Si existe un protocolo específico para 'base' en por_base, lo usa.
    Si no, devuelve el protocolo por defecto (inoculacion).
    Retrocompatible: si inoculacion_meta no tiene por_base, devuelve inoculacion.
    """
    if not isinstance(inoculacion_meta, dict):
        return []
    if base:
        base = str(base).strip()
        por_base = inoculacion_meta.get("por_base", {})
        if isinstance(por_base, dict) and base in por_base:
            return list(por_base[base])
    return list(inoculacion_meta.get("inoculacion", []))


def load_inoc_momentos():
    if os.path.exists(_INOC_MOMENTOS_FILE):
        try:
            with open(_INOC_MOMENTOS_FILE, "r", encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, list):
                result = [
                    {"key": str(m["key"]), "label": str(m["label"]),
                     "masa_default": float(m["masa_default"]) if m.get("masa_default") else 50}
                    for m in data
                    if isinstance(m, dict) and m.get("key") and m.get("label")
                ]
                if result:
                    return result
        except Exception:
            pass
    return [dict(m) for m in _DEFAULT_INOC_MOMENTOS]

def save_inoc_momentos(momentos):
    tmp = _INOC_MOMENTOS_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(momentos, f, ensure_ascii=False, indent=2)
    os.replace(tmp, _INOC_MOMENTOS_FILE)



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

