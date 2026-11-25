"""THEMIS night infrared over the box (P4, issue #44): thermal data from Mars Odyssey.

Source: one NASA Mars Trek tile of THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018,
zoom 9 (the deepest level), row 269, column 902: 256 x 256 px over 0.35 deg, about
81 m per pixel, and it covers the whole box (about 25 x 25 of its pixels). At night,
ground that holds heat (rock, high thermal inertia) is brighter than loose sand and
dust. The tile is an 8-bit display product (brightness, not temperature or inertia).

The check this layer was meant for, "does it confirm E8's sand?", answers no at this
scale: E8's sand patches (67-548 m2) are smaller than one THEMIS pixel (~6,600 m2),
and night brightness does not follow the sand fraction averaged per pixel (`check`).
It is context, not a cost term.

Release themis-v1 holds the tile; the downloaded kit's test tile is the same file.
"""

import io
import math
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image

R_MARS = 3_396_190.0
Z, ROW, COL = 9, 269, 902
TILE_W_DEG, TILE_H_DEG = 360 / 2 ** (Z + 1), 180 / 2 ** Z
TILE_WEST, TILE_NORTH = COL * TILE_W_DEG - 180, 90 - ROW * TILE_H_DEG
NAME = "THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018"
FILE = f"{NAME}__z{Z}_row{ROW}_col{COL}.png"
M_PER_PX = math.radians(TILE_W_DEG / 256) * R_MARS


def find(data_dir):
    data_dir = Path(data_dir)
    for p in (data_dir / "thermal" / FILE, data_dir / "04_mars_trek" / "teselas_prueba" / FILE):
        if p.exists():
            return p
    return None


def _tile(path):
    a = np.asarray(Image.open(path).convert("LA"))
    return a[..., 0].astype(float), a[..., 1] > 0


def _pixel_of(x, y):
    """THEMIS tile pixel (column, row) of DEM metres x, y (equirectangular sphere)."""
    lon, lat = np.degrees(np.asarray(x) / R_MARS), np.degrees(np.asarray(y) / R_MARS)
    return (np.floor((lon - TILE_WEST) / TILE_W_DEG * 256).astype(int),
            np.floor((TILE_NORTH - lat) / TILE_H_DEG * 256).astype(int))


def layer_png(path, bbox, size=500):
    """The tile over the box as a PNG (bbox: xmin, ymin, xmax, ymax in DEM metres).
    Interpolated smoothly (cubic) between the 81 m pixel centres, so the layer shows the
    broad warm/cool pattern instead of blocks; it adds no detail the data does not have.
    Colours: a warm sequential ramp (dark = cooler at night, bright = holds heat)."""
    from matplotlib import colormaps
    from scipy.ndimage import gaussian_filter, map_coordinates
    dn, ok = _tile(path)
    xmin, ymin, xmax, ymax = bbox
    xs = xmin + (np.arange(size) + 0.5) * (xmax - xmin) / size
    ys = ymax - (np.arange(size) + 0.5) * (ymax - ymin) / size
    X, Y = np.meshgrid(xs, ys)
    lon, lat = np.degrees(X / R_MARS), np.degrees(Y / R_MARS)
    # fractional pixel coordinates, pixel centres at integer + 0.5
    fx = (lon - TILE_WEST) / TILE_W_DEG * 256 - 0.5
    fy = (TILE_NORTH - lat) / TILE_H_DEG * 256 - 0.5
    v = map_coordinates(gaussian_filter(dn, 0.6), [fy, fx], order=3, mode="nearest")
    lo, hi = np.percentile(v, [2, 98])                     # stretch to the box's own range
    f = np.clip((v - lo) / max(hi - lo, 1), 0, 1)
    rgba = (colormaps["inferno"](0.15 + 0.8 * f) * 255).astype(np.uint8)
    rgba[..., 3] = np.where(map_coordinates(ok.astype(float), [fy, fx], order=0, mode="nearest") > 0, 200, 0)
    buf = io.BytesIO()
    Image.fromarray(rgba, "RGBA").save(buf, format="PNG", optimize=True)
    return buf.getvalue()


