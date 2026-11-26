// pie_horno.js -- VISTAS.pie_horno: administración de dispositivos + control SSH de la Raspberry del
// kiosko físico. Puerto de frontend/js/pie_horno.js de ajuste_comp_web. A diferencia de las demás vistas,
// esta NO espera aprobación para mostrarse (si no, un dispositivo pendiente nunca podría enterarse de su
// propio ID para que alguien más lo apruebe) -- la tabla completa y el control de Raspberry solo cargan si
// el dispositivo actual ya es "editor".
//
// Nombres con prefijo "ph"/"_ph" -- nucleo concatena todos los scripts del módulo en un solo scope global
// sin import/export, y una "function" de nivel superior se pisa en silencio si otro script ya declaró el
// mismo nombre (a diferencia de let/const, que test_pantallas.py sí detecta).

const phEls = {};

function phActionButton(label, onClick, danger = false) {
  const b = document.createElement("button");
  b.textContent = label;
  if (danger) b.className = "peligro";
  b.onclick = onClick;
  return b;
}

async function phRefreshMe() {
  const me = await Ajuste.myDeviceStatus();
  phEls.myId.textContent = me.id;
  phEls.myStatus.textContent = `${me.status} (${me.role})`;
  return me;
}

async function phRefreshList() {
  try {
    const data = await Ajuste.apiFetch("/api/devices");
    phEls.rows.innerHTML = "";
    const entries = Object.values(data.devices).sort((a, b) =>
      (a.status === "pending" ? 0 : 1) - (b.status === "pending" ? 0 : 1));
    for (const d of entries) {
      const tr = document.createElement("tr");
      tr.innerHTML = `<td>${esc(d.name || "")}</td><td>${esc(d.status)}</td><td>${esc(d.role)}</td>
        <td>${esc(d.last_seen || "")}</td><td>${esc(d.ip || "")}</td>`;
      const actionsTd = document.createElement("td");
      if (d.status !== "approved") {
        actionsTd.appendChild(phActionButton("Aprobar", () => phAct(d.id, "approve")));
      }
      if (d.status !== "revoked") {
        actionsTd.appendChild(phActionButton("Revocar", () => phAct(d.id, "revoke"), true));
      }
      actionsTd.appendChild(phActionButton(
        d.role === "editor" ? "Hacer viewer" : "Hacer editor",
        () => phSetRole(d.id, d.role === "editor" ? "viewer" : "editor"),
      ));
      actionsTd.appendChild(phActionButton("Eliminar", () => phAct(d.id, "", "DELETE"), true));
      tr.appendChild(actionsTd);
      phEls.rows.appendChild(tr);
    }
  } catch (ex) {
    phEls.rows.innerHTML = `<tr><td colspan="6" class="sutil">
      Este dispositivo no es editor todavía — pedile a un editor existente que te apruebe.</td></tr>`;
  }
}

async function phAct(id, action, method = "POST") {
  if (method === "DELETE") {
    if (!confirm("¿Eliminar este dispositivo de la lista?")) return;
    await Ajuste.apiFetch(`/api/devices/${id}`, { method: "DELETE" });
  } else {
    await Ajuste.apiFetch(`/api/devices/${id}/${action}`, { method: "POST" });
  }
  phRefreshList();
}

async function phSetRole(id, role) {
  await Ajuste.apiFetch(`/api/devices/${id}/role/${role}`, { method: "POST" });
  phRefreshList();
}

// ---------- Raspberry Pie de Horno (SSH) ----------

async function phLoadLocalUrl() {
  try {
    const data = await Ajuste.apiFetch("/api/pie-horno/local-url");
    phEls.localUrl.textContent = data.url;
  } catch (ex) {
    phEls.localUrl.textContent = "-";
  }
}

let phRaspBusy = false;

async function phRefreshRaspStatus() {
  if (phRaspBusy) return;
  phEls.raspState.textContent = "Consultando...";
  try {
    const s = await Ajuste.apiFetch("/api/pie-horno/raspberry/status");
    phEls.raspState.textContent = s.state;
    phEls.raspState.style.color = s.state_color || "";
    phEls.raspUrl.textContent = s.url || "-";
    phEls.raspDetail.textContent = s.detail || "-";
    phEls.raspIdle.textContent = s.idle_text || "-";
  } catch (ex) {
    phEls.raspState.textContent = "Error al consultar";
  }
}

