# storage.py
import os
import json
import re

# Archivos de datos (catálogo e históricos) en la carpeta del usuario
ALLOYS_FILE  = os.path.join(os.path.expanduser("~"), "ajuste_comp_catalogo.json")
HISTORY_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_history.json")
QUALITY_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_quality_reports.json")
QUALITY_IMAGES_DIR = os.path.join(os.path.expanduser("~"), "ajuste_comp_quality_images")
FURNACE_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_pie_horno.json")
LADLES_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_cucharas.json")
DEVICES_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_devices.json")
THERMAL_DEVICE_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_thermal_device.json")
COLADA_KEY_RE = re.compile(r"^\s*(\d+)\s*/\s*(\d{2})(?:\s*-\s*.*)?\s*$")


class DuplicateColadaError(ValueError):
    pass


def _atomic_write(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)
    os.replace(tmp, path)


# ---------- Catálogo ----------
def load_alloys():
    if not os.path.exists(ALLOYS_FILE):
        return []
    with open(ALLOYS_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []


def save_alloys(alloys):
    _atomic_write(ALLOYS_FILE, alloys or [])


# ---------- Históricos ----------
def load_history():
    if not os.path.exists(HISTORY_FILE):
        return []
    with open(HISTORY_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []


def append_history(session):
    hist = load_history()
    _ensure_unique_history_colada(hist, session)
    hist.append(session)
    _atomic_write(HISTORY_FILE, hist)


def save_history(history_list):
    _atomic_write(HISTORY_FILE, history_list or [])


def update_session(index, session_obj):
    hist = load_history()
    if 0 <= index < len(hist):
        _ensure_unique_history_colada(hist, session_obj, ignore_index=index)
        hist[index] = session_obj
        save_history(hist)


def delete_session(index):
    hist = load_history()
    if 0 <= index < len(hist):
        session = hist[index]
        del hist[index]
        save_history(hist)
        delete_ladles_for_colada(session.get("colada", ""))


def update_adjustment(session_index, adj_index, new_adj):
    hist = load_history()
    if 0 <= session_index < len(hist):
        ajustes = hist[session_index].get("ajustes", [])
        if 0 <= adj_index < len(ajustes):
            ajustes[adj_index] = new_adj
            hist[session_index]["ajustes"] = ajustes
            save_history(hist)


def delete_adjustment(session_index, adj_index):
    hist = load_history()
    if 0 <= session_index < len(hist):
        ajustes = hist[session_index].get("ajustes", [])
        if 0 <= adj_index < len(ajustes):
            del ajustes[adj_index]
            hist[session_index]["ajustes"] = ajustes
            save_history(hist)


def attach_thermal_analysis(colada, analysis_obj):
    key = normalize_colada_key(colada)
    if not key:
        raise ValueError("Colada vacia.")
    hist = load_history()
    for index, session in enumerate(hist):
        if normalize_colada_key((session or {}).get("colada", "")) != key:
            continue
        analyses = session.get("thermal_analysis", [])
        if not isinstance(analyses, list):
            analyses = []
        analyses.append(analysis_obj)
        session["thermal_analysis"] = analyses
        hist[index] = session
        save_history(hist)
        return index
    raise ValueError(f"No existe una sesion historica para la colada {key}.")


# ---------- Cache analisis termico del dispositivo ----------
def load_thermal_device_records():
    if not os.path.exists(THERMAL_DEVICE_FILE):
        return []
    with open(THERMAL_DEVICE_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            return []
    return data if isinstance(data, list) else []


def save_thermal_device_records(records):
    _atomic_write(THERMAL_DEVICE_FILE, records or [])


# ---------- Informes de calidad ----------
def load_quality_reports():
    if not os.path.exists(QUALITY_FILE):
        return []
    with open(QUALITY_FILE, "r", encoding="utf-8") as f:
        try:
            return json.load(f)
        except Exception:
            return []


def save_quality_reports(reports):
    _atomic_write(QUALITY_FILE, reports or [])


def ensure_quality_images_dir():
    os.makedirs(QUALITY_IMAGES_DIR, exist_ok=True)
    return QUALITY_IMAGES_DIR


# ---------- Estado pie de horno ----------
def _empty_furnace_state():
    return {
        "updated_at": None,
        "ajuste": {
            "colada": "",
            "material_objetivo": "",
            "hora_actual": "",
            "ce_formula": "",
            "ce_actual": None,
            "ce_estimado": None,
            "materiales": [],
            "composicion_actual": [],
            "composicion_estimada": [],
        },
    }


def load_furnace_state():
    if not os.path.exists(FURNACE_FILE):
        return _empty_furnace_state()
    with open(FURNACE_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            return _empty_furnace_state()
    if not isinstance(data, dict):
        return _empty_furnace_state()
    out = _empty_furnace_state()
    out.update(data)
    ajuste = data.get("ajuste", {})
    if isinstance(ajuste, dict):
        out["ajuste"].update(ajuste)
    return out


def save_furnace_state(state):
    base = _empty_furnace_state()
    if isinstance(state, dict):
        base.update(state)
        ajuste = state.get("ajuste", {})
        if isinstance(ajuste, dict):
            base["ajuste"].update(ajuste)
    _atomic_write(FURNACE_FILE, base)


def clear_furnace_state():
    _atomic_write(FURNACE_FILE, _empty_furnace_state())


# ---------- Conteo de cucharas ----------
def _empty_ladles_state():
    return {
        "updated_at": None,
        "current": {
            "colada": "",
            "material_objetivo": "",
            "counts": {},
            "events": {},
        },
        "history_by_colada": {},
    }


def load_ladles_state():
    if not os.path.exists(LADLES_FILE):
        return _empty_ladles_state()
    with open(LADLES_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            return _empty_ladles_state()
    if not isinstance(data, dict):
        return _empty_ladles_state()
    out = _empty_ladles_state()
    out.update(data)
    if not isinstance(out.get("current"), dict):
        out["current"] = {"colada": "", "material_objetivo": "", "counts": {}, "events": {}}
    if not isinstance(out["current"].get("counts"), dict):
        out["current"]["counts"] = {}
    if not isinstance(out["current"].get("events"), dict):
        out["current"]["events"] = {}
    if not isinstance(out.get("history_by_colada"), dict):
        out["history_by_colada"] = {}
    return out


def save_ladles_state(state):
    base = _empty_ladles_state()
    if isinstance(state, dict):
        base.update(state)
        if not isinstance(base.get("current"), dict):
            base["current"] = {"colada": "", "material_objetivo": "", "counts": {}, "events": {}}
        if not isinstance(base["current"].get("counts"), dict):
            base["current"]["counts"] = {}
        if not isinstance(base["current"].get("events"), dict):
            base["current"]["events"] = {}
        if not isinstance(base.get("history_by_colada"), dict):
            base["history_by_colada"] = {}
    _atomic_write(LADLES_FILE, base)


def normalize_colada_key(value):
    text = str(value or "").strip()
    match = COLADA_KEY_RE.match(text)
    if not match:
        return text
    return f"{int(match.group(1)):04d} /{str(match.group(2)).zfill(2)}"


def _ensure_unique_history_colada(history, session, ignore_index=None):
    key = normalize_colada_key((session or {}).get("colada", ""))
    if not key:
        return
    for idx, item in enumerate(history or []):
        if ignore_index is not None and idx == ignore_index:
            continue
        if normalize_colada_key((item or {}).get("colada", "")) == key:
            raise DuplicateColadaError(f"Ya existe una sesion guardada para la colada {key}.")


def delete_ladles_for_colada(colada):
    key = normalize_colada_key(colada)
    if not key:
        return False
    state = load_ladles_state()
    history = state.get("history_by_colada", {})
    if not isinstance(history, dict):
        history = {}
    removed = False
    for candidate in {key, str(colada or "").strip()}:
        if candidate and candidate in history:
            history.pop(candidate, None)
            removed = True
    current = state.get("current", {}) if isinstance(state.get("current", {}), dict) else {}
    if normalize_colada_key(current.get("colada", "")) == key:
        current["counts"] = {}
        current["events"] = {}
        state["current"] = current
        removed = True
    if removed:
        state["history_by_colada"] = history
        save_ladles_state(state)
    return removed


def prune_ladles_history_for_sessions(sessions):
    valid_keys = {
        normalize_colada_key((session or {}).get("colada", ""))
        for session in (sessions or [])
        if normalize_colada_key((session or {}).get("colada", ""))
    }
    state = load_ladles_state()
    history = state.get("history_by_colada", {})
    if not isinstance(history, dict) or not history:
        return 0
    removed = 0
    for key in list(history.keys()):
        if normalize_colada_key(key) not in valid_keys:
            history.pop(key, None)
            removed += 1
    if removed:
        state["history_by_colada"] = history
        save_ladles_state(state)
    return removed


# ---------- Dispositivos Pie de Horno ----------
def _empty_devices_state():
    return {
        "devices": {},
    }


def load_devices_state():
    if not os.path.exists(DEVICES_FILE):
        return _empty_devices_state()
    with open(DEVICES_FILE, "r", encoding="utf-8") as f:
        try:
            data = json.load(f)
        except Exception:
            return _empty_devices_state()
    if not isinstance(data, dict):
        return _empty_devices_state()
    out = _empty_devices_state()
    devices = data.get("devices", {})
    out["devices"] = devices if isinstance(devices, dict) else {}
    return out


def save_devices_state(state):
    base = _empty_devices_state()
    if isinstance(state, dict) and isinstance(state.get("devices"), dict):
        base["devices"] = state["devices"]
    _atomic_write(DEVICES_FILE, base)
