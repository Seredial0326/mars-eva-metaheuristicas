"""Walkback of E5 tours on small synthetic grids."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_network import grid_graph

from orienteering.data_io import Stations
from orienteering.network import route_path, station_matrix
from orienteering.problem import Problem
from orienteering.safety import return_costs, solve_with_walkback, tour_walkback
from orienteering.solvers import dp


def line_stations(graph, cols, prizes, service_j=None):
    """Stations on row 0 of a 1-row grid at the given columns; station 0 is the habitat."""
    n = len(cols)
    xy = [graph.cell_to_xy(0, c) for c in cols]
    return Stations(np.array(["habitat"] + [f"S{k}" for k in range(1, n)]), np.array([""] * n),
                    np.array([p[0] for p in xy]), np.array([p[1] for p in xy]),
                    np.zeros(n, dtype=np.int64), np.array(cols), np.array(prizes, dtype=float),
                    np.zeros(n)), (np.zeros(n) if service_j is None else np.asarray(service_j, float))


def profile(graph, stations, route, service_j, usable_j):
    dis = station_matrix(graph, stations)
    path, stop_index = route_path(graph, stations, route, dis)
    rv = return_costs(graph, graph.node(stations.row[0], stations.col[0]))
    stop_service = [service_j[k] if k not in route[:m] else 0.0 for m, k in enumerate(route)]
    return tour_walkback(graph, path, stop_index, stop_service, rv, usable_j)


def test_round_trip_within_budget_passes():
    graph = grid_graph(1, 6)
    stations, svc = line_stations(graph, [0, 5], [0, 5])
    prof = profile(graph, stations, [0, 1, 0], svc, usable_j=10.0)
    assert prof["feasible"] and prof["min_slack_j"] == pytest.approx(0.0)
    assert prof["stop_slack_j"].tolist() == pytest.approx([10.0, 0.0, 0.0])


def test_route_ending_away_from_habitat_fails_at_the_far_stop():
    # Out to col 5 (5 J) and on to col 2 (3 J): 8 J fits in 9, but at col 5 the astronaut has
    # used 5 J and needs 5 J to get home
    graph = grid_graph(1, 6)
    stations, svc = line_stations(graph, [0, 5, 2], [0, 5, 1])
    prof = profile(graph, stations, [0, 1, 2], svc, usable_j=9.0)
    assert not prof["feasible"]
    assert prof["first_violation_stop"] == 1
    assert prof["min_slack_j"] == pytest.approx(-1.0)


def test_service_counts_after_the_stop():
    graph = grid_graph(1, 6)
    stations, svc = line_stations(graph, [0, 3], [0, 5], service_j=[0.0, 2.0])
    prof = profile(graph, stations, [0, 1, 0], svc, usable_j=7.0)
    assert prof["used_j"][-1] == pytest.approx(3 + 3 + 2)
    assert not prof["feasible"]
    assert prof["stop_slack_j"][1] == pytest.approx(7 - (3 + 2) - 3)


def test_trivial_tour_passes():
    graph = grid_graph(1, 3)
    stations, svc = line_stations(graph, [0, 2], [0, 1])
    prof = profile(graph, stations, [0, 0], svc, usable_j=0.0)
    assert prof["feasible"]


def test_replans_with_a_lower_budget():
    # 0 = habitat (col 0), 1 = A (col 5, prize 5), 2 = C (col 1, prize 3), 3 = B (col 2, prize 1),
    # the route must end at B. With 9 J the best is habitat > C > A > B (8 J, prize 9) but it is
    # past the point of no return at A; the re-plan settles on habitat > C > B.
    graph = grid_graph(1, 6)
    stations, svc = line_stations(graph, [0, 5, 1, 2], [0, 5, 3, 1])
    dis = station_matrix(graph, stations)
    problem = Problem(energy=dis, prize=stations.prize, budget=9.0, end=3)
    rv = return_costs(graph, graph.node(0, 0))

    def check(route):
        path, stop_index = route_path(graph, stations, route, dis)
        return tour_walkback(graph, path, stop_index, [0.0] * len(route), rv, problem.budget)

    assert dp.solve(problem).route == [0, 2, 1, 3]
    solution, prof, retries = solve_with_walkback(problem, dp.solve, check)

    assert solution.route == [0, 2, 3] and solution.prize == 4.0
    assert prof["feasible"] and retries >= 1


def test_replan_drops_only_the_station_that_breaks_walkback():
    # Station 1 always breaks the walkback with a huge deficit. Lowering the budget by
    # that deficit leaves nothing, so the best repair is to forbid station 1 alone.
    energy = np.ones((4, 4))
    np.fill_diagonal(energy, 0.0)
    problem = Problem(energy=energy, prize=np.array([0.0, 5.0, 3.0, 2.0]), budget=10.0)

    def check(route):
        bad = [m for m, k in enumerate(route) if k == 1]
        return {"feasible": not bad, "min_slack_j": -100.0 if bad else 1.0,
                "first_violation_stop": bad[0] if bad else None}

    solution, prof, retries = solve_with_walkback(problem, dp.solve, check)

    assert prof["feasible"] and 1 not in solution.route
    assert solution.prize == 5.0 and sorted(solution.route[1:-1]) == [2, 3]
