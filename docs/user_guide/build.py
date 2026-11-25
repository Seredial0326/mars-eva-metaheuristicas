"""Build the 2D planner user guide (docs/user_guide/index.html).

    node docs/user_guide/capture.mjs      # screenshots + boxes -> img/, shots.json
    python docs/user_guide/build.py       # template.html + shots.json -> index.html

The 3D map's guide uses the same builder on its own folder:

    node docs/user_guide_3d/capture.mjs
    python docs/user_guide/build.py docs/user_guide_3d

Every <!--SHOT:name--> marker in template.html becomes a figure: the screenshot with an
SVG layer on top (same coordinate space as the screenshot, so it scales with it). Each
control the text explains gets an outlined box, a numbered badge and an arrow from the
badge to the box. The numbers match the list under the figure (data-shot / data-n).
"""

import html
import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
PANEL_W = 372                     # width of the 2D planner's side panel at 1440 px; a shot can
                                  # give its own "panel_w" (0: no side panel)
SKIP = {"no-plan": {1}}            # behind the panel header after scrolling: not visible
# One sentence per screenshot for screen readers (the key list below it is linked too).
ALT = {
    "tips": "The planner with a tip card next to the side panel, pointing at the control it means.",
    "overview": "The planner: side panel with the step tabs on the left, the map of the 2 by 2 km area on the right.",
    "terrain": "Step 1, Terrain: the list of map layers and the slope limit on the left, the slope map on the right.",
    "stations": "Step 2, Stations: station type, load buttons, the folded Advanced section and the stations table.",
    "placing": "Placing a station: the add mode is on and a banner on the map says what a click will do.",
    "plan-inputs": "Step 3, Plan: the habitat, the limits (EVA length, energy budget, reserve) and the Plan the walk button.",
    "plan-result": "A plan: the guarantee chip, what it spends, the visiting order, radio and best time to leave, and the route on the map.",
    "no-plan": "No plan: the message says which station and resource fall short and what budget would fit.",
    "walk": "Step 4, Walk: the walk card, the energy bar and player, and the route with the safety lines on the map.",
    "probe": "Try another point: the astronaut placed on the map, with the time home and spare energy for that point.",
    "context": "Context: radiation with the storm simulator, and the weather of the chosen sol with its temperature chart.",
}


