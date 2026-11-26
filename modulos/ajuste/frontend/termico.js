// termico.js -- VISTAS.termico: puerto de frontend/js/termico.js de ajuste_comp_web. Lista archivos de
// carpeta + cache de dispositivo ya bajado, grafica curvas (doble eje, pan/zoom), vincula a Históricos
// (manual y automático por horario), compara curvas, calculadora de expansión, y carga C/Si en Ajuste.
//
// Nombres con prefijo "term"/"_term" a propósito: nucleo concatena todos los scripts del módulo en un solo
// scope global (sin import/export) -- "els"/"fmtNum"/"setStatus"/"closeModal"/"openOverlay"/"start" YA están
// declarados por ajuste.js en ese mismo scope. Mismo criterio que historicos.js (ver su comentario de
// cabecera para el detalle de por qué esto importa: redeclarar una `function` la pisa en silencio, redeclarar
// un `let`/`const` tira SyntaxError y rompe TODAS las pantallas).
//
// Modales: nucleo.js ya da abrirModal()/cerrarModal() -- no se porta el openOverlay/.modal-overlay propio
// del original. Descarga automática desde el equipo SÍ está (a diferencia de lo que decía el comentario
// viejo de este archivo -- esa limitación ya no aplica, el backend /api/termico/download está portado).

let termRecords = [];
let termSelectedPaths = [];
let termCurves = [];
let termCurveVisibility = {};
let termCarbonTseValue = null;
let termCarbonTlValue = null;
let termMicroTseValue = null;
let termSelectionTimer = null;
let termEls = {};

const TERM_COLORS = ["#2f6fb3", "#d9822b", "#2e8b57", "#9c4fa8", "#c0392b", "#546e8a"];

function _termFmtNum(n, decimals = 2) {
  if (n === null || n === undefined || n === "" || !Number.isFinite(Number(n))) return "N/D";
  const v = Number(n);
  let s = v.toFixed(decimals);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s || "0";
}

