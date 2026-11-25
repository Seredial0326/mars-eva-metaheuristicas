"""Check that every data file the demo needs is in place, and say how to get what is missing.

Usage (repo root):
    python -m api.check_data
Exit code 0 when everything needed is present, 1 otherwise. Optional layers only warn.
"""

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DATA = REPO / "data"

# (folder, files, release, required?, what breaks without it)
RELEASES = [
    ("base", ["dem_1m.tif", "slope_deg.tif", "grid.json", "crs.wkt", "ortho_color_025.tif"],
     "base-grid-v2", True, "everything (grid, costs, planner)"),
    ("tiles", ["tiles.json", "ortho/0/0/0.png", "slope/0/0/0.png"],
     "tiles-v2", True, "the map tiles"),
    ("e2", ["trajectory.geojson"], "e2-trajectory-v1", True, "the fixed test route"),
    ("stations", ["stations_manual.gpkg", "stations_rubric.json"], "stations-v1", False,
     "saved science stations (the HUD can still add them by hand)"),
    ("stations", ["candidates.json"], "stations-candidates-v1", False,
     "the 'Load Curiosity sites' button (Curiosity's drill sites)"),
    ("e9", ["rocas.tif"], "e9-rocks-v1", False, "the Boulders layer (E9)"),
    ("e12", ["sep_alert.json", "rad_summary.json", "route_dose.geojson"], "e12-dose-v1", False,
     "the radiation panel"),
    ("e8", ["sand.tif"], "e8-v0", False, "the sand layer and E1's sand price"),
    ("e1", ["e1_weights.json", "sand_mean_5m.tif"], "e1-sand-v1", False,
     "the human cost (without it /plan uses E3 alone)"),
    ("rems", ["rems_weather_msl.json"], "rems-v1", False,
     "the surface weather panel (REMS); the downloaded kit's 03_curiosity/clima_rems also works"),
    ("minerals", ["gale_minerals.geojson"], "minerals-v1", False,
     "the regional minerals panel (CRISM/OMEGA); or build it: python -m api.minerals build"),
    ("thermal", ["THEMIS_NightIR_ControlledMosaics_100m_v2_oct2018__z9_row269_col902.png"], "themis-v1", False,
     "the THEMIS night thermal layer; the Mars Trek kit's test tile also works"),
    ("tiles/3d/photos", ["catalog.json"], "rover-photos-v1", False,
     "the 383 Curiosity photos in the 3D view"),
    ("tiles/3d", ["."], "generated", False,
     "the 3D view (run once: python src/viz3d/build_terrain_assets.py)"),
]


def download_hint(folder, release):
    if release == "generated":
        return "python src/viz3d/build_terrain_assets.py"
    zip_name = release.replace("-", "_") + ".zip"
    if release in ("stations-v1", "stations-candidates-v1"):
        return f"gh release download {release} --dir data/{folder}"
    return (f"gh release download {release} --dir data   then unzip data/{zip_name} "
            f"into data/{folder}  (PowerShell: Expand-Archive data\\{zip_name} data\\{folder} -Force)")


def main():
    missing_required = False
    for folder, files, release, required, impact in RELEASES:
        absent = [f for f in files if not (DATA / folder / f).exists()]
        if not absent:
            print(f"  ok       data/{folder}/  ({release})")
            continue
        tag = "MISSING " if required else "optional"
        print(f"  {tag} data/{folder}/  ({release}) -> without it: {impact}")
        print(f"           missing: {', '.join(absent)}")
        print(f"           get it:  {download_hint(folder, release)}")
        missing_required |= required
    print("\nAll required data present." if not missing_required
          else "\nSome required data is missing: the demo will not start correctly.")
    return 1 if missing_required else 0


if __name__ == "__main__":
    sys.exit(main())
