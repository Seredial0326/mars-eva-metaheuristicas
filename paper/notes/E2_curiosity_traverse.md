# E2 · Curiosity's traverse on the base grid and a terrain-only baseline

Owner: Juan (`@JuanCorredor2023`) · Issue: #4 (closed) · PRs: #22 (hours 0–4), #25 (hours 4–12) · Status: done (update with E8 sand in PR #57) · Last update: 2026-11-14

## Question
Where exactly did Curiosity drive inside our 2 × 2 km bbox, cell by cell on the base grid? And, within reach of that route, do the terrain features of the base grid tell where the rover drove? The second answer is the bar the learned cost (E1) has to beat.

## Data
- **Traverse:** PLACES `localized_interp.csv` [PLACES], 49,315 interpolated rover poses for the whole mission, each with `easting`/`northing` already in the DEM CRS, elevation, orientation, `site`, `drive`, `pose` and `sol`.
  - Only `ROVER` rows are used. The 121 `SITE` rows (`drive = -1`, `pose = -1`) are site-frame origins: each of the 10 inside the bbox lies exactly on an existing `ROVER` pose (0.000 m) and has no orientation, so keeping them would duplicate poses.
  - The `localized_interp_demv2.csv` variant is not used: it is tied to another DEM version and sits about +56 m higher and up to 22 m off horizontally against DEM v3.
- **Grid and terrain:** JB's base grid (release `base-grid-v2`): `dem_1m.tif` [Parker2016] cropped to the contract bbox (2000 × 2000 cells of 1 m), `slope_deg.tif`, `roughness.tif`, `tpi.tif`; orthophoto `ortho_color_025.tif` [HiRISE-Gale] for review. Bbox and CRS are read from `docs/contracts/grid.json` and `crs.wkt`.

## Method

### Hours 0–4: traverse to grid (`src/ml/trajectory_to_grid.py`)
1. Keep the `ROVER` poses with `sol ≥ 0` in file order (sorted by site, drive, pose = route order).
2. Cell indices from the DEM transform: `col = floor((E − XMIN) / 1 m)`, `row = floor((YMAX − N) / 1 m)`, row 0 at the top. Keep the poses inside the grid; a new segment starts whenever the route re-enters the bbox or two consecutive poses are more than 10 m apart.
3. Consecutive poses are 0.92 m apart (median; p99 1.58 m, max 2.0 m), so a cell can lie between two poses. The line between consecutive poses is sampled every 0.25 m and the cells it crosses are added. Consecutive repeats are removed, which gives the **cell sequence** in traversal order (input for E1).
4. Outputs: route line and poses (GeoPackage and GeoJSON, DEM CRS), visited-cell list, cell sequence.

### Hours 4–12: cell × feature table and logistic baseline (`src/ml/cell_features.py`, `src/ml/logistic_baseline.py`)
1. **Compared cells.** Visited cells against not visited cells within 25, 50 (main) and 100 m of the route (Euclidean distance to the nearest visited cell), plus the whole box as a reference. Comparing against the whole box mostly measures geography ("the rover never went to that corner"); the corridor holds the alternatives the drivers actually had. Cells closer than 2 m to the route are excluded: the rover is about 3 m wide, so they were driven over too.
2. **Features:** `slope_deg`, `roughness`, `tpi` at 1 m, plus the mean slope in 5 × 5 m and 15 × 15 m windows, because drivers avoid areas, not single cells. Position, elevation and distance to the route are left out on purpose so the model cannot guess by location.
3. **Validation:** the route is split into 5 consecutive blocks with the same number of visited cells (by route order: sols 4369–4450, 4450–4512, 4512–4587, 4587–4680, 4680–4868). Every cell inherits the block of its nearest visited cell. Each block is scored by a model trained on the other four (leave-one-block-out), because neighbouring cells are strongly correlated and a random split would inflate the score.
4. **Model:** logistic regression on standardized features with class-balanced weights (scikit-learn [sklearn]), plus a slope-only model. Metric: AUC (0.5 = chance).

## Results

### Traverse on the grid
Source: `src/ml/trajectory_to_grid.py` → `data/e2/summary.json`.

