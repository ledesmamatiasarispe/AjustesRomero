"use strict";

// camara.js — SPA de la cámara de calidad (kiosko para microscopio). Puerto de frontend/js/camara.js de
// ajuste_comp_web. Página STANDALONE (servida en /camara.html, no es una pestaña del shell del núcleo) --
// carga comun.js antes de este script para poder usar el namespace global "Ajuste" (apiFetch/deviceHeaders),
// pero no depende de nada más del shell.
//
// CAMBIO DELIBERADO vs. la app vieja: el backend original (quality_api.py / routers/camara.py) no exigía
// aprobación de dispositivo -- a propósito, "cualquiera en la red local que entre puede ver y analizar".
// Esta migración le dio auth por dispositivo consistente a cada router (ver rutas/camara.py), así que todas
// las llamadas de este archivo ahora mandan los headers X-Pie-Device-Id/Name vía Ajuste.apiFetch() (para
// JSON) o Ajuste.deviceHeaders() (para los endpoints que devuelven una imagen binaria, donde apiFetch no
// sirve porque siempre intenta parsear JSON). La PC del microscopio necesita aprobarse una vez, como
// cualquier otra pantalla de esta app.
//
// Flujo tipico: video en vivo (polling de un solo frame) -> "Capturar" congela un frame -> el usuario ajusta
// modo/umbral/calibracion -> "Analizar" manda ese frame congelado al servidor (quality_analyzer.py hace el
// trabajo pesado de OpenCV) -> se dibuja el overlay de resultado sobre un canvas superpuesto a la imagen.

// ── Estado global ────────────────────────────────────────────────────────────
const S = {
  live: true,

  // Canvas overlay
  zoom: 1.0,
  panX: 0,
  panY: 0,
  dragging: false,
  dragStart: null,
  imgNatW: 0,
  imgNatH: 0,

  // Calibración activa
  calId: null,
  calPxPerMm: null,   // extraído del selector cuando se carga
  calibrations: [],

  // Análisis
  mode: "nodular",
  threshold: 0,
  minArea: 100,
  useOpen: true,
  lastStats: null,
  overlayDataUrl: null,
  binaryDataUrl: null,
  showOverlay: false,
  showBinary: false,
  analyzing: false,

  // Medidas
  measuring: false,
  pendingPt: null,    // {fx, fy} en coords del frame real
  measurements: [],   // [{x1,y1,x2,y2, label, id}]
};

// ── Nodos DOM ────────────────────────────────────────────────────────────────
const n = {
  liveStream:    document.getElementById("liveStream"),
  capturedImg:   document.getElementById("capturedImg"),
  viewBox:       document.getElementById("viewBox"),
  overlay:       document.getElementById("overlay"),
  calSelect:     document.getElementById("calSelect"),
  btnReloadCal:  document.getElementById("btnReloadCal"),
  modeSelect:    document.getElementById("modeSelect"),
  threshSlider:  document.getElementById("threshSlider"),
  threshVal:     document.getElementById("threshVal"),
  minAreaInput:  document.getElementById("minAreaInput"),
  useOpenChk:    document.getElementById("useOpenChk"),
  btnCapture:    document.getElementById("btnCapture"),
  btnResume:     document.getElementById("btnResume"),
  btnMeasure:    document.getElementById("btnMeasure"),
  btnClearMeasures: document.getElementById("btnClearMeasures"),
  chkOverlay:    document.getElementById("chkOverlay"),
  chkBinary:     document.getElementById("chkBinary"),
  btnDownload:   document.getElementById("btnDownload"),
  btnPDF:        document.getElementById("btnPDF"),
  statusBar:     document.getElementById("statusBar"),
  statsContent:  document.getElementById("statsContent"),
  hint:          document.getElementById("hint"),
};

const ctx = n.overlay.getContext("2d");

// ── Helpers ──────────────────────────────────────────────────────────────────
function setStatus(msg, type = "") {
  n.statusBar.textContent = msg;
  n.statusBar.className = type;
}

function showHint(msg, ms = 2500) {
  n.hint.textContent = msg;
  n.hint.classList.add("visible");
  clearTimeout(showHint._t);
  showHint._t = setTimeout(() => n.hint.classList.remove("visible"), ms);
}

// Misma conversion de unidades que quality_analyzer.get_px_per_mm (Python,
// servidor) — duplicada aca para poder mostrar la escala/medidas en vivo
// en el canvas sin ida y vuelta al servidor; el analisis real (px/mm que
// cuenta para los resultados) siempre se recalcula server-side con cal_id.
function getCalPxPerMm() {
  const cal = S.calibrations.find(c => c.id === S.calId);
  if (!cal || !cal.px_per_unit) return null;
  const unit = cal.unit || "µm";
  const v = parseFloat(cal.px_per_unit);
  if (unit === "µm") return v * 1000;
  if (unit === "cm") return v / 10;
  return v;
}

// ── Barra de escala (como en microscopía) ───────────────────────────────────
function niceScaleLength(targetMm) {
  if (!(targetMm > 0) || !isFinite(targetMm)) return null;
  const steps = [1, 2, 5];
  const exp = Math.floor(Math.log10(targetMm));
  let best = null, bestDiff = Infinity;
  for (let e = exp - 1; e <= exp + 1; e++) {
    for (const s of steps) {
      const val = s * Math.pow(10, e);
      const diff = Math.abs(Math.log(val / targetMm));
      if (diff < bestDiff) { bestDiff = diff; best = val; }
    }
  }
  const mm = best;
  let unit, dispVal;
  if (mm < 1) { unit = "µm"; dispVal = mm * 1000; }
  else if (mm < 10) { unit = "mm"; dispVal = mm; }
  else { unit = "cm"; dispVal = mm / 10; }
  dispVal = Math.round(dispVal * 100) / 100;
  return { mm, label: `${dispVal} ${unit}` };
}

