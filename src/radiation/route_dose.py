"""E12 - Dose along the EVA timeline: time, energy and accumulated dose per route point.

Dose = dose rate x time outside. The rate comes from RAD (rad_data.py); the time
comes from walking the route with the E3 model (src/fisica, Sebas), plus the time
spent at each station.

Steps:
1. Steps of the route, two cases:
   - the route is a chain of neighbouring grid cells (what E4/E5 produce, vertices
     on cell centres): each step is one E3 edge, d_h = 1 or sqrt(2) m and
     alpha = atan(dz / d_h) between the two cells, exactly as fisica.edge_cost;
   - any other line (Curiosity's traverse): resampled every --step-m metres with
     the DEM read bilinearly. Same formulas, different sampling.
2. Time and energy of each step with E3 (Apollo speed, Santee 2001 power):
   dt = d_h / (V(alpha) cos alpha), E = P(alpha, V, g) dt.
3. Terrain factor eta (sensitivity; Santee has none, see sensitivity.py):
   mode "energy": E x eta, time unchanged (Pandolf-style surface factor);
   mode "speed":  V / eta, so time x eta and power at the slower speed.
   Applied where the optional --sand-raster is >= 0.5, or everywhere without it.
4. Stations: each one adds its service_time_min at the nearest route point (for an
   E5 tour, matched in visiting order).
5. Dose: constant boxwork background (default) or the real RAD series from
   --start-utc on, integrated exactly over the piecewise-linear series.
6. Return time to the HABITAT, a user input (return_time.py): return_s is the
   fastest walk back from E4's rv_time_s.tif (--return-raster) or, until it
   exists, from E12's provisional fallback. return_route_s is the walk back along
   the route itself (meaningful only when the route starts at the habitat).

Usage:
    python src/radiation/route_dose.py --habitat X Y [--route data/e5/tour_nominal.gpkg]
        [--out-and-back] [--stations FILE] [--return-raster data/e4/rv_time_s.tif]
        [--start-utc 2025-11-11T10:00:00Z] [--g 3.71] [--eta 1.0 --eta-mode energy]
        [--sand-raster FILE] [--step-m 1] [--every-m 5] [--out data/e12/route_dose.geojson]
Writes the GeoJSON (Point per output step) and <out>_summary.json.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import map_coordinates

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from fisica.edge_cost import SPEED_ZERO_SLOPE_DEG, santee_power_array  # noqa: E402
from fisica.metabolic import G_MARS, J_PER_WH, TOTAL_MASS_KG, apollo_speed  # noqa: E402
from radiation.common import (BASE, E2_OUTPUT, E12_OUTPUT, NOMINAL_COLUMN, Q_GCR, REPO,  # noqa: E402
                              SECONDS_PER_DAY, crs_wkt, pixel_coords, posix_seconds, rad_rate_csv)
from radiation.return_time import resolve_habitat, return_time_for  # noqa: E402

EDGE_SLOPE_LIMIT_DEG = 20.0     # E3/E4 planning limit; steps above it are only counted
LOOP_TOLERANCE_M = 5.0          # a route that ends this close to its start is a loop
MAX_STATION_DIST_M = 25.0       # stations farther than this from the route are ignored
CELL_CENTRE_TOL_M = 0.05        # vertices this close to cell centres count as a cell chain


# ----------------------------------------------------------------------------- route

def load_route(path):
    """First LineString of a route file (metres, DEM CRS) -> (N, 2) array; plus stations.

    - GeoJSON (the /plan output): stations are Point features with kind == "station"
      and an optional service_time_min.
    - E5 tour GeoPackage (src/orienteering/run.py --out): see load_e5_tour.
    """
    if Path(path).suffix.lower() == ".gpkg":
        return load_e5_tour(path)
    fc = json.loads(Path(path).read_text(encoding="utf-8"))
    line = next((f for f in fc["features"] if f["geometry"]["type"] == "LineString"), None)
    if line is None:
        raise SystemExit(f"{path}: no LineString feature")
    xy = np.asarray(line["geometry"]["coordinates"], dtype=float)[:, :2]
    stations = load_stations_fc(fc)
    return xy, stations


def load_stations_fc(fc):
    out = []
    for f in fc["features"]:
        p = f.get("properties") or {}
        if f["geometry"]["type"] == "Point" and p.get("kind", "station") == "station":
            x, y = f["geometry"]["coordinates"][:2]
            out.append({"id": p.get("id"), "x": float(x), "y": float(y),
                        "service_time_min": float(p.get("service_time_min") or 0.0)})
    return out


def load_e5_tour(path):
    """E5 tour GeoPackage (Diana, layers "route" and "stops") -> (N, 2) array, visited stations.

    The route layer holds the tour's cell path, habitat to habitat. The stops layer
    holds only the stations the tour visits, with their visiting "order" and
    service_time_min; the habitat stops (type "habitat") are not stations. The
    order is kept so that each station's service time lands on its visit (see
    station_indices), even where the tour passes the same cell again.
    """
    import geopandas as gpd
    line = gpd.read_file(path, layer="route").geometry
    if line.empty or line.iloc[0].geom_type != "LineString":
        raise SystemExit(f"{path}: layer 'route' has no LineString")
    xy = np.asarray(line.iloc[0].coords, dtype=float)[:, :2]
    stops = gpd.read_file(path, layer="stops").sort_values("order")
    stations = [{"id": r.id, "x": float(r.geometry.x), "y": float(r.geometry.y),
                 "service_time_min": float(r.service_time_min), "order": int(r.order)}
                for r in stops.itertuples() if str(r.type).lower() != "habitat"]
    return xy, stations


def load_stations(path):
    """Stations from a GeoJSON (Point features) or Sebas's stations_manual.gpkg."""
    path = Path(path)
    if path.suffix.lower() == ".gpkg":
        import geopandas as gpd
        gdf = gpd.read_file(path, layer="stations")
        return [{"id": r.id, "x": float(r.geometry.x), "y": float(r.geometry.y),
                 "service_time_min": float(r.service_time_min)} for r in gdf.itertuples()]
    return load_stations_fc(json.loads(path.read_text(encoding="utf-8")))


def repo_relative(path):
    """Path as text, relative to the repo when it is inside it (for the summaries)."""
    if path is None:
        return None
    p = Path(path).resolve()
    try:
        return p.relative_to(REPO).as_posix()
    except ValueError:
        return str(path)


def out_and_back(xy):
    """Close a one-way route by retracing it back to the start (EVA loop)."""
    return np.vstack([xy, xy[::-1][1:]])


def resample_line(xy, step_m):
    """Points every step_m metres (horizontal) along the polyline, ends included.

    Returns (points (M, 2), distance along the line (M,)). Zero-length segments
    (repeated vertices) are dropped first.
    """
    seg = np.diff(xy, axis=0)
    seg_len = np.hypot(seg[:, 0], seg[:, 1])
    keep = np.concatenate([[True], seg_len > 1e-9])
    xy = xy[keep]
    cum = np.concatenate([[0.0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    total = cum[-1]
    n = max(int(np.ceil(total / step_m)), 1)
    s = np.linspace(0.0, total, n + 1)
    x = np.interp(s, cum, xy[:, 0])
    y = np.interp(s, cum, xy[:, 1])
    return np.column_stack([x, y]), s


def sample_raster(path, xy, order=1):
    """Raster value at each (x, y): bilinear (order=1) or nearest cell (order=0).

    NaN outside the raster or next to a nodata cell. Within half a cell of the
    border the edge value is extended (a route vertex can sit on the box edge).
    """
    with rasterio.open(path) as src:
        a = src.read(1).astype(np.float64)
        if src.nodata is not None and np.isfinite(src.nodata):
            a[a == src.nodata] = np.nan
        inv = ~src.transform
    cols, rows = pixel_coords(inv, xy[:, 0], xy[:, 1])
    outside = (rows < 0) | (cols < 0) | (rows > a.shape[0]) | (cols > a.shape[1])
    # pixel (row, col) has its centre at index + 0.5 in the transform's space
    out = map_coordinates(a, np.vstack([rows - 0.5, cols - 0.5]), order=order, mode="nearest")
    out[outside] = np.nan
    return out


def cell_chain(xy, transform, shape, tol_m=CELL_CENTRE_TOL_M):
    """(rows, cols) if the polyline is a chain of 8-neighbour cells through cell centres, else None."""
    cols, rows = pixel_coords(~transform, xy[:, 0], xy[:, 1])
    r, c = np.floor(rows).astype(int), np.floor(cols).astype(int)
    if (r < 0).any() or (c < 0).any() or (r >= shape[0]).any() or (c >= shape[1]).any():
        return None
    cx = transform.c + (c + 0.5) * transform.a
    cy = transform.f + (r + 0.5) * transform.e
    if np.max(np.hypot(xy[:, 0] - cx, xy[:, 1] - cy)) > tol_m:
        return None
    keep = np.concatenate([[True], (np.diff(r) != 0) | (np.diff(c) != 0)])
    r, c = r[keep], c[keep]
    if len(r) < 2 or np.any(np.abs(np.diff(r)) > 1) or np.any(np.abs(np.diff(c)) > 1):
        return None
    return r, c


def route_steps(route_xy, dem_path, step_m=1.0):
    """Points, distances, elevations, step lengths and slopes of a route (see step 1)."""
    with rasterio.open(dem_path) as src:
        dem = src.read(1).astype(np.float64)
        transform = src.transform
    chain = cell_chain(route_xy, transform, dem.shape)
    if chain is not None:
        r, c = chain
        points = np.column_stack([transform.c + (c + 0.5) * transform.a, transform.f + (r + 0.5) * transform.e])
        z = dem[r, c]
        diagonal = (np.diff(r) != 0) & (np.diff(c) != 0)
        d_h = abs(transform.a) * np.where(diagonal, np.sqrt(2.0), 1.0)
        method = "e3_edges"
    else:
        points, dist = resample_line(route_xy, step_m)
        z = sample_raster(dem_path, points)
        d_h = np.diff(dist)
        method = f"resampled_{step_m:g}m"
    if np.isnan(z).any():
        raise SystemExit(f"{int(np.isnan(z).sum())} route points fall on DEM nodata or outside the DEM")
    alpha = np.degrees(np.arctan(np.diff(z) / d_h))
    return {"points": points, "dist": np.concatenate([[0.0], np.cumsum(d_h)]), "z": z,
            "d_h": d_h, "alpha": alpha, "method": method}


# ------------------------------------------------------------------------- walking

def step_costs(d_h, alpha_deg, g_mps2=G_MARS, mass_kg=TOTAL_MASS_KG, eta=None, eta_mode="energy",
               signed=True):
    """Time (s) and energy (J) of each step: the E3 edge formulas, vectorised.

    eta: None, a number or an array (one per step) >= 1; see the module docstring.
    """
    d_h = np.asarray(d_h, dtype=float)
    alpha = np.asarray(alpha_deg, dtype=float)
    if np.any(alpha >= SPEED_ZERO_SLOPE_DEG):
        raise ValueError(f"slope >= {SPEED_ZERO_SLOPE_DEG} deg: the Apollo speed is <= 0")
    eta_arr = np.ones_like(d_h) if eta is None else np.broadcast_to(np.asarray(eta, float), d_h.shape)
    v = apollo_speed(alpha, signed)
    if eta_mode == "speed":
        v = v / eta_arr
    elif eta_mode != "energy":
        raise ValueError("eta_mode must be 'energy' or 'speed'")
    dt = d_h / (v * np.cos(np.radians(alpha)))
    energy = santee_power_array(mass_kg, v, alpha, g_mps2) * dt
    if eta_mode == "energy":
        energy = energy * eta_arr
    return dt, energy


def station_indices(points, stations):
    """Index of the route point nearest to each station, and its distance (m).

    When every station has an "order" (an E5 tour), they are matched in that order,
    each one at or after the point of the previous one: a tour can pass a
    station's cell on another leg, and the service time belongs to the visit.
    """
    ordered = bool(stations) and all(s.get("order") is not None for s in stations)
    seq = sorted(range(len(stations)), key=lambda k: stations[k]["order"]) if ordered else range(len(stations))
    out = [None] * len(stations)
    lo = 0
    for k in seq:
        s = stations[k]
        d = np.hypot(points[lo:, 0] - s["x"], points[lo:, 1] - s["y"])
        i = lo + int(np.argmin(d))
        out[k] = (i, float(d[i - lo]))
        if ordered:
            lo = i
    return out


def walk(points, d_h, alpha, g_mps2=G_MARS, eta=None, eta_mode="energy", stations=(), mass_kg=TOTAL_MASS_KG,
         close_tol_m=LOOP_TOLERANCE_M, max_station_dist_m=MAX_STATION_DIST_M):
    """Timeline of the route: arrays with one value per point (d_h, alpha: one per step).

    Returns dict with t_s (elapsed time when LEAVING the point: walking plus every
    dwell up to and including this point), walk_s (walking time only), energy_j
    (cumulative walking energy), alpha_deg (slope of the step that ARRIVES at the
    point; 0 for the first), dwell_s (service time spent at the point) and
    return_route_s (walking time back to the route START along the route itself:
    retracing it, or, for a loop, the shorter of retracing and going on). eta may be
    one value per point; the value of the arriving point applies to each step.
    Stations farther than max_station_dist_m from the route are not visited
    (listed in "stations_ignored").
    """
    eta_used = eta if eta is None or np.isscalar(eta) else np.asarray(eta)[1:]
    dt, e = step_costs(d_h, alpha, g_mps2, mass_kg, eta_used, eta_mode)
    # walking back over the same step: same length, opposite slope
    dt_back, _ = step_costs(d_h, -np.asarray(alpha), g_mps2, mass_kg, eta_used, eta_mode)

    dwell = np.zeros(len(points))
    ignored = []
    for (i, d), s in zip(station_indices(points, stations), stations):
        if d > max_station_dist_m:
            ignored.append({"id": s.get("id"), "dist_to_route_m": round(d, 1)})
            continue
        dwell[i] += 60.0 * s["service_time_min"]
    walk_t = np.concatenate([[0.0], np.cumsum(dt)])
    t = walk_t + np.cumsum(dwell)          # dwell at point i happens on arrival at i
    return_route = np.concatenate([[0.0], np.cumsum(dt_back)])
    closed = bool(np.hypot(*(points[-1] - points[0])) <= close_tol_m)
    if closed:
        return_route = np.minimum(return_route, walk_t[-1] - walk_t)
    return {
        "t_s": t,
        "walk_s": walk_t,
        "dwell_s": dwell,
        "energy_j": np.concatenate([[0.0], np.cumsum(e)]),
        "alpha_deg": np.concatenate([[0.0], alpha]),
        "return_route_s": return_route,
        "closed": closed,
        "stations_ignored": ignored,
    }


# ---------------------------------------------------------------------------- dose

class DoseRate:
    """Absorbed dose rate in uGy/day as a function of UTC time.

    constant(rate): the same rate at any time.
    series(epochs, rates): piecewise-linear between RAD observations, constant
    beyond the ends. cumulative(t) integrates it exactly.
    """

    def __init__(self, t_s, rate, label):
        self.t_s = np.asarray(t_s, dtype=float)          # POSIX seconds
        self.rate = np.asarray(rate, dtype=float)        # uGy/day
        self.label = label
        seg = np.diff(self.t_s) * 0.5 * (self.rate[1:] + self.rate[:-1]) / SECONDS_PER_DAY
        self._cum = np.concatenate([[0.0], np.cumsum(seg)])   # uGy since t_s[0]

    @classmethod
    def constant(cls, rate_ugy_day):
        return cls([0.0, 1.0], [rate_ugy_day, rate_ugy_day], f"constant {rate_ugy_day:.2f} uGy/day")

    @classmethod
    def series(cls, csv_path=None, column=NOMINAL_COLUMN + "_ugy_day", drop_spikes=True):
        df = pd.read_csv(csv_path or rad_rate_csv())
        df = df[df["quality_ok"].astype(bool)]
        if drop_spikes:
            df = df[~df["spike"].astype(bool)]
        t = posix_seconds(df["utc"])
        return cls(t, df[column].to_numpy(), f"RAD series ({column})")

    def at(self, t):
        return np.interp(t, self.t_s, self.rate)

    def cumulative(self, t):
        """uGy accumulated from t_s[0] to t (works before/after the series too)."""
        t = np.asarray(t, dtype=float)
        inside = np.interp(t, self.t_s, self._cum)
        before = np.minimum(t - self.t_s[0], 0.0) * self.rate[0] / SECONDS_PER_DAY
        after = np.maximum(t - self.t_s[-1], 0.0) * self.rate[-1] / SECONDS_PER_DAY
        return inside + before + after

    def dose_between(self, t0, t1):
        return self.cumulative(t1) - self.cumulative(t0)


def background_rate(summary_path=None):
    """Nominal boxwork background (uGy/day) written by rad_data.py."""
    path = Path(summary_path) if summary_path else E12_OUTPUT / "rad_summary.json"
    if not path.exists():
        raise SystemExit("Missing data/e12/rad_summary.json. Run first:\n  python src/radiation/rad_data.py")
    return json.loads(path.read_text(encoding="utf-8"))["nominal"]["background_ugy_per_day"]


def route_timeline(route_xy, dem_path, dose_rate, start_utc=None, step_m=1.0, g_mps2=G_MARS,
                   eta=1.0, eta_mode="energy", sand_raster=None, stations=(), return_raster=None):
    """Full E12 timeline of one route as a DataFrame (one row per route point).

    return_raster: R_T raster (s) to the habitat; adds return_s (nearest cell).
    The table's attrs carry the step method ("e3_edges" or "resampled_<step>m").
    """
    st = route_steps(route_xy, dem_path, step_m)
    points = st["points"]
    eta_arg = eta
    if sand_raster is not None and eta != 1.0:
        sand = sample_raster(sand_raster, points, order=0)
        eta_arg = np.where(np.nan_to_num(sand) >= 0.5, eta, 1.0)
    w = walk(points, st["d_h"], st["alpha"], g_mps2, eta_arg, eta_mode, stations)
    if w["stations_ignored"]:
        print(f"{len(w['stations_ignored'])} station(s) farther than {MAX_STATION_DIST_M} m from the route "
              f"were ignored: {w['stations_ignored']}")
    t0 = 0.0 if start_utc is None else pd.Timestamp(start_utc).timestamp()
    t_abs = t0 + w["t_s"]
    dose = dose_rate.dose_between(t0, t_abs)
    tl = pd.DataFrame({
        "x": points[:, 0], "y": points[:, 1], "dist_m": st["dist"], "elev_m": st["z"],
        "alpha_deg": w["alpha_deg"], "t_s": w["t_s"], "walk_s": w["walk_s"], "dwell_s": w["dwell_s"],
        "energy_wh": w["energy_j"] / J_PER_WH,
        "rate_ugy_h": dose_rate.at(t_abs) / 24.0,
        "dose_ugy": dose, "dose_usv_est": dose * Q_GCR,
        "return_route_s": w["return_route_s"],
    })
    if return_raster is not None:
        tl["return_s"] = sample_raster(return_raster, points, order=0)
    tl.attrs["method"] = st["method"]
    return tl


def summarise(tl, dose_rate, args_dict, stations, habitat=None, return_info=None):
    steep = np.abs(tl["alpha_deg"].to_numpy()[1:]) > EDGE_SLOPE_LIMIT_DEG
    last = tl.iloc[-1]
    out = {
        "route": repo_relative(args_dict.get("route")),
        "stations_file": repo_relative(args_dict.get("stations")),
        "step_method": tl.attrs.get("method"),
        "habitat": habitat,
        "return_time": return_info,
        "dose_rate": dose_rate.label,
        "start_utc": args_dict.get("start_utc"),
        "g_mps2": args_dict.get("g"), "eta": args_dict.get("eta"), "eta_mode": args_dict.get("eta_mode"),
        "sand_raster": repo_relative(args_dict.get("sand_raster")),
        "step_m": args_dict.get("step_m"),
        "out_and_back": bool(args_dict.get("out_and_back")),
        "loop": bool(np.hypot(last["x"] - tl["x"].iloc[0], last["y"] - tl["y"].iloc[0]) <= LOOP_TOLERANCE_M),
        "length_m": round(float(last["dist_m"]), 1),
        "points": int(len(tl)),
        "stations_given": len(stations),
        "stations_visited": int((tl["dwell_s"] > 0).sum()),
        "eva_time_h": round(float(last["t_s"]) / 3600, 3),
        "walk_time_h": round(float(last["walk_s"]) / 3600, 3),
        "dwell_time_h": round(float(tl["dwell_s"].sum()) / 3600, 3),
        "mean_speed_mps": round(float(last["dist_m"] / last["walk_s"]), 3),
        "energy_wh": round(float(last["energy_wh"]), 1),
        "dose_ugy": round(float(last["dose_ugy"]), 2),
        "dose_usv_est": round(float(last["dose_usv_est"]), 1),
        "dose_ugy_per_km": round(float(last["dose_ugy"]) / (float(last["dist_m"]) / 1000), 2),
        "steps_steeper_than_edge_limit": int(steep.sum()),
        "steps_steeper_than_edge_limit_pct": round(100 * float(steep.mean()), 2),
        "alpha_abs_p95_deg": round(float(np.percentile(np.abs(tl["alpha_deg"]), 95)), 2),
        "quality_factor_estimate": Q_GCR,
        "units": {"coordinates": "m (DEM CRS)", "time": "s", "energy": "Wh", "dose": "uGy absorbed",
                  "dose_usv_est": "uSv, estimate = uGy x Q_GCR"},
    }
    if "return_s" in tl:
        out["max_return_time_h"] = round(float(np.nanmax(tl["return_s"])) / 3600, 3)
        out["points_without_return"] = int(tl["return_s"].isna().sum())
        if habitat is not None:
            out["route_starts_at_habitat"] = bool(np.hypot(tl["x"].iloc[0] - habitat["xy"][0],
                                                           tl["y"].iloc[0] - habitat["xy"][1]) <= LOOP_TOLERANCE_M)
    return out


def _round_or_none(v, nd):
    return None if not np.isfinite(v) else round(float(v), nd)


def to_geojson(tl, every_m, props):
    """Points every every_m metres (first and last always kept)."""
    keep = np.unique(np.concatenate([
        np.searchsorted(tl["dist_m"].to_numpy(), np.arange(0, tl["dist_m"].iloc[-1], every_m)),
        [len(tl) - 1]]))
    keep = np.unique(np.concatenate([keep, np.flatnonzero(tl["dwell_s"].to_numpy() > 0)]))
    feats = []
    for i in keep:
        r = tl.iloc[i]
        p = {"i": int(i), "dist_m": round(r.dist_m, 1), "t_s": round(r.t_s, 1), "elev_m": round(r.elev_m, 2),
             "energy_wh": round(r.energy_wh, 2), "rate_ugy_h": round(r.rate_ugy_h, 3),
             "dose_ugy": round(r.dose_ugy, 3), "dose_usv_est": round(r.dose_usv_est, 2),
             "dwell_s": round(r.dwell_s, 1), "return_route_s": round(r.return_route_s, 1)}
        if "return_s" in tl:
            p["return_s"] = _round_or_none(r.return_s, 1)
        feats.append({"type": "Feature",
                      "geometry": {"type": "Point", "coordinates": [round(r.x, 3), round(r.y, 3)]},
                      "properties": p})
    return {"type": "FeatureCollection", "crs": {"type": "name", "properties": {"name": crs_wkt()}},
            "properties": props, "features": feats}


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--route", default=str(E2_OUTPUT / "trajectory.geojson"),
                    help="GeoJSON with a LineString, or an E5 tour GeoPackage "
                         "(default: Curiosity's trajectory, the old provisional route)")
    ap.add_argument("--habitat", nargs=2, type=float, metavar=("X", "Y"),
                    help="habitat in DEM metres (the same input E4 uses); else taken from the route file")
    ap.add_argument("--out-and-back", action="store_true",
                    help="close a one-way route by walking it back to the start")
    ap.add_argument("--stations", help="GeoJSON or stations_manual.gpkg with service_time_min")
    ap.add_argument("--return-raster", help="E4's rv_time_s.tif (R(v) in seconds for the same habitat)")
    ap.add_argument("--dem", default=str(BASE / "dem_1m.tif"))
    ap.add_argument("--slope", default=str(BASE / "slope_deg.tif"), help="used by the return-time fallback")
    ap.add_argument("--start-utc", help="use the real RAD series from this time (default: constant background)")
    ap.add_argument("--g", type=float, default=G_MARS)
    ap.add_argument("--eta", type=float, default=1.0)
    ap.add_argument("--eta-mode", choices=["energy", "speed"], default="energy")
    ap.add_argument("--sand-raster", help="sand probability raster (E8); eta only where >= 0.5")
    ap.add_argument("--step-m", type=float, default=1.0, help="resampling step for lines that are not cell chains")
    ap.add_argument("--every-m", type=float, default=5.0, help="spacing of the output points")
    ap.add_argument("--out", type=Path, default=E12_OUTPUT / "route_dose.geojson")
    args = ap.parse_args()

    habitat_xy, habitat_source = resolve_habitat(args.habitat, args.route)
    xy, stations = load_route(args.route)
    if args.out_and_back:
        xy = out_and_back(xy)
    if args.stations:
        stations = load_stations(args.stations)
    ret_path, ret_info = return_time_for(habitat_xy, args.return_raster, args.dem, args.slope)
    rate = DoseRate.series() if args.start_utc else DoseRate.constant(background_rate())
    tl = route_timeline(xy, args.dem, rate, args.start_utc, args.step_m, args.g, args.eta,
                        args.eta_mode, args.sand_raster, stations, return_raster=ret_path)
    habitat = {"xy": [round(habitat_xy[0], 3), round(habitat_xy[1], 3)], "source": habitat_source}
    summary = summarise(tl, rate, vars(args), stations, habitat, ret_info)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(to_geojson(tl, args.every_m, summary)), encoding="utf-8")
    summary_path = args.out.with_name(args.out.stem + "_summary.json")
    summary_path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(f"{summary['length_m']} m, {summary['eva_time_h']} h, {summary['energy_wh']} Wh, "
          f"{summary['dose_ugy']} uGy (~{summary['dose_usv_est']} uSv); steps: {summary['step_method']}; "
          f"return time: {ret_info['source']}")
    print(f"wrote {args.out} and {summary_path.name}")


if __name__ == "__main__":
    main()
