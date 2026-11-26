# calc.py -- puerto sin cambios de backend/core/calc.py de ajuste_comp_web (salvo los imports, ahora relativos
# al paquete del módulo).
#
# Motor de calculo de composiciones — UNICO lugar de la app donde corre esta matematica. Funciones puras
# (reciben todo por parametro, no dependen de un self.alloys/self.cb_obj) para que rutas/ajuste.py,
# rutas/catalogo.py y cualquier otro dominio que necesite "que composicion me queda si agrego estos
# materiales" llamen siempre a lo mismo, en vez de reimplementarlo cada uno por su lado.
from __future__ import annotations

from typing import List, Optional

from .config import ELEMENTS
from .utils import to_float, _norm, simulate_with_plan


def effective_total_perkg(alloy: dict) -> float:
    """Fraccion de 1 kg del material que efectivamente termina en el baño (lo demas se pierde por
    oxidacion/escoria/etc), segun su "rendimiento" (%) cargado en el catalogo. rendimiento=100 -> devuelve 1.0
    (sin perdida)."""
    return to_float(alloy.get("rendimiento", 100.0)) / 100.0


def effective_add_perkg(alloy: dict, element: str) -> float:
    """Cuanto de un elemento puntual aporta 1 kg de este material al baño, ya descontado el rendimiento
    (composicion% * rendimiento%)."""
    rend = effective_total_perkg(alloy)
    pct = to_float((alloy.get("composicion") or {}).get(element, 0.0)) / 100.0
    return rend * pct


def effective_add(alloy: dict, kg: float, elements: Optional[List[str]] = None) -> dict:
    """Igual que effective_add_perkg pero para todos los elementos a la vez y para una cantidad `kg` concreta
    de material (no por kg unitario)."""
    rend = effective_total_perkg(alloy)
    out = {e: 0.0 for e in (elements or ELEMENTS)}
    comp = alloy.get("composicion") or {}
    for e in out.keys():
        out[e] = kg * (to_float(comp.get(e, 0.0)) / 100.0) * rend
    return out


def estimate_composition(comp_actual: dict, masa_bano: float, plan_materiales: list,
                          elements: Optional[List[str]] = None) -> dict:
    """UNICO punto de la app para "si le agrego estos materiales al baño, que composicion me queda" — tanto el
    motor de Ajuste (Greedy/Lineal) como cualquier vista de composicion estimada en otros dominios (Catalogo,
    Informes, etc.) tienen que pasar su plan por aca en vez de reimplementar la suma a mano.

    plan_materiales: lista de {"alloy": <dict con composicion/rendimiento>, "kg": float}. Cada item trae su
    propio dict de alloy en vez de resolverse por nombre contra el catalogo — da lo mismo si ese dict es un
    material real, uno tipeado a mano (rendimiento 100 si no se aclara), o uno armado a partir de una seleccion
    de inoculantes (kg = dosis * gramos_cucharin1 / 1000, con la composicion propia de ese inoculante). La suma
    es lineal, asi que combinar matA + matB no requiere "fusionarlos" en un matC sintetico antes de sumar:
    pasarlos como dos entradas del plan da el mismo resultado.

    Envoltorio fino sobre utils.simulate_with_plan (misma matematica que tab_ajuste.py::calc_prediction) — arma
    un dict {clave_temporal: kg} y un get_alloy() que resuelve esas claves contra los dicts ya recibidos, para
    no obligar al llamador a inventar nombres de catalogo para materiales que no existen ahi.

    Devuelve {"mass": <masa efectiva resultante>, "composicion": {el: %}}."""
    elements = elements or ELEMENTS
    alloys_by_key = {}
    plan_by_key = {}
    for i, item in enumerate(plan_materiales or []):
        kg = to_float(item.get("kg", 0.0))
        if kg <= 0:
            continue
        key = f"__plan_{i}__"
        alloys_by_key[key] = item.get("alloy") or {}
        plan_by_key[key] = kg
    mass_nueva, comp = simulate_with_plan(
        to_float(masa_bano), comp_actual or {}, plan_by_key, elements,
        alloys_by_key.get, effective_add, effective_total_perkg,
    )
    return {"mass": mass_nueva, "composicion": comp}


