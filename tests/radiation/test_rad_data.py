"""E12: reading and cleaning the RAD CSVs, and the SEP detection rule."""

import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from radiation.common import posix_seconds  # noqa: E402
from radiation.rad_data import isolated_spikes, load_series, read_csv  # noqa: E402
from radiation.sep_alert import detect  # noqa: E402

HEADER = ("EPOCH_yyyy-mm-ddThh:mm:ss.sssZ,ALIVE_TIME_seconds_(All_Q),TOTAL_DOSE_B_uGray/day_(All_Q),"
          "RTG_CORRECTED_DOSE_B_uGray/day_(All_Q),TOTAL_DOSE_E_uGray/day_(All_Q),TOTAL_DOSE_B_uGray/day_(good_Q),"
          "RTG_CORRECTED_DOSE_B_uGray/day_(good_Q),TOTAL_DOSE_E_uGray/day_(good_Q)")


def write_csv(path, rows, start_sol=4410, start_time="20250101_00:13:37"):
    lines = ["#     GLOBAL ATTRIBUTES", f"#     START_SOL                       {start_sol}",
             f"#     START_TIME                      {start_time}", "#", HEADER]
    lines += rows
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def test_fill_values_become_nan(tmp_path):
    p = tmp_path / "a.csv"
    write_csv(p, ["2025-01-01T00:13:37.000000000Z,933.2,169.4,111.2,148.5,169.4,111.2,148.5",
                  "2025-01-01T00:30:43.000000000Z,933.2,170.0,112.0,149.0,-1.00000E+31,-1.00000E+31,-1.00000E+31"])
    df = read_csv(p)
    assert df["dose_e"].iloc[0] == pytest.approx(148.5)
    assert np.isnan(df["dose_e"].iloc[1]) and np.isnan(df["dose_b_rtg"].iloc[1])
    assert df["dose_e_allq"].iloc[1] == pytest.approx(149.0)     # all-quality column kept as is


def test_unexpected_header_fails(tmp_path):
    p = tmp_path / "a.csv"
    p.write_text("# x\nEPOCH,FOO\n2025-01-01T00:00:00Z,1\n", encoding="utf-8")
    with pytest.raises(ValueError):
        read_csv(p)


def test_sol_from_anchor_is_within_half_a_sol(tmp_path):
    p = tmp_path / "a.csv"
    write_csv(p, ["2025-01-01T00:13:37.000000000Z,933,169,111,148,169,111,148",
                  "2025-01-03T00:13:37.000000000Z,933,169,111,148,169,111,148"])
    df, meta = load_series(tmp_path)
    assert df["sol"].iloc[0] == pytest.approx(4410.5)
    # two Earth days later = 172800 s / 88775.244 s per sol = 1.946 sols
    assert df["sol"].iloc[1] - df["sol"].iloc[0] == pytest.approx(172800 / 88775.244)


def _series(values, start="2025-01-01", step_min=17):
    t = pd.date_range(start, periods=len(values), freq=f"{step_min}min", tz="UTC")
    return pd.Series(np.asarray(values, dtype=float), index=t)


def test_isolated_spike_is_flagged_but_a_storm_is_not():
    vals = np.full(600, 150.0)
    vals[300] = 300.0                      # one high observation: glitch
    vals[450:460] = 300.0                  # ten in a row: storm
    s = _series(vals)
    df = pd.DataFrame({"epoch": s.index, "dose_e": s.to_numpy()})
    mask = isolated_spikes(df)
    assert mask[300] and not mask[450:460].any()


def test_detect_needs_consecutive_observations():
    vals = np.full(600, 150.0)
    vals[300] = 300.0
    vals[450:460] = 300.0
    s = _series(vals)
    events = detect(s, k_on=1.5, n_on=2, k_off=1.2)
    assert len(events) == 1
    e = events[0]
    assert e["onset_utc"] == s.index[450].isoformat()
    assert e["alarm_utc"] == s.index[451].isoformat()
    assert e["end_utc"] == s.index[459].isoformat()
    # excess = 150 uGy/day over 10 observations of 17 min
    assert e["excess_dose_ugy"] == pytest.approx(150 * 10 * 17 / 1440, abs=0.01)
    assert len(detect(s, k_on=1.5, n_on=1)) == 2          # n_on = 1 also fires on the glitch


def test_posix_seconds_ignores_storage_unit():
    t = pd.Series(pd.to_datetime(["1970-01-01T00:00:10Z", "2025-11-11T13:27:42Z"], utc=True))
    assert posix_seconds(t)[0] == pytest.approx(10.0)
    assert posix_seconds(t.astype("datetime64[us, UTC]"))[1] == pytest.approx(
        pd.Timestamp("2025-11-11T13:27:42Z").timestamp())
