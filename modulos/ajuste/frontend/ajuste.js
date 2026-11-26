// ajuste.js — VISTAS.ajuste: pantalla central de Ajuste (sesión compartida colada/objetivo/composición actual
// + motor de cálculo Greedy/Lineal + "Cambio de base" + Carbomax automático por RS485/Modbus + cuadro de
// control del Espectrómetro LMX06). Puerto de frontend/js/ajuste.js de ajuste_comp_web.
//
// A diferencia de la app vieja (una página HTML estática por pantalla, con los elementos ya en el DOM al
// cargar el script), esta vista se reconstruye entera cada vez que se entra a la pestaña "Ajuste" -- por eso
// `els` se llena DENTRO de VISTAS.ajuste (después de armar el HTML), no a nivel de módulo, y los listeners de
// los botones también se registran ahí. wsConnect() se desconecta y se vuelve a conectar en cada entrada a la
// vista (si no, cada visita deja un socket viejo abierto para siempre).

let META = { elements: [] };
let SESSION = null;
let CAN_EDIT = false;
let suppressReload = false;
let els = {};
let graphView = null;
let saveTimer = null;
let kgSaveTimer = null;
// Guardados en vuelo (ver scheduleSave y el input de kg): lo que falta mandar, cuántos hay viajando y un número
// por canal para descartar una respuesta vieja que llega después de una más nueva.
let _patchPendiente = {};
let _guardando = 0;
let _seqSesion = 0;
let _seqKg = 0;
let _wsDisconnects = [];

function fmtNum(n) {
  if (n === null || n === undefined || n === "") return "";
  const v = Number(n);
  if (!Number.isFinite(v)) return "";
  // Solo recortar ceros sobrantes DESPUES del punto decimal -- "\.?0+$" a secas también se come ceros
  // finales de la parte ENTERA si algún día se llama con menos decimales.
  const s = v.toFixed(6);
  return s.includes(".") ? s.replace(/0+$/, "").replace(/\.$/, "") : s;
}

function parseNum(s, fallback = 0) {
  const v = parseFloat(String(s ?? "").replace(",", "."));
  return Number.isFinite(v) ? v : fallback;
}

async function loadMeta() {
  [META] = await Promise.all([Ajuste.apiFetch("/api/meta"), _cargarFamiliasPorBase()]);
}

// Contador de cucharas cargadas al horno -- mismo dato que muestra Pie de Horno (Raspberry). Reusa
// /api/kiosk/snapshot tal cual; ese endpoint todavía no existe en esta app (fase del kiosko), así que esto
// falla en silencio hasta que se porte -- igual que ya hacía la app vieja ante cualquier error de red.
async function loadCucharasCounter() {
  try {
    const data = await Ajuste.apiFetch("/api/kiosk/snapshot");
    const c = data?.cucharas || {};
    const total = Number(c.total_cucharas || 0);
    els.cucharasBadge.textContent = `Cucharas: ${total}`;
    els.cucharasBadge.title = c.colada
      ? `Cucharas cargadas al horno en la colada ${c.colada}${c.material_objetivo ? ` (${c.material_objetivo})` : ""}`
      : "Cucharas cargadas al horno en esta colada, según Pie de Horno";
  } catch (_) {
    // silencioso -- no bloquear Ajuste si el kiosko/snapshot falla (o todavía no existe)
  }
}

// ---------- Render ----------

// Si la grilla ya está armada con los mismos elementos, se actualizan los valores EN EL LUGAR y la casilla donde
// el usuario está escribiendo no se toca: rearmarla con innerHTML la reemplazaba por una nueva con el valor del
// servidor (el valor "volvía" y se perdía el foco). Solo se rearma si cambian los elementos o si es editable.
// Efecto de cada elemento en una fundición de hierro: le da color al nombre en las grillas de composición
// (ajuste.css, .el-ferrita/.el-perlita/.el-carburo/.el-neutro) y el texto del tooltip. Es una guía de lectura
// rápida, no un cálculo: el efecto real depende de la cantidad, y eso va dicho en el texto.
//   ferrita = grafitizante, favorece matriz ferrítica.
//   perlita = favorece perlita sin formar carburos.
//   carburo = favorece perlita Y es propenso a formar carburos (el de más riesgo de dureza/blanqueo).
//   neutro  = sin efecto apreciable sobre la matriz (impurezas, efecto sobre el grafito, o la base).
// Cada elemento: { e: efecto, t: texto, g: grano } común a las dos familias, y opcionalmente `Gris: {...}` /
// `Nodular: {...}` con lo que cambia en esa familia (el combo de la leyenda elige cuál se ve; ver
// _familiaEfectos). `g` dice si afina el grano/la estructura y CUÁL: más celdas eutécticas o nódulos
// (inoculantes), grafito más fino (Ti, Nb) o perlita de espaciado más fino (Mo, Cr, V).
// Fuentes: lo de grano, bibliografía de fundición (Stefanescu; Ti, Nb y V en HT250; Ductile Iron Society sobre
// tierras raras y Bi). Las diferencias gris/nodular son conocimiento general de fundición, sin una fuente puntual:
// los rangos (S, Ti) son orientativos.
const EFECTO_ELEMENTO = {
  C: { e: "ferrita", t: "Grafitizante: favorece ferrita" },
  Si: { e: "ferrita", t: "Grafitizante fuerte: favorece ferrita",
    g: "No afina por sí solo; lo que nuclea en el FeSi inoculante es el Ca/Ba/Al/Zr/Sr que trae" },
  Al: { e: "ferrita", t: "Grafitizante: favorece ferrita",
    g: "Ayuda a nuclear el grafito (sube la temperatura eutéctica); afina las celdas menos que el Ca" },
  Co: { e: "ferrita", t: "Grafitizante leve: favorece ferrita" },
  Ca: { e: "ferrita", t: "Inoculante: grafitizante", g: "SÍ afina: más celdas eutécticas / nódulos y menos blanqueo" },
  Ba: { e: "ferrita", t: "Inoculante: grafitizante",
    g: "SÍ afina: más celdas eutécticas / nódulos; efecto más duradero (menos fading)" },
  Zr: { e: "ferrita", t: "Inoculante: grafitizante",
    g: "SÍ afina: inoculante (más celdas / nódulos), refuerza al Sr; además fija nitrógeno" },
  Cu: { e: "perlita", t: "Perlitizante, no forma carburos" },
  Ni: { e: "perlita", t: "Perlitizante, no forma carburos", g: "No afina: la perlita tiende a quedar más gruesa" },
  Sn: { e: "perlita", t: "Perlitizante fuerte, no forma carburos" },
  Sb: { e: "perlita", t: "Perlitizante fuerte, no forma carburos",
    Nodular: { t: "Perlitizante fuerte; en exceso degenera el grafito. En trazas evita el grafito chunky en piezas gruesas (mejor junto con tierras raras)" } },
  As: { e: "perlita", t: "Perlitizante" },
  Mn: { e: "carburo", g: "No afina: la perlita tiende a quedar más gruesa",
    Gris: { t: "Perlitizante y carburígeno leve. Se combina con el S (MnS): se dosifica en relación al azufre" },
    Nodular: { t: "Perlitizante y carburígeno: sin S que lo ate segrega a los bordes de celda y forma carburos (más crítico en nodular ferrítico)" } },
  Cr: { e: "carburo", t: "Perlitizante y carburígeno fuerte",
    g: "Afina la perlita (espaciado laminar más fino); arriba de ~0,25 % sube el blanqueo" },
  Mo: { e: "carburo", t: "Perlitizante y carburígeno",
    g: "Afina la perlita: es el que más achica el espaciado laminar; no cambia el grafito bajo 0,5 %" },
  V: { e: "carburo", t: "Perlitizante y carburígeno fuerte", g: "SÍ afina: perlita más fina y celdas eutécticas más chicas" },
  W: { e: "carburo", t: "Perlitizante y carburígeno" },
  Ti: { e: "carburo",
    Gris: { t: "Carburígeno (TiC, TiN)",
      g: "SÍ afina: más austenita primaria y grafito más fino (favorece tipo D, subenfriado); que el TiN nuclee la austenita está discutido" },
    Nodular: { t: "Antinodulizante y carburígeno (TiC): baja la nodularidad (se busca < 0,05 %)",
      g: "No afina: perjudica la forma del grafito" } },
  Nb: { e: "carburo", t: "Carburígeno (NbC)", g: "SÍ afina: el NbC nuclea y afina el grafito, y la perlita queda más fina" },
  B: { e: "carburo", t: "Carburígeno fuerte" },
  Te: { e: "carburo", Gris: { t: "Carburígeno muy fuerte (blanqueo)" },
    Nodular: { t: "Carburígeno muy fuerte (blanqueo) y antinodulizante" } },
  Se: { e: "carburo", t: "Carburígeno" },
  Mg: { e: "carburo",
    Gris: { t: "Residual indeseado: lleva a grafito compacto y blanqueo" },
    Nodular: { t: "Nodulizante principal; en exceso favorece carburos",
      g: "No afina por sí solo: el número de nódulos lo da la inoculación" } },
  Ce: { e: "carburo",
    Gris: { t: "Poco uso; en exceso, blanqueo y grafito anormal" },
    Nodular: { t: "Nodulizante auxiliar: neutraliza Pb, Bi, Sb y Ti; en exceso favorece carburos",
      g: "SÍ afina: sube el conteo de nódulos (más que el Mg); en exceso, grafito chunky en piezas gruesas" } },
  La: { e: "carburo",
    Gris: { t: "Poco uso; en exceso, blanqueo y grafito anormal" },
    Nodular: { t: "Nodulizante auxiliar: neutraliza Pb, Bi, Sb y Ti; en exceso favorece carburos",
      g: "SÍ afina: sube el conteo de nódulos (más que el Mg); en exceso, grafito chunky en piezas gruesas" } },
  P: { e: "neutro",
    Gris: { t: "Forma esteadita (fósforo-eutéctico); se tolera más, da colabilidad" },
    Nodular: { t: "Forma esteadita: baja el alargamiento y la resiliencia; mantenerlo bajo" } },
  S: { e: "neutro",
    Gris: { t: "Hace falta un mínimo (~0,05–0,12 %); se balancea con el Mn (MnS)",
      g: "SÍ ayuda: los sulfuros son los núcleos que usa el inoculante; sin S la inoculación rinde poco" },
    Nodular: { t: "Bajarlo al mínimo (~< 0,02 %): consume Mg (MgS), hace escoria y degenera el grafito" } },
  // Pb: el riesgo es para la estructura (grafito y matriz), no para el crisol -- por eso no está en RIESGO_CRISOL.
  // Fuente: Giesserei-Lexikon "Blei" (umbral 0,003 %, estabiliza la perlita, el Ce lo revierte) y estudios sobre
  // Pb en gris (grafito en púas/malla, caen resistencia y dureza). Entra por chatarra: bujes, cojinetes, pinturas
  // con plomo, aceros resulfurados con Pb.
  Pb: { e: "perlita",
    Gris: { t: "Nocivo para grafito y matriz: aun en trazas da grafito en púas / malla, caen resistencia y dureza; estabiliza la perlita" },
    Nodular: { t: "Nocivo para grafito y matriz: arriba de ~0,003 % da grafito Widmanstätten (antinodulizante), baja mucho la resistencia a fisuras y estabiliza la perlita. Un poco de Ce junto con el Mg lo neutraliza" } },
  Bi: { Gris: { e: "carburo", t: "Promueve blanqueo (se usa en maleable justamente para eso)" },
    Nodular: { e: "neutro", t: "En exceso degenera el grafito",
      g: "SÍ afina: en trazas sube mucho el conteo de nódulos, sobre todo junto con tierras raras" } },
  Zn: { e: "neutro", t: "Sin efecto apreciable sobre la matriz" },
  Fe: { e: "neutro", t: "Base" },
};

// Tierras raras: además del color por efecto llevan un brillo rosado (.el-tierra-rara en ajuste.css) para
// distinguirlas a simple vista. Solo Ce y La están en ELEMENTS; el resto queda listo por si se agregan.
const TIERRAS_RARAS = new Set(["La", "Ce", "Pr", "Nd", "Sm", "Y", "Sc"]);

// Metales de bajo punto de fusión con riesgo DOCUMENTADO para el revestimiento del horno si vienen en la carga
// fría: se funden mucho antes que el acero/arrabio, se meten en las fisuras del crisol y las agrandan. Llevan un
// subrayado amarillo (.el-riesgo-crisol en ajuste.css) y una línea más en el tooltip. Criterio: solo los que
// tienen fuente que describa el daño al revestimiento -- Zn (Foundry Mgmt & Technology, D. Green 2017; patentes
// de inductores de canal) y Al (patente US 9429364: reduce la sílice del revestimiento y penetra las fisuras).
// Pb, Sn, Bi y Sb también funden bajo, pero no se encontró fuente sobre daño al crisol: no se marcan.
const RIESGO_CRISOL = {
  Zn: "Funde a ~420 °C y hierve a ~907 °C: el vapor de zinc (chatarra galvanizada) penetra la cara caliente y las fisuras del revestimiento y las agranda; la zona penetrada se vuelve conductora. Cargarlo temprano y no usarlo en la sinterización ni en arranques en frío",
  Al: "Funde a ~660 °C: reduce la sílice del revestimiento (forma alúmina y silicio), lo debilita y penetra las fisuras",
};

