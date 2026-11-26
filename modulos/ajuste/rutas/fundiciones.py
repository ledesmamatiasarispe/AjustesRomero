# rutas/fundiciones.py -- puerto sin cambios de comportamiento de backend/routers/fundiciones.py de
# ajuste_comp_web. Automatización COM de Access ("Fundiciones-2010PRG") -- ver ..fundiciones.py para el
# detalle de la lógica portada (que corre igual que en el original). Este router es la parte fina: valida el
# informe pedido, corre la automatización (bloqueante, puede tardar varios segundos por los
# reintentos/SendKeys) en el threadpool de FastAPI, y serializa las llamadas con un lock -- el original era
# de un solo usuario/hilo de Tkinter tocando una sola sesión de Access; esta versión web puede recibir
# pedidos de varios dispositivos a la vez, y dos automatizaciones COM concurrentes sobre la MISMA instancia
# de Access se pisarían entre sí (SetFocus/SendKeys de una interfiriendo con la otra) -- por eso el lock es
# una adición obligatoria, no un cambio de alcance.
#
# Requiere correr en la PC del laboratorio (Windows, con Access instalado y la unidad de red de Fundiciones
# alcanzable) -- no se puede probar de punta a punta fuera de esa máquina; ver el docstring de
# ..fundiciones.py.
#
# CoInitialize: FastAPI corre estos endpoints "def" (sincrónicos) en el threadpool de anyio, que reparte las
# llamadas entre varios hilos nuevos a medida que hacen falta -- no hay garantía de que dos pedidos
# consecutivos caigan en el mismo hilo. COM exige CoInitialize() en CADA hilo antes de usar un objeto COM
# (GetActiveObject/Dispatch); sin eso, la llamada revienta con "CoInitialize no llamado" apenas el pedido
# cae en un hilo nuevo del pool. _run_locked es el ÚNICO lugar que llama a ..fundiciones.py bajo el lock, así
# que es también el único lugar que necesita CoInitialize/CoUninitialize -- nada más abajo en la pila abre
# threads propios.
import threading

import pythoncom
from fastapi import APIRouter, Body, Depends, HTTPException

from .. import datos
from .. import dispositivos as devices
from .. import fundiciones as com

router = APIRouter(prefix="/api/fundiciones", tags=["fundiciones"])

_ACCESS_LOCK = threading.Lock()


def _find_report(report_id):
    reports = datos.load_quality_reports()
    return next((r for r in reports if r.get("id") == report_id), None)


def _run_locked(run):
    """Corre `run` (callable sin argumentos que hace el trabajo COM y arma la respuesta) serializado contra
    cualquier otra operación de Access en curso, con CoInitialize propio del hilo que atiende este pedido.
    Único punto de entrada a ..fundiciones.py -- ver nota de CoInitialize más arriba."""
    if not _ACCESS_LOCK.acquire(blocking=False):
        raise HTTPException(
            status_code=409,
            detail={"error": "fundiciones_ocupado", "message": "Ya hay una operación con Access en curso desde otro dispositivo. Esperá a que termine."},
        )
    pythoncom.CoInitialize()
    try:
        return run()
    finally:
        pythoncom.CoUninitialize()
        _ACCESS_LOCK.release()