function _termDarkenHex(color, factor = 0.68) {
  const raw = color.replace("#", "");
  const r = Math.max(0, Math.min(255, Math.round(parseInt(raw.slice(0, 2), 16) * factor)));
  const g = Math.max(0, Math.min(255, Math.round(parseInt(raw.slice(2, 4), 16) * factor)));
  const b = Math.max(0, Math.min(255, Math.round(parseInt(raw.slice(4, 6), 16) * factor)));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

function _termSetStatus(text, variant) {
  termEls.status.textContent = text;
  termEls.status.className = "sutil toolbar-status" + (variant ? ` ${variant}` : "");
}

// ---------- lista de archivos ----------

async function _termLoadRecords() {
  const mode = termEls.modeSelect.value;
  try {
    const data = await Ajuste.apiFetch(`/api/termico/records?mode=${encodeURIComponent(mode)}`);
    termRecords = data.records;
    termEls.folderLine.textContent = data.folder_exists
      ? `Carpeta: ${data.folder}`
      : `La carpeta no existe todavía: ${data.folder} (se crea sola cuando el equipo exporta el primer análisis).`;
    _termSetStatus(`${termRecords.length} archivo(s)/curva(s) detectado(s).`);
    _termRenderRecordsTable();
  } catch (ex) {
    _termSetStatus(`Error: ${ex.message}`, "error");
  }
}

function _termRenderRecordsTable() {
  const selectedSet = new Set(termSelectedPaths);
  termEls.recordsRows.innerHTML = termRecords.map((r) => {
    const cls = r.needs_review ? "term-needs-review" : (r.auto_linked ? "term-auto-linked" : "");
    const selCls = selectedSet.has(r.path) ? " term-selected" : "";
    const ipLabel = r.ip ? ` <span class="sutil">(${esc(r.ip)})</span>` : "";
    return `<tr class="${cls}${selCls}" data-path="${encodeURIComponent(r.path)}">
      <td title="${esc(r.name)}">${esc(r.name)}${ipLabel}</td>
      <td>${esc(r.modified)}</td>
      <td>${esc(r.colada_display) || "—"}</td>
      <td>${esc(r.etapa_display) || "—"}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="4" class="sutil">Sin archivos detectados.</td></tr>`;

  // Tocar una fila la agrega arriba del gráfico (como "abrir" un documento) -- para sacarla hay que usar la
  // × roja del panel de curvas abiertas, no re-tocar la fila.
  termEls.recordsRows.querySelectorAll("tr[data-path]").forEach((tr) => {
    tr.addEventListener("click", () => {
      const path = decodeURIComponent(tr.dataset.path);
      if (!termSelectedPaths.includes(path)) {
        termSelectedPaths.push(path);
        _termRenderRecordsTable();
        _termScheduleLoadSelection();
      }
    });
  });
}

function _termCloseCurve(path) {
  termSelectedPaths = termSelectedPaths.filter((p) => p !== path);
  delete termCurveVisibility[path];
  _termRenderRecordsTable();
  _termScheduleLoadSelection();
}

function _termScheduleLoadSelection() {
  if (termSelectionTimer) clearTimeout(termSelectionTimer);
  termSelectionTimer = setTimeout(_termLoadSelection, 150);
}

async function _termLoadSelection() {
  if (!termSelectedPaths.length) {
    termCurves = [];
    termEls.selectionLabel.textContent = "Seleccioná uno o más archivos para ver curvas y resultados.";
    termEls.curvesBox.style.display = "none";
    _termClearInfo();
    _termClearCompare();
    _termResetExpansion();
    _termDrawChart();
    return;
  }
  termEls.selectionLabel.textContent = `Cargando ${termSelectedPaths.length} curva(s)...`;
  try {
    const qs = termSelectedPaths.map((p) => `path=${encodeURIComponent(p)}`).join("&");
    const data = await Ajuste.apiFetch(`/api/termico/curve?${qs}`);
    termCurves = data.curves;
    for (const c of termCurves) {
      if (!(c.path in termCurveVisibility)) termCurveVisibility[c.path] = true;
    }
    termEls.selectionLabel.textContent = termCurves.length === 1
      ? termCurves[0].name
      : `${termCurves.slice(0, 2).map((c) => c.name).join(", ")}${termCurves.length > 2 ? `, +${termCurves.length - 2} más` : ""}`;
    _termRenderCurvesChecklist();
    _termRenderCarbonTseSelect();
    _termRenderInfoTab();
    _termRenderCompareTab();
    if (termCurves.length === 1 && termCurves[0].mode_group === "Microestructura") {
      _termPopulateExpansionFromMetrics(termCurves[0].metrics);
    }
    termChartState.initialized = false;
    _termDrawChart();
    _termSetStatus(`${termRecords.length} archivo(s) detectado(s). ${termCurves.length} curva(s) cargada(s).`);
  } catch (ex) {
    termEls.selectionLabel.textContent = "No se pudo leer la selección.";
    _termSetStatus(`Error: ${ex.message}`, "error");
  }
}

function _termRenderCurvesChecklist() {
  if (!termCurves.length) {
    termEls.curvesBox.style.display = "none";
    return;
  }
  termEls.curvesBox.style.display = "flex";
  termEls.curvesList.innerHTML = termCurves.map((c, i) => {
    const color = TERM_COLORS[i % TERM_COLORS.length];
    const visible = termCurveVisibility[c.path] !== false;
    return `<div class="term-curve-row">
      <span class="term-curve-swatch" style="background:${color}"></span>
      <input type="checkbox" data-vis="${encodeURIComponent(c.path)}" ${visible ? "checked" : ""} title="Mostrar/ocultar en el gráfico">
      <span class="term-curve-name">${esc(c.name)}</span>
      <button type="button" class="term-curve-close" data-close="${encodeURIComponent(c.path)}" title="Cerrar esta curva">✕</button>
    </div>`;
  }).join("");
  termEls.curvesList.querySelectorAll("[data-vis]").forEach((cb) => {
    cb.addEventListener("change", () => {
      const path = decodeURIComponent(cb.dataset.vis);
      termCurveVisibility[path] = cb.checked;
      _termDrawChart();
    });
  });
  termEls.curvesList.querySelectorAll("[data-close]").forEach((btn) => {
    btn.addEventListener("click", () => _termCloseCurve(decodeURIComponent(btn.dataset.close)));
  });
}

// ---------- TS/TL de Carbono vinculado (solo para 1 curva de Microestructura) ----------

async function _termRenderCarbonTseSelect() {
  termCarbonTseValue = null;
  termCarbonTlValue = null;
  termMicroTseValue = null;
  termEls.carbonTseSelect.innerHTML = `<option value="">(ninguno)</option>`;
  if (termCurves.length !== 1 || termCurves[0].mode_group !== "Microestructura") {
    termEls.carbonTseBox.style.display = "none";
    return;
  }
  termMicroTseValue = termCurves[0].metrics.tse;
  try {
    const { options } = await Ajuste.apiFetch(`/api/termico/carbon-tse-options?path=${encodeURIComponent(termCurves[0].path)}`);
    if (!options.length) {
      termEls.carbonTseBox.style.display = "none";
      return;
    }
    termEls.carbonTseBox.style.display = "flex";
    termEls.carbonTseSelect.innerHTML = `<option value="">(ninguno)</option>` +
      options.map((o, i) => `<option value="${i}">${esc(o.label)}</option>`).join("");
    termEls.carbonTseSelect.dataset.options = JSON.stringify(options);
  } catch (ex) {
    termEls.carbonTseBox.style.display = "none";
  }
}

// ---------- tab Información ----------

function _termClearInfo() {
  termEls.infoRows.innerHTML = "";
}

function _termRenderInfoTab() {
  if (!termCurves.length) return _termClearInfo();
  const first = termCurves[0];
  const rows = [["Archivo", first.name]];
  if (termCurves.length > 1) {
    rows.push(["Curvas seleccionadas", String(termCurves.length)]);
    const compareNames = termCurves.slice(1, 3).map((c) => c.name).join(", ") + (termCurves.length > 3 ? `, +${termCurves.length - 3} más` : "");
    rows.push(["Comparando con", compareNames]);
  }
  for (const r of first.info_rows) rows.push([r.campo, r.valor]);
  if (first.mode_group === "Microestructura" && first.vps !== null && first.vps !== undefined) {
    rows.push(["VPS (°)", _termFmtNum(first.vps, 1)]);
  }
  termEls.infoRows.innerHTML = rows.map(([k, v]) => `<tr><td>${esc(k)}</td><td>${esc(String(v))}</td></tr>`).join("");
}

// ---------- tab Comparación ----------

function _termClearCompare() {
  termEls.compareHead.innerHTML = "";
  termEls.compareRows.innerHTML = "";
  termEls.compareText.textContent = "";
}

async function _termRenderCompareTab() {
  _termClearCompare();
  if (!termCurves.length) return;
  if (termCurves[0].mode_group === "Carbono") {
    termEls.compareText.textContent = "";
    return;
  }
  if (termCurves.length === 1) {
    termEls.compareText.textContent = `Archivo: ${termCurves[0].name}\n\n${termCurves[0].result_text}`;
    return;
  }
  try {
    const data = await Ajuste.apiFetch("/api/termico/compare", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ paths: termCurves.map((c) => c.path) }),
    });
    termEls.compareHead.innerHTML = `<tr><th>Métrica</th>${data.columns.map((c) => `<th>${esc(c)}</th>`).join("")}</tr>`;
    termEls.compareRows.innerHTML = data.rows.map((r) => `<tr><td>${esc(r.metrica)}</td>${r.valores.map((v) => `<td>${esc(String(v))}</td>`).join("")}</tr>`).join("");
    termEls.compareText.textContent = data.text || "";
  } catch (ex) {
    termEls.compareText.textContent = `Error al comparar: ${ex.message}`;
  }
}

// ---------- gráfico: doble eje (temperatura / derivada), pan + zoom ----------

const termChartState = { xMin: 0, xMax: 1, yTMin: 0, yTMax: 1, yDMin: 0, yDMax: 1, drag: null, initialized: false };

