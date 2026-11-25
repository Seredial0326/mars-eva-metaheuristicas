"""Analysis of a lab run: summary table, non-parametric tests and the seven comparison figures.

Run from the repo root (src must be importable):
    PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.analyze data/lab/runs/<id>

Writes into <run_dir>/analysis/:
    summary.csv   per algorithm x size bucket: gap, optimal share, runtime, evaluations
    stats.csv     Friedman over the four metaheuristics, then Wilcoxon per pair with Holm
    fig1_convergence.png ... fig7_performance_profile.png   (figure texts are in Spanish)

Conventions:
- Only rows with status == "ok" count. Gaps are relative to each instance's reference
  (`gap_pct`); a `best_known` reference is the best value found, not a proven optimum.
- Size buckets by n (habitat included): 10-20, 21-50, 51-80, 81-200 (the lab sizes are
  20, 50, 80 and 100).
- Convergence curves end with the point (runtime_s, final prize) of runs.csv, because SA and GA
  polish after their last trace row.
- One fixed colour per algorithm in every figure (the dataviz palette; see COLOURS).
"""
import argparse
import csv
import itertools
import warnings
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402

from orienteering.lab import datasets  # noqa: E402
from orienteering.lab.datasets import INSTANCES, REPO  # noqa: E402

# Fixed order = the order the palette was validated in (adjacent pairs); the exact methods
# take the two ends. dp/ils/sa/aco/ga are e6_benchmark.COLOURS; cpsat (violet) was checked with
# the dataviz validator in that slot (adjacent CVD and normal-vision floors pass).
ORDER = ("dp", "ils", "sa", "aco", "ga", "cpsat")
META = ("ils", "sa", "aco", "ga")
COLOURS = {"dp": "#2a78d6", "ils": "#eb6834", "sa": "#1baf7a", "aco": "#eda100",
           "ga": "#e87ba4", "cpsat": "#6250d6"}
LABELS = {"dp": "DP (exacto)", "cpsat": "CP-SAT (exacto)", "ils": "ILS", "sa": "SA", "aco": "ACO",
          "ga": "GA"}
BUCKETS = ("10-20", "21-50", "51-80", "81-200")
BUCKET_MARKERS = {"10-20": "o", "21-50": "s", "51-80": "^", "81-200": "D"}
INK, INK2, GRID, SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"
HILLSHADE = REPO / "data" / "base" / "hillshade.tif"
FIGURE_FILES = ("fig1_convergence.png", "fig2_quality_vs_time.png", "fig3_scalability.png",
                "fig4_gap_boxplots.png", "fig5_internal_dynamics.png", "fig6_routes.png",
                "fig7_performance_profile.png")
SUMMARY_COLUMNS = ["algorithm", "size_bucket", "runs", "mean_gap_pct", "median_gap_pct",
                   "std_gap_pct", "optimal_share", "mean_runtime_s", "median_runtime_s",
                   "mean_evaluations"]
STATS_COLUMNS = ["a", "b", "statistic", "p_value", "p_holm", "n_instances"]
TEXT_FIELDS = {"instance", "set", "kind", "algorithm", "status", "reference_kind", "route"}


# ---------------------------------------------------------------- reading

def _f(x):
    """Float of a CSV/number cell; None for empty, missing or non-finite values."""
    if x is None or x == "":
        return None
    try:
        v = float(x)
    except (TypeError, ValueError):
        return None
    return v if np.isfinite(v) else None


def _truthy(x):
    return x is True or str(x).strip().lower() in ("true", "1", "1.0")


def _auto(key, x):
    if key in TEXT_FIELDS:
        return x
    if x in ("True", "False"):
        return x == "True"
    if x == "":
        return None
    try:
        return float(x)
    except ValueError:
        return x


def _read_csv(path):
    with open(path, newline="", encoding="utf-8") as f:
        return [{k: _auto(k, v) for k, v in row.items()} for row in csv.DictReader(f)]


def _seed(x):
    """Seed key shared by runs.csv and the traces: '' (deterministic) or '0', '1', ..."""
    v = _f(x)
    return "" if v is None else str(int(v))


def size_bucket(n):
    n = float(n)
    return "10-20" if n <= 20 else "21-50" if n <= 50 else "51-80" if n <= 80 else "81-200"


def _ok(runs):
    return [r for r in runs if r.get("status", "ok") == "ok"]


# ---------------------------------------------------------------- summary and stats

