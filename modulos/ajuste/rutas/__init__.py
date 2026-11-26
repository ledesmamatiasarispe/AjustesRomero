"""Router combinado del módulo "ajuste": un archivo por dominio (mismo recorte que backend/routers/*.py en
ajuste_comp_web, para que la traducción sea 1:1 y fácil de rastrear), todos con su propio prefix "/api/...", más
/api/meta y la ruta de WebSocket (que no llevan prefix). Modulo solo acepta UN router, así que este paquete los
junta en uno solo."""
from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from ..config import ELEMENTS
from ..ws import hub
from . import ajuste, calidad, camara, catalogo, dashboard, dispositivos, fundiciones, historicos, informes, kiosk, modbus, pie_horno, settings, termico

router = APIRouter()
router.include_router(dispositivos.router)
router.include_router(dashboard.router)
router.include_router(catalogo.router)
router.include_router(settings.router)
router.include_router(historicos.router)
router.include_router(informes.router)
router.include_router(termico.router)
router.include_router(pie_horno.router)
router.include_router(calidad.router)
router.include_router(kiosk.router)
router.include_router(modbus.router)
router.include_router(fundiciones.router)
router.include_router(camara.router)
router.include_router(ajuste.router)

# Tipos de material del catálogo (no la composición química -- eso ya lo sabe el frontend por ELEMENTS). Se
# expone en vez de duplicarla a mano en JS, para que no se desincronice de config.py.
ALLOY_TYPES = ["Ferroaleación", "Metal puro", "Recorte", "Retorno", "Aditivo",
               "Aleación propia", "Aleación final", "Otro"]


@router.get("/api/meta")
def meta():
    return {"elements": ELEMENTS, "alloy_types": ALLOY_TYPES}


@router.websocket("/ws/{channel}")
async def ws_endpoint(websocket: WebSocket, channel: str):
    """Canal genérico: el frontend abre /ws/ajuste, /ws/cucharas, /ws/devices, etc. según qué pantalla esté
    mirando. No hace falta un endpoint por dominio -- el "channel" de la URL alcanza para que hub.broadcast(channel,
    ...) le llegue solo a quien está escuchando eso. Portado sin cambios de main.py de ajuste_comp_web."""
    await hub.connect(channel, websocket)
    try:
        while True:
            # No se espera nada del cliente en este canal; el receive_text solo sirve para detectar la
            # desconexión (WebSocketDisconnect).
            await websocket.receive_text()
    except WebSocketDisconnect:
        await hub.disconnect(channel, websocket)
