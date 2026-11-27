// historicos.js -- puerto de frontend/js/historicos.js de ajuste_comp_web como VISTAS.historicos del shell
// del núcleo. Dock de pestañas: "Lista" (fija, no se puede cerrar) + una por cada colada abierta (se abre al
// tocar una fila de la lista, se cierra con la ×) -- mismo espíritu que el ttk.Notebook del original.
//
// Alcance de este corte: lista+detalle, editar colada, marcar sinterizado, eliminar sesión, editar/eliminar
// un ajuste puntual, exportar CSV de un ajuste, exportar todo el historial a JSON, ver/corregir el conteo de
// cucharas (los datos en sí los sigue escribiendo el kiosko de Pie de Horno, todavía no portado). Análisis
// térmico adjunto queda pendiente (depende de ese módulo, todavía no portado). "Generar informe de calidad"
// (btn-quality-report / _histOpenQualityReportModal) pega a /api/calidad/material-options y
// /api/calidad/generate-from-session -- Calidad todavía no está portado, así que ese botón hoy muestra el
// error de red tal cual (mismo try/catch que ya tenía el original); no se le sacó el botón, solo queda sin
// efecto hasta que se porte ese módulo.
//
// OJO CON LOS ÍNDICES (mismo caveat que ya documenta rutas/historicos.py): el "idx" de una colada es su
// POSICIÓN en la lista, no un id estable. Si con dos pestañas de colada abiertas se borra una sesión
// ANTERIOR a la otra en la lista, el idx de la pestaña que quedó abierta pasa a apuntar a una colada
// distinta -- mismo comportamiento (no siempre ideal) que ya tenía el original. Para no empeorarlo en
// silencio, cada vez que se (re)carga una pestaña de detalle se compara la colada guardada en la pestaña
// contra la que devuelve el servidor para ese idx, y si no coinciden se avisa.
//
// Nombres con prefijo "hist"/"_hist" a propósito: nucleo concatena todos los scripts del módulo en un solo
// scope global (sin import/export), y varios nombres genéricos que tenía el original como módulo ES
// (fmtNum, parseNum, setStatus, CAN_EDIT, SESSION, closeModal, openOverlay) YA están declarados por
// ajuste.js en ese mismo scope -- redeclarar un `function` con el mismo nombre no tira error (lo pisa en
// silencio, el último script en cargar gana) y redeclarar un `let`/`const` sí tira SyntaxError y rompe TODAS
// las pantallas. Mejor prefijar todo lo propio de este archivo que confiar en que test_pantallas.py (que
// solo detecta colisiones de let/const/class, no de function) lo note.

let histSessions = [];
let histOpenTabs = [];       // [{idx, colada}], en el orden en que se abrieron
let histActiveTab = "list";  // "list" o un idx (number)
let histCanEdit = false;
let histElements = [];

function _histFmtNum(n, decimals = 4) {
  if (n === null || n === undefined || n === "" || !Number.isFinite(Number(n))) return "";
  const v = Number(n);
  let s = v.toFixed(decimals);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s === "" || s === "-" ? "0" : s;
}

function _histParseNum(s, fallback = 0) {
  const v = parseFloat(String(s ?? "").replace(",", "."));
  return Number.isFinite(v) ? v : fallback;
}

// ---------- Dock de pestañas externo (Lista + una por colada abierta) ----------

function _histRenderOuterTabs() {
  const outer = $("#hist-outer-tabs");
  if (!outer) return;
  const listBtn = `<button type="button" class="hist-outer-tab ${histActiveTab === "list" ? "active" : ""}" data-outer-tab="list">Planilla Control de Fusión Inducción</button>`;
  const sessionBtns = histOpenTabs.map((t) => `<button type="button" class="hist-outer-tab ${histActiveTab === t.idx ? "active" : ""}" data-outer-tab="${t.idx}">
    <span>${esc(t.colada || "(sin colada)")}</span>
    <span class="hist-tab-close" data-close-tab="${t.idx}" title="Cerrar">✕</span>
  </button>`).join("");
  outer.innerHTML = listBtn + sessionBtns;

  outer.querySelectorAll(".hist-outer-tab").forEach((btn) => {
    btn.addEventListener("click", (e) => {
      if (e.target.closest("[data-close-tab]")) return; // el click de cerrar no cambia de pestaña
      const t = btn.dataset.outerTab;
      if (t === "list") _histSwitchToList(); else _histSwitchToSessionTab(Number(t));
    });
  });
  outer.querySelectorAll("[data-close-tab]").forEach((x) => {
    x.addEventListener("click", (e) => {
      e.stopPropagation();
      _histCloseSessionTab(Number(x.dataset.closeTab));
    });
  });
}

