"""E1 - Maximum-entropy inverse reinforcement learning (MaxEnt IRL) on the base grid.

Plain idea: the rover drivers chose a route between a start and a goal. We look
for the terrain prices (weights) under which that route is the most likely one.

Model [Ziebart2008]
-------------------
A route zeta from a start cell to a goal cell has probability

    P(zeta) = exp(-C(zeta)) / Z,      C(zeta) = sum of its edge costs,

so cheap routes are exponentially more likely than expensive ones, but any
route can happen. Moves go to the 8 neighbours, in the same order as
`src/fisica/edge_cost.py` (NEIGHBOURS), and the cost of the move u -> v is

    cost(u -> v) = d * (c(u) + c(v)) / 2,      c(cell) = w . phi(cell),

with d = 1 m (straight) or sqrt(2) m (diagonal). phi[0] is a constant 1, so
w[0] is the price of one metre of terrain whose other features are all 0.
Features are scaled to be >= 0 and weights are kept >= 0, so no move pays you
to take it.

Backward pass (soft value iteration). V(goal) = 0 and, for every other cell,

    V(u) = -log sum_k exp(-(cost(u -> v_k) + V(v_k))).

V(u) is a "soft minimum" of the cost to reach the goal from u: like the
cheapest-path cost (Aaron's R(v) is the hard version), but routes that are
almost as cheap also count. The policy of the model rover is

    pi_k(u) = exp(-(cost(u -> v_k) + V(v_k)) + V(u)),

which sums to 1 over the 8 moves.

Forward pass. Put mass 1 on the start cell and push it with pi until the goal
absorbs it. D(u) is the expected number of visits to u; from D and pi we get
the expected metres driven over each cell and the expected feature counts E[f].

Fit. The negative log-likelihood of a demonstration and its gradient are

    NLL = C(zeta) - V(start),        dNLL/dw = f(zeta) - E[f],

where f(zeta) are the feature counts along the real route. If the model's
routes cross more of a feature than the real one did, the gradient raises that
feature's price. The NLL is convex in w, so L-BFGS-B (with the bounds below)
finds the single best w.

Why w[0] >= W0_MIN. With 8 neighbours the number of possible walks grows
exponentially with their length. If moves are too cheap, the sum Z over all
walks diverges. For a uniform price c per metre this happens when
4 exp(-c) + 4 exp(-sqrt(2) c) >= 1, i.e. c <= 1.78. Keeping w[0] >= 2.0 and
every other weight >= 0 keeps every cell at >= 2.0 per metre, so Z is finite.
"""

import os
import sys
import time
from dataclasses import dataclass
from pathlib import Path

# On Windows, PyTorch and conda's NumPy/SciPy (MKL) can each load their own Intel
# OpenMP runtime (libiomp5md.dll). The second one aborts the process ("OMP: Error
# #15", seen as "Fatal Python error: Aborted" inside SciPy's L-BFGS-B) unless this
# is set. Intel warns it may give wrong results in rare cases; the gradient tests
# (tests/ml) compare against autograd and finite differences and would catch that.
# setdefault: whoever needs another value can still set it. tests/ml/conftest.py
# does the same for the tests, which import torch before this module.
os.environ.setdefault("KMP_DUPLICATE_LIB_OK", "TRUE")

import numpy as np  # noqa: E402
import torch  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))   # src/, for fisica

from fisica.edge_cost import NEIGHBOURS  # noqa: E402  (same move order as E3)

STEP_M = np.array([np.sqrt(2.0) if dr and dc else 1.0 for dr, dc in NEIGHBOURS])
W0_MIN = 2.0          # price floor of one metre (see the module docstring)
VI_TOL = 1e-9         # backward pass: stop when V changes less than this
FLOW_TOL = 1e-9       # forward pass: stop when less mass than this is still travelling
MAX_ITER = 20000
CHECK_EVERY = 10      # convergence is checked every this many iterations


