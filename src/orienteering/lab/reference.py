"""Ground truth for the lab: the exact optimum when DP or CP-SAT proves it, else the best known."""

import importlib.util
from dataclasses import dataclass

from orienteering.solvers import cpsat, dp

KINDS = ("dp_optimal", "cpsat_optimal", "best_known")


@dataclass
class Reference:
    """Prize every run's gap is measured against.

    kind is one of KINDS; upper_bound is the proven bound on the optimum (equal to prize when
    the reference is optimal, None when unknown); solver names the solver that produced route.
    """
    prize: float
    kind: str
    upper_bound: float | None
    solver: str | None
    route: list[int]


def _proven(sol, kind):
    return Reference(prize=sol.prize, kind=kind, upper_bound=sol.prize, solver=sol.solver,
                     route=list(sol.route))


def exact_reference(problem, dp_max=18, cpsat_limit_s=120.0, tracers=None):
    """Run the exact solvers that apply to `problem` and return (reference or None, solutions).

    n = problem.n (habitat included).
    - n <= dp_max: DP gives `dp_optimal`; CP-SAT also runs (only to time it) when ortools is
      installed and n <= cpsat.MAX_STATIONS, but the reference stays the DP one.
    - dp_max < n <= cpsat.MAX_STATIONS with ortools: CP-SAT gives `cpsat_optimal` when it proves
      the optimum within cpsat_limit_s; otherwise (None, [sol]) and finalize() builds a
      `best_known` that keeps sol.bound as upper_bound.
    - otherwise (None, []).
    tracers may hold Tracers under "dp" and "cpsat"; they are passed to the solvers that run.
    The returned solutions are everything that ran, so the caller can store them as rows.
    """
    tracers = tracers or {}
    n = problem.n
    solutions = []
    have_ortools = importlib.util.find_spec("ortools") is not None
    run_cpsat = have_ortools and n <= cpsat.MAX_STATIONS

    ref = None
    if n <= dp_max:
        sol = dp.solve(problem, trace=tracers.get("dp"))
        solutions.append(sol)
        ref = _proven(sol, "dp_optimal")
    if run_cpsat:
        sol = cpsat.solve(problem, time_limit_s=cpsat_limit_s, trace=tracers.get("cpsat"))
        solutions.append(sol)
        if ref is None and sol.optimal:
            ref = _proven(sol, "cpsat_optimal")
    return ref, solutions


def finalize(ref, solutions):
    """Return a Reference that is never None: a proven `ref` is kept, otherwise `best_known`.

    best_known is the best prize among `solutions` (ties: lower energy); its upper_bound is the
    smallest bound any solution proved (None if none did).
    """
    if ref is not None and ref.kind != "best_known":
        return ref
    if not solutions:
        return Reference(prize=0.0, kind="best_known", upper_bound=None, solver=None, route=[])
    best = max(solutions, key=lambda s: (s.prize, -s.energy))
    bounds = [s.bound for s in solutions if s.bound is not None]
    return Reference(prize=best.prize, kind="best_known",
                     upper_bound=min(bounds) if bounds else None,
                     solver=best.solver, route=list(best.route))


def gap_pct(prize, ref_prize):
    """Percentage by which `prize` falls short of `ref_prize`; 0.0 when the reference is <= 0."""
    if ref_prize <= 0:
        return 0.0
    return 100.0 * (ref_prize - prize) / ref_prize
