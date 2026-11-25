"""Build the browser assets of the 3D map (P1, issue #42) from the base grid.

Run from the repo root (about 1 min):
    python src/viz3d/build_terrain_assets.py [--data-dir data] [--out-dir <data-dir>/tiles/3d]

--data-dir defaults to the MARTIAN_DATA environment variable, else <repo>/data
(the same rule as api/main.py). The output goes inside data/tiles/ because the API
already serves that folder at /tiles/, so the 3D page needs no API change.

NOTE: data/tiles/3d/ is NOT part of the tiles-v2 release. If data/tiles/ is
downloaded or unzipped again, run this script again.

Reads data/base/dem_1m.tif and data/base/ortho_color_025.tif. Writes:
    height_2m.bin         uint16 LE, 1000 x 1000: DEM, mean of each 2 x 2 m block
    height_low_2m.bin     same grid: DEM smoothed with a Gaussian (sigma 25 m), the "hillside"
    detail_2m.bin         same grid: local relief = Gaussian(DEM - hillside, sigma 3 m)
    normal_detail.png     1000 x 1000 RGB: tangent-space normal map of the local relief
    ortho_4096.jpg        whole box at 4096 px (low quality preset)
    ortho_hi_<r><c>.jpg   four overlapping 4096 px tiles at the native 0.25 m (high preset)
    terrain.json          grid, encodings, measured mesh error and exaggeration check

Grid convention (all layers): row 0 = north, column 0 = west. Value (i, j) of the
2 m grid sits at the centre of its block: (2j + 1) m east of xmin, (2i + 1) m south
of ymax. Decode a layer with z = offset_m + scale_m * uint16.

The page draws   shown = height + (k - 1) * detail   so k = 1 is the DEM itself and
k > 1 exaggerates only the smoothed local relief, not the 475 m hillside and not the
pixel-scale noise of the DEM.
"""

import argparse
import json
import os
import time
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from scipy import ndimage as ndi

MESH_STEP_M = 2            # spacing of the stored grids
LOW_SIGMA_M = 25.0         # Gaussian that separates the hillside from the local relief
DETAIL_SIGMA_M = 3.0       # Gaussian on the local relief: below this the 1 m DEM is noise
NORMAL_GAIN = 4.0          # slopes are multiplied by this before encoding (8-bit precision)
ORTHO_LOW_PX = 4096
ORTHO_TILE_PX = 4096       # 4096 px * 0.25 m = 1024 m per tile; two tiles overlap by 48 m
JPEG_QUALITY = 90
EXAGGERATIONS = (1, 2, 3, 5, 10)


