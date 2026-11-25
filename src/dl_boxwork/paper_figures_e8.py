"""Paper figures for E8 (issue #11, paper/notes/E8_boxwork_sand.md).

Run from the data/ folder after train_unet.py, predict_unet.py, point_labels.py score and
eval_with_rover.py:
  python ../src/dl_boxwork/paper_figures_e8.py
  -> ../paper/figures/e8_fig1_training.png ... e8_fig4_rover_auc.png, e8/paper_numbers.json
"""
import csv
import json
import math
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from matplotlib.patches import Rectangle

FIG, E8 = Path("../paper/figures"), Path("e8")
FIG.mkdir(parents=True, exist_ok=True)
NAMES = {0: "background", 1: "ridge", 2: "sand/trough"}


def wilson(k, n, z=1.96):
    if n == 0:
        return (np.nan, np.nan, np.nan)
    p = k / n
    d = 1 + z * z / n
    m = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (p, m - h, m + h)


def users_accuracy(path):
    rows = [r for r in csv.DictReader(open(path)) if r["answer"] not in ("", "-1")]
    out = {}
    for c in (0, 1, 2):
        sub = [r for r in rows if int(r["stratum"]) == c]
        out[c] = wilson(sum(int(r["answer"]) == c for r in sub), len(sub))
    return out


# --- fig 1: training curve -------------------------------------------------------------
log = json.loads((E8 / "train_log.json").read_text())
ep = [r["epoch"] for r in log["log"]]
fig, ax = plt.subplots(1, 2, figsize=(11, 3.8))
ax[0].plot(ep, [r["loss"] for r in log["log"]], "k-o", ms=3)
ax[0].set_title("training loss (CE + Dice)")
for key, col in (("background", "#999999"), ("ridge", "#e41a1c"), ("trough", "#377eb8")):
    ax[1].plot(ep, [r["val_iou_weak"][key] for r in log["log"]], "-o", ms=3, color=col, label=key)
ax[1].axvline(log["best_epoch"], color="k", ls="--", lw=1)
ax[1].set_title("IoU vs WEAK labels in the held-out region")
ax[1].legend(fontsize=8)
for a in ax:
    a.set_xlabel("epoch")
fig.tight_layout()
fig.savefig(FIG / "e8_fig1_training.png", dpi=200)

# --- fig 2: predicted sand over the bbox, held-out region and Curiosity -------------------
with rasterio.open("base/ortho_color_025.tif") as src:
    img = src.read(out_shape=(3, 2000, 2000)).transpose(1, 2, 0)
with rasterio.open(E8 / "sand.tif") as src:
    sand, T = src.read(1), src.transform
p = pd.read_csv("03_curiosity/places_pds/data_localizations/localized_interp.csv",
                usecols=["frame", "easting", "northing"])
p = p[p.frame == "ROVER"]
col, row = (p.easting - T.c) / T.a, (p.northing - T.f) / T.e
ok = (col >= 0) & (col < 2000) & (row >= 0) & (row < 2000)
fig, ax = plt.subplots(figsize=(7.5, 7.5))
ax.imshow(img)
ax.imshow(np.ma.masked_less_equal(sand, 0), cmap="Blues", vmin=0, vmax=1, alpha=0.75)
ax.plot(col[ok], row[ok], ".", ms=0.5, color="#ffd400", label="Curiosity (PLACES)")
ax.add_patch(Rectangle((0, 1500), 1000, 500, fill=False, ec="white", lw=1.5, ls="--",
                       label="held-out validation region (SW-S)"))
ax.set_title("E8 sand fraction per 1 m cell (blue), 2 x 2 km bbox")
ax.legend(loc="upper right", fontsize=8, markerscale=15)
ax.axis("off")
fig.tight_layout()
fig.savefig(FIG / "e8_fig2_sand_map.png", dpi=200)

# --- fig 3: blind point validation, both labelling passes -------------------------------
passes = {"pass 1": users_accuracy(E8 / "points_pass1.csv"), "pass 2 (strict sand)": users_accuracy(E8 / "points.csv")}
fig, ax = plt.subplots(figsize=(7, 4))
xs = np.arange(3)
for k, (name, ua) in enumerate(passes.items()):
    v = np.array([ua[c] for c in (2, 1, 0)])
    ax.errorbar(xs + (k - 0.5) * 0.18, v[:, 0], yerr=[v[:, 0] - v[:, 1], v[:, 2] - v[:, 0]],
                fmt="o", capsize=4, label=name)
ax.set_xticks(xs, ["sand/trough", "ridge", "background"])
ax.set_ylim(0, 1)
ax.set_ylabel("user's accuracy (95 % Wilson CI)")
ax.set_title("When the U-Net predicts a class, how often is it right? (80 points per class)")
ax.legend(fontsize=8)
fig.tight_layout()
fig.savefig(FIG / "e8_fig3_point_validation.png", dpi=200)

# --- fig 4: rover-route AUC per block (boxwork sols) --------------------------------------
rv = json.loads((E8 / "rover_eval.json").read_text())["boxwork_sols_only"]
layers = ["sand (E8)", "ridge (E8)", "slope_deg (DEM)", "roughness (DEM)"]
fig, ax = plt.subplots(figsize=(7, 4))
for i, name in enumerate(layers):
    blocks = [b for b in rv[name]["per_block"] if b is not None]
    ax.scatter([i] * len(blocks), blocks, color="#636363", s=18, zorder=3)
    ax.bar(i, rv[name]["auc_avoid_mean"] - 0.5, bottom=0.5, color="#377eb8" if "sand" in name else "#bdbdbd")
ax.axhline(0.5, color="k", lw=1)
ax.set_xticks(range(len(layers)), layers, fontsize=8)
ax.set_ylim(0.4, 0.6)
ax.set_ylabel("AUC_avoid (dots = route blocks)")
ax.set_title("Does a layer explain where Curiosity drove? (boxwork sols)")
fig.tight_layout()
fig.savefig(FIG / "e8_fig4_rover_auc.png", dpi=200)

numbers = {name: {NAMES[c]: [round(x, 3) for x in ua[c]] for c in ua} for name, ua in passes.items()}
(E8 / "paper_numbers.json").write_text(json.dumps({"users_accuracy_value_lo_hi": numbers}, indent=2))
print(json.dumps(numbers, indent=2))
print("saved paper/figures/e8_fig1_training.png ... e8_fig4_rover_auc.png")
