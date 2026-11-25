"""
Contract between the data pipeline and the solvers.
Every solver takes a Problem and returns a Solution; solvers only see matrices,
never grids, files or coordinates.
"""
from dataclasses import dataclass

import numpy as np


"""
Orienteering instance over n stations.
    energy : (n, n) station-to-station walking cost matrix in J (not symmetric)
    prize : (n,) prize of each station
    budget : energy budget in J; the whole route (walking and service, including the
             final leg to end) must fit in it
    start, end : first and last station of the route (end != start: end is always the last stop)
    time : (n, n) station-to-station walking time in s, measured along the same legs as
           `energy`; required by time windows and max_duration_s
    service_s : (n,) service time at each station in s
    service_j : (n,) energy spent working at each station in J (service_s x service power)
    windows : (n, 2) earliest and latest time (s from the start of the EVA) at which the
              service of each station may begin; np.inf for no closing time. Arriving
              early means waiting until it opens (waiting costs time, not energy). For the
              start, the window bounds the departure; when end == start, the closing time
              of the start also bounds the return.
    max_duration_s : the route must be back at end, service included, by this time
    wait_power_w : metabolic power while waiting for a window to open (W); 0 by default,
                   i.e. waiting costs time but no energy, until the team agrees a value
Every station of the route is served once, start included; the final return to the
start (end == start) is not served again.
"""
@dataclass
class Problem:
    energy: np.ndarray
    prize: np.ndarray
    budget: float
    start: int = 0
    end: int = 0
    time: np.ndarray | None = None
    service_s: np.ndarray | None = None
    service_j: np.ndarray | None = None
    windows: np.ndarray | None = None
    max_duration_s: float | None = None
    wait_power_w: float = 0.0

    @property
    def n(self):
        return len(self.energy)

    @property
    def timed(self):
        return self.windows is not None or self.max_duration_s is not None


"""
Result of a solver.
    route : station indices from start to end (empty if no route fits)
    prize : prize collected by the route
    energy : energy spent by the route in J, walking plus service
    solver : name of the solver that produced it
    runtime_s : time the solver took
    duration_s : time at which the route ends, waits and service included
                 (None if problem.time is missing)
    bound : best proven upper bound on the prize, for solvers that give one (CP-SAT);
            None if the solver gives none
    optimal : True if the solver proved the route optimal (exact solvers always do;
              None if unknown, as for the heuristic OR-Tools routing solver)
"""
@dataclass
class Solution:
    route: list[int]
    prize: float
    energy: float
    solver: str
    runtime_s: float
    duration_s: float | None = None
    bound: float | None = None
    optimal: bool | None = None
    iterations: int | None = None                           # loop iterations (metaheuristics)
    evaluations: int | None = None                          # feasibility checks, where counted
    trace_rows: list | None = None                          # CP-SAT solution-callback rows


"""
Walks a route through the problem's rules, the same way every solver applies them.
Returns a dict:
    energy : J, walking plus service (each distinct station served once) plus waiting
             (wait time x problem.wait_power_w)
    duration : s, time at which the route ends (None if problem.time is missing)
    arrival, begin, depart : (len(route),) times at each stop (None without problem.time);
                             begin - arrival is the wait for the window to open
    feasible : True if every window and max_duration_s hold (the energy budget is not checked)
"""
def evaluate_route(problem, route):
    n_stops = len(route)
    served = [k not in route[:m] for m, k in enumerate(route)]
    svc_j = problem.service_j if problem.service_j is not None else np.zeros(problem.n)
    svc_s = problem.service_s if problem.service_s is not None else np.zeros(problem.n)

    energy = sum(float(problem.energy[a][b]) for a, b in zip(route, route[1:]))
    energy += sum(float(svc_j[k]) for k, s in zip(route, served) if s)

    result = {"energy": energy, "duration": None, "arrival": None, "begin": None,
              "depart": None, "feasible": True}
    if problem.time is None:
        result["feasible"] = not problem.timed
        return result

    windows = problem.windows if problem.windows is not None else np.tile([0.0, np.inf], (problem.n, 1))
    arrival, begin, depart = np.zeros(n_stops), np.zeros(n_stops), np.zeros(n_stops)
    feasible = True
    for m, k in enumerate(route):
        arrival[m] = 0.0 if m == 0 else depart[m - 1] + float(problem.time[route[m - 1]][k])
        if served[m]:
            begin[m] = max(arrival[m], float(windows[k][0]))
            feasible &= begin[m] <= windows[k][1]
            depart[m] = begin[m] + float(svc_s[k])
        else:
            begin[m] = depart[m] = arrival[m]
            feasible &= arrival[m] <= windows[k][1]

    duration = float(depart[-1]) if n_stops else 0.0
    if problem.max_duration_s is not None:
        feasible &= duration <= problem.max_duration_s
    if problem.wait_power_w:
        result["energy"] += float(problem.wait_power_w) * float((begin - arrival).sum())
    result.update(duration=duration, arrival=arrival, begin=begin, depart=depart,
                  feasible=bool(feasible))
    return result
