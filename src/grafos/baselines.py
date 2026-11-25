"""MVP baselines for E4 (issue #8): how simple EVA planners judge a round trip.

Every method moves on the SAME graph as the MVP (E3 arcs: |slope along the move|
<= 20 deg, cells with slope_deg > 30 deg blocked), so only the cost model and the
safety rule change. Each one has a route and a verdict ("safe" or not):

  B1 A*-slope    route: shortest DISTANCE (A* with the octile heuristic) under the
                 slope limits; verdict: round-trip length x flat-ground energy per
                 metre <= budget.
  B2 radius      route: same as B1; verdict: straight-line distance to the habitat
                 <= r, with r = budget / (2 x flat energy per metre) (Apollo-style
                 walkback radius).
  B3 linear-O2   route: shortest TIME out and back (E3 times); verdict: oxygen at a
                 constant metabolic rate, O2 = RATE_W x time / 20.1 kJ/L, fits the
                 O2 equivalent of the budget (same as RATE_W x time <= budget).
  MVP            route: minimum E3 energy out and back; verdict: exact,
                 g(goal) + R(goal) <= budget (walkback holds at every point).

Ground truth for every route: its E3 energy. A baseline is "falsely safe" when it
says safe but its own route needs more than the budget (the dangerous error).
B1/B2 come back along the same path reversed (arcs are symmetric in existence).
"""

import heapq
import sys
from pathlib import Path

import numpy as np

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fisica.metabolic import KJ_PER_LITER_O2, segment_cost  # noqa: E402
from grafos.graph import follow  # noqa: E402

FLAT_TIME_S_PER_M, FLAT_J_PER_M = segment_cost(1.0, 0.0)   # ~1.333 s/m, ~389.6 J/m
RATE_W = 293.0     # ~1000 BTU/h, ISS EMU average planning rate [NASA-Mars-mass]
METHODS = ("B1_astar_slope", "B2_fixed_radius", "B3_linear_o2", "MVP_e4")


def octile(graph, a, b):
    """Admissible distance heuristic (m) between nodes on an 8-neighbour grid."""
    (ra, ca), (rb, cb) = graph.cell(a), graph.cell(b)
    dr, dc = np.abs(ra - rb), np.abs(ca - cb)
    cell = abs(graph.transform[0]) if graph.transform is not None else 1.0
    return cell * (np.maximum(dr, dc) + (np.sqrt(2) - 1) * np.minimum(dr, dc))


def astar(graph, source, target, weight="length_m"):
    """A* shortest path (node array) and its cost. With weight='length_m' the
    octile heuristic is admissible and consistent, so the path is optimal."""
    m = graph.csr(weight)
    indptr, indices, data = m.indptr, m.indices, m.data
    source, target = int(source), int(target)
    tr, tc = graph.cell(target)
    cell = abs(graph.transform[0]) if graph.transform is not None else 1.0
    k = np.sqrt(2) - 1

    def h(v):
        r, c = divmod(v, graph.width)
        dr, dc = abs(r - tr), abs(c - tc)
        return cell * (max(dr, dc) + k * min(dr, dc)) if weight == "length_m" else 0.0

    dist = {source: 0.0}
    prev = {source: -1}
    heap = [(h(source), 0.0, source)]
    closed = set()
    while heap:
        _, d, v = heapq.heappop(heap)
        if v in closed:
            continue
        if v == target:
            path = [v]
            while prev[path[-1]] >= 0:
                path.append(prev[path[-1]])
            return np.array(path[::-1], dtype=np.int64), d
        closed.add(v)
        a, z = indptr[v], indptr[v + 1]
        for w, c in zip(indices[a:z].tolist(), data[a:z].tolist()):
            nd = d + c
            if nd < dist.get(w, np.inf):
                dist[w] = nd
                prev[w] = v
                heapq.heappush(heap, (nd + h(w), nd, w))
    raise ValueError("target not reachable")