@dataclass
class Demo:
    """One demonstration: a route inside a feature window.

    phi:  (F, H, W) features, phi[0] = 1. NaN in any feature = blocked cell.
    path: (T, 2) int array of (row, col) inside the window, 8-connected.
          path[0] is the start and path[-1] the goal.
    """
    phi: np.ndarray
    path: np.ndarray
    name: str = ""
    offset: tuple = (0, 0)     # (row, col) of the window's top-left cell on the full grid

    def __post_init__(self):
        self.path = np.asarray(self.path, dtype=np.int64)
        goal = self.path[-1]
        hits = np.flatnonzero((self.path == goal).all(axis=1))
        # The goal absorbs: a route that touches its goal earlier ends there.
        self.path = self.path[: hits[0] + 1]
        steps = np.abs(np.diff(self.path, axis=0))
        if len(steps) and (steps.max() > 1 or (steps.sum(axis=1) == 0).any()):
            raise ValueError(f"{self.name}: the path is not 8-connected without repeats")
        if not np.isfinite(self.phi[:, self.path[:, 0], self.path[:, 1]]).all():
            raise ValueError(f"{self.name}: the path crosses a blocked cell")

    @property
    def length_m(self):
        steps = np.abs(np.diff(self.path, axis=0))
        return float(np.where(steps.sum(axis=1) == 2, np.sqrt(2.0), 1.0).sum())

    def metres_per_cell(self):
        """(H, W) metres the route spends in each cell: half of every step at each end."""
        m = np.zeros(self.phi.shape[1:])
        steps = np.abs(np.diff(self.path, axis=0))
        d = np.where(steps.sum(axis=1) == 2, np.sqrt(2.0), 1.0)
        np.add.at(m, (self.path[:-1, 0], self.path[:-1, 1]), d / 2)
        np.add.at(m, (self.path[1:, 0], self.path[1:, 1]), d / 2)
        return m

    def feature_counts(self):
        """f(zeta): sum over cells of phi * metres driven there. C(zeta) = w . f(zeta)."""
        return np.nansum(self.phi * self.metres_per_cell(), axis=(1, 2))


@dataclass
class Batch:
    """Demonstrations padded to one window size, plus a 1-cell blocked border."""
    phi: torch.Tensor        # (B, F, H, W), 0 where blocked
    open: torch.Tensor       # (B, H, W) bool, cell can be entered
    start: torch.Tensor      # (B, 2) row, col (padded coordinates)
    goal: torch.Tensor       # (B, 2)
    counts: torch.Tensor     # (B, F) feature counts of the real routes
    length_m: torch.Tensor   # (B,)
    names: list


def make_batches(demos, chunk=16, device="cpu"):
    """Group demos of similar window size (less padding) into batches of `chunk`."""
    order = sorted(range(len(demos)), key=lambda i: demos[i].phi.shape[1] * demos[i].phi.shape[2])
    batches = []
    for s in range(0, len(order), chunk):
        group = [demos[i] for i in order[s:s + chunk]]
        f = group[0].phi.shape[0]
        h = max(d.phi.shape[1] for d in group) + 2
        w = max(d.phi.shape[2] for d in group) + 2
        phi = np.zeros((len(group), f, h, w))
        is_open = np.zeros((len(group), h, w), dtype=bool)
        for b, d in enumerate(group):
            ok = np.isfinite(d.phi).all(axis=0)
            phi[b, :, 1:1 + d.phi.shape[1], 1:1 + d.phi.shape[2]] = np.where(ok, d.phi, 0.0)
            is_open[b, 1:1 + d.phi.shape[1], 1:1 + d.phi.shape[2]] = ok
        t = lambda a, dt=torch.float64: torch.as_tensor(np.asarray(a), dtype=dt, device=device)
        batches.append(Batch(
            phi=t(phi), open=t(is_open, torch.bool),
            start=t([d.path[0] + 1 for d in group], torch.long),
            goal=t([d.path[-1] + 1 for d in group], torch.long),
            counts=t([d.feature_counts() for d in group]),
            length_m=t([d.length_m for d in group]),
            names=[d.name for d in group]))
    return batches


