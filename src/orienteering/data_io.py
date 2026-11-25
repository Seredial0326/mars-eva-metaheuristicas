"""
Inputs of E5: stations (GeoPackage, CRS of the DEM) placed on the E4 grid graph.
The grid, the E3 costs and the habitat placement come from grafos (E4, Aaron).
"""
from dataclasses import dataclass
from pathlib import Path

import geopandas as gpd
import numpy as np
from shapely.geometry import LineString, Point

DATA_DIR = Path(__file__).resolve().parents[2] / "data"
BASE_DIR = DATA_DIR / "base"
ROUTE_PATH = DATA_DIR / "e5" / "e5_route.gpkg"
STATIONS_PATH = DATA_DIR / "stations" / "stations_manual.gpkg"
STATIONS_LAYER = "stations"
TRAJECTORY_PATH = DATA_DIR / "e2" / "trajectory.gpkg"
TRAJECTORY_LAYER = "poses"


"""
Stations placed on the base grid, one entry per station:
    id, type: identifier and kind of the station (ridge, hollow, contact, curiosity, habitat)
    x, y: coordinates in the CRS of the DEM (Mars equirectangular metres)
    row, col: cell of the base grid that contains the point
    prize: prize of the station (score of the rubric)
    service_s: service time at the station in s
    windows: (n, 2) earliest and latest start of service in s from the start of the
             EVA ([0, inf] = always open); None means no station has a window
"""
@dataclass
class Stations:
    id: np.ndarray
    type: np.ndarray
    x: np.ndarray
    y: np.ndarray
    row: np.ndarray
    col: np.ndarray
    prize: np.ndarray
    service_s: np.ndarray
    windows: np.ndarray | None = None

    def __len__(self):
        return len(self.row)

    """
    Stations selected by a boolean mask or an index array.
    """
    def subset(self, keep):
        windows = self.windows[keep] if self.windows is not None else None
        return Stations(self.id[keep], self.type[keep], self.x[keep], self.y[keep],
                        self.row[keep], self.col[keep], self.prize[keep], self.service_s[keep],
                        windows)

    """
    Stations with a new one inserted first (the habitat as station 0), always open.
    """
    def prepend(self, id, type, x, y, row, col, prize=0.0, service_s=0.0):
        windows = None
        if self.windows is not None:
            windows = np.vstack([[0.0, np.inf], self.windows])
        return Stations(np.r_[[id], self.id], np.r_[[type], self.type],
                        np.r_[x, self.x], np.r_[y, self.y], np.r_[row, self.row],
                        np.r_[col, self.col], np.r_[prize, self.prize],
                        np.r_[service_s, self.service_s], windows)

    """
    Stations of self followed by those of other. If only one side has windows, the
    other side's stations are always open.
    """
    def concat(self, other):
        windows = None
        if self.windows is not None or other.windows is not None:
            always = lambda st: np.tile([0.0, np.inf], (len(st), 1))  # noqa: E731
            windows = np.vstack([self.windows if self.windows is not None else always(self),
                                 other.windows if other.windows is not None else always(other)])
        return Stations(*(np.r_[getattr(self, f), getattr(other, f)] for f in
                          ("id", "type", "x", "y", "row", "col", "prize", "service_s")), windows)


