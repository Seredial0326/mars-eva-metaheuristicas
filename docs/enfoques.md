# Enfoques E1–E12: qué es cada uno

Resumen del plan original del equipo (`docs/plan_enfoques_E1-E12.pdf`, 12 páginas). Los issues y la guía de trabajo nombran las piezas por su código (E4, E7, E12…); aquí está qué significa cada código. Para horas, entregas y cortes manda `docs/guia_trabajo_equipo.md`; si este resumen y la guía no coinciden, vale la guía.

**Idea del proyecto:** un planificador de EVA para el boxwork del cráter Gale que calibra su costo con el recorrido real de Curiosity y planifica de forma exacta para el humano. La diferencia frente a otros equipos se mide con números: costo calibrado, garantía de regreso exacta en cada punto y validación con datos reales.

**Por qué el boxwork:** son crestas de 1 a 2 m con huecos arenosos entre ellas. Curiosity encontró arcillas en las crestas y carbonatos en los huecos, y la arena de los huecos hace deslizar las ruedas. Los objetivos científicos coinciden con los peligros.

## Tabla rápida

| Código | Qué es | Dueño | Issue | Prioridad |
|---|---|---|---|---|
| E1 | Costo del terreno aprendido de la ruta de Curiosity (MaxEnt IRL) | Juan | #5 | MVP |
| E2 | Trayectoria de Curiosity llevada a la malla y análisis de movilidad | Juan | #4 | MVP (versión mínima) |
| E3 | Costo metabólico y de O2 del astronauta con gravedad de Marte | Sebas | #6 | MVP |
| E4 | Walkback exacto: R(v) y ruta con restricción de regreso | Aaron | #7 | MVP |
| E5 | Orienteering: qué estaciones visitar y en qué orden | Diana | #9 | MVP |
| E6 | Metaheurísticas comparadas contra el óptimo exacto | Diana | #14 | Segunda |
| E7 | Robustez ante el error del DEM (Monte Carlo, CVaR) | Aaron | #15 | Segunda, solo si E9 se corta |
| E8 | Crestas y huecos del boxwork con top-hat y U-Net | JB | #11 | Segunda |
| E9 | Rocas con BoulderNet, destilada a una CNN ligera | Aaron | #12 | Segunda |
| E10 | Validación del mapa orbital contra la vista del rover | JB | sin issue | Solo versión reducida si todo lo demás está listo |
| E11 | Línea de vista, sombras y EVA en pareja | sin dueño | sin issue | No planeado |
| E12 | Dosis de radiación en la línea de tiempo y alerta SEP | Juan | #13 | Segunda |

## MVP (cierra en la hora 24)

### E1 · Costo aprendido de Curiosity
- **Pregunta:** ¿qué combinación de pendiente, rugosidad, curvatura y tipo de terreno explica las rutas que eligieron los conductores de Curiosity?
- **Qué hace:** ajusta los pesos de un costo lineal por celda con MaxEnt IRL (soft value iteration; gradiente = conteos esperados de features − conteos de la demostración). Baseline barato: regresión logística "celda visitada o no". Para el humano se cambia el término de pendiente por el metabólico (E3) y se conserva lo aprendido de rugosidad y arena.
- **Datos:** features del DEM de 1 m y la trayectoria de PLACES.
- **Validación:** por segmentos de la ruta (leave-one-segment-out); distancia de Hausdorff, porcentaje de la ruta real dentro de un buffer de 5 y 10 m, log-verosimilitud.
- **Riesgo:** las rutas del rover también reflejan decisiones científicas y de comunicación, no solo de terreno. No sobreafirmar.

### E2 · Movilidad de Curiosity
- **Qué hace:** cruza las posiciones del rover con el DEM: celdas visitadas con sus features, pendientes que el rover atravesó frente a las disponibles, avance por sol, rodeos.
- **Versión mínima del MVP:** proyectar la trayectoria a la malla (`trayectoria.geojson` y lista de celdas) y la tabla celda × feature que alimenta E1.

### E3 · Costo metabólico con gravedad
- **Pregunta:** ¿cuánto le cuesta cada paso a un astronauta con traje a 0,38 g?
- **Qué hace:** costo por arista con Pandolf más la corrección de bajada de Santee, en la forma del modelo CSRM de NASA, con un factor de gravedad G que multiplica los términos de peso. Velocidad con Tobler o con la regresión de Apolo. Se integra en Wh y de ahí sale el O2.
- **Validación:** reproducir el caso de Apolo 14 (Carr, Newman y Hodges 2003) y análisis de sensibilidad a G, al coeficiente de terreno η y a la masa del traje.
- **Supuestos que hay que declarar:** G = 0,38 es inferencia nuestra (el CSRM solo propone 0,17 para la Luna, sin validar); no hay η para regolito marciano; el término de bajada aparece distinto en dos fuentes (`+25V²` y `+(25 − V²)`).

