# Lab datasets in the HUD: design (short)

**Intent.** For the class presentation, the main app (`/`, the HUD) must show the points of the
lab datasets on the Mars map and let the presenter pick one of the six algorithms and compute
the route live, drawn over the terrain. Routes already computed by the lab runs are not loaded.

**Approved by Sebas (2026-11-25): option A + B.**

## What gets built

- **Stations tab**: next to "Load Curiosity sites", a selector plus a **"Load lab dataset"**
  button. The selector lists:
  - the 8 station sets of the experiment (`real-n20-0`, `real-n20-1`, `real-n50-0`, ...,
    `real-n100-1`; both scenarios of a case share the stations, so one entry per case);
  - **"Full pool (120)"**: every station of the lab pool (manual + E8 + generated `G*`).
- Loading **replaces** the station list (the plan must use exactly that set). While a lab
  dataset is loaded:
  - "Save stations" is disabled, so the saved manual stations are never overwritten;
  - a notice names the dataset and offers **"Back to my stations"** (reloads the saved list);
  - each station keeps the score it has in the experiment (`lab_score`), so E8 stations do
    not get the rubric's contact score.
- **Plan tab**: unchanged. The presenter picks the algorithm in "Route solver", sets EVA
  length (120 or 180 min, the experiment's scenarios), and presses "Plan the walk". The route
  follows the terrain and the summary shows the solver and its time (already there).
- Exact solvers keep their limits (DP up to 19 stations, CP-SAT up to 59); above that the plan
  shows the existing 422 message.

## Backend

- `GET /lab/datasets` → `[{id, label, n, stations}]`: the 8 cases found on disk, plus `pool`
  when `pool.csv` exists.
- `GET /lab/datasets/{id}` → `{id, label, habitat: {x, y}, stations: [{id, type, x, y,
  score, service_time_min}]}` (habitat excluded from `stations`). Ids validated with `_SAFE`;
  404 when missing.
- `datasets.build_all` also writes `data/lab/instances/pool.csv` (same columns as the
  instance CSVs, habitat first) when it is missing; computing the pool needs the graph but no
  Dijkstra.

## Approaches considered

- A. One experiment instance per load: matches the measured results; exact solvers run on 20
  and 50 nodes.
- B. The full pool: every point at once; only metaheuristics run.
- **A + B (chosen)**: one selector offers both for about the same cost.
- Loading pre-computed routes from `runs.csv`: rejected by Sebas (routes must be live).

## Notes

- Scores in the HUD can differ slightly from the lab runs: `/plan` snaps stations to grid
  cells and re-plans when the walkback check fails.
- The habitat is the HUD's (box centre unless the user set a base), which is the lab
  habitat's cell.
