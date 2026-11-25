# Datos de Martian Map (NASA Space Apps 2026)

Todo lo que hay en esta carpeta está **descargado tal cual, sin procesar**. Solo se comprobó que cada archivo abre y qué formato tiene. No hay recortes, features ni resultados: eso empieza con el equipo el 14 de noviembre.

Descargado el 13-nov-2026. Cada subcarpeta tiene un `_NOTAS.md` con el detalle archivo por archivo (URL de origen, tamaño, comprobación). Este README es el índice.

## 1. Estado de las descargas

| Conjunto | Tamaño | Estado |
| --- | --- | --- |
| Waypoints, ruta y PLACES de Curiosity | 61 MB | Completo |
| Clima REMS, radiación RAD | 173 MB | Completo |
| Índice de imágenes crudas + muestra Navcam | 355 MB | Completo |
| Panorámicas del boxwork | 928 MB | Completo (falta una versión de 1,9 GB, ver sección 8) |
| Catálogos de Mars Trek | 3,5 MB | Completo |
| Geología USGS | 2,0 GB | Completo |
| BoulderNet (2 datasets + pesos + código) | 3,4 GB | Completo, md5 verificado |
| Instancias de orienteering | 18 MB | Completo |
| Papers | 151 MB | 24 de 27 (ver sección 8) |
| DEM de Gale 1 m | 3,87 GB | Completo (00:43), cabecera leída y huella del servidor verificada |
| AI4Mars v0.1 | 6,15 GB | Completo (01:21), huella del servidor verificada, extraído (71.355 archivos) |
| Ortofoto color (COG) | 1,03 GB | Completo (01:07), cabecera leída y huella del servidor verificada |
| Ortofoto gris 25 cm | 24,4 GB | Completo (06:58), cabecera leída y huella del servidor verificada |
| Crudos de BoulderNet | 9,4 GB | Opcional. **En pausa al 54 %** (detenida a las 7:57; los segmentos `.part*` están guardados). Para continuar: `python3 data/_scripts/descargar_todo.py --perfil opcional` |

Para ver el avance en cualquier momento: `bash data/_scripts/estado.sh`. Todas las descargas son reanudables: si algo se corta, se repite el mismo comando.

## 2. Estructura

```text
data/
├── README.md                      este archivo
├── _scripts/                      descarga, verificación y copia entre máquinas (sección 7)
├── 01_terreno/dem_gale_1m/        DEM de 1 m (GeoTIFF)
├── 02_imagenes_orbitales/
│   ├── ortofoto_color_cog/        mosaico HiRISE color 25 cm (COG)
│   └── ortofoto_gris_25cm/        mosaico HiRISE gris 25 cm (24 GB)
├── 03_curiosity/
│   ├── waypoints/                 finales de conducción y ruta (GeoJSON)
│   ├── places_pds/                localizaciones oficiales PDS (CSV)
│   ├── clima_rems/                meteorología por sol (JSON)
│   ├── radiacion_rad/             tasa de dosis del detector RAD (CSV, CDF)
│   ├── imagenes_crudas/           índice de 140.755 imágenes + muestra Navcam
│   └── panoramas/                 3 panorámicas publicadas del boxwork
├── 04_mars_trek/                  catálogo y esquemas de teselas (no las teselas)
├── 05_geologia/                   mapa geológico global y datos locales de Gale
├── 06_bouldernet/                 datasets, pesos y código de detección de rocas
├── 07_ai4mars/                    etiquetas de terreno en vista del rover
├── 08_instancias_orienteering/    instancias de prueba de KU Leuven
└── 09_papers/                     referencias en PDF, por tema
```

## 3. Sistema de coordenadas común

Lo más importante para empezar: **el DEM, las dos ortofotos, los waypoints y PLACES comparten proyección**, así que se superponen sin reproyectar.