### E4 · Walkback exacto
- **Pregunta:** ¿cuál es la mejor ruta tal que, en cada punto, lo consumido más el costo mínimo de volver al hábitat quepa en el presupuesto con margen?
- **Qué hace:** Dijkstra inverso desde el hábitat sobre el grafo metabólico → R(v), el costo mínimo de regreso desde cada celda. Después, label-setting con la restricción `consumo(v) + R(v) ≤ (1 − margen)·B` en cada etiqueta.
- **Qué se muestra:** R(v) como isocronas de "punto de no retorno".
- **Validación:** contra los baselines (A* con umbral de pendiente, radio fijo, O2 lineal): contar rutas que el radio fijo da por seguras y que violan el presupuesto exacto.

### E5 · Orienteering de estaciones
- **Pregunta:** dadas N estaciones con valor científico, ¿qué subconjunto y en qué orden maximiza la ciencia sin violar energía, duración ni walkback?
- **Qué hace:** matriz de costos entre estaciones (un Dijkstra desde cada una) y DP de máscara de bits, exacta hasta N ≈ 18–20, con ventanas de tiempo y tiempo de servicio. Para N mayor, ILP con OR-Tools.
- **Valor de cada estación:** crestas (arcillas) frente a huecos (carbonatos), diversidad de unidades.
- **Validación:** óptimo comprobado contra fuerza bruta en N pequeño; tiempo de cómputo frente a N.

## Segunda prioridad (después de la hora 24)

### E6 · Metaheurísticas contra el exacto
ILS y otra metaheurística (SA, GA o ACO) comparadas con la DP: gap contra el óptimo en N ≤ 18 y tiempo. Sirve para el modo de muchas estaciones; con N ≈ 15 el exacto gana y no debe presentarse una metaheurística como solución.

### E7 · Robustez ante el error del DEM
Genera 100–200 versiones del DEM con un campo gaussiano correlacionado, calcula la probabilidad de superar el umbral de pendiente por celda y planifica con restricción probabilística o minimizando el CVaR. Resultado: tasa de violación de la ruta nominal frente a la robusta y el costo extra de la robustez. La σ del error es un supuesto y hay que declararlo.

### E8 · Crestas y huecos del boxwork
Etiquetas débiles con top-hat morfológico sobre el DEM (cresta, hueco, ignorar) y una U-Net ligera entrenada sobre la ortofoto de 25 cm. Sirve para dos cosas: propone estaciones científicas para E5 y da un peligro de arena (`arena.tif`) para el costo. Se valida con parches etiquetados a mano (IoU, F1) contra el propio top-hat.

### E9 · Rocas con BoulderNet
Inferencia con BoulderNet (Mask R-CNN, Detectron2) sobre la ortofoto y destilación a una CNN ligera que da densidad de rocas por celda (`rocas.tif`). Es una densidad de riesgo, no una garantía de que no hay rocas: por debajo de ~1 m la detección a 25 cm/píxel no es fiable.

### E12 · Radiación y replanificación
La radiación cósmica de fondo (≈0,64 mSv/día según RAD) casi no depende de la ruta, así que un mapa de radiación por píxel sería decorativo. Lo correcto es un presupuesto de dosis en la línea de tiempo de la EVA y un escenario de alerta por evento solar (SEP) que dispara la replanificación hacia el hábitat.

## No planeados

- **E10 · Orbital contra vista del rover:** segmentar imágenes Navcam del boxwork y comparar el porcentaje de arena y roca con la predicción orbital de E8/E9. Solo en versión reducida (10–20 imágenes) si todo lo demás está listo.
- **E11 · Línea de vista, sombras y pareja:** viewshed desde el hábitat, sombras por hora y team orienteering para dos astronautas. Es el menos prioritario.

## Correcciones al plan original

El PDF se escribió antes de descargar los datos. Esto se comprobó después (detalle en `data/README.md`, sección 6):

1. **Soles del boxwork.** El plan dice ≈4.450–4.850, tomado de una leyenda de NASA con un error de fecha. Por las fechas de REMS, el rango es ≈4.541–4.848. Dentro de la caja del recorte acordada hay 5.257 poses de PLACES (soles 4.369–4.868, sites 111–121).
2. **PLACES sí cubre el boxwork.** El plan temía que el archivo fuera de 2021. La versión actual llega al sol 4.868 y trae poses con sol y orientación: `data/03_curiosity/places_pds/`.
3. **Pendiente.** En una prueba sobre un recorte del boxwork (1,4 × 2 km, no la caja final), a 1–2 m de base el 45 % de las celdas superaba 15° y el 31 % superaba 20°, mientras que el rover registró una inclinación mediana de 8° y máxima de 17,5°. Hay que fijar a qué escala se mide la pendiente antes de aplicar un límite.
4. **AI4Mars.** La versión descargada (v0.1) solo trae Curiosity y llega al sol 2.579: no incluye el boxwork.
5. **BoulderNet.** El dataset tiene unos 50 parches de Marte y ninguno es de Gale.
6. **Estaciones.** No existe una capa pública con los sitios de taladro de Curiosity; hay que cruzar el registro del taladro con PLACES o marcarlos a mano.
7. **Tamaños reales.** DEM 3,87 GB; ortofoto gris 24,4 GB; ortofoto en color 1,03 GB.
