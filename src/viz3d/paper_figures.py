"""Figures for the P1 paper note (paper/notes/P1_3d_map.md).

Run from the repo root:
    python src/viz3d/paper_figures.py [--data-dir data] [--only relief|sun]

Writes paper/figures/p1_fig1_relief_exaggeration.jpg: the local relief of a
600 x 600 m window shaded from the west, exaggerated 1, 3, 5 and 10 times, from the
raw 1 m DEM (top) and after the 3 m Gaussian used by the 3D map (bottom), next to
the orthophoto of the same window. It is the evidence for two choices of
build_terrain_assets.py: smoothing the local relief and capping the slider at x5.

Writes paper/figures/p1_fig2_sun_sol4711.png: elevation and azimuth of the Sun at the
box centre through Curiosity sol 4711, the default sol of the 3D map, and next to it
p1_fig2_sun_sol4711.json with the numbers quoted in the note. The Sun is computed by
the page's own code (web/3d/mars_sun.js, Mars24 algorithm), run with Node through
src/viz3d/sun_table.mjs: there is no second implementation here. Needs `node` on PATH.
"""

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import rasterio  # noqa: E402
from scipy import ndimage as ndi  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from viz3d.build_terrain_assets import DETAIL_SIGMA_M, LOW_SIGMA_M, slopes  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
FIG = REPO / "paper" / "figures"
WINDOW = (900, 700, 600)            # row, col, side (m): knolls, a scarp and boxwork
LIGHT_AZ_EL = (270.0, 35.0)         # from the west, 35 degrees above the horizon
KS = (1, 3, 5, 10)
SUN_SOL = 4711                      # default sol of the 3D map (web/3d/sun_model.js)
SUN_TIMES_H = (7, 12, 15, 17)       # local true solar times quoted in the note


def shade(d_east, d_north, k):
    """Lambert shading of a surface whose slopes are k times the given ones."""
    az, el = np.radians(LIGHT_AZ_EL)
    light = (np.sin(az) * np.cos(el), np.cos(az) * np.cos(el), np.sin(el))   # east, north, up
    nx, ny = -k * d_east, -k * d_north
    return np.clip((nx * light[0] + ny * light[1] + light[2]) / np.sqrt(nx * nx + ny * ny + 1), 0, 1)


def figure_relief(base):
    r0, c0, n = WINDOW
    with rasterio.open(base / "dem_1m.tif") as src:
        dem = src.read(1).astype(np.float64)
    with rasterio.open(base / "ortho_color_025.tif") as src:
        ortho = np.transpose(src.read(window=((r0 * 4, (r0 + n) * 4), (c0 * 4, (c0 + n) * 4)),
                                      out_shape=(3, n, n)), (1, 2, 0))
    raw = dem - ndi.gaussian_filter(dem, LOW_SIGMA_M, mode="reflect")
    smooth = ndi.gaussian_filter(raw, DETAIL_SIGMA_M, mode="reflect")
    win = (slice(r0, r0 + n), slice(c0, c0 + n))

    fig, axes = plt.subplots(2, len(KS) + 1, figsize=(15, 6.3), dpi=110)
    rows = ((f"1 m DEM minus hillside (raw)", raw),
            (f"same, Gaussian {DETAIL_SIGMA_M:g} m (used)", smooth))
    for r, (label, field) in enumerate(rows):
        d_east, d_north = slopes(field)
        for c, k in enumerate(KS):
            ax = axes[r, c]
            ax.imshow(shade(d_east[win], d_north[win], k), cmap="gray", vmin=0, vmax=1)
            ax.set_title(f"local relief ×{k}" + (" (not offered)" if k > 5 else ""), fontsize=10)
            if c == 0:
                ax.set_ylabel(label, fontsize=10)
    axes[0, -1].imshow(ortho)
    axes[0, -1].set_title("HiRISE orthophoto, same window", fontsize=10)
    axes[1, -1].axis("off")
    axes[1, -1].text(0.0, 0.95, f"Window {n} × {n} m, north up.\nLight from the west, "
                     f"{LIGHT_AZ_EL[1]:g}° high.\nHillside = Gaussian {LOW_SIGMA_M:g} m of the DEM.",
                     va="top", fontsize=10, transform=axes[1, -1].transAxes)
    for ax in axes.flat:
        ax.set_xticks([]); ax.set_yticks([])
    fig.tight_layout()
    FIG.mkdir(parents=True, exist_ok=True)
    out = FIG / "p1_fig1_relief_exaggeration.jpg"
    fig.savefig(out, pil_kwargs={"quality": 82})
    plt.close(fig)
    print(out, f"{out.stat().st_size / 1e6:.2f} MB")


def sun_table(base, sol):
    """Sun through a sol at the box centre: the JSON of src/viz3d/sun_table.mjs."""
    bbox = json.loads((base / "grid.json").read_text(encoding="utf-8"))["bbox"]
    x, y = (bbox["xmin"] + bbox["xmax"]) / 2, (bbox["ymin"] + bbox["ymax"]) / 2
    cmd = ["node", str(Path(__file__).with_name("sun_table.mjs")),
           "--sol", str(sol), "--x", repr(x), "--y", repr(y), "--step-min", "5"]
    return json.loads(subprocess.run(cmd, check=True, capture_output=True, text=True, cwd=REPO).stdout)


