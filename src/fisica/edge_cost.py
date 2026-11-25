"""E3 - Directed edge costs over the base grid (8-neighbour graph).

Reference: zero-to-hero guide REV3, sections 17-18 and 22.

For every cell u and each of the 8 neighbours v we compute:
    alpha = atan((z_v - z_u) / d_h)           signed, along u -> v
    dt    = d_h / (V(alpha) * cos(alpha))     seconds
    E     = M_Santee(alpha, V, g) * dt        joules
The graph is DIRECTED: cost(u -> v) != cost(v -> u) when there is slope.

Output layout (shared contract with the graph code):
    time_s[k, row, col]   time to go from (row, col) to its neighbour k
    energy_j[k, row, col] energy for the same move
    k follows NEIGHBOURS below. NaN = edge does not exist (off-grid,
    nodata cell at either end, or |alpha| above the slope limit).
"""

import warnings

import numpy as np

from .metabolic import BODY_MASS_KG, G_EARTH, G_MARS, J_PER_WH, TOTAL_MASS_KG

# (d_row, d_col) for k = 0..7. Row grows southwards (north-up raster).
NEIGHBOURS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
#              N        NE       E       SE      S       SW       W        NW

DEFAULT_MAX_SLOPE_DEG = 20.0   # CSRM limit; the model is extrapolated beyond it
EXTRAPOLATION_SLOPE_DEG = 25.0  # above this we warn: far outside the validated range
SPEED_ZERO_SLOPE_DEG = 75.0     # Apollo speed 0.75 - 0.01*alpha reaches 0 here, so
                                # time and energy turn negative and break Dijkstra
DEFAULT_MAX_CELL_SLOPE_DEG = 30.0   # team decision: block cells whose steepest
                                    # slope (slope_deg.tif) exceeds this; None disables


def _shifted(a, d_row, d_col):
    """a[row + d_row, col + d_col] aligned with a[row, col]; NaN off-grid."""
    out = np.full_like(a, np.nan)
    rows, cols = a.shape
    src_r = slice(max(d_row, 0), rows + min(d_row, 0))
    dst_r = slice(max(-d_row, 0), rows + min(-d_row, 0))
    src_c = slice(max(d_col, 0), cols + min(d_col, 0))
    dst_c = slice(max(-d_col, 0), cols + min(-d_col, 0))
    out[dst_r, dst_c] = a[src_r, src_c]
    return out


def santee_power_array(mass_kg, v, alpha_deg, g_mps2):
    """Vectorised version of metabolic.santee_2001_power (total only)."""
    a = np.radians(alpha_deg)
    w_level = (3.28 * mass_kg + 71.1) * (0.661 * v * np.cos(a) + 0.115)
    up = 3.5 * mass_kg * g_mps2 * v * np.sin(a)
    down = 2.4 * mass_kg * g_mps2 * v * np.sin(a) * 0.3 ** (np.abs(alpha_deg) / 7.65)
    w_slope = np.where(alpha_deg > 0, up, np.where(alpha_deg < 0, down, 0.0))
    return w_level + w_slope


def pandolf_cf_power_array(mass_kg, v, alpha_deg, eta=1.0, body_kg=BODY_MASS_KG):
    """Vectorised metabolic.pandolf_cf_power (sensitivity branch only)."""
    w, l = body_kg, mass_kg - body_kg
    g = 100.0 * np.tan(np.radians(alpha_deg))
    m = 1.5 * w + 2.0 * (w + l) * (l / w) ** 2 + eta * (w + l) * (1.5 * v ** 2 + 0.35 * v * g)
    cf = eta * (g * (w + l) * v / 3.5 - (w + l) * (g + 6) ** 2 / w + (25 - v ** 2))
    return np.where(g < 0, m - cf, m)


MODELS = ("santee2001", "pandolf_cf", "pandolf_cf_scaled")


def model_power(model, mass_kg, v, alpha_deg, g_mps2):
    """Power for one of MODELS. Only santee2001 is nominal; the Pandolf branches are
    for sensitivity: pandolf_cf is terrestrial, pandolf_cf_scaled multiplies it by
    g/g_Earth (the CSRM whole-power scaling, the low-cost scenario of the guide)."""
    if model == "santee2001":
        return santee_power_array(mass_kg, v, alpha_deg, g_mps2)
    if model == "pandolf_cf":
        return pandolf_cf_power_array(mass_kg, v, alpha_deg)
    if model == "pandolf_cf_scaled":
        return pandolf_cf_power_array(mass_kg, v, alpha_deg) * g_mps2 / G_EARTH
    raise ValueError(f"unknown model {model!r}; expected one of {MODELS}")


