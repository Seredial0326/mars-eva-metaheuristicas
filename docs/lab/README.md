# Laboratorio de metaheurísticas: guía

Esta guía explica cómo correr el laboratorio que compara seis algoritmos de ruta sobre el
mismo conjunto de estaciones, qué archivos produce, cómo leer sus gráficas y qué resultados
dio la corrida final. Todo el código vive en `src/orienteering/lab/`, `api/lab.py` y
`web/lab.html`.

## 1. Qué es

El problema es el **Orienteering Problem (OP)** del astronauta: hay un hábitat (nodo 0, salida
y llegada), `n - 1` estaciones con un puntaje (`prize`) cada una, y un presupuesto de energía.
Caminar entre estaciones y trabajar en cada una (servicio, 10 min) gasta energía. Hay que
elegir **qué estaciones visitar y en qué orden** para maximizar el puntaje total sin pasarse
del presupuesto **y sin pasarse de la duración máxima de la EVA** (120 o 180 min, según el
escenario). No hay ventanas de horario: solo energía y duración. Es NP-difícil: los métodos exactos sirven hasta cierto tamaño y las
metaheurísticas escalan sin garantía de óptimo.

Los seis algoritmos están en `src/orienteering/solvers/` (todos tienen la forma
`solve(problem) -> Solution`):

| Algoritmo | Archivo | Cómo funciona (una línea) |
|---|---|---|
| `dp` | `dp.py` | Programación dinámica exacta por máscaras de bits: estados (conjunto visitado, última estación); con ventanas guarda etiquetas de Pareto. Hasta 20 nodos. |
| `cpsat` | `cpsat.py` | Modelo exacto de OR-Tools CP-SAT (circuito sobre estaciones opcionales); prueba el óptimo dentro del límite de tiempo o devuelve su mejor ruta con una cota superior (`Solution.bound`). Hasta 60 nodos. |
| `ils` | `ils.py` | Búsqueda local iterada: inserción por mejor razón, 2-opt e intercambios; luego una perturbación que quita S paradas consecutivas (S crece). Determinista. |
| `sa` | `sa.py` | Recocido simulado: movimientos aleatorios (agregar, quitar, intercambiar, invertir tramo) con aceptación `exp(-pérdida / T)` y T enfriándose; pule la mejor ruta con la búsqueda local del ILS. Con semilla. |
| `aco` | `aco.py` | Colonia de hormigas (Ant Colony System): cada hormiga construye una ruta factible guiada por feromona y (puntaje / energía añadida); pule la mejor de la iteración. Con semilla. |
| `ga` | `ga.py` | Algoritmo genético: población de rutas factibles, torneo, cruce por orden, mutación, elitismo y reparación; pule la mejor con la búsqueda local del ILS. Con semilla. |

Los módulos del laboratorio son:

- `lab/datasets.py`: genera y guarda las instancias.
- `lab/reference.py`: calcula la verdad de referencia (el valor contra el que se mide el gap).
- `lab/trace.py`: `Tracer`, que registra una fila por iteración de cada solver.
- `lab/run.py`: el corredor de experimentos (algoritmos x instancias x semillas).
- `lab/analyze.py`: tablas, pruebas estadísticas y las siete figuras.
- `api/lab.py` y `web/lab.html` + `web/lab.js`: la página del laboratorio en la aplicación.

## 2. Cómo correr todo

Desde la raíz del repo, con el entorno virtual `.venv`. El paquete `orienteering` está en
`src/`, por eso se define `PYTHONPATH=src` (no hay `pyproject.toml`).

Bash (Git Bash):

```bash
# 1. Datasets (se guardan en data/lab/instances/, ignorado por git; unos 2 min)
PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.datasets

# 2. Corrida rápida (2 instancias) o completa (las 16 de disco); semillas 0-2 en ambas
PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.run --suite quick --dp-max 20
PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.run --suite full --dp-max 20 --cpsat-limit 60 --out data/lab/runs/final

# 3. Análisis: tablas, estadística y figuras
PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.analyze data/lab/runs/final

# 4. La aplicación (la página del laboratorio queda en /lab.html)
.venv/Scripts/python.exe -m uvicorn api.main:app --port 8000
# o bien: python tools/demo.py run
```

