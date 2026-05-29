const DATA_REFRESH_MS = 60000;
const CLOCK_REFRESH_MS = 60000;
const DEVICE_STATUS_REFRESH_MS = 5000;
const IDLE_CLOCK_AFTER_MS = 2 * 60 * 60 * 1000;
const DEVICE_ID_KEY = "pie_horno_device_id";
const DEVICE_NAME_KEY = "pie_horno_device_name";
const DEVICE_NAME_CONFIRMED_KEY = "pie_horno_device_name_confirmed";
const RASPI_KIOSK = new URLSearchParams(window.location.search).get("kiosk") === "raspi";

document.documentElement.classList.toggle("raspi-kiosk", RASPI_KIOSK);

const nodes = {
  statusPill: document.getElementById("status-pill"),
  approvalBanner: document.getElementById("approval-banner"),
  reloadAppBtn: document.getElementById("reload-app-btn"),
  keyboardToggleBtn: document.getElementById("keyboard-toggle-btn"),
  keyboardFocusInput: document.getElementById("keyboard-focus-input"),
  deviceNameModal: document.getElementById("device-name-modal"),
  deviceNameForm: document.getElementById("device-name-form"),
  deviceNameInput: document.getElementById("device-name-input"),
  updatedAt: document.getElementById("updated-at"),
  colada: document.getElementById("colada-actual"),
  materialObjetivo: document.getElementById("material-objetivo"),
  horaActual: document.getElementById("hora-actual"),
  materialesBody: document.getElementById("materiales-body"),
  materialesEmpty: document.getElementById("materiales-empty"),
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
  colada: "",
  materialObjetivo: "",
  counts: {},
  saving: false,
  canEdit: false,
};

const ajusteState = {
  rows: [],
  saving: false,
  canEdit: false,
  confirmedAt: "",
  generalPct: 100,
  dirty: false,
};

const deviceState = {
  id: "",
  name: "",
  status: "unknown",
  role: "viewer",
  registering: false,
};

const idleClockState = {
  lastActivityAt: Date.now(),
  visible: false,
};

let liveEvents = null;
let liveEventsRetry = null;
let connectionFailures = 0;

