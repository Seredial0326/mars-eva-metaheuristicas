# Laboratorio de metaheurísticas: plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** registrar iteración por iteración los seis solvers del OP, generar datasets grandes (sintéticos y sobre el terreno real), correr experimentos con verdad de referencia, guardar todo en CSV, analizarlo con gráficas/estadística y exponerlo en la UI.

**Architecture:** cada solver de `src/orienteering/solvers/` acepta `trace=None`; un paquete nuevo `src/orienteering/lab/` (trace, reference, datasets, run, analyze) hace el resto; `api/lab.py` + `web/lab.html` lo exponen, y `/plan` gana `solver`.

**Tech Stack:** Python 3.14 (`.venv`), numpy, scipy, matplotlib, OR-Tools 9.15 (CP-SAT), FastAPI, JS sin librerías nuevas (SVG).

**Spec:** `docs/superpowers/specs/2026-11-25-laboratorio-metaheuristicas-design.md`

## Global Constraints

- Todo en la rama local `clase-metaheuristicas`. Nunca `git push`, ni PR, ni board.
- Python: `.venv/Scripts/python.exe` (Windows). Tests: `.venv/Scripts/python.exe -m pytest ...` desde la raíz.
- Con `trace=None` cada solver da exactamente la misma `Solution.route` y `prize` que antes.
- DP por defecto hasta n = 18 (`--dp-max 18`); CP-SAT hasta 60 nodos, 120 s por instancia (`--cpsat-limit 120`).
- Metaheurísticas con sus límites actuales (10 s, parámetros por defecto sin cambios).
- Salidas en `data/lab/` (ignorado por git): `data/lab/instances/`, `data/lab/runs/<YYYYmmdd-HHMMSS>/`.
- `reference_kind` ∈ {`dp_optimal`, `cpsat_optimal`, `best_known`}.
- Presupuesto real: 1000 Wh con 10 % de margen; variante 120 min. Servicio 10 min por estación (el de las manuales); puntajes de `data/stations/stations_rubric.json` (ridge 5, hollow 4, contact 4, curiosity 3).
- Estaciones reales a ≥ 40 m entre sí y del hábitat (centro de la caja `paper_figures.BOX_CENTRE`).
- Código y docstrings en inglés como el resto del repo; textos de `web/lab.html` en español; el HUD sigue en inglés.
- Gráficas: cargar la skill `dataviz` antes de escribir código de figuras.

## Review Focus

1. Instancia donde ninguna estación cabe en el presupuesto (ruta vacía, `prize = 0`): gap definido como 0, CSV sin NaN rotos, figuras sin división por cero. → test en Task 5 y Task 7.
2. CP-SAT sin `ortools` o que no prueba el óptimo dentro del límite: la referencia cae a `best_known` con la cota guardada, nunca marca `cpsat_optimal`. → test en Task 5.
3. Algoritmo pedido con más nodos que su `MAX_STATIONS` (DP con 40): se salta con `status = "skipped_size"` en `runs.csv`, no aborta la corrida. → test en Task 7.
4. `POST /lab/solve` con un nombre de instancia o algoritmo inexistente o demasiadas semillas: 422 con mensaje, no 500. → test en Task 9.
5. Re-ejecutar `datasets` con instancias ya generadas: las reutiliza sin recalcular Dijkstras ni cambiar su contenido (mismo hash). → test en Task 6.

---

### Task 1: `Tracer`, contador de evaluaciones e instalación de OR-Tools

**Files:**
- Create: `src/orienteering/lab/__init__.py`, `src/orienteering/lab/trace.py`
- Modify: `src/orienteering/solvers/heuristics.py` (`Evaluator.__init__`, `Evaluator.check`)
- Test: `tests/orienteering/test_trace.py`

**Interfaces:**
- Produces: `class Tracer(every: int = 1)`; `tracer(**fields) -> None` (añade `t_s` = segundos desde `tracer.start()` o desde la primera llamada); `tracer.start() -> None`; `tracer.extend(rows: list[dict]) -> None` (filas que ya traen `t_s`); `tracer.rows: list[dict]`; `tracer.to_csv(path, extra: dict | None = None) -> None` (antepone las columnas de `extra` a cada fila). Con `every=k` guarda la fila 0, cada k-ésima y la última (`tracer.flush()` la fija; los solvers llaman `flush()` al terminar).
- Produces: `Evaluator.evaluations: int`, incrementado en cada `check()`.

