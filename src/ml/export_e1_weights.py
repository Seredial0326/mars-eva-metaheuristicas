"""E1 -> E3 hand-off: write data/e1/e1_weights.json in the format agreed in #2 (read by fisica.human_cost).

Format (Sebas, issue #2, PR #41): per feature a weight >= 0, the raster it comes
from, the min/max of the 0-1 scaling, `transform` positive/negative for the
two halves of TPI, and `slope: true` for slope features (dropped by E3, which
already charges slope). `distance_weight` is the learned price of a metre.
Rasters are given relative to the feature directory of
src/fisica/build_cost_layers.py (by default the DEM's folder, data/base/).

Which weights are handed over: the per-sol models at 1 m (fit_irl.py and
validate_irl.py with --features dem, sand, dem_sand, rocks and sand_rocks) are
the candidates; the rocks models use the E9 student layer (rocas.tif), the
teacher run is only a sensitivity check.
Only a model whose terrain prices beat the distance-only control on held-out
blocks (held-out NLL per metre) can be handed over; among those, the one with
the lowest held-out NLL wins. If none beats the control, every weight is 0: a
price that does not generalise would add noise to the planner. The fitted
values are always kept in `fitted_weight` (ignored by E3).

Exact scaling: E1 uses x / p99 without clipping; fisica.human_cost uses
clip(x / max, 0, 1). We export max = the true maximum of x over the box (so the
clip never acts) and weight = w * max / p99, which gives exactly the same
cost. For the sand layers p99 = max = 1, so the weights are unchanged. For
the boulder layers p99 < max, and the max ignores NaN cells; E1 and
fisica.human_cost both count a NaN cell of rocas.tif as 0.

The window means (5 x 5 m of sand, 10 x 10 m of boulder cover) have no raster
of their own, so this script writes them to data/e1/sand_mean_5m.tif and
data/e1/rocks_mean_10m.tif (float32, base grid) when the chosen model uses them.

Input:  data/e1/irl_fit_<tag>.json and data/e1/validation_<tag>.json for every candidate
Output: data/e1/e1_weights.json (and the window-mean rasters the chosen model needs)
Usage:  python src/ml/export_e1_weights.py
"""
import json

import numpy as np
import rasterio

import common
import irl_data

CANDIDATES = {"dem": "per_sol_cell1m_margin50m",
              "sand": "per_sol_cell1m_margin50m_sand",
              "dem_sand": "per_sol_cell1m_margin50m_dem_sand",
              "rocks": "per_sol_cell1m_margin50m_rocks",
              "sand_rocks": "per_sol_cell1m_margin50m_sand_rocks"}
# Window means written by this script (feature -> file)
MEAN_TIFS = {"sand_mean_5m": common.E1_OUTPUT / "sand_mean_5m.tif",
             "rocks_mean_10m": common.E1_OUTPUT / "rocks_mean_10m.tif"}
# feature -> (raster relative to data/base/, transform, slope feature, note)
SOURCES = {
    "roughness": ("roughness.tif", None, False, None),
    "tpi_ridge": ("tpi.tif", "positive", False, None),
    "tpi_hollow": ("tpi.tif", "negative", False, None),
    "slope_deg": ("slope_deg.tif", None, True, None),
    "slope_mean_5m": ("slope_deg.tif", None, True, "mean of slope_deg.tif over a 5 x 5 m window"),
    "slope_mean_15m": ("slope_deg.tif", None, True, "mean of slope_deg.tif over a 15 x 15 m window"),
    "sand": ("../e8/sand.tif", None, False, "E8 sand fraction (release e8-v0)"),
    "sand_mean_5m": ("../e1/sand_mean_5m.tif", None, False,
                     "mean of sand.tif over a 5 x 5 m window, written by src/ml/export_e1_weights.py"),
    "rocks": ("../e9/rocas.tif", None, False,
              "E9 boulder cover fraction, distilled student (release e9-rocks-v1); NaN counts as 0"),
    "rocks_mean_10m": ("../e1/rocks_mean_10m.tif", None, False,
                       "mean of rocas.tif (NaN as 0) over a 10 x 10 m window, written by src/ml/export_e1_weights.py"),
}


def load(kind, tag):
    path = common.E1_OUTPUT / f"{kind}_{tag}.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def candidates():
    out = {}
    for name, tag in CANDIDATES.items():
        fit, val = load("irl_fit", tag), load("validation", tag)
        if fit is None or val is None:
            continue
        s = val["summary"]
        out[name] = {"tag": tag, "fit": fit,
                     "held_out_nll_per_m": {"terrain": s["terrain"]["nll_per_m"],
                                            "distance_only": s["distance_only"]["nll_per_m"]},
                     "beats_control": s["terrain"]["nll_per_m"] < s["distance_only"]["nll_per_m"]}
    return out


