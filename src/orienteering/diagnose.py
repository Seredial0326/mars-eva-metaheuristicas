"""
Why an E5 tour has no plan, or leaves a station out (#119, A4).

Every diagnosis is a dict with
    code    : "invalid_input" | "unreachable" | "insufficient_resources" |
              "search_incomplete" | "walkback"
    exact   : True when the reason is proven within the E5 model, False when it is an estimate
    message : one line for people
and, depending on the code, the field at fault, the limits, the station closest to fitting
with what it needs and what is available, and actions that would let that station fit.

The E5 model: least-energy legs between the habitat and the stations on the request's graph
(network.station_matrices), service at the service power, the energy budget minus the margin,
O2 as energy / 20.1 kJ/L (no leak), and the leg time along those least-energy legs.

What is exact. A station whose round trip habitat -> station -> habitat alone does not fit
cannot be in any tour: every tour that visits it walks at least those two legs and does its
service. For energy and O2 this is exact on the graph (least-energy legs are the minimum).
For duration it is exact for the E5 model only: a faster but costlier path is not searched,
so a duration shortfall is flagged exact = False.
"""
import math

import numpy as np

from grafos.labels import KJ_PER_LITER_O2, NoFeasibleRoute
from grafos.walkback import J_PER_WH

J_PER_LITER_O2 = KJ_PER_LITER_O2 * 1000.0
CODES = ("invalid_input", "unreachable", "insufficient_resources", "search_incomplete", "walkback")


class NoTourFound(NoFeasibleRoute):
    """No tour for the request. A NoFeasibleRoute, so callers that catch it keep working;
    .diagnosis holds the structured reason."""
    def __init__(self, diagnosis):
        self.diagnosis = diagnosis
        super().__init__(diagnosis["message"])


class TourInputError(ValueError):
    """Bad request for an E5 tour. A ValueError, as before; .diagnosis holds code
    "invalid_input" and the field at fault."""
    def __init__(self, message, field):
        self.diagnosis = {"code": "invalid_input", "exact": True, "field": field, "message": message}
        super().__init__(message)


"""
The limits of a /plan request as E5 applies them.
    usable_j : energy budget minus the margin (J)
    o2_l : O2 budget (L) or None
    max_duration_s : or None
    margin : the request's margin (to turn usable energy back into a budget)
"""
def limits(usable_j, o2_l, max_duration_s, margin):
    return {"usable_j": float(usable_j), "o2_l": None if o2_l is None else float(o2_l),
            "max_duration_s": None if max_duration_s is None else float(max_duration_s),
            "margin": float(margin)}


"""
Round trip habitat (0) -> station k -> habitat alone against each limit.
Returns {"id", "reachable", "fits_alone", "short": [resources over their limit],
         "needs": {energy_wh, o2_l, duration_min}, "available": {...}, "exact"}.
"""
def station_alone(problem, lim, k, sid):
    out = {"id": str(sid)}
    go, back = float(problem.energy[0, k]), float(problem.energy[k, 0])
    if not (np.isfinite(go) and np.isfinite(back)):
        out.update(reachable=False, fits_alone=False, short=["path"], needs={}, available={}, exact=True)
        return out
    svc_j = float(problem.service_j[k]) if problem.service_j is not None else 0.0
    energy_j = go + back + svc_j
    needs = {"energy_wh": round(energy_j / J_PER_WH, 3)}
    available = {"energy_wh": round(lim["usable_j"] / J_PER_WH, 3)}
    short = []
    if energy_j > lim["usable_j"] + 1e-9:
        short.append("energy")
    if lim["o2_l"] is not None:
        needs["o2_l"] = round(energy_j / J_PER_LITER_O2, 4)
        available["o2_l"] = lim["o2_l"]
        if energy_j > lim["o2_l"] * J_PER_LITER_O2 + 1e-9:
            short.append("o2")
    if problem.time is not None:
        dur = float(problem.time[0, k] + problem.time[k, 0]) + float(problem.service_s[k])
        needs["duration_min"] = round(dur / 60.0, 2)
        if lim["max_duration_s"] is not None:
            available["duration_min"] = round(lim["max_duration_s"] / 60.0, 2)
            if dur > lim["max_duration_s"] + 1e-9:
                short.append("duration")
    out.update(reachable=True, fits_alone=not short, short=short, needs=needs,
               available=available, exact=short != ["duration"])
    return out


"""
What would let a station that does not fit alone fit (each line is needed; together they
are enough for that station alone, not for any other station or for the full tour).
"""
def _up(value, decimals):
    """value rounded up to `decimals` places, so the printed minimum is never below the need
    (62.72 -> 62.8, not 62.7). Matches the HUD's up() in web/index.html."""
    scale = 10 ** decimals
    return math.ceil(value * scale - 1e-9) / scale


