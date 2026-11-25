"""E9 figures and numbers for the paper (paper/notes/E9_boulders.md).

Reads data/e9/ (teacher.py and distill.py outputs) and writes
  data/e9/summary.json
  paper/figures/e9_fig1_teacher.png    teacher detections on a zoom + cover over the box
  paper/figures/e9_fig2_student.png    teacher vs student cover (10 m) on validation blocks

Runs in any env with rasterio, geopandas and matplotlib (the API env is fine).
"""

import json
import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")   # torch + SciPy OpenMP (as in E1)

import geopandas as gpd
import matplotlib
import numpy as np
import rasterio
from rasterio.windows import Window, bounds

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from dl_rocas.distill import BLOCK_PX, UP, block_mean, val_blocks  # noqa: E402

E9 = REPO / "data" / "e9"
ORTHO = REPO / "data" / "base" / "ortho_gray_025.tif"
FIG = REPO / "paper" / "figures"
ZOOM = Window(250, 250, 500, 500)          # 125 m, NW corner: scarp with debris


def load(name):
    return json.loads((E9 / name).read_text(encoding="utf-8"))


def read(path):
    with rasterio.open(path) as src:
        return src.read(1), src.bounds


def fig1(gdf):
    with rasterio.open(ORTHO) as src:
        im = src.read(1, window=ZOOM)
        b = bounds(ZOOM, src.transform)
    cover, bb = read(E9 / "teacher_cover_1m.tif")
    c10 = block_mean(np.nan_to_num(cover), 10) * 100
    fig, ax = plt.subplots(1, 2, figsize=(12, 5.6))
    ext = (b[0], b[2], b[1], b[3])
    ax[0].imshow(im, cmap="gray", extent=ext)
    sel = gdf.cx[b[0]:b[2], b[1]:b[3]]
    sel.boundary.plot(ax=ax[0], color="#e4572e", lw=0.7)
    ax[0].set_xlim(b[0], b[2])
    ax[0].set_ylim(b[1], b[3])
    ax[0].set_title(f"(a) BoulderNet detections, 125 m zoom ({len(sel)} boulders)")
    ax[0].set_xticks([])
    ax[0].set_yticks([])
    ax[0].set_xlabel("")
    ax[0].set_ylabel("")
    h = ax[1].imshow(c10, cmap="magma", extent=(bb.left, bb.right, bb.bottom, bb.top),
                     vmin=0, vmax=np.nanpercentile(c10, 99.5))
    ax[1].add_patch(plt.Rectangle((b[0], b[1]), b[2] - b[0], b[3] - b[1], fill=False,
                                  ec="cyan", lw=1.2))
    ax[1].set_title("(b) Teacher rock cover, 10 m windows (%)")
    ax[1].set_xticks([])
    ax[1].set_yticks([])
    fig.colorbar(h, ax=ax[1], shrink=0.85, label="% of ground covered by boulders")
    fig.tight_layout()
    out = FIG / "e9_fig1_teacher.png"
    fig.savefig(out, dpi=150)
    plt.close(fig)
    return out


