"""E12 numbers and figures for the paper (paper/notes/E12_radiation_dose.md).

The EVAs are E5's two tours (Diana, src/orienteering/run.py) from the habitat at
the box centre, with E4's return-time raster (Aaron, src/grafos/build_rv.py):
    nominal  data/e5/tour_nominal.gpkg  13 stations
    max120   data/e5/tour_120min.gpkg   8 stations, --max-duration-min 120

Usage (repo root), after rad_data.py and, for each tour, route_dose.py,
sep_alert.py --no-out-and-back (out dirs data/e12/tours/<tour>/) and
sensitivity.py on the nominal tour (see the note's Reproduce section):
    python src/radiation/paper_figures.py
Inputs:  data/e12/rad_summary.json, rad_dose_rate.csv, data/e12/tours/<tour>/*.json,
         data/e12/tours/nominal/sensitivity.csv, data/e5/tour_*.gpkg, data/e4/rv_time_s.tif,
         data/base/dem_1m.tif, slope_deg.tif, data/e2/cell_sequence.csv and trajectory.geojson
         (method check), data/e12/route_dose_summary.json (old provisional route, comparison)
Outputs: data/e12/e12_summary.json   every number quoted in the note
         paper/figures/e12_fig1_rad_dose_rate.png
         paper/figures/e12_fig2_eva_dose_timeline.png
         paper/figures/e12_fig3_sensitivity.png
         paper/figures/e12_fig4_return_time_map.png
"""
import json
import sys
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.dates as mdates  # noqa: E402
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
import rasterio  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fisica.edge_cost import NEIGHBOURS, edge_costs  # noqa: E402
from radiation.common import BASE, E2_OUTPUT, E12_OUTPUT, PRODUCTS, REPO  # noqa: E402
from radiation.return_time import fallback_return_time  # noqa: E402
from radiation.route_dose import (DoseRate, background_rate, load_route, route_timeline,  # noqa: E402
                                  station_indices)
from radiation.sep_alert import BASELINE_WINDOW, K_ON, load_rates  # noqa: E402

FIG_DIR = REPO / "paper" / "figures"
TOURS_DIR = E12_OUTPUT / "tours"
TOURS = {
    "nominal": {"file": PRODUCTS / "e5" / "tour_nominal.gpkg", "label": "Nominal tour (13 stations)"},
    "max120": {"file": PRODUCTS / "e5" / "tour_120min.gpkg", "label": "120 min tour (8 stations)"},
}

# Reference palette (dataviz skill, light mode)
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
MUTED = "#898781"
GRID = "#e1e0d9"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a"]      # blue, orange, aqua (fixed order)
CRITICAL = "#d03b3b"                            # status: alarm
BLUE_RAMP = ["#cde2fb", "#9ec5f4", "#6da7ec", "#3987e5", "#256abf", "#184f95", "#0d366b"]

plt.rcParams.update({
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": MUTED, "axes.labelcolor": TEXT_2, "xtick.color": MUTED, "ytick.color": MUTED,
    "text.color": TEXT, "axes.grid": True, "grid.color": GRID, "grid.linewidth": 0.6,
    "axes.spines.top": False, "axes.spines.right": False, "font.size": 9, "axes.titlesize": 10,
    "axes.titleweight": "bold", "axes.titlelocation": "left", "legend.frameon": False,
    "lines.linewidth": 1.8,
})


def load_json(name, folder=E12_OUTPUT):
    return json.loads((Path(folder) / name).read_text(encoding="utf-8"))


def tour_timeline(tour, sep, dose_rate, start_utc=None):
    """E12 timeline of one E5 tour, with the return time from the raster named in its sep_alert.json."""
    xy, stations = load_route(TOURS[tour]["file"])
    tl = route_timeline(xy, BASE / "dem_1m.tif", dose_rate, start_utc=start_utc, stations=stations,
                        return_raster=REPO / sep["return_time_map"]["file"])
    return tl, stations


# ----------------------------------------------------------------------- checks