async function phRunRaspAction(action, label, { confirmMsg } = {}) {
  if (phRaspBusy) return;
  if (confirmMsg && !confirm(confirmMsg)) return;
  phRaspBusy = true;
  phEls.raspAction.textContent = label;
  try {
    const res = await Ajuste.apiFetch(`/api/pie-horno/raspberry/${action}`, { method: "POST" });
    phEls.raspAction.textContent = res.ok ? (res.message || "Listo.").slice(0, 120) : `Error: ${(res.message || "").slice(0, 100)}`;
  } catch (ex) {
    phEls.raspAction.textContent = `Error: ${ex.message}`;
  } finally {
    phRaspBusy = false;
    setTimeout(phRefreshRaspStatus, action === "reboot" ? 12000 : 2500);
  }
}

VISTAS.pie_horno = async () => {
  $("#vista").innerHTML = `
    <div class="encabezado"><h2>Pie de Horno</h2></div>
    <div class="tarjeta">
      <h3>Acceso Pie de Horno</h3>
      <p class="sutil">URL kiosko (para la Raspberry o cualquier celular/tablet en planta): <b id="ph-local-url">-</b></p>
      <p class="sutil"><a href="/kiosk.html" target="_blank">Abrir el kiosko acá mismo →</a></p>
      <p class="sutil">Un dispositivo aprobado normal solo ve datos. Marcá como editor a los que pueden sumar/restar cucharas o cargar datos.</p>
    </div>

    <div class="tarjeta">
      <h3>Raspberry Pie de Horno</h3>
      <p>Conexión: <b id="ph-rasp-state">Sin consultar</b></p>
      <p class="sutil">URL kiosk: <span id="ph-rasp-url">-</span> — <span id="ph-rasp-detail">-</span></p>
      <p class="sutil">Inactividad: <span id="ph-rasp-idle">-</span></p>
      <div class="botones" style="margin-top:10px;">
        <button id="ph-btn-rasp-refresh">Actualizar estado</button>
        <button id="ph-btn-rasp-sleep">Reposo falso</button>
        <button id="ph-btn-rasp-wake">Despertar kiosk</button>
        <button id="ph-btn-rasp-restart">Reiniciar kiosk</button>
        <button id="ph-btn-rasp-reboot" class="peligro">Reiniciar Raspberry</button>
        <button id="ph-btn-rasp-poweroff" class="peligro">Apagar completo</button>
        <span id="ph-rasp-action" class="sutil"></span>
      </div>
    </div>

    <div class="tarjeta">
      <h3>Dispositivos</h3>
      <p class="sutil">Este dispositivo: <b id="ph-my-id"></b> — estado: <b id="ph-my-status"></b></p>
      <div style="overflow-x:auto;">
        <table>
          <thead><tr><th>Nombre</th><th>Estado</th><th>Rol</th><th>Última conexión</th><th>IP</th><th></th></tr></thead>
          <tbody id="ph-rows"></tbody>
        </table>
      </div>
    </div>`;

  phEls.myId = $("#ph-my-id");
  phEls.myStatus = $("#ph-my-status");
  phEls.rows = $("#ph-rows");
  phEls.localUrl = $("#ph-local-url");
  phEls.raspState = $("#ph-rasp-state");
  phEls.raspUrl = $("#ph-rasp-url");
  phEls.raspDetail = $("#ph-rasp-detail");
  phEls.raspIdle = $("#ph-rasp-idle");
  phEls.raspAction = $("#ph-rasp-action");

  $("#ph-btn-rasp-refresh").addEventListener("click", phRefreshRaspStatus);
  $("#ph-btn-rasp-sleep").addEventListener("click", () => phRunRaspAction("sleep", "Mandando a reposo falso..."));
  $("#ph-btn-rasp-wake").addEventListener("click", () => phRunRaspAction("wake", "Despertando kiosk..."));
  $("#ph-btn-rasp-restart").addEventListener("click", () => phRunRaspAction("restart_kiosk", "Reiniciando kiosk..."));
  $("#ph-btn-rasp-reboot").addEventListener("click", () => phRunRaspAction("reboot", "Reiniciando Raspberry...", {
    confirmMsg: "¿Reiniciar la Raspberry ahora?",
  }));
  $("#ph-btn-rasp-poweroff").addEventListener("click", () => phRunRaspAction("poweroff", "Apagando Raspberry...", {
    confirmMsg: "¿Apagar completamente la Raspberry?\n\nDespués no se puede despertar por SSH hasta que vuelva la energía.",
  }));

  const me = await phRefreshMe();
  await phRefreshList();
  await phLoadLocalUrl();
  // Usuario logueado: edita aunque esta PC no esté aprobada (la aprobación es para el kiosco, no para esta pestaña).
  const canEdit = me.dev_skip_approval || me.por_usuario || (me.status === "approved" && me.role === "editor");
  if (canEdit) {
    phRefreshRaspStatus();
  } else {
    phEls.raspState.textContent = "Necesitás ser editor para controlar la Raspberry.";
  }
  Ajuste.wsConnect("devices", (msg) => {
    if (msg.type === "devices_changed") phRefreshList();
  });
};
