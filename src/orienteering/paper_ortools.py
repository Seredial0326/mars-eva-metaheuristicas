"""OR-Tools results for the E5 paper note: the 13 manual stations plus E8's 15 sand-rock
contacts (28 stations), beyond the DP's 20 nodes. CP-SAT (exact model) gives the tours;
the OR-Tools routing heuristic is compared against it and against the DP.

Run from the repo root (needs releases stations-v1 and stations-e8-v0 in data/stations):
    python src/orienteering/paper_ortools.py [--habitat X Y] [--time-limit-s 120]

Writes, separately from the DP's data/e5/summary.json (paper_figures.py):
    data/e5/summary_ortools.json
    data/e5/e5_route_ortools_28.gpkg, data/e5/e5_route_ortools_28_120min.gpkg
    paper/figures/e5_fig5_ortools_28.png
"""
import argparse
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from rasterio.windows import from_bounds  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.build_rv import SERVICE_POWER_W  # noqa: E402
from grafos.walkback import J_PER_WH  # noqa: E402

from orienteering.data_io import (DATA_DIR, STATIONS_PATH, read_station_files,  # noqa: E402
                                  read_stations, write_route_gpkg)
from orienteering.network import (load_graph, place_habitat, reachable_stations,  # noqa: E402
                                  route_path, station_matrices)
from orienteering.paper_figures import (BOX_CENTRE, BUDGET_WH, MARGIN,  # noqa: E402
                                        TYPE_COLOURS, random_problem)
from orienteering.problem import Problem, evaluate_route  # noqa: E402
from orienteering.safety import (return_costs, solve_with_walkback, stop_energy,  # noqa: E402
                                 tour_walkback)
