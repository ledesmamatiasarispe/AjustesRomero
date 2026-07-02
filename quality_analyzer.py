"""
Funciones de análisis OpenCV de microestructura — versión standalone (sin Tkinter).
Extraídas de tab_calidad.py para uso en quality_api.py (servidor web).
"""
import json
import re
from pathlib import Path

IMAGEJ_RESOLUCION_PX_MM = 1655
IMAGEJ_AREA_UMBRAL = 100
IMAGEJ_LIMITS = (
    ("Clase 3 (0.25-0.50mm)", 0.25, 0.50),
    ("Clase 4 (0.12-0.25mm)", 0.12, 0.25),
    ("Clase 5 (0.06-0.12mm)", 0.06, 0.12),
    ("Clase 6 (0.03-0.06mm)", 0.03, 0.06),
    ("Clase 7 (0.015-0.03mm)", 0.015, 0.03),
    ("Clase 8 (<0.015mm)", 0.0001, 0.015),
)

_LAMINAR_MORPH_LABELS = {
    "A": "A — Distribución uniforme aleatoria",
    "B": "B — Distribución en rosetas",
    "C": "C — Grafito Kish (laminillas grandes)",
    "D": "D — Interdendrítico aleatorio",
    "E": "E — Interdendrítico orientado",
}

_CAL_FILE = Path.home() / "ajuste_comp_calibraciones.json"


def load_calibrations() -> list:
    try:
        return json.loads(_CAL_FILE.read_text(encoding="utf-8"))
    except Exception:
        return []


def get_px_per_mm(cal_id: str | None) -> float | None:
    cals = load_calibrations()
    effective_id = cal_id
    if not effective_id:
        effective_id = next((c["id"] for c in cals if c.get("is_default")), None)
    if not effective_id:
        return None
    cal = next((c for c in cals if c.get("id") == effective_id), None)
    if not cal or not cal.get("px_per_unit"):
        return None
    unit = cal.get("unit", "µm")
    v = float(cal["px_per_unit"])
    if unit == "µm":
        return v * 1000.0
    if unit == "cm":
        return v / 10.0
    return v  # mm


def classify_particle_material(mean_val, solidity, mean_bgr, circularity,
                                mns_thresh=95, rechupe_solidity=0.52,
                                mns_blue_ratio=1.12, mns_min_circ=0.45,
                                rechupe_sat_thresh=70, rechupe_val_thresh=95) -> str:
    import cv2 as _cv2
    import numpy as np

    hsv_s, hsv_v = 0, 255
    if mean_bgr is not None:
        try:
            px = np.uint8([[[int(mean_bgr[0]), int(mean_bgr[1]), int(mean_bgr[2])]]])
            hsv = _cv2.cvtColor(px, _cv2.COLOR_BGR2HSV)[0][0]
            hsv_s, hsv_v = int(hsv[1]), int(hsv[2])
        except Exception:
            pass

    if hsv_v < 55 and hsv_s < 30:
        return "C"

    if hsv_s > rechupe_sat_thresh and hsv_v < rechupe_val_thresh:
        return "rechupe"

    if circularity >= mns_min_circ:
        color_gris = mean_val > mns_thresh
        color_violet = False
        if mean_bgr is not None:
            b, r = float(mean_bgr[0]), float(mean_bgr[2])
            color_violet = b > 25 and (b / max(r, 1)) >= mns_blue_ratio
        if color_gris or color_violet:
            return "MnS"

    if solidity < rechupe_solidity:
        return "rechupe"

    return "C"


