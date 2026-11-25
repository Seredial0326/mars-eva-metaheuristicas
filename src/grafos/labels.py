"""E4 - Round trips with walkback over several resources (issue #7).

Resources: metabolic energy E (J) and time t (s). Oxygen is derived from both:
    O2 (L) = E / KJ_PER_LITER_O2 / 1000  +  leak_lpm * t / 60
The first term is metabolic O2 (E3, fisica.metabolic.liters_o2); the second is
consumption that depends on time and not on effort (suit leakage, purge), a
declared assumption (0 by default).

Limits (Budget), checked at EVERY point of the route (walkback rule):
    E_used + E_need(v)  <= energy_j     usable metabolic energy
    t_used + t_need(v)  <= time_s       maximum EVA duration
    O2_used + O2_need(v) <= o2_l        usable oxygen
where *_need(v) is the minimum still needed to finish: on the way out,
cost(v -> goal) + service + R(goal); on the way back, R(v).

Note: for a PLANNED round trip, the rule at every point follows from the totals
(R(v) <= the planned rest of the trip), so a closed route is feasible iff its
totals fit. The per-point rule matters for open or partial routes, which
walkback.check_walkback checks.

Search, round trip habitat -> goal -> habitat (method in the result):
  1. "dijkstra": best route for the objective alone (two Dijkstras). If it fits
     every limit it is the exact optimum.
  2. "lagrangian": otherwise, sweep routes that minimise a weighted sum of E and
     t (supported Pareto routes) and keep the best one that fits. Fast; may miss
     the optimum by `gap`.
  3. "label_setting": exact resource-constrained search with (E, t) Pareto labels
     per (node, phase), best-first by objective + lower bound, pruned by the
     lagrangian route's value. If it hits max_labels, the lagrangian route is
     returned with exact=False.
"""

import heapq
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import dijkstra

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.graph import follow  # noqa: E402

KJ_PER_LITER_O2 = 20.1          # same value as fisica.metabolic.KJ_PER_LITER_O2


@dataclass
class Budget:
    energy_j: float = np.inf     # usable metabolic energy (already minus margin)
    time_s: float = np.inf       # maximum EVA duration
    o2_l: float = np.inf         # usable oxygen
    leak_lpm: float = 0.0        # time-based O2 use (L/min), declared assumption

    def o2(self, e_j, t_s):
        o2 = np.asarray(e_j) / 1000.0 / KJ_PER_LITER_O2
        if self.leak_lpm:                       # skip 0 * inf = NaN on unreachable cells
            o2 = o2 + self.leak_lpm * np.asarray(t_s) / 60.0
        return o2

    def fits(self, e_j, t_s, tol=1e-9):
        return bool(e_j <= self.energy_j * (1 + tol) and t_s <= self.time_s * (1 + tol)
                    and self.o2(e_j, t_s) <= self.o2_l * (1 + tol))


class NoFeasibleRoute(Exception):
    pass


def _objective_weights(objective, budget):
    """(cE, ct) so that the objective is cE * E + ct * t."""
    if objective == "energy":
        return 1.0, 0.0
    if objective == "time":
        return 0.0, 1.0
    if objective == "o2":
        return 1.0 / 1000.0 / KJ_PER_LITER_O2, budget.leak_lpm / 60.0
    raise ValueError("objective must be 'energy', 'time' or 'o2'")


class _Weighted:
    """Round trips minimising wE * E + wt * t, reusing the graph structure."""

    def __init__(self, graph, habitat, goal, service_e, service_t):
        self.g, self.h, self.goal = graph, int(habitat), int(goal)
        self.se, self.st = service_e, service_t
        self.E, self.T = graph.csr("energy_j"), graph.csr("time_s")
        self.Er, self.Tr = graph.csr("energy_j", True), graph.csr("time_s", True)
        for a, b in ((self.E, self.T), (self.Er, self.Tr)):
            if not (np.array_equal(a.indptr, b.indptr) and np.array_equal(a.indices, b.indices)):
                raise ValueError("energy and time graphs must have the same arcs")

    def _csr(self, a, b, we, wt):
        return sparse.csr_matrix((we * a.data + wt * b.data, a.indices, a.indptr), shape=a.shape)

    def route(self, we, wt):
        _, prev = dijkstra(self._csr(self.E, self.T, we, wt), indices=self.h,
                           return_predecessors=True)
        _, nxt = dijkstra(self._csr(self.Er, self.Tr, we, wt), indices=self.h,
                          return_predecessors=True)
        out = follow(prev, self.goal, end=self.h)[::-1]
        back = follow(nxt, self.goal, end=self.h)
        path = np.concatenate([out, back[1:]])
        e = self.g.path_cost(path, "energy_j")
        t = self.g.path_cost(path, "time_s")
        turn = len(out) - 1
        e[turn:] += self.se
        t[turn:] += self.st
        return {"path": path, "turn": turn, "e": e, "t": t}


