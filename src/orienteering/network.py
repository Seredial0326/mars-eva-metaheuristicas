"""
E5 on top of the E4 grid graph (grafos, Aaron): loading, habitat placement,
station-to-station matrix and the cell path of each leg.
"""
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from grafos.graph import Graph, follow  # noqa: E402

from orienteering.data_io import BASE_DIR  # noqa: E402


"""
Loads the E4 graph from data/base (edges_e3.npz, grid.json, crs.wkt) and the mask
of its largest strongly connected component (the cells you can go to and come back
from), from Graph.main_component (cached in the graph).
human=True uses the human cost, the same one /plan uses: E3 energy x E1's terrain
factor of the arrival cell (fisica.human_cost, weights in data/e1/e1_weights.json from
release e1-sand-v1, which also needs data/e8 from release e8-v0). Time is unchanged.
Returns (graph, main_cc) with main_cc a bool array of the grid's shape.
"""
def load_graph(base_dir=BASE_DIR, human=False):
    graph = human_graph(base_dir) if human else Graph.from_base_dir(base_dir)
    graph.cost_model = "E3 x E1 sand (human)" if human else "E3"
    return graph, graph.main_component()


"""
E4 graph with the human cost, built like api/planner.graph(base, 30.0, human=True):
E3 edges (edges_e3.npz) with every arc's energy multiplied by E1's terrain factor of
the cell it enters. Raises FileNotFoundError if E1's weights or E3's edges are missing.
"""
def human_graph(base_dir=BASE_DIR):
    import json

    from fisica.human_cost import human_edge_costs, load_rasters, load_weights, terrain_factor

    base = Path(base_dir)
    weights = base.parent / "e1" / "e1_weights.json"
    edges = base / "edges_e3.npz"
    if not weights.exists():
        raise FileNotFoundError(f"{weights} not found: gh release download e1-sand-v1 (and e8-v0)")
    if not edges.exists():
        raise FileNotFoundError(f"{edges} not found: run src/fisica/build_cost_layers.py first")

    with np.load(edges) as z:
        energy, time_s, neighbours = z["energy_j"], z["time_s"], z["neighbours"]
    spec = load_weights(weights)
    factor = terrain_factor(spec, load_rasters(spec, base), energy.shape[1:])
    energy = human_edge_costs(energy, factor, [tuple(int(v) for v in n) for n in neighbours])
    grid = json.loads((base / "grid.json").read_text(encoding="utf-8"))
    return Graph({"energy_j": energy, "time_s": time_s}, neighbours,
                 transform=tuple(grid["grid_1m"]["affine"]),
                 crs_wkt=(base / "crs.wkt").read_text(encoding="utf-8").strip())


"""
Places the habitat exactly as E4 and /plan do (Graph.place): if its cell is blocked
or outside the main component it moves to the nearest valid cell.
Returns (row, col, moved_m); use graph.cell_to_xy(row, col) for the coordinates shared
with E4 and E12. Raises ValueError if xy is outside the grid.
"""
def place_habitat(graph, xy):
    return graph.place(*xy, label="habitat")


"""
Tells which stations sit inside the main component, i.e. can be reached from
the habitat and can return to it.
"""
def reachable_stations(main_cc, stations):
    return main_cc[stations.row, stations.col]


"""
Directed cost matrix between stations: dis[i][j] is the minimum cost from station i
to station j (one Dijkstra per station, grafos Graph.cost_matrix).
weight: "energy_j" (J) or "time_s" (s). It is not symmetric.
"""
def station_matrix(graph, stations, weight="energy_j"):
    return graph.cost_matrix(graph.node(stations.row, stations.col), weight)


"""
Energy and time matrices between stations, both measured along the same legs:
energy[i][j] is the minimum energy from station i to station j, and time[i][j] is
the walking time along that minimum-energy leg (not the fastest leg), so the
solver's times match the route that is actually walked. Unreachable pairs are np.inf.
Each (station, station) value is cached per graph object, so a repeated plan with the
same stations (/plan requests, sensitivity runs) needs no Dijkstra at all; a Dijkstra
only runs from a station that has a pair not seen before. The cache holds pair values
only (a few bytes each), never the 4 M-cell search results. Returns new arrays.
"""
def station_matrices(graph, stations):
    ids = [int(v) for v in graph.node(stations.row, stations.col)]
    n = len(ids)
    pairs = _pair_cache(graph)

    for src in dict.fromkeys(ids):
        if any((src, dst) not in pairs for dst in ids if dst != src):
            dist, pred = graph.costs_from(src, "energy_j", predecessors=True)
            for dst in dict.fromkeys(ids):
                if dst == src or (src, dst) in pairs:
                    continue
                e = float(dist[dst])
                t = np.inf
                if np.isfinite(e):
                    leg = follow(pred, dst, end=src)[::-1]
                    t = float(graph.path_cost(leg, "time_s")[-1])
                pairs[(src, dst)] = (e, t)

    energy = np.zeros((n, n))
    time = np.zeros((n, n))
    for i, src in enumerate(ids):
        for j, dst in enumerate(ids):
            if src != dst:
                energy[i, j], time[i, j] = pairs[(src, dst)]
    return energy, time


_CACHE = {}
_CACHE_GRAPHS = 4


"""
Pair cache for one graph object: {(source node, destination node): (energy J, time s)}.
Keeps at most _CACHE_GRAPHS graphs (e.g. /plan's plain and human-cost graphs). The graph
itself is kept in the entry, so an id() reused by another object can't match.
"""
def _pair_cache(graph):
    entry = _CACHE.get(id(graph))
    if entry is None or entry[0] is not graph:
        if len(_CACHE) >= _CACHE_GRAPHS:
            _CACHE.pop(next(iter(_CACHE)))
        entry = (graph, {})
        _CACHE[id(graph)] = entry
    return entry[1]


"""
Empties the station-matrix cache (e.g. after the graph's costs change in place).
"""
def clear_matrix_cache():
    _CACHE.clear()


"""
Node path (cell ids) of the cheapest leg from node a to node b.
limit: known cost of the leg (e.g. from station_matrix); the search stops there,
which is much faster than a search over the whole grid.
Raises ValueError if b is unreachable from a.
"""
def leg_path(graph, a, b, weight="energy_j", limit=np.inf):
    if a == b:
        return np.array([a], dtype=np.int64)
    limit = limit * (1 + 1e-9) + 1e-6 if np.isfinite(limit) else np.inf
    _, pred = graph.costs_from(a, weight, limit=limit, predecessors=True)
    return follow(pred, b, end=a)[::-1]


"""
Full cell path of a tour (station indices, from start to end).
    dis : station matrix used by the solver, to bound each leg's search
Returns (path, stop_index): path is the node id of every cell visited, in order;
stop_index[k] is the position in path of the k-th stop of the tour.
"""
def route_path(graph, stations, route, dis=None, weight="energy_j"):
    nodes = graph.node(stations.row, stations.col)
    path, stop_index = [int(nodes[route[0]])], [0]

    for a, b in zip(route, route[1:]):
        limit = dis[a][b] if dis is not None else np.inf
        leg = leg_path(graph, int(nodes[a]), int(nodes[b]), weight, limit)
        path.extend(int(v) for v in leg[1:])
        stop_index.append(len(path) - 1)

    return np.array(path, dtype=np.int64), stop_index
