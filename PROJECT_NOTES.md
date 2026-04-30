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
10. `host_api.py`: HTTP host API for Raspberry/client consumption (`/api/health`, `/api/pie-horno`).
11. `web/`: simple Raspberry-facing web client served by the host API root (`/`).

## Data Storage Locations
1. Catalog: `~/ajuste_comp_catalogo.json`.
2. History: `~/ajuste_comp_history.json`.
3. UI state: `~/ajuste_comp_ui.json`.
4. Furnace snapshot for Raspberry/host export: `~/ajuste_comp_pie_horno.json`.
5. Ladle counts for Raspberry/client: `~/ajuste_comp_cucharas.json`.
6. Pie de Horno approved devices: `~/ajuste_comp_devices.json`.

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
11. Catalog limit CSV export/import now includes `tipo`; importing old CSVs without `tipo` skips ambiguous duplicated names instead of updating the first match.
12. `Ajuste` now writes a host-side `pie de horno` snapshot to `~/ajuste_comp_pie_horno.json` only when an adjustment is applied; reset/cancel workspace clears that snapshot back to empty.
13. `app.py` now starts a background host API on port `8765`; Raspberry/client can read `GET /api/health` and `GET /api/pie-horno`.
14. The host API root (`/`) now serves a simple web UI with tabs `Ajuste` and `Cucharas`.
15. `Cucharas` now loads valid final materials from catalog metadata (`calidad_meta.es_material_final` + `bases`) for the current `material_objetivo`, supports `+/-`, total count, and auto-saves each change to `~/ajuste_comp_cucharas.json` through `POST /api/cucharas`.
16. Ladle counts remain separate from `ajuste_comp_history.json`; `Historicos` joins `~/ajuste_comp_cucharas.json` by colada id for display in a `Cucharas` tab.
17. The manual `Guardar` and `Colada -/+` controls were removed from the web `Cucharas` tab; each `+/-` count change is saved immediately.
18. Host API data endpoints now require device approval instead of a password/token. New browsers register themselves as `pending` in `~/ajuste_comp_devices.json`; the host tab `PIE DE HORNO` approves/revokes them.
19. `POST /api/cucharas` now validates JSON size and count payloads; invalid or oversized input is rejected before touching storage.
20. `app.py` starts the LocalTunnel public URL by default with subdomain `phorno-k91m-ajc26-zeta84`; public URL is `https://phorno-k91m-ajc26-zeta84.loca.lt/`.
21. Approved web clients open `GET /api/events` with Server-Sent Events; when any client saves `Cucharas`, the host broadcasts `refresh` so all clients reload immediately, with the 60-second polling left as fallback.
22. Devices now have a `role` in `~/ajuste_comp_devices.json`: `viewer` can only see data, and any `editor` device can use `+/-` in `Cucharas`. The host tab `PIE DE HORNO` has `Hacer editor` and `Solo ver`. `POST /api/cucharas` rejects non-editor devices with `read_only`.
23. `Cucharas` storage now keeps per-material timestamp events in `~/ajuste_comp_cucharas.json`: each `+` appends `{"saved_at": ...}` for that material, and each `-` removes the latest event for that material. `history_by_colada` now stores one dict per colada with `counts`, `events`, and computed `statistics`; old list-based history is still read by `Historicos`. The web buttons post `{material_final, delta}` instead of a full count snapshot, so multiple editors do not overwrite each other with stale totals.
24. The web `Cucharas` section has sub-tabs `Conteo` and `Estadisticas`. `Estadisticas` shows total per material, first/last timestamp, elapsed time, and a reserved block for future stats.
25. In `Historicos`, the `Cucharas` tab inside each colada displays the single ladle record in three sections: total quantity per material, time metrics (first, last, first-to-last duration, average interval), and chronological material/time events. Legacy list-based ladle saves are collapsed to their latest snapshot because exact per-spoon timestamps did not exist before the event schema.
26. The main `Estadisticas` tab includes a `Cucharas` section with overall ladle metrics, totals by material, per-colada timing/volume summaries, and activity by hour. Exact timing metrics only use event-schema ladle data; legacy ladle snapshots contribute to totals where possible.
27. Deleting a session from `Historicos` now also deletes the matching `history_by_colada` record in `~/ajuste_comp_cucharas.json`. `Historicos.refresh()` and `Estadisticas.refresh()` prune orphan ladle records whose colada no longer exists in `ajuste_comp_history.json`, so deleted coladas do not keep appearing in ladle stats.
28. History session coladas are now unique by normalized `NNNN /YY` key. `0050 /26 - X` and `50 /26 - Y` conflict, but `0050 /27` is allowed. `storage.append_history()` and `storage.update_session()` raise `DuplicateColadaError` on duplicates; UI catches it in Ajuste save and Historicos edit.
29. The main `Estadisticas` tab includes an `Informes de calidad` section with quality-report totals, date range, active/archived/draft counts, property averages/min/max, breakdowns by material/base, microstructure distributions, and report counts by date.
30. Pie de Horno editor clients now show `Iniciar` and `Guardar` buttons in the web `Cucharas` toolbar. `Iniciar` resets the current colada count after client confirmation when local count is non-zero; `Guardar` forces the current ladle state into `history_by_colada` while the existing per-click auto-save remains active.
31. Saving an `Ajuste` session to history no longer clears the Pie de Horno snapshot. This lets operators archive the adjustment immediately while the Raspberry keeps showing the active colada/cucharas until a Pie editor explicitly starts the next count.
32. Pie de Horno no longer requires an applied calculation to receive context. When an Ajuste session starts or its objective/colada/current alloy changes, `tab_ajuste.py` publishes a partial furnace snapshot with colada, material objetivo, current composition, and CE actual when available; applying an adjustment still publishes the full snapshot with materials and estimated composition. These snapshot changes also notify connected web clients.
33. The web `Cucharas` `Iniciar` action now requires the current Ajuste snapshot to provide both colada and material objetivo. It starts the count from that Ajuste context and refuses to fall back to stale ladle context if Ajuste has not started/published a session.
34. Raspberry connectivity diagnosis on 2026-04-17: `192.168.0.133` had LAN, SSH, DNS, and internet OK, but the Windows host IP changed from `192.168.0.124` to `192.168.0.110`. If Pie de Horno shows disconnected while the Raspberry has internet, check the host IP/launcher URL first.
35. Raspberry can reach the Windows host via `http://LAB01.local:8765/`; this is preferred over a numeric LAN IP for kiosk use because it survives host DHCP IP changes without requiring the public tunnel.
36. Raspberry kiosk launcher now has dual URL fallback: it checks `http://LAB01.local:8765/api/health` first and uses `http://LAB01.local:8765/?kiosk=raspi`; if unavailable, it checks `https://phorno-k91m-ajc26-zeta84.loca.lt/api/health` and falls back to the public tunnel URL. The selected URL is written to `/tmp/pie-de-horno-url.txt` on the Raspberry.
37. `app.py` has a LocalTunnel watchdog: after startup it checks `PUBLIC_TUNNEL_URL/api/health` every 30 seconds in a background thread. After 2 consecutive failures it restarts only the LocalTunnel process, not the Tk app. The `PIE DE HORNO` tab shows the tunnel state, last check time, and restart count; after 3 restarts it shows a red continuous-failure warning.
38. The Pie de Horno web client now asks for a device/operator name before first registration. It stores `pie_horno_device_name_confirmed=1` in localStorage after the user presses `Continuar`; devices without that flag will be prompted once and the chosen name is sent in `X-Pie-Device-Name` / `/api/device/register` so the host can identify pending approvals.
39. Raspberry on-screen keyboard: `squeekboard` is installed and was re-enabled only for kiosk use via `/home/raspberry/.config/autostart/squeekboard.desktop`. Other disabled autostart apps remain disabled. It was also started live with `XDG_RUNTIME_DIR=/run/user/1000 WAYLAND_DISPLAY=wayland-0 /usr/bin/squeekboard`; observed memory was about 26 MiB RSS.
40. Pie de Horno web topbar now has quick actions next to the title: `Recargar` calls `window.location.reload()` and `Teclado` toggles focus on a hidden text input to open/close the Raspberry Wayland on-screen keyboard when `squeekboard` is running.
41. `TabAjuste.set_state()` now schedules `_ensure_furnace_context_published()` after restore so Pie de Horno gets the current colada/material context even if the host opens/restores on a non-Ajuste tab. The helper preserves an existing matching full snapshot with applied materials and only publishes a partial context when the snapshot is empty or belongs to another colada/material.
42. LocalTunnel kept returning intermittent `HTTP 503`, so the watchdog was made more aggressive: check interval is now 10 seconds, restart happens after 1 failed health check, and restart kills orphan `node ... localtunnel --port 8765` processes before starting a fresh tunnel. This is a mitigation, not a guarantee; consider moving to Tailscale/ngrok/Cloudflare if public access must be reliable.
43. Raspberry fake sleep scripts were installed: `/home/raspberry/.local/bin/pie-sleep` closes Chromium/squeekboard and turns HDMI off while keeping SSH/network alive; `/home/raspberry/.local/bin/pie-wake` turns HDMI on, starts the kiosk launcher if Chromium is not running, and starts squeekboard if needed. Symlinks `pie-sleep.sh` and `pie-wake.sh` also exist.
44. Touch wake was added to Raspberry fake sleep. `/home/raspberry/.local/bin/pie-touch-wake` detects the touchscreen input event (`/dev/input/event2`, QDTECH/MPI7002) and runs `pie-wake` on first touch while `/tmp/pie-horno-sleep.txt` exists. `pie-sleep` now starts this watcher after turning HDMI off. Local helper BATs were added: `raspberry_sleep.bat` runs `ssh raspberry@192.168.0.133 pie-sleep`; `raspberry_wake.bat` runs `ssh raspberry@192.168.0.133 pie-wake`.
45. `pie-sleep`, `pie-wake`, and `pie-touch-wake` are also symlinked in `/usr/local/bin` on the Raspberry because non-interactive SSH did not include `/home/raspberry/.local/bin` in `PATH`. Local BATs now call the full `/home/raspberry/.local/bin/...` paths to avoid "orden no encontrada".
46. Raspberry automatic idle policy installed: `/home/raspberry/.local/bin/pie-idle-manager` monitors touchscreen `/dev/input/event2`. After 7200 seconds without touch it runs `pie-sleep`; after 18000 seconds without touch it runs `sudo -n systemctl poweroff`. It starts from `/home/raspberry/.config/autostart/pie-idle-manager.desktop` and is currently running. `pie-wake` writes `/tmp/pie-idle-activity.txt` so remote wake resets the idle counter. Local helper `raspberry_idle_status.bat` prints `/tmp/pie-idle-manager-state.json`.
47. The host `PIE DE HORNO` tab now includes a `Raspberry Pie de Horno` supervision/control panel. It checks SSH status for `raspberry@192.168.0.133`, shows kiosk URL, idle timer, RAM, uptime, keyboard/kiosk/idle-manager state, and provides buttons for `Actualizar estado`, `Reposo falso`, `Despertar kiosk`, `Reiniciar kiosk`, `Reiniciar Raspberry`, and `Apagar completo` (the dangerous actions ask confirmation). SSH commands run in background threads so Tk does not freeze.
48. Raspberry fake sleep now shows a simple black clock screen instead of turning HDMI fully off. `/home/raspberry/.local/bin/pie-sleep` launches `/home/raspberry/.local/bin/pie-clock.html` in Chromium kiosk mode with a large `HH:MM` clock, keeps `/tmp/pie-horno-sleep.txt`, and starts `pie-touch-wake`. `/home/raspberry/.local/bin/pie-wake` kills the clock Chromium when waking from fake sleep, then starts the normal Pie de Horno kiosk and squeekboard.
48. Quality final reports can now attach images per material report. Selected images are copied into `~/ajuste_comp_quality_images/`, and each report stores an `imagenes` list with image id, original name, copied path, and timestamp inside `~/ajuste_comp_quality_reports.json`. The Calidad tab shows add/open/remove image controls, includes an in-app image preview, the report form is scrollable, and printed HTML reports include attached image thumbnails.
49. The Calidad image section now has an `Importar ImageJ` workflow. It reads an ImageJ CSV with `Area` and `Circ.` columns, filters particles below 100 px area, calculates nodules/mm2, nodularity %, vermicular %, average/min/max graphite size, class distribution, fills the report fields, appends a structured observation block, optionally attaches the sample image, and generates/attaches a distribution chart in `~/ajuste_comp_quality_images/`. `Tam grafito` is filled from the predominant graphite size class, or two classes when the second class is relevant; micron average remains only as a technical observation.
50. Calidad printing now defaults to no attached images. Top toolbar has `Imprimir` and `Imprimir con imagenes` next to `Refrescar`; the old lower print button was removed to avoid duplicate controls.
51. Calidad compact group print keeps three rows per material; separators key off `material ...` rows instead of assuming a fixed index.
52. In Calidad compact group print, nodular `tipo grafito` no longer repeats the vermicular percentage or duplicates `% nodularizacion`; it prints `Nodular X%   nod/mm2 XXX` inside the same value cell.
53. Calidad print group separators now use each group's color: every group has a thick top and bottom border using `--group-line`, so the final group also closes with a colored horizontal line.
54. Pie de Horno web now displays current colada and material objetivo together in the `Numero colada actual` card as `0056/26-5`; the separate `Material objetivo` cards remain in the DOM but are hidden. Stored values are unchanged.
55. `POST /api/cucharas` no longer accepts legacy full-count snapshots. Editors must send `delta`, `start`, or `save`; this prevents older/stale secondary clients from overwriting the real Pie de Horno count with a full local reference.

## Duplicate Name Risk
1. The catalog can legitimately contain the same `nombre` for different `tipo` values, especially `Aleaci?n propia` and `Aleaci?n final`.
2. Any lookup keyed only by `nombre` is unsafe.
3. The most dangerous collisions are with numeric codes like `2`, `5`, `7`, `8`, `10`, `12`, `13`.
4. When reviewing code, always verify whether a lookup should prefer `Aleaci?n propia`, a valid non-final adjuster, or `Aleaci?n final`.
5. Critical protections are already added in `tab_ajuste.py` and `tab_historicos.py`, but the design would be safer long-term with unique internal ids.
6. `tab_catalogo.py` import/export for limits is now protected with `tipo`, but older CSVs without that column remain ambiguous when the same `nombre` exists more than once.

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
