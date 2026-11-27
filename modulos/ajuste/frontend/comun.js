// comun.js -- puerto de frontend/js/common.js de ajuste_comp_web: identidad de dispositivo (headers
// X-Pie-Device-Id/Name) + apiFetch + waitForApproval + wsConnect, compartido por todas las pantallas de este
// módulo. Tiene que cargar ANTES que cualquier otro script del módulo (scripts=["comun.js", "dashboard.js", ...]
// en __init__.py) y no usar import/export -- a diferencia de la app vieja, el núcleo concatena los scripts como
// <script> sueltos (sin type="module"), igual que nucleo.js/ayuda.js. Todo cuelga de un solo objeto global
// "Ajuste" en vez de nombres sueltos -- test_pantallas.py (lo trae sincronizar.py) falla si dos módulos declaran el
// mismo global, y esta app va a tener muchos scripts en el mismo scope.
//
// MISMAS claves de localStorage que la app vieja (a propósito): un navegador que ya tenía un device_id aprobado
// contra ajuste_comp_web sigue aprobado tal cual al pasar a esta URL nueva, sin que un administrador tenga que
// volver a aprobar cada PC/tablet de planta.
const Ajuste = {};

// ---------- Modo oscuro ----------
// Se guarda por navegador (cada PC/tablet de planta elige el suyo). Sin elección guardada arranca en claro, como
// siempre -- no se sigue la preferencia del sistema para que ninguna PC cambie sola de aspecto. Los colores están
// en comun.css (html[data-tema="oscuro"]). Los gráficos dibujan en <canvas>, que no ve el CSS: piden sus colores
// a Ajuste.coloresGrafico() y escuchan el evento "ajuste:tema" para redibujarse al cambiar.
const TEMA_KEY = "ajuste_tema";

Ajuste.temaOscuro = function () {
  return document.documentElement.dataset.tema === "oscuro";
};

// avisar=false solo al cargar: todavía no hay gráficos que redibujar (y así tampoco depende de `Event`, que no
// existe en el chequeo sin navegador de tests/test_pantallas.py).
Ajuste.aplicarTema = function (oscuro, { avisar = true } = {}) {
  if (oscuro) document.documentElement.dataset.tema = "oscuro";
  else delete document.documentElement.dataset.tema;
  if (avisar) window.dispatchEvent(new Event("ajuste:tema"));
};

// La llama la tarjeta "Apariencia" de Opciones (settings.js).
Ajuste.elegirTema = function (oscuro) {
  localStorage.setItem(TEMA_KEY, oscuro ? "oscuro" : "claro");
  Ajuste.aplicarTema(oscuro);
};

// Colores neutros de los gráficos (fondo, grilla, ejes, textos) y los textos/rellenos que en claro eran muy oscuros
// para leerse sobre fondo oscuro. Los puntos y líneas de las series (azul, naranja, violeta, rojo...) quedan fijos
// en cada gráfico: tienen tono medio y se leen bien sobre los dos fondos.
Ajuste.coloresGrafico = function () {
  return Ajuste.temaOscuro()
    ? { fondo: "#1a2129", borde: "#3a4652", grilla: "#2a343f", eje: "#c5ced8", ejeSuave: "#6f7d8b",
        texto: "#e3e8ee", sutil: "#9aa6b2", serie: "#5c9ee0",
        areaObjetivo: "#1d3320", verdeLinea: "#66bb6a", verde: "#81c784", violeta: "#b39ddb", naranja: "#ffb74d" }
    : { fondo: "#ffffff", borde: "#d5d5d5", grilla: "#eeeeee", eje: "#333333", ejeSuave: "#8d99a6",
        texto: "#1d2733", sutil: "#66717d", serie: "#1f5f99",
        areaObjetivo: "#e8f5e9", verdeLinea: "#2e7d32", verde: "#1b5e20", violeta: "#5e35b1", naranja: "#e65100" };
};

// Se aplica apenas carga el script (antes de que el núcleo muestre la app) para no ver un destello en claro.
Ajuste.aplicarTema(localStorage.getItem(TEMA_KEY) === "oscuro", { avisar: false });

