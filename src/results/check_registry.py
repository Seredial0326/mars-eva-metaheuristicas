"""Check the team results registry against the files that produced it (C3, #120).

The registry (`results/registry.csv`, format owned by Juan, #16) has one row per
reported figure. This script runs on each owner's machine, where the output
files exist (data/ stays out of git), and checks three things:

1. The output file exists and its sha256 starts with the registered 12 hex digits.
2. The value read from the file at `field` equals `value` at the precision the
   registry prints (0.5 in the last printed digit).
3. Documents that cite a row by tag, `4.7 %<!-- r:x2-adaptive-ruin -->`, print
   the same number right before the tag. Untagged mentions are only reported.

`field` locators (anything after a space and `*` scales the number, e.g. `rate *100`):
    JSON   a.b[0].c            dotted keys, [n] list indexes, ["key.with.dots"]
    JSONL  [3].a.b             line index, then a JSON path
    CSV    column@key=value    first row whose `key` column equals `value`
           column@3            row index (0-based, header excluded)
    text   re:<regex>          first capture group of the first match
    any    pending             not checked yet

Usage:
    python src/results/check_registry.py                    # every row whose file is here
    python src/results/check_registry.py --owner Sebas      # only my rows; missing files fail
    python src/results/check_registry.py --json report.json
Exit code 1 when any check fails.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import re
import subprocess
import sys
from dataclasses import dataclass, field as dc_field
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
REGISTRY = ROOT / "results" / "registry.csv"
DOCS = ("README.md", "docs/demo.md", "paper/notes/*.md", "paper/sections/*.md")
COLUMNS = ("id", "piece", "owner", "result", "value", "unit", "interval", "population",
           "setting", "kind", "negative", "script", "output", "field", "commit",
           "data_version", "sha256", "confirmed", "reported_in")
KINDS = {"observation", "model", "simulation", "check"}
TAG = re.compile(r"<!--\s*r:([A-Za-z0-9_.-]+)\s*-->")
# A number as people write it: optional sign (not the dash of a range like 2.06–6.45),
# thousands commas, point or comma decimal.
NUMBER = re.compile(r"(?<![\d.,])[-−]?\d+(?:,\d{3})*(?:[.,]\d+)?")


@dataclass
class Finding:
    row: str
    level: str          # "error", "warning" or "info"
    check: str
    message: str


@dataclass
class Report:
    findings: list[Finding] = dc_field(default_factory=list)
    checked: list[str] = dc_field(default_factory=list)
    skipped: list[str] = dc_field(default_factory=list)

    def add(self, row, level, check, message):
        self.findings.append(Finding(row, level, check, message))

    @property
    def errors(self):
        return [f for f in self.findings if f.level == "error"]


# ---------- numbers ----------

def parse_number(text):
    """Registry or document number -> float, or None if it is not a number."""
    t = str(text).strip().replace("−", "-").replace(" ", "").replace(" ", "")
    if re.fullmatch(r"-?\d{1,3}(,\d{3})+(\.\d+)?", t):
        t = t.replace(",", "")
    elif re.fullmatch(r"-?\d+,\d+", t):
        t = t.replace(",", ".")       # decimal comma (Spanish docs)
    try:
        v = float(t)
    except ValueError:
        return None
    return v if math.isfinite(v) else None


def decimals(text):
    t = str(text).strip()
    m = re.search(r"[.,](\d+)$", t)
    if m and not re.fullmatch(r"-?\d{1,3}(,\d{3})+", t):
        return len(m.group(1))
    return 0


def same_value(registered, found):
    """True when `found` rounds to the registry's printed value."""
    reg = parse_number(registered)
    if reg is None:
        return str(registered).strip().lower() == str(found).strip().lower()
    if isinstance(found, bool) or found is None:
        return False
    try:
        got = float(found)
    except (TypeError, ValueError):
        got = parse_number(found)
    if got is None or not math.isfinite(got):
        return False
    tol = 0.5 * 10 ** -decimals(registered) + 1e-9 * max(1.0, abs(reg))
    return abs(got - reg) <= tol


# ---------- locating a value in a file ----------

_PATH_TOKEN = re.compile(r'\["((?:[^"\\]|\\.)*)"\]|\[(-?\d+)\]|([^.\[\]]+)')


def walk(obj, path):
    """Follow a dotted path with [n] indexes and ["quoted.keys"]."""
    pos = 0
    path = path.strip()
    while pos < len(path):
        if path[pos] == ".":
            pos += 1
            continue
        m = _PATH_TOKEN.match(path, pos)
        if not m:
            raise KeyError(f"cannot parse path at {path[pos:]!r}")
        quoted, index, key = m.groups()
        if index is not None:
            if not isinstance(obj, list):
                raise KeyError(f"[{index}] on a non-list")
            obj = obj[int(index)]
        else:
            k = quoted if quoted is not None else key
            if not isinstance(obj, dict) or k not in obj:
                raise KeyError(f"no key {k!r}")
            obj = obj[k]
        pos = m.end()
    return obj


