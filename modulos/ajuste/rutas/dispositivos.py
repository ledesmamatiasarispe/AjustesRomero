"""Administración de dispositivos (aprobar/revocar/asignar rol) -- puerto de la parte "/api/devices" de
backend/routers/pie_horno.py de ajuste_comp_web. El control SSH de la Raspberry y la URL local (/api/pie-horno/...)
quedan para la fase del kiosko -- esto es solo la aprobación por dispositivo en sí, que dispositivos.py ya tiene
lista desde la fase 2."""
from fastapi import APIRouter, Depends, HTTPException

from .. import dispositivos as devices
from ..ws import hub

router = APIRouter(prefix="/api/devices", tags=["devices"])


@router.get("/me")
def my_status(device: dict = Depends(devices.current_device), usuario: dict | None = Depends(devices.usuario_opcional)):
    """Cualquier dispositivo (incluso 'pending') puede consultar su propio estado -- es lo que la página usa para
    saber si mostrar 'esperando aprobación' o dejar pasar al resto de la app.

    "status"/"role" son el estado REAL guardado, separado de "dev_skip_approval": mientras ese flag esté prendido
    (ver devices.DEV_SKIP_APPROVAL), el backend deja pasar todo igual aunque el dispositivo siga 'pending' de
    verdad -- el frontend usa ese campo para no trabarse esperando una aprobación que ahora mismo no hace falta."""
    if not device:
        raise HTTPException(status_code=400, detail={"error": "invalid_device_id"})
    return {
        "id": device.get("id"),
        "name": device.get("name"),
        "status": device.get("status", "pending"),
        "role": device.get("role", "viewer"),
        "dev_skip_approval": devices.DEV_SKIP_APPROVAL,
        # Hay un usuario logueado: las pestañas no esperan la aprobación del dispositivo (devices.require_acceso).
        # El kiosco de Pie de Horno no manda sesión, así que para él esto siempre es False.
        "por_usuario": usuario is not None,
    }


@router.get("")
def list_devices(_: dict = Depends(devices.require_acceso_editor)):
    return {"devices": devices.list_devices()}


@router.post("/{device_id}/approve")
async def approve(device_id: str, _: dict = Depends(devices.require_acceso_editor)):
    updated = devices.set_device_status(device_id, "approved")
    if updated is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    await hub.broadcast("devices", {"type": "devices_changed"})
    return updated


@router.post("/{device_id}/revoke")
async def revoke(device_id: str, _: dict = Depends(devices.require_acceso_editor)):
    updated = devices.set_device_status(device_id, "revoked")
    if updated is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    await hub.broadcast("devices", {"type": "devices_changed"})
    return updated


@router.post("/{device_id}/role/{role}")
async def set_role(device_id: str, role: str, _: dict = Depends(devices.require_acceso_editor)):
    try:
        updated = devices.set_device_role(device_id, role)
    except ValueError as ex:
        raise HTTPException(status_code=400, detail={"error": str(ex)}) from ex
    if updated is None:
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    await hub.broadcast("devices", {"type": "devices_changed"})
    return updated


@router.delete("/{device_id}")
async def delete(device_id: str, _: dict = Depends(devices.require_acceso_editor)):
    devices.delete_device(device_id)
    await hub.broadcast("devices", {"type": "devices_changed"})
    return {"ok": True}