function makeDeviceId() {
  if (window.crypto && typeof window.crypto.randomUUID === "function") {
    return window.crypto.randomUUID();
  }
  return `pie-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
}

function defaultDeviceName(id) {
  const platform = navigator.platform || (navigator.userAgent.includes("Linux") ? "Linux" : "Navegador");
  return `Pie de Horno ${platform} ${String(id || "").slice(-6)}`;
}

function cleanDeviceName(value) {
  return String(value || "")
    .replace(/[<>]/g, "")
    .replace(/\s+/g, " ")
    .trim()
    .slice(0, 80);
}

function ensureDeviceIdentity() {
  let id = window.localStorage.getItem(DEVICE_ID_KEY) || "";
  if (!/^[A-Za-z0-9_.:-]{8,80}$/.test(id)) {
    id = makeDeviceId();
    window.localStorage.setItem(DEVICE_ID_KEY, id);
  }

  let name = cleanDeviceName(window.localStorage.getItem(DEVICE_NAME_KEY) || "");
  if (!name.trim()) {
    name = defaultDeviceName(id);
    window.localStorage.setItem(DEVICE_NAME_KEY, name);
  }

  deviceState.id = id;
  deviceState.name = cleanDeviceName(name) || defaultDeviceName(id);
}

function hasConfirmedDeviceName() {
  return window.localStorage.getItem(DEVICE_NAME_CONFIRMED_KEY) === "1";
}

function requestDeviceNameIfNeeded() {
  ensureDeviceIdentity();
  if (hasConfirmedDeviceName()) {
    return Promise.resolve(deviceState.name);
  }

  nodes.deviceNameInput.value = deviceState.name;
  nodes.deviceNameModal.classList.add("is-visible");
  nodes.deviceNameModal.setAttribute("aria-hidden", "false");
  window.setTimeout(() => {
    try {
      nodes.deviceNameInput.focus();
      nodes.deviceNameInput.select();
    } catch (error) {
      // Touch kiosks may not allow programmatic focus.
    }
  }, 50);

  return new Promise((resolve) => {
    const onSubmit = (event) => {
      event.preventDefault();
      const chosen = cleanDeviceName(nodes.deviceNameInput.value) || deviceState.name || defaultDeviceName(deviceState.id);
      window.localStorage.setItem(DEVICE_NAME_KEY, chosen);
      window.localStorage.setItem(DEVICE_NAME_CONFIRMED_KEY, "1");
      deviceState.name = chosen;
      nodes.deviceNameModal.classList.remove("is-visible");
      nodes.deviceNameModal.setAttribute("aria-hidden", "true");
      nodes.deviceNameForm.removeEventListener("submit", onSubmit);
      resolve(chosen);
    };
    nodes.deviceNameForm.addEventListener("submit", onSubmit);
  });
}

function setApprovalMessage(message, variant = "") {
  nodes.approvalBanner.textContent = message || "";
  nodes.approvalBanner.className = "approval-banner";
  if (message) {
    nodes.approvalBanner.classList.add("is-visible");
  }
  if (variant) {
    nodes.approvalBanner.classList.add(variant);
  }
}

function setKeyboardButtonState(active) {
  nodes.keyboardToggleBtn.classList.toggle("is-active", Boolean(active));
  nodes.keyboardToggleBtn.textContent = active ? "Cerrar teclado" : "Teclado";
}

function toggleKeyboard() {
  const active = document.activeElement;
  const editableActive = active && (
    active === nodes.keyboardFocusInput ||
    active === nodes.deviceNameInput ||
    active.tagName === "INPUT" ||
    active.tagName === "TEXTAREA" ||
    active.isContentEditable
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

function stopLiveEvents() {
  if (liveEventsRetry) {
    window.clearTimeout(liveEventsRetry);
    liveEventsRetry = null;
  }
  if (liveEvents) {
    liveEvents.close();
    liveEvents = null;
  }
}

function startLiveEvents() {
  if (liveEvents || deviceState.status !== "approved") {
    return;
  }
  if (liveEventsRetry) {
    window.clearTimeout(liveEventsRetry);
    liveEventsRetry = null;
  }

  const params = new URLSearchParams({
    device_id: deviceState.id,
    name: deviceState.name,
  });
  liveEvents = new EventSource(`/api/events?${params.toString()}`);
  liveEvents.addEventListener("refresh", () => {
    loadSnapshot();
  });
  liveEvents.onerror = () => {
    stopLiveEvents();
    liveEventsRetry = window.setTimeout(startLiveEvents, 3000);
  };
}

async function apiFetch(url, options = {}) {
  const headers = new Headers(options.headers || {});
  headers.set("X-Pie-Device-Id", deviceState.id);
  headers.set("X-Pie-Device-Name", deviceState.name);
  const response = await fetch(url, { ...options, headers, cache: "no-store" });
  return response;
}

async function registerDevice() {
  if (deviceState.registering) {
    return deviceState.status;
  }
  deviceState.registering = true;
  try {
    const response = await apiFetch("/api/device/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        device_id: deviceState.id,
        name: deviceState.name,
      }),
    });
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    deviceState.status = data.status || "pending";
    deviceState.role = data.role || "viewer";
    if (deviceState.status === "approved") {
      setStatus(true, "Dispositivo aprobado");
      setApprovalMessage("");
      startLiveEvents();
    } else if (deviceState.status === "revoked") {
      stopLiveEvents();
      setStatus(false, "pendiente de aprovar");
      setApprovalMessage("pendiente de aprovar", "is-revoked");
    } else {
      stopLiveEvents();
      setStatus(false, "pendiente de aprovar");
      setApprovalMessage("pendiente de aprovar");
    }
    return deviceState.status;
  } catch (error) {
    setStatus(false, "Sin conectar");
    return "unknown";
  } finally {
    deviceState.registering = false;
  }
}

function setText(node, value) {
  node.textContent = value || "";
}

function formatColadaWithMaterial(colada, materialObjetivo) {
  const coladaText = String(colada || "").trim().replace(/\s*\/\s*/g, "/");
  const materialText = String(materialObjetivo || "").trim();
  if (!coladaText) {
    return "";
  }
  return materialText ? `${coladaText}-${materialText}` : coladaText;
}

function currentClockLabel() {
  return new Date().toLocaleTimeString("es-AR", {
    hour: "2-digit",
    minute: "2-digit",
  });
}

function refreshClock() {
  const label = currentClockLabel();
  setText(nodes.horaActual, label);
  setText(nodes.cucharasHora, label);
}

function refreshIdleClock() {
  if (!nodes.idleClockTime) {
    return;
  }
  nodes.idleClockTime.textContent = currentClockLabel();
}

function showIdleClock() {
  if (!nodes.idleClockOverlay || idleClockState.visible) {
    return;
  }
  idleClockState.visible = true;
  refreshIdleClock();
  nodes.idleClockOverlay.classList.add("is-visible");
  nodes.idleClockOverlay.setAttribute("aria-hidden", "false");
}

function hideIdleClock() {
  if (!nodes.idleClockOverlay || !idleClockState.visible) {
    return;
  }
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
  if (!idleClockState.visible && Date.now() - idleClockState.lastActivityAt >= IDLE_CLOCK_AFTER_MS) {
    showIdleClock();
  }
}

function setupIdleClock() {
  ["pointerdown", "keydown", "touchstart", "wheel"].forEach((eventName) => {
    window.addEventListener(eventName, noteUserActivity, { passive: true });
  });
  if (nodes.idleClockOverlay) {
    nodes.idleClockOverlay.addEventListener("click", noteUserActivity);
  }
  window.setInterval(checkIdleClock, 1000);
}

function formatValue(value) {
  if (typeof value !== "number" || Number.isNaN(value)) {
    return "";
  }
  return value.toLocaleString("es-AR", {
    minimumFractionDigits: 0,
    maximumFractionDigits: 6,
  });
}

function formatTimestamp(value) {
  if (!value) {
    return "";
  }
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    return String(value);
  }
  return date.toLocaleString("es-AR", {
    day: "2-digit",
    month: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  });
}

function renderCE(bannerNode, valueNode, formula, value) {
  const numericValue = Number(value);
  const hasValue = Number.isFinite(numericValue);
  bannerNode.classList.toggle("is-visible", hasValue);
  if (!hasValue) {
    valueNode.textContent = "";
    return;
  }
  const suffix = formula ? ` (${formula})` : "";
  valueNode.textContent = `${formatValue(numericValue)}${suffix}`;
}

function renderRows(tbody, emptyNode, rows, columns) {
  tbody.innerHTML = "";
  const safeRows = Array.isArray(rows) ? rows : [];
  emptyNode.classList.toggle("is-visible", safeRows.length === 0);
  if (!safeRows.length) {
    return;
  }
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
  if (!Number.isFinite(numeric)) {
    return fallback;
  }
  return Math.max(0, Math.min(100, numeric));
}

function setAjusteStatus(message, variant = "") {
  setText(nodes.ajusteStatus, message);
  nodes.ajusteStatus.className = "toolbar-status";
  if (variant) {
    nodes.ajusteStatus.classList.add(variant);
  }
}

function syncAjusteState(ajuste) {
  const rows = Array.isArray(ajuste?.materiales) ? ajuste.materiales : [];
  ajusteState.rows = rows
    .map((row) => {
      const kg = Number(row?.kg || 0);
      if (!Number.isFinite(kg) || kg <= 0) {
        return null;
      }
      const pct = normalizePctValue(row?.porcentaje_horno, 100);
      return {
        nombre: row?.nombre || "",
        kg,
        porcentaje_horno: pct,
        kg_horno: Number(row?.kg_horno ?? (kg * pct / 100)),
      };
    })
    .filter(Boolean);
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
  ajusteState.rows = ajusteState.rows.map((row) => ({
    ...row,
    porcentaje_horno: safePct,
    kg_horno: row.kg * safePct / 100,
  }));
  ajusteState.dirty = true;
  renderAjusteMaterials();
}

function applyAjustePctRow(name, pct) {
  const safePct = normalizePctValue(pct, 100);
  ajusteState.rows = ajusteState.rows.map((row) => (
    row.nombre === name
      ? { ...row, porcentaje_horno: safePct, kg_horno: row.kg * safePct / 100 }
      : row
  ));
  const rows = ajusteState.rows;
  ajusteState.generalPct = rows.length && rows.every((row) => row.porcentaje_horno === rows[0].porcentaje_horno)
    ? rows[0].porcentaje_horno
    : 100;
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
        if (normalizePctValue(row.porcentaje_horno, 100) === pct) {
          btn.classList.add("is-active");
        }
        btn.textContent = `${pct}%`;
        btn.addEventListener("click", () => applyAjustePctRow(row.nombre, pct));
        group.appendChild(btn);
      });
      tdActions.appendChild(group);
    }
    tr.appendChild(tdActions);
    nodes.materialesBody.appendChild(tr);
  }

  if (ajusteState.saving) {
    setAjusteStatus("Guardando confirmacion del horno...", "is-dirty");
  } else if (ajusteState.dirty) {
    setAjusteStatus("Cambios pendientes de guardar.", "is-dirty");
  } else if (!ajusteState.canEdit && rows.length) {
    setAjusteStatus("Solo lectura");
  } else if (ajusteState.confirmedAt) {
    setAjusteStatus(`Confirmado: ${ajusteState.confirmedAt}`, "is-saved");
  } else if (rows.length) {
    setAjusteStatus("Pendiente de confirmar cuanto se tiro al horno.", "is-dirty");
  } else {
    setAjusteStatus("");
  }
}

function cucharasTotal() {
  return Object.values(cucharasState.counts).reduce((acc, value) => acc + Math.max(0, Number(value) || 0), 0);
}

function setCucharasStatus(message, variant = "") {
  setText(nodes.cucharasStatus, message);
  nodes.cucharasStatus.className = "toolbar-status";
  if (variant) {
    nodes.cucharasStatus.classList.add(variant);
  }
}

function renderCucharasWarning(payload) {
  nodes.cucharasSavedWarning.classList.remove("is-visible");
  nodes.cucharasSavedWarning.textContent = "";
}

function syncCucharasState(payload) {
  cucharasState.colada = payload?.colada || "";
  cucharasState.materialObjetivo = payload?.material_objetivo || "";
  cucharasState.counts = {};
  for (const row of payload?.rows || []) {
    cucharasState.counts[row.material_final] = Math.max(0, Number(row.cantidad) || 0);
  }
}

function renderCucharas(payload) {
  setText(nodes.cucharasColada, formatColadaWithMaterial(payload?.colada || "", payload?.material_objetivo || ""));
  setText(nodes.cucharasMaterial, payload?.material_objetivo || "");
  refreshClock();
  renderCucharasWarning(payload);

  if (!cucharasState.saving || cucharasState.materialObjetivo !== (payload?.material_objetivo || "")) {
    syncCucharasState(payload);
  }

  nodes.cucharasBody.innerHTML = "";
  const rows = Array.isArray(payload?.rows) ? payload.rows : [];
  nodes.cucharasEmpty.classList.toggle("is-visible", rows.length === 0);

  for (const row of rows) {
    const material = row.material_final;
    const count = Math.max(0, Number(cucharasState.counts[material] ?? row.cantidad ?? 0));
    cucharasState.counts[material] = count;

    const tr = document.createElement("tr");

    const tdMaterial = document.createElement("td");
    tdMaterial.textContent = material;
    tr.appendChild(tdMaterial);

    const tdCount = document.createElement("td");
    tdCount.textContent = formatValue(count);
    tdCount.className = "qty-cell";
    tr.appendChild(tdCount);

    const tdActions = document.createElement("td");
    tdActions.className = "actions-cell";

    if (cucharasState.canEdit) {
      const minusBtn = document.createElement("button");
      minusBtn.type = "button";
      minusBtn.className = "qty-button qty-button-minus";
      minusBtn.textContent = "-";
      minusBtn.addEventListener("click", () => changeCuchara(material, -1));

      const plusBtn = document.createElement("button");
      plusBtn.type = "button";
      plusBtn.textContent = "+";
      plusBtn.className = "qty-button qty-button-plus";
      plusBtn.addEventListener("click", () => changeCuchara(material, 1));

      tdActions.appendChild(minusBtn);
      tdActions.appendChild(plusBtn);
    }
    tr.appendChild(tdActions);
    nodes.cucharasBody.appendChild(tr);
  }

  nodes.totalCucharas.textContent = formatValue(cucharasTotal()) || "0";
  nodes.cucharasEditorActions.classList.toggle("is-visible", Boolean(cucharasState.canEdit));
  nodes.cucharasStartBtn.disabled = !cucharasState.canEdit || cucharasState.saving || rows.length === 0;
  nodes.cucharasSaveBtn.disabled = !cucharasState.canEdit || cucharasState.saving || rows.length === 0;
  if (cucharasState.saving) {
    setCucharasStatus("Guardando...", "is-dirty");
  } else if (!cucharasState.canEdit && rows.length) {
    setCucharasStatus("Solo lectura");
  } else if (payload?.updated_at) {
    setCucharasStatus(`Guardado: ${payload.updated_at}`, "is-saved");
  } else {
    setCucharasStatus("");
  }
}

async function runCucharasAction(action) {
  if (!cucharasState.canEdit || cucharasState.saving) {
    return;
  }
  if (action === "start" && cucharasTotal() > 0) {
    const ok = window.confirm("Iniciar borra el conteo actual de esta colada. Continuar?");
    if (!ok) {
      return;
    }
  }
  cucharasState.saving = true;
  setCucharasStatus(action === "start" ? "Iniciando..." : "Guardando...", "is-dirty");
  try {
    const response = await apiFetch("/api/cucharas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action }),
    });
    if (response.status === 403) {
      cucharasState.canEdit = false;
      setCucharasStatus("Solo lectura");
      loadSnapshot();
      return;
    }
    if (response.status === 409) {
      cucharasState.saving = false;
      renderCucharas({
        colada: cucharasState.colada,
        material_objetivo: cucharasState.materialObjetivo,
        rows: Object.keys(cucharasState.counts).map((key) => ({
          material_final: key,
          cantidad: cucharasState.counts[key],
        })),
        updated_at: null,
      });
      setCucharasStatus("Primero inicia la sesion en Ajuste.", "is-dirty");
      return;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    syncCucharasState(data.cucharas || {});
    cucharasState.saving = false;
    renderCucharas(data.cucharas || {});
    renderCucharasStats(data.cucharas?.statistics || {});
    setCucharasStatus(action === "start" ? "Conteo iniciado." : "Guardado.", "is-saved");
  } catch (error) {
    cucharasState.saving = false;
    renderCucharas({
      colada: cucharasState.colada,
      material_objetivo: cucharasState.materialObjetivo,
      rows: Object.keys(cucharasState.counts).map((key) => ({
        material_final: key,
        cantidad: cucharasState.counts[key],
      })),
      updated_at: null,
    });
    setCucharasStatus("No se pudo completar.", "is-dirty");
  } finally {
    cucharasState.saving = false;
  }
}

async function saveAjusteConfirmation() {
  if (!ajusteState.canEdit || ajusteState.saving || !ajusteState.rows.length) {
    return;
  }
  ajusteState.saving = true;
  renderAjusteMaterials();
  try {
    const response = await apiFetch("/api/pie-horno", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        action: "save_materiales",
        general_pct: ajusteState.generalPct,
        rows: ajusteState.rows.map((row) => ({
          nombre: row.nombre,
          porcentaje_horno: normalizePctValue(row.porcentaje_horno, 100),
        })),
      }),
    });
    if (response.status === 403) {
      ajusteState.canEdit = false;
      ajusteState.saving = false;
      renderAjusteMaterials();
      return;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    ajusteState.saving = false;
    ajusteState.dirty = false;
    renderSnapshot(data.payload || {});
  } catch (error) {
    ajusteState.saving = false;
    renderAjusteMaterials();
    setAjusteStatus("No se pudo guardar la confirmacion.", "is-dirty");
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
    const values = [
      row.material_final || "",
      formatValue(Number(row.total || 0)) || "0",
      formatTimestamp(row.first_saved_at),
      formatTimestamp(row.last_saved_at),
      row.duration_label || "",
    ];
    for (const value of values) {
      const td = document.createElement("td");
      td.textContent = value;
      tr.appendChild(td);
    }
    nodes.cucharasStatsBody.appendChild(tr);
  }
}

function changeCuchara(material, delta) {
  if (!cucharasState.canEdit) {
    return;
  }
  const current = Math.max(0, Number(cucharasState.counts[material] || 0));
  cucharasState.counts[material] = Math.max(0, current + delta);
  renderCucharas({
    colada: cucharasState.colada,
    material_objetivo: cucharasState.materialObjetivo,
    rows: Object.keys(cucharasState.counts).map((key) => ({
      material_final: key,
      cantidad: cucharasState.counts[key],
    })),
    updated_at: null,
  });
  saveCucharaDelta(material, delta);
}

async function saveCucharaDelta(material, delta) {
  if (!cucharasState.canEdit || cucharasState.saving || !cucharasState.materialObjetivo) {
    return;
  }
  cucharasState.saving = true;
  renderCucharas({
    colada: cucharasState.colada,
    material_objetivo: cucharasState.materialObjetivo,
    rows: Object.keys(cucharasState.counts).map((key) => ({
      material_final: key,
      cantidad: cucharasState.counts[key],
    })),
    updated_at: null,
  });
  try {
    const response = await apiFetch("/api/cucharas", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        material_objetivo: cucharasState.materialObjetivo,
        material_final: material,
        delta,
      }),
    });
    if (response.status === 403) {
      cucharasState.canEdit = false;
      setCucharasStatus("Solo lectura");
      loadSnapshot();
      return;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    syncCucharasState(data.cucharas || {});
    cucharasState.saving = false;
    renderCucharas(data.cucharas || {});
  } catch (error) {
    cucharasState.saving = false;
    renderCucharas({
      colada: cucharasState.colada,
      material_objetivo: cucharasState.materialObjetivo,
      rows: Object.keys(cucharasState.counts).map((key) => ({
        material_final: key,
        cantidad: cucharasState.counts[key],
      })),
      updated_at: null,
    });
    setCucharasStatus("No se pudo guardar.", "is-dirty");
  } finally {
    cucharasState.saving = false;
  }
}

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
  if (!ajusteState.saving) {
    syncAjusteState(ajuste);
  }
  renderAjusteMaterials();

  renderRows(nodes.compActualBody, nodes.compActualEmpty, compActual, [
    { key: "elemento" },
    { key: "valor", format: formatValue },
  ]);

  renderRows(nodes.compEstimadaBody, nodes.compEstimadaEmpty, compEstimada, [
    { key: "elemento" },
    { key: "valor", format: formatValue },
  ]);

  renderCucharas({
    ...cucharas,
    colada: cucharas.colada || ajuste.colada || "",
    material_objetivo: cucharas.material_objetivo || ajuste.material_objetivo || "",
  });
  renderCucharasStats(cucharas.statistics || {});
  renderCarbomaxPending(data?.carbomax_pending || null);
}

// ── Modal Carbomax pendiente ────────────────────────────────────────

const carbomaxModal = {
  overlay: document.getElementById("carbomax-modal-overlay"),
  sourceEl: document.getElementById("carbomax-modal-source"),
  cEl: document.getElementById("carbomax-modal-c"),
  siEl: document.getElementById("carbomax-modal-si"),
  objetivoRow: document.getElementById("carbomax-objetivo-row"),
  objetivoSelect: document.getElementById("carbomax-objetivo-select"),
  coladaInput: document.getElementById("carbomax-colada-input"),
  confirmBtn: document.getElementById("carbomax-confirm-btn"),
  rejectBtn: document.getElementById("carbomax-reject-btn"),
  visible: false,
  sending: false,
};

function renderCarbomaxPending(pending) {
  if (!carbomaxModal.overlay) return;
  if (!pending) {
    hideCarbomaxModal();
    return;
  }
  // Solo mostrar a dispositivos editor
  if (deviceState.role !== "editor") {
    hideCarbomaxModal();
    return;
  }
  const c  = Number(pending.carbon  || 0);
  const si = Number(pending.silicon || 0);
  if (c <= 0 && si <= 0) {
    hideCarbomaxModal();
    return;
  }
  carbomaxModal.cEl.textContent  = c.toFixed(2);
  carbomaxModal.siEl.textContent = si.toFixed(2);
  const src = [pending.source, pending.analysis_ts].filter(Boolean).join("  —  ");
  carbomaxModal.sourceEl.textContent = src;

  // Selector de objetivo (solo si no hay sesión)
  const objectives = Array.isArray(pending.objectives) ? pending.objectives : [];
  if (objectives.length) {
    carbomaxModal.objetivoRow.hidden = false;
    carbomaxModal.objetivoSelect.innerHTML = objectives
      .map((o) => `<option value="${String(o).replace(/"/g, "&quot;")}">${String(o)}</option>`)
      .join("");
  } else {
    carbomaxModal.objetivoRow.hidden = true;
  }

  if (!carbomaxModal.visible) {
    carbomaxModal.overlay.removeAttribute("hidden");
    carbomaxModal.visible = true;
  }
}

