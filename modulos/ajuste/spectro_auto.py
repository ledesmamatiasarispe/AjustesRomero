# spectro_auto.py -- puerto sin cambios de comportamiento de backend/core/spectro_auto.py de ajuste_comp_web.
# Soporte de fondo para el cuadro "Espectro" del panel de Ajuste: mantiene vivo un listener de eventos del
# espectrómetro LMX06 (ver spectro_client.py), agrega cada resultado nuevo a una lista de "últimas mediciones"
# de la sesión compartida, publica el estado del instrumento en vivo, y orquesta el ciclo completo de una
# medición disparada a mano desde la web (botón "Medir ahora").
#
# El espectrómetro NO es confiable para C/Si (limitación conocida de OES en hierro fundido) -- terreno
# exclusivo de Carbomax. _on_spectro_event y trigger_measurement descartan esas dos keys (y Fe, remainder
# calculado) aunque el instrumento las incluya en la respuesta.
import asyncio
import threading
import time

from . import datos
from . import spectro_client
from .utils import to_float

_TICK_SECONDS = 2.0
_MAX_RECENT_RESULTS = 20
_INSTRUMENT_POLL_EVERY_N_TICKS = 5  # ~10s a _TICK_SECONDS=2.0

_listener = None            # spectro_client.SpectroEventsListener activo, o None
_listener_key = None        # (host, events_port) con el que se armó _listener
_listener_lock = threading.Lock()
_tick_count = 0
# Último estado/modo conocido -- cada evento (InstrumentStateChanged, RemoteControlChanged) solo trae UNA de
# las dos partes del broadcast "spectro_instrument_state" que ya espera el frontend, así que ambos handlers
# completan la otra mitad con el último valor que se sepa.
_last_remote_control_mode = ""
_last_instrument_state = {}


def _apply_elements(st, elements):
    """Carga TODOS los elementos del dict salvo C/Si/Fe en "Actual" y recalcula Fe por diferencia -- mismo
    criterio que carbomax_auto._apply_carbon_silicon para C/Si. Usado tanto por el listener pasivo como por
    el endpoint "usar esta medición"."""
    actual = dict(st.get("actual") or {})
    for el, pct in (elements or {}).items():
        if el in ("C", "Si", "Fe"):
            continue
        actual[el] = to_float(pct)
    total = sum(to_float(v) for el, v in actual.items() if el != "Fe")
    actual["Fe"] = max(0.0, 100.0 - total)
    return actual


def _append_recent_result(st, elements, source_label):
    """Agrega un resultado a spectro_recent_results (más nuevo primero) y recorta a los últimos
    _MAX_RECENT_RESULTS. Muta st in-place, no guarda -- eso lo hace el llamador.

    "colada" queda grabado con el valor de ESTE momento -- la lista sobrevive al cambio de colada a propósito
    (es un log del instrumento, no algo que se vacía)."""
    entry = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "source": str(source_label or "").strip(),
        "elements": dict(elements or {}),
        "colada": str(st.get("colada", "") or "").strip(),
    }
    recent = list(st.get("spectro_recent_results") or [])
    recent.insert(0, entry)
    st["spectro_recent_results"] = recent[:_MAX_RECENT_RESULTS]


_ALERT_KINDS = (
    "ProcessError", "ProcessInformation",
    "OperatorInteractionNeeded", "OperatorInteractionFinished",
    "MeasurementBroken",
)
_MAX_ALERTS = 20
_ALERT_EXPIRY_MINUTES = 3
_MEASURING_STALE_SECONDS = 120
_measuring_since = None


def _set_measuring_state(phase, st=None):
    """Actualiza spectro_measuring (badge en vivo del panel) y avisa por WebSocket. `phase` es False
    (inactivo), "measuring" (lectura física en curso) o "calculating" (lectura terminada, todavía calculando
    el resultado). Si se pasa `st` ya cargado lo muta pero NO guarda -- el llamador es responsable de
    datos.save_ajuste_session."""
    global _measuring_since
    own_transaction = st is None
    if st is None:
        st = datos.load_ajuste_session()
    if st.get("spectro_measuring") == phase:
        return  # sin cambio, no hace falta guardar/avisar de nuevo
    st["spectro_measuring"] = phase
    _measuring_since = time.monotonic() if phase else None
    if own_transaction:
        datos.save_ajuste_session(st)
    from .ws import hub
    hub.broadcast_threadsafe("ajuste", {"type": "spectro_measuring", "phase": phase})


