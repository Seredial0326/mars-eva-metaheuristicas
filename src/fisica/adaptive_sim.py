"""X2 (#101): simulated walks with a known metabolic bias, adaptive vs fixed walkback.

    python src/fisica/adaptive_sim.py [--runs 300]

The demo plan is E4's live round trip from the box centre to the best-scoring saved
station (api.planner.plan, same request as the E11 figure). An astronaut whose real use
is k_true x E3 walks it in segments of SEG_M metres, with lognormal noise per segment.
At the end of every segment each policy checks whether it can walk the NEXT segment
and still get home (E4's walkback rule, used + need <= budget at every point ahead):

    used_real + k x E3(next segment) + k x R(next point) > budget  -> turn back now

with k = 1 for the fixed policy and k = k_p90 (adaptive_k) for the adaptive one.
used_real is what was really used (observed); E3(next segment) and R(v) (rv_wh) are
E3's predictions. Looking one segment ahead matters: the stop at the station charges
its whole service time to one segment (about 38 Wh here).
Turning back means walking R(v)'s path home at the real cost k_true x R(v) (+ noise).
If no alarm fires, the astronaut finishes the plan. The budget is set relative to the
plan (BUDGET_RATIO x its predicted energy): in this 2 x 2 km box the real suit budget
never binds (E4 note), so a tight budget is needed for the question to mean anything.

Outputs: data/adaptive/summary.json and paper/figures/x2_fig1_adaptive_k.png.
"""

import argparse
import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "src"))

from fisica import adaptive_k as ak  # noqa: E402
from fisica.metabolic import KJ_PER_LITER_O2  # noqa: E402

BASE = REPO / "data" / "base"
OUT = REPO / "data" / "adaptive"
FIG = REPO / "paper" / "figures" / "x2_fig1_adaptive_k.png"
CENTRE = (8143537.49, -284463.08)
K_TRUE = [0.8, 1.0, 1.2, 1.5]
SEG_M = 30.0              # m between checks (one observed segment)
NOISE = ak.SIGMA_OBS      # per-segment noise of log(observed / predicted), as the filter
BUDGET_RATIO = 1.25       # usable budget = 1.25 x the plan's predicted energy
Q = 0.90
L_PER_WH = 3.6 / KJ_PER_LITER_O2

SERIES = {"adaptive": "#2a78d6", "fixed": "#eb6834"}
INK, INK2, GRID = "#0b0b0b", "#52514e", "#e5e4e0"
K_COL = {0.8: "#1baf7a", 1.0: "#2a78d6", 1.2: "#eda100", 1.5: "#e34948"}


def demo_plan():
    from api import planner, stations as st
    from api.plan import PlanRequest
    saved = st.load(REPO / "data" / "stations")
    rubric = saved.get("rubric") or {}
    req = PlanRequest(
        start=CENTRE, energy_budget_wh=1000, margin=0.10, max_duration_min=120,
        max_cell_slope_deg=30,
        stations=[dict(id=s["id"], x=s["x"], y=s["y"], type=s.get("type"),
                       score=float(rubric.get(s.get("type"), 0)),
                       service_time_min=s.get("service_time_min") or 0)
                  for s in saved["stations"]])
    fc, info = planner.plan(req, BASE)
    p = next(f for f in fc["features"] if f["properties"]["kind"] == "route")["properties"]
    xy = np.asarray(next(f for f in fc["features"]
                         if f["properties"]["kind"] == "route")["geometry"]["coordinates"])
    d = np.concatenate([[0], np.cumsum(np.hypot(*np.diff(xy, axis=0).T))])
    return {"used": np.asarray(p["used_wh"]), "rv": np.asarray(p["rv_wh"]),
            "t": np.asarray(p["t_s"]), "d": d, "goal": info.get("goal_station")}


def checkpoints(d):
    """Vertex indices at every SEG_M metres, plus the last vertex."""
    marks = np.arange(SEG_M, d[-1], SEG_M)
    idx = np.unique(np.concatenate([[0], np.searchsorted(d, marks), [len(d) - 1]]))
    return idx


