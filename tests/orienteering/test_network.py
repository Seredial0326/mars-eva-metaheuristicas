"""E5 on the E4 grid graph: stations, habitat, matrix and legs on small synthetic grids."""

import sys
from pathlib import Path

import geopandas as gpd
import numpy as np
import pytest
from shapely.geometry import Point

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from grafos.graph import Graph

from orienteering.data_io import read_stations
from orienteering.network import (leg_path, place_habitat, reachable_stations,
                                  station_matrices, station_matrix)

NEIGHBOURS = [(-1, 0), (-1, 1), (0, 1), (1, 1), (1, 0), (1, -1), (0, -1), (-1, -1)]
E, W = 2, 6


def grid_graph(rows, cols, blocked=(), east_cost=1.0):
    """Unit costs on a rows x cols grid, east moves cost east_cost, blocked cells have no edges.
    Cell (r, c) covers x in [c, c+1) and y in (rows-r-1, rows-r]."""
    energy = np.full((8, rows, cols), 1.0)
    r, c = np.indices((rows, cols))
    for k, (dr, dc) in enumerate(NEIGHBOURS):
        nr, nc = r + dr, c + dc
        off = (nr < 0) | (nr >= rows) | (nc < 0) | (nc >= cols)
        for br, bc in blocked:
            off |= ((r == br) & (c == bc)) | ((nr == br) & (nc == bc))
        energy[k][off] = np.nan
    energy[E] = np.where(np.isfinite(energy[E]), east_cost, np.nan)
    return Graph({"energy_j": energy, "time_s": energy.copy()}, NEIGHBOURS,
                 transform=(1.0, 0.0, 0.0, 0.0, -1.0, float(rows)))


def stations_at(graph, cells, **cols):
    pts = [Point(*(float(v) for v in graph.cell_to_xy(r, c))) for r, c in cells]
    return gpd.GeoDataFrame(cols, geometry=pts)


def test_read_stations_uses_contract_columns(tmp_path):
    graph = grid_graph(3, 4)
    gdf = stations_at(graph, [(0, 0), (1, 2), (1, 2), (2, 3)],
                      id=["R0", "H0", "dup", "C1"], type=["ridge", "hollow", "hollow", "contact"],
                      score=[5.0, 4.0, 4.0, 4.0], service_time_min=[10.0, 5.0, 5.0, 0.0])
    path = tmp_path / "stations.gpkg"
    gdf.to_file(path, layer="stations")

    s = read_stations(graph, path, layer="stations")

    assert s.id.tolist() == ["R0", "H0", "C1"]
    assert s.type.tolist() == ["ridge", "hollow", "contact"]
    assert s.prize.tolist() == [5.0, 4.0, 4.0]
    assert s.service_s.tolist() == [600.0, 300.0, 0.0]
    assert list(zip(s.row.tolist(), s.col.tolist())) == [(0, 0), (1, 2), (2, 3)]


def test_read_stations_defaults_without_columns(tmp_path):
    graph = grid_graph(2, 2)
    path = tmp_path / "poses.gpkg"
    stations_at(graph, [(0, 0), (1, 1)]).to_file(path, layer="poses")

    s = read_stations(graph, path, layer="poses")

    assert s.prize.tolist() == [1.0, 1.0] and s.service_s.tolist() == [0.0, 0.0]


def test_read_stations_windows(tmp_path):
    graph = grid_graph(2, 3)
    gdf = stations_at(graph, [(0, 0), (0, 1), (0, 2)], id=["A", "B", "C"],
                      window_open_min=[10.0, None, 0.0], window_close_min=[20.0, 30.0, None])
    path = tmp_path / "w.gpkg"
    gdf.to_file(path, layer="stations")

    s = read_stations(graph, path, layer="stations")

    assert s.windows.tolist() == [[600.0, 1200.0], [0.0, 1800.0], [0.0, np.inf]]
    assert s.prepend("habitat", "habitat", 0.0, 0.0, 1, 0).windows[0].tolist() == [0.0, np.inf]