PowerShell:

```powershell
$env:PYTHONPATH="src"
.venv\Scripts\python.exe -m orienteering.lab.datasets
.venv\Scripts\python.exe -m orienteering.lab.run --suite full --dp-max 20 --cpsat-limit 60 --out data\lab\runs\final
.venv\Scripts\python.exe -m orienteering.lab.analyze data\lab\runs\final
.venv\Scripts\python.exe -m uvicorn api.main:app --port 8000
```

Opciones de cada comando (tomadas de `--help`):

| Comando | Opción | Qué hace |
|---|---|---|
| `datasets` | `--synthetic` | Además de las 16 de terreno, genera las sintéticas (solo se usan en las pruebas unitarias). |
| `datasets` | `--force` | Regenera las que ya existen (sin él se reutilizan tal cual). |
| `run` | `--suite {quick,full}` | Obligatoria. `quick`: `real-n20-0-120min` y `real-n20-0-180min`. `full`: todas las de disco. Ambas con semillas 0-2. |
| `run` | `--instances a,b,c` | Lista de instancias; reemplaza a la de la suite. |
| `run` | `--algorithms dp,cpsat,ils,sa,aco,ga` | Subconjunto de algoritmos (por defecto los seis). |
| `run` | `--seeds 0-9` o `0,3,5` | Semillas de `sa`, `aco` y `ga` (por defecto las de la suite). |
| `run` | `--dp-max 18` | Máximo de nodos para el DP (por defecto 18, tope 20). Con las instancias de este laboratorio se usa 20: el límite de duración poda casi todos los estados y el DP resuelve 20 nodos en menos de 1 s. |
| `run` | `--cpsat-limit 120` | Segundos máximos de CP-SAT por instancia (por defecto 120; la corrida final usó 60). |
| `run` | `--out DIR` | Carpeta de salida (por defecto `data/lab/runs/<YYYYmmdd-HHMMSS>`). |
| `analyze` | `run_dir` | Carpeta escrita por `run`; deja todo en `<run_dir>/analysis/`. |

En la aplicación hay dos entradas al laboratorio:

- **HUD (`/`)**: en los ajustes del plan hay un selector **Route solver** (Auto, DP, CP-SAT,
  ILS, SA, ACO, GA). "Auto" es exacto: DP hasta 19 nodos y CP-SAT por encima. El resultado
  del plan muestra el solver usado y su tiempo. El chip **Lab ›** abre la página del
  laboratorio.
- **`/lab.html`**: lista las corridas guardadas en `data/lab/runs/`, muestra su resumen y sus
  figuras, y permite resolver una instancia en vivo con los algoritmos que se elijan
  (`POST /lab/solve`; en vivo CP-SAT usa 30 s y el DP llega a 18 nodos).

## 3. Datasets

`datasets.py` crea **16 instancias sobre el terreno real** de Marte (el mismo grafo de costo
humano que usa `/plan`). **`n` es el número de nodos incluyendo el hábitat** (nodo 0); una
instancia con `n = 20` tiene 19 estaciones.

**Un solo conjunto de estaciones.** Las estaciones marcadas a mano y las nuevas no se tratan
por separado: forman un único *pool* de 120 estaciones del que cada instancia saca las suyas.

- Primero entran las estaciones manuales (`data/stations/stations_manual.gpkg`) y las de E8
  (`stations_e8.gpkg`, si existe), con su tipo, puntaje y tiempo de servicio. Sus ventanas de
  horario se descartan.
- El resto del pool se genera sobre la componente principal del grafo con semilla fija (7000).
  Las nuevas se llaman `G1`, `G2`, ... y cada una queda a >= 40 m del hábitat y de
  todas las que ya están en el pool. Su
  tipo y puntaje salen de `data/stations/stations_rubric.json` (ridge 5, hollow 4, contact 4,
  curiosity 3) y su servicio es de 10 min.