function drawScaleBar(c, cw, ch) {
  const pxPerMm = getCalPxPerMm();
  if (!pxPerMm || pxPerMm <= 0) return;
  const nice = niceScaleLength((cw * 0.18) / pxPerMm);
  if (!nice) return;
  const barPx = nice.mm * pxPerMm;
  if (!(barPx > 0) || barPx > cw * 0.6) return; // calibracion absurda -- no dibujar algo sin sentido

  const margin = Math.max(16, cw * 0.02);
  const barH = Math.max(3, cw / 400);
  const capH = barH * 4;
  const x2 = cw - margin;
  const x1 = x2 - barPx;
  const y = ch - margin;
  const fs = Math.max(14, cw / 55);

  c.save();
  c.lineCap = "butt";
  c.shadowColor = "rgba(0,0,0,0.9)";
  c.shadowBlur = 3;
  c.strokeStyle = "#fff";
  c.lineWidth = barH;
  c.beginPath();
  c.moveTo(x1, y); c.lineTo(x2, y);
  c.moveTo(x1, y - capH / 2); c.lineTo(x1, y + capH / 2);
  c.moveTo(x2, y - capH / 2); c.lineTo(x2, y + capH / 2);
  c.stroke();

  c.shadowBlur = 0;
  c.font = `bold ${fs}px system-ui`;
  c.textAlign = "center";
  c.textBaseline = "bottom";
  const labelX = (x1 + x2) / 2;
  const labelY = y - capH / 2 - 4;
  c.strokeStyle = "#000";
  c.lineWidth = 3;
  c.strokeText(nice.label, labelX, labelY);
  c.fillStyle = "#fff";
  c.fillText(nice.label, labelX, labelY);
  c.restore();
}

// ── Calibraciones ────────────────────────────────────────────────────────────
async function loadCalibrations() {
  try {
    const data = await Ajuste.apiFetch("/api/camara/calibraciones");
    S.calibrations = data.calibraciones || [];
    const effectiveId = data.effective_id || null;

    n.calSelect.innerHTML = '<option value="">Sin calibrar</option>';
    for (const cal of S.calibrations) {
      const opt = document.createElement("option");
      opt.value = cal.id;
      opt.textContent = cal.nombre + (cal.is_default ? " (defecto)" : "");
      n.calSelect.appendChild(opt);
    }
    if (effectiveId) {
      n.calSelect.value = effectiveId;
      S.calId = effectiveId;
    } else {
      S.calId = n.calSelect.value || null;
    }
  } catch (ex) {
    setStatus("Error cargando calibraciones", "error");
  }
}

n.calSelect.addEventListener("change", () => {
  S.calId = n.calSelect.value || null;
});

n.btnReloadCal.addEventListener("click", () => {
  loadCalibrations().then(() => showHint("Calibraciones actualizadas"));
});

// ── Controles de análisis ────────────────────────────────────────────────────
n.modeSelect.addEventListener("change", () => { S.mode = n.modeSelect.value; });

n.threshSlider.addEventListener("input", () => {
  const v = parseInt(n.threshSlider.value);
  S.threshold = v;
  n.threshVal.textContent = v === 0 ? "auto" : String(v);
});

n.minAreaInput.addEventListener("change", () => {
  S.minArea = Math.max(1, parseInt(n.minAreaInput.value) || 100);
});

n.useOpenChk.addEventListener("change", () => { S.useOpen = n.useOpenChk.checked; });

// ── Resize canvas overlay ────────────────────────────────────────────────────
const resizeObserver = new ResizeObserver(() => {
  const vb = document.getElementById("viewBox");
  n.overlay.width = vb.clientWidth;
  n.overlay.height = vb.clientHeight;
  drawOverlay();
});
resizeObserver.observe(document.getElementById("viewBox"));

// ── Transformaciones imagen ↔ canvas ─────────────────────────────────────────
function getDisplayRect() {
  const el = S.live ? n.liveStream : n.capturedImg;
  if (!el || el.hidden) return null;

  const cw = n.overlay.width;
  const ch = n.overlay.height;
  const natW = S.live ? (el.naturalWidth || cw) : (S.imgNatW || el.naturalWidth || cw);
  const natH = S.live ? (el.naturalHeight || ch) : (S.imgNatH || el.naturalHeight || ch);
  if (!natW || !natH) return null;

  const scale = Math.min(cw / natW, ch / natH);
  const dw = natW * scale;
  const dh = natH * scale;
  const dx = (cw - dw) / 2;
  const dy = (ch - dh) / 2;
  return { dx, dy, dw, dh, scale, natW, natH };
}

function canvasToFrame(cx, cy) {
  const r = getDisplayRect();
  if (!r) return null;
  const cx0 = n.overlay.width / 2;
  const cy0 = n.overlay.height / 2;
  const ix = (cx - cx0 - S.panX) / S.zoom + cx0;
  const iy = (cy - cy0 - S.panY) / S.zoom + cy0;
  const fx = (ix - r.dx) / r.scale;
  const fy = (iy - r.dy) / r.scale;
  return { fx, fy };
}

