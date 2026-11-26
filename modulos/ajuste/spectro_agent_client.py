# spectro_agent_client.py
"""
Cliente HTTP para el agente de teclado remoto del espectrometro LMX06
(spectro_key_agent.ps1, ver la PC 192.168.0.126). NO existe equivalente en
la app de escritorio -- es funcionalidad nueva, no un puerto.

Por que existe, si ya esta spectro_client.py (Automation Interface oficial,
puerto 11000): con la licencia "Limited" instalada en esta planta, el
instrumento acepta todos los comandos de automatizacion EXCEPTO "Measure"
-- no se puede disparar una medicion a distancia por ese protocolo (ver
GetRemoteControlState en spectro_client.py / el boton "Medir ahora" del
cuadro Espectro, deshabilitado fuera del modo "Full"). Este modulo es la
via alternativa: un agente PowerShell que corre DENTRO de la sesion
interactiva de Windows en esa PC (unico lugar donde SendKeys llega a la
ventana real de LMX06MeasurementGUI.exe -- un SSH exec_command comun cae
en la Sesion 0, sin escritorio, y no ve la ventana) y expone esas teclas
como un endpoint HTTP simple en la LAN, puerto 8899. El mapeo
slug -> combinacion de teclas real vive del lado del agente, no aca --
este modulo solo conoce que comandos existen (para validar y para que la
web tenga etiqueta/grupo/atajo/icono) y hace el POST.

El host del agente es el MISMO host que spectro_host (misma PC), asi que
enviar_comando() lo recibe como parametro en vez de duplicar el campo de
configuracion -- el operario ya lo carga una sola vez en el cuadro
Espectro.
"""

import json
import os
import urllib.error
import urllib.request
from pathlib import Path

AGENT_PORT = 8899
# Token compartido con el agente (spectro_key_agent.ps1 / spectro_agent_announce.ps1 en la PC del espectrometro).
# NO va en el codigo: el repo es publico y con el token cualquiera en la LAN podria mandarle teclas al
# instrumento. Se lee de la variable de entorno ACOMP_SPECTRO_TOKEN o, si no esta, de spectro_agent_token.txt
# al lado de la base (data/, fuera del repo). Sin token: no se mandan comandos y no se acepta ningun anuncio.
TOKEN_ARCHIVO = "spectro_agent_token.txt"


def agent_token() -> str:
    token = os.environ.get("ACOMP_SPECTRO_TOKEN", "").strip()
    if token:
        return token
    from nucleo import db  # tarde: DB_PATH lo fija ajustes.configurar() al arrancar
    try:
        return (db.DB_PATH.parent / TOKEN_ARCHIVO).read_text(encoding="utf-8").strip()
    except OSError:
        return ""

TIMEOUT = 5

# Iconos reales del instrumento, recuperados de los recursos embebidos en
# LMX06MeasurementGUI.exe (no hay .ico sueltos en el disco). Un archivo
# frontend/img/espectro/<slug>.png presente es lo que habilita el icono
# para ese comando -- no todos los slugs tienen uno todavia.
ICONS_DIR = Path(__file__).resolve().parent / "frontend" / "img" / "espectro"

