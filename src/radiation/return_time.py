"""E12 - Habitat input and the walking time back to it.

Team decision (board, 2026-11-14): the habitat is a USER INPUT, the same one E4
receives. E12 never picks its own: it takes --habitat X Y (metres, DEM CRS), or
the habitat point that comes inside the route file (the "start" point of /plan,
a "base" point, a point with type/tipo "habitat", or the habitat stop of an E5
tour GeoPackage). Without one it stops.

Return time R_T(v), the minimum walking time from v back to the habitat:
- official source: E4's rv_time_s.tif (Aaron, src/grafos/build_rv.py), passed
  with --return-raster;
- until it exists, a FALLBACK computed here with the same recipe: reverse Dijkstra
  from the habitat over the E3 time edges (fisica.edge_costs defaults: 20 deg per
  edge, cells > 30 deg blocked), the habitat snapped to the nearest cell of the
  largest strongly connected component (as E4 does). It is cached in
  data/e12/return_time_s_e12_fallback.tif with the habitat cell in its tags.
"""
import json
import sys
from pathlib import Path

import numpy as np
import rasterio
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import connected_components, dijkstra

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fisica.edge_cost import NEIGHBOURS, edge_costs  # noqa: E402
from radiation.common import BASE, E12_OUTPUT, pixel_coords  # noqa: E402

HABITAT_KINDS = {"start", "base", "habitat"}
FALLBACK_PATH = E12_OUTPUT / "return_time_s_e12_fallback.tif"


# ------------------------------------------------------------------- habitat

def habitat_from_features(fc):
    """(x, y, label) of the habitat point inside a FeatureCollection, or None."""
    for f in fc.get("features", []):
        if f["geometry"]["type"] != "Point":
            continue
        p = f.get("properties") or {}
        kind = str(p.get("kind", "")).lower()
        typ = str(p.get("type", p.get("tipo", ""))).lower()
        if kind in HABITAT_KINDS or typ == "habitat":
            x, y = f["geometry"]["coordinates"][:2]
            return float(x), float(y), f"route file point ({kind or typ})"
    return None


def resolve_habitat(habitat_arg, route_path=None):
    """The habitat (x, y) and where it came from. --habitat wins over the route file."""
    if habitat_arg is not None:
        x, y = habitat_arg
        return (float(x), float(y)), "--habitat"
    if route_path is not None:
        if Path(route_path).suffix.lower() == ".gpkg":       # E5 tour: the habitat stop
            import geopandas as gpd
            fc = json.loads(gpd.read_file(route_path, layer="stops").to_json())
        else:
            fc = json.loads(Path(route_path).read_text(encoding="utf-8"))
        found = habitat_from_features(fc)
        if found:
            return (found[0], found[1]), found[2]
    raise SystemExit("No habitat given. The habitat is a user input (the same one E4 uses): pass "
                     "--habitat X Y in DEM metres, or a route file with a 'start'/'base'/'habitat' point.")


# --------------------------------------------------------------- return time

def time_graph(time_s):
    """Forward graph (CSR) of the E3 time edges: node = row * cols + col."""
    _, rows, cols = time_s.shape
    idx = np.arange(rows * cols, dtype=np.int64).reshape(rows, cols)
    src, dst, data = [], [], []
    for k, (dr, dc) in enumerate(NEIGHBOURS):
        ok = np.isfinite(time_s[k])
        r, c = np.nonzero(ok)
        src.append(idx[r, c])
        dst.append(idx[r + dr, c + dc])
        data.append(time_s[k][ok].astype(np.float64))
    n = rows * cols
    return csr_matrix((np.concatenate(data), (np.concatenate(src), np.concatenate(dst))), shape=(n, n))


def main_component(graph, shape):
    """Boolean grid: cells in the largest strongly connected component."""
    _, labels = connected_components(graph, directed=True, connection="strong")
    counts = np.bincount(labels)
    return (labels == int(np.argmax(counts))).reshape(shape)


