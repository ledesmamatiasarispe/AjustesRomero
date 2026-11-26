# spectro_client.py
"""
Cliente para el espectrometro SPECTRO LMX06 (Spark Analyzer Pro MAXx) via su
Automation Interface (AISAP): dos sockets TCP con telegramas XML -- Commands
Server (puerto 11000, request/response sincronico) y Events Server (puerto
11001, push de eventos). Protocolo documentado en
"Automation Interface LMX06.pdf" (SPECTRO Analytical Instruments GmbH).

Copiado tal cual desde ajuste_comp_nuevo/spectro_client.py -- es codigo puro
(sin Tkinter, solo socket/threading), ya pensado para poder llamarse desde
otro lado sin cambios. core/spectro_auto.py llama a estas funciones desde un
thread de fondo (ver ese archivo para como se integra con asyncio/WebSocket).

A diferencia de device_sync.py (Carbomax, HTTP+CGI, se sondea un indice
historico), este equipo empuja eventos por un socket persistente: no hace
falta indice ni deduplicacion por historial, cada evento
MeasurementCompleted/AnalysisFinished es el disparador directo de "hay un
resultado nuevo, andar a buscarlo" -- ver SpectroEventsListener.

Framing: el manual no documenta un length-prefix para los telegramas sobre
el socket crudo -- cada uno es un documento XML completo y autocontenido
('<?xml ...?><AutomationCommand ...>...</AutomationCommand>' o
AutomationEvent). _extract_telegrams() encuentra el/los telegrama(s)
completos que haya en el buffer acumulado buscando la tag de cierre que
corresponde a la primera tag de apertura, sin asumir ningun separador
extra -- soporta tanto telegramas partidos en varios recv() como varios
telegramas pegados en un mismo recv() (puede pasar en Events Server si se
completan dos mediciones casi juntas).

Uso como script independiente (valida framing + trae el ultimo resultado):
    python spectro_client.py [host]
"""

import re
import socket
import threading
import time
import xml.etree.ElementTree as ET

DEFAULT_COMMANDS_PORT = 11000
DEFAULT_EVENTS_PORT = 11001
COMMAND_TIMEOUT = 10        # segundos, por llamada de comando
EVENT_RECONNECT_DELAY = 5   # segundos entre reintentos de conexion al Events Server


class SpectroError(Exception):
    pass


# Hook opcional para que send_command() avise cada vez que confirma (True) o
# pierde (False) la conexion con el Commands Server -- registrado por
# core/spectro_auto.py (set_connectivity_hook), nunca importado directo aca
# para no crear un ciclo (spectro_auto ya importa este modulo). No hace
# falta un proceso de fondo aparte para saber si el instrumento responde:
# cada llamada real (el poll periodico de estado, o cualquier boton que el
# operador toque -- Probar, Medir ahora, Detener, Flush, etc.) ya intenta
# una conexion TCP nueva por si sola (ver send_command), asi que es la
# señal de "esta vivo" mas confiable que hay -- mas que un socket ya
# establecido del lado de Eventos, que no se entera si el otro lado se
# apaga de golpe sin mandar ni FIN ni RST.
_connectivity_hook = None


def set_connectivity_hook(fn):
    """fn(is_connected: bool) -- se llama desde send_command() en cada
    llamada, exitosa o no. Ver comentario arriba."""
    global _connectivity_hook
    _connectivity_hook = fn


def _notify_connectivity(is_connected):
    if callable(_connectivity_hook):
        try:
            _connectivity_hook(is_connected)
        except Exception:
            pass


# ---------- framing de telegramas ----------

_XML_DECL_RE = re.compile(rb"<\?xml[^>]*\?>\s*")
_ROOT_OPEN_RE = re.compile(rb"<([A-Za-z_][\w:.-]*)")


