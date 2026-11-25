"""Build R(v) and an E4 round trip with walkback on the real grid.

Run from the repo root:
    python src/grafos/build_rv.py --habitat X Y [--budget-wh 1000] [--margin 0.1]
        [--goal X Y] [--base-dir data/base] [--out-dir data/e4]

--habitat is required (user input, metres in the DEM's CRS; the box spans
x 8142537.49 .. 8144537.49, y -285463.08 .. -283463.08). If it falls on a
blocked cell (slope > 30 deg) or outside the main connected area, it is moved
to the nearest valid cell and the move is reported.

Uses data/base/edges_e3.npz if present; otherwise computes the E3 costs in
memory from dem_1m.tif and slope_deg.tif (~3 s).

Writes to OUT_DIR:
    rv.tif         R(v): energy (Wh) to return to the habitat, float32, NaN = cannot return
    g.tif          energy (Wh) to reach each cell from the habitat, NaN = unreachable
    safe.tif       1 where g + R <= usable budget, 0 elsewhere (float32, NaN off-graph)
    e4_route.geojson  round trip habitat -> goal -> habitat with the walkback profile
"""

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
import rasterio

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.graph import Graph  # noqa: E402
from grafos.labels import Budget, NoFeasibleRoute, min_slack, round_trip  # noqa: E402
from grafos.walkback import J_PER_WH, Walkback  # noqa: E402

# Metabolic power while working at a site. ~205 W is the upper end of the "low"
# band (<= 700 BTU/h) in NASA xEMU metabolic studies (NTRS 20220009964).
SERVICE_POWER_W = 205.0


def write_raster(path, a, profile):
    with rasterio.open(path, "w", **profile) as dst:
        dst.write(a.astype("float32"), 1)


def route_geojson(graph, prof, habitat_xy, goal_xy, crs_wkt, **props):
    rows, cols = graph.cell(prof["path"])
    x, y = graph.cell_to_xy(rows, cols)
    wh = lambda a: [round(float(v) / J_PER_WH, 4) for v in a]   # noqa: E731
    line = {"type": "Feature",
            "geometry": {"type": "LineString",
                         "coordinates": [[float(a), float(b)] for a, b in zip(x, y)]},
            "properties": {"kind": "route", "approach": "E4_walkback",
                           "feasible": prof["feasible"],
                           "first_violation": prof["first_violation"],
                           "turn_index": prof.get("turn_index"),
                           "energy_wh": round(float(prof["used_j"][-1]) / J_PER_WH, 3),
                           "time_s": round(float(prof["time_s"][-1]), 1),
                           "length_m": round(float(prof["length_m"][-1]), 1),
                           "o2_l": round(float(prof["o2_l"][-1]), 2),
                           "method": prof.get("method"), "exact": prof.get("exact"),
                           "gap": prof.get("gap"),
                           "usable_wh": round(prof["usable_j"] / J_PER_WH, 3),
                           # per-vertex profile, same order as the coordinates
                           "used_wh": wh(prof["used_j"]), "rv_wh": wh(prof["rv_j"]),
                           "slack_wh": wh(prof["slack_j"]),
                           "t_s": [round(float(v), 1) for v in prof["time_s"]],
                           "rv_time_s": [round(float(v), 1) for v in prof["rv_time_s"]],
                           "o2_used_l": [round(float(v), 3) for v in prof["o2_l"]],
                           **props}}
    pts = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": list(p)},
            "properties": {"kind": k}} for k, p in (("start", habitat_xy), ("goal", goal_xy))]
    return {"type": "FeatureCollection",
            "crs": {"type": "name", "properties": {"name": crs_wkt}},
            "features": [line] + pts}


def place(graph, main_cc, xy, label):
    """CLI wrapper of Graph.place: prints the move and exits on bad input.
    Library code should call graph.place(x, y) and handle ValueError itself.
    `main_cc` is kept for backward compatibility and ignored."""
    try:
        sr, sc, moved = graph.place(*xy, label=label)
    except ValueError as err:
        sys.exit(f"error: {err}")
    if moved > 0:
        print(f"warning: {label} {list(xy)} is on a blocked cell or outside the main "
              f"connected area; moved {moved:.1f} m to cell ({sr}, {sc})")
    return sr, sc