from orienteering.solvers import cpsat, dp, routing  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BASE, OUT, FIG = REPO / "data" / "base", REPO / "data" / "e5", REPO / "paper" / "figures"
E8_PATH = DATA_DIR / "stations" / "stations_e8.gpkg"
SCENARIOS = {"nominal": None, "max_120_min": 7200.0}
ROUTING_LIMITS_S = [1.0, 5.0, 15.0, 60.0]
RANDOM_SIZES, RANDOM_CASES, ROUTING_RANDOM_S = (12, 16, 20), 10, 2.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--habitat", type=float, nargs=2, metavar=("X", "Y"), default=BOX_CENTRE)
    ap.add_argument("--time-limit-s", type=float, default=120.0,
                    help="CP-SAT search cap of the final runs (it stops once the optimum is proven)")
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    s = {"budget_wh": BUDGET_WH, "margin": MARGIN, "service_power_w": SERVICE_POWER_W,
         "solver": "OR-Tools CP-SAT", "cpsat_time_limit_s": args.time_limit_s,
         "cpsat_workers": cpsat.WORKERS,
         "routing_heuristic": f"OR-Tools routing, {routing.METAHEURISTIC}" + (" + LNS" if routing.LNS else "")}

    graph, main_cc = load_graph(BASE)
    manual_ids = set(read_stations(graph, STATIONS_PATH).id.tolist())
    e8_in_file = len(read_stations(graph, E8_PATH))
    stations = read_station_files(graph, [STATIONS_PATH, E8_PATH])
    hr, hc, moved = place_habitat(graph, args.habitat)
    hx, hy = (float(v) for v in graph.cell_to_xy(hr, hc))
    s["habitat_xy"], s["habitat_moved_m"] = [hx, hy], round(moved, 2)
    stations = stations.prepend("habitat", "habitat", hx, hy, hr, hc)
    ok = reachable_stations(main_cc, stations)
    s["stations_outside_main_component"] = stations.id[~ok].tolist()
    stations = stations.subset(ok)
    source = np.array(["habitat" if k == 0 else "manual" if i in manual_ids else "E8"
                       for k, i in enumerate(stations.id)])
    s["stations"] = {"manual": int((source == "manual").sum()), "E8": int((source == "E8").sum()),
                     "E8_in_file": e8_in_file, "nodes_with_habitat": len(stations)}
    s["max_possible_prize"] = {src: round(float(stations.prize[source == src].sum()), 2)
                               for src in ("manual", "E8")}
    s["max_possible_prize"]["all"] = round(float(stations.prize.sum()), 2)
    s["service_min"] = {src: float(stations.service_s[source == src].sum() / 60.0)
                        for src in ("manual", "E8")}

    t0 = time.time()
    dis, tim = station_matrices(graph, stations)
    s["matrices_s"] = round(time.time() - t0, 2)
    rv_j = return_costs(graph, int(graph.node(hr, hc)))
    usable_j = BUDGET_WH * (1 - MARGIN) * J_PER_WH

    def problem(keep=None, max_duration_s=None):
        keep = np.arange(len(stations)) if keep is None else keep
        return Problem(energy=dis[np.ix_(keep, keep)], prize=stations.prize[keep], budget=usable_j,
                       time=tim[np.ix_(keep, keep)], service_s=stations.service_s[keep],
                       service_j=stations.service_s[keep] * SERVICE_POWER_W,
                       max_duration_s=max_duration_s)

    # 1. Both OR-Tools solvers against the DP on the 14-node manual instance of the paper note
    manual = np.flatnonzero(source != "E8")
    s["vs_dp_manual_14"] = {}
    for name, max_d in SCENARIOS.items():
        p = problem(manual, max_d)
        exact = dp.solve(p)
        row = {"dp_prize": exact.prize, "dp_energy_wh": round(exact.energy / J_PER_WH, 1),
               "dp_s": round(exact.runtime_s, 2)}
        for label, sol in (("cpsat", cpsat.solve(p, 60.0)), ("routing", routing.solve(p, 10.0))):
            row.update({f"{label}_prize": sol.prize,
                        f"{label}_energy_wh": round(sol.energy / J_PER_WH, 1),
                        f"{label}_same_stations": set(exact.route) == set(sol.route),
                        f"{label}_s": round(sol.runtime_s, 2)})
        s["vs_dp_manual_14"][name] = row

    # 2. Both against the DP on random instances up to the DP's limit
    s["vs_dp_random"] = vs_dp_random()

    # 3. All stations: the routing heuristic at several search times, then CP-SAT with walkback
    s["routing_by_time_limit"] = {name: [] for name in SCENARIOS}
    for name, max_d in SCENARIOS.items():
        for limit in ROUTING_LIMITS_S:
            sol = routing.solve(problem(max_duration_s=max_d), limit)
            s["routing_by_time_limit"][name].append({"time_limit_s": limit, "prize": round(sol.prize, 2),
                                                     "energy_wh": round(sol.energy / J_PER_WH, 1)})

    runs = {}
    for name, max_d in SCENARIOS.items():
        p = problem(max_duration_s=max_d)
        checked = {}

        def check(route):
            path, stop_index = route_path(graph, stations, route, dis)
            checked[tuple(route)] = (path, stop_index)
            return tour_walkback(graph, path, stop_index, stop_energy(p, route), rv_j, usable_j)

        sol, wb, retries = solve_with_walkback(p, lambda q: cpsat.solve(q, args.time_limit_s), check)
        path, stop_index = checked[tuple(sol.route)]
        runs[name] = (sol, path)
        s[name] = describe(sol, wb, retries, p, stations, source, path, s["max_possible_prize"]["all"])
        out = OUT / ("e5_route_ortools_28.gpkg" if max_d is None else "e5_route_ortools_28_120min.gpkg")
        write_route_gpkg(out, graph, stations, sol, path, stop_index, usable_j, SERVICE_POWER_W,
                         evaluate_route(p, sol.route), wb)
        s[name]["gpkg"] = str(out.relative_to(REPO)).replace("\\", "/")

    # 4. The DP's manual-only tours (summary.json), for the gain of adding E8
    dp_summary = OUT / "summary.json"
    if dp_summary.exists():
        d = json.loads(dp_summary.read_text(encoding="utf-8"))
        s["dp_manual_only"] = {name: {k: d[name][k] for k in ("prize", "energy_wh", "duration_min",
                                                              "stations_visited")}
                               for name in SCENARIOS if name in d}

    (OUT / "summary_ortools.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    print(json.dumps({k: s[k] for k in ("stations", "vs_dp_manual_14", "vs_dp_random",
                                        "routing_by_time_limit", "nominal", "max_120_min")}, indent=2))
    fig_map(graph, stations, source, runs, s)


def describe(sol, wb, retries, p, stations, source, path, max_prize):
    timeline = evaluate_route(p, sol.route)
    visited = sorted(set(sol.route) - {0})
    served_j = sum(p.service_j[k] for k in visited)
    served_s = sum(p.service_s[k] for k in visited)
    return {"prize": round(sol.prize, 2), "prize_fraction": round(sol.prize / max_prize, 3),
            "order": [str(stations.id[k]) for k in sol.route],
            "stations_visited": len(visited),
            "visited_manual": int(sum(source[k] == "manual" for k in visited)),
            "visited_E8": int(sum(source[k] == "E8" for k in visited)),
            "prize_manual": round(float(sum(p.prize[k] for k in visited if source[k] == "manual")), 2),
            "prize_E8": round(float(sum(p.prize[k] for k in visited if source[k] == "E8")), 2),
            "energy_wh": round(sol.energy / J_PER_WH, 1),
            "walk_energy_wh": round((sol.energy - served_j) / J_PER_WH, 1),
            "service_energy_wh": round(served_j / J_PER_WH, 1),
            "duration_min": round(timeline["duration"] / 60.0, 1),
            "service_min": round(served_s / 60.0, 1),
            "length_m": round(float(wb["length_m"][-1]), 1), "cells": int(len(path)),
            "walkback_ok": bool(wb["feasible"]),
            "walkback_min_slack_wh": round(wb["min_slack_j"] / J_PER_WH, 1),
            "walkback_retries": retries, "cpsat_optimal": bool(sol.optimal),
            "cpsat_bound": None if sol.bound is None else round(sol.bound, 2),
            "cpsat_s": round(sol.runtime_s, 1)}


