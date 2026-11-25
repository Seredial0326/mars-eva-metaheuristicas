<!-- Owner: JB assembles from every note's Limitations · Sources: all notes · Status: drafted from the notes by JB's Claude; owner to confirm -->

## 5. Discussion

**What the validation shows.** The walkback guarantee and the tour are exact on the model's costs, and the comparison with simple rules is made on the same graph, so the false-safe rates measure the rules, not noise. The guarantee is exact only on the model and its data: it does not cover uncertainty in E3's costs, the service placeholder or O2 beyond its equivalence with energy. Curiosity's traverse tests something narrower. DEM features separate the valleys the drivers chose from the rest of the box (AUC 0.73), but within the boxwork they do not explain the path, which also followed science targets, operations and features the DEM does not resolve. Between given start and goal points, orthophoto sand is the only learned price that holds out of sample.

**Reproducibility.** Every number reported by the team is in one registry (`results/registry.csv`, 68 figures from 17 pieces at the time of writing). Each row records what the figure is computed over, its kind (observation, model, simulation or check), the script, output file and field it comes from, the commit, the input data version and the output's checksum, and each was confirmed by its owner. A checker reads every figure back from its output file and verifies that the documents print the same number. The table in `results/results_table.md` is generated from that registry, not edited by hand.

**Negative results.** Learned DEM prices are zero or near zero at every scale, and none beats distance alone on held-out drives (E1). Boxwork ridges could not be mapped reliably from weak labels (E8). A boulder price did not hold out of sample (E1 with E9). A Gaussian process on boulder cover is no more accurate than a 20 m smoothing (X1). THEMIS night infrared at 81 m does not see the sand. We keep these results because they tell the next team where the signal is not.

**Limitations.**
- **Metabolic model.** Santee (2001) with Mars gravity is an extrapolation, not validated for a suited astronaut on Mars, and O2 is a metabolic equivalent, not a tank reading.
- **Orbital data.** The 1 m DEM is coarser than its posting. The sand map finds about 1 in 9 sand pixels. Boulders below about 1 m are invisible, BoulderNet misses about 4 in 10 labelled boulders on Mars, and no label exists in Gale. The boulder uncertainty (X1) covers interpolation, not that undercount.
- **Learned price.** The sand price measures how much Curiosity's drivers avoided sand; applying it to an astronaut is an assumption.
- **Simulation.** Radio is pure line of sight. The dose covers one habitat and E5's two tours, and the storm replay uses the one weak SEP in the RAD window (1.9×). The adaptive walkback is validated in simulation only. Its 90 % interval is overconfident when consumption errors are correlated in time, so k_p90 is a margin, not a guarantee.
- **Scope.** Station values encode an expert ranking, not measurements, and service time and power are placeholders. Everything is one 2 × 2 km box and, for most numbers, one habitat.

**Future work.** A filter that handles correlated errors, and an evaluation under uncertainty of the joint energy, time and O2 check that the way home and the rejoin now make (#119; C1 in #120 evaluated energy only). Robustness to DEM errors (E7). A planning cost for time without radio. A larger area with a two-level grid (rover between zones, walking within them).
