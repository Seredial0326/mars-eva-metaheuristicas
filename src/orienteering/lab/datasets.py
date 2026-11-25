"""Station datasets for the metaheuristics lab: real-terrain instances (the experiment set)
and synthetic plane instances (kept for the unit tests and quick checks).

Real-terrain instances draw their stations from one pool: the manual stations (plus E8's when
stations_e8.gpkg exists) together with stations generated on the terrain. Every instance is
energy-only (no time windows) and comes in two scenarios with a maximum EVA duration of 120
and 180 min.

Instances are cached under data/lab/instances/ (git-ignored) as `<name>.npz` (matrices and
problem fields), `<name>.csv` (stations) and, for real ones, `<name>.geojson`.

Run from the repo root (src must be importable):
    PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.datasets
"""
import argparse
import csv
import json
import sys
import time
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from orienteering.instances import random_instance
from orienteering.problem import Problem

REPO = Path(__file__).resolve().parents[3]
INSTANCES = REPO / "data" / "lab" / "instances"
WINDOWS_DIR = REPO / "data" / "lab" / "instances-windows"   # the same set with time windows

SYN_SIZES = (10, 12, 14, 16, 18, 20, 30, 40, 60, 100, 200)
SYN_KINDS = ("energy", "windows")
SYN_CASES = range(5)
REAL_SIZES = (20, 50, 80, 100)
REAL_CASES = range(2)
SCENARIOS = {"120min": 7200.0, "180min": 10800.0}
POOL_SIZE = 120                         # stations in the pool (manual first, then generated)
POOL_SEED = 7_000

MIN_SPACING_M = 40.0
SERVICE_S = 600.0
RUBRIC_PATH = REPO / "data" / "stations" / "stations_rubric.json"
BUDGET_WH, MARGIN = 1000.0, 0.10        # same as paper_figures
BOX_CENTRE = (8143537.99, -284463.58)   # same as paper_figures.BOX_CENTRE
CSV_FIELDS = ("id", "type", "x", "y", "prize", "service_s")


@dataclass
class Instance:
    """One lab instance: `problem` for the solvers, `distance` (m) for plots, `stations` rows
    (id, type, x, y, prize, service_s) with row 0 = habitat."""
    name: str
    set: str
    kind: str
    problem: Problem
    distance: np.ndarray
    stations: list[dict]


# ---------------------------------------------------------------- synthetic

def synthetic_name(n, kind, case):
    return f"syn-{kind}-n{n}-{case}"


def synthetic(n, kind, case):
    """Random instance of `random_instance` on a seeded plane; n counts the habitat."""
    seed = 10_000 * n + case + (0 if kind == "energy" else 5_000)
    pts = np.random.default_rng(seed).random((n, 2)) * 100
    problem = random_instance(np.random.default_rng(seed), n, kind)
    distance = np.linalg.norm(pts[:, None] - pts[None], axis=2)
    stations = [{"id": "habitat" if i == 0 else f"S{i}", "type": "synthetic",
                 "x": float(pts[i, 0]), "y": float(pts[i, 1]), "prize": float(problem.prize[i]),
                 "service_s": 0.0 if problem.service_s is None else float(problem.service_s[i])}
                for i in range(n)]
    return Instance(synthetic_name(n, kind, case), "synthetic", kind, problem, distance, stations)


# ---------------------------------------------------------------- real terrain

def _paths():
    """Make `api` (repo root) and `orienteering` (src) importable; the repo's modules do the
    same with sys.path.insert."""
    for p in (REPO, REPO / "src"):
        if str(p) not in sys.path:
            sys.path.insert(0, str(p))


def load_graph():
    """Human-cost graph used by /plan (about 4 s)."""
    _paths()
    from api.planner import graph
    return graph(str(REPO / "data" / "base"), 30.0, True)


def _matrices(graph, nodes):
    """Energy (J), time (s) and length (m) between `nodes` along the minimum-energy legs.
    One Dijkstra per source; the search result is dropped before the next one."""
    from grafos.graph import follow
    n = len(nodes)
    energy, tim, length = (np.zeros((n, n)) for _ in range(3))
    for i, src in enumerate(nodes):
        dist, pred = graph.costs_from(src, "energy_j", predecessors=True)
        for j, dst in enumerate(nodes):
            if i == j:
                continue
            energy[i, j] = dist[dst]
            if np.isfinite(dist[dst]):
                leg = follow(pred, dst, end=src)[::-1]
                tim[i, j] = graph.path_cost(leg, "time_s")[-1]
                length[i, j] = graph.path_cost(leg, "length_m")[-1]
            else:
                tim[i, j] = length[i, j] = np.inf
        del dist, pred
    return energy, tim, length


