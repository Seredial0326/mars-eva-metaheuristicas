"""E1 step 2 - Curiosity's route as MaxEnt IRL demonstrations.

Demonstrations: data/e2/cell_sequence.csv cut by sol. A sol's drive starts
where the rover was parked (the last cell of the previous sol) and ends where
it parked at the end of the sol. Drives shorter than MIN_DRIVE_M are skipped:
they carry almost no information about route choice.

Window: the box around the drive plus MARGIN_M on every side, clipped to the
grid. The model rover can only move inside it.

Features (phi), every one >= 0 so that a cell can only cost more, never pay:
  metre            constant 1: the price of one metre of terrain
  slope_deg        steepest slope of the cell (JB, 1 m)
  roughness        JB's roughness layer
  tpi_ridge        max(tpi, 0): how much higher the cell is than its surroundings
  tpi_hollow       max(-tpi, 0): how much lower
  slope_mean_5m    mean slope in a 5 x 5 m window (as in E2)
  slope_mean_15m   mean slope in a 15 x 15 m window (as in E2)
TPI is split in two because a weight cannot be negative: this way ridges and
hollows each get their own price. Every feature except metre is divided by its
99th percentile over the whole box, so 1 means "as high as the top 1 % of the box".

With --features dem_sand (E8, JB's release e8-v0) two more; --features sand
uses only metre and these two:
  sand             fraction of the cell that E8's U-Net marks as sand (data/e8/sand.tif)
  sand_mean_5m     mean sand fraction in a 5 x 5 m window
With --features rocks (E9, Aaron's release e9-rocks-v1) metre and two more;
--features sand_rocks uses metre, the two sand features and these two:
  rocks            fraction of the cell covered by boulders (data/e9/rocas.tif, the
                   distilled student; NaN counts as 0, as in fisica.human_cost)
  rocks_mean_10m   mean boulder cover in a 10 x 10 m window (E9: the layer reads
                   best averaged to 10 m)
--rocks-layer teacher reads data/e9/teacher_cover_1m.tif (BoulderNet itself)
instead of the student, as a sensitivity check.
The default feature set ("dem") is the one of the E1 result merged in #50.

Block: the E2 validation block (src/ml/cell_features.py: 5 consecutive stretches
of the route with the same number of visited cells) of the drive's middle step.
"""
import numpy as np
import pandas as pd
import rasterio
from scipy.ndimage import uniform_filter

import cell_features as cf
import common
import maxent_irl as irl

DEM_FEATURES = ["metre", "slope_deg", "roughness", "tpi_ridge", "tpi_hollow",
                "slope_mean_5m", "slope_mean_15m"]
FEATURE_SETS = {"dem": DEM_FEATURES, "dem_sand": DEM_FEATURES + ["sand", "sand_mean_5m"],
                "sand": ["metre", "sand", "sand_mean_5m"],
                "rocks": ["metre", "rocks", "rocks_mean_10m"],
                "sand_rocks": ["metre", "sand", "sand_mean_5m", "rocks", "rocks_mean_10m"]}
FEATURES = list(DEM_FEATURES)     # the active set; setup() switches it with --features
SAND = common.PRODUCTS / "e8" / "sand.tif"
ROCKS = common.PRODUCTS / "e9" / "rocas.tif"                       # E9 student (release e9-rocks-v1)
ROCK_LAYERS = {"student": ROCKS, "teacher": common.PRODUCTS / "e9" / "teacher_cover_1m.tif"}
ROCKS_LAYER = "student"           # the active rock layer; setup() switches it with --rocks-layer
MIN_DRIVE_M = 10.0
MARGIN_M = 50


def read_on_grid(path, transform, shape, release):
    """A float64 layer that must be on the base grid (same transform and shape as the DEM)."""
    if not path.exists():
        raise SystemExit(f"{path} not found: download {release} into data/{path.parent.name}/")
    with rasterio.open(path) as src:
        if src.transform != transform or src.shape != shape:
            raise SystemExit(f"{path} is not on the base grid")
        return src.read(1).astype("float64")


def rock_features(cover):
    """rocks (cell cover, NaN -> 0) and rocks_mean_10m (its mean over a 10 x 10 m window)."""
    rocks = np.nan_to_num(cover, nan=0.0)
    return {"rocks": rocks, "rocks_mean_10m": uniform_filter(rocks, size=10, mode="nearest")}


