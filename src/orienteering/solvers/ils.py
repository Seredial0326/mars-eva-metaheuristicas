"""
Iterated local search for the orienteering problem (E6), after Vansteenwegen et al.
[Vansteenwegen2009]: local search (best-ratio insertion, 2-opt, swaps for better
stations), then a shake that removes S consecutive stops from position R; S grows by one
each time and R moves along the route, so the shakes cover the whole tour.
Heuristic: no optimality guarantee. Deterministic (no random numbers).
"""
import time

from orienteering.solvers.heuristics import Evaluator

MAX_STATIONS = 500
MAX_NO_IMPROVE = 150
TIME_LIMIT_S = 10.0


def solve(problem, max_no_improve=MAX_NO_IMPROVE, time_limit_s=TIME_LIMIT_S, trace=None):
    """`trace`: optional Tracer; gets one row per loop iteration (it never changes the result)."""
    t0 = time.perf_counter()
    if trace is not None:
        trace.start()
    if problem.n > MAX_STATIONS:
        raise ValueError(f"ILS is limited to {MAX_STATIONS} stations, got {problem.n}")
    if problem.timed and problem.time is None:
        raise ValueError("time windows and max_duration_s need problem.time")
    ev = Evaluator(problem)
    current = ev.initial()
    if current is None:
        if trace is not None:
            trace.flush()
        return ev.solution(None, "ils", time.perf_counter() - t0, 0)

    best = current
    shake_size, shake_at, stale, iters = 1, 1, 0, 0
    while stale < max_no_improve and time.perf_counter() - t0 < time_limit_s:
        current = ev.local_search(current)
        improved = ev.key(current) > ev.key(best)
        if improved:
            best, shake_size, stale = list(current), 1, 0
        else:
            stale += 1
        if trace is not None:
            trace(iter=iters, best_prize=ev.points(best), best_energy_j=ev.total(best),
                  current_prize=ev.points(current), shake_size=shake_size, shake_at=shake_at,
                  stale=stale, improved=bool(improved))
        iters += 1
        inner = current[1:-1]
        if not inner:
            continue
        shake_at = (shake_at - 1) % len(inner) + 1
        removed = set(range(shake_at - 1, shake_at - 1 + shake_size))
        inner = [k for m, k in enumerate(inner) if m not in removed]
        current = ev.repair([current[0], *inner, current[-1]]) or ev.initial()
        shake_at += shake_size
        shake_size += 1
        if shake_size > max(1, len(best) // 2):
            shake_size = 1
    if trace is not None:
        trace.flush()
    return ev.solution(best, "ils", time.perf_counter() - t0, iters)
