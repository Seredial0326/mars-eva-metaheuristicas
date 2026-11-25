"""Numbers and the figure of the P6 note (paper/notes/P6_departure_time.md): best time to
leave for the E5 tours.

Run from the repo root (inputs as in the E5 note; REMS release rems-v1 in data/rems for
the sunrise/sunset check, skipped if missing):
    python src/orienteering/paper_departure.py [--derive-only]

Writes data/p6/departure_summary.json and paper/figures/p6_fig1_departure.png.
--derive-only recomputes the derived block (shadow_shortening_min) in the existing
departure_summary.json, without planning or scoring again.
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
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from grafos.build_rv import SERVICE_POWER_W  # noqa: E402

from api.plan import PlanRequest  # noqa: E402
from orienteering import departure as dep  # noqa: E402
from orienteering.data_io import STATIONS_PATH, read_stations  # noqa: E402
from orienteering.network import load_graph  # noqa: E402
from orienteering.paper_figures import BOX_CENTRE, BUDGET_WH, MARGIN  # noqa: E402
from orienteering.tour import plan_tour  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT, FIG = REPO / "data" / "p6", REPO / "paper" / "figures"
REMS = REPO / "data" / "rems" / "rems_weather_msl.json"
SOL = 4711                                  # the Nevado Sajama drill, the 3D view's default sol
STARTS = np.arange(5.0, 19.0 + 1e-9, 0.25)  # every 15 min, local true solar time
MARS_YEAR_SOLS = 668.6
SEASON_STEP = 14
TOURS = {"nominal": None, "max_120_min": 120.0}
COLOURS = {"nominal": "#2a78d6", "max_120_min": "#eb6834"}   # dataviz slots 1-2
LABELS = {"nominal": "Nominal tour (181 min)", "max_120_min": "120 min tour"}


def shadow_shortening(tours):
    """Minutes the terrain's shadows cut from each end of the lit window (lit window with the
    terrain against the one with a smooth horizon), per tour, and their range over the tours.
    The team's results table reads shadow_shortening_min.range."""
    out, cuts = {}, []
    for name, t in tours.items():
        lit, flat = t["lit_window_ltst_h"], t["lit_window_no_terrain_ltst_h"]
        if not lit or not flat:
            continue
        start, end = round((lit[0] - flat[0]) * 60), round((flat[1] - lit[1]) * 60)
        out[name] = {"start": start, "end": end}
        cuts += [start, end]
    if cuts:
        out["min"], out["max"] = min(cuts), max(cuts)
        out["range"] = f"{min(cuts)}–{max(cuts)}"
    return out


