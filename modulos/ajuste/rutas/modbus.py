# rutas/modbus.py -- puerto sin cambios de backend/routers/modbus.py de ajuste_comp_web. Pestaña "Delta
# Modbus" -- lectura cruda RS485/Modbus RTU del CARBOMAX DELTA (COM3, ver ..carbomax_modbus.py para el
# protocolo). No es un puerto de la app de escritorio: tooling nuevo para seguir explorando el mapa de
# registros a mano. Router delgado a propósito: toda la lógica del protocolo vive en carbomax_modbus.py.
from fastapi import APIRouter, Body, Depends

from .. import carbomax_modbus
from .. import dispositivos as devices

router = APIRouter(prefix="/api/modbus", tags=["modbus"])


@router.post("/read")
def read(payload: dict = Body(default={}), _: dict = Depends(devices.require_acceso_editor)):
    try:
        start = max(0, int(payload.get("start", 0)))
    except (TypeError, ValueError):
        start = 0
    try:
        count = int(payload.get("count", 32))
    except (TypeError, ValueError):
        count = 32
    return {"start": start, "results": carbomax_modbus.leer_todo(start_address=start, quantity=count)}
