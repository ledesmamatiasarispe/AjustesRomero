# rutas/catalogo.py -- puerto 1:1 de backend/routers/catalogo.py de ajuste_comp_web. CRUD del catálogo de
# materiales: datos.save_alloys() reemplaza la lista COMPLETA cada vez (no hay upsert parcial) -- toda
# operación de escritura lee la lista entera, la modifica en memoria, y la vuelve a guardar entera. El "id" de
# un material para las rutas /{idx} es su posición en la lista (mismo criterio frágil-pero-aceptado que ya usa
# datos.py para sesiones/ajustes de Históricos) — se avisa por WebSocket después de cada cambio.
#
# Un material tiene TRES formas distintas según "tipo":
#   - genérico (Ferroaleación/Metal puro/Aditivo/Aleación propia/etc.): composición + límites (min/max
#     independientes) + especiales (CE). Además, CUALQUIER material genérico puede tener el flag "inoculante"
#     que agrega gramos_cucharin1/unidad_inoculacion/color_inoculacion -- es el mecanismo que usan de verdad
#     los materiales inoculantes existentes hoy en la base, NO el tipo="Inoculante".
#   - tipo == "Inoculante": legacy, no alcanzable creando un material nuevo desde el editor, pero se soporta
#     por si hay datos viejos así: la composición sale de copiar un material "base" + una lista de "medidas".
#   - tipo == "Aleación final": NO es una aleación con composición propia, es una ficha de calidad
#     (tracción/dureza/tamaño de grafito/protocolo de inoculación) asociada a una o más "bases".
import json as _json

from fastapi import APIRouter, Body, Depends, HTTPException

from .. import datos
from .. import dispositivos as devices
from ..calc import effective_add, effective_total_perkg
from ..ce import ce_from_percent
from ..config import ELEMENTS
from ..utils import to_float, to_float_or_none, _norm, simulate_staged
from ..ws import hub

router = APIRouter(prefix="/api/alloys", tags=["catalogo"])


# ---------- Helpers (funciones puras) ----------

def _normalize_limites(lim_dict):
    out = {}
    for e in ELEMENTS:
        src = (lim_dict or {}).get(e, {})
        out[e] = {
            "soft_min": src.get("soft_min", None),
            "soft_max": src.get("soft_max", None),
            "hard_min": None,
            "hard_max": None,
        }
    return out


def _normalize_especiales(esp_dict):
    esp = {
        "CE_formula": "FUNDICION", "CE_min": None, "CE_max": None,
        "CE_custom": {"C": 1.0, "Si": 1 / 3, "P": 1 / 3, "S": 0.0},
    }
    if esp_dict:
        esp["CE_formula"] = _norm(esp_dict.get("CE_formula", "FUNDICION")) or "FUNDICION"
        esp["CE_min"] = esp_dict.get("CE_min", None)
        esp["CE_max"] = esp_dict.get("CE_max", None)
        raw = esp_dict.get("CE_custom", {})
        clean = {}
        if isinstance(raw, dict):
            for k, v in raw.items():
                if k in ELEMENTS:
                    vv = to_float_or_none(v)
                    if vv is not None:
                        clean[k] = vv
        if clean:
            esp["CE_custom"] = clean
    return esp


def _meta_inoculacion_full(meta):
    raw = (meta or {}).get("inoculacion", [])
    if not isinstance(raw, list):
        raw = []
    result = []
    for v in raw:
        if isinstance(v, str) and v.strip():
            result.append({"nombre": v.strip(), "cantidad_dosis": 1, "momento": "horno"})
        elif isinstance(v, dict) and str(v.get("nombre", "")).strip():
            mom = str(v.get("momento", "horno") or "horno") or "horno"
            try:
                dosis = float(v.get("cantidad_dosis", 1) or 1)
            except Exception:
                dosis = 1.0
            result.append({"nombre": str(v["nombre"]).strip(), "cantidad_dosis": dosis, "momento": mom})
    return result


def _gramos_cucharin1(alloys, nombre):
    for a in alloys:
        if str(a.get("nombre", "")).strip() == nombre:
            return a.get("gramos_cucharin1", 0) or 0
    return 0


# ---------- Construcción del dict a guardar, según tipo (dispatcher) ----------

def _build_generic(a, payload):
    a["limites"] = _normalize_limites(payload.get("limites"))
    a["especiales"] = _normalize_especiales(payload.get("especiales"))
    a["composicion"] = {e: to_float((payload.get("composicion") or {}).get(e, 0.0)) for e in ELEMENTS}
    return a