# ---------------------------------------------------------------- grid helpers

def _inner(a):
    """Interior of a padded (..., H, W) array."""
    return a[..., 1:-1, 1:-1]


def _neighbour(a, k):
    """Value of neighbour k for every interior cell: a[..., r + dr, c + dc]."""
    dr, dc = NEIGHBOURS[k]
    h, w = a.shape[-2:]
    return a[..., 1 + dr:h - 1 + dr, 1 + dc:w - 1 + dc]


def _pad(a, value):
    return torch.nn.functional.pad(a, (1, 1, 1, 1), value=value)


def _at(a, idx):
    """a[b, row_b, col_b] for every b."""
    return a[torch.arange(a.shape[0], device=a.device), idx[:, 0], idx[:, 1]]


def _goal_mask(batch):
    m = torch.zeros(batch.open.shape, dtype=torch.bool, device=batch.open.device)
    m[torch.arange(m.shape[0]), batch.goal[:, 0], batch.goal[:, 1]] = True
    return _inner(m)


def cell_costs(w, batch):
    """(B, H, W) padded cell prices w . phi, +inf where blocked (and on the border)."""
    c = torch.einsum("f,bfhw->bhw", w, batch.phi)
    return torch.where(batch.open, c, torch.full_like(c, torch.inf))


def move_costs(w, batch):
    """(B, 8, h, w) cost of the move from each interior cell to neighbour k; +inf if blocked."""
    c = cell_costs(w, batch)
    step = torch.as_tensor(STEP_M, dtype=c.dtype, device=c.device)
    return torch.stack([step[k] * (_inner(c) + _neighbour(c, k)) / 2 for k in range(8)], dim=1)


# ---------------------------------------------------------------- the two passes

def soft_values(cost, goal_mask, n_iter=None):
    """Backward pass. cost: (B, 8, h, w). Returns V (B, h, w) and the iterations used.

    With n_iter=None it iterates to convergence; with a number it runs exactly
    that many iterations without in-place edits (used to check the gradient
    with automatic differentiation). In that mode cells not reached yet start
    at a large finite value instead of +inf, because the derivative of
    logsumexp over all -inf entries is NaN (nll_autograd also caps the cost
    of blocked moves for the same reason).
    """
    far = torch.inf if n_iter is None else 1e6
    inf = torch.full(goal_mask.shape, far, dtype=cost.dtype, device=cost.device)
    v = torch.where(goal_mask, torch.zeros_like(inf), inf)
    it = 0
    while True:
        vp = _pad(v, far)
        q = cost + torch.stack([_neighbour(vp, k) for k in range(8)], dim=1)
        v_new = torch.where(goal_mask, torch.zeros_like(inf), -torch.logsumexp(-q, dim=1))
        it += 1
        if n_iter is not None:
            v = v_new
            if it >= n_iter:
                return v, it
            continue
        if it % CHECK_EVERY == 0 or it >= MAX_ITER:
            fin = torch.isfinite(v_new)
            change = torch.where(fin, (v_new - v).abs(), torch.zeros_like(v_new))
            change = torch.nan_to_num(change, nan=0.0, posinf=torch.inf)
            if change.max() < VI_TOL:
                return v_new, it
            if it >= MAX_ITER:
                raise RuntimeError(f"soft value iteration did not converge in {MAX_ITER} iterations")
        v = v_new


def log_policy(cost, v, goal_mask):
    """(B, 8, h, w) log pi_k(u). The goal has no moves (it absorbs)."""
    vp = _pad(v, torch.inf)
    q = cost + torch.stack([_neighbour(vp, k) for k in range(8)], dim=1)
    lp = -q + v[:, None]
    bad = goal_mask[:, None] | ~torch.isfinite(lp)
    return torch.where(bad, torch.full_like(lp, -torch.inf), lp)