function frameToCanvas(fx, fy) {
  const r = getDisplayRect();
  if (!r) return null;
  const cx0 = n.overlay.width / 2;
  const cy0 = n.overlay.height / 2;
  const ix = fx * r.scale + r.dx;
  const iy = fy * r.scale + r.dy;
  const cx = (ix - cx0) * S.zoom + cx0 + S.panX;
  const cy = (iy - cy0) * S.zoom + cy0 + S.panY;
  return { cx, cy };
}

// ── Dibujar overlay ──────────────────────────────────────────────────────────
let _overlayImg = null;
let _binaryImg = null;

function _loadImg(dataUrl) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => resolve(null);
    img.src = "data:image/jpeg;base64," + dataUrl;
  });
}

async function updateOverlayImages() {
  _overlayImg = S.overlayDataUrl ? await _loadImg(S.overlayDataUrl) : null;
  _binaryImg = S.binaryDataUrl ? await _loadImg(S.binaryDataUrl) : null;
  drawOverlay();
}

function drawOverlay() {
  const cw = n.overlay.width;
  const ch = n.overlay.height;
  ctx.clearRect(0, 0, cw, ch);

  const r = getDisplayRect();
  if (!r) return;

  ctx.save();
  const cx0 = cw / 2;
  const cy0 = ch / 2;
  ctx.translate(cx0 + S.panX, cy0 + S.panY);
  ctx.scale(S.zoom, S.zoom);
  ctx.translate(-cx0, -cy0);

  if (S.showBinary && _binaryImg) {
    ctx.globalAlpha = 0.85;
    ctx.drawImage(_binaryImg, r.dx, r.dy, r.dw, r.dh);
    ctx.globalAlpha = 1;
  } else if (S.showOverlay && _overlayImg) {
    ctx.drawImage(_overlayImg, r.dx, r.dy, r.dw, r.dh);
  }

  ctx.restore();
  drawMeasurements();
}

function drawMeasurements() {
  for (const m of S.measurements) {
    const p1 = frameToCanvas(m.x1, m.y1);
    const p2 = frameToCanvas(m.x2, m.y2);
    if (!p1 || !p2) continue;
    ctx.beginPath();
    ctx.moveTo(p1.cx, p1.cy);
    ctx.lineTo(p2.cx, p2.cy);
    ctx.strokeStyle = "#ffcc44";
    ctx.lineWidth = 2;
    ctx.stroke();
    for (const p of [p1, p2]) {
      ctx.beginPath();
      ctx.arc(p.cx, p.cy, 4, 0, Math.PI * 2);
      ctx.fillStyle = "#ffcc44";
      ctx.fill();
    }
    const mx = (p1.cx + p2.cx) / 2;
    const my = (p1.cy + p2.cy) / 2 - 8;
    ctx.font = "bold 12px system-ui";
    ctx.fillStyle = "#000";
    ctx.strokeStyle = "#000";
    ctx.lineWidth = 3;
    ctx.strokeText(m.label, mx, my);
    ctx.fillStyle = "#ffcc44";
    ctx.fillText(m.label, mx, my);
  }

  if (S.pendingPt) {
    const p = frameToCanvas(S.pendingPt.fx, S.pendingPt.fy);
    if (p) {
      ctx.beginPath();
      ctx.arc(p.cx, p.cy, 5, 0, Math.PI * 2);
      ctx.fillStyle = "#4a9eff";
      ctx.fill();
    }
  }
}

// ── Stream en vivo por polling (reemplaza <img src="/api/camara/mjpeg">) ────
// Un <img> apuntando directo al multipart MJPEG puede acumular latencia con
// el uso -- pedir un frame por vez con fetch() en un loop auto-pautado evita
// el problema de raíz: nunca hay más de un pedido en vuelo. /frame devuelve
// JPEG binario, no JSON -- por eso usa fetch() crudo + Ajuste.deviceHeaders()
// en vez de Ajuste.apiFetch() (que siempre intenta parsear la respuesta como
// JSON y rompería con bytes de imagen).
let liveFrameTimer = null;
let liveFrameUrl = null;
const LIVE_POLL_INTERVAL_MS = 60;

function stopLivePolling() {
  if (liveFrameTimer) { clearTimeout(liveFrameTimer); liveFrameTimer = null; }
  // best-effort, no bloquea la UI ni importa si no llega (ej. al cerrar la
  // pestaña) -- sendBeacon no sirve aca porque el endpoint no acepta ese
  // Content-Type, asi que se usa fetch con keepalive.
  fetch("/api/camara/stream/stop", { method: "POST", keepalive: true, headers: Ajuste.deviceHeaders() }).catch(() => {});
}

async function pollLiveFrame() {
  if (!S.live) return;
  try {
    const r = await fetch("/api/camara/frame", { cache: "no-store", headers: Ajuste.deviceHeaders() });
    if (r.ok) {
      const blob = await r.blob();
      const url = URL.createObjectURL(blob);
      const prevUrl = liveFrameUrl;
      n.liveStream.src = url;
      liveFrameUrl = url;
      if (prevUrl) URL.revokeObjectURL(prevUrl);
    }
  } catch (ex) {
    // silencioso -- se reintenta en el proximo tick
  } finally {
    if (S.live) liveFrameTimer = setTimeout(pollLiveFrame, LIVE_POLL_INTERVAL_MS);
  }
}