// ---------- Gris / Nodular para los efectos ----------
// El combo de la leyenda elige qué familia se describe. Se recuerda por navegador y cambia SOLO al elegir otra
// base objetivo: la familia de la base sale del catálogo de Calidad (los materiales finales declaran su familia y
// de qué bases salen; si todos los de una base son de la misma familia, esa es la de la base). Una base sin
// materiales finales, o con las dos familias, no cambia nada. Después el usuario puede elegir la otra a mano.
const FAMILIA_EFECTOS_KEY = "ajuste_familia_efectos";
let _familiaEfectos = localStorage.getItem(FAMILIA_EFECTOS_KEY) === "Nodular" ? "Nodular" : "Gris";
let _familiaPorBase = {};
let _ultimaBaseVista; // undefined = todavía no se miró ninguna base (la primera vez también sincroniza)

async function _cargarFamiliasPorBase() {
  try {
    const cat = await Ajuste.apiFetch("/api/calidad/catalog");
    const out = {};
    for (const [base, mats] of Object.entries(cat.base_to_materials || {})) {
      const familias = new Set(mats.map((m) => ((cat.materials || {})[m] || {}).family).filter(Boolean));
      if (familias.size === 1) out[base] = [...familias][0];
    }
    _familiaPorBase = out;
  } catch (_) {
    _familiaPorBase = {}; // sin catálogo el combo queda manual
  }
}

function _elegirFamiliaEfectos(familia) {
  if (familia !== "Gris" && familia !== "Nodular") return;
  _familiaEfectos = familia;
  localStorage.setItem(FAMILIA_EFECTOS_KEY, familia);
  const sel = document.getElementById("sel-familia-efectos");
  if (sel && sel.value !== familia) sel.value = familia;
  // Solo se cambian los nombres (clase + tooltip), sin rearmar las grillas: no se toca ninguna casilla.
  document.querySelectorAll(".el-nombre[data-el]").forEach((span) => {
    span.outerHTML = _spanElemento(span.dataset.el);
  });
}

function _sincronizarFamiliaConBase() {
  const base = SESSION ? (SESSION.objective || "") : "";
  if (base === _ultimaBaseVista) return;
  _ultimaBaseVista = base;
  const familia = _familiaPorBase[base];
  if (familia && familia !== _familiaEfectos) _elegirFamiliaEfectos(familia);
}

function _efectoElemento(el) {
  const d = EFECTO_ELEMENTO[el] || {};
  return { e: "neutro", t: "", ...d, ...(d[_familiaEfectos] || {}) };
}

function _spanElemento(el) {
  const { e: efecto, t: texto, g: grano } = _efectoElemento(el);
  const tr = TIERRAS_RARAS.has(el);
  const mg = el === "Mg"; // el nodulizante principal: destello como el de la reacción en la cuchara
  // &#10; = salto de línea dentro del tooltip nativo (atributo title)
  const titulo = texto ? `${el} (${_familiaEfectos.toLowerCase()}): ${texto}${tr ? " (tierra rara)" : ""}` +
    (grano ? `&#10;Grano: ${grano}` : "") +
    (RIESGO_CRISOL[el] ? `&#10;⚠ Crisol: ${RIESGO_CRISOL[el]}` : "") : "";
  const extra = (tr ? " el-tierra-rara" : "") + (mg ? " el-nodulizante" : "") +
    (RIESGO_CRISOL[el] ? " el-riesgo-crisol" : "");
  return `<span class="el-nombre el-${efecto}${extra}" data-el="${el}"${titulo ? ` title="${titulo}"` : ""}>${el}</span>`;
}

function buildCompGrid(container, values, { editable, onChange } = {}) {
  const firma = `${META.elements.join(",")}|${editable ? 1 : 0}`;
  if (container.dataset.firma === firma) {
    container.querySelectorAll("input[data-el]").forEach((inp) => {
      if (inp !== document.activeElement) inp.value = fmtNum((values || {})[inp.dataset.el] ?? 0);
    });
    if (editable && container.contains(document.activeElement)) recalcFeActual(container);
    return;
  }
  container.dataset.firma = firma;
  container.innerHTML = "";
  for (const el of META.elements) {
    const wrap = document.createElement("label");
    const val = values ? values[el] : undefined;
    const readOnlyFe = editable && el === "Fe";
    wrap.innerHTML = _spanElemento(el) +
      `<input type="text" data-el="${el}" value="${fmtNum(val ?? 0)}" ${editable && !readOnlyFe ? "" : "readonly tabindex=\"-1\""}>`;
    container.appendChild(wrap);
  }
  if (editable) {
    container.querySelectorAll("input[data-el]:not([readonly])").forEach((inp) => {
      inp.addEventListener("input", () => {
        recalcFeActual(container);
        onChange && onChange();
      });
    });
  }
}

function recalcFeActual(container) {
  let total = 0;
  container.querySelectorAll("input[data-el]").forEach((inp) => {
    if (inp.dataset.el !== "Fe") total += parseNum(inp.value, 0);
  });
  const fe = container.querySelector('input[data-el="Fe"]');
  if (fe) fe.value = fmtNum(Math.max(0, 100 - total));
}

function readCompGrid(container) {
  const out = {};
  container.querySelectorAll("input[data-el]").forEach((inp) => {
    out[inp.dataset.el] = parseNum(inp.value, 0);
  });
  return out;
}

function ceLabel(formula, val, min, max) {
  if (!formula || val === null || val === undefined) return "";
  let s = `CE: ${fmtNum(val)}`;
  if (min !== null && min !== undefined) s += ` | min ${fmtNum(min)}`;
  if (max !== null && max !== undefined) s += ` | max ${fmtNum(max)}`;
  return s;
}

function renderTopBar() {
  // El campo donde el usuario está escribiendo (o el desplegable abierto) no se pisa con lo del servidor.
  const enUso = (campo) => campo === document.activeElement;
  if (!enUso(els.colada)) els.colada.value = SESSION.colada || "";
  if (!enUso(els.mass)) els.mass.value = fmtNum(SESSION.mass);
  if (!enUso(els.method)) els.method.value = SESSION.method || "Greedy";
  if (!enUso(els.pct)) els.pct.value = SESSION.partial_pct || 100;

  if (!enUso(els.objective)) {
    const opts = ['<option value="">(sin objetivo)</option>']
      .concat(SESSION.objective_names.map((n) => `<option value="${n}" ${n === SESSION.objective ? "selected" : ""}>${esc(n)}</option>`));
    els.objective.innerHTML = opts.join("");
  }

  if (SESSION.session_started_at) {
    els.sessionStatus.textContent = `Sesión iniciada: ${SESSION.session_started_at}`;
  } else {
    els.sessionStatus.textContent = "Sin sesión iniciada (elegí un objetivo para arrancar)";
  }
}

function renderCompositionPanels() {
  _sincronizarFamiliaConBase();
  buildCompGrid(els.gridActual, SESSION.actual, { editable: CAN_EDIT, onChange: () => scheduleSave({ actual: readCompGrid(els.gridActual) }) });
  buildCompGrid(els.gridEstimado, SESSION.predicted.composicion, { editable: false });
  buildCompGrid(els.gridObjetivo, SESSION.objective_composicion || {}, { editable: false });

  const p = SESSION.predicted;
  els.ceActual.textContent = ceLabel(p.ce_formula, p.ce_actual, null, null);
  els.ceEstimado.textContent = ceLabel(p.ce_formula, p.ce_estimado, null, null);
  els.ceObjetivo.textContent = ceLabel(p.ce_formula, p.ce_objetivo, p.ce_min, p.ce_max);
  els.ceActual.title = els.ceEstimado.title = els.ceObjetivo.title = p.ce_formula ? `Fórmula: ${p.ce_formula}` : "";
  els.massEstimada.textContent = SESSION.objective ? `Masa estimada (efectiva): ${fmtNum(p.mass)} kg` : "";
}

function renderAdjustRows() {
  const list = SESSION.adjust_list || [];
  // Misma lista de materiales que la que está en pantalla: solo se actualizan los kg en el lugar, sin tocar la
  // casilla enfocada (ver buildCompGrid). Es type=number: con "12." a medio escribir el navegador informa el
  // valor como vacío, así que copiarlo a una casilla nueva tampoco servía -- hay que no reemplazarla.
  const firma = JSON.stringify([list, CAN_EDIT]);
  if (els.adjustRows.dataset.firma === firma) {
    els.adjustRows.querySelectorAll("[data-kg]").forEach((inp) => {
      if (inp !== document.activeElement) inp.value = fmtNum((SESSION.kg || {})[inp.dataset.kg] || 0);
    });
    return;
  }
  els.adjustRows.dataset.firma = firma;
  const rowsHtml = list.length
    ? list.map((name) => `<tr>
        <td>${esc(name)}</td>
        <td><input type="number" step="0.001" min="0" data-kg="${esc(name)}" value="${fmtNum((SESSION.kg || {})[name] || 0)}" ${CAN_EDIT ? "" : "disabled"}></td>
        <td><button type="button" class="peligro chico" data-clear-kg="${esc(name)}" title="Poner en 0" ${CAN_EDIT ? "" : "disabled"}>0</button></td>
      </tr>`).join("")
    : `<tr><td colspan="3" class="sutil">(Sin materiales de ajuste seleccionados)</td></tr>`;
  // Fila fija al final, siempre última: agregar/quitar materiales de la lista.
  const pickRowHtml = `<tr><td colspan="3">
    <button type="button" id="btn-pick-materials" ${CAN_EDIT ? "" : "disabled"} style="width:100%;">Elegir materiales…</button>
  </td></tr>`;
  els.adjustRows.innerHTML = rowsHtml + pickRowHtml;
  els.adjustRows.querySelectorAll("[data-kg]").forEach((inp) => {
    inp.addEventListener("input", () => {
      if (!CAN_EDIT) return;
      if (!SESSION.kg) SESSION.kg = {};
      SESSION.kg[inp.dataset.kg] = parseNum(inp.value, 0);
      suppressReload = true;
      if (kgSaveTimer) clearTimeout(kgSaveTimer);
      kgSaveTimer = setTimeout(async () => {
        kgSaveTimer = null;
        const kg = { ...(SESSION.kg || {}) };
        const miTurno = ++_seqKg;
        _guardando++;
        try {
          suppressReload = true;
          await Ajuste.apiFetch("/api/ajuste/session", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kg }) });
          const res = await Ajuste.apiFetch("/api/ajuste/calc", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
          if (miTurno !== _seqKg) return; // salió otro guardado después: esta respuesta ya es vieja
          // Lo tecleado mientras viajaba (otra casilla de kg) se conserva hasta su propio guardado.
          const kgLocal = SESSION.kg;
          SESSION = res;
          if (kgSaveTimer) SESSION.kg = { ...(SESSION.kg || {}), ...kgLocal };
          render(); // render() deja intacta la casilla donde se está escribiendo
        } catch (ex) {
          setStatus(`Error: ${ex.message}`, "error");
        } finally {
          _guardando--;
          if (_guardando === 0 && !saveTimer && !kgSaveTimer) suppressReload = false;
        }
      }, 450);
    });
  });
  els.adjustRows.querySelector("#btn-pick-materials").addEventListener("click", openPickMaterialsModal);
  els.adjustRows.querySelectorAll("[data-clear-kg]").forEach((btn) => {
    btn.addEventListener("click", () => clearOneKg(btn.dataset.clearKg));
  });
}

// Un botón por fila que pone esa casilla en 0 puntual, en vez de seleccionar el número y apretar borrar --
// mismo flujo que el guardado de un kg individual (PATCH kg + recalcular), pero disparado al toque en vez de
// esperar el debounce de 450ms.
async function clearOneKg(name) {
  if (!CAN_EDIT) return;
  const kg = { ...(SESSION.kg || {}), [name]: 0 };
  SESSION.kg = kg;
  render();
  try {
    suppressReload = true;
    await Ajuste.apiFetch("/api/ajuste/session", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ kg }) });
    const res = await Ajuste.apiFetch("/api/ajuste/calc", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({}) });
    SESSION = res;
    render();
  } catch (ex) {
    setStatus(`Error: ${ex.detail?.message || ex.message}`, "error");
  } finally {
    suppressReload = false;
  }
}

function renderHistorial() {
  const rows = SESSION.ajustes_log || [];
  if (!rows.length) {
    els.histRows.innerHTML = `<tr><td colspan="5" class="sutil">Sin ajustes aplicados todavía en esta sesión.</td></tr>`;
    return;
  }
  els.histRows.innerHTML = rows.slice().reverse().map((r) => {
    const materiales = Object.entries(r.materiales || {}).map(([n, kg]) => `${esc(n)}: ${fmtNum(kg)} kg`).join(", ");
    const cambios = (r.cambios_list || []).slice(0, 4).map((c) => `${c.elemento}: ${fmtNum(c.de)}→${fmtNum(c.a)}`).join(", ");
    return `<tr>
      <td>${esc(r.fecha)}</td>
      <td>${esc(r.objetivo)}</td>
      <td>${materiales}</td>
      <td>${esc(cambios)}</td>
      <td>${fmtNum(r.ce_inicial)} → ${fmtNum(r.ce_estimado)} (${fmtNum(r.ce_objetivo)})</td>
    </tr>`;
  }).join("");
}

