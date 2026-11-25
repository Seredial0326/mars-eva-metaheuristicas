"""E12 - Read and clean the RAD dose-rate series (CDAWeb MSL_RAD_OBS-L2 CSVs).

Input: the server-generated CSVs in
    <raw data>/03_curiosity/radiacion_rad/cdaweb_MSL_RAD_OBS-L2/csv_dosimetria_servicio_cdas/
Each file starts with ~124 comment lines (#), then one header line and one row
per RAD observation (nominal cadence 16 min, 8 min at high count rates).

Units: absorbed dose RATE in micro-gray per Earth day, as the CSV header says
(`uGray/day`). The PDS label of the same field says microGray/hour; per day is the
only reading consistent with the published surface rate [Hassler2014]
(0.21 mGy/day; per hour would give about 3.7 mGy/day, 18 times too high).

Columns kept (the good-quality versions; flagged rows carry the CDF fill -1e31):
    dose_e      tissue-equivalent plastic, detector E. NOT corrected for the
                rover's MMRTG (radioisotope power source) background.
    dose_b      silicon, detector B, raw.
    dose_b_rtg  silicon, detector B, corrected for the MMRTG contribution.
Nominal for the astronaut: dose_e. It is the closest to human tissue, and it is
conservative because it still contains the MMRTG background.

Usage:
    python src/radiation/rad_data.py [--csv-dir DIR] [--out-dir data/e12]
Writes rad_dose_rate.csv (one row per observation) and rad_summary.json.
"""
import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from radiation.common import (BOXWORK_SOLS, E12_OUTPUT, NOMINAL_COLUMN, Q_GCR,  # noqa: E402
                              SOL_S, rad_csv_dir)

FILL_BELOW = -1e30          # CDF fill value is -1e31
# Columns of the CDAWeb listing, in file order. The header text is checked
# against these fragments so a change of layout fails loudly.
RAW_COLUMNS = [
    ("epoch", "EPOCH"),
    ("alive_s", "ALIVE_TIME"),
    ("dose_b_allq", "TOTAL_DOSE_B_uGray/day_(All_Q)"),
    ("dose_b_rtg_allq", "RTG_CORRECTED_DOSE_B_uGray/day_(All_Q)"),
    ("dose_e_allq", "TOTAL_DOSE_E_uGray/day_(All_Q)"),
    ("dose_b", "TOTAL_DOSE_B_uGray/day_(good_Q)"),
    ("dose_b_rtg", "RTG_CORRECTED_DOSE_B_uGray/day_(good_Q)"),
    ("dose_e", "TOTAL_DOSE_E_uGray/day_(good_Q)"),
]
DOSE_COLUMNS = ["dose_e", "dose_b", "dose_b_rtg"]

# Isolated spike: one observation far above its neighbours (a detector glitch,
# not a solar event). Used only to count them; the SEP alert (sep_alert.py)
# rejects them by asking for several consecutive high observations.
SPIKE_RATIO = 1.5
NEIGHBOUR_RATIO = 1.2
BASELINE_WINDOW = "3D"


def read_sol_anchor(path):
    """(START_SOL, START_TIME) from the comment block of one CDAWeb CSV."""
    sol = start = None
    with open(path, encoding="utf-8", errors="replace") as f:
        for line in f:
            if not line.startswith("#"):
                break
            m = re.match(r"#\s+START_SOL\s+(\d+)", line)
            if m:
                sol = int(m.group(1))
            m = re.match(r"#\s+START_TIME\s+(\d{8}_\d{2}:\d{2}:\d{2})", line)
            if m:
                start = pd.Timestamp(pd.to_datetime(m.group(1), format="%Y%m%d_%H:%M:%S"), tz="UTC")
    if sol is None or start is None:
        raise ValueError(f"{path}: START_SOL / START_TIME not found in the comment block")
    return sol, start


