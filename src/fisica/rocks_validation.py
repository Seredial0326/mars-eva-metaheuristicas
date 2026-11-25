"""C5 (#120): independent spatial validation around the existing X1 fitter.

Reuses dl_rocas.rocks_gp and grafos.rock_risk without changing either owner.
No final full-fit raster is scored as if it were an out-of-fold prediction.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys

import numpy as np
import rasterio
from scipy import ndimage
from scipy.sparse.csgraph import dijkstra
from threadpoolctl import threadpool_limits

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dl_rocas import rocks_gp as gp
from grafos.graph import Graph, follow
from grafos.rock_risk import rock_factor


def digest(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def split_masks(fold, valid, test_id, buffer=1):
    """Disjoint train/calibration/test groups, plus a spatial training buffer."""
    if buffer < 0:
        raise ValueError("buffer must be nonnegative")
    ids = sorted(np.unique(fold[valid]).tolist())
    if len(ids) < 4 or test_id not in ids:
        raise ValueError("at least four spatial fold groups required")
    cal_id = ids[(ids.index(test_id) + 1) % len(ids)]
    test, cal = valid & (fold == test_id), valid & (fold == cal_id)
    excluded = test | cal
    if buffer:
        excluded = ndimage.binary_dilation(excluded, iterations=buffer)
    train = valid & ~excluded
    if not train.any() or not cal.any() or not test.any():
        raise ValueError("empty spatial partition")
    return train, cal, test


def smoothing_model(values, fold, train, cal, sigmas=(1., 2., 3., 5., 10.), buffer=1):
    """Choose sigma on inner training folds; calibrate width on a separate group.

    Calibration labels never enter the mean fit; outer-test labels enter neither
    tuning nor interval width. This is an empirical residual envelope, not a
    guaranteed spatial conformal interval.
    """
    errors = {}
    for sigma in sigmas:
        residuals = []
        for inner in np.unique(fold[train]):
            held = train & (fold == inner)
            fit = train & (fold != inner)
            if buffer:
                fit &= ~ndimage.binary_dilation(held, iterations=buffer)
            if fit.any() and held.any():
                pred = gp.smooth_predict(np.nan_to_num(values), fit, sigma)
                residuals.extend((pred[held] - values[held]).tolist())
        if not residuals:
            raise ValueError("no inner spatial validation samples")
        errors[float(sigma)] = float(np.mean(np.square(residuals)))
    sigma = min(errors, key=lambda s: (errors[s], s))
    mean = gp.smooth_predict(np.nan_to_num(values), train, sigma)
    width = float(np.quantile(np.abs(values[cal] - mean[cal]), .90, method="higher"))
    return {"sigma_blocks": sigma, "calibration_half_width_pct": width,
            "inner_mse": errors}, mean, np.maximum(0, mean - width), mean + width


def metrics(pred, truth, lo, hi, mask):
    if not mask.any():
        return {"blocks": 0, "rmse_pct": None, "coverage_90": None, "width_mean_pct": None}
    err = pred[mask] - truth[mask]
    return {"blocks": int(mask.sum()), "rmse_pct": float(np.sqrt(np.mean(err ** 2))),
            "coverage_90": float(np.mean((truth[mask] >= lo[mask]) & (truth[mask] <= hi[mask]))),
            "width_mean_pct": float(np.mean(hi[mask] - lo[mask]))}


def validate(teacher, out, *, seed=1205, buffer=1):
    values = gp.block_means(teacher) * 100
    valid = np.isfinite(values)
    folds = gp.folds(values.shape, seed)
    groups = gp.group_masks(gp.block_means(np.isfinite(teacher).astype(float)))
    groups.update(all=valid, rocky=valid & (values > 0), zero=valid & (values == 0))
    coordinates = gp.block_xy(values.shape)
    models = {name: {k: np.full(values.shape, np.nan) for k in ("mean", "std", "lo", "hi")}
              for name in ("gp", "smooth")}
    records = []
    out.mkdir(parents=True, exist_ok=True)
    for k in range(gp.N_FOLDS):
        train, cal, test = split_masks(folds, valid, k, buffer)
        baseline, mean, lo, hi = smoothing_model(values, folds, train, cal, buffer=buffer)
        models["smooth"]["mean"][test], models["smooth"]["lo"][test], models["smooth"]["hi"][test] = mean[test], lo[test], hi[test]
        print(f"fold {k}: GP training on {int(train.sum())} blocks; calibration={int(cal.sum())}, test={int(test.sum())}", flush=True)
        # The original fitter chooses hyperparameters from training values only.
        with threadpool_limits(limits=4):
            fitted = gp.fit_gp(coordinates[train.ravel()], gp.forward(values[train], "sqrt"), seed + k)
            mu_z, sd_z = fitted.predict(coordinates[test.ravel()], return_std=True)
        mu, sd, lower, upper = gp.back(mu_z, sd_z, "sqrt")
        for name, array in zip(("mean", "std", "lo", "hi"), (mu, sd, lower, upper)):
            models["gp"][name][test] = array
        records.append({"fold": k, "training_blocks": int(train.sum()),
                        "calibration_blocks": int(cal.sum()), "test_blocks": int(test.sum()),
                        "smooth": baseline, "gp": gp.gp_params(fitted)})
        # Persist real held-out predictions and partition IDs for independent audit.
        np.savez_compressed(out / f"fold_{k}.npz", truth_pct=values, fold_ids=folds,
                            train=train, calibration=cal, test=test,
                            gp_mean_pct=models["gp"]["mean"], gp_std_pct=models["gp"]["std"],
                            gp_lo_pct=models["gp"]["lo"], gp_hi_pct=models["gp"]["hi"],
                            smooth_mean_pct=models["smooth"]["mean"],
                            smooth_lo_pct=models["smooth"]["lo"], smooth_hi_pct=models["smooth"]["hi"])
        print(f"fold {k} saved", flush=True)
        del fitted
    result = {"settings": {"seed": seed, "block_m": gp.BLOCK, "tile_m": gp.BLOCK * gp.TILE_BLOCKS,
                           "folds": gp.N_FOLDS, "training_buffer_blocks": buffer,
                           "training_buffer_m": buffer * gp.BLOCK,
                           "protocol": "outer test + separate calibration + inner training-only sigma selection"},
              "per_fold": records, "scores": {}}
    for name, arrays in models.items():
        result["scores"][name] = {group: metrics(arrays["mean"], values, arrays["lo"], arrays["hi"],
                                               mask & valid) for group, mask in groups.items()}
    # Bootstrap complete 400 m tiles, not individual 20 m blocks or 1 m cells.
    tile_cover = {name: [] for name in models}
    for r in range(0, values.shape[0], gp.TILE_BLOCKS):
        for c in range(0, values.shape[1], gp.TILE_BLOCKS):
            tile = np.zeros(values.shape, bool)
            tile[r:r + gp.TILE_BLOCKS, c:c + gp.TILE_BLOCKS] = True
            for name, arrays in models.items():
                tile_cover[name].append(metrics(arrays["mean"], values, arrays["lo"], arrays["hi"],
                                                tile & valid)["coverage_90"])
    rng = np.random.default_rng(seed)
    resample = rng.integers(0, len(tile_cover["gp"]), (1000, len(tile_cover["gp"])))
    for name, values_ in tile_cover.items():
        samples = np.asarray(values_)[resample].mean(axis=1)
        result["scores"][name]["tile_bootstrap_coverage_ci95"] = np.quantile(samples, [.025, .975]).tolist()
    result["warnings"] = ["Teacher cover is the reference, not independent human rock labels.",
                           "Final full-fit rocks_std.tif cannot be called out-of-fold validation; this refits the unchanged X1 fitter on held-out partitions.",
                           "Both mean predictors use the same training partition; smoothing calibrates its envelope on a separate group.",
                           "The buffer/calibration holdout make this protocol different from Aaron's original CV; numbers need not match.",
                           "Tile-bootstrap intervals are conditional spatial summaries, not a physical coverage guarantee."]
    (out / "validation.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    table = ["# C5 held-out spatial interval comparison", "",
             "Teacher reference only; no final full-fit map is counted as held out.", "",
             "| Model | Group | Blocks | RMSE (% cover) | Coverage of nominal 90% interval | Mean width (% cover) |",
             "|---|---|---|---|---|---|"]
    for name in models:
        for group in groups:
            s = result["scores"][name][group]
            table.append(f"| {name} | {group} | {s['blocks']} | {s['rmse_pct']} | {s['coverage_90']} | {s['width_mean_pct']} |")
    table += ["", "Source: src/fisica/rocks_validation.py → validation.json and fold_*.npz."]
    (out / "table.md").write_text("\n".join(table), encoding="utf-8")
    return result


def route_sensitivity(data, layers, out):
    """Use released maps and existing risk function; never change nominal costs."""
    graph = Graph.from_base_dir(data / "base")
    r, c = graph.snap(graph.height // 2, graph.width // 2, graph.main_component())
    habitat = int(graph.node(r, c))
    import geopandas as gpd
    goals = []
    for p in (data / "stations/stations_manual.gpkg", data / "stations/stations_e8.gpkg"):
        if p.exists():
            for _, station in gpd.read_file(p, layer="stations").iterrows():
                r, c, _ = graph.place(station.geometry.x, station.geometry.y)
                goals.append((str(station["id"]), int(graph.node(r, c))))
    arrays = {}
    for name, path in {"mean": layers / "rocks_mean.tif", "std": layers / "rocks_std.tif",
                       "teacher": data / "e9/teacher_cover_1m.tif"}.items():
        with rasterio.open(path) as src:
            if src.shape != graph.shape or tuple(src.transform)[:6] != tuple(graph.transform)[:6]:
                raise ValueError("risk raster does not match base grid")
            arrays[name] = src.read(1).ravel()
    base, length = graph.csr("energy_j"), graph.csr("length_m")
    rows, nominal = [], {}
    for k, lam in [(0., 0.), *[(k, lam) for k in (1., 3., 10.) for lam in (0., 1.645)]]:
        factor = rock_factor(arrays["mean"], arrays["std"], k, lam)
        if not np.isfinite(factor).all():
            raise ValueError("nonfinite risk factor")
        weighted = base.copy()
        for start in range(0, len(weighted.data), 1_000_000):
            weighted.data[start:start + 1_000_000] *= factor[weighted.indices[start:start + 1_000_000]]
        _, a = dijkstra(weighted, indices=habitat, return_predecessors=True)
        _, b = dijkstra(weighted.T.tocsr(), indices=habitat, return_predecessors=True)
        for name, goal in goals:
            if goal == habitat or a[goal] < 0 or b[goal] < 0:
                continue
            path = np.r_[follow(a, goal, habitat)[::-1], follow(b, goal, habitat)[1:]]
            e3 = float(np.asarray(base[path[:-1], path[1:]]).sum() / 3600)
            priced = float(np.asarray(weighted[path[:-1], path[1:]]).sum() / 3600)
            distance = float(np.asarray(length[path[:-1], path[1:]]).sum())
            if k == 0:
                nominal[name] = {"e3": e3, "length": distance}
            rows.append({"k_assumed": k, "lambda_assumed": lam, "goal": name,
                         "e3_wh": e3, "priced_wh": priced, "length_m": distance,
                         "e3_delta_pct": 100 * (e3 / nominal[name]["e3"] - 1),
                         "length_delta_m": distance - nominal[name]["length"],
                         "teacher_cover_sum": float(np.nansum(arrays["teacher"][path])),
                         "usable_budget_assumed_wh": 1.10 * nominal[name]["e3"],
                         "priced_margin_wh": 1.10 * nominal[name]["e3"] - priced})
        print(f"risk sweep k={k}, lambda={lam} complete", flush=True)
        del weighted
    summary = []
    for k, lam in sorted({(r["k_assumed"], r["lambda_assumed"]) for r in rows}):
        case = [r for r in rows if (r["k_assumed"], r["lambda_assumed"]) == (k, lam)]
        summary.append({"k_assumed": k, "lambda_assumed": lam, "goals": len(case),
                        "teacher_cover_sum_total": sum(r["teacher_cover_sum"] for r in case),
                        "e3_delta_pct_median": float(np.median([r["e3_delta_pct"] for r in case])),
                        "e3_delta_pct_max": max(r["e3_delta_pct"] for r in case),
                        "length_delta_m_max": max(r["length_delta_m"] for r in case),
                        "priced_margin_wh_min": min(r["priced_margin_wh"] for r in case)})
    result = {"rows": rows, "summary": summary, "nominal_policy": "E3, k=lambda=0 unchanged",
              "warnings": ["k and lambda are sensitivity assumptions, not validated astronaut costs.",
                           "Priced margin uses an artificial 1.10x nominal E3 loop budget, not a suit allocation.",
                           "Teacher cover is an orbital detector output, not full ground truth; unresolved rocks and teacher bias remain."]}
    (out / "routes.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def draw(result, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    fig, ax = plt.subplots(figsize=(7, 4))
    groups = ("all", "rocky", "edge", "near_nodata", "interior")
    for offset, name in ((-.12, "gp"), (.12, "smooth")):
        values = [result["scores"][name][g]["coverage_90"] for g in groups]
        ax.plot(np.arange(len(groups)) + offset, values, "o", label=name)
    ax.axhline(.9, color="#777", linestyle="--", label="nominal 90%")
    ax.set_xticks(range(len(groups)), ["all", "rocky", "edge", "near nodata", "interior"])
    ax.set_ylabel("Held-out interval coverage")
    ax.set_ylim(0, 1.02)
    ax.set_title("C5: blocked test, separate calibration, training buffer")
    ax.spines[["top", "right"]].set_visible(False)
    ax.legend()
    fig.tight_layout()
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=140)
    plt.close(fig)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", type=Path, required=True)
    parser.add_argument("--layers", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=1205)
    parser.add_argument("--buffer", type=int, default=1)
    parser.add_argument("--skip-routes", action="store_true")
    parser.add_argument("--figure", type=Path)
    args = parser.parse_args()
    if args.buffer < 0 or args.seed < 0:
        raise ValueError("buffer and seed must be nonnegative")
    with rasterio.open(args.data / "e9/teacher_cover_1m.tif") as src:
        teacher = src.read(1)
    result = validate(teacher, args.out, seed=args.seed, buffer=args.buffer)
    sources = [args.data / "e9/teacher_cover_1m.tif", args.layers / "rocks_mean.tif", args.layers / "rocks_std.tif"]
    if not args.skip_routes:
        route_sensitivity(args.data, args.layers, args.out)
        sources += [args.data / "base" / n for n in ("dem_1m.tif", "slope_deg.tif", "grid.json", "crs.wkt")]
        cached_edges = args.data / "base/edges_e3.npz"
        if cached_edges.exists():
            sources.append(cached_edges)
        sources += [p for p in (args.data / "stations/stations_manual.gpkg", args.data / "stations/stations_e8.gpkg") if p.exists()]
    manifest = {"data_sha256": {str(p): digest(p) for p in sources},
                "script_sha256": digest(__file__), "original_fitter_sha256": digest(gp.__file__),
                "graph_module_sha256": digest(sys.modules[Graph.__module__].__file__),
                "risk_module_sha256": digest(sys.modules[rock_factor.__module__].__file__),
                "commit": subprocess.check_output(["git", "rev-parse", "HEAD"], text=True).strip(),
                "seed": args.seed, "production_changes": False}
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    if args.figure:
        draw(result, args.figure)
    print(args.out / "validation.json")


if __name__ == "__main__":
    main()