function hideCarbomaxModal() {
  if (!carbomaxModal.overlay) return;
  carbomaxModal.overlay.setAttribute("hidden", "");
  carbomaxModal.visible = false;
  carbomaxModal.sending = false;
}

async function sendCarbomaxAction(action) {
  if (carbomaxModal.sending) return;
  carbomaxModal.sending = true;
  carbomaxModal.confirmBtn.disabled = true;
  carbomaxModal.rejectBtn.disabled  = true;
  try {
    const body = { action };
    if (action === "confirm") {
      body.objetivo = carbomaxModal.objetivoSelect?.value || "";
      body.colada   = carbomaxModal.coladaInput?.value?.trim() || "";
    }
    await apiFetch("/api/carbomax/action", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
  } catch (_) {
    // silencioso — el host limpiará el estado de todos modos
  } finally {
    hideCarbomaxModal();
  }
}

function setupCarbomaxModal() {
  carbomaxModal.confirmBtn?.addEventListener("click", () => sendCarbomaxAction("confirm"));
  carbomaxModal.rejectBtn?.addEventListener("click",  () => sendCarbomaxAction("reject"));
}

function setStatus(ok, label) {
  nodes.statusPill.textContent = label;
  nodes.statusPill.classList.toggle("is-ok", ok);
}

async function loadSnapshot() {
  try {
    if (!deviceState.id) {
      ensureDeviceIdentity();
    }
    if (deviceState.status !== "approved") {
      const status = await registerDevice();
      if (status !== "approved") {
        renderSnapshot({ ajuste: {}, cucharas: {} });
        return;
      }
    }
    const response = await apiFetch("/api/pie-horno");
    if (response.status === 403) {
      const data = await response.json().catch(() => ({}));
      deviceState.status = data.status || "pending";
      stopLiveEvents();
      const label = "pendiente de aprovar";
      setStatus(false, label);
      setApprovalMessage("pendiente de aprovar", deviceState.status === "revoked" ? "is-revoked" : "");
      renderSnapshot({ ajuste: {}, cucharas: {} });
      return;
    }
    if (!response.ok) {
      throw new Error(`HTTP ${response.status}`);
    }
    const data = await response.json();
    connectionFailures = 0;
    renderSnapshot(data);
    setStatus(true, "Host conectado");
    startLiveEvents();
  } catch (error) {
    connectionFailures += 1;
    setStatus(false, connectionFailures >= 3 ? "Sin conectar" : "Reconectando...");
  }
}

function setupTabs() {
  const tabs = Array.from(document.querySelectorAll("[data-tab-target]"));
  const panels = Array.from(document.querySelectorAll(".panel"));
  tabs.forEach((tab) => {
    tab.addEventListener("click", () => {
      const target = tab.dataset.tabTarget;
      tabs.forEach((node) => node.classList.toggle("is-active", node === tab));
      panels.forEach((panel) => panel.classList.toggle("is-active", panel.id === target));
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

setupTabs();
setupCucharasTabs();
setupCarbomaxModal();
nodes.reloadAppBtn.addEventListener("click", () => {
  window.location.reload();
});
nodes.keyboardToggleBtn.addEventListener("click", toggleKeyboard);
document.addEventListener("focusin", (event) => {
  const target = event.target;
  const editable = target && (
    target === nodes.keyboardFocusInput ||
    target === nodes.deviceNameInput ||
    target.tagName === "INPUT" ||
    target.tagName === "TEXTAREA" ||
    target.isContentEditable
  );
  setKeyboardButtonState(editable);
});
document.addEventListener("focusout", () => {
  window.setTimeout(() => {
    const active = document.activeElement;
    const editable = active && (
      active === nodes.keyboardFocusInput ||
      active === nodes.deviceNameInput ||
      active.tagName === "INPUT" ||
      active.tagName === "TEXTAREA" ||
      active.isContentEditable
    );
    setKeyboardButtonState(editable);
  }, 0);
});
nodes.cucharasStartBtn.addEventListener("click", () => runCucharasAction("start"));
nodes.cucharasSaveBtn.addEventListener("click", () => runCucharasAction("save"));
nodes.ajusteSaveBtn.addEventListener("click", () => saveAjusteConfirmation());
document.querySelectorAll("[data-ajuste-all-pct]").forEach((button) => {
  button.addEventListener("click", () => applyAjustePctAll(button.dataset.ajusteAllPct));
});

async function startApp() {
  ensureDeviceIdentity();
  refreshClock();
  setupIdleClock();
  await requestDeviceNameIfNeeded();
  await loadSnapshot();
  window.setInterval(() => {
    if (deviceState.status === "approved") {
      return;
    }
    registerDevice().then((status) => {
      if (status === "approved") {
        loadSnapshot();
      }
    });
  }, DEVICE_STATUS_REFRESH_MS);
  window.setInterval(loadSnapshot, DATA_REFRESH_MS);
  window.setInterval(refreshClock, CLOCK_REFRESH_MS);
}

startApp();

// ── Inoculaciones ────────────────────────────────────────────────────────────

const MOMENTO_LABEL = {
  horno: "Horno",
  cuchara_transp: "C. transp.",
  cuchara_colar: "C. colar",
};

let inocData = [];

async function loadInoculaciones() {
  try {
    const res = await apiFetch("/api/inoculaciones");
    const data = await res.json();
    inocData = data.inoculaciones || [];
    renderInocList();
  } catch (_) {
    inocData = [];
  }
}

function renderInocList() {
  const list  = document.getElementById("inoc-list");
  const empty = document.getElementById("inoc-list-empty");
  list.innerHTML = "";
  if (!inocData.length) {
    list.appendChild(empty);
    return;
  }
  inocData.forEach((item, idx) => {
    const li = document.createElement("li");
    li.className = "inoc-item";
    li.textContent = item.nombre;
    li.addEventListener("click", () => showInocDetail(idx));
    list.appendChild(li);
  });
}

function showInocDetail(idx) {
  const item = inocData[idx];
  if (!item) return;

  document.querySelectorAll(".inoc-item").forEach((el, i) =>
    el.classList.toggle("is-active", i === idx)
  );

  document.getElementById("inoc-detail-title").textContent = item.nombre;

  const body  = document.getElementById("inoc-detail-body");
  const empty = document.getElementById("inoc-detail-empty");
  const theadRow = document.querySelector("#inoc-detail-table thead tr");
  body.innerHTML = "";

  const proc = item.procedimiento || [];
  if (!proc.length) {
    empty.hidden = false;
    theadRow.innerHTML = "<th>Etapa</th><th>Inoculante</th><th>Total g</th>";
    return;
  }
  empty.hidden = true;

  const sorted = [...proc].sort((a, b) =>
    (a.momento_idx ?? 999) - (b.momento_idx ?? 999)
  );

  // Mapa de labels de etapa desde los datos
  const momentoLabelMap = {};
  for (const e of sorted)
    momentoLabelMap[e.momento || "horno"] = e.momento_label || MOMENTO_LABEL[e.momento] || e.momento || "horno";

  // Unidades presentes en orden de aparición
  const unitsPresent = [];
  for (const e of sorted) {
    const u = e.unidad || "cucharín";
    if (!unitsPresent.includes(u)) unitsPresent.push(u);
  }

  // Reconstruir thead
  let theadHtml = "<th>Etapa</th><th>Inoculante</th>";
  for (const u of unitsPresent)
    theadHtml += `<th class="inoc-col-compact">${u}</th>`;
  for (const u of unitsPresent) {
    theadHtml += `<th class="inoc-col-detail inoc-group-start">cant.</th>`;
    theadHtml += `<th class="inoc-col-detail">g/${u}</th>`;
  }
  theadHtml += "<th>Total g</th>";
  theadRow.innerHTML = theadHtml;

  // Reconstruir tbody
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
      for (const u of unitsPresent)
        rowHtml += `<td class="inoc-col-compact">${eUnit === u ? e.cant : "—"}</td>`;
      for (const u of unitsPresent) {
        const match = eUnit === u;
        rowHtml += `<td class="inoc-col-detail inoc-group-start">${match ? e.cant : "—"}</td>`;
        rowHtml += `<td class="inoc-col-detail">${match && e.gramos ? e.gramos + " g" : "—"}</td>`;
      }
      rowHtml += `<td>${e.total != null ? e.total + " g" : "—"}</td>`;
      const rest = document.createElement("template");
      rest.innerHTML = rowHtml;
      tr.append(...rest.content.childNodes);
      if (hasColor) {
        for (const td of tr.querySelectorAll("td:not(.inoc-etapa-cell)")) {
          td.style.backgroundColor = e.color;
          td.style.color = contrastColor(e.color);
        }
      }
      body.appendChild(tr);
    }
    i += count;
    groupIndex++;
  }
}

function contrastColor(hex) {
  const c = hex.replace("#", "");
  const r = parseInt(c.substring(0, 2), 16) / 255;
  const g = parseInt(c.substring(2, 4), 16) / 255;
  const b = parseInt(c.substring(4, 6), 16) / 255;
  const toLinear = x => x <= 0.04045 ? x / 12.92 : Math.pow((x + 0.055) / 1.055, 2.4);
  const L = 0.2126 * toLinear(r) + 0.7152 * toLinear(g) + 0.0722 * toLinear(b);
  return L > 0.179 ? "#1a1a1a" : "#ffffff";
}

document.getElementById("inoc-mode-btn").addEventListener("click", () => {
  const table = document.getElementById("inoc-detail-table");
  const nowCompact = table.classList.toggle("is-compact");
  document.getElementById("inoc-mode-btn").textContent =
    nowCompact ? "Ver detalle" : "Vista rápida";
});

// Cargar al entrar a la pestaña
document.querySelectorAll("[data-tab-target]").forEach(btn => {
  btn.addEventListener("click", () => {
    if (btn.dataset.tabTarget === "inoc-panel" && !inocData.length) {
      loadInoculaciones();
    }
  });
});