def _extract_telegrams(buf):
    """Extrae todos los telegramas XML completos presentes en buf (pueden
    venir varios pegados en un mismo recv()). Cada telegrama es un
    documento propio '<?xml...?><Root ...>...</Root>'. No asume ningun
    separador entre telegramas mas alla del cierre de la tag raiz.

    Devuelve (lista_de_telegramas_bytes, resto_sin_consumir_todavia).
    """
    telegrams = []
    pos = 0
    n = len(buf)
    while True:
        while pos < n and buf[pos:pos + 1].isspace():
            pos += 1
        if pos >= n:
            break
        decl = _XML_DECL_RE.match(buf, pos)
        search_from = decl.end() if decl else pos
        root_match = _ROOT_OPEN_RE.match(buf, search_from)
        if not root_match:
            break  # todavia no llego ni la tag de apertura
        tag = root_match.group(1)
        close = b"</" + tag + b">"
        end = buf.find(close, root_match.end())
        if end == -1:
            break  # telegrama incompleto, falta mas data
        end += len(close)
        telegrams.append(buf[pos:end])
        pos = end
    return telegrams, buf[pos:]


def _read_one_telegram(sock, timeout=COMMAND_TIMEOUT):
    """Lee del socket hasta juntar un telegrama completo (ver
    _extract_telegrams) y devuelve el Element raiz ya parseado."""
    sock.settimeout(timeout)
    buf = b""
    deadline = time.monotonic() + timeout
    while True:
        try:
            chunk = sock.recv(65536)
        except socket.timeout:
            raise SpectroError(f"Timeout esperando respuesta ({timeout}s)")
        if not chunk:
            raise SpectroError("Conexion cerrada por el instrumento sin telegrama completo")
        buf += chunk
        telegrams, _ = _extract_telegrams(buf)
        if telegrams:
            return ET.fromstring(telegrams[0])
        if time.monotonic() > deadline:
            raise SpectroError(f"Timeout juntando telegrama XML ({timeout}s), buffer={buf[:200]!r}")


# ---------- comandos (Commands Server, puerto 11000) ----------