// ---------- Orden de las pestañas ----------
// El menú lo arma el núcleo en el servidor (Menu(..., orden=N) de cada módulo). Acá solo se reacomodan los <a> de
// #menu en el navegador según el orden que se eligió en Opciones > Pestañas (settings.js) -- por navegador, como el
// tema. Una pestaña que no figura en lo guardado (una pantalla nueva de una versión posterior) va al final, en su
// orden de fábrica, así nunca desaparece.
const ORDEN_PESTANAS_KEY = "ajuste_orden_pestanas";

Ajuste.ordenPestanasGuardado = function () {
  try {
    const v = JSON.parse(localStorage.getItem(ORDEN_PESTANAS_KEY) || "null");
    return Array.isArray(v) ? v : null;
  } catch (_) {
    return null;
  }
};

// Orden de fábrica: el del HTML que mandó el servidor, tomado una sola vez antes de reacomodar nada.
const _menu = document.getElementById("menu");
const _ordenFabrica = _menu ? [..._menu.querySelectorAll("a[data-vista]")].map((a) => a.dataset.vista) : [];

Ajuste.ordenFabricaPestanas = () => _ordenFabrica.slice();

Ajuste.aplicarOrdenPestanas = function (orden) {
  if (!_menu) return;
  const pos = new Map((orden || _ordenFabrica).map((vista, i) => [vista, i]));
  const enlaces = [..._menu.querySelectorAll("a[data-vista]")];
  enlaces.sort((a, b) => {
    const pa = pos.has(a.dataset.vista) ? pos.get(a.dataset.vista) : 1000 + _ordenFabrica.indexOf(a.dataset.vista);
    const pb = pos.has(b.dataset.vista) ? pos.get(b.dataset.vista) : 1000 + _ordenFabrica.indexOf(b.dataset.vista);
    return pa - pb;
  });
  enlaces.forEach((a) => _menu.appendChild(a));
};

// null = volver al orden de fábrica.
Ajuste.guardarOrdenPestanas = function (orden) {
  if (orden) localStorage.setItem(ORDEN_PESTANAS_KEY, JSON.stringify(orden));
  else localStorage.removeItem(ORDEN_PESTANAS_KEY);
  Ajuste.aplicarOrdenPestanas(orden);
};

Ajuste.aplicarOrdenPestanas(Ajuste.ordenPestanasGuardado());

const DEVICE_ID_KEY = "ajuste_web_device_id";
const DEVICE_NAME_KEY = "ajuste_web_device_name";

Ajuste.ensureDeviceIdentity = function () {
  let id = localStorage.getItem(DEVICE_ID_KEY) || "";
  if (!/^[A-Za-z0-9_.:-]{8,80}$/.test(id)) {
    id = (window.crypto && crypto.randomUUID) ? crypto.randomUUID()
      : `web-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 14)}`;
    localStorage.setItem(DEVICE_ID_KEY, id);
  }
  let name = localStorage.getItem(DEVICE_NAME_KEY) || "";
  if (!name.trim()) {
    const platform = navigator.platform || "Navegador";
    name = `${platform} ${id.slice(-6)}`;
    localStorage.setItem(DEVICE_NAME_KEY, name);
  }
  return { id, name };
};

Ajuste.deviceHeaders = function () {
  const { id, name } = Ajuste.ensureDeviceIdentity();
  return { "X-Pie-Device-Id": id, "X-Pie-Device-Name": name };
};

// Sesión del usuario logueado en el núcleo (misma clave que nucleo.js: "<prefijo>_token"). Solo existe dentro de la
// app principal (index.html del núcleo lleva data-prefijo); las páginas sueltas -- el kiosco de Pie de Horno, la
// cámara -- no la mandan y siguen dependiendo de la aprobación del dispositivo (ver devices.require_acceso).
Ajuste.sesionHeaders = function () {
  const prefijo = document.body && document.body.dataset.prefijo;
  if (!prefijo) return {};
  let token = null;
  try { token = localStorage.getItem(`${prefijo}_token`); } catch (_) { /* sin almacenamiento */ }
  return token ? { Authorization: `Bearer ${token}` } : {};
};