function _histSwitchToList() {
  histActiveTab = "list";
  $("#hist-panel-list").style.display = "block";
  $("#hist-panel-detail").style.display = "none";
  _histRenderOuterTabs();
  _histLoadSessions();
}

async function _histOpenSessionTab(idx) {
  const s = histSessions.find((x) => x.idx === idx);
  if (!histOpenTabs.some((t) => t.idx === idx)) {
    histOpenTabs.push({ idx, colada: s ? s.colada : "" });
  }
  await _histSwitchToSessionTab(idx);
}

async function _histSwitchToSessionTab(idx) {
  histActiveTab = idx;
  $("#hist-panel-list").style.display = "none";
  $("#hist-panel-detail").style.display = "block";
  _histRenderOuterTabs();
  await _histLoadDetail(idx);
}

function _histCloseSessionTab(idx) {
  histOpenTabs = histOpenTabs.filter((t) => t.idx !== idx);
  if (histActiveTab === idx) _histSwitchToList(); else _histRenderOuterTabs();
}

// ---------- Pestañas internas del detalle (Ajustes/Cálculos/Carbono/Spectro/Cucharas/Ensayos) ----------

function _histSwitchDetailTab(tab) {
  $("#hist-detail-tabs").querySelectorAll(".hist-detail-tab").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.tab === tab);
  });
  document.querySelectorAll(".hist-detail-panel").forEach((panel) => {
    panel.style.display = panel.id === `hist-tab-${tab}` ? "block" : "none";
  });
}

function _histSetTabLabel(tab, label, count) {
  const btn = $("#hist-detail-tabs").querySelector(`.hist-detail-tab[data-tab="${tab}"]`);
  if (btn) btn.textContent = count ? `${label} (${count})` : label;
}

// ---------- Lista ----------

async function _histLoadSessions() {
  const { sessions } = await Ajuste.apiFetch("/api/historicos/sessions");
  histSessions = sessions;
  _histRenderList();
}

function _histRenderList() {
  // Misma sintaxis de búsqueda que Calidad (número exacto, rango "91:95", ventana "91L5", texto libre) --
  // lógica compartida en colada_search.js, no duplicada acá.
  const filtered = ColadaSearch.filterByColadaQuery(histSessions, $("#hist-search").value, (s) => s.colada, (s) => s.objetivo);
  $("#hist-rows").innerHTML = filtered.map((s) => `<tr data-idx="${s.idx}">
    <td>${esc(s.colada || "")}${s.primer_sinterizado ? '<span class="hist-badge-sinterizado">S</span>' : ""}${s.has_traccion_lab ? '<span title="Tracción real Lab cargada en al menos un informe de Calidad de esta colada">🔬</span>' : ""}${s.tiene_informe_creado ? '<span class="hist-dot hist-dot-informe" title="Al menos un informe de Calidad activo (no archivado) de esta colada"></span>' : ""}${s.tiene_informe_archivado ? '<span class="hist-dot hist-dot-informe-archivado" title="Al menos un informe de Calidad archivado de esta colada"></span>' : ""}</td>
    <td>${esc(s.objetivo || "")}</td>
    <td>${s.auto_saved ? "Auto" : ""}</td>
    <td>${esc(s.started_at || "")}</td>
    <td>${esc(s.crisol)}</td>
    <td>${s.n_ajustes}</td>
  </tr>`).join("") || `<tr><td colspan="6" class="sutil">Sin coladas guardadas.</td></tr>`;
  $("#hist-rows").querySelectorAll("tr[data-idx]").forEach((tr) => {
    tr.addEventListener("click", () => _histOpenSessionTab(Number(tr.dataset.idx)));
  });
}

// ---------- Detalle ----------

