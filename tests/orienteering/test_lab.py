"""Metaheuristics lab: ground-truth reference (DP, CP-SAT, best known) and gap."""

import importlib.util
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from orienteering.instances import random_instance
from orienteering.lab import reference
from orienteering.lab.reference import Reference, exact_reference, finalize, gap_pct
from orienteering.lab.trace import Tracer
from orienteering.problem import Problem, Solution
from orienteering.solvers import cpsat

HAS_ORTOOLS = importlib.util.find_spec("ortools") is not None


def instance(seed, n):
    return random_instance(np.random.default_rng(seed), n, "energy")


def fake_solution(prize, optimal, bound, energy=1.0, route=None):
    return Solution(route=route if route is not None else [0, 1, 0], prize=prize, energy=energy,
                    solver="cpsat", runtime_s=0.1, bound=bound, optimal=optimal)


def test_small_uses_dp():
    ref, sols = exact_reference(instance(1, 10), dp_max=18)
    assert ref.kind == "dp_optimal" and ref.solver == "dp"
    assert ref.upper_bound == ref.prize
    assert sols[0].solver == "dp" and ref.route == sols[0].route
    assert ref.prize == sols[0].prize


@pytest.mark.skipif(not HAS_ORTOOLS, reason="needs ortools")
def test_small_also_times_cpsat_but_keeps_dp_reference():
    ref, sols = exact_reference(instance(2, 8), dp_max=18, cpsat_limit_s=10)
    assert ref.kind == "dp_optimal"
    assert [s.solver for s in sols] == ["dp", "cpsat"]


@pytest.mark.skipif(not HAS_ORTOOLS, reason="needs ortools")
def test_medium_uses_cpsat():
    ref, sols = exact_reference(instance(3, 25), dp_max=18, cpsat_limit_s=30)
    assert [s.solver for s in sols] == ["cpsat"]
    assert ref is None or ref.kind == "cpsat_optimal"
    if ref is not None:
        assert ref.prize == ref.upper_bound == sols[0].prize
        assert ref.solver == "cpsat"
    else:
        assert sols[0].optimal is False