Ajuste.apiFetch = async function (url, options = {}) {
  const headers = { ...Ajuste.deviceHeaders(), ...Ajuste.sesionHeaders(), ...(options.headers || {}) };
  const response = await fetch(url, { ...options, headers, cache: "no-store" });
  if (!response.ok) {
    let detail = null;
    try { detail = await response.json(); } catch (_) { /* sin body JSON */ }
    const err = new Error(`HTTP ${response.status}`);
    err.status = response.status;
    err.detail = detail;
    throw err;
  }
  if (response.status === 204) return null;
  return response.json();
};

// Trazabilidad (ISO 9001): al eliminar un registro las pantallas piden el motivo y lo mandan en el header X-Motivo; el
// backend lo guarda en la bitácora junto con el contenido eliminado. Devuelve null si el usuario cancela, y obliga a
// escribir algo: una baja sin motivo no se puede explicar en una auditoría.
Ajuste.pedirMotivo = function (pregunta) {
  for (;;) {
    const m = prompt(`${pregunta}\n\nMotivo (queda registrado en la trazabilidad):`);
    if (m === null) return null;
    if (m.trim()) return m.trim();
    alert("Escribí el motivo para poder continuar.");
  }
};

Ajuste.headersMotivo = (motivo) => ({ "X-Motivo": encodeURIComponent(motivo || "") });

Ajuste.myDeviceStatus = async function () {
  return Ajuste.apiFetch("/api/devices/me");
};

/**
 * Se fija cada 4s si el dispositivo ya esta aprobado; mientras no lo este, muestra un aviso simple y bloquea el
 * resto de la pantalla. Cada vista lo llama al arrancar; el callback recibe el status una vez que queda aprobado
 * ("approved") -- o de una si el backend tiene prendido dev_skip_approval.
 */
// Con un usuario logueado (status.por_usuario) no se espera nada: la aprobación por dispositivo es solo para el kiosco
// de Pie de Horno, que la pide explícita con { soloDispositivo: true }. El usuario logueado puede editar (role
// "editor" efectivo); el estado real del dispositivo se sigue viendo en la pestaña Pie de Horno.
Ajuste.waitForApproval = function (onApproved, { soloDispositivo = false } = {}) {
  let banner = document.getElementById("ajuste-approval-banner");
  if (!banner) {
    banner = document.createElement("div");
    banner.id = "ajuste-approval-banner";
    banner.style.cssText = "position:fixed;inset:0;background:#12121f;color:#e0e0ec;" +
      "display:flex;align-items:center;justify-content:center;flex-direction:column;" +
      "gap:12px;font-family:system-ui,sans-serif;z-index:9999;text-align:center;padding:20px;";
    banner.innerHTML = `<div style="font-size:1.3rem;">Esperando aprobación del dispositivo…</div>
      <div style="color:#a0a0b8;font-size:0.9rem;">Pedile a un administrador que lo apruebe desde
      Pie de Horno → Dispositivos.</div>`;
  }

  async function check() {
    try {
      const status = await Ajuste.myDeviceStatus();
      if (!soloDispositivo && status.por_usuario) {
        banner.remove();
        onApproved({ ...status, status: "approved", role: "editor" });
        return;
      }
      if (status.status === "approved" || status.dev_skip_approval) {
        banner.remove();
        onApproved(status);
        return;
      }
    } catch (_) { /* red caida, se reintenta */ }
    document.body.appendChild(banner);
    setTimeout(check, 4000);
  }
  check();
};

Ajuste.wsConnect = function (channel, onMessage) {
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  let ws = null;
  let retryTimer = null;

  function connect() {
    ws = new WebSocket(`${proto}//${location.host}/ws/${channel}`);
    ws.onmessage = (event) => {
      try { onMessage(JSON.parse(event.data)); } catch (_) { /* mensaje no-JSON, se ignora */ }
    };
    ws.onclose = () => {
      retryTimer = setTimeout(connect, 3000);
    };
  }
  connect();
  return () => {
    if (retryTimer) clearTimeout(retryTimer);
    if (ws) ws.onclose = null; // evitar reconectar despues de un cierre intencional
    if (ws) ws.close();
  };
};
