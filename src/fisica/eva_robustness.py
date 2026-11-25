"""C1 (#120): paired, sequential energy-policy experiments; simulation only.

Input: explicit events and segmented minimum-energy returns at every checkpoint.
No policies query future realised consumption. Random worlds are generated before
evaluating policies, so stopping early cannot change another policy's samples.
This is an offline evaluator, not a replacement for the operational API (#119).
"""

import argparse
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import subprocess
import sys
from statistics import NormalDist

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fisica import adaptive_k as ak


@dataclass(frozen=True)
class Event:
    predicted_wh: float
    return_segments_wh: tuple[float, ...]
    kind: str = "walk"
    science: float = 0.0


@dataclass(frozen=True)
class Plan:
    events: tuple[Event, ...]
    capacity_wh: float
    reserve_wh: float
    provenance: dict

    def __post_init__(self):
        if not self.events:
            raise ValueError("plan needs at least one event")
        if not (math.isfinite(self.capacity_wh) and self.capacity_wh > 0
                and math.isfinite(self.reserve_wh)
                and 0 <= self.reserve_wh < self.capacity_wh):
            raise ValueError("finite capacity > reserve >= 0 required")
        for e in self.events:
            if e.kind not in ("walk", "service", "wait"):
                raise ValueError("unsupported event kind")
            if any(not math.isfinite(v) or v < 0 for v in
                   (e.predicted_wh, e.science, *e.return_segments_wh)):
                raise ValueError("event costs and science must be finite and nonnegative")
            if e.science and e.kind != "service":
                raise ValueError("science is awarded only after service")
        if self.events[-1].return_segments_wh:
            raise ValueError("final event must arrive at habitat (empty return)")

    @property
    def usable_wh(self):
        return self.capacity_wh - self.reserve_wh


def load_plan(path):
    doc = json.loads(Path(path).read_text(encoding="utf-8"))
    if doc.get("schema_version") != 1:
        raise ValueError("unsupported experiment input schema")
    events = tuple(Event(float(e["predicted_wh"]),
                         tuple(float(v) for v in e["return_segments_wh"]),
                         e.get("kind", "walk"), float(e.get("science", 0)))
                   for e in doc["events"])
    return Plan(events, float(doc["capacity_wh"]), float(doc["reserve_wh"]),
                doc.get("provenance", {}))


def synthetic_plan():
    """Explicit provisional fixture: two stations, not a Gale measurement."""
    return Plan((Event(10, (10,)), Event(12, (10,), "service", 3),
                 Event(10, (10, 10)), Event(18, (10, 10), "service", 5),
                 Event(10, (10,)), Event(10, ())), 90, 9,
                {"type": "synthetic", "name": "two-station energy fixture",
                 "warning": "not a real terrain plan or human validation"})


def correlated_noise(rng, count, sigma, rho, initial=None):
    """Stationary AR(1) log noise; returns continue the last outbound state."""
    noise = np.empty(count)
    state = rng.normal(0, sigma) if initial is None else initial
    for i in range(count):
        if i or initial is not None:
            state = rho * state + math.sqrt(1 - rho * rho) * rng.normal(0, sigma)
        noise[i] = state
    return noise


def realised_world(plan, rng, k_true, sigma, rho):
    log_noise = correlated_noise(rng, len(plan.events), sigma, rho)
    costs = np.array([e.predicted_wh for e in plan.events]) * k_true * np.exp(log_noise)
    # Indexed by checkpoint (0 = habitat), identical for every policy that returns
    # there. Separate draws for different checkpoints are declared counterfactuals.
    returns = [np.empty(0)]
    for i, e in enumerate(plan.events):
        noise = correlated_noise(rng, len(e.return_segments_wh), sigma, rho, log_noise[i])
        returns.append(np.array(e.return_segments_wh) * k_true * np.exp(noise))
    return costs, returns


