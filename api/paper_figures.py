"""Product figure for the paper (paper/notes/product_api_hud.md).

    python -m api.paper_figures

Writes paper/figures/product_fig1_redline_tour_radio.png and the numbers it shows in
data/product/product_fig1.json. Everything comes from the same code the API serves:
  (a) the 30 min red line (R_T = 1800 s, api/walkback.py) against the two fixed-radius
      rules, with the cells the circles call safe that are not, split into "no way back"
      (blocked or cut off) and "too slow" (detours);
  (b) the 120 min E5 tour of the saved stations (api/tour.py -> orienteering.plan_tour),
      with the habitat antenna's line-of-sight coverage and the stretches of the route
      with no direct radio (E11, api/comms.py).
Habitat at the box centre, cell block 30 degrees, human cost (E3 x E1 sand), 1000 Wh,
10 % margin. Needs data/base, data/stations (stations-v1) and, for (b), GDAL and E5.
"""

import json
import sys
from pathlib import Path

import numpy as np
import rasterio

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from api import planner, stations as st, tour, walkback as wb  # noqa: E402
from api.plan import PlanRequest  # noqa: E402

BASE = REPO / "data" / "base"
STATIONS = REPO / "data" / "stations"
OUT_PNG = REPO / "paper" / "figures" / "product_fig1_redline_tour_radio.png"
OUT_JSON = REPO / "data" / "product" / "product_fig1.json"
LIMIT_DEG, THRESHOLD_S, BUDGET_WH, MARGIN, DURATION_MIN = 30.0, 1800.0, 1000.0, 0.10, 120

# Colours validated with the dataviz palette checker (light mode, per panel, all pairs).
NO_WAY_BACK, TOO_SLOW, RED_LINE = "#6250d6", "#eda100", "#e34948"
ROUTE, NO_RADIO, COVERAGE = "#2a78d6", "#d55181", "#eda100"
INK, MUTED = "#222222", "#666666"


def hillshade(dem, az=315.0, alt=45.0, cell=1.0):
    dz_dy, dz_dx = np.gradient(np.nan_to_num(dem, nan=np.nanmean(dem)), cell)
    slope = np.arctan(np.hypot(dz_dx, dz_dy))
    aspect = np.arctan2(-dz_dx, dz_dy)
    a, z = np.radians(360.0 - az + 90.0), np.radians(90.0 - alt)
    hs = np.cos(z) * np.cos(slope) + np.sin(z) * np.sin(slope) * np.cos(a - aspect)
    return np.clip(hs, 0, 1)


