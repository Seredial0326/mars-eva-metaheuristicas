# Guion del video: Mars EVA Planner y laboratorio de metaheurísticas

Nov 25, 2026 · @Sebastián Díaz Álvarez

Video de 3 minutos en 7 escenas: el problema, el alcance, la aplicación en vivo, el código, los resultados, la comparación con ventanas de horario y el cierre. Cada escena dice qué se escucha (voz) y qué se ve (pantalla); la voz suma unas 430 palabras, unos 3 minutos a ritmo normal.

## Escenas de un vistazo

| Tiempo | Escena | Qué se ve |
| --- | --- | --- |
| 0:00–0:20 | 1 · El problema | El mapa de la app: el área de 2 × 2 km en el cráter Gale y el hábitat |
| 0:20–0:45 | 2 · Alcance | Una lámina con los 6 algoritmos y los números del dataset |
| 0:45–1:25 | 3 · La aplicación en vivo | Cargar un dataset, planear con DP, luego con ACO sobre 120 estaciones |
| 1:25–2:00 | 4 · El código | VS Code en las líneas clave de SA, ACO, GA e ILS, y un CSV de trazas |
| 2:00–2:30 | 5 · Resultados sin ventanas | Gráficas de convergencia, perfil de desempeño, tabla de gaps y rutas |
| 2:30–2:50 | 6 · Con ventanas de horario | La gráfica comparativa: cada algoritmo sin y con ventanas |
| 2:50–3:00 | 7 · Cierre | La página del laboratorio resolviendo en vivo, y de vuelta al mapa |

## Escena 1 · El problema (0:00–0:20)

**Pantalla:** la aplicación en `http://127.0.0.1:8000/`, vista completa del área (botón *Whole area*). Zoom lento hacia el hábitat en el centro.

**Voz:** “Un astronauta en Marte sale del hábitat con 900 vatios-hora de energía y una caminata de dos o tres horas. A su alrededor hay decenas de sitios de interés científico, cada uno con un puntaje. ¿Cuáles visita y en qué orden, para obtener la mayor ciencia sin quedarse sin tiempo ni energía? Es el *Orienteering Problem*, un problema NP-difícil.”

## Escena 2 · Alcance (0:20–0:45)

**Pantalla:** una lámina simple, en dos columnas:

- *Exactos:* Programación dinámica (DP) · CP-SAT (Google OR-Tools)
- *Metaheurísticas:* ILS · Recocido simulado (SA) · Colonia de hormigas (ACO) · Algoritmo genético (GA)
- Abajo: *120 estaciones · 16 instancias · 20, 50, 80 y 100 nodos · límites de 120 y 180 min · 3 semillas*

**Voz:** “Comparamos seis algoritmos sobre el mismo problema. Dos exactos: programación dinámica y CP-SAT, de Google. Y cuatro metaheurísticas: búsqueda local iterada, recocido simulado, colonia de hormigas y algoritmo genético. Trabajamos sobre el terreno real: un conjunto de 120 estaciones, entre las marcadas a mano y otras generadas, del que salen 16 instancias de 20 a 100 nodos, con límites de 120 y 180 minutos.”

## Escena 3 · La aplicación en vivo (0:45–1:25)

**Pantalla**, en este orden:

1. Pestaña **Stations** → selector *20 nodes · case 0* → **Load lab dataset**. Aparecen los 19 puntos sobre el mapa.
2. Pestaña **Plan** → *More options* → *Route solver*: **Dynamic programming** → *EVA length* 120 → **Plan the walk**. La ruta cyan sigue el terreno; el panel dice 5 de 19 estaciones y 116 de 120 min.
3. De vuelta en **Stations**: *Full pool (120 stations)* → **Load lab dataset**. Se llena el mapa.
4. **Plan**: solver **Ant colony (ACO)**, *EVA length* 180 → **Plan the walk** (unos 4 s): 14 de 120 estaciones.
5. Mismo dataset con **CP-SAT** → aparece el aviso *“supports up to 59 plus the habitat”*.

**Voz:** “En la aplicación podemos cargar cualquier instancia del experimento y elegir el algoritmo. Con 20 nodos, la programación dinámica encuentra la ruta óptima: cinco estaciones en 116 de los 120 minutos, y el camino sigue el terreno real, evitando las pendientes. Con las 120 estaciones, los exactos ya no alcanzan: CP-SAT llega hasta 60 nodos. Pero la colonia de hormigas resuelve las 120 en unos cuatro segundos.”

## Escena 4 · El código de los algoritmos (1:25–2:00)

**Pantalla:** VS Code con fuente grande, unos 6 s por archivo:

