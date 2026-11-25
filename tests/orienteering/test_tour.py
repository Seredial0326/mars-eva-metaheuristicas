"""E5 tour for POST /plan, with the real request model (api/plan.py) on synthetic grids."""

import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_network import grid_graph

from api.plan import PlanRequest
from grafos.labels import NoFeasibleRoute
from orienteering.tour import plan_tour

WH = 3600.0


def station(graph, sid, row, col, score, service_min=0.0):
    x, y = (float(v) for v in graph.cell_to_xy(row, col))
    return {"id": sid, "x": x, "y": y, "type": "ridge", "score": score,
            "service_time_min": service_min}


def request(graph, stations, budget_j, **kw):
    start = [float(v) for v in graph.cell_to_xy(1, 0)]
    return PlanRequest(start=start, stations=stations, energy_budget_wh=budget_j / WH,
                       margin=0.0, service_energy_wh_per_min=0.0, **kw)


def features(fc, kind):
    return [f for f in fc["features"] if f["properties"]["kind"] == kind]


def test_full_tour_in_e4_route_format():
    graph = grid_graph(3, 8)
    sts = [station(graph, "A", 1, 3, 5), station(graph, "B", 1, 7, 4), station(graph, "C", 0, 5, 3)]

    fc, info = plan_tour(request(graph, sts, 100.0), graph)

    line = features(fc, "route")[0]
    p = line["properties"]
    n = len(line["geometry"]["coordinates"])
    for key in ("used_wh", "rv_wh", "slack_wh", "t_s", "rv_time_s", "o2_used_l"):
        assert len(p[key]) == n
    assert p["approach"] == "E5_tour" and p["feasible"] and p["exact"]
    assert p["order"][0] == p["order"][-1] == "habitat"
    assert sorted(p["order"][1:-1]) == ["A", "B", "C"] and p["prize"] == 12.0
    assert p["stop_index"][0] == 0 and p["stop_index"][-1] == n - 1
    assert p["energy_wh"] == pytest.approx(p["used_wh"][-1], abs=1e-3)
    assert p["rv_wh"][-1] == 0.0
    assert [f["properties"]["id"] for f in features(fc, "stop")] == p["order"][1:-1]
    assert features(fc, "start")[0]["properties"]["moved_m"] == 0.0
    assert info["skipped"] == [] and info["goal_station"] is None and info["warnings"] == []


def test_tight_budget_skips_stations():
    graph = grid_graph(3, 8)
    sts = [station(graph, "near", 1, 2, 1), station(graph, "far", 1, 7, 5)]
    fc, info = plan_tour(request(graph, sts, 5.0), graph)
    assert features(fc, "route")[0]["properties"]["order"] == ["habitat", "near", "habitat"]
    assert info["skipped"] == ["far"]


def test_service_energy_and_time_in_the_profile():
    graph = grid_graph(3, 8)
    sts = [station(graph, "A", 1, 3, 5, service_min=2.0)]
    req = request(graph, sts, 1000.0)
    req.service_energy_wh_per_min = 1.0 / 60.0          # 1 W -> 120 J for 2 min
    fc, _ = plan_tour(req, graph)
    p = features(fc, "route")[0]["properties"]
    assert p["energy_wh"] * WH == pytest.approx(6.0 + 120.0, abs=0.1)
    assert p["time_s"] == pytest.approx(6.0 + 120.0)
    stop = features(fc, "stop")[0]["properties"]
    assert stop["departure_time_s"] - stop["arrival_time_s"] == pytest.approx(120.0)


def test_o2_budget_is_the_tighter_limit():
    graph = grid_graph(3, 8)
    sts = [station(graph, "near", 1, 2, 1), station(graph, "far", 1, 7, 5)]
    o2_l = 5.0 / 20100.0                                 # O2 for 5 J
    fc, info = plan_tour(request(graph, sts, 100.0, o2_budget_l=o2_l), graph)
    p = features(fc, "route")[0]["properties"]
    assert p["order"] == ["habitat", "near", "habitat"]
    assert p["usable_wh"] == pytest.approx(5.0 / WH, abs=1e-3)       # rounded to 3 decimals like E4
    assert p["usable_wh"] < 100.0 / WH
    assert any("O2" in w for w in info["warnings"])


