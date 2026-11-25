"""
Heuristic orienteering solver with Google OR-Tools' routing library. Not exact: guided
local search runs until the time limit and returns the best tour found. It misses the
optimum on tight energy budgets (data/e5/summary_ortools.json), so cpsat is the solver
used beyond the DP; this one is kept for comparison.

On Windows the pip build of OR-Tools and conda-forge's pyarrow (loaded by pandas 3) ship
DLLs with the same names (abseil, protobuf), and whichever loads second fails. So when
pyarrow is installed, the search runs in a fresh Python process that never imports pandas;
it costs about 0.2 s per solve.
"""
import importlib
import importlib.util
import math
import os
import pickle
import subprocess
import sys
import time
from pathlib import Path

import numpy as np

from orienteering.problem import Solution, evaluate_route

MAX_STATIONS = 200
TIME_LIMIT_S = 10.0
ENERGY_UNITS = 1e7           # the budget is mapped to this many integer units
TIME_UNITS_PER_S = 100       # time resolution of 0.01 s
PRIZE_UNITS = 100            # prize resolution of 0.01 points
METAHEURISTIC = "GUIDED_LOCAL_SEARCH"
LNS = True                   # large-neighbourhood moves that swap several stations at once


"""
Solves the problem as a single-vehicle routing model from start to end:
    - every other station is optional (a disjunction); skipping it costs its prize, scaled
      above any feasible route's energy, so the model maximises the prize first and, among
      equal prizes, minimises the energy (the same order as the DP)
    - energy dimension: leg energy plus the service of the arrival station, capacity the
      budget minus the start's service
    - time dimension (only when the problem is timed): leg time plus the service of the
      departure station; slack is the wait for a window; each station's cumul (start of
      service) lies in its window, the end's within max_duration_s
Integer costs are rounded up and limits down, so every tour the model accepts also holds
with the exact values; the returned tour is re-checked with problem.evaluate_route.
Waiting energy (problem.wait_power_w > 0) is not modelled: use the DP.
    time_limit_s : search time (default TIME_LIMIT_S); the search always runs until it
    metaheuristic : OR-Tools LocalSearchMetaheuristic name
    lns : enable the path and inactive-node LNS operators
"""
def solve(problem, time_limit_s=None, metaheuristic=METAHEURISTIC, lns=LNS):
    time_limit_s = TIME_LIMIT_S if time_limit_s is None else time_limit_s
    if problem.n > MAX_STATIONS:
        raise ValueError(f"the OR-Tools solver is limited to {MAX_STATIONS} stations, got {problem.n}")
    if problem.timed and problem.time is None:
        raise ValueError("time windows and max_duration_s need problem.time")
    if problem.wait_power_w:
        raise NotImplementedError("waiting energy is not modelled in the OR-Tools solver; use dp")
    return solve_isolated("orienteering.solvers.routing", "solve_here",
                          (problem, time_limit_s, metaheuristic, lns))


"""
True if OR-Tools can be loaded here without breaking or being broken by pyarrow.
"""
def in_process():
    if os.name != "nt" or "ortools" in sys.modules:
        return True
    return importlib.util.find_spec("pyarrow") is None


"""
Calls module.func(*args), here if in_process() allows it, otherwise in a fresh
interpreter (see the module docstring); arguments and result travel pickled through
stdin and stdout. Used by both OR-Tools solvers.
"""
def solve_isolated(module, func, args):
    if importlib.util.find_spec("ortools") is None:
        raise ImportError("the OR-Tools solvers need the ortools package (pip install ortools)")
    if in_process():
        return getattr(importlib.import_module(module), func)(*args)
    src = str(Path(__file__).resolve().parents[2])
    code = ("import sys; sys.path.insert(0, sys.argv[1]); "
            "from orienteering.solvers.routing import child_main; child_main()")
    done = subprocess.run([sys.executable, "-c", code, src], input=pickle.dumps((module, func, args)),
                          capture_output=True)
    if done.returncode != 0:
        raise RuntimeError("OR-Tools child process failed: " + done.stderr.decode(errors="replace"))
    return pickle.loads(done.stdout)


def child_main():
    module, func, args = pickle.loads(sys.stdin.buffer.read())
    result = getattr(importlib.import_module(module), func)(*args)
    sys.stdout.buffer.write(pickle.dumps(result))


