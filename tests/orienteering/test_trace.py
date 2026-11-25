"""Tracer (per-iteration rows, CSV export) and the Evaluator evaluation counter."""

import csv
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_dp_vs_brute import KINDS, random_problem

import pytest

from orienteering.instances import random_instance
from orienteering.lab.trace import Tracer
from orienteering.solvers import aco, ga, ils, sa
from orienteering.solvers.heuristics import Evaluator


def test_tracer_every_keeps_first_and_last():
    tr = Tracer(every=10)
    tr.start()
    for i in range(25):
        tr(iter=i, best=float(i))
    tr.flush()
    tr.flush()                                              # idempotent
    assert [r["iter"] for r in tr.rows] == [0, 10, 20, 24]


def test_tracer_flush_does_not_duplicate_a_kept_row():
    tr = Tracer(every=10)
    for i in range(21):
        tr(iter=i)
    tr.flush()
    assert [r["iter"] for r in tr.rows] == [0, 10, 20]


def test_tracer_rows_have_time():
    tr = Tracer()
    tr.start()
    for i in range(5):
        tr(iter=i)
    t = [r["t_s"] for r in tr.rows]
    assert t == sorted(t) and t[0] >= 0


def test_tracer_extend_keeps_given_times():
    tr = Tracer(every=10)
    tr.extend([{"t_s": 0.5, "best": 1.0}, {"t_s": 1.5, "best": 2.0}])
    tr.flush()
    assert [r["t_s"] for r in tr.rows] == [0.5, 1.5]


def test_tracer_to_csv_extra_columns(tmp_path):
    tr = Tracer()
    for i in range(3):
        tr(iter=i, best=2.0 * i)
    path = tmp_path / "t.csv"
    tr.to_csv(path, extra={"instance": "toy", "seed": 7})
    with open(path, newline="") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0])[:2] == ["instance", "seed"]
    assert len(rows) == 3 and rows[2]["instance"] == "toy" and rows[2]["best"] == "4.0"


def test_evaluator_counts_checks():
    problem = random_problem(np.random.default_rng(0), 5, 0, 0, KINDS[0])
    ev = Evaluator(problem)
    assert ev.evaluations == 0
    for _ in range(3):
        ev.check([0, 1, 0])
    assert ev.evaluations == 3


ILS_COLUMNS = {"iter", "best_prize", "best_energy_j", "current_prize", "shake_size", "shake_at",
               "stale", "improved", "t_s"}
SA_COLUMNS = {"iter", "best_prize", "best_energy_j", "temp", "move", "feasible", "accepted",
              "delta", "current_score", "t_s"}
ACO_COLUMNS = {"iter", "best_prize", "best_energy_j", "round_best_prize", "ants_mean_prize",
               "tau_mean", "tau_max", "stale", "t_s"}
GA_COLUMNS = {"iter", "best_prize", "best_energy_j", "pop_best", "pop_mean", "pop_worst",
              "diversity", "stale", "t_s"}
RUNNERS = {
    "ils": (lambda p, trace=None, seed=0: ils.solve(p, trace=trace), ILS_COLUMNS),
    "sa": (lambda p, trace=None, seed=0: sa.solve(p, seed=seed, steps=3000, trace=trace),
           SA_COLUMNS),
    "aco": (lambda p, trace=None, seed=0: aco.solve(p, seed=seed, trace=trace), ACO_COLUMNS),
    "ga": (lambda p, trace=None, seed=0: ga.solve(p, seed=seed, trace=trace), GA_COLUMNS),
}


def lab_instance(i):
    return random_instance(np.random.default_rng(i), 12)


@pytest.mark.parametrize("name", RUNNERS)
@pytest.mark.parametrize("i", range(8))
def test_trace_does_not_change_result(name, i):
    run = RUNNERS[name][0]
    problem, seed = lab_instance(i), i % 3
    plain, traced = run(problem, seed=seed), run(problem, trace=Tracer(), seed=seed)
    assert traced.route == plain.route and traced.prize == plain.prize
    assert traced.evaluations == plain.evaluations
    assert traced.iterations == plain.iterations
    assert plain.evaluations > 0 and plain.iterations > 0