def main():
    repo = Path(__file__).resolve().parents[2]
    ap = argparse.ArgumentParser(description="R(v) and E4 walkback round trip.")
    ap.add_argument("--habitat", type=float, nargs=2, metavar=("X", "Y"), required=True,
                    help="habitat position, metres in the DEM's CRS")
    ap.add_argument("--budget-wh", type=float, default=1000.0)
    ap.add_argument("--margin", type=float, default=0.10)
    ap.add_argument("--goal", type=float, nargs=2, metavar=("X", "Y"),
                    help="default: the safe cell farthest (in energy) from the habitat")
    ap.add_argument("--max-duration-min", type=float, default=None,
                    help="maximum EVA duration (default: no limit)")
    ap.add_argument("--o2-budget-l", type=float, default=None,
                    help="usable O2 in litres, after reserves (default: no limit)")
    ap.add_argument("--o2-leak-lpm", type=float, default=0.0,
                    help="time-based O2 use, L/min (leakage/purge), declared assumption")
    ap.add_argument("--service-min", type=float, default=0.0, help="work time at the goal")
    ap.add_argument("--service-power-w", type=float, default=SERVICE_POWER_W,
                    help="metabolic power while working at the goal")
    ap.add_argument("--objective", choices=["energy", "time", "o2"], default="energy")
    ap.add_argument("--base-dir", default=str(repo / "data" / "base"))
    ap.add_argument("--out-dir", default=str(repo / "data" / "e4"))
    args = ap.parse_args()

    base, out = Path(args.base_dir), Path(args.out_dir)
    out.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    graph = Graph.from_base_dir(base)
    main_cc = graph.main_component()
    print(f"graph: {graph.n:,} nodes, {graph.csr().nnz:,} arcs; largest SCC "
          f"{100 * main_cc.mean():.1f}% ({time.time() - t0:.1f}s)")

    hr, hc = place(graph, main_cc, args.habitat, "habitat")
    habitat = int(graph.node(hr, hc))
    habitat_xy = [float(v) for v in graph.cell_to_xy(hr, hc)]

    budget = Budget(
        energy_j=args.budget_wh * (1 - args.margin) * J_PER_WH,
        time_s=np.inf if args.max_duration_min is None else args.max_duration_min * 60.0,
        o2_l=np.inf if args.o2_budget_l is None else args.o2_budget_l,
        leak_lpm=args.o2_leak_lpm)

    t0 = time.time()
    wb = Walkback.compute(graph, habitat)
    rv_t = graph.costs_to(habitat, "time_s")
    g_t = graph.costs_from(habitat, "time_s")
    # Safe region: every limit's lower bound for a there-and-back trip (no service).
    # Necessary condition; the exact answer for one goal is the label-setting below.
    loop_e, loop_t = wb.g_j + wb.rv_j, g_t + rv_t
    safe = ((loop_e <= budget.energy_j) & (loop_t <= budget.time_s)
            & (budget.o2(loop_e, loop_t) <= budget.o2_l))
    print(f"R(v), g(v) in energy and time: {time.time() - t0:.1f}s; safe cells "
          f"{safe.sum():,} ({100 * safe.mean():.1f}%)")

    with rasterio.open(base / "dem_1m.tif") as src:
        profile = src.profile | {"dtype": "float32", "nodata": np.nan, "count": 1,
                                 "compress": "deflate"}
    write_raster(out / "rv.tif", wb.raster(wb.rv_j / J_PER_WH), profile)
    write_raster(out / "rv_time_s.tif", wb.raster(rv_t), profile)
    write_raster(out / "g.tif", wb.raster(wb.g_j / J_PER_WH), profile)
    reach = np.isfinite(wb.g_j) & np.isfinite(wb.rv_j)
    write_raster(out / "safe.tif",
                 np.where(reach, safe, np.nan).reshape(graph.shape), profile)

    if args.goal:
        gr, gc = place(graph, main_cc, args.goal, "goal")
        goal = int(graph.node(gr, gc))
    else:
        goal = int(np.argmax(np.where(safe, loop_e, -np.inf)))
        gr, gc = graph.cell(goal)
    goal_xy = [float(v) for v in graph.cell_to_xy(gr, gc)]

    t0 = time.time()
    try:
        prof = round_trip(graph, habitat, goal, budget, objective=args.objective,
                          service_s=args.service_min * 60.0,
                          service_power_w=args.service_power_w)
    except NoFeasibleRoute as err:
        sys.exit(f"no feasible E4 route to {goal_xy}: {err}")
    s = min_slack(prof)
    fc = route_geojson(graph, prof, habitat_xy, goal_xy, graph.crs_wkt,
                       budget_wh=args.budget_wh, margin=args.margin,
                       max_duration_min=args.max_duration_min, o2_budget_l=args.o2_budget_l,
                       o2_leak_lpm=args.o2_leak_lpm, service_min=args.service_min,
                       objective=args.objective)
    (out / "e4_route.geojson").write_text(json.dumps(fc), encoding="utf-8")
    unit, scale = {"energy": ("Wh", J_PER_WH), "time": ("min", 60.0), "o2": ("L", 1.0)}[args.objective]
    print(f"route: method {prof['method']}, exact={prof['exact']}, "
          f"gap to optimum <= {prof['gap'] / scale:.2f} {unit}, "
          f"{prof['labels_expanded']:,} labels, {time.time() - t0:.1f}s")
    print(f"habitat {habitat_xy}, goal {goal_xy}: round trip "
          f"{prof['used_j'][-1] / J_PER_WH:.1f} Wh, {prof['time_s'][-1] / 60:.1f} min, "
          f"{prof['o2_l'][-1]:.1f} L O2, {prof['length_m'][-1]:.0f} m; min slack "
          f"{s['energy_j'] / J_PER_WH:.1f} Wh, {s['time_s'] / 60:.1f} min, {s['o2_l']:.1f} L")


if __name__ == "__main__":
    main()
