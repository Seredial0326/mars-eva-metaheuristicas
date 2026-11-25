"""X2 (#101): conjugate filter on log k (src/fisica/adaptive_k.py), with known bias."""

import sys
from math import exp, log
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fisica import adaptive_k as ak  # noqa: E402

K_TRUE = [0.8, 1.0, 1.2, 1.5]
SIGMA = ak.SIGMA_OBS


def walk(k_true, n, rng, sigma=SIGMA):
    """n segments: predicted O2 per segment (L) and what a k_true astronaut uses."""
    pred = rng.uniform(0.05, 0.6, n)                       # ~3-30 m segments of E3 O2
    obs = k_true * pred * np.exp(rng.normal(0.0, sigma, n))
    return obs, pred


def test_prior_alone_is_the_prior():
    p = ak.prior()
    assert (p.mu, p.sd, p.n) == (0.0, 0.3, 0)
    lo, hi = ak.interval(p, 0.90)
    assert lo == pytest.approx(exp(-1.6449 * 0.3), rel=1e-3)
    assert hi == pytest.approx(exp(1.6449 * 0.3), rel=1e-3)


def test_update_is_the_conjugate_formula():
    p = ak.update(ak.prior(0.3), 1.2, 1.0, sigma_obs=0.15)
    w = (1 / 0.15 ** 2) / (1 / 0.3 ** 2 + 1 / 0.15 ** 2)  # data weight 0.8
    assert p.mu == pytest.approx(w * log(1.2))
    assert p.sd == pytest.approx((1 / 0.3 ** 2 + 1 / 0.15 ** 2) ** -0.5)
    assert p.n == 1


def test_order_does_not_matter_and_empty_segments_are_ignored():
    rng = np.random.default_rng(3)
    obs, pred = walk(1.2, 12, rng)
    a = ak.update_many(ak.prior(), obs, pred)
    b = ak.update_many(ak.prior(), obs[::-1], pred[::-1])
    assert (a.mu, a.sd) == pytest.approx((b.mu, b.sd))
    assert ak.update(a, 0.0, 0.3) == a and ak.update(a, 0.3, 0.0) == a


@pytest.mark.parametrize("k_true", K_TRUE)
def test_one_walk_recovers_k_true(k_true):
    rng = np.random.default_rng(int(k_true * 100))
    post = ak.update_many(ak.prior(), *walk(k_true, 30, rng))
    lo, hi = ak.interval(post, 0.90)
    assert lo <= k_true <= hi
    assert hi - lo < 0.2
    assert ak.quantile(post, 0.90) > exp(post.mu)            # p90 above the median


@pytest.mark.parametrize("k_true", K_TRUE)
def test_ci90_coverage_is_about_90_percent(k_true):
    """2000 walks of 20 segments: the share of IC90 that contain k_true."""
    rng = np.random.default_rng(1000 + int(k_true * 10))
    hits = 0
    for _ in range(2000):
        lo, hi = ak.interval(ak.update_many(ak.prior(), *walk(k_true, 20, rng)), 0.90)
        hits += lo <= k_true <= hi
    assert 0.87 <= hits / 2000 <= 0.93


def test_bad_arguments():
    with pytest.raises(ValueError):
        ak.prior(0)
    with pytest.raises(ValueError):
        ak.update(ak.prior(), 1.0, 1.0, sigma_obs=0)
    with pytest.raises(ValueError):
        ak.quantile(ak.prior(), 1.0)


def test_reserve_check_uses_the_high_quantile():
    # 40 L used of 100; return predicted 45 L. With k_p90 = 1.4 it needs 63 L > 60 L left.
    out = ak.reserve_check(40.0, 45.0, 100.0, 1.4)
    assert out["return_now"] and out["reserve_needed"] == pytest.approx(63.0)
    assert out["margin_after_return"] == pytest.approx(-3.0)
    assert not ak.reserve_check(40.0, 45.0, 100.0, 1.0)["return_now"]