def _append_alert(st, entry):
    """Mismo criterio que _append_recent_result: más nuevo primero, recortado a _MAX_ALERTS. Poda de paso
    las alertas vencidas. Muta st in-place, no guarda."""
    alerts = list(st.get("spectro_alerts") or [])
    alerts.insert(0, entry)
    st["spectro_alerts"] = alerts[:_MAX_ALERTS]
    _prune_expired_alerts(st)


def _prune_expired_alerts(st):
    """Saca del log las alertas que ya dejaron de ser accionables hace más de _ALERT_EXPIRY_MINUTES:
    ProcessInformation (nunca pide respuesta), MeasurementBroken (informativa después del hecho) y
    OperatorInteractionNeeded ya resuelta. ProcessError se deja siempre y una OperatorInteractionNeeded sin
    resolver también (todavía espera una respuesta humana).

    Muta st in-place, no guarda -- el llamador decide si vale la pena guardar/avisar. Devuelve True si saco
    algo."""
    alerts = st.get("spectro_alerts") or []
    if not alerts:
        return False
    now = time.time()
    kept = []
    changed = False
    for a in alerts:
        expirable = (
            a.get("kind") in ("ProcessInformation", "MeasurementBroken")
            or (a.get("kind") == "OperatorInteractionNeeded" and a.get("resolved"))
        )
        if expirable:
            try:
                ts = time.mktime(time.strptime(a.get("ts", ""), "%Y-%m-%d %H:%M:%S"))
            except (ValueError, TypeError):
                ts = None  # ts ilegible -- se deja, mejor de más que reventar
            if ts is not None and (now - ts) >= _ALERT_EXPIRY_MINUTES * 60:
                changed = True
                continue
        kept.append(a)
    if changed:
        st["spectro_alerts"] = kept
    return changed


def _resolve_pending_interaction(st, interaction_name, resolved_option):
    """Marca resuelta la OperatorInteractionNeeded pendiente más reciente con ese nombre (si hay una) --
    común a OperatorInteractionFinished (resuelta físicamente frente al instrumento O vía
    FinishOperatorInteraction) y a finish_spectro_interaction. Muta st in-place, no guarda. Devuelve True si
    encontró y marcó algo."""
    alerts = st.get("spectro_alerts") or []
    for a in alerts:
        if a.get("kind") == "OperatorInteractionNeeded" and a.get("name") == interaction_name and not a.get("resolved"):
            a["resolved"] = True
            a["resolved_option"] = resolved_option or ""
            return True
    return False


