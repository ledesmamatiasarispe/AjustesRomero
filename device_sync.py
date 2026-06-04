# device_sync.py
"""
Sincronización de fondo con el dispositivo Carbomax.

Flujo:
  1. Consulta /getallidx.cgi  → índice JSON completo
  2. Para cada ID nuevo (no en la DB local), consulta /getdata.cgi?btrqh=<id>
  3. Guarda en SQLite mediante save_thermal_device_records()
  4. Notifica a quien haya registrado un callback

Uso desde la app:
    from device_sync import DeviceSyncService
    svc = DeviceSyncService(ip="192.168.0.180", on_done=mi_callback)
    svc.start_once()        # dispara una sincronización ahora
    svc.start_auto(120)     # sincroniza cada 120 segundos
    svc.stop()
"""

import hashlib
import http.client
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime

from storage import load_thermal_device_records, save_thermal_device_records

SYNC_TIMEOUT      = 30      # segundos por request
SYNC_RETRIES      = 2
SYNC_RETRY_DELAY  = 1.5


# ---------- utilidades de fecha ----------

def _parse_device_date(raw):
    """Convierte 'DDMMYYYY HHMMSS' o 'DD/MM/YYYY HH:MM' a datetime o None."""
    s = str(raw or "").strip()
    if not s:
        return None
    for fmt in ("%d/%m/%Y %H:%M", "%Y-%m-%d %H:%M", "%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(s, fmt)
        except ValueError:
            pass
    # formato compacto DDMMYYYY HHMMSS
    m = re.match(r"^(\d{2})(\d{2})(\d{4})\s+(\d{2})(\d{2})(\d{2})$", s)
    if m:
        dd, mo, yy, hh, mi, ss = m.groups()
        try:
            return datetime(int(yy), int(mo), int(dd), int(hh), int(mi), int(ss))
        except ValueError:
            pass
    return None


def _fmt_display(raw):
    """Formatea fecha para mostrar en la UI: 'DD/MM/YYYY HH:MM'."""
    dt = _parse_device_date(raw)
    if dt:
        return dt.strftime("%d/%m/%Y %H:%M")
    return str(raw or "").strip()


# ---------- HTTP helpers ----------

class _HttpError(Exception):
    pass


def _http_get(ip, endpoint, timeout=SYNC_TIMEOUT, retries=SYNC_RETRIES):
    """
    Hace GET a http://ip/endpoint.
    El dispositivo a veces responde sin cabeceras HTTP estándar,
    por eso hay un fallback con socket crudo.
    """
    url = f"http://{ip}{endpoint}"
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "CarboSync/1.0"})
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return resp.read()
        except http.client.BadStatusLine:
            # el dispositivo manda JSON sin cabecera HTTP — usar socket crudo
            try:
                return _raw_socket_get(ip, endpoint, timeout)
            except Exception as ex:
                last_err = ex
        except (urllib.error.URLError, TimeoutError, socket.timeout, OSError) as ex:
            last_err = ex
            if attempt < retries:
                time.sleep(SYNC_RETRY_DELAY)
    raise _HttpError(f"No se pudo conectar a {url}: {last_err}")


def _raw_socket_get(ip, endpoint, timeout=SYNC_TIMEOUT):
    req = (
        f"GET {endpoint} HTTP/1.0\r\n"
        f"Host: {ip}\r\n"
        "User-Agent: CarboSync/1.0\r\n"
        "Connection: close\r\n\r\n"
    ).encode("ascii", errors="ignore")
    with socket.create_connection((ip, 80), timeout=timeout) as sock:
        sock.settimeout(timeout)
        sock.sendall(req)
        chunks = []
        while True:
            chunk = sock.recv(65536)
            if not chunk:
                break
            chunks.append(chunk)
    return b"".join(chunks)


def _parse_json(raw, url=""):
    """Decodifica bytes → dict/list, maneja cabeceras HTTP opcionales."""
    text = raw.decode("utf-8", errors="replace")
    text = text.replace("00011900", "01011900").replace("\\", "/").strip()
    if text.startswith("HTTP/"):
        for sep in ("\r\n\r\n", "\n\n"):
            pos = text.find(sep)
            if pos >= 0:
                text = text[pos + len(sep):].strip()
                break
    return json.loads(text)


# ---------- parsers de la página web del dispositivo ----------

