// kiosk.js — SPA "Pie de Horno" que corre la Raspberry Pi en el piso de planta. Puerto de
// frontend/js/kiosk.js de ajuste_comp_web, página STANDALONE (no pasa por el shell del núcleo -- corre a
// pantalla completa en una Raspberry táctil, ver rutas/kiosk.py). Carga comun.js antes que este archivo
// (mismo truco que cualquier otra pantalla: Ajuste.apiFetch/waitForApproval/wsConnect), sin import/export.
const CLOCK_REFRESH_MS = 60000;
const DATA_REFRESH_MS = 60000;
// Si no hay actividad tactil/mouse por 2hs, se tapa la pantalla con un reloj grande (pantalla de
// "protector" para el kiosko Raspberry) — ver idleClockState/checkIdleClock.
const IDLE_CLOCK_AFTER_MS = 2 * 60 * 60 * 1000;
// ?kiosk=raspi activa estilos/comportamiento especificos para la Raspberry Pi que corre esto en modo
// kiosko fijo (controlada por SSH desde Pie de Horno, ver raspberry_ssh.py) — distinto de un
// celular/tablet cualquiera.
const RASPI_KIOSK = new URLSearchParams(window.location.search).get("kiosk") === "raspi";

document.documentElement.classList.toggle("raspi-kiosk", RASPI_KIOSK);

const nodes = {
  statusPill: document.getElementById("status-pill"),
  reloadAppBtn: document.getElementById("reload-app-btn"),
  keyboardToggleBtn: document.getElementById("keyboard-toggle-btn"),
  keyboardFocusInput: document.getElementById("keyboard-focus-input"),
  updatedAt: document.getElementById("updated-at"),
  colada: document.getElementById("colada-actual"),
  materialObjetivo: document.getElementById("material-objetivo"),
  horaActual: document.getElementById("hora-actual"),
  materialesBody: document.getElementById("materiales-body"),
  materialesEmpty: document.getElementById("materiales-empty"),
  carbomaxRecentBody: document.getElementById("carbomax-recent-body"),
  carbomaxRecentEmpty: document.getElementById("carbomax-recent-empty"),
  ajusteStatus: document.getElementById("ajuste-status"),
  ajusteEditorActions: document.getElementById("ajuste-editor-actions"),
  ajusteSaveActions: document.getElementById("ajuste-save-actions"),
  ajusteSaveBtn: document.getElementById("ajuste-save-btn"),
  compActualBody: document.getElementById("comp-actual-body"),
  compActualEmpty: document.getElementById("comp-actual-empty"),
  compEstimadaBody: document.getElementById("comp-estimada-body"),
  compEstimadaEmpty: document.getElementById("comp-estimada-empty"),
  ceActualBanner: document.getElementById("ce-actual-banner"),
  ceActualValue: document.getElementById("ce-actual-value"),
  ceEstimadaBanner: document.getElementById("ce-estimada-banner"),
  ceEstimadaValue: document.getElementById("ce-estimada-value"),
  cucharasColada: document.getElementById("cucharas-colada"),
  cucharasMaterial: document.getElementById("cucharas-material"),
  cucharasHora: document.getElementById("cucharas-hora"),
  cucharasBody: document.getElementById("cucharas-body"),
  cucharasEmpty: document.getElementById("cucharas-empty"),
  cucharasSavedWarning: document.getElementById("cucharas-saved-warning"),
  cucharasStatus: document.getElementById("cucharas-status"),
  cucharasEditorActions: document.getElementById("cucharas-editor-actions"),
  cucharasUndoBtn: document.getElementById("cucharas-undo-btn"),
  cucharasStartBtn: document.getElementById("cucharas-start-btn"),
  cucharasSaveBtn: document.getElementById("cucharas-save-btn"),
  totalCucharas: document.getElementById("total-cucharas"),
  statsTotalCucharas: document.getElementById("stats-total-cucharas"),
  statsDuration: document.getElementById("stats-duration"),
  statsFirst: document.getElementById("stats-first"),
  statsLast: document.getElementById("stats-last"),
  cucharasStatsBody: document.getElementById("cucharas-stats-body"),
  cucharasStatsEmpty: document.getElementById("cucharas-stats-empty"),
  idleClockOverlay: document.getElementById("idle-clock-overlay"),
  idleClockTime: document.getElementById("idle-clock-time"),
};

const cucharasState = {
  colada: "", materialObjetivo: "", counts: {}, saving: false, canEdit: false, family: "",
  initiated: false, initiatedColada: "", initiatedMaterial: "",
};

const ajusteState = {
  rows: [], saving: false, canEdit: false, confirmedAt: "", generalPct: 100, dirty: false, colada: "",
};

const deviceState = { role: "viewer" };

const idleClockState = { lastActivityAt: Date.now(), visible: false };

// ---------- reloj / idle ----------

function setText(node, value) { node.textContent = value || ""; }

function formatColadaWithMaterial(colada, materialObjetivo) {
  const coladaText = String(colada || "").trim().replace(/\s*\/\s*/g, "/");
  const materialText = String(materialObjetivo || "").trim();
  if (!coladaText) return "";
  return materialText ? `${coladaText}-${materialText}` : coladaText;
}

function currentClockLabel() {
  return new Date().toLocaleTimeString("es-AR", { hour: "2-digit", minute: "2-digit" });
}

function refreshClock() {
  const label = currentClockLabel();
  setText(nodes.horaActual, label);
  setText(nodes.cucharasHora, label);
}

function refreshIdleClock() {
  if (nodes.idleClockTime) nodes.idleClockTime.textContent = currentClockLabel();
}

function showIdleClock() {
  if (!nodes.idleClockOverlay || idleClockState.visible) return;
  idleClockState.visible = true;
  refreshIdleClock();
  nodes.idleClockOverlay.classList.add("is-visible");
  nodes.idleClockOverlay.setAttribute("aria-hidden", "false");
}

function hideIdleClock() {
  if (!nodes.idleClockOverlay || !idleClockState.visible) return;
  idleClockState.visible = false;
  nodes.idleClockOverlay.classList.remove("is-visible");
  nodes.idleClockOverlay.setAttribute("aria-hidden", "true");
}

function noteUserActivity() {
  idleClockState.lastActivityAt = Date.now();
  hideIdleClock();
}

