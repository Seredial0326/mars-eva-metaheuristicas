"""P6 best time to leave: GET /plan/departure on a saved plan. Needs data/base."""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

if not (REPO / "data" / "base" / "dem_1m.tif").exists():
    pytest.skip("team data not available", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from api import guide, main  # noqa: E402

FIXTURES = REPO / "tests" / "viz3d" / "fixtures"
client = TestClient(main.app)


@pytest.fixture
def plans(tmp_path, monkeypatch):
    """A private plans folder, so the test never overwrites the real last plan."""
    monkeypatch.setattr(main, "PLANS", tmp_path)
    return tmp_path


def save(plans, fixture):
    fc = json.loads((FIXTURES / fixture).read_text(encoding="utf-8"))
    guide.save_plan(plans, {"stations": []}, fc.get("plan", fc))


def test_departure_of_the_saved_tour(plans):
    save(plans, "plan_tour_e5.json")                  # the 120 min E5 tour
    res = client.get("/plan/departure", params={"sol": 4711})
    assert res.status_code == 200
    d = res.json()
    assert d["sol"] == 4711 and d["duration_min"] == pytest.approx(111.4, abs=0.1)
    assert len(d["rows"]) == 57                       # every 15 min, 05:00-19:00
    assert d["best"]["sunlit_share"] == 1.0
    assert d["lit_window_clock"] == ["06:45", "15:15"] and d["best_clock"] == "11:00"
    assert d["best_mission_clock"] == "10:22"
    for r in d["rows"]:
        assert r["sunlit_share"] + r["shadow_share"] + r["dark_share"] == pytest.approx(1.0, abs=1e-3)


def test_default_sol_and_e4_round_trip(plans):
    save(plans, "plan_e4.json")                       # a single-goal E4 plan also has a clock
    d = client.get("/plan/departure").json()
    assert d["sol"] == main.weather.DEFAULT_SOL and d["rows"]


def test_no_plan_and_untimed_route(plans):
    assert client.get("/plan/departure").status_code == 404
    save(plans, "plan_fixed_route.json")              # Curiosity's fixed test route: no t_s
    res = client.get("/plan/departure")
    assert res.status_code == 422 and "timed route" in res.json()["detail"]
    assert client.get("/plan/departure", params={"sol": 0}).status_code == 422