# slug -> (etiqueta, grupo, atajo mostrado). El orden de este dict define
# el orden en que se listan los botones en la web. Atajos leidos de la
# tabla "Customize toolbar" de Routine Measurement (LMX06MeasurementGUI).
COMANDOS = {
    "iniciar_medicion":           ("Iniciar medicion",         "Medicion", "F2"),
    "iniciar_medicion_multiple":  ("Medicion multiple",        "Medicion", "Shift+F2"),
    "repetir_ultima_medicion":    ("Repetir ultima medicion",  "Medicion", "Alt+F2"),
    "detener_medicion":           ("Detener medicion",         "Medicion", "F3"),
    "finalizar_muestra":          ("Finalizar muestra",        "Medicion", "F9"),
    "descartar_muestra":          ("Descartar muestra",        "Medicion", "Shift+D"),

    "id_muestra":                 ("ID de muestra",            "Muestra", "F5"),
    "siguiente_paso":             ("Siguiente paso",           "Muestra", "S"),
    "eliminar_restaurar":         ("Eliminar / Restaurar",     "Muestra", "D"),

    "ver_medicion_unica":         ("Vista medicion unica",     "Vistas", "F4"),
    "ver_valores_medios":         ("Ver valores medios",       "Vistas", "F6"),
    "ver_medios_rsd":             ("Ver medios y RSD",         "Vistas", "Shift+F6"),
    "vista_por_defecto":          ("Vista por defecto",        "Vistas", "Esc"),

    "cargar_metodo":              ("Cargar metodo",            "Metodo / Estandar", "F10"),
    "tipo_estandarizacion":       ("Tipo de estandarizacion",  "Metodo / Estandar", "Shift+F8"),
    "prueba_estandar_control":    ("Prueba estandar de control", "Metodo / Estandar", "F11"),
    "tipo_correccion":            ("Tipo de correccion",       "Metodo / Estandar", "F8"),
    "editar_estandarizacion":     ("Editar valores de estandarizacion", "Metodo / Estandar", "Ctrl+S"),
    "editar_pretarea":            ("Editar tiempos de pretarea", "Metodo / Estandar", "Ctrl+P"),

    "buscar_grado":                ("Buscar grado",             "Grado", "Ctrl+F"),
    "aplicar_grado":               ("Aplicar grado",            "Grado", "Ctrl+G"),
    "importar_grado":              ("Importar grado",           "Grado", "Alt+G"),

    "flush":                       ("Flush",                    "Flush", "F"),
    "detener_flush":               ("Detener Flush",            "Flush", "Shift+F"),

    "fijar_resultado":             ("Fijar resultado",          "Resultados fijados", "Alt+A"),
    "quitar_resultado_fijado":     ("Quitar resultado fijado",  "Resultados fijados", "Alt+D"),
    "quitar_todos_fijados":        ("Quitar todos los fijados", "Resultados fijados", "Ctrl+D"),
    "mostrar_ocultar_ids_fijados": ("Mostrar/ocultar IDs fijados", "Resultados fijados", "Alt+I"),

    "icalize":                     ("iCALize",                  "Otros", "F7"),
    "exportar":                    ("Exportar",                 "Otros", "Shift+S"),
    "imprimir":                    ("Imprimir",                 "Otros", "F12"),
    "control_remoto":              ("Modo control remoto",      "Otros", "Ctrl+R"),
    "ultimo_resultado":            ("Ultimo resultado",         "Otros", "Shift+L"),
    "aceptar":                     ("Aceptar",                  "Otros", "A"),
}


class SpectroAgentError(Exception):
    pass


def comandos_publicos():
    """Lista [{slug, etiqueta, grupo, atajo, icono}] en el orden de
    COMANDOS. `icono` es la URL estatica (/img/espectro/<slug>.png) si ese
    archivo existe, o None."""
    result = []
    for slug, (etiqueta, grupo, atajo) in COMANDOS.items():
        icono = f"/img/espectro/{slug}.png" if (ICONS_DIR / f"{slug}.png").exists() else None
        result.append({"slug": slug, "etiqueta": etiqueta, "grupo": grupo, "atajo": atajo, "icono": icono})
    return result


def enviar_comando(host, slug, timeout=TIMEOUT):
    """Pide al agente remoto (en `host`, mismo host que spectro_host) que
    mande la tecla de `slug` a la ventana de LMX06MeasurementGUI.exe.
    Devuelve el dict de respuesta del agente tal cual ({"ok": True,
    "sent": "..."} o {"ok": False, "error": "..."}).

    Levanta SpectroAgentError solo si no se pudo hablar con el agente en
    absoluto (timeout, conexion rechazada) -- un comando rechazado por el
    agente mismo (token invalido, ventana no encontrada) es un {"ok":
    False, ...} normal, no una excepcion. Sincronico a proposito (socket
    bloqueante): quien llama debe usar asyncio.to_thread, mismo criterio
    que spectro_client.send_command.
    """
    if slug not in COMANDOS:
        raise SpectroAgentError(f"Comando desconocido: {slug}")
    if not host:
        raise SpectroAgentError("Falta el host del espectrometro")
    token = agent_token()
    if not token:
        raise SpectroAgentError(f"Falta el token del agente (ACOMP_SPECTRO_TOKEN o data/{TOKEN_ARCHIVO})")
    url = f"http://{host}:{AGENT_PORT}/key/{slug}?token={token}"
    req = urllib.request.Request(url, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as ex:
        try:
            return json.loads(ex.read().decode("utf-8"))
        except Exception:
            return {"ok": False, "error": f"HTTP {ex.code}"}
    except Exception as ex:
        raise SpectroAgentError(f"No se pudo contactar el agente del espectrometro: {ex}") from ex
