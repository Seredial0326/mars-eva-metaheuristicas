"""EVA planner API (FastAPI).

Run from the repo root:
    python -m uvicorn api.main:app --reload --port 8000
Then open http://localhost:8000/

The API and the HUD are served from the same origin, so no CORS setup is needed.
Reference: zero-to-hero guide REV3, sections 33-38.
"""

import json
import os
from pathlib import Path

import numpy as np

from fastapi import FastAPI, HTTPException, Query, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from . import guide
from . import planner
from . import tour
from . import radiation as rad
from . import data_sources
from . import minerals
from . import thermal
from . import weather
from . import walkback as wb
from . import adaptive
from . import comms as e11
from . import departure
from . import lab
from .plan import (PlanRequest, RejoinRequest, ReturnHomeRequest, WalkRecord, WalkbackRequest, feature,
                   feature_collection)
from .raster_layers import blocked_layer, cost_layer, rocks_layer, sand_layer
from . import stations as st

REPO = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("MARTIAN_DATA", REPO / "data"))
BASE = DATA / "base"
TILES = DATA / "tiles"
E2 = DATA / "e2"
STATIONS = DATA / "stations"
E12 = DATA / "e12"
E8 = DATA / "e8"
E9 = DATA / "e9"
PLANS = DATA / "plans"
WALKS = DATA / "walks"
WEB = REPO / "web"

app = FastAPI(title="Mars EVA planner", version="0.1.0")


def _read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


@app.get("/health")
def health():
    """Confirm the server is up and the base data is where we expect it."""
    return {
        "status": "ok",
        "base_grid": (BASE / "grid.json").exists(),
        "tiles": (TILES / "tiles.json").exists(),
    }


@app.get("/layers")
def layers():
    """Grid contract (CRS, bbox, resolution) and the tile layers for the HUD.

    Coordinates everywhere are metres in the DEM's Mars equirectangular CRS,
    never WGS84 (guide section 37).
    """
    return {
        "crs_wkt": (BASE / "crs.wkt").read_text(encoding="utf-8").strip(),
        "grid": _read_json(BASE / "grid.json"),
        "tiles": _read_json(TILES / "tiles.json"),
    }


@app.get("/layers/cost.png")
def cost_png():
    """E3 cost per cell (display only), coloured with the legend from /layers/cost."""
    return Response(cost_layer(str(BASE))[0], media_type="image/png")


@app.get("/layers/cost")
def cost_legend():
    return cost_layer(str(BASE))[1]


@app.get("/layers/sand.png")
def sand_png():
    """E8 sand fraction (release e8-v0): detected sand, conservative."""
    if not (E8 / "sand.tif").exists():
        raise HTTPException(status_code=404, detail="data/e8/sand.tif missing (release e8-v0)")
    return Response(sand_layer(str(E8))[0], media_type="image/png")


@app.get("/layers/rocks.png")
def rocks_png():
    """E9 boulder cover (release e9-rocks-v1, Aaron): halftone, one dot per 10 m square."""
    if not (E9 / "rocas.tif").exists():
        raise HTTPException(status_code=404, detail="data/e9/rocas.tif missing (release e9-rocks-v1)")
    return Response(rocks_layer(str(E9))[0], media_type="image/png")


@app.get("/layers/rocks")
def rocks_info():
    if not (E9 / "rocas.tif").exists():
        raise HTTPException(status_code=404, detail="data/e9/rocas.tif missing (release e9-rocks-v1)")
    return {**rocks_layer(str(E9))[1], "source": "E9 (Aaron): BoulderNet distilled to a small U-Net, release e9-rocks-v1",
            "note": "boulders larger than about 1 m; display only, not part of the route cost"}


@app.get("/layers/sand")
def sand_info():
    if not (E8 / "sand.tif").exists():
        raise HTTPException(status_code=404, detail="data/e8/sand.tif missing (release e8-v0)")
    return {**sand_layer(str(E8))[1], "source": "E8 U-Net v0 (JB), release e8-v0",
            "note": "conservative: ~91 % precision when it marks sand, but it misses a lot of sand"}


@app.get("/layers/blocked.png")
def blocked_png(max_cell_slope_deg: float = Query(30.0, ge=0, le=90)):
    """Cells blocked because their steepest slope exceeds the limit (red)."""
    return Response(blocked_layer(str(BASE), round(max_cell_slope_deg, 1))[0],
                    media_type="image/png")


