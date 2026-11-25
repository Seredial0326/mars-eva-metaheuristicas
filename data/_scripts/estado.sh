#!/bin/bash
# Muestra el avance de las descargas: bash data/_scripts/estado.sh
cd "$(dirname "$0")/.."
date '+%F %T'
for f in _logs/*.log; do printf '%-22s %s\n' "$(basename "$f")" "$(tr '\r' '\n' < "$f" | grep -v '^$' | tail -1)"; done
echo "--- procesos activos"; pgrep -fl "bajar.py" | sed -E 's/.*bajar.py //' | cut -c1-110
echo "--- tamaños"; du -sh [0-9]*/ 2>/dev/null
