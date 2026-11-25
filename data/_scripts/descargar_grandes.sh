#!/bin/bash
# Descargas grandes de USGS (reanudables, 8 conexiones). Volver a ejecutar continúa donde quedó.
# Uso: bash data/_scripts/descargar_grandes.sh [dem|color|gris]
set -u
cd "$(dirname "$0")/.."
BASE="https://asc-pds-services.s3.us-west-2.amazonaws.com/mosaic/Mars/MSL"
case "${1:-}" in
  dem)   python3 -I _scripts/bajar.py "$BASE/MSL_Gale_DEM_Mosaic_1m_v3.tif" "01_terreno/dem_gale_1m/MSL_Gale_DEM_Mosaic_1m_v3.tif" ;;
  color) python3 -I _scripts/bajar.py "$BASE/MSL_Gale_HiRISE-LRGB_78quads_sharp_cog.tif" "02_imagenes_orbitales/ortofoto_color_cog/MSL_Gale_HiRISE-LRGB_78quads_sharp_cog.tif" ;;
  gris)  python3 -I _scripts/bajar.py "$BASE/MSL_Gale_Orthophoto_Mosaic_25cm_v3.tif" "02_imagenes_orbitales/ortofoto_gris_25cm/MSL_Gale_Orthophoto_Mosaic_25cm_v3.tif" --conns 12 ;;
  *) echo "uso: $0 dem|color|gris" ;;
esac
