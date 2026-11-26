// colada_search.js -- puerto de frontend/js/colada_search.js de ajuste_comp_web: buscador de "número de
// colada" compartido por Históricos (buscador de coladas guardadas) y, más adelante, Calidad (buscador de
// informes) -- misma lógica en vez de dos copias. Expuesto como el namespace global "ColadaSearch" (no
// import/export: nucleo concatena los scripts como <script> sueltos) para no ensuciar el scope global con
// nombres sueltos como "parseColadaTerm".
//
// Sintaxis que entiende un término (varios términos se separan por coma, unidos por OR):
//   "91"        -> número de colada exacto, ignora ceros a la izquierda (91 encuentra "0091 /26").
//   "91/26"     -> el mismo número, exigiendo además el año.
//   "91:95"     -> rango de colada inclusive en los dos extremos, funciona en cualquier orden.
//   "91:95/26"  -> el mismo rango, exigiendo además el año.
//   "91L5"      -> ventana: la colada 91 más las 5 coladas anteriores y las 5 siguientes POR POSICIÓN en la
//                  lista ordenada por colada. "91L5/26" fija el año de la colada pivote.
//   cualquier otra cosa -> texto libre, buscado en el número de colada (como texto) y en el "extraText" que
//                  pase el llamador (informe/material en Calidad, objetivo en Históricos).
const ColadaSearch = {};

ColadaSearch.parseColadaTerm = function (term) {
  let m = term.match(/^\s*(\d+)\s*:\s*(\d+)\s*(?:\/\s*(\d{1,2}))?\s*$/);
  if (m) return { type: "range", from: parseInt(m[1], 10), to: parseInt(m[2], 10), year: m[3] ? parseInt(m[3], 10) : null };
  m = term.match(/^\s*(\d+)\s*\/?\s*(\d{0,2})\s*$/);
  if (m) return { type: "exact", num: parseInt(m[1], 10), year: m[2] ? parseInt(m[2], 10) : null };
  return null;
};

ColadaSearch.parseWindowTerm = function (term) {
  const m = term.match(/^\s*(\d+)\s*[Ll]\s*(\d+)\s*(?:\/\s*(\d{1,2}))?\s*$/);
  if (!m) return null;
  return { center: parseInt(m[1], 10), radius: parseInt(m[2], 10), year: m[3] ? parseInt(m[3], 10) : null };
};

// Extrae {num, year} de cualquier texto de colada tipo "0091 /26", "91/26", "91 /26 - Bloque". null si no
// tiene esa pinta.
ColadaSearch.coladaNumYear = function (text) {
  const m = String(text || "").match(/(\d+)\s*\/\s*(\d{2})/);
  return m ? { num: parseInt(m[1], 10), year: parseInt(m[2], 10) } : null;
};

function _csTermMatchesItem(term, coladaText, extraText) {
  const parsed = ColadaSearch.parseColadaTerm(term);
  if (parsed) {
    // Pinta de número de colada: matchea el número EXACTO (sin contar ceros a la izquierda) o el rango,
    // nunca como substring -- si no, "91" traería también "0910 /26" solo porque "91" aparece adentro.
    const ny = ColadaSearch.coladaNumYear(coladaText);
    if (!ny) return false;
    if (parsed.type === "range") {
      const lo = Math.min(parsed.from, parsed.to), hi = Math.max(parsed.from, parsed.to);
      return ny.num >= lo && ny.num <= hi && (parsed.year == null || parsed.year === ny.year);
    }
    return ny.num === parsed.num && (parsed.year == null || parsed.year === ny.year);
  }
  const q = term.trim().toLowerCase();
  const haystack = `${coladaText || ""} ${extraText || ""}`.toLowerCase();
  return haystack.includes(q);
}

/**
 * Filtra `items` por `query`, devolviendo el subconjunto que matchea (en el MISMO orden relativo que traían
 * en `items` -- esta función no reordena el resultado, cada pantalla lo muestra como prefiera).
 *
 * getColada(item) -> texto de colada/lote de ese item.
 * getExtraText(item) -> texto adicional para la búsqueda libre (opcional: informe/material en Calidad,
 *   objetivo en Históricos).
 */
ColadaSearch.filterByColadaQuery = function (items, query, getColada, getExtraText) {
  const q = String(query || "").trim();
  if (!q) return items;
  const terms = q.split(",").map((t) => t.trim()).filter(Boolean);
  if (!terms.length) return items;

  // Copia ordenada por colada SOLO para que "91L5" sepa qué es "antes" y "después" -- el resultado final
  // respeta el orden original de items.
  const sorted = [...items].sort((a, b) => {
    const na = ColadaSearch.coladaNumYear(getColada(a));
    const nb = ColadaSearch.coladaNumYear(getColada(b));
    if (na && nb) {
      if (na.num !== nb.num) return na.num - nb.num;
      return na.year - nb.year;
    }
    return String(getColada(a) || "").localeCompare(String(getColada(b) || ""));
  });

  const matched = new Set();
  for (const term of terms) {
    const win = ColadaSearch.parseWindowTerm(term);
    if (win) {
      const pivotIdx = sorted.findIndex((it) => {
        const ny = ColadaSearch.coladaNumYear(getColada(it));
        return ny && ny.num === win.center && (win.year == null || win.year === ny.year);
      });
      if (pivotIdx !== -1) {
        const start = Math.max(0, pivotIdx - win.radius);
        const end = Math.min(sorted.length - 1, pivotIdx + win.radius);
        sorted.slice(start, end + 1).forEach((it) => matched.add(it));
      }
      continue;
    }
    for (const it of items) {
      if (_csTermMatchesItem(term, getColada(it), getExtraText ? getExtraText(it) : "")) matched.add(it);
    }
  }
  return items.filter((it) => matched.has(it));
};

// Texto fijo del tooltip ⓘ que se muestra al lado del buscador -- una sola copia para que Calidad e
// Históricos digan exactamente lo mismo.
ColadaSearch.COLADA_SEARCH_TOOLTIP =
  "Número de colada, ignora ceros a la izquierda: 91 encuentra 0091.\n" +
  "91/26 exige además el año.\n" +
  "Coma = varias búsquedas: 91,95 encuentra la 91 y la 95.\n" +
  "Dos puntos = rango: 91:95 (o 91:95/26 con año) encuentra de la 91 a la 95.\n" +
  "L = ventana: 91L5 encuentra la 91 más las 5 coladas anteriores y las 5 siguientes (91L5/26 fija el año de la 91).\n" +
  "Si no parece número de colada, busca como texto libre.";