def summarize(runs):
    """One row per (algorithm, size bucket) over the status == "ok" runs; see SUMMARY_COLUMNS.
    std_gap_pct is the sample standard deviation (0 for one run); optimal_share is a fraction."""
    groups = {}
    for r in _ok(runs):
        n = _f(r.get("n"))
        if n is None or r.get("algorithm") is None:
            continue
        groups.setdefault((r["algorithm"], size_bucket(n)), []).append(r)
    rank = {a: i for i, a in enumerate(ORDER)}
    out = []
    for (alg, bucket), rs in sorted(groups.items(),
                                    key=lambda kv: (rank.get(kv[0][0], 99), kv[0][1])):
        gaps = [v for v in (_f(r.get("gap_pct")) for r in rs) if v is not None]
        times = [v for v in (_f(r.get("runtime_s")) for r in rs) if v is not None]
        evals = [v for v in (_f(r.get("evaluations")) for r in rs) if v is not None]
        out.append({
            "algorithm": alg, "size_bucket": bucket, "runs": len(rs),
            "mean_gap_pct": float(np.mean(gaps)) if gaps else "",
            "median_gap_pct": float(np.median(gaps)) if gaps else "",
            "std_gap_pct": (float(np.std(gaps, ddof=1)) if len(gaps) > 1 else 0.0) if gaps else "",
            "optimal_share": float(np.mean([_truthy(r.get("is_optimal")) for r in rs])),
            "mean_runtime_s": float(np.mean(times)) if times else "",
            "median_runtime_s": float(np.median(times)) if times else "",
            "mean_evaluations": float(np.mean(evals)) if evals else ""})
    return out


def _holm(pvals):
    """Holm step-down adjusted p-values, in the input order (monotone, capped at 1)."""
    m = len(pvals)
    order = np.argsort(pvals)
    adj, running = [0.0] * m, 0.0
    for rank, i in enumerate(order):
        running = max(running, (m - rank) * pvals[i])
        adj[i] = min(1.0, running)
    return adj


def stats(runs):
    """Friedman test over ils/sa/aco/ga on the per-instance mean gap (mean over seeds), then
    Wilcoxon signed-rank for the 6 pairs with Holm correction. The exact methods are left out
    (their gap is 0 by construction when they are the reference). With fewer than 2 complete
    instances only the Friedman row is returned, with empty values."""
    from scipy import stats as st
    per = {}                                                # (instance, alg) -> [gap, ...]
    for r in _ok(runs):
        g = _f(r.get("gap_pct"))
        if r.get("algorithm") in META and g is not None:
            per.setdefault((r["instance"], r["algorithm"]), []).append(g)
    insts = sorted({i for i, _ in per if all((i, a) in per for a in META)})
    friedman = {"a": "friedman", "b": "", "statistic": "", "p_value": "", "p_holm": "",
                "n_instances": len(insts)}
    if len(insts) < 2:
        return [friedman]
    mat = np.array([[np.mean(per[(i, a)]) for a in META] for i in insts])    # instances x algs
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        stat, p = st.friedmanchisquare(*mat.T) if not np.ptp(mat, axis=1).max() == 0 else (0.0, 1.0)
    if not np.isfinite(stat) or not np.isfinite(p):
        stat, p = 0.0, 1.0
    friedman.update(statistic=float(stat), p_value=float(p), p_holm=float(p))
    pairs, pvals, stat_list = list(itertools.combinations(range(len(META)), 2)), [], []
    for i, j in pairs:
        diff = mat[:, i] - mat[:, j]
        if not np.any(diff):
            s, pv = 0.0, 1.0
        else:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                s, pv = st.wilcoxon(mat[:, i], mat[:, j])
            s, pv = float(s), float(pv)
        stat_list.append(s)
        pvals.append(pv)
    rows = [friedman]
    for (i, j), s, pv, ph in zip(pairs, stat_list, pvals, _holm(pvals)):
        rows.append({"a": META[i], "b": META[j], "statistic": s, "p_value": pv, "p_holm": ph,
                     "n_instances": len(insts)})
    return rows


# ---------------------------------------------------------------- plotting helpers

def split_route(route, ids):
    """Station indices of a route string ('habitat-S1-habitat') given the instance's ids;
    ids that contain '-' are matched greedily (longest first)."""
    if not route:
        return []
    index = {s: k for k, s in enumerate(ids)}
    toks, out, i = route.split("-"), [], 0
    while i < len(toks):
        for j in range(len(toks), i, -1):
            name = "-".join(toks[i:j])
            if name in index:
                out.append(index[name])
                i = j
                break
        else:
            i += 1                                          # unknown token: skip it
    return out


def _style(ax, grid="y"):
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(INK2)
    ax.tick_params(colors=INK2, labelsize=9)
    ax.set_facecolor(SURFACE)
    if grid:
        ax.grid(axis=grid if grid in ("x", "y") else "both", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)


def _empty(ax, msg="sin datos"):
    ax.text(0.5, 0.5, msg, transform=ax.transAxes, ha="center", va="center", color=INK2,
            fontsize=10)
    ax.set_xticks([])
    ax.set_yticks([])
    for side in ax.spines.values():
        side.set_visible(False)


def _alg_legend(ax, algs, loc="best", **kw):
    handles = [Line2D([0], [0], color=COLOURS[a], lw=2.2, marker="o", ms=6,
                      markeredgecolor=SURFACE, label=LABELS[a]) for a in algs]
    return ax.legend(handles=handles, loc=loc, frameon=False, fontsize=9, labelcolor=INK, **kw)