async function _histLoadDetail(idx) {
  let s;
  try {
    s = await Ajuste.apiFetch(`/api/historicos/sessions/${idx}`);
  } catch (ex) {
    avisar(`Error al cargar detalle: ${ex.message}`, true);
    return;
  }
  const tabInfo = histOpenTabs.find((t) => t.idx === idx);
  if (tabInfo && tabInfo.colada && tabInfo.colada !== s.colada) {
    avisar(`Ojo: esta pestaña apuntaba a "${tabInfo.colada}" y ahora carga "${s.colada}" — probablemente se borró alguna colada anterior en la lista y los índices se corrieron. Cerrá y volvé a abrir la pestaña.`, true);
  }
  if (tabInfo) tabInfo.colada = s.colada;
  _histRenderOuterTabs();

  [$("#hist-btn-edit-colada"), $("#hist-btn-toggle-sinterizado"), $("#hist-btn-delete-session")].forEach((b) => { b.disabled = !histCanEdit; });

  $("#hist-detail-colada").textContent = s.colada || "(sin colada)";
  $("#hist-detail-summary").textContent =
    `Objetivo: ${s.objetivo || ""}\n` +
    `Guardado: ${s.auto_saved ? "Automático" : "Manual"}\n` +
    `Inicio: ${s.started_at || ""}\n` +
    `Fin: ${s.ended_at || ""}\n` +
    `Ajustes: ${s.n_ajustes}  ·  Cálculos: ${s.n_calculos}  ·  Carbono: ${s.n_carbono}`;

  _histSetTabLabel("ajustes", "Ajustes", s.n_ajustes);
  _histSetTabLabel("calculos", "Cálculos", s.n_calculos);
  _histSetTabLabel("carbono", "Carbono", s.n_carbono);
  _histSetTabLabel("spectro", "Spectro", s.n_spectro);
  _histSetTabLabel("cucharas", "Cucharas", (s.cucharas || {}).total_cucharas || 0);
  _histSetTabLabel("ensayos", "Ensayos", (s.ensayos || []).length);
  _histSwitchDetailTab("ajustes");

  $("#hist-ensayos-rows").innerHTML = (s.ensayos || []).map((e) => `<tr>
    <td>Material ${esc(e.material || "")}</td>
    <td>${esc(e.traccion_real || "")}</td>
    <td>${esc(e.estiramiento_real || "")}</td>
    <td>${esc(e.tension_real_lim_prop || "")}</td>
    <td>${esc(e.mg_disuelto || "")}</td>
  </tr>`).join("") || `<tr><td colspan="5" class="sutil">Sin ensayos reales cargados en Calidad para esta colada.</td></tr>`;

  $("#hist-adj-rows").innerHTML = (s.ajustes || []).map((a, i) => `<tr>
    <td>${esc(a.fecha || "")}</td>
    <td>${_histFmtNum(a.porcentaje, 0)}${a.porcentaje != null ? "%" : ""}</td>
    <td>${_histFmtNum(a.ce_estimado)}</td>
    <td>${esc(a.resumen || "")}</td>
    <td><button type="button" data-edit-adj="${i}">${histCanEdit ? "Editar" : "Ver"}</button></td>
    <td><button type="button" data-csv-adj="${i}">CSV</button></td>
    <td><button type="button" data-del-adj="${i}" class="peligro" ${histCanEdit ? "" : "disabled"}>Eliminar</button></td>
  </tr>`).join("") || `<tr><td colspan="7" class="sutil">Sin ajustes aplicados en esta colada.</td></tr>`;

  $("#hist-adj-rows").querySelectorAll("[data-edit-adj]").forEach((btn) => {
    btn.addEventListener("click", () => _histOpenEditAdjustModal(idx, Number(btn.dataset.editAdj), s.ajustes[Number(btn.dataset.editAdj)]));
  });
  $("#hist-adj-rows").querySelectorAll("[data-csv-adj]").forEach((btn) => {
    btn.addEventListener("click", () => {
      window.open(`/api/historicos/sessions/${idx}/adjustments/${btn.dataset.csvAdj}/export.csv`, "_blank");
    });
  });
  $("#hist-adj-rows").querySelectorAll("[data-del-adj]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      const motivo = Ajuste.pedirMotivo("¿Eliminar este ajuste de la colada?");
      if (motivo === null) return;
      try {
        await Ajuste.apiFetch(`/api/historicos/sessions/${idx}/adjustments/${btn.dataset.delAdj}`,
          { method: "DELETE", headers: Ajuste.headersMotivo(motivo) });
        await _histLoadDetail(idx);
      } catch (ex) {
        avisar(`Error: ${ex.message}`, true);
      }
    });
  });

  $("#hist-calc-rows").innerHTML = (s.calculos || []).map((c) => `<tr>
    <td>${esc(c.fecha || "")}</td>
    <td>${_histFmtNum(c.porcentaje, 0)}${c.porcentaje != null ? "%" : ""}</td>
    <td>${_histFmtNum(c.ce_estimado)}</td>
    <td>${esc(c.resumen || "")}</td>
  </tr>`).join("") || `<tr><td colspan="4" class="sutil">Sin cálculos registrados.</td></tr>`;

  $("#hist-carbon-rows").innerHTML = (s.carbono || []).map((c) => `<tr>
    <td>${esc(c.fecha || "")}</td>
    <td>${esc(c.source_name || "")}</td>
    <td>${_histFmtNum(c.carbono)}</td>
    <td>${_histFmtNum(c.silicio)}</td>
    <td>${_histFmtNum(c.ce)}</td>
  </tr>`).join("") || `<tr><td colspan="5" class="sutil">Sin lecturas de Carbono (Carbomax automático).</td></tr>`;

  $("#hist-spectro-rows").innerHTML = (s.spectro_resultados || []).map((r) => {
    const summary = Object.entries(r.elements || {})
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([el, pct]) => `${el} ${_histFmtNum(pct)}%`)
      .join(", ");
    return `<tr>
      <td>${esc(r.ts || "")}</td>
      <td>${esc(r.source || "")}</td>
      <td>${esc(summary)}</td>
    </tr>`;
  }).join("") || `<tr><td colspan="3" class="sutil">Sin resultados de Espectro para esta colada.</td></tr>`;

  _histRenderCucharas(idx, s.cucharas || {});
}

