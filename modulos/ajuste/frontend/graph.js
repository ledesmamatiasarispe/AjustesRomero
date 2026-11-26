// graph.js — gráfico de dispersión C/Si de Ajuste, centrado en el objetivo. Los datos (transiciones, punto
// actual/estimado, polígono de límites+CE, casco convexo histórico, elipse de deriva) los arma el backend
// (GET /api/ajuste/graph, ver graph.py) — este módulo SOLO dibuja.
//
// Sistema de coordenadas: todo está centrado en el objetivo (target C/Si) — cada punto trae "dx"/"dy" = delta
// respecto al target. zoom/pan son estado puramente de la vista del cliente (no se persisten).
//
// Puerto sin cambios de frontend/js/graph.js de ajuste_comp_web, salvo quitar "export" (el núcleo concatena
// scripts planos, sin módulos ES -- createGraphView queda como función global).
const MARGIN = { left: 56, right: 26, top: 30, bottom: 48 };
const FONT_TICK = "11px 'Segoe UI', sans-serif";
const FONT_AXIS = "13px 'Segoe UI', sans-serif";
const FONT_CORNER = "11px 'Segoe UI', sans-serif";
const FONT_LABEL = "11px 'Segoe UI', sans-serif";
const FONT_LABEL_BOLD = "bold 12px 'Segoe UI', sans-serif";

function _graphFmt(n, decimals = 4) {
  if (n === null || n === undefined || !Number.isFinite(n)) return "";
  const s = Number(n).toFixed(decimals).replace(/\.?0+$/, "");
  return s === "" || s === "-" ? "0" : s;
}

function _graphLine(ctx, x1, y1, x2, y2) {
  ctx.beginPath();
  ctx.moveTo(x1, y1);
  ctx.lineTo(x2, y2);
  ctx.stroke();
}

function _graphText(ctx, x, y, str, align = "left", baseline = "middle") {
  ctx.textAlign = align;
  ctx.textBaseline = baseline;
  ctx.fillText(str, x, y);
}

function _graphDot(ctx, x, y, r, fill, outline) {
  ctx.beginPath();
  ctx.arc(x, y, r, 0, Math.PI * 2);
  ctx.fillStyle = fill;
  ctx.fill();
  if (outline) {
    ctx.strokeStyle = outline;
    ctx.lineWidth = 2;
    ctx.stroke();
  }
}

function _graphArrow(ctx, x1, y1, x2, y2, color) {
  ctx.setLineDash([]);
  ctx.strokeStyle = color;
  ctx.lineWidth = 2;
  _graphLine(ctx, x1, y1, x2, y2);
  const angle = Math.atan2(y2 - y1, x2 - x1);
  const headLen = 9;
  ctx.beginPath();
  ctx.moveTo(x2, y2);
  ctx.lineTo(x2 - headLen * Math.cos(angle - Math.PI / 7), y2 - headLen * Math.sin(angle - Math.PI / 7));
  ctx.lineTo(x2 - headLen * Math.cos(angle + Math.PI / 7), y2 - headLen * Math.sin(angle + Math.PI / 7));
  ctx.closePath();
  ctx.fillStyle = color;
  ctx.fill();
}

// Elige si una etiqueta va arriba o abajo de su punto según cuánto lugar quede hasta el borde del área de
// ploteo, para que nunca quede recortada ni pegada contra el eje/los números de esa punta.
function _graphPlaceLabelY(py, y0, y1, offset) {
  if (y1 - py < py - y0) return { dy: -offset, baseline: "bottom" };
  return { dy: offset, baseline: "top" };
}

function _graphEllipseExtent(major, minor, angle) {
  major = major || 0.03;
  minor = minor || 0.03;
  angle = angle || 0;
  const ca = Math.cos(angle), sa = Math.sin(angle);
  const xExtent = Math.sqrt((major * ca) ** 2 + (minor * sa) ** 2);
  const yExtent = Math.sqrt((major * sa) ** 2 + (minor * ca) ** 2);
  return [Math.max(0.03, xExtent), Math.max(0.03, yExtent)];
}

