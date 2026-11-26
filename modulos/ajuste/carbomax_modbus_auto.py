# carbomax_modbus_auto.py -- puerto sin cambios de comportamiento de backend/carbomax_modbus_auto.py de
# ajuste_comp_web. Detección automática de análisis Carbono nuevos por RS485/Modbus (stands 3 y 4 -- los dos
# configurados de fábrica en modo CARBONO, ver carbomax_modbus.py para el protocolo y el mapa de registros
# confirmado). Es la vía PRINCIPAL de detección automática hoy (decisión del usuario, 11/09/2026) -- local
# (COM3), no depende de que la red al equipo esté arriba.
import asyncio
import time
from datetime import datetime

from . import carbomax_modbus
from . import datos
from .carbomax_auto import _append_recent_record
from .utils import to_float

_TICK_SECONDS = 5.0
_DEFAULT_POLL_SECONDS = 60.0

_last_poll_monotonic = 0.0


def reset_poll_cooldown():
    global _last_poll_monotonic
    _last_poll_monotonic = 0.0


def _stand_state_key(stand_no):
    return f"carbomax_modbus_last_stand{stand_no}"


# Rangos metalúrgicamente plausibles para descartar basura residual de un stand sin usar (ej. Stand 3:
# C=-6.05%, Si=62.3%, temperaturas en 0.0 -- no-cero pero sin sentido, confirmado el 11/09/2026). Generosos a
# propósito: el objetivo es filtrar basura obvia, no validar de más.
_CARBON_RANGE = (0.5, 8.0)
_SILICON_RANGE = (0.1, 6.0)
_TEMP_RANGE = (500.0, 1800.0)


def _is_valid_measurement(decoded):
    carbon = decoded.get("c")
    silicon = decoded.get("si")
    temps = (decoded.get("pico"), decoded.get("tl"), decoded.get("ts"), decoded.get("tf"))
    if carbon is None or silicon is None or any(t is None for t in temps):
        return False
    if not (_CARBON_RANGE[0] <= carbon <= _CARBON_RANGE[1]):
        return False
    if not (_SILICON_RANGE[0] <= silicon <= _SILICON_RANGE[1]):
        return False
    return all(_TEMP_RANGE[0] <= t <= _TEMP_RANGE[1] for t in temps)


async def _check_stands_once(st):
    """Lee los dos stands por Modbus, detecta y registra análisis nuevos. Compartida por el tick automático y
    por force_check_now() -- la única diferencia entre ambos caminos es QUIÉN decide cuándo llamarla (el
    cooldown de poll_seconds vs. un click manual), la detección/guardado es la misma lógica una sola vez.
    Devuelve (any_block_changed, new_records, errors_by_stand) -- no guarda la sesión, eso lo hace el llamador."""
    from .ws import hub

    any_block_changed = False
    new_records = 0
    errors = {}
    for stand_no, base in carbomax_modbus.STAND_BLOCK_BASES.items():
        try:
            registers = await asyncio.to_thread(carbomax_modbus.read_stand_block, base)
        except Exception as ex:
            print(f"[carbomax_modbus_auto] stand {stand_no}: {ex}", flush=True)
            errors[stand_no] = str(ex)
            continue

        block = registers[:carbomax_modbus.STAND_BLOCK_SIZE]
        key = _stand_state_key(stand_no)
        previous = st.get(key)
        if previous == block:
            continue  # misma medición de siempre, nada que hacer

        st[key] = block
        any_block_changed = True

        decoded = carbomax_modbus.decode_carbono_block(registers, base)
        if not _is_valid_measurement(decoded):
            # Bloque vacío, recién inicializado, o basura residual -- no es un análisis real; se guarda igual
            # el estado para no volver a compararlo contra None.
            continue
        carbon = decoded["c"]
        silicon = decoded["si"]

        source_label = f"Carbomax Modbus — Stand {stand_no}"
        analysis_dt = datetime.now()
        record_keys = {f"modbus:stand{stand_no}:{analysis_dt.isoformat(timespec='seconds')}"}
        _append_recent_record(st, carbon, silicon, source_label, analysis_dt, record_keys)
        new_records += 1
        print(
            f"[carbomax_modbus_auto] analisis nuevo detectado: stand {stand_no} "
            f"C={to_float(carbon):.2f}% Si={to_float(silicon):.2f}%", flush=True,
        )
        await hub.broadcast("ajuste", {
            "type": "carbomax_result", "carbon": carbon, "silicon": silicon, "source_name": source_label,
        })

    return any_block_changed, new_records, errors


async def _tick_once():
    global _last_poll_monotonic
    from .rutas.ajuste import _load_and_clean

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    if not bool(st.get("carbomax_auto")):
        return

    now = time.monotonic()
    poll_seconds = to_float(st.get("carbomax_modbus_poll_seconds", _DEFAULT_POLL_SECONDS))
    if now - _last_poll_monotonic < poll_seconds:
        return
    _last_poll_monotonic = now

    any_block_changed, _new_records, _errors = await _check_stands_once(st)
    if any_block_changed:
        datos.save_ajuste_session(st)


async def force_check_now():
    """Puerto del botón 'Forzar' del panel Carbomax de Ajuste: poder revisar YA si un análisis ya terminó, sin
    esperar el resto del intervalo de poll_seconds. Hace exactamente lo mismo que un tick del loop de fondo --
    misma _check_stands_once(), mismo dedup por bloque crudo, mismo broadcast -- solo que ignora el cooldown.
    Reinicia el cooldown a partir de AHORA para que el tick de fondo no vuelva a leer los stands un instante
    después de este chequeo manual."""
    global _last_poll_monotonic
    from .rutas.ajuste import _load_and_clean

    alloys = datos.load_alloys()
    st = _load_and_clean(alloys)
    if not bool(st.get("carbomax_auto")):
        return {"ok": False, "message": "Carbomax automático está apagado."}

    any_block_changed, new_records, errors = await _check_stands_once(st)
    if any_block_changed:
        datos.save_ajuste_session(st)
    _last_poll_monotonic = time.monotonic()
    return {"ok": True, "new_records": new_records, "errors": errors}


async def carbomax_modbus_auto_loop():
    """Tarea de fondo persistente -- arrancada una sola vez desde Modulo.al_iniciar. Nunca debería terminar
    sola; cualquier excepción de un tick se loguea y el loop sigue."""
    print("[carbomax_modbus_auto] loop de fondo arrancado", flush=True)
    while True:
        try:
            await _tick_once()
        except Exception as ex:
            print(f"[carbomax_modbus_auto] tick error: {ex}", flush=True)
        await asyncio.sleep(_TICK_SECONDS)
