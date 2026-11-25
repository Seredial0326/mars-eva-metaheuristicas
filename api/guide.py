"""Guide mode backend (#43): the saved plan and the instant way home.

- The last successful live plan is saved (data/plans/last_plan.json) so the
  guide screen on the arm tablet can load it after planning in the habitat.
- Return home: the FASTEST path from the astronaut's position to the habitat,
  from E4's reversed Dijkstra (Graph.costs_to with predecessors). It is the
  emergency way back (time is what the 30 min oxygen reserve limits), and it
  needs no new planning: pred[v] is already the next cell towards the habitat.
"""

import json
from functools import lru_cache
from pathlib import Path

import numpy as np
from scipy import sparse
from scipy.sparse.csgraph import dijkstra

from . import planner
from grafos.graph import follow  # noqa: E402  (planner puts src/ on the path)
from fisica.metabolic import KJ_PER_LITER_O2  # noqa: E402

J_PER_WH = 3600.0
# Return-home candidates (#119 A2): paths minimising (1 - w) * time + w * energy, from
# the fastest (w = 0) to the least-energy (w = 1). The best feasible path need not be
# among them, so "nothing fits" is exact only when a resource fails at its own minimum.
SWEEP = (0.0, 0.1, 0.25, 0.5, 0.75, 0.9, 1.0)
O2_MODEL = f"metabolic: energy / {KJ_PER_LITER_O2} kJ per L, plus o2_leak_lpm x time"
RESOURCE_KEYS = ("energy_remaining_wh", "time_remaining_s", "o2_remaining_l")


def save_plan(plans_dir, request, fc):
    plans_dir = Path(plans_dir)
    plans_dir.mkdir(parents=True, exist_ok=True)
    (plans_dir / "last_plan.json").write_text(
        json.dumps({"request": request, "plan": fc}), encoding="utf-8")


def load_plan(plans_dir):
    path = Path(plans_dir) / "last_plan.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


@lru_cache(maxsize=8)
def _towards_home(base_dir, max_cell_slope_deg, habitat_node, human=True):
    g = planner.graph(base_dir, max_cell_slope_deg, human)
    t, pred = g.costs_to(habitat_node, "time_s", predecessors=True)
    return t, pred


@lru_cache(maxsize=16)
def _towards_home_mix(base_dir, max_cell_slope_deg, habitat_node, human, w):
    """Next node towards the habitat for the cost (1 - w) * s * time + w * energy, with
    s = median(energy) / median(time) so that both terms weigh alike."""
    if w == 0.0:
        return _towards_home(base_dir, max_cell_slope_deg, habitat_node, human)[1]
    g = planner.graph(base_dir, max_cell_slope_deg, human)
    E, T = g.csr("energy_j", True), g.csr("time_s", True)
    if not (np.array_equal(E.indptr, T.indptr) and np.array_equal(E.indices, T.indices)):
        raise ValueError("energy and time graphs must have the same arcs")
    scale = float(np.median(E.data) / np.median(T.data))
    mixed = sparse.csr_matrix(((1 - w) * scale * T.data + w * E.data, E.indices, E.indptr),
                              shape=E.shape)
    return dijkstra(mixed, indices=int(habitat_node), return_predecessors=True)[1]


def resources_given(res):
    return bool(res) and any(res.get(k) is not None for k in RESOURCE_KEYS)


def check_resources(energy_wh, time_s, res):
    """Energy (plus the reserve to keep), time and O2 needed by ONE path against what
    is left. O2 comes from that same energy, plus a declared leak per minute; it is not
    treated as an independent resource."""
    reserve = res.get("energy_reserve_wh") or 0.0
    leak = res.get("o2_leak_lpm") or 0.0
    o2 = energy_wh * J_PER_WH / 1000.0 / KJ_PER_LITER_O2 + leak * time_s / 60.0
    out = {}
    for name, unit, need, have in (
            ("energy", "wh", energy_wh + reserve, res.get("energy_remaining_wh")),
            ("time", "s", time_s, res.get("time_remaining_s")),
            ("o2", "l", o2, res.get("o2_remaining_l"))):
        out[name] = {f"needed_{unit}": round(float(need), 3),
                     f"available_{unit}": None if have is None else round(float(have), 3),
                     "ok": None if have is None else bool(need <= have * (1 + 1e-9))}
    out["energy"]["reserve_wh"] = round(float(reserve), 3)
    return out


def fits(checks):
    return all(c["ok"] is not False for c in checks.values())


def failing(checks):
    return [n for n, c in checks.items() if c["ok"] is False]


