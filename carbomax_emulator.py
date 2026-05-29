"""
carbomax_emulator.py
Emulador del dispositivo Carbomax/Delta para pruebas locales.

Sirve los mismos endpoints CGI que el equipo real:
  GET /getallidx.cgi            → índice de mediciones
  GET /getdata.cgi?btrqh=<id>   → detalle de una medición
  GET /dataparam.cgi?logon=<pw> → auth (siempre TRUE en emulador)
  GET /                         → UI de configuración/generación

Uso:
  python carbomax_emulator.py [puerto]   (default: 8766)

Luego en la app, cambiar IP del equipo a  127.0.0.1:8766
"""

import json
import math
import random
import socket
import sys
import time
from datetime import datetime
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

PORT = int(sys.argv[1]) if len(sys.argv) > 1 else 8766
STORE_FILE = Path(__file__).parent / "carbomax_emulator_data.json"

# ── Almacenamiento en memoria ──────────────────────────────────────────────────

_records = []   # lista de dicts {id, date, mode, material, lot, detail}
_next_id = [1]


def _load_store():
    global _records, _next_id
    if STORE_FILE.exists():
        try:
            data = json.loads(STORE_FILE.read_text(encoding="utf-8"))
            _records = data.get("records", [])
            _next_id[0] = data.get("next_id", len(_records) + 1)
            return
        except Exception:
            pass
    _records = []
    _next_id[0] = 1