def test_max_duration_is_respected():
    graph = grid_graph(3, 8)
    sts = [station(graph, "near", 1, 2, 1), station(graph, "far", 1, 7, 5)]
    fc, _ = plan_tour(request(graph, sts, 100.0, max_duration_min=5.0 / 60.0), graph)
    p = features(fc, "route")[0]["properties"]
    assert p["order"] == ["habitat", "near", "habitat"] and p["time_s"] <= 5.0


def test_blocked_station_is_moved_and_reported():
    graph = grid_graph(3, 8, blocked=[(1, 4)])
    fc, info = plan_tour(request(graph, [station(graph, "A", 1, 4, 5)], 100.0), graph)
    stop = features(fc, "stop")[0]["properties"]
    assert stop["moved_m"] > 0 and stop["requested"] != features(fc, "stop")[0]["geometry"]["coordinates"]
    assert any("station A moved" in w for w in info["warnings"])


def test_no_station_fits():
    graph = grid_graph(3, 8)
    with pytest.raises(NoFeasibleRoute):
        plan_tour(request(graph, [station(graph, "far", 1, 7, 5)], 3.0), graph)


def test_input_errors():
    graph = grid_graph(3, 8)
    with pytest.raises(ValueError):
        plan_tour(request(graph, [], 100.0), graph)
    many = [station(graph, f"S{k}", k % 3, 1 + k % 7, 1) for k in range(20)]
    with pytest.raises(ValueError):                    # too many for the DP when asked for it
        plan_tour(request(graph, many, 100.0), graph, solver="dp")


def test_more_stations_than_the_dp_use_cpsat():
    graph = grid_graph(5, 6)
    cells = [(r, c) for r in range(5) for c in range(6) if (r, c) != (1, 0)][:21]
    sts = [station(graph, f"S{k}", r, c, 1) for k, (r, c) in enumerate(cells)]

    fc, info = plan_tour(request(graph, sts, 1000.0), graph)

    p = features(fc, "route")[0]["properties"]
    assert p["method"] == "cpsat" and p["exact"] and p["gap"] == 0.0 and p["feasible"]
    assert p["prize"] == 21.0 and sorted(p["order"][1:-1]) == sorted(s["id"] for s in sts)


# --- #119 A4/A5: structured diagnosis and the smallest return margin ----------------------

from orienteering import diagnose  # noqa: E402


def test_no_tour_names_the_resource_and_the_closest_station():
    graph = grid_graph(3, 8)
    sts = [station(graph, "far", 1, 7, 5), station(graph, "mid", 1, 4, 2)]
    with pytest.raises(NoFeasibleRoute) as err:           # still a NoFeasibleRoute for /plan
        plan_tour(request(graph, sts, 3.0), graph)
    d = err.value.diagnosis
    assert isinstance(err.value, diagnose.NoTourFound)
    assert d["code"] == "insufficient_resources" and d["exact"] and d["limiting"] == ["energy"]
    assert d["closest"]["id"] == "mid"                    # 8 J round trip against 3 J
    assert d["closest"]["needs"]["energy_wh"] == pytest.approx(8.0 / WH, abs=1e-3)
    assert d["closest"]["available"]["energy_wh"] == pytest.approx(3.0 / WH, abs=1e-3)
    assert "mid" in str(err.value) and "energy" in str(err.value)
    assert d["actions"] and "energy budget" in d["actions"][0]


def test_no_tour_by_o2_and_by_duration():
    graph = grid_graph(3, 8)
    sts = [station(graph, "A", 1, 3, 5)]
    with pytest.raises(diagnose.NoTourFound) as err:
        plan_tour(request(graph, sts, 100.0, o2_budget_l=1.0 / 20100.0), graph)
    d = err.value.diagnosis
    assert d["limiting"] == ["energy", "o2"] or d["limiting"] == ["o2"]
    assert "o2" in d["limiting"] and d["exact"]
    with pytest.raises(diagnose.NoTourFound) as err:
        plan_tour(request(graph, sts, 100.0, max_duration_min=1.0 / 60.0), graph)
    d = err.value.diagnosis
    assert d["limiting"] == ["duration"] and d["exact"] is False   # legs follow least energy, not time
    assert d["closest"]["needs"]["duration_min"] == pytest.approx(6.0 / 60.0, abs=1e-2)