def actions(alone, lim):
    out = []
    keep = 1.0 - lim["margin"]
    if "energy" in alone["short"]:
        need = alone["needs"]["energy_wh"]
        out.append(f"energy budget at least {_up(need / max(keep, 1e-12), 1):.1f} Wh at margin "
                   f"{lim['margin']:g} (or a lower margin)")
    if "o2" in alone["short"]:
        out.append(f"O2 budget at least {_up(alone['needs']['o2_l'], 2):.2f} L")
    if "duration" in alone["short"]:
        out.append(f"max duration at least {_up(alone['needs']['duration_min'], 1):.1f} min "
                   "(estimate: legs follow the least-energy path)")
    if "path" in alone["short"]:
        out.append("move the station or the habitat, or unblock cells: no walkable path")
    return out


"""
How far a station is from fitting alone: the largest need / available over its short
resources (1 = fits exactly). Unreachable stations sort last.
"""
def shortfall(alone):
    if not alone["reachable"]:
        return np.inf
    keys = {"energy": "energy_wh", "o2": "o2_l", "duration": "duration_min"}
    ratios = [alone["needs"][keys[r]] / max(alone["available"][keys[r]], 1e-12) for r in alone["short"]]
    return max(ratios) if ratios else 0.0


"""
Diagnosis when the solver returns no tour.
    problem : the E5 Problem (station 0 the habitat)
    ids : station ids, habitat first
    lim : from limits()
    solution : the solver's Solution (optimal False and bound None = search stopped without
               a tour and without proving there is none)
    solver_name, time_limit_s : for the search_incomplete message
"""
def no_tour(problem, ids, lim, solution, solver_name, time_limit_s=None):
    alone = [station_alone(problem, lim, k, ids[k]) for k in range(1, len(ids))]
    base = {"limits": public_limits(lim), "stations": alone}
    if alone and all(not a["reachable"] for a in alone):
        return {"code": "unreachable", "exact": True, **base,
                "message": "no station can be reached from the habitat and back on foot"}
    fits = [a for a in alone if a["fits_alone"]]
    if not fits:
        closest = min(alone, key=shortfall)
        short = ", ".join(closest["short"])
        keys = {"energy": "energy_wh", "o2": "o2_l", "duration": "duration_min", "path": None}
        detail = "; ".join(f"{r} needs {closest['needs'][keys[r]]:g}, available {closest['available'][keys[r]]:g}"
                           for r in closest["short"] if keys[r])
        return {"code": "insufficient_resources", "exact": all(a["exact"] for a in alone), **base,
                "limiting": closest["short"], "closest": closest, "actions": actions(closest, lim),
                "message": f"no station fits even alone (habitat > station > habitat); the closest is "
                           f"{closest['id']}, short of {short}" + (f" ({detail})" if detail else "")}
    limit = f" within its {time_limit_s:g} s limit" if time_limit_s else ""
    return {"code": "search_incomplete", "exact": False, **base,
            "fits_alone": [a["id"] for a in fits], "solver": solver_name,
            "proven_infeasible": bool(solution is not None and solution.optimal),
            "message": f"{len(fits)} station(s) fit alone, but the {solver_name} search found no tour"
                       f"{limit}; try fewer stations (the exact DP takes up to 19)"}


"""
Diagnosis of a tour that fits the limits at the stations but fails the walkback at some
vertex of the walked line after every re-plan (code "walkback", exact).
"""
def walkback_failure(profile, retries, lim):
    deficit = -float(profile["min_slack_j"])
    at = int(np.argmin(profile["slack_j"]))
    keep = 1.0 - lim["margin"]
    return {"code": "walkback", "exact": True, "limits": public_limits(lim),
            "first_violation": profile["first_violation"], "min_slack_index": at,
            "deficit_wh": round(deficit / J_PER_WH, 3), "retries": int(retries),
            "actions": [f"about {deficit / J_PER_WH / max(keep, 1e-12):.1f} Wh more energy budget for this tour "
                        "(a re-plan may find another tour)"],
            "message": f"every tour tried fails the walkback: at route vertex {profile['first_violation']} "
                       f"there is not enough energy left to return ({deficit / J_PER_WH:.1f} Wh short; "
                       f"{retries} re-plan(s) tried)"}


"""
Why each station that the tour leaves out was left out (exact when the solver is exact):
it does not fit alone (resources and needs as station_alone), or it fits alone but not
together with the chosen ones (the solver maximises points within the limits).
"""
def skipped(problem, ids, lim, route, exact):
    visited = set(route)
    out = {}
    for k in range(1, len(ids)):
        if k in visited:
            continue
        a = station_alone(problem, lim, k, ids[k])
        if a["fits_alone"]:
            a["reason"] = "fits alone, but not together with the chosen stations within the limits"
            a["exact"] = bool(exact)
        else:
            a["reason"] = "does not fit even alone: " + ", ".join(a["short"])
        out[str(ids[k])] = a
    return out


def public_limits(lim):
    return {"usable_energy_wh": round(lim["usable_j"] / J_PER_WH, 3), "o2_budget_l": lim["o2_l"],
            "max_duration_min": None if lim["max_duration_s"] is None else round(lim["max_duration_s"] / 60.0, 2),
            "margin": lim["margin"]}
