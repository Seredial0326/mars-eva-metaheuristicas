"""Experiment runner of the metaheuristics lab: solvers x instances x seeds -> CSV files.

Run from the repo root (src must be importable):
    PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.run --suite quick
    PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.run --suite full --out some/dir

Output folder (default data/lab/runs/<YYYYmmdd-HHMMSS>/):
    runs.csv       one row per (instance, algorithm, seed), columns RUN_COLUMNS
    instances.csv  one row per instance with its reference (prize, kind, upper bound)
    config.json    solver parameters, ortools version, platform, dp_max, cpsat_limit_s
    traces/trace_<algorithm>.csv   per-iteration traces, long format (instance, seed first)

Order per instance: exact_reference (DP and/or CP-SAT, traced; their runs become the dp/cpsat
rows), the metaheuristics, finalize(), and only then gap_pct / is_optimal of every row.

Row semantics:
- status is "ok", "skipped_size" (n above the algorithm's limit, dp above --dp-max, or CP-SAT
  without ortools) or "error" (the solver raised; the message goes to stderr and the run
  continues). Skipped and error rows leave the run-metric fields empty; the instance-level
  reference fields are still filled.
- seed is empty for the deterministic dp, cpsat and ils.
- energy_wh = energy_j / 3600; budget_used_pct = 100 * energy_j / budget (empty if budget <= 0).
- distance_m sums the instance's distance matrix over the route legs (plane units for synthetic
  instances); walk_time_s sums problem.time over the legs (empty without problem.time);
  duration_s is Solution.duration_s (waiting and service included).
- n_visited counts distinct stations of the route other than start and end.
- is_optimal is `prize >= reference_prize - 1e-6` for every reference kind; with `best_known`
  it means "matched the best known", not "proved optimal".
- feasible is evaluate_route's verdict and energy <= budget + 1e-6 (an empty route is feasible).
"""
import argparse
import csv
import importlib.util
import inspect
import json
import platform
import sys
import time
from importlib import metadata
from pathlib import Path

from orienteering.lab import datasets
from orienteering.lab.datasets import INSTANCES, REPO
from orienteering.lab.reference import exact_reference, finalize, gap_pct
from orienteering.lab.trace import Tracer
from orienteering.problem import evaluate_route
from orienteering.solvers import MAX_STATIONS, SOLVERS

ALGORITHMS = ("dp", "cpsat", "ils", "sa", "aco", "ga")
SEEDED = {"sa", "aco", "ga"}
EXACT = ("dp", "cpsat")
TRACE_EVERY = {"sa": 20}                                    # the others trace every iteration
RUNS_DIR = REPO / "data" / "lab" / "runs"

RUN_COLUMNS = ["instance", "set", "kind", "n", "algorithm", "seed", "status", "prize",
               "reference_prize", "reference_kind", "upper_bound", "gap_pct", "is_optimal",
               "energy_j", "energy_wh", "budget_used_pct", "distance_m", "walk_time_s",
               "duration_s", "n_visited", "route", "runtime_s", "iterations", "evaluations",
               "feasible"]
INSTANCE_COLUMNS = ["instance", "set", "kind", "n", "budget", "max_duration_s",
                    "reference_prize", "reference_kind", "upper_bound"]

SUITES = {
    "quick": {"instances": ["real-n20-0-120min", "real-n20-0-180min"], "seeds": [0, 1, 2]},
    "full": {"instances": None, "seeds": [0, 1, 2]},    # None = every instance on disk
}


def _num(x, digits):
    """Rounded float for the CSV; None and non-finite values become the empty string."""
    if x is None or x != x or abs(x) == float("inf"):
        return ""
    return round(float(x), digits)


def _blank(inst, algorithm, seed, status):
    row = dict.fromkeys(RUN_COLUMNS, "")
    row.update({"instance": inst.name, "set": inst.set, "kind": inst.kind, "n": inst.problem.n,
                "algorithm": algorithm, "seed": seed, "status": status})
    return row


def _row(inst, algorithm, seed, sol):
    """The runs.csv row (reference fields still empty) of one finished solver run."""
    p = inst.problem
    route = list(sol.route)
    legs = list(zip(route, route[1:]))
    ev = evaluate_route(p, route)
    row = _blank(inst, algorithm, seed, "ok")
    row.update(
        prize=_num(sol.prize, 4),
        energy_j=_num(sol.energy, 1),
        energy_wh=_num(sol.energy / 3600.0, 2),
        budget_used_pct=_num(100.0 * sol.energy / p.budget, 2) if p.budget > 0 else "",
        distance_m=_num(sum(float(inst.distance[a][b]) for a, b in legs), 1),
        walk_time_s=(_num(sum(float(p.time[a][b]) for a, b in legs), 1)
                     if p.time is not None else ""),
        duration_s=_num(sol.duration_s, 1),
        n_visited=len(set(route) - {p.start, p.end}),
        route="-".join(inst.stations[k]["id"] for k in route),
        runtime_s=_num(sol.runtime_s, 4),
        iterations="" if sol.iterations is None else sol.iterations,
        evaluations="" if sol.evaluations is None else sol.evaluations,
        feasible=bool(ev["feasible"] and sol.energy <= p.budget + 1e-6),
    )
    return row