def walk(plan, k_true, budget, rng):
    """One walk: both policies see the same real segments. Returns per-policy outcome
    and the filter trace (k median and IC90 after each segment)."""
    used_p, rv = plan["used"], plan["rv"]
    idx = checkpoints(plan["d"])
    pred = np.diff(used_p[idx])
    obs = k_true * pred * np.exp(rng.normal(0, NOISE, len(pred)))
    real_used = np.concatenate([[0.0], np.cumsum(obs)])         # at each checkpoint
    seg_wh = float(np.mean(pred))                               # a typical segment's E3 use

    post, trace = ak.prior(), []
    out = {name: None for name in ("adaptive", "fixed")}
    for s in range(1, len(idx)):
        post = ak.update(post, obs[s - 1], pred[s - 1])
        lo, hi = ak.interval(post, 0.90)
        trace.append((float(np.exp(post.mu)), lo, hi))
        v = idx[s]
        last = s == len(idx) - 1
        for name, k_res in (("adaptive", ak.quantile(post, Q)), ("fixed", 1.0)):
            if out[name] is not None:
                continue
            if last:                                             # back at the habitat
                out[name] = {"turned_back": False, "at_m": float(plan["d"][v]),
                             "used": float(real_used[s])}
            elif real_used[s] + k_res * (pred[s] + rv[idx[s + 1]]) > budget:   # walkback alarm
                # The way home is walked in segments too, each with its own noise, so
                # its total noise is NOISE / sqrt(number of segments home).
                n_home = max(1.0, rv[v] / seg_wh)
                total = real_used[s] + k_true * rv[v] * np.exp(rng.normal(0, NOISE / np.sqrt(n_home)))
                out[name] = {"turned_back": True, "at_m": float(plan["d"][v]),
                             "used": float(total)}
    for o in out.values():
        o["margin_wh"] = budget - o["used"]
        o["ran_out"] = o["margin_wh"] < 0
        o["done_frac"] = o["at_m"] / plan["d"][-1] if o["turned_back"] else 1.0
    return out, trace


def segments_to_converge(trace, k_true, width=0.2):
    for s, (_, lo, hi) in enumerate(trace, start=1):
        if lo <= k_true <= hi and hi - lo < width:
            return s
    return None


