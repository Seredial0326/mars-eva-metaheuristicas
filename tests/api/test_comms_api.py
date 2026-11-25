"""E11 radio endpoints (#76): /comms/check, /layers/comms(.png). Need data/base."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

if not (REPO / "data" / "base" / "dem_1m.tif").exists():
    pytest.skip("team data not available", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from api import main  # noqa: E402

client = TestClient(main.app)
CENTRE = [8143537.49, -284463.08]
# 400 m south-west from the centre: crosses the ridge that hides part of the demo route
ROUTE = [[CENTRE[0] - k * 0.6, CENTRE[1] - k * 0.8] for k in range(0, 500)]
T_S = [k * 1.5 for k in range(len(ROUTE))]


def check(**body):
    return client.post("/comms/check", json=body)


def test_check_given_route_has_per_vertex_arrays():
    res = check(route={"coordinates": ROUTE, "t_s": T_S}, habitat=CENTRE, gap_m=20)
    assert res.status_code == 200
    fc = res.json()
    p = fc["properties"]
    assert len(p["radio_ok"]) == len(ROUTE) and len(p["pair_state"]) == len(ROUTE)
    assert set(p["pair_state"]) <= {"direct", "relay", "none"}
    assert p["radio_ok"][0] is True                        # at the habitat
    assert 0 < p["coverage"] < 1
    kinds = [f["properties"]["kind"] for f in fc["features"]]
    assert kinds == ["no_radio", "pair_unlinked", "habitat"]
    no_radio = fc["features"][0]["properties"]
    assert no_radio["length_m"] <= no_radio["route_length_m"]
    for seg in no_radio["stretches"]:                       # t_s on every stretch
        assert seg["end_t_s"] >= seg["start_t_s"]
    # every vertex marked without radio lies on a no_radio stretch
    assert (not all(p["radio_ok"])) == (no_radio["stretches"] != [])


def test_pair_never_worse_than_alone_within_the_limit():
    p = check(route={"coordinates": ROUTE}, habitat=CENTRE, gap_m=20).json()["properties"]
    none = sum(s == "none" for s in p["pair_state"])
    alone = sum(not ok for ok in p["radio_ok"])
    assert none <= alone


def test_plan_request_keys_are_accepted():
    body = {"route": {"coordinates": ROUTE[:50]}, "habitat": CENTRE, "human_cost": False,
            "max_cell_slope_deg": 30, "energy_budget_wh": 1000, "stations": []}
    assert check(**body).status_code == 200


def test_last_plan_is_the_default_route():
    plan = client.post("/plan", json={"start": CENTRE, "energy_budget_wh": 1000,
                                      "goal": [CENTRE[0] + 150, CENTRE[1]]})
    assert plan.status_code == 200
    route = next(f for f in plan.json()["features"] if f["properties"]["kind"] == "route")
    fc = check().json()
    assert len(fc["properties"]["radio_ok"]) == len(route["geometry"]["coordinates"])
    assert fc["properties"]["habitat"] == CENTRE


@pytest.mark.parametrize("body", [
    {"route": {"coordinates": ROUTE}, "habitat": [0.0, 0.0]},
    {"route": {"coordinates": [[0.0, 0.0], [1.0, 1.0]]}, "habitat": CENTRE},
    {"route": {"coordinates": ROUTE, "t_s": [0.0, 1.0]}, "habitat": CENTRE},
    {"route": {"coordinates": []}, "habitat": CENTRE},
    {"route": {"coordinates": ROUTE}, "gap_m": -5},
])
def test_invalid_requests(body):
    assert check(**body).status_code == 422


def test_no_route_and_no_plan_is_404(tmp_path, monkeypatch):
    monkeypatch.setattr(main, "PLANS", tmp_path)
    assert check().status_code == 404


def test_coverage_layer():
    res = client.get("/layers/comms.png", params={"x": CENTRE[0], "y": CENTRE[1]})
    assert res.status_code == 200 and res.content[:8] == b"\x89PNG\r\n\x1a\n"
    info = client.get("/layers/comms", params={"x": CENTRE[0], "y": CENTRE[1]}).json()
    assert info["coverage"] == pytest.approx(0.2256, abs=0.001)   # E11 note, centre
    assert client.get("/layers/comms").status_code == 200          # default habitat
    assert client.get("/layers/comms", params={"x": CENTRE[0]}).status_code == 422
    assert client.get("/layers/comms.png", params={"x": 0, "y": 0}).status_code == 422


def test_without_gdal_only_e11_answers_503(monkeypatch):
    monkeypatch.setattr(main.e11, "AVAILABLE", False)
    assert check(route={"coordinates": ROUTE[:5]}, habitat=CENTRE).status_code == 503
    assert client.get("/layers/comms").status_code == 503
    assert client.get("/layers/comms.png").status_code == 503
    assert client.get("/health").status_code == 200


def test_api_starts_when_gdal_is_missing():
    """Fresh interpreter where `import osgeo` fails (plain pip install): api.main still
    imports and the radio stays on, with the NumPy port of GDAL's viewshed."""
    import subprocess
    code = ("import sys; sys.modules['osgeo'] = None; sys.path.insert(0, r'%s'); "
            "import api.main as m; assert m.e11.AVAILABLE; "
            "assert m.e11.comms.ENGINE == 'numpy'; "
            "assert any(r.path == '/plan' for r in m.app.routes); print('ok')" % REPO)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True,
                         cwd=REPO, timeout=120)
    assert out.stdout.strip().endswith("ok"), out.stderr[-2000:]
