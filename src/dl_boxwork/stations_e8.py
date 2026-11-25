"""E8 science stations for E5 (issue #11): sand-rock contacts in the boxwork.

The ridge layer is not reliable (paper note E8), so stations are placed where the reliable
sand layer meets rock: for every sand patch the size of a boxwork hollow (15-600 m2;
larger connected sand is a sand sheet), the station is the
most raised rock cell (highest TPI, the DEM keeps a ~10 cm signal of the walls) in a 5 m
ring around it. Score grows with patch size and with the local density of hollows (more
boxwork around). Greedy selection keeps stations at least --spacing-m apart.

Output follows E5's loader (src/orienteering/data_io.py, branch 9-e5-orienteering):
GeoPackage, CRS of the DEM, layer "stations", columns id, type, score, service_time_min
(+ source and diagnostics). type = "contact".

Run from the data/ folder:
  python ../src/dl_boxwork/stations_e8.py [--n 15] [--spacing-m 50] [--service-min 20]
  -> stations/stations_e8.gpkg, e8/stations_e8_preview.png
"""
import argparse
from pathlib import Path

import geopandas as gpd
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from scipy.ndimage import binary_dilation, find_objects, gaussian_filter, label

parser = argparse.ArgumentParser()
parser.add_argument("--n", type=int, default=15, help="max number of stations (E5 DP cut is N = 15)")
parser.add_argument("--spacing-m", type=float, default=50, help="minimum distance between stations")
parser.add_argument("--sand-min", type=float, default=0.25, help="cell is sand if sand.tif >= this")
parser.add_argument("--min-patch-m2", type=float, default=15, help="smallest sand patch that counts as a hollow")
parser.add_argument("--max-patch-m2", type=float, default=600,
                    help="larger connected sand is a sand sheet or dune field, not a boxwork hollow (cells 10-25 m)")
parser.add_argument("--ring-m", type=int, default=5, help="search ring around each patch (m)")
parser.add_argument("--edge-m", type=int, default=30, help="keep stations this far from the bbox edge")
parser.add_argument("--service-min", type=float, default=20, help="service time per station (min)")
parser.add_argument("--score-max", type=float, default=5, help="scores are scaled to 1..score-max")
args = parser.parse_args()

with rasterio.open("e8/sand.tif") as src:
    sand = src.read(1)
    T, crs, H, W = src.transform, src.crs, src.height, src.width
with rasterio.open("base/tpi.tif") as src:
    tpi = src.read(1).astype("float32")
    if src.nodata is not None:
        tpi[tpi == src.nodata] = np.nan

is_sand = sand >= args.sand_min
any_sand = sand > 0
lab, n = label(is_sand)  # 4-connected, so hollows touching at a corner stay separate
areas = np.bincount(lab.ravel())  # m2 (1 m cells)
density = gaussian_filter(is_sand.astype("float32"), 25)  # local share of hollows (~50 m window)
dens_n = density / max(float(density.max()), 1e-6)

edge = args.edge_m
boxes = find_objects(lab)
cands = []
for k in np.nonzero((areas >= args.min_patch_m2) & (areas <= args.max_patch_m2))[0]:
    if k == 0:
        continue
    sr, sc = boxes[k - 1]
    r0, r1 = max(sr.start - args.ring_m, 0), min(sr.stop + args.ring_m, H)
    c0, c1 = max(sc.start - args.ring_m, 0), min(sc.stop + args.ring_m, W)
    patch = lab[r0:r1, c0:c1] == k
    sub = tpi[r0:r1, c0:c1]
    ring = binary_dilation(patch, iterations=args.ring_m) & ~any_sand[r0:r1, c0:c1] & np.isfinite(sub)
    if not ring.any():
        continue
    t = np.where(ring, sub, -np.inf)
    i, j = np.unravel_index(np.argmax(t), t.shape)
    r, c = r0 + i, c0 + j
    if r < edge or c < edge or r >= H - edge or c >= W - edge:
        continue
    value = np.log1p(areas[k]) * (0.5 + dens_n[r, c])
    cands.append((value, r, c, int(areas[k]), float(tpi[r, c]), float(density[r, c])))

cands.sort(reverse=True)
chosen = []
for cand in cands:
    if all(np.hypot(cand[1] - o[1], cand[2] - o[2]) >= args.spacing_m for o in chosen):
        chosen.append(cand)
    if len(chosen) == args.n:
        break
if not chosen:
    raise SystemExit("no stations found: lower --sand-min or --min-patch-m2")

v = np.array([s[0] for s in chosen])
score = 1 + (args.score_max - 1) * (v - v.min()) / max(v.max() - v.min(), 1e-9)
xs = [T.c + (s[2] + 0.5) * T.a for s in chosen]
ys = [T.f + (s[1] + 0.5) * T.e for s in chosen]
gdf = gpd.GeoDataFrame({
    "id": [f"E8-{i + 1:02d}" for i in range(len(chosen))],
    "type": "contact",
    "score": np.round(score, 2),
    "service_time_min": args.service_min,
    "source": "E8",
    "sand_patch_m2": [s[3] for s in chosen],
    "tpi_m": [round(s[4], 3) for s in chosen],
    "local_hollow_share": [round(s[5], 3) for s in chosen],
    "row": [s[1] for s in chosen], "col": [s[2] for s in chosen],
}, geometry=gpd.points_from_xy(xs, ys), crs=crs.to_wkt())
Path("stations").mkdir(exist_ok=True)
gdf.to_file("stations/stations_e8.gpkg", layer="stations", driver="GPKG")
print(gdf.drop(columns="geometry").to_string(index=False))
print(f"{len(cands)} candidate patches, {len(gdf)} stations -> stations/stations_e8.gpkg (layer 'stations')")

# Preview over the orthophoto
with rasterio.open("base/ortho_color_025.tif") as src:
    img = src.read(out_shape=(3, H, W)).transpose(1, 2, 0)
fig, ax = plt.subplots(figsize=(9, 9))
ax.imshow(img)
ax.imshow(np.ma.masked_less(sand, args.sand_min), cmap="Blues", vmin=0, vmax=1, alpha=0.6)
for s, name in zip(chosen, gdf["id"]):
    ax.plot(s[2], s[1], "o", ms=9, mfc="yellow", mec="black")
    ax.text(s[2] + 15, s[1], name, color="yellow", fontsize=8, weight="bold")
ax.set_title("E8 stations: sand-rock contacts (blue = sand >= %.2f)" % args.sand_min)
ax.axis("off")
fig.tight_layout()
fig.savefig("e8/stations_e8_preview.png", dpi=90)
print("saved e8/stations_e8_preview.png")
