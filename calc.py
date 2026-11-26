# calc.py
#
# *** NO SE USA EN NINGUN LADO ***  (verificado: ningun otro archivo del
# repo hace "from calc import ..." ni "import calc"). Parece una extraccion
# de la logica de calculo de tab_ajuste.py a un modulo standalone/testeable
# que nunca se termino de conectar: tab_ajuste.py tiene sus propias copias
# internas y funcionalmente identicas (_solve_linear, _solve_kg_for_target,
# _effective_add_perkg, etc, ver PROJECT_NOTES.md "Quick Reference of Key
# Functions"). Mejora sugerida: o se conecta tab_ajuste.py para usar estas
# funciones (elimina duplicacion), o se borra este archivo si no hay plan de
# usarlo. Se deja comentado igual por si sirve de referencia/documentacion
# de la matematica del ajuste.
from __future__ import annotations

from typing import List, Optional

from config import ELEMENTS
from utils import to_float


def effective_total_perkg(alloy: dict) -> float:
    """Fraccion de 1 kg del material que efectivamente termina en el baño
    (lo demas se pierde por oxidacion/escoria/etc), segun su "rendimiento"
    (%) cargado en el catalogo. rendimiento=100 -> devuelve 1.0 (sin perdida)."""
    return to_float(alloy.get("rendimiento", 100.0)) / 100.0


def effective_add_perkg(alloy: dict, element: str) -> float:
    """Cuanto de un elemento puntual aporta 1 kg de este material al baño,
    ya descontado el rendimiento (composicion% * rendimiento%)."""
    rend = effective_total_perkg(alloy)
    pct = to_float((alloy.get("composicion") or {}).get(element, 0.0)) / 100.0
    return rend * pct


def effective_add(alloy: dict, kg: float, elements: Optional[List[str]] = None) -> dict:
    """Igual que effective_add_perkg pero para todos los elementos a la vez
    y para una cantidad `kg` concreta de material (no por kg unitario)."""
    rend = effective_total_perkg(alloy)
    out = {e: 0.0 for e in (elements or ELEMENTS)}
    comp = alloy.get("composicion") or {}
    for e in out.keys():
        out[e] = kg * (to_float(comp.get(e, 0.0)) / 100.0) * rend
    return out


def solve_kg_for_target(M: float, m_elem: float, T_frac: float, add_elem_perkg: float, add_total_perkg: float,
                        eps: float = 1e-12) -> Optional[float]:
    """Despeja cuantos kg de UN material agregar para que UN elemento llegue
    exactamente a T_frac (fraccion 0-1) del baño, partiendo de masa total M
    y masa actual del elemento m_elem. Es la solucion algebraica de:
        T_frac = (m_elem + kg*add_elem_perkg) / (M + kg*add_total_perkg)
    Si el denominador es ~0 (el material no mueve el objetivo, ej. no tiene
    ese elemento y ademas no diluye), no hay solucion y devuelve None."""
    denom = add_elem_perkg - T_frac * add_total_perkg
    num = T_frac * M - m_elem
    if abs(denom) < eps:
        return None
    return num / denom


def solve_linear(A: List[List[float]], b: List[float], prefer_numpy: bool = True,
                 ridge: float = 1e-9, eps: float = 1e-12) -> Optional[List[float]]:
    """Resuelve el sistema (posiblemente sobre/sub-determinado) A*x = b para
    un plan de ajuste con VARIOS materiales y VARIOS elementos objetivo a la
    vez (algoritmo "Lineal" del ajuste). Primero intenta numpy (minimos
    cuadrados via lstsq, mas estable); si numpy no esta disponible cae a una
    implementacion manual por ecuaciones normales (A^T A x = A^T b) con
    "ridge" (regularizacion) para que la matriz no quede singular con datos
    casi-colineales, resuelta por eliminacion gaussiana con pivoteo parcial."""
    if not A or not A[0]:
        return None
    m = len(A)
    n = len(A[0])

    if prefer_numpy:
        try:
            import numpy as np  # type: ignore
            x, *_ = np.linalg.lstsq(np.array(A, dtype=float), np.array(b, dtype=float), rcond=None)
            return [float(v) for v in x.tolist()]
        except Exception:
            pass

    # Build normal equations with ridge regularization
    ATA = [[0.0 for _ in range(n)] for _ in range(n)]
    ATb = [0.0 for _ in range(n)]
    for i in range(n):
        for j in range(n):
            s = 0.0
            for k in range(m):
                s += A[k][i] * A[k][j]
            ATA[i][j] = s
        ATA[i][i] += ridge
        sb = 0.0
        for k in range(m):
            sb += A[k][i] * b[k]
        ATb[i] = sb

    # Gauss con pivoteo parcial: en cada columna, usar como pivote la fila
    # con mayor valor absoluto restante (mejora estabilidad numerica).
    for i in range(n):
        pivot_row = i
        pivot_val = abs(ATA[i][i])
        for r in range(i + 1, n):
            if abs(ATA[r][i]) > pivot_val:
                pivot_val = abs(ATA[r][i])
                pivot_row = r
        if pivot_val < eps:
            return None
        if pivot_row != i:
            ATA[i], ATA[pivot_row] = ATA[pivot_row], ATA[i]
            ATb[i], ATb[pivot_row] = ATb[pivot_row], ATb[i]

        pivot = ATA[i][i]
        inv = 1.0 / pivot
        for j in range(i, n):
            ATA[i][j] *= inv
        ATb[i] *= inv

        for r in range(n):
            if r == i:
                continue
            factor = ATA[r][i]
            if abs(factor) < eps:
                continue
            for c in range(i, n):
                ATA[r][c] -= factor * ATA[i][c]
            ATb[r] -= factor * ATb[i]
    return ATb
