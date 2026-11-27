"""Esquema del módulo "ajuste": las tablas de negocio de ajuste_comp_web, portadas tal cual existen hoy en la base
real (~/ajuste_comp.db) -- ver backend/core/storage.py::_create_tables de la app vieja, que es la fuente de verdad de
estas columnas.

Dos cosas que NO se portan porque el núcleo ya las da:
  - La tabla "meta" (key/value) de la app vieja hace lo mismo que la tabla "config" del núcleo. En vez de duplicarla,
    migrar() copia a "config" las claves que todavía hacen falta ("settings", "thermal_ips", "camera_calibrations")
    la primera vez que corre contra una base vieja, y no toca "migrated" (era un flag interno del import JSON->SQLite
    de la app vieja, ya no aplica). La tabla "meta" vieja queda en la base, sin usar -- no se borra nada.
  - Usuarios/sesiones: la app vieja no tenía ninguno (auth por dispositivo, no por login); no hay nada que convertir.

columnas=[] porque esta base no evolucionó nunca por ALTER TABLE -- el único CREATE TABLE IF NOT EXISTS de storage.py
ya es la forma final."""
from pathlib import Path

from . import trazabilidad

ESQUEMA = """
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
CREATE TABLE IF NOT EXISTS ajuste_session (
    id   INTEGER PRIMARY KEY,
    data TEXT
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
CREATE TABLE IF NOT EXISTS cucharas_base_config (
    base           TEXT NOT NULL,
    material_final TEXT NOT NULL,
    active         INTEGER NOT NULL DEFAULT 1,
    PRIMARY KEY (base, material_final)
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
CREATE TABLE IF NOT EXISTS cargas_guardadas (
    id         INTEGER PRIMARY KEY AUTOINCREMENT,
    nombre     TEXT,
    created_at TEXT,
    materiales TEXT
);
""" + trazabilidad.ESQUEMA

COLUMNAS: list = []

# Claves de la tabla "meta" vieja que todavía hace falta alguien lea -- las otras (solo "migrated") eran un flag
# interno del import JSON->SQLite de la app vieja, ya cumplido hace rato.
_META_A_CONFIG = ("settings", "thermal_ips", "camera_calibrations")

# ajuste_comp_inoc_momentos.json / ajuste_comp_inoc_units.json (~/, fuera de la DB) -- mismo criterio que "meta":
# el núcleo ya da un key/value ("config"), así que esto entra ahí en vez de inventar un archivo propio nuevo.
# load_inoc_units() de la app vieja no tenía archivo real en este equipo (siempre caía al default hardcodeado), así
# que no hay nada para migrar de esa segunda clave -- el default vive directo en datos.py.
_INOC_MOMENTOS_FILE = Path.home() / "ajuste_comp_inoc_momentos.json"


def migrar(c) -> None:
    """Se corre siempre, al arrancar, dentro de la transacción del núcleo -- tiene que ser idempotente.

    1) Si esta base viene de la app vieja (tiene "meta"), copia a "config" (del núcleo) las claves que todavía no
       estén ahí -- una sola vez por clave, nunca pisa lo que ya haya en "config".
    2) Si existe el JSON viejo de momentos de inoculación y todavía no se migró, lo copia a "config" también.
    3) Limpia el tipo de catálogo "Aleación especial", dado de baja hace tiempo (puerto de
       storage.py::_migrate_types, misma lógica, para que una base vieja importada quede igual que si hubiera
       seguido corriendo contra la app vieja)."""
    tiene_meta = c.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='meta'"
    ).fetchone()
    if tiene_meta:
        for clave in _META_A_CONFIG:
            ya_esta = c.execute("SELECT 1 FROM config WHERE clave=?", (clave,)).fetchone()
            if ya_esta:
                continue
            fila = c.execute("SELECT value FROM meta WHERE key=?", (clave,)).fetchone()
            if fila is not None:
                c.execute("INSERT INTO config (clave, valor) VALUES (?, ?)", (clave, fila["value"]))

    if not c.execute("SELECT 1 FROM config WHERE clave='inoc_momentos'").fetchone() and _INOC_MOMENTOS_FILE.exists():
        import json
        try:
            datos = json.loads(_INOC_MOMENTOS_FILE.read_text(encoding="utf-8"))
        except Exception:
            datos = None
        if isinstance(datos, list) and datos:
            c.execute("INSERT INTO config (clave, valor) VALUES ('inoc_momentos', ?)",
                      (json.dumps(datos, ensure_ascii=False),))

    c.execute("DELETE FROM alloys WHERE tipo='Aleación especial'")

    # 4) Trazabilidad ISO 9001: primer registro de la bitácora (una sola vez por base).
    trazabilidad.iniciar(c)
