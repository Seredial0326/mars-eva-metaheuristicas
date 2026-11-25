"""
Real time windows from the light (issue #111): each station's window is the stretch of
time in which it is in sunlight and out of the terrain's shadow, so E5 solves a true
orienteering problem with time windows (OPTW) and the light changes which stations are
chosen, not only the departure time (P6, departure.py).

For a departure t0 (local true solar time on a Curiosity sol):
    1. every station is sampled every STEP_S seconds after t0, and each sample is dark,
       shadowed or sunlit by the rule of departure.light_state, with the station's own
       terrain horizon (departure.horizon_table at the station, 1.7 m eye height);
    2. the sunlit samples form intervals; the station's window is the longest one with
       room for its service, as [open, close - service] in seconds after t0, because the
       work must also be done in the light. The DP takes one window per station, so a
       station that is lit, shadowed, then lit again keeps only its longest stretch;
    3. a station with no stretch long enough for its service is dropped for that departure.
Windows end at the sol's local midnight: an EVA belongs to its sol, so the next morning's
light never counts (otherwise a tour with no duration limit could wait overnight).
The habitat has no window. Walking between stations is not limited by the light; how much
of the walk is sunlit is reported, as P6 does.

sweep() repeats this for each candidate departure, solves each OPTW with E5's solver
(DP up to 20 nodes, CP-SAT above) and recommends the departure with the largest prize,
ties broken as P6 does: the larger sunlit share of the walk, then the higher lowest Sun,
then the earliest.

The Sun is computed at the habitat for all stations (the box is 2 km across: the Sun's
position changes by about 0.03 degrees across it).
"""
import time

import numpy as np

from orienteering import departure as dep
from orienteering.network import route_path
from orienteering.problem import Problem, evaluate_route
from orienteering.solvers import MAX_STATIONS, SOLVERS, pick

STEP_S = 60.0                 # light sampled every minute


def station_horizons(stations, dem, transform):
    """Terrain horizon (departure.horizon_table rows) at every station, habitat included."""
    return dep.horizon_table(np.column_stack([stations.x, stations.y]), dem, transform)


def site(stations):
    """Planetographic latitude and longitude east of the habitat (station 0)."""
    lon, lat = dep.lon_lat(float(stations.x[0]), float(stations.y[0]))
    return dep.planetographic_latitude(lat), lon


def seconds_to_midnight(t0_ltst):
    """Seconds from a departure at t0 (local true solar time) to the end of its sol."""
    return (24.0 - float(t0_ltst)) / 24.0 * dep.SOL_IN_SECONDS


def light_profile(horizons, sol, t0_ltst, lat_pg, lon_east, span_s=None, step_s=STEP_S):
    """(times, states): sample times in seconds after the departure, up to span_s
    (default: the sol's local midnight), and an (n, samples) array of light states
    (0 dark, 1 shadowed, 2 sunlit) for each station."""
    span_s = seconds_to_midnight(t0_ltst) if span_s is None else span_s
    times = np.arange(0.0, span_s + step_s / 2, step_s)
    utc0 = dep.utc_of_true_solar_time(sol, t0_ltst, lon_east)
    sun = dep.sun_position(utc0 + times * 1000.0, lat_pg, lon_east, tt=dep.tt_minus_utc(utc0))
    states = np.vstack([dep.light_state(sun["elevation"], sun["azimuth"], np.repeat(h[None], len(times), 0))
                        for h in horizons])
    return times, states


def sunlit_intervals(times, lit):
    """[(start_s, end_s), ...] of the runs of True in lit (sample times)."""
    out, start = [], None
    for t, on in zip(times, lit):
        if on and start is None:
            start = t
        elif not on and start is not None:
            out.append((float(start), float(prev)))
            start = None
        prev = t
    if start is not None:
        out.append((float(start), float(times[-1])))
    return out


def windows_from_light(times, states, service_s):
    """(windows, ok, n_intervals): windows (n, 2) in seconds after the departure, ok the
    stations that keep one, and how many sunlit stretches each has. Station 0 (habitat)
    is always [0, inf]."""
    n = len(states)
    windows = np.tile([0.0, np.inf], (n, 1))
    ok = np.ones(n, dtype=bool)
    n_intervals = np.zeros(n, dtype=int)
    for k in range(1, n):
        spans = sunlit_intervals(times, states[k] == 2)
        n_intervals[k] = len(spans)
        fits = [(e - s - service_s[k], s, e) for s, e in spans if e - s >= service_s[k]]
        if not fits:
            ok[k] = False
            windows[k] = [0.0, -1.0]
            continue
        _, s, e = max(fits)
        windows[k] = [s, e - service_s[k]]
    return windows, ok, n_intervals


def shadow_minutes(horizons, sol, lat_pg, lon_east, step_s=STEP_S):
    """Minutes of the sol's daylight (Sun above a smooth horizon) that each station
    spends in the terrain's shadow. A station with more than 0 has a window that the
    terrain restricts, whatever the departure."""
    times, states = light_profile(horizons, sol, 0.0, lat_pg, lon_east,
                                  span_s=dep.SOL_IN_SECONDS, step_s=step_s)
    return (states == 1).sum(axis=1) * step_s / 60.0


def solve_with_windows(base, windows, ok, solver=None):
    """Solves base (a Problem over all stations) with these windows, without the
    stations that lost theirs. Returns (Solution with routes in base's indices, kept)."""
    keep = np.flatnonzero(ok)
    sub = Problem(energy=base.energy[np.ix_(keep, keep)], prize=base.prize[keep], budget=base.budget,
                  start=0, end=0, time=base.time[np.ix_(keep, keep)],
                  service_s=None if base.service_s is None else base.service_s[keep],
                  service_j=None if base.service_j is None else base.service_j[keep],
                  windows=windows[keep], max_duration_s=base.max_duration_s,
                  wait_power_w=base.wait_power_w)
    name = solver or pick(sub.n)
    if sub.n > MAX_STATIONS[name]:
        raise ValueError(f"{sub.n} nodes: solver {name} supports up to {MAX_STATIONS[name]}")
    sol = SOLVERS[name](sub)
    sol.route = [int(keep[k]) for k in sol.route]
    return sol, keep


