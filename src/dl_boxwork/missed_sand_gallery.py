"""E8 v1 diagnostic (issue #93): what does the sand that the U-Net misses look like?

Shows 16 m crops of blind points in SW-S that the labeller called sand, split into
  - top: points the U-Net called sand (found sand)
  - bottom: points the U-Net called background or ridge (missed sand)
with p_sand at the centre. If missed sand looks different (dust cover, mixed with gravel,
redder), the fix is new labels of that kind, not a threshold.

Run from the data/ folder:
  python ../src/dl_boxwork/missed_sand_gallery.py [--n 12]  -> e8/missed_sand_gallery.png
"""
import argparse
import csv
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio

OUT, Z = Path("e8"), 32  # 32 px = 8 m half-size at 0.25 m
parser = argparse.ArgumentParser()
parser.add_argument("--points", default="e8/points.csv")
parser.add_argument("--n", type=int, default=12)
parser.add_argument("--seed", type=int, default=3)
args = parser.parse_args()

rows = [r for r in csv.DictReader(open(args.points)) if r["answer"] == "2"]
found = [r for r in rows if r["stratum"] == "2"]
missed = [r for r in rows if r["stratum"] != "2"]
rng = np.random.default_rng(args.seed)
pick = lambda rs: [rs[i] for i in rng.choice(len(rs), min(args.n, len(rs)), replace=False)] if rs else []
found, missed_show = pick(found), pick(missed)

with rasterio.open("base/ortho_color_025.tif") as src:
    img = src.read().transpose(1, 2, 0)
with rasterio.open(OUT / "p_sand_025.tif") as src:
    ps = src.read(1)

n = args.n
fig, axes = plt.subplots(2, n, figsize=(1.9 * n, 4.6), squeeze=False)
for i, (title, rs) in enumerate((("found sand", found), ("MISSED sand", missed_show))):
    for j in range(n):
        a = axes[i, j]
        a.axis("off")
        if j >= len(rs):
            continue
        r, c = int(rs[j]["row"]), int(rs[j]["col"])
        a.imshow(img[r - Z:r + Z, c - Z:c + Z], interpolation="nearest")
        a.plot([Z - 6, Z - 2], [Z, Z], "y-", [Z + 2, Z + 6], [Z, Z], "y-",
               [Z, Z], [Z - 6, Z - 2], "y-", [Z, Z], [Z + 2, Z + 6], "y-", lw=1)
        a.set_title(f"{title}\np={ps[r, c] / 254:.2f} s{rs[j]['stratum']}", fontsize=7)
fig.suptitle(f"Blind points labelled sand in SW-S: {len([r for r in rows if r['stratum'] == '2'])} found, "
             f"{len(missed)} missed (16 m crops)", fontsize=9)
fig.tight_layout()
fig.savefig(OUT / "missed_sand_gallery.png", dpi=130)
pm = [ps[int(r["row"]), int(r["col"])] / 254 for r in missed]
print(f"missed sand points: {len(missed)}; p_sand at them: median {np.median(pm):.3f}, "
      f"max {np.max(pm):.3f}, share > 0.05: {np.mean(np.array(pm) > 0.05):.2f}")
k, v = np.unique([r["stratum"] for r in missed], return_counts=True)
print("by predicted class (0 background, 1 ridge):", {str(a): int(b) for a, b in zip(k, v)})
print("saved e8/missed_sand_gallery.png")
