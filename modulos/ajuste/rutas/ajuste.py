# rutas/ajuste.py -- puerto del NÚCLEO de backend/routers/ajuste.py de ajuste_comp_web (pestaña central: motor
# de cálculo Greedy/Lineal + la "sesión de trabajo" compartida colada/objetivo/composición actual/plan de
# materiales, un solo "workspace" para todos los dispositivos conectados).
#
# ALCANCE DE ESTE CORTE -- a propósito, para no bloquear lo central en una sola pasada gigante:
#   - Carbomax automático (toggle/config/check-now/registros recientes) y Espectrómetro LMX06 (conexión,
#     medir, alertas, teclado remoto) NO están portados todavía -- dependen de hilos de fondo con protocolos
#     de hardware (RS485/Modbus, socket TCP) que se portan aparte, con más atención dedicada a esa fidelidad
#     de protocolo. Los puntos de extensión quedan marcados explícitamente abajo (_load_and_clean,
#     save_session) y en el router: cuando se porten, agregan sus propios endpoints a este mismo router.
#   - "Cambio de base" (POST /cambio-base) SÍ está, completo: es una función agregada en esta misma migración
#     (no viene de la app de escritorio), simulación aparte que no toca la sesión real.
#   - Carbomax automático de red/legacy (_ensure_adjusters_in_catalog, defaults hardcodeados de adjust_list)
#     tampoco se porta -- mismo criterio ya aplicado en Catálogo: la lista de materiales de ajuste arranca
#     vacía, el usuario elige de lo que ya existe en su catálogo real.
from datetime import datetime
import re
import uuid

from fastapi import APIRouter, Body, Depends, HTTPException, Request

from .. import datos
from .. import dispositivos as devices
from .. import calc
from .. import graph
from ..config import ELEMENTS
from ..utils import to_float, _norm
from ..ce import ce_from_percent
from ..ws import hub

router = APIRouter(prefix="/api/ajuste", tags=["ajuste"])


# ---------- Helpers de catálogo ----------

def _own_alloy_names(alloys):
    """Nombres candidatos a objetivo: solo tipo=='Aleación propia'."""
    return sorted({a.get("nombre", "") for a in alloys if a.get("tipo", "") == "Aleación propia"},
                  key=lambda v: (0, int(v)) if str(v).isdigit() else (1, str(v).lower()))


def _adjuster_candidate_names(alloys):
    """Todo material con tipo != 'Aleación final' es un candidato válido de ajuste (no se incluyen acá los
    combos sintéticos "Final / Base", esos son una fase posterior)."""
    return sorted({a.get("nombre", "") for a in alloys if a.get("nombre", "") and a.get("tipo", "") != "Aleación final"},
                  key=lambda v: (0, int(v)) if str(v).isdigit() else (1, str(v).lower()))


def _alloy_by_name(alloys, name, prefer_ajuste=True):
    """Entre las entradas con ese nombre, preferir la que tenga el flag 'ajuste' si hay más de una, evitando
    'Aleación final' (esas no tienen composición propia)."""
    items = [a for a in alloys if str(a.get("nombre", "")).strip() == str(name).strip()
             and a.get("tipo", "") != "Aleación final"]
    if not items:
        return None
    if prefer_ajuste:
        for a in items:
            if bool(a.get("ajuste", False)):
                return a
    return items[0]


def _objective_alloy(alloys, name):
    if not name:
        return None
    return next((a for a in alloys if str(a.get("nombre", "")).strip() == str(name).strip()
                 and a.get("tipo", "") == "Aleación propia"), None)


def _objective_ce_data(obj_alloy):
    esp = (obj_alloy or {}).get("especiales", {}) or {}
    frm = esp.get("CE_formula", "FUNDICION") or "FUNDICION"
    return (esp.get("CE_min"), esp.get("CE_max"), _norm(frm), esp.get("CE_custom", {}) or {})


# ---------- Colada "NNNN /YY" ----------

_COLADA_IDYY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})\s*$")
_COLADA_IDYY_PREFIX_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})")


def _parse_colada_idyy(s):
    m = _COLADA_IDYY_RE.match(s or "")
    if not m:
        return (None, None)
    return (int(m.group(1)), m.group(2))


def _next_colada_idyy(colada):
    # Usa PREFIX regex para soportar "NNNN /YY - sufijo" (formato del sistema viejo)
    m = _COLADA_IDYY_PREFIX_RE.match(colada or "")
    cur_id = int(m.group(1)) if m else None
    next_id = (cur_id + 1) if cur_id is not None else 1
    next_yy = datetime.now().strftime("%y")
    return f"{next_id:04d} /{next_yy}"


def _last_colada_id_from_history():
    """Busca el ID numérico más alto entre las coladas ya guardadas en Históricos. A diferencia de
    _parse_colada_idyy (que exige que el string completo sea "NNNN /YY"), el campo "colada" de una sesión ya
    guardada tiene el sufijo "- material", así que acá se toma el PREFIJO "NNNN /YY" nada más."""
    best_id = None
    for session in datos.load_history():
        if not isinstance(session, dict):
            continue
        m = _COLADA_IDYY_PREFIX_RE.match(str(session.get("colada", "") or ""))
        if not m:
            continue
        try:
            cid = int(m.group(1))
        except ValueError:
            continue
        if best_id is None or cid > best_id:
            best_id = cid
    return best_id


def _ensure_colada_idyy(colada):
    """Si todavía no hay número de colada cargado, sugiere el siguiente automáticamente -- mirando también el
    último número real en Históricos (si el "workspace" en curso está vacío, tipicamente la primera vez que se
    usa, la sugerencia no debe arrancar siempre en "0001" aunque ya haya cientos de coladas reales)."""
    if _parse_colada_idyy(colada) != (None, None):
        return colada
    last_id = _last_colada_id_from_history()
    next_id = (last_id + 1) if last_id is not None else 1
    return f"{next_id:04d} /{datetime.now().strftime('%y')}"


# ---------- Resumen de cambios ----------

def _summarize_changes(comp0, comp1):
    out = []
    for e in ELEMENTS:
        v0 = to_float(comp0.get(e, 0.0))
        v1 = to_float(comp1.get(e, 0.0))
        d = v1 - v0
        if abs(d) > 1e-12:
            out.append({"elemento": e, "de": v0, "a": v1, "delta": d})
    return out


# ---------- Snapshot "pie de horno" ----------

def _furnace_material_rows(plan, adjust_list):
    items = {str(name): round(to_float(kg), 3) for name, kg in (plan or {}).items() if to_float(kg) > 0}
    rows = []
    seen = set()
    for name in adjust_list or []:
        if name in items:
            rows.append({"nombre": name, "kg": items[name], "porcentaje_horno": 100, "kg_horno": items[name]})
            seen.add(name)
    for name in sorted(items):
        if name not in seen:
            rows.append({"nombre": name, "kg": items[name], "porcentaje_horno": 100, "kg_horno": items[name]})
    return rows