- Las matrices de energía, tiempo y distancia se calculan una sola vez para todo el pool
  (121 Dijkstras, unos 2 min). Cada instancia toma la submatriz de sus estaciones, que es
  exactamente la que daría calcularla aparte, porque el costo de un tramo no depende de las
  demás estaciones.

| Nombre | Cuántas | Qué son |
|---|---|---|
| `real-n<n>-<caso>-<escenario>` | 16 | `n` en **20, 50, 80 y 100**; casos 0-1 (cada caso es otra muestra del pool, semilla `7000 + 100 n + caso`); escenarios **`120min`** y **`180min`** (duración máxima de 7200 s y 10800 s). Las dos versiones de un mismo caso comparten estaciones y matrices; solo cambia el límite de duración. |

Todas las instancias usan solo energía (sin ventanas de horario) con un presupuesto de
**1000 Wh y 10 % de margen**, es decir 900 Wh útiles, más la duración máxima del escenario
(los tiempos incluyen caminata y servicio). Cada instancia se guarda como `<nombre>.npz`
(matrices y campos del problema), `<nombre>.csv` (estaciones: `id, type, x, y, prize,
service_s`) y `<nombre>.geojson`. Volver a correr `datasets` reutiliza las que ya existen sin
cambiar su contenido.

Las instancias sintéticas (`syn-<kind>-n<n>-<caso>`, puntos aleatorios en un plano) siguen
en el código, pero solo para las pruebas unitarias: no tienen tiempos de caminata, así que no
se les puede poner el límite de duración.

## 4. Verdad de referencia

Para medir qué tan lejos queda cada algoritmo hace falta un valor de referencia por instancia
(`reference.py`). Hay tres tipos (`reference_kind`):

| `reference_kind` | Cuándo | Significado |
|---|---|---|
| `dp_optimal` | `n <= --dp-max` (20 en la corrida final: las instancias de 20 nodos) | El DP probó el óptimo. CP-SAT también corre, solo para medir su tiempo. |
| `cpsat_optimal` | `dp-max < n <= 60` (aquí, las de 50 nodos) y CP-SAT probó el óptimo dentro de `--cpsat-limit` | Óptimo probado por CP-SAT. |
| `best_known` | El resto: CP-SAT no lo probó a tiempo, o `n > 60` (las de 80 y 100 nodos) | El mejor puntaje que encontró **cualquier** algoritmo de la corrida (empate: menor energía). **No es un óptimo probado.** Si CP-SAT corrió, `upper_bound` guarda su cota superior; si no hay cota queda vacío. |

- `gap_pct = 100 * (reference_prize - prize) / reference_prize`; vale 0 si la referencia es
  <= 0 (instancia donde ninguna estación cabe).
- `is_optimal = prize >= reference_prize - 1e-6`. Con `dp_optimal` y `cpsat_optimal` significa
  "alcanzó el óptimo". Con `best_known` significa **"igualó al mejor conocido"**, no que sea
  óptimo. Por eso con `best_known` un gap de 0 no prueba optimalidad.
- Con `best_known` el gap solo puede ser >= 0 y el mejor algoritmo siempre tiene gap 0.

## 5. Qué hay en cada CSV

Una corrida (`data/lab/runs/<id>/`) contiene `runs.csv`, `instances.csv`, `config.json` y
`traces/trace_<algoritmo>.csv`; `analyze` agrega `analysis/` con `summary.csv`, `stats.csv` y
las figuras.

### `runs.csv`: una fila por (instancia, algoritmo, semilla)

