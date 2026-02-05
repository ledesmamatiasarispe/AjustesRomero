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
    s = f"{x:.{nd}f}".rstrip("0").rstrip(".")
    return s or "0"

def fmt_opt(x, nd=6): return "" if x is None else fmt(float(x), nd)

def _norm(s):
    if not s: return ""
    return (s.upper()
              .replace("Ó","O").replace("Í","I")
              .replace("Á","A").replace("É","E").replace("Ú","U"))


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
