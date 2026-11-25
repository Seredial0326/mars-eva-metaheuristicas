# Laboratorio de metaheurísticas para la ruta del astronauta (diseño)

Fecha: 2026-11-25 · Rama local `clase-metaheuristicas` (copia del repo para la clase; nada se sube a GitHub).

## Intención

El proyecto del hackatón pasa a ser el proyecto final de la clase de Metaheurísticas. El
problema es un *orienteering problem* (OP): desde el hábitat, elegir qué estaciones visitar
y en qué orden para maximizar el puntaje científico sin pasarse del presupuesto de energía
(y, opcionalmente, de la duración máxima y las ventanas de tiempo). El código ya resuelve el
OP con dos métodos exactos (DP por subconjuntos, CP-SAT) y cuatro metaheurísticas (ILS, SA,
ACO, GA). Lo que falta para la clase es **ver y medir** cómo se comporta cada uno:

1. un dataset de estaciones más grande que las 13 manuales + E8;
2. un registro iteración por iteración del comportamiento interno de cada algoritmo;
3. CSV con todo lo calculado (ruta, puntaje, energía, distancia, tiempos, gap);
4. gráficas y estadísticas para compararlos en calidad (accuracy) y eficiencia;
5. acceso desde la UI.

## Objetivos, no objetivos y anti-objetivos

- **Objetivos:** comparar los seis métodos sobre las mismas instancias, con una verdad de
  referencia (ground truth) honesta; trazas que permitan explicar en el informe *por qué* un
  algoritmo converge o se estanca; todo reproducible con un comando y semillas fijas.
- **No objetivos:** cambiar los algoritmos ni sus parámetros por defecto; ajuste de
  hiperparámetros (queda como extensión); tocar GitHub (sin push, sin PR, sin board).
- **Anti-objetivos:** que el registro altere el resultado de un solver (con `trace=None` cada
  solver debe dar exactamente la misma ruta que hoy); un "óptimo" que en realidad no está
  probado presentado como óptimo.

## Restricciones

- Python 3.14 en `.venv`. `ortools` no está instalado; existe la rueda `ortools-9.15.6755-cp314`
  y se instala en `.venv` con permiso del usuario.
- La DP es O(2ⁿ·n²) en tiempo y guarda 2ⁿ·n estados en listas de Python: hasta 20 nodos
  (`dp.MAX_STATIONS`), y con 20 usa del orden de cientos de MB. La máquina ya se quedó corta de
  memoria una vez en esta sesión, así que el barrido por defecto de la DP llega a n = 18 y
  n = 20 es opcional (`--dp-max 20`).
- CP-SAT admite hasta 60 nodos (`cpsat.MAX_STATIONS`). En Windows corre en un subproceso
  (`routing.solve_isolated`), así que un callback de Python no cruza ese límite: la traza de
  CP-SAT se recoge dentro del subproceso y vuelve con la `Solution`.
- Terreno real: grafo humano E3×E1 en ~4 s, un Dijkstra ~0,7 s. 100 estaciones ≈ 100
  Dijkstras ≈ 2 min; las matrices se guardan en caché (`.npz`).
- Los datos y resultados van en `data/lab/` (ignorado por git, igual que `data/e6/`).

## Enfoques considerados (elegido: A)

- **A. Registro dentro de cada solver + módulo de laboratorio** (elegido por el usuario). Cada
  solver recibe `trace=None` opcional; un paquete nuevo `src/orienteering/lab/` genera datos,
  corre experimentos, escribe CSV y dibuja. Un solo código por algoritmo: la UI y los
  experimentos ven lo mismo.
- B. Copiar los solvers a otra carpeta con el registro: dos versiones que se desincronizan y
  la UI seguiría usando la vieja. Descartado.
- C. Como A pero el análisis en un notebook: cómodo para explorar, menos reproducible para el
  informe. Descartado (los CSV de A se pueden abrir igual en un notebook).

## Diseño

### 1. Trazas (`trace`)

`src/orienteering/lab/trace.py` define `Tracer`: un objeto invocable `tracer(**campos)` que
añade una fila con `t_s` (segundos desde que el solver empezó) y los campos que le pasan.
`Tracer(every=k)` guarda una de cada k filas para los bucles largos (SA hace 20 000 pasos);
la última fila siempre se guarda. `tracer.rows` es una lista de dicts; `tracer.to_csv(path)`.

Cada solver acepta `trace=None` y, solo si no es `None`, lo llama. Campos comunes en todas las
filas: `iter`, `best_prize`, `best_energy_j`. Campos propios:

