# graph.py -- puerto sin cambios de backend/core/graph.py de ajuste_comp_web (solo imports relativos). Motor
# del gráfico de dispersión C/Si de Ajuste: solo la matemática pura (filtrado robusto de outliers, casco
# convexo, elipse de desviación por eje, recorte del área de límites por semiplanos de CE) -- el dibujo en
# canvas vive del lado del frontend (graph.js), este módulo arma el JSON que el frontend consume tal cual.
#
# Sistema de coordenadas: todo el gráfico está centrado en el objetivo (target C/Si) -- "dx"/"dy" en los
# payloads de salida son SIEMPRE delta respecto al target (C - target_C, Si - target_Si), nunca valores
# absolutos, salvo donde se indica lo contrario (los campos "c"/"si" de stat_circles son el centroide en valor
# ABSOLUTO, ya que hull_shape_stats no conoce el target -- quien llama a history_stat_circles le resta el
# target después, ver build_graph_payload).
#
# NO se portó _graph_circle_stats (elipse de covarianza/PCA): está en el original pero no la llama nadie --
# código muerto, se omite en vez de portar algo que la propia app de escritorio no usa.
import math

from .utils import to_float, _norm
from .ce import ce_from_percent
from .calc import ce_coeffs as _ce_coeffs


def material_key(value):
    """Normaliza un nombre de objetivo para agrupar/comparar entre sesiones de Históricos."""
    key = _norm(value)
    if key.startswith("mat") and key[3:].isdigit():
        return key[3:]
    return key


def robust_points(points):
    """Filtra outliers por distancia a la mediana (MAD, median absolute deviation). Con menos de 4 puntos no
    filtra nada (no hay suficiente info para distinguir outlier de dato real)."""
    if len(points) < 4:
        return points

    def median(vals):
        vals = sorted(vals)
        n = len(vals)
        mid = n // 2
        if n % 2:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2

    mx = median(p[0] for p in points)
    my = median(p[1] for p in points)
    distances = sorted(((p[0] - mx) ** 2 + (p[1] - my) ** 2) ** 0.5 for p in points)
    md = median(distances)
    deviations = sorted(abs(d - md) for d in distances)
    mad = median(deviations)
    limit = md + 0.05 if mad <= 1e-12 else md + (3.0 * 1.4826 * mad)
    filtered = [p for p in points if ((p[0] - mx) ** 2 + (p[1] - my) ** 2) ** 0.5 <= limit]
    return filtered if filtered else points


def axis_deviation_stats(points):
    """Elipse (en realidad rectángulo con ejes alineados a los ejes: angle siempre 0) de desviación media
    absoluta por eje. Usada para las elipses naranja (deriva entre ajustes consecutivos de una misma colada
    histórica)."""
    if not points:
        return None
    raw_count = len(points)
    points = robust_points(points)
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n
    if n == 1:
        dev_x = dev_y = 0.03
    else:
        dev_x = sum(abs(p[0] - mx) for p in points) / n
        dev_y = sum(abs(p[1] - my) for p in points) / n
    major = max(0.03, dev_x)
    minor = max(0.03, dev_y)
    return mx, my, major, minor, 0.0, n, raw_count, points


def hull_shape_stats(points):
    """Casco convexo (con un pequeño margen hacia afuera) de los puntos dados. Usada para los polígonos
    violeta (dónde cayó históricamente la composición inicial al empezar una colada con este mismo objetivo).
    "major"/"minor" quedan como el semi-ancho/alto del bounding box del polígono (no de una elipse real), se
    usan solo para reservar espacio al lado del label y en el cálculo del span global."""
    if not points:
        return None
    raw_count = len(points)
    points = robust_points(points)
    n = len(points)
    mx = sum(p[0] for p in points) / n
    my = sum(p[1] for p in points) / n

    def cross(o, a, b):
        return ((a[0] - o[0]) * (b[1] - o[1])) - ((a[1] - o[1]) * (b[0] - o[0]))

    unique = sorted(set(points))
    if len(unique) <= 2:
        polygon = [{"dx": p[0], "dy": p[1]} for p in unique]
    else:
        lower = []
        for p in unique:
            while len(lower) >= 2 and cross(lower[-2], lower[-1], p) <= 0:
                lower.pop()
            lower.append(p)
        upper = []
        for p in reversed(unique):
            while len(upper) >= 2 and cross(upper[-2], upper[-1], p) <= 0:
                upper.pop()
            upper.append(p)
        hull = lower[:-1] + upper[:-1]
        margin = 0.02
        polygon = []
        for x, y in hull:
            vx, vy = x - mx, y - my
            dist = (vx * vx + vy * vy) ** 0.5
            if dist > 1e-12:
                x += (vx / dist) * margin
                y += (vy / dist) * margin
            polygon.append({"dx": x, "dy": y})
    if len(polygon) < 3:
        major = minor = 0.03
        angle = 0.0
    else:
        xs = [to_float(p["dx"]) for p in polygon]
        ys = [to_float(p["dy"]) for p in polygon]
        major = max(0.03, max(abs(x - mx) for x in xs))
        minor = max(0.03, max(abs(y - my) for y in ys))
        angle = 0.0
    return mx, my, major, minor, angle, n, raw_count, points, polygon