def main():
    if "--derive-only" in sys.argv[1:]:
        path = OUT / "departure_summary.json"
        s = json.loads(path.read_text(encoding="utf-8"))
        s["shadow_shortening_min"] = shadow_shortening(s["tours"])
        path.write_text(json.dumps(s, indent=1), encoding="utf-8")
        print(s["shadow_shortening_min"])
        return
    OUT.mkdir(parents=True, exist_ok=True)
    FIG.mkdir(parents=True, exist_ok=True)
    graph, _ = load_graph()
    gdf_stations = read_stations(graph, STATIONS_PATH)
    stations = [{"id": str(i), "x": float(x), "y": float(y), "type": str(t), "score": float(p),
                 "service_time_min": float(s) / 60.0}
                for i, x, y, t, p, s in zip(gdf_stations.id, gdf_stations.x, gdf_stations.y,
                                            gdf_stations.type, gdf_stations.prize, gdf_stations.service_s)]
    dem, transform = dep.load_dem()
    s = {"sol": SOL, "starts_ltst_h": [float(v) for v in STARTS], "eye_m": dep.EYE_M,
         "horizon_m": dep.HORIZON_M, "azimuth_bins": dep.AZIMUTH_BINS, "tours": {}}

    tracks = {}
    for name, max_min in TOURS.items():
        req = PlanRequest(start=BOX_CENTRE, stations=stations, energy_budget_wh=BUDGET_WH, margin=MARGIN,
                          service_energy_wh_per_min=SERVICE_POWER_W / 60.0, max_duration_min=max_min,
                          human_cost=False)
        fc, _ = plan_tour(req, graph)
        xy, t_s = dep.tour_from_plan(fc)
        t0 = time.perf_counter()
        horizon = dep.horizon_table(xy, dem, transform)
        horizon_s = time.perf_counter() - t0
        t0 = time.perf_counter()
        rows, best, window = dep.score_departures(xy, t_s, SOL, STARTS, horizon)
        score_s = time.perf_counter() - t0
        flat_rows, flat_best, flat_window = dep.score_departures(xy, t_s, SOL, STARTS, None)
        shadowed = [r for r in rows if r["shadow_share"] > 0]
        tracks[name] = (xy, t_s, horizon, rows, flat_rows)
        s["tours"][name] = {
            "duration_min": round(float(t_s[-1]) / 60.0, 1), "vertices": len(xy),
            "horizon_s": round(horizon_s, 2), "score_s": round(score_s, 3),
            "best": best, "lit_window_ltst_h": window, "lit_window_no_terrain_ltst_h": flat_window,
            "max_shadow_share": max(r["shadow_share"] for r in rows),
            "max_shadow_share_at_ltst_h": max(rows, key=lambda r: r["shadow_share"])["start_ltst_h"],
            "starts_with_terrain_shadow": len(shadowed),
            "rows": rows}

    # The lit window through one Mars year (120 min tour), every SEASON_STEP sols
    xy, t_s, horizon, _, _ = tracks["max_120_min"]
    lon, lat_pc = dep.lon_lat(*xy[0])
    lat = dep.planetographic_latitude(lat_pc)
    season = []
    for sol in range(SOL, SOL + int(MARS_YEAR_SOLS) + 1, SEASON_STEP):
        _, best, window = dep.score_departures(xy, t_s, sol, np.arange(5.0, 19.0 + 1e-9, 1 / 12), horizon)
        ls = float(dep.sun_position(dep.utc_of_true_solar_time(sol, 12.0, lon), lat, lon)["ls"])
        season.append({"sol": sol, "ls": round(ls, 1), "best_ltst_h": best["start_ltst_h"],
                       "best_min_sun_elevation_deg": best["min_sun_elevation_deg"], "lit_window_ltst_h": window})
    s["shadow_shortening_min"] = shadow_shortening(s["tours"])
    s["season_120_min"] = season
    widths = [w["lit_window_ltst_h"][1] - w["lit_window_ltst_h"][0] for w in season if w["lit_window_ltst_h"]]
    s["season_window_width_h_min_max"] = [round(min(widths), 2), round(max(widths), 2)]
    s["season_sols_without_window"] = sum(1 for w in season if not w["lit_window_ltst_h"])

    # REMS: computed sunrise and sunset (smooth horizon) against the reported ones
    if REMS.exists():
        s["rems_check"] = rems_check(lat, lon)
        rec = next((r for r in json.loads(REMS.read_text(encoding="utf-8"))["soles"] if int(r["sol"]) == SOL), None)
        if rec:
            s["rems_sol"] = {k: rec[k] for k in ("sol", "terrestrial_date", "ls", "min_temp", "max_temp",
                                                 "sunrise", "sunset", "atmo_opacity")}

    (OUT / "departure_summary.json").write_text(json.dumps(s, indent=1), encoding="utf-8")
    for name in TOURS:
        t = s["tours"][name]
        print(name, t["duration_min"], "min; best", dep.clock(t["best"]["start_ltst_h"]), "window",
              t["lit_window_ltst_h"], "no terrain", t["lit_window_no_terrain_ltst_h"],
              "max shadow", t["max_shadow_share"], "at", t["max_shadow_share_at_ltst_h"])
    print("season widths", s["season_window_width_h_min_max"], "without window", s["season_sols_without_window"])
    print("rems", s.get("rems_check"), s.get("rems_sol"))
    figure(s, tracks)


