"""
E5 entry point: stations + E4 grid graph (E3 costs) -> station-to-station matrix -> solver.

    python src/orienteering/run.py --habitat X Y [--stations A.gpkg B.gpkg] [--solver auto]
                                   [--budget-wh 1000] [--margin 0.1]
"""
import argparse
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.build_rv import SERVICE_POWER_W  # noqa: E402
from grafos.walkback import J_PER_WH  # noqa: E402

from orienteering.data_io import (ROUTE_PATH, STATIONS_LAYER, STATIONS_PATH,  # noqa: E402
                                  read_station_files, write_route_gpkg)
from orienteering.network import (load_graph, place_habitat, reachable_stations,  # noqa: E402
                                  route_path, station_matrices)
from orienteering.problem import Problem, evaluate_route  # noqa: E402
from orienteering.safety import (return_costs, solve_with_walkback, stop_energy,  # noqa: E402
                                 tour_walkback)
from orienteering.solvers import MAX_STATIONS, SOLVERS, cpsat, pick, routing  # noqa: E402


def main(argv=None):
    ap = argparse.ArgumentParser(description="E5 orienteering over the E3 energy cost")
    ap.add_argument("--habitat", type=float, nargs=2, metavar=("X", "Y"), required=True,
                    help="habitat position, metres in the DEM's CRS (same input as E4)")
    ap.add_argument("--stations", nargs="+", default=[STATIONS_PATH],
                    help="GeoPackage(s) with the stations, merged in order (e.g. manual + E8)")
    ap.add_argument("--layer", default=STATIONS_LAYER)
    ap.add_argument("--prize-col", default="score")
    ap.add_argument("--budget-wh", type=float, default=1000.0, help="energy budget (same as E4)")
    ap.add_argument("--margin", type=float, default=0.10, help="reserve kept out of the budget (same as E4)")
    ap.add_argument("--service-power-w", type=float, default=SERVICE_POWER_W,
                    help="metabolic power while working at a station (same default as E4; proposed in #2)")
    ap.add_argument("--max-duration-min", type=float, default=None,
                    help="maximum EVA duration, back at the habitat (default: no limit; same flag as E4)")
    ap.add_argument("--wait-power-w", type=float, default=0.0,
                    help="metabolic power while waiting for a time window (default 0: waiting costs no energy)")
    ap.add_argument("--human-cost", action="store_true",
                    help="E3 x E1 sand price, the cost /plan uses (needs releases e1-sand-v1 and e8-v0)")
    ap.add_argument("--solver", choices=["auto", *sorted(SOLVERS)], default="auto",
                    help="auto: the DP up to its 20 nodes, OR-Tools CP-SAT above")
    ap.add_argument("--time-limit-s", type=float, default=None,
                    help=f"search limit of the OR-Tools solvers (default {cpsat.TIME_LIMIT_S:g} s for "
                         f"cpsat, which stops earlier once optimal; {routing.TIME_LIMIT_S:g} s for routing)")
    ap.add_argument("--light-sol", type=int, default=None,
                    help="time windows from the light on this Curiosity sol (#111): each station is "
                         "served only while it is in sunlight; sweeps the departure time and plans "
                         "the best one (replaces windows read from the stations file)")
    ap.add_argument("--depart-from", type=float, default=5.0, help="earliest departure, local true solar time")
    ap.add_argument("--depart-to", type=float, default=19.0, help="latest departure")
    ap.add_argument("--depart-step-min", type=float, default=15.0)
    ap.add_argument("--out", default=ROUTE_PATH, help="GeoPackage for the route (layers route and stops)")
    args = ap.parse_args(argv)
    t0 = time.time()

    try:
        graph, main_cc = load_graph(human=args.human_cost)
    except FileNotFoundError as err:
        raise SystemExit(f"error: {err}")
    print(f"cost model: {graph.cost_model}")
    stations = read_station_files(graph, args.stations, layer=args.layer, prize_col=args.prize_col)

    try:
        hr, hc, moved = place_habitat(graph, args.habitat)
    except ValueError as err:
        raise SystemExit(f"error: {err}")
    if moved > 0:
        print(f"warning: habitat {list(args.habitat)} is on a blocked cell or outside the main "
              f"connected area; moved {moved:.1f} m to cell ({hr}, {hc})")
    hx, hy = (float(v) for v in graph.cell_to_xy(hr, hc))
    stations = stations.prepend("habitat", "habitat", hx, hy, hr, hc)

    ok = reachable_stations(main_cc, stations)
    if not ok.all():
        print(f"dropping stations outside the main connected area: {stations.id[~ok].tolist()}")
        stations = stations.subset(ok)
    if args.solver == "auto":
        args.solver = pick(len(stations))
    limit = MAX_STATIONS[args.solver]
    if len(stations) > limit:
        raise SystemExit(f"{len(stations)} stations: solver {args.solver} supports up to {limit}, select fewer")

    dis, tim = station_matrices(graph, stations)
    budget_j = args.budget_wh * (1 - args.margin) * J_PER_WH
    max_duration_s = args.max_duration_min * 60.0 if args.max_duration_min is not None else None
    if stations.windows is not None:
        print(f"time windows on {int((np.isfinite(stations.windows[:, 1]) | (stations.windows[:, 0] > 0)).sum())} stations")

    service_j = stations.service_s * args.service_power_w
    problem = Problem(energy=dis, prize=stations.prize, budget=budget_j, time=tim,
                      service_s=stations.service_s, service_j=service_j,
                      windows=stations.windows, max_duration_s=max_duration_s,
                      wait_power_w=args.wait_power_w)
    if args.light_sol is not None:
        stations, problem, dis = light_windows_plan(graph, stations, problem, args)
    rv_j = return_costs(graph, graph.node(hr, hc))
    checked = {}

    def check(route):
        path, stop_index = route_path(graph, stations, route, dis)
        checked[tuple(route)] = (path, stop_index)
        return tour_walkback(graph, path, stop_index, stop_energy(problem, route), rv_j, budget_j)

    try:
        solve = SOLVERS[args.solver]
        if args.solver in ("cpsat", "routing") and args.time_limit_s is not None:
            solve = lambda p: SOLVERS[args.solver](p, args.time_limit_s)  # noqa: E731
        solution, walkback, retries = solve_with_walkback(problem, solve, check)
    except (ValueError, NotImplementedError) as err:
        raise SystemExit(f"solver {args.solver}: {err}")

    served_j = sum(service_j[k] for k in set(solution.route))
    waited_j = sum(stop_energy(problem, solution.route)) - served_j if solution.route else 0.0
    print(f"{len(stations)} stations, usable budget {budget_j / J_PER_WH:.0f} Wh, solver {solution.solver} "
          f"({solution.runtime_s:.2f} s), total {time.time() - t0:.1f} s")
    if solution.bound is not None:
        print(f"optimal: {solution.optimal}; best bound on the prize {solution.bound:g}")
    print(f"habitat at ({hx:.1f}, {hy:.1f}); prize {solution.prize:g}, "
          f"spent {solution.energy / J_PER_WH:.1f} Wh "
          f"(walking {(solution.energy - served_j - waited_j) / J_PER_WH:.1f}, service {served_j / J_PER_WH:.1f} "
          f"at {args.service_power_w:g} W, waiting {waited_j / J_PER_WH:.1f} at {args.wait_power_w:g} W)")
    for k in solution.route:
        print(f"  {stations.id[k]:>8} ({stations.type[k]}): x={stations.x[k]:.1f} "
              f"y={stations.y[k]:.1f} prize={stations.prize[k]:g}")

    if not solution.route:
        print("no route fits in the budget, windows and duration: nothing written")
        return solution
    timeline = evaluate_route(problem, solution.route)
    wait_s = float((timeline["begin"] - timeline["arrival"]).sum())
    served_s = sum(stations.service_s[k] for k in set(solution.route))
    print(f"duration {timeline['duration'] / 60:.0f} min (walking {(timeline['duration'] - served_s - wait_s) / 60:.0f}, "
          f"service {served_s / 60:.0f}, waiting {wait_s / 60:.0f})")

    if walkback["feasible"]:
        print(f"walkback ok: smallest slack {walkback['min_slack_j'] / J_PER_WH:.1f} Wh"
              + (f" (after {retries} re-plans)" if retries else ""))
    else:
        bad = stations.id[solution.route[walkback["first_violation_stop"]]]
        print(f"WARNING: walkback fails before reaching {bad} (slack {walkback['min_slack_j'] / J_PER_WH:.1f} Wh) "
              f"after {retries} re-plans")

    path, stop_index = checked[tuple(solution.route)]
    out = write_route_gpkg(args.out, graph, stations, solution, path, stop_index, budget_j,
                           args.service_power_w, timeline, walkback, args.wait_power_w)
    print(f"route written to {out} ({len(path)} cells, {time.time() - t0:.1f} s total)")
    return solution