def evaluate(plan, costs, returns, policy, *, sigma_obs=ak.SIGMA_OBS,
             quantile=0.90, k_true=1.0):
    """Run one policy with observations from its own executed prefix only.

    Reserve failure means usable energy was insufficient for the realised escape
    at an executed checkpoint or on the chosen finish. Negative arrival margins
    are counterfactual required energy, not a physical arrival after exhaustion.
    """
    if policy not in ("nominal", "conservative", "adaptive"):
        raise ValueError("unknown policy")
    post = ak.prior()
    used, science, completed = 0.0, 0.0, 0
    failed_event = False
    min_escape_margin = plan.usable_wh
    fixed_k = 1.0 if policy == "nominal" else ak.quantile(post, quantile)
    for i, e in enumerate(plan.events):
        k = ak.quantile(post, quantile) if policy == "adaptive" else fixed_k
        # Test BEFORE moving/working, including the entire next service interval.
        need = e.predicted_wh + sum(e.return_segments_wh)
        if used + k * need > plan.usable_wh:
            break
        used += float(costs[i])
        completed += 1
        if used > plan.capacity_wh:
            # Full event + escape cost remains a counterfactual requirement; no
            # completed science or measurement is credited after depletion.
            failed_event = True
            break
        science += e.science
        post = ak.update(post, float(costs[i]), e.predicted_wh, sigma_obs)
        escape = float(np.sum(returns[completed]))
        min_escape_margin = min(min_escape_margin, plan.usable_wh - used - escape)
    home_cost = float(np.sum(returns[completed]))
    final_used = used + home_cost
    min_escape_margin = min(min_escape_margin, plan.usable_wh - final_used)
    lo, hi = ak.interval(post, 0.90)
    return {
        "reserve_violated": min_escape_margin < -1e-9,
        "capacity_exceeded": final_used > plan.capacity_wh + 1e-9,
        "arrival_margin_wh": plan.usable_wh - final_used,
        "min_escape_margin_wh": min_escape_margin,
        "science": science, "turned_back": completed < len(plan.events) and not failed_event,
        "events_completed": completed - int(failed_event), "observations": post.n,
        "depleted_during_event": failed_event,
        "habitat_reached": final_used <= plan.capacity_wh,
        "ci90_covers_k": lo <= k_true <= hi,
        "ci90_width": hi - lo,
    }


METRICS = ("reserve_violated", "capacity_exceeded", "arrival_margin_wh",
           "min_escape_margin_wh", "science", "turned_back", "ci90_covers_k")


def mean_interval(values, indices):
    """Percentile bootstrap over independent EVA worlds, never over vertices."""
    a = np.asarray(values, dtype=float)
    samples = a[indices].mean(axis=1)
    return {"mean": float(a.mean()), "ci95": np.quantile(samples, [.025, .975]).tolist(),
            "method": "paired-world percentile bootstrap"}


def proportion_interval(values):
    """Wilson score interval keeps nonzero uncertainty at zero/all failures."""
    a = np.asarray(values, dtype=float)
    n, p = len(a), float(a.mean())
    z = NormalDist().inv_cdf(.975)
    den = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / den
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / den
    return {"mean": p, "ci95": [max(0., centre - half), min(1., centre + half)],
            "method": "Wilson score over independent EVA worlds"}