def main():
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.lines import Line2D
    from matplotlib.patches import Patch

    with rasterio.open(BASE / "dem_1m.tif") as src:
        dem = src.read(1).astype(float)
        tr = src.transform
    rows, cols = dem.shape
    xmin, ymax = tr.c, tr.f
    xmax, ymin = xmin + cols * tr.a, ymax + rows * tr.e
    extent = (0, (xmax - xmin) / 1000, 0, (ymax - ymin) / 1000)        # km from the SW corner
    km = lambda xy: ((np.asarray(xy)[..., 0] - xmin) / 1000, (np.asarray(xy)[..., 1] - ymin) / 1000)  # noqa: E731
    centre = ((xmin + xmax) / 2, (ymin + ymax) / 2)
    shade = hillshade(dem)

    # ---- (a) red line against fixed radii ----
    g = wb.grid(str(BASE), LIMIT_DEG, True)
    base_node = g.node(*centre)
    r_t, _ = wb.return_fields(str(BASE), LIMIT_DEG, base_node, True)
    checks = wb.fixed_radius_check(g, r_t, centre, THRESHOLD_S)
    red = g.contour(r_t, THRESHOLD_S, base_node)
    xs = xmin + (np.arange(cols) + 0.5) * tr.a
    ys = ymax + (np.arange(rows) + 0.5) * tr.e
    dist = np.hypot(xs[None, :] - centre[0], ys[:, None] - centre[1])
    inside = dist <= min(c["radius_m"] for c in checks)
    no_way = inside & ~np.isfinite(r_t)
    slow = inside & np.isfinite(r_t) & (r_t > THRESHOLD_S)

    # ---- (b) the 120 min tour and its radio ----
    saved = st.load(STATIONS)
    rub = saved["rubric"]
    req = PlanRequest(start=list(centre), energy_budget_wh=BUDGET_WH, margin=MARGIN,
                      max_duration_min=DURATION_MIN, max_cell_slope_deg=LIMIT_DEG, human_cost=True,
                      stations=[{"id": s["id"], "x": s["x"], "y": s["y"], "type": s["type"],
                                 "score": rub[s["type"]], "service_time_min": s["service_time_min"]}
                                for s in saved["stations"]])
    fc, info = tour.plan_tour(req, BASE, planner.SERVICE_POWER_W)
    route = next(f for f in fc["features"] if f["properties"]["kind"] == "route")
    rp = route["properties"]
    coords = np.asarray(route["geometry"]["coordinates"])
    radio = None
    try:
        from api import comms
        grid_json = json.loads((BASE / "grid.json").read_text(encoding="utf-8"))
        creq = comms.CommsRequest(route={"coordinates": coords.tolist(), "t_s": rp["t_s"]},
                                  habitat=list(centre))
        radio = comms.check(str(BASE), creq, None, grid_json["bbox"],
                            (BASE / "crs.wkt").read_text(encoding="utf-8").strip())
        cover = comms.comms.line_of_sight(centre, str(BASE))
    except ImportError as err:                       # no GDAL: panel (b) without radio
        print(f"radio skipped: {err}")
        cover = None

    # ---- draw ----
    plt.rcParams.update({"font.size": 9, "axes.edgecolor": MUTED, "axes.labelcolor": INK,
                         "xtick.color": MUTED, "ytick.color": MUTED})
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 5.6), constrained_layout=True)
    for ax in (ax1, ax2):
        ax.imshow(shade[::2, ::2], cmap="gray", extent=extent, vmin=-0.3, vmax=1.2, interpolation="bilinear")
        ax.set_xlim(extent[0], extent[1]); ax.set_ylim(extent[2], extent[3])
        ax.set_xlabel("km east"); ax.set_aspect("equal")
    ax1.set_ylabel("km north")

    overlay = np.zeros((rows, cols, 4))
    for mask, colour in ((no_way, NO_WAY_BACK), (slow, TOO_SLOW)):
        overlay[mask] = matplotlib.colors.to_rgba(colour, 0.55)
    ax1.imshow(overlay[::2, ::2], extent=extent, interpolation="nearest")
    for line in red:
        x, y = km(line); ax1.plot(x, y, color=RED_LINE, lw=1.8)
    for c, ls in zip(checks, ("--", ":")):
        x, y = km(c["circle"]); ax1.plot(x, y, color=INK, lw=1.0, ls=ls)
    bx, by = km(np.array(centre)); ax1.plot(bx, by, marker="s", ms=7, color="white", mec=INK, mew=1.2)
    c0 = checks[0]
    ax1.set_title(f"(a) 30 min red line vs fixed radius: {c0['falsely_safe_pct']:.0f} % of the "
                  f"{c0['radius_m'] / 1000:.2f} km circle is falsely safe", loc="left", fontsize=9.5, color=INK)
    ax1.legend(handles=[
        Line2D([], [], color=RED_LINE, lw=1.8, label="R_T = 30 min (terrain-aware)"),
        Line2D([], [], color=INK, lw=1.0, ls="--", label=f"{checks[0]['radius_m'] / 1000:.2f} km (30 min at 0.75 m/s)"),
        Line2D([], [], color=INK, lw=1.0, ls=":", label=f"{checks[1]['radius_m'] / 1000:.2f} km (Apollo rule)"),
        Patch(color=NO_WAY_BACK, alpha=0.55, label=f"inside, no way back ({c0['falsely_safe_no_way_back_pct']:.1f} %)"),
        Patch(color=TOO_SLOW, alpha=0.55, label=f"inside, too slow ({c0['falsely_safe_too_slow_pct']:.1f} %)"),
        Line2D([], [], marker="s", color="white", mec=INK, ls="", label="habitat (box centre)")],
        loc="lower left", fontsize=7.5, framealpha=0.9)

    if cover is not None:
        cov = np.zeros((rows, cols, 4)); cov[cover] = matplotlib.colors.to_rgba(COVERAGE, 0.35)
        ax2.imshow(cov[::2, ::2], extent=extent, interpolation="nearest")
    x, y = km(coords); ax2.plot(x, y, color=ROUTE, lw=1.8, solid_capstyle="round")
    if radio is not None:
        for f in radio["features"]:
            if f["properties"].get("kind") == "no_radio":
                for line in f["geometry"]["coordinates"]:
                    lx, ly = km(line); ax2.plot(lx, ly, color=NO_RADIO, lw=3.2, solid_capstyle="round")
    order = {sid: k + 1 for k, sid in enumerate(info["visit_order"])}
    for s in saved["stations"]:
        sx, sy = km(np.array([s["x"], s["y"]]))
        visited = s["id"] in order
        ax2.plot(sx, sy, marker="o", ms=5.5, color=ROUTE if visited else "white", mec=INK, mew=0.8)
    # number the visiting order: each label pushed away from the stations' centre, so
    # crowded stations fan out instead of stacking
    pts = {sid: km(np.array([t["x"], t["y"]])) for t in saved["stations"] for sid in [t["id"]] if sid in order}
    cx_, cy_ = np.mean([v[0] for v in pts.values()]), np.mean([v[1] for v in pts.values()])
    for sid, k in order.items():
        sx, sy = pts[sid]
        ang = np.arctan2(sy - cy_, sx - cx_) if (sx, sy) != (cx_, cy_) else 0.0
        ax2.annotate(str(k), (sx, sy), xytext=(9 * np.cos(ang), 9 * np.sin(ang)), textcoords="offset points",
                     ha="center", va="center", fontsize=7.5, fontweight="bold", color=INK,
                     bbox=dict(boxstyle="round,pad=0.12", fc="white", ec="none", alpha=0.8))
    # zoom on the tour and the habitat (square, 120 m margin)
    allx = np.concatenate([x, [v[0] for v in pts.values()], [bx]])
    ally = np.concatenate([y, [v[1] for v in pts.values()], [by]])
    half = max(np.ptp(allx), np.ptp(ally)) / 2 + 0.12
    mx, my = (allx.min() + allx.max()) / 2, (ally.min() + ally.max()) / 2
    ax2.set_xlim(max(extent[0], mx - half), min(extent[1], mx + half))
    ax2.set_ylim(max(extent[2], my - half), min(extent[3], my + half))
    ax2.plot(bx, by, marker="s", ms=7, color="white", mec=INK, mew=1.2)
    one = radio["properties"]["single"] if radio else None
    title = (f"(b) {DURATION_MIN} min E5 tour: {len(order)} of {len(saved['stations'])} stations, "
             f"{rp['time_s'] / 60:.0f} min, {rp['energy_wh']:.0f} Wh")
    ax2.set_title(title, loc="left", fontsize=9.5, color=INK)
    handles = [Line2D([], [], color=ROUTE, lw=1.6, label="tour (numbers: visiting order)"),
               Line2D([], [], marker="o", color="white", mec=INK, ls="", label="station not visited")]
    if radio is not None:
        handles += [Patch(color=COVERAGE, alpha=0.35,
                          label=f"antenna line of sight ({radio['properties']['coverage'] * 100:.1f} % of box)"),
                    Line2D([], [], color=NO_RADIO, lw=3.2,
                           label=f"no direct radio ({one['length_m']:.0f} m, {one['fraction'] * 100:.0f} % of route)")]
    ax2.legend(handles=handles, loc="upper left", fontsize=7.5, framealpha=0.9)

    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(OUT_PNG, dpi=115)
    numbers = {
        "habitat": list(centre), "cell_block_deg": LIMIT_DEG, "threshold_s": THRESHOLD_S,
        "cost_model": g.cost_model,
        "fixed_radius": [{k: v for k, v in c.items() if k != "circle"} for c in checks],
        "tour": {"max_duration_min": DURATION_MIN, "budget_wh": BUDGET_WH, "margin": MARGIN,
                 "visit_order": info["visit_order"], "time_min": round(rp["time_s"] / 60, 1),
                 "energy_wh": rp["energy_wh"], "length_m": rp["length_m"], "engine": info.get("engine")},
        "radio": None if radio is None else {
            "coverage": radio["properties"]["coverage"], "single": one,
            "pair_unlinked": radio["properties"]["pair"]["unlinked"]},
    }
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(numbers, indent=1), encoding="utf-8")
    print(f"wrote {OUT_PNG} ({OUT_PNG.stat().st_size / 1024:.0f} KB) and {OUT_JSON}")


if __name__ == "__main__":
    main()
