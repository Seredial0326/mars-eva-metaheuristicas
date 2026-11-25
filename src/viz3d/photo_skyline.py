"""Compare Navcam skylines with the skyline of the 1 m DEM (P3 block 2 check).

Run ``python -m src.viz3d.photo_skyline --help`` from the repository root.

For each photo it uses the 768 px, 40-degree comparison image made by
build_rover_photos.py (same heading and pitch as the camera, zero roll, lens
distortion removed, transparent where the photo has no pixels) and:

1. ray-casts the DEM through every column of that pinhole frame and finds the
   topmost row whose ray meets terrain inside the 2 x 2 km box (curvature drop
   d^2/2R included). The grazing point is where the terrain's angle along that
   ray is largest. The skyline is an "in_box" feature when the grazing point is
   inside the box (a crest: the ray rises above the terrain behind it), and the
   "box_edge" when it lies within EDGE_MARGIN_M of the box boundary (the terrain
   still rises there and is only cut off, so the ray leaves the box before rising
   above it and the true skyline lies beyond the DEM);
2. finds the photo's own sky/ground boundary: the sky is the large smooth
   region connected to the top of the frame (gradient of the Gaussian-smoothed
   image below a threshold), scanned down each column, the boundary placed at the
   strongest vertical intensity step just below the end of that sky run;
3. compares both only where the DEM skyline is an in-box feature. The difference
   is DEM row minus photo row: negative means the DEM puts ground where the photo
   shows sky (an in-box disagreement); positive means the photo's skyline is
   higher, which can be farther terrain outside the box and is not an error.

Writes one figure per requested photo and a JSON with every number, plus an
aggregate over all selected photos within a pitch limit. Paths are explicit;
nothing is downloaded and the catalogue is only read.
"""
from __future__ import annotations

import argparse
import json
import math
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image  # noqa: E402
import rasterio  # noqa: E402
from scipy import ndimage  # noqa: E402

SCHEMA_VERSION = 1
SIZE = 768                              # comparison image side, pixels
FOV_DEG = 40.0                          # comparison image field of view
FOCAL_PX = (SIZE / 2) / math.tan(math.radians(FOV_DEG / 2))
MARS_RADIUS_M = 3_396_190.0             # sphere of the DEM CRS
STEP_M = 0.5                            # horizontal ray-marching step (DEM cell 1 m)
EDGE_MARGIN_M = 2.0                     # a grazing point this close to the box boundary is the box edge
SEARCH_TOP_ROW = -SIZE / 2              # the DEM search reaches half a frame above the image
BISECTION_STEPS = 16                    # (768 + 384) px / 2^16 = 0.02 px
COLUMN_CHUNK = 128
SKY_SIGMA_PX = 2.0                      # Gaussian smoothing before the gradient
SKY_MAX_GRADIENT = 1.5                  # grey levels per pixel; sky is smoother than this
SKY_MIN_AREA = 0.01                     # sky component: at least 1 % of the valid pixels
EDGE_RIM_PX = 2                         # ignored rim of the photo next to transparent pixels
REFINE_BELOW_PX = 6                     # search window for the boundary below the end of the sky run
MEDIAN_COLUMNS = 5                      # median filter across columns of the photo skyline
LIMIT_DEG = 1.0
HIDDEN_MIN_DEG = 0.5                    # photo skyline this far above an in-box crest: crest seen against terrain
HIDDEN_WINDOW_PX = 18                   # search +-18 px (about 1 degree) around the DEM crest
HIDDEN_TOLERANCE_PX = 3
ALIGN_SHIFT_PX = 60                     # offset search range, +-60 px (about +-3.3 degrees)
ALIGN_TOLERANCE_PX = 3.0


def camera_basis(heading, pitch):
    """Forward, image-right and image-down unit vectors in map east/north/up.

    Heading is clockwise from north and pitch positive below the horizon, both in
    radians, as in catalog.json; roll is zero (the comparison image removes it).
    """
    sh, ch, sp, cp = math.sin(heading), math.cos(heading), math.sin(pitch), math.cos(pitch)
    return (np.array([sh * cp, ch * cp, -sp]), np.array([ch, -sh, 0.0]),
            np.array([-sh * sp, -ch * sp, -cp]))


def column_offsets():
    """Ray coordinate a of each column centre: ray = forward + a*right + b*down."""
    return (np.arange(SIZE) + 0.5 - SIZE / 2) / FOCAL_PX


def row_to_b(row):
    return (np.asarray(row, dtype=float) + 0.5 - SIZE / 2) / FOCAL_PX


def depression_deg(row, a):
    """Angle of a row below the optical axis, measured inside its column."""
    return np.degrees(np.arctan2(row_to_b(row), np.sqrt(1 + np.asarray(a) ** 2)))