- Proyección: equirectangular de Marte, `+proj=eqc +lat_ts=0 +lat_0=0 +lon_0=0 +x_0=0 +y_0=0 +R=3396190 +units=m`.
- Conversión directa: `easting = lon × 59274,697 m/°`, `northing = lat × 59274,697 m/°` (longitud este positiva, latitud planetocéntrica).
- Las columnas `easting`/`northing` de los waypoints y de PLACES ya están en ese sistema. Comprobado: la elevación `elev_geoid` de los waypoints coincide con el DEM con diferencia 0,00 m en los 114 puntos probados.
- GeoJSON de waypoints y ruta: coordenadas `[lon, lat, elevación]` en grados. No es WGS84 terrestre: es longitud/latitud marciana.
- Mars Trek usa otra cosa: teselas en lon/lat (`EPSG::104905`), ver `04_mars_trek/_NOTAS.md`.

## 4. Qué es cada cosa

### 01_terreno/dem_gale_1m — E1, E2, E3, E4, E5, E7, E8

`MSL_Gale_DEM_Mosaic_1m_v3.tif` (USGS, Parker y Calef 2016). Mosaico HRSC + CTX + HiRISE amarrado a MOLA.

- GeoTIFF de 32.980 × 57.440 píxeles, 1 banda `float32`, 1 m/píxel, `nodata = -32767`, compresión LZW.
- Guardado en tiras (no en teselas) y sin pirámides: leer una ventana pequeña es rápido, abrirlo entero en un visor es lento.
- Cubre lon 137,124–137,681 y lat −5,099 a −4,130; contiene los 1.389 waypoints de la misión.
- Alturas en metros sobre el areoide; en la zona del boxwork van de unos −3.860 a −3.400 m.

### 02_imagenes_orbitales — E8, E9, mapa base del producto

| Archivo | Formato comprobado (cabecera leída en local tras la descarga) |
| --- | --- |
| `ortofoto_color_cog/MSL_Gale_HiRISE-LRGB_78quads_sharp_cog.tif` | 36.000 × 76.000 px, 3 bandas `uint8` RGB, 0,25 m/píxel, COG con teselas de 512 px, JPEG, 8 niveles de pirámide. Cubre E 8.140.000–8.149.000 y N −289.000 a −270.000 (franja de 9 × 19 km que incluye toda la ruta reciente y el boxwork). |
| `ortofoto_gris_25cm/MSL_Gale_Orthophoto_Mosaic_25cm_v3.tif` | 180.000 × 280.000 px, 1 banda `uint8` con paleta, 0,25 m/píxel, teselas de 128 px, PackBits, sin pirámides. Cubre 45 × 70 km. |

La de color es la práctica para trabajar; la gris cubre más área. Ambas se pueden leer por ventanas directamente desde la URL sin tenerlas en disco (URLs en `_scripts/manifiesto.json`).

### 03_curiosity/waypoints — E1, E2 (y estaciones para E5)

Capas del mapa público de localización de la misión.

| Archivo | Contenido |
| --- | --- |
| `MSL_waypoints.json` | 1.389 puntos, uno por final de conducción, soles 3–5073. Campos: `site, drive, sol, easting, northing, elev_geoid, lon, lat, roll, pitch, yaw, tilt, dist_m, dist_total_m`. Ángulos en grados. |
| `MSL_traverse.json` | Ruta continua: 1.317 tramos `MultiLineString`, 27.018 vértices `[lon, lat, elev]`. Única propiedad: `Length`. **No trae sol ni tiempo.** |
| `MSL_waypoints_current.json` | Posición actual (sol 5073). |
| `MSL_SurfaceSites.json` | 4 polígonos de sitios con nombre (ninguno es del boxwork). |
| `mmgis_config_MSL.json` | Configuración del mapa, con los nombres reales de sus 7 capas. |

### 03_curiosity/places_pds — E1, E2

Base de localizaciones PLACES del PDS (bundle PDS4, cada tabla con su etiqueta `.csv.xml`). Llega al sol 4868.

| Archivo | Contenido |
| --- | --- |
| `data_localizations/localized_interp.csv` | 49.315 poses interpoladas (una por posición registrada del rover). Es la trayectoria fina con tiempo. |
| `data_localizations/localized_pos.csv` | 1.470 posiciones localizadas. |
| `data_localizations/telemetry.csv` | 106.755 filas de telemetría de movilidad. |
| `*_demv2.csv` | Variantes ajustadas a otra versión del DEM. |
| `data_mechanisms/mech_drill.csv` | 2.131 registros del taladro (site, drive, SCLK; **sin columna de sol**). |
| `document/PLACES_PDS_SIS.pdf` | Especificación: qué significa cada columna y cada marco de referencia. Leerla antes de usar las tablas. |

