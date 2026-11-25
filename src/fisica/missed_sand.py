"""C2 (#120): operational sensitivity to spatially missed sand, offline only.

Segmentation scenarios and energy-penalty assumptions are crossed separately.
Validation labels locate hypothetical patches in SW-S; they are not an exhaustive
ground-truth map. The conservative policy uses only the nominal sand map, not
these labels or the realised hidden field. No official raster or API is changed.
"""
import argparse
import csv
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import rasterio
from scipy import ndimage
from scipy.sparse.csgraph import dijkstra

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from fisica.edge_cost import NEIGHBOURS, edge_costs
from fisica.human_cost import human_edge_costs, load_rasters, load_weights, terrain_factor
from grafos.graph import Graph, follow


def sha256(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for part in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(part)
    return digest.hexdigest()


def missed_sites(points, shape, block_m=20):
    """Deduplicate missed sand labels in spatial blocks; 0.25 m -> 1 m cells."""
    groups = {}
    labels = 0
    for p in points:
        if int(p["answer"]) != 2 or int(p["stratum"]) == 2:
            continue
        r, c = int(p["row"]) // 4, int(p["col"]) // 4
        if not (0 <= r < shape[0] and 0 <= c < shape[1]):
            raise ValueError("label does not fall on the base grid")
        groups.setdefault((r // block_m, c // block_m), []).append((r, c))
        labels += 1
    sites = np.array([np.mean(v, axis=0) for _, v in sorted(groups.items())]).reshape(-1, 2)
    return sites, labels


def hidden_field(sand, sites, radius_m, seed, support=None, presence=.5):
    """One hypothetical world: spatial disks sampled by label block, not pixel.

    Radius and presence are assumptions. The nominal fraction is retained; only
    the remaining fraction can be hidden. Returned array is never written over E8.
    """
    if radius_m <= 0 or not 0 <= presence <= 1:
        raise ValueError("radius > 0 and presence in [0,1] required")
    rng = np.random.default_rng(seed)
    field = np.zeros(sand.shape, dtype=np.float32)
    for row, col in sites:
        if rng.random() > presence:
            continue
        row, col = np.array([row, col]) + rng.uniform(-radius_m / 3, radius_m / 3, 2)
        r0, r1 = max(0, int(row - radius_m)), min(sand.shape[0], int(row + radius_m) + 1)
        c0, c1 = max(0, int(col - radius_m)), min(sand.shape[1], int(col + radius_m) + 1)
        rr, cc = np.ogrid[r0:r1, c0:c1]
        field[r0:r1, c0:c1] = np.maximum(field[r0:r1, c0:c1],
                                        ((rr - row) ** 2 + (cc - col) ** 2 <= radius_m ** 2))
    field *= 1 - np.nan_to_num(np.clip(sand, 0, 1), nan=0)
    if support is not None:
        field *= support
    return field


def conservative_proxy(sand, scale_m=20):
    """A declared image-only precaution: unknown sand may neighbour known sand.

    This does not recover confidently missed sand far from detections and is not
    a calibrated probability. No validation labels are consumed here.
    """
    if not np.any(np.nan_to_num(sand) > 0):
        return np.zeros(sand.shape)
    distance = ndimage.distance_transform_edt(~(np.nan_to_num(sand) > 0))
    return .5 * np.exp(-(distance / scale_m) ** 2) * (1 - np.nan_to_num(sand))


def arrival_scaled(csr, factor):
    """Use the existing E1 arrival-cell convention with bounded temporaries."""
    out = csr.copy()
    flat = np.asarray(factor).ravel()
    if flat.size != csr.shape[0] or np.any(~np.isfinite(flat)) or np.any(flat < 1):
        raise ValueError("finite arrival factors >=1 required")
    for start in range(0, len(out.data), 1_000_000):
        end = start + 1_000_000
        out.data[start:end] *= flat[out.indices[start:end]]
    return out


def loop_metrics(csr, path, hidden, beta, usable_wh):
    path = np.asarray(path, dtype=int)
    if len(path) < 2 or path[0] != path[-1]:
        raise ValueError("margin identity requires a closed positive-cost loop")
    if beta < 0 or not np.isfinite(beta):
        raise ValueError("beta must be finite and nonnegative")
    edge_wh = np.asarray(csr[path[:-1], path[1:]]).ravel() / 3600
    if np.any(edge_wh <= 0):
        raise ValueError("path must follow positive edges")
    extra = np.asarray(hidden).ravel()[path[1:]]
    energy = float(np.sum(edge_wh * (1 + beta * extra)))
    # For a complete loop, true minimum return R(v) cannot exceed its remaining
    # suffix. Hence max_v(used(v)+R(v)) = total energy, attained at the habitat.
    # This is an evaluation identity, not an operational alarm or a new R raster.
    return {"actual_wh": energy, "margin_wh": float(usable_wh - energy),
            "reserve_violated": energy > usable_wh + 1e-9,
            "hidden_arrival_cells": float(extra.sum())}


def route_overlap(a, b):
    left, right = set(zip(a[:-1], a[1:])), set(zip(b[:-1], b[1:]))
    return len(left & right) / len(left | right) if left | right else 1.


def paths(csr, habitat, goals):
    _, outbound = dijkstra(csr, indices=habitat, return_predecessors=True)
    _, home = dijkstra(csr.T.tocsr(), indices=habitat, return_predecessors=True)
    result = {}
    for name, node in goals:
        if node == habitat or outbound[node] < 0 or home[node] < 0:
            continue
        a, b = follow(outbound, node, habitat)[::-1], follow(home, node, habitat)
        result[name] = np.concatenate([a, b[1:]])
    return result


def mean_ci(values, bootstrap_seed=1202):
    a = np.asarray(values, dtype=float)
    rng = np.random.default_rng(bootstrap_seed)
    means = a[rng.integers(0, len(a), (1000, len(a)))].mean(axis=1)
    return {"mean": float(a.mean()), "ci95": np.quantile(means, [.025, .975]).tolist(),
            "unit": "one spatial world (all goals aggregated before bootstrap)"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--worlds", type=int, default=30)
    parser.add_argument("--seed", type=int, default=1202)
    parser.add_argument("--radii", type=float, nargs="+", default=[5, 15, 30])
    parser.add_argument("--betas", type=float, nargs="+", default=[.115, 1.])
    parser.add_argument("--budget-ratio", type=float, default=1.10)
    parser.add_argument("--figure", type=Path)
    args = parser.parse_args()
    if (args.worlds < 2 or args.seed < 0 or not np.isfinite(args.budget_ratio)
            or args.budget_ratio <= 0 or any(not np.isfinite(b) or b < 0 for b in args.betas)
            or any(not np.isfinite(r) or r <= 0 for r in args.radii)):
        raise ValueError("worlds >=2, positive budget ratio and nonnegative beta required")
    data = args.data.resolve()
    with rasterio.open(data / "base/dem_1m.tif") as src:
        dem, transform = src.read(1).astype(float), src.transform
    with rasterio.open(data / "base/slope_deg.tif") as src:
        slope = src.read(1)
        if slope.shape != dem.shape or src.transform != transform:
            raise ValueError("slope does not match base grid")
    with rasterio.open(data / "e8/sand.tif") as src:
        sand = src.read(1)
        if sand.shape != dem.shape or src.transform != transform:
            raise ValueError("sand does not match base grid")
    time_s, energy, _ = edge_costs(dem, cell_slope_deg=slope, max_cell_slope_deg=30)
    spec = load_weights(data / "e1/e1_weights.json")
    factor = terrain_factor(spec, load_rasters(spec, data / "base"), dem.shape)
    energy = human_edge_costs(energy, factor, NEIGHBOURS)
    graph = Graph({"energy_j": energy, "time_s": time_s}, NEIGHBOURS, transform=tuple(transform),
                  crs_wkt=(data / "base/crs.wkt").read_text())
    del energy, time_s, dem, slope, factor
    # Read existing station products without editing their owner modules.
    import geopandas as gpd
    hr, hc = graph.snap(graph.height // 2, graph.width // 2, graph.main_component())
    habitat = int(graph.node(hr, hc))
    goals = []
    for station_file in (data / "stations/stations_manual.gpkg", data / "stations/stations_e8.gpkg"):
        if station_file.exists():
            for _, station in gpd.read_file(station_file, layer="stations").iterrows():
                row, col, _ = graph.place(station.geometry.x, station.geometry.y)
                goals.append((str(station["id"]), int(graph.node(row, col))))
    if not goals:
        raise ValueError("existing stations are required")
    with (data / "e8/points.csv").open(newline="") as stream:
        sites, label_count = missed_sites(list(csv.DictReader(stream)), graph.shape)
    region = json.loads((data / "e8/points_strata.json").read_text())["val"]
    if region != "SW-S" or graph.shape != (2000, 2000):
        raise ValueError("this experiment's declared support is E8 SW-S on the 2 km base grid")
    support = np.zeros(graph.shape, dtype=bool)
    support[1500:, :1000] = True
    if not len(sites):
        raise ValueError("no missed labels; do not invent hidden sand sites")
    base = graph.csr("energy_j")
    nominal = paths(base, habitat, goals)
    proxy = conservative_proxy(sand)
    policies, route_rows = {}, []
    for beta in args.betas:
        weighted = arrival_scaled(base, 1 + beta * proxy)
        conservative = paths(weighted, habitat, goals)
        policies[beta] = {"nominal": nominal, "conservative": conservative}
        for name, route in conservative.items():
            baseline = nominal[name]
            cost = float(np.asarray(base[baseline[:-1], baseline[1:]]).sum() / 3600)
            planned = float(np.asarray(weighted[route[:-1], route[1:]]).sum() / 3600)
            nominal_on_candidate = float(np.asarray(base[route[:-1], route[1:]]).sum() / 3600)
            route_rows.append({"beta": beta, "goal": name,
                               "nominal_wh": cost, "conservative_nominal_wh": nominal_on_candidate,
                               "conservative_planned_wh": planned,
                               "budget_wh": args.budget_ratio * cost,
                               "conservative_declines": planned > args.budget_ratio * cost,
                               "edge_jaccard": route_overlap(baseline, route),
                               "length_delta_m": float(graph.path_cost(route, "length_m")[-1]
                                                       - graph.path_cost(baseline, "length_m")[-1])})
        del weighted
        print(f"planned beta={beta}, {len(conservative)} goals", flush=True)
    rows = []
    decisions = {(r["beta"], r["goal"]): not r["conservative_declines"] for r in route_rows}
    for radius in args.radii:
        for world in range(args.worlds):
            seed = args.seed + world  # same spatial draw across beta/policy comparisons
            hidden = hidden_field(sand, sites, radius, seed, support)
            for beta, planned in policies.items():
                for policy, goal_paths in planned.items():
                    for name, route in goal_paths.items():
                        baseline = nominal[name]
                        cost = float(np.asarray(base[baseline[:-1], baseline[1:]]).sum() / 3600)
                        info = loop_metrics(base, route, hidden, beta, args.budget_ratio * cost)
                        rows.append({"radius_m": radius, "world": world, "beta": beta,
                                     "policy": policy, "goal": name,
                                     "accepted": policy == "nominal" or decisions[(beta, name)], **info})
            if world % 10 == 0:
                print(f"radius={radius} world={world + 1}/{args.worlds}", flush=True)
    summaries = []
    for radius in args.radii:
        for beta in args.betas:
            for policy in ("nominal", "conservative"):
                case = [r for r in rows if (r["radius_m"], r["beta"], r["policy"]) == (radius, beta, policy)]
                accepted_goals = len({r["goal"] for r in case if r["accepted"]})
                record = {"radius_m": radius, "beta": beta, "policy": policy,
                          "candidate_goals": len(nominal), "accepted_goals": accepted_goals,
                          "counterfactual_includes_declined": accepted_goals < len(nominal)}
                for metric in ("actual_wh", "margin_wh", "reserve_violated", "hidden_arrival_cells"):
                    means = [np.mean([r[metric] for r in case if r["world"] == w]) for w in range(args.worlds)]
                    record[metric] = mean_ci(means)
                summaries.append(record)
    paired = []
    for radius in args.radii:
        for beta in args.betas:
            record = {"radius_m": radius, "beta": beta,
                      "comparison": "conservative minus nominal, candidate loops (including declined)"}
            for metric in ("actual_wh", "margin_wh", "reserve_violated", "hidden_arrival_cells"):
                delta = []
                for world in range(args.worlds):
                    case = [r for r in rows if (r["radius_m"], r["beta"], r["world"]) == (radius, beta, world)]
                    a = {r["goal"]: r[metric] for r in case if r["policy"] == "conservative"}
                    b = {r["goal"]: r[metric] for r in case if r["policy"] == "nominal"}
                    delta.append(np.mean([float(a[g]) - float(b[g]) for g in a]))
                record[metric] = mean_ci(delta)
            paired.append(record)
    sources = [data / f for f in ("base/dem_1m.tif", "base/slope_deg.tif", "base/grid.json",
                                  "e1/e1_weights.json", "e1/sand_mean_5m.tif", "e8/sand.tif",
                                  "e8/points.csv", "e8/points_strata.json")]
    sources += [p for p in (data / "stations/stations_manual.gpkg", data / "stations/stations_e8.gpkg") if p.exists()]
    report = {"settings": {"worlds": args.worlds, "seed": args.seed, "radii_m": args.radii,
                           "betas": args.betas, "presence_probability_assumed": .5,
                           "budget_ratio_assumed": args.budget_ratio, "label_block_m": 20,
                           "conservative_proxy_scale_m": 20, "support": "SW-S only"},
              "missed_labels": label_count, "spatial_label_blocks": len(sites),
              "goals": len(nominal), "summary": summaries, "routes": route_rows,
              "paired_candidate_differences": paired,
              "data_sha256": {str(p.relative_to(data)): sha256(p) for p in sources},
              "script_sha256": sha256(__file__),
              "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
              "warnings": ["Scenario sensitivity, not calibrated sand prevalence or astronaut validation.",
                           "No per-pixel sampling inference; worlds are resampled after aggregating all goals.",
                           "Reported energy/margins evaluate candidate loops counterfactually, including declined plans; do not treat them as executed tours.",
                           "No time/O2 feasibility claim; no station service; nominal raster and routing costs are unchanged.",
                           "Hard-class omitted labels are scenario anchors, not a reproduction of the probability-threshold calibration in #93.",
                           "Point labels are stratified and ambiguous; disks/presence/jitter/penalties are assumptions, not ground truth.",
                           "Zero-event bootstrap intervals may be degenerate; they do not prove zero physical risk.",
                           "The conservative map is a precaution near detections, not a cure for confidently missed classes."]}
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    table = ["# C2 candidate loops (including declined plans)", "",
             "Spatial scenario sensitivity only; not a corrected nominal sand map.", "",
             "| Radius (m) | Beta | Policy | Accepted goals | Mean actual Wh | Mean margin Wh | Candidate reserve violation share |",
             "|---|---|---|---|---|---|---|"]
    for row in summaries:
        table.append(f"| {row['radius_m']} | {row['beta']} | {row['policy']} | {row['accepted_goals']}/{row['candidate_goals']} "
                     f"| {row['actual_wh']['mean']:.5f} | {row['margin_wh']['mean']:.5f} | {row['reserve_violated']['mean']:.5f} |")
    table += ["", "Source: src/fisica/missed_sand.py → summary.json and worlds.jsonl."]
    (args.out / "table.md").write_text("\n".join(table), encoding="utf-8")
    with (args.out / "worlds.jsonl").open("w", encoding="utf-8") as stream:
        for row in rows:
            stream.write(json.dumps(row) + "\n")
    if args.figure:
        draw(report, args.figure)
    print(args.out / "summary.json")


def draw(report, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, axes = plt.subplots(1, 2, figsize=(10, 4))
    colors = {"nominal": "#be5636", "conservative": "#235789"}
    for ax, metric, label in zip(axes, ("actual_wh", "margin_wh"),
                                 ("Mean actual loop energy (Wh)", "Mean usable margin (Wh)")):
        for beta in report["settings"]["betas"]:
            for policy in colors:
                rows = [r for r in report["summary"] if r["beta"] == beta and r["policy"] == policy]
                ax.plot([r["radius_m"] for r in rows], [r[metric]["mean"] for r in rows],
                        marker="o", linestyle="-" if beta == min(report["settings"]["betas"]) else "--",
                        color=colors[policy], label=f"{policy}, beta={beta}")
        ax.set_xlabel("Assumed hidden-patch radius (m)")
        ax.set_ylabel(label)
        ax.spines[["top", "right"]].set_visible(False)
    axes[0].legend(fontsize=8)
    fig.suptitle("C2: candidate loops incl. declined plans; spatial SW-S scenarios only")
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)


if __name__ == "__main__":
    main()
