"""Surface weather at Gale from Curiosity's REMS (P4, issue #44).

Source: the public MSL weather feed (Centro de Astrobiologia, CAB), one record per
sol with air and ground temperature ranges, pressure, UV index, sunrise and sunset.
The feed declares itself "for outreach purposes only"; REMS science data is in PDS.
It is context for the EVA (when to go out, how cold the ground is), not a cost term:
it has one value per sol for the whole site, not a map.

Every value in the feed is a string and "--" means missing.
"""

import json
from functools import lru_cache
from pathlib import Path

# Boxwork campaign: sol 4541 (arrival, 2025-05-15) to sol 4848 (departure), from the
# dates of the images and REMS itself (data/README.md, note 1).
CAMPAIGN_SOLS = (4541, 4848)
DEFAULT_SOL = 4711          # Nevado Sajama drill; also the 3D view's default sol (P1 block 4)
UV_LEVELS = ["Low", "Moderate", "High", "Very_High"]


def _num(v):
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _minutes(hhmm):
    try:
        h, m = hhmm.split(":")
        return int(h) * 60 + int(m)
    except (AttributeError, ValueError):
        return None


def find_feed(data_dir):
    """The REMS feed: release folder data/rems/ first, then the downloaded kit."""
    data_dir = Path(data_dir)
    for p in (data_dir / "rems" / "rems_weather_msl.json",
              data_dir / "03_curiosity" / "clima_rems" / "rems_weather_msl.json"):
        if p.exists():
            return p
    return None


@lru_cache(maxsize=2)
def load(path):
    """Parsed records keyed by sol (int), numbers as floats, missing as None."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    out = {}
    for r in raw["soles"]:
        sol = _num(r.get("sol"))
        if sol is None:
            continue
        rise, set_ = _minutes(r.get("sunrise")), _minutes(r.get("sunset"))
        uv = r.get("local_uv_irradiance_index")
        out[int(sol)] = {
            "sol": int(sol), "earth_date": r.get("terrestrial_date"),
            "ls_deg": _num(r.get("ls")), "season": r.get("season"),
            "air_min_c": _num(r.get("min_temp")), "air_max_c": _num(r.get("max_temp")),
            "ground_min_c": _num(r.get("min_gts_temp")), "ground_max_c": _num(r.get("max_gts_temp")),
            "pressure_pa": _num(r.get("pressure")),
            "uv_index": uv if uv in UV_LEVELS else None,
            "opacity": None if r.get("atmo_opacity") in (None, "--") else r.get("atmo_opacity"),
            "sunrise": r.get("sunrise") if rise is not None else None,
            "sunset": r.get("sunset") if set_ is not None else None,
            "daylight_h": None if rise is None or set_ is None else round((set_ - rise) / 60, 2),
        }
    return out


def nearest(records, sol):
    """The record of `sol`, or of the nearest sol with data (REMS has gaps)."""
    if sol in records:
        return records[sol]
    return records[min(records, key=lambda s: (abs(s - sol), s))]


def summary(path, sol=DEFAULT_SOL, eva_min=None):
    """Weather of one sol, the boxwork campaign series and plain-words EVA notes."""
    recs = load(str(path))
    day = dict(nearest(recs, sol))
    day["requested_sol"] = sol
    a, b = CAMPAIGN_SOLS
    series = [{k: r[k] for k in ("sol", "air_min_c", "air_max_c", "ground_min_c", "ground_max_c")}
              for s, r in sorted(recs.items()) if a <= s <= b and r["air_min_c"] is not None]
    lows = [r["air_min_c"] for r in series]
    highs = [r["air_max_c"] for r in series]
    notes = []
    if day["daylight_h"] is not None:
        notes.append(f"Daylight {day['sunrise']}–{day['sunset']} local time "
                     f"({day['daylight_h']:.1f} h)")
        if eva_min is not None:
            fits = eva_min / 60 <= day["daylight_h"]
            notes.append(f"A {eva_min:.0f} min EVA {'fits' if fits else 'does NOT fit'} in daylight")
    if day["ground_max_c"] is not None and day["ground_min_c"] is not None:
        notes.append(f"Ground {day['ground_min_c']:.0f} to {day['ground_max_c']:.0f} °C: "
                     "the suit's boots and gloves see this range, not the air's")
    if day["uv_index"]:
        notes.append(f"UV {day['uv_index'].replace('_', ' ').lower()} (no ozone layer on Mars)")
    return {
        "day": day,
        "campaign": {"sols": list(CAMPAIGN_SOLS), "n_sols": len(series),
                     "air_min_c": min(lows) if lows else None,
                     "air_max_c": max(highs) if highs else None, "series": series},
        "notes": notes,
        "sol_range": [min(recs), max(recs)],
        "source": "MSL REMS public weather feed (CAB/NASA); outreach product, one value per sol",
        "units": {"temperature": "°C", "pressure": "Pa", "time": "local time on the feed"},
    }
