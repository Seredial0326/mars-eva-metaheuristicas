# Escena 3 · Mars EVA Planner

Ejecutar desde la raíz del repositorio en PowerShell. La captura usa el planificador que ya corre en `http://127.0.0.1:8000/`, con sus teselas y datasets del laboratorio. Requiere Node.js, FFmpeg y ffprobe en el PATH, y la habilidad HyperFrames instalada en `.agents/skills/hyperframes/`.

```powershell
npm.cmd ci --prefix video
& .\video\node_modules\.bin\playwright.cmd install chromium
node video/capturar-03.mjs
node video/montar-03.mjs
```

La primera ejecución de DP y ACO calienta el servidor. La segunda queda en `video/grabaciones/escena-03.webm`, a 1920 × 1080. El archivo contiguo `resultados-03.json` guarda las cifras del panel, el tiempo de respuesta desde el clic y el aviso de CP-SAT. Los segundos se miden antes de ajustar el ritmo de la toma para la edición.

El montaje toma la voz de `video/audio/03-*` o de `video/audio/escena 3.mp4`. Ajusta la duración de la imagen a la voz y deja cuatro segundos adicionales para el aviso. Sin voz, conserva el ritmo original. El proyecto editable queda en `video/composicion/` y el render en `video/escena-03-prueba.mp4`. Cada ejecución sustituye la prueba anterior.