"""
--light-sol: sweeps the departures, prints one line per departure, and returns the
stations and the problem of the best one (windows from the light, stations without
light for their service dropped), so the rest of run.py plans, checks the walkback and
writes the route as usual.
"""
def light_windows_plan(graph, stations, problem, args):
    from orienteering import departure as dep
    from orienteering import light_windows as lw

    dem, transform = dep.load_dem()
    starts = np.arange(args.depart_from, args.depart_to + 1e-9, args.depart_step_min / 60.0)
    t_s = time.time()
    rows, best = lw.sweep(graph, stations, problem, args.light_sol, starts, dem, transform,
                          solver=None if args.solver == "auto" else args.solver)
    print(f"time windows from the light, sol {args.light_sol}: {len(rows)} departures in "
          f"{time.time() - t_s:.1f} s (prize, stations served, dropped for lack of light)")
    for r in rows:
        mark = "  <- best" if r is best else ""
        print(f"  {dep.clock(r['start_ltst_h'])}  prize {r['prize']:g}  {len(set(r['route'])) - 1} stations"
              + (f"  dropped {r['dropped']}" if r["dropped"] else "") + mark)
    share = best["walk_sunlit_share"]
    print(f"best departure {dep.clock(best['start_ltst_h'])} local true solar time"
          + (f" ({100 * share:.1f} % of the walk in sunlight)" if share is not None else ""))
    keep = np.flatnonzero(~np.isin(stations.id, best["dropped"]))
    windows = np.asarray(best["windows_s"])[keep]
    stations = stations.subset(keep)
    stations.windows = windows
    dis = problem.energy[np.ix_(keep, keep)]
    problem = Problem(energy=dis, prize=problem.prize[keep], budget=problem.budget,
                      time=problem.time[np.ix_(keep, keep)], service_s=problem.service_s[keep],
                      service_j=problem.service_j[keep], windows=windows,
                      max_duration_s=problem.max_duration_s, wait_power_w=problem.wait_power_w)
    return stations, problem, dis


if __name__ == "__main__":
    main()
