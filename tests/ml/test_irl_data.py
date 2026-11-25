"""Tests for the pure helpers of src/ml/irl_data.py (no data files needed)."""

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "ml"))

import irl_data  # noqa: E402


def test_feature_sets_start_with_metre_and_keep_the_merged_default():
    for name, feats in irl_data.FEATURE_SETS.items():
        assert feats[0] == "metre", name
        assert len(set(feats)) == len(feats), name
    assert irl_data.FEATURE_SETS["dem"] == irl_data.DEM_FEATURES == [
        "metre", "slope_deg", "roughness", "tpi_ridge", "tpi_hollow", "slope_mean_5m", "slope_mean_15m"]
    assert irl_data.FEATURE_SETS["dem_sand"][-2:] == ["sand", "sand_mean_5m"]


def test_rock_feature_sets():
    assert irl_data.FEATURE_SETS["rocks"] == ["metre", "rocks", "rocks_mean_10m"]
    assert irl_data.FEATURE_SETS["sand_rocks"] == ["metre", "sand", "sand_mean_5m", "rocks", "rocks_mean_10m"]
    assert irl_data.ROCKS.name == "rocas.tif" and irl_data.ROCK_LAYERS["student"] == irl_data.ROCKS


def test_rock_features_count_nan_as_zero_and_average_over_10m():
    rng = np.random.default_rng(1)
    cover = rng.random((40, 40)) * 0.1
    cover[12, 20] = np.nan
    f = irl_data.rock_features(cover)
    assert np.isfinite(f["rocks"]).all() and f["rocks"][12, 20] == 0.0
    filled = np.where(np.isnan(cover), 0.0, cover)
    np.testing.assert_array_equal(f["rocks"], filled)
    # An interior cell's 10 m mean is the plain mean of the 10 x 10 window around it (NaN as 0).
    assert f["rocks_mean_10m"][15, 18] == pytest.approx(filled[10:20, 13:23].mean())
    assert f["rocks_mean_10m"].mean() == pytest.approx(filled.mean(), rel=0.05)


def test_rocks_layer_needs_a_rocks_feature_set():
    before = (list(irl_data.FEATURES), irl_data.ROCKS_LAYER)
    with pytest.raises(SystemExit, match="rocks"):
        irl_data.setup(argparse.Namespace(features="sand", rocks_layer="teacher"))
    assert (irl_data.FEATURES, irl_data.ROCKS_LAYER) == before     # nothing switched


def test_missing_rock_layer_names_the_release(tmp_path):
    with pytest.raises(SystemExit, match="e9-rocks-v1"):
        irl_data.read_on_grid(tmp_path / "e9" / "rocas.tif", None, (2, 2), "Aaron's release e9-rocks-v1")


def test_rock_layer_off_the_base_grid_is_refused(tmp_path):
    from rasterio.transform import from_origin
    path = tmp_path / "rocas.tif"
    grid = from_origin(0.0, 4.0, 1.0, 1.0)
    with rasterio.open(path, "w", driver="GTiff", width=4, height=4, count=1, dtype="float32",
                       transform=from_origin(0.5, 4.0, 1.0, 1.0)) as dst:
        dst.write(np.zeros((1, 4, 4), dtype="float32"))
    with pytest.raises(SystemExit, match="base grid"):
        irl_data.read_on_grid(path, grid, (4, 4), "release")


def test_step_length_counts_diagonals_as_sqrt2():
    path = np.array([(0, 0), (0, 1), (1, 2), (2, 2)])
    assert irl_data.step_length(path) == pytest.approx(2 + 2 ** 0.5)


def test_coarse_features_are_block_means():
    phi = np.arange(2 * 10 * 10, dtype=float).reshape(2, 10, 10)
    c = irl_data.coarse_features(phi, 5)
    assert c.shape == (2, 2, 2)
    assert c[1, 1, 0] == pytest.approx(phi[1, 5:10, 0:5].mean())


def test_coarse_path_is_8_connected_without_repeats():
    rng = np.random.default_rng(0)
    moves = np.array([(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)])
    path = np.cumsum(np.vstack([(100, 100), moves[rng.integers(0, 8, 500)]]), axis=0)
    c = irl_data.coarse_path(path, 5)
    steps = np.abs(np.diff(c, axis=0))
    assert steps.max() == 1 and (steps.sum(axis=1) > 0).all()
    assert (c[0] == path[0] // 5).all() and (c[-1] == path[-1] // 5).all()


def test_coarse_table_converts_length_to_metres():
    table = pd.DataFrame({"sol": [1], "block": [0], "path": [np.array([(0, 0), (0, 5), (0, 10)])],
                          "length_m": [10.0], "n_steps": [2]})
    # The 1 m path above jumps 5 cells; only the coarse conversion is under test here.
    out = irl_data.coarse_table(table, 5)
    assert out.path.iloc[0].tolist() == [[0, 0], [0, 1], [0, 2]]
    assert out.length_m.iloc[0] == pytest.approx(10.0)