function checkIdleClock() {
  refreshIdleClock();
  if (!idleClockState.visible && Date.now() - idleClockState.lastActivityAt >= IDLE_CLOCK_AFTER_MS) showIdleClock();
}

function setupIdleClock() {
  ["pointerdown", "keydown", "touchstart", "wheel"].forEach((eventName) => {
    window.addEventListener(eventName, noteUserActivity, { passive: true });
  });
  if (nodes.idleClockOverlay) nodes.idleClockOverlay.addEventListener("click", noteUserActivity);
  window.setInterval(checkIdleClock, 1000);
}

// ---------- teclado tactil ----------

function setKeyboardButtonState(active) {
  nodes.keyboardToggleBtn.classList.toggle("is-active", Boolean(active));
  nodes.keyboardToggleBtn.textContent = active ? "Cerrar teclado" : "Teclado";
}

// Boton "Teclado": en el kiosko tactil (sin teclado fisico) no siempre hay un input visible enfocable
// para invocar el teclado virtual del SO; nodes.keyboardFocusInput es un input oculto dedicado solo a
// este truco.
function toggleKeyboard() {
  const active = document.activeElement;
  const editableActive = active && (
    active === nodes.keyboardFocusInput || active.tagName === "INPUT" ||
    active.tagName === "TEXTAREA" || active.isContentEditable
  );
  if (editableActive) {
    active.blur();
    setKeyboardButtonState(false);
    return;
  }
  nodes.keyboardFocusInput.value = "";
  nodes.keyboardFocusInput.focus({ preventScroll: true });
  setKeyboardButtonState(true);
}

// ---------- formato ----------

// Los operarios de planta miden materiales a ojo/balanza en fracciones (ej. "2 y 3/4 kg"), no en
// decimales — por eso los kg calculados se muestran como fraccion mixta en vez de "2.75".
function toFraction(n) {
  if (typeof n !== "number" || Number.isNaN(n)) return "—";
  if (n === 0) return "0";
  const sign = n < 0 ? "-" : "";
  const abs = Math.abs(n);
  const whole = Math.floor(abs);
  const frac = abs - whole;
  if (frac < 1e-9) return sign + whole;
  let best = { num: 1, den: 1, err: Infinity };
  for (let d = 1; d <= 16; d++) {
    const num = Math.round(frac * d);
    const err = Math.abs(frac - num / d);
    if (err < best.err) best = { num, den: d, err };
    if (err < 1e-9) break;
  }
  const fracStr = best.den === 1 ? String(best.num) : `${best.num}/${best.den}`;
  if (whole === 0) return sign + fracStr;
  return `${sign}${whole} ${fracStr}`;
}

function formatValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) return "";
  return value.toLocaleString("es-AR", { minimumFractionDigits: 0, maximumFractionDigits: 6 });
}

