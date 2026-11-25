"""E2 + E8: does the sand layer lift E2's terrain-only logistic baseline?

Question: E2's logistic baseline (visited vs not visited cells near Curiosity's
route, five DEM features) reaches an out-of-block AUC of only 0.526 in the 50 m
corridor. Does adding E8's sand layer raise it, and is the gain consistent
across the route blocks?

Method: exactly E2's pipeline (logistic_baseline.py): the same comparison sets
(corridor 25 / 50 (main) / 100 m and the whole box with its fixed random
subsample), the same model (StandardScaler + class-balanced LogisticRegression)
and the same leave-one-block-out validation over cell_features.N_BLOCKS route
blocks. Three models:
  dem_only        E2's five DEM features (must reproduce E2: 0.526 / 0.730)
  dem_plus_sand   the five DEM features + sand + sand_mean_5m
  sand_only       sand + sand_mean_5m
Sand features:
  sand            E8's U-Net sand fraction (0-1) of the 1 m cell
  sand_mean_5m    mean sand fraction in a 5 x 5 m window (uniform_filter, mode="nearest")
Boxwork-only score: mean of the out-of-block AUCs of blocks BOXWORK_BLOCKS
(2, 3, 4: sols 4512-4868, mostly boxwork per the E2 note), plus the pooled
out-of-block AUC of their cells; "within_boxwork" repeats the leave-one-block-out
using only those three blocks (train on two boxwork blocks, test on the third).

Input:  data/e2/cell_features.parquet, data/base/*.tif (for the whole box),
        data/e8/sand.tif (same grid as data/base/dem_1m.tif)
Output: data/e2/logistic_baseline_sand.json
          AUC per block, mean, min, max, pooled out-of-block and boxwork-only
          means for every set and model; dem_plus_sand minus dem_only deltas and
          number of blocks improved; standardized coefficients of dem_plus_sand
          fitted on the whole main set; sand medians and means for visited vs
          not visited cells of the main set.
        (logistic_baseline.json is never touched.)

Usage:  python src/ml/logistic_sand.py   (after cell_features.py and E8's sand.tif)
"""
import json
import time

import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import uniform_filter
from sklearn.metrics import roc_auc_score

import cell_features as cf
import common
import logistic_baseline as lb

SAND_PATH = common.PRODUCTS / "e8" / "sand.tif"
OUTPUT = common.E2_OUTPUT / "logistic_baseline_sand.json"
SAND_FEATURES = ["sand", "sand_mean_5m"]
MODELS = {
    "dem_only": cf.FEATURES,
    "dem_plus_sand": cf.FEATURES + SAND_FEATURES,
    "sand_only": SAND_FEATURES,
}
BOXWORK_BLOCKS = (2, 3, 4)
MAIN_SET = f"corridor_{lb.MAIN_CORRIDOR_M}m"
# E2's published auc_mean (data/e2/logistic_baseline.json, all_features).
E2_REFERENCE = {"corridor_50m": 0.526, "whole_box": 0.730}


def sand_rasters():
    """Dict name -> 2000 x 2000 sand layer, checked against the base grid."""
    with rasterio.open(SAND_PATH) as src, rasterio.open(common.base_layer("dem_1m.tif")) as dem:
        if src.crs != dem.crs or src.transform != dem.transform or src.shape != dem.shape:
            raise SystemExit(f"{SAND_PATH} is not on the base grid of dem_1m.tif")
        sand = src.read(1).astype("float64")
    if np.isnan(sand).any():
        raise SystemExit(f"{SAND_PATH} has NaN cells")
    # mode="nearest" as in cell_features.py: only the outer 2 m of the box are affected.
    return {"sand": sand, "sand_mean_5m": uniform_filter(sand, size=5, mode="nearest")}


def add_sand(data, layers):
    for name in SAND_FEATURES:
        data[name] = layers[name][data.row.to_numpy(), data.col.to_numpy()].astype("float32")
    return data


def scores(data, features):
    """E2's AUC summary plus the boxwork-only scores for one set and model."""
    aucs, oof = lb.leave_one_block_out(data, features)
    box = data.block.isin(BOXWORK_BLOCKS).to_numpy()
    # Leave-one-block-out using only the boxwork blocks.
    within = []
    for b in BOXWORK_BLOCKS:
        train = box & (data.block != b).to_numpy()
        test = (data.block == b).to_numpy()
        model = lb.new_model().fit(data.loc[train, features], data.visited[train])
        within.append(roc_auc_score(data.visited[test], model.predict_proba(data.loc[test, features])[:, 1]))
    raw = {
        "auc_per_block": aucs,
        "auc_mean": float(np.mean(aucs)),
        "auc_min": float(np.min(aucs)),
        "auc_max": float(np.max(aucs)),
        "auc_pooled_out_of_block": float(roc_auc_score(data.visited, oof)),
        "auc_mean_boxwork_blocks": float(np.mean([aucs[b] for b in BOXWORK_BLOCKS])),
        "auc_pooled_boxwork_blocks": float(roc_auc_score(data.visited[box], oof[box])),
        "auc_per_block_within_boxwork": within,
        "auc_mean_within_boxwork": float(np.mean(within)),
    }
    return raw