// La casilla donde el usuario está escribiendo NUNCA se pisa con lo que llega del servidor. render() se dispara
// por muchas vías que no esperan al usuario: la respuesta de su propio guardado (que salió hace ~0,5 s, así que
// trae lo que había tecleado ANTES), el "session_changed" que el servidor manda por WS después de cada guardado,
// un resultado de Carbomax/espectrómetro... Antes cada una rearmaba las grillas con innerHTML: el campo enfocado
// volvía al valor viejo, perdía el cursor, y fmtNum() se comía la coma a medio escribir ("3," -> "3").
// La defensa principal está en cada render (buildCompGrid, renderAdjustRows, renderTopBar): actualizan en el
// lugar y saltean la casilla enfocada. Esto es el respaldo para cuando igual hubo que rearmarla (cambió la lista
// de materiales, por ejemplo): se le copia lo que tenía escrito a la nueva y se le devuelve el foco.
// El valor del servidor recién se muestra cuando el usuario sale de la casilla (ver _alSalirDeCasilla).
function _capturarEdicion() {
  const a = document.activeElement;
  if (!a || !["INPUT", "TEXTAREA"].includes(a.tagName) || a.readOnly) return null;
  if (["checkbox", "radio", "button", "submit"].includes(a.type)) return null;
  if (!document.getElementById("vista")?.contains(a)) return null;
  let selector;
  if (a.id) selector = `#${CSS.escape(a.id)}`;
  else if (a.dataset.el) selector = `#${CSS.escape(a.closest("[id]")?.id || "")} [data-el="${CSS.escape(a.dataset.el)}"]`;
  else if (a.dataset.kg) selector = `#adjust-rows [data-kg="${CSS.escape(a.dataset.kg)}"]`;
  else return null;
  let inicio = null, fin = null;
  try { inicio = a.selectionStart; fin = a.selectionEnd; } catch (_) { /* type=number no tiene selección */ }
  return { campo: a, selector, valor: a.value, inicio, fin };
}

function _restaurarEdicion(edicion) {
  if (!edicion) return;
  if (edicion.campo.isConnected) return; // es la misma casilla, no se rearmó: no hay nada que restaurar
  const campo = document.querySelector(edicion.selector);
  if (!campo) return;
  campo.value = edicion.valor;
  if (document.activeElement !== campo) campo.focus({ preventScroll: true });
  if (edicion.inicio !== null) {
    try { campo.setSelectionRange(edicion.inicio, edicion.fin); } catch (_) { /* idem */ }
  }
  if (campo.dataset.el && els.gridActual?.contains(campo)) recalcFeActual(els.gridActual);
}

function render() {
  const edicion = _capturarEdicion();
  renderTopBar();
  renderCompositionPanels();
  renderAdjustRows();
  renderHistorial();
  renderCarbomaxRecent();
  renderSpectroPanel();
  _restaurarEdicion(edicion);
  refreshGraph();
}

// Al salir de una casilla se le pone el valor del servidor ya formateado ("3,50" -> "3.5"), sin rearmar nada (un
// render() acá podría reconstruir el botón que el usuario está clickeando y perderle el clic). Si todavía hay un
// guardado pendiente no se toca: lo actualiza la respuesta de ese guardado.
function _alSalirDeCasilla(ev) {
  const campo = ev.target;
  if (!SESSION || saveTimer || kgSaveTimer || _guardando > 0) return;
  if (campo.dataset.el && els.gridActual?.contains(campo)) campo.value = fmtNum((SESSION.actual || {})[campo.dataset.el] ?? 0);
  else if (campo.dataset.kg) campo.value = fmtNum((SESSION.kg || {})[campo.dataset.kg] || 0);
  else if (campo === els.mass) campo.value = fmtNum(SESSION.mass);
}

async function refreshGraph() {
  try {
    const data = await Ajuste.apiFetch("/api/ajuste/graph");
    graphView.draw(data);
  } catch (ex) {
    graphView.draw({ error: ex.message });
  }
}

function setStatus(msg, variant = "") {
  els.status.textContent = msg || "";
  els.status.className = variant === "error" ? "error" : "sutil";
}

// ---------- Guardado (PATCH /session), debounced para texto libre ----------

function scheduleSave(patch, { immediate } = {}) {
  if (!CAN_EDIT) return;
  Object.assign(SESSION, patch);
  // Se corta la recarga por WS desde el primer tecleo, no recién cuando arranca el fetch del guardado -- si
  // no, un broadcast que llega mientras el usuario todavía está escribiendo (antes de que se cumpla el
  // debounce) dispara reload() y reconstruye el grid con el valor viejo del servidor, borrando lo recién
  // tecleado.
  suppressReload = true;
  // Se ACUMULA con lo que todavía no salió: antes cada llamada reemplazaba el patch pendiente, así que escribir
  // la colada y enseguida la masa (dentro de los 500 ms) perdía la colada.
  _patchPendiente = { ..._patchPendiente, ...patch };
  if (saveTimer) clearTimeout(saveTimer);
  saveTimer = null;
  const fire = async () => {
    saveTimer = null;
    const envio = _patchPendiente;
    _patchPendiente = {};
    const miTurno = ++_seqSesion;
    _guardando++;
    try {
      suppressReload = true;
      const updated = await Ajuste.apiFetch("/api/ajuste/session", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify(envio) });
      // Si mientras viajaba salió otro guardado, esta respuesta ya es vieja: la que vale es la del último.
      if (miTurno !== _seqSesion) return;
      SESSION = updated;
      Object.assign(SESSION, _patchPendiente); // lo tecleado después del envío sigue mandando hasta guardarse
      render(); // render() deja intacta la casilla donde se está escribiendo
      setStatus("");
    } catch (ex) {
      setStatus(`Error al guardar: ${ex.message}`, "error");
    } finally {
      _guardando--;
      if (_guardando === 0 && !saveTimer && !kgSaveTimer) suppressReload = false;
    }
  };
  if (immediate) fire(); else saveTimer = setTimeout(fire, 500);
}

// ---------- Reload completo (GET /session) ----------

async function reload() {
  SESSION = await Ajuste.apiFetch("/api/ajuste/session");
  render();
}

// ---------- Modal: elegir materiales de ajuste ----------

function openPickMaterialsModal() {
  const selected = new Set(SESSION.adjust_list || []);
  abrirModal(`
    <h2>Materiales de ajuste</h2>
    <p class="sutil">Elegí de qué materiales del catálogo puede disponer el motor de cálculo para el ajuste.</p>
    <div class="pick-list">
      ${SESSION.adjuster_candidates.map((n) => `<label>
        <input type="checkbox" value="${esc(n)}" ${selected.has(n) ? "checked" : ""}> ${esc(n)}
      </label>`).join("")}
    </div>
    <div class="botones" style="margin-top:12px;">
      <button type="button" id="pm-cancel">Cancelar</button>
      <button type="button" id="pm-save" class="primario">Guardar</button>
    </div>`);
  document.getElementById("pm-cancel").onclick = cerrarModal;
  document.getElementById("pm-save").onclick = async () => {
    const names = [...document.querySelectorAll('#modal-cuerpo input[type="checkbox"]:checked')].map((c) => c.value);
    try {
      SESSION = await Ajuste.apiFetch("/api/ajuste/session", { method: "PATCH", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ adjust_list: names }) });
      render();
      cerrarModal();
    } catch (ex) {
      setStatus(`Error: ${ex.message}`, "error");
    }
  };
}

// ---------- Modal: cargar composición actual desde catálogo ----------

async function openLoadActualModal() {
  const alloys = await Ajuste.apiFetch("/api/alloys");
  const propias = alloys.filter((a) => a.tipo === "Aleación propia").sort((a, b) => a.nombre.localeCompare(b.nombre));
  abrirModal(`
    <h2>Cargar composición actual desde catálogo</h2>
    <div class="pick-list">
      ${propias.map((a) => `<button type="button" class="btn-pick-alloy" data-idx="${a.idx}" style="display:block;width:100%;text-align:left;margin-bottom:4px;">${esc(a.nombre)}</button>`).join("") || '<p class="sutil">No hay materiales tipo "Aleación propia" en el catálogo.</p>'}
    </div>
    <div class="botones" style="margin-top:12px;">
      <button type="button" id="la-cancel">Cerrar</button>
    </div>`);
  document.getElementById("la-cancel").onclick = cerrarModal;
  document.querySelectorAll(".btn-pick-alloy").forEach((btn) => {
    btn.onclick = () => {
      const a = propias.find((x) => String(x.idx) === btn.dataset.idx);
      if (!a) return;
      scheduleSave({ actual: { ...a.composicion } }, { immediate: true });
      cerrarModal();
    };
  });
}

// ---------- Modal: cambio de base ----------
// A partir de la composición Estimada actual (la que ya está dando esta colada, targeteada a
// SESSION.objective), simula qué hay que agregar para en cambio llegar a OTRO material del catálogo -- ej.
// viendo que la colada va a quedar en base 8, calcular si agregando algo se la puede reclasificar como base
// 10. Pega a /api/ajuste/cambio-base, que reusa el mismo motor que "Calcular" pero sin tocar la sesión real
// -- por eso este modal no llama a render() ni guarda nada, solo muestra el resultado y se descarta al
// cerrarlo.
function renderCambioBaseResult(container, res) {
  const planEntries = Object.entries(res.plan || {});
  const planRows = planEntries.length
    ? planEntries.map(([n, kg]) => `<tr><td>${esc(n)}</td><td class="num">${fmtNum(kg)}</td></tr>`).join("")
    : `<tr><td colspan="2" class="sutil">(No hace falta agregar nada)</td></tr>`;
  const warnHtml = res.warning ? `<p class="error">${esc(res.warning)}</p>` : "";
  const missingHtml = (res.missing_elements || []).length
    ? `<p class="error">Elementos sin cubrir con los materiales de ajuste actuales: ${res.missing_elements.join(", ")}</p>` : "";

  container.innerHTML = `
    <div class="row" style="gap:16px;flex-wrap:wrap;align-items:flex-start;margin-top:10px;">
      <table style="min-width:220px;">
        <thead><tr><th>Material a agregar</th><th>Kg</th></tr></thead>
        <tbody>${planRows}</tbody>
      </table>
      <div style="flex:1;min-width:260px;">
        <p class="sutil">Composición resultante (${fmtNum(res.predicted.mass)} kg) ${ceLabel(res.ce_formula, res.ce_estimado, res.ce_min, res.ce_max)}</p>
        <div id="cb-grid-pred" class="grid-elements comp-grid"></div>
      </div>
    </div>
    ${warnHtml}${missingHtml}`;
  buildCompGrid(container.querySelector("#cb-grid-pred"), res.predicted.composicion, { editable: false });
}

function openCambioBaseModal() {
  const massDefault = fmtNum(SESSION.predicted.mass);
  abrirModal(`
    <h2>Cambio de base</h2>
    <p class="sutil">Calcula qué agregar a la composición Estimada actual para llegar a otro material, sin tocar la sesión en curso.</p>
    <div class="row" style="align-items:flex-end;">
      <div style="flex:1;">
        <label>Material objetivo</label>
        <select id="cb-objetivo" style="width:100%;">
          <option value="">(elegir)</option>
          ${SESSION.objective_names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("")}
        </select>
      </div>
      <div><label>Masa a convertir (kg)</label><br><input id="cb-mass" type="text" style="width:120px;" value="${massDefault}"></div>
      <button type="button" id="cb-calc" class="primario">Calcular</button>
    </div>
    <div id="cb-result"></div>
    <div class="botones" style="margin-top:12px;">
      <button type="button" id="cb-close">Cerrar</button>
    </div>`, true);
  document.getElementById("cb-close").onclick = cerrarModal;
  document.getElementById("cb-calc").onclick = async () => {
    const objetivo = document.getElementById("cb-objetivo").value.trim();
    const mass = parseNum(document.getElementById("cb-mass").value, 0);
    const resultEl = document.getElementById("cb-result");
    if (!objetivo) { resultEl.innerHTML = `<p class="error">Elegí un material objetivo.</p>`; return; }
    if (mass <= 0) { resultEl.innerHTML = `<p class="error">Ingresá una masa mayor a 0.</p>`; return; }
    resultEl.innerHTML = `<p class="sutil">Calculando…</p>`;
    try {
      const res = await Ajuste.apiFetch("/api/ajuste/cambio-base", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ objective: objetivo, mass, actual: SESSION.predicted.composicion }),
      });
      renderCambioBaseResult(resultEl, res);
    } catch (ex) {
      resultEl.innerHTML = `<p class="error">Error: ${ex.detail?.message || ex.detail?.error || ex.message}</p>`;
    }
  };
}

// ---------- Acciones ----------

async function runAction(url, body, { successMsg } = {}) {
  try {
    setStatus("");
    els.warningMsg.textContent = "";
    const res = await Ajuste.apiFetch(url, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body || {}) });
    SESSION = res;
    render();
    if (res.warning) els.warningMsg.textContent = res.warning;
    if (successMsg) setStatus(successMsg, "ok");
  } catch (ex) {
    setStatus(`Error: ${ex.detail?.detail?.message || ex.detail?.detail?.error || ex.message}`, "error");
  }
}