| Archivo | Líneas | Qué resaltar |
| --- | --- | --- |
| `src/orienteering/solvers/sa.py` | 64 | La aceptación: `rng.random() < math.exp(delta / temp)` |
| `src/orienteering/solvers/aco.py` | 107–111 | Elegir la mejor con probabilidad `Q0`, y la actualización local de la feromona |
| `src/orienteering/solvers/ga.py` | 92–101 y 67 | El cruce por orden y la reparación del hijo |
| `src/orienteering/solvers/ils.py` | 34–44 | El *shake*: tamaño y posición de la perturbación |
| `data/lab/runs/final/traces/trace_ga.csv` | primeras filas | Una fila por generación: mejor, media, peor y diversidad |

**Voz:** “Cada algoritmo vive en su propio archivo. El recocido simulado acepta a veces una ruta peor, con una probabilidad que baja con la temperatura. La colonia de hormigas elige la siguiente estación por la feromona y por el puntaje entre la energía. El genético cruza rutas y repara las que se pasan del presupuesto. Y a todos les agregamos un registro por iteración, que guarda en CSV cómo avanza su búsqueda.”

## Escena 5 · Resultados sin ventanas (2:00–2:30)

**Pantalla**, unos 6 s cada una (todas en `data/lab/runs/final/analysis/`, o en `/lab.html` → corrida *final*):

1. `fig1_convergence.png`: las curvas suben hasta la referencia.
2. La tabla de gaps de la sección 7 de `docs/lab/README.md`.
3. `fig7_performance_profile.png`: la curva rosa del GA arriba a la izquierda.
4. `fig6_routes.png`: la misma instancia resuelta por los seis; el ILS se queda en 34 de 40 puntos.
5. `fig5_internal_dynamics.png`, unos segundos, como cierre visual.

**Voz:** “Medimos todo contra una verdad de referencia: el óptimo de la programación dinámica o de CP-SAT, que resultó más rápido. Sin ventanas de horario, el genético es el más preciso: 0.21 % de brecha y 90 % de corridas en el óptimo. La colonia de hormigas es el mejor equilibrio: 0.6 % en medio segundo. Pero la prueba de Friedman da p = 0.086: con 16 instancias, la diferencia todavía no es significativa.”

## Escena 6 · Con ventanas de horario (2:30–2:50)

**Pantalla:** `data/lab/comparacion-ventanas.png` a pantalla completa (círculo hueco = sin ventanas, lleno = con ventanas). Con el cursor o un zoom suave, señalar primero la línea larga de **ACO** (73 % → 29 %) y luego la de **GA**, que casi no se mueve. Si se prefiere la figura del análisis: `data/lab/runs/final-windows/analysis/fig7_performance_profile.png`.

**Voz:** “Luego repetimos todo con ventanas de horario en las estaciones. Ahí las diferencias sí son significativas: p = 0.0002. El genético casi no cambia y queda primero; la colonia de hormigas cae al último lugar, de 73 a 29 % de corridas en el óptimo. El mejor algoritmo depende de las restricciones del problema.”

## Escena 7 · Cierre (2:50–3:00)

**Pantalla:** `/lab.html` → *Ejecutar* con `real-n50-0-120min` y los seis algoritmos, unos 5 s mientras se dibuja la convergencia en vivo. Últimos 5 s: de vuelta al mapa con la ruta de la escena 3.

**Voz:** “En resumen: los exactos garantizan el óptimo solo en problemas chicos; las metaheurísticas escalan a cien estaciones. Y en Marte, lo que limita la caminata es el tiempo, no la energía.”

Si la voz se pasa de los 10 s, quita “y en Marte…”: ya lo dijo la escena 1.

## Antes de grabar

- [ ] Servidor corriendo (`.venv/Scripts/python.exe -m uvicorn api.main:app --port 8000`) y **un plan hecho antes de grabar**: el primero tarda unos 30 s mientras se arma el grafo del terreno.
- [ ] Pestañas abiertas: la app (`/`), `/lab.html` con la corrida *final*, las figuras fig1, fig5, fig6 y fig7, la gráfica data/lab/comparacion-ventanas.png, y la sección 7 de `docs/lab/README.md`.
- [ ] VS Code con `sa.py`, `aco.py`, `ga.py` e `ils.py` abiertos en las líneas de la escena 4, fuente a 18 pt o más.
- [ ] Pantalla a 1920 × 1080, notificaciones ocultas, zoom del navegador al 100 %.
- [ ] Voz grabada aparte y montada sobre las tomas: así cada escena se ajusta a su tiempo sin repetir la toma.