def _is_busy_html(raw):
    """Devuelve True si el dispositivo responde con la página de 'análisis en curso'."""
    text = raw.decode("latin-1", errors="replace") if isinstance(raw, bytes) else raw
    return "working on an analysis" in text.lower() or "carbomaxdelta" in text.lower()


def _parse_float_es(s):
    """Convierte '1.298,00' o '1298,00' o ' 4,60' al float correspondiente."""
    try:
        return float(str(s).strip().replace(".", "").replace(",", "."))
    except Exception:
        return None


def _hist_index_date_to_compact(date_str):
    """'17/04/2026 - 12:52:57'  →  '17042026 125257'"""
    raw = str(date_str or "").strip()
    for fmt in ("%d/%m/%Y - %H:%M:%S", "%d/%m/%Y - %H:%M", "%d/%m/%Y %H:%M:%S"):
        try:
            from datetime import datetime as _dt
            return _dt.strptime(raw, fmt).strftime("%d%m%Y %H%M%S")
        except Exception:
            pass
    return raw


def _parse_hist_index_dat(raw):
    """
    Parsea HistIndex.dat (CSV de la página web del dispositivo).
    Devuelve dict compatible con {"TableIndex": [...]}.
    """
    text = raw.decode("latin-1", errors="replace") if isinstance(raw, bytes) else str(raw)
    # Quitar cabeceras HTTP y BOM
    if "\r\n\r\n" in text:
        text = text.split("\r\n\r\n", 1)[1]
    text = text.lstrip("﻿").strip()

    if _is_busy_html(text):
        raise _HttpError("Dispositivo ocupado (análisis en curso)")

    rows = []
    lines = [l.rstrip("\r") for l in text.split("\n")]
    for line in lines:
        parts = [p.strip() for p in line.split(",")]
        # Formato esperado: date/time, mode, lot, material, id
        # La primera fila de datos tiene fecha con longitud > 5
        if len(parts) < 5 or len(parts[0]) < 8:
            continue
        date_compact = _hist_index_date_to_compact(parts[0])
        rows.append({
            "id":       parts[4],
            "date":     date_compact,
            "mode":     parts[1],
            "lot":      parts[2],
            "material": parts[3],
        })
    return {"TableIndex": rows}


def _parse_dadoshist_csv(raw, index_row=None):
    """
    Parsea dadoshist.cgi (CSV con ; y decimales con coma).
    Devuelve dict compatible con {"TableData": [...]}.
    index_row: fila del índice con id, date, mode, lot, material.
    """
    text = raw.decode("latin-1", errors="replace") if isinstance(raw, bytes) else str(raw)
    if "\r\n\r\n" in text:
        text = text.split("\r\n\r\n", 1)[1]
    text = text.lstrip("﻿").strip()

    if _is_busy_html(text):
        raise _HttpError("Dispositivo ocupado (análisis en curso)")

    idx = index_row or {}
    row_id  = str(idx.get("id", ""))
    mode    = str(idx.get("mode", "")).strip().upper()
    lot     = str(idx.get("lot", "")).strip()
    material = str(idx.get("material", "")).strip()
    date_compact = str(idx.get("date", "")).strip()

    # Parsear fecha para start/stop_date en formato "DD/MM/YYYY HH:MM"
    try:
        from datetime import datetime as _dt
        stop_dt = _dt.strptime(date_compact, "%d%m%Y %H%M%S")
        stop_fmt = stop_dt.strftime("%d/%m/%Y %H:%M")
    except Exception:
        stop_fmt = date_compact

    # Separar secciones por línea en blanco
    sections = [s.strip() for s in text.replace("\r", "").split("\n\n") if s.strip()]

    metrics = {}
    data_temp, data_deriv = [], []

    for section in sections:
        lines = section.split("\n")
        if not lines:
            continue
        headers = [h.strip() for h in lines[0].split(";")]
        if not headers:
            continue

        if headers[0].lower() in ("periodo", "period", "time"):
            # Sección de curva: Periodo;Temperatura;Derivada
            for line in lines[1:]:
                parts = [p.strip() for p in line.split(";")]
                if len(parts) >= 3:
                    temp = _parse_float_es(parts[1])
                    deriv = _parse_float_es(parts[2])
                    if temp is not None:
                        data_temp.append(int(round(temp * 10)))
                    if deriv is not None:
                        data_deriv.append(int(round(deriv * 100)))
        elif len(lines) >= 2:
            # Sección de métricas: headers en línea 0, valores en línea 1
            values = [v.strip() for v in lines[1].split(";")]
            for h, v in zip(headers, values):
                f = _parse_float_es(v)
                if f is not None:
                    metrics[h.strip()] = f

    # Mapear métricas al formato interno (×10 para temps, ×100 para %)
    def _t(key, *aliases):
        for k in (key,) + aliases:
            if k in metrics:
                return int(round(metrics[k] * 10))
        return 0

    def _c(key, *aliases):
        for k in (key,) + aliases:
            if k in metrics:
                return int(round(metrics[k] * 100))
        return 0

    detail = {
        "id":          row_id,
        "test_mode":   mode,
        "material":    material,
        "lot":         lot,
        "obsevation":  "",
        "start_date":  stop_fmt,
        "stop_date":   stop_fmt,
        "channel":     0,
        "tag1": 0, "tag2": 0, "tag3": 0, "tag4": 0,
        "product":     "DELTA",
        "peak":        _t("Pico", "Peak"),
        "liquidus":    _t("TL"),
        "carbon_eq":   _c("CE", "CE%"),
        "solidus":     _t("TS"),
        "carbon":      _c("C"),
        "silicon":     _c("Si"),
        "tse":         _t("TSE"),
        "tre":         _t("TRE"),
        "recalec":     _t("REC"),
        "delta_rec":   _c("ΔREC", "Delta REC", "DREC"),
        "final":       _t("TF"),
        "data_temp":   data_temp,
        "data_deriv":  data_deriv,
    }
    return {"TableData": [detail]}


