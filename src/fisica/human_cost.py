"""E3 + E1: human cost = E3 metabolic energy x a terrain factor learned from Curiosity.

Reference: zero-to-hero guide REV3 (E1: "for the human, the slope term is replaced
by the metabolic cost, keeping what was learned about roughness and sand").

    cost_human(u -> v) = energy_E3(u -> v) * factor(v)
    factor(v)          = 1 + scale * sum_k w_k * f_k(v)      over NON-slope features

- Slope features are dropped: E3 already charges slope with physics, so keeping
  them would charge it twice.
- The factor depends on the arrival cell v (the MaxEnt convention: the cost of
  entering a state), so every arc keeps its own E3 energy and up != down.
- With w_k >= 0 and f_k in [0, 1], factor >= 1: costs stay positive (Dijkstra).
- The result is still in joules, so R(v), walkback and E5's checks keep their
  physical meaning; the factor reads as "how many metabolic joules a cell is
  worth to a person, relative to bare rock".
- scale: if E1 learns a per-step (distance) weight w_dist, scale = 1 / w_dist,
  which turns the learned cost into a relative price per step. Otherwise scale
  comes from the weights file.

Weights file (proposed contract with E1, data/e1/e1_weights.json):
{
  "distance_weight": 1.0,                       # optional; sets scale = 1 / w
  "scale": 1.0,                                 # used when distance_weight is absent
  "features": {
    "roughness":  {"weight": 0.4, "raster": "roughness.tif", "min": 0.03, "max": 0.82},
    "tpi_ridge":  {"weight": 0.2, "raster": "tpi.tif", "transform": "positive", "min": 0, "max": 1.2},
    "tpi_hollow": {"weight": 0.3, "raster": "tpi.tif", "transform": "negative", "min": 0, "max": 1.07},
    "slope_deg":  {"weight": 0.9, "raster": "slope_deg.tif", "min": 0, "max": 49, "slope": true}
  }
}
Each feature is scaled to [0, 1] as clip((x - min) / (max - min), 0, 1), with the
SAME min/max E1 used when fitting. "slope": true marks features dropped here.
"""

import json
import warnings
from pathlib import Path

import numpy as np
import rasterio

SLOPE_FEATURES = {"slope_deg", "slope_mean_5m", "slope_mean_15m"}


def load_weights(path):
    spec = json.loads(Path(path).read_text(encoding="utf-8"))
    for name, f in spec["features"].items():
        if f["weight"] < 0:
            raise ValueError(f"E1 weight for {name} is negative ({f['weight']}); "
                             "the human cost needs weights >= 0")
        if f["max"] <= f["min"]:
            raise ValueError(f"feature {name}: max must be greater than min")
    return spec


def is_slope(name, feature):
    return feature.get("slope", False) or name in SLOPE_FEATURES


def scaled_feature(raw, feature):
    x = np.asarray(raw, dtype=np.float64)
    t = feature.get("transform")
    if t == "positive":
        x = np.maximum(x, 0.0)
    elif t == "negative":
        x = np.maximum(-x, 0.0)
    elif t is not None:
        raise ValueError(f"unknown transform {t!r}")
    return np.clip((x - feature["min"]) / (feature["max"] - feature["min"]), 0.0, 1.0)


def terrain_factor(spec, rasters, shape):
    """factor(v) >= 1 per cell from the non-slope features.

    rasters: {raster file name: 2-D array}. NaN feature values count as 0 (no
    extra price); cells without a DEM value have no edges anyway.
    """
    if "distance_weight" in spec:
        if spec["distance_weight"] <= 0:
            raise ValueError("distance_weight must be > 0")
        scale = 1.0 / spec["distance_weight"]
    else:
        scale = float(spec.get("scale", 1.0))
    total = None
    for name, f in spec["features"].items():
        if is_slope(name, f):
            continue                                    # E3 already charges slope
        term = f["weight"] * np.nan_to_num(scaled_feature(rasters[f["raster"]], f))
        total = term if total is None else total + term
    if total is None:
        return np.ones(shape)
    return 1.0 + scale * total


def human_edge_costs(energy_j, factor, neighbours):
    """Multiply each arc u -> v by factor(v). Same shape and NaN pattern as energy_j."""
    out = np.full_like(energy_j, np.nan)
    rows, cols = factor.shape
    for k, (dr, dc) in enumerate(neighbours):
        shifted = np.full(factor.shape, np.nan)
        rs = slice(max(dr, 0), rows + min(dr, 0)); rd = slice(max(-dr, 0), rows + min(-dr, 0))
        cs = slice(max(dc, 0), cols + min(dc, 0)); cd = slice(max(-dc, 0), cols + min(-dc, 0))
        shifted[rd, cd] = factor[rs, cs]                # factor of the arrival cell
        out[k] = energy_j[k] * shifted
    if np.any(out[np.isfinite(out)] <= 0):
        warnings.warn("non-positive human costs found; check the E1 weights")
    return out.astype(np.float32)


def load_rasters(spec, base_dir):
    names = {f["raster"] for n, f in spec["features"].items() if not is_slope(n, f)}
    out = {}
    for name in names:
        with rasterio.open(Path(base_dir) / name) as src:
            out[name] = src.read(1)
    return out