def edge_costs(dem, cell_size_m=1.0, mass_kg=TOTAL_MASS_KG, g_mps2=G_MARS,
               signed=True, max_slope_deg=DEFAULT_MAX_SLOPE_DEG,
               cell_slope_deg=None, max_cell_slope_deg=DEFAULT_MAX_CELL_SLOPE_DEG,
               model="santee2001"):
    """Directed time (s) and energy (J) for the 8 edges of every cell.

    dem: 2-D float array of elevations in metres, NaN = nodata.
    max_slope_deg: limit on the slope ALONG the move (edge removed above it).
        Must stay below 75 deg (Apollo speed hits 0); keep it around 20-25 deg.
    cell_slope_deg: optional steepest-slope raster (slope_deg.tif). Cells above
        max_cell_slope_deg are blocked (no edge in or out); this covers the
        cross-slope risk that Santee does not model. Pass max_cell_slope_deg=None
        (or no raster) to disable the block.
    model: "santee2001" (nominal) or a Pandolf branch, for sensitivity only.
    Returns (time_s, energy_j, alpha_deg), each float32 of shape (8, rows, cols).
    """
    if max_slope_deg >= SPEED_ZERO_SLOPE_DEG:
        raise ValueError(f"max_slope_deg must be < {SPEED_ZERO_SLOPE_DEG} deg: the Apollo "
                         "speed becomes <= 0 and edge costs turn negative")
    if max_slope_deg > EXTRAPOLATION_SLOPE_DEG:
        warnings.warn(f"max_slope_deg = {max_slope_deg} deg is far outside the validated "
                      "range (about +/-20 deg); costs are an extrapolation", stacklevel=2)

    dem = np.asarray(dem, dtype=np.float64)
    shape = (len(NEIGHBOURS),) + dem.shape
    time_s = np.full(shape, np.nan, dtype=np.float32)
    energy_j = np.full(shape, np.nan, dtype=np.float32)
    alpha_out = np.full(shape, np.nan, dtype=np.float32)

    walkable = np.isfinite(dem)
    if cell_slope_deg is not None and max_cell_slope_deg is not None:
        walkable &= np.asarray(cell_slope_deg) <= max_cell_slope_deg   # NaN -> blocked
    blocked_dem = np.where(walkable, dem, np.nan)   # NaN cells get no edges

    for k, (dr, dc) in enumerate(NEIGHBOURS):
        d_h = cell_size_m * (np.sqrt(2.0) if dr and dc else 1.0)
        dz = _shifted(blocked_dem, dr, dc) - blocked_dem   # NaN if either end is nodata/blocked
        alpha = np.degrees(np.arctan(dz / d_h))
        valid = np.isfinite(alpha) & (np.abs(alpha) <= max_slope_deg)
        alpha_v = np.where(valid, alpha, 0.0)                # placeholder to avoid warnings
        v = 0.75 - 0.01 * (alpha_v if signed else np.abs(alpha_v))
        dt = d_h / (v * np.cos(np.radians(alpha_v)))
        e = model_power(model, mass_kg, v, alpha_v, g_mps2) * dt
        time_s[k] = np.where(valid, dt, np.nan)
        energy_j[k] = np.where(valid, e, np.nan)
        alpha_out[k] = np.where(valid, alpha, np.nan)

    return time_s, energy_j, alpha_out


def cell_cost_wh(energy_j, cell_size_m):
    """Display summary: mean Wh to cross one cell, over its valid outgoing edges.

    NaN where the cell has no valid edge. Planning must use the directed edges.
    """
    lengths = np.array([cell_size_m * (np.sqrt(2) if dr and dc else 1.0)
                        for dr, dc in NEIGHBOURS], dtype=np.float32)
    per_metre = energy_j / lengths[:, None, None]          # NaN edges stay NaN
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)    # all-NaN cells -> NaN
        mean_j = np.nanmean(per_metre, axis=0)
    return (mean_j * cell_size_m / J_PER_WH).astype(np.float32)
