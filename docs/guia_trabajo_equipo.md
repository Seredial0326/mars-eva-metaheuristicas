# Guía de trabajo del equipo · hora 0 a la entrega

Nov 14, 2026 · @Javier

## Cómo usar esta guía

Cada integrante tiene su sección con lo que hace de la hora 0 a la 48, qué archivo necesita, de quién lo recibe y a quién lo entrega. El MVP (E1 + E2 mínimo + E3 + E4 + E5) se cierra en la hora 24, y el código se congela en la hora 40. Las horas cuentan desde el arranque oficial del equipo, no desde la hora del reloj.

**Reglas para todos**

- **Un dueño por pieza.** Si tu pieza depende de otra que aún no llega, trabaja con un archivo provisional del mismo formato y cámbialo cuando llegue el real.
- **Los contratos no se cambian sin avisar.** Cualquier cambio de formato se publica primero en el issue de contratos y lo confirma quien consume ese archivo.
- **Hora límite = hora límite.** Si una pieza riesgosa no llega a su hora de corte, se aplica su plan B y la persona refuerza el MVP o la demo.
- **Cada bloque termina con un commit** y un comentario en tu issue: qué quedó, qué falta y qué archivo dejaste.
- **Agentes (Claude Code y Codex) solo en terminal normal**, nunca de administrador, y en modo de aprobación. Igual con `pip` y `npm`.
- **Los datos no van al repo.** `data\raw` y `data\base` están en `.gitignore`; los archivos se comparten por USB o por la carpeta compartida del equipo.

**Contratos compartidos (ya fijados)**

| Contrato | Valor | Dónde vive |
| --- | --- | --- |
| CRS | Equirectangular de Marte, esfera R = 3.396.190 m (el del DEM) | `base\crs.wkt` |
| Caja del recorte (2 × 2 km) | XMIN 8142537.492786024 · YMIN −285463.075189438 · XMAX 8144537.492786024 · YMAX −283463.075189438 | `base\grid.json` e issue de contratos |
| Celda | 1 m para todas las capas de análisis; 0,25 m solo para ortofotos y U-Net | `base\grid.json` |
| Nodata | `NaN` en float32 | `base\grid.json` |
| Formatos | Rasters GeoTIFF float32 sobre la malla base; puntos y rutas en GeoJSON con el CRS del DEM | Plan de acción, sección Contratos |

**GitHub:** un issue por pieza (E1, E2, …, Malla base), un issue de contratos y etiquetas por área. Los agentes leen y comentan esos issues, así que lo que no está en un issue no existe para el resto del equipo.

## Línea de tiempo general

Todo arranca con la malla base de JB (horas 0–4); el MVP se integra entre las horas 20 y 24, y el código se congela en la hora 40.

&#91;embedded content: línea de tiempo del equipo · 5 personas, horas 0–48\]

Los hitos son: hora 4, mapa con ortofoto y pendiente; hora 12, R(v) y ruta con walkback; hora 24, MVP con números contra los 3 baselines; hora 34, una capa de segunda prioridad integrada; hora 40, código congelado. Los huecos en cada columna son las horas de integración y de demo, que hacen todos juntos.

## Diana · E5 orienteering y E6

Diana entrega qué estaciones visitar y en qué orden (E5). En la hora 24 lo debe tener sobre el costo real; después le agrega las estaciones de E8 y, si sobra tiempo, el benchmark E6.

