"""
Benchmark instances for E6: readers for the KU Leuven classic OP files and a random
generator with the E5 rules (service, time windows).
"""
from pathlib import Path

import numpy as np

from orienteering.problem import Problem

REPO = Path(__file__).resolve().parents[2]
INSTANCE_DIRS = [REPO / "data" / "08_instancias_orienteering",
                 REPO.parent / "data" / "08_instancias_orienteering"]


"""
Folder of the KU Leuven instances (data/08_instancias_orienteering, in the repo's data
folder or the team's shared one next to the repo), or None.
"""
def instance_dir():
    return next((d for d in INSTANCE_DIRS if d.exists()), None)


"""
Classic OP file (Tsiligirides, Chao; OP_clasico/OP_format.txt): first line "Tmax P",
then "x y score" per point; the first point is the start, the second the end;
Euclidean distances. The distance plays the role of energy and Tmax of the budget.
"""
def read_op(path):
    rows = [line.split() for line in Path(path).read_text().splitlines() if line.strip()]
    tmax = float(rows[0][0])
    pts = np.array([[float(v) for v in r[:3]] for r in rows[1:]])
    dist = np.linalg.norm(pts[:, None, :2] - pts[None, :, :2], axis=2)
    return Problem(energy=dist, prize=pts[:, 2].copy(), budget=tmax, start=0, end=1)


def tsiligirides(root=None):
    root = root or instance_dir()
    files = sorted((root / "OP_clasico").glob("Tsiligirides_*/extraido/*/tsiligirides_problem_*_budget_*.txt"))
    return [(f"T{f.stem.split('_')[2]}-{int(f.stem.split('_')[-1])}", read_op(f)) for f in files]


"""
Random instance with n nodes (node 0 = habitat, start and end): points in a 100 x 100
square, energy = distance x an asymmetric factor in [0.9, 1.2], prizes 1-5, 0-20 units
of service energy per station; the budget is a fraction (0.3-0.7) of a nearest-neighbour
tour through every station, so part of them fit.
kind "windows" adds walking time (= energy), service time (= service energy) and a
window on about half of the stations.
"""
def random_instance(rng, n, kind="energy"):
    pts = rng.random((n, 2)) * 100
    energy = np.linalg.norm(pts[:, None] - pts[None], axis=2) * rng.uniform(0.9, 1.2, (n, n))
    np.fill_diagonal(energy, 0.0)
    prize = np.r_[0.0, rng.integers(1, 6, n - 1).astype(float)]
    service = np.r_[0.0, rng.uniform(0, 20, n - 1)]
    full = nearest_neighbour_cost(energy) + service.sum()
    p = Problem(energy=energy, prize=prize, budget=rng.uniform(0.3, 0.7) * full, service_j=service)
    if kind == "windows":
        p.time = energy.copy()
        p.service_s = service.copy()
        opens = np.where(rng.random(n) < 0.5, rng.uniform(0, 0.5 * full, n), 0.0)
        widths = rng.uniform(0.15, 0.5, n) * full
        p.windows = np.column_stack([opens, np.where(opens > 0, opens + widths, np.inf)])
        p.windows[0] = [0.0, np.inf]
    return p


def nearest_neighbour_cost(energy, start=0):
    left, at, cost = set(range(len(energy))) - {start}, start, 0.0
    while left:
        nxt = min(left, key=lambda k: energy[at, k])
        cost += energy[at, nxt]
        left.discard(nxt)
        at = nxt
    return cost + energy[at, start]
