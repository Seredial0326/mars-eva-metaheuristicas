"""X2 (#101): learn the astronaut's own metabolic cost during the walk.

Model: real O2 use = k x E3's predicted O2, with one multiplicative factor k for the
whole EVA (suit, fitness, load, terrain the model misses). We filter log k:

    prior        log k ~ N(mu0, sd0^2)              (default N(0, 0.3^2): k within ~+-35 %)
    observation  y = log(o2_observed / o2_predicted) = log k + eps,  eps ~ N(0, sigma_obs^2)

Normal prior x normal likelihood is conjugate, so after each segment the posterior of
log k stays normal and the update is closed form (precisions add). k is lognormal:
its median is exp(mu) and its quantiles are exp(mu + z_q sd).

Because O2 is E / 20.1 kJ/L (fisica.metabolic.liters_o2), the same k applies to energy:
pass Wh instead of litres and nothing changes. Pure functions, no I/O.
"""

from dataclasses import dataclass
from math import exp, log, sqrt

from scipy.stats import norm

PRIOR_SD = 0.3          # sd of log k before the walk (issue #101)
SIGMA_OBS = 0.15        # default noise of one segment's log ratio (declared assumption)


@dataclass(frozen=True)
class Posterior:
    """Normal belief on log k, and how many segments were used."""
    mu: float = 0.0
    sd: float = PRIOR_SD
    n: int = 0

    def as_dict(self):
        return {"mu": self.mu, "sd": self.sd, "n": self.n}


def prior(sd=PRIOR_SD, mu=0.0):
    if sd <= 0:
        raise ValueError("prior sd must be > 0")
    return Posterior(mu=float(mu), sd=float(sd), n=0)


def update(post, o2_observed, o2_predicted, sigma_obs=SIGMA_OBS):
    """Posterior after one segment with o2_observed used against o2_predicted.

    A segment with no predicted or no observed use carries no information on k and
    returns `post` unchanged. sigma_obs > 0 is the noise of log(observed/predicted)."""
    if sigma_obs <= 0:
        raise ValueError("sigma_obs must be > 0")
    if not (o2_predicted > 0 and o2_observed > 0):
        return post
    y = log(o2_observed / o2_predicted)
    prec0, prec_y = 1.0 / post.sd ** 2, 1.0 / sigma_obs ** 2
    prec = prec0 + prec_y
    mu = (post.mu * prec0 + y * prec_y) / prec
    return Posterior(mu=mu, sd=sqrt(1.0 / prec), n=post.n + 1)


def update_many(post, observed, predicted, sigma_obs=SIGMA_OBS):
    for o, p in zip(observed, predicted):
        post = update(post, o, p, sigma_obs)
    return post


def quantile(post, q):
    """q-quantile of k (lognormal)."""
    if not 0 < q < 1:
        raise ValueError("q must be in (0, 1)")
    return exp(post.mu + norm.ppf(q) * post.sd)


def interval(post, level=0.90):
    """Central credible interval of k at `level` (e.g. 0.90 -> p5 and p95)."""
    a = (1 - level) / 2
    return quantile(post, a), quantile(post, 1 - a)


def summary(post, q_reserve=0.90):
    lo, hi = interval(post, 0.90)
    return {"k_median": exp(post.mu), "k_mean": exp(post.mu + post.sd ** 2 / 2),
            f"k_p{round(q_reserve * 100)}": quantile(post, q_reserve),
            "ci90": [lo, hi], "ci90_width": hi - lo, "log_k": post.as_dict()}


def reserve_check(o2_used, o2_return_predicted, o2_budget, k_reserve):
    """Can the astronaut still get home? The return needs k_reserve x the predicted
    return (same route: a uniform k does not change which path is cheapest).

    o2_used is what was really used so far (observed). Returns the reserve needed,
    what is left after it, and return_now when the return no longer fits."""
    need = k_reserve * o2_return_predicted
    left = o2_budget - o2_used
    return {"reserve_needed": need, "remaining": left, "margin_after_return": left - need,
            "return_now": need > left}