@pytest.mark.parametrize("name", RUNNERS)
@pytest.mark.parametrize("i", range(4))
def test_best_prize_never_drops(name, i):
    tr = Tracer()
    sol = RUNNERS[name][0](lab_instance(i), trace=tr, seed=i)
    best = [r["best_prize"] for r in tr.rows]
    assert best and all(b2 >= b1 for b1, b2 in zip(best, best[1:]))
    assert [r["iter"] for r in tr.rows] == list(range(len(tr.rows)))
    assert len(tr.rows) == sol.iterations


@pytest.mark.parametrize("name", RUNNERS)
def test_trace_columns(name):
    run, columns = RUNNERS[name]
    tr = Tracer()
    run(lab_instance(1), trace=tr)
    assert tr.rows and all(set(r) == columns for r in tr.rows)


def test_ils_improved_is_bool():
    tr = Tracer()
    ils.solve(lab_instance(2), trace=tr)
    assert all(isinstance(r["improved"], bool) for r in tr.rows)


def test_sa_move_kinds_and_decisions():
    tr = Tracer()
    sa.solve(lab_instance(3), seed=1, steps=3000, trace=tr)
    assert {r["move"] for r in tr.rows} <= {"add", "drop", "swap", "reverse", "none"}
    assert len({r["move"] for r in tr.rows}) >= 3
    assert all(isinstance(r["accepted"], bool) and isinstance(r["feasible"], bool)
               for r in tr.rows)
    assert all(not r["accepted"] for r in tr.rows if not r["feasible"])


def test_sa_temperature_decreases():
    tr = Tracer()
    sa.solve(lab_instance(0), seed=0, steps=3000, trace=tr)
    temps = [r["temp"] for r in tr.rows]
    assert len(temps) > 100 and all(t2 < t1 for t1, t2 in zip(temps, temps[1:]))


def test_solution_without_route_has_counts():
    problem = lab_instance(0)
    problem.budget = 0.0
    for sol in (ils.solve(problem), sa.solve(problem)):
        assert sol.prize == 0.0 and sol.evaluations is not None


def test_ga_diversity_in_unit_interval():
    tr = Tracer()
    ga.solve(lab_instance(1), seed=1, trace=tr)
    assert tr.rows and all(0 < r["diversity"] <= 1 for r in tr.rows)
    assert all(r["pop_worst"] <= r["pop_mean"] <= r["pop_best"] for r in tr.rows)


def test_aco_tau_positive():
    tr = Tracer()
    aco.solve(lab_instance(1), seed=1, trace=tr)
    assert tr.rows and all(0 < r["tau_mean"] <= r["tau_max"] for r in tr.rows)
    assert all(r["round_best_prize"] >= 0 and r["ants_mean_prize"] >= 0 for r in tr.rows)


def test_aco_ga_solution_without_route_has_counts():
    problem = lab_instance(0)
    problem.budget = 0.0
    for sol in (aco.solve(problem), ga.solve(problem)):
        assert sol.prize == 0.0 and sol.evaluations is not None


# ---- DP and CP-SAT -------------------------------------------------------------------

import importlib.util

from orienteering.solvers import cpsat, dp

DP_COMMON = {"iter", "best_prize", "best_energy_j", "t_s"}
DP_COLUMNS = DP_COMMON | {"masks_done", "states", "closable", "k", "states_k", "closable_k",
                          "best_prize_k"}


def dp_instance(i, kind):
    rng = np.random.default_rng(100 + i)
    n = 10 + i % 5                                          # 10..14 nodes
    problem = random_problem(rng, n, 0, 0 if i % 2 else int(rng.integers(n)), kind)
    problem.budget = rng.uniform(15, 40)                    # roomy enough to have states
    return problem