def round_trip(graph, habitat, goal, budget, objective="energy",
               service_s=0.0, service_power_w=0.0, max_labels=50_000, sweep=7, refine=8):
    """Best habitat -> goal -> habitat route that fits every Budget limit.

    objective: 'energy', 'time' or 'o2'. service_s / service_power_w: work time
    at the goal and the metabolic power while working (added at the turn).
    Returns a profile dict (see _profile). Raises NoFeasibleRoute.
    """
    habitat, goal = int(habitat), int(goal)
    if habitat == goal:
        raise ValueError("goal must differ from the habitat")
    cE, ct = _objective_weights(objective, budget)
    value = lambda e, t: cE * e + ct * t                     # noqa: E731
    svc_e, svc_t = service_power_w * service_s, float(service_s)

    rv_e = graph.costs_to(habitat, "energy_j")
    rv_t = graph.costs_to(habitat, "time_s")
    if not np.isfinite(rv_e[goal]) or not np.isfinite(graph.costs_from(habitat)[goal]):
        raise NoFeasibleRoute("goal is not connected to the habitat")
    W = _Weighted(graph, habitat, goal, svc_e, svc_t)

    # 1. objective alone
    best = W.route(cE, ct)
    lower = value(best["e"][-1], best["t"][-1])                # no route can do better
    if budget.fits(best["e"][-1], best["t"][-1]):
        return _profile(graph, budget, best, rv_e, rv_t, "dijkstra", True, 0.0, lower, 0)

    # 2. lagrangian sweep over supported Pareto routes
    e0 = max(W.route(1.0, 0.0)["e"][-1], 1.0)
    t0 = max(W.route(0.0, 1.0)["t"][-1], 1.0)
    cache = {}

    def at(theta):
        if theta not in cache:
            cache[theta] = W.route(np.cos(theta) / e0, np.sin(theta) / t0)
        return cache[theta]

    def ok(r):
        return budget.fits(r["e"][-1], r["t"][-1])

    thetas = list(np.linspace(0, np.pi / 2, sweep))
    for a, b in zip(thetas[:-1], thetas[1:]):
        if ok(at(a)) != ok(at(b)):
            lo, hi = (a, b) if ok(at(a)) else (b, a)          # lo feasible, hi not
            for _ in range(refine):
                mid = 0.5 * (lo + hi)
                lo, hi = (mid, hi) if ok(at(mid)) else (lo, mid)
    feasible = [r for r in cache.values() if ok(r)]
    lag = min(feasible, key=lambda r: value(r["e"][-1], r["t"][-1])) if feasible else None
    upper = value(lag["e"][-1], lag["t"][-1]) if lag else np.inf

    # 3. exact label-setting, pruned by the lagrangian value
    tg_e = graph.costs_to(goal, "energy_j")
    tg_t = graph.costs_to(goal, "time_s")
    try:
        exact = _label_setting(graph, habitat, goal, budget, cE, ct, upper,
                               rv_e, rv_t, tg_e, tg_t, svc_e, svc_t, max_labels)
    except _LabelLimit as lim:
        if lag is None:
            raise NoFeasibleRoute(f"no supported route fits and the exact search hit "
                                  f"{max_labels} labels; the budget may still be feasible")
        return _profile(graph, budget, lag, rv_e, rv_t, "lagrangian", False,
                        upper - lower, lower, lim.popped)
    if exact is None:
        if lag is None:
            raise NoFeasibleRoute("no route fits the budget")
        return _profile(graph, budget, lag, rv_e, rv_t, "lagrangian", True, 0.0, lower, 0)
    route, popped = exact
    return _profile(graph, budget, route, rv_e, rv_t, "label_setting", True, 0.0, lower, popped)


class _LabelLimit(Exception):
    def __init__(self, popped):
        self.popped = popped


