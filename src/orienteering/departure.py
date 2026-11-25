"""
Best time to leave (P6, issue #45): for a planned EVA, which departure time keeps the
astronaut in sunlight for the most of the walk.

For each candidate departure (local true solar time on a given sol), the planned tour is
replayed with its own clock: vertex k is reached t_s[k] seconds after leaving (walking,
service and waits, as /plan gives them). At each vertex the Sun is placed in the sky
with Mars24, and the vertex is
    - dark       if the Sun is below the horizon of a smooth planet;
    - shadowed   if the Sun is up but below the terrain horizon seen from there (a ridge
                 or a crater wall between the astronaut and the Sun, from the 1 m DEM);
    - sunlit     otherwise.
Each vertex weighs the time until the next one, so a 10 min stop counts 10 min.
The recommended departure is the one with the largest sunlit share of the walk; ties go
to the one whose lowest Sun is highest (shorter shadows, better light), then to the
earliest.

The Sun: a line-by-line port of Juan's web/3d/mars_sun.js (P1, Mars24 algorithm of
[Allison2000]), so the 3D view and this module agree; tests/orienteering/test_departure.py
checks the port against that file with Node.

Times are local true solar time (the Sun's own clock, as the 3D view uses); each row also
gives the local mean solar time of the departure, the clock missions and REMS use.

Not modelled: temperature (the REMS feed gives each sol's minimum and maximum, not the
hour), refraction and the size of the solar disc, dust opacity, and shadows of rocks
smaller than the 1 m DEM resolves.

Usage, on a saved /plan answer (GET /plan/last, or the file the API keeps):
    python src/orienteering/departure.py --plan data/plans/last_plan.json --sol 4711
"""
import argparse
import json
import math
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REPO = Path(__file__).resolve().parents[2]
DEM_PATH = REPO / "data" / "base" / "dem_1m.tif"
MARS_R = 3396190.0                     # sphere of the DEM's CRS (base/crs.wkt)
EYE_M = 1.7                            # height of the astronaut's eyes and suit radio (as E11)
HORIZON_M = 400.0                      # how far the terrain horizon is searched
HORIZON_STEP_M = 2.0
AZIMUTH_BINS = 72                      # 5 degrees each

# ---- Mars24, ported from web/3d/mars_sun.js (equation numbers as there) ---------------
SOL_IN_DAYS = 1.0274912517
SOL_IN_SECONDS = SOL_IN_DAYS * 86400
MARS_FLATTENING = 1 - 3376.2 / 3396.19
MSL_CLOCK_LON_EAST = 137.42
MSL_SOL0_MSD = 49269
_LEAP_STEPS = [(915148800000, 32), (1136073600000, 33), (1230768000000, 34),
               (1341100800000, 35), (1435708800000, 36), (1483228800000, 37)]
_PERTURBERS = [(0.0071, 2.2353, 49.409), (0.0057, 2.7543, 168.173), (0.0039, 1.1177, 191.837),
               (0.0037, 15.7866, 21.736), (0.0021, 2.1354, 15.704), (0.0020, 2.4694, 95.528),
               (0.0018, 32.8493, 49.095)]


def _sind(a):
    return np.sin(np.radians(a))


def _cosd(a):
    return np.cos(np.radians(a))


def tt_minus_utc(utc_ms):
    """TT - UTC in seconds (A-4), from the leap seconds in force at the instant."""
    leap = _LEAP_STEPS[0][1]
    for start, s in _LEAP_STEPS:
        if utc_ms >= start:
            leap = s
    return 32.184 + leap


