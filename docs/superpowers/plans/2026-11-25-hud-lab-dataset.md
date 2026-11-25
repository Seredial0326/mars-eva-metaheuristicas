# Lab datasets in the HUD Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A "Load lab dataset" button in the HUD's Stations tab that loads one experiment case or the full 120-station pool, so any of the six solvers can plan it live.

**Architecture:** `datasets.build_all` also writes `pool.csv`; `api/lab.py` serves the list of datasets and each dataset's stations; `web/index.html` replaces its station list with them (scores kept, Save disabled, way back to the saved stations). Planning reuses `/plan` and the existing solver selector.

**Tech Stack:** Python 3.14, FastAPI, pytest; vanilla JS + deck.gl in `web/index.html`.

**Spec:** `docs/superpowers/specs/2026-11-25-hud-lab-dataset-design.md`

## Global Constraints

- Dataset ids: `real-n<n>-<case>` (one per case, read from `<id>-120min.csv`) and `pool`.
- `GET /lab/datasets` → `[{id, label, n, stations}]`; `GET /lab/datasets/{id}` → `{id, label, habitat: {x, y}, stations: [{id, type, x, y, score, service_time_min}]}`; unknown or unsafe id → 404.
- `pool.csv` lives in `data/lab/instances/`, columns `id,type,x,y,prize,service_s`, habitat first.
- HUD: loading replaces the list; Save disabled while loaded; "Back to my stations" reloads `/stations`; score from `lab_score`.
- UI copy in English (the HUD is in English); local branch only, no push.

## Review Focus

- Path traversal in `/lab/datasets/{id}` (`..`, `%2e%2e`): expect 404.
- No `pool.csv` on disk (old data dir): list omits `pool`, `GET /lab/datasets/pool` → 404.
- Loading a dataset, then editing a station: Save must stay disabled until "Back to my stations".
- A plan made before loading must show as stale after loading.
- Exact solver on 99 stations: the existing 422 message must show, not a blank panel.

---

### Task 1: pool.csv and dataset endpoints

**Files:**
- Modify: `src/orienteering/lab/datasets.py` (`build_all`, new `save_pool(stations, root)`)
- Modify: `api/lab.py` (two routes)
- Test: `tests/orienteering/test_lab.py`, `tests/api/test_lab_api.py`

- [ ] **Step 1: Tests**
  - `test_save_pool_roundtrip(tmp_path)`: `save_pool(stations, tmp_path)` writes `pool.csv` with the habitat first and the CSV columns above.
  - `test_lab_datasets_list(client, lab_dir)`: with `real-n20-0-120min.*`, `real-n20-0-180min.*` and `pool.csv` in the patched instances dir, the list is `[{"id": "real-n20-0", ...}, {"id": "pool", ...}]` with `stations` = rows minus the habitat.
  - `test_lab_dataset_get`: `GET /lab/datasets/real-n20-0` returns the habitat and the stations with `score` = prize and `service_time_min` = service_s / 60.
  - `test_lab_dataset_missing_and_traversal`: `pool` without the file, `nope`, `..%2Fruns` → 404.
- [ ] **Step 2:** Run them; they fail.
- [ ] **Step 3:** Implement. `build_all` writes `pool.csv` whenever it is missing and `real` is on (graph + `station_pool`, no Dijkstra).
- [ ] **Step 4:** Run `pytest tests/orienteering/test_lab.py tests/api/test_lab_api.py -q`; pass. Run `PYTHONPATH=src .venv/Scripts/python.exe -m orienteering.lab.datasets` to write the real `pool.csv`.
- [ ] **Step 5:** Commit `lab: serve experiment station sets and the station pool`.

### Task 2: HUD button

**Files:**
- Modify: `web/index.html` (Stations panel markup, `scoreOf`, `saveStations`, new `loadLabDatasets()` / `loadLabDataset()`)

- [ ] **Step 1:** Markup next to `#load-candidates`: `<select id="lab-dataset">` (filled from `/lab/datasets`, hidden row when the list is empty) and `<button id="load-lab" class="secondary">Load lab dataset</button>`; a notice `#lab-notice` with a `Back to my stations` link button.
- [ ] **Step 2:** `scoreOf = s => s.lab_score ?? Number(rubric[s.type] ?? 0)`; loading maps `score → lab_score`, replaces `stations`, sets `labDataset`, disables `#save-stations`, marks the plan stale, re-renders. "Back to my stations" calls `loadStations()`, clears `labDataset`, re-enables Save.
- [ ] **Step 3:** Verify in the running app: load `real-n20-0`, plan with DP; load `pool`, plan with ACO; CP-SAT on `pool` shows the 422 message; Save is disabled until going back.
- [ ] **Step 4:** Run the full test suites once; commit `web: load lab datasets in the HUD`.
