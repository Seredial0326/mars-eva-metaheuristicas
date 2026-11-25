"""Summary numbers and paper figures for the base grid (issue #3, paper/notes/base_grid.md).

Run from the data/ folder:  python ../src/gis/paper_figures.py
Writes base/summary.json and ../paper/figures/grid_fig1..4.png
"""
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.patches import Rectangle
from rasterio.enums import Resampling
from rasterio.windows import Window, from_bounds

FIG = Path("../paper/figures")
FIG.mkdir(parents=True, exist_ok=True)
RAW_DEM = Path("01_terreno/dem_gale_1m/MSL_Gale_DEM_Mosaic_1m_v3.tif")
PLACES = Path("03_curiosity/places_pds/data_localizations/localized_interp.csv")
CONTEXT_M = 12000  # side of the context window
ZOOM = (875, 875, 250)  # row0, col0, size in 1 m cells for the detail figure


def read(path):
    with rasterio.open(path) as src:
        return src.read(1, masked=True).filled(np.nan).astype("float32"), src.transform


def hillshade(z, cell, azimuth=315.0, altitude=45.0):
    gy, gx = np.gradient(z, cell)
    slope = np.arctan(np.hypot(gx, gy))
    aspect = np.arctan2(-gy, -gx)
    az, alt = np.radians(360.0 - azimuth + 90.0), np.radians(altitude)
    return np.clip(np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect), 0, 1)


def stats(a):
    return {"min": round(float(np.nanmin(a)), 3), "max": round(float(np.nanmax(a)), 3),
            "mean": round(float(np.nanmean(a)), 3), "median": round(float(np.nanmedian(a)), 3),
            "std": round(float(np.nanstd(a)), 3)}


def pct_above(a, t):
    return round(100 * float(np.nanmean(a > t)), 3)


dem, T = read("base/dem_1m.tif")
slope, _ = read("base/slope_deg.tif")
residual, _ = read("base/residual.tif")
roughness, _ = read("base/roughness.tif")
tpi, _ = read("base/tpi.tif")
h, w = dem.shape
xmin, ymax = T.c, T.f
xmax, ymin = xmin + T.a * w, ymax + T.e * h
km = (0, (xmax - xmin) / 1000, 0, (ymax - ymin) / 1000)

# --- checks and summary numbers ---------------------------------------------------------
with rasterio.open("base/dem_1m.tif") as d, rasterio.open("base/ortho_color_025.tif") as oc, \
        rasterio.open("base/ortho_gray_025.tif") as og:
    checks = {
        "same_origin": d.transform.c == oc.transform.c == og.transform.c and d.transform.f == oc.transform.f == og.transform.f,
        "ortho_is_4x": oc.width == 4 * d.width and oc.height == 4 * d.height and og.width == 4 * d.width,
        "same_crs": d.crs == oc.crs == og.crs,
        "dem_nan_cells": int(np.isnan(dem).sum()),
    }
    gray = og.read(1)
    luminance = oc.read().astype("float32").mean(0)
valid = gray > 0
corr = float(np.corrcoef(gray[valid][::50].astype("float32"), luminance[valid][::50])[0, 1])
gy, gx = np.gradient(dem, 1.0)
slope_np = np.degrees(np.arctan(np.hypot(gx, gy)))[1:-1, 1:-1]