function _termResizeCanvas(canvas) {
  const rect = canvas.parentElement.getBoundingClientRect();
  const dpr = window.devicePixelRatio || 1;
  const w = Math.max(80, rect.width);
  const h = Math.max(60, rect.height);
  canvas.width = Math.round(w * dpr);
  canvas.height = Math.round(h * dpr);
  canvas.style.width = `${w}px`;
  canvas.style.height = `${h}px`;
  const ctx = canvas.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);
  return { ctx, w, h };
}

function _termCurveTagValue(info, tagKey, tagLabel) {
  const aliasKey = `${tagKey} / ${tagLabel} (s)`;
  const row = info.find((r) => r.campo === tagKey || r.campo === aliasKey);
  if (!row) return null;
  const v = parseFloat(String(row.valor).replace(",", "."));
  return Number.isFinite(v) ? v : null;
}

function _termComputeInitialBounds() {
  let xMin = Infinity, xMax = -Infinity, yTMin = Infinity, yTMax = -Infinity, yDMin = Infinity, yDMax = -Infinity;
  let any = false;
  for (const c of termCurves) {
    if (termCurveVisibility[c.path] === false) continue;
    const { periodos, temperaturas, derivadas } = c.chart;
    if (!periodos.length) continue;
    any = true;
    for (let i = 0; i < periodos.length; i++) {
      if (periodos[i] < xMin) xMin = periodos[i];
      if (periodos[i] > xMax) xMax = periodos[i];
      if (temperaturas[i] < yTMin) yTMin = temperaturas[i];
      if (temperaturas[i] > yTMax) yTMax = temperaturas[i];
      if (derivadas[i] < yDMin) yDMin = derivadas[i];
      if (derivadas[i] > yDMax) yDMax = derivadas[i];
    }
  }
  if (!any) return null;
  const padX = Math.max((xMax - xMin) * 0.03, 1);
  const padYT = Math.max((yTMax - yTMin) * 0.12, 1);
  const padYD = Math.max((yDMax - yDMin) * 0.12, 0.1);
  return {
    xMin: xMin - padX, xMax: xMax + padX,
    yTMin: yTMin - padYT, yTMax: yTMax + padYT * 1.6, // extra arriba para etiquetas de tags
    yDMin: yDMin - padYD, yDMax: yDMax + padYD,
  };
}

function _termResetChartView() {
  const bounds = _termComputeInitialBounds();
  if (!bounds) return;
  Object.assign(termChartState, bounds);
  termChartState.initialized = true;
}