function createGraphView(canvas) {
  const ctx = canvas.getContext("2d");
  // El contenedor (.graph-wrap) es quien define el tamaño real vía CSS (width:100%, height fija) — el canvas
  // se mide y se fija en base a ESE rect, no al propio.
  const container = canvas.parentElement || canvas;
  const state = { zoom: 1.0, panDx: 0.0, panDy: 0.0, showBlue: false, showOrange: false, lastData: null, dragStart: null, redrawTimer: null };

  function resizeToContainer() {
    const rect = container.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(220, rect.width);
    const h = Math.max(180, rect.height);
    const bufW = Math.max(1, Math.round(w * dpr));
    const bufH = Math.max(1, Math.round(h * dpr));
    if (canvas.width !== bufW || canvas.height !== bufH) {
      canvas.width = bufW;
      canvas.height = bufH;
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    }
    return { w, h };
  }

  function draw(data) {
    if (data) state.lastData = data;
    data = state.lastData;
    if (!data) return;
    const { w, h } = resizeToContainer();
    ctx.clearRect(0, 0, w, h);
    ctx.font = FONT_AXIS;
    const col = Ajuste.coloresGrafico(); // fondo/grilla/ejes/textos según el tema (comun.js)

    if (data.error) {
      ctx.fillStyle = "#c0392b";
      _graphText(ctx, w / 2, h / 2, `Error gráfico: ${data.error}`, "center");
      return;
    }
    if (!data.has_objective) {
      ctx.fillStyle = col.sutil;
      _graphText(ctx, w / 2, h / 2, "Seleccioná aleación objetivo", "center");
      return;
    }

    const x0 = MARGIN.left, x1 = w - MARGIN.right;
    const y0 = MARGIN.top, y1 = h - MARGIN.bottom;
    const cx = (x0 + x1) / 2, cy = (y0 + y1) / 2;
    const plotW = Math.max(1, x1 - x0), plotH = Math.max(1, y1 - y0);
    const span = Math.max(data.span || 0, 0.05) / Math.max(0.1, state.zoom);
    const panDx = state.panDx, panDy = state.panDy;

    ctx.fillStyle = col.fondo;
    ctx.fillRect(x0, y0, plotW, plotH);
    ctx.strokeStyle = col.borde;
    ctx.lineWidth = 1;
    ctx.strokeRect(x0, y0, plotW, plotH);

    ctx.strokeStyle = col.grilla;
    ctx.setLineDash([]);
    for (const step of [-1.0, -0.5, 0.5, 1.0]) {
      const gx = cx + step * (plotW / 2);
      const gy = cy - step * (plotH / 2);
      _graphLine(ctx, gx, y0, gx, y1);
      _graphLine(ctx, x0, gy, x1, gy);
    }

    const zeroX = cx - (panDx / span) * (plotW / 2);
    const zeroY = cy + (panDy / span) * (plotH / 2);
    ctx.strokeStyle = col.eje;
    ctx.lineWidth = 2;
    _graphLine(ctx, x0, zeroY, x1, zeroY);
    _graphLine(ctx, zeroX, y0, zeroX, y1);
    ctx.lineWidth = 1;

    const tick = span / 2;
    const targetC = data.target_c || 0, targetSi = data.target_si || 0;
    ctx.fillStyle = col.sutil;
    ctx.font = FONT_TICK;
    _graphText(ctx, x0 + 2, zeroY + 16, (targetC + panDx - span).toFixed(3), "left");
    _graphText(ctx, cx + plotW / 4, zeroY + 16, (targetC + panDx + tick).toFixed(3), "center");
    _graphText(ctx, cx - plotW / 4, zeroY + 16, (targetC + panDx - tick).toFixed(3), "center");
    _graphText(ctx, x1 - 2, zeroY + 16, (targetC + panDx + span).toFixed(3), "right");
    _graphText(ctx, zeroX + 8, y0 + 10, (targetSi + panDy + span).toFixed(3), "left");
    _graphText(ctx, zeroX + 8, y1 - 10, (targetSi + panDy - span).toFixed(3), "left");

    ctx.fillStyle = col.texto;
    ctx.font = FONT_AXIS;
    _graphText(ctx, (x0 + x1) / 2, h - 14, "C (%)", "center");
    ctx.save();
    ctx.translate(16, (y0 + y1) / 2);
    ctx.rotate(-Math.PI / 2);
    _graphText(ctx, 0, 0, "Si (%)", "center");
    ctx.restore();

    ctx.fillStyle = col.sutil;
    ctx.font = FONT_CORNER;
    _graphText(ctx, x0 + 4, y0 + 4, `centro = obj C ${_graphFmt(targetC)} / Si ${_graphFmt(targetSi)}`, "left", "top");

    const xy = (pt) => [
      cx + ((pt.dx - panDx) / span) * (plotW / 2),
      cy - ((pt.dy - panDy) / span) * (plotH / 2),
    ];

    function drawEllipse(centerDx, centerDy, major, minor, angle, color, dash) {
      const px = cx + ((centerDx - panDx) / span) * (plotW / 2);
      const py = cy - ((centerDy - panDy) / span) * (plotH / 2);
      const scaleX = plotW / (2 * span), scaleY = plotH / (2 * span);
      const ca = Math.cos(angle || 0), sa = Math.sin(angle || 0);
      ctx.beginPath();
      for (let i = 0; i <= 64; i++) {
        const t = (2 * Math.PI * i) / 64;
        const ex = (major || 0.03) * Math.cos(t) * ca - (minor || 0.03) * Math.sin(t) * sa;
        const ey = (major || 0.03) * Math.cos(t) * sa + (minor || 0.03) * Math.sin(t) * ca;
        const x = px + ex * scaleX, y = py - ey * scaleY;
        if (i === 0) ctx.moveTo(x, y); else ctx.lineTo(x, y);
      }
      ctx.closePath();
      ctx.strokeStyle = color;
      ctx.lineWidth = 2;
      ctx.setLineDash(dash);
      ctx.stroke();
      ctx.setLineDash([]);
      const [xExtent, yExtent] = _graphEllipseExtent(major, minor, angle);
      return [px, py, Math.max(6, xExtent * scaleX), Math.max(6, yExtent * scaleY)];
    }

    function drawPolygon(polygon, { fill, stroke, dash }) {
      const coords = polygon.map(xy);
      if (coords.length < 3) return null;
      ctx.beginPath();
      coords.forEach(([x, y], i) => (i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)));
      ctx.closePath();
      if (fill) { ctx.fillStyle = fill; ctx.fill(); }
      ctx.strokeStyle = stroke;
      ctx.lineWidth = 2;
      ctx.setLineDash(dash || []);
      ctx.stroke();
      ctx.setLineDash([]);
      return coords;
    }

    // Área de límites del objetivo (recortada por CE min/max) — solo el polígono, sin etiqueta de texto.
    const targetArea = data.target_limit_area;
    if (targetArea) {
      drawPolygon(targetArea.polygon || [], { fill: col.areaObjetivo, stroke: col.verdeLinea, dash: [6, 3] });
    }

    // Casco convexo histórico por objetivo (violeta)
    for (const st of data.stat_circles || []) {
      const polygon = st.polygon || [];
      let px, py, rx;
      const coords = polygon.length >= 3 ? drawPolygon(polygon, { stroke: "#7e57c2", dash: [4, 3] }) : null;
      if (coords) {
        [px, py] = xy(st);
        rx = Math.max(6, _graphEllipseExtent(st.major, st.minor, st.angle || 0)[0] * (plotW / (2 * span)));
      } else {
        [px, py, rx] = drawEllipse(st.dx, st.dy, st.major, st.minor, st.angle || 0, "#7e57c2", [4, 3]);
      }
      if (state.showBlue) {
        for (const pt of st.plot_points || []) {
          const [ptx, pty] = xy(pt);
          _graphDot(ctx, ptx, pty, 2, "#1e88e5");
        }
      }
      const count = st.count || 0, rawCount = st.raw_count || count;
      const countLabel = rawCount === count ? String(count) : `${count}/${rawCount}`;
      ctx.fillStyle = col.violeta;
      ctx.font = FONT_LABEL;
      _graphText(ctx, px + rx + 4, py, `${st.material || ""} (${countLabel})`, "left");
    }

    // Elipse de deriva entre ajustes consecutivos (naranja)
    for (const st of data.step_circles || []) {
      const [px, py, rx] = drawEllipse(st.dx, st.dy, st.major, st.minor, st.angle || 0, "#fb8c00", [2, 3]);
      if (state.showOrange) {
        for (const pt of st.plot_points || []) {
          const [ptx, pty] = xy(pt);
          _graphDot(ctx, ptx, pty, 2, "#fb8c00");
        }
      }
      const count = st.count || 0, rawCount = st.raw_count || count;
      const countLabel = rawCount === count ? String(count) : `${count}/${rawCount}`;
      ctx.fillStyle = col.naranja;
      ctx.font = FONT_LABEL;
      _graphText(ctx, px + rx + 4, py, `sig ${st.label || ""} (${countLabel})`, "left");
    }

    // Ajustes aplicados en la sesión en curso (flechas numeradas)
    for (const tr of data.transitions || []) {
      const [sx, sy] = xy(tr.start);
      const [ex, ey] = xy(tr.end);
      _graphArrow(ctx, sx, sy, ex, ey, col.sutil);
      _graphDot(ctx, sx, sy, 5, "#e53935", "#7f1715");
      _graphDot(ctx, ex, ey, 5, "#1e88e5", "#0d47a1");
      ctx.fillStyle = col.texto;
      ctx.font = FONT_LABEL_BOLD;
      const lx = ex >= sx ? ex + 8 : ex - 8;
      _graphText(ctx, lx, ey, tr.label, ex >= sx ? "left" : "right");
    }

    // Actual -> Estimado (plan cargado ahora, todavía no aplicado).
    const current = data.current, estimated = data.estimated;
    if (current && estimated) {
      const [sx, sy] = xy(current);
      const [ex, ey] = xy(estimated);
      _graphArrow(ctx, sx, sy, ex, ey, col.verdeLinea);
      _graphDot(ctx, ex, ey, 6, "#43a047", "#1b5e20");
      ctx.fillStyle = col.verde;
      ctx.font = FONT_LABEL_BOLD;
      const { dy, baseline } = _graphPlaceLabelY(ey, y0, y1, 12);
      _graphText(ctx, ex + 9, ey + dy, "Estimado", "left", baseline);
    }
    if (current) {
      const [px, py] = xy(current);
      _graphDot(ctx, px, py, 6, "#ffd200", "#6f5c00");
      ctx.fillStyle = col.texto;
      ctx.font = FONT_LABEL_BOLD;
      const { dy, baseline } = _graphPlaceLabelY(py, y0, y1, 12);
      _graphText(ctx, px + 9, py + dy, "Actual", "left", baseline);
    }
  }

  function throttledRedraw() {
    if (state.redrawTimer) return;
    state.redrawTimer = setTimeout(() => { state.redrawTimer = null; draw(); }, 33);
  }

  function resetView() {
    state.zoom = 1.0;
    state.panDx = 0.0;
    state.panDy = 0.0;
    draw();
  }

  function canvasPoint(e) {
    const rect = canvas.getBoundingClientRect();
    return [e.clientX - rect.left, e.clientY - rect.top];
  }

  canvas.addEventListener("wheel", (e) => {
    e.preventDefault();
    const oldZoom = Math.max(0.1, state.zoom);
    const factor = e.deltaY > 0 ? 1 / 1.15 : 1.15;
    const newZoom = Math.max(0.2, Math.min(12.0, oldZoom * factor));
    if (Math.abs(newZoom - oldZoom) <= 1e-12) return;
    state.zoom = newZoom;
    throttledRedraw();
  }, { passive: false });

  canvas.addEventListener("mousedown", (e) => {
    const [x, y] = canvasPoint(e);
    state.dragStart = { x, y, baseDx: state.panDx, baseDy: state.panDy };
  });
  window.addEventListener("mousemove", (e) => {
    if (!state.dragStart || !state.lastData) return;
    const [x, y] = canvasPoint(e);
    const rect = canvas.getBoundingClientRect();
    const plotW = Math.max(1, rect.width - MARGIN.left - MARGIN.right);
    const plotH = Math.max(1, rect.height - MARGIN.top - MARGIN.bottom);
    const span = Math.max(state.lastData.span || 0, 0.05) / Math.max(0.1, state.zoom);
    state.panDx = state.dragStart.baseDx - ((x - state.dragStart.x) / plotW) * (2 * span);
    state.panDy = state.dragStart.baseDy + ((y - state.dragStart.y) / plotH) * (2 * span);
    throttledRedraw();
  });
  window.addEventListener("mouseup", () => { state.dragStart = null; });
  canvas.addEventListener("dblclick", (e) => { e.preventDefault(); resetView(); });

  // ---------- Pan y zoom por touch (Pointer Events) ----------
  const activeTouches = new Map(); // pointerId -> {x, y} en clientX/clientY
  let pinchStartDist = 0;
  let pinchStartZoom = 1;

  function touchDist() {
    const pts = [...activeTouches.values()];
    return Math.hypot(pts[0].x - pts[1].x, pts[0].y - pts[1].y);
  }

  canvas.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse") return;
    try { canvas.setPointerCapture(e.pointerId); } catch (_) { /* si no lo soporta, sigue funcionando igual */ }
    activeTouches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (activeTouches.size === 2) {
      state.dragStart = null; // pausa el pan mientras se pellizca con 2 dedos
      pinchStartDist = touchDist();
      pinchStartZoom = state.zoom;
    } else if (activeTouches.size === 1) {
      const [x, y] = canvasPoint(e);
      state.dragStart = { x, y, baseDx: state.panDx, baseDy: state.panDy };
    }
  });

  canvas.addEventListener("pointermove", (e) => {
    if (e.pointerType === "mouse" || !activeTouches.has(e.pointerId)) return;
    e.preventDefault();
    activeTouches.set(e.pointerId, { x: e.clientX, y: e.clientY });
    if (activeTouches.size === 2) {
      const dist = touchDist();
      if (pinchStartDist > 0) {
        const newZoom = Math.max(0.2, Math.min(12.0, pinchStartZoom * (dist / pinchStartDist)));
        if (Math.abs(newZoom - state.zoom) > 1e-12) { state.zoom = newZoom; throttledRedraw(); }
      }
    } else if (activeTouches.size === 1 && state.dragStart && state.lastData) {
      const [x, y] = canvasPoint(e);
      const rect = canvas.getBoundingClientRect();
      const plotW = Math.max(1, rect.width - MARGIN.left - MARGIN.right);
      const plotH = Math.max(1, rect.height - MARGIN.top - MARGIN.bottom);
      const span = Math.max(state.lastData.span || 0, 0.05) / Math.max(0.1, state.zoom);
      state.panDx = state.dragStart.baseDx - ((x - state.dragStart.x) / plotW) * (2 * span);
      state.panDy = state.dragStart.baseDy + ((y - state.dragStart.y) / plotH) * (2 * span);
      throttledRedraw();
    }
  }, { passive: false });

  function endTouch(e) {
    if (e.pointerType === "mouse" || !activeTouches.has(e.pointerId)) return;
    activeTouches.delete(e.pointerId);
    if (activeTouches.size === 1) {
      const pt = [...activeTouches.values()][0];
      const rect = canvas.getBoundingClientRect();
      state.dragStart = { x: pt.x - rect.left, y: pt.y - rect.top, baseDx: state.panDx, baseDy: state.panDy };
    } else if (activeTouches.size === 0) {
      state.dragStart = null;
    }
  }
  canvas.addEventListener("pointerup", endTouch);
  canvas.addEventListener("pointercancel", endTouch);

  if (window.ResizeObserver) {
    new ResizeObserver(() => draw()).observe(container);
  }
  window.addEventListener("ajuste:tema", () => draw());

  return {
    draw,
    resetView,
    setShowBlue(v) { state.showBlue = v; draw(); },
    setShowOrange(v) { state.showOrange = v; draw(); },
  };
}