// ---------- Carbomax automático ----------
// Toggle + diálogo "Configurar..." + lista "últimos análisis" (ver carbomax_modbus_auto.py del backend para
// el loop de fondo RS485/Modbus, la vía principal de detección hoy). "Usar" en una fila requiere que ya haya
// un objetivo elegido arriba -- la lista no bloquea nada, cada análisis que detecta el loop se agrega solo.

function openCarbomaxConfigModal() {
  const names = SESSION.carbomax_base_names && SESSION.carbomax_base_names.length === 3
    ? SESSION.carbomax_base_names : ["", "", ""];
  const candidates = SESSION.adjuster_candidates || [];
  const opt = (list, current) => ['<option value="">(elegir)</option>']
    .concat(list.map((n) => `<option value="${esc(n)}" ${n === current ? "selected" : ""}>${esc(n)}</option>`)).join("");
  abrirModal(`
    <h2>Configurar Carbomax automático</h2>
    <div class="row"><label>IP del equipo<br><input id="cc-ip" type="text" placeholder="192.168.0.180"></label></div>
    <div class="row"><div style="flex:1;"><label>Fuente de Carbono
      <select id="cc-c">${opt(candidates, names[0])}</select></label></div></div>
    <div class="row"><div style="flex:1;"><label>Fuente de Silicio
      <select id="cc-si">${opt(candidates, names[1])}</select></label></div></div>
    <div class="row"><div style="flex:1;"><label>Diluyente de Fe
      <select id="cc-fe">${opt(candidates, names[2])}</select></label></div></div>
    <div class="row">
      <div><label>Intervalo de descarga (seg)<br><input id="cc-poll" type="number" min="5" max="300" value="${SESSION.carbomax_poll_seconds || 15}" style="width:90px;"></label></div>
      <div><label>Reintento si está ocupado o no responde (seg)<br><input id="cc-busy" type="number" min="1" max="60" value="${SESSION.carbomax_busy_poll_seconds || 5}" style="width:90px;"></label></div>
      <div><label>Timeout HTTP (seg)<br><input id="cc-timeout" type="number" min="1" max="30" value="${Math.min(30, SESSION.carbomax_timeout || 4)}" style="width:90px;"></label></div>
    </div>
    <div class="row">
      <div><label>Factor máximo de masa (ej: 1.25 = +25%)<br><input id="cc-massfactor" type="text" value="${SESSION.carbomax_max_mass_factor || 1.25}" style="width:90px;"></label></div>
      <div><label style="display:flex;align-items:center;gap:6px;margin-top:22px;"><input type="checkbox" id="cc-apply" ${SESSION.carbomax_auto_apply ? "checked" : ""}> Aplicar el ajuste automáticamente</label></div>
    </div>
    <p class="sutil">Si "Aplicar automáticamente" está destildado, el plan se calcula y carga en Estimado pero hay que apretar "Aplicar" a mano.</p>
    <p class="error" id="cc-error"></p>
    <div class="botones" style="margin-top:10px;">
      <button type="button" id="cc-cancel">Cancelar</button>
      <button type="button" id="cc-save" class="primario">Guardar</button>
    </div>`, true);
  document.getElementById("cc-ip").value = SESSION.carbomax_device_ip || "192.168.0.180";
  document.getElementById("cc-cancel").onclick = cerrarModal;
  document.getElementById("cc-save").onclick = async () => {
    const base_names = [
      document.getElementById("cc-c").value.trim(),
      document.getElementById("cc-si").value.trim(),
      document.getElementById("cc-fe").value.trim(),
    ];
    const errEl = document.getElementById("cc-error");
    if (base_names.some((n) => !n)) { errEl.textContent = "Completá los 3 materiales."; return; }
    try {
      SESSION = await Ajuste.apiFetch("/api/ajuste/carbomax-auto/config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          base_names,
          device_ip: document.getElementById("cc-ip").value.trim(),
          poll_seconds: parseNum(document.getElementById("cc-poll").value, 15),
          busy_poll_seconds: parseNum(document.getElementById("cc-busy").value, 5),
          timeout: parseNum(document.getElementById("cc-timeout").value, 4),
          auto_apply: document.getElementById("cc-apply").checked,
          max_mass_factor: parseNum(document.getElementById("cc-massfactor").value, 1.25),
        }),
      });
      render();
      cerrarModal();
      setStatus("Carbomax automático configurado.", "ok");
    } catch (ex) {
      errEl.textContent = ex.detail?.message || ex.detail?.error || ex.message;
    }
  };
}

function renderCarbomaxRecent() {
  const rows = SESSION.carbomax_recent_records || [];
  const currentColada = SESSION.colada || "";
  const currentCount = currentColada ? rows.filter((r) => r.colada === currentColada).length : 0;
  els.cxRecentCount.textContent = currentColada ? `${currentCount} de esta colada` : "";
  if (!rows.length) {
    els.cxRecentRows.innerHTML = `<tr><td colspan="6" class="sutil">Sin análisis todavía.</td></tr>`;
    return;
  }
  els.cxRecentRows.innerHTML = rows.map((r, i) => {
    const isCurrent = r.colada && r.colada === currentColada;
    const isOld = r.colada && r.colada !== currentColada;
    const rowStyle = isOld ? ` style="opacity:0.55;"` : "";
    const coladaCell = isCurrent
      ? `<span style="color:var(--verde);font-weight:600;">${esc(r.colada)}</span>`
      : (esc(r.colada) || `<span class="sutil" style="margin-left:0;">?</span>`);
    return `<tr${rowStyle}>
      <td>${esc(r.ts || "")}</td>
      <td>${coladaCell}</td>
      <td>${fmtNum(r.carbon)}</td>
      <td>${fmtNum(r.silicon)}</td>
      <td>${esc(r.source || "")}</td>
      <td><button type="button" class="cx-use-btn chico" data-idx="${i}" ${CAN_EDIT ? "" : "disabled"}>Usar</button></td>
    </tr>`;
  }).join("");
  els.cxRecentRows.querySelectorAll(".cx-use-btn").forEach((btn) => {
    btn.onclick = async () => {
      try {
        const res = await Ajuste.apiFetch("/api/ajuste/carbomax-auto/use-record", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ index: Number(btn.dataset.idx) }),
        });
        setStatus(res.message || "Carbomax automático procesado.", res.ok ? "ok" : "error");
        await reload();
      } catch (ex) {
        setStatus(`Error: ${ex.detail?.message || ex.message}`, "error");
      }
    };
  });
}

// ---------- Popup de Carbono detectado (simple) ----------
// Puerto 1:1 -- pega a /api/ajuste/carbon-silicon, que SÍ está portado. Lo que todavía no existe es quién lo
// DISPARA: el mensaje WS "carbon_detected" lo manda el auto-vínculo de Análisis Térmico (routers/termico.py,
// NO Carbomax automático -- ese módulo manda "carbomax_result", ya portado más abajo) -- hasta que se porte
// Análisis Térmico, esta función queda lista pero nunca se invoca sola.

function renderCSiRow(carbon, silicon, idPrefix) {
  return `<div class="row">
    <div><label>C (%)</label><input id="${idPrefix}-c" type="text" readonly value="${fmtNum(carbon)}" style="width:100px;"></div>
    <div><label>Si (%)</label><input id="${idPrefix}-si" type="text" readonly value="${fmtNum(silicon)}" style="width:100px;"></div>
  </div>`;
}

function renderObjectiveSelect(id) {
  return `<div style="flex:1;"><label>Material final</label>
    <select id="${id}" style="width:100%;">
      <option value="">(elegir)</option>
      ${SESSION.objective_names.map((n) => `<option value="${esc(n)}">${esc(n)}</option>`).join("")}
    </select>
  </div>`;
}

function openCarbonDetectedModal(msg) {
  const needsObjective = !!msg.no_session;
  abrirModal(`
    <h2>Nuevo análisis de Carbono detectado</h2>
    <p>Colada <strong>${esc(msg.colada)}</strong> — ${esc(msg.source_name || "análisis sin nombre")}</p>
    ${renderCSiRow(msg.carbon, msg.silicon, "cd")}
    ${needsObjective ? `
    <p class="sutil">Todavía no hay sesión iniciada para esta colada — elegí el material final para arrancarla y cargar estos valores.</p>
    <div class="row">${renderObjectiveSelect("cd-objetivo")}</div>` : `
    <p class="sutil">¿Cargar estos valores en la composición Actual?</p>`}
    <div class="botones" style="margin-top:10px;">
      <button type="button" id="cd-ignore">Ignorar</button>
      <button type="button" id="cd-accept" class="primario">${needsObjective ? "Iniciar sesión y cargar" : "Cargar en Actual"}</button>
    </div>`);
  document.getElementById("cd-ignore").onclick = cerrarModal;
  document.getElementById("cd-accept").onclick = async () => {
    if (SESSION.colada !== msg.colada) {
      avisar(`La colada cambió (ahora es "${SESSION.colada}") — no se cargan estos valores para evitar mezclarlos con otra sesión.`, true);
      cerrarModal();
      return;
    }
    const body = { carbon: msg.carbon, silicon: msg.silicon };
    if (needsObjective) {
      const objetivo = document.getElementById("cd-objetivo").value.trim();
      if (!objetivo) { avisar("Elegí un material final.", true); return; }
      if (SESSION.session_started_at) {
        avisar("Ya se inició una sesión mientras elegías el material — revisá la composición actual a mano.", true);
        cerrarModal();
        return;
      }
      body.objective = objetivo;
    }
    cerrarModal();
    try {
      SESSION = await Ajuste.apiFetch("/api/ajuste/carbon-silicon", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
      });
      render();
      setStatus(`Composición actual actualizada desde ${msg.source_name || "Carbomax"}: C=${fmtNum(msg.carbon)} / Si=${fmtNum(msg.silicon)}`, "ok");
    } catch (ex) {
      setStatus(`Error: ${ex.detail?.message || ex.detail?.error || ex.message}`, "error");
    }
  };
}

// ---------- Cuadro "Espectro" (control manual del LMX06) ----------
// A diferencia del flujo Carbomax (toggle + popup), este cuadro está siempre visible: conexión, estado del
// instrumento, método/perfil activo, botón "Medir ahora" y la tabla de últimas mediciones viven todos acá.
// No hay aplicación automática de ningún plan -- "usar esta medición" solo copia composición a "Actual" (ver
// ..spectro_auto.py, sección "Espectrómetro LMX06" de rutas/ajuste.py).

const spectroState = {
  instrumentState: {},
  remoteControlMode: "",
  methods: [],
  currentMethod: null,
  profiles: [],
  currentProfile: null,
};

// "measuring" (MeasurementStarted, lectura física en curso) vs "calculating" (MeasurementFinished, lectura
// terminada pero todavía calculando el resultado). Los dos apagan igual con MeasurementCompleted/
// AnalysisFinished/MeasurementBroken (phase=false).
const MEASURING_PHASE_LABEL = {
  measuring: "● Midiendo…",
  calculating: "● Calculando…",
};

function updateMeasuringBadge(phase) {
  const badge = els.spMeasuringBadge;
  if (!badge) return;
  badge.classList.remove("phase-measuring", "phase-calculating");
  if (!phase) {
    badge.hidden = true;
    return;
  }
  badge.hidden = false;
  badge.textContent = MEASURING_PHASE_LABEL[phase] || "● En curso…";
  badge.classList.add(`phase-${phase}`);
}

// spectro_auto es el toggle ("debería estar tratando de conectar"), spectro_connected es si el socket con el
// Events Server está de verdad abierto ahora mismo -- con la PC del instrumento apagada, spectro_auto sigue
// en true (nadie lo apaga) y el thread reintenta para siempre, así que hace falta esta segunda señal para no
// mostrar "Conectado" cuando en realidad no hay nada del otro lado.
function updateConnBadge() {
  const badge = els.spConnBadge;
  badge.classList.remove("state-connected", "state-connecting", "state-disconnected");
  if (!SESSION.spectro_auto) {
    badge.textContent = "Desconectado";
    badge.classList.add("state-disconnected");
  } else if (SESSION.spectro_connected) {
    badge.textContent = "● Conectado";
    badge.classList.add("state-connected");
  } else {
    badge.textContent = "Conectando…";
    badge.classList.add("state-connecting");
  }
}

function renderSpectroPanel() {
  updateConnBadge();
  updateMeasuringBadge(SESSION.spectro_measuring);
  els.spBtnConnect.textContent = SESSION.spectro_auto ? "Desconectar" : "Conectar";
  if (document.activeElement !== els.spHost) els.spHost.value = SESSION.spectro_host || "";
  if (document.activeElement !== els.spCmdPort) els.spCmdPort.value = SESSION.spectro_commands_port || 11000;
  if (document.activeElement !== els.spEvtPort) els.spEvtPort.value = SESSION.spectro_events_port || 11001;
  if (!els.spSampleName.value) els.spSampleName.value = SESSION.colada || "";

  els.spBtnMeasure.disabled = !CAN_EDIT || spectroState.remoteControlMode !== "Full";
  els.spBtnMeasure.title = spectroState.remoteControlMode && spectroState.remoteControlMode !== "Full"
    ? `Control remoto en modo "${spectroState.remoteControlMode}" -- hace falta "Full" para medir.` : "";
  els.spBtnMeasure.hidden = !!SESSION.spectro_hide_measure;
  if (document.activeElement !== els.spChkHideMeasure) {
    els.spChkHideMeasure.checked = !!SESSION.spectro_hide_measure;
  }
  els.spChkHideMeasure.disabled = !CAN_EDIT;

  renderInstrumentStateBadges();
  renderMethodProfileSelects();
  renderRecentSpectroResults();
  renderSpectroAlerts();
}

