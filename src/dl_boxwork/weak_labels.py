"""E8 weak labels from the 0.25 m HiRISE orthophoto (issue #11).

Why the image and not the DEM: the DEM's effective resolution misses the boxwork
ridges (paper/notes/base_grid.md, fig 4); the orthophoto resolves them.

Classes (0.25 m grid, same as ortho_color_025.tif):
  0 background, 1 ridge, 2 trough/sand, 255 ignore.
- ridge: bright LINEAR structures 0.5-1.5 m wide (Sato ridge filter at 0.5 m), small
  fragments removed. A brightness top-hat alone also fired on loose bright clasts (v1).
- trough/sand: darker than surroundings (black top-hat) or dark grey-blue (sand).
Thresholds are percentiles of the TRAINING quadrants only, so the validation
quadrant never influences the rules.

Regions: quadrants NW, NE, SW, SE (4000 x 4000 px = 1 x 1 km) and the halves of SW,
SW-N and SW-S (2000 x 4000 px = 0.5 x 1 km). The validation region is held out;
everything else is training.

Run from the data/ folder:
  1) choose:  python ../src/dl_boxwork/weak_labels.py
     -> e8/quadrants_overview.png (orthophoto + Curiosity route, no labels)
  2) label:   python ../src/dl_boxwork/weak_labels.py --val SW-S [--ridge-p 92] [--min-ridge-m2 10] ...
     -> e8/labels_025.tif, e8/weak_labels_summary.json, e8/labels_preview.png
        (preview shows TRAINING quadrants only)
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
from scipy.ndimage import gaussian_filter, grey_closing, label
from skimage.filters import sato

BACKGROUND, RIDGE, TROUGH, IGNORE = 0, 1, 2, 255
OUT = Path("e8")
PLACES = Path("03_curiosity/places_pds/data_localizations/localized_interp.csv")
TRAJECTORY = Path("e2/trajectory.gpkg")
HALF = 4000  # px per quadrant side (0.25 m)
QUADRANTS = {"NW": (0, 0), "NE": (0, HALF), "SW": (HALF, 0), "SE": (HALF, HALF)}  # row0, col0
REGIONS = {q: (r, c, HALF, HALF) for q, (r, c) in QUADRANTS.items()}  # row0, col0, height, width
REGIONS |= {"SW-N": (HALF, 0, HALF // 2, HALF), "SW-S": (HALF + HALF // 2, 0, HALF // 2, HALF)}
DETAIL = 1000  # px (250 m) detail windows

parser = argparse.ArgumentParser()
parser.add_argument("--val", choices=list(REGIONS), help="validation region (held out)")
parser.add_argument("--sigmas", type=float, nargs="+", default=[1, 2, 3],
                    help="Sato scales in 0.5 m px (1-3 px = ridges about 0.5-1.5 m wide)")
parser.add_argument("--ridge-p", type=float, default=92, help="Sato response percentile to call ridge")
parser.add_argument("--min-ridge-m2", type=float, default=10, help="drop ridge fragments smaller than this (m2)")
parser.add_argument("--size", type=int, default=25, help="black top-hat window in 0.25 m px (25 px = 6.25 m)")
parser.add_argument("--trough-p", type=float, default=90, help="black top-hat percentile to call trough")
parser.add_argument("--blue-p", type=float, default=90, help="blueness percentile to call sand")
parser.add_argument("--bg-p", type=float, default=50, help="ridge and trough responses below this percentile = background")
args = parser.parse_args()
OUT.mkdir(exist_ok=True)

with rasterio.open("base/ortho_color_025.tif") as src:
    rgb = src.read().astype("float32")
    profile = src.profile.copy()
    T = src.transform
img = np.clip(rgb.transpose(1, 2, 0) / 255.0, 0, 1)
H, W = img.shape[:2]


def region_mask(name, shape=(H, W), scale=1):
    m = np.zeros(shape, bool)
    r0, c0, h, w = (v // scale for v in REGIONS[name])
    m[r0:r0 + h, c0:c0 + w] = True
    return m


def training_regions(val):
    """Disjoint training regions: the three other quadrants, plus the other half of SW."""
    if val in ("SW-N", "SW-S"):
        other = "SW-S" if val == "SW-N" else "SW-N"
        return [q for q in ("NW", "NE", "SE")] + [other]
    return [q for q in QUADRANTS if q != val]


def route_px():
    """Curiosity poses in 0.25 m px: E2's official file if present, else PLACES."""
    if TRAJECTORY.exists():
        import geopandas as gpd
        layers = gpd.list_layers(TRAJECTORY)["name"].tolist()
        layer = next((n for n in layers if "pose" in n.lower()), layers[0])
        g = gpd.read_file(TRAJECTORY, layer=layer)
        pts = g.geometry.get_coordinates()
        x, y = pts.x.to_numpy(), pts.y.to_numpy()
    elif PLACES.exists():
        import pandas as pd
        p = pd.read_csv(PLACES, usecols=["frame", "easting", "northing"])
        p = p[p.frame == "ROVER"]
        x, y = p.easting.to_numpy(), p.northing.to_numpy()
    else:
        return None
    col, row = (x - T.c) / T.a, (y - T.f) / T.e
    keep = (col >= 0) & (col < W) & (row >= 0) & (row < H)
    return col[keep], row[keep]


