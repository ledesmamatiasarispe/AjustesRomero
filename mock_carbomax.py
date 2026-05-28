#!/usr/bin/env python3
"""
Mock Carbomax — servidor HTTP que simula el dispositivo Carbomax.

Correlo con:  python3 mock_carbomax.py
Luego abrí:   http://localhost:8888  en el navegador para agregar lecturas.
Y lanzá la app con:  python3 run_with_mock.py
"""
import http.server
import json
import math
import random
import threading
import time
import urllib.parse
from datetime import datetime

# ── Estado global ─────────────────────────────────────────────────────────────

_records = {}   # {id: record_dict}
_lock    = threading.Lock()
_seq     = [1]

def _gen_id():
    with _lock:
        rid = f"MOCK{_seq[0]:04d}"
        _seq[0] += 1
    return rid

def _now_device():
    return datetime.now().strftime("%d%m%Y %H%M%S")

def _now_display():
    return datetime.now().strftime("%d/%m/%Y %H:%M")

def _gen_curve(c_pct, si_pct):
    """Genera una curva de enfriamiento térmica plausible."""
    tl = max(1080, min(1200, 1165 - 65 * c_pct + 8 * si_pct))
    n  = 300
    temps, deriv = [], [0]
    for i in range(n):
        base  = (1280 - tl) * math.exp(-i / 90) + tl - 4
        if 75 < i < 115:
            base += 4 * math.sin(math.pi * (i - 75) / 40)
        temps.append(round((base + random.uniform(-0.2, 0.2)) * 10))
    for i in range(1, n):
        deriv.append(temps[i] - temps[i - 1])
    return temps, deriv, round(tl * 10)

def _make_record(c_pct, si_pct, lote="TEST", modo="CARBO"):
    rid  = _gen_id()
    now  = _now_device()
    temps, deriv, tl_d = _gen_curve(c_pct, si_pct)
    detail = {
        "test_mode":  modo,
        "channel":    "1",
        "material":   "Fe",
        "lot":        lote,
        "obsevation": "",
        "carbon":     round(c_pct  * 100),
        "silicon":    round(si_pct * 100),
        "carbon_eq":  round((c_pct + si_pct / 3) * 100),
        "start_date": now,
        "stop_date":  now,
        "peak":       max(temps) if temps else 12800,
        "liquidus":   tl_d,
        "tse":        round(tl_d * 0.992),
        "tre":        round(tl_d * 0.975),
        "recalec":    round(tl_d * 0.965),
        "final":      temps[-1] if temps else 11000,
        "data_temp":  temps,
        "data_deriv": deriv,
        "tag1": "", "tag2": "", "tag3": "", "tag4": "",
    }
    return rid, {
        "id":     rid,
        "mode":   modo,
        "date":   now,
        "display_date": _now_display(),
        "c_pct":  c_pct,
        "si_pct": si_pct,
        "lote":   lote,
        "detail": detail,
        "_in_index": False,
    }

# Registro semilla (la app lo ve al seedear y lo ignora como "viejo")
_SEED_ID = "SEED0001"
_records[_SEED_ID] = {
    "id": _SEED_ID, "mode": "CARBO", "date": "01052026 080000",
    "display_date": "01/05/2026 08:00",
    "c_pct": 3.0, "si_pct": 1.5, "lote": "SEMILLA",
    "_in_index": False,
    "detail": {
        "test_mode": "CARBO", "channel": "1", "material": "Fe",
        "lot": "SEMILLA", "obsevation": "",
        "carbon": 300, "silicon": 150, "carbon_eq": 350,
        "start_date": "01052026 080000", "stop_date": "01052026 080500",
        "peak": 12800, "liquidus": 11900, "tse": 11850, "tre": 11800,
        "recalec": 11750, "final": 11500,
        "data_temp": [], "data_deriv": [],
        "tag1": "", "tag2": "", "tag3": "", "tag4": "",
    },
}

# ── HTML del panel ─────────────────────────────────────────────────────────────

