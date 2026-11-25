"""Best time to leave (P6): the Sun port against the 3D view's mars_sun.js, the terrain
horizon on synthetic walls, and the scoring on a real saved /plan tour."""

import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))

from orienteering import departure as d

GALE = (d.planetographic_latitude(-4.78), 137.37)
PLAN = ROOT / "tests" / "viz3d" / "fixtures" / "plan_tour_e5.json"

NODE_CHECK = """
import {pathToFileURL} from 'node:url';
const m = await import(pathToFileURL(process.argv[2]).href);
const site = {latDeg: Number(process.argv[3]), lonEastDeg: Number(process.argv[4])};
const out = [];
for (const utc of JSON.parse(process.argv[5])) {
  const s = m.sunPosition(utc, site);
  out.push([s.elevation, s.azimuth, s.ltst, s.lmst]);
}
out.push(m.utcOfTrueSolarTime(4711, 15, site.lonEastDeg));
console.log(JSON.stringify(out));
"""


@pytest.mark.skipif(shutil.which("node") is None, reason="Node is not installed")
def test_sun_matches_the_3d_view(tmp_path):
    script = tmp_path / "check.mjs"
    script.write_text(NODE_CHECK)
    instants = [1768651200000.0, 1762868640000.0, 1717211700000.0, 1790000000000.0]
    done = subprocess.run(["node", str(script), str(ROOT / "web" / "3d" / "mars_sun.js"),
                           str(GALE[0]), str(GALE[1]), json.dumps(instants)],
                          capture_output=True, text=True, check=True)
    js = json.loads(done.stdout.strip().splitlines()[-1])
    for utc, (elev, az, ltst, lmst) in zip(instants, js[:-1]):
        py = d.sun_position(utc, *GALE)
        assert float(py["elevation"]) == pytest.approx(elev, abs=1e-9)
        assert float(py["azimuth"]) == pytest.approx(az, abs=1e-9)
        assert float(py["ltst"]) == pytest.approx(ltst, abs=1e-9)
        assert float(py["lmst"]) == pytest.approx(lmst, abs=1e-9)
    assert d.utc_of_true_solar_time(4711, 15, GALE[1]) == pytest.approx(js[-1], abs=1.0)


def test_local_time_and_noon():
    utc = d.utc_of_true_solar_time(4711, 12.0, GALE[1])
    sun = d.sun_position(utc, *GALE)
    assert float(sun["ltst"]) == pytest.approx(12.0, abs=1e-6)
    off_meridian = min(float(sun["azimuth"]) % 180, 180 - float(sun["azimuth"]) % 180)
    assert off_meridian < 1e-6                                         # due north or due south at true noon
    before, after = (d.sun_position(utc + s * 3.6e6, *GALE)["elevation"] for s in (-1, 1))
    assert float(sun["elevation"]) > max(float(before), float(after))   # highest at true noon
    night = d.sun_position(d.utc_of_true_solar_time(4711, 0.0, GALE[1]), *GALE)
    assert float(night["elevation"]) < 0


def test_lon_lat_of_the_crs():
    lon, lat = d.lon_lat(8143537.99, -284463.58)
    assert lon == pytest.approx(137.38, abs=0.01) and lat == pytest.approx(-4.80, abs=0.01)


def flat_with_wall(wall_height):
    """100 x 100 m flat DEM (1 m cells, top-left at x=0, y=100) with a wall at x >= 60."""
    dem = np.zeros((100, 100))
    dem[:, 60:] = wall_height
    return dem, (1.0, 0.0, 0.0, 0.0, -1.0, 100.0)


def test_horizon_of_a_wall():
    dem, transform = flat_with_wall(20.0)
    h = d.horizon_table([(40.5, 50.5)], dem, transform, eye_m=0.0, max_m=50, step_m=0.5, bins=4)
    # East (bin 1): the wall top 20 m up, its face 19.5 m away (x = 60 against 40.5)
    assert h[0, 1] == pytest.approx(np.degrees(np.arctan2(20.0, 19.5)), abs=1e-9)
    assert h[0, 3] == pytest.approx(0.0)              # west: flat ground at eye height
    assert h[0, 0] == pytest.approx(0.0) and h[0, 2] == pytest.approx(0.0)


def test_shadow_and_darkness_states():
    dem, transform = flat_with_wall(200.0)
    xy = np.array([(40.5, 50.5), (40.5, 51.5)])
    t_s = np.array([0.0, 600.0])
    horizon = d.horizon_table(xy, dem, transform, max_m=60)
    rows, best, window = d.score_departures(xy, t_s, 4711, [0.0, 8.0, 12.0, 16.0], horizon)
    by = {r["start_ltst_h"]: r for r in rows}
    assert by[0.0]["dark_share"] == 1.0                                # midnight
    assert by[8.0]["shadow_share"] == 1.0                              # low eastern Sun behind the wall
    assert by[16.0]["sunlit_share"] == 1.0                             # western Sun, nothing in the way
    assert best["sunlit_share"] == 1.0 and window is not None
    flat = d.score_departures(xy, t_s, 4711, [8.0], None)[0][0]
    assert flat["sunlit_share"] == 1.0                                 # no terrain: no shadow


def test_real_tour_from_a_saved_plan():
    xy, t_s = d.tour_from_plan(json.loads(PLAN.read_text(encoding="utf-8")))
    assert len(xy) == len(t_s) and t_s[0] == 0 and np.all(np.diff(t_s) >= 0)
    rows, best, window = d.score_departures(xy, t_s, 4711, np.arange(5.0, 19.01, 1.0))
    assert best["sunlit_share"] == 1.0 and 10.0 <= best["start_ltst_h"] <= 12.0
    assert window[0] < best["start_ltst_h"] < window[1]
    assert all(0.999 <= r["sunlit_share"] + r["shadow_share"] + r["dark_share"] <= 1.001 for r in rows)
    assert rows[-1]["dark_share"] == 1.0                              # leaving at 19:00 is all in the dark


def test_terrain_only_removes_light():
    import rasterio  # noqa: F401  (the DEM is needed)
    if not d.DEM_PATH.exists():
        pytest.skip("data/base/dem_1m.tif not downloaded")
    xy, t_s = d.tour_from_plan(json.loads(PLAN.read_text(encoding="utf-8")))
    dem, transform = d.load_dem()
    starts = np.arange(5.0, 19.01, 0.5)
    with_terrain = d.score_departures(xy, t_s, 4711, starts, d.horizon_table(xy, dem, transform))[0]
    smooth = d.score_departures(xy, t_s, 4711, starts, None)[0]
    assert all(a["sunlit_share"] <= b["sunlit_share"] + 1e-9 for a, b in zip(with_terrain, smooth))
    assert any(a["shadow_share"] > 0 for a in with_terrain)              # the box's relief does cast shadows


def test_clock():
    assert d.clock(11.0) == "11:00" and d.clock(6.5) == "06:30" and d.clock(23.99) == "23:59"
