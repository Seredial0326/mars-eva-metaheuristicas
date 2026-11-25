"""E3 numbers and figure for the paper (paper/notes/E3_metabolic_cost.md).

Usage (repo root):
    python src/fisica/paper_figures.py
Inputs:  data/base/dem_1m.tif, data/base/slope_deg.tif (release base-grid-v2)
Outputs: data/e3/e3_summary.json   every number quoted in the note
         paper/figures/e3_fig1_power_and_cost_vs_slope.png
"""

import json
import sys
from math import cos, radians
from pathlib import Path

import numpy as np
import rasterio
from scipy.ndimage import label, uniform_filter

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / "src"))

from fisica.edge_cost import (NEIGHBOURS, SPEED_ZERO_SLOPE_DEG, _shifted,  # noqa: E402
                              edge_costs)
from fisica.metabolic import (G_EARTH, G_MARS, G_MOON, J_PER_WH, TOTAL_MASS_KG,  # noqa: E402
                              apollo_speed, liters_o2, santee_2001_power, segment_cost)

BASE = REPO / "data" / "base"
OUT_JSON = REPO / "data" / "e3" / "e3_summary.json"
OUT_FIG = REPO / "paper" / "figures" / "e3_fig1_power_and_cost_vs_slope.png"
m = TOTAL_MASS_KG


def pandolf_flat(body_kg=76.4, load_kg=47.8, v=0.75, eta=1.0):
    """Pandolf (1977) on flat ground, alternative branch (guide section 6)."""
    w, l = body_kg, load_kg
    return 1.5 * w + 2.0 * (w + l) * (l / w) ** 2 + eta * (w + l) * 1.5 * v ** 2


def cost_per_horizontal_m(alpha, signed=True):
    v = apollo_speed(alpha, signed)
    return santee_2001_power(m, v, alpha, G_MARS)[2] / (v * cos(radians(alpha)))


def model_numbers():
    flat = santee_2001_power(m, 0.75, 0, G_MARS)[2]
    pandolf = pandolf_flat()
    t1, e1 = segment_cost(4100, 0)
    t2, e2 = segment_cost(900, 10)
    sweep = np.round(np.arange(-20, 20.0001, 0.01), 2)
    out = {"flat_power_w": {"earth": santee_2001_power(m, 0.75, 0, G_EARTH)[2],
                            "moon": santee_2001_power(m, 0.75, 0, G_MOON)[2],
                            "mars": flat},
           "lunar_check": {"pandolf_flat_earth_w": pandolf,
                           "pandolf_total_scaling_moon_w": pandolf * G_MOON / G_EARTH,
                           "santee_flat_w": flat},
           "toy_5km": {"energy_kj": (e1 + e2) / 1000, "energy_wh": (e1 + e2) / J_PER_WH,
                       "o2_l": liters_o2(e1 + e2), "time_h": (t1 + t2) / 3600},
           "c_min_h": {}}
    for signed in (True, False):
        c = np.array([cost_per_horizontal_m(a, signed) for a in sweep])
        i = int(np.argmin(c))
        out["c_min_h"]["signed" if signed else "abs"] = {"j_per_m": float(c[i]),
                                                         "alpha_deg": float(sweep[i])}
    out["c_flat_h_j_per_m"] = cost_per_horizontal_m(0)
    return out


def all_edge_alphas(dem):
    """Signed slope of every edge, with no limit (for the statistics only)."""
    alphas = []
    for dr, dc in NEIGHBOURS:
        d_h = np.sqrt(2.0) if dr and dc else 1.0
        alphas.append(np.degrees(np.arctan((_shifted(dem, dr, dc) - dem) / d_h)))
    return np.stack(alphas)


