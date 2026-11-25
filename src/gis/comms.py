"""E11 radio line of sight: habitat antenna, the route, and a pair of astronauts.

- Habitat coverage: GDAL ViewshedGenerate on data/base/dem_1m.tif, observer at the
  habitat cell with the antenna `antenna_h` m above the ground, target an astronaut's
  radio `astronaut_h` m above each cell. In memory (MEM driver), cached per habitat
  cell. Curvature coefficient 1.0 (no refraction: Mars' atmosphere is too thin to
  bend VHF/UHF noticeably); GDAL takes the radius from the DEM's sphere (3,396,190 m).
- Without GDAL's Python bindings (a plain pip install has none on Windows), the same
  viewshed is computed by `viewshed_numpy`, a NumPy port of GDAL 3.13's algorithm
  (alg/viewshed/viewshed_executor.cpp: normal output, Edge cell mode, curvature) with
  the same formulas in the same order, and the DEM is read with rasterio.
  tests/gis/test_comms.py checks that both give the same cells where GDAL is installed.
- Astronaut to astronaut: exact profile along the segment (bilinear DEM samples every
  0.5 m) with the same curvature bulge, so no viewshed per point.
- check_route: where on a route the astronaut has no direct radio to the habitat.
- check_pair: the second astronaut walks `gap_m` behind on the same route; a vertex is
  linked if both see the habitat, or one sees it and relays for the other (mutual
  line of sight). Separation is checked against `max_sep_m`.

Coordinates are metres in the DEM's Mars equirectangular CRS; distances along the
route are map metres (the x scale error at Gale's latitude, 1 - cos 4.8 deg, is 0.4 %).
"""

from functools import lru_cache
from pathlib import Path

import numpy as np

try:                     # GDAL's bindings come with conda (conda-forge gdal), not pip
    from osgeo import gdal
    gdal.UseExceptions()
except ImportError:      # NumPy port of the same viewshed, DEM read with rasterio
    gdal = None

ENGINE = "gdal" if gdal is not None else "numpy"

ANTENNA_H = 3.0          # m, habitat antenna mast above the ground
ASTRONAUT_H = 1.7        # m, suit radio above the ground (standing astronaut)
MARS_RADIUS_M = 3396190.0
CURV_COEFF = 1.0         # 1 - refraction coefficient; Mars: no refraction
PROFILE_STEP_M = 0.5


@lru_cache(maxsize=2)
def dem(base_dir):
    """(elevation float64 array, geotransform) of data/base/dem_1m.tif."""
    path = Path(base_dir) / "dem_1m.tif"
    if gdal is None:
        import rasterio
        with rasterio.open(path) as src:
            return src.read(1).astype(np.float64), tuple(src.transform.to_gdal())
    ds = gdal.Open(str(path))
    z = ds.GetRasterBand(1).ReadAsArray().astype(np.float64)
    return z, ds.GetGeoTransform()


def cell_of(gt, x, y, shape):
    """(row, col) of the cell containing (x, y); ValueError outside the grid."""
    col = int(np.floor((x - gt[0]) / gt[1]))
    row = int(np.floor((y - gt[3]) / gt[5]))
    if not (0 <= row < shape[0] and 0 <= col < shape[1]):
        raise ValueError(f"point ({x:.1f}, {y:.1f}) is outside the study box")
    return row, col


def cells_of(gt, x, y, shape):
    """Vectorised cell_of, clipped to the grid (route vertices are inside)."""
    col = np.clip(np.floor((np.asarray(x) - gt[0]) / gt[1]).astype(int), 0, shape[1] - 1)
    row = np.clip(np.floor((np.asarray(y) - gt[3]) / gt[5]).astype(int), 0, shape[0] - 1)
    return row, col


