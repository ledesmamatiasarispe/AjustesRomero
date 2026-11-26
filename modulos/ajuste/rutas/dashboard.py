# rutas/dashboard.py -- puerto 1:1 de backend/routers/dashboard.py de ajuste_comp_web. Pestaña "Dashboard": panel
# de indicadores agregados sobre datos que YA están guardados en otros dominios (Históricos) -- esta pantalla no
# escribe nada propio, solo lee y resume. Bases de catálogo: "8"/"10" son Nodular, "2"/"5" son Gris.
import re
import time
from datetime import datetime, timezone

import requests
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response

from .. import datos
from .. import dispositivos as devices

router = APIRouter(prefix="/api/dashboard", tags=["dashboard"])

NODULAR_BASES = ("8", "10")
GRIS_BASES = ("2", "5")
ALL_BASES = NODULAR_BASES + GRIS_BASES


def _azufre_por_colada(bases):
    """Un punto por colada cuyo objetivo está en `bases`, con al menos una lectura de espectro que trajo S.
    Cada colada aporta UN solo punto: la lectura más nueva de esa sesión, no el promedio ni todas sueltas (una
    colada puede quedar con varias lecturas seguidas -- medición, corrección de tratamiento, nueva medición -- y
    la primera no es "la" composición final)."""
    hist = datos.load_history()
    puntos = []
    for s in hist:
        objetivo = str(s.get("objetivo", "") or "").strip()
        if objetivo not in bases:
            continue
        lecturas = [
            (str(sr.get("ts", "") or ""), sr["elements"]["S"])
            for sr in (s.get("spectro_resultados") or [])
            if isinstance(sr, dict) and isinstance(sr.get("elements"), dict)
            and sr["elements"].get("S") is not None
        ]
        if not lecturas:
            continue
        lecturas.sort(key=lambda par: par[0])
        ts_final, s_final = lecturas[-1]
        puntos.append({
            "colada": s.get("colada", ""), "objetivo": objetivo, "ts": ts_final,
            "s_pct": s_final, "n_lecturas": len(lecturas),
        })
    puntos.sort(key=lambda p: p["ts"])
    return puntos


@router.get("/azufre-nodulares")
def azufre_nodulares(_: dict = Depends(devices.require_approved_device)):
    return {"puntos": _azufre_por_colada(NODULAR_BASES)}


@router.get("/azufre-base/{base}")
def azufre_base(base: str, _: dict = Depends(devices.require_approved_device)):
    base = base.strip()
    if base not in ALL_BASES:
        raise HTTPException(status_code=404, detail={"error": "base_desconocida"})
    return {"puntos": _azufre_por_colada((base,))}


@router.get("/acceso.html")
def descargar_acceso(request: Request, _: dict = Depends(devices.require_approved_device)):
    """Acceso a esta app para el botón "Descargar acceso" del Dashboard. Usa request.base_url en vez de una IP
    fija, porque cada equipo de la planta puede llegar por una interfaz de red distinta. Es un .html con
    redirect, no un .url: Chrome/Edge tratan los .url como "tipo de archivo peligroso" y los renombran a
    .download al bajarlos, sin importar el Content-Type -- .html no está en esa lista."""
    base = str(request.base_url).rstrip("/") + "/"
    contenido = (
        "<!doctype html><html lang=\"es\"><head><meta charset=\"UTF-8\">"
        f"<meta http-equiv=\"refresh\" content=\"0; url={base}\">"
        "<title>Ajuste de Composición</title></head><body>"
        f"<p>Abriendo Ajuste de Composición… si no pasa nada, <a href=\"{base}\">tocá aquí</a>.</p>"
        f"<script>location.href={base!r};</script>"
        "</body></html>"
    )
    return Response(
        content=contenido, media_type="text/html",
        headers={"Content-Disposition": 'attachment; filename="Ajuste de Composicion.html"'},
    )


# ---------- Clima espacial ----------
# Tormentas geomagnéticas (G), de radiación solar (S) y apagones de radio (R) -- Space Weather Prediction Center
# de NOAA, sin API key. Proxy a un servicio externo: se cachea en memoria del proceso (300s) y si NOAA no
# responde se sirve el último dato bueno en cache en vez de romper la pantalla.
_NOAA_SCALES_URL = "https://services.swpc.noaa.gov/products/noaa-scales.json"
_NOAA_ALERTS_URL = "https://services.swpc.noaa.gov/products/alerts.json"
_NOAA_TIMEOUT = 6
_NOAA_CACHE_TTL = 300

_noaa_cache = {"ts": 0.0, "data": None}

_ESCALA_LABELS = {
    "G": "Tormenta geomagnética",
    "S": "Tormenta de radiación solar",
    "R": "Apagón de radio (llamarada solar)",
}
_HEADLINE_RE = re.compile(r"\r?\n\r?\n([^\r\n]+)")
_SCALE_RE = re.compile(r"(?:NOAA|Noaa) Scale:\s*([A-Z]\d[^\r\n]*)")


def _parse_alerta_noaa(item):
    msg = item.get("message") or ""
    m = _HEADLINE_RE.search(msg)
    if m:
        titulo = m.group(1).strip()
    else:
        lineas = msg.strip().splitlines()
        titulo = lineas[0].strip() if lineas else ""
    m2 = _SCALE_RE.search(msg)
    return {"ts": item.get("issue_datetime", ""), "titulo": titulo, "escala": m2.group(1).strip() if m2 else ""}


def _clima_espacial_fresco():
    escalas = None
    try:
        resp = requests.get(_NOAA_SCALES_URL, timeout=_NOAA_TIMEOUT)
        resp.raise_for_status()
        hoy = resp.json().get("0", {})
        escalas = {}
        for letra in ("G", "S", "R"):
            bloque = hoy.get(letra) or {}
            valor = bloque.get("Scale")
            escalas[letra] = {
                "label": _ESCALA_LABELS[letra],
                "scale": int(valor) if valor not in (None, "") else 0,
                "text": bloque.get("Text") or "none",
            }
    except Exception:
        escalas = None

    alertas = None
    try:
        resp = requests.get(_NOAA_ALERTS_URL, timeout=_NOAA_TIMEOUT)
        resp.raise_for_status()
        alertas = [_parse_alerta_noaa(item) for item in resp.json()[:8]]
    except Exception:
        alertas = None

    if escalas is None and alertas is None:
        return None
    return {
        "obtenido_en": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "escalas": escalas or {}, "alertas": alertas or [],
    }


@router.get("/clima-espacial")
def clima_espacial(_: dict = Depends(devices.require_approved_device)):
    ahora = time.time()
    if ahora - _noaa_cache["ts"] > _NOAA_CACHE_TTL:
        fresco = _clima_espacial_fresco()
        if fresco is not None:
            _noaa_cache["ts"] = ahora
            _noaa_cache["data"] = fresco
    if _noaa_cache["data"] is None:
        raise HTTPException(status_code=503, detail={"error": "noaa_no_disponible"})
    return _noaa_cache["data"]