def write_mean(name, raw):
    """Write the window-mean feature `name` in its own units (not divided by p99) on the base grid."""
    with rasterio.open(common.base_layer("dem_1m.tif")) as dem:
        profile = dem.profile | {"dtype": "float32", "count": 1, "nodata": np.nan}
    with rasterio.open(MEAN_TIFS[name], "w", **profile) as dst:
        dst.write(raw[name].astype(np.float32), 1)
    return MEAN_TIFS[name]


def factor_check(spec, phi, feats, w):
    """Run E3's own reader (fisica.human_cost) on the spec and compare with E1's formula."""
    from fisica import human_cost as hc        # src/ is on sys.path (maxent_irl)
    tmp = common.E1_OUTPUT / "_e1_weights_check.json"
    tmp.write_text(json.dumps(spec), encoding="utf-8")
    try:
        loaded = hc.load_weights(tmp)
        factor = hc.terrain_factor(loaded, hc.load_rasters(loaded, common.BASE), phi.shape[1:])
    finally:
        tmp.unlink()
    # E1's own price relative to a metre: fitted weights on E1's scaled features (x / p99).
    non_slope = [j for j, n in enumerate(feats) if j > 0 and not SOURCES[n][2]]
    e1 = np.ones(phi.shape[1:])
    if spec["validated"]:
        e1 = e1 + sum(w[feats[j]] * phi[j].astype(np.float64) for j in non_slope) / w["metre"]
    return {"min": float(factor.min()), "median": float(np.median(factor)),
            "p95": float(np.percentile(factor, 95)), "max": float(factor.max()),
            "share_above_1_05": float((factor > 1.05).mean()),
            "max_abs_diff_vs_e1_formula": float(np.abs(factor - e1).max())}


def main():
    cands = candidates()
    if "dem" not in cands:
        raise SystemExit("run fit_irl.py and validate_irl.py (default features) first")
    passing = {k: c for k, c in cands.items() if c["beats_control"]}
    chosen = min(passing, key=lambda k: passing[k]["held_out_nll_per_m"]["terrain"]) if passing else "dem"
    c = cands[chosen]
    fit, validated = c["fit"], bool(passing)
    feats = fit["features"]
    phi, scale, _ = irl_data.feature_stack(feats, rocks_layer="student")
    raw, _ = irl_data.raw_features(feats, rocks_layer="student")
    w = fit["terrain"]["w"]
    features = {}
    for j, name in enumerate(feats[1:], start=1):
        raster, transform, slope, note = SOURCES[name]
        # The largest value E3 reads (float32 rasters, NaN ignored), so x / max never exceeds 1.
        true_max = float(np.nanmax(raw[name].astype(np.float32)))
        factor = true_max / scale[name]          # weight conversion for clip(x / true_max)
        f = {"weight": w[name] * factor if validated else 0.0, "fitted_weight": w[name],
             "raster": raster, "min": 0.0, "max": true_max}
        if transform:
            f["transform"] = transform
        if slope:
            f["slope"] = True
        if note:
            f["note"] = note
        features[name] = f
    written = [write_mean(n, raw) for n in MEAN_TIFS if validated and n in feats]
    non_slope = [n for n in feats[1:] if not SOURCES[n][2]]
    max_factor = 1 + sum(features[n]["weight"] for n in non_slope) / w["metre"]
    spec = {
        "distance_weight": w["metre"],
        "features": features,
        "validated": validated,
        "model": chosen,
        "result": (f"the '{chosen}' model beats the distance-only control on held-out blocks; its prices are "
                   f"handed over (terrain factor 1 to {max_factor:.3f})" if validated else
                   "no terrain price beats the distance-only control on held-out blocks: every weight is 0, "
                   "so the human cost is E3 alone (factor 1)"),
        "candidates": {k: {"tag": v["tag"], "held_out_nll_per_m": v["held_out_nll_per_m"],
                           "beats_control": v["beats_control"]} for k, v in cands.items()},
        "source": f"src/ml/fit_irl.py -> data/e1/irl_fit_{c['tag']}.json; "
                  f"src/ml/validate_irl.py -> data/e1/validation_{c['tag']}.json",
        "raster_paths": "relative to the feature directory of build_cost_layers.py (default: data/base/)",
        "scaling": "max = true maximum over the box and weight = w * max / p99, so human_cost's clip never acts "
                   "and the cost equals E1's w * x / p99",
    }
    spec["terrain_factor_check"] = factor_check(spec, phi, feats, w)
    out = common.E1_OUTPUT / "e1_weights.json"
    out.write_text(json.dumps(spec, indent=2), encoding="utf-8")
    print(json.dumps({k: spec[k] for k in ("model", "validated", "result", "candidates")}, indent=2))
    print(f"wrote {out}" + "".join(f" and {p}" for p in written))


if __name__ == "__main__":
    main()