| Solver | Una fila por | Campos propios |
|---|---|---|
| `dp` | cada 1/100 de las máscaras y al final, una fila por tamaño de subconjunto k | `masks_done`, `states` (estados (máscara, i) alcanzables), `closable` (conjuntos que cierran en presupuesto), `k` y `best_prize_k` en las filas finales |
| `cpsat` | cada solución nueva que encuentra el solver | `objective`, `bound` (cota superior), `phase` (1 = puntaje, 2 = energía) |
| `ils` | iteración | `current_prize`, `shake_size`, `shake_at`, `stale`, `improved` |
| `sa` | paso | `temp`, `move` (add/drop/swap/reverse), `feasible`, `accepted`, `delta`, `current_score` |
| `aco` | iteración | `round_best_prize`, `ants_mean_prize`, `tau_mean`, `tau_max`, `stale` |
| `ga` | generación | `pop_best`, `pop_mean`, `pop_worst`, `diversity` (rutas distintas / población), `stale` |

Además `heuristics.Evaluator` cuenta cuántas veces evalúa una ruta (`ev.evaluations`); ese
número va en `runs.csv` como medida de esfuerzo independiente de la máquina.

Garantía: con `trace=None` ninguna rama nueva se ejecuta y los resultados no cambian. Un test
compara, para varias instancias y semillas, la ruta con y sin `Tracer`.

### 2. Verdad de referencia (`lab/reference.py`)

Para cada instancia, en este orden:

