"""Figures of E2 for the paper (paper/figures/e2_*).

Reads the E2 outputs in data/e2/ and JB's base grid, and writes:
  e2_fig1_trajectory.jpg      route over the hillshade and the orthophoto, coloured by sol
  e2_fig2_slope_distribution.png   slope of visited cells vs the 50 m corridor vs the whole box
  e2_fig3_auc.png             logistic baseline AUC per comparison set (mean and block range)
  e2_fig4_score_map.png       route-likeness score of the main model with the route on top

Usage:  python src/ml/paper_figures.py   (after trajectory_to_grid.py, cell_features.py
        and logistic_baseline.py)
"""
import json

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd
import rasterio
from rasterio.enums import Resampling

import common
from plot_trajectory import hillshade

FIGURES = common.REPO / "paper" / "figures"


def route_rc():
    """Route vertices as (col, row) image coordinates on the 1 m grid."""
    xmin, _, _, ymax = common.crop_box()
    lines = json.loads((common.E2_OUTPUT / "trajectory.geojson").read_text(encoding="utf-8"))["features"]
    return [np.array(f["geometry"]["coordinates"]) - [xmin, 0] for f in lines], ymax


def fig_trajectory():
    xmin, _, _, ymax = common.crop_box()
    with rasterio.open(common.base_layer("dem_1m.tif")) as d:
        z = d.read(1)
    with rasterio.open(common.base_layer("ortho_color_025.tif")) as o:
        rgb = np.moveaxis(o.read([1, 2, 3], out_shape=(3, 1000, 1000), resampling=Resampling.average), 0, -1)
    poses = json.loads((common.E2_OUTPUT / "trajectory_poses.geojson").read_text(encoding="utf-8"))["features"]
    xy = np.array([f["geometry"]["coordinates"] for f in poses])
    sol = np.array([f["properties"]["sol"] for f in poses])
    cx, ry = xy[:, 0] - xmin, ymax - xy[:, 1]

    fig, axes = plt.subplots(1, 2, figsize=(12, 6.2), constrained_layout=True)
    axes[0].imshow(hillshade(z), cmap="gray", extent=(0, 2000, 2000, 0))
    axes[0].set_title("(a) Hillshade of the 1 m DEM")
    axes[1].imshow(rgb, extent=(0, 2000, 2000, 0))
    axes[1].set_title("(b) HiRISE colour orthophoto")
    for ax in axes:
        sc = ax.scatter(cx, ry, c=sol, s=1.2, cmap="plasma", lw=0)
        ax.set_xlabel("column (m)")
        ax.set_ylabel("row (m)")
    fig.colorbar(sc, ax=axes, shrink=0.75, label="sol")
    fig.savefig(FIGURES / "e2_fig1_trajectory.jpg", dpi=110, pil_kwargs={"quality": 88})


def fig_slope_distribution():
    table = pd.read_parquet(common.E2_OUTPUT / "cell_features.parquet")
    with rasterio.open(common.base_layer("slope_deg.tif")) as s:
        box = s.read(1).ravel()
    groups = {
        "visited cells": table.slope_deg[table.visited == 1],
        "not visited, 2–50 m from the route": table.slope_deg[(table.visited == 0) & (table.dist_to_route_m <= 50)],
        "whole box": box[np.isfinite(box)],
    }
    bins = np.arange(0, 61, 1)
    fig, ax = plt.subplots(figsize=(6.5, 4), constrained_layout=True)
    for label, v in groups.items():
        ax.hist(v, bins=bins, density=True, histtype="step", lw=1.6, label=f"{label} (median {np.median(v):.1f}°)")
    ax.set_xlabel("slope at 1 m (degrees)")
    ax.set_ylabel("fraction of cells per degree")
    ax.legend(fontsize=8)
    fig.savefig(FIGURES / "e2_fig2_slope_distribution.png", dpi=130)


def fig_auc():
    report = json.loads((common.E2_OUTPUT / "logistic_baseline.json").read_text(encoding="utf-8"))
    names = list(report["sets"])
    labels = [n.replace("corridor_", "≤ ").replace("m", " m").replace("whole_box", "whole box") for n in names]
    x = np.arange(len(names))
    fig, ax = plt.subplots(figsize=(6.5, 4), constrained_layout=True)
    for i, (model, offset) in enumerate((("all_features", -0.17), ("slope_only", 0.17))):
        mean = np.array([report["sets"][n][model]["auc_mean"] for n in names])
        lo = mean - np.array([report["sets"][n][model]["auc_min"] for n in names])
        hi = np.array([report["sets"][n][model]["auc_max"] for n in names]) - mean
        ax.bar(x + offset, mean, width=0.34, yerr=[lo, hi], capsize=3, label=model.replace("_", " "))
    ax.axhline(0.5, color="k", ls="--", lw=0.8, label="chance")
    ax.set_xticks(x, labels)
    ax.set_xlabel("not visited cells used for comparison")
    ax.set_ylabel("AUC (mean, range over 5 held-out blocks)")
    ax.set_ylim(0.3, 0.9)
    ax.legend(fontsize=8, loc="upper left")
    fig.savefig(FIGURES / "e2_fig3_auc.png", dpi=130)


def fig_score_map():
    with rasterio.open(common.E2_OUTPUT / "visit_probability.tif") as src:
        score = src.read(1, out_shape=(1000, 1000), resampling=Resampling.average)
    lines, ymax = route_rc()
    fig, ax = plt.subplots(figsize=(6.5, 5.6), constrained_layout=True)
    im = ax.imshow(score, cmap="viridis", extent=(0, 2000, 2000, 0))
    for line in lines:
        ax.plot(line[:, 0], ymax - line[:, 1], color="red", lw=1)
    fig.colorbar(im, ax=ax, shrink=0.8, label="route-likeness score (relative)")
    ax.set_xlabel("column (m)")
    ax.set_ylabel("row (m)")
    fig.savefig(FIGURES / "e2_fig4_score_map.png", dpi=130)


def main():
    FIGURES.mkdir(parents=True, exist_ok=True)
    for make in (fig_trajectory, fig_slope_distribution, fig_auc, fig_score_map):
        make()
    for f in sorted(FIGURES.glob("e2_*")):
        print(f"{f.relative_to(common.REPO).as_posix()}  {f.stat().st_size // 1024} KB")


if __name__ == "__main__":
    main()