def _label_setting(graph, habitat, goal, budget, cE, ct, upper, rv_e, rv_t, tg_e, tg_t,
                   svc_e, svc_t, max_labels):
    """Exact best route with value < upper, or None if there is none."""
    tail_e, tail_t = svc_e + rv_e[goal], svc_t + rv_t[goal]
    E, T = graph.csr("energy_j"), graph.csr("time_s")
    indptr, indices, de, dt = E.indptr, E.indices, E.data, T.data
    k_o2, leak = 1.0 / 1000.0 / KJ_PER_LITER_O2, budget.leak_lpm / 60.0
    eps = 1e-9 * max(1.0, upper if np.isfinite(upper) else 1.0)

    L_node, L_phase, L_e, L_t, L_parent = [], [], [], [], []
    front, heap = {}, []

    def push(v, phase, e, t, parent):
        if phase == 0:
            le, lt = tg_e[v] + tail_e, tg_t[v] + tail_t
        else:
            le, lt = rv_e[v], rv_t[v]
        fe, ft = e + le, t + lt
        if not (np.isfinite(fe) and fe <= budget.energy_j and ft <= budget.time_s
                and fe * k_o2 + ft * leak <= budget.o2_l):
            return
        pr = cE * fe + ct * ft
        if pr >= upper - eps:
            return
        key = (v, phase)
        f = front.get(key)
        if f is not None:
            for a, b in f:
                if a <= e and b <= t:
                    return
            f[:] = [(a, b) for a, b in f if not (e <= a and t <= b)]
            f.append((e, t))
        else:
            front[key] = [(e, t)]
        L_node.append(v); L_phase.append(phase); L_e.append(e); L_t.append(t)
        L_parent.append(parent)
        heapq.heappush(heap, (pr, len(L_node) - 1))

    push(habitat, 0, 0.0, 0.0, -1)
    popped = 0
    while heap:
        _, i = heapq.heappop(heap)
        v, phase, e, t = L_node[i], L_phase[i], L_e[i], L_t[i]
        if (e, t) not in front.get((v, phase), ()):
            continue
        popped += 1
        if popped > max_labels:
            raise _LabelLimit(popped)
        if phase == 1 and v == habitat:
            chain = []
            while i >= 0:
                chain.append(i)
                i = L_parent[i]
            chain.reverse()
            path = np.array([L_node[j] for j in chain], dtype=np.int64)
            ph = np.array([L_phase[j] for j in chain])
            return ({"path": path, "turn": int(np.argmax(ph == 1)),
                     "e": np.array([L_e[j] for j in chain]),
                     "t": np.array([L_t[j] for j in chain])}, popped)
        a, z = indptr[v], indptr[v + 1]
        for w, ce, ctt in zip(indices[a:z].tolist(), de[a:z].tolist(), dt[a:z].tolist()):
            if phase == 0 and w == goal:
                push(w, 1, e + ce + svc_e, t + ctt + svc_t, i)
            else:
                push(w, phase, e + ce, t + ctt, i)
    return None


def _profile(graph, budget, r, rv_e, rv_t, method, exact, gap, lower, labels):
    path, turn, e, t = r["path"], r["turn"], r["e"], r["t"]
    o2 = budget.o2(e, t)
    # still needed to finish from each point: the planned rest of the trip
    need_e, need_t = e[-1] - e, t[-1] - t
    return {
        "path": path, "turn_index": turn,
        "used_j": e, "time_s": t, "o2_l": o2, "length_m": graph.path_cost(path, "length_m"),
        "rv_j": rv_e[path], "rv_time_s": rv_t[path],           # true R(v), min return
        "slack_j": budget.energy_j - e - need_e,
        "slack_time_s": budget.time_s - t - need_t,
        "slack_o2_l": budget.o2_l - o2 - (budget.o2(e[-1], t[-1]) - o2),
        "usable_j": float(budget.energy_j),
        "feasible": True, "first_violation": None,
        "method": method, "exact": exact, "gap": float(gap), "lower_bound": float(lower),
        "labels_expanded": labels,
    }


def min_slack(prof):
    """Smallest slack of each limit along the route (J, s, L)."""
    return {"energy_j": float(np.min(prof["slack_j"])),
            "time_s": float(np.min(prof["slack_time_s"])),
            "o2_l": float(np.min(prof["slack_o2_l"]))}
