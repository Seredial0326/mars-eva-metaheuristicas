"""Tests for directed edge costs on small synthetic DEMs."""

import sys
from math import radians, tan
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fisica.edge_cost import NEIGHBOURS, edge_costs
from fisica.metabolic import segment_cost

N, E, S, W, NE = 0, 2, 4, 6, 1


def test_flat_dem_matches_segment_cost():
    t, e, _ = edge_costs(np.zeros((5, 5)))
    t_ref, e_ref = segment_cost(1.0, 0)
    assert e[E, 2, 2] == pytest.approx(e_ref, rel=1e-6)          # ~389.64 J per metre
    assert t[E, 2, 2] == pytest.approx(t_ref, rel=1e-6)
    t_diag, e_diag = segment_cost(np.sqrt(2), 0)
    assert e[NE, 2, 2] == pytest.approx(e_diag, rel=1e-6)


def test_ramp_is_directed():
    # Elevation rises eastwards: tan(10 deg) metres per column.
    dem = np.tile(np.arange(5) * tan(radians(10)), (5, 1))
    t, e, a = edge_costs(dem)
    assert a[E, 2, 2] == pytest.approx(10, abs=1e-4)
    assert a[W, 2, 3] == pytest.approx(-10, abs=1e-4)
    assert e[E, 2, 2] == pytest.approx(segment_cost(1.0, 10)[1], rel=1e-5)
    assert e[E, 2, 2] != pytest.approx(e[W, 2, 3])                # up != down


def test_borders_and_nodata_have_no_edges():
    dem = np.zeros((4, 4))
    dem[1, 1] = np.nan
    _, e, _ = edge_costs(dem)
    assert np.isnan(e[N, 0, :]).all()                             # off the north edge
    assert np.isnan(e[:, 1, 1]).all()                             # leaving a nodata cell
    assert np.isnan(e[E, 1, 0])                                   # entering a nodata cell


def test_slope_limit_removes_edges():
    dem = np.tile(np.arange(4) * tan(radians(25)), (3, 1))
    _, e, _ = edge_costs(dem, max_slope_deg=20)
    assert np.isnan(e[E]).all() and np.isnan(e[W]).all()
    assert np.isfinite(e[N, 1:, :]).all()                         # contour moves stay


def test_all_costs_positive():
    rng = np.random.default_rng(0)
    _, e, _ = edge_costs(rng.normal(0, 0.1, (20, 20)))
    assert (e[np.isfinite(e)] > 0).all()                          # Dijkstra needs >= 0


def test_neighbour_order_is_8_unique_moves():
    assert len(set(NEIGHBOURS)) == 8 and (0, 0) not in NEIGHBOURS


def test_cell_slope_block_and_disable():
    dem = np.zeros((5, 5))
    cell_slope = np.full((5, 5), 10.0)
    cell_slope[2, 2] = 35.0
    _, e, _ = edge_costs(dem, cell_slope_deg=cell_slope, max_cell_slope_deg=30)
    assert np.isnan(e[:, 2, 2]).all()                             # no edge out of the steep cell
    assert np.isnan(e[E, 2, 1])                                   # no edge into it
    assert np.isfinite(e[E, 1, 1])                                # the rest is untouched
    _, e_off, _ = edge_costs(dem, cell_slope_deg=cell_slope, max_cell_slope_deg=None)
    assert np.isfinite(e_off[:, 2, 2]).all()                      # demo toggle: block disabled
    _, e_40, _ = edge_costs(dem, cell_slope_deg=cell_slope, max_cell_slope_deg=40)
    assert np.isfinite(e_40[:, 2, 2]).all()                       # demo slider: higher limit


def test_slope_limit_guard_keeps_costs_positive():
    with pytest.raises(ValueError):
        edge_costs(np.zeros((3, 3)), max_slope_deg=75)            # speed would reach 0
    with pytest.warns(UserWarning):
        edge_costs(np.zeros((3, 3)), max_slope_deg=40)            # allowed, but extrapolated
    rng = np.random.default_rng(1)
    dem = rng.normal(0, 3.0, (30, 30))                            # very steep random terrain
    with pytest.warns(UserWarning):
        t, e, _ = edge_costs(dem, max_slope_deg=74.9)
    assert (e[np.isfinite(e)] > 0).all() and (t[np.isfinite(t)] > 0).all()


def test_models_agree_on_definitions():
    from fisica.edge_cost import model_power
    from fisica.metabolic import G_EARTH, G_MARS, pandolf_cf_power
    a = np.array([0.0, 10.0, -10.0]); v = 0.75 - 0.01 * a
    pan = model_power("pandolf_cf", 124.2, v, a, G_MARS)
    for i in range(3):
        assert pan[i] == pytest.approx(pandolf_cf_power(76.4, 47.8, v[i], a[i]), rel=1e-9)
    scaled = model_power("pandolf_cf_scaled", 124.2, v, a, G_MARS)
    assert np.allclose(scaled, pan * G_MARS / G_EARTH)
    with pytest.raises(ValueError):
        model_power("pandolf", 124.2, v, a, G_MARS)
