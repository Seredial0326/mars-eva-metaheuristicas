"""Raster overlays rendered on the fly for the HUD (one 2000 x 2000 PNG each).

- Cost layer: E3 mean Wh to cross each cell (display only), computed once
  WITHOUT the cell block, so changing the block limit does not recolour it.
- Blocked mask: cells whose steepest slope (slope_deg.tif) exceeds a limit.
  Cheap to compute, so the HUD slider can request any limit live.
"""

import io
import sys
from functools import lru_cache
from pathlib import Path

import numpy as np
import rasterio
from matplotlib import colormaps
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fisica.edge_cost import cell_cost_wh, edge_costs  # noqa: E402

BLOCKED_RGBA = (14, 16, 20, 190)      # near-black hatch (see blocked_layer)


def _png(rgba):
    buf = io.BytesIO()
    Image.fromarray(rgba, mode="RGBA").save(buf, format="PNG", optimize=False)
    return buf.getvalue()


def _read(path):
    with rasterio.open(path) as src:
        return src.read(1).astype(np.float64), abs(src.res[0])


@lru_cache(maxsize=1)
def cost_layer(base_dir):
    """(png_bytes, legend dict). Colour scale: c_min (darkest) to the 98th pct."""
    dem, cell = _read(Path(base_dir) / "dem_1m.tif")
    _, energy_j, _ = edge_costs(dem, cell_size_m=cell)          # edge limit only
    wh = cell_cost_wh(energy_j, cell)
    vmin = float(np.nanmin(wh))
    vmax = float(np.nanpercentile(wh, 98))
    norm = np.clip((wh - vmin) / (vmax - vmin), 0, 1)
    rgba = (colormaps["magma"](np.nan_to_num(norm)) * 255).astype(np.uint8)
    rgba[np.isnan(wh)] = 0                                       # transparent
    legend = {"units": "Wh per cell (1 m)", "vmin": vmin, "vmax": vmax,
              "vmin_j_per_m": vmin * 3600 / cell, "vmax_j_per_m": vmax * 3600 / cell,
              "colormap": "magma"}
    return _png(rgba), legend


@lru_cache(maxsize=1)
def _slope(base_dir):
    return _read(Path(base_dir) / "slope_deg.tif")[0]


@lru_cache(maxsize=64)
def blocked_layer(base_dir, max_cell_slope_deg):
    """(png_bytes, fraction of cells blocked) for a given slope limit."""
    slope = _slope(base_dir)
    with np.errstate(invalid="ignore"):
        blocked = ~(slope <= max_cell_slope_deg)                  # NaN counts as blocked
    rgba = np.zeros(slope.shape + (4,), dtype=np.uint8)
    # A dark neutral hatch, not a colour: red is kept for the 30 min return line on the
    # map, and these cells sit right under it. 12 m diagonal stripes stay readable at
    # the whole-area zoom and do not alias into a flat tint.
    rows, cols = np.indices(slope.shape)
    stripe = ((rows + cols) // 12) % 2 == 0
    rgba[blocked & stripe] = BLOCKED_RGBA
    rgba[blocked & ~stripe] = BLOCKED_RGBA[:3] + (BLOCKED_RGBA[3] // 2,)
    return _png(rgba), float(blocked.mean())


SAND_RGB = (250, 246, 235)          # warm white: no station type, slope band or line uses it


@lru_cache(maxsize=1)
def sand_layer(e8_dir):
    """E8 sand fraction (0-1) as a PNG: one hue, opacity grows with the fraction,
    no sand = transparent. E8's U-Net is conservative (high precision, low recall),
    so this shows DETECTED sand, not all the sand."""
    with rasterio.open(Path(e8_dir) / "sand.tif") as src:
        frac = np.nan_to_num(src.read(1).astype(np.float64))
    rgba = np.zeros(frac.shape + (4,), dtype=np.uint8)
    rgba[..., :3] = SAND_RGB
    rgba[..., 3] = (np.clip(frac, 0, 1) * 220).astype(np.uint8)
    return _png(rgba), {"share_of_box_with_sand_pct": float((frac > 0.5).mean() * 100)}


ROCK_RGB = (232, 236, 255)          # cool white dots with a dark ring: a texture, not a fill
ROCK_BLOCK_M = 10                   # E9 reads best averaged to 10 m (README of e9-rocks-v1)
ROCK_FULL = 0.10                    # 10 % of a 10 m square under boulders draws the largest dot
ROCK_MIN = 0.01                     # below 1 % no dot is drawn (noise)


@lru_cache(maxsize=1)
def rocks_layer(e9_dir):
    """E9 boulder cover (rocas.tif, 1 m, fraction 0-1) as a halftone PNG: one dot per
    10 m square, dot AREA proportional to the share of the square covered by boulders
    (capped at ROCK_FULL). Boulders under ~1 m are not detected. Display only."""
    from PIL import ImageDraw
    with rasterio.open(Path(e9_dir) / "rocas.tif") as src:
        cover = src.read(1).astype(np.float64)
    b = ROCK_BLOCK_M
    h, w = (cover.shape[0] // b) * b, (cover.shape[1] // b) * b
    blocks = np.nanmean(cover[:h, :w].reshape(h // b, b, w // b, b), axis=(1, 3))
    img = Image.new("RGBA", cover.shape[::-1], (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    rmax = b * 0.48
    for (i, j), c in np.ndenumerate(np.nan_to_num(blocks)):
        if c < ROCK_MIN:
            continue
        r = max(1.2, rmax * np.sqrt(min(1.0, c / ROCK_FULL)))
        cx, cy = j * b + b / 2, i * b + b / 2
        draw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=ROCK_RGB + (235,), outline=(10, 12, 16, 220), width=1)
    valid = blocks[~np.isnan(blocks)]
    info = {"block_m": b, "mean_cover_pct": float(np.nanmean(cover) * 100),
            "share_of_squares_with_dots_pct": float((valid >= ROCK_MIN).mean() * 100),
            "share_of_squares_over_5pct_pct": float((valid >= 0.05).mean() * 100),
            "full_dot_cover_pct": ROCK_FULL * 100}
    return _png(np.asarray(img)), info