- [ ] **Step 0: Instalar OR-Tools (pedir permiso al usuario) y fijar la línea base**

Run: `.venv/Scripts/python.exe -m pip install ortools==9.15.6755` y luego `.venv/Scripts/python.exe -m pytest tests/orienteering -q`
Expected: instalación OK; anotar cuántos tests pasan/saltan (línea base para no romper nada).

- [ ] **Step 1: Tests que fallan**

`test_tracer_every_keeps_first_and_last` (Tracer(every=10), 25 llamadas + flush → iter 0, 10, 20, 24); `test_tracer_rows_have_time` (`t_s` no decreciente, ≥ 0); `test_tracer_to_csv_extra_columns` (CSV con `instance,seed` primero); `test_evaluator_counts_checks` (3 `check()` → `evaluations == 3`).

- [ ] **Step 2: Correr y ver que fallan** — `pytest tests/orienteering/test_trace.py -v` → ImportError.
- [ ] **Step 3: Implementar `Tracer` y el contador.**
- [ ] **Step 4: Correr `test_trace.py` y `test_metaheuristics.py`** → PASS.
- [ ] **Step 5: Commit** `lab: add per-iteration Tracer and evaluation counter`

### Task 2: Trazas en ILS y SA

**Files:**
- Modify: `src/orienteering/solvers/ils.py` (`solve`), `src/orienteering/solvers/sa.py` (`solve`, `move`)
- Test: `tests/orienteering/test_trace.py`

**Interfaces:**
- Consumes: `Tracer` (Task 1).
- Produces: `ils.solve(problem, max_no_improve=..., time_limit_s=..., trace=None)`; `sa.solve(problem, seed=0, steps=..., time_limit_s=..., trace=None)`. Todas las `Solution` ganan atributos `iterations: int` y `evaluations: int` (añadir los dos campos con default `None` a `problem.Solution`).
- Filas ILS: `iter, best_prize, best_energy_j, current_prize, shake_size, shake_at, stale, improved`.
- Filas SA: `iter, best_prize, best_energy_j, temp, move, feasible, accepted, delta, current_score`. `move` ∈ {`add`,`drop`,`swap`,`reverse`,`none`}: `move()` devuelve `(route, kind)`.

- [ ] **Step 1: Tests que fallan** — `test_trace_does_not_change_result[ils|sa]` (8 instancias `random_instance` n=12, semillas 0-2: misma `route`/`prize` con y sin Tracer); `test_best_prize_never_drops[ils|sa]`; `test_trace_columns[ils|sa]` (conjunto exacto de columnas de arriba + `t_s`); `test_sa_temperature_decreases`.
- [ ] **Step 2: Ver que fallan.**
- [ ] **Step 3: Implementar.** Ojo SA: el `rng` no debe consumir números distintos con traza (no llamar al rng desde el código de traza).
- [ ] **Step 4: `pytest tests/orienteering -q`** → todo lo de la línea base + nuevos PASS.
- [ ] **Step 5: Commit** `orienteering: trace ILS and SA iterations`

### Task 3: Trazas en ACO y GA

**Files:**
- Modify: `src/orienteering/solvers/aco.py` (`solve`), `src/orienteering/solvers/ga.py` (`solve`)
- Test: `tests/orienteering/test_trace.py`

**Interfaces:**
- Produces: `aco.solve(..., trace=None)`, `ga.solve(..., trace=None)`; rellenan `Solution.iterations/evaluations`.
- Filas ACO: `iter, best_prize, best_energy_j, round_best_prize, ants_mean_prize, tau_mean, tau_max, stale`.
- Filas GA: `iter, best_prize, best_energy_j, pop_best, pop_mean, pop_worst, diversity, stale`; `diversity = len({tuple(r) for r in pop}) / len(pop)`.

- [ ] **Step 1: Tests que fallan** — mismos tres tests parametrizados con `aco`, `ga`; más `test_ga_diversity_in_unit_interval`, `test_aco_tau_positive`.
- [ ] **Step 2: Ver que fallan.**
- [ ] **Step 3: Implementar.**
- [ ] **Step 4: `pytest tests/orienteering -q`** → PASS.
- [ ] **Step 5: Commit** `orienteering: trace ACO and GA iterations`

### Task 4: Trazas en DP y CP-SAT

