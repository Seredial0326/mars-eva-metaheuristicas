"""The bitmask DP must match brute force on small random instances."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from orienteering.problem import Problem, evaluate_route
from orienteering.solvers import brute, dp

KINDS = ("plain", "service", "windows", "duration", "wait")


def random_problem(rng, n, start, end, kind):
    pts = rng.random((n, 2)) * 10
    energy = np.linalg.norm(pts[:, None] - pts[None], axis=2) * rng.uniform(0.8, 1.5, (n, n))
    np.fill_diagonal(energy, 0.0)
    prize = rng.integers(1, 6, n).astype(float)
    problem = Problem(energy=energy, prize=prize, budget=rng.uniform(0, 30), start=start, end=end)
    if kind == "plain":
        return problem

    problem.time = energy * rng.uniform(5, 10, (n, n))
    problem.service_s = rng.choice([0.0, 30.0, 60.0], n)
    problem.service_j = problem.service_s * rng.uniform(0.002, 0.01)
    if kind in ("windows", "wait"):
        opens = rng.uniform(0, 150, n) * (rng.random(n) < 0.6)
        widths = np.where(rng.random(n) < 0.3, np.inf, rng.uniform(10, 120, n))
        problem.windows = np.column_stack([opens, opens + widths])
    if kind == "wait":
        problem.wait_power_w = rng.uniform(0.005, 0.05)
    if kind == "duration":
        problem.max_duration_s = rng.uniform(50, 400)
    return problem


@pytest.mark.parametrize("seed", range(500))
def test_dp_matches_brute_force(seed):
    rng = np.random.default_rng(seed)
    n = int(rng.integers(2, 8))
    start = int(rng.integers(n))
    end = start if rng.random() < 0.5 else int(rng.integers(n))
    problem = random_problem(rng, n, start, end, KINDS[seed % len(KINDS)])

    got, ref = dp.solve(problem), brute.solve(problem)

    assert got.prize == pytest.approx(ref.prize)
    if ref.route:
        result = evaluate_route(problem, got.route)
        assert got.route[0] == start and got.route[-1] == end
        assert result["feasible"]
        assert got.energy == pytest.approx(result["energy"])
        assert got.energy <= problem.budget + 1e-9
        assert got.prize == pytest.approx(sum(problem.prize[k] for k in set(got.route)))
        if result["duration"] is not None:
            assert got.duration_s == pytest.approx(result["duration"])
    else:
        assert got.route == []


def test_service_energy_changes_the_choice():
    # 0 = habitat, 1 = A (prize 5, long work), 2 = B (prize 4, short work); every leg costs 10 J
    energy = np.full((3, 3), 10.0)
    np.fill_diagonal(energy, 0.0)
    problem = Problem(energy=energy, prize=np.array([0.0, 5.0, 4.0]), budget=40.0)

    assert dp.solve(problem).prize == 9.0

    problem.service_j = np.array([0.0, 25.0, 5.0])
    got = dp.solve(problem)
    assert got.route == [0, 2, 0]
    assert got.energy == pytest.approx(10 + 5 + 10)


def test_service_counts_start_once_and_not_on_return():
    energy = np.array([[0.0, 1.0], [1.0, 0.0]])
    problem = Problem(energy=energy, prize=np.array([1.0, 1.0]), budget=100.0,
                      time=energy * 10, service_s=np.array([60.0, 120.0]),
                      service_j=np.array([3.0, 7.0]))

    got = dp.solve(problem)

    assert got.route == [0, 1, 0]
    assert got.energy == pytest.approx(1 + 1 + 3 + 7)
    assert got.duration_s == pytest.approx(10 + 10 + 60 + 120)


def window_problem(windows, max_duration_s=None):
    # 0 = habitat, 1 = A, 2 = B; every leg costs 1 J and takes 10 s, no service
    energy = np.ones((3, 3))
    np.fill_diagonal(energy, 0.0)
    return Problem(energy=energy, prize=np.array([0.0, 1.0, 1.0]), budget=100.0,
                   time=energy * 10, windows=np.array(windows, dtype=float),
                   max_duration_s=max_duration_s)


def test_window_forces_the_order():
    # A closes at 15 s, so it has to come first; B only opens at 50 s, so the route waits there
    got = dp.solve(window_problem([[0, np.inf], [0, 15], [50, np.inf]]))
    assert got.route == [0, 1, 2, 0]
    timeline = evaluate_route(window_problem([[0, np.inf], [0, 15], [50, np.inf]]), got.route)
    assert timeline["begin"][2] - timeline["arrival"][2] == pytest.approx(30.0)
    assert got.duration_s == pytest.approx(60.0)


def test_window_drops_an_unreachable_station():
    # B closes at 5 s but takes 10 s to reach: it is skipped
    got = dp.solve(window_problem([[0, np.inf], [0, np.inf], [0, 5]]))
    assert got.route == [0, 1, 0] and got.prize == 1.0


def test_max_duration_limits_the_route():
    assert dp.solve(window_problem([[0, np.inf]] * 3, max_duration_s=30)).prize == 2.0
    assert dp.solve(window_problem([[0, np.inf]] * 3, max_duration_s=25)).prize == 1.0
    assert dp.solve(window_problem([[0, np.inf]] * 3, max_duration_s=15)).route == [0, 0]


def test_slower_label_survives_when_it_is_cheaper():
    # Two ways to B: through A (cheap, slow) or direct (expensive, fast); C opens late, so the
    # cheap one is kept and wins under a tight energy budget
    energy = np.array([[0, 1, 9, 1], [1, 0, 1, 1], [9, 1, 0, 1], [1, 1, 1, 0]], dtype=float)
    time_m = np.array([[0, 50, 5, 50], [50, 0, 50, 50], [5, 50, 0, 5], [50, 50, 5, 0]], dtype=float)
    problem = Problem(energy=energy, prize=np.array([0.0, 1.0, 1.0, 1.0]), budget=4.0,
                      time=time_m, windows=np.array([[0, np.inf], [0, np.inf], [0, np.inf], [100, 200]]))
    got, ref = dp.solve(problem), brute.solve(problem)
    assert got.prize == ref.prize == 3.0


def test_waiting_energy_changes_the_choice():
    # A opens at 50 s. Visiting A first waits 40 s (4 J at 0.1 W), B first then A waits
    # 30 s (3 J); walking costs 3 J either way. With 5.5 J neither order fits any more.
    problem = window_problem([[0, np.inf], [50, np.inf], [0, np.inf]])
    problem.budget = 5.5
    assert dp.solve(problem).prize == 2.0
    problem.wait_power_w = 0.1
    assert evaluate_route(problem, [0, 1, 2, 0])["energy"] == pytest.approx(3.0 + 4.0)
    assert evaluate_route(problem, [0, 2, 1, 0])["energy"] == pytest.approx(3.0 + 3.0)
    got = dp.solve(problem)
    assert got.prize == 1.0 and got.route == [0, 2, 0]


def test_toy_problem_with_known_optimum():
    # Named toy problem (h0-4 criterion): habitat at the centre of a circle of 10 stations
    # of radius 10 m, one leg costs its length in J and every station is worth 1 point.
    # A tour that visits k neighbouring stations costs 2 * 10 + (k - 1) * chord, so with
    # a 50 J budget the optimum visits k = 1 + floor(30 / chord) stations, all adjacent.
    n_st, radius = 10, 10.0
    angles = 2 * np.pi * np.arange(n_st) / n_st
    pts = np.vstack([[0.0, 0.0], np.column_stack([radius * np.cos(angles), radius * np.sin(angles)])])
    energy = np.linalg.norm(pts[:, None] - pts[None], axis=2)
    chord = 2 * radius * np.sin(np.pi / n_st)
    problem = Problem(energy=energy, prize=np.r_[0.0, np.ones(n_st)], budget=50.0)

    got = dp.solve(problem)

    k = 1 + int(30.0 // chord)
    assert got.prize == k
    visited = sorted(k_ - 1 for k_ in got.route[1:-1])
    gaps = np.diff(visited + [visited[0] + n_st])
    assert sorted(gaps)[:-1] == [1] * (k - 1)             # a run of neighbours on the circle
    assert got.energy == pytest.approx(2 * radius + (k - 1) * chord)


@pytest.mark.parametrize("seed", range(40))
def test_solve_many_matches_separate_solves(seed):
    rng = np.random.default_rng(1000 + seed)
    n = int(rng.integers(2, 8))
    problem = random_problem(rng, n, 0, 0, KINDS[seed % len(KINDS)])
    rubrics = [rng.integers(0, 6, n).astype(float) for _ in range(5)]

    many = dp.solve_many(problem, rubrics)

    for rubric, got in zip(rubrics, many):
        problem.prize = rubric
        alone, ref = dp.solve(problem), brute.solve(problem)
        assert got.prize == pytest.approx(alone.prize) == pytest.approx(ref.prize)
        assert got.energy == pytest.approx(alone.energy)


def test_timed_problem_needs_a_time_matrix():
    problem = Problem(energy=np.zeros((2, 2)), prize=np.ones(2), budget=1.0, max_duration_s=10.0)
    with pytest.raises(ValueError):
        dp.solve(problem)


def test_no_route_if_start_service_exceeds_budget():
    problem = Problem(energy=np.zeros((2, 2)), prize=np.ones(2), budget=1.0,
                      service_j=np.array([2.0, 0.0]))
    assert dp.solve(problem).route == [] and brute.solve(problem).route == []


def test_dp_rejects_too_many_stations():
    problem = Problem(energy=np.zeros((21, 21)), prize=np.ones(21), budget=1.0)
    with pytest.raises(ValueError):
        dp.solve(problem)
