"""Fixture of a real multi-station tour for the 3D map tests (P1, issue #42, block 6).

Writes tests/viz3d/fixtures/plan_tour_e5.json: the FeatureCollection that POST /plan
answers when the tour planner (E5, Diana, src/orienteering) is present, for the saved
stations and the 2D planner's default limits. The planning code is called in this
process: no server is used and NOTHING IS SAVED (the server would save the answer as
the last plan, which the guide screen loads; here that step is replaced by a no-op and
the plans folder is checked before and after).

E5 is not in main yet. Take its folder from the open PR branch into a scratch folder
and point --e5-src at it:

    git archive origin/9-e5-orienteering src/orienteering | tar -x -C <scratch>
    python src/viz3d/make_tour_fixture.py --e5-src <scratch>/src

The request is the one the 3D page sends with "Plan with default settings"
(web/3d/api.js: defaultPlanRequest): saved stations scored by the rubric, 1000 Wh with a
10 % margin, cells over 30 degrees blocked, start at the box centre, and --max-duration-min
(default 120). The answer is kept whole (every vertex, every profile array); only the
CRS text is dropped and the file is written without spaces, to stay small.
"""

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tests" / "viz3d" / "fixtures" / "plan_tour_e5.json"
PROFILE_KEYS = ("t_s", "used_wh", "rv_wh", "rv_time_s", "slack_wh", "o2_used_l")


def digest(folder):
    """Names and content hashes of the files of a folder (to show nothing was written)."""
    folder = Path(folder)
    if not folder.exists():
        return {}
    return {p.name: hashlib.md5(p.read_bytes()).hexdigest() for p in sorted(folder.iterdir()) if p.is_file()}


def main():
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--e5-src", required=True, help="folder that contains orienteering/ (E5 branch)")
    ap.add_argument("--max-duration-min", type=float, default=120.0)
    ap.add_argument("--out", default=str(OUT))
    args = ap.parse_args()
    if not (Path(args.e5_src) / "orienteering" / "tour.py").exists():
        sys.exit(f"{args.e5_src} has no orienteering/tour.py")

    sys.path.insert(0, str(REPO))
    sys.path.append(str(Path(args.e5_src).resolve()))
    from api import main as api            # noqa: E402 (after the path is set)
    from api import stations as st         # noqa: E402
    from api.plan import PlanRequest       # noqa: E402

    if not api.tour.AVAILABLE:
        sys.exit("api/tour.py does not see E5: check --e5-src")
    api.guide.save_plan = lambda *a, **k: None          # never replace the saved plan
    before = digest(api.PLANS)

    saved = st.load(api.STATIONS)
    rubric = saved.get("rubric") or {}
    bbox = json.loads((api.BASE / "grid.json").read_text(encoding="utf-8"))["bbox"]
    start = [(bbox["xmin"] + bbox["xmax"]) / 2, (bbox["ymin"] + bbox["ymax"]) / 2]
    request = {
        "start": start,
        "stations": [{"id": s["id"], "x": s["x"], "y": s["y"], "type": s.get("type"),
                      "score": float(rubric.get(s.get("type"), 0)),
                      "service_time_min": s.get("service_time_min") or 0} for s in saved["stations"]],
        "energy_budget_wh": 1000, "gravity_m_s2": 3.71, "margin": 0.10,
        "max_duration_min": args.max_duration_min, "o2_budget_l": None,
        "apollo_speed_uses_signed_slope": True, "service_energy_wh_per_min": None,
        "max_cell_slope_deg": 30,
    }
    req = PlanRequest(**request)
    req.check_inside(bbox)
    fc = api._plan_live(req)               # what POST /plan returns for this request
    if digest(api.PLANS) != before:
        sys.exit("the plans folder changed: this must not happen")

    fc.pop("crs", None)                    # the CRS text is long and the page does not read it
    route = next(f for f in fc["features"] if f["properties"].get("kind") == "route")
    n = len(route["geometry"]["coordinates"])
    for key in PROFILE_KEYS:
        if key in route["properties"]:
            assert len(route["properties"][key]) == n, f"{key} is not aligned with the vertices"
    fc["properties"]["fixture"] = {
        "made_by": "src/viz3d/make_tour_fixture.py", "e5_branch": "origin/9-e5-orienteering",
        "request": {k: v for k, v in request.items() if k != "stations"},
        "stations_requested": len(request["stations"])}
    out = Path(args.out)
    out.write_text(json.dumps(fc, separators=(",", ":")), encoding="utf-8")
    p = route["properties"]
    print(f"{out}: {out.stat().st_size / 1024:.0f} KB, {n} vertices, {p.get('length_m')} m, "
          f"{p.get('time_s')} s, visits {p.get('visit_order')}, stops at {p.get('stop_index')}")
    print("data folder:", os.environ.get("MARTIAN_DATA", REPO / "data"), "- plans folder unchanged")


if __name__ == "__main__":
    main()
