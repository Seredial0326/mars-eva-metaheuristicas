"""Numbers and figure for the light-window section of the E5 note (#111).

Run from the repo root (inputs as in the E5 note):
    python src/orienteering/paper_light_windows.py

Writes data/e5/light_windows.json and paper/figures/e5_fig6_light_windows.png.
"""
import json
import sys
import time
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.build_rv import SERVICE_POWER_W  # noqa: E402
from grafos.walkback import J_PER_WH  # noqa: E402

from orienteering import departure as dep  # noqa: E402
from orienteering import light_windows as lw  # noqa: E402
from orienteering.data_io import STATIONS_PATH, read_stations  # noqa: E402
from orienteering.network import load_graph, place_habitat, station_matrices  # noqa: E402
from orienteering.paper_figures import BOX_CENTRE, BUDGET_WH, MARGIN  # noqa: E402
from orienteering.problem import Problem  # noqa: E402
from orienteering.solvers import dp  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT, FIG = REPO / "data" / "e5", REPO / "paper" / "figures"
SOL = 4711
STARTS = np.arange(5.0, 19.0 + 1e-9, 0.25)
SCENARIOS = {"nominal": None, "max_120_min": 7200.0}
WAITS = {"wait_0_w": 0.0, "wait_205_w": SERVICE_POWER_W}   # 205 W: an upper bound until a resting value is agreed
COLOURS = {"nominal": "#2a78d6", "max_120_min": "#eb6834"}   # dataviz slots 1-2
LABELS = {"nominal": "Nominal (no time limit)", "max_120_min": "120 min limit"}


def jaccard(a, b):
    a, b = set(a) - {0}, set(b) - {0}
    return 1.0 if not a and not b else len(a & b) / len(a | b)


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    graph, _ = load_graph()
    st = read_stations(graph, STATIONS_PATH)
    r, c, _ = place_habitat(graph, BOX_CENTRE)
    x, y = (float(v) for v in graph.cell_to_xy(r, c))
    st = st.prepend("habitat", "habitat", x, y, r, c)
    dis, tim = station_matrices(graph, st)
    dem, transform = dep.load_dem()
    horizons = lw.station_horizons(st, dem, transform)
    lat, lon = lw.site(st)
    shadow = lw.shadow_minutes(horizons, SOL, lat, lon)
    s = {"sol": SOL, "starts_ltst_h": [float(v) for v in STARTS], "step_s": lw.STEP_S,
         "shadow_minutes_in_daylight": {str(i): round(float(m), 1) for i, m in zip(st.id[1:], shadow[1:])},
         "runs": {}}

    for name, max_d in SCENARIOS.items():
        for wname, wp in WAITS.items():
            base = Problem(energy=dis, prize=st.prize, budget=BUDGET_WH * (1 - MARGIN) * J_PER_WH, time=tim,
                           service_s=st.service_s, service_j=st.service_s * SERVICE_POWER_W,
                           max_duration_s=max_d, wait_power_w=wp)
            plain = dp.solve(base)
            t0 = time.perf_counter()
            rows, best = lw.sweep(graph, st, base, SOL, STARTS, dem, transform)
            sweep_s = time.perf_counter() - t0
            for row in rows:
                row["jaccard_vs_no_windows"] = round(jaccard(row["route"], plain.route), 3)
                row["same_order_as_no_windows"] = row["route"] == plain.route
                row.pop("windows_s")
            s["runs"][f"{name}/{wname}"] = {
                "no_windows_prize": float(plain.prize), "no_windows_order": [str(st.id[k]) for k in plain.route],
                "sweep_s": round(sweep_s, 1), "solve_s_max": max(r["solve_s"] for r in rows),
                "best": {k: best[k] for k in ("start_ltst_h", "prize", "order", "walk_sunlit_share",
                                              "walk_min_sun_elevation_deg", "service_sunlit_share", "energy_j",
                                              "duration_s")},
                "full_prize_departures_ltst_h": [r["start_ltst_h"] for r in rows if abs(r["prize"] - plain.prize) < 1e-9],
                "rows": rows}
            print(name, wname, "no windows", plain.prize, "best", dep.clock(best["start_ltst_h"]), best["prize"],
                  "full-prize departures", len(s["runs"][f"{name}/{wname}"]["full_prize_departures_ltst_h"]),
                  "sweep", round(sweep_s, 1), "s")

    (OUT / "light_windows.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    figure(s)


def figure(s):
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    for name in SCENARIOS:
        run = s["runs"][f"{name}/wait_0_w"]
        x = [r["start_ltst_h"] for r in run["rows"]]
        ax_a.plot(x, [r["prize"] for r in run["rows"]], color=COLOURS[name], lw=2, label=LABELS[name])
        ax_a.axhline(run["no_windows_prize"], color=COLOURS[name], lw=1, ls="--",
                     label=f"{LABELS[name]}, ignoring the light")
        ax_b.plot(x, [r["jaccard_vs_no_windows"] for r in run["rows"]], color=COLOURS[name], lw=2,
                  label=LABELS[name])
        b = run["best"]
        ax_a.scatter([b["start_ltst_h"]], [b["prize"]], s=50, color=COLOURS[name], edgecolor="white",
                     linewidth=1.5, zorder=3)
    ax_a.set_ylabel("Points collected (rubric S1)")
    ax_b.set_ylabel("Overlap with the stations chosen\nignoring the light (Jaccard)")
    ax_b.set_ylim(-0.03, 1.05)
    for ax in (ax_a, ax_b):
        ax.set_xlabel(f"Departure, local true solar time (sol {s['sol']})")
        ax.set_xticks(range(5, 20, 2), [f"{h:02d}:00" for h in range(5, 20, 2)])
        ax.grid(color="#e4e3df", linewidth=0.6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(labelsize=8)
        ax.legend(fontsize=8, frameon=False, loc="lower center")
    fig.savefig(FIG / "e5_fig6_light_windows.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