def rems_check(lat, lon):
    """Sunrise and sunset, local mean solar time, where the Sun crosses a smooth horizon,
    against the times REMS reports for each sol (minutes)."""
    soles = json.loads(REMS.read_text(encoding="utf-8"))["soles"]
    hours = np.arange(3.0, 21.0, 1 / 60)
    rise_d, set_d = [], []
    for rec in soles:
        if ":" not in str(rec.get("sunrise", "")) or ":" not in str(rec.get("sunset", "")):
            continue
        sol = int(rec["sol"])
        utc0 = dep.utc_of_true_solar_time(sol, 12.0, lon)
        sun = dep.sun_position(utc0 + (hours - 12.0) / 24 * dep.SOL_IN_SECONDS * 1000, lat, lon,
                               tt=dep.tt_minus_utc(utc0))
        e = sun["elevation"]
        up = np.flatnonzero((e[:-1] <= 0) & (e[1:] > 0))
        down = np.flatnonzero((e[:-1] > 0) & (e[1:] <= 0))
        if not len(up) or not len(down):
            continue
        hm = [int(v) + int(w) / 60 for v, w in (rec["sunrise"].split(":"), rec["sunset"].split(":"))]
        rise_d.append((sun["lmst"][up[0]] - hm[0]) * 60)
        set_d.append((sun["lmst"][down[0]] - hm[1]) * 60)
    both = np.abs(np.r_[rise_d, set_d])
    return {"sols": len(rise_d), "median_abs_min": round(float(np.median(both)), 2),
            "p95_abs_min": round(float(np.percentile(both, 95)), 2), "max_abs_min": round(float(both.max()), 2),
            "clock": "local mean solar time (with local true solar time the differences reach the equation of time, up to about 50 min)"}


def figure(s, tracks):
    fig, (ax_a, ax_b) = plt.subplots(1, 2, figsize=(12, 4.6), constrained_layout=True)
    for name in TOURS:
        rows, flat = tracks[name][3], tracks[name][4]
        x = [r["start_ltst_h"] for r in rows]
        ax_a.plot(x, [100 * r["sunlit_share"] for r in rows], color=COLOURS[name], lw=2, label=LABELS[name])
        ax_a.plot(x, [100 * r["sunlit_share"] for r in flat], color=COLOURS[name], lw=1.2, ls="--",
                  label=LABELS[name] + ", no terrain")
        best = s["tours"][name]["best"]
        ax_a.scatter([best["start_ltst_h"]], [100 * best["sunlit_share"]], s=50, color=COLOURS[name],
                     edgecolor="white", linewidth=1.5, zorder=3)
        ax_a.annotate(f"best {dep.clock(best['start_ltst_h'])}", (best["start_ltst_h"], 100 * best["sunlit_share"]),
                      xytext=(0, 6 if name == "nominal" else -14), textcoords="offset points", ha="center",
                      fontsize=8, color="#3a3a38")
    ax_a.set_xlabel(f"Departure, local true solar time (sol {s['sol']})")
    ax_a.set_ylabel("Share of the walk in sunlight (%)")
    ax_a.set_xticks(range(5, 20, 2), [f"{h:02d}:00" for h in range(5, 20, 2)])
    ax_a.legend(fontsize=8, frameon=False, loc="lower center")

    season = [w for w in s["season_120_min"] if w["lit_window_ltst_h"]]
    sols = [w["sol"] for w in season]
    lo = [w["lit_window_ltst_h"][0] for w in season]
    hi = [w["lit_window_ltst_h"][1] for w in season]
    ax_b.fill_between(sols, lo, hi, color=COLOURS["max_120_min"], alpha=0.25, lw=0,
                      label="departures with the whole 120 min tour in sunlight")
    ax_b.plot(sols, [w["best_ltst_h"] for w in season], color=COLOURS["max_120_min"], lw=2, label="best departure")
    ax_b.set_xlabel("Curiosity sol (one Mars year from sol 4711; labels give the season, Ls)")
    ax_b.set_ylabel("Departure, local true solar time")
    ax_b.set_yticks(range(6, 17, 2), [f"{h:02d}:00" for h in range(6, 17, 2)])
    ticks = season[::8]
    ax_b.set_xticks([w["sol"] for w in ticks], [f"{w['sol']}\nLs {w['ls']:.0f}°" for w in ticks], fontsize=7)
    ax_b.set_ylim(5.5, 17.5)
    ax_b.legend(fontsize=8, frameon=False, loc="upper center", ncol=2)
    for ax in (ax_a, ax_b):
        ax.grid(color="#e4e3df", linewidth=0.6)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        ax.tick_params(labelsize=8)
    fig.savefig(FIG / "p6_fig1_departure.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