def _usable_j():
    _paths()
    from grafos.walkback import J_PER_WH
    return BUDGET_WH * (1 - MARGIN) * J_PER_WH


def _scenario_instances(prefix, set_name, stations, energy, tim, length, service_j):
    """One instance per scenario (120min, 180min) sharing the same matrices."""
    prize = np.array([s["prize"] for s in stations])
    service_s = np.array([s["service_s"] for s in stations])
    out = []
    for scen, max_d in SCENARIOS.items():
        p = Problem(energy=energy, prize=prize, budget=_usable_j(), time=tim, service_s=service_s,
                    service_j=service_j, max_duration_s=max_d)
        out.append(Instance(f"{prefix}-{scen}", set_name, scen, p, length, stations))
    return out


def station_pool(graph=None):
    """(stations, nodes): the habitat (row 0) and POOL_SIZE stations on the main component.

    The manual stations come first (plus E8's when stations_e8.gpkg exists; time windows are
    dropped); generated ones fill the pool, drawn with default_rng(POOL_SEED) and kept only if
    at least 40 m (Euclidean) from the habitat and from every station already in the pool.
    No Dijkstra here, so it is cheap."""
    _paths()
    from orienteering.data_io import DATA_DIR, STATIONS_PATH, read_station_files
    graph = graph if graph is not None else load_graph()
    rubric = json.loads(RUBRIC_PATH.read_text(encoding="utf-8"))["rubric"]
    types = sorted(rubric)

    hr, hc, _ = graph.place(*BOX_CENTRE, label="habitat")
    hx, hy = (float(v) for v in graph.cell_to_xy(hr, hc))
    stations = [{"id": "habitat", "type": "habitat", "x": hx, "y": hy, "prize": 0.0,
                 "service_s": 0.0}]
    nodes = [int(graph.node(hr, hc))]
    main = graph.main_component()

    e8 = DATA_DIR / "stations" / "stations_e8.gpkg"
    paths = [f for f in (STATIONS_PATH, e8) if f.exists()]
    if paths:
        st = read_station_files(graph, paths)
        st = st.subset(main[st.row, st.col])
        for i in range(len(st)):
            node = int(graph.node(st.row[i], st.col[i]))
            if node in nodes:
                continue
            stations.append({"id": str(st.id[i]), "type": str(st.type[i]), "x": float(st.x[i]),
                             "y": float(st.y[i]), "prize": float(st.prize[i]),
                             "service_s": float(st.service_s[i])})
            nodes.append(node)

    rng = np.random.default_rng(POOL_SEED)
    cells = np.flatnonzero(main.ravel())
    xy = np.array([[s["x"], s["y"]] for s in stations])
    k = 0
    while len(stations) < POOL_SIZE + 1:
        node = int(cells[rng.integers(len(cells))])
        r, c = (int(v) for v in graph.cell(node))
        x, y = (float(v) for v in graph.cell_to_xy(r, c))
        if np.min(np.hypot(xy[:, 0] - x, xy[:, 1] - y)) < MIN_SPACING_M:
            continue
        typ = types[int(rng.integers(len(types)))]
        k += 1
        stations.append({"id": f"G{k}", "type": typ, "x": x, "y": y,
                         "prize": float(rubric[typ]), "service_s": SERVICE_S})
        nodes.append(node)
        xy = np.vstack([xy, [x, y]])
    return stations, nodes