| Quantity | Value |
|---|---|
| Poses inside the bbox | 5,247 (sols 4369–4868, sites 111–121) |
| Poses in the boxwork (sols 4541–4848, provisional range) | 2,598 |
| Segments / length | 1 / 3,900.3 m |
| Visited cells (with at least one pose) | 4,477 (3,566) |
| Steps in the cell sequence | 4,687 |

Figure: [e2_fig1_trajectory.jpg](../figures/e2_fig1_trajectory.jpg), the route over the hillshade (a) and the orthophoto (b), coloured by sol.

### Terrain-only baseline
Source: `src/ml/logistic_baseline.py` → `data/e2/logistic_baseline.json`. The table has 603,695 cells: 4,477 visited plus 599,218 not visited at 2–100 m (158,898 within 25 m, 313,711 within 50 m).

| Not visited cells used | All features: AUC mean (block range) | Slope only |
|---|---|---|
| ≤ 25 m | 0.512 (0.486–0.537) | 0.490 |
| **≤ 50 m (main)** | **0.526 (0.473–0.612)** | 0.458 |
| ≤ 100 m | 0.561 (0.466–0.668) | 0.537 |
| Whole box (400,000 random not visited cells) | 0.730 (0.612–0.812) | 0.663 |

- **AUC per block (all features, 50 m):** 0.612, 0.551, 0.497, 0.473, 0.498. The two blocks before the boxwork (sols 4369–4512) carry the only local signal (0.655 and 0.668 at 100 m). The three later blocks (sols 4512–4868, mostly boxwork) are at chance at every corridor width (0.47–0.53).
- **Slope distributions in the 50 m corridor:** visited and not visited cells are nearly identical. Median 8.9° vs 8.8°, p90 19.0° vs 19.4°, p99 34.6° vs 32.9°, and 1.76 % of cells above 30° in both groups. The whole box has a median of 13.4°. Figures: [e2_fig2_slope_distribution.png](../figures/e2_fig2_slope_distribution.png) and [e2_fig3_auc.png](../figures/e2_fig3_auc.png).
- **Standardized coefficients of the main model** (fitted on all blocks, 50 m): `slope_mean_15m` −0.359, `roughness` +0.270, `slope_mean_5m` +0.142, `slope_deg` −0.079, `tpi` −0.042. The slope features are strongly correlated with each other, so individual signs should not be over-read; the largest effect is avoiding steep terrain at the 15 m scale.
- **Route-likeness map:** [e2_fig4_score_map.png](../figures/e2_fig4_score_map.png) (`data/e2/visit_probability.tif`). Steep ridge walls score low, and the route runs through the high-scoring valley floor.

**Reading:** terrain explains the choice of valley (whole box: AUC 0.73) but not the path within it (50 m corridor: 0.53, about chance).

### Update: the same baseline with E8 sand
Source: `src/ml/logistic_sand.py` → `data/e2/logistic_baseline_sand.json`. The baseline above is unchanged. This repeats it with E8's `sand.tif` (release `e8-v0`, PR #49): the sand fraction of the cell and its 5 × 5 m mean. Same sets, model and blocks; the DEM-only model reproduces 0.526 and 0.730 exactly.

| Not visited cells used | DEM only | DEM + sand | Sand only |
|---|---|---|---|
| ≤ 50 m (main) | 0.526 | 0.531 | 0.524 |
| Whole box | 0.730 | 0.726 | 0.446 |

- **Corridor:** sand lifts the AUC by 0.005, better in 4 of 5 blocks (−0.013, +0.007, +0.015, +0.014, +0.002). That is noise level for a per-cell score.
- **Direction:** visited cells have less sand than their neighbours (corridor means 0.063 vs 0.091; 6.1 % vs 8.8 % of cells more than half sand).
- **Whole box, sand only:** below 0.5, because some stretches of the route run through sandier ground than the box average. It reflects where the route runs, not avoidance.
- **On whole routes it does help:** with start and goal given, E1's MaxEnt model with sand beats distance alone out of sample (`paper/notes/E1_maxent_irl.md`).