def vs_dp_random():
    out = {}
    for n in RANDOM_SIZES:
        for kind in ("service", "windows"):
            same = {"cpsat": 0, "routing": 0}
            gap, proven, cp_s = 0.0, 0, []
            for case in range(RANDOM_CASES):
                p = random_problem(np.random.default_rng(10_000 * n + case), n, kind)
                exact = dp.solve(p)
                cp, heur = cpsat.solve(p, 60.0), routing.solve(p, ROUTING_RANDOM_S)
                same["cpsat"] += abs(exact.prize - cp.prize) < 1e-9
                same["routing"] += abs(exact.prize - heur.prize) < 1e-9
                proven += bool(cp.optimal)
                cp_s.append(cp.runtime_s)
                if exact.prize:
                    gap = max(gap, (exact.prize - heur.prize) / exact.prize)
            out[f"n{n}_{kind}"] = {"cases": RANDOM_CASES, "cpsat_same_prize": same["cpsat"],
                                   "cpsat_proven_optimal": proven, "cpsat_max_s": round(max(cp_s), 2),
                                   "routing_same_prize": same["routing"], "routing_max_gap": round(gap, 3),
                                   "routing_time_limit_s": ROUTING_RANDOM_S}
    return out


def fig_map(graph, stations, source, runs, s):
    pad = 100.0
    bounds = (stations.x.min() - pad, stations.y.min() - pad, stations.x.max() + pad, stations.y.max() + pad)
    with rasterio.open(BASE / "hillshade.tif") as src:
        shade = src.read(1, window=from_bounds(*bounds, transform=src.transform))
    extent = (bounds[0], bounds[2], bounds[1], bounds[3])

    fig, axes = plt.subplots(1, 2, figsize=(12, 6.4), constrained_layout=True)
    total = s["max_possible_prize"]["all"]
    titles = {"nominal": f"Nominal: {s['nominal']['prize']:g} of {total:g} points",
              "max_120_min": f"Max. 120 min: {s['max_120_min']['prize']:g} points"}
    for ax, name in zip(axes, SCENARIOS):
        sol, path = runs[name]
        ax.imshow(shade, cmap="gray", extent=extent, origin="upper")
        px, py = graph.cell_to_xy(*graph.cell(path))
        ax.plot(px, py, color="#f1c40f", lw=1.4)
        visited = set(sol.route)
        for k in range(len(stations)):
            colour = TYPE_COLOURS.get(str(stations.type[k]), "grey")
            marker = "*" if k == 0 else "s" if source[k] == "E8" else "o"
            ax.scatter(stations.x[k], stations.y[k], s=140 if k == 0 else 55, marker=marker,
                       facecolor=colour if k in visited else "white", edgecolor=colour,
                       linewidth=1.4, zorder=3)
            ax.annotate("habitat" if k == 0 else str(stations.id[k]), (stations.x[k], stations.y[k]),
                        xytext=(4, 4), textcoords="offset points", fontsize=6.5, color="white")
        for m, k in enumerate(sol.route[1:-1], start=1):
            ax.annotate(str(m), (stations.x[k], stations.y[k]), xytext=(-10, -12),
                        textcoords="offset points", fontsize=7, color="#f1c40f")
        ax.set_title(titles[name], fontsize=11)
        ax.set_xlabel("x (m, Mars equirectangular)")
        ax.ticklabel_format(useOffset=False, style="plain")
        ax.tick_params(labelsize=7)
    axes[0].set_ylabel("y (m)")
    handles = [plt.Line2D([], [], marker="o", ls="", color=c, label=t)
               for t, c in TYPE_COLOURS.items() if t != "habitat"]
    handles += [plt.Line2D([], [], marker="s", ls="", color=TYPE_COLOURS["contact"], label="E8 contact"),
                plt.Line2D([], [], marker="o", ls="", markerfacecolor="white", markeredgecolor="grey",
                           label="skipped")]
    axes[1].legend(handles=handles, loc="lower right", fontsize=8)
    fig.savefig(FIG / "e5_fig5_ortools_28.png", dpi=110)
    plt.close(fig)


if __name__ == "__main__":
    main()