// ---------- Cucharas cargadas ----------

function _histRenderCucharas(sessionIdx, cucharas) {
  const btnEdit = $("#hist-btn-edit-cucharas");
  btnEdit.disabled = !histCanEdit || !cucharas.has_data;

  if (!cucharas.has_data) {
    $("#hist-cucharas-summary").textContent = "Sin registro de cucharas para esta colada.";
    $("#hist-cucharas-rows").innerHTML = "";
    $("#hist-cucharas-events").innerHTML = "";
    return;
  }
  $("#hist-cucharas-summary").textContent =
    `Total cucharas: ${cucharas.total_cucharas}\n` +
    `Primera: ${cucharas.first_saved_at || "—"}  ·  Última: ${cucharas.last_saved_at || "—"}\n` +
    `Duración: ${cucharas.duration_label || "—"}  ·  Intervalo promedio: ${cucharas.avg_interval_label || "—"}`;

  $("#hist-cucharas-rows").innerHTML = (cucharas.rows || []).map((r) => `<tr>
    <td>${esc(r.material_final || "")}</td><td>${r.cantidad || 0}</td>
  </tr>`).join("") || `<tr><td colspan="2" class="sutil">Sin cucharas cargadas.</td></tr>`;

  $("#hist-cucharas-events").innerHTML = (cucharas.events || []).map((e) => `<tr>
    <td>${esc(e.material || "")}</td><td>${esc(e.time || "")}</td>
  </tr>`).join("") || `<tr><td colspan="2" class="sutil">Sin eventos.</td></tr>`;

  btnEdit.onclick = () => _histOpenEditCucharasModal(sessionIdx, cucharas);
}

function _histOpenEditCucharasModal(sessionIdx, cucharas) {
  const rows = cucharas.rows || [];
  abrirModal(`
    <h2>Editar cucharas</h2>
    <p class="sutil">Corregí la cantidad de cucharas por material de esta colada.</p>
    <table><thead><tr><th>Material</th><th style="width:100px">Cantidad</th></tr></thead>
      <tbody>${rows.map((r) => `<tr>
        <td>${esc(r.material_final)}</td>
        <td><input type="number" min="0" step="1" data-mat="${esc(r.material_final)}" value="${r.cantidad || 0}"></td>
      </tr>`).join("")}</tbody>
    </table>
    <p id="hist-ecu-error" class="error"></p>
    <div class="botones" style="margin-top:10px;">
      <button type="button" id="hist-ecu-cancel">Cancelar</button>
      <button type="button" id="hist-ecu-save" class="primario">Guardar</button>
    </div>`);
  document.getElementById("hist-ecu-cancel").onclick = cerrarModal;
  document.getElementById("hist-ecu-save").onclick = async () => {
    const counts = {};
    document.querySelectorAll("[data-mat]").forEach((inp) => {
      counts[inp.dataset.mat] = _histParseNum(inp.value, 0);
    });
    const errEl = document.getElementById("hist-ecu-error");
    try {
      await Ajuste.apiFetch(`/api/historicos/sessions/${sessionIdx}/cucharas`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ counts }),
      });
      await _histLoadDetail(sessionIdx);
      cerrarModal();
    } catch (ex) {
      errEl.textContent = ex.detail?.detail?.error || ex.message;
    }
  };
}

