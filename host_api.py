import json
import mimetypes
import re
import socket
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from datetime import datetime
from urllib.parse import parse_qs, urlparse

from storage import (
    load_alloys,
    load_devices_state,
    load_furnace_state,
    load_ladles_state,
    save_furnace_state,
    save_devices_state,
    save_ladles_state,
)


HOST_API_HOST = "0.0.0.0"
HOST_API_PORT = 8765
HOST_API_PUBLIC_PORT = 50500
CURRENT_HOST_API_PORT = HOST_API_PORT
WEB_DIR = Path(__file__).resolve().parent / "web"
MAX_JSON_BODY_BYTES = 32 * 1024
MAX_CUCHARAMATERIALS = 200
MAX_CUCHARAS_COUNT = 9999
DEVICE_ID_RE = re.compile(r"^[A-Za-z0-9_.:-]{8,80}$")
DEVICE_NAME_MAX_LEN = 80
EVENT_KEEPALIVE_SECONDS = 25
DEVICE_ROLES = ("viewer", "editor")

_EVENT_CONDITION = threading.Condition()
_DATA_VERSION = 0


class CucharasContextError(ValueError):
    pass


def notify_data_changed():
    global _DATA_VERSION
    with _EVENT_CONDITION:
        _DATA_VERSION += 1
        _EVENT_CONDITION.notify_all()


def get_host_api_port():
    return int(CURRENT_HOST_API_PORT)


def _local_ip():
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        try:
            sock.close()
        except Exception:
            pass


def _sorted_codes(values):
    unique = []
    seen = set()
    for value in values:
        text = str(value or "").strip()
        if not text or text in seen:
            continue
        seen.add(text)
        unique.append(text)
    return sorted(unique, key=lambda val: (0, int(val)) if str(val).isdigit() else (1, str(val).lower()))


def _ladle_material_options(material_objetivo):
    target = str(material_objetivo or "").strip()
    if not target:
        return []
    options = []
    for alloy in load_alloys():
        meta = alloy.get("calidad_meta", {}) if isinstance(alloy, dict) else {}
        if not isinstance(meta, dict) or not meta.get("es_material_final"):
            continue
        bases = [str(base).strip() for base in (meta.get("bases") or []) if str(base).strip()]
        if target not in bases:
            continue
        code = str(meta.get("codigo") or alloy.get("nombre", "")).strip()
        if code:
            options.append(code)
    return _sorted_codes(options)


def _cucharas_payload_for(material_objetivo):
    target = str(material_objetivo or "").strip()
    stored = load_ladles_state()
    current = stored.get("current", {}) if isinstance(stored.get("current", {}), dict) else {}
    counts_raw = current.get("counts", {}) if target else {}
    if not isinstance(counts_raw, dict):
        counts_raw = {}
    materials = _ladle_material_options(target)
    rows = []
    total = 0
    for code in materials:
        try:
            count = max(0, int(counts_raw.get(code, 0)))
        except Exception:
            count = 0
        total += count
        rows.append({"material_final": code, "cantidad": count})
    return {
        "colada": str(current.get("colada", "")).strip(),
        "material_objetivo": target,
        "rows": rows,
        "total_cucharas": total,
        "updated_at": stored.get("updated_at"),
    }


def _host_context(payload):
    ajuste = payload.get("ajuste", {}) if isinstance(payload, dict) else {}
    if not isinstance(ajuste, dict):
        ajuste = {}
    return {
        "colada": str(ajuste.get("colada", "")).strip(),
        "material_objetivo": str(ajuste.get("material_objetivo", "")).strip(),
    }


def _default_ladles_state():
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


def _normalize_ladles_state(state):
    base = _default_ladles_state()
    if isinstance(state, dict):
        base.update(state)
    current = base.get("current", {})
    if not isinstance(current, dict):
        current = {}
    clean_current = {
        "colada": str(current.get("colada", "")).strip(),
        "material_objetivo": str(current.get("material_objetivo", "")).strip(),
        "counts": current.get("counts", {}) if isinstance(current.get("counts", {}), dict) else {},
        "events": current.get("events", {}) if isinstance(current.get("events", {}), dict) else {},
    }
    base["current"] = clean_current
    if not isinstance(base.get("history_by_colada"), dict):
        base["history_by_colada"] = {}
    return base


def _event_time(event):
    if isinstance(event, dict):
        return str(event.get("saved_at", "") or "")
    return str(event or "")


