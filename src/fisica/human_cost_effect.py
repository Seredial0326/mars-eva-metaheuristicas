"""Effect of the human cost (E3 x E1 sand price) on the round trip to Nevado Sajama.

The E3 note reports this comparison (162.4 Wh with E3 alone, +1.8 % with the
human cost). This script writes it to a file so the results registry (#16, C3)
can point at it. It runs /plan's own code (api/planner.plan) twice: habitat at
the box centre, goal at the Nevado Sajama drill, 1,000 Wh budget, 10 % margin,
30 deg cell block; only `human_cost` changes.

Output: data/e3/human_cost_effect.json
    python src/fisica/human_cost_effect.py
"""

import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))

from api.plan import PlanRequest  # noqa: E402
from api import planner  # noqa: E402

BASE = REPO / "data" / "base"
OUT = REPO / "data" / "e3" / "human_cost_effect.json"
HABITAT_XY = (8143537.492786024, -284463.075189438)   # box centre (base/grid.json)
SAJAMA_XY = (8143217.5, -284993.2)                    # same goal as sensitivity.py
BUDGET_WH = 1000.0


def sha256(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def route(human):
    req = PlanRequest(start=HABITAT_XY, goal=SAJAMA_XY, energy_budget_wh=BUDGET_WH,
                      human_cost=human)
    fc, meta = planner.plan(req, str(BASE))
    r = next(f for f in fc["features"] if f["properties"]["kind"] == "route")
    p = r["properties"]
    return {"cost_model": meta["cost_model"], "energy_wh": p["energy_wh"],
            "time_min": round(p["time_s"] / 60, 2), "length_m": p["length_m"],
            "o2_l": p["o2_l"], "path": r["geometry"]["coordinates"]}


def max_offset_m(a, b):
    """Largest distance from a vertex of route b to the nearest vertex of route a."""
    import numpy as np
    pa, pb = np.asarray(a, float), np.asarray(b, float)
    d = np.sqrt(((pb[:, None, :] - pa[None, :, :]) ** 2).sum(-1)).min(1)
    return float(d.max()), float((d <= 5).mean() * 100)


def main():
    e3, human = route(False), route(True)
    if human["cost_model"] == "E3":
        raise SystemExit("data/e1/e1_weights.json is missing: the human cost equals E3")
    offset, within = max_offset_m(e3["path"], human["path"])
    out = {
        "setting": {"habitat_xy": HABITAT_XY, "goal_xy": SAJAMA_XY, "budget_wh": BUDGET_WH,
                    "margin": 0.10, "max_cell_slope_deg": 30.0},
        "e3": {k: v for k, v in e3.items() if k != "path"},
        "human": {k: v for k, v in human.items() if k != "path"},
        "extra_energy_pct": round(100 * (human["energy_wh"] / e3["energy_wh"] - 1), 3),
        "route_max_offset_m": round(offset, 1),
        "route_within_5m_pct": round(within, 1),
        "inputs_sha256": {name: sha256(p) for name, p in {
            "dem_1m.tif": BASE / "dem_1m.tif", "slope_deg.tif": BASE / "slope_deg.tif",
            "e1_weights.json": REPO / "data" / "e1" / "e1_weights.json"}.items()},
    }
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(f"E3 {e3['energy_wh']:.1f} Wh -> human {human['energy_wh']:.1f} Wh "
          f"({out['extra_energy_pct']:+.1f} %), route up to {offset:.0f} m away -> {OUT}")


if __name__ == "__main__":
    main()