// ---------- Alertas (ProcessError/ProcessInformation/OperatorInteractionNeeded) ----------
// Eventos que reflejan lo que se ve en la pantalla del instrumento. ProcessError es un error real (rojo),
// OperatorInteractionNeeded está esperando que alguien responda ahí mismo (ámbar, la más urgente),
// ProcessInformation es solo informativo (neutro).
const ALERT_STYLE = {
  ProcessError: { color: "var(--rojo)", label: "Error" },
  OperatorInteractionNeeded: { color: "var(--ambar)", label: "Necesita atención" },
  ProcessInformation: { color: "var(--sutil)", label: "Info" },
  MeasurementBroken: { color: "var(--rojo)", label: "Medición interrumpida" },
};

// SampleIdentificationNeeded es la única interacción donde "responder" significa escribir un dato nuevo, no
// elegir una opción -- el protocolo no manda texto libre dentro de FinishOperatorInteraction, así que el
// flujo real es: PrepareAnalysis con el ID nuevo, después FinishOperatorInteraction con "Ok". Se destaca
// aparte (banner propio) para que no pase desapercibido.
const SAMPLE_ID_INTERACTION = "SampleIdentificationNeeded";

// Colada sin espacios alrededor de la barra, más "-" y el objetivo si hay uno cargado -- ej. "0123/26-5".
function formatColadaConMaterial(colada, objetivo) {
  const coladaText = String(colada || "").trim().replace(/\s*\/\s*/g, "/");
  const materialText = String(objetivo || "").trim();
  if (!coladaText) return "";
  return materialText ? `${coladaText}-${materialText}` : coladaText;
}

// "resolved" es compartido (vive en la sesión) -- una vez respondida, ningún dispositivo vuelve a ofrecer
// los botones de esa alerta. recentlyResolvedTs SÍ es local: solo controla cuánto dura el cartel "Resuelto"
// antes de que la alerta pase a ser un renglón de historial mudo (5s).
let recentlyResolvedTs = null;
let recentlyResolvedTimer = null;

function flashResolved(ts) {
  recentlyResolvedTs = ts;
  clearTimeout(recentlyResolvedTimer);
  recentlyResolvedTimer = setTimeout(() => {
    recentlyResolvedTs = null;
    renderSpectroAlerts();
  }, 5000);
}

function renderSpectroAlerts() {
  if (!els.spAlerts) return;
  const alerts = SESSION.spectro_alerts || [];
  if (!alerts.length) {
    els.spAlerts.innerHTML = `<span class="sutil" style="margin-left:0;">Sin alertas del instrumento.</span>`;
    return;
  }
  const first = alerts[0];
  const firstJustResolved = first && first.resolved && first.kind === "OperatorInteractionNeeded" && recentlyResolvedTs === first.ts;
  const needsSampleId = first && !first.resolved && first.kind === "OperatorInteractionNeeded" && first.name === SAMPLE_ID_INTERACTION && CAN_EDIT;

  const rows = alerts.slice(0, 8).map((a, idx) => {
    // Una OperatorInteractionNeeded YA resuelta no necesita más el color "necesita atención" -- si no, queda
    // ámbar para siempre aunque no haya ningún botón para apretar.
    const isResolvedInteraction = a.kind === "OperatorInteractionNeeded" && a.resolved;
    const style = isResolvedInteraction
      ? { color: "var(--verde)", label: "Resuelta" }
      : (ALERT_STYLE[a.kind] || { color: "var(--sutil)", label: a.kind || "" });
    const extra = a.kind === "OperatorInteractionNeeded" && (a.options || []).length
      ? ` (${a.options.map((o) => esc(o)).join(" / ")})`
      : (a.detail ? ` (${esc(a.detail)})` : "");
    // Solo la alerta más reciente y sin resolver ofrece responder -- las de más abajo son historial. La de
    // SampleIdentificationNeeded se resuelve arriba, en el banner propio.
    const canRespondHere = idx === 0 && !a.resolved && a.kind === "OperatorInteractionNeeded" && CAN_EDIT && a.name !== SAMPLE_ID_INTERACTION;
    const actionsId = `sp-alert-actions-${idx}`;
    return `<div style="font-size:0.85em;border-left:3px solid ${style.color};padding-left:6px;">`
      + `<strong style="color:${style.color};">${style.label}</strong> `
      + `${esc(a.name || a.kind)}${extra} `
      + `<span class="sutil" style="margin-left:0;">— ${esc(a.ts || "")}</span>`
      + (canRespondHere ? `<div id="${actionsId}" class="row" style="gap:4px;margin-top:2px;"></div>` : "")
      + `</div>`;
  }).join("");

  const suggestedSampleId = formatColadaConMaterial(SESSION.colada, SESSION.objective);
  // Si seguimos mostrando la MISMA alerta (mismo ts) que en el render anterior, no pisar lo que el operario
  // ya haya tocado en el campo -- solo se arranca con la sugerencia cuando la alerta es nueva.
  const prevInput = document.getElementById("sp-alert-sample-id");
  const isSameAlert = needsSampleId && els.spAlerts.dataset.sampleAlertTs === first.ts;
  const initialSampleId = (isSameAlert && prevInput) ? prevInput.value : suggestedSampleId;

  const banner = needsSampleId ? `
    <div style="border:1px solid var(--ambar);border-radius:8px;padding:8px;margin-bottom:6px;background:var(--ambar-claro);">
      <strong style="color:var(--ambar);">El instrumento pide identificación de muestra</strong>
      <div class="row" style="gap:6px;margin-top:6px;align-items:center;">
        <input id="sp-alert-sample-id" type="text" placeholder="ID de muestra" value="${esc(initialSampleId)}" style="flex:1;min-width:120px;">
        <button id="sp-alert-sample-id-auto" type="button" title="Cargar ${esc(suggestedSampleId)}">Usar automático</button>
        <button id="sp-alert-sample-id-send" type="button" class="primario">Enviar ID y confirmar</button>
        <button id="sp-alert-sample-id-cancel" type="button">Cancelar</button>
      </div>
    </div>` : (firstJustResolved ? `
    <div style="border:1px solid var(--verde);border-radius:8px;padding:8px;margin-bottom:6px;background:var(--verde-claro);">
      <strong style="color:var(--verde);">✓ "${esc(first.name)}" resuelta</strong>
    </div>` : "");

  els.spAlerts.innerHTML = banner + rows;
  if (needsSampleId) els.spAlerts.dataset.sampleAlertTs = first.ts;

  if (needsSampleId) {
    document.getElementById("sp-alert-sample-id-auto").addEventListener("click", () => {
      document.getElementById("sp-alert-sample-id").value = suggestedSampleId;
    });
    document.getElementById("sp-alert-sample-id-send").addEventListener("click", (e) => sendSampleIdForAlert(first.name, first.ts, e.target));
    document.getElementById("sp-alert-sample-id-cancel").addEventListener("click", (e) => respondSpectroInteraction(first.name, first.ts, "Cancel", e.target));
    return;
  }

  if (first && !first.resolved && first.kind === "OperatorInteractionNeeded" && CAN_EDIT) {
    const actionsEl = document.getElementById("sp-alert-actions-0");
    if (actionsEl) {
      const options = (first.options || []).length ? first.options : [null];
      options.forEach((opt) => {
        const btn = document.createElement("button");
        btn.type = "button";
        btn.textContent = opt || "Confirmar";
        btn.addEventListener("click", () => respondSpectroInteraction(first.name, first.ts, opt, btn));
        actionsEl.appendChild(btn);
      });
    }
  }
}

async function sendSampleIdForAlert(interactionName, alertTs, btn) {
  const input = document.getElementById("sp-alert-sample-id");
  const sampleId = (input?.value || "").trim();
  if (!sampleId) {
    setStatus("Escribí un ID de muestra antes de enviar.", "error");
    return;
  }
  const sendBtn = document.getElementById("sp-alert-sample-id-send");
  const cancelBtn = document.getElementById("sp-alert-sample-id-cancel");
  [sendBtn, cancelBtn, input].forEach((el) => { if (el) el.disabled = true; });
  try {
    await Ajuste.apiFetch("/api/ajuste/spectro-auto/set-sample-id", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ sample_id: sampleId }),
    });
    await Ajuste.apiFetch("/api/ajuste/spectro-auto/finish-interaction", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interaction_name: interactionName, option: "Ok" }),
    });
    setStatus(`Espectrómetro: ID "${sampleId}" enviado y confirmado.`, "ok");
    flashResolved(alertTs);
    reload();
  } catch (ex) {
    setStatus(`Error enviando el ID al instrumento: ${ex.detail?.message || ex.message}`, "error");
    [sendBtn, cancelBtn, input].forEach((el) => { if (el) el.disabled = false; });
  }
}

async function respondSpectroInteraction(interactionName, alertTs, option, btn) {
  const group = btn.parentElement;
  Array.from(group.children).forEach((b) => { b.disabled = true; });
  try {
    await Ajuste.apiFetch("/api/ajuste/spectro-auto/finish-interaction", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ interaction_name: interactionName, option }),
    });
    setStatus(`Espectrómetro: "${interactionName}" respondida (${option || "Confirmar"}).`, "ok");
    flashResolved(alertTs);
    reload();
  } catch (ex) {
    setStatus(`Error respondiendo al instrumento: ${ex.detail?.message || ex.message}`, "error");
    Array.from(group.children).forEach((b) => { b.disabled = false; });
  }
}

function renderInstrumentStateBadges() {
  const st = spectroState.instrumentState || {};
  const entries = Object.entries(st);
  const modeTxt = spectroState.remoteControlMode ? `Control remoto: ${spectroState.remoteControlMode}` : "";
  if (!entries.length && !modeTxt) {
    els.spInstrumentState.innerHTML = `<span class="sutil">Sin datos del instrumento todavía.</span>`;
    return;
  }
  const chip = (label, value) => {
    const ok = String(value).toLowerCase() === "ok" || String(value).toLowerCase() === "true";
    return `<span class="chip ${ok ? "verde" : "ambar"}">${esc(label)}: ${esc(String(value))}</span>`;
  };
  let html = entries
    .filter(([k]) => /State$|Ok$/.test(k))
    .map(([k, v]) => chip(k.replace(/State$/, ""), v))
    .join(" ");
  if (modeTxt) {
    html += ` <span class="chip">${esc(modeTxt)}</span>`;
  }
  els.spInstrumentState.innerHTML = html;
}

// Método/perfil por defecto: lo que se usa el día a día. Solo es el placeholder que se ve ANTES de que
// llegue la lista real vía GetMethodNames/GetProfileNames -- "Activar método/perfil" no hace nada con este
// placeholder (no tiene excitation_type/base_element todavía), es puramente para que el combo no arranque
// vacío/"(sin datos)".
const DEFAULT_SPECTRO_METHOD = "Fe-20-F";
const DEFAULT_SPECTRO_PROFILE = "Fe-Base";

function renderMethodProfileSelects() {
  const curMethod = spectroState.currentMethod?.method_name || "";
  els.spMethodSelect.innerHTML = spectroState.methods.length
    ? spectroState.methods.map((m) => `<option value="${esc(m.method_name)}" ${m.method_name === curMethod ? "selected" : ""}>${esc(m.method_name)}</option>`).join("")
    : `<option value="${DEFAULT_SPECTRO_METHOD}" selected>${DEFAULT_SPECTRO_METHOD}</option>`;

  const curProfile = spectroState.currentProfile?.profile_name || "";
  els.spProfileSelect.innerHTML = spectroState.profiles.length
    ? spectroState.profiles.map((p) => `<option value="${esc(p.profile_name)}" ${p.profile_name === curProfile ? "selected" : ""}>${esc(p.profile_name)}</option>`).join("")
    : `<option value="${DEFAULT_SPECTRO_PROFILE}" selected>${DEFAULT_SPECTRO_PROFILE}</option>`;
}