class Dem:
    """North-up float DEM with bilinear sampling between cell centres."""

    def __init__(self, path):
        with rasterio.open(path) as src:
            t = src.transform
            if t.b != 0 or t.d != 0 or t.a <= 0 or t.e >= 0:
                raise ValueError("The DEM must be a north-up grid")
            self.z = src.read(1).astype(np.float64)
            if src.nodata is not None and not np.isnan(src.nodata):
                self.z[self.z == src.nodata] = np.nan
            self.x0, self.y0, self.dx, self.dy = t.c, t.f, t.a, -t.e
            b = src.bounds
            self.bounds = (b.left, b.bottom, b.right, b.top)

    def sample(self, x, y):
        h, w = self.z.shape
        fc = np.clip((x - self.x0) / self.dx - 0.5, 0, w - 1)
        fr = np.clip((self.y0 - y) / self.dy - 0.5, 0, h - 1)
        c0 = np.minimum(fc.astype(np.int64), w - 2)
        r0 = np.minimum(fr.astype(np.int64), h - 2)
        tc, tr = fc - c0, fr - r0
        z = self.z
        return ((1 - tr) * ((1 - tc) * z[r0, c0] + tc * z[r0, c0 + 1])
                + tr * ((1 - tc) * z[r0 + 1, c0] + tc * z[r0 + 1, c0 + 1]))


def _exit_distance(cx, cy, ue, un, bounds):
    """Horizontal distance from an inside point to the box boundary along (ue, un)."""
    xmin, ymin, xmax, ymax = bounds
    with np.errstate(divide="ignore", invalid="ignore"):
        tx = np.where(ue > 0, (xmax - cx) / ue, np.where(ue < 0, (xmin - cx) / ue, np.inf))
        ty = np.where(un > 0, (ymax - cy) / un, np.where(un < 0, (ymin - cy) / un, np.inf))
    return np.minimum(tx, ty)


def _march(dem, camera, rays):
    """Clearance (m) of each ray above the curved terrain at horizontal steps.

    Returns horizontal distances (K,), clearance (n, K) with NaN beyond the box,
    and the exit distance of each ray. Terrain = DEM - d^2 / (2 R).
    """
    cx, cy, cz = camera
    h = np.hypot(rays[:, 0], rays[:, 1])
    ue, un, rise = rays[:, 0] / h, rays[:, 1] / h, rays[:, 2] / h
    d_exit = _exit_distance(cx, cy, ue, un, dem.bounds)
    d = np.arange(1, int(math.ceil(d_exit.max() / STEP_M)) + 1) * STEP_M
    terrain = (dem.sample(cx + d[None, :] * ue[:, None], cy + d[None, :] * un[:, None])
               - d[None, :] ** 2 / (2 * MARS_RADIUS_M))
    clearance = cz + d[None, :] * rise[:, None] - terrain
    clearance[d[None, :] > d_exit[:, None]] = np.nan
    return d, clearance, d_exit


def dem_skyline(dem, pose):
    """Topmost row whose ray meets terrain inside the box, for every column.

    Returns row (float, pixel-centre coordinates; NaN where undefined), kind
    ("in_box", "box_edge", "above_search" or "no_terrain") and the horizontal
    distance of the grazing point (m).
    """
    camera = (float(pose["x"]), float(pose["y"]), float(pose["z"]))
    forward, right, down = camera_basis(float(pose["heading"]), float(pose["pitch"]))
    a = column_offsets()

    def rays(cols, row):
        return forward + a[cols, None] * right + row_to_b(row)[:, None] * down

    def hits(row):
        out = np.zeros(SIZE, dtype=bool)
        for start in range(0, SIZE, COLUMN_CHUNK):
            cols = np.arange(start, min(start + COLUMN_CHUNK, SIZE))
            _, clearance, _ = _march(dem, camera, rays(cols, row[cols]))
            out[cols] = np.any(clearance <= 0, axis=1)
        return out

    lo = np.full(SIZE, SEARCH_TOP_ROW)
    hi = np.full(SIZE, SIZE - 0.5)
    hit_lo, hit_hi = hits(lo), hits(hi)
    for _ in range(BISECTION_STEPS):
        mid = (lo + hi) / 2
        hit = hits(mid)
        hi, lo = np.where(hit, mid, hi), np.where(hit, lo, mid)

    # The grazing point is where the terrain's angle seen along the final ray is
    # largest: minimum clearance / distance. A crest inside the box lets the ray
    # rise above the terrain behind it; a maximum at the box boundary means the
    # terrain was still rising there and the box edge sets the skyline.
    kind = np.full(SIZE, "box_edge", dtype=object)
    distance = np.full(SIZE, np.nan)
    for start in range(0, SIZE, COLUMN_CHUNK):
        cols = np.arange(start, min(start + COLUMN_CHUNK, SIZE))
        d, clearance, d_exit = _march(dem, camera, rays(cols, hi[cols]))
        angle_gap = np.where(np.isfinite(clearance), clearance / d[None, :], np.inf)
        graze = d[np.argmin(angle_gap, axis=1)]
        distance[cols] = graze
        kind[cols] = np.where(graze < d_exit - EDGE_MARGIN_M, "in_box", "box_edge")
    row = hi.copy()
    kind[hit_lo] = "above_search"
    kind[~hit_hi] = "no_terrain"
    row[hit_lo | ~hit_hi] = np.nan
    distance[hit_lo | ~hit_hi] = np.nan
    return row, kind, distance