def _on_spectro_alert_event(name, xml_element):
    """Callback para ProcessError/ProcessInformation/OperatorInteractionNeeded/OperatorInteractionFinished --
    eventos que reflejan un diálogo mostrado en la pantalla del instrumento. A diferencia de
    MeasurementCompleted/AnalysisFinished, ES el propio telegrama del evento el que ya trae todo lo que hace
    falta -- no hace falta ninguna llamada de red adicional."""
    para = xml_element.find("Para")

    if name == "OperatorInteractionFinished":
        interaction_name = ""
        resolved_option = ""
        if para is not None:
            desc = para.find("OperatorInteractionDescriptor")
            if desc is not None:
                interaction_name = (desc.findtext("InteractionName") or "").strip()
                resolved_option = (desc.findtext("SelectedInteractionOption") or "").strip()
        if not interaction_name:
            return
        st = datos.load_ajuste_session()
        if not _resolve_pending_interaction(st, interaction_name, resolved_option):
            return  # no había nada pendiente con ese nombre -- nada que actualizar
        datos.save_ajuste_session(st)
        from .ws import hub
        hub.broadcast_threadsafe("ajuste", {
            "type": "spectro_alert_resolved",
            "name": interaction_name,
            "resolved_option": resolved_option,
        })
        return

    entry = {
        "ts": time.strftime("%Y-%m-%d %H:%M:%S"),
        "kind": name,
        "name": "",
        "detail": "",
        "options": [],
        "resolved": False,
    }
    if name == "MeasurementBroken":
        entry["name"] = "Medición interrumpida"
    elif para is not None:
        if name == "ProcessError":
            desc = para.find("ProcessErrorDescriptor")
            if desc is not None:
                entry["name"] = (desc.findtext("ErrorName") or "").strip()
                entry["detail"] = (desc.findtext("ErrorType") or "").strip()
        elif name == "ProcessInformation":
            desc = para.find("ProcessInformationDescriptor")
            if desc is not None:
                entry["name"] = (desc.findtext("InformationName") or "").strip()
                entry["detail"] = (desc.findtext("InformationType") or "").strip()
        elif name == "OperatorInteractionNeeded":
            desc = para.find("OperatorInteractionDescriptor")
            if desc is not None:
                entry["name"] = (desc.findtext("InteractionName") or "").strip()
                entry["options"] = [
                    (opt.text or "").strip()
                    for opt in desc.findall("./InteractionOptions/InteractionOption")
                ]

    st = datos.load_ajuste_session()
    _append_alert(st, entry)
    if name == "MeasurementBroken":
        _set_measuring_state(False, st=st)
    datos.save_ajuste_session(st)

    from .ws import hub
    hub.broadcast_threadsafe("ajuste", {"type": "spectro_alert", **entry})


def _on_instrument_state_changed_event(xml_element):
    """El instrumento empuja su InstrumentStateDescriptor completo cada vez que algo cambia -- no hace falta
    ninguna llamada de red adicional para procesarlo."""
    global _last_instrument_state
    para = xml_element.find("Para")
    desc = para.find("InstrumentStateDescriptor") if para is not None else None
    if desc is None:
        return
    state = {child.tag: (child.text or "").strip() for child in desc}
    _last_instrument_state = state
    from .ws import hub
    hub.broadcast_threadsafe("ajuste", {
        "type": "spectro_instrument_state",
        "state": state,
        "remote_control_mode": _last_remote_control_mode,
    })


def _on_remote_control_changed_event(xml_element):
    """El instrumento avisa apenas cambia el modo de control remoto (Full/Limited/Off). Reusa el último
    InstrumentStateDescriptor conocido para completar el broadcast (este evento no lo trae, solo el modo)."""
    global _last_remote_control_mode
    para = xml_element.find("Para")
    desc = para.find("RemoteControlDescriptor") if para is not None else None
    if desc is None:
        return
    mode = (desc.findtext("RemoteControlMode") or "").strip()
    if not mode:
        return
    _last_remote_control_mode = mode
    from .ws import hub
    hub.broadcast_threadsafe("ajuste", {
        "type": "spectro_instrument_state",
        "state": _last_instrument_state,
        "remote_control_mode": mode,
    })


def _on_spectro_event(name, xml_element):
    """Callback de SpectroEventsListener -- corre en el thread del listener, NO en el event loop de asyncio.
    Trae el resultado (llamada de red bloqueante) y lo agrega a la lista de resultados recientes de la
    sesión compartida vía datos.* (sincrono) + hub.broadcast_threadsafe()."""
    if name == "InstrumentStateChanged":
        _on_instrument_state_changed_event(xml_element)
        return
    if name == "RemoteControlChanged":
        _on_remote_control_changed_event(xml_element)
        return
    if name == "MeasurementStarted":
        _set_measuring_state("measuring")
        return
    if name == "MeasurementFinished":
        _set_measuring_state("calculating")
        return
    if name in _ALERT_KINDS:
        _on_spectro_alert_event(name, xml_element)
        return
    listener = _listener
    if listener is None:
        return
    _set_measuring_state(False)
    try:
        elements = spectro_client.get_analysis_results(listener.host, port=listener.commands_port)
    except spectro_client.SpectroError as ex:
        print(f"[spectro_auto] error trayendo resultado: {ex}", flush=True)
        return
    except Exception as ex:
        print(f"[spectro_auto] error inesperado trayendo resultado: {ex}", flush=True)
        return

    elements = {el: pct for el, pct in elements.items() if el not in ("C", "Si", "Fe")}
    if not elements:
        print("[spectro_auto] análisis sin elementos utilizables (¿solo C/Si?), se ignora.", flush=True)
        return

    st = datos.load_ajuste_session()
    if not bool(st.get("spectro_auto")):
        return  # se desactivó mientras se traía el resultado
    _append_recent_result(st, elements, name)
    datos.save_ajuste_session(st)

    from .ws import hub
    hub.broadcast_threadsafe("ajuste", {
        "type": "spectro_result",
        "elements": elements,
        "source_name": name,
    })


