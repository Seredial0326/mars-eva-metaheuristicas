"""Tests for the MaxEnt IRL core (src/ml/maxent_irl.py) on small synthetic windows."""

import sys
from pathlib import Path

import numpy as np
import pytest
import torch
from scipy.ndimage import gaussian_filter

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "ml"))

import maxent_irl as irl  # noqa: E402


def smooth_window(seed, h=24, w=20):
    rng = np.random.default_rng(seed)
    f = gaussian_filter(rng.standard_normal((h, w)), 3)
    f = (f - f.min()) / (f.max() - f.min())
    return np.stack([np.ones((h, w)), f])


def demos_from(phi, w, goal, starts, seed=0):
    rng = np.random.default_rng(seed)
    pi = irl.policy_for(w, phi, goal)
    return [irl.Demo(phi, irl.sample_route(pi, s, goal, rng), f"d{i}") for i, s in enumerate(starts)]


def test_neighbour_order_matches_e3():
    from fisica.edge_cost import NEIGHBOURS
    assert irl.NEIGHBOURS == NEIGHBOURS
    assert irl.STEP_M.tolist() == pytest.approx([1, 2 ** 0.5] * 4)


def test_policy_sums_to_one_except_at_goal():
    phi = smooth_window(1)
    goal = (20, 15)
    pi = irl.policy_for(np.array([2.5, 3.0]), phi, goal)
    total = pi.sum(axis=0)
    assert total[goal] == 0
    total[goal] = 1
    assert total == pytest.approx(np.ones_like(total), abs=1e-9)


def test_gradient_matches_autograd_and_finite_differences():
    phi = smooth_window(2)
    # Two window sizes in one batch, so padding (blocked cells) is exercised too.
    demos = demos_from(phi, np.array([2.5, 3.0]), (20, 15), [(2, 2), (3, 17)], seed=1)
    demos += demos_from(phi[:, :16, :14], np.array([2.5, 3.0]), (12, 10), [(1, 1)], seed=2)
    batch = irl.make_batches(demos, chunk=8)[0]
    w = np.array([3.0, 1.0])
    ev = irl.evaluate(w, [batch])
    wt = torch.tensor(w, dtype=torch.float64, requires_grad=True)
    loss = irl.nll_autograd(wt, batch, n_iter=ev.vi_iter + 100)
    loss.backward()
    assert loss.item() == pytest.approx(ev.nll.sum(), rel=1e-10)
    assert wt.grad.numpy() == pytest.approx(ev.grad.sum(axis=0), rel=1e-8)
    eps = 1e-5
    fd = [(irl.evaluate(w + eps * e, [batch]).nll.sum() - irl.evaluate(w - eps * e, [batch]).nll.sum())
          / (2 * eps) for e in np.eye(2)]
    assert np.array(fd) == pytest.approx(ev.grad.sum(axis=0), rel=1e-6)
    assert (ev.nll > 0).all()          # a probability is at most 1


def test_route_cost_equals_weights_times_feature_counts():
    phi = smooth_window(3)
    d = demos_from(phi, np.array([2.5, 3.0]), (20, 15), [(2, 2)])[0]
    w = np.array([2.2, 1.7])
    c = np.tensordot(w, phi, axes=1)
    steps = np.diff(d.path, axis=0)
    by_step = sum((2 ** 0.5 if abs(dr) + abs(dc) == 2 else 1.0) * (c[tuple(a)] + c[tuple(b)]) / 2
                  for a, b, (dr, dc) in zip(d.path[:-1], d.path[1:], steps))
    assert w @ d.feature_counts() == pytest.approx(by_step)


def test_fit_recovers_hidden_prices():
    rng = np.random.default_rng(5)
    phi = smooth_window(5, 40, 40)
    true_w = np.array([2.5, 4.0])
    starts = [tuple(rng.integers(0, 40, 2)) for _ in range(40)]
    demos = demos_from(phi, true_w, (20, 20), [s for s in starts if s != (20, 20)], seed=6)
    w_fit, info = irl.fit(irl.make_batches(demos, chunk=64), np.array([3.0, 1.0]))
    assert info["success"]
    assert w_fit == pytest.approx(true_w, rel=0.25)


def test_demo_rejects_jumps_and_blocked_cells():
    phi = smooth_window(4)
    with pytest.raises(ValueError):
        irl.Demo(phi, [(0, 0), (0, 2)])
    blocked = phi.copy()
    blocked[1, 0, 1] = np.nan
    with pytest.raises(ValueError):
        irl.Demo(blocked, [(0, 0), (0, 1)])
    d = irl.Demo(phi, [(0, 0), (0, 1), (0, 2), (0, 1)])   # goal (0, 1) is touched earlier
    assert len(d.path) == 2
