// informes.js -- puerto de frontend/js/informes.js de ajuste_comp_web como VISTAS.informes del shell del
// núcleo. El backend (rutas/informes.py::GET /data) hace UN solo fetch con los 13 paneles ya armados; acá
// solo se rellenan tablas y se dibujan gráficos canvas a partir de ese payload -- no hay estado de servidor
// que este módulo escriba.
//
// Paleta de gráficos: la grilla/ejes/texto se tradujeron del tema oscuro de la app vieja (#2f2f47/#9090a8/
// #c8c8dc) a las variables de nucleo (--borde/--sutil/--texto) ya resueltas a hex (canvas no puede leer
// var(...) directo) -- misma lógica que dashboard.js. PALETTE (colores de series/categorías) se deja igual:
// son los colores clásicos de gráficos de Excel, ya bastante neutros, funcionan en los dos temas.
function _infFmtNum(n, decimals = 3) {
  if (n === null || n === undefined || n === "" || !Number.isFinite(Number(n))) return "—";
  const v = Number(n);
  let s = v.toFixed(decimals);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s === "" || s === "-" ? "0" : s;
}

const INF_SECTIONS = [
  ["summary", "Resumen general"],
  ["materials", "Materiales mas usados"],
  ["monthly_furnace", "Hierro fundido mensual"],
  ["monthly_hornos", "Hierro mensual por hornos"],
  ["targets", "Objetivos mas usados"],
  ["elements", "Elementos mas ajustados"],
  ["ce", "CE y formulas"],
  ["days", "Produccion por fecha"],
  ["durations", "Duracion de sesiones"],
  ["cucharas", "Cucharas"],
  ["quality_reports", "Informes de calidad"],
  ["inoculantes", "Uso de inoculantes"],
  ["timeline", "Linea de tiempo diaria"],
  ["composicion_traccion", "Composición final vs Tracción"],
];

let infData = null;
let infActiveSection = "summary";
let infTimelineDayIdx = 0;
let infTimelineCorrected = false;
let infCompTracMaterial = "__todos__";
let infCompTracSelected = []; // hasta 2 row-keys, para el radar comparativo
let infResizeListenerAdded = false;

// ---------- helpers de tabla ----------

function _infFillTable(tbodyId, rows, columns) {
  const tbody = document.getElementById(tbodyId);
  if (!tbody) return;
  if (!rows || !rows.length) {
    tbody.innerHTML = `<tr><td colspan="${columns.length}" class="sutil">Sin datos.</td></tr>`;
    return;
  }
  tbody.innerHTML = rows.map((row) => `<tr>${columns.map((c) => `<td>${c(row)}</td>`).join("")}</tr>`).join("");
}

// ---------- canvas: setup DPI-aware ----------

function _infResizeCanvas(canvas) {
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(80, rect.width);
  const h = Math.max(60, rect.height);
  const bufW = Math.max(1, Math.round(w * dpr));
  const bufH = Math.max(1, Math.round(h * dpr));
  canvas.width = bufW;
  canvas.height = bufH;
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

const INF_PALETTE = [
  "#5B9BD5", "#ED7D31", "#70AD47", "#FFC000", "#A5A5A5", "#4472C4",
  "#C00000", "#7030A0", "#00B0F0", "#92D050", "#FF6699", "#B4C7E7",
  "#FFD966", "#9DC3E6", "#F4B183", "#A9D18E",
];
// Grises/textos/estado, resueltos desde las variables del núcleo (canvas no puede leer var(...) directo).
const INF_C_BORDE = "#dde3e9";
const INF_C_SUTIL = "#66717d";
const INF_C_TEXTO = "#1d2733";
const INF_C_VERDE = "#2e7d32";
const INF_C_ROJO = "#c0392b";
const INF_C_AMBAR = "#b26a00";

function _infEmptyChart(canvas, msg = "Sin datos para graficar.") {
  const { ctx, w, h } = _infResizeCanvas(canvas);
  ctx.fillStyle = INF_C_SUTIL;
  ctx.font = "13px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText(msg, w / 2, h / 2);
}

function _infTruncateLabel(ctx, label, maxWidth) {
  if (ctx.measureText(label).width <= maxWidth) return label;
  let s = label;
  while (s.length > 1 && ctx.measureText(s + "…").width > maxWidth) s = s.slice(0, -1);
  return s + "…";
}

// ---------- gráfico de barras horizontales ----------

function _infDrawBarH(canvas, items, { color = INF_PALETTE[0] } = {}) {
  if (!items.length) return _infEmptyChart(canvas);
  const { ctx, w, h } = _infResizeCanvas(canvas);
  const margin = { left: 130, right: 46, top: 10, bottom: 10 };
  const plotW = Math.max(10, w - margin.left - margin.right);
  const rowH = (h - margin.top - margin.bottom) / items.length;
  const maxVal = Math.max(...items.map((it) => it.value), 0.0001);

  ctx.font = "11px system-ui, sans-serif";
  items.forEach((it, i) => {
    const y = margin.top + i * rowH;
    const barH = Math.max(4, rowH * 0.62);
    const barY = y + (rowH - barH) / 2;
    const barW = (it.value / maxVal) * plotW;

    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillStyle = INF_C_TEXTO;
    ctx.fillText(_infTruncateLabel(ctx, it.label, margin.left - 10), margin.left - 10, y + rowH / 2);

    ctx.fillStyle = it.color || color;
    ctx.fillRect(margin.left, barY, barW, barH);

    ctx.textAlign = "left";
    ctx.fillStyle = INF_C_TEXTO;
    ctx.fillText(_infFmtNum(it.value, it.decimals ?? 2), margin.left + barW + 6, y + rowH / 2);
  });
}

// ---------- gráfico de barras verticales (agrupadas o apiladas) ----------

function _infDrawBarV(canvas, labels, series, { mode = "grouped" } = {}) {
  if (!labels.length || !series.length) return _infEmptyChart(canvas);
  const { ctx, w, h } = _infResizeCanvas(canvas);
  const margin = { left: 52, right: 14, top: 16, bottom: labels.length > 8 ? 56 : 40 };
  const plotW = Math.max(10, w - margin.left - margin.right);
  const plotH = Math.max(10, h - margin.top - margin.bottom);

  let maxVal;
  if (mode === "stacked") {
    maxVal = Math.max(...labels.map((_, i) => series.reduce((s, sr) => s + (sr.values[i] || 0), 0)), 0.0001);
  } else {
    maxVal = Math.max(...series.flatMap((sr) => sr.values), 0.0001);
  }

  ctx.strokeStyle = INF_C_BORDE;
  ctx.fillStyle = INF_C_SUTIL;
  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const val = (maxVal / ticks) * t;
    const y = margin.top + plotH - (val / maxVal) * plotH;
    ctx.beginPath();
    ctx.moveTo(margin.left, y);
    ctx.lineTo(margin.left + plotW, y);
    ctx.stroke();
    ctx.fillText(_infFmtNum(val, val < 10 ? 2 : 0), margin.left - 6, y);
  }

  const groupW = plotW / labels.length;
  const barGap = groupW * 0.18;
  const usableW = groupW - barGap;
  const barW = mode === "stacked" ? usableW : usableW / series.length;

  labels.forEach((label, i) => {
    const gx = margin.left + i * groupW + barGap / 2;
    if (mode === "stacked") {
      let acc = 0;
      series.forEach((sr, si) => {
        const val = sr.values[i] || 0;
        const barH = (val / maxVal) * plotH;
        const y = margin.top + plotH - (acc / maxVal) * plotH - barH;
        ctx.fillStyle = sr.color || INF_PALETTE[si % INF_PALETTE.length];
        ctx.fillRect(gx, y, usableW, barH);
        acc += val;
      });
    } else {
      series.forEach((sr, si) => {
        const val = sr.values[i] || 0;
        const barH = (val / maxVal) * plotH;
        const x = gx + si * barW;
        ctx.fillStyle = sr.color || INF_PALETTE[si % INF_PALETTE.length];
        ctx.fillRect(x, margin.top + plotH - barH, barW, barH);
      });
    }
    ctx.save();
    ctx.fillStyle = INF_C_SUTIL;
    ctx.font = "10px system-ui, sans-serif";
    const lx = gx + usableW / 2;
    const ly = margin.top + plotH + 12;
    if (labels.length > 8) {
      ctx.translate(lx, ly);
      ctx.rotate(-Math.PI / 4);
      ctx.textAlign = "right";
      ctx.textBaseline = "middle";
      ctx.fillText(_infTruncateLabel(ctx, String(label), 90), 0, 0);
    } else {
      ctx.textAlign = "center";
      ctx.textBaseline = "top";
      ctx.fillText(_infTruncateLabel(ctx, String(label), groupW), lx, ly);
    }
    ctx.restore();
  });

  if (series.length > 1) {
    let lx = margin.left;
    const ly = 4;
    ctx.font = "10px system-ui, sans-serif";
    series.forEach((sr, si) => {
      ctx.fillStyle = sr.color || INF_PALETTE[si % INF_PALETTE.length];
      ctx.fillRect(lx, ly, 9, 9);
      ctx.fillStyle = INF_C_TEXTO;
      ctx.textAlign = "left";
      ctx.textBaseline = "top";
      ctx.fillText(sr.name, lx + 12, ly - 1);
      lx += 12 + ctx.measureText(sr.name).width + 14;
    });
  }
}

