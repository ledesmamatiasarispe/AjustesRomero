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
