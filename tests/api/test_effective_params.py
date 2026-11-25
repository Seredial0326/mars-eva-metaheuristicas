"""#119 A1: plan parameters the engine does not use are rejected, slope 0 means the same
everywhere (rejected), and /plan reports the configuration it really used."""

import sys
from pathlib import Path

import pytest
from pydantic import ValidationError

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from api import adaptive  # noqa: E402
from api.plan import (MARS_G, PlanRequest, RejoinRequest, ReturnHomeRequest,  # noqa: E402
                      WalkbackRequest)

CENTRE = (8143537.49, -284463.08)
BASE = {"start": CENTRE, "energy_budget_wh": 1000.0}
POS = {"position": CENTRE, "habitat": CENTRE}
MODELS = [
    (PlanRequest, BASE),
    (WalkbackRequest, {"current_position": CENTRE, "energy_remaining_wh": 500.0}),
    (ReturnHomeRequest, POS),
    (RejoinRequest, {**POS, "target": CENTRE}),
    (adaptive.UpdateRequest, {"used": 0.0, "budget": 900.0, "return_predicted": 10.0}),
]


@pytest.mark.parametrize("model,body", MODELS)
@pytest.mark.parametrize("limit", [0, -5, 90.5])
def test_slope_limit_out_of_range_is_rejected_everywhere(model, body, limit):
    with pytest.raises(ValidationError):
        model(**body, max_cell_slope_deg=limit)


@pytest.mark.parametrize("model,body", MODELS)
def test_slope_limit_null_and_valid_values(model, body):
    assert model(**body).max_cell_slope_deg == 30.0
    assert model(**body, max_cell_slope_deg=None).max_cell_slope_deg is None
    assert model(**body, max_cell_slope_deg=0.5).max_cell_slope_deg == 0.5
    assert model(**body, max_cell_slope_deg=90).max_cell_slope_deg == 90


@pytest.mark.parametrize("g", [1.62, 9.81, 3.7])
def test_unsupported_gravity_is_rejected(g):
    with pytest.raises(ValidationError, match="only Mars gravity"):
        PlanRequest(**BASE, gravity_m_s2=g)


def test_unsigned_speed_rule_is_rejected():
    with pytest.raises(ValidationError, match="signed slope"):
        PlanRequest(**BASE, apollo_speed_uses_signed_slope=False)


def test_defaults_still_accepted_and_effective_config():
    req = PlanRequest(**BASE, gravity_m_s2=3.71, apollo_speed_uses_signed_slope=True,
                      max_cell_slope_deg=None, human_cost=False, margin=0.2)
    assert req.effective("E3", 150.0) == {
        "gravity_m_s2": MARS_G, "apollo_speed_uses_signed_slope": True,
        "max_cell_slope_deg": None, "human_cost": False, "cost_model": "E3",
        "margin": 0.2, "service_power_w": 150.0}


# ---------- endpoints (need the team data) ----------

DATA = (REPO / "data" / "e2" / "trajectory.geojson").exists() and \
    (REPO / "data" / "base" / "dem_1m.tif").exists()
needs_data = pytest.mark.skipif(not DATA, reason="team data not available")


@pytest.fixture
def client(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main
    monkeypatch.setattr(main, "PLANS", tmp_path)          # never touch the real saved plan
    return TestClient(main.app)


@needs_data
def test_plan_reports_effective_config(client):
    fc = client.post("/plan", json={**BASE, "goal": [CENTRE[0] + 100, CENTRE[1]]}).json()
    eff = fc["properties"]["effective"]
    assert eff["gravity_m_s2"] == MARS_G and eff["apollo_speed_uses_signed_slope"] is True
    assert eff["max_cell_slope_deg"] == 30.0 and eff["margin"] == 0.1
    assert eff["cost_model"] == fc["properties"]["cost_model"]
    assert eff["service_power_w"] > 0
    fixed = client.post("/plan", json={**BASE, "stations": []}).json()
    assert fixed["properties"]["effective"]["cost_model"] is None


@needs_data
@pytest.mark.parametrize("path,body", [
    ("/plan", {**BASE, "gravity_m_s2": 1.62}),
    ("/plan", {**BASE, "apollo_speed_uses_signed_slope": False}),
    ("/plan", {**BASE, "max_cell_slope_deg": 0}),
    ("/walkback", {"current_position": CENTRE, "energy_remaining_wh": 500, "max_cell_slope_deg": 0}),
    ("/guide/return_home", {**POS, "max_cell_slope_deg": 0}),
    ("/guide/rejoin", {**POS, "target": CENTRE, "max_cell_slope_deg": 0}),
    ("/walkback/update", {"used": 0, "budget": 900, "return_predicted": 10, "max_cell_slope_deg": 0}),
])
def test_endpoints_reject_instead_of_ignoring(client, path, body):
    assert client.post(path, json=body).status_code == 422


@needs_data
def test_null_limit_still_means_no_block(client):
    body = {"current_position": [CENTRE[0] + 50, CENTRE[1]], "energy_remaining_wh": 500}
    none = client.post("/walkback", json={**body, "max_cell_slope_deg": None})
    assert none.status_code == 200
    assert none.json()["properties"]["max_cell_slope_deg"] is None