def figure_sun(base):
    table = sun_table(base, SUN_SOL)
    rows, site = table["rows"], table["site"]
    hours = np.array([r["hours"] for r in rows])
    elevation = np.array([r["elevation_deg"] for r in rows])
    # Bearing of the Sun as degrees east of north, -180 to 180. At this site and season
    # the Sun crosses the meridian to the north both at noon and (under the ground, less
    # than a degree from straight down) at midnight, so the curve has no jump: north,
    # east, north, west, north.
    bearing = np.array([(r["azimuth_deg"] + 180) % 360 - 180 for r in rows])
    rise, sunset = (c["hours"] for c in table["crossings"])
    key = {r["hours"]: r for r in table["key_times"]}
    noon_ls = key[12]["ls_deg"]

    ink, muted, line = "#1f2328", "#6b7280", "#b4530f"
    fig, (top, bottom) = plt.subplots(2, 1, figsize=(8.4, 6.2), dpi=130, sharex=True,
                                      gridspec_kw={"height_ratios": (1.15, 1), "hspace": 0.12})
    for ax in (top, bottom):
        for a, b in ((0, rise), (sunset, 24)):
            ax.axvspan(a, b, color="#e9ebee", lw=0)        # night: the Sun is below the horizon
        ax.grid(color="#d9dce1", lw=0.6)
        ax.set_axisbelow(True)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(muted)
        ax.tick_params(colors=muted, labelsize=9)

    top.axhline(0, color=muted, lw=0.8)
    top.plot(hours, elevation, color=line, lw=2)
    top.set_ylabel("Sun elevation (degrees)", color=ink, fontsize=10)
    top.set_ylim(-95, 95)
    top.set_yticks(range(-90, 91, 30))
    top.text(0.25, 4, "horizon", color=muted, fontsize=8.5, va="bottom")
    top.text(rise / 2, -84, "night", color=muted, fontsize=9, ha="center")
    top.text((sunset + 24) / 2, -84, "night", color=muted, fontsize=9, ha="center")
    bottom.plot(hours, bearing, color=line, lw=2)
    bottom.set_ylabel("Direction of the Sun (azimuth)", color=ink, fontsize=10)
    bottom.set_ylim(-125, 125)
    bottom.set_yticks((-90, 0, 90))
    bottom.set_yticklabels(("west 270°", "north 0°", "east 90°"))
    bottom.set_xlabel("Local true solar time at the box centre (hours)", color=ink, fontsize=10)
    bottom.set_xlim(0, 24)
    bottom.set_xticks(range(0, 25, 2))

    for h in SUN_TIMES_H:
        r = key[h]
        signed = (r["azimuth_deg"] + 180) % 360 - 180
        top.plot(h, r["elevation_deg"], "o", ms=7, color=line, mec="white", mew=1.5)
        bottom.plot(h, signed, "o", ms=7, color=line, mec="white", mew=1.5)
        left = h >= 15                                     # labels outside the curve, both sides of noon
        top.annotate(f"{h:02d}:00  {r['elevation_deg']:.1f}°", (h, r["elevation_deg"]),
                     xytext=(-9 if not left else 9, 0 if h != 12 else 7), textcoords="offset points",
                     ha="right" if not left else "left", va="center" if h != 12 else "bottom",
                     color=ink, fontsize=9)
        bottom.annotate(f"{r['azimuth_deg']:.1f}°", (h, signed), xytext=(9, 6), textcoords="offset points",
                        ha="left", va="bottom", color=ink, fontsize=9)

    top.set_title(f"Sun at the centre of the study box, Curiosity sol {table['sol']} "
                  f"({key[12]['utc'][:10]} UTC, Ls {noon_ls:.1f}°)", color=ink, fontsize=11, loc="left")
    fig.text(0.125, 0.012,
             f"{site['lon_east_deg']:.2f}° E, {abs(site['lat_planetographic_deg']):.2f}° S (planetographic). "
             "Mars24 algorithm (Allison and McEwen 2000), web/3d/mars_sun.js.\n"
             "Horizon of a smooth planet: no terrain, no refraction. "
             "At night the Sun passes within 1° of straight down.",
             color=muted, fontsize=7.5, va="bottom", linespacing=1.4)
    fig.subplots_adjust(left=0.125, right=0.97, top=0.93, bottom=0.135)
    FIG.mkdir(parents=True, exist_ok=True)
    out = FIG / f"p1_fig2_sun_sol{table['sol']}.png"
    fig.savefig(out)
    plt.close(fig)
    numbers = {k: table[k] for k in ("made_by", "sol", "site", "key_times", "crossings")}
    numbers["made_by"] = f"src/viz3d/paper_figures.py with {numbers['made_by']}"
    out.with_suffix(".json").write_text(json.dumps(numbers, indent=1) + "\n", encoding="utf-8")
    print(out, f"{out.stat().st_size / 1e6:.2f} MB")
    for r in table["key_times"] + table["crossings"]:
        print(f"  {r.get('what', ''):8s}{r['local_true_solar_time']}  {r['utc']}  elevation {r['elevation_deg']:7.2f}  "
              f"azimuth {r['azimuth_deg']:7.2f}  Ls {r['ls_deg']:.2f}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--data-dir", default=os.environ.get("MARTIAN_DATA", str(REPO / "data")))
    ap.add_argument("--only", choices=("relief", "sun"), help="draw one figure instead of both")
    args = ap.parse_args()
    base = Path(args.data_dir) / "base"
    if args.only != "sun":
        figure_relief(base)
    if args.only != "relief":
        figure_sun(base)


if __name__ == "__main__":
    main()
