"""E2 (hours 4-12): cell x feature table around Curiosity's route.

For every cell near the route it stores the terrain features from JB's base
grid, whether the rover went through it, how far it is from the route and the
route position of the nearest visited cell (used to split the route into
consecutive blocks for validation).

Which cells are in the table:
  - visited cells: the cells in data/e2/trajectory_cells.csv (dist_to_route_m = 0);
  - not visited cells: cells with MIN_GAP_M <= distance to the route <= MAX_CORRIDOR_M.
    Cells closer than MIN_GAP_M are left out: the rover is about 3 m wide, so the
    cells right next to the route line were driven over too.
Smaller corridors (25 m, 50 m) are filters on dist_to_route_m.

Features (no position, elevation or distance: those would let a model guess by
location instead of by terrain):
  slope_deg, roughness, tpi   JB's layers at 1 m
  slope_mean_5m, slope_mean_15m   mean slope in a 5 x 5 and 15 x 15 m window
                                  (planners avoid areas, not single cells)

Input:  data/base/{dem_1m,slope_deg,roughness,tpi}.tif, data/e2/trajectory_cells.csv
Output: data/e2/cell_features.parquet

Usage:  python src/ml/cell_features.py   (after trajectory_to_grid.py)
"""
import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import distance_transform_edt, uniform_filter

import common

MIN_GAP_M = 2.0
MAX_CORRIDOR_M = 100.0
N_BLOCKS = 5
FEATURES = ["slope_deg", "roughness", "tpi", "slope_mean_5m", "slope_mean_15m"]


def read_layer(name):
    with rasterio.open(common.base_layer(name)) as src:
        return src.read(1).astype("float64"), src.transform


def feature_rasters():
    """Dict name -> 2000 x 2000 array, plus the grid transform."""
    slope, t = read_layer("slope_deg.tif")
    layers = {
        "slope_deg": slope,
        "roughness": read_layer("roughness.tif")[0],
        "tpi": read_layer("tpi.tif")[0],
        # mode="nearest" repeats the edge cells: only the outer 7 m of the box are affected.
        "slope_mean_5m": uniform_filter(slope, size=5, mode="nearest"),
        "slope_mean_15m": uniform_filter(slope, size=15, mode="nearest"),
    }
    return layers, t


def route_rasters(shape):
    """Visited mask, distance to the route (m), and route position / sol / block of the nearest visited cell."""
    cells = pd.read_csv(common.E2_OUTPUT / "trajectory_cells.csv")
    visited = np.zeros(shape, bool)
    visited[cells.row, cells.col] = True
    route_pos = np.full(shape, -1, np.int64)
    route_pos[cells.row, cells.col] = cells.first_step
    sol = np.zeros(shape, np.int64)
    sol[cells.row, cells.col] = cells.sol_min

    # Distance from every cell centre to the nearest visited cell centre (cells are 1 m).
    dist, (ir, ic) = distance_transform_edt(~visited, return_indices=True)
    nearest_pos = route_pos[ir, ic]
    nearest_sol = sol[ir, ic]
    # N_BLOCKS consecutive stretches of the route with the same number of visited cells.
    edges = np.quantile(cells.first_step, np.linspace(0, 1, N_BLOCKS + 1)[1:-1])
    block = np.searchsorted(edges, nearest_pos, side="right")
    return visited, dist, nearest_pos, nearest_sol, block


def build_table(max_dist_m=MAX_CORRIDOR_M):
    """Cell table for visited cells plus not visited cells within [MIN_GAP_M, max_dist_m] (None = whole box)."""
    layers, t = feature_rasters()
    shape = layers["slope_deg"].shape
    visited, dist, nearest_pos, nearest_sol, block = route_rasters(shape)
    keep = visited | (dist >= MIN_GAP_M)
    if max_dist_m is not None:
        keep &= dist <= max_dist_m
    r, c = np.nonzero(keep)
    table = pd.DataFrame({
        "row": r.astype(np.int32), "col": c.astype(np.int32),
        "x": t.c + (c + 0.5) * t.a, "y": t.f + (r + 0.5) * t.e,
    })
    for name in FEATURES:
        table[name] = layers[name][r, c].astype("float32")
    table["visited"] = visited[r, c].astype(np.int8)
    table["dist_to_route_m"] = dist[r, c].astype("float32")
    table["route_pos"] = nearest_pos[r, c].astype(np.int32)
    table["sol"] = nearest_sol[r, c].astype(np.int32)
    table["block"] = block[r, c].astype(np.int8)
    if table[FEATURES].isna().any().any():
        raise SystemExit("Some features are NaN inside the table")
    return table


def main():
    table = build_table()
    out = common.E2_OUTPUT / "cell_features.parquet"
    table.to_parquet(out, index=False)
    vis = table.visited == 1
    print(out)
    print(f"  {len(table):,} cells: {vis.sum():,} visited, {(~vis).sum():,} not visited "
          f"({MIN_GAP_M:g}-{MAX_CORRIDOR_M:g} m from the route)")
    for d in (25, 50, 100):
        print(f"  corridor {d:>3} m: {((table.dist_to_route_m <= d) & ~vis).sum():,} not visited cells")
    print("  visited cells per block:", table[vis].groupby("block").size().to_dict())
    print("  medians, visited vs not visited (50 m corridor):")
    sub = table[vis | (table.dist_to_route_m <= 50)]
    print(sub.groupby("visited")[FEATURES].median().round(2).to_string())


if __name__ == "__main__":
    main()
