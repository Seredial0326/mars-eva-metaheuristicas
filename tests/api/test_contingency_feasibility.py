"""#119 A2: return home and rejoin check energy, time and O2 on the SAME path, and
rejoin also checks the rest of the plan. Without remaining resources nothing changes."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from api import guide  # noqa: E402
from api.plan import RejoinRequest, ReturnHomeRequest  # noqa: E402

BASE = str(REPO / "data" / "base")
HABITAT = (8143537.49, -284463.08)          # box centre
FAR = (8143217.5, -284993.2)                # Nevado Sajama, ~14 min home
NEAR, TARGET = (8143300.0, -284700.0), (8143250.0, -284800.0)


# ---------- pure checks (no data) ----------

def test_check_resources_on_one_path():
    c = guide.check_resources(70.0, 850.0, {"energy_remaining_wh": 75, "time_remaining_s": 800,
                                            "energy_reserve_wh": 4, "o2_remaining_l": None})
    assert c["energy"] == {"needed_wh": 74.0, "available_wh": 75.0, "ok": True, "reserve_wh": 4.0}
    assert c["time"]["ok"] is False
    assert c["o2"]["ok"] is None and c["o2"]["needed_l"] == pytest.approx(70 * 3.6 / 20.1, abs=1e-3)
    assert not guide.fits(c) and guide.failing(c) == ["time"]


def test_o2_is_derived_from_energy_plus_declared_leak():
    base = guide.check_resources(36.0, 600.0, {"o2_remaining_l": 100})["o2"]["needed_l"]
    leak = guide.check_resources(36.0, 600.0, {"o2_remaining_l": 100, "o2_leak_lpm": 0.5})
    assert leak["o2"]["needed_l"] == pytest.approx(base + 5.0, abs=1e-3)


def test_request_models_are_additive():
    r = ReturnHomeRequest(position=HABITAT, habitat=HABITAT)
    assert not guide.resources_given(r.resources())
    r = RejoinRequest(position=HABITAT, habitat=HABITAT, target=HABITAT,
                      energy_remaining_wh=10, continuation={"energy_wh": 5, "time_s": 60})
    assert guide.resources_given(r.resources()) and r.continuation.energy_wh == 5
    with pytest.raises(ValueError):
        ReturnHomeRequest(position=HABITAT, habitat=HABITAT, energy_remaining_wh=-1)


# ---------- on the real graph ----------

DATA = (REPO / "data" / "base" / "dem_1m.tif").exists()
needs_data = pytest.mark.skipif(not DATA, reason="team data not available")


@pytest.fixture(scope="module")
def sweep():
    """Time and energy of every candidate path home from FAR."""
    return {w: guide._return_home_path(BASE, 30.0, FAR, HABITAT, True, 1.0, w)
            for w in guide.SWEEP}


@needs_data
def test_without_resources_it_is_the_fastest_path_as_before(sweep):
    out = guide.return_home(BASE, 30.0, FAR, HABITAT)
    assert out["feasible"] is None and "checks" not in out
    assert out["time_s"] == pytest.approx(sweep[0.0]["time_s"])
    assert min(v["time_s"] for v in sweep.values()) == pytest.approx(out["time_s"])
    assert min(v["energy_wh"] for v in sweep.values()) == pytest.approx(sweep[1.0]["energy_wh"])


@needs_data
def test_fastest_kept_when_everything_fits(sweep):
    out = guide.return_home(BASE, 30.0, FAR, HABITAT,
                            resources={"energy_remaining_wh": 500, "time_remaining_s": 3000,
                                       "o2_remaining_l": 100})
    assert (out["choice"], out["feasible"], out["diagnosis"]) == ("fastest", True, None)
    assert all(c["ok"] for c in out["checks"].values())


@needs_data
def test_fast_but_too_costly_picks_a_feasible_alternative(sweep):
    fast, least = sweep[0.0]["energy_wh"], sweep[1.0]["energy_wh"]
    assert least < fast
    budget = (fast + least) / 2
    out = guide.return_home(BASE, 30.0, FAR, HABITAT,
                            resources={"energy_remaining_wh": budget, "time_remaining_s": 3000})
    assert out["feasible"] is True and out["choice"] in ("tradeoff", "least_energy")
    assert out["energy_wh"] <= budget < out["fastest"]["energy_wh"]
    assert out["fastest"]["feasible"] is False and out["fastest"]["failing"] == ["energy"]
    assert out["time_s"] >= out["fastest"]["time_s"]          # never faster than the fastest


@needs_data
@pytest.mark.parametrize("res,limiting", [
    ({"energy_remaining_wh": 10, "time_remaining_s": 3000}, ["energy"]),
    ({"energy_remaining_wh": 500, "time_remaining_s": 60}, ["time"]),
    ({"energy_remaining_wh": 500, "o2_remaining_l": 1}, ["o2"]),
    ({"energy_remaining_wh": 500, "energy_reserve_wh": 495}, ["energy"]),
])
def test_insufficient_resources_are_proven_and_never_called_safe(res, limiting):
    out = guide.return_home(BASE, 30.0, FAR, HABITAT, resources=res)
    assert out["feasible"] is False and out["choice"] == "least_energy"
    d = out["diagnosis"]
    assert d["code"] == "insufficient_resources" and d["limiting"] == limiting and d["exact"]
    assert out["fastest"]["feasible"] is False


@needs_data
def test_k_scales_energy_in_the_checks():
    res = {"energy_remaining_wh": guide.return_home(BASE, 30.0, FAR, HABITAT)["energy_wh"] * 1.2}
    assert guide.return_home(BASE, 30.0, FAR, HABITAT, resources=res)["feasible"]
    assert not guide.return_home(BASE, 30.0, FAR, HABITAT, k=1.5, resources=res)["feasible"]


@needs_data
def test_already_home_with_resources():
    out = guide.return_home(BASE, 30.0, HABITAT, HABITAT,
                            resources={"energy_remaining_wh": 0, "time_remaining_s": 0})
    assert out["feasible"] is True and out["energy_wh"] == 0 and len(out["coordinates"]) == 1


@needs_data
def test_rejoin_checks_connector_and_rest_of_plan():
    plain = guide.rejoin(BASE, 30.0, NEAR, TARGET, HABITAT)
    assert plain["feasible"] is None and "checks" not in plain
    ok = guide.rejoin(BASE, 30.0, NEAR, TARGET, HABITAT,
                      resources={"energy_remaining_wh": 500, "time_remaining_s": 3000},
                      continuation={"energy_wh": 100, "time_s": 1200})
    assert ok["feasible"] and ok["walkback_ok"] and ok["continue_ok"]
    assert ok["checks"]["energy"]["needed_wh"] == pytest.approx(ok["energy_wh"] + 100, abs=1e-3)
    # the connector fits but the rest of the plan does not: go home instead
    rest = guide.rejoin(BASE, 30.0, NEAR, TARGET, HABITAT,
                        resources={"energy_remaining_wh": 500, "time_remaining_s": 3000},
                        continuation={"energy_wh": 490, "time_s": 1200})
    assert rest["walkback_ok"] and not rest["continue_ok"] and rest["feasible"] is False
    assert rest["diagnosis"]["action"] == "return_home"
    assert rest["diagnosis"]["limiting"] == ["energy"]
    # even the way home from here does not fit
    home = guide.rejoin(BASE, 30.0, NEAR, TARGET, HABITAT,
                        resources={"energy_remaining_wh": plain["rv_wh"][0] - 1})
    assert home["first_violation_index"] == 0 and home["feasible"] is False
    assert "already does not fit" in home["diagnosis"]["message"]


@needs_data
def test_endpoints_pass_resources(tmp_path, monkeypatch):
    from fastapi.testclient import TestClient
    from api import main
    monkeypatch.setattr(main, "PLANS", tmp_path)
    client = TestClient(main.app)
    body = {"position": list(FAR), "habitat": list(HABITAT)}
    plain = client.post("/guide/return_home", json=body).json()["features"][0]["properties"]
    assert plain["feasible"] is None
    tight = client.post("/guide/return_home", json={**body, "energy_remaining_wh": 10}).json()
    p = tight["features"][0]["properties"]
    assert p["feasible"] is False and p["diagnosis"]["limiting"] == ["energy"]
    rj = client.post("/guide/rejoin", json={"position": list(NEAR), "target": list(TARGET),
                                           "habitat": list(HABITAT), "energy_remaining_wh": 500,
                                           "continuation": {"energy_wh": 490, "time_s": 60}})
    assert rj.json()["features"][0]["properties"]["continue_ok"] is False
