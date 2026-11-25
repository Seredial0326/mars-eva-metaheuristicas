"""Numbers and figures for the E4 paper note (paper/notes/E4_walkback.md).

Run from the repo root:
    python src/grafos/paper_figures.py [--habitat X Y]

Writes data/e4/summary.json and paper/figures/e4_fig1_rv_map.png,
paper/figures/e4_fig2_safe_area.png. The habitat defaults to the box centre:
an illustrative choice for the paper, since the habitat is a user input.
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

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.graph import Graph  # noqa: E402
from grafos.labels import Budget, round_trip  # noqa: E402
from grafos.walkback import J_PER_WH, Walkback  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
BASE, OUT, FIG = REPO / "data" / "base", REPO / "data" / "e4", REPO / "paper" / "figures"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--habitat", type=float, nargs=2, metavar=("X", "Y"))
    args = ap.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    s = {}

    t0 = time.time()
    g = Graph.from_base_dir(BASE)
    s["graph_build_s"] = round(time.time() - t0, 2)
    labels, sizes = g.components()
    main_cc = (labels == np.argmax(sizes)).reshape(g.shape)
    deg = g.out_degree()
    s["nodes"] = g.n
    s["arcs"] = int(g.csr().nnz)
    s["arcs_fraction_of_8n"] = round(s["arcs"] / (8 * g.n), 4)
    s["nodes_without_out_arcs_fraction"] = round(float(np.mean(deg == 0)), 4)
    s["largest_scc_fraction"] = round(float(sizes.max() / g.n), 4)
    s["largest_scc_fraction_of_walkable"] = round(float(sizes.max() / np.sum(deg > 0)), 4)
    s["second_scc_cells"] = int(np.sort(sizes)[-2])

    if args.habitat:
        r, c = (int(v) for v in g.xy_to_cell(*args.habitat))
    else:
        r, c = g.height // 2, g.width // 2
    hr, hc = g.snap(r, c, mask=main_cc)
    hab = int(g.node(hr, hc))
    s["habitat_xy"] = [float(v) for v in g.cell_to_xy(hr, hc)]

    t0 = time.time()
    wb = Walkback.compute(g, hab)
    s["rv_and_g_s"] = round(time.time() - t0, 2)
    rv_wh = wb.rv_j / J_PER_WH
    fin = np.isfinite(rv_wh)
    s["rv_wh_percentiles_50_99_max"] = [round(float(v), 1)
                                        for v in np.percentile(rv_wh[fin], [50, 99, 100])]
    s["rv_unreachable_fraction"] = round(float(1 - fin.mean()), 4)
    loop_wh = (wb.g_j + wb.rv_j) / J_PER_WH

    budgets = [100, 200, 300, 400, 500, 600, 700, 800, 1000]
    s["safe_fraction_by_usable_wh"] = {b: round(float(np.mean(loop_wh <= b)), 4) for b in budgets}

    # asymmetry: how much more it costs to come back than to go out
    both = np.isfinite(wb.g_j) & np.isfinite(wb.rv_j) & (wb.g_j > 0)
    ratio = wb.rv_j[both] / wb.g_j[both]
    s["return_over_outbound_percentiles_5_50_95"] = [round(float(v), 3)
                                                     for v in np.percentile(ratio, [5, 50, 95])]

    # E4 round trip to the farthest returnable cell, energy only
    goal = int(np.argmax(np.where(np.isfinite(loop_wh), loop_wh, -np.inf)))
    t0 = time.time()
    free = round_trip(g, hab, goal, Budget())
    s["farthest_round_trip"] = {
        "goal_xy": [float(v) for v in g.cell_to_xy(*g.cell(goal))],
        "energy_wh": round(float(free["used_j"][-1] / J_PER_WH), 1),
        "time_min": round(float(free["time_s"][-1] / 60), 1),
        "o2_l": round(float(free["o2_l"][-1]), 1),
        "length_m": round(float(free["length_m"][-1]), 0),
        "method": free["method"], "seconds": round(time.time() - t0, 1)}

    # same goal with a binding time limit: min-energy vs min-time trade-off
    tmin = round_trip(g, hab, goal, Budget(), objective="time")
    limit = 0.5 * (tmin["time_s"][-1] + free["time_s"][-1])
    t0 = time.time()
    tied = round_trip(g, hab, goal, Budget(time_s=limit))
    s["binding_time_limit"] = {
        "min_time_route": {"energy_wh": round(float(tmin["used_j"][-1] / J_PER_WH), 2),
                           "time_min": round(float(tmin["time_s"][-1] / 60), 2)},
        "limit_min": round(limit / 60, 2),
        "energy_wh": round(float(tied["used_j"][-1] / J_PER_WH), 2),
        "time_min": round(float(tied["time_s"][-1] / 60), 2),
        "method": tied["method"], "exact": tied["exact"],
        "gap_wh": round(tied["gap"] / J_PER_WH, 3),
        "labels": tied["labels_expanded"], "seconds": round(time.time() - t0, 1)}

    (OUT / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")
    print(json.dumps(s, indent=2))

    # ---------------------------------------------------------------- figures
    with rasterio.open(BASE / "hillshade.tif") as src:
        hs = src.read(1)
    ext = [0, g.width, g.height, 0]
    fig, ax = plt.subplots(1, 2, figsize=(11, 5.2), constrained_layout=True)
    ax[0].imshow(hs, cmap="gray", extent=ext)
    im = ax[0].imshow(wb.raster(rv_wh), cmap="viridis", alpha=0.75, extent=ext)
    fig.colorbar(im, ax=ax[0], shrink=0.8, label="R(v): energy to return (Wh)")
    pr, pc = g.cell(free["path"])
    ax[0].plot(pc, pr, color="w", lw=1.2, label="E4 round trip")
    ax[0].plot(hc, hr, marker="*", color="red", ms=14, mec="k", label="habitat")
    ax[0].legend(loc="lower left", fontsize=8)
    ax[0].set_title("R(v), one reverse Dijkstra (grey = no return)")
    ax[1].imshow(hs, cmap="gray", extent=ext)
    zone = np.full(g.shape, np.nan)
    for b in (300, 200, 100):
        zone[(loop_wh <= b).reshape(g.shape)] = b
    im2 = ax[1].imshow(zone, cmap="plasma_r", alpha=0.6, extent=ext, vmin=50, vmax=350)
    fig.colorbar(im2, ax=ax[1], shrink=0.8, ticks=[100, 200, 300],
                 label="smallest usable budget that reaches and returns (Wh)")
    ax[1].plot(hc, hr, marker="*", color="red", ms=14, mec="k")
    ax[1].set_title("Safe region g(v) + R(v) <= budget")
    for a in ax:
        a.set_xlabel("column (m, east)")
        a.set_ylabel("row (m, south)")
    fig.savefig(FIG / "e4_fig1_rv_map.png", dpi=110)

    fig, ax = plt.subplots(figsize=(5.5, 3.8), constrained_layout=True)
    xs = np.linspace(0, np.nanmax(loop_wh[np.isfinite(loop_wh)]) * 1.05, 200)
    srt = np.sort(loop_wh[np.isfinite(loop_wh)])
    ax.plot(xs, np.searchsorted(srt, xs) / g.n * 100)
    ax.axhline(100 * s["largest_scc_fraction"], ls="--", color="gray",
               label="largest connected area")
    ax.set_xlabel("usable energy budget (Wh)")
    ax.set_ylabel("cells reachable and returnable (%)")
    ax.legend(fontsize=8)
    ax.grid(alpha=0.3)
    fig.savefig(FIG / "e4_fig2_safe_area.png", dpi=120)

    baselines_figure(g, hab, hs, ext, s)
    (OUT / "summary.json").write_text(json.dumps(s, indent=2), encoding="utf-8")


def baselines_figure(g, hab, hs, ext, s, fraction=0.5):
    """What each baseline DECLARES safe vs the exact safe region (whole grid).
    Red = declared safe although no route fits the budget (sure danger)."""
    from grafos.baselines import FLAT_J_PER_M, RATE_W, BaselineEvaluator
    ev = BaselineEvaluator(g, hab)
    b = fraction * ev.farthest_loop_j()
    exact = ev.loop_e <= b
    hr, hc = g.cell(hab)
    rows, cols = np.divmod(np.arange(g.n), g.width)
    straight = np.hypot(rows - hr, cols - hc) * abs(g.transform[0])
    reach = np.isfinite(ev.loop_e)
    declared = {
        "B1 A*-slope: 2 x path length x flat J/m": (2 * ev.len_out * FLAT_J_PER_M <= b) & reach,
        "B2 fixed radius": (straight <= b / (2 * FLAT_J_PER_M)) & reach,
        "B3 linear O2 (293 W x time)": (RATE_W * (ev.t_out + ev.t_back) <= b) & reach,
    }
    s["baselines_map"] = {"budget_fraction": fraction, "budget_wh": round(b / J_PER_WH, 1),
                          "exact_safe_fraction": round(float(exact.mean()), 4)}
    fig, ax = plt.subplots(1, 3, figsize=(15, 5.2), constrained_layout=True)
    for a, (name, dec) in zip(ax, declared.items()):
        img = np.full(g.n, np.nan)
        img[exact & dec] = 0          # agree: safe
        img[~dec & exact] = 1         # baseline too conservative
        img[dec & ~exact] = 2         # declared safe, impossible
        a.imshow(hs, cmap="gray", extent=ext)
        a.imshow(img.reshape(g.shape), cmap=matplotlib.colors.ListedColormap(
            ["#4caf50", "#2196f3", "#e53935"]), vmin=0, vmax=2, alpha=0.6, extent=ext,
            interpolation="nearest")
        a.plot(hc, hr, marker="*", color="yellow", ms=14, mec="k")
        bad = float((dec & ~exact).sum() / max(dec.sum(), 1))
        s["baselines_map"][name.split(":")[0]] = {
            "declared_safe_fraction": round(float(dec.mean()), 4),
            "impossible_among_declared": round(bad, 4)}
        a.set_title(f"{name}\n{100 * bad:.1f}% of 'safe' cells cannot be done", fontsize=9)
        a.set_xlabel("column (m, east)")
    ax[0].set_ylabel("row (m, south)")
    fig.suptitle(f"Green: safe for both. Red: baseline says safe, exact E4 says impossible. "
                 f"Blue: baseline too cautious. Budget {b / J_PER_WH:.0f} Wh "
                 f"({fraction:.0%} of the farthest round trip).", fontsize=10)
    fig.savefig(FIG / "e4_fig3_baselines_map.png", dpi=100)


if __name__ == "__main__":
    main()