**Files:**
- Modify: `src/orienteering/solvers/dp.py` (`solve`, `solve_many`, `closable_fast`, `closable_timed`), `src/orienteering/solvers/cpsat.py` (`solve`, `solve_here`)
- Test: `tests/orienteering/test_trace.py`

**Interfaces:**
- Produces: `dp.solve(problem, trace=None)`. Filas de progreso cada `max(1, 2**n // 100)` máscaras: `iter` (= máscaras procesadas), `best_prize`, `best_energy_j`, `masks_done`, `states`, `closable`; al final una fila por k = 1..n con `k`, `states_k`, `closable_k`, `best_prize_k`. `best_prize` del progreso = mejor premio entre los conjuntos cerrables vistos hasta ahí (usar `prizes_by_mask`).
- Produces: `cpsat.solve(problem, time_limit_s=None, trace=None)`. Con traza, `solve_here(problem, time_limit_s, record=True)` usa un `cp_model.CpSolverSolutionCallback` que guarda `{t_s, iter, objective, bound, phase}` (objective/bound en puntos) y los devuelve en `Solution.trace_rows` (nuevo campo opcional en `Solution`, default `None`); `solve` hace `trace.extend(sol.trace_rows)`. Funciona igual dentro o fuera del subproceso.

- [ ] **Step 1: Tests que fallan** — `test_dp_trace_same_result` (n=10..14, con y sin ventanas); `test_dp_trace_states_by_k` (suma de `closable_k` == `len(closable)`); `test_cpsat_trace_objective_monotone_and_bound_above` (`skipif` sin ortools; objective no decreciente en fase 1; `bound >= objective`; último objective == `sol.prize` cuando `optimal`).
- [ ] **Step 2: Ver que fallan.**
- [ ] **Step 3: Implementar.** En la DP, la traza no debe añadir trabajo por estado salvo un contador; el conteo `states_k` se hace en una pasada final sobre la tabla.
- [ ] **Step 4: `pytest tests/orienteering -q`** (incluye `test_dp_vs_brute`, `test_routing`) → PASS.
- [ ] **Step 5: Commit** `orienteering: trace DP state growth and CP-SAT objective/bound`

### Task 5: Verdad de referencia

**Files:**
- Create: `src/orienteering/lab/reference.py`
- Test: `tests/orienteering/test_lab.py`

**Interfaces:**
- Produces: `@dataclass Reference(prize: float, kind: str, upper_bound: float | None, solver: str | None, route: list[int])`; `exact_reference(problem, dp_max=18, cpsat_limit_s=120.0) -> tuple[Reference | None, list[Solution]]` (devuelve también las soluciones exactas que corrió, para que el ejecutor las guarde como filas); `finalize(ref: Reference | None, solutions: list[Solution]) -> Reference` (si `ref` es None o no probado, `best_known` = mejor `prize` entre todas, conservando `upper_bound`); `gap_pct(prize, ref_prize) -> float` (0.0 si `ref_prize <= 0`).
- Reglas: n ≤ dp_max → DP (`dp_optimal`) y además CP-SAT si hay ortools y n ≤ 60 (solo para medir tiempo); dp_max < n ≤ 60 → CP-SAT, `cpsat_optimal` si `optimal`; si no, `None` + cota.

- [ ] **Step 1: Tests que fallan** — `test_small_uses_dp`; `test_medium_uses_cpsat` (skipif sin ortools, n=25, límite 30 s); `test_cpsat_unproven_falls_back` (monkeypatch `cpsat.solve` → `optimal=False, bound=99` → `kind == "best_known"`, `upper_bound == 99`); `test_no_ortools_falls_back` (monkeypatch `importlib.util.find_spec("ortools")` → None); `test_gap_zero_reference`.
- [ ] **Step 2-4:** ver fallar, implementar, PASS.
- [ ] **Step 5: Commit** `lab: add ground-truth reference (DP, CP-SAT, best known)`

### Task 6: Datasets sintéticos y reales

**Files:**
- Create: `src/orienteering/lab/datasets.py`
- Test: `tests/orienteering/test_lab.py`