def e3_edge_check(dem_path, slope_path):
    """E12 route times against the sum of E3 edge times over E2's 8-connected cell sequence.

    A check of the method, not a route number: Curiosity's cell sequence is a long
    real path, so it tests the timing on many kinds of steps.
    - the cell sequence given to route_timeline as a chain of cell centres must give
      exactly the E3 edge sum (step method "e3_edges");
    - Curiosity's free line (pose positions) is resampled every 1 m: compare per metre.
    """
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float64)
    with rasterio.open(slope_path) as src:
        slope = src.read(1).astype(np.float64)
    # no slope limits: the rover's real path crosses steeper edges than a planner would
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", UserWarning)          # 60 deg is on purpose here
        time_s, _, _ = edge_costs(dem, 1.0, max_slope_deg=60.0, cell_slope_deg=slope, max_cell_slope_deg=None)
    seq = pd.read_csv(E2_OUTPUT / "cell_sequence.csv")
    k_of = {d: k for k, d in enumerate(NEIGHBOURS)}
    total, length, missing = 0.0, 0.0, 0
    r, c = seq["row"].to_numpy(), seq["col"].to_numpy()
    for i in range(len(seq) - 1):
        k = k_of.get((int(r[i + 1] - r[i]), int(c[i + 1] - c[i])))
        t = time_s[k, r[i], c[i]] if k is not None else np.nan
        if np.isfinite(t):
            total += float(t)
            length += float(np.hypot(*NEIGHBOURS[k]))
        else:
            missing += 1
    with rasterio.open(dem_path) as src:
        T = src.transform
    centres = np.column_stack([T.c + (c + 0.5) * T.a, T.f + (r + 0.5) * T.e])
    tl_cells = route_timeline(centres, dem_path, DoseRate.constant(1.0))
    t_cells = float(tl_cells["t_s"].iloc[-1])
    xy, _ = load_route(E2_OUTPUT / "trajectory.geojson")
    tl = route_timeline(xy, dem_path, DoseRate.constant(1.0))
    t_line, l_line = float(tl["t_s"].iloc[-1]), float(tl["dist_m"].iloc[-1])
    return {"e3_edges_cell_sequence_h": round(total / 3600, 4),
            "e12_on_cell_chain_h": round(t_cells / 3600, 4), "e12_cell_chain_method": tl_cells.attrs["method"],
            "e12_cell_chain_vs_e3_relative_difference": float(f"{t_cells / total - 1:.2e}"),
            "e12_resampled_line_h": round(t_line / 3600, 3), "e12_line_method": tl.attrs["method"],
            "cell_path_length_m": round(length, 1), "line_length_m": round(l_line, 1),
            "cell_steps": int(len(seq) - 1), "steps_without_edge": missing,
            "time_relative_difference": round(t_line / total - 1, 4),
            "s_per_m_cells": round(total / length, 4), "s_per_m_line": round(t_line / l_line, 4),
            "s_per_m_relative_difference": round((t_line / l_line) / (total / length) - 1, 4)}


def tour_against_e5(tour, sep):
    """E12's clock and walking energy on an E5 tour against E5's own numbers (same E3 edges)."""
    import geopandas as gpd
    path = TOURS[tour]["file"]
    e5 = gpd.read_file(path, layer="route").iloc[0]
    stops = gpd.read_file(path, layer="stops")
    tl, stations = tour_timeline(tour, sep, DoseRate.constant(1.0))
    idx = station_indices(tl[["x", "y"]].to_numpy(), stations)
    e12_leave = {s["id"]: float(tl["t_s"].iloc[i]) for s, (i, _) in zip(stations, idx)}
    e5_leave = dict(zip(stops["id"], stops["departure_time_s"]))
    diff = [abs(e12_leave[k] - e5_leave[k]) for k in e12_leave]
    return {"e5_file": path.relative_to(REPO).as_posix(), "e5_order": e5["order"],
            "e5_duration_min": round(float(e5["duration_s"]) / 60, 2),
            "e12_eva_time_min": round(float(tl["t_s"].iloc[-1]) / 60, 2),
            "e5_walk_time_s": round(float(e5["travel_time_s"]), 2),
            "e12_walk_time_s": round(float(tl["walk_s"].iloc[-1]), 2),
            "e5_length_m": round(float(e5["length_m"]), 2), "e12_length_m": round(float(tl["dist_m"].iloc[-1]), 2),
            "e5_walk_energy_wh": round(float(e5["walk_energy_wh"]), 3),
            "e12_walk_energy_wh": round(float(tl["energy_wh"].iloc[-1]), 3),
            "e5_total_energy_wh_with_service": round(float(e5["energy_wh"]), 1),
            "e5_service_power_w": float(e5["service_power_w"]),
            "stations": len(stations),
            "max_abs_diff_station_departure_s": float(f"{max(diff):.3g}")}


