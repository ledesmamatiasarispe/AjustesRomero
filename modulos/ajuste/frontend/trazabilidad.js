// trazabilidad.js -- VISTAS.trazabilidad: consulta de la bitácora de cambios (ISO 9001, 7.5.3 / 8.5.2). Solo lee:
// la bitácora la escribe el backend en la misma transacción de cada cambio (modulos/ajuste/trazabilidad.py).
//
// Nombres con prefijo "traz"/"_traz": el núcleo concatena todos los scripts en un solo scope global.
//
// Otras pantallas abren esta ya filtrada por colada con Ajuste.verTrazabilidad(colada) (p.ej. Históricos).

let _trazCatalogo = null;
let _trazFiltroInicial = null;

Ajuste.verTrazabilidad = function (colada) {
  _trazFiltroInicial = { colada: String(colada || "") };
  irA("trazabilidad");
};

function _trazFecha(iso) {
  const m = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}:\d{2}:\d{2})/.exec(String(iso || ""));
  return m ? `${m[3]}/${m[2]}/${m[1]} ${m[4]}` : esc(iso || "");
}

function _trazValor(v) {
  if (v === null || v === undefined) return `<span class="sutil">—</span>`;
  const texto = typeof v === "object" ? JSON.stringify(v) : String(v);
  const corto = texto.length > 240 ? `${texto.slice(0, 240)}…` : texto;
  return `<span title="${esc(texto.slice(0, 4000))}">${esc(corto)}</span>`;
}

const _TRAZ_ACCION_CLASE = { alta: "traz-alta", modificacion: "traz-mod", baja: "traz-baja", inicio: "traz-inicio" };

function _trazQuien(r) {
  const tipo = r.actor_tipo === "usuario" ? "👤" : r.actor_tipo === "dispositivo" ? "🖥" : "⚙";
  const extra = r.actor_tipo === "usuario" && r.dispositivo ? `<div class="sutil">desde ${esc(r.dispositivo)}</div>` : "";
  return `${tipo} ${esc(r.actor)}${extra}`;
}

function _trazParams() {
  const p = new URLSearchParams();
  for (const id of ["colada", "entidad", "accion", "actor", "desde", "hasta", "texto"]) {
    const v = $(`#traz-${id}`).value.trim();
    if (v) p.set(id, v);
  }
  return p;
}

async function _trazVerificar() {
  const el = $("#traz-integridad");
  el.className = "traz-integridad";
  el.textContent = "Verificando integridad…";
  try {
    const r = await Ajuste.apiFetch("/api/trazabilidad/verificar");
    if (r.integra) {
      el.classList.add("ok");
      el.textContent = `✓ Bitácora íntegra — ${r.registros} registros, ninguno alterado`;
    } else {
      el.classList.add("mal");
      el.textContent = `✗ Bitácora alterada en el registro N° ${r.registro_id}: ${r.detalle}`;
    }
  } catch (ex) {
    el.textContent = `No se pudo verificar (${ex.message})`;
  }
}

async function _trazBuscar() {
  const tbody = $("#traz-rows");
  tbody.innerHTML = `<tr><td colspan="7" class="sutil">Buscando…</td></tr>`;
  let data;
  try {
    data = await Ajuste.apiFetch(`/api/trazabilidad/registros?${_trazParams()}`);
  } catch (ex) {
    tbody.innerHTML = `<tr><td colspan="7" class="sutil">Error: ${esc(ex.message)}</td></tr>`;
    return;
  }
  const filas = data.registros || [];
  $("#traz-cuenta").textContent = filas.length >= 500
    ? "Mostrando los 500 más recientes — filtrá para acotar."
    : `${filas.length} registro(s).`;
  if (!filas.length) {
    tbody.innerHTML = `<tr><td colspan="7" class="sutil">Sin registros para ese filtro.</td></tr>`;
    return;
  }
  const acciones = (_trazCatalogo && _trazCatalogo.acciones) || {};
  tbody.innerHTML = filas.map((r) => `
    <tr class="traz-fila" data-id="${r.id}">
      <td>${r.id}</td>
      <td style="white-space:nowrap;">${_trazFecha(r.fecha)}</td>
      <td>${_trazQuien(r)}</td>
      <td><span class="traz-accion ${_TRAZ_ACCION_CLASE[r.accion] || ""}">${esc(acciones[r.accion] || r.accion)}</span></td>
      <td>${esc(r.entidad_nombre)}<div class="sutil">${esc(r.clave || "")}</div></td>
      <td>${esc(r.resumen || "")}</td>
      <td>${esc(r.motivo || "")}</td>
    </tr>`).join("");
}

