# utils.py -- puerto sin cambios de backend/core/utils.py de ajuste_comp_web. Helpers numericos y de simulacion
# de composicion, compartidos por practicamente todos los dominios (Ajuste, Catalogo, Historicos, Calidad,
# Analisis termico). Funciones puras, sin dependencias.

def to_float(s):
    """Convierte a float en forma "tolerante": acepta coma decimal y nunca tira excepcion. Si el valor esta
    vacio o no es numero, devuelve 0.0.

    OJO: ese 0.0 silencioso puede esconder un dato mal cargado (ej. un campo con texto en vez de numero se lee
    como "cero" en vez de avisar el error). Para casos donde hay que distinguir "vacio" de "cero real", usar
    to_float_or_none."""
    if s is None: return 0.0
    s = str(s).strip().replace(",", ".")
    if not s: return 0.0
    try: return float(s)
    except: return 0.0

def to_float_or_none(s):
    """Igual que to_float, pero devuelve None (en vez de 0.0) cuando el valor esta vacio o no se puede
    parsear, para poder distinguir "sin dato" de "cero"."""
    if s is None: return None
    s = str(s).strip().replace(",", ".")
    if s == "": return None
    try: return float(s)
    except: return None

def fmt(x, nd=6):
    """Formatea un numero con hasta `nd` decimales, recortando ceros y el punto decimal sobrantes (ej.
    3.500000 -> "3.5", 3.000000 -> "3")."""
    if nd <= 0:
        return f"{x:.0f}"
    s = f"{x:.{nd}f}".rstrip("0").rstrip(".")
    return s or "0"

def fmt_opt(x, nd=6):
    """Como fmt(), pero para valores opcionales: None se muestra como cadena vacia en vez de "0"."""
    return "" if x is None else fmt(float(x), nd)

def _norm(s):
    """Normaliza texto para comparaciones insensibles a mayusculas/acentos (ej. nombres de formula de CE). Solo
    cubre vocales mayusculas con tilde (Ó, Í, Á, É, Ú) - no toca Ñ ni vocales en minuscula, porque quien la usa
    siempre le pasa el texto ya en mayusculas."""
    if not s: return ""
    return (s.upper()
              .replace("Ó","O").replace("Í","I")
              .replace("Á","A").replace("É","E").replace("Ú","U"))


def simulate_staged(comp0, stage_specs, elements, get_alloy, effective_add, effective_total_perkg):
    """Simula la inoculación por etapas secuenciales.

    stage_specs: iterable de (mass_kg, [(nombre, kg), ...]).
    Cada etapa aplica sus inoculantes a mass_kg kg de metal con la composición resultante de la etapa anterior.
    Devuelve la composición final (%)."""
    comp = {e: to_float(comp0.get(e, 0.0)) for e in elements}
    for mass_kg, items in stage_specs:
        if not items or mass_kg <= 0:
            continue
        # Masa de cada elemento presente en esta etapa, antes de inocular.
        masses = {e: mass_kg * comp.get(e, 0.0) / 100.0 for e in elements}
        add_eff = 0.0
        for name, kg in items:
            a = get_alloy(name)
            if not a:
                continue
            eff = effective_add(a, kg)
            for e in elements:
                masses[e] += eff[e]
            add_eff += kg * effective_total_perkg(a)
        M_new = mass_kg + add_eff
        if M_new > 0:
            # La composicion resultante de esta etapa es la base de la siguiente etapa (por eso el loop
            # reasigna "comp").
            comp = {e: 100.0 * masses[e] / M_new for e in elements}
    return comp


def simulate_with_plan(M0, comp0, plan, elements, get_alloy, effective_add, effective_total_perkg):
    """Aplica un plan de ajuste {material: kg} de una sola vez sobre una masa M0 con composicion comp0, y
    devuelve (masa_final, composicion_final_%). Es la funcion central que usan Ajuste/Historicos para predecir
    el resultado de un ajuste antes (o en vez) de aplicarlo de verdad."""
    masses = {e: M0 * to_float(comp0.get(e, 0.0)) / 100.0 for e in elements}
    add_total_eff = 0.0
    for name, kg in (plan or {}).items():
        if kg <= 0:
            continue
        a = get_alloy(name)
        if not a:
            raise ValueError(f"Material '{name}' no existe en catalogo.")
        eff = effective_add(a, kg)
        for e in elements:
            masses[e] += eff[e]
        add_total_eff += kg * effective_total_perkg(a)
    Mnew = M0 + add_total_eff
    comp_pct = {e: (100.0 * masses[e] / Mnew if Mnew > 0 else 0.0) for e in elements}
    return (Mnew, comp_pct)