def _trace_rows(inst, seed, tracer):
    return [{"instance": inst.name, "seed": seed, **r} for r in tracer.rows]


def _run_instance(inst, algorithms, seeds, dp_max, cpsat_limit_s, solver_kwargs):
    """Returns (rows, traces, reference)."""
    kwargs = solver_kwargs or {}
    p = inst.problem
    tracers = {"dp": Tracer(), "cpsat": Tracer()}
    try:
        ref, exact_sols = exact_reference(p, dp_max=dp_max, cpsat_limit_s=cpsat_limit_s,
                                          tracers=tracers)
    except Exception as exc:                                # keep the batch alive
        print(f"ERROR {inst.name} exact_reference: {type(exc).__name__}: {exc}", file=sys.stderr)
        ref, exact_sols = None, []
    exact = {s.solver: s for s in exact_sols}
    have_ortools = importlib.util.find_spec("ortools") is not None

    entries = []                                            # (row, Solution | None)
    traces = {}
    for algorithm in algorithms:
        if algorithm in EXACT:
            limit = dp_max if algorithm == "dp" else MAX_STATIONS["cpsat"]
            if algorithm in exact:
                entries.append((_row(inst, algorithm, "", exact[algorithm]), exact[algorithm]))
                traces[algorithm] = _trace_rows(inst, "", tracers[algorithm])
            elif p.n > limit or (algorithm == "cpsat" and not have_ortools):
                entries.append((_blank(inst, algorithm, "", "skipped_size"), None))
            else:                                           # it should have run and did not
                entries.append((_blank(inst, algorithm, "", "error"), None))
            continue
        if p.n > MAX_STATIONS[algorithm]:
            entries.append((_blank(inst, algorithm, "", "skipped_size"), None))
            continue
        for seed in (seeds if algorithm in SEEDED else [""]):
            tracer = Tracer(every=TRACE_EVERY.get(algorithm, 1))
            args = dict(kwargs.get(algorithm, {}))
            if algorithm in SEEDED:
                args["seed"] = seed
            try:
                sol = SOLVERS[algorithm](p, trace=tracer, **args)
            except Exception as exc:                        # keep the batch alive
                print(f"ERROR {inst.name} {algorithm} seed={seed!r}: "
                      f"{type(exc).__name__}: {exc}", file=sys.stderr)
                entries.append((_blank(inst, algorithm, seed, "error"), None))
                continue
            entries.append((_row(inst, algorithm, seed, sol), sol))
            traces.setdefault(algorithm, []).extend(_trace_rows(inst, seed, tracer))

    # the reference comes from everything that ran, requested or not
    ran = list(exact_sols) + [s for _, s in entries if s is not None and s.solver not in exact]
    ref = finalize(ref, ran)
    rows = []
    for row, sol in entries:
        row.update(reference_prize=_num(ref.prize, 4), reference_kind=ref.kind,
                   upper_bound=_num(ref.upper_bound, 4))
        if sol is not None:
            row["gap_pct"] = _num(gap_pct(sol.prize, ref.prize), 4)
            row["is_optimal"] = bool(sol.prize >= ref.prize - 1e-6)
        rows.append(row)
    return rows, traces, ref


def run_instance(inst, algorithms, seeds, dp_max=18, cpsat_limit_s=120.0, solver_kwargs=None):
    """Run `algorithms` on `inst`; returns (runs.csv rows, {algorithm: long-format trace rows}).

    solver_kwargs maps an algorithm to extra keyword arguments for its solver (tests use it to
    shorten runs); it does not reach the exact runs made by exact_reference.
    """
    rows, traces, _ = _run_instance(inst, algorithms, seeds, dp_max, cpsat_limit_s, solver_kwargs)
    return rows, traces


def _write_csv(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns)
        writer.writeheader()
        writer.writerows(rows)


def _write_trace(path, rows):
    names = []
    for row in rows:
        names += [k for k in row if k not in names]
    _write_csv(path, names, rows)


