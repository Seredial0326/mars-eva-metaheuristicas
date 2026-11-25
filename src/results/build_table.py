"""Team results table (#16): results/registry.csv -> results/results_table.md.

The registry holds one row per number, with where it comes from (script, output file,
commit, data version, checksum) and what it is computed over. The readable table is
generated from it and is never edited by hand, so the two cannot drift apart. The
registry format was announced on the board (#1); the provenance checker that opens
each output file is part C3 of #120 and lives elsewhere.

Usage (from the repo root):
    python src/results/build_table.py          # rewrite results/results_table.md
    python src/results/build_table.py --check  # exit 1 if the table is out of date

Input:  results/registry.csv
Output: results/results_table.md
"""

from __future__ import annotations

import argparse
import csv
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "results" / "registry.csv"
TABLE = ROOT / "results" / "results_table.md"

COLUMNS = [
    "id", "piece", "owner", "result", "value", "unit", "interval", "population", "setting",
    "kind", "negative", "script", "output", "field", "commit", "data_version", "sha256",
    "confirmed", "reported_in",
]
KINDS = ("observation", "model", "simulation", "check")
YES_NO = ("yes", "no")
PENDING = "pending"
SCRIPT_DIRS = ("src/", "api/")      # where the code that writes an output lives
OUTPUT_DIRS = ("data/", "paper/")   # outputs stay out of git under data/; figures and their JSON in paper/

# Order of the pieces in the table: data and learned cost, the planner and its
# baselines, tours, then the learned layers, radio, contingencies and the product.
# A piece that is not listed goes at the end, in alphabetical order.
PIECE_ORDER = [
    "E2", "E1", "E3", "E4", "Baselines", "E5", "E6", "P6", "E8", "E9", "X1", "E11", "X2",
    "C1", "E12", "P1", "P3",
]

# Pieces that are expected but whose rows arrive later. The note disappears from the
# table as soon as the piece has a row in the registry.
EXPECTED_LATER = {
    "E12": "the dose on the E5 tours arrives from #144. The numbers on Curiosity's "
           "out-and-back route (provisional) are left out on purpose.",
}

# Pieces that will not have a row, and why.
NOT_RUN = {
    "E7": "the route on a perturbed DEM was not run: it was the fallback if E9 was cut, "
          "and E9 worked (#15 closed). The DEM-error study is now part C4 of #120.",
}

HEX = re.compile(r"^[0-9a-f]+$")


def load(path: Path = REGISTRY) -> list[dict[str, str]]:
    """Read the registry; one dict per row, keys in COLUMNS order."""
    with open(path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"{path.name}: header must be exactly {','.join(COLUMNS)}")
        return [dict(row) for row in reader]


def validate(rows: list[dict[str, str]]) -> list[str]:
    """Return a list of problems (empty if the registry is valid)."""
    problems: list[str] = []
    seen: set[str] = set()
    for n, row in enumerate(rows, start=2):  # line 1 is the header
        where = f"line {n} ({row.get('id') or 'no id'})"
        if None in row or any(v is None for v in row.values()):
            problems.append(f"{where}: wrong number of fields")
            continue
        for col in COLUMNS:
            if not row[col].strip():
                problems.append(f"{where}: empty {col}")
        if row["id"] in seen:
            problems.append(f"{where}: duplicate id")
        seen.add(row["id"])
        if row["kind"] not in KINDS:
            problems.append(f"{where}: kind must be one of {', '.join(KINDS)}")
        for col in ("negative", "confirmed"):
            if row[col] not in YES_NO:
                problems.append(f"{where}: {col} must be yes or no")
        commit = row["commit"]
        if commit != PENDING and not (HEX.match(commit) and len(commit) >= 7):
            problems.append(f"{where}: commit must be a short hash (7+ hex characters) or '{PENDING}'")
        sha = row["sha256"]
        if sha != PENDING and not (HEX.match(sha) and len(sha) == 12):
            problems.append(f"{where}: sha256 must be 12 hex characters or '{PENDING}'")
        if not row["script"].startswith(SCRIPT_DIRS):
            problems.append(f"{where}: script must start with one of {', '.join(SCRIPT_DIRS)}")
        if row["output"] != PENDING and not row["output"].startswith(OUTPUT_DIRS):
            problems.append(f"{where}: output must start with one of {', '.join(OUTPUT_DIRS)} or be '{PENDING}'")
        if row["piece"] in NOT_RUN:
            problems.append(f"{where}: {row['piece']} was not run (see NOT_RUN)")
    return problems


