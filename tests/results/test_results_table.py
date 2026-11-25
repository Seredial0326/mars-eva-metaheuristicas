"""Tests for the team results table (#16): the registry is valid and the table is up to date.

No data files needed: the checks read only results/registry.csv and results/results_table.md.
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src" / "results"))

import build_table  # noqa: E402


def _row(**overrides):
    row = {
        "id": "e0-example", "piece": "E0", "owner": "Juan", "result": "An example number",
        "value": "1.5", "unit": "Wh", "interval": "none", "population": "10 cells",
        "setting": "none", "kind": "model", "negative": "no", "script": "src/x.py",
        "output": "data/x.json", "field": "pending", "commit": "abcdef1",
        "data_version": "pending", "sha256": "pending", "confirmed": "no", "reported_in": "#16",
    }
    row.update(overrides)
    return row


def _write(path, rows):
    with open(path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=build_table.COLUMNS, lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


# --- the committed files ----------------------------------------------------

def test_registry_is_valid():
    rows = build_table.load()
    assert rows, "registry.csv has no rows"
    assert build_table.validate(rows) == []


def test_table_is_up_to_date_with_the_registry():
    expected = build_table.render(build_table.load())
    current = build_table.TABLE.read_text(encoding="utf-8")
    assert current == expected, "run: python src/results/build_table.py"


def test_table_rows_have_no_empty_cells():
    rows = build_table.load()
    lines = [line for line in build_table.TABLE.read_text(encoding="utf-8").splitlines()
             if line.startswith("| ") and "(" in line.split("|")[1]]
    assert len(lines) == len(rows)
    for line in lines:
        cells = [c.strip() for c in line.strip().strip("|").split(" | ")]
        assert len(cells) == 8, line
        assert all(cells), line


def test_most_rows_name_their_output_file():
    rows = build_table.load()
    named = [row for row in rows if row["output"] != build_table.PENDING]
    assert len(named) >= 0.9 * len(rows)


# --- the checks themselves ----------------------------------------------------

def test_validate_flags_empty_cells_and_duplicates():
    problems = build_table.validate([_row(), _row(unit=" ")])
    assert any("empty unit" in p for p in problems)
    assert any("duplicate id" in p for p in problems)


@pytest.mark.parametrize("column, bad", [
    ("kind", "guess"), ("negative", "maybe"), ("confirmed", "Yes"),
    ("commit", "abc"), ("commit", "ABCDEF1"), ("sha256", "abc"), ("piece", "E7"),
    ("script", "tests/x.test.mjs"), ("output", "PR #82"),
])
def test_validate_flags_bad_values(column, bad):
    assert build_table.validate([_row(**{column: bad})])


def test_validate_accepts_a_good_row():
    rows = [_row(), _row(id="e0-other", sha256="0123456789ab"),
            _row(id="e0-api", script="api/planner.py (/plan)", output="pending"),
            _row(id="e0-unmerged", commit="pending")]
    assert build_table.validate(rows) == []
    assert "@ commit pending" in build_table.render(rows)


def test_load_rejects_a_wrong_header(tmp_path):
    path = tmp_path / "registry.csv"
    path.write_text("id,piece\nx,E0\n", encoding="utf-8")
    with pytest.raises(ValueError):
        build_table.load(path)


def test_load_and_render_a_small_registry(tmp_path):
    path = tmp_path / "registry.csv"
    _write(path, [_row(), _row(id="e0-neg", negative="yes", interval="95% CI 1–2", sha256="0123456789ab")])
    rows = build_table.load(path)
    text = build_table.render(rows)
    assert "| E0 (Juan) | An example number | 1.5 Wh |" in text
    assert "1.5 Wh (95% CI 1–2)" in text
    assert "## Negative results" in text
    assert "| Juan | 2 | 2 | 0 | 0 | 1 | 2 | 2 |" in text


def test_pieces_follow_the_order_and_pending_notes_disappear():
    rows = [_row(id="p3-a", piece="P3"), _row(id="e2-a", piece="E2"), _row(id="zz-a", piece="ZZ")]
    text = build_table.render(rows)
    assert text.index("| E2 (") < text.index("| P3 (") < text.index("| ZZ (")
    assert "**E12 (pending):**" in text
    assert "**E7:**" in text
    text = build_table.render(rows + [_row(id="e12-a", piece="E12")])
    assert "**E12 (pending):**" not in text


def test_pipes_in_cells_are_escaped():
    text = build_table.render([_row(result="a | b")])
    assert "a \\| b" in text