Las cinco tablas de localización tienen las mismas 26 columnas: `frame, site, drive, pose, landing_x/y/z, northing, easting, planetocentric_latitude, planetodetic_latitude, longitude, elevation, map_pixel_line/sample, dem_pixel_line/sample, roll, pitch, yaw, quat_*, sclk, sol`.

### 03_curiosity/clima_rems — condiciones actuales, ventanas de tiempo de E5

`rems_weather_msl.json`: 4.745 registros, uno por sol (soles 1–4995, hasta el 25-ago-2026). Temperatura mínima y máxima del aire y del suelo, presión, amanecer y atardecer, índice UV, estación.

- Todos los valores son cadenas de texto; hay que convertirlos.
- `wind_speed` y `abs_humidity` están vacíos (`"--"`) en todos los registros.
- `atmo_opacity` es texto ("Sunny") y el UV es categórico (Low/Moderate/High/Very_High).
- El propio archivo se declara "for outreach purposes only".

### 03_curiosity/radiacion_rad — E12

| Carpeta | Contenido |
| --- | --- |
| `cdaweb_MSL_RAD_OBS-L2/csv_dosimetria_servicio_cdas/` | 11 CSV, 57.843 observaciones del 1-ene-2025 al 11-nov-2026 (~85 por día). Columnas: `EPOCH`, `ALIVE_TIME_seconds`, `TOTAL_DOSE_B`, `RTG_CORRECTED_DOSE_B`, `TOTAL_DOSE_E`. **Es lo que hay que usar.** |
| `cdaweb_MSL_RAD_OBS-L2/cdf_obs-l2/` | Los mismos datos en 680 archivos CDF diarios (no abiertos; requieren `cdflib`). |
| `pds_ppi_MSL-M-RAD-3-RDR-V1.0/` | Documentación del volumen PDS y una muestra de un sol (4715). |
| `FUENTES.md` | URLs exactas para bajar más. |

Las dosis son **absorbidas** (CDAWeb las etiqueta en µGy/día; la etiqueta PDS dice µGy/hora para un campo equivalente: verificar la unidad antes de usar). Ningún producto trae dosis equivalente en Sv, así que no se comparan directamente con los 0,64 mSv/día de Hassler 2014.

### 03_curiosity/imagenes_crudas — vista desde el suelo para el producto, E10

- `indice_soles_4450_4848/page_*.json`: metadatos de las 140.755 imágenes crudas de esos soles (todas las cámaras). Cada item trae `sol, instrument, date_taken, https_url` y un bloque `extended`. **Las imágenes no están descargadas**: el índice dice dónde está cada una.
- Navcam, Hazcam y ChemCam traen `site`, `drive`, `xyz`, `attitude`, `mast_az`, `mast_el`: se pueden ubicar en el mapa. Mastcam, MAHLI y MARDI traen esos campos en `null`.
- De 59.584 items de Navcam solo 6.505 son imágenes completas; el resto son miniaturas o recortes.
- `muestra_navcam/sol_XXXX/`: 238 JPEG de 1024 × 1024 de seis soles (4450, 4548, 4650, 4711, 4789, 4845), con manifiesto por carpeta.

### 03_curiosity/panoramas — demo y narrativa

| Producto | Archivos |
| --- | --- |
| PIA26559, primera panorámica del boxwork | JPEG 29.241 × 7.728 (38 MB) y TIFF (451 MB) |
| PIA26696, 360° en "Nevado Sajama" | JPEG reducido 8.192 × 1.685 y PNG 29.643 × 6.655 (289 MB) |
| PIA26693, vista general de la región | PNG 16.221 × 6.189 (179 MB) |

Cada una con su página y su leyenda en texto.

### 04_mars_trek — mapa base del producto, capas térmica y de contexto