def expected_visits(pi, start, shape):
    """Forward pass. pi: (B, 8, h, w). Returns D (B, h, w) and the iterations used."""
    b, h, w = shape
    dt = torch.zeros((b, h + 2, w + 2), dtype=pi.dtype, device=pi.device)
    dt[torch.arange(b), start[:, 0], start[:, 1]] = 1.0
    dt = _inner(dt)
    total = torch.zeros_like(dt)
    it = 0
    while True:
        total += dt
        flow = dt[:, None] * pi
        nxt = torch.zeros((b, h + 2, w + 2), dtype=pi.dtype, device=pi.device)
        for k, (dr, dc) in enumerate(NEIGHBOURS):
            nxt[:, 1 + dr:h + 1 + dr, 1 + dc:w + 1 + dc] += flow[:, k]
        dt = _inner(nxt)
        it += 1
        # Mass that reaches the goal is counted once more (next loop) and then stops.
        if it % CHECK_EVERY == 0:
            travelling = (dt * (pi.sum(dim=1) > 0)).sum(dim=(1, 2))
            if travelling.max() < FLOW_TOL:
                return total + dt, it
            if it >= MAX_ITER:
                raise RuntimeError(f"forward pass did not converge in {MAX_ITER} iterations")


def expected_metres(pi, visits):
    """(B, h, w) expected metres driven over each cell (half of every move at each end)."""
    b, h, w = visits.shape
    flow = visits[:, None] * pi
    step = torch.as_tensor(STEP_M, dtype=pi.dtype, device=pi.device)
    out = torch.einsum("k,bkhw->bhw", step, flow)
    inflow = torch.zeros((b, h + 2, w + 2), dtype=pi.dtype, device=pi.device)
    for k, (dr, dc) in enumerate(NEIGHBOURS):
        inflow[:, 1 + dr:h + 1 + dr, 1 + dc:w + 1 + dc] += step[k] * flow[:, k]
    return (out + _inner(inflow)) / 2


# ---------------------------------------------------------------- objective and fit

@dataclass
class Evaluation:
    nll: np.ndarray          # (n_demos,) negative log-likelihood of each real route
    grad: np.ndarray         # (n_demos, F) dNLL/dw of each route
    expected: np.ndarray     # (n_demos, F) expected feature counts E[f]
    names: list
    length_m: np.ndarray
    vi_iter: int
    flow_iter: int


@torch.no_grad()
def evaluate(w, batches):
    """NLL and gradient of every demonstration at weights w (classic two-pass method)."""
    out = {"nll": [], "grad": [], "expected": [], "names": [], "length_m": []}
    vi_max = flow_max = 0
    for batch in batches:
        wt = torch.as_tensor(w, dtype=batch.phi.dtype, device=batch.phi.device)
        cost = move_costs(wt, batch)
        gm = _goal_mask(batch)
        v, vi_it = soft_values(cost, gm)
        v_start = _at(_pad(v, torch.inf), batch.start)
        if not torch.isfinite(v_start).all():
            bad = [n for n, ok in zip(batch.names, torch.isfinite(v_start).tolist()) if not ok]
            raise RuntimeError(f"goal not reachable from start in: {bad}")
        pi = torch.exp(log_policy(cost, v, gm))
        visits, fl_it = expected_visits(pi, batch.start, v.shape)
        ef = torch.einsum("bfhw,bhw->bf", _inner(batch.phi), expected_metres(pi, visits))
        out["nll"].append((batch.counts @ wt - v_start).cpu().numpy())
        out["grad"].append((batch.counts - ef).cpu().numpy())
        out["expected"].append(ef.cpu().numpy())
        out["names"] += batch.names
        out["length_m"].append(batch.length_m.cpu().numpy())
        vi_max, flow_max = max(vi_max, vi_it), max(flow_max, fl_it)
    cat = {k: np.concatenate(out[k]) for k in ("nll", "grad", "expected", "length_m")}
    return Evaluation(names=out["names"], vi_iter=vi_max, flow_iter=flow_max, **cat)


