"""Multi-station EVA for POST /plan: E5 (Diana, src/orienteering) chooses which
stations to visit and in what order; E4 (Aaron) gives the legs and checks the
walkback; the HUD and the guide get the same per-vertex profile as E4's route.

E5 is imported lazily: until it is merged in main, AVAILABLE is False and /plan
keeps planning the single-goal E4 round trip.
"""

import numpy as np

from . import planner
from fisica.metabolic import J_PER_WH, KJ_PER_LITER_O2  # noqa: E402 (planner sets the path)
from grafos.walkback import check_walkback  # noqa: E402

try:
    # Preferred: E5's own /plan entry point (Diana, src/orienteering/tour.py). It owns
    # the tour logic (O2 limit, walkback re-planning); this module only adapts names.
    from orienteering.tour import plan_tour as _e5_plan_tour
    from grafos.labels import NoFeasibleRoute as _E4NoRoute
    DELEGATE = True
except ImportError:
    DELEGATE = False

try:
    from orienteering.data_io import Stations
    from orienteering.network import route_path, station_matrices
    from orienteering.problem import Problem
    from orienteering.solvers import MAX_STATIONS, SOLVERS
    AVAILABLE = True
except ImportError:                       # E5 not merged yet
    AVAILABLE = False
AVAILABLE = AVAILABLE or DELEGATE


class NoTour(Exception):
    """Nothing fits the limits. .diagnosis is E5's structured reason (#119 A4:
    code, exact, message, and the limiting station and resource when known), or None."""
    def __init__(self, message, diagnosis=None):
        super().__init__(message)
        self.diagnosis = diagnosis


def plan_tour(req, base_dir, service_power_w):
    """FeatureCollection of the best station tour habitat -> ... -> habitat.

    Raises ValueError (bad input) or NoTour (nothing fits the limits)."""
    g = planner.graph(str(base_dir), req.max_cell_slope_deg, req.human_cost)
    if DELEGATE:
        return _delegate(req, g)
    return _local_tour(req, g, service_power_w)


def _delegate(req, g):
    """Call E5's plan_tour on the shared graph (E3 or human cost) and normalise names
    for the HUD and the guide (order -> visit_order)."""
    try:
        fc, info = _e5_plan_tour(req, g, req.solver)
    except _E4NoRoute as err:
        raise NoTour(str(err), getattr(err, "diagnosis", None))
    route = next(f for f in fc["features"] if f["properties"]["kind"] == "route")
    p = route["properties"]
    if not p.get("feasible", True):
        # E5 re-plans on a walkback failure but, if every retry fails, returns the last
        # (unsafe) tour. Never hand an unsafe tour to the HUD or the guide.
        raise NoTour(_unsafe_message(p.get("first_violation"), info.get("walkback_retries", 0)),
                     p.get("diagnosis") or info.get("diagnosis"))
    # E5 lists the habitat at both ends of order/stop_index; the HUD and the guide
    # expect only the stations, in visiting order, with their positions on the line.
    order, idx = list(p.get("order", [])), list(p.get("stop_index", []))
    pairs = [(o, i) for o, i in zip(order, idx) if o != "habitat"] if len(order) == len(idx)         else [(o, None) for o in order if o != "habitat"]
    p["visit_order"] = [o for o, _ in pairs]
    if all(i is not None for _, i in pairs):
        p["stop_index"] = [int(i) for _, i in pairs]
    if p["stop_index"] and p.get("turn_index") is None:
        p["turn_index"] = int(p["stop_index"][-1])
    info = dict(info)
    info["visit_order"] = p["visit_order"]
    info["stations_considered"] = len(req.stations)
    info["cost_model"] = g.cost_model
    info["engine"] = "E5 plan_tour (src/orienteering)"
    return fc, info


def _unsafe_message(first_violation, retries):
    where = "" if first_violation is None else f" at route vertex {first_violation}"
    return (f"every tour that fits the limits fails the walkback{where} (not enough energy "
            f"left to return; {retries} re-plan(s) tried); raise the budget or lower the margin")


MAX_REPLANS = 5