# ---------- lógica de sync ----------

def _identity_from_info(info):
    """Cadena determinista que identifica unívocamente una medición."""
    parts = (
        str(info.get("Dt Inicio", "") or info.get("Dt Termino", "") or "").strip(),
        str(info.get("Dt Termino", "") or "").strip(),
        str(info.get("Modo", "") or "").strip().upper(),
        str(info.get("Material", "") or "").strip().upper(),
        str(info.get("Lote", "") or "").strip().upper(),
        str(info.get("Canal", "") or "").strip(),
        str(info.get("tag1", "") or "").strip(),
        str(info.get("tag2", "") or "").strip(),
        str(info.get("tag3", "") or "").strip(),
        str(info.get("tag4", "") or "").strip(),
        str(info.get("Pico", "") or "").strip(),
        str(info.get("TL", "") or "").strip(),
        str(info.get("CE %", "") or "").strip(),
        str(info.get("TS", "") or "").strip(),
        str(info.get("C %", "") or "").strip(),
        str(info.get("Si %", "") or "").strip(),
        str(info.get("TSE", "") or "").strip(),
        str(info.get("TRE", "") or "").strip(),
        str(info.get("REC", "") or "").strip(),
        str(info.get("Delta REC C/s", "") or "").strip(),
        str(info.get("TF", "") or "").strip(),
    )
    if not parts[0]:
        return ""
    return "|".join(parts)


def _local_id(identity):
    if not identity:
        return ""
    return hashlib.sha1(identity.encode("utf-8", errors="ignore")).hexdigest()[:16]


def _mode_group(mode_str):
    m = str(mode_str or "").upper()
    if "MICR" in m:
        return "Microestructura"
    if "CARB" in m:
        return "Carbono"
    return ""


def _build_info_from_detail(ip, row_id, detail):
    """Mapea los campos del getdata.cgi al formato 'info' que usa la app."""
    def _c(v):
        """centésimas → decimal con 2 decimales, e.g. 448 → 4.48"""
        try:
            return round(int(v) / 100, 2)
        except Exception:
            return None

    def _t(v):
        """décimas de grado → grados, e.g. 11375 → 1137.5"""
        try:
            return round(int(v) / 10, 1)
        except Exception:
            return None

    start_fmt = _fmt_display(detail.get("start_date", ""))
    stop_fmt  = _fmt_display(detail.get("stop_date", ""))

    info = {
        "ID":           str(row_id),
        "IP":           str(ip),
        "Equipamento":  "Carbomax",
        "Modo":         str(detail.get("test_mode", "") or ""),
        "Canal":        str(detail.get("channel", "") or ""),
        "Material":     str(detail.get("material", "") or ""),
        "Lote":         str(detail.get("lot", "") or ""),
        "Observacion":  str(detail.get("obsevation", "") or ""),
        "Dt Inicio":    start_fmt,
        "Dt Termino":   stop_fmt,
        "Pico":         _t(detail.get("peak")),
        "TL":           _t(detail.get("liquidus")),
        "CE %":         _c(detail.get("carbon_eq")),
        "TSE":          _t(detail.get("tse")),
        "TRE":          _t(detail.get("tre")),
        "REC":          _t(detail.get("recalec")),
        "Delta REC C/s": _c(detail.get("delta_rec")),
        "TF":           _t(detail.get("final")),
        "tag1":         detail.get("tag1"),
        "tag2":         detail.get("tag2"),
        "tag3":         detail.get("tag3"),
        "tag4":         detail.get("tag4"),
        # campos carbono (pueden estar presentes según modo)
        "TS":           _t(detail.get("ts")),
        "C %":          _c(detail.get("carbon")),
        "Si %":         _c(detail.get("silicon")),
    }
    return info