function _termDrawChart() {
  const canvas = termEls.chartCanvas;
  const { ctx, w, h } = _termResizeCanvas(canvas);
  const col = Ajuste.coloresGrafico(); // grilla/ejes/textos según el tema (comun.js)
  const visible = termCurves.filter((c) => termCurveVisibility[c.path] !== false && c.chart.periodos.length);
  if (!visible.length) {
    ctx.fillStyle = col.sutil;
    ctx.font = "13px system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(termCurves.length ? "Todas las curvas están ocultas." : "Seleccioná una o más curvas para graficar.", w / 2, h / 2);
    return;
  }
  if (!termChartState.initialized) _termResetChartView();

  const margin = { left: 58, right: 58, top: 26, bottom: 34 };
  const plotW = Math.max(10, w - margin.left - margin.right);
  const plotH = Math.max(10, h - margin.top - margin.bottom);
  const { xMin, xMax, yTMin, yTMax, yDMin, yDMax } = termChartState;
  const xOf = (x) => margin.left + ((x - xMin) / (xMax - xMin || 1)) * plotW;
  const yTOf = (y) => margin.top + plotH - ((y - yTMin) / (yTMax - yTMin || 1)) * plotH;
  const yDOf = (y) => margin.top + plotH - ((y - yDMin) / (yDMax - yDMin || 1)) * plotH;

  ctx.save();
  ctx.beginPath();
  ctx.rect(margin.left, margin.top, plotW, plotH);
  ctx.clip();

  // grilla
  ctx.strokeStyle = col.grilla;
  ctx.lineWidth = 1;
  for (let i = 0; i <= 6; i++) {
    const x = margin.left + (plotW / 6) * i;
    ctx.beginPath(); ctx.moveTo(x, margin.top); ctx.lineTo(x, margin.top + plotH); ctx.stroke();
  }
  for (let i = 0; i <= 5; i++) {
    const y = margin.top + (plotH / 5) * i;
    ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(margin.left + plotW, y); ctx.stroke();
  }

  // curvas
  visible.forEach((c) => {
    const colorIdx = termCurves.indexOf(c);
    const color = TERM_COLORS[colorIdx % TERM_COLORS.length];
    const derColor = _termDarkenHex(color, Ajuste.temaOscuro() ? 1.4 : 0.68);
    const { periodos, temperaturas, derivadas } = c.chart;

    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    ctx.beginPath();
    periodos.forEach((p, i) => {
      const x = xOf(p), y = yTOf(temperaturas[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();

    ctx.strokeStyle = derColor;
    ctx.lineWidth = 1;
    ctx.globalAlpha = 0.95;
    ctx.beginPath();
    periodos.forEach((p, i) => {
      const x = xOf(p), y = yDOf(derivadas[i]);
      if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
    });
    ctx.stroke();
    ctx.globalAlpha = 1;

    // lineas de tag verticales
    const tag2Label = c.mode_group === "Carbono" ? "TS" : "TSE";
    for (const [tagKey, tagLabel] of [["tag1", "TL"], ["tag2", tag2Label], ["tag3", "TRE"], ["tag4", "TF"]]) {
      const val = _termCurveTagValue(c.info_rows, tagKey, tagLabel);
      if (val === null) continue;
      const x = xOf(val);
      ctx.setLineDash([4, 4]);
      ctx.strokeStyle = color;
      ctx.lineWidth = 1.3;
      ctx.beginPath(); ctx.moveTo(x, margin.top); ctx.lineTo(x, margin.top + plotH); ctx.stroke();
      ctx.setLineDash([]);
    }
  });

  // lineas de referencia horizontales
  const refLines = [];
  if (termCarbonTseValue !== null) refLines.push([termCarbonTseValue, "#c0392b", "TS Carbono"]);
  if (termCarbonTlValue !== null) refLines.push([termCarbonTlValue, col.violeta, "TL Carbono"]);
  if (termMicroTseValue !== null && termCurves.length === 1 && termCurves[0].mode_group === "Microestructura") {
    refLines.push([termMicroTseValue, col.verdeLinea, "TSE Microestructura"]);
  }
  for (const [val, color] of refLines) {
    const y = yTOf(val);
    ctx.setLineDash([6, 3]);
    ctx.strokeStyle = color;
    ctx.lineWidth = 1.6;
    ctx.beginPath(); ctx.moveTo(margin.left, y); ctx.lineTo(margin.left + plotW, y); ctx.stroke();
    ctx.setLineDash([]);
  }
  ctx.restore();

  // etiquetas de tags (arriba, fuera del clip)
  visible.forEach((c) => {
    const colorIdx = termCurves.indexOf(c);
    const color = TERM_COLORS[colorIdx % TERM_COLORS.length];
    const tag2Label = c.mode_group === "Carbono" ? "TS" : "TSE";
    ctx.font = "9px system-ui, sans-serif";
    ctx.fillStyle = color;
    for (const [tagKey, tagLabel] of [["tag1", "TL"], ["tag2", tag2Label], ["tag3", "TRE"], ["tag4", "TF"]]) {
      const val = _termCurveTagValue(c.info_rows, tagKey, tagLabel);
      if (val === null || val < xMin || val > xMax) continue;
      const x = xOf(val);
      ctx.save();
      ctx.translate(x, margin.top - 4);
      ctx.rotate(-Math.PI / 2);
      ctx.textAlign = "left";
      ctx.textBaseline = "middle";
      ctx.fillText(tagLabel, 0, 0);
      ctx.restore();
    }
  });

  // valores de lineas de referencia (a la derecha)
  ctx.font = "10px system-ui, sans-serif";
  ctx.textAlign = "right";
  ctx.textBaseline = "middle";
  for (const [val, color, label] of refLines) {
    if (val < yTMin || val > yTMax) continue;
    const y = yTOf(val);
    ctx.fillStyle = color;
    ctx.fillText(`${label} ${_termFmtNum(val, 1)} C`, margin.left + plotW - 4, y - 8);
  }

  // ejes
  ctx.strokeStyle = col.ejeSuave;
  ctx.lineWidth = 1;
  ctx.strokeRect(margin.left, margin.top, plotW, plotH);

  ctx.fillStyle = col.texto;
  ctx.font = "10px system-ui, sans-serif";
  ctx.textBaseline = "middle";
  ctx.textAlign = "right";
  for (let i = 0; i <= 5; i++) {
    const val = yTMin + ((yTMax - yTMin) / 5) * (5 - i);
    const y = margin.top + (plotH / 5) * i;
    ctx.fillText(_termFmtNum(val, 0), margin.left - 6, y);
  }
  ctx.textAlign = "left";
  for (let i = 0; i <= 5; i++) {
    const val = yDMin + ((yDMax - yDMin) / 5) * (5 - i);
    const y = margin.top + (plotH / 5) * i;
    ctx.fillText(_termFmtNum(val, 2), margin.left + plotW + 6, y);
  }
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  for (let i = 0; i <= 6; i++) {
    const val = xMin + ((xMax - xMin) / 6) * i;
    const x = margin.left + (plotW / 6) * i;
    ctx.fillText(_termFmtNum(val, 0), x, margin.top + plotH + 6);
  }

  ctx.save();
  ctx.translate(12, margin.top + plotH / 2);
  ctx.rotate(-Math.PI / 2);
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("Temperatura", 0, 0);
  ctx.restore();
  ctx.save();
  ctx.translate(w - 10, margin.top + plotH / 2);
  ctx.rotate(Math.PI / 2);
  ctx.textAlign = "center";
  ctx.textBaseline = "middle";
  ctx.fillText("Derivada", 0, 0);
  ctx.restore();
  ctx.textAlign = "center";
  ctx.textBaseline = "top";
  ctx.fillText("Periodo (s)", margin.left + plotW / 2, h - 12);
}

// ---------- interacción: pan + zoom ----------

function _termBindChartInteractions() {
  const canvas = termEls.chartCanvas;
  const margin = { left: 58, right: 58, top: 26, bottom: 34 };

  canvas.addEventListener("wheel", (e) => {
    if (!termChartState.initialized) return;
    e.preventDefault();
    const rect = canvas.getBoundingClientRect();
    const px = e.clientX - rect.left, py = e.clientY - rect.top;
    const plotW = rect.width - margin.left - margin.right;
    const plotH = rect.height - margin.top - margin.bottom;
    const scale = e.deltaY < 0 ? (1 / 1.2) : 1.2;

    const xFrac = (px - margin.left) / plotW;
    const xData = termChartState.xMin + xFrac * (termChartState.xMax - termChartState.xMin);
    termChartState.xMin = xData - (xData - termChartState.xMin) * scale;
    termChartState.xMax = xData + (termChartState.xMax - xData) * scale;

    const yFrac = (py - margin.top) / plotH;
    const yTData = termChartState.yTMax - yFrac * (termChartState.yTMax - termChartState.yTMin);
    termChartState.yTMin = yTData - (yTData - termChartState.yTMin) * scale;
    termChartState.yTMax = yTData + (termChartState.yTMax - yTData) * scale;
    const yDData = termChartState.yDMax - yFrac * (termChartState.yDMax - termChartState.yDMin);
    termChartState.yDMin = yDData - (yDData - termChartState.yDMin) * scale;
    termChartState.yDMax = yDData + (termChartState.yDMax - yDData) * scale;

    _termDrawChart();
  }, { passive: false });

  canvas.addEventListener("mousedown", (e) => {
    if (e.button !== 0 || !termChartState.initialized) return;
    termChartState.drag = { x: e.clientX, y: e.clientY, ...termChartState };
  });
  window.addEventListener("mousemove", (e) => {
    if (!termChartState.drag) return;
    const rect = canvas.getBoundingClientRect();
    const plotW = rect.width - margin.left - margin.right;
    const plotH = rect.height - margin.top - margin.bottom;
    const dx = ((e.clientX - termChartState.drag.x) / plotW) * (termChartState.drag.xMax - termChartState.drag.xMin);
    const dyT = ((e.clientY - termChartState.drag.y) / plotH) * (termChartState.drag.yTMax - termChartState.drag.yTMin);
    const dyD = ((e.clientY - termChartState.drag.y) / plotH) * (termChartState.drag.yDMax - termChartState.drag.yDMin);
    termChartState.xMin = termChartState.drag.xMin - dx;
    termChartState.xMax = termChartState.drag.xMax - dx;
    termChartState.yTMin = termChartState.drag.yTMin + dyT;
    termChartState.yTMax = termChartState.drag.yTMax + dyT;
    termChartState.yDMin = termChartState.drag.yDMin + dyD;
    termChartState.yDMax = termChartState.drag.yDMax + dyD;
    _termDrawChart();
  });
  window.addEventListener("mouseup", () => { termChartState.drag = null; });
  canvas.addEventListener("dblclick", () => { _termResetChartView(); _termDrawChart(); });

  if (window.ResizeObserver) {
    new ResizeObserver(() => _termDrawChart()).observe(canvas.parentElement);
  }
  window.addEventListener("ajuste:tema", () => _termDrawChart());
}

// ---------- calculadora de expansión (cliente, matematica pura) ----------

function _termParseExpField(id) {
  const v = parseFloat(String(document.getElementById(id).value || "").replace(",", "."));
  return Number.isFinite(v) ? v : null;
}

function _termApplyExpResult(valId, statusId, value, threshold) {
  const valEl = document.getElementById(valId);
  const stEl = document.getElementById(statusId);
  if (value === null) {
    valEl.textContent = "—";
    valEl.className = "term-exp-badge";
    stEl.textContent = "";
    return;
  }
  const pct = value * 100;
  const ok = value >= threshold;
  valEl.textContent = `${_termFmtNum(pct, 1)} %`;
  valEl.className = "term-exp-badge " + (ok ? "term-ok" : "term-fail");
  stEl.textContent = ok ? "✓ OK" : `✗ Bajo (mín ${threshold * 100}%)`;
}

function _termCalcExpansion() {
  const t1 = _termParseExpField("exp-tag1");
  const t2 = _termParseExpField("exp-tag2");
  const t3 = _termParseExpField("exp-tag3");
  const t4 = _termParseExpField("exp-tag4");
  let gray = null, nod = null;
  if (t1 !== null && t2 !== null && t4 !== null && t4 !== t1) gray = (t4 - t2) / (t4 - t1);
  if (t1 !== null && t3 !== null && t4 !== null && t4 !== t1) nod = (t4 - t3) / (t4 - t1);
  _termApplyExpResult("exp-gray-val", "exp-gray-status", gray, 0.60);
  _termApplyExpResult("exp-nod-val", "exp-nod-status", nod, 0.70);
}

function _termResetExpansion() {
  ["exp-tag1", "exp-tag2", "exp-tag3", "exp-tag4"].forEach((id) => { document.getElementById(id).value = ""; });
  document.getElementById("exp-source-note").textContent = "";
  _termCalcExpansion();
}

function _termPopulateExpansionFromMetrics(metrics) {
  document.getElementById("exp-tag1").value = metrics.tag1 ?? "";
  document.getElementById("exp-tag2").value = metrics.tag2 ?? "";
  document.getElementById("exp-tag3").value = metrics.tag3 ?? "";
  document.getElementById("exp-tag4").value = metrics.tag4 ?? "";
  // El equipo no informa tag1-4 en la descarga por red (siempre llegan en 0 via dadoshist.cgi) -- el
  // backend los deriva de la propia curva temperatura-tiempo buscando donde cruza TL/TSE/TRE/TF (ver
  // _derive_tags_from_series en rutas/termico.py). Avisar que son estimados, no un tiempo que el equipo
  // midió directo, para que el operario sepa que puede corregirlos a mano si el cruce no fue preciso.
  const note = document.getElementById("exp-source-note");
  note.textContent = metrics.tags_derived
    ? "Tiempos estimados a partir de la curva (el equipo no informa tag1-4 en la descarga por red) — se pueden corregir a mano."
    : "";
  _termCalcExpansion();
}

// ---------- adjuntar a Históricos ----------

async function _termOpenAttachModal() {
  if (!termCurves.length) { alert("Seleccioná una o más curvas para adjuntar."); return; }
  let coladas = [];
  let etapas = [];
  try {
    [{ coladas }, { etapas }] = await Promise.all([
      Ajuste.apiFetch("/api/termico/coladas"),
      Ajuste.apiFetch("/api/termico/etapas"),
    ]);
  } catch (ex) {
    alert(`No se pudo cargar coladas/etapas: ${ex.message}`);
    return;
  }
  if (!etapas.length) {
    alert("No hay etapas de inoculación configuradas. Definilas en Catálogo → Aleación final → Protocolo de inoculación.");
  }
  const suggestedColada = termCurves.find((c) => c.suggested_colada)?.suggested_colada || coladas[0] || "";
  const suggestedBase = termCurves[0].suggested_material_base || "";

  abrirModal(`
    <h2>Adjuntar ${termCurves.length} curva(s) térmica(s)</h2>
    <div class="row">
      <div><label>Colada</label><input id="at-colada" list="at-coladas-list" style="width:220px;" value="${esc(suggestedColada)}"></div>
      <div><label>Material base</label><input id="at-base" style="width:180px;" value="${esc(suggestedBase)}"></div>
    </div>
    <datalist id="at-coladas-list">${coladas.map((c) => `<option value="${esc(c)}">`).join("")}</datalist>
    <div class="term-table-wrap">
      <table>
        <thead><tr><th>Curva</th><th>Observación</th><th>Etapa *</th></tr></thead>
        <tbody id="at-rows">
          ${termCurves.map((c) => `<tr data-path="${encodeURIComponent(c.path)}">
            <td>${esc(c.name)}</td>
            <td><input type="text" data-obs style="width:100%;"></td>
            <td><select data-etapa><option value="">(elegir)</option>${etapas.map((e) => `<option value="${esc(e)}">${esc(e)}</option>`).join("")}</select></td>
          </tr>`).join("")}
        </tbody>
      </table>
    </div>
    <p id="at-status" class="error" style="margin-top:8px;"></p>
    <div class="botones" style="justify-content:flex-end;margin-top:10px;">
      <button type="button" id="at-cancel">Cancelar</button>
      <button type="button" id="at-save" class="primario">Guardar / Adjuntar</button>
    </div>`, true);

  document.getElementById("at-cancel").addEventListener("click", cerrarModal);
  document.getElementById("at-save").addEventListener("click", async () => {
    const colada = document.getElementById("at-colada").value.trim();
    const materialBase = document.getElementById("at-base").value.trim();
    if (!colada) { alert("Ingresá una colada."); return; }
    const observations = {};
    const etapasByPath = {};
    let missing = false;
    document.querySelectorAll("#at-rows tr").forEach((tr) => {
      const path = decodeURIComponent(tr.dataset.path);
      observations[path] = tr.querySelector("[data-obs]").value.trim();
      const etapa = tr.querySelector("[data-etapa]").value.trim();
      etapasByPath[path] = etapa;
      if (!etapa) missing = true;
    });
    if (missing) {
      alert("Seleccioná la etapa de toma de muestra para cada curva antes de adjuntar.");
      return;
    }
    try {
      await Ajuste.apiFetch("/api/termico/attach", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: termCurves.map((c) => c.path), colada, material_base: materialBase, observations, etapas: etapasByPath }),
      });
      cerrarModal();
      _termSetStatus(`Curva(s) adjuntada(s) a Históricos: colada ${colada}.`);
      await _termLoadRecords();
    } catch (ex) {
      document.getElementById("at-status").textContent = `Error: ${ex.detail?.detail?.error || ex.message}`;
    }
  });
}

// ---------- editar vínculo ----------

async function _termOpenEditLinkModal() {
  if (termSelectedPaths.length !== 1) { alert("Seleccioná una sola curva vinculada para editar."); return; }
  const path = termSelectedPaths[0];
  let entries = [];
  try {
    ({ entries } = await Ajuste.apiFetch(`/api/termico/link?path=${encodeURIComponent(path)}`));
  } catch (ex) {
    alert(`Error: ${ex.message}`);
    return;
  }
  if (!entries.length) { alert("Esta curva todavía no está vinculada a ningún histórico."); return; }
  let etapas = [];
  try { ({ etapas } = await Ajuste.apiFetch("/api/termico/etapas")); } catch (_) { /* sin etapas configuradas */ }

  const coladaOpts = entries.map((e) => e.colada);
  abrirModal(`
    <h2>Editar vínculo de análisis térmico</h2>
    ${entries.length > 1 ? `<div class="row"><div><label>Colada</label>
      <select id="el-colada">${coladaOpts.map((c) => `<option value="${esc(c)}">${esc(c)}</option>`).join("")}</select></div></div>` : ""}
    <div class="row"><div><label>Modo</label><span id="el-mode"></span></div></div>
    <div id="el-field-row" class="row"></div>
    <div class="row"><div><label>Observación</label><input id="el-obs" style="width:280px;"></div></div>
    <div class="botones" style="justify-content:flex-end;margin-top:10px;">
      <button type="button" id="el-cancel">Cancelar</button>
      <button type="button" id="el-save" class="primario">Guardar</button>
    </div>`);

  const selColada = document.getElementById("el-colada");
  const modeSpan = document.getElementById("el-mode");
  const fieldRow = document.getElementById("el-field-row");
  const obsInput = document.getElementById("el-obs");

  function loadEntry() {
    const colada = selColada ? selColada.value : entries[0].colada;
    const entry = entries.find((e) => e.colada === colada) || entries[0];
    modeSpan.textContent = entry.mode_group || "Desconocido";
    obsInput.value = entry.observacion || "";
    if (entry.mode_group === "Carbono") {
      fieldRow.innerHTML = `<div><label>Orden</label><input id="el-orden" type="number" min="1" style="width:80px;" value="${entry.orden ?? ""}"></div>`;
    } else {
      fieldRow.innerHTML = `<div><label>Etapa</label><select id="el-etapa"><option value="">(elegir)</option>${etapas.map((e) => `<option value="${esc(e)}" ${e === entry.etapa_muestra ? "selected" : ""}>${esc(e)}</option>`).join("")}</select></div>`;
    }
  }
  if (selColada) selColada.addEventListener("change", loadEntry);
  loadEntry();

  document.getElementById("el-cancel").addEventListener("click", cerrarModal);
  document.getElementById("el-save").addEventListener("click", async () => {
    const colada = selColada ? selColada.value : entries[0].colada;
    const entry = entries.find((e) => e.colada === colada) || entries[0];
    const patch = { observacion: obsInput.value.trim() };
    if (entry.mode_group === "Carbono") {
      const raw = document.getElementById("el-orden").value.trim();
      patch.orden = raw ? parseInt(raw, 10) : null;
    } else {
      patch.etapa_muestra = document.getElementById("el-etapa").value.trim();
    }
    try {
      await Ajuste.apiFetch("/api/termico/link", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ colada, source_file: path, patch }),
      });
      cerrarModal();
      _termSetStatus("Vínculo actualizado.");
      await _termLoadRecords();
    } catch (ex) {
      alert(`No se pudo guardar el vínculo: ${ex.detail?.detail?.error || ex.message}`);
    }
  });
}