function startLivePolling() {
  if (liveFrameTimer) return; // ya esta corriendo
  fetch("/api/camara/stream/start", { method: "POST", headers: Ajuste.deviceHeaders() }).catch(() => {});
  pollLiveFrame();
}

window.addEventListener("beforeunload", () => {
  fetch("/api/camara/stream/stop", { method: "POST", keepalive: true, headers: Ajuste.deviceHeaders() }).catch(() => {});
});

// ── Captura ──────────────────────────────────────────────────────────────────
// /capture devuelve JPEG binario -- mismo motivo que /frame arriba, fetch()
// crudo + headers manuales en vez de Ajuste.apiFetch().
n.btnCapture.addEventListener("click", async () => {
  setStatus("Capturando…");
  n.btnCapture.disabled = true;
  try {
    const r = await fetch("/api/camara/capture", { method: "POST", headers: Ajuste.deviceHeaders() });
    if (!r.ok) {
      const d = await r.json().catch(() => ({}));
      setStatus("Error al capturar: " + (d.error || r.status), "error");
      return;
    }
    const blob = await r.blob();
    const url = URL.createObjectURL(blob);
    await new Promise((res) => {
      n.capturedImg.onload = () => {
        S.imgNatW = n.capturedImg.naturalWidth;
        S.imgNatH = n.capturedImg.naturalHeight;
        res();
      };
      n.capturedImg.src = url;
    });

    S.live = false;
    stopLivePolling();
    n.liveStream.src = "";
    n.liveStream.style.display = "none";
    n.capturedImg.removeAttribute("hidden");
    n.capturedImg.style.display = "";

    S.lastStats = null;
    S.overlayDataUrl = null;
    S.binaryDataUrl = null;
    S.measurements = [];
    S.pendingPt = null;
    _overlayImg = null;
    _binaryImg = null;
    drawOverlay();

    n.btnResume.removeAttribute("hidden");
    n.chkOverlay.checked = false;
    n.chkBinary.checked = false;
    S.showOverlay = false;
    S.showBinary = false;

    setStatus("Imagen capturada — analizando…");
    const ok = await analyze();
    if (ok) {
      S.showOverlay = true;
      n.chkOverlay.checked = true;
      drawOverlay();
    }
  } catch (ex) {
    setStatus("Error de red: " + ex.message, "error");
  } finally {
    n.btnCapture.disabled = false;
  }
});

n.btnResume.addEventListener("click", () => {
  S.live = true;
  n.capturedImg.style.display = "none";
  n.capturedImg.setAttribute("hidden", "");
  startLivePolling();
  n.liveStream.style.display = "";
  n.btnResume.setAttribute("hidden", "");
  S.lastStats = null;
  S.overlayDataUrl = null;
  S.binaryDataUrl = null;
  S.measurements = [];
  S.pendingPt = null;
  _overlayImg = null;
  _binaryImg = null;
  S.zoom = 1;
  S.panX = 0;
  S.panY = 0;
  drawOverlay();
  renderStats(null);
  setStatus("Stream reanudado");
});

// ── Overlays toggle ──────────────────────────────────────────────────────────
n.chkOverlay.addEventListener("change", () => {
  S.showOverlay = n.chkOverlay.checked;
  if (S.showOverlay) { S.showBinary = false; n.chkBinary.checked = false; }
  drawOverlay();
});

n.chkBinary.addEventListener("change", () => {
  S.showBinary = n.chkBinary.checked;
  if (S.showBinary) { S.showOverlay = false; n.chkOverlay.checked = false; }
  drawOverlay();
});

// ── Medidas ──────────────────────────────────────────────────────────────────
n.btnMeasure.addEventListener("click", () => {
  S.measuring = !S.measuring;
  S.pendingPt = null;
  n.btnMeasure.classList.toggle("active", S.measuring);
  n.viewBox.style.cursor = S.measuring ? "crosshair" : "grab";
  showHint(S.measuring ? "Clic en punto 1 y luego punto 2" : "Modo medir desactivado");
});

n.btnClearMeasures.addEventListener("click", () => {
  S.measurements = [];
  S.pendingPt = null;
  drawOverlay();
});

function calcLabel(x1, y1, x2, y2) {
  const dist_px = Math.sqrt((x2 - x1) ** 2 + (y2 - y1) ** 2);
  const pxPerMm = getCalPxPerMm();
  if (pxPerMm) {
    const um = (dist_px / pxPerMm) * 1000;
    return um >= 1000
      ? (um / 1000).toFixed(2) + " mm"
      : um.toFixed(1) + " µm";
  }
  return dist_px.toFixed(0) + " px";
}

// ── Interacción con la vista (pan / zoom / medir) ────────────────────────────
n.viewBox.style.cursor = "grab";

n.viewBox.addEventListener("pointerdown", (e) => {
  if (e.target === document.getElementById("btnFullscreen")) return;
  if (S.measuring) return;
  S.dragging = true;
  S.dragStart = { x: e.clientX - S.panX, y: e.clientY - S.panY };
  n.viewBox.setPointerCapture(e.pointerId);
  n.viewBox.style.cursor = "grabbing";
});

n.viewBox.addEventListener("pointermove", (e) => {
  if (!S.dragging || S.measuring) return;
  S.panX = e.clientX - S.dragStart.x;
  S.panY = e.clientY - S.dragStart.y;
  drawOverlay();
});