def grid_numbers(dem, slope):
    signed_a = all_edge_alphas(dem)
    a = np.abs(signed_a)
    out = {"cell_slope_deg": {"mean": float(np.nanmean(slope)),
                              "pct_over_20": float(np.nanmean(slope > 20) * 100),
                              "pct_over_30": float(np.nanmean(slope > 30) * 100)},
           "edge_slope_deg": {"mean": float(np.nanmean(a)),
                              "pct_over_20": float(np.nanmean(a > 20) * 100),
                              "pct_over_30": float(np.nanmean(a > 30) * 100)},
           # climbs at or above 75 deg: Apollo speed <= 0 (negative time/energy)
           "uphill_edges_at_or_above_speed_zero": int(np.nansum(signed_a >= SPEED_ZERO_SLOPE_DEG)),
           "smoothing_pct_edges_over_20": {}}
    for k in (1, 3, 5):
        z = dem if k == 1 else uniform_filter(dem, k, mode="nearest")
        out["smoothing_pct_edges_over_20"][f"{k}m"] = float(
            np.nanmean(np.abs(all_edge_alphas(z)) > 20) * 100)

    for name, kwargs in {"edge_limit_only": {},
                         "edge_and_cell_block_30": {"cell_slope_deg": slope,
                                                    "max_cell_slope_deg": 30}}.items():
        _, e, _ = edge_costs(dem, **kwargs)
        walkable = np.isfinite(e).any(axis=0)
        lab, _ = label(walkable)
        largest = np.bincount(lab.ravel())[1:].max()
        out[name] = {"walkable_pct": float(walkable.mean() * 100),
                     "largest_4connected_pct": float(largest / walkable.size * 100),
                     "edge_energy_j": [float(np.nanmin(e)), float(np.nanmax(e))]}
    return out


def figure(path):
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    al = np.linspace(-30, 30, 601)
    comps = np.array([santee_2001_power(m, apollo_speed(a), a, G_MARS) for a in al])
    fig, ax = plt.subplots(1, 2, figsize=(11, 4.2))
    for axis in ax:
        axis.axvspan(-30, -20, color="0.9")
        axis.axvspan(20, 30, color="0.9")
        axis.axvline(0, color="0.6", lw=0.6)
        axis.set_xlabel("slope along the move, alpha (deg)")
    ax[0].plot(al, comps[:, 0], label="W_level")
    ax[0].plot(al, comps[:, 1], label="W_slope (g = 3.71 m/s²)")
    ax[0].plot(al, comps[:, 2], "k", lw=2, label="M = W_level + W_slope")
    ax[0].set_ylabel("metabolic power (W)")
    ax[0].set_title("(a) Santee 2001, Apollo speed (signed)")
    ax[0].legend(fontsize=8)
    for signed, style, lab in ((True, "-", "signed speed"), (False, "--", "|alpha| speed")):
        c = [cost_per_horizontal_m(a, signed) for a in al]
        ax[1].plot(al, c, style, label=lab)
        i = int(np.argmin(np.where(np.abs(al) <= 20, c, np.inf)))
        ax[1].plot(al[i], c[i], "o", color="C3" if signed else "C1")
    ax[1].axhline(cost_per_horizontal_m(0), color="0.5", lw=0.8, ls=":", label="flat")
    ax[1].set_ylabel("energy per horizontal metre (J/m)")
    ax[1].set_title("(b) cost per metre; dots = c_min,h in ±20°")
    ax[1].legend(fontsize=8)
    fig.text(0.5, -0.02, "Grey bands: |alpha| > 20 deg, removed from the graph (CSRM limit).",
             ha="center", fontsize=8)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=130, bbox_inches="tight")


def main():
    with rasterio.open(BASE / "dem_1m.tif") as src:
        dem = src.read(1).astype(np.float64)
    with rasterio.open(BASE / "slope_deg.tif") as src:
        slope = src.read(1).astype(np.float64)
    summary = {"model": model_numbers(), "grid": grid_numbers(dem, slope),
               "parameters": {"mass_kg": m, "g_mars": G_MARS, "max_slope_deg": 20,
                              "max_cell_slope_deg": 30, "apollo_speed": "signed"}}
    OUT_JSON.parent.mkdir(parents=True, exist_ok=True)
    OUT_JSON.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    figure(OUT_FIG)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
