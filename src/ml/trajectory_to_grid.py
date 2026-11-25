"""Minimal E2: Curiosity's trajectory (PLACES) mapped onto the base grid.

Input: PLACES localized_interp.csv and data/base/dem_1m.tif (JB's base grid).
Only ROVER rows are used: SITE rows (drive = -1) are site-frame origins, not poses.

Output in data/e2/:
  trajectory.gpkg            layers "route" (line) and "poses" (points), in the DEM CRS
  trajectory.geojson         the same route as a line (one segment per entry into the box)
  trajectory_poses.geojson   one point per pose, with sol, row, column and elevations
  trajectory_cells.csv       cells the rover went through (one row per cell)
  cell_sequence.csv          the same cells in the order they were traversed (input for E1)
  summary.json               DEM used and checks

Row and column come from the DEM transform: col = floor((E - XMIN) / 1 m),
row = floor((YMAX - N) / 1 m). PLACES coordinates are already in the DEM CRS.
GeoJSON files are in metres, with the contract CRS in the "crs" member.

Usage:  python src/ml/trajectory_to_grid.py
"""
import json

import geopandas as gpd
import numpy as np
import pandas as pd
import rasterio
from rasterio.crs import CRS

import common

SAMPLE_STEP_M = 0.25   # to find the cells the line between two poses crosses
MAX_GAP_M = 10.0       # consecutive poses farther apart than this start a new segment


def read_dem():
    path = common.base_layer("dem_1m.tif")
    xmin, ymin, xmax, ymax = common.crop_box()
    with rasterio.open(path) as d:
        z, t, crs, res, bounds = d.read(1), d.transform, d.crs, d.res, d.bounds
    checks = {
        "crs_matches_contract": crs == CRS.from_wkt(common.crs_wkt()),
        "cell_is_1m": res == (1.0, 1.0),
        "box_matches_contract": bool(np.allclose(tuple(bounds), (xmin, ymin, xmax, ymax), atol=1e-6)),
    }
    if not all(checks.values()):
        raise SystemExit(f"{path} does not meet the contract: {checks}")
    return path, z, t, checks


def read_poses(t, height, width):
    df = pd.read_csv(common.places_interp())
    df = df[(df.frame == "ROVER") & (df.sol >= 0)].reset_index(drop=True)
    # The file is sorted by (site, drive, pose), which is the order of the route.
    df["col"] = np.floor((df.easting - t.c) / t.a).astype(int)
    df["row"] = np.floor((df.northing - t.f) / t.e).astype(int)
    inside = df.col.between(0, width - 1) & df.row.between(0, height - 1)
    # A new segment starts every time the route enters the box again.
    df["segment"] = (inside & ~inside.shift(fill_value=False)).cumsum()
    d = df[inside].copy()
    gap = np.hypot(d.easting.diff(), d.northing.diff())
    d.loc[(gap > MAX_GAP_M) | (d.segment != d.segment.shift()), "segment_break"] = True
    d["segment"] = d.segment_break.fillna(False).astype(bool).cumsum()
    return d.drop(columns="segment_break").reset_index(drop=True)


def cell_sequence(d, t, height, width):
    """Cells crossed by the line between consecutive poses, without repeating consecutive cells."""
    parts = []
    for segment, g in d.groupby("segment", sort=True):
        e, n, sol = g.easting.to_numpy(), g.northing.to_numpy(), g.sol.to_numpy()
        pe, pn, ps = [e[:1]], [n[:1]], [sol[:1]]
        for i in range(len(g) - 1):
            k = max(1, int(np.ceil(np.hypot(e[i + 1] - e[i], n[i + 1] - n[i]) / SAMPLE_STEP_M)))
            s = np.linspace(0, 1, k + 1)[1:]
            pe.append(e[i] + s * (e[i + 1] - e[i]))
            pn.append(n[i] + s * (n[i + 1] - n[i]))
            ps.append(np.where(s < 1, sol[i], sol[i + 1]))
        pe, pn, ps = map(np.concatenate, (pe, pn, ps))
        c = np.clip(np.floor((pe - t.c) / t.a).astype(int), 0, width - 1)
        r = np.clip(np.floor((pn - t.f) / t.e).astype(int), 0, height - 1)
        changes = np.r_[True, (c[1:] != c[:-1]) | (r[1:] != r[:-1])]
        parts.append(pd.DataFrame({"segment": segment, "row": r[changes], "col": c[changes], "sol": ps[changes]}))
    s = pd.concat(parts, ignore_index=True)
    s.insert(1, "order", s.groupby("segment").cumcount())
    return s