| Columna | Significado |
|---|---|
| `instance` | Nombre de la instancia. |
| `set` | `real` (las sintéticas de las pruebas dicen `synthetic`). |
| `kind` | Escenario: `120min` o `180min`. |
| `n` | Nodos, hábitat incluido. |
| `algorithm` | `dp`, `cpsat`, `ils`, `sa`, `aco` o `ga`. |
| `seed` | Semilla; vacía en `dp`, `cpsat` e `ils` (deterministas). |
| `status` | `ok`; `skipped_size` (n supera el límite del algoritmo, el DP supera `--dp-max`, o CP-SAT sin `ortools`); `error` (el solver lanzó una excepción, el mensaje va a stderr y la corrida sigue). En las filas `skipped_size` y `error` los campos de resultado quedan vacíos, pero los de referencia sí se llenan. |
| `prize` | Puntaje de la ruta. |
| `reference_prize` | Puntaje de referencia de la instancia. |
| `reference_kind` | `dp_optimal`, `cpsat_optimal` o `best_known`. |
| `upper_bound` | Cota superior probada del óptimo (vacía si no se conoce). |
| `gap_pct` | Brecha porcentual contra la referencia (ver sección 4). |
| `is_optimal` | `prize >= reference_prize - 1e-6` (ver sección 4). |
| `energy_j` | Energía de la ruta en joules: caminar más servicio (más esperas, si el problema las pondera). |
| `energy_wh` | `energy_j / 3600`. |
| `budget_used_pct` | `100 * energy_j / presupuesto` (vacía si el presupuesto es <= 0). |
| `distance_m` | Suma de la matriz de distancias sobre los tramos de la ruta (unidades del plano en las sintéticas). |
| `walk_time_s` | Suma de `problem.time` sobre los tramos (vacía si el problema no tiene tiempos). |
| `duration_s` | `Solution.duration_s`: instante en que termina la ruta, con esperas y servicio. |
| `n_visited` | Estaciones distintas visitadas, sin contar inicio y fin. |
| `route` | Ids de las estaciones en orden, separados por `-`. |
| `runtime_s` | Segundos que tardó el solver. |
| `iterations` | Iteraciones del lazo (metaheurísticas; en el DP, máscaras procesadas). |
| `evaluations` | Chequeos de factibilidad contados (incluye las verificaciones finales). Vacía donde no se cuenta. |
| `feasible` | Veredicto de `evaluate_route` y `energy <= presupuesto + 1e-6` (una ruta vacía es factible). |

### `instances.csv`: una fila por instancia

`instance`, `set`, `kind`, `n`, `budget` (J, o unidades del plano en las sintéticas),
`max_duration_s` (vacía si no hay límite), `reference_prize`, `reference_kind`, `upper_bound`.

### `config.json`

Algoritmos y semillas usados, `dp_max`, `cpsat_limit_s`, versión de `ortools`, plataforma y
Python, `max_stations` por algoritmo, cada cuántas filas se traza (`trace_every`) y los
parámetros por defecto de cada solver. Sirve para reproducir la corrida.

### `traces/trace_<algoritmo>.csv`: una fila por iteración

Formato largo: las columnas `instance` y `seed` van primero y todas las filas tienen `t_s`
(segundos desde que arrancó el solver). Las columnas de cada algoritmo:

| Archivo | Columnas propias | Qué son |
|---|---|---|
| `trace_ils.csv` | `iter`, `best_prize`, `best_energy_j`, `current_prize`, `shake_size`, `shake_at`, `stale`, `improved` | Una fila por vuelta del lazo. `current_prize`: puntaje de la solución actual; `shake_size` / `shake_at`: tamaño y posición de la perturbación; `stale`: vueltas sin mejorar; `improved`: si esta vuelta mejoró. |
| `trace_sa.csv` | `iter`, `best_prize`, `best_energy_j`, `temp`, `move`, `feasible`, `accepted`, `delta`, `current_score` | Una fila por paso: temperatura, tipo de movimiento, si era factible y si se aceptó, cambio de puntaje (`delta`) y puntaje actual. |
| `trace_aco.csv` | `iter`, `best_prize`, `best_energy_j`, `round_best_prize`, `ants_mean_prize`, `tau_mean`, `tau_max`, `stale` | Una fila por iteración: mejor de la ronda, media de las hormigas y media / máximo de la feromona. |
| `trace_ga.csv` | `iter`, `best_prize`, `best_energy_j`, `pop_best`, `pop_mean`, `pop_worst`, `diversity`, `stale` | Una fila por generación: mejor, media y peor de la población, y `diversity` (fracción de rutas distintas). |
| `trace_cpsat.csv` | `iter`, `objective`, `bound`, `phase`, `best_prize`, `best_energy_j` | Una fila por solución hallada: `phase` 1 = maximizar puntaje, 2 = minimizar energía con el puntaje fijo; `objective` y `bound` están en puntos (fase 1) o joules (fase 2); `best_energy_j` está vacía en la fase 1. |
| `trace_dp.csv` | `iter`, `best_prize`, `best_energy_j`, `masks_done`, `states`, `closable`, `k`, `states_k`, `closable_k`, `best_prize_k` | Unas 100 filas de progreso (`masks_done`, `states`, `closable`) y, al final, una fila por tamaño de conjunto k = 1..n (`k`, `states_k`, `closable_k`, `best_prize_k`); las columnas que no aplican quedan vacías. |

