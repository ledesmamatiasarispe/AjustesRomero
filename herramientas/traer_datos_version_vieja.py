"""Trae los datos más nuevos de la app vieja (ajuste_comp_web, ~/ajuste_comp.db) a data/ajuste_comp.db de esta app
SIN perder lo que es propio de appbase.

A diferencia de copiar_base_real.py (que reemplaza el archivo entero y sirvió para la carga inicial), esto:
  - reemplaza el contenido de las tablas del negocio (las que existen en las dos bases con el mismo esquema) por
    el de la app vieja;
  - en `devices` hace upsert: actualiza/agrega los de la vieja y CONSERVA los que solo existen acá (dispositivos
    aprobados directamente en esta app);
  - no toca las tablas que solo tiene appbase (usuarios, sesiones, config, archivos... del núcleo).

Antes de escribir:
  - lee la base vieja con la API de backup de sqlite3 a un archivo temporal (foto consistente aunque la app vieja
    esté escribiendo en ese momento; la base vieja se abre en solo lectura);
  - guarda un backup de la base de esta app en data/backups/ajuste_comp_<fecha>.db;
  - aborta si alguna tabla común tiene esquema distinto (no se adivina cómo mapear columnas).
Todo el reemplazo va en UNA transacción: si algo falla, la base de esta app queda como estaba.

Correrlo con ESTA app detenida (si no, la app puede tener en memoria la sesión de ajuste vieja y pisarla):

    python herramientas/traer_datos_version_vieja.py
"""
import sqlite3
import tempfile
from datetime import datetime
from pathlib import Path

ORIGEN = Path.home() / "ajuste_comp.db"
DESTINO = Path(__file__).resolve().parent.parent / "data" / "ajuste_comp.db"
BACKUPS = DESTINO.parent / "backups"

# Tablas con upsert por clave primaria en vez de reemplazo completo (ver docstring).
UPSERT = {"devices"}


def _tablas(conn):
    return {r[0]: r[1] for r in conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}


def _conteo(conn, tabla, esquema="main"):
    return conn.execute(f'SELECT COUNT(*) FROM {esquema}."{tabla}"').fetchone()[0]


def main() -> None:
    if not ORIGEN.exists():
        raise SystemExit(f"No existe {ORIGEN}")
    if not DESTINO.exists():
        raise SystemExit(f"No existe {DESTINO} -- para la carga inicial usar copiar_base_real.py")

    with tempfile.TemporaryDirectory() as tmp:
        foto = Path(tmp) / "vieja.db"
        src = sqlite3.connect(f"file:{ORIGEN.as_posix()}?mode=ro", uri=True)
        dst = sqlite3.connect(foto)
        try:
            src.backup(dst)
        finally:
            dst.close()
            src.close()

        BACKUPS.mkdir(parents=True, exist_ok=True)
        respaldo = BACKUPS / f"ajuste_comp_{datetime.now():%Y%m%d_%H%M%S}.db"
        b_src = sqlite3.connect(DESTINO)
        b_dst = sqlite3.connect(respaldo)
        try:
            b_src.backup(b_dst)
        finally:
            b_dst.close()
            b_src.close()
        print(f"Backup de esta app: {respaldo}")

        conn = sqlite3.connect(DESTINO, isolation_level=None)
        try:
            conn.execute("ATTACH DATABASE ? AS vieja", (str(foto),))
            nuestras = _tablas(conn)
            viejas = {r[0]: r[1] for r in conn.execute(
                "SELECT name, sql FROM vieja.sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
            comunes = sorted(set(nuestras) & set(viejas))
            distintas = [t for t in comunes if nuestras[t] != viejas[t]]
            if distintas:
                raise SystemExit(f"Esquema distinto en {distintas}: no se trae nada.")
            solo_vieja = sorted(set(viejas) - set(nuestras))
            if solo_vieja:
                print(f"Aviso: tablas que solo tiene la vieja (no se traen): {solo_vieja}")

            print(f"{'tabla':<22}{'antes':>8}{'vieja':>8}{'después':>9}")
            conn.execute("BEGIN IMMEDIATE")
            try:
                antes = {t: _conteo(conn, t) for t in comunes}
                for t in comunes:
                    if t in UPSERT:
                        conn.execute(f'INSERT OR REPLACE INTO main."{t}" SELECT * FROM vieja."{t}"')
                    else:
                        conn.execute(f'DELETE FROM main."{t}"')
                        conn.execute(f'INSERT INTO main."{t}" SELECT * FROM vieja."{t}"')
                # Autoincrementales: los contadores de las tablas traídas vienen de la vieja; los demás quedan.
                hay_seq = conn.execute(
                    "SELECT 1 FROM vieja.sqlite_master WHERE name='sqlite_sequence'").fetchone()
                if hay_seq:
                    for nombre, seq in conn.execute("SELECT name, seq FROM vieja.sqlite_sequence").fetchall():
                        if nombre in comunes:
                            conn.execute("DELETE FROM main.sqlite_sequence WHERE name=?", (nombre,))
                            conn.execute("INSERT INTO main.sqlite_sequence(name, seq) VALUES (?, ?)", (nombre, seq))
                for t in comunes:
                    print(f"{t:<22}{antes[t]:>8}{_conteo(conn, t, 'vieja'):>8}{_conteo(conn, t):>9}")
                conn.execute("COMMIT")
            except BaseException:
                conn.execute("ROLLBACK")
                raise
            conn.execute("DETACH DATABASE vieja")
            integridad = conn.execute("PRAGMA integrity_check").fetchone()[0]
            fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            conn.close()

    print(f"integrity_check: {integridad}")
    print(f"foreign_key_check: {'vacío (ok)' if not fk else fk}")
    if integridad != "ok" or fk:
        raise SystemExit(f"Algo quedó mal: restaurar con  copy \"{respaldo}\" \"{DESTINO}\"")
    print("Datos traídos OK.")


if __name__ == "__main__":
    main()