n.viewBox.addEventListener("pointerup", () => {
  S.dragging = false;
  n.viewBox.style.cursor = S.measuring ? "crosshair" : "grab";
});

n.viewBox.addEventListener("click", (e) => {
  if (!S.measuring) return;
  if (e.target === document.getElementById("btnFullscreen")) return;
  const rect = n.overlay.getBoundingClientRect();
  const cx = e.clientX - rect.left;
  const cy = e.clientY - rect.top;
  const pt = canvasToFrame(cx, cy);
  if (!pt) return;

  if (!S.pendingPt) {
    S.pendingPt = { fx: pt.fx, fy: pt.fy };
    showHint("Clic en punto 2");
    drawOverlay();
  } else {
    const label = calcLabel(S.pendingPt.fx, S.pendingPt.fy, pt.fx, pt.fy);
    S.measurements.push({
      x1: S.pendingPt.fx, y1: S.pendingPt.fy,
      x2: pt.fx, y2: pt.fy,
      label,
      id: Date.now(),
    });
    S.pendingPt = null;
    showHint("Medida: " + label);
    drawOverlay();
  }
});

n.viewBox.addEventListener("wheel", (e) => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
  S.zoom = Math.max(1, Math.min(10, S.zoom * factor));
  if (S.zoom === 1) { S.panX = 0; S.panY = 0; }
  drawOverlay();
}, { passive: false });

// ── Análisis ─────────────────────────────────────────────────────────────────
// /analyze devuelve JSON siempre (incluso en error -- un {"error": "..."}
// con status 200, no una excepción HTTP), así que encaja bien con
// Ajuste.apiFetch() -- el try/catch sigue cubriendo errores de red/auth.
async function analyze() {
  if (S.live) { setStatus("Captura una imagen primero", "error"); return false; }
  if (S.analyzing) return false;
  S.analyzing = true;
  n.btnPDF.disabled = true;
  setStatus("Analizando…");
  try {
    const data = await Ajuste.apiFetch("/api/camara/analyze", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        mode: S.mode,
        threshold: S.threshold,
        min_area: S.minArea,
        use_open: S.useOpen,
        cal_id: S.calId || null,
      }),
    });
    if (data.error) { setStatus("Error: " + data.error, "error"); return false; }
    S.lastStats = data.stats;
    S.overlayDataUrl = data.overlay_jpeg || null;
    S.binaryDataUrl = data.binary_jpeg || null;
    await updateOverlayImages();
    renderStats(data.stats);
    setStatus("Análisis completo", "ok");
    return true;
  } catch (ex) {
    setStatus("Error de red: " + ex.message, "error");
    return false;
  } finally {
    S.analyzing = false;
    n.btnPDF.disabled = false;
  }
}

// ── Render estadísticas ───────────────────────────────────────────────────────
function renderStats(stats) {
  if (!stats) {
    n.statsContent.innerHTML = '<p class="stats-empty">Sin análisis.<br>Capturá una imagen para ver los resultados.</p>';
    return;
  }

  const row = (key, val) =>
    `<div class="stats-row"><span class="s-key">${key}</span><span class="s-val">${val}</span></div>`;

  let html = "";

  if (S.mode === "nodular") {
    html += `<div class="stats-title">Análisis Nodular</div>`;
    html += row("Partículas", stats.n_total ?? "—");
    html += row("Densidad", stats.n_mm2 != null ? stats.n_mm2 + " /mm²" : "—");
    html += row("Nodularidad", stats.nodularidad != null ? stats.nodularidad + " %" : "—");
    html += row("Vermicular", stats.vermicular != null ? stats.vermicular + " %" : "—");
    html += row("Ø promedio", stats.diam_prom_um != null ? stats.diam_prom_um + " µm" : "—");
    html += row("Ø máximo", stats.diam_max_um != null ? stats.diam_max_um + " µm" : "—");
    html += row("Ø mínimo", stats.diam_min_um != null ? stats.diam_min_um + " µm" : "—");
    html += row("Tamaño clase", stats.tam_grafito_clase || "—");
  } else {
    html += `<div class="stats-title">Análisis Laminar</div>`;
    html += row("Laminillas", stats.n_total ?? "—");
    html += row("Densidad", stats.n_mm2 != null ? stats.n_mm2 + " /mm²" : "—");
    html += row("Long. prom.", stats.long_prom_um != null ? stats.long_prom_um + " µm" : "—");
    html += row("Long. máx.", stats.long_max_um != null ? stats.long_max_um + " µm" : "—");
    html += row("Long. mín.", stats.long_min_um != null ? stats.long_min_um + " µm" : "—");
    html += row("Largo/ancho", stats.aspect_ratio_prom ?? "—");
    html += row("Morfología", stats.morfologia_label || stats.morfologia_iso || "—");
    html += row("Tamaño clase", stats.tam_clase || "—");
    if (stats.n_mns) html += row("Posibles MnS", stats.n_mns);
  }

  const counts = stats.counts || {};
  if (Object.keys(counts).length) {
    html += `<div class="stats-title" style="margin-top:10px">Distribución por clase</div>`;
    html += `<table class="dist-table"><thead><tr><th>Clase</th><th>N</th></tr></thead><tbody>`;
    const totalN = Object.values(counts).reduce((a, b) => a + b, 0);
    for (const [cls, cnt] of Object.entries(counts)) {
      const short = cls.replace("Clase ", "C").split(" (")[0];
      const pct = totalN ? Math.round(cnt / totalN * 100) : 0;
      html += `<tr><td>${short}</td><td>${cnt} (${pct}%)</td></tr>`;
    }
    html += `</tbody></table>`;
  }

  if (S.measurements.length) {
    html += `<div class="stats-title" style="margin-top:10px">Medidas</div>`;
    html += `<table class="meas-table"><tbody>`;
    S.measurements.forEach((m, i) => {
      html += `<tr><td style="color:var(--fg2)">${i + 1}.</td><td>${m.label}</td></tr>`;
    });
    html += `</tbody></table>`;
  }

  n.statsContent.innerHTML = html;
}