@app.get("/layers/blocked")
def blocked_stats(max_cell_slope_deg: float = Query(30.0, ge=0, le=90)):
    fraction = blocked_layer(str(BASE), round(max_cell_slope_deg, 1))[1]
    return {"max_cell_slope_deg": max_cell_slope_deg, "blocked_fraction": fraction}


@app.get("/stations/rubric")
def stations_rubric():
    """Default rubric: type -> label, score and the reason behind it."""
    return st.DEFAULT_RUBRIC


@app.get("/stations")
def stations_get():
    """Saved manual stations and the rubric they were saved with."""
    return st.load(STATIONS)


@app.post("/stations")
def stations_save(body: st.StationSet):
    """Validate and save the manual stations as a GeoPackage for E5 (Diana)."""
    try:
        body.check_inside(_read_json(BASE / "grid.json")["bbox"])
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))
    crs_wkt = (BASE / "crs.wkt").read_text(encoding="utf-8").strip()
    path = st.save(body, STATIONS, crs_wkt)
    return {"saved": len(body.stations), "path": path.as_posix()}


@app.get("/stations/candidates")
def stations_candidates():
    """Suggested stations (release stations-candidates-v1). The HUD loads them unsaved."""
    path = STATIONS / "candidates.json"
    if not path.exists():
        raise HTTPException(status_code=404,
                            detail="Curiosity sites missing: gh release download "
                                   "stations-candidates-v1 -D data/stations")
    return _read_json(path)


@app.get("/stations/e8")
def stations_e8():
    """E8 contact stations (JB, release stations-e8-v0). The HUD loads them unsaved."""
    out = st.load_e8(STATIONS)
    if out is None:
        raise HTTPException(status_code=404,
                            detail="E8 stations missing: gh release download stations-e8-v0 -D data/stations")
    return {"stations": out, "source": "E8 (JB): rock next to boxwork-sized sand patches"}


@app.get("/stations/stations_manual.gpkg")
def stations_download():
    path = STATIONS / "stations_manual.gpkg"
    if not path.exists():
        raise HTTPException(status_code=404, detail="no stations saved yet")
    return FileResponse(path, filename="stations_manual.gpkg",
                        media_type="application/geopackage+sqlite3")


@app.get("/radiation")
def radiation():
    """Dose budget and SEP scenarios from E12 (no per-pixel radiation map)."""
    if not (E12 / "sep_alert.json").exists():
        raise HTTPException(status_code=404, detail="E12 outputs missing in data/e12/")
    return {**rad.summary(E12), "curve": rad.dose_curve(E12)}


@app.get("/weather")
def weather_summary(sol: int = Query(weather.DEFAULT_SOL, ge=1),
                    eva_min: float = Query(None, gt=0)):
    """Surface weather of one sol from Curiosity's REMS (context, not a cost term)."""
    path = weather.find_feed(DATA)
    if path is None:
        raise HTTPException(status_code=404, detail="REMS feed missing: data/rems/ (release rems-v1)")
    return weather.summary(path, sol, eva_min)


