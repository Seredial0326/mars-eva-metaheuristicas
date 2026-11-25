"""E3 sensitivity analysis (guide REV3, sections 9.2 and 42.1).

Usage (repo root):
    python src/fisica/sensitivity.py
Inputs:  data/base/dem_1m.tif, slope_deg.tif (base-grid-v2)
Outputs: data/e3/e3_sensitivity.json
         paper/figures/e3_fig2_sensitivity.png

One parameter changes at a time from the nominal model (Santee 2001, 124.2 kg,
signed Apollo speed, g = 3.71 m/s^2, cells steeper than 30 deg blocked):
mass, speed sign convention, gravity, metabolic model and the cell block.
For each scenario:
- toy route (4.1 km flat + 0.9 km horizontal at +10 deg): energy and time;
- return fields from a habitat at the box centre: median and maximum return
  energy R_E, median return time R_T, share of the box within 30 min;
- energy-optimal route from the habitat to Curiosity's drilled ridge (Nevado
  Sajama): energy, time, length, and the share of its cells within 5 m of the
  nominal route (buffer metric, guide section 41.2), which says whether the
  route itself changes. Sharing exact cells is too strict: a parallel path one
  metre away shares none.
"""

import json
import sys
from math import cos, radians
from pathlib import Path

import numpy as np
import rasterio
from scipy.ndimage import distance_transform_edt
from scipy.sparse import csr_matrix
from scipy.sparse.csgraph import dijkstra

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from fisica.edge_cost import NEIGHBOURS, edge_costs, model_power  # noqa: E402
from fisica.metabolic import G_EARTH, G_MARS, G_MOON, J_PER_WH, TOTAL_MASS_KG  # noqa: E402

BASE = REPO / "data" / "base"
OUT_JSON = REPO / "data" / "e3" / "e3_sensitivity.json"
OUT_FIG = REPO / "paper" / "figures" / "e3_fig2_sensitivity.png"
GOAL_XY = (8143217.5, -284993.2)       # Nevado Sajama drill (Curiosity ridge), see api/candidates.py

NOMINAL = dict(mass_kg=TOTAL_MASS_KG, signed=True, g_mps2=G_MARS, model="santee2001",
               max_cell_slope_deg=30.0)
SCENARIOS = [
    ("nominal", {}),
    ("mass 100 kg", {"mass_kg": 100.0}),
    ("mass 150 kg", {"mass_kg": 150.0}),
    ("speed from |alpha|", {"signed": False}),
    ("gravity Moon 1.62", {"g_mps2": G_MOON}),
    ("gravity Earth 9.81", {"g_mps2": G_EARTH}),
    ("model Pandolf + CF", {"model": "pandolf_cf"}),
    ("model Pandolf + CF x g/gE", {"model": "pandolf_cf_scaled"}),
    ("cell block 20 deg", {"max_cell_slope_deg": 20.0}),
    ("cell block 25 deg", {"max_cell_slope_deg": 25.0}),
    ("no cell block", {"max_cell_slope_deg": None}),
]


def toy_route(p):
    """Energy (kJ) and time (h) of the guide's 5 km toy route under scenario p."""
    e = t = 0.0
    for d_h, a in ((4100.0, 0.0), (900.0, 10.0)):
        v = 0.75 - 0.01 * (a if p["signed"] else abs(a))
        dt = d_h / (v * cos(radians(a)))
        e += float(model_power(p["model"], p["mass_kg"], np.float64(v), np.float64(a), p["g_mps2"])) * dt
        t += dt
    return e / 1000.0, t / 3600.0


def graph(w, shape):
    rows, cols = shape
    idx = np.arange(rows * cols).reshape(shape)
    src, dst, data = [], [], []
    for k, (dr, dc) in enumerate(NEIGHBOURS):
        ok = np.isfinite(w[k])
        r, c = np.nonzero(ok)
        src.append(idx[r, c]); dst.append(idx[r + dr, c + dc]); data.append(w[k][ok].astype(np.float64))
    n = rows * cols
    return csr_matrix((np.concatenate(data), (np.concatenate(src), np.concatenate(dst))), shape=(n, n))


def path_nodes(pred, start, end):
    nodes, n = [], end
    while n != start and n >= 0:
        nodes.append(int(n)); n = pred[n]
    return set(nodes + [start]) if n == start else set()