def return_home(base_dir, max_cell_slope_deg, position_xy, habitat_xy, human=True, k=1.0,
                resources=None):
    """Way home from the astronaut's position.

    Without `resources`: the fastest path, as before (feasible = null).
    With any of energy_remaining_wh / time_remaining_s / o2_remaining_l (and optional
    energy_reserve_wh, o2_leak_lpm): energy, time and O2 are checked on the SAME path.
    The fastest path is kept if it fits; otherwise the fastest candidate that fits
    (choice "tradeoff" or "least_energy"); if none fits, the least-energy path comes
    back with feasible = false and a diagnosis, never the fastest path as if safe."""
    args = (base_dir, max_cell_slope_deg, position_xy, habitat_xy, human, k)
    fast = _return_home_path(*args, 0.0)
    if not resources_given(resources):
        fast["feasible"] = None
        return fast
    fast["checks"] = check_resources(fast["energy_wh"], fast["time_s"], resources)
    summary = {"time_s": fast["time_s"], "energy_wh": fast["energy_wh"],
               "feasible": fits(fast["checks"]), "failing": failing(fast["checks"])}
    common = {"fastest": summary, "o2_model": O2_MODEL, "diagnosis": None}
    if summary["feasible"]:
        return {**fast, **common, "choice": "fastest", "feasible": True}
    least = _return_home_path(*args, 1.0)
    least["checks"] = check_resources(least["energy_wh"], least["time_s"], resources)
    for w in SWEEP[1:]:                                     # fastest first
        cand = least if w == 1.0 else _return_home_path(*args, w)
        if cand is not least:
            cand["checks"] = check_resources(cand["energy_wh"], cand["time_s"], resources)
        if fits(cand["checks"]):
            return {**cand, **common, "feasible": True,
                    "choice": "least_energy" if w == 1.0 else "tradeoff"}
    # Nothing fits. Proven when a resource fails even at its own minimum: energy (and
    # O2 without a leak, which is proportional to energy) on the least-energy path,
    # time on the fastest path.
    proven = [n for n in failing(least["checks"])
              if n == "energy" or (n == "o2" and not resources.get("o2_leak_lpm"))]
    if "time" in summary["failing"]:
        proven.append("time")
    limiting = proven or sorted(set(summary["failing"]) | set(failing(least["checks"])))
    msg = "no way home fits the remaining " + " and ".join(limiting)
    if not proven:
        msg += ("; not proven, only paths between the fastest and the least-energy one "
                "were checked")
    return {**least, **common, "feasible": False, "choice": "least_energy",
            "diagnosis": {"code": "insufficient_resources", "limiting": limiting,
                          "exact": bool(proven), "message": msg}}


def _return_home_path(base_dir, max_cell_slope_deg, position_xy, habitat_xy, human, k, w):
    """Path position -> habitat for the mix weight w (0 = fastest, 1 = least energy),
    with time, energy and length and the per-vertex profile.
    k (X2, #101): metabolic factor on E3's energy; it scales energy, not the path or time.
    Raises ValueError if a point is outside the box or the habitat is unreachable."""
    g = planner.graph(base_dir, max_cell_slope_deg, human)
    hr, hc, _ = g.place(*habitat_xy, label="habitat")
    pr, pc, moved = g.place(*position_xy, label="position")
    habitat, pos = int(g.node(hr, hc)), int(g.node(pr, pc))
    t, _ = _towards_home(base_dir, max_cell_slope_deg, habitat, human)
    if not np.isfinite(t[pos]):
        raise ValueError("no walkable way back to the habitat from here")
    pred = _towards_home_mix(base_dir, max_cell_slope_deg, habitat, human, w)
    path = follow(pred, pos, end=habitat) if pos != habitat else np.array([pos])
    rows, cols = g.cell(path)
    x, y = g.cell_to_xy(rows, cols)
    one = len(path) > 1
    energy = (g.path_cost(path, "energy_j") if one else np.array([0.0])) * k
    length = g.path_cost(path, "length_m") if one else np.array([0.0])
    times = g.path_cost(path, "time_s") if one else np.array([0.0])
    return {
        "coordinates": [[float(a), float(b)] for a, b in zip(x, y)],
        "time_s": float(times[-1]), "energy_wh": float(energy[-1] / J_PER_WH),
        "length_m": float(length[-1]), "position_moved_m": moved,
        # per-vertex profile, same order as the coordinates (for the guide simulation)
        "t_s": [round(float(v), 1) for v in times],
        "used_wh": [round(float(v) / J_PER_WH, 4) for v in energy],
    }


@lru_cache(maxsize=8)
def _return_energy(base_dir, max_cell_slope_deg, habitat_node, human=True):
    g = planner.graph(base_dir, max_cell_slope_deg, human)
    return g.costs_to(habitat_node, "energy_j")