def _on_spectro_status(msg):
    print(f"[spectro_auto] {msg}", flush=True)


def _on_spectro_connected(is_connected):
    """Refleja en la sesión compartida si el instrumento responde de verdad ahora mismo."""
    st = datos.load_ajuste_session()
    if bool(st.get("spectro_connected")) == is_connected:
        return
    st["spectro_connected"] = is_connected
    datos.save_ajuste_session(st)
    from .ws import hub
    hub.broadcast_threadsafe("ajuste", {"type": "spectro_connected", "connected": is_connected})


spectro_client.set_connectivity_hook(_on_spectro_connected)


async def trigger_measurement(sample_name):
    """Orquesta un ciclo completo de medición manual (botón "Medir ahora" del cuadro Espectro):
    GetRemoteControlState (aborta si no es "Full") -> PrepareAnalysis -> Measure -> FinishAnalysis ->
    GetAnalysisResults. Cada paso se corre con asyncio.to_thread para no trabar el event loop.

    Devuelve (ok: bool, message: str, elements: dict)."""
    st = datos.load_ajuste_session()
    host = str(st.get("spectro_host", "") or "").strip()
    if not host:
        return False, "Espectrómetro: host no configurado.", {}
    commands_port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)

    try:
        mode = await asyncio.to_thread(spectro_client.get_remote_control_state, host, commands_port)
    except spectro_client.SpectroError as ex:
        return False, f"Espectrómetro: no se pudo consultar el control remoto ({ex}).", {}
    if mode != "Full":
        return False, (
            f'Espectrómetro: el control remoto está en modo "{mode or "desconocido"}" -- '
            "hace falta modo Full para medir a distancia."
        ), {}

    try:
        await asyncio.to_thread(spectro_client.prepare_analysis, host, sample_name, commands_port)
    except spectro_client.SpectroError as ex:
        return False, f"Espectrómetro: no se pudo preparar el análisis ({ex}).", {}

    try:
        result = await asyncio.to_thread(spectro_client.measure, host, commands_port, 60)
    except spectro_client.SpectroError as ex:
        return False, f"Espectrómetro: error al medir ({ex}).", {}

    if result["state"] in spectro_client.MEASURE_ERROR_STATES:
        return False, f"Espectrómetro: medición no completada ({result['state']}).", {}

    try:
        await asyncio.to_thread(spectro_client.finish_analysis, host, commands_port)
    except spectro_client.SpectroError as ex:
        return False, f"Espectrómetro: no se pudo finalizar el análisis ({ex}).", {}

    try:
        elements = await asyncio.to_thread(spectro_client.get_analysis_results, host, commands_port)
    except spectro_client.SpectroError as ex:
        return False, f"Espectrómetro: no se pudo traer el resultado ({ex}).", {}

    elements = {el: pct for el, pct in elements.items() if el not in ("C", "Si", "Fe")}
    if not elements:
        return False, "Espectrómetro: medición sin elementos utilizables.", {}

    source_label = f"Medición manual — {sample_name}" if sample_name else "Medición manual"
    st = datos.load_ajuste_session()  # releer: la medición tarda varios segundos, evitar pisar cambios concurrentes
    _append_recent_result(st, elements, source_label)
    datos.save_ajuste_session(st)

    from .ws import hub
    await hub.broadcast("ajuste", {
        "type": "spectro_result",
        "elements": elements,
        "source_name": source_label,
    })
    return True, f"Medición completada ({result['state']}).", elements


