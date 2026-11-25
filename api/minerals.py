"""Regional mineral detections around the box from orbit (P4, issue #44).

Two NASA Mars Trek point layers (downloaded in data/04_mars_trek/arcgis_servicios/):
  - "Aqueous Mineral Distribution": class phyllosilicate, sulfate, silica, chloride or
    carbonate (a global compilation; the layer names neither author nor instrument).
  - "Hydrous Mineral Detections OMEGA/CRISM": hydrous minerals, instrument OMEGA (Mars
    Express) or CRISM (MRO), no mineral class.
They are global compilations with coordinates rounded to 0.01-0.1 deg (about 0.6-6 km),
and many points are repeated. None falls inside the 2 x 2 km box, so this is regional
context for the scientific value of the area, never a per-cell layer or a station score.

Build once from the kit (writes data/minerals/gale_minerals.geojson, release minerals-v1):
    python -m api.minerals build
"""

import json
import math
import sys
from pathlib import Path

R_MARS = 3_396_190.0
# Box centre in the DEM's equirectangular metres (base/grid.json), lon = x / R, lat = y / R.
BOX_CENTRE_XY = (8143537.492786024, -284463.075189438)
KEEP_RADIUS_KM = 300.0
# Gale crater for orientation on the HUD's inset map: about 154 km across, centre near
# 5.4 S 137.8 E (approximate; drawn as a circle).
GALE_CENTRE_LONLAT = (137.8, -5.4)
GALE_RADIUS_KM = 77.0
CLASSES = ["phyllosilicate", "sulfate", "silica", "chloride", "carbonate", "hydrous"]
KIT = ("04_mars_trek", "arcgis_servicios")
FILE = ("minerals", "gale_minerals.geojson")


def box_centre_lonlat():
    x, y = BOX_CENTRE_XY
    return math.degrees(x / R_MARS), math.degrees(y / R_MARS)


def distance_bearing(lon0, lat0, lon, lat):
    """Great-circle distance (km) and initial bearing (deg from north) on the sphere."""
    p1, p2, dl = math.radians(lat0), math.radians(lat), math.radians(lon - lon0)
    c = math.sin(p1) * math.sin(p2) + math.cos(p1) * math.cos(p2) * math.cos(dl)
    d = R_MARS * math.acos(max(-1.0, min(1.0, c))) / 1000.0
    b = math.degrees(math.atan2(math.sin(dl) * math.cos(p2),
                                math.cos(p1) * math.sin(p2) - math.sin(p1) * math.cos(p2) * math.cos(dl)))
    return d, b % 360.0


def build(data_dir):
    """Deduplicated detections within KEEP_RADIUS_KM of the box, as one GeoJSON."""
    data_dir = Path(data_dir)
    src = data_dir.joinpath(*KIT)
    lon0, lat0 = box_centre_lonlat()
    seen, feats = set(), []
    layers = [("Aquieous_Mineral_Distribution_Options_clon0__features_*.geojson", "Aqueous Mineral Distribution"),
              ("Hydrous_Mineral_Detections_OMEGA_CRISM_clon0__features_*.geojson", "Hydrous Mineral Detections OMEGA/CRISM")]
    for pattern, layer in layers:
        files = sorted(src.glob(pattern))
        if not files:
            raise FileNotFoundError(f"{src / pattern}: download the Mars Trek kit (data/README.md)")
        for f in files:
            for ft in json.loads(f.read_text(encoding="utf-8"))["features"]:
                if not ft.get("geometry"):
                    continue
                lon, lat = (float(v) for v in ft["geometry"]["coordinates"][:2])
                pr = ft["properties"]
                cls = pr.get("Class") or "hydrous"
                instrument = pr.get("Instrument") or "orbital"   # the aqueous layer names no instrument
                key = (round(lon, 3), round(lat, 3), cls, instrument)
                if key in seen:
                    continue
                seen.add(key)
                d, b = distance_bearing(lon0, lat0, lon, lat)
                if d > KEEP_RADIUS_KM:
                    continue
                feats.append({"type": "Feature", "geometry": {"type": "Point", "coordinates": [lon, lat]},
                              "properties": {"class": cls, "instrument": instrument, "layer": layer,
                                             "distance_km": round(d, 2), "bearing_deg": round(b, 1)}})
    feats.sort(key=lambda f: f["properties"]["distance_km"])
    out = data_dir.joinpath(*FILE)
    out.parent.mkdir(parents=True, exist_ok=True)
    fc = {"type": "FeatureCollection",
          "properties": {"crs": "planetocentric lon/lat (deg, east positive)",
                         "box_centre_lonlat": [lon0, lat0], "keep_radius_km": KEEP_RADIUS_KM,
                         "source": "NASA Mars Trek ArcGIS point layers (global compilations)"},
          "features": feats}
    out.write_text(json.dumps(fc), encoding="utf-8")
    return out, len(feats)


def find(data_dir):
    p = Path(data_dir).joinpath(*FILE)
    return p if p.exists() else None


def summary(path, radius_km=100.0):
    """Detections within radius_km of the box, the nearest of each class, plain notes."""
    fc = json.loads(Path(path).read_text(encoding="utf-8"))
    pts = [f for f in fc["features"] if f["properties"]["distance_km"] <= radius_km]
    nearest = {}
    for f in fc["features"]:                      # sorted by distance
        c = f["properties"]["class"]
        nearest.setdefault(c, {"distance_km": f["properties"]["distance_km"],
                               "bearing_deg": f["properties"]["bearing_deg"],
                               "instrument": f["properties"]["instrument"]})
    counts = {c: sum(f["properties"]["class"] == c for f in pts) for c in CLASSES}
    first = fc["features"][0]["properties"] if fc["features"] else None
    notes = ["No orbital detection falls inside the 2 × 2 km box: this is regional context."]
    if first:
        notes.append(f"Nearest: {first['class']} ({first['instrument']}) "
                     f"{first['distance_km']:.0f} km away")
    notes.append("Points are global compilations rounded to 0.01–0.1° (0.6–6 km); "
                 "Curiosity measured the box's minerals on the ground (drill sites)")
    lon0, lat0 = fc["properties"]["box_centre_lonlat"]
    g_d, g_b = distance_bearing(lon0, lat0, *GALE_CENTRE_LONLAT)
    return {"radius_km": radius_km, "box_centre_lonlat": [lon0, lat0],
            "gale": {"distance_km": round(g_d, 1), "bearing_deg": round(g_b, 1),
                     "radius_km": GALE_RADIUS_KM, "approximate": True},
            "classes": CLASSES, "counts": counts, "nearest": nearest, "notes": notes,
            "points": [{"lon": f["geometry"]["coordinates"][0], "lat": f["geometry"]["coordinates"][1],
                        **f["properties"]} for f in pts],
            "source": fc["properties"]["source"]}


if __name__ == "__main__":
    if sys.argv[1:] == ["build"]:
        repo = Path(__file__).resolve().parents[1]
        path, n = build(repo / "data")
        print(f"wrote {path} ({n} detections within {KEEP_RADIUS_KM:.0f} km)")
    else:
        print(__doc__)