def rejoin(base_dir, max_cell_slope_deg, position_xy, target_xy, habitat_xy, human=True,
           resources=None, continuation=None):
    """Off-route recovery: the least-energy path position -> target (a point on the
    planned route ahead), with the same per-vertex profile as E4's route: t_s,
    used_wh, and what it takes to get home from each vertex (rv_wh, rv_time_s).

    With `resources` (as in return_home) it also checks, on this path: (1) the walkback
    rule at every vertex of the connector (used so far + way home + reserve fits), and
    (2) the connector plus the rest of the plan from the target (`continuation`:
    energy_wh, time_s, both from the target to the end of the plan) against what is
    left. feasible is true only if both hold; otherwise the diagnosis says to go home."""
    g = planner.graph(base_dir, max_cell_slope_deg, human)
    hr, hc, _ = g.place(*habitat_xy, label="habitat")
    pr, pc, moved = g.place(*position_xy, label="position")
    tr, tc, _ = g.place(*target_xy, label="target")
    habitat, pos, target = (int(g.node(r, c)) for r, c in ((hr, hc), (pr, pc), (tr, tc)))
    if pos == target:
        path = np.array([pos])
    else:
        cost, pred = g.costs_from(pos, "energy_j", predecessors=True)
        if not np.isfinite(cost[target]):
            raise ValueError("cannot rejoin the route from here")
        path = follow(pred, target, end=pos)[::-1]           # pos -> target
    rows, cols = g.cell(path)
    x, y = g.cell_to_xy(rows, cols)
    one = len(path) > 1
    energy = g.path_cost(path, "energy_j") if one else np.array([0.0])
    times = g.path_cost(path, "time_s") if one else np.array([0.0])
    rv_t, _ = _towards_home(base_dir, max_cell_slope_deg, habitat, human)
    rv_e = _return_energy(base_dir, max_cell_slope_deg, habitat, human)
    out = {
        "coordinates": [[float(a), float(b)] for a, b in zip(x, y)],
        "time_s": float(times[-1]), "energy_wh": float(energy[-1] / J_PER_WH),
        "position_moved_m": moved,
        "t_s": [round(float(v), 1) for v in times],
        "used_wh": [round(float(v) / J_PER_WH, 4) for v in energy],
        "rv_wh": [round(float(v) / J_PER_WH, 4) for v in rv_e[path]],
        "rv_time_s": [round(float(v), 1) for v in rv_t[path]],
    }
    if not resources_given(resources):
        out["feasible"] = None
        return out
    # (1) walkback along the connector: at each vertex, so far + way home must fit.
    e_way = (energy + rv_e[path]) / J_PER_WH
    t_way = times + rv_t[path]
    bad = [i for i in range(len(path))
           if not fits(check_resources(float(e_way[i]), float(t_way[i]), resources))]
    # (2) the connector plus the rest of the plan from the target.
    cont = continuation or {}
    total_e = out["energy_wh"] + (cont.get("energy_wh") or 0.0)
    total_t = out["time_s"] + (cont.get("time_s") or 0.0)
    checks = check_resources(total_e, total_t, resources)
    walkback_ok, continue_ok = not bad, fits(checks)
    reasons, limiting = [], list(failing(checks))
    if not walkback_ok:
        short = failing(check_resources(float(e_way[bad[0]]), float(t_way[bad[0]]), resources))
        limiting = sorted(set(limiting) | set(short))
        reasons.append("the way home from here already does not fit the remaining "
                       + " and ".join(short) if bad[0] == 0 else
                       f"the way home stops fitting the remaining {' and '.join(short)} "
                       f"at vertex {bad[0]} of the rejoin path")
    if not continue_ok:
        reasons.append("the rest of the plan does not fit the remaining "
                       + " and ".join(failing(checks)))
    out.update(
        checks=checks, continuation_given=continuation is not None,
        walkback_ok=walkback_ok, first_violation_index=bad[0] if bad else None,
        continue_ok=continue_ok, feasible=walkback_ok and continue_ok, o2_model=O2_MODEL,
        diagnosis=None if not reasons else {
            "code": "insufficient_resources", "limiting": limiting,
            "exact": True, "action": "return_home",
            "message": "; ".join(reasons) + ": return home now"})
    return out


def save_walk(walks_dir, record):
    """Keep a walk for the debrief: data/walks/walk_<UTC time>.json and last_walk.json."""
    from datetime import datetime, timezone
    walks_dir = Path(walks_dir)
    walks_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    text = json.dumps({"saved_utc": stamp, **record})
    (walks_dir / f"walk_{stamp}.json").write_text(text, encoding="utf-8")
    (walks_dir / "last_walk.json").write_text(text, encoding="utf-8")
    return f"walk_{stamp}.json"


def load_walk(walks_dir):
    path = Path(walks_dir) / "last_walk.json"
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None
