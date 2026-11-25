"""Candidate science stations for the HUD (to be reviewed by a person, never auto-saved).

Usage (repo root):
    python -m api.candidates
Inputs:  data/base/dem_1m.tif, slope_deg.tif, ortho_color_025.tif (base-grid-v2),
         data/e2/trajectory_poses.geojson (E2),
         data/03_curiosity/places_pds/data_mechanisms/mech_drill.csv (PLACES)
Output:  data/stations/candidates.json

Two groups:
1. Curiosity's own targets (NASA science team choices). Drill sites are found by
   crossing PLACES drill-mechanism activity (site, drive) with the rover poses;
   contacts are the rover position on the sols it crossed them (approximate).
2. Extra ridge/hollow candidates from DEM relief + orthophoto tone, calibrated on
   the drilled ridge/hollow pair: at a 21 m window the drilled ridge is about
   +0.5 m above its surroundings and lighter, the hollow lower and darker. The
   1 m DEM barely resolves the boxwork, so these are suggestions only.
"""

import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from rasterio.enums import Resampling
from rasterio.transform import xy
from scipy.ndimage import uniform_filter

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"

# Curiosity boxwork-campaign targets (names and sols: docs/research/station_value_rubric.md).
DRILLS = {  # (site, drive) where the PLACES drill mechanism moved -> station
    (116, 1944): ("Q1", "curiosity", "Altadena drill (sol 4564): first drill of the boxwork campaign"),
    (119, 1722): ("H0", "hollow", "Valle de la Luna drill (hollow, about sol 4694): siderite-rich, clay-free"),
    (120, 82): ("R0", "ridge", "Nevado Sajama drill (ridge, about sol 4711; re-drilled for SAM TMAH): "
                               "clays + Fe oxides. Also a Curiosity site, counted once as ridge"),
}
CONTACT_SOLS = {
    4534: ("C1", "Approximate: rover position on sol 4534, entry into the boxwork unit "
                 "(Chenapau / Altadena contact)"),
    4848: ("C2", "Approximate: rover position on sol 4848, crossing into the layered sulfate unit"),
}
WINDOW_M = 21                       # relief/tone window, calibrated on the drilled pair
SEARCH = (1290, 1650, 590, 820)     # rows, cols of the visible polygon network (1 m grid)
MIN_SPACING_M = 40
MAX_SLOPE_DEG = 25


def curiosity_targets():
    poses = json.loads((DATA / "e2" / "trajectory_poses.geojson").read_text())["features"]
    drill_rows = csv.DictReader(open(DATA / "03_curiosity" / "places_pds" / "data_mechanisms"
                                     / "mech_drill.csv"))
    active = {(int(r["site"]), int(r["drive"])) for r in drill_rows if r["drill"] != "0"}
    out = []
    for key, (sid, kind, note) in DRILLS.items():
        assert key in active, f"no drill activity at site/drive {key}"
        p = next(f for f in poses if (f["properties"]["site"], f["properties"]["drive"]) == key)
        x, y = p["geometry"]["coordinates"][:2]
        out.append({"id": sid, "type": kind, "x": x, "y": y, "source": "NASA (Curiosity target)",
                    "confidence": "high", "note": note})
    for sol, (sid, note) in CONTACT_SOLS.items():
        p = [f for f in poses if f["properties"]["sol"] == sol][-1]
        x, y = p["geometry"]["coordinates"][:2]
        out.append({"id": sid, "type": "contact", "x": x, "y": y, "source": "NASA (Curiosity traverse)",
                    "confidence": "approximate", "note": note})
    return out


def relief_candidates(n_each=4):
    base = DATA / "base"
    with rasterio.open(base / "dem_1m.tif") as src:
        z = src.read(1).astype(np.float64)
        transform = src.transform
    with rasterio.open(base / "slope_deg.tif") as src:
        slope = src.read(1)
    with rasterio.open(base / "ortho_color_025.tif") as src:
        grey = src.read(out_shape=(3,) + z.shape, resampling=Resampling.average).astype(np.float64).mean(0)

    relief = uniform_filter(z - uniform_filter(z, WINDOW_M, mode="nearest"), 5)
    tone = uniform_filter(grey - uniform_filter(grey, WINDOW_M, mode="nearest"), 5)
    score = (relief - relief.mean()) / relief.std() + (tone - tone.mean()) / tone.std()

    r0, r1, c0, c1 = SEARCH
    ok = np.zeros(z.shape, bool)
    ok[r0:r1, c0:c1] = True
    ok &= slope <= MAX_SLOPE_DEG
    for x, y in [(t["x"], t["y"]) for t in curiosity_targets() if t["type"] in ("ridge", "hollow")]:
        r, c = rasterio.transform.rowcol(transform, x, y)
        ok[r - 25:r + 25, c - 25:c + 25] = False          # keep clear of the drilled pair

    def pick(values, mask):
        values = np.where(mask, values, -np.inf)
        found = []
        while len(found) < n_each and np.isfinite(values.max()):
            r, c = np.unravel_index(np.argmax(values), values.shape)
            found.append((r, c))
            values[max(r - MIN_SPACING_M, 0):r + MIN_SPACING_M,
                   max(c - MIN_SPACING_M, 0):c + MIN_SPACING_M] = -np.inf
        return found

    out = []
    for kind, prefix, values, mask in (
            ("ridge", "R", score, ok & (relief > 0.3) & (tone > 0)),
            ("hollow", "H", -score, ok & (relief < -0.1) & (tone < 0))):
        for i, (r, c) in enumerate(pick(values, mask), 1):
            x, y = xy(transform, r, c)
            # Large relief means a scarp edge or foot rather than a boxwork ridge/hollow.
            big = abs(relief[r, c]) > 1.5
            out.append({"id": f"{prefix}{i}", "type": kind, "x": float(x), "y": float(y),
                        "source": "candidate (DEM relief + ortho tone)",
                        "confidence": "low" if big else "medium",
                        "note": (f"relief {relief[r, c]:+.2f} m, tone {tone[r, c]:+.1f}, slope "
                                 f"{slope[r, c]:.0f} deg" + ("; may be a scarp, check" if big else ""))})
    return out


def main():
    cands = curiosity_targets() + relief_candidates()
    out = DATA / "stations" / "candidates.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"method": __doc__.strip().splitlines()[0], "candidates": cands},
                              indent=2), encoding="utf-8")
    for c in cands:
        print(f"{c['id']:3} {c['type']:9} {c['confidence']:11} {c['note']}")
    print(f"-> {out}")


if __name__ == "__main__":
    main()