def raw_features(features=None, rocks_layer=None):
    """Every feature in its own units (before dividing by its 99th percentile), and the transform."""
    features = features or FEATURES
    rocks_layer = rocks_layer or ROCKS_LAYER
    layers, transform = cf.feature_rasters()
    raw = {
        "slope_deg": layers["slope_deg"],
        "roughness": layers["roughness"],
        "tpi_ridge": np.maximum(layers["tpi"], 0.0),
        "tpi_hollow": np.maximum(-layers["tpi"], 0.0),
        "slope_mean_5m": layers["slope_mean_5m"],
        "slope_mean_15m": layers["slope_mean_15m"],
    }
    shape = layers["slope_deg"].shape
    if "sand" in features:
        sand = read_on_grid(SAND, transform, shape, "JB's release e8-v0")
        raw["sand"] = sand
        raw["sand_mean_5m"] = uniform_filter(sand, size=5, mode="nearest")
    if "rocks" in features:
        raw |= rock_features(read_on_grid(ROCK_LAYERS[rocks_layer], transform, shape,
                                          "Aaron's release e9-rocks-v1"))
    return raw, transform


def feature_stack(features=None, rocks_layer=None):
    """(F, 2000, 2000) float32 features, the scale (99th percentile) of each, and the transform."""
    features = features or FEATURES
    raw, transform = raw_features(features, rocks_layer)
    scale = {}
    for k in features[1:]:
        p99 = float(np.nanpercentile(raw[k], 99))
        scale[k] = p99 if p99 > 0 else float(np.nanmax(raw[k]))   # a mostly-zero layer
    phi = np.stack([np.ones_like(raw["slope_deg"])] + [raw[k] / scale[k] for k in features[1:]])
    return phi.astype(np.float32), scale, transform


def step_length(path):
    steps = np.abs(np.diff(path, axis=0))
    return float(np.where(steps.sum(axis=1) == 2, np.sqrt(2.0), 1.0).sum())


def block_edges():
    """The E2 block edges: route positions that split the visited cells into N_BLOCKS equal parts."""
    cells = pd.read_csv(common.E2_OUTPUT / "trajectory_cells.csv")
    return np.quantile(cells.first_step, np.linspace(0, 1, cf.N_BLOCKS + 1)[1:-1])