// ── Compositar imagen base + overlay/binary + medidas en un solo canvas ──────
function buildComposedCanvas() {
  const tmp = document.createElement("canvas");
  tmp.width = S.imgNatW || n.overlay.width;
  tmp.height = S.imgNatH || n.overlay.height;
  const tc = tmp.getContext("2d");

  tc.drawImage(n.capturedImg, 0, 0, tmp.width, tmp.height);

  if (S.showBinary && _binaryImg) {
    tc.globalAlpha = 0.85;
    tc.drawImage(_binaryImg, 0, 0, tmp.width, tmp.height);
    tc.globalAlpha = 1;
  } else if (S.showOverlay && _overlayImg) {
    tc.drawImage(_overlayImg, 0, 0, tmp.width, tmp.height);
  }

  for (const m of S.measurements) {
    tc.beginPath();
    tc.moveTo(m.x1, m.y1);
    tc.lineTo(m.x2, m.y2);
    tc.strokeStyle = "#ffcc44";
    tc.lineWidth = Math.max(2, tmp.width / 600);
    tc.stroke();
    for (const [px, py] of [[m.x1, m.y1], [m.x2, m.y2]]) {
      tc.beginPath();
      tc.arc(px, py, 5, 0, Math.PI * 2);
      tc.fillStyle = "#ffcc44";
      tc.fill();
    }
    const mx = (m.x1 + m.x2) / 2;
    const my = (m.y1 + m.y2) / 2 - 12;
    const fs = Math.max(14, tmp.width / 60);
    tc.font = `bold ${fs}px system-ui`;
    tc.strokeStyle = "#000";
    tc.lineWidth = 3;
    tc.strokeText(m.label, mx, my);
    tc.fillStyle = "#ffcc44";
    tc.fillText(m.label, mx, my);
  }
  drawScaleBar(tc, tmp.width, tmp.height);
  return tmp;
}

// ── Descargar imagen ─────────────────────────────────────────────────────────
n.btnDownload.addEventListener("click", () => {
  if (S.live) { showHint("Captura una imagen primero"); return; }
  buildComposedCanvas().toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `calidad_${new Date().toISOString().slice(0,19).replace(/:/g,"-")}.png`;
    a.click();
  }, "image/png");
});

// ── Guardar en informe de Calidad ────────────────────────────────────────────
const HINT_REPORT_ID = new URLSearchParams(location.search).get("report_id");
const btnSaveToReport = document.getElementById("btnSaveToReport");
const selTargetLote = document.getElementById("targetLote");
const selTargetMaterial = document.getElementById("targetMaterial");
let SAVE_TARGETS = [];

function materialsForLote(lote) {
  return [...new Set(SAVE_TARGETS.filter((t) => t.lote === lote).map((t) => t.material))];
}

function fillMaterialSelect(preferMaterial) {
  const mats = materialsForLote(selTargetLote.value);
  selTargetMaterial.innerHTML = mats.length
    ? mats.map((m) => `<option value="${m}">${m}</option>`).join("")
    : `<option value="">(sin materiales)</option>`;
  if (preferMaterial && mats.includes(preferMaterial)) selTargetMaterial.value = preferMaterial;
}

async function loadSaveTargets() {
  try {
    const data = await Ajuste.apiFetch("/api/camara/report-targets");
    SAVE_TARGETS = data.targets || [];
  } catch (ex) {
    setStatus("No se pudo cargar la lista de informes: " + ex.message, "error");
    return;
  }
  const lotes = [...new Set(SAVE_TARGETS.map((t) => t.lote))];
  selTargetLote.innerHTML = lotes.length
    ? lotes.map((l) => `<option value="${l}">${l}</option>`).join("")
    : `<option value="">(sin informes)</option>`;

  const hinted = HINT_REPORT_ID ? SAVE_TARGETS.find((t) => t.report_id === HINT_REPORT_ID) : null;
  if (hinted) selTargetLote.value = hinted.lote;
  fillMaterialSelect(hinted ? hinted.material : null);
}
selTargetLote.addEventListener("change", () => fillMaterialSelect());
loadSaveTargets();

const btnAnalyzeAndSave = document.getElementById("btnAnalyzeAndSave");

function loadImageFromBlob(blob) {
  return new Promise((resolve, reject) => {
    const img = new Image();
    const url = URL.createObjectURL(blob);
    img.onload = () => resolve({ img, url });
    img.onerror = () => reject(new Error("No se pudo decodificar el cuadro"));
    img.src = url;
  });
}

function loadImageFromB64(b64) {
  return new Promise((resolve, reject) => {
    if (!b64) { resolve(null); return; }
    const img = new Image();
    img.onload = () => resolve(img);
    img.onerror = () => reject(new Error("No se pudo decodificar el overlay"));
    img.src = "data:image/jpeg;base64," + b64;
  });
}