def _furnace_comp_rows(comp):
    rows = []
    for el in ELEMENTS:
        value = round(to_float((comp or {}).get(el, 0.0)), 6)
        if abs(value) > 1e-12:
            rows.append({"elemento": el, "valor": value})
    return rows


async def _publish_furnace_snapshot(st, plan, comp0, pred_pct, objetivo_name, ce_formula, ce_now, ce_pred):
    ts = datetime.now()
    datos.save_furnace_state({
        "updated_at": ts.isoformat(timespec="seconds"),
        "ajuste": {
            "colada": st.get("colada", "").strip(),
            "material_objetivo": str(objetivo_name or "").strip(),
            "hora_actual": ts.strftime("%H:%M"),
            "ce_formula": str(ce_formula or "").strip(),
            "ce_actual": round(to_float(ce_now), 6),
            "ce_estimado": round(to_float(ce_pred), 6),
            "porcentaje_general_horno": 100,
            "materiales_confirmados": False,
            "confirmado_at": None,
            "materiales": _furnace_material_rows(plan, st.get("adjust_list", [])),
            "composicion_actual": _furnace_comp_rows(comp0),
            "composicion_estimada": _furnace_comp_rows(pred_pct),
        },
    })
    await hub.broadcast("furnace", {"type": "furnace_changed"})


async def _publish_furnace_context(st):
    colada = st.get("colada", "").strip()
    objetivo_name = st.get("objective", "").strip()
    if not colada or not objetivo_name:
        return
    ts = datetime.now()
    alloys = datos.load_alloys()
    obj = _objective_alloy(alloys, objetivo_name)
    _, _, ce_formula, ce_custom = _objective_ce_data(obj)
    ce_now = ce_from_percent(st.get("actual", {}), ce_formula, ce_custom) if obj else None
    datos.save_furnace_state({
        "updated_at": ts.isoformat(timespec="seconds"),
        "ajuste": {
            "colada": colada,
            "material_objetivo": objetivo_name,
            "hora_actual": ts.strftime("%H:%M"),
            "ce_formula": str(ce_formula or "").strip() if obj else "",
            "ce_actual": round(to_float(ce_now), 6) if ce_now is not None else None,
            "ce_estimado": None,
            "materiales": [],
            "composicion_actual": _furnace_comp_rows(st.get("actual", {})),
            "composicion_estimada": [],
        },
    })
    await hub.broadcast("furnace", {"type": "furnace_changed"})



# ---------- Vista compuesta que devuelven GET y las acciones (estado + info derivada) ----------

def _predicted_from_kg(st, alloys):
    """Recalcula (masa, composición, ce_actual, ce_estimado) a partir del kg actualmente cargado en la sesión
    -- función pura de lectura, se llama tanto desde GET como después de cada acción."""
    mass = to_float(st.get("mass", 0))
    comp0 = st.get("actual", {})
    plan_items = []
    for name, kg in (st.get("kg") or {}).items():
        kg = to_float(kg)
        if kg <= 0:
            continue
        a = _alloy_by_name(alloys, name)
        if not a:
            continue
        plan_items.append({"alloy": a, "kg": kg})
    result = calc.estimate_composition(comp0, mass, plan_items)

    obj = _objective_alloy(alloys, st.get("objective", ""))
    ce_min, ce_max, ce_formula, ce_custom = _objective_ce_data(obj)
    ce_now = ce_from_percent(comp0, ce_formula, ce_custom) if obj else None
    ce_pred = ce_from_percent(result["composicion"], ce_formula, ce_custom) if obj else None
    ce_tgt = ce_from_percent(obj["composicion"], ce_formula, ce_custom) if obj else None

    return {
        "mass": result["mass"],
        "composicion": result["composicion"],
        "ce_formula": ce_formula if obj else None,
        "ce_min": ce_min, "ce_max": ce_max,
        "ce_actual": ce_now, "ce_estimado": ce_pred, "ce_objetivo": ce_tgt,
    }


def _session_view(st, alloys):
    obj = _objective_alloy(alloys, st.get("objective", ""))
    out = dict(st)
    out["objective_names"] = _own_alloy_names(alloys)
    out["adjuster_candidates"] = _adjuster_candidate_names(alloys)
    out["objective_composicion"] = obj.get("composicion") if obj else None
    out["objective_limites"] = obj.get("limites") if obj else None
    out["predicted"] = _predicted_from_kg(st, alloys)
    return out


def _load_and_clean(alloys):
    """Carga la sesión y descarta de adjust_list/objective cualquier nombre que ya no exista/valga en el
    catálogo actual. También asegura el número de colada si todavía está vacío, y poda spectro_alerts
    vencidas (spectro_auto._prune_expired_alerts) para que una carga de página fresca ya vea el log limpio
    sin esperar al próximo tick de spectro_auto_loop."""
    from .. import spectro_auto as _spectro_auto_mod  # import local -- evita el ciclo rutas.ajuste <-> spectro_auto

    st = datos.load_ajuste_session()
    dirty = False
    clean_adjust = [n for n in st.get("adjust_list", []) if _alloy_by_name(alloys, n)]
    if clean_adjust != st.get("adjust_list", []):
        st["adjust_list"] = clean_adjust
        st["kg"] = {k: v for k, v in (st.get("kg") or {}).items() if k in clean_adjust}
        dirty = True
    if not str(st.get("colada", "") or "").strip():
        st["colada"] = _ensure_colada_idyy(st.get("colada", ""))
        dirty = True
    if _spectro_auto_mod._prune_expired_alerts(st):
        dirty = True
    if dirty:
        datos.save_ajuste_session(st)
    return st


# ---------- Endpoints ----------

@router.get("/session")
def get_session(_: dict = Depends(devices.require_acceso)):
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    return _session_view(st, alloys)


@router.get("/graph")
def get_graph(_: dict = Depends(devices.require_acceso)):
    """Datos del gráfico de dispersión C/Si. El frontend (graph.js) hace el dibujo en canvas; acá solo se
    arma el JSON (transiciones de la sesión en curso, punto actual/estimado, polígono de límites+CE, y las
    estadísticas históricas por objetivo: casco convexo de arranques y elipse de deriva entre ajustes
    consecutivos)."""
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    obj = _objective_alloy(alloys, st.get("objective", ""))
    if not obj:
        return {"has_objective": False}

    adjustments = []
    for it in sorted(st.get("ajustes_log", []), key=lambda x: x.get("fecha", "")):
        initial = ((it.get("inicial") or {}).get("comp") or {})
        final = ((it.get("estimado") or {}).get("comp") or {})
        if initial and final:
            adjustments.append({"initial": dict(initial), "final": dict(final)})

    predicted = _predicted_from_kg(st, alloys)
    has_live_prediction = any(to_float(v) > 0 for v in (st.get("kg") or {}).values())
    _, _, ce_formula, ce_custom = _objective_ce_data(obj)
    esp = obj.get("especiales", {}) or {}

    return graph.build_graph_payload(
        objective_name=st.get("objective", ""),
        target=obj.get("composicion", {}),
        current=st.get("actual", {}),
        predicted=predicted["composicion"],
        has_live_prediction=has_live_prediction,
        adjustments=adjustments,
        objective_limits=obj.get("limites", {}),
        ce_min=esp.get("CE_min"), ce_max=esp.get("CE_max"),
        ce_formula=ce_formula, ce_custom=ce_custom,
        sessions=datos.load_history(),
    )