@lru_cache(maxsize=2)
def check(path, sand_tif, slope_tif):
    """Night brightness against E8's sand fraction and the slope, per THEMIS pixel
    fully inside the box. Spearman rank correlations; pixels are not independent
    (neighbours are alike), so the permutation p-value is optimistic."""
    dn, ok = _tile(path)
    with rasterio.open(sand_tif) as src:
        sand = src.read(1).astype(float); tr = src.transform
    with rasterio.open(slope_tif) as src:
        slope = src.read(1).astype(float)
    rows, cols = sand.shape
    xs = tr.c + (np.arange(cols) + 0.5) * tr.a
    ys = tr.f + (np.arange(rows) + 0.5) * tr.e
    px, _ = _pixel_of(xs, np.zeros_like(xs))
    _, py = _pixel_of(np.zeros_like(ys), ys)
    key = (py[:, None] * 256 + px[None, :]).ravel()
    s, sl = sand.ravel(), slope.ravel()
    good = ~np.isnan(s) & ~np.isnan(sl)
    n_all = np.bincount(key, minlength=65536)
    n = np.bincount(key[good], minlength=65536)
    sum_s = np.bincount(key[good], weights=s[good], minlength=65536)
    sum_sl = np.bincount(key[good], weights=sl[good], minlength=65536)
    full = (n_all >= 0.8 * M_PER_PX ** 2) & (n >= 0.8 * n_all) & ok.ravel()
    idx = np.nonzero(full)[0]
    b, fs, fsl = dn.ravel()[idx], sum_s[idx] / n[idx], sum_sl[idx] / n[idx]

    def rank(a):
        return np.argsort(np.argsort(a)).astype(float)

    def rho(u, v):
        return float(np.corrcoef(rank(u), rank(v))[0, 1])

    r_sand = rho(b, fs)
    rng = np.random.default_rng(0)
    perm = np.array([rho(rng.permutation(b), fs) for _ in range(500)])
    q1, q3 = np.quantile(fs, [0.25, 0.75])
    return {"pixels": int(len(idx)), "brightness_range": [float(b.min()), float(b.max())],
            "spearman_brightness_vs_sand": round(r_sand, 3),
            "spearman_brightness_vs_slope": round(rho(b, fsl), 3),
            "permutation_p_sand": round(float(np.mean(np.abs(perm) >= abs(r_sand))), 3),
            "brightness_sandiest_quarter": round(float(b[fs >= q3].mean()), 1),
            "brightness_least_sandy_quarter": round(float(b[fs <= q1].mean()), 1),
            "mean_sand_fraction": round(float(fs.mean()), 3)}


def summary(path, sand_tif=None, slope_tif=None):
    out = {"product": NAME, "instrument": "THEMIS (night IR)", "mission": "Mars Odyssey",
           "tile": {"z": Z, "row": ROW, "col": COL}, "m_per_px": round(M_PER_PX, 1),
           "notes": [f"{M_PER_PX:.0f} m pixels: the 2 × 2 km box is about 25 × 25 of them",
                     "8-bit display brightness, not a temperature: brighter at night = holds heat (rock)",
                     "Context only, not a cost term"]}
    if sand_tif and Path(sand_tif).exists() and slope_tif and Path(slope_tif).exists():
        c = check(str(path), str(sand_tif), str(slope_tif))
        out["check_vs_e8_sand"] = c
        out["notes"].append(
            f"Does it confirm E8's sand? No at this scale: rank correlation with the sand fraction "
            f"{c['spearman_brightness_vs_sand']:+.2f} over {c['pixels']} pixels (sand patches are smaller "
            f"than one pixel); with slope {c['spearman_brightness_vs_slope']:+.2f}")
    return out
