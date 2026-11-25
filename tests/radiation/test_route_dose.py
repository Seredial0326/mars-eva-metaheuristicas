"""E12: timeline and dose along a route, against hand-computed values."""

import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fisica.metabolic import G_EARTH, G_MARS, G_MOON, TOTAL_MASS_KG, segment_cost  # noqa: E402
from radiation.route_dose import (DoseRate, load_route, out_and_back, resample_line,  # noqa: E402
                                  route_steps, route_timeline, sample_raster, step_costs, walk)
from radiation.sensitivity import budget_limited  # noqa: E402


def make_dem(tmp_path, slope_deg=0.0, size=200):
    """size x size raster of 1 m cells, elevation rising eastwards at slope_deg."""
    cols = np.arange(size) + 0.5
    z = np.tile(np.tan(np.radians(slope_deg)) * cols, (size, 1)).astype("float32")
    path = tmp_path / "dem.tif"
    with rasterio.open(path, "w", driver="GTiff", width=size, height=size, count=1, dtype="float32",
                       transform=from_origin(0.0, float(size), 1.0, 1.0), nodata=np.nan) as dst:
        dst.write(z, 1)
    return path


def steps(dem, xy, step_m=1.0):
    st = route_steps(np.asarray(xy, dtype=float), dem, step_m)
    return st["points"], st["d_h"], st["alpha"]


def test_step_costs_match_e3_segment_cost():
    for alpha in (-15.0, -3.0, 0.0, 4.0, 12.0):
        dt, e = step_costs(np.array([1.0]), np.array([alpha]))
        dt_ref, e_ref = segment_cost(1.0, alpha, TOTAL_MASS_KG, G_MARS)
        assert dt[0] == pytest.approx(dt_ref) and e[0] == pytest.approx(e_ref)


def test_resample_keeps_length_and_ends():
    xy = np.array([[0, 0], [10, 0], [10, 0], [10, 5.5]], dtype=float)   # repeated vertex
    pts, s = resample_line(xy, 1.0)
    assert s[-1] == pytest.approx(15.5)
    assert np.allclose(pts[0], [0, 0]) and np.allclose(pts[-1], [10, 5.5])
    assert np.all(np.diff(s) <= 1.0 + 1e-9)


def test_bilinear_dem_sampling(tmp_path):
    dem = make_dem(tmp_path, slope_deg=10.0)
    z = sample_raster(dem, np.array([[50.25, 100.0], [0.1, 100.0], [-5.0, 100.0]]))
    assert z[0] == pytest.approx(np.tan(np.radians(10.0)) * 50.25, rel=1e-6)
    assert np.isfinite(z[1])                      # within half a cell of the border
    assert np.isnan(z[2])                         # outside


def test_flat_route_time_and_constant_dose(tmp_path):
    dem = make_dem(tmp_path, 0.0)
    xy = np.array([[10.0, 100.0], [110.0, 100.0]])
    rate = DoseRate.constant(144.0)               # 6 uGy/h
    tl = route_timeline(xy, dem, rate)
    t = 100.0 / 0.75                              # Apollo speed on flat ground
    assert tl["t_s"].iloc[-1] == pytest.approx(t)
    assert tl["dose_ugy"].iloc[-1] == pytest.approx(6.0 * t / 3600)
    assert tl["rate_ugy_h"].iloc[0] == pytest.approx(6.0)


def test_stations_add_dwell_and_dose(tmp_path):
    dem = make_dem(tmp_path, 0.0)
    xy = np.array([[10.0, 100.0], [110.0, 100.0]])
    stations = [{"id": "s1", "x": 60.2, "y": 101.0, "service_time_min": 30.0}]
    rate = DoseRate.constant(144.0)
    tl = route_timeline(xy, dem, rate, stations=stations)
    assert tl["dwell_s"].sum() == pytest.approx(1800.0)
    assert tl["dwell_s"].idxmax() == 50
    assert tl["t_s"].iloc[-1] == pytest.approx(100 / 0.75 + 1800)
    assert tl["walk_s"].iloc[-1] == pytest.approx(100 / 0.75)


def test_ordered_stations_dwell_on_the_visit(tmp_path):
    # out along y = 100.5 and back; A sits on the outbound path but is visited on the way back, after B
    dem = make_dem(tmp_path, 0.0)
    xs = np.arange(10.5, 61.0)
    xy = out_and_back(np.column_stack([xs, np.full_like(xs, 100.5)]))
    a = {"id": "A", "x": 20.5, "y": 100.5, "service_time_min": 10.0}
    b = {"id": "B", "x": 60.5, "y": 100.5, "service_time_min": 10.0}
    plain = route_timeline(xy, dem, DoseRate.constant(144.0), stations=[a, b])
    assert plain["dwell_s"].to_numpy().nonzero()[0].tolist() == [10, 50]     # nearest point: the first pass
    tour = route_timeline(xy, dem, DoseRate.constant(144.0), stations=[{**b, "order": 1}, {**a, "order": 2}])
    assert tour["dwell_s"].to_numpy().nonzero()[0].tolist() == [50, 90]      # A on the way back
    assert tour["t_s"].iloc[-1] == pytest.approx(plain["t_s"].iloc[-1])