@router.post("/reports/group/load")
def load_report_group(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    """Botón real 'Cargar en Access' aplicado a un GRUPO (los N materiales de una misma colada) -- cargar
    los materiales de una colada de un solo click en vez de uno por uno. Mismo orden que ve la pantalla
    (material, alfabético -- ver buildGroups en calidad.js).

    OJO orden de rutas: esta va ANTES de /reports/{report_id}/load -- Starlette matchea por orden de
    registro, y "/reports/group/load" calza con el patrón "/reports/{report_id}/load" (report_id="group")
    tan bien como con este. Si quedara después, esta ruta quedaría inalcanzable."""
    base = str(payload.get("base", "") or "").strip()
    lote = str(payload.get("lote", "") or "").strip()
    if not base or not lote:
        raise HTTPException(status_code=400, detail={"error": "falta_base_o_lote"})
    reports = datos.load_quality_reports()
    group = sorted(
        (r for r in reports if r.get("base", "") == base and r.get("lote", "") == lote),
        key=lambda r: str(r.get("material", "")),
    )
    if not group:
        raise HTTPException(status_code=404, detail={"error": "grupo_no_encontrado"})
    return _run_locked(lambda: {"ok": bool(com.load_report_group_in_access(group)), "status": com.get_status()})


@router.post("/reports/bulk/load")
def load_all_report_groups(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    """Botón 'Cargar TODO en Access' -- cargar de un solo click TODOS los grupos (coladas) que la pantalla
    tiene visibles en el árbol, en vez de abrir cada grupo y apretar 'Cargar en Access' uno por uno. El
    frontend manda la lista de grupos tal cual los construye buildGroups() (ya filtrados por
    archivado/búsqueda) -- el backend no vuelve a decidir qué está "pendiente", solo ejecuta sobre la lista
    que la pantalla tiene en pantalla.

    Un solo CoInitialize/lock para TODA la tanda (no uno por grupo, como pasaría si el frontend pegara N
    POST a /reports/group/load): entre grupos no hace falta soltar el lock, y se evita el overhead de
    CoInitialize/CoUninitialize repetido. Si un grupo falla se sigue con el siguiente -- cada grupo vuelve a
    seleccionar su propia colada desde cero (ver load_report_group_in_access), así que no hereda una
    posición de formulario rota del grupo anterior; lo que SÍ se sigue cortando es el loop interno de
    materiales DENTRO de un grupo que falla (mismo comportamiento de siempre para ese caso, sin cambios)."""
    groups_payload = payload.get("groups") or []
    if not groups_payload:
        raise HTTPException(status_code=400, detail={"error": "sin_grupos"})
    reports = datos.load_quality_reports()

    def run():
        results = []
        for g in groups_payload:
            base = str(g.get("base", "") or "").strip()
            lote = str(g.get("lote", "") or "").strip()
            if not base or not lote:
                results.append({"base": base, "lote": lote, "ok": False, "status": "Grupo sin base/lote."})
                continue
            group = sorted(
                (r for r in reports if r.get("base", "") == base and r.get("lote", "") == lote),
                key=lambda r: str(r.get("material", "")),
            )
            if not group:
                results.append({"base": base, "lote": lote, "ok": False, "status": "Grupo no encontrado."})
                continue
            ok = bool(com.load_report_group_in_access(group))
            results.append({"base": base, "lote": lote, "ok": ok, "status": com.get_status()})
        return {"ok": all(r["ok"] for r in results), "results": results, "status": com.get_status()}

    return _run_locked(run)


@router.post("/reports/{report_id}/load")
def load_report(report_id: str, _: dict = Depends(devices.require_editor_device)):
    """Botón real 'Cargar en Access': abre/activa Fundiciones y carga colada + responsable + fecha +
    material completo hasta espesores."""
    report = _find_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail={"error": "informe_no_encontrado"})
    return _run_locked(lambda: {"ok": bool(com.load_report_in_access(report)), "status": com.get_status()})


@router.post("/reports/{report_id}/review")
def review_report(report_id: str, _: dict = Depends(devices.require_editor_device)):
    """Botón real 'Abrir en Access': navega hasta el material ya cargado, sin volver a escribir datos, para
    revisar a ojo en Access."""
    report = _find_report(report_id)
    if report is None:
        raise HTTPException(status_code=404, detail={"error": "informe_no_encontrado"})
    return _run_locked(lambda: {"ok": bool(com.open_report_for_review(report)), "status": com.get_status()})


@router.get("/status")
def get_status(_: dict = Depends(devices.require_approved_device)):
    return {"status": com.get_status(), "busy": _ACCESS_LOCK.locked()}


# ---------- diagnóstico (sin botón en el original -- útil para depurar nombres de controles contra la base
# real, algo que no se puede verificar fuera de la PC del laboratorio) ----------

@router.post("/diagnostico/probar-control")
def probe_control(payload: dict = Body(...), _: dict = Depends(devices.require_editor_device)):
    control_name = str(payload.get("control_name", "") or "").strip()
    if not control_name:
        raise HTTPException(status_code=400, detail={"error": "falta_control_name"})
    return _run_locked(lambda: {"ok": bool(com.goto_control(control_name)), "status": com.get_status()})


@router.get("/diagnostico/control-activo")
def active_control(_: dict = Depends(devices.require_editor_device)):
    def run():
        info = com.detect_active_control()
        return {"ok": info is not None, "info": info, "status": com.get_status()}
    return _run_locked(run)


@router.post("/diagnostico/material/{direction}")
def go_material(direction: str, _: dict = Depends(devices.require_editor_device)):
    if direction not in ("next", "prev"):
        raise HTTPException(status_code=400, detail={"error": "direccion_invalida"})
    return _run_locked(lambda: {"ok": bool(com.go_material_record(direction)), "status": com.get_status()})
