"""E1 step 3 - fit the terrain prices to Curiosity's route (MaxEnt IRL).

Fits on every demonstration (src/ml/irl_data.py) two models:
  terrain        all features of irl_data.FEATURES
  distance_only  control: every terrain price held at 0, only the price of a metre
The control knows each demonstration's start and goal too, so it already
explains a lot ("go roughly straight"). Terrain only explains the route if the
terrain model beats the control. This in-sample fit gives the weights; the
honest test on demonstrations the model has not seen is src/ml/validate_irl.py.

Output: data/e1/irl_fit_<tag>.json, tag from the options (see irl_data.setup)
Usage:  python src/ml/fit_irl.py                                    one demo per sol, 1 m, 50 m margin
        python src/ml/fit_irl.py --piece-m 250 --cell 5 --whole-box  250 m pieces, 5 m cells, whole box
"""
import argparse
import json
import time

import numpy as np
import torch

import common
import irl_data
import maxent_irl as irl

L2 = 0.0


def describe(w, ev, total_m):
    real = ev.expected.sum(0) + ev.grad.sum(0)
    return {
        "w": dict(zip(irl_data.FEATURES, np.round(w, 5).tolist())),
        "w_relative_to_metre": dict(zip(irl_data.FEATURES, np.round(w / w[0], 5).tolist())),
        "nll_per_m": float(ev.nll.sum() / total_m),
        "feature_counts_real": dict(zip(irl_data.FEATURES, np.round(real, 2).tolist())),
        "feature_counts_model": dict(zip(irl_data.FEATURES, np.round(ev.expected.sum(0), 2).tolist())),
        "w0_at_floor": bool(np.isclose(w[0], irl.W0_MIN)),
    }


def preference_check(ev):
    """At the distance-only fit: does the real route cross more or less of each feature per metre?

    Positive diff = the real route crosses more than the model's routes (the
    fit would want a negative price, which the bound stops at 0); negative =
    less (a positive price would help). z is the mean difference over its
    standard error across demonstrations; |z| < 2 is indistinguishable from chance.
    """
    real = ev.expected + ev.grad
    m_real, m_model = real[:, 0], ev.expected[:, 0]
    out = {}
    for j, name in enumerate(irl_data.FEATURES[1:], start=1):
        d = real[:, j] / m_real - ev.expected[:, j] / m_model
        se = d.std(ddof=1) / np.sqrt(len(d))
        out[name] = {"real_per_m": float((real[:, j] / m_real).mean()),
                     "model_per_m": float((ev.expected[:, j] / m_model).mean()),
                     "diff_per_m": float(d.mean()), "z": float(d.mean() / se) if se > 0 else 0.0,
                     "share_real_higher": float((d > 0).mean())}
    return out


def main():
    ap = argparse.ArgumentParser()
    irl_data.add_arguments(ap)
    args = ap.parse_args()
    common.E1_OUTPUT.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    t0 = time.perf_counter()
    tag, phi, table, demos, scale = irl_data.setup(args)
    batches = irl.make_batches(demos, chunk=args.chunk, device=device)
    # Route length in metres (NLL per metre). On coarse cells a move is `cell` metres long.
    total_m = float(sum(d.length_m for d in demos)) * args.cell
    print(f"{tag}: {len(demos)} demonstrations, {total_m:.0f} m, device {device}", flush=True)

    n_f = len(irl_data.FEATURES)
    w_init = np.r_[3.0, np.full(n_f - 1, 0.5)]
    print("distance-only control:", flush=True)
    w_dist, info_dist = irl.fit(batches, w_init, fixed={i: 0.0 for i in range(1, n_f)}, verbose=True)
    print("terrain model:", flush=True)
    w_fit, info = irl.fit(batches, w_init, l2=L2, verbose=True)
    ev_fit, ev_dist = irl.evaluate(w_fit, batches), irl.evaluate(w_dist, batches)
    # evaluate() returns demonstrations in batch order; match them to the table by name.
    nll_fit, nll_dist = dict(zip(ev_fit.names, ev_fit.nll)), dict(zip(ev_dist.names, ev_dist.nll))

    report = {
        "tag": tag, "options": vars(args), "features": irl_data.FEATURES, "feature_scale_p99": scale,
        "n_demos": len(demos), "route_m": total_m, "l2": L2, "w0_min": irl.W0_MIN,
        "price_unit": f"per {args.cell} m of route", "device": device,
        "terrain": describe(w_fit, ev_fit, total_m) | {
            "fit": {k: info[k] for k in ("success", "message", "n_eval", "seconds")}},
        "distance_only": describe(w_dist, ev_dist, total_m) | {
            "fit": {k: info_dist[k] for k in ("success", "message", "n_eval", "seconds")}},
        "preference_check_at_distance_only": preference_check(ev_dist),
        "per_demo": [{"name": d.name, "sol": int(r.sol), "block": int(r.block), "length_m": d.length_m * args.cell,
                      "nll_terrain": float(nll_fit[d.name]), "nll_distance_only": float(nll_dist[d.name])}
                     for d, r in zip(demos, table.itertuples())],
    }
    out = common.E1_OUTPUT / f"irl_fit_{tag}.json"
    out.write_text(json.dumps(report, indent=2), encoding="utf-8")
    better = int((ev_fit.nll < ev_dist.nll).sum())
    print(f"\nNLL per metre: terrain {report['terrain']['nll_per_m']:.4f}, "
          f"distance only {report['distance_only']['nll_per_m']:.4f}; "
          f"terrain better on {better}/{len(demos)} demonstrations")
    print("terrain weights:", report["terrain"]["w"])
    print(f"wrote {out} ({time.perf_counter() - t0:.0f} s)")


if __name__ == "__main__":
    main()