def _event_list(raw):
    if not isinstance(raw, list):
        return []
    out = []
    for item in raw:
        if isinstance(item, dict):
            saved_at = str(item.get("saved_at", "") or "")
        else:
            saved_at = str(item or "")
        if saved_at:
            out.append({"saved_at": saved_at})
    return out


def _counts_from_events(events, valid_materials=None):
    if not isinstance(events, dict):
        return {}
    valid = set(valid_materials or [])
    out = {}
    for code, values in events.items():
        key = str(code or "").strip()
        if not key or (valid and key not in valid):
            continue
        out[key] = len(_event_list(values))
    return out


def _normalize_events_for_counts(events, counts, fallback_time):
    normalized = {}
    for code, qty in (counts or {}).items():
        key = str(code or "").strip()
        if not key:
            continue
        try:
            count = max(0, int(qty))
        except Exception:
            count = 0
        existing = _event_list((events or {}).get(key, []))
        if len(existing) > count:
            existing = existing[:count]
        while len(existing) < count:
            existing.append({"saved_at": fallback_time or _now_iso()})
        normalized[key] = existing
    return normalized


def _parse_iso(value):
    text = str(value or "").strip()
    if not text:
        return None
    try:
        return datetime.fromisoformat(text)
    except Exception:
        return None


