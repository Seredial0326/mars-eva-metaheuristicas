"""The OR-Tools solvers (CP-SAT and routing) against the exact DP, and their limits."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

if importlib.util.find_spec("ortools") is None:      # don't import it here (see routing.py)
    pytest.skip("ortools is not installed", allow_module_level=True)

from test_dp_vs_brute import random_problem, window_problem

from orienteering.problem import Problem, evaluate_route
from orienteering.solvers import EXACT, MAX_STATIONS, SOLVERS, cpsat, dp, pick, routing

KINDS = ("plain", "service", "windows", "duration")
OR_SOLVERS = {"cpsat": lambda p: cpsat.solve(p, 5.0), "routing": lambda p: routing.solve(p, 0.1)}


def small_case(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(2, 8))
    start = int(rng.integers(n))
    end = start if rng.random() < 0.5 else int(rng.integers(n))
    return random_problem(rng, n, start, end, KINDS[seed % len(KINDS)])


@pytest.mark.parametrize("name", OR_SOLVERS)
@pytest.mark.parametrize("seed", range(30))
def test_matches_dp_on_small_instances(seed, name):
    problem = small_case(seed)

    got, ref = OR_SOLVERS[name](problem), dp.solve(problem)

    assert got.solver == name
    assert got.prize == pytest.approx(ref.prize)
    if name == "cpsat":
        assert got.optimal and got.bound == pytest.approx(ref.prize)
    if ref.route:
        result = evaluate_route(problem, got.route)
        assert got.route[0] == problem.start and got.route[-1] == problem.end
        assert result["feasible"] and got.energy <= problem.budget + 1e-9
        assert got.energy == pytest.approx(result["energy"])
        assert got.energy <= ref.energy * (1 + 1e-4) + 1e-6      # ties broken by energy too
    else:
        assert got.route == []


@pytest.mark.parametrize("name", OR_SOLVERS)
def test_window_order_and_duration(name):
    solve = OR_SOLVERS[name]
    got = solve(window_problem([[0, np.inf], [0, 15], [50, np.inf]]))
    assert got.route == [0, 1, 2, 0] and got.duration_s == pytest.approx(60.0)
    assert solve(window_problem([[0, np.inf]] * 3, max_duration_s=25)).prize == 1.0
    assert solve(window_problem([[0, np.inf], [0, np.inf], [0, 5]])).route == [0, 1, 0]


def test_cpsat_proves_the_optimum_beyond_the_dp():
    # 30 stations on a circle around the habitat: too many for the DP; the optimum is a
    # run of neighbours like the toy problem's (test_dp_vs_brute)
    n_st, radius = 30, 10.0
    angles = 2 * np.pi * np.arange(n_st) / n_st
    pts = np.vstack([[0.0, 0.0], np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])])
    energy = np.linalg.norm(pts[:, None] - pts[None], axis=2)
    chord = 2 * radius * np.sin(np.pi / n_st)
    problem = Problem(energy=energy, prize=np.r_[0.0, np.ones(n_st)], budget=40.0)
    with pytest.raises(ValueError):
        dp.solve(problem)

    got = cpsat.solve(problem, 20.0)

    k = 1 + int(20.0 // chord)
    assert got.prize == k and got.optimal and got.bound == k
    assert got.energy == pytest.approx(2 * radius + (k - 1) * chord, rel=1e-4)


@pytest.mark.parametrize("name", OR_SOLVERS)
def test_rejects_waiting_energy_and_empty_budget(name):
    problem = window_problem([[0, np.inf], [50, np.inf], [0, np.inf]])
    problem.wait_power_w = 0.1
    with pytest.raises(NotImplementedError):
        OR_SOLVERS[name](problem)
    problem = Problem(energy=np.zeros((2, 2)), prize=np.ones(2), budget=1.0,
                      service_j=np.array([2.0, 0.0]))
    assert OR_SOLVERS[name](problem).route == []


@pytest.mark.parametrize("name", OR_SOLVERS)
def test_unreachable_leg_is_skipped(name):
    energy = np.array([[0.0, 1.0, np.inf], [1.0, 0.0, np.inf], [np.inf, np.inf, 0.0]])
    problem = Problem(energy=energy, prize=np.array([0.0, 1.0, 5.0]), budget=10.0)
    assert OR_SOLVERS[name](problem).route == [0, 1, 0]


def test_registry():
    assert SOLVERS["cpsat"] is cpsat.solve and SOLVERS["routing"] is routing.solve
    assert not {"cpsat", "routing"} & EXACT
    assert MAX_STATIONS["cpsat"] > MAX_STATIONS["dp"]
    assert pick(MAX_STATIONS["dp"]) == "dp" and pick(MAX_STATIONS["dp"] + 1) == "cpsat"
