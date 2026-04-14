# PROJECT_NOTES.md

This file is for ChatGPT handoff. It is intentionally verbose so a new chat can continue immediately without missing decisions or context. Keep it updated as changes are made.

## TL;DR
1. App is a Tkinter desktop tool for alloy adjustment.
2. Main tabs: Catalogo, Ajuste, Historicos.
3. Data is saved under user home (not the repo).
4. Current algorithms: Greedy and Lineal only.
5. Ranges (soft_min/soft_max) are for UI coloring only and are NOT enforced by algorithms.
6. Lineal uses normal equations and can be unstable on singular data.

## How to Run
1. From repo root: `python app.py`.
2. Window state persists in `~/ajuste_comp_ui.json`.
3. Data persists in `~/ajuste_comp_catalogo.json` and `~/ajuste_comp_history.json`.

## Project Map
1. `app.py`: UI bootstrap, theme, tab wiring, state save/restore.
2. `tab_ajuste.py`: adjustment logic, calculator, current session history, auto-estimar.
3. `tab_catalogo.py`: catalog editor, import/export, limits UI.
4. `tab_historicos.py`: saved sessions UI (docked tabs).
5. `storage.py`: read/write JSON data in user home.
6. `ce.py`: carbon equivalent (CE) formulas.
7. `utils.py`: numeric helpers and `simulate_with_plan`.
8. `widgets.py`: ScrollFrame helper.
9. `config.py`: colors, theme, element list.

## Data Storage Locations
1. Catalog: `~/ajuste_comp_catalogo.json`.
2. History: `~/ajuste_comp_history.json`.
3. UI state: `~/ajuste_comp_ui.json`.

## Repo JSON vs Runtime JSON
1. Repo includes `materiales.json`, `ajuste_estado.json`, `ajustes_historicos.json`.
2. These are NOT used by the running app.
3. Runtime persistence uses the files in user home listed above.

## Encoding / Mojibake
1. Some UI strings show mojibake (e.g., `Â±`, `Ã¡`, `Ã³`).
2. This is caused by inconsistent file encoding.
3. If UI text looks broken, normalize source files to UTF-8.

## Catalog Data Model
Each catalog entry is a dict with keys:
1. `nombre`: string.
2. `tipo`: string (Ferroaleacion, Metal puro, Aleacion propia, etc).
3. `rendimiento`: number, 0-100.
4. `costo`: number.
5. `composicion`: dict of element -> percent.
6. `limites`: dict of element -> dict of soft_min/soft_max/hard_min/hard_max.
7. `especiales`: CE settings for Aleacion propia.
8. `ajuste`: bool, if it is a material de ajuste.

Important: UI now uses ONLY "soft" limits, and hard_min/hard_max are set to None.

## Limits UI (Catalogo)
1. Per element, user enters "± absoluto" (absolute delta).
2. That delta is converted to soft_min and soft_max as `ideal ± delta`.
3. Hard limits are removed from UI.
4. Import/export of limits uses only soft_min and soft_max columns.

## CE (Carbon Equivalent)
1. CE formula is computed in `ce.py`.
2. CE settings are stored in catalog under `especiales`.
3. CE is shown in UI and logged in history.
4. Current algorithms do not enforce CE as a hard constraint.
5. CE min/max fields are informational only right now.

## Ajuste Tab (Main Algorithm Flow)
Primary entry: `TabAjuste._estimate_core`.

High-level steps inside `_estimate_core`:
1. Load target alloy and current mass/composition.
2. Choose materials of ajuste from `adjust_list`.
3. For non C/Si/Fe:
   - Greedy: per element, pick best adjuster by highest contribution.
   - Lineal: solve linear system for target elements.
4. Dilution step:
   - If C or Si above target, add steel to dilute.
5. Raise C/Si:
   - If C below target, add graphite.
   - If Si below target, add silicon.
6. Build final plan dict and update UI.

## Algorithms (Current)
Only two algorithms are enabled in the combobox: Greedy and Lineal.

Greedy:
1. For each element not C/Si/Fe, choose one best material by max contribution.
2. Adds that material to reach target.
3. Dilutes with steel if C/Si above target.
4. Adds graphite/silicon if C/Si below target.
5. Targets the objective values, not the soft range.

Lineal:
1. Builds a linear system for non C/Si/Fe target elements.
2. Solves with `_solve_linear` using normal equations (AᵀA), no regularization.
3. Applies solution, then same dilution and C/Si raise steps.
4. Targets objective values, not soft range.

Important: There is no range enforcement in algorithms. Ranges are used only for UI coloring.

## UI and State
1. Auto-estimar can be enabled; it recomputes on changes.
2. Slider % affects calculate partial and auto-estimar.
3. Preset buttons for 30/50/75/100%.
4. Reset button clears current session, logs, and kg inputs.

