"""Live planning for POST /plan with E4 (Aaron, src/grafos) on E3's costs.

- The graph is built from fisica.edge_costs with the cell block the user chose
  in the HUD (team decision: it can be moved or disabled), cached per limit.
- Habitat and goal are snapped with Graph.place (walkable cell in the main
  connected area); the response reports how far they moved.
- The route is E4's round trip habitat -> goal -> habitat under the energy,
  duration and O2 limits (labels.round_trip), formatted with build_rv's
  route_geojson, so the per-vertex profile (used_wh, rv_wh, t_s, rv_time_s,
  o2_used_l, slack_wh) reaches the HUD unchanged.
- Until E5 (Diana) is merged the goal is one station: the request's goal, or the
  highest-scoring station. With E5 it becomes the full station tour.
"""

import json
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fisica.edge_cost import NEIGHBOURS, edge_costs  # noqa: E402
from fisica.human_cost import (human_edge_costs, load_rasters, load_weights,  # noqa: E402
                               terrain_factor)
from fisica.metabolic import J_PER_WH  # noqa: E402
from grafos.build_rv import SERVICE_POWER_W, route_geojson  # noqa: E402
from grafos.graph import Graph  # noqa: E402
from grafos.labels import Budget, NoFeasibleRoute, round_trip  # noqa: E402


def e1_weights_path(base_dir):
    """E1's weights (release e1-sand-v1) next to the base grid, or None."""
    path = Path(base_dir).parent / "e1" / "e1_weights.json"
    return path if path.exists() else None


@lru_cache(maxsize=4)
def graph(base_dir, max_cell_slope_deg, human=True):
    """E4 Graph on E3 costs; with human=True and E1's weights present, the energy
    of every arc is E3 x E1's terrain factor of the arrival cell (fisica.human_cost).
    Time is unchanged (E1 prices energy, not speed)."""
    base = Path(base_dir)
    with rasterio.open(base / "dem_1m.tif") as src:
        dem = src.read(1).astype(np.float64)
    with rasterio.open(base / "slope_deg.tif") as src:
        slope = src.read(1)
    t, e, _ = edge_costs(dem, cell_slope_deg=slope, max_cell_slope_deg=max_cell_slope_deg)
    weights = e1_weights_path(base) if human else None
    if weights is not None:
        spec = load_weights(weights)
        factor = terrain_factor(spec, load_rasters(spec, base), dem.shape)
        e = human_edge_costs(e, factor, NEIGHBOURS)
    g = json.loads((base / "grid.json").read_text(encoding="utf-8"))
    gr = Graph({"energy_j": e, "time_s": t}, NEIGHBOURS,
               transform=tuple(g["grid_1m"]["affine"]),
               crs_wkt=(base / "crs.wkt").read_text(encoding="utf-8").strip())
    gr.cost_model = "E3 x E1 sand (human)" if weights is not None else "E3"
    return gr


def pick_goal(req):
    """(x, y, station or None): explicit goal, else the best-scoring station."""
    if req.goal is not None:
        return req.goal[0], req.goal[1], None
    if not req.stations:
        raise ValueError("add a station or a goal to plan a route")
    best = max(req.stations, key=lambda s: s.score)
    return best.x, best.y, best


def plan(req, base_dir):
    """FeatureCollection of the E4 round trip. Raises ValueError or NoFeasibleRoute."""
    g = graph(str(base_dir), req.max_cell_slope_deg, req.human_cost)
    gx, gy, station = pick_goal(req)
    hr, hc, h_moved = g.place(*req.start, label="habitat")
    tr, tc, t_moved = g.place(gx, gy, label="goal")
    habitat, goal = int(g.node(hr, hc)), int(g.node(tr, tc))
    if habitat == goal:
        raise ValueError("the goal falls on the habitat cell")

    service_min = station.service_time_min if station else 0.0
    service_w = (req.service_energy_wh_per_min * 60.0 if req.service_energy_wh_per_min is not None
                 else SERVICE_POWER_W)
    budget = Budget(
        energy_j=req.energy_budget_wh * (1 - req.margin) * J_PER_WH,
        time_s=np.inf if req.max_duration_min is None else req.max_duration_min * 60.0,
        o2_l=np.inf if req.o2_budget_l is None else req.o2_budget_l)
    prof = round_trip(g, habitat, goal, budget, service_s=service_min * 60.0,
                      service_power_w=service_w)

    habitat_xy = [float(v) for v in g.cell_to_xy(hr, hc)]
    goal_xy = [float(v) for v in g.cell_to_xy(tr, tc)]
    fc = route_geojson(g, prof, habitat_xy, goal_xy, g.crs_wkt,
                       budget_wh=req.energy_budget_wh, margin=req.margin,
                       max_duration_min=req.max_duration_min, o2_budget_l=req.o2_budget_l,
                       service_min=service_min, objective="energy")
    for f in fc["features"]:
        k = f["properties"]["kind"]
        if k == "start":
            f["properties"].update(requested=list(req.start), moved_m=h_moved)
        elif k == "goal":
            f["properties"].update(requested=[gx, gy], moved_m=t_moved,
                                   station=station.id if station else None)
    return fc, {"cost_model": g.cost_model, "habitat_moved_m": h_moved, "goal_moved_m": t_moved,
                "goal_station": station.id if station else None,
                "service_power_w": service_w}


__all__ = ["plan", "graph", "NoFeasibleRoute"]