def _build_record(ip, row_id, index_row, detail):
    """Construye el dict de registro que guarda la app en SQLite."""
    start_raw = str(detail.get("start_date", "") or index_row.get("date", "") or "")
    stop_raw  = str(detail.get("stop_date", "") or "")
    mode_raw  = str(detail.get("test_mode", "") or index_row.get("mode", "") or "")

    info    = _build_info_from_detail(ip, row_id, detail)
    series  = [v for v in (detail.get("data_temp") or []) if v != 0]
    deriv   = [v for v in (detail.get("data_deriv") or []) if v != 0]

    payload = {
        "info":    info,
        "series":  series,
        "deriv":   deriv,
        "name":    f"{ip}_{row_id}.json",
    }

    identity = _identity_from_info(info)
    loc_id   = _local_id(identity)
    path     = f"device://{ip}/local/{loc_id}" if loc_id else f"device://{ip}/{row_id}"
    payload["path"]      = path
    payload["identity"]  = identity
    payload["local_id"]  = loc_id

    modified = _fmt_display(start_raw) or _fmt_display(stop_raw)

    return {
        "name":       f"{ip}_{row_id}.json",
        "path":       path,
        "legacy_path": f"device://{ip}/{row_id}",
        "identity":   identity,
        "local_id":   loc_id,
        "modified":   modified,
        "source":     "device",
        "mode_group": _mode_group(mode_raw),
        "payload":    payload,
    }