## Historicos Tab
1. Left panel lists saved sessions (coladas).
2. Right panel has docked tabs, one per session.
3. Each session tab has inner tabs for Ajustes and Calculos.
4. Double-click opens detail view inside the session tab.
5. "Resumen de ajustes" sums all materials in the session.

## Events Between Tabs
1. `<<HistoryUpdated>>` from Ajuste refreshes Historicos.
2. `<<CatalogUpdated>>` from Catalogo refreshes Ajuste and Historicos.

## Known Decisions
1. Ranges are for UI warning only.
2. Algorithms should target objective values.
3. CE is informative only, not a hard constraint.

## Known Fragile Areas
1. Indentation errors in `tab_catalogo.py` can break dialogs.
2. Changing catalog requires refreshing objective combobox.
3. Adjuster lists can contain names not in catalog if not refreshed.
4. `to_float` returns 0.0 on parse errors, which can hide bad inputs.
5. `APP_TITLE` exists in `config.py`, but the app uses `APP_TITLE` defined in `app.py`.

## Known Failure Modes
1. `_solve_linear` can return None if the system is singular or ill-conditioned.
2. Greedy/Lineal can fail if a target element has no valid adjuster.
3. Lineal may produce negative kg; current code effectively ignores non-positive values.

## Debug Checklist
1. If UI has missing buttons: check indentation in `tab_catalogo.py`.
2. If objectives not updated: verify `<<CatalogUpdated>>` handler.
3. If Historicos not refreshing: verify `<<HistoryUpdated>>`.
4. If C/Si stays low/high: check target values and adjuster compositions.

## What Changed Recently
1. Catalog limits are now only "? absoluto" (soft only).
2. Hard limits removed from UI and imports/exports.
3. Algorithms ignore ranges; ranges are UI only.
4. Historicos redesigned as docked tabs.
5. Catalog updates refresh Ajuste and Historicos.
6. `Calidad` now reads final-material defaults from catalog metadata (`calidad_meta.defaults`) instead of a hardcoded seed.
7. Report generation in `Calidad` reloads catalog data before creating reports, so edited defaults like `cementita` should propagate into new reports.
8. `Ajuste` now separates duplicated names by type: objective lookup prefers `Aleaci?n propia`, current alloy selection prefers `Aleaci?n propia`, and adjuster lookup excludes `Aleaci?n final`.
9. `Historicos` simulation also separates duplicated names by type: objective composition prefers `Aleaci?n propia`, and plan simulation prefers valid non-final adjusters.
10. The PySide experiment folders were removed on purpose; future migration should happen in a separate cloned workspace, not inside this main repo.

## Duplicate Name Risk
1. The catalog can legitimately contain the same `nombre` for different `tipo` values, especially `Aleaci?n propia` and `Aleaci?n final`.
2. Any lookup keyed only by `nombre` is unsafe.
3. The most dangerous collisions are with numeric codes like `2`, `5`, `7`, `8`, `10`, `12`, `13`.
4. When reviewing code, always verify whether a lookup should prefer `Aleaci?n propia`, a valid non-final adjuster, or `Aleaci?n final`.
5. Critical protections are already added in `tab_ajuste.py` and `tab_historicos.py`, but the design would be safer long-term with unique internal ids.

## Suggested Future Work
1. If range enforcement is desired, rewrite algorithms with range constraints.
2. If CE should be hard, add CE constraints to algorithm.
3. Add unit tests for `_solve_kg_for_target` and `_solve_linear`.

## How to Extend Safely
1. When adding new algorithm options, update combobox values and state restore.
2. Keep storage schema stable; migrations are not implemented.
3. Prefer small, reversible changes and commit often.

## Quick Reference of Key Functions
1. `TabAjuste._estimate_core`: main algorithm.
2. `TabAjuste._solve_linear`: linear system solver.
3. `TabAjuste._solve_kg_for_target`: compute kg for single element target.
4. `TabAjuste._effective_add_perkg`: contribution per kg.
5. `TabAjuste._log_ajuste` and `_log_calc`: history logging.
6. `TabCatalogo._edit_dialog`: catalog editor dialog.
7. `TabHistoricos._open_session_tab`: session dock UI.

## Session History Schema
1. `colada`: string like "NNNN /YY - MATERIAL".
2. `objetivo`: objective alloy name.
3. `started_at` / `ended_at`.
4. `ajustes`: list of applied adjustments.
5. `calculos`: list of calculated adjustments.

Each ajuste entry:
1. `fecha`, `objetivo`, `porcentaje`.
2. `inicial` and `estimado` mass/comp.
3. `materiales`: dict material -> kg.
4. `cambios_list`: list of (elem, v0, v1, delta).
5. `ce_formula`, `ce_inicial`, `ce_estimado`, `ce_objetivo`.

## Action When Chat Resets
1. Read this file first.
2. Run `git status -sb`.
3. Inspect `tab_ajuste.py` for algorithm changes.
4. Inspect `tab_catalogo.py` for catalog UI changes.