summary = {
    "bbox_m": {"xmin": xmin, "ymin": ymin, "xmax": xmax, "ymax": ymax},
    "grid": {"width": w, "height": h, "cell_m": T.a},
    "checks": checks,
    "dem_elevation_m": stats(dem),
    "ortho_gray": {"zero_pct": round(100 * float(np.mean(gray == 0)), 4), "corr_with_color": round(corr, 3)},
    "slope_deg": stats(slope) | {f"pct_above_{t}": pct_above(slope, t) for t in (15, 30, 45, 60, 70)},
    "slope_check_median_abs_diff_deg": round(float(np.nanmedian(np.abs(slope[1:-1, 1:-1] - slope_np))), 3),
    "residual_m": stats(residual) | {"pct_abs_above_3m": round(100 * float(np.nanmean(np.abs(residual) > 3)), 3)},
    "roughness_m": stats(roughness),
    "tpi_m": stats(tpi),
    "tiles": {name: sum(1 for _ in Path(f"tiles/{name}").rglob("*.png")) for name in ("ortho", "slope", "hillshade")},
}
Path("base/summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))

# --- fig 1: context (12 x 12 km of Gale, full Curiosity route, our bbox) ---------------
cx, cy = (xmin + xmax) / 2, (ymin + ymax) / 2
half = CONTEXT_M / 2
n = 1200
with rasterio.open(RAW_DEM) as src:
    win = from_bounds(cx - half, cy - half, cx + half, cy + half, src.transform)
    ctx = src.read(1, window=win, out_shape=(n, n), resampling=Resampling.average, masked=True)
ctx = ctx.filled(np.nan).astype("float32")
poses = pd.read_csv(PLACES, usecols=["frame", "easting", "northing", "sol"])
poses = poses[poses["frame"] == "ROVER"]
near = poses[(abs(poses.easting - cx) < half) & (abs(poses.northing - cy) < half)]
inside = near[(near.easting >= xmin) & (near.easting <= xmax) & (near.northing >= ymin) & (near.northing <= ymax)]
fig, ax = plt.subplots(figsize=(7, 7))
ext = (-half / 1000, half / 1000, -half / 1000, half / 1000)
ax.imshow(hillshade(np.nan_to_num(ctx, nan=np.nanmean(ctx)), CONTEXT_M / n), cmap="gray", extent=ext)
ax.plot((near.easting - cx) / 1000, (near.northing - cy) / 1000, ".", ms=0.6, color="#ff7f00", label="Curiosity (PLACES)")
ax.plot((inside.easting - cx) / 1000, (inside.northing - cy) / 1000, ".", ms=0.6, color="#e41a1c",
        label=f"inside bbox (sols {inside.sol.min()}-{inside.sol.max()})")
ax.add_patch(Rectangle(((xmin - cx) / 1000, (ymin - cy) / 1000), (xmax - xmin) / 1000, (ymax - ymin) / 1000,
                       fill=False, ec="#377eb8", lw=2, label="2 x 2 km bbox"))
ax.set_xlabel("km east of bbox centre")
ax.set_ylabel("km north of bbox centre")
ax.legend(loc="lower left", markerscale=12, fontsize=8)
ax.set_title("Base grid in context (Gale DEM v3, hillshade)")
fig.tight_layout()
fig.savefig(FIG / "grid_fig1_context.png", dpi=200)

# --- fig 2: the four features ------------------------------------------------------------
fig, axes = plt.subplots(2, 2, figsize=(11, 10))
panels = [(slope, "slope (deg)", "RdYlGn_r", 0, 45), (residual, "residual (m)", "RdBu_r", -2, 2),
          (roughness, "roughness (m)", "viridis", 0, 1), (tpi, "TPI (m)", "RdBu_r", -3, 3)]
for ax, (a, title, cmap, lo, hi) in zip(axes.flat, panels):
    im = ax.imshow(a, cmap=cmap, vmin=lo, vmax=hi, extent=km)
    ax.set_title(title)
    ax.set_xlabel("km")
    fig.colorbar(im, ax=ax, shrink=0.8)
fig.tight_layout()
fig.savefig(FIG / "grid_fig2_features.png", dpi=200)

# --- fig 3: slope distribution -------------------------------------------------------------
fig, ax = plt.subplots(figsize=(7, 4))
ax.hist(slope[np.isfinite(slope)].ravel(), bins=np.arange(0, 81, 1), color="#636363",
        weights=np.full(int(np.isfinite(slope).sum()), 100 / np.isfinite(slope).sum()))
for t in (15, 30, 45):
    ax.axvline(t, color="#e41a1c", lw=1, ls="--")
    ax.text(t + 0.5, ax.get_ylim()[1] * 0.9, f"> {t} deg: {pct_above(slope, t):.1f} %", fontsize=8, color="#e41a1c")
ax.set_xlabel("slope (deg), 1 m cells")
ax.set_ylabel("% of cells")
ax.set_title("Slope distribution in the 2 x 2 km bbox")
fig.tight_layout()
fig.savefig(FIG / "grid_fig3_slope_hist.png", dpi=200)

# --- fig 4: 250 m detail: orthophoto, hillshade, residual ----------------------------------
r0, c0, size = ZOOM
with rasterio.open("base/ortho_color_025.tif") as src:
    ortho = src.read(window=Window(c0 * 4, r0 * 4, size * 4, size * 4)).transpose(1, 2, 0)
with rasterio.open("base/hillshade.tif") as src:
    hs = src.read(1, window=Window(c0, r0, size, size))
zext = (0, size, 0, size)
fig, axes = plt.subplots(1, 3, figsize=(15, 5.3))
axes[0].imshow(ortho, extent=zext)
axes[0].set_title("HiRISE orthophoto (0.25 m)")
axes[1].imshow(hs, cmap="gray", extent=zext)
axes[1].set_title("DEM hillshade (1 m)")
im = axes[2].imshow(residual[r0:r0 + size, c0:c0 + size], cmap="RdBu_r", vmin=-2, vmax=2, extent=zext)
axes[2].set_title("residual (m): ridges red, hollows blue")
fig.colorbar(im, ax=axes[2], shrink=0.8)
for ax in axes:
    ax.set_xlabel("m")
fig.tight_layout()
fig.savefig(FIG / "grid_fig4_detail.png", dpi=200)
print("figures saved in paper/figures/grid_fig1..4")