@router.patch("/session")
async def patch_session(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Actualiza cualquier subconjunto de {mass, actual, objective, adjust_list, kg, method, colada,
    partial_pct} -- un solo PATCH porque el frontend web no tiene un widget Tk por campo que dispare su propio
    callback."""
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)

    if "mass" in payload:
        st["mass"] = to_float(payload["mass"])
    if "actual" in payload:
        st["actual"] = {e: to_float((payload["actual"] or {}).get(e, 0.0)) for e in ELEMENTS}
    if "method" in payload and payload["method"] in ("Greedy", "Lineal"):
        st["method"] = payload["method"]
    if "partial_pct" in payload:
        st["partial_pct"] = max(1, min(100, int(to_float(payload["partial_pct"]) or 100)))
    if "colada" in payload:
        st["colada"] = str(payload["colada"] or "").strip()
    if "adjust_list" in payload:
        names = [str(n).strip() for n in (payload["adjust_list"] or []) if str(n).strip()]
        valid = [n for n in names if _alloy_by_name(alloys, n)]
        st["adjust_list"] = valid
        old_kg = st.get("kg") or {}
        st["kg"] = {n: to_float(old_kg.get(n, 0.0)) for n in valid}
    if "kg" in payload:
        kg = dict(st.get("kg") or {})
        for name, val in (payload["kg"] or {}).items():
            if name in st.get("adjust_list", []):
                kg[name] = to_float(val)
        st["kg"] = kg
    if "objective" in payload:
        name = str(payload["objective"] or "").strip()
        if name and not _objective_alloy(alloys, name):
            raise HTTPException(status_code=400, detail={"error": "objetivo_invalido"})
        st["objective"] = name
        if name and not st.get("session_started_at"):
            st["session_started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    datos.save_ajuste_session(st)
    if st.get("colada") and st.get("objective"):
        await _publish_furnace_context(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.post("/carbon-silicon")
async def load_carbon_silicon(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Carga C/Si en la composición Actual (Fe por diferencia) y, opcionalmente, elige el objetivo si todavía
    no hay sesión iniciada -- usado por el popup de "Carbono detectado" simple (openCarbonDetectedModal en
    ajuste.js)."""
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)

    objetivo = str(payload.get("objective", "") or "").strip()
    if objetivo:
        if not _objective_alloy(alloys, objetivo):
            raise HTTPException(status_code=400, detail={"error": "objetivo_invalido"})
        if st.get("session_started_at"):
            raise HTTPException(status_code=409, detail={"error": "sesion_ya_iniciada"})
        st["objective"] = objetivo
        st["session_started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    from .. import carbomax_auto as carbomax_auto_mod
    st["actual"] = carbomax_auto_mod._apply_carbon_silicon(st, payload.get("carbon", 0), payload.get("silicon", 0))

    datos.save_ajuste_session(st)
    if st.get("colada") and st.get("objective"):
        await _publish_furnace_context(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.post("/estimate")
async def estimate(payload: dict = Body(None), _: dict = Depends(devices.require_acceso_editor)):
    """Botón "Estimar" (o "Calcular %" si se manda pct)."""
    payload = payload or {}
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)

    obj_name = st.get("objective", "").strip()
    if not obj_name:
        raise HTTPException(status_code=400, detail={"error": "objetivo_requerido"})
    obj = _objective_alloy(alloys, obj_name)
    if not obj:
        raise HTTPException(status_code=400, detail={"error": "objetivo_no_encontrado"})
    if not st.get("session_started_at"):
        st["session_started_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    adjust_alloys = {n: _alloy_by_name(alloys, n) for n in st.get("adjust_list", [])}
    adjust_alloys = {n: a for n, a in adjust_alloys.items() if a}

    _, _, ce_formula, ce_custom = _objective_ce_data(obj)
    result = calc.estimate_plan(
        st.get("actual", {}), st.get("mass", 0), obj["composicion"], adjust_alloys,
        method=st.get("method", "Greedy"), ce_formula=ce_formula, ce_custom=ce_custom,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail={"error": result["error"],
                                                       "message": "Faltan materiales base (C/Si/Fe) en la lista de ajuste."})

    plan = result["plan"]
    pct = payload.get("pct")
    if pct is not None:
        p = max(1, min(100, int(to_float(pct) or 100))) / 100.0
        plan = {k: v * p for k, v in plan.items()}

    st["kg"] = {n: 0.0 for n in st.get("adjust_list", [])}
    for name, kg in plan.items():
        st["kg"][name] = round(kg, 3)

    datos.save_ajuste_session(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    view = _session_view(st, alloys)
    view["missing_elements"] = result["missing_elements"]
    view["warning"] = result["warning"]
    return view


@router.post("/calc")
async def calc_prediction(_: dict = Depends(devices.require_acceso_editor)):
    """Botón "Calcular" -- recalcula la predicción a partir del kg cargado a mano en la sesión, sin correr el
    solver."""
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    return _session_view(st, alloys)


@router.post("/cambio-base")
async def cambio_base(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Botón "Cambio de base" del panel Estimado: a partir de una composición YA lograda (la Estimada/final de
    la colada en curso, que quedó targeteada a un material) calcula qué agregar para en cambio llegar a OTRO
    material del catálogo, con una masa elegida a mano.

    Reusa el mismo motor que /estimate (calc.estimate_plan). A diferencia de /estimate, esto NO toca la
    sesión real -- ni el kg/objective/mass de la colada en curso ni el historial: es una simulación aparte,
    se descarta si se cierra el modal. Los materiales candidatos son los mismos ya configurados en "Elegir
    materiales…" (adjust_list)."""
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)

    obj_name = str(payload.get("objective", "") or "").strip()
    obj = _objective_alloy(alloys, obj_name)
    if not obj:
        raise HTTPException(status_code=400, detail={"error": "objetivo_invalido"})

    mass = to_float(payload.get("mass", 0))
    if mass <= 0:
        raise HTTPException(status_code=400, detail={"error": "masa_invalida"})

    comp_actual = {e: to_float((payload.get("actual") or {}).get(e, 0.0)) for e in ELEMENTS}

    adjust_alloys = {n: _alloy_by_name(alloys, n) for n in st.get("adjust_list", [])}
    adjust_alloys = {n: a for n, a in adjust_alloys.items() if a}

    method = payload.get("method") if payload.get("method") in ("Greedy", "Lineal") else st.get("method", "Greedy")
    _, _, ce_formula, ce_custom = _objective_ce_data(obj)
    result = calc.estimate_plan(
        comp_actual, mass, obj["composicion"], adjust_alloys,
        method=method, ce_formula=ce_formula, ce_custom=ce_custom,
    )
    if "error" in result:
        raise HTTPException(status_code=400, detail={"error": result["error"],
                                                       "message": "Faltan materiales base (C/Si/Fe) en la lista de ajuste (\"Elegir materiales…\")."})

    plan = {name: round(kg, 3) for name, kg in result["plan"].items() if kg > 0}
    plan_items = [{"alloy": adjust_alloys[name], "kg": kg} for name, kg in plan.items()]
    predicted = calc.estimate_composition(comp_actual, mass, plan_items)

    ce_min, ce_max, _, _ = _objective_ce_data(obj)
    ce_actual = ce_from_percent(comp_actual, ce_formula, ce_custom)
    ce_estimado = ce_from_percent(predicted["composicion"], ce_formula, ce_custom)
    ce_objetivo = ce_from_percent(obj["composicion"], ce_formula, ce_custom)

    return {
        "objective": obj_name,
        "objective_composicion": obj["composicion"],
        "objective_limites": obj.get("limites"),
        "mass": mass,
        "plan": plan,
        "predicted": predicted,
        "ce_formula": ce_formula, "ce_min": ce_min, "ce_max": ce_max,
        "ce_actual": ce_actual, "ce_estimado": ce_estimado, "ce_objetivo": ce_objetivo,
        "missing_elements": result["missing_elements"],
        "warning": result["warning"],
    }


async def _commit_apply(st, alloys):
    """Lógica compartida de "Aplicar" -- extraída de apply_adjustment para que también la use (en la fase de
    Carbomax automático) el ajuste automático cuando carbomax_auto_apply esté activo. Requiere que
    st["objective"]/st["kg"] ya estén seteados; muta st in-place (registra el ajuste en ajustes_log y
    commitea actual/mass), publica el snapshot de Pie de Horno. NO guarda ni hace broadcast de
    session_changed -- eso queda a cargo del llamador, junto con cualquier otro campo que también haya
    cambiado en la misma escritura."""
    M0 = to_float(st.get("mass", 0))
    comp0 = st.get("actual", {})
    plan = {n: to_float(kg) for n, kg in (st.get("kg") or {}).items() if to_float(kg) > 0}
    predicted = _predicted_from_kg(st, alloys)
    Mnew, pred_pct = predicted["mass"], predicted["composicion"]

    obj = _objective_alloy(alloys, st.get("objective", ""))
    _, _, ce_formula, ce_custom = _objective_ce_data(obj)
    ce_now = predicted["ce_actual"]
    ce_pred = predicted["ce_estimado"]
    ce_obj = predicted["ce_objetivo"]

    entry = {
        "id": uuid.uuid4().hex,
        "fecha": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "colada": st.get("colada", ""),
        "objetivo": st.get("objective", ""),
        "porcentaje": 100.0,
        "inicial": {"masa": M0, "comp": comp0},
        "estimado": {"masa": Mnew, "comp": pred_pct},
        "objetivo_comp": obj.get("composicion") if obj else {},
        "materiales": plan,
        "cambios_list": _summarize_changes(comp0, pred_pct),
        "ce_formula": ce_formula,
        "ce_custom": ce_custom or {},
        "ce_inicial": ce_now,
        "ce_estimado": ce_pred,
        "ce_objetivo": ce_obj,
    }
    st.setdefault("ajustes_log", []).append(entry)
    await _publish_furnace_snapshot(st, plan, comp0, pred_pct, st.get("objective", ""), ce_formula, ce_now, ce_pred)

    st["actual"] = {e: round(to_float(pred_pct.get(e, 0.0)), 6) for e in ELEMENTS}
    st["mass"] = Mnew
    st["kg"] = {n: 0.0 for n in st.get("adjust_list", [])}


@router.post("/apply")
async def apply_adjustment(_: dict = Depends(devices.require_acceso_editor)):
    """Botón "Aplicar" -- registra el ajuste en el historial de la sesión en curso, publica el snapshot de
    Pie de Horno, y "commitea" la composición/masa estimada como la nueva composición/masa actual (deja el kg
    en 0 para el próximo ajuste)."""
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    if not st.get("objective"):
        raise HTTPException(status_code=400, detail={"error": "sesion_no_iniciada"})

    await _commit_apply(st, alloys)

    datos.save_ajuste_session(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.post("/reset")
async def reset_adjustment(_: dict = Depends(devices.require_acceso_editor)):
    """Botón "Reiniciar ajuste" -- vuelve la masa a 1000, el kg a 0 y borra el historial de ajustes/cálculos
    de la sesión en curso (sin tocar objetivo/colada -- para eso está /save-session o /cancel-session)."""
    st = datos.load_ajuste_session()
    st["mass"] = 1000.0
    st["kg"] = {n: 0.0 for n in st.get("adjust_list", [])}
    st["ajustes_log"] = []
    st["calc_log"] = []
    datos.clear_furnace_state()
    await hub.broadcast("furnace", {"type": "furnace_changed"})
    datos.save_ajuste_session(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    alloys = datos.load_alloys()
    return _session_view(st, alloys)


@router.post("/cancel-session")
async def cancel_session(_: dict = Depends(devices.require_acceso_editor)):
    """Cancela el inicio de sesión sin guardar nada en Históricos (objetivo y cronómetro vuelven a cero)."""
    st = datos.load_ajuste_session()
    st["objective"] = ""
    st["session_started_at"] = None
    datos.clear_furnace_state()
    await hub.broadcast("furnace", {"type": "furnace_changed"})
    datos.save_ajuste_session(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    alloys = datos.load_alloys()
    return _session_view(st, alloys)


async def _do_save_session(st, auto=False):
    """Manda el historial de ajustes de la sesión en curso a Históricos, avanza el número de colada, y
    resetea el workspace (objetivo y cronómetro incluidos) para la próxima colada. Extraída de save_session
    para que también la use (en la fase de auto-guardado por sesión larga) un loop de fondo sin duplicar la
    lógica. Lanza HTTPException en los mismos casos que el endpoint (sin ajustes / colada duplicada) -- el
    llamador de fondo los atrapa y sigue en el próximo tick en vez de crashear el loop.

    OJO: arma new_st en memoria y recién escribe una vez, al final -- save_ajuste_session ya arranca de
    _empty_ajuste_session() y superpone lo que se le pase, así que un dict nuevo alcanza."""
    if not st.get("ajustes_log"):
        raise HTTPException(status_code=400, detail={"error": "sin_ajustes"})

    started_at = st.get("session_started_at") or st["ajustes_log"][0].get("fecha")
    session = {
        "colada": st.get("colada", ""),
        "objetivo": st.get("objective", ""),
        "started_at": started_at,
        "ended_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "ajustes": list(st["ajustes_log"]),
        "calculos": list(st.get("calc_log", [])),
        "carbono": [],
        # Curvas térmicas que se vincularon a esta colada mientras todavía estaba en curso -- se trasladan
        # tal cual, no se pierden al guardar.
        "thermal_analysis": list(st.get("thermal_analysis", [])),
        "auto_saved": bool(auto),
        # Resultados del espectrómetro de ESTA colada -- spectro_recent_results sobrevive al cambio de colada
        # (es un log del instrumento), así que hay que filtrar, no copiar la lista entera.
        "spectro_resultados": [
            r for r in (st.get("spectro_recent_results") or [])
            if r.get("colada") == st.get("colada", "")
        ],
    }
    try:
        datos.append_history(session)
    except datos.DuplicateColadaError as ex:
        raise HTTPException(status_code=409, detail={"error": "colada_duplicada", "message": str(ex)}) from ex

    new_st = {}
    new_st["colada"] = _next_colada_idyy(st.get("colada", ""))
    new_st["adjust_list"] = st.get("adjust_list", [])
    # Carbomax automático: el toggle/configuración sobreviven al cambio de colada (igual que en el original),
    # solo se resetea el tracking de registros consumidos/pendientes de la colada que se acaba de cerrar.
    new_st["carbomax_auto"] = st.get("carbomax_auto", False)
    new_st["carbomax_auto_apply"] = st.get("carbomax_auto_apply", True)
    new_st["carbomax_max_mass_factor"] = st.get("carbomax_max_mass_factor", 1.25)
    new_st["carbomax_base_names"] = st.get("carbomax_base_names", [])
    new_st["carbomax_device_ip"] = st.get("carbomax_device_ip", "")
    new_st["carbomax_poll_seconds"] = st.get("carbomax_poll_seconds", 15.0)
    new_st["carbomax_busy_poll_seconds"] = st.get("carbomax_busy_poll_seconds", 5.0)
    new_st["carbomax_timeout"] = st.get("carbomax_timeout", 4.0)
    new_st["carbomax_recent_records"] = st.get("carbomax_recent_records", [])
    if new_st["carbomax_auto"]:
        new_st["carbomax_auto_armed_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    # Cuadro Espectro: la conexión/configuración sobreviven al cambio de colada (es configuración del
    # instrumento físico, no de la colada). spectro_recent_results TAMBIÉN sobrevive -- es un log de
    # mediciones del instrumento, no algo atado a una colada puntual.
    new_st["spectro_auto"] = st.get("spectro_auto", False)
    new_st["spectro_host"] = st.get("spectro_host", "")
    new_st["spectro_commands_port"] = st.get("spectro_commands_port", 11000)
    new_st["spectro_events_port"] = st.get("spectro_events_port", 11001)
    new_st["spectro_recent_results"] = st.get("spectro_recent_results", [])
    new_st["spectro_disabled_keys"] = st.get("spectro_disabled_keys", [])
    new_st["spectro_alerts"] = st.get("spectro_alerts", [])
    new_st["spectro_hide_measure"] = st.get("spectro_hide_measure", False)
    new_st["spectro_measuring"] = st.get("spectro_measuring", False)
    new_st["spectro_connected"] = st.get("spectro_connected", False)
    new_st = datos.save_ajuste_session(new_st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    await hub.broadcast("historicos", {"type": "history_changed"})
    return new_st


@router.post("/reload-session")
async def reload_session(_: dict = Depends(devices.require_acceso)):
    """Fuerza a todos los clientes conectados a recargar la sesión desde la DB."""
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return {"ok": True}


@router.post("/save-session")
async def save_session(_: dict = Depends(devices.require_acceso_editor)):
    """Botón "Guardar sesión" / terminar colada.

    Antes de cerrar, si hay un espectrómetro configurado le manda FinishAnalysis -- documenta/exporta el
    análisis activo según el perfil, mismo mecanismo que "Finish Sample" en la GUI, para no dejar algo sin
    cerrar en el instrumento al terminar la colada. Best-effort a propósito: si no hay ningún análisis
    activo o el instrumento no responde, no bloquea el guardado de la sesión -- solo el auto-guardado por
    sesión larga (session_auto_save.py) NO pasa por acá, deliberado: no conviene que un timer de fondo le
    mande FinishAnalysis al instrumento sin que el operario lo haya pedido."""
    st = datos.load_ajuste_session()

    host = str(st.get("spectro_host", "") or "").strip()
    if host:
        import asyncio
        from .. import spectro_client

        commands_port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)
        try:
            await asyncio.to_thread(spectro_client.finish_analysis, host, commands_port)
        except spectro_client.SpectroError:
            pass

    new_st = await _do_save_session(st, auto=False)
    alloys = datos.load_alloys()
    return _session_view(new_st, alloys)


# ---------- Carbomax automático ----------
# Puerto de tab_ajuste.py (bloque "Carbomax automático" -- ver ..carbomax_auto para el cálculo/aplicación del
# plan, ..carbomax_modbus_auto para el loop de fondo RS485/Modbus, la vía principal de detección hoy). Estos
# cuatro endpoints son la contraparte del botón toggle, el diálogo "Configurar..." y la lista de "últimos
# análisis" del original.

@router.post("/carbomax-auto/toggle")
async def toggle_carbomax_auto(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    enabled = bool(payload.get("enabled"))
    if bool(st.get("carbomax_auto")) != enabled:
        st["carbomax_auto"] = enabled
        if enabled:
            st["carbomax_auto_armed_at"] = st.get("session_started_at") or datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            # Sembrar "ahora" como corte: el loop de fondo solo procesa análisis con timestamp posterior a
            # este momento, para no reprocesar algo viejo que haya quedado sin consumir/rechazar de antes de
            # prender el modo automático.
            st["carbomax_last_ts"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        else:
            st["carbomax_auto_armed_at"] = None
        datos.save_ajuste_session(st)
        await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.post("/carbomax-auto/config")
async def configure_carbomax_auto(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    names = [str(n or "").strip() for n in (payload.get("base_names") or [])]
    if len(names) != 3 or any(not n for n in names):
        raise HTTPException(status_code=400, detail={"error": "faltan_materiales", "message": "Completá los 3 materiales (C, Si, Fe)."})
    missing = [n for n in names if not _alloy_by_name(alloys, n)]
    if missing:
        raise HTTPException(status_code=400, detail={"error": "material_no_encontrado", "message": f"No encontrado en catálogo: {', '.join(missing)}"})
    st["carbomax_base_names"] = names
    if "poll_seconds" in payload:
        st["carbomax_poll_seconds"] = max(5.0, min(300.0, to_float(payload.get("poll_seconds"))))
    if "busy_poll_seconds" in payload:
        st["carbomax_busy_poll_seconds"] = max(1.0, min(60.0, to_float(payload.get("busy_poll_seconds"))))
    if "timeout" in payload:
        st["carbomax_timeout"] = max(1.0, min(30.0, to_float(payload.get("timeout"))))
    if "auto_apply" in payload:
        st["carbomax_auto_apply"] = bool(payload.get("auto_apply"))
    if "max_mass_factor" in payload:
        st["carbomax_max_mass_factor"] = max(1.0, to_float(payload.get("max_mass_factor")))
    if str(payload.get("device_ip", "") or "").strip():
        st["carbomax_device_ip"] = str(payload["device_ip"]).strip()
    # Resetear cooldown para que el loop tome el nuevo intervalo de inmediato.
    from .. import carbomax_modbus_auto
    carbomax_modbus_auto.reset_poll_cooldown()
    datos.save_ajuste_session(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.post("/carbomax-auto/check-now")
async def check_carbomax_now(_: dict = Depends(devices.require_acceso_editor)):
    """Botón "Forzar" del panel Carbomax de Ajuste: lee los stands YA en vez de esperar el resto del
    intervalo de poll_seconds, por si el análisis ya terminó. Mismo camino de detección/guardado que el tick
    de fondo -- ver carbomax_modbus_auto.force_check_now(), que reusa _check_stands_once() tal cual usa el
    loop automático. Si aparece algo nuevo, el broadcast "carbomax_result" que ya dispara esa función alcanza
    para refrescar todos los dispositivos (incluido el que apretó el botón); esta respuesta es solo el
    feedback inmediato del click."""
    from .. import carbomax_modbus_auto
    result = await carbomax_modbus_auto.force_check_now()
    if not result.get("ok"):
        raise HTTPException(status_code=400, detail={"error": "carbomax_auto_apagado", "message": result.get("message")})
    return result


@router.post("/carbomax-auto/use-record")
async def use_carbomax_record(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """"Usar" de una fila de la lista de últimos análisis de Carbono -- índice posicional. A diferencia de
    Spectro (que solo copia a Actual), esto corre el cálculo completo del plan C/Si/Fe
    (compute_and_apply_plan) contra los 3 materiales base configurados, así que requiere que ya haya un
    objetivo elegido arriba -- el viejo popup lo pedía inline porque bloqueaba todo hasta resolverse; la
    lista no bloquea nada, así que no hace falta repetir ese selector por cada fila."""
    from .. import carbomax_auto as carbomax_auto_mod

    try:
        index = int(payload.get("index"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail={"error": "index_invalido"})

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    recent = st.get("carbomax_recent_records") or []
    if index < 0 or index >= len(recent):
        raise HTTPException(status_code=404, detail={"error": "registro_no_encontrado"})
    record = recent[index]

    if not str(st.get("objective", "") or "").strip():
        raise HTTPException(status_code=400, detail={
            "error": "objetivo_no_elegido",
            "message": "Elegí la aleación objetivo arriba antes de usar un análisis de Carbomax.",
        })
    record_colada = str(record.get("colada", "") or "").strip()
    current_colada = str(st.get("colada", "") or "").strip()
    if record_colada and record_colada != current_colada:
        raise HTTPException(status_code=409, detail={
            "error": "colada_distinta",
            "message": f'Este análisis es de la colada "{record_colada}" y la colada actual es "{current_colada}" -- revisá antes de aplicar.',
        })

    ok, message = await carbomax_auto_mod.compute_and_apply_plan(
        st, alloys, record.get("carbon", 0), record.get("silicon", 0), record.get("source", ""),
    )
    datos.save_ajuste_session(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    await hub.broadcast("ajuste", {"type": "status_message", "message": message})
    return {"ok": ok, "message": message}

# ---------- Espectrómetro LMX06 (cuadro "Espectro") ----------
# Backend del cuadro de control manual del espectrómetro (ver ..spectro_auto para el listener de fondo/
# orquestación de mediciones, ..spectro_client para el protocolo del instrumento). A diferencia de Carbomax,
# este NO es un flujo automático con popup de confirmación: el cuadro está siempre visible, el operario
# dispara mediciones a mano ("Medir ahora") o deja que el listener pasivo detecte mediciones hechas directo
# en el instrumento, y en los dos casos el resultado cae en spectro_recent_results -- el operario elige qué
# fila copiar a "Actual" con "usar esta medición", sin cálculo/aplicación automática de ningún plan (por eso
# no hay "auto_apply" acá, a diferencia de Carbomax).

@router.post("/spectro-auto/toggle")
async def toggle_spectro_auto(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """"Conectado/Desconectado" del cuadro Espectro -- arranca o para el listener de eventos de fondo
    (spectro_auto.py::_tick_once)."""
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    enabled = bool(payload.get("enabled"))
    if enabled and not str(st.get("spectro_host", "") or "").strip():
        raise HTTPException(status_code=400, detail={
            "error": "host_no_configurado",
            "message": "Configurá el host del espectrómetro antes de conectar.",
        })
    if bool(st.get("spectro_auto")) != enabled:
        st["spectro_auto"] = enabled
        datos.save_ajuste_session(st)
        await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.post("/spectro-auto/reconnect")
async def force_spectro_reconnect(_: dict = Depends(devices.require_acceso_editor)):
    """Botón "Forzar reconexión" de Opciones Spectro (ver spectro_auto.force_reconnect). Prende spectro_auto
    si estaba apagado (forzar reconectar implica querer estar conectado) y tira el listener actual para que
    arranque uno nuevo en el próximo tick, en vez de depender de que is_alive() detecte un socket colgado
    por su cuenta."""
    from .. import spectro_auto

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={
            "error": "host_no_configurado",
            "message": "Configurá el host del espectrómetro antes de reconectar.",
        })
    if not st.get("spectro_auto"):
        st["spectro_auto"] = True
        datos.save_ajuste_session(st)
    spectro_auto.force_reconnect()
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.post("/spectro-auto/config")
async def configure_spectro_auto(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(payload.get("host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_requerido", "message": "Ingresá el host/IP del espectrómetro."})
    st["spectro_host"] = host
    if "commands_port" in payload:
        st["spectro_commands_port"] = int(to_float(payload.get("commands_port")) or 11000)
    if "events_port" in payload:
        st["spectro_events_port"] = int(to_float(payload.get("events_port")) or 11001)
    datos.save_ajuste_session(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.post("/spectro-auto/test")
async def test_spectro_connection(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Botón "Probar conexión" del cuadro: pide GetSoftwareVersion sin tocar la sesión ni el listener de
    fondo."""
    import asyncio
    from .. import spectro_client

    host = str(payload.get("host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_requerido"})
    port = int(to_float(payload.get("commands_port", 11000)) or 11000)
    try:
        version = await asyncio.to_thread(spectro_client.get_software_version, host, port, 5)
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "conexion_fallida", "message": str(ex)}) from ex
    return {"ok": True, "version": version}


@router.post("/spectro-auto/measure")
async def measure_spectro_now(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Botón "Medir ahora": dispara PrepareAnalysis -> Measure -> FinishAnalysis -> GetAnalysisResults
    contra el instrumento real (ver spectro_auto.trigger_measurement para el detalle y el alcance
    deliberadamente acotado -- un replicate, solo muestra "Unknown")."""
    from .. import spectro_auto as spectro_auto_mod

    sample_name = str(payload.get("sample_name", "") or "").strip()
    ok, message, elements = await spectro_auto_mod.trigger_measurement(sample_name)
    return {"ok": ok, "message": message, "elements": elements}


@router.post("/spectro-auto/agent-announce")
async def spectro_agent_announce(request: Request, payload: dict = Body(default={})):
    """La PC del espectrómetro no tiene IP fija (DHCP) -- a diferencia de este host -- así que en vez de
    depender de reconfigurar "Host / IP" a mano cada vez que cambia, spectro_agent_announce.ps1 (tarea
    programada cada 5' en esa PC) se anuncia sola. Se toma la IP de origen real de la conexión
    (request.client.host), no un valor que el agente reporte en el body -- más confiable si esa PC tiene más
    de una interfaz de red.

    No usa el auth de dispositivos.py (eso es para navegadores aprobados por un humano) -- se autentica con
    el mismo token (agent_token()) que ya comparte con enviar_comando() en spectro_agent_client.py, para que solo el
    agente legítimo pueda mover a dónde apunta spectro_host."""
    from .. import spectro_agent_client

    token = str(payload.get("token") or request.query_params.get("token") or "")
    esperado = spectro_agent_client.agent_token()
    if not esperado or token != esperado:
        raise HTTPException(status_code=401, detail={"error": "token_invalido"})

    ip = request.client.host if request.client else None
    if not ip:
        raise HTTPException(status_code=400, detail={"error": "sin_ip"})

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    if st.get("spectro_host") != ip:
        st["spectro_host"] = ip
        datos.save_ajuste_session(st)
        await hub.broadcast("ajuste", {"type": "session_changed"})
    return {"ok": True, "host": ip}


@router.post("/spectro-auto/set-sample-id")
async def set_spectro_sample_id(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Manda un ID de muestra nuevo al instrumento vía PrepareAnalysis, sin disparar Measure -- pensado para
    responder la alerta SampleIdentificationNeeded: el protocolo no permite mandar texto libre dentro de
    FinishOperatorInteraction (solo elige una opción ya ofrecida), así que la "entrada" real pasa por este
    comando -- el operario escribe el ID acá, se lo pasamos al instrumento por la Automation Interface, y
    recién después conviene confirmar la interacción con Ok (spectro-auto/finish-interaction)."""
    import asyncio
    from .. import spectro_client

    sample_value = str(payload.get("sample_id", "") or "").strip()
    if not sample_value:
        raise HTTPException(status_code=400, detail={"error": "sample_id_requerido"})

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    commands_port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)

    try:
        await asyncio.to_thread(spectro_client.prepare_analysis, host, sample_value, commands_port)
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "no_se_pudo_preparar", "message": str(ex)}) from ex
    return {"ok": True}


@router.post("/spectro-auto/finish-interaction")
async def finish_spectro_interaction(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Responde desde la web una OperatorInteractionNeeded pendiente (ver spectro_auto.py::_on_spectro_alert_event,
    alerta más reciente del cuadro Espectro) -- contraparte de FinishOperatorInteraction. Sin esto la alerta
    se veía pero no había forma de resolverla salvo pararse frente al instrumento.

    El instrumento va a empujar OperatorInteractionFinished solo y ESE evento es quien de verdad marca
    "resolved" (mismo camino que si alguien la resuelve parado frente al instrumento) -- pero no conviene
    esperar esa vuelta para que la web sepa que funcionó, así que también se marca acá al toque, redundante
    a propósito."""
    import asyncio
    from .. import spectro_client
    from .. import spectro_auto

    interaction_name = str(payload.get("interaction_name", "") or "").strip()
    if not interaction_name:
        raise HTTPException(status_code=400, detail={"error": "interaction_name_requerido"})
    option = payload.get("option")
    option = str(option).strip() if option else None

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    commands_port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)

    try:
        await asyncio.to_thread(
            spectro_client.finish_operator_interaction, host, interaction_name, option, commands_port,
        )
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "no_se_pudo_responder", "message": str(ex)}) from ex

    # Releer antes de escribir -- la llamada de red de arriba tarda (mismo criterio que trigger_measurement).
    st = datos.load_ajuste_session()
    if spectro_auto._resolve_pending_interaction(st, interaction_name, option):
        datos.save_ajuste_session(st)
        await hub.broadcast("ajuste", {"type": "session_changed"})
    return {"ok": True}


@router.get("/spectro-auto/keys")
async def get_spectro_keys(_: dict = Depends(devices.require_acceso)):
    """Lista de comandos de la botonera de teclado remoto (ver spectro_agent_client.py) para que la web
    arme los botones, con `activo` marcando cuáles están visibles hoy -- la web muestra solo los activos en
    la botonera y TODOS en el checklist de "Opciones Spectro"."""
    from .. import spectro_agent_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    disabled = set(st.get("spectro_disabled_keys", []) or [])
    comandos = spectro_agent_client.comandos_publicos()
    for c in comandos:
        c["activo"] = c["slug"] not in disabled
    return {"comandos": comandos}


@router.post("/spectro-auto/keys/visibility")
async def set_spectro_keys_visibility(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Checklist de "Opciones Spectro": guarda qué comandos de la botonera quedan ocultos. Reemplaza la
    lista completa, y es compartida -- lo que se desmarca ahí se va de la botonera para todos los
    dispositivos."""
    from .. import spectro_agent_client

    raw = payload.get("disabled")
    if not isinstance(raw, list):
        raise HTTPException(status_code=400, detail={"error": "disabled_invalido"})
    disabled = [str(s) for s in raw if str(s) in spectro_agent_client.COMANDOS]

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    st["spectro_disabled_keys"] = disabled
    datos.save_ajuste_session(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return {"ok": True, "disabled": disabled}


@router.post("/spectro-auto/hide-measure-button")
async def set_hide_measure_button(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Checklist de "Opciones Spectro": "Medir ahora" nunca funciona sin licencia Full -- esto lo saca de la
    vista (compartido, para todos los dispositivos) sin borrar el botón/endpoint del código."""
    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    st["spectro_hide_measure"] = bool(payload.get("hidden"))
    datos.save_ajuste_session(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.post("/spectro-auto/send-key")
async def send_spectro_key(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """Botonera de teclado remoto: manda una tecla real a la ventana de LMX06MeasurementGUI.exe vía el
    agente que corre en su sesión interactiva (ver spectro_agent_client.py) -- la alternativa a "Medir
    ahora" cuando el control remoto del instrumento está en modo "Limited" y no permite Measure por la
    Automation Interface."""
    import asyncio
    from .. import spectro_agent_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={
            "error": "host_no_configurado",
            "message": "Configurá el host del espectrómetro antes de usar la botonera.",
        })
    slug = str(payload.get("cmd", "") or "").strip()
    if slug not in spectro_agent_client.COMANDOS:
        raise HTTPException(status_code=400, detail={"error": "comando_desconocido"})
    try:
        result = await asyncio.to_thread(spectro_agent_client.enviar_comando, host, slug)
    except spectro_agent_client.SpectroAgentError as ex:
        raise HTTPException(status_code=502, detail={"error": "agente_inalcanzable", "message": str(ex)}) from ex
    return result


@router.post("/spectro-auto/start-flush")
async def start_spectro_flush(_: dict = Depends(devices.require_acceso_editor)):
    """Arranca el flush por API (manual 8.32) -- alternativa a la tecla F de la botonera que no depende de
    que la ventana de LMX06MeasurementGUI.exe tenga foco (mismo criterio que stop-measure)."""
    import asyncio
    from .. import spectro_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    commands_port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)

    try:
        await asyncio.to_thread(spectro_client.start_flush, host, commands_port)
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "no_se_pudo_iniciar", "message": str(ex)}) from ex
    return {"ok": True}


@router.post("/spectro-auto/stop-flush")
async def stop_spectro_flush(_: dict = Depends(devices.require_acceso_editor)):
    """Para el flush por API (manual 8.33) -- contraparte de start-flush."""
    import asyncio
    from .. import spectro_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    commands_port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)

    try:
        await asyncio.to_thread(spectro_client.stop_flush, host, commands_port)
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "no_se_pudo_detener", "message": str(ex)}) from ex
    return {"ok": True}


@router.post("/spectro-auto/stop-measure")
async def stop_spectro_measure(_: dict = Depends(devices.require_acceso_editor)):
    """Corta una medición en curso vía StopMeasure -- sin payload, a diferencia del resto de las rutas de
    este archivo. Funciona en paralelo a measure_spectro_now (que queda bloqueado en asyncio.to_thread
    esperando la respuesta de Measure en SU propia conexión): StopMeasure abre una conexión nueva a
    propósito, es el único comando del protocolo pensado para usarse así."""
    import asyncio
    from .. import spectro_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    commands_port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)

    try:
        await asyncio.to_thread(spectro_client.stop_measure, host, commands_port)
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "no_se_pudo_detener", "message": str(ex)}) from ex
    return {"ok": True}


@router.post("/spectro-auto/use-result")
async def use_spectro_result(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    """"Usar en Actual" de una fila de la tabla de últimas mediciones -- id posicional (mismo criterio que
    /api/alloys/{idx}), copia esos elementos a "Actual" (sin C/Si, ver spectro_auto._apply_elements) y
    listo: NO corre estimate/apply, eso lo dispara el operario aparte con "Calcular"/"Aplicar" como
    cualquier carga manual de composición."""
    from .. import spectro_auto as spectro_auto_mod

    try:
        index = int(payload.get("index"))
    except (TypeError, ValueError):
        raise HTTPException(status_code=400, detail={"error": "index_invalido"})

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    recent = st.get("spectro_recent_results") or []
    if index < 0 or index >= len(recent):
        raise HTTPException(status_code=404, detail={"error": "resultado_no_encontrado"})

    st["actual"] = spectro_auto_mod._apply_elements(st, recent[index].get("elements", {}))
    datos.save_ajuste_session(st)
    if st.get("colada") and st.get("objective"):
        await _publish_furnace_context(st)
    await hub.broadcast("ajuste", {"type": "session_changed"})
    return _session_view(st, alloys)


@router.get("/spectro-auto/instrument")
async def get_spectro_instrument(_: dict = Depends(devices.require_acceso)):
    """Estado del instrumento + modo de control remoto bajo demanda (además del push periódico de
    spectro_auto.py::_tick_once) -- para el botón de refresco manual del cuadro."""
    import asyncio
    from .. import spectro_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)
    try:
        state = await asyncio.to_thread(spectro_client.get_instrument_state, host, port)
        mode = await asyncio.to_thread(spectro_client.get_remote_control_state, host, port)
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "conexion_fallida", "message": str(ex)}) from ex
    return {"state": state, "remote_control_mode": mode}


@router.get("/spectro-auto/methods")
async def get_spectro_methods(_: dict = Depends(devices.require_acceso)):
    import asyncio
    from .. import spectro_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)
    try:
        methods = await asyncio.to_thread(spectro_client.get_method_names, host, port)
        current = await asyncio.to_thread(spectro_client.get_current_method_name, host, port)
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "conexion_fallida", "message": str(ex)}) from ex
    return {"methods": methods, "current": current}


@router.post("/spectro-auto/select-method")
async def select_spectro_method(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    import asyncio
    from .. import spectro_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)
    excitation_type = str(payload.get("excitation_type", "") or "").strip()
    base_element = str(payload.get("base_element", "") or "").strip()
    method_name = str(payload.get("method_name", "") or "").strip()
    if not method_name:
        raise HTTPException(status_code=400, detail={"error": "metodo_requerido"})
    try:
        pending_ical = await asyncio.to_thread(
            spectro_client.select_method, host, excitation_type, base_element, method_name, port,
        )
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "conexion_fallida", "message": str(ex)}) from ex
    return {"ok": True, "pending_ical": pending_ical}


@router.get("/spectro-auto/profiles")
async def get_spectro_profiles(_: dict = Depends(devices.require_acceso)):
    import asyncio
    from .. import spectro_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)
    try:
        profiles = await asyncio.to_thread(spectro_client.get_profile_names, host, port)
        current = await asyncio.to_thread(spectro_client.get_current_profile_name, host, port)
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "conexion_fallida", "message": str(ex)}) from ex
    return {"profiles": profiles, "current": current}


@router.post("/spectro-auto/select-profile")
async def select_spectro_profile(payload: dict = Body(...), _: dict = Depends(devices.require_acceso_editor)):
    import asyncio
    from .. import spectro_client

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        raise HTTPException(status_code=400, detail={"error": "host_no_configurado"})
    port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)
    profile_name = str(payload.get("profile_name", "") or "").strip()
    if not profile_name:
        raise HTTPException(status_code=400, detail={"error": "perfil_requerido"})
    try:
        pending_ical = await asyncio.to_thread(spectro_client.select_profile, host, profile_name, port)
    except spectro_client.SpectroError as ex:
        raise HTTPException(status_code=502, detail={"error": "conexion_fallida", "message": str(ex)}) from ex
    return {"ok": True, "pending_ical": pending_ical}
