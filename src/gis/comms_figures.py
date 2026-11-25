"""E11 numbers and figure for paper/notes/E11_comms.md.

    python src/gis/comms_figures.py

Inputs: data/base (base-grid-v2), data/stations (stations-v1), data/e1 (optional,
human cost). Plans the demo EVA live with E4 (api.planner.plan, same request as the
3D page's default plan: habitat at the box centre, saved stations, 1000 Wh, 120 min)
and checks it for one astronaut and for a pair. Writes data/comms/summary.json and
paper/figures/e11_fig1_radio.png.
"""

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from osgeo import gdal  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from gis import comms  # noqa: E402

BASE = REPO / "data" / "base"
OUT = REPO / "data" / "comms"
FIG = REPO / "paper" / "figures" / "e11_fig1_radio.png"
CENTRE = (8143537.49, -284463.08)
GAPS = [0, 5, 10, 20, 30, 50, 75, 100, 125, 150]

GOOD, WARN, CRIT = "#0ca30c", "#fab219", "#d03b3b"      # status palette
SERIES1, INK, INK2 = "#2a78d6", "#0b0b0b", "#52514e"


def demo_plan():
    from api import planner, stations as st
    from api.plan import PlanRequest
    saved = st.load(REPO / "data" / "stations")
    rubric = saved.get("rubric") or {}
    req = PlanRequest(
        start=CENTRE, energy_budget_wh=1000, margin=0.10, max_duration_min=120,
        max_cell_slope_deg=30,
        stations=[dict(id=s["id"], x=s["x"], y=s["y"], type=s.get("type"),
                       score=float(rubric.get(s.get("type"), 0)),
                       service_time_min=s.get("service_time_min") or 0)
                  for s in saved["stations"]])
    fc, info = planner.plan(req, BASE)
    route = next(f for f in fc["features"] if f["properties"]["kind"] == "route")
    return route, info


def viewshed_vs_profile(habitat, n=5000, seed=0):
    """Agreement of GDAL's viewshed with the exact profile on random cells."""
    z, gt = comms.dem(str(BASE))
    vis = comms.line_of_sight(habitat, BASE)
    r0, c0 = comms.cell_of(gt, *habitat, z.shape)
    obs = (gt[0] + (c0 + 0.5) * gt[1], gt[3] + (r0 + 0.5) * gt[5])
    rng = np.random.default_rng(seed)
    rc = rng.integers(0, z.shape[0], (n, 2))
    same = [comms.profile_los(z, gt, obs, (gt[0] + (c + 0.5) * gt[1], gt[3] + (r + 0.5) * gt[5]),
                              comms.ANTENNA_H, comms.ASTRONAUT_H) == vis[r, c] for r, c in rc]
    return float(np.mean(same))


def horizon_check():
    """Flat DEM in the team's CRS, observer and target 0.1 m high: GDAL's last visible
    cell must match the Mars horizon 2 sqrt(2 R h), not the Earth one."""
    srs = (BASE / "crs.wkt").read_text(encoding="utf-8")
    n = 4000
    ds = gdal.GetDriverByName("MEM").Create("", n, 1, 1, gdal.GDT_Float32)
    ds.SetGeoTransform((0, 1, 0, 0, 0, -1))
    ds.SetProjection(srs)
    ds.GetRasterBand(1).WriteArray(np.zeros((1, n), np.float32))
    out = gdal.ViewshedGenerate(ds.GetRasterBand(1), "MEM", "", [], 0.5, -0.5, 0.1, 0.1,
                                1, 0, 0, 0, comms.CURV_COEFF, gdal.GVM_Edge, 0.0)
    last = int(np.flatnonzero(out.GetRasterBand(1).ReadAsArray()[0] > 0).max())
    return {"gdal_last_visible_m": last,
            "mars_expected_m": round(2 * np.sqrt(2 * comms.MARS_RADIUS_M * 0.1), 1),
            "earth_expected_m": round(2 * np.sqrt(2 * 6378137.0 * 0.1), 1)}


def random_habitats(k=20, seed=0):
    grid = json.loads((BASE / "grid.json").read_text(encoding="utf-8"))["bbox"]
    rng = np.random.default_rng(seed)
    xs = rng.uniform(grid["xmin"] + 50, grid["xmax"] - 50, k)
    ys = rng.uniform(grid["ymin"] + 50, grid["ymax"] - 50, k)
    cov = [comms.coverage((x, y), BASE) for x, y in zip(xs, ys)]
    return {"n": k, "seed": seed, "coverage_mean": round(float(np.mean(cov)), 4),
            "coverage_min": round(float(np.min(cov)), 4),
            "coverage_max": round(float(np.max(cov)), 4)}