def _gradients(image):
    """Grey image, valid mask and Sobel gradients (grey levels per pixel) after the Gaussian."""
    rgba = np.asarray(image.convert("RGBA"), dtype=float)
    if rgba.shape[:2] != (SIZE, SIZE):
        raise ValueError(f"Comparison image must be {SIZE} x {SIZE}")
    grey = rgba[..., :3].mean(axis=2)
    # The 2 px rim next to transparent pixels holds resampled frame-border artefacts.
    valid = ndimage.binary_erosion(rgba[..., 3] > 0, iterations=EDGE_RIM_PX, border_value=1)
    if not valid.all():
        if not valid.any():
            raise ValueError("Comparison image has no pixels")
        _, (ri, ci) = ndimage.distance_transform_edt(~valid, return_indices=True)
        grey = grey[ri, ci]
    smooth = ndimage.gaussian_filter(grey, SKY_SIGMA_PX)
    return grey, valid, ndimage.sobel(smooth, axis=0) / 8, ndimage.sobel(smooth, axis=1) / 8


def _peak(values):
    """Index of the maximum with a parabolic sub-sample offset."""
    k = int(np.argmax(values))
    if 0 < k < values.size - 1:
        y0, y1, y2 = values[k - 1], values[k], values[k + 1]
        denom = y0 - 2 * y1 + y2
        if denom < 0:
            return k + 0.5 * (y0 - y2) / denom
    return float(k)


def photo_skyline(image, debug_path=None):
    """Sky/ground boundary per column of a comparison image.

    Method: grey = mean of RGB; transparent pixels and an EDGE_RIM_PX rim next to
    them (resampled frame-border artefacts) take the nearest valid value (so they
    make no edges) and are otherwise ignored. After a Gaussian of
    SKY_SIGMA_PX, a pixel is smooth when its Sobel gradient is below
    SKY_MAX_GRADIENT grey levels per pixel. The sky is every smooth 4-connected
    component that touches the top row and holds at least SKY_MIN_AREA of the
    valid pixels (transparent pixels count as smooth for connectivity); islands
    enclosed by sky (stars, hot pixels, scraps of faint haze) are filled. Scanning
    each column down from its first valid pixel, the sky run ends at the first
    valid non-sky pixel; the boundary is the strongest vertical intensity step in
    the next REFINE_BELOW_PX rows (parabolic sub-pixel), then a median filter of
    MEDIAN_COLUMNS columns. Brightness is not assumed: the sky may be brighter
    or darker than the ground.

    Returns row (float, NaN when undefined) and status per column: "ok",
    "ground_at_top" (the skyline is above the frame or hidden), "no_ground",
    "no_pixels"; and the first valid row of each column.
    """
    grey, valid, gy, gx = _gradients(image)
    candidate = (np.hypot(gx, gy) < SKY_MAX_GRADIENT) | ~valid
    labels, _ = ndimage.label(candidate)
    top = np.unique(labels[0][labels[0] > 0])
    sky_labels = []
    if top.size:
        area = np.atleast_1d(ndimage.sum(valid, labels, index=top))
        sky_labels = top[area >= SKY_MIN_AREA * valid.sum()]
    # Islands enclosed by sky (stars, hot pixels, scraps of faint haze) become sky.
    sky = ndimage.binary_fill_holes(np.isin(labels, sky_labels)) & valid

    raw = np.full(SIZE, np.nan)
    status = np.full(SIZE, "ok", dtype=object)
    first_valid = np.full(SIZE, -1)
    for col in range(SIZE):
        rows_valid = np.flatnonzero(valid[:, col])
        if rows_valid.size == 0:
            status[col] = "no_pixels"
            continue
        first = rows_valid[0]
        first_valid[col] = first
        ground = np.flatnonzero(valid[first:, col] & ~sky[first:, col]) + first
        if ground.size == 0:
            status[col] = "no_ground"
            continue
        start = ground[0]
        if start == first:
            status[col] = "ground_at_top"
            continue
        window = np.arange(max(start - 1, first + 1), min(start + REFINE_BELOW_PX, SIZE - 1))
        # The centred difference of a smoothed step peaks between the last sky row
        # and the first ground row: the same pixel-centre convention as the DEM row.
        raw[col] = window[0] + _peak(np.abs(gy[window, col]))
    row = raw.copy()
    ok = status == "ok"
    half = MEDIAN_COLUMNS // 2
    for col in np.flatnonzero(ok):
        neighbours = raw[max(0, col - half):col + half + 1]
        row[col] = np.nanmedian(neighbours)
    if debug_path is not None:
        view = np.dstack([grey, grey, grey]).astype(np.uint8)
        view[sky] = (0.5 * view[sky] + [0, 0, 120]).astype(np.uint8)
        Image.fromarray(view).save(debug_path, quality=85)
    return row, status, first_valid


def _summary(values):
    values = np.asarray(values, dtype=float)
    if values.size == 0:
        return {"n": 0, "median_deg": None, "p90_deg": None, "max_deg": None}
    return {"n": int(values.size), "median_deg": round(float(np.median(values)), 3),
            "p90_deg": round(float(np.percentile(values, 90)), 3), "max_deg": round(float(values.max()), 3)}