@pytest.mark.filterwarnings("ignore:'crs' was not provided")
def test_e5_tour_geopackage(tmp_path):
    gpd = pytest.importorskip("geopandas")
    from shapely.geometry import LineString, Point

    from radiation.return_time import resolve_habitat
    xs = np.arange(10.5, 61.0)
    xy = out_and_back(np.column_stack([xs, np.full_like(xs, 100.5)]))
    path = tmp_path / "tour.gpkg"
    gpd.GeoDataFrame({"order_text": ["habitat>B>A>habitat"]}, geometry=[LineString(xy)]).to_file(
        path, layer="route", driver="GPKG")
    gpd.GeoDataFrame({"order": [0, 1, 2, 3], "id": ["habitat", "B", "A", "habitat"],
                      "type": ["habitat", "ridge", "hollow", "habitat"],
                      "service_time_min": [0.0, 10.0, 10.0, 0.0]},
                     geometry=[Point(10.5, 100.5), Point(60.5, 100.5), Point(20.5, 100.5), Point(10.5, 100.5)]
                     ).to_file(path, layer="stops", driver="GPKG")
    route_xy, stations = load_route(path)
    assert np.allclose(route_xy, xy)
    assert [(s["id"], s["order"], s["service_time_min"]) for s in stations] == [("B", 1, 10.0), ("A", 2, 10.0)]
    assert resolve_habitat(None, path) == ((10.5, 100.5), "route file point (habitat)")
    tl = route_timeline(route_xy, make_dem(tmp_path, 0.0), DoseRate.constant(144.0), stations=stations)
    assert tl.attrs["method"] == "e3_edges"
    assert tl["dwell_s"].to_numpy().nonzero()[0].tolist() == [50, 90]


def test_far_station_is_ignored(tmp_path):
    dem = make_dem(tmp_path, 0.0)
    pts, d_h, alpha = steps(dem, [[10.0, 100.0], [110.0, 100.0]])
    far = [{"id": "far", "x": 60.0, "y": 160.0, "service_time_min": 30.0}]
    w = walk(pts, d_h, alpha, stations=far)
    assert w["dwell_s"].sum() == 0.0
    assert w["stations_ignored"] == [{"id": "far", "dist_to_route_m": 60.0}]


def test_gravity_changes_energy_not_time(tmp_path):
    dem = make_dem(tmp_path, 8.0)
    pts, d_h, alpha = steps(dem, [[10.0, 100.0], [150.0, 100.0]])
    out = {g: walk(pts, d_h, alpha, g) for g in (G_MOON, G_MARS, G_EARTH)}
    times = [o["t_s"][-1] for o in out.values()]
    energies = [o["energy_j"][-1] for o in out.values()]
    assert np.ptp(times) == pytest.approx(0.0, abs=1e-9)
    assert energies[0] < energies[1] < energies[2]


def test_eta_modes(tmp_path):
    dem = make_dem(tmp_path, 0.0)
    pts, d_h, alpha = steps(dem, [[10.0, 100.0], [110.0, 100.0]])
    base = walk(pts, d_h, alpha)
    en = walk(pts, d_h, alpha, eta=2.0, eta_mode="energy")
    sp = walk(pts, d_h, alpha, eta=2.0, eta_mode="speed")
    assert en["t_s"][-1] == pytest.approx(base["t_s"][-1])
    assert en["energy_j"][-1] == pytest.approx(2 * base["energy_j"][-1])
    assert sp["t_s"][-1] == pytest.approx(2 * base["t_s"][-1])
    assert base["energy_j"][-1] < sp["energy_j"][-1] < 2 * base["energy_j"][-1]
    with pytest.raises(ValueError):
        walk(pts, d_h, alpha, eta=2.0, eta_mode="other")


def test_return_along_route_retrace_and_loop(tmp_path):
    dem = make_dem(tmp_path, 5.0)
    one_way = np.array([[10.0, 100.0], [110.0, 100.0]])        # uphill eastwards
    w = walk(*steps(dem, one_way))
    dt_down, _ = segment_cost(1.0, -5.0)
    assert w["return_route_s"][-1] == pytest.approx(100 * dt_down, rel=1e-3)   # walking back is downhill
    assert not w["closed"]
    w = walk(*steps(dem, out_and_back(one_way)))
    assert w["closed"]
    assert w["return_route_s"][-1] == pytest.approx(0.0)
    assert np.argmax(w["return_route_s"]) == pytest.approx(100, abs=1)       # farthest = turnaround


def test_series_rate_integrates_exactly():
    # rate rises linearly from 100 to 200 uGy/day over one day
    r = DoseRate([0.0, 86400.0], [100.0, 200.0], "ramp")
    assert r.dose_between(0.0, 86400.0) == pytest.approx(150.0)
    assert r.dose_between(-86400.0, 0.0) == pytest.approx(100.0)       # constant before the series
    assert r.at(43200.0) == pytest.approx(150.0)


def test_budget_limited_stops_when_energy_runs_out():
    t = np.array([0.0, 10.0, 20.0])
    e = np.array([0.0, 100.0, 200.0])
    assert budget_limited(t, e, 150.0) == (15.0, True)
    assert budget_limited(t, e, 500.0) == (20.0, False)