def read_csv(path):
    """One CDAWeb CSV -> DataFrame with RAW_COLUMNS names; fill values -> NaN."""
    df = pd.read_csv(path, comment="#")
    header = [c.strip() for c in df.columns]
    if len(header) != len(RAW_COLUMNS) or any(frag not in h for (_, frag), h in zip(RAW_COLUMNS, header)):
        raise ValueError(f"{path}: unexpected header {header}")
    df.columns = [name for name, _ in RAW_COLUMNS]
    df["epoch"] = pd.to_datetime(df["epoch"], utc=True)
    for c in df.columns[1:]:
        df[c] = df[c].astype(float).where(df[c] > FILL_BELOW)
    return df


def sol_of(epochs, anchors):
    """Approximate MSL sol (float) for each epoch from the files' START_SOL anchors.

    Each anchor says the first observation of a file falls in sol START_SOL, but not
    where inside that sol; adding 0.5 puts it in the middle, so the result is good to
    about +/-0.5 sol. Returns (sol_float array, spread of the anchors in sols).
    """
    ref = anchors[0][1]
    zero = np.array([s + 0.5 - (t - ref).total_seconds() / SOL_S for s, t in anchors])
    elapsed = (epochs - ref).dt.total_seconds().to_numpy() / SOL_S
    return zero.mean() + elapsed, float(zero.max() - zero.min())


def load_series(csv_dir):
    """All CSVs of a folder -> one clean, time-sorted DataFrame (plus sol)."""
    paths = sorted(Path(csv_dir).glob("*.csv"))
    if not paths:
        raise SystemExit(f"No CSV files in {csv_dir}")
    df = pd.concat([read_csv(p) for p in paths], ignore_index=True)
    df = df.sort_values("epoch").drop_duplicates("epoch").reset_index(drop=True)
    anchors = [read_sol_anchor(p) for p in paths]
    df["sol"], spread = sol_of(df["epoch"], anchors)
    df["quality_ok"] = df[DOSE_COLUMNS].notna().all(axis=1)
    return df, {"files": [p.name for p in paths], "sol_anchor_spread": spread}


def isolated_spikes(df, column=NOMINAL_COLUMN):
    """Boolean mask: observation > SPIKE_RATIO x trailing median, neighbours not."""
    s = df.set_index("epoch")[column].dropna()
    base = s.rolling(BASELINE_WINDOW, min_periods=10).median()
    ratio = s / base
    prev_r, next_r = ratio.shift(1), ratio.shift(-1)
    mask = (ratio > SPIKE_RATIO) & (prev_r < NEIGHBOUR_RATIO) & (next_r < NEIGHBOUR_RATIO)
    return mask.reindex(df["epoch"]).fillna(False).to_numpy()


def daily_stats(df, column):
    daily = df.set_index("epoch")[column].resample("D").mean().dropna()
    return daily


def describe(values):
    v = np.asarray(values, dtype=float)
    v = v[np.isfinite(v)]
    return {"n": int(v.size), "mean": round(float(v.mean()), 2), "median": round(float(np.median(v)), 2),
            "p05": round(float(np.percentile(v, 5)), 2), "p95": round(float(np.percentile(v, 95)), 2),
            "min": round(float(v.min()), 2), "max": round(float(v.max()), 2)}