Detalles que conviene saber para no malinterpretar las trazas:

- **SA se adelgaza**: guarda la fila 0, una de cada 20 y la última (`trace_every = 20`); los
  demás algoritmos guardan todas las filas.
- **`best_energy_j` de la traza** es caminar + servicio, **sin energía de espera**; la energía
  de `Solution` / `runs.csv` sí incluye las esperas. Como estas instancias no tienen ventanas
  de horario, no hay esperas y ambas coinciden.
- **`Solution.evaluations` incluye las verificaciones finales**, así que `evaluations` de
  `runs.csv` puede ser algo mayor que lo visible en la traza.
- **SA y GA pulen después de su última fila de traza**: el puntaje final de `runs.csv` puede
  superar el último `best_prize` de la traza. Por eso las curvas de convergencia terminan con
  el punto (`runtime_s`, `prize`) de `runs.csv`.
- **ILS**: `shake_size` y `stale` se registran **después** de la actualización de esa vuelta.
- **DP**: en las filas de progreso `iter` es el número de máscaras alcanzadas (en las filas
  por k vale `2^n - 1`). `states` cuenta las etiquetas creadas **alguna vez**; `states_k`
  cuenta las etiquetas que **sobreviven**. `best_prize_k` **no** incluye el puntaje del
  destino cuando `end != start`.

### `analysis/summary.csv`

Una fila por (algoritmo, rango de tamaño) sobre las filas `status == ok`. Rangos de `n`:
`10-20`, `21-50`, `51-80`, `81-200`; con estas instancias cada rango es un tamaño (20, 50, 80
y 100). Columnas: `algorithm`, `size_bucket`, `runs`, `mean_gap_pct`,
`median_gap_pct`, `std_gap_pct` (desviación muestral), `optimal_share` (fracción de corridas
con `is_optimal`; recuerda la sección 4), `mean_runtime_s`, `median_runtime_s`,
`mean_evaluations`.

### `analysis/stats.csv`

Columnas `a`, `b`, `statistic`, `p_value`, `p_holm`, `n_instances`. La primera fila
(`a = friedman`) es la prueba de Friedman sobre **ils, sa, aco y ga** usando el gap medio de
cada instancia (promedio sobre semillas); solo entran instancias donde los cuatro tienen
datos. Las seis filas siguientes son pruebas de Wilcoxon de rangos con signo para cada par,
con `p_holm` corregido por Holm (paso descendente, acotado a 1). Los métodos exactos quedan
fuera porque su gap es 0 por construcción cuando son la referencia.

## 6. Cómo leer cada figura

Las figuras se guardan en `analysis/` y sus textos están en español. Cada algoritmo tiene un
color fijo en todas.

