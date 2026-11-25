"""X2 (#101): adaptive walkback. POST /walkback/update learns the astronaut's own
metabolic factor k from each walked segment and re-checks the way home with a high
quantile of k (k_p90 by default), not the mean.

- Filter: src/fisica/adaptive_k.py (conjugate normal on log k, prior N(0, 0.3^2)).
- A uniform k scales every E3 arc by the same factor, so the cheapest way home does
  not change and the reserve is exactly k_p90 x R(v). The 30 min line (time) does not
  change either: k is metabolic, not speed.
- Units: one unit for the whole request, Wh (E3 energy) or L (metabolic O2). The ratio
  observed / predicted, and so k, is the same in both (O2 = E / 20.1 kJ/L).
- Stateless: the client sends back the posterior it got from the previous call.
"""

import sys
from pathlib import Path
from typing import List, Literal, Optional, Tuple

from pydantic import BaseModel, Field, model_validator

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fisica import adaptive_k as ak  # noqa: E402

from .plan import SlopeLimit  # noqa: E402

WH_PER_L_O2 = 20.1 / 3.6       # 20.1 kJ/L (fisica.metabolic.KJ_PER_LITER_O2) in Wh/L


class PosteriorIn(BaseModel):
    mu: float = 0.0
    sd: float = Field(default=ak.PRIOR_SD, gt=0)
    n: int = Field(default=0, ge=0)


class SegmentIn(BaseModel):
    """What one walked segment used, against what E3 predicted for it (same unit)."""
    observed: float = Field(ge=0)
    predicted: float = Field(ge=0)


class UpdateRequest(BaseModel):
    posterior: Optional[PosteriorIn] = None          # null: the prior (start of the EVA)
    segment: Optional[SegmentIn] = None               # null: only re-check the reserve
    unit: Literal["Wh", "L"] = "Wh"
    used: float = Field(ge=0)                         # really used so far (observed)
    budget: float = Field(gt=0)                       # usable budget, same unit
    # The predicted (k = 1) return from here: give it (route's rv_wh at the vertex), or
    # give position (+ habitat) and the server takes R_E(v) from the walkback fields.
    return_predicted: Optional[float] = Field(default=None, ge=0)
    position: Optional[Tuple[float, float]] = None
    habitat: Optional[Tuple[float, float]] = None
    max_cell_slope_deg: SlopeLimit = 30.0                 # null = no block (api/plan.py)
    human_cost: bool = True
    # Rest of the planned route from the current vertex (k = 1, same unit, absolute
    # used and return need per vertex), to find the point of no return with k_p90.
    plan_used: Optional[List[float]] = None
    plan_return: Optional[List[float]] = None
    q_reserve: float = Field(default=0.90, gt=0.5, lt=1)
    sigma_obs: float = Field(default=ak.SIGMA_OBS, gt=0)
    prior_sd: float = Field(default=ak.PRIOR_SD, gt=0)

    @model_validator(mode="after")
    def need_a_return(self):
        if self.return_predicted is None and self.position is None:
            raise ValueError("give return_predicted, or position to compute it")
        if (self.plan_used is None) != (self.plan_return is None):
            raise ValueError("give both plan_used and plan_return, or neither")
        if self.plan_used is not None and len(self.plan_used) != len(self.plan_return):
            raise ValueError("plan_used and plan_return must have the same length")
        return self


def point_of_no_return(used_now, plan_used, plan_return, budget, k):
    """First index j of the rest of the plan where, at factor k, what will have been
    used plus what the way home needs no longer fits: used_now + k (U_j - U_0) + k R_j
    > budget. None if the whole plan still fits. Index 0 is the current vertex."""
    u0 = plan_used[0]
    for j, (u, r) in enumerate(zip(plan_used, plan_return)):
        if used_now + k * (u - u0) + k * r > budget:
            return j
    return None


def update(req, return_predicted):
    p = req.posterior
    post = ak.prior(req.prior_sd) if p is None else ak.Posterior(p.mu, p.sd, p.n)
    if req.segment is not None:
        post = ak.update(post, req.segment.observed, req.segment.predicted, req.sigma_obs)
    s = ak.summary(post, req.q_reserve)
    k_res = ak.quantile(post, req.q_reserve)
    adaptive = ak.reserve_check(req.used, return_predicted, req.budget, k_res)
    fixed = ak.reserve_check(req.used, return_predicted, req.budget, 1.0)
    out = {
        "posterior": post.as_dict(),
        "k": {"median": s["k_median"], "mean": s["k_mean"], "reserve": k_res,
              "q_reserve": req.q_reserve, "ci90": s["ci90"], "ci90_width": s["ci90_width"]},
        "unit": req.unit, "used": req.used, "budget": req.budget,
        "return_predicted": return_predicted,
        "reserve": {**adaptive, "k": k_res},
        "fixed": {**fixed, "k": 1.0},
        "return_now": adaptive["return_now"],
        "no_return_index": None, "no_return_index_fixed": None,
        "warnings": ["k is learned from simulated or reported use; validated in simulation "
                     "only, not with astronauts"],
    }
    if req.plan_used is not None and len(req.plan_used):
        out["no_return_index"] = point_of_no_return(req.used, req.plan_used, req.plan_return,
                                                    req.budget, k_res)
        out["no_return_index_fixed"] = point_of_no_return(req.used, req.plan_used,
                                                          req.plan_return, req.budget, 1.0)
    if post.n == 0:
        out["warnings"].append("no segment observed yet: k is the prior")
    return out


def to_unit(wh, unit):
    return wh if unit == "Wh" else wh / WH_PER_L_O2