def e4_raster_against_fallback(sep):
    """E4's rv_time_s.tif against E12's own recipe for the same habitat (computed, not cached)."""
    path = REPO / sep["return_time_map"]["file"]
    with rasterio.open(path) as src:
        e4 = src.read(1).astype(np.float64)
    fb, _, info = fallback_return_time(BASE / "dem_1m.tif", BASE / "slope_deg.tif", sep["habitat"]["xy"])
    fb = fb.astype(np.float64)
    both = np.isfinite(e4) & np.isfinite(fb)
    finite = e4[np.isfinite(e4)]
    hr, hc = info["habitat_cell_row_col"]
    return {"file": sep["return_time_map"]["file"],
            "habitat_cell_row_col": [hr, hc], "habitat_snapped_cells": info["habitat_snapped_cells"],
            "habitat_cell_return_s": float(e4[hr, hc]),
            "reachable_cells_e4": int(np.isfinite(e4).sum()), "reachable_cells_e12_recipe": int(np.isfinite(fb).sum()),
            "cells_reachable_in_only_one": int((np.isfinite(e4) != np.isfinite(fb)).sum()),
            "max_abs_diff_s": float(f"{np.max(np.abs(e4[both] - fb[both])):.3g}"),
            "reachable_share_of_grid": round(float(finite.size / e4.size), 4),
            "main_component_share": info["main_component_share"],
            "median_h": round(float(np.median(finite)) / 3600, 3),
            "p95_h": round(float(np.percentile(finite, 95)) / 3600, 3),
            "max_h": round(float(finite.max()) / 3600, 3)}


# ---------------------------------------------------------------------- figures

def fig1_rad(rad, sep):
    df = pd.read_csv(E12_OUTPUT / "rad_dose_rate.csv", parse_dates=["utc"])
    good = df[df["quality_ok"]].set_index("utc")
    daily = good[["dose_e_ugy_day", "dose_b_rtg_ugy_day"]].resample("D").mean()
    ev = sep["strongest_event"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.4), gridspec_kw={"width_ratios": [1.7, 1]})

    b0, b1 = pd.Timestamp(rad["boxwork_utc"][0]), pd.Timestamp(rad["boxwork_utc"][1])
    a.axvspan(b0, b1, color=GRID, alpha=0.6, lw=0)
    a.text(b0 + (b1 - b0) / 2, 86, "boxwork sols 4541–4848", ha="center", color=TEXT_2, fontsize=8)
    a.plot(daily.index, daily["dose_e_ugy_day"], color=SERIES[0], label="Tissue-equivalent (E)")
    a.plot(daily.index, daily["dose_b_rtg_ugy_day"], color=SERIES[1], label="Silicon, MMRTG-corrected (B)")
    a.annotate("SEP 2025-11-11", xy=(pd.Timestamp(ev["onset_utc"]), daily["dose_e_ugy_day"].loc["2025-11-11"]),
               xytext=(28, 12), textcoords="offset points", ha="left", color=TEXT_2, fontsize=8,
               arrowprops={"arrowstyle": "-", "color": MUTED, "lw": 0.8})
    a.set_ylim(80, 210)
    a.set_ylabel("Daily mean dose rate (µGy/day)")
    a.set_title("(a) RAD surface dose rate, 2025–2026")
    a.legend(loc="upper left", fontsize=8)
    a.xaxis.set_major_formatter(mdates.DateFormatter("%b %Y"))
    a.xaxis.set_major_locator(mdates.MonthLocator(bymonth=[1, 5, 9]))

    rates = load_rates()
    w = rates.loc["2025-11-10T12:00":"2025-11-12T12:00"]
    base = rates.rolling(BASELINE_WINDOW, min_periods=10).median().shift(1).loc[w.index]
    b.plot(w.index, w.to_numpy(), color=SERIES[0], lw=1.4, marker="o", ms=2.5, label="Detector E, 17 min")
    b.plot(base.index, K_ON * base.to_numpy(), color=MUTED, lw=1.2, ls="--", label=f"{K_ON}× baseline")
    t_alarm = pd.Timestamp(ev["alarm_utc"])
    b.axvline(t_alarm, color=CRITICAL, lw=1.2)
    b.text(t_alarm, 300, " alarm " + t_alarm.strftime("%H:%M UTC"), color=TEXT, fontsize=8, va="top")
    b.set_ylim(120, 310)
    b.set_ylabel("Dose rate (µGy/day)")
    b.set_title("(b) 2025-11-11 event and alarm")
    b.legend(loc="upper left", fontsize=7.5, bbox_to_anchor=(0.0, 0.9))
    b.xaxis.set_major_formatter(mdates.DateFormatter("%d %b\n%H:%M"))
    b.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 12]))
    fig.tight_layout()
    fig.savefig(FIG_DIR / "e12_fig1_rad_dose_rate.png", dpi=150)
    plt.close(fig)