**Interfaces:**
- Produces: `@dataclass Instance(name: str, set: str, kind: str, problem: Problem, distance: np.ndarray, stations: list[dict])` (`stations`: `id, type, x, y, prize, service_s`; fila 0 = hábitat); `synthetic(n: int, kind: str, case: int) -> Instance` (semilla `10_000 * n + case + (0 if kind == "energy" else 5_000)`; puntos = primer `rng.random((n, 2)) * 100` de un `default_rng(semilla)` idéntico al que recibe `instances.random_instance`; `distance` euclídea); `real(n: int, case: int, scenario: str, graph=None) -> Instance` (`scenario` ∈ {`nominal`, `120min`}); `manual(scenario, graph=None) -> Instance` (13 manuales + E8, como `e6_benchmark.real_instances`); `save(inst, root=INSTANCES) -> Path`, `load(name, root=INSTANCES) -> Instance` (`.npz` + `.csv`, y `.geojson` en CRS del DEM para las reales); `build_all(synthetic=True, real=True, force=False) -> list[str]`; CLI `python -m orienteering.lab.datasets [--synthetic] [--real] [--force]`.
- Tamaños: sintéticos n ∈ {10, 12, 14, 16, 18, 20, 30, 40, 60, 100, 200} × {energy, windows} × casos 0-4; reales n ∈ {20, 40, 60, 100} × casos 0-1 × {nominal, 120min} (las matrices se calculan una vez por (n, caso) y los dos escenarios las comparten).
- Reales: grafo `api.planner.graph("data/base", 30.0, True)`; muestreo con `default_rng(7_000 + 100 * n + case)` de celdas en `main_component`, rechazo si a < 40 m de otra o del hábitat; matrices energía/tiempo/longitud por el camino de mínima energía (un `costs_from(..., predecessors=True)` por estación, `follow`, `path_cost(leg, "time_s")` y `path_cost(leg, "length_m")`). `service_j = service_s * grafos.build_rv.SERVICE_POWER_W`.
- Nombres: `syn-{kind}-n{n}-{case}`, `real-n{n}-{case}-{scenario}`, `manual-{scenario}`.

- [ ] **Step 1: Tests que fallan** — `test_synthetic_matches_random_instance` (misma `energy` que `random_instance(default_rng(semilla), n, kind)`); `test_synthetic_distance_bounds` (`0.9*d <= energy <= 1.2*d` fuera de la diagonal); `test_save_load_roundtrip`; `test_build_all_reuses` (segunda llamada sin `force` no reescribe: mismo `mtime` y hash, Review Focus 5); `test_real_spacing` (marcado `slow`, skip sin `data/base`: n=20, distancias euclídeas ≥ 40 m, matrices finitas).
- [ ] **Step 2-4:** ver fallar, implementar, PASS.
- [ ] **Step 5: Generar los datos** — `.venv/Scripts/python.exe -m orienteering.lab.datasets --synthetic --real` (en segundo plano; reales ≈ 5-10 min). Expected: ~110 sintéticas + 16 reales + 2 manuales en `data/lab/instances/`.
- [ ] **Step 6: Commit** `lab: add synthetic and real-terrain station datasets`

### Task 7: Ejecutor de experimentos y CSV

**Files:**
- Create: `src/orienteering/lab/run.py`
- Test: `tests/orienteering/test_lab.py`

**Interfaces:**
- Consumes: Tasks 1-6.
- Produces: `ALGORITHMS = ("dp", "cpsat", "ils", "sa", "aco", "ga")`; `SEEDED = {"sa", "aco", "ga"}`; `run_instance(inst, algorithms, seeds, dp_max, cpsat_limit_s) -> tuple[list[dict], dict[str, list[dict]]]` (filas de `runs.csv`, trazas por algoritmo); `run_suite(names, algorithms, seeds, dp_max, cpsat_limit_s, out_dir) -> Path`; `SUITES = {"quick": [...], "full": [...]}`; CLI `python -m orienteering.lab.run --suite quick|full [--instances ...] [--algorithms ...] [--seeds 0-9] [--dp-max 18] [--cpsat-limit 120]`.
- `quick`: `syn-energy-n10-0`, `syn-windows-n14-0`, `syn-energy-n30-0`, `real-n20-0-nominal`, semillas 0-2. `full`: todas, semillas 0-9.
- Algoritmos deterministas (dp, cpsat, ils) corren una vez con `seed = ""`.
- Columnas de `runs.csv` (este orden): `instance, set, kind, n, algorithm, seed, status, prize, reference_prize, reference_kind, upper_bound, gap_pct, is_optimal, energy_j, energy_wh, budget_used_pct, distance_m, walk_time_s, duration_s, n_visited, route, runtime_s, iterations, evaluations, feasible`. `status` ∈ {`ok`, `skipped_size`, `error`}; `route` con los `id` de estación unidos por `-`; `distance_m` y `walk_time_s` sumando las matrices sobre la ruta (sintéticas: unidades del plano en `distance_m`).
- También escribe `config.json` (parámetros de cada solver, `ortools` versión, `platform.platform()`, `dp_max`, `cpsat_limit_s`), `instances.csv` (`instance, set, kind, n, budget, max_duration_s, reference_prize, reference_kind, upper_bound`) y `traces/trace_<algoritmo>.csv` (columnas `instance, seed` + las de la traza; SA con `Tracer(every=20)`).
- Orden por instancia: `exact_reference`, metaheurísticas, `finalize`, y entonces calcular `gap_pct` e `is_optimal` de todas las filas.