function formatTimestamp(value) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return String(value);
  return date.toLocaleString("es-AR", { day: "2-digit", month: "2-digit", hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function renderCE(bannerNode, valueNode, formula, value) {
  const numericValue = Number(value);
  const hasValue = Number.isFinite(numericValue);
  bannerNode.classList.toggle("is-visible", hasValue);
  if (!hasValue) { valueNode.textContent = ""; return; }
  const suffix = formula ? ` (${formula})` : "";
  valueNode.textContent = `${formatValue(numericValue)}${suffix}`;
}

function renderRows(tbody, emptyNode, rows, columns) {
  tbody.innerHTML = "";
  const safeRows = Array.isArray(rows) ? rows : [];
  emptyNode.classList.toggle("is-visible", safeRows.length === 0);
  if (!safeRows.length) return;
  for (const row of safeRows) {
    const tr = document.createElement("tr");
    for (const column of columns) {
      const td = document.createElement("td");
      const rawValue = row?.[column.key];
      td.textContent = column.format ? column.format(rawValue) : (rawValue ?? "");
      tr.appendChild(td);
    }
    tbody.appendChild(tr);
  }
}

function normalizePctValue(value, fallback = 100) {
  const numeric = Math.round(Number(value));
  if (!Number.isFinite(numeric)) return fallback;
  return Math.max(0, Math.min(100, numeric));
}

// ---------- Ajuste: materiales / % horno ----------

function setAjusteStatus(message, variant = "") {
  setText(nodes.ajusteStatus, message);
  nodes.ajusteStatus.className = "toolbar-status";
  if (variant) nodes.ajusteStatus.classList.add(variant);
}

// "porcentaje_horno" es que fraccion del kg calculado por Ajuste va efectivamente a ESTE horno (cuando la
// carga de un material se reparte entre varios hornos); kg_horno = kg * pct/100 es lo que realmente
// termina pesando/cargando el operario.
function syncAjusteState(ajuste) {
  const rows = Array.isArray(ajuste?.materiales) ? ajuste.materiales : [];
  ajusteState.rows = rows.map((row) => {
    const kg = Number(row?.kg || 0);
    if (!Number.isFinite(kg) || kg <= 0) return null;
    const pct = normalizePctValue(row?.porcentaje_horno, 100);
    return { nombre: row?.nombre || "", kg, porcentaje_horno: pct, kg_horno: Number(row?.kg_horno ?? (kg * pct / 100)) };
  }).filter(Boolean);
  ajusteState.colada = ajuste?.colada || "";
  ajusteState.confirmedAt = ajuste?.confirmado_at || "";
  if (ajusteState.rows.length) {
    const allSame = ajusteState.rows.every((row) => row.porcentaje_horno === ajusteState.rows[0].porcentaje_horno);
    ajusteState.generalPct = allSame ? ajusteState.rows[0].porcentaje_horno : normalizePctValue(ajuste?.porcentaje_general_horno, 100);
  } else {
    ajusteState.generalPct = normalizePctValue(ajuste?.porcentaje_general_horno, 100);
  }
  ajusteState.dirty = false;
}

function applyAjustePctAll(pct) {
  const safePct = normalizePctValue(pct, 100);
  ajusteState.generalPct = safePct;
  ajusteState.rows = ajusteState.rows.map((row) => ({ ...row, porcentaje_horno: safePct, kg_horno: row.kg * safePct / 100 }));
  ajusteState.dirty = true;
  renderAjusteMaterials();
}

function applyAjustePctRow(name, pct) {
  const safePct = normalizePctValue(pct, 100);
  ajusteState.rows = ajusteState.rows.map((row) => (
    row.nombre === name ? { ...row, porcentaje_horno: safePct, kg_horno: row.kg * safePct / 100 } : row
  ));
  const rows = ajusteState.rows;
  ajusteState.generalPct = rows.length && rows.every((row) => row.porcentaje_horno === rows[0].porcentaje_horno) ? rows[0].porcentaje_horno : 100;
  ajusteState.dirty = true;
  renderAjusteMaterials();
}

function renderAjusteMaterials() {
  nodes.materialesBody.innerHTML = "";
  const rows = Array.isArray(ajusteState.rows) ? ajusteState.rows : [];
  const allSame = rows.length > 0 && rows.every((row) => normalizePctValue(row.porcentaje_horno, 100) === normalizePctValue(rows[0].porcentaje_horno, 100));
  const activeGlobalPct = allSame ? normalizePctValue(rows[0].porcentaje_horno, 100) : null;
  document.querySelectorAll("[data-ajuste-all-pct]").forEach((button) => {
    const pct = normalizePctValue(button.dataset.ajusteAllPct, 100);
    button.classList.toggle("is-active", activeGlobalPct !== null && pct === activeGlobalPct);
  });
  nodes.materialesEmpty.classList.toggle("is-visible", rows.length === 0);
  nodes.ajusteEditorActions.classList.toggle("is-visible", Boolean(ajusteState.canEdit && rows.length));
  nodes.ajusteSaveActions.classList.toggle("is-visible", Boolean(ajusteState.canEdit && rows.length));
  nodes.ajusteSaveBtn.disabled = !ajusteState.canEdit || ajusteState.saving || rows.length === 0;

  for (const row of rows) {
    const tr = document.createElement("tr");
    const tdMaterial = document.createElement("td");
    tdMaterial.textContent = row.nombre || "";
    tr.appendChild(tdMaterial);

    const tdPlan = document.createElement("td");
    tdPlan.textContent = formatValue(row.kg) || "";
    tdPlan.className = "plan-kg-cell";
    tr.appendChild(tdPlan);

    const tdPct = document.createElement("td");
    tdPct.textContent = `${normalizePctValue(row.porcentaje_horno, 100)}%`;
    tdPct.className = "pct-cell";
    tr.appendChild(tdPct);

    const tdKgHorno = document.createElement("td");
    tdKgHorno.textContent = formatValue(Number(row.kg_horno || 0)) || "";
    tdKgHorno.className = "confirmed-kg-cell";
    tr.appendChild(tdKgHorno);

    const tdActions = document.createElement("td");
    tdActions.className = "actions-cell";
    if (ajusteState.canEdit) {
      const group = document.createElement("div");
      group.className = "percent-group";
      [25, 50, 75, 100].forEach((pct) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.className = "percent-button";
        if (normalizePctValue(row.porcentaje_horno, 100) === pct) btn.classList.add("is-active");
        btn.textContent = `${pct}%`;
        btn.addEventListener("click", () => applyAjustePctRow(row.nombre, pct));
        group.appendChild(btn);
      });
      tdActions.appendChild(group);
    }
    tr.appendChild(tdActions);
    nodes.materialesBody.appendChild(tr);
  }

  if (ajusteState.saving) setAjusteStatus("Guardando confirmacion del horno...", "is-dirty");
  else if (ajusteState.dirty) setAjusteStatus("Cambios pendientes de guardar.", "is-dirty");
  else if (!ajusteState.canEdit && rows.length) setAjusteStatus("Solo lectura");
  else if (ajusteState.confirmedAt) setAjusteStatus(`Confirmado: ${ajusteState.confirmedAt}`, "is-saved");
  else if (rows.length) setAjusteStatus("Pendiente de confirmar cuanto se tiro al horno.", "is-dirty");
  else setAjusteStatus("");
}

async function saveAjusteConfirmation() {
  if (!ajusteState.canEdit || ajusteState.saving || !ajusteState.rows.length) return;
  ajusteState.saving = true;
  renderAjusteMaterials();
  try {
    const data = await Ajuste.apiFetch("/api/kiosk/materiales", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        general_pct: ajusteState.generalPct,
        rows: ajusteState.rows.map((row) => ({ nombre: row.nombre, porcentaje_horno: normalizePctValue(row.porcentaje_horno, 100) })),
      }),
    });
    ajusteState.saving = false;
    ajusteState.dirty = false;
    renderSnapshot(data);
  } catch (error) {
    ajusteState.saving = false;
    if (error.status === 403) { ajusteState.canEdit = false; renderAjusteMaterials(); return; }
    renderAjusteMaterials();
    setAjusteStatus("No se pudo guardar la confirmacion.", "is-dirty");
  }
}

// ---------- Cucharas ----------

function cucharasTotal() {
  return Object.values(cucharasState.counts).reduce((acc, value) => acc + Math.max(0, Number(value) || 0), 0);
}

function setCucharasStatus(message, variant = "") {
  setText(nodes.cucharasStatus, message);
  nodes.cucharasStatus.className = "toolbar-status";
  if (variant) nodes.cucharasStatus.classList.add(variant);
}

const sessionBanner = {
  el: document.getElementById("cucharas-session-banner"),
  textEl: document.getElementById("cucharas-session-banner-text"),
  closeBtn: document.getElementById("cucharas-session-banner-close"),
  timer: null,
};
sessionBanner.closeBtn?.addEventListener("click", () => hideSessionBanner());

function hideSessionBanner() {
  if (!sessionBanner.el) return;
  sessionBanner.el.setAttribute("hidden", "");
  if (sessionBanner.timer) { clearTimeout(sessionBanner.timer); sessionBanner.timer = null; }
}

function showSessionBanner(colada, material) {
  if (!sessionBanner.el || !sessionBanner.textEl) return;
  const label = [String(colada || "").trim(), String(material || "").trim()].filter(Boolean).join("  ·  ");
  sessionBanner.textEl.textContent = label ? `Nueva sesión: ${label}` : "Sesión reiniciada";
  sessionBanner.el.removeAttribute("hidden");
  sessionBanner.el.style.animation = "none";
  sessionBanner.el.offsetHeight;
  sessionBanner.el.style.animation = "";
  if (sessionBanner.timer) clearTimeout(sessionBanner.timer);
  sessionBanner.timer = setTimeout(hideSessionBanner, 8000);
}