def ellipse_extent(item):
    """Cuánto se extiende una elipse (major/minor/angle) en x e y. Se usa para reservar espacio al label y
    para el cálculo del span global (cuánto zoom-out hace falta para que todo entre)."""
    major = to_float(item.get("major", item.get("radius", 0.03)))
    minor = to_float(item.get("minor", item.get("radius", 0.03)))
    angle = to_float(item.get("angle", 0.0))
    ca, sa = math.cos(angle), math.sin(angle)
    x_extent = ((major * ca) ** 2 + (minor * sa) ** 2) ** 0.5
    y_extent = ((major * sa) ** 2 + (minor * ca) ** 2) ** 0.5
    return max(0.03, x_extent), max(0.03, y_extent)


def history_stat_circles(sessions, objective_name=""):
    """Agrupa, por cada material objetivo distinto visto en Históricos, la composición INICIAL (C/Si) del
    primer ajuste de cada sesión guardada que apuntó a ese objetivo, y calcula su casco convexo. Si se pasa
    objective_name, filtra a solo ese objetivo (comparación normalizada vía material_key)."""
    grouped = {}
    objective_key = material_key(objective_name)
    for session in sessions or []:
        if not isinstance(session, dict):
            continue
        adjustments = session.get("ajustes", [])
        if not isinstance(adjustments, list) or not adjustments:
            continue
        first = adjustments[0] if isinstance(adjustments[0], dict) else {}
        material = str(session.get("objetivo") or first.get("objetivo") or "").strip()
        if not material:
            continue
        if objective_key and material_key(material) != objective_key:
            continue
        initial = ((first.get("inicial") or {}).get("comp") or {})
        if not isinstance(initial, dict):
            continue
        grouped.setdefault(material, []).append(
            (to_float(initial.get("C", 0.0)), to_float(initial.get("Si", 0.0)))
        )

    circles = []
    for material, points in grouped.items():
        stats = hull_shape_stats(points)
        if not stats:
            continue
        mx, my, major, minor, angle, n, raw_count, used_points, polygon = stats
        circles.append({
            "material": material, "count": n, "raw_count": raw_count,
            "c": mx, "si": my, "major": major, "minor": minor, "angle": angle,
            "points": [{"c": p[0], "si": p[1]} for p in used_points],
            "polygon": polygon,
        })
    circles.sort(key=lambda item: (-item["count"], item["material"].lower()))
    return circles


def history_step_delta_circle(sessions, objective_name=""):
    """Para el mismo objetivo, mide cuánto "salta" la composición entre el final estimado de un ajuste
    aplicado y la lectura inicial del siguiente ajuste DENTRO de la misma colada histórica (sesiones con 2+
    ajustes). Es la "deriva" típica que separa lo que el motor estimó de lo que se terminó leyendo en la
    práctica antes del próximo ajuste."""
    objective_key = material_key(objective_name)
    points = []
    for session in sessions or []:
        if not isinstance(session, dict):
            continue
        adjustments = session.get("ajustes", [])
        if not isinstance(adjustments, list) or len(adjustments) < 2:
            continue
        first = adjustments[0] if isinstance(adjustments[0], dict) else {}
        material = str(session.get("objetivo") or first.get("objetivo") or "").strip()
        if not material:
            continue
        if objective_key and material_key(material) != objective_key:
            continue
        for prev, nxt in zip(adjustments, adjustments[1:]):
            if not isinstance(prev, dict) or not isinstance(nxt, dict):
                continue
            prev_final = ((prev.get("estimado") or {}).get("comp") or {})
            next_initial = ((nxt.get("inicial") or {}).get("comp") or {})
            if not isinstance(prev_final, dict) or not isinstance(next_initial, dict):
                continue
            points.append((
                to_float(next_initial.get("C", 0.0)) - to_float(prev_final.get("C", 0.0)),
                to_float(next_initial.get("Si", 0.0)) - to_float(prev_final.get("Si", 0.0)),
            ))
    stats = axis_deviation_stats(points)
    if not stats:
        return None
    dc, dsi, major, minor, angle, n, raw_count, used_points = stats
    return {
        "dc": dc, "dsi": dsi, "major": major, "minor": minor, "angle": angle,
        "count": n, "raw_count": raw_count,
        "points": [{"dc": p[0], "dsi": p[1]} for p in used_points],
    }


