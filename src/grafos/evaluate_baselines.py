"""Evaluate the MVP baselines against the exact E4 planner (issue #8).

Run from the repo root:
    # one habitat (user input), budgets relative to its farthest round trip
    python src/grafos/evaluate_baselines.py --habitat X Y
    # paper table: box centre + N random habitats (fixed seed)
    python src/grafos/evaluate_baselines.py --n-habitats 20

Budgets: since the habitat is a user input, budgets are fractions of the most
expensive exact round trip from THAT habitat (default 0.25, 0.5, 0.75), so the
same levels mean the same thing for any habitat. --budget-wh uses absolute values.

Goals: the 13 manual stations (data/stations/stations_manual.gpkg, release
stations-v1; skipped if missing) plus --n-goals random cells of the main
connected component (fixed seed).

Human cost (issue #65): --human-cost builds the graph with api.planner.graph(base,
30, human=True), i.e. E3 energy x E1's sand factor (release e1-sand-v1, 1.0-1.115;
time unchanged). The terrain truth and the MVP then use the human cost, while the
baselines keep their flat-E3 calibration (389.6 J/m, 293 W): they plan as someone
who knows nothing about sand. Budget levels are fractions of the farthest round
trip on the graph in use, so they keep their meaning.

Extra goals: --extra-stations adds GeoPackages with a "stations" layer, e.g. the
15 sand-rock contacts of E8 (data/stations/stations_e8.gpkg, release stations-e8-v0).

Writes to --out-dir (default data/baselines), with --suffix on every file name
(default: "_human" with --human-cost, plus "_e8" if E8 stations are added):
    baselines_goals.csv       one row per habitat x budget x goal x method
    baselines_summary.json    confusion counts per method and budget level
    b1_astar_slope.geojson, b2_fixed_radius.geojson, b3_linear_o2.geojson, mvp_e4.geojson
                              round trip to a reference station from the first habitat,
                              with the real profile (used_wh, rv_wh, slack_wh) per vertex
"""

import argparse
import csv
import json
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.baselines import METHODS, BaselineEvaluator, summarise  # noqa: E402
from grafos.graph import Graph  # noqa: E402
from grafos.labels import Budget, round_trip  # noqa: E402
from grafos.walkback import J_PER_WH  # noqa: E402

REPO = Path(__file__).resolve().parents[2]


def build_graph(base_dir, human):
    """E3 graph (as in #56), or E3 x E1 sand through the API's planner.graph. Stops
    if the human cost was asked for but E1's weights are missing (planner.graph
    would silently fall back to E3)."""
    if not human:
        g = Graph.from_base_dir(base_dir)
        g.cost_model = "E3"
        return g
    sys.path.insert(0, str(REPO))
    from api import planner
    g = planner.graph(str(base_dir), 30.0, True)
    if g.cost_model == "E3":
        sys.exit("--human-cost: E1 weights not found (data/e1/e1_weights.json, release "
                 "e1-sand-v1; also data/e8/ from release e8-v0)")
    return g


def load_stations(graph, path):
    if not Path(path).exists():
        print(f"stations not found ({path}): using random goals only")
        return []
    import geopandas as gpd
    gdf = gpd.read_file(path, layer="stations")
    out = []
    for _, s in gdf.iterrows():
        try:
            r, c, moved = graph.place(s.geometry.x, s.geometry.y, label=s["id"])
        except ValueError:
            continue
        out.append({"id": s["id"], "type": s["type"], "node": int(graph.node(r, c)),
                    "moved_m": moved})
    return out