// Evita que un snapshot del servidor (llegado por el refresh periodico o por el WebSocket de OTRO
// dispositivo conectado) le pise al operario los contadores que esta tocando en este mismo momento antes
// de guardarlos.
function syncCucharasState(payload, fromDirectSave = false) {
  const newColada = payload?.colada || "";
  const newMaterial = payload?.material_objetivo || "";
  const prevColada = cucharasState.colada;
  const prevMaterial = cucharasState.materialObjetivo;
  const firstLoad = !prevColada && !prevMaterial;
  const sessionChanged = !firstLoad && (newColada || newMaterial) && (newColada !== prevColada || newMaterial !== prevMaterial);
  const hasActiveCounts = cucharasState.initiated && Object.values(cucharasState.counts).some((v) => v > 0);

  if (hasActiveCounts && !fromDirectSave) {
    if (sessionChanged) showSessionBanner(newColada, newMaterial);
    return;
  }
  cucharasState.colada = newColada;
  cucharasState.materialObjetivo = newMaterial;
  cucharasState.counts = {};
  for (const row of payload?.rows || []) cucharasState.counts[row.material_final] = Math.max(0, Number(row.cantidad) || 0);
  if (sessionChanged) showSessionBanner(newColada, newMaterial);
}

function renderCucharas(payload) {
  const displayColada = cucharasState.colada || payload?.colada || "";
  const displayMaterial = cucharasState.materialObjetivo || payload?.material_objetivo || "";
  setText(nodes.cucharasColada, formatColadaWithMaterial(displayColada, displayMaterial));
  setText(nodes.cucharasMaterial, displayMaterial);
  refreshClock();
  nodes.cucharasSavedWarning.classList.remove("is-visible");
  nodes.cucharasSavedWarning.textContent = "";

  if (!cucharasState.saving || cucharasState.materialObjetivo !== (payload?.material_objetivo || "")) {
    syncCucharasState(payload);
  }

  cucharasState.family = payload?.family || "";
  nodes.cucharasBody.innerHTML = "";
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  nodes.cucharasEmpty.classList.toggle("is-visible", rows.length === 0);
  const isNodular = cucharasState.family === "Nodular";

  for (const row of rows) {
    const material = row.material_final;
    const count = Math.max(0, Number(cucharasState.counts[material] ?? row.cantidad ?? 0));
    cucharasState.counts[material] = count;

    const col = document.createElement("div");
    col.className = "cuchara-col";

    const nameEl = document.createElement("span");
    nameEl.className = "cuchara-col-name";
    nameEl.textContent = material;
    col.appendChild(nameEl);

    const countEl = document.createElement("span");
    countEl.className = "cuchara-col-count";
    countEl.textContent = count > 0 ? formatValue(count) : "0";
    col.appendChild(countEl);

    if (cucharasState.canEdit) {
      const plusBtn = document.createElement("button");
      plusBtn.type = "button";
      plusBtn.textContent = "+";
      plusBtn.className = "qty-button qty-button-plus";
      plusBtn.addEventListener("click", () => changeCuchara(material, 1));
      col.appendChild(plusBtn);

      if (isNodular) {
        // Familia Nodular: suelen cargarse de a pares — atajo "+2".
        const plus2Btn = document.createElement("button");
        plus2Btn.type = "button";
        plus2Btn.textContent = "+2";
        plus2Btn.className = "qty-button qty-button-plus qty-button-plus2";
        plus2Btn.addEventListener("click", () => changeCuchara(material, 2));
        col.appendChild(plus2Btn);
      }

      const minusBtn = document.createElement("button");
      minusBtn.type = "button";
      minusBtn.className = "qty-button qty-button-minus";
      minusBtn.textContent = "−";
      minusBtn.addEventListener("click", () => changeCuchara(material, -1));
      col.appendChild(minusBtn);
    }

    nodes.cucharasBody.appendChild(col);
  }

  nodes.totalCucharas.textContent = formatValue(cucharasTotal()) || "0";
  nodes.cucharasEditorActions.classList.toggle("is-visible", Boolean(cucharasState.canEdit));
  nodes.cucharasStartBtn.disabled = !cucharasState.canEdit || cucharasState.saving || rows.length === 0;
  nodes.cucharasSaveBtn.disabled = !cucharasState.canEdit || cucharasState.saving || rows.length === 0;
  if (cucharasState.saving) setCucharasStatus("Guardando...", "is-dirty");
  else if (!cucharasState.canEdit && rows.length) setCucharasStatus("Solo lectura");
  else if (payload?.updated_at) setCucharasStatus(`Guardado: ${payload.updated_at}`, "is-saved");
  else setCucharasStatus("");
}

async function runCucharasAction(action) {
  if (!cucharasState.canEdit || cucharasState.saving) return;
  if (action === "start") {
    const sameColada = Boolean(ajusteState.colada && cucharasState.colada && ajusteState.colada === cucharasState.colada);
    if (!sameColada && cucharasTotal() > 0) {
      if (!window.confirm("Iniciar borra el conteo actual de esta colada. Continuar?")) return;
    }
    saveUndoSnapshot();
  }
  cucharasState.saving = true;
  setCucharasStatus(action === "start" ? "Iniciando..." : "Guardando...", "is-dirty");
  try {
    const data = await Ajuste.apiFetch("/api/kiosk/cucharas", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action }),
    });
    if (action === "start") {
      cucharasState.initiated = true;
      cucharasState.initiatedColada = data.cucharas?.colada || "";
      cucharasState.initiatedMaterial = data.cucharas?.material_objetivo || "";
      cucharasState.counts = {};
      showUndoBtn();
    }
    syncCucharasState(data.cucharas || {});
    cucharasState.saving = false;
    renderCucharas(data.cucharas || {});
    renderCucharasStats(data.cucharas?.statistics || {});
    setCucharasStatus(action === "start" ? "Conteo iniciado." : "Guardado.", "is-saved");
  } catch (error) {
    cucharasState.saving = false;
    if (error.status === 403) { cucharasState.canEdit = false; setCucharasStatus("Solo lectura"); loadSnapshot(); return; }
    if (error.status === 409) {
      renderCucharas({
        colada: cucharasState.colada, material_objetivo: cucharasState.materialObjetivo,
        rows: Object.keys(cucharasState.counts).map((key) => ({ material_final: key, cantidad: cucharasState.counts[key] })),
        updated_at: null,
      });
      setCucharasStatus("Primero inicia la sesion en Ajuste.", "is-dirty");
      return;
    }
    renderCucharas({
      colada: cucharasState.colada, material_objetivo: cucharasState.materialObjetivo,
      rows: Object.keys(cucharasState.counts).map((key) => ({ material_final: key, cantidad: cucharasState.counts[key] })),
      updated_at: null,
    });
    setCucharasStatus("No se pudo completar.", "is-dirty");
  } finally {
    cucharasState.saving = false;
  }
}