def _footer(fig, ctx, extra=""):
    text = ctx["footnote"] + (" " + extra if extra else "")
    frac = 0.62 / fig.get_figheight()                       # room for the two-line footnote
    fig.get_layout_engine().set(rect=(0, frac, 1, 1 - frac))
    fig.text(0.01, 0.08 / fig.get_figheight(), text, fontsize=8, color=INK2, ha="left",
             va="bottom", wrap=True)


def _save(fig, path):
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)
    return path


def _algs_present(runs):
    present = {r["algorithm"] for r in runs}
    return [a for a in ORDER if a in present]


def _footnote(instances):
    kinds = [r.get("reference_kind") for r in instances]
    best = sum(k == "best_known" for k in kinds)
    return (f"Gap = (referencia - puntaje) / referencia. Referencia: óptimo probado (DP/CP-SAT) en "
            f"{len(kinds) - best} de {len(kinds)} instancias; en las otras {best} es el mejor "
            f"valor conocido (no probado óptimo).")


# ---------------------------------------------------------------- figure 1: convergence

def _curves(traces, runs, instance, ref):
    """{algorithm: [(t array, y array in % of ref), ...]} for one instance, one entry per seed."""
    final = {(r["algorithm"], _seed(r.get("seed"))): r for r in runs
             if r["instance"] == instance and _f(r.get("prize")) is not None
             and _f(r.get("runtime_s")) is not None}
    out = {}
    for alg, rows in traces.items():
        per_seed = {}
        for r in rows:
            if r.get("instance") != instance:
                continue
            if alg == "dp" and _f(r.get("k")) is not None:
                continue                                    # final per-k rows are not progress
            t, y = _f(r.get("t_s")), _f(r.get("best_prize"))
            if t is not None and y is not None:
                per_seed.setdefault(_seed(r.get("seed")), []).append((t, y))
        for seed, pts in per_seed.items():
            run = final.get((alg, seed))
            if run is not None:                             # R6: polish after the last row
                pts.append((float(run["runtime_s"]), float(run["prize"])))
            pts.sort()
            t = np.array([p[0] for p in pts])
            y = np.maximum.accumulate(np.array([p[1] for p in pts])) / ref * 100.0
            out.setdefault(alg, []).append((t, y))
    return out


def _band(curves, grid):
    """Median and quartiles over seeds of step curves sampled on `grid` (NaN before the first
    row; each run holds its last value after it ends); cut at the longest run."""
    mat = np.full((len(curves), len(grid)), np.nan)
    for k, (t, y) in enumerate(curves):
        idx = np.searchsorted(t, grid, side="right") - 1
        ok = idx >= 0
        mat[k, ok] = y[idx[ok]]
    tmax = max(t[-1] for t, _ in curves)
    keep = np.isfinite(mat).any(axis=0) & (grid <= tmax * 1.0000001)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        return (grid[keep], np.nanmedian(mat[:, keep], axis=0),
                np.nanpercentile(mat[:, keep], 25, axis=0),
                np.nanpercentile(mat[:, keep], 75, axis=0), len(curves))


def fig_convergence(path, runs, instances, traces, ctx):
    ref_of = {r["instance"]: _f(r.get("reference_prize")) for r in instances}
    n_of = {r["instance"]: int(_f(r["n"])) for r in instances}
    traced = {r["instance"] for rows in traces.values() for r in rows}
    best = {}
    for inst in traced:
        if inst in n_of and (ref_of.get(inst) or 0) > 0:
            b = size_bucket(n_of[inst])
            if b not in best or n_of[inst] > n_of[best[b]]:
                best[b] = inst
    chosen = [best[b] for b in BUCKETS if b in best]
    fig, axes = plt.subplots(1, max(1, len(chosen)), figsize=(4.6 * max(1, len(chosen)), 4.4),
                             squeeze=False, constrained_layout=True)
    seen = set()
    for ax, inst in zip(axes[0], chosen):
        _style(ax, "both")
        curves = _curves(traces, runs, inst, ref_of[inst])
        grid = np.geomspace(1e-3, max(t[-1] for cs in curves.values() for t, _ in cs), 300)
        lows = []
        for alg in ORDER:
            if alg not in curves:
                continue
            seen.add(alg)
            g, med, q1, q3, n = _band(curves[alg], grid)
            if len(g) == 0:
                continue
            if n > 1:
                ax.fill_between(g, q1, q3, color=COLOURS[alg], alpha=0.18, linewidth=0)
            ax.plot(g, med, color=COLOURS[alg], lw=2.0)
            ax.plot(g[-1:], med[-1:], marker="o", ms=6, color=COLOURS[alg],
                    markeredgecolor=SURFACE, mew=1.2)
            lows.append(np.nanmin(q1))
        ax.axhline(100, color=INK2, lw=1, ls="--")
        ax.set_xscale("log")
        lo = max(0.0, np.floor((min(lows) if lows else 90) / 5) * 5 - 2)
        ax.set_ylim(lo, 102)
        ax.set_title(f"{inst} (n={n_of[inst]})", fontsize=10, color=INK)
        ax.set_xlabel("Tiempo (s, escala log)", fontsize=9, color=INK2)
    if not chosen:
        _empty(axes[0][0])
    else:
        axes[0][0].set_ylabel("Mejor puntaje (% de la referencia)", fontsize=9, color=INK2)
        _alg_legend(axes[0][-1], [a for a in ORDER if a in seen], loc="lower right")
    fig.suptitle("Convergencia: mediana entre semillas y rango intercuartil (línea punteada = "
                 "referencia; el punto marca el fin de cada corrida)", fontsize=11, color=INK)
    _footer(fig, ctx)
    return _save(fig, path)


