"""Aprobación por dispositivo -- puerto de backend/devices.py de ajuste_comp_web, CAPA ADICIONAL propia del módulo
que convive con el login del núcleo (decisión del usuario, 24/11/2026): las pantallas de planta (PC de laboratorio,
tablets, la Raspberry del horno) siguen sin pedir usuario/contraseña, solo se aprueban una vez desde la administración
de dispositivos. El login de nucleo.auth sigue existiendo (lo trae el núcleo), pero esta app no lo exige en sus
propias rutas -- usa require_approved_device/require_editor_device, como siempre.

Cambios reales contra el original (no solo traducción de import):
  - Antes cada función hacía load_devices_state()/save_devices_state() -- traía la tabla "devices" ENTERA a un dict
    de Python, mutaba una entrada y volvía a escribir toda la tabla. Eso tenía sentido cuando storage.py guardaba
    casi todo como un blob JSON por tabla, pero "devices" siempre tuvo columnas propias de verdad (device_id es la
    primary key). Acá se lee/escribe fila por fila, con nucleo.db.transaccion() (BEGIN IMMEDIATE, serializa
    escritores) en vez del RLock de módulo que usaba la app vieja -- mismo dato, sin la carrera de "leo la tabla
    entera, el otro escribe, yo piso su cambio al guardar la tabla entera de vuelta".
  - DEV_SKIP_APPROVAL default pasa a "0" (apagado): la app vieja lo dejaba en "1" por defecto y esto ya se detectó
    como una exposición real (CLAUDE.md de ajuste_comp_web, servidor bindeado a 0.0.0.0 + bypass de aprobación
    prendido sin querer). La variable de entorno pasa a llamarse ACOMP_DEV_SKIP_APPROVAL (via nucleo.ajustes.env,
    mismo prefijo que el resto de la configuración de esta app) en vez de AJUSTE_WEB_DEV_SKIP_APPROVAL."""
import re
from datetime import datetime

from fastapi import Depends, Header, HTTPException, Request

from nucleo import db
from nucleo.ajustes import env

DEV_SKIP_APPROVAL = env("DEV_SKIP_APPROVAL", "0") != "0"

DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,80}$")
DEVICE_NAME_MAX_LEN = 80
DEVICE_ROLES = ("viewer", "editor")


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _safe_device_name(value):
    text = str(value or "").strip()
    text = " ".join(text.split())
    return text[:DEVICE_NAME_MAX_LEN] or "Dispositivo sin nombre"


def valid_device_id(device_id):
    return bool(DEVICE_ID_RE.match(str(device_id or "").strip()))


def _row_to_dict(row):
    return {
        "id": row["device_id"], "name": row["name"], "status": row["status"], "role": row["role"],
        "first_seen": row["first_seen"], "last_seen": row["last_seen"],
        "ip": row["ip"], "user_agent": row["user_agent"],
    }


def register_or_touch_device(device_id, name="", user_agent="", ip=""):
    """Crea el dispositivo si no existe (queda en 'pending'), o si ya existe solo actualiza
    last_seen/ip/user_agent -- nunca pisa el status ni el role ya asignados por un administrador.

    Bootstrap: el primer dispositivo que se registra en toda la vida de la app (la tabla está vacía) se
    auto-aprueba como editor -- esta app no tiene una puerta de atrás de escritorio para aprobar el primero a mano."""
    device_id = str(device_id or "").strip()
    if not valid_device_id(device_id):
        return None

    now = _now_iso()
    with db.transaccion() as c:
        es_el_primero = not c.execute("SELECT 1 FROM devices LIMIT 1").fetchone()
        actual = c.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()

        if es_el_primero and actual is None:
            status, role = "approved", "editor"
        elif actual is not None:
            status = actual["status"] if actual["status"] in ("pending", "approved", "revoked") else "pending"
            role = actual["role"] if actual["role"] in DEVICE_ROLES else "viewer"
        else:
            status, role = "pending", "viewer"

        nombre = _safe_device_name(name or (actual["name"] if actual is not None else ""))
        primera_vez = actual["first_seen"] if actual is not None else now
        c.execute("""
            INSERT INTO devices (device_id, name, status, role, first_seen, last_seen, ip, user_agent)
            VALUES (?,?,?,?,?,?,?,?)
            ON CONFLICT(device_id) DO UPDATE SET
                name=excluded.name, status=excluded.status, role=excluded.role,
                last_seen=excluded.last_seen, ip=excluded.ip, user_agent=excluded.user_agent
        """, (device_id, nombre, status, role, primera_vez, now, str(ip or "")[:80], str(user_agent or "")[:240]))
        fila = c.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        return _row_to_dict(fila)


