"""X1 (#102): boulder cover with uncertainty. A Gaussian process on 20 m blocks of
E9's boulder cover gives a smoothed mean (rocks_mean.tif) and its standard
deviation (rocks_std.tif) on the base grid.

    python src/dl_rocas/rocks_gp.py          -> data/e9/rocks_mean.tif, rocks_std.tif,
                                                data/e9/rocks_gp.json

Input: the teacher's cover (data/e9/teacher_cover_1m.tif, BoulderNet), the original
signal. The same GP on the student's cover (rocas.tif) is run as a comparison: does
"cheap student + GP" recover the teacher's map?

Model
- Blocks: mean cover of each 20 x 20 m block (100 x 100 blocks). 65 % of the blocks
  have no boulder at all and the values are very skewed, so the GP works on
  z = sqrt(cover %) (skew 8.1 -> 2.9). Back to cover: if z ~ N(mu, s^2), then
  E[z^2] = mu^2 + s^2 and Var[z^2] = 4 mu^2 s^2 + 2 s^4; interval bounds are squared
  (a lower bound below 0 becomes 0). A GP on the raw cover is run for comparison.
- Kernel: C * Matern(nu = 1.5) + White, scikit-learn [sklearn], normalize_y. The
  hyperparameters are fitted on ~2000 training blocks taken from random 320 m
  windows of contiguous blocks (exact GP cost grows with n^3; windows keep the
  20 m neighbours that a scattered subsample would lose), then the GP is refitted
  with them fixed on all training blocks (exact, ~8000 points).
- The std published and validated is the PREDICTIVE one: the spread of the cover
  the teacher would measure in that block, noise included.

Validation (spatial CV)
- The box is cut in 5 x 5 tiles of 400 m; the 25 tiles go to 5 folds at random
  (seed 102), 5 tiles per fold. Each fold is predicted from the other four.
- Rivals: the training mean (no spatial information) and a Gaussian smoothing of
  the training blocks (normalised convolution, sigma 0.5-3 blocks). The best
  smoothing sigma is chosen on the test folds themselves, which favours the rival.
- Metrics on held-out blocks, in cover %: RMSE, MAE, and for the GP the coverage
  of its 90 % intervals (calibrated if close to 90 %) and their mean width.
"""

import argparse
import json
import sys
import time
import warnings
from pathlib import Path

import numpy as np
import rasterio
from scipy import ndimage
from sklearn.gaussian_process import GaussianProcessRegressor
from sklearn.gaussian_process.kernels import ConstantKernel, Matern, WhiteKernel

REPO = Path(__file__).resolve().parents[2]
E9 = REPO / "data" / "e9"
BLOCK = 20                      # m (= cells of 1 m)
TILE_BLOCKS = 20                # 400 m CV tiles
N_FOLDS = 5
SEED = 102
N_SUB = 2000
Z90 = 1.6448536269514722
SIGMAS = (1.0, 2.0, 3.0, 5.0, 10.0)


# ---------------------------------------------------------------- data

def read(path):
    with rasterio.open(path) as src:
        return src.read(1).astype(np.float64), src.profile.copy()


def block_means(a, b=BLOCK):
    """(H/b, W/b) mean of each block, ignoring NaN; NaN if the block is empty."""
    h, w = a.shape[0] // b, a.shape[1] // b
    v = a[:h * b, :w * b].reshape(h, b, w, b)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", RuntimeWarning)       # empty blocks -> NaN
        return np.nanmean(v, axis=(1, 3))


def block_xy(shape, b=BLOCK):
    """Block centres in metres from the box's NW corner (x east, y south)."""
    r, c = np.mgrid[0:shape[0], 0:shape[1]]
    return np.column_stack([(c.ravel() + 0.5) * b, (r.ravel() + 0.5) * b]).astype(float)


def random_folds(shape, seed=SEED):
    """Fold id of each block at random: held-out blocks have data all around them,
    so this measures interpolation (what the final map does), not extrapolation."""
    rng = np.random.default_rng(seed + 1)
    return rng.permutation(np.arange(shape[0] * shape[1]) % N_FOLDS).reshape(shape)


