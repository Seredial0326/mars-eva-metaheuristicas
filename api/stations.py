"""Manual science stations: rubric, validation and GeoPackage export for E5.

The score of a station is NOT chosen per station: it comes from the rubric of
its type, so the value of every station can be traced to an explicit,
editable rule (guide REV3, section 24). The HUD can edit the rubric live.

Output for Diana (E5): data/stations/stations_manual.gpkg, layer "stations",
DEM CRS, columns id, type, score, service_time_min, note. The rubric used is
saved next to it as stations_rubric.json.
"""

import json
from pathlib import Path
from typing import Dict, List

import geopandas as gpd
from pydantic import BaseModel, Field, field_validator, model_validator
from shapely.geometry import Point

# Default rubric (team decision, 2026-11-14), backed by the literature review in
# docs/research/station_value_rubric.md. Scores encode an expert ORDER of
# priorities (Apollo/BASALT practice), not measured values; the HUD edits them
# live and the paper reports their sensitivity.
RUBRIC_VERSION = "2026-11-14"
DEFAULT_RUBRIC = {
    "ridge": {
        "label": "Boxwork ridge", "score": 5,
        "why": ("Ridge cement: late groundwater in the sulfate interval; the drilled ridge "
                "(Nevado Sajama) has clays + Fe oxides and was chosen for the mission's last "
                "SAM TMAH organics run (preliminary, n = 1)"),
        "sources": ["Siebach2014", "Hausrath2026", "JPL2026"],
    },
    "hollow": {
        "label": "Hollow between ridges", "score": 4,
        "why": ("Hollow bedrock: abundant siderite, no clays, less altered (reduced end-member "
                "of the pair; preliminary, n = 1). Sand and slip are costed in E3/E4, not here"),
        "sources": ["Hausrath2026", "Siebach2026"],
    },
    "contact": {
        "label": "Contact between units", "score": 4,
        "why": ("Contact between units: brackets environmental change and relative timing "
                "(clay-free Chenapau / clay-bearing Altadena; Altadena / layered sulfate); "
                "explicit final-phase target of Curiosity's boxwork campaign"),
        "sources": ["NASA-blog-4804", "Herd2025", "Siebach2026"],
    },
    "curiosity": {
        "label": "Curiosity measurement site", "score": 3,
        "why": ("Curiosity drill or long stop: ground truth and calibration for the E8 maps; "
                "little new science because it is already measured"),
        "sources": ["MSR-STM2025", "Brady2019"],
    },
}

LAYER = "stations"


class ManualStation(BaseModel):
    id: str = Field(min_length=1)
    type: str
    x: float
    y: float
    service_time_min: float = Field(default=10.0, ge=0)
    note: str = ""


class StationSet(BaseModel):
    rubric: Dict[str, float]                       # type -> score
    stations: List[ManualStation] = []

    @field_validator("rubric")
    @classmethod
    def non_negative_scores(cls, rubric):
        if any(v < 0 for v in rubric.values()):
            raise ValueError("rubric scores must be >= 0")
        return rubric

    @model_validator(mode="after")
    def consistent(self):
        ids = [s.id for s in self.stations]
        if len(ids) != len(set(ids)):
            raise ValueError("station ids must be unique")
        unknown = {s.type for s in self.stations} - set(self.rubric)
        if unknown:
            raise ValueError(f"station types not in the rubric: {sorted(unknown)}")
        return self

    def check_inside(self, bbox):
        for s in self.stations:
            if not (bbox["xmin"] <= s.x <= bbox["xmax"] and bbox["ymin"] <= s.y <= bbox["ymax"]):
                raise ValueError(f"station {s.id} is outside the study box")


def save(station_set, out_dir, crs_wkt):
    """Write the GeoPackage and the rubric. Returns the GeoPackage path."""
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / "stations_manual.gpkg"
    rows = [{"id": s.id, "type": s.type, "score": float(station_set.rubric[s.type]),
             "service_time_min": s.service_time_min, "note": s.note,
             "geometry": Point(s.x, s.y)} for s in station_set.stations]
    columns = ["id", "type", "score", "service_time_min", "note", "geometry"]
    gdf = gpd.GeoDataFrame(rows, columns=columns, geometry="geometry", crs=crs_wkt)
    if path.exists():
        path.unlink()                                 # overwrite the whole file
    gdf.to_file(path, layer=LAYER, driver="GPKG")
    (out_dir / "stations_rubric.json").write_text(json.dumps({
        "rubric": station_set.rubric,
        "default_rubric_version": RUBRIC_VERSION,
        "sources": {t: v["sources"] for t, v in DEFAULT_RUBRIC.items()},
        "review": "docs/research/station_value_rubric.md",
    }, indent=2), encoding="utf-8")
    return path


def load(out_dir):
    """Saved stations and rubric, or empty defaults if nothing was saved yet."""
    out_dir = Path(out_dir)
    path = out_dir / "stations_manual.gpkg"
    rubric_path = out_dir / "stations_rubric.json"
    rubric = ({k: v["score"] for k, v in DEFAULT_RUBRIC.items()} if not rubric_path.exists()
              else json.loads(rubric_path.read_text(encoding="utf-8"))["rubric"])
    stations = []
    if path.exists():
        gdf = gpd.read_file(path, layer=LAYER)
        stations = [{"id": r.id, "type": r.type, "x": r.geometry.x, "y": r.geometry.y,
                     "service_time_min": float(r.service_time_min), "note": r.note or ""}
                    for r in gdf.itertuples()]
    return {"rubric": rubric, "stations": stations}


E8_FILE = "stations_e8.gpkg"


def load_e8(out_dir):
    """JB's E8 contact stations (release stations-e8-v0): the highest rock point next to
    a boxwork-sized sand patch. They are type "contact", so in the HUD their score is the
    rubric's contact score like any other station; E8's own 1-5 score (patch size and
    hollow density) goes in the note, as a hint for choosing among them."""
    path = Path(out_dir) / E8_FILE
    if not path.exists():
        return None
    gdf = gpd.read_file(path, layer="stations")
    out = []
    for _, r in gdf.iterrows():
        note = f"E8 score {float(r['score']):.1f}/5"
        if "sand_patch_m2" in gdf.columns:
            note += f" · sand patch {float(r['sand_patch_m2']):.0f} m²"
        if "tpi_m" in gdf.columns:
            note += f" · {float(r['tpi_m']):.1f} m above its surroundings"
        out.append({"id": str(r["id"]), "type": str(r["type"]), "x": float(r.geometry.x),
                    "y": float(r.geometry.y), "service_time_min": float(r["service_time_min"]),
                    "note": note + " (E8 U-Net + TPI, JB)", "e8_score": float(r["score"])})
    return out