def fig2():
    t, bb = read(E9 / "teacher_cover_1m.tif")
    s, _ = read(E9 / "rocas.tif")
    nb = t.shape[0] * UP // BLOCK_PX
    cell_block = BLOCK_PX // UP
    val = np.zeros(t.shape, bool)
    for by, bx in val_blocks(nb):
        val[by * cell_block:(by + 1) * cell_block, bx * cell_block:(bx + 1) * cell_block] = True
    t10 = block_mean(np.where(np.isnan(t), np.nan, t), 10) * 100
    s10 = block_mean(np.where(np.isnan(s), np.nan, s), 10) * 100
    v10 = block_mean(val.astype(float), 10) == 1
    ext = (bb.left, bb.right, bb.bottom, bb.top)
    vmax = np.nanpercentile(t10, 99.5)
    fig, ax = plt.subplots(1, 3, figsize=(16, 5.2))
    for a, arr, title in ((ax[0], t10, "(a) Teacher (BoulderNet)"),
                          (ax[1], s10, "(b) Student (rocas.tif)")):
        h = a.imshow(arr, cmap="magma", extent=ext, vmin=0, vmax=vmax)
        a.set_title(title)
        a.set_xticks([])
        a.set_yticks([])
    # outline the validation blocks
    for by, bx in val_blocks(nb):
        x0 = bb.left + bx * BLOCK_PX * 0.25
        y1 = bb.top - by * BLOCK_PX * 0.25
        for a in ax[:2]:
            a.add_patch(plt.Rectangle((x0, y1 - 250), 250, 250, fill=False, ec="cyan", lw=0.8))
    fig.colorbar(h, ax=ax[:2], shrink=0.85, label="boulder cover, 10 m windows (%)")
    k = v10 & ~np.isnan(t10) & ~np.isnan(s10)
    ax[2].scatter(t10[k], s10[k], s=2, alpha=0.3, color="#4062bb")
    m = max(np.nanmax(t10[k]), np.nanmax(s10[k]))
    ax[2].plot([0, m], [0, m], color="gray", lw=0.8)
    r = np.corrcoef(t10[k], s10[k])[0, 1]
    ax[2].set_xlabel("teacher cover (%)")
    ax[2].set_ylabel("student cover (%)")
    ax[2].set_title(f"(c) Validation blocks (cyan), r = {r:.2f}, n = {k.sum()}")
    ax[2].set_aspect("equal")
    out = FIG / "e9_fig2_student.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def fig3():
    """X1 (#102): teacher cover at 20 m, GP mean, GP std (both on the base grid)."""
    t, bb = read(E9 / "teacher_cover_1m.tif")
    m, _ = read(E9 / "rocks_mean.tif")
    sd, _ = read(E9 / "rocks_std.tif")
    t20 = block_mean(np.where(np.isnan(t), np.nan, t), 20) * 100
    ext = (bb.left, bb.right, bb.bottom, bb.top)
    gp = load("rocks_gp.json")
    fig, ax = plt.subplots(1, 3, figsize=(17, 5.4))
    vmax = np.nanpercentile(t20, 99)
    panels = ((ax[0], t20, "(a) Teacher cover, 20 m blocks (%)", "magma", vmax),
              (ax[1], m * 100, "(b) GP mean, rocks_mean.tif (%)", "magma", vmax),
              (ax[2], sd * 100, "(c) GP std, rocks_std.tif (%)", "viridis",
               np.nanpercentile(sd * 100, 99.5)))
    for a, arr, title, cmap, vm in panels:
        h = a.imshow(arr, cmap=cmap, extent=ext, vmin=0, vmax=vm)
        a.set_title(title)
        a.set_xticks([])
        a.set_yticks([])
        fig.colorbar(h, ax=a, shrink=0.8)
    ls = gp["final"]["length_scale_m"]
    fig.suptitle(f"Matern length scale {ls:.0f} m; spatial CV (400 m tiles): IC90 coverage "
                 f"{gp['cv']['gp_teacher_sqrt']['coverage_90']:.2f}", y=0.98)
    out = FIG / "e9_fig3_gp.png"
    fig.savefig(out, dpi=150, bbox_inches="tight")
    plt.close(fig)
    return out


def main():
    FIG.mkdir(parents=True, exist_ok=True)
    gdf = gpd.read_file(E9 / "boulders_teacher.gpkg")
    teacher = load("boulders_teacher.json")
    check = load("teacher_check_mars.json")
    student = load("student_metrics.json")
    rocas = load("rocas.json")
    area_km2 = 4.0
    summary = dict(
        teacher=dict(boulders_score_ge_0_1=len(gdf),
                     boulders_score_ge_0_5=int((gdf.score >= 0.5).sum()),
                     per_km2_score_ge_0_5=float((gdf.score >= 0.5).sum() / area_km2),
                     diameter_m_median=float(gdf.diameter_m.median()),
                     diameter_m_p95=float(gdf.diameter_m.quantile(0.95)),
                     params=check["params"],
                     seconds_whole_box=teacher["seconds"], tiles=teacher["tiles"],
                     check_mars=check["splits"], check_score_thresh=check["score_thresh"]),
        student=dict(params=student["params"], best_val_loss=student["best_val_loss"],
                     train_seconds=student["train_seconds"],
                     cover_val=student["cover_val"], cover_train=student["cover_train"],
                     seconds_whole_box=rocas["seconds_whole_box"],
                     mean_cover=rocas["mean_cover"]),
        speedup_whole_box=teacher["seconds"] / rocas["seconds_whole_box"],
        params_ratio=check["params"] / student["params"],
        figures=[str(fig1(gdf).relative_to(REPO)), str(fig2().relative_to(REPO))],
    )
    if (E9 / "rocks_gp.json").exists():                      # X1 (#102)
        summary["figures"].append(str(fig3().relative_to(REPO)))
    (E9 / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    print(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