def sync_once(ip, log=None):
    """
    Descarga registros nuevos desde el dispositivo y actualiza SQLite.

    Parámetros
    ----------
    ip  : str   IP del dispositivo Carbomax
    log : callable(str) opcional — recibe mensajes de progreso

    Retorna
    -------
    dict con claves:
        ok          bool
        new         int   registros nuevos descargados
        reused      int   registros ya existentes
        total       int   total en DB después de la sync
        error       str   mensaje de error (si not ok)
    """
    def _log(msg):
        if callable(log):
            log(msg)

    _log(f"[sync] Iniciando desde {ip}")

    # 1. Cargar registros existentes, indexados por identity y legacy_path
    try:
        existing = load_thermal_device_records() or []
    except Exception as ex:
        return {"ok": False, "error": f"No se pudo leer DB: {ex}", "new": 0, "reused": 0, "total": 0}

    existing_by_identity  = {}
    existing_by_legacy    = {}
    for rec in existing:
        ident = str(rec.get("identity", "") or "").strip()
        if ident:
            existing_by_identity[ident] = rec
        leg = str(rec.get("legacy_path", "") or "").strip()
        if leg:
            existing_by_legacy[leg] = rec
        # también por path viejo device://ip/rowid
        path = str(rec.get("path", "") or "").strip()
        if path and path.startswith("device://") and "/local/" not in path:
            existing_by_legacy[path] = rec

    # 2. Obtener índice del dispositivo (web-page primero, JSON como fallback)
    try:
        raw_idx = _http_get(ip, "/HistIndex.dat")
        idx_data = _parse_hist_index_dat(raw_idx)
        index_rows = idx_data.get("TableIndex", [])
        _log(f"[sync] Índice obtenido via HistIndex.dat")
    except Exception as ex1:
        _log(f"[sync] HistIndex.dat falló ({ex1}), intentando getallidx.cgi...")
        try:
            raw_idx = _http_get(ip, "/getallidx.cgi")
            idx_data = _parse_json(raw_idx)
            index_rows = idx_data.get("TableIndex", [])
        except Exception as ex2:
            return {"ok": False, "error": f"No se pudo obtener índice: {ex2}", "new": 0, "reused": 0, "total": len(existing)}

    _log(f"[sync] Índice recibido: {len(index_rows)} registros en dispositivo")

    # 3. Para cada fila del índice: reutilizar o descargar
    updated_records = []          # lista final para guardar
    seen_identities = set()
    new_count    = 0
    reused_count = 0

    for row in index_rows:
        row_id     = str(row.get("id", "")).strip()
        legacy_key = f"device://{ip}/{row_id}"
        mode_raw   = str(row.get("mode", "") or "")

        # ¿ya tenemos este registro?
        cached = existing_by_identity.get("") or None   # placeholder
        cached = existing_by_legacy.get(legacy_key)

        if cached:
            # marcar como visto y reutilizar
            ident = str(cached.get("identity", "") or "").strip()
            if ident:
                seen_identities.add(ident)
            reused_count += 1
            updated_records.append(cached)
            _log(f"[sync] id={row_id}: reutilizado")
            continue

        # Descargar detalle (web-page primero, JSON como fallback)
        try:
            raw_detail = _http_get(ip, f"/dadoshist.cgi?btrqh={urllib.parse.quote(row_id)}")
            detail_data = _parse_dadoshist_csv(raw_detail, index_row=row)
            rows_detail = detail_data.get("TableData", [])
            if not rows_detail:
                _log(f"[sync] id={row_id}: detalle vacío (dadoshist), se omite")
                continue
            detail = rows_detail[0]
        except Exception as ex1:
            _log(f"[sync] id={row_id}: dadoshist falló ({ex1}), intentando getdata.cgi...")
            try:
                raw_detail = _http_get(ip, f"/getdata.cgi?btrqh={urllib.parse.quote(row_id)}")
                detail_data = _parse_json(raw_detail)
                rows_detail = detail_data.get("TableData", [])
                if not rows_detail:
                    _log(f"[sync] id={row_id}: detalle vacío (getdata), se omite")
                    continue
                detail = rows_detail[0]
            except Exception as ex2:
                _log(f"[sync] id={row_id}: error descargando detalle: {ex2}")
                continue

        series = [v for v in (detail.get("data_temp") or []) if v != 0]
        if not series:
            _log(f"[sync] id={row_id}: sin puntos de curva, se omite")
            continue

        rec = _build_record(ip, row_id, row, detail)
        ident = rec.get("identity", "")
        if ident:
            seen_identities.add(ident)

        new_count += 1
        updated_records.append(rec)
        _log(f"[sync] id={row_id}: descargado ({rec['mode_group']})")

    # 4. Añadir registros existentes que ya no están en el índice del dispositivo
    #    (mantener histórico local)
    for rec in existing:
        ident = str(rec.get("identity", "") or "").strip()
        if ident and ident not in seen_identities:
            updated_records.append(rec)
            seen_identities.add(ident)

    # 5. Deduplicar por path antes de guardar
    seen_paths = set()
    deduped = []
    for rec in updated_records:
        p = str(rec.get("path", "") or "").strip()
        if p and p in seen_paths:
            continue
        if p:
            seen_paths.add(p)
        deduped.append(rec)

    # 6. Guardar en SQLite
    try:
        save_thermal_device_records(deduped)
    except Exception as ex:
        return {"ok": False, "error": f"No se pudo guardar en DB: {ex}",
                "new": new_count, "reused": reused_count, "total": len(deduped)}

    _log(f"[sync] Listo — nuevos={new_count} reutilizados={reused_count} total={len(deduped)}")
    return {
        "ok":     True,
        "new":    new_count,
        "reused": reused_count,
        "total":  len(deduped),
        "error":  "",
    }


# ---------- servicio de fondo ----------

