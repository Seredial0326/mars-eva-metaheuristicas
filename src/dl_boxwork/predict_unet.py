"""Predict the E8 U-Net over the whole bbox (issue #11).

Sliding 1024 px windows with 128 px overlap; softmax probabilities are averaged where
windows overlap. Writes the 0.25 m class map and two 1 m layers on the base grid:
the fraction of each 1 m cell predicted as sand/trough and as ridge.

The preview NEVER shows the validation region, so hand labels made there stay blind.

Run from the data/ folder:
  python ../src/dl_boxwork/predict_unet.py [--ckpt e8/unet_v1.pt] [--val SW-S]
  -> e8/pred_classes_025.tif, e8/sand.tif, e8/ridge.tif, e8/predict_summary.json, e8/predict_preview.png
  python ../src/dl_boxwork/predict_unet.py --prob-only
  -> only e8/p_sand_025.tif (sand probability x 254, uint8), other outputs untouched
"""
import argparse
import json
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
import segmentation_models_pytorch as smp
import torch
from matplotlib.colors import ListedColormap

IGNORE, N_CLASSES = 255, 3
OUT = Path("e8")
MEAN = np.array([0.485, 0.456, 0.406], dtype="float32").reshape(3, 1, 1)
STD = np.array([0.229, 0.224, 0.225], dtype="float32").reshape(3, 1, 1)
HALF = 4000
REGIONS = {"NW": (0, 0, HALF, HALF), "NE": (0, HALF, HALF, HALF), "SE": (HALF, HALF, HALF, HALF),
           "SW-N": (HALF, 0, HALF // 2, HALF), "SW-S": (HALF + HALF // 2, 0, HALF // 2, HALF)}
DETAIL = 1000

parser = argparse.ArgumentParser()
parser.add_argument("--ckpt", default="e8/unet_v1.pt")
parser.add_argument("--val", default="SW-S", choices=["SW-S", "SW-N", "NW", "NE", "SE"])
parser.add_argument("--win", type=int, default=1024)
parser.add_argument("--overlap", type=int, default=128)
parser.add_argument("--prob-only", action="store_true",
                    help="write only e8/p_sand_025.tif (for threshold calibration) and stop")
args = parser.parse_args()
device = "cuda" if torch.cuda.is_available() else "cpu"

model = smp.Unet("efficientnet-b0", encoder_weights=None, in_channels=3, classes=N_CLASSES)
ckpt = torch.load(args.ckpt, map_location="cpu", weights_only=False)
model.load_state_dict(ckpt["state_dict"])
model.to(device).eval()

with rasterio.open("base/ortho_color_025.tif") as src:
    rgb = src.read()  # (3, H, W) uint8
    profile = src.profile.copy()
_, H, W = rgb.shape
win, step = args.win, args.win - args.overlap


def starts(n):
    s = list(range(0, n - win + 1, step))
    return s if s[-1] == n - win else s + [n - win]


prob = np.zeros((N_CLASSES, H, W), dtype="float32")
count = np.zeros((H, W), dtype="float32")
with torch.no_grad():
    for r in starts(H):
        for c in starts(W):
            x = (rgb[:, r:r + win, c:c + win].astype("float32") / 255.0 - MEAN) / STD
            logits = model(torch.from_numpy(x[None]).to(device))
            p = torch.softmax(logits.float(), dim=1)[0].cpu().numpy()
            prob[:, r:r + win, c:c + win] += p
            count[r:r + win, c:c + win] += 1
prob /= count
p8 = profile | {"count": 1, "dtype": "uint8", "nodata": IGNORE, "compress": "deflate", "tiled": True,
                "blockxsize": 256, "blockysize": 256, "photometric": "minisblack"}
p8.pop("interleave", None)
# sand probability, 0-254 (255 is nodata): used by calibrate_sand.py to pick a threshold
with rasterio.open(OUT / "p_sand_025.tif", "w", **p8) as dst:
    dst.write(np.round(prob[2] * 254).astype("uint8"), 1)
if args.prob_only:
    print("saved e8/p_sand_025.tif (sand probability x 254)")
    raise SystemExit
cls = prob.argmax(0).astype("uint8")
del prob, count

p8 = profile | {"count": 1, "dtype": "uint8", "nodata": IGNORE, "compress": "deflate", "tiled": True,
                "blockxsize": 256, "blockysize": 256, "photometric": "minisblack"}
p8.pop("interleave", None)
with rasterio.open(OUT / "pred_classes_025.tif", "w", **p8) as dst:
    dst.write(cls, 1)

# 1 m layers on the base grid: fraction of the 4 x 4 sub-cells in each class
with rasterio.open("base/dem_1m.tif") as dem:
    p1 = dem.profile.copy()
p1.update(dtype="float32", nodata=np.nan, count=1, compress="deflate", tiled=True)
blocks = cls.reshape(H // 4, 4, W // 4, 4)
sand = (blocks == 2).mean(axis=(1, 3)).astype("float32")
ridge = (blocks == 1).mean(axis=(1, 3)).astype("float32")
for name, a in (("sand.tif", sand), ("ridge.tif", ridge)):
    with rasterio.open(OUT / name, "w", **p1) as dst:
        dst.write(a, 1)


def region_mask(name):
    m = np.zeros((H, W), bool)
    r0, c0, hh, ww = REGIONS[name]
    m[r0:r0 + hh, c0:c0 + ww] = True
    return m


val = region_mask(args.val)
summary = {
    "ckpt": args.ckpt, "epoch": ckpt.get("epoch"),
    "class_pct_whole_bbox": {n: round(100 * float(np.mean(cls == v)), 2)
                             for n, v in (("background", 0), ("ridge", 1), ("trough", 2))},
    "class_pct_training_area": {n: round(100 * float(np.mean(cls[~val] == v)), 2)
                                for n, v in (("background", 0), ("ridge", 1), ("trough", 2))},
    "sand_1m_mean_fraction": round(float(sand.mean()), 4),
    "ridge_1m_mean_fraction": round(float(ridge.mean()), 4),
}
(OUT / "predict_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))

# Preview (validation region hidden): whole bbox + weak labels vs prediction in training windows
with rasterio.open(OUT / "labels_025.tif") as src:
    weak = src.read(1)
img = np.clip(rgb.transpose(1, 2, 0) / 255.0, 0, 1)
colors = ListedColormap(["#00000000", "#e41a1c", "#377eb8", "#ffff0040"])
trains = [q for q in ("NW", "NE", "SE", "SW-N", "SW-S") if q != args.val]
fig, axes = plt.subplots(3, len(trains) + 1, figsize=(5 * (len(trains) + 1), 15), squeeze=False)
show_cls = np.where(val, 3, cls)[::8, ::8]
axes[0, 0].imshow(np.where(val[::8, ::8, None], 0.5, img[::8, ::8]))
axes[0, 0].set_title(f"orthophoto ({args.val} hidden)")
axes[1, 0].imshow(np.where(val[::8, ::8, None], 0.5, img[::8, ::8]))
axes[1, 0].imshow(show_cls, cmap=colors, vmin=0, vmax=3, interpolation="nearest")
axes[1, 0].set_title("U-Net prediction (whole bbox)")
axes[2, 0].axis("off")
for j, q in enumerate(trains, start=1):
    r0, c0, hh, ww = REGIONS[q]
    b = (weak[r0:r0 + hh, c0:c0 + ww] == 1).reshape(hh // DETAIL, DETAIL, ww // DETAIL, DETAIL).sum(axis=(1, 3))
    br, bc = np.unravel_index(np.argmax(b), b.shape)
    r, c = r0 + br * DETAIL, c0 + bc * DETAIL
    axes[0, j].imshow(img[r:r + DETAIL, c:c + DETAIL])
    axes[0, j].set_title(f"{q}: orthophoto (250 m)")
    axes[1, j].imshow(img[r:r + DETAIL, c:c + DETAIL])
    axes[1, j].imshow(np.where(weak[r:r + DETAIL, c:c + DETAIL] == IGNORE, 3, weak[r:r + DETAIL, c:c + DETAIL]),
                      cmap=colors, vmin=0, vmax=3, interpolation="nearest")
    axes[1, j].set_title(f"{q}: weak labels (v3)")
    axes[2, j].imshow(img[r:r + DETAIL, c:c + DETAIL])
    axes[2, j].imshow(cls[r:r + DETAIL, c:c + DETAIL], cmap=colors, vmin=0, vmax=3, interpolation="nearest")
    axes[2, j].set_title(f"{q}: U-Net prediction")
for a in axes.flat:
    a.axis("off")
fig.tight_layout()
fig.savefig(OUT / "predict_preview.png", dpi=70)
print("saved e8/pred_classes_025.tif, e8/sand.tif, e8/ridge.tif, e8/predict_summary.json, e8/predict_preview.png")
