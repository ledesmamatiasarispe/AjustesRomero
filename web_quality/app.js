"use strict";

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

function getCalPxPerMm() {
  const cal = S.calibrations.find(c => c.id === S.calId);
  if (!cal || !cal.px_per_unit) return null;
  const unit = cal.unit || "µm";
  const v = parseFloat(cal.px_per_unit);
  if (unit === "µm") return v * 1000;
  if (unit === "cm") return v / 10;
  return v;
}

// ── Calibraciones ────────────────────────────────────────────────────────────
async function loadCalibrations() {
  try {
    const r = await fetch("/api/calibraciones");
    const data = await r.json();
    S.calibrations = data.calibraciones || [];
    const effectiveId = data.effective_id || null;

    // Reconstruir select
    n.calSelect.innerHTML = '<option value="">Sin calibrar</option>';
    for (const cal of S.calibrations) {
      const opt = document.createElement("option");
      opt.value = cal.id;
      opt.textContent = cal.nombre + (cal.is_default ? " (defecto)" : "");
      n.calSelect.appendChild(opt);
    }
    // Preseleccionar effective_id
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
// La imagen (live o capturada) se muestra con object-fit:contain.
// Para medidas y overlays necesitamos saber las coords del frame real.

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

// Coords canvas → coords del frame natural (aplicando zoom/pan)
function canvasToFrame(cx, cy) {
  const r = getDisplayRect();
  if (!r) return null;

  // El zoom/pan se aplica sobre el display rect
  // (center del canvas es el punto de referencia del zoom)
  const cx0 = n.overlay.width / 2;
  const cy0 = n.overlay.height / 2;
  // Invertir zoom/pan
  const ix = (cx - cx0 - S.panX) / S.zoom + cx0;
  const iy = (cy - cy0 - S.panY) / S.zoom + cy0;
  // Invertir object-fit:contain
  const fx = (ix - r.dx) / r.scale;
  const fy = (iy - r.dy) / r.scale;
  return { fx, fy };
}

// Coords del frame natural → coords canvas
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
  // Aplicar zoom/pan centrado en el canvas
  const cx0 = cw / 2;
  const cy0 = ch / 2;
  ctx.translate(cx0 + S.panX, cy0 + S.panY);
  ctx.scale(S.zoom, S.zoom);
  ctx.translate(-cx0, -cy0);

  // Dibujar overlay o binary si están activos
  if (S.showBinary && _binaryImg) {
    ctx.globalAlpha = 0.85;
    ctx.drawImage(_binaryImg, r.dx, r.dy, r.dw, r.dh);
    ctx.globalAlpha = 1;
  } else if (S.showOverlay && _overlayImg) {
    ctx.drawImage(_overlayImg, r.dx, r.dy, r.dw, r.dh);
  }

  ctx.restore();

  // Medidas (sin zoom/pan para que las coordenadas del canvas sean directas)
  // Las medidas se transforman manualmente con frameToCanvas
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
    // Puntos extremos
    for (const p of [p1, p2]) {
      ctx.beginPath();
      ctx.arc(p.cx, p.cy, 4, 0, Math.PI * 2);
      ctx.fillStyle = "#ffcc44";
      ctx.fill();
    }
    // Etiqueta
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

  // Punto pendiente
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

// ── Captura ──────────────────────────────────────────────────────────────────
n.btnCapture.addEventListener("click", async () => {
  setStatus("Capturando…");
  n.btnCapture.disabled = true;
  try {
    const r = await fetch("/api/capture", { method: "POST" });
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
    n.liveStream.src = "";
    n.liveStream.style.display = "none";
    n.capturedImg.removeAttribute("hidden");
    n.capturedImg.style.display = "";

    // Limpiar análisis anterior
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
  n.liveStream.src = "/api/mjpeg?t=" + Date.now();
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
// Los eventos van al #viewBox (no al canvas) para que el botón de pantalla
// completa —también hijo de #viewBox— pueda recibir sus propios clics.
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

// Zoom con rueda
n.viewBox.addEventListener("wheel", (e) => {
  e.preventDefault();
  const factor = e.deltaY < 0 ? 1.15 : 1 / 1.15;
  S.zoom = Math.max(1, Math.min(10, S.zoom * factor));
  if (S.zoom === 1) { S.panX = 0; S.panY = 0; }
  drawOverlay();
}, { passive: false });

// ── Análisis ─────────────────────────────────────────────────────────────────
async function analyze() {
  if (S.live) { setStatus("Captura una imagen primero", "error"); return false; }
  if (S.analyzing) return false;
  S.analyzing = true;
  n.btnPDF.disabled = true;
  setStatus("Analizando…");
  try {
    const r = await fetch("/api/analyze", {
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
    const data = await r.json();
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

  // Distribución por clase
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

  // Medidas actuales
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

// ── Descargar imagen ─────────────────────────────────────────────────────────
n.btnDownload.addEventListener("click", () => {
  if (S.live) { showHint("Captura una imagen primero"); return; }
  const tmp = document.createElement("canvas");
  tmp.width = S.imgNatW || n.overlay.width;
  tmp.height = S.imgNatH || n.overlay.height;
  const tc = tmp.getContext("2d");

  // Dibujar imagen base
  tc.drawImage(n.capturedImg, 0, 0, tmp.width, tmp.height);

  // Overlay / binary encima
  if (S.showBinary && _binaryImg) {
    tc.globalAlpha = 0.85;
    tc.drawImage(_binaryImg, 0, 0, tmp.width, tmp.height);
    tc.globalAlpha = 1;
  } else if (S.showOverlay && _overlayImg) {
    tc.drawImage(_overlayImg, 0, 0, tmp.width, tmp.height);
  }

  // Medidas en coords del frame real
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

  tmp.toBlob((blob) => {
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `calidad_${new Date().toISOString().slice(0,19).replace(/:/g,"-")}.png`;
    a.click();
  }, "image/png");
});

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

    // ── Encabezado ──
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

    // ── Imagen ──
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
    const imgData = tmp.toDataURL("image/jpeg", 0.92);
    const maxImgH = 90;
    const maxImgW = pw - 2 * margin;
    const ar = tmp.width / tmp.height;
    let imgW = maxImgW;
    let imgH = imgW / ar;
    if (imgH > maxImgH) { imgH = maxImgH; imgW = imgH * ar; }
    doc.addImage(imgData, "JPEG", margin, y, imgW, imgH);
    y += imgH + 6;

    // ── Tabla de estadísticas ──
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

    // ── Distribución por clase ──
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

    // ── Medidas ──
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
  // El ResizeObserver redibuja el canvas automáticamente al cambiar tamaño
});

// ── Init ─────────────────────────────────────────────────────────────────────
loadCalibrations();
drawOverlay();
setStatus("Stream en vivo. Presioná Capturar para congelar la imagen.");

// ── Chat ─────────────────────────────────────────────────────────────────────
const Chat = (() => {
  let _user = localStorage.getItem("chatUser") || null;
  let _pass = localStorage.getItem("chatPass") || null;
  let _lastId = 0;
  let _sse = null;

  const el = {
    panel:    document.getElementById("chatPanel"),
    header:   document.getElementById("chatHeader"),
    toggle:   document.getElementById("btnChatToggle"),
    body:     document.getElementById("chatBody"),
    login:    document.getElementById("chatLogin"),
    active:   document.getElementById("chatActive"),
    userIn:   document.getElementById("chatUser"),
    passIn:   document.getElementById("chatPass"),
    btnLogin: document.getElementById("btnChatLogin"),
    btnReg:   document.getElementById("btnChatRegister"),
    errMsg:   document.getElementById("chatLoginError"),
    messages: document.getElementById("chatMessages"),
    input:    document.getElementById("chatInput"),
    btnSend:  document.getElementById("btnChatSend"),
  };

  function setErr(msg) { el.errMsg.textContent = msg || ""; }

  function expand() {
    el.panel.classList.remove("collapsed", "has-new");
    el.toggle.textContent = "▼";
  }

  function _renderMsg(msg) {
    const isManager = msg.is_manager;
    const isOwn = !isManager && msg.username === _user;
    const div = document.createElement("div");
    div.className = "chat-msg " + (isManager ? "manager" : isOwn ? "own" : "other");
    const auth = document.createElement("div");
    auth.className = "chat-msg-author";
    auth.textContent = msg.username;
    const body = document.createElement("div");
    body.textContent = msg.body;
    div.appendChild(auth);
    div.appendChild(body);
    el.messages.appendChild(div);
    el.messages.scrollTop = el.messages.scrollHeight;
    if (msg.id > _lastId) _lastId = msg.id;
  }

  async function _fetchMsgs(since) {
    try {
      const r = await fetch("/api/chat/messages?since=" + (since || 0));
      if (!r.ok) return;
      const msgs = await r.json();
      msgs.forEach(_renderMsg);
    } catch (_) {}
  }

  function _connectSSE() {
    if (_sse) { _sse.close(); _sse = null; }
    _sse = new EventSource("/api/chat/events");
    _sse.addEventListener("new_message", () => {
      _fetchMsgs(_lastId);
      if (el.panel.classList.contains("collapsed")) {
        el.panel.classList.add("has-new");
        expand();
      }
    });
    _sse.onerror = () => {
      if (_sse) { _sse.close(); _sse = null; }
      setTimeout(_connectSSE, 5000);
    };
  }

  function _showActive() {
    el.login.hidden = true;
    el.active.removeAttribute("hidden");
  }

  async function _doAuth(register) {
    const u = el.userIn.value.trim();
    const p = el.passIn.value;
    if (!u || !p) { setErr("Completá nombre y contraseña"); return; }
    setErr("");
    el.btnLogin.disabled = true;
    el.btnReg.disabled = true;
    try {
      const r = await fetch(register ? "/api/chat/register" : "/api/chat/login", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: u, password: p }),
      });
      const data = await r.json();
      if (data.error) {
        setErr(data.error);
      } else {
        _user = u; _pass = p;
        localStorage.setItem("chatUser", u);
        localStorage.setItem("chatPass", p);
        _showActive();
        _fetchMsgs(0);
        _connectSSE();
      }
    } catch (_) {
      setErr("Error de red");
    } finally {
      el.btnLogin.disabled = false;
      el.btnReg.disabled = false;
    }
  }

  async function _sendMsg() {
    const body = el.input.value.trim();
    if (!body || !_user) return;
    el.input.value = "";
    try {
      await fetch("/api/chat/send", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ username: _user, password: _pass, body }),
      });
    } catch (_) {}
  }

  // Init
  el.header.addEventListener("click", (e) => {
    if (!e.target.closest("#chatActive") && !e.target.closest("#chatLogin")) {
      el.panel.classList.toggle("collapsed");
      el.panel.classList.remove("has-new");
      el.toggle.textContent = el.panel.classList.contains("collapsed") ? "▲" : "▼";
    }
  });
  el.btnLogin.addEventListener("click", () => _doAuth(false));
  el.btnReg.addEventListener("click", () => _doAuth(true));
  el.btnSend.addEventListener("click", _sendMsg);
  el.input.addEventListener("keydown", (e) => { if (e.key === "Enter") _sendMsg(); });

  // Auto-login si hay credenciales guardadas
  if (_user && _pass) {
    el.userIn.value = _user;
    el.passIn.value = _pass;
    _doAuth(false);
  }
})();
