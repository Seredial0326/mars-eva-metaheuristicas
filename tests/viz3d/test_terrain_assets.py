"""Tests for the 3D terrain assets (P1, issue #42) on small synthetic grids,
plus a check of the real assets when they have been built."""

import json
import os
import sys
from pathlib import Path

import numpy as np
import pytest
import rasterio
from rasterio.transform import from_origin

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from viz3d import build_terrain_assets as bta  # noqa: E402

DATA = Path(os.environ.get("MARTIAN_DATA", REPO / "data"))


def test_block_mean_keeps_block_centres():
    a = np.arange(16, dtype=float).reshape(4, 4)
    assert bta.block_mean(a, 2).tolist() == [[2.5, 4.5], [10.5, 12.5]]


def test_quantize_roundtrip_is_within_half_a_step():
    rng = np.random.default_rng(0)
    a = -3876.0 + 475.0 * rng.random((50, 60))
    q, offset, scale = bta.quantize(a)
    assert q.dtype == np.dtype("<u2")
    assert scale < 0.01                                   # under 1 cm per step
    assert np.abs(bta.dequantize(q, offset, scale) - a).max() <= scale / 2 + 1e-9


def test_slopes_follow_east_and_north_with_row0_north():
    rows, cols = np.mgrid[0:20, 0:30]
    east_ramp = 0.3 * cols                                # rises 0.3 m per metre east
    north_ramp = -0.2 * rows                              # row 0 is north: rises 0.2 m/m north
    de, dn = bta.slopes(east_ramp)
    assert np.allclose(de, 0.3) and np.allclose(dn, 0.0)
    de, dn = bta.slopes(north_ramp)
    assert np.allclose(de, 0.0) and np.allclose(dn, 0.2)


def test_normal_map_flat_is_up_and_ramp_leans_downhill():
    flat = bta.normal_map(np.zeros((4, 4)), np.zeros((4, 4)))
    assert (flat == [128, 128, 255]).all()
    # Ground rising to the east: the normal leans west (R < 128), no north component.
    ramp = bta.normal_map(np.full((4, 4), 0.25), np.zeros((4, 4)))
    assert (ramp[..., 0] < 128).all() and (ramp[..., 1] == 128).all()
    # Ground rising to the north: the normal leans south (G < 128).
    ramp = bta.normal_map(np.zeros((4, 4)), np.full((4, 4), 0.25))
    assert (ramp[..., 1] < 128).all() and (ramp[..., 0] == 128).all()


def test_normal_map_decodes_back_to_the_slopes():
    rng = np.random.default_rng(1)
    de, dn = rng.uniform(-0.6, 0.6, (2, 30, 30))
    back_e, back_n = bta.decode_normal_slopes(bta.normal_map(de, dn))
    assert np.abs(back_e - de).max() < 0.02 and np.abs(back_n - dn).max() < 0.02


def test_split_relief_separates_hillside_from_a_ridge():
    rows, cols = np.mgrid[0:200, 0:200]
    hillside = 0.2 * cols                                  # 40 m over 200 m
    ridge = 1.5 * np.exp(-((cols - 100) / 6.0) ** 2)       # 1.5 m high, about 20 m wide
    low, detail = bta.split_relief(hillside + ridge)
    middle = (slice(60, 140), slice(60, 140))
    assert np.abs(low[middle] - hillside[middle]).max() < 0.6     # the hillside stays in `low`
    assert 0.8 < detail[100, 100] < 1.5                           # most of the ridge is detail
    assert abs(detail[100, 70]) < 0.35                            # and away from it, little is


def test_mesh_error_is_zero_on_a_plane_and_grows_with_spacing():
    rows, cols = np.mgrid[0:64, 0:64]
    plane = 0.1 * rows + 0.3 * cols
    assert bta.mesh_error(plane, 2)["max"] < 1e-6
    bumpy = plane + np.sin(rows / 2.0) * np.cos(cols / 3.0)
    assert bta.mesh_error(bumpy, 2)["p95"] < bta.mesh_error(bumpy, 4)["p95"]


