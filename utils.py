# utils.py
def to_float(s):
    if s is None: return 0.0
    s = str(s).strip().replace(",", ".")
    if not s: return 0.0
    try: return float(s)
    except: return 0.0

def to_float_or_none(s):
    if s is None: return None
    s = str(s).strip().replace(",", ".")
    if s == "": return None
    try: return float(s)
    except: return None

def fmt(x, nd=6):
    if nd <= 0:
        return f"{x:.0f}"
    s = f"{x:.{nd}f}".rstrip("0").rstrip(".")
    return s or "0"

def fmt_opt(x, nd=6): return "" if x is None else fmt(float(x), nd)

def _norm(s):
    if not s: return ""
    return (s.upper()
              .replace("Ó","O").replace("Í","I")
              .replace("Á","A").replace("É","E").replace("Ú","U"))


def simulate_staged(comp0, stage_specs, elements, get_alloy, effective_add, effective_total_perkg):
    """Simula la inoculación por etapas secuenciales.

    stage_specs: iterable de (mass_kg, [(nombre, kg), ...]).
    Cada etapa aplica sus inoculantes a mass_kg kg de metal con la composición
    resultante de la etapa anterior. Devuelve la composición final (%).
    """
    comp = {e: to_float(comp0.get(e, 0.0)) for e in elements}
    for mass_kg, items in stage_specs:
        if not items or mass_kg <= 0:
            continue
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
            comp = {e: 100.0 * masses[e] / M_new for e in elements}
    return comp


def simulate_with_plan(M0, comp0, plan, elements, get_alloy, effective_add, effective_total_perkg):
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
