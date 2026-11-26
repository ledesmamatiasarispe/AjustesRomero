# carbomax_auto.py -- puerto PARCIAL de backend/core/carbomax_auto.py de ajuste_comp_web: solo lo que no
# depende de Análisis Térmico (device_sync.py/termico.py, todavía no portados). Esto alcanza para que el
# camino PRINCIPAL de detección (Modbus, ver carbomax_modbus_auto.py) funcione de punta a punta, incluido
# "usar" un análisis de la lista -- lo único que queda afuera es el camino de red/CGI (descarga de curvas
# completas), que en la app vieja tiene su propio loop de fondo QUE NI SIQUIERA SE ARRANCA hoy (decisión del
# usuario, 11/09/2026: Modbus es la vía principal) -- solo se usa a demanda desde Análisis Térmico, así que no
# bloquea nada portar esto ahora y el resto cuando se porte ese módulo.
#
# Funciones que SÍ se portan (no dependen de termico.py/device_sync.py):
#   _record_keys, _append_recent_record, _apply_carbon_silicon, _mass_cap_ok, compute_and_apply_plan,
#   reset_poll_cooldown.
# Funciones que NO se portan todavía (dependen de termico.py/device_sync.py, van con esa fase):
#   _pick_latest_unconsumed_record, _download_and_link, _tick_once, carbomax_auto_loop (el loop de red/CGI).
from datetime import datetime

from . import calc
from .utils import to_float

_MAX_RECENT_RECORDS = 20

_last_poll_monotonic = 0.0


def reset_poll_cooldown():
    """Fuerza al próximo tick a revisar de inmediato en vez de esperar el cooldown restante."""
    global _last_poll_monotonic
    _last_poll_monotonic = 0.0


def _record_keys(record):
    """Identificadores estables de un registro del dispositivo (independientes del path, que puede cambiar
    entre descargas) usados para no reprocesar/reconsumir el mismo análisis dos veces."""
    if not isinstance(record, dict):
        return set()
    keys = set()
    for value in (record.get("path", ""), record.get("legacy_path", ""), record.get("identity", "")):
        text = str(value or "").strip()
        if text:
            keys.add(text)
    local_id = str(record.get("local_id", "") or "").strip()
    if local_id:
        keys.add(local_id)
        keys.add(f"local_id:{local_id}")
    return keys


def _append_recent_record(st, carbon, silicon, source_label, analysis_dt, record_keys):
    """Agrega un análisis de Carbono detectado a carbomax_recent_records (más nuevo primero, recortado a
    _MAX_RECENT_RECORDS) -- mismo criterio que spectro_auto._append_recent_result. "colada" queda grabado con
    el valor de ESTE momento: la lista sobrevive al cambio de colada (es un log del dispositivo), así que hace
    falta para distinguir después cuáles análisis son de la colada actual. Muta st in-place, no guarda."""
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "colada": str(st.get("colada", "") or "").strip(),
        "source": str(source_label or "").strip(),
        "carbon": to_float(carbon),
        "silicon": to_float(silicon),
        "analysis_ts": analysis_dt.strftime("%Y-%m-%d %H:%M:%S") if analysis_dt else None,
        "record_keys": list(record_keys or []),
    }
    recent = list(st.get("carbomax_recent_records") or [])
    recent.insert(0, entry)
    st["carbomax_recent_records"] = recent[:_MAX_RECENT_RECORDS]


def _apply_carbon_silicon(st, carbon, silicon):
    """Carga C/Si en "Actual" y recalcula Fe por diferencia -- mismo criterio que usa el popup de Carbono
    simple del lado frontend. Única fuente real de esta cuenta: rutas/ajuste.py::load_carbon_silicon la llama
    de acá en vez de tener su propia copia."""
    actual = dict(st.get("actual") or {})
    actual["C"] = to_float(carbon)
    actual["Si"] = to_float(silicon)
    total = sum(to_float(v) for el, v in actual.items() if el != "Fe")
    actual["Fe"] = max(0.0, 100.0 - total)
    return actual


