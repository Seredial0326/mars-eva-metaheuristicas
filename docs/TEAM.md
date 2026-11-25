# Martian Map · guía del equipo

Guía interna del equipo (en español). El README del proyecto, en inglés y para el jurado, está en [`../README.md`](../README.md).

Equipo de NASA Space Apps 2026, reto *Martian Map*: planificador de EVA para el boxwork del cráter Gale, validado con la ruta de Curiosity.

## Para empezar

1. Instala [GitHub CLI](https://cli.github.com) y ejecuta `gh auth login` con **tu propia cuenta** (el tablero ignora los mensajes de la misma cuenta).
2. Clona el repositorio y comprueba el acceso al tablero:
   ```bash
   tools/board whoami
   tools/board read -n 20
   ```
3. Lee `AGENTS.md`: reglas del equipo y tabla de responsables por carpeta. Tu agente también la lee (`CLAUDE.md` la importa).
4. Lee `docs/guia_trabajo_equipo.md`: qué hace cada persona de la hora 0 a la entrega, entregas cruzadas, contratos y horas de corte. Cada pieza tiene su issue. Qué significa cada código (E1…E12): `docs/enfoques.md`.
5. Los datos no están en el repositorio. `data/README.md` describe cada conjunto, su formato y en qué enfoque se usa, y `data/_scripts/` trae los scripts para copiarlos por la red local o bajarlos del origen.

## Correr la app (HUD, modo Guiar y vista 3D)

Un solo servidor (FastAPI) sirve la API, el HUD y las teselas en `http://localhost:8000/`. No hace falta internet en la demo. Detalle y guion de 6 minutos: `docs/demo.md`.

**Requisitos:** Python 3.12 (el entorno del equipo, por ejemplo `conda activate martian`) y `gh` con `gh auth login`. Todo en una terminal normal, no de administrador, desde la raíz del repositorio.

1. **Código al día e instalación de paquetes** (una vez):
   ```powershell
   git checkout main; git pull
   python -m pip install -r api/requirements.txt
   ```
2. **Datos** (una vez; no están en git, vienen de los releases). En PowerShell:
   ```powershell
   gh release download base-grid-v2 --dir data; Expand-Archive data\base_grid_v2.zip data\base -Force; Remove-Item data\base_grid_v2.zip
   gh release download tiles-v2 --dir data; Expand-Archive data\tiles_v2.zip data\tiles -Force; Remove-Item data\tiles_v2.zip
   gh release download e2-trajectory-v1 --dir data; Expand-Archive data\e2_trajectory_v1.zip data\e2 -Force; Remove-Item data\e2_trajectory_v1.zip
   gh release download stations-v1 --dir data\stations
   gh release download e12-dose-v1 --dir data; Expand-Archive data\e12_dose_v1.zip data\e12 -Force; Remove-Item data\e12_dose_v1.zip
   gh release download e8-v0 --dir data; Expand-Archive data\e8_v0.zip data\e8 -Force; Remove-Item data\e8_v0.zip
   gh release download e1-sand-v1 --dir data; Expand-Archive data\e1_sand_v1.zip data\e1 -Force; Remove-Item data\e1_sand_v1.zip
   gh release download minerals-v1 --dir data; Expand-Archive data\minerals_v1.zip data\minerals -Force; Remove-Item data\minerals_v1.zip
   gh release download themis-v1 --dir data; Expand-Archive data\themis_v1.zip data\thermal -Force; Remove-Item data\themis_v1.zip
   gh release download rems-v1 --dir data; Expand-Archive data\rems_v1.zip data\rems -Force; Remove-Item data\rems_v1.zip
   python src/viz3d/build_terrain_assets.py
   ```
   La última línea genera `data/tiles/3d/` para la vista 3D (unos segundos). Comprueba qué falta con:
   ```powershell
   python -m api.check_data
   ```
   Si falta algo, ese comando imprime el comando exacto para bajarlo. Solo `base`, `tiles` y `e2` son obligatorios; sin los demás se apaga la capa o el panel correspondiente.
3. **Arrancar:**
   ```powershell
   python -m uvicorn api.main:app --port 8000
   ```
   Abre **http://localhost:8000/** (HUD). Desde el HUD, después de planificar: **modo Guiar** (`/guide.html`) y **vista 3D** (`/3d/`). El primer plan tarda unos 10 s mientras se arma el grafo; los siguientes, menos de 3 s. Antes de presentar, planifica una vez para dejarlo en caché.
   La **portada** (qué es la app, botones a las tres vistas, la demo paso a paso y el video) está en **http://localhost:8000/home/**.
4. **Comprobar** (opcional): `http://localhost:8000/health` y `python -m pytest tests -q`.

Problemas comunes:
- **El puerto 8000 está ocupado:** usa `--port 8001` y abre esa dirección.
- **Cambiaste de rama y el servidor no ve el cambio:** detenlo (Ctrl+C) y arráncalo de nuevo.
- **El plan visita una sola estación:** el tour de varias estaciones necesita E5 (`src/orienteering`) en `main`. Sin él, `/plan` hace la ida y vuelta de E4 a una estación.

## Tablero de agentes

La issue fijada **Message Board** (#1) es donde los agentes de cada integrante se pasan trabajo. Comandos:

| Comando | Qué hace |
|---|---|
| `tools/board post "[Nombre's Agente] ..."` | Publica. Todo mensaje empieza diciendo de quién es el agente. |
| `tools/board unread` | Muestra lo nuevo desde tu última lectura y marca las menciones. |
| `tools/board wait` | Se bloquea hasta que otra cuenta publique. |
| `tools/board read -n 20` | Muestra los últimos 20 mensajes. |
| `tools/board whoami` | Imprime tu usuario de GitHub. |

Formato tomado de [azizu06/hackathon-agent-board](https://github.com/azizu06/hackathon-agent-board) ([guía](https://marvelous-relative-5de.notion.site/hack)). Solo necesita `bash`, `git` y `gh`.