Recurso oficial del reto. No hay teselas descargadas: se piden al servidor de NASA cuando se muestra el mapa.

- `catalogo/`: los 225 productos de Mars Trek.
- `wmts_capabilities/`: esquema de 18 capas que cubren Gale.
- `teselas_prueba/`: dos teselas reales sobre el boxwork que confirman el patrón de URL.
- `arcgis_servicios/`: las dos capas de detecciones minerales (CRISM/OMEGA) como GeoJSON de puntos.

Patrón: `https://trek.nasa.gov/tiles/Mars/EQ/<capa>/1.0.0/default/default028mm/{z}/{fila}/{col}.png`, con 2^(z+1) columnas × 2^z filas y origen en (−180, 90). Niveles máximos: `curiosity_hirise_mosaic` 16, `Gale_DEM_SMG_1m` 14, `Gale_CTX_BlockAdj_dd` 12, THEMIS 9. Las teselas son imágenes de 8 bits para mostrar, no valores físicos.

### 05_geologia — contexto, valor científico de estaciones (E5)

Recurso oficial del reto (programa de mapas geológicos USGS-NASA).

- `SIM3292_global_Tanaka2014/`: mapa geológico global 1:20M en shapefile y geodatabase (1.311 polígonos con `Unit` y `UnitDesc`). A esa escala Gale entero son unas pocas unidades.
- `usgs_pgm_hub/`: índice de los 148 mapas publicados. **No existe mapa geológico local de Gale publicado** ("Aeolis Mons" 1:60K figura como en progreso).
- `I-1111_Aeolis_cuadrangulo_1978/`: cuadrángulo 1:5M, solo imagen.
- `gale_especificos/`: tres conjuntos de Zenodo (CC-BY) de zonas vecinas de Mount Sharp (Glen Torridon, Sakarya Vallis). No son del boxwork.

### 06_bouldernet — E9 (y referencia para E8)

Prieur et al. 2023, licencia CC-BY-4.0. Los tres zip tienen md5 verificado y están extraídos en `extraido/`.

| Carpeta | Contenido |
| --- | --- |
| `zenodo_8171052_original_2023/Apr2023-…-mask-5px.zip` | 953 parches de 500 × 500 gris (PNG y GeoTIFF). Train 755 / validación 142 / test 56. Etiquetas en formato Detectron2 (máscaras RLE), 1 clase `boulder`, 39.378 anotaciones. Luna 656, Tierra 248, **Marte 49**. |
| `zenodo_8171052_original_2023/best_model.zip` | Pesos del modelo: `model_0055999.pth` (el recomendado) y `model_0063999.pth`, 351 MB cada uno, más configuración. Mask R-CNN ResNet-50 + FPN. |
| `zenodo_14250874_ampliado_2024/` | 4.976 PNG de 500 × 500. Train 3.957 / validación 739 / test 280. Etiquetas en YOLO-seg (`.txt`) y Detectron2 (JSON por columnas, se lee con `pandas.read_json`). Luna 4.678, Tierra 248, **Marte 50**. |
| `MLtools/`, `rastertools/`, `shptools/`, `YOLOv8-BeyondEarth/` | Código de los autores (MIT), solo clonado. |

Requisitos según los README (no instalados): Python ≥ 3.9, PyTorch 1.13.1, Detectron2. El modelo se entrenó con detectron2 0.6 y PyTorch 1.12.1 con CUDA 11.6. El `_BASE_` del yaml apunta a una ruta del autor y hay que cambiarlo.

### 07_ai4mars — E10

`nasa_v0.1/ai4mars-dataset-merged-0.1.zip` (6,15 GB) y su contenido en `nasa_v0.1/extraido/ai4mars-dataset-merged-0.1/msl/`. Comprobado tras extraer:

