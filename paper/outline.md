# Paper outline (draft)

Working title: *Planning astronaut EVAs in the Gale crater boxwork, validated against Curiosity's traverse.*

Each section lists the notes in `notes/` that feed it. Owners fill their notes; the outline is assembled at the end.

## Abstract
One paragraph, written last.

## 1. Introduction
Why EVA planning on Mars needs terrain-aware, energy-aware routes; the boxwork as a science target; what we contribute (planner, learned cost, walkback guarantee, orienteering of stations, validation with a real rover traverse).

## 2. Study area and data
- Gale crater boxwork, 2 × 2 km bbox, CRS and grid → *base grid note*
- DEM, orthophotos, terrain features → *base grid note*
- Curiosity's traverse (PLACES) → [E2](notes/E2_curiosity_traverse.md)
- Other datasets used (REMS, RAD, BoulderNet, AI4Mars) → notes of E12, [E9](notes/E9_boulders.md), E10

## 3. Methods
- 3.1 Base grid and terrain features → *base grid note*
- 3.2 Curiosity's traverse on the grid and terrain-only baseline → [E2](notes/E2_curiosity_traverse.md)
- 3.3 Learned terrain cost (MaxEnt IRL) → *E1 note*
- 3.4 Metabolic and O2 cost under Mars gravity → [E3](notes/E3_metabolic_cost.md)
- 3.5 Graph, return-energy layer R(v) and walkback routes → [E4](notes/E4_walkback.md)
- 3.6 Station selection (orienteering) → [E5](notes/E5_orienteering.md)
- 3.7 Boxwork ridges and hollows (top-hat, U-Net) → *E8 note*
- 3.8 Boulder density (BoulderNet teacher distilled to a light CNN) and its uncertainty (GP on 20 m blocks, X1) → [E9](notes/E9_boulders.md)
- 3.9 Radiation dose along the EVA timeline → *E12 note*
- 3.10 Product: API and HUD; manual stations and their rubric; guide mode shared by the arm tablet and the 3D rehearsal; context data (REMS, CRISM/OMEGA, THEMIS) and radio (E11) in the UI → [product](notes/product_api_hud.md)
- 3.11 Best time to leave (Sun and terrain shadows along the planned EVA) → [P6](notes/P6_departure_time.md)

## 4. Results
- MVP route versus the three baselines, on E3 and on the human cost: at a 50 % budget the baselines call 22–46 % of their "safe" goals wrongly, the MVP none; sand adds about 1 point, slope drives the failures → [E4](notes/E4_walkback.md) (section Baselines), *E5 note, results table*
- How well terrain and learned costs explain Curiosity's route → [E2](notes/E2_curiosity_traverse.md), *E1 note*
- Second-priority layers (E8, E9, E12) and their effect on the plan. For E9: a 0.93 M-parameter student reproduces BoulderNet's density (r = 0.66, calibrated) 42 times faster but finds single boulders poorly (F1 0.27 against 0.66); pricing boulders halves the boulder area crossed for +0.06 % energy → [E9](notes/E9_boulders.md)
- Boulder uncertainty (X1): a GP's mean is no better than a 20 m smoothing, its 90 % intervals are calibrated overall (92–93 %) but narrow on rocky blocks (~80 %); pricing mean + 1.645 std cuts the boulder area crossed by 56 % for < 1 % energy → [E9](notes/E9_boulders.md) (section Uncertainty layer)
- The 30 min red line against fixed-radius rules (about a third of the circle is falsely safe) → [product](notes/product_api_hud.md), *E4 note*
- What binds in the box: time, not energy; the rubric decides only when time is short; radio line of sight leaves about 41 % of a 120 min tour without direct radio → [product](notes/product_api_hud.md), [E3](notes/E3_metabolic_cost.md), *E5 and E11 notes*

- Every planned tour keeps its walkback, and a refusal says why (#119): 16 tours pass the walkback and are proven optima; at 40 Wh the diagnosis names the shortfall and the advised budget (62.8 Wh) fits → [E5](notes/E5_orienteering.md)
- Light changes which stations are visited, not only when to leave (#111): full points for departures 05:00–14:45, none from 17:45; a different set at 06:00 → [E5](notes/E5_orienteering.md), [P6](notes/P6_departure_time.md)
- The way home and the rejoin checked on one path for energy, time and O2 (#151) → [product](notes/product_api_hud.md)
- Adaptive walkback in simulation (X2) and the paired evaluation C1 → [X2](notes/X2_adaptive_walkback.md), [C1](notes/C1_eva_robustness.md)

## 5. Discussion
What the validation does and does not show; limitations collected from every note; future work. Negative results to keep: E1 finds no held-out price for boulders (#108), and the GP adds no accuracy over a simple smoothing (X1); no boulder term enters the nominal cost.

## 6. Conclusions

## References
`references.md`
