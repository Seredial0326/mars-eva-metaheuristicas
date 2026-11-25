"""C1 evaluation invariants: pairing, timing, service and unseen observations."""
import json
from pathlib import Path
import sys

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from fisica.eva_robustness import (Event, Plan, evaluate, experiment, load_plan,
                                  proportion_interval, realised_world, synthetic_plan)


def test_unsafe_first_event_never_leaves_habitat():
    plan = Plan((Event(60, (60,)), Event(60, ())), 100, 10, {})
    result = evaluate(plan, np.array([60, 60]), [[], [60], []], "nominal")
    assert result["events_completed"] == 0
    assert result["observations"] == 0
    assert result["arrival_margin_wh"] == 90
    assert not result["reserve_violated"]


def test_full_service_is_checked_before_work_and_no_partial_science_awarded():
    plan = Plan((Event(10, (10,)), Event(80, (10,), "service", 9),
                 Event(10, ())), 100, 10, {})
    result = evaluate(plan, np.array([10, 80, 10]), [[], [10], [10], []], "nominal")
    assert result["events_completed"] == 1
    assert result["science"] == 0
    assert result["arrival_margin_wh"] == 70


def test_actual_return_cost_counts_even_if_model_thinks_it_fits():
    plan = Plan((Event(10, (10,)), Event(90, ())), 100, 10, {})
    result = evaluate(plan, np.array([10, 90]), [[], [100], []], "nominal")
    assert result["reserve_violated"]
    assert result["capacity_exceeded"]
    assert result["arrival_margin_wh"] == -20
    assert result["observations"] == 1


def test_only_executed_prefix_updates_filter():
    plan = Plan((Event(10, (10,)), Event(90, ())), 100, 10, {})
    a = evaluate(plan, np.array([10, 1]), [[], [10], []], "adaptive")
    b = evaluate(plan, np.array([10, 1e6]), [[], [10], []], "adaptive")
    assert a == b
    assert a["observations"] == 1


def test_depleted_service_never_earns_science_or_future_observations():
    plan = Plan((Event(10, (10,)), Event(20, (10,), "service", 9),
                 Event(10, ())), 100, 10, {})
    result = evaluate(plan, np.array([10, 200, 10]), [[], [10], [10], []], "nominal")
    assert result["science"] == 0
    assert result["observations"] == 1
    assert result["events_completed"] == 1
    assert result["depleted_during_event"]
    assert not result["habitat_reached"]
    assert not result["turned_back"]


def test_zero_noise_complete_walk_has_exact_energy_and_science():
    plan = synthetic_plan()
    costs, returns = realised_world(plan, np.random.default_rng(1), .8, 0, .7)
    result = evaluate(plan, costs, returns, "nominal", k_true=.8)
    assert not result["turned_back"]
    assert result["science"] == 8
    assert result["arrival_margin_wh"] == pytest.approx(81 - .8 * 70)


def test_pairing_is_invariant_to_policy_order_and_reproducible():
    kwargs = dict(runs=20, bootstrap=100, seed=8)
    a = experiment(synthetic_plan(), **kwargs)
    b = experiment(synthetic_plan(), **kwargs,
                   policies=("adaptive", "nominal", "conservative"))
    assert a == b
    assert a == experiment(synthetic_plan(), **kwargs)
    for metric, estimate in a["paired_differences"]["adaptive_minus_nominal"].items():
        rows = a["rows"]
        delta = np.mean([float(x[metric]) - float(y[metric])
                         for x, y in zip(rows["adaptive"], rows["nominal"])])
        assert estimate["mean"] == pytest.approx(delta)


def test_identical_actions_share_identical_returns():
    plan = Plan((Event(10, (10,)), Event(200, ())), 100, 10, {})
    costs, returns = realised_world(plan, np.random.default_rng(9), 1.2, .15, .7)
    results = [evaluate(plan, costs, returns, name) for name in
               ("nominal", "conservative", "adaptive")]
    assert {r["events_completed"] for r in results} == {1}
    assert len({r["arrival_margin_wh"] for r in results}) == 1


@pytest.mark.parametrize("kwargs", [dict(runs=1), dict(bootstrap=99), dict(rho=1),
                                   dict(sigma=-1), dict(k_true=float("nan")),
                                   dict(seed=-1)])