def block_mean(a, f):
    """Mean of each f x f block (the array sides must be multiples of f)."""
    rows, cols = a.shape
    return a.reshape(rows // f, f, cols // f, f).mean(axis=(1, 3))


def split_relief(dem, low_sigma=LOW_SIGMA_M, detail_sigma=DETAIL_SIGMA_M):
    """(hillside, smoothed local relief) on the DEM grid, in metres."""
    low = ndi.gaussian_filter(dem, low_sigma, mode="reflect")
    detail = ndi.gaussian_filter(dem - low, detail_sigma, mode="reflect")
    return low, detail


def quantize(a):
    """float array -> (uint16 array, offset, scale) with a = offset + scale * q."""
    lo, hi = float(a.min()), float(a.max())
    scale = (hi - lo) / 65535.0 or 1.0
    q = np.round((a - lo) / scale).astype("<u2")
    return q, lo, scale


def dequantize(q, offset, scale):
    return offset + scale * q.astype(np.float64)


def slopes(field, cell_m=1.0):
    """(d/d east, d/d north) of a raster whose row 0 is north."""
    d_east = np.gradient(field, cell_m, axis=1)
    d_north = -np.gradient(field, cell_m, axis=0)
    return d_east, d_north


def normal_map(d_east, d_north, gain=NORMAL_GAIN):
    """uint8 RGB tangent-space normal map: R = east, G = north, B = up.

    Encodes normalize(-gain * d_east, -gain * d_north, 1). In three.js, with
    normalScale = k / gain, the shaded slope is k times the stored one.
    """
    n = np.stack([-gain * d_east, -gain * d_north, np.ones_like(d_east)], axis=-1)
    n /= np.linalg.norm(n, axis=-1, keepdims=True)
    return np.round((n * 0.5 + 0.5) * 255.0).astype(np.uint8)


def decode_normal_slopes(rgb, gain=NORMAL_GAIN):
    """Inverse of normal_map: (d_east, d_north) from the RGB image."""
    n = rgb.astype(np.float64) / 255.0 * 2.0 - 1.0
    return -n[..., 0] / n[..., 2] / gain, -n[..., 1] / n[..., 2] / gain


def mesh_error(dem, step):
    """Abs. error (m) of a mesh with `step` m spacing (block means, bilinear between
    them) against the 1 m DEM, away from the border."""
    coarse = block_mean(dem, step)
    rows, cols = dem.shape
    rr, cc = np.mgrid[0:rows, 0:cols]
    shift = step / 2.0 - 0.5                      # block centre in cell-index units
    back = ndi.map_coordinates(coarse, [(rr - shift) / step, (cc - shift) / step],
                               order=1, mode="nearest")
    err = np.abs(back - dem)[step:-step, step:-step]
    p50, p95, p99 = np.percentile(err, [50, 95, 99])
    return {"p50": round(float(p50), 3), "p95": round(float(p95), 3),
            "p99": round(float(p99), 3), "max": round(float(err.max()), 2),
            "triangles": 2 * (rows // step - 1) * (cols // step - 1)}


def apparent_slope_deg(d_east, d_north, k):
    """Median and 90th percentile of the local-relief slope once exaggerated k times."""
    g = np.hypot(d_east, d_north)
    p50, p90 = np.percentile(g, [50, 90])
    return {"median": round(float(np.degrees(np.arctan(k * p50))), 1),
            "p90": round(float(np.degrees(np.arctan(k * p90))), 1)}


def ortho_tiles(size_px, tile_px=ORTHO_TILE_PX, cell_m=0.25):
    """Four overlapping square tiles covering the image: (row, col, top_px, left_px)."""
    starts = (0, size_px - tile_px)
    return [(r, c, top, left) for r, top in enumerate(starts) for c, left in enumerate(starts)]


def build(data_dir, out_dir):
    base = Path(data_dir) / "base"
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()

    grid = json.loads((base / "grid.json").read_text(encoding="utf-8"))
    with rasterio.open(base / "dem_1m.tif") as src:
        dem = src.read(1).astype(np.float64)
        cell = float(src.transform.a)
    if np.isnan(dem).any():                        # the base grid has none; keep it safe
        idx = ndi.distance_transform_edt(np.isnan(dem), return_distances=False, return_indices=True)
        dem = dem[tuple(idx)]
    assert cell == 1.0 and dem.shape[0] % MESH_STEP_M == 0 and dem.shape[1] % MESH_STEP_M == 0

    low, detail = split_relief(dem)
    layers = {}
    for name, field in (("height", dem), ("low", low), ("detail", detail)):
        q, offset, scale = quantize(block_mean(field, MESH_STEP_M))
        fname = {"height": "height_2m.bin", "low": "height_low_2m.bin",
                 "detail": "detail_2m.bin"}[name]
        q.tofile(out / fname)
        layers[name] = {"file": fname, "offset_m": offset, "scale_m": scale}
    print(f"heights written ({time.time() - t0:.1f}s)")

    d_east, d_north = slopes(detail)
    rgb = normal_map(block_mean(d_east, MESH_STEP_M), block_mean(d_north, MESH_STEP_M))
    Image.fromarray(rgb).save(out / "normal_detail.png", optimize=True)

    raw_e, raw_n = slopes(dem - low)
    check = {"smoothed_detail": {str(k): apparent_slope_deg(d_east, d_north, k)
                                 for k in EXAGGERATIONS},
             "raw_1m_detail": {str(k): apparent_slope_deg(raw_e, raw_n, k)
                               for k in EXAGGERATIONS}}
    errors = {str(s): mesh_error(dem, s) for s in (2, 4, 8)}
    print(f"normal map and checks written ({time.time() - t0:.1f}s)")

    with rasterio.open(base / "ortho_color_025.tif") as src:
        ortho = np.transpose(src.read([1, 2, 3]), (1, 2, 0))
        ortho_cell = float(src.transform.a)
    img = Image.fromarray(ortho)
    img.resize((ORTHO_LOW_PX, ORTHO_LOW_PX), Image.LANCZOS).save(
        out / f"ortho_{ORTHO_LOW_PX}.jpg", quality=JPEG_QUALITY, optimize=True)
    size_m = ortho.shape[0] * ortho_cell
    tiles = []
    for r, c, top, left in ortho_tiles(ortho.shape[0]):
        fname = f"ortho_hi_{r}{c}.jpg"
        img.crop((left, top, left + ORTHO_TILE_PX, top + ORTHO_TILE_PX)).save(
            out / fname, quality=JPEG_QUALITY, optimize=True)
        tiles.append({"file": fname, "west_m": left * ortho_cell, "north_m": top * ortho_cell,
                      "size_m": ORTHO_TILE_PX * ortho_cell})
    print(f"orthophoto written ({time.time() - t0:.1f}s)")

    rows, cols = dem.shape[0] // MESH_STEP_M, dem.shape[1] // MESH_STEP_M
    meta = {
        "version": 1,
        "generated_by": "src/viz3d/build_terrain_assets.py",
        "bbox": grid["bbox"],
        "size_m": size_m,
        "grid": {"rows": rows, "cols": cols, "spacing_m": MESH_STEP_M,
                 "first_center_m": MESH_STEP_M / 2.0, "row0": "north", "col0": "west",
                 "dtype": "uint16 little-endian; value = offset_m + scale_m * uint16"},
        "layers": layers,
        "relief": {"low_sigma_m": LOW_SIGMA_M, "detail_sigma_m": DETAIL_SIGMA_M,
                   "shown": "height + (k - 1) * detail", "max_exaggeration": 5,
                   "z_min_m": float(dem.min()), "z_max_m": float(dem.max()),
                   "detail_p01_m": round(float(np.percentile(detail, 1)), 2),
                   "detail_p99_m": round(float(np.percentile(detail, 99)), 2)},
        "normal": {"file": "normal_detail.png", "rows": rows, "cols": cols, "gain": NORMAL_GAIN,
                   "encoding": "rgb = 0.5 + 0.5 * normalize(-gain * d(detail)/d(east), "
                               "-gain * d(detail)/d(north), 1); row 0 = north",
                   "three_js": "normalScale = k / gain; vertex normals come from `low`"},
        "ortho": {"low": {"file": f"ortho_{ORTHO_LOW_PX}.jpg", "west_m": 0.0, "north_m": 0.0,
                          "size_m": size_m},
                  "high": tiles},
        "mesh_error_m": errors,
        "exaggeration_check_deg": check,
        "sources": {name: {"file": f"base/{name}", "bytes": (base / name).stat().st_size}
                    for name in ("dem_1m.tif", "ortho_color_025.tif")},
    }
    (out / "terrain.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    print(f"done: {out} ({time.time() - t0:.1f}s)")
    return meta


def main():
    repo = Path(__file__).resolve().parents[2]
    default_data = os.environ.get("MARTIAN_DATA", str(repo / "data"))
    ap = argparse.ArgumentParser(description="Browser assets for the 3D map (issue #42).")
    ap.add_argument("--data-dir", default=default_data,
                    help="folder with base/ (default: MARTIAN_DATA, else <repo>/data)")
    ap.add_argument("--out-dir", default=None, help="default: <data-dir>/tiles/3d")
    args = ap.parse_args()
    meta = build(args.data_dir, args.out_dir or Path(args.data_dir) / "tiles" / "3d")
    print(json.dumps({"mesh_error_m": meta["mesh_error_m"],
                      "exaggeration_check_deg": meta["exaggeration_check_deg"]}, indent=2))


if __name__ == "__main__":
    main()