def compare(dem_row, dem_kind, photo_row, photo_status, first_valid):
    """Per-column comparison where the DEM skyline is an in-box feature."""
    a = column_offsets()
    in_box = dem_kind == "in_box"
    ok = in_box & (photo_status == "ok")
    diff_px = np.where(ok, dem_row - photo_row, np.nan)
    diff_deg = np.where(ok, depression_deg(dem_row, a) - depression_deg(photo_row, a), np.nan)
    d = diff_deg[ok]
    dem_above, photo_above = -d[d < 0], d[d > 0]
    n = int(ok.sum())
    top_edge = first_valid - 0.5
    ground_top = in_box & (photo_status == "ground_at_top")
    censored = ground_top & (dem_row > top_edge)
    edge_ok = (dem_kind == "box_edge") & (photo_status == "ok")
    edge_deg = depression_deg(dem_row[edge_ok], a[edge_ok]) - depression_deg(photo_row[edge_ok], a[edge_ok])
    stats = {
        "columns": SIZE,
        "dem_kind_counts": {k: int(np.sum(dem_kind == k))
                            for k in ("in_box", "box_edge", "above_search", "no_terrain")},
        "photo_status_counts": {k: int(np.sum(photo_status == k))
                                for k in ("ok", "ground_at_top", "no_ground", "no_pixels")},
        "in_box_compared": n,
        "signed_median_deg": round(float(np.median(d)), 3) if n else None,
        "abs_median_deg": round(float(np.median(np.abs(d))), 3) if n else None,
        "abs_p90_deg": round(float(np.percentile(np.abs(d), 90)), 3) if n else None,
        "within_limit_fraction": round(float(np.mean(np.abs(d) <= LIMIT_DEG)), 4) if n else None,
        "dem_above_photo": {**_summary(dem_above),
                            "beyond_limit_fraction": round(float(np.sum(dem_above > LIMIT_DEG)) / n, 4) if n else None},
        "photo_above_dem": {**_summary(photo_above),
                            "beyond_limit_fraction": round(float(np.sum(photo_above > LIMIT_DEG)) / n, 4) if n else None},
        "in_box_photo_ground_at_top": {"censored_photo_above_dem": int(censored.sum()),
                                       "both_above_frame": int((ground_top & ~censored).sum())},
        "box_edge_compared": int(edge_ok.sum()),
        "box_edge_dem_above_photo_beyond_limit": int(np.sum(edge_deg < -LIMIT_DEG)),
    }
    return stats, diff_px, diff_deg


def hidden_crest_edges(image, dem_row, diff_deg):
    """Is an in-box crest seen against farther terrain marked by an intensity step?

    Where the photo skyline is more than HIDDEN_MIN_DEG above an in-box DEM
    skyline, the DEM crest should be a silhouette in front of farther terrain.
    For each such column, the strongest vertical step of the smoothed image within
    +-HIDDEN_WINDOW_PX of the DEM row is located (parabolic sub-pixel). If the crest
    is real and well placed, the steps cluster near zero offset; if the location
    were random, about (2*HIDDEN_TOLERANCE_PX+1)/(2*HIDDEN_WINDOW_PX+1) of the
    columns would fall within tolerance by chance. Offsets are edge row minus DEM
    row (positive: the edge in the photo is below the DEM line).
    """
    _, valid, gy, _ = _gradients(image)
    cols = np.flatnonzero(np.isfinite(diff_deg) & (diff_deg > HIDDEN_MIN_DEG) & np.isfinite(dem_row)
                          & (dem_row >= HIDDEN_WINDOW_PX + 1) & (dem_row <= SIZE - HIDDEN_WINDOW_PX - 2))
    offsets = []
    for col in cols:
        centre = int(round(dem_row[col]))
        window = np.arange(centre - HIDDEN_WINDOW_PX, centre + HIDDEN_WINDOW_PX + 1)
        if not valid[window, col].all():
            continue
        offsets.append(window[0] + _peak(np.abs(gy[window, col])) - dem_row[col])
    offsets = np.asarray(offsets)
    chance = (2 * HIDDEN_TOLERANCE_PX + 1) / (2 * HIDDEN_WINDOW_PX + 1)
    if offsets.size == 0:
        return {"n": 0, "chance_fraction": round(chance, 3)}
    deg = math.degrees(1 / FOCAL_PX)
    return {"n": int(offsets.size),
            "within_tolerance_fraction": round(float(np.mean(np.abs(offsets) <= HIDDEN_TOLERANCE_PX)), 4),
            "chance_fraction": round(chance, 3), "median_offset_px": round(float(np.median(offsets)), 2),
            "median_offset_deg": round(float(np.median(offsets) * deg), 3),
            "median_abs_offset_deg": round(float(np.median(np.abs(offsets)) * deg), 3)}