def main():
    OUT.mkdir(parents=True, exist_ok=True)
    route, info = demo_plan()
    coords = np.asarray(route["geometry"]["coordinates"])
    t_s = route["properties"]["t_s"]
    habitat = CENTRE
    single = comms.check_route(coords, habitat, BASE, t_s)
    pairs = {g: comms.check_pair(coords, habitat, BASE, t_s, gap_m=g) for g in GAPS}
    for p in pairs.values():
        p.pop("unlinked_segments")
        p.pop("separation_segments")

    summary = {
        "habitat": list(habitat), "antenna_h_m": comms.ANTENNA_H,
        "astronaut_h_m": comms.ASTRONAUT_H, "curvature_coeff": comms.CURV_COEFF,
        "coverage_centre": round(comms.coverage(habitat, BASE), 4),
        "coverage_random_habitats": random_habitats(),
        "demo_route": {"goal_station": info.get("goal_station"),
                       "vertices": len(coords), "single": single["summary"],
                       "single_segments": [{k: v for k, v in g.items() if k != "coordinates"}
                                           for g in single["segments"]]},
        "pair_by_gap_m": {str(g): {"unlinked": p["unlinked"], "relay_m": p["relay"]["length_m"],
                                   "separation_exceeded_m": p["separation_exceeded"]["length_m"],
                                   "max_separation_seen_m": p["max_separation_seen_m"]}
                          for g, p in pairs.items()},
        "checks": {"viewshed_vs_profile_agreement": viewshed_vs_profile(habitat),
                   "horizon": horizon_check()},
    }
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    figure(coords, habitat, single, summary)
    print(json.dumps(summary, indent=2))


def figure(coords, habitat, single, summary):
    z, gt = comms.dem(str(BASE))
    vis = comms.line_of_sight(habitat, BASE)
    hs = gdal.Open(str(BASE / "hillshade.tif")).ReadAsArray()
    extent = [0, 2000, 0, 2000]                              # km-free local metres
    lx = lambda x: x - gt[0]
    ly = lambda y: y - (gt[3] + gt[5] * z.shape[0])

    # Pair at 20 m: status per vertex of the leader (p <= L), for colouring the route.
    pair = comms.check_pair(coords, habitat, BASE, None, gap_m=20)
    s = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(coords, axis=0).T))])
    a_ok = np.asarray(single["radio_ok"])
    unl = np.zeros(len(coords), bool)
    for g in pair["unlinked_segments"]:
        unl |= (s >= g["start_m"]) & (s <= g["end_m"])
    state = np.where(a_ok, 0, np.where(unl, 2, 1))           # 0 direct, 1 relay, 2 none

    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12, 5.6), gridspec_kw={"width_ratios": [1.1, 1]})
    ax.imshow(hs, cmap="gray", extent=extent, vmin=0, vmax=255)
    over = np.zeros((*vis.shape, 4))
    over[vis] = matplotlib.colors.to_rgba(SERIES1, 0.35)
    ax.imshow(over, extent=extent)
    x, y = lx(coords[:, 0]), ly(coords[:, 1])
    for k, (col, lab) in enumerate([(GOOD, "direct radio"), (WARN, "relay via partner (20 m behind)"),
                                    (CRIT, "no link")]):
        m = state == k
        ax.scatter(x[m], y[m], s=3, c=col, label=lab, zorder=3, linewidths=0)
    ax.plot(lx(habitat[0]), ly(habitat[1]), marker="^", ms=10, mfc="white", mec=INK, zorder=4,
            ls="none", label="habitat antenna (3 m)")
    ax.set_xlim(0, 2000)
    ax.set_ylim(0, 2000)
    ax.set_xlabel("east (m)")
    ax.set_ylabel("north (m)")
    ax.set_title("(a) Radio line of sight from the habitat (blue: visible at 1.7 m)",
                 fontsize=10, loc="left", color=INK)
    from matplotlib.lines import Line2D
    handles = [Line2D([], [], color=c, lw=3, label=l) for c, l in
               [(GOOD, "direct radio"), (WARN, "relay via partner (20 m behind)"), (CRIT, "no link")]]
    handles.append(Line2D([], [], marker="^", ms=9, mfc="white", mec=INK, ls="none",
                          label="habitat antenna (3 m)"))
    ax.legend(handles=handles, loc="lower left", fontsize=8, framealpha=0.9)

    gaps = np.array(GAPS)
    unl_m = [summary["pair_by_gap_m"][str(g)]["unlinked"]["length_m"] for g in GAPS]
    alone = summary["demo_route"]["single"]["length_m"]
    bx.axhline(alone, color=INK2, lw=2, ls="--")
    bx.text(0, alone + 20, f"one astronaut: {alone:.0f} m", fontsize=9, color=INK2)
    bx.plot(gaps, unl_m, color=SERIES1, lw=2, marker="o", ms=5)
    bx.text(gaps[3], min(unl_m) - 70, "pair, B behind A: no link", fontsize=9, color=INK)
    bx.axvline(100, color=INK2, lw=1, ls=":")
    bx.text(102, 120, "100 m pair\nseparation limit",
            fontsize=8, color=INK2)
    bx.set_xlabel("gap between the astronauts along the route (m)")
    bx.set_ylabel("route without radio link (m)")
    bx.set_ylim(0, max(max(unl_m), alone) * 1.15)
    bx.grid(axis="y", color="#e5e4e0", lw=0.8)
    for side in ("top", "right"):
        bx.spines[side].set_visible(False)
    bx.set_title("(b) Demo route: no-link length vs the pair's gap", fontsize=10, loc="left",
                 color=INK)
    fig.tight_layout()
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, dpi=150)


if __name__ == "__main__":
    main()
