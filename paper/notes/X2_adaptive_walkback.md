# X2 · Adaptive (Bayesian) walkback

Owner: JB (`@JavierBonilla2004`) · Issues: #101, part of #45 (P6); follow-up experiment in #120 (C1) · PRs: #113 (backend, simulation, note), #116 (guide), #118 (3D rehearsal bias), #160 (3D meter, alert and card rows) · Status: done · Last update: 2026-11-15

## Question
The walkback reserve (E4) trusts a fixed metabolic model (Santee 2001, E3). Measured metabolic rates in prototype suits reached up to twice Apollo's, and in Apollo 17 the return distance was recomputed from the real consumption during the EVA. Can the planner learn during the walk how much this astronaut really uses, and re-check the way home with that? And is that safer than the fixed reserve?

## Data
- **Plan:** E4's live round trip from the box centre to the best-scoring saved station R0 (`api.planner.plan`; same request as the E11 figure). It is 1,331 m long and takes 40.0 min. E3 predicts 199.75 Wh, about 35.8 L of metabolic O2 (`data/adaptive/summary.json → plan`).
- **Observed use:** none exists. Every "observed" value here is **simulated**.

## Method
1. **Model.** Real use = k × E3's predicted use, with one factor k for the whole EVA (suit, fitness, load, terrain the model misses). O2 is E / 20.1 kJ/L, so the same k applies to energy and to O2.
2. **Filter** (`src/fisica/adaptive_k.py`). Prior log k ~ N(0, 0.3²), i.e. k within about ±35 %. Each walked segment gives y = log(observed / predicted) = log k + ε, with ε ~ N(0, σ_obs²) and σ_obs = 0.15. A normal prior with a normal likelihood is conjugate: precisions add, so the posterior stays normal and the update is closed form. k is lognormal, with quantiles exp(μ + z_q σ).
3. **Reserve.** A uniform k scales every E3 arc by the same factor, so the cheapest way home does not change: the reserve is exactly k × R(v). It needs no new Dijkstra. The 30 min line does not change either, because k is metabolic and does not change speed. The reserve uses the **90th percentile** k_p90, not the mean. The alert fires when used + k_p90 × R(v) > budget ("return now").
4. **API.**
   - `POST /walkback/update` is stateless: segment → posterior, k median, mean, p90 and IC90, reserve, `return_now`, and the point of no return on the rest of the plan, at k_p90 and at k = 1.
   - `/walkback` and `/guide/return_home` take an optional `k`. The default 1.0 gives exactly today's output.
5. **Simulation** (`src/fisica/adaptive_sim.py`):
   - **Walks:** k_true ∈ {0.8, 1.0, 1.2, 1.5}, 300 walks each, fixed seeds. Every 30 m segment uses k_true × E3 × lognormal noise (σ = 0.15).
   - **Decision:** after every segment, each policy checks whether it can walk the **next** segment and still get home: used + k (E3 next segment + R(next point)) ≤ budget. Fixed uses k = 1; adaptive uses k_p90. If not, it turns back along R(v)'s path at the real cost, with per-segment noise as well.
   - **Budget:** 1.25 × the plan's predicted energy (249.7 Wh). In this 2 × 2 km box the real suit budget never binds (E4 note), so a tight budget is needed for the question to mean anything.
   - **Tried and fixed:**
     - Checking only at the end of each segment let both policies overshoot at the station stop. The stop charges its whole service time (about 38 Wh) to one segment.
     - One noise draw for the whole walk home overstated its noise compared with the filter's own model.

## Results
Source: `src/fisica/adaptive_sim.py` → `data/adaptive/summary.json`, figure [x2_fig1_adaptive_k.png](../figures/x2_fig1_adaptive_k.png).

| k_true | Policy | Ran out of O2 | Turned back | Plan done (mean) | O2 left, median (p5) |
|---|---|---|---|---|---|
| 0.8 | fixed / adaptive | 0 % / 0 % | 0 % / 0 % | 100 % / 100 % | 15.9 (14.0) L, same |
| 1.0 | fixed / adaptive | 0 % / 0 % | 0 % / 0 % | 100 % / 100 % | 8.7 (6.3) L, same |
| 1.2 | fixed | 15.7 % | 15.7 % | 97.9 % | 1.4 (−0.9) L |
| 1.2 | adaptive | 7.7 % | 46.0 % | 77.5 % | 2.4 (−0.2) L |
| 1.5 | fixed | **90.0 %** | 100 % | 51.2 % | −7.7 (−11.7) L |
| 1.5 | adaptive | **4.7 %** | 100 % | 48.2 % | 2.0 (0.05) L |