// ---------- cargar C/Si en Ajuste ----------

async function _termSendCarbonToAjuste() {
  if (termCurves.length !== 1) { alert("Seleccioná un solo análisis de Carbono para cargar C/Si en Ajuste."); return; }
  const curve = termCurves[0];
  if (curve.mode_group !== "Carbono") { alert("La carga automática a Ajuste solo aplica a análisis del modo Carbono."); return; }
  const cRow = curve.info_rows.find((r) => r.campo === "C %");
  const siRow = curve.info_rows.find((r) => r.campo === "Si %");
  const carbon = cRow ? parseFloat(String(cRow.valor).replace(",", ".")) : null;
  const silicon = siRow ? parseFloat(String(siRow.valor).replace(",", ".")) : null;
  if (!Number.isFinite(carbon) || !Number.isFinite(silicon)) {
    alert("Este análisis no trae Carbono y Silicio listos para cargar.");
    return;
  }
  try {
    const session = await Ajuste.apiFetch("/api/ajuste/session");
    const actual = { ...(session.actual || {}) };
    actual.C = carbon;
    actual.Si = silicon;
    let total = 0;
    for (const [el, val] of Object.entries(actual)) if (el !== "Fe") total += Number(val) || 0;
    actual.Fe = Math.max(0, 100 - total);
    await Ajuste.apiFetch("/api/ajuste/session", {
      method: "PATCH", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ actual }),
    });
    _termSetStatus(`Datos de Carbono cargados en Ajuste: C=${_termFmtNum(carbon)} / Si=${_termFmtNum(silicon)}`);
  } catch (ex) {
    alert(`No se pudo cargar C/Si en Ajuste: ${ex.detail?.detail?.error || ex.message}`);
  }
}