def test_reject_invalid_experiments(kwargs):
    with pytest.raises(ValueError):
        experiment(synthetic_plan(), **kwargs)


@pytest.mark.parametrize("events", [(), (Event(-1, ()),), (Event(1, (1,)),),
                                    (Event(1, (), science=1),),
                                    (Event(float("nan"), ()),)])
def test_reject_invalid_plans(events):
    with pytest.raises(ValueError):
        Plan(events, 100, 10, {})


def test_explicit_plan_loader_and_version(tmp_path):
    path = tmp_path / "input.json"
    doc = {"schema_version": 1, "capacity_wh": 100, "reserve_wh": 10,
           "provenance": {"type": "synthetic"},
           "events": [{"predicted_wh": 5, "return_segments_wh": []}]}
    path.write_text(json.dumps(doc))
    assert load_plan(path).events == (Event(5, ()),)
    doc["schema_version"] = 2
    path.write_text(json.dumps(doc))
    with pytest.raises(ValueError, match="schema"):
        load_plan(path)


def test_zero_failures_does_not_mean_zero_statistical_uncertainty():
    score = proportion_interval([False] * 300)
    assert score["mean"] == 0
    assert score["ci95"][1] > .01
    assert 0 <= score["ci95"][0] < 1e-10


def test_export_saved_tour_matches_exact_directed_return_paths(tmp_path, monkeypatch):
    from types import SimpleNamespace
    from fisica.edge_cost import NEIGHBOURS, edge_costs
    from grafos.graph import Graph
    from fisica.eva_robustness import export_saved_plan
    from fisica import eva_robustness
    t, e, _ = edge_costs(np.tile(np.arange(5) * .1, (3, 1)))
    g = Graph({"energy_j": e, "time_s": t}, NEIGHBOURS,
              transform=(1., 0., 100., 0., -1., 50.))
    g.cost_model = "synthetic directed slope"
    nodes = np.array([g.node(1, c) for c in [0, 1, 2, 3, 4, 3, 2, 1, 0]])
    walking = g.path_cost(nodes) / 3600
    rv = g.costs_to(nodes[0]) / 3600
    used = walking.copy()
    used[4:] += 10
    coords = [list(map(float, g.cell_to_xy(*g.cell(n)))) for n in nodes]
    saved = {"request": {"energy_budget_wh": 100, "human_cost": False},
             "plan": {"features": [
                 {"geometry": {"coordinates": coords}, "properties": {
                     "kind": "route", "feasible": True, "used_wh": used.tolist(),
                     "rv_wh": rv[nodes].tolist(), "stop_index": [4],
                     "service_power_w": 60, "usable_wh": 90}},
                 {"properties": {"kind": "stop", "service_time_min": 10,
                                  "wait_s": 0, "score": 5}}]}}
    path = tmp_path / "saved.json"
    path.write_text(json.dumps(saved))
    monkeypatch.setitem(sys.modules, "api", SimpleNamespace(planner=SimpleNamespace(
        graph=lambda *args: g, e1_weights_path=lambda *args: None)))
    # The graph above is synthetic. Its provenance must be synthetic too: do not
    # hash the real DEM/grid (which do not exist in a clean checkout).
    metadata = tmp_path / "metadata"
    metadata.mkdir()
    for name in ("grid.json", "crs.wkt", "dem_1m.tif", "slope_deg.tif"):
        (metadata / name).write_bytes(b"synthetic graph metadata: " + name.encode())
    real_digest = eva_robustness.file_sha256
    monkeypatch.setattr(eva_robustness, "file_sha256",
                        lambda path: real_digest(metadata / Path(path).name))
    plan = export_saved_plan(path, tmp_path / "input.json", segment_m=2)
    assert sum(e.predicted_wh for e in plan.events) == pytest.approx(used[-1])
    assert sum(e.science for e in plan.events) == 5
    assert [e.kind for e in plan.events] == ["walk", "walk", "service", "walk", "walk"]
    assert sum(plan.events[1].return_segments_wh) == pytest.approx(rv[nodes[4]])
    assert plan.events[-1].return_segments_wh == ()
    saved["plan"]["features"][0]["properties"]["used_wh"][4] += 1
    path.write_text(json.dumps(saved))
    with pytest.raises(ValueError, match="split"):
        export_saved_plan(path, tmp_path / "input.json", segment_m=2)
