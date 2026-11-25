"""Paths and shared contracts for the E2 and E1 scripts.

The crop box and the CRS are read from the contracts JB published
(docs/contracts/) instead of being copied by hand, so a contract change
reaches these scripts automatically.
"""
import json
import os
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CONTRACTS = REPO / "docs" / "contracts"

# Team products (outside git: data/* is in .gitignore).
PRODUCTS = REPO / "data"
BASE = PRODUCTS / "base"      # JB's base grid (release base-grid-vN)
E2_OUTPUT = PRODUCTS / "e2"
E1_OUTPUT = PRODUCTS / "e1"

# Provisional sol range of the boxwork (data/README.md, section 6).
# The team sets the final range; here it only flags the poses.
BOXWORK_SOLS = (4541, 4848)


def crop_box():
    """(xmin, ymin, xmax, ymax) of the crop, read from docs/contracts/grid.json."""
    bbox = json.loads((CONTRACTS / "grid.json").read_text(encoding="utf-8-sig"))["bbox"]
    return bbox["xmin"], bbox["ymin"], bbox["xmax"], bbox["ymax"]


def crs_wkt():
    return (CONTRACTS / "crs.wkt").read_text(encoding="utf-8").strip()


def raw_data_dir():
    """Folder with the downloaded data (01_terreno, 03_curiosity, ...).

    Uses MARTIAN_DATA if set; otherwise tries the repo's data/ (where
    clonar_desde_lan.py puts it), data/raw/ and the sibling folder ../data.
    """
    env = os.environ.get("MARTIAN_DATA")
    candidates = [Path(env)] if env else [PRODUCTS, PRODUCTS / "raw", REPO.parent / "data"]
    for c in candidates:
        if (c / "01_terreno").is_dir():
            return c
    raise SystemExit(
        "Could not find the downloaded data. Set MARTIAN_DATA to the folder "
        "that contains 01_terreno/ and 03_curiosity/. Tried: " + ", ".join(map(str, candidates))
    )


def places_interp():
    # localized_interp.csv, not the _demv2 variant: that one is tied to another
    # DEM version (about +56 m in height and up to 22 m of horizontal shift
    # against DEM v3).
    return raw_data_dir() / "03_curiosity" / "places_pds" / "data_localizations" / "localized_interp.csv"


def base_layer(name):
    """A layer of JB's base grid in data/base/ (never crop a different box)."""
    path = BASE / name
    if not path.exists():
        raise SystemExit(
            f"Missing data/base/{name}. Download the base grid from the repo root:\n"
            "  gh release download base-grid-v2 --dir data\n"
            "and unzip data/base_grid_v2.zip into data/base/."
        )
    return path
