"""
E5 for POST /plan: the full station tour, in the same shape as E4's live plan
(api/planner.plan), so /plan and the HUD can use either without changes.

    fc, info = plan_tour(req, graph)

req is api.plan.PlanRequest (start, stations[id, x, y, type, score, service_time_min],
energy_budget_wh, margin, service_energy_wh_per_min, max_duration_min, o2_budget_l);
graph is the grafos Graph /plan already built (api.planner.graph, with the user's cell
block). Raises ValueError (bad input) or grafos.labels.NoFeasibleRoute (no station fits),
the same exceptions /plan already turns into 422. Both carry a structured reason in
.diagnosis (diagnose.TourInputError and diagnose.NoTourFound, #119 A4): code, exact,
message, and the limiting station, resource, need and availability when they can be computed.

Hook in api/planner.plan (Sebas's file), before the E4 single-goal round trip:
    if req.stations and req.goal is None:
        from orienteering.tour import plan_tour
        return plan_tour(req, g)
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.build_rv import SERVICE_POWER_W  # noqa: E402
from grafos.labels import KJ_PER_LITER_O2  # noqa: E402
from grafos.walkback import J_PER_WH  # noqa: E402

from orienteering import diagnose  # noqa: E402
from orienteering.data_io import Stations  # noqa: E402
from orienteering.network import route_path, station_matrices  # noqa: E402
from orienteering.problem import Problem, evaluate_route  # noqa: E402
from orienteering.safety import (return_costs, solve_with_walkback, stop_energy,  # noqa: E402
                                 tour_walkback)
from orienteering.solvers import EXACT, MAX_STATIONS, SOLVERS, pick  # noqa: E402
from orienteering.solvers.cpsat import TIME_LIMIT_S as CPSAT_TIME_LIMIT_S  # noqa: E402

J_PER_LITER_O2 = KJ_PER_LITER_O2 * 1000.0


"""
Plans the E5 tour habitat -> stations -> habitat for a /plan request on `graph`.
Limits: usable energy (budget minus margin), max_duration_min and o2_budget_l. With no
O2 leak (the /plan contract has none) O2 is energy / 20.1 kJ/L, so the O2 limit is
applied as a second energy limit and the tighter one is used.
Habitat and stations are placed with graph.place, like the E4 goal in /plan.
solver: "auto" uses the DP up to 19 stations and OR-Tools CP-SAT above (exact model,
search capped at 30 s); or a name of solvers.SOLVERS.
Returns (FeatureCollection, info):
    route feature (kind "route", approach "E5_tour"): E4's per-vertex profile (used_wh,
        rv_wh, slack_wh, t_s, rv_time_s, o2_used_l, same order as the coordinates; used
        and t include service and waits), totals, prize, order (station ids), stop_index
        (position of each stop in the coordinates), feasible (walkback), exact (optimum
        proven and no walkback re-plan), min_slack_wh and min_slack_index (smallest
        return margin along the line, service and waits included, and its vertex),
        diagnosis (only when feasible is False: diagnose.walkback_failure)
    start point (kind "start") and one point per stop (kind "stop") in visiting order
    info: habitat_moved_m, goal_moved_m (0), goal_station (None), service_power_w,
        prize, order, skipped (station ids not visited), skipped_reasons (per skipped id:
        diagnose.skipped), walkback_retries, warnings, diagnosis (as in the route)