// ---------- torta ----------

function _infDrawPie(canvas, items) {
  const total = items.reduce((s, it) => s + it.value, 0);
  if (!items.length || total <= 0) return _infEmptyChart(canvas);
  const { ctx, w, h } = _infResizeCanvas(canvas);
  const legendW = 150;
  const cx = (w - legendW) / 2;
  const cy = h / 2;
  const r = Math.max(20, Math.min(cx, cy) - 16);

  let start = -Math.PI / 2;
  items.forEach((it, i) => {
    const slice = (it.value / total) * Math.PI * 2;
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.arc(cx, cy, r, start, start + slice);
    ctx.closePath();
    ctx.fillStyle = it.color || INF_PALETTE[i % INF_PALETTE.length];
    ctx.fill();
    start += slice;
  });

  let ly = 14;
  ctx.font = "11px system-ui, sans-serif";
  items.forEach((it, i) => {
    const lx = w - legendW + 4;
    ctx.fillStyle = it.color || INF_PALETTE[i % INF_PALETTE.length];
    ctx.fillRect(lx, ly, 10, 10);
    const pct = ((it.value / total) * 100).toFixed(0);
    ctx.fillStyle = INF_C_TEXTO;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(`${_infTruncateLabel(ctx, it.label, legendW - 50)} (${pct}%)`, lx + 14, ly);
    ly += 18;
  });
}

// ---------- histograma ----------

function _infDrawHistogram(canvas, values, { bins = 12, avg = null } = {}) {
  if (!values.length) return _infEmptyChart(canvas);
  const min = Math.min(...values);
  const max = Math.max(...values);
  const span = Math.max(max - min, 0.0001);
  const counts = new Array(bins).fill(0);
  values.forEach((v) => {
    let idx = Math.floor(((v - min) / span) * bins);
    if (idx >= bins) idx = bins - 1;
    if (idx < 0) idx = 0;
    counts[idx]++;
  });
  const labels = counts.map((_, i) => Math.round(min + (span / bins) * i));
  _infDrawBarV(canvas, labels, [{ name: "Sesiones", values: counts, color: INF_PALETTE[0] }]);

  if (avg !== null) {
    const canvasRect = canvas.parentElement.getBoundingClientRect();
    const ctx = canvas.getContext("2d");
    const margin = { left: 52, right: 14, top: 16, bottom: labels.length > 8 ? 56 : 40 };
    const plotW = Math.max(10, canvasRect.width - margin.left - margin.right);
    const x = margin.left + ((avg - min) / span) * plotW;
    ctx.strokeStyle = INF_PALETTE[1];
    ctx.lineWidth = 1.5;
    ctx.setLineDash([5, 3]);
    ctx.beginPath();
    ctx.moveTo(x, margin.top);
    ctx.lineTo(x, canvasRect.height - margin.bottom);
    ctx.stroke();
    ctx.setLineDash([]);
  }
}

// ---------- dispersion (scatter) ----------

