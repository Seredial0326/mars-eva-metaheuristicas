"""Compare two runs of evaluate_baselines.py (issue #65): E3 against the human cost
(E3 x E1 sand), same habitats, goals and budget fractions.

    python src/grafos/compare_baselines.py            # _e8 vs _human_e8 in data/baselines

Writes data/baselines/baselines_compare_human.json and prints, per budget level and
method: share of false safes among the goals called safe, safety factor needed
(p99), and the median real / estimated energy, for all goals and for the E8
sand-rock contact stations only (where the sand price matters most).
"""

import argparse
import json
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
METHODS = ("B1_astar_slope", "B2_fixed_radius", "B3_linear_o2", "MVP_e4")


def contact_table(csv_path):
    d = pd.read_csv(csv_path, usecols=["level", "goal_type", "method", "safe",
                                       "really_feasible", "real_j", "estimate_j"])
    d = d[d.goal_type == "contact"]
    out = {}
    for (level, method), g in d.groupby(["level", "method"]):
        said = int(g.safe.sum())
        fs = int((g.safe & ~g.really_feasible).sum())
        out.setdefault(level, {})[method] = dict(
            goals=len(g), said_safe=said, false_safe=fs,
            false_safe_rate_of_said_safe=fs / said if said else None,
            real_over_estimate_median=float((g.real_j / g.estimate_j).median()))
    return out


def main():
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dir", default=str(REPO / "data" / "baselines"))
    ap.add_argument("--e3", default="_e8", help="suffix of the E3 run")
    ap.add_argument("--human", default="_human_e8", help="suffix of the human-cost run")
    args = ap.parse_args()
    d = Path(args.dir)
    runs = {}
    for name, sfx in (("E3", args.e3), ("human", args.human)):
        s = json.loads((d / f"baselines_summary{sfx}.json").read_text(encoding="utf-8"))
        runs[name] = dict(cost_model=s.get("cost_model", "E3"), habitats=s["habitats"],
                          goals=s["goals"], stations=s["stations"],
                          all_goals={lv: {m: {k: v[m][k] for k in (
                              "said_safe", "false_safe", "false_safe_rate_of_said_safe",
                              "safety_factor_needed_p99", "real_over_estimate_median",
                              "missed_fraction_of_feasible")} for m in METHODS}
                              for lv, v in s["levels"].items()},
                          e8_contacts=contact_table(d / f"baselines_goals{sfx}.csv"))
    (d / "baselines_compare_human.json").write_text(json.dumps(runs, indent=1), encoding="utf-8")

    for part in ("all_goals", "e8_contacts"):
        print(f"\n## {part}: false safe % of 'safe' (E3 -> human) | real/est median | p99 factor")
        for lv in runs["E3"][part]:
            for m in METHODS:
                a, b = runs["E3"][part][lv][m], runs["human"][part][lv][m]
                fa, fb = a["false_safe_rate_of_said_safe"] or 0, b["false_safe_rate_of_said_safe"] or 0
                line = (f"{lv:4s} {m:16s} {100 * fa:5.1f} -> {100 * fb:5.1f}   "
                        f"{a['real_over_estimate_median']:.3f} -> {b['real_over_estimate_median']:.3f}")
                if part == "all_goals":
                    line += (f"   {a['safety_factor_needed_p99']:.2f} -> "
                             f"{b['safety_factor_needed_p99']:.2f}")
                print(line)
    print("\nwrote", d / "baselines_compare_human.json")


if __name__ == "__main__":
    main()
