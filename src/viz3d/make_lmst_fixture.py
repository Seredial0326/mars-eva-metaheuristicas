"""Fixture for the Mars time test (tests/viz3d/mars_sun.test.mjs): real pairs of UTC and
Curiosity local mean solar time.

Run from the repo root:
    python src/viz3d/make_lmst_fixture.py --index-dir <...>/03_curiosity/imagenes_crudas/indice_soles_4450_4848

The folder holds the pages of the public raw-image index of Curiosity for sols 4450 to
4848 (`page_*.json`, downloaded by the team; see data/README.md). Every image has
`date_taken` (UTC, whole seconds) and, in `extended.lmst`, the mission's own local time
(`Sol-04450M08:30:55.289`). This script keeps a few of them so the test needs no data:

  - only Navcam images (`instrument` starts with `NAV_`), which carry `lmst`;
  - about 30 sols spread evenly over the sols that have Navcam images, plus sol 4711
    (the default sol of the 3D map) or the nearest one that has Navcam images;
  - one image per sol, taken at a different place of the sol's list each time so the
    pairs cover different hours.

Only `sol`, `instrument`, `date_taken` and `lmst` are written. The choice is
deterministic: running it again on the same index writes the same file.
"""

import argparse
import json
import re
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT = REPO / "tests" / "viz3d" / "fixtures" / "msl_lmst_pairs.json"
LMST = re.compile(r"^Sol-(\d{5})M(\d\d):(\d\d):(\d\d\.\d+)$")
N_SOLS = 30
MUST_HAVE_SOL = 4711


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--index-dir", required=True, help="folder with page_*.json")
    index_dir = Path(ap.parse_args().index_dir)

    by_sol, pages, navcam = {}, 0, 0
    for page in sorted(index_dir.glob("page_*.json")):
        pages += 1
        for item in json.loads(page.read_text(encoding="utf-8"))["items"]:
            lmst = (item.get("extended") or {}).get("lmst")
            if not str(item.get("instrument", "")).startswith("NAV_") or not lmst or not item.get("date_taken"):
                continue
            match = LMST.match(lmst)
            if not match or int(match.group(1)) != item["sol"]:
                raise SystemExit(f"unexpected lmst {lmst!r} for sol {item['sol']} (image {item.get('imageid')})")
            navcam += 1
            by_sol.setdefault(item["sol"], {})[(item["date_taken"], item["instrument"])] = lmst

    sols = sorted(by_sol)
    chosen = {sols[round(i * (len(sols) - 1) / (N_SOLS - 1))] for i in range(N_SOLS)}
    chosen.add(min(sols, key=lambda s: (abs(s - MUST_HAVE_SOL), s)))
    pairs = []
    for i, sol in enumerate(sorted(chosen)):
        images = sorted(by_sol[sol].items())
        (date_taken, instrument), lmst = images[(i * 7919) % len(images)]
        pairs.append({"sol": sol, "instrument": instrument, "date_taken": date_taken, "lmst": lmst})

    doc = {
        "source": "Curiosity raw-image index (mars.nasa.gov raw images API), sols 4450-4848, Navcam only",
        "made_by": "src/viz3d/make_lmst_fixture.py",
        "note": "date_taken is UTC in whole seconds; lmst is the mission clock (local mean solar time at 137.42 E)",
        "index": {"pages": pages, "navcam_images_with_lmst": navcam, "sols_with_navcam": len(sols),
                  "first_sol": sols[0], "last_sol": sols[-1]},
        "pairs": pairs,
    }
    OUT.write_text(json.dumps(doc, indent=1) + "\n", encoding="utf-8")
    print(OUT, f"{len(pairs)} pairs from {len(sols)} sols with Navcam images ({navcam} images, {pages} pages)")


if __name__ == "__main__":
    main()