def split_scale(locator):
    m = re.match(r"^(.*?)\s+\*\s*([-+0-9.eE]+)\s*$", locator)
    if m:
        return m.group(1), float(m.group(2))
    return locator, 1.0


def read_field(path: Path, locator: str):
    locator, scale = split_scale(locator.strip())
    suffix = path.suffix.lower()
    if locator.startswith("re:"):
        m = re.search(locator[3:], path.read_text(encoding="utf-8"), re.MULTILINE)
        if not m:
            raise KeyError("regex did not match")
        value = m.group(1) if m.groups() else m.group(0)
    elif suffix == ".json":
        value = walk(json.loads(path.read_text(encoding="utf-8")), locator)
    elif suffix == ".jsonl":
        m = re.match(r"^\[(\d+)\]\.?(.*)$", locator)
        if not m:
            raise KeyError("JSONL locator starts with [line]")
        with path.open(encoding="utf-8") as stream:
            for i, line in enumerate(stream):
                if i == int(m.group(1)):
                    value = walk(json.loads(line), m.group(2))
                    break
            else:
                raise KeyError(f"no line {m.group(1)}")
    elif suffix in (".csv", ".tsv"):
        m = re.match(r"^([^@]+)@(?:(\d+)|([^=]+)=(.*))$", locator)
        if not m:
            raise KeyError("CSV locator is column@row or column@key=value")
        column, index, key, wanted = m.groups()
        with path.open(encoding="utf-8", newline="") as stream:
            rows = list(csv.DictReader(stream, delimiter="\t" if suffix == ".tsv" else ","))
        if index is not None:
            row = rows[int(index)]
        else:
            row = next((r for r in rows if str(r.get(key, "")).strip() == wanted.strip()), None)
            if row is None:
                raise KeyError(f"no row with {key}={wanted}")
        if column not in row:
            raise KeyError(f"no column {column!r}")
        value = row[column]
    else:
        raise KeyError(f"no locator rule for {suffix or 'files without extension'}; use re:")
    if scale != 1.0:
        number = value if isinstance(value, (int, float)) and not isinstance(value, bool) \
            else parse_number(value)
        if number is None:
            raise KeyError(f"cannot scale non-number {value!r}")
        value = number * scale
    return value


