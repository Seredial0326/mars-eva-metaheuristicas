"""E11: the NumPy viewshed against GDAL's on the real DEM (needs GDAL, i.e. conda).

    python src/gis/comms_engine_check.py

Writes data/comms/engine_check.json:
- viewsheds: for 21 habitat cells (the centre, its neighbour, the four corners, edge
  cells and 12 random cells) and three antenna heights (1.7, 3 and 10 m), how many of
  the 4,000,000 cells GDAL ViewshedGenerate and comms.viewshed_numpy mark differently;
- tour: coverage, check_route and check_pair on the saved plan (data/plans/last_plan.json,
  the planner's last plan) with each engine, and whether the answers are identical;
- dem: whether rasterio and GDAL read the same DEM and geotransform.
"""

import json
import sys
import time
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from gis import comms  # noqa: E402

BASE = REPO / "data" / "base"
OUT = REPO / "data" / "comms" / "engine_check.json"


def clear():
    comms.dem.cache_clear()
    comms._viewshed.cache_clear()


def with_engine(name, fn):
    gdal = comms.gdal
    comms.gdal = gdal if name == "gdal" else None
    clear()
    try:
        return fn()
    finally:
        comms.gdal = gdal
        clear()


def main():
    if comms.gdal is None:
        raise SystemExit("needs GDAL's Python bindings (conda install -c conda-forge gdal)")
    base = str(BASE)
    z, gt = comms.dem(base)
    rng = np.random.default_rng(7)
    cells = [(1000, 1000), (1000, 1001), (0, 0), (0, 1999), (1999, 0), (1999, 1999),
             (5, 1000), (1000, 3), (1994, 1500)]
    cells += [tuple(int(v) for v in rng.integers(0, 2000, 2)) for _ in range(12)]
    rows, seconds = [], []
    for r, c in cells:
        for antenna_h in (3.0, 10.0, 1.7):
            ref = comms._viewshed.__wrapped__(base, r, c, antenna_h, comms.ASTRONAUT_H)
            t0 = time.perf_counter()
            ours = comms.viewshed_numpy(z, gt, r, c, antenna_h, comms.ASTRONAUT_H)
            seconds.append(time.perf_counter() - t0)
            rows.append({"row": r, "col": c, "antenna_h": antenna_h,
                         "gdal_visible": round(float(ref.mean()), 6),
                         "numpy_visible": round(float(ours.mean()), 6),
                         "differing_cells": int((ref != ours).sum())})

    plan = json.loads((REPO / "data" / "plans" / "last_plan.json").read_text())["plan"]
    route = next(f for f in plan["features"] if f["properties"].get("kind") == "route")
    xy, t_s = route["geometry"]["coordinates"], route["properties"].get("t_s")
    hab = plan["properties"]["habitat"]

    def tour():
        return {"coverage": comms.coverage(hab, base),
                "route": comms.check_route(xy, hab, base, t_s=t_s),
                "pair": comms.check_pair(xy, hab, base, t_s=t_s)}

    g, n = with_engine("gdal", tour), with_engine("numpy", tour)
    same = json.dumps(g, sort_keys=True, default=str) == json.dumps(n, sort_keys=True, default=str)
    zg, gtg = with_engine("gdal", lambda: comms.dem(base))
    zn, gtn = with_engine("numpy", lambda: comms.dem(base))

    out = {
        "viewsheds": {"count": len(rows), "cells_each": int(z.size),
                      "max_differing_cells": max(r["differing_cells"] for r in rows),
                      "numpy_seconds_median": round(float(np.median(seconds)), 3),
                      "cases": rows},
        "tour": {"identical": same, "habitat": hab,
                 "coverage": round(g["coverage"], 6),
                 "route_summary": g["route"]["summary"],
                 "pair_summary": {k: v for k, v in g["pair"].items()
                                  if not isinstance(v, (list, dict))}},
        "dem": {"identical": bool(np.array_equal(zg, zn, equal_nan=True)),
                "geotransform_identical": tuple(gtg) == tuple(gtn)},
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print(f"wrote {OUT}: {out['viewsheds']['count']} viewsheds, max differing cells "
          f"{out['viewsheds']['max_differing_cells']}; tour identical {same}; "
          f"dem identical {out['dem']['identical']}")


if __name__ == "__main__":
    main()
