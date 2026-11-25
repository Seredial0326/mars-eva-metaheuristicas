"""
Shared pieces of the E6 metaheuristics (ils.py, sa.py): route energy, feasibility under
every rule of the Problem, best insertion, 2-opt and repair. A route is a list of
station indices from problem.start to problem.end; each station appears once (the start
twice when the tour returns to it).
"""
import numpy as np

from orienteering.problem import Solution, evaluate_route


class Evaluator:
    def __init__(self, problem):
        self.p = problem
        self.evaluations = 0                                # check() calls, for the lab traces
        self.n = problem.n
        self.energy = np.asarray(problem.energy, dtype=float)
        self.prize = np.asarray(problem.prize, dtype=float)
        self.svc = (np.asarray(problem.service_j, dtype=float) if problem.service_j is not None
                    else np.zeros(self.n))
        self.timed = problem.timed or (bool(problem.wait_power_w) and problem.windows is not None)
        self.budget = float(problem.budget) + 1e-9
        self.start, self.end = problem.start, problem.end
        self.fixed = {self.start, self.end}

    def walk(self, route):
        e = self.energy
        return float(sum(e[a, b] for a, b in zip(route, route[1:])))

    def total(self, route):
        return self.walk(route) + float(sum(self.svc[k] for k in set(route)))

    def points(self, route):
        return float(sum(self.prize[k] for k in set(route)))

    """
    (feasible, energy): energy within the budget and, if the problem is timed, every
    window and the maximum duration (problem.evaluate_route, which also adds waits).
    """
    def check(self, route):
        self.evaluations += 1
        if not self.timed:
            spent = self.total(route)
            return spent <= self.budget, spent
        result = evaluate_route(self.p, route)
        return result["feasible"] and result["energy"] <= self.budget, result["energy"]

    def initial(self):
        route = [self.start, self.end]
        return route if self.check(route)[0] else None

    def key(self, route):
        """Higher is better: points first, then less energy."""
        return (round(self.points(route), 9), -self.total(route))

    """
    Inserts stations one at a time while any fits, choosing the largest
    prize^2 / added energy [Vansteenwegen2009] at its cheapest position.
    candidates: stations allowed (default every unvisited one).
    """
    def insert_greedy(self, route, candidates=None):
        e, svc = self.energy, self.svc
        route = list(route)
        while True:
            visited = set(route)
            pool = [k for k in (range(self.n) if candidates is None else candidates)
                    if k not in visited and k not in self.fixed and self.prize[k] > 0]
            spent = self.total(route)
            options = []
            for k in pool:
                for pos in range(1, len(route)):
                    a, b = route[pos - 1], route[pos]
                    added = e[a, k] + e[k, b] - e[a, b] + svc[k]
                    if not np.isfinite(added) or spent + added > self.budget:
                        continue
                    options.append((self.prize[k] ** 2 / max(added, 1e-12), k, pos))
            if not options:
                return route
            options.sort(reverse=True)
            for _, k, pos in options:
                cand = route[:pos] + [k] + route[pos:]
                if not self.timed or self.check(cand)[0]:
                    route = cand
                    break
            else:
                return route

    """
    2-opt on the visiting order: reverses segments while the energy drops (the matrix
    is not symmetric, so the whole reversed segment is re-costed).
    """
    def two_opt(self, route):
        route = list(route)
        best = self.total(route)
        improved = True
        while improved:
            improved = False
            for i in range(1, len(route) - 2):
                for j in range(i + 1, len(route) - 1):
                    cand = route[:i] + route[i:j + 1][::-1] + route[j + 1:]
                    spent = self.total(cand)
                    if spent < best - 1e-9 and (not self.timed or self.check(cand)[0]):
                        route, best, improved = cand, spent, True
        return route

    """
    Replaces a visited station by an unvisited one worth more, where that fits.
    """
    def swap_up(self, route):
        route = list(route)
        improved = True
        while improved:
            improved = False
            for pos in range(1, len(route) - 1):
                k = route[pos]
                without = route[:pos] + route[pos + 1:]
                better = [j for j in range(self.n) if j not in route and j not in self.fixed
                          and self.prize[j] > self.prize[k]]
                cand = self.insert_greedy(without, better) if better else without
                if self.check(cand)[0] and self.key(cand) > self.key(route):
                    route, improved = cand, True
                    break
        return route

    def local_search(self, route):
        route = self.insert_greedy(route)
        route = self.two_opt(route)
        route = self.insert_greedy(route)
        return self.swap_up(route)

    """
    Drops the stations with the lowest prize / saved energy until the route is feasible
    again (removing a stop can make a route longer when the costs break the triangle
    inequality, or move a later stop past its window).
    """
    def repair(self, route):
        route = list(route)
        while not self.check(route)[0] and len(route) > 2:
            e = self.energy
            worst = min(range(1, len(route) - 1),
                        key=lambda m: self.prize[route[m]] / max(
                            e[route[m - 1], route[m]] + e[route[m], route[m + 1]]
                            - e[route[m - 1], route[m + 1]] + self.svc[route[m]], 1e-12))
            route = route[:worst] + route[worst + 1:]
        return route if self.check(route)[0] else None

    def solution(self, route, name, runtime, iterations=None):
        counts = {"iterations": iterations}
        if route is None:
            return Solution([], 0.0, 0.0, name, runtime, evaluations=self.evaluations, **counts)
        ok, spent = self.check(route)
        if not ok:
            return Solution([], 0.0, 0.0, name, runtime, evaluations=self.evaluations, **counts)
        duration = evaluate_route(self.p, route)["duration"] if self.p.time is not None else None
        return Solution(route, self.points(route), spent, name, runtime, duration,
                        evaluations=self.evaluations, **counts)
