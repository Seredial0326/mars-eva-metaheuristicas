"""Task-based evaluation of E8 with Curiosity's real route (issue #11). No hand labels.

Question: do the E8 layers explain where the rover actually drove, better than the DEM
features (E2 found DEM features at chance inside the boxwork: AUC about 0.5)?
For each layer, compare the cells the rover drove over with the cells it could have
taken (2-50 m from the route), per route block, as E2 does:
  AUC_avoid = probability that a driven cell has a LOWER value than an alternative cell.
  0.5 = no information; > 0.5 = the rover avoided high values; < 0.5 = it preferred them.
Also reports simple morphometrics of the predicted sand patches.

Run from the data/ folder:
  python ../src/dl_boxwork/eval_with_rover.py   -> e8/rover_eval.json
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import binary_dilation, distance_transform_edt, label
from scipy.stats import mannwhitneyu

OUT = Path("e8")
PLACES = Path("03_curiosity/places_pds/data_localizations/localized_interp.csv")
BOXWORK_SOLS = (4541, 4848)  # provisional range (data/README.md)
LAYERS = {"sand (E8)": OUT / "sand.tif", "ridge (E8)": OUT / "ridge.tif",
          "slope_deg (DEM)": Path("base/slope_deg.tif"), "roughness (DEM)": Path("base/roughness.tif")}

with rasterio.open("base/dem_1m.tif") as dem:
    T, H, W = dem.transform, dem.height, dem.width
layers = {}
for name, path in LAYERS.items():
    with rasterio.open(path) as src:
        layers[name] = src.read(1).astype("float32")

# Route cells: ROVER poses in file order, segments densified every 0.25 m (gaps > 10 m not joined)
p = pd.read_csv(PLACES, usecols=["frame", "easting", "northing", "sol"])
p = p[p.frame == "ROVER"].reset_index(drop=True)
x, y, sol = p.easting.to_numpy(), p.northing.to_numpy(), p.sol.to_numpy()
pts = []
for i in range(len(x) - 1):
    d = np.hypot(x[i + 1] - x[i], y[i + 1] - y[i])
    k = max(1, int(d / 0.25)) if d <= 10 else 1
    t = np.linspace(0, 1, k, endpoint=False)
    pts.append(np.c_[x[i] + t * (x[i + 1] - x[i]), y[i] + t * (y[i + 1] - y[i]), np.full(k, sol[i])])
pts = np.vstack(pts)
col = np.floor((pts[:, 0] - T.c) / T.a).astype(int)
row = np.floor((pts[:, 1] - T.f) / T.e).astype(int)
inside = (row >= 0) & (row < H) & (col >= 0) & (col < W)
row, col, psol = row[inside], col[inside], pts[inside, 2]

sol_grid = np.zeros((H, W), "float32")
visited = np.zeros((H, W), bool)
visited[row, col] = True
sol_grid[row, col] = psol
visited = binary_dilation(visited, structure=np.ones((3, 3)))  # rover is about 3 m wide
dist, (ir, ic) = distance_transform_edt(~visited, return_indices=True)
# sol of the nearest driven pose for every cell (to split by route block)
seed = np.zeros((H, W), bool)
seed[row, col] = True
_, (sr, sc) = distance_transform_edt(~seed, return_indices=True)
cell_sol = sol_grid[sr, sc]
corridor = (dist > 2) & (dist <= 50)

sols = np.sort(psol)
edges = np.quantile(sols, np.linspace(0, 1, 6))  # 5 blocks with equal numbers of route samples


def auc_avoid(v_drive, v_alt):
    v_drive, v_alt = v_drive[np.isfinite(v_drive)], v_alt[np.isfinite(v_alt)]
    if len(v_drive) < 20 or len(v_alt) < 20:
        return None
    u = mannwhitneyu(v_alt, v_drive, alternative="two-sided").statistic  # alt > drive counts
    return round(float(u / (len(v_drive) * len(v_alt))), 3)


def evaluate(mask_extra):
    res = {}
    for name, a in layers.items():
        per_block = []
        for b in range(5):
            in_b = (cell_sol >= edges[b]) & (cell_sol <= edges[b + 1]) & mask_extra
            per_block.append(auc_avoid(a[visited & in_b], a[corridor & in_b]))
        ok = [v for v in per_block if v is not None]
        res[name] = {"auc_avoid_mean": round(float(np.mean(ok)), 3) if ok else None, "per_block": per_block,
                     "mean_driven": round(float(np.nanmean(a[visited & mask_extra])), 4) if (visited & mask_extra).any() else None,
                     "mean_alternatives": round(float(np.nanmean(a[corridor & mask_extra])), 4) if (corridor & mask_extra).any() else None}
    return res


everything = np.ones((H, W), bool)
boxwork = (cell_sol >= BOXWORK_SOLS[0]) & (cell_sol <= BOXWORK_SOLS[1])
sws = np.zeros((H, W), bool)
sws[1500:, :1000] = True  # SW-S (held out from E8 training) on the 1 m grid

# Morphometrics of predicted sand patches (0.25 m map)
with rasterio.open(OUT / "pred_classes_025.tif") as src:
    cls = src.read(1)
lab, n = label(cls == 2, structure=np.ones((3, 3)))
areas = np.bincount(lab.ravel())[1:] * 0.0625  # m2
areas = areas[areas >= 1]
result = {
    "route_blocks_sol_edges": [round(float(e)) for e in edges],
    "driven_cells": int(visited.sum()), "alternative_cells_2_50m": int(corridor.sum()),
    "whole_route": evaluate(everything),
    "boxwork_sols_only": evaluate(boxwork),
    "SW-S_only (held out from training)": evaluate(sws),
    "sand_patch_area_m2": {"n": int(len(areas)),
                           "median": round(float(np.median(areas)), 1) if len(areas) else None,
                           "p90": round(float(np.percentile(areas, 90)), 1) if len(areas) else None},
    "reading": "auc_avoid 0.5 = no information; E2 found DEM features near 0.5 inside the boxwork",
}
(OUT / "rover_eval.json").write_text(json.dumps(result, indent=2))
print(json.dumps(result, indent=2))