class DeviceSyncService:
    """
    Servicio de sincronización en background.

    Ejemplo:
        def on_done(result):
            if result["ok"] and result["new"] > 0:
                root.after(0, refresh_tab)

        svc = DeviceSyncService("192.168.0.180", on_done=on_done)
        svc.start_once()          # una sola vez
        svc.start_auto(interval=180)  # cada 3 minutos
    """

    def __init__(self, ip, on_done=None, on_log=None):
        """
        ip       : str        IP del dispositivo
        on_done  : callable   fn(result_dict) llamada en el hilo de fondo al terminar
        on_log   : callable   fn(str) para mensajes de progreso
        """
        self.ip      = ip
        self.on_done = on_done
        self.on_log  = on_log
        self._stop   = threading.Event()
        self._thread = None
        self._lock   = threading.Lock()

    def _log(self, msg):
        if callable(self.on_log):
            try:
                self.on_log(msg)
            except Exception:
                pass

    def _run_once(self):
        result = sync_once(self.ip, log=self._log)
        if callable(self.on_done):
            try:
                self.on_done(result)
            except Exception:
                pass

    def _run_auto(self, interval):
        while not self._stop.wait(0):
            self._run_once()
            # esperar interval segundos, pero chequeando _stop cada segundo
            for _ in range(int(interval)):
                if self._stop.is_set():
                    return
                time.sleep(1)

    def start_once(self):
        """Lanza una sincronización única en background."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return  # ya corriendo
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_once, daemon=True, name="CarboSync-once"
            )
            self._thread.start()

    def start_auto(self, interval=180):
        """Lanza sincronización periódica cada `interval` segundos."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_auto, args=(interval,),
                daemon=True, name="CarboSync-auto"
            )
            self._thread.start()

    def stop(self):
        """Detiene la sincronización automática."""
        self._stop.set()

    @property
    def is_running(self):
        return bool(self._thread and self._thread.is_alive())


# ---------- servicio de vigilancia (auto ajuste) ----------