def snap(mask, row, col):
    """The cell itself if it is in mask, else the nearest cell that is."""
    if 0 <= row < mask.shape[0] and 0 <= col < mask.shape[1] and mask[row, col]:
        return row, col, 0.0
    rr, cc = np.nonzero(mask)
    k = int(np.argmin((rr - row) ** 2 + (cc - col) ** 2))
    return int(rr[k]), int(cc[k]), float(np.hypot(rr[k] - row, cc[k] - col))


def habitat_cell(transform, x, y):
    col, row = pixel_coords(~transform, x, y)
    return int(np.floor(row)), int(np.floor(col))


def fallback_return_time(dem_path, slope_path, habitat_xy):
    """E12's provisional R_T (s, float32, NaN = cannot reach the habitat), profile, info."""
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float64)
        profile = src.profile
        transform = src.transform
    with rasterio.open(slope_path) as src:
        slope = src.read(1).astype(np.float64)
    time_s, _, _ = edge_costs(dem, abs(transform.a), cell_slope_deg=slope)
    graph = time_graph(time_s)
    mask = main_component(graph, dem.shape)
    r0, c0 = habitat_cell(transform, *habitat_xy)
    hr, hc, moved = snap(mask, r0, c0)
    dist = dijkstra(graph.T.tocsr(), directed=True, indices=hr * dem.shape[1] + hc)
    out = dist.reshape(dem.shape).astype(np.float32)
    out[~np.isfinite(out)] = np.nan
    profile.update(dtype="float32", nodata=np.nan, count=1, compress="deflate")
    info = {"source": "E12 fallback (provisional, until E4 rv_time_s.tif)",
            "habitat_xy": [round(habitat_xy[0], 3), round(habitat_xy[1], 3)],
            "habitat_cell_row_col": [hr, hc], "habitat_input_cell_row_col": [r0, c0],
            "habitat_snapped_cells": round(moved, 2),
            "main_component_share": round(float(mask.mean()), 4),
            "weights": "E3 edge time_s, fisica.edge_cost defaults (20 deg edge, 30 deg cell block)"}
    return out, profile, info


def return_time_for(habitat_xy, return_raster=None, dem_path=BASE / "dem_1m.tif",
                    slope_path=BASE / "slope_deg.tif", cache_path=FALLBACK_PATH):
    """(path of the R_T raster to use, info). E4's raster if given, else the cached fallback."""
    if return_raster is not None:
        return Path(return_raster), {"source": "E4 rv_time_s.tif (--return-raster)",
                                     "file": str(return_raster),
                                     "habitat_xy": [round(habitat_xy[0], 3), round(habitat_xy[1], 3)]}
    cache_path = Path(cache_path)
    if cache_path.exists():
        with rasterio.open(cache_path) as src:
            tags = src.tags()
        if tags.get("habitat_xy") == json.dumps([round(habitat_xy[0], 3), round(habitat_xy[1], 3)]):
            return cache_path, json.loads(tags["info"])
    out, profile, info = fallback_return_time(dem_path, slope_path, habitat_xy)
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    with rasterio.open(cache_path, "w", **profile) as dst:
        dst.write(out, 1)
        dst.update_tags(habitat_xy=json.dumps(info["habitat_xy"]), info=json.dumps(info))
    finite = out[np.isfinite(out)]
    info.update({"file": "data/e12/" + cache_path.name,
                 "reachable_share_of_grid": round(float(finite.size / out.size), 4),
                 "median_h": round(float(np.median(finite)) / 3600, 3),
                 "p95_h": round(float(np.percentile(finite, 95)) / 3600, 3),
                 "max_h": round(float(finite.max()) / 3600, 3)})
    with rasterio.open(cache_path, "r+") as dst:
        dst.update_tags(info=json.dumps(info))
    return cache_path, info