def rounded(raw):
    return {k: [round(float(a), 3) for a in v] if isinstance(v, list) else round(v, 3) for k, v in raw.items()}


def main():
    start = time.time()
    layers = sand_rasters()
    table = pd.read_parquet(common.E2_OUTPUT / "cell_features.parquet")
    sets = lb.comparison_sets(table)

    visited = table[table.visited == 1]
    report = {
        "blocks": cf.N_BLOCKS, "min_gap_m": cf.MIN_GAP_M, "main_set": MAIN_SET,
        "models": MODELS, "sand_source": "data/e8/sand.tif",
        "boxwork_blocks": list(BOXWORK_BLOCKS),
        "sol_range_per_block": {str(b): [int(g.sol.min()), int(g.sol.max())] for b, g in visited.groupby("block")},
        "sets": {},
    }
    raw_all = {}
    for name, data in sets.items():
        data = add_sand(data, layers)
        sets[name] = data
        entry = {"visited": int(data.visited.sum()), "not_visited": int((data.visited == 0).sum())}
        raw_all[name] = {}
        for model_name, feats in MODELS.items():
            raw = scores(data, feats)
            raw_all[name][model_name] = raw
            entry[model_name] = rounded(raw)
        base, plus = raw_all[name]["dem_only"], raw_all[name]["dem_plus_sand"]
        entry["dem_plus_sand_minus_dem_only"] = {
            "auc_mean": round(plus["auc_mean"] - base["auc_mean"], 3),
            "auc_pooled_out_of_block": round(plus["auc_pooled_out_of_block"] - base["auc_pooled_out_of_block"], 3),
            "auc_mean_boxwork_blocks": round(plus["auc_mean_boxwork_blocks"] - base["auc_mean_boxwork_blocks"], 3),
            "auc_per_block": [round(p - b, 3) for p, b in zip(plus["auc_per_block"], base["auc_per_block"])],
            "blocks_improved": int(sum(p > b for p, b in zip(plus["auc_per_block"], base["auc_per_block"]))),
        }
        report["sets"][name] = entry
        print(f"{name:14s} done ({time.time() - start:.0f} s)")

    # dem_only must reproduce E2's published numbers.
    check = {name: entry for name, entry in report["sets"].items() if name in E2_REFERENCE}
    report["reproduces_e2"] = all(check[n]["dem_only"]["auc_mean"] == v for n, v in E2_REFERENCE.items())
    if not report["reproduces_e2"]:
        print("WARNING: dem_only does not reproduce E2:",
              {n: (check[n]["dem_only"]["auc_mean"], v) for n, v in E2_REFERENCE.items()})

    # dem_plus_sand fitted on the whole main set, and sand statistics there.
    main_set = sets[MAIN_SET]
    feats = MODELS["dem_plus_sand"]
    model = lb.new_model().fit(main_set[feats], main_set.visited)
    report["dem_plus_sand_standardized_coefficients_main_set"] = {
        f: round(float(c), 3) for f, c in zip(feats, model[-1].coef_[0])}
    groups = main_set.groupby("visited")[SAND_FEATURES]
    label = {0: "not_visited", 1: "visited"}
    report["sand_stats_main_set"] = {
        label[v]: {
            "median": {f: round(float(x), 3) for f, x in med.items()},
            "mean": {f: round(float(x), 3) for f, x in groups.mean().loc[v].items()},
            "share_sand_above_0.5": round(float((main_set.loc[main_set.visited == v, "sand"] > 0.5).mean()), 3),
        }
        for v, med in groups.median().iterrows()
    }
    report["runtime_s"] = round(time.time() - start, 1)
    OUTPUT.write_text(json.dumps(report, indent=2), encoding="utf-8")

    # Compact summary.
    print(f"\n{'set':14s} {'model':14s} {'mean':>6s} {'min':>6s} {'max':>6s} {'pooled':>7s} "
          f"{'box2-4':>7s} {'within':>7s}")
    for name, entry in report["sets"].items():
        for model_name in MODELS:
            m = entry[model_name]
            print(f"{name:14s} {model_name:14s} {m['auc_mean']:6.3f} {m['auc_min']:6.3f} {m['auc_max']:6.3f} "
                  f"{m['auc_pooled_out_of_block']:7.3f} {m['auc_mean_boxwork_blocks']:7.3f} "
                  f"{m['auc_mean_within_boxwork']:7.3f}")
        d = entry["dem_plus_sand_minus_dem_only"]
        print(f"{'':14s} {'delta':14s} {d['auc_mean']:+6.3f}  blocks improved {d['blocks_improved']}/{cf.N_BLOCKS} "
              f"{d['auc_per_block']}")
    print("reproduces E2 (0.526 / 0.730):", report["reproduces_e2"])
    print("dem_plus_sand coefficients:", report["dem_plus_sand_standardized_coefficients_main_set"])
    print("sand stats (main set):", json.dumps(report["sand_stats_main_set"]))
    print(f"{OUTPUT}  ({report['runtime_s']} s)")


if __name__ == "__main__":
    main()
