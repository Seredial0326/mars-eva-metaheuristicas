"""C3 (#120): registry checker and intervals (src/results/check_registry.py, intervals.py)."""

import csv
import hashlib
import json
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from results import check_registry as cr  # noqa: E402
from results import intervals as iv  # noqa: E402


def sha12(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()[:12]


def row(**over):
    base = {c: "x" for c in cr.COLUMNS}
    base.update(id="x2-ruin", piece="X2", owner="JB", result="share out of O2",
                value="4.7", unit="%", interval="none", population="1000 walks",
                setting="k_true 1.5", kind="simulation", negative="no",
                script="python src/fisica/adaptive_sim.py", output="data/x2/summary.json",
                field="adaptive.ruin *100", commit="pending", data_version="pending",
                sha256="pending", confirmed="yes", reported_in="#101")
    base.update(over)
    return base


def write_registry(root, rows):
    path = root / "results" / "registry.csv"
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(stream, fieldnames=cr.COLUMNS)
        writer.writeheader()
        writer.writerows(rows)
    return path


@pytest.fixture
def repo(tmp_path):
    out = tmp_path / "data" / "x2"
    out.mkdir(parents=True)
    (out / "summary.json").write_text(json.dumps(
        {"adaptive": {"ruin": 0.04712, "ci": [0.035, 0.062]}, "a.b": 3}), encoding="utf-8")
    (out / "table.csv").write_text("policy,ruin\nfixed,0.90\nadaptive,0.047\n", encoding="utf-8")
    (out / "walks.jsonl").write_text('{"w": 1}\n{"w": 2}\n', encoding="utf-8")
    (out / "table.md").write_text("Ruin: **4.7 %**\n", encoding="utf-8")
    (tmp_path / "paper" / "notes").mkdir(parents=True)
    return tmp_path


def messages(report, level="error"):
    return [(f.row, f.check, f.message) for f in report.findings if f.level == level]


# ---------- numbers ----------

@pytest.mark.parametrize("text,value", [
    ("4.7", 4.7), ("−57.0", -57.0), ("1,234", 1234.0), ("4,7", 4.7), ("300", 300.0),
    ("1,234.5", 1234.5), ("abc", None), ("nan", None)])
def test_parse_number(text, value):
    assert cr.parse_number(text) == value


def test_same_value_uses_printed_precision():
    assert cr.same_value("4.7", 4.712)
    assert cr.same_value("4.7", 4.65)
    assert not cr.same_value("4.7", 4.76)
    assert cr.same_value("300", 300)
    assert not cr.same_value("300", 301)
    assert cr.same_value("yes", "Yes")
    assert not cr.same_value("4.7", True)
    assert not cr.same_value("4.7", None)


def test_number_before_ignores_range_dash_and_markdown():
    assert cr.number_before("95% Wilson 2.06–6.45") == "6.45"
    assert cr.number_before("difference **−57.0** percentage points") == "−57.0"
    assert cr.number_before("no number") is None


# ---------- locators ----------

def test_read_field_formats(repo):
    d = repo / "data" / "x2"
    assert cr.read_field(d / "summary.json", "adaptive.ruin") == 0.04712
    assert cr.read_field(d / "summary.json", "adaptive.ci[1]") == 0.062
    assert cr.read_field(d / "summary.json", '["a.b"]') == 3
    assert cr.read_field(d / "summary.json", "adaptive.ruin *100") == pytest.approx(4.712)
    assert cr.read_field(d / "table.csv", "ruin@policy=adaptive") == "0.047"
    assert cr.read_field(d / "table.csv", "ruin@0") == "0.90"
    assert cr.read_field(d / "table.csv", "ruin@policy=adaptive *100") == pytest.approx(4.7)
    assert cr.read_field(d / "walks.jsonl", "[1].w") == 2
    assert cr.read_field(d / "table.md", r"re:Ruin: \*\*([\d.]+)") == "4.7"
    with pytest.raises(KeyError):
        cr.read_field(d / "summary.json", "adaptive.missing")
    with pytest.raises(KeyError):
        cr.read_field(d / "table.csv", "ruin@policy=none")


# ---------- rows ----------

def test_matching_row_passes(repo):
    path = repo / "data" / "x2" / "summary.json"
    write_registry(repo, [row(sha256=sha12(path))])
    report = cr.run(repo / "results" / "registry.csv", repo, owners=["JB"])
    assert messages(report) == []
    assert report.checked == ["x2-ruin"]


def test_value_and_checksum_mismatch_fail(repo):
    write_registry(repo, [row(value="5.1", sha256="0123456789ab")])
    report = cr.run(repo / "results" / "registry.csv", repo)
    checks = {c for _, c, _ in messages(report)}
    assert checks == {"value", "sha256"}


def test_missing_file_fails_only_for_the_owner(repo):
    write_registry(repo, [row(output="data/x2/gone.json")])
    assert cr.run(repo / "results" / "registry.csv", repo).errors == []
    mine = cr.run(repo / "results" / "registry.csv", repo, owners=["@jb"])
    assert [c for _, c, _ in messages(mine)] == ["output"]
    other = cr.run(repo / "results" / "registry.csv", repo, owners=["Sebas"])
    assert other.errors == [] and other.skipped == ["x2-ruin"]


def test_pending_cells_are_reported_not_failed(repo):
    write_registry(repo, [row(field="pending")])
    report = cr.run(repo / "results" / "registry.csv", repo)
    assert report.errors == []
    infos = {c for _, c, _ in messages(report, "info")}
    assert {"sha256", "value"} <= infos


def test_schema_errors(repo):
    path = write_registry(repo, [row(), row(kind="guess", negative="maybe", sha256="XYZ", unit="")])
    report = cr.run(path, repo)
    text = " ".join(m for _, _, m in messages(report))
    for part in ("duplicate id", "empty cells: unit", "kind must be", "negative must be",
                 "sha256 is 12"):
        assert part in text
    bad = repo / "results" / "short.csv"
    bad.write_text("id,value\na,1\n", encoding="utf-8")
    assert "missing columns" in cr.run(bad, repo).errors[0].message


def test_output_must_be_one_file(repo):
    write_registry(repo, [row(output="data/x2/*/summary.json")])
    assert [c for _, c, _ in messages(cr.run(repo / "results" / "registry.csv", repo))] == ["output"]


# ---------- documents ----------

def test_doc_tags(repo):
    note = repo / "paper" / "notes" / "X2.md"
    note.write_text(
        "Adaptive runs out in **4.7 %**<!-- r:x2-ruin --> of walks.\n"
        "Old figure: 5.2 %<!-- r:x2-ruin -->\n"
        "Spanish: 4,7 %<!-- r:x2-ruin -->\n"
        "Too precise: 4.70 %<!-- r:x2-ruin -->\n"
        "Unknown: 3 <!-- r:nope -->\n"
        "Bare tag <!-- r:x2-ruin -->\n"
        "Example in code: `9 %<!-- r:other -->`\n"
        "```\n8 <!-- r:other -->\n```\n", encoding="utf-8")
    (repo / "paper" / "notes" / "_template.md").write_text("9 <!-- r:x2-ruin -->", encoding="utf-8")
    write_registry(repo, [row()])
    report = cr.run(repo / "results" / "registry.csv", repo)
    docs = [m for _, c, m in messages(report) if c == "doc"]
    assert len(docs) == 4
    assert any("X2.md:2 prints 5.2" in m for m in docs)
    assert any("X2.md:4 prints 4.70" in m for m in docs)
    assert any("not in the registry" in m for m in docs)
    assert any("no number before it" in m for m in docs)


def test_untagged_rows_are_info(repo):
    write_registry(repo, [row()])
    report = cr.run(repo / "results" / "registry.csv", repo)
    assert ("x2-ruin", "doc", "no tagged citation in README, demo or notes") in messages(report, "info")


def test_cli_exit_code_and_json(repo, capsys):
    write_registry(repo, [row(value="9.9")])
    out = repo / "report.json"
    code = cr.main(["--registry", str(repo / "results" / "registry.csv"),
                    "--root", str(repo), "--json", str(out), "--quiet"])
    assert code == 1
    findings = json.loads(out.read_text(encoding="utf-8"))["findings"]
    assert [f["check"] for f in findings if f["level"] == "error"] == ["value"]
    assert "INFO" not in capsys.readouterr().out


# ---------- intervals ----------

def test_wilson_matches_c1_and_edges():
    lo, hi = iv.wilson(11, 300)
    assert 0.018 < lo < 0.022 and 0.063 < hi < 0.066
    lo0, hi0 = iv.wilson(0, 300)
    assert lo0 == 0.0 and 0 < hi0 < 0.02
    assert iv.wilson(300, 300)[1] == 1.0
    with pytest.raises(ValueError):
        iv.wilson(5, 3)


def test_block_bootstrap_resamples_blocks():
    rng = np.random.default_rng(1)
    blocks = np.repeat(np.arange(10), 50)
    shift = rng.normal(0, 1, 10)[blocks]          # strong block effect
    values = shift + rng.normal(0, 0.1, blocks.size)
    lo, hi = iv.block_bootstrap(values, blocks, seed=2)
    naive = 1.96 * values.std() / np.sqrt(values.size)
    assert hi - lo > 4 * naive                    # pixels are not independent samples
    with pytest.raises(ValueError):
        iv.block_bootstrap(values[:100], blocks[:100])


def test_paired_bootstrap_and_text():
    a = np.array([1, 0, 1, 1, 0, 1, 1, 1], dtype=float)
    lo, hi = iv.paired_bootstrap(a, a)
    assert lo == hi == 0.0                        # no discordance: degenerate
    assert iv.registry_text(0.0206, 0.0645, "Wilson", scale=100) == "95% Wilson 2.06–6.45"