| Figura | Qué muestra | Cómo leerla |
|---|---|---|
| `fig1_convergence.png` | Una instancia por tamaño (20, 50, 80, 100). Eje x: tiempo en escala log; eje y: mejor puntaje hasta ese momento como % de la referencia. Línea = mediana entre semillas, sombra = rango intercuartil, punto = fin de la corrida, línea punteada = referencia. | Quien sube antes y llega a 100 % converge mejor. Una curva que se queda plana abajo de 100 % está atorada en un óptimo local. Las de DP y CP-SAT suben de golpe porque solo reportan soluciones completas. |
| `fig2_quality_vs_time.png` | Un punto por (algoritmo, tamaño): gap medio contra tiempo medio. La forma del marcador indica el tamaño. | Abajo a la izquierda es mejor: poco gap en poco tiempo. Sirve para ver el compromiso calidad-tiempo de cada método. |
| `fig3_scalability.png` | Tiempo de cómputo (mediana) contra `n` para cada algoritmo, en escala log. | Muestra cómo crece el costo con el tamaño. Los exactos se cortan en su límite (DP 20, CP-SAT 60 nodos); GA y SA se aplanan en su límite de tiempo o de pasos. |
| `fig4_gap_boxplots.png` | Una caja por algoritmo y un panel por tamaño, con la distribución del gap de cada corrida. | La mediana y la altura de la caja dicen qué tan bueno y qué tan estable es cada método. Con pocas corridas (ILS tiene 4 por tamaño) la caja es poco informativa. |
| `fig5_internal_dynamics.png` | Lo que pasa adentro de cada algoritmo (semilla 0): temperatura y tasa de aceptación de SA, feromona de ACO, diversidad y puntajes de la población del GA, tamaño del *shake* y puntajes del ILS, estados por tamaño k del DP y objetivo contra cota de CP-SAT. | Sirve para explicar el comportamiento: si la aceptación de SA cae a cero se volvió búsqueda local; si la feromona de ACO no se separa de su media, casi no aprende; si la diversidad del GA cae, la población convergió; si la cota y el objetivo de CP-SAT se juntan, probó el óptimo. |
| `fig6_routes.png` | La ruta que encontró cada algoritmo en una misma instancia (semilla 0), sobre el relieve. La estrella es el hábitat y las líneas son rectas entre estaciones (el camino real sigue el terreno). | Compara visualmente qué estaciones eligió cada método, con su puntaje y gap abajo. |
| `fig7_performance_profile.png` | Perfil de desempeño (Dolan-Moré): para cada umbral τ, la fracción de corridas con gap <= τ. | Arriba a la izquierda es mejor. El valor en τ = 0 es la fracción de corridas que llegan a la referencia. Una curva que tarda en llegar a 1 tiene corridas malas aunque su promedio se vea bien. Los exactos solo cuentan en las instancias donde corren. |

## 7. Resultados de la corrida final

Corrida final: `data/lab/runs/final` (16 instancias, `--dp-max 20 --cpsat-limit 60`,
semillas 0-2; 192 filas, 172 `ok` y 20 `skipped_size`, todas las rutas factibles; unos 8 min en
total). Fuentes: `runs.csv`, `instances.csv`, `analysis/summary.csv` y `analysis/stats.csv`.

**Referencias** (`instances.csv`): `dp_optimal` en las 4 de 20 nodos, `cpsat_optimal` en las
4 de 50 nodos (CP-SAT probó el óptimo en las cuatro, muy por debajo del límite de 60 s) y
`best_known` en las 8 de 80 y 100 nodos, donde no corre ningún método exacto. Entonces en la
mitad de las instancias el gap es contra un óptimo probado, y en la otra mitad contra el mejor
valor que alguien encontró.

**DP contra CP-SAT como verdad de referencia** (`summary.csv`, mediana de `runtime_s`):

| n | DP | CP-SAT |
|---|---|---|
| 20 | 0.93 s | 0.61 s |
| 50 | no corre (más de 20 nodos) | 3.79 s |

CP-SAT es más rápido que el DP aun en 20 nodos, y además llega hasta 60. Por eso es la mejor
verdad de referencia para este problema; el DP sirve para validar a CP-SAT en las chicas
(dan el mismo óptimo en las 4).

**Calidad de las metaheurísticas** (gap medio en % por tamaño, `summary.csv`; entre
paréntesis, fracción de corridas que llegan a la referencia):