- [ ] **Step 1: Tests que fallan** — `test_run_instance_columns` (columnas exactas); `test_all_routes_feasible` (`evaluate_route` sobre cada `route`); `test_dp_skipped_when_too_big` (n=30 → fila `dp` con `status == "skipped_size"`); `test_empty_route_instance` (presupuesto 0 → `prize 0`, `gap_pct 0`, sin NaN, Review Focus 1); `test_run_suite_writes_files` (suite mínima en `tmp_path`: `runs.csv`, `instances.csv`, `config.json`, `traces/trace_sa.csv`).
- [ ] **Step 2-4:** ver fallar, implementar, PASS.
- [ ] **Step 5: Correr `--suite quick`** → carpeta en `data/lab/runs/`; revisar a mano `runs.csv`.
- [ ] **Step 6: Commit** `lab: add experiment runner writing runs, instances and trace CSVs`

### Task 8: Análisis, estadística y figuras

**Files:**
- Create: `src/orienteering/lab/analyze.py`
- Test: `tests/orienteering/test_lab.py`

**Interfaces:**
- Consumes: archivos de Task 7.
- Produces: `summarize(runs: list[dict]) -> list[dict]` (por `algorithm` × `size_bucket` ∈ {`10-18`, `20-40`, `60-200`}: `runs, mean_gap_pct, median_gap_pct, std_gap_pct, optimal_share, mean_runtime_s, median_runtime_s, mean_evaluations`); `stats(runs) -> list[dict]` (Friedman sobre el gap medio por instancia de las 4 metaheurísticas + DP/CP-SAT donde corrieron; Wilcoxon por pares con Holm: `a, b, statistic, p_value, p_holm, n_instances`); `figures(run_dir) -> list[Path]`; CLI `python -m orienteering.lab.analyze <run_dir>` → `<run_dir>/analysis/summary.csv`, `stats.csv`, `fig1_convergence.png` … `fig7_performance_profile.png` (los 7 del spec §5, en ese orden).
- Paleta: la de `e6_benchmark.COLOURS` extendida a 6 (`dp`, `cpsat` separados), leyenda fija en las 7 figuras.

- [ ] **Step 0: Cargar la skill `dataviz`.**
- [ ] **Step 1: Tests que fallan** — `test_summarize_known_values` (filas sintéticas a mano → medias exactas); `test_stats_holm_monotone` (`p_holm >= p_value`); `test_figures_written` (sobre la corrida mínima de Task 7: 7 PNG no vacíos).
- [ ] **Step 2-4:** ver fallar, implementar, PASS.
- [ ] **Step 5: Analizar la corrida `quick` y mirar las 7 figuras** (Read de cada PNG); corregir lo ilegible.
- [ ] **Step 6: Commit** `lab: add summary, Friedman/Wilcoxon stats and comparison figures`

### Task 9: API: `solver` en `/plan` y endpoints del laboratorio

**Files:**
- Modify: `api/plan.py` (`PlanRequest.solver: Literal["auto","dp","cpsat","ils","sa","aco","ga"] = "auto"`), `api/tour.py` (`_delegate`: `_e5_plan_tour(req, g, req.solver)`), `api/main.py` (`app.include_router(lab.router)` antes del `mount("/")`)
- Create: `api/lab.py`
- Test: `tests/api/test_lab_api.py`

