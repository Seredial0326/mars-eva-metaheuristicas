"""E11 radio for the HUD and the walk (#76): line of sight to the habitat and the pair.

- POST /comms/check: the route of a plan (given, or the last saved plan) checked for
  one astronaut (direct radio to the habitat antenna) and for a pair walking `gap_m`
  apart on the same route (relay). Per-vertex arrays aligned with the route vertices,
  like rv_wh: radio_ok (one astronaut) and pair_state ("direct" / "relay" / "none").
- GET /layers/comms.png and /layers/comms: the habitat's radio coverage (cells where
  a suit radio at 1.7 m sees the 3 m antenna), for a given habitat or the last plan's.

The maths is in src/gis/comms.py (JB, E11). Handoff of this file and the routes in
main.py from Sebas on #76.
"""

import io
import sys
from functools import lru_cache
from pathlib import Path
from typing import List, Optional, Tuple

import numpy as np
from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

try:                                       # GDAL is not in api/requirements.txt (conda)
    from gis import comms  # noqa: E402
    AVAILABLE, MISSING = True, None
except ImportError as err:                 # the rest of the API must still start
    comms, AVAILABLE, MISSING = None, False, str(err)

from .plan import feature, feature_collection  # noqa: E402

UNAVAILABLE = "E11 radio needs GDAL's Python bindings (conda install -c conda-forge gdal)"
ANTENNA_H, ASTRONAUT_H = 3.0, 1.7          # m; same defaults as src/gis/comms.py
COVERAGE_RGBA = (42, 120, 214, 110)        # visible cells, translucent blue


class RouteIn(BaseModel):
    coordinates: List[Tuple[float, float]] = Field(min_length=1)
    t_s: Optional[List[float]] = None


class CommsRequest(BaseModel):
    """Extra keys are ignored, so the plan's own request can be sent as is."""
    model_config = ConfigDict(extra="ignore")

    route: Optional[RouteIn] = None          # null: the last saved plan's route
    habitat: Optional[Tuple[float, float]] = None   # null: the plan's habitat
    gap_m: float = Field(default=20.0, ge=0, le=1000)
    max_pair_distance_m: float = Field(default=100.0, gt=0)
    antenna_height_m: float = Field(default=ANTENNA_H, ge=0, le=100)
    astronaut_height_m: float = Field(default=ASTRONAUT_H, ge=0, le=10)
    # Accepted so the plan request can be reused; they do not change the radio.
    human_cost: bool = True
    max_cell_slope_deg: Optional[float] = None


def _inside(bbox, x, y):
    return bbox["xmin"] <= x <= bbox["xmax"] and bbox["ymin"] <= y <= bbox["ymax"]


def route_and_habitat(req, saved_plan, bbox):
    """(coords, t_s, habitat, source) from the request or the saved plan.
    Raises LookupError when there is nothing to check, ValueError when invalid."""
    habitat = req.habitat
    if req.route is not None:
        coords, t_s, source = req.route.coordinates, req.route.t_s, "request"
    else:
        if saved_plan is None:
            raise LookupError("no route given and no plan yet: plan an EVA in the HUD first")
        fc = saved_plan["plan"]
        route = next((f for f in fc["features"] if f["properties"].get("kind") == "route"), None)
        if route is None:
            raise LookupError("the last plan has no route")
        coords, t_s = route["geometry"]["coordinates"], route["properties"].get("t_s")
        source = fc["properties"].get("source", "last plan")
        if habitat is None and fc["properties"].get("habitat"):
            habitat = tuple(fc["properties"]["habitat"])
    if habitat is None:
        habitat = tuple(coords[0])
    if not _inside(bbox, *habitat):
        raise ValueError("habitat is outside the study box")
    if any(not _inside(bbox, x, y) for x, y in coords):
        raise ValueError("the route leaves the study box")
    if t_s is not None and len(t_s) != len(coords):
        raise ValueError("t_s must have one value per route vertex")
    return np.asarray(coords, float), t_s, tuple(habitat), source


def check(base_dir, req, saved_plan, bbox, crs_wkt):
    coords, t_s, habitat, source = route_and_habitat(req, saved_plan, bbox)
    heights = dict(antenna_h=req.antenna_height_m, astronaut_h=req.astronaut_height_m)
    single = comms.check_route(coords, habitat, base_dir, t_s, **heights)
    pair = comms.check_pair(coords, habitat, base_dir, t_s, gap_m=req.gap_m,
                            max_sep_m=req.max_pair_distance_m, **heights)

    def strip(segments):
        return [{k: v for k, v in g.items() if k != "coordinates"} for g in segments]

    features = [
        feature("MultiLineString", [g["coordinates"] for g in single["segments"]],
                kind="no_radio", stretches=strip(single["segments"]), **single["summary"]),
        feature("MultiLineString", [g["coordinates"] for g in pair["unlinked_segments"]],
                kind="pair_unlinked", stretches=strip(pair["unlinked_segments"]),
                gap_m=pair["gap_m"], **pair["unlinked"]),
        feature("Point", list(habitat), kind="habitat",
                antenna_height_m=req.antenna_height_m),
    ]
    return feature_collection(
        features, crs_wkt,
        units={"coordinates": "m", "time": "s", "duration": "min", "length": "m"},
        source=source, habitat=list(habitat),
        antenna_height_m=req.antenna_height_m, astronaut_height_m=req.astronaut_height_m,
        coverage=round(comms.coverage(habitat, base_dir, **heights), 4),
        radio_ok=single["radio_ok"], pair_state=pair["vertex_state"],
        single=single["summary"],
        pair={"gap_m": pair["gap_m"], "max_pair_distance_m": pair["max_separation_m"],
              "max_separation_seen_m": pair["max_separation_seen_m"],
              "unlinked": pair["unlinked"], "relay": pair["relay"],
              "separation_exceeded": pair["separation_exceeded"]},
        warnings=["pure line of sight on the 1 m DEM: no diffraction or link budget; "
                  "boxwork ridges and boulders the DEM misses can block more"])


def default_habitat(saved_plan, centre):
    if saved_plan and saved_plan["plan"]["properties"].get("habitat"):
        return tuple(saved_plan["plan"]["properties"]["habitat"]), "last plan"
    return centre, "box centre (no plan yet)"


@lru_cache(maxsize=16)
def coverage_png(base_dir, x, y):
    vis = comms.line_of_sight((x, y), base_dir)
    rgba = np.zeros((*vis.shape, 4), np.uint8)
    rgba[vis] = COVERAGE_RGBA
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG")
    return buf.getvalue()


def coverage_info(base_dir, habitat, source):
    return {"habitat": list(habitat), "habitat_source": source,
            "coverage": round(comms.coverage(habitat, base_dir), 4),
            "antenna_height_m": ANTENNA_H, "astronaut_height_m": ASTRONAUT_H,
            "colour_rgba": list(COVERAGE_RGBA)}
