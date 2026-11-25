"""Numbers for the diagnosis and guarantee section of the E5 note (#119, A4 and A5).

Run from the repo root (inputs as in the E5 note):
    python src/orienteering/paper_diagnosis.py

Plans the E5 tour through plan_tour (the /plan entry point) on the plain E3 graph, from the
box centre with the 13 manual stations, for a grid of energy budgets and duration limits,
and writes data/e5/diagnosis.json: the reproducible scenario, each case's outcome (tour or
diagnosis code) and, for every tour, the smallest return margin along the line (service and
waits included) and where it is.
"""
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from api.plan import PlanRequest  # noqa: E402
from grafos.build_rv import SERVICE_POWER_W  # noqa: E402

from orienteering import diagnose  # noqa: E402
from orienteering.data_io import STATIONS_PATH, read_stations  # noqa: E402
from orienteering.network import load_graph  # noqa: E402
from orienteering.paper_figures import BOX_CENTRE, MARGIN  # noqa: E402
from orienteering.tour import plan_tour  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "data" / "e5" / "diagnosis.json"
BUDGETS_WH = [1000.0, 600.0, 300.0, 100.0, 40.0]
DURATIONS_MIN = [None, 120.0, 60.0, 20.0]


def request(st, budget_wh, max_duration_min=None, o2_budget_l=None, extra=()):
    stations = [{"id": str(st.id[k]), "type": str(st.type[k]), "x": float(st.x[k]), "y": float(st.y[k]),
                 "score": float(st.prize[k]), "service_time_min": float(st.service_s[k]) / 60.0}
                for k in range(len(st))]
    return PlanRequest(start=BOX_CENTRE, stations=stations + list(extra), energy_budget_wh=budget_wh,
                       margin=MARGIN, service_energy_wh_per_min=SERVICE_POWER_W / 60.0,
                       max_duration_min=max_duration_min, o2_budget_l=o2_budget_l)


def outcome(graph, req):
    t0 = time.perf_counter()
    try:
        fc, info = plan_tour(req, graph)
    except (diagnose.NoTourFound, diagnose.TourInputError) as err:
        d = err.diagnosis
        out = {"code": d["code"], "exact": d["exact"], "message": d["message"]}
        if "closest" in d:
            out.update(limiting=d["limiting"], closest=d["closest"]["id"], needs=d["closest"]["needs"],
                       available=d["closest"]["available"], actions=d["actions"])
        if "field" in d:
            out["field"] = d["field"]
        return out | {"solve_s": round(time.perf_counter() - t0, 2)}
    p = fc["features"][0]["properties"]
    n = len(p["slack_wh"])
    at = p["min_slack_index"]
    stops = p["stop_index"]
    after = max(m for m, i in enumerate(stops) if i <= at)
    reasons = info["skipped_reasons"]
    return {"code": "tour", "feasible": p["feasible"], "method": p["method"], "exact": p["exact"],
            "prize": p["prize"], "stations": len(p["order"]) - 2, "energy_wh": p["energy_wh"],
            "duration_min": round(p["time_s"] / 60.0, 1), "usable_wh": p["usable_wh"],
            "min_slack_wh": p["min_slack_wh"], "min_slack_index": at, "vertices": n,
            "min_slack_after_stop": p["order"][after], "last_stop": p["order"][-2],
            "min_slack_equals_end": abs(p["min_slack_wh"] - p["slack_wh"][-1]) < 1e-3,
            "slack_at_end_wh": p["slack_wh"][-1],
            "skipped_fit_alone": sorted(k for k, v in reasons.items() if v["fits_alone"]),
            "skipped_not_alone": {k: v["short"] for k, v in reasons.items() if not v["fits_alone"]},
            "solve_s": round(time.perf_counter() - t0, 2)}


def main():
    graph, _ = load_graph()
    st = read_stations(graph, STATIONS_PATH)
    s = {"scenario": {
            "habitat": list(BOX_CENTRE), "stations": f"{len(st)} manual ({STATIONS_PATH.name})",
            "graph": "plain E3 edges (data/base/edges_e3.npz; E3 defaults: no move over 20 deg, no cell over 30 deg)",
            "cost_model": graph.cost_model, "margin": MARGIN, "service_power_w": SERVICE_POWER_W,
            "o2": "energy / 20.1 kJ/L, no leak", "solver": "auto (DP up to 19 stations, CP-SAT above)",
            "entry_point": "orienteering.tour.plan_tour (POST /plan)"},
         "grid": []}
    for b in BUDGETS_WH:
        for d in DURATIONS_MIN:
            o = outcome(graph, request(st, b, d))
            s["grid"].append({"budget_wh": b, "max_duration_min": d, **o})
            print(b, d, o["code"], o.get("prize"), o.get("min_slack_wh"), o.get("limiting"), o["solve_s"])
    s["o2_limited"] = outcome(graph, request(st, 1000.0, o2_budget_l=1.0))
    s["duration_limited"] = outcome(graph, request(st, 1000.0, max_duration_min=5.0))
    # the advice for the smallest budget: the closest station's need / (1 - margin), plus 0.1 %
    low = next(g for g in s["grid"] if g["code"] == "insufficient_resources")
    advised = low["needs"]["energy_wh"] / (1 - MARGIN) * 1.001
    s["advice_check"] = {"from_budget_wh": low["budget_wh"], "advised_budget_wh": round(advised, 2),
                         **outcome(graph, request(st, advised))}
    print("duration", s["duration_limited"]["code"], s["duration_limited"].get("limiting"))
    print("advice", advised, s["advice_check"]["code"], s["advice_check"].get("prize"))
    s["outside_the_box"] = outcome(graph, request(st, 1000.0, extra=[
        {"id": "X", "type": "ridge", "x": BOX_CENTRE[0] + 5000.0, "y": BOX_CENTRE[1], "score": 1.0,
         "service_time_min": 0.0}]))
    print("o2", s["o2_limited"]["code"], s["o2_limited"].get("limiting"))
    print("outside", s["outside_the_box"]["code"], s["outside_the_box"].get("field"))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(s, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