_HTML = r"""<!DOCTYPE html>
<html lang="es">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Mock Carbomax</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:system-ui,sans-serif;background:#12121f;color:#d0d8e8;padding:28px;max-width:860px;margin:auto}
h1{color:#4fc3f7;margin-bottom:24px;font-size:1.5rem;display:flex;align-items:center;gap:10px}
h2{font-size:.95rem;color:#81d4fa;margin-bottom:14px;text-transform:uppercase;letter-spacing:.05em}
.card{background:#1a1f3a;border-radius:10px;padding:22px;margin-bottom:20px;border:1px solid #263050}
label{display:block;font-size:.82rem;color:#8090aa;margin-bottom:4px;margin-top:14px}
label:first-child{margin-top:0}
input[type=number],input[type=text]{
  width:100%;padding:9px 13px;border-radius:7px;border:1px solid #2e3d5a;
  background:#0d1a30;color:#d0d8e8;font-size:.95rem;outline:none}
input:focus{border-color:#4fc3f7}
.row{display:flex;gap:14px}
.row>div{flex:1}
button{
  margin-top:18px;padding:11px 28px;border:none;border-radius:7px;
  cursor:pointer;font-size:.95rem;font-weight:700;
  background:#4fc3f7;color:#050d1a;transition:background .15s}
button:hover{background:#81d4fa}
table{width:100%;border-collapse:collapse;font-size:.84rem}
thead th{text-align:left;color:#607090;padding:7px 10px;border-bottom:1px solid #263050;font-weight:600}
tbody td{padding:7px 10px;border-bottom:1px solid #1a2540}
tbody tr:hover{background:#1f2a47}
.badge{display:inline-block;padding:2px 9px;border-radius:10px;font-size:.72rem;font-weight:700}
.badge-semilla{background:#455a64;color:#cfd8dc}
.badge-pendiente{background:#e65100;color:#fff}
.badge-enviado{background:#2e7d32;color:#c8e6c9}
.empty{color:#4a5568;font-style:italic;padding:10px 0}
.tip{font-size:.8rem;color:#607090;margin-top:8px}
</style>
</head>
<body>
<h1>🔬 Mock Carbomax</h1>

<div class="card">
  <h2>Nueva lectura de carbono</h2>
  <form method="POST" action="/add">
    <div class="row">
      <div>
        <label>C (%)</label>
        <input type="number" name="carbon" step="0.01" min="2.0" max="5.0" value="3.45" required>
      </div>
      <div>
        <label>Si (%)</label>
        <input type="number" name="silicon" step="0.01" min="0.5" max="4.0" value="1.85" required>
      </div>
      <div>
        <label>Lote / etiqueta</label>
        <input type="text" name="lote" value="TEST001" maxlength="20">
      </div>
    </div>
    <button type="submit">➕ Agregar lectura</button>
  </form>
  <p class="tip">La app detecta el nuevo registro en el próximo ciclo de vigilancia (~20 s con dispositivo real, menos con mock).</p>
</div>

<div class="card">
  <h2>Registros</h2>
  <div id="tbl">__TABLE__</div>
</div>

<script>
setInterval(()=>{
  fetch('/status').then(r=>r.json()).then(d=>{
    document.getElementById('tbl').innerHTML = d.html;
  }).catch(()=>{});
}, 2000);
</script>
</body>
</html>"""

def _table_html():
    rows = list(_records.values())
    if not rows:
        return '<p class="empty">Sin registros.</p>'
    html = ('<table><thead><tr>'
            '<th>ID</th><th>C%</th><th>Si%</th><th>Lote</th><th>Fecha</th><th>Estado</th>'
            '</tr></thead><tbody>')
    for r in reversed(rows):
        rid = r["id"]
        if rid == _SEED_ID:
            badge = '<span class="badge badge-semilla">semilla</span>'
        elif r.get("_in_index"):
            badge = '<span class="badge badge-enviado">enviado a app</span>'
        else:
            badge = '<span class="badge badge-pendiente">pendiente</span>'
        html += (f'<tr><td>{rid}</td><td>{r["c_pct"]}</td><td>{r["si_pct"]}</td>'
                 f'<td>{r.get("lote","")}</td><td>{r.get("display_date","")}</td>'
                 f'<td>{badge}</td></tr>')
    return html + '</tbody></table>'

# ── HTTP handler ───────────────────────────────────────────────────────────────

class Handler(http.server.BaseHTTPRequestHandler):

    def do_GET(self):
        path = self.path.split("?")[0]

        if path in ("/", "/index.html"):
            with _lock:
                body = _HTML.replace("__TABLE__", _table_html()).encode()
            self._send(200, "text/html; charset=utf-8", body)

        elif path == "/status":
            with _lock:
                body = json.dumps({"html": _table_html()}).encode()
            self._send(200, "application/json", body)

        elif path == "/getallidx.cgi":
            with _lock:
                for r in _records.values():
                    r["_in_index"] = True
                rows = [{"id": r["id"], "mode": r["mode"], "date": r["date"]}
                        for r in _records.values()]
            body = json.dumps({"TableIndex": rows}).encode()
            self._send(200, "application/json", body)
            print(f"[MOCK] getallidx → {len(rows)} registros", flush=True)

        elif path == "/getdata.cgi":
            qs  = urllib.parse.parse_qs(self.path.split("?", 1)[-1] if "?" in self.path else "")
            rid = qs.get("btrqh", [""])[0]
            with _lock:
                r = _records.get(rid)
            if r:
                body = json.dumps({"TableData": [r["detail"]]}).encode()
                self._send(200, "application/json", body)
                print(f"[MOCK] getdata {rid} → C={r['c_pct']}% Si={r['si_pct']}%", flush=True)
            else:
                self._send(404, "application/json", b'{"error":"not found"}')

        else:
            self._send(404, "text/plain", b"Not found")

    def do_POST(self):
        if self.path == "/add":
            length = int(self.headers.get("Content-Length", 0))
            raw    = self.rfile.read(length).decode(errors="replace")
            params = urllib.parse.parse_qs(raw)
            try:
                c   = float(params.get("carbon",  ["3.45"])[0])
                si  = float(params.get("silicon", ["1.85"])[0])
                lot = (params.get("lote", ["TEST"])[0] or "TEST")[:20]
                rid, record = _make_record(c, si, lot)
                with _lock:
                    _records[rid] = record
                print(f"[MOCK] ✚ nuevo registro {rid}: C={c}% Si={si}% lote={lot}", flush=True)
            except Exception as ex:
                print(f"[MOCK] Error al agregar: {ex}", flush=True)
            self.send_response(303)
            self.send_header("Location", "/")
            self.end_headers()
        else:
            self._send(404, "text/plain", b"Not found")

    def _send(self, code, ctype, body):
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):
        pass


# ── Main ───────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port = 8888
    srv  = http.server.HTTPServer(("0.0.0.0", port), Handler)
    print(f"🔬 Mock Carbomax corriendo en http://localhost:{port}")
    print(f"   → Abrí esa URL en el navegador para agregar lecturas.")
    print(f"   → Lanzá la app con:  python3 run_with_mock.py")
    print()
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[MOCK] Servidor detenido.")