## Checks
- CRS, bbox and cell size of the DEM match the contract (`summary.json` → `checks`).
- **Elevation agreement:** PLACES elevation minus DEM elevation at the assigned cell has a median of −0.01 m, with p5 −0.74 m and p95 +0.61 m. A horizontal misregistration of a few metres would show up as metre-level differences on slopes, so this also rules out registration as the cause of the near-chance AUC.
- Nine poses differ by about 2 m (−2.0 to −2.4 m, rover lower than the DEM, at sols 4432, 4614 and 4647). In QGIS they sit on a ridge edge and on very rough boxwork terrain: narrow troughs the DEM smooths over.
- **Independent indices:** our row/col equal the DEM pixel indices that PLACES ships (`dem_pixel_line/sample`, on a grid aligned with ours) for 99.5 % of poses; the other 52 lie at most 5.2 mm from a cell edge (PLACES rounds those columns to 0.01 px).
- The cell sequence is 8-connected (every step goes to one of the 8 neighbours).
- Identical results with a provisional crop of the raw DEM and with JB's `dem_1m.tif`, which are identical rasters.
- Our slope recomputed with Horn's method matches `slope_deg.tif` (99 % of cells within 0.011°).
- Visual review in QGIS over the orthophoto, the slope and the filtered `|dz| > 2 m` poses.

## Limitations
- Features come from a 1 m DEM whose effective resolution is coarser. Rocks, sand patches and small ridges, which are what a rover actually avoids, are below what these features see. 1 m slope is also noisy: 1.76 % of visited cells exceed 30°, which the rover did not literally climb.
- Route choices also follow science targets (drill sites, imaging) and operations, not only terrain, so a terrain-only model has a ceiling.
- The block validation has no spatial buffer between blocks, so neighbouring cells across a block edge can share information. This would inflate the AUC, not deflate it, and the local AUCs are already near chance.
- The model scores are class-balanced, relative scores, not calibrated probabilities.
- The boxwork sol range (4541–4848) is provisional.
- No rover tracks were identified in the orthophoto, so the route could not be checked against them directly; the elevation agreement is the main positional check.

## What other pieces can use
- **E1 (Juan):** `data/e2/cell_sequence.csv` gives the demonstrations; `cell_features.parquet` gives the features. Expect little local signal from slope, roughness and TPI alone. MaxEnt models whole paths, which may capture the valley choice better than a per-cell classifier. The bar to beat is AUC 0.53 (50 m) and 0.73 (whole box).
- **E8 (JB):** inside the boxwork the terrain features are at chance. Sand and ridge masks (`arena.tif`, ridge/hollow classes) are the most likely missing features, so expect them to matter.
- **E9 (Aaron):** boulder density (`rocas.tif`) is the other obstacle class below the DEM's resolution, and is likely to help in the same way.
- **E4/E5 (Aaron, Diana):** at the large scale the route avoids steep valley walls; mean slope at 15 m had the largest coefficient.
- **Everyone:** use `data/e2/` (release `e2-trajectory-v1`) for the traverse, not the trajectory file in the old `malla-base` packages.

## Reproduce
From the repo root, with the `martian` environment, `data/base/` from release `base-grid-v2`, and PLACES in `data/` or `../data` (or `MARTIAN_DATA`):
```bash
python src/ml/trajectory_to_grid.py
python src/ml/cell_features.py
python src/ml/logistic_baseline.py
python src/ml/paper_figures.py
python src/ml/logistic_sand.py    # update with E8 sand (needs data/e8/ from release e8-v0)
```

## Outputs
In `data/e2/`:
- `trajectory.gpkg`, `trajectory.geojson`, `trajectory_poses.geojson`, `trajectory_cells.csv`, `cell_sequence.csv`, `summary.json` (shared as release `e2-trajectory-v1`);
- `cell_features.parquet`, `logistic_baseline.json`, `logistic_roc.png`, `visit_probability.tif`;
- `logistic_baseline_sand.json` (update with E8 sand).

In `paper/figures/`: the `e2_fig1` to `e2_fig4` figures. Column reference: `src/ml/README.md`.
