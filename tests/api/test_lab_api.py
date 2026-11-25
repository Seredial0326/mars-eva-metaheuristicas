"""API tests of the metaheuristics lab (/lab/*) and the solver choice of /plan."""

import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from fastapi.testclient import TestClient  # noqa: E402

from api.main import app  # noqa: E402
from orienteering.lab import datasets  # noqa: E402

client = TestClient(app)
CENTRE = [8143537.49, -284463.08]
NAME = "syn-energy-n10-0"
HAVE_DATA = (REPO / "data" / "e2" / "trajectory.geojson").exists()


@pytest.fixture()
def lab(tmp_path, monkeypatch):
    import api.lab as lab_mod
    monkeypatch.setattr(lab_mod, "LAB_DIR", tmp_path)
    datasets.save(datasets.synthetic(10, "energy", 0), root=tmp_path / "instances")
    return tmp_path


def make_run(lab, run_id="20260101-000000", analysis=True):
    d = lab / "runs" / run_id
    (d / "traces").mkdir(parents=True)
    (d / "runs.csv").write_text("instance,algorithm\na,dp\nb,sa\n", encoding="utf-8")
    (d / "instances.csv").write_text("instance\na\n", encoding="utf-8")
    (d / "config.json").write_text("{}", encoding="utf-8")
    if analysis:
        (d / "analysis").mkdir()
        (d / "analysis" / "summary.csv").write_text("algorithm,n,gap\ndp,10,0.0\nsa,10,\n", encoding="utf-8")
        (d / "analysis" / "fig1.png").write_bytes(b"\x89PNG\r\n")
    return d