function renderCucharasStats(stats) {
  const safeStats = stats || {};
  const rows = Array.isArray(safeStats.rows) ? safeStats.rows : [];
  setText(nodes.statsTotalCucharas, formatValue(Number(safeStats.total_cucharas || 0)) || "0");
  setText(nodes.statsDuration, safeStats.duration_label || "");
  setText(nodes.statsFirst, formatTimestamp(safeStats.first_saved_at));
  setText(nodes.statsLast, formatTimestamp(safeStats.last_saved_at));

  nodes.cucharasStatsBody.innerHTML = "";
  const visibleRows = rows.filter((row) => Number(row?.total || 0) > 0);
  nodes.cucharasStatsEmpty.classList.toggle("is-visible", visibleRows.length === 0);
  for (const row of visibleRows) {
    const tr = document.createElement("tr");
    const values = [row.material_final || "", formatValue(Number(row.total || 0)) || "0", formatTimestamp(row.first_saved_at), formatTimestamp(row.last_saved_at), row.duration_label || ""];
    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    nodes.cucharasStatsBody.appendChild(tr);
  }
}

function changeCuchara(material, delta) {
  if (!cucharasState.canEdit) return;
  if (!cucharasState.initiated) {
    cucharasState.initiated = true;
    cucharasState.initiatedColada = cucharasState.colada;
    cucharasState.initiatedMaterial = cucharasState.materialObjetivo;
  }
  hideUndoBtn();
  const current = Math.max(0, Number(cucharasState.counts[material] || 0));
  cucharasState.counts[material] = Math.max(0, current + delta);
  renderCucharas({
    colada: cucharasState.colada, material_objetivo: cucharasState.materialObjetivo,
    rows: Object.keys(cucharasState.counts).map((key) => ({ material_final: key, cantidad: cucharasState.counts[key] })),
    updated_at: null,
  });
  saveCucharaDelta(material, delta);
}

async function saveCucharaDelta(material, delta) {
  const targetMaterial = cucharasState.initiatedMaterial || cucharasState.materialObjetivo;
  const targetColada = cucharasState.initiatedColada || cucharasState.colada;
  if (!cucharasState.canEdit || cucharasState.saving || !targetMaterial) return;
  cucharasState.saving = true;
  renderCucharas({
    colada: targetColada, material_objetivo: targetMaterial,
    rows: Object.keys(cucharasState.counts).map((key) => ({ material_final: key, cantidad: cucharasState.counts[key] })),
    updated_at: null,
  });
  try {
    const data = await Ajuste.apiFetch("/api/kiosk/cucharas", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ material_objetivo: targetMaterial, colada_override: targetColada, material_final: material, delta }),
    });
    syncCucharasState(data.cucharas || {}, true);
    cucharasState.saving = false;
    renderCucharas(data.cucharas || {});
  } catch (error) {
    cucharasState.saving = false;
    if (error.status === 403) { cucharasState.canEdit = false; setCucharasStatus("Solo lectura"); loadSnapshot(); return; }
    renderCucharas({
      colada: cucharasState.colada, material_objetivo: cucharasState.materialObjetivo,
      rows: Object.keys(cucharasState.counts).map((key) => ({ material_final: key, cantidad: cucharasState.counts[key] })),
      updated_at: null,
    });
    setCucharasStatus("No se pudo guardar.", "is-dirty");
  } finally {
    cucharasState.saving = false;
  }
}

// ---------- Botón Volver (undo iniciar) ----------

const undoState = { available: false, colada: "", material: "", counts: {}, timer: null, TIMEOUT_MS: 120_000 };

function saveUndoSnapshot() {
  undoState.colada = cucharasState.colada;
  undoState.material = cucharasState.materialObjetivo;
  undoState.counts = { ...cucharasState.counts };
  undoState.available = Object.values(undoState.counts).some((v) => v > 0);
}

function showUndoBtn() {
  if (!nodes.cucharasUndoBtn || !undoState.available) return;
  nodes.cucharasUndoBtn.removeAttribute("hidden");
  if (undoState.timer) clearTimeout(undoState.timer);
  undoState.timer = setTimeout(hideUndoBtn, undoState.TIMEOUT_MS);
}

function hideUndoBtn() {
  if (!nodes.cucharasUndoBtn) return;
  nodes.cucharasUndoBtn.setAttribute("hidden", "");
  undoState.available = false;
  if (undoState.timer) { clearTimeout(undoState.timer); undoState.timer = null; }
}

async function restorePreviousSession() {
  if (!undoState.available || cucharasState.saving) return;
  if (!window.confirm(`Volver a:\n  Colada: ${undoState.colada || "—"}\n  Material: ${undoState.material || "—"}\n\n¿Confirmar?`)) return;
  hideUndoBtn();
  cucharasState.saving = true;
  setCucharasStatus("Restaurando...", "is-dirty");
  try {
    const data = await Ajuste.apiFetch("/api/kiosk/cucharas", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action: "restore_previous", previous_colada: undoState.colada, previous_material: undoState.material, previous_counts: undoState.counts }),
    });
    cucharasState.initiated = true;
    cucharasState.initiatedColada = undoState.colada;
    cucharasState.initiatedMaterial = undoState.material;
    cucharasState.counts = { ...undoState.counts };
    syncCucharasState(data.cucharas || {}, true);
    cucharasState.saving = false;
    renderCucharas(data.cucharas || {});
    setCucharasStatus("Colada anterior restaurada.", "is-saved");
  } catch (err) {
    cucharasState.saving = false;
    setCucharasStatus("No se pudo restaurar.", "is-dirty");
  }
}

// ---------- Snapshot / render general ----------