function buildCanvasFromFreshImage(img, overlayImg) {
  const tmp = document.createElement("canvas");
  tmp.width = img.naturalWidth;
  tmp.height = img.naturalHeight;
  const tc = tmp.getContext("2d");
  tc.drawImage(img, 0, 0, tmp.width, tmp.height);
  if (overlayImg) tc.drawImage(overlayImg, 0, 0, tmp.width, tmp.height);
  drawScaleBar(tc, tmp.width, tmp.height);
  return tmp;
}

async function handleSaveToReport(withAnalysis) {
  const target = SAVE_TARGETS.find((t) => t.lote === selTargetLote.value && t.material === selTargetMaterial.value);
  if (!target) {
    setStatus(`No existe informe para ${selTargetLote.value || "(sin sesión)"} / ${selTargetMaterial.value || "(sin material)"} — creá el informe en Calidad primero.`, "error");
    return;
  }
  const btn = withAnalysis ? btnAnalyzeAndSave : btnSaveToReport;
  btn.disabled = true;
  let revokeUrl = null;
  try {
    let canvas;
    if (S.live) {
      setStatus(withAnalysis ? "Analizando…" : "Guardando…");
      // /capture devuelve JPEG binario -- fetch() crudo + headers manuales (ver nota arriba de pollLiveFrame).
      const r = await fetch("/api/camara/capture", { method: "POST", headers: Ajuste.deviceHeaders() });
      if (!r.ok) {
        const d = await r.json().catch(() => ({}));
        setStatus("Error al tomar el cuadro actual: " + (d.error || r.status), "error");
        return;
      }
      const { img, url } = await loadImageFromBlob(await r.blob());
      revokeUrl = url;
      let overlayImg = null;
      if (withAnalysis) {
        const data = await Ajuste.apiFetch("/api/camara/analyze", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ mode: S.mode, threshold: S.threshold, min_area: S.minArea, use_open: S.useOpen, cal_id: S.calId || null }),
        });
        if (data.error) { setStatus("Error al analizar: " + data.error, "error"); return; }
        overlayImg = await loadImageFromB64(data.overlay_jpeg);
        setStatus("Guardando en el informe…");
      }
      canvas = buildCanvasFromFreshImage(img, overlayImg);
    } else {
      if (withAnalysis && !S.lastStats) {
        const ok = await analyze();
        if (!ok) return;
      }
      setStatus("Guardando en el informe…");
      canvas = buildComposedCanvas();
    }

    const dataUrl = canvas.toDataURL("image/jpeg", 0.92);
    const b64 = dataUrl.split(",")[1];
    const comentario = window.prompt("Comentario para esta imagen (opcional):", "") || "";
    try {
      await Ajuste.apiFetch(`/api/camara/save-to-report/${target.report_id}`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ image_jpeg: b64, comentario }),
      });
    } catch (ex2) {
      setStatus("Error al guardar: " + (ex2.detail?.error || ex2.message), "error");
      return;
    }
    setStatus(`Imagen guardada en el informe (${target.lote} / ${target.material}).`, "ok");
    showHint("Guardada en el informe");
  } catch (ex) {
    setStatus("Error: " + ex.message, "error");
  } finally {
    if (revokeUrl) URL.revokeObjectURL(revokeUrl);
    btn.disabled = false;
  }
}

btnSaveToReport.addEventListener("click", () => handleSaveToReport(false));
btnAnalyzeAndSave.addEventListener("click", () => handleSaveToReport(true));

