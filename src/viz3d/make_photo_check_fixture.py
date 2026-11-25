"""Write tests/viz3d/fixtures/rover_photo_real_checks.json from the raw data.

A real Navcam stereo pair (sol 4711) with its PLACES rows, and 20 real drives inside the
box, for physical checks of the photo geometry (stereo baseline, mast height, drive
direction). Run from the repository root, with <raw> the full data folder:

    python src/viz3d/make_photo_check_fixture.py . <raw>/03_curiosity tests/viz3d/fixtures/rover_photo_real_checks.json
"""
import csv
import json
import math
import sys
from pathlib import Path

repo, raw, out = (Path(p) for p in sys.argv[1:4])
sys.path.insert(0, str(repo))
from src.viz3d.build_rover_photos import load_places, resolve_place, in_bbox  # noqa: E402

KEEP = ("id", "imageid", "instrument", "is_thumbnail", "camera_model_type", "subframe_rect",
        "scale_factor", "attitude", "camera_model_component_list", "camera_vector", "site",
        "drive", "sol", "spacecraft_clock", "date_taken", "image_credit", "https_url")
grid = json.loads((repo / "docs/contracts/grid.json").read_text(encoding="utf-8"))
bbox = grid["bbox"]
places, _ = load_places(raw / "places_pds/data_localizations/localized_interp.csv")

full = {}
for page in sorted((raw / "imagenes_crudas/indice_soles_4450_4848").glob("page_*.json")):
    for item in json.loads(page.read_text(encoding="utf-8"))["items"]:
        if item.get("sol") != 4711 or item.get("is_thumbnail") is not False:
            continue
        if not str(item.get("instrument", "")).startswith("NAV_"):
            continue
        if (item.get("extended") or {}).get("sample_type") != "full":
            continue
        full[item["imageid"]] = item

pairs = []
for image_id, left in sorted(full.items()):
    if image_id.startswith("NLB_") and "NRB_" + image_id[4:] in full:
        pairs.append((left, full["NRB_" + image_id[4:]]))
print("pairs on sol 4711:", len(pairs))
left, right = pairs[0]
samples = []
for item in (left, right):
    row, _ = resolve_place(item, places[(int(item["site"]), int(item["drive"]))])
    trimmed = {k: item[k] for k in KEEP}
    trimmed["extended"] = {k: item["extended"][k] for k in ("sample_type", "mast_az", "mast_el", "lmst")}
    samples.append({"item": trimmed, "places_row": row})

with (raw / "places_pds/data_localizations/localized_interp.csv").open(encoding="utf-8-sig", newline="") as f:
    rows = [r for r in csv.DictReader(f) if r["frame"] == "ROVER"]
rows = [r for r in rows if in_bbox(float(r["easting"]), float(r["northing"]), bbox)]
rows.sort(key=lambda r: (int(r["site"]), int(r["drive"]), int(r["pose"])))
latest = {}
for r in rows:
    latest[(int(r["site"]), int(r["drive"]))] = r          # highest pose per site/drive
keys = sorted(latest)
hops = []
for a, b in zip(keys, keys[1:]):
    if a[0] != b[0]:
        continue
    ra, rb = latest[a], latest[b]
    d = math.dist([float(ra["easting"]), float(ra["northing"])], [float(rb["easting"]), float(rb["northing"])])
    if 1 <= d <= 30:
        hops.append([{k: r[k] for k in ("site", "drive", "pose", "easting", "northing", "elevation",
                                       "quat_s", "quat_v1", "quat_v2", "quat_v3", "sol")} for r in (ra, rb)])
    if len(hops) == 20:
        break
print("hops:", len(hops))
fixture = {
    "provenance": {
        "metadata": "NASA/JPL-Caltech MSL raw-image API index downloaded 2026-11-13 (sol 4711, first "
                    "full-frame NLB/NRB pair by image id; fields trimmed to those the geometry uses)",
        "places": "localized_interp.csv, NASA/JPL PDS Imaging Node; image rows joined by "
                  "src/viz3d/build_rover_photos.resolve_place; drive hops are the first 20 consecutive "
                  "same-site drives inside the box, 1-30 m apart, highest pose of each drive",
    },
    "stereo_pair": samples,
    "drive_hops": hops,
}
out.write_text(json.dumps(fixture, indent=1) + "\n", encoding="utf-8")
print("wrote", out, out.stat().st_size, "bytes")