**Interfaces:**
- Produces: `GET /lab/runs` → `[{id, created, instances, rows}]`; `GET /lab/runs/{id}/summary` → JSON de `analysis/summary.csv` (404 si falta); `GET /lab/runs/{id}/files/{path}` → CSV/PNG dentro de la carpeta (rechaza `..`); `GET /lab/instances` → `[{name, set, kind, n}]`; `GET /lab/instances/{name}` → estaciones (+ GeoJSON para reales); `POST /lab/solve` body `{instance: str, algorithms: list[str], seeds: list[int] = [0]}` → `{reference, runs: [...filas de runs.csv...], traces: {alg: [filas]}, stations}`. Límites: ≤ 6 algoritmos, ≤ 5 semillas; nombres válidos o 422 (Review Focus 4).

- [ ] **Step 1: Tests que fallan** — `test_plan_accepts_solver` (`/plan` con `solver="ils"` responde con `method == "ils"`, skip sin datos como en `test_api.py`); `test_lab_solve_small` (instancia sintética n=10, `["dp","sa"]`, semillas `[0,1]` → 3 filas, trazas `sa` no vacías); `test_lab_solve_rejects_bad_input` (instancia/algoritmo inexistente, 6 semillas → 422); `test_lab_files_no_traversal` (`..` → 400/404).
- [ ] **Step 2-4:** ver fallar, implementar, `pytest tests/api -q` → PASS.
- [ ] **Step 5: Commit** `api: add solver choice to /plan and lab endpoints`

### Task 10: UI: selector en el HUD y página Laboratorio

**Files:**
- Modify: `web/index.html` (select `#solver` en "More options" del panel Plan, `solver` en el body de `requestPlan`, enlace "Lab" junto a "Data sources")
- Create: `web/lab.html`, `web/lab.js`
- Test: `tests/web/lab.test.mjs` (mismo estilo que `tests/web/landing.test.mjs`)

**Interfaces:**
- Consumes: endpoints de Task 9.
- `lab.html`, en español, tres secciones: **Corridas** (select de `/lab/runs`, tabla de `summary`, galería de las 7 figuras, enlaces a `runs.csv`, `instances.csv`, `traces/*.csv`); **Ejecutar** (select de instancia, checkboxes de algoritmos, semillas 1-5, botón; mientras corre, botón ocupado con `aria-busy`); **Resultados en vivo** (tabla de filas, gráfica SVG de convergencia `best_prize` vs `t_s` por algoritmo/semilla, gráfica SVG de la ruta de cada algoritmo sobre las estaciones; mismo color por algoritmo que las figuras).
- `lab.js` exporta funciones puras testeables: `convergenceSeries(traces) -> {alg: [[t, prize], ...]}`, `scale(domain, range) -> fn`, `routePolyline(stations, routeIds) -> "x,y x,y ..."`.

- [ ] **Step 1: Tests que fallan** — `convergenceSeries` agrupa por algoritmo y semilla y ordena por `t_s`; `routePolyline` respeta el orden; `index.html` contiene `id="solver"` y el body de `/plan` incluye `solver`.
- [ ] **Step 2-4:** ver fallar, implementar, `node --test tests/web` → PASS.
- [ ] **Step 5: Prueba manual con la skill `run`**: arrancar la app, planear en el HUD con `sa` y con `dp`, abrir `/lab.html`, ejecutar `syn-energy-n14-0` con los 6 algoritmos; capturas.
- [ ] **Step 6: Commit** `web: add solver selector to the HUD and the lab page`

### Task 11: Corrida completa y guía

**Files:**
- Create: `docs/lab/README.md`

- [ ] **Step 1: Correr `--suite full`** en segundo plano y luego `analyze`. Expected: `runs.csv` con todas las instancias, `reference_kind` repartido entre los tres tipos, ninguna fila `feasible == False`.
- [ ] **Step 2: Escribir `docs/lab/README.md`** (español): comandos de las Tasks 6-8 y 10, significado de cada columna de cada CSV, cómo leer cada figura, la tabla de DP vs CP-SAT por tamaño (cuál fue más rápido), limitaciones (DP ≤ 18/20, `best_known` no es óptimo).
- [ ] **Step 3: `pytest tests/orienteering tests/api -q` y `node --test tests/web`** → todo PASS frente a la línea base.
- [ ] **Step 4: Commit** `docs: add lab guide with how to run and read the results`
