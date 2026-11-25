"""Point-based blind validation for E8 (issue #11): faster and easier than painting.

Standard accuracy assessment for remote-sensing maps (stratified random sampling,
Olofsson et al. 2014): random points are drawn inside the validation region, stratified
by the class the U-Net predicted there. For each point you see only the orthophoto with
a cross-hair (never the prediction) and press one key. Then:
  - user's accuracy per class = how often a predicted ridge/sand/background is right
  - producer's accuracy and overall accuracy, area-weighted (Olofsson et al. 2014)
  - the same points also score the weak rules (v3)

Run from the data/ folder:
  python ../src/dl_boxwork/point_labels.py sample [--n 80] [--seed 2]   -> e8/points.csv
  python ../src/dl_boxwork/point_labels.py label                         (window: keys below)
  python ../src/dl_boxwork/point_labels.py score                         -> e8/point_scores.json
Keys while labelling:  1 ridge   2 sand/trough   3 background   0 unsure   b back   q save and quit
Answers are saved after every key, so you can stop and resume any time.
"""
import argparse
import csv
import json
import math
from pathlib import Path

import numpy as np
import rasterio

OUT = Path("e8")
POINTS = OUT / "points.csv"
NAMES = {0: "background", 1: "ridge", 2: "trough"}
KEYS = {"1": 1, "2": 2, "3": 0, "0": -1}  # -1 = unsure
HALF = 4000
REGIONS = {"SW-S": (HALF + HALF // 2, 0, HALF // 2, HALF), "SW-N": (HALF, 0, HALF // 2, HALF),
           "NW": (0, 0, HALF, HALF), "NE": (0, HALF, HALF, HALF), "SE": (HALF, HALF, HALF, HALF)}
CTX, ZOOM = 128, 32  # half-sizes in 0.25 m px: 64 m context window, 16 m zoom

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["sample", "label", "score"])
parser.add_argument("--val", default="SW-S", choices=list(REGIONS))
parser.add_argument("--n", type=int, default=80, help="points per predicted class")
parser.add_argument("--seed", type=int, default=2)
args = parser.parse_args()


def load_points():
    with open(POINTS, newline="") as f:
        return list(csv.DictReader(f))


def save_points(rows):
    with open(POINTS, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)


if args.mode == "sample":
    with rasterio.open(OUT / "pred_classes_025.tif") as src:
        pred = src.read(1)
    r0, c0, hh, ww = REGIONS[args.val]
    rng = np.random.default_rng(args.seed)
    inner = pred[r0 + CTX:r0 + hh - CTX, c0 + CTX:c0 + ww - CTX]  # keep the context window inside
    rows = []
    for cls in (1, 2, 0):
        rr, cc = np.nonzero(inner == cls)
        pick = rng.choice(len(rr), size=min(args.n, len(rr)), replace=False)
        rows += [{"row": int(rr[i] + r0 + CTX), "col": int(cc[i] + c0 + CTX), "stratum": cls, "answer": ""}
                 for i in pick]
    order = rng.permutation(len(rows))  # shuffle so strata are not guessable from the order
    rows = [rows[i] for i in order]
    region = pred[r0:r0 + hh, c0:c0 + ww]
    weights = {str(c): float(np.mean(region == c)) for c in (0, 1, 2)}
    (OUT / "points_strata.json").write_text(json.dumps({"val": args.val, "area_share_predicted": weights}, indent=2))
    save_points(rows)
    print(f"{len(rows)} points saved to {POINTS}; predicted area shares in {args.val}: {weights}")
    raise SystemExit