function renderSnapshot(data) {
  const ajuste = data?.ajuste || {};
  const cucharas = data?.cucharas || {};
  const permissions = data?.permissions || {};
  deviceState.role = permissions.role || deviceState.role || "viewer";
  cucharasState.canEdit = Boolean(permissions.can_edit_cucharas);
  ajusteState.canEdit = Boolean(permissions.can_edit_ajuste);
  const compActual = (ajuste.composicion_actual || []).filter((row) => Math.abs(Number(row?.valor || 0)) > 1e-12);
  const compEstimada = (ajuste.composicion_estimada || []).filter((row) => Math.abs(Number(row?.valor || 0)) > 1e-12);
  setText(nodes.updatedAt, data?.updated_at || "");
  setText(nodes.colada, formatColadaWithMaterial(ajuste.colada || "", ajuste.material_objetivo || ""));
  setText(nodes.materialObjetivo, ajuste.material_objetivo || "");
  refreshClock();
  renderCE(nodes.ceActualBanner, nodes.ceActualValue, ajuste.ce_formula, ajuste.ce_actual);
  renderCE(nodes.ceEstimadaBanner, nodes.ceEstimadaValue, ajuste.ce_formula, ajuste.ce_estimado);
  if (!ajusteState.saving) syncAjusteState(ajuste);
  renderAjusteMaterials();

  renderRows(nodes.compActualBody, nodes.compActualEmpty, compActual, [{ key: "elemento" }, { key: "valor", format: formatValue }]);
  renderRows(nodes.compEstimadaBody, nodes.compEstimadaEmpty, compEstimada, [{ key: "elemento" }, { key: "valor", format: formatValue }]);

  renderCucharas({ ...cucharas, colada: cucharas.colada || ajuste.colada || "", material_objetivo: cucharas.material_objetivo || ajuste.material_objetivo || "" });
  renderCucharasStats(cucharas.statistics || {});
  renderCarbomaxRecent(data?.carbomax_recent || []);
}

// ---------- Lista Carbomax — últimos análisis ----------
// Contraparte web de la lista "Carbomax — últimos análisis" de ajuste.js (mismo dato, misma idea que el
// cuadro Espectro): el loop de Carbomax automático agrega cada análisis nuevo a carbomax_recent_records
// sin bloquear nada. "Usar" pega al MISMO endpoint que ajuste.js (/api/ajuste/carbomax-auto/use-record),
// no hay un mecanismo aparte -- y requiere que el objetivo ya esté elegido desde la pantalla de Ajuste (el
// kiosk no tiene forma de elegirlo).
let carbomaxUsingIndex = null;

function renderCarbomaxRecent(records) {
  if (!nodes.carbomaxRecentBody) return;
  const rows = Array.isArray(records) ? records : [];
  const canEdit = deviceState.role === "editor";
  nodes.carbomaxRecentEmpty.classList.toggle("is-visible", rows.length === 0);
  nodes.carbomaxRecentBody.innerHTML = "";

  rows.forEach((r, i) => {
    const tr = document.createElement("tr");
    [r.ts, r.colada, formatValue(Number(r.carbon || 0)), formatValue(Number(r.silicon || 0)), r.source].forEach((val) => {
      const td = document.createElement("td");
      td.textContent = val || "";
      tr.appendChild(td);
    });
    const tdActions = document.createElement("td");
    if (canEdit) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.className = "action-button secondary";
      btn.textContent = "Usar";
      btn.disabled = carbomaxUsingIndex !== null;
      btn.addEventListener("click", () => useCarbomaxRecord(i));
      tdActions.appendChild(btn);
    }
    tr.appendChild(tdActions);
    nodes.carbomaxRecentBody.appendChild(tr);
  });
}

async function useCarbomaxRecord(index) {
  if (carbomaxUsingIndex !== null) return;
  carbomaxUsingIndex = index;
  try {
    await Ajuste.apiFetch("/api/ajuste/carbomax-auto/use-record", {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ index }),
    });
  } catch (_) {
    // silencioso — el proximo snapshot refleja el estado real de todos modos
  } finally {
    carbomaxUsingIndex = null;
    loadSnapshot();
  }
}

// ---------- carga de snapshot / status ----------

function setStatus(ok, label) {
  nodes.statusPill.textContent = label;
  nodes.statusPill.classList.toggle("is-ok", ok);
}

let connectionFailures = 0;

async function loadSnapshot() {
  try {
    const data = await Ajuste.apiFetch("/api/kiosk/snapshot");
    connectionFailures = 0;
    renderSnapshot(data);
    setStatus(true, "Host conectado");
  } catch (error) {
    connectionFailures += 1;
    setStatus(false, connectionFailures >= 3 ? "Sin conectar" : "Reconectando...");
  }
}

// ---------- tabs ----------

function setupTabs() {
  const tabs = Array.from(document.querySelectorAll("[data-tab-target]"));
  const panels = Array.from(document.querySelectorAll(".panel"));
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tabTarget;
      tabs.forEach((node) => node.classList.toggle("is-active", node === tab));
      panels.forEach((panel) => panel.classList.toggle("is-active", panel.id === target));
      if (target === "inoc-panel") {
        if (!inocData.length) loadInoculaciones();
        else { _inocPopulateBaseFilter(); renderInocList(); if (_inocDetailIdx >= 0) showInocDetail(_inocDetailIdx); }
      }
    });
  });
}

function setupCucharasTabs() {
  const tabs = Array.from(document.querySelectorAll("[data-cucharas-tab-target]"));
  const panels = Array.from(document.querySelectorAll(".cucharas-subpanel"));
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.cucharasTabTarget;
      tabs.forEach((node) => node.classList.toggle("is-active", node === tab));
      panels.forEach((panel) => panel.classList.toggle("is-active", panel.id === target));
    });
  });
}

// ---------- Inoculaciones ----------

const MOMENTO_LABEL = { horno: "Horno", cuchara_transp: "C. transp.", cuchara_colar: "C. colar" };

let inocData = [];
let _inocDetailIdx = -1;
let _inocDetailBase = null;
let _inocCucharasConfig = {};  // { [base]: { [material_final]: bool } } — cache por base

function _inocActiveFilter() {
  return document.getElementById("inoc-base-filter")?.value || "";
}

function _inocPopulateBaseFilter() {
  const sel = document.getElementById("inoc-base-filter");
  if (!sel) return;
  const prev = sel.value;
  const allBases = new Set();
  for (const item of inocData) {
    for (const b of (item.bases || [])) allBases.add(b);
    for (const b of Object.keys(item.procedimiento_por_base || {})) allBases.add(b);
  }
  sel.innerHTML = `<option value="">Todas las bases</option>` + [...allBases].sort().map((b) => `<option value="${b}">${b}</option>`).join("");
  const autoBase = cucharasState.materialObjetivo || "";
  sel.value = (prev && allBases.has(prev)) ? prev : (allBases.has(autoBase) ? autoBase : "");
}

