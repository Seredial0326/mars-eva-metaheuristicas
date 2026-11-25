"""Which data types the planner combines, from which instruments and missions (P4, #44).

The challenge asks for at least three data types combined. This list is the HUD's
"N data types from M missions" panel. A source only counts when its file is on disk
and the product uses it; planned sources are listed apart, never counted.
"""

from pathlib import Path

from . import thermal, weather

# (data type, instrument, mission(s) joined by " / ", what the product does with it,
#  path under data/, or a function data_dir -> path for sources with two homes)
SOURCES = [
    ("Orbital image", "HiRISE orthophoto, 25 cm", "Mars Reconnaissance Orbiter",
     "base map; sand found by E8's U-Net and boulders by E9 (BoulderNet)", "base/ortho_color_025.tif"),
    ("Elevation", "HiRISE stereo DEM, 1 m", "Mars Reconnaissance Orbiter",
     "slope, E3 walking cost, walkback, 3D view", "base/dem_1m.tif"),
    ("Rover traverse", "Curiosity localization (PLACES)", "Mars Science Laboratory",
     "E1 learns a terrain price from the route; test route", "e2/trajectory.geojson"),
    ("Radiation", "RAD dosimetry", "Mars Science Laboratory",
     "EVA dose budget and solar storm alert (E12)", "e12/rad_summary.json"),
    ("Surface weather", "REMS", "Mars Science Laboratory",
     "temperature, UV and daylight of the EVA's sol", weather.find_feed),
    ("Spectral (minerals)", "CRISM / OMEGA detections", "Mars Reconnaissance Orbiter / Mars Express",
     "regional context: hydrous minerals and clays 16-50 km from the box", "minerals/gale_minerals.geojson"),
    ("Thermal", "THEMIS night IR, ~81 m", "Mars Odyssey",
     "context layer; checked against E8's sand (no relation at 81 m)", thermal.find),
]

PLANNED = [
    ("Chemistry", "ChemCam / APXS at the drill sites", "Mars Science Laboratory"),
]


def summary(data_dir):
    data_dir = Path(data_dir)
    used, missing = [], []
    for kind, instrument, mission, use, rel in SOURCES:
        path = rel(data_dir) if callable(rel) else data_dir / rel
        row = {"type": kind, "instrument": instrument, "mission": mission, "use": use}
        (used if path is not None and Path(path).exists() else missing).append(row)
    missions = sorted({m for r in used for m in r["mission"].split(" / ")})
    return {
        "n_types": len({r["type"] for r in used}), "n_missions": len(missions),
        "missions": missions, "sources": used, "missing": missing,
        "planned": [{"type": k, "instrument": i, "mission": m} for k, i, m in PLANNED],
    }
