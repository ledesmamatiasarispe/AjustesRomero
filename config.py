# config.py
APP_TITLE = "Calculadora de ComposiciÃ³n QuÃ­mica (Ajuste)"

# Tema visual
THEME = "dark"
BG = "#1e1e1e"
FG = "#e6e6e6"
BG_ENTRY = "#2b2b2b"
ACCENT = "#3a7bd5"

ELEMENTS = [
    "C","Si","Mn","P","S","Cr","Mo","Ni","Al","Co","Cu","Nb","Ti","V","W",
    "Pb","Sn","Mg","As","Zr","Bi","Ce","Sb","Se","Te","B","Zn","La","Fe"
]

DATA_FILE  = "materiales.json"          # CatÃ¡logo (aleaciones y lÃ­mites)
STATE_FILE = "ajuste_estado.json"       # Estado de trabajo (masa, actual, objetivo, kg, etc.)
HIST_FILE  = "ajustes_historicos.json"  # Historial persistente de coladas

COLOR_OK   = "#225c3b"
COLOR_FAIL = "#6b2b2b"
COLOR_WARN = "#6b5a2b"
TOL_NO_LIMITS = 0.02

CATALOG_TYPES = ["FerroaleaciÃ³n", "Metal puro", "Recorte", "Retorno", "Aditivo", "AleaciÃ³n propia", "Otro"]
