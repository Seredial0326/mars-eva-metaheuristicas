"""Radiation for the HUD, read from E12's outputs (Juan, data/e12/).

The HUD shows radiation as a dose budget along the EVA timeline and an SEP
alert scenario, never as a per-pixel map: at the scale of a few km the cosmic
background barely depends on position (guide REV3, section 43; E12 note).

SEP scenarios follow E12: storms x10 and x50 scale the EXCESS over the baseline
of the real 2025-11-11 event; they are hypothetical, not measured.
"""

import json
from pathlib import Path

UGY_DAY_TO_UGY_H = 1 / 24


def _load(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


def summary(e12_dir):
    """Background rate, the real SEP event and storm scenarios (rates in uGy/h)."""
    e12 = Path(e12_dir)
    rad = _load(e12 / "rad_summary.json")
    sep = _load(e12 / "sep_alert.json")
    route = _load(e12 / "route_dose.geojson")["properties"]
    ev = sep["strongest_event"]
    base_h = ev["baseline_ugy_day"] * UGY_DAY_TO_UGY_H
    peak_h = ev["peak_ugy_day"] * UGY_DAY_TO_UGY_H
    background_h = float(route["dose_rate"].split()[1]) * UGY_DAY_TO_UGY_H
    scenarios = [{"id": "real", "label": "Real event 2025-11-11 (peak 1.9x)",
                  "rate_ugy_h": peak_h, "measured": True}]
    for k in (10, 50):
        scenarios.append({"id": f"x{k}", "label": f"Storm x{k} (hypothetical)",
                          "rate_ugy_h": base_h + k * (peak_h - base_h), "measured": False})
    return {
        "background_ugy_h": background_h,
        "quality_factor_estimate": route.get("quality_factor_estimate"),
        "boxwork_sols": rad.get("boxwork_sols"),
        "sep_rule": sep["rule"],
        "real_event": {k: ev[k] for k in ("onset_utc", "alarm_utc", "alarm_delay_min",
                                          "duration_h", "peak_ratio", "excess_dose_ugy")},
        "scenarios": scenarios,
        "provisional_eva": {k: route[k] for k in ("length_m", "eva_time_h", "energy_wh",
                                                  "dose_ugy", "dose_usv_est")},
        "source": "E12 (Juan), data/e12/; provisional EVA = Curiosity traverse out and back",
    }


def dose_curve(e12_dir, max_points=300):
    """Accumulated dose against EVA time for the provisional route, downsampled."""
    feats = _load(Path(e12_dir) / "route_dose.geojson")["features"]
    step = max(1, len(feats) // max_points)
    pts = feats[::step] + ([feats[-1]] if (len(feats) - 1) % step else [])
    return [{"t_h": f["properties"]["t_s"] / 3600, "dose_ugy": f["properties"]["dose_ugy"]}
            for f in pts]
