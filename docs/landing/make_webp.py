"""Turn the PNG screenshots of docs/landing/capture.mjs into the WebP files the landing
page and the demo page use (web/home/assets/<name>-<width>.webp), in the same widths as
before, at quality 80.

    python docs/landing/make_webp.py [png-dir] [only,these,shots]

png-dir defaults to <system temp>/landing-shots, capture.mjs's default. A PNG that is not
there is left as it is in web/home/assets/ (for example photo-3d without the rover photos).
"""
import sys
import tempfile
from pathlib import Path

from PIL import Image

ASSETS = Path(__file__).resolve().parents[2] / "web" / "home" / "assets"
WIDTHS = {
    "hero-3d": (960, 1600, 2400),
    "poster-3d": (960, 1600),
    "plan-2d": (800, 1400, 2000),
    "walkback-2d": (800, 1400, 2000),
    "rehearse-3d": (800, 1400, 2000),
    "photo-3d": (640, 1000, 1600),
    "guide-walk": (480, 800, 1184),
    "guide-storm": (480, 800, 1184),
    **{f"step-{s}": (640, 1000, 1600)
       for s in ("terrain", "cost", "steep", "stations", "radio", "storm", "weather", "rehearse")},
}


def main(src, only=None):
    for name, widths in WIDTHS.items():
        if only and name not in only:
            continue
        png = src / f"{name}.png"
        if not png.exists():
            print(f"{name}: no PNG, kept as it is")
            continue
        img = Image.open(png).convert("RGB")
        for w in widths:
            h = round(img.height * w / img.width)
            out = ASSETS / f"{name}-{w}.webp"
            img.resize((w, h), Image.LANCZOS).save(out, "WEBP", quality=80, method=6)
            print(f"{out.name} {w}x{h} {out.stat().st_size // 1024} KB")


if __name__ == "__main__":
    src = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(tempfile.gettempdir()) / "landing-shots"
    only = set(sys.argv[2].split(",")) if len(sys.argv) > 2 else None
    main(src, only)
