"""
Genetic algorithm for the orienteering problem (E6). A population of feasible tours
evolves by tournament selection, crossover and mutation; every child is repaired (stops
dropped until it fits) and then filled by best-ratio insertion, so the whole population
stays feasible. (The first GA for the orienteering problem [Tasgetiren2000] kept
infeasible tours under an adaptive penalty instead.)
    - initial tours: greedy insertion over a random half of the stations, so they differ
    - crossover (order-based): a segment of one parent's stops, then the other parent's
      remaining stops in that parent's order
    - mutation: drop a stop, add an unvisited station at its cheapest position, swap two
      stops, or reverse a segment
    - elitism: the best tours pass unchanged
The best tour found is polished with the ILS local search and returned.
Heuristic, seeded (seed) for reproducible runs.
"""
import time

import numpy as np

from orienteering.solvers.heuristics import Evaluator

MAX_STATIONS = 500
POPULATION = 30
GENERATIONS = 80
MAX_NO_IMPROVE = 25
ELITE = 2
TOURNAMENT = 3
MUTATION = 0.3
TIME_LIMIT_S = 10.0


def solve(problem, seed=0, population=POPULATION, generations=GENERATIONS,
          max_no_improve=MAX_NO_IMPROVE, time_limit_s=TIME_LIMIT_S, trace=None):
    """`trace`: optional Tracer; gets one row per generation (it never changes the result)."""
    t0 = time.perf_counter()
    if trace is not None:
        trace.start()
    if problem.n > MAX_STATIONS:
        raise ValueError(f"GA is limited to {MAX_STATIONS} stations, got {problem.n}")
    if problem.timed and problem.time is None:
        raise ValueError("time windows and max_duration_s need problem.time")
    ev = Evaluator(problem)
    empty = ev.initial()
    if empty is None:
        if trace is not None:
            trace.flush()
        return ev.solution(None, "ga", time.perf_counter() - t0, 0)

    rng = np.random.default_rng(seed)
    free = [k for k in range(ev.n) if k not in ev.fixed and ev.prize[k] > 0]
    pop = [ev.insert_greedy(empty)]                     # the plain greedy tour, then random halves
    while len(pop) < population:
        half = [k for k in free if rng.random() < 0.5]
        pop.append(ev.insert_greedy(empty, half))
    pop.sort(key=ev.key, reverse=True)
    best, stale, iters = pop[0], 0, 0

    for _ in range(generations):
        if stale >= max_no_improve or time.perf_counter() - t0 > time_limit_s:
            break
        children = [list(r) for r in pop[:ELITE]]
        while len(children) < population:
            a, b = pick(ev, pop, rng), pick(ev, pop, rng)
            child = crossover(a, b, rng)
            if rng.random() < MUTATION:
                child = mutate(ev, child, free, rng)
            child = ev.repair(child) or empty
            children.append(ev.insert_greedy(child))
        pop = sorted(children, key=ev.key, reverse=True)
        if ev.key(pop[0]) > ev.key(best):
            best, stale = pop[0], 0
        else:
            stale += 1
        if trace is not None:
            points = [ev.points(r) for r in pop]
            trace(iter=iters, best_prize=ev.points(best), best_energy_j=ev.total(best),
                  pop_best=max(points), pop_mean=float(np.mean(points)), pop_worst=min(points),
                  diversity=len({tuple(r) for r in pop}) / len(pop), stale=stale)
        iters += 1
    best = ev.local_search(best)
    if trace is not None:
        trace.flush()
    return ev.solution(best, "ga", time.perf_counter() - t0, iters)


def pick(ev, pop, rng):
    """Tournament selection: the best of TOURNAMENT tours drawn at random."""
    drawn = rng.choice(len(pop), size=min(TOURNAMENT, len(pop)), replace=False)
    return pop[min(drawn)]                               # pop is sorted best first


def crossover(a, b, rng):
    """A segment of a's stops, then b's other stops in b's order (start and end kept)."""
    inner_a, inner_b = a[1:-1], b[1:-1]
    if not inner_a:
        return list(b)
    i, j = sorted(rng.integers(0, len(inner_a) + 1, 2))
    segment = inner_a[i:j]
    taken = set(segment)
    rest = [k for k in inner_b if k not in taken]
    return [a[0], *segment, *rest, a[-1]]


def mutate(ev, route, free, rng):
    inner = route[1:-1]
    out = [k for k in free if k not in route]
    kind = rng.integers(4)
    if kind == 0 and inner:                              # drop a stop
        m = 1 + rng.integers(len(inner))
        return route[:m] + route[m + 1:]
    if kind == 1 and out:                                # add at the cheapest position
        k = out[rng.integers(len(out))]
        e = ev.energy
        pos = min(range(1, len(route)),
                  key=lambda m: e[route[m - 1], k] + e[k, route[m]] - e[route[m - 1], route[m]])
        return route[:pos] + [k] + route[pos:]
    if kind == 2 and len(inner) >= 2:                    # swap two stops
        i, j = 1 + rng.choice(len(inner), 2, replace=False)
        route = list(route)
        route[i], route[j] = route[j], route[i]
        return route
    if len(inner) >= 2:                                  # reverse a segment
        i, j = sorted(1 + rng.choice(len(inner), 2, replace=False))
        return route[:i] + route[i:j + 1][::-1] + route[j + 1:]
    return route