# ---------------------------------------------------------------- figures 2-4, 7

def fig_quality_time(path, summary, algs, ctx):
    fig, ax = plt.subplots(figsize=(9.2, 4.8), constrained_layout=True)
    _style(ax, "both")
    by = {(r["algorithm"], r["size_bucket"]): r for r in summary
          if r["mean_gap_pct"] != "" and r["mean_runtime_s"] != ""}
    for alg in algs:
        pts = [(b, by[(alg, b)]) for b in BUCKETS if (alg, b) in by]
        if len(pts) > 1:
            ax.plot([max(r["mean_runtime_s"], 1e-4) for _, r in pts],
                    [r["mean_gap_pct"] for _, r in pts], color=COLOURS[alg], lw=1, alpha=0.5)
        for b, r in pts:
            ax.scatter(max(r["mean_runtime_s"], 1e-4), r["mean_gap_pct"], s=95,
                       marker=BUCKET_MARKERS[b], color=COLOURS[alg], edgecolor=SURFACE,
                       linewidth=1.5, zorder=3)
    if not by:
        _empty(ax)
    ax.set_xscale("log")
    ax.set_xlabel("Tiempo medio de ejecución (s, escala log)", fontsize=9, color=INK2)
    ax.set_ylabel("Gap medio vs referencia (%)", fontsize=9, color=INK2)
    lo, hi = ax.get_ylim()
    ax.set_ylim(-0.04 * hi, hi)
    ax.set_title("Calidad contra tiempo (abajo a la izquierda es mejor)", fontsize=11, color=INK)
    _alg_legend(fig, algs, loc="outside right upper", title="Algoritmo", title_fontsize=9)
    fig.legend(handles=[Line2D([0], [0], marker=m, color="none", markerfacecolor="#8a8984",
                              markeredgecolor=SURFACE, ms=8, label=f"n = {b}")
                       for b, m in BUCKET_MARKERS.items()],
              loc="outside right center", frameon=False, fontsize=9,
              title="Tamaño", title_fontsize=9, labelcolor=INK)
    _footer(fig, ctx)
    return _save(fig, path)


def fig_scalability(path, runs, algs, ctx):
    fig, ax = plt.subplots(figsize=(9.2, 4.8), constrained_layout=True)
    _style(ax, "both")
    data = {}
    for r in _ok(runs):
        t = _f(r.get("runtime_s"))
        if r.get("set") == "synthetic" and t is not None:
            data.setdefault((r["algorithm"], r["kind"], int(_f(r["n"]))), []).append(t)
    kinds = {"energy": "-", "windows": "--"}
    used = set()
    for alg in algs:
        for kind, ls in kinds.items():
            pts = sorted((n, float(np.median(v))) for (a, k, n), v in data.items()
                         if a == alg and k == kind)
            if pts:
                used.add(kind)
                ax.plot([p[0] for p in pts], [max(p[1], 1e-4) for p in pts], ls=ls, lw=1.8,
                        marker="o", ms=5, color=COLOURS[alg], markeredgecolor=SURFACE)
    if not data:
        _empty(ax)
    ax.set_xscale("log")
    ax.set_yscale("log")
    ns = sorted({k[2] for k in data})
    if ns:
        ax.set_xticks(ns)
        ax.set_xticklabels([str(n) for n in ns], fontsize=8)
        ax.minorticks_off()
    ax.set_xlabel("Nodos n (incluye el hábitat, escala log)", fontsize=9, color=INK2)
    ax.set_ylabel("Tiempo mediano (s, escala log)", fontsize=9, color=INK2)
    ax.set_title("Escalabilidad en instancias sintéticas", fontsize=11, color=INK)
    _alg_legend(fig, algs, loc="outside right upper")
    fig.legend(handles=[Line2D([0], [0], color=INK2, ls=ls, lw=1.8, label=f"tipo {k}")
                       for k, ls in kinds.items() if k in used],
              loc="outside right center", frameon=False, fontsize=9, labelcolor=INK)
    _footer(fig, ctx, "Cada punto: mediana de todas las corridas con ese n; solo instancias "
                      "sintéticas.")
    return _save(fig, path)