def feature_collection(features):
    return {
        "type": "FeatureCollection",
        "crs": {"type": "name", "properties": {"name": common.crs_wkt()}},
        "features": features,
    }


def main():
    dem_path, z, t, checks = read_dem()
    height, width = z.shape
    d = read_poses(t, height, width)
    d["elev_dem"] = z[d.row, d.col]
    d["dz"] = d.elevation - d.elev_dem
    d["in_boxwork"] = d.sol.between(*common.BOXWORK_SOLS)

    seq = cell_sequence(d, t, height, width)
    by_segment = seq.groupby("segment")
    jump = np.maximum(abs(by_segment.row.diff()), abs(by_segment.col.diff()))
    checks["sequence_is_8_connected"] = bool((jump.dropna() == 1).all())
    checks["no_nan_on_route"] = bool(np.isfinite(d.elev_dem).all())

    # Cell list (one row per cell).
    seq["step"] = np.arange(len(seq))
    cells = seq.groupby(["row", "col"]).agg(
        n_steps=("step", "size"), first_step=("step", "min"), sol_min=("sol", "min"), sol_max=("sol", "max"),
    ).reset_index()
    n_poses = d.groupby(["row", "col"]).size().rename("n_poses")
    cells = cells.join(n_poses, on=["row", "col"]).fillna({"n_poses": 0}).astype({"n_poses": int})
    cells["has_pose"] = cells.n_poses > 0
    cells.insert(2, "x", t.c + (cells.col + 0.5) * t.a)
    cells.insert(3, "y", t.f + (cells.row + 0.5) * t.e)
    cells = cells.sort_values("first_step").reset_index(drop=True)

    # Route line and poses.
    lines = []
    for segment, g in d.groupby("segment"):
        xy = np.c_[g.easting, g.northing]
        lines.append({
            "type": "Feature",
            "geometry": {"type": "LineString", "coordinates": np.round(xy, 3).tolist()},
            "properties": {
                "segment": int(segment), "sol_start": int(g.sol.min()), "sol_end": int(g.sol.max()),
                "n_poses": len(g), "length_m": round(float(np.hypot(*np.diff(xy, axis=0).T).sum()), 1),
            },
        })
    poses = [{
        "type": "Feature",
        "geometry": {"type": "Point", "coordinates": [round(r.easting, 3), round(r.northing, 3)]},
        "properties": {
            "site": int(r.site), "drive": int(r.drive), "pose": int(r.pose), "sol": int(r.sol), "sclk": int(r.sclk),
            "row": int(r.row), "col": int(r.col), "elev_places": round(r.elevation, 3),
            "elev_dem": round(float(r.elev_dem), 3), "dz": round(float(r.dz), 3), "in_boxwork": bool(r.in_boxwork),
            "segment": int(r.segment),
        },
    } for r in d.itertuples()]

    out = common.E2_OUTPUT
    out.mkdir(parents=True, exist_ok=True)
    (out / "trajectory.geojson").write_text(json.dumps(feature_collection(lines)), encoding="utf-8")
    (out / "trajectory_poses.geojson").write_text(json.dumps(feature_collection(poses)), encoding="utf-8")
    cells.to_csv(out / "trajectory_cells.csv", index=False)
    seq.drop(columns="step").to_csv(out / "cell_sequence.csv", index=False)
    gpkg = out / "trajectory.gpkg"
    gpkg.unlink(missing_ok=True)
    for layer, feats in (("route", lines), ("poses", poses)):
        gpd.GeoDataFrame.from_features(feats, crs=common.crs_wkt()).to_file(gpkg, layer=layer, driver="GPKG")

    summary = {
        "dem": dem_path.relative_to(common.REPO).as_posix(),
        "places": common.places_interp().name,
        "poses": len(d), "sols": [int(d.sol.min()), int(d.sol.max())],
        "poses_in_boxwork": int(d.in_boxwork.sum()), "boxwork_sols_provisional": list(common.BOXWORK_SOLS),
        "segments": int(d.segment.nunique()), "length_m": round(sum(f["properties"]["length_m"] for f in lines), 1),
        "cells": len(cells), "cells_with_pose": int(cells.has_pose.sum()), "sequence_steps": len(seq),
        "dz_places_minus_dem_m": {k: round(float(v), 2) for k, v in
                                  zip(("p5", "median", "p95"), np.percentile(d.dz, [5, 50, 95]))},
        "poses_with_abs_dz_over_2m": int((abs(d.dz) > 2).sum()),
        "checks": checks,
    }
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