| Horas | Tarea | Necesita (de quién) | Entrega (a quién) | Lista cuando |
| --- | --- | --- | --- | --- |
| 0–4 | DP de orienteering con máscara de bits sobre 10–12 estaciones sintéticas; lector del GeoJSON de estaciones del contrato | Nada (datos sintéticos) | — | La DP da el óptimo del toy problem y lee un GeoJSON de prueba |
| 4–12 | Matriz de costos entre estaciones (un Dijkstra desde cada estación sobre el grafo); ventanas de tiempo en la DP | Grafo (Aaron, h4); costo E3 (Sebas, h8); estaciones v0 de E8 (JB, h8) | — | La matriz se calcula sobre el costo E3 real |
| 12–18 | E5 completo sobre el costo real con las estaciones manuales | Estaciones manuales con valor (Sebas, h14) | Ruta de E5 (Aaron, para unirla con el walkback) | Ruta óptima en GeoJSON en menos de 1 min |
| 18 | **Corte de E5:** si la DP no cabe en tiempo, bajar a N = 15 o pasar a ILP con OR-Tools | — | — | — |
| 18–20 | Apoyo a Juan en soft value iteration (E1) | — | — | — |
| 20–24 | Integración del MVP (todos) | Costo E1 + E3 | Ruta con estaciones óptimas (Sebas) | Hito 24 cumplido |
| 24–34 | Meter las estaciones de E8 en E5 (v0 primero, v1 cuando llegue); E6 solo si el núcleo está estable | Estaciones v1 de E8 (JB, h32) | Ruta con estaciones E8 (Sebas) | Hito 34: E8 influye en la elección de estaciones |
| 34–40 | Resultados de E6: DP contra metaheurísticas (calidad y tiempo) | — | Tabla de E6 (Juan, para la tabla final) | Tabla con 3 métodos |
| 40–46 | Video, demo, README y ensayo (todos) | — | — | — |
| 46–48 | Margen para el envío | — | — | — |

**Apoya a:** Juan en soft value iteration (E1). **Plan B:** E6 no se empieza si el MVP no da números a la hora 24 (corte a la hora 30).

## Aaron · Grafo, E4 walkback, baselines y E9

Aaron entrega el grafo sobre la malla, la capa R(v) (energía mínima para volver al hábitat desde cada celda) y la ruta con walkback de E4. También hace los tres baselines contra los que se mide el MVP. Después de la hora 24 toma E9, o E7 si E9 se corta.

| Horas | Tarea | Necesita (de quién) | Entrega (a quién) | Lista cuando |
| --- | --- | --- | --- | --- |
| 0–2 | Grafo de 8 vecinos sobre `prueba_dem.tif` con costo provisional de pendiente | Recorte de prueba (JB, ya existe) | — | Dijkstra corre de punta a punta del recorte |
| 2–4 | Cambiar al `dem_1m.tif` y `slope_deg.tif` oficiales | `dem_1m.tif` (JB, h2); `slope_deg.tif` (JB, h3) | Grafo (Diana, h4) | Mismas dimensiones que `grid.json` |
| 4–12 | Dijkstra inverso desde el hábitat → R(v); label-setting con walkback | Costo E3 (Sebas, h8) | `rv.tif` y ruta E4 (Sebas, h12) | Hito 12: capa R(v) y ruta con walkback sobre el costo E3 |
| 12–20 | Baselines: A\* con umbral de pendiente, radio fijo y O2 lineal | — | Rutas baseline (Juan, para la tabla) | Tres rutas en GeoJSON con energía y R(v) por punto |
| 20–24 | Integración del MVP (todos) | Costo E1 + E3 (Sebas y Juan) | Ruta final con walkback (Sebas) | Hito 24 cumplido |
| 24–28 | E9: correr BoulderNet sobre el recorte gris | `orto_gris_025.tif` (JB, h2) | — | Detecciones de rocas sobre el recorte |
| 28 | **Corte de E9:** si BoulderNet no corre, pasar a E7 | — | — | — |
| 28–34 | Destilar BoulderNet a una CNN ligera → densidad de rocas por celda | Detecciones | `rocas.tif` (Juan y Sebas) | Raster float32 sobre la malla base |
| 34–40 | E7 (ruta con DEM perturbado) solo si E9 se cortó; si no, apoyo a la tabla de resultados | — | Resultados de E7 (Juan) | — |
| 40–46 | Video, demo, README y ensayo (todos) | — | — | — |
| 46–48 | Margen para el envío | — | — | — |