// ── Calcular y descargar PDF ─────────────────────────────────────────────────
n.btnPDF.addEventListener("click", async () => {
  if (S.live) { showHint("Captura una imagen primero"); return; }
  if (!S.lastStats) {
    const ok = await analyze();
    if (!ok) return;
  }

  setStatus("Generando PDF…");
  n.btnPDF.disabled = true;

  try {
    const { jsPDF } = window.jspdf;
    const doc = new jsPDF({ orientation: "portrait", unit: "mm", format: "a4" });

    const pw = doc.internal.pageSize.getWidth();
    const ph = doc.internal.pageSize.getHeight();
    const margin = 12;
    let y = margin;

    doc.setFontSize(14);
    doc.setFont(undefined, "bold");
    doc.text("Análisis Microestructural de Calidad", margin, y);
    y += 8;
    doc.setFontSize(9);
    doc.setFont(undefined, "normal");
    doc.setTextColor(100);
    const fecha = new Date().toLocaleString("es-AR");
    const calNombre = S.calibrations.find(c => c.id === S.calId)?.nombre || "Sin calibrar";
    doc.text(`Fecha: ${fecha}   |   Calibración: ${calNombre}   |   Modo: ${S.mode}`, margin, y);
    doc.setTextColor(0);
    y += 6;
    doc.setDrawColor(180);
    doc.line(margin, y, pw - margin, y);
    y += 5;

    const tmp = document.createElement("canvas");
    tmp.width = S.imgNatW || 1280;
    tmp.height = S.imgNatH || 960;
    const tc = tmp.getContext("2d");
    tc.drawImage(n.capturedImg, 0, 0, tmp.width, tmp.height);
    if (S.showBinary && _binaryImg) {
      tc.globalAlpha = 0.85;
      tc.drawImage(_binaryImg, 0, 0, tmp.width, tmp.height);
      tc.globalAlpha = 1;
    } else if (_overlayImg) {
      tc.drawImage(_overlayImg, 0, 0, tmp.width, tmp.height);
    }
    for (const m of S.measurements) {
      tc.beginPath(); tc.moveTo(m.x1, m.y1); tc.lineTo(m.x2, m.y2);
      tc.strokeStyle = "#ffcc44"; tc.lineWidth = Math.max(2, tmp.width / 600); tc.stroke();
      for (const [px, py] of [[m.x1, m.y1], [m.x2, m.y2]]) {
        tc.beginPath(); tc.arc(px, py, 5, 0, Math.PI * 2);
        tc.fillStyle = "#ffcc44"; tc.fill();
      }
      const fs = Math.max(14, tmp.width / 60);
      tc.font = `bold ${fs}px system-ui`;
      tc.strokeStyle = "#000"; tc.lineWidth = 3; tc.strokeText(m.label, (m.x1+m.x2)/2, (m.y1+m.y2)/2-12);
      tc.fillStyle = "#ffcc44"; tc.fillText(m.label, (m.x1+m.x2)/2, (m.y1+m.y2)/2-12);
    }
    drawScaleBar(tc, tmp.width, tmp.height);
    const imgData = tmp.toDataURL("image/jpeg", 0.92);
    const maxImgH = 90;
    const maxImgW = pw - 2 * margin;
    const ar = tmp.width / tmp.height;
    let imgW = maxImgW;
    let imgH = imgW / ar;
    if (imgH > maxImgH) { imgH = maxImgH; imgW = imgH * ar; }
    doc.addImage(imgData, "JPEG", margin, y, imgW, imgH);
    y += imgH + 6;

    doc.setDrawColor(200);
    doc.line(margin, y, pw - margin, y);
    y += 4;

    const stats = S.lastStats;
    let rows = [];
    if (S.mode === "nodular") {
      rows = [
        ["Partículas totales", stats.n_total ?? "—"],
        ["Densidad (nód/mm²)", stats.n_mm2 ?? "—"],
        ["Nodularidad (%)", stats.nodularidad ?? "—"],
        ["Vermicular (%)", stats.vermicular ?? "—"],
        ["Ø promedio (µm)", stats.diam_prom_um ?? "—"],
        ["Ø máximo (µm)", stats.diam_max_um ?? "—"],
        ["Ø mínimo (µm)", stats.diam_min_um ?? "—"],
        ["Tamaño clase", stats.tam_grafito_clase || "—"],
      ];
    } else {
      rows = [
        ["Laminillas totales", stats.n_total ?? "—"],
        ["Densidad (lam/mm²)", stats.n_mm2 ?? "—"],
        ["Long. promedio (µm)", stats.long_prom_um ?? "—"],
        ["Long. máxima (µm)", stats.long_max_um ?? "—"],
        ["Long. mínima (µm)", stats.long_min_um ?? "—"],
        ["Largo/ancho prom.", stats.aspect_ratio_prom ?? "—"],
        ["Morfología ISO", stats.morfologia_label || stats.morfologia_iso || "—"],
        ["Tamaño clase", stats.tam_clase || "—"],
        ["Posibles MnS", stats.n_mns ?? 0],
      ];
    }

    doc.autoTable({
      startY: y,
      head: [["Parámetro", "Valor"]],
      body: rows,
      margin: { left: margin, right: margin },
      styles: { fontSize: 9, cellPadding: 2 },
      headStyles: { fillColor: [40, 80, 140], textColor: 255, fontStyle: "bold" },
      alternateRowStyles: { fillColor: [245, 245, 252] },
    });
    y = doc.lastAutoTable.finalY + 6;

    const counts = stats.counts || {};
    const countRows = Object.entries(counts).map(([cls, cnt]) => {
      const short = cls.replace("Clase ", "C").split(" (")[0];
      return [short, cnt];
    });
    if (countRows.length) {
      doc.autoTable({
        startY: y,
        head: [["Clase ISO", "Cantidad"]],
        body: countRows,
        margin: { left: margin, right: margin },
        styles: { fontSize: 9, cellPadding: 2 },
        headStyles: { fillColor: [40, 100, 60], textColor: 255, fontStyle: "bold" },
        alternateRowStyles: { fillColor: [245, 252, 245] },
      });
      y = doc.lastAutoTable.finalY + 6;
    }

    if (S.measurements.length) {
      const measRows = S.measurements.map((m, i) => [i + 1, m.label]);
      doc.autoTable({
        startY: y,
        head: [["#", "Distancia"]],
        body: measRows,
        margin: { left: margin, right: margin },
        styles: { fontSize: 9, cellPadding: 2 },
        headStyles: { fillColor: [100, 80, 20], textColor: 255, fontStyle: "bold" },
      });
    }

    const fname = `analisis_calidad_${new Date().toISOString().slice(0,10)}.pdf`;
    doc.save(fname);
    setStatus("PDF descargado", "ok");
  } catch (ex) {
    setStatus("Error generando PDF: " + ex.message, "error");
    console.error(ex);
  } finally {
    n.btnPDF.disabled = false;
  }
});

// ── Pantalla completa ─────────────────────────────────────────────────────────
document.getElementById("btnFullscreen").addEventListener("click", () => {
  const full = document.body.classList.toggle("fs");
  document.getElementById("btnFullscreen").textContent = full ? "✕" : "⛶";
});

// ── Init ─────────────────────────────────────────────────────────────────────
loadCalibrations();
drawOverlay();
startLivePolling();
setStatus("Stream en vivo. Presioná Capturar para congelar la imagen.");