class BaselineEvaluator:
    """All trees from one habitat, then cheap per-goal evaluation of every method."""

    def __init__(self, graph, habitat):
        self.g, self.h = graph, int(habitat)
        # MVP: exact energy out (g) and back (R)
        self.g_e = graph.costs_from(self.h, "energy_j")
        self.r_e = graph.costs_to(self.h, "energy_j")
        # B1/B2: shortest-distance tree from the habitat
        self.len_out, self.len_pred = graph.costs_from(self.h, "length_m", predecessors=True)
        # B3: shortest-time trees out and back
        self.t_out, self.t_pred = graph.costs_from(self.h, "time_s", predecessors=True)
        self.t_back, self.t_next = graph.costs_to(self.h, "time_s", predecessors=True)
        self.loop_e = self.g_e + self.r_e

    def farthest_loop_j(self):
        """Most expensive exact round trip from this habitat (sets relative budgets)."""
        f = self.loop_e[np.isfinite(self.loop_e)]
        return float(f.max())

    def _route_energy(self, path):
        return float(self.g.path_cost(path, "energy_j")[-1])

    def evaluate(self, goal, budget_j):
        """One dict per method for this goal: verdict, estimate, real E3 energy."""
        goal = int(goal)
        g = self.g
        out = []
        # B1 / B2 share the distance route, back by the same path reversed
        d_path = follow(self.len_pred, goal, end=self.h)[::-1]
        d_loop = np.concatenate([d_path, d_path[::-1][1:]])
        d_real = self._route_energy(d_loop)
        d_len = 2.0 * float(self.len_out[goal])
        d_time = float(g.path_cost(d_loop, "time_s")[-1])
        b1_est = d_len * FLAT_J_PER_M
        out.append({"method": "B1_astar_slope", "estimate_j": b1_est,
                    "safe": b1_est <= budget_j, "real_j": d_real,
                    "length_m": d_len, "time_s": d_time})
        radius = budget_j / (2.0 * FLAT_J_PER_M)
        (rg, cg), (rh, ch) = g.cell(goal), g.cell(self.h)
        cell = abs(g.transform[0]) if g.transform is not None else 1.0
        straight = float(np.hypot(rg - rh, cg - ch) * cell)
        out.append({"method": "B2_fixed_radius", "estimate_j": 2.0 * straight * FLAT_J_PER_M,
                    "safe": straight <= radius, "real_j": d_real,
                    "length_m": d_len, "time_s": d_time, "radius_m": radius,
                    "straight_m": straight})
        # B3: shortest time out and back, O2 at a constant rate
        t_go = follow(self.t_pred, goal, end=self.h)[::-1]
        t_back = follow(self.t_next, goal, end=self.h)
        t_loop = np.concatenate([t_go, t_back[1:]])
        t_total = float(self.t_out[goal] + self.t_back[goal])
        b3_est = RATE_W * t_total
        out.append({"method": "B3_linear_o2", "estimate_j": b3_est,
                    "estimate_o2_l": b3_est / 1000.0 / KJ_PER_LITER_O2,
                    "safe": b3_est <= budget_j, "real_j": self._route_energy(t_loop),
                    "length_m": float(g.path_cost(t_loop, "length_m")[-1]),
                    "time_s": t_total})
        # MVP: exact
        e_star = float(self.loop_e[goal])
        out.append({"method": "MVP_e4", "estimate_j": e_star, "safe": e_star <= budget_j,
                    "real_j": e_star, "length_m": np.nan, "time_s": np.nan})
        for r in out:
            r["optimal_j"] = e_star
            r["really_feasible"] = r["real_j"] <= budget_j     # its own route fits
            r["any_route_feasible"] = e_star <= budget_j       # the goal is reachable at all
        return out

    def routes(self, goal):
        """Node paths of every method (for GeoJSON), keyed by method."""
        goal = int(goal)
        d_path = follow(self.len_pred, goal, end=self.h)[::-1]
        d_loop = np.concatenate([d_path, d_path[::-1][1:]])
        t_loop = np.concatenate([follow(self.t_pred, goal, end=self.h)[::-1],
                                 follow(self.t_next, goal, end=self.h)[1:]])
        return {"B1_astar_slope": (d_loop, len(d_path) - 1),
                "B2_fixed_radius": (d_loop, len(d_path) - 1),
                "B3_linear_o2": (t_loop, int(np.argmax(t_loop == goal)))}


def summarise(rows):
    """Confusion counts per method from evaluate() rows (one budget level)."""
    out = {}
    for m in METHODS:
        rs = [r for r in rows if r["method"] == m]
        n = len(rs)
        said = np.array([r["safe"] for r in rs])
        own_ok = np.array([r["really_feasible"] for r in rs])
        any_ok = np.array([r["any_route_feasible"] for r in rs])
        over = np.array([r["real_j"] / r["optimal_j"] - 1 for r in rs if np.isfinite(r["optimal_j"])])
        # how far the method's own estimate is from the real E3 energy of its route
        ratio = np.array([r["real_j"] / r["estimate_j"] for r in rs if r["estimate_j"] > 0])
        out[m] = {
            "n": n,
            "said_safe": int(said.sum()),
            # dangerous: said safe but its own route does not fit the budget
            "false_safe": int((said & ~own_ok).sum()),
            "false_safe_rate_of_said_safe": float((said & ~own_ok).sum() / max(said.sum(), 1)),
            # said safe for a goal no route can do within budget
            "said_safe_but_impossible": int((said & ~any_ok).sum()),
            # too conservative: said no although the exact plan fits
            "false_unsafe": int((~said & any_ok).sum()),
            "missed_fraction_of_feasible": float((~said & any_ok).sum() / max(any_ok.sum(), 1)),
            "energy_overcost_median": float(np.median(over)) if len(over) else np.nan,
            "energy_overcost_p95": float(np.percentile(over, 95)) if len(over) else np.nan,
            # real / estimated energy: > 1 means the method underestimates
            "real_over_estimate_median": float(np.median(ratio)) if len(ratio) else np.nan,
            # budget factor the method would need so that no goal is falsely safe
            "safety_factor_needed_p99": float(np.percentile(ratio, 99)) if len(ratio) else np.nan,
            "safety_factor_needed_max": float(ratio.max()) if len(ratio) else np.nan,
        }
    return out