"""
Reads a point layer from a GeoPackage and places every point on the grid of `graph`
(grafos.graph.Graph). Columns of stations_manual.gpkg (Sebas, release stations-v1):
    id, type, score (prize_col), service_time_min
Optional time window columns (not in stations-v1 yet), minutes from the start of the EVA:
    window_open_min, window_close_min (empty = no limit)
Missing columns get defaults: id = row number, type = "", prize = 1, service = 0,
no windows.
Points outside the grid are dropped. Points falling in an already used cell are
dropped too (the first one is kept), so every station is a distinct graph node.
The habitat is not read from the file: it is a user input (see run.py).
"""
def read_stations(graph, path=STATIONS_PATH, layer=STATIONS_LAYER, prize_col="score"):
    gdf = gpd.read_file(path, layer=layer).reset_index(drop=True)
    n = len(gdf)

    x = gdf.geometry.x.to_numpy()
    y = gdf.geometry.y.to_numpy()
    ids = gdf["id"].astype(str).to_numpy() if "id" in gdf.columns else np.arange(n).astype(str)
    types = gdf["type"].astype(str).to_numpy() if "type" in gdf.columns else np.full(n, "")
    prize = gdf[prize_col].to_numpy(dtype=float) if prize_col in gdf.columns else np.ones(n)
    if "service_time_min" in gdf.columns:
        service_s = gdf["service_time_min"].to_numpy(dtype=float) * 60.0
    else:
        service_s = np.zeros(n)

    windows = None
    if "window_open_min" in gdf.columns or "window_close_min" in gdf.columns:
        opens = gdf.get("window_open_min", np.zeros(n))
        closes = gdf.get("window_close_min", np.full(n, np.inf))
        opens, closes = np.asarray(opens, dtype=float), np.asarray(closes, dtype=float)
        opens = np.where(np.isnan(opens), 0.0, opens) * 60.0
        closes = np.where(np.isnan(closes), np.inf, closes) * 60.0
        windows = np.column_stack([opens, closes])

    row, col = graph.xy_to_cell(x, y)
    inside = (row >= 0) & (row < graph.height) & (col >= 0) & (col < graph.width)
    stations = Stations(ids, types, x, y, row, col, prize, service_s, windows).subset(inside)

    _, first = np.unique(graph.node(stations.row, stations.col), return_index=True)
    return stations.subset(np.sort(first))


"""
Reads several station files (same columns as read_stations, for example the manual
stations and E8's stations_e8.gpkg) into one set, in file order. A station whose id or
cell was already used by an earlier one is dropped.
"""
def read_station_files(graph, paths, layer=STATIONS_LAYER, prize_col="score"):
    stations = None
    for path in paths:
        part = read_stations(graph, path, layer=layer, prize_col=prize_col)
        stations = part if stations is None else stations.concat(part)
    _, first = np.unique(stations.id, return_index=True)
    stations = stations.subset(np.sort(first))
    _, first = np.unique(graph.node(stations.row, stations.col), return_index=True)
    return stations.subset(np.sort(first))


