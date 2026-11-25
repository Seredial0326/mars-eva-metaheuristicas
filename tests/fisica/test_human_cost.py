"""Tests for the E3 + E1 human cost (factor on the arrival cell, slope dropped)."""

import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fisica.edge_cost import NEIGHBOURS, edge_costs
from fisica.human_cost import human_edge_costs, load_weights, terrain_factor

E, W = 2, 6


def spec(**weights):
    feats = {
        "roughness": {"weight": weights.get("roughness", 0.0), "raster": "rough", "min": 0.0, "max": 1.0},
        "tpi_ridge": {"weight": weights.get("ridge", 0.0), "raster": "tpi", "transform": "positive",
                      "min": 0.0, "max": 1.0},
        "slope_deg": {"weight": 5.0, "raster": "slope", "min": 0.0, "max": 45.0},
    }
    return {"scale": 1.0, "features": feats}


def test_zero_weights_give_e3_exactly():
    dem = np.zeros((5, 5)); _, e, _ = edge_costs(dem)
    rasters = {"rough": np.random.default_rng(0).random((5, 5)), "tpi": np.zeros((5, 5))}
    f = terrain_factor(spec(), rasters, dem.shape)
    assert np.allclose(f, 1.0)                                    # slope weight is ignored
    h = human_edge_costs(e, f, NEIGHBOURS)
    assert np.allclose(h[np.isfinite(e)], e[np.isfinite(e)])


def test_ridge_price_applies_on_arrival_and_keeps_direction():
    dem = np.tile(np.arange(5) * 0.17, (5, 1))                    # ramp rising eastwards
    _, e, _ = edge_costs(dem)
    tpi = np.zeros((5, 5)); tpi[2, 3] = 1.0                       # one ridge cell
    f = terrain_factor(spec(ridge=0.5), {"rough": np.zeros((5, 5)), "tpi": tpi}, dem.shape)
    h = human_edge_costs(e, f, NEIGHBOURS)
    assert h[E, 2, 2] == pytest.approx(e[E, 2, 2] * 1.5, rel=1e-6)   # entering the ridge cell
    assert h[W, 2, 3] == pytest.approx(e[W, 2, 3], rel=1e-6)         # leaving it: no price
    assert h[E, 2, 2] != pytest.approx(h[W, 2, 3])                   # directed


def test_costs_never_below_e3_and_nan_pattern_kept():
    rng = np.random.default_rng(1)
    dem = rng.normal(0, 0.2, (12, 12)); dem[4, 4] = np.nan
    _, e, _ = edge_costs(dem)
    rasters = {"rough": rng.random((12, 12)), "tpi": rng.normal(0, 1, (12, 12))}
    h = human_edge_costs(e, terrain_factor(spec(roughness=0.7, ridge=0.3), rasters, dem.shape),
                         NEIGHBOURS)
    assert np.array_equal(np.isnan(h), np.isnan(e))
    ok = np.isfinite(e)
    assert (h[ok] >= e[ok] - 1e-6).all()


def test_weights_file_validation(tmp_path):
    good = spec(roughness=0.2)
    p = tmp_path / "w.json"; p.write_text(json.dumps(good))
    assert load_weights(p)["features"]["roughness"]["weight"] == 0.2
    bad = spec(roughness=-0.1); p.write_text(json.dumps(bad))
    with pytest.raises(ValueError):
        load_weights(p)


def test_distance_weight_sets_the_scale():
    s = spec(roughness=0.5); s.pop("scale"); s["distance_weight"] = 2.0
    f = terrain_factor(s, {"rough": np.ones((3, 3)), "tpi": np.zeros((3, 3))}, (3, 3))
    assert np.allclose(f, 1.25)                                   # 1 + 0.5 / 2