def test_cpsat_unproven_falls_back(monkeypatch):
    monkeypatch.setattr(reference.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(cpsat, "solve", lambda p, time_limit_s=None, trace=None:
                        fake_solution(7.0, False, 99.0))
    ref, sols = exact_reference(instance(4, 25), dp_max=18)
    assert ref is None and len(sols) == 1
    final = finalize(ref, sols)
    assert final.kind == "best_known" and final.upper_bound == 99
    assert final.prize == 7.0 and final.route == [0, 1, 0]


def test_cpsat_proven_is_reference(monkeypatch):
    monkeypatch.setattr(reference.importlib.util, "find_spec", lambda name: object())
    monkeypatch.setattr(cpsat, "solve", lambda p, time_limit_s=None, trace=None:
                        fake_solution(9.0, True, 9.0))
    ref, sols = exact_reference(instance(4, 25), dp_max=18)
    assert ref.kind == "cpsat_optimal" and ref.prize == ref.upper_bound == 9.0
    assert finalize(ref, sols) is ref


def test_no_ortools_falls_back(monkeypatch):
    monkeypatch.setattr(reference.importlib.util, "find_spec", lambda name: None)
    ref, sols = exact_reference(instance(5, 25), dp_max=18)
    assert (ref, sols) == (None, [])
    heur = fake_solution(5.0, None, None)
    final = finalize(ref, [heur])
    assert final.kind == "best_known" and final.prize == 5.0 and final.upper_bound is None


def test_no_ortools_small_still_dp(monkeypatch):
    monkeypatch.setattr(reference.importlib.util, "find_spec", lambda name: None)
    ref, sols = exact_reference(instance(6, 9), dp_max=18)
    assert ref.kind == "dp_optimal" and [s.solver for s in sols] == ["dp"]


def test_too_big_has_no_reference():
    ref, sols = exact_reference(instance(7, 61), dp_max=18)
    assert (ref, sols) == (None, [])


def test_tracers_are_forwarded():
    tr = {"dp": Tracer()}
    exact_reference(instance(8, 8), dp_max=18, cpsat_limit_s=5, tracers=tr)
    assert tr["dp"].rows


def test_finalize_best_known_ties_prefer_lower_energy():
    a = fake_solution(5.0, None, None, energy=10.0, route=[0, 1, 0])
    b = fake_solution(5.0, None, None, energy=8.0, route=[0, 2, 0])
    c = fake_solution(4.0, None, None, energy=1.0, route=[0, 3, 0])
    final = finalize(None, [a, b, c])
    assert final.prize == 5.0 and final.route == [0, 2, 0]


def test_finalize_keeps_proven_reference():
    ref = Reference(prize=6.0, kind="dp_optimal", upper_bound=6.0, solver="dp", route=[0, 1, 0])
    assert finalize(ref, [fake_solution(99.0, None, None)]) is ref


def test_gap_zero_reference():
    assert gap_pct(0.0, 0.0) == 0.0
    assert gap_pct(3.0, 0.0) == 0.0
    assert gap_pct(3.0, 4.0) == pytest.approx(25.0)
    assert gap_pct(4.0, 4.0) == 0.0


def test_nothing_fits_instance():
    p = Problem(energy=np.array([[0.0, 5.0], [5.0, 0.0]]), prize=np.array([0.0, 3.0]),
                budget=1.0, service_j=np.zeros(2))
    ref, sols = exact_reference(p, dp_max=18, cpsat_limit_s=5)
    assert ref.prize == 0.0 and gap_pct(0.0, ref.prize) == 0.0


# ---------------------------------------------------------------- datasets
import hashlib  # noqa: E402

from orienteering.lab import datasets  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
HAS_TERRAIN = (REPO / "data" / "base" / "dem_1m.tif").exists()


def synth_seed(n, kind, case):
    return 10_000 * n + case + (0 if kind == "energy" else 5_000)


@pytest.mark.parametrize("kind", ["energy", "windows"])
def test_synthetic_matches_random_instance(kind):
    inst = datasets.synthetic(12, kind, 3)
    ref = random_instance(np.random.default_rng(synth_seed(12, kind, 3)), 12, kind)
    assert inst.name == f"syn-{kind}-n12-3" and inst.set == "synthetic" and inst.kind == kind
    assert np.array_equal(inst.problem.energy, ref.energy)
    assert np.array_equal(inst.problem.prize, ref.prize)
    assert inst.problem.budget == ref.budget
    assert [s["id"] for s in inst.stations][:3] == ["habitat", "S1", "S2"]
    assert len(inst.stations) == 12 == inst.problem.n


def test_synthetic_distance_bounds():
    inst = datasets.synthetic(14, "energy", 0)
    d, e = inst.distance, inst.problem.energy
    off = ~np.eye(len(d), dtype=bool)
    assert np.all(e[off] >= 0.9 * d[off] - 1e-9) and np.all(e[off] <= 1.2 * d[off] + 1e-9)


@pytest.mark.parametrize("kind", ["energy", "windows"])
def test_save_load_roundtrip(tmp_path, kind):
    inst = datasets.synthetic(10, kind, 1)
    datasets.save(inst, root=tmp_path)
    back = datasets.load(inst.name, root=tmp_path)
    assert back.name == inst.name and back.set == inst.set and back.kind == inst.kind
    assert back.stations == inst.stations
    for f in ("energy", "prize", "time", "service_s", "service_j", "windows"):
        a, b = getattr(inst.problem, f), getattr(back.problem, f)
        assert (a is None) == (b is None), f
        if a is not None:
            assert np.array_equal(a, b), f
    assert np.array_equal(inst.distance, back.distance)
    assert back.problem.budget == inst.problem.budget
    assert back.problem.max_duration_s == inst.problem.max_duration_s
    assert (back.problem.start, back.problem.end) == (0, 0)


def test_roundtrip_max_duration(tmp_path):
    inst = datasets.synthetic(10, "energy", 0)
    inst.problem.max_duration_s = 7200.0
    datasets.save(inst, root=tmp_path)
    assert datasets.load(inst.name, root=tmp_path).problem.max_duration_s == 7200.0


def test_build_all_reuses(tmp_path):
    names = datasets.build_all(synthetic=True, real=False, root=tmp_path)
    assert len(names) == 11 * 2 * 5
    files = sorted(tmp_path.glob("*.npz"))
    assert len(files) == 110

    def snap():
        return {f.name: (f.stat().st_mtime_ns, hashlib.sha256(f.read_bytes()).hexdigest())
                for f in tmp_path.iterdir()}
    before = snap()
    assert datasets.build_all(synthetic=True, real=False, root=tmp_path) == names
    assert snap() == before


@pytest.mark.skipif(not HAS_TERRAIN, reason="needs data/base")
def test_real_spacing():
    from api.planner import graph as make_graph
    g = make_graph(str(REPO / "data" / "base"), 30.0, True)
    pool = datasets.station_pool(g)
    stations, nodes = pool
    assert len(stations) == datasets.POOL_SIZE + 1 == len(set(nodes))
    assert stations[0]["id"] == "habitat"
    assert len({s["id"] for s in stations}) == len(stations)      # ids are unique
    gen = np.array([[s["x"], s["y"]] for s in stations if s["id"].startswith("G")])
    allxy = np.array([[s["x"], s["y"]] for s in stations])
    for x, y in gen:                       # generated ones keep 40 m from everything
        d = np.hypot(allxy[:, 0] - x, allxy[:, 1] - y)
        assert np.sort(d)[1] >= 40.0
    inst, inst180 = datasets.real_pair(20, 0, graph=g, pool=pool)
    assert inst.name == "real-n20-0-120min" and inst180.name == "real-n20-0-180min"
    assert len(inst.stations) == 20 == inst.problem.n
    assert inst.stations[0]["id"] == "habitat"
    assert np.all(np.isfinite(inst.problem.energy)) and np.all(np.isfinite(inst.problem.time))
    assert np.all(np.isfinite(inst.distance))
    assert inst.problem.windows is None
    assert inst.problem.max_duration_s == 7200.0 and inst180.problem.max_duration_s == 10800.0
    assert np.array_equal(inst180.problem.energy, inst.problem.energy)


def test_pool_submatrix_is_exact():
    """Instances cut from the pool matrices equal instances with their own Dijkstras."""
    import types
    rng = np.random.default_rng(0)
    m = rng.random((6, 6))
    np.fill_diagonal(m, 0)
    stations = [{"id": "habitat" if i == 0 else f"R{i}", "type": "t", "x": float(i),
                 "y": 0.0, "prize": float(i), "service_s": 600.0} for i in range(6)]
    pool = (stations, list(range(6)))
    a, _ = datasets.real_pair(4, 1, pool=pool, matrices=(m, m * 2, m * 3))
    ids = [int(s["id"][1:]) if s["id"] != "habitat" else 0 for s in a.stations]
    assert ids[0] == 0 and ids == sorted(ids) and len(set(ids)) == 4
    assert np.array_equal(a.problem.energy, m[np.ix_(ids, ids)])
    assert np.array_equal(a.problem.time, 2 * m[np.ix_(ids, ids)])
    assert np.array_equal(a.distance, 3 * m[np.ix_(ids, ids)])
    with pytest.raises(ValueError):
        datasets.real_pair(7, 0, pool=pool, matrices=(m, m, m))


# ---------------------------------------------------------------- runner (run.py)

import csv
import json

from orienteering.lab import datasets, run
from orienteering.problem import evaluate_route

FAST = {"ils": {"max_no_improve": 5}, "sa": {"steps": 1500}, "aco": {"iterations": 4},
        "ga": {"generations": 4}}


def syn(n, kind="energy", case=0):
    return datasets.synthetic(n, kind, case)


def test_run_instance_columns():
    inst = syn(10)
    rows, traces = run.run_instance(inst, ("dp", "ils", "sa"), [0, 1], 18, 5.0, solver_kwargs=FAST)
    assert rows and all(list(r) == run.RUN_COLUMNS for r in rows)
    assert [r["algorithm"] for r in rows] == ["dp", "ils", "sa", "sa"]
    by = {(r["algorithm"], r["seed"]): r for r in rows}
    assert by[("dp", "")]["status"] == "ok" and by[("ils", "")]["status"] == "ok"
    assert by[("sa", 0)]["seed"] == 0 and by[("sa", 1)]["seed"] == 1
    assert by[("dp", "")]["reference_kind"] == "dp_optimal"
    assert by[("dp", "")]["is_optimal"] is True and by[("dp", "")]["gap_pct"] == 0.0
    assert set(traces) == {"dp", "ils", "sa"}
    assert all(t[0]["instance"] == inst.name for t in traces.values())
    assert {r["seed"] for r in traces["sa"]} == {0, 1}


def test_all_routes_feasible():
    inst = syn(14, "windows")
    rows, _ = run.run_instance(inst, run.ALGORITHMS, [0], 18, 5.0, solver_kwargs=FAST)
    ok = [r for r in rows if r["status"] == "ok"]
    assert {r["algorithm"] for r in ok} == set(run.ALGORITHMS)
    for r in ok:
        route = [int(s[1:]) if s != "habitat" else 0 for s in r["route"].split("-")]
        ev = evaluate_route(inst.problem, route)
        assert ev["feasible"] and ev["energy"] <= inst.problem.budget + 1e-6
        assert r["feasible"] is True


def test_dp_skipped_when_too_big():
    inst = syn(30)
    rows, traces = run.run_instance(inst, ("dp", "ils"), [0], 18, 5.0, solver_kwargs=FAST)
    dp_row = next(r for r in rows if r["algorithm"] == "dp")
    assert dp_row["status"] == "skipped_size"
    assert dp_row["prize"] == "" and dp_row["route"] == ""
    assert next(r for r in rows if r["algorithm"] == "ils")["status"] == "ok"
    assert "dp" not in traces


def test_solver_error_row(monkeypatch, capsys):
    def boom(problem, **kw):
        raise RuntimeError("kaput")
    monkeypatch.setitem(run.SOLVERS, "ils", boom)
    rows, _ = run.run_instance(syn(10), ("ils", "dp"), [0], 18, 5.0, solver_kwargs=FAST)
    assert next(r for r in rows if r["algorithm"] == "ils")["status"] == "error"
    assert next(r for r in rows if r["algorithm"] == "dp")["status"] == "ok"
    assert "kaput" in capsys.readouterr().err


def test_empty_route_instance():
    inst = syn(10)
    inst.problem.budget = 0.0
    rows, _ = run.run_instance(inst, ("dp", "ils", "sa"), [0], 18, 5.0, solver_kwargs=FAST)
    for r in rows:
        assert r["status"] == "ok" and r["prize"] == 0.0 and r["gap_pct"] == 0.0
        assert set(r["route"].split("-")) <= {"habitat", ""} and r["n_visited"] == 0 and r["feasible"] is True
        assert r["budget_used_pct"] == ""
        assert not any(isinstance(v, float) and v != v for v in r.values())


def test_run_suite_writes_files(tmp_path):
    root = tmp_path / "inst"
    datasets.save(syn(10), root)
    datasets.save(syn(14, "windows"), root)
    out = run.run_suite(["syn-energy-n10-0", "syn-windows-n14-0"], ("dp", "ils", "sa"), [0, 1],
                        18, 5.0, tmp_path / "out", instances_root=root, solver_kwargs=FAST)
    assert out == tmp_path / "out"
    with open(out / "runs.csv", newline="", encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    assert list(rows[0]) == run.RUN_COLUMNS and len(rows) == 8
    with open(out / "instances.csv", newline="", encoding="utf-8") as f:
        inst_rows = list(csv.DictReader(f))
    assert [r["instance"] for r in inst_rows] == ["syn-energy-n10-0", "syn-windows-n14-0"]
    assert inst_rows[0]["reference_kind"] == "dp_optimal"
    cfg = json.loads((out / "config.json").read_text(encoding="utf-8"))
    assert cfg["dp_max"] == 18 and cfg["cpsat_limit_s"] == 5.0 and "platform" in cfg
    assert "sa" in cfg["solvers"] and "ortools" in cfg
    with open(out / "traces" / "trace_sa.csv", newline="", encoding="utf-8") as f:
        tr = list(csv.DictReader(f))
    assert list(tr[0])[:2] == ["instance", "seed"] and {r["seed"] for r in tr} == {"0", "1"}
    assert (out / "traces" / "trace_dp.csv").exists()


# ---------------------------------------------------------------- analysis (Task 8)

from orienteering.lab import analyze  # noqa: E402


def arow(alg, n, gap, runtime, evals=None, instance="i", seed=0, status="ok", opt=None):
    return {"instance": instance, "n": n, "algorithm": alg, "seed": seed, "status": status,
            "gap_pct": gap, "runtime_s": runtime, "evaluations": evals,
            "is_optimal": gap == 0 if opt is None else opt}


def test_size_bucket_edges():
    assert [analyze.size_bucket(n) for n in (10, 20, 21, 50, 51, 80, 81, 100, 200)] == [
        "10-20", "10-20", "21-50", "21-50", "51-80", "51-80", "81-200", "81-200", "81-200"]


def test_summarize_known_values():
    runs = [arow("ils", 12, 0.0, 1.0, 100), arow("ils", 12, 2.0, 3.0, 300, seed=1),
            arow("ils", 12, 4.0, 5.0, "", seed=2),            # empty evaluations are ignored
            arow("sa", 30, 5.0, 2.0, 50),
            arow("sa", 30, "", "", "", status="error"),       # not counted
            arow("sa", 30, "", "", "", status="skipped_size")]
    rows = {(r["algorithm"], r["size_bucket"]): r for r in analyze.summarize(runs)}
    assert set(rows) == {("ils", "10-20"), ("sa", "21-50")}
    ils = rows[("ils", "10-20")]
    assert ils["runs"] == 3 and ils["mean_gap_pct"] == pytest.approx(2.0)
    assert ils["median_gap_pct"] == pytest.approx(2.0) and ils["std_gap_pct"] == pytest.approx(2.0)
    assert ils["optimal_share"] == pytest.approx(1 / 3)
    assert ils["mean_runtime_s"] == pytest.approx(3.0) and ils["median_runtime_s"] == pytest.approx(3.0)
    assert ils["mean_evaluations"] == pytest.approx(200.0)
    sa = rows[("sa", "21-50")]
    assert sa["runs"] == 1 and sa["std_gap_pct"] == 0.0 and sa["optimal_share"] == 0.0


def stat_runs(n_inst=6):
    rng = np.random.default_rng(0)
    runs = []
    for i in range(n_inst):
        for k, alg in enumerate(("ils", "sa", "aco", "ga")):
            for seed in (0, 1):
                runs.append(arow(alg, 12, float(k + rng.random() * 2), 1.0, instance=f"i{i}", seed=seed))
    return runs


def test_stats_holm_monotone():
    rows = analyze.stats(stat_runs())
    assert rows[0]["a"] == "friedman" and rows[0]["b"] == "" and rows[0]["n_instances"] == 6
    assert rows[0]["p_holm"] == rows[0]["p_value"] and rows[0]["p_value"] < 0.05
    pairs = rows[1:]
    assert len(pairs) == 6
    assert all(r["p_holm"] >= r["p_value"] - 1e-12 and r["p_holm"] <= 1.0 for r in pairs)
    assert {(r["a"], r["b"]) for r in pairs} == {
        ("ils", "sa"), ("ils", "aco"), ("ils", "ga"), ("sa", "aco"), ("sa", "ga"), ("aco", "ga")}


def test_stats_all_equal_and_too_few(recwarn):
    runs = [arow(a, 12, 0.0, 1.0, instance=f"i{i}") for i in range(4)
            for a in ("ils", "sa", "aco", "ga")]
    rows = analyze.stats(runs)
    assert rows[0]["statistic"] == 0 and rows[0]["p_value"] == 1.0
    assert all(r["statistic"] == 0 and r["p_value"] == 1.0 and r["p_holm"] == 1.0 for r in rows[1:])
    one = analyze.stats([arow(a, 12, 1.0, 1.0) for a in ("ils", "sa", "aco", "ga")])
    assert len(one) == 1 and one[0]["a"] == "friedman" and one[0]["p_value"] == ""
    assert not [w for w in recwarn.list if "scipy" in str(w.filename)]


def test_split_route_with_hyphenated_ids():
    assert analyze.split_route("habitat-S-1-S2-habitat", ["habitat", "S-1", "S2"]) == [0, 1, 2, 0]
    assert analyze.split_route("", ["habitat"]) == []


def test_figures_written(tmp_path):
    root = tmp_path / "inst"
    datasets.save(syn(10), root)
    datasets.save(syn(14, "windows"), root)
    out = run.run_suite(["syn-energy-n10-0", "syn-windows-n14-0"], run.ALGORITHMS, [0, 1],
                        18, 5.0, tmp_path / "out", instances_root=root, solver_kwargs=FAST)
    result = analyze.analyze(out, instances_root=root)
    files = result["figures"]
    assert [p.name for p in files] == [
        "fig1_convergence.png", "fig2_quality_vs_time.png", "fig3_scalability.png",
        "fig4_gap_boxplots.png", "fig5_internal_dynamics.png", "fig6_routes.png",
        "fig7_performance_profile.png"]
    assert all(p.parent == out / "analysis" and p.stat().st_size > 5000 for p in files)
    for name in ("summary.csv", "stats.csv"):
        assert (out / "analysis" / name).stat().st_size > 0


def test_with_windows(tmp_path):
    base = datasets.synthetic(12, "energy", 0)
    base.problem.time = base.problem.energy.copy()
    base.problem.service_s = np.zeros(12)
    base.problem.max_duration_s = 100.0
    base.name, base.set = "real-n12-0-120min", "real"
    tw = datasets.with_windows(base, 1)
    w = tw.problem.windows
    assert tw.name == "realtw-n12-0-120min" and tw.set == "real-windows"
    assert w.shape == (12, 2) and list(w[0]) == [0.0, np.inf]
    late = w[:, 0] > 0
    assert np.all(w[late, 0] <= 50.0) and np.all(np.isinf(w[~late, 1]))
    widths = w[late, 1] - w[late, 0]
    assert np.all((widths >= 15.0) & (widths <= 50.0))
    assert np.array_equal(tw.problem.energy, base.problem.energy)
    assert tw.problem.max_duration_s == 100.0
    assert np.array_equal(datasets.with_windows(base, 1).problem.windows, w)   # seeded


def test_save_pool_roundtrip(tmp_path):
    rows = [{"id": "habitat", "type": "habitat", "x": 1.0, "y": 2.0, "prize": 0.0, "service_s": 0.0},
            {"id": "G1", "type": "ridge", "x": 3.0, "y": 4.0, "prize": 5.0, "service_s": 600.0}]
    path = datasets.save_pool(rows, tmp_path)
    assert path == tmp_path / "pool.csv"
    lines = path.read_text(encoding="utf-8").splitlines()
    assert lines[0] == "id,type,x,y,prize,service_s"
    assert lines[1].startswith("habitat,habitat,1.0,2.0") and lines[2].startswith("G1,ridge")
