# Base grid · Bbox, DEM, orthophotos, terrain features and map tiles

Owner: JB (`@JavierBonilla2004`) · Issue: #3 · PRs: #17, #18, #19, #20 (hours 0–4), this PR (paper note) · Status: done; hour-4 milestone waits on the HUD (#10) · Last update: 2026-11-14

## Question
Which piece of Gale do we plan on, and on what grid? Every other piece needs the same CRS, bbox and cell, so this note fixes them and checks that the data inside are good enough: complete, aligned, and with HiRISE-level detail where Curiosity drove through the boxwork.

## Data
- **DEM:** `MSL_Gale_DEM_Mosaic_1m_v3.tif` [Parker2016]: HRSC + CTX + HiRISE mosaic tied to MOLA, 1 m/px, float32, nodata −32767, stored in row strips.
- **Orthophotos (0.25 m):** HiRISE colour COG `MSL_Gale_HiRISE-LRGB_78quads_sharp_cog.tif` and grey `MSL_Gale_Orthophoto_Mosaic_25cm_v3.tif` [HiRISE-Gale]. The grey mosaic (≈ 50 GB, uncompressed rows) was never downloaded whole: only the bbox was read over HTTP with GDAL `/vsicurl/` (about 1.4 GB, 8 min).
- **Traverse (for placing the bbox only):** PLACES `localized_interp.csv` [PLACES]. The official traverse on the grid is E2's (`data/e2/`).

## Method

### Hours 0–1: CRS and bbox
1. The DEM and both orthophotos share the same projection (Mars equirectangular, sphere R = 3,396,190 m; identical `+proj` strings). Their WKT names differ, so the DEM WKT is the contract: `docs/contracts/crs.wkt`.
2. The bbox is 2 × 2 km, centred on Curiosity's poses in the boxwork campaign and **snapped to the DEM pixel grid**. The DEM origin is not an integer (x0 = 8,127,993.4928 m), so GDAL `-tap` would shift the bbox by half a metre; we always crop with `-te` (`docs/contracts/bbox.txt`).
3. Visual check in QGIS: DEM hillshade vs orthophoto, and the PLACES poses over both.

### Hours 1–2: base grid (`src/gis/grid.py`)
1. `dem_1m.tif`: `gdalwarp -te <bbox> -tr 1 1`, nodata → NaN. Because the bbox is on the DEM grid, this only crops.
2. `dem_1m_margin.tif`: same with a 64 m margin, so filters have neighbours at the edges.
3. `ortho_color_025.tif`, `ortho_gray_025.tif`: `gdalwarp -te <bbox> -tr 0.25 0.25 -t_srs crs.wkt`, bilinear. The colour COG is offset 0.24 m from the DEM grid, so it is resampled onto it.
4. `grid.json`: CRS, bbox, origin, cell size, size and nodata, so the others can work without opening the DEM (`docs/contracts/grid.json`).

### Hours 2–3: terrain features (`src/gis/features.py`)
All computed on the margin DEM and cropped to the exact bbox (64 cells per side).

| Layer | Definition |
|---|---|
| `slope_deg` | GDAL `gdaldem slope` (Horn), degrees |
| `residual` | DEM − Gaussian-smoothed DEM (σ = 5 m) |
| `roughness` | local standard deviation of `residual`, 7 × 7 m |
| `tpi` | DEM − local mean, 15 × 15 m |
| `hillshade` | GDAL `gdaldem hillshade`, uint8 (display) |

### Hours 3–4: map tiles (`src/gis/tiles.py`)
Colour slope (green 0°, yellow 15°, orange 30°, red ≥ 45°) and XYZ tiles with the GDAL `gdal2tiles` **raster** profile (not Web Mercator): orthophoto z 0–5, slope and hillshade z 0–3. The z = 0 tile spans 2048 m in all three layers, so they overlay without extra maths (`tiles.json`).

## Results
Source: `src/gis/paper_figures.py` → `data/base/summary.json`.

### Grid

| Quantity | Value |
|---|---|
| Bbox (m, DEM CRS) | x 8,142,537.49–8,144,537.49 · y −285,463.08 to −283,463.08 |
| Grid | 2000 × 2000 cells of 1 m (orthophotos 8000 × 8000 of 0.25 m) |
| Curiosity poses inside | 5,247 `ROVER` poses, sols 4369–4868, sites 111–121 (E2) |
| DEM elevation | −3876.1 to −3401.2 m; 0 NaN cells |

Figure: [grid_fig1_context.png](../figures/grid_fig1_context.png), the bbox and the whole traverse over 12 × 12 km of the DEM.

### Terrain features

