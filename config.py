# config.py
# Constantes compartidas por toda la app: tema visual, lista de elementos
# quimicos soportados y colores de estado. No hay logica aca, solo valores.

# Tema visual (unico tema soportado hoy; "THEME" no se usa para elegir entre
# varios, es documentacion de que estos colores son el tema oscuro).
THEME = "dark"
BG = "#1e1e1e"
FG = "#e6e6e6"
BG_ENTRY = "#2b2b2b"
ACCENT = "#3a7bd5"

# Elementos quimicos que la app conoce (composicion de aleaciones, catalogo,
# calculo de ajuste, etc). El ORDEN de esta lista define el orden en que se
# muestran las filas/columnas de composicion en toda la UI (Ajuste, Catalogo,
# Historicos, Calidad) - agregar un elemento nuevo al final no reordena nada,
# pero insertarlo en el medio cambia el orden visual en todas las tablas.
ELEMENTS = [
    "C","Si","Mn","P","S","Cr","Mo","Ni","Al","Co","Cu","Nb","Ti","V","W",
    "Pb","Sn","Mg","As","Zr","Bi","Ce","Sb","Se","Te","B","Zn","La","Fe"
]

# Colores de estado (dentro/fuera de rango, advertencia) usados en tablas de
# composicion para pintar celdas segun si el valor esta OK, fuera de limite,
# o en zona de advertencia.
COLOR_OK   = "#225c3b"
COLOR_FAIL = "#6b2b2b"
COLOR_WARN = "#6b5a2b"
# Tolerancia usada al colorear una celda como "OK" cuando el material no
# tiene limites (soft_min/soft_max) configurados en el catalogo.
TOL_NO_LIMITS = 0.02

# Agente de teclado remoto del espectrometro LMX06 (spectro_key_agent.ps1,
# corriendo en la sesion interactiva de user001 en 192.168.0.126 -- unico
# lugar donde SendKeys llega a la ventana real de LMX06MeasurementGUI.exe,
# ver spectro_agent_client.py). Distinto de DEFAULT_COMMANDS_PORT/EVENTS_PORT
# en spectro_client.py, que hablan la Automation Interface oficial.
SPECTRO_AGENT_HOST = "192.168.0.126"
SPECTRO_AGENT_PORT = 8899
SPECTRO_AGENT_TOKEN = __import__("os").environ.get("SPECTRO_AGENT_TOKEN", "")  # fuera del repo (es público)

# CARBOMAX DELTA por RS485/Modbus RTU Slave (adaptador USB-serie local,
# distinto de la interfaz de red CGI que ya emula carbomax_emulator.py).
# Direccion de esclavo, puerto COM y baudrate confirmados en el equipo real
# el 10/09/2026 -- ver carbomax_modbus_client.py.
CARBOMAX_MODBUS_PORT = "COM3"
CARBOMAX_MODBUS_BAUDRATE = 57600
CARBOMAX_MODBUS_SLAVE_ID = 1