def _mass_cap_ok(st, alloys, plan):
    """Tope de seguridad de masa: no deja que el plan automático infle la masa del baño más de
    carbomax_max_mass_factor veces la masa base."""
    from .rutas.ajuste import _predicted_from_kg

    base_mass = to_float(st.get("mass", 0))
    if base_mass <= 0:
        return True, base_mass, base_mass
    probe = dict(st)
    probe["kg"] = {n: to_float(kg) for n, kg in plan.items()}
    predicted_mass = _predicted_from_kg(probe, alloys)["mass"]
    max_mass = base_mass * to_float(st.get("carbomax_max_mass_factor", 1.25))
    return predicted_mass <= max_mass, base_mass, predicted_mass


async def compute_and_apply_plan(st, alloys, carbon, silicon, source_label=""):
    """Calcula el plan C/Si/Fe con el mismo motor que /api/ajuste/estimate (calc.estimate_plan), pero
    restringido a los 3 materiales base configurados -- no a la lista completa de ajuste del usuario. Aplica
    el tope de seguridad de masa, escribe kg en la sesión, y aplica (POST /apply) o solo calcula según
    carbomax_auto_apply.

    Muta st in-place. NO guarda ni hace broadcast -- eso lo hace el llamador (rutas/ajuste.py::use_carbomax_record),
    junto con cualquier otro campo que también haya cambiado en la misma escritura. Devuelve (ok: bool, message: str)."""
    from .rutas.ajuste import _alloy_by_name, _objective_alloy, _objective_ce_data, _commit_apply

    st["actual"] = _apply_carbon_silicon(st, carbon, silicon)

    base_names = list(st.get("carbomax_base_names") or [])
    if len(base_names) != 3:
        return False, "Carbomax automático: materiales C/Si/Fe no configurados."

    adjust_alloys = {n: _alloy_by_name(alloys, n) for n in base_names}
    missing = [n for n, a in adjust_alloys.items() if a is None]
    if missing:
        return False, f"Carbomax automático: no encontrado en catálogo: {', '.join(missing)}."

    obj = _objective_alloy(alloys, st.get("objective", ""))
    if not obj:
        return False, "Carbomax automático: objetivo no encontrado."
    _, _, ce_formula, ce_custom = _objective_ce_data(obj)

    result = calc.estimate_plan(
        st.get("actual", {}), st.get("mass", 0), obj["composicion"], adjust_alloys,
        method=st.get("method", "Greedy"), ce_formula=ce_formula, ce_custom=ce_custom,
    )
    if "error" in result or not result.get("plan"):
        return False, "Carbomax automático: no se pudo calcular el ajuste (faltan materiales base C/Si/Fe)."

    plan = result["plan"]
    ok, base_mass, predicted_mass = _mass_cap_ok(st, alloys, plan)
    if not ok:
        return False, (
            f"Carbomax automático bloqueado: el plan llevaría la masa de "
            f"{base_mass:.1f} kg a {predicted_mass:.1f} kg. Revisar C/Si o ajustar manualmente."
        )

    adjust_list = list(st.get("adjust_list") or [])
    for name in base_names:
        if name not in adjust_list:
            adjust_list.append(name)
    st["adjust_list"] = adjust_list
    kg = {n: 0.0 for n in adjust_list}
    for name, value in plan.items():
        kg[name] = round(to_float(value), 3)
    st["kg"] = kg

    if bool(st.get("carbomax_auto_apply", True)):
        await _commit_apply(st, alloys)
        action = "aplicado"
    else:
        action = "calculado (sin aplicar)"
    src_txt = f" [{source_label}]" if source_label else ""
    return True, f"Carbomax automático {action}: C={to_float(carbon):.2f}% Si={to_float(silicon):.2f}%{src_txt}"
