"""Best time to leave for the last plan (P6, #45): GET /plan/departure.

The scoring lives in src/orienteering/departure.py (Diana): for each departure time the
plan's own clock (t_s per vertex) is replayed, and each vertex is sunlit, in the shadow
of the terrain (1 m DEM) or in the dark. This module only adapts it to the saved plan
and keeps the DEM in memory between calls.
"""
from functools import lru_cache
from pathlib import Path

import numpy as np

from . import planner  # noqa: F401  (puts src/ on the path)
from orienteering import departure as dep  # noqa: E402

STEP_MIN = 15.0
FROM_H, TO_H = 5.0, 19.0


@lru_cache(maxsize=2)
def _dem(base_dir):
    return dep.load_dem(Path(base_dir) / "dem_1m.tif")


def best_time(base_dir, saved, sol):
    """The departure table for a saved plan ({"request", "plan"}) on a Curiosity sol.
    Raises LookupError if there is no plan and ValueError if its route has no clock."""
    if saved is None:
        raise LookupError("no plan yet: plan an EVA in the HUD first")
    fc = saved.get("plan", saved)
    route = next((f for f in fc.get("features", []) if f["properties"].get("kind") == "route"), None)
    if route is None or not route["properties"].get("t_s"):
        raise ValueError("the last plan has no timed route (plan a walk with stations or a goal)")
    xy, t_s = dep.tour_from_plan(fc)
    dem, transform = _dem(str(base_dir))
    horizon = dep.horizon_table(xy, dem, transform)
    starts = np.arange(FROM_H, TO_H + 1e-9, STEP_MIN / 60.0)
    rows, best, window = dep.score_departures(xy, t_s, int(sol), starts, horizon)
    lon, lat = dep.lon_lat(*xy[0])
    return {"sol": int(sol), "duration_min": round(float(t_s[-1]) / 60.0, 1),
            "habitat_lon_east_deg": round(lon, 4), "habitat_lat_deg": round(lat, 4),
            "clock": "local true solar time at the habitat (start_lmst_h: local mean solar time, the mission clock)",
            "step_min": STEP_MIN, "best": best, "lit_window_ltst_h": window,
            "best_clock": dep.clock(best["start_ltst_h"]),
            "best_mission_clock": dep.clock(best["start_lmst_h"]),
            "lit_window_clock": [dep.clock(h) for h in window] if window else None,
            "rows": rows}
