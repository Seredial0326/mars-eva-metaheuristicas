# Mars EVA Planner · Video

El proyecto editable de las siete escenas está en `video/composicion/`. Desde la raíz del repositorio:

```powershell
node video/pelicula.mjs preview
node video/pelicula.mjs render
node video/pelicula.mjs verificar
```

La exportación queda en `video/mars-eva-planner.mp4`. La verificación decodifica el video y el audio completos y extrae un fotograma por escena en `video/revision/`.

## Rehacer el montaje

Instala las herramientas con los comandos de preparación de abajo. Reúne los siete audios, el MP4 aprobado de la escena 3 y las figuras del laboratorio. Con el servidor local activo:

```powershell
node video/capturar-mapa-lab.mjs
python video/preparar-algoritmos.py
node video/graficas.mjs
node video/pelicula.mjs preparar
node video/pelicula.mjs check
node video/pelicula.mjs render
```

`preparar` mide los siete audios decodificados y escribe sus cortes en `video/composicion/tiempos.json`. Las marcas de frase de las láminas están en `preparar-algoritmos.py` y `tiempos-graficas.json`. La toma de ACO se recorta para sincronizar la imagen con la voz. En el laboratorio `real-n50-0-120min` se ejecutan los cinco solvers habilitados. La interfaz muestra DP deshabilitado junto al límite.

## Preparación y prueba de la escena 3

Ejecutar desde la raíz del repositorio en PowerShell. La captura usa el planificador que ya corre en `http://127.0.0.1:8000/`, con sus teselas y datasets del laboratorio. Requiere Node.js, FFmpeg y ffprobe en el PATH, y la habilidad HyperFrames instalada en `.agents/skills/hyperframes/`.

```powershell
npm.cmd ci --prefix video
& .\video\node_modules\.bin\playwright.cmd install chromium
node video/capturar-03.mjs
node video/montar-03.mjs
```

La primera ejecución de DP y ACO calienta el servidor. La segunda queda en `video/grabaciones/escena-03.webm`, a 1920 × 1080. El archivo contiguo `resultados-03.json` guarda las cifras del panel, el tiempo de respuesta desde el clic y el aviso de CP-SAT. Los segundos se miden antes de ajustar el ritmo de la toma para la edición.

El montaje toma la voz de `video/audio/03-*` o de `video/audio/escena 3.mp4`. Ajusta la duración de la imagen a la voz y deja cuatro segundos adicionales para el aviso. Sin voz, conserva el ritmo original. El proyecto de prueba queda en `video/composicion-prueba-03/` y el render en `video/escena-03-prueba.mp4`. Cada ejecución sustituye la prueba anterior.
