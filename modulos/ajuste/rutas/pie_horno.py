# rutas/pie_horno.py -- puerto de la parte "/api/pie-horno" de backend/routers/pie_horno.py de
# ajuste_comp_web (la parte "/api/devices" -- aprobar/revocar/asignar rol -- ya está en rutas/dispositivos.py,
# portada en la fase 2 de esta migración). Esto es: la URL local para tipear en el navegador kiosko de la
# Raspberry, y el control remoto por SSH del kiosko físico (ver ..raspberry_ssh.py).
import socket

from fastapi import APIRouter, Depends, HTTPException, Request

from .. import dispositivos as devices
from .. import raspberry_ssh

router = APIRouter(prefix="/api/pie-horno", tags=["pie-horno"])


def _local_ip():
    """IP de esta PC en la red local (no la pública), para armar la URL que hay que tipear en el navegador
    de la Raspberry."""
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        try:
            sock.close()
        except Exception:
            pass


@router.get("/local-url")
def local_url(request: Request, _: dict = Depends(devices.require_acceso)):
    """URL que hay que tipear en el navegador kiosko de la Raspberry -- apunta directo a kiosk.html (no a
    "/", que en esta app abre el shell del núcleo) con ?kiosk=raspi para los ajustes de tamaño específicos
    de esa pantalla. Usa request.url.port (el puerto real con el que este navegador llegó al servidor) en
    vez de un 50506 hardcodeado -- esta app puede caer en otro puerto si el 50506 ya está ocupado (ver
    nucleo.puerto.al_arrancar), y el valor hardcodeado de la app vieja quedaría mal ahí."""
    port = request.url.port or 50506
    return {"url": f"http://{_local_ip()}:{port}/kiosk.html?kiosk=raspi"}


@router.get("/raspberry/status")
def raspberry_status(_: dict = Depends(devices.require_acceso)):
    """Bloqueante (SSH real) a propósito -- FastAPI corre los endpoints 'def' sincronos en threadpool."""
    return raspberry_ssh.get_status()


@router.post("/raspberry/{action}")
def raspberry_action(action: str, _: dict = Depends(devices.require_acceso_editor)):
    if action not in raspberry_ssh.RASPBERRY_ACTIONS:
        raise HTTPException(status_code=400, detail={"error": "accion_invalida"})
    return raspberry_ssh.run_action(action)
