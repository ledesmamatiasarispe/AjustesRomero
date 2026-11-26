// catalogo.js -- puerto de frontend/js/catalogo.js de ajuste_comp_web como VISTAS.catalogo del shell del
// núcleo: lista + editor de materiales. Usa el modal nativo del núcleo (abrirModal/cerrarModal) en vez del
// overlay propio #modal-root de la app vieja, y avisar() para mensajes de guardado/error en vez de un span de
// estado en la barra -- mismo patrón que ya usa el núcleo en su propia pantalla de Opciones.
const CE_FORMULAS = ["FUNDICION", "IIW", "IIW+Si/24", "CET", "PERSONALIZADA"];

let CAT_META = { elements: [], alloy_types: [] };
let CAT_ALLOYS = [];
let CAT_CAN_EDIT = false;
let catWsOff = null;

function catFmtNum(n) {
  if (n === null || n === undefined || n === "") return "";
  const v = Number(n);
  if (!Number.isFinite(v)) return "";
  const s = v.toFixed(6);
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}

function catParseNum(s, fallback = 0) {
  const v = parseFloat(String(s ?? "").replace(",", "."));
  return Number.isFinite(v) ? v : fallback;
}

async function catLoadMeta() {
  CAT_META = await Ajuste.apiFetch("/api/meta");
}

async function catLoadAlloys() {
  CAT_ALLOYS = await Ajuste.apiFetch("/api/alloys");
  catRefreshTipoFilterOptions();
  catRenderRows();
}

function catRefreshTipoFilterOptions() {
  const sel = $("#cat-filter-tipo");
  const tipos = [...new Set(CAT_ALLOYS.map((a) => a.tipo).filter(Boolean))].sort();
  const current = sel.value;
  sel.innerHTML = `<option value="">Todos los tipos</option>` +
    tipos.map((t) => `<option value="${esc(t)}">${esc(t)}</option>`).join("");
  sel.value = tipos.includes(current) ? current : "";
}

function catHasAnyLimits(a) {
  const lim = a.limites || {};
  return CAT_META.elements.some((e) => {
    const d = lim[e] || {};
    return d.soft_min !== null && d.soft_min !== undefined
      || d.soft_max !== null && d.soft_max !== undefined;
  });
}

function catInoculantNames() {
  // Mismo orden que tab_catalogo.py::nombres_sorted: numérico si el nombre es todo dígitos, alfabético
  // (case-insensitive) para el resto.
  const names = [...new Set(CAT_ALLOYS.filter((a) => a.inoculante).map((a) => a.nombre))];
  names.sort((x, y) => {
    const nx = /^\d+$/.test(x), ny = /^\d+$/.test(y);
    if (nx && ny) return Number(x) - Number(y);
    if (nx !== ny) return nx ? -1 : 1;
    return x.toLowerCase().localeCompare(y.toLowerCase());
  });
  return names;
}

function catUnitOfInoc(nombre) {
  const alloy = CAT_ALLOYS.find((x) => x.nombre === nombre);
  return (alloy && alloy.unidad_inoculacion) || "cucharín";
}

function catGramosOfInoc(nombre) {
  const alloy = CAT_ALLOYS.find((x) => x.nombre === nombre);
  return (alloy && Number(alloy.gramos_cucharin1)) || 0;
}

function catBaseNames() {
  // "Aleación propia" candidatas como base.
  return [...new Set(CAT_ALLOYS.filter((a) => a.tipo === "Aleación propia").map((a) => a.nombre))].sort();
}

function catRenderRows() {
  const q = $("#cat-search").value.trim().toLowerCase();
  const tipo = $("#cat-filter-tipo").value;
  const rowsEl = $("#cat-rows");
  rowsEl.innerHTML = "";
  for (const a of CAT_ALLOYS) {
    if (q && !(a.nombre || "").toLowerCase().includes(q)) continue;
    if (tipo && a.tipo !== tipo) continue;
    const tr = document.createElement("tr");
    const tipoLabel = a.tipo + (a.inoculante ? " [inoculante]" : "");
    tr.innerHTML = `
      <td>${esc(a.nombre || "")}</td>
      <td>${esc(tipoLabel)}</td>
      <td>${catFmtNum(a.rendimiento)}</td>
      <td>${catFmtNum(a.costo)}</td>
      <td>${a.ajuste ? "Sí" : ""}</td>
      <td>${catHasAnyLimits(a) ? "Sí" : ""}</td>
      <td class="col-action" data-col="inoc"></td>
      <td class="col-action" data-col="edit"></td>
      <td class="col-action" data-col="dup"></td>
      <td class="col-action" data-col="del"></td>
    `;
    // Cada acción vive SIEMPRE en su propia celda, y el botón SIEMPRE se crea -- cuando no corresponde para
    // esta fila (no es Aleación final, o el dispositivo no es editor) el botón queda deshabilitado en vez de
    // sacarse, para que el lugar nunca cambie de una fila a otra.
    const addActionButton = (col, label, onClick, { enabled, danger = false } = {}) => {
      const btn = document.createElement("button");
      btn.className = "chico" + (danger ? " peligro" : "");
      btn.textContent = label;
      btn.disabled = !enabled;
      if (enabled) btn.onclick = onClick;
      tr.querySelector(`[data-col="${col}"]`).appendChild(btn);
    };

    addActionButton("inoc", "Ver", () => catOpenInoculacionViewer(a), { enabled: a.tipo === "Aleación final" });
    addActionButton("edit", "Editar", () => catOpenEditor(a), { enabled: CAT_CAN_EDIT });
    addActionButton("dup", "Duplicar", () => catDuplicateAlloy(a.idx), { enabled: CAT_CAN_EDIT });
    addActionButton("del", "Eliminar", () => catDeleteAlloy(a), { enabled: CAT_CAN_EDIT, danger: true });

    rowsEl.appendChild(tr);
  }
}