async function _trazAbrirDetalle(tr) {
  const siguiente = tr.nextElementSibling;
  if (siguiente && siguiente.classList.contains("traz-detalle")) {
    siguiente.remove();
    return;
  }
  const det = document.createElement("tr");
  det.className = "traz-detalle";
  det.innerHTML = `<td colspan="7" class="sutil">Cargando…</td>`;
  tr.after(det);
  try {
    const r = await Ajuste.apiFetch(`/api/trazabilidad/registros/${tr.dataset.id}`);
    let cuerpo;
    if (r.cambios && r.cambios.length) {
      cuerpo = `<table class="traz-cambios">
        <thead><tr><th>Campo</th><th>Antes</th><th>Después</th></tr></thead>
        <tbody>${r.cambios.map((ch) => `<tr><td class="mono">${esc(ch.campo)}</td>
          <td>${_trazValor(ch.antes)}</td><td>${_trazValor(ch.despues)}</td></tr>`).join("")}</tbody></table>`;
    } else {
      const registro = r.despues !== null && r.despues !== undefined ? r.despues : r.antes;
      const titulo = r.accion === "baja" ? "Registro tal como era al eliminarse" : "Registro tal como se creó";
      cuerpo = `<p><b>${titulo}</b></p><pre class="traz-json">${esc(JSON.stringify(registro, null, 2))}</pre>`;
    }
    det.innerHTML = `<td colspan="7">
      <div class="traz-meta sutil">IP: ${esc(r.ip || "—")} · ${r.actor_tipo === "usuario" && r.dispositivo
        ? `Dispositivo: ${esc(r.dispositivo)} · ` : ""}Huella: <span class="mono">${esc(r.hash.slice(0, 16))}…</span></div>
      ${cuerpo}</td>`;
  } catch (ex) {
    det.innerHTML = `<td colspan="7" class="sutil">Error: ${esc(ex.message)}</td>`;
  }
}