- **Does the fixed reserve run out with k_true = 1.5?** Yes, in 90 % of the walks. It turns back on time by its own count, but its count of the way home is 1.5 times too low. The adaptive reserve runs out in 4.7 %, and those are small overshoots (p5 margin +0.05 L).
- **Does the adaptive reserve turn back too early with k_true = 0.8?** No. Both policies finish the plan in every walk, with the same margin, because with a low k the alarm never comes close. The price of caution shows at k_true = 1.2: the adaptive policy turns back in 46 % of the walks and completes 77.5 % of the plan on average, against 97.9 % for the fixed one, which in exchange runs out of O2 twice as often (15.7 % against 7.7 %).
- **How fast does it learn?** These are medians over 300 walks of the number of 30 m segments until the IC90 contains k_true and is narrower than 0.2:
  - k_true 0.8: 4 segments;
  - k_true 1.0: 6;
  - k_true 1.2: 9;
  - k_true 1.5: 14.

  It never reached that in 0–0.7 % of the walks. The far k_true takes longer because the prior pulls towards 1.
- **IC90 coverage** at the end of the walk: 88.0 %, 91.3 %, 90.0 % and 91.0 % for k_true 0.8, 1.0, 1.2 and 1.5.

## Checks
- `tests/fisica/test_adaptive_k.py`:
  - the update equals the conjugate formula;
  - the result does not depend on the order of the segments;
  - segments with zero use carry no information.
- **Known bias in the same tests:** for k_true ∈ {0.8, 1.0, 1.2, 1.5} the IC90 after 30 segments contains k_true and is narrower than 0.2. Over 2,000 walks of 20 segments, IC90 coverage stays within 87–93 % for every k_true.
- `tests/api/test_walkback_update.py`:
  - the prior alone gives the prior's p90;
  - 25 segments at 1.5× recover k ≈ 1.5;
  - `return_now` fires when the k_p90 return does not fit but the fixed one does;
  - the point of no return is found on a toy plan;
  - R(v) taken from a position matches `/walkback`;
  - litres = Wh × 3.6 / 20.1;
  - with k = 1, `/walkback` and `/guide/return_home` give exactly today's output. With k = 1.5 the return energy scales by 1.5 while time and path do not change.

## Limitations
- **Validated in simulation only, not with astronauts.** The data come from the same model the filter assumes (one constant k, lognormal noise), so the results show that the method is consistent, not that it is right for a real suit.
- **There is no measured O2.** We do not predict metabolism from physiological sensors (heart rate, CO2) that we do not have. In a real suit the observation would come from PLSS O2 or from a heart-rate-based estimate, each with its own error.
- **One k for the whole EVA.** Fatigue, cooling or terrain the model misses change k during the walk, and a constant-k filter would lag behind those changes.
- σ_obs = 0.15 and the prior σ0 = 0.3 are declared assumptions.
- The budget is artificial (1.25 × the plan) because the box is too small for the real suit budget to bind.
- One plan and one habitat.
- Not yet done (follow-up in #120, C1): a third, "conservative" policy (a fixed reserve margin), paired differences with intervals, and correlated noise between segments (here segments are independent).
- The residual run-outs of the adaptive policy (4.7–7.7 %) come from noise near zero margin. A higher quantile (p95) or a fixed reserve on top of k_p90 would cut them, at the cost of turning back earlier.

## What other pieces can use
- **Guide (tablet, #116).** `web/guide_core.js` (section "adaptive walkback") calls `POST /walkback/update` every 30 m walked, sending back the `posterior` it returned. The real use is simulated from a `k_true` chosen in the demo drawer ("Use ×1.0 / 1.2 / 1.5 / 0.8"). `web/guide.html` shows:
  - a "Spare energy, learned use (k p90)" meter with `k.median` and `k.ci90`;
  - the "RETURN NOW" alert in `#alert`, with voice;
  - four rows in "plan against the walk": k with its IC90, the real energy, and where "return now" fires at k_p90 and at k = 1.

  The alert only shows with a tight budget (about 1.25 × the plan's energy), because the box never uses up 900 Wh.
- **3D rehearsal (#118).** `buildRehearsal(route, points, {kTrue})` adds `used_real_wh` to each state and exposes `bias.segments` (predicted vs observed per 30 m) for the same endpoint. Without the option the rehearsal is unchanged (`?check=rehearse` identical to main). **#160 adds the k meter ("Spare energy at your pace"), the RETURN NOW alert, the "Use ×k" demo button and the 4 card rows to the 3D rehearsal.** They use the same `guide_core` functions as the tablet, including its simulated use per 30 m (`adaptiveStep`), so both views say the same; `model.bias` from #118 stays available but is not used, so the noise is drawn once. The rehearsal asks the server only while playing, and not when the checks turn it off, so `?check=rehearse` is unchanged.
- **E4 (Aaron):** k is a uniform scale on the energy field. For any R(v) it is k × R(v) with the same paths.

## Reproduce
```bash
python -m pytest tests/fisica/test_adaptive_k.py tests/api/test_walkback_update.py -q
python src/fisica/adaptive_sim.py --runs 300
```
Inputs: `data/base`, `data/stations` and optionally `data/e1` (human cost).

## Outputs
`data/adaptive/summary.json` (local); `paper/figures/x2_fig1_adaptive_k.png`.