def test_lab_solve_small(lab):
    r = client.post("/lab/solve", json={"instance": NAME, "algorithms": ["dp", "sa"], "seeds": [0, 1]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert len(body["runs"]) == 3                       # dp once, sa twice
    assert body["traces"]["sa"]
    assert body["reference"]["kind"] in {"dp_optimal", "cpsat_optimal", "best_known"}
    assert body["n"] == 10 and body["stations"]


@pytest.mark.parametrize("body", [
    {"instance": "nope", "algorithms": ["dp"]},
    {"instance": NAME, "algorithms": ["magic"]},
    {"instance": NAME, "algorithms": []},
    {"instance": NAME, "algorithms": ["dp"] * 7},
    {"instance": NAME, "algorithms": ["dp"], "seeds": [0, 1, 2, 3, 4, 5]},
    {"instance": NAME, "algorithms": ["dp"], "seeds": [1000]},
    {"instance": "../etc", "algorithms": ["dp"]},
])
def test_lab_solve_rejects_bad_input(lab, body):
    assert client.post("/lab/solve", json=body).status_code == 422


def test_lab_runs_summary_and_files(lab):
    make_run(lab, "20260101-000000")
    make_run(lab, "20260102-000000", analysis=False)
    runs = client.get("/lab/runs").json()
    assert [r["id"] for r in runs] == ["20260102-000000", "20260101-000000"]
    assert runs[1]["rows"] == 2 and runs[1]["instances"] == 1
    assert runs[1]["has_analysis"] and runs[1]["figures"] == ["fig1.png"]
    assert not runs[0]["has_analysis"]
    s = client.get("/lab/runs/20260101-000000/summary")
    assert s.status_code == 200 and s.json()[0] == {"algorithm": "dp", "n": "10", "gap": "0.0"}
    assert client.get("/lab/runs/20260102-000000/summary").status_code == 404
    f = client.get("/lab/runs/20260101-000000/files/runs.csv")
    assert f.status_code == 200 and f.headers["content-type"].startswith("text/csv")
    p = client.get("/lab/runs/20260101-000000/files/analysis/fig1.png")
    assert p.status_code == 200 and p.headers["content-type"] == "image/png"


@pytest.mark.parametrize("path", ["../../instances/syn-energy-n10-0.csv", "%2e%2e/runs.csv",
                                  "..%2f..%2fx", "/etc/passwd", "nothing.csv"])
def test_lab_files_no_traversal(lab, path):
    make_run(lab)
    (lab / "secret.txt").write_text("x", encoding="utf-8")
    r = client.get(f"/lab/runs/20260101-000000/files/{path}")
    assert r.status_code in (400, 404)
    assert client.get("/lab/runs/..%2fx/files/runs.csv").status_code in (400, 404)


def test_lab_instances(lab):
    items = client.get("/lab/instances").json()
    assert items == [{"name": NAME, "set": "synthetic", "kind": "energy", "n": 10}]
    d = client.get(f"/lab/instances/{NAME}").json()
    assert d["name"] == NAME and d["n"] == 10 and d["geojson"] is None and len(d["stations"]) == 10
    assert d["budget"] > 0
    assert client.get("/lab/instances/nope").status_code == 404


@pytest.mark.skipif(not HAVE_DATA, reason="team data not available")
def test_plan_accepts_solver():
    body = {"start": CENTRE, "energy_budget_wh": 1000.0, "margin": 0.1,
            "stations": [{"id": "S1", "x": CENTRE[0] + 100, "y": CENTRE[1], "score": 5},
                         {"id": "S2", "x": CENTRE[0], "y": CENTRE[1] + 100, "score": 4}],
            "solver": "ils"}
    fc = client.post("/plan", json=body).json()
    route = next(f for f in fc["features"] if f["properties"]["kind"] == "route")
    assert route["properties"]["method"] == "ils"
    assert client.post("/plan", json={**body, "solver": "bogus"}).status_code == 422


# ---------------------------------------------------------------- lab datasets in the HUD

def _write_case(root, name, stations):
    root.mkdir(parents=True, exist_ok=True)
    lines = ["id,type,x,y,prize,service_s"] + [
        f"{s[0]},{s[1]},{s[2]},{s[3]},{s[4]},{s[5]}" for s in stations]
    (root / f"{name}.csv").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (root / f"{name}.npz").write_bytes(b"x")


ROWS = [("habitat", "habitat", 10.0, 20.0, 0.0, 0.0), ("H0", "hollow", 11.0, 21.0, 4.0, 600.0),
        ("E8-03", "contact", 12.0, 22.0, 2.44, 1200.0)]


@pytest.fixture()
def lab_sets(tmp_path, monkeypatch):
    import api.lab as lab_mod
    monkeypatch.setattr(lab_mod, "LAB_DIR", tmp_path)
    inst = tmp_path / "instances"
    for scen in ("120min", "180min"):
        _write_case(inst, f"real-n20-0-{scen}", ROWS)
    return inst


def test_lab_datasets_list(lab_sets):
    datasets.save_pool([dict(zip(datasets.CSV_FIELDS, r)) for r in ROWS + ROWS[1:2]], lab_sets)
    body = client.get("/lab/datasets").json()
    assert [d["id"] for d in body] == ["real-n20-0", "pool"]
    assert body[0]["n"] == 20 and body[0]["stations"] == 2
    assert body[1]["stations"] == 3 and body[1]["label"]


def test_lab_dataset_get(lab_sets):
    r = client.get("/lab/datasets/real-n20-0")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["id"] == "real-n20-0" and body["habitat"] == {"x": 10.0, "y": 20.0}
    assert body["stations"] == [
        {"id": "H0", "type": "hollow", "x": 11.0, "y": 21.0, "score": 4.0, "service_time_min": 10.0},
        {"id": "E8-03", "type": "contact", "x": 12.0, "y": 22.0, "score": 2.44, "service_time_min": 20.0}]


@pytest.mark.parametrize("ds", ["pool", "nope", "real-n20-9", "..%2Fruns", "%2e%2e"])
def test_lab_dataset_missing_and_traversal(lab_sets, ds):
    assert client.get(f"/lab/datasets/{ds}").status_code == 404
    assert "pool" not in [d["id"] for d in client.get("/lab/datasets").json()]