# ---- step 1: overview to choose the validation quadrant (no labels shown) -----------------
if args.val is None:
    fig, ax = plt.subplots(figsize=(9, 9))
    ax.imshow(img[::8, ::8], extent=(0, W, H, 0))
    route = route_px()
    if route is not None:
        ax.plot(*route, ".", ms=1, color="#00e5ff", label="Curiosity")
        ax.legend(loc="lower left", markerscale=10)
    ax.axhline(HALF, color="white", lw=1.5)
    ax.axvline(HALF, color="white", lw=1.5)
    ax.plot([0, HALF], [HALF * 1.5, HALF * 1.5], color="white", lw=1, ls="--")
    for name, (r0, c0) in QUADRANTS.items():
        ax.text(c0 + 150, r0 + 400, name, color="white", fontsize=22, weight="bold")
    ax.set_title("Choose the validation quadrant (1 x 1 km each)")
    ax.axis("off")
    fig.tight_layout()
    fig.savefig(OUT / "quadrants_overview.png", dpi=110)
    print("saved e8/quadrants_overview.png -> choose --val NW|NE|SW|SE and run again")
    raise SystemExit

# ---- step 2: weak labels, thresholds from training quadrants only -----------------------
train = ~region_mask(args.val)
train05 = ~region_mask(args.val, (H // 2, W // 2), 2)
lum = gaussian_filter(rgb.mean(0), sigma=1.0)
blue = (rgb[2] - rgb[0]) / (rgb.sum(0) + 1.0)  # grey-blue sand vs red-orange rock

# Ridges: Sato filter for bright linear structures, at 0.5 m (2 x 2 block mean)
lum05 = rgb.mean(0).reshape(H // 2, 2, W // 2, 2).mean(axis=(1, 3))
ridge_r = sato(lum05, sigmas=args.sigmas, black_ridges=False).astype("float32")

# Troughs: darker than surroundings, at 0.25 m
black = grey_closing(lum, size=(args.size, args.size)) - lum


def sample(a, mask, step=7):
    s = np.zeros(a.shape, bool)
    s[::step, ::step] = True
    return a[mask & s]


th = {
    "sato_ridge": float(np.percentile(sample(ridge_r, train05), args.ridge_p)),
    "sato_bg": float(np.percentile(sample(ridge_r, train05), args.bg_p)),
    "black_trough": float(np.percentile(sample(black, train), args.trough_p)),
    "black_bg": float(np.percentile(sample(black, train), args.bg_p)),
    "blueness_sand": float(np.percentile(sample(blue, train), args.blue_p)),
    "lum_median": float(np.percentile(sample(lum, train), 50)),
}

min_px = max(1, int(round(args.min_ridge_m2 / 0.25)))  # 0.5 m px are 0.25 m2
candidates = ridge_r >= th["sato_ridge"]
comp, _ = label(candidates, structure=np.ones((3, 3)))  # 8-connected fragments
sizes = np.bincount(comp.ravel())
ridge05 = candidates & (sizes[comp] >= min_px)
ridge = np.repeat(np.repeat(ridge05, 2, axis=0), 2, axis=1)
quiet = np.repeat(np.repeat(ridge_r <= th["sato_bg"], 2, axis=0), 2, axis=1)
sand = (blue >= th["blueness_sand"]) & (lum <= th["lum_median"])

labels = np.full((H, W), IGNORE, dtype="uint8")
labels[quiet & (black <= th["black_bg"]) & ~sand] = BACKGROUND
labels[((black >= th["black_trough"]) & ~ridge) | sand] = TROUGH
labels[ridge & ~sand] = RIDGE

p8 = profile | {"count": 1, "dtype": "uint8", "nodata": IGNORE, "compress": "deflate", "tiled": True,
                "blockxsize": 256, "blockysize": 256, "photometric": "minisblack"}
p8.pop("interleave", None)
with rasterio.open(OUT / "labels_025.tif", "w", **p8) as dst:
    dst.write(labels, 1)


def shares(mask):
    return {name: round(100 * float(np.mean(labels[mask] == v)), 2)
            for name, v in (("background", BACKGROUND), ("ridge", RIDGE), ("trough", TROUGH), ("ignore", IGNORE))}


summary = {
    "version": 2,
    "params": vars(args),
    "thresholds_from": "training quadrants only",
    "thresholds": th,
    "class_pct_train": shares(train),
    "class_pct_per_region": {q: shares(region_mask(q)) for q in training_regions(args.val)},
    "sand_pct_train": round(100 * float(sand[train].mean()), 2),
}
(OUT / "weak_labels_summary.json").write_text(json.dumps(summary, indent=2))
print(json.dumps(summary, indent=2))

# Preview, TRAINING quadrants only: centre window (typical) and densest-ridge window (best case)
colors = ListedColormap(["#00000000", "#e41a1c", "#377eb8", "#ffff0040"])
shown = np.where(labels == IGNORE, 3, labels)
trains = training_regions(args.val)
fig, axes = plt.subplots(4, len(trains), figsize=(5 * len(trains), 20), squeeze=False)
for j, q in enumerate(trains):
    r0, c0, h, w = REGIONS[q]
    blocks = ridge[r0:r0 + h, c0:c0 + w].reshape(h // DETAIL, DETAIL, w // DETAIL, DETAIL).sum(axis=(1, 3))
    br, bc = np.unravel_index(np.argmax(blocks), blocks.shape)
    windows = [("centre", r0 + (h - DETAIL) // 2, c0 + (w - DETAIL) // 2),
               ("most ridges", r0 + br * DETAIL, c0 + bc * DETAIL)]
    for i, (kind, r, c) in enumerate(windows):
        axes[2 * i, j].imshow(img[r:r + DETAIL, c:c + DETAIL])
        axes[2 * i, j].set_title(f"{q} {kind}: orthophoto (250 m)")
        axes[2 * i + 1, j].imshow(img[r:r + DETAIL, c:c + DETAIL])
        axes[2 * i + 1, j].imshow(shown[r:r + DETAIL, c:c + DETAIL], cmap=colors, vmin=0, vmax=3,
                                  interpolation="nearest")
        axes[2 * i + 1, j].set_title(f"{q} {kind}: red ridge, blue trough/sand, yellow ignore")
for a in axes.flat:
    a.axis("off")
fig.tight_layout()
fig.savefig(OUT / "labels_preview.png", dpi=75)
print(f"saved e8/labels_025.tif, e8/weak_labels_summary.json, e8/labels_preview.png (validation {args.val} hidden)")