def alignment(dem_row, dem_kind, photo_row, photo_status):
    """Constant (horizontal, vertical) shift of the in-box DEM skyline that best fits the photo.

    Counts in-box columns where DEM row + dy lies within ALIGN_TOLERANCE_PX of the
    photo skyline at column + dx, for dx, dy in +-ALIGN_SHIFT_PX. A positive dx moves
    the DEM line right (photo features lie to the right of the model's); a positive
    dy moves it down. Reported with the score at zero shift; flat skylines make dx
    ambiguous, so the spread of near-best shifts (score >= 90 % of the best) is
    also given. Fractions are over the in-box columns with a photo skyline.
    """
    cols = np.flatnonzero(dem_kind == "in_box")
    compared = int(np.sum((dem_kind == "in_box") & (photo_status == "ok")))
    if compared < 20:
        return None
    shifts = np.arange(-ALIGN_SHIFT_PX, ALIGN_SHIFT_PX + 1)
    score = np.zeros((shifts.size, shifts.size))
    for i, dx in enumerate(shifts):
        target = cols + dx
        keep = (target >= 0) & (target < SIZE)
        src, dst = cols[keep], target[keep]
        okp = photo_status[dst] == "ok"
        src, dst = src[okp], dst[okp]
        if src.size == 0:
            continue
        resid = (dem_row[src][:, None] + shifts[None, :]) - photo_row[dst][:, None]
        score[i] = np.sum(np.abs(resid) <= ALIGN_TOLERANCE_PX, axis=0) / compared
    i, j = np.unravel_index(np.argmax(score), score.shape)
    zero = ALIGN_SHIFT_PX
    near = np.argwhere(score >= 0.9 * score[i, j])
    deg = math.degrees(1 / FOCAL_PX)  # 0.054 degree per pixel at the image centre
    return {"best_dx_px": int(shifts[i]), "best_dy_px": int(shifts[j]),
            "best_dx_deg": round(float(shifts[i] * deg), 2), "best_dy_deg": round(float(shifts[j] * deg), 2),
            "best_fraction": round(float(score[i, j]), 4), "zero_shift_fraction": round(float(score[zero, zero]), 4),
            "near_best_dx_px": [int(shifts[near[:, 0].min()]), int(shifts[near[:, 0].max()])],
            "near_best_dy_px": [int(shifts[near[:, 1].min()]), int(shifts[near[:, 1].max()])]}


def _rounded(values, digits=2):
    return [None if not np.isfinite(v) else round(float(v), digits) for v in np.asarray(values, dtype=float)]


def analyse(photo, catalog_dir, dem, debug_dir=None):
    image = Image.open(catalog_dir / photo["assets"]["rectified"])
    debug = None if debug_dir is None else debug_dir / f"sky_{photo['id']}.jpg"
    dem_row, dem_kind, distance = dem_skyline(dem, photo["pose"])
    photo_row, status, first_valid = photo_skyline(image, debug)
    stats, diff_px, diff_deg = compare(dem_row, dem_kind, photo_row, status, first_valid)
    pose = photo["pose"]
    in_box = dem_kind == "in_box"
    result = {
        "id": photo["id"], "sol": photo["sol"], "rectified": photo["assets"]["rectified"],
        "heading_deg": round(math.degrees(pose["heading"]), 3),
        "elevation_deg": round(-math.degrees(pose["pitch"]), 3),
        "camera": {k: pose[k] for k in ("x", "y", "z")},
        "in_box_skyline_distance_m": ({"median": round(float(np.median(distance[in_box])), 1),
                                       "min": round(float(distance[in_box].min()), 1),
                                       "max": round(float(distance[in_box].max()), 1)}
                                      if in_box.any() else None),
        **stats,
        "alignment": alignment(dem_row, dem_kind, photo_row, status),
        "hidden_crest_edges": hidden_crest_edges(image, dem_row, diff_deg),
    }
    columns = {"dem_row": _rounded(dem_row), "dem_kind": dem_kind.tolist(),
               "dem_distance_m": _rounded(distance, 1), "photo_row": _rounded(photo_row),
               "photo_status": status.tolist(), "diff_px": _rounded(diff_px), "diff_deg": _rounded(diff_deg, 3)}
    return result, columns, image


def _pct(value):
    return "n/a" if value is None else f"{100 * value:.0f}%"


def _array(values):
    return np.array([np.nan if v is None else v for v in values], dtype=float)


def _draw_lines(ax, dem_row, kind, photo_row, bad, label=True):
    u = np.arange(SIZE)
    for col in np.flatnonzero(bad):
        ax.plot([col, col], [dem_row[col], photo_row[col]], color="#ff3030", lw=1, alpha=0.6)
    ax.plot(u, np.where(kind == "in_box", dem_row, np.nan), color="#00e5ff", lw=1.8,
            label="DEM skyline, feature inside the box" if label else None)
    ax.plot(u, np.where(kind == "box_edge", dem_row, np.nan), color="#00e5ff", lw=1.4, ls=(0, (4, 3)),
            label="DEM skyline, only the box edge" if label else None)
    ax.plot(u, photo_row, color="#ffb000", lw=1.0, label="photo skyline (sky/ground boundary)" if label else None)