def experiment(plan, *, runs=300, seed=120, sigma=0.15, rho=0.0,
               k_true=1.2, bootstrap=1000, policies=None):
    if runs < 2 or bootstrap < 100 or seed < 0:
        raise ValueError("runs >= 2, bootstrap >= 100, seed >= 0 required")
    if not (math.isfinite(k_true) and k_true > 0 and math.isfinite(sigma)
            and sigma >= 0 and math.isfinite(rho) and abs(rho) < 1):
        raise ValueError("positive k_true, nonnegative sigma and abs(rho) < 1 required")
    names = tuple(policies or ("nominal", "conservative", "adaptive"))
    if len(set(names)) != len(names) or set(names) != {"nominal", "conservative", "adaptive"}:
        raise ValueError("exactly three distinct policies required")
    rows = {name: [] for name in names}
    seeds = np.random.SeedSequence(seed).spawn(runs + 1)
    for run in range(runs):
        costs, returns = realised_world(plan, np.random.default_rng(seeds[run]), k_true, sigma, rho)
        for name in names:
            result = evaluate(plan, costs, returns, name, k_true=k_true)
            rows[name].append({"world": run, **result})
    indices = np.random.default_rng(seeds[-1]).integers(0, runs, (bootstrap, runs))
    summary = {}
    paired = {}
    for name in names:
        summary[name] = {m: mean_interval([r[m] for r in rows[name]], indices) for m in METRICS}
        for m in ("reserve_violated", "capacity_exceeded", "turned_back", "ci90_covers_k"):
            summary[name][m] = proportion_interval([r[m] for r in rows[name]])
        if name != "nominal":
            paired[name + "_minus_nominal"] = {
                m: mean_interval([float(a[m]) - float(b[m])
                                  for a, b in zip(rows[name], rows["nominal"])], indices)
                for m in METRICS}
    return {"settings": {"runs": runs, "seed": seed, "k_true": k_true,
                         "sigma_log": sigma, "rho_log": rho, "bootstrap": bootstrap,
                         "filter_sigma_assumed": ak.SIGMA_OBS,
                         "quantile": .9, "prior_sd": ak.PRIOR_SD,
                         "worst_case_binomial_95_half_width_approx": 1.96 / math.sqrt(4 * runs)},
            "policies": summary, "paired_differences": paired, "rows": rows}


