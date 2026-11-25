"""E9 effect on the plan: what happens to round trips if boulder cover (rocas.tif)
is priced into the route cost?

    python src/dl_rocas/route_effect.py      -> data/e9/route_effect.json

Same graph as E4 (E3 arcs, 20 deg per move, cells > 30 deg blocked). Habitat = box
centre (snapped as in E4). Goals = the 13 manual stations + the 15 E8 contact
stations. For each goal, the minimum-cost round trip with arc energy

    E3 energy x (1 + k * cover(arrival cell)),    k in {0, 1, 3, 10}

k has no source: it is a sensitivity sweep (k = 0 is the E4 route). Reported per k,
against k = 0: true E3 energy and length of the round trip, number of route cells
with cover >= 0.25 (cells that are mostly boulder) and the summed cover along the
route (expected m^2 of boulder stepped on, 1 m cells). A route can change only
where an alternative with less rock costs little more.

X1 (#102): with --layer gp the price uses the GP layers of rocks_gp.py,
E3 x (1 + k * (rocks_mean + lam * rocks_std)), for lam in --lams (default 0 and
1.645, the one-sided 95 % bound), and the boulders stepped on are counted on the
teacher's cover (the GP's input) -> data/e9/route_effect_gp.json.
"""

import argparse
import json
import os
import sys
from pathlib import Path

os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np  # noqa: E402
import rasterio  # noqa: E402
import scipy.sparse as sp  # noqa: E402
from scipy.sparse.csgraph import dijkstra  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))
from grafos.graph import Graph, follow  # noqa: E402
from grafos.rock_risk import rock_factor  # noqa: E402

KS = (0.0, 1.0, 3.0, 10.0)
ROCKY = 0.25


def stations(graph, paths):
    import geopandas as gpd
    out = []
    for p in paths:
        if not Path(p).exists():
            continue
        for _, s in gpd.read_file(p, layer="stations").iterrows():
            try:
                r, c, _ = graph.place(s.geometry.x, s.geometry.y, label=s["id"])
            except ValueError:
                continue
            out.append((s["id"], s["type"], int(graph.node(r, c))))
    return out


def read(name):
    with rasterio.open(REPO / "data" / "e9" / name) as src:
        return src.read(1)


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--layer", choices=("rocas", "gp"), default="rocas")
    ap.add_argument("--lams", type=float, nargs="+", default=[0.0, 1.645])
    args = ap.parse_args()
    base = REPO / "data" / "base"
    graph = Graph.from_base_dir(base)
    main_cc = graph.main_component()
    hr, hc = graph.snap(graph.height // 2, graph.width // 2, mask=main_cc)
    hab = int(graph.node(hr, hc))
    if args.layer == "rocas":
        cover = np.nan_to_num(read("rocas.tif")).ravel()          # priced and counted
        cases = [(k, 0.0) for k in KS]
        price = {c: rock_factor(cover, None, c[0]) for c in cases}
    else:
        cover = np.nan_to_num(read("teacher_cover_1m.tif")).ravel()   # counted
        mean, std = read("rocks_mean.tif").ravel(), read("rocks_std.tif").ravel()
        cases = [(k, lam) for lam in args.lams for k in KS]
        price = {c: rock_factor(mean, std, c[0], c[1]) for c in cases}
    goals = stations(graph, [REPO / "data" / "stations" / "stations_manual.gpkg",
                             REPO / "data" / "stations" / "stations_e8.gpkg"])
    E = graph.csr("energy_j").tocoo()
    e3 = graph.csr("energy_j")
    length = graph.csr("length_m")

    def path_sum(m, path):
        return float(np.asarray(m[path[:-1], path[1:]]).sum())

    per_k = {}
    rows = []
    for k, lam in cases:
        w = sp.csr_matrix((E.data * price[(k, lam)][E.col], (E.row, E.col)), shape=E.shape)
        _, pred_out = dijkstra(w, indices=hab, return_predecessors=True)
        _, pred_back = dijkstra(w.T.tocsr(), indices=hab, return_predecessors=True)
        for gid, gtype, g in goals:
            if g == hab or pred_out[g] < 0 or pred_back[g] < 0:
                continue
            out = follow(pred_out, g, hab)[::-1]          # hab -> g
            back = follow(pred_back, g, hab)                # g -> hab (next hop to hab)
            path = np.concatenate([out, back[1:]])
            c = cover[path]
            rows.append(dict(k=k, lam=lam, goal=gid, type=gtype,
                             e3_wh=path_sum(e3, path) / 3600.0,
                             length_m=path_sum(length, path),
                             rocky_cells=int((c >= ROCKY).sum()),
                             boulder_m2=float(c.sum())))
    base_rows = {r["goal"]: r for r in rows if r["k"] == 0.0 and r["lam"] == cases[0][1]}
    for k, lam in cases:
        sel = [r for r in rows if r["k"] == k and r["lam"] == lam]
        d_e = [100 * (r["e3_wh"] / base_rows[r["goal"]]["e3_wh"] - 1) for r in sel]
        d_l = [r["length_m"] - base_rows[r["goal"]]["length_m"] for r in sel]
        key = str(k) if args.layer == "rocas" else f"k={k:g},lam={lam:g}"
        per_k[key] = dict(
            goals=len(sel),
            rocky_cells_total=int(sum(r["rocky_cells"] for r in sel)),
            boulder_m2_total=float(sum(r["boulder_m2"] for r in sel)),
            goals_touching_rocky_cells=int(sum(r["rocky_cells"] > 0 for r in sel)),
            e3_energy_change_pct_median=float(np.median(d_e)),
            e3_energy_change_pct_max=float(np.max(d_e)),
            length_change_m_median=float(np.median(d_l)),
            length_change_m_max=float(np.max(d_l)))
        v = per_k[key]
        print(f"k={k:4.1f} lam={lam:5.3f}: {v['goals']} goals, rocky cells on routes {v['rocky_cells_total']:4d} "
              f"({v['goals_touching_rocky_cells']} goals touch one), boulder m2 "
              f"{v['boulder_m2_total']:7.1f}, E3 energy +{v['e3_energy_change_pct_median']:.2f} % "
              f"median (max +{v['e3_energy_change_pct_max']:.2f} %), length "
              f"+{v['length_change_m_median']:.0f} m median (max +{v['length_change_m_max']:.0f} m)")
    out = dict(habitat_node=hab, k_values=list(KS), rocky_threshold=ROCKY, layer=args.layer,
               lams=sorted({lam for _, lam in cases}),
               counted_on="rocas.tif" if args.layer == "rocas" else "teacher_cover_1m.tif",
               note="k is a sensitivity sweep without a source; k=0 is the E4 route",
               box_rocky_share_of_main_component=float((cover[main_cc.ravel()] >= ROCKY).mean()),
               per_k=per_k, per_goal=rows)
    path = REPO / "data" / "e9" / ("route_effect.json" if args.layer == "rocas"
                                   else "route_effect_gp.json")
    path.write_text(json.dumps(out, indent=1), encoding="utf-8")
    print("wrote", path)


if __name__ == "__main__":
    main()
