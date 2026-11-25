"""Tests for the grid graph and walkback on small synthetic DEMs."""

import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from fisica.edge_cost import NEIGHBOURS, edge_costs  # noqa: E402
from grafos.graph import Graph, follow  # noqa: E402
from grafos.walkback import Walkback, check_walkback  # noqa: E402

TRANSFORM = (1.0, 0.0, 100.0, 0.0, -1.0, 50.0)


def make_graph(dem, **kw):
    t, e, _ = edge_costs(dem, **kw)
    return Graph({"energy_j": e, "time_s": t}, NEIGHBOURS, transform=TRANSFORM)


def test_node_and_cell_roundtrip():
    g = make_graph(np.zeros((4, 6)))
    n = g.node(2, 5)
    assert n == 2 * 6 + 5
    assert tuple(g.cell(n)) == (2, 5)
    x, y = g.cell_to_xy(2, 5)
    assert (x, y) == (105.5, 47.5)
    assert tuple(g.xy_to_cell(x, y)) == (2, 5)


def test_arc_count_on_flat_grid():
    h, w = 5, 7
    g = make_graph(np.zeros((h, w)))
    straight = 2 * (h * (w - 1) + w * (h - 1))
    diagonal = 4 * (h - 1) * (w - 1)
    assert g.csr().nnz == straight + diagonal


def test_flat_shortest_path_is_chebyshev():
    g = make_graph(np.zeros((10, 10)))
    d = g.costs_from(g.node(0, 0), weight="length_m")
    assert d[g.node(3, 7)] == pytest.approx(3 * np.sqrt(2) + 4)


def test_reverse_keeps_original_arc_cost():
    dem = np.tile(np.arange(10.0) * 0.2, (3, 1))            # ramp rising to the east
    g = make_graph(dem)
    a, b = g.node(1, 0), g.node(1, 9)
    up = g.costs_from(a)[b]                                 # a -> b climbs
    assert g.costs_to(b)[a] == pytest.approx(up)            # same quantity, reversed graph
    assert g.costs_from(b)[a] < up                          # going down is cheaper


def test_negative_weights_rejected():
    e = np.ones((8, 3, 3))
    e[0, 1, 1] = -1
    with pytest.raises(ValueError):
        Graph({"energy_j": e}, NEIGHBOURS)


def test_snap_skips_blocked_cells():
    dem = np.zeros((7, 7))
    slope = np.zeros((7, 7))
    slope[2:5, 2:5] = 45                                    # blocked block in the middle
    g = make_graph(dem, cell_slope_deg=slope)
    r, c = g.snap(3, 3)
    assert not (2 <= r <= 4 and 2 <= c <= 4)
    assert abs(r - 3) <= 2 and abs(c - 3) <= 2


def test_place_raises_outside_and_moves_blocked():
    dem = np.zeros((9, 9))
    slope = np.zeros((9, 9))
    slope[3:6, 3:6] = 45                                    # blocked block in the middle
    g = make_graph(dem, cell_slope_deg=slope)
    x, y = g.cell_to_xy(1, 1)
    assert g.place(x, y) == (1, 1, 0.0)                     # valid cell: unchanged
    x, y = g.cell_to_xy(4, 4)
    r, c, moved = g.place(x, y)
    assert g.main_component()[r, c] and moved == pytest.approx(np.hypot(r - 4, c - 4))
    with pytest.raises(ValueError):
        g.place(0.0, 0.0)                                   # outside the grid


def test_follow_and_path_cost():
    g = make_graph(np.zeros((6, 6)))
    s, t = g.node(0, 0), g.node(5, 3)
    d, pred = g.costs_from(s, predecessors=True)
    path = follow(pred, t, end=s)[::-1]
    assert path[0] == s and path[-1] == t
    assert g.path_cost(path)[-1] == pytest.approx(d[t])


def test_cost_matrix_is_directed():
    dem = np.tile(np.arange(8.0) * 0.2, (3, 1))
    g = make_graph(dem)
    m = g.cost_matrix([g.node(1, 0), g.node(1, 7)])
    assert m[0, 0] == 0 and m[1, 1] == 0
    assert m[0, 1] > m[1, 0]


def test_walkback_round_trip_and_safe_region():
    dem = np.tile(np.arange(20.0) * 0.15, (5, 1))
    g = make_graph(dem)
    hab = g.node(2, 0)
    wb = Walkback.compute(g, hab)
    goal = g.node(2, 19)
    loop = wb.g_j[goal] + wb.rv_j[goal]

    prof = wb.round_trip(goal, usable_j=loop * 1.01)
    assert prof["feasible"] and prof["path"][0] == hab and prof["path"][-1] == hab
    assert prof["used_j"][-1] == pytest.approx(loop)
    assert prof["slack_j"].min() == pytest.approx(loop * 0.01, rel=1e-6)

    assert not wb.safe_mask(loop * 0.99).reshape(g.shape)[2, 19]
    assert not wb.round_trip(goal, usable_j=loop * 0.99)["feasible"]


def test_check_walkback_finds_point_of_no_return():
    g = make_graph(np.zeros((1, 30)))
    wb = Walkback.compute(g, g.node(0, 0))
    path = g.node(0, np.arange(30))                         # go east, never come back
    step = wb.rv_j[g.node(0, 1)]                            # energy of one 1 m move
    prof = check_walkback(g, path, wb.rv_j, usable_j=20 * step)
    # used(v) + R(v) = 2 * col * step  ->  first violation at col 11
    assert prof["first_violation"] == 11
    assert not prof["feasible"]