def main(runs):
    OUT.mkdir(parents=True, exist_ok=True)
    plan = demo_plan()
    budget = BUDGET_RATIO * plan["used"][-1]
    n_seg = len(checkpoints(plan["d"])) - 1
    summary = {"plan": {"goal_station": plan["goal"], "length_m": round(float(plan["d"][-1]), 1),
                        "energy_wh": round(float(plan["used"][-1]), 2),
                        "o2_l": round(float(plan["used"][-1] * L_PER_WH), 2),
                        "duration_min": round(float(plan["t"][-1] / 60), 2), "segments": n_seg},
               "settings": {"seg_m": SEG_M, "noise_sd_log": NOISE, "prior_sd_log": ak.PRIOR_SD,
                            "q_reserve": Q, "budget_ratio": BUDGET_RATIO,
                            "budget_wh": round(float(budget), 2), "runs": runs},
               "by_k_true": {}}
    traces = {}
    for k_true in K_TRUE:
        rng = np.random.default_rng(int(k_true * 1000))
        res = {"adaptive": [], "fixed": []}
        conv, cover = [], []
        for r in range(runs):
            out, trace = walk(plan, k_true, budget, rng)
            for name in res:
                res[name].append(out[name])
            conv.append(segments_to_converge(trace, k_true))
            cover.append(trace[-1][1] <= k_true <= trace[-1][2])
            if r == 0:
                traces[k_true] = trace
        entry = {}
        for name, rows in res.items():
            m = np.array([o["margin_wh"] for o in rows])
            entry[name] = {
                "ran_out_pct": round(100 * float(np.mean([o["ran_out"] for o in rows])), 1),
                "turned_back_pct": round(100 * float(np.mean([o["turned_back"] for o in rows])), 1),
                "plan_done_mean_pct": round(100 * float(np.mean([o["done_frac"] for o in rows])), 1),
                "margin_wh_median": round(float(np.median(m)), 2),
                "margin_wh_p5": round(float(np.percentile(m, 5)), 2),
                "margin_l_median": round(float(np.median(m) * L_PER_WH), 2),
                "margin_l_p5": round(float(np.percentile(m, 5) * L_PER_WH), 2)}
        ok = [c for c in conv if c is not None]
        entry["filter"] = {
            "segments_to_ci90_contains_and_width_lt_0_2_median": float(np.median(ok)) if ok else None,
            "never_converged_pct": round(100 * (1 - len(ok) / runs), 1),
            "ci90_coverage_at_end_pct": round(100 * float(np.mean(cover)), 1)}
        summary["by_k_true"][str(k_true)] = entry
        entry["_margins"] = {name: [o["margin_wh"] * L_PER_WH for o in rows]
                             for name, rows in res.items()}
    figure(traces, summary, budget)
    for e in summary["by_k_true"].values():
        e.pop("_margins")
    (OUT / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


def figure(traces, summary, budget):
    fig, (ax, bx) = plt.subplots(1, 2, figsize=(12, 5.2), gridspec_kw={"width_ratios": [1.15, 1]})
    for k_true, trace in traces.items():
        s = np.arange(1, len(trace) + 1)
        med, lo, hi = (np.array(v) for v in zip(*trace))
        c = K_COL[k_true]
        ax.fill_between(s, lo, hi, color=c, alpha=0.18, linewidth=0)
        ax.plot(s, med, color=c, lw=2)
        ax.axhline(k_true, color=c, lw=1, ls=":")
        ax.text(s[-1] + 0.6, med[-1], f"k_true {k_true}", va="center", fontsize=9, color=INK)
    ax.set_xlim(0, len(next(iter(traces.values()))) + 9)
    ax.set_xlabel(f"segments walked ({SEG_M:.0f} m each)")
    ax.set_ylabel("k (real use / E3 prediction)")
    ax.set_title("(a) Estimated k, median and 90 % credible band (one walk each)",
                 fontsize=10, loc="left", color=INK)
    ax.grid(axis="y", color=GRID, lw=0.8)

    ks = [str(k) for k in K_TRUE]
    pos = np.arange(len(ks))
    for off, name in ((-0.18, "fixed"), (0.18, "adaptive")):
        data = [summary["by_k_true"][k]["_margins"][name] for k in ks]
        bp = bx.boxplot(data, positions=pos + off, widths=0.3, patch_artist=True, showfliers=False,
                        medianprops={"color": INK, "lw": 1.5}, whiskerprops={"color": INK2},
                        capprops={"color": INK2})
        for b in bp["boxes"]:
            b.set(facecolor=SERIES[name], alpha=0.85, edgecolor=SERIES[name])
        for i, k in enumerate(ks):
            pct = summary["by_k_true"][k][name]["ran_out_pct"]
            if pct > 0:
                bx.text(pos[i] + off, min(data[i]) - 1.2, f"{pct:.0f} %\nout", ha="center",
                        va="top", fontsize=8, color=INK)
    bx.axhline(0, color=INK2, lw=1.2)
    bx.set_xticks(pos, [f"k_true {k}" for k in ks])
    bx.set_ylabel("O2 left at the habitat (L, metabolic equivalent)")
    bx.set_title(f"(b) Margin at arrival, budget {BUDGET_RATIO:g}x the plan "
                 f"({summary['settings']['runs']} walks)", fontsize=10, loc="left", color=INK)
    from matplotlib.patches import Patch
    bx.legend(handles=[Patch(color=SERIES["fixed"], label="fixed walkback (k = 1)"),
                       Patch(color=SERIES["adaptive"], label="adaptive walkback (k_p90)")],
              loc="upper right", fontsize=8, frameon=False)
    bx.grid(axis="y", color=GRID, lw=0.8)
    for a in (ax, bx):
        for side in ("top", "right"):
            a.spines[side].set_visible(False)
    lo = min(min(min(v) for v in e["_margins"].values()) for e in summary["by_k_true"].values())
    bx.set_ylim(lo - 6, None)
    fig.tight_layout()
    FIG.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(FIG, dpi=150)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=int, default=300)
    main(ap.parse_args().runs)
