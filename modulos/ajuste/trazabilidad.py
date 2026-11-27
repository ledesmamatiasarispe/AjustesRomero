"""Trazabilidad (ISO 9001:2015, 7.5.3 control de la información documentada y 8.5.2 identificación y trazabilidad).

Antes de esto, casi toda escritura de la app pisaba el registro anterior sin dejar rastro: editar una colada en
Históricos, corregir un informe de Calidad o cambiar el rendimiento de un material del catálogo reemplazaba el dato y
listo -- no quedaba quién lo cambió, cuándo, ni qué decía antes. Un borrado no se podía reconstruir.

Este módulo agrega UNA bitácora (tabla "bitacora") con estas garantías:
  - QUIÉN: el usuario logueado del núcleo (si hay sesión), si no el dispositivo aprobado que hizo el pedido, y si no
    vino de un pedido (hilos de fondo: auto-guardado de sesión, espectrómetro, Carbomax) queda como "Sistema".
  - CUÁNDO y DESDE DÓNDE: fecha/hora del servidor e IP del cliente.
  - QUÉ: entidad + clave (p.ej. sesion / colada 1234) + acción (alta, modificación, baja).
  - CÓMO ERA Y CÓMO QUEDÓ: en un alta se guarda el registro completo tal cual se creó; en una baja, el registro
    completo tal cual era (así un borrado siempre se puede reconstruir); en una modificación solo la lista de campos
    que cambiaron con su valor anterior y el nuevo (las sesiones pesan ~200 KB: guardar las dos copias enteras en cada
    edición haría crecer la base sin aportar nada que el diff no diga).
  - POR QUÉ: el motivo que escribe el usuario (header X-Motivo; las pantallas lo piden al eliminar).
  - INALTERABLE: dos triggers de SQLite rechazan cualquier UPDATE o DELETE sobre la tabla, y cada fila guarda el
    SHA-256 de su contenido encadenado con el de la anterior -- si alguien edita la base por fuera (con un editor de
    SQLite, borrando los triggers), verificar_cadena() detecta en qué registro se rompió.

El registro se escribe con la MISMA conexión y dentro de la MISMA transacción que el cambio (registrar(c, ...)): o
quedan los dos o no queda ninguno. Nunca un cambio sin su rastro, ni un rastro de un cambio que no ocurrió.

Quién actúa se pasa por una contextvar que fijan las dependencias de acceso (dispositivos.require_acceso*): así no
hace falta pasar el actor por las 125 rutas ni por cada función de datos.py."""
import contextvars
import hashlib
import json
from urllib.parse import unquote

from nucleo import db

ESQUEMA = """
CREATE TABLE IF NOT EXISTS bitacora (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    fecha         TEXT NOT NULL,
    actor_tipo    TEXT NOT NULL,
    actor         TEXT NOT NULL,
    actor_id      TEXT,
    dispositivo   TEXT,
    ip            TEXT,
    accion        TEXT NOT NULL,
    entidad       TEXT NOT NULL,
    clave         TEXT,
    colada        TEXT,
    antes         TEXT,
    despues       TEXT,
    cambios       TEXT,
    motivo        TEXT,
    hash_anterior TEXT,
    hash          TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_bitacora_colada ON bitacora (colada);
CREATE INDEX IF NOT EXISTS ix_bitacora_entidad ON bitacora (entidad, clave);
CREATE INDEX IF NOT EXISTS ix_bitacora_fecha ON bitacora (fecha);
CREATE TRIGGER IF NOT EXISTS bitacora_no_se_modifica BEFORE UPDATE ON bitacora
BEGIN
    SELECT RAISE(ABORT, 'La bitacora de trazabilidad no se puede modificar');
END;
CREATE TRIGGER IF NOT EXISTS bitacora_no_se_borra BEFORE DELETE ON bitacora
BEGIN
    SELECT RAISE(ABORT, 'La bitacora de trazabilidad no se puede borrar');
END;
"""