def figure(image, result, columns, path):
    """Comparison image with both skylines, the per-column difference and a caption."""
    rgba = np.asarray(image.convert("RGBA"))
    view = np.where(rgba[..., 3:4] > 0, rgba[..., :3], np.array([70, 70, 90], dtype=np.uint8))
    dem_row, photo_row = _array(columns["dem_row"]), _array(columns["photo_row"])
    diff = _array(columns["diff_deg"])
    kind = np.array(columns["dem_kind"], dtype=object)
    bad = np.isfinite(diff) & (diff < -LIMIT_DEG)
    width, height = 840, 1050
    left, image_bottom, strip_bottom, strip_height = 56, 270, 104, 140
    fig = plt.figure(figsize=(width / 100, height / 100), dpi=100)
    ax = fig.add_axes([left / width, image_bottom / height, SIZE / width, SIZE / height])
    ax.imshow(view, interpolation="nearest")
    _draw_lines(ax, dem_row, kind, photo_row, bad)
    if bad.any():
        ax.plot([], [], color="#ff3030", lw=1, label="DEM above photo by > 1 degree")
    ax.set_xlim(-0.5, SIZE - 0.5)
    ax.set_ylim(SIZE - 0.5, -0.5)
    ax.set_xticks([])
    ax.set_yticks([])
    ax.legend(loc="upper left", fontsize=7.5, framealpha=0.75)

    # Zoom when the skylines occupy only a small part of the frame.
    shown = np.isfinite(photo_row) | ((kind == "in_box") & (dem_row >= 0) & (dem_row <= SIZE - 1))
    if shown.any():
        cols = np.flatnonzero(shown)
        rows = np.concatenate([photo_row[shown][np.isfinite(photo_row[shown])],
                               dem_row[shown][np.isfinite(dem_row[shown])]])
        rows = rows[(rows >= 0) & (rows <= SIZE - 1)]
        c0, c1 = max(cols.min() - 10, 0), min(cols.max() + 10, SIZE - 1)
        r0, r1 = max(rows.min() - 15, 0), min(rows.max() + 15, SIZE - 1)
        zoom = 2.0
        if (c1 - c0) * zoom <= 0.8 * SIZE and (r1 - r0) * zoom <= 0.4 * SIZE:
            w, h = (c1 - c0) * zoom / SIZE, (r1 - r0) * zoom / SIZE
            inset = ax.inset_axes([0.99 - w, 0.01, w, h])
            inset.imshow(view, interpolation="nearest")
            _draw_lines(inset, dem_row, kind, photo_row, bad, label=False)
            inset.set_xlim(c0, c1)
            inset.set_ylim(r1, r0)
            inset.set_xticks([])
            inset.set_yticks([])
            ax.indicate_inset_zoom(inset, edgecolor="white")

    strip = fig.add_axes([left / width, strip_bottom / height, SIZE / width, strip_height / height])
    u = np.arange(SIZE)
    clipped = np.clip(diff, -4, 4)
    strip.axhline(0, color="0.4", lw=0.8)
    for y in (-LIMIT_DEG, LIMIT_DEG):
        strip.axhline(y, color="0.4", lw=0.8, ls=":")
    strip.scatter(u[diff < 0], clipped[diff < 0], s=2, color="#d62728", label="DEM above photo (in-box disagreement)")
    strip.scatter(u[diff > 0], clipped[diff > 0], s=2, color="#e08a00",
                  label="photo above DEM (farther terrain or DEM too low)")
    strip.set_xlim(-0.5, SIZE - 0.5)
    strip.set_ylim(-4.2, 4.2)
    strip.set_ylabel("DEM - photo (deg)", fontsize=7.5)
    strip.set_xlabel("image column (in-box DEM skyline only; clipped at 4 degrees)", fontsize=7.5)
    strip.tick_params(labelsize=7)
    strip.legend(loc="upper right", fontsize=6.5, framealpha=0.8, markerscale=3)

    above, below = result["dem_above_photo"], result["photo_above_dem"]
    line1 = (f"{result['id']}, sol {result['sol']}: heading {result['heading_deg']:.1f} deg, "
             f"elevation {result['elevation_deg']:+.1f} deg, 40 deg view.")
    line2 = (f"In-box DEM skyline in {result['dem_kind_counts']['in_box']} of 768 columns; "
             f"{result['in_box_compared']} compared with the photo skyline. Median |DEM - photo| "
             f"{result['abs_median_deg']} deg, p90 {result['abs_p90_deg']} deg.")
    line3 = (f"DEM above photo by > 1 deg (in-box disagreement): {_pct(above['beyond_limit_fraction'])}. "
             f"Photo above DEM by > 1 deg (may be terrain beyond the box): {_pct(below['beyond_limit_fraction'])}.")
    for k, line in enumerate((line1, line2, line3)):
        fig.text(8 / width, (52 - 18 * k) / height, line, fontsize=7.8, va="center")
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, pil_kwargs={"quality": 88})
    plt.close(fig)
    if path.stat().st_size >= 1_000_000:
        raise RuntimeError(f"{path} is not under 1 MB")