def walk_clock(graph, path, stop_index, timeline):
    """Seconds since leaving at every vertex of the walked path, waits and service
    included (the same construction as tour.plan_tour's t_s)."""
    t_s = np.asarray(graph.path_cost(path, "time_s"), dtype=float).copy()
    for m, at in enumerate(stop_index):
        t_s[at:] += timeline["depart"][m] - timeline["arrival"][m]
    return t_s


def tour_light(graph, stations, base, route, sol, t0_ltst, dem, transform, windows=None):
    """(walk sunlit share, lowest Sun elevation during the walk, service sunlit share)
    for a route walked from departure t0: the first two are P6's criteria (time-weighted
    share of the walk in sunlight, and its lowest Sun), the third the consistency check.
    windows: the ones the route was solved with, so the schedule has the same waits."""
    if len(route) < 2:
        return 1.0, 90.0, 1.0
    problem = Problem(energy=base.energy, prize=base.prize, budget=base.budget, time=base.time,
                      service_s=base.service_s, service_j=base.service_j, windows=windows,
                      wait_power_w=base.wait_power_w)
    path, stop_index = route_path(graph, stations, route, base.energy)
    timeline = evaluate_route(problem, route)
    t_s = walk_clock(graph, path, stop_index, timeline)
    rows, cols = graph.cell(path)
    xy = np.column_stack(graph.cell_to_xy(rows, cols))
    horizon = dep.horizon_table(xy, dem, transform)
    lat_pg, lon = site(stations)
    elev, _, state, _, _ = dep.light_along(xy, t_s, sol, t0_ltst, horizon, lat_pg, lon)
    weight = np.r_[np.diff(t_s), 0.0]
    walk_share = float(weight[state == 2].sum() / max(weight.sum(), 1e-9))
    return (walk_share, float(np.min(elev)),
            service_light_share(stations, base, route, timeline, sol, t0_ltst, dem, transform))


def service_light_share(stations, base, route, timeline, sol, t0_ltst, dem, transform, step_s=30.0):
    """Share of the service time at the stops spent in sunlight, sampled every step_s
    seconds with each stop's own horizon: 1.0 when every window holds (consistency check
    against P6's light rule)."""
    stops = [(m, k) for m, k in enumerate(route) if base.service_s is not None and base.service_s[k] > 0
             and k not in route[:m]]
    if not stops:
        return 1.0
    lat_pg, lon = site(stations)
    utc0 = dep.utc_of_true_solar_time(sol, t0_ltst, lon)
    lit = total = 0
    for m, k in stops:
        t = np.arange(timeline["begin"][m], timeline["depart"][m] + 1e-9, step_s)
        sun = dep.sun_position(utc0 + t * 1000.0, lat_pg, lon, tt=dep.tt_minus_utc(utc0))
        h = dep.horizon_table([(stations.x[k], stations.y[k])], dem, transform)
        state = dep.light_state(sun["elevation"], sun["azimuth"], np.repeat(h, len(t), 0))
        lit += int((state == 2).sum())
        total += len(t)
    return lit / total


def sweep(graph, stations, base, sol, starts_ltst, dem, transform, solver=None, light_ties=True):
    """One row per departure: stations with a window, the OPTW solution and its prize;
    plus the recommended row. base: the Problem without windows (all stations, start and
    end at the habitat). With light_ties, the departures tied at the best prize also get
    the sunlit share of their walk (P6) to break the tie."""
    horizons = station_horizons(stations, dem, transform)
    lat_pg, lon = site(stations)
    rows = []
    for t0 in starts_ltst:
        t_start = time.perf_counter()
        times, states = light_profile(horizons, sol, t0, lat_pg, lon)
        windows, ok, n_int = windows_from_light(times, states, np.asarray(base.service_s, dtype=float))
        sol_t, _ = solve_with_windows(base, windows, ok, solver)
        rows.append({"start_ltst_h": round(float(t0), 3), "stations_with_window": int(ok[1:].sum()),
                     "dropped": [str(stations.id[k]) for k in np.flatnonzero(~ok)],
                     "split_light": [str(stations.id[k]) for k in np.flatnonzero(n_int > 1)],
                     "route": sol_t.route, "order": [str(stations.id[k]) for k in sol_t.route],
                     "prize": float(sol_t.prize), "energy_j": float(sol_t.energy),
                     "duration_s": None if sol_t.duration_s is None else float(sol_t.duration_s),
                     "solver": sol_t.solver, "solve_s": round(time.perf_counter() - t_start, 3),
                     "windows_s": windows.tolist(), "walk_sunlit_share": None,
                     "walk_min_sun_elevation_deg": None, "service_sunlit_share": None})
    top = max(r["prize"] for r in rows)
    tied = [r for r in rows if abs(r["prize"] - top) < 1e-9]
    if light_ties and len(tied) > 1:
        for r in tied:
            (r["walk_sunlit_share"], r["walk_min_sun_elevation_deg"],
             r["service_sunlit_share"]) = tour_light(graph, stations, base, r["route"], sol,
                                                     r["start_ltst_h"], dem, transform,
                                                     np.asarray(r["windows_s"]))
    best = max(tied, key=lambda r: (r["walk_sunlit_share"] or 0.0, r["walk_min_sun_elevation_deg"] or -90.0,
                                    -r["start_ltst_h"]))
    return rows, best
