"""X2 (#101): POST /walkback/update and the optional k on /walkback and return_home."""

import sys
from math import exp, log
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

if not ((REPO / "data" / "base" / "dem_1m.tif").exists() and (REPO / "data" / "tiles").is_dir()):
    pytest.skip("team data not available (data/base and data/tiles)", allow_module_level=True)

from fastapi.testclient import TestClient  # noqa: E402

from api import main  # noqa: E402

client = TestClient(main.app)
CENTRE = [8143537.49, -284463.08]
EAST = [CENTRE[0] + 300, CENTRE[1]]


def upd(**body):
    return client.post("/walkback/update", json=body)


def test_prior_only_gives_the_prior_and_no_alert():
    out = upd(used=10, budget=900, return_predicted=100).json()
    assert out["posterior"] == {"mu": 0.0, "sd": 0.3, "n": 0}
    assert out["k"]["reserve"] == pytest.approx(exp(1.2816 * 0.3), rel=1e-3)   # prior p90
    assert out["reserve"]["reserve_needed"] == pytest.approx(100 * out["k"]["reserve"])
    assert out["return_now"] is False and out["fixed"]["k"] == 1.0
    assert any("prior" in w for w in out["warnings"])


def test_segments_move_k_and_the_posterior_round_trips():
    post = None
    for _ in range(25):                                  # the astronaut uses 1.5x E3
        out = upd(posterior=post, segment={"observed": 1.5, "predicted": 1.0},
                  used=10, budget=900, return_predicted=100).json()
        post = out["posterior"]
    assert post["n"] == 25
    assert out["k"]["median"] == pytest.approx(1.5, abs=0.02)
    lo, hi = out["k"]["ci90"]
    assert lo < 1.5 < hi and out["k"]["reserve"] > out["k"]["median"]


def test_return_now_when_the_k_p90_return_does_not_fit():
    # 600 used of 900, predicted return 250. Fixed (k=1): 250 < 300 fits. With a
    # posterior centred on log 1.4 the k_p90 return (>350) does not.
    post = {"mu": log(1.4), "sd": 0.05, "n": 20}
    out = upd(posterior=post, used=600, budget=900, return_predicted=250).json()
    assert out["return_now"] is True and out["fixed"]["return_now"] is False
    assert out["reserve"]["margin_after_return"] < 0 < out["fixed"]["margin_after_return"]


def test_point_of_no_return_on_the_rest_of_the_plan():
    used = [0, 100, 200, 300, 400]            # planned, k = 1, absolute
    ret = [0, 100, 200, 150, 50]               # return need from each vertex
    post = {"mu": log(1.5), "sd": 0.01, "n": 50}
    out = upd(posterior=post, used=0, budget=400, return_predicted=0,
              plan_used=used, plan_return=ret).json()
    # k = 1.5: vertex 2 needs 1.5 (200 + 200) = 600 > 400; fixed (k = 1): vertex 3 needs 300 + 150 = 450 > 400
    assert out["no_return_index"] == 2
    assert out["no_return_index_fixed"] == 3


def test_return_from_position_uses_the_walkback_field_and_litres():
    wh = upd(used=0, budget=900, position=EAST, habitat=CENTRE).json()["return_predicted"]
    wb = client.post("/walkback", json={"current_position": EAST, "energy_remaining_wh": 900,
                                        "base": CENTRE}).json()["properties"]
    assert wh == pytest.approx(wb["return_energy_wh"])
    litres = upd(used=0, budget=100, unit="L", position=EAST, habitat=CENTRE).json()
    assert litres["return_predicted"] == pytest.approx(wh * 3.6 / 20.1)


@pytest.mark.parametrize("body", [
    {"used": 0, "budget": 900},                                          # no return, no position
    {"used": 0, "budget": 0, "return_predicted": 1},
    {"used": 0, "budget": 900, "return_predicted": 1, "plan_used": [0, 1]},
    {"used": 0, "budget": 900, "return_predicted": 1, "plan_used": [0, 1], "plan_return": [1]},
    {"used": 0, "budget": 900, "return_predicted": 1, "q_reserve": 0.4},
    {"used": 0, "budget": 900, "position": [0, 0]},
    {"used": 0, "budget": 900, "return_predicted": 1, "posterior": {"mu": 0, "sd": 0}},
])
def test_invalid_requests(body):
    assert upd(**body).status_code == 422


def test_walkback_k_defaults_to_today_and_scales_the_return():
    body = {"current_position": EAST, "energy_remaining_wh": 300, "base": CENTRE}
    one = client.post("/walkback", json=body).json()["properties"]
    same = client.post("/walkback", json={**body, "k": 1.0}).json()["properties"]
    k15 = client.post("/walkback", json={**body, "k": 1.5}).json()["properties"]
    assert one["return_energy_wh"] == same["return_energy_wh"]
    assert k15["return_energy_wh"] == pytest.approx(1.5 * one["return_energy_wh"])
    assert k15["return_time_s"] == one["return_time_s"]             # time does not change


def test_return_home_k_scales_energy_not_path():
    body = {"position": EAST, "habitat": CENTRE}
    a = client.post("/guide/return_home", json=body).json()["features"][0]
    b = client.post("/guide/return_home", json={**body, "k": 1.2}).json()["features"][0]
    assert a["geometry"] == b["geometry"]
    assert b["properties"]["energy_wh"] == pytest.approx(1.2 * a["properties"]["energy_wh"])
    assert b["properties"]["time_s"] == a["properties"]["time_s"]
