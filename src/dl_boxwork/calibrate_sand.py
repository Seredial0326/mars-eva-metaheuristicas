"""E8 v1, option A (issue #11): pick a sand threshold on p_sand with the existing blind points.

The v0 map uses argmax with class weights, which is conservative (sand recall ~0.11).
Here the rule becomes "sand if p_sand >= t". Precision and recall of any t are estimated
from the 240 blind points of SW-S with the same area-weighted estimators as point_labels.py
(Olofsson et al. 2014): the points were stratified by the v0 argmax class, so each point
weighs W[stratum] / n[stratum] whatever rule is evaluated.

Choosing t on the same points that score it would be optimistic, so t is chosen on one
random half and scored on the other half, many times (repeated 2-fold). Only those
out-of-sample numbers are reported as the result; the final t uses all points.

Run from the data/ folder, after predict_unet.py --prob-only:
  python ../src/dl_boxwork/calibrate_sand.py [--min-precision 0.8] [--write]
  -> e8/sand_calibration.json, e8/sand_calibration.png
     with --write: e8/sand_v1.tif (1 m fraction of sub-cells with p_sand >= t; sand.tif untouched)
"""
import argparse
import csv
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

OUT = Path("e8")
SAND = 2
parser = argparse.ArgumentParser()
parser.add_argument("--points", default="e8/points.csv", help="pass-2 blind points")
parser.add_argument("--min-precision", type=float, default=0.8,
                    help="choose the t with the best recall among those with precision >= this "
                         "(falls back to the best F1)")
parser.add_argument("--splits", type=int, default=200, help="random half splits for the out-of-sample score")
parser.add_argument("--seed", type=int, default=11)
parser.add_argument("--write", action="store_true", help="write e8/sand_v1.tif with the chosen t")
args = parser.parse_args()

with rasterio.open(OUT / "p_sand_025.tif") as src:
    psand = src.read(1)
rows = [r for r in csv.DictReader(open(args.points)) if r["answer"] not in ("", "-1")]
W = {int(k): v for k, v in json.loads((OUT / "points_strata.json").read_text())["area_share_predicted"].items()}
stratum = np.array([int(r["stratum"]) for r in rows])
is_sand = np.array([int(r["answer"]) == SAND for r in rows])
p = np.array([psand[int(r["row"]), int(r["col"])] / 254.0 for r in rows])
T = np.round(np.arange(0.05, 0.96, 0.05), 2)


def scores(idx, t):
    """Area-weighted precision, recall, F1 of 'sand if p >= t' on the points idx."""
    w = np.zeros(len(idx))
    for s in (0, 1, 2):
        m = stratum[idx] == s
        if m.any():
            w[m] = W[s] / m.sum()
    pred = p[idx] >= t
    tp = w[pred & is_sand[idx]].sum()
    prec = tp / w[pred].sum() if w[pred].sum() else np.nan
    rec = tp / w[is_sand[idx]].sum() if w[is_sand[idx]].sum() else np.nan
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else np.nan
    return prec, rec, f1


def choose(idx):
    s = np.array([scores(idx, t) for t in T])
    ok = s[:, 0] >= args.min_precision
    if ok.any():
        return T[ok][np.nanargmax(s[ok, 1])]
    return T[np.nanargmax(s[:, 2])]


allidx = np.arange(len(rows))
curve = np.array([scores(allidx, t) for t in T])
rng = np.random.default_rng(args.seed)
oos = []
for _ in range(args.splits):
    perm = rng.permutation(len(rows))
    a, b = perm[: len(rows) // 2], perm[len(rows) // 2:]
    for fit, test in ((a, b), (b, a)):
        oos.append(scores(test, choose(fit)))
oos = np.array(oos)
t_final = float(choose(allidx))


def band(x):
    x = x[~np.isnan(x)]
    return [round(float(np.median(x)), 3), round(float(np.percentile(x, 2.5)), 3), round(float(np.percentile(x, 97.5)), 3)]


# v0 reference with the same estimator: argmax sand == stratum 2
w_all = np.array([W[s] / (stratum == s).sum() for s in stratum])
tp0 = w_all[(stratum == SAND) & is_sand].sum()
result = {
    "points": len(rows), "sand_answers": int(is_sand.sum()),
    "rule": f"sand if p_sand >= t; t maximises recall with precision >= {args.min_precision} (else best F1)",
    "v0_argmax": {"precision": round(float(tp0 / w_all[stratum == SAND].sum()), 3),
                  "recall": round(float(tp0 / w_all[is_sand].sum()), 3)},
    "t_final_all_points": t_final,
    "in_sample_at_t_final": dict(zip(("precision", "recall", "f1"),
                                     [round(float(x), 3) for x in scores(allidx, t_final)])),
    "out_of_sample_repeated_2fold_median_p2.5_p97.5": {"precision": band(oos[:, 0]), "recall": band(oos[:, 1]),
                                                       "f1": band(oos[:, 2])},
    "curve": {str(t): [round(float(x), 3) for x in c] for t, c in zip(T, curve)},
    "note": "points are from SW-S only; t is applied to the whole bbox",
}
(OUT / "sand_calibration.json").write_text(json.dumps(result, indent=2))
print(json.dumps({k: v for k, v in result.items() if k != "curve"}, indent=2))

fig, ax = plt.subplots(figsize=(6.5, 4))
ax.plot(T, curve[:, 0], "-o", ms=3, label="precision")
ax.plot(T, curve[:, 1], "-o", ms=3, label="recall")
ax.plot(T, curve[:, 2], "-o", ms=3, label="F1")
ax.axvline(t_final, color="k", ls="--", lw=1, label=f"chosen t = {t_final}")
ax.set_xlabel("threshold on p_sand")
ax.set_ylim(0, 1)
ax.set_title("Sand rule vs blind points (SW-S, area-weighted)")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(OUT / "sand_calibration.png", dpi=150)
print("saved e8/sand_calibration.json, e8/sand_calibration.png")

if args.write:
    H, Wd = psand.shape
    sand_v1 = (psand >= round(t_final * 254)).reshape(H // 4, 4, Wd // 4, 4).mean(axis=(1, 3)).astype("float32")
    with rasterio.open("base/dem_1m.tif") as dem:
        prof = dem.profile.copy()
    prof.update(dtype="float32", nodata=np.nan, count=1, compress="deflate", tiled=True, blockxsize=256, blockysize=256)
    with rasterio.open(OUT / "sand_v1.tif", "w", **prof) as dst:
        dst.write(sand_v1, 1)
    print(f"saved e8/sand_v1.tif (t = {t_final}); mean sand fraction {sand_v1.mean():.4f}")