def solve_here(problem, time_limit_s, metaheuristic, lns):
    from ortools.constraint_solver import pywrapcp, routing_enums_pb2
    from ortools.util.optional_boolean_pb2 import BOOL_TRUE

    t0 = time.perf_counter()
    n = problem.n
    start, end = problem.start, problem.end
    svc_j = problem.service_j if problem.service_j is not None else np.zeros(n)
    svc_s = problem.service_s if problem.service_s is not None else np.zeros(n)
    empty = Solution([], 0.0, 0.0, "routing", time.perf_counter() - t0)
    if problem.budget <= 0 or svc_j[start] > problem.budget:
        return empty

    scale = ENERGY_UNITS / problem.budget
    capacity = int(math.floor((problem.budget - svc_j[start]) * scale))
    on_arrival = np.where(np.arange(n) == start, 0.0, svc_j)
    leg_e = np.ceil((problem.energy + on_arrival[None, :]) * scale)
    leg_e = np.minimum(leg_e, capacity + 1).astype(np.int64)    # longer legs can't fit anyway
    np.fill_diagonal(leg_e, 0)

    manager = pywrapcp.RoutingIndexManager(n, 1, [start], [end])
    routing = pywrapcp.RoutingModel(manager)
    node = manager.IndexToNode

    energy_cb = routing.RegisterTransitMatrix(leg_e.tolist())
    routing.SetArcCostEvaluatorOfAllVehicles(energy_cb)
    routing.AddDimension(energy_cb, 0, capacity, True, "energy")

    skip_unit = capacity + 1                                    # one prize unit > any route's energy
    for k in range(n):
        if k not in (start, end):
            penalty = int(round(float(problem.prize[k]) * PRIZE_UNITS)) * skip_unit
            routing.AddDisjunction([manager.NodeToIndex(k)], penalty)

    if problem.timed and not add_time_dimension(problem, routing, manager, svc_s):
        empty.runtime_s = time.perf_counter() - t0
        return empty

    params = pywrapcp.DefaultRoutingSearchParameters()
    params.first_solution_strategy = routing_enums_pb2.FirstSolutionStrategy.PATH_CHEAPEST_ARC
    params.local_search_metaheuristic = getattr(routing_enums_pb2.LocalSearchMetaheuristic, metaheuristic)
    if lns:
        ops = params.local_search_operators
        ops.use_path_lns = ops.use_full_path_lns = ops.use_inactive_lns = BOOL_TRUE
    params.time_limit.FromMilliseconds(max(1, int(time_limit_s * 1000)))
    found = routing.SolveWithParameters(params)
    if found is None:
        empty.runtime_s = time.perf_counter() - t0
        return empty

    index, route = routing.Start(0), []
    while not routing.IsEnd(index):
        route.append(node(index))
        index = found.Value(routing.NextVar(index))
    route.append(node(index))

    result = evaluate_route(problem, route)
    runtime = time.perf_counter() - t0
    if result["energy"] > problem.budget + 1e-9 or not result["feasible"]:
        return Solution([], 0.0, 0.0, "routing", runtime)
    prize = float(sum(problem.prize[k] for k in set(route)))
    return Solution(route, prize, result["energy"], "routing", runtime, result["duration"])


"""
Time dimension: the cumul of a node is the start of its service (arrival plus the wait),
the transit of a leg i -> j is the service at i plus the walk to j. Service at the start
is paid when leaving it; the return to the start is not served again. Returns False if
the start or the end can never be within its window, in which case no tour exists.
"""
def add_time_dimension(problem, routing, manager, svc_s):
    n, start, end = problem.n, problem.start, problem.end
    windows = problem.windows if problem.windows is not None else np.tile([0.0, np.inf], (n, 1))
    walk = np.asarray(problem.time, dtype=float)
    finite = np.isfinite(walk)
    horizon_s = float(np.where(finite, walk, 0.0).max(axis=1).sum() + svc_s.sum()
                      + np.max(np.where(np.isfinite(windows[:, 0]), windows[:, 0], 0.0))
                      + 1.0 + n / TIME_UNITS_PER_S)           # room for rounding every leg up
    if problem.max_duration_s is not None:
        horizon_s = min(horizon_s, problem.max_duration_s)
    horizon = int(math.floor(horizon_s * TIME_UNITS_PER_S))

    leg_t = np.ceil((svc_s[:, None] + np.where(finite, walk, 0.0)) * TIME_UNITS_PER_S)
    leg_t = np.where(finite, np.minimum(leg_t, horizon + 1), horizon + 1).astype(np.int64)
    np.fill_diagonal(leg_t, 0)
    time_cb = routing.RegisterTransitMatrix(leg_t.tolist())
    routing.AddDimension(time_cb, horizon, horizon, False, "time")
    dim = routing.GetDimensionOrDie("time")

    def window(k, latest=horizon):
        lo = int(math.ceil(max(0.0, float(windows[k][0])) * TIME_UNITS_PER_S))
        hi = latest
        if np.isfinite(windows[k][1]):
            hi = min(hi, int(math.floor(float(windows[k][1]) * TIME_UNITS_PER_S)))
        return lo, hi

    for k in range(n):
        if k in (start, end):
            continue
        index = manager.NodeToIndex(k)
        lo, hi = window(k)
        if hi < lo:
            routing.solver().Add(routing.ActiveVar(index) == 0)
        else:
            dim.CumulVar(index).SetRange(lo, hi)

    lo, hi = window(start)
    if hi < lo:
        return False
    dim.CumulVar(routing.Start(0)).SetRange(lo, hi)
    if end == start:
        lo, hi = 0, window(start)[1]
    else:
        latest = horizon
        if problem.max_duration_s is not None:
            latest = min(latest, int(math.floor((problem.max_duration_s - svc_s[end]) * TIME_UNITS_PER_S)))
        lo, hi = window(end, latest)
    if hi < lo:
        return False
    dim.CumulVar(routing.End(0)).SetRange(lo, hi)
    return True
