# device_sync.py
"""
Utilidades de bajo nivel para hablar con el dispositivo Carbomax (parseo de
HistIndex.dat/getallidx.cgi/dadoshist.cgi/getdata.cgi) mas la funcion
sync_once() para sincronizar todo el indice contra SQLite de una vez.

tab_analisis_termico.py usa directamente estas funciones de parseo
(_parse_hist_index_dat, _parse_dadoshist_csv, _is_busy_html) para su propia
descarga incremental (_fetch_device_records). El ciclo de descarga+vinculacion
automatico y periodico vive en TabAjuste.carbomax_auto (ver tab_ajuste.py),
que llama a TabAnalisisTermico.run_download_and_link_cycle_async(...).

Uso como script independiente (sincroniza una vez y sale):
    python device_sync.py 192.168.0.180
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
    # El firmware del equipo a veces manda "00011900" (dia 00, invalido)
    # como fecha por defecto de un campo vacio; se lo corrige a "01011900"
    # (dia 01) para que despues parsee como fecha valida en vez de tirar
    # excepcion.
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

    # NOTA: existing_by_identity se arma pero no se usa para buscar mas abajo
    # (la identidad solo se puede calcular DESPUES de bajar el detalle, ver
    # _identity_from_info, que necesita campos como "Dt Inicio" que vienen
    # del detalle, no del indice) — el match real de "ya lo tengo" se hace
    # por legacy_path/row_id (existing_by_legacy) unicamente.
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

        # ¿ya tenemos este registro? (unico match posible: por row_id, ver
        # nota sobre existing_by_identity mas arriba)
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


# ---------- ejecución directa (script independiente) ----------

if __name__ == "__main__":
    # Permite correr "python device_sync.py [ip]" para probar la sync a mano
    # sin levantar toda la app; la IP por defecto es solo una conveniencia
    # para pruebas en el taller, no un valor "real" de produccion.
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