def _limit_bounds(mn, mx, target_value):
    has_min = mn is not None
    has_max = mx is not None
    if not has_min and not has_max:
        return None
    target_value = to_float(target_value)
    lower = to_float(mn) - target_value if has_min else -0.03
    upper = to_float(mx) - target_value if has_max else 0.03
    if lower > upper:
        lower, upper = upper, lower
    return (lower, upper)


def target_limit_area(target, limits, ce_min, ce_max, ce_formula, ce_custom):
    """Rectángulo de límites soft_min/soft_max de C y Si del objetivo, recortado además por los semiplanos de
    CE_min/CE_max (si la fórmula de CE elegida depende de C y/o Si). limits: dict {"C": {"soft_min":..,
    "soft_max":..}, "Si": {...}} del objetivo (mismo shape que alloy["limites"])."""
    if not target:
        return None
    c_lim = (limits or {}).get("C", {}) or {}
    si_lim = (limits or {}).get("Si", {}) or {}
    c_bounds = _limit_bounds(c_lim.get("soft_min"), c_lim.get("soft_max"), target.get("C", 0.0))
    si_bounds = _limit_bounds(si_lim.get("soft_min"), si_lim.get("soft_max"), target.get("Si", 0.0))
    if c_bounds is None and si_bounds is None:
        return None
    c_bounds = c_bounds or (-0.03, 0.03)
    si_bounds = si_bounds or (-0.03, 0.03)
    polygon = [
        {"dx": c_bounds[0], "dy": si_bounds[0]},
        {"dx": c_bounds[1], "dy": si_bounds[0]},
        {"dx": c_bounds[1], "dy": si_bounds[1]},
        {"dx": c_bounds[0], "dy": si_bounds[1]},
    ]

    ce_target = ce_from_percent(target, ce_formula, ce_custom)
    coeffs = _ce_coeffs(ce_formula, ce_custom)
    c_coef = to_float(coeffs.get("C", 0.0))
    si_coef = to_float(coeffs.get("Si", 0.0))

    def clip_halfplane(poly, a, b, limit):
        if not poly:
            return []

        def value(pt):
            return (a * to_float(pt["dx"])) + (b * to_float(pt["dy"]))

        def intersect(p1, p2):
            v1, v2 = value(p1), value(p2)
            denom = v2 - v1
            if abs(denom) <= 1e-12:
                return dict(p2)
            t = (limit - v1) / denom
            return {
                "dx": to_float(p1["dx"]) + t * (to_float(p2["dx"]) - to_float(p1["dx"])),
                "dy": to_float(p1["dy"]) + t * (to_float(p2["dy"]) - to_float(p1["dy"])),
            }

        out = []
        prev = poly[-1]
        prev_inside = value(prev) <= limit + 1e-12
        for curr in poly:
            curr_inside = value(curr) <= limit + 1e-12
            if curr_inside:
                if not prev_inside:
                    out.append(intersect(prev, curr))
                out.append(dict(curr))
            elif prev_inside:
                out.append(intersect(prev, curr))
            prev = curr
            prev_inside = curr_inside
        return out

    if abs(c_coef) > 1e-12 or abs(si_coef) > 1e-12:
        if ce_max is not None:
            polygon = clip_halfplane(polygon, c_coef, si_coef, to_float(ce_max) - ce_target)
        if ce_min is not None:
            polygon = clip_halfplane(polygon, -c_coef, -si_coef, -(to_float(ce_min) - ce_target))
    if len(polygon) < 3:
        return None
    x_extent = max(abs(to_float(p["dx"])) for p in polygon)
    y_extent = max(abs(to_float(p["dy"])) for p in polygon)
    return {
        "dx": 0.0, "dy": 0.0,
        "major": max(0.001, x_extent), "minor": max(0.001, y_extent), "angle": 0.0,
        "polygon": polygon,
    }