class WatchService:
    """
    Vigila el dispositivo en background y notifica cuando aparece un registro
    CARBONO nuevo con C% y Si% disponibles.

    Uso:
        def on_carbon(info):
            carbon  = info["C %"]     # float, ej. 3.21
            silicon = info["Si %"]    # float, ej. 1.95
            label   = info["_label"]  # nombre legible para mostrar en UI
            root.after(0, lambda: ajuste_tab.load_carbon_silicon(carbon, silicon, label))

        ws = WatchService("192.168.0.180", on_carbon=on_carbon, interval=20)
        ws.start()
        ws.stop()
    """

    # Intervalo de sondeo por defecto (segundos)
    DEFAULT_INTERVAL = 20

    def __init__(self, ip, on_carbon=None, on_status=None, interval=None):
        """
        ip          IP del dispositivo
        on_carbon   fn(info_dict) — callback al detectar nuevo carbono
        on_status   fn(str) — callback con mensajes de estado (opcional)
        interval    segundos entre consultas al índice
        """
        self.ip          = ip
        self.on_carbon   = on_carbon
        self.on_status   = on_status
        self.interval    = int(interval or self.DEFAULT_INTERVAL)
        self._stop       = threading.Event()
        self._thread     = None
        self._lock       = threading.Lock()
        self._known_ids  = set()   # IDs ya vistos en el dispositivo
        self._seeded     = False   # ¿ya se sembró el conjunto inicial?

    def _emit_status(self, msg):
        if callable(self.on_status):
            try:
                self.on_status(msg)
            except Exception:
                pass

    def _fetch_index(self, retries=SYNC_RETRIES):
        """Obtiene el índice via HistIndex.dat (página web) con fallback a getallidx.cgi."""
        try:
            raw = _http_get(self.ip, "/HistIndex.dat", timeout=SYNC_TIMEOUT, retries=retries)
            data = _parse_hist_index_dat(raw)
        except Exception:
            raw = _http_get(self.ip, "/getallidx.cgi", timeout=SYNC_TIMEOUT, retries=retries)
            data = _parse_json(raw)
        return data.get("TableIndex", [])

    def _seed_known_ids(self):
        """Marca todos los IDs actualmente en el dispositivo como 'ya conocidos'
        para no re-disparar en el primer poll."""
        try:
            rows = self._fetch_index()
            self._known_ids = {str(r.get("id", "")).strip() for r in rows if r.get("id") is not None}
            self._seeded = True
            self._emit_status(f"[watch] Semilla: {len(self._known_ids)} IDs conocidos en {self.ip}")
        except Exception as ex:
            self._emit_status(f"[watch] No se pudo obtener semilla inicial: {ex}")
            self._seeded = True

    def _poll_once(self):
        """Un ciclo de sondeo: pide el índice y procesa IDs nuevos."""
        try:
            rows = self._fetch_index(retries=1)
        except Exception as ex:
            self._emit_status(f"[watch] Error al consultar índice: {ex}")
            return

        new_rows = []
        for row in rows:
            rid = str(row.get("id", "")).strip()
            if rid not in self._known_ids:
                new_rows.append(row)
                self._known_ids.add(rid)

        if not new_rows:
            return

        self._emit_status(f"[watch] {len(new_rows)} registro(s) nuevo(s) detectado(s)")

        for row in new_rows:
            mode = str(row.get("mode", "") or "").upper()
            rid  = str(row.get("id", "")).strip()

            if "CARB" not in mode:
                self._emit_status(f"[watch] id={rid} modo={mode}: ignorado (no es CARBONO)")
                continue

            # Descargar detalle (web-page primero, JSON como fallback)
            try:
                raw_d    = _http_get(self.ip, f"/dadoshist.cgi?btrqh={urllib.parse.quote(rid)}",
                                     timeout=SYNC_TIMEOUT, retries=2)
                det_data = _parse_dadoshist_csv(raw_d, index_row=row)
                rows_d   = det_data.get("TableData", [])
                if not rows_d:
                    self._emit_status(f"[watch] id={rid}: detalle vacío")
                    continue
                detail = rows_d[0]
            except Exception as ex1:
                try:
                    raw_d    = _http_get(self.ip, f"/getdata.cgi?btrqh={urllib.parse.quote(rid)}",
                                         timeout=SYNC_TIMEOUT, retries=2)
                    det_data = _parse_json(raw_d)
                    rows_d   = det_data.get("TableData", [])
                    if not rows_d:
                        self._emit_status(f"[watch] id={rid}: detalle vacío")
                        continue
                    detail = rows_d[0]
                except Exception as ex2:
                    self._emit_status(f"[watch] id={rid}: error descargando detalle: {ex2}")
                    continue

            info = _build_info_from_detail(self.ip, rid, detail)
            carbon  = info.get("C %")
            silicon = info.get("Si %")

            if carbon is None or silicon is None:
                self._emit_status(
                    f"[watch] id={rid}: sin C% o Si% (C={carbon}, Si={silicon}), ignorado"
                )
                continue

            label = f"Carbomax {self.ip} id={rid}  {info.get('Dt Inicio','')}"
            info["_label"] = label
            info["_ip"]    = self.ip
            info["_id"]    = rid

            self._emit_status(f"[watch] id={rid}: CARBONO nuevo → C={carbon}% Si={silicon}%")

            if callable(self.on_carbon):
                try:
                    self.on_carbon(info)
                except Exception as ex:
                    self._emit_status(f"[watch] on_carbon callback error: {ex}")

    def _run_loop(self):
        # Sembrar primero
        if not self._seeded:
            self._seed_known_ids()

        self._emit_status(f"[watch] Vigilancia activa — sondeo cada {self.interval}s")

        while not self._stop.is_set():
            self._poll_once()
            # esperar interval segundos, interruptible segundo a segundo
            for _ in range(self.interval):
                if self._stop.is_set():
                    return
                time.sleep(1)

        self._emit_status("[watch] Vigilancia detenida")

    def start(self):
        """Inicia la vigilancia en background. No-op si ya está corriendo."""
        with self._lock:
            if self._thread and self._thread.is_alive():
                return
            self._stop.clear()
            self._thread = threading.Thread(
                target=self._run_loop, daemon=True, name="CarboWatch"
            )
            self._thread.start()

    def stop(self):
        """Detiene la vigilancia."""
        self._stop.set()

    def reset_seed(self):
        """Fuerza re-sembrado: el próximo poll tratará todos los IDs como nuevos
        hasta la semilla actual. Útil si se reinicia una sesión de ajuste."""
        self._seeded = False
        self._known_ids.clear()

    @property
    def is_running(self):
        return bool(self._thread and self._thread.is_alive() and not self._stop.is_set())


# ---------- ejecución directa (script independiente) ----------

if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

    ip = sys.argv[1] if len(sys.argv) > 1 else "192.168.0.180"
    print(f"Sincronizando con {ip}...")

    result = sync_once(ip, log=print)
    print()
    if result["ok"]:
        print(f"✓  Nuevos: {result['new']}  |  Reutilizados: {result['reused']}  |  Total en DB: {result['total']}")
    else:
        print(f"✗  Error: {result['error']}")
