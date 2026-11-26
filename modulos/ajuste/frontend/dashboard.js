// dashboard.js -- puerto de frontend/js/dashboard.js de ajuste_comp_web como VISTAS.dashboard del shell del
// núcleo (antes era su propia página dashboard.html). Cada ficha de %S sale de la misma fábrica `sulfurCard`,
// apuntando a su propio endpoint de rutas/dashboard.py -- un punto por colada (ver el docstring de
// _azufre_por_colada en el backend para el criterio de "filtrar datos raros"). Gráfico dibujado a mano en
// <canvas>, sin pan/zoom: cada ficha es un resumen de un vistazo.
const SULFUR_CARDS = [
  { key: "nod", titulo: "Azufre en nodulares (8 / 10)", endpoint: "/api/dashboard/azufre-nodulares" },
  { key: "gris2", titulo: "Azufre en gris — base 2", endpoint: "/api/dashboard/azufre-base/2" },
  { key: "gris5", titulo: "Azufre en gris — base 5", endpoint: "/api/dashboard/azufre-base/5" },
];

function _resizeCanvas(canvas) {
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

function _fmtFecha(ts) {
  if (!ts) return "";
  const [fecha, hora] = String(ts).split(" ");
  const [y, m, d] = (fecha || "").split("-");
  return d && m && y ? `${d}/${m}/${y}${hora ? " " + hora.slice(0, 5) : ""}` : ts;
}

function _sulfurCard(grid, { key, titulo, endpoint }) {
  const card = document.createElement("div");
  card.className = "tarjeta dash-card";
  card.innerHTML = `
    <div class="dash-card-head">
      <h2>${esc(titulo)}</h2>
      <p class="sutil" id="s-subtitle-${key}">—</p>
    </div>
    <div class="dash-chart-wrap">
      <canvas id="s-chart-${key}"></canvas>
      <div id="s-tooltip-${key}" class="dash-tooltip"></div>
    </div>
    <div class="dash-card-foot">
      <div class="dash-stats" id="s-stats-${key}"></div>
      <p class="dash-note" id="s-note-${key}"></p>
    </div>`;
  grid.appendChild(card);

  const els = {
    canvas: document.getElementById(`s-chart-${key}`),
    tooltip: document.getElementById(`s-tooltip-${key}`),
    subtitle: document.getElementById(`s-subtitle-${key}`),
    stats: document.getElementById(`s-stats-${key}`),
    note: document.getElementById(`s-note-${key}`),
  };

  let puntos = [];
  let layout = null; // recalculado en cada draw, lo usa el hover

  function drawChart() {
    const { ctx, w, h } = _resizeCanvas(els.canvas);
    const col = Ajuste.coloresGrafico(); // grilla/textos/serie según el tema (comun.js)
    if (!puntos.length) {
      ctx.fillStyle = col.sutil;
      ctx.font = "13px system-ui";
      ctx.textAlign = "center";
      ctx.fillText("Sin lecturas de espectro todavía.", w / 2, h / 2);
      layout = null;
      return;
    }

    const pad = { top: 14, right: 14, bottom: 26, left: 40 };
    const plotW = w - pad.left - pad.right;
    const plotH = h - pad.top - pad.bottom;

    const tMin = puntos[0]._t, tMax = puntos[puntos.length - 1]._t;
    const span = Math.max(1, tMax - tMin);
    const sMax = Math.max(0.02, ...puntos.map((p) => p.s_pct)) * 1.15;

    const x = (t) => pad.left + (t - tMin) / span * plotW;
    const y = (v) => pad.top + plotH - (v / sMax) * plotH;

    const yTicks = [0, sMax / 2, sMax];
    ctx.strokeStyle = col.grilla;
    ctx.lineWidth = 1;
    ctx.fillStyle = col.sutil;
    ctx.font = "11px system-ui";
    ctx.textAlign = "right";
    for (const t of yTicks) {
      const gy = Math.round(y(t)) + 0.5;
      ctx.beginPath();
      ctx.moveTo(pad.left, gy);
      ctx.lineTo(w - pad.right, gy);
      ctx.stroke();
      ctx.fillText(`${t.toFixed(2)}%`, pad.left - 6, gy + 3);
    }

    ctx.strokeStyle = col.serie;
    ctx.lineWidth = 2;
    ctx.lineJoin = "round";
    ctx.beginPath();
    puntos.forEach((p, i) => {
      const px = x(p._t), py = y(p.s_pct);
      if (i === 0) ctx.moveTo(px, py); else ctx.lineTo(px, py);
    });
    ctx.stroke();

    ctx.fillStyle = col.serie;
    for (const p of puntos) {
      ctx.beginPath();
      ctx.arc(x(p._t), y(p.s_pct), 3.5, 0, Math.PI * 2);
      ctx.fill();
    }

    layout = { pad, plotW, plotH, tMin, tMax, span, sMax, x, y, w, h };
  }

  function nearestPoint(px) {
    if (!layout) return null;
    const t = layout.tMin + (px - layout.pad.left) / layout.plotW * layout.span;
    let best = puntos[0], bestDist = Infinity;
    for (const p of puntos) {
      const d = Math.abs(p._t - t);
      if (d < bestDist) { bestDist = d; best = p; }
    }
    return best;
  }

  function onPointerMove(evt) {
    if (!layout) return;
    const rect = els.canvas.getBoundingClientRect();
    const px = evt.clientX - rect.left;
    if (px < layout.pad.left || px > layout.w - layout.pad.right) {
      els.tooltip.style.opacity = "0";
      return;
    }
    const p = nearestPoint(px);
    if (!p) return;
    els.tooltip.innerHTML = "";
    const val = document.createElement("div");
    val.className = "tt-val";
    val.textContent = `${p.s_pct.toFixed(2)}% S`;
    const colada = document.createElement("div");
    colada.className = "tt-row";
    colada.textContent = `Colada ${p.colada} (base ${p.objetivo})`;
    const fecha = document.createElement("div");
    fecha.className = "tt-row";
    fecha.textContent = _fmtFecha(p.ts);
    els.tooltip.append(val, colada, fecha);
    els.tooltip.style.opacity = "1";
    const left = px + 12;
    const top = layout.y(p.s_pct) - 54;
    els.tooltip.style.top = `${Math.max(2, top)}px`;
    els.tooltip.style.left = `${left}px`;
    requestAnimationFrame(() => {
      const tw = els.tooltip.offsetWidth;
      if (left + tw > layout.w - 4) els.tooltip.style.left = `${px - tw - 12}px`;
    });
  }

  function renderStats() {
    if (!puntos.length) {
      els.subtitle.textContent = "Sin datos todavía.";
      els.stats.innerHTML = "";
      return;
    }
    const vals = puntos.map((p) => p.s_pct).slice().sort((a, b) => a - b);
    const mediana = vals[Math.floor(vals.length / 2)];
    const max = vals[vals.length - 1];
    els.subtitle.textContent =
      `${_fmtFecha(puntos[0].ts).split(" ")[0]} – ${_fmtFecha(puntos[puntos.length - 1].ts).split(" ")[0]} · ${puntos.length} coladas`;
    els.stats.innerHTML =
      `<span>Mediana: <b>${mediana.toFixed(2)}%</b></span>` +
      `<span>Máximo: <b>${max.toFixed(2)}%</b></span>`;
    const conVarias = puntos.filter((p) => p.n_lecturas > 1).length;
    els.note.textContent = conVarias
      ? `Un punto por colada (última lectura de espectro de esa sesión). ${conVarias} colada(s) tuvieron más de una lectura — se descartaron las intermedias, quedó solo la final.`
      : "Un punto por colada (última lectura de espectro de esa sesión).";
  }

  return {
    async load() {
      try {
        const data = await Ajuste.apiFetch(endpoint);
        puntos = (data.puntos || [])
          .map((p) => ({ ...p, _t: new Date((p.ts || "").replace(" ", "T")).getTime() }))
          .filter((p) => Number.isFinite(p._t));
      } catch (ex) {
        els.subtitle.textContent = `Error cargando datos: ${ex.message}`;
        return;
      }
      renderStats();
      drawChart();
      new ResizeObserver(() => drawChart()).observe(els.canvas.parentElement);
      window.addEventListener("ajuste:tema", () => drawChart());
      els.canvas.addEventListener("pointermove", onPointerMove);
      els.canvas.addEventListener("pointerleave", () => { els.tooltip.style.opacity = "0"; });
    },
  };
}

// ---------- Ficha "Clima espacial" (NOAA) ----------
function _fmtFechaAlerta(ts) {
  if (!ts) return "";
  const d = new Date(String(ts).replace(" ", "T") + "Z");
  if (!Number.isFinite(d.getTime())) return ts;
  return d.toLocaleString("es-AR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit" });
}