function _inocItemBases(item) {
  return [...new Set([...(item.bases || []), ...Object.keys(item.procedimiento_por_base || {})])].sort();
}

function _inocProtocol(item, base) {
  const pb = item.procedimiento_por_base || {};
  if (base && pb[base]) return pb[base];
  return item.procedimiento || [];
}

async function _loadInocCucharasConfig(base) {
  if (!base || base in _inocCucharasConfig) return;
  try {
    const data = await Ajuste.apiFetch(`/api/kiosk/cucharas-base-config?base=${encodeURIComponent(base)}`);
    _inocCucharasConfig[base] = data.config || {};
  } catch (_) {
    _inocCucharasConfig[base] = {};
  }
}

function renderInocList() {
  const list = document.getElementById("inoc-list");
  const empty = document.getElementById("inoc-list-empty");
  const filter = _inocActiveFilter();
  list.innerHTML = "";
  const entries = [];
  for (let idx = 0; idx < inocData.length; idx++) {
    const item = inocData[idx];
    const bases = _inocItemBases(item);
    if (!filter) {
      if (bases.length <= 1) {
        const base = bases[0] || null;
        if (_inocProtocol(item, base).length > 0) entries.push({ idx, base, label: base ? `${item.nombre} (${base})` : item.nombre });
      } else {
        for (const base of bases) {
          if (_inocProtocol(item, base).length > 0) entries.push({ idx, base, label: `${item.nombre} (${base})` });
        }
      }
    } else {
      const inBases = (item.bases || []).includes(filter);
      const inPorBase = filter in (item.procedimiento_por_base || {});
      if ((inBases || inPorBase) && _inocProtocol(item, filter).length > 0) entries.push({ idx, base: filter, label: item.nombre });
    }
  }
  if (!entries.length) { list.appendChild(empty); return; }
  for (const entry of entries) {
    const li = document.createElement("li");
    li.className = "inoc-item";
    li.dataset.inocIdx = entry.idx;
    li.dataset.inocBase = entry.base || "";
    li.addEventListener("click", () => showInocDetail(entry.idx, entry.base));

    const nameSpan = document.createElement("span");
    nameSpan.textContent = entry.label;
    li.appendChild(nameSpan);

    if (filter) {
      const matNombre = inocData[entry.idx]?.nombre || entry.label;
      const cfg = _inocCucharasConfig[filter] || {};
      const isActive = cfg[matNombre] !== false;

      const chk = document.createElement("input");
      chk.type = "checkbox";
      chk.className = "inoc-cucharas-chk";
      chk.checked = isActive;
      chk.title = "Mostrar en conteo de cucharas";
      chk.addEventListener("click", (e) => e.stopPropagation());
      chk.addEventListener("change", async () => {
        const active = chk.checked;
        if (!_inocCucharasConfig[filter]) _inocCucharasConfig[filter] = {};
        _inocCucharasConfig[filter][matNombre] = active;
        try {
          await Ajuste.apiFetch("/api/kiosk/cucharas-base-config", {
            method: "POST", headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ base: filter, material_final: matNombre, active }),
          });
        } catch (_) {
          chk.checked = !active;
          _inocCucharasConfig[filter][matNombre] = !active;
        }
      });
      li.appendChild(chk);
    }

    list.appendChild(li);
  }
  _syncInocListSelection();
}

function _syncInocListSelection() {
  document.querySelectorAll(".inoc-item").forEach((el) => {
    const match = Number(el.dataset.inocIdx) === _inocDetailIdx && (el.dataset.inocBase || null) === _inocDetailBase;
    el.classList.toggle("is-active", match);
  });
}

document.getElementById("inoc-base-filter")?.addEventListener("change", async () => {
  const filter = _inocActiveFilter();
  await _loadInocCucharasConfig(filter);
  renderInocList();
  if (_inocDetailIdx >= 0) {
    const filter = _inocActiveFilter();
    const item = inocData[_inocDetailIdx];
    const stillVisible = !filter || (filter in (item?.procedimiento_por_base || {}));
    if (!stillVisible) {
      _inocDetailIdx = -1;
      document.getElementById("inoc-detail-title").textContent = "—";
      document.getElementById("inoc-detail-body").innerHTML = "";
      document.getElementById("inoc-detail-empty").hidden = false;
      document.getElementById("inoc-active-base-badge")?.setAttribute("hidden", "");
    } else {
      showInocDetail(_inocDetailIdx, _inocDetailBase);
    }
  }
});

async function loadInoculaciones() {
  try {
    const data = await Ajuste.apiFetch("/api/kiosk/inoculaciones");
    inocData = data.inoculaciones || [];
    _inocPopulateBaseFilter();
    await _loadInocCucharasConfig(_inocActiveFilter());
    renderInocList();
    const activeMat = cucharasState.materialObjetivo || "";
    if (activeMat) {
      const matchIdx = inocData.findIndex((it) => it.nombre === activeMat);
      if (matchIdx >= 0) showInocDetail(matchIdx);
    }
  } catch (_) {
    inocData = [];
  }
}