def profile_geojson(graph, path, turn, rv_j, budget_j, crs_wkt, **props):
    used = graph.path_cost(path, "energy_j")
    t = graph.path_cost(path, "time_s")
    rows, cols = graph.cell(path)
    x, y = graph.cell_to_xy(rows, cols)
    rv = rv_j[path]
    wh = lambda a: [round(float(v) / J_PER_WH, 4) for v in a]   # noqa: E731
    feat = {"type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[float(a), float(b)] for a, b in zip(x, y)]},
            "properties": {"kind": "route", "turn_index": int(turn),
                           "energy_wh": round(float(used[-1]) / J_PER_WH, 3),
                           "time_s": round(float(t[-1]), 1),
                           "length_m": round(float(graph.path_cost(path, "length_m")[-1]), 1),
                           "budget_wh": round(budget_j / J_PER_WH, 3),
                           "really_feasible": bool(used[-1] <= budget_j),
                           # walkback with the exact R(v) along THIS route
                           "used_wh": wh(used), "rv_wh": wh(rv),
                           "slack_wh": wh(budget_j - used - rv),
                           "t_s": [round(float(v), 1) for v in t], **props}}
    return {"type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": crs_wkt}}, "features": [feat]}


def main():
    ap = argparse.ArgumentParser(description="E4 baselines vs the exact planner.")
    ap.add_argument("--habitat", type=float, nargs=2, metavar=("X", "Y"),
                    help="habitat (metres in the DEM CRS); default: box centre")
    ap.add_argument("--n-habitats", type=int, default=0,
                    help="extra random habitats in the main component (paper table)")
    ap.add_argument("--budget-fractions", type=float, nargs="+", default=[0.25, 0.5, 0.75])
    ap.add_argument("--budget-wh", type=float, nargs="+",
                    help="absolute usable budgets instead of fractions")
    ap.add_argument("--n-goals", type=int, default=2000)
    ap.add_argument("--seed", type=int, default=8)
    ap.add_argument("--reference-station", default="R0")
    ap.add_argument("--stations", default=str(REPO / "data" / "stations" / "stations_manual.gpkg"))
    ap.add_argument("--extra-stations", nargs="*", default=[],
                    help="more station GeoPackages (layer 'stations'), e.g. "
                         "data/stations/stations_e8.gpkg")
    ap.add_argument("--human-cost", action="store_true",
                    help="terrain truth and MVP on E3 x E1 sand (api.planner.graph)")
    ap.add_argument("--suffix", default=None, help="appended to every output file name")
    ap.add_argument("--base-dir", default=str(REPO / "data" / "base"))
    ap.add_argument("--out-dir", default=str(REPO / "data" / "baselines"))
    args = ap.parse_args()

    if args.suffix is None:
        args.suffix = ("_human" if args.human_cost else "") +             ("_e8" if any("e8" in Path(p).name for p in args.extra_stations) else "")
    sfx = args.suffix
    out = Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    graph = build_graph(args.base_dir, args.human_cost)
    main_cc = graph.main_component()
    print(f"graph ready ({time.time() - t0:.1f}s)")
    rng = np.random.default_rng(args.seed)
    cc_nodes = np.flatnonzero(main_cc.ravel())

    if args.habitat:
        hr, hc, moved = graph.place(*args.habitat, label="habitat")
        if moved:
            print(f"warning: habitat moved {moved:.1f} m to a valid cell")
    else:
        hr, hc = graph.snap(graph.height // 2, graph.width // 2, mask=main_cc)
    habitats = [int(graph.node(hr, hc))]
    habitats += [int(v) for v in rng.choice(cc_nodes, size=args.n_habitats, replace=False)]

    stations = load_stations(graph, args.stations)
    for path in args.extra_stations:
        stations += load_stations(graph, path)
    print(f"cost model: {graph.cost_model}; {len(stations)} stations")
    goals = [(s["id"], s["type"], s["node"]) for s in stations]
    goals += [(f"rnd{i}", "random", int(v))
              for i, v in enumerate(rng.choice(cc_nodes, size=args.n_goals, replace=False))]

    rows, levels = [], {}
    for hi, hab in enumerate(habitats):
        t1 = time.time()
        ev = BaselineEvaluator(graph, hab)
        far = ev.farthest_loop_j()
        if args.budget_wh:
            budgets = [(f"{b:g}Wh", b * J_PER_WH) for b in args.budget_wh]
        else:
            budgets = [(f"{f:.0%}", f * far) for f in args.budget_fractions]
        for gid, gtype, node in goals:
            if node == hab or not np.isfinite(ev.loop_e[node]):
                continue
            for label, b in budgets:
                for r in ev.evaluate(node, b):
                    r.update(habitat=hab, habitat_index=hi, goal=gid, goal_type=gtype,
                             level=label, budget_j=b, farthest_loop_j=far)
                    rows.append(r)
                    levels.setdefault(label, []).append(r)
        print(f"habitat {hi + 1}/{len(habitats)}: farthest loop {far / J_PER_WH:.0f} Wh, "
              f"{time.time() - t1:.1f}s")

    summary = {"habitats": len(habitats), "goals": len(goals), "seed": args.seed,
               "stations": len(stations), "cost_model": graph.cost_model,
               "baseline_calibration": "flat E3: 389.6 J/m, 293 W (blind to sand)",
               "station_files": [Path(args.stations).name] + [Path(p).name for p in args.extra_stations],
               "levels": {k: summarise(v) for k, v in levels.items()},
               "levels_stations_only": {k: summarise([r for r in v if r["goal_type"] != "random"])
                                        for k, v in levels.items()}}
    (out / f"baselines_summary{sfx}.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    keys = ["habitat_index", "habitat", "level", "budget_j", "farthest_loop_j", "goal",
            "goal_type", "method", "safe", "really_feasible", "any_route_feasible",
            "estimate_j", "real_j", "optimal_j", "length_m", "time_s"]
    with open(out / f"baselines_goals{sfx}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)

    # GeoJSON: reference station from the first habitat, middle budget level
    ref = next((s for s in stations if s["id"] == args.reference_station), None)
    if ref is not None:
        ev = BaselineEvaluator(graph, habitats[0])
        label, b = (budgets[len(budgets) // 2] if not args.budget_wh else budgets[0])
        if args.budget_wh is None:
            b = args.budget_fractions[len(args.budget_fractions) // 2] * ev.farthest_loop_j()
        verdicts = {r["method"]: r for r in ev.evaluate(ref["node"], b)}
        for m, (path, turn) in ev.routes(ref["node"]).items():
            fc = profile_geojson(graph, path, turn, ev.r_e, b, graph.crs_wkt, method=m,
                                 goal=ref["id"], said_safe=bool(verdicts[m]["safe"]),
                                 estimate_wh=round(verdicts[m]["estimate_j"] / J_PER_WH, 3))
            (out / f"{m.split('_', 1)[0].lower()}_{m.split('_', 1)[1]}{sfx}.geojson").write_text(
                json.dumps(fc), encoding="utf-8")
        mvp = round_trip(graph, habitats[0], ref["node"], Budget())
        fc = profile_geojson(graph, mvp["path"], mvp["turn_index"], ev.r_e, b, graph.crs_wkt,
                             method="MVP_e4", goal=ref["id"], said_safe=bool(verdicts["MVP_e4"]["safe"]),
                             estimate_wh=round(verdicts["MVP_e4"]["estimate_j"] / J_PER_WH, 3))
        (out / f"mvp_e4{sfx}.geojson").write_text(json.dumps(fc), encoding="utf-8")

    for k, s in summary["levels"].items():
        print(f"\n== budget {k} of the farthest round trip ==")
        for m in METHODS:
            v = s[m]
            print(f"{m:16s} said safe {v['said_safe']:5d}  FALSE SAFE {v['false_safe']:4d} "
                  f"({100 * v['false_safe_rate_of_said_safe']:.1f}% of 'safe')  "
                  f"impossible-but-safe {v['said_safe_but_impossible']:4d}  "
                  f"missed {100 * v['missed_fraction_of_feasible']:.1f}%  "
                  f"overcost median {100 * v['energy_overcost_median']:.1f}%  "
                  f"real/est median {v['real_over_estimate_median']:.2f} "
                  f"(factor needed p99 {v['safety_factor_needed_p99']:.2f})")


if __name__ == "__main__":
    main()
