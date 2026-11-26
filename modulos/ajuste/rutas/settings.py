# rutas/settings.py -- puerto 1:1 de backend/routers/settings.py de ajuste_comp_web. Lo poco que sigue
# siendo funcionalidad real en la web (auto_save_hours, debug_mode) -- el resto de la vieja pestaña "Opciones"
# de escritorio no aplica. En el frontend esto NO es una pestaña propia: se agrega como una tarjeta más dentro
# de la pantalla "Opciones" que ya trae el núcleo (Nucleo.tarjetasOpciones), en vez de duplicar esa pantalla.
from fastapi import APIRouter, Body, Depends

from .. import datos
from .. import dispositivos as devices

router = APIRouter(prefix="/api/settings", tags=["settings"])


@router.get("")
def get_settings(_: dict = Depends(devices.require_acceso)):
    return datos.load_settings()


@router.post("")
def update_settings(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    current = datos.load_settings()
    if "auto_save_hours" in payload:
        try:
            value = max(1.0, min(24.0, float(payload["auto_save_hours"])))
        except (TypeError, ValueError):
            value = current["auto_save_hours"]
        current["auto_save_hours"] = value
    if "debug_mode" in payload:
        current["debug_mode"] = bool(payload["debug_mode"])
    return datos.save_settings(current)