function showInocDetail(idx, base) {
  const item = inocData[idx];
  if (!item) return;
  _inocDetailIdx = idx;
  const filter = _inocActiveFilter();
  const autoBase = cucharasState.materialObjetivo || "";
  const porBases = Object.keys(item.procedimiento_por_base || {});
  _inocDetailBase = base !== undefined ? (base || null) : (filter && porBases.includes(filter)) ? filter : (porBases.includes(autoBase)) ? autoBase : null;

  _syncInocListSelection();

  document.getElementById("inoc-detail-title").textContent = item.nombre + (_inocDetailBase ? ` (${_inocDetailBase})` : "");
  const badge = document.getElementById("inoc-active-base-badge");
  if (badge) {
    if (_inocDetailBase) { badge.textContent = _inocDetailBase; badge.removeAttribute("hidden"); }
    else badge.setAttribute("hidden", "");
  }

  const proc = _inocProtocol(item, _inocDetailBase);
  const body = document.getElementById("inoc-detail-body");
  const emptyEl = document.getElementById("inoc-detail-empty");
  const theadRow = document.querySelector("#inoc-detail-table thead tr");
  body.innerHTML = "";
  if (!proc.length) {
    emptyEl.hidden = false;
    theadRow.innerHTML = "<th>Etapa</th><th>Inoculante</th><th>Total g</th>";
    return;
  }
  emptyEl.hidden = true;

  const sorted = [...proc].sort((a, b) => (a.momento_idx ?? 999) - (b.momento_idx ?? 999));
  const momentoLabelMap = {};
  for (const e of sorted) momentoLabelMap[e.momento || "horno"] = e.momento_label || MOMENTO_LABEL[e.momento] || e.momento || "horno";

  const unitsPresent = [];
  for (const e of sorted) { const u = e.unidad || "cucharín"; if (!unitsPresent.includes(u)) unitsPresent.push(u); }

  let theadHtml = "<th>Etapa</th><th>Inoculante</th>";
  for (const u of unitsPresent) theadHtml += `<th class="inoc-col-compact">${u}</th>`;
  for (const u of unitsPresent) { theadHtml += `<th class="inoc-col-detail inoc-group-start">cant.</th>`; theadHtml += `<th class="inoc-col-detail">g/${u}</th>`; }
  theadHtml += "<th>Total g</th>";
  theadRow.innerHTML = theadHtml;

  let i = 0;
  let groupIndex = 0;
  while (i < sorted.length) {
    const mom = sorted[i].momento || "horno";
    let count = 0;
    while (i + count < sorted.length && (sorted[i + count].momento || "horno") === mom) count++;
    for (let j = 0; j < count; j++) {
      const e = sorted[i + j];
      const eUnit = e.unidad || "cucharín";
      const tr = document.createElement("tr");
      tr.classList.add(groupIndex % 2 === 0 ? "inoc-etapa-even" : "inoc-etapa-odd");
      const hasColor = e.color && /^#[0-9a-fA-F]{6}$/.test(e.color);
      if (j === 0) {
        tr.classList.add("inoc-etapa-first-row");
        const td = document.createElement("td");
        td.rowSpan = count;
        td.textContent = momentoLabelMap[mom] || mom;
        td.className = "inoc-etapa-cell";
        tr.appendChild(td);
      }
      let rowHtml = `<td>${e.nombre}</td>`;
      for (const u of unitsPresent) rowHtml += `<td class="inoc-col-compact">${eUnit === u ? toFraction(e.cant) : "—"}</td>`;
      for (const u of unitsPresent) {
        const match = eUnit === u;
        rowHtml += `<td class="inoc-col-detail inoc-group-start">${match ? toFraction(e.cant) : "—"}</td>`;
        rowHtml += `<td class="inoc-col-detail">${match && e.gramos ? e.gramos + " g" : "—"}</td>`;
      }
      rowHtml += `<td>${e.total != null ? e.total + " g" : "—"}</td>`;
      const rest = document.createElement("template");
      rest.innerHTML = rowHtml;
      tr.append(...rest.content.childNodes);
      if (hasColor) {
        for (const td of tr.querySelectorAll("td:not(.inoc-etapa-cell)")) { td.style.backgroundColor = e.color; td.style.color = contrastColor(e.color); }
      }
      body.appendChild(tr);
    }
    i += count;
    groupIndex++;
  }
}

// Luminancia relativa (formula WCAG) del color de fondo para elegir texto negro o blanco legible encima
// (color_inoculacion configurado en Catálogo por material).
function contrastColor(hex) {
  const c = hex.replace("#", "");
  const r = parseInt(c.substring(0, 2), 16) / 255;
  const g = parseInt(c.substring(2, 4), 16) / 255;
  const b = parseInt(c.substring(4, 6), 16) / 255;
  const toLinear = (x) => (x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4));
  const L = 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
  return L > 0.179 ? "#1a1a1a" : "#ffffff";
}

document.getElementById("inoc-mode-btn")?.addEventListener("click", () => {
  const table = document.getElementById("inoc-detail-table");
  const nowCompact = table.classList.toggle("is-compact");
  document.getElementById("inoc-mode-btn").textContent = nowCompact ? "Ver detalle" : "Vista rápida";
});

// ---------- arranque ----------

setupTabs();
setupCucharasTabs();
nodes.reloadAppBtn.addEventListener("click", () => window.location.reload());
// "Salir" vuelve al shell del núcleo (pestaña Ajuste) -- en la app vieja era /ajuste.html, acá no existe
// esa página suelta, el shell vive en "/" y las pestañas son hashes.
document.getElementById("exit-kiosk-btn").addEventListener("click", () => { window.location.href = "/#ajuste"; });
nodes.keyboardToggleBtn.addEventListener("click", toggleKeyboard);
document.addEventListener("focusin", (event) => {
  const target = event.target;
  const editable = target && (target === nodes.keyboardFocusInput || target.tagName === "INPUT" || target.tagName === "TEXTAREA" || target.isContentEditable);
  setKeyboardButtonState(editable);
});
document.addEventListener("focusout", () => {
  window.setTimeout(() => {
    const active = document.activeElement;
    const editable = active && (active === nodes.keyboardFocusInput || active.tagName === "INPUT" || active.tagName === "TEXTAREA" || active.isContentEditable);
    setKeyboardButtonState(editable);
  }, 0);
});
nodes.cucharasUndoBtn?.addEventListener("click", () => restorePreviousSession());
nodes.cucharasStartBtn.addEventListener("click", () => runCucharasAction("start"));
nodes.cucharasSaveBtn.addEventListener("click", () => runCucharasAction("save"));
nodes.ajusteSaveBtn.addEventListener("click", () => saveAjusteConfirmation());
document.querySelectorAll("[data-ajuste-all-pct]").forEach((button) => {
  button.addEventListener("click", () => applyAjustePctAll(button.dataset.ajusteAllPct));
});

async function start() {
  refreshClock();
  setupIdleClock();
  Ajuste.waitForApproval(async (status) => {
    deviceState.role = status.role || "viewer";
    await loadSnapshot();
    Ajuste.wsConnect("kiosk", () => loadSnapshot());
    Ajuste.wsConnect("furnace", () => loadSnapshot());
    Ajuste.wsConnect("ajuste", () => loadSnapshot());
    window.setInterval(loadSnapshot, DATA_REFRESH_MS);
  }, { soloDispositivo: true }); // el kiosco al pie del horno es la única pantalla que exige dispositivo aprobado
  window.setInterval(refreshClock, CLOCK_REFRESH_MS);
}

start();