def fig2_timeline(seps, rate_bg):
    """(a) dose along both tours, and the nominal one during the storm; (b) time back to the habitat."""
    bg = {t: tour_timeline(t, seps[t], DoseRate.constant(rate_bg))[0] for t in TOURS}
    far = seps["nominal"]["replay"]["farthest"]
    tl_sep, _ = tour_timeline("nominal", seps["nominal"], DoseRate.series(), start_utc=far["eva_start_utc"])
    nom, short = bg["nominal"], bg["max120"]
    h, h2 = nom["t_s"] / 3600, short["t_s"] / 3600
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.3))
    a.plot(h, nom["dose_ugy"], color=SERIES[0], label=f"{TOURS['nominal']['label']}, background")
    a.plot(h, tl_sep["dose_ugy"], color=SERIES[1], label="Nominal tour during the 2025-11-11 SEP")
    a.plot(h2, short["dose_ugy"], color=SERIES[2], label=f"{TOURS['max120']['label']}, background")
    t_alarm_h = (pd.Timestamp(seps["nominal"]["strongest_event"]["alarm_utc"])
                 - pd.Timestamp(far["eva_start_utc"])).total_seconds() / 3600
    a.axvline(t_alarm_h, color=CRITICAL, lw=1.2)
    top = float(tl_sep["dose_ugy"].iloc[-1]) * 1.12
    a.text(t_alarm_h, top * 0.93, "alarm ", color=TEXT, fontsize=8, va="center", ha="right")
    for tl, hh in ((nom, h), (tl_sep, h), (short, h2)):
        a.text(hh.iloc[-1], tl["dose_ugy"].iloc[-1], f" {tl['dose_ugy'].iloc[-1]:.1f} µGy", color=TEXT_2,
               fontsize=8, va="center")
    a.set_xlim(0, h.iloc[-1] * 1.22)
    a.set_ylim(0, top)
    a.set_xlabel("EVA time (h)")
    a.set_ylabel("Accumulated absorbed dose (µGy)")
    a.set_title("(a) Dose along the E5 tours")
    a.legend(loc="lower right", fontsize=7.5)

    b.plot(h, nom["return_s"] / 3600, color=SERIES[0], label="Nominal tour, fastest path (E4 R_T)")
    b.plot(h, nom["return_route_s"] / 3600, color=SERIES[0], lw=1.0, ls="--",
           label="Nominal tour, along the tour")
    b.plot(h2, short["return_s"] / 3600, color=SERIES[2], label="120 min tour, fastest path (E4 R_T)")
    b.set_xlabel("EVA time (h)")
    b.set_ylabel("Walking time back to the habitat (h)")
    b.set_title("(b) Time to shelter if the alarm comes now")
    b.legend(loc="upper right", fontsize=7.5)
    b.set_ylim(0, max(float(np.nanmax(nom["return_route_s"])), float(np.nanmax(nom["return_s"]))) / 3600 * 1.45)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "e12_fig2_eva_dose_timeline.png", dpi=150)
    plt.close(fig)
    return {"nominal_eva_h": round(float(h.iloc[-1]), 3),
            "nominal_dose_background_ugy": round(float(nom["dose_ugy"].iloc[-1]), 2),
            "nominal_dose_during_sep_ugy": round(float(tl_sep["dose_ugy"].iloc[-1]), 2),
            "max120_eva_h": round(float(h2.iloc[-1]), 3),
            "max120_dose_background_ugy": round(float(short["dose_ugy"].iloc[-1]), 2)}