def pooled(results_columns):
    """Statistics over all compared columns of several photos."""
    kind = np.concatenate([np.array(c["dem_kind"], dtype=object) for c in results_columns])
    status = np.concatenate([np.array(c["photo_status"], dtype=object) for c in results_columns])
    diff = np.concatenate([_array(c["diff_deg"]) for c in results_columns])
    d = diff[np.isfinite(diff)]
    n = d.size
    dem_above, photo_above = -d[d < 0], d[d > 0]
    return {"columns": int(kind.size), "in_box_columns": int(np.sum(kind == "in_box")),
            "in_box_compared": int(n),
            "signed_median_deg": round(float(np.median(d)), 3) if n else None,
            "abs_median_deg": round(float(np.median(np.abs(d))), 3) if n else None,
            "abs_p90_deg": round(float(np.percentile(np.abs(d), 90)), 3) if n else None,
            "within_limit_fraction": round(float(np.mean(np.abs(d) <= LIMIT_DEG)), 4) if n else None,
            "dem_above_photo": {**_summary(dem_above),
                                "beyond_limit_fraction": round(float(np.sum(dem_above > LIMIT_DEG)) / n, 4) if n else None},
            "photo_above_dem": {**_summary(photo_above),
                                "beyond_limit_fraction": round(float(np.sum(photo_above > LIMIT_DEG)) / n, 4) if n else None},
            "photo_status_counts_in_box": {k: int(np.sum((kind == "in_box") & (status == k)))
                                           for k in ("ok", "ground_at_top", "no_ground", "no_pixels")}}


def _hidden_summary(results):
    """Pooled hidden-crest step check; photos whose steps are no better than chance."""
    rows = [(r["id"], r["sol"], r["hidden_crest_edges"]) for r in results if r["hidden_crest_edges"]["n"] > 0]
    if not rows:
        return None
    n = sum(h["n"] for _, _, h in rows)
    within = sum(h["n"] * h["within_tolerance_fraction"] for _, _, h in rows) / n
    chance = rows[0][2]["chance_fraction"]
    return {"photos": len(rows), "columns": int(n), "within_tolerance_fraction": round(within, 4),
            "chance_fraction": chance,
            "photos_at_or_below_1_5x_chance": [{"id": i, "sol": s, "within_tolerance_fraction": h["within_tolerance_fraction"]}
                                              for i, s, h in rows if h["within_tolerance_fraction"] <= 1.5 * chance]}


def _alignment_summary(results, min_fraction=0.6):
    """Median best shift over photos whose best alignment fits most compared columns."""
    good = [(r["id"], r["sol"], r["alignment"]) for r in results
            if r["alignment"] and r["alignment"]["best_fraction"] >= min_fraction]
    if not good:
        return None
    dx = np.array([a["best_dx_px"] for _, _, a in good])
    dy = np.array([a["best_dy_px"] for _, _, a in good])
    deg = math.degrees(1 / FOCAL_PX)
    return {"min_best_fraction": min_fraction, "photos": len(good),
            "median_dx_px": float(np.median(dx)), "median_dy_px": float(np.median(dy)),
            "median_dx_deg": round(float(np.median(dx) * deg), 2), "median_dy_deg": round(float(np.median(dy) * deg), 2),
            "per_photo": [{"id": i, "sol": s, "dx_px": a["best_dx_px"], "dy_px": a["best_dy_px"],
                           "near_best_dx_px": a["near_best_dx_px"], "best_fraction": a["best_fraction"]}
                          for i, s, a in good]}


