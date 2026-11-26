// modbus.js -- VISTAS.modbus: "Delta Modbus", lectura cruda RS485/Modbus RTU del Carbomax Delta (ver
// ..carbomax_modbus.py / rutas/modbus.py). Sin interpretar nada -- vuelca las 4 tablas tal como vienen, para
// seguir armando el mapa de registros a mano. Puerto de frontend/js/modbus.js de ajuste_comp_web.
//
// Nombres con prefijo "modbus"/"_modbus" -- nucleo concatena todos los scripts del módulo en un solo scope
// global sin import/export, y una "function" de nivel superior se pisa en silencio si otro script ya
// declaró el mismo nombre.

const MODBUS_KEYS = ["coils", "discrete_inputs", "holding_registers", "input_registers"];

function _modbusRenderTable(entry) {
  if (!entry.ok) {
    return `<p class="error">${esc(entry.error || "Error de lectura.")}</p>`;
  }
  if (!entry.values.length) {
    return `<p class="sutil">Sin valores.</p>`;
  }
  const hasHex = entry.values[0].hex !== undefined;
  const head = hasHex
    ? "<tr><th>Dirección</th><th>Valor</th><th class=\"mono\">Hex</th></tr>"
    : "<tr><th>Dirección</th><th>Valor</th></tr>";
  const rows = entry.values.map((v) => (
    hasHex
      ? `<tr><td>${v.address}</td><td>${v.value}</td><td class="mono">${esc(v.hex)}</td></tr>`
      : `<tr><td>${v.address}</td><td>${v.value}</td></tr>`
  )).join("");
  return `<div style="overflow-x:auto;"><table><thead>${head}</thead><tbody>${rows}</tbody></table></div>`;
}

function _modbusRenderResults(grid, results) {
  grid.innerHTML = MODBUS_KEYS.map((key) => {
    const entry = results[key];
    if (!entry) return "";
    return `
      <section class="tarjeta">
        <h3>${esc(entry.label)}</h3>
        <p class="sutil">Dirección ${entry.start} — cantidad ${entry.quantity}</p>
        ${_modbusRenderTable(entry)}
      </section>`;
  }).join("");
}

VISTAS.modbus = async () => {
  $("#vista").innerHTML = `
    <div class="encabezado"><h2>Delta Modbus</h2></div>
    <div class="tarjeta">
      <div class="campos">
        <label>Dirección inicial<br><input id="modbus-f-start" type="number" min="0" value="0" style="width:100px;"></label>
        <label>Cantidad<br><input id="modbus-f-count" type="number" min="1" max="2000" value="32" style="width:100px;"></label>
      </div>
      <div class="botones">
        <button type="button" id="modbus-btn-read" class="primario">Leer</button>
      </div>
      <p class="error" id="modbus-status"></p>
    </div>
    <div id="modbus-grid"></div>`;

  const startInput = $("#modbus-f-start");
  const countInput = $("#modbus-f-count");
  const btnRead = $("#modbus-btn-read");
  const statusEl = $("#modbus-status");
  const grid = $("#modbus-grid");

  async function leer() {
    btnRead.disabled = true;
    statusEl.className = "sutil";
    statusEl.textContent = "Leyendo...";
    const start = parseInt(startInput.value, 10) || 0;
    const count = parseInt(countInput.value, 10) || 32;
    try {
      const data = await Ajuste.apiFetch("/api/modbus/read", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ start, count }),
      });
      _modbusRenderResults(grid, data.results);
      statusEl.className = "sutil";
      statusEl.textContent = `OK — dirección ${data.start}`;
    } catch (ex) {
      statusEl.className = "error";
      statusEl.textContent = `Error: ${ex.detail?.detail?.message || ex.message}`;
    } finally {
      btnRead.disabled = false;
    }
  }

  btnRead.addEventListener("click", leer);

  Ajuste.waitForApproval(async (status) => {
    const canEdit = status.role === "editor" || status.dev_skip_approval;
    if (!canEdit) {
      btnRead.disabled = true;
      statusEl.className = "error";
      statusEl.textContent = "Solo lectura (rol viewer) — no se puede disparar una lectura Modbus.";
    }
  });
};