- Solo Curiosity (la carpeta de los otros rovers está vacía), soles 1–2579: **no incluye el boxwork**.
- 18.127 imágenes Navcam de 1024 × 1024 con máscaras del rover y de distancia.
- Etiquetas PNG: 0 suelo, 1 roca madre, 2 arena, 3 roca grande, 255 sin etiqueta. Train 16.064, test 322; no hay validación.
- Carpetas: `images/edr` (18.127 JPG en gris), `images/mxy` (18.097 máscaras del rover, valores 0/1), `images/rng-30m` (18.096 máscaras de distancia), `labels/train` y `labels/test/masked-gold-min{1,2,3}-100agree` (322 cada una). Todo es PNG/JPG de 1024 × 1024, 8 bits, un canal.
- **Hay etiquetas enteras en 255** (imagen sin ningún píxel etiquetado): salió en 2 de las 3 que abrí. Hay que filtrarlas antes de entrenar.

### 08_instancias_orienteering — E5, E6

Instancias de KU Leuven, cada conjunto con su archivo de formato: `OP_clasico/` (Tsiligirides, Chao), `TOP/`, `TOPTW/` (con soluciones óptimas), `TDOP/`, `TDOPTW/`. Los formatos están resumidos en su `_NOTAS.md`. No hay óptimos publicados para el OP clásico, solo para las variantes con ventanas de tiempo.

### 09_papers — referencia

24 PDF por tema: `destilacion_y_rocas/` (Hinton 2015, BoulderNet, U-Net), `irl_y_movilidad_rover/`, `metabolismo_y_eva/`, `orienteering_y_robustez/`, `radiacion/`, más `ciencia_boxwork/` con las notas de NASA sobre el boxwork y el recurso oficial de la ruta por Mount Sharp. La tabla con referencia completa y enfoque está en su `_NOTAS.md`.

## 5. Qué usa cada enfoque

| Enfoque | Datos |
| --- | --- |
| E1 costo aprendido | `03_curiosity/places_pds` (trayectoria fina), `waypoints`, `01_terreno` |
| E2 movilidad del rover | `03_curiosity/waypoints` (tilt, pitch, roll), `places_pds/telemetry.csv`, `01_terreno` |
| E3 costo metabólico | `01_terreno`; papers de `metabolismo_y_eva/` |
| E4 walkback | `01_terreno` |
| E5 orienteering | `01_terreno`, `08_instancias_orienteering`, `clima_rems` (ventanas), `05_geologia` y `ciencia_boxwork` (valor de estaciones) |
| E6 metaheurísticas | `08_instancias_orienteering` |
| E7 robustez del DEM | `01_terreno` |
| E8 crestas y huecos | `01_terreno`, `02_imagenes_orbitales` |
| E9 rocas | `06_bouldernet`, `02_imagenes_orbitales` |
| E10 orbital vs. rover | `07_ai4mars`, `03_curiosity/imagenes_crudas` |
| E11 visibilidad y sombras | `01_terreno` |
| E12 radiación | `03_curiosity/radiacion_rad` |
| Producto (mapa, HUD) | `04_mars_trek`, `02_imagenes_orbitales`, `panoramas`, `imagenes_crudas`, `clima_rems` |

## 6. Avisos que conviene leer antes de empezar

1. **Los soles del boxwork no son 4450–4850.** La leyenda de NASA de PIA26559 dice "sol 4.451" para el 15-may-2025, pero según REMS y las fechas de las imágenes ese día es el **sol 4541** (el 4451 es el 12-feb-2025). El rover salió hacia el sol 4848. Entre 4541 y 4848 hay 77 waypoints (1,85 km) y 2.603 poses en `localized_interp.csv`. El rango exacto debe fijarlo el equipo mirando el mapa.
2. **La ruta continua sin tiempo y la trayectoria con tiempo son archivos distintos.** `MSL_traverse.json` no dice cuándo; `localized_interp.csv` sí, pero llega al sol 4868 y no al 5073.
3. **No hay capa pública de sitios de taladro.** Lo más cercano es `mech_drill.csv` (site y drive, sin sol), que hay que cruzar con PLACES.
4. **La pendiente depende de la escala.** Medida sobre el DEM crudo a 1–2 m, en la zona del boxwork cerca de la mitad de las celdas supera 15°. Es una comprobación previa, no un resultado: el equipo decide a qué escala medirla.
5. **BoulderNet casi no tiene Marte** (49–50 parches de 4 imágenes HiRISE, ninguna de Gale) y **AI4Mars v0.1 no llega al boxwork**.
6. **REMS y RAD tienen unidades y huecos que revisar** (secciones de arriba).

