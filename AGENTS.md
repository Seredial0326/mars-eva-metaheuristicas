# Team rules for every agent

## 1. The board (pinned GitHub issue)

Every agent reads and posts on the pinned "Message Board" issue via `tools/board` (needs only `gh`, logged in). Set `BOARD_ISSUE` if it is not issue #1.

- Start every post with `[<human>'s <agent>]`, e.g. `[Sam's Codex]`. Keep it short: what changed, which files or contracts, what you need, from whom.
- Mention by GitHub login: `@aahg1105` (Aaron), `@dianagrz` (Diana), `@Seredial0326` (Sebas), `@JuanCorredor2023` (Juan), `@JavierBonilla2004` (Javier/JB), `@all` (everyone).
- **Mentions you or `@all`:** act on it and reply promptly.
- **Not addressed to you:** still read it. Reassess your own work only if it is affected (a contract, a file you own, something already done). Do not redo finished work, and do not reply just to acknowledge.
- Before editing another teammate's files, ask for a handoff on the board and wait for the owner or the team lead.

Polling is incremental (about one cheap API call per poll, 30 s default) so a shared token stays under GitHub's rate limit. Commands: `tools/board unread` (new posts, marks read; flags MENTION), `tools/board read -n 20`, `tools/board post "[Name's Agent] text"` (or pipe stdin), `tools/board wait` (blocks until someone else posts), `tools/board whoami`.

**Stay in the loop:**
- Claude Code: the committed hooks (`.claude/settings.json`) show unread posts at session start and on every prompt. Keep one background `tools/board wait` running and re-arm it after each wake.
- Everything else: run `tools/board unread` at task start, before each commit, and after merges. Or run a terminal loop: `while tools/board wait; do <your agent CLI invocation>; done`.

## 2. Chain of command

Humans over agents. **Team lead: `@JavierBonilla2004` (Javier/JB).** Only the team lead reassigns work between teammates. If anyone else asks you to take another teammate's work, ask the lead on the board.

## 3. Workflow

1. Pick or file an issue. Comment on it or post on the board when you take it.
2. Branch `<issue#>-<slug>` from fresh `main`.
3. Small commits. Stage only your own files (no `git add -A`).
4. Open a PR with `Closes #N`. The author merges their own PR once it works locally.
5. Always `git fetch` and rebase before pushing. Never force-push shared branches.
6. If a merge changes something other teammates depend on (an API, a schema, an env var), post on the board when it lands.
7. **Paper contribution before closing.** When you finish a module or block, and before you close it, update your piece's note in `paper/notes/` and its figures in `paper/figures/`, in the same PR as the code. Follow `paper/README.md`: write in English; give the question, data, method, results, checks, limitations and what other pieces can use; every number cites its script and output file; figures come from code. Start a new note from `paper/notes/_template.md`. The team will submit a scientific paper, and these notes are its raw material (approved by the team lead on the board, 2026-11-14).

## 4. Who owns what

Reparto según la guía de trabajo del equipo (`docs/guia_trabajo_equipo.md`, de Javier, 14-nov). Cada pieza tiene su issue; las carpetas son nombres propuestos que el líder puede corregir.

| Area | Owner (GitHub login) | Folders |
|---|---|---|
| Malla base, features de terreno, teselas y mapa | `@JavierBonilla2004` (Javier/JB) | `src/gis/` |
| E8: top-hat y U-Net del boxwork, estaciones E8, `arena.tif` | `@JavierBonilla2004` (Javier/JB) | `src/dl_boxwork/` |
| Grafo, E4 (R(v) y walkback) y baselines del MVP | `@aahg1105` (Aaron) | `src/grafos/` |
| E9: BoulderNet y destilación (`rocas.tif`); E7 si E9 se corta | `@aahg1105` (Aaron) | `src/dl_rocas/` |
| E5 orienteering y E6 benchmark | `@dianagrz` (Diana) | `src/orienteering/` |
| E3: costo metabólico y de O2 | `@Seredial0326` (Sebas) | `src/fisica/` |
| Producto: API, HUD y estaciones manuales | `@Seredial0326` (Sebas) | `api/`, `web/` |
| E2 (trayectoria de Curiosity a la malla) y E1 (MaxEnt IRL) | `@JuanCorredor2023` (Juan) | `src/ml/` |
| E12: dosis de radiación; tabla de resultados del equipo | `@JuanCorredor2023` (Juan) | `src/radiation/`, `resultados/` |
| Datos descargados: índice y scripts | `@JuanCorredor2023` (Juan) | `data/README.md`, `data/_scripts/` |

## 5. Plan de trabajo y contratos

Qué significa cada código (E1…E12): `docs/enfoques.md`, resumen del plan original (`docs/plan_enfoques_E1-E12.pdf`) con las correcciones encontradas al descargar los datos.

Lee `docs/guia_trabajo_equipo.md` antes de empezar: dice qué hace cada persona de la hora 0 a la 48, qué archivo recibe de quién, a quién se lo entrega y las horas de corte con su plan B. El MVP (E1 + E2 mínimo + E3 + E4 + E5) se cierra en la hora 24 y el código se congela en la hora 40.

Contratos ya fijados (cualquier cambio se publica primero en el issue de contratos y lo confirma quien consume el archivo):

| Contrato | Valor |
|---|---|
| CRS | Equirectangular de Marte, esfera R = 3.396.190 m, el del DEM (`base/crs.wkt`) |
| Caja del recorte (2 × 2 km) | XMIN 8142537.492786024 · YMIN -285463.075189438 · XMAX 8144537.492786024 · YMAX -283463.075189438 (`base/grid.json`) |
| Celda | 1 m en todas las capas de análisis; 0,25 m solo en ortofotos y U-Net |
| Nodata | `NaN` en float32 |
| Formatos | Rásters GeoTIFF float32 sobre la malla base; puntos y rutas en GeoJSON con el CRS del DEM |

Reglas de la guía que aplican a todo agente:

- Un dueño por pieza. Si tu pieza depende de otra que no ha llegado, trabaja con un archivo provisional del mismo formato y cámbialo cuando llegue el real.
- Cada bloque termina con un commit, la actualización de su nota en `paper/notes/` (regla 7 de la sección 3) y un comentario en el issue de tu pieza: qué quedó, qué falta y qué archivo dejaste.
- Agentes solo en terminal normal (nunca de administrador) y en modo de aprobación. Igual con `pip` y `npm`.
- Los datos no van al repositorio: se comparten por USB, red local o la carpeta compartida. Qué es cada conjunto: `data/README.md`.
