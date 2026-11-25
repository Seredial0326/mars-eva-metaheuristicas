# C3 · Checking the results registry against its outputs

Owner: Sebas (`@Seredial0326`) for the checker and intervals; Juan (`@JuanCorredor2023`) owns the registry rows, `build_table.py` and the table (#16) · Issue: #120 (C3), #16 · PRs: pending · Status: in progress · Last update: 2026-11-15

## Question
Does every figure the team reports still match the file that produced it, and do the README, the demo script and the notes print the same figure?

## Data
- `results/registry.csv`, one row per reported figure. The format is Juan's (#16, board post 2026-11-15): `id`, `piece`, `owner`, `result`, `value`, `unit`, `interval`, `population`, `setting`, `kind`, `negative`, `script`, `output`, `field`, `commit`, `data_version`, `sha256`, `confirmed`, `reported_in`.
- The output files named in `output`. They live under `data/` and stay out of git, so each owner checks their own rows on their machine.
- Documents: `README.md`, `docs/demo.md`, `paper/notes/*.md` and `paper/sections/*.md`. `_template.md` is skipped.

## Method
`src/results/check_registry.py` runs three checks per row.

1. **File.** The output exists and the first 12 hex digits of its SHA-256 equal `sha256`. A mismatch means the file was regenerated after the row was written. With `--owner`, a missing file is an error for that owner's rows. Without it, rows whose file is not on this machine are skipped and listed, not failed.
2. **Value.** The checker reads the number at `field` and compares it with `value` at the precision the registry prints: it must be within half of the last printed digit. For example, 4.7 accepts 4.65 to 4.75. A trailing ` *100` scales the number first, for fractions reported as percent. Locators:
   - JSON: `a.b[0]`, with `["key.with.dots"]` for keys that contain dots;
   - JSONL: `[line].path`;
   - CSV: `column@key=value` or `column@row`;
   - text: `re:` plus a regex with one group.
3. **Documents.** A document cites a row with an HTML comment right after the number, `4.7 %<!-- r:x2-adaptive-ruin -->`. The comment is invisible when rendered. The number just before the tag must match the registry, with the same number of decimals; decimal commas and thousands separators are accepted. An unknown id or a tag with no number before it is an error. Untagged rows are listed as information only. Guessing which untagged sentence states which result would flag too much noise.

Cells marked `pending` (`field`, `sha256`, `commit`, `data_version`) are reported as information, never as passes. Schema checks cover:
- the columns exist and no cell is empty;
- ids are unique;
- `kind` ∈ {observation, model, simulation, check} and `negative` ∈ {yes, no};
- `sha256` is 12 hex digits or `pending`.

The exit code is 1 when any error is found, so the checker can run before a commit or in CI on a machine that has the data.

`src/results/intervals.py` gives the `interval` cell only where the population is well defined. Each function names the unit it counts or resamples:
- `wilson(k, n)` for rates over independent trials (EVA worlds, simulated walks). It stays informative at 0 or n failures.
- `block_bootstrap(values, blocks)` resamples whole spatial blocks, sols or segments, never single pixels or vertices. It refuses fewer than 5 blocks.
- `paired_bootstrap(a, b)` for two policies on the same worlds. It is degenerate (zero width) when there is no discordance, and this is reported, not hidden.
- `registry_text` writes the cell in the registry's form, e.g. `95% Wilson 2.06–6.45`.

## Results
- Tests: 23 pass, including tags shown as examples in `code` or fenced blocks, which are not citations (`python -m pytest tests/results/test_check_registry.py`). They cover each locator, rounding at the printed precision, checksum and value mismatches, owner and missing-file rules, schema errors, document tags (wrong, over-precise, unknown and bare tags, decimal comma), the CLI exit code and the intervals.
- Smoke test on real output: a two-row registry for C1 (`data/robustness/c1-real/summary.json` from `src/fisica/eva_robustness.py`) passes. It holds the adaptive reserve-violation rate (3.67 %) and the paired difference against nominal (−57.0 percentage points). `wilson(11, 300)` reproduces C1's interval, 2.06–6.45 %. - Sebas's 7 rows in Juan's registry (PR #146, branch `16-results-table`): E3 ×3 and C1 ×4. With `field` and `sha256` filled in, all 7 pass with `--owner Sebas`: values, checksums and the tag in the E3 note. The Nevado Sajama row (+1.8 %) had no output file, because the comparison was run by hand for the E3 note. `src/fisica/human_cost_effect.py` → `data/e3/human_cost_effect.json` now produces it. The file also showed that the note's E3-only energy was 162.5 Wh (162.462), not 162.4; the note is corrected.
- The 58 other rows were skipped here (other owners' files); each owner runs the check on their machine.

## Checks
- The tests build a small repository in a temporary folder with JSON, CSV, JSONL and Markdown outputs and a note with tags, so they need no shared data.
- The block bootstrap test has a strong block effect and checks that the interval is much wider than a naive per-pixel interval.

## Limitations
- The checker can only check rows whose output is on the machine that runs it. A full pass needs each owner to run it with `--owner`.
- It checks that a value matches its file, not that the file is scientifically right. A checksum also says nothing about inputs that changed while the output stayed identical; `data_version` is not verified.
- `interval` is not checked against the file yet; only `value` is.
- Untagged citations are not checked. Until notes use tags, stale numbers in prose can still slip through.

## What other pieces can use
- Every owner: tag a figure where you cite it, `value<!-- r:<id> -->`, and run `python src/results/check_registry.py --owner <you>` before you close a note.
- Juan (#16): write `field` with the locators above and `sha256` with the first 12 hex digits. `intervals.registry_text` writes the `interval` cell. I do not change the CSV, `build_table.py` or the table.

## Reproduce
```
python -m pytest tests/results/test_check_registry.py
python src/results/check_registry.py --owner <your name or login> --json data/results/check_report.json
```

## Outputs
- `src/results/check_registry.py`, `src/results/intervals.py`, `tests/results/test_check_registry.py`.
- The optional JSON report path is chosen by whoever runs it; keep it under `data/` (out of git).