def file_sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def export_saved_plan(saved_path, output_path, segment_m=30):
    """Export an E5 saved tour using exact E4 return paths (no API changes).

    Walking checkpoints are approximately segment_m apart (up to one extra grid
    edge), with explicit service events. Returns use the same walking scale.
    Waiting requires a power model and is rejected. Reject mismatching graph
    profiles instead of silently evaluating a different cost model.
    """
    if not math.isfinite(segment_m) or segment_m < 2:
        raise ValueError("segment_m must be finite and >= 2")
    from api import planner
    from grafos.graph import follow
    from fisica.human_cost import is_slope
    repo = Path(__file__).resolve().parents[2]
    saved_path = Path(saved_path)
    saved = json.loads(saved_path.read_text(encoding="utf-8"))
    request, fc = saved["request"], saved["plan"]
    line = next(f for f in fc["features"] if f["properties"].get("kind") == "route")
    p = line["properties"]
    if p.get("feasible") is not True:
        raise ValueError("export requires a feasible E5 tour")
    g = planner.graph(str(repo / "data/base"), request.get("max_cell_slope_deg", 30),
                      request.get("human_cost", True))
    nodes = []
    for x, y in line["geometry"]["coordinates"]:
        row, col, moved = g.place(x, y)
        if moved > .01:
            raise ValueError("route no longer matches current graph")
        nodes.append(int(g.node(row, col)))
    if nodes[0] != nodes[-1]:
        raise ValueError("tour must end at its habitat")
    walking = g.path_cost(np.asarray(nodes), "energy_j") / 3600
    distance = g.path_cost(np.asarray(nodes), "length_m")
    rv, pred = g.costs_to(nodes[0], "energy_j", predecessors=True)
    if not np.allclose(rv[nodes] / 3600, p["rv_wh"], atol=.02, rtol=0):
        raise ValueError("saved return profile differs from current graph")
    stops = [f["properties"] for f in fc["features"] if f["properties"].get("kind") == "stop"]
    indices = p.get("stop_index", [])
    if len(stops) != len(indices):
        raise ValueError("stop metadata required to separate service and walking")
    service_power = p.get("service_power_w")
    if service_power is None:
        raise ValueError("explicit service power required")
    at = {}
    cumulative_service = np.zeros(len(nodes))
    for stop, index in zip(stops, indices):
        if stop.get("wait_s", 0):
            raise ValueError("waiting needs an explicit power model; not supported by exporter yet")
        energy = stop["service_time_min"] * float(service_power) / 60
        at.setdefault(index, []).append((energy, float(stop["score"])))
        cumulative_service[index:] += energy
    if not np.allclose(walking + cumulative_service, p["used_wh"], atol=.02, rtol=0):
        raise ValueError("walking/service split differs from saved energy profile")
    checkpoints = [0]
    for i in range(1, len(nodes)):
        if (distance[i] - distance[checkpoints[-1]] >= segment_m or i in at
                or i == len(nodes) - 1):
            checkpoints.append(i)
    events = []
    for before, i in zip(checkpoints, checkpoints[1:]):
        home = follow(pred, nodes[i], end=nodes[0]) if nodes[i] != nodes[0] else np.array([nodes[0]])
        returns = []
        if len(home) > 1:
            he = g.path_cost(home, "energy_j") / 3600
            hd = g.path_cost(home, "length_m")
            start = 0
            for j in range(1, len(home)):
                if hd[j] - hd[start] >= segment_m or j == len(home) - 1:
                    returns.append(float(he[j] - he[start]))
                    start = j
        events.append(Event(float(walking[i] - walking[before]), tuple(returns)))
        for energy, science in at.get(i, []):
            events.append(Event(energy, tuple(returns), "service", science))
    capacity = float(request["energy_budget_wh"])
    usable = float(p["usable_wh"])
    data_files = [repo / "data/base" / name for name in
                  ("grid.json", "crs.wkt", "dem_1m.tif", "slope_deg.tif")]
    weights = planner.e1_weights_path(repo / "data/base") if request.get("human_cost", True) else None
    if weights:
        data_files.append(weights)
        spec = json.loads(weights.read_text(encoding="utf-8"))
        data_files.extend((repo / "data/base" / f["raster"]).resolve()
                          for name, f in spec["features"].items()
                          if not is_slope(name, f))
    # E5 may tighten energy by an equivalent O2 budget: retain that usable limit.
    plan = Plan(tuple(events), capacity, capacity - usable, {
        "type": "exported_E5", "source": str(saved_path),
        "source_sha256": hashlib.sha256(saved_path.read_bytes()).hexdigest(),
        "cost_model": g.cost_model, "request": request, "segment_m": segment_m,
        "checks": "walking + service and exact E4 returns match saved arrays within 0.02 Wh",
        "data_sha256": {str(f.relative_to(repo)): file_sha256(f) for f in data_files},
    })
    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps({"schema_version": 1, **asdict(plan)}, indent=2), encoding="utf-8")
    return plan


def figure(report, target):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    names = ["nominal", "conservative", "adaptive"]
    for ax, metric, label in zip(axes, ["reserve_violated", "science"],
                                 ["Usable-reserve violation share", "Science completed (points)"]):
        for j, name in enumerate(names):
            s = report["policies"][name][metric]
            lo, hi = s["ci95"]
            ax.plot(j, s["mean"], "o", color="#235789")
            ax.vlines(j, lo, hi, color="#235789")
        ax.set_xticks(range(3), names)
        ax.set_ylabel(label)
        ax.spines[["top", "right"]].set_visible(False)
    fig.suptitle("Simulation only: " + report["input"]["provenance"].get("type", "unspecified")
                 + f"; k={report['settings']['k_true']}, rho={report['settings']['rho_log']}")
    fig.tight_layout()
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(target, dpi=140)
    plt.close(fig)


