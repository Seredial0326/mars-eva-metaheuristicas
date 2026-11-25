"""
Orienteering with OR-Tools' CP-SAT solver: an exact model (circuit over optional stations)
for instances beyond the DP's 20 nodes. Within the time limit it either proves the
optimum or returns its best tour with an upper bound on the prize (Solution.bound).

On Windows the search may run in a separate process (see routing.solve_isolated).
"""
import math
import time

import numpy as np

from orienteering.problem import Solution, evaluate_route

MAX_STATIONS = 60
TIME_LIMIT_S = 30.0
ENERGY_UNITS = 1e6           # the budget is mapped to this many integer units
TIME_UNITS_PER_S = 1000      # time resolution of 1 ms
PRIZE_UNITS = 100            # prize resolution of 0.01 points
WORKERS = 8


"""
Model, with x[i, j] = 1 if the tour walks i -> j and y[k] = 1 if station k is visited:
    - AddCircuit over the arcs plus a self-loop (k, k, not y[k]) for every optional
      station; when end != start, a fixed arc end -> start closes the circuit
    - energy: sum of (leg energy + service of the arrival station) over the arcs plus
      the start's service <= budget
    - time (only when the problem is timed): T[k] is the start of service at k; an arc
      i -> j forces T[j] >= T[i] + service_i + walk_ij; visited stations start within
      their window; the return (end == start) or the end's service fits max_duration_s.
      With max_duration_s, the walking and service of the chosen arcs (plus the end's
      service) must also fit in it: redundant, since waits only add, but linear, so it
      gives CP-SAT a much tighter bound than the arc-by-arc time rule alone
    - objective: maximise the prize; a second phase with the prize fixed minimises the
      energy (the DP's tie-break), using the remaining time
Costs are rounded up and limits down, so every tour the model accepts also holds with the
exact values; the tour is re-checked with problem.evaluate_route.
Waiting energy (problem.wait_power_w > 0) is not modelled: use the DP.
    time_limit_s : total search time (default TIME_LIMIT_S), split between the phases
Solution.bound is the best proven upper bound on the prize (equal to the prize when the
optimum is proven) and Solution.optimal says whether it was.
With `trace` (a Tracer) one row per solution the solver finds is added (see Recorder);
the rows come back in Solution.trace_rows, also from the child process.
"""
def solve(problem, time_limit_s=None, trace=None):
    from orienteering.solvers.routing import solve_isolated
    time_limit_s = TIME_LIMIT_S if time_limit_s is None else time_limit_s
    if problem.n > MAX_STATIONS:
        raise ValueError(f"the CP-SAT solver is limited to {MAX_STATIONS} stations, got {problem.n}")
    if problem.timed and problem.time is None:
        raise ValueError("time windows and max_duration_s need problem.time")
    if problem.wait_power_w:
        raise NotImplementedError("waiting energy is not modelled in the CP-SAT solver; use dp")
    if trace is not None:
        trace.start()
    sol = solve_isolated("orienteering.solvers.cpsat", "solve_here",
                         (problem, time_limit_s, trace is not None))
    if trace is not None:
        trace.extend(sol.trace_rows or [])
        trace.flush()
    return sol


"""
Rows of the CP-SAT trace, one per solution found (callback of both phases):
    t_s (seconds since solve_here started), iter (solution index over both phases),
    phase (1 = maximise the prize, 2 = minimise the energy), objective and bound (points
    in phase 1, J in phase 2), best_prize (the incumbent's prize) and best_energy_j
    (None in phase 1).
"""
def make_recorder(cp_model, rows, t0, phase, scale_units, prize_pts=None):
    class Recorder(cp_model.CpSolverSolutionCallback):
        def __init__(self):
            super().__init__()

        def OnSolutionCallback(self):
            objective = self.ObjectiveValue() / scale_units
            rows.append({"t_s": time.perf_counter() - t0, "iter": len(rows),
                         "objective": objective, "bound": self.BestObjectiveBound() / scale_units,
                         "phase": phase,
                         "best_prize": objective if prize_pts is None else prize_pts,
                         "best_energy_j": None if prize_pts is None else objective})
    return Recorder()


