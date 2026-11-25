"""Return fields and walkback boundaries for the HUD (guide REV3, sections 20 and 34.3).

PROVISIONAL: E4 (Aaron) owns R(v). Until his rv.tif is delivered, the HUD uses
these fields, computed with the same E3 directed costs; swap the source when it
arrives.

- R_T(v): minimum TIME from v back to the base (s). The red line is R_T = 1800 s,
  the 30 min emergency-oxygen contingency. Cached per base.
- R_E(v): minimum ENERGY from v back to the base (J). Cached per base.
- F_E(p, v): minimum energy from the current position p to v (J), per request.
- Energy-safe region: F_E(p, v) + R_E(v) <= E_remaining (go to v and still get back).

R_T and R_E are Dijkstra runs from the base on the REVERSED graph, keeping the
cost of each original arc, so going down and coming back up are not mixed.
"""

import sys
from functools import lru_cache
from pathlib import Path

import contourpy
import numpy as np
import rasterio
from scipy import ndimage
from scipy.sparse.csgraph import dijkstra
from shapely.geometry import LineString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))



class Grid:
    """Base grid and the two sparse graphs (time, energy), taken from the planner's
    shared E4 Graph so walkback, /plan and the guide use exactly the same costs
    (E3, or E3 x E1's sand price when human=True)."""

    def __init__(self, base_dir, max_cell_slope_deg, human=True):
        from . import planner
        with rasterio.open(f"{base_dir}/dem_1m.tif") as src:
            self.transform = src.transform
            self.shape = (src.height, src.width)
        g = planner.graph(base_dir, max_cell_slope_deg, human)
        self.cost_model = g.cost_model
        self.time = g.csr("time_s")
        self.energy = g.csr("energy_j")
        self.time_rev = g.csr("time_s", reverse=True)
        self.energy_rev = g.csr("energy_j", reverse=True)

    def cell(self, x, y):
        row, col = rasterio.transform.rowcol(self.transform, x, y)
        if not (0 <= row < self.shape[0] and 0 <= col < self.shape[1]):
            raise ValueError("point is outside the study box")
        return row, col

    def node(self, x, y):
        row, col = self.cell(x, y)
        return row * self.shape[1] + col

    def region(self, field, level, seed_node):
        """Cells with field <= level that are connected to seed_node, holes filled.

        Blocked or unreachable cells (inf) are outside. Small blocked islands
        inside the region are filled, because the boundary we want to show is
        how far the astronaut can go, not every single steep cell.
        """
        inside = np.isfinite(field) & (field <= level)
        labels, _ = ndimage.label(inside, structure=np.ones((3, 3)))
        seed = labels.flat[seed_node]
        if seed == 0:
            return np.zeros(self.shape, bool)
        region = ndimage.binary_fill_holes(labels == seed)
        # Display smoothing (about 2 m): close small notches, then remove thin
        # fringes, so the line follows scarps instead of every steep cell.
        k = np.ones((3, 3), bool)
        smooth = ndimage.binary_opening(ndimage.binary_closing(region, k, iterations=2), k,
                                        iterations=2)
        smooth.flat[seed_node] = True              # never smooth away the seed itself
        labels, _ = ndimage.label(smooth, structure=np.ones((3, 3)))
        return ndimage.binary_fill_holes(labels == labels.flat[seed_node])

    def boundary(self, mask, simplify_m=2.0, min_length_m=40.0):
        """Outer boundary of a boolean region as MultiLineString coordinates
        (metres, DEM CRS), closed along the box edge and simplified."""
        f = np.zeros((self.shape[0] + 2, self.shape[1] + 2))
        f[1:-1, 1:-1] = mask                                    # one-cell outside border
        lines = contourpy.contour_generator(z=f, line_type="Separate").lines(0.5)
        a, e, c, b, d, fy = (self.transform.a, self.transform.e, self.transform.c,
                             self.transform.b, self.transform.d, self.transform.f)
        out = []
        for line in lines:
            cols, rows = line[:, 0] - 0.5, line[:, 1] - 0.5     # undo padding, cell centres
            xs = c + cols * a + rows * b
            ys = fy + cols * d + rows * e
            simple = LineString(np.column_stack([xs, ys])).simplify(simplify_m)
            if simple.length < min_length_m:                    # slivers of a few cells
                continue
            out.append(np.round(np.asarray(simple.coords), 2).tolist())
        return out

    def contour(self, field, level, seed_node):
        return self.boundary(self.region(field, level, seed_node))


@lru_cache(maxsize=4)
def grid(base_dir, max_cell_slope_deg, human=True):
    return Grid(base_dir, max_cell_slope_deg, human)


@lru_cache(maxsize=8)
def return_fields(base_dir, max_cell_slope_deg, base_node, human=True):
    """(R_T in s, R_E in J) as 2-D arrays; inf where the base cannot be reached."""
    g = grid(base_dir, max_cell_slope_deg, human)
    r_t = dijkstra(g.time_rev, directed=True, indices=base_node).reshape(g.shape)
    r_e = dijkstra(g.energy_rev, directed=True, indices=base_node).reshape(g.shape)
    return r_t, r_e


def forward_energy(base_dir, max_cell_slope_deg, start_node, limit_j, human=True):
    g = grid(base_dir, max_cell_slope_deg, human)
    return dijkstra(g.energy, directed=True, indices=start_node, limit=limit_j).reshape(g.shape)


# Fixed-radius rules the real return time is compared with (guide section 15.2).
FIXED_RADII_M = {"30 min at 0.75 m/s (guide)": 1350.0, "Apollo rule 1.7 km (3.4 km/h)": 1700.0}


def fixed_radius_check(g, r_t, base_xy, threshold_s):
    """For each fixed radius: the circle (metres, DEM CRS) and, over the cells of
    the box, the share of cells INSIDE the circle that cannot get back within
    threshold_s (falsely safe), and the share of the truly safe zone left OUTSIDE.
    The circle can extend past the 2 x 2 km box; only box cells are counted."""
    rows, cols = g.shape
    a, c, e, f = g.transform.a, g.transform.c, g.transform.e, g.transform.f
    xs = c + (np.arange(cols) + 0.5) * a
    ys = f + (np.arange(rows) + 0.5) * e
    dist = np.hypot(xs[None, :] - base_xy[0], ys[:, None] - base_xy[1])
    truly_safe = np.isfinite(r_t) & (r_t <= threshold_s)
    out = []
    for name, radius in FIXED_RADII_M.items():
        inside = dist <= radius
        n_inside = int(inside.sum())
        falsely_safe = inside & ~truly_safe
        no_way_back = inside & ~np.isfinite(r_t)                 # blocked or cut off
        too_slow = inside & np.isfinite(r_t) & (r_t > threshold_s)
        missed = truly_safe & ~inside
        ang = np.linspace(0, 2 * np.pi, 145)
        circle = np.column_stack([base_xy[0] + radius * np.cos(ang),
                                  base_xy[1] + radius * np.sin(ang)])
        out.append({
            "rule": name, "radius_m": radius,
            "circle": np.round(circle, 2).tolist(),
            "falsely_safe_pct": float(100 * falsely_safe.sum() / max(n_inside, 1)),
            "falsely_safe_no_way_back_pct": float(100 * no_way_back.sum() / max(n_inside, 1)),
            "falsely_safe_too_slow_pct": float(100 * too_slow.sum() / max(n_inside, 1)),
            "missed_safe_pct": float(100 * missed.sum() / max(int(truly_safe.sum()), 1)),
        })
    return out
