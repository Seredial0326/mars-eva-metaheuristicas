"""Tests for the multi-resource label-setting (energy, time, O2) with walkback."""

import itertools
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fisica.edge_cost import NEIGHBOURS, edge_costs  # noqa: E402
from grafos.graph import Graph  # noqa: E402
from grafos.labels import Budget, NoFeasibleRoute, round_trip  # noqa: E402


def make_graph(dem):
    t, e, _ = edge_costs(dem)
    return Graph({"energy_j": e, "time_s": t}, NEIGHBOURS)


def hilly(n=12, seed=0):
    rng = np.random.default_rng(seed)
    return np.cumsum(rng.normal(0, 0.12, (n, n)), axis=0) + np.cumsum(rng.normal(0, 0.12, (n, n)), axis=1)


def test_unconstrained_equals_two_dijkstras():
    g = make_graph(hilly())
    hab, goal = g.node(1, 1), g.node(10, 9)
    prof = round_trip(g, hab, goal, Budget())
    best = g.costs_from(hab)[goal] + g.costs_from(goal)[hab]
    assert prof["used_j"][-1] == pytest.approx(best)
    assert prof["path"][0] == hab and prof["path"][-1] == hab
    assert prof["path"][prof["turn_index"]] == goal


def test_time_limit_changes_the_route():
    g = make_graph(hilly(seed=3))
    hab, goal = g.node(0, 0), g.node(11, 11)
    free = round_trip(g, hab, goal, Budget())
    t_min = g.costs_from(hab, "time_s")[goal] + g.costs_from(goal, "time_s")[hab]
    tight = round_trip(g, hab, goal, Budget(time_s=t_min * 1.0000001))
    assert tight["time_s"][-1] <= t_min * 1.0000001
    assert tight["used_j"][-1] >= free["used_j"][-1] - 1e-6
    with pytest.raises(NoFeasibleRoute):
        round_trip(g, hab, goal, Budget(time_s=t_min * 0.99))


def test_walkback_holds_at_every_point():
    g = make_graph(hilly(seed=5))
    hab, goal = g.node(2, 2), g.node(9, 10)
    loop = round_trip(g, hab, goal, Budget())["used_j"][-1]
    prof = round_trip(g, hab, goal, Budget(energy_j=loop * 1.02))
    assert np.all(prof["slack_j"] >= -1e-6)
    assert prof["slack_j"].min() == pytest.approx(loop * 0.02, rel=1e-6)
    with pytest.raises(NoFeasibleRoute):
        round_trip(g, hab, goal, Budget(energy_j=loop * 0.98))


def test_o2_with_leak_and_service():
    g = make_graph(hilly(seed=7))
    hab, goal = g.node(0, 5), g.node(11, 5)
    b = Budget(leak_lpm=0.05)
    prof = round_trip(g, hab, goal, b, service_s=600, service_power_w=150)
    e, t = prof["used_j"][-1], prof["time_s"][-1]
    assert prof["o2_l"][-1] == pytest.approx(e / 20100 + 0.05 * t / 60)
    plain = round_trip(g, hab, goal, Budget())
    assert e == pytest.approx(plain["used_j"][-1] + 150 * 600)
    assert t == pytest.approx(plain["time_s"][-1] + 600)
    with pytest.raises(NoFeasibleRoute):
        round_trip(g, hab, goal, Budget(o2_l=prof["o2_l"][-1] * 0.99, leak_lpm=0.05),
                   service_s=600, service_power_w=150)


def brute_force(g, hab, goal, max_t):
    """Min energy over all simple out/back paths on a tiny grid, time <= max_t."""
    E, T = g.csr("energy_j"), g.csr("time_s")

    def paths(s, d, seen):
        if s == d:
            yield [s]
            return
        a, z = E.indptr[s], E.indptr[s + 1]
        for w in E.indices[a:z]:
            if w not in seen:
                for p in paths(int(w), d, seen | {int(w)}):
                    yield [s] + p

    def cost(p):
        return (sum(E[p[i], p[i + 1]] for i in range(len(p) - 1)),
                sum(T[p[i], p[i + 1]] for i in range(len(p) - 1)))

    outs = [cost(p) for p in paths(hab, goal, {hab})]
    backs = [cost(p) for p in paths(goal, hab, {goal})]
    best = np.inf
    for (e1, t1), (e2, t2) in itertools.product(outs, backs):
        if t1 + t2 <= max_t:
            best = min(best, e1 + e2)
    return best


def test_matches_brute_force_on_tiny_grid():
    dem = hilly(4, seed=11) * 1.5
    g = make_graph(dem)
    hab, goal = g.node(0, 0), g.node(2, 2)
    t_min = g.costs_from(hab, "time_s")[goal] + g.costs_from(goal, "time_s")[hab]
    for f in (1.0, 1.05, 1.2, 10):
        ref = brute_force(g, hab, goal, t_min * f + 1e-9)
        prof = round_trip(g, hab, goal, Budget(time_s=t_min * f + 1e-9))
        assert prof["used_j"][-1] == pytest.approx(ref)