async function catDuplicateAlloy(idx) {
  try {
    await Ajuste.apiFetch(`/api/alloys/${idx}/duplicate`, { method: "POST" });
    avisar("Duplicado.");
  } catch (ex) {
    avisar(`Error: ${ex.message}`, true);
  }
}

async function catDeleteAlloy(a) {
  if (!confirm(`¿Eliminar "${a.nombre}"?`)) return;
  try {
    await Ajuste.apiFetch(`/api/alloys/${a.idx}`, { method: "DELETE" });
    avisar("Eliminado.");
  } catch (ex) {
    avisar(`Error: ${ex.message}`, true);
  }
}

// ---------- "Ver inoculación" / "Ver composición estimada" (solo lectura) ----------

async function catOpenInoculacionViewer(alloy) {
  const data = await Ajuste.apiFetch(`/api/alloys/${alloy.idx}/inoculacion`);
  const rows = data.rows.map((r) => `<tr>
    <td>${esc(r.nombre)}</td><td>${catFmtNum(r.cantidad_dosis)}</td>
    <td>${r.gramos_cucharin1 ? catFmtNum(r.gramos_cucharin1) + " g" : "—"}</td>
    <td>${r.total_g != null ? catFmtNum(r.total_g) + " g" : "—"}</td>
  </tr>`).join("") || `<tr><td colspan="4" class="sutil">Sin protocolo configurado.</td></tr>`;
  abrirModal(`
    <h2>Inoculación — ${esc(data.nombre)}</h2>
    <p class="sutil">Bases: ${esc(data.bases.join(" / ") || "—")}</p>
    <div class="tabla-wrap"><table>
      <thead><tr><th>Material</th><th>Cant.</th><th>g/unidad</th><th>Total g</th></tr></thead>
      <tbody>${rows}</tbody>
    </table></div>
    <div class="botones" style="margin-top:14px;justify-content:flex-end;">
      <button id="cat-btn-ver-comp">Ver composición estimada</button>
      <button id="cat-btn-close-inoc">Cerrar</button>
    </div>`);
  $("#cat-btn-close-inoc").onclick = cerrarModal;
  $("#cat-btn-ver-comp").onclick = () => catOpenCompEstimadaViewer(alloy, data.bases);
}

async function catOpenCompEstimadaViewer(alloy, bases) {
  if (!bases.length) { alert("Esta Aleación final no tiene bases configuradas."); return; }
  const momentos = (await Ajuste.apiFetch("/api/alloys/inoc/momentos")).momentos;
  const massInputs = momentos.map((m) => `<div>
    <label>${esc(m.label)} (kg)</label>
    <input data-mass="${esc(m.key)}" type="text" value="${m.masa_default ?? 50}" style="width:80px">
  </div>`).join("");
  abrirModal(`
    <h2>Composición estimada — ${esc(alloy.nombre)}</h2>
    <div class="row"><div><label>Base</label>
      <select id="cat-f-base">${bases.map((b) => `<option>${esc(b)}</option>`).join("")}</select>
    </div></div>
    <div class="row">${massInputs}</div>
    <div class="tabla-wrap"><table><thead><tr><th>Elemento</th><th>Base (%)</th><th>Inoculantes (Δ%)</th><th>Total estimado (%)</th></tr></thead><tbody id="cat-comp-rows"></tbody></table></div>
    <p id="cat-ce-out" class="sutil"></p>
    <div class="botones" style="justify-content:flex-end;">
      <button id="cat-btn-calc" class="primario">Calcular</button>
      <button id="cat-btn-close-comp">Cerrar</button>
    </div>`, true);
  $("#cat-btn-close-comp").onclick = cerrarModal;
  async function calc() {
    const base = $("#cat-f-base").value;
    const stage_masses = {};
    document.querySelectorAll("#modal-cuerpo [data-mass]").forEach((inp) => {
      stage_masses[inp.dataset.mass] = catParseNum(inp.value, 0);
    });
    try {
      const res = await Ajuste.apiFetch(`/api/alloys/${alloy.idx}/simulate-inoc`, {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base, stage_masses }),
      });
      $("#cat-comp-rows").innerHTML = Object.entries(res.composicion)
        .map(([e, v]) => {
          const b = res.base_composicion?.[e] ?? 0;
          const delta = res.inoculantes_delta?.[e] ?? 0;
          const gramos = res.inoculantes_gramos?.[e] ?? 0;
          const sign = delta > 0 ? "+" : "";
          const gramosTxt = gramos > 0.004 ? ` (${catFmtNum(gramos)}g)` : "";
          return `<tr><td>${esc(e)}</td><td>${catFmtNum(b)}</td><td>${sign}${catFmtNum(delta)}${gramosTxt}</td><td>${catFmtNum(v)}</td></tr>`;
        }).join("");
      $("#cat-ce-out").textContent = `CE (Fundición): ${catFmtNum(res.ce_fundicion)}`;
    } catch (ex) {
      $("#cat-ce-out").textContent = `Error: ${ex.detail?.detail?.error || ex.message}`;
    }
  }
  $("#cat-btn-calc").onclick = calc;
  calc();
}

// ---------- Editor ----------

function catOpenEditor(alloy) {
  const isNew = !alloy;
  const a = alloy || {
    nombre: "", tipo: "Ferroaleación", rendimiento: 90, costo: 0,
    composicion: {}, limites: {}, especiales: {}, ajuste: false,
    inoculante: false, gramos_cucharin1: 0, unidad_inoculacion: "cucharín", color_inoculacion: "",
  };

  abrirModal(`
    <h2>${isNew ? "Nuevo material" : `Editar: ${esc(a.nombre)}`}</h2>
    <div class="row">
      <div><label>Nombre</label><input id="cat-f-nombre" type="text" value="${esc(a.nombre || "")}" style="width:260px"></div>
      <div><label>Tipo</label>
        <select id="cat-f-tipo">${CAT_META.alloy_types.map((t) => `<option ${t === a.tipo ? "selected" : ""}>${esc(t)}</option>`).join("")}</select>
      </div>
      <div><label>Rendimiento %</label><input id="cat-f-rend" type="text" value="${catFmtNum(a.rendimiento)}" style="width:80px"></div>
      <div><label>Costo</label><input id="cat-f-costo" type="text" value="${catFmtNum(a.costo)}" style="width:80px"></div>
      <div><label class="check"><input id="cat-f-ajuste" type="checkbox" ${a.ajuste ? "checked" : ""}> Material de ajuste</label></div>
      <div><label class="check"><input id="cat-f-inoculante" type="checkbox" ${a.inoculante ? "checked" : ""}> Es inoculante</label></div>
    </div>
    <div id="cat-dosif-box" class="row" style="display:none;background:var(--gris-claro);padding:8px;border-radius:6px;">
      <div><label>Unidad</label><input id="cat-f-unidad" type="text" value="${esc(a.unidad_inoculacion || "cucharín")}" style="width:100px"></div>
      <div><label>g/unidad</label><input id="cat-f-gramos" type="text" value="${catFmtNum(a.gramos_cucharin1)}" style="width:80px"></div>
      <div><label>Color PDH</label>
        <div style="display:flex;align-items:center;gap:4px;">
          <input id="cat-f-color" type="text" value="${esc(a.color_inoculacion || "")}" style="width:90px" placeholder="#rrggbb">
          <input id="cat-f-color-picker" type="color" value="${/^#[0-9a-fA-F]{6}$/.test(a.color_inoculacion || "") ? a.color_inoculacion : "#ffffff"}" title="Elegir color" style="width:34px;height:30px;padding:2px;cursor:pointer;">
        </div>
      </div>
    </div>
    <div id="cat-body-generic"></div>
    <div id="cat-body-final" style="display:none;"></div>
    <div class="botones" style="margin-top:16px;justify-content:flex-end;">
      <span id="cat-modal-status" class="error"></span>
      <button id="cat-btn-cancel">Cancelar</button>
      <button id="cat-btn-save" class="primario">Guardar</button>
    </div>
  `, true);

  const dosifBox = $("#cat-dosif-box");
  const fInoc = $("#cat-f-inoculante");
  const syncDosif = () => { dosifBox.style.display = fInoc.checked ? "flex" : "none"; };
  fInoc.addEventListener("change", syncDosif);
  syncDosif();

  // Paleta de color del inoculante (se usa para mostrarlo en Pie de Horno) -- el input type=color nativo ES
  // la paleta; se mantiene en sincro con el campo de texto para poder también tipear un hex a mano o dejarlo
  // vacío.
  const fColor = $("#cat-f-color");
  const fColorPicker = $("#cat-f-color-picker");
  fColorPicker.addEventListener("input", () => { fColor.value = fColorPicker.value; });
  fColor.addEventListener("input", () => {
    const v = fColor.value.trim();
    if (/^#[0-9a-fA-F]{6}$/.test(v)) fColorPicker.value = v;
  });

  const bodyGeneric = $("#cat-body-generic");
  const bodyFinal = $("#cat-body-final");
  const fTipo = $("#cat-f-tipo");

  catBuildGenericBody(bodyGeneric, a);
  const finalCtx = catBuildFinalBody(bodyFinal, a);

  function syncMode() {
    const isFinal = fTipo.value === "Aleación final";
    bodyGeneric.style.display = isFinal ? "none" : "block";
    bodyFinal.style.display = isFinal ? "block" : "none";
  }
  fTipo.addEventListener("change", syncMode);
  syncMode();

  $("#cat-btn-cancel").onclick = cerrarModal;
  $("#cat-btn-save").onclick = async () => {
    const modalStatus = $("#cat-modal-status");
    try {
      const payload = {
        nombre: $("#cat-f-nombre").value.trim(),
        tipo: fTipo.value,
        rendimiento: catParseNum($("#cat-f-rend").value, 0),
        costo: catParseNum($("#cat-f-costo").value, 0),
        ajuste: $("#cat-f-ajuste").checked,
        inoculante: fInoc.checked,
        unidad_inoculacion: $("#cat-f-unidad").value.trim() || "cucharín",
        gramos_cucharin1: catParseNum($("#cat-f-gramos").value, 0),
        color_inoculacion: $("#cat-f-color").value.trim(),
      };
      if (!payload.nombre) throw new Error("El nombre es obligatorio.");

      if (fTipo.value === "Aleación final") {
        await finalCtx.ready; // etapas (momentos) tienen que estar cargadas antes de leer la grilla
        Object.assign(payload, finalCtx.collect());
      } else {
        Object.assign(payload, catCollectGenericBody(bodyGeneric));
      }

      if (isNew) {
        await Ajuste.apiFetch("/api/alloys", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      } else {
        await Ajuste.apiFetch(`/api/alloys/${a.idx}`, { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) });
      }
      cerrarModal();
      avisar("Guardado.");
    } catch (ex) {
      modalStatus.textContent = ex.detail?.detail?.error || ex.message;
    }
  };
}

// ---------- Cuerpo genérico: composición + límites + especiales (CE) ----------

function catBuildGenericBody(container, a) {
  const compRows = CAT_META.elements.map((e) => {
    const val = a.composicion?.[e] ?? 0;
    return `<label>${esc(e)}: <input data-comp="${esc(e)}" type="text" value="${catFmtNum(val)}"></label>`;
  }).join("");

  const limRows = CAT_META.elements.map((e) => {
    const lim = a.limites?.[e] || {};
    const ideal = a.composicion?.[e] ?? 0;
    const deltaMin = (lim.soft_min !== null && lim.soft_min !== undefined && (ideal - lim.soft_min) >= 0)
      ? catFmtNum(ideal - lim.soft_min) : "";
    const deltaMax = (lim.soft_max !== null && lim.soft_max !== undefined && (lim.soft_max - ideal) >= 0)
      ? catFmtNum(lim.soft_max - ideal) : "";
    return `<tr>
      <td>${esc(e)}</td>
      <td><input data-lim-min="${esc(e)}" type="text" value="${deltaMin}" style="width:80px"></td>
      <td><input data-lim-max="${esc(e)}" type="text" value="${deltaMax}" style="width:80px"></td>
    </tr>`;
  }).join("");

  const esp = Object.assign(
    { CE_formula: "FUNDICION", CE_min: "", CE_max: "", CE_custom: {} },
    a.especiales || {},
  );
  const ceCustomRows = CAT_META.elements.map((e) => {
    const v = esp.CE_custom?.[e];
    return `<tr><td>${esc(e)}</td><td><input data-ce-coef="${esc(e)}" type="text" value="${v != null ? catFmtNum(v) : ""}" style="width:80px"></td></tr>`;
  }).join("");

  container.innerHTML = `
    <h3>Composición (% en peso)</h3>
    <div class="cat-grid-elements">${compRows}</div>

    <h3>Límites (± independiente por elemento — vacío = sin límite de ese lado)</h3>
    <div class="row"><button type="button" id="cat-btn-auto-limits">Auto-límites…</button></div>
    <div style="max-height:220px;overflow:auto;">
      <table><thead><tr><th>Elemento</th><th>Mínimo</th><th>Máximo</th></tr></thead>
      <tbody id="cat-lim-body">${limRows}</tbody></table>
    </div>

    <h3>Carbono equivalente (CE)</h3>
    <div class="row">
      <div><label>Fórmula</label>
        <select id="cat-f-ce-formula">${CE_FORMULAS.map((f) => `<option ${f === esp.CE_formula ? "selected" : ""}>${f}</option>`).join("")}</select>
      </div>
      <div><label>CE mín</label><input id="cat-f-ce-min" type="text" value="${esp.CE_min ?? ""}" style="width:80px"></div>
      <div><label>CE máx</label><input id="cat-f-ce-max" type="text" value="${esp.CE_max ?? ""}" style="width:80px"></div>
    </div>
    <div id="cat-ce-custom-box" style="display:none;max-height:180px;overflow:auto;">
      <p class="sutil" style="font-size:0.8rem;">CE = Σ coeficiente × %elemento</p>
      <table><thead><tr><th>Elemento</th><th>Coef.</th></tr></thead><tbody>${ceCustomRows}</tbody></table>
    </div>
  `;

  const ceFormulaSel = container.querySelector("#cat-f-ce-formula");
  const ceCustomBox = container.querySelector("#cat-ce-custom-box");
  const syncCe = () => { ceCustomBox.style.display = ceFormulaSel.value === "PERSONALIZADA" ? "block" : "none"; };
  ceFormulaSel.addEventListener("change", syncCe);
  syncCe();

  container.querySelector("#cat-btn-auto-limits").onclick = () => catOpenAutoLimitsDialog(container);
}

function catCollectGenericBody(container) {
  const composicion = {};
  container.querySelectorAll("[data-comp]").forEach((input) => {
    composicion[input.dataset.comp] = catParseNum(input.value, 0);
  });
  const limites = {};
  for (const e of CAT_META.elements) {
    const minInput = container.querySelector(`[data-lim-min="${e}"]`);
    const maxInput = container.querySelector(`[data-lim-max="${e}"]`);
    const minV = minInput.value.trim() === "" ? null : catParseNum(minInput.value, NaN);
    const maxV = maxInput.value.trim() === "" ? null : catParseNum(maxInput.value, NaN);
    const ideal = composicion[e] ?? 0;
    limites[e] = {
      soft_min: (minV !== null && !Number.isNaN(minV)) ? ideal - minV : null,
      soft_max: (maxV !== null && !Number.isNaN(maxV)) ? ideal + maxV : null,
    };
  }
  const ceFormula = container.querySelector("#cat-f-ce-formula").value;
  const especiales = {
    CE_formula: ceFormula,
    CE_min: container.querySelector("#cat-f-ce-min").value.trim() === "" ? null : catParseNum(container.querySelector("#cat-f-ce-min").value, null),
    CE_max: container.querySelector("#cat-f-ce-max").value.trim() === "" ? null : catParseNum(container.querySelector("#cat-f-ce-max").value, null),
  };
  if (ceFormula === "PERSONALIZADA") {
    const custom = {};
    container.querySelectorAll("[data-ce-coef]").forEach((input) => {
      const v = input.value.trim();
      if (v !== "") custom[input.dataset.ceCoef] = catParseNum(v, 0);
    });
    especiales.CE_custom = custom;
  }
  return { composicion, limites, especiales };
}

function catOpenAutoLimitsDialog(genericBody) {
  const checks = CAT_META.elements.map((e) =>
    `<label class="check" style="display:block;"><input type="checkbox" data-el="${esc(e)}" checked> ${esc(e)}</label>`).join("");
  abrirModal(`
    <h2>Auto-límites</h2>
    <div class="row"><div><label>Rango ± (min y max)</label><input id="cat-f-abs" type="text" value="0.10" style="width:80px"></div></div>
    <div style="max-height:220px;overflow:auto;">${checks}</div>
    <div class="botones" style="justify-content:flex-end;">
      <button id="cat-btn-cancel2">Cancelar</button>
      <button id="cat-btn-apply" class="primario">Aplicar</button>
    </div>`);
  $("#cat-btn-cancel2").onclick = cerrarModal;
  $("#cat-btn-apply").onclick = () => {
    const rng = catParseNum($("#cat-f-abs").value, NaN);
    if (Number.isNaN(rng) || rng < 0) { alert("Rango inválido."); return; }
    document.querySelectorAll("#modal-cuerpo [data-el]").forEach((chk) => {
      if (!chk.checked) return;
      const e = chk.dataset.el;
      const compInput = genericBody.querySelector(`[data-comp="${e}"]`);
      const ideal = catParseNum(compInput.value, 0);
      const minInput = genericBody.querySelector(`[data-lim-min="${e}"]`);
      const maxInput = genericBody.querySelector(`[data-lim-max="${e}"]`);
      if (ideal <= 0) { minInput.value = ""; maxInput.value = ""; return; }
      minInput.value = catFmtNum(rng);
      maxInput.value = catFmtNum(rng);
    });
    cerrarModal();
  };
}

// ---------- Cuerpo "Aleación final": ficha de calidad + protocolo de inoculación ----------

function catBuildFinalBody(container, a) {
  const calidadMeta = a.calidad_meta || {};
  const savedBases = calidadMeta.bases || [];
  const defaults = calidadMeta.defaults || {};
  const inocMeta = a.inoculacion_meta || {};
  const candidates = [...new Set([...catBaseNames(), ...savedBases])].sort();

  const baseChecks = candidates.map((b) =>
    `<label style="display:inline-block;margin-right:10px;"><input type="checkbox" data-base-chk="${esc(b)}" ${savedBases.includes(b) ? "checked" : ""}> ${esc(b)}</label>`
  ).join("");

  container.innerHTML = `
    <h3>Ficha de calidad (Aleación final)</h3>
    <div class="row"><div style="flex:1;"><label>Bases válidas</label><div>${baseChecks || "<span class=\"sutil\">No hay materiales tipo Aleación propia todavía.</span>"}</div></div>
      <div><label>Familia</label>
        <select id="cat-f-family"><option ${calidadMeta.family === "Gris" ? "selected" : ""}>Gris</option><option ${calidadMeta.family === "Nodular" ? "selected" : ""}>Nodular</option></select>
      </div>
    </div>
    <div class="row">
      <div><label>Tracción</label><input id="cat-f-traccion" type="text" value="${esc(defaults.traccion || "")}" style="width:90px"></div>
      <div><label>Sección muestra</label><input id="cat-f-seccion" type="text" value="${esc(defaults.seccion || "")}" style="width:120px"></div>
      <div><label>Dureza</label><input id="cat-f-dureza" type="text" value="${esc(defaults.dureza || "")}" style="width:90px"></div>
    </div>
    <div class="row">
      <div><label>Tamaño grafito</label><input id="cat-f-tam" type="text" value="${esc(defaults.tam_grafito || "")}" style="width:90px"></div>
      <div id="cat-f-morf-wrap"><label>Morfología</label><input id="cat-f-morf" type="text" value="${esc(defaults.morfologia || "")}" style="width:120px"></div>
      <div><label>Tipo grafito</label><input id="cat-f-tipo-graf" type="text" value="${esc(defaults.tipo_grafito || "")}" style="width:120px"></div>
    </div>
    <div class="row">
      <div><label>Conteo nódulos</label><input id="cat-f-conteo" type="text" value="${esc(defaults.conteo_nodulos || "")}" style="width:90px"></div>
      <div><label>% nodularización</label><input id="cat-f-pctnod" type="text" value="${esc(defaults.pct_nodularizacion || "")}" style="width:120px"></div>
      <div><label>Alargamiento</label><input id="cat-f-alarg" type="text" value="${esc(defaults.alargamiento || "")}" style="width:90px"></div>
    </div>
    <div class="row">
      <div><label>Perlita</label><input id="cat-f-perlita" type="text" value="${esc(defaults.perlita || "")}" style="width:90px"></div>
      <div><label>Ferrita</label><input id="cat-f-ferrita" type="text" value="${esc(defaults.ferrita || "")}" style="width:90px"></div>
    </div>

    <h3>Protocolo de inoculación</h3>
    <div class="row" style="align-items:center;">
      <div id="cat-f-inoc-tabs" class="inoc-tabs"></div>
      <div id="cat-f-inoc-use-default-wrap" style="display:none;">
        <label class="check">
          <input type="checkbox" id="cat-f-inoc-use-default"> Usar protocolo por defecto
        </label>
      </div>
    </div>
    <div class="tabla-wrap" style="max-height:320px;overflow:auto;">
      <table><thead id="cat-inoc-grid-head"></thead><tbody id="cat-inoc-grid-body"></tbody></table>
    </div>
  `;

  const familySel = container.querySelector("#cat-f-family");
  const morfWrap = container.querySelector("#cat-f-morf-wrap");
  const syncFamily = () => { morfWrap.style.display = familySel.value === "Nodular" ? "none" : "block"; };
  familySel.addEventListener("change", syncFamily);
  syncFamily();

  // Grilla fija: filas = TODOS los materiales con flag inoculante activo (no solo los ya cargados en el
  // protocolo), columnas = TODAS las etapas + una columna de referencia "g/unidad" por cada unidad de medida
  // presente entre esos materiales. protocolByBase[scope] = { nombre: { momento: cantidad_dosis } }, solo se
  // guardan entradas con cantidad > 0.
  const protocolByBase = { "": catEntriesToNestedMap(inocMeta.inoculacion || []) };
  const useDefaultByBase = {};
  for (const [base, entries] of Object.entries(inocMeta.por_base || {})) {
    protocolByBase[base] = catEntriesToNestedMap(entries);
    useDefaultByBase[base] = false; // esta base ya tenía protocolo propio guardado
  }
  for (const b of candidates) {
    if (!(b in useDefaultByBase)) useDefaultByBase[b] = true; // sin override -> hereda default
  }

  const inocNames = catInoculantNames();
  const unitsPresent = [];
  for (const n of inocNames) {
    const u = catUnitOfInoc(n);
    if (!unitsPresent.includes(u)) unitsPresent.push(u);
  }

  const tabsEl = container.querySelector("#cat-f-inoc-tabs");
  const useDefaultWrap = container.querySelector("#cat-f-inoc-use-default-wrap");
  const useDefaultChk = container.querySelector("#cat-f-inoc-use-default");
  const gridHead = container.querySelector("#cat-inoc-grid-head");
  const gridBody = container.querySelector("#cat-inoc-grid-body");
  let momentos = [];
  let currentScope = "";

  // Subpestañas (una por base marcada, más "Por defecto") en vez de un desplegable.
  function switchScope(scope) {
    collectCurrentScopeFromDom(); // guarda ediciones de la pestaña anterior antes de cambiar
    currentScope = scope;
    renderGrid();
    refreshScopeTabs();
  }

  function refreshScopeTabs() {
    const checkedBases = [...container.querySelectorAll("[data-base-chk]")]
      .filter((c) => c.checked).map((c) => c.dataset.baseChk);
    if (!checkedBases.includes(currentScope)) currentScope = "";
    const tabs = ["", ...checkedBases];
    tabsEl.innerHTML = tabs.map((scope) => `<button type="button" class="inoc-tab ${scope === currentScope ? "active" : ""}" data-scope="${esc(scope)}">${esc(scope) || "Por defecto"}</button>`).join("");
    tabsEl.querySelectorAll(".inoc-tab").forEach((btn) => {
      btn.addEventListener("click", () => switchScope(btn.dataset.scope));
    });
  }
  container.querySelectorAll("[data-base-chk]").forEach((chk) => chk.addEventListener("change", refreshScopeTabs));
  refreshScopeTabs();

  function collectCurrentScopeFromDom() {
    if (!gridBody.querySelector("[data-nombre]")) return;
    const map = protocolByBase[currentScope] || (protocolByBase[currentScope] = {});
    gridBody.querySelectorAll("[data-nombre][data-momento]").forEach((inp) => {
      const nombre = inp.dataset.nombre;
      const momento = inp.dataset.momento;
      const v = catParseNum(inp.value, 0);
      if (!map[nombre]) map[nombre] = {};
      if (v > 0) map[nombre][momento] = v;
      else delete map[nombre][momento];
    });
  }

  function renderGrid() {
    const scope = currentScope;
    const map = protocolByBase[scope] || (protocolByBase[scope] = {});

    if (scope === "") {
      useDefaultWrap.style.display = "none";
    } else {
      useDefaultWrap.style.display = "";
      useDefaultChk.checked = !!useDefaultByBase[scope];
    }
    const disabled = scope !== "" && useDefaultByBase[scope];

    let thead = "<tr><th>Material</th>";
    for (const m of momentos) thead += `<th>${esc(m.label)}</th>`;
    for (const u of unitsPresent) thead += `<th>g/${esc(u)}</th>`;
    thead += "</tr>";

    let tbody = "";
    for (const name of inocNames) {
      tbody += `<tr><td>${esc(name)}</td>`;
      for (const m of momentos) {
        const val = (map[name] && map[name][m.key]) || 0;
        tbody += `<td><input type="number" step="0.5" min="0" data-nombre="${esc(name)}" data-momento="${esc(m.key)}" value="${val}" ${disabled ? "disabled" : ""} style="width:64px"></td>`;
      }
      const mu = catUnitOfInoc(name);
      const g = catGramosOfInoc(name);
      for (const u of unitsPresent) {
        tbody += `<td class="sutil">${u === mu ? (g ? `${catFmtNum(g)} g` : "—") : "—"}</td>`;
      }
      tbody += "</tr>";
    }
    gridHead.innerHTML = thead;
    gridBody.innerHTML = tbody || `<tr><td class="sutil">No hay materiales con flag "inoculante" en el catálogo.</td></tr>`;
  }

  useDefaultChk.addEventListener("change", () => {
    if (!currentScope) return;
    useDefaultByBase[currentScope] = useDefaultChk.checked;
    renderGrid();
  });

  // Cargar etapas (momentos) de forma async antes de poder armar la grilla.
  const ready = Ajuste.apiFetch("/api/alloys/inoc/momentos").then((res) => {
    momentos = res.momentos;
    renderGrid();
  });

  return {
    collect() {
      collectCurrentScopeFromDom();
      const bases = [...container.querySelectorAll("[data-base-chk]")]
        .filter((c) => c.checked).map((c) => c.dataset.baseChk);
      const inoc_default = catNestedMapToEntries(protocolByBase[""] || {});
      const inoc_por_base = {};
      for (const b of bases) {
        if (useDefaultByBase[b]) continue; // hereda el protocolo por defecto, no se guarda override
        const entries = catNestedMapToEntries(protocolByBase[b] || {});
        if (entries.length) inoc_por_base[b] = entries;
      }
      return {
        bases,
        family: familySel.value,
        defaults: {
          traccion: container.querySelector("#cat-f-traccion").value.trim(),
          seccion: container.querySelector("#cat-f-seccion").value.trim(),
          dureza: container.querySelector("#cat-f-dureza").value.trim(),
          tam_grafito: container.querySelector("#cat-f-tam").value.trim(),
          morfologia: container.querySelector("#cat-f-morf").value.trim(),
          tipo_grafito: container.querySelector("#cat-f-tipo-graf").value.trim(),
          conteo_nodulos: container.querySelector("#cat-f-conteo").value.trim(),
          pct_nodularizacion: container.querySelector("#cat-f-pctnod").value.trim(),
          alargamiento: container.querySelector("#cat-f-alarg").value.trim(),
          perlita: container.querySelector("#cat-f-perlita").value.trim(),
          ferrita: container.querySelector("#cat-f-ferrita").value.trim(),
        },
        inoc_default,
        inoc_por_base,
      };
    },
    ready,
  };
}

function catEntriesToNestedMap(entries) {
  const map = {};
  for (const e of (entries || [])) {
    const nombre = typeof e === "string" ? e : e.nombre;
    const momento = typeof e === "string" ? "horno" : (e.momento || "horno");
    const cant = typeof e === "string" ? 1 : Number(e.cantidad_dosis || 1);
    if (!nombre) continue;
    if (!map[nombre]) map[nombre] = {};
    map[nombre][momento] = cant;
  }
  return map;
}

function catNestedMapToEntries(map) {
  const out = [];
  for (const [nombre, byMomento] of Object.entries(map || {})) {
    for (const [momento, cant] of Object.entries(byMomento)) {
      if (cant > 0) out.push({ nombre, cantidad_dosis: cant, momento });
    }
  }
  return out;
}

// ---------- Vista ----------

VISTAS.catalogo = async () => {
  $("#vista").innerHTML = `
    <div class="encabezado"><h2>Catálogo</h2></div>
    <div class="row" style="align-items:center;">
      <input id="cat-search" type="text" placeholder="Buscar por nombre…" style="width:200px">
      <select id="cat-filter-tipo"><option value="">Todos los tipos</option></select>
      <button id="cat-btn-new" class="primario">Nuevo</button>
    </div>
    <div class="tabla-wrap" style="max-height:70vh;">
      <table>
        <thead>
          <tr>
            <th>Nombre</th><th>Tipo</th><th>Rendimiento %</th><th>Costo</th>
            <th>Ajuste</th><th>Límites</th>
            <th class="col-action">Inoculación</th>
            <th class="col-action">Editar</th>
            <th class="col-action">Duplicar</th>
            <th class="col-action">Eliminar</th>
          </tr>
        </thead>
        <tbody id="cat-rows"></tbody>
      </table>
    </div>`;

  $("#cat-btn-new").addEventListener("click", () => catOpenEditor(null));
  $("#cat-search").addEventListener("input", catRenderRows);
  $("#cat-filter-tipo").addEventListener("change", catRenderRows);

  if (catWsOff) { catWsOff(); catWsOff = null; }

  Ajuste.waitForApproval(async (status) => {
    CAT_CAN_EDIT = status.role === "editor" || status.dev_skip_approval;
    if (!CAT_CAN_EDIT) {
      $("#cat-btn-new").disabled = true;
    }
    await catLoadMeta();
    await catLoadAlloys();
    catWsOff = Ajuste.wsConnect("catalogo", (msg) => {
      if (msg.type === "catalog_changed") catLoadAlloys();
    });
  });
};