def viewshed_numpy(z, gt, row, col, antenna_h, astronaut_h, radius=MARS_RADIUS_M,
                   curv_coeff=CURV_COEFF):
    """bool[rows, cols] visibility from cell (row, col), as GDAL ViewshedGenerate.

    Port of GDAL 3.13 (normal output, GVM_Edge, curvature, no distance limits). Each
    cell's height is lowered by curv_coeff * r^2 / (2 R) and by the observer's height;
    then the sweep goes outwards from the observer. A cell is hidden when its height
    plus `astronaut_h` is below the horizon dfZ interpolated from the two cells next to
    it on the observer's side, and it carries max(height, dfZ) outwards. GDAL sweeps
    row by row; a cell off the diagonals depends only on cells one step closer in its
    own octant, so here the octants with |dx| < |dy| advance by rows and those with
    |dx| > |dy| by columns, one ring k at a time, vectorised along the ring."""
    fac = curv_coeff / (radius * 2.0)
    z_obs = antenna_h + z[row, col]
    yy = (np.arange(z.shape[0]) - row) * gt[5]
    xx = (np.arange(z.shape[1]) - col) * gt[1]
    h = z - (fac * (xx[None, :] ** 2 + yy[:, None] ** 2) + z_obs)
    vis = np.ones(z.shape, dtype=bool)

    def put(cur, dfz):                    # GDAL setOutputNormal: visibility, then max
        return ~(cur + astronaut_h < dfz), np.where(cur < dfz, dfz, cur)

    # The observer's row and column (GDAL: first line and initial position): CalcHeightLine.
    a_rows = {}
    for sy, sx, axis in ((0, 1, "r+"), (0, -1, "r-"), (1, 0, "c+"), (-1, 0, "c-")):
        n = (z.shape[1] - col if sx > 0 else col + 1) if sy == 0 else (z.shape[0] - row if sy > 0 else row + 1)
        line = np.empty(n)
        line[0] = h[row, col]
        for k in range(1, n):
            r, c = row + sy * k, col + sx * k
            cur = h[r, c]
            if k == 1:
                dfz = cur                    # next to the observer: visible
            else:
                dfz = line[k - 1] * k / (k - 1)
            vis[r, c] = not (cur + astronaut_h < dfz)
            line[k] = dfz if cur < dfz else cur
        a_rows[axis] = line
    vis[row, col] = True
    # The four quadrants, each seen from the observer: a[i, j] is the carried height
    # i rows and j columns away; row 0 and column 0 are the observer's row and column.
    for (sy, sx) in ((1, 1), (1, -1), (-1, 1), (-1, -1)):
        rs = np.arange(row, z.shape[0]) if sy > 0 else np.arange(row, -1, -1)
        cs = np.arange(col, z.shape[1]) if sx > 0 else np.arange(col, -1, -1)
        hq = h[np.ix_(rs, cs)]
        ni, nj = hq.shape
        a = np.full(hq.shape, np.nan)
        vq = np.ones(hq.shape, dtype=bool)
        a[0, :] = a_rows["r+" if sx > 0 else "r-"]
        a[:, 0] = a_rows["c+" if sy > 0 else "c-"]
        for k in range(1, max(ni, nj)):
            if k < ni and k < nj:            # diagonal |dx| == |dy| == k
                cur = hq[k, k]
                dfz = cur if k == 1 else a[k - 1, k - 1] * k / (k - 1)
                vq[k, k] = not (cur + astronaut_h < dfz)
                a[k, k] = dfz if cur < dfz else cur
            if k < ni and k > 1:             # row k, 0 < j < k: |dx| < |dy|
                j = np.arange(1, min(k, nj))
                if j.size:
                    dfz = (a[k - 1, j - 1] * j + a[k - 1, j] * (k - j)) / (k - 1)
                    vq[k, j], a[k, j] = put(hq[k, j], dfz)
            if k < nj and k > 1:             # column k, 0 < i < k: |dx| > |dy|
                i = np.arange(1, min(k, ni))
                if i.size:
                    dfz = (a[i - 1, k - 1] * i + a[i, k - 1] * (k - i)) / (k - 1)
                    vq[i, k], a[i, k] = put(hq[i, k], dfz)
        inner = vq[1:, 1:]
        vis[np.ix_(rs[1:], cs[1:])] = inner
    return vis


@lru_cache(maxsize=16)
def _viewshed(base_dir, row, col, antenna_h, astronaut_h):
    if gdal is None:
        z, gt = dem(base_dir)
        vis = viewshed_numpy(z, gt, row, col, antenna_h, astronaut_h)
        vis.setflags(write=False)
        return vis
    ds = gdal.Open(str(Path(base_dir) / "dem_1m.tif"))
    gt = ds.GetGeoTransform()
    ox, oy = gt[0] + (col + 0.5) * gt[1], gt[3] + (row + 0.5) * gt[5]
    out = gdal.ViewshedGenerate(
        ds.GetRasterBand(1), "MEM", "", [], ox, oy, antenna_h, astronaut_h,
        1.0, 0.0, 0.0, 0.0, CURV_COEFF, gdal.GVM_Edge, 0.0)
    vis = out.GetRasterBand(1).ReadAsArray() > 0.5
    vis.setflags(write=False)
    return vis


def line_of_sight(habitat_xy, base_dir, antenna_h=ANTENNA_H, astronaut_h=ASTRONAUT_H):
    """bool[rows, cols]: True where an astronaut's radio sees the habitat antenna."""
    z, gt = dem(str(base_dir))
    row, col = cell_of(gt, *habitat_xy, z.shape)
    return _viewshed(str(base_dir), row, col, float(antenna_h), float(astronaut_h))