def mars_time(utc_ms, tt=None):
    """Mars time quantities of instants (UTC ms, scalar or array): ls, eot, msd, mtc,
    subsolar longitude west and declination (planetographic), in degrees and hours."""
    utc_ms = np.asarray(utc_ms, dtype=float)
    if tt is None:
        tt = tt_minus_utc(float(np.min(utc_ms)))
    dt = utc_ms / 86400000 - 10957.5 + tt / 86400                              # A-2, A-5, A-6
    m = 19.3871 + 0.52402073 * dt                                              # B-1
    alpha_fms = 270.3871 + 0.524038496 * dt                                    # B-2
    pbs = sum(a * _cosd(0.985626 * dt / tau + phi) for a, tau, phi in _PERTURBERS)  # B-3
    nu_minus_m = ((10.691 + 3.0e-7 * dt) * _sind(m) + 0.623 * _sind(2 * m) + 0.050 * _sind(3 * m)
                  + 0.005 * _sind(4 * m) + 0.0005 * _sind(5 * m) + pbs)         # B-4
    ls = np.mod(alpha_fms + nu_minus_m, 360)                                   # B-5
    eot = 2.861 * _sind(2 * ls) - 0.071 * _sind(4 * ls) + 0.002 * _sind(6 * ls) - nu_minus_m  # C-1
    msd = (dt - 4.5) / SOL_IN_DAYS + 44796.0 - 0.0009626                       # C-2
    mtc = np.mod(msd, 1) * 24
    subsolar_lon_west = np.mod(mtc * 15 + eot + 180, 360)                      # C-5
    declination = np.degrees(np.arcsin(0.42565 * _sind(ls))) + 0.25 * _sind(ls)  # D-1
    return {"ls": ls, "eot": eot, "msd": msd, "mtc": mtc,
            "subsolar_lon_west": subsolar_lon_west, "declination": declination}


def planetographic_latitude(planetocentric_deg):
    if abs(planetocentric_deg) >= 90:
        return math.copysign(90.0, planetocentric_deg)
    return math.degrees(math.atan(math.tan(math.radians(planetocentric_deg)) / (1 - MARS_FLATTENING) ** 2))


def sun_position(utc_ms, lat_deg, lon_east_deg, tt=None):
    """The Sun seen from a site (latitude planetographic): elevation and azimuth (compass
    bearing from north through east) in degrees, local mean and true solar time in hours."""
    t = mars_time(utc_ms, tt)
    h = np.mod(-lon_east_deg, 360) - t["subsolar_lon_west"]                    # D-5
    cos_z = (_sind(t["declination"]) * _sind(lat_deg)
             + _cosd(t["declination"]) * _cosd(lat_deg) * _cosd(h))
    zenith = np.degrees(np.arccos(np.clip(cos_z, -1, 1)))
    azimuth = np.mod(np.degrees(np.arctan2(_sind(h), _cosd(lat_deg) * np.tan(np.radians(t["declination"]))
                                           - _sind(lat_deg) * _cosd(h))), 360)  # D-6
    lmst = np.mod(t["mtc"] + lon_east_deg / 15, 24)
    return {"elevation": 90 - zenith, "azimuth": azimuth, "lmst": lmst,
            "ltst": np.mod(lmst + t["eot"] / 15, 24), "ls": t["ls"]}


def utc_of_msl_clock(sol, lmst_hours=0.0, tt=None):
    msd = sol + lmst_hours / 24 + MSL_SOL0_MSD - MSL_CLOCK_LON_EAST / 360

    def to_utc(seconds):
        return (((msd - 44796.0 + 0.0009626) * SOL_IN_DAYS + 4.5) - seconds / 86400 + 10957.5) * 86400000

    if tt is not None:
        return to_utc(tt)
    return to_utc(tt_minus_utc(to_utc(69.184)))


def true_solar_date(utc_ms, lon_east_deg, tt=None):
    t = mars_time(utc_ms, tt)
    return t["msd"] + lon_east_deg / 360 + t["eot"] / 360 - MSL_SOL0_MSD


def utc_of_true_solar_time(sol, ltst_hours, lon_east_deg, tt=None):
    """UTC instant (ms) at which, at a longitude, it is the given local true solar time of
    the given Curiosity sol (Newton steps on true_solar_date, as mars_sun.js)."""
    target = sol + ltst_hours / 24
    utc = utc_of_msl_clock(sol, ltst_hours, tt)
    for _ in range(4):
        utc += float(target - true_solar_date(utc, lon_east_deg, tt)) * SOL_IN_SECONDS * 1000
    return utc


# ---- the site and the terrain ------------------------------------------------------

def lon_lat(x, y):
    """Planetocentric longitude east and latitude (degrees) of a point of the DEM's
    equirectangular CRS (lon_0 = 0, lat_ts = 0, sphere of radius MARS_R)."""
    return math.degrees(x / MARS_R), math.degrees(y / MARS_R)