function _climaEspacialCard(grid) {
  const card = document.createElement("div");
  card.className = "tarjeta dash-card";
  card.innerHTML = `
    <div class="dash-card-head">
      <h2>Clima espacial (NOAA)</h2>
      <p class="sutil" id="space-subtitle">—</p>
    </div>
    <div class="space-badges" id="space-badges"></div>
    <ul class="space-alertas" id="space-alertas"></ul>
    <p class="dash-note">Tormentas geomagnéticas (G), de radiación solar (S) y apagones de radio por
      llamaradas (R) — Space Weather Prediction Center, NOAA. No es un dato de la planta, es informativo.</p>`;
  grid.appendChild(card);

  const els = {
    subtitle: document.getElementById("space-subtitle"),
    badges: document.getElementById("space-badges"),
    alertas: document.getElementById("space-alertas"),
  };

  return {
    async load() {
      let data;
      try {
        data = await Ajuste.apiFetch("/api/dashboard/clima-espacial");
      } catch (ex) {
        els.subtitle.textContent = `Error cargando datos: ${ex.message}`;
        return;
      }
      els.subtitle.textContent = `Actualizado ${_fmtFechaAlerta(data.obtenido_en)}`;

      els.badges.innerHTML = "";
      for (const letra of ["G", "S", "R"]) {
        const e = (data.escalas || {})[letra];
        if (!e) continue;
        const div = document.createElement("div");
        div.className = `space-badge sev-${Number(e.scale) || 0}`;
        const nivel = document.createElement("div");
        nivel.className = "sb-nivel";
        nivel.textContent = `${letra}${e.scale}`;
        const label = document.createElement("div");
        label.className = "sb-label";
        label.textContent = e.label;
        const texto = document.createElement("div");
        texto.className = "sb-text";
        texto.textContent = e.text;
        div.append(nivel, label, texto);
        els.badges.appendChild(div);
      }

      els.alertas.innerHTML = "";
      if (!data.alertas || !data.alertas.length) {
        const li = document.createElement("li");
        li.textContent = "Sin alertas recientes.";
        els.alertas.appendChild(li);
      } else {
        for (const a of data.alertas) {
          const li = document.createElement("li");
          const ts = document.createElement("span");
          ts.className = "sa-ts";
          ts.textContent = _fmtFechaAlerta(a.ts);
          li.appendChild(ts);
          if (a.escala) {
            const escEl = document.createElement("span");
            escEl.className = "sa-escala";
            escEl.textContent = a.escala;
            li.appendChild(escEl);
          }
          li.appendChild(document.createElement("br"));
          li.appendChild(document.createTextNode(a.titulo || ""));
          els.alertas.appendChild(li);
        }
      }
    },
  };
}

VISTAS.dashboard = async () => {
  $("#vista").innerHTML = `
    <div class="encabezado"><h2>Dashboard</h2>
      <button type="button" id="btn-descargar-acceso">Descargar acceso a la app</button>
    </div>
    <div class="dash-grid" id="dash-grid"></div>`;
  const grid = $("#dash-grid");
  $("#btn-descargar-acceso").addEventListener("click", () => {
    window.open("/api/dashboard/acceso.html", "_blank");
  });
  Ajuste.waitForApproval(async () => {
    for (const cfg of SULFUR_CARDS) {
      await _sulfurCard(grid, cfg).load();
    }
    await _climaEspacialCard(grid).load();
  });
};