def ce_coeffs(formula: str, custom_coefs: Optional[dict] = None) -> dict:
    """Coeficientes {elemento: peso} de la formula de carbono equivalente elegida — puerto de
    tab_ajuste.py::_ce_coeffs. Se usan tanto para mostrar el CE (ver ce.py::ce_from_percent, que ya tiene su
    propia tabla) como aca en el solver, para desempatar en el metodo Greedy priorizando materiales que NO
    empujen el CE (ver ce_impact_perkg)."""
    f = _norm(formula or "FUNDICION")
    if f in ("PERSONALIZADA", "CUSTOM", "PERSONAL"):
        coefs = {}
        for e in ELEMENTS:
            v = to_float((custom_coefs or {}).get(e, 0.0))
            if v != 0.0:
                coefs[e] = v
        return coefs
    if f in ("FUNDICION", "FUNDICION GRIS", "CAST", "CASTIRON", "CAST_IRON", "FOUNDRY"):
        return {"C": 1.0, "Si": 1.0 / 3.0, "P": 1.0 / 3.0}
    if f == "CET":
        return {"C": 1.0, "Mn": 1.0 / 10.0, "Mo": 1.0 / 10.0, "Cr": 1.0 / 20.0, "Cu": 1.0 / 20.0, "Ni": 1.0 / 40.0}
    coefs = {"C": 1.0, "Mn": 1.0 / 6.0, "Cr": 1.0 / 5.0, "Mo": 1.0 / 5.0, "V": 1.0 / 5.0, "Ni": 1.0 / 15.0, "Cu": 1.0 / 15.0}
    if f in ("IIW+SI/24", "IIW_SI", "IIW+SI"):
        coefs["Si"] = 1.0 / 24.0
    return coefs


def ce_impact_perkg(alloy: dict, coeffs: dict) -> float:
    """Cuanto mueve el CE un kg de este material — puerto de tab_ajuste.py::_ce_impact_perkg. Se usa solo para
    el desempate del Greedy (grupo 0 = no toca el CE, se prefiere sobre grupo 1)."""
    rend = effective_total_perkg(alloy)
    impact = 0.0
    comp = alloy.get("composicion", {}) or {}
    for e, coef in (coeffs or {}).items():
        pct = to_float(comp.get(e, 0.0))
        impact += rend * (pct / 100.0) * coef
    return impact


def pick_base_adjusters(adjust_alloys: dict):
    """adjust_alloys: {nombre: alloy_dict} de los materiales de ajuste candidatos. Elige dinamicamente los tres
    materiales "base" que resuelven C/Si/Fe: el que mas %C aporta, el que mas %Si aporta, el que mas %Fe
    aporta — puerto de tab_ajuste.py::_pick_base_adjusters (misma logica, ahi recorria adjust_names y resolvia
    cada uno por nombre)."""
    best_c = (None, 0.0)
    best_si = (None, 0.0)
    best_fe = (None, -1.0)
    for a in adjust_alloys.values():
        if not a:
            continue
        comp = a.get("composicion", {}) or {}
        c = to_float(comp.get("C", 0.0))
        si = to_float(comp.get("Si", 0.0))
        fe = to_float(comp.get("Fe", 0.0))
        if c > best_c[1]:
            best_c = (a, c)
        if si > best_si[1]:
            best_si = (a, si)
        if fe > best_fe[1]:
            best_fe = (a, fe)
    return (best_c[0], best_si[0], best_fe[0])