def get_nodule_contours(image_bgr, threshold=0, min_area=None, use_open=True) -> list:
    import numpy as np
    import cv2 as _cv2

    area_min = int(min_area) if min_area is not None else IMAGEJ_AREA_UMBRAL
    gray = _cv2.cvtColor(image_bgr, _cv2.COLOR_BGR2GRAY)
    blur = _cv2.GaussianBlur(gray, (5, 5), 0)
    if threshold and threshold > 0:
        _, thresh = _cv2.threshold(blur, int(threshold), 255, _cv2.THRESH_BINARY_INV)
    else:
        _, thresh = _cv2.threshold(blur, 0, 255, _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
    kernel = np.ones((3, 3), np.uint8)
    if use_open:
        thresh = _cv2.morphologyEx(thresh, _cv2.MORPH_OPEN, kernel, iterations=1)
    thresh = _cv2.morphologyEx(thresh, _cv2.MORPH_CLOSE, kernel, iterations=1)
    contours, _ = _cv2.findContours(thresh, _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_SIMPLE)
    result = []
    mask_buf = np.zeros(gray.shape, dtype=np.uint8)
    for cnt in contours:
        area = _cv2.contourArea(cnt)
        if area < area_min:
            continue
        perimeter = _cv2.arcLength(cnt, True)
        circ = (4 * np.pi * area / perimeter ** 2) if perimeter > 0 else 0
        hull = _cv2.convexHull(cnt)
        hull_area = _cv2.contourArea(hull)
        solidity = float(area / hull_area) if hull_area > 0 else 1.0
        mask_buf[:] = 0
        _cv2.drawContours(mask_buf, [cnt], -1, 255, -1)
        mean_val = float(_cv2.mean(gray, mask=mask_buf)[0])
        mean_bgr_p = _cv2.mean(image_bgr, mask=mask_buf)[:3]
        classification = classify_particle_material(mean_val, solidity, mean_bgr_p, circ)
        result.append({
            "contour": cnt, "circ": float(circ),
            "area_px": area, "diam_px": (4 * area / np.pi) ** 0.5,
            "solidity": solidity, "mean_val": mean_val,
            "classification": classification,
        })
    return result


def count_nodules(image_bgr, px_per_mm=None, threshold=0, min_area=None, use_open=True) -> dict | None:
    import numpy as np

    area_min = int(min_area) if min_area is not None else IMAGEJ_AREA_UMBRAL
    scale = float(px_per_mm) if px_per_mm else IMAGEJ_RESOLUCION_PX_MM
    h, w = image_bgr.shape[:2]
    analysis_area_mm2 = (w / scale) * (h / scale)

    contours_data = get_nodule_contours(image_bgr, threshold=threshold,
                                        min_area=area_min, use_open=use_open)
    if not contours_data:
        return None

    particles = []
    for cd in contours_data:
        diam_mm = float(np.sqrt((4 * cd["area_px"]) / np.pi) / scale)
        particles.append({
            "area": cd["area_px"],
            "circ": cd["circ"],
            "diam_mm": diam_mm,
            "mat": cd["classification"],
        })

    area_total = sum(p["area"] for p in particles)
    nod_area = sum(p["area"] for p in particles if p["circ"] >= 0.5)
    mat_counts: dict = {}
    for p in particles:
        mat_counts[p["mat"]] = mat_counts.get(p["mat"], 0) + 1

    counts: dict = {}
    for category, min_d, max_d in IMAGEJ_LIMITS:
        c = sum(1 for p in particles if min_d <= p["diam_mm"] <= max_d)
        if c:
            counts[category] = c
    fuera = sum(
        1 for p in particles
        if not any(min_d <= p["diam_mm"] <= max_d for _, min_d, max_d in IMAGEJ_LIMITS)
    )
    if fuera:
        counts["Fuera de clase"] = fuera

    diams = [p["diam_mm"] for p in particles]
    return {
        "n_total": len(particles),
        "n_mm2": round(len(particles) / analysis_area_mm2, 2),
        "nodularidad": round(nod_area / area_total * 100, 2) if area_total else 0,
        "vermicular": round((area_total - nod_area) / area_total * 100, 2) if area_total else 0,
        "diam_prom_um": round(float(np.mean(diams)) * 1000, 2),
        "diam_max_um": round(float(max(diams)) * 1000, 2),
        "diam_min_um": round(float(min(diams)) * 1000, 2),
        "counts": counts,
        "mat_counts": mat_counts,
        "tam_grafito_clase": imagej_majority_size_text(counts),
        "px_per_mm": round(scale, 4),
    }


def get_laminar_contours(image_bgr, threshold=0, min_area=100, blur_size=5, use_open=True) -> list:
    import numpy as np
    import cv2 as _cv2

    gray = _cv2.cvtColor(image_bgr, _cv2.COLOR_BGR2GRAY)
    k = blur_size if blur_size % 2 == 1 else blur_size + 1
    blur = _cv2.GaussianBlur(gray, (k, k), 0)
    if threshold > 0:
        _, thresh = _cv2.threshold(blur, threshold, 255, _cv2.THRESH_BINARY_INV)
    else:
        _, thresh = _cv2.threshold(blur, 0, 255, _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
    kernel = np.ones((2, 2), np.uint8)
    if use_open:
        thresh = _cv2.morphologyEx(thresh, _cv2.MORPH_OPEN, kernel, iterations=1)
    contours, _ = _cv2.findContours(thresh, _cv2.RETR_EXTERNAL, _cv2.CHAIN_APPROX_SIMPLE)
    result = []
    mask_buf = np.zeros(gray.shape, dtype=np.uint8)
    for cnt in contours:
        area = _cv2.contourArea(cnt)
        if area < min_area:
            continue
        perimeter = _cv2.arcLength(cnt, True)
        circ = (4 * np.pi * area / perimeter ** 2) if perimeter > 0 else 0
        rect = _cv2.minAreaRect(cnt)
        (_, _), (rw, rh), angle = rect
        length_px = float(max(rw, rh))
        width_px = float(min(rw, rh))
        if rw < rh:
            angle = angle + 90
        angle = float(angle % 180)
        aspect = length_px / max(width_px, 1.0)
        hull_area = _cv2.contourArea(_cv2.convexHull(cnt))
        solidity = float(area / hull_area) if hull_area > 0 else 1.0
        mask_buf[:] = 0
        _cv2.drawContours(mask_buf, [cnt], -1, 255, -1)
        mean_val = float(_cv2.mean(gray, mask=mask_buf)[0])
        mean_bgr_p = _cv2.mean(image_bgr, mask=mask_buf)[:3]
        classification = classify_particle_material(mean_val, solidity, mean_bgr_p, circ)
        ptype = "mns" if circ >= 0.5 and aspect < 2.0 else "graphite"
        result.append({
            "contour": cnt,
            "circ": float(circ),
            "length_px": length_px,
            "width_px": width_px,
            "aspect_ratio": float(aspect),
            "angle": angle,
            "area_px": float(area),
            "particle_type": ptype,
            "mean_val": mean_val,
            "solidity": solidity,
            "classification": classification,
        })
    return result


def classify_laminar_morphology(flakes) -> str:
    import numpy as np

    if not flakes:
        return "—"
    elongated = [f for f in flakes if f.get("aspect_ratio", 1) >= 2.0]
    if not elongated:
        return "D"
    lengths = [f["length_um"] for f in elongated]
    mean_len = float(np.mean(lengths))
    std_len = float(np.std(lengths))
    cv_len = std_len / mean_len if mean_len > 0 else 0
    norm_angles = [f["angle"] % 90 for f in elongated]
    std_angle = float(np.std(norm_angles)) if norm_angles else 90.0
    if mean_len > 400 or (mean_len > 150 and cv_len > 0.9):
        return "C"
    if std_angle < 18 and mean_len < 180:
        return "E"
    if mean_len < 35:
        return "D"
    if cv_len > 0.6 and 35 <= mean_len <= 200:
        return "B"
    return "A"


def count_laminar(image_bgr, px_per_mm=None, threshold=0, min_area=None, use_open=True) -> dict | None:
    import numpy as np

    area_min = int(min_area) if min_area is not None else IMAGEJ_AREA_UMBRAL
    scale = float(px_per_mm) if px_per_mm else IMAGEJ_RESOLUCION_PX_MM
    h, w = image_bgr.shape[:2]
    area_mm2 = (w / scale) * (h / scale)

    flakes = get_laminar_contours(image_bgr, threshold=threshold,
                                  min_area=area_min, use_open=use_open)
    MNS_MAX_DIAM_UM = 30.0
    for f in flakes:
        f["length_um"] = (f["length_px"] / scale) * 1000.0
        f["width_um"] = (f["width_px"] / scale) * 1000.0
        equiv_diam_um = 2.0 * (f["area_px"] / 3.14159) ** 0.5 / scale * 1000.0
        f["equiv_diam_um"] = equiv_diam_um
        if f["particle_type"] == "mns" and equiv_diam_um > MNS_MAX_DIAM_UM:
            f["particle_type"] = "graphite"

    graphite = [f for f in flakes if f["particle_type"] == "graphite"]
    mns = [f for f in flakes if f["particle_type"] == "mns"]

    if not graphite:
        return None

    n_total = len(graphite)
    n_mm2 = n_total / area_mm2 if area_mm2 > 0 else 0
    lengths = [f["length_um"] for f in graphite]

    counts: dict = {}
    for label, lo, hi in IMAGEJ_LIMITS:
        lo_um = lo * 1000
        hi_um = hi * 1000
        n = sum(1 for f in graphite if lo_um <= f["length_um"] < hi_um)
        if n:
            counts[label] = n
    fuera = sum(1 for f in graphite
                if not any(lo * 1000 <= f["length_um"] < hi * 1000
                            for _, lo, hi in IMAGEJ_LIMITS))
    if fuera:
        counts["Fuera de clase"] = fuera

    tam_clase = imagej_majority_size_text(counts)
    morph_type = classify_laminar_morphology(graphite)
    aspects = [f["aspect_ratio"] for f in graphite]
    n_mns = len(mns)
    n_mns_mm2 = n_mns / area_mm2 if area_mm2 > 0 else 0
    return {
        "n_total": n_total,
        "n_mm2": round(n_mm2, 2),
        "long_prom_um": round(float(np.mean(lengths)), 2),
        "long_max_um": round(float(np.max(lengths)), 2),
        "long_min_um": round(float(np.min(lengths)), 2),
        "aspect_ratio_prom": round(float(np.mean(aspects)), 2),
        "morfologia_iso": morph_type,
        "morfologia_label": _LAMINAR_MORPH_LABELS.get(morph_type, morph_type),
        "tam_clase": tam_clase,
        "counts": counts,
        "n_mns": n_mns,
        "n_mns_mm2": round(n_mns_mm2, 2),
        "px_per_mm": round(scale, 4),
        "flakes": flakes,
    }


def imagej_class_code(label: str) -> str:
    match = re.search(r"Clase\s+(\d+)", str(label or ""))
    return match.group(1) if match else str(label or "").strip()


def imagej_majority_size_text(counts: dict) -> str:
    class_counts = [
        (idx, label, int(round(float(counts.get(label, 0) or 0))))
        for idx, (label, _, _) in enumerate(IMAGEJ_LIMITS)
        if float(counts.get(label, 0) or 0) > 0
    ]
    if not class_counts:
        return ""
    total = sum(count for _, _, count in class_counts)
    ordered = sorted(class_counts, key=lambda item: (-item[2], item[0]))
    selected = [ordered[0]]
    if len(ordered) > 1:
        top_count = ordered[0][2]
        second = ordered[1]
        second_ratio = second[2] / total if total else 0
        close_to_top = second[2] >= (top_count * 0.5)
        if second_ratio >= 0.20 or close_to_top:
            selected.append(second)
    selected = sorted(selected, key=lambda item: item[0])
    return "-".join(imagej_class_code(label) for _, label, _ in selected)


def draw_nodule_overlay(image_bgr, contours_data):
    import cv2 as _cv2
    out = image_bgr.copy()
    COLOR_NOD = (0, 220, 80)
    COLOR_MNS = (255, 200, 0)
    COLOR_RECHUPE = (0, 60, 220)
    color_map = {"C": COLOR_NOD, "MnS": COLOR_MNS, "rechupe": COLOR_RECHUPE}
    for cd in contours_data:
        color = color_map.get(cd.get("classification", "C"), COLOR_NOD)
        _cv2.drawContours(out, [cd["contour"]], -1, color, 2)
    return out


def draw_laminar_overlay(image_bgr, flakes):
    import cv2 as _cv2
    out = image_bgr.copy()
    COLOR_GRAPH = (0, 220, 80)
    COLOR_MNS = (255, 200, 0)
    COLOR_RECHUPE = (0, 60, 220)
    for f in flakes:
        if f.get("particle_type") == "mns":
            color = COLOR_MNS
        elif f.get("classification") == "rechupe":
            color = COLOR_RECHUPE
        else:
            color = COLOR_GRAPH
        _cv2.drawContours(out, [f["contour"]], -1, color, 2)
    return out


def get_binary_image(image_bgr, threshold=0, use_open=True):
    import numpy as np
    import cv2 as _cv2
    gray = _cv2.cvtColor(image_bgr, _cv2.COLOR_BGR2GRAY)
    blur = _cv2.GaussianBlur(gray, (5, 5), 0)
    if threshold and threshold > 0:
        _, thresh = _cv2.threshold(blur, int(threshold), 255, _cv2.THRESH_BINARY_INV)
    else:
        _, thresh = _cv2.threshold(blur, 0, 255, _cv2.THRESH_BINARY_INV + _cv2.THRESH_OTSU)
    kernel = np.ones((3, 3), np.uint8)
    if use_open:
        thresh = _cv2.morphologyEx(thresh, _cv2.MORPH_OPEN, kernel, iterations=1)
    return _cv2.cvtColor(thresh, _cv2.COLOR_GRAY2BGR)