| Algoritmo | n = 20 | n = 50 | n = 80 | n = 100 | Mediana de tiempo (todas) |
|---|---|---|---|---|---|
| GA | 0.00 (1.00) | 0.00 (1.00) | 0.43 (0.83) | 0.40 (0.75) | 5.13 s |
| ACO | 0.63 (0.75) | 0.00 (1.00) | 1.30 (0.42) | 0.48 (0.75) | 0.49 s |
| SA | 0.86 (0.75) | 2.50 (0.50) | 1.51 (0.50) | 0.81 (0.75) | 0.88 s |
| ILS | 8.20 (0.25) | 0.49 (0.75) | 0.66 (0.75) | 0.40 (0.75) | 3.84 s |

Sobre las 172 corridas `ok`, el gap medio es GA 0.21 %, ACO 0.60 %, SA 1.42 % e ILS 2.44 %;
llegan a la referencia el 90 % de las corridas del GA, el 73 % de ACO y el 62 % de SA e ILS.
El 2.44 % del ILS viene casi todo de una sola instancia de 20 nodos (`real-n20-1-180min`),
donde se queda en 34.26 puntos contra 40 (gap 14.3 %): como es determinista, repite ese
óptimo local siempre (`fig6_routes.png`).

**Pruebas estadísticas** (`stats.csv`, gap medio por instancia, 16 instancias):

- Friedman sobre ILS, SA, ACO y GA: estadístico 6.6, **p = 0.086**. Con α = 0.05 no se
  rechaza que los cuatro rindan igual.
- Wilcoxon por pares: el par con más diferencia es SA contra GA (p = 0.018 sin corregir), pero
  con la corrección de Holm queda en p = 0.107. Ningún par es significativo después de Holm.
- Rango medio por instancia (1 = mejor; calculado de `runs.csv`): GA 2.06, ACO 2.41, ILS
  2.66, SA 2.88.

**Qué se concluye**

1. **GA es el más preciso** (menor gap y más corridas en la referencia, y su curva domina el
   perfil de desempeño de `fig7`), pero también el más lento: en 80 y 100 nodos tarda unos
   9 s, cerca de su límite de 10 s.
2. **ACO es el mejor compromiso**: segundo en calidad y el más rápido (mediana 0.49 s).
3. **SA es rápido pero menos fino**: sus gaps son pequeños y parejos, sin llegar tan seguido a
   la referencia.
4. **ILS es muy bueno en las grandes, pero puede atorarse**: al no tener semilla, cuando cae en
   un óptimo local cae siempre (el caso de 20 nodos). En `fig5` su puntaje actual y el mejor
   no cambian en ninguna de las 160 iteraciones en la instancia de 100 nodos: la perturbación
   no lo saca de su primera solución.
5. **Con 16 instancias las diferencias no son estadísticamente significativas** (Friedman p =
   0.086): las tendencias de arriba son consistentes, pero hacen falta más instancias para
   afirmarlas con α = 0.05.
6. **La restricción que manda es el tiempo, no la energía**: la duración media de las rutas
   llena el 97-98 % del límite (7006 s de 7200 en `120min`, 10555 s de 10800 en `180min`),
   mientras que la energía usada es en promedio el 55 % del presupuesto de 900 Wh en `120min`
   y el 82 % en `180min` (`duration_s` y `budget_used_pct` en `runs.csv`). Pasar de 120 a 180 min sube el puntaje de referencia
   cerca de 50 % (por ejemplo de 40 a 61 en `real-n100-0`).

### 7.1 La misma corrida con ventanas de horario

Corrida aparte: `data/lab/runs/final-windows` (instancias en `data/lab/instances-windows/`,
prefijo `realtw-`). Son las mismas 16 instancias (estaciones, matrices, límites de 120 y 180 min,
semillas y algoritmos), más ventanas de horario con la regla de las sintéticas escalada a la
duración T de la EVA: cada estación abre tarde con probabilidad 0.5, en U(0, 0.5 T), y queda
abierta U(0.15, 0.5) T; las demás y el hábitat están siempre abiertas (`datasets.with_windows`,
semilla `9000 + 100 n + caso`). 172 corridas `ok`, todas factibles.