def fig_boxplots(path, runs, algs, ctx):
    ok = _ok(runs)
    buckets = [b for b in BUCKETS if any(size_bucket(_f(r["n"])) == b for r in ok)]
    fig, axes = plt.subplots(1, max(1, len(buckets)), figsize=(4.2 * max(1, len(buckets)), 4.6),
                             squeeze=False, sharey=True, constrained_layout=True)
    rng = np.random.default_rng(0)
    top = 1.0
    for ax, b in zip(axes[0], buckets):
        _style(ax, "y")
        labels = []
        for k, alg in enumerate(algs):
            g = [v for r in ok if r["algorithm"] == alg and size_bucket(_f(r["n"])) == b
                 for v in [_f(r.get("gap_pct"))] if v is not None]
            labels.append(f"{LABELS[alg].split(' ')[0]}\n(n={len(g)})")
            if not g:
                continue
            top = max(top, max(g))
            bp = ax.boxplot([g], positions=[k], widths=0.55, patch_artist=True, showfliers=False,
                            medianprops={"color": INK, "lw": 1.6},
                            boxprops={"facecolor": COLOURS[alg], "alpha": 0.35,
                                      "edgecolor": COLOURS[alg], "lw": 1.4},
                            whiskerprops={"color": COLOURS[alg]}, capprops={"color": COLOURS[alg]})
            del bp
            ax.scatter(k + rng.uniform(-0.18, 0.18, len(g)), g, s=14, color=COLOURS[alg],
                       edgecolor=SURFACE, linewidth=0.5, alpha=0.85, zorder=3)
        ax.set_xticks(range(len(algs)))
        ax.set_xticklabels(labels, fontsize=8)
        ax.set_title(f"n = {b}", fontsize=10, color=INK)
    if not buckets:
        _empty(axes[0][0])
    else:
        axes[0][0].set_ylabel("Gap vs referencia (%)", fontsize=9, color=INK2)
        axes[0][0].set_ylim(-0.04 * top, top * 1.06)
    fig.suptitle("Dispersión del gap entre instancias y semillas (cada punto = una corrida)",
                 fontsize=11, color=INK)
    _footer(fig, ctx)
    return _save(fig, path)


def fig_profile(path, runs, algs, ctx):
    fig, ax = plt.subplots(figsize=(9.2, 4.8), constrained_layout=True)
    _style(ax, "both")
    gaps = {a: np.array([v for r in _ok(runs) if r["algorithm"] == a
                         for v in [_f(r.get("gap_pct"))] if v is not None]) for a in algs}
    allg = np.concatenate([g for g in gaps.values()] or [np.zeros(1)])
    xmax = max(5.0, 1.05 * float(allg.max())) if allg.size else 5.0
    grid = np.linspace(0, xmax, 600)
    for alg in algs:
        g = gaps[alg]
        if g.size:
            ax.plot(grid, [(g <= tau + 1e-9).mean() for tau in grid], color=COLOURS[alg], lw=2.0,
                    drawstyle="steps-post")
    if not allg.size:
        _empty(ax)
    ax.set_xlim(0, xmax)
    start = min([(g <= 1e-9).mean() for g in gaps.values() if g.size] or [0.0])
    ax.set_ylim(max(0.0, np.floor((start - 0.05) * 10) / 10), 1.02)
    ax.set_xlabel("Umbral τ de gap vs referencia (%)", fontsize=9, color=INK2)
    ax.set_ylabel("Fracción de corridas con gap ≤ τ", fontsize=9, color=INK2)
    ax.set_title("Perfil de desempeño (arriba a la izquierda es mejor)", fontsize=11, color=INK)
    _alg_legend(fig, algs, loc="outside right upper")
    _footer(fig, ctx, "Cada corrida = una (instancia, semilla).")
    return _save(fig, path)


# ---------------------------------------------------------------- figure 5: internal dynamics

def _series(rows, instance, seed=None, **cols):
    """Columns (as float arrays, NaN where empty) of one (instance, seed) of a trace."""
    rows = [r for r in rows if r.get("instance") == instance]
    seeds = sorted({_seed(r.get("seed")) for r in rows})
    if not rows:
        return None
    pick = "0" if "0" in seeds else seeds[0]
    rows = [r for r in rows if _seed(r.get("seed")) == pick]
    return {k: np.array([np.nan if _f(r.get(c)) is None else _f(r.get(c)) for r in rows])
            for k, c in cols.items()}, rows


def _rolling(x, w):
    c = np.cumsum(np.insert(x, 0, 0.0))
    lo = np.maximum(np.arange(1, len(x) + 1) - w, 0)
    return (c[1:] - c[lo]) / (np.arange(1, len(x) + 1) - lo)


