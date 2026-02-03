# config.py
APP_TITLE = "Calculadora de Composición Química (Ajuste)"

ELEMENTS = [
    "C","Si","Mn","P","S","Cr","Mo","Ni","Al","Co","Cu","Nb","Ti","V","W",
    "Pb","Sn","Mg","As","Zr","Bi","Ce","Sb","Se","Te","B","Zn","La","Fe"
]

DATA_FILE  = "materiales.json"          # Catálogo (aleaciones y límites)
STATE_FILE = "ajuste_estado.json"       # Estado de trabajo (masa, actual, objetivo, kg, etc.)
HIST_FILE  = "ajustes_historicos.json"  # Historial persistente de coladas

COLOR_OK   = "#d6f5d6"
COLOR_FAIL = "#ffd6d6"
COLOR_WARN = "#fff3cd"
TOL_NO_LIMITS = 0.02

CATALOG_TYPES = ["Ferroaleación", "Metal puro", "Recorte", "Retorno", "Aditivo", "Aleación propia", "Otro"]
