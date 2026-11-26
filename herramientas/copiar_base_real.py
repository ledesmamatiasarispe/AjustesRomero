"""Copia segura de la base real de ajuste_comp_web (~/ajuste_comp.db, puede estar abierta por la app vieja en este
mismo momento) a data/ajuste_comp.db de esta app -- API de backup de sqlite3 (consistente aunque haya escrituras
concurrentes, a diferencia de copiar el archivo a mano). Imprime los conteos de las tablas principales antes y
después para poder compararlos.

    python herramientas/copiar_base_real.py
"""
import sqlite3
from pathlib import Path

ORIGEN = Path.home() / "ajuste_comp.db"
DESTINO = Path(__file__).resolve().parent.parent / "data" / "ajuste_comp.db"

TABLAS = ["alloys", "sessions", "quality_reports", "furnace_state", "ajuste_session",
          "ladles_current", "ladles_history", "cucharas_base_config", "devices",
          "thermal_records", "cargas_guardadas", "meta"]


def conteos(ruta: Path) -> dict:
    conn = sqlite3.connect(f"file:{ruta.as_posix()}?mode=ro", uri=True)
    try:
        out = {}
        existentes = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
        for t in TABLAS:
            out[t] = conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0] if t in existentes else None
        return out
    finally:
        conn.close()


def main() -> None:
    if not ORIGEN.exists():
        raise SystemExit(f"No existe {ORIGEN}")
    print(f"Origen: {ORIGEN} ({ORIGEN.stat().st_size:,} bytes)")
    antes = conteos(ORIGEN)

    DESTINO.parent.mkdir(parents=True, exist_ok=True)
    if DESTINO.exists():
        DESTINO.unlink()
    origen_conn = sqlite3.connect(f"file:{ORIGEN.as_posix()}?mode=ro", uri=True)
    destino_conn = sqlite3.connect(DESTINO)
    try:
        origen_conn.backup(destino_conn)
    finally:
        destino_conn.close()
        origen_conn.close()

    despues = conteos(DESTINO)
    print(f"Destino: {DESTINO} ({DESTINO.stat().st_size:,} bytes)")
    print(f"{'tabla':<22}{'antes':>10}{'después':>10}")
    ok = True
    for t in TABLAS:
        a, d = antes[t], despues[t]
        marca = "" if a == d else "  <-- DIFIERE"
        if a != d:
            ok = False
        print(f"{t:<22}{str(a):>10}{str(d):>10}{marca}")

    conn = sqlite3.connect(DESTINO)
    try:
        fk = conn.execute("PRAGMA foreign_key_check").fetchall()
        integridad = conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()
    print(f"foreign_key_check: {'vacío (ok)' if not fk else fk}")
    print(f"integrity_check: {integridad}")
    if not ok or fk or integridad != "ok":
        raise SystemExit("La copia no quedó idéntica al original -- no seguir con esta copia.")
    print("Copia verificada OK.")


if __name__ == "__main__":
    main()