@app.get("/layers/thermal.png")
def thermal_png():
    """THEMIS night IR over the box (Mars Odyssey, ~81 m pixels), gray."""
    path = thermal.find(DATA)
    if path is None:
        raise HTTPException(status_code=404, detail="THEMIS tile missing: data/thermal/ (release themis-v1)")
    bbox = json.loads((BASE / "grid.json").read_text(encoding="utf-8"))["bbox"]
    return Response(thermal.layer_png(path, (bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"])),
                    media_type="image/png")


@app.get("/thermal")
def thermal_summary():
    """What the THEMIS layer is, and how it compares with E8's sand (context only)."""
    path = thermal.find(DATA)
    if path is None:
        raise HTTPException(status_code=404, detail="THEMIS tile missing: data/thermal/ (release themis-v1)")
    return thermal.summary(path, E8 / "sand.tif", BASE / "slope_deg.tif")


@app.get("/minerals")
def minerals_summary(radius_km: float = Query(100.0, gt=0, le=minerals.KEEP_RADIUS_KM)):
    """Orbital mineral detections (CRISM/OMEGA) around the box: regional context only."""
    path = minerals.find(DATA)
    if path is None:
        raise HTTPException(status_code=404,
                            detail="mineral detections missing: data/minerals/ (release minerals-v1)")
    return minerals.summary(path, radius_km)


@app.get("/data_sources")
def data_sources_summary():
    """Data types, instruments and missions the product combines (HUD panel)."""
    return data_sources.summary(DATA)


@app.post("/walks")
def walks_save(rec: WalkRecord):
    """Keep a walk logged by the guide (tablet or 3D rehearsal) with its summary
    against the plan, for the debrief (P6, #45)."""
    return {"saved": guide.save_walk(WALKS, rec.model_dump())}


@app.get("/walks/last")
def walks_last():
    rec = guide.load_walk(WALKS)
    if rec is None:
        raise HTTPException(status_code=404, detail="no walk logged yet: walk a plan in guide mode first")
    return rec


@app.get("/plan/last")
def plan_last():
    """The last live plan, for the guide screen (web/guide.html)."""
    saved = guide.load_plan(PLANS)
    if saved is None:
        raise HTTPException(status_code=404, detail="no plan yet: plan an EVA in the HUD first")
    return saved


@app.get("/plan/departure")
def plan_departure(sol: int = Query(weather.DEFAULT_SOL, ge=1)):
    """P6: best time to leave for the last plan on a Curiosity sol. For each departure
    (every 15 min, 05:00-19:00 local true solar time) the share of the walk in sunlight,
    in the terrain's shadow or in the dark; the best one and the fully lit window."""
    try:
        return departure.best_time(BASE, guide.load_plan(PLANS), sol)
    except LookupError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))


@app.post("/guide/return_home")
def return_home(req: ReturnHomeRequest):
    """Fastest way back to the habitat from the astronaut's position (E4 reversed
    Dijkstra on time, no new planning)."""
    limit = req.max_cell_slope_deg
    try:
        out = guide.return_home(str(BASE), limit, req.position, req.habitat, req.human_cost,
                                req.k, resources=req.resources())
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))
    crs_wkt = (BASE / "crs.wkt").read_text(encoding="utf-8").strip()
    return feature_collection(
        [feature("LineString", out.pop("coordinates"), kind="return_home", **out)], crs_wkt,
        units={"coordinates": "m", "energy": "Wh", "time": "s"})


@app.post("/guide/rejoin")
def rejoin(req: RejoinRequest):
    """Off route: least-energy path back onto the planned route, with the per-vertex
    profile (t_s, used_wh, rv_wh, rv_time_s) so the guide can splice it in."""
    limit = req.max_cell_slope_deg
    try:
        out = guide.rejoin(str(BASE), limit, req.position, req.target, req.habitat,
                           req.human_cost, resources=req.resources(),
                           continuation=req.continuation.model_dump() if req.continuation else None)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))
    crs_wkt = (BASE / "crs.wkt").read_text(encoding="utf-8").strip()
    return feature_collection(
        [feature("LineString", out.pop("coordinates"), kind="rejoin", **out)], crs_wkt,
        units={"coordinates": "m", "energy": "Wh", "time": "s"})


def _box_centre():
    b = _read_json(BASE / "grid.json")["bbox"]
    return ((b["xmin"] + b["xmax"]) / 2, (b["ymin"] + b["ymax"]) / 2)