def solve_here(problem, time_limit_s, record=False):
    from ortools.sat.python import cp_model

    t0 = time.perf_counter()
    rows = [] if record else None
    n, start, end = problem.n, problem.start, problem.end
    svc_j = problem.service_j if problem.service_j is not None else np.zeros(n)
    svc_s = problem.service_s if problem.service_s is not None else np.zeros(n)
    empty = Solution([], 0.0, 0.0, "cpsat", 0.0, bound=0.0, optimal=True, trace_rows=rows)
    if problem.budget <= 0 or svc_j[start] > problem.budget:
        empty.runtime_s = time.perf_counter() - t0
        return empty

    scale = ENERGY_UNITS / problem.budget
    capacity = int(math.floor((problem.budget - svc_j[start]) * scale))
    on_arrival = np.where(np.arange(n) == start, 0.0, svc_j)
    leg_e = np.ceil((problem.energy + on_arrival[None, :]) * scale)

    m = cp_model.CpModel()
    y = [m.NewBoolVar(f"y{k}") for k in range(n)]
    arcs, x = [], {}
    for i in range(n):
        for j in range(n):
            if i == j or not np.isfinite(leg_e[i, j]) or leg_e[i, j] > capacity:
                continue
            if end != start and (j == start or i == end):
                continue                     # start only first, end only last
            x[i, j] = m.NewBoolVar(f"x{i}_{j}")
            arcs.append((i, j, x[i, j]))
            m.AddImplication(x[i, j], y[i])
            m.AddImplication(x[i, j], y[j])
    for k in range(n):
        if k in (start, end):
            m.Add(y[k] == 1)
        else:
            arcs.append((k, k, y[k].Not()))
    stay = None
    if end != start:
        arcs.append((end, start, m.NewConstant(1)))
    else:
        stay = m.NewBoolVar("stay")          # the empty tour start -> start
        arcs.append((start, start, stay))
        for k in range(n):                   # else the others could close a loop without the start
            if k != start:
                m.AddImplication(stay, y[k].Not())
    m.AddCircuit(arcs)

    energy = sum(int(leg_e[i, j]) * v for (i, j), v in x.items())
    m.Add(energy <= capacity)

    if problem.timed:
        add_times(m, problem, x, y, svc_s, stay)

    prize_units = [int(round(float(problem.prize[k]) * PRIZE_UNITS)) for k in range(n)]
    prize = sum(p * y[k] for k, p in enumerate(prize_units))
    m.Maximize(prize)

    solver = cp_model.CpSolver()
    solver.parameters.num_search_workers = WORKERS
    solver.parameters.max_time_in_seconds = max(0.1, 0.8 * time_limit_s)
    if record:
        status = solver.Solve(m, make_recorder(cp_model, rows, t0, 1, PRIZE_UNITS))
    else:
        status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        empty.runtime_s = time.perf_counter() - t0
        if status != cp_model.INFEASIBLE:    # no tour found, but none proven impossible
            empty.optimal, empty.bound = False, None
        return empty
    optimal = status == cp_model.OPTIMAL
    bound = solver.BestObjectiveBound() / PRIZE_UNITS
    best = int(round(solver.ObjectiveValue()))
    route = read_route(solver, x, start, end)

    # Phase 2: same prize, least energy
    left = time_limit_s - (time.perf_counter() - t0)
    if left > 0.05:
        m.ClearObjective()
        m.Add(prize >= best)
        m.Minimize(energy)
        for (i, j), v in x.items():
            m.AddHint(v, solver.BooleanValue(v))
        solver.parameters.max_time_in_seconds = left
        if record:
            status2 = solver.Solve(m, make_recorder(cp_model, rows, t0, 2, scale,
                                                    best / PRIZE_UNITS))
        else:
            status2 = solver.Solve(m)
        if status2 in (cp_model.OPTIMAL, cp_model.FEASIBLE):
            route = read_route(solver, x, start, end)
    sol = finish(problem, route, t0, optimal, bound)
    sol.trace_rows = rows
    return sol


def add_times(m, problem, x, y, svc_s, stay):
    n, start, end = problem.n, problem.start, problem.end
    windows = problem.windows if problem.windows is not None else np.tile([0.0, np.inf], (n, 1))
    walk = np.where(np.isfinite(problem.time), problem.time, 0.0)
    horizon_s = (walk.max(axis=1).sum() + svc_s.sum()
                 + np.max(np.where(np.isfinite(windows[:, 0]), windows[:, 0], 0.0))
                 + 1.0 + n / TIME_UNITS_PER_S)
    if problem.max_duration_s is not None:
        horizon_s = min(horizon_s, problem.max_duration_s)
    horizon = int(math.floor(horizon_s * TIME_UNITS_PER_S))
    up = lambda v: int(math.ceil(v * TIME_UNITS_PER_S))      # noqa: E731
    down = lambda v: int(math.floor(v * TIME_UNITS_PER_S))   # noqa: E731

    begin = [m.NewIntVar(0, horizon, f"t{k}") for k in range(n)]
    back = m.NewIntVar(0, horizon, "back") if end == start else None
    for k in range(n):
        lo = up(max(0.0, float(windows[k][0])))
        hi = horizon if not np.isfinite(windows[k][1]) else min(horizon, down(float(windows[k][1])))
        if k == end and end != start and problem.max_duration_s is not None:
            hi = min(hi, down(problem.max_duration_s - float(svc_s[end])))
        if hi < lo:
            m.Add(y[k] == 0)
            continue
        m.Add(begin[k] >= lo).OnlyEnforceIf(y[k])
        m.Add(begin[k] <= hi).OnlyEnforceIf(y[k])
    if back is not None and np.isfinite(windows[start][1]):
        m.Add(back <= down(float(windows[start][1])))
    if stay is not None:                     # the empty tour still serves the start
        m.Add(back >= begin[start] + up(float(svc_s[start]))).OnlyEnforceIf(stay)
    if problem.max_duration_s is not None:
        busy = sum(up(float(svc_s[i]) + float(walk[i, j])) * v for (i, j), v in x.items())
        last = up(float(svc_s[end])) if end != start else 0
        m.Add(busy + last <= down(problem.max_duration_s))
    for (i, j), v in x.items():
        step = up(float(svc_s[i]) + float(walk[i, j]))
        target = back if (j == start and back is not None) else begin[j]
        m.Add(target >= begin[i] + step).OnlyEnforceIf(v)


def read_route(solver, x, start, end):
    succ = {i: j for (i, j), v in x.items() if solver.BooleanValue(v)}
    route, k = [start], start
    while k in succ and len(route) <= len(x) + 1:
        k = succ[k]
        route.append(k)
        if k == end:
            break
    if route[-1] != end or len(route) == 1:
        route.append(end)                    # empty tour start -> start
    return route


def finish(problem, route, t0, optimal, bound):
    result = evaluate_route(problem, route)
    runtime = time.perf_counter() - t0
    if result["energy"] > problem.budget + 1e-9 or not result["feasible"]:
        return Solution([], 0.0, 0.0, "cpsat", runtime, bound=bound, optimal=False)
    prize = float(sum(problem.prize[k] for k in set(route)))
    return Solution(route, prize, result["energy"], "cpsat", runtime, result["duration"],
                    bound=bound, optimal=optimal)