def _local_tour(req, g, service_power_w):
    """Fallback built on E5's primitives, for E5 versions without plan_tour."""
    hr, hc, h_moved = g.place(*req.start, label="habitat")
    hx, hy = (float(v) for v in g.cell_to_xy(hr, hc))

    # Stations on the grid: snapped like E4, one station per cell, habitat first.
    rows, cols, keep, moved = [], [], [], {}
    used_cells = {(hr, hc)}
    for s in req.stations:
        r, c, m = g.place(s.x, s.y, label=f"station {s.id}")
        if (r, c) in used_cells:
            continue
        used_cells.add((r, c)); rows.append(r); cols.append(c); keep.append(s); moved[s.id] = m
    if not keep:
        raise ValueError("no station left after placing them on the grid")
    limit = MAX_STATIONS["dp"]
    if len(keep) + 1 > limit:
        raise ValueError(f"{len(keep)} stations: the exact DP supports up to {limit - 1}")
    xs, ys = g.cell_to_xy(np.array(rows), np.array(cols))
    st = Stations(id=np.array([s.id for s in keep]), type=np.array([s.type or "" for s in keep]),
                  x=np.asarray(xs, float), y=np.asarray(ys, float),
                  row=np.array(rows), col=np.array(cols),
                  prize=np.array([s.score for s in keep], float),
                  service_s=np.array([s.service_time_min * 60.0 for s in keep], float))
    st = st.prepend("habitat", "habitat", hx, hy, hr, hc)

    dis, tim = station_matrices(g, st)
    usable_j = req.energy_budget_wh * (1 - req.margin) * J_PER_WH
    service_j = st.service_s * service_power_w
    max_s = None if req.max_duration_min is None else req.max_duration_min * 60.0
    habitat = int(g.node(hr, hc))
    rv_e = g.costs_to(habitat, "energy_j")
    rv_t = g.costs_to(habitat, "time_s")

    # The DP checks energy only at the stations; the walkback is checked on every vertex
    # of the walked line. If it fails, re-plan with the DP budget lowered by the deficit
    # (the slack is always measured against the real usable energy).
    budget, retries = usable_j, 0
    while True:
        problem = Problem(energy=dis, prize=st.prize, budget=budget, time=tim,
                          service_s=st.service_s, service_j=service_j, max_duration_s=max_s)
        sol = SOLVERS["dp"](problem)
        if not sol.route or len(sol.route) < 3:
            if retries:
                raise NoTour(_unsafe_message(first_violation, retries))
            raise NoTour("no station fits in the energy budget and EVA duration")
        path, stop_index = route_path(g, st, sol.route, dis)
        wb = check_walkback(g, path, rv_e, usable_j)
        # Per-vertex profile: walking from E4's graph plus service added at each stop.
        used, t = wb["used_j"].copy(), wb["time_s"].copy()
        for k, idx in zip(sol.route[1:-1], stop_index[1:-1]):
            used[idx:] += service_j[k]
            t[idx:] += st.service_s[k]
        rv = rv_e[path]
        slack = usable_j - used - rv
        bad = np.nonzero(slack < -1e-6)[0]
        if not len(bad):
            break
        first_violation = int(bad[0])
        if retries >= MAX_REPLANS:
            raise NoTour(_unsafe_message(first_violation, retries))
        budget -= float(-slack.min()) + 1.0
        retries += 1
    o2 = used / 1000.0 / KJ_PER_LITER_O2
    rows_p, cols_p = g.cell(path)
    x, y = g.cell_to_xy(rows_p, cols_p)
    visit = [str(st.id[k]) for k in sol.route[1:-1]]
    wh = lambda a: [round(float(v) / J_PER_WH, 4) for v in a]   # noqa: E731
    line = {"type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[float(a), float(b)] for a, b in zip(x, y)]},
            "properties": {
                "kind": "route", "approach": "E5_orienteering_on_E4",
                "feasible": True, "first_violation": None, "walkback_retries": retries,
                "energy_wh": round(float(used[-1]) / J_PER_WH, 3), "time_s": round(float(t[-1]), 1),
                "length_m": round(float(wb["length_m"][-1]), 1), "o2_l": round(float(o2[-1]), 2),
                "usable_wh": round(usable_j / J_PER_WH, 3), "prize": float(sol.prize),
                "visit_order": visit, "stop_index": [int(i) for i in stop_index[1:-1]],
                "turn_index": int(stop_index[-2]) if len(stop_index) > 2 else None,
                "used_wh": wh(used), "rv_wh": wh(rv), "slack_wh": wh(slack),
                "t_s": [round(float(v), 1) for v in t],
                "rv_time_s": [round(float(v), 1) for v in rv_t[path]],
                "o2_used_l": [round(float(v), 3) for v in o2],
                "solver": sol.solver, "solver_runtime_s": round(sol.runtime_s, 3)}}
    start = {"type": "Feature", "geometry": {"type": "Point", "coordinates": [hx, hy]},
             "properties": {"kind": "start", "requested": list(req.start), "moved_m": h_moved}}
    info = {"engine": "api/tour.py on E5 primitives", "cost_model": g.cost_model,
            "habitat_moved_m": h_moved, "visit_order": visit, "prize": float(sol.prize),
            "stations_considered": len(keep), "service_power_w": service_power_w,
            "moved": moved, "walkback_retries": retries,
            "warnings": [f"walkback: re-planned {retries} time(s) with a lower budget"] if retries else []}
    return {"type": "FeatureCollection", "features": [line, start]}, info
