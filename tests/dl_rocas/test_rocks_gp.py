"""X1 (#102): GP helpers (blocks, folds, back-transform) and the boulder risk factor."""

import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np  # noqa: E402
import pytest  # noqa: E402

pytest.importorskip("sklearn")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dl_rocas.rocks_gp import (N_FOLDS, TILE_BLOCKS, back, block_means, fit_gp,  # noqa: E402
                               folds, smooth_predict, to_grid)
from grafos.rock_risk import apply_to_energy, rock_factor  # noqa: E402


def test_block_means_ignore_nan():
    a = np.ones((40, 40))
    a[:20, :20] = np.nan
    a[20:, 20:] = 3.0
    m = block_means(a, 20)
    assert np.isnan(m[0, 0]) and m[0, 1] == 1 and m[1, 1] == 3


def test_folds_are_balanced_tiles():
    f = folds((100, 100))
    assert sorted(np.unique(f)) == list(range(N_FOLDS))
    counts = np.bincount(f.ravel())
    assert counts.min() == counts.max()                       # 5 tiles each
    t = TILE_BLOCKS
    assert (f[:t, :t] == f[0, 0]).all()                        # a tile is one fold


def test_back_transform_moments_match_monte_carlo():
    rng = np.random.default_rng(0)
    mu, sd = np.array([0.0, 0.5, 2.0]), np.array([0.3, 0.4, 0.5])
    mean, std, lo, hi = back(mu, sd, "sqrt")
    z = rng.normal(mu, sd, size=(200_000, 3))
    c = z ** 2
    np.testing.assert_allclose(mean, c.mean(0), rtol=0.02)
    np.testing.assert_allclose(std, c.std(0), rtol=0.03)
    inside = ((c >= lo) & (c <= hi)).mean(0)
    assert np.all(inside >= 0.89)              # >= 90 % (exact when the interval misses 0)


def test_back_transform_none_is_identity():
    mean, std, lo, hi = back(np.array([1.0]), np.array([0.5]), "none")
    assert mean[0] == 1.0 and std[0] == 0.5 and hi[0] == pytest.approx(1.0 + 1.645 * 0.5, 1e-3)


def test_smoothing_only_uses_training_blocks():
    v = np.zeros((10, 10))
    v[5, 5] = 100.0
    train = np.ones_like(v, bool)
    train[5, 5] = False                       # the only rocky block is held out
    assert np.allclose(smooth_predict(v, train, 1.0), 0.0)


def test_gp_recovers_a_smooth_field_with_calibrated_intervals():
    rng = np.random.default_rng(1)
    xy = rng.uniform(0, 1000, size=(400, 2))
    f = np.sin(xy[:, 0] / 150) + np.cos(xy[:, 1] / 200)
    y = f + rng.normal(0, 0.2, len(f))
    gp = fit_gp(xy[:300], y[:300])
    mu, sd = gp.predict(xy[300:], return_std=True)
    assert np.sqrt(np.mean((mu - f[300:]) ** 2)) < 0.25
    inside = np.abs(y[300:] - mu) <= 1.645 * sd
    assert 0.8 <= inside.mean() <= 0.99


def test_to_grid_shape_and_constant():
    g = to_grid(np.full((3, 4), 2.0), (60, 80), 20)
    assert g.shape == (60, 80) and np.allclose(g, 2.0)


def test_rock_factor():
    mean = np.array([0.0, 0.1, np.nan])
    std = np.array([0.0, 0.05, 0.2])
    np.testing.assert_allclose(rock_factor(mean, std, k=0), 1.0)
    np.testing.assert_allclose(rock_factor(mean, std, k=10, lam=0), [1.0, 2.0, 1.0])
    np.testing.assert_allclose(rock_factor(mean, std, k=10, lam=2), [1.0, 3.0, 5.0])
    with pytest.raises(ValueError):
        rock_factor(mean, std, k=-1)


def test_apply_to_energy_uses_arrival_cell():
    from fisica.edge_cost import NEIGHBOURS
    e = np.ones((8, 3, 3), np.float32)
    factor = np.ones((3, 3))
    factor[1, 1] = 2.0
    out = apply_to_energy(e, factor, NEIGHBOURS)
    # arcs arriving at the centre cost 2, arcs leaving it cost 1
    for d, (dr, dc) in enumerate(NEIGHBOURS):
        assert out[d, 1 - dr, 1 - dc] == pytest.approx(2.0)
        assert out[d, 1, 1] == pytest.approx(1.0)
