"""E2 (hours 4-12): logistic baseline, visited or not from terrain features.

This is the bar E1 (MaxEnt IRL) has to beat. For each comparison set it fits a
logistic regression on standardized features and reports the AUC with
leave-one-block-out validation: the route is split into N_BLOCKS consecutive
stretches (cell_features.py), each block is scored by a model trained on the
other blocks, and cells inherit the block of their nearest visited cell.

Comparison sets: visited cells against not visited cells within 25, 50 (main)
and 100 m of the route, plus the whole box as a reference (not visited cells
subsampled at random to BOX_NEGATIVES; a random subsample does not bias the AUC).
Two models: all features, and slope only.

Output in data/e2/:
  logistic_baseline.json   AUC per block and mean for every set and model,
                           coefficients of the main model, feature medians
  logistic_roc.png         ROC curves of the main set (out-of-block predictions)
  visit_probability.tif    main model applied to every cell of the box: a relative
                           0-1 score of how route-like the terrain is (class-balanced
                           fit, so it is not a calibrated probability)

Usage:  python src/ml/logistic_baseline.py   (after cell_features.py)
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score, roc_curve
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

import cell_features as cf
import common

CORRIDORS_M = (25, 50, 100)
MAIN_CORRIDOR_M = 50
BOX_NEGATIVES = 400_000
SEED = 0
MODELS = {"all_features": cf.FEATURES, "slope_only": ["slope_deg"]}


def new_model():
    return make_pipeline(StandardScaler(), LogisticRegression(class_weight="balanced", max_iter=1000))


def leave_one_block_out(table, features):
    """AUC of each held-out block and the out-of-block score of every cell."""
    oof = np.full(len(table), np.nan)
    aucs = []
    for b in range(cf.N_BLOCKS):
        test = (table.block == b).to_numpy()
        model = new_model().fit(table.loc[~test, features], table.visited[~test])
        oof[test] = model.predict_proba(table.loc[test, features])[:, 1]
        aucs.append(roc_auc_score(table.visited[test], oof[test]))
    return aucs, oof


def comparison_sets(table):
    vis = table.visited == 1
    sets = {f"corridor_{d}m": table[vis | (table.dist_to_route_m <= d)].reset_index(drop=True) for d in CORRIDORS_M}
    box = cf.build_table(max_dist_m=None)
    neg = box[box.visited == 0].sample(n=BOX_NEGATIVES, random_state=SEED)
    sets["whole_box"] = pd.concat([box[box.visited == 1], neg], ignore_index=True)
    return sets


def main():
    table = pd.read_parquet(common.E2_OUTPUT / "cell_features.parquet")
    report = {"blocks": cf.N_BLOCKS, "min_gap_m": cf.MIN_GAP_M, "features": cf.FEATURES, "sets": {}}
    roc = {}
    for name, data in comparison_sets(table).items():
        entry = {"visited": int(data.visited.sum()), "not_visited": int((data.visited == 0).sum())}
        for model_name, feats in MODELS.items():
            aucs, oof = leave_one_block_out(data, feats)
            entry[model_name] = {
                "auc_mean": round(float(np.mean(aucs)), 3), "auc_min": round(float(np.min(aucs)), 3),
                "auc_max": round(float(np.max(aucs)), 3), "auc_per_block": [round(float(a), 3) for a in aucs],
                "auc_pooled_out_of_block": round(float(roc_auc_score(data.visited, oof)), 3),
            }
            if name == f"corridor_{MAIN_CORRIDOR_M}m":
                roc[model_name] = roc_curve(data.visited, oof)
        report["sets"][name] = entry
        print(f"{name:14s} all features AUC {entry['all_features']['auc_mean']:.3f} "
              f"[{entry['all_features']['auc_min']:.3f}-{entry['all_features']['auc_max']:.3f}] · "
              f"slope only {entry['slope_only']['auc_mean']:.3f}")

    # Main model fitted on every block: coefficients and probability map.
    main_set = table[(table.visited == 1) | (table.dist_to_route_m <= MAIN_CORRIDOR_M)]
    model = new_model().fit(main_set[cf.FEATURES], main_set.visited)
    coefs = model[-1].coef_[0]
    report["main_set"] = f"corridor_{MAIN_CORRIDOR_M}m"
    report["main_model_standardized_coefficients"] = {f: round(float(c), 3) for f, c in zip(cf.FEATURES, coefs)}
    report["feature_medians_main_set"] = {
        ("visited" if v else "not_visited"): {f: round(float(m), 3) for f, m in row.items()}
        for v, row in main_set.groupby("visited")[cf.FEATURES].median().iterrows()
    }

    layers, _ = cf.feature_rasters()
    grid = pd.DataFrame({f: layers[f].ravel() for f in cf.FEATURES})
    prob = model.predict_proba(grid)[:, 1].reshape(layers["slope_deg"].shape).astype("float32")
    with rasterio.open(common.base_layer("dem_1m.tif")) as src:
        profile = src.profile | {"dtype": "float32", "nodata": np.nan, "compress": "deflate"}
    with rasterio.open(common.E2_OUTPUT / "visit_probability.tif", "w", **profile) as dst:
        dst.write(prob, 1)

    fig, ax = plt.subplots(figsize=(5.5, 5.5), constrained_layout=True)
    for model_name, (fpr, tpr, _) in roc.items():
        auc = report["sets"][report["main_set"]][model_name]["auc_pooled_out_of_block"]
        ax.plot(fpr, tpr, label=f"{model_name} (AUC {auc:.3f})")
    ax.plot([0, 1], [0, 1], "k--", lw=0.8, label="chance (0.5)")
    ax.set_xlabel("false positive rate")
    ax.set_ylabel("true positive rate")
    ax.set_title(f"Logistic baseline, {MAIN_CORRIDOR_M} m corridor, out-of-block")
    ax.legend(loc="lower right")
    fig.savefig(common.E2_OUTPUT / "logistic_roc.png", dpi=110)

    (common.E2_OUTPUT / "logistic_baseline.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    print("coefficients (standardized):", report["main_model_standardized_coefficients"])


if __name__ == "__main__":
    main()