def estimate_plan(comp_actual: dict, mass: float, target_comp: dict, adjust_alloys: dict,
                   method: str = "Greedy", ce_formula: str = "FUNDICION",
                   ce_custom: Optional[dict] = None, elements: Optional[List[str]] = None) -> dict:
    """Puerto 1:1 de tab_ajuste.py::_estimate_core, sin las partes de UI/
    estado/logging (eso lo maneja routers/ajuste.py) — funcion pura que
    recibe todo por parametro y devuelve el plan de materiales a agregar.

    adjust_alloys: {nombre: alloy_dict} — los materiales de ajuste
    seleccionados por el usuario, YA resueltos contra el catalogo (incluye
    el flag "ajuste" y la composicion/rendimiento de cada uno).

    Estrategia en dos etapas porque C, Si y Fe se resuelven distinto del
    resto (ver comentario largo original en tab_ajuste.py):
      1) Para cada elemento que NO sea C/Si/Fe con objetivo > 0, se sube
         usando el material que mas aporte ese elemento por kg ("Greedy"),
         o con el metodo "Lineal" se arma y resuelve un sistema de
         ecuaciones para varios elementos/materiales a la vez (con fallback
         a Greedy elemento-por-elemento para lo que el sistema no cubra).
      2) Con las masas ya actualizadas por la etapa 1, se resuelven C/Si/Fe:
         los materiales base (mas %C / %Si / %Fe entre los candidatos) se
         despejan analiticamente contra el objetivo de C y Si, y Fe cierra
         el balance de masa.

    Devuelve {"plan": {nombre: kg}, "missing_elements": [...], "warning": str|None}.
    Si faltan materiales base (C/Si/Fe) entre los candidatos, {"error": "..."}."""
    elements = elements or ELEMENTS
    eps = 1e-12
    M0 = to_float(mass)
    comp0 = comp_actual or {}
    masses = {e: M0 * to_float(comp0.get(e, 0.0)) / 100.0 for e in elements}
    M = M0

    tgt_pct = target_comp or {}
    T_C = to_float(tgt_pct.get("C", 0.0)) / 100.0
    T_Si = to_float(tgt_pct.get("Si", 0.0)) / 100.0
    T_frac = {e: to_float(tgt_pct.get(e, 0.0)) / 100.0 for e in elements}

    a_graph, a_sil, a_steel = pick_base_adjusters(adjust_alloys)
    if not (a_graph and a_sil and a_steel):
        return {"error": "faltan_materiales_base"}

    coeffs = ce_coeffs(ce_formula, ce_custom)
    other_adjusters = [n for n in adjust_alloys.keys() if n]
    missing_elems = []
    warn_msg = None

    # 1) Subir elementos != C,Si,Fe con los materiales elegidos
    kg_other = {}
    best_for_elem = {}
    for el in [e for e in elements if e not in ("C", "Si", "Fe")]:
        best_name, best_rE = None, 0.0
        for nm in other_adjusters:
            a = adjust_alloys.get(nm)
            if not a:
                continue
            rE = effective_add_perkg(a, el)
            if rE > best_rE + 1e-16:
                best_name, best_rE = nm, rE
        if best_name:
            best_for_elem[el] = best_name

    if method == "Lineal":
        target_elems = [e for e in elements if e not in ("C", "Si", "Fe") and to_float(tgt_pct.get(e, 0.0)) > 0]
        mats = [nm for nm in other_adjusters
                if any(effective_add_perkg(adjust_alloys.get(nm), e) > eps for e in target_elems)]
        if target_elems and mats:
            A, b = [], []
            for e in target_elems:
                A.append([effective_add_perkg(adjust_alloys.get(nm), e) for nm in mats])
                b.append(T_frac.get(e, 0.0) * M - masses[e])
            sol = solve_linear(A, b)
            if sol:
                for nm, kg in zip(mats, sol):
                    if kg and kg > 0:
                        a = adjust_alloys.get(nm)
                        eff = effective_add(a, kg, elements)
                        for e in elements:
                            masses[e] += eff[e]
                        M += kg * effective_total_perkg(a)
                        kg_other[nm] = kg_other.get(nm, 0.0) + kg
        # fallback greedy para lo que el sistema lineal no haya cubierto
        for el in [e for e in elements if e not in ("C", "Si", "Fe")]:
            T_E = to_float(tgt_pct.get(el, 0.0)) / 100.0
            if T_E <= 0:
                continue
            fE = masses[el] / M if M > 0 else 0.0
            if fE < T_E - 1e-12:
                nm = best_for_elem.get(el)
                if not nm:
                    missing_elems.append(el)
                    continue
                a = adjust_alloys.get(nm)
                if not a:
                    missing_elems.append(el)
                    continue
                rE = effective_add_perkg(a, el)
                rTOT = effective_total_perkg(a)
                if rTOT <= 0 or rE <= eps:
                    missing_elems.append(el)
                    continue
                k = solve_kg_for_target(M, masses[el], T_E, rE, rTOT)
                if k is None or k <= 0:
                    missing_elems.append(el)
                    continue
                eff = effective_add(a, k, elements)
                for e in elements:
                    masses[e] += eff[e]
                M += k * rTOT
                kg_other[nm] = kg_other.get(nm, 0.0) + k
    else:
        for el in [e for e in elements if e not in ("C", "Si", "Fe")]:
            T_E = to_float(tgt_pct.get(el, 0.0)) / 100.0
            if T_E <= 0:
                continue
            fE = masses[el] / M if M > 0 else 0.0
            if fE < T_E - 1e-12:
                best_name, best_a, best_k, best_rTOT, best_rE = None, None, None, 0.0, None
                best_group = 2
                nm = best_for_elem.get(el)
                if nm:
                    a = adjust_alloys.get(nm)
                    rE = effective_add_perkg(a, el)
                    rTOT = effective_total_perkg(a)
                    if rTOT > 0 and rE > eps:
                        impact = ce_impact_perkg(a, coeffs)
                        group = 0 if impact <= 1e-9 else 1
                        k = solve_kg_for_target(M, masses[el], T_E, rE, rTOT)
                        if k is not None and k > 0:
                            eff = effective_add(a, k, elements)
                            Mnew = M + k * rTOT
                            ok = True
                            for e in elements:
                                T_e = T_frac.get(e, 0.0)
                                if T_e > 0:
                                    f_new = (masses[e] + eff[e]) / Mnew if Mnew > 0 else 0.0
                                    if f_new > T_e + 1e-12:
                                        ok = False
                                        break
                            if ok and group <= best_group:
                                if (group < best_group or best_rE is None or rE > best_rE + 1e-16
                                        or (abs(rE - best_rE) <= 1e-16 and (best_k is None or k < best_k))):
                                    best_group = group
                                    best_name, best_a, best_k, best_rTOT, best_rE = nm, a, k, rTOT, rE
                if best_a and best_k and best_k > 0:
                    eff = effective_add(best_a, best_k, elements)
                    for e in elements:
                        masses[e] += eff[e]
                    M += best_k * best_rTOT
                    kg_other[best_name] = kg_other.get(best_name, 0.0) + best_k
                else:
                    missing_elems.append(el)

    if missing_elems:
        warn_msg = "No hay material de ajuste que eleve sin pasarse para: " + ", ".join(missing_elems)

    # 2) Bajar con acero si C/Si por encima del objetivo
    kg_steel = kg_C = kg_Si = 0.0
    rTOT_s = effective_total_perkg(a_steel)
    rC_s = effective_add_perkg(a_steel, "C")
    rSi_s = effective_add_perkg(a_steel, "Si")
    rTOT_g = effective_total_perkg(a_graph)
    rC_g = effective_add_perkg(a_graph, "C")
    rTOT_si = effective_total_perkg(a_sil)
    rSi = effective_add_perkg(a_sil, "Si")

    def fracC():
        return masses["C"] / M if M > 0 else 0.0

    def fracSi():
        return masses["Si"] / M if M > 0 else 0.0

    need_down_C = fracC() > T_C + 1e-12
    need_down_Si = fracSi() > T_Si + 1e-12
    if need_down_C or need_down_Si:
        kC = solve_kg_for_target(M, masses["C"], T_C, rC_s, rTOT_s) if need_down_C else None
        kSi = solve_kg_for_target(M, masses["Si"], T_Si, rSi_s, rTOT_s) if need_down_Si else None
        k = max((kC or 0.0), (kSi or 0.0))
        if k and k > 0:
            eff = effective_add(a_steel, k, elements)
            for e in elements:
                masses[e] += eff[e]
            M += k * rTOT_s
            kg_steel += k

    # 3) Subir lo que falte de C y Si
    if fracC() < T_C - 1e-12 and rC_g > eps:
        k = solve_kg_for_target(M, masses["C"], T_C, rC_g, rTOT_g)
        if k and k > 0:
            eff = effective_add(a_graph, k, elements)
            for e in elements:
                masses[e] += eff[e]
            M += k * rTOT_g
            kg_C += k
    if fracSi() < T_Si - 1e-12 and rSi > eps:
        k = solve_kg_for_target(M, masses["Si"], T_Si, rSi, rTOT_si)
        if k and k > 0:
            eff = effective_add(a_sil, k, elements)
            for e in elements:
                masses[e] += eff[e]
            M += k * rTOT_si
            kg_Si += k

    # Plan final
    plan = {}
    for n, kg in kg_other.items():
        if kg > 0:
            plan[n] = plan.get(n, 0.0) + kg
    if kg_steel > 0 and a_steel:
        nm = a_steel.get("nombre", "")
        plan[nm] = plan.get(nm, 0.0) + kg_steel
    if kg_C > 0 and a_graph:
        nm = a_graph.get("nombre", "")
        plan[nm] = plan.get(nm, 0.0) + kg_C
    if kg_Si > 0 and a_sil:
        nm = a_sil.get("nombre", "")
        plan[nm] = plan.get(nm, 0.0) + kg_Si

    # Refuerzo: si algun elemento objetivo quedo por debajo (por interaccion
    # entre etapas), agregar con el mejor material candidato para ese
    # elemento (mismo bloque "try/except: pass" que el original — es un
    # ajuste best-effort, si no encuentra material valido lo deja pasar).
    try:
        M_sim = M0
        masses_sim = {e: M0 * to_float(comp0.get(e, 0.0)) / 100.0 for e in elements}
        for nm, kg in plan.items():
            if kg <= 0:
                continue
            a = adjust_alloys.get(nm)
            if not a:
                continue
            eff = effective_add(a, kg, elements)
            for e in elements:
                masses_sim[e] += eff[e]
            M_sim += kg * effective_total_perkg(a)
        for el in [e for e in elements if e not in ("C", "Si", "Fe")]:
            T_E = to_float(tgt_pct.get(el, 0.0)) / 100.0
            if T_E <= 0:
                continue
            fE = masses_sim[el] / M_sim if M_sim > 0 else 0.0
            if fE < T_E - 1e-12:
                nm = best_for_elem.get(el)
                if not nm:
                    continue
                a = adjust_alloys.get(nm)
                if not a:
                    continue
                rE = effective_add_perkg(a, el)
                rTOT = effective_total_perkg(a)
                if rTOT <= 0 or rE <= eps:
                    continue
                k = solve_kg_for_target(M_sim, masses_sim[el], T_E, rE, rTOT)
                if k is None or k <= 0:
                    continue
                eff = effective_add(a, k, elements)
                for e in elements:
                    masses_sim[e] += eff[e]
                M_sim += k * rTOT
                plan[nm] = plan.get(nm, 0.0) + k
    except Exception:
        pass

    return {"plan": plan, "missing_elements": missing_elems, "warning": warn_msg}