- **n ≤ `--dp-max` (18 por defecto):** DP → óptimo probado. CP-SAT también corre en estas
  instancias, para medir cuál de los dos exactos es más rápido (ese es el criterio "si CP-SAT
  es más rápido, úsalo": la tabla lo dice por tamaño).
- **n ≤ 60:** CP-SAT con límite `--cpsat-limit` (120 s por defecto). Si prueba el óptimo,
  `reference_kind = cpsat_optimal`; si no, entra en el caso siguiente pero se guarda su cota.
- **resto:** la mejor solución encontrada por cualquier método y semilla,
  `reference_kind = best_known`, con `upper_bound` = cota de CP-SAT cuando la hay.

`gap_pct = 100 · (referencia − puntaje) / referencia`. Con `best_known` el gap es relativo a lo
mejor conocido y se marca así en tablas y gráficas.

### 3. Datasets (`lab/datasets.py`)

Cada instancia se guarda en `data/lab/instances/<nombre>.npz` (matrices energía, tiempo,
distancia; premio; servicio; ventanas; presupuesto) y sus estaciones en `<nombre>.csv`
(+ `.geojson` para las reales).

- **Sintéticas (escalabilidad):** se reutiliza `instances.random_instance` (puntos en un
  cuadrado 100×100, asimetría 0,9-1,2, premios 1-5). Tamaños n ∈ {10, 12, 14, 16, 18, 20, 30,
  40, 60, 100, 200}, tipos `energy` y `windows`, 5 instancias por tamaño y tipo, semillas
  fijas. Distancia = euclídea.
- **Terreno real (caso de estudio y UI):** estaciones muestreadas dentro de la componente
  principal del grafo humano, a ≥ 40 m entre sí y del hábitat (centro de la caja), con tipo al
  azar entre ridge/hollow/contact/curiosity, puntaje de `stations_rubric.json` y tiempo de
  servicio por tipo (el que usan las estaciones manuales). Tamaños n ∈ {20, 40, 60, 100}, más
  las 13 manuales + E8 existentes. Presupuesto 1000 Wh con 10 % de margen (el de E5), y una
  variante con 120 min. La matriz de distancia se mide sobre el camino de mínima energía.

`python -m orienteering.lab.datasets --synthetic --real` genera todo; las instancias ya
existentes se reutilizan.

### 4. Ejecutor (`lab/run.py`)

`python -m orienteering.lab.run --suite quick|full [--algorithms ...] [--seeds 0-9]
[--dp-max 18] [--cpsat-limit 120]` crea `data/lab/runs/<fecha-hora>/` con:

- `config.json`: parámetros de cada algoritmo, semillas, versión de ortools, máquina.
- `instances.csv`: una fila por instancia (set, n, tipo, presupuesto, referencia, cota).
- `runs.csv`: una fila por (instancia, algoritmo, semilla): `prize`, `reference_prize`,
  `reference_kind`, `upper_bound`, `gap_pct`, `is_optimal`, `energy_j`, `energy_wh`,
  `budget_used_pct`, `distance_m`, `walk_time_s`, `duration_s`, `n_visited`, `route` (ids
  separados por `-`), `runtime_s`, `iterations`, `evaluations`, `feasible` (revisado con
  `evaluate_route`).
- `traces/trace_<algoritmo>.csv`: formato largo, columnas `instance`, `seed` + las de la traza.

Las metaheurísticas mantienen su límite de 10 s. `quick` = unas pocas instancias pequeñas
(≈ 1 min) para probar; `full` = todo (decenas de minutos, en segundo plano).

### 5. Análisis y gráficas (`lab/analyze.py`)

`python -m orienteering.lab.analyze data/lab/runs/<id>` escribe en `<id>/analysis/`:

- `summary.csv`: por algoritmo y tamaño, media/mediana/desv. del gap, % de veces óptimo, tiempo
  medio y mediano, evaluaciones.
- `stats.csv`: test de Friedman sobre los rangos por instancia y Wilcoxon por pares con
  corrección de Holm (scipy).
- Figuras PNG:
  1. convergencia: mejor puntaje vs tiempo e iteración, mediana y rango intercuartil entre
     semillas, una instancia por tamaño;
  2. calidad vs tiempo: gap medio contra tiempo medio (frontera de eficiencia);
  3. escalabilidad: tiempo vs n en escala log (DP exponencial frente a CP-SAT y
     metaheurísticas);
  4. boxplots del gap por algoritmo y tamaño (robustez entre semillas);
  5. dinámica interna: temperatura y tasa de aceptación de SA, feromona de ACO, diversidad del
     GA, tamaño del shake de ILS, estados por k de la DP, objetivo y cota de CP-SAT;
  6. rutas: la ruta de cada algoritmo sobre el plano (sintéticas) o sobre el hillshade
     (reales);
  7. perfil de desempeño (Dolan-Moré): fracción de instancias resueltas a ≤ τ del mejor.

### 6. UI

- **HUD (`web/index.html`)**: selector "Algoritmo" (auto, dp, cpsat, ils, sa, aco, ga) en el
  panel del plan. `PlanRequest` gana `solver: str = "auto"`; `api/tour.py` lo pasa a E5
  `plan_tour(req, g, solver)`. La tarjeta del plan ya muestra el método y su tiempo.
- **Página Laboratorio (`web/lab.html` + `web/lab.js`)**, enlazada desde el HUD:
  - elegir una corrida de `data/lab/runs/` y ver su `summary.csv` y sus figuras, con enlaces
    para descargar los CSV;
  - "Ejecutar": elegir una instancia, algoritmos y semillas, correrlos en el servidor y ver
    sus curvas de convergencia y sus rutas, dibujadas en SVG sin librerías nuevas.
  - Endpoints nuevos en `api/lab.py` (router montado en `api/main.py`): `GET /lab/runs`,
    `GET /lab/runs/{id}/...` (CSV y PNG), `GET /lab/instances`, `POST /lab/solve`.
    `POST /lab/solve` es síncrono y limita la petición (≤ 6 algoritmos × 5 semillas, n ≤ 60
    para la DP/CP-SAT según sus límites).

### 7. Verificación

- `tests/orienteering/test_trace.py`: misma ruta con y sin traza (todos los solvers, varias
  semillas); `best_prize` nunca baja; columnas esperadas por solver.
- `tests/orienteering/test_lab.py`: referencia elige DP / CP-SAT / best_known según n; el
  ejecutor en una suite mínima escribe `runs.csv` y `traces/` con las columnas acordadas y
  todas las rutas son factibles.
- `tests/api/`: `/plan` acepta `solver`; `/lab/solve` devuelve trazas y rutas.
- Los tests existentes (`tests/orienteering`, `tests/api`) siguen pasando.
- Prueba manual: `--suite quick`, `analyze`, abrir el HUD y el Laboratorio en el navegador.

## Decisiones que quedan al implementador

Nombres internos, la forma exacta de dibujar cada figura (siguiendo la guía de
visualización), el muestreo de estaciones reales cuando un punto cae en celda bloqueada (se
redibuja), y el orden de las columnas en los CSV.

## Decisiones mías (revisables)

- DP hasta n = 18 por defecto por la memoria; 20 con bandera.
- CP-SAT con 120 s por instancia (el del benchmark E6).
- Resultados en `data/lab/` (no versionado), commits solo en la rama local.
- Sin nota en `paper/notes/` (regla del hackatón); en su lugar `docs/lab/README.md` con cómo
  correr todo y cómo leer cada CSV y figura.
