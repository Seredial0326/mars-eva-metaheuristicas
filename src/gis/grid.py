"""Build data/base/grid.json: the base-grid spec (contract in issue #2).

Run from the data/ folder:  python ../src/gis/grid.py
"""
import json

import rasterio

with rasterio.open("base/dem_1m.tif") as dem, rasterio.open("base/ortho_color_025.tif") as ortho:
    t, to = dem.transform, ortho.transform
    xmin, ymax = t.c, t.f
    xmax, ymin = t.c + t.a * dem.width, t.f + t.e * dem.height
    grid = {
        "crs_wkt": "data/base/crs.wkt (repo: docs/contracts/crs.wkt)",
        "crs_proj4": dem.crs.to_proj4(),
        "bbox": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
        "bbox_margin_64m": {"xmin": xmin - 64, "ymin": ymin - 64, "xmax": xmax + 64, "ymax": ymax + 64},
        "grid_1m": {
            "file": "data/base/dem_1m.tif",
            "cell_size_m": t.a,
            "width": dem.width,
            "height": dem.height,
            "origin_x": xmin,
            "origin_y": ymax,
            "affine": list(t)[:6],
        },
        "grid_025m": {
            "file": "data/base/ortho_color_025.tif",
            "cell_size_m": to.a,
            "width": ortho.width,
            "height": ortho.height,
            "affine": list(to)[:6],
        },
        "dtype": "float32",
        "nodata": "NaN",
        "notes": [
            "Origin = top-left corner of cell (0, 0). Row 0 = north.",
            "Center of cell (row, col): x = origin_x + (col + 0.5) * cell; y = origin_y - (row + 0.5) * cell.",
            "To crop: gdalwarp -te xmin ymin xmax ymax -tr 1 1 (never -tap).",
            "One 1 m cell = 4 x 4 cells of 0.25 m.",
        ],
    }

with open("base/grid.json", "w", encoding="utf-8") as f:
    json.dump(grid, f, indent=2)
print(json.dumps(grid, indent=2))