@app.post("/walkback")
def walkback(req: WalkbackRequest):
    """Red line R_T = threshold (cached per base) and the energy-safe boundary
    F_E(p, v) + R_E(v) = E_remaining (recomputed for each position and energy).
    Also compares the red line with the fixed-radius rules (guide section 15.2)."""
    limit = req.max_cell_slope_deg
    base_xy = req.base or _box_centre()
    try:
        g = wb.grid(str(BASE), limit, req.human_cost)
        base_node, pos_node = g.node(*base_xy), g.node(*req.current_position)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))
    r_t, r_e = wb.return_fields(str(BASE), limit, base_node, req.human_cost)
    if not np.isfinite(r_t.flat[pos_node]):
        raise HTTPException(status_code=422, detail="no walkable path from this position "
                            "to the base (blocked cell or isolated area)")
    e_rem_j = req.energy_remaining_wh * 3600.0
    # X2 (#101): a uniform metabolic factor k scales every arc, so k (F_E + R_E) <= E_rem
    # is the same region as F_E + R_E <= E_rem / k (k = 1: unchanged).
    e_eff_j = e_rem_j / req.k
    f_e = wb.forward_energy(str(BASE), limit, pos_node, e_eff_j, req.human_cost)
    combined = f_e + r_e                                   # J at k = 1: go to v, then return

    rt_here, re_here = float(r_t.flat[pos_node]), float(r_e.flat[pos_node]) * req.k
    warnings = [f"return fields on {g.cost_model} costs (same graph as /plan)"]
    if req.base is None:
        warnings.append("base not set: using the box centre (illustrative)")
    features = [
        feature("MultiLineString", g.contour(r_t, req.emergency_return_time_s, base_node),
                kind="emergency_time_boundary", threshold_s=req.emergency_return_time_s),
        feature("MultiLineString", g.contour(combined, e_eff_j, pos_node),
                kind="energy_safe_boundary", energy_remaining_wh=req.energy_remaining_wh),
        feature("Point", list(base_xy), kind="base"),
        feature("Point", list(req.current_position), kind="current_position"),
    ]
    for chk in wb.fixed_radius_check(g, r_t, base_xy, req.emergency_return_time_s):
        features.append(feature("LineString", chk.pop("circle"), kind="fixed_radius", **chk))
    crs_wkt = (BASE / "crs.wkt").read_text(encoding="utf-8").strip()
    return feature_collection(
        features, crs_wkt,
        units={"coordinates": "m", "energy": "Wh", "time": "s"},
        return_time_s=rt_here, return_energy_wh=re_here / 3600.0,
        contingency_ok=rt_here <= req.emergency_return_time_s,
        energy_ok=re_here <= e_rem_j,
        energy_left_after_return_wh=(e_rem_j - re_here) / 3600.0, k=req.k,
        max_cell_slope_deg=req.max_cell_slope_deg, warnings=warnings)


@app.post("/walkback/update")
def walkback_update(req: adaptive.UpdateRequest):
    """X2 (#101): one walked segment -> posterior of the metabolic factor k, k_p90, the
    reserve home at k_p90 and the "return now" alert (stateless: send the posterior
    back on the next call). Units: Wh or L for the whole request."""
    ret = req.return_predicted
    warnings = []
    if ret is None:
        limit = req.max_cell_slope_deg
        habitat = req.habitat
        if habitat is None:
            saved = guide.load_plan(PLANS)
            habitat = (tuple(saved["plan"]["properties"]["habitat"])
                       if saved and saved["plan"]["properties"].get("habitat") else _box_centre())
            warnings.append("habitat not given: last plan's habitat (or the box centre)")
        try:
            g = wb.grid(str(BASE), limit, req.human_cost)
            base_node, pos_node = g.node(*habitat), g.node(*req.position)
        except ValueError as err:
            raise HTTPException(status_code=422, detail=str(err))
        _, r_e = wb.return_fields(str(BASE), limit, base_node, req.human_cost)
        re_j = float(r_e.flat[pos_node])
        if not np.isfinite(re_j):
            raise HTTPException(status_code=422, detail="no walkable path from this position "
                                "to the habitat")
        ret = adaptive.to_unit(re_j / 3600.0, req.unit)
    out = adaptive.update(req, ret)
    out["warnings"] += warnings
    return out

class PlanError(Exception):
    """A /plan request with no plan: 422 with the same text `detail` as before, plus
    `diagnosis` (E5's structured reason, #119 A4) when the planner gives one."""
    def __init__(self, detail, diagnosis=None):
        super().__init__(detail)
        self.detail, self.diagnosis = detail, diagnosis


@app.exception_handler(PlanError)
def _plan_error(request, err):
    body = {"detail": err.detail}
    if err.diagnosis is not None:
        body["diagnosis"] = err.diagnosis
    return JSONResponse(status_code=422, content=body)


