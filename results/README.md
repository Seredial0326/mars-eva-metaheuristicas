# results/ · team results table (#16)

| File | What it is |
|---|---|
| [`registry.csv`](registry.csv) | **The registry.** One row per number, with what it is computed over and where it comes from. This is the file people edit. |
| [`results_table.md`](results_table.md) | **The table to read**, for the demo, the README and the paper. Generated from the registry by `src/results/build_table.py`; never edited by hand. |

The format was announced on the board (#1). It is also the record that part C3 of #120 asks for: metric, units, population, configuration, commit, data version or checksum, script and output.

## Columns of `registry.csv`

UTF-8, comma-separated, decimal point, **no empty cells**. Use `none` (interval, setting) or `pending` (field, data version, checksum) instead of leaving a cell empty.

| Column | What goes there |
|---|---|
| `id` | Short unique id, prefixed by the piece: `e4-rv-median` |
| `piece`, `owner` | Piece (E1…X2, `Baselines`, C1, P1…) and its owner |
| `result` | What is measured, in English. A reference number from the same output can go in the text: `GP RMSE (best smoothing: 1.142)` |
| `value`, `unit` | The number as the table shows it, and its unit (Wh, %, min, AUC, count…) |
| `interval` | An interval when the population is well defined (`95% Wilson 2.06–6.45`), else `none` |
| `population` | What the number is computed over: n and of what |
| `setting` | The configuration that matters (budget, cost, seed, sol…). Values with no source say `assumed` |
| `kind` | `observation` (measured on real data), `model` (our model on the real terrain or data), `simulation` (synthetic or random scenarios), `check` (validation of a method or tool) |
| `negative` | `yes` for a negative result. They are kept on purpose |
| `script`, `output` | The command that writes the output file (under `src/` or `api/`), and that file (`data/…`, or `paper/…` for a figure's JSON). `pending` while a number has no output file yet |
| `field` | Where the number is inside the output, or `pending`. Same syntax as the checker of part C3 (`src/results/check_registry.py`, #145): `a.b[0]`, `levels["50%"].x` for keys with dots or symbols, and a trailing ` *100` to turn a fraction into % |
| `commit` | Short hash of the code that produced the output, or `pending` while that code is in a PR not yet merged (the owner fills it in after the merge) |
| `data_version` | Input data releases (`base-grid-v2; e8-v0`), or `pending` |
| `sha256` | First 12 characters of the sha256 of the output file, or `pending` |
| `confirmed` | `yes` once the owner confirmed the row |
| `reported_in` | Where the owner reported it: a comment in #16, a PR, or a note line (`paper/notes/E2_curiosity_traverse.md:53`) |

The checksum is that of the file on the owner's machine:

```bash
python -c "import hashlib,sys; print(hashlib.sha256(open(sys.argv[1],'rb').read()).hexdigest()[:12])" data/e4/summary.json
```

## Add or correct a row

1. Edit **only your own rows** in `registry.csv` (another owner's rows need a handoff on the board).
2. Regenerate the table: `python src/results/build_table.py`
3. Run the tests: `python -m pytest tests/results`
4. Commit both files in the same PR.

`python src/results/build_table.py --check` only checks that the table is up to date.

## Who does what

- **Juan (#16):** the format, the rows and `build_table.py`; each owner confirms or corrects their rows.
- **Sebas (part C3 of #120):** the provenance checker that opens each output file and compares `value` and `sha256` with the registry, intervals where they apply, and the C3 note. New columns are asked for on the board first.
- **E12** gets its row from #144 (the dose on the E5 tours). **E7** has no row: it was not run because E9 worked.