if args.mode == "label":
    import matplotlib.pyplot as plt

    with rasterio.open("base/ortho_color_025.tif") as src:
        img = src.read().transpose(1, 2, 0)
    rows = load_points()
    state = {"i": next((k for k, r in enumerate(rows) if r["answer"] == ""), len(rows))}
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 6.8))

    def draw():
        i = state["i"]
        a1.clear(); a2.clear()
        if i >= len(rows):
            fig.suptitle("All points labelled. Press q to save and quit.")
            fig.canvas.draw_idle()
            return
        r, c = int(rows[i]["row"]), int(rows[i]["col"])
        a1.imshow(img[r - CTX:r + CTX, c - CTX:c + CTX], extent=(-32, 32, 32, -32))
        a1.add_patch(plt.Rectangle((-4, -4), 8, 8, fill=False, ec="yellow", lw=1.5))
        a1.set_title("context 64 m (yellow box = zoom)")
        a2.imshow(img[r - ZOOM:r + ZOOM, c - ZOOM:c + ZOOM], extent=(-8, 8, 8, -8), interpolation="nearest")
        a2.plot([-8, -1], [0, 0], "y-", [1, 8], [0, 0], "y-", [0, 0], [-8, -1], "y-", [0, 0], [1, 8], "y-", lw=1.5)
        a2.set_title("zoom 16 m: what is UNDER the centre of the cross?")
        done = sum(rr["answer"] != "" for rr in rows)
        fig.suptitle(f"point {i + 1}/{len(rows)}  (done {done})   1 ridge   2 sand/trough   3 background   "
                     f"0 unsure   b back   q quit")
        fig.canvas.draw_idle()

    def on_key(event):
        k = event.key
        if k in KEYS and state["i"] < len(rows):
            rows[state["i"]]["answer"] = str(KEYS[k])
            save_points(rows)
            state["i"] += 1
        elif k == "b" and state["i"] > 0:
            state["i"] -= 1
        elif k == "q":
            save_points(rows)
            plt.close(fig)
            return
        draw()

    fig.canvas.mpl_connect("key_press_event", on_key)
    draw()
    plt.show()
    raise SystemExit

# ---- score ---------------------------------------------------------------------------------
rows = [r for r in load_points() if r["answer"] not in ("", "-1")]
unsure = sum(r["answer"] == "-1" for r in load_points())
W = {int(k): v for k, v in json.loads((OUT / "points_strata.json").read_text())["area_share_predicted"].items()}
with rasterio.open(OUT / "labels_025.tif") as src:
    weak = src.read(1)


def wilson(k, n, z=1.96):
    if n == 0:
        return [None, None]
    p = k / n
    d = 1 + z * z / n
    m = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return [round(m - h, 3), round(m + h, 3)]


n = np.zeros((3, 3))  # rows: predicted stratum, cols: reference answer
for r in rows:
    n[int(r["stratum"]), int(r["answer"])] += 1
ni = n.sum(1)
p = np.array([[W[i] * n[i, j] / ni[i] if ni[i] else 0 for j in range(3)] for i in range(3)])  # area proportions
ua = {NAMES[i]: {"value": round(n[i, i] / ni[i], 3) if ni[i] else None, "ci95": wilson(n[i, i], ni[i]),
                 "n": int(ni[i])} for i in range(3)}
pa = {NAMES[j]: round(p[j, j] / p[:, j].sum(), 3) if p[:, j].sum() else None for j in range(3)}

agree = [(int(weak[int(r["row"]), int(r["col"])]), int(r["answer"])) for r in rows]
agree = [(w_, a) for w_, a in agree if w_ != 255]
scores = {
    "points_answered": len(rows), "points_unsure": unsure,
    "unet_users_accuracy": ua,
    "unet_producers_accuracy_area_weighted": pa,
    "unet_overall_accuracy_area_weighted": round(float(np.trace(p)), 3),
    "reference_area_share_estimate": {NAMES[j]: round(float(p[:, j].sum()), 3) for j in range(3)},
    "confusion_counts_rows_pred_cols_ref": n.astype(int).tolist(),
    "weak_rules_v3_accuracy_where_labelled": {"value": round(np.mean([w_ == a for w_, a in agree]), 3) if agree else None,
                                              "n": len(agree)},
    "method": "stratified random sampling by predicted class, area-weighted estimators (Olofsson et al. 2014)",
}
(OUT / "point_scores.json").write_text(json.dumps(scores, indent=2))
print(json.dumps(scores, indent=2))
