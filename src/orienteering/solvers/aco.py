"""
Ant colony optimisation for the orienteering problem (E6): Ant Colony System
[Dorigo1997], the variant Montemanni and Gambardella used for orienteering with time
windows [Montemanni2009].

Each ant builds a tour from the start, one station at a time. A station is a candidate
only if, after visiting it, the tour can still be closed at the end within the energy
budget, every time window and the maximum duration; so every ant's tour is feasible by
construction. The next station is chosen by pheromone x (prize / added energy)^beta:
with probability q0 the best candidate, otherwise one drawn in proportion. Using a leg
lowers its pheromone a little (local update), so the ants of one iteration spread out.
The best tour of each iteration is polished (2-opt, then insertion), and the best tour
so far reinforces its legs (global update).
Heuristic, seeded (seed) for reproducible runs.
"""
import time

import numpy as np

from orienteering.solvers.heuristics import Evaluator

MAX_STATIONS = 500
ANTS = 10
ITERATIONS = 100
MAX_NO_IMPROVE = 40
BETA = 2.0                   # weight of prize / added energy against the pheromone
Q0 = 0.9                     # probability of taking the best candidate
RHO = 0.1                    # evaporation of the global and the local update
TIME_LIMIT_S = 10.0


def solve(problem, seed=0, ants=ANTS, iterations=ITERATIONS, max_no_improve=MAX_NO_IMPROVE,
          time_limit_s=TIME_LIMIT_S, trace=None):
    """`trace`: optional Tracer; gets one row per iteration (it never changes the result)."""
    t0 = time.perf_counter()
    if trace is not None:
        trace.start()
    if problem.n > MAX_STATIONS:
        raise ValueError(f"ACO is limited to {MAX_STATIONS} stations, got {problem.n}")
    if problem.timed and problem.time is None:
        raise ValueError("time windows and max_duration_s need problem.time")
    ev = Evaluator(problem)
    best = ev.initial()
    if best is None:
        if trace is not None:
            trace.flush()
        return ev.solution(None, "aco", time.perf_counter() - t0, 0)

    rng = np.random.default_rng(seed)
    step = Steps(ev)
    total = float(ev.prize[ev.prize > 0].sum()) or 1.0
    best = ev.insert_greedy(best)                       # greedy tour: starting level and first best
    tau0 = max(ev.points(best) / total, 1e-3)
    tau = np.full((ev.n, ev.n), tau0)
    with np.errstate(divide="ignore", invalid="ignore"):
        eta = ev.prize[None, :] / np.maximum(ev.energy + ev.svc[None, :], 1e-12)
    eta = np.where(np.isfinite(eta), eta, 0.0) ** BETA

    stale, iters = 0, 0
    for _ in range(iterations):
        if stale >= max_no_improve or time.perf_counter() - t0 > time_limit_s:
            break
        round_best = None
        ant_points = []
        for _ in range(ants):
            route = build(ev, step, tau, eta, tau0, rng)
            ant_points.append(ev.points(route))
            if round_best is None or ev.key(route) > ev.key(round_best):
                round_best = route
        round_best = ev.insert_greedy(ev.two_opt(round_best))
        if ev.key(round_best) > ev.key(best):
            best, stale = round_best, 0
        else:
            stale += 1
        deposit = ev.points(best) / total
        for a, b in zip(best, best[1:]):
            tau[a, b] = (1 - RHO) * tau[a, b] + RHO * deposit
        if trace is not None:
            trace(iter=iters, best_prize=ev.points(best), best_energy_j=ev.total(best),
                  round_best_prize=ev.points(round_best),
                  ants_mean_prize=float(np.mean(ant_points)),
                  tau_mean=float(tau.mean()), tau_max=float(tau.max()), stale=stale)
        iters += 1
    if trace is not None:
        trace.flush()
    return ev.solution(best, "aco", time.perf_counter() - t0, iters)


