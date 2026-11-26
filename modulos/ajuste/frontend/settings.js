// settings.js -- puerto de frontend/js/settings.js de ajuste_comp_web, adaptado al patrón de "tarjetas" de la
// pantalla Opciones del núcleo (Nucleo.tarjetasOpciones) en vez de una pestaña propia: esta app ya no tiene
// una pestaña "Opciones" separada, se suma como una tarjeta más dentro de la que ya trae el núcleo. Solo
// auto_save_hours y debug_mode siguen siendo configuración real (ver rutas/settings.py).
// Apariencia (claro/oscuro): es de cada navegador, no del servidor -- se guarda en localStorage y se aplica al
// tocarlo, sin botón Guardar (ver Ajuste.elegirTema en comun.js).
Nucleo.tarjetasOpciones.push({
  orden: 10,
  html: async () => `
    <div class="tarjeta" id="op-tema">
      <h3>Apariencia</h3>
      <div class="botones">
        <label class="check"><input type="radio" name="op-tema" value="claro" ${Ajuste.temaOscuro() ? "" : "checked"}> Modo claro</label>
        <label class="check"><input type="radio" name="op-tema" value="oscuro" ${Ajuste.temaOscuro() ? "checked" : ""}> Modo oscuro</label>
      </div>
      <p class="sutil">Vale solo para este navegador: cada PC o tablet elige el suyo. Al imprimir siempre sale en claro.</p>
    </div>`,
  activar: () => {
    document.querySelectorAll('input[name="op-tema"]').forEach((radio) => {
      radio.addEventListener("change", () => Ajuste.elegirTema(radio.value === "oscuro"));
    });
  },
});

// Pestañas: el orden del menú de arriba, también por navegador (ver Ajuste.aplicarOrdenPestanas en comun.js). Con
// ▲/▼ en vez de arrastrar para que ande igual con el dedo en las tablets. Cada movimiento se aplica y se guarda al
// instante. Las pestañas que este usuario no ve (Usuarios si no es administrador) no se listan, pero conservan su
// lugar en lo guardado.
function _opPestanasVisibles() {
  return [...document.querySelectorAll("#menu a[data-vista]")]
    .filter((a) => !a.classList.contains("oculto"))
    .map((a) => ({ vista: a.dataset.vista, titulo: a.textContent.trim() }));
}

function _opPestanasLista() {
  const lista = _opPestanasVisibles();
  return lista.map((p, i) => `
    <li data-vista="${esc(p.vista)}">
      <span class="op-pestana-nombre">${esc(p.titulo)}</span>
      <button type="button" class="chico" data-mover="-1" ${i === 0 ? "disabled" : ""} title="Subir">▲</button>
      <button type="button" class="chico" data-mover="1" ${i === lista.length - 1 ? "disabled" : ""} title="Bajar">▼</button>
    </li>`).join("");
}

Nucleo.tarjetasOpciones.push({
  orden: 15,
  html: async () => `
    <div class="tarjeta" id="op-pestanas">
      <h3>Pestañas</h3>
      <p class="sutil">El orden de las pestañas de arriba. Vale solo para este navegador.</p>
      <ol id="op-pestanas-lista">${_opPestanasLista()}</ol>
      <div class="botones"><button type="button" id="op-pestanas-fabrica">Volver al orden de fábrica</button></div>
    </div>`,
  activar: () => {
    const ol = document.getElementById("op-pestanas-lista");
    ol.addEventListener("click", (ev) => {
      const boton = ev.target.closest("button[data-mover]");
      if (!boton) return;
      const li = boton.closest("li");
      const visibles = _opPestanasVisibles().map((p) => p.vista);
      const i = visibles.indexOf(li.dataset.vista);
      const j = i + Number(boton.dataset.mover);
      if (i < 0 || j < 0 || j >= visibles.length) return;
      // Se intercambian las dos pestañas visibles dentro del orden COMPLETO del menú (incluye las ocultas).
      const completo = [...document.querySelectorAll("#menu a[data-vista]")].map((a) => a.dataset.vista);
      const a = completo.indexOf(visibles[i]), b = completo.indexOf(visibles[j]);
      [completo[a], completo[b]] = [completo[b], completo[a]];
      Ajuste.guardarOrdenPestanas(completo);
      ol.innerHTML = _opPestanasLista();
      ol.querySelector(`li[data-vista="${CSS.escape(visibles[i])}"] button[data-mover="${boton.dataset.mover}"]`)?.focus();
    });
    document.getElementById("op-pestanas-fabrica").onclick = () => {
      Ajuste.guardarOrdenPestanas(null);
      ol.innerHTML = _opPestanasLista();
      avisar("Pestañas en el orden de fábrica.");
    };
  },
});

Nucleo.tarjetasOpciones.push({
  orden: 20,
  html: async () => {
    let s;
    try {
      s = await Ajuste.apiFetch("/api/settings");
    } catch (ex) {
      return `<div class="tarjeta" id="op-ajuste"><h3>Ajuste de Composición</h3><p class="error">Error cargando: ${esc(ex.message)}</p></div>`;
    }
    return `
      <div class="tarjeta" id="op-ajuste">
        <h3>Ajuste de Composición</h3>
        <div class="campos">
          <label>Auto-guardar sesión de Ajuste después de (horas)
            <input id="op-ajuste-auto-save" type="number" min="1" max="24" step="0.5" value="${esc(s.auto_save_hours)}" style="width:100px;">
          </label>
          <label style="display:flex;align-items:center;gap:6px;">
            <input type="checkbox" id="op-ajuste-debug" ${s.debug_mode ? "checked" : ""}> Modo debug (más detalle en los logs del servidor)
          </label>
        </div>
        <div class="botones">
          <button type="button" id="op-ajuste-guardar" class="primario">Guardar</button>
          <button type="button" id="op-ajuste-recargar">Recargar datos de Ajuste</button>
        </div>
        <p class="error" id="op-ajuste-error"></p>
      </div>`;
  },
  activar: () => {
    const errEl = document.getElementById("op-ajuste-error");
    document.getElementById("op-ajuste-guardar").onclick = async () => {
      errEl.textContent = "";
      try {
        await Ajuste.apiFetch("/api/settings", {
          method: "POST", headers: { "Content-Type": "application/json" },
          body: JSON.stringify({
            auto_save_hours: parseFloat(document.getElementById("op-ajuste-auto-save").value) || 3,
            debug_mode: document.getElementById("op-ajuste-debug").checked,
          }),
        });
        avisar("Guardado.");
      } catch (ex) {
        errEl.textContent = ex.detail?.message || ex.message;
      }
    };
    document.getElementById("op-ajuste-recargar").onclick = async () => {
      errEl.textContent = "";
      try {
        await Ajuste.apiFetch("/api/ajuste/reload-session", { method: "POST" });
        avisar("Datos de Ajuste recargados.");
      } catch (ex) {
        errEl.textContent = ex.detail?.message || ex.message;
      }
    };
  },
});