ACCIONES = ("alta", "modificacion", "baja", "inicio")

# Nombres que ve el usuario (pantalla Trazabilidad y CSV). La clave es lo que se guarda en la base.
ENTIDADES = {
    "sesion": "Colada (sesión de ajuste)",
    "ajuste": "Ajuste de una colada",
    "cucharas": "Cucharas de una colada",
    "cucharas_en_curso": "Cucharas (colada en curso)",
    "informe_calidad": "Informe de calidad",
    "material": "Material del catálogo",
    "carga": "Carga guardada",
    "configuracion": "Configuración",
    "cucharas_base": "Cucharas por base",
    "dispositivo": "Dispositivo",
    "bitacora": "Bitácora",
}

SISTEMA = {"tipo": "sistema", "nombre": "Sistema (automático)", "id": "", "dispositivo": "", "ip": ""}

_actor = contextvars.ContextVar("acomp_trazabilidad_actor", default=None)
_motivo = contextvars.ContextVar("acomp_trazabilidad_motivo", default="")

MOTIVO_MAX = 500


# ---------- quién actúa ----------

def fijar_actor(usuario: dict | None, device: dict | None, ip: str = "", motivo: str = "") -> None:
    """Lo llaman las dependencias de acceso al principio de cada pedido. Se fija SIEMPRE (también en lecturas): así
    un valor de un pedido anterior nunca puede quedar colgado en este."""
    device = device or {}
    nombre_disp = str(device.get("name") or "").strip()
    if usuario:
        nombre = str(usuario.get("nombre") or "").strip()
        login = str(usuario.get("usuario") or "").strip()
        actor = {"tipo": "usuario", "nombre": f"{nombre} ({login})" if nombre and nombre != login else login,
                 "id": str(usuario.get("id") or ""), "dispositivo": nombre_disp, "ip": ip}
    elif device.get("id"):
        actor = {"tipo": "dispositivo", "nombre": nombre_disp or str(device.get("id")),
                 "id": str(device.get("id")), "dispositivo": nombre_disp, "ip": ip}
    else:
        actor = {**SISTEMA, "ip": ip}
    _actor.set(actor)
    _motivo.set(limpiar_motivo(motivo))


def limpiar_motivo(motivo) -> str:
    texto = unquote(str(motivo or ""))
    return " ".join(texto.split())[:MOTIVO_MAX]


def actor_actual() -> dict:
    return _actor.get() or dict(SISTEMA)


def motivo_actual() -> str:
    return _motivo.get() or ""


# ---------- diferencias ----------

def _ruta(base: str, parte) -> str:
    if isinstance(parte, int):
        return f"{base}[{parte}]"
    return f"{base}.{parte}" if base else str(parte)


def diferencias(antes, despues, ruta: str = "", limite: int = 400) -> list:
    """Campos que cambiaron, como [{"campo": "ajustes[2].kg.FeSi", "antes": 1.5, "despues": 2.0}, ...]. Baja por
    dicts y listas; todo lo demás se compara por valor. `limite` corta el detalle si cambió casi todo (p.ej. se
    reemplazó una lista entera): el último elemento avisa cuántos cambios más hubo."""
    salida: list = []

    def recorrer(a, b, r):
        if a == b:
            return
        if isinstance(a, dict) and isinstance(b, dict):
            for k in list(a.keys()) + [k for k in b.keys() if k not in a]:
                recorrer(a.get(k), b.get(k), _ruta(r, k))
            return
        if isinstance(a, list) and isinstance(b, list):
            for i in range(max(len(a), len(b))):
                recorrer(a[i] if i < len(a) else None, b[i] if i < len(b) else None, _ruta(r, i))
            return
        salida.append({"campo": r or "(registro)", "antes": a, "despues": b})

    recorrer(antes, despues, ruta)
    if len(salida) > limite:
        resto = len(salida) - limite
        salida = salida[:limite] + [{"campo": f"(y {resto} cambios más)", "antes": None, "despues": None}]
    return salida