def _piece_key(piece: str) -> tuple[int, str]:
    if piece in PIECE_ORDER:
        return (PIECE_ORDER.index(piece), "")
    return (len(PIECE_ORDER), piece)


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ").strip()


def _value(row: dict[str, str]) -> str:
    value = f"{row['value']} {row['unit']}"
    if row["interval"] != "none":
        value += f" ({row['interval']})"
    return value


def _kind(row: dict[str, str]) -> str:
    return row["kind"] + (", **negative**" if row["negative"] == "yes" else "")


def _source(row: dict[str, str]) -> str:
    commit = "commit pending" if row["commit"] == PENDING else row["commit"]
    return f"`{row['script']}` → `{row['output']}` @ {commit}"


def render(rows: list[dict[str, str]]) -> str:
    """The Markdown table, grouped by piece in PIECE_ORDER and kept in registry order inside a piece."""
    ordered = sorted(enumerate(rows), key=lambda item: (_piece_key(item[1]["piece"]), item[0]))
    pieces = {row["piece"] for row in rows}
    owners = sorted({row["owner"] for row in rows})

    out = [
        "# Team results table",
        "",
        "<!-- Generated by src/results/build_table.py from results/registry.csv. Do not edit by hand. -->",
        "",
        f"{len(rows)} numbers from {len(pieces)} pieces. Each row comes from one line of "
        "[`registry.csv`](registry.csv), which also keeps the output field, the input data "
        "version and the checksum. How to add or correct a row: [README](README.md).",
        "",
        "**Kind:** *observation* is measured on real data; *model* is our model applied to the "
        "real terrain or data; *simulation* uses synthetic or random scenarios; *check* validates "
        "a method or a tool. Values marked *assumed* in the setting have no source.",
        "",
        "| Piece | Result | Value | Over what | Setting | Kind | Source | Owner confirmed |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for _, row in ordered:
        cells = [
            f"{row['piece']} ({row['owner']})", row["result"], _value(row), row["population"],
            row["setting"], _kind(row), _source(row), row["confirmed"],
        ]
        out.append("| " + " | ".join(_cell(c) for c in cells) + " |")

    out += ["", "## Not in the table", ""]
    for piece, why in NOT_RUN.items():
        out.append(f"- **{piece}:** {why}")
    for piece, why in EXPECTED_LATER.items():
        if piece not in pieces:
            out.append(f"- **{piece} (pending):** {why}")

    negatives = [row for _, row in ordered if row["negative"] == "yes"]
    if negatives:
        out += ["", "## Negative results", "",
                "Kept on purpose: they go to the Discussion and are as valuable as the positive ones.", ""]
        out += [f"- **{row['piece']}:** {_cell(row['result'])}: {_cell(_value(row))}." for row in negatives]

    out += ["", "## Provenance still pending", "",
            "Fields that the owner still has to give (`pending` in the registry). Part C3 of #120 "
            "checks the rest against the output files.", "",
            "| Owner | Rows | Not confirmed | No commit in main | No output file | No checksum | No data version "
            "| No output field |",
            "|---|---|---|---|---|---|---|---|"]
    for owner in owners:
        mine = [row for row in rows if row["owner"] == owner]
        counts = [len(mine), sum(r["confirmed"] == "no" for r in mine)]
        counts += [sum(PENDING in r[col].split("; ") for r in mine)
                   for col in ("commit", "output", "sha256", "data_version", "field")]
        out.append(f"| {owner} | " + " | ".join(str(c) for c in counts) + " |")
    return "\n".join(out) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--check", action="store_true", help="only check that the table is up to date")
    args = parser.parse_args(argv)

    rows = load()
    problems = validate(rows)
    if problems:
        print("registry.csv has problems:", *problems, sep="\n  ", file=sys.stderr)
        return 1
    text = render(rows)
    if args.check:
        current = TABLE.read_text(encoding="utf-8") if TABLE.exists() else ""
        if current != text:
            print("results_table.md is out of date: run python src/results/build_table.py", file=sys.stderr)
            return 1
        print(f"results_table.md is up to date ({len(rows)} rows)")
        return 0
    TABLE.write_text(text, encoding="utf-8", newline="\n")
    print(f"wrote {TABLE.relative_to(ROOT)} ({len(rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
