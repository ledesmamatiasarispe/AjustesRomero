# ce.py
from utils import to_float, _norm
from config import ELEMENTS

def ce_from_percent(comp_pct, formula="FUNDICION", custom_coefs=None):
    """
    Calcula CE en % en peso. Fórmulas soportadas:
      - FUNDICION: C + (Si + P)/3
      - IIW:       C + Mn/6 + (Cr+Mo+V)/5 + (Ni+Cu)/15  (opcional Si/24 => "IIW+Si/24")
      - CET:       C + (Mn+Mo)/10 + (Cr+Cu)/20 + Ni/40
      - PERSONALIZADA: CE = Σ coef(elemento) * %(elemento)
    """
    f = _norm(formula or "FUNDICION")
    C  = to_float(comp_pct.get("C",0.0))
    Mn = to_float(comp_pct.get("Mn",0.0))
    Cr = to_float(comp_pct.get("Cr",0.0))
    Mo = to_float(comp_pct.get("Mo",0.0))
    V  = to_float(comp_pct.get("V",0.0))
    Ni = to_float(comp_pct.get("Ni",0.0))
    Cu = to_float(comp_pct.get("Cu",0.0))
    Si = to_float(comp_pct.get("Si",0.0))
    P  = to_float(comp_pct.get("P",0.0))

    if f in ("PERSONALIZADA","CUSTOM","PERSONAL"):
        total = 0.0
        coefs = custom_coefs or {}
        for e in ELEMENTS:
            total += to_float(coefs.get(e, 0.0)) * to_float(comp_pct.get(e, 0.0))
        return total

    if f in ("FUNDICION","FUNDICION GRIS","CAST","CASTIRON","CAST_IRON","FOUNDRY"):
        return C + (Si + P) / 3.0

    if f == "CET":
        return C + (Mn + Mo)/10.0 + (Cr + Cu)/20.0 + Ni/40.0

    # IIW base
    ce = C + Mn/6.0 + (Cr + Mo + V)/5.0 + (Ni + Cu)/15.0
    if f in ("IIW+SI/24","IIW_SI","IIW+SI"):
        ce += Si/24.0
    return ce