def test_raising_the_budget_as_advised_makes_the_station_fit():
    graph = grid_graph(3, 8)
    sts = [station(graph, "A", 1, 5, 5)]
    req = request(graph, sts, 3.0)
    req.margin = 0.2
    with pytest.raises(diagnose.NoTourFound) as err:
        plan_tour(req, graph)
    need_wh = err.value.diagnosis["closest"]["needs"]["energy_wh"] / 0.8
    req.energy_budget_wh = need_wh * 1.001
    fc, _ = plan_tour(req, graph)
    assert features(fc, "route")[0]["properties"]["order"] == ["habitat", "A", "habitat"]


def test_printed_minimums_round_up_never_below_the_need():
    # 56.448 Wh at margin 0.1 needs 62.72 Wh: rounding to nearest printed 62.7, which fails
    alone = {"short": ["energy", "o2", "duration"],
             "needs": {"energy_wh": 56.448, "o2_l": 1.231, "duration_min": 14.01}}
    lines = diagnose.actions(alone, {"margin": 0.1})
    assert lines[0].startswith("energy budget at least 62.8 Wh")
    assert lines[1] == "O2 budget at least 1.24 L"
    assert lines[2].startswith("max duration at least 14.1 min")
    exact = {"short": ["energy"], "needs": {"energy_wh": 45.0}}   # 45 / 0.9 = 50.0, no bump
    assert diagnose.actions(exact, {"margin": 0.1})[0].startswith("energy budget at least 50.0 Wh")


def test_input_errors_carry_the_field():
    graph = grid_graph(3, 8)
    with pytest.raises(ValueError) as err:
        plan_tour(request(graph, [], 100.0), graph)
    assert err.value.diagnosis == {"code": "invalid_input", "exact": True, "field": "stations",
                                   "message": "add a station to plan an E5 tour"}
    outside = station(graph, "out", 1, 3, 1)
    outside["x"] += 1000.0
    with pytest.raises(ValueError) as err:
        plan_tour(request(graph, [station(graph, "A", 1, 3, 1), outside], 100.0), graph)
    assert err.value.diagnosis["field"] == "stations[1]"


def test_search_incomplete_is_not_reported_as_no_fit():
    from orienteering.problem import Problem, Solution
    problem = Problem(energy=np.array([[0, 1.0], [1.0, 0]]), prize=np.array([0.0, 1.0]), budget=10.0)
    lim = diagnose.limits(10.0, None, None, 0.0)
    timed_out = Solution([], 0.0, 0.0, "cpsat", 30.0, bound=None, optimal=False)
    d = diagnose.no_tour(problem, ["habitat", "A"], lim, timed_out, "cpsat", 30.0)
    assert d["code"] == "search_incomplete" and d["exact"] is False and d["fits_alone"] == ["A"]
    unreach = Problem(energy=np.array([[0, np.inf], [np.inf, 0]]), prize=np.array([0.0, 1.0]), budget=10.0)
    d = diagnose.no_tour(unreach, ["habitat", "A"], lim, timed_out, "cpsat", 30.0)
    assert d["code"] == "unreachable" and d["exact"]


def test_skipped_reasons_and_smallest_margin():
    graph = grid_graph(3, 8)
    sts = [station(graph, "near", 1, 2, 1), station(graph, "far", 1, 7, 5), station(graph, "mid", 1, 4, 1)]
    fc, info = plan_tour(request(graph, sts, 9.0), graph)
    p = features(fc, "route")[0]["properties"]
    assert sorted(p["order"][1:-1]) == ["mid", "near"]     # 2 + 2 + 4 J = 8 J of 9
    r = info["skipped_reasons"]
    assert r["far"]["fits_alone"] is False and r["far"]["short"] == ["energy"]
    assert p["min_slack_wh"] == pytest.approx(min(p["slack_wh"]), abs=1e-3)
    assert p["slack_wh"][p["min_slack_index"]] == pytest.approx(p["min_slack_wh"], abs=1e-3)
    assert p["diagnosis"] is None and info["diagnosis"] is None


def test_skipped_station_that_fits_alone_is_flagged_as_combined():
    graph = grid_graph(3, 8)
    sts = [station(graph, "left", 0, 4, 3), station(graph, "right", 2, 4, 3)]
    fc, info = plan_tour(request(graph, sts, 9.0), graph)
    p = features(fc, "route")[0]["properties"]
    assert len(p["order"]) == 3                           # 4 + 2 + 4 J for both > 9 J
    (sid, reason), = info["skipped_reasons"].items()
    assert reason["fits_alone"] and reason["exact"] and "together" in reason["reason"]
