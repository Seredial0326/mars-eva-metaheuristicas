"""Terrain features on the base grid (issue #3).

Reads data/base/dem_1m_margin.tif, computes every layer with a 64 m margin so
filters have neighbours at the edges, then crops to the exact bbox.

Run from the data/ folder:  python ../src/gis/features.py
"""
import subprocess

import numpy as np
import rasterio
from scipy.ndimage import gaussian_filter, uniform_filter

MARGIN = 64  # cells of 1 m
BASE = "base"


def run(cmd):
    subprocess.run(cmd, check=True)


def read(path):
    with rasterio.open(path) as src:
        return src.read(1, masked=True).filled(np.nan).astype("float32")


def crop(a):
    return a[MARGIN:-MARGIN, MARGIN:-MARGIN]


def local_std(a, size):
    mean = uniform_filter(a, size)
    return np.sqrt(np.clip(uniform_filter(a * a, size) - mean * mean, 0, None))


# 1. Slope and hillshade with GDAL (Horn method), on the margin DEM
run(["gdaldem", "slope", f"{BASE}/dem_1m_margin.tif", f"{BASE}/slope_margin.tif", "-compute_edges"])
run(["gdaldem", "hillshade", f"{BASE}/dem_1m_margin.tif", f"{BASE}/hillshade_margin.tif", "-compute_edges"])

dem = read(f"{BASE}/dem_1m_margin.tif")
with rasterio.open(f"{BASE}/dem_1m.tif") as ref:
    profile = ref.profile.copy()
profile.update(dtype="float32", nodata=np.nan, count=1, compress="deflate", tiled=True)


def save(name, a, units):
    a = crop(a).astype("float32")
    with rasterio.open(f"{BASE}/{name}", "w", **profile) as dst:
        dst.write(a, 1)
    print(f"{name:16s} {units:4s} min {np.nanmin(a):9.3f}  max {np.nanmax(a):9.3f}  "
          f"mean {np.nanmean(a):9.3f}  NaN {int(np.isnan(a).sum())}  shape {a.shape}")
    return a


# 2. Slope (degrees), checked against NumPy central differences
slope = save("slope_deg.tif", read(f"{BASE}/slope_margin.tif"), "deg")
gy, gx = np.gradient(dem, 1.0, 1.0)
slope_np = crop(np.degrees(np.arctan(np.hypot(gx, gy))))
print(f"  check: median |gdaldem - numpy| = {np.nanmedian(np.abs(slope - slope_np)):.2f} deg")
print(f"  cells with slope > 15 deg: {100 * np.nanmean(slope > 15):.1f} %")

# 3. Residual (fine detail): DEM minus its smoothed version
residual = dem - gaussian_filter(dem, sigma=5)
save("residual.tif", residual, "m")

# 4. Roughness: local standard deviation of the residual, 7 x 7 window
save("roughness.tif", local_std(residual, 7), "m")

# 5. TPI: DEM minus its local mean, 15 x 15 window
save("tpi.tif", dem - uniform_filter(dem, 15), "m")

# 6. Hillshade cropped (uint8, for display)
with rasterio.open(f"{BASE}/hillshade_margin.tif") as src:
    hs = src.read(1)
profile_u8 = profile.copy()
profile_u8.update(dtype="uint8", nodata=0)
with rasterio.open(f"{BASE}/hillshade.tif", "w", **profile_u8) as dst:
    dst.write(crop(hs), 1)
print("hillshade.tif    done")
