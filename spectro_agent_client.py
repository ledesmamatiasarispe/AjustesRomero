# spectro_agent_client.py
"""
Cliente HTTP para el agente de teclado remoto del espectrometro LMX06
(spectro_key_agent.ps1). No confundir con spectro_client.py: ese habla la
Automation Interface oficial de SPECTRO (puerto 11000/11001), y con la
licencia "Limited" instalada aca no puede disparar "Measure" a distancia
(ver PROJECT_NOTES.md / memoria de sesion). Esto es la via alternativa:
un agente PowerShell que corre DENTRO de la sesion interactiva de user001
en 192.168.0.126 (unico lugar donde Windows deja que SendKeys llegue a la
ventana real de LMX06MeasurementGUI.exe -- una SSH exec_command comun cae
en la Sesion 0, sin acceso al escritorio) y que expone esas teclas como
un endpoint HTTP simple en la LAN.

El mapeo slug -> combinacion de teclas real (SendKeys) vive del lado del
agente (spectro_key_agent.ps1), no aca. Este modulo solo conoce que
comandos existen (para validar y para que host_api.py/la web tengan
etiqueta + agrupacion), y hace el POST.
"""

import json
import urllib.error
import urllib.request
from pathlib import Path

from config import SPECTRO_AGENT_HOST, SPECTRO_AGENT_PORT, SPECTRO_AGENT_TOKEN

TIMEOUT = 5

# Iconos reales del instrumento, recuperados de los recursos embebidos en
# LMX06MeasurementGUI.exe (no hay .ico sueltos en el disco -- ver
# PROJECT_NOTES.md). Un archivo web/icons/<slug>.png presente es lo que
# habilita el icono para ese comando; no todos los slugs tienen uno.
ICONS_DIR = Path(__file__).resolve().parent / "web" / "icons"

# slug -> (etiqueta, grupo, atajo mostrado). El orden de este dict define
# el orden en que se listan los botones en la web.
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
    COMANDOS, para que host_api.py se la pase tal cual a la web (unica
    fuente de verdad de que botones existen). `icono` es la URL servida
    por host_api.py (/icons/<slug>.png) si ese archivo existe, o None."""
    result = []
    for slug, (etiqueta, grupo, atajo) in COMANDOS.items():
        icono = f"/icons/{slug}.png" if (ICONS_DIR / f"{slug}.png").exists() else None
        result.append({"slug": slug, "etiqueta": etiqueta, "grupo": grupo, "atajo": atajo, "icono": icono})
    return result


def enviar_comando(slug, timeout=TIMEOUT):
    """Pide al agente remoto que mande la tecla de `slug` a la ventana de
    LMX06MeasurementGUI.exe. Devuelve el dict de respuesta del agente tal
    cual ({"ok": True, "sent": "..."} o {"ok": False, "error": "..."}).

    Levanta SpectroAgentError solo si no se pudo hablar con el agente en
    absoluto (timeout, conexion rechazada) -- un comando rechazado por el
    agente mismo (token invalido, ventana no encontrada) es un {"ok":
    False, ...} normal, no una excepcion.
    """
    if slug not in COMANDOS:
        raise SpectroAgentError(f"Comando desconocido: {slug}")
    url = f"http://{SPECTRO_AGENT_HOST}:{SPECTRO_AGENT_PORT}/key/{slug}?token={SPECTRO_AGENT_TOKEN}"
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


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    slug = sys.argv[1] if len(sys.argv) > 1 else "vista_por_defecto"
    print(f"Enviando '{slug}'...")
    try:
        print(enviar_comando(slug))
    except SpectroAgentError as ex:
        print(f"ERROR: {ex}")