**Apoya a:** JB en la U-Net (horas 8–12, si el grafo ya está estable). **Plan B:** sin BoulderNet a la hora 28, E9 se corta, Aaron toma E7 y JB sigue con E8.

## Juan · E2 mínimo, E1 MaxEnt IRL y E12

Juan convierte las rutas reales de Curiosity en celdas de la malla (E2) y aprende de ellas cuánto "cuesta" cada tipo de terreno (E1). Esos pesos, combinados con E3, forman el costo humano. Después de la hora 24 cierra las métricas, calcula la dosis de radiación (E12) y arma la tabla de resultados.

| Horas | Tarea | Necesita (de quién) | Entrega (a quién) | Lista cuando |
| --- | --- | --- | --- | --- |
| 0–4 | Proyectar la trayectoria de PLACES a la malla, junto con JB: sistema de coordenadas, conversión al CRS del DEM, fila y columna, revisión en QGIS | `localized_interp.csv` (ya descargado); `dem_1m.tif` (JB, h2) | `trayectoria.geojson` y lista de celdas (Sebas) | Los waypoints caen sobre el terreno por donde pasó el rover |
| 4–12 | E2 mínimo: celdas visitadas con sus features; baseline logístico (visitada o no) | Features (JB, h4) | Tabla celda × feature | El baseline logístico da un AUC |
| 12–20 | MaxEnt IRL lineal; validación por segmentos de la trayectoria | Grafo (Aaron); apoyo de Diana en soft value iteration | Pesos de E1 (Sebas, para combinar con E3) | Los pesos explican mejor la ruta real que el baseline |
| 20 | **Corte de E1:** si MaxEnt no converge, costo E3 con pesos fijados por sensibilidad | — | — | — |
| 20–24 | Integración del MVP (todos) | Rutas de Aaron y Diana | Números del MVP contra los 3 baselines | Hito 24 cumplido |
| 24–34 | Métricas finales de E1; E12 dosis acumulada en la línea de tiempo; sensibilidad a G y η | `arena.tif` (JB, h30); `rocas.tif` (Aaron, h34) | Dosis por punto de la ruta (Sebas) | Curva de dosis sobre la ruta |
| 30 | **Corte de E12:** sin cifras claras, solo dosis acumulada, sin alerta SEP | — | — | — |
| 34–40 | Tabla de resultados del equipo (MVP, baselines, E6, E7, E8, E9) | Resultados de cada área | Tabla final (todos, para la demo) | Tabla con números, sin celdas vacías |
| 40–46 | Video, demo, README y ensayo (todos) | — | — | — |
| 46–48 | Margen para el envío | — | — | — |

**Apoya a:** Sebas en la validación de E3. **Ya resuelto:** PLACES cubre el boxwork hasta el sol 4868, con 4024 posiciones (sites 113–121).

## Sebas · E3 metabólico, API, HUD y estaciones

Sebas entrega el costo E3: la energía y el oxígeno que gasta el astronauta por celda con la gravedad de Marte. Es la pieza que no puede retrasarse, porque Aaron y Diana planifican con ella. También construye la API y el HUD que ve el jurado, y congela el código en la hora 40.