async def _poll_instrument_state(host, commands_port):
    global _last_remote_control_mode, _last_instrument_state
    try:
        state = await asyncio.to_thread(spectro_client.get_instrument_state, host, commands_port)
        mode = await asyncio.to_thread(spectro_client.get_remote_control_state, host, commands_port)
    except spectro_client.SpectroError as ex:
        print(f"[spectro_auto] error consultando estado del instrumento: {ex}", flush=True)
        return
    except Exception as ex:
        print(f"[spectro_auto] error inesperado consultando estado del instrumento: {ex}", flush=True)
        return
    _last_remote_control_mode = mode
    _last_instrument_state = state
    from .ws import hub
    await hub.broadcast("ajuste", {
        "type": "spectro_instrument_state",
        "state": state,
        "remote_control_mode": mode,
    })


def force_reconnect():
    """Botón "Forzar reconexión" de Opciones Spectro -- tira el listener actual, si hay uno, para que el
    próximo tick de _tick_once arme uno nuevo desde cero. También limpia spectro_measuring."""
    global _listener, _listener_key
    with _listener_lock:
        if _listener is not None:
            _listener.stop()
            _listener = None
            _listener_key = None
    _set_measuring_state(False)


async def _tick_once():
    """Un tick del reconciliador de conexión del cuadro Espectro. Se ocupa de cuatro cosas: 1) podar
    spectro_alerts vencidas; 2) destrabar spectro_measuring si quedó pegado más de _MEASURING_STALE_SECONDS;
    3) que el thread listener esté corriendo (o parado) según spectro_auto/spectro_host/puertos; 4) cada
    _INSTRUMENT_POLL_EVERY_N_TICKS consultar y publicar el estado del instrumento."""
    global _listener, _listener_key, _tick_count, _measuring_since
    st = datos.load_ajuste_session()

    if _prune_expired_alerts(st):
        datos.save_ajuste_session(st)
        from .ws import hub
        await hub.broadcast("ajuste", {"type": "spectro_alerts_pruned"})

    phase = st.get("spectro_measuring")
    if phase:
        if _measuring_since is None:
            _measuring_since = time.monotonic()
        elif (time.monotonic() - _measuring_since) > _MEASURING_STALE_SECONDS:
            print(f"[spectro_auto] spectro_measuring atascado en {phase!r} hace más de "
                  f"{_MEASURING_STALE_SECONDS}s sin evento terminal -- reseteando.", flush=True)
            _set_measuring_state(False)

    should_run = bool(st.get("spectro_auto"))
    host = str(st.get("spectro_host", "") or "").strip()
    events_port = int(to_float(st.get("spectro_events_port", 11001)) or 11001)
    commands_port = int(to_float(st.get("spectro_commands_port", 11000)) or 11000)

    with _listener_lock:
        if not should_run or not host:
            if _listener is not None:
                _listener.stop()
                _listener = None
                _listener_key = None
            return

        key = (host, events_port)
        if _listener is not None and _listener.is_alive() and _listener_key == key:
            _listener.commands_port = commands_port  # el puerto de comandos puede cambiar sin reiniciar el listener de eventos
        else:
            if _listener is not None:
                _listener.stop()
            _listener = spectro_client.SpectroEventsListener(
                host, port=events_port, on_event=_on_spectro_event, on_status=_on_spectro_status,
                on_connected=_on_spectro_connected,
            )
            _listener.commands_port = commands_port
            _listener.start()
            _listener_key = key

    _tick_count += 1
    listener = _listener
    if listener is not None and listener.is_alive() and _tick_count % _INSTRUMENT_POLL_EVERY_N_TICKS == 0:
        await _poll_instrument_state(listener.host, listener.commands_port)


async def spectro_auto_loop():
    """Tarea de fondo persistente -- arrancada una sola vez desde Modulo.al_iniciar. Nunca debería terminar
    sola; cualquier excepción de un tick se loguea y el loop sigue."""
    while True:
        try:
            await _tick_once()
        except Exception as ex:
            print(f"[spectro_auto] tick error: {ex}", flush=True)
        await asyncio.sleep(_TICK_SECONDS)