def pieces(piece_m):
    """The route cut into consecutive pieces of about piece_m grid metres (no sol boundaries)."""
    seq = pd.read_csv(common.E2_OUTPUT / "cell_sequence.csv")
    edges = block_edges()
    path = seq[["row", "col"]].to_numpy()
    steps = np.abs(np.diff(path, axis=0))
    cum = np.r_[0.0, np.cumsum(np.where(steps.sum(axis=1) == 2, np.sqrt(2.0), 1.0))]
    n = max(int(round(cum[-1] / piece_m)), 1)
    cuts = np.searchsorted(cum, np.linspace(0, cum[-1], n + 1))
    rows = []
    for a, b in zip(cuts[:-1], cuts[1:]):
        p = path[a:b + 1]
        middle = int(seq.order.iloc[(a + b) // 2])
        rows.append({"sol": int(seq.sol.iloc[a]), "block": int(np.searchsorted(edges, middle, side="right")),
                     "path": p, "length_m": step_length(p), "n_steps": len(p) - 1})
    return pd.DataFrame(rows)


def drives():
    """One row per sol with a drive of at least MIN_DRIVE_M: sol, block, path (T, 2) on the grid."""
    seq = pd.read_csv(common.E2_OUTPUT / "cell_sequence.csv")
    edges = block_edges()
    rows, prev_last = [], None
    for sol, g in seq.groupby("sol", sort=False):
        path = g[["row", "col"]].to_numpy()
        if prev_last is not None and np.abs(path[0] - prev_last).max() == 1:
            path = np.vstack([prev_last, path])   # start where the rover was parked
        prev_last = g[["row", "col"]].to_numpy()[-1]
        length = step_length(path)
        if length < MIN_DRIVE_M:
            continue
        middle = int(g.order.iloc[len(g) // 2])
        rows.append({"sol": int(sol), "block": int(np.searchsorted(edges, middle, side="right")),
                     "path": path, "length_m": length, "n_steps": len(path) - 1})
    return pd.DataFrame(rows)


def coarse_features(phi, factor):
    """Features on cells of factor x factor m: the mean of the 1 m cells inside each one."""
    f, h, w = phi.shape
    return phi.reshape(f, h // factor, factor, w // factor, factor).mean(axis=(2, 4))


def coarse_path(path, factor):
    """A 1 m route on cells of factor x factor m, without consecutive repeats (still 8-connected)."""
    p = path // factor
    keep = np.r_[True, (np.diff(p, axis=0) != 0).any(axis=1)]
    return p[keep]


def coarse_table(table, factor):
    """Same rows with each path moved to the coarse grid (length in coarse-cell units)."""
    out = table.copy()
    out["path"] = [coarse_path(p, factor) for p in table.path]
    out["length_m"] = [step_length(p) * factor for p in out.path]
    return out


def window_demo(phi, path, name, margin=MARGIN_M):
    """Demo with the features of the box around path plus margin, clipped to the grid."""
    n_rows, n_cols = phi.shape[1:]
    lo = np.maximum(path.min(axis=0) - margin, 0)
    hi = np.minimum(path.max(axis=0) + margin + 1, (n_rows, n_cols))
    win = phi[:, lo[0]:hi[0], lo[1]:hi[1]].astype(np.float64)
    return irl.Demo(win, path - lo, name=name, offset=(int(lo[0]), int(lo[1])))


def demos(phi, table, margin=MARGIN_M):
    return [window_demo(phi, r.path, f"sol{r.sol}_{i}", margin) for i, r in enumerate(table.itertuples())]


def add_arguments(ap):
    """Command-line options shared by fit_irl.py and validate_irl.py."""
    ap.add_argument("--piece-m", type=float, default=None,
                    help="cut the route into pieces of about this many metres (default: one per sol)")
    ap.add_argument("--cell", type=int, default=1, help="cell size in metres (1 = base grid)")
    ap.add_argument("--margin", type=int, default=MARGIN_M, help="window margin in metres")
    ap.add_argument("--whole-box", action="store_true", help="every window is the whole box")
    ap.add_argument("--chunk", type=int, default=16, help="demonstrations per GPU batch")
    ap.add_argument("--features", choices=sorted(FEATURE_SETS), default="dem",
                    help="feature set: dem (E1 as merged in #50), dem_sand (plus E8 sand), sand (metre + sand), "
                         "rocks (metre + E9 boulders) or sand_rocks (metre + sand + boulders)")
    ap.add_argument("--rocks-layer", choices=sorted(ROCK_LAYERS), default="student",
                    help="E9 boulder layer for the rocks features: student (rocas.tif, default) or "
                         "teacher (teacher_cover_1m.tif, sensitivity check; tag suffix _teacher)")


def setup(args):
    """(tag, features on the chosen grid, table, demos, feature scales) for the chosen demonstrations.

    Also makes args.features the active FEATURES list, which fit_irl.py and
    validate_irl.py read, and args.rocks_layer the active ROCKS_LAYER. Route
    lengths for NLL per metre come from the demos (demo.length_m * cell), not
    from the table: a demo that touches its goal earlier is cut there.
    """
    global FEATURES, ROCKS_LAYER
    layer = getattr(args, "rocks_layer", "student")
    if layer != "student" and "rocks" not in FEATURE_SETS[args.features]:
        raise SystemExit("--rocks-layer only applies to a feature set with rocks")
    FEATURES, ROCKS_LAYER = list(FEATURE_SETS[args.features]), layer
    phi, scale, _ = feature_stack()
    table = drives() if args.piece_m is None else pieces(args.piece_m)
    if args.cell > 1:
        phi = coarse_features(phi, args.cell)
        table = coarse_table(table, args.cell)
    margin = 10 ** 6 if args.whole_box else -(-args.margin // args.cell)   # metres -> cells
    tag = ("per_sol" if args.piece_m is None else f"piece{int(args.piece_m)}m") + \
        f"_cell{args.cell}m_" + ("box" if args.whole_box else f"margin{args.margin}m") + \
        ("" if args.features == "dem" else f"_{args.features}") + \
        ("" if ROCKS_LAYER == "student" else f"_{ROCKS_LAYER}")
    return tag, phi, table, demos(phi, table, margin), scale


if __name__ == "__main__":
    phi, scale, _ = feature_stack()
    table = drives()
    ds = demos(phi, table)
    sizes = np.array([d.phi.shape[1:] for d in ds])
    print(f"{len(table)} drives, {table.length_m.sum():.0f} m; per block:",
          table.groupby("block").agg(n=("sol", "size"), m=("length_m", "sum")).round(0).to_dict("index"))
    print(f"window size rows {sizes[:, 0].min()}-{sizes[:, 0].max()}, cols {sizes[:, 1].min()}-{sizes[:, 1].max()}")
    print("scale (99th percentile):", {k: round(v, 3) for k, v in scale.items()})
