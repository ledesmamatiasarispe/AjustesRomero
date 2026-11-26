// panels.js — paneles ("tablas") totalmente reorganizables: se arrastran desde el ícono ⠿⠿ y, según en qué
// parte de otro panel se suelten, quedan al lado (misma fila, comparten ancho ajustable) o arriba/abajo (fila
// nueva). Puerto sin cambios de frontend/js/panels.js de ajuste_comp_web, salvo quitar "export" (el núcleo
// concatena scripts planos, sin módulos ES -- makeReorderable queda como función global).
//
// Modelo de datos (la única fuente de verdad de la disposición):
//   rows = [[panelId, panelId, ...], [panelId], ...]
// Cada sub-array es una fila; el orden de los sub-arrays es el orden vertical, el orden dentro de cada uno es
// el orden horizontal. Ancho y alto se guardan aparte, indexados por la "firma" de la fila (ids ordenados y
// unidos) para que sobrevivan a reordenar mientras el mismo conjunto de paneles siga junto.
//
// Todo se guarda por navegador/dispositivo (localStorage), no en la sesión compartida del servidor.
function makeReorderable(containerId, storageKey, initialWideIds = []) {
  const container = document.getElementById(containerId);
  if (!container) return;
  const rowsKey = `ajuste_web_panel_rows:${storageKey}`;
  const widthKey = `ajuste_web_panel_width:${storageKey}`;
  const heightKey = `ajuste_web_row_height:${storageKey}`;

  function loadJSON(key, fallback) {
    try {
      const v = JSON.parse(localStorage.getItem(key) || "null");
      return v === null || v === undefined ? fallback : v;
    } catch (_) {
      return fallback;
    }
  }
  function saveJSON(key, value) {
    try { localStorage.setItem(key, JSON.stringify(value)); } catch (_) { /* storage lleno/deshabilitado, no es critico */ }
  }

  const widthsByRow = loadJSON(widthKey, {});  // {firmaDeFila: {panelId: fraccion}}
  const heights = loadJSON(heightKey, {});     // {firmaDeFila: alto en px}
  let rows = loadJSON(rowsKey, null);

  function allPanelsById() {
    const map = {};
    container.querySelectorAll(".panel").forEach((p) => { map[p.dataset.panel] = p; });
    return map;
  }

  function rowSig(ids) {
    return ids.slice().sort().join("|");
  }

  function defaultRows() {
    const ids = Object.keys(allPanelsById());
    const narrow = ids.filter((id) => !initialWideIds.includes(id));
    const wide = ids.filter((id) => initialWideIds.includes(id));
    const out = [];
    if (narrow.length) out.push(narrow);
    for (const id of wide) out.push([id]);
    return out;
  }

  if (!Array.isArray(rows)) rows = defaultRows();

  function sanitizeRows() {
    const known = new Set(Object.keys(allPanelsById()));
    rows = rows.map((r) => r.filter((id) => known.has(id))).filter((r) => r.length);
    const placed = new Set(rows.flat());
    for (const id of known) {
      if (!placed.has(id)) rows.push([id]);
    }
  }

  function saveRows() { saveJSON(rowsKey, rows); }

  // ---------- Separador de ancho entre dos paneles de una fila ----------
  function buildWidthHandle(rowIds, leftPanel, rightPanel) {
    const handle = document.createElement("div");
    handle.className = "resize-handle-v";
    handle.title = "Arrastrar para redistribuir el ancho (doble click: restablecer)";
    const sig = rowSig(rowIds);
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const row = handle.parentElement;
      const rowWidth = row.getBoundingClientRect().width;
      const startX = e.clientX;
      const leftStartW = leftPanel.getBoundingClientRect().width;
      const rightStartW = rightPanel.getBoundingClientRect().width;
      const totalW = leftStartW + rightStartW;
      const minW = Math.min(140, totalW / 3);
      document.body.classList.add("resizing-cols");
      const w = widthsByRow[sig] || (widthsByRow[sig] = {});

      function onMove(ev) {
        const dx = ev.clientX - startX;
        const newLeftW = Math.min(totalW - minW, Math.max(minW, leftStartW + dx));
        const newRightW = totalW - newLeftW;
        const leftFrac = newLeftW / rowWidth, rightFrac = newRightW / rowWidth;
        leftPanel.style.flex = `0 0 ${(leftFrac * 100).toFixed(3)}%`;
        rightPanel.style.flex = `0 0 ${(rightFrac * 100).toFixed(3)}%`;
        w[leftPanel.dataset.panel] = leftFrac;
        w[rightPanel.dataset.panel] = rightFrac;
      }
      function onUp() {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        document.body.classList.remove("resizing-cols");
        saveJSON(widthKey, widthsByRow);
      }
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    });
    handle.addEventListener("dblclick", () => {
      if (widthsByRow[sig]) {
        delete widthsByRow[sig][leftPanel.dataset.panel];
        delete widthsByRow[sig][rightPanel.dataset.panel];
        saveJSON(widthKey, widthsByRow);
      }
      render();
    });
    return handle;
  }

  // ---------- Separador de alto debajo de una fila ----------
  function buildHeightHandle(rowEl, sig) {
    const handle = document.createElement("div");
    handle.className = "resize-handle-h";
    handle.title = "Arrastrar para fijar el alto de esta fila (doble click: restablecer)";
    handle.addEventListener("mousedown", (e) => {
      e.preventDefault();
      const startY = e.clientY;
      const startH = rowEl.getBoundingClientRect().height;
      document.body.classList.add("resizing-rows");

      function onMove(ev) {
        const newH = Math.max(90, startH + (ev.clientY - startY));
        rowEl.style.height = `${newH}px`;
        rowEl.classList.add("row-capped");
        heights[sig] = newH;
      }
      function onUp() {
        window.removeEventListener("mousemove", onMove);
        window.removeEventListener("mouseup", onUp);
        document.body.classList.remove("resizing-rows");
        saveJSON(heightKey, heights);
      }
      window.addEventListener("mousemove", onMove);
      window.addEventListener("mouseup", onUp);
    });
    handle.addEventListener("dblclick", () => {
      delete heights[sig];
      rowEl.style.height = "";
      rowEl.classList.remove("row-capped");
      saveJSON(heightKey, heights);
    });
    return handle;
  }

  // ---------- Render: reconstruye #panels a partir de `rows` ----------
  function render() {
    sanitizeRows();
    const panelsMap = allPanelsById();
    container.innerHTML = "";
    for (const rowIds of rows) {
      const rowPanels = rowIds.map((id) => panelsMap[id]).filter(Boolean);
      if (!rowPanels.length) continue;
      const rowEl = document.createElement("div");
      rowEl.className = "panel-row";
      const sig = rowSig(rowIds);
      const savedH = heights[sig];
      if (savedH) { rowEl.style.height = `${savedH}px`; rowEl.classList.add("row-capped"); }

      const wFracs = widthsByRow[sig] || {};
      rowPanels.forEach((p, i) => {
        const frac = wFracs[p.dataset.panel];
        p.style.flex = rowPanels.length > 1
          ? (frac ? `0 0 ${(frac * 100).toFixed(3)}%` : `1 1 ${(100 / rowPanels.length).toFixed(3)}%`)
          : "1 1 100%";
        rowEl.appendChild(p);
        if (i < rowPanels.length - 1) rowEl.appendChild(buildWidthHandle(rowIds, p, rowPanels[i + 1]));
      });
      container.appendChild(rowEl);
      container.appendChild(buildHeightHandle(rowEl, sig));
    }
  }

  // ---------- Drag: reordenar / regrupar ----------
  let draggedId = null;
  let pendingCandidate = null;

  function clearDropHints() {
    container.querySelectorAll(".panel").forEach((p) => p.classList.remove("drop-left", "drop-right", "drop-top", "drop-bottom"));
  }

  function computeZone(e, rect) {
    const relX = (e.clientX - rect.left) / rect.width;
    const relY = (e.clientY - rect.top) / rect.height;
    const edge = 0.25;
    if (relX < edge) return "left";
    if (relX > 1 - edge) return "right";
    return relY < 0.5 ? "top" : "bottom";
  }

  function computeCandidateRows(targetPanel, zone) {
    let candidate = rows.map((r) => r.slice());
    candidate = candidate.map((r) => r.filter((x) => x !== draggedId)).filter((r) => r.length);
    if (targetPanel && targetPanel.dataset.panel !== draggedId) {
      const targetId = targetPanel.dataset.panel;
      const ri = candidate.findIndex((r) => r.includes(targetId));
      if (ri === -1) return candidate;
      if (zone === "left" || zone === "right") {
        const pi = candidate[ri].indexOf(targetId);
        candidate[ri].splice(zone === "left" ? pi : pi + 1, 0, draggedId);
      } else {
        candidate.splice(zone === "top" ? ri : ri + 1, 0, [draggedId]);
      }
    } else if (!candidate.some((r) => r.includes(draggedId))) {
      candidate.push([draggedId]);
    }
    return candidate;
  }

  container.addEventListener("dragstart", (e) => {
    const handle = e.target.closest(".drag-handle");
    const panel = handle && handle.closest(".panel");
    if (!handle || !panel) { e.preventDefault(); return; }
    draggedId = panel.dataset.panel;
    pendingCandidate = null;
    panel.classList.add("dragging");
    e.dataTransfer.effectAllowed = "move";
    try { e.dataTransfer.setDragImage(panel, 20, 20); } catch (_) { /* no soportado en algun navegador viejo, no bloquea el drag */ }
  });

  container.addEventListener("dragover", (e) => {
    if (!draggedId) return;
    e.preventDefault();
    clearDropHints();
    const targetPanel = e.target.closest(".panel");
    if (targetPanel && targetPanel.dataset.panel !== draggedId) {
      const rect = targetPanel.getBoundingClientRect();
      const zone = computeZone(e, rect);
      targetPanel.classList.add(`drop-${zone}`);
      pendingCandidate = computeCandidateRows(targetPanel, zone);
    } else {
      pendingCandidate = computeCandidateRows(null, null);
    }
  });

  container.addEventListener("dragleave", (e) => {
    if (!container.contains(e.relatedTarget)) clearDropHints();
  });

  container.addEventListener("dragend", () => {
    clearDropHints();
    const el = draggedId && container.querySelector(`.panel[data-panel="${CSS.escape(draggedId)}"]`);
    if (el) el.classList.remove("dragging");
    if (pendingCandidate) {
      rows = pendingCandidate;
      saveRows();
    }
    pendingCandidate = null;
    draggedId = null;
    render();
  });

  // ---------- Drag por touch: mismo reordenamiento, sin HTML5 DnD ----------
  let touchPointerId = null;
  let touchPanelEl = null;
  let touchStartX = 0;
  let touchStartY = 0;
  let touchDragging = false;
  const TOUCH_DRAG_THRESHOLD = 8; // px -- distingue un toque de "recien arranca a arrastrar"

  function finishTouchDrag() {
    if (touchDragging) {
      clearDropHints();
      if (touchPanelEl) touchPanelEl.classList.remove("dragging");
      if (pendingCandidate) {
        rows = pendingCandidate;
        saveRows();
      }
      render();
    }
    pendingCandidate = null;
    draggedId = null;
    touchPointerId = null;
    touchPanelEl = null;
    touchDragging = false;
  }

  container.addEventListener("pointerdown", (e) => {
    if (e.pointerType === "mouse") return; // el mouse ya usa el Drag and Drop nativo de arriba
    const handle = e.target.closest(".drag-handle");
    const panel = handle && handle.closest(".panel");
    if (!handle || !panel) return;
    touchPointerId = e.pointerId;
    touchPanelEl = panel;
    touchStartX = e.clientX;
    touchStartY = e.clientY;
    touchDragging = false;
  });

  container.addEventListener("pointermove", (e) => {
    if (touchPointerId === null || e.pointerId !== touchPointerId) return;
    if (!touchDragging) {
      const dx = e.clientX - touchStartX;
      const dy = e.clientY - touchStartY;
      if (Math.hypot(dx, dy) < TOUCH_DRAG_THRESHOLD) return;
      touchDragging = true;
      draggedId = touchPanelEl.dataset.panel;
      pendingCandidate = null;
      touchPanelEl.classList.add("dragging");
      try { touchPanelEl.setPointerCapture(touchPointerId); } catch (_) { /* si no lo soporta, sigue funcionando igual */ }
    }
    e.preventDefault();
    clearDropHints();
    const targetPanel = document.elementFromPoint(e.clientX, e.clientY)?.closest(".panel") || null;
    if (targetPanel && targetPanel.dataset.panel !== draggedId) {
      const rect = targetPanel.getBoundingClientRect();
      const zone = computeZone(e, rect);
      targetPanel.classList.add(`drop-${zone}`);
      pendingCandidate = computeCandidateRows(targetPanel, zone);
    } else {
      pendingCandidate = computeCandidateRows(null, null);
    }
  });

  container.addEventListener("pointerup", (e) => {
    if (touchPointerId === null || e.pointerId !== touchPointerId) return;
    finishTouchDrag();
  });
  container.addEventListener("pointercancel", (e) => {
    if (touchPointerId === null || e.pointerId !== touchPointerId) return;
    finishTouchDrag();
  });

  render();
  saveRows();
}