# ---------- escribir ----------

def _json(v):
    return None if v is None else json.dumps(v, ensure_ascii=False, sort_keys=True, default=str)


def _hash(fila: dict) -> str:
    contenido = json.dumps({k: fila.get(k) for k in _CAMPOS_HASH}, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()


_CAMPOS_HASH = ("fecha", "actor_tipo", "actor", "actor_id", "dispositivo", "ip", "accion", "entidad", "clave",
                "colada", "antes", "despues", "cambios", "motivo", "hash_anterior")


def registrar(c, accion: str, entidad: str, clave="", *, antes=None, despues=None, colada: str = "",
              motivo: str | None = None) -> bool:
    """Deja UN registro en la bitácora con la conexión `c` (la de la transacción del cambio). No registra nada si
    antes y después son iguales (un "guardar" sin cambios no es un evento). Devuelve si registró."""
    if accion not in ACCIONES:
        raise ValueError(f"accion de bitacora invalida: {accion}")
    if accion == "modificacion":
        cambios = diferencias(antes, despues)
        if not cambios:
            return False
        antes_txt, despues_txt, cambios_txt = None, None, _json(cambios)
    elif accion == "alta":
        antes_txt, despues_txt, cambios_txt = None, _json(despues), None
    elif accion == "baja":
        antes_txt, despues_txt, cambios_txt = _json(antes), None, None
    else:
        antes_txt, despues_txt, cambios_txt = _json(antes), _json(despues), None

    actor = actor_actual()
    previo = c.execute("SELECT hash FROM bitacora ORDER BY id DESC LIMIT 1").fetchone()
    fila = {
        "fecha": db.ahora(), "actor_tipo": actor["tipo"], "actor": actor["nombre"], "actor_id": actor.get("id", ""),
        "dispositivo": actor.get("dispositivo", ""), "ip": actor.get("ip", ""),
        "accion": accion, "entidad": entidad, "clave": str(clave or ""), "colada": str(colada or ""),
        "antes": antes_txt, "despues": despues_txt, "cambios": cambios_txt,
        "motivo": limpiar_motivo(motivo_actual() if motivo is None else motivo),
        "hash_anterior": previo["hash"] if previo else "",
    }
    fila["hash"] = _hash(fila)
    columnas = ", ".join(fila)
    c.execute(f"INSERT INTO bitacora ({columnas}) VALUES ({', '.join('?' * len(fila))})", tuple(fila.values()))
    return True


def registrar_cambio(c, entidad: str, clave, antes, despues, *, colada: str = "") -> bool:
    """Alta, baja o modificación según qué lado falte."""
    if antes is None and despues is None:
        return False
    if antes is None:
        return registrar(c, "alta", entidad, clave, despues=despues, colada=colada)
    if despues is None:
        return registrar(c, "baja", entidad, clave, antes=antes, colada=colada)
    return registrar(c, "modificacion", entidad, clave, antes=antes, despues=despues, colada=colada)


def registrar_coleccion(c, entidad: str, antes: dict, despues: dict, colada_de=None) -> int:
    """Para las funciones que reemplazan una colección entera (catálogo de materiales, informes de calidad): compara
    elemento por elemento por su clave y registra solo lo que de verdad se agregó, se sacó o cambió."""
    colada_de = colada_de or (lambda v: "")
    n = 0
    for clave in list(antes.keys()) + [k for k in despues.keys() if k not in antes]:
        a, d = antes.get(clave), despues.get(clave)
        if registrar_cambio(c, entidad, clave, a, d, colada=colada_de(d if d is not None else a)):
            n += 1
    return n


def iniciar(c) -> None:
    """Primer registro de la bitácora (una sola vez por base): deja constancia de desde cuándo hay trazabilidad y de
    qué había en ese momento, para que una auditoría no confunda "sin registros" con "sin cambios"."""
    if c.execute("SELECT 1 FROM bitacora LIMIT 1").fetchone():
        return
    conteo = {}
    for tabla in ("sessions", "quality_reports", "alloys", "ladles_history", "cargas_guardadas", "devices"):
        try:
            conteo[tabla] = c.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
        except Exception:
            pass
    _actor.set(dict(SISTEMA))
    registrar(c, "inicio", "bitacora", "inicio", despues={"registros_existentes": conteo},
              motivo="Inicio de la trazabilidad: los registros anteriores a esta fecha no tienen historial de cambios.")
    _actor.set(None)


# ---------- leer ----------

def _fila_a_dict(row, completo: bool = False) -> dict:
    d = {k: row[k] for k in row.keys() if k not in ("antes", "despues", "cambios")}
    d["entidad_nombre"] = ENTIDADES.get(row["entidad"], row["entidad"])
    cambios = json.loads(row["cambios"]) if row["cambios"] else None
    d["resumen"] = _resumen(row["accion"], cambios)
    if completo:
        d["antes"] = json.loads(row["antes"]) if row["antes"] else None
        d["despues"] = json.loads(row["despues"]) if row["despues"] else None
        d["cambios"] = cambios
    return d


def _resumen(accion: str, cambios) -> str:
    if accion != "modificacion" or not cambios:
        return ""
    campos = [ch["campo"] for ch in cambios if not ch["campo"].startswith("(y ")]
    texto = ", ".join(campos[:4])
    if len(cambios) > 4:
        texto += f" y {len(cambios) - 4} más"
    return texto


def consultar(*, colada: str = "", entidad: str = "", actor: str = "", accion: str = "", desde: str = "",
              hasta: str = "", texto: str = "", limite: int = 500) -> list:
    filtros, params = [], []
    if colada:
        filtros.append("(colada = ? OR clave = ?)")
        params += [colada, colada]
    if entidad:
        filtros.append("entidad = ?")
        params.append(entidad)
    if accion:
        filtros.append("accion = ?")
        params.append(accion)
    if actor:
        filtros.append("(actor LIKE ? OR dispositivo LIKE ?)")
        params += [f"%{actor}%", f"%{actor}%"]
    if desde:
        filtros.append("fecha >= ?")
        params.append(desde)
    if hasta:
        filtros.append("fecha < ?")
        params.append(hasta)
    if texto:
        filtros.append("(clave LIKE ? OR motivo LIKE ? OR cambios LIKE ?)")
        params += [f"%{texto}%"] * 3
    where = f"WHERE {' AND '.join(filtros)}" if filtros else ""
    limite = max(1, min(int(limite or 500), 5000))
    with db.transaccion() as c:
        rows = c.execute(f"SELECT * FROM bitacora {where} ORDER BY id DESC LIMIT ?", (*params, limite)).fetchall()
    return [_fila_a_dict(r) for r in rows]


def detalle(registro_id: int) -> dict | None:
    with db.transaccion() as c:
        row = c.execute("SELECT * FROM bitacora WHERE id=?", (registro_id,)).fetchone()
    return _fila_a_dict(row, completo=True) if row else None


def verificar_cadena() -> dict:
    """Recalcula el hash de cada registro y su encadenamiento. Si alguien editó o borró un registro por fuera de la
    app, devuelve el primero donde se rompe."""
    with db.transaccion() as c:
        rows = c.execute("SELECT * FROM bitacora ORDER BY id").fetchall()
    anterior = ""
    for row in rows:
        fila = {k: row[k] for k in row.keys()}
        if fila["hash_anterior"] != anterior:
            return {"integra": False, "registros": len(rows), "registro_id": row["id"],
                    "detalle": "Falta un registro anterior o se alteró el orden (cadena cortada)."}
        if _hash(fila) != fila["hash"]:
            return {"integra": False, "registros": len(rows), "registro_id": row["id"],
                    "detalle": "El contenido de este registro se modificó después de escribirse."}
        anterior = fila["hash"]
    return {"integra": True, "registros": len(rows), "registro_id": None, "detalle": ""}
