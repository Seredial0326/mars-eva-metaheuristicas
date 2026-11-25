"""E4 - Exact walkback: R(v) and routes that can always return (issue #7).

R(v) = minimum energy to go from cell v back to the habitat, from ONE Dijkstra
on the reversed graph (each arc keeps the cost of its original direction, since
going up costs more than going down).

Walkback rule at every point v of a route:
    used(v) + R(v) <= (1 - margin) * budget        ("usable" energy)
The slack usable - used(v) - R(v) is what is left; the first point where it goes
negative is past the point of no return.

For a single resource (energy), label-setting with this rule reduces to Dijkstra
from the habitat with pruning: the minimum `used(v)` is a dominating label, so a
cell is reachable-and-returnable iff g(v) + R(v) <= usable, where g = forward
Dijkstra. Multi-resource labels (energy + time/O2) are a later step.
"""

import sys
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

if __package__ in (None, ""):          # run as a script: make `grafos` importable
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.graph import Graph, follow  # noqa: E402

J_PER_WH = 3600.0


@dataclass
class Walkback:
    """R(v), g(v) and the safe region for one habitat."""
    graph: Graph
    habitat: int                     # node id
    rv_j: np.ndarray                 # (n,) cost cell -> habitat, inf = cannot return
    g_j: np.ndarray                  # (n,) cost habitat -> cell, inf = unreachable
    next_hop: np.ndarray = field(repr=False)   # next node towards the habitat
    prev_hop: np.ndarray = field(repr=False)   # previous node from the habitat

    @classmethod
    def compute(cls, graph, habitat):
        rv, next_hop = graph.costs_to(habitat, predecessors=True)
        g, prev_hop = graph.costs_from(habitat, predecessors=True)
        return cls(graph, int(habitat), rv, g, next_hop, prev_hop)

    def raster(self, values):
        """(n,) -> float32 grid with NaN where the value is infinite."""
        a = np.asarray(values, dtype=np.float64).reshape(self.graph.shape)
        return np.where(np.isfinite(a), a, np.nan).astype(np.float32)

    def safe_mask(self, usable_j):
        """Cells the astronaut can reach from the habitat AND come back from."""
        return (self.g_j + self.rv_j) <= usable_j

    def round_trip(self, goal, usable_j):
        """Minimum-energy habitat -> goal -> habitat, with the walkback profile.

        Along a minimum-energy outbound path, used(v) + R(v) is non-decreasing
        (triangle inequality), so the round trip is feasible iff it holds at the goal.
        """
        goal = int(goal)
        if not np.isfinite(self.g_j[goal]) or not np.isfinite(self.rv_j[goal]):
            raise ValueError("goal cannot be reached from, or cannot return to, the habitat")
        out = follow(self.prev_hop, goal, end=self.habitat)[::-1]
        back = follow(self.next_hop, goal, end=self.habitat)
        path = np.concatenate([out, back[1:]])
        prof = check_walkback(self.graph, path, self.rv_j, usable_j)
        prof["turn_index"] = len(out) - 1
        return prof


def check_walkback(graph, path, rv_j, usable_j):
    """Walkback profile of ANY node path (E4 route, E5 tour, baselines).

    Returns a dict with per-point arrays (used_j, rv_j, slack_j, time_s) and
    `first_violation`: index of the first point with negative slack, or None.
    """
    path = np.asarray(path, dtype=np.int64)
    used = graph.path_cost(path, "energy_j")
    t = graph.path_cost(path, "time_s")
    length = graph.path_cost(path, "length_m")
    rv = np.asarray(rv_j)[path]
    slack = usable_j - used - rv
    bad = np.nonzero(slack < 0)[0]
    return {
        "path": path,
        "used_j": used,
        "rv_j": rv,
        "slack_j": slack,
        "time_s": t,
        "length_m": length,
        "usable_j": float(usable_j),
        "feasible": bool(len(bad) == 0),
        "first_violation": int(bad[0]) if len(bad) else None,
    }


if __name__ == "__main__":
    # This file is a library; running it is the same as running build_rv.py.
    from grafos.build_rv import main
    main()