def folds(shape, seed=SEED):
    """Fold id (0-4) of each block: 400 m tiles assigned at random, 5 per fold."""
    nt = shape[0] // TILE_BLOCKS
    rng = np.random.default_rng(seed)
    tile_fold = rng.permutation(np.arange(nt * nt) % N_FOLDS).reshape(nt, nt)
    r, c = np.mgrid[0:shape[0], 0:shape[1]]
    return tile_fold[r // TILE_BLOCKS, c // TILE_BLOCKS]


# ---------------------------------------------------------------- transforms

def forward(cover_pct, transform):
    return np.sqrt(cover_pct) if transform == "sqrt" else cover_pct


def back(mu, sd, transform):
    """Mean, std and 90 % interval of the cover (%) from N(mu, sd^2) in GP space."""
    lo, hi = mu - Z90 * sd, mu + Z90 * sd
    if transform != "sqrt":
        return mu, sd, np.maximum(lo, 0.0), hi
    mean = mu ** 2 + sd ** 2
    std = np.sqrt(4 * mu ** 2 * sd ** 2 + 2 * sd ** 4)
    lo_c = np.where(lo > 0, lo ** 2, 0.0)
    hi_c = np.maximum(lo ** 2, hi ** 2)
    hi_c = np.where(lo > 0, hi ** 2, hi_c)
    return mean, std, lo_c, hi_c


# ---------------------------------------------------------------- models

def kernel():
    return (ConstantKernel(1.0, (1e-3, 1e2))
            * Matern(length_scale=60.0, length_scale_bounds=(5.0, 2000.0), nu=1.5)
            + WhiteKernel(0.5, (1e-4, 10.0)))


def window_subsample(X, n, seed=SEED, window_m=16 * BLOCK):
    """About n points taken from random square windows of contiguous blocks. A plain
    random subsample would space the points ~45 m apart and hide the short-range
    correlation from the hyperparameter fit; windows keep the neighbours."""
    rng = np.random.default_rng(seed)
    chosen = np.zeros(len(X), bool)
    for _ in range(200):
        if chosen.sum() >= n:
            break
        cx, cy = X[rng.integers(len(X))]
        chosen |= (np.abs(X[:, 0] - cx) < window_m / 2) & (np.abs(X[:, 1] - cy) < window_m / 2)
    idx = np.flatnonzero(chosen)
    return idx if len(idx) <= n else rng.choice(idx, n, replace=False)


def fit_gp(X, y, seed=SEED):
    """Hyperparameters on a windowed subsample, then an exact refit on all points."""
    sub = window_subsample(X, min(N_SUB, len(y)), seed)
    gp0 = GaussianProcessRegressor(kernel(), normalize_y=True, n_restarts_optimizer=2,
                                   random_state=seed).fit(X[sub], y[sub])
    gp = GaussianProcessRegressor(gp0.kernel_, normalize_y=True, optimizer=None).fit(X, y)
    return gp


def gp_params(gp):
    k = gp.kernel_
    return dict(amplitude=float(k.k1.k1.constant_value),
                length_scale_m=float(k.k1.k2.length_scale),
                noise=float(k.k2.noise_level), kernel=str(k))


def smooth_predict(values, train_mask, sigma):
    """Normalised Gaussian convolution of the training blocks. Where the filter
    does not reach any training block (inside a large held-out tile), it falls
    back to the training mean, as the GP does far from data."""
    v = np.where(train_mask, values, 0.0)
    num = ndimage.gaussian_filter(v, sigma, mode="nearest")
    den = ndimage.gaussian_filter(train_mask.astype(float), sigma, mode="nearest")
    fallback = values[train_mask].mean()
    with np.errstate(invalid="ignore", divide="ignore"):
        out = num / den
    return np.where(den > 1e-6, out, fallback)


def scores(pred, truth):
    e = pred - truth
    return dict(rmse=float(np.sqrt(np.mean(e ** 2))), mae=float(np.mean(np.abs(e))),
                bias=float(np.mean(e)))


# ---------------------------------------------------------------- CV

def group_masks(valid_share, edge_blocks=2):
    """Blocks on the box edge (outer 2 blocks = 40 m) and blocks touching orthophoto
    nodata (a block with a NaN cell, or next to one): where interpolation has data
    on one side only (#120, C5)."""
    edge = np.zeros(valid_share.shape, bool)
    edge[:edge_blocks], edge[-edge_blocks:] = True, True
    edge[:, :edge_blocks], edge[:, -edge_blocks:] = True, True
    hole = ndimage.binary_dilation(valid_share < 1.0, iterations=1)
    return {"edge": edge, "near_nodata": hole, "interior": ~edge & ~hole}


def by_group(pred, truth, ok, groups, lo=None, hi=None):
    out = {}
    for name, g in (groups or {}).items():
        m = ok & g.ravel()
        if not m.any():
            continue
        out[name] = dict(blocks=int(m.sum()), **scores(pred[m], truth[m]))
        if lo is not None:
            out[name]["coverage_90"] = float(((truth[m] >= lo[m]) & (truth[m] <= hi[m])).mean())
    return out


def cross_validate(source_pct, truth_pct, fold, transform, groups=None):
    """GP on `source` blocks, scored against `truth` blocks on each held-out fold."""
    X = block_xy(source_pct.shape)
    src, tru, f = source_pct.ravel(), truth_pct.ravel(), fold.ravel()
    ok = np.isfinite(src) & np.isfinite(tru)
    preds = np.full(src.shape, np.nan)
    lo = np.full(src.shape, np.nan)
    hi = np.full(src.shape, np.nan)
    params = []
    for k in range(N_FOLDS):
        tr, te = ok & (f != k), ok & (f == k)
        gp = fit_gp(X[tr], forward(src[tr], transform))
        mu, sd = gp.predict(X[te], return_std=True)
        m, _, l, h = back(mu, sd, transform)
        preds[te], lo[te], hi[te] = m, l, h
        params.append(gp_params(gp))
    t = tru[ok]
    inside = (t >= lo[ok]) & (t <= hi[ok])
    out = scores(preds[ok], t)
    out.update(coverage_90=float(inside.mean()), interval_width_mean=float(np.mean(hi[ok] - lo[ok])),
               coverage_90_where_truth_zero=float(inside[t == 0].mean()),
               coverage_90_where_truth_positive=float(inside[t > 0].mean()),
               by_group=by_group(preds, tru, ok, groups, lo, hi),
               per_fold_params=params)
    return out


def cv_baselines(source_pct, truth_pct, fold, groups=None):
    src, tru, f = source_pct, truth_pct, fold
    ok = np.isfinite(src) & np.isfinite(tru)
    res = {}
    mean_pred = np.full(src.shape, np.nan)
    smooth = {s: np.full(src.shape, np.nan) for s in SIGMAS}
    for k in range(N_FOLDS):
        tr, te = ok & (f != k), ok & (f == k)
        mean_pred[te] = src[tr].mean()
        for s in SIGMAS:
            smooth[s][te] = smooth_predict(np.nan_to_num(src), tr, s)[te]
    res["training_mean"] = scores(mean_pred[ok], tru[ok])
    res["smoothing"] = {str(s): scores(smooth[s][ok], tru[ok]) for s in SIGMAS}
    best = min(SIGMAS, key=lambda s: res["smoothing"][str(s)]["rmse"])
    res["smoothing_best_sigma_blocks"] = best
    res["smoothing_best"] = res["smoothing"][str(best)]
    res["smoothing_best_by_group"] = by_group(smooth[best].ravel(), tru.ravel(), ok.ravel(), groups)
    res["training_mean_by_group"] = by_group(mean_pred.ravel(), tru.ravel(), ok.ravel(), groups)
    return res


# ---------------------------------------------------------------- final maps

def to_grid(block_values, shape, b=BLOCK):
    """Blocks -> 1 m cells, bilinear between block centres."""
    z = ndimage.zoom(block_values, b, order=1, mode="nearest", grid_mode=True)
    return z[:shape[0], :shape[1]]


def write(path, arr, profile, **tags):
    p = profile.copy()
    p.update(dtype="float32", count=1, nodata=np.nan, compress="deflate")
    with rasterio.open(path, "w", **p) as dst:
        dst.write(arr.astype(np.float32), 1)
        dst.update_tags(**tags)


def drives_check(sols, layers):
    """Mean and max of each layer along the E2 poses of the given sols (Juan, #108)."""
    import geopandas as gpd
    path = REPO / "data" / "e2" / "trajectory_poses.geojson"
    if not path.exists():
        return {}
    poses = gpd.read_file(path)
    out = {}
    for sol in sols:
        p = poses[poses.sol == sol]
        if p.empty:
            continue
        r, c = p.row.to_numpy(int), p.col.to_numpy(int)
        out[str(sol)] = {"poses": int(len(p))}
        for name, a in layers.items():
            v = a[r, c]
            out[str(sol)][name] = dict(mean=float(np.nanmean(v)), max=float(np.nanmax(v)))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--skip-cv", action="store_true", help="only the final maps")
    args = ap.parse_args()
    t0 = time.time()
    teacher, profile = read(E9 / "teacher_cover_1m.tif")
    student, _ = read(E9 / "rocas.tif")
    tb = block_means(teacher) * 100.0              # cover % per 20 m block
    sb = block_means(student) * 100.0
    fold = folds(tb.shape)
    groups = group_masks(block_means(np.isfinite(teacher).astype(float)))
    out = dict(block_m=BLOCK, blocks=int(tb.size), cv_tile_m=BLOCK * TILE_BLOCKS,
               group_blocks={k: int(v.sum()) for k, v in groups.items()},
               folds=N_FOLDS, seed=SEED, hyper_subsample=N_SUB,
               teacher_blocks=dict(mean_pct=float(np.nanmean(tb)),
                                   zero_share=float(np.mean(tb == 0)),
                                   p99_pct=float(np.nanpercentile(tb, 99))))
    if not args.skip_cv:
        cv = {}
        for transform in ("sqrt", "none"):
            cv[f"gp_teacher_{transform}"] = cross_validate(tb, tb, fold, transform, groups)
            print(f"GP teacher ({transform}): {cv[f'gp_teacher_{transform}']['rmse']:.4f} RMSE, "
                  f"IC90 {cv[f'gp_teacher_{transform}']['coverage_90']:.3f}  "
                  f"({time.time() - t0:.0f} s)", flush=True)
        cv["baselines_teacher"] = cv_baselines(tb, tb, fold, groups)
        cv["gp_student_vs_teacher_sqrt"] = cross_validate(sb, tb, fold, "sqrt", groups)
        cv["baselines_student_vs_teacher"] = cv_baselines(sb, tb, fold, groups)
        out["cv"] = cv
        b = cv["baselines_teacher"]
        print(f"rivals: mean {b['training_mean']['rmse']:.4f}, smoothing best "
              f"(sigma {b['smoothing_best_sigma_blocks']}) {b['smoothing_best']['rmse']:.4f}")
        g = cv["gp_student_vs_teacher_sqrt"]
        print(f"GP on student vs teacher: {g['rmse']:.4f} RMSE, IC90 {g['coverage_90']:.3f}")
        rf = random_folds(tb.shape)
        cv["random_blocks"] = dict(
            gp_teacher_sqrt=cross_validate(tb, tb, rf, "sqrt", groups),
            baselines_teacher=cv_baselines(tb, tb, rf, groups))
        r = cv["random_blocks"]
        print(f"random blocks: GP {r['gp_teacher_sqrt']['rmse']:.4f} (IC90 "
              f"{r['gp_teacher_sqrt']['coverage_90']:.3f}), mean "
              f"{r['baselines_teacher']['training_mean']['rmse']:.4f}, smoothing best "
              f"{r['baselines_teacher']['smoothing_best']['rmse']:.4f} (sigma "
              f"{r['baselines_teacher']['smoothing_best_sigma_blocks']})", flush=True)

    # final maps: GP (sqrt) on all teacher blocks
    X = block_xy(tb.shape)
    ok = np.isfinite(tb.ravel())
    gp = fit_gp(X[ok], np.sqrt(tb.ravel()[ok]))
    mu, sd = gp.predict(X, return_std=True)
    mean, std, lo, hi = back(mu, sd, "sqrt")
    mean_b, std_b = mean.reshape(tb.shape), std.reshape(tb.shape)
    nodata = ~np.isfinite(teacher)
    mean1 = to_grid(mean_b, teacher.shape) / 100.0
    std1 = to_grid(std_b, teacher.shape) / 100.0
    mean1[nodata], std1[nodata] = np.nan, np.nan
    common = dict(source="X1 (#102) GP on 20 m blocks of BoulderNet cover, src/dl_rocas/rocks_gp.py",
                  block_m=str(BLOCK))
    write(E9 / "rocks_mean.tif", mean1, profile,
          units="expected fraction of the cell covered by boulders (0-1), 20 m scale", **common)
    write(E9 / "rocks_std.tif", std1, profile,
          units="predictive std of that fraction (0-1), noise included", **common)
    out["final"] = dict(gp_params(gp), mean_pct_mean=float(np.nanmean(mean1) * 100),
                        std_pct_median=float(np.nanmedian(std1) * 100),
                        std_pct_p99=float(np.nanpercentile(std1, 99) * 100))

    # student + GP, for the comparison maps and the drives check
    oks = np.isfinite(sb.ravel())
    gps = fit_gp(X[oks], np.sqrt(sb.ravel()[oks]))
    mus, sds = gps.predict(X, return_std=True)
    smean, sstd, _, _ = back(mus, sds, "sqrt")
    out["final_student"] = gp_params(gps)
    layers = dict(teacher=teacher, student=student, gp_teacher_mean=mean1, gp_teacher_std=std1,
                  gp_student_mean=to_grid(smean.reshape(tb.shape), teacher.shape) / 100.0,
                  gp_student_std=to_grid(sstd.reshape(tb.shape), teacher.shape) / 100.0)
    out["drives_from_e1"] = drives_check((4544, 4673, 4680), layers)
    np.save(E9 / "rocks_gp_student_blocks.npy", np.stack([smean.reshape(tb.shape),
                                                           sstd.reshape(tb.shape)]))
    out["seconds"] = round(time.time() - t0, 1)
    (E9 / "rocks_gp.json").write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k not in ("cv",)}, indent=1))
    print("wrote", E9 / "rocks_mean.tif", E9 / "rocks_std.tif", E9 / "rocks_gp.json")


if __name__ == "__main__":
    sys.exit(main())
