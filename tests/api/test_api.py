"""API tests with FastAPI's TestClient. Need data/base, data/tiles and data/e2."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

if not (REPO / "data" / "e2" / "trajectory.geojson").exists():
    pytest.skip("team data not available", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402

client = TestClient(app)
CENTRE = [8143537.49, -284463.08]          # middle of the 2 x 2 km box


def plan_body(**overrides):
    body = {"start": CENTRE, "energy_budget_wh": 1000.0, "margin": 0.1,
            "stations": [{"id": "S1", "x": CENTRE[0] + 100, "y": CENTRE[1], "score": 5}]}
    body.update(overrides)
    return body


def test_health_and_layers():
    assert client.get("/health").json()["status"] == "ok"
    layers = client.get("/layers").json()
    assert layers["grid"]["grid_1m"]["width"] == 2000
    assert "Mars" in layers["crs_wkt"]


def test_plan_without_stations_returns_fixed_route_in_mars_metres():
    fc = client.post("/plan", json=plan_body(stations=[])).json()
    kinds = [f["properties"]["kind"] for f in fc["features"]]
    assert kinds == ["route", "start"]
    route = fc["features"][0]
    x, y = route["geometry"]["coordinates"][0]
    assert 8142537 < x < 8144538 and -285464 < y < -283463   # inside the box, metres
    assert fc["properties"]["energy_usable_wh"] == pytest.approx(900.0)
    assert fc["properties"]["feasible"] is None              # never claim feasibility yet


@pytest.mark.parametrize("bad", [
    {"energy_budget_wh": 0},
    {"margin": 1.0},
    {"gravity_m_s2": -3.71},
    {"start": [0.0, 0.0]},                                   # outside the box
    {"stations": [{"id": "A", "x": CENTRE[0], "y": CENTRE[1], "score": 1},
                  {"id": "A", "x": CENTRE[0], "y": CENTRE[1], "score": 2}]},
    {"stations": [{"id": "A", "x": CENTRE[0], "y": CENTRE[1], "score": -1}]},
])
def test_plan_rejects_invalid_requests(bad):
    assert client.post("/plan", json=plan_body(**bad)).status_code == 422


def test_cost_layer_png_and_legend():
    res = client.get("/layers/cost.png")
    assert res.status_code == 200 and res.content[:8] == b"\x89PNG\r\n\x1a\n"
    legend = client.get("/layers/cost").json()
    assert legend["vmin_j_per_m"] == pytest.approx(338.75, abs=0.1)   # guide c_min,h


def test_blocked_mask_follows_the_limit():
    frac = lambda v: client.get("/layers/blocked", params={"max_cell_slope_deg": v}).json()["blocked_fraction"]
    assert frac(30) == pytest.approx(0.12, abs=0.02)                  # JB: 12 % > 30 deg
    assert frac(15) > frac(30) > frac(60)
    assert client.get("/layers/blocked.png", params={"max_cell_slope_deg": 120}).status_code == 422


def test_plan_accepts_disabled_block():
    fc = client.post("/plan", json=plan_body(max_cell_slope_deg=None)).json()
    assert fc["properties"]["max_cell_slope_deg"] is None


def station_set(**overrides):
    body = {"rubric": {"ridge": 5, "hollow": 4, "contact": 3, "curiosity": 3},
            "stations": [{"id": "R1", "type": "ridge", "x": CENTRE[0], "y": CENTRE[1]},
                         {"id": "H1", "type": "hollow", "x": CENTRE[0] + 50, "y": CENTRE[1],
                          "service_time_min": 15, "note": "dark sand"}]}
    body.update(overrides)
    return body


def test_stations_roundtrip_gpkg(tmp_path, monkeypatch):
    import geopandas as gpd
    import api.main as main
    monkeypatch.setattr(main, "STATIONS", tmp_path)          # never touch the real file
    assert client.get("/stations").json()["stations"] == []
    rubric = {"ridge": 7, "hollow": 4, "contact": 3, "curiosity": 3}  # edited live
    assert client.post("/stations", json=station_set(rubric=rubric)).json()["saved"] == 2
    gdf = gpd.read_file(tmp_path / "stations_manual.gpkg", layer="stations")
    assert list(gdf["score"]) == [7.0, 4.0]                  # score comes from the rubric
    assert "Mars" in gdf.crs.to_wkt()
    back = client.get("/stations").json()
    assert back["rubric"]["ridge"] == 7 and back["stations"][1]["note"] == "dark sand"
    assert client.get("/stations/stations_manual.gpkg").status_code == 200


@pytest.mark.parametrize("bad", [
    {"stations": [{"id": "X", "type": "crater", "x": CENTRE[0], "y": CENTRE[1]}]},
    {"stations": [{"id": "X", "type": "ridge", "x": 0.0, "y": 0.0}]},
    {"rubric": {"ridge": -1, "hollow": 4, "contact": 3, "curiosity": 3}},
    {"stations": [{"id": "X", "type": "ridge", "x": CENTRE[0], "y": CENTRE[1]},
                  {"id": "X", "type": "hollow", "x": CENTRE[0], "y": CENTRE[1]}]},
])
def test_stations_reject_invalid(bad, tmp_path, monkeypatch):
    import api.main as main
    monkeypatch.setattr(main, "STATIONS", tmp_path)
    assert client.post("/stations", json=station_set(**bad)).status_code == 422


def test_candidates_endpoint(tmp_path, monkeypatch):
    import json as _json
    import api.main as main
    monkeypatch.setattr(main, "STATIONS", tmp_path)
    assert client.get("/stations/candidates").status_code == 404
    (tmp_path / "candidates.json").write_text(_json.dumps(
        {"candidates": [{"id": "R0", "type": "ridge", "x": CENTRE[0], "y": CENTRE[1]}]}))
    assert client.get("/stations/candidates").json()["candidates"][0]["id"] == "R0"


def test_curiosity_drill_targets_match_places():
    """Raw PLACES data when present; else the released candidates.json; else skip."""
    import json as _json
    raw = REPO / "data" / "03_curiosity" / "places_pds" / "data_mechanisms" / "mech_drill.csv"
    released = REPO / "data" / "stations" / "candidates.json"
    if raw.exists():
        from api.candidates import curiosity_targets
        targets = curiosity_targets()
    elif released.exists():
        targets = _json.loads(released.read_text(encoding="utf-8"))["candidates"]
    else:
        pytest.skip("needs raw PLACES data or release stations-candidates-v1")
    t = {c["id"]: c for c in targets}
    ridge, hollow = t["R0"], t["H0"]
    d = ((ridge["x"] - hollow["x"]) ** 2 + (ridge["y"] - hollow["y"]) ** 2) ** 0.5
    assert 8 < d < 12                      # NASA: drilled ridge ~10 m from the drilled hollow


def test_walkback_fields_and_boundaries():
    body = {"current_position": [CENTRE[0] + 300, CENTRE[1]], "energy_remaining_wh": 150}
    fc = client.post("/walkback", json=body).json()
    p = fc["properties"]
    assert 400 <= p["return_time_s"] <= 600            # 300 m at ~0.75 m/s, plus detours
    assert 30 <= p["return_energy_wh"] <= 60           # 300 m x ~390 J/m = 32.5 Wh on flat ground
    assert p["contingency_ok"] and p["energy_ok"]
    kinds = {f["properties"]["kind"]: f for f in fc["features"]}
    assert kinds["emergency_time_boundary"]["geometry"]["coordinates"]       # red line exists
    assert kinds["energy_safe_boundary"]["properties"]["energy_remaining_wh"] == 150


def test_walkback_return_is_directed():
    import numpy as np
    import api.main as main
    from api import walkback as wb
    g = wb.grid(str(main.BASE), 30.0)
    base = g.node(*main._box_centre())
    r_t, r_e = wb.return_fields(str(main.BASE), 30.0, base)
    assert r_t.flat[base] == 0 and r_e.flat[base] == 0
    f_e = wb.forward_energy(str(main.BASE), 30.0, base, np.inf)            # base -> v
    both = np.isfinite(f_e) & np.isfinite(r_e)
    assert np.abs(f_e[both] - r_e[both]).max() > 1.0                       # going != coming back


def test_walkback_rejects_bad_requests():
    assert client.post("/walkback", json={"current_position": [0, 0],
                                          "energy_remaining_wh": 10}).status_code == 422
    assert client.post("/walkback", json={"current_position": CENTRE,
                                          "energy_remaining_wh": -1}).status_code == 422


def test_walkback_boundaries_are_few_closed_rings():
    body = {"current_position": [CENTRE[0] + 300, CENTRE[1]], "energy_remaining_wh": 150}
    fc = client.post("/walkback", json=body).json()
    for f in fc["features"][:2]:
        rings = f["geometry"]["coordinates"]
        assert 1 <= len(rings) <= 3                        # not thousands of fragments
        assert all(r[0] == r[-1] for r in rings)           # closed along scarps and box edge


def test_radiation_summary_and_scenarios():
    if not (REPO / "data" / "e12" / "sep_alert.json").exists():
        pytest.skip("E12 outputs not generated")
    r = client.get("/radiation").json()
    assert 5 < r["background_ugy_h"] < 9                      # E12: 6.52 uGy/h in the boxwork
    rates = [s["rate_ugy_h"] for s in r["scenarios"]]
    assert rates == sorted(rates) and r["scenarios"][0]["measured"]
    assert abs(r["curve"][-1]["dose_ugy"] - r["provisional_eva"]["dose_ugy"]) < 0.1


def test_plan_live_with_e4_round_trip():
    # An explicit goal always uses E4's single-goal round trip (with or without E5).
    body = plan_body(goal=[8143217.5, -284993.2],
                     stations=[{"id": "R0", "x": 8143217.5, "y": -284993.2, "score": 5,
                                "service_time_min": 15}])
    fc = client.post("/plan", json=body).json()
    route = next(f for f in fc["features"] if f["properties"]["kind"] == "route")["properties"]
    assert fc["properties"]["source"].startswith("E4") and route["feasible"]
    assert 150 < route["energy_wh"] < 300                     # ~214 Wh to Nevado Sajama and back
    n = len(route["used_wh"])
    assert len(route["rv_wh"]) == len(route["t_s"]) == n       # per-vertex profile for the HUD
    assert all(b >= a for a, b in zip(route["used_wh"], route["used_wh"][1:]))   # budget only shrinks
    goal = next(f for f in fc["features"] if f["properties"]["kind"] == "goal")["properties"]
    assert goal["moved_m"] >= 0


def test_plan_live_infeasible_budget_is_422():
    body = plan_body(energy_budget_wh=150,
                     stations=[{"id": "R0", "x": 8143217.5, "y": -284993.2, "score": 5}])
    assert client.post("/plan", json=body).status_code == 422


def test_rocks_layer():
    if not (REPO / "data" / "e9" / "rocas.tif").exists():
        pytest.skip("E9 release (e9-rocks-v1) not downloaded")
    res = client.get("/layers/rocks.png")
    assert res.status_code == 200 and res.content[:4] == b"\x89PNG"
    info = client.get("/layers/rocks").json()
    assert info["block_m"] == 10 and 0 < info["mean_cover_pct"] < 5          # boulders cover well under 5 % of the box
    assert 0 < info["share_of_squares_over_5pct_pct"] < info["share_of_squares_with_dots_pct"] < 100


def test_sand_layer():
    if not (REPO / "data" / "e8" / "sand.tif").exists():
        pytest.skip("E8 release not downloaded")
    res = client.get("/layers/sand.png")
    assert res.status_code == 200 and res.content[:4] == b"\x89PNG"
    assert 0 < client.get("/layers/sand").json()["share_of_box_with_sand_pct"] < 50


def test_check_data_script_runs():
    from api import check_data
    assert check_data.main() in (0, 1)


def test_guide_saved_plan_and_return_home(tmp_path, monkeypatch):
    import api.main as main
    monkeypatch.setattr(main, "PLANS", tmp_path)               # never touch the real saved plan
    assert client.get("/plan/last").status_code == 404
    st = [{"id": "R0", "x": 8143217.5, "y": -284993.2, "score": 5, "type": "ridge"}]
    client.post("/plan", json=plan_body(stations=st))
    saved = client.get("/plan/last").json()
    station = next(f for f in saved["plan"]["features"] if f["properties"]["kind"] == "station")
    assert station["properties"]["type"] == "ridge"            # the guide card needs the type
    home = client.post("/guide/return_home", json={"position": [8143217.5, -284993.2],
                                                   "habitat": CENTRE}).json()["features"][0]
    p = home["properties"]
    assert 600 < p["time_s"] < 1200 and len(p["t_s"]) == len(home["geometry"]["coordinates"])
    assert p["t_s"][-1] == pytest.approx(p["time_s"], abs=1.0)  # profile ends at the habitat
    assert client.post("/guide/return_home", json={"position": [0, 0], "habitat": CENTRE}).status_code == 422


@pytest.mark.parametrize("page", ["index.html", "guide.html", "card.html"])
def test_pages_work_offline(page):
    import re
    html = (REPO / "web" / page).read_text(encoding="utf-8")
    assert not re.search(r'<(script|link)[^>]+(src|href)="https?://', html)   # no CDN at demo time
    assert client.get("/vendor/deck.gl-9.1.14.min.js").status_code == 200


def test_plan_tour_with_e5_respects_duration():
    from api import tour
    if not tour.AVAILABLE:
        pytest.skip("E5 (src/orienteering) not in this checkout yet")
    st = [{"id": "R0", "x": 8143217.5, "y": -284993.2, "score": 5, "type": "ridge", "service_time_min": 10},
          {"id": "H0", "x": 8143219.3, "y": -284983.2, "score": 4, "type": "hollow", "service_time_min": 10},
          {"id": "Q1", "x": 8143367.9, "y": -284509.5, "score": 3, "type": "curiosity", "service_time_min": 10}]
    long_ = client.post("/plan", json=plan_body(stations=st, max_duration_min=240)).json()
    short = client.post("/plan", json=plan_body(stations=st, max_duration_min=30)).json()
    pl, ps = long_["features"][0]["properties"], short["features"][0]["properties"]
    assert len(pl["visit_order"]) == 3 and pl["feasible"]
    assert len(ps["visit_order"]) < 3 and ps["time_s"] <= 30 * 60 + 1      # duration binds
    assert len(pl["stop_index"]) == len(pl["visit_order"])
    assert all(b >= a for a, b in zip(pl["used_wh"], pl["used_wh"][1:]))


def test_human_cost_graph_vs_e3():
    from api import planner
    if planner.e1_weights_path(REPO / "data" / "base") is None:
        pytest.skip("E1 weights (e1-sand-v1) not downloaded")
    import numpy as np
    base = str(REPO / "data" / "base")
    e3, hu = planner.graph(base, 30.0, False), planner.graph(base, 30.0, True)
    assert e3.cost_model == "E3" and "E1" in hu.cost_model
    a, b = e3.csr("energy_j"), hu.csr("energy_j")
    assert a.nnz == b.nnz                                       # same edges
    ratio = b.data / a.data
    assert ratio.min() >= 1 - 1e-6 and ratio.max() <= 1.12      # factor 1 .. 1.115 (sand)
    assert np.array_equal(e3.csr("time_s").data, hu.csr("time_s").data)   # E1 prices energy only


def test_plan_reports_cost_model_and_walkback_accepts_flag():
    body = plan_body(goal=[8143217.5, -284993.2],
                     stations=[{"id": "R0", "x": 8143217.5, "y": -284993.2, "score": 5}])
    for human in (False, True):
        fc = client.post("/plan", json={**body, "human_cost": human}).json()
        assert fc["properties"]["human_cost"] is human and fc["properties"]["cost_model"]
    wb = client.post("/walkback", json={"current_position": [CENTRE[0] + 300, CENTRE[1]],
                                        "energy_remaining_wh": 150, "human_cost": False}).json()
    assert "E3" in wb["properties"]["warnings"][0]


def test_walkback_compares_fixed_radius_rules():
    fc = client.post("/walkback", json={"current_position": [CENTRE[0] + 300, CENTRE[1]],
                                        "energy_remaining_wh": 150}).json()
    rules = [f["properties"] for f in fc["features"] if f["properties"]["kind"] == "fixed_radius"]
    assert {r["radius_m"] for r in rules} == {1350.0, 1700.0}
    for r in rules:
        assert 0 <= r["falsely_safe_pct"] <= 100
        assert abs(r["falsely_safe_pct"] - r["falsely_safe_no_way_back_pct"]
                   - r["falsely_safe_too_slow_pct"]) < 1e-6


def test_plan_refuses_a_tour_that_fails_the_walkback(monkeypatch):
    """If E5's re-plans all fail, plan_tour returns the last tour with feasible=False:
    /plan must refuse it (422), never hand an unsafe tour to the HUD or the guide."""
    from api import tour

    def unsafe(req, g, solver="auto"):
        line = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                "properties": {"kind": "route", "feasible": False, "first_violation": 1,
                               "order": ["habitat", "R0", "habitat"], "stop_index": [0, 1, 1]}}
        return {"type": "FeatureCollection", "features": [line]}, {"walkback_retries": 5}

    class NoRoute(Exception):
        pass

    monkeypatch.setattr(tour, "AVAILABLE", True)
    monkeypatch.setattr(tour, "DELEGATE", True)
    monkeypatch.setattr(tour, "_e5_plan_tour", unsafe, raising=False)
    monkeypatch.setattr(tour, "_E4NoRoute", NoRoute, raising=False)
    st = [{"id": "R0", "x": 8143217.5, "y": -284993.2, "score": 5, "type": "ridge", "service_time_min": 10}]
    r = client.post("/plan", json=plan_body(stations=st))
    assert r.status_code == 422
    assert "fails the walkback" in r.json()["detail"] and "vertex 1" in r.json()["detail"]


def test_weather_from_rems():
    from api import weather
    if weather.find_feed(REPO / "data") is None:
        pytest.skip("REMS feed (rems-v1) not downloaded")
    w = client.get("/weather", params={"sol": 4711, "eva_min": 120}).json()
    d = w["day"]
    assert d["sol"] == 4711 and d["earth_date"] == "2025-11-06"
    assert d["air_min_c"] < d["air_max_c"] and d["ground_min_c"] < d["ground_max_c"]
    assert 11 < d["daylight_h"] < 13                       # near the equator: ~12 h of light
    assert any("fits in daylight" in n for n in w["notes"])
    lo, hi = w["campaign"]["sols"]
    assert all(lo <= p["sol"] <= hi for p in w["campaign"]["series"])
    assert w["campaign"]["n_sols"] > 200
    near = client.get("/weather", params={"sol": 10_000}).json()["day"]   # beyond the feed
    assert near["sol"] == w["sol_range"][1] and near["requested_sol"] == 10_000
    assert client.get("/weather", params={"sol": 0}).status_code == 422


def test_data_sources_counts_only_what_is_on_disk():
    d = client.get("/data_sources").json()
    assert d["n_types"] == len(d["sources"]) >= 3          # the challenge asks for 3 or more
    assert d["n_missions"] == len({m for s in d["sources"] for m in s["mission"].split(" / ")})
    assert {"Orbital image", "Elevation"} <= {s["type"] for s in d["sources"]}
    planned = {p["type"] for p in d["planned"]}
    assert not planned & {s["type"] for s in d["sources"]}   # planned is never counted


def test_minerals_are_regional_context_only():
    from api import minerals
    if minerals.find(REPO / "data") is None:
        pytest.skip("mineral detections (minerals-v1) not downloaded")
    m = client.get("/minerals", params={"radius_km": 100}).json()
    assert all(p["distance_km"] <= 100 for p in m["points"])
    assert all(p["distance_km"] > 1.5 for p in m["points"])        # none inside the 2 x 2 km box
    assert set(m["counts"]) == set(m["classes"])
    assert m["nearest"]["hydrous"]["distance_km"] < m["nearest"]["phyllosilicate"]["distance_km"]
    lon, lat = m["box_centre_lonlat"]
    assert 137.3 < lon < 137.5 and -4.9 < lat < -4.7                # Gale, the boxwork
    assert client.get("/minerals", params={"radius_km": 1000}).status_code == 422


def test_thermal_themis_layer_and_sand_check():
    from api import thermal
    if thermal.find(REPO / "data") is None:
        pytest.skip("THEMIS tile (themis-v1) not downloaded")
    png = client.get("/layers/thermal.png")
    assert png.status_code == 200 and png.content[:4] == b"\x89PNG"
    t = client.get("/thermal").json()
    assert t["mission"] == "Mars Odyssey" and 75 < t["m_per_px"] < 90
    c = t.get("check_vs_e8_sand")
    if c is not None:                                   # needs E8's sand.tif
        assert 500 < c["pixels"] < 700                  # ~25 x 25 THEMIS pixels in the box
        assert abs(c["spearman_brightness_vs_sand"]) < 0.2   # no relation at 81 m


def test_e8_stations_endpoint():
    from api import stations as stmod
    if stmod.load_e8(REPO / "data" / "stations") is None:
        pytest.skip("E8 stations (stations-e8-v0) not downloaded")
    out = client.get("/stations/e8").json()["stations"]
    assert len(out) >= 10
    assert all(s["type"] == "contact" and s["id"].startswith("E8-") for s in out)
    assert all("E8 score" in s["note"] and 1 <= s["e8_score"] <= 5 for s in out)
    b = client.get("/layers").json()["grid"]["bbox"]
    assert all(b["xmin"] <= s["x"] <= b["xmax"] and b["ymin"] <= s["y"] <= b["ymax"] for s in out)


def test_walks_are_kept_for_the_debrief(tmp_path, monkeypatch):
    from api import main as m
    monkeypatch.setattr(m, "WALKS", tmp_path)
    assert client.get("/walks/last").status_code == 404
    rec = {"summary": {"plan": {"timeS": 600}, "walked": {"timeS": 660}},
           "points": [[8143537.5, -284463.1, 0.0, 0.0, "plan", True], [8143540.5, -284463.1, 4.0, 0.3, "plan", False]]}
    name = client.post("/walks", json=rec).json()["saved"]
    assert (tmp_path / name).exists() and (tmp_path / "last_walk.json").exists()
    last = client.get("/walks/last").json()
    assert last["summary"]["walked"]["timeS"] == 660 and len(last["points"]) == 2
    assert client.post("/walks", json={"points": []}).status_code == 422      # summary is required


# --- #119 A4: /plan says why there is no plan ----------------------------------------------

def test_plan_no_tour_has_a_structured_diagnosis():
    from api import tour
    if not tour.DELEGATE:
        pytest.skip("E5's plan_tour not available")
    st = [{"id": "R0", "x": 8143217.5, "y": -284993.2, "score": 5, "type": "ridge", "service_time_min": 10},
          {"id": "N1", "x": CENTRE[0] + 100, "y": CENTRE[1], "score": 1, "type": "ridge", "service_time_min": 10}]
    r = client.post("/plan", json=plan_body(energy_budget_wh=5.0, stations=st))
    assert r.status_code == 422
    body = r.json()
    assert body["detail"].startswith("no feasible tour:")          # the text contract is unchanged
    d = body["diagnosis"]
    assert d["code"] == "insufficient_resources" and d["exact"] and d["limiting"] == ["energy"]
    assert d["closest"]["id"] == "N1" and d["closest"]["needs"]["energy_wh"] > d["closest"]["available"]["energy_wh"]
    assert d["actions"] and "energy budget" in d["actions"][0]


def test_plan_outside_the_box_names_the_field():
    st = [{"id": "A", "x": CENTRE[0] + 100, "y": CENTRE[1], "score": 1},
          {"id": "far", "x": CENTRE[0] + 5000, "y": CENTRE[1], "score": 1}]
    r = client.post("/plan", json=plan_body(stations=st))
    assert r.status_code == 422
    assert r.json()["detail"] == "station far is outside the study box"
    assert r.json()["diagnosis"] == {"code": "invalid_input", "exact": True, "field": "stations[1]",
                                     "message": "station far is outside the study box"}
    r = client.post("/plan", json=plan_body(start=[CENTRE[0] + 5000, CENTRE[1]]))
    assert r.json()["diagnosis"]["field"] == "start"


def test_plan_unsafe_tour_passes_the_walkback_diagnosis(monkeypatch):
    from api import tour
    diag = {"code": "walkback", "exact": True, "message": "every tour tried fails the walkback",
            "first_violation": 1, "deficit_wh": 2.5, "retries": 5, "actions": ["about 2.8 Wh more"]}

    def unsafe(req, g, solver="auto"):
        line = {"type": "Feature", "geometry": {"type": "LineString", "coordinates": [[0, 0], [1, 1]]},
                "properties": {"kind": "route", "feasible": False, "first_violation": 1, "diagnosis": diag,
                               "order": ["habitat", "R0", "habitat"], "stop_index": [0, 1, 1]}}
        return {"type": "FeatureCollection", "features": [line]}, {"walkback_retries": 5, "diagnosis": diag}

    class NoRoute(Exception):
        pass

    monkeypatch.setattr(tour, "AVAILABLE", True)
    monkeypatch.setattr(tour, "DELEGATE", True)
    monkeypatch.setattr(tour, "_e5_plan_tour", unsafe, raising=False)
    monkeypatch.setattr(tour, "_E4NoRoute", NoRoute, raising=False)
    st = [{"id": "R0", "x": 8143217.5, "y": -284993.2, "score": 5, "type": "ridge", "service_time_min": 10}]
    r = client.post("/plan", json=plan_body(stations=st))
    assert r.status_code == 422 and "fails the walkback" in r.json()["detail"]
    assert r.json()["diagnosis"] == diag


def test_plan_e4_round_trip_without_diagnosis_keeps_the_old_body():
    body = plan_body(energy_budget_wh=150, goal=[8143217.5, -284993.2],
                     stations=[{"id": "R0", "x": 8143217.5, "y": -284993.2, "score": 5}])
    r = client.post("/plan", json=body)
    assert r.status_code == 422 and set(r.json()) == {"detail"}