function renderRecentSpectroResults() {
  const rows = SESSION.spectro_recent_results || [];
  const currentColada = SESSION.colada || "";
  const currentCount = currentColada ? rows.filter((r) => r.colada === currentColada).length : 0;
  els.spRecentCount.textContent = currentColada ? `${currentCount} de esta colada` : "";
  if (!rows.length) {
    els.spRecentRows.innerHTML = `<tr><td colspan="5" class="sutil">Sin mediciones todavía.</td></tr>`;
    return;
  }
  els.spRecentRows.innerHTML = rows.map((r, i) => {
    const summary = Object.entries(r.elements || {})
      .sort((a, b) => a[0].localeCompare(b[0]))
      .map(([el, pct]) => `${esc(el)} ${Number(pct).toFixed(2)}%`)
      .join(", ");
    // "colada" no existe en resultados de antes de este campo -- esos quedan sin marcar ni gris ni verde, no
    // se puede saber a qué colada pertenecían.
    const isCurrent = r.colada && r.colada === currentColada;
    const isOld = r.colada && r.colada !== currentColada;
    const rowStyle = isOld ? ` style="opacity:0.55;"` : "";
    const coladaCell = isCurrent
      ? `<span style="color:var(--verde);font-weight:600;">${esc(r.colada)}</span>`
      : (esc(r.colada) || `<span class="sutil" style="margin-left:0;">?</span>`);
    return `<tr${rowStyle}>
      <td>${esc(r.ts || "")}</td>
      <td>${coladaCell}</td>
      <td>${esc(r.source || "")}</td>
      <td style="max-width:360px;overflow:hidden;text-overflow:ellipsis;white-space:nowrap;" title="${esc(summary)}">${summary}</td>
      <td><button type="button" class="sp-use-btn chico" data-idx="${i}" ${CAN_EDIT ? "" : "disabled"}>Usar en Actual</button></td>
    </tr>`;
  }).join("");
  els.spRecentRows.querySelectorAll(".sp-use-btn").forEach((btn) => {
    btn.onclick = async () => {
      try {
        SESSION = await Ajuste.apiFetch("/api/ajuste/spectro-auto/use-result", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ index: Number(btn.dataset.idx) }),
        });
        render();
        setStatus("Medición copiada a Actual.", "ok");
      } catch (ex) {
        setStatus(`Error: ${ex.detail?.message || ex.message}`, "error");
      }
    };
  });
}

async function refreshSpectroInstrument() {
  if (!SESSION.spectro_host) return;
  try {
    const res = await Ajuste.apiFetch("/api/ajuste/spectro-auto/instrument");
    spectroState.instrumentState = res.state || {};
    spectroState.remoteControlMode = res.remote_control_mode || "";
  } catch (_) {
    // silencioso -- puede fallar si el instrumento está apagado, no es un error del usuario
  }
  renderInstrumentStateBadges();
  els.spBtnMeasure.disabled = !CAN_EDIT || spectroState.remoteControlMode !== "Full";
}

async function refreshSpectroMethodsProfiles() {
  if (!SESSION.spectro_host) return;
  try {
    const m = await Ajuste.apiFetch("/api/ajuste/spectro-auto/methods");
    spectroState.methods = m.methods || [];
    spectroState.currentMethod = m.current || null;
  } catch (_) { /* silencioso */ }
  try {
    const p = await Ajuste.apiFetch("/api/ajuste/spectro-auto/profiles");
    spectroState.profiles = p.profiles || [];
    spectroState.currentProfile = p.current || null;
  } catch (_) { /* silencioso */ }
  renderMethodProfileSelects();
}

// ---------- Botonera de teclado remoto (sp-keys-*) ----------
// Alternativa a "Medir ahora" cuando el instrumento está en modo "Limited" (ver ..spectro_agent_client.py /
// rutas/ajuste.py::send_spectro_key). Los botones se arman una sola vez desde /spectro-auto/keys -- el
// catálogo no cambia en caliente.
let spKeyCommands = [];
let spKeySending = false;

async function loadSpectroKeys() {
  try {
    const res = await Ajuste.apiFetch("/api/ajuste/spectro-auto/keys");
    spKeyCommands = res.comandos || [];
    renderSpectroKeys();
  } catch (_) {
    spKeyCommands = [];
  }
}

function renderSpectroKeys() {
  if (!els.spKeysGroups) return;
  const visible = spKeyCommands.filter((cmd) => cmd.activo !== false);
  const byGroup = new Map();
  for (const cmd of visible) {
    if (!byGroup.has(cmd.grupo)) byGroup.set(cmd.grupo, []);
    byGroup.get(cmd.grupo).push(cmd);
  }
  els.spKeysGroups.innerHTML = "";
  for (const [grupo, items] of byGroup) {
    const wrap = document.createElement("div");
    wrap.className = "toolbar";
    wrap.style.flexWrap = "wrap";
    wrap.style.gap = "6px";
    wrap.style.marginBottom = "4px";
    const label = document.createElement("span");
    label.className = "sutil";
    label.style.marginLeft = "0";
    label.style.minWidth = "110px";
    label.textContent = grupo;
    wrap.appendChild(label);
    for (const cmd of items) {
      const btn = document.createElement("button");
      btn.type = "button";
      btn.title = cmd.atajo;
      btn.disabled = !CAN_EDIT;
      btn.innerHTML = (cmd.icono ? `<img src="/static/ajuste/img/espectro/${esc(cmd.slug)}.png" alt="" width="16" height="16" style="vertical-align:middle;margin-right:4px;">` : "")
        + esc(cmd.etiqueta);
      btn.addEventListener("click", () => sendSpectroKey(cmd.slug, btn));
      wrap.appendChild(btn);
    }
    els.spKeysGroups.appendChild(wrap);
  }
  renderKeysVisibilityList();
}

// ---------- Lista de visibilidad de la botonera (dentro de "Opciones Spectro") ----------
// Checklist de los comandos para sacar de la botonera los que no se usan en el día a día -- ver POST
// /spectro-auto/keys/visibility. La lista de deshabilitados es compartida (vive en la sesión), así que lo
// que se desmarca ahí se va de la botonera para todos los dispositivos.
let spKeysVisibilitySaving = false;

function renderKeysVisibilityList() {
  if (!els.spKeysVisibility) return;
  const byGroup = new Map();
  for (const cmd of spKeyCommands) {
    if (!byGroup.has(cmd.grupo)) byGroup.set(cmd.grupo, []);
    byGroup.get(cmd.grupo).push(cmd);
  }
  els.spKeysVisibility.innerHTML = "";
  for (const [grupo, items] of byGroup) {
    const wrap = document.createElement("div");
    wrap.style.marginBottom = "6px";
    const title = document.createElement("div");
    title.className = "sutil";
    title.style.marginLeft = "0";
    title.textContent = grupo;
    wrap.appendChild(title);
    for (const cmd of items) {
      const row = document.createElement("label");
      row.style.display = "inline-flex";
      row.style.alignItems = "center";
      row.style.gap = "4px";
      row.style.marginRight = "12px";
      row.style.fontSize = "0.9em";
      const chk = document.createElement("input");
      chk.type = "checkbox";
      chk.checked = cmd.activo !== false;
      chk.disabled = !CAN_EDIT;
      chk.addEventListener("change", () => toggleSpectroKeyVisibility(cmd.slug, chk.checked));
      row.appendChild(chk);
      row.appendChild(document.createTextNode(cmd.etiqueta));
      wrap.appendChild(row);
    }
    els.spKeysVisibility.appendChild(wrap);
  }
}

async function toggleSpectroKeyVisibility(slug, checked) {
  if (spKeysVisibilitySaving) return;
  spKeysVisibilitySaving = true;
  const cmd = spKeyCommands.find((c) => c.slug === slug);
  if (cmd) cmd.activo = checked;
  const disabled = spKeyCommands.filter((c) => c.activo === false).map((c) => c.slug);
  try {
    await Ajuste.apiFetch("/api/ajuste/spectro-auto/keys/visibility", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ disabled }),
    });
    renderSpectroKeys();
  } catch (ex) {
    els.spKeysStatus.textContent = `Error guardando visibilidad: ${ex.detail?.message || ex.message}`;
  } finally {
    spKeysVisibilitySaving = false;
  }
}

async function sendSpectroKey(slug, btn) {
  if (spKeySending) return;
  spKeySending = true;
  if (btn) btn.disabled = true;
  els.spKeysStatus.textContent = `Enviando ${slug}...`;
  try {
    const res = await Ajuste.apiFetch("/api/ajuste/spectro-auto/send-key", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ cmd: slug }),
    });
    els.spKeysStatus.textContent = res.ok ? `OK (${res.sent || ""})` : `Error: ${res.error || ""}`;
  } catch (ex) {
    els.spKeysStatus.textContent = `Error: ${ex.detail?.message || ex.message}`;
  } finally {
    spKeySending = false;
    if (btn) btn.disabled = !CAN_EDIT;
  }
}

// ---------- Vista ----------