def _bilinear(z, gt, x, y):
    """DEM elevation at points, bilinear between cell centres (edges clamped)."""
    u = (np.asarray(x) - gt[0]) / gt[1] - 0.5
    v = (np.asarray(y) - gt[3]) / gt[5] - 0.5
    u = np.clip(u, 0, z.shape[1] - 1.000001)
    v = np.clip(v, 0, z.shape[0] - 1.000001)
    c0, r0 = np.floor(u).astype(int), np.floor(v).astype(int)
    fu, fv = u - c0, v - r0
    top = z[r0, c0] * (1 - fu) + z[r0, c0 + 1] * fu
    bot = z[r0 + 1, c0] * (1 - fu) + z[r0 + 1, c0 + 1] * fu
    return top * (1 - fv) + bot * fv


def profile_los(z, gt, a_xy, b_xy, h_a=ASTRONAUT_H, h_b=ASTRONAUT_H, radius=MARS_RADIUS_M,
                step=PROFILE_STEP_M):
    """Line of sight between points a and b standing h_a / h_b m above the ground.

    The terrain between them is raised by the curvature bulge s (D - s) / (2 R) * coeff,
    which is the same geometry as GDAL's viewshed (target lowered by D^2 / 2R)."""
    (ax, ay), (bx, by) = a_xy, b_xy
    d = float(np.hypot(bx - ax, by - ay))
    if d < 2 * step:
        return True
    t = np.arange(1, int(np.ceil(d / step))) * (step / d)
    t = t[t < 1]
    za = _bilinear(z, gt, ax, ay) + h_a
    zb = _bilinear(z, gt, bx, by) + h_b
    ground = _bilinear(z, gt, ax + t * (bx - ax), ay + t * (by - ay))
    bulge = CURV_COEFF * (t * d) * ((1 - t) * d) / (2 * radius)
    return bool(np.all(ground + bulge < za + t * (zb - za)))


def _arc_length(xy):
    seg = np.hypot(*np.diff(xy, axis=0).T) if len(xy) > 1 else np.zeros(0)
    return np.concatenate([[0.0], np.cumsum(seg)])


def runs(bad, s, t_s=None, xy=None):
    """Continuous stretches where `bad` holds, on samples with arc length s (m) and
    optional time t_s (s). A step between two samples counts as bad if either end is
    bad (conservative). Returns (segments, summary)."""
    bad = np.asarray(bad, bool)
    n = len(bad)
    edge_bad = bad[:-1] | bad[1:] if n > 1 else np.zeros(0, bool)
    ds = np.diff(s)
    dt = np.diff(t_s) if t_s is not None else None
    segments = []
    i = 0
    while i < len(edge_bad):
        if not edge_bad[i]:
            i += 1
            continue
        j = i
        while j + 1 < len(edge_bad) and edge_bad[j + 1]:
            j += 1
        seg = {"start_m": round(float(s[i]), 1), "end_m": round(float(s[j + 1]), 1),
               "length_m": round(float(ds[i:j + 1].sum()), 1)}
        if dt is not None:
            seg.update(start_t_s=round(float(t_s[i]), 1), end_t_s=round(float(t_s[j + 1]), 1),
                       start_min=round(float(t_s[i]) / 60, 2),
                       end_min=round(float(t_s[j + 1]) / 60, 2),
                       duration_min=round(float(dt[i:j + 1].sum()) / 60, 2))
        if xy is not None:
            seg["coordinates"] = [[float(a), float(b)] for a, b in xy[i:j + 2]]
        segments.append(seg)
        i = j + 1
    total = float(s[-1]) if n else 0.0
    length = float(ds[edge_bad].sum()) if n > 1 else 0.0
    summary = {"segments": len(segments), "length_m": round(length, 1),
               "fraction": round(length / total, 4) if total > 0 else 0.0,
               "longest_m": max((g["length_m"] for g in segments), default=0.0)}
    if dt is not None:
        summary["duration_min"] = round(float(dt[edge_bad].sum()) / 60, 2)
        summary["longest_min"] = max((g["duration_min"] for g in segments), default=0.0)
    return segments, summary