def run_scenario(p, dem, slope, transform, habitat, goal):
    t_s, e_j, _ = edge_costs(dem, mass_kg=p["mass_kg"], g_mps2=p["g_mps2"], signed=p["signed"],
                             cell_slope_deg=slope, max_cell_slope_deg=p["max_cell_slope_deg"],
                             model=p["model"])
    ge, gt = graph(e_j, dem.shape), graph(t_s, dem.shape)
    r_e = dijkstra(ge.T.tocsr(), directed=True, indices=habitat)
    r_t = dijkstra(gt.T.tocsr(), directed=True, indices=habitat)
    f_e, pred = dijkstra(ge, directed=True, indices=habitat, return_predecessors=True)
    nodes = path_nodes(pred, habitat, goal)
    # time and length along the energy-optimal route
    order, n = [goal], goal
    while n != habitat:
        n = pred[n]; order.append(int(n))
    order = order[::-1]
    cols = dem.shape[1]
    t_route = length = 0.0
    for a, b in zip(order[:-1], order[1:]):
        dr, dc = b // cols - a // cols, b % cols - a % cols
        k = NEIGHBOURS.index((dr, dc))
        t_route += float(t_s[k, a // cols, a % cols])
        length += float(np.hypot(dr, dc))
    ok = np.isfinite(r_e)
    toy_kj, toy_h = toy_route(p)
    return {
        "toy_energy_kj": toy_kj, "toy_time_h": toy_h,
        "reachable_pct": float(ok.mean() * 100),
        "return_energy_wh_median": float(np.median(r_e[ok]) / J_PER_WH),
        "return_energy_wh_max": float(r_e[ok].max() / J_PER_WH),
        "return_time_min_median": float(np.median(r_t[np.isfinite(r_t)]) / 60),
        "within_30min_pct": float((r_t <= 1800).mean() * 100),
        "route_energy_wh": float(f_e[goal] / J_PER_WH), "route_time_min": t_route / 60,
        "route_length_m": length,
    }, nodes


def figure(results, path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    names = [n for n, _ in SCENARIOS if n != "nominal"]
    nom = results["nominal"]
    panels = [("return_energy_wh_median", "median return energy R_E (% change)"),
              ("route_energy_wh", "energy of the route to Nevado Sajama (% change)"),
              ("within_30min_pct", "box within 30 min (change, percentage points)")]
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.6), sharey=True)
    y = np.arange(len(names))[::-1]
    for ax, (key, title) in zip(axes, panels):
        if key == "within_30min_pct":
            vals = [results[n][key] - nom[key] for n in names]
        else:
            vals = [100 * (results[n][key] / nom[key] - 1) for n in names]
        ax.barh(y, vals, color="#4c78a8", height=0.6)
        ax.axvline(0, color="0.3", lw=0.8)
        ax.set_title(title, fontsize=9)
        ax.grid(axis="x", color="0.9"); ax.set_axisbelow(True)
        for yi, v in zip(y, vals):
            ax.text(v, yi, f" {v:+.0f}", va="center", ha="left" if v >= 0 else "right", fontsize=7)
        lo, hi = min(vals + [0]), max(vals + [0])
        pad = 0.25 * (hi - lo or 1)
        ax.set_xlim(lo - pad, hi + pad)
    axes[0].set_yticks(y)
    axes[0].set_yticklabels([f"{n}  (route {results[n]['route_within_5m_pct']:.0f} % within 5 m)"
                             for n in names], fontsize=8)
    fig.suptitle("E3 sensitivity: one parameter at a time from the nominal model "
                 "(Santee 2001, 124.2 kg, signed Apollo speed, g = 3.71, 30° cell block)", fontsize=9)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130, bbox_inches="tight")


def main():
    with rasterio.open(BASE / "dem_1m.tif") as src:
        dem = src.read(1).astype(np.float64); transform = src.transform
    with rasterio.open(BASE / "slope_deg.tif") as src:
        slope = src.read(1)
    cols = dem.shape[1]
    centre = (transform.c + cols / 2 * transform.a, transform.f + dem.shape[0] / 2 * transform.e)
    node = lambda xy: (lambda rc: rc[0] * cols + rc[1])(rasterio.transform.rowcol(transform, *xy))  # noqa: E731
    habitat, goal = node(centre), node(GOAL_XY)

    results, nodes = {}, {}
    for name, change in SCENARIOS:
        p = {**NOMINAL, **change}
        results[name], nodes[name] = run_scenario(p, dem, slope, transform, habitat, goal)
        print(f"{name:28s} R_E med {results[name]['return_energy_wh_median']:6.1f} Wh | "
              f"route {results[name]['route_energy_wh']:6.1f} Wh {results[name]['route_time_min']:5.1f} min | "
              f"30 min {results[name]['within_30min_pct']:5.1f} %")
    nominal_mask = np.ones(dem.size, bool)
    nominal_mask[list(nodes["nominal"])] = False
    dist_m = distance_transform_edt(nominal_mask.reshape(dem.shape))   # metres to the nominal route
    for name in results:
        cells = np.fromiter(nodes[name], int)
        results[name]["route_within_5m_pct"] = float((dist_m.flat[cells] <= 5).mean() * 100)
        results[name]["route_max_offset_m"] = float(dist_m.flat[cells].max())
    summary = {"nominal": NOMINAL, "habitat_xy": centre, "goal_xy": GOAL_XY,
               "scenarios": {n: {**c} for n, c in SCENARIOS}, "results": results}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2, default=float), encoding="utf-8")
    figure(results, OUT_FIG)
    print(f"-> {OUT_JSON}\n-> {OUT_FIG}")


if __name__ == "__main__":
    main()
