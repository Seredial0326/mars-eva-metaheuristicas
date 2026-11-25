#!/usr/bin/env python3
"""Arma data/_kit_ligero.zip: todo lo pequeño (archivos < 30 MB) para pasar por USB o un Release.

Uso:  python3 data/_scripts/armar_kit_ligero.py
Incluye waypoints, PLACES, clima, radiación (CSV), índice de imágenes, catálogos de Trek, geología vectorial,
instancias, papers, notas y scripts. Excluye rasters grandes, datasets de BoulderNet/AI4Mars, CDF de RAD,
carpetas extraido/ y descargas a medias. Se descomprime en la raíz del repo y recrea data/...
"""
import os, re, zipfile
DATA = os.path.dirname(os.path.dirname(os.path.abspath(__file__))); LIM = 30 << 20
OMITIR = ("06_bouldernet/zenodo", "07_ai4mars/nasa", "03_curiosity/radiacion_rad/cdaweb_MSL_RAD_OBS-L2/cdf_obs-l2", "_logs")
ya = (".zip", ".jpg", ".jpeg", ".png", ".pdf", ".gif", ".7z", ".cdf")
n = tot = 0; dest = os.path.join(DATA, "_kit_ligero.zip")
with zipfile.ZipFile(dest + ".tmp", "w", allowZip64=True) as z:
    for raiz, dirs, files in os.walk(DATA):
        rel = os.path.relpath(raiz, DATA).replace(os.sep, "/")
        dirs[:] = sorted(d for d in dirs if d not in ("extraido", ".git", "__pycache__") and not any((rel + "/" + d).lstrip("./").startswith(o) for o in OMITIR))
        for f in sorted(files):
            p = os.path.join(raiz, f)
            if f.startswith("_kit_ligero") or f == ".DS_Store" or re.search(r"\.(part\d+|tmp)$", f) or os.path.getsize(p) >= LIM: continue
            arc = "data/" + os.path.relpath(p, DATA).replace(os.sep, "/")
            z.write(p, arc, zipfile.ZIP_STORED if f.lower().endswith(ya) else zipfile.ZIP_DEFLATED); n += 1; tot += os.path.getsize(p)
os.replace(dest + ".tmp", dest)
print(f"{n} archivos, {tot/1e6:.0f} MB sin comprimir -> {dest} ({os.path.getsize(dest)/1e6:.0f} MB)")