def run(catalog, dem_path, ids, figure_dir, output_json, max_pitch_deg, debug_dir=None):
    catalog = Path(catalog)
    data = json.loads(catalog.read_text(encoding="utf-8"))
    photos = {p["id"]: p for p in data["photos"]}
    missing = [i for i in ids if i not in photos]
    if missing:
        raise SystemExit(f"Unknown photo ids: {missing}")
    sols = [photos[i]["sol"] for i in ids]
    if len(set(sols)) != len(sols):
        raise SystemExit("Figure photos must come from different sols (one figure per sol)")
    dem = Dem(dem_path)
    bbox = data["bbox"]
    if any(abs(a - b) > 1e-6 for a, b in zip(dem.bounds, (bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"]))):
        raise SystemExit("DEM bounds differ from the catalogue box")
    if debug_dir is not None:
        Path(debug_dir).mkdir(parents=True, exist_ok=True)
        debug_dir = Path(debug_dir)
    figures, per_photo, done = [], [], {}
    for photo_id in ids:
        result, columns, image = analyse(photos[photo_id], catalog.parent, dem, debug_dir)
        done[photo_id] = (result, columns)
        path = Path(figure_dir) / f"p3_fig1_skyline_{result['sol']}.jpg"
        figure(image, result, columns, path)
        figures.append({**result, "figure": path.name, "per_column": columns})
        print(json.dumps({k: result[k] for k in ("id", "sol", "in_box_compared", "abs_median_deg",
                                                 "dem_above_photo", "photo_above_dem", "alignment")}))
    selected = sorted((p for p in data["photos"] if p["assets"].get("rectified")
                       and abs(math.degrees(p["pose"]["pitch"])) <= max_pitch_deg), key=lambda p: (p["sol"], p["id"]))
    agg_columns = []
    for photo in selected:
        if photo["id"] in done:
            result, columns = done[photo["id"]]
        else:
            result, columns, _ = analyse(photo, catalog.parent, dem, debug_dir)
        per_photo.append(result)
        agg_columns.append(columns)
    aggregate = {"selection": f"every catalogue photo with |pitch| <= {max_pitch_deg} degrees",
                 "photo_count": len(selected), "sol_count": len({p["sol"] for p in selected}),
                 "pooled": pooled(agg_columns) if agg_columns else None,
                 "photos_with_in_box_columns": sum(r["dem_kind_counts"]["in_box"] > 0 for r in per_photo),
                 "photos_with_dem_above_photo_beyond_limit": sum(
                     (r["dem_above_photo"]["beyond_limit_fraction"] or 0) > 0 for r in per_photo),
                 "photos_with_compared_columns": sum(r["in_box_compared"] > 0 for r in per_photo),
                 "hidden_crest_edges": _hidden_summary(per_photo),
                 "alignment": _alignment_summary(per_photo),
                 "per_photo": per_photo}
    document = {
        "schema_version": SCHEMA_VERSION, "script": "src/viz3d/photo_skyline.py",
        "inputs": {"catalog": str(catalog), "generation": data.get("generation"), "dem": str(dem_path)},
        "parameters": {"image_size_px": SIZE, "fov_deg": FOV_DEG, "focal_px": FOCAL_PX,
                       "mars_radius_m": MARS_RADIUS_M, "ray_step_m": STEP_M, "edge_margin_m": EDGE_MARGIN_M,
                       "search_top_row": SEARCH_TOP_ROW, "bisection_steps": BISECTION_STEPS,
                       "sky_sigma_px": SKY_SIGMA_PX, "sky_max_gradient_levels_per_px": SKY_MAX_GRADIENT,
                       "sky_min_area_fraction": SKY_MIN_AREA, "refine_below_px": REFINE_BELOW_PX,
                       "median_columns": MEDIAN_COLUMNS, "limit_deg": LIMIT_DEG,
                       "align_shift_px": ALIGN_SHIFT_PX, "align_tolerance_px": ALIGN_TOLERANCE_PX,
                       "hidden_min_deg": HIDDEN_MIN_DEG, "hidden_window_px": HIDDEN_WINDOW_PX,
                       "hidden_tolerance_px": HIDDEN_TOLERANCE_PX},
        "conventions": {
            "rows": "pixel-centre coordinates of the 768 px comparison image, 0 = top; boundary at the grazing ray",
            "diff": "DEM skyline row minus photo skyline row (also in degrees inside the column)",
            "dem_above_photo": "negative diff: the DEM puts ground where the photo shows sky; an in-box disagreement",
            "photo_above_dem": "positive diff: the photo's skyline is higher; may be farther terrain outside the box, not counted as an error",
            "beyond_limit_fraction": "columns of that case beyond limit_deg over all in-box compared columns",
            "dem_kind": "in_box = largest terrain angle along the grazing ray lies inside the box (a crest); box_edge = it lies within edge_margin_m of the box boundary (terrain cut off by the box)",
            "photo_status": "ok; ground_at_top = no sky at the top of that column (skyline above the frame)",
            "hidden_crest_edges": "where the photo skyline is above an in-box DEM crest by > hidden_min_deg, offset of the strongest vertical intensity step within +-hidden_window_px of the DEM row (edge minus DEM, px); chance_fraction = share expected within tolerance if the step were placed at random",
            "alignment": "constant shift of the in-box DEM skyline (dx right, dy down, pixels) maximising the fraction of columns within align_tolerance_px of the photo skyline",
        },
        "figures": figures, "aggregate": aggregate,
    }
    output_json = Path(output_json)
    output_json.parent.mkdir(parents=True, exist_ok=True)
    output_json.write_text(json.dumps(document, indent=1, allow_nan=False), encoding="utf-8")
    print(json.dumps({"aggregate": aggregate["pooled"], "photos": aggregate["photo_count"]}))
    return document


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--catalog", required=True, type=Path, help="data/tiles/3d/photos/catalog.json")
    parser.add_argument("--dem", required=True, type=Path, help="data/base/dem_1m.tif")
    parser.add_argument("--ids", required=True, nargs="+", help="photo ids for the figures (different sols)")
    parser.add_argument("--figure-dir", required=True, type=Path, help="paper/figures")
    parser.add_argument("--output-json", required=True, type=Path, help="data/tiles/3d/photos/skyline_check.json")
    parser.add_argument("--max-pitch-deg", type=float, default=12.0, help="aggregate: |pitch| limit (default 12)")
    parser.add_argument("--debug-dir", type=Path, help="optional folder for sky-mask images")
    args = parser.parse_args(argv)
    run(args.catalog, args.dem, args.ids, args.figure_dir, args.output_json, args.max_pitch_deg, args.debug_dir)


if __name__ == "__main__":
    main()