def _build_inoculante(a, payload, alloys):
    inoc_meta = payload.get("inoculante_meta") or {}
    base_name = str(inoc_meta.get("base_material", "") or "").strip()
    if not base_name:
        raise HTTPException(status_code=400, detail={"error": "base_requerida"})
    base_item = next((c for c in alloys if str(c.get("nombre", "")).strip() == base_name), None)
    if not base_item:
        raise HTTPException(status_code=400, detail={"error": "base_no_encontrada"})
    medidas = []
    for med in (inoc_meta.get("medidas") or []):
        grams = to_float(med.get("gramos", 0))
        if grams <= 0:
            continue
        medidas.append({"nombre": str(med.get("nombre") or f"Medida {len(medidas) + 1}").strip(), "gramos": grams})
    if not medidas:
        raise HTTPException(status_code=400, detail={"error": "medidas_requeridas"})
    a.update({
        "composicion": dict(base_item.get("composicion", {}) or {}),
        "limites": _normalize_limites(None),
        "especiales": _normalize_especiales(None),
        "ajuste": False,
        "inoculante": True,
        "subtipo": "Inoculante",
        "inoculante_meta": {"base_material": base_name, "medidas": medidas},
    })
    return a


def _build_final(a, payload, existing):
    src = existing or {}
    bases = [str(b).strip() for b in (payload.get("bases") or []) if str(b).strip()]
    if not bases:
        raise HTTPException(status_code=400, detail={"error": "bases_requeridas"})
    family = str(payload.get("family", "") or "").strip()
    if family not in ("Gris", "Nodular"):
        raise HTTPException(status_code=400, detail={"error": "family_invalida"})
    prev_meta = src.get("calidad_meta", {}) if isinstance(src.get("calidad_meta"), dict) else {}
    d = payload.get("defaults") or {}
    a.update({
        "composicion": src.get("composicion", {}),
        "limites": src.get("limites", {}),
        "especiales": src.get("especiales", {}),
        "calidad_meta": {
            "es_material_final": True,
            "codigo": a["nombre"],
            "base_ref": bases[0],
            "bases": bases,
            "family": family,
            "section_options": prev_meta.get("section_options", []),
            "defaults": {
                "traccion": str(d.get("traccion", "") or "").strip(),
                "seccion": str(d.get("seccion", "") or "").strip(),
                "dureza": str(d.get("dureza", "") or "").strip(),
                "tam_grafito": str(d.get("tam_grafito", "") or "").strip(),
                "morfologia": "" if family == "Nodular" else str(d.get("morfologia", "") or "").strip(),
                "tipo_grafito": str(d.get("tipo_grafito", "") or "").strip(),
                "conteo_nodulos": str(d.get("conteo_nodulos", "") or "").strip(),
                "pct_nodularizacion": str(d.get("pct_nodularizacion", "") or "").strip(),
                "alargamiento": str(d.get("alargamiento", "") or "").strip(),
                "perlita": str(d.get("perlita", "") or "").strip(),
                "ferrita": str(d.get("ferrita", "") or "").strip(),
            },
        },
    })
    # El payload de la grilla siempre manda inoc_default/inoc_por_base completos (aunque queden vacíos porque
    # el usuario puso todo en 0), así que es autoritativo: no hay que "preservar" el inoculacion_meta previo
    # cuando el resultado da vacío, o nunca se podría borrar un protocolo.
    a["inoculacion_meta"] = {
        "inoculacion": payload.get("inoc_default") or [],
        "por_base": payload.get("inoc_por_base") or {},
    }
    return a


def _build_alloy_dict(payload: dict, existing: dict | None, alloys: list) -> dict:
    nombre = str(payload.get("nombre", "")).strip()
    if not nombre:
        raise HTTPException(status_code=400, detail={"error": "nombre_requerido"})

    is_inoc_flag = bool(payload.get("inoculante"))
    raw_tipo = str(payload.get("tipo", "") or "").strip()
    # El checkbox "Es inoculante" fuerza el tipo a Ferroaleación -- es el mecanismo real que usan los
    # inoculantes existentes en la base.
    tipo = "Ferroaleación" if is_inoc_flag else (raw_tipo or "Ferroaleación")

    rendimiento = to_float(payload.get("rendimiento", 90))
    if not (0 < rendimiento <= 100):
        raise HTTPException(status_code=400, detail={"error": "rendimiento_invalido"})

    a = {}
    if existing:
        a.update(existing)  # preserva cualquier campo "extra" no tocado por esta función
    a.update({
        "nombre": nombre,
        "tipo": tipo,
        "rendimiento": rendimiento,
        "costo": to_float(payload.get("costo", 0)),
        "ajuste": bool(payload.get("ajuste", False)),
        "gramos_cucharin1": to_float(payload.get("gramos_cucharin1", 0)),
        "unidad_inoculacion": str(payload.get("unidad_inoculacion", "") or "").strip() or "cucharín",
        "color_inoculacion": str(payload.get("color_inoculacion", "") or "").strip() or None,
    })
    if is_inoc_flag:
        a["subtipo"] = "Inoculante"
        a["inoculante"] = True
    else:
        a.pop("subtipo", None)
        a.pop("inoculante", None)

    if tipo == "Inoculante":
        return _build_inoculante(a, payload, alloys)
    if tipo == "Aleación final":
        return _build_final(a, payload, existing)
    return _build_generic(a, payload)