def _duration_label(seconds):
    try:
        total = max(0, int(seconds))
    except Exception:
        total = 0
    hours, rem = divmod(total, 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h {minutes:02d}m"
    if minutes:
        return f"{minutes}m {secs:02d}s"
    return f"{secs}s"


def _statistics_from_events(events, materials):
    rows = []
    all_times = []
    for code in materials:
        items = _event_list((events or {}).get(code, []))
        times = [_event_time(item) for item in items if _event_time(item)]
        parsed = [dt for dt in (_parse_iso(value) for value in times) if dt is not None]
        first = min(parsed).isoformat(timespec="seconds") if parsed else ""
        last = max(parsed).isoformat(timespec="seconds") if parsed else ""
        duration_seconds = int((max(parsed) - min(parsed)).total_seconds()) if len(parsed) >= 2 else 0
        all_times.extend(parsed)
        rows.append({
            "material_final": code,
            "total": len(items),
            "first_saved_at": first,
            "last_saved_at": last,
            "duration_seconds": duration_seconds,
            "duration_label": _duration_label(duration_seconds) if len(parsed) >= 2 else "",
        })
    total_duration = int((max(all_times) - min(all_times)).total_seconds()) if len(all_times) >= 2 else 0
    return {
        "rows": rows,
        "total_cucharas": sum(row["total"] for row in rows),
        "first_saved_at": min(all_times).isoformat(timespec="seconds") if all_times else "",
        "last_saved_at": max(all_times).isoformat(timespec="seconds") if all_times else "",
        "duration_seconds": total_duration,
        "duration_label": _duration_label(total_duration) if len(all_times) >= 2 else "",
    }


def _sync_ladles_current_with_host(state, host_payload):
    out = _normalize_ladles_state(state)
    current = out["current"]
    host_ctx = _host_context(host_payload)
    changed = False
    if not current.get("colada") and host_ctx["colada"]:
        current["colada"] = host_ctx["colada"]
        changed = True
    if not current.get("material_objetivo") and host_ctx["material_objetivo"]:
        current["material_objetivo"] = host_ctx["material_objetivo"]
        changed = True
    out["current"] = current
    return out, changed


def _cucharas_payload_from_state(state):
    normalized = _normalize_ladles_state(state)
    current = normalized["current"]
    target = current.get("material_objetivo", "")
    colada = current.get("colada", "")
    materials = _ladle_material_options(target)
    counts_raw = current.get("counts", {})
    events = _normalize_events_for_counts(
        current.get("events", {}),
        counts_raw,
        normalized.get("updated_at") or _now_iso(),
    )
    history_by_colada = normalized.get("history_by_colada", {})
    saved_record = history_by_colada.get(colada, {}) if isinstance(history_by_colada, dict) else {}
    if isinstance(saved_record, list):
        saved_count = len(saved_record)
        last_saved_at = saved_record[-1].get("saved_at", "") if saved_record else ""
    elif isinstance(saved_record, dict):
        saved_count = sum(_counts_from_events(saved_record.get("events", {}), materials).values())
        last_saved_at = str(saved_record.get("updated_at", "") or "")
    else:
        saved_count = 0
        last_saved_at = ""
    rows = []
    total = 0
    for code in materials:
        try:
            count = max(0, int(len(events.get(code, []))))
        except Exception:
            count = 0
        total += count
        rows.append({"material_final": code, "cantidad": count})
    return {
        "colada": colada,
        "material_objetivo": target,
        "rows": rows,
        "total_cucharas": total,
        "updated_at": normalized.get("updated_at"),
        "statistics": _statistics_from_events(events, materials),
        "saved_count": saved_count,
        "already_saved": saved_count > 0,
        "last_saved_at": last_saved_at,
    }


def build_host_payload():
    payload = load_furnace_state()
    ladles = load_ladles_state()
    ladles, changed = _sync_ladles_current_with_host(ladles, payload)
    if changed:
        save_ladles_state(ladles)
    payload["cucharas"] = _cucharas_payload_from_state(ladles)
    return payload


def _clamp_percent(value, default=100):
    try:
        pct = int(round(float(value)))
    except Exception:
        pct = int(default)
    return max(0, min(100, pct))


def _normalize_furnace_material_rows(rows):
    out = []
    if not isinstance(rows, list):
        return out
    for row in rows:
        if not isinstance(row, dict):
            continue
        name = str(row.get("nombre", "") or "").strip()
        if not name:
            continue
        try:
            kg = round(float(row.get("kg", 0) or 0), 3)
        except Exception:
            kg = 0.0
        if kg <= 0:
            continue
        pct = _clamp_percent(row.get("porcentaje_horno", 100), default=100)
        kg_horno = round(kg * pct / 100.0, 3)
        out.append({
            "nombre": name,
            "kg": kg,
            "porcentaje_horno": pct,
            "kg_horno": kg_horno,
        })
    return out


def save_furnace_material_confirmation(rows, general_pct=None):
    state = load_furnace_state()
    ajuste = state.get("ajuste", {}) if isinstance(state, dict) else {}
    if not isinstance(ajuste, dict):
        ajuste = {}
    current_rows = _normalize_furnace_material_rows(ajuste.get("materiales", []))
    if not current_rows:
        return build_host_payload()

    pct_map = {}
    for row in rows or []:
        if not isinstance(row, dict):
            continue
        name = str(row.get("nombre", "") or "").strip()
        if not name:
            continue
        pct_map[name] = _clamp_percent(row.get("porcentaje_horno", 100), default=100)

    shared_pct = None if general_pct is None else _clamp_percent(general_pct, default=100)
    updated_rows = []
    for row in current_rows:
        pct = pct_map.get(row["nombre"], shared_pct if shared_pct is not None else row.get("porcentaje_horno", 100))
        pct = _clamp_percent(pct, default=100)
        kg = round(float(row.get("kg", 0) or 0), 3)
        updated_rows.append({
            "nombre": row["nombre"],
            "kg": kg,
            "porcentaje_horno": pct,
            "kg_horno": round(kg * pct / 100.0, 3),
        })

    confirmed_at = _now_iso()
    ajuste["materiales"] = updated_rows
    ajuste["porcentaje_general_horno"] = (
        shared_pct if shared_pct is not None else _clamp_percent(ajuste.get("porcentaje_general_horno", 100), default=100)
    )
    ajuste["materiales_confirmados"] = True
    ajuste["confirmado_at"] = confirmed_at
    state["updated_at"] = confirmed_at
    state["ajuste"] = ajuste
    save_furnace_state(state)
    notify_data_changed()
    return build_host_payload()


def _persist_cucharas_events(state, current, target, valid_materials, events, saved_at, host_payload):
    clean_counts = _counts_from_events(events, valid_materials)
    history_by_colada = state.get("history_by_colada", {})
    if not isinstance(history_by_colada, dict):
        history_by_colada = {}
    colada_key = str(current.get("colada", "")).strip()
    if colada_key:
        history_by_colada[colada_key] = {
            "updated_at": saved_at,
            "colada": colada_key,
            "material_objetivo": target,
            "counts": clean_counts,
            "events": events,
            "statistics": _statistics_from_events(events, _sorted_codes(valid_materials)),
        }
    state["history_by_colada"] = history_by_colada

    host_ctx = _host_context(host_payload)
    current["counts"] = clean_counts
    current["events"] = events
    if host_ctx["colada"] and (host_ctx["colada"] != current.get("colada") or host_ctx["material_objetivo"] != current.get("material_objetivo")):
        current = {
            "colada": host_ctx["colada"],
            "material_objetivo": host_ctx["material_objetivo"],
            "counts": {},
            "events": {},
        }
    state["current"] = current
    state["updated_at"] = saved_at
    save_ladles_state(state)
    notify_data_changed()
    return _cucharas_payload_from_state(state)


def save_cuchara_delta(material, delta):
    host_payload = load_furnace_state()
    state, changed = _sync_ladles_current_with_host(load_ladles_state(), host_payload)
    current = state["current"]
    target = current.get("material_objetivo", "")
    valid_materials = set(_ladle_material_options(target))
    code = str(material or "").strip()
    if code not in valid_materials:
        return _cucharas_payload_from_state(state)
    try:
        step = int(delta)
    except Exception:
        step = 0
    if step < -100:
        step = -100
    if step > 100:
        step = 100
    saved_at = datetime.now().isoformat(timespec="seconds")
    old_counts = current.get("counts", {}) if isinstance(current.get("counts", {}), dict) else {}
    events = _normalize_events_for_counts(current.get("events", {}), old_counts, state.get("updated_at") or saved_at)
    current_events = events.setdefault(code, [])
    if step > 0:
        for _ in range(step):
            current_events.append({"saved_at": saved_at})
    elif step < 0:
        del current_events[max(0, len(current_events) + step):]
    return _persist_cucharas_events(state, current, target, valid_materials, events, saved_at, host_payload)


def save_cucharas_for(counts):
    host_payload = load_furnace_state()
    state, changed = _sync_ladles_current_with_host(load_ladles_state(), host_payload)
    current = state["current"]
    target = current.get("material_objetivo", "")
    valid_materials = set(_ladle_material_options(target))
    clean_counts = {}
    for key, value in (counts or {}).items():
        code = str(key or "").strip()
        if code not in valid_materials:
            continue
        try:
            qty = max(0, int(value))
        except Exception:
            qty = 0
        clean_counts[code] = qty
    saved_at = datetime.now().isoformat(timespec="seconds")
    old_counts = current.get("counts", {}) if isinstance(current.get("counts", {}), dict) else {}
    events = _normalize_events_for_counts(current.get("events", {}), old_counts, state.get("updated_at") or saved_at)
    for code in _sorted_codes(valid_materials):
        old_qty = len(events.get(code, []))
        new_qty = clean_counts.get(code, 0)
        if new_qty > old_qty:
            events.setdefault(code, [])
            for _ in range(new_qty - old_qty):
                events[code].append({"saved_at": saved_at})
        elif new_qty < old_qty:
            events[code] = events.get(code, [])[:new_qty]
    return _persist_cucharas_events(state, current, target, valid_materials, events, saved_at, host_payload)


def start_cucharas_count():
    host_payload = load_furnace_state()
    state, changed = _sync_ladles_current_with_host(load_ladles_state(), host_payload)
    host_ctx = _host_context(host_payload)
    current = state.get("current", {}) if isinstance(state.get("current", {}), dict) else {}
    colada = host_ctx["colada"]
    target = host_ctx["material_objetivo"]
    if not colada or not target:
        raise CucharasContextError("missing_ajuste_context")
    valid_materials = _sorted_codes(_ladle_material_options(target))

    state["current"] = {
        "colada": colada,
        "material_objetivo": target,
        "counts": {code: 0 for code in valid_materials},
        "events": {code: [] for code in valid_materials},
    }
    history_by_colada = state.get("history_by_colada", {})
    if isinstance(history_by_colada, dict) and colada:
        history_by_colada.pop(colada, None)
        state["history_by_colada"] = history_by_colada
    state["updated_at"] = datetime.now().isoformat(timespec="seconds")
    save_ladles_state(state)
    notify_data_changed()
    return _cucharas_payload_from_state(state)


def save_cucharas_current():
    host_payload = load_furnace_state()
    state, changed = _sync_ladles_current_with_host(load_ladles_state(), host_payload)
    current = state.get("current", {}) if isinstance(state.get("current", {}), dict) else {}
    target = str(current.get("material_objetivo", "") or "").strip()
    valid_materials = set(_ladle_material_options(target))
    saved_at = datetime.now().isoformat(timespec="seconds")
    old_counts = current.get("counts", {}) if isinstance(current.get("counts", {}), dict) else {}
    events = _normalize_events_for_counts(current.get("events", {}), old_counts, state.get("updated_at") or saved_at)
    return _persist_cucharas_events(state, current, target, valid_materials, events, saved_at, host_payload)


def _is_valid_counts(counts):
    if not isinstance(counts, dict) or len(counts) > MAX_CUCHARAMATERIALS:
        return False
    for key, value in counts.items():
        if not isinstance(key, str) or len(key) > 120:
            return False
        try:
            qty = int(value)
        except Exception:
            return False
        if qty < 0 or qty > MAX_CUCHARAS_COUNT:
            return False
    return True


def _is_valid_delta_payload(payload):
    if not isinstance(payload, dict):
        return False
    material = str(payload.get("material_final") or payload.get("material") or "").strip()
    if not material or len(material) > 120:
        return False
    try:
        delta = int(payload.get("delta", 0))
    except Exception:
        return False
    return -100 <= delta <= 100 and delta != 0


def _now_iso():
    return datetime.now().isoformat(timespec="seconds")


def _safe_device_name(value):
    text = str(value or "").strip()
    text = " ".join(text.split())
    return text[:DEVICE_NAME_MAX_LEN] or "Dispositivo sin nombre"


def _valid_device_id(device_id):
    return bool(DEVICE_ID_RE.match(str(device_id or "").strip()))


def register_or_touch_device(device_id, name="", user_agent="", ip=""):
    device_id = str(device_id or "").strip()
    if not _valid_device_id(device_id):
        return None

    state = load_devices_state()
    devices = state.get("devices", {})
    if not isinstance(devices, dict):
        devices = {}

    now = _now_iso()
    current = devices.get(device_id, {})
    if not isinstance(current, dict):
        current = {}

    status = current.get("status") or "pending"
    if status not in ("pending", "approved", "revoked"):
        status = "pending"
    role = current.get("role") or "viewer"
    if role not in DEVICE_ROLES:
        role = "viewer"

    current.update({
        "id": device_id,
        "name": _safe_device_name(name or current.get("name")),
        "status": status,
        "role": role,
        "first_seen": current.get("first_seen") or now,
        "last_seen": now,
        "ip": str(ip or "")[:80],
        "user_agent": str(user_agent or "")[:240],
    })
    devices[device_id] = current
    state["devices"] = devices
    save_devices_state(state)
    return current


def get_device(device_id):
    device_id = str(device_id or "").strip()
    if not _valid_device_id(device_id):
        return None
    state = load_devices_state()
    devices = state.get("devices", {})
    if not isinstance(devices, dict):
        return None
    current = devices.get(device_id)
    return current if isinstance(current, dict) else None


class _HostAPIHandler(BaseHTTPRequestHandler):
    server_version = "AjusteCompHost/1.0"

    def log_message(self, format, *args):
        return

    def _send_json(self, payload, status=200):
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _send_device_error(self, status="pending"):
        self._send_json({
            "ok": False,
            "error": "device_not_approved",
            "status": status or "pending",
            "message": "Este dispositivo debe aprobarse desde la pestana PIE DE HORNO del host.",
        }, status=403)

    def _request_path(self):
        return urlparse(self.path).path

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def _device_headers(self):
        query = self._query()
        device_id = str(self.headers.get("X-Pie-Device-Id", "") or (query.get("device_id") or [""])[0]).strip()
        device_name = str(self.headers.get("X-Pie-Device-Name", "") or (query.get("name") or [""])[0]).strip()
        return device_id, device_name

    def _client_ip(self):
        try:
            forwarded = str(self.headers.get("X-Forwarded-For", "") or "").split(",")[0].strip()
            if forwarded:
                return forwarded
            return str(self.client_address[0])
        except Exception:
            return ""

    def _device_auth_status(self):
        device = self._device_auth_device()
        if not device:
            return "unknown"
        return str(device.get("status") or "pending")

    def _device_auth_device(self):
        device_id, device_name = self._device_headers()
        return register_or_touch_device(
            device_id,
            device_name,
            self.headers.get("User-Agent", ""),
            self._client_ip(),
        )

    def _can_edit_cucharas(self, device):
        return (
            isinstance(device, dict)
            and device.get("status") == "approved"
            and device.get("role") == "editor"
        )

    def _send_bytes(self, body, content_type, status=200):
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        try:
            length = int(self.headers.get("Content-Length", "0") or "0")
        except Exception:
            length = 0
        if length < 0 or length > MAX_JSON_BODY_BYTES:
            return None
        raw = self.rfile.read(length) if length > 0 else b"{}"
        try:
            data = json.loads(raw.decode("utf-8"))
        except Exception:
            return None
        return data if isinstance(data, dict) else None

    def _serve_file(self, path):
        try:
            raw = path.read_bytes()
        except Exception:
            self._send_json({"ok": False, "error": "not_found"}, status=404)
            return
        content_type, _ = mimetypes.guess_type(str(path))
        self._send_bytes(raw, content_type or "application/octet-stream")

    def _serve_events(self):
        status = self._device_auth_status()
        if status != "approved":
            self._send_device_error(status)
            return

        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Connection", "keep-alive")
        self.end_headers()

        last_version = -1
        try:
            self.wfile.write(b"event: ready\ndata: {}\n\n")
            self.wfile.flush()
            while True:
                with _EVENT_CONDITION:
                    current = _DATA_VERSION
                    if current == last_version:
                        _EVENT_CONDITION.wait(timeout=EVENT_KEEPALIVE_SECONDS)
                    current = _DATA_VERSION

                if current != last_version:
                    payload = json.dumps({"version": current, "ts": time.time()})
                    self.wfile.write(f"event: refresh\ndata: {payload}\n\n".encode("utf-8"))
                    last_version = current
                else:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except Exception:
            return

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type, X-Pie-Device-Id, X-Pie-Device-Name")
        self.end_headers()

    def do_GET(self):
        path = self._request_path()
        if path in ("/", "/index.html"):
            self._serve_file(WEB_DIR / "index.html")
            return
        if path == "/static/app.css":
            self._serve_file(WEB_DIR / "app.css")
            return
        if path == "/static/app.js":
            self._serve_file(WEB_DIR / "app.js")
            return
        if path in ("/api/events", "/api/events/"):
            self._serve_events()
            return
        if path in ("/api/health", "/api/health/"):
            listen_port = ""
            try:
                listen_port = int(self.server.server_address[1])
            except Exception:
                listen_port = get_host_api_port()
            self._send_json({
                "ok": True,
                "service": "ajuste_comp_host",
                "listen_host": HOST_API_HOST,
                "listen_port": listen_port,
                "local_ip": _local_ip(),
                "auth_required": True,
                "auth_mode": "device_approval",
            })
            return
        if path in ("/api/device/status", "/api/device/status/"):
            device_id, _ = self._device_headers()
            device = get_device(device_id)
            self._send_json({
                "ok": True,
                "status": str((device or {}).get("status") or "unknown"),
                "role": str((device or {}).get("role") or "viewer"),
                "device_id": str(device_id or ""),
            })
            return
        if path in ("/api/pie-horno", "/api/pie-horno/"):
            device = self._device_auth_device()
            status = str((device or {}).get("status") or "unknown")
            if status != "approved":
                self._send_device_error(status)
                return
            payload = build_host_payload()
            role = str((device or {}).get("role") or "viewer")
            payload["permissions"] = {
                "role": role,
                "can_edit_cucharas": self._can_edit_cucharas(device),
                "can_edit_ajuste": self._can_edit_cucharas(device),
            }
            self._send_json(payload)
            return
        self._send_json({
            "ok": False,
            "error": "not_found",
            "endpoints": ["/", "/api/health", "/api/device/register", "/api/device/status", "/api/pie-horno", "/api/events"],
        }, status=404)

    def do_POST(self):
        path = self._request_path()
        if path in ("/api/device/register", "/api/device/register/"):
            payload = self._read_json_body()
            if payload is None:
                self._send_json({"ok": False, "error": "invalid_json"}, status=400)
                return
            device_id = str(payload.get("device_id", "") or "").strip()
            device_name = str(payload.get("name", "") or "").strip()
            device = register_or_touch_device(
                device_id,
                device_name,
                self.headers.get("User-Agent", ""),
                self._client_ip(),
            )
            if not device:
                self._send_json({"ok": False, "error": "invalid_device"}, status=400)
                return
            self._send_json({
                "ok": True,
                "status": str(device.get("status") or "pending"),
                "role": str(device.get("role") or "viewer"),
                "device_id": device_id,
            })
            return
        if path in ("/api/pie-horno", "/api/pie-horno/"):
            device = self._device_auth_device()
            status = str((device or {}).get("status") or "unknown")
            if status != "approved":
                self._send_device_error(status)
                return
            if not self._can_edit_cucharas(device):
                self._send_json({
                    "ok": False,
                    "error": "read_only",
                    "status": "approved",
                    "role": str((device or {}).get("role") or "viewer"),
                    "message": "Este dispositivo solo puede ver.",
                }, status=403)
                return
            payload = self._read_json_body()
            if payload is None:
                self._send_json({"ok": False, "error": "invalid_json"}, status=400)
                return
            action = str(payload.get("action", "") or "").strip().lower()
            if action != "save_materiales":
                self._send_json({"ok": False, "error": "invalid_action"}, status=400)
                return
            host_payload = save_furnace_material_confirmation(
                payload.get("rows", []),
                general_pct=payload.get("general_pct"),
            )
            self._send_json({"ok": True, "payload": host_payload})
            return
        if path not in ("/api/cucharas", "/api/cucharas/"):
            self._send_json({"ok": False, "error": "not_found"}, status=404)
            return
        device = self._device_auth_device()
        status = str((device or {}).get("status") or "unknown")
        if status != "approved":
            self._send_device_error(status)
            return
        if not self._can_edit_cucharas(device):
            self._send_json({
                "ok": False,
                "error": "read_only",
                "status": "approved",
                "role": str((device or {}).get("role") or "viewer"),
                "message": "Este dispositivo solo puede ver.",
            }, status=403)
            return
        payload = self._read_json_body()
        if payload is None:
            self._send_json({"ok": False, "error": "invalid_json"}, status=400)
            return
        action = str(payload.get("action", "") or "").strip().lower()
        if action == "start":
            try:
                cucharas = start_cucharas_count()
            except CucharasContextError:
                self._send_json({
                    "ok": False,
                    "error": "missing_ajuste_context",
                    "message": "Inicia la sesion en Ajuste con numero de colada y material objetivo.",
                }, status=409)
                return
            self._send_json({"ok": True, "cucharas": cucharas})
            return
        if action == "save":
            cucharas = save_cucharas_current()
            self._send_json({"ok": True, "cucharas": cucharas})
            return
        if "delta" in payload:
            if not _is_valid_delta_payload(payload):
                self._send_json({"ok": False, "error": "invalid_delta"}, status=400)
                return
            cucharas = save_cuchara_delta(
                payload.get("material_final") or payload.get("material"),
                payload.get("delta"),
            )
            self._send_json({"ok": True, "cucharas": cucharas})
            return
        self._send_json({
            "ok": False,
            "error": "snapshot_counts_disabled",
            "message": "Usa delta/start/save. No se aceptan snapshots completos para evitar pisar conteos desde clientes viejos.",
        }, status=409)


class _QuietThreadingHTTPServer(ThreadingHTTPServer):
    def handle_error(self, request, client_address):
        exc_type, exc, _ = sys.exc_info()
        disconnect_errors = (BrokenPipeError, ConnectionAbortedError, ConnectionResetError)
        winerror = getattr(exc, "winerror", None)
        if exc_type and issubclass(exc_type, disconnect_errors):
            return
        if isinstance(exc, OSError) and winerror in (10053, 10054):
            return
        super().handle_error(request, client_address)


class HostAPIServer:
    def __init__(self, host=HOST_API_HOST, port=HOST_API_PORT, allow_fallback=False):
        self.host = host
        self.port = int(port)
        self.allow_fallback = bool(allow_fallback)
        self.httpd = None
        self.thread = None

    def start(self):
        global CURRENT_HOST_API_PORT
        if self.httpd is not None:
            return self
        try:
            self.httpd = _QuietThreadingHTTPServer((self.host, self.port), _HostAPIHandler)
        except OSError:
            if not self.allow_fallback:
                raise
            self.httpd = _QuietThreadingHTTPServer((self.host, 0), _HostAPIHandler)
        self.port = int(self.httpd.server_address[1])
        CURRENT_HOST_API_PORT = self.port
        self.thread = threading.Thread(target=self.httpd.serve_forever, name="ajuste-comp-host-api", daemon=True)
        self.thread.start()
        return self

    def stop(self):
        if self.httpd is None:
            return
        try:
            self.httpd.shutdown()
            self.httpd.server_close()
        finally:
            self.httpd = None
            self.thread = None

    def url(self):
        return f"http://{_local_ip()}:{self.port}"