| Layer | Range | Other |
|---|---|---|
| `slope_deg` | 0–79.6° | mean 16.2°; 44.0 % > 15°, 12.4 % > 30°, 1.92 % > 45°, 0.105 % > 60°, 0.006 % > 70° |
| `residual` | −7.48 to +13.08 m | mean 0; only 0.021 % of cells beyond ±3 m |
| `roughness` | 0.006–4.75 m | mean 0.244 m |
| `tpi` | −7.32 to +13.32 m | mean 0 |

- Cells above 60° (0.1 %) are the walls of the large wind-eroded knobs; for a walking astronaut 12 % of the box is above 30°.
- Figures: [grid_fig2_features.png](../figures/grid_fig2_features.png) and [grid_fig3_slope_hist.png](../figures/grid_fig3_slope_hist.png).

### Map tiles
1,365 orthophoto tiles (z 0–5), 85 slope and 85 hillshade tiles (z 0–3), released as `tiles-v2`.

### DEM detail vs the orthophoto
[grid_fig4_detail.png](../figures/grid_fig4_detail.png) shows a 250 × 250 m window. The **orthophoto resolves the boxwork**: a network of bright ridges a few metres wide enclosing 5–15 m cells, with dark grey-blue sand in the troughs. The **DEM hillshade and residual do not**: at this scale they show smooth blobs and no network. The DEM is posted at 1 m but its effective resolution is coarser, so boxwork ridges (1–3 m wide) are below what it resolves. This matches E2: inside the boxwork, DEM features do not predict where the rover drove (AUC ≈ 0.53).

## Checks
Source: `summary.json` → `checks`.
- Same origin for the DEM and both orthophotos (8,142,537.492786024, −283,463.075189438); orthophotos exactly 4 × the DEM; same CRS: all `True`.
- Grey vs colour orthophoto: Pearson correlation 0.953 (1 pixel in 50); grey nodata (0) is 0.001 % of the bbox.
- Slope from `gdaldem` (Horn) vs NumPy central differences: median absolute difference 0.30°.
- E2 independently recovered the same grid indices that PLACES ships for 99.5 % of poses, and PLACES elevations match the DEM with a median difference of −0.01 m (E2 note).
- Visual review in QGIS: hillshade and orthophoto overlay with no visible shift, and the traverse runs between the knobs, never over a wall.

## Limitations
- **Effective DEM resolution is coarser than 1 m** (see above). Every DEM-derived layer misses the boxwork ridges; only the orthophoto sees them.
- The 1 m slope is noisy: single cells above 60° are partly DEM artefacts, not climbable walls.
- The orthophotos are resampled (bilinear) onto the DEM grid, which slightly smooths them.
- A vertical seam of the DEM mosaic is visible about 4.6 km east of the bbox (fig 1). It lies outside the bbox but should be checked before any extension east.
- No DEM-quality map (local detail per 50 m block) was made yet.

## What other pieces can use
- **Everyone:** release `base-grid-v2` → `data/base/`; spec in `docs/contracts/grid.json`. Never crop your own bbox or use `-tap`.
- **E3, E4, baselines (Sebas, Aaron):** `slope_deg.tif`. 12 % of cells above 30° will act as no-go terrain.
- **E1 (Juan):** `roughness.tif`, `tpi.tif`. Expect them to explain the large-scale valley choice, not the path inside the boxwork.
- **E8 (JB):** weak labels from DEM top-hats would mark the large knobs, not the boxwork network. Labels derived from the orthophoto (bright ridges, dark sand) are being evaluated in #11.
- **HUD (Sebas):** release `tiles-v2` → `data/tiles/`, raster profile, see `tiles.json`.

## Reproduce
From the `data/` folder, with the `martian` environment, the DEM, the colour COG and PLACES in their `data/` folders:
```bash
gdalwarp ...            # crops: commands in docs/contracts/bbox.txt and src/gis/ docstrings
python ../src/gis/grid.py
python ../src/gis/features.py
python ../src/gis/tiles.py
python ../src/gis/paper_figures.py
```

## Outputs
In `data/base/` (release `base-grid-v2`): `dem_1m.tif`, `dem_1m_margin.tif`, `ortho_color_025.tif`, `ortho_gray_025.tif`, `slope_deg.tif`, `residual.tif`, `roughness.tif`, `tpi.tif`, `hillshade.tif`, `crs.wkt`, `bbox.txt`, `grid.json`, `summary.json`.
In `data/tiles/` (release `tiles-v2`): `ortho/`, `slope/`, `hillshade/`, `tiles.json`.
In `paper/figures/`: `grid_fig1_context.png` to `grid_fig4_detail.png`.