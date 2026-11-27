// calidad.js -- VISTAS.calidad: ABM de informes de control de fundición (ISO 9001). Puerto de
// frontend/js/calidad.js de ajuste_comp_web, PRIMER CORTE (confirmado con el usuario en la app vieja): solo
// el formulario + guardado/listado/grupos/borradores/archivado + generar informe desde una sesión de
// Históricos (ya portado del lado de historicos.js, pega a /api/calidad/material-options y
// /api/calidad/generate-from-session, ambos ya funcionando acá). El análisis OpenCV de imágenes (módulo
// Cámara) y la automatización COM con Access (módulo Fundiciones) van en pasadas aparte -- los botones
// "Cámara"/"Cargar en Access"/etc. ya están en la pantalla (son parte del layout real) pero sus endpoints
// (/camara.html, /api/fundiciones/*) todavía no existen, van a fallar con 404/no encontrado hasta que se
// porten esos módulos, igual que ya pasó con /api/kiosk/snapshot en ajuste.js antes de portar Kiosko.
//
// Todos los nombres top-level de este archivo llevan prefijo cal/_cal -- el shell del núcleo concatena los
// scripts de todas las pantallas en UN solo scope global sin import/export, y una `function` repetida pisa en
// silencio a la anterior sin que ningún test lo detecte (a diferencia de let/const, que test_pantallas.py sí
// cacha). Mismo criterio que ya usaron historicos.js (hist/_hist) y termico.js (term/_term).
const GRAPHITE_TYPE_OPTIONS = [
  "A", "A 100%", "A95/B05", "A 95% / B 5%", "A90/B10", "A 90% / B 10%",
  "A85/B15", "A 85% / B 15%", "A80/B20", "A95/C05", "A90/C10", "A90", "A-B",
];
const GRAPHITE_SIZE_OPTIONS = [
  "1", "1-2", "2", "2-1", "2-3", "3", "3-2", "3-4", "4", "4-3", "4-5", "4-6",
  "5", "5-4", "5-6", "6", "6-4", "6-5", "6-7", "7", "7-6", "7-8", "8", "8-7",
];

const CAL_FIELD_IDS = [
  "fecha", "lote", "informe", "ce_final", "c_final", "si_final",
  "traccion", "traccion_real", "dureza", "conteo_nodulos", "pct_nodularizacion",
  "alargamiento", "estiramiento_real", "tension_real_lim_prop", "mg_disuelto", "perlita", "ferrita",
];

let calEls = {};
let calCatalog = { bases: [], base_to_materials: {}, materials: {} };
let calReports = [];
let calCanEdit = false;
let calSelected = null; // {type:"report", id} | {type:"group", base, lote} | null (nuevo)
let calCurrentImages = [];
let calLastMicroField = null;
let calDraftTimer = null;
let calSuppressChange = false;

function _calFmtNum(n, decimals = 2) {
  if (n === null || n === undefined || n === "" || !Number.isFinite(Number(n))) return "";
  const v = Number(n);
  let s = v.toFixed(decimals);
  if (s.includes(".")) s = s.replace(/0+$/, "").replace(/\.$/, "");
  return s;
}

// ---------- catálogo / combos dependientes ----------

async function _calLoadCatalog() {
  calCatalog = await Ajuste.apiFetch("/api/calidad/catalog");
  calEls.base.innerHTML = calCatalog.bases.map((b) => `<option value="${esc(b)}">${esc(b)}</option>`).join("");
  calEls.tam_grafito.innerHTML = `<option value=""></option>` + GRAPHITE_SIZE_OPTIONS.map((o) => `<option value="${o}">${o}</option>`).join("");
  calEls.tipo_grafito.innerHTML = `<option value=""></option>` + GRAPHITE_TYPE_OPTIONS.map((o) => `<option value="${o}">${o}</option>`).join("");
}

function _calFamilyForMaterial(material) {
  return (calCatalog.materials[material] || {}).family || "";
}

function _calMaterialsForBase(base) {
  return calCatalog.base_to_materials[base] || [];
}

function _calSyncMaterialsOptions() {
  const base = calEls.base.value;
  const materials = _calMaterialsForBase(base);
  const current = calEls.material.value;
  calEls.material.innerHTML = materials.map((m) => `<option value="${esc(m)}">${esc(m)}</option>`).join("");
  if (materials.includes(current)) calEls.material.value = current;
  else if (materials.length) calEls.material.value = materials[0];
  _calSyncSectionOptions();
  _calSyncFamilyFields();
}

function _calSyncSectionOptions() {
  const material = calEls.material.value;
  const entry = calCatalog.materials[material];
  const options = (entry && entry.section_options) || [];
  const current = calEls.seccion.value;
  calEls.seccion.innerHTML = options.map((o) => `<option value="${esc(o)}">${esc(o)}</option>`).join("");
  if (options.includes(current)) calEls.seccion.value = current;
  else if (entry) calEls.seccion.value = entry.default_section || "";
}

function _calSyncFamilyFields() {
  const family = _calFamilyForMaterial(calEls.material.value);
  const nod = family === "Nodular";
  const gris = family === "Gris";
  calEls.lblMorfologia.style.display = nod ? "none" : "";
  if (nod) calEls.morfologia.value = "";
  calEls.lblTipoGrafito.style.display = gris ? "" : "none";
  if (!gris) calEls.tipo_grafito.value = "";
  calEls.lblConteoNodulos.style.display = nod ? "" : "none";
  calEls.lblPctNod.style.display = nod ? "" : "none";
  calEls.lblAlargamiento.style.display = nod ? "" : "none";
  calEls.lblEstiramientoReal.style.display = nod ? "" : "none";
  calEls.lblTensionRealLimProp.style.display = nod ? "" : "none";
  calEls.lblMgDisuelto.style.display = nod ? "" : "none";
  if (!nod) {
    calEls.conteo_nodulos.value = ""; calEls.pct_nodularizacion.value = ""; calEls.alargamiento.value = "";
    calEls.estiramiento_real.value = ""; calEls.tension_real_lim_prop.value = ""; calEls.mg_disuelto.value = "";
  }
}

function _calApplyMaterialDefaults(force) {
  const material = calEls.material.value;
  const entry = calCatalog.materials[material];
  const defaults = (entry && entry.defaults) || {};
  _calSyncSectionOptions();
  const setIfEmpty = (el, key) => { if (force || !el.value.trim()) el.value = defaults[key] || ""; };
  setIfEmpty(calEls.traccion, "traccion");
  setIfEmpty(calEls.dureza, "dureza");
  setIfEmpty(calEls.alargamiento, "alargamiento");
  setIfEmpty(calEls.conteo_nodulos, "conteo_nodulos");
  setIfEmpty(calEls.pct_nodularizacion, "pct_nodularizacion");
  setIfEmpty(calEls.tam_grafito, "tam_grafito");
  if (_calFamilyForMaterial(material) === "Nodular") calEls.morfologia.value = "";
  else setIfEmpty(calEls.morfologia, "morfologia");
  setIfEmpty(calEls.tipo_grafito, "tipo_grafito");
  setIfEmpty(calEls.perlita, "perlita");
  setIfEmpty(calEls.ferrita, "ferrita");
  _calUpdateMicrostructure();
}

// ---------- perlita / ferrita / matriz (reactivo) ----------

function _calParseOptFloat(el) {
  const raw = (el.value || "").trim().replace(",", ".");
  if (!raw) return null;
  const v = parseFloat(raw);
  return Number.isFinite(v) ? v : null;
}

function _calUpdateMicrostructure() {
  let perlita = _calParseOptFloat(calEls.perlita);
  let ferrita = _calParseOptFloat(calEls.ferrita);
  const field = calLastMicroField;

  if (field === "perlita" && perlita !== null) {
    perlita = Math.max(0, Math.min(100, perlita));
    ferrita = Math.max(0, 100 - perlita);
    calEls.perlita.value = _calFmtNum(perlita);
    calEls.ferrita.value = _calFmtNum(ferrita);
  } else if (field === "ferrita" && ferrita !== null) {
    ferrita = Math.max(0, Math.min(100, ferrita));
    perlita = Math.max(0, 100 - ferrita);
    calEls.ferrita.value = _calFmtNum(ferrita);
    calEls.perlita.value = _calFmtNum(perlita);
  }

  perlita = _calParseOptFloat(calEls.perlita);
  ferrita = _calParseOptFloat(calEls.ferrita);
  let matriz = "";
  if (perlita !== null && ferrita !== null && Math.abs((perlita + ferrita) - 100) <= 1e-6) {
    if (perlita >= 100 - 1e-6) matriz = "Perlitico";
    else if (ferrita >= 100 - 1e-6) matriz = "Ferritico";
    else if (perlita >= ferrita) matriz = "Perlita";
    else matriz = "Ferrita";
  }
  calEls.matriz.value = matriz;
}

// ---------- borrador (autosave) ----------

function _calFormPayload() {
  const payload = { base: calEls.base.value, material: calEls.material.value };
  for (const key of CAL_FIELD_IDS) payload[key] = calEls[key] ? calEls[key].value.trim() : "";
  payload.tam_grafito = calEls.tam_grafito.value;
  payload.tipo_grafito = calEls.tipo_grafito.value;
  payload.seccion = calEls.seccion.value;
  payload.morfologia = calEls.material && _calFamilyForMaterial(calEls.material.value) === "Nodular" ? "" : calEls.morfologia.value;
  payload.matriz = calEls.matriz.value;
  payload.datos = calEls.datos.value.trim();
  return payload;
}

function _calScheduleDraftSave() {
  if (calSuppressChange || !calCanEdit) return;
  if (!calSelected) return; // informe nuevo (sin guardar todavía): no autoguarda, igual que el original
  if (calDraftTimer) clearTimeout(calDraftTimer);
  calDraftTimer = setTimeout(_calFireDraftSave, 500);
}

async function _calFireDraftSave() {
  calDraftTimer = null;
  const patch = _calFormPayload();
  try {
    if (calSelected.type === "report") {
      const updated = await Ajuste.apiFetch(`/api/calidad/reports/${calSelected.id}`, {
        method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ patch }),
      });
      _calApplyReportToList(updated);
    } else if (calSelected.type === "group") {
      await Ajuste.apiFetch("/api/calidad/reports/group/draft", {
        method: "PATCH", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base: calSelected.base, lote: calSelected.lote, patch }),
      });
      await _calLoadReports({ preserveSelection: true });
    }
    _calSetDraftBanner(true);
  } catch (ex) {
    avisar(`No se pudo autoguardar: ${ex.message}`, true);
  }
}

function _calApplyReportToList(updated) {
  const idx = calReports.findIndex((r) => r.id === updated.id);
  if (idx >= 0) calReports[idx] = updated;
  _calRenderTree();
}

function _calSetDraftBanner(pending) {
  calEls.draftBanner.style.display = pending ? "block" : "none";
}

// ---------- árbol de informes ----------

function _calGroupKey(base, lote) { return `${base} ${lote}`; }

// La sintaxis del buscador (número exacto, rango "91:95", ventana "91L5", texto libre) vive en
// colada_search.js (global ColadaSearch), compartida con Históricos.
function _calBuildGroups() {
  const query = (calEls.searchInformes.value || "").trim();
  // Buscando: mira archivados y no archivados por igual, sin importar el checkbox -- el checkbox solo manda
  // cuando no hay búsqueda activa.
  const visible = query ? calReports : (calEls.chkArchived.checked ? calReports : calReports.filter((r) => !r.archived));
  const groups = new Map();
  for (const r of visible) {
    const key = _calGroupKey(r.base, r.lote);
    if (!groups.has(key)) groups.set(key, { base: r.base, lote: r.lote, base_display: r.base_display || r.base, reports: [] });
    groups.get(key).reports.push(r);
  }
  let list = [...groups.values()];
  list.sort((a, b) => {
    const fa = a.reports[0]?.fecha || "", fb = b.reports[0]?.fecha || "";
    if (a.lote !== b.lote) return a.lote < b.lote ? -1 : 1;
    if (a.base !== b.base) return a.base < b.base ? -1 : 1;
    return fa < fb ? -1 : fa > fb ? 1 : 0;
  });
  for (const g of list) g.reports.sort((a, b) => String(a.material).localeCompare(String(b.material)));
  if (query) {
    list = ColadaSearch.filterByColadaQuery(list, query, (g) => g.lote,
      (g) => [g.base, g.base_display, ...g.reports.map((r) => `${r.informe || ""} ${r.material || ""}`)].join(" "));
  }
  return list;
}

function _calFamilyForGroup(reports) {
  const families = [...new Set(reports.map((r) => r._family_resolved || r.family).filter(Boolean))];
  if (!families.length) return "";
  return families.length === 1 ? families[0] : "Mixto";
}

function _calRenderTree() {
  const groups = _calBuildGroups();
  calEls.tree.innerHTML = groups.map((g) => {
    const family = _calFamilyForGroup(g.reports);
    const groupActive = calSelected && calSelected.type === "group" && calSelected.base === g.base && calSelected.lote === g.lote;
    const anyDraft = g.reports.some((r) => r._draft_pending);
    return `<div class="qc-tree-group">
      <div class="qc-tree-group-head${groupActive ? " active" : ""}" data-group-base="${esc(g.base)}" data-group-lote="${esc(g.lote)}">
        <span class="qc-tree-group-title">Base ${esc(g.base_display)} — ${esc(g.lote)}</span>
        <span class="qc-tree-group-meta">${esc(family)}${anyDraft ? " · borrador" : ""} · ${g.reports.length} informe(s)</span>
      </div>
      ${g.reports.map((r) => {
        const active = calSelected && calSelected.type === "report" && calSelected.id === r.id;
        const dotClass = r._draft_pending ? "qc-dot-draft" : (r._completeness === "complete" ? "qc-dot-complete" : "qc-dot-incomplete");
        const labIndicator = String(r.traccion_real ?? "").trim()
          ? '<span class="qc-lab-complete" title="Tracción real Lab cargada" aria-label="Tracción real Lab cargada">Lab ✓</span>'
          : "";
        return `<div class="qc-tree-report${active ? " active" : ""}" data-report-id="${esc(r.id)}">
          <span class="qc-dot ${dotClass}"></span>
          <span class="qc-tree-report-name">Material ${esc(r.material)}</span>
          ${labIndicator}
          <span class="qc-tree-report-informe" title="${esc(r.informe || "")}">${esc(r.informe || "")}</span>
        </div>`;
      }).join("")}
    </div>`;
  }).join("") || `<p class="sutil">${(calEls.searchInformes.value || "").trim() ? "Sin informes que coincidan con la búsqueda." : "Sin informes cargados todavía."}</p>`;

  calEls.tree.querySelectorAll("[data-group-base]").forEach((el) => {
    el.addEventListener("click", () => _calLoadGroup(el.dataset.groupBase, el.dataset.groupLote));
  });
  calEls.tree.querySelectorAll("[data-report-id]").forEach((el) => {
    el.addEventListener("click", () => _calLoadReport(el.dataset.reportId));
  });
}

// ---------- carga / limpieza de formulario ----------

function _calClearForm() {
  calSuppressChange = true;
  calSelected = null;
  calEls.fecha.value = new Date().toISOString().slice(0, 10);
  calEls.base.value = calCatalog.bases[0] || "";
  _calSyncMaterialsOptions();
  _calApplyMaterialDefaults(true);
  calEls.lote.value = "";
  calEls.informe.value = "";
  calEls.ce_final.value = "";
  calEls.c_final.value = "";
  calEls.si_final.value = "";
  calEls.traccion_real.value = "";
  calEls.datos.value = "";
  calCurrentImages = [];
  _calRenderImages();
  _calSetModeBanner(null);
  _calSetDraftBanner(false);
  calSuppressChange = false;
}

function _calFillFormFromReport(r) {
  calSuppressChange = true;
  calEls.fecha.value = r.fecha || "";
  calEls.base.value = r.base || "";
  _calSyncMaterialsOptions();
  calEls.material.value = r.material || "";
  _calSyncSectionOptions();
  calEls.seccion.value = r.seccion || "";
  calEls.lote.value = r.lote || "";
  calEls.informe.value = r.informe || "";
  calEls.ce_final.value = r.ce_final || "";
  calEls.c_final.value = r.c_final || "";
  calEls.si_final.value = r.si_final || "";
  calEls.traccion.value = r.traccion || "";
  calEls.traccion_real.value = r.traccion_real || "";
  calEls.dureza.value = r.dureza || "";
  calEls.tam_grafito.value = r.tam_grafito || "";
  calEls.morfologia.value = r.morfologia || "";
  calEls.tipo_grafito.value = r.tipo_grafito || "";
  calEls.conteo_nodulos.value = r.conteo_nodulos || "";
  calEls.pct_nodularizacion.value = r.pct_nodularizacion || "";
  calEls.alargamiento.value = r.alargamiento || "";
  calEls.estiramiento_real.value = r.estiramiento_real || "";
  calEls.tension_real_lim_prop.value = r.tension_real_lim_prop || "";
  calEls.mg_disuelto.value = r.mg_disuelto || "";
  calEls.perlita.value = r.perlita || "";
  calEls.ferrita.value = r.ferrita || "";
  calEls.matriz.value = r.matriz || "";
  _calSyncFamilyFields();
  _calUpdateMicrostructure();
  calEls.datos.value = r.datos || "";
  calCurrentImages = r.imagenes || [];
  _calRenderImages();
  calSuppressChange = false;
}

function _calSetModeBanner(text) {
  if (text) { calEls.modeBanner.textContent = text; calEls.modeBanner.style.display = "block"; }
  else { calEls.modeBanner.style.display = "none"; }
  calEls.material.disabled = !!text;
}

function _calLoadReport(id) {
  const r = calReports.find((x) => x.id === id);
  if (!r) return;
  calSelected = { type: "report", id };
  _calFillFormFromReport(r);
  _calSetModeBanner(null);
  _calSetDraftBanner(!!r._draft_pending);
  _calRenderTree();
}

function _calLoadGroup(base, lote) {
  const reports = calReports.filter((r) => r.base === base && r.lote === lote);
  if (!reports.length) return;
  calSelected = { type: "group", base, lote };
  _calFillFormFromReport(reports[0]);
  calEls.informe.value = _calInformeGroupBase(reports[0]);
  const mats = reports.map((r) => r.material).sort().join(", ");
  _calSetModeBanner(`Modo grupo: estás editando TODO el grupo Base ${base} / ${lote}. Los cambios se aplican a todos los materiales: ${mats}`);
  _calSetDraftBanner(reports.some((r) => r._draft_pending));
  calCurrentImages = [];
  _calRenderImages();
  _calRenderTree();
}

function _calInformeGroupBase(report) {
  return String(report.informe || "").replace(/\s*-\s*mat\s+\S+\s*$/, "").trim();
}

// ---------- imágenes ----------

function _calRenderImages() {
  calEls.imagesRows.innerHTML = calCurrentImages.map((img) => `<tr data-img-id="${esc(img.id)}">
    <td>${esc(img.nombre)}</td>
    <td>${esc(img.comentario || "")}</td>
    <td class="col-action"><button type="button" data-view-img="${esc(img.id)}">Ver</button></td>
    <td class="col-action"><button type="button" data-del-img="${esc(img.id)}" class="peligro">Quitar</button></td>
  </tr>`).join("") || `<tr><td colspan="4" class="sutil">Sin imágenes.</td></tr>`;

  calEls.imagesRows.querySelectorAll("[data-view-img]").forEach((btn) => {
    btn.addEventListener("click", () => {
      const img = calCurrentImages.find((i) => i.id === btn.dataset.viewImg);
      if (!img) return;
      const filename = img.path.split(/[\\/]/).pop();
      calEls.imagePreview.innerHTML = `<img src="/api/calidad/images/${encodeURIComponent(filename)}" alt="${esc(img.nombre)}">`;
    });
  });
  calEls.imagesRows.querySelectorAll("[data-del-img]").forEach((btn) => {
    btn.addEventListener("click", async () => {
      if (!calSelected || calSelected.type !== "report") return;
      if (!confirm("¿Quitar esta imagen del informe?")) return;
      await Ajuste.apiFetch(`/api/calidad/reports/${calSelected.id}/images/${btn.dataset.delImg}`, { method: "DELETE" });
      await _calReloadSelectedReport();
    });
  });
}

async function _calReloadSelectedReport() {
  await _calLoadReports({ preserveSelection: true });
}

// ---------- Conversión durómetro Brinell: mm de identación → HB ----------
// Tabla copiada tal cual de dureza.xlsx (planilla del laboratorio) -- tabla de referencia fija, no cambia,
// por eso vive como constante acá y no como algo que se carga del backend.
const CAL_BRINELL_TABLE = [
  [3.30, 341], [3.35, 331], [3.40, 321], [3.45, 311], [3.50, 302],
  [3.55, 293], [3.60, 285], [3.65, 277], [3.70, 269], [3.75, 262],
  [3.80, 255], [3.85, 248], [3.90, 241], [3.95, 235], [4.00, 229],
  [4.05, 223], [4.10, 217], [4.15, 212], [4.20, 207], [4.25, 201],
  [4.30, 197], [4.35, 192], [4.40, 187], [4.45, 183], [4.50, 179],
  [4.55, 174], [4.60, 170], [4.65, 167], [4.70, 163], [4.75, 159],
  [4.80, 156], [4.85, 152], [4.90, 149], [4.95, 146], [5.00, 143],
  [5.05, 140], [5.10, 137], [5.15, 134], [5.20, 131], [5.25, 128],
  [5.30, 126], [5.35, 123],
];

// Interpolación lineal entre los dos puntos tabulados que rodean el mm medido. Fuera del rango de la tabla NO
// se extrapola -- devuelve outOfRange en vez de inventar un número.
function _calInterpolateHB(mm) {
  const t = CAL_BRINELL_TABLE;
  if (!(mm > 0) || !isFinite(mm)) return { value: null, outOfRange: false };
  if (mm < t[0][0] || mm > t[t.length - 1][0]) return { value: null, outOfRange: true };
  for (let i = 0; i < t.length - 1; i++) {
    const [mm1, hb1] = t[i], [mm2, hb2] = t[i + 1];
    if (mm >= mm1 && mm <= mm2) {
      const frac = (mm - mm1) / (mm2 - mm1);
      return { value: hb1 + frac * (hb2 - hb1), outOfRange: false };
    }
  }
  return { value: null, outOfRange: true };
}

function _calOpenDurezaHbModal() {
  abrirModal(`
    <h2>Dureza Brinell — mm → HB</h2>
    <p class="sutil">Diámetro de la identación medido con el durómetro (tabla de dureza.xlsx del laboratorio).</p>
    <div class="row" style="align-items:flex-end;gap:8px;">
      <label style="flex:1;">Diámetro (mm)<br><input id="dh-mm" type="number" step="0.01" min="0" style="width:100%;"></label>
      <div style="flex:1;">
        <div class="sutil" style="margin:0 0 4px;">Dureza (HB)</div>
        <div id="dh-result" style="font-size:1.4rem;font-weight:700;">—</div>
      </div>
    </div>
    <div id="dh-warning" class="error" style="margin-top:4px;"></div>
    <div class="botones" style="justify-content:flex-end;margin-top:10px;">
      <button type="button" id="dh-cancel">Cerrar</button>
      <button type="button" id="dh-use" class="primario" disabled>Usar este valor</button>
    </div>
    <details style="margin-top:14px;">
      <summary class="sutil" style="cursor:pointer;">Ver tabla completa</summary>
      <div style="margin-top:6px;max-height:280px;overflow-y:auto;border:1px solid var(--borde);border-radius:6px;padding:4px 8px;">
        <table style="width:100%;font-size:0.82rem;">
          <thead><tr><th>mm</th><th>HB</th></tr></thead>
          <tbody>${CAL_BRINELL_TABLE.map(([mm, hb]) => `<tr><td>${mm.toFixed(2)}</td><td>${hb}</td></tr>`).join("")}</tbody>
        </table>
      </div>
    </details>`, true);
  const mmInput = document.getElementById("dh-mm");
  const resultEl = document.getElementById("dh-result");
  const warningEl = document.getElementById("dh-warning");
  const useBtn = document.getElementById("dh-use");
  let currentHB = null;

  mmInput.addEventListener("input", () => {
    const mm = parseFloat(mmInput.value);
    const { value, outOfRange } = _calInterpolateHB(mm);
    currentHB = value != null ? Math.round(value) : null;
    resultEl.textContent = currentHB != null ? String(currentHB) : "—";
    warningEl.textContent = outOfRange ? `Fuera del rango de la tabla (${CAL_BRINELL_TABLE[0][0]}–${CAL_BRINELL_TABLE[CAL_BRINELL_TABLE.length - 1][0]} mm) — no se puede convertir.` : "";
    useBtn.disabled = currentHB == null;
  });
  document.getElementById("dh-cancel").onclick = cerrarModal;
  useBtn.onclick = () => {
    if (currentHB == null) return;
    calEls.dureza.value = String(currentHB);
    _calScheduleDraftSave();
    cerrarModal();
  };
  mmInput.focus();
}

// ---------- Conversión tracción: MPa → kg/mm² ----------
// 1 kgf/mm² = 9.80665 MPa por definición -- factor fijo, no una tabla como Brinell.
const CAL_KGF_PER_MPA = 1 / 9.80665;

function _calOpenMpaToKgModal(targetInput, fieldLabel) {
  abrirModal(`
    <h2>${esc(fieldLabel)} — MPa → kg/mm²</h2>
    <p class="sutil">Valor medido/informado en MPa (1 kgf/mm² = 9,80665 MPa).</p>
    <div class="row" style="align-items:flex-end;gap:8px;">
      <label style="flex:1;">MPa<br><input id="tm-mpa" type="number" step="0.01" min="0" style="width:100%;"></label>
      <div style="flex:1;">
        <div class="sutil" style="margin:0 0 4px;">kg/mm²</div>
        <div id="tm-result" style="font-size:1.4rem;font-weight:700;">—</div>
      </div>
    </div>
    <div class="botones" style="justify-content:flex-end;margin-top:10px;">
      <button type="button" id="tm-cancel">Cerrar</button>
      <button type="button" id="tm-use" class="primario" disabled>Usar este valor</button>
    </div>`);
  const mpaInput = document.getElementById("tm-mpa");
  const resultEl = document.getElementById("tm-result");
  const useBtn = document.getElementById("tm-use");
  let currentKg = null;

  mpaInput.addEventListener("input", () => {
    const mpa = parseFloat(mpaInput.value);
    currentKg = (mpa > 0 && isFinite(mpa)) ? mpa * CAL_KGF_PER_MPA : null;
    resultEl.textContent = currentKg != null ? currentKg.toFixed(2) : "—";
    useBtn.disabled = currentKg == null;
  });
  document.getElementById("tm-cancel").onclick = cerrarModal;
  useBtn.onclick = () => {
    if (currentKg == null) return;
    targetInput.value = currentKg.toFixed(2);
    _calScheduleDraftSave();
    cerrarModal();
  };
  mpaInput.focus();
}

// ---------- Imprimir grupos (etiqueta compacta, hasta 3 por hoja) ----------
// Misma idea que el original: hasta 3 grupos codificados por color en una hoja A4, pensada para cortar y
// pegar en la pieza. La SELECCIÓN de qué imprimir usa un modal normal (abrirModal); el documento final es una
// ventana nueva con document.write + CSS fijo propio del papel impreso (no las variables del tema de la app
// -- es un documento que se imprime, no una pantalla), igual patrón que el resto de "imprimir" en esta app
// (ver herramientas.js, "orden de armado").
function _calPrintedGraphiteText(r) {
  const family = r._family_resolved || r.family || "";
  if (family === "Nodular") {
    const count = String(r.conteo_nodulos || "").trim();
    return count ? `Nodular    nodulos/mm2 = ${count}` : "Nodular";
  }
  return String(r.tipo_grafito || r.morfologia || "").trim();
}

function _calPrintMicroRows(r) {
  const perlita = parseFloat(String(r.perlita || "").replace(",", "."));
  const ferrita = parseFloat(String(r.ferrita || "").replace(",", "."));
  const hasPerlita = Number.isFinite(perlita);
  const hasFerrita = Number.isFinite(ferrita);
  if (!hasPerlita && !hasFerrita) return ["", ""];
  if (hasPerlita && perlita === 100) return ["Perlitico", ""];
  if (hasFerrita && ferrita === 100) return ["Ferritico", ""];
  const items = [];
  if (hasPerlita) items.push(["Perlita", perlita, 0]);
  if (hasFerrita) items.push(["Ferrita", ferrita, 1]);
  items.sort((a, b) => (b[1] - a[1]) || (a[2] - b[2]));
  const pctText = (label, value) => {
    const rounded = Math.round(value);
    return Math.abs(value - rounded) < 0.0001 ? `${label} ${rounded}%` : `${label} ${value.toFixed(1)}%`;
  };
  const lines = items.map(([label, value]) => pctText(label, value));
  while (lines.length < 2) lines.push("");
  return lines.slice(0, 2);
}

function _calDarkenHex(hex, factor = 0.65) {
  const raw = String(hex || "").replace("#", "");
  if (raw.length !== 6) return "#111111";
  const r = Math.max(0, Math.min(255, Math.round(parseInt(raw.slice(0, 2), 16) * factor)));
  const g = Math.max(0, Math.min(255, Math.round(parseInt(raw.slice(2, 4), 16) * factor)));
  const b = Math.max(0, Math.min(255, Math.round(parseInt(raw.slice(4, 6), 16) * factor)));
  return `#${r.toString(16).padStart(2, "0")}${g.toString(16).padStart(2, "0")}${b.toString(16).padStart(2, "0")}`;
}

function _calRenderPrintImagesHtml(reports) {
  const figures = [];
  for (const r of reports) {
    const material = String(r.material || "").trim();
    for (const img of (r.imagenes || [])) {
      const filename = String(img.path || "").split(/[\\/]/).pop();
      if (!filename) continue;
      const src = `/api/calidad/images/${encodeURIComponent(filename)}`;
      const captionParts = [];
      if (material) captionParts.push(`Mat ${material}`);
      captionParts.push((img.comentario || "").trim() || img.nombre || "Imagen");
      const caption = captionParts.join(" - ");
      figures.push(`<figure><img src="${esc(src)}" alt="${esc(caption)}"><figcaption>${esc(caption)}</figcaption></figure>`);
    }
  }
  if (!figures.length) return "";
  return `<div class="images-block"><div class="images-title">Imágenes adjuntas</div>${figures.join("")}</div>`;
}

function _calRenderPrintGroupHtml(group, groupColor, includeImages) {
  const reports = group.reports;
  const family = _calFamilyForGroup(reports);
  const first = reports[0] || {};
  const leftRows = [
    ["base", String(group.base_display || group.base || "")],
    ["ce", String(first.ce_final || "")],
    ["c", String(first.c_final || "")],
    ["si", String(first.si_final || "")],
  ];
  const materialRows = [];
  for (const r of reports) {
    const [micro1, micro2] = _calPrintMicroRows(r);
    materialRows.push([`material ${r.material || ""}`, "", "Tamaño", String(r.tam_grafito || "")]);
    materialRows.push(["tipo grafito", _calPrintedGraphiteText(r), micro1, ""]);
    materialRows.push(["HB", String(r.dureza || ""), micro2, ""]);
  }
  const rowCount = Math.max(leftRows.length, materialRows.length);
  const rowsHtml = [];
  for (let i = 0; i < rowCount; i++) {
    const [leftLabel, leftValue] = leftRows[i] || ["", ""];
    const [matLabel, matValue, rightLabel, rightValue] = materialRows[i] || ["", "", "", ""];
    const leftBlock = i === 0
      ? `<th class="group-title" colspan="2">colada ${esc(group.lote)}</th>` +
        `<td class="mat-cell"><span class="cell-label">${esc(matLabel)}</span><span class="cell-value">${esc(matValue)}</span></td>` +
        `<td class="prop-cell"><span class="cell-label">${esc(rightLabel)}</span><span class="cell-value">${esc(rightValue)}</span></td>`
      : `<th class="left-label">${esc(leftLabel)}</th><td class="left-value">${esc(leftValue)}</td>` +
        `<td class="mat-cell"><span class="cell-label">${esc(matLabel)}</span><span class="cell-value">${esc(matValue)}</span></td>` +
        `<td class="prop-cell"><span class="cell-label">${esc(rightLabel)}</span><span class="cell-value">${esc(rightValue)}</span></td>`;
    const rowClass = (i > 0 && matLabel.startsWith("material ")) ? ' class="material-sep"' : "";
    rowsHtml.push(`<tr${rowClass}>${leftBlock}</tr>`);
  }
  const familyLine = family ? `<div class="group-family">${esc(family)}</div>` : "";
  const imagesBlock = includeImages ? _calRenderPrintImagesHtml(reports) : "";
  return `<section class="group-report" style="color:${esc(groupColor)}; --group-line:${esc(_calDarkenHex(groupColor))};">
    ${familyLine}
    <table class="group-table">${rowsHtml.join("")}</table>
    ${imagesBlock}
  </section>`;
}

const CAL_PRINT_GROUP_COLORS = ["#1f4ea3", "#b03a2e", "#2e8b57"];

function _calBuildGroupsPrintDocument(groups, includeImages) {
  const pages = [];
  let previousDate = null;
  for (let start = 0; start < groups.length; start += 3) {
    const chunk = groups.slice(start, start + 3);
    const parts = [];
    for (let idx = 0; idx < chunk.length; idx++) {
      const g = chunk[idx];
      const groupDate = String((g.reports[0] || {}).fecha || "").slice(0, 10);
      if (groupDate && groupDate !== previousDate) {
        parts.push(`<div class="date-header">${esc(groupDate)}</div>`);
        previousDate = groupDate;
      }
      parts.push(_calRenderPrintGroupHtml(g, CAL_PRINT_GROUP_COLORS[idx] || "#111111", includeImages));
    }
    pages.push(`<div class="page">${parts.join("")}</div>`);
  }
  return `<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Informes de calidad</title>
<style>
  @page { size: A4 portrait; margin: 14mm 8mm 8mm 8mm; }
  body { margin: 0; font-family: "Segoe UI", Arial, sans-serif; color: #111; background: #f2f2f2; }
  .page { width: 194mm; min-height: 281mm; margin: 0 auto 6mm auto; background: #fff; box-sizing: border-box; page-break-after: always; padding: 4mm 0 0 0; }
  .page:last-child { page-break-after: auto; }
  .date-header { margin: 0; padding: 1mm 1.5mm; font-size: 18px; font-weight: 700; text-align: right; border-top: 2px solid #111; border-bottom: 1px solid #777; background: #f5f5f5; }
  .page .date-header:first-child { border-top: 0; }
  .group-report { border-top: 3px solid var(--group-line, #111111); border-bottom: 3px solid var(--group-line, #111111); padding: 0; box-sizing: border-box; overflow: hidden; }
  .group-report + .group-report { margin-top: -3px; }
  .group-family { font-size: 15px; font-weight: 700; text-transform: uppercase; margin: 0; padding: 0; line-height: 1; color: #444; }
  .group-table { width: 100%; margin: 0; border-collapse: collapse; font-size: 15px; table-layout: fixed; }
  .group-table th, .group-table td { border: 1px solid #b9b9b9; padding: 1.2mm 1.6mm; text-align: left; vertical-align: middle; }
  .group-title { font-size: 17px; font-weight: 700; background: #fafafa; }
  .left-label { width: 10%; font-weight: 700; background: #fafafa; text-transform: lowercase; }
  .left-value { width: 18%; }
  .mat-cell { width: 42%; border-left: 3px solid var(--group-line, #111111) !important; }
  .prop-cell { width: 30%; }
  .material-sep .mat-cell, .material-sep .prop-cell { border-top: 3px solid var(--group-line, #111111) !important; }
  .cell-label { display: inline-block; min-width: 96px; font-weight: 700; color: var(--group-line, #111111); }
  .cell-value { display: inline-block; }
  .images-block { display: flex; flex-wrap: wrap; gap: 3mm; padding: 2mm 1.5mm 3mm 1.5mm; border-top: 1px solid #b9b9b9; color: #111; }
  .images-title { flex: 0 0 100%; font-size: 12px; font-weight: 700; text-transform: uppercase; color: var(--group-line, #111111); }
  .images-block figure { margin: 0; width: 45mm; break-inside: avoid; }
  .images-block img { width: 45mm; max-height: 38mm; object-fit: contain; border: 1px solid #999; background: #fff; }
  .images-block figcaption { font-size: 10px; line-height: 1.15; color: #333; word-break: break-word; }
</style>
</head>
<body>${pages.join("")}</body>
</html>`;
}

function _calOpenPrintGroupsModal(includeImages) {
  const groups = _calBuildGroups();
  if (!groups.length) { alert("No hay informes para imprimir."); return; }
  const defaultIdxs = new Set(groups.map((_g, i) => i).slice(-3));
  abrirModal(`
    <h2>Imprimir grupos${includeImages ? " (con imágenes)" : ""}</h2>
    <p class="sutil">Seleccioná hasta 3 grupos — podés destildar informes puntuales dentro de un grupo para no incluirlos.</p>
    <div style="max-height:360px;overflow-y:auto;">
      ${groups.map((g, gi) => {
        const checked = defaultIdxs.has(gi);
        const family = _calFamilyForGroup(g.reports);
        const fecha = g.reports[0]?.fecha || "";
        return `<div style="padding:4px 0;">
          <label style="display:block;font-weight:600;">
            <input type="checkbox" data-group-idx="${gi}" ${checked ? "checked" : ""}>
            Base ${esc(g.base_display || g.base)} — ${esc(family)} — ${esc(g.lote)} (${g.reports.length} informe(s), ${esc(fecha)})
          </label>
          <div style="padding-left:22px;">
            ${g.reports.map((r) => {
              const parts = [r.material ? `Material ${r.material}` : "", r.seccion, r.informe].filter(Boolean);
              const subLabel = parts.length ? parts.join(" · ") : "(sin datos)";
              return `<label style="display:block;">
                <input type="checkbox" data-group-idx="${gi}" data-report-id="${esc(r.id)}" ${checked ? "checked" : ""}>
                ${esc(subLabel)}
              </label>`;
            }).join("")}
          </div>
        </div>`;
      }).join("")}
    </div>
    <p id="pg-status" class="sutil" style="margin-top:8px;"></p>
    <div class="botones" style="justify-content:flex-end;margin-top:10px;">
      <button type="button" id="pg-cancel">Cancelar</button>
      <button type="button" id="pg-accept" class="primario">Imprimir</button>
    </div>`, true);

  document.querySelectorAll("[data-group-idx]:not([data-report-id])").forEach((groupCb) => {
    groupCb.addEventListener("change", () => {
      document.querySelectorAll(`[data-report-id][data-group-idx="${groupCb.dataset.groupIdx}"]`).forEach((cb) => {
        cb.checked = groupCb.checked;
      });
    });
  });
  document.querySelectorAll("[data-report-id]").forEach((reportCb) => {
    reportCb.addEventListener("change", () => {
      const idx = reportCb.dataset.groupIdx;
      const groupCb = document.querySelector(`[data-group-idx="${idx}"]:not([data-report-id])`);
      const anyChecked = [...document.querySelectorAll(`[data-report-id][data-group-idx="${idx}"]`)].some((cb) => cb.checked);
      if (groupCb) groupCb.checked = anyChecked;
    });
  });

  document.getElementById("pg-cancel").onclick = cerrarModal;
  document.getElementById("pg-accept").onclick = async () => {
    const chosen = [];
    groups.forEach((g, gi) => {
      const checkedIds = new Set(
        [...document.querySelectorAll(`[data-report-id][data-group-idx="${gi}"]:checked`)].map((cb) => cb.dataset.reportId)
      );
      if (!checkedIds.size) return;
      chosen.push({ base: g.base, lote: g.lote, base_display: g.base_display, reports: g.reports.filter((r) => checkedIds.has(r.id)) });
    });
    if (!chosen.length) { alert("No seleccionaste informes para imprimir."); return; }
    if (chosen.length > 3) { alert("Podés seleccionar hasta 3 grupos."); return; }
    const printHtml = _calBuildGroupsPrintDocument(chosen, includeImages);
    const win = window.open("", "_blank");
    if (!win) { alert("El navegador bloqueó la ventana nueva. Habilitá pop-ups para este sitio."); return; }
    win.document.open();
    win.document.write(printHtml);
    win.document.close();
    const statusEl = document.getElementById("pg-status");
    statusEl.textContent = "Archivando grupos impresos…";
    try {
      let archived = 0;
      for (const g of chosen) {
        const res = await Ajuste.apiFetch("/api/calidad/reports/group/archive", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base: g.base, lote: g.lote }),
        });
        archived += res.archived || 0;
      }
      cerrarModal();
      avisar(`Hoja lista para imprimir generada. Informes archivados: ${archived}.`);
      await _calLoadReports({ preserveSelection: true });
    } catch (ex) {
      statusEl.className = "error";
      statusEl.textContent = `Se abrió la hoja, pero no se pudo archivar: ${ex.message}`;
    }
  };
}

// ---------- Fundiciones (automatización COM de Access) -- fase siguiente ----------
// Los botones existen (son parte real del layout) pero /api/fundiciones/* todavía no está portado -- fallan
// con error de red/404 hasta esa fase, igual que ya pasó con otros endpoints todavía no portados en este
// mismo módulo (ver comentario de cabecera).
async function _calRunFundicionesRequest(button, url, confirmMessage, body) {
  if (confirmMessage && !confirm(confirmMessage)) return;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "Trabajando en Access…";
  avisar("Conectando con Access… esto puede tardar varios segundos.");
  try {
    const opts = { method: "POST" };
    if (body) { opts.headers = { "Content-Type": "application/json" }; opts.body = JSON.stringify(body); }
    const res = await Ajuste.apiFetch(url, opts);
    avisar(res.status || (res.ok ? "Listo." : "No se pudo completar."), !res.ok);
    if (!res.ok) alert(res.status || "No se pudo completar la operación en Access.");
  } catch (err) {
    const message = (err.detail && (err.detail.message || err.detail.error)) || err.message || String(err);
    avisar(`Error: ${message}`, true);
    alert(`No se pudo completar la operación en Access.\n\n${message}`);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function _calRunFundicionesAction(button, action, confirmMessage) {
  if (!calSelected || calSelected.type !== "report") {
    alert("Seleccioná un informe individual (con lote y material completos) antes de enviarlo a Access.");
    return;
  }
  await _calRunFundicionesRequest(button, `/api/fundiciones/reports/${encodeURIComponent(calSelected.id)}/${action}`, confirmMessage);
}

// ---------- carga de datos ----------

async function _calLoadReports({ preserveSelection } = {}) {
  const data = await Ajuste.apiFetch("/api/calidad/reports");
  calReports = data.reports;
  _calRenderTree();
  if (preserveSelection && calSelected) {
    if (calSelected.type === "report") {
      const r = calReports.find((x) => x.id === calSelected.id);
      if (r) { _calFillFormFromReport(r); _calSetDraftBanner(!!r._draft_pending); return; }
    } else if (calSelected.type === "group") {
      const reports = calReports.filter((r) => r.base === calSelected.base && r.lote === calSelected.lote);
      if (reports.length) { _calSetDraftBanner(reports.some((r) => r._draft_pending)); return; }
    }
  }
}

// ---------- Vista ----------

VISTAS.calidad = async () => {
  $("#vista").innerHTML = `
    <div class="encabezado"><h2>Calidad</h2></div>
    <div class="tarjeta">
      <div class="toolbar" style="flex-wrap:wrap;">
        <label style="display:inline-flex;align-items:center;gap:6px;">
          <input type="checkbox" id="cal-chk-archived"> Mostrar archivados
        </label>
        <input type="text" id="cal-search-informes" placeholder="Buscar colada (ej: 91, 91:95, 91L5)" style="width:240px;">
        <span id="cal-search-informes-help" style="cursor:help;" class="sutil">ⓘ</span>
        <button type="button" id="cal-btn-refresh">Refrescar</button>
      </div>
    </div>

    <div class="tarjeta qc-shell">
      <div class="qc-form-pane">
        <div id="cal-mode-banner" class="qc-banner qc-banner-mode" style="display:none;"></div>
        <div id="cal-draft-banner" class="qc-banner qc-banner-draft" style="display:none;">
          Cambios autoguardados sin confirmar. Tocá Guardar para cerrar el borrador.
        </div>

        <div class="qc-form-actions">
          <div class="qc-action-group">
            <span class="qc-action-group-label">Informe</span>
            <div class="qc-action-group-buttons">
              <button type="button" id="cal-btn-new" class="primario">Nuevo</button>
              <button type="button" id="cal-btn-save" class="primario">Guardar</button>
              <button type="button" id="cal-btn-cancel-draft">Cancelar</button>
              <button type="button" id="cal-btn-add-material">Agregar material</button>
            </div>
          </div>
          <div class="qc-action-group">
            <span class="qc-action-group-label">Imágenes</span>
            <div class="qc-action-group-buttons">
              <button type="button" id="cal-btn-camera">Cámara</button>
            </div>
          </div>
          <div class="qc-action-group">
            <span class="qc-action-group-label">Access</span>
            <div class="qc-action-group-buttons">
              <button type="button" id="cal-btn-fundiciones-load">Cargar en Access</button>
              <button type="button" id="cal-btn-fundiciones-review">Abrir en Access</button>
              <button type="button" id="cal-btn-fundiciones-load-all">Cargar TODO en Access</button>
            </div>
          </div>
          <div class="qc-action-group">
            <span class="qc-action-group-label">Grupo</span>
            <div class="qc-action-group-buttons">
              <button type="button" id="cal-btn-archive-group">Archivar grupo</button>
              <button type="button" id="cal-btn-print">Imprimir</button>
              <button type="button" id="cal-btn-print-images">Imprimir con imágenes</button>
            </div>
          </div>
          <div class="qc-action-group qc-action-group-danger">
            <span class="qc-action-group-label">Eliminar</span>
            <div class="qc-action-group-buttons">
              <button type="button" id="cal-btn-delete" class="peligro">Eliminar</button>
              <button type="button" id="cal-btn-delete-group" class="peligro">Eliminar grupo</button>
            </div>
          </div>
        </div>

        <div class="qc-fields-grid">
          <label>Fecha<input id="cal-f-fecha" type="text"></label>
          <label>Base<select id="cal-f-base"></select></label>
          <label>Material<select id="cal-f-material"></select></label>
          <label>Lote / colada<input id="cal-f-lote" type="text"></label>
          <label class="qc-span2">Informe<input id="cal-f-informe" type="text"></label>
        </div>

        <fieldset class="qc-fieldset">
          <legend>Valores finales</legend>
          <div class="qc-fields-grid">
            <label>CE final<input id="cal-f-ce_final" type="text"></label>
            <label>C final<input id="cal-f-c_final" type="text"></label>
            <label>Si final<input id="cal-f-si_final" type="text"></label>
          </div>
        </fieldset>

        <fieldset class="qc-fieldset">
          <legend>Propiedades</legend>
          <div class="qc-fields-grid">
            <label>Tracción (kg/mm²)<input id="cal-f-traccion" type="text"></label>
            <label>Dureza
              <span style="display:flex;gap:4px;">
                <input id="cal-f-dureza" type="text" style="flex:1;min-width:0;">
                <button type="button" id="cal-btn-dureza-hb" title="Convertir mm de identación (durómetro Brinell) a HB">mm→HB</button>
              </span>
            </label>
            <label>Tam grafito<select id="cal-f-tam_grafito"></select></label>
            <label id="cal-lbl-morfologia">Morfología<input id="cal-f-morfologia" type="text" readonly></label>
            <label id="cal-lbl-tipo_grafito">Tipo grafito<select id="cal-f-tipo_grafito"></select></label>
            <label id="cal-lbl-conteo_nodulos">Conteo nódulos<input id="cal-f-conteo_nodulos" type="text"></label>
            <label id="cal-lbl-pct_nodularizacion">% nodularización<input id="cal-f-pct_nodularizacion" type="text"></label>
            <label id="cal-lbl-alargamiento">Alargamiento (%)<input id="cal-f-alargamiento" type="text"></label>
            <label>Perlita %<input id="cal-f-perlita" type="text"></label>
            <label>Ferrita %<input id="cal-f-ferrita" type="text"></label>
            <label>Sección muestra<select id="cal-f-seccion"></select></label>
            <label>Matriz prevalente<input id="cal-f-matriz" type="text" readonly></label>
          </div>
        </fieldset>

        <fieldset class="qc-fieldset">
          <legend>Ensayos</legend>
          <div class="qc-fields-grid">
            <label>Tracción real Lab (kg/mm²)
              <span style="display:flex;gap:4px;">
                <input id="cal-f-traccion_real" type="text" style="flex:1;min-width:0;">
                <button type="button" id="cal-btn-traccion-mpa" title="Convertir un valor medido en MPa a kg/mm²">MPa→kg</button>
              </span>
            </label>
            <label id="cal-lbl-estiramiento_real">Estiramiento real<input id="cal-f-estiramiento_real" type="text"></label>
            <label id="cal-lbl-tension_real_lim_prop">Tensión real lím prop (kg/mm²)
              <span style="display:flex;gap:4px;">
                <input id="cal-f-tension_real_lim_prop" type="text" style="flex:1;min-width:0;">
                <button type="button" id="cal-btn-tension-mpa" title="Convertir un valor medido en MPa a kg/mm²">MPa→kg</button>
              </span>
            </label>
            <label id="cal-lbl-mg_disuelto">Mg disuelto (%)<input id="cal-f-mg_disuelto" type="text"></label>
          </div>
        </fieldset>

        <label class="qc-block">Datos / observaciones
          <textarea id="cal-f-datos" rows="8"></textarea>
        </label>

        <fieldset class="qc-fieldset">
          <legend>Imágenes del informe</legend>
          <div class="qc-images-wrap">
            <table>
              <thead><tr><th>Archivo</th><th>Comentario</th><th class="col-action"></th><th class="col-action"></th></tr></thead>
              <tbody id="cal-images-rows"></tbody>
            </table>
            <div class="row" style="margin-top:8px;">
              <input type="file" id="cal-f-image-upload" accept=".png,.jpg,.jpeg,.bmp,.gif,.webp">
            </div>
            <div id="cal-image-preview" class="qc-image-preview">Sin imagen seleccionada</div>
          </div>
        </fieldset>
      </div>

      <div class="qc-list-pane">
        <div id="cal-reports-tree" class="qc-tree"></div>
      </div>
    </div>`;

  calEls = {
    chkArchived: document.getElementById("cal-chk-archived"),
    searchInformes: document.getElementById("cal-search-informes"),
    searchInformesHelp: document.getElementById("cal-search-informes-help"),
    btnRefresh: document.getElementById("cal-btn-refresh"),
    modeBanner: document.getElementById("cal-mode-banner"),
    draftBanner: document.getElementById("cal-draft-banner"),
    btnNew: document.getElementById("cal-btn-new"),
    btnSave: document.getElementById("cal-btn-save"),
    btnCancelDraft: document.getElementById("cal-btn-cancel-draft"),
    btnAddMaterial: document.getElementById("cal-btn-add-material"),
    btnCamera: document.getElementById("cal-btn-camera"),
    btnFundicionesLoad: document.getElementById("cal-btn-fundiciones-load"),
    btnFundicionesReview: document.getElementById("cal-btn-fundiciones-review"),
    btnFundicionesLoadAll: document.getElementById("cal-btn-fundiciones-load-all"),
    btnArchiveGroup: document.getElementById("cal-btn-archive-group"),
    btnPrint: document.getElementById("cal-btn-print"),
    btnPrintImages: document.getElementById("cal-btn-print-images"),
    btnDelete: document.getElementById("cal-btn-delete"),
    btnDeleteGroup: document.getElementById("cal-btn-delete-group"),
    fecha: document.getElementById("cal-f-fecha"),
    base: document.getElementById("cal-f-base"),
    material: document.getElementById("cal-f-material"),
    lote: document.getElementById("cal-f-lote"),
    informe: document.getElementById("cal-f-informe"),
    ce_final: document.getElementById("cal-f-ce_final"),
    c_final: document.getElementById("cal-f-c_final"),
    si_final: document.getElementById("cal-f-si_final"),
    traccion: document.getElementById("cal-f-traccion"),
    traccion_real: document.getElementById("cal-f-traccion_real"),
    dureza: document.getElementById("cal-f-dureza"),
    btnDurezaHb: document.getElementById("cal-btn-dureza-hb"),
    btnTraccionMpa: document.getElementById("cal-btn-traccion-mpa"),
    btnTensionMpa: document.getElementById("cal-btn-tension-mpa"),
    tam_grafito: document.getElementById("cal-f-tam_grafito"),
    morfologia: document.getElementById("cal-f-morfologia"),
    lblMorfologia: document.getElementById("cal-lbl-morfologia"),
    tipo_grafito: document.getElementById("cal-f-tipo_grafito"),
    lblTipoGrafito: document.getElementById("cal-lbl-tipo_grafito"),
    conteo_nodulos: document.getElementById("cal-f-conteo_nodulos"),
    lblConteoNodulos: document.getElementById("cal-lbl-conteo_nodulos"),
    pct_nodularizacion: document.getElementById("cal-f-pct_nodularizacion"),
    lblPctNod: document.getElementById("cal-lbl-pct_nodularizacion"),
    alargamiento: document.getElementById("cal-f-alargamiento"),
    lblAlargamiento: document.getElementById("cal-lbl-alargamiento"),
    estiramiento_real: document.getElementById("cal-f-estiramiento_real"),
    lblEstiramientoReal: document.getElementById("cal-lbl-estiramiento_real"),
    tension_real_lim_prop: document.getElementById("cal-f-tension_real_lim_prop"),
    lblTensionRealLimProp: document.getElementById("cal-lbl-tension_real_lim_prop"),
    mg_disuelto: document.getElementById("cal-f-mg_disuelto"),
    lblMgDisuelto: document.getElementById("cal-lbl-mg_disuelto"),
    perlita: document.getElementById("cal-f-perlita"),
    ferrita: document.getElementById("cal-f-ferrita"),
    seccion: document.getElementById("cal-f-seccion"),
    matriz: document.getElementById("cal-f-matriz"),
    datos: document.getElementById("cal-f-datos"),
    imagesRows: document.getElementById("cal-images-rows"),
    imageUpload: document.getElementById("cal-f-image-upload"),
    imagePreview: document.getElementById("cal-image-preview"),
    tree: document.getElementById("cal-reports-tree"),
  };

  [["perlita", calEls.perlita], ["ferrita", calEls.ferrita]].forEach(([key, el]) => {
    el.addEventListener("focus", () => { calLastMicroField = key; });
    el.addEventListener("input", () => { _calUpdateMicrostructure(); _calScheduleDraftSave(); });
  });

  calEls.base.addEventListener("change", () => { _calSyncMaterialsOptions(); _calScheduleDraftSave(); });
  calEls.material.addEventListener("change", () => { _calApplyMaterialDefaults(false); _calSyncFamilyFields(); _calScheduleDraftSave(); });

  CAL_FIELD_IDS.forEach((key) => {
    const el = calEls[key];
    if (el && !["perlita", "ferrita"].includes(key)) el.addEventListener("input", _calScheduleDraftSave);
  });
  [calEls.tam_grafito, calEls.tipo_grafito, calEls.seccion, calEls.morfologia].forEach((el) => el.addEventListener("input", _calScheduleDraftSave));
  calEls.datos.addEventListener("input", _calScheduleDraftSave);

  calEls.chkArchived.addEventListener("change", _calRenderTree);
  calEls.searchInformes.addEventListener("input", _calRenderTree);
  calEls.searchInformesHelp.title = ColadaSearch.COLADA_SEARCH_TOOLTIP;
  calEls.btnRefresh.addEventListener("click", () => _calLoadReports({ preserveSelection: true }));
  calEls.btnNew.addEventListener("click", _calClearForm);

  calEls.btnSave.addEventListener("click", async () => {
    try {
      if (calSelected && calSelected.type === "group") {
        await Ajuste.apiFetch("/api/calidad/reports/group", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base: calSelected.base, lote: calSelected.lote, patch: _calFormPayload() }),
        });
        avisar("Grupo guardado.");
        await _calLoadReports({ preserveSelection: true });
        return;
      }
      const payload = _calFormPayload();
      if (calSelected && calSelected.type === "report") payload.id = calSelected.id;
      payload.imagenes = calCurrentImages;
      const saved = await Ajuste.apiFetch("/api/calidad/reports", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload),
      });
      avisar("Informe guardado.");
      calSelected = { type: "report", id: saved.id };
      await _calLoadReports({ preserveSelection: true });
    } catch (ex) {
      avisar(`No se pudo guardar: ${ex.detail?.detail?.error || ex.message}`, true);
    }
  });

  calEls.btnCancelDraft.addEventListener("click", async () => {
    if (!calSelected) { _calClearForm(); return; }
    try {
      if (calSelected.type === "report") {
        await Ajuste.apiFetch(`/api/calidad/reports/${calSelected.id}/cancel-draft`, { method: "POST" });
      } else {
        await Ajuste.apiFetch("/api/calidad/reports/group/cancel-draft", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ base: calSelected.base, lote: calSelected.lote }),
        });
      }
      await _calLoadReports({ preserveSelection: true });
      avisar("Borrador descartado.");
    } catch (ex) {
      avisar(`Error: ${ex.message}`, true);
    }
  });

  calEls.btnDurezaHb.addEventListener("click", _calOpenDurezaHbModal);
  calEls.btnTraccionMpa.addEventListener("click", () => _calOpenMpaToKgModal(calEls.traccion_real, "Tracción real"));
  calEls.btnTensionMpa.addEventListener("click", () => _calOpenMpaToKgModal(calEls.tension_real_lim_prop, "Tensión real lím prop"));

  calEls.btnAddMaterial.addEventListener("click", async () => {
    const groupInfo = calSelected ? (calSelected.type === "group" ? calSelected : calReports.find((r) => r.id === calSelected.id)) : null;
    if (!groupInfo) { alert("Seleccioná un grupo o un material dentro del grupo."); return; }
    const base = groupInfo.base;
    const lote = groupInfo.lote;
    const existingMaterials = new Set(calReports.filter((r) => r.base === base && r.lote === lote).map((r) => r.material));
    const missing = _calMaterialsForBase(base).filter((m) => !existingMaterials.has(m));
    if (!missing.length) { alert("Ese grupo ya tiene todos los materiales posibles."); return; }

    abrirModal(`
      <h2>Agregar materiales — Base ${esc(base)}</h2>
      <p class="sutil">Seleccioná los materiales a agregar:</p>
      <div class="pick-list">${missing.map((m) => `<label><input type="checkbox" value="${esc(m)}" checked> Material ${esc(m)}</label>`).join("")}</div>
      <div class="botones" style="justify-content:flex-end;margin-top:12px;">
        <button type="button" id="am-cancel">Cancelar</button>
        <button type="button" id="am-accept" class="primario">Agregar</button>
      </div>`);
    document.getElementById("am-cancel").onclick = cerrarModal;
    document.getElementById("am-accept").onclick = async () => {
      const materials = [...document.querySelectorAll(".pick-list input[type=checkbox]:checked")].map((c) => c.value);
      if (!materials.length) { cerrarModal(); return; }
      await Ajuste.apiFetch("/api/calidad/reports/group/add-materials", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ base, lote, materials }),
      });
      cerrarModal();
      avisar(`${materials.length} material(es) agregado(s).`);
      await _calLoadReports({ preserveSelection: true });
    };
  });

  calEls.btnCamera.addEventListener("click", () => {
    // La cámara se puede abrir en cualquier momento -- el destino (sesión/material) se elige recién al
    // guardar la foto, con los combos de la propia página de la cámara. Si hay un informe individual ya
    // seleccionado acá, se lo pasa solo como sugerencia para preseleccionar ese destino.
    const hint = (calSelected && calSelected.type === "report") ? `?report_id=${encodeURIComponent(calSelected.id)}` : "";
    window.open(`/camara.html${hint}`, "_blank");
  });

  // Si el usuario abrió la cámara en otra pestaña y guardó una imagen ahí, al volver a esta pestaña se
  // refresca sola en vez de requerir "Refrescar".
  window.addEventListener("focus", () => {
    if (calSelected && calSelected.type === "report") _calLoadReports({ preserveSelection: true });
  });

  calEls.btnFundicionesLoad.addEventListener("click", () => {
    if (calSelected && calSelected.type === "group") {
      const n = (calSelected.reports || []).length;
      _calRunFundicionesRequest(
        calEls.btnFundicionesLoad,
        "/api/fundiciones/reports/group/load",
        `Esto abre Access y carga colada, responsable, fecha y los ${n} materiales del grupo (Base ${calSelected.base} / ${calSelected.lote}), uno atrás del otro. ¿Continuar?`,
        { base: calSelected.base, lote: calSelected.lote },
      );
      return;
    }
    _calRunFundicionesAction(
      calEls.btnFundicionesLoad, "load",
      "Esto abre Access y carga colada, responsable, fecha y el material completo hasta espesores. ¿Continuar?",
    );
  });

  calEls.btnFundicionesReview.addEventListener("click", () => {
    _calRunFundicionesAction(calEls.btnFundicionesReview, "review", null);
  });

  calEls.btnFundicionesLoadAll.addEventListener("click", async () => {
    const groups = _calBuildGroups();
    if (!groups.length) { alert("No hay grupos para cargar."); return; }
    const totalMateriales = groups.reduce((n, g) => n + g.reports.length, 0);
    if (!confirm(
      `Esto abre Access y carga, uno atrás del otro, los ${groups.length} grupo(s) visibles `
      + `(${totalMateriales} material(es) en total). Puede tardar varios minutos. ¿Continuar?`,
    )) return;

    const button = calEls.btnFundicionesLoadAll;
    const originalText = button.textContent;
    button.disabled = true;
    button.textContent = "Trabajando en Access…";
    avisar("Conectando con Access… esto puede tardar varios minutos.");
    try {
      const res = await Ajuste.apiFetch("/api/fundiciones/reports/bulk/load", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ groups: groups.map((g) => ({ base: g.base, lote: g.lote })) }),
      });
      const fallidos = res.results.filter((r) => !r.ok);
      const resumen = `Cargados ${res.results.length - fallidos.length}/${res.results.length} grupo(s).`
        + (fallidos.length ? ` Fallaron: ${fallidos.map((r) => `${r.base}/${r.lote}`).join(", ")}.` : "");
      avisar(resumen, !res.ok);
      if (!res.ok) alert(`${resumen}\n\n${fallidos.map((r) => `${r.base}/${r.lote}: ${r.status}`).join("\n")}`);
    } catch (err) {
      const message = (err.detail && (err.detail.message || err.detail.error)) || err.message || String(err);
      avisar(`Error: ${message}`, true);
      alert(`No se pudo completar la carga en Access.\n\n${message}`);
    } finally {
      button.disabled = false;
      button.textContent = originalText;
    }
  });

  calEls.btnArchiveGroup.addEventListener("click", async () => {
    const info = calSelected ? (calSelected.type === "group" ? calSelected : calReports.find((r) => r.id === calSelected.id)) : null;
    if (!info) { alert("Seleccioná un grupo o un material del grupo."); return; }
    if (!confirm(`¿Archivar el grupo Base ${info.base} / ${info.lote}?`)) return;
    const res = await Ajuste.apiFetch("/api/calidad/reports/group/archive", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ base: info.base, lote: info.lote }),
    });
    avisar(`${res.archived} informe(s) archivado(s).`);
    _calClearForm();
    await _calLoadReports({ preserveSelection: false });
  });

  calEls.btnPrint.addEventListener("click", () => _calOpenPrintGroupsModal(false));
  calEls.btnPrintImages.addEventListener("click", () => _calOpenPrintGroupsModal(true));

  calEls.btnDelete.addEventListener("click", async () => {
    if (!calSelected || calSelected.type !== "report") { alert("Seleccioná un informe individual para eliminar."); return; }
    const motivo = Ajuste.pedirMotivo("¿Eliminar el informe seleccionado?");
    if (motivo === null) return;
    await Ajuste.apiFetch(`/api/calidad/reports/${calSelected.id}`, { method: "DELETE", headers: Ajuste.headersMotivo(motivo) });
    _calClearForm();
    await _calLoadReports({ preserveSelection: false });
  });

  calEls.btnDeleteGroup.addEventListener("click", async () => {
    const info = calSelected ? (calSelected.type === "group" ? calSelected : calReports.find((r) => r.id === calSelected.id)) : null;
    if (!info) { alert("Seleccioná un grupo o un material del grupo."); return; }
    const count = calReports.filter((r) => r.base === info.base && r.lote === info.lote).length;
    const motivo = Ajuste.pedirMotivo(`¿Eliminar el grupo completo (${count} informes)?`);
    if (motivo === null) return;
    await Ajuste.apiFetch(`/api/calidad/reports/group?base=${encodeURIComponent(info.base)}&lote=${encodeURIComponent(info.lote)}`,
      { method: "DELETE", headers: Ajuste.headersMotivo(motivo) });
    _calClearForm();
    await _calLoadReports({ preserveSelection: false });
  });

  Ajuste.waitForApproval(async (status) => {
    calCanEdit = status.role === "editor" || status.dev_skip_approval;
    if (!calCanEdit) {
      [
        calEls.btnNew, calEls.btnSave, calEls.btnCancelDraft, calEls.btnAddMaterial,
        calEls.btnFundicionesLoad, calEls.btnFundicionesReview, calEls.btnFundicionesLoadAll,
        calEls.btnArchiveGroup, calEls.btnPrint, calEls.btnPrintImages, calEls.btnDelete, calEls.btnDeleteGroup,
      ].forEach((b) => { b.disabled = true; });
    }
    await _calLoadCatalog();
    await _calLoadReports();
    _calClearForm();
  });
};