## 7. Scripts y copia a otras máquinas

Todos están en `_scripts/` y solo necesitan Python 3 estándar (Linux, macOS, Windows).

| Script | Para qué |
| --- | --- |
| `estado.sh` | Ver el avance de las descargas en curso. |
| `bajar.py URL DESTINO` | Descarga reanudable por segmentos en paralelo. |
| `descargar_todo.py --perfil terreno dl` | Bajar los archivos grandes directo del origen según `manifiesto.json`. `--solo-verificar` comprueba tamaños y md5. |
| `servir_lan.py` | En la máquina que ya tiene los datos: los sirve por la red local (solo lectura). |
| `clonar_desde_lan.py http://IP:8000` | On each new machine: copies `data/` from the one running `servir_lan.py`. Accepts `--solo` and `--excluir`. Extracts the zips at the destination. Inside a git checkout it never copies `data/README.md` or `data/_scripts/` (they come from git). |
| `safe_zip.py` | Path checks and zip extraction used by the two scripts above: resumable, long paths on Windows, skips and lists `.ipynb_checkpoints`, `__MACOSX` and names Windows cannot store. |
| `armar_kit_ligero.py` | Empaqueta todo lo pequeño (< 30 MB por archivo, unos 700 MB) en `_kit_ligero.zip` para USB. |
| `descargar_grandes.sh`, `cola_noche.sh` | Las descargas de la noche del 13. |

Camino recomendado con las seis máquinas en la misma red: `servir_lan.py` en una y `clonar_desde_lan.py` en las demás. Si la red bloquea conexiones entre equipos: `descargar_todo.py` en cada una (baja de NASA y Zenodo) más el kit ligero por USB.

`data/` no se sube al repositorio (está en `.gitignore`); solo este README y `_scripts/`.

Para leer los GeoTIFF hace falta `rasterio` (GDAL), que no viene con Python. Probado en esta máquina: `uv run --python 3.12 --with rasterio python ...`.

## 8. Lo que no se consiguió o quedó fuera

| Qué | Por qué | Dónde está |
| --- | --- | --- |
| Paper NaviGATOR (ICES-2024-400) | El repositorio bloquea descargas automáticas; es abierto | Bajar a mano: enlace en `09_papers/_NOTAS.md` |
| Papers Arvidson 2017 y Pandolf 1977 | De pago | DOI en `09_papers/_NOTAS.md` |
| PIA26696 a resolución completa | PNG de 1,9 GB | URL en `03_curiosity/panoramas/_NOTAS.md` |
| AI4Mars v0.6 (los cuatro rovers) | 16,2 GB | Zenodo 15995036 |
| Volumen PDS completo de RAD | ~68 MB por sol | `radiacion_rad/FUENTES.md` |
| Rasters propios de PLACES | 0,4–1,4 GB en un servidor a 100 KB/s | `places_pds/_NOTAS.md` |
| Versión GIS del cuadrángulo I-1111 | El servidor rechaza descargas automáticas | `05_geologia/_NOTAS.md` |
| Crudos de BoulderNet 2023 y 2024 | 9,4 GB y 16,4 GB | `06_bouldernet/_NOTAS.md` |

## 9. Créditos y licencias

- DEM y ortofotos: USGS Astrogeology / NASA / JPL-Caltech / University of Arizona (dominio público; citar Calef y Parker 2016).
- Datos de Curiosity (waypoints, PLACES, REMS, RAD, imágenes): NASA/JPL-Caltech, PDS, CDAWeb; REMS: Centro de Astrobiología (CAB).
- Mars Trek: NASA/JPL.
- BoulderNet: Prieur et al. 2023, CC-BY-4.0; código MIT.
- AI4Mars: NASA/JPL; la v0.1 no declara licencia en data.nasa.gov (la v0.6 es CC-BY-4.0).
- Instancias de orienteering: KU Leuven.
- Papers: cada uno bajo la licencia de su fuente abierta; son para consulta del equipo, no para redistribuir.
