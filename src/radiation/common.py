"""Paths and constants shared by the E12 scripts.

Paths reuse src/ml/common.py (same owner), so the raw-data lookup
(MARTIAN_DATA, data/, ../data) works the same way as in E2 and E1.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ml.common import BASE, BOXWORK_SOLS, E2_OUTPUT, PRODUCTS, REPO, crs_wkt, raw_data_dir  # noqa: E402,F401

E12_OUTPUT = PRODUCTS / "e12"

SECONDS_PER_DAY = 86400.0       # RAD rates are per Earth day (CSV header: uGray/day)
SOL_S = 88775.244               # length of a Mars solar day in seconds

# Mean quality factor of the surface GCR field measured by RAD [Hassler2014]:
# 0.21 mGy/day absorbed -> 0.64 mSv/day dose equivalent. Used only to give an
# ESTIMATE in mSv; SEP protons have a lower quality factor, so for storms the
# estimate is an upper bound.
Q_GCR = 3.05

# Nominal dose column (see rad_data.py): tissue-equivalent plastic, detector E.
NOMINAL_COLUMN = "dose_e"


def pixel_coords(inv, x, y):
    """(col, row) in pixel units for map coordinates, given the INVERSE affine transform."""
    import numpy as np
    x, y = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    return inv.a * x + inv.b * y + inv.c, inv.d * x + inv.e * y + inv.f


def posix_seconds(times):
    """UTC datetimes (Series, Index or array) -> float seconds since 1970.

    Does not rely on astype("int64"): pandas may store microseconds, not nanoseconds.
    """
    import pandas as pd
    t = pd.to_datetime(times, utc=True)
    return ((t - pd.Timestamp("1970-01-01", tz="UTC")) / pd.Timedelta(seconds=1)).to_numpy(dtype=float)


def rad_csv_dir():
    """Folder with the 11 CDAWeb dosimetry CSVs (data/README.md, 03_curiosity/radiacion_rad)."""
    return (raw_data_dir() / "03_curiosity" / "radiacion_rad" / "cdaweb_MSL_RAD_OBS-L2"
            / "csv_dosimetria_servicio_cdas")


def rad_rate_csv():
    """Clean per-observation series written by rad_data.py."""
    path = E12_OUTPUT / "rad_dose_rate.csv"
    if not path.exists():
        raise SystemExit("Missing data/e12/rad_dose_rate.csv. Run first:\n"
                         "  python src/radiation/rad_data.py")
    return path