"""
Writes the E5 route to a GeoPackage in the CRS of the DEM (contract #2), two layers:
    route : one LineString through the centre of every cell of the tour, with
            solver, prize, energy_wh, travel_time_s, length_m, usable_wh and the
            visiting order (station ids separated by ">")
    stops : one Point per stop in visiting order (habitat first and last) with
            order, id, type, score, service_time_min, service_energy_wh, and on arrival:
            energy_wh (walking plus service done so far), walk_energy_wh, travel_time_s
            (walking only), arrival_time_s (walking plus service so far), length_m;
            plus the walking energy of the leg into it (leg_energy_wh)
    graph : grafos Graph (cell centres, CRS and leg costs)
    path, stop_index : from network.route_path
    usable_j : energy budget the solver used, in J
    service_power_w : metabolic power while working at a station (service energy =
                      service time x power); every stop is served once, the final
                      return to the habitat is not
    timeline : problem.evaluate_route(problem, route), optional. With it the stops get
               the solver's schedule: arrival_time_s, wait_s (waiting for a window to
               open) and departure_time_s, and the route its duration_s and wait_s.
               Without it the times are walking plus service, with no waits.
    wait_power_w : power while waiting for a window (W); the waits' energy is added to
                   the totals (wait_energy_wh) and to the energy on arrival at later stops
    walkback : safety.tour_walkback profile, optional. With it the stops get rv_wh
               (energy to walk back to the habitat) and slack_wh (energy left after
               that, once the stop's service is done), and the route walkback_ok and
               min_slack_wh.
The route layer has the totals: energy_wh (walking plus service), walk_energy_wh,
service_energy_wh, travel_time_s (walking), duration_s (walking, waits and service).
Returns the path of the file.
"""
def write_route_gpkg(out_path, graph, stations, solution, path, stop_index, usable_j,
                     service_power_w=0.0, timeline=None, walkback=None, wait_power_w=0.0):
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    energy = graph.path_cost(path, "energy_j") if len(path) > 1 else np.zeros(1)
    time_s = graph.path_cost(path, "time_s") if len(path) > 1 else np.zeros(1)
    length = graph.path_cost(path, "length_m") if len(path) > 1 else np.zeros(1)

    route_st = list(solution.route)
    served = np.array([k not in route_st[:m] for m, k in enumerate(route_st)])
    svc_s = np.where(served, stations.service_s[route_st], 0.0)
    svc_j = svc_s * service_power_w
    done_s = np.r_[0.0, np.cumsum(svc_s)[:-1]]

    at = np.asarray(stop_index)
    if timeline is not None and timeline["arrival"] is not None:
        arrival = np.asarray(timeline["arrival"], dtype=float)
        wait = np.asarray(timeline["begin"], dtype=float) - arrival
        departure = np.asarray(timeline["depart"], dtype=float)
    else:
        arrival = time_s[at] + done_s
        wait = np.zeros(len(at))
        departure = arrival + svc_s
    duration = float(departure[-1]) if len(departure) else 0.0
    wait_j = wait * wait_power_w
    done_j = np.r_[0.0, np.cumsum(svc_j + wait_j)[:-1]]

    rows, cols = graph.cell(path)
    xs, ys = graph.cell_to_xy(rows, cols)
    coords = list(zip(xs.tolist(), ys.tolist()))
    if len(coords) == 1:
        coords = coords * 2

    route_ids = [str(stations.id[k]) for k in solution.route]
    route = gpd.GeoDataFrame({
        "solver": [solution.solver],
        "prize": [float(solution.prize)],
        "energy_wh": [(float(energy[-1]) + svc_j.sum() + wait_j.sum()) / 3600.0],
        "walk_energy_wh": [float(energy[-1]) / 3600.0],
        "service_energy_wh": [svc_j.sum() / 3600.0],
        "wait_energy_wh": [wait_j.sum() / 3600.0],
        "travel_time_s": [float(time_s[-1])],
        "duration_s": [duration],
        "wait_s": [float(wait.sum())],
        "service_power_w": [float(service_power_w)],
        "length_m": [float(length[-1])],
        "usable_wh": [float(usable_j) / 3600.0],
        "n_stops": [len(route_ids)],
        "order": [">".join(route_ids)],
    }, geometry=[LineString(coords)], crs=graph.crs_wkt)

    previous = np.r_[0, at[:-1]]
    stops = gpd.GeoDataFrame({
        "order": np.arange(len(route_ids)),
        "id": route_ids,
        "type": [str(stations.type[k]) for k in solution.route],
        "score": [float(stations.prize[k]) for k in solution.route],
        "service_time_min": svc_s / 60.0,
        "service_energy_wh": svc_j / 3600.0,
        "energy_wh": (energy[at] + done_j) / 3600.0,
        "walk_energy_wh": energy[at] / 3600.0,
        "leg_energy_wh": (energy[at] - energy[previous]) / 3600.0,
        "travel_time_s": time_s[at],
        "arrival_time_s": arrival,
        "wait_s": wait,
        "departure_time_s": departure,
        "length_m": length[at],
    }, geometry=[Point(stations.x[k], stations.y[k]) for k in solution.route], crs=graph.crs_wkt)

    route["cost_model"] = [str(getattr(graph, "cost_model", "E3"))]
    if walkback is not None:
        route["walkback_ok"] = [bool(walkback["feasible"])]
        route["min_slack_wh"] = [float(walkback["min_slack_j"]) / 3600.0]
        stops["rv_wh"] = np.asarray(walkback["rv_j"])[at] / 3600.0
        stops["slack_wh"] = np.asarray(walkback["stop_slack_j"]) / 3600.0

    if out_path.exists():
        out_path.unlink()
    route.to_file(out_path, layer="route", driver="GPKG")
    stops.to_file(out_path, layer="stops", driver="GPKG")
    return out_path