def test_ortho_tiles_cover_the_image_and_overlap():
    tiles = bta.ortho_tiles(8000)
    assert [(r, c) for r, c, _, _ in tiles] == [(0, 0), (0, 1), (1, 0), (1, 1)]
    assert {top for _, _, top, _ in tiles} == {0, 8000 - 4096}


def test_build_writes_every_asset(tmp_path):
    """End to end on a tiny synthetic base grid (64 x 64 m)."""
    base = tmp_path / "base"
    base.mkdir()
    n = 64
    rows, cols = np.mgrid[0:n, 0:n]
    dem = (-3600.0 + 0.2 * cols - 0.1 * rows).astype("float32")
    with rasterio.open(base / "dem_1m.tif", "w", driver="GTiff", width=n, height=n, count=1,
                       dtype="float32", transform=from_origin(1000.0, 5000.0, 1.0, 1.0)) as dst:
        dst.write(dem, 1)
    ortho = np.zeros((3, 4 * n, 4 * n), dtype="uint8")
    ortho[0, : 2 * n] = 200                                # north half red
    with rasterio.open(base / "ortho_color_025.tif", "w", driver="GTiff", width=4 * n,
                       height=4 * n, count=3, dtype="uint8",
                       transform=from_origin(1000.0, 5000.0, 0.25, 0.25)) as dst:
        dst.write(ortho)
    (base / "grid.json").write_text(json.dumps({"bbox": {
        "xmin": 1000.0, "ymin": 5000.0 - n, "xmax": 1000.0 + n, "ymax": 5000.0}}))

    old_low, old_tile = bta.ORTHO_LOW_PX, bta.ORTHO_TILE_PX
    bta.ORTHO_LOW_PX, bta.ORTHO_TILE_PX = 128, 160
    try:
        meta = bta.build(tmp_path, tmp_path / "tiles" / "3d")
    finally:
        bta.ORTHO_LOW_PX, bta.ORTHO_TILE_PX = old_low, old_tile

    out = tmp_path / "tiles" / "3d"
    saved = json.loads((out / "terrain.json").read_text(encoding="utf-8"))
    assert saved["grid"]["rows"] == saved["grid"]["cols"] == n // 2
    height = saved["layers"]["height"]
    q = np.fromfile(out / height["file"], dtype="<u2").reshape(n // 2, n // 2)
    z = bta.dequantize(q, height["offset_m"], height["scale_m"])
    assert np.abs(z - bta.block_mean(dem.astype(float), 2)).max() < 0.01
    assert z[0, 0] > z[-1, 0] and z[0, -1] > z[0, 0]       # row 0 north (higher), col 0 west
    for name in ("height_low_2m.bin", "detail_2m.bin", "normal_detail.png", "ortho_128.jpg",
                 "ortho_hi_00.jpg", "ortho_hi_11.jpg"):
        assert (out / name).stat().st_size > 0
    assert meta["mesh_error_m"]["2"]["max"] < 0.01         # a plane is reproduced exactly


@pytest.mark.skipif(not (DATA / "tiles" / "3d" / "terrain.json").exists(),
                    reason="3D assets not built (python src/viz3d/build_terrain_assets.py)")
def test_real_assets_match_the_dem():
    out = DATA / "tiles" / "3d"
    meta = json.loads((out / "terrain.json").read_text(encoding="utf-8"))
    g, layer = meta["grid"], meta["layers"]["height"]
    q = np.fromfile(out / layer["file"], dtype="<u2").reshape(g["rows"], g["cols"])
    z = bta.dequantize(q, layer["offset_m"], layer["scale_m"])
    with rasterio.open(DATA / "base" / "dem_1m.tif") as src:
        dem = src.read(1).astype(np.float64)
    assert np.abs(z - bta.block_mean(dem, 2)).max() < 0.02          # under 2 cm everywhere
    # Orientation: the north-west corner is the lowest of the four, the south-east the highest.
    corners = {"nw": z[0, 0], "ne": z[0, -1], "sw": z[-1, 0], "se": z[-1, -1]}
    assert min(corners, key=corners.get) == "nw" and max(corners, key=corners.get) == "se"
    assert abs(z[0, 0] - dem[:2, :2].mean()) < 0.02
    assert meta["mesh_error_m"]["2"]["p95"] < meta["mesh_error_m"]["4"]["p95"] < 1.0
