"""E12: habitat as an input, return time to it, and routes on E3 edges."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fisica.edge_cost import NEIGHBOURS, edge_costs  # noqa: E402
from radiation.return_time import (fallback_return_time, resolve_habitat,  # noqa: E402
                                   return_time_for)
from radiation.route_dose import DoseRate, route_steps, route_timeline, walk  # noqa: E402


def write_raster(path, a):
    with rasterio.open(path, "w", driver="GTiff", width=a.shape[1], height=a.shape[0], count=1,
                       dtype="float32", transform=from_origin(0.0, float(a.shape[0]), 1.0, 1.0),
                       nodata=np.nan) as dst:
        dst.write(a.astype("float32"), 1)
    return path


def centre(row, col, size):
    """Map coordinates of the centre of (row, col) on a size x size 1 m grid with origin (0, size)."""
    return col + 0.5, size - (row + 0.5)


# ------------------------------------------------------------------- habitat

def test_habitat_argument_wins(tmp_path):
    route = tmp_path / "r.geojson"
    route.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [5.0, 6.0]},
         "properties": {"kind": "start"}}]}), encoding="utf-8")
    assert resolve_habitat((1.0, 2.0), route) == ((1.0, 2.0), "--habitat")
    assert resolve_habitat(None, route) == ((5.0, 6.0), "route file point (start)")


def test_habitat_from_tipo_column_and_missing(tmp_path):
    route = tmp_path / "r.geojson"
    route.write_text(json.dumps({"type": "FeatureCollection", "features": [
        {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
         "properties": {}},
        {"type": "Feature", "geometry": {"type": "Point", "coordinates": [3.0, 4.0]},
         "properties": {"tipo": "habitat"}}]}), encoding="utf-8")
    assert resolve_habitat(None, route)[0] == (3.0, 4.0)
    empty = tmp_path / "e.geojson"
    empty.write_text(json.dumps({"type": "FeatureCollection", "features": []}), encoding="utf-8")
    with pytest.raises(SystemExit):
        resolve_habitat(None, empty)


# --------------------------------------------------------------- return time

def test_fallback_return_time_flat_and_snap(tmp_path):
    size = 40
    dem = write_raster(tmp_path / "dem.tif", np.zeros((size, size)))
    slope = np.zeros((size, size))
    slope[5:12, 5:12] = 45.0                 # blocked ring...
    slope[7:10, 7:10] = 0.0                  # ...around a 3 x 3 island
    slope_path = write_raster(tmp_path / "slope.tif", slope)

    hab = centre(20, 20, size)
    rt, _, info = fallback_return_time(dem, slope_path, hab)
    assert info["habitat_cell_row_col"] == [20, 20] and info["habitat_snapped_cells"] == 0
    assert rt[20, 20] == pytest.approx(0.0)
    assert rt[20, 30] == pytest.approx(10 / 0.75, rel=1e-5)      # 10 m flat, Apollo speed
    assert np.isnan(rt[8, 8])                                     # the island cannot reach the habitat

    rt2, _, info2 = fallback_return_time(dem, slope_path, centre(8, 8, size))   # habitat on the island
    assert info2["habitat_snapped_cells"] > 0
    r, c = info2["habitat_cell_row_col"]
    assert not (7 <= r < 10 and 7 <= c < 10)                      # moved to the main component
    assert rt2[r, c] == pytest.approx(0.0)


def test_return_time_for_caches_and_prefers_e4(tmp_path):
    size = 20
    dem = write_raster(tmp_path / "dem.tif", np.zeros((size, size)))
    slope = write_raster(tmp_path / "slope.tif", np.zeros((size, size)))
    cache = tmp_path / "fallback.tif"
    hab = centre(10, 10, size)
    p1, info1 = return_time_for(hab, None, dem, slope, cache)
    assert p1 == cache and info1["source"].startswith("E12 fallback")
    mtime = cache.stat().st_mtime_ns
    p2, info2 = return_time_for(hab, None, dem, slope, cache)
    assert cache.stat().st_mtime_ns == mtime and info2["habitat_cell_row_col"] == [10, 10]
    e4 = write_raster(tmp_path / "rv_time_s.tif", np.ones((size, size)))
    p3, info3 = return_time_for(hab, e4, dem, slope, cache)
    assert p3 == e4 and info3["source"].startswith("E4")


# ---------------------------------------------------------- routes on E3 edges

def test_cell_chain_uses_exact_e3_edges(tmp_path):
    size = 30
    rng = np.random.default_rng(0)
    z = np.cumsum(rng.normal(0, 0.05, (size, size)), axis=1)      # gentle random relief
    dem = write_raster(tmp_path / "dem.tif", z)
    cells = [(15, 3), (15, 4), (14, 5), (13, 6), (13, 7), (14, 8), (15, 8), (16, 9)]
    xy = np.array([centre(r, c, size) for r, c in cells])
    st = route_steps(xy, dem)
    assert st["method"] == "e3_edges"
    w = walk(st["points"], st["d_h"], st["alpha"])
    time_s, energy_j, _ = edge_costs(z.astype(np.float32).astype(np.float64), 1.0)
    k_of = {d: k for k, d in enumerate(NEIGHBOURS)}
    t_ref = sum(time_s[k_of[(r2 - r1, c2 - c1)], r1, c1] for (r1, c1), (r2, c2) in zip(cells, cells[1:]))
    e_ref = sum(energy_j[k_of[(r2 - r1, c2 - c1)], r1, c1] for (r1, c1), (r2, c2) in zip(cells, cells[1:]))
    assert w["walk_s"][-1] == pytest.approx(float(t_ref), rel=1e-5)
    assert w["energy_j"][-1] == pytest.approx(float(e_ref), rel=1e-5)


def test_free_line_is_resampled(tmp_path):
    size = 30
    dem = write_raster(tmp_path / "dem.tif", np.zeros((size, size)))
    st = route_steps(np.array([[3.2, 15.1], [20.7, 15.1]]), dem)
    assert st["method"].startswith("resampled")
    jump = np.array([centre(15, 3, size), centre(15, 6, size)])  # cell centres but not neighbours
    assert route_steps(jump, dem)["method"].startswith("resampled")


def test_timeline_reads_return_raster(tmp_path):
    size = 30
    dem = write_raster(tmp_path / "dem.tif", np.zeros((size, size)))
    rt = np.arange(size * size, dtype=float).reshape(size, size)
    ret = write_raster(tmp_path / "rt.tif", rt)
    xy = np.array([centre(15, 3, size), centre(15, 4, size), centre(15, 5, size)])
    tl = route_timeline(xy, dem, DoseRate.constant(144.0), return_raster=ret)
    assert list(tl["return_s"]) == [rt[15, 3], rt[15, 4], rt[15, 5]]
    assert tl.attrs["method"] == "e3_edges"
