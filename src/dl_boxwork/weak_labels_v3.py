"""E8 weak labels v3 (issue #11): ridges as watersheds between sand-filled troughs.

v1 (brightness top-hat) fired on loose clasts; v2 (Sato alone) fired on bright layer
edges, ledges and rubble. Boxwork ridges differ by CONTEXT, not by local shape: bright
ridges with dark sand on both sides that close into cells of about 10-20 m, with two
roughly orthogonal ridge families (Siebach & Grotzinger 2014; Siebach et al. LPSC 2026).

Pipeline (all at 0.5 m; labels written at 0.25 m on the ortho grid):
  1. sand: grey-blue and darker than the median (works since v1)
  2. watershed of the smoothed luminance flooded from sand troughs -> divide lines
     = candidate polygonal network; Sato at ridge scale (1.5-3 m) must agree
  3. regional boxwork score S (window about 40 m), 0-3:
       + low double-angle orientation coherence R2 (parallel layers give R2 near 1)
       + many compact watershed cells (50-600 m2, aspect < 3)
       + local sand fraction between 15 and 60 %
  4. classes: 1 ridge = network ridges where S >= min-score; 2 trough/sand = sand;
     0 background = non-sand with weak ridge response, or bright structures where S = 0
     (teaches the net that layer edges and rubble are NOT boxwork); 255 = the rest
     plus a 0.5 m band on every class boundary.
Thresholds are percentiles of the TRAINING regions only.

Run from the data/ folder:
  python ../src/dl_boxwork/weak_labels_v3.py --val SW-S [--sigmas-m 1.5 2 3] [--r2-max 0.5] [--min-score 2]
  -> e8/labels_025.tif, e8/weak_labels_summary.json, e8/labels_preview.png, e8/score_preview.png
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
from scipy.ndimage import binary_dilation, binary_erosion, gaussian_filter, label, maximum_filter, minimum_filter
from skimage.feature import hessian_matrix
from skimage.filters import sato
from skimage.measure import regionprops_table
from skimage.segmentation import watershed

BACKGROUND, RIDGE, TROUGH, IGNORE = 0, 1, 2, 255
OUT = Path("e8")
PX = 0.5  # working resolution, m
HALF = 4000  # quadrant side at 0.25 m
QUADRANTS = {"NW": (0, 0), "NE": (0, HALF), "SW": (HALF, 0), "SE": (HALF, HALF)}
REGIONS = {q: (r, c, HALF, HALF) for q, (r, c) in QUADRANTS.items()}
REGIONS |= {"SW-N": (HALF, 0, HALF // 2, HALF), "SW-S": (HALF + HALF // 2, 0, HALF // 2, HALF)}
DETAIL = 1000  # 250 m preview windows at 0.25 m

parser = argparse.ArgumentParser()
parser.add_argument("--val", choices=list(REGIONS), required=True, help="validation region (held out)")
parser.add_argument("--sigmas-m", type=float, nargs="+", default=[1.5, 2.0, 3.0], help="Sato scales in m")
parser.add_argument("--ridge-p", type=float, default=85, help="Sato percentile for a ridge candidate")
parser.add_argument("--bg-p", type=float, default=50, help="Sato percentile below which non-sand is background")
parser.add_argument("--blue-p", type=float, default=90, help="blueness percentile to call sand")
parser.add_argument("--min-sand-m2", type=float, default=10, help="smallest sand trough used as a marker")
parser.add_argument("--window-m", type=float, default=17.5, help="Gaussian sigma of the regional window (m)")
parser.add_argument("--r2-max", type=float, default=0.5, help="orientation coherence below this counts as network")
parser.add_argument("--cell-m2", type=float, nargs=2, default=[50, 600], help="compact cell area range (m2)")
parser.add_argument("--min-score", type=int, default=2, help="regional score (0-3) needed to label ridges")
args = parser.parse_args()
OUT.mkdir(exist_ok=True)

with rasterio.open("base/ortho_color_025.tif") as src:
    rgb = src.read().astype("float32")
    profile = src.profile.copy()
H, W = rgb.shape[1:]
h, w = H // 2, W // 2
rgb05 = rgb.reshape(3, h, 2, w, 2).mean(axis=(2, 4))
L = rgb05.mean(0)
blue = (rgb05[2] - rgb05[0]) / (rgb05.sum(0) + 1.0)


def region_mask(name, shape, scale):
    m = np.zeros(shape, bool)
    r0, c0, hh, ww = (v // scale for v in REGIONS[name])
    m[r0:r0 + hh, c0:c0 + ww] = True
    return m


def training_regions(val):
    if val in ("SW-N", "SW-S"):
        return ["NW", "NE", "SE", "SW-S" if val == "SW-N" else "SW-N"]
    return [q for q in QUADRANTS if q != val]


train = ~region_mask(args.val, (h, w), 2)
grid = np.zeros((h, w), bool)
grid[::5, ::5] = True
sample = train & grid


def pct(a, q):
    return float(np.percentile(a[sample], q))


# 1. sand troughs
sand = (blue >= pct(blue, args.blue_p)) & (L <= pct(L, 50))
lab, _ = label(sand, structure=np.ones((3, 3)))
sizes = np.bincount(lab.ravel())
sand = sand & (sizes[lab] >= args.min_sand_m2 / PX ** 2)
markers, n_markers = label(binary_erosion(sand, iterations=1), structure=np.ones((3, 3)))

# 2. divide lines between troughs + ridge response at ridge scale
Ls = gaussian_filter(L, 1)
cells = watershed(gaussian_filter(L, 2), markers=markers, watershed_line=True)
lines = binary_dilation(cells == 0, iterations=3)  # 1.5 m tolerance
ridge_r = sato(Ls, sigmas=[s / PX for s in args.sigmas_m], black_ridges=False).astype("float32")
cand = ridge_r >= pct(ridge_r, args.ridge_p)
network = cand & lines & ~sand

# 3. regional score
Hrr, Hrc, Hcc = hessian_matrix(Ls, sigma=args.sigmas_m[len(args.sigmas_m) // 2] / PX, order="rc",
                               use_gaussian_derivatives=True)
theta = 0.5 * np.arctan2(2 * Hrc, Hcc - Hrr)
del Hrr, Hrc, Hcc
k = args.window_m / PX
wgt = ridge_r * cand
Wsum = gaussian_filter(wgt, k) + 1e-6
R2 = np.hypot(gaussian_filter(wgt * np.cos(2 * theta), k), gaussian_filter(wgt * np.sin(2 * theta), k)) / Wsum

props = regionprops_table(cells, properties=("label", "area", "axis_major_length", "axis_minor_length"))
area_m2 = props["area"] * PX ** 2
aspect = props["axis_major_length"] / np.maximum(props["axis_minor_length"], 1e-6)
good = (area_m2 >= args.cell_m2[0]) & (area_m2 <= args.cell_m2[1]) & (aspect < 3)
lut = np.zeros(cells.max() + 1, bool)
lut[props["label"][good]] = True
compact_frac = gaussian_filter(lut[cells].astype("float32"), k)
sand_frac = gaussian_filter(sand.astype("float32"), k)

S = ((R2 < args.r2_max).astype("uint8") + (compact_frac > 0.5) + ((sand_frac >= 0.15) & (sand_frac <= 0.6)))

# 4. classes at 0.5 m, then a 0.5 m ignore band on boundaries
lab05 = np.full((h, w), IGNORE, dtype="uint8")
lab05[~sand & ((ridge_r <= pct(ridge_r, args.bg_p)) | ((S == 0) & cand))] = BACKGROUND
lab05[sand] = TROUGH
lab05[network & (S >= args.min_score)] = RIDGE
edge = maximum_filter(lab05, 3) != minimum_filter(lab05, 3)
lab05[edge] = IGNORE
labels = np.repeat(np.repeat(lab05, 2, axis=0), 2, axis=1)

p8 = profile | {"count": 1, "dtype": "uint8", "nodata": IGNORE, "compress": "deflate", "tiled": True,
                "blockxsize": 256, "blockysize": 256, "photometric": "minisblack"}
p8.pop("interleave", None)
with rasterio.open(OUT / "labels_025.tif", "w", **p8) as dst:
    dst.write(labels, 1)


def shares(mask):
    return {n: round(100 * float(np.mean(lab05[mask] == v)), 2)
            for n, v in (("background", BACKGROUND), ("ridge", RIDGE), ("trough", TROUGH), ("ignore", IGNORE))}


boxy = train & (S >= args.min_score)
summary = {
    "version": 3,
    "params": vars(args),
    "thresholds_from": "training regions only",
    "class_pct_train": shares(train),
    "class_pct_per_region": {q: shares(region_mask(q, (h, w), 2)) for q in training_regions(args.val)},
    "boxwork_score_pct_train": {f"S={s}": round(100 * float(np.mean(S[train] == s)), 2) for s in range(4)},
    "ridge_cover_in_boxwork_regions_pct": round(100 * float(np.mean(network[boxy])), 2) if boxy.any() else None,
    "expected_ridge_cover_pct": "20-50 (Siebach & Grotzinger 2014)",
    "compact_cell_area_m2_median": round(float(np.median(area_m2[good])), 1) if good.any() else None,
    "n_sand_troughs": int(n_markers),
}
(OUT / "weak_labels_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))

# Previews (training regions only)
img = np.clip(rgb.transpose(1, 2, 0) / 255.0, 0, 1)
colors = ListedColormap(["#00000000", "#e41a1c", "#377eb8", "#ffff0040"])
shown = np.where(labels == IGNORE, 3, labels)
trains = training_regions(args.val)
ridge25 = labels == RIDGE
fig, axes = plt.subplots(4, len(trains), figsize=(5 * len(trains), 20), squeeze=False)
for j, q in enumerate(trains):
    r0, c0, hh, ww = REGIONS[q]
    blocks = ridge25[r0:r0 + hh, c0:c0 + ww].reshape(hh // DETAIL, DETAIL, ww // DETAIL, DETAIL).sum(axis=(1, 3))
    br, bc = np.unravel_index(np.argmax(blocks), blocks.shape)
    for i, (kind, r, c) in enumerate([("centre", r0 + (hh - DETAIL) // 2, c0 + (ww - DETAIL) // 2),
                                      ("most ridges", r0 + br * DETAIL, c0 + bc * DETAIL)]):
        axes[2 * i, j].imshow(img[r:r + DETAIL, c:c + DETAIL])
        axes[2 * i, j].set_title(f"{q} {kind}: orthophoto (250 m)")
        axes[2 * i + 1, j].imshow(img[r:r + DETAIL, c:c + DETAIL])
        axes[2 * i + 1, j].imshow(shown[r:r + DETAIL, c:c + DETAIL], cmap=colors, vmin=0, vmax=3,
                                  interpolation="nearest")
        axes[2 * i + 1, j].set_title(f"{q} {kind}: red ridge, blue sand, yellow ignore")
for a in axes.flat:
    a.axis("off")
fig.tight_layout()
fig.savefig(OUT / "labels_preview.png", dpi=75)

fig, ax = plt.subplots(1, 2, figsize=(14, 7))
val05 = region_mask(args.val, (h, w), 2)
ax[0].imshow(np.where(val05[..., None], 0.5, img[::2, ::2])[::4, ::4])
ax[0].set_title(f"orthophoto (validation {args.val} greyed out)")
im = ax[1].imshow(np.where(val05, np.nan, S.astype("float32"))[::4, ::4], cmap="viridis", vmin=0, vmax=3)
ax[1].set_title("regional boxwork score S (0-3)")
fig.colorbar(im, ax=ax[1], shrink=0.8)
for a in ax:
    a.axis("off")
fig.tight_layout()
fig.savefig(OUT / "score_preview.png", dpi=90)
print("saved e8/labels_025.tif, e8/weak_labels_summary.json, e8/labels_preview.png, e8/score_preview.png")
