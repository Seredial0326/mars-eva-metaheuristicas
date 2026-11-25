"""E1 step 1 - synthetic check of the MaxEnt IRL code (src/ml/maxent_irl.py).

If the method cannot find prices that we hid ourselves, it will not find the
ones behind Curiosity's route either. So:

1. Invent a terrain: three smooth random features scaled to 0-1 on an
   80 x 80 grid. Feature B is a decoy: its true price is 0.
2. Hide known prices TRUE_W and draw N_DEMOS routes from that model, each
   between a random start and goal 15-35 cells apart, inside a window around
   them with a MARGIN of 10 cells (the same window logic as the real data).
3. Check the gradient three ways on a few routes: the classic two-pass
   formula, PyTorch automatic differentiation through the backward pass, and
   finite differences of the NLL. They must agree.
4. Fit from W_INIT and compare with TRUE_W. Repeat with N_REPEATS different
   terrains and route sets, to see how much the estimate moves by chance.
5. Fit the distance-only control (all terrain prices held at 0): it must
   explain the routes worse than the terrain model.

Outputs: data/e1/toy_check.json and paper/figures/e1_fig1_toy_check.png.

Usage:  python src/ml/irl_toy_check.py
"""
import json
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import torch  # noqa: E402
from scipy.ndimage import gaussian_filter  # noqa: E402

import common  # noqa: E402
import maxent_irl as irl  # noqa: E402

GRID = 80
FEATURES = ["metre", "feature A", "feature B (decoy)", "feature C"]
TRUE_W = np.array([2.5, 4.0, 0.0, 1.5])
W_INIT = np.array([3.0, 1.0, 1.0, 1.0])
N_DEMOS = 60
DIST_RANGE = (15, 35)
MARGIN = 10
N_REPEATS = 5
N_GRAD_CHECK = 5
SEED = 2026


def terrain(rng):
    """(F, GRID, GRID) features: constant 1, then three smooth fields in 0-1."""
    fields = []
    for sigma in (4.0, 4.0, 2.0):
        f = gaussian_filter(rng.standard_normal((GRID, GRID)), sigma)
        fields.append((f - f.min()) / (f.max() - f.min()))
    return np.stack([np.ones((GRID, GRID))] + fields)


def window(a, b):
    """Row and column slices of the box around cells a and b plus MARGIN, clipped to the grid."""
    lo = np.maximum(np.minimum(a, b) - MARGIN, 0)
    hi = np.minimum(np.maximum(a, b) + MARGIN + 1, GRID)
    return slice(lo[0], hi[0]), slice(lo[1], hi[1])


def draw_demos(phi_full, w, rng, n):
    """n routes drawn from the model with prices w, and the top-left corner of each window."""
    demos, offsets = [], []
    while len(demos) < n:
        start, goal = rng.integers(0, GRID, size=(2, 2))
        if not DIST_RANGE[0] <= np.hypot(*(goal - start)) <= DIST_RANGE[1]:
            continue
        rs, cs = window(start, goal)
        off = np.array([rs.start, cs.start])
        phi = phi_full[:, rs, cs]
        pi = irl.policy_for(w, phi, goal - off)
        path = irl.sample_route(pi, start - off, goal - off, rng)
        demos.append(irl.Demo(phi, path, name=f"toy{len(demos):02d}"))
        offsets.append(off)
    return demos, offsets


def gradient_check(demos, w):
    batch = irl.make_batches(demos)[0]
    ev = irl.evaluate(w, [batch])
    classic = ev.grad.sum(axis=0)
    wt = torch.tensor(w, dtype=torch.float64, requires_grad=True)
    loss = irl.nll_autograd(wt, batch, n_iter=ev.vi_iter + 200)
    loss.backward()
    eps = 1e-5
    fd = np.array([(irl.evaluate(w + eps * e, [batch]).nll.sum()
                    - irl.evaluate(w - eps * e, [batch]).nll.sum()) / (2 * eps)
                   for e in np.eye(len(w))])
    rel = lambda a, b: float(np.abs(a - b).max() / np.abs(b).max())
    return {"w": w.tolist(), "classic": classic.tolist(), "autograd": wt.grad.tolist(),
            "finite_difference": fd.tolist(),
            "max_rel_diff_autograd": rel(wt.grad.numpy(), classic),
            "max_rel_diff_finite_difference": rel(fd, classic),
            "nll_classic": float(ev.nll.sum()), "nll_autograd": float(loss.item())}