def test_time_matrix_follows_the_energy_leg():
    # East moves are cheap in energy (0.5) but slow (5 s); the time matrix must report the
    # time of the minimum-energy leg, not the fastest one
    graph = grid_graph(2, 3)
    energy = graph._edges["energy_j"].copy()
    slow = graph._edges["time_s"].copy()
    energy[E] = np.where(np.isfinite(energy[E]), 0.5, np.nan)
    slow[E] = np.where(np.isfinite(slow[E]), 5.0, np.nan)
    graph = Graph({"energy_j": energy, "time_s": slow}, NEIGHBOURS, transform=graph.transform)
    stations = type("S", (), {"row": np.array([0, 0]), "col": np.array([0, 2])})

    e, t = station_matrices(graph, stations)

    assert e[0, 1] == 1.0 and t[0, 1] == 10.0
    assert e[1, 0] == 2.0 and t[1, 0] == 2.0
    assert t[0, 0] == 0.0


def test_matrix_cache_reuses_pairs():
    graph = grid_graph(3, 6)
    calls = []
    search = graph.costs_from
    graph.costs_from = lambda *a, **k: calls.append(a[0]) or search(*a, **k)
    first = type("S", (), {"row": np.array([0, 1, 2]), "col": np.array([0, 3, 5])})
    more = type("S", (), {"row": np.array([0, 1, 2, 2]), "col": np.array([0, 3, 5, 1])})

    e1, t1 = station_matrices(graph, first)
    assert len(calls) == 3
    e2, t2 = station_matrices(graph, first)
    assert len(calls) == 3                                 # same stations: no new search
    assert np.array_equal(e1, e2) and np.array_equal(t1, t2)
    e1[0, 1] = -1.0                                        # callers can't corrupt the cache
    assert station_matrices(graph, first)[0][0, 1] != -1.0

    e3, _ = station_matrices(graph, more)                  # one new station: every source has a new pair
    assert len(calls) == 3 + 4
    assert np.array_equal(e3[:3, :3], e2)


def test_matrix_is_directed():
    graph = grid_graph(1, 3, east_cost=2.0)
    stations = type("S", (), {"row": np.array([0, 0]), "col": np.array([0, 2])})
    dis = station_matrix(graph, stations)
    assert dis[0, 1] == 4.0 and dis[1, 0] == 2.0


def test_habitat_snaps_and_blocked_station_is_unreachable():
    graph = grid_graph(3, 3, blocked=[(1, 1)])
    main_cc = graph.main_component()

    r, c, moved = place_habitat(graph, graph.cell_to_xy(1, 1))
    assert (r, c) != (1, 1) and moved == pytest.approx(1.0)
    assert place_habitat(graph, graph.cell_to_xy(0, 0)) == (0, 0, 0.0)
    with pytest.raises(ValueError):
        place_habitat(graph, (100.0, 100.0))
    stations = type("S", (), {"row": np.array([0, 1]), "col": np.array([0, 1])})
    assert reachable_stations(main_cc, stations).tolist() == [True, False]


def test_leg_path_detours_blocked_cell():
    graph = grid_graph(3, 3, blocked=[(1, 1)])
    a, b = int(graph.node(1, 0)), int(graph.node(1, 2))
    path = leg_path(graph, a, b)
    cells = [tuple(int(v) for v in graph.cell(n)) for n in path]
    assert cells[0] == (1, 0) and cells[-1] == (1, 2) and (1, 1) not in cells


