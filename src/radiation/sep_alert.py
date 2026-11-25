"""E12 - Solar particle event (SEP) alert: detection rule, return time, replay.

Why an alert and not a dose map: the background (galactic cosmic rays) hardly
depends on where the astronaut stands, and habitat walls stop it poorly. SEP
protons are softer, so a shelter does stop them: the useful decision is "go back
now", and its cost depends on where you are, through the time to get back.

1. Detection rule on the RAD series (detector E, good quality, spikes kept: the
   rule itself must reject them). Baseline = trailing median over BASELINE_WINDOW,
   past observations only. Alarm when the rate is > k_on x baseline for n_on
   consecutive observations; the event ends after n_on observations < k_off x.
   A threshold sweep reports alarms and delays for each (k_on, n_on).
2. Return time to the HABITAT, a user input (return_time.py): fastest walk back
   (time, not energy: dose is rate x time) from E4's rv_time_s.tif, or E12's
   provisional fallback with the same recipe until E4 delivers it.
3. Replay: the EVA (an E5 tour with --no-out-and-back; by default the old
   provisional route, Curiosity's traverse out and back) placed so the
   real alarm of the strongest event arrives when the astronaut is farthest from
   the habitat, and at 25 % / 75 % of the EVA time. Compares "ignore the alarm"
   (finish the plan) with "return now" (fastest walk back), counting only the dose
   received outside, for the real storm and for storms scaled x10 and x50
   (hypothetical: only the excess over the baseline is scaled).

Usage:
    python src/radiation/sep_alert.py --habitat X Y [--route data/e5/tour_nominal.gpkg]
        [--no-out-and-back] [--return-raster data/e4/rv_time_s.tif] [--out-dir DIR]
Writes data/e12/sep_alert.json and sep_thresholds.csv (and the fallback return-time
raster if no E4 raster is given).
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radiation.common import (BASE, E2_OUTPUT, E12_OUTPUT, NOMINAL_COLUMN, Q_GCR,  # noqa: E402
                              SECONDS_PER_DAY, posix_seconds, rad_rate_csv)
from radiation.return_time import resolve_habitat, return_time_for  # noqa: E402
from radiation.route_dose import (DoseRate, background_rate, load_route, out_and_back,  # noqa: E402
                                  repo_relative, route_timeline)

K_ON, N_ON, K_OFF = 1.5, 2, 1.2
BASELINE_WINDOW = "3D"
SWEEP_K = [1.2, 1.3, 1.5, 2.0]
SWEEP_N = [1, 2, 3]
STORM_SCALES = [1, 10, 50]
ALARM_FRACTIONS = [0.25, 0.75]
COLUMN = NOMINAL_COLUMN + "_ugy_day"


# ------------------------------------------------------------------- detection

def load_rates(csv_path=None):
    df = pd.read_csv(csv_path or rad_rate_csv())
    df = df[df["quality_ok"].astype(bool)].copy()
    df["utc"] = pd.to_datetime(df["utc"], utc=True)
    return df.set_index("utc")[COLUMN]


def baseline(rates, window=BASELINE_WINDOW):
    """Trailing median of PAST observations (the current one is excluded)."""
    return rates.rolling(window, min_periods=10).median().shift(1)


def detect(rates, k_on=K_ON, n_on=N_ON, k_off=K_OFF, window=BASELINE_WINDOW):
    """Events found by the rule, as a list of dicts (times in UTC ISO)."""
    base = baseline(rates, window)
    ratio = (rates / base).to_numpy()
    t = rates.index
    r = rates.to_numpy()
    b = base.to_numpy()
    events, i, n = [], 0, len(r)
    while i < n:
        if not (np.isfinite(ratio[i]) and ratio[i] > k_on):
            i += 1
            continue
        j = i
        while j < n and np.isfinite(ratio[j]) and ratio[j] > k_on:
            j += 1
        if j - i < n_on:                      # too short: glitch, not an event
            i = j
            continue
        onset, alarm = i, i + n_on - 1
        base0 = b[onset]                      # baseline frozen at the onset
        k, calm = j, 0                        # event goes on until n_on calm observations
        while k < n and calm < n_on:
            calm = calm + 1 if r[k] < k_off * base0 else 0
            k += 1
        end = max(k - calm - 1, j - 1)
        sl = slice(onset, end + 1)
        dt_days = np.diff(posix_seconds(t[onset:end + 2])) / SECONDS_PER_DAY
        excess = np.clip(r[sl] - base0, 0, None)[:len(dt_days)]
        events.append({
            "onset_utc": t[onset].isoformat(), "alarm_utc": t[alarm].isoformat(), "end_utc": t[end].isoformat(),
            "alarm_delay_min": round((t[alarm] - t[onset]).total_seconds() / 60, 1),
            "duration_h": round((t[end] - t[onset]).total_seconds() / 3600, 2),
            "baseline_ugy_day": round(float(base0), 2), "peak_ugy_day": round(float(r[sl].max()), 2),
            "peak_ratio": round(float(r[sl].max() / base0), 3),
            "excess_dose_ugy": round(float((excess * dt_days).sum()), 2),
            "observations_above_k_on": int(j - i),
        })
        i = end + 1
    return events


def threshold_sweep(rates, reference_onset):
    """Alarms per (k_on, n_on) and whether the reference event is caught."""
    rows = []
    ref = pd.Timestamp(reference_onset)
    for k in SWEEP_K:
        for n in SWEEP_N:
            ev = detect(rates, k, n)
            hit = [e for e in ev if abs(pd.Timestamp(e["onset_utc"]) - ref) < pd.Timedelta("12h")]
            rows.append({"k_on": k, "n_on": n, "alarms": len(ev), "catches_reference": bool(hit),
                         "alarm_delay_min": hit[0]["alarm_delay_min"] if hit else None,
                         "other_alarms": len(ev) - len(hit)})
    return pd.DataFrame(rows)


# ---------------------------------------------------------------------- replay

def scaled_series(rate, event, scale):
    """Copy of a DoseRate where the excess over the event baseline is x scale."""
    t0 = pd.Timestamp(event["onset_utc"]).timestamp()
    t1 = pd.Timestamp(event["end_utc"]).timestamp()
    b = event["baseline_ugy_day"]
    r = rate.rate.copy()
    inside = (rate.t_s >= t0) & (rate.t_s <= t1)
    r[inside] = b + scale * np.clip(r[inside] - b, 0, None)
    return DoseRate(rate.t_s, r, f"{rate.label}, event excess x{scale}")


def alarm_positions(tl):
    """Where on the EVA the alarm is replayed: farthest point and 25 % / 75 % of the time."""
    t = tl["t_s"].to_numpy()
    pos = {"farthest": int(np.nanargmax(tl["return_s"].to_numpy()))}
    for f in ALARM_FRACTIONS:
        pos[f"{int(f * 100)}pct_of_eva"] = int(np.searchsorted(t, f * t[-1]))
    return pos


def replay(tl, rate, event, i_far):
    """'Ignore the alarm' against 'return now' for one event and one timeline.

    The EVA starts so that the alarm arrives when the astronaut is at point i_far.
    "Ignore" finishes the planned EVA; "return now" takes the fastest walk back to
    the habitat (return_s, from the R_T raster). Only the dose received outside is
    counted. return_route_h (walking back along the route) is reported for context.
    """
    alarm = pd.Timestamp(event["alarm_utc"]).timestamp()
    start = alarm - float(tl["t_s"].iloc[i_far])
    end = start + float(tl["t_s"].iloc[-1])
    t_ret = float(tl["return_s"].iloc[i_far])
    if not np.isfinite(t_ret):
        raise SystemExit(f"route point {i_far} cannot reach the habitat on the E3 graph")
    out = {"eva_start_utc": pd.Timestamp(start, unit="s", tz="UTC").isoformat(),
           "alarm_point_index": i_far, "alarm_point_dist_m": round(float(tl["dist_m"].iloc[i_far]), 1),
           "return_fastest_h": round(t_ret / 3600, 3),
           "return_route_h": round(float(tl["return_route_s"].iloc[i_far]) / 3600, 3),
           "remaining_plan_h": round((end - alarm) / 3600, 3), "scales": []}
    for s in STORM_SCALES:
        r = scaled_series(rate, event, s) if s != 1 else rate
        before = float(r.dose_between(start, alarm))
        ignore = float(r.dose_between(start, end))
        back = before + float(r.dose_between(alarm, alarm + t_ret))
        out["scales"].append({"scale": s, "dose_ignore_ugy": round(ignore, 2), "dose_return_ugy": round(back, 2),
                              "dose_saved_ugy": round(ignore - back, 2),
                              "dose_saved_usv_upper_est": round((ignore - back) * Q_GCR, 1),
                              "peak_rate_ugy_h": round((event["baseline_ugy_day"] + s * (
                                  event["peak_ugy_day"] - event["baseline_ugy_day"])) / 24, 2)})
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--route", default=str(E2_OUTPUT / "trajectory.geojson"))
    ap.add_argument("--habitat", nargs=2, type=float, metavar=("X", "Y"),
                    help="habitat in DEM metres (the same input E4 uses); else taken from the route file")
    ap.add_argument("--return-raster", help="E4's rv_time_s.tif (R(v) in seconds for the same habitat)")
    ap.add_argument("--no-out-and-back", action="store_true",
                    help="use the route as given (it should already end at the habitat)")
    ap.add_argument("--dem", default=str(BASE / "dem_1m.tif"))
    ap.add_argument("--slope", default=str(BASE / "slope_deg.tif"))
    ap.add_argument("--out-dir", type=Path, default=E12_OUTPUT)
    args = ap.parse_args()
    args.out_dir.mkdir(parents=True, exist_ok=True)

    # 1. detection
    rates = load_rates()
    events = detect(rates)
    strongest = max(events, key=lambda e: e["excess_dose_ugy"]) if events else None
    sweep = threshold_sweep(rates, strongest["onset_utc"]) if strongest else pd.DataFrame()
    sweep.to_csv(args.out_dir / "sep_thresholds.csv", index=False)

    # 2. return time to the habitat (user input; E4 raster or E12 fallback)
    habitat_xy, habitat_source = resolve_habitat(args.habitat, args.route)
    ret_path, ret_info = return_time_for(habitat_xy, args.return_raster, args.dem, args.slope)
    xy, stations = load_route(args.route)
    if not args.no_out_and_back:
        xy = out_and_back(xy)

    # 3. replay on the EVA
    replays = None
    if strongest:
        tl = route_timeline(xy, args.dem, DoseRate.constant(background_rate()), stations=stations,
                            return_raster=ret_path)
        series = DoseRate.series()
        replays = {name: replay(tl, series, strongest, i) for name, i in alarm_positions(tl).items()}
        replays["eva_time_h"] = round(float(tl["t_s"].iloc[-1]) / 3600, 3)
        replays["step_method"] = tl.attrs.get("method")
        far = tl["return_route_s"].to_numpy() > 60        # skip the points next to the habitat
        replays["return_fastest_vs_route_median"] = round(float(np.nanmedian(
            tl["return_s"].to_numpy()[far] / tl["return_route_s"].to_numpy()[far])), 3)

    summary = {
        "rule": {"column": COLUMN, "k_on": K_ON, "n_on": N_ON, "k_off": K_OFF, "baseline": BASELINE_WINDOW
                 + " trailing median of past observations"},
        "series_utc": [rates.index.min().isoformat(), rates.index.max().isoformat()],
        "events": events,
        "strongest_event": strongest,
        "threshold_sweep": sweep.to_dict(orient="records"),
        "habitat": {"xy": [round(habitat_xy[0], 3), round(habitat_xy[1], 3)], "source": habitat_source},
        "return_time_map": ret_info,
        "replay": replays,
        "route": repo_relative(args.route), "out_and_back": not args.no_out_and_back,
        "notes": ["only the dose received outside is counted; the habitat dose is not modelled",
                  "the x10 and x50 storms are hypothetical (excess over the baseline scaled)",
                  "dose_saved_usv_upper_est uses the GCR quality factor; SEP protons have a lower one"],
    }
    (args.out_dir / "sep_alert.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps({k: summary[k] for k in ["events", "return_time_map", "replay"]}, indent=2))
    print(sweep.to_string(index=False))


if __name__ == "__main__":
    main()