// ---------- Editar un ajuste puntual ----------

function _histOpenEditAdjustModal(sessionIdx, adjIdx, adj) {
  const mats = adj.materiales || {};
  const names = Object.keys(mats).sort();
  const compIni = (adj.inicial || {}).comp || {};
  const compEst = (adj.estimado || {}).comp || {};
  const compObj = adj.objetivo_comp || {};
  const cambios = adj.cambios_list || [];

  const cambiosHtml = cambios.length
    ? `<table><thead><tr><th>Elemento</th><th>De</th><th>A</th></tr></thead>
        <tbody>${cambios.map((c) => `<tr><td>${esc(c.elemento)}</td><td>${_histFmtNum(c.de)}</td><td>${_histFmtNum(c.a)}</td></tr>`).join("")}</tbody>
      </table>`
    : `<p class="sutil">Sin cambios de composición registrados en este ajuste.</p>`;

  const compRowsHtml = histElements.map((el) => `<tr>
      <td>${esc(el)}</td><td>${_histFmtNum(compIni[el] ?? 0)}</td><td>${_histFmtNum(compEst[el] ?? 0)}</td><td>${_histFmtNum(compObj[el] ?? 0)}</td>
    </tr>`).join("");

  abrirModal(`
    <h2>Editar ajuste</h2>
    <p class="sutil">Fecha: ${esc(adj.fecha || "")} · Objetivo: ${esc(adj.objetivo || "")}</p>

    <h3 style="margin-top:14px;">Cambios de composición</h3>
    ${cambiosHtml}

    <h3 style="margin-top:14px;">Composición (%) — Inicial / Estimado / Objetivo</h3>
    <div style="max-height:220px;overflow-y:auto;">
      <table><thead><tr><th>Elemento</th><th>Inicial</th><th>Estimado</th><th>Objetivo</th></tr></thead>
        <tbody>${compRowsHtml}</tbody>
      </table>
    </div>

    <h3 style="margin-top:14px;">Materiales (kg)</h3>
    <table><thead><tr><th>Material</th><th style="width:120px">kg</th></tr></thead>
      <tbody>${names.map((n) => `<tr>
        <td>${esc(n)}</td><td><input type="number" step="0.001" min="0" data-mat="${esc(n)}" value="${_histFmtNum(mats[n], 3)}" ${histCanEdit ? "" : "disabled"}></td>
      </tr>`).join("") || '<tr><td colspan="2" class="sutil">Este ajuste no tiene materiales cargados.</td></tr>'}</tbody>
    </table>
    <p id="hist-ea-error" class="error"></p>
    <div class="botones" style="margin-top:10px;">
      <button type="button" id="hist-ea-cancel">${histCanEdit ? "Cancelar" : "Cerrar"}</button>
      ${histCanEdit ? '<button type="button" id="hist-ea-save" class="primario">Guardar cambios</button>' : ""}
    </div>`, true);
  document.getElementById("hist-ea-cancel").onclick = cerrarModal;
  if (!histCanEdit) return;
  document.getElementById("hist-ea-save").onclick = async () => {
    const materiales = {};
    document.querySelectorAll("[data-mat]").forEach((inp) => {
      materiales[inp.dataset.mat] = _histParseNum(inp.value, 0);
    });
    const errEl = document.getElementById("hist-ea-error");
    try {
      const res = await Ajuste.apiFetch(`/api/historicos/sessions/${sessionIdx}/adjustments/${adjIdx}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ materiales }),
      });
      await _histLoadDetail(sessionIdx);
      cerrarModal();
      avisar(`Guardado. Masa estimada: ${_histFmtNum(res.estimado.mass, 3)} kg · CE: ${_histFmtNum(res.ce_estimado)}`);
    } catch (ex) {
      errEl.textContent = `Error: ${ex.detail?.detail?.message || ex.detail?.detail?.error || ex.message}`;
    }
  };
}

// ---------- Editar colada ----------

function _histOpenEditColadaModal() {
  if (typeof histActiveTab !== "number") return;
  const tabInfo = histOpenTabs.find((t) => t.idx === histActiveTab);
  const activeIdx = histActiveTab;
  abrirModal(`
    <h2>Editar colada</h2>
    <div class="campos"><label>Colada (formato: ID /YY - MATERIAL)
      <input id="hist-ec-colada" type="text" value="${esc((tabInfo && tabInfo.colada) || "")}"></label></div>
    <p id="hist-ec-error" class="error"></p>
    <div class="botones" style="margin-top:10px;">
      <button type="button" id="hist-ec-cancel">Cancelar</button>
      <button type="button" id="hist-ec-save" class="primario">Guardar</button>
    </div>`);
  document.getElementById("hist-ec-cancel").onclick = cerrarModal;
  document.getElementById("hist-ec-save").onclick = async () => {
    const errEl = document.getElementById("hist-ec-error");
    try {
      await Ajuste.apiFetch(`/api/historicos/sessions/${activeIdx}`, {
        method: "PUT", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ colada: document.getElementById("hist-ec-colada").value }),
      });
      await _histLoadDetail(activeIdx);
      cerrarModal();
    } catch (ex) {
      errEl.textContent = ex.detail?.detail?.message || ex.detail?.detail?.error || ex.message;
    }
  };
}

// ---------- Generar informe de calidad ----------
// Depende de /api/calidad/*, todavía no portado -- el try/catch de abajo ya maneja ese caso (muestra el
// error de red tal cual), no hace falta nada especial hasta que se porte ese módulo.

async function _histOpenQualityReportModal() {
  if (typeof histActiveTab !== "number") return;
  const sessionIdx = histActiveTab;
  let info;
  try {
    info = await Ajuste.apiFetch(`/api/calidad/material-options?session_idx=${sessionIdx}`);
  } catch (ex) {
    alert(`No se pudo generar el informe de calidad: ${ex.detail?.detail?.error || ex.message}`);
    return;
  }
  if (!info.materials.length) {
    alert("No hay materiales disponibles para generar un informe de calidad de esta colada.");
    return;
  }
  const defaultSet = new Set(info.default_materials || []);
  abrirModal(`
    <h2>Generar informe de calidad</h2>
    <p>Base ${esc(info.base_display || info.base)}${info.family ? ` — ${esc(info.family)}` : ""}</p>
    <p class="sutil">${esc(info.lote)}</p>
    <p class="sutil">Seleccioná los materiales a generar:</p>
    <div class="pick-list">${info.materials.map((m) => `<label><input type="checkbox" value="${esc(m)}" ${defaultSet.has(m) ? "checked" : ""}> Material ${esc(m)}</label>`).join("")}</div>
    <p id="hist-qr-error" class="error"></p>
    <div class="botones" style="margin-top:10px;">
      <button type="button" id="hist-qr-cancel">Cancelar</button>
      <button type="button" id="hist-qr-accept" class="primario">Generar</button>
    </div>`);
  document.getElementById("hist-qr-cancel").onclick = cerrarModal;
  document.getElementById("hist-qr-accept").onclick = async () => {
    const materials = [...document.querySelectorAll(".pick-list input[type=checkbox]:checked")].map((c) => c.value);
    const errEl = document.getElementById("hist-qr-error");
    if (!materials.length) {
      errEl.textContent = "Seleccioná al menos un material.";
      return;
    }
    try {
      const res = await Ajuste.apiFetch("/api/calidad/generate-from-session", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_idx: sessionIdx, materials }),
      });
      cerrarModal();
      avisar(`Se generaron/actualizaron ${res.updated} informe(s) de calidad. Revisalos en la pestaña Calidad.`);
    } catch (ex) {
      errEl.textContent = ex.detail?.detail?.error || ex.message;
    }
  };
}

// ---------- Vista ----------

VISTAS.historicos = async () => {
  $("#vista").innerHTML = `
    <div class="encabezado"><h2>Históricos</h2></div>
    <div class="tarjeta">
      <div id="hist-outer-tabs" class="hist-outer-tabs"></div>

      <!-- Pestaña fija "Lista", no se puede cerrar -->
      <div id="hist-panel-list">
        <div class="toolbar" style="flex-wrap:wrap;gap:8px;margin-bottom:10px;">
          <input id="hist-search" type="text" placeholder="Buscar colada u objetivo (ej: 91, 91:95, 91L5)" style="flex:1;min-width:220px;">
          <span id="hist-search-help" style="cursor:help;" class="sutil">ⓘ</span>
          <button type="button" id="hist-btn-refresh">Refrescar</button>
          <button type="button" id="hist-btn-export-json">Exportar JSON</button>
        </div>
        <p class="sutil">Tocá una colada para abrirla en una pestaña nueva.</p>
        <div class="hist-table-wrap">
          <table>
            <thead><tr><th>ID</th><th>Objetivo</th><th>Guardado</th><th>Inicio</th><th>Crisol</th><th># ajustes</th></tr></thead>
            <tbody id="hist-rows"></tbody>
          </table>
        </div>
      </div>

      <!-- Pestaña de detalle: una por colada abierta (se reusa este mismo panel, redibujado cada vez que se
           cambia de pestaña de sesión) -->
      <div id="hist-panel-detail" style="display:none;">
        <div class="toolbar" style="flex-wrap:wrap;gap:8px;">
          <h3 id="hist-detail-colada" style="margin:0;"></h3>
          <button type="button" id="hist-btn-edit-colada">Editar colada</button>
          <button type="button" id="hist-btn-toggle-sinterizado">Marcar/Desmarcar sinterizado</button>
          <button type="button" id="hist-btn-quality-report">Generar informe de calidad</button>
          <button type="button" id="hist-btn-trazabilidad" title="Quién cargó y modificó esta colada">Trazabilidad</button>
          <button type="button" id="hist-btn-delete-session" class="peligro">Eliminar sesión</button>
        </div>
        <pre id="hist-detail-summary" class="hist-summary"></pre>

        <div id="hist-detail-tabs" class="hist-detail-tabs">
          <button type="button" class="hist-detail-tab active" data-tab="ajustes">Ajustes</button>
          <button type="button" class="hist-detail-tab" data-tab="calculos">Cálculos</button>
          <button type="button" class="hist-detail-tab" data-tab="carbono">Carbono</button>
          <button type="button" class="hist-detail-tab" data-tab="spectro">Spectro</button>
          <button type="button" class="hist-detail-tab" data-tab="cucharas">Cucharas</button>
          <button type="button" class="hist-detail-tab" data-tab="ensayos">Ensayos</button>
        </div>

        <div id="hist-tab-ajustes" class="hist-detail-panel">
          <div class="hist-table-wrap">
            <table>
              <thead><tr><th>Fecha</th><th>%</th><th>CE est.</th><th>Resumen</th><th>Editar</th><th>CSV</th><th>Eliminar</th></tr></thead>
              <tbody id="hist-adj-rows"></tbody>
            </table>
          </div>
        </div>

        <div id="hist-tab-calculos" class="hist-detail-panel" style="display:none;">
          <p class="sutil">Cálculos hechos con el botón "Calcular" -- no llegaron a aplicarse.</p>
          <div class="hist-table-wrap">
            <table>
              <thead><tr><th>Fecha</th><th>%</th><th>CE est.</th><th>Resumen</th></tr></thead>
              <tbody id="hist-calc-rows"></tbody>
            </table>
          </div>
        </div>

        <div id="hist-tab-carbono" class="hist-detail-panel" style="display:none;">
          <p class="sutil">Lecturas de Carbono/Silicio del Carbomax automático.</p>
          <div class="hist-table-wrap">
            <table>
              <thead><tr><th>Fecha</th><th>Fuente</th><th>C</th><th>Si</th><th>CE</th></tr></thead>
              <tbody id="hist-carbon-rows"></tbody>
            </table>
          </div>
        </div>

        <div id="hist-tab-spectro" class="hist-detail-panel" style="display:none;">
          <p class="sutil">Resultados del espectrómetro LMX06 capturados durante esta colada.</p>
          <div class="hist-table-wrap">
            <table>
              <thead><tr><th>Fecha</th><th>Origen</th><th>Elementos</th></tr></thead>
              <tbody id="hist-spectro-rows"></tbody>
            </table>
          </div>
        </div>

        <div id="hist-tab-cucharas" class="hist-detail-panel" style="display:none;">
          <button type="button" id="hist-btn-edit-cucharas" style="margin-bottom:8px;" disabled>Editar…</button>
          <pre id="hist-cucharas-summary" class="hist-summary"></pre>
          <div class="hist-cucharas-cols">
            <div class="hist-table-wrap">
              <table><thead><tr><th>Material</th><th>Cantidad</th></tr></thead><tbody id="hist-cucharas-rows"></tbody></table>
            </div>
            <div class="hist-table-wrap">
              <table><thead><tr><th>Material</th><th>Hora</th></tr></thead><tbody id="hist-cucharas-events"></tbody></table>
            </div>
          </div>
        </div>

        <div id="hist-tab-ensayos" class="hist-detail-panel" style="display:none;">
          <p class="sutil">Ensayos reales cargados en Calidad para esta colada (informe por material).</p>
          <div class="hist-table-wrap">
            <table>
              <thead><tr><th>Material</th><th>Tracción real Lab (kg/mm²)</th><th>Estiramiento real</th><th>Tensión real lím prop (kg/mm²)</th><th>Mg disuelto (%)</th></tr></thead>
              <tbody id="hist-ensayos-rows"></tbody>
            </table>
          </div>
        </div>
      </div>
    </div>`;

  $("#hist-search-help").title = ColadaSearch.COLADA_SEARCH_TOOLTIP;
  $("#hist-search").addEventListener("input", _histRenderList);
  $("#hist-btn-refresh").addEventListener("click", () => {
    if (typeof histActiveTab === "number") _histLoadDetail(histActiveTab); else _histLoadSessions();
  });
  $("#hist-btn-export-json").addEventListener("click", () => window.open("/api/historicos/export.json", "_blank"));
  $("#hist-btn-edit-colada").addEventListener("click", _histOpenEditColadaModal);
  $("#hist-btn-quality-report").addEventListener("click", _histOpenQualityReportModal);
  $("#hist-btn-toggle-sinterizado").addEventListener("click", async () => {
    if (typeof histActiveTab !== "number") return;
    try {
      await Ajuste.apiFetch(`/api/historicos/sessions/${histActiveTab}/toggle-sinterizado`, { method: "POST" });
      avisar("Actualizado. El contador de crisol se reinicia desde esta colada si quedó marcada.");
      await _histLoadDetail(histActiveTab);
    } catch (ex) {
      avisar(`Error: ${ex.message}`, true);
    }
  });
  $("#hist-btn-trazabilidad").addEventListener("click", () => {
    const colada = ($("#hist-detail-colada").textContent || "").replace(/^Colada\s*/i, "").trim();
    Ajuste.verTrazabilidad(colada);
  });
  $("#hist-btn-delete-session").addEventListener("click", async () => {
    if (typeof histActiveTab !== "number") return;
    const motivo = Ajuste.pedirMotivo("¿Eliminar la sesión de esta pestaña? (Su contenido queda guardado en Trazabilidad.)");
    if (motivo === null) return;
    try {
      const idx = histActiveTab;
      await Ajuste.apiFetch(`/api/historicos/sessions/${idx}`, { method: "DELETE", headers: Ajuste.headersMotivo(motivo) });
      _histCloseSessionTab(idx);
    } catch (ex) {
      avisar(`Error: ${ex.message}`, true);
    }
  });
  $("#hist-detail-tabs").querySelectorAll(".hist-detail-tab").forEach((btn) => {
    btn.addEventListener("click", () => _histSwitchDetailTab(btn.dataset.tab));
  });

  Ajuste.waitForApproval(async (status) => {
    histCanEdit = status.role === "editor" || status.dev_skip_approval;
    if (!histCanEdit) avisar("Solo lectura (rol viewer).");
    const meta = await Ajuste.apiFetch("/api/meta");
    histElements = meta.elements || [];
    histOpenTabs = [];
    histActiveTab = "list";
    _histRenderOuterTabs();
    await _histLoadSessions();
  });
};