// ---------- descarga desde el equipo / auto-vínculo ----------

async function _termLoadDeviceIps() {
  try {
    const { ips, default: def } = await Ajuste.apiFetch("/api/termico/device-ips");
    termEls.deviceIpsList.innerHTML = ips.map((ip) => `<option value="${esc(ip)}">`).join("");
    if (!termEls.deviceIp.value) termEls.deviceIp.value = ips[0] || def;
  } catch (_) { /* no hay IPs guardadas todavia, no es un error */ }
}

async function _termDownloadFromDevice() {
  const ip = termEls.deviceIp.value.trim();
  if (!ip) { alert("Ingresá la IP del equipo."); return; }
  termEls.btnDownload.disabled = true;
  _termSetStatus(`Descargando análisis térmicos desde ${ip}… puede tardar un rato.`);
  try {
    const res = await Ajuste.apiFetch("/api/termico/download", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ ip }),
    });
    _termSetStatus(res.message);
    await _termLoadDeviceIps();
    await _termLoadRecords();
  } catch (ex) {
    _termSetStatus(`No se pudo descargar desde ${ip}: ${ex.detail?.detail?.error || ex.message}`, "error");
  } finally {
    termEls.btnDownload.disabled = false;
  }
}

async function _termRunAutoLink(modeGroup) {
  if (!confirm(`¿Vincular automáticamente todas las curvas sueltas de ${modeGroup} por cercanía de horario?`)) return;
  try {
    const res = await Ajuste.apiFetch("/api/termico/auto-link", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ mode_group: modeGroup }),
    });
    _termSetStatus(res.message);
    await _termLoadRecords();
  } catch (ex) {
    _termSetStatus(`Error: ${ex.message}`, "error");
  }
}

