# spectro_client.py
"""
Cliente para el espectrometro SPECTRO LMX06 (Spark Analyzer Pro MAXx) via su
Automation Interface (AISAP): dos sockets TCP con telegramas XML -- Commands
Server (puerto 11000, request/response sincronico) y Events Server (puerto
11001, push de eventos). Protocolo documentado en
"Automation Interface LMX06.pdf" (SPECTRO Analytical Instruments GmbH).

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
    with socket.create_connection((host, port), timeout=timeout) as sock:
        sock.sendall(telegram.encode("utf-8"))
        root = _read_one_telegram(sock, timeout=timeout)

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
    exclusiva de quien llama (tab_ajuste._run_spectro_auto), para que este
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
            elements[name] = float(raw)
        except (TypeError, ValueError):
            continue
    return elements


# ---------- eventos (Events Server, puerto 11001) ----------

class SpectroEventsListener(threading.Thread):
    """Escucha el Events Server en un thread aparte y llama a
    on_event(name, xml_element) por cada AutomationEvent relevante
    (MeasurementCompleted / AnalysisFinished -- el resto se ignora).

    Reconecta con backoff si se corta la conexion: eso pasa en el uso
    normal cada vez que LMX06MeasurementGUI.exe esta cerrado (el
    Commands/Events Server vive DENTRO del proceso de la GUI, no como
    servicio de Windows aparte -- confirmado 24/08/2026), asi que no es un
    error a mostrar en rojo, solo el estado normal fuera de medicion.

    on_event/on_status pueden llegar desde este thread -- quien los
    implemente (tab_ajuste.py) es responsable de marshallar cualquier
    toque a la UI de Tk via self.after(0, ...), esta clase no lo hace por
    si sola.
    """

    RELEVANT_EVENTS = ("MeasurementCompleted", "AnalysisFinished")

    def __init__(self, host, port=DEFAULT_EVENTS_PORT, on_event=None, on_status=None,
                 reconnect_delay=EVENT_RECONNECT_DELAY):
        super().__init__(daemon=True, name="spectro-events-listener")
        self.host = host
        self.port = port
        self.on_event = on_event
        self.on_status = on_status
        self.reconnect_delay = reconnect_delay
        self._stop_flag = threading.Event()

    def stop(self):
        self._stop_flag.set()

    def _status(self, msg):
        if callable(self.on_status):
            try:
                self.on_status(msg)
            except Exception:
                pass

    def run(self):
        while not self._stop_flag.is_set():
            try:
                self._listen_once()
            except Exception as ex:
                self._status(f"Espectrometro: sin conexion ({ex}), reintentando...")
            if self._stop_flag.is_set():
                return
            self._stop_flag.wait(self.reconnect_delay)

    def _listen_once(self):
        with socket.create_connection((self.host, self.port), timeout=self.reconnect_delay) as sock:
            self._status("Espectrometro: conectado al Events Server.")
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