def send_command(host, name, para_xml="", port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Manda un AutomationCommand y devuelve el Element <Return> de la
    respuesta (o None si el comando no trae Return). Conexion nueva por
    llamada -- no se mantiene un socket de comandos persistente, mismo
    criterio que _http_get en device_sync.py para Carbomax.

    Levanta SpectroError si TranslationStatus/CmdStatus no son "OK".
    """
    telegram = (
        '<?xml version="1.0" encoding="utf-8"?>'
        f'<AutomationCommand Name="{name}" Direction="Server">'
        f"<Para>{para_xml}</Para>"
        "</AutomationCommand>"
    )
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            sock.sendall(telegram.encode("utf-8"))
            root = _read_one_telegram(sock, timeout=timeout)
    except Exception:
        # Nunca llegamos a tener una respuesta bien formada -- sin
        # importar si fue un error de socket (host apagado/inalcanzable)
        # o de framing, eso ya prueba que no hay conexion util ahora
        # mismo. Se re-lanza tal cual: esto solo agrega el aviso, no
        # cambia que excepcion ve el llamador.
        _notify_connectivity(False)
        raise
    # Llegar hasta aca -- telegrama mandado, respuesta XML bien formada
    # recibida -- ya prueba que el Commands Server esta vivo y responde,
    # sin importar lo que diga TranslationStatus/CmdStatus mas abajo (eso
    # es un rechazo de NEGOCIO -- ej. StartFlush con Argon en mal estado
    # -- no una desconexion, y no debe mostrarse como tal).
    _notify_connectivity(True)

    translation = root.get("TranslationStatus", "")
    cmd_status = root.get("CmdStatus", "")
    if translation and translation != "OK":
        raise SpectroError(f"{name}: TranslationStatus={translation}")
    if cmd_status and cmd_status != "OK":
        err = (root.findtext("ErrorText") or "").strip()
        raise SpectroError(f"{name}: CmdStatus={cmd_status} {err}".strip())
    return root.find("Return")


def get_software_version(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    ret = send_command(host, "GetSoftwareVersion", port=port, timeout=timeout)
    if ret is None:
        return ""
    return (ret.findtext(".//SoftwareVersion") or "").strip()


def get_current_login_name(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    ret = send_command(host, "GetCurrentLogInName", port=port, timeout=timeout)
    if ret is None:
        return ""
    return (ret.findtext(".//LoginName") or "").strip()


def get_analysis_results(host, port=DEFAULT_COMMANDS_PORT, results_type="LastSingle",
                          values_type="Elements", timeout=COMMAND_TIMEOUT):
    """Pide GetAnalysisResults y devuelve {ElementName: pct} de TODOS los
    elementos del ultimo analisis, tal cual los reporta el instrumento.

    Nota importante: esta funcion NO filtra nada -- en particular no saca
    "C"/"Si" aunque el instrumento no sea confiable para esos dos (ver
    PROJECT_NOTES.md / plan de integracion). Ese filtro es responsabilidad
    exclusiva de quien llama (core/spectro_auto.py del lado web,
    tab_ajuste._run_spectro_auto del lado escritorio), para que este
    modulo quede agnostico de esa regla de negocio y reutilizable tal cual
    si algun dia se necesita el analisis completo para otra cosa (ej. un
    reporte de calidad).
    """
    para = (
        "<SampleResultsDescriptor>"
        f"<SampleResultsType>{results_type}</SampleResultsType>"
        f"<SampleResultsValuesType>{values_type}</SampleResultsValuesType>"
        "</SampleResultsDescriptor>"
    )
    ret = send_command(host, "GetAnalysisResults", para_xml=para, port=port, timeout=timeout)
    if ret is None:
        return {}
    elements = {}
    # Elements NO cuelga directo de SampleResult -- esta bajo
    # MeasurementReplicates/MeasurementReplicate/Measurement/Elements (uno
    # por replica). Con SampleResultsType="LastSingle" hay una sola
    # MeasurementReplicate. Ojo: SampleResult tambien tiene un
    # MeasurementStatistics/Measurement/Elements aparte (solo poblado para
    # "Average") -- no usar ".//Elements/Element" generico o se mezclan/
    # duplican ambos bloques.
    path = ".//SampleResult/MeasurementReplicates/MeasurementReplicate/Measurement/Elements/Element"
    for el in ret.findall(path):
        name = (el.get("ElementName") or "").strip()
        if not name:
            continue
        conc = el.find('ElementResult[@Type="Conc"]')
        if conc is None:
            conc = el.find("ElementResult")  # fallback si no hay uno "Conc" exacto
        if conc is None:
            continue
        raw = conc.findtext("ResultValue")
        try:
            value = float(raw)
        except (TypeError, ValueError):
            continue
        # "Limpieza" del resultado (pedido del usuario, 24/08/2026): cerca
        # del limite de deteccion el instrumento puede devolver trazas
        # negativas por ruido de la resta de fondo (ej. Sb/Se/Te en
        # -0.007%) -- no tiene sentido fisico una concentracion negativa,
        # se lleva a 0. Los ~15 decimales que manda el instrumento tambien
        # son falsa precision (muy por debajo de la repetibilidad real del
        # metodo), se redondea aca, en el origen, para que todo lo que
        # consuma este dict (spectro_recent_results, "usar en Actual",
        # etc.) ya reciba el valor limpio sin repetir la cuenta.
        # 3 decimales, no 2 (ajustado 18/11/2026, pedido del usuario): a 2
        # decimales un trazo real de 0.009% (ya es un dato, ver el
        # historial de arsenico) redondeaba a 0.00 igual que un 0.0009%
        # genuinamente despreciable -- los dos quedaban indistinguibles.
        elements[name] = round(max(0.0, value), 3)
    return elements


# ---------- control del instrumento (cuadro "Espectro" manual) ----------
# Agregado para el panel de control manual en ajuste_comp_web (ver
# core/spectro_auto.py::trigger_measurement) -- deliberadamente solo cubre
# el flujo de muestra "Unknown" (produccion normal), un replicate por
# medicion, sin ICal/Control/TypeStd. Mismo estilo que send_command/
# get_analysis_results de arriba.

def get_remote_control_state(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Devuelve "Full"/"Limited"/"Off". En "Limited" el instrumento acepta
    todos los comandos EXCEPTO Measure -- hay que chequear esto antes de
    ofrecer el boton de medir, no alcanza con que Measure falle prolijo."""
    ret = send_command(host, "GetRemoteControlState", port=port, timeout=timeout)
    if ret is None:
        return ""
    return (ret.findtext(".//RemoteControlMode") or "").strip()


def get_instrument_state(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Devuelve {PropertyName: PropertyValue} de TODAS las propiedades que
    mande InstrumentStateDescriptor, sin whitelist -- el llamador elige que
    mostrar. Los nombres varian segun que hardware tenga el instrumento
    (ver manual: InstrumentOk, ArgonState, PlasmaGeneratorState, etc.)."""
    ret = send_command(host, "GetInstrumentState", port=port, timeout=timeout)
    if ret is None:
        return {}
    desc = ret.find(".//InstrumentStateDescriptor")
    if desc is None:
        return {}
    return {child.tag: (child.text or "").strip() for child in desc}


def _method_descriptor_xml(excitation_type, base_element, method_name):
    return (
        "<MethodDescriptor>"
        f"<ExcitationType>{excitation_type}</ExcitationType>"
        f"<BaseElement>{base_element}</BaseElement>"
        f"<MethodName>{method_name}</MethodName>"
        "</MethodDescriptor>"
    )


def _parse_method_descriptors(ret):
    out = []
    for md in ret.findall(".//MethodDescriptor"):
        out.append({
            "excitation_type": (md.findtext("ExcitationType") or "").strip(),
            "base_element": (md.findtext("BaseElement") or "").strip(),
            "method_name": (md.findtext("MethodName") or "").strip(),
        })
    return out


def _parse_ical_standards(ret):
    out = []
    for it in ret.findall(".//ICalStandardDescriptor"):
        out.append({
            "name": (it.findtext("ICalStandardName") or "").strip(),
            "min_measurements": (it.findtext("MinMeasurementsCount") or "").strip(),
        })
    return out


def get_method_names(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    ret = send_command(host, "GetMethodNames", port=port, timeout=timeout)
    return _parse_method_descriptors(ret) if ret is not None else []


def get_current_method_name(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    ret = send_command(host, "GetCurrentMethodName", port=port, timeout=timeout)
    if ret is None:
        return {}
    methods = _parse_method_descriptors(ret)
    return methods[0] if methods else {}


def select_method(host, excitation_type, base_element, method_name,
                   port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Activa el metodo indicado. Devuelve la lista de ICalStandardDescriptors
    pendientes (vacia si no hace falta calibrar) -- el llamador decide si
    solo avisar (este panel no automatiza la calibracion ICal)."""
    para = _method_descriptor_xml(excitation_type, base_element, method_name)
    ret = send_command(host, "SelectMethod", para_xml=para, port=port, timeout=timeout)
    return _parse_ical_standards(ret) if ret is not None else []


def _parse_profile_descriptors(ret):
    out = []
    for pd in ret.findall(".//ProfileDescriptor"):
        out.append({
            "profile_name": (pd.findtext("ProfileName") or "").strip(),
            "profile_type": (pd.findtext("ProfileType") or "").strip(),
            "description": (pd.findtext("ProfileDescription") or "").strip(),
        })
    return out


def get_profile_names(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    ret = send_command(host, "GetProfileNames", port=port, timeout=timeout)
    return _parse_profile_descriptors(ret) if ret is not None else []


def get_current_profile_name(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    ret = send_command(host, "GetCurrentProfileName", port=port, timeout=timeout)
    if ret is None:
        return {}
    profiles = _parse_profile_descriptors(ret)
    return profiles[0] if profiles else {}


def select_profile(host, profile_name, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Activa el perfil indicado. Devuelve ICalStandardDescriptors pendientes,
    mismo criterio que select_method."""
    para = f"<ProfileDescriptor><ProfileName>{profile_name}</ProfileName></ProfileDescriptor>"
    ret = send_command(host, "SelectProfile", para_xml=para, port=port, timeout=timeout)
    return _parse_ical_standards(ret) if ret is not None else []


def get_analysis_id_format(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Devuelve los campos de identificacion de muestra que ESTE
    instrumento tiene configurados (varia por instalacion -- no asumir
    "Sample Name" como el nombre de fabrica, cada planta puede renombrarlo
    o agregar campos propios). Cada item: {id_name, type, is_sample_name}.
    El campo con is_sample_name=True es el que identifica unívocamente la
    muestra -- en esta planta es literalmente "Numero de Colada", no
    "Sample Name" (confirmado 24/08/2026 contra el instrumento real)."""
    ret = send_command(host, "GetAnalysisIDFormat", port=port, timeout=timeout)
    if ret is None:
        return []
    out = []
    for sid in ret.findall(".//AnalysisID/SampleID"):
        out.append({
            "id_name": (sid.findtext("IDName") or "").strip(),
            "type": sid.get("Type", ""),
            "is_sample_name": sid.get("IsSampleName", "") == "True",
        })
    return out


def prepare_analysis(host, sample_value, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Prepara un analisis de muestra "desconocida" (produccion normal,
    AnalyticalMode=UnknownMeas). NO cubre Control/TypeStd/ICal -- fuera de
    alcance del panel manual (ver core/spectro_auto.py::trigger_measurement).

    sample_value se carga en el campo que ESTE instrumento tenga
    configurado como identificador único de la muestra (SampleID con
    IsSampleName="True", consultado en vivo via get_analysis_id_format --
    el IDName real varia por instalacion, no se asume "Sample Name"). Si
    la consulta falla o ningun campo esta marcado como identificador,
    cae a IDName="Sample Name" como fallback razonable para no dejar el
    analisis sin preparar."""
    id_name = "Sample Name"
    try:
        fields = get_analysis_id_format(host, port=port, timeout=timeout)
        sample_field = next((f for f in fields if f.get("is_sample_name")), None)
        if sample_field and sample_field.get("id_name"):
            id_name = sample_field["id_name"]
    except SpectroError:
        pass
    para = (
        "<AnalysisDescriptor>"
        "<AnalyticalMode>UnknownMeas</AnalyticalMode>"
        "<AnalysisID>"
        '<SampleID Type="Text">'
        f"<IDName>{id_name}</IDName>"
        f"<IDValue>{sample_value}</IDValue>"
        "</SampleID>"
        "</AnalysisID>"
        "</AnalysisDescriptor>"
    )
    send_command(host, "PrepareAnalysis", para_xml=para, port=port, timeout=timeout)


def measure(host, port=DEFAULT_COMMANDS_PORT, timeout=60):
    """Dispara una medicion (la chispa real) y espera a que termine --
    timeout mas largo que el default de comandos porque una medicion real
    tarda varios segundos. Devuelve {"state": measurementCompletionState,
    "index": measurementIndex}."""
    ret = send_command(host, "Measure", port=port, timeout=timeout)
    if ret is None:
        return {"state": "", "index": ""}
    desc = ret.find(".//MeasurementCompletionDescriptor")
    if desc is None:
        return {"state": "", "index": ""}
    return {
        "state": (desc.findtext("MeasurementCompletionState") or "").strip(),
        "index": (desc.findtext("MeasurementIndex") or "").strip(),
    }


# Estados de Measure que indican que la medicion NO se completo bien --
# no tiene sentido llamar a FinishAnalysis despues de ninguno de estos
# (ver manual, seccion 8.26.3).
MEASURE_ERROR_STATES = ("StartTimeout", "RunTimeout", "Aborted", "ReferenceError")


def finish_analysis(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Completa y documenta el analisis (imprime/exporta segun el perfil
    activo, ver manual seccion 8.3) -- llamar SOLO si measure() no devolvio
    un estado de MEASURE_ERROR_STATES."""
    send_command(host, "FinishAnalysis", port=port, timeout=timeout)


def discard_analysis(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Descarta el analisis en curso sin documentarlo."""
    send_command(host, "DiscardAnalysis", port=port, timeout=timeout)


def start_flush(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Arranca el flush (argon o aire purificado, manual 8.32) -- sin
    parametros, el instrumento elige el gas segun como este configurado."""
    send_command(host, "StartFlush", port=port, timeout=timeout)


def stop_flush(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Para el flush en curso (manual 8.33)."""
    send_command(host, "StopFlush", port=port, timeout=timeout)


def stop_measure(host, port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Corta una medicion en curso (manual 8.34). Sin Para, sin Return --
    si no hay nada midiendo en ese momento, no hace nada.

    Es el UNICO comando del protocolo pensado para usarse asincronicamente
    (el manual lo aclara explicito): mientras measure() esta bloqueado en
    SU propia conexion esperando el resultado, esto necesita abrir una
    conexion NUEVA para interrumpirla desde afuera -- que es exactamente
    lo que ya hace send_command() en cada llamada (una conexion nueva por
    comando, ver cabecera del archivo), asi que no hace falta nada
    especial de este lado."""
    send_command(host, "StopMeasure", port=port, timeout=timeout)


def finish_operator_interaction(host, interaction_name, selected_option=None,
                                 port=DEFAULT_COMMANDS_PORT, timeout=COMMAND_TIMEOUT):
    """Responde una interaccion pendiente que llego como evento
    OperatorInteractionNeeded (ver SpectroEventsListener /
    core/spectro_auto.py::_on_spectro_alert_event) -- contraparte de ese
    evento, manual seccion 8.4. selected_option es una de las
    InteractionOptions que trajo el evento (ej. "Yes"/"No"/"Done"); varias
    interacciones no tienen opciones y solo piden confirmar, ahi va None.
    Como resultado el instrumento empuja OperatorInteractionFinished (no
    escuchado aca -- la interaccion simplemente deja de estar pendiente)."""
    para = f"<OperatorInteractionDescriptor><InteractionName>{interaction_name}</InteractionName>"
    if selected_option:
        para += f"<SelectedInteractionOption>{selected_option}</SelectedInteractionOption>"
    para += "</OperatorInteractionDescriptor>"
    send_command(host, "FinishOperatorInteraction", para_xml=para, port=port, timeout=timeout)


# ---------- eventos (Events Server, puerto 11001) ----------

class SpectroEventsListener(threading.Thread):
    """Escucha el Events Server en un thread aparte y llama a
    on_event(name, xml_element) por cada AutomationEvent relevante:
    MeasurementCompleted/AnalysisFinished (hay resultado nuevo),
    ProcessError/ProcessInformation/OperatorInteractionNeeded (el
    instrumento muestra un dialogo en su propia pantalla -- error, aviso,
    o algo que necesita que alguien confirme/rechace ahi mismo), y
    OperatorInteractionFinished (esa interaccion se resolvio -- via
    FinishOperatorInteraction o parado frente al instrumento, el evento
    llega igual en los dos casos, es la unica forma de que el cuadro
    Espectro sepa que una alerta ya no esta pendiente si se resolvio
    fisicamente), InstrumentStateChanged (el instrumento empuja su
    InstrumentStateDescriptor completo cada vez que cambia algo -- mismo
    shape que GetInstrumentState), RemoteControlChanged (idem pero para
    el modo Limited/Full/Off) -- las dos ultimas reemplazan la espera de
    hasta ~10s del poll periodico por algo instantaneo -- y
    MeasurementStarted/MeasurementBroken (badge "Midiendo..." en vivo y
    aviso si una medicion se corta a medias). El resto de los ~20 eventos
    documentados se ignora.

    Reconecta con backoff si se corta la conexion: eso pasa en el uso
    normal cada vez que LMX06MeasurementGUI.exe esta cerrado (el
    Commands/Events Server vive DENTRO del proceso de la GUI, no como
    servicio de Windows aparte -- confirmado 24/08/2026), asi que no es un
    error a mostrar en rojo, solo el estado normal fuera de medicion.

    on_event/on_status pueden llegar desde este thread -- quien los
    implemente es responsable de volver de forma segura al runtime que
    corresponda (self.after(0, ...) en Tkinter, hub.broadcast_threadsafe()
    en el backend web), esta clase no lo hace por si sola.
    """

    RELEVANT_EVENTS = (
        "MeasurementCompleted", "AnalysisFinished",
        "ProcessError", "ProcessInformation",
        "OperatorInteractionNeeded", "OperatorInteractionFinished",
        "InstrumentStateChanged", "RemoteControlChanged",
        "MeasurementStarted", "MeasurementFinished", "MeasurementBroken",
    )

    def __init__(self, host, port=DEFAULT_EVENTS_PORT, on_event=None, on_status=None,
                 on_connected=None, reconnect_delay=EVENT_RECONNECT_DELAY):
        super().__init__(daemon=True, name="spectro-events-listener")
        self.host = host
        self.port = port
        self.on_event = on_event
        self.on_status = on_status
        self.on_connected = on_connected
        self.reconnect_delay = reconnect_delay
        self._stop_flag = threading.Event()
        # Distinto de is_alive() (que solo dice si el THREAD python sigue
        # corriendo, cosa que es cierta todo el rato que este reintentando
        # conectar) -- esto es si el socket TCP con el Events Server esta
        # de verdad abierto ahora mismo. Confirmado como bug real: con la
        # PC del Spectro apagada, is_alive() da True indefinidamente (el
        # thread sigue vivo, solo reintentando) y no habia ninguna otra
        # senal de que la conexion se haya perdido.
        self.connected = False

    def stop(self):
        self._stop_flag.set()
        self._set_connected(False)

    def _status(self, msg):
        if callable(self.on_status):
            try:
                self.on_status(msg)
            except Exception:
                pass

    def _set_connected(self, value):
        if self.connected == value:
            return
        self.connected = value
        if callable(self.on_connected):
            try:
                self.on_connected(value)
            except Exception:
                pass

    def run(self):
        while not self._stop_flag.is_set():
            try:
                self._listen_once()
            except Exception as ex:
                self._status(f"Espectrometro: sin conexion ({ex}), reintentando...")
            finally:
                self._set_connected(False)
            if self._stop_flag.is_set():
                return
            self._stop_flag.wait(self.reconnect_delay)

    def _listen_once(self):
        with socket.create_connection((self.host, self.port), timeout=self.reconnect_delay) as sock:
            self._status("Espectrometro: conectado al Events Server.")
            self._set_connected(True)
            sock.settimeout(1.0)
            buf = b""
            while not self._stop_flag.is_set():
                try:
                    chunk = sock.recv(65536)
                except socket.timeout:
                    continue
                if not chunk:
                    raise SpectroError("Events Server cerro la conexion")
                buf += chunk
                telegrams, buf = _extract_telegrams(buf)
                for raw in telegrams:
                    self._handle_telegram(raw)

    def _handle_telegram(self, raw):
        try:
            root = ET.fromstring(raw)
        except ET.ParseError:
            return
        name = root.get("Name", "")
        if name in self.RELEVANT_EVENTS and callable(self.on_event):
            try:
                self.on_event(name, root)
            except Exception:
                pass


# ---------- ejecucion directa (script independiente) ----------

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    host = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.126"

    print(f"Conectando a {host}:{DEFAULT_COMMANDS_PORT} (Commands Server)...")
    try:
        version = get_software_version(host)
        print(f"  Version software: {version or '(vacio)'}")
    except SpectroError as ex:
        print(f"  ERROR GetSoftwareVersion: {ex}")

    try:
        login = get_current_login_name(host)
        print(f"  Usuario logueado: {login or '(vacio)'}")
    except SpectroError as ex:
        print(f"  ERROR GetCurrentLogInName: {ex}")

    print("\nPidiendo GetAnalysisResults (LastSingle)...")
    try:
        elements = get_analysis_results(host)
        if elements:
            print("Elementos del ultimo analisis:")
            for el, pct in sorted(elements.items()):
                marca = "  (ignorado por la app: no confiable via espectro)" if el in ("C", "Si") else ""
                print(f"  {el}: {pct}%{marca}")
        else:
            print("Sin resultados (¿no se corrio ningun analisis todavia en esta sesion del instrumento?)")
    except SpectroError as ex:
        print(f"ERROR GetAnalysisResults: {ex}")
