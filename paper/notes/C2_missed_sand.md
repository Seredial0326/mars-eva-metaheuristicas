# C2 · Operational sensitivity to missed sand

Owner: Sebas (`@Seredial0326`) · Issue: #120 C2 · Status: scenario evaluation complete; review pending · Last update: 2026-11-15

## Question

How do spatially omitted sand patches change route energy and return margin, separately from an uncertain energy penalty? Can a precaution based only on the existing image detections recover the missed class?

## Data

The nominal E3 × E1 sand graph, existing manual/E8 stations and E8 blind point labels. E8's note reports sand recall near 11% and a failed threshold-adjustment attempt (#93). Its error includes confidently missed dust-covered sand; threshold reduction is not a demonstrated correction. We do not retrain or replace `sand.tif`, change the nominal cost, or reinterpret detector variance as missing-class probability.

Source for every experiment number below: `src/fisica/missed_sand.py` → `data/robustness/c2/summary.json`, `worlds.jsonl` and generated `table.md`. Inputs have SHA-256 records in the summary; raw data remain outside git.

The local CSV contains 45 sand labels whose **hard predicted stratum** is not sand, grouped into 43 distinct 20 m label blocks after converting 0.25 m pixel indices to 1 m cells. This is a scenario-anchor definition, not a reproduction of the 39 probability-threshold misses in E8's calibration note. The first-pass labels are unavailable locally, so agreement between annotator passes is not checked. The sample is stratified and ambiguous, not an exhaustive surface map.

The evaluation uses the 28 existing station goals and a habitat at the centre of the base grid. Hidden patches are confined to SW-S (the point-validation support), not extrapolated to all Gale or the whole box.

## Method

`src/fisica/missed_sand.py` creates an isolated graph and output directory; it reads existing physics, E1 and graph functions without changing their owner modules.

1. **Segmentation scenarios:** each label block can generate one disk, with presence probability 0.5, centre jitter ±radius/3 and radii 5, 15 or 30 m. These parameters are assumptions. Disks overlap spatially, stay within SW-S, and add only the cell fraction not already marked as sand. There are 30 independent seeded worlds per radius. A pixel is not treated as an independent observation.
2. **Separate penalty axis:** extra energy on a hypothetical hidden fraction h is E_nominal × (1 + beta·h), with beta 0.115 or 1.0. The smaller value is on the scale of the existing sand-factor ceiling, not a fitted price for the missed class; the larger value is an intentionally strong sensitivity case. Neither is a measured astronaut penalty. The same spatial world is used across penalties and policies.
3. **Policies:** nominal uses the unchanged E3 × E1 graph. A candidate conservative policy uses only the nominal map: 0.5·exp[−(distance_to_detected_sand/20 m)²]·(1−sand). This proximity proxy is a declared precaution, not a calibrated probability. It cannot see label locations or the realised hidden world. Round trips are shortest paths on the directed weighted graph.
4. **Budget:** usable energy is artificially set to 1.10 times each goal's nominal loop energy, equally for both policies and all worlds. This stresses sensitivity in a box where the real suit budget often does not bind. A candidate exceeding its own predicted usable budget is **declined**, not executed.
5. **Evaluation:** report candidate route overlap (directed-edge Jaccard), length change, realised loop energy, hidden-cell exposure and minimum usable return margin. For a positive-cost loop ending at its habitat, the minimum of usable − used(v) − R_true(v) equals usable minus the loop's total actual energy: the remaining loop is always one valid return, and equality holds at the final habitat. The identity is checked against exact reverse Dijkstra on a toy directed graph. It is not a new operational return field or time/O2 guarantee.
6. **Inference:** aggregate all goals within each complete spatial world, then bootstrap worlds for marginal and paired candidate differences. Do not bootstrap vertices, pixels or repeated goals as independent experiments. Small or zero-event intervals can be degenerate and do not establish zero physical risk.

## Results

The conservative candidate changes 27/28 loops at beta=0.115 and 28/28 at beta=1.0. Maximum added length is 14.40 m and 78.05 m, respectively. The weak candidate accepts all goals under the chosen budget; the strong candidate declines all goals. The following energy/margin numbers still evaluate the candidate loops counterfactually, including declined ones; they are not statistics of executed walks.