def main():
    common.E1_OUTPUT.mkdir(parents=True, exist_ok=True)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    rng = np.random.default_rng(SEED)
    report = {"true_w": TRUE_W.tolist(), "w_init": W_INIT.tolist(), "features": FEATURES,
              "grid": GRID, "n_demos": N_DEMOS, "dist_range_cells": DIST_RANGE,
              "margin_cells": MARGIN, "w0_min": irl.W0_MIN, "device": device, "repeats": []}
    keep = None
    for rep in range(N_REPEATS):
        t0 = time.perf_counter()
        phi_full = terrain(rng)
        demos, offsets = draw_demos(phi_full, TRUE_W, rng, N_DEMOS)
        entry = {"seconds_drawing": time.perf_counter() - t0}
        if rep == 0:
            entry["gradient_check"] = gradient_check(demos[:N_GRAD_CHECK], np.array([3.0, 1.0, 2.0, 0.5]))
            g = entry["gradient_check"]
            print(f"gradient check: autograd rel. diff {g['max_rel_diff_autograd']:.1e}, "
                  f"finite differences {g['max_rel_diff_finite_difference']:.1e}")
        batches = irl.make_batches(demos, chunk=32, device=device)
        w_fit, info = irl.fit(batches, W_INIT)
        ev_fit = irl.evaluate(w_fit, batches)
        ev_true = irl.evaluate(TRUE_W, batches)
        w_dist, info_dist = irl.fit(batches, W_INIT, fixed={1: 0.0, 2: 0.0, 3: 0.0})
        ev_dist = irl.evaluate(w_dist, batches)
        total_m = info["total_m"]
        # Feature matching: at the optimum the model's expected counts equal the real ones
        # (real = expected + gradient), so the gradient is ~0.
        entry.update({
            "w_fit": w_fit.tolist(), "fit_success": info["success"], "fit_evaluations": info["n_eval"],
            "fit_seconds": info["seconds"], "route_m": total_m,
            "nll_per_m": {"fit": float(ev_fit.nll.sum() / total_m),
                          "true_w": float(ev_true.nll.sum() / total_m),
                          "distance_only": float(ev_dist.nll.sum() / total_m)},
            "w_distance_only": w_dist.tolist(),
            "feature_counts_real": (ev_fit.expected.sum(0) + ev_fit.grad.sum(0)).tolist(),
            "feature_counts_model": ev_fit.expected.sum(0).tolist(),
            "max_abs_gradient_per_m_at_fit": float(np.abs(ev_fit.grad.sum(0)).max() / total_m),
        })
        report["repeats"].append(entry)
        print(f"repeat {rep}: w_fit {np.round(w_fit, 3)} (true {TRUE_W})  "
              f"NLL/m fit {entry['nll_per_m']['fit']:.4f}, true {entry['nll_per_m']['true_w']:.4f}, "
              f"distance only {entry['nll_per_m']['distance_only']:.4f}  "
              f"[{info['n_eval']} evaluations, {info['seconds']:.0f} s]", flush=True)
        if rep == 0:
            keep = (phi_full, demos, offsets, info)

    fits = np.array([r["w_fit"] for r in report["repeats"]])
    report["w_fit_mean"] = fits.mean(0).tolist()
    report["w_fit_std"] = fits.std(0, ddof=1).tolist() if len(fits) > 1 else None
    report["max_abs_error"] = np.abs(fits - TRUE_W).max(0).tolist()
    (common.E1_OUTPUT / "toy_check.json").write_text(json.dumps(report, indent=2), encoding="utf-8")
    figure(report, *keep)
    print(f"mean w_fit {np.round(fits.mean(0), 3)} +- {np.round(fits.std(0, ddof=1), 3)}")
    print(f"wrote {common.E1_OUTPUT / 'toy_check.json'} and paper/figures/e1_fig1_toy_check.png")


def figure(report, phi_full, demos, offsets, info):
    fig, ax = plt.subplots(1, 3, figsize=(15, 4.6))
    cost = np.tensordot(TRUE_W, phi_full, axes=1)
    im = ax[0].imshow(cost, cmap="magma")
    fig.colorbar(im, ax=ax[0], label="true price per metre")
    for d, (r0, c0) in zip(demos[:12], offsets[:12]):
        ax[0].plot(d.path[:, 1] + c0, d.path[:, 0] + r0, lw=1.2)
        ax[0].plot(d.path[-1, 1] + c0, d.path[-1, 0] + r0, "w*", ms=6)
    ax[0].set_title("(a) Invented terrain, 12 drawn routes")
    ax[0].set_xticks([]), ax[0].set_yticks([])

    fits = np.array([r["w_fit"] for r in report["repeats"]])
    x = np.arange(len(TRUE_W))
    ax[1].bar(x - 0.2, TRUE_W, 0.4, label="hidden (true)", color="0.6")
    ax[1].bar(x + 0.2, fits.mean(0), 0.4, yerr=fits.std(0, ddof=1) if len(fits) > 1 else None,
              capsize=4, label=f"recovered (mean ± sd, {len(fits)} repeats)", color="tab:blue")
    ax[1].set_xticks(x, FEATURES, rotation=15)
    ax[1].set_ylabel("price (weight)")
    ax[1].set_title("(b) Hidden vs recovered prices")
    ax[1].set_ylim(0, fits.max() * 1.45)
    ax[1].legend(loc="upper right")

    h = info["history"]
    ax[2].plot(range(1, len(h) + 1), [e["nll_per_m"] for e in h], "o-", ms=3, label="terrain model")
    ref = report["repeats"][0]["nll_per_m"]
    ax[2].axhline(ref["true_w"], color="0.4", ls="--", label="at the hidden prices")
    ax[2].axhline(ref["distance_only"], color="tab:red", ls=":", label="distance-only control")
    ax[2].set_xlabel("fit evaluation")
    ax[2].set_ylabel("NLL per metre (lower = less surprised)")
    ax[2].set_title("(c) Fit progress, repeat 0")
    ax[2].legend()
    fig.tight_layout()
    fig.savefig(common.REPO / "paper" / "figures" / "e1_fig1_toy_check.png", dpi=120)
    plt.close(fig)


if __name__ == "__main__":
    main()