def test_route_gpkg_round_trip(tmp_path):
    import pyogrio

    from orienteering.data_io import Stations, write_route_gpkg
    from orienteering.network import route_path
    from orienteering.problem import Solution

    graph = grid_graph(3, 4, blocked=[(1, 1)])
    cells = [(1, 0), (1, 3), (0, 2)]
    xy = [graph.cell_to_xy(r, c) for r, c in cells]
    stations = Stations(np.array(["habitat", "A", "B"]), np.array(["habitat", "ridge", "hollow"]),
                        np.array([p[0] for p in xy]), np.array([p[1] for p in xy]),
                        np.array([r for r, _ in cells]), np.array([c for _, c in cells]),
                        np.array([0.0, 5.0, 4.0]), np.array([0.0, 600.0, 300.0]))
    dis = station_matrix(graph, stations)
    route = [0, 1, 2, 0]
    spent = sum(dis[a][b] for a, b in zip(route, route[1:]))
    solution = Solution(route, 9.0, spent, "dp", 0.0)

    path, stop_index = route_path(graph, stations, route, dis)
    out = write_route_gpkg(tmp_path / "e5.gpkg", graph, stations, solution, path, stop_index, 100.0)

    assert sorted(name for name, _ in pyogrio.list_layers(out)) == ["route", "stops"]
    line = gpd.read_file(out, layer="route").iloc[0]
    stops = gpd.read_file(out, layer="stops")

    assert line["order"] == "habitat>A>B>habitat"
    assert line["energy_wh"] * 3600 == pytest.approx(spent)
    assert len(line.geometry.coords) == len(path)
    assert stops["id"].tolist() == ["habitat", "A", "B", "habitat"]
    assert stops["energy_wh"].iloc[-1] * 3600 == pytest.approx(spent)
    assert stops["leg_energy_wh"].sum() * 3600 == pytest.approx(spent)
    assert stops["service_time_min"].tolist() == [0.0, 10.0, 5.0, 0.0]
    assert [tuple(int(v) for v in graph.cell(n)) for n in path[stop_index]] == cells + [cells[0]]

    # With service at 2 W: A works 600 s (1200 J), B 300 s (600 J); the habitat is not served
    out = write_route_gpkg(tmp_path / "e5s.gpkg", graph, stations, solution, path, stop_index,
                           100.0, service_power_w=2.0)
    line = gpd.read_file(out, layer="route").iloc[0]
    stops = gpd.read_file(out, layer="stops")
    walk_s = float(graph.path_cost(path, "time_s")[-1])

    assert line["service_energy_wh"] * 3600 == pytest.approx(1800.0)
    assert line["energy_wh"] * 3600 == pytest.approx(spent + 1800.0)
    assert line["duration_s"] == pytest.approx(walk_s + 900.0)
    assert (stops["service_energy_wh"] * 3600).tolist() == pytest.approx([0.0, 1200.0, 600.0, 0.0])
    assert stops["energy_wh"].iloc[-1] * 3600 == pytest.approx(spent + 1800.0)
    assert stops["arrival_time_s"].iloc[2] == pytest.approx(stops["travel_time_s"].iloc[2] + 600.0)

    # With a timeline from the solver: B opens late, so the route waits there
    from orienteering.problem import Problem, evaluate_route
    problem = Problem(energy=dis, prize=stations.prize, budget=1e9, time=np.ones((3, 3)) * 10,
                      service_s=stations.service_s,
                      windows=np.array([[0, np.inf], [0, np.inf], [2000, np.inf]]))
    timeline = evaluate_route(problem, route)
    out = write_route_gpkg(tmp_path / "e5w.gpkg", graph, stations, solution, path, stop_index,
                           100.0, service_power_w=2.0, timeline=timeline)
    line = gpd.read_file(out, layer="route").iloc[0]
    stops = gpd.read_file(out, layer="stops")

    assert stops["arrival_time_s"].tolist() == pytest.approx([0.0, 10.0, 620.0, 2310.0])
    assert stops["wait_s"].tolist() == pytest.approx([0.0, 0.0, 1380.0, 0.0])
    assert stops["departure_time_s"].tolist() == pytest.approx([0.0, 610.0, 2300.0, 2310.0])
    assert line["duration_s"] == pytest.approx(2310.0) and line["wait_s"] == pytest.approx(1380.0)


def test_read_station_files_merges_without_repeats(tmp_path):
    from orienteering.data_io import read_station_files

    graph = grid_graph(3, 4)
    manual, e8 = tmp_path / "manual.gpkg", tmp_path / "e8.gpkg"
    stations_at(graph, [(0, 0), (1, 2)], id=["R0", "H0"], score=[5.0, 4.0],
                service_time_min=[10.0, 10.0]).to_file(manual, layer="stations")
    stations_at(graph, [(2, 3), (1, 2), (0, 3), (2, 0)], id=["E8-01", "E8-02", "R0", "E8-03"],
                score=[2.5, 1.0, 3.0, 1.5], service_time_min=[20.0] * 4,
                window_close_min=[30.0, None, None, None]).to_file(e8, layer="stations")

    s = read_station_files(graph, [manual, e8])

    assert s.id.tolist() == ["R0", "H0", "E8-01", "E8-03"]       # same cell as H0, same id as R0
    assert s.prize.tolist() == [5.0, 4.0, 2.5, 1.5]
    assert s.service_s.tolist() == [600.0, 600.0, 1200.0, 1200.0]
    assert s.windows.tolist() == [[0.0, np.inf], [0.0, np.inf], [0.0, 1800.0], [0.0, np.inf]]
