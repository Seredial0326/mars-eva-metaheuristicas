"""Cut E8 training and validation patches (issue #11).

Patches of 256 x 256 px (64 x 64 m at 0.25 m) from the colour orthophoto and the weak
labels. Training patches never touch the validation region or a buffer around it, so
neighbouring pixels cannot leak across the split. Validation patches come only from
inside the validation region; the ~50 hand-labelled patches are chosen from them later.

Run from the data/ folder:
  python ../src/dl_boxwork/make_patches.py --val SW-S [--size 256] [--buffer-m 16] [--min-labelled 0.2]
  -> e8/patches_train.npz, e8/patches_val.npz, e8/patches_summary.json, e8/patches_preview.png
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from matplotlib.colors import ListedColormap

IGNORE = 255
OUT = Path("e8")
HALF = 4000
REGIONS = {"NW": (0, 0, HALF, HALF), "NE": (0, HALF, HALF, HALF), "SW": (HALF, 0, HALF, HALF),
           "SE": (HALF, HALF, HALF, HALF), "SW-N": (HALF, 0, HALF // 2, HALF),
           "SW-S": (HALF + HALF // 2, 0, HALF // 2, HALF)}

parser = argparse.ArgumentParser()
parser.add_argument("--val", choices=list(REGIONS), required=True)
parser.add_argument("--size", type=int, default=256, help="patch side in px")
parser.add_argument("--buffer-m", type=float, default=16, help="gap between train patches and the validation region")
parser.add_argument("--min-labelled", type=float, default=0.2, help="min fraction of non-ignore px in a train patch")
args = parser.parse_args()

with rasterio.open("base/ortho_color_025.tif") as src:
    rgb = src.read().transpose(1, 2, 0)  # (H, W, 3) uint8
with rasterio.open(OUT / "labels_025.tif") as src:
    lab = src.read(1)
H, W = lab.shape
s = args.size
buf = int(round(args.buffer_m / 0.25))
r0, c0, hh, ww = REGIONS[args.val]
val_box = (r0, c0, r0 + hh, c0 + ww)
blocked = (r0 - buf, c0 - buf, r0 + hh + buf, c0 + ww + buf)


def overlaps(r, c, box):
    return r < box[2] and r + s > box[0] and c < box[3] and c + s > box[1]


def inside(r, c, box):
    return r >= box[0] and c >= box[1] and r + s <= box[2] and c + s <= box[3]


train_rc, val_rc, skipped = [], [], 0
for r in range(0, H - s + 1, s):
    for c in range(0, W - s + 1, s):
        if inside(r, c, val_box):
            val_rc.append((r, c))
        elif not overlaps(r, c, blocked):
            if np.mean(lab[r:r + s, c:c + s] != IGNORE) >= args.min_labelled:
                train_rc.append((r, c))
            else:
                skipped += 1


def stack(rcs):
    X = np.stack([rgb[r:r + s, c:c + s] for r, c in rcs])
    Y = np.stack([lab[r:r + s, c:c + s] for r, c in rcs])
    return X, Y, np.array(rcs, dtype=np.int32)


Xt, Yt, RCt = stack(train_rc)
Xv, Yv, RCv = stack(val_rc)
np.savez_compressed(OUT / "patches_train.npz", X=Xt, Y=Yt, rc=RCt)
np.savez_compressed(OUT / "patches_val.npz", X=Xv, Y=Yv, rc=RCv)


def pct(Y):
    names = {0: "background", 1: "ridge", 2: "trough", IGNORE: "ignore"}
    return {n: round(100 * float(np.mean(Y == v)), 2) for v, n in names.items()}


summary = {
    "params": vars(args),
    "patch_m": s * 0.25,
    "n_train": len(train_rc), "n_val": len(val_rc), "n_train_skipped_mostly_ignore": skipped,
    "class_pct_train": pct(Yt), "class_pct_val_weak": pct(Yv),
    "note": "validation weak labels are for reference only; the score that counts is against hand labels",
}
(OUT / "patches_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))

# Preview: 8 random TRAINING patches with their weak labels
rng = np.random.default_rng(0)
idx = rng.choice(len(Xt), size=min(8, len(Xt)), replace=False)
colors = ListedColormap(["#00000000", "#e41a1c", "#377eb8", "#ffff0040"])
fig, axes = plt.subplots(2, len(idx), figsize=(2.6 * len(idx), 5.4), squeeze=False)
for j, i in enumerate(idx):
    axes[0, j].imshow(Xt[i])
    axes[0, j].set_title(f"r{RCt[i][0]} c{RCt[i][1]}", fontsize=8)
    axes[1, j].imshow(Xt[i])
    axes[1, j].imshow(np.where(Yt[i] == IGNORE, 3, Yt[i]), cmap=colors, vmin=0, vmax=3, interpolation="nearest")
for a in axes.flat:
    a.axis("off")
fig.tight_layout()
fig.savefig(OUT / "patches_preview.png", dpi=90)
print("saved e8/patches_train.npz, e8/patches_val.npz, e8/patches_summary.json, e8/patches_preview.png")