def nll_autograd(w, batch, n_iter):
    """Total NLL of a batch with V from n_iter unrolled iterations, differentiable in w.

    Only used to check the classic gradient on small problems.
    """
    cost = move_costs(w, batch)
    # Blocked moves: a huge finite cost instead of +inf keeps the derivative finite.
    cost = torch.where(torch.isfinite(cost), cost, torch.full_like(cost, 1e6))
    v, _ = soft_values(cost, _goal_mask(batch), n_iter=n_iter)
    return (batch.counts @ w - _at(_pad(v, torch.inf), batch.start)).sum()


def bounds(n_features, w0_min=W0_MIN):
    return [(w0_min, None)] + [(0.0, None)] * (n_features - 1)


def fit(batches, w_init, l2=0.0, fixed=None, max_iter=200, verbose=False):
    """Fit w by minimising mean NLL per metre + l2/2 * |w[1:]|^2 with L-BFGS-B.

    fixed: optional {index: value} of weights held constant (for example, a
    distance-only control model holds every terrain weight at 0).
    Returns (w, info) where info records the optimisation history.
    """
    from scipy.optimize import minimize

    w_init = np.asarray(w_init, dtype=float)
    total_m = float(sum(b.length_m.sum().item() for b in batches))
    bnds = bounds(len(w_init))
    for i, val in (fixed or {}).items():
        bnds[i] = (val, val)
        w_init[i] = val
    history = []
    t0 = time.perf_counter()

    def objective(w):
        ev = evaluate(w, batches)
        reg = np.r_[0.0, w[1:]]
        value = ev.nll.sum() / total_m + 0.5 * l2 * reg @ reg
        grad = ev.grad.sum(axis=0) / total_m + l2 * reg
        history.append({"w": w.tolist(), "nll_per_m": float(ev.nll.sum() / total_m),
                        "objective": float(value), "seconds": time.perf_counter() - t0,
                        "vi_iter": ev.vi_iter, "flow_iter": ev.flow_iter})
        if verbose:
            print(f"  eval {len(history):3d}  nll/m {history[-1]['nll_per_m']:.5f}  "
                  f"w {np.round(w, 3)}  ({history[-1]['seconds']:.0f} s)", flush=True)
        return value, grad

    res = minimize(objective, w_init, jac=True, method="L-BFGS-B", bounds=bnds,
                   options={"maxiter": max_iter, "gtol": 1e-7, "ftol": 1e-12})
    info = {"success": bool(res.success), "message": str(res.message), "n_eval": len(history),
            "objective": float(res.fun), "history": history, "total_m": total_m,
            "seconds": time.perf_counter() - t0}
    return res.x, info


# ---------------------------------------------------------------- tools for routes

@torch.no_grad()
def policy_for(w, phi, goal, device="cpu"):
    """(8, H, W) policy of the model rover in window phi (F, H, W) towards goal (row, col)."""
    batch = make_batches([Demo(phi, [goal])], device=device)[0]
    wt = torch.as_tensor(w, dtype=torch.float64, device=device)
    cost = move_costs(wt, batch)
    gm = _goal_mask(batch)
    v, _ = soft_values(cost, gm)
    return torch.exp(log_policy(cost, v, gm))[0].cpu().numpy()


def sample_route(pi, start, goal, rng, max_steps=100000):
    """Draw one route from the model rover's policy (8, H, W)."""
    r, c = start
    path = [(r, c)]
    for _ in range(max_steps):
        if (r, c) == tuple(goal):
            return np.array(path)
        p = pi[:, r, c]
        k = rng.choice(8, p=p / p.sum())
        r, c = r + NEIGHBOURS[k][0], c + NEIGHBOURS[k][1]
        path.append((r, c))
    raise RuntimeError("route did not reach its goal")