| Horas | Tarea | Necesita (de quién) | Entrega (a quién) | Lista cuando |
| --- | --- | --- | --- | --- |
| 0–4 | Implementar E3 (Pandolf/Santee con G de Marte) como función costo(celda, vecino) | `slope_deg.tif` (JB, h3) | — | Reproduce el caso Apolo del toy problem |
| 4–8 | Raster de costo E3 sobre la malla | `dem_1m.tif`, features (JB) | `costo_e3.tif` o la función (Aaron y Diana, **h8**) | Wh por celda, float32, mismas dimensiones que `grid.json` |
| 8–12 | Esqueleto de la API (FastAPI) y del HUD sobre el mapa de JB | Teselas y mapa (JB, h4) | — | El HUD muestra la ortofoto y la pendiente desde la API |
| 12–20 | Capas R(v) e isocrona en el HUD; estaciones manuales con valor científico | `rv.tif` (Aaron, h12) | `estaciones_manual.geojson` (Diana, **h14**) | El HUD dibuja R(v) y la ruta E4 |
| 20–24 | Integración del MVP (todos): combinar E3 con los pesos de E1 | Pesos de E1 (Juan); rutas (Aaron, Diana) | Costo humano final (Aaron y Diana) | Hito 24 cumplido y visible en el HUD |
| 24–34 | Integrar capas de E8, E9 y E12; alerta SEP en el HUD | `arena.tif` (JB, h30); `rocas.tif` (Aaron, h34); dosis (Juan) | — | Hito 34: al menos una capa de segunda prioridad en el HUD |
| 34–40 | Pulir la demo y **congelar el código a la hora 40** | — | Rama de entrega | Desde la hora 40 solo se arreglan errores |
| 40–46 | Video, demo, README y ensayo (todos) | — | — | — |
| 46–48 | Margen para el envío | — | — | — |

**Apoya a:** Aaron a leer R(v) en el HUD; es el support de Grafos si Aaron o Diana se atoran.

## JB · Malla base, features, mapa y E8

JB entrega la malla base: el recorte alineado, los rasters y las features sobre las que trabajan todos. Por eso las horas 0–4 son las más críticas del equipo. Después entrena la U-Net de E8, que marca crestas y huecos, propone estaciones y da el peligro de arena. El detalle de cada paso está en el *Manual de JB*.

**Ya hecho (sábado 14, 7–9 h):** datos descargados; centro dentro del DEM y de la ortofoto con 0 % sin dato; detalle de HiRISE (0,416 m); caja alineada al DEM sin `-tap`; mismo CRS en los dos archivos (solo cambian los nombres).

| Horas | Tarea | Necesita (de quién) | Entrega (a quién) | Lista cuando |
| --- | --- | --- | --- | --- |
| 0–1 | Guardar `crs.wkt`; revisión visual en QGIS (sombreado contra ortofoto); publicar la caja en el issue de contratos | Datos en `data\raw` | Caja (todos) | Las crestas del sombreado caen sobre las de la foto |
| 1–2 | `dem_1m.tif`, `orto_color_025.tif`, `orto_gris_025.tif` (o canal rojo) y `grid.json` | Caja y `crs.wkt` | `dem_1m.tif` y `grid.json` (todos, **h2**); `orto_gris_025.tif` (Aaron) | Las 4 comprobaciones dan `True` |
| 2–3 | Features con margen de 64 m: pendiente, residuo, rugosidad, TPI | `dem_1m_margen.tif` | `slope_deg.tif` (Sebas y Aaron, **h3**) | Valores en rango y sin `NaN` en el borde |
| 3–4 | Capas de 8 bits, teselas, mapa con ortofoto y pendiente, mapa de calidad; anunciar en el issue | Features | Todas las features (Juan, **h4**); teselas (Sebas) | Hito 4: el mapa muestra la ortofoto y la pendiente |
| 2–4 | En paralelo, apoyo a Juan para proyectar la trayectoria | `dem_1m.tif` | — | Los waypoints caen sobre el terreno |
| 4–6 | Etiquetas débiles con top-hat blanco y negro (cresta, hueco, 255 = ignorar) | `dem_1m.tif` | `etiquetas_1m.tif` | Máscaras con sentido en QGIS |
| 6–8 | Llevar etiquetas a 0,25 m; 4 cuadrantes (3 de entrenamiento, 1 de validación); parches de 256 × 256 | Ortofoto y etiquetas | `estaciones_e8_v0.geojson` desde el top-hat (Diana, **h8**) | Parches listos y estaciones v0 en el CRS del DEM |
| 8–12 | Entrenar la U-Net (EfficientNet-B0, 1 canal, 3 clases, precisión mixta, lotes de 8) | Parches | Primer modelo | La pérdida baja en validación |
| 12–20 | Etiquetar a mano 50 parches del cuadrante de validación; IoU y F1 con tolerancia del top-hat contra la U-Net | Parches de validación | Tabla de métricas de E8 (Juan) | Tabla con los dos métodos |
| 20–24 | Integración del MVP (todos): revisar que todas las capas usan la malla base | — | — | Hito 24 cumplido |
| 24–28 | Predecir todo el recorte con ventanas solapadas | Modelo + ortofoto | Máscaras a 0,25 m | — |
| 28 | **Corte de E8:** si la U-Net no supera al top-hat, se usan las máscaras del top-hat | — | — | — |
| 28–30 | Volver a 1 m (fracción de cada clase por celda) | Máscaras | `arena.tif` (Juan y Sebas, **h30**) | Raster float32 sobre la malla base |
| 30–32 | Componentes conexos de crestas y huecos → centroides → estaciones | Máscaras a 1 m | `estaciones_e8.geojson` v1 (Diana, **h32**) | GeoJSON con el formato del contrato |
| 32–40 | Apoyar la integración de E8 en el HUD; E10 reducido solo si todo está listo | — | — | — |
| 40–46 | Video, demo, README y ensayo (todos) | — | — | — |
| 46–48 | Margen para el envío | — | — | — |

