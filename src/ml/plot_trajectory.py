"""Quick visual check for E2: the trajectory over the DEM hillshade and over the orthophoto.

It does not replace the QGIS review; it is a fast way to see that the route
falls where it should. Writes data/e2/trajectory_review.png.

Usage:  python src/ml/plot_trajectory.py   (after trajectory_to_grid.py)
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import rasterio
from rasterio.enums import Resampling

import common


def hillshade(z, azimuth=315, altitude=45):
    dy, dx = np.gradient(z)  # 1 m cells
    slope = np.arctan(np.hypot(dx, dy))
    aspect = np.arctan2(-dx, dy)
    az, alt = np.radians(azimuth), np.radians(altitude)
    return np.sin(alt) * np.cos(slope) + np.cos(alt) * np.sin(slope) * np.cos(az - aspect)


def main():
    xmin, ymin, xmax, ymax = common.crop_box()
    with rasterio.open(common.base_layer("dem_1m.tif")) as d:
        z = d.read(1)
    with rasterio.open(common.base_layer("ortho_color_025.tif")) as o:
        rgb = o.read([1, 2, 3], out_shape=(3, 2000, 2000), resampling=Resampling.average)
    rgb = np.moveaxis(rgb, 0, -1)

    poses = json.loads((common.E2_OUTPUT / "trajectory_poses.geojson").read_text(encoding="utf-8"))["features"]
    xy = np.array([f["geometry"]["coordinates"] for f in poses])
    sol = np.array([f["properties"]["sol"] for f in poses])
    # From metres to image coordinates (column, row) on the 1 m grid.
    cx, ry = xy[:, 0] - xmin, ymax - xy[:, 1]

    fig, axes = plt.subplots(1, 2, figsize=(16, 8.4), constrained_layout=True)
    axes[0].imshow(hillshade(z), cmap="gray", extent=(0, 2000, 2000, 0))
    axes[0].set_title("Hillshade of data/base/dem_1m.tif")
    axes[1].imshow(rgb, extent=(0, 2000, 2000, 0))
    axes[1].set_title("data/base/ortho_color_025.tif (downsampled to 1 m)")
    for ax in axes:
        sc = ax.scatter(cx, ry, c=sol, s=1.5, cmap="plasma", lw=0)
        ax.set_xlabel("column")
        ax.set_ylabel("row")
    fig.colorbar(sc, ax=axes, shrink=0.7, label="sol")
    fig.suptitle(f"E2: {len(poses)} PLACES poses inside the crop box, sols {sol.min()}–{sol.max()}")
    out = common.E2_OUTPUT / "trajectory_review.png"
    fig.savefig(out, dpi=110)
    print(out)


if __name__ == "__main__":
    main()