def visible(m, w, h):
    """Clip a box to the screenshot; None if less than 8 px of it shows."""
    x0, y0 = max(0, m["x"]), max(0, m["y"])
    x1, y1 = min(w, m["x"] + m["w"]), min(h, m["y"] + m["h"])
    if x1 - x0 < 8 or y1 - y0 < 8:
        return None
    return {"n": m["n"], "x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}


def badge_place(b, w, h, taken):
    """Where the numbered badge goes: outside the box, on the side with most room,
    away from badges already placed."""
    cx, cy = b["x"] + b["w"] / 2, b["y"] + b["h"] / 2
    off = 46
    cands = []
    if b["w"] > w * 0.5 and b["h"] > h * 0.5:                 # a huge box (the map): inside its corner
        cands.append((b["x"] + 40, b["y"] + 40))
    cands += [(b["x"] + b["w"] + off, cy), (b["x"] - off, cy), (cx, b["y"] - off), (cx, b["y"] + b["h"] + off),
              (b["x"] + b["w"] + off, b["y"]), (b["x"] - off, b["y"] + b["h"])]
    best, score = None, -1e9
    for px, py in cands:
        if not (22 <= px <= w - 22 and 22 <= py <= h - 22):
            continue
        clear = min((((px - qx) ** 2 + (py - qy) ** 2) ** 0.5 for qx, qy in taken), default=999)
        s = min(clear, 120)
        if s > score:
            best, score = (px, py), s
    if best is None:
        best = (min(max(cx, 22), w - 22), min(max(cy, 22), h - 22))
    return best


def edge_point(b, px, py):
    """Point on the box border nearest to the badge, where the arrow ends."""
    x = min(max(px, b["x"]), b["x"] + b["w"])
    y = min(max(py, b["y"]), b["y"] + b["h"])
    return x, y


def figure(name, shot):
    w, h = shot["w"], shot["h"]
    boxes = [v for m in shot["marks"] if m["n"] not in SKIP.get(name, set())
             if (v := visible(m, w, h))]
    taken, parts = [], []
    # Controls in the side panel: badges in one column just right of the panel, in the
    # order of the boxes from top to bottom, never closer than 40 px to each other.
    panel_w = shot.get("panel_w", PANEL_W)
    side = sorted([b for b in boxes if panel_w and b["x"] + b["w"] <= panel_w + 4], key=lambda b: b["y"] + b["h"] / 2)
    column, last = {}, -1e9
    for b in side:
        y = max(b["y"] + b["h"] / 2, last + 40)
        column[id(b)] = (panel_w + 34, min(y, h - 22))
        last = y
    # Dense controls in a box (the 3D player): "columns" [x_left, x_right] puts each badge
    # in the column on its side of the box, stacked from top to bottom, 36 px apart.
    if shot.get("columns"):
        xl, xr = shot["columns"]
        mid = (xl + xr) / 2
        sides = {"l": [], "r": []}
        for b in boxes:
            if id(b) in column:
                continue
            cx = b["x"] + b["w"] / 2
            if abs(cx - mid) < 40:                     # as wide as the box: the emptier side
                sides["l" if len(sides["l"]) <= len(sides["r"]) else "r"].append(b)
            else:
                sides["l" if cx < mid else "r"].append(b)
        for side, x in (("l", xl), ("r", xr)):
            last = -1e9
            for b in sorted(sides[side], key=lambda b: b["y"] + b["h"] / 2):
                y = max(b["y"] + b["h"] / 2, last + 36)
                column[id(b)] = (x, min(y, h - 22))
                last = y
    for b in boxes:
        px, py = column.get(id(b)) or badge_place(b, w, h, taken)
        taken.append((px, py))
        ex, ey = edge_point(b, px, py)
        dist = ((ex - px) ** 2 + (ey - py) ** 2) ** 0.5
        arrow = ""
        if dist > 26:
            # shorten the line so it starts at the badge's rim
            sx, sy = px + (ex - px) * 18 / dist, py + (ey - py) * 18 / dist
            arrow = (f'<line class="lead" x1="{sx:.0f}" y1="{sy:.0f}" x2="{ex:.0f}" y2="{ey:.0f}" '
                     f'marker-end="url(#arrow-{name})"/>')
        parts.append(
            f'<g class="mark" data-n="{b["n"]}">'
            f'<rect class="hl" x="{b["x"] - 3:.0f}" y="{b["y"] - 3:.0f}" width="{b["w"] + 6:.0f}" '
            f'height="{b["h"] + 6:.0f}" rx="7"/>{arrow}'
            f'<circle class="badge" cx="{px:.0f}" cy="{py:.0f}" r="17"/>'
            f'<text class="badge-n" x="{px:.0f}" y="{py + 6:.0f}">{b["n"]}</text></g>')
    shown = ",".join(str(b["n"]) for b in boxes)
    return (f'<figure class="shot" data-shot="{name}" data-shown="{shown}">'
            f'<div class="frame"><div class="canvas"><img src="{html.escape(shot["img"])}" width="{w}" height="{h}" '
            f'alt="{html.escape(ALT.get(name, "Screenshot: " + name))}" aria-describedby="keys-{name}" loading="lazy">'
            f'<svg viewBox="0 0 {w} {h}" preserveAspectRatio="none" aria-hidden="true">'
            f'<defs><marker id="arrow-{name}" viewBox="0 0 10 10" refX="8" refY="5" markerWidth="7" '
            f'markerHeight="7" orient="auto-start-reverse"><path d="M0,0 L10,5 L0,10 z" class="arrowhead"/></marker></defs>'
            + "".join(parts) +
            f'</svg></div></div><p class="swipe">Swipe sideways to see the whole screen.</p>'
            f'<a class="zoom" href="{html.escape(shot["img"])}" target="_blank" rel="noopener">'
            f'Open the full-size screenshot</a></figure>')


def main():
    folder = Path(sys.argv[1]).resolve() if len(sys.argv) > 1 else HERE
    shots = json.loads((folder / "shots.json").read_text(encoding="utf-8"))
    page = (folder / "template.html").read_text(encoding="utf-8")
    for name, shot in shots.items():
        page = page.replace(f"<!--SHOT:{name}-->", figure(name, shot))
    page = re.sub(r'<ol class="keys" data-shot="([\w-]+)">', r'<ol class="keys" id="keys-\1" data-shot="\1">', page)
    missing = [line for line in page.splitlines() if "<!--SHOT:" in line]
    if missing:
        raise SystemExit(f"no screenshot for: {missing}")
    (folder / "index.html").write_text(page, encoding="utf-8")
    print(f"wrote {folder / 'index.html'} ({len(page) / 1024:.0f} KB, {len(shots)} screenshots)")


if __name__ == "__main__":
    main()