def real_pair(n, case, graph=None, pool=None, matrices=None):
    """(120min, 180min) instances with n nodes: the habitat + n-1 stations drawn without
    replacement from the pool with default_rng(7000 + 100 n + case).

    `pool` is station_pool(graph) and `matrices` the (energy, time, length) matrices of the
    whole pool (as _matrices(graph, nodes) returns them); without them only the drawn nodes
    get their Dijkstras. A leg's cost does not depend on the other stations, so a submatrix of
    the pool matrices is exactly the instance's matrix."""
    from grafos.build_rv import SERVICE_POWER_W
    if pool is None:
        graph = graph if graph is not None else load_graph()
        pool = station_pool(graph)
    stations, nodes = pool
    if n > len(stations):
        raise ValueError(f"the pool has {len(stations)} nodes, asked for {n}")
    rng = np.random.default_rng(7_000 + 100 * n + case)
    pick = [0] + sorted(int(i) + 1 for i in rng.choice(len(stations) - 1, n - 1, replace=False))
    if matrices is not None:
        energy, tim, length = (m[np.ix_(pick, pick)].copy() for m in matrices)
    else:
        graph = graph if graph is not None else load_graph()
        energy, tim, length = _matrices(graph, [nodes[i] for i in pick])
    chosen = [stations[i] for i in pick]
    service_j = np.array([s["service_s"] for s in chosen]) * SERVICE_POWER_W
    return _scenario_instances(f"real-n{n}-{case}", "real", chosen, energy, tim, length,
                               service_j)


def real(n, case, scenario, graph=None):
    """One scenario ("120min" or "180min") of real_pair; use real_pair to share the matrices."""
    if scenario not in SCENARIOS:
        raise ValueError(f"unknown scenario {scenario!r}")
    return real_pair(n, case, graph)[list(SCENARIOS).index(scenario)]


# ---------------------------------------------------------------- storage