function _infDrawScatter(canvas, points, { xLabel = "", yLabel = "" } = {}) {
  if (!points.length) return _infEmptyChart(canvas);
  const { ctx, w, h } = _infResizeCanvas(canvas);
  const margin = { left: 56, right: 20, top: 16, bottom: 46 };
  const plotW = Math.max(10, w - margin.left - margin.right);
  const plotH = Math.max(10, h - margin.top - margin.bottom);

  const xs = points.map((p) => p.x);
  const ys = points.map((p) => p.y);
  const xMin = Math.min(...xs), xMax = Math.max(...xs);
  const yMin = Math.min(...ys), yMax = Math.max(...ys);
  const xSpan = Math.max(xMax - xMin, 0.0001);
  const ySpan = Math.max(yMax - yMin, 0.0001);
  const xPad = xSpan * 0.1, yPad = ySpan * 0.1;
  const xLo = xMin - xPad, xHi = xMax + xPad;
  const yLo = yMin - yPad, yHi = yMax + yPad;
  const xOf = (x) => margin.left + ((x - xLo) / (xHi - xLo)) * plotW;
  const yOf = (y) => margin.top + plotH - ((y - yLo) / (yHi - yLo)) * plotH;

  ctx.strokeStyle = INF_C_BORDE;
  ctx.fillStyle = INF_C_SUTIL;
  ctx.font = "10px system-ui, sans-serif";
  const ticks = 4;
  for (let t = 0; t <= ticks; t++) {
    const xv = xLo + ((xHi - xLo) / ticks) * t;
    const xPix = xOf(xv);
    ctx.beginPath(); ctx.moveTo(xPix, margin.top); ctx.lineTo(xPix, margin.top + plotH); ctx.stroke();
    ctx.textAlign = "center"; ctx.textBaseline = "top";
    ctx.fillText(_infFmtNum(xv, xv < 10 ? 2 : 0), xPix, margin.top + plotH + 6);

    const yv = yLo + ((yHi - yLo) / ticks) * t;
    const yPix = yOf(yv);
    ctx.beginPath(); ctx.moveTo(margin.left, yPix); ctx.lineTo(margin.left + plotW, yPix); ctx.stroke();
    ctx.textAlign = "right"; ctx.textBaseline = "middle";
    ctx.fillText(_infFmtNum(yv, yv < 10 ? 2 : 0), margin.left - 6, yPix);
  }

  const familyColor = {};
  let colorIdx = 0;
  points.forEach((p) => {
    const fam = p.family || "Sin dato";
    if (!(fam in familyColor)) familyColor[fam] = INF_PALETTE[(colorIdx++) % INF_PALETTE.length];
    ctx.beginPath();
    ctx.arc(xOf(p.x), yOf(p.y), 4, 0, Math.PI * 2);
    ctx.fillStyle = familyColor[fam];
    ctx.globalAlpha = 0.85;
    ctx.fill();
    ctx.globalAlpha = 1;
  });

  ctx.fillStyle = INF_C_TEXTO;
  ctx.font = "11px system-ui, sans-serif";
  ctx.textAlign = "center"; ctx.textBaseline = "bottom";
  ctx.fillText(xLabel, margin.left + plotW / 2, h - 2);
  ctx.save();
  ctx.translate(12, margin.top + plotH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center"; ctx.textBaseline = "top";
  ctx.fillText(yLabel, 0, 0);
  ctx.restore();

  let lx = margin.left;
  const ly = 2;
  ctx.font = "10px system-ui, sans-serif";
  Object.entries(familyColor).forEach(([fam, color]) => {
    ctx.fillStyle = color;
    ctx.fillRect(lx, ly, 9, 9);
    ctx.fillStyle = INF_C_TEXTO;
    ctx.textAlign = "left"; ctx.textBaseline = "top";
    ctx.fillText(fam, lx + 12, ly - 1);
    lx += 12 + ctx.measureText(fam).width + 14;
  });
}

// ---------- telaraña (radar) ----------

const INF_RADAR_AXES = ["C", "Si", "Mn", "Cr", "Mo", "Ni", "Cu", "Sn"];

function _infDrawRadar(canvas, axes, series, ranges) {
  if (!series.length) return _infEmptyChart(canvas, "Marcá 1 o 2 filas para ver su composición.");
  const { ctx, w, h } = _infResizeCanvas(canvas);
  const legendH = 20;
  const cx = w / 2;
  const cy = legendH + (h - legendH) / 2;
  const r = Math.max(30, Math.min(w, h - legendH) / 2 - 60);
  const n = axes.length;
  const angleOf = (i) => -Math.PI / 2 + (i * 2 * Math.PI) / n;
  const radioFloor = 0.12;
  const normalize = (axis, value) => {
    const [lo, hi] = ranges[axis] || [0, 1];
    const span = Math.max(hi - lo, 1e-9);
    const t = Math.max(0, Math.min(1, (value - lo) / span));
    return radioFloor + t * (1 - radioFloor);
  };
  const pointAt = (i, frac) => {
    const a = angleOf(i);
    return [cx + Math.cos(a) * r * frac, cy + Math.sin(a) * r * frac];
  };

  ctx.strokeStyle = INF_C_BORDE;
  ctx.lineWidth = 1;
  [0.25, 0.5, 0.75, 1].forEach((frac) => {
    ctx.beginPath();
    for (let i = 0; i <= n; i++) {
      const [x, y] = pointAt(i % n, frac);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    }
    ctx.stroke();
  });
  ctx.font = "11px system-ui, sans-serif";
  for (let i = 0; i < n; i++) {
    const [x, y] = pointAt(i, 1);
    ctx.beginPath();
    ctx.moveTo(cx, cy);
    ctx.lineTo(x, y);
    ctx.stroke();
    const a = angleOf(i);
    const lx = cx + Math.cos(a) * (r + 32);
    const ly = cy + Math.sin(a) * (r + 26);
    ctx.fillStyle = INF_C_TEXTO;
    ctx.textAlign = Math.cos(a) > 0.3 ? "left" : Math.cos(a) < -0.3 ? "right" : "center";
    ctx.textBaseline = Math.sin(a) > 0.3 ? "top" : Math.sin(a) < -0.3 ? "bottom" : "middle";
    ctx.fillText(axes[i], lx, ly);
  }

  series.forEach((s) => {
    ctx.beginPath();
    axes.forEach((axis, i) => {
      const frac = normalize(axis, s.values[axis] ?? 0);
      const [x, y] = pointAt(i, frac);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.closePath();
    ctx.fillStyle = s.color;
    ctx.globalAlpha = 0.22;
    ctx.fill();
    ctx.globalAlpha = 1;
    ctx.strokeStyle = s.color;
    ctx.lineWidth = 2;
    ctx.stroke();
    axes.forEach((axis, i) => {
      const frac = normalize(axis, s.values[axis] ?? 0);
      const [x, y] = pointAt(i, frac);
      ctx.beginPath();
      ctx.arc(x, y, 3, 0, Math.PI * 2);
      ctx.fillStyle = s.color;
      ctx.fill();
    });
  });

  ctx.font = "10px system-ui, sans-serif";
  axes.forEach((axis, i) => {
    const a = angleOf(i);
    const dirX = Math.cos(a), dirY = Math.sin(a);
    series.forEach((s, si) => {
      const frac = normalize(axis, s.values[axis] ?? 0);
      const [x, y] = pointAt(i, frac);
      const lx = x + dirX * 9;
      const ly = y + dirY * 9 + (si - (series.length - 1) / 2) * 12;
      ctx.fillStyle = s.color;
      ctx.textAlign = dirX > 0.3 ? "left" : dirX < -0.3 ? "right" : "center";
      ctx.textBaseline = dirY > 0.3 ? "top" : dirY < -0.3 ? "bottom" : "middle";
      ctx.fillText(_infFmtNum(s.values[axis], 3), lx, ly);
    });
  });

  let lx = 4;
  ctx.font = "11px system-ui, sans-serif";
  series.forEach((s) => {
    ctx.fillStyle = s.color;
    ctx.fillRect(lx, 4, 10, 10);
    ctx.fillStyle = INF_C_TEXTO;
    ctx.textAlign = "left";
    ctx.textBaseline = "top";
    ctx.fillText(s.name, lx + 14, 3);
    lx += 18 + ctx.measureText(s.name).width + 18;
  });
}

// ---------- linea de tiempo diaria (gantt) ----------

const INF_TL_WIN_START = 5 * 60;
const INF_TL_WIN_END = 18 * 60;
const INF_TL_FIRST_START = 5 * 60 + 30;

function _infTlToMinutes(ts) {
  if (!ts) return null;
  const text = String(ts).replace("T", " ").slice(0, 19);
  const m = text.match(/^(\d{4})-(\d{2})-(\d{2}) (\d{2}):(\d{2}):(\d{2})$/);
  if (!m) return null;
  return Number(m[4]) * 60 + Number(m[5]) + Number(m[6]) / 60;
}

function _infDrawTimeline(canvas, sessions, corrected) {
  if (!sessions.length) return _infEmptyChart(canvas, "Sin coladas para este dia.");
  const { ctx, w, h } = _infResizeCanvas(canvas);
  const margin = { left: 130, right: 60, top: 10, bottom: 30 };
  const plotW = Math.max(10, w - margin.left - margin.right);
  const plotH = Math.max(10, h - margin.top - margin.bottom);
  const winSpan = INF_TL_WIN_END - INF_TL_WIN_START;
  const rowH = plotH / sessions.length;
  const xOf = (min) => margin.left + (Math.max(0, Math.min(min, winSpan)) / winSpan) * plotW;

  const starts = [];
  const ends = [];
  if (corrected) {
    let prevEnd = INF_TL_FIRST_START;
    sessions.forEach((s) => {
      let lastCuchara = null;
      for (const ts of s.cucharas) {
        const t = _infTlToMinutes(ts);
        if (t !== null && (lastCuchara === null || t > lastCuchara)) lastCuchara = t;
      }
      if (lastCuchara === null) {
        const ajTimes = s.ajustes.map((aj) => _infTlToMinutes(aj.fecha)).filter((t) => t !== null);
        lastCuchara = ajTimes.length ? Math.max(...ajTimes) : prevEnd + 90;
      }
      starts.push(prevEnd);
      ends.push(Math.max(lastCuchara, prevEnd + 1));
      prevEnd = ends[ends.length - 1];
    });
  }

  ctx.strokeStyle = INF_C_BORDE;
  ctx.fillStyle = INF_C_SUTIL;
  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let m = 0; m <= winSpan; m += 60) {
    const x = xOf(m);
    ctx.beginPath();
    ctx.moveTo(x, margin.top);
    ctx.lineTo(x, margin.top + plotH);
    ctx.stroke();
    const totalMin = m + INF_TL_WIN_START;
    const hh = String(Math.floor(totalMin / 60)).padStart(2, "0");
    const mm = String(totalMin % 60).padStart(2, "0");
    ctx.fillText(`${hh}:${mm}`, x, margin.top + plotH + 6);
  }

  sessions.forEach((s, i) => {
    const y = margin.top + i * rowH;
    const barH = Math.max(6, rowH * 0.55);
    const barY = y + (rowH - barH) / 2;
    const color = INF_PALETTE[i % INF_PALETTE.length];

    let startM, endM;
    if (corrected) {
      startM = starts[i];
      endM = ends[i];
    } else {
      startM = _infTlToMinutes(s.started_at);
      endM = _infTlToMinutes(s.ended_at);
      if (endM === null) {
        const ajTimes = s.ajustes.map((aj) => _infTlToMinutes(aj.fecha)).filter((t) => t !== null);
        endM = ajTimes.length ? Math.max(...ajTimes) + 5 : (startM ?? INF_TL_WIN_START) + 60;
      }
      if (startM === null) startM = INF_TL_WIN_START;
    }
    const sClip = Math.max(startM, INF_TL_WIN_START) - INF_TL_WIN_START;
    const eClip = Math.min(endM, INF_TL_WIN_END) - INF_TL_WIN_START;
    const dur = Math.max(eClip - sClip, 3);

    ctx.fillStyle = color;
    ctx.globalAlpha = 0.85;
    ctx.fillRect(xOf(sClip), barY, xOf(sClip + dur) - xOf(sClip), barH);
    ctx.globalAlpha = 1;

    ctx.strokeStyle = INF_C_VERDE;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(xOf(sClip), y + 2);
    ctx.lineTo(xOf(sClip), y + rowH - 2);
    ctx.stroke();

    ctx.strokeStyle = INF_C_ROJO;
    ctx.lineWidth = 1.4;
    for (const aj of s.ajustes) {
      const t = _infTlToMinutes(aj.fecha);
      if (t === null || t < INF_TL_WIN_START || t > INF_TL_WIN_END) continue;
      const x = xOf(t - INF_TL_WIN_START);
      ctx.beginPath();
      ctx.moveTo(x, barY);
      ctx.lineTo(x, barY + barH);
      ctx.stroke();
    }

    ctx.strokeStyle = INF_C_AMBAR;
    ctx.lineWidth = 1.1;
    for (const ts of s.cucharas) {
      const t = _infTlToMinutes(ts);
      if (t === null || t < INF_TL_WIN_START || t > INF_TL_WIN_END) continue;
      const x = xOf(t - INF_TL_WIN_START);
      ctx.beginPath();
      ctx.moveTo(x, barY);
      ctx.lineTo(x, barY + barH);
      ctx.stroke();
    }

    ctx.fillStyle = INF_C_TEXTO;
    ctx.font = "10px system-ui, sans-serif";
    ctx.textAlign = "right";
    ctx.textBaseline = "middle";
    ctx.fillText(_infTruncateLabel(ctx, s.colada || s.objetivo || "", margin.left - 10), margin.left - 10, y + rowH / 2);

    if (s.total_cucharas > 0) {
      ctx.fillStyle = INF_C_AMBAR;
      ctx.textAlign = "left";
      ctx.fillText(`${s.total_cucharas} cuch.`, xOf(sClip + dur) + 4, y + rowH / 2);
    }
  });

  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "left";
  ctx.textBaseline = "top";
  const legend = [["Inicio sesión", INF_C_VERDE], ["Ajuste", INF_C_ROJO], ["Cuchara (PDH)", INF_C_AMBAR]];
  let lx = margin.left;
  legend.forEach(([label, color]) => {
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    ctx.moveTo(lx, 2);
    ctx.lineTo(lx, 10);
    ctx.stroke();
    ctx.fillStyle = INF_C_SUTIL;
    ctx.fillText(label, lx + 6, 0);
    lx += 14 + ctx.measureText(label).width + 16;
  });
}

// ---------- render por sección ----------

function _infRenderSummary(d) {
  document.getElementById("summary-text").textContent =
    `Materiales en catalogo: ${d.total_catalog}\n` +
    `Materiales de ajuste: ${d.total_adjusters}\n` +
    `Sesiones guardadas: ${d.total_sessions}\n` +
    `Ajustes aplicados: ${d.total_ajustes}\n` +
    `Calculos guardados: ${d.total_calculos}\n` +
    `Objetivos distintos: ${d.total_targets}\n` +
    `kg agregados acumulados: ${_infFmtNum(d.total_kg, 3)}`;
  const items = d.chart.labels.map((label, i) => ({ label, value: d.chart.values[i] }));
  _infDrawBarH(document.getElementById("chart-summary"), items, { color: INF_PALETTE[0] });
}

function _infRenderMaterials(d) {
  _infFillTable("materials-rows", d.rows, [(r) => r.material, (r) => _infFmtNum(r.kg, 3)]);
  const items = d.chart_top15.map((it) => ({ label: it.material, value: it.kg }));
  _infDrawBarH(document.getElementById("chart-materials"), items);
}

function _infRenderMonthlyFurnace(d) {
  const s = d.summary;
  document.getElementById("monthly-furnace-text").textContent =
    `Cucharas registradas: ${s.total_cucharas} | Equivalencia usada: ${_infFmtNum(s.kg_per_count, 0)} kg aprox/cuchara | ` +
    `Meses: ${s.months} | Materiales: ${s.materials} | Material principal: ${s.top_material}` +
    ` | Coladas con cucharas: ${s.coladas_con_cucharas}`;
  const labels = d.data.map((row) => row.month);
  const series = d.materials_order.map((mat, i) => ({
    name: mat, color: INF_PALETTE[i % INF_PALETTE.length],
    values: d.data.map((row) => row.materials[mat] || 0),
  }));
  _infDrawBarV(document.getElementById("chart-monthly-furnace"), labels, series, { mode: "stacked" });
}

function _infRenderMonthlyHornos(d) {
  const s = d.summary;
  document.getElementById("monthly-hornos-text").textContent =
    `Hornos registrados: ${s.hornos} | Equivalencia usada: ${_infFmtNum(s.kg_per_session, 0)} kg/horno | ` +
    `Total por hornos: ${_infFmtNum(s.total_kg, 0)} kg | Meses: ${s.months} | Materiales: ${s.materials} | ` +
    `Material principal: ${s.top_material}`;
  const labels = d.data.map((row) => row.month);
  const series = d.materials_order.map((mat, i) => ({
    name: mat, color: INF_PALETTE[i % INF_PALETTE.length],
    values: d.data.map((row) => row.materials[mat] || 0),
  }));
  _infDrawBarV(document.getElementById("chart-monthly-hornos"), labels, series, { mode: "stacked" });
}

function _infRenderTargets(d) {
  _infFillTable("targets-rows", d.rows, [(r) => r.objetivo, (r) => r.cant]);
  const items = d.chart_top10.map((it) => ({ label: it.objetivo, value: it.cant }));
  _infDrawBarH(document.getElementById("chart-targets"), items, { color: INF_PALETTE[1] });
}

function _infRenderElements(d) {
  _infFillTable("elements-rows", d.rows, [(r) => r.elemento, (r) => r.veces, (r) => _infFmtNum(r.delta, 4)]);
  const items = d.chart_top12.map((it) => ({ label: it.elemento, value: it.delta, decimals: 3 }));
  _infDrawBarH(document.getElementById("chart-elements"), items, { color: INF_PALETTE[2] });
}

function _infRenderCe(d) {
  _infFillTable("ce-rows", d.rows, [(r) => r.formula, (r) => r.veces, (r) => _infFmtNum(r.ce_ini, 4), (r) => _infFmtNum(r.ce_est, 4)]);
  _infDrawBarV(document.getElementById("chart-ce"), d.chart.formulas, [
    { name: "CE inicial", values: d.chart.ini, color: INF_PALETTE[0] },
    { name: "CE final", values: d.chart.fin, color: INF_PALETTE[1] },
  ]);
}

function _infRenderDays(d) {
  _infFillTable("days-rows", d.rows, [(r) => r.fecha, (r) => r.sesiones, (r) => r.ajustes, (r) => _infFmtNum(r.kg, 3)]);
  _infDrawBarV(document.getElementById("chart-days-kg"), d.chart.fechas, [{ name: "kg", values: d.chart.kg, color: INF_PALETTE[0] }]);
  _infDrawBarV(document.getElementById("chart-days-sesiones"), d.chart.fechas, [{ name: "sesiones", values: d.chart.sesiones, color: INF_PALETTE[1] }]);
}

function _infRenderDurations(d) {
  if (!d.count) {
    document.getElementById("durations-text").textContent = "No hay suficientes fechas validas para calcular duraciones.";
    _infEmptyChart(document.getElementById("chart-durations"));
    return;
  }
  document.getElementById("durations-text").textContent =
    `Duracion promedio: ${_infFmtNum(d.avg, 1)} min\n` +
    `Duracion minima: ${_infFmtNum(d.min, 1)} min\n` +
    `Duracion maxima: ${_infFmtNum(d.max, 1)} min\n` +
    `Sesiones con duracion valida: ${d.count}`;
  _infDrawHistogram(document.getElementById("chart-durations"), d.durations, { bins: 12, avg: d.avg });
}

function _infRenderCucharas(d) {
  const s = d.summary;
  document.getElementById("cucharas-summary-text").textContent =
    `Coladas con cucharas: ${s.coladas_con_cucharas}\n` +
    `Total cucharas cargadas: ${s.total_cucharas}\n` +
    `Materiales distintos usados: ${s.materiales_distintos}\n` +
    `Material mas usado: ${s.material_top}\n` +
    `Promedio cucharas por colada: ${_infFmtNum(s.prom_por_colada, 2)}\n` +
    `Eventos con horario exacto: ${s.eventos_con_horario}\n` +
    `Duracion promedio primera-ultima: ${s.duracion_prom}\n` +
    `Promedio entre cucharas: ${s.prom_entre_cucharas}\n` +
    `Colada mas rapida: ${s.colada_mas_rapida}\n` +
    `Colada mas lenta: ${s.colada_mas_lenta}`;

  _infFillTable("cucharas-materials-rows", d.materials, [
    (r) => r.material, (r) => r.total, (r) => r.coladas, (r) => `${_infFmtNum(r.pct, 1)}%`, (r) => _infFmtNum(r.prom, 2),
  ]);
  _infFillTable("cucharas-coladas-rows", d.coladas, [
    (r) => r.colada, (r) => r.objetivo, (r) => r.total, (r) => r.primera, (r) => r.ultima,
    (r) => r.duracion, (r) => r.prom_entre, (r) => r.top_material,
  ]);
  _infFillTable("cucharas-hours-rows", d.hours, [(r) => r.hora, (r) => r.total, (r) => r.material]);

  _infDrawPie(document.getElementById("chart-cucharas-pie"), d.pie.map((p, i) => ({ ...p, color: INF_PALETTE[i % INF_PALETTE.length] })));
  _infDrawBarV(document.getElementById("chart-cucharas-hours"), d.hours_chart.horas, [
    { name: "cucharas", values: d.hours_chart.totales, color: INF_PALETTE[0] },
  ]);
}

function _infRenderQuality(d) {
  const s = d.summary;
  document.getElementById("quality-summary-text").textContent =
    `Informes totales: ${s.total}\n` +
    `Informes activos: ${s.active}\n` +
    `Informes archivados: ${s.archived}\n` +
    `Borradores pendientes: ${s.drafts}\n` +
    `Rango de fechas: ${s.date_range}\n` +
    `Lotes / coladas con informe: ${s.lots}\n` +
    `Bases distintas: ${s.bases}\n` +
    `Materiales distintos: ${s.materials}\n` +
    `Material mas informado: ${s.top_material}\n` +
    `Base mas informada: ${s.top_base}\n` +
    `Familia mas frecuente: ${s.top_family}\n` +
    `Informes con nombre/codigo: ${s.informes_named}\n` +
    `Informes con observaciones: ${s.with_observations}\n` +
    `Informes con CE / traccion / dureza: ${s.with_ce} / ${s.with_traccion} / ${s.with_dureza}\n` +
    `Promedio informes por lote: ${_infFmtNum(s.avg_reports_per_lot, 2)}`;

  _infFillTable("quality-props-rows", d.props, [
    (r) => r.campo, (r) => _infFmtNum(r.prom, 2), (r) => _infFmtNum(r.min, 2), (r) => _infFmtNum(r.max, 2), (r) => r.cant,
  ]);
  _infFillTable("quality-materials-rows", d.materials, [
    (r) => r.material, (r) => r.informes, (r) => r.bases,
    (r) => _infFmtNum(r.traccion, 2), (r) => _infFmtNum(r.dureza, 2), (r) => _infFmtNum(r.ce, 2),
  ]);
  _infFillTable("quality-bases-rows", d.bases, [
    (r) => r.base, (r) => r.informes, (r) => r.materiales, (r) => _infFmtNum(r.traccion, 2), (r) => _infFmtNum(r.dureza, 2),
  ]);
  _infFillTable("quality-micro-rows", d.micro, [(r) => r.tipo, (r) => r.valor, (r) => r.informes, (r) => `${_infFmtNum(r.pct, 1)}%`]);
  _infFillTable("quality-days-rows", d.days, [(r) => r.fecha, (r) => r.informes, (r) => r.lotes, (r) => r.materiales]);

  _infDrawBarV(document.getElementById("chart-quality"), d.chart.materiales, [
    { name: "Traccion", values: d.chart.traccion, color: INF_PALETTE[0] },
    { name: "Dureza", values: d.chart.dureza, color: INF_PALETTE[2] },
  ]);
}

function _infRenderInoculantes(d) {
  _infFillTable("inoc-config-rows", d.config, [
    (r) => r.inoc, (r) => r.unidad, (r) => (r.gramos == null ? "—" : _infFmtNum(r.gramos, 4)), (r) => r.materiales, (r) => r.etapas,
  ]);

  document.getElementById("inoc-recent-colada").textContent = d.recent.colada || "Sin datos de cucharas";
  _infFillTable("inoc-recent-rows", d.recent.rows, [
    (r) => r.inoc, (r) => r.dosis, (r) => (r.gramos_u == null ? "—" : _infFmtNum(r.gramos_u, 4)), (r) => _infFmtNum(r.total_kg, 3),
  ]);

  _infFillTable("inoc-hist-rows", d.historico, [
    (r) => r.inoc, (r) => r.coladas, (r) => r.dosis, (r) => _infFmtNum(r.total_kg, 3), (r) => _infFmtNum(r.prom_kg, 3),
  ]);

  const monthly = d.monthly;
  const head = document.getElementById("inoc-monthly-head");
  const body = document.getElementById("inoc-monthly-rows");
  if (!monthly.meses.length || !monthly.inoculantes.length) {
    head.innerHTML = "<tr><th>Mes</th></tr>";
    body.innerHTML = `<tr><td class="sutil">Sin datos.</td></tr>`;
  } else {
    head.innerHTML = `<tr><th>Mes</th>${monthly.inoculantes.map((i) => `<th>${i}</th>`).join("")}</tr>`;
    const rows = monthly.rows.map((row) => `<tr><td>${row.mes}</td>${monthly.inoculantes.map((i) => `<td>${row[i] ? _infFmtNum(row[i], 3) : "—"}</td>`).join("")}</tr>`);
    const totalRow = `<tr style="font-weight:600;background:var(--gris-claro);"><td>TOTAL</td>${monthly.inoculantes.map((i) => `<td>${_infFmtNum(monthly.totales[i], 3)}</td>`).join("")}</tr>`;
    body.innerHTML = rows.join("") + totalRow;
  }

  const series = monthly.inoculantes.map((inoc, i) => ({
    name: inoc, color: INF_PALETTE[i % INF_PALETTE.length],
    values: monthly.rows.map((row) => row[inoc] || 0),
  }));
  _infDrawBarV(document.getElementById("chart-inoc-monthly"), monthly.meses, series, { mode: "grouped" });
}

function _infRenderTimeline(d) {
  const days = d.available_days;
  if (!days.length) {
    document.getElementById("tl-day-label").textContent = "Sin datos";
    _infEmptyChart(document.getElementById("chart-timeline"));
    return;
  }
  if (infTimelineDayIdx < 0) infTimelineDayIdx = 0;
  if (infTimelineDayIdx >= days.length) infTimelineDayIdx = days.length - 1;
  const day = days[infTimelineDayIdx];
  document.getElementById("tl-day-label").textContent = `${day}  (${days.length - infTimelineDayIdx}/${days.length})`;
  document.getElementById("tl-prev").disabled = infTimelineDayIdx >= days.length - 1;
  document.getElementById("tl-next").disabled = infTimelineDayIdx <= 0;
  _infDrawTimeline(document.getElementById("chart-timeline"), d.days[day] || [], infTimelineCorrected);
}

function _infCompTracSummary(rows) {
  const ceVals = rows.map((r) => r.ce_final).filter((v) => v !== null && v !== undefined);
  const trVals = rows.map((r) => r.traccion_real);
  const coladas = new Set(rows.map((r) => r.colada)).size;
  const conInoc = rows.filter((r) => r.incluye_inoculacion).length;
  return {
    total: rows.length,
    coladas,
    conInoc,
    ce_prom: ceVals.length ? ceVals.reduce((a, b) => a + b, 0) / ceVals.length : null,
    traccion_prom: trVals.length ? trVals.reduce((a, b) => a + b, 0) / trVals.length : null,
  };
}

function _infCompTracPopulateSelect(allRows) {
  const sel = document.getElementById("comptrac-material");
  const materials = [...new Set(allRows.map((r) => r.material))].sort();
  const prev = infCompTracMaterial;
  sel.innerHTML = `<option value="__todos__">Todos los materiales</option>` +
    materials.map((m) => `<option value="${m}">${m}</option>`).join("");
  infCompTracMaterial = materials.includes(prev) ? prev : "__todos__";
  sel.value = infCompTracMaterial;
}

function _infCompTracRowKey(r) {
  return `${r.colada}::${r.material}::${r.fecha}`;
}

function _infCompTracRadarRanges(rows) {
  const ranges = {};
  INF_RADAR_AXES.forEach((axis) => {
    const values = rows.map((r) => r.comp[axis]).filter((v) => v !== null && v !== undefined);
    ranges[axis] = values.length ? [Math.min(...values), Math.max(...values)] : [0, 1];
  });
  return ranges;
}

function _infRenderCompTracRadar(allRows) {
  const hint = document.getElementById("comptrac-radar-hint");
  const canvas = document.getElementById("chart-comptrac-radar");
  const selectedRows = infCompTracSelected
    .map((key) => allRows.find((r) => _infCompTracRowKey(r) === key))
    .filter((r) => r);
  if (!selectedRows.length) {
    hint.textContent = "Marcá 1 o 2 filas en la tabla de arriba para ver su composición química (escala por elemento: min/max de todas las filas de esta sección).";
    _infEmptyChart(canvas);
    return;
  }
  const ranges = _infCompTracRadarRanges(allRows);
  const series = selectedRows.map((r, i) => ({
    name: `${r.colada} · ${r.material} (${_infFmtNum(r.traccion_real, 2)} kg/mm²)`,
    color: INF_PALETTE[i % INF_PALETTE.length],
    values: r.comp,
  }));
  hint.textContent = series.length === 2
    ? `Comparando: ${series[0].name}  vs  ${series[1].name}`
    : `Mostrando: ${series[0].name} — marcá una segunda fila para comparar.`;
  _infDrawRadar(canvas, INF_RADAR_AXES, series, ranges);
}

function _infRenderCompTrac(d) {
  _infCompTracPopulateSelect(d.rows);
  const rows = infCompTracMaterial === "__todos__" ? d.rows : d.rows.filter((r) => r.material === infCompTracMaterial);
  const s = _infCompTracSummary(rows);

  document.getElementById("comptrac-summary-text").textContent = !s.total
    ? "Sin filas para este filtro: ninguna colada tiene a la vez composición final (un ajuste aplicado) y tracción real cargada en Calidad."
    : `Filas (colada + material con ambos datos): ${s.total} — ${s.coladas} colada${s.coladas === 1 ? "" : "s"} distinta${s.coladas === 1 ? "" : "s"}\n` +
      `Con inoculación incluida en la composición: ${s.conInoc} de ${s.total}\n` +
      `CE final promedio: ${_infFmtNum(s.ce_prom, 3)}\n` +
      `Tracción real promedio: ${_infFmtNum(s.traccion_prom, 2)} kg/mm²`;

  _infFillTable("comptrac-rows", rows, [
    (r) => `<input type="checkbox" class="comptrac-chk" data-key="${_infCompTracRowKey(r)}" ${infCompTracSelected.includes(_infCompTracRowKey(r)) ? "checked" : ""}>`,
    (r) => r.colada, (r) => r.material, (r) => r.family, (r) => r.fecha,
    (r) => r.incluye_inoculacion ? '<span title="Incluye el aporte del inoculante">✓</span>' : '<span class="sutil" title="Solo composición de horno: no hay protocolo de inoculación resuelto para este material+base">—</span>',
    (r) => _infFmtNum(r.comp.C, 3), (r) => _infFmtNum(r.comp.Si, 3), (r) => _infFmtNum(r.comp.Mn, 3),
    (r) => _infFmtNum(r.comp.Cr, 3), (r) => _infFmtNum(r.comp.Mo, 3), (r) => _infFmtNum(r.comp.Ni, 3),
    (r) => _infFmtNum(r.comp.Cu, 3), (r) => _infFmtNum(r.comp.Sn, 3),
    (r) => _infFmtNum(r.ce_final, 3), (r) => _infFmtNum(r.traccion_real, 2),
  ]);
  document.querySelectorAll("#comptrac-rows .comptrac-chk").forEach((chk) => {
    chk.addEventListener("change", () => {
      const key = chk.dataset.key;
      infCompTracSelected = infCompTracSelected.filter((k) => k !== key);
      if (chk.checked) {
        infCompTracSelected.push(key);
        if (infCompTracSelected.length > 2) infCompTracSelected.shift(); // FIFO: se queda con las 2 ultimas marcadas
      }
      _infRenderCompTrac(d); // re-renderiza tabla (checks al dia) + radar
    });
  });

  const points = rows.filter((r) => r.ce_final !== null && r.ce_final !== undefined)
    .map((r) => ({ x: r.ce_final, y: r.traccion_real, family: r.family }));
  _infDrawScatter(document.getElementById("chart-comptrac"), points, { xLabel: "CE final", yLabel: "Tracción real (kg/mm²)" });

  _infRenderCompTracRadar(d.rows);
}

const INF_RENDERERS = {
  summary: (d) => _infRenderSummary(d.summary),
  materials: (d) => _infRenderMaterials(d.materials),
  monthly_furnace: (d) => _infRenderMonthlyFurnace(d.monthly_furnace),
  monthly_hornos: (d) => _infRenderMonthlyHornos(d.monthly_hornos),
  targets: (d) => _infRenderTargets(d.targets),
  elements: (d) => _infRenderElements(d.elements),
  ce: (d) => _infRenderCe(d.ce),
  days: (d) => _infRenderDays(d.days),
  durations: (d) => _infRenderDurations(d.durations),
  cucharas: (d) => _infRenderCucharas(d.cucharas),
  quality_reports: (d) => _infRenderQuality(d.quality_reports),
  inoculantes: (d) => _infRenderInoculantes(d.inoculantes),
  timeline: (d) => _infRenderTimeline(d.timeline),
  composicion_traccion: (d) => _infRenderCompTrac(d.composicion_traccion),
};

// ---------- sidebar / navegación de secciones ----------

function _infRenderSidebar() {
  const list = document.getElementById("section-list");
  list.innerHTML = INF_SECTIONS.map(([key, label]) =>
    `<button type="button" class="inf-sec-btn${key === infActiveSection ? " active" : ""}" data-sec="${key}">${label}</button>`
  ).join("");
  list.querySelectorAll("[data-sec]").forEach((btn) => {
    btn.addEventListener("click", () => _infSwitchSection(btn.dataset.sec));
  });
}

function _infSwitchSection(key) {
  infActiveSection = key;
  document.querySelectorAll(".inf-sec-btn").forEach((btn) => btn.classList.toggle("active", btn.dataset.sec === key));
  document.querySelectorAll(".inf-section").forEach((el) => { el.style.display = el.id === `sec-${key}` ? "flex" : "none"; });
  document.getElementById("sec-title").textContent = INF_SECTIONS.find(([k]) => k === key)?.[1] || "";
  if (infData) INF_RENDERERS[key](infData);
}

// ---------- carga de datos ----------

async function _infLoad() {
  const status = document.getElementById("inf-status");
  status.textContent = "Cargando…";
  status.className = "sutil";
  try {
    infData = await Ajuste.apiFetch("/api/informes/data");
    infTimelineDayIdx = 0;
    status.textContent = "";
    INF_RENDERERS[infActiveSection](infData);
  } catch (ex) {
    status.textContent = `Error: ${ex.message}`;
    status.className = "error";
  }
}

VISTAS.informes = async () => {
  $("#vista").innerHTML = `
    <div class="tarjeta inf-shell">
      <div class="inf-sidebar">
        <div class="row" style="margin-bottom:10px;">
          <button id="btn-inf-refresh" class="primario" type="button">Refrescar</button>
        </div>
        <div id="section-list" class="inf-section-list"></div>
        <div id="inf-status" class="sutil" style="margin-top:8px;"></div>
      </div>

      <div class="inf-content">
        <h2 id="sec-title"></h2>

        <div id="sec-summary" class="inf-section">
          <pre id="summary-text" class="inf-summary"></pre>
          <div class="inf-chart-wrap"><canvas id="chart-summary"></canvas></div>
        </div>

        <div id="sec-materials" class="inf-section" style="display:none;">
          <div class="inf-table-wrap">
            <table><thead><tr><th>Material</th><th>kg total</th></tr></thead><tbody id="materials-rows"></tbody></table>
          </div>
          <div class="inf-chart-wrap"><canvas id="chart-materials"></canvas></div>
        </div>

        <div id="sec-monthly_furnace" class="inf-section" style="display:none;">
          <pre id="monthly-furnace-text" class="inf-summary"></pre>
          <div class="inf-chart-wrap"><canvas id="chart-monthly-furnace"></canvas></div>
        </div>

        <div id="sec-monthly_hornos" class="inf-section" style="display:none;">
          <pre id="monthly-hornos-text" class="inf-summary"></pre>
          <div class="inf-chart-wrap"><canvas id="chart-monthly-hornos"></canvas></div>
        </div>

        <div id="sec-targets" class="inf-section" style="display:none;">
          <div class="inf-table-wrap">
            <table><thead><tr><th>Objetivo</th><th>Ajustes</th></tr></thead><tbody id="targets-rows"></tbody></table>
          </div>
          <div class="inf-chart-wrap"><canvas id="chart-targets"></canvas></div>
        </div>

        <div id="sec-elements" class="inf-section" style="display:none;">
          <div class="inf-table-wrap">
            <table><thead><tr><th>Elemento</th><th>Veces</th><th>Delta abs total</th></tr></thead><tbody id="elements-rows"></tbody></table>
          </div>
          <div class="inf-chart-wrap"><canvas id="chart-elements"></canvas></div>
        </div>

        <div id="sec-ce" class="inf-section" style="display:none;">
          <div class="inf-table-wrap">
            <table><thead><tr><th>Formula</th><th>Usos</th><th>CE inicial prom</th><th>CE final prom</th></tr></thead><tbody id="ce-rows"></tbody></table>
          </div>
          <div class="inf-chart-wrap"><canvas id="chart-ce"></canvas></div>
        </div>

        <div id="sec-days" class="inf-section" style="display:none;">
          <div class="inf-table-wrap">
            <table><thead><tr><th>Fecha</th><th>Sesiones</th><th>Ajustes</th><th>kg agregados</th></tr></thead><tbody id="days-rows"></tbody></table>
          </div>
          <div class="inf-chart-cols">
            <div class="inf-chart-wrap"><canvas id="chart-days-kg"></canvas></div>
            <div class="inf-chart-wrap"><canvas id="chart-days-sesiones"></canvas></div>
          </div>
        </div>

        <div id="sec-durations" class="inf-section" style="display:none;">
          <pre id="durations-text" class="inf-summary"></pre>
          <div class="inf-chart-wrap"><canvas id="chart-durations"></canvas></div>
        </div>

        <div id="sec-cucharas" class="inf-section" style="display:none;">
          <pre id="cucharas-summary-text" class="inf-summary"></pre>
          <h3>Totales por material</h3>
          <div class="inf-cols-2">
            <div class="inf-table-wrap">
              <table><thead><tr><th>Material</th><th>Total cucharas</th><th>Coladas</th><th>% del total</th><th>Prom/colada</th></tr></thead><tbody id="cucharas-materials-rows"></tbody></table>
            </div>
            <div class="inf-chart-wrap"><canvas id="chart-cucharas-pie"></canvas></div>
          </div>
          <h3>Resumen por colada</h3>
          <div class="inf-table-wrap">
            <table><thead><tr><th>Colada</th><th>Material</th><th>Total</th><th>Primera</th><th>Ultima</th><th>Duracion</th><th>Prom entre cuch.</th><th>Material mas usado</th></tr></thead><tbody id="cucharas-coladas-rows"></tbody></table>
          </div>
          <h3>Actividad por hora</h3>
          <div class="inf-table-wrap">
            <table><thead><tr><th>Hora</th><th>Cucharas</th><th>Material dominante</th></tr></thead><tbody id="cucharas-hours-rows"></tbody></table>
          </div>
          <div class="inf-chart-wrap"><canvas id="chart-cucharas-hours"></canvas></div>
        </div>

        <div id="sec-quality_reports" class="inf-section" style="display:none;">
          <pre id="quality-summary-text" class="inf-summary"></pre>
          <h3>Promedios de propiedades</h3>
          <div class="inf-cols-2">
            <div class="inf-table-wrap">
              <table><thead><tr><th>Campo</th><th>Promedio</th><th>Min</th><th>Max</th><th>Cant.</th></tr></thead><tbody id="quality-props-rows"></tbody></table>
            </div>
            <div class="inf-chart-wrap"><canvas id="chart-quality"></canvas></div>
          </div>
          <h3>Informes por material</h3>
          <div class="inf-table-wrap">
            <table><thead><tr><th>Material</th><th>Informes</th><th>Bases</th><th>Traccion prom</th><th>Dureza prom</th><th>CE prom</th></tr></thead><tbody id="quality-materials-rows"></tbody></table>
          </div>
          <h3>Informes por base</h3>
          <div class="inf-table-wrap">
            <table><thead><tr><th>Base</th><th>Informes</th><th>Materiales</th><th>Traccion prom</th><th>Dureza prom</th></tr></thead><tbody id="quality-bases-rows"></tbody></table>
          </div>
          <h3>Metalografia / matriz</h3>
          <div class="inf-table-wrap">
            <table><thead><tr><th>Tipo</th><th>Valor</th><th>Informes</th><th>%</th></tr></thead><tbody id="quality-micro-rows"></tbody></table>
          </div>
          <h3>Informes por fecha</h3>
          <div class="inf-table-wrap">
            <table><thead><tr><th>Fecha</th><th>Informes</th><th>Lotes</th><th>Materiales</th></tr></thead><tbody id="quality-days-rows"></tbody></table>
          </div>
        </div>

        <div id="sec-inoculantes" class="inf-section" style="display:none;">
          <h3>Configuracion actual</h3>
          <div class="inf-table-wrap">
            <table><thead><tr><th>Inoculante</th><th>Unidad</th><th>g/unidad</th><th>Materiales que lo usan</th><th>Etapas</th></tr></thead><tbody id="inoc-config-rows"></tbody></table>
          </div>
          <h3>Colada mas reciente: <span id="inoc-recent-colada"></span></h3>
          <div class="inf-table-wrap">
            <table><thead><tr><th>Inoculante</th><th>Total dosis</th><th>g/unidad</th><th>Total kg estimado</th></tr></thead><tbody id="inoc-recent-rows"></tbody></table>
          </div>
          <h3>Consumo historico acumulado</h3>
          <div class="inf-table-wrap">
            <table><thead><tr><th>Inoculante</th><th>Coladas</th><th>Total dosis</th><th>Total kg estimado</th><th>Prom kg/colada</th></tr></thead><tbody id="inoc-hist-rows"></tbody></table>
          </div>
          <h3>Consumo mensual (kg)</h3>
          <div class="inf-table-wrap">
            <table id="inoc-monthly-table"><thead id="inoc-monthly-head"></thead><tbody id="inoc-monthly-rows"></tbody></table>
          </div>
          <div class="inf-chart-wrap"><canvas id="chart-inoc-monthly"></canvas></div>
        </div>

        <div id="sec-timeline" class="inf-section" style="display:none;">
          <div class="row">
            <button id="tl-prev" type="button">◀</button>
            <span id="tl-day-label" class="inf-day-label">Sin datos</span>
            <button id="tl-next" type="button">▶</button>
            <label style="display:inline-flex;align-items:center;gap:6px;margin-left:18px;">
              <input type="checkbox" id="tl-corrected"> Horarios corregidos
            </label>
          </div>
          <div class="inf-chart-wrap inf-chart-wrap-tall"><canvas id="chart-timeline"></canvas></div>
        </div>

        <div id="sec-composicion_traccion" class="inf-section" style="display:none;">
          <div class="row" style="margin-bottom:10px;">
            <label>Material<br><select id="comptrac-material"></select></label>
          </div>
          <p class="sutil">La composición final suma, cuando se puede resolver el protocolo de inoculación para ese material y esa base, el aporte químico del inoculante dosificado en la cuchara (no solo la del horno antes de colar).</p>
          <pre id="comptrac-summary-text" class="inf-summary"></pre>
          <div class="inf-chart-wrap"><canvas id="chart-comptrac"></canvas></div>
          <div class="inf-table-wrap">
            <table>
              <thead><tr>
                <th title="Marcá hasta 2 filas para comparar su composición en el gráfico de abajo">Comparar</th>
                <th>Colada</th><th>Material</th><th>Familia</th><th>Fecha</th>
                <th title="Si incluye el aporte quimico del inoculante dosificado en la cuchara para ese material+base, o solo la composicion del horno">Inoc.</th>
                <th>C</th><th>Si</th><th>Mn</th><th>Cr</th><th>Mo</th><th>Ni</th><th>Cu</th><th>Sn</th>
                <th>CE final</th><th>Tracción real (kg/mm²)</th>
              </tr></thead>
              <tbody id="comptrac-rows"></tbody>
            </table>
          </div>
          <h3>Perfil de composición (telaraña)</h3>
          <p id="comptrac-radar-hint" class="sutil">Marcá 1 o 2 filas en la tabla de arriba para ver su composición química.</p>
          <div class="inf-chart-wrap"><canvas id="chart-comptrac-radar"></canvas></div>
        </div>
      </div>
    </div>`;

  document.getElementById("btn-inf-refresh").addEventListener("click", _infLoad);
  document.getElementById("tl-prev").addEventListener("click", () => {
    const days = infData?.timeline.available_days || [];
    if (infTimelineDayIdx < days.length - 1) { infTimelineDayIdx++; _infRenderTimeline(infData.timeline); }
  });
  document.getElementById("tl-next").addEventListener("click", () => {
    if (infTimelineDayIdx > 0) { infTimelineDayIdx--; _infRenderTimeline(infData.timeline); }
  });
  document.getElementById("tl-corrected").addEventListener("change", (e) => {
    infTimelineCorrected = e.target.checked;
    if (infData) _infRenderTimeline(infData.timeline);
  });
  document.getElementById("comptrac-material").addEventListener("change", (e) => {
    infCompTracMaterial = e.target.value;
    if (infData) _infRenderCompTrac(infData.composicion_traccion);
  });

  if (!infResizeListenerAdded) {
    infResizeListenerAdded = true;
    let resizeTimer = null;
    window.addEventListener("resize", () => {
      if (resizeTimer) clearTimeout(resizeTimer);
      resizeTimer = setTimeout(() => {
        // La vista puede haber cambiado desde que se disparó el resize -- si "section-list" ya no está en el
        // DOM, el usuario se fue de Informes y no hay nada para redibujar.
        if (infData && document.getElementById("section-list")) INF_RENDERERS[infActiveSection](infData);
      }, 150);
    });
  }

  _infRenderSidebar();
  _infSwitchSection(infActiveSection);
  Ajuste.waitForApproval(_infLoad);
};