**Apoya a:** Juan en proyectar la trayectoria y en ML. **Cambio respecto al Manual:** las estaciones v0 del top-hat salen en la hora 8 para que Diana conecte el formato temprano; las v1 de la U-Net llegan en la hora 32.

## Entregas cruzadas y cortes

Si una entrega se atrasa, quien la recibe trabaja con un provisional del mismo formato y avisa en el issue. Quien la entrega avisa en cuanto vea que no llega, no a la hora límite.

| Hora | Archivo | De | Para |
| --- | --- | --- | --- |
| 1 | Caja del recorte y `crs.wkt` | JB | Todos |
| 2 | `dem_1m.tif`, `grid.json`, `orto_gris_025.tif` | JB | Todos; ortofoto gris para Aaron |
| 3 | `slope_deg.tif` | JB | Sebas, Aaron |
| 4 | Features y teselas del mapa | JB | Juan, Sebas |
| 4 | Grafo sobre la malla | Aaron | Diana |
| 4 | `trayectoria.geojson` y celdas | Juan | Sebas |
| 8 | Costo E3 | Sebas | Aaron, Diana |
| 8 | `estaciones_e8_v0.geojson` (top-hat) | JB | Diana |
| 12 | `rv.tif` y ruta E4 | Aaron | Sebas |
| 14 | `estaciones_manual.geojson` | Sebas | Diana |
| 20 | Pesos de E1 | Juan | Sebas |
| 24 | Costo humano final y rutas del MVP | Sebas, Aaron, Diana | Todos |
| 30 | `arena.tif` | JB | Juan, Sebas |
| 32 | `estaciones_e8.geojson` v1 | JB | Diana |
| 34 | `rocas.tif` | Aaron | Juan, Sebas |
| 34 | Dosis por punto | Juan | Sebas |
| 40 | Tabla de resultados y código congelado | Juan, Sebas | Todos |

**Horas de corte**

| Hora | Pieza | Si no llega |
| --- | --- | --- |
| 18 | E5 | Bajar a N = 15 o ILP con OR-Tools |
| 20 | E1 | Costo E3 con pesos fijados por sensibilidad |
| 28 | E8 | Máscaras del top-hat como estaciones y peligro |
| 28 | E9 | Aaron pasa a E7 |
| 30 | E12 | Solo dosis acumulada, sin alerta SEP |
| 30 | E6, E7, E10 | No se empiezan si el MVP no dio números en la hora 24 |

**Pregunta abierta:** a qué hora del reloj es la hora 0. Escríbanla aquí para convertir esta tabla a horas reales.
