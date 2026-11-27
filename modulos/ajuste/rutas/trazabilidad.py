# rutas/trazabilidad.py -- consulta de la bitácora (ISO 9001, 7.5.3 / 8.5.2). Solo lectura: la bitácora la escribe
# datos.py dentro de la misma transacción de cada cambio (ver trazabilidad.py), nunca una ruta.
import csv
import io
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse

from .. import datos
from .. import dispositivos as devices
from .. import trazabilidad

router = APIRouter(prefix="/api/trazabilidad", tags=["trazabilidad"])


def _filtros(colada, entidad, actor, accion, desde, hasta, texto):
    return {
        "colada": (datos.normalize_colada_key(colada) or colada.strip()) if colada else "",
        "entidad": entidad.strip(), "actor": actor.strip(), "accion": accion.strip(),
        # "hasta" es inclusivo para el usuario (elige el día): se compara contra el día siguiente.
        "desde": desde.strip(), "hasta": (hasta.strip() + "T99") if hasta.strip() else "",
        "texto": texto.strip(),
    }


@router.get("/catalogo")
def catalogo(_: dict = Depends(devices.require_acceso)):
    return {"entidades": trazabilidad.ENTIDADES,
            "acciones": {"alta": "Alta", "modificacion": "Modificación", "baja": "Baja", "inicio": "Inicio"}}


@router.get("/registros")
def registros(colada: str = "", entidad: str = "", actor: str = "", accion: str = "", desde: str = "",
              hasta: str = "", texto: str = "", limite: int = Query(500, ge=1, le=5000),
              _: dict = Depends(devices.require_acceso)):
    return {"registros": trazabilidad.consultar(
        **_filtros(colada, entidad, actor, accion, desde, hasta, texto), limite=limite)}


@router.get("/registros/{registro_id}")
def registro(registro_id: int, _: dict = Depends(devices.require_acceso)):
    r = trazabilidad.detalle(registro_id)
    if r is None:
        raise HTTPException(404, "No existe ese registro de la bitácora.")
    return r


@router.get("/verificar")
def verificar(_: dict = Depends(devices.require_acceso)):
    return trazabilidad.verificar_cadena()


def _valor_csv(v):
    if v is None:
        return ""
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return str(v)


@router.get("/export.csv")
def exportar(colada: str = "", entidad: str = "", actor: str = "", accion: str = "", desde: str = "",
             hasta: str = "", texto: str = "", _: dict = Depends(devices.require_acceso)):
    """Una fila por campo cambiado (en altas/bajas, una fila con el registro completo): lo que pide un auditor para
    revisar un período o una colada sin entrar a la app. Separador ";" y BOM para que Excel en castellano lo abra
    bien de un doble clic."""
    filas = trazabilidad.consultar(**_filtros(colada, entidad, actor, accion, desde, hasta, texto), limite=5000)
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";")
    w.writerow(["N°", "Fecha", "Quién", "Tipo", "Dispositivo", "IP", "Acción", "Qué", "Clave", "Colada",
                "Campo", "Antes", "Después", "Motivo", "Hash"])
    for f in reversed(filas):
        d = trazabilidad.detalle(f["id"])
        base = [d["id"], d["fecha"], d["actor"], d["actor_tipo"], d["dispositivo"], d["ip"], d["accion"],
                d["entidad_nombre"], d["clave"], d["colada"]]
        fin = [d["motivo"], d["hash"]]
        if d.get("cambios"):
            for ch in d["cambios"]:
                w.writerow(base + [ch["campo"], _valor_csv(ch["antes"]), _valor_csv(ch["despues"])] + fin)
        else:
            w.writerow(base + ["(registro completo)", _valor_csv(d.get("antes")), _valor_csv(d.get("despues"))] + fin)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue()]), media_type="text/csv; charset=utf-8",
                             headers={"Content-Disposition": 'attachment; filename="trazabilidad.csv"'})
