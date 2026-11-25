"""C2: spatial units, directionality, immutable inputs and closed-loop margins."""
from pathlib import Path
import sys

import numpy as np
import pytest
from scipy import sparse
from scipy.sparse.csgraph import dijkstra

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from fisica.missed_sand import (arrival_scaled, conservative_proxy, hidden_field,
                                loop_metrics, mean_ci, missed_sites, route_overlap)


def test_labels_are_scaled_and_grouped_as_spatial_units():
    points = [{"row": 8, "col": 12, "answer": 2, "stratum": 0},
              {"row": 12, "col": 12, "answer": 2, "stratum": 1},
              {"row": 80, "col": 80, "answer": 2, "stratum": 2}]
    sites, count = missed_sites(points, (30, 30), block_m=10)
    assert count == 2
    np.testing.assert_allclose(sites, [[2.5, 3.]])


def test_hidden_world_is_reproducible_and_preserves_nominal_map():
    sand = np.zeros((40, 40))
    sand[20, 20] = 1
    original = sand.copy()
    support = np.zeros_like(sand, bool)
    support[15:25, 15:25] = True
    sites = np.array([[20, 20]])
    a = hidden_field(sand, sites, 8, 3, support, presence=1)
    b = hidden_field(sand, sites, 8, 3, support, presence=1)
    np.testing.assert_array_equal(a, b)
    np.testing.assert_array_equal(sand, original)
    assert not a[~support].any()
    assert a[20, 20] == 0
    assert a.sum() > 0


def test_conservative_proxy_cannot_recover_distant_missed_class():
    sand = np.zeros((40, 40))
    hidden = hidden_field(sand, [[20, 20]], 4, 1, presence=1)
    assert hidden.sum() > 0
    assert conservative_proxy(sand).sum() == 0


def test_arrival_cell_scaling_keeps_direction_and_source_unchanged():
    base = sparse.csr_matrix([[0., 2.], [3., 0.]])
    result = arrival_scaled(base, [2., 4.])
    assert result[0, 1] == 8
    assert result[1, 0] == 6
    assert base[0, 1] == 2
    assert base[1, 0] == 3


def test_closed_loop_margin_equals_exact_worst_vertex_margin():
    base = sparse.csr_matrix([[0., 3600, 10000], [7200, 0, 3600], [3600, 7200, 0]])
    path = np.array([0, 1, 2, 0])
    hidden = np.array([0, 1, .5])
    truth = arrival_scaled(base, 1 + hidden)
    energy = np.r_[0., np.cumsum(np.asarray(truth[path[:-1], path[1:]]).ravel() / 3600)]
    r = dijkstra(truth.T.tocsr(), indices=0) / 3600
    expected = float(np.min(10 - energy - r[path]))
    result = loop_metrics(base, path, hidden, beta=1, usable_wh=10)
    assert result["margin_wh"] == pytest.approx(expected)
    assert result["actual_wh"] == pytest.approx(4.5)
    assert not result["reserve_violated"]
    assert loop_metrics(base, path, hidden, 1, 4)["reserve_violated"]


def test_zero_penalty_separates_segmentation_from_metabolic_uncertainty():
    base = sparse.csr_matrix([[0., 3600], [7200, 0]])
    assert loop_metrics(base, [0, 1, 0], [1, 1], 0, 5)["actual_wh"] == 3


def test_open_route_cannot_use_closed_loop_margin_identity():
    with pytest.raises(ValueError, match="closed"):
        loop_metrics(sparse.csr_matrix([[0., 3600], [7200, 0]]), [0, 1], [1, 1], 1, 10)


def test_route_overlap_uses_directed_edges():
    assert route_overlap([0, 1, 2, 0], [0, 2, 1, 0]) == 0
    assert route_overlap([0, 1, 0], [0, 1, 0]) == 1


def test_bootstrap_unit_is_world_not_raster_pixel():
    summary = mean_ci([1, 2, 3])
    assert summary["mean"] == 2
    assert "world" in summary["unit"]
    assert summary == mean_ci([1, 2, 3])