def _pick_dynamics(traces, n_of):
    """Main instance (most of sa/aco/ga/ils traced, then largest n), DP and CP-SAT instances."""
    present = {a: {r["instance"] for r in traces.get(a, [])} for a in META}
    count = {}
    for insts in present.values():
        for i in insts:
            count[i] = count.get(i, 0) + 1
    main = max(count, key=lambda i: (count[i], n_of.get(i, 0)), default=None)
    dp_insts = {r["instance"] for r in traces.get("dp", []) if _f(r.get("k")) is not None}
    cp_insts = {r["instance"] for r in traces.get("cpsat", [])}
    big = lambda s: max(s, key=lambda i: n_of.get(i, 0), default=None)  # noqa: E731
    return main, big(dp_insts), big(cp_insts)


def fig_dynamics(path, instances, traces, ctx):
    n_of = {r["instance"]: int(_f(r["n"])) for r in instances}
    main, dp_inst, cp_inst = _pick_dynamics(traces, n_of)
    fig, axes = plt.subplots(3, 3, figsize=(13.5, 10.2), constrained_layout=True)
    for ax in axes.ravel():
        _style(ax, "both")

    def title(ax, text, inst):
        ax.set_title(f"{text}\n{inst} (n={n_of[inst]})" if inst else text, fontsize=9.5,
                     color=INK, loc="left")

    def lines(ax, x, curves, alg, logy=False):
        """curves = [(y, label, linestyle)]; direct labels at the right end."""
        for y, label, ls in curves:
            ax.plot(x, y, color=COLOURS[alg], ls=ls, lw=1.8, label=label)
        if logy:
            ax.set_yscale("log")
        ax.legend(frameon=False, fontsize=8.5, labelcolor=INK, loc="best")

    def get(alg, inst, **cols):
        return _series(traces.get(alg, []), inst, **cols) if inst else None

    # SA: temperature and rolling acceptance (two panels, two scales)
    sa = get("sa", main, it="iter", temp="temp", acc="accepted")
    if sa:
        d, rows = sa
        acc = np.array([1.0 if _truthy(r.get("accepted")) else 0.0 for r in rows])
        lines(axes[0, 0], d["it"], [(d["temp"], "temperatura", "-")], "sa", logy=True)
        w = max(10, len(acc) // 25)
        lines(axes[0, 1], d["it"], [(_rolling(acc, w), f"media móvil ({w} muestras)", "-")], "sa")
        axes[0, 1].set_ylim(0, 1.02)
    else:
        _empty(axes[0, 0])
        _empty(axes[0, 1])
    title(axes[0, 0], "SA: temperatura (log)", main)
    title(axes[0, 1], "SA: tasa de aceptación", main)
    axes[0, 0].set_xlabel("Iteración", fontsize=9, color=INK2)
    axes[0, 1].set_xlabel("Iteración", fontsize=9, color=INK2)
    axes[0, 1].set_ylabel("Fracción aceptada", fontsize=9, color=INK2)
    # ACO pheromone
    aco = get("aco", main, it="iter", mean="tau_mean", mx="tau_max")
    if aco:
        d, _ = aco
        lines(axes[0, 2], d["it"], [(d["mx"], "τ máx", "--"), (d["mean"], "τ media", "-")], "aco")
    else:
        _empty(axes[0, 2])
    title(axes[0, 2], "ACO: feromona", main)
    axes[0, 2].set_xlabel("Iteración", fontsize=9, color=INK2)
    # GA diversity and population prizes
    ga = get("ga", main, it="iter", div="diversity", best="pop_best", mean="pop_mean",
             worst="pop_worst")
    if ga:
        d, _ = ga
        lines(axes[1, 0], d["it"], [(d["div"], "diversidad", "-")], "ga")
        lines(axes[1, 1], d["it"], [(d["best"], "mejor", "-"), (d["mean"], "media", "--"),
                                    (d["worst"], "peor", ":")], "ga")
    else:
        _empty(axes[1, 0])
        _empty(axes[1, 1])
    title(axes[1, 0], "GA: diversidad de la población", main)
    title(axes[1, 1], "GA: puntaje de la población", main)
    axes[1, 0].set_xlabel("Generación", fontsize=9, color=INK2)
    axes[1, 1].set_xlabel("Generación", fontsize=9, color=INK2)
    # ILS
    ils = get("ils", main, it="iter", shake="shake_size", cur="current_prize", best="best_prize")
    if ils:
        d, _ = ils
        axes[1, 2].step(d["it"], d["shake"], where="post", color=COLOURS["ils"], lw=1.8)
        lines(axes[2, 0], d["it"], [(d["best"], "mejor", "-"), (d["cur"], "actual", "--")], "ils")
    else:
        _empty(axes[1, 2])
        _empty(axes[2, 0])
    title(axes[1, 2], "ILS: tamaño del shake", main)
    title(axes[2, 0], "ILS: puntaje actual y mejor", main)
    axes[1, 2].set_xlabel("Iteración", fontsize=9, color=INK2)
    axes[2, 0].set_xlabel("Iteración", fontsize=9, color=INK2)
    # DP states by k
    dp_rows = [r for r in traces.get("dp", []) if r.get("instance") == dp_inst
               and _f(r.get("k")) is not None]
    if dp_rows:
        ks = np.array([_f(r["k"]) for r in dp_rows])
        lines(axes[2, 1], ks, [(np.array([_f(r.get("states_k")) or np.nan for r in dp_rows]),
                                "estados", "-"),
                               (np.array([_f(r.get("closable_k")) or np.nan for r in dp_rows]),
                                "cerrables", "--")], "dp", logy=True)
    else:
        _empty(axes[2, 1])
    title(axes[2, 1], "DP: estados por tamaño k del conjunto (log)", dp_inst)
    axes[2, 1].set_xlabel("k (estaciones visitadas)", fontsize=9, color=INK2)
    # CP-SAT objective vs bound
    cp = get("cpsat", cp_inst, t="t_s", obj="objective", bound="bound", phase="phase")
    if cp:
        d, _ = cp
        keep = ~(d["phase"] >= 2)                           # phase 2 minimises energy (other unit)
        d = {k: v[keep] for k, v in d.items()}
        lines(axes[2, 2], d["t"], [(d["bound"], "cota", "--"), (d["obj"], "objetivo", "-")], "cpsat")
    else:
        _empty(axes[2, 2])
    title(axes[2, 2], "CP-SAT: objetivo y cota", cp_inst)
    axes[2, 2].set_xlabel("Tiempo (s)", fontsize=9, color=INK2)
    fig.suptitle("Dinámica interna de los algoritmos (semilla 0)", fontsize=12, color=INK)
    _footer(fig, ctx, "SA se muestrea cada 20 iteraciones: la tasa de aceptación es una media "
                      "móvil sobre esas muestras.")
    return _save(fig, path)


# ---------------------------------------------------------------- figure 6: routes

def _hillshade(xmin, xmax, ymin, ymax, path=HILLSHADE):
    """(image, extent) of the hillshade cropped to a box, or None without the file/rasterio."""
    try:
        import rasterio
        from rasterio.windows import from_bounds
        with rasterio.open(path) as src:
            win = from_bounds(xmin, ymin, xmax, ymax, src.transform).round_offsets().round_lengths()
            img = src.read(1, window=win)
            t = src.window_transform(win)
        h, w = img.shape
        return img, (t.c, t.c + t.a * w, t.f + t.e * h, t.f)
    except Exception:
        return None


def _route_instances(runs, order=("synthetic", "real", "manual")):
    """One instance per set: most algorithms ok, then closest to n = 30."""
    best = {}
    for r in _ok(runs):
        best.setdefault(r["set"], {}).setdefault(r["instance"], set()).add(r["algorithm"])
    n_of = {r["instance"]: _f(r["n"]) for r in runs}
    out = []
    for s in sorted(best, key=lambda s: (order.index(s) if s in order else 99, s)):
        out.append((s, max(best[s], key=lambda i: (len(best[s][i]), -abs(n_of[i] - 30), i))))
    return out


def fig_routes(path, runs, algs, ctx, instances_root, hillshade=HILLSHADE):
    chosen = _route_instances(runs)
    fig, axes = plt.subplots(max(1, len(chosen)), len(ORDER),
                             figsize=(2.35 * len(ORDER), 2.75 * max(1, len(chosen)) + 0.6),
                             squeeze=False, constrained_layout=True)
    for row, (set_name, name) in enumerate(chosen):
        try:
            inst = datasets.load(name, instances_root)
        except (OSError, KeyError):
            for ax in axes[row]:
                _empty(ax, f"{name}: instancia no encontrada")
            continue
        xs = np.array([s["x"] for s in inst.stations])
        ys = np.array([s["y"] for s in inst.stations])
        ids = [s["id"] for s in inst.stations]
        pad = 0.08 * max(np.ptp(xs), np.ptp(ys), 1.0)
        box = (xs.min() - pad, xs.max() + pad, ys.min() - pad, ys.max() + pad)
        shade = None if set_name == "synthetic" else _hillshade(box[0], box[1], box[2], box[3],
                                                                hillshade)
        if shade is not None:                               # do not draw past the raster
            e = shade[1]
            box = (max(box[0], e[0]), min(box[1], e[1]), max(box[2], e[2]), min(box[3], e[3]))
        for col, alg in enumerate(ORDER):
            ax = axes[row, col]
            ax.set_facecolor(SURFACE)
            ax.set_xticks([])
            ax.set_yticks([])
            for side in ax.spines.values():
                side.set_color(GRID)
            if shade is not None:
                ax.imshow(shade[0], cmap="gray", extent=shade[1], alpha=0.75, aspect="equal")
            ax.set_xlim(box[0], box[1])
            ax.set_ylim(box[2], box[3])
            ax.set_aspect("equal")
            ax.scatter(xs[1:], ys[1:], s=14, color="#8a8984" if shade is None else "#f5f5f0",
                       edgecolor="#4a4a46", linewidth=0.5, zorder=2)
            mine = [r for r in _ok(runs) if r["instance"] == name and r["algorithm"] == alg]
            mine.sort(key=lambda r: (_seed(r.get("seed")) != "0", _seed(r.get("seed"))))
            if row == 0:
                ax.set_title(LABELS[alg], fontsize=9.5, color=INK)
            if not mine:
                ax.text(0.5, 0.06, "no ejecutada", transform=ax.transAxes, ha="center",
                        va="bottom", color=INK, fontsize=8.5,
                        bbox={"facecolor": SURFACE, "alpha": 0.85, "edgecolor": "none", "pad": 2})
                ax.scatter(xs[:1], ys[:1], marker="*", s=70, color=INK, zorder=4)
                continue
            r = mine[0]
            idx = split_route(r["route"], ids)
            ax.plot(xs[idx], ys[idx], color=COLOURS[alg], lw=1.8, zorder=3,
                    solid_joinstyle="round")
            vis = [i for i in set(idx) if i != 0]
            ax.scatter(xs[vis], ys[vis], s=26, color=COLOURS[alg], edgecolor=SURFACE,
                       linewidth=0.8, zorder=4)
            ax.scatter(xs[:1], ys[:1], marker="*", s=80, color=INK, edgecolor=SURFACE,
                       linewidth=0.6, zorder=5)
            gap = _f(r.get("gap_pct"))
            ax.set_xlabel(f"puntaje {_f(r['prize']):g}" + ("" if gap is None else
                                                          f" · gap {gap:.1f}%"),
                          fontsize=8, color=INK2, labelpad=3)
        axes[row, 0].set_ylabel(f"{set_name}\n{name}\n(n={inst.problem.n})", fontsize=8.5,
                                color=INK)
    if not chosen:
        _empty(axes[0, 0])
    fig.suptitle("Rutas por algoritmo (semilla 0; estrella = hábitat; líneas rectas entre "
                 "estaciones)", fontsize=11, color=INK)
    _footer(fig, ctx)
    return _save(fig, path)


# ---------------------------------------------------------------- driver

def _load_run(run_dir):
    run_dir = Path(run_dir)
    runs = _read_csv(run_dir / "runs.csv")
    instances = _read_csv(run_dir / "instances.csv")
    traces = {}
    for p in sorted((run_dir / "traces").glob("trace_*.csv")):
        traces[p.stem[len("trace_"):]] = _read_csv(p)
    return runs, instances, traces


def figures(run_dir, instances_root=INSTANCES, out_dir=None, hillshade=HILLSHADE):
    """Write the seven PNG into <run_dir>/analysis (or out_dir) and return their paths."""
    run_dir = Path(run_dir)
    out = Path(out_dir) if out_dir else run_dir / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    runs, instances, traces = _load_run(run_dir)
    algs = _algs_present(_ok(runs))
    summary = summarize(runs)
    ctx = {"footnote": _footnote(instances)}
    paths = [out / f for f in FIGURE_FILES]
    with plt.rc_context({"font.family": "DejaVu Sans", "figure.facecolor": SURFACE,
                         "axes.facecolor": SURFACE, "axes.labelcolor": INK2,
                         "text.color": INK, "savefig.facecolor": SURFACE}):
        fig_convergence(paths[0], runs, instances, traces, ctx)
        fig_quality_time(paths[1], summary, algs, ctx)
        fig_scalability(paths[2], runs, algs, ctx)
        fig_boxplots(paths[3], runs, algs, ctx)
        fig_dynamics(paths[4], instances, traces, ctx)
        fig_routes(paths[5], runs, algs, ctx, instances_root, hillshade)
        fig_profile(paths[6], runs, algs, ctx)
    return paths


def _write(path, columns, rows):
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=columns)
        w.writeheader()
        for r in rows:
            w.writerow({k: (round(v, 6) if isinstance(v, float) else v) for k, v in r.items()})


def analyze(run_dir, instances_root=INSTANCES, hillshade=HILLSHADE):
    """Write summary.csv, stats.csv and the figures; returns {"summary", "stats", "figures"}."""
    run_dir = Path(run_dir)
    runs = _read_csv(run_dir / "runs.csv")
    out = run_dir / "analysis"
    out.mkdir(parents=True, exist_ok=True)
    summary, st = summarize(runs), stats(runs)
    _write(out / "summary.csv", SUMMARY_COLUMNS, summary)
    _write(out / "stats.csv", STATS_COLUMNS, st)
    return {"summary": summary, "stats": st,
            "figures": figures(run_dir, instances_root, hillshade=hillshade)}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("run_dir", help="folder written by orienteering.lab.run")
    ap.add_argument("--instances-dir", default=str(INSTANCES),
                    help="folder with the run's instances, for the route figure")
    args = ap.parse_args(argv)
    result = analyze(args.run_dir, Path(args.instances_dir))
    for p in result["figures"]:
        print(p)
    print(f"wrote {Path(args.run_dir) / 'analysis'}")


if __name__ == "__main__":
    main()
