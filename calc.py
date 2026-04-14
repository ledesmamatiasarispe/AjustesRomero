# calc.py
from __future__ import annotations

from typing import List, Optional

from config import ELEMENTS
from utils import to_float


def effective_total_perkg(alloy: dict) -> float:
    return to_float(alloy.get("rendimiento", 100.0)) / 100.0


def effective_add_perkg(alloy: dict, element: str) -> float:
    rend = effective_total_perkg(alloy)
    pct = to_float((alloy.get("composicion") or {}).get(element, 0.0)) / 100.0
    return rend * pct


def effective_add(alloy: dict, kg: float, elements: Optional[List[str]] = None) -> dict:
    rend = effective_total_perkg(alloy)
    out = {e: 0.0 for e in (elements or ELEMENTS)}
    comp = alloy.get("composicion") or {}
    for e in out.keys():
        out[e] = kg * (to_float(comp.get(e, 0.0)) / 100.0) * rend
    return out


def solve_kg_for_target(M: float, m_elem: float, T_frac: float, add_elem_perkg: float, add_total_perkg: float,
                        eps: float = 1e-12) -> Optional[float]:
    denom = add_elem_perkg - T_frac * add_total_perkg
    num = T_frac * M - m_elem
    if abs(denom) < eps:
        return None
    return num / denom


def solve_linear(A: List[List[float]], b: List[float], prefer_numpy: bool = True,
                 ridge: float = 1e-9, eps: float = 1e-12) -> Optional[List[float]]:
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

    # Gauss with partial pivoting
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
