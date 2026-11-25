"""E9 helpers that do not need Detectron2 or the data: tiling ownership, block means,
validation split and the student network's shapes."""

import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")   # torch + SciPy OpenMP (as in E1)

import numpy as np  # noqa: E402
import pytest  # noqa: E402

torch = pytest.importorskip("torch")
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from dl_rocas.distill import TinyUNet, block_mean, n_params, val_blocks  # noqa: E402
from dl_rocas.teacher import STRIDE, TILE, box_iou, own_block, tile_origins  # noqa: E402


@pytest.mark.parametrize("n", [500, 501, 749, 750, 1000, 8000, 8123])
def test_tiles_cover_the_image(n):
    starts = tile_origins(n)
    assert starts[0] == 0 and starts[-1] + TILE == n
    covered = np.zeros(n, bool)
    for s in starts:
        covered[s:s + TILE] = True
    assert covered.all()


@pytest.mark.parametrize("n", [500, 749, 1000, 8000, 8123])
def test_every_pixel_owned_by_exactly_one_tile(n):
    """The kept central blocks partition [0, n): no boulder is lost or counted twice."""
    owners = np.zeros(n, int)
    for s in tile_origins(n):
        lo, hi = own_block(s, n)
        assert s <= lo < hi <= s + TILE          # a tile only keeps what it sees
        owners[lo:hi] += 1
    assert (owners == 1).all()


def test_kept_block_is_away_from_inner_tile_edges():
    n = 8000
    for s in tile_origins(n):
        lo, hi = own_block(s, n)
        if s > 0:
            assert lo - s >= (TILE - STRIDE) // 2
        if s + TILE < n:
            assert s + TILE - hi >= (TILE - STRIDE) // 2 - 1


def test_box_iou():
    a = np.array([[0, 0, 10, 10]], float)
    b = np.array([[0, 0, 10, 10], [5, 0, 15, 10], [20, 20, 30, 30]], float)
    np.testing.assert_allclose(box_iou(a, b)[0], [1.0, 1 / 3, 0.0])


def test_block_mean():
    a = np.arange(16, dtype=float).reshape(4, 4)
    np.testing.assert_allclose(block_mean(a, 2), [[2.5, 4.5], [10.5, 12.5]])


def test_validation_blocks_spread_and_about_a_fifth():
    v = val_blocks(8)
    assert 0.15 <= len(v) / 64 <= 0.25
    assert {by for by, _ in v} == set(range(8))     # every block row has validation
    assert {bx for _, bx in v} == set(range(8))


def test_student_shapes_and_size():
    m = TinyUNet(32).eval()
    with torch.no_grad():
        y = m(torch.zeros(2, 1, 64, 96))
    assert y.shape == (2, 1, 64, 96)
    assert 0.5e6 < n_params(m) < 1.5e6               # ~47x smaller than BoulderNet
