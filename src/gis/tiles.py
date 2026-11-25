"""Display layers and XYZ tiles (gdal2tiles raster profile) for the web map (issue #3).

Run from the data/ folder:  python ../src/gis/tiles.py
Output: data/tiles/{ortho,slope,hillshade}/{z}/{x}/{y}.png and data/tiles/tiles.json
"""
import json
import shutil
import subprocess
import sys
from pathlib import Path

import rasterio

BASE, VIZ, TILES = Path("base"), Path("viz"), Path("tiles")
TILE_PX = 256
SLOPE_RAMP = "nv 0 0 0 0\n0 26 152 80\n15 254 224 139\n30 244 109 67\n45 165 0 38\n90 80 0 20\n"

# name: (source raster, zoom levels, max resolution in m)
LAYERS = {
    "ortho": (BASE / "ortho_color_025.tif", "0-5", 0.25),
    "slope": (VIZ / "slope_color.tif", "0-3", 1.0),
    "hillshade": (BASE / "hillshade.tif", "0-3", 1.0),
}


def run(cmd):
    subprocess.run([str(c) for c in cmd], check=True)


VIZ.mkdir(exist_ok=True)
TILES.mkdir(exist_ok=True)

# 1. Colour slope: green (flat) -> yellow 15 -> orange 30 -> red 45+ degrees
(VIZ / "slope_ramp.txt").write_text(SLOPE_RAMP)
run(["gdaldem", "color-relief", "-alpha", BASE / "slope_deg.tif", VIZ / "slope_ramp.txt", VIZ / "slope_color.tif"])

# 2. Tiles: raster profile (not Web Mercator), XYZ order (y = 0 at the top)
for name, (src, zoom, _) in LAYERS.items():
    out = TILES / name
    if out.exists():
        shutil.rmtree(out)
    run([sys.executable, "-m", "osgeo_utils.gdal2tiles", "--profile=raster", "--xyz",
         "--processes=8", "-z", zoom, "-w", "none", src, out])
    n = sum(1 for _ in out.rglob("*.png"))
    print(f"{name:10s} {n:5d} tiles, zoom {zoom}")

# 3. Tile spec for the map (every layer shares the same z = 0 footprint)
with rasterio.open(BASE / "dem_1m.tif") as dem:
    t, width = dem.transform, dem.width
tile_z0_m = TILE_PX * 2 ** 3 * t.a  # 256 px * 8 * 1 m = 2048 m (= 256 * 32 * 0.25 m)
spec = {
    "profile": "gdal2tiles raster profile, --xyz, PNG 256 x 256, y = 0 at the top",
    "origin_m": {"xmin": t.c, "ymax": t.f},
    "tile_z0_m": tile_z0_m,
    "tile_bounds": "tile (z, x, y) spans x in [xmin + x*s, xmin + (x+1)*s], "
                   "y in [ymax - (y+1)*s, ymax - y*s], with s = tile_z0_m / 2**z",
    "layers": {name: {"url": f"tiles/{name}/{{z}}/{{x}}/{{y}}.png", "zoom": zoom, "max_res_m": res}
               for name, (_, zoom, res) in LAYERS.items()},
    "slope_colors": "green 0, yellow 15, orange 30, red 45+ degrees",
    "bbox_size_m": t.a * width,
    "note": "Tiles span 2048 m; the last 48 m on the right and bottom are transparent.",
}
(TILES / "tiles.json").write_text(json.dumps(spec, indent=2))
print(json.dumps(spec, indent=2))
