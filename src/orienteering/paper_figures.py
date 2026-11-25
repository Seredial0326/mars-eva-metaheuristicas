"""Numbers and figures for the E5 paper note (paper/notes/E5_orienteering.md).

Run from the repo root:
    python src/orienteering/paper_figures.py [--habitat X Y]

Writes data/e5/summary.json and paper/figures/e5_fig1_tour_map.png,
e5_fig2_prize_vs_budget.png, e5_fig3_dp_runtime.png. The habitat defaults to the
box centre, the same illustrative choice as the E4 note (the habitat is a user input).
"""
import argparse
import itertools
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

from orienteering.data_io import STATIONS_PATH, read_stations  # noqa: E402
from orienteering.network import (load_graph, place_habitat, reachable_stations,  # noqa: E402
                                  route_path, station_matrices)
from orienteering.problem import Problem, evaluate_route  # noqa: E402
from orienteering.safety import (return_costs, solve_with_walkback, stop_energy,  # noqa: E402
                                 tour_walkback)
from orienteering.solvers import brute, dp  # noqa: E402
from orienteering.solvers.dp import closable_timed, prizes_by_mask  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BASE, OUT, FIG = REPO / "data" / "base", REPO / "data" / "e5", REPO / "paper" / "figures"
BOX_CENTRE = (8143537.99, -284463.58)
BUDGET_WH, MARGIN = 1000.0, 0.10
TYPE_COLOURS = {"ridge": "#c0392b", "hollow": "#2471a3", "contact": "#7d3c98",
                "curiosity": "#d68910", "habitat": "black"}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--habitat", type=float, nargs=2, metavar=("X", "Y"), default=BOX_CENTRE)
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    s = {"budget_wh": BUDGET_WH, "margin": MARGIN, "service_power_w": SERVICE_POWER_W}

    # Graph, stations, habitat
    t0 = time.time()
    graph, main_cc = load_graph(BASE)
    s["graph_load_s"] = round(time.time() - t0, 2)
    stations = read_stations(graph, STATIONS_PATH)
    s["stations_in_file"] = len(stations)
    hr, hc, moved = place_habitat(graph, args.habitat)
    hx, hy = (float(v) for v in graph.cell_to_xy(hr, hc))
    s["habitat_xy"], s["habitat_moved_m"] = [hx, hy], round(moved, 2)
    stations = stations.prepend("habitat", "habitat", hx, hy, hr, hc)
    ok = reachable_stations(main_cc, stations)
    s["stations_outside_main_component"] = stations.id[~ok].tolist()
    stations = stations.subset(ok)
    s["n_nodes"] = len(stations)
    s["max_possible_prize"] = float(stations.prize.sum())

    t0 = time.time()
    dis, tim = station_matrices(graph, stations)
    s["matrices_s"] = round(time.time() - t0, 2)
    off = ~np.eye(len(stations), dtype=bool)
    asym = (dis / dis.T)[off]
    s["matrix_energy_wh_min_median_max"] = [round(float(v) / J_PER_WH, 2) for v in
                                            (dis[off].min(), np.median(dis[off]), dis[off].max())]
    s["matrix_asymmetry_p5_p50_p95"] = [round(float(v), 3) for v in np.percentile(asym, [5, 50, 95])]

    habitat = int(graph.node(hr, hc))
    t0 = time.time()
    rv_j = return_costs(graph, habitat)
    s["rv_s"] = round(time.time() - t0, 2)
    usable_j = BUDGET_WH * (1 - MARGIN) * J_PER_WH
    service_j = stations.service_s * SERVICE_POWER_W

    def problem(budget_j=usable_j, power=SERVICE_POWER_W, max_duration_s=None):
        return Problem(energy=dis, prize=stations.prize, budget=budget_j, time=tim,
                       service_s=stations.service_s, service_j=stations.service_s * power,
                       max_duration_s=max_duration_s)

    def plan(p, g=graph, dis_m=None, rv=None):
        dis_m = dis if dis_m is None else dis_m
        rv = rv_j if rv is None else rv
        checked = {}

        def check(route):
            path, stop_index = route_path(g, stations, route, dis_m)
            checked[tuple(route)] = (path, stop_index)
            return tour_walkback(g, path, stop_index, stop_energy(p, route), rv, p.budget)

        solution, wb, retries = solve_with_walkback(p, dp.solve, check)
        path, stop_index = checked[tuple(solution.route)]
        return solution, wb, retries, {"path": path, "stop_index": stop_index}

    def describe(solution, wb, retries, checked, p):
        timeline = evaluate_route(p, solution.route)
        served_j = sum(p.service_j[k] for k in set(solution.route))
        served_s = sum(p.service_s[k] for k in set(solution.route))
        return {"prize": float(solution.prize),
                "prize_fraction": round(float(solution.prize) / s["max_possible_prize"], 3),
                "order": [str(stations.id[k]) for k in solution.route],
                "stations_visited": len(set(solution.route)) - 1,
                "energy_wh": round(solution.energy / J_PER_WH, 1),
                "walk_energy_wh": round((solution.energy - served_j) / J_PER_WH, 1),
                "service_energy_wh": round(served_j / J_PER_WH, 1),
                "duration_min": round(timeline["duration"] / 60.0, 1),
                "walk_min": round((timeline["duration"] - served_s) / 60.0, 1),
                "service_min": round(served_s / 60.0, 1),
                "length_m": round(float(wb["length_m"][-1]), 1),
                "cells": int(len(checked["path"])),
                "walkback_ok": bool(wb["feasible"]),
                "walkback_min_slack_wh": round(wb["min_slack_j"] / J_PER_WH, 1),
                "walkback_retries": retries,
                "dp_s": round(solution.runtime_s, 3)}

    # Nominal run and 120 min limit
    runs = {}
    for name, p in (("nominal", problem()), ("max_120_min", problem(max_duration_s=7200.0))):
        sol, wb, retries, checked = plan(p)
        runs[name] = (sol, checked)
        s[name] = describe(sol, wb, retries, checked, p)

    # Same two runs on the human cost (E3 x E1 sand price), the cost /plan uses
    human, _ = load_graph(BASE, human=True)
    h_dis, h_tim = station_matrices(human, stations)
    h_rv = return_costs(human, int(human.node(hr, hc)))
    h_off = (h_dis / dis)[off]
    s["human_leg_energy_ratio_min_max"] = [round(float(h_off.min()), 4), round(float(h_off.max()), 4)]
    for name, max_d in (("nominal", None), ("max_120_min", 7200.0)):
        p = Problem(energy=h_dis, prize=stations.prize, budget=usable_j, time=h_tim,
                    service_s=stations.service_s, service_j=service_j, max_duration_s=max_d)
        sol, wb, retries, checked = plan(p, human, h_dis, h_rv)
        s[f"human_{name}"] = describe(sol, wb, retries, checked, p)
        s[f"human_{name}"]["same_stations_as_E3"] = (set(s[f"human_{name}"]["order"])
                                                     == set(s[name]["order"]))

    # Rubric sensitivity (docs/research/station_value_rubric.md): S0-S6 and S7 Monte Carlo
    s["sensitivity"] = sensitivity(stations, dis, tim, usable_j, s["nominal"]["duration_min"])

    # Prize against usable budget, with and without service energy
    sweep = list(range(50, 951, 50))
    s["budget_sweep_usable_wh"] = sweep
    for label, power in (("with_service", SERVICE_POWER_W), ("without_service", 0.0)):
        s[f"budget_sweep_prize_{label}"] = [float(dp.solve(problem(wh * J_PER_WH, power)).prize)
                                            for wh in sweep]

    # DP against brute force on random instances (same generator as the tests)
    s["dp_vs_brute"] = dp_vs_brute(500)

    # DP runtime against N (worst case: everything fits, so every state is reachable)
    s["dp_runtime_fast_s"] = runtime_vs_n([8, 10, 12, 14, 16, 18, 20], timed=False)
    s["dp_runtime_timed_s"] = runtime_vs_n([8, 10, 12, 14, 16, 18], timed=True)

    (OUT / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    print(json.dumps({k: v for k, v in s.items() if k in ("nominal", "max_120_min", "dp_vs_brute")}, indent=2))

    fig_tour_map(graph, stations, runs, s)
    fig_prize_vs_budget(s)
    fig_runtime(s)
    fig_sensitivity(s)


RUBRICS = {  # ridge / hollow / contact / curiosity, docs/research/station_value_rubric.md
    "S0 current": (5, 4, 3, 3), "S1 recommended": (5, 4, 4, 3), "S2 equal": (1, 1, 1, 1),
    "S3 NASA-style": (3, 2, 2, 1), "S4 contact first": (4, 4, 5, 3),
    "S5 hollow = ridge": (5, 5, 4, 3), "S6 wide contrast": (9, 4, 4, 1),
}
TYPES = ("ridge", "hollow", "contact", "curiosity")
FRACTIONS = [0.5, 0.6, 0.7, 0.8, 0.9, 1.0, 1.1, 1.2]
N_RANDOM = 500


"""
Rubric sensitivity as specified in docs/research/station_value_rubric.md:
scenarios S0-S6 plus S7 (N_RANDOM random rubrics in [1, 5] that keep S1's order:
ridge >= hollow, contact >= curiosity), each solved at time budgets of 0.5-1.2 x the
nominal duration (the time S1 needs to visit every station, energy budget unchanged).
Also S1 with service times x 1.5 (SEXTANT found real traverses slower than planned).
Metrics against S1 at the same budget: Jaccard of the visited sets, Kendall tau of the
order of the stations both visit, and the fraction of the rubric's maximum score.
One DP per budget (solve_many); only the choice of the best set depends on the rubric.
"""
def sensitivity(stations, dis, tim, usable_j, nominal_min):
    from scipy.stats import kendalltau

    rng = np.random.default_rng(2026)
    types = [str(t) for t in stations.type]
    rubrics = dict(RUBRICS)
    for k in range(N_RANDOM):
        v = np.sort(rng.uniform(1, 5, 4))[::-1]
        mid = v[1:3] if rng.random() < 0.5 else v[2:0:-1]
        rubrics[f"S7_{k}"] = (v[0], mid[0], mid[1], v[3])

    def prizes(rubric):
        score = dict(zip(TYPES, rubric))
        return np.array([score.get(t, 0.0) for t in types], dtype=float)

    names = list(rubrics)
    vectors = [prizes(rubrics[nm]) for nm in names]
    out = {"nominal_duration_min": nominal_min, "fractions": FRACTIONS,
           "rubrics": {nm: list(rubrics[nm]) for nm in RUBRICS}, "n_random": N_RANDOM}

    def stops(route):
        return [k for k in route if k != 0]

    def compare(ref, got):
        a, b = set(stops(ref.route)), set(stops(got.route))
        jac = len(a & b) / len(a | b) if a | b else 1.0
        common = [k for k in stops(ref.route) if k in b]
        tau = None
        if len(common) >= 2:
            pos = {k: m for m, k in enumerate(stops(got.route))}
            tau = float(kendalltau(range(len(common)), [pos[k] for k in common]).statistic)
        return jac, tau

    per_fraction = []
    for f in FRACTIONS:
        p = Problem(energy=dis, prize=vectors[1], budget=usable_j, time=tim,
                    service_s=stations.service_s, service_j=stations.service_s * SERVICE_POWER_W,
                    max_duration_s=f * nominal_min * 60.0)
        sols = dict(zip(names, dp.solve_many(p, vectors)))
        ref = sols["S1 recommended"]
        closable, _ = closable_timed(p)
        s1_by_mask = prizes_by_mask(list(vectors[1]), len(vectors[1]))
        s1_best = max(s1_by_mask[m] for m in closable)
        row = {"fraction": f, "s1_order": [str(stations.id[k]) for k in ref.route],
               "s1_tied_sets": sum(1 for m in closable if s1_by_mask[m] == s1_best)}
        for nm in RUBRICS:
            jac, tau = compare(ref, sols[nm])
            row[nm] = {"jaccard": round(jac, 3), "kendall_tau": None if tau is None else round(tau, 3),
                       "score_fraction": round(sols[nm].prize / vectors[names.index(nm)].sum(), 3)}
        jacs = [compare(ref, sols[nm])[0] for nm in names if nm.startswith("S7_")]
        row["S7"] = {"same_set_share": round(float(np.mean(np.isclose(jacs, 1.0))), 3),
                     "jaccard_p5_median": [round(float(np.percentile(jacs, 5)), 3),
                                           round(float(np.median(jacs)), 3)]}

        inflated = Problem(energy=dis, prize=vectors[1], budget=usable_j, time=tim,
                           service_s=stations.service_s * 1.5,
                           service_j=stations.service_s * 1.5 * SERVICE_POWER_W,
                           max_duration_s=f * nominal_min * 60.0)
        slow = dp.solve(inflated)
        jac, tau = compare(ref, slow)
        row["S1 service x1.5"] = {"jaccard": round(jac, 3),
                                  "score_fraction": round(slow.prize / vectors[1].sum(), 3)}
        per_fraction.append(row)
    out["per_fraction"] = per_fraction

    fixed = [nm for nm in RUBRICS if nm != "S1 recommended"]
    threshold = None
    for row in reversed(per_fraction):
        if all(row[nm]["jaccard"] == 1.0 for nm in fixed) and row["S7"]["same_set_share"] >= 0.95:
            threshold = row["fraction"]
        else:
            break
    out["stable_from_fraction"] = threshold
    return out


def random_problem(rng, n, kind):
    pts = rng.random((n, 2)) * 10
    energy = np.linalg.norm(pts[:, None] - pts[None], axis=2) * rng.uniform(0.8, 1.5, (n, n))
    np.fill_diagonal(energy, 0.0)
    start = int(rng.integers(n))
    end = start if rng.random() < 0.5 else int(rng.integers(n))
    p = Problem(energy=energy, prize=rng.integers(1, 6, n).astype(float),
                budget=rng.uniform(0, 30), start=start, end=end)
    if kind != "plain":
        p.time = energy * rng.uniform(5, 10, (n, n))
        p.service_s = rng.choice([0.0, 30.0, 60.0], n)
        p.service_j = p.service_s * rng.uniform(0.002, 0.01)
    if kind in ("windows", "wait"):
        opens = rng.uniform(0, 150, n) * (rng.random(n) < 0.6)
        widths = np.where(rng.random(n) < 0.3, np.inf, rng.uniform(10, 120, n))
        p.windows = np.column_stack([opens, opens + widths])
    if kind == "wait":
        p.wait_power_w = rng.uniform(0.005, 0.05)
    if kind == "duration":
        p.max_duration_s = rng.uniform(50, 400)
    return p


def dp_vs_brute(cases):
    kinds = ("plain", "service", "windows", "duration", "wait")
    result = {k: {"cases": 0, "same_prize": 0} for k in kinds}
    for seed in range(cases):
        rng = np.random.default_rng(seed)
        kind = kinds[seed % len(kinds)]
        p = random_problem(rng, int(rng.integers(2, 8)), kind)
        result[kind]["cases"] += 1
        result[kind]["same_prize"] += abs(dp.solve(p).prize - brute.solve(p).prize) < 1e-9
    return result


def runtime_vs_n(sizes, timed):
    out = {}
    for n in sizes:
        rng = np.random.default_rng(n)
        pts = rng.random((n, 2)) * 100
        energy = np.linalg.norm(pts[:, None] - pts[None], axis=2)
        p = Problem(energy=energy, prize=np.ones(n), budget=1e12)
        if timed:
            p.time = energy.copy()
            opens = rng.uniform(0, 300, n) * (rng.random(n) < 0.5)
            p.windows = np.column_stack([opens, np.full(n, np.inf)])
        t0 = time.perf_counter()
        dp.solve(p)
        out[str(n)] = round(time.perf_counter() - t0, 5)
    return out


def fig_tour_map(graph, stations, runs, s):
    xs = np.r_[stations.x, s["habitat_xy"][0]]
    ys = np.r_[stations.y, s["habitat_xy"][1]]
    pad = 120.0
    bounds = (xs.min() - pad, ys.min() - pad, xs.max() + pad, ys.max() + pad)
    with rasterio.open(BASE / "hillshade.tif") as src:
        shade = src.read(1, window=from_bounds(*bounds, transform=src.transform))
    extent = (bounds[0], bounds[2], bounds[1], bounds[3])

    fig, axes = plt.subplots(1, 2, figsize=(12, 6.2), constrained_layout=True)
    titles = {"nominal": f"Nominal: {s['nominal']['prize']:g} of {s['max_possible_prize']:g} points",
              "max_120_min": f"Max. 120 min: {s['max_120_min']['prize']:g} points"}
    for ax, name in zip(axes, ("nominal", "max_120_min")):
        sol, checked = runs[name]
        ax.imshow(shade, cmap="gray", extent=extent, origin="upper")
        rows, cols = graph.cell(checked["path"])
        px, py = graph.cell_to_xy(rows, cols)
        ax.plot(px, py, color="#f1c40f", lw=1.6, label="route")
        visited = set(sol.route)
        for k in range(len(stations)):
            colour = TYPE_COLOURS.get(str(stations.type[k]), "grey")
            face = colour if k in visited else "white"
            ax.scatter(stations.x[k], stations.y[k], s=70 if k else 140, marker="o" if k else "*",
                       facecolor=face, edgecolor=colour, linewidth=1.5, zorder=3)
            ax.annotate(str(stations.id[k]) if k else "habitat", (stations.x[k], stations.y[k]),
                        xytext=(4, 4), textcoords="offset points", fontsize=8, color="white")
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
    handles.append(plt.Line2D([], [], marker="o", ls="", markerfacecolor="white",
                              markeredgecolor="grey", label="skipped"))
    axes[1].legend(handles=handles, loc="lower right", fontsize=8)
    fig.savefig(FIG / "e5_fig1_tour_map.png", dpi=110)
    plt.close(fig)


def fig_prize_vs_budget(s):
    fig, ax = plt.subplots(figsize=(6.5, 4), constrained_layout=True)
    ax.step(s["budget_sweep_usable_wh"], s["budget_sweep_prize_without_service"], where="post",
            label="walking only", color="#7f8c8d")
    ax.step(s["budget_sweep_usable_wh"], s["budget_sweep_prize_with_service"], where="post",
            label=f"walking + service ({s['service_power_w']:g} W, 10 min/station)", color="#c0392b")
    ax.axhline(s["max_possible_prize"], ls=":", color="black", lw=0.8)
    ax.set_xlabel("usable energy (Wh)")
    ax.set_ylabel("prize (rubric points)")
    ax.legend(fontsize=8, loc="lower right")
    fig.savefig(FIG / "e5_fig2_prize_vs_budget.png", dpi=120)
    plt.close(fig)


def fig_runtime(s):
    fig, ax = plt.subplots(figsize=(6.5, 4), constrained_layout=True)
    for key, label in (("dp_runtime_fast_s", "energy only"),
                       ("dp_runtime_timed_s", "with time windows (Pareto labels)")):
        n = [int(k) for k in s[key]]
        ax.semilogy(n, list(s[key].values()), marker="o", label=label)
    ax.set_xlabel("stations including the habitat (N)")
    ax.set_ylabel("DP time (s), everything within budget")
    ax.grid(True, which="both", alpha=0.3)
    ax.legend(fontsize=8)
    fig.savefig(FIG / "e5_fig3_dp_runtime.png", dpi=120)
    plt.close(fig)


def fig_sensitivity(s):
    sens = s["sensitivity"]
    f = sens["fractions"]
    rows = sens["per_fraction"]
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 4), constrained_layout=True)
    for nm in RUBRICS:
        if nm == "S1 recommended":
            continue
        ax1.plot(f, [r[nm]["jaccard"] for r in rows], marker="o", ms=3, label=nm)
    ax1.plot(f, [r["S7"]["same_set_share"] for r in rows], color="black", lw=2,
             label=f"S7: share of {sens['n_random']} random rubrics\nwith S1's station set")
    ax1.plot(f, [r["S1 service x1.5"]["jaccard"] for r in rows], color="grey", ls="--",
             label="S1, service time x 1.5")
    ax1.set_xlabel(f"time budget / nominal ({sens['nominal_duration_min']:.0f} min)")
    ax1.set_ylabel("Jaccard of visited stations vs S1")
    ax1.set_ylim(-0.02, 1.05)
    ax1.legend(fontsize=7, loc="lower right")
    for nm in RUBRICS:
        ax2.plot(f, [r[nm]["score_fraction"] for r in rows], marker="o", ms=3, label=nm)
    ax2.set_xlabel("time budget / nominal")
    ax2.set_ylabel("fraction of the rubric's maximum score")
    ax2.legend(fontsize=7, loc="lower right")
    fig.savefig(FIG / "e5_fig4_rubric_sensitivity.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
