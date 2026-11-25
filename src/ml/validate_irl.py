"""E1 step 4 - leave-one-block-out validation of the learned terrain prices.

For each of the 5 E2 blocks (src/ml/cell_features.py), fit on the other four
blocks and test on this one, which the model has not seen. Two models:
  terrain        every feature of irl_data.FEATURES
  distance_only  control: only the price of a metre (knows start and goal too)

Metrics on every held-out demonstration:
  nll_per_m    how surprised the model is by the real route (lower is better)
  hausdorff_m  largest gap between the real route and the predicted one, where
               the predicted route is the cheapest path from start to goal under
               the learned prices (skimage MCP with geometric=True: the same
               move cost d * (c(u) + c(v)) / 2 as the model)
  within_5m / within_10m  share of the real route's cells within 5 / 10 m of
               the predicted route

Cell-level AUC, comparable with E2's logistic baseline: every cell scores
-(w . phi) with the out-of-block weights, on E2's comparison sets (50 m
corridor and whole box). The distance-only control gives every cell the same
score (AUC 0.5), so only the terrain model is scored.

Output: data/e1/validation_<tag>.json, tag from the options (see irl_data.setup)
Usage:  python src/ml/validate_irl.py                                    one demo per sol, 1 m, 50 m margin
        python src/ml/validate_irl.py --piece-m 250 --cell 5 --whole-box  250 m pieces, 5 m cells, whole box
"""
import argparse
import json
import time

import numpy as np
import pandas as pd
import torch
from scipy.spatial import cKDTree
from skimage.graph import route_through_array
from sklearn.metrics import roc_auc_score

import cell_features as cf
import common
import irl_data
import logistic_baseline as lb
import maxent_irl as irl


def route_metrics(w, demo, cell_m):
    cost = np.tensordot(w, demo.phi, axes=1)
    start, goal = tuple(demo.path[0]), tuple(demo.path[-1])
    pred, _ = route_through_array(cost, start, goal, fully_connected=True, geometric=True)
    pred = np.asarray(pred)
    d_real = cKDTree(pred).query(demo.path)[0] * cell_m     # each real cell to the predicted route
    d_pred = cKDTree(demo.path).query(pred)[0] * cell_m
    return {"hausdorff_m": float(max(d_real.max(), d_pred.max())),
            "within_5m": float((d_real <= 5).mean()), "within_10m": float((d_real <= 10).mean()),
            "pred_length_m": irl_data.step_length(pred) * cell_m}


def summarise(rows):
    df = pd.DataFrame(rows)
    out = {}
    for model, g in df.groupby("model"):
        out[model] = {
            "nll_per_m": float(g.nll.sum() / g.length_m.sum()),
            "hausdorff_m_median": float(g.hausdorff_m.median()),
            "hausdorff_m_mean": float(g.hausdorff_m.mean()),
            # Route shares weighted by route length, so long demonstrations count more.
            "within_5m": float(np.average(g.within_5m, weights=g.length_m)),
            "within_10m": float(np.average(g.within_10m, weights=g.length_m)),
        }
    return out


def main():
    ap = argparse.ArgumentParser()
    irl_data.add_arguments(ap)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    t0 = time.perf_counter()

    tag, phi, table, demos, _ = irl_data.setup(args)
    print(f"{tag}: {len(demos)} demonstrations, device {device}", flush=True)
    n_f = len(irl_data.FEATURES)
    w_init = np.r_[3.0, np.full(n_f - 1, 0.5)]

    cells = pd.read_parquet(common.E2_OUTPUT / "cell_features.parquet")
    sets = {k: v for k, v in lb.comparison_sets(cells).items() if k in ("corridor_50m", "whole_box")}

    rows, per_block, auc_scores = [], [], {k: np.full(len(v), np.nan) for k, v in sets.items()}
    for b in range(cf.N_BLOCKS):
        train = [d for d, blk in zip(demos, table.block) if blk != b]
        test = [(d, r) for d, r in zip(demos, table.itertuples()) if r.block == b]
        batches = irl.make_batches(train, chunk=args.chunk, device=device)
        fits = {"terrain": irl.fit(batches, w_init)[0],
                "distance_only": irl.fit(batches, w_init, fixed={i: 0.0 for i in range(1, n_f)})[0]}
        test_batches = irl.make_batches([d for d, _ in test], chunk=args.chunk, device=device)
        for model, w in fits.items():
            ev = irl.evaluate(w, test_batches)
            nll = dict(zip(ev.names, ev.nll))
            for d, r in test:
                rows.append({"model": model, "block": b, "name": d.name, "sol": r.sol,
                             "length_m": d.length_m * args.cell, "nll": float(nll[d.name])}
                            | route_metrics(w, d, args.cell))
        for k, s in sets.items():
            m = (s.block == b).to_numpy()
            rr, cc = s.row[m].to_numpy() // args.cell, s.col[m].to_numpy() // args.cell
            auc_scores[k][m] = -np.tensordot(fits["terrain"], phi[:, rr, cc], axes=1)
        per_block.append({"block": b, "n_test": len(test),
                          "w_terrain": dict(zip(irl_data.FEATURES, np.round(fits["terrain"], 5).tolist())),
                          "w_distance_only": float(fits["distance_only"][0]),
                          "summary": summarise([r for r in rows if r["block"] == b])})
        print(f"block {b}: {len(test)} test demos | {per_block[-1]['summary']} "
              f"({time.perf_counter() - t0:.0f} s)", flush=True)

    auc = {}
    for k, s in sets.items():
        y = s.visited.to_numpy()
        per = [roc_auc_score(y[s.block == b], auc_scores[k][s.block == b]) for b in range(cf.N_BLOCKS)]
        auc[k] = {"per_block": per, "mean": float(np.mean(per))}
    e2 = json.loads((common.E2_OUTPUT / "logistic_baseline.json").read_text(encoding="utf-8"))
    report = {
        "tag": tag, "options": vars(args), "n_demos": len(demos), "features": irl_data.FEATURES,
        "summary": summarise(rows), "auc_terrain_cost": auc,
        "auc_e2_logistic": {k: e2["sets"][k]["all_features"]["auc_mean"] for k in sets
                            if k in e2["sets"]},
        "per_block": per_block, "per_demo": rows, "seconds": time.perf_counter() - t0,
    }
    out = common.E1_OUTPUT / f"validation_{tag}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps({k: report[k] for k in ("summary", "auc_terrain_cost", "auc_e2_logistic")}, indent=2))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
