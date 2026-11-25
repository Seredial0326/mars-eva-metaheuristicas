"""C5: nested spatial leakage guards and predictive-interval auditability."""
from pathlib import Path
import sys
from types import SimpleNamespace

import numpy as np
import pytest
from scipy import ndimage

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from fisica.rocks_validation import metrics, smoothing_model, split_masks, validate
from grafos.rock_risk import rock_factor
from dl_rocas import rocks_gp as gp


def fixture():
    folds = np.tile(np.repeat(np.arange(5), 10), (20, 1))
    values = .01 + np.arange(folds.size).reshape(folds.shape) / 1000
    return values, folds


def test_spatial_train_calibration_test_are_disjoint_and_buffered():
    values, folds = fixture()
    train, cal, test = split_masks(folds, np.isfinite(values), 0, buffer=1)
    assert not (train & cal).any()
    assert not (train & test).any()
    assert not (cal & test).any()
    assert not (train & ndimage.binary_dilation(test | cal)).any()
    assert train.any() and cal.any() and test.any()


def test_outer_labels_cannot_select_smoothing_or_interval_width():
    values, folds = fixture()
    train, cal, test = split_masks(folds, np.isfinite(values), 0)
    baseline = smoothing_model(values, folds, train, cal)
    changed = values.copy()
    changed[test] = 1e8
    repeated = smoothing_model(changed, folds, train, cal)
    assert baseline[0] == repeated[0]
    for a, b in zip(baseline[1:], repeated[1:]):
        np.testing.assert_array_equal(a, b)


def test_calibration_labels_never_enter_mean_fit_or_sigma_selection():
    values, folds = fixture()
    train, cal, _ = split_masks(folds, np.isfinite(values), 0)
    baseline = smoothing_model(values, folds, train, cal)
    changed = values.copy()
    changed[cal] += 100
    repeated = smoothing_model(changed, folds, train, cal)
    assert baseline[0]["sigma_blocks"] == repeated[0]["sigma_blocks"]
    assert baseline[0]["inner_mse"] == repeated[0]["inner_mse"]
    np.testing.assert_array_equal(baseline[1], repeated[1])
    assert repeated[0]["calibration_half_width_pct"] > baseline[0]["calibration_half_width_pct"]


def test_empty_group_is_not_reported_as_zero_coverage():
    a = np.zeros((2, 2))
    assert metrics(a, a, a, a, a.astype(bool))["coverage_90"] is None
    result = metrics(a, a, a, a, np.ones_like(a, bool))
    assert result["coverage_90"] == 1
    assert result["rmse_pct"] == 0


def test_existing_risk_defaults_do_not_enable_penalty():
    np.testing.assert_array_equal(rock_factor([0., .5, np.nan], [1., .2, np.nan]), np.ones(3))
    assert rock_factor([.1], [.2], k=3, lam=1)[0] == pytest.approx(1.9)


def test_validator_passes_only_training_labels_to_original_fitter(tmp_path, monkeypatch):
    teacher = np.arange(60, dtype=float).reshape(6, 10) / 1000
    folds = np.tile(np.repeat(np.arange(5), 2), (6, 1))
    calls = []

    def fit(x, y, seed):
        calls.append(y.copy())
        return SimpleNamespace(predict=lambda x, return_std: (np.full(len(x), float(np.mean(y))),
                                                            np.full(len(x), .1)))

    monkeypatch.setattr(gp, "block_means", lambda a: a)
    monkeypatch.setattr(gp, "folds", lambda shape, seed: folds)
    monkeypatch.setattr(gp, "fit_gp", fit)
    monkeypatch.setattr(gp, "gp_params", lambda fitted: {"synthetic": True})
    monkeypatch.setattr(gp, "TILE_BLOCKS", 2)
    result = validate(teacher, tmp_path, buffer=1)
    for k, received in enumerate(calls):
        train, cal, test = split_masks(folds, np.ones_like(folds, bool), k)
        np.testing.assert_allclose(received, gp.forward(teacher[train] * 100, "sqrt"))
        record = np.load(tmp_path / f"fold_{k}.npz")
        np.testing.assert_array_equal(record["train"], train)
        np.testing.assert_array_equal(record["calibration"], cal)
        np.testing.assert_array_equal(record["test"], test)
    assert result["scores"]["gp"]["all"]["blocks"] == teacher.size


@pytest.mark.parametrize("buffer", [-1, -10])
def test_negative_buffer_rejected(buffer):
    values, folds = fixture()
    with pytest.raises(ValueError):
        split_masks(folds, np.isfinite(values), 0, buffer)