"""
def plan_tour(req, graph, solver="auto"):
    usable_j = req.energy_budget_wh * (1 - req.margin) * J_PER_WH
    energy_limit_j = usable_j
    if req.o2_budget_l is not None:
        energy_limit_j = min(usable_j, req.o2_budget_l * J_PER_LITER_O2)
    service_w = (req.service_energy_wh_per_min * 60.0 if req.service_energy_wh_per_min is not None
                 else SERVICE_POWER_W)
    max_duration_s = req.max_duration_min * 60.0 if req.max_duration_min is not None else None
    if not req.stations:
        raise diagnose.TourInputError("add a station to plan an E5 tour", "stations")
    if solver == "auto":
        solver = pick(len(req.stations) + 1)
    if len(req.stations) + 1 > MAX_STATIONS[solver]:
        raise diagnose.TourInputError(f"{len(req.stations)} stations: the E5 {solver} supports up to "
                                      f"{MAX_STATIONS[solver] - 1} plus the habitat", "stations")

    stations, moved, requested = place_stations(req, graph)
    lim = diagnose.limits(usable_j, req.o2_budget_l, max_duration_s, req.margin)
    dis, tim = station_matrices(graph, stations)
    service_j = stations.service_s * service_w
    problem = Problem(energy=dis, prize=stations.prize, budget=energy_limit_j, time=tim,
                      service_s=stations.service_s, service_j=service_j,
                      max_duration_s=max_duration_s)

    habitat = int(graph.node(stations.row[0], stations.col[0]))
    rv_j = return_costs(graph, habitat)
    checked = {}

    def check(route):
        path, stop_index = route_path(graph, stations, route, dis)
        checked[tuple(route)] = (path, stop_index)
        return tour_walkback(graph, path, stop_index, stop_energy(problem, route), rv_j,
                             energy_limit_j)

    solution, walkback, retries = solve_with_walkback(problem, SOLVERS[solver], check)
    if not solution.route or len(set(solution.route)) == 1:
        raise diagnose.NoTourFound(diagnose.no_tour(
            problem, stations.id, lim, solution, solver,
            CPSAT_TIME_LIMIT_S if solver == "cpsat" else None))

    route = solution.route
    path, stop_index = checked[tuple(route)]
    timeline = evaluate_route(problem, route)

    walk_t = graph.path_cost(path, "time_s")
    extra_t = np.zeros(len(path))
    for m, at in enumerate(stop_index):
        extra_t[at:] += timeline["depart"][m] - timeline["arrival"][m]
    t_s = walk_t + extra_t
    rv_time_s = graph.costs_to(habitat, "time_s")[path]
    o2_l = walkback["used_j"] / J_PER_LITER_O2
    wh = lambda a: [round(float(v) / J_PER_WH, 4) for v in a]  # noqa: E731

    rows, cols = graph.cell(path)
    xs, ys = graph.cell_to_xy(rows, cols)
    order = [str(stations.id[k]) for k in route]
    visited = set(route)
    skipped = [str(stations.id[k]) for k in range(1, len(stations)) if k not in visited]

    exact = retries == 0 and (solver in EXACT or bool(solution.optimal))
    diagnosis = None if walkback["feasible"] else diagnose.walkback_failure(walkback, retries, lim)
    skipped_reasons = diagnose.skipped(problem, stations.id, lim, route, exact)

    warnings = []
    if req.o2_budget_l is not None and energy_limit_j < usable_j:
        warnings.append(f"O2 budget is the tighter limit: {energy_limit_j / J_PER_WH:.0f} Wh of "
                        f"{usable_j / J_PER_WH:.0f} usable")
    if retries:
        warnings.append(f"walkback: re-planned {retries} time(s) with a lower budget")
    for k in range(1, len(stations)):
        if moved[k] > 0:
            warnings.append(f"station {stations.id[k]} moved {moved[k]:.1f} m to the nearest "
                            "walkable cell of the main connected area")

    line = {"type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[float(a), float(b)] for a, b in zip(xs, ys)]},
            "properties": {
                "kind": "route", "approach": "E5_tour",
                "feasible": bool(walkback["feasible"]),
                "first_violation": walkback["first_violation"],
                "turn_index": None,
                "energy_wh": round(float(walkback["used_j"][-1]) / J_PER_WH, 3),
                "time_s": round(float(t_s[-1]), 1),
                "length_m": round(float(walkback["length_m"][-1]), 1),
                "o2_l": round(float(o2_l[-1]), 2),
                "method": solution.solver,
                "exact": exact,
                "gap": (round((solution.bound - solution.prize) / solution.bound, 4)
                        if solution.bound else None),
                "usable_wh": round(energy_limit_j / J_PER_WH, 3),
                "prize": float(solution.prize), "order": order,
                "stop_index": [int(v) for v in stop_index],
                "service_power_w": float(service_w),
                "used_wh": wh(walkback["used_j"]), "rv_wh": wh(walkback["rv_j"]),
                "slack_wh": wh(walkback["slack_j"]),
                "min_slack_wh": round(float(walkback["min_slack_j"]) / J_PER_WH, 4),
                "min_slack_index": int(np.argmin(walkback["slack_j"])),
                "diagnosis": diagnosis,
                "t_s": [round(float(v), 1) for v in t_s],
                "rv_time_s": [round(float(v), 1) for v in rv_time_s],
                "o2_used_l": [round(float(v), 3) for v in o2_l],
                "budget_wh": req.energy_budget_wh, "margin": req.margin,
                "max_duration_min": req.max_duration_min, "o2_budget_l": req.o2_budget_l}}

    start = {"type": "Feature",
             "geometry": {"type": "Point", "coordinates": [float(stations.x[0]), float(stations.y[0])]},
             "properties": {"kind": "start", "requested": list(req.start), "moved_m": moved[0]}}

    stops = []
    for m, k in enumerate(route):
        if m == 0 or (k == 0 and m == len(route) - 1):
            continue
        at = stop_index[m]
        stops.append({"type": "Feature",
                      "geometry": {"type": "Point",
                                   "coordinates": [float(stations.x[k]), float(stations.y[k])]},
                      "properties": {
                          "kind": "stop", "order": m, "id": str(stations.id[k]),
                          "type": str(stations.type[k]), "score": float(stations.prize[k]),
                          "service_time_min": float(stations.service_s[k]) / 60.0,
                          "arrival_time_s": round(float(timeline["arrival"][m]), 1),
                          "wait_s": round(float(timeline["begin"][m] - timeline["arrival"][m]), 1),
                          "departure_time_s": round(float(timeline["depart"][m]), 1),
                          "energy_wh": round(float(walkback["used_j"][at]) / J_PER_WH, 3),
                          "slack_wh": round(float(walkback["stop_slack_j"][m]) / J_PER_WH, 3),
                          "requested": requested[k], "moved_m": moved[k]}})

    fc = {"type": "FeatureCollection",
          "crs": {"type": "name", "properties": {"name": graph.crs_wkt}},
          "features": [line, start] + stops}
    info = {"habitat_moved_m": moved[0], "goal_moved_m": 0.0, "goal_station": None,
            "service_power_w": float(service_w), "prize": float(solution.prize),
            "order": order, "skipped": skipped, "skipped_reasons": skipped_reasons,
            "walkback_retries": retries, "warnings": warnings, "diagnosis": diagnosis}
    return fc, info


"""
Habitat (station 0) and the request's stations placed on `graph` with graph.place.
Returns (Stations at the placed cell centres, moved_m per station, requested [x, y]).
"""
def place_stations(req, graph):
    points = [("habitat", "habitat", req.start[0], req.start[1], 0.0, 0.0)]
    points += [(s.id, s.type or "", s.x, s.y, s.score, s.service_time_min * 60.0)
               for s in req.stations]
    ids, types, xs, ys, rows, cols, prizes, service, moved, requested = ([] for _ in range(10))
    for k, (sid, stype, x, y, score, service_s) in enumerate(points):
        try:
            r, c, m = graph.place(x, y, label="habitat" if sid == "habitat" else f"station {sid}")
        except ValueError as err:
            raise diagnose.TourInputError(str(err), "start" if k == 0 else f"stations[{k - 1}]") from err
        cx, cy = graph.cell_to_xy(r, c)
        ids.append(sid), types.append(stype), xs.append(float(cx)), ys.append(float(cy))
        rows.append(r), cols.append(c), prizes.append(float(score)), service.append(float(service_s))
        moved.append(float(m)), requested.append([float(x), float(y)])
    stations = Stations(np.array(ids), np.array(types), np.array(xs), np.array(ys),
                        np.array(rows), np.array(cols), np.array(prizes), np.array(service))
    return stations, moved, requested
