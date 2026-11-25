"""Derived blocks the team's results table reads: E6 overall and P6 shadow_shortening_min."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from orienteering.e6_benchmark import overall
from orienteering.paper_departure import shadow_shortening


def run(group, instance, method, gap, proven=True):
    return {"set": group, "instance": instance, "method": method, "gap": gap, "optimum_proven": proven}


def test_overall_pools_sets_and_skips_unproven_optima():
    rows = [run("a", "i1", "exact", 0.0), run("b", "i1", "exact", 0.0),   # same name, other set
            run("a", "i1", "ga", 0.0), run("a", "i1", "ga", 0.2), run("b", "i1", "ga", 0.0),
            run("b", "i2", "ga", 0.5, proven=False)]                         # no proven optimum
    out = overall(rows)
    assert out["exact"] == {"instances": 2, "runs": 2, "optimal_share": 1.0,
                            "mean_gap_pct": 0.0, "max_gap_pct": 0.0}
    assert out["ga"]["instances"] == 2 and out["ga"]["runs"] == 3
    assert out["ga"]["optimal_share"] == 0.6667
    assert out["ga"]["max_gap_pct"] == 20.0
    assert "ils" not in out


def test_shadow_shortening_per_end_and_range():
    tours = {"nominal": {"lit_window_ltst_h": [6.5, 14.5], "lit_window_no_terrain_ltst_h": [6.25, 15]},
             "max_120_min": {"lit_window_ltst_h": [6.75, 15.25], "lit_window_no_terrain_ltst_h": [6.25, 16]},
             "unlit": {"lit_window_ltst_h": None, "lit_window_no_terrain_ltst_h": [6.25, 16]}}
    out = shadow_shortening(tours)
    assert out["nominal"] == {"start": 15, "end": 30}
    assert out["max_120_min"] == {"start": 30, "end": 45}
    assert "unlit" not in out
    assert (out["min"], out["max"], out["range"]) == (15, 45, "15–45")