def sha12(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()[:12]


# ---------- registry ----------

def load_registry(path: Path, report: Report):
    with path.open(encoding="utf-8-sig", newline="") as stream:
        reader = csv.DictReader(stream)
        missing = [c for c in COLUMNS if c not in (reader.fieldnames or [])]
        if missing:
            report.add("(registry)", "error", "schema", f"missing columns: {', '.join(missing)}")
            return []
        rows = list(reader)
    seen = set()
    for n, row in enumerate(rows, start=2):
        rid = (row.get("id") or "").strip() or f"line {n}"
        if rid in seen:
            report.add(rid, "error", "schema", "duplicate id")
        seen.add(rid)
        empty = [c for c in COLUMNS if not (row.get(c) or "").strip()]
        if empty:
            report.add(rid, "error", "schema", f"empty cells: {', '.join(empty)}")
        if (row.get("kind") or "").strip() not in KINDS:
            report.add(rid, "error", "schema", f"kind must be one of {sorted(KINDS)}")
        if (row.get("negative") or "").strip() not in ("yes", "no"):
            report.add(rid, "error", "schema", "negative must be yes or no")
        sha = (row.get("sha256") or "").strip()
        if sha != "pending" and not re.fullmatch(r"[0-9a-f]{12}", sha):
            report.add(rid, "error", "schema", "sha256 is 12 lowercase hex digits or pending")
    return rows


def owner_matches(row, owners):
    if not owners:
        return False
    names = {o.strip().lstrip("@").lower() for o in owners}
    return any(part.strip().lstrip("@").lower() in names
               for part in re.split(r"[;/,]", row.get("owner", "")))


def commit_known(commit, root):
    if commit == "pending":
        return True
    try:
        out = subprocess.run(["git", "cat-file", "-e", commit + "^{commit}"], cwd=root,
                             capture_output=True, timeout=20)
    except (OSError, subprocess.TimeoutExpired):
        return True     # no git here: do not report a false problem
    return out.returncode == 0


def check_rows(rows, root: Path, owners, report: Report):
    for row in rows:
        rid = row["id"].strip()
        mine = owner_matches(row, owners)
        out = (row.get("output") or "").strip()
        if not out or any(ch in out for ch in "*?;"):
            report.add(rid, "error", "output", "output must name exactly one file")
            continue
        path = (root / out) if not Path(out).is_absolute() else Path(out)
        if owners and not mine:
            report.skipped.append(rid)
            continue
        if not path.is_file():
            if mine:
                report.add(rid, "error", "output", f"{out} not found on the owner's machine")
            else:
                report.skipped.append(rid)
            continue
        report.checked.append(rid)
        sha = row["sha256"].strip()
        if sha == "pending":
            report.add(rid, "info", "sha256", f"pending; this file is {sha12(path)}")
        elif sha12(path) != sha:
            report.add(rid, "error", "sha256",
                       f"{out} is {sha12(path)}, registry says {sha} (file regenerated?)")
        loc = row["field"].strip()
        if loc == "pending":
            report.add(rid, "info", "value", "field pending; value not checked")
        else:
            try:
                found = read_field(path, loc)
            except (KeyError, IndexError, ValueError, re.error) as exc:
                report.add(rid, "error", "value", f"cannot read {loc!r}: {exc}")
            else:
                if not same_value(row["value"], found):
                    report.add(rid, "error", "value",
                               f"registry {row['value']} {row['unit']}, file gives {found!r}")
        if not commit_known(row["commit"].strip(), root):
            report.add(rid, "warning", "commit", f"commit {row['commit']} not in this clone")


# ---------- documents ----------

def doc_files(root: Path, patterns=DOCS):
    files = []
    for pattern in patterns:
        files.extend(sorted(root.glob(pattern)))
    return [f for f in files if f.is_file() and not f.name.startswith("_")]


def number_before(text):
    """Last number in `text`, ignoring markdown emphasis and a trailing unit."""
    cleaned = re.sub(r"[*_`]", "", text)
    numbers = NUMBER.findall(cleaned)
    return numbers[-1] if numbers else None


def check_docs(rows, root: Path, report: Report, patterns=DOCS):
    by_id = {r["id"].strip(): r for r in rows}
    tagged = set()
    for doc in doc_files(root, patterns):
        rel = doc.relative_to(root).as_posix()
        fenced = False
        for lineno, line in enumerate(doc.read_text(encoding="utf-8").splitlines(), start=1):
            if line.lstrip().startswith(("```", "~~~")):
                fenced = not fenced
                continue
            if fenced:
                continue
            # A tag shown as an example in `code` is not a citation.
            line = re.sub(r"`[^`]*`", lambda m: " " * len(m.group(0)), line)
            for m in TAG.finditer(line):
                rid = m.group(1)
                where = f"{rel}:{lineno}"
                if rid not in by_id:
                    report.add(rid, "error", "doc", f"{where} cites an id that is not in the registry")
                    continue
                tagged.add(rid)
                before = line[:m.start()]
                before = TAG.sub("", before)
                shown = number_before(before[-80:])
                if shown is None:
                    report.add(rid, "error", "doc", f"{where} has the tag but no number before it")
                elif not same_value(by_id[rid]["value"], shown) or (
                        decimals(shown) != decimals(by_id[rid]["value"])
                        and parse_number(by_id[rid]["value"]) is not None):
                    report.add(rid, "error", "doc",
                               f"{where} prints {shown}, registry says {by_id[rid]['value']}")
    for rid in by_id:
        if rid not in tagged:
            report.add(rid, "info", "doc", "no tagged citation in README, demo or notes")
    return tagged


# ---------- CLI ----------

def run(registry: Path, root: Path, owners=(), patterns=DOCS):
    report = Report()
    if not registry.is_file():
        report.add("(registry)", "error", "schema", f"{registry} not found")
        return report
    rows = load_registry(registry, report)
    check_rows(rows, root, owners, report)
    check_docs(rows, root, report, patterns)
    return report


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--registry", type=Path, default=REGISTRY)
    parser.add_argument("--root", type=Path, default=ROOT,
                        help="repository root that output paths are relative to")
    parser.add_argument("--owner", action="append", default=[],
                        help="check only this owner's rows; their files must exist (repeatable)")
    parser.add_argument("--json", type=Path, help="also write the report as JSON")
    parser.add_argument("--quiet", action="store_true", help="hide info lines")
    args = parser.parse_args(argv)
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="replace")    # Windows consoles without UTF-8

    report = run(args.registry, args.root, args.owner)
    for f in report.findings:
        if args.quiet and f.level == "info":
            continue
        print(f"{f.level.upper():7} {f.row:28} {f.check:7} {f.message}")
    print(f"\n{len(report.checked)} rows checked against their files, "
          f"{len(report.skipped)} skipped (file not on this machine or another owner), "
          f"{len(report.errors)} errors.")
    if args.json:
        args.json.write_text(json.dumps({
            "checked": report.checked, "skipped": report.skipped,
            "findings": [f.__dict__ for f in report.findings]}, indent=2), encoding="utf-8")
    return 1 if report.errors else 0


if __name__ == "__main__":
    sys.exit(main())