"""
One ant: from the start, keeps choosing among the stations that still allow closing the
tour, until none is left. Returns a feasible route.
"""
def build(ev, step, tau, eta, tau0, rng):
    state = step.initial()
    route = [ev.start]
    visited = np.zeros(ev.n, dtype=bool)
    visited[[ev.start, ev.end]] = True
    at = ev.start
    while True:
        ok = step.candidates(at, state) & ~visited
        cand = np.flatnonzero(ok)
        if len(cand) == 0:
            break
        weight = tau[at, cand] * eta[at, cand]
        if weight.sum() <= 0:
            nxt = int(cand[rng.integers(len(cand))])
        elif rng.random() < Q0:
            nxt = int(cand[np.argmax(weight)])
        else:
            nxt = int(rng.choice(cand, p=weight / weight.sum()))
        tau[at, nxt] = (1 - RHO) * tau[at, nxt] + RHO * tau0     # local update
        state = step.advance(at, nxt, state)
        visited[nxt] = True
        route.append(nxt)
        at = nxt
    route.append(ev.end)
    if not ev.check(route)[0]:                # numerical edge: fall back to the shared rules
        route = ev.repair(route) or ev.initial()
    return route


"""
Incremental form of problem.evaluate_route for a tour that grows at its end: the state
is (energy spent, departure time) at the last stop. candidates() says, for every
station at once, whether going there next still leaves a feasible way to close the tour.
"""
class Steps:
    def __init__(self, ev):
        p = ev.p
        n = ev.n
        self.ev = ev
        self.energy, self.svc_j, self.prize, self.budget = ev.energy, ev.svc, ev.prize, ev.budget
        self.wait_w = float(p.wait_power_w or 0.0)
        self.time = None if p.time is None else np.asarray(p.time, dtype=float)
        self.svc_s = (np.asarray(p.service_s, dtype=float) if p.service_s is not None
                      else np.zeros(n))
        windows = p.windows if p.windows is not None else np.tile([0.0, np.inf], (n, 1))
        self.opens = np.asarray(windows, dtype=float)[:, 0]
        self.closes = np.asarray(windows, dtype=float)[:, 1]
        self.max_t = np.inf if p.max_duration_s is None else float(p.max_duration_s) + 1e-9
        self.closes_tol = self.closes + 1e-9
        self.end_served = ev.end != ev.start

    def initial(self):
        """State after serving the start (which may open late)."""
        if self.time is None:
            return float(self.svc_j[self.ev.start]), 0.0
        begin = max(0.0, float(self.opens[self.ev.start]))
        return (float(self.svc_j[self.ev.start]) + self.wait_w * begin,
                begin + float(self.svc_s[self.ev.start]))

    def _arrive(self, at, state):
        """Energy and departure time after going from `at` to each station and serving it."""
        spent, depart = state
        e = spent + self.energy[at] + self.svc_j
        if self.time is None:
            return e, None, np.isfinite(e)
        arrive = depart + self.time[at]
        begin = np.maximum(arrive, self.opens)
        with np.errstate(invalid="ignore"):
            e = e + self.wait_w * (begin - arrive)
        ok = np.isfinite(e) & np.isfinite(arrive) & (begin <= self.closes_tol)
        return e, begin + self.svc_s, ok

    def candidates(self, at, state):
        e, leave, ok = self._arrive(at, state)
        end = self.ev.end
        close_e = self.energy[:, end] + (self.svc_j[end] if self.end_served else 0.0)
        if self.time is not None:
            back = leave + self.time[:, end]
            if self.end_served:
                begin = np.maximum(back, self.opens[end])
                with np.errstate(invalid="ignore"):
                    close_e = close_e + self.wait_w * (begin - back)
                ok &= (begin <= self.closes_tol[end]) & (begin + self.svc_s[end] <= self.max_t)
            else:
                ok &= (back <= self.closes_tol[end]) & (back <= self.max_t)
        with np.errstate(invalid="ignore"):
            ok &= (e + close_e <= self.budget) & (self.prize > 0)
        return ok

    def advance(self, at, nxt, state):
        e, leave, _ = self._arrive(at, state)
        return float(e[nxt]), 0.0 if leave is None else float(leave[nxt])