@router.get("")
def list_alloys(_: dict = Depends(devices.require_acceso)):
    alloys = datos.load_alloys()
    return [{"idx": i, **a} for i, a in enumerate(alloys)]


@router.get("/{idx}")
def get_alloy(idx: int, _: dict = Depends(devices.require_acceso)):
    alloys = datos.load_alloys()
    if idx < 0 or idx >= len(alloys):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    return {"idx": idx, **alloys[idx]}


@router.post("")
async def create_alloy(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    alloys = datos.load_alloys()
    new_item = _build_alloy_dict(payload, None, alloys)
    alloys.append(new_item)
    datos.save_alloys(alloys)
    await hub.broadcast("catalogo", {"type": "catalog_changed"})
    return {"idx": len(alloys) - 1, **new_item}


@router.put("/{idx}")
async def update_alloy(idx: int, payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    alloys = datos.load_alloys()
    if idx < 0 or idx >= len(alloys):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    alloys[idx] = _build_alloy_dict(payload, alloys[idx], alloys)
    datos.save_alloys(alloys)
    await hub.broadcast("catalogo", {"type": "catalog_changed"})
    return {"idx": idx, **alloys[idx]}


@router.delete("/{idx}")
async def delete_alloy(idx: int, _: dict = Depends(devices.require_acceso_editor)):
    alloys = datos.load_alloys()
    if idx < 0 or idx >= len(alloys):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    alloys.pop(idx)
    datos.save_alloys(alloys)
    await hub.broadcast("catalogo", {"type": "catalog_changed"})
    return {"ok": True}


@router.post("/{idx}/duplicate")
async def duplicate_alloy(idx: int, _: dict = Depends(devices.require_acceso_editor)):
    alloys = datos.load_alloys()
    if idx < 0 or idx >= len(alloys):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    new_item = _json.loads(_json.dumps(alloys[idx]))
    new_item["nombre"] = (new_item.get("nombre", "") + " (copia)").strip()
    alloys.append(new_item)
    datos.save_alloys(alloys)
    await hub.broadcast("catalogo", {"type": "catalog_changed"})
    return {"idx": len(alloys) - 1, **new_item}


# ---------- Inoculación: unidades y etapas (usadas por el editor) ----------

@router.get("/inoc/units")
def get_inoc_units(_: dict = Depends(devices.require_acceso)):
    return {"units": datos.load_inoc_units()}


@router.put("/inoc/units")
def set_inoc_units(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    units = payload.get("units") or []
    if not units:
        raise HTTPException(status_code=400, detail={"error": "lista_vacia"})
    datos.save_inoc_units(units)
    return {"ok": True}


@router.get("/inoc/momentos")
def get_inoc_momentos(_: dict = Depends(devices.require_acceso)):
    return {"momentos": datos.load_inoc_momentos()}


@router.put("/inoc/momentos")
def set_inoc_momentos(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    momentos = payload.get("momentos") or []
    if not momentos:
        raise HTTPException(status_code=400, detail={"error": "lista_vacia"})
    datos.save_inoc_momentos(momentos)
    return {"ok": True}


# ---------- "Ver inoculación" / "Ver composición estimada" (solo Aleación final) ----------

@router.get("/{idx}/inoculacion")
def get_inoculacion(idx: int, base: str | None = None, _: dict = Depends(devices.require_acceso)):
    """Protocolo de inoculación resuelto para esta Aleación final (el de la base pedida si existe uno
    específico, si no el por defecto), con gramos/dosis calculados."""
    alloys = datos.load_alloys()
    if idx < 0 or idx >= len(alloys):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    alloy = alloys[idx]
    meta = alloy.get("inoculacion_meta", {}) if isinstance(alloy.get("inoculacion_meta"), dict) else {}
    calidad_meta = alloy.get("calidad_meta", {}) if isinstance(alloy.get("calidad_meta"), dict) else {}
    bases = calidad_meta.get("bases", [])
    entries = datos.resolve_inoc_protocol(meta, base=base) if base else meta.get("inoculacion", [])
    inoculacion = _meta_inoculacion_full({"inoculacion": entries})
    rows = []
    for e in inoculacion:
        g = _gramos_cucharin1(alloys, e["nombre"])
        cant = e["cantidad_dosis"]
        rows.append({
            "nombre": e["nombre"], "cantidad_dosis": cant, "momento": e.get("momento", "horno"),
            "gramos_cucharin1": g, "total_g": round(g * cant, 2) if g and cant else None,
        })
    return {"nombre": alloy.get("nombre", ""), "bases": bases, "rows": rows}


@router.post("/{idx}/simulate-inoc")
def simulate_inoc(idx: int, payload: dict = Body(...), _: dict = Depends(devices.require_acceso)):
    """Composición resultante de aplicar el protocolo de inoculación de esta Aleación final sobre una base,
    etapa por etapa. payload: {"base": str, "stage_masses": {momento_key: kg}}."""
    alloys = datos.load_alloys()
    if idx < 0 or idx >= len(alloys):
        raise HTTPException(status_code=404, detail={"error": "not_found"})
    alloy = alloys[idx]
    meta = alloy.get("inoculacion_meta", {}) if isinstance(alloy.get("inoculacion_meta"), dict) else {}
    base_name = str(payload.get("base", "") or "").strip()
    base_alloy = next((a for a in alloys if str(a.get("nombre", "")).strip() == base_name), None)
    if not base_alloy:
        raise HTTPException(status_code=400, detail={"error": "base_no_encontrada"})

    inoculacion = _meta_inoculacion_full(
        {"inoculacion": datos.resolve_inoc_protocol(meta, base=base_name)}
    )
    stage_items = {}
    for e in inoculacion:
        mom = e.get("momento", "horno") or "horno"
        g = _gramos_cucharin1(alloys, e["nombre"])
        if e["cantidad_dosis"] > 0 and g:
            stage_items.setdefault(mom, []).append((e["nombre"], e["cantidad_dosis"], g))

    stage_masses = payload.get("stage_masses") or {}
    stage_specs = []
    for mom, items in stage_items.items():
        mass = to_float(stage_masses.get(mom, 0))
        if mass <= 0:
            raise HTTPException(status_code=400, detail={"error": f"masa_invalida_{mom}"})
        specs = [(nombre, (g * cant) / 1000) for nombre, cant, g in items]
        stage_specs.append((mass, specs))

    def get_alloy(name):
        return next((a for a in alloys if str(a.get("nombre", "")).strip() == name), None)

    if not stage_specs:
        comp = base_alloy.get("composicion", {})
    else:
        comp = simulate_staged(base_alloy.get("composicion", {}), stage_specs, ELEMENTS,
                                get_alloy, effective_add, effective_total_perkg)

    # Gramos de cada elemento aportados FÍSICAMENTE por los inoculantes (independiente de la dilución): suma,
    # sobre todas las etapas, de gramos_de_ese_material * su_propia_composicion%/100 — a diferencia de
    # "inoculantes_delta" (que es neto y puede ir negativo por dilución de la base, ej. el %Fe baja aunque
    # nadie agregó un inoculante sin Fe), esto es la cantidad real en gramos que aporta la inoculación.
    inoc_gramos_el = {e: 0.0 for e in ELEMENTS}
    for items in stage_items.values():
        for nombre, cant, g in items:
            a = get_alloy(nombre)
            if not a:
                continue
            total_g = g * cant
            comp_mat = a.get("composicion", {}) or {}
            for e in ELEMENTS:
                inoc_gramos_el[e] += total_g * to_float(comp_mat.get(e, 0.0)) / 100.0

    base_comp = base_alloy.get("composicion", {}) or {}
    # Desglose base/inoculantes/total: "base" es la composición propia del material base elegido (sin inocular
    # todavía), "inoculantes" es el delta neto que deja el protocolo de inoculación aplicado (total - base) —
    # se suma exacto: base + inoculantes = total, para que se entienda de un vistazo cuánto mueve la aguja la
    # inoculación.
    elements_shown = [e for e in ELEMENTS if to_float(comp.get(e, 0)) > 0.001 or to_float(base_comp.get(e, 0)) > 0.001]
    return {
        "composicion": {e: round(to_float(comp.get(e, 0)), 4) for e in elements_shown},
        "base_composicion": {e: round(to_float(base_comp.get(e, 0)), 4) for e in elements_shown},
        "inoculantes_delta": {e: round(to_float(comp.get(e, 0)) - to_float(base_comp.get(e, 0)), 4) for e in elements_shown},
        "inoculantes_gramos": {e: round(inoc_gramos_el.get(e, 0.0), 2) for e in elements_shown},
        "ce_fundicion": round(ce_from_percent(comp), 4),
    }