// ---------- Vista ----------

VISTAS.termico = async () => {
  $("#vista").innerHTML = `
    <div class="encabezado"><h2>Análisis Térmico</h2></div>
    <div class="tarjeta">
      <div class="toolbar" style="flex-wrap:wrap;">
        <select id="mode-select">
          <option value="Microestructura">Microestructura</option>
          <option value="Carbono">Carbono</option>
          <option value="Todos">Todos</option>
        </select>
        <button id="btn-refresh">Actualizar</button>
        <button id="btn-open-folder">Abrir carpeta</button>
        <input id="device-ip" list="device-ips-list" style="width:130px;" placeholder="IP del equipo">
        <datalist id="device-ips-list"></datalist>
        <button id="btn-download" class="primario">Descargar dispositivo</button>
        <button id="btn-auto-micro">Vincular Microestructura por horario</button>
        <button id="btn-auto-carbon">Vincular Carbono por horario</button>
        <button id="btn-attach" class="primario">Adjuntar a Históricos</button>
        <button id="btn-edit-link">Editar vínculo</button>
        <button id="btn-send-ajuste">Cargar C/Si en Ajuste</button>
        <button id="btn-delete" class="peligro">Eliminar</button>
        <span id="status" class="sutil toolbar-status"></span>
      </div>
      <p id="folder-line" class="sutil"></p>
    </div>

    <div class="tarjeta term-shell">
      <div class="term-list-pane">
        <div class="term-table-wrap">
          <table>
            <thead><tr><th>Archivo</th><th>Modificado</th><th>Vinculado a</th><th>Etapa</th></tr></thead>
            <tbody id="records-rows"></tbody>
          </table>
        </div>
      </div>

      <div class="term-detail-pane">
        <p id="selection-label" class="sutil">Seleccioná uno o más archivos para ver curvas y resultados.</p>

        <div id="curves-box" class="term-curves-box" style="display:none;">
          <div id="curves-list" class="term-curves-list"></div>
          <div id="carbon-tse-box" class="term-carbon-tse" style="display:none;">
            <label>TS / TL de Carbono vinculado</label>
            <select id="carbon-tse-select"><option value="">(ninguno)</option></select>
            <button id="btn-clear-tse" type="button">Quitar línea</button>
          </div>
        </div>

        <div class="term-chart-wrap"><canvas id="chart-termico"></canvas></div>
        <p class="sutil" style="margin-top:4px;">Rueda del mouse: zoom. Click + arrastrar: pan. Doble click: reset.</p>

        <div id="detail-tabs" class="term-tabs" style="margin:12px 0 8px;">
          <button type="button" class="term-tab active" data-tab="info">Información</button>
          <button type="button" class="term-tab" data-tab="compare">Comparación</button>
          <button type="button" class="term-tab" data-tab="expansion">Expansión</button>
        </div>

        <div id="tab-info" class="term-tab-panel">
          <table><tbody id="info-rows"></tbody></table>
        </div>

        <div id="tab-compare" class="term-tab-panel" style="display:none;">
          <div class="term-table-wrap">
            <table id="compare-table"><thead id="compare-head"></thead><tbody id="compare-rows"></tbody></table>
          </div>
          <pre id="compare-text" class="term-summary"></pre>
        </div>

        <div id="tab-expansion" class="term-tab-panel" style="display:none;">
          <p class="sutil">Ingresá los tiempos (tag) en segundos desde el inicio del análisis. Se autocompletan al elegir una curva de Microestructura.</p>
          <p id="exp-source-note" class="sutil"></p>
          <div class="term-exp-fields">
            <label>tag1 — Tiempo en TL (Liquidus) [s]<input id="exp-tag1" type="text"></label>
            <label>tag2 — Tiempo en TSE (Inicio eutéctico) [s]<input id="exp-tag2" type="text"></label>
            <label>tag3 — Tiempo en TRE (Fin eutéctico / REC) [s]<input id="exp-tag3" type="text"></label>
            <label>tag4 — Tiempo en TF (Solidificación final) [s]<input id="exp-tag4" type="text"></label>
          </div>
          <button id="btn-exp-clear" type="button" style="margin-top:6px;">Limpiar</button>
          <div class="term-exp-results">
            <div class="term-exp-result"><span>Expansión gris:</span><span id="exp-gray-val" class="term-exp-badge">—</span><span id="exp-gray-status"></span></div>
            <div class="term-exp-result"><span>Expansión nodular:</span><span id="exp-nod-val" class="term-exp-badge">—</span><span id="exp-nod-status"></span></div>
          </div>
          <p class="sutil">Fórmulas: Exp. gris = (tag4−tag2)/(tag4−tag1) → objetivo &gt; 60%. Exp. nodular = (tag4−tag3)/(tag4−tag1) → objetivo &gt; 70%.</p>
        </div>
      </div>
    </div>`;

  termEls = {
    modeSelect: document.getElementById("mode-select"),
    btnRefresh: document.getElementById("btn-refresh"),
    btnOpenFolder: document.getElementById("btn-open-folder"),
    deviceIp: document.getElementById("device-ip"),
    deviceIpsList: document.getElementById("device-ips-list"),
    btnDownload: document.getElementById("btn-download"),
    btnAutoMicro: document.getElementById("btn-auto-micro"),
    btnAutoCarbon: document.getElementById("btn-auto-carbon"),
    btnAttach: document.getElementById("btn-attach"),
    btnEditLink: document.getElementById("btn-edit-link"),
    btnSendAjuste: document.getElementById("btn-send-ajuste"),
    btnDelete: document.getElementById("btn-delete"),
    status: document.getElementById("status"),
    folderLine: document.getElementById("folder-line"),
    recordsRows: document.getElementById("records-rows"),
    selectionLabel: document.getElementById("selection-label"),
    curvesBox: document.getElementById("curves-box"),
    curvesList: document.getElementById("curves-list"),
    carbonTseBox: document.getElementById("carbon-tse-box"),
    carbonTseSelect: document.getElementById("carbon-tse-select"),
    btnClearTse: document.getElementById("btn-clear-tse"),
    chartCanvas: document.getElementById("chart-termico"),
    infoRows: document.getElementById("info-rows"),
    compareHead: document.getElementById("compare-head"),
    compareRows: document.getElementById("compare-rows"),
    compareText: document.getElementById("compare-text"),
  };

  termRecords = [];
  termSelectedPaths = [];
  termCurves = [];
  termCurveVisibility = {};
  termChartState.initialized = false;

  termEls.carbonTseSelect.addEventListener("change", () => {
    const options = JSON.parse(termEls.carbonTseSelect.dataset.options || "[]");
    const picked = options[Number(termEls.carbonTseSelect.value)];
    termCarbonTseValue = picked ? picked.ts : null;
    termCarbonTlValue = picked ? picked.tl : null;
    _termDrawChart();
  });
  termEls.btnClearTse.addEventListener("click", () => {
    termCarbonTseValue = null;
    termCarbonTlValue = null;
    termEls.carbonTseSelect.value = "";
    _termDrawChart();
  });

  document.getElementById("btn-exp-clear").addEventListener("click", _termResetExpansion);
  ["exp-tag1", "exp-tag2", "exp-tag3", "exp-tag4"].forEach((id) => {
    document.getElementById(id).addEventListener("input", _termCalcExpansion);
  });

  document.querySelectorAll("#detail-tabs .term-tab").forEach((btn) => {
    btn.addEventListener("click", () => {
      document.querySelectorAll("#detail-tabs .term-tab").forEach((b) => b.classList.toggle("active", b === btn));
      document.querySelectorAll(".term-tab-panel").forEach((el) => { el.style.display = el.id === `tab-${btn.dataset.tab}` ? "block" : "none"; });
    });
  });

  termEls.modeSelect.addEventListener("change", _termLoadRecords);
  termEls.btnRefresh.addEventListener("click", _termLoadRecords);
  termEls.btnOpenFolder.addEventListener("click", async () => {
    try {
      await Ajuste.apiFetch("/api/termico/open-folder", { method: "POST" });
      _termSetStatus("Abriendo carpeta en la PC del servidor…");
    } catch (ex) {
      _termSetStatus(`Error: ${ex.message}`, "error");
    }
  });
  termEls.btnDownload.addEventListener("click", _termDownloadFromDevice);
  termEls.btnAutoMicro.addEventListener("click", () => _termRunAutoLink("Microestructura"));
  termEls.btnAutoCarbon.addEventListener("click", () => _termRunAutoLink("Carbono"));
  termEls.btnAttach.addEventListener("click", _termOpenAttachModal);
  termEls.btnEditLink.addEventListener("click", _termOpenEditLinkModal);
  termEls.btnSendAjuste.addEventListener("click", _termSendCarbonToAjuste);
  termEls.btnDelete.addEventListener("click", async () => {
    if (!termSelectedPaths.length) { alert("No hay registros seleccionados."); return; }
    if (!confirm(`¿Eliminar ${termSelectedPaths.length} registro(s)? Esto borra los archivos de la carpeta compartida.`)) return;
    try {
      const res = await Ajuste.apiFetch("/api/termico/records", {
        method: "DELETE", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ paths: termSelectedPaths }),
      });
      termSelectedPaths = [];
      _termSetStatus(`${res.deleted} registro(s) eliminado(s).${res.errors.length ? ` Errores: ${res.errors.join("; ")}` : ""}`);
      await _termLoadRecords();
      await _termLoadSelection();
    } catch (ex) {
      _termSetStatus(`Error: ${ex.message}`, "error");
    }
  });

  Ajuste.waitForApproval(async () => {
    _termBindChartInteractions();
    await Promise.all([_termLoadRecords(), _termLoadDeviceIps()]);
    _termDrawChart();
  });
};