def build_graph_payload(*, objective_name, target, current, predicted, has_live_prediction,
                         adjustments, objective_limits, ce_min, ce_max, ce_formula, ce_custom,
                         sessions):
    """Arma el payload completo que consume graph.js (la parte de cálculo; el dibujo en sí vive en el
    frontend). `adjustments` es la lista de ajustes YA APLICADOS en la sesión en curso ([{"initial": comp%,
    "final": comp%}, ...], en orden cronológico) -- cada uno se dibuja como una flecha numerada roja→azul."""
    transitions = []
    plot_points = []
    for idx, item in enumerate(adjustments or [], start=1):
        initial = item.get("initial") or {}
        final = item.get("final") or {}
        start = {"kind": "initial", "label": str(idx), "c": to_float(initial.get("C", 0.0)), "si": to_float(initial.get("Si", 0.0))}
        end = {"kind": "final", "label": str(idx), "c": to_float(final.get("C", 0.0)), "si": to_float(final.get("Si", 0.0))}
        transitions.append({"label": str(idx), "start": start, "end": end})
        plot_points.extend([start, end])

    current_point = {"kind": "current", "label": "Actual", "c": to_float((current or {}).get("C", 0.0)), "si": to_float((current or {}).get("Si", 0.0))}
    plot_points.append(current_point)

    estimated_point = None
    if has_live_prediction and predicted:
        estimated_point = {"kind": "estimated", "label": "Estimado", "c": to_float(predicted.get("C", 0.0)), "si": to_float(predicted.get("Si", 0.0))}
        plot_points.append(estimated_point)

    target_c = to_float((target or {}).get("C", 0.0))
    target_si = to_float((target or {}).get("Si", 0.0))
    for pt in plot_points:
        pt["dx"] = pt["c"] - target_c
        pt["dy"] = pt["si"] - target_si

    stat_circles = history_stat_circles(sessions, objective_name)
    for st in stat_circles:
        st["dx"] = to_float(st.get("c", 0.0)) - target_c
        st["dy"] = to_float(st.get("si", 0.0)) - target_si
        st["plot_points"] = [
            {"dx": to_float(p.get("c", 0.0)) - target_c, "dy": to_float(p.get("si", 0.0)) - target_si}
            for p in st.get("points", [])
        ]
        # st["polygon"] llega con valores ABSOLUTOS de C/Si guardados bajo las claves dx/dy (así los deja
        # hull_shape_stats, que no conoce el target) -- acá recién se convierten a delta real.
        st["polygon"] = [
            {"dx": to_float(p.get("dx", 0.0)) - target_c, "dy": to_float(p.get("dy", 0.0)) - target_si}
            for p in st.get("polygon", [])
        ]

    step_delta = history_step_delta_circle(sessions, objective_name)
    step_circles = []
    for tr in transitions:
        if step_delta:
            end = tr["end"]
            step_circles.append({
                "label": tr["label"],
                "count": step_delta.get("count", 0),
                "raw_count": step_delta.get("raw_count", 0),
                "dx": (to_float(end.get("c", 0.0)) + to_float(step_delta.get("dc", 0.0))) - target_c,
                "dy": (to_float(end.get("si", 0.0)) + to_float(step_delta.get("dsi", 0.0))) - target_si,
                "major": step_delta.get("major", 0.03),
                "minor": step_delta.get("minor", 0.03),
                "angle": step_delta.get("angle", 0.0),
                "plot_points": [
                    {
                        "dx": (to_float(end.get("c", 0.0)) + to_float(p.get("dc", 0.0))) - target_c,
                        "dy": (to_float(end.get("si", 0.0)) + to_float(p.get("dsi", 0.0))) - target_si,
                    }
                    for p in step_delta.get("points", [])
                ],
            })

    tla = target_limit_area(target, objective_limits, ce_min, ce_max, ce_formula, ce_custom)

    max_abs = max(
        [abs(pt["dx"]) for pt in plot_points]
        + [abs(pt["dy"]) for pt in plot_points]
        + [abs(st["dx"]) + ellipse_extent(st)[0] for st in stat_circles]
        + [abs(st["dy"]) + ellipse_extent(st)[1] for st in stat_circles]
        + [abs(st["dx"]) + ellipse_extent(st)[0] for st in step_circles]
        + [abs(st["dy"]) + ellipse_extent(st)[1] for st in step_circles]
        + ([to_float(tla.get("major", 0.0)), to_float(tla.get("minor", 0.0))] if tla else [])
        + [0.05]
    )
    span = max_abs * 1.20

    return {
        "has_objective": True,
        "target_c": target_c, "target_si": target_si,
        "transitions": transitions,
        "current": current_point,
        "estimated": estimated_point,
        "target_limit_area": tla,
        "stat_circles": stat_circles,
        "step_circles": step_circles,
        "span": span,
    }