def summarise(df, meta):
    good = df[df["quality_ok"]]
    in_box = good[(good["sol"] >= BOXWORK_SOLS[0]) & (good["sol"] < BOXWORK_SOLS[1] + 1)]
    gaps = df["epoch"].diff().dt.total_seconds().dropna()
    within_day_cv = (good.set_index("epoch")[NOMINAL_COLUMN].resample("D").std()
                     / good.set_index("epoch")[NOMINAL_COLUMN].resample("D").mean()).dropna()
    monthly = good.set_index("epoch")[DOSE_COLUMNS].resample("MS").median().round(1)
    spikes = df.loc[df["spike"], ["epoch", NOMINAL_COLUMN]]
    nominal_box = float(in_box[NOMINAL_COLUMN].median())
    return {
        "source": "CDAWeb MSL_RAD_OBS-L2 dosimetry listing (data/03_curiosity/radiacion_rad)",
        "files": meta["files"],
        "units": "absorbed dose rate, micro-gray per Earth day (uGy/day)",
        "observations": int(len(df)),
        "observations_quality_ok": int(df["quality_ok"].sum()),
        "observations_flagged_fill": int((~df["quality_ok"]).sum()),
        "first_utc": df["epoch"].min().isoformat(),
        "last_utc": df["epoch"].max().isoformat(),
        "sol_range_approx": [round(float(df["sol"].min()), 1), round(float(df["sol"].max()), 1)],
        "sol_anchor_spread_sols": round(meta["sol_anchor_spread"], 3),
        "cadence_s": {"median": float(gaps.median()), "p99": float(gaps.quantile(0.99)),
                      "max": float(gaps.max())},
        "boxwork_sols": list(BOXWORK_SOLS),
        "boxwork_utc": [in_box["epoch"].min().isoformat(), in_box["epoch"].max().isoformat()],
        "boxwork_observation_stats": {c: describe(in_box[c]) for c in DOSE_COLUMNS},
        "boxwork_daily_mean_stats": {c: describe(daily_stats(in_box, c)) for c in DOSE_COLUMNS},
        "whole_series_daily_mean_stats": {c: describe(daily_stats(good, c)) for c in DOSE_COLUMNS},
        "within_day_cv_median": round(float(within_day_cv.median()), 4),
        "nominal": {
            "column": NOMINAL_COLUMN,
            "background_ugy_per_day": round(nominal_box, 2),
            "background_ugy_per_hour": round(nominal_box / 24.0, 3),
            "quality_factor_estimate": Q_GCR,
            "background_usv_per_day_estimate": round(nominal_box * Q_GCR, 1),
            "why": "median of the good-quality detector-E observations over the boxwork sols",
        },
        "unit_check": {
            "hassler2014_ugy_per_day": 210.0,
            "ratio_series_median_to_hassler": round(float(good[NOMINAL_COLUMN].median()) / 210.0, 3),
            "ratio_if_column_were_per_hour": round(float(good[NOMINAL_COLUMN].median()) * 24 / 210.0, 1),
        },
        "mmrtg_share_of_b": round(float(1 - good["dose_b_rtg"].median() / good["dose_b"].median()), 3),
        "isolated_spikes": {
            "rule": f"> {SPIKE_RATIO} x trailing {BASELINE_WINDOW} median, both neighbours < {NEIGHBOUR_RATIO} x",
            "count": int(len(spikes)),
            "examples": [{"utc": t.isoformat(), NOMINAL_COLUMN: round(float(v), 1)}
                         for t, v in spikes.head(10).itertuples(index=False)],
        },
        "monthly_median": {t.strftime("%Y-%m"): row.to_dict() for t, row in monthly.iterrows()},
    }


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--csv-dir", type=Path, default=None, help="folder with the CDAWeb CSVs")
    ap.add_argument("--out-dir", type=Path, default=E12_OUTPUT)
    args = ap.parse_args()

    csv_dir = args.csv_dir or rad_csv_dir()
    df, meta = load_series(csv_dir)
    df["spike"] = isolated_spikes(df)
    args.out_dir.mkdir(parents=True, exist_ok=True)

    out = df[["epoch", "sol", "alive_s", "dose_e", "dose_b", "dose_b_rtg", "quality_ok", "spike"]].copy()
    out["epoch"] = out["epoch"].dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    out = out.rename(columns={"epoch": "utc", "dose_e": "dose_e_ugy_day", "dose_b": "dose_b_ugy_day",
                              "dose_b_rtg": "dose_b_rtg_ugy_day"})
    out.to_csv(args.out_dir / "rad_dose_rate.csv", index=False, float_format="%.3f")

    summary = summarise(df, meta)
    (args.out_dir / "rad_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    nom = summary["nominal"]
    print(f"{summary['observations']} observations ({summary['observations_flagged_fill']} flagged), "
          f"{summary['first_utc'][:10]} .. {summary['last_utc'][:10]}")
    print(f"boxwork background ({NOMINAL_COLUMN}): {nom['background_ugy_per_day']} uGy/day "
          f"= {nom['background_ugy_per_hour']} uGy/h; isolated spikes: {summary['isolated_spikes']['count']}")
    print(f"wrote {args.out_dir / 'rad_dose_rate.csv'} and rad_summary.json")


if __name__ == "__main__":
    main()