def report_table(report):
    lines = ["# C1: simulated energy-policy comparison", "",
             "Simulation only. Rates count independent EVA worlds; reserve violation is not capacity exhaustion.",
             "", f"Worlds per policy: {report['settings']['runs']}; seed: {report['settings']['seed']}.",
             "", "| Policy | Reserve violation (95% Wilson CI) | Capacity exceeded | Science mean | Margin mean (Wh) |",
             "|---|---|---|---|---|"]
    for name in ("nominal", "conservative", "adaptive"):
        row = report["policies"][name]
        rate = row["reserve_violated"]
        lo, hi = rate["ci95"]
        lines.append(f"| {name} | {100 * rate['mean']:.2f}% ({100 * lo:.2f}–{100 * hi:.2f}%) "
                     f"| {100 * row['capacity_exceeded']['mean']:.2f}% "
                     f"| {row['science']['mean']:.3f} | {row['arrival_margin_wh']['mean']:.3f} |")
    delta = report["paired_differences"]["adaptive_minus_nominal"]["reserve_violated"]
    lo, hi = delta["ci95"]
    lines += ["", f"Adaptive minus nominal reserve-violation difference: {100 * delta['mean']:.2f} "
              f"percentage points (95% paired-world bootstrap: {100 * lo:.2f} to {100 * hi:.2f}).", "",
              "Source: src/fisica/eva_robustness.py → summary.json and walks.jsonl in this directory.", ""]
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument("--synthetic", action="store_true")
    source.add_argument("--plan", type=Path)
    source.add_argument("--saved-plan", type=Path, help="export saved E5 tour using current graph")
    parser.add_argument("--out", type=Path, default=Path("data/robustness/c1"))
    parser.add_argument("--runs", type=int, default=300)
    parser.add_argument("--seed", type=int, default=120)
    parser.add_argument("--k-true", type=float, default=1.2)
    parser.add_argument("--rho", type=float, default=0.0)
    parser.add_argument("--sigma", type=float, default=.15)
    parser.add_argument("--bootstrap", type=int, default=1000)
    parser.add_argument("--figure", type=Path)
    args = parser.parse_args()
    args.out.mkdir(parents=True, exist_ok=True)
    if args.saved_plan:
        sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
        plan = export_saved_plan(args.saved_plan, args.out / "input.json")
    else:
        plan = synthetic_plan() if args.synthetic else load_plan(args.plan)
    input_doc = {"schema_version": 1, **asdict(plan)}
    input_bytes = json.dumps(input_doc, sort_keys=True).encode()
    report = experiment(plan, runs=args.runs, seed=args.seed, k_true=args.k_true,
                        rho=args.rho, sigma=args.sigma, bootstrap=args.bootstrap)
    rows = report.pop("rows")
    report.update(schema_version=1, input=input_doc,
                  input_sha256=hashlib.sha256(input_bytes).hexdigest(),
                  script="src/fisica/eva_robustness.py", python=sys.version,
                  script_sha256=file_sha256(Path(__file__)),
                  filter_sha256=file_sha256(Path(ak.__file__)),
                  numpy=np.__version__,
                  commit=subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                  tracked_worktree_dirty=bool(subprocess.check_output(
                      ["git", "status", "--porcelain", "--untracked-files=no"], text=True).strip()),
                  warnings=["Simulation, not astronaut validation; energy only; no time/speed/leak model.",
                            "k_true is the lognormal median multiplier, not its arithmetic mean.",
                            "AR(1) noise is a stress test; the filter still assumes independent noise.",
                            "Return draws are shared at equal checkpoints; different abort points use counterfactual return branches.",
                            "Marginal binary rates use Wilson intervals; paired differences use world bootstrap and can be degenerate with no discordance.",
                            "No operational guarantee between checkpoints; #119 is not replaced by this evaluator."])
    (args.out / "input.json").write_text(json.dumps(input_doc, indent=2), encoding="utf-8")
    (args.out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    (args.out / "table.md").write_text(report_table(report), encoding="utf-8")
    with (args.out / "walks.jsonl").open("w", encoding="utf-8") as stream:
        for policy, results in rows.items():
            for row in results:
                stream.write(json.dumps({"policy": policy, **row}) + "\n")
    if args.figure:
        figure(report, args.figure)
    print(args.out / "summary.json")


if __name__ == "__main__":
    main()
