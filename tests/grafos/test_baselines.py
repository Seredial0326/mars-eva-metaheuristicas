"""Tests for the MVP baselines (issue #8) on small synthetic DEMs."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fisica.edge_cost import NEIGHBOURS, edge_costs  # noqa: E402
from grafos.baselines import (FLAT_J_PER_M, RATE_W, BaselineEvaluator, astar,  # noqa: E402
                              summarise)
from grafos.graph import Graph  # noqa: E402

TRANSFORM = (1.0, 0.0, 0.0, 0.0, -1.0, 0.0)


def make_graph(dem, slope=None):
    t, e, _ = edge_costs(dem, cell_slope_deg=slope)
    return Graph({"energy_j": e, "time_s": t}, NEIGHBOURS, transform=TRANSFORM)


def by_method(rows):
    return {r["method"]: r for r in rows}


def test_astar_matches_dijkstra():
    rng = np.random.default_rng(1)
    dem = np.cumsum(rng.normal(0, 0.1, (25, 25)), axis=1)
    g = make_graph(dem)
    s, t = g.node(0, 0), g.node(24, 17)
    path, cost = astar(g, s, t)
    assert cost == pytest.approx(g.costs_from(s, "length_m")[t])
    assert g.path_cost(path, "length_m")[-1] == pytest.approx(cost)


def test_astar_never_uses_blocked_cells():
    dem = np.zeros((15, 15))
    slope = np.zeros((15, 15))
    slope[2:13, 7] = 45                                     # wall with gaps at both ends
    g = make_graph(dem, slope)
    path, _ = astar(g, g.node(7, 0), g.node(7, 14))
    rows, cols = g.cell(path)
    assert not np.any(slope[rows, cols] > 30)


def test_flat_ground_all_methods_agree():
    g = make_graph(np.zeros((1, 60)))
    ev = BaselineEvaluator(g, g.node(0, 0))
    rows = by_method(ev.evaluate(g.node(0, 40), budget_j=1e9))
    assert rows["B1_astar_slope"]["real_j"] == pytest.approx(rows["MVP_e4"]["real_j"])
    assert rows["B1_astar_slope"]["estimate_j"] == pytest.approx(80 * FLAT_J_PER_M)
    assert all(r["safe"] and r["really_feasible"] for r in rows.values())


def test_uphill_goal_is_falsely_safe_for_radius_and_linear_o2():
    # goal 60 m away at the top of a ~11 deg ramp: going up costs much more than flat
    dem = np.tile(np.arange(61.0) * 0.2, (1, 1))
    g = make_graph(dem)
    ev = BaselineEvaluator(g, g.node(0, 0))
    goal = g.node(0, 60)
    exact = ev.loop_e[goal]
    flat = 2 * 60 * FLAT_J_PER_M
    assert exact > flat                                      # the ramp costs more than flat
    budget = 0.5 * (exact + flat)                             # between the two
    rows = by_method(ev.evaluate(goal, budget))
    assert not rows["MVP_e4"]["safe"]                         # exact: does not fit
    assert rows["B2_fixed_radius"]["safe"] and not rows["B2_fixed_radius"]["really_feasible"]
    assert rows["B1_astar_slope"]["safe"] and not rows["B1_astar_slope"]["really_feasible"]
    s = summarise(ev.evaluate(goal, budget))
    assert s["B2_fixed_radius"]["false_safe"] == 1
    assert s["MVP_e4"]["false_safe"] == 0


def test_linear_o2_uses_constant_rate_on_true_time():
    dem = np.tile(np.arange(30.0) * 0.15, (3, 1))
    g = make_graph(dem)
    ev = BaselineEvaluator(g, g.node(1, 0))
    goal = g.node(1, 29)
    b3 = by_method(ev.evaluate(goal, 1e9))["B3_linear_o2"]
    t = g.costs_from(g.node(1, 0), "time_s")[goal] + g.costs_to(g.node(1, 0), "time_s")[goal]
    assert b3["time_s"] == pytest.approx(t)
    assert b3["estimate_j"] == pytest.approx(RATE_W * t)


def test_sand_raises_truth_not_baseline_estimates():
    """#65: with a pricier terrain (E1 sand factor > 1 on the arrival cell), the
    baselines keep their flat-E3 estimates while the real cost and the MVP rise, so
    a goal that was safe on E3 can become a false safe."""
    from fisica.human_cost import human_edge_costs
    rng = np.random.default_rng(3)
    dem = np.cumsum(rng.normal(0, 0.05, (20, 20)), axis=1)
    t, e, _ = edge_costs(dem)
    factor = np.ones(dem.shape)
    factor[:, 10:] = 1.115                                  # full sand on the east half
    e_h = human_edge_costs(e, factor, NEIGHBOURS)
    g3 = Graph({"energy_j": e, "time_s": t}, NEIGHBOURS, transform=TRANSFORM)
    gh = Graph({"energy_j": e_h, "time_s": t}, NEIGHBOURS, transform=TRANSFORM)
    hab, goal = g3.node(10, 2), g3.node(10, 17)
    r3 = by_method(BaselineEvaluator(g3, hab).evaluate(goal, budget_j=1e9))
    rh = by_method(BaselineEvaluator(gh, hab).evaluate(goal, budget_j=1e9))
    for m in ("B1_astar_slope", "B2_fixed_radius", "B3_linear_o2"):
        assert rh[m]["estimate_j"] == pytest.approx(r3[m]["estimate_j"])   # blind to sand
        assert rh[m]["real_j"] > r3[m]["real_j"]
    assert rh["MVP_e4"]["real_j"] > r3["MVP_e4"]["real_j"]
    assert rh["MVP_e4"]["estimate_j"] == pytest.approx(rh["MVP_e4"]["real_j"])