def save(inst, root=INSTANCES):
    """Write `<name>.npz`, `<name>.csv` (and `.geojson` for real ones); returns the npz path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    p = inst.problem
    arrays = {"energy": p.energy, "distance": inst.distance, "prize": p.prize,
              "budget": np.array(p.budget), "start": np.array(p.start), "end": np.array(p.end),
              "max_duration_s": np.array(np.nan if p.max_duration_s is None else p.max_duration_s),
              "set": np.array(inst.set), "kind": np.array(inst.kind), "name": np.array(inst.name)}
    for field in ("time", "service_s", "service_j", "windows"):
        if getattr(p, field) is not None:
            arrays[field] = getattr(p, field)
    path = root / f"{inst.name}.npz"
    np.savez(path, **arrays)
    with open(root / f"{inst.name}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows({k: (repr(v) if isinstance(v, float) else v) for k, v in s.items()}
                    for s in inst.stations)
    if inst.set in ("real", "real-windows"):
        crs = (REPO / "data" / "base" / "crs.wkt").read_text(encoding="utf-8").strip()
        feats = [{"type": "Feature", "geometry": {"type": "Point", "coordinates": [s["x"], s["y"]]},
                  "properties": {k: s[k] for k in ("id", "type", "prize", "service_s")}}
                 for s in inst.stations]
        (root / f"{inst.name}.geojson").write_text(
            json.dumps({"type": "FeatureCollection", "crs_wkt": crs, "features": feats}),
            encoding="utf-8")
    return path


def load(name, root=INSTANCES):
    """Rebuild the Instance saved by `save`; matrices come back bit-identical."""
    root = Path(root)
    with np.load(root / f"{name}.npz", allow_pickle=False) as z:
        opt = lambda k: z[k].copy() if k in z.files else None  # noqa: E731
        max_d = float(z["max_duration_s"])
        problem = Problem(energy=z["energy"].copy(), prize=z["prize"].copy(),
                          budget=float(z["budget"]), start=int(z["start"]), end=int(z["end"]),
                          time=opt("time"), service_s=opt("service_s"),
                          service_j=opt("service_j"), windows=opt("windows"),
                          max_duration_s=None if np.isnan(max_d) else max_d)
        distance, set_name, kind = z["distance"].copy(), str(z["set"]), str(z["kind"])
    with open(root / f"{name}.csv", newline="", encoding="utf-8") as f:
        stations = [{"id": r["id"], "type": r["type"], "x": float(r["x"]), "y": float(r["y"]),
                     "prize": float(r["prize"]), "service_s": float(r["service_s"])}
                    for r in csv.DictReader(f)]
    return Instance(name, set_name, kind, problem, distance, stations)


def with_windows(inst, seed):
    """Copy of a real instance with time windows, by the synthetic "windows" rule scaled to
    the EVA length T (max_duration_s): each station opens late with probability 0.5, at
    U(0, 0.5 T), and then stays open U(0.15, 0.5) T; the others (and the habitat) are always
    open. Same stations, matrices and limits; the name gets the prefix `realtw`."""
    p = inst.problem
    T = float(p.max_duration_s)
    rng = np.random.default_rng(seed)
    n = p.n
    opens = np.where(rng.random(n) < 0.5, rng.uniform(0, 0.5 * T, n), 0.0)
    widths = rng.uniform(0.15, 0.5, n) * T
    windows = np.column_stack([opens, np.where(opens > 0, opens + widths, np.inf)])
    windows[0] = [0.0, np.inf]
    q = Problem(energy=p.energy, prize=p.prize, budget=p.budget, start=p.start, end=p.end,
                time=p.time, service_s=p.service_s, service_j=p.service_j, windows=windows,
                max_duration_s=p.max_duration_s)
    return Instance(inst.name.replace("real-", "realtw-", 1), "real-windows", inst.kind, q,
                    inst.distance, inst.stations)


def build_windows(root=WINDOWS_DIR, base_root=INSTANCES, force=False):
    """The real-terrain set again with time windows, in its own folder (default
    data/lab/instances-windows). Seed per case: 9000 + 100 n + case, shared by both
    scenarios (the windows scale with each scenario's T). Returns the names."""
    names = []
    for n in REAL_SIZES:
        for case in REAL_CASES:
            for sc in SCENARIOS:
                base = f"real-n{n}-{case}-{sc}"
                inst = with_windows(load(base, base_root), 9_000 + 100 * n + case)
                names.append(inst.name)
                if force or not _exists(inst.name, root):
                    save(inst, root)
    return names


def save_pool(stations, root=INSTANCES):
    """Write the station pool (habitat first) as `pool.csv`, same columns as the instance
    CSVs; the HUD loads it as a dataset. Returns the path."""
    root = Path(root)
    root.mkdir(parents=True, exist_ok=True)
    path = root / "pool.csv"
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        w.writeheader()
        w.writerows({k: (repr(v) if isinstance(v, float) else v) for k, v in s.items()}
                    for s in stations)
    return path


def _exists(name, root):
    return all((Path(root) / f"{name}.{ext}").exists() for ext in ("npz", "csv"))


def build_all(synthetic=False, real=True, force=False, root=INSTANCES):
    """Generate the missing instances (all with force) and return the names of the set.

    Existing files are left untouched, so a rerun recomputes no Dijkstra. The terrain graph,
    the station pool and the pool matrices are built lazily, once, and only when something
    real is missing."""
    names = []
    if synthetic:
        for n in SYN_SIZES:
            for kind in SYN_KINDS:
                for case in SYN_CASES:
                    name = synthetic_name(n, kind, case)
                    names.append(name)
                    if force or not _exists(name, root):
                        save(globals()["synthetic"](n, kind, case), root)
    if real:
        pool = matrices = graph = None
        if force or not (Path(root) / "pool.csv").exists():
            graph = load_graph()
            pool = station_pool(graph)
            save_pool(pool[0], root)
        for n in REAL_SIZES:
            for case in REAL_CASES:
                wanted = [f"real-n{n}-{case}-{sc}" for sc in SCENARIOS]
                names += wanted
                if not force and all(_exists(w, root) for w in wanted):
                    continue
                if matrices is None:
                    graph = graph if graph is not None else load_graph()
                    pool = pool if pool is not None else station_pool(graph)
                    t0 = time.time()
                    matrices = _matrices(graph, pool[1])
                    print(f"pool of {len(pool[0]) - 1} stations: {time.time() - t0:.0f} s",
                          flush=True)
                for inst in real_pair(n, case, pool=pool, matrices=matrices):
                    save(inst, root)
    return names


def main():
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--synthetic", action="store_true", help="also the synthetic instances")
    ap.add_argument("--windows", action="store_true",
                    help="also the same real set with time windows, in data/lab/instances-windows")
    ap.add_argument("--force", action="store_true", help="regenerate existing instances")
    args = ap.parse_args()
    names = build_all(args.synthetic, True, args.force)
    print(f"{len(names)} instances in {INSTANCES}")
    if args.windows:
        tw = build_windows(force=args.force)
        print(f"{len(tw)} instances with time windows in {WINDOWS_DIR}")


if __name__ == "__main__":
    main()
