"""Boulder risk term for the route cost (X1, #102).

The energy of every arc is multiplied by a factor of its ARRIVAL cell, as the E1
sand price does (fisica.human_cost.human_edge_costs):

    factor(v) = 1 + k * (mean(v) + lam * std(v))

- mean, std: boulder cover (fraction 0-1) and its uncertainty, e.g. E9's
  rocks_mean.tif / rocks_std.tif (GP) or rocas.tif with std = 0.
- k: price per unit of cover. It has no source: E1 (#108) found no held-out price
  for boulders, so k is a sensitivity knob (k = 0 turns the term off).
- lam: how many standard deviations of caution. lam = 0 (default) uses the mean
  only; lam = 1.645 prices the upper end of a 90 % interval (one-sided 95 %).

NaN cells (nodata) count as no boulder.
"""

import numpy as np


def rock_factor(mean, std=None, k=0.0, lam=0.0):
    """Per-cell multiplicative factor >= 1."""
    if k < 0 or lam < 0:
        raise ValueError("k and lam must be >= 0")
    m = np.nan_to_num(np.asarray(mean, dtype=np.float64), nan=0.0)
    s = 0.0 if std is None else np.nan_to_num(np.asarray(std, dtype=np.float64), nan=0.0)
    risk = np.clip(m + lam * s, 0.0, None)
    return 1.0 + k * risk


def apply_to_energy(energy_j, factor, neighbours):
    """(8, H, W) arc energies x factor of each arc's arrival cell (same convention
    as fisica.human_cost: arc d from (r, c) arrives at (r + dr, c + dc))."""
    from fisica.human_cost import human_edge_costs
    return human_edge_costs(energy_j, factor, neighbours)
