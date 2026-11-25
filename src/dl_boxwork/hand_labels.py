"""Blind hand labels for E8 validation (issue #11).

export: writes N orthophoto patches from the validation region (never seen by the rules
        or the training) as PNGs enlarged 3x, plus an empty copy to paint on. No weak
        labels or predictions are shown, so the hand labels stay independent.
score:  reads the painted copies and scores the U-Net prediction and the weak labels
        against them, only on painted pixels.

Paint ON the *_paint.png copies with the PENCIL or a hard brush, pure colours only:
  red   (255,0,0)  = ridge        blue (0,0,255) = trough/sand
  green (0,255,0)  = background   unpainted      = not scored
Partial labelling is fine: paint only what you are sure of, in every class.

Run from the data/ folder:
  python ../src/dl_boxwork/hand_labels.py export [--n 50] [--seed 1]
  python ../src/dl_boxwork/hand_labels.py score  [--tol-m 1.0]
  -> e8/hand/*.png, e8/hand/index.csv ; e8/hand_scores.json
"""
import argparse
import csv
import json
from pathlib import Path

import numpy as np
import rasterio
from PIL import Image
from scipy.ndimage import binary_dilation

OUT, HAND = Path("e8"), Path("e8/hand")
SCALE = 3
COLORS = {1: (255, 0, 0), 2: (0, 0, 255), 0: (0, 255, 0)}  # ridge, trough, background
NAMES = {0: "background", 1: "ridge", 2: "trough"}
IGNORE = 255

parser = argparse.ArgumentParser()
parser.add_argument("mode", choices=["export", "score"])
parser.add_argument("--n", type=int, default=50)
parser.add_argument("--seed", type=int, default=1)
parser.add_argument("--color-tol", type=float, default=60, help="max RGB distance to a pure label colour")
parser.add_argument("--tol-m", type=float, default=1.0, help="ridge tolerance for precision/recall (m)")
args = parser.parse_args()

if args.mode == "export":
    va = np.load(OUT / "patches_val.npz")
    X, RC = va["X"], va["rc"]
    idx = np.sort(np.random.default_rng(args.seed).choice(len(X), size=min(args.n, len(X)), replace=False))
    HAND.mkdir(parents=True, exist_ok=True)
    with open(HAND / "index.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["patch", "val_index", "row_025", "col_025"])
        for k, i in enumerate(idx):
            big = Image.fromarray(X[i]).resize((X[i].shape[1] * SCALE, X[i].shape[0] * SCALE), Image.NEAREST)
            name = f"p{k:02d}"
            big.save(HAND / f"{name}_ortho.png")
            big.save(HAND / f"{name}_paint.png")
            w.writerow([name, int(i), int(RC[i][0]), int(RC[i][1])])
    print(f"exported {len(idx)} patches to e8/hand/ (paint on *_paint.png, keep *_ortho.png as reference)")
    raise SystemExit

# ---- score -------------------------------------------------------------------------------
with rasterio.open(OUT / "pred_classes_025.tif") as src:
    pred_all = src.read(1)
with rasterio.open(OUT / "labels_025.tif") as src:
    weak_all = src.read(1)
rows = list(csv.DictReader(open(HAND / "index.csv")))
s = 256
tol_px = int(round(args.tol_m / 0.25))
conf = {"unet": np.zeros((3, 3), "int64"), "weak": np.zeros((3, 3), "int64")}
ridge_pr = {k: [0, 0, 0, 0] for k in conf}  # tp_pred, n_pred, tp_ref, n_ref (with tolerance)
used = 0
for r in rows:
    painted = np.asarray(Image.open(HAND / f"{r['patch']}_paint.png").convert("RGB")).astype("float32")
    ortho = np.asarray(Image.open(HAND / f"{r['patch']}_ortho.png").convert("RGB")).astype("float32")
    pick = (slice(SCALE // 2, None, SCALE), slice(SCALE // 2, None, SCALE))  # centre pixel of each 3x3 block
    painted, changed = painted[pick][:s, :s], (np.abs(painted - ortho).sum(-1) > 0)[pick][:s, :s]
    ref = np.full((s, s), IGNORE, "uint8")
    for cls, col in COLORS.items():  # only pixels the labeller actually changed count
        ref[changed & (np.linalg.norm(painted - np.array(col, "float32"), axis=-1) <= args.color_tol)] = cls
    if (ref != IGNORE).sum() == 0:
        continue
    used += 1
    r0, c0 = int(r["row_025"]), int(r["col_025"])
    m = ref != IGNORE
    for key, src in (("unet", pred_all), ("weak", weak_all)):
        p = src[r0:r0 + s, c0:c0 + s]
        mm = m & (p != IGNORE)
        conf[key] += np.bincount(3 * ref[mm].astype("int64") + p[mm], minlength=9).reshape(3, 3)
        # ridge precision/recall with spatial tolerance, on painted area only
        ref_r, pred_r = (ref == 1), (p == 1) & m
        ridge_pr[key][0] += int((pred_r & binary_dilation(ref_r, iterations=tol_px)).sum())
        ridge_pr[key][1] += int(pred_r.sum())
        ridge_pr[key][2] += int((ref_r & binary_dilation(pred_r, iterations=tol_px)).sum())
        ridge_pr[key][3] += int(ref_r.sum())


def metrics(cm, pr):
    iou = np.diag(cm) / np.maximum(cm.sum(0) + cm.sum(1) - np.diag(cm), 1)
    prec = pr[0] / max(pr[1], 1)
    rec = pr[2] / max(pr[3], 1)
    return {"iou": {NAMES[c]: round(float(iou[c]), 3) for c in range(3)},
            "pixel_accuracy": round(float(np.trace(cm) / max(cm.sum(), 1)), 3),
            "ridge_precision_tol": round(prec, 3), "ridge_recall_tol": round(rec, 3),
            "ridge_f1_tol": round(2 * prec * rec / max(prec + rec, 1e-9), 3),
            "confusion_rows_ref_cols_pred": cm.tolist()}


scores = {"patches_scored": used, "tolerance_m": args.tol_m,
          "painted_px_per_class": {NAMES[c]: int(conf["unet"][c].sum()) for c in range(3)},
          "unet": metrics(conf["unet"], ridge_pr["unet"]), "weak_rules_v3": metrics(conf["weak"], ridge_pr["weak"])}
(OUT / "hand_scores.json").write_text(json.dumps(scores, indent=2))
print(json.dumps(scores, indent=2))