def _plan_tour(req):
    """E5 station tour on E4's graph (when E5 is in main)."""
    service_w = (req.service_energy_wh_per_min * 60.0 if req.service_energy_wh_per_min is not None
                 else planner.SERVICE_POWER_W)
    try:
        fc, info = tour.plan_tour(req, BASE, service_w)
    except ValueError as err:
        raise PlanError(str(err), getattr(err, "diagnosis", None))
    except tour.NoTour as err:
        raise PlanError(f"no feasible tour: {err}", err.diagnosis)
    p = fc["features"][0]["properties"]
    order = {sid: i + 1 for i, sid in enumerate(info["visit_order"])}
    warnings = [f"E5 tour: {len(order)} of {info['stations_considered']} stations, prize "
                f"{info['prize']:g} (order {' > '.join(info['visit_order'])})"]
    skipped = [s.id for s in req.stations if s.id not in order]
    if skipped:
        warnings.append(f"not visited within the limits: {', '.join(skipped)}")
    if info["habitat_moved_m"] > 0:
        warnings.append(f"habitat moved {info['habitat_moved_m']:.1f} m to the nearest walkable cell")
    if req.service_energy_wh_per_min is None:
        warnings.append(f"service power assumed {service_w:.0f} W (E4 default)")
    warnings += info.get("warnings", [])                 # E5: O2 limit, re-plans, moved stations
    fc["features"] += [feature("Point", [s.x, s.y], kind="station", id=s.id, type=s.type,
                               score=s.score, service_time_min=s.service_time_min,
                               visited=s.id in order, order=order.get(s.id))
                       for s in req.stations]
    fc["properties"] = dict(
        model="santee_2001", source=f"E5 tour (live, {info.get('engine', 'E5')})",
        habitat=list(req.start),
        cost_model=info["cost_model"], human_cost=req.human_cost,
        units={"coordinates": "m", "energy": "Wh", "time": "s"},
        energy_budget_wh=req.energy_budget_wh, energy_usable_wh=p["usable_wh"],
        feasible=p["feasible"], max_cell_slope_deg=req.max_cell_slope_deg,
        max_duration_min=req.max_duration_min, o2_budget_l=req.o2_budget_l,
        effective=req.effective(info["cost_model"], service_w),
        warnings=warnings)
    guide.save_plan(PLANS, req.model_dump(), fc)
    return fc


def _plan_live(req):
    """E5 tour when available and no explicit goal; otherwise the E4 round trip to
    the request's goal or the best-scoring station."""
    if tour.AVAILABLE and req.goal is None and req.stations:
        return _plan_tour(req)
    try:
        fc, info = planner.plan(req, BASE)
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))
    except planner.NoFeasibleRoute as err:
        raise HTTPException(status_code=422, detail=f"no feasible route: {err}")
    route = next(f for f in fc["features"] if f["properties"]["kind"] == "route")
    p = route["properties"]
    warnings = []
    if info["goal_station"] is not None:
        warnings.append(f"single-goal round trip to the best-scoring station "
                        f"{info['goal_station']}; the multi-station tour comes with E5")
    for what in ("habitat", "goal"):
        if info[f"{what}_moved_m"] > 0:
            warnings.append(f"{what} moved {info[what + '_moved_m']:.1f} m to the nearest "
                            "walkable cell of the main connected area")
    if req.service_energy_wh_per_min is None:
        warnings.append(f"service power assumed {info['service_power_w']:.0f} W (E4 default)")
    fc["features"] += [feature("Point", [s.x, s.y], kind="station", id=s.id, type=s.type,
                               score=s.score, service_time_min=s.service_time_min)
                       for s in req.stations]
    fc["properties"] = dict(
        model="santee_2001", source="E4_walkback (live)",
        habitat=list(req.start), cost_model=info["cost_model"], human_cost=req.human_cost,
        units={"coordinates": "m", "energy": "Wh", "time": "s"},
        energy_budget_wh=req.energy_budget_wh, energy_usable_wh=p["usable_wh"],
        feasible=p["feasible"], max_cell_slope_deg=req.max_cell_slope_deg,
        max_duration_min=req.max_duration_min, o2_budget_l=req.o2_budget_l,
        effective=req.effective(info["cost_model"], info["service_power_w"]),
        warnings=warnings)
    guide.save_plan(PLANS, req.model_dump(), fc)        # the guide screen loads it
    return fc


def _fixed_test_route():
    """Curiosity's trajectory (E2, Juan) used as a fixed route to test the whole
    pipeline before the planner is connected (guide section 38)."""
    route = _read_json(E2 / "trajectory.geojson")["features"][0]
    return route["geometry"]["coordinates"], route["properties"]