@pytest.mark.parametrize("kind", ["plain", "windows"])
@pytest.mark.parametrize("i", range(5))
def test_dp_trace_same_result(kind, i):
    problem = dp_instance(i, kind)
    plain, traced = dp.solve(problem), dp.solve(problem, trace=Tracer())
    assert traced.route == plain.route and traced.prize == plain.prize
    assert traced.energy == plain.energy
    assert plain.iterations == (1 << problem.n) - 1 and plain.evaluations is None


@pytest.mark.parametrize("kind", ["plain", "windows"])
@pytest.mark.parametrize("i", range(5))
def test_dp_trace_states_by_k(kind, i):
    problem = dp_instance(i, kind)
    tr = Tracer()
    sol = dp.solve(problem, trace=tr)
    assert all(set(r) == DP_COLUMNS for r in tr.rows)
    progress = [r for r in tr.rows if r["k"] is None]
    by_k = [r for r in tr.rows if r["k"] is not None]
    assert tr.rows == progress + by_k                       # progress first, then the k rows
    assert [r["k"] for r in by_k] == list(range(1, problem.n + 1))
    assert sum(r["closable_k"] for r in by_k) == progress[-1]["closable"]
    end_prize = problem.prize[problem.end] if problem.end != problem.start else 0.0
    assert max(r["best_prize_k"] for r in by_k) + end_prize == pytest.approx(sol.prize)
    assert progress[-1]["best_prize"] == pytest.approx(sol.prize)
    assert all(r["best_prize"] == pytest.approx(sol.prize) for r in by_k)
    assert 50 <= len(progress) <= 110
    assert [r["states"] for r in progress] == sorted(r["states"] for r in progress)
    best = [r["best_prize"] for r in progress]
    assert all(b2 >= b1 for b1, b2 in zip(best, best[1:]))
    assert progress[-1]["masks_done"] == sol.iterations


def test_dp_trace_empty_instance():
    problem = dp_instance(0, "plain")
    problem.budget = 0.0
    tr = Tracer()
    sol = dp.solve(problem, trace=tr)
    assert sol.prize == 0.0 and sol.route == []
    assert all(r["best_prize"] == 0.0 for r in tr.rows)


needs_ortools = pytest.mark.skipif(importlib.util.find_spec("ortools") is None,
                                   reason="ortools is not installed")


def cpsat_instance(i):
    return random_instance(np.random.default_rng(200 + i), 14)


@needs_ortools
@pytest.mark.parametrize("i", range(3))
def test_cpsat_trace_objective_monotone_and_bound_above(i):
    problem = cpsat_instance(i)
    tr = Tracer()
    sol = cpsat.solve(problem, time_limit_s=10.0, trace=tr)
    assert sol.trace_rows
    phase1 = [r for r in tr.rows if r["phase"] == 1]
    phase2 = [r for r in tr.rows if r["phase"] == 2]
    assert phase1 and [r["iter"] for r in tr.rows if r["phase"] == 1] == list(range(len(phase1)))
    obj = [r["objective"] for r in phase1]
    assert all(b >= a for a, b in zip(obj, obj[1:]))
    assert all(r["bound"] >= r["objective"] - 1e-9 for r in phase1)
    assert all(r["best_energy_j"] is None for r in phase1)
    assert all(r["best_energy_j"] == pytest.approx(r["objective"]) for r in phase2)
    if sol.optimal:
        assert obj[-1] == pytest.approx(sol.prize)
    t = [r["t_s"] for r in tr.rows]
    assert t == sorted(t) and t[0] >= 0


@needs_ortools
def test_cpsat_trace_does_not_change_result():
    problem = cpsat_instance(0)
    plain = cpsat.solve(problem, time_limit_s=10.0)
    traced = cpsat.solve(problem, time_limit_s=10.0, trace=Tracer())
    assert plain.trace_rows is None
    assert traced.prize == plain.prize
