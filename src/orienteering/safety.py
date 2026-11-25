"""
Walkback for E5 tours, on top of E4 (grafos.walkback.check_walkback, Aaron).

At every cell v of the route: used(v) + R(v) <= usable energy, where R(v) is the
minimum energy to walk from v back to the habitat and used(v) is the energy spent so
far, walking plus the service done at the stops already reached.

For a tour that starts and ends at the habitat this always holds once the whole tour
fits in the budget: R(v) is never more than the rest of the planned tour. It can
fail when the route ends elsewhere (end != start), so the check and the re-planning
below are what guarantee it.
"""
import sys
from dataclasses import replace
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.walkback import check_walkback  # noqa: E402

from orienteering.problem import evaluate_route  # noqa: E402


"""
Energy spent AT each stop of a route (J): its service (each station once) plus the
energy of waiting there for its window (wait time x problem.wait_power_w), with the
same rules as problem.evaluate_route. This is what tour_walkback adds at each stop.
"""
def stop_energy(problem, route):
    svc = problem.service_j if problem.service_j is not None else np.zeros(problem.n)
    energy = [float(svc[k]) if k not in route[:m] else 0.0 for m, k in enumerate(route)]
    if problem.wait_power_w and problem.time is not None:
        timeline = evaluate_route(problem, route)
        waits = np.asarray(timeline["begin"]) - np.asarray(timeline["arrival"])
        energy = [e + float(problem.wait_power_w) * float(w) for e, w in zip(energy, waits)]
    return energy


"""
R(v) for every cell: minimum energy (J) to walk from the cell back to the habitat
node, np.inf if it cannot return. One Dijkstra on the reversed graph.
"""
def return_costs(graph, habitat_node):
    return graph.costs_to(int(habitat_node))


"""
Walkback profile of a tour.
    path, stop_index : from network.route_path
    stop_service_j : (len(stop_index),) service energy done at each stop (0 where the
                     stop is not served, e.g. the final return to the habitat)
    rv_j : from return_costs
    usable_j : usable energy budget in J
Service is counted as done before leaving the stop, so at a stop's cell the check uses
the energy after its service (the stricter moment).
Returns check_walkback's dict with used_j and slack_j including service, plus:
    service_j : cumulative service energy along the path
    stop_slack_j : slack at each stop, after its service
    min_slack_j : smallest slack along the route
    first_violation_stop : position in the tour of the first stop at or after the
                           first violation, or None
"""
def tour_walkback(graph, path, stop_index, stop_service_j, rv_j, usable_j):
    path = np.asarray(path, dtype=np.int64)
    if len(path) < 2:
        rv = np.asarray(rv_j)[path]
        zero = np.zeros(len(path))
        profile = {"path": path, "used_j": zero, "rv_j": rv, "slack_j": usable_j - rv,
                   "time_s": zero, "length_m": zero, "usable_j": float(usable_j)}
    else:
        profile = check_walkback(graph, path, rv_j, usable_j)

    service = np.zeros(len(path))
    for at, energy in zip(stop_index, stop_service_j):
        service[at:] += float(energy)
    used = profile["used_j"] + service
    slack = usable_j - used - profile["rv_j"]
    bad = np.nonzero(slack < 0)[0]
    first = int(bad[0]) if len(bad) else None

    first_stop = None
    if first is not None:
        first_stop = int(np.searchsorted(np.asarray(stop_index), first))
    profile.update(used_j=used, slack_j=slack, service_j=service,
                   feasible=first is None, first_violation=first,
                   stop_slack_j=slack[np.asarray(stop_index)],
                   min_slack_j=float(slack.min()) if len(slack) else float(usable_j),
                   first_violation_stop=first_stop)
    return profile


"""
Solves the problem and checks the walkback of the tour. If it fails, two repairs are
tried from that tour, breadth first:
    - lower the budget by the deficit (minus the smallest slack), so the tour spends less;
    - forbid the station of the first violation (not the start or end), so the tour
      can keep its budget and drop only the station that breaks the walkback.
The best feasible tour found within max_retries extra solves is returned; since the
budget-only repair is one of the branches, this is never worse than lowering the budget
alone. The trivial tour (stay at the habitat) always passes.
    solve : solver function, solve(problem) -> Solution
    check : function route -> walkback profile (tour_walkback for that route)
Returns (solution, profile, retries); profile is None if no route fits at all. If no
feasible tour is found, the last one tried is returned with its failing profile.
"""
def solve_with_walkback(problem, solve, check, max_retries=5):
    solution = solve(problem)
    if not solution.route:
        return solution, None, 0
    profile = check(solution.route)
    if profile["feasible"]:
        return solution, profile, 0

    best = None
    last = (solution, profile)
    frontier = list(repairs(problem, problem.budget, frozenset(), solution, profile))
    seen = set(frontier)
    retries = 0
    while frontier and retries < max_retries:
        budget, forbidden = frontier.pop(0)
        retries += 1
        candidate = solve(restricted(problem, budget, forbidden))
        if not candidate.route:
            continue
        prof = check(candidate.route)
        if prof["feasible"]:
            if best is None or candidate.prize > best[0].prize:
                best = (candidate, prof)
            continue
        last = (candidate, prof)
        for option in repairs(problem, budget, forbidden, candidate, prof):
            if option not in seen:
                seen.add(option)
                frontier.append(option)

    if best is not None:
        return best[0], best[1], retries
    return last[0], last[1], retries


"""
The two repairs of a tour that fails the walkback: (lower budget, same forbidden set)
and, when the violation is at a station other than the start or end, (same budget,
that station forbidden as well).
"""
def repairs(problem, budget, forbidden, solution, profile):
    options = [(budget - (-profile["min_slack_j"] + 1.0), forbidden)]
    stop = profile.get("first_violation_stop")
    if stop is not None and stop < len(solution.route):
        k = solution.route[stop]
        if k not in (problem.start, problem.end) and k not in forbidden:
            options.append((budget, forbidden | {k}))
    return options


"""
The problem with another budget and some stations made unreachable (their rows and
columns of the energy matrix set to infinity). Station indices do not change.
"""
def restricted(problem, budget, forbidden):
    if not forbidden:
        return replace(problem, budget=budget)
    energy = np.array(problem.energy, dtype=float, copy=True)
    for k in forbidden:
        energy[k, :] = np.inf
        energy[:, k] = np.inf
        energy[k, k] = 0.0
    return replace(problem, budget=budget, energy=energy)
