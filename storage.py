# storage.py
import os
import json

# Archivos de datos (catálogo e históricos) en la carpeta del usuario
ALLOYS_FILE  = os.path.join(os.path.expanduser("~"), "ajuste_comp_catalogo.json")
HISTORY_FILE = os.path.join(os.path.expanduser("~"), "ajuste_comp_history.json")


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
    hist.append(session)
    _atomic_write(HISTORY_FILE, hist)


def save_history(history_list):
    _atomic_write(HISTORY_FILE, history_list or [])


def update_session(index, session_obj):
    hist = load_history()
    if 0 <= index < len(hist):
        hist[index] = session_obj
        save_history(hist)


def delete_session(index):
    hist = load_history()
    if 0 <= index < len(hist):
        del hist[index]
        save_history(hist)


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