def fig3_sensitivity():
    """Dose and walking energy against eta on the nominal tour.

    The fixed-energy-budget reading of sensitivity.py is left out: E12 counts only
    the walking energy, and on a tour most of the energy is station work (E5,
    205 W), so a budget of walking energy alone would mislead.
    """
    df = pd.read_csv(TOURS_DIR / "nominal" / "sensitivity.csv")
    m = df[df.gravity == "mars"]
    sp, en = m[m.eta_mode == "speed"], m[m.eta_mode == "energy"]
    fig, (a, b) = plt.subplots(1, 2, figsize=(9.2, 3.3), sharex=True)
    lines = [(sp, "dose_ugy_rel", SERIES[1], "Sand slows the walk (V/η)"),
             (en, "dose_ugy_rel", SERIES[0], "Sand only raises energy (E·η)")]
    for d, col, color, label in lines:
        a.plot(d.eta, d[col], color=color, marker="o", ms=4, label=label)
    a.set_ylabel("Dose / nominal")
    a.set_xlabel("Terrain factor η (applied to the whole walk)")
    a.set_title("(a) Dose, Mars gravity, nominal tour")
    a.legend(loc="upper left", fontsize=7.5)
    for d, color, label in [(sp, SERIES[1], "Sand slows the walk (V/η)"),
                            (en, SERIES[0], "Sand only raises energy (E·η)")]:
        b.plot(d.eta, d.energy_wh_rel, color=color, marker="o", ms=4, label=label)
    g = df[(df.eta == 1.0) & (df.eta_mode == "energy")].set_index("gravity").energy_wh_rel
    b.text(0.40, 0.36, "Gravity at η = 1 (walking energy / nominal):\n"
           f"Moon {g['moon']:.2f} · Mars {g['mars']:.2f} · Earth {g['earth']:.2f}\n"
           "EVA time and dose: identical for all three", transform=b.transAxes, fontsize=7.5, color=TEXT_2,
           va="top")
    b.set_ylabel("Walking energy / nominal")
    b.set_xlabel("Terrain factor η (applied to the whole walk)")
    b.set_title("(b) Walking energy, Mars gravity, nominal tour")
    b.legend(loc="upper left", fontsize=7.5)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "e12_fig3_sensitivity.png", dpi=150)
    plt.close(fig)


