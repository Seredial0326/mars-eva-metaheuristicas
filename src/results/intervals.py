"""Intervals for registry rows, only where the population is well defined (C3, #120).

Each function names the unit that is resampled or counted, because that is the
choice that makes an interval honest here:
- independent trials (EVA worlds, simulated walks): Wilson for rates;
- spatial results: whole spatial blocks, never single pixels or vertices;
- paired policy comparisons: the same worlds for both policies.

`registry_text` gives the `interval` cell in the form the registry uses,
e.g. "95% Wilson 2.06–6.45".
"""

from __future__ import annotations

import math
from statistics import NormalDist

import numpy as np


def wilson(successes: int, trials: int, level: float = 0.95):
    """Wilson score interval for a rate over independent trials (works at 0 and n)."""
    if trials <= 0 or not 0 <= successes <= trials:
        raise ValueError("need 0 <= successes <= trials and trials > 0")
    if not 0 < level < 1:
        raise ValueError("level must be in (0, 1)")
    z = NormalDist().inv_cdf(0.5 + level / 2)
    p = successes / trials
    den = 1 + z * z / trials
    centre = (p + z * z / (2 * trials)) / den
    half = z * math.sqrt(p * (1 - p) / trials + z * z / (4 * trials * trials)) / den
    lo = 0.0 if successes == 0 else max(0.0, centre - half)
    hi = 1.0 if successes == trials else min(1.0, centre + half)
    return lo, hi


def block_bootstrap(values, blocks, stat=np.mean, *, n_boot: int = 2000,
                    level: float = 0.95, seed: int = 0):
    """Percentile bootstrap that resamples whole blocks (spatial tiles, sols, segments).

    `values[i]` belongs to block `blocks[i]`. Each replicate draws as many blocks
    as there are, with replacement, and keeps all values of each drawn block.
    With fewer than 5 blocks the interval says little; that raises instead.
    """
    v = np.asarray(values, dtype=float)
    b = np.asarray(blocks)
    if v.shape != b.shape or v.ndim != 1:
        raise ValueError("values and blocks must be 1-D and the same length")
    labels = np.unique(b)
    if len(labels) < 5:
        raise ValueError(f"{len(labels)} blocks are too few for a block bootstrap")
    groups = [v[b == label] for label in labels]
    rng = np.random.default_rng(seed)
    reps = np.empty(n_boot)
    for i in range(n_boot):
        pick = rng.integers(0, len(groups), len(groups))
        reps[i] = stat(np.concatenate([groups[j] for j in pick]))
    lo, hi = np.quantile(reps, [(1 - level) / 2, (1 + level) / 2])
    return float(lo), float(hi)


def paired_bootstrap(a, b, stat=np.mean, *, n_boot: int = 2000,
                     level: float = 0.95, seed: int = 0):
    """Interval for stat(a - b) when a[i] and b[i] come from the same world i."""
    d = np.asarray(a, dtype=float) - np.asarray(b, dtype=float)
    if d.ndim != 1 or len(d) < 2:
        raise ValueError("need two paired 1-D arrays with at least 2 worlds")
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(d), (n_boot, len(d)))
    reps = np.apply_along_axis(stat, 1, d[idx])
    lo, hi = np.quantile(reps, [(1 - level) / 2, (1 + level) / 2])
    return float(lo), float(hi)


def registry_text(lo: float, hi: float, method: str, *, level: float = 0.95,
                  scale: float = 1.0, digits: int = 2):
    """The registry's `interval` cell, e.g. registry_text(.0206, .0645, "Wilson", scale=100)."""
    return f"{round(100 * level):d}% {method} {lo * scale:.{digits}f}–{hi * scale:.{digits}f}"