def solve_kg_for_target(M: float, m_elem: float, T_frac: float, add_elem_perkg: float, add_total_perkg: float,
                        eps: float = 1e-12) -> Optional[float]:
    """Despeja cuantos kg de UN material agregar para que UN elemento llegue exactamente a T_frac (fraccion
    0-1) del baño, partiendo de masa total M y masa actual del elemento m_elem. Es la solucion algebraica de:
        T_frac = (m_elem + kg*add_elem_perkg) / (M + kg*add_total_perkg)
    Si el denominador es ~0 (el material no mueve el objetivo, ej. no tiene ese elemento y ademas no diluye),
    no hay solucion y devuelve None."""
    denom = add_elem_perkg - T_frac * add_total_perkg
    num = T_frac * M - m_elem
    if abs(denom) < eps:
        return None
    return num / denom


def solve_linear(A: List[List[float]], b: List[float], prefer_numpy: bool = True,
                 ridge: float = 1e-9, eps: float = 1e-12) -> Optional[List[float]]:
    """Resuelve el sistema (posiblemente sobre/sub-determinado) A*x = b para un plan de ajuste con VARIOS
    materiales y VARIOS elementos objetivo a la vez (algoritmo "Lineal" del ajuste). Primero intenta numpy
    (minimos cuadrados via lstsq, mas estable); si numpy no esta disponible cae a una implementacion manual por
    ecuaciones normales (A^T A x = A^T b) con "ridge" (regularizacion) para que la matriz no quede singular con
    datos casi-colineales, resuelta por eliminacion gaussiana con pivoteo parcial."""
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

    # Gauss con pivoteo parcial: en cada columna, usar como pivote la fila con mayor valor absoluto restante
    # (mejora estabilidad numerica).
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