VISTAS.trazabilidad = async () => {
  $("#vista").innerHTML = `
    <div class="encabezado"><h2>Trazabilidad</h2></div>
    <div class="tarjeta">
      <p class="sutil">Registro de todos los cambios: quién, cuándo, desde dónde, qué había antes y qué quedó.
        No se puede editar ni borrar, y cada registro está encadenado con el anterior para detectar alteraciones.</p>
      <div id="traz-integridad" class="traz-integridad"></div>
      <div class="traz-filtros">
        <label>Colada <input id="traz-colada" type="text" placeholder="ej: 1234/26"></label>
        <label>Qué <select id="traz-entidad"><option value="">Todo</option></select></label>
        <label>Acción <select id="traz-accion"><option value="">Todas</option></select></label>
        <label>Quién <input id="traz-actor" type="text" placeholder="usuario o dispositivo"></label>
        <label>Desde <input id="traz-desde" type="date"></label>
        <label>Hasta <input id="traz-hasta" type="date"></label>
        <label>Texto <input id="traz-texto" type="text" placeholder="campo, motivo, clave…"></label>
        <div class="botones">
          <button type="button" id="traz-btn-buscar">Buscar</button>
          <button type="button" id="traz-btn-limpiar">Limpiar</button>
          <button type="button" id="traz-btn-csv">Exportar CSV</button>
        </div>
      </div>
      <p id="traz-cuenta" class="sutil"></p>
      <div style="overflow-x:auto;">
        <table class="traz-tabla">
          <thead><tr><th>N°</th><th>Fecha</th><th>Quién</th><th>Acción</th><th>Qué</th><th>Cambios</th><th>Motivo</th></tr></thead>
          <tbody id="traz-rows"></tbody>
        </table>
      </div>
      <p class="sutil">Tocá un registro para ver el detalle campo por campo.</p>
    </div>`;

  if (!_trazCatalogo) {
    try { _trazCatalogo = await Ajuste.apiFetch("/api/trazabilidad/catalogo"); } catch (_) { _trazCatalogo = null; }
  }
  if (_trazCatalogo) {
    $("#traz-entidad").insertAdjacentHTML("beforeend", Object.entries(_trazCatalogo.entidades)
      .map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join(""));
    $("#traz-accion").insertAdjacentHTML("beforeend", Object.entries(_trazCatalogo.acciones)
      .map(([k, v]) => `<option value="${esc(k)}">${esc(v)}</option>`).join(""));
  }
  if (_trazFiltroInicial) {
    $("#traz-colada").value = _trazFiltroInicial.colada || "";
    _trazFiltroInicial = null;
  }

  $("#traz-btn-buscar").addEventListener("click", _trazBuscar);
  $("#traz-btn-limpiar").addEventListener("click", () => {
    $("#vista").querySelectorAll(".traz-filtros input, .traz-filtros select").forEach((el) => { el.value = ""; });
    _trazBuscar();
  });
  $("#traz-btn-csv").addEventListener("click", async () => {
    // fetch (no un <a href>): la ruta pide la sesión/dispositivo por headers.
    try {
      const resp = await fetch(`/api/trazabilidad/export.csv?${_trazParams()}`,
        { headers: { ...Ajuste.deviceHeaders(), ...Ajuste.sesionHeaders() }, cache: "no-store" });
      if (!resp.ok) throw new Error(`HTTP ${resp.status}`);
      const url = URL.createObjectURL(await resp.blob());
      const a = document.createElement("a");
      a.href = url;
      a.download = `trazabilidad_${new Date().toISOString().slice(0, 10)}.csv`;
      a.click();
      setTimeout(() => URL.revokeObjectURL(url), 2000);
    } catch (ex) {
      alert(`No se pudo exportar: ${ex.message}`);
    }
  });
  $("#vista").querySelectorAll(".traz-filtros input").forEach((el) =>
    el.addEventListener("keydown", (e) => { if (e.key === "Enter") _trazBuscar(); }));
  $("#traz-rows").addEventListener("click", (e) => {
    const tr = e.target.closest("tr.traz-fila");
    if (tr) _trazAbrirDetalle(tr);
  });

  _trazVerificar();
  _trazBuscar();
};

Ayuda.pasos.trazabilidad = () => [
  { titulo: "Trazabilidad", texto: "Cada alta, cambio o baja de coladas, ajustes, cucharas, informes de calidad, "
      + "materiales, configuración y dispositivos queda registrado acá: quién lo hizo, cuándo y desde qué equipo." },
  { el: () => Ayuda.h.enVista("#traz-integridad"), titulo: "Integridad",
    texto: "La bitácora no se puede editar ni borrar. Si alguien la alterara por fuera de la app, acá se ve en qué registro." },
  { el: () => Ayuda.h.enVista(".traz-filtros"), titulo: "Filtros",
    texto: "Filtrá por colada para ver toda su historia, o por período, por persona o por tipo de registro." },
  { el: () => Ayuda.h.enVista(".traz-tabla"), titulo: "Detalle",
    texto: "Tocá un registro para ver campo por campo qué tenía antes y qué quedó. En una baja se ve el registro "
      + "completo tal como era, con el motivo que se escribió al eliminarlo." },
  { el: () => Ayuda.h.boton("Exportar CSV"), titulo: "Exportar",
    texto: "Arma el listado filtrado para una auditoría; se abre directo en Excel." },
];
