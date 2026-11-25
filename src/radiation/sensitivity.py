"""E12 - Sensitivity of EVA time, energy and dose to gravity G and terrain factor eta.

Why this is not trivial: in the nominal E3 model the walking speed is the Apollo
regression V(alpha) = 0.75 - 0.01 alpha, which does not depend on G, and Santee 2001
has no terrain factor. So for a FIXED route, G changes the energy but not the
time, and the dose (rate x time) does not move. G and eta reach the dose only
through the time outside:

    eta mode "energy": eta multiplies the energy (Pandolf-style surface factor);
                       time and dose unchanged. Lower bound for the dose.
    eta mode "speed":  sand slows the walk, V / eta; time and dose x eta (on the
                       sand part). Upper bound for the dose.
    budget-limited:    with a fixed energy budget B (the nominal route energy),
                       the EVA stops when B is spent; a costlier walk means a
                       shorter EVA and LESS dose.

Grid: G in {Moon 1.62, Mars 3.71, Earth 9.81} m/s^2, eta in {1.0, 1.2, 1.5, 1.8, 2.1}
(Pandolf/Soule terrain factors: 1.0 paved, 1.2 light brush, 1.5 heavy brush,
1.8 swamp, 2.1 loose sand [Soule1972, Pandolf1977]). Until sand.tif (E8) arrives,
eta applies to the whole route: this is the worst case for the sand share.

Usage:
    python src/radiation/sensitivity.py [--route ...] [--sand-raster FILE]
Writes data/e12/sensitivity.csv and sensitivity.json.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fisica.metabolic import G_EARTH, G_MARS, G_MOON, J_PER_WH  # noqa: E402
from radiation.common import BASE, E2_OUTPUT, E12_OUTPUT, SECONDS_PER_DAY  # noqa: E402
from radiation.route_dose import (background_rate, load_route, repo_relative, route_steps,  # noqa: E402
                                  sample_raster, walk)

GRAVITIES = {"moon": G_MOON, "mars": G_MARS, "earth": G_EARTH}
ETAS = [1.0, 1.2, 1.5, 1.8, 2.1]
MODES = ["energy", "speed"]


def budget_limited(t_s, energy_j, budget_j):
    """Time at which the cumulative energy reaches budget_j (or the route end)."""
    if energy_j[-1] <= budget_j:
        return float(t_s[-1]), False
    return float(np.interp(budget_j, energy_j, t_s)), True


def run(route_xy, dem_path, rate_ugy_day, stations=(), sand_raster=None, step_m=1.0):
    st = route_steps(route_xy, dem_path, step_m)
    points, d_h, alpha = st["points"], st["d_h"], st["alpha"]
    sand = None
    if sand_raster is not None:
        sand = np.nan_to_num(sample_raster(sand_raster, points, order=0)) >= 0.5
    nominal = walk(points, d_h, alpha, G_MARS, None, "energy", stations)
    budget_j = float(nominal["energy_j"][-1])
    rows = []
    for g_name, g in GRAVITIES.items():
        for mode in MODES:
            for eta in ETAS:
                eta_arg = eta if sand is None else np.where(sand, eta, 1.0)
                w = walk(points, d_h, alpha, g, eta_arg, mode, stations)
                t, e = w["t_s"], w["energy_j"]
                t_budget, stopped = budget_limited(t, e, budget_j)
                rows.append({
                    "gravity": g_name, "g_mps2": g, "eta_mode": mode, "eta": eta,
                    "eva_time_h": t[-1] / 3600, "energy_wh": e[-1] / J_PER_WH,
                    "dose_ugy": rate_ugy_day * t[-1] / SECONDS_PER_DAY,
                    "budget_time_h": t_budget / 3600,
                    "budget_dose_ugy": rate_ugy_day * t_budget / SECONDS_PER_DAY,
                    "budget_stops_early": stopped,
                })
    df = pd.DataFrame(rows)
    ref = df[(df.gravity == "mars") & (df.eta == 1.0) & (df.eta_mode == "energy")].iloc[0]
    for c in ["eva_time_h", "energy_wh", "dose_ugy", "budget_dose_ugy"]:
        df[c + "_rel"] = df[c] / ref[c]
    return df, budget_j / J_PER_WH, (float(sand.mean()) if sand is not None else 1.0)


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--route", default=str(E2_OUTPUT / "trajectory.geojson"))
    ap.add_argument("--dem", default=str(BASE / "dem_1m.tif"))
    ap.add_argument("--sand-raster")
    ap.add_argument("--out-dir", type=Path, default=E12_OUTPUT)
    args = ap.parse_args()

    xy, stations = load_route(args.route)
    rate = background_rate()
    df, budget_wh, sand_share = run(xy, args.dem, rate, stations, args.sand_raster)
    args.out_dir.mkdir(parents=True, exist_ok=True)
    df.round(4).to_csv(args.out_dir / "sensitivity.csv", index=False)

    def pick(g, mode, eta):
        r = df[(df.gravity == g) & (df.eta_mode == mode) & (df.eta == eta)].iloc[0]
        return {k: round(float(r[k]), 3) for k in ["eva_time_h", "energy_wh", "dose_ugy", "budget_dose_ugy",
                                                     "eva_time_h_rel", "energy_wh_rel", "dose_ugy_rel",
                                                     "budget_dose_ugy_rel"]}

    mars = df[df.gravity == "mars"]
    summary = {
        "route": repo_relative(args.route), "sand_raster": repo_relative(args.sand_raster),
        "eta_applied_to_share_of_route": round(sand_share, 3),
        "rate_ugy_day": rate, "budget_wh": round(budget_wh, 1),
        "reference": pick("mars", "energy", 1.0),
        "gravity_moon_vs_earth_at_eta1": {"moon": pick("moon", "energy", 1.0), "earth": pick("earth", "energy", 1.0)},
        "eta_2_1_on_mars": {"energy_mode": pick("mars", "energy", 2.1), "speed_mode": pick("mars", "speed", 2.1)},
        "ranges_on_mars": {
            "dose_rel": [round(float(mars.dose_ugy_rel.min()), 3), round(float(mars.dose_ugy_rel.max()), 3)],
            "energy_rel": [round(float(mars.energy_wh_rel.min()), 3), round(float(mars.energy_wh_rel.max()), 3)],
            "budget_dose_rel": [round(float(mars.budget_dose_ugy_rel.min()), 3),
                                round(float(mars.budget_dose_ugy_rel.max()), 3)],
        },
        "dose_changes_with_g_on_fixed_route": bool(df.dose_ugy.round(6).groupby([df.eta_mode, df.eta]).nunique().max() > 1),
    }
    (args.out_dir / "sensitivity.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