def _solver_defaults(name):
    """Default keyword parameters of a solver, from its signature."""
    params = inspect.signature(SOLVERS[name]).parameters
    return {k: v.default for k, v in params.items()
            if v.default is not inspect.Parameter.empty and k not in ("seed", "trace")}


def _config(algorithms, seeds, dp_max, cpsat_limit_s):
    try:
        ortools_version = metadata.version("ortools")
    except metadata.PackageNotFoundError:
        ortools_version = None
    return {"algorithms": list(algorithms), "seeds": list(seeds), "dp_max": dp_max,
            "cpsat_limit_s": cpsat_limit_s, "ortools": ortools_version,
            "platform": platform.platform(), "python": platform.python_version(),
            "max_stations": {a: MAX_STATIONS[a] for a in algorithms},
            "trace_every": {a: TRACE_EVERY.get(a, 1) for a in algorithms},
            "solvers": {a: _solver_defaults(a) for a in algorithms}}


def run_suite(names, algorithms, seeds, dp_max=18, cpsat_limit_s=120.0, out_dir=None,
              instances_root=INSTANCES, solver_kwargs=None):
    """Run every instance in `names` and write runs.csv, instances.csv, config.json and
    traces/ into out_dir (default data/lab/runs/<timestamp>). Returns the folder."""
    out_dir = Path(out_dir) if out_dir else RUNS_DIR / time.strftime("%Y%m%d-%H%M%S")
    (out_dir / "traces").mkdir(parents=True, exist_ok=True)
    runs, inst_rows, traces = [], [], {}
    for i, name in enumerate(names, 1):
        inst = datasets.load(name, instances_root)
        t0 = time.time()
        rows, tr, ref = _run_instance(inst, algorithms, seeds, dp_max, cpsat_limit_s,
                                      solver_kwargs)
        runs += rows
        for algorithm, trows in tr.items():
            traces.setdefault(algorithm, []).extend(trows)
        p = inst.problem
        inst_rows.append({"instance": name, "set": inst.set, "kind": inst.kind, "n": p.n,
                          "budget": _num(p.budget, 1), "max_duration_s": _num(p.max_duration_s, 1),
                          "reference_prize": _num(ref.prize, 4), "reference_kind": ref.kind,
                          "upper_bound": _num(ref.upper_bound, 4)})
        print(f"[{i}/{len(names)}] {name} (n={p.n}): {len(rows)} rows, reference "
              f"{ref.prize:.4f} ({ref.kind}), {time.time() - t0:.1f} s", flush=True)
    _write_csv(out_dir / "runs.csv", RUN_COLUMNS, runs)
    _write_csv(out_dir / "instances.csv", INSTANCE_COLUMNS, inst_rows)
    for algorithm, trows in traces.items():
        _write_trace(out_dir / "traces" / f"trace_{algorithm}.csv", trows)
    (out_dir / "config.json").write_text(
        json.dumps(_config(algorithms, seeds, dp_max, cpsat_limit_s), indent=2, default=str),
        encoding="utf-8")
    return out_dir


def parse_seeds(text):
    """'0-9' -> 0..9; '0,2,5' -> [0, 2, 5]; both forms may be mixed ('0-2,7')."""
    seeds = []
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        seeds += list(range(int(lo), int(hi) + 1)) if hi else [int(lo)]
    return seeds


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--suite", choices=sorted(SUITES), required=True)
    ap.add_argument("--instances", help="comma-separated instance names (overrides the suite)")
    ap.add_argument("--algorithms", default=",".join(ALGORITHMS))
    ap.add_argument("--seeds", help="e.g. 0-9 or 0,3,5 (default: the suite's)")
    ap.add_argument("--dp-max", type=int, default=18)
    ap.add_argument("--cpsat-limit", type=float, default=120.0)
    ap.add_argument("--out", help="output folder (default data/lab/runs/<timestamp>)")
    ap.add_argument("--instances-dir", default=str(INSTANCES),
                    help="folder with the instances (default data/lab/instances)")
    args = ap.parse_args(argv)
    root = Path(args.instances_dir)

    suite = SUITES[args.suite]
    names = args.instances.split(",") if args.instances else suite["instances"]
    if names is None:
        names = sorted(p.stem for p in root.glob("*.npz"))
    algorithms = [a.strip() for a in args.algorithms.split(",") if a.strip()]
    unknown = [a for a in algorithms if a not in ALGORITHMS]
    if unknown:
        ap.error(f"unknown algorithms: {unknown}")
    seeds = parse_seeds(args.seeds) if args.seeds else suite["seeds"]
    out = run_suite(names, algorithms, seeds, args.dp_max, args.cpsat_limit, args.out,
                    instances_root=root)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