def fig4_map(sep):
    with rasterio.open(REPO / sep["return_time_map"]["file"]) as src:
        ret = src.read(1) / 60.0
        b = src.bounds
    cmap = LinearSegmentedColormap.from_list("blue_seq", BLUE_RAMP)
    cmap.set_bad(GRID)
    fig, ax = plt.subplots(figsize=(5.6, 4.8))
    ext = [0, b.right - b.left, 0, b.top - b.bottom]
    im = ax.imshow(ret, cmap=cmap, extent=ext, interpolation="nearest")
    styles = {"nominal": {"color": SERIES[1], "lw": 1.6, "ls": "-"},
              "max120": {"color": TEXT, "lw": 0.9, "ls": "--"}}
    for tour, st in styles.items():
        xy, stations = load_route(TOURS[tour]["file"])
        ax.plot(xy[:, 0] - b.left, xy[:, 1] - b.bottom, label=TOURS[tour]["label"], **st)
    _, stations = load_route(TOURS["nominal"]["file"])
    sx = np.array([s["x"] for s in stations]) - b.left
    sy = np.array([s["y"] for s in stations]) - b.bottom
    ax.plot(sx, sy, marker="o", ms=4.5, mfc=SURFACE, mec=TEXT, mew=0.9, ls="none", label="Stations")
    hx, hy = sep["habitat"]["xy"]
    ax.plot(hx - b.left, hy - b.bottom, marker="s", ms=7, color=TEXT, ls="none", label="Habitat (input)")
    ax.grid(False)
    ax.set_xlabel("Easting in the crop (m)")
    ax.set_ylabel("Northing in the crop (m)")
    ax.set_title("Fastest walk back to the habitat (min), E4")
    cb = fig.colorbar(im, ax=ax, fraction=0.04, pad=0.02)
    cb.set_label("minutes; grey = blocked or unreachable", color=TEXT_2)
    cb.outline.set_visible(False)
    ax.legend(loc="upper left", fontsize=7.5, frameon=True, facecolor=SURFACE, edgecolor=GRID, framealpha=0.92)
    fig.tight_layout()
    fig.savefig(FIG_DIR / "e12_fig4_return_time_map.png", dpi=150)
    plt.close(fig)


def main():
    FIG_DIR.mkdir(parents=True, exist_ok=True)
    rad = load_json("rad_summary.json")
    seps = {t: load_json("sep_alert.json", TOURS_DIR / t) for t in TOURS}
    routes = {t: load_json("route_dose_summary.json", TOURS_DIR / t) for t in TOURS}
    sens = load_json("sensitivity.json", TOURS_DIR / "nominal")
    sep = seps["nominal"]                     # detection does not depend on the tour
    rate_bg = background_rate()
    fig1_rad(rad, sep)
    timeline = fig2_timeline(seps, rate_bg)
    fig3_sensitivity()
    fig4_map(sep)
    old = load_json("route_dose_summary.json")           # Curiosity out and back (e12-dose-v1)
    summary = {
        "rad": {k: rad[k] for k in ["observations", "observations_flagged_fill", "first_utc", "last_utc",
                                    "boxwork_utc", "nominal", "unit_check", "within_day_cv_median",
                                    "mmrtg_share_of_b", "isolated_spikes"]},
        "rad_daily_boxwork": rad["boxwork_daily_mean_stats"],
        "rad_monthly_dose_e": {k: v["dose_e"] for k, v in rad["monthly_median"].items()},
        "sep": {k: sep[k] for k in ["rule", "events", "strongest_event", "habitat"]},
        "sep_threshold_sweep": sep["threshold_sweep"],
        "tours": {t: {"route_dose": routes[t], "replay": seps[t]["replay"],
                      "habitat": seps[t]["habitat"], "return_time_map": seps[t]["return_time_map"]}
                  for t in TOURS},
        "timeline_figure": timeline,
        "sensitivity_nominal_tour": sens,
        "return_time_map_e4": e4_raster_against_fallback(sep),
        "check_tours_against_e5": {t: tour_against_e5(t, seps[t]) for t in TOURS},
        "check_against_e3_edges": e3_edge_check(BASE / "dem_1m.tif", BASE / "slope_deg.tif"),
        "old_provisional_route": {"route": old["route"], "out_and_back": old["out_and_back"],
                                  "habitat": old["habitat"]["xy"], **{k: old[k] for k in (
                                      "length_m", "eva_time_h", "energy_wh", "dose_ugy", "dose_usv_est",
                                      "steps_steeper_than_edge_limit_pct")}},
    }
    (E12_OUTPUT / "e12_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    for k in ("check_tours_against_e5", "return_time_map_e4", "check_against_e3_edges"):
        print(k, json.dumps(summary[k], indent=2))
    print(json.dumps(timeline, indent=2))
    for p in sorted(FIG_DIR.glob("e12_*.png")):
        print(p.name, p.stat().st_size // 1024, "KB")


if __name__ == "__main__":
    main()