Para reproducirla:

```bash
PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.datasets --windows
PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.run --suite full --instances-dir data/lab/instances-windows --dp-max 20 --cpsat-limit 60 --out data/lab/runs/final-windows
PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.analyze data/lab/runs/final-windows --instances-dir data/lab/instances-windows
```

| Algoritmo | Gap medio sin ventanas | Gap medio con ventanas | Llega a la referencia (con ventanas) | Mediana de tiempo (con ventanas) |
|---|---|---|---|---|
| GA | 0.21 % | 0.30 % | 94 % | 7.72 s |
| ILS | 2.44 % | 1.11 % | 69 % | 3.90 s |
| SA | 1.42 % | 3.09 % | 52 % | 0.83 s |
| ACO | 0.60 % | 3.34 % | 29 % | 0.49 s |

Fuente: `runs.csv` de cada corrida (filas `ok`). Lo que cambia con las ventanas:

- **Las diferencias ahora sí son significativas**: Friedman p = 0.0002 (contra 0.086 sin
  ventanas). Con Holm, GA es mejor que ACO (p = 0.009) y que SA (p = 0.022)
  (`analysis/stats.csv`). Rango medio: GA 1.69, ILS 2.12, SA 2.94, ACO 3.25.
- **ACO es el que más sufre**: su gap pasa de 0.6 % a 3.3 % y solo el 29 % de sus corridas
  llega a la referencia. Una explicación probable (no la medimos): construye la ruta estación
  por estación, y con ventanas una mala elección temprana deja fuera estaciones que abren más
  tarde.
- **ILS mejora** (de 2.44 % a 1.11 %): con ventanas llega al óptimo en `realtw-n20-1-180min`
  (36 de 36), la instancia donde sin ventanas se atoraba, aunque en 100 nodos queda en 2.3 %.
- **CP-SAT se vuelve más lento**: mediana de 18 s en 50 nodos (3.8 s sin ventanas), y en
  `realtw-n50-1-180min` no prueba el óptimo en 60 s (la referencia queda `best_known` = 46 con
  cota 50.2). La DP no cambia (0.77 s en 20 nodos).
- **El tiempo sigue limitando más que la energía**: 55 % y 84 % del presupuesto usado en 120 y
  180 min, con la duración casi llena.

## 8. Limitaciones

- **DP hasta 20 nodos.** Aquí cabe gracias al límite de duración; sin él, 20 nodos usan
  mucha memoria (`2^n` estados).
- **CP-SAT hasta 60 nodos y 60 s por instancia en la corrida final.** Si no prueba el óptimo en ese tiempo, la
  referencia pasa a `best_known`.
- **`best_known` no es un óptimo probado**: es el mejor valor que vio algún algoritmo. Los
  gaps sobre instancias con `best_known` son optimistas, porque la referencia podría estar por
  debajo del óptimo real (la `upper_bound`, cuando existe, acota cuánto).
- **Tiempos de una sola máquina**: los segundos de `runtime_s` dependen del equipo, de la
  carga y de que CP-SAT use 8 hilos. Sirven para comparar entre algoritmos dentro de esta
  corrida, no como cifras absolutas.
- **Parámetros por defecto sin afinar**: ILS, SA, ACO y GA corren con los parámetros y el
  límite de 10 s que traen por defecto; con otros parámetros el orden entre ellos podría
  cambiar.
- **Pocas instancias**: 2 casos por tamaño y 2 escenarios (16 instancias) y 3 semillas por
  metaheurística aleatoria. Alcanza para comparar tendencias, pero cada rango de tamaño tiene
  solo 4 instancias, y las pruebas estadísticas tienen poca potencia.
- **Un solo terreno**: todas las instancias salen de la misma zona de 2 x 2 km y del mismo
  pool de estaciones.