def _save_store():
    try:
        STORE_FILE.write_text(
            json.dumps({"records": _records, "next_id": _next_id[0]}, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
    except Exception:
        pass


# ── Generadores de curvas sintéticas ──────────────────────────────────────────

def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _micro_curve(pico, tl, tse, tre, tf, duration_s=160, step=0.5):
    """
    Genera curva de temperatura y derivada para modo MICROESTRUCTURA.
    Valores de temperatura en décimas de grado (como el equipo real).
    """
    n = int(duration_s / step)
    temp_pts = []
    deriv_pts = []
    cool_rate = (pico - tf) / duration_s   # °C/s de enfriamiento promedio

    for i in range(n):
        t = i * step
        base = pico - cool_rate * t

        # Térmica en TL: pequeña perturbación positiva
        if tl - 8 < base < tl + 8:
            base += 4 * math.exp(-((base - tl) ** 2) / 30)

        # Recalescencia eutectica entre TSE y TRE
        if tf < base < tse:
            dist = abs(base - (tse + tre) / 2)
            bump = 15 * math.exp(-(dist ** 2) / 80)
            base += bump

        base = _clamp(base, tf - 10, pico + 5)
        noise = random.gauss(0, 0.3)
        temp_pts.append(int(round((base + noise) * 10)))

    # Derivada: diferencia entre puntos consecutivos (en °C/s × 100)
    for i in range(n):
        if i == 0:
            d = 0.0
        else:
            d = (temp_pts[i] - temp_pts[i - 1]) / step / 10.0  # °C/s
        deriv_pts.append(int(round(d * 100)))

    return temp_pts, deriv_pts


def _carbon_curve(pico, tl, ts, tf, duration_s=140, step=0.5):
    """
    Genera curva de temperatura y derivada para modo CARBONO.
    """
    n = int(duration_s / step)
    temp_pts = []
    cool_rate = (pico - tf) / duration_s

    for i in range(n):
        t = i * step
        base = pico - cool_rate * t
        if tl - 5 < base < tl + 5:
            base += 3 * math.exp(-((base - tl) ** 2) / 20)
        if ts - 10 < base < ts + 10:
            base += 6 * math.exp(-((base - ts) ** 2) / 40)
        base = _clamp(base, tf - 5, pico + 5)
        noise = random.gauss(0, 0.3)
        temp_pts.append(int(round((base + noise) * 10)))

    deriv_pts = []
    for i in range(n):
        if i == 0:
            d = 0.0
        else:
            d = (temp_pts[i] - temp_pts[i - 1]) / step / 10.0
        deriv_pts.append(int(round(d * 100)))

    return temp_pts, deriv_pts


# ── Creación de registros ──────────────────────────────────────────────────────

def _now_fmt():
    return datetime.now().strftime("%d%m%Y %H%M%S")


def _fmt_display(dt_str):
    try:
        return datetime.strptime(dt_str, "%d%m%Y %H%M%S").strftime("%d/%m/%Y %H:%M")
    except Exception:
        return dt_str


def create_micro_record(material="FcE500", lot="", canal="1", obs="",
                        pico=1360.0, tl=1155.0, tse=1148.0, tre=1143.0,
                        rec=12.0, delta_rec=2.5, tf=1080.0, ce=4.48):
    rid = str(_next_id[0])
    _next_id[0] += 1
    now = _now_fmt()
    temp_pts, deriv_pts = _micro_curve(pico, tl, tse, tre, tf)
    detail = {
        "id": rid,
        "test_mode": "MICROESTRUTURA",
        "channel": canal,
        "material": material,
        "lot": lot,
        "obsevation": obs,
        "start_date": _fmt_display(now),
        "stop_date": _fmt_display(now),
        "peak":      int(round(pico * 10)),
        "liquidus":  int(round(tl * 10)),
        "carbon_eq": int(round(ce * 100)),
        "tse":       int(round(tse * 10)),
        "tre":       int(round(tre * 10)),
        "recalec":   int(round(rec * 10)),
        "delta_rec": int(round(delta_rec * 10)),
        "final":     int(round(tf * 10)),
        "tag1": 45,
        "tag2": 62,
        "tag3": 89,
        "tag4": 120,
        "data_temp":  temp_pts,
        "data_deriv": deriv_pts,
        "product": "",
    }
    rec = {"id": rid, "date": now, "mode": "MICROESTRUTURA",
           "material": material, "lot": lot, "detail": detail}
    _records.insert(0, rec)
    _save_store()
    return rid


def create_carbon_record(material="FcE500", lot="", canal="1", obs="",
                         pico=1360.0, tl=1155.0, ts=1090.0, tf=1050.0,
                         ce=4.48, carbon=3.21, silicon=2.15):
    rid = str(_next_id[0])
    _next_id[0] += 1
    now = _now_fmt()
    temp_pts, deriv_pts = _carbon_curve(pico, tl, ts, tf)
    detail = {
        "id": rid,
        "test_mode": "CARBONO",
        "channel": canal,
        "material": material,
        "lot": lot,
        "obsevation": obs,
        "start_date": _fmt_display(now),
        "stop_date":  _fmt_display(now),
        "peak":      int(round(pico * 10)),
        "liquidus":  int(round(tl * 10)),
        "carbon_eq": int(round(ce * 100)),
        "solidus":   int(round(ts * 10)),
        "carbon":    int(round(carbon * 100)),
        "silicon":   int(round(silicon * 100)),
        "final":     int(round(tf * 10)),
        "tag1": 40,
        "tag2": 58,
        "tag3": 80,
        "tag4": 110,
        "data_temp":  temp_pts,
        "data_deriv": deriv_pts,
        "product": "",
    }
    rec = {"id": rid, "date": now, "mode": "CARBONO",
           "material": material, "lot": lot, "detail": detail}
    _records.insert(0, rec)
    _save_store()
    return rid


def delete_record(rid):
    global _records
    _records = [r for r in _records if str(r["id"]) != str(rid)]
    _save_store()


# ── HTTP handler ───────────────────────────────────────────────────────────────

def _json_resp(handler, data, status=200):
    body = json.dumps(data, ensure_ascii=False).encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "application/json; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.send_header("Access-Control-Allow-Origin", "*")
    handler.end_headers()
    handler.wfile.write(body)


def _html_resp(handler, html, status=200):
    body = html.encode("utf-8")
    handler.send_response(status)
    handler.send_header("Content-Type", "text/html; charset=utf-8")
    handler.send_header("Content-Length", str(len(body)))
    handler.end_headers()
    handler.wfile.write(body)


def _read_body(handler):
    length = int(handler.headers.get("Content-Length", "0") or "0")
    if length <= 0:
        return {}
    raw = handler.rfile.read(length)
    ct = handler.headers.get("Content-Type", "")
    if "json" in ct:
        try:
            return json.loads(raw.decode("utf-8"))
        except Exception:
            return {}
    return parse_qs(raw.decode("utf-8"))


class _Handler(BaseHTTPRequestHandler):
    server_version = "CarboxEmulator/1.0"

    def log_message(self, fmt, *args):
        print(f"[EMU] {self.address_string()} {fmt % args}")

    def _path(self):
        return urlparse(self.path).path

    def _query(self):
        return parse_qs(urlparse(self.path).query)

    def do_GET(self):
        p = self._path()
        q = self._query()
        if p in ("/getallidx.cgi", "/getallidx.cgi/"):
            self._handle_index()
        elif p in ("/getdata.cgi", "/getdata.cgi/"):
            self._handle_detail(q)
        elif p in ("/dataparam.cgi", "/dataparam.cgi/"):
            self._handle_auth(q)
        elif p in ("/", "/index.html"):
            _html_resp(self, _ui_html())
        elif p == "/api/records":
            _json_resp(self, {"records": [
                {"id": r["id"], "date": r["date"], "mode": r["mode"],
                 "material": r["material"], "lot": r["lot"]}
                for r in _records
            ]})
        else:
            _json_resp(self, {"error": "not_found"}, 404)

    def do_POST(self):
        p = self._path()
        body = _read_body(self)
        if p == "/api/create":
            self._handle_create(body)
        elif p == "/api/delete":
            rid = str(body.get("id", "")).strip()
            if rid:
                delete_record(rid)
            _json_resp(self, {"ok": True})
        else:
            _json_resp(self, {"error": "not_found"}, 404)

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def _handle_index(self):
        rows = []
        for r in _records:
            rows.append({
                "id":       r["id"],
                "date":     r["date"],
                "mode":     r["mode"],
                "material": r["material"],
                "lot":      r["lot"],
            })
        _json_resp(self, {"TableIndex": rows})

    def _handle_detail(self, q):
        rid = (q.get("btrqh") or [""])[0].strip()
        for r in _records:
            if str(r["id"]) == rid:
                _json_resp(self, {"TableData": [r["detail"]]})
                return
        _json_resp(self, {"TableData": []})

    def _handle_auth(self, q):
        # En el emulador siempre devuelve TRUE (sin contraseña real)
        pw = (q.get("logon") or [""])[0]
        body = b"TRUE"
        self.send_response(200)
        self.send_header("Content-Type", "text/plain")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _handle_create(self, body):
        try:
            mode = str(body.get("mode", "micro")).lower()
            material = str(body.get("material", "FcE500")).strip() or "FcE500"
            lot      = str(body.get("lot", "")).strip()
            canal    = str(body.get("canal", "1")).strip() or "1"
            obs      = str(body.get("obs", "")).strip()

            def _f(key, default):
                try:
                    return float(body.get(key, default))
                except Exception:
                    return float(default)

            if "carb" in mode:
                rid = create_carbon_record(
                    material=material, lot=lot, canal=canal, obs=obs,
                    pico=_f("pico", 1360), tl=_f("tl", 1155),
                    ts=_f("ts", 1090),    tf=_f("tf", 1050),
                    ce=_f("ce", 4.48),    carbon=_f("carbon", 3.21),
                    silicon=_f("silicon", 2.15),
                )
            else:
                rid = create_micro_record(
                    material=material, lot=lot, canal=canal, obs=obs,
                    pico=_f("pico", 1360),  tl=_f("tl", 1155),
                    tse=_f("tse", 1148),    tre=_f("tre", 1143),
                    rec=_f("rec", 12.0),    delta_rec=_f("delta_rec", 2.5),
                    tf=_f("tf", 1080),      ce=_f("ce", 4.48),
                )
            _json_resp(self, {"ok": True, "id": rid})
        except Exception as ex:
            _json_resp(self, {"ok": False, "error": str(ex)}, 500)


# ── HTML de la UI de configuración ────────────────────────────────────────────

def _ui_html():
    return """<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Carbomax Emulator</title>
<style>
  * { box-sizing: border-box; margin: 0; padding: 0; }
  body { font-family: Arial, sans-serif; font-size: 13px; background: #1a1a2e; color: #e0e0e0; }
  header { background: #0f3460; padding: 12px 20px; display: flex; align-items: center; gap: 12px; }
  header h1 { font-size: 16px; color: #e94560; }
  header span { font-size: 11px; color: #aaa; }
  .container { display: grid; grid-template-columns: 380px 1fr; gap: 16px; padding: 16px; max-width: 1100px; }
  .card { background: #16213e; border-radius: 8px; padding: 16px; border: 1px solid #0f3460; }
  .card h2 { font-size: 13px; color: #e94560; margin-bottom: 12px; text-transform: uppercase; letter-spacing: 1px; }
  .tabs { display: flex; gap: 0; margin-bottom: 14px; }
  .tab { padding: 6px 18px; cursor: pointer; border: 1px solid #0f3460; background: #0d1b34; color: #aaa; font-size: 12px; }
  .tab.active { background: #e94560; color: #fff; border-color: #e94560; }
  .tab:first-child { border-radius: 4px 0 0 4px; }
  .tab:last-child  { border-radius: 0 4px 4px 0; }
  .form-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px; }
  .form-grid.full { grid-template-columns: 1fr; }
  label { display: block; font-size: 11px; color: #888; margin-bottom: 2px; }
  input, select { width: 100%; padding: 5px 8px; background: #0d1b34; border: 1px solid #0f3460;
                  color: #e0e0e0; border-radius: 4px; font-size: 12px; }
  input:focus { outline: none; border-color: #e94560; }
  .btn { padding: 8px 18px; border: none; border-radius: 4px; cursor: pointer; font-size: 12px; font-weight: bold; }
  .btn-primary { background: #e94560; color: #fff; }
  .btn-primary:hover { background: #c73652; }
  .btn-danger { background: #444; color: #e94560; font-size: 11px; padding: 3px 8px; border-radius: 3px; cursor: pointer; border: none; }
  .btn-danger:hover { background: #600; color: #fff; }
  .msg { padding: 8px 12px; border-radius: 4px; font-size: 12px; margin-top: 10px; display: none; }
  .msg.ok  { background: #1a4a1a; color: #7fff7f; display: block; }
  .msg.err { background: #4a1a1a; color: #ff7f7f; display: block; }
  table { width: 100%; border-collapse: collapse; font-size: 12px; }
  th { background: #0f3460; color: #aaa; padding: 6px 8px; text-align: left; font-weight: normal; }
  td { padding: 5px 8px; border-bottom: 1px solid #0f3460; }
  tr:hover td { background: #1f2f50; }
  .badge { display: inline-block; padding: 2px 7px; border-radius: 10px; font-size: 10px; font-weight: bold; }
  .badge-micro  { background: #1a3a4a; color: #4ea1ff; }
  .badge-carbon { background: #3a2a1a; color: #ff9f43; }
  .hint { font-size: 10px; color: #555; margin-top: 4px; }
  .section-hidden { display: none; }
  #port-info { font-size: 11px; color: #4ea1ff; margin-top: 8px; }
</style>
</head>
<body>
<header>
  <h1>&#9654; Carbomax Emulator</h1>
  <span>Emulador del dispositivo para pruebas locales</span>
</header>
<div class="container">

  <!-- Panel izquierdo: crear medición -->
  <div>
    <div class="card">
      <h2>Nueva medición</h2>
      <div class="tabs">
        <div class="tab active" id="tab-micro" onclick="switchMode('micro')">Microestructura</div>
        <div class="tab"        id="tab-carb"  onclick="switchMode('carb')">Carbono</div>
      </div>

      <div class="form-grid">
        <div>
          <label>Material</label>
          <input id="f-material" value="FcE500">
        </div>
        <div>
          <label>Lote / Colada</label>
          <input id="f-lot" placeholder="0050/26">
        </div>
        <div>
          <label>Canal</label>
          <input id="f-canal" value="1">
        </div>
        <div>
          <label>Observación</label>
          <input id="f-obs" placeholder="opcional">
        </div>
      </div>

      <hr style="border-color:#0f3460;margin:12px 0">

      <!-- Campos Microestructura -->
      <div id="fields-micro">
        <div class="form-grid">
          <div><label>Pico (°C)</label><input id="f-pico" type="number" value="1360" step="0.5"></div>
          <div><label>TL (°C)</label><input id="f-tl" type="number" value="1155" step="0.5"></div>
          <div><label>TSE (°C)</label><input id="f-tse" type="number" value="1148" step="0.5"></div>
          <div><label>TRE (°C)</label><input id="f-tre" type="number" value="1143" step="0.5"></div>
          <div><label>REC (°C)</label><input id="f-rec" type="number" value="12.0" step="0.1"></div>
          <div><label>Delta REC (°C/s)</label><input id="f-delta-rec" type="number" value="2.5" step="0.1"></div>
          <div><label>TF (°C)</label><input id="f-tf-m" type="number" value="1080" step="0.5"></div>
          <div><label>CE %</label><input id="f-ce-m" type="number" value="4.48" step="0.01"></div>
        </div>
        <p class="hint">La curva de temperatura se genera sintéticamente a partir de estos parámetros.</p>
      </div>

      <!-- Campos Carbono -->
      <div id="fields-carb" class="section-hidden">
        <div class="form-grid">
          <div><label>Pico (°C)</label><input id="f-pico-c" type="number" value="1360" step="0.5"></div>
          <div><label>TL (°C)</label><input id="f-tl-c" type="number" value="1155" step="0.5"></div>
          <div><label>TS / Solidus (°C)</label><input id="f-ts" type="number" value="1090" step="0.5"></div>
          <div><label>TF (°C)</label><input id="f-tf-c" type="number" value="1050" step="0.5"></div>
          <div><label>CE %</label><input id="f-ce-c" type="number" value="4.48" step="0.01"></div>
          <div><label>C %</label><input id="f-carbon" type="number" value="3.21" step="0.01"></div>
          <div class="form-grid full">
            <div><label>Si %</label><input id="f-silicon" type="number" value="2.15" step="0.01"></div>
          </div>
        </div>
        <p class="hint">C% y Si% se inyectan directamente en el detalle de la medición.</p>
      </div>

      <div style="margin-top:14px">
        <button class="btn btn-primary" onclick="createRecord()">&#43; Crear medición</button>
      </div>
      <div id="msg" class="msg"></div>
    </div>

    <div class="card" style="margin-top:14px">
      <h2>Conexión</h2>
      <p>Agregá esta IP en la app (campo <strong>IP equipo</strong>):</p>
      <div id="port-info">127.0.0.1:PORT_PLACEHOLDER</div>
      <p style="margin-top:8px;font-size:11px;color:#666">
        Los endpoints activos:<br>
        &nbsp;/getallidx.cgi &nbsp;/getdata.cgi &nbsp;/dataparam.cgi
      </p>
    </div>
  </div>

  <!-- Panel derecho: lista de mediciones -->
  <div class="card">
    <h2>Mediciones en el emulador <span id="count" style="color:#555;font-weight:normal"></span></h2>
    <table>
      <thead>
        <tr>
          <th>ID</th><th>Fecha</th><th>Modo</th><th>Material</th><th>Lote</th><th></th>
        </tr>
      </thead>
      <tbody id="records-body">
        <tr><td colspan="6" style="color:#555;text-align:center">Cargando...</td></tr>
      </tbody>
    </table>
  </div>
</div>

<script>
let _mode = 'micro';

document.getElementById('port-info').textContent = '127.0.0.1:' + location.port;

function switchMode(m) {
  _mode = m;
  document.getElementById('tab-micro').classList.toggle('active', m === 'micro');
  document.getElementById('tab-carb').classList.toggle('active', m === 'carb');
  document.getElementById('fields-micro').classList.toggle('section-hidden', m !== 'micro');
  document.getElementById('fields-carb').classList.toggle('section-hidden', m !== 'carb');
}

function showMsg(text, ok) {
  const el = document.getElementById('msg');
  el.textContent = text;
  el.className = 'msg ' + (ok ? 'ok' : 'err');
  setTimeout(() => { el.className = 'msg'; }, 4000);
}

async function createRecord() {
  const body = { mode: _mode };
  body.material  = document.getElementById('f-material').value;
  body.lot       = document.getElementById('f-lot').value;
  body.canal     = document.getElementById('f-canal').value;
  body.obs       = document.getElementById('f-obs').value;
  if (_mode === 'micro') {
    body.pico      = parseFloat(document.getElementById('f-pico').value);
    body.tl        = parseFloat(document.getElementById('f-tl').value);
    body.tse       = parseFloat(document.getElementById('f-tse').value);
    body.tre       = parseFloat(document.getElementById('f-tre').value);
    body.rec       = parseFloat(document.getElementById('f-rec').value);
    body.delta_rec = parseFloat(document.getElementById('f-delta-rec').value);
    body.tf        = parseFloat(document.getElementById('f-tf-m').value);
    body.ce        = parseFloat(document.getElementById('f-ce-m').value);
  } else {
    body.pico    = parseFloat(document.getElementById('f-pico-c').value);
    body.tl      = parseFloat(document.getElementById('f-tl-c').value);
    body.ts      = parseFloat(document.getElementById('f-ts').value);
    body.tf      = parseFloat(document.getElementById('f-tf-c').value);
    body.ce      = parseFloat(document.getElementById('f-ce-c').value);
    body.carbon  = parseFloat(document.getElementById('f-carbon').value);
    body.silicon = parseFloat(document.getElementById('f-silicon').value);
  }
  try {
    const r = await fetch('/api/create', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(body),
    });
    const data = await r.json();
    if (data.ok) {
      showMsg('Medicion creada — ID ' + data.id, true);
      loadRecords();
    } else {
      showMsg('Error: ' + data.error, false);
    }
  } catch(e) {
    showMsg('Error de red: ' + e, false);
  }
}

async function deleteRecord(id) {
  if (!confirm('Eliminar medicion ID ' + id + '?')) return;
  await fetch('/api/delete', {
    method: 'POST',
    headers: {'Content-Type': 'application/json'},
    body: JSON.stringify({id}),
  });
  loadRecords();
}

function fmtDate(raw) {
  // raw: "DDMMYYYY HHMMSS"
  try {
    const d = raw.replace(/(\d{2})(\d{2})(\d{4})\s+(\d{2})(\d{2})(\d{2})/, '$3-$2-$1T$4:$5:$6');
    return new Date(d).toLocaleString('es-AR', {day:'2-digit',month:'2-digit',year:'2-digit',hour:'2-digit',minute:'2-digit'});
  } catch { return raw; }
}

async function loadRecords() {
  try {
    const r = await fetch('/api/records');
    const data = await r.json();
    const tbody = document.getElementById('records-body');
    document.getElementById('count').textContent = '(' + data.records.length + ')';
    if (!data.records.length) {
      tbody.innerHTML = '<tr><td colspan="6" style="color:#555;text-align:center">Sin mediciones. Crea una desde el panel izquierdo.</td></tr>';
      return;
    }
    tbody.innerHTML = data.records.map(rec => {
      const cls  = rec.mode.toUpperCase().includes('CARB') ? 'badge-carbon' : 'badge-micro';
      const label = rec.mode.toUpperCase().includes('CARB') ? 'CARBONO' : 'MICRO';
      return `<tr>
        <td>${rec.id}</td>
        <td>${fmtDate(rec.date)}</td>
        <td><span class="badge ${cls}">${label}</span></td>
        <td>${rec.material}</td>
        <td>${rec.lot || '—'}</td>
        <td><button class="btn-danger" onclick="deleteRecord('${rec.id}')">Eliminar</button></td>
      </tr>`;
    }).join('');
  } catch(e) {
    document.getElementById('records-body').innerHTML = '<tr><td colspan="6" style="color:#e94560">Error cargando: '+e+'</td></tr>';
  }
}

loadRecords();
setInterval(loadRecords, 5000);
</script>
</body>
</html>
"""


# ── Punto de entrada ───────────────────────────────────────────────────────────

def _local_ip():
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        try:
            s.close()
        except Exception:
            pass


if __name__ == "__main__":
    _load_store()
    server = HTTPServer(("0.0.0.0", PORT), _Handler)
    print(f"Carbomax Emulator corriendo en http://127.0.0.1:{PORT}/")
    print(f"  LAN IP: http://{_local_ip()}:{PORT}/")
    print(f"  En la app cambiar 'IP equipo' a:  127.0.0.1:{PORT}")
    print(f"  Endpoints: /getallidx.cgi  /getdata.cgi  /dataparam.cgi")
    print(f"  Mediciones guardadas en: {STORE_FILE}")
    print("Ctrl+C para detener.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nDetenido.")