def check_route(coords, habitat_xy, base_dir, t_s=None, antenna_h=ANTENNA_H,
                astronaut_h=ASTRONAUT_H):
    """Stretches of a route with no direct radio to the habitat (one astronaut)."""
    xy = np.asarray(coords, float).reshape(-1, 2)
    t = None if t_s is None else np.asarray(t_s, float)
    if t is not None and len(t) != len(xy):
        raise ValueError("t_s must have one value per route vertex")
    vis = line_of_sight(habitat_xy, base_dir, antenna_h, astronaut_h)
    z, gt = dem(str(base_dir))
    rows, cols = cells_of(gt, xy[:, 0], xy[:, 1], z.shape)
    ok = vis[rows, cols]
    s = _arc_length(xy)
    segments, summary = runs(~ok, s, t, xy)
    return {"radio_ok": ok.tolist(), "segments": segments,
            "summary": {**summary, "route_length_m": round(float(s[-1]), 1),
                        "route_duration_min": None if t is None else round(float(t[-1]) / 60, 2)}}


def check_pair(coords, habitat_xy, base_dir, t_s=None, gap_m=20.0, max_sep_m=100.0,
               antenna_h=ANTENNA_H, astronaut_h=ASTRONAUT_H, step_m=1.0):
    """Two astronauts on the same route, B `gap_m` behind A (along the route).

    Samples every `step_m` of the pair's progress p in [0, L + gap]: A at min(p, L)
    (waiting at the habitat at the end), B at clip(p - gap, 0, L) (waiting at the
    habitat at the start). Time: A's t(p) until A arrives, then B's walk time.

    `vertex_state` has one entry per route vertex (A standing on it): "direct" (both
    see the habitat), "relay" (only one does, and passes the link to the other) or
    "none" (the pair has no link)."""
    xy = np.asarray(coords, float).reshape(-1, 2)
    s = _arc_length(xy)
    L = float(s[-1])
    t = None if t_s is None else np.asarray(t_s, float)
    if t is not None and len(t) != len(xy):
        raise ValueError("t_s must have one value per route vertex")
    gap = float(gap_m)
    p = np.unique(np.concatenate([np.arange(0.0, L + gap, step_m), [L + gap], s]))
    sa, sb = np.minimum(p, L), np.clip(p - gap, 0.0, L)
    at = lambda q: np.column_stack([np.interp(q, s, xy[:, 0]), np.interp(q, s, xy[:, 1])])
    a, b = at(sa), at(sb)
    if t is None:
        time = None
    else:
        ta, tb = np.interp(sa, s, t), np.interp(sb, s, t)
        tb_arrive = float(np.interp(max(L - gap, 0.0), s, t))
        time = np.where(p <= L, ta, float(t[-1]) + (tb - tb_arrive))

    vis = line_of_sight(habitat_xy, base_dir, antenna_h, astronaut_h)
    z, gt = dem(str(base_dir))
    ra, ca = cells_of(gt, a[:, 0], a[:, 1], z.shape)
    rb, cb = cells_of(gt, b[:, 0], b[:, 1], z.shape)
    a_ok, b_ok = vis[ra, ca], vis[rb, cb]
    sep = np.hypot(*(a - b).T)
    need = a_ok ^ b_ok                                  # only then the relay matters
    mutual = np.ones(len(p), bool)
    for i in np.flatnonzero(need):
        mutual[i] = profile_los(z, gt, a[i], b[i], astronaut_h, astronaut_h)
    linked = (a_ok & b_ok) | (need & mutual & (sep <= max_sep_m))
    relay = linked & need
    sep_bad = sep > max_sep_m

    unlinked_seg, unlinked = runs(~linked, p, time, a)
    _, relay_sum = runs(relay, p, time)
    sep_seg, sep_sum = runs(sep_bad, p, time, a)
    _, a_alone = runs(~a_ok, p, time)
    _, b_alone = runs(~b_ok, p, time)
    for g in sep_seg:
        g.pop("coordinates", None)
    at_vertex = np.searchsorted(p, s)                    # p contains every vertex's s
    state = np.where(~linked, "none", np.where(relay, "relay", "direct"))[at_vertex]
    return {
        "vertex_state": state.tolist(),
        "gap_m": gap, "max_separation_m": float(max_sep_m),
        "max_separation_seen_m": round(float(sep.max()), 1) if len(sep) else 0.0,
        "unlinked": unlinked, "unlinked_segments": unlinked_seg,
        "relay": relay_sum, "separation_exceeded": sep_sum,
        "separation_segments": sep_seg,
        "a_no_direct": a_alone, "b_no_direct": b_alone,
        "samples": len(p), "step_m": step_m,
    }


def coverage(habitat_xy, base_dir, antenna_h=ANTENNA_H, astronaut_h=ASTRONAUT_H):
    """Fraction of the box with direct radio to the habitat."""
    return float(line_of_sight(habitat_xy, base_dir, antenna_h, astronaut_h).mean())
