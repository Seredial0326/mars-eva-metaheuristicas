"""Time windows from the light (#111): light profile -> windows, the OPTW they make, and
consistency with P6's light rule on the real terrain."""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_dp_vs_brute import random_problem

from orienteering import departure as dep
from orienteering import light_windows as lw
from orienteering.problem import Problem, evaluate_route
from orienteering.solvers import brute, dp


def test_sunlit_intervals():
    t = np.arange(0, 10.0)
    lit = np.array([1, 1, 0, 0, 1, 1, 1, 0, 1, 1], dtype=bool)
    assert lw.sunlit_intervals(t, lit) == [(0.0, 1.0), (4.0, 6.0), (8.0, 9.0)]
    assert lw.sunlit_intervals(t, np.zeros(10, dtype=bool)) == []


def test_windows_keep_the_longest_stretch_with_room_for_service():
    times = np.arange(0, 3601.0, 60.0)                    # one hour, every minute
    states = np.full((4, len(times)), 2)
    states[1, 10:20] = 1                                  # A: lit 0-9 min, shadow, lit 20-60 min
    states[2, :] = 0                                      # B: dark all the time
    states[3, :] = 1
    states[3, 30:36] = 2                                  # C: lit only 30-35 min
    service = np.array([0.0, 600.0, 600.0, 600.0])
    windows, ok, n_int = lw.windows_from_light(times, states, service)
    assert windows[0].tolist() == [0.0, np.inf] and ok[0]
    assert ok[1] and n_int[1] == 2
    assert windows[1].tolist() == [1200.0, 3600.0 - 600.0]  # the longer, later stretch
    assert not ok[2] and not ok[3]                        # no light / 5 min < 10 min of service


def test_handmade_afternoon_shadow_changes_the_order():
    # habitat 0, A and B; every leg 1 J and 600 s, 600 s of service. Without windows the
    # cheapest order is 0 A B 0. A falls into shadow 20 min after leaving, so it must go first;
    # B is in shadow at the start and only lit from 25 min on.
    energy = np.array([[0, 1, 1], [1, 0, 1], [1, 1, 0.5]], dtype=float)
    energy[0, 2] = 2.0                                   # going to B first is dearer
    base = Problem(energy=energy, prize=np.array([0.0, 1.0, 1.0]), budget=100.0,
                   time=np.full((3, 3), 600.0) - np.eye(3) * 600.0, service_s=np.array([0.0, 600.0, 600.0]))
    times = np.arange(0, 3 * 3600.0 + 1, 60.0)
    states = np.full((3, len(times)), 2)
    states[1, times >= 1200 + 600] = 1                   # A: shadow from 30 min
    states[2, times < 1500] = 1                          # B: shadow until 25 min
    windows, ok, _ = lw.windows_from_light(times, states, base.service_s)
    plain = dp.solve(base)
    timed, _ = lw.solve_with_windows(base, windows, ok)
    assert plain.prize == timed.prize == 2.0
    assert timed.route == [0, 1, 2, 0]
    base.windows = windows
    result = evaluate_route(base, timed.route)
    assert result["feasible"]
    assert result["begin"][1] >= windows[1][0] and result["begin"][1] <= windows[1][1]


@pytest.mark.parametrize("seed", range(60))
def test_dp_matches_brute_force_with_light_windows(seed):
    rng = np.random.default_rng(5000 + seed)
    n = int(rng.integers(2, 8))
    problem = random_problem(rng, n, 0, 0, "service")
    times = np.arange(0, 600.0, 5.0)
    states = np.where(rng.random((n, len(times))) < 0.97, 2, 1)
    for k in range(1, n):                                 # a few long shadow spells per station
        for _ in range(int(rng.integers(0, 3))):
            a = int(rng.integers(len(times)))
            states[k, a:a + int(rng.integers(5, 40))] = 1
    windows, ok, _ = lw.windows_from_light(times, states, problem.service_s)
    got, _ = lw.solve_with_windows(problem, windows, ok, solver="dp")
    problem.windows = windows
    ref = brute.solve(problem)
    assert got.prize == pytest.approx(ref.prize)
    if got.route:
        assert evaluate_route(problem, got.route)["feasible"]
        assert all(ok[k] for k in got.route)


def test_seconds_to_midnight():
    assert lw.seconds_to_midnight(12.0) == pytest.approx(dep.SOL_IN_SECONDS / 2)
    assert lw.seconds_to_midnight(23.0) == pytest.approx(dep.SOL_IN_SECONDS / 24)


real = pytest.mark.skipif(not dep.DEM_PATH.exists() or not (ROOT / "data" / "stations" / "stations_manual.gpkg").exists(),
                          reason="team data not available")


@pytest.fixture(scope="module")
def real_instance():
    from grafos.build_rv import SERVICE_POWER_W
    from grafos.walkback import J_PER_WH
    from orienteering.data_io import STATIONS_PATH, read_stations
    from orienteering.network import load_graph, place_habitat, station_matrices

    graph, _ = load_graph()
    st = read_stations(graph, STATIONS_PATH)
    r, c, _ = place_habitat(graph, (8143537.99, -284463.58))
    x, y = (float(v) for v in graph.cell_to_xy(r, c))
    st = st.prepend("habitat", "habitat", x, y, r, c)
    dis, tim = station_matrices(graph, st)
    base = Problem(energy=dis, prize=st.prize, budget=900 * J_PER_WH, time=tim, service_s=st.service_s,
                   service_j=st.service_s * SERVICE_POWER_W, max_duration_s=7200.0)
    dem, transform = dep.load_dem()
    return graph, st, base, dem, transform


@real
def test_real_light_windows_are_consistent_with_p6(real_instance):
    graph, st, base, dem, transform = real_instance
    rows, best = lw.sweep(graph, st, base, 4711, [6.0, 11.0, 16.0], dem, transform)
    plain = dp.solve(base)
    assert all(r["prize"] <= plain.prize + 1e-9 for r in rows)
    assert best["start_ltst_h"] == 11.0 and best["prize"] == plain.prize
    for r in rows:                                        # every stop is worked in sunlight
        walk, low, service = lw.tour_light(graph, st, base, r["route"], 4711, r["start_ltst_h"], dem, transform,
                                           np.asarray(r["windows_s"]))
        assert service == pytest.approx(1.0)
        assert 0.0 <= walk <= 1.0
    by = {r["start_ltst_h"]: r for r in rows}
    assert set(by[6.0]["route"]) != set(plain.route)      # morning shadows change the stations
    assert by[16.0]["order"] != [str(st.id[k]) for k in plain.route]   # and the evening the order