VISTAS.ajuste = async () => {
  $("#vista").innerHTML = `<div class="vista-ajuste">
    <div class="encabezado"><h2>Ajuste</h2></div>
    <div class="tarjeta">
      <div class="toolbar" style="flex-wrap:wrap;">
        <div><label>N° colada</label><br><input id="f-colada" type="text" placeholder="0001 /26" style="width:110px"></div>
        <div><label>Aleación objetivo (Aleación propia)</label><br><select id="f-objective" style="width:220px"></select></div>
        <div><label>Masa del baño (kg)</label><br><input id="f-mass" type="text" style="width:100px"></div>
        <button id="btn-load-actual">Cargar actual desde catálogo…</button>
        <span id="cucharas-badge" class="ce-badge" title="Cucharas cargadas al horno en esta colada, según Pie de Horno"></span>
        <span id="session-status" class="toolbar-status sutil"></span>
      </div>
      <div class="toolbar" style="flex-wrap:wrap;margin-top:8px;">
        <label>Método
          <select id="f-method"><option>Greedy</option><option>Lineal</option></select>
        </label>
        <label>% del plan
          <input id="f-pct" type="number" min="1" max="100" value="100" style="width:64px">
        </label>
        <button id="btn-calc" class="primario">Calcular</button>
        <button id="btn-apply" class="primario">Aplicar</button>
        <button id="btn-cambio-base" title="A partir de la composición Estimada actual, calcular qué agregar para llegar a otro material objetivo, sin tocar la sesión en curso">Cambio de base…</button>
        <button id="btn-carbomax-auto">Carbomax automático</button>
        <button id="btn-carbomax-config">Configurar Carbomax…</button>
        <span style="flex:1"></span>
        <button id="btn-reset">Reiniciar ajuste</button>
        <button id="btn-cancel-session" class="peligro">Cancelar sesión</button>
        <button id="btn-save-session">Guardar sesión (terminar colada)</button>
      </div>
      <div id="status" class="sutil"></div>
    </div>

    <div id="panels">
      <section class="tarjeta panel" data-panel="actual">
        <div class="panel-head">
          <h3 class="drag-handle" draggable="true" title="Arrastrar para reordenar">Actual (%) <span id="ce-actual" class="ce-badge"></span></h3>
        </div>
        <div id="grid-actual" class="grid-elements comp-grid"></div>
        <div class="leyenda-elementos sutil">
          <label class="familia-efectos" title="Algunos elementos actúan distinto en gris y en nodular. Cambia solo al elegir una base objetivo (según el catálogo de Calidad).">
            Efectos en <select id="sel-familia-efectos"><option value="Gris">Gris</option><option value="Nodular">Nodular</option></select>
          </label>
          <span><b class="el-ferrita">■</b> pro ferrita</span>
          <span><b class="el-perlita">■</b> pro perlita</span>
          <span><b class="el-carburo">■</b> perlita + carburos</span>
          <span><b class="el-neutro">■</b> neutro</span>
          <span><b class="el-riesgo-crisol">&nbsp;&nbsp;&nbsp;</b> riesgo para el crisol en carga fría</span>
          <span>(pasá el mouse por un elemento para ver el detalle)</span>
        </div>
      </section>

      <section class="tarjeta panel" data-panel="estimado">
        <div class="panel-head">
          <h3 class="drag-handle" draggable="true" title="Arrastrar para reordenar">Estimado (%) <span id="ce-estimado" class="ce-badge"></span></h3>
        </div>
        <div class="sutil" id="mass-estimada" style="margin-bottom:6px;"></div>
        <div id="grid-estimado" class="grid-elements comp-grid"></div>
      </section>

      <section class="tarjeta panel" data-panel="objetivo">
        <div class="panel-head">
          <h3 class="drag-handle" draggable="true" title="Arrastrar para reordenar">Objetivo (%) <span id="ce-objetivo" class="ce-badge"></span></h3>
        </div>
        <div id="grid-objetivo" class="grid-elements comp-grid"></div>
      </section>

      <section class="tarjeta panel" data-panel="espectro">
        <div class="panel-head">
          <h3 class="drag-handle" draggable="true" title="Arrastrar para reordenar">Espectrómetro <span id="spectro-conn-badge" class="ce-badge"></span> <span id="sp-measuring-badge" class="ce-badge" hidden></span></h3>
          <button id="sp-btn-options" type="button" style="margin-left:auto;">Opciones Spectro</button>
        </div>

        <div id="sp-options" hidden>
          <div class="toolbar" style="flex-wrap:wrap;gap:6px;">
            <div><label>Host / IP</label><br><input id="sp-host" type="text" style="width:130px"></div>
            <div><label>Puerto comandos</label><br><input id="sp-cmdport" type="number" min="1" max="65535" style="width:90px"></div>
            <div><label>Puerto eventos</label><br><input id="sp-evtport" type="number" min="1" max="65535" style="width:90px"></div>
            <button id="sp-btn-config" type="button">Guardar conexión</button>
            <button id="sp-btn-test" type="button">Probar</button>
            <button id="sp-btn-connect" type="button">Conectar</button>
            <button id="sp-btn-force-reconnect" type="button">Forzar reconexión</button>
          </div>
          <div id="sp-test-result" class="sutil"></div>

          <h4 style="margin:10px 0 4px;">Botón "Medir ahora"</h4>
          <label style="display:inline-flex;align-items:center;gap:6px;font-size:0.9em;">
            <input id="sp-chk-hide-measure" type="checkbox">
            Ocultar "Medir ahora" (nunca funciona sin licencia Full del control remoto)
          </label>

          <h4 style="margin:10px 0 4px;">Botones visibles en la botonera</h4>
          <p class="sutil" style="margin:0 0 6px;">Desmarcá los que no uses en el día a día — se van de la botonera para todos los dispositivos.</p>
          <div id="sp-keys-visibility"></div>
        </div>

        <div id="sp-alerts" style="display:flex;flex-direction:column;gap:3px;margin:8px 0;"></div>

        <div id="sp-instrument-state" class="row" style="flex-wrap:wrap;gap:6px;margin:8px 0;"></div>

        <div class="toolbar" style="flex-wrap:wrap;gap:6px;align-items:flex-end;">
          <div><label>Método activo</label><br>
            <select id="sp-method-select" style="width:170px;"></select></div>
          <button id="sp-btn-select-method" type="button">Activar método</button>

          <div><label>Perfil activo</label><br>
            <select id="sp-profile-select" style="width:170px;"></select></div>
          <button id="sp-btn-select-profile" type="button">Activar perfil</button>

          <div><label>ID de muestra</label><br>
            <input id="sp-sample-name" type="text" style="width:150px;"></div>
          <button id="sp-btn-measure" class="primario" type="button">Medir ahora</button>

          <button id="sp-btn-refresh-methods" type="button">Actualizar lista</button>
        </div>
        <div id="sp-ical-warning" class="error"></div>

        <h4 style="margin:10px 0 4px;">Otros comandos (funcionan en modo "Limited")</h4>
        <div class="toolbar" style="flex-wrap:wrap;gap:6px;">
          <button id="sp-btn-stop-measure" class="peligro" type="button">Detener medición</button>
          <button id="sp-btn-start-flush" type="button">Iniciar Flush</button>
          <button id="sp-btn-stop-flush" type="button">Detener Flush</button>
        </div>
        <div id="sp-measure-status" class="sutil"></div>

        <h4 style="margin:10px 0 4px;">Botonera (control remoto por teclado)</h4>
        <p class="sutil" style="margin:0 0 6px;">
          Manda la tecla al instrumento como si se apretara en su propio teclado — alternativa a "Medir ahora"
          cuando el control remoto está en modo "Limited". Requiere LMX06MeasurementGUI abierto en esa PC.
        </p>
        <div id="sp-keys-status" class="sutil"></div>
        <div id="sp-keys-groups"></div>

        <h4 style="margin:10px 0 4px;">Últimas mediciones <span id="sp-recent-count" class="ce-badge"></span></h4>
        <table>
          <thead><tr><th>Hora</th><th>Colada</th><th>Origen</th><th>Elementos</th><th style="width:110px"></th></tr></thead>
          <tbody id="sp-recent-rows"></tbody>
        </table>
      </section>

      <section class="tarjeta panel" data-panel="carbomax">
        <div class="toolbar">
          <h3 class="drag-handle" draggable="true" title="Arrastrar para reordenar" style="margin:0;">Carbomax — últimos análisis <span id="cx-recent-count" class="ce-badge"></span></h3>
          <button type="button" id="btn-carbomax-check-now">Forzar</button>
          <span id="cx-check-now-status" class="sutil toolbar-status"></span>
        </div>
        <table>
          <thead><tr><th>Hora</th><th>Colada</th><th>C %</th><th>Si %</th><th>Fuente</th><th></th></tr></thead>
          <tbody id="cx-recent-rows"></tbody>
        </table>
      </section>

      <section class="tarjeta panel" data-panel="grafico">
        <div class="toolbar">
          <h3 class="drag-handle" draggable="true" title="Arrastrar para reordenar" style="margin:0;">Gráfico C / Si (centrado en el objetivo)</h3>
          <label><input type="checkbox" id="chk-blue-points"> Puntos violeta (arranques históricos)</label>
          <label><input type="checkbox" id="chk-orange-points"> Puntos naranja (deriva histórica)</label>
          <span class="sutil toolbar-status">Rueda: zoom · arrastrar: pan · doble click: resetear vista</span>
        </div>
        <div class="graph-wrap"><canvas id="graph-canvas"></canvas></div>
      </section>

      <section class="tarjeta panel" data-panel="materiales">
        <div class="toolbar">
          <h3 class="drag-handle" draggable="true" title="Arrastrar para reordenar" style="margin:0;">Materiales de ajuste</h3>
          <span id="warning-msg" class="error toolbar-status"></span>
        </div>
        <table>
          <thead><tr><th>Material</th><th style="width:140px">kg a agregar</th><th style="width:40px"></th></tr></thead>
          <tbody id="adjust-rows"></tbody>
        </table>
      </section>

      <section class="tarjeta panel" data-panel="historial">
        <div class="panel-head">
          <h3 class="drag-handle" draggable="true" title="Arrastrar para reordenar">Historial de ajustes de esta sesión</h3>
        </div>
        <table>
          <thead><tr><th>Fecha</th><th>Objetivo</th><th>Materiales</th><th>Cambios principales</th><th>CE inicial → estimado (objetivo)</th></tr></thead>
          <tbody id="hist-rows"></tbody>
        </table>
      </section>
    </div>
  </div>`;

  els = {
    colada: document.getElementById("f-colada"),
    objective: document.getElementById("f-objective"),
    mass: document.getElementById("f-mass"),
    btnLoadActual: document.getElementById("btn-load-actual"),
    sessionStatus: document.getElementById("session-status"),
    status: document.getElementById("status"),
    gridActual: document.getElementById("grid-actual"),
    gridEstimado: document.getElementById("grid-estimado"),
    gridObjetivo: document.getElementById("grid-objetivo"),
    ceActual: document.getElementById("ce-actual"),
    ceEstimado: document.getElementById("ce-estimado"),
    ceObjetivo: document.getElementById("ce-objetivo"),
    massEstimada: document.getElementById("mass-estimada"),
    method: document.getElementById("f-method"),
    pct: document.getElementById("f-pct"),
    warningMsg: document.getElementById("warning-msg"),
    adjustRows: document.getElementById("adjust-rows"),
    btnCalc: document.getElementById("btn-calc"),
    btnApply: document.getElementById("btn-apply"),
    btnCambioBase: document.getElementById("btn-cambio-base"),
    btnReset: document.getElementById("btn-reset"),
    btnCancelSession: document.getElementById("btn-cancel-session"),
    btnSaveSession: document.getElementById("btn-save-session"),
    btnCarbomaxAuto: document.getElementById("btn-carbomax-auto"),
    btnCarbomaxConfig: document.getElementById("btn-carbomax-config"),
    btnCarbomaxCheckNow: document.getElementById("btn-carbomax-check-now"),
    cxCheckNowStatus: document.getElementById("cx-check-now-status"),
    cxRecentCount: document.getElementById("cx-recent-count"),
    cxRecentRows: document.getElementById("cx-recent-rows"),
    spConnBadge: document.getElementById("spectro-conn-badge"),
    spMeasuringBadge: document.getElementById("sp-measuring-badge"),
    spBtnOptions: document.getElementById("sp-btn-options"),
    spOptionsPanel: document.getElementById("sp-options"),
    spKeysVisibility: document.getElementById("sp-keys-visibility"),
    spHost: document.getElementById("sp-host"),
    spCmdPort: document.getElementById("sp-cmdport"),
    spEvtPort: document.getElementById("sp-evtport"),
    spBtnConfig: document.getElementById("sp-btn-config"),
    spBtnTest: document.getElementById("sp-btn-test"),
    spBtnConnect: document.getElementById("sp-btn-connect"),
    spBtnForceReconnect: document.getElementById("sp-btn-force-reconnect"),
    spTestResult: document.getElementById("sp-test-result"),
    spInstrumentState: document.getElementById("sp-instrument-state"),
    spMethodSelect: document.getElementById("sp-method-select"),
    spProfileSelect: document.getElementById("sp-profile-select"),
    spBtnSelectMethod: document.getElementById("sp-btn-select-method"),
    spBtnSelectProfile: document.getElementById("sp-btn-select-profile"),
    spBtnRefreshMethods: document.getElementById("sp-btn-refresh-methods"),
    spIcalWarning: document.getElementById("sp-ical-warning"),
    spSampleName: document.getElementById("sp-sample-name"),
    spBtnMeasure: document.getElementById("sp-btn-measure"),
    spChkHideMeasure: document.getElementById("sp-chk-hide-measure"),
    spBtnStopMeasure: document.getElementById("sp-btn-stop-measure"),
    spBtnStartFlush: document.getElementById("sp-btn-start-flush"),
    spBtnStopFlush: document.getElementById("sp-btn-stop-flush"),
    spMeasureStatus: document.getElementById("sp-measure-status"),
    spRecentRows: document.getElementById("sp-recent-rows"),
    spRecentCount: document.getElementById("sp-recent-count"),
    spKeysStatus: document.getElementById("sp-keys-status"),
    spKeysGroups: document.getElementById("sp-keys-groups"),
    spAlerts: document.getElementById("sp-alerts"),
    histRows: document.getElementById("hist-rows"),
    graphCanvas: document.getElementById("graph-canvas"),
    chkBluePoints: document.getElementById("chk-blue-points"),
    chkOrangePoints: document.getElementById("chk-orange-points"),
    cucharasBadge: document.getElementById("cucharas-badge"),
  };

  graphView = createGraphView(els.graphCanvas);
  makeReorderable("panels", "ajuste", ["grafico", "materiales", "historial"]);

  // En el contenedor de esta vista (se crea de nuevo en cada visita), no en #vista: #vista es del núcleo y vive
  // siempre, así que cada entrada a Ajuste le sumaría otro listener que seguiría andando en las demás pantallas.
  document.querySelector(".vista-ajuste").addEventListener("focusout", _alSalirDeCasilla);
  const selFamilia = document.getElementById("sel-familia-efectos");
  selFamilia.value = _familiaEfectos;
  selFamilia.addEventListener("change", () => _elegirFamiliaEfectos(selFamilia.value));
  els.chkBluePoints.addEventListener("change", () => graphView.setShowBlue(els.chkBluePoints.checked));
  els.chkOrangePoints.addEventListener("change", () => graphView.setShowOrange(els.chkOrangePoints.checked));

  els.objective.addEventListener("change", () => scheduleSave({ objective: els.objective.value }, { immediate: true }));
  els.colada.addEventListener("input", () => scheduleSave({ colada: els.colada.value }));
  els.mass.addEventListener("input", () => scheduleSave({ mass: parseNum(els.mass.value, 0) }));
  els.method.addEventListener("change", () => scheduleSave({ method: els.method.value }, { immediate: true }));
  els.pct.addEventListener("change", () => scheduleSave({ partial_pct: parseNum(els.pct.value, 100) }, { immediate: true }));

  els.btnLoadActual.addEventListener("click", openLoadActualModal);
  els.btnCambioBase.addEventListener("click", openCambioBaseModal);

  els.btnCalc.addEventListener("click", () => runAction("/api/ajuste/estimate", { pct: parseNum(els.pct.value, 100) }, { successMsg: "Plan calculado." }));
  els.btnApply.addEventListener("click", () => runAction("/api/ajuste/apply", {}, { successMsg: "Aplicado." }));
  els.btnReset.addEventListener("click", () => {
    if (!confirm("Esto borra el historial de ajustes de la sesión en curso y reinicia masa/kg. ¿Continuar?")) return;
    runAction("/api/ajuste/reset", {}, { successMsg: "Ajuste reiniciado." });
  });
  els.btnCancelSession.addEventListener("click", () => {
    if (!confirm("Esto cancela el inicio de sesión (objetivo y cronómetro) sin guardar nada en Históricos. ¿Continuar?")) return;
    runAction("/api/ajuste/cancel-session", {}, { successMsg: "Sesión cancelada." });
  });
  els.btnSaveSession.addEventListener("click", () => {
    if (!confirm("Esto manda los ajustes de la sesión en curso a Históricos y arranca una colada nueva. ¿Continuar?")) return;
    runAction("/api/ajuste/save-session", {}, { successMsg: "Sesión guardada." });
  });

  els.btnCarbomaxAuto.addEventListener("click", async () => {
    const enabled = !SESSION.carbomax_auto;
    if (enabled && (!SESSION.carbomax_base_names || SESSION.carbomax_base_names.length !== 3)) {
      alert('Antes de prenderlo, configurá los 3 materiales C/Si/Fe con "Configurar Carbomax…".');
      return;
    }
    try {
      SESSION = await Ajuste.apiFetch("/api/ajuste/carbomax-auto/toggle", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }),
      });
      render();
      setStatus(enabled ? "Carbomax automático activado." : "Carbomax automático desactivado.", "ok");
    } catch (ex) {
      setStatus(`Error: ${ex.message}`, "error");
    }
  });

  els.btnCarbomaxCheckNow.addEventListener("click", async () => {
    els.btnCarbomaxCheckNow.disabled = true;
    els.cxCheckNowStatus.textContent = "Buscando...";
    els.cxCheckNowStatus.className = "sutil toolbar-status";
    try {
      const res = await Ajuste.apiFetch("/api/ajuste/carbomax-auto/check-now", { method: "POST" });
      const errorStands = Object.keys(res.errors || {});
      if (res.new_records > 0) {
        els.cxCheckNowStatus.textContent = `Encontrado: ${res.new_records} análisis nuevo${res.new_records === 1 ? "" : "s"} — agregado a la lista.`;
        els.cxCheckNowStatus.className = "toolbar-status";
        // El broadcast "carbomax_result" del backend ya dispara reload() en esta y en las demás pantallas --
        // no hace falta pedirlo de nuevo acá.
      } else if (errorStands.length) {
        els.cxCheckNowStatus.textContent = `Sin novedades. Error leyendo stand ${errorStands.join(", ")}: ${res.errors[errorStands[0]]}`;
        els.cxCheckNowStatus.className = "error toolbar-status";
      } else {
        els.cxCheckNowStatus.textContent = "Sin novedades — todavía no hay un análisis nuevo en los stands.";
      }
    } catch (ex) {
      els.cxCheckNowStatus.textContent = `Error: ${ex.detail?.message || ex.message}`;
      els.cxCheckNowStatus.className = "error toolbar-status";
    } finally {
      els.btnCarbomaxCheckNow.disabled = !CAN_EDIT;
    }
  });

  els.btnCarbomaxConfig.addEventListener("click", openCarbomaxConfigModal);

  els.spBtnOptions.addEventListener("click", () => {
    const hidden = els.spOptionsPanel.hasAttribute("hidden");
    if (hidden) els.spOptionsPanel.removeAttribute("hidden");
    else els.spOptionsPanel.setAttribute("hidden", "");
    els.spBtnOptions.textContent = hidden ? "Ocultar opciones" : "Opciones Spectro";
  });

  els.spChkHideMeasure.addEventListener("change", async () => {
    const hidden = els.spChkHideMeasure.checked;
    els.spChkHideMeasure.disabled = true;
    try {
      SESSION = await Ajuste.apiFetch("/api/ajuste/spectro-auto/hide-measure-button", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ hidden }),
      });
      render();
    } catch (ex) {
      setStatus(`Error guardando la preferencia: ${ex.detail?.message || ex.message}`, "error");
      els.spChkHideMeasure.checked = !hidden;
    } finally {
      els.spChkHideMeasure.disabled = !CAN_EDIT;
    }
  });

  els.spBtnConfig.addEventListener("click", async () => {
    const host = els.spHost.value.trim();
    if (!host) { setStatus("Ingresá el host/IP del espectrómetro.", "error"); return; }
    try {
      SESSION = await Ajuste.apiFetch("/api/ajuste/spectro-auto/config", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host,
          commands_port: parseNum(els.spCmdPort.value, 11000),
          events_port: parseNum(els.spEvtPort.value, 11001),
        }),
      });
      render();
      setStatus("Espectrómetro configurado.", "ok");
    } catch (ex) {
      setStatus(`Error: ${ex.detail?.message || ex.message}`, "error");
    }
  });

  els.spBtnTest.addEventListener("click", async () => {
    els.spTestResult.textContent = "Probando...";
    try {
      const res = await Ajuste.apiFetch("/api/ajuste/spectro-auto/test", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          host: els.spHost.value.trim(),
          commands_port: parseNum(els.spCmdPort.value, 11000),
        }),
      });
      els.spTestResult.textContent = `OK — versión del instrumento: ${res.version || "(desconocida)"}`;
    } catch (ex) {
      els.spTestResult.textContent = `Error: ${ex.detail?.message || ex.message}`;
    }
  });

  els.spBtnConnect.addEventListener("click", async () => {
    const enabled = !SESSION.spectro_auto;
    if (enabled && !SESSION.spectro_host) {
      alert("Antes de conectar, guardá el host/IP del espectrómetro.");
      return;
    }
    try {
      SESSION = await Ajuste.apiFetch("/api/ajuste/spectro-auto/toggle", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ enabled }),
      });
      render();
      setStatus(enabled ? "Espectrómetro conectado." : "Espectrómetro desconectado.", "ok");
      if (enabled) { refreshSpectroInstrument(); refreshSpectroMethodsProfiles(); }
    } catch (ex) {
      setStatus(`Error: ${ex.detail?.message || ex.message}`, "error");
    }
  });

  els.spBtnForceReconnect.addEventListener("click", async () => {
    // Distinto de Conectar/Desconectar: no depende de que el usuario sepa si el toggle está prendido o no --
    // siempre prende spectro_auto (si estaba apagado) Y tira el listener actual para que arranque uno nuevo.
    // También limpia "Midiendo.../Calculando..." si había quedado pegado.
    try {
      SESSION = await Ajuste.apiFetch("/api/ajuste/spectro-auto/reconnect", { method: "POST" });
      render();
      setStatus("Reconexión forzada — reconectando con el espectrómetro.", "ok");
      refreshSpectroInstrument();
      refreshSpectroMethodsProfiles();
    } catch (ex) {
      setStatus(`Error: ${ex.detail?.message || ex.message}`, "error");
    }
  });

  els.spBtnRefreshMethods.addEventListener("click", () => {
    refreshSpectroInstrument();
    refreshSpectroMethodsProfiles();
  });

  els.spBtnSelectMethod.addEventListener("click", async () => {
    const methodName = els.spMethodSelect.value;
    const m = spectroState.methods.find((x) => x.method_name === methodName);
    if (!m) return;
    try {
      const res = await Ajuste.apiFetch("/api/ajuste/spectro-auto/select-method", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ excitation_type: m.excitation_type, base_element: m.base_element, method_name: m.method_name }),
      });
      els.spIcalWarning.textContent = (res.pending_ical || []).length
        ? `Este método necesita calibración ICal antes de medir de forma confiable (${res.pending_ical.map((i) => i.name).join(", ")}).`
        : "";
      setStatus(`Método "${methodName}" activado.`, "ok");
      refreshSpectroMethodsProfiles();
    } catch (ex) {
      setStatus(`Error: ${ex.detail?.message || ex.message}`, "error");
    }
  });

  els.spBtnSelectProfile.addEventListener("click", async () => {
    const profileName = els.spProfileSelect.value;
    if (!profileName) return;
    try {
      const res = await Ajuste.apiFetch("/api/ajuste/spectro-auto/select-profile", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ profile_name: profileName }),
      });
      els.spIcalWarning.textContent = (res.pending_ical || []).length
        ? `Este perfil necesita calibración ICal antes de medir de forma confiable (${res.pending_ical.map((i) => i.name).join(", ")}).`
        : "";
      setStatus(`Perfil "${profileName}" activado.`, "ok");
      refreshSpectroMethodsProfiles();
    } catch (ex) {
      setStatus(`Error: ${ex.detail?.message || ex.message}`, "error");
    }
  });

  els.spBtnMeasure.addEventListener("click", async () => {
    els.spBtnMeasure.disabled = true;
    els.spMeasureStatus.textContent = "Midiendo... (puede tardar varios segundos)";
    try {
      const res = await Ajuste.apiFetch("/api/ajuste/spectro-auto/measure", {
        method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sample_name: els.spSampleName.value.trim() }),
      });
      els.spMeasureStatus.textContent = res.message || "";
      setStatus(res.message || "", res.ok ? "ok" : "error");
      await reload();
    } catch (ex) {
      els.spMeasureStatus.textContent = `Error: ${ex.detail?.message || ex.message}`;
      setStatus(`Error: ${ex.detail?.message || ex.message}`, "error");
    } finally {
      els.spBtnMeasure.disabled = !CAN_EDIT || spectroState.remoteControlMode !== "Full";
    }
  });

  // A diferencia de "Medir ahora", no se deshabilita según remoteControlMode -- el manual no dice que
  // StopMeasure necesite licencia Full (es el único comando pensado para usarse mientras otra conexión está
  // bloqueada midiendo), así que si el instrumento la rechaza en Limited, el error va a salir solo del lado
  // del protocolo -- no vale la pena adivinar acá.
  els.spBtnStopMeasure.addEventListener("click", async () => {
    els.spBtnStopMeasure.disabled = true;
    try {
      await Ajuste.apiFetch("/api/ajuste/spectro-auto/stop-measure", { method: "POST" });
      setStatus("Espectrómetro: medición detenida.", "ok");
    } catch (ex) {
      setStatus(`Error deteniendo la medición: ${ex.detail?.message || ex.message}`, "error");
    } finally {
      els.spBtnStopMeasure.disabled = !CAN_EDIT;
    }
  });

  els.spBtnStartFlush.addEventListener("click", async () => {
    els.spBtnStartFlush.disabled = true;
    try {
      await Ajuste.apiFetch("/api/ajuste/spectro-auto/start-flush", { method: "POST" });
      setStatus("Espectrómetro: flush iniciado.", "ok");
    } catch (ex) {
      setStatus(`Error iniciando el flush: ${ex.detail?.message || ex.message}`, "error");
    } finally {
      els.spBtnStartFlush.disabled = !CAN_EDIT;
    }
  });

  els.spBtnStopFlush.addEventListener("click", async () => {
    els.spBtnStopFlush.disabled = true;
    try {
      await Ajuste.apiFetch("/api/ajuste/spectro-auto/stop-flush", { method: "POST" });
      setStatus("Espectrómetro: flush detenido.", "ok");
    } catch (ex) {
      setStatus(`Error deteniendo el flush: ${ex.detail?.message || ex.message}`, "error");
    } finally {
      els.spBtnStopFlush.disabled = !CAN_EDIT;
    }
  });

  // Desconecta cualquier WS que haya quedado de una visita anterior a esta vista -- si no, cada entrada a
  // "Ajuste" deja un socket viejo abierto para siempre.
  _wsDisconnects.forEach((fn) => fn());
  _wsDisconnects = [];

  Ajuste.waitForApproval(async (status) => {
    CAN_EDIT = status.role === "editor" || status.dev_skip_approval;
    if (!CAN_EDIT) {
      [els.btnLoadActual, els.btnCalc, els.btnApply, els.btnCambioBase,
        els.btnReset, els.btnCancelSession, els.btnSaveSession,
        els.btnCarbomaxAuto, els.btnCarbomaxConfig, els.btnCarbomaxCheckNow,
        els.spBtnConfig, els.spBtnConnect, els.spBtnForceReconnect, els.spBtnSelectMethod, els.spBtnSelectProfile,
        els.spBtnMeasure, els.spBtnStopMeasure, els.spBtnStartFlush, els.spBtnStopFlush].forEach((b) => { b.disabled = true; });
      setStatus("Solo lectura (rol viewer).");
    }
    await loadMeta();
    await reload();
    loadSpectroKeys();
    loadCucharasCounter();
    if (SESSION.spectro_auto) { refreshSpectroInstrument(); refreshSpectroMethodsProfiles(); }
    _wsDisconnects.push(Ajuste.wsConnect("kiosk", () => loadCucharasCounter()));
    _wsDisconnects.push(Ajuste.wsConnect("ajuste", (msg) => {
      if (msg && msg.type === "carbon_detected") {
        if (CAN_EDIT) openCarbonDetectedModal(msg);
        return;
      }
      if (msg && msg.type === "carbomax_result") {
        // El análisis ya se guardó en carbomax_recent_records del lado del backend -- alcanza con recargar
        // la sesión para que la lista se actualice sola, no hace falta un popup.
        setStatus(`Carbomax: nuevo análisis (${msg.source_name || ""}).`, "ok");
        if (!suppressReload) reload();
        return;
      }
      if (msg && msg.type === "spectro_result") {
        // El resultado ya se guardó en spectro_recent_results del lado del backend -- alcanza con recargar
        // la sesión para que la tabla se actualice sola, no hace falta un popup.
        setStatus(`Espectrómetro: nueva medición (${msg.source_name || ""}).`, "ok");
        if (!suppressReload) reload();
        return;
      }
      if (msg && msg.type === "spectro_alert") {
        const style = ALERT_STYLE[msg.kind] || { label: msg.kind || "Alerta" };
        setStatus(`Espectrómetro — ${style.label}: ${msg.name || msg.kind}`, msg.kind === "ProcessError" ? "error" : "");
        if (!suppressReload) reload();
        return;
      }
      if (msg && msg.type === "spectro_alert_resolved") {
        // Resuelta por CUALQUIER vía -- parado frente al instrumento o por la web, en otro dispositivo. No
        // hay "flash" verde para este caso (no fue esta pantalla la que resolvió), solo se refresca para que
        // deje de mostrar botones.
        setStatus(`Espectrómetro: "${msg.name}" ya se resolvió (${msg.resolved_option || "sin opción"}).`, "ok");
        if (!suppressReload) reload();
        return;
      }
      if (msg && msg.type === "spectro_instrument_state") {
        spectroState.instrumentState = msg.state || {};
        spectroState.remoteControlMode = msg.remote_control_mode || "";
        renderInstrumentStateBadges();
        els.spBtnMeasure.disabled = !CAN_EDIT || spectroState.remoteControlMode !== "Full";
        return;
      }
      if (msg && msg.type === "spectro_measuring") {
        SESSION.spectro_measuring = msg.phase || false;
        updateMeasuringBadge(SESSION.spectro_measuring);
        return;
      }
      if (msg && msg.type === "spectro_connected") {
        SESSION.spectro_connected = !!msg.connected;
        updateConnBadge();
        return;
      }
      if (msg && msg.type === "status_message") {
        setStatus(msg.message || "");
        if (!suppressReload) reload();
        return;
      }
      if (!suppressReload) reload();
    }));
  });
};