At the largest assumed radius (30 m), mean over the goals and spatial worlds:

| Beta | Candidate | Accepted goals | Actual energy | Usable margin | Hidden arrival-cell fraction sum |
|---|---|---|---|---|---|
| 0.115 | nominal | 28/28 | 157.90237 Wh | 15.76219 Wh | 1.77024 |
| 0.115 | conservative | 28/28 | 158.26023 Wh | 15.40434 Wh | 1.10952 |
| 1.0 | nominal | 28/28 | 158.09857 Wh | 15.56600 Wh | 1.77024 |
| 1.0 | conservative | 0/28 | 166.48446 Wh | 7.18011 Wh | 1.69405 |

For the weak candidate at radius 30 m, the paired extra energy is 0.35786 Wh (95% world-bootstrap interval 0.35454–0.36124 Wh). The nominal mean without route/hidden changes is 157.87688 Wh, so the omitted patches add only about 0.02549 Wh in that weak case. At radius 5 m they do not intersect any candidate route in these worlds; at 15 m the intersection remains very small. These are conditional geometric results, not evidence that E8's missed sand is operationally harmless.

There are no nominal reserve violations in the tested worlds. For the strong conservative **declined** candidates at radius 30 m, 1.43% would violate the reserve if executed anyway; that is a counterfactual diagnostic, not a failure rate of the declining policy. Under that assumed penalty, rejecting every goal is itself an unacceptable science tradeoff, not a useful safety result.

The image-only proximity precaution does not solve the confidently missing class: it spends energy avoiding areas near existing detections, while omitted patches may lie elsewhere. No policy or corrected raster is promoted to production. Figure: [c2_fig1_missed_sand.png](../figures/c2_fig1_missed_sand.png), generated by the same script.

## Checks

`tests/fisica/test_missed_sand.py` checks label-scale conversion and block deduplication; spatial support, reproducibility and immutable nominal input; failure of an image-only proxy with no detections; arrival-cell directionality; closed-loop margins against exact return Dijkstra; independent variation of map error and penalty; and world-level bootstrap units. No downloaded data are needed for these tests. The real run checks raster alignment and records source hashes.

## Limitations

- One habitat, station round trips without service, and a small spatially sampled region. No E5 re-selection of scientific stations or joint time/O2 return is evaluated.
- Hard-class point misses are not an area-weighted estimate of hidden sand prevalence. One label block per disk does not mean real blocks are independent; independence belongs to generated worlds under the declared model.
- SW-S patch support barely intersects the selected routes. This limits detection power and prevents generalising the small energy effect to unlabelled terrain.
- Disk geometry, presence, proxy scale, tight budget and both penalties are assumptions. The true missed-class energy penalty is unknown. First-pass label agreement and physical human traverses are unavailable.
- Candidate-route means include declined plans to make geometry/energy comparisons explicit. `accepted_goals` and row-level `accepted` must accompany those results; they must not be presented as executed-trip outcomes.
- A different spatial model could give different failures. Lowering a threshold or adding a generic uncertainty term is not justified by this study.

## What other pieces can use

- **JB (E8):** the label support and ambiguity must accompany downstream scenario claims. No change to #93 or the nominal sand product is proposed.
- **Claude (#16/#145, C3):** the summary contains script/data hashes, configurations, world counts, candidate acceptance, per-goal geometry and paired world differences. Preserve the declined-plan distinction when extracting rows.
- **Aaron/Diana:** the analysis uses your directed graph convention and existing station products; no graph/orienteering code is changed.

## Reproduce

In the existing scientific environment, from this branch's root:

```powershell
python -m pytest tests/fisica -q
python src/fisica/missed_sand.py --data C:/path/to/data --out data/robustness/c2 --worlds 30 --figure paper/figures/c2_fig1_missed_sand.png
```

Inputs: official base grid, E1 weights/feature rasters, E8 `sand.tif`, `points.csv` and `points_strata.json`, manual/E8 station GeoPackages. All inputs remain unchanged. A different local label snapshot is a different scenario-anchor dataset; compare its checksum.

## Outputs

`data/robustness/c2/{summary.json,worlds.jsonl,table.md}` (outside git); `paper/figures/c2_fig1_missed_sand.png`; new evaluator and tests. #120 remains open for the other blocks and broader validation.