def horizon_table(xy, dem, transform, eye_m=EYE_M, max_m=HORIZON_M, step_m=HORIZON_STEP_M,
                  bins=AZIMUTH_BINS):
    """(n, bins) elevation angle (degrees) of the terrain horizon seen from each point at
    eye height, toward each azimuth bin (bin b is the direction b * 360 / bins degrees from
    north through east; light_along uses the nearest bin). -90 where nothing rises above
    the eye within max_m."""
    xy = np.asarray(xy, dtype=float)
    x0, res, y0 = transform[2], transform[0], transform[5]
    rows_n, cols_n = dem.shape
    dist = np.arange(step_m, max_m + step_m / 2, step_m)
    az = np.radians(np.arange(bins) * 360.0 / bins)
    dx = np.sin(az)[:, None] * dist[None, :]                                   # (bins, steps)
    dy = np.cos(az)[:, None] * dist[None, :]
    out = np.full((len(xy), bins), -90.0)
    for lo in range(0, len(xy), 128):
        block = xy[lo:lo + 128]
        c0 = np.floor((block[:, 0] - x0) / res).astype(int)
        r0 = np.floor((y0 - block[:, 1]) / -transform[4]).astype(int)
        z0 = dem[np.clip(r0, 0, rows_n - 1), np.clip(c0, 0, cols_n - 1)] + eye_m
        cols = np.floor((block[:, 0, None, None] + dx[None] - x0) / res).astype(int)
        rows = np.floor((y0 - (block[:, 1, None, None] + dy[None])) / -transform[4]).astype(int)
        inside = (rows >= 0) & (rows < rows_n) & (cols >= 0) & (cols < cols_n)
        z = dem[np.clip(rows, 0, rows_n - 1), np.clip(cols, 0, cols_n - 1)]
        angle = np.degrees(np.arctan2(z - z0[:, None, None], dist[None, None, :]))
        angle = np.where(inside & np.isfinite(z), angle, -90.0)
        out[lo:lo + 128] = angle.max(axis=2)
    return out


def load_dem(path=DEM_PATH):
    import rasterio
    with rasterio.open(path) as src:
        return src.read(1).astype(float), tuple(src.transform)[:6]


# ---- scoring -----------------------------------------------------------------------

def light_along(xy, t_s, sol, start_ltst, horizon, lat_pg, lon_east):
    """Per-vertex light for one departure: elevation, azimuth and state
    (0 dark, 1 shadowed by terrain, 2 sunlit)."""
    utc0 = utc_of_true_solar_time(sol, start_ltst, lon_east)
    sun = sun_position(utc0 + np.asarray(t_s, dtype=float) * 1000.0, lat_pg, lon_east,
                       tt=tt_minus_utc(utc0))
    elev, az = sun["elevation"], sun["azimuth"]
    return elev, az, light_state(elev, az, horizon), float(sun["ltst"][-1]), float(sun["lmst"][0])


def light_state(elev, az, horizon_rows=None):
    """0 dark (Sun below a smooth horizon), 1 shadowed (Sun below the terrain horizon in
    its direction, nearest bin), 2 sunlit, for Sun positions elev/az (degrees). Row k of
    horizon_rows is the terrain horizon (horizon_table) seen from where sample k is taken;
    None for a smooth planet."""
    elev, az = np.asarray(elev, dtype=float), np.asarray(az, dtype=float)
    state = np.full(elev.shape, 2)
    if horizon_rows is not None:
        bins = horizon_rows.shape[1]
        b = np.mod(np.floor(np.mod(az + 180.0 / bins, 360) / (360.0 / bins)).astype(int), bins)
        state[elev < horizon_rows[np.arange(len(elev)), b]] = 1
    state[elev <= 0] = 0
    return state


def score_departures(xy, t_s, sol, starts_ltst, horizon=None):
    """One row per candidate departure, the recommended one, and the window: the earliest
    and latest departures (among the candidates) with the whole walk in sunlight, or None.
    xy: (n, 2) route vertices in the DEM's CRS (the habitat first); t_s: (n,) seconds since
    leaving; horizon: horizon_table(xy, ...) or None for a smooth planet (no cast shadows)."""
    xy = np.asarray(xy, dtype=float)
    t_s = np.asarray(t_s, dtype=float)
    lon_east, lat_pc = lon_lat(*xy[0])
    lat_pg = planetographic_latitude(lat_pc)
    weight = np.r_[np.diff(t_s), 0.0]
    total = float(weight.sum()) or 1.0
    rows = []
    for start in starts_ltst:
        elev, _, state, end, start_lmst = light_along(xy, t_s, sol, start, horizon, lat_pg, lon_east)
        unlit = state < 2
        longest = run = 0.0
        for w, u in zip(weight, unlit):
            run = run + w if u else 0.0
            longest = max(longest, run)
        rows.append({"start_ltst_h": round(float(start), 3), "start_lmst_h": round(start_lmst, 3),
                     "end_ltst_h": round(end, 3),
                     "sunlit_share": round(float(weight[state == 2].sum()) / total, 4),
                     "shadow_share": round(float(weight[state == 1].sum()) / total, 4),
                     "dark_share": round(float(weight[state == 0].sum()) / total, 4),
                     "min_sun_elevation_deg": round(float(elev.min()), 2),
                     "longest_unlit_min": round(longest / 60.0, 1)})
    best = max(rows, key=lambda r: (r["sunlit_share"], r["min_sun_elevation_deg"], -r["start_ltst_h"]))
    lit = [r for r in rows if r["sunlit_share"] >= 1.0 - 1e-9]
    window = (lit[0]["start_ltst_h"], lit[-1]["start_ltst_h"]) if lit else None
    return rows, best, window


def tour_from_plan(plan):
    """(xy, t_s) of the route of a /plan answer (FeatureCollection, or {"plan": ...})."""
    fc = plan.get("plan", plan)
    route = next(f for f in fc["features"] if f["properties"].get("kind") == "route")
    return np.asarray(route["geometry"]["coordinates"], dtype=float)[:, :2], np.asarray(route["properties"]["t_s"], dtype=float)


def clock(hours):
    h = int(hours) % 24
    return f"{h:02d}:{int(round((hours - int(hours)) * 60)) % 60:02d}"


def main(argv=None):
    ap = argparse.ArgumentParser(description="Best departure time for a planned EVA (P6)")
    ap.add_argument("--plan", required=True, help="a saved /plan answer (JSON FeatureCollection)")
    ap.add_argument("--sol", type=int, default=4711, help="Curiosity sol of the EVA (4711: Nevado Sajama drill)")
    ap.add_argument("--from-h", type=float, default=5.0, help="earliest departure, local true solar time")
    ap.add_argument("--to-h", type=float, default=19.0, help="latest departure")
    ap.add_argument("--step-min", type=float, default=15.0)
    ap.add_argument("--no-terrain", action="store_true", help="ignore cast shadows (smooth planet)")
    ap.add_argument("--out", help="write the table as JSON")
    args = ap.parse_args(argv)

    xy, t_s = tour_from_plan(json.loads(Path(args.plan).read_text(encoding="utf-8")))
    horizon = None
    if not args.no_terrain:
        dem, transform = load_dem()
        horizon = horizon_table(xy, dem, transform)
    starts = np.arange(args.from_h, args.to_h + 1e-9, args.step_min / 60.0)
    rows, best, window = score_departures(xy, t_s, args.sol, starts, horizon)
    print(f"sol {args.sol}, EVA of {t_s[-1] / 60:.0f} min, {len(xy)} vertices"
          + (", terrain shadows from the 1 m DEM" if horizon is not None else ", no terrain"))
    print("leave   back    sunlit  shadow  dark   lowest Sun  longest unlit")
    for r in rows:
        mark = "  <- best" if r is best else ""
        print(f"{clock(r['start_ltst_h'])}  {clock(r['end_ltst_h'])}  {100 * r['sunlit_share']:5.1f} %"
              f"  {100 * r['shadow_share']:5.1f} %  {100 * r['dark_share']:5.1f} %  {r['min_sun_elevation_deg']:6.1f} deg"
              f"  {r['longest_unlit_min']:6.1f} min{mark}")
    print(f"best time to leave: {clock(best['start_ltst_h'])} local true solar time, "
          f"{clock(best['start_lmst_h'])} local mean solar time (the mission clock) "
          f"({100 * best['sunlit_share']:.1f} % of the walk in sunlight, lowest Sun {best['min_sun_elevation_deg']:.1f} deg)")
    if window:
        print(f"whole walk in sunlight for departures from {clock(window[0])} to {clock(window[1])}")
    else:
        print("no departure keeps the whole walk in sunlight")
    if args.out:
        Path(args.out).parent.mkdir(parents=True, exist_ok=True)
        Path(args.out).write_text(json.dumps({"sol": args.sol, "rows": rows, "best": best, "lit_window_ltst_h": window}, indent=1), encoding="utf-8")
    return rows, best, window


if __name__ == "__main__":
    main()
