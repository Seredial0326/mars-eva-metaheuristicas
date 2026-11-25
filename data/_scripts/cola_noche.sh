#!/bin/bash
# Cola nocturna: espera a que terminen DEM + ortofoto color, luego baja la ortofoto gris (24 GB)
# y, solo si queda tiempo (antes de las 06:00), los datos crudos de BoulderNet (9,4 GB).
# Uso: bash data/_scripts/cola_noche.sh [PID_a_esperar]
cd "$(dirname "$0")/.."
if [ -n "${1:-}" ]; then while kill -0 "$1" 2>/dev/null; do sleep 30; done; fi
echo "[$(date '+%F %T')] empieza ortofoto gris"
bash _scripts/descargar_grandes.sh gris
echo "[$(date '+%F %T')] ortofoto gris terminó (exit $?)"
H=$(date +%H)
if [ "$H" -ge 20 ] || [ "$H" -lt 6 ]; then
  echo "[$(date '+%F %T')] empieza raw_data_BOULDERING (9,4 GB)"
  mkdir -p 06_bouldernet/zenodo_8171052_original_2023
  python3 -I _scripts/bajar.py "https://zenodo.org/api/records/8171052/files/raw_data_BOULDERING.zip/content" \
    "06_bouldernet/zenodo_8171052_original_2023/raw_data_BOULDERING.zip" --conns 8 --md5 ad8592ada710a00ec2cd8e0db8be9896
else
  echo "[$(date '+%F %T')] sin tiempo para raw_data_BOULDERING; queda pendiente (opcional)"
fi
echo "[$(date '+%F %T')] cola terminada"