def get_device(device_id):
    device_id = str(device_id or "").strip()
    if not valid_device_id(device_id):
        return None
    with db.transaccion() as c:
        fila = c.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
    return _row_to_dict(fila) if fila else None


def set_device_status(device_id, status):
    if status not in ("pending", "approved", "revoked"):
        raise ValueError("status invalido")
    with db.transaccion() as c:
        actual = c.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if actual is None:
            return None
        role = actual["role"] if actual["role"] in DEVICE_ROLES else "viewer"
        now = _now_iso()
        if status == "approved":
            c.execute("UPDATE devices SET status=?, role=? WHERE device_id=?", (status, role, device_id))
        elif status == "revoked":
            c.execute("UPDATE devices SET status=?, role='viewer' WHERE device_id=?", (status, device_id))
        else:
            c.execute("UPDATE devices SET status=? WHERE device_id=?", (status, device_id))
        fila = c.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        return _row_to_dict(fila)


def set_device_role(device_id, role):
    if role not in DEVICE_ROLES:
        raise ValueError("role invalido")
    with db.transaccion() as c:
        actual = c.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        if actual is None:
            return None
        if role == "editor":
            c.execute("UPDATE devices SET role=?, status='approved' WHERE device_id=?", (role, device_id))
        else:
            c.execute("UPDATE devices SET role=? WHERE device_id=?", (role, device_id))
        fila = c.execute("SELECT * FROM devices WHERE device_id=?", (device_id,)).fetchone()
        return _row_to_dict(fila)


def delete_device(device_id):
    with db.transaccion() as c:
        c.execute("DELETE FROM devices WHERE device_id=?", (device_id,))


def list_devices():
    with db.transaccion() as c:
        filas = c.execute("SELECT * FROM devices").fetchall()
    return {row["device_id"]: _row_to_dict(row) for row in filas}


# ---------- Dependencias FastAPI ----------

def _client_ip(request: Request):
    forwarded = str(request.headers.get("x-forwarded-for", "") or "").split(",")[0].strip()
    if forwarded:
        return forwarded
    return str(request.client.host) if request.client else ""


def current_device(
    request: Request,
    x_pie_device_id: str = Header(default=""),
    x_pie_device_name: str = Header(default=""),
):
    """Registra/actualiza el dispositivo en cada request y lo devuelve tal cual está en la DB, sin exigir
    aprobación todavía -- usar require_approved_device/require_editor_device para rutas que sí necesitan bloquear."""
    device_id = x_pie_device_id.strip()
    device_name = x_pie_device_name.strip()
    return register_or_touch_device(
        device_id, device_name, request.headers.get("user-agent", ""), _client_ip(request),
    )


def require_approved_device(device: dict = Depends(current_device)):
    if DEV_SKIP_APPROVAL:
        return device or {"id": "dev-mode", "status": "approved", "role": "editor"}
    if not device or device.get("status") != "approved":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "device_not_approved",
                "status": (device or {}).get("status", "pending"),
                "message": "Este dispositivo debe aprobarse desde la página de administración.",
            },
        )
    return device


def usuario_opcional(authorization: str | None = Header(None)):
    """La sesión del núcleo (usuario logueado) si vino una válida; None si no vino o venció -- sin lanzar 401:
    quien llama decide si con eso alcanza o si cae a la aprobación del dispositivo."""
    if not authorization:
        return None
    from nucleo import auth  # tarde: auth usa la base, que se configura al arrancar
    try:
        return auth.sesion(authorization)
    except HTTPException:
        return None


# Pestañas de la app (todo menos el kiosco de Pie de Horno): pasa un usuario logueado, o -- como antes -- un
# dispositivo aprobado sin sesión (así las pantallas que se abren sin login, como el kiosco, pueden seguir leyendo
# lo que necesitan de otras rutas). La aprobación por dispositivo queda para el kiosco (rutas/kiosk.py, que sigue
# usando require_approved_device / require_editor_device): es la pantalla fija al pie del horno, sin nadie logueado.
def require_acceso(device: dict = Depends(current_device), usuario: dict | None = Depends(usuario_opcional)):
    if usuario:
        return device or {}
    return require_approved_device(device)


def require_acceso_editor(device: dict = Depends(current_device), usuario: dict | None = Depends(usuario_opcional)):
    if usuario:
        return device or {}
    return require_editor_device(require_approved_device(device))


def require_editor_device(device: dict = Depends(require_approved_device)):
    if DEV_SKIP_APPROVAL:
        return device
    if device.get("role") != "editor":
        raise HTTPException(
            status_code=403,
            detail={
                "error": "read_only",
                "status": "approved",
                "role": device.get("role", "viewer"),
                "message": "Este dispositivo solo puede ver.",
            },
        )
    return device