@app.post("/plan")
def plan(req: PlanRequest):
    """Plan an EVA. For now it returns a FIXED test route, not a planned one."""
    try:
        req.check_inside(_read_json(BASE / "grid.json")["bbox"])
    except ValueError as err:
        msg = str(err)
        field = "start" if msg.startswith("start") else next(
            (f"stations[{i}]" for i, s in enumerate(req.stations) if msg.startswith(f"station {s.id} ")), "stations")
        raise PlanError(msg, {"code": "invalid_input", "exact": True, "field": field, "message": msg})

    if req.stations or req.goal is not None:
        return _plan_live(req)
    coords, props = _fixed_test_route()
    warnings = ["fixed test route (Curiosity trajectory): the planner is not connected yet"]
    if req.service_energy_wh_per_min is None:
        warnings.append("service_energy_wh_per_min is null: the plan cannot be labelled "
                        "energy-feasible")

    features = [feature("LineString", coords, kind="route", source="curiosity_trajectory_e2",
                        length_m=props.get("length_m"), energy_wh=None, time_s=None)]
    features += [feature("Point", [s.x, s.y], kind="station", id=s.id, score=s.score,
                         service_time_min=s.service_time_min) for s in req.stations]
    features.append(feature("Point", list(req.start), kind="start"))

    crs_wkt = (BASE / "crs.wkt").read_text(encoding="utf-8").strip()
    return feature_collection(
        features, crs_wkt,
        model="santee_2001", units={"coordinates": "m", "energy": "Wh", "time": "s"},
        energy_budget_wh=req.energy_budget_wh,
        energy_usable_wh=req.energy_usable_j / 3600.0,
        max_cell_slope_deg=req.max_cell_slope_deg,
        effective=req.effective(None, None),
        feasible=None, warnings=warnings)


@app.post("/comms/check")
def comms_check(req: e11.CommsRequest):
    """E11 radio along a route (the given one, or the last plan's): stretches with no
    direct radio to the habitat, and the pair (relay) with radio_ok / pair_state per
    route vertex."""
    _e11_ready()
    grid = _read_json(BASE / "grid.json")
    crs_wkt = (BASE / "crs.wkt").read_text(encoding="utf-8").strip()
    try:
        return e11.check(str(BASE), req, guide.load_plan(PLANS), grid["bbox"], crs_wkt)
    except LookupError as err:
        raise HTTPException(status_code=404, detail=str(err))
    except ValueError as err:
        raise HTTPException(status_code=422, detail=str(err))


def _e11_ready():
    """E11 needs GDAL (conda); without it only these routes fail, with 503."""
    if not e11.AVAILABLE:
        raise HTTPException(status_code=503, detail=f"{e11.UNAVAILABLE}: {e11.MISSING}")


def _comms_habitat(x, y):
    _e11_ready()
    if (x is None) != (y is None):
        raise HTTPException(status_code=422, detail="give both x and y, or neither")
    if x is not None:
        b = _read_json(BASE / "grid.json")["bbox"]
        if not (b["xmin"] <= x <= b["xmax"] and b["ymin"] <= y <= b["ymax"]):
            raise HTTPException(status_code=422, detail="habitat is outside the study box")
        return (x, y), "request"
    return e11.default_habitat(guide.load_plan(PLANS), _box_centre())


@app.get("/layers/comms.png")
def comms_png(x: float = Query(None), y: float = Query(None)):
    """E11 radio coverage of a habitat (default: the last plan's), blue = visible."""
    (hx, hy), _ = _comms_habitat(x, y)
    return Response(e11.coverage_png(str(BASE), round(hx, 1), round(hy, 1)),
                    media_type="image/png")


@app.get("/layers/comms")
def comms_info(x: float = Query(None), y: float = Query(None)):
    habitat, source = _comms_habitat(x, y)
    return e11.coverage_info(str(BASE), habitat, source)


app.include_router(lab.router)


# Static files go last so they do not shadow the API routes.
app.mount("/tiles", StaticFiles(directory=TILES, check_dir=False), name="tiles")   # without tiles-v2 the API still starts (check_data says what is missing)
# The illustrated user guides, served from docs/ as they are: same paths as in the repo, so
# the links between the 2D and the 3D guide keep working. The landing page links to them.
for _guide in ("user_guide", "user_guide_3d"):
    app.mount(f"/docs/{_guide}", StaticFiles(directory=REPO / "docs" / _guide, html=True, check_dir=False),
              name=_guide)
app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
