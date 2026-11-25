# E5 · Station selection and order (orienteering)

Owner: Diana (`@dianagrz`) · Issues: #9, #111, #119 · PRs: #37, #78, #83, #114 (time windows from the light), #131 (diagnosis and guarantee scope), #133 (diagnosis in `/plan` and the HUD) · Status: done (in `main` since #37: `/plan` plans the multi-station tour through `plan_tour`; DP up to 20 nodes, CP-SAT above; E8 stations v0 integrated; a v1 is not committed (JB, #9) and would only need a rerun; time windows now come from the light, #111; why there is no plan and the guarantee's scope, #119) · Last update: 2026-11-15

## Question
Given N science stations with a value, which subset should the astronaut visit, and in what order, to collect the most value without breaking the energy budget, the EVA duration, the stations' time windows or the walkback rule (always able to walk home)?

## Data
- **Terrain cost:** E3 directed edge costs (Sebas, `data/base/edges_e3.npz`): energy (J) and time (s) for the 8 moves of every 1 m cell, Santee (2001) metabolic power at Apollo speed ([E3 note](E3_metabolic_cost.md)). Loaded through E4's graph (Aaron, `src/grafos/graph.py`, [E4 note](E4_walkback.md)), with E3's defaults: no move steeper than 20°, no cell steeper than 30°.
- **Human cost (comparison):** E3 energy × E1's terrain factor of the arrival cell (`fisica.human_cost`), with the sand price of release `e1-sand-v1` (Juan, [E1 note](E1_maxent_irl.md)) on E8's `sand.tif` (release `e8-v0`, [E8 note](E8_boxwork_sand.md)). It is the cost `/plan` uses by default (`human_cost = true` in its request).
- **Stations:** the 13 manual stations of release `stations-v1` (Sebas, `data/stations/stations_manual.gpkg`, layer `stations`): 5 ridges, 5 hollows, 2 contacts and 1 Curiosity drill site, scored with the 5/4/4/3 rubric ([product note](product_api_hud.md)), 56 points in total. Every station has 10 min of service (`service_time_min`, a placeholder).
- **Habitat:** a user input (team decision, 2026-11-14). For this note it is the box centre, (8143537.99, −284463.58), the same illustrative choice as the E4 note.
- **E8 stations (separate run):** the 15 sand-rock contacts of release `stations-e8-v0` (JB, `data/stations/stations_e8.gpkg`, script `src/dl_boxwork/stations_e8.py`, [E8 note](E8_boxwork_sand.md)), all `type = contact`, scores 1–5 from hollow size and local hollow density, 20 min of service each. With the manual stations they make 28, beyond the DP; they are solved with OR-Tools and reported in their own section and files, so the DP results above them stay as they are.
- **Time windows (#111):** from the light, not from a file. The Sun (Mars24, the same as the 3D view and P6) and each station's terrain horizon from the 1 m DEM ([P6 note](P6_departure_time.md)), on sol 4711.

## Method
1. **Stations on the graph.** Each station falls in one 1 m cell; two stations in the same cell are merged. The habitat is placed with `Graph.place` like E4 and `/plan`: a blocked cell, or one outside the largest strongly connected component, is moved to the nearest valid cell. Stations outside that component are dropped, since the astronaut could not get back from them.
2. **Station matrices.** One Dijkstra per station (`scipy.sparse.csgraph`) gives the directed minimum-energy cost between every pair. The walking time of each pair is measured along that same minimum-energy leg, not the fastest one, so the solver's times match the route that is actually walked (`network.station_matrices`). The pair values are cached per graph, so a repeated plan with the same stations runs no Dijkstra.
3. **Service and waiting.** Working at a station costs `service_time × power`, with 205 W by default: E4's value, the top of the "low" band in [NASA-xEMU-met]. It was proposed as a shared value on #2 and never confirmed; `/plan` uses the same 205 W. It is paid on arrival at each station; the habitat is not served again on return. Waiting for a time window costs `wait time × wait power`, 0 W by default until the team agrees a value.
4. **Exact bitmask DP** [HeldKarp1962]. `dp[mask][i]` is the least energy to visit (and serve) the set `mask` ending at station `i`, built over masks in increasing order. Every set that can be closed within the budget is kept with its cheapest closing; the solution is the closable set with the most points, and among equal points the one using less energy. The order is rebuilt from parent pointers. Exact up to 20 nodes including the habitat. Prizes are summed per set, so the DP maximises total points [Vansteenwegen2011] [Gunawan2016].
5. **Time windows and maximum duration.** With two resources, one value per state is no longer enough: a route that spends more energy but arrives earlier can be the only one that still meets a later window. Each state then keeps its Pareto labels, the (energy, departure time) pairs no other label beats, as in resource-constrained shortest paths [Irnich2005]. Arriving before a window opens means waiting until it opens. With a waiting power `w`, label A dominates B when it leaves no later and `e_A + w·(t_B − t_A) ≤ e_B` (A could wait until B's time and still spend no more); with `w = 0` this is plain Pareto dominance. Without windows or a duration limit the single-value DP runs.
6. **Several rubrics at once.** Which station sets fit the limits does not depend on their scores, so `solve_many` builds the DP tables once and only repeats the choice of the best set for each rubric. The sensitivity analysis (step 9) uses it.
7. **Walkback.** After solving, the tour's full cell path is checked with E4's `check_walkback`, adding the service and waiting energy spent so far: at every cell, energy used + R(v) ≤ usable energy, where R(v) is the minimum energy to walk back to the habitat. If a tour fails, two repairs are tried breadth first, at most 5 extra solves: lower the budget by the deficit, or forbid the station of the first violation. The best feasible tour wins, so the result is never worse than lowering the budget alone (`safety.solve_with_walkback`).
8. **One shared rule set.** `problem.evaluate_route` applies these rules to any route. The DP, the brute-force solver, the tests and the outputs all use it.
9. **Rubric sensitivity**, as specified in `docs/research/station_value_rubric.md` (Sebas):
   - Scenarios S0 current (5/4/3/3), S1 recommended (5/4/4/3, the reference), S2 equal (1/1/1/1), S3 NASA-style (3/2/2/1), S4 contact first (4/4/5/3), S5 hollow = ridge (5/5/4/3), S6 wide contrast (9/4/4/1), for ridge/hollow/contact/Curiosity site.
   - S7: 500 random rubrics in [1, 5] that keep S1's order (ridge ≥ hollow and contact ≥ Curiosity site).
   - Each is solved at time budgets of 0.5–1.2 × the nominal duration, the time S1 needs to visit every station. Time is the budget swept because in this box time, not energy, binds (`docs/demo.md`); energy stays at 900 Wh usable. S1 is also solved with service times × 1.5, since SEXTANT's field validation found real traverses slower than planned (as cited in the rubric review).
   - Metrics against S1 at the same budget: Jaccard index of the visited stations, Kendall τ of the order of the stations both visit, and the fraction of the rubric's maximum score. The stability threshold is the smallest budget from which every fixed scenario and at least 95 % of S7 visit S1's set.
10. **Beyond 20 nodes: OR-Tools CP-SAT** [ORTools] (`solvers/cpsat.py`). An exact model: a Boolean per arc and per station, `AddCircuit` with a self-loop for every station that may be skipped, the energy budget as one linear constraint, and for time a start-of-service variable per station that each chosen arc pushes forward (service at the departure station plus the walk). Visited stations start within their window. Two details matter:
    - When the tour may stay at the habitat (the empty tour), staying forces every other station off. Otherwise the solver can close a loop through other stations that never touches the habitat.
    - With a maximum duration, the walking and service of the chosen arcs must also fit in it. This is redundant, since waits only add time, but it is linear. Without it CP-SAT could not prove the 28-station 120 min case within its time limit; with it the optimum is proven in 0.5 s.

    Costs are rounded up (energy to 10⁻⁶ of the budget, time to 1 ms) and limits down, so every tour the model accepts also holds exactly. A first phase maximises the points; a second, with the points fixed, minimises the energy (the DP's tie-break). The solver reports whether the optimum is proven and an upper bound on the points. `run.py --solver auto` and `/plan` (`plan_tour(solver="auto")`) use the DP up to 20 nodes and CP-SAT above. Waiting energy is not modelled in it.
11. **Tried and kept only for comparison: OR-Tools routing** (`solvers/routing.py`): the vehicle-routing library with one vehicle, each station a skippable node whose skipping costs its points, and guided local search. It finds the right tour on the real instances, but on random energy-only instances it misses the optimum in up to 6 of 10 cases, by up to 31 % of the points (`vs_dp_random`, 2 s per case). Its moves change one or two stations at a time, and a tight budget can need several swapped at once. Enabling the path and inactive-node LNS moves made it match the DP on the unit tests' small cases (2–7 nodes) but not on the larger ones.
12. **Windows DLL clash.** The pip build of OR-Tools and conda-forge's pyarrow (loaded by pandas 3) ship DLLs with the same names (abseil, protobuf); in one Python process whichever loads second fails. When pyarrow is installed on Windows, both OR-Tools solvers run in a fresh Python process that never imports pandas (about 0.2 s per solve).
13. **Time windows from the light** (#111, `src/orienteering/light_windows.py`). Each station is served only while it is in sunlight and out of the terrain's shadow:
    - For a departure t0, every station is sampled every minute after t0, up to the sol's local midnight (an EVA belongs to its sol), and each sample is dark, shadowed or sunlit by P6's rule (`departure.light_state`) with the station's own horizon (1.7 m eye height, searched to 400 m).
    - The sunlit samples form stretches. The station's window is the longest stretch with room for its service, as [start, end − service] in seconds after t0, because the work must be done in the light too. The DP takes one window per station, so a station lit, shadowed and lit again keeps only its longest stretch. A station with no stretch long enough is dropped for that departure.
    - The resulting OPTW is solved with the same solver (DP up to 20 nodes, CP-SAT above), for every departure from 05:00 to 19:00 every 15 min. The recommended departure has the most points; ties go as in P6: the larger sunlit share of the walk, then the higher lowest Sun, then the earliest.
    - Walking between stations is not limited by the light; its sunlit share is reported. Waiting for a window costs 0 W by default, and also 205 W (the service power) as an upper bound until a resting power is agreed with Sebas (E3 has none).
    - `run.py --light-sol 4711` sweeps the departures, plans the best one and writes it as usual (walkback check and route GeoPackage).
14. **Why there is no tour** (#119, A4; `src/orienteering/diagnose.py`). `plan_tour` raises the same exceptions as before (a `ValueError` for bad input, E4's `NoFeasibleRoute` when nothing fits), and each now carries a structured `.diagnosis` with a `code`, whether it is `exact`, and a one-line `message`:
    - `invalid_input`: the field at fault (`stations`, `start`, `stations[i]` outside the study box).
    - `unreachable`: no station has a walkable path from the habitat and back.
    - `insufficient_resources`: no station fits even on its own (habitat > station > habitat). Any tour that visits a station walks at least those two legs and does its service, so this is a proof that no tour exists, not a guess. It names the station closest to fitting, the resources it is short of (energy, O2, duration), what it needs and what is available, and what would let that station fit (for energy: the budget it needs at the request's margin). The actions are worded for that station only: raising a budget does not promise a larger tour.
    - `search_incomplete`: some station fits alone but CP-SAT stopped at its 30 s limit without a tour; this is not a proof, so `exact` is false.
    - `walkback`: every re-planned tour still fails the walkback; it gives the vertex, the deficit in Wh and the number of re-plans. It is set on the route (`diagnosis`) and `api/tour.py` already refuses such a tour.
    - Energy and O2 shortfalls are exact on the graph (the legs are the least-energy paths). A duration shortfall is flagged `exact = false`: E5 times each leg along its least-energy path and does not search for a faster, costlier one.
    - For a tour that leaves stations out, `info["skipped_reasons"]` says, per station, whether it does not fit even alone (and why) or fits alone but not together with the chosen ones.
    - `/plan` returns the diagnosis as `diagnosis` beside the 422's text `detail`, and the HUD words it for the user (#119).
    - The route also reports its smallest return margin (`min_slack_wh`) and the vertex where it occurs (`min_slack_index`), service and waiting included (#119, A5).
15. **Tried and dropped:**
    - The first DP pruned a state whenever going straight to the end was already over budget. That is only valid when the cost matrix satisfies the triangle inequality. Dijkstra matrices do, but the random test matrices did not, and the DP disagreed with brute force on some of them. It now prunes only on the energy already spent.
    - Splitting each station's service cost into half on its incoming and half on its outgoing edges, a common way to turn station costs into edge costs, was considered and dropped. It gives the same totals here but wrong partial totals, which the walkback and windows need.
    - Caching each station's whole Dijkstra result (about 48 MB per station) was dropped for caching only the station-to-station values.
    - Windows looked for 16 h after the departure reached the next sol's sunrise, so a tour with no duration limit could wait through the night for a station's morning light. Windows now end at the sol's local midnight.

## Results
All numbers come from `src/orienteering/paper_figures.py` → `data/e5/summary.json` (habitat at the box centre, 1000 Wh budget, 10 % margin, so 900 Wh usable, 205 W service, plain E3 cost unless stated).

- **Matrices:** 14 nodes (13 stations and the habitat), all inside the main component. The 14 Dijkstras take 8.53 s and R(v) 1.30 s. Leg energies range from 1.2 to 133.8 Wh (median 30.4 Wh). The cost from i to j divided by the cost from j to i has percentiles 5/50/95 of 0.625 / 1.0 / 1.599, so the order of a tour matters.
- **Nominal tour:** all 13 stations, 56 of 56 points, order habitat > C1 > Q1 > H3 > H1 > C2 > R0 > H0 > R4 > H4 > R1 > H2 > R2 > R3 > habitat.

  | | Energy | Time |
  |---|---|---|
  | Walking | 279.4 Wh | 50.9 min |
  | Service | 444.2 Wh | 130.0 min |
  | Total | 723.6 Wh | 180.9 min |

  2,252 m over 1,842 cells. The DP takes 0.08 s. Walkback holds with a minimum slack of 176.4 Wh and no re-plans. Service, not walking, is most of the cost (61 % of the energy, 72 % of the time).
- **With a 120 min limit:** 8 stations and 37 points (66 % of the maximum): habitat > R3 > R2 > H2 > H4 > H0 > R0 > R4 > R1 > habitat, in 111.4 min and 445.1 Wh. Time, not energy, is the binding limit. The DP with Pareto labels takes 0.23 s.
- **Human cost:** leg energies rise by up to 3.5 % (ratio 1.0–1.0348 to plain E3). The nominal tour visits the same 13 stations (726.3 Wh, 2.7 Wh more) and the 120 min tour the same 8 (447.5 Wh), in a different order for the nominal one. The sand price does not change which stations are chosen.
- **Prize against budget** (Figure 2): counting service, the planner needs 750 Wh of usable energy to visit all 13 stations; walking alone would need 300 Wh. At 450 Wh it collects 37 points with service against 56 without. Ignoring service would overstate what an EVA can do by a wide margin.
- **Rubric sensitivity** (Figure 4, nominal duration 180.9 min):

  | Time budget / nominal | 0.5 | 0.6 | 0.7 | 0.8 | 0.9 | ≥ 1.0 |
  |---|---|---|---|---|---|---|
  | Stations S1 visits | 5 | 7 | 9 | 10 | 12 | 13 |
  | Station sets tied at S1's best score | 1 | 15 | 3 | 9 | 1 | 1 |
  | S7 rubrics choosing S1's set | 100 % | 45 % | 53 % | 0 % | 93 % | 100 % |
  | Jaccard vs S1: S0 / S2 / S4 / S5 | 1 / 0.25 / 0.25 / 0.43 | 1 / 0.75 / 0.56 / 0.75 | 1 / 0.8 / 0.8 / 1 | 0.82 for all four | 1 for all | 1 for all |

  S3 and S6 match S1's set at every budget. The visited set stops depending on the rubric from **1.0 × the nominal duration** (`stable_from_fraction`); at 0.9 every fixed scenario agrees and 93 % of S7. Where S7 agrees least (0.6, 0.7, 0.8), S1's integer scores tie: several station sets reach S1's best score (15, 3 and 9) and energy decides between them, while random scores never tie. So the disagreement there is between equally good sets for S1, not a different judgement. With service times × 1.5, S1 keeps only 36–88 % of its maximum score across the sweep and never matches the nominal set (Jaccard 0.67–0.85). From 0.7 × the nominal duration upwards, that change of the service estimate moves the visited set more than any fixed rubric does; only at 0.5 (S2, S4 and S5) and 0.6 (S4) does a fixed rubric move it more.
- **DP runtime** (Figure 3, worst case where every station fits, so every state is reachable):

  | N (with habitat) | 8 | 10 | 12 | 14 | 16 | 18 | 20 |
  |---|---|---|---|---|---|---|---|
  | Energy only (s) | 0.0005 | 0.0027 | 0.015 | 0.10 | 0.46 | 2.28 | 10.8 |
  | Time windows (s) | 0.0018 | 0.017 | 0.081 | 0.66 | 1.26 | 6.26 | – |

  The fast DP grows about 5× per two stations, as 2ⁿ·n² predicts. With windows it stays under 6.3 s up to 18 nodes. The 14 real nodes solve in under 0.25 s, so a run is dominated by the 8.5 s of Dijkstras, which the cache removes on repeated plans.

![E5 tour](../figures/e5_fig1_tour_map.png)
*Figure 1. E5 tours over the hillshade. Left: nominal (900 Wh usable), all 13 stations. Right: 120 min limit, 8 stations. Filled circles are visited, open circles skipped; small numbers give the visiting order.*

![Prize against budget](../figures/e5_fig2_prize_vs_budget.png)
*Figure 2. Points collected against usable energy, with and without the service energy (205 W, 10 min per station).*

![DP runtime](../figures/e5_fig3_dp_runtime.png)
*Figure 3. DP time against the number of nodes, with everything within budget. Random Euclidean instances; one run per N.*

![Rubric sensitivity](../figures/e5_fig4_rubric_sensitivity.png)
*Figure 4. Left: overlap (Jaccard) of each scenario's visited stations with S1's, the share of 500 random order-preserving rubrics that pick S1's set, and S1 with service times × 1.5. Right: fraction of each rubric's maximum score. Time budget as a fraction of the 180.9 min S1 needs for all stations.*

## Results with the E8 stations (OR-Tools, 28 stations)
Kept apart from the DP results above. All numbers come from `src/orienteering/paper_ortools.py` → `data/e5/summary_ortools.json`, with the same habitat, budget, margin and service power, plain E3 cost.

- **Instance:** 13 manual and 15 E8 stations. E8-02 and E8-08 are outside the main connected component, so 26 stations and the habitat remain (27 nodes). The 27 Dijkstras take 16.5 s. Maximum points: 56 manual + 23.26 E8 = 79.26. E8 stations carry 20 min of service each, so all 26 would need 390 min of service alone (130 manual + 260 E8).
- **Nominal (900 Wh usable, no time limit):** 60.47 points, proven optimal by CP-SAT in 0.3 s. It visits all 13 manual stations (56 points) and two E8 contacts, E8-05 and E8-04 (4.47 points), at the end of the tour near the ridges: habitat > C1 > Q1 > H3 > R3 > R2 > H2 > H4 > H1 > C2 > R0 > H0 > R4 > R1 > E8-05 > E8-04 > habitat.

  | | DP, 13 manual stations | CP-SAT, 26 stations |
  |---|---|---|
  | Points | 56 | 60.47 |
  | Energy (walking + service) | 723.6 Wh | 872.0 Wh (291.2 + 580.8) |
  | Duration | 180.9 min | 222.9 min |
  | Walkback minimum slack | 176.4 Wh | 28.0 Wh |

  2,341 m over 1,911 cells; walkback holds with no re-plans. Energy is now the binding limit: 872.0 of 900 Wh, 148.4 Wh more than the DP's manual-only tour for 4.47 more points.
- **With a 120 min limit:** 37 points, proven optimal in 0.5 s: the same 8 manual stations and order as the DP (445.1 Wh, 111.4 min). No E8 station enters: each costs 20 min of service, twice a manual station's.
- **OR-Tools against the DP** (the DP is exact up to 20 nodes):
  - On the 14-node manual instance, CP-SAT (0.06 s and 0.2 s) and the routing heuristic (10 s) both return the DP's stations and energy, nominal and 120 min.
  - On random instances (generator of `paper_figures.py`, 10 per size and kind): CP-SAT matches the DP's points on 60/60 and proves the optimum on all of them, in at most 0.25 s.

    | Nodes | 12 | 16 | 20 |
    |---|---|---|---|
    | Routing heuristic (2 s), energy only: same points as the DP | 7/10 | 6/10 | 4/10 |
    | Its largest loss | 20 % | 19 % | 31 % |
    | Routing heuristic, time windows: same points | 10/10 | 10/10 | 10/10 |

  - On the 26 stations the routing heuristic finds the optimal points in 1 s in both cases, and the optimal energy after 5 s (nominal) and 15 s (120 min).

![E5 tours with E8 stations](../figures/e5_fig5_ortools_28.png)
*Figure 5. CP-SAT tours over the 13 manual (circles) and 13 reachable E8 stations (squares). Left: nominal, 900 Wh usable. Right: 120 min limit. Filled markers are visited, open ones skipped; small numbers give the visiting order.*

## Results with time windows from the light (#111)
Numbers from `src/orienteering/paper_light_windows.py` → `data/e5/light_windows.json` (13 manual stations, the same habitat, budget and service as above, plain E3 cost, sol 4711).

- **Every station spends part of the daylight in a terrain shadow:** from 15 min (Q1) to 89 min (H1) of the sol's daylight (06:02–17:58 local true solar time), all of it within 2 h of sunrise or sunset; at midday every station is lit. So the windows bind only for early and late departures.

| Tour | Ignoring the light | Full points for departures | Best departure | At 15:00 | At 16:00 | At 17:00 |
|---|---|---|---|---|---|---|
| Nominal (no time limit) | 56 | 05:00–14:45 | 10:30 | 53 | 37 | 10 |
| 120 min limit | 37 | 06:00–16:00 | 11:00 | 37 | 37 | 10 |

- **Leaving between 05:00 and 14:45** the nominal tour still collects all 56 points, every station worked in sunlight; the best departure is 10:30, with the whole walk sunlit and the lowest Sun at 65.3°. **Later, the evening shadows take stations away:** 53 points at 15:00, 37 at 16:00, nothing from 17:45. Ignoring the light, the plan would claim 56 points at every departure.
- **The light changes the choice of stations, not only the departure time.** At 06:00 the 120 min tour still collects 37 points but with a different set (Jaccard 0.78 against the set chosen ignoring the light): it goes H1 > R0 > H0 > R4 > R1 > H2 > R2 > R3, taking H1 instead of H4. Leaving at 06:00, the stations come out of the morning shadow 4 to 51 min after departure (Q1 first, R1 last), and H1 is lit after 20 min. Leaving at 16:00, the last possible start of service is 39 min (H1) to 98 min (Q1) after departure, so the nominal tour serves only 8 stations, in an order the windows force: R1 > R4 > R0 > H0 > H4 > H2 > R2 > R3 (37 points). At 05:00 the 120 min tour keeps only 12 points: waiting for the light uses its time limit.
- **Waiting cost.** With waiting at 205 W, an upper bound, the points are the same from 05:15 on (the order changes for departures from 05:15 to 06:15, to wait less); leaving at 05:00 the nominal tour drops to 52 points, because waiting for sunrise is no longer free. The 120 min tour's points do not change.
- **Consistency with P6:** at the recommended departures the share of the service time in sunlight is 1.0 for both tours, and the best departures are those of P6 (10:30 and 11:00).
- **Speed:** each OPTW solves in at most 0.56 s (14 nodes, DP with Pareto labels). The full sweep of 57 departures takes 50–75 s, most of it scoring the light along the walk of the departures that tie at full points (about 1 s each, for the tie-break).

![Time windows from the light](../figures/e5_fig6_light_windows.png)
*Figure 6. Left: points collected against the departure time on sol 4711 with time windows from the light (solid), and ignoring the light (dashed); dots mark the recommended departure. Right: overlap (Jaccard) of the stations chosen with the light and ignoring it. Waiting costs 0 W.*

## Diagnosis and the scope of the guarantee (#119)
Numbers from `src/orienteering/paper_diagnosis.py` → `data/e5/diagnosis.json`. The scenario is written in the file: habitat at the box centre, the 13 manual stations, the plain E3 graph, margin 0.1, service at 205 W, O2 as energy / 20.1 kJ/L, the automatic solver, and `plan_tour` as `/plan` calls it. The script plans for energy budgets of 1000, 600, 300, 100 and 40 Wh, each with no duration limit and with 120, 60 and 20 min.

- **Every one of the 16 tours found passes the walkback and is a proven optimum** (DP). On each, the smallest return margin along the line equals the energy left on arriving home. It is first reached on the way home after the last stop: the margin never shrinks below that before. The smallest is 3.6 Wh, for 600 Wh with no duration limit, not the smallest budget (300 Wh keeps 19.9 Wh and 100 Wh keeps 33.6 Wh) (44 points, 10 stations); the nominal tour keeps 176.4 Wh.
- **At 40 Wh no tour exists, and the diagnosis says why:** `insufficient_resources`, exact, short of energy. The closest station is C1, which alone needs 56.4 Wh against 36.0 Wh usable. The advice is a budget of at least 62.8 Wh at margin 0.1 (56.448 / 0.9 = 62.72, rounded up so the printed minimum always fits). The check plans again just above the exact need, at 62.78 Wh (62.72 × 1.001, `advice_check`), and gets the tour to C1 (4 points) with 0.06 Wh to spare, so the printed 62.8 Wh fits too.
- **With an O2 budget of 1 L** the limit is O2 (C1 needs 10.11 L). **With 5 min** it is the duration (C1 needs 13.95 min), flagged as an estimate. **A station 5 km east** of the habitat is rejected as `invalid_input` on `stations[13]`.
- **Skipped stations:** with a 20 min limit, the tour visits C1 and Q1 is left out although it fits alone; the 11 others do not fit even alone. At 1000 Wh and 120 min, the 5 stations left out all fit alone, but not together with the 8 chosen ones.
- **What the guarantee covers.** A tour from `/plan` holds, at every vertex of its line, energy used (walking, service and waiting) + R(v) ≤ usable energy, and its totals respect the duration and O2 limits. This is conditional on the model and its data: E3's energy and time on the 1 m DEM (no rocks below its resolution), the service placeholder (10 min, 205 W), and O2 as a transformation of energy, not an independent resource with its own consumption or leaks. It does not cover uncertainty in those costs (#101 learns a factor on E3's cost while walking; #120). Nor does it cover a time-to-return rule along the way: the duration is checked on the whole tour, and a contingency return limit belongs to the walkback and the guide (#119, A2).

## Checks
- **Brute force.** The DP matches exhaustive enumeration of every ordered subset on 500 random instances of 2–7 nodes with asymmetric costs and random start and end: 100/100 with energy only, with service, with time windows, with a maximum duration, and with windows plus a waiting cost (`dp_vs_brute`). The random windows and limits are tight enough to change the best answer in many of those cases.
- **OR-Tools against the DP:** see the results section above (`vs_dp_manual_14`, `vs_dp_random`); every CP-SAT tour is re-checked with `evaluate_route` before it is returned.
- **Unit tests:** `pytest tests/orienteering` passes 742 tests (E6's metaheuristics, P6, the light windows and the diagnosis included). Besides the brute-force cases, they cover:
  - `solve_many` against separate solves and brute force, for several rubrics at once
  - a named toy problem with a known optimum: 10 stations on a circle around the habitat, where the best tour is a run of neighbours of predictable length and energy
  - service changing which stations are picked, waiting energy changing them too, and the habitat served once
  - a window that forces the order, an unreachable window, and a slower but cheaper label that must survive
  - time measured along the minimum-energy leg, directed costs, and the matrix cache (no new search for repeated stations; callers can't alter it)
  - a blocked station detoured or moved; walkback failing at the right stop; both re-plan repairs
  - the route GeoPackage read back, and `plan_tour` with the real `/plan` request model
  - both OR-Tools solvers against the DP on 30 small random instances each (CP-SAT also proves each optimum), windows, a maximum duration, unreachable legs, and CP-SAT on 30 stations on a circle (beyond the DP) with a known optimum
  - reading the manual and E8 files together without repeated ids or cells, and `plan_tour` switching to CP-SAT for 21 stations
  - the diagnosis (#119): the code, resource and closest station for energy, O2 and duration shortfalls; raising the budget as advised makes the station fit; input errors name the field; a CP-SAT timeout is not reported as "nothing fits"; unreachable stations; reasons for skipped stations; the smallest margin and its vertex
  - time windows from the light: light profiles to windows (the longest stretch with room for the service; stations without one dropped), a hand-made instance where an afternoon shadow fixes the order, the DP against brute force on 60 random instances with windows made from random light profiles, and, on the real terrain, every stop worked in sunlight at 06:00, 11:00 and 16:00 (P6's rule, sampled every 30 s), the morning shadows changing the stations and the evening ones the order
- **Same cost as `/plan`:** with `human=True`, E5's station matrix equals the one built by `api.planner.graph(base, 30.0, human=True)` (maximum relative difference 0.0 on the 13 stations).
- **`/plan` integration:** in `main`, `/plan` delegates to `plan_tour` (#64) and refuses a tour that still fails the walkback after the re-plans (#68). The tour and plan tests of `tests/api` pass (24 tests), unchanged by the diagnosis: its exceptions are subclasses of the ones `/plan` already catches.
- **Route against solver:** the energy of the written route, recomputed cell by cell with E4's `Graph.path_cost`, equals the solver's energy.
- **Visual check** (Figure 1): the routes pass through every visited station in the reported order, and stay off the steep scarp in the south-west of the map.

## Limitations
- **Station values are a rubric, not measurements**, and points add up: two Curiosity sites (3 + 3) outweigh one ridge (5). The sensitivity analysis shows the choice of stations does not depend on the rubric once the time budget covers all stations, and that below it S1's own ties are as large an effect as changing the rubric.
- **Service is a placeholder:** 10 min per station and 205 W are not agreed values (proposed on #2, never confirmed). Service is most of the cost, and from 0.7 × the nominal duration upwards 1.5 × the service time changes the plan more than any fixed rubric does.
- **Time windows come from the light only.** No source gives other windows (operations, temperature); REMS has only each sol's minimum and maximum temperature, not the hour. The light is geometry: no dust, no refraction, no rocks below the 1 m DEM's resolution (as in P6). One window per station: a station lit, shadowed and lit again keeps only its longest stretch. Walking in the shadow or the dark between stations is allowed and reported, not forbidden. Waiting at 205 W is an upper bound, not an agreed resting power.
- **Pareto labels can grow** with many binding windows. Measured up to 18 nodes with random windows (6.3 s); denser binding windows could be slower; CP-SAT is the fallback.
- **Walkback never binds for round trips.** For a tour that starts and ends at the habitat and fits the budget, R(v) is never more than the rest of the planned tour, so the check always passes. It only matters for routes that end elsewhere. It covers energy only, not return time; the HUD shows the 30 min return separately. On the 16 real tours of the diagnosis section the smallest margin is always the one on arriving home.
- **Costs come from the DEM-based E3 model**, with the same limits as E4: no rocks (E9), and the DEM does not resolve the boxwork ridges ([base grid note](base_grid.md)). The human cost adds only sand, and it does not change the chosen stations here.
- **The sensitivity uses one habitat** (the box centre) and the 13 manual stations; the tie pattern depends on both.
- **E8 scores are not on the rubric's scale.** They grow with hollow size and hollow density (1–5, continuous), while the manual stations use the 5/4/4/3 rubric, so adding them mixes two scales. With 20 min of service each, E8 adds 4.47 points to the nominal tour and none under 120 min. The HUD makes the other choice: its *Load E8 contact stations* button (#79) scores them by the rubric as contacts (4 points), so a `/plan` tour over the 28 stations is not this section's tour ([product note](product_api_hud.md)).
- **The diagnosis explains the first reason only.** When no station fits alone it is exact. When some fit alone but the solver finds no tour, which only CP-SAT's time limit can cause, it says so and does not guess. `/plan` passes it on as `diagnosis` next to the text `detail` of its 422, and the HUD shows it in its *No plan* message (#119, [product note](product_api_hud.md)).
- **No radio constraint.** E11 ([E11 note](E11_comms.md)) finds stretches of a tour without a direct radio link to the habitat. E5 does not limit them; the team left that for after the hackathon (#76).
- **CP-SAT has no waiting energy** and is only exact up to the rounding (costs up, limits down; 10⁻⁶ of the budget, 1 ms). It was proven optimal on every instance here, but a larger or harder instance could hit its time limit; it then returns its best tour, the bound and `optimal = false`.

## What other pieces can use
- **API/HUD (Sebas):** `/plan` delegates the multi-station tour to `tour.plan_tour(req, graph)` (#64). It applies the energy, duration and `o2_budget_l` limits, re-plans on a walkback failure, and switches to CP-SAT above 19 stations (output `method = "cpsat"`, `exact` true only if the optimum is proven, `gap` from the bound). Its signature and output keys are kept stable. Since #119 it adds `min_slack_wh`, `min_slack_index` and `diagnosis` to the route, `skipped_reasons` and `diagnosis` to `info`, and a `.diagnosis` dict on its exceptions, for structured `/plan` errors and HUD actions. `api/tour.py` keeps a fallback on E5's primitives (`Stations`, `station_matrices`, `Problem`, `SOLVERS["dp"]`, `route_path`), so those names stay stable too. `station_matrices` caches pairs, so repeated `/plan` requests with the same stations skip the Dijkstras. The HUD can add the E8 stations to a plan (#79).
- **Rubric (Sebas):** the sensitivity results answer the proposal in `docs/research/station_value_rubric.md`: stable from the full-tour budget, and the contact/hollow tie of S1 is what makes it ambiguous below.
- **E4 and baselines (Aaron):** the station matrices and `evaluate_route` can score any visiting order, including the baselines.
- **E12 (Juan):** the route GeoPackage (`data/e5/e5_route.gpkg`, layers `route` and `stops`) and the `/plan` output have arrival and departure times per stop for the dose timeline.
- **E8 (JB):** `stations_e8.gpkg` is read together with the manual stations (`read_station_files`, `run.py --stations A B`). Two of the 15 are unreachable from the habitat's component, and only two are worth their 20 min of service in the nominal tour.
- **E11 (JB):** a limit on the minutes without radio would enter E5 as one more additive resource per leg, like the duration, or need no E5 change at all if the graph prices the cells without radio (#76).
- **P6 and the HUD (Sebas):** `light_windows.sweep` gives, for each departure, the points, the stations and their windows; the HUD could show the station windows next to the *Best time to leave* line (issue #111, optional, Sebas's files).
- **E6 (Diana):** the benchmark of the exact solvers against four metaheuristics (ILS, simulated annealing, ant colony system and a genetic algorithm) is in the [E6 note](E6_benchmark.md): at E5's sizes the exact solvers are as fast and always right.

## Reproduce
```powershell
gh release download base-grid-v2 --dir data; Expand-Archive data\base_grid_v2.zip data\base -Force; Remove-Item data\base_grid_v2.zip
gh release download stations-v1 --dir data/stations
gh release download stations-e8-v0 --dir data/stations
gh release download e8-v0 --dir data\e8; Expand-Archive data\e8\e8_v0.zip data\e8 -Force
gh release download e1-sand-v1 --dir data\e1; Expand-Archive data\e1\e1_sand_v1.zip data\e1 -Force
python src/fisica/build_cost_layers.py data/base/dem_1m.tif data/base --slope-raster data/base/slope_deg.tif   # optional, ~3 s
python src/orienteering/run.py --habitat 8143537.99 -284463.58
python src/orienteering/run.py --habitat 8143537.99 -284463.58 --max-duration-min 120 --human-cost
python src/orienteering/paper_figures.py
python src/orienteering/run.py --habitat 8143537.99 -284463.58 --stations data/stations/stations_manual.gpkg data/stations/stations_e8.gpkg
python src/orienteering/paper_ortools.py
python src/orienteering/run.py --habitat 8143537.99 -284463.58 --light-sol 4711
python src/orienteering/paper_light_windows.py   # about 4 min
python src/orienteering/paper_diagnosis.py       # about 1 min
python -m pytest tests/orienteering
```

## Outputs
- `data/e5/e5_route.gpkg` (from `run.py`): layers `route` and `stops`, CRS of the DEM, with the cost model used.
- `data/e5/summary.json` (from `paper_figures.py`, about 70 s).
- `paper/figures/e5_fig1_tour_map.png`, `e5_fig2_prize_vs_budget.png`, `e5_fig3_dp_runtime.png`, `e5_fig4_rubric_sensitivity.png`.
- With the E8 stations, separately: `data/e5/summary_ortools.json`, `data/e5/e5_route_ortools_28.gpkg` and `e5_route_ortools_28_120min.gpkg` (from `paper_ortools.py`, about 4 min, most of it the routing heuristic's comparison runs), `paper/figures/e5_fig5_ortools_28.png`.
- Time windows from the light: `data/e5/light_windows.json` (from `paper_light_windows.py`), `paper/figures/e5_fig6_light_windows.png`.
- Diagnosis and guarantee scope: `data/e5/diagnosis.json` (from `paper_diagnosis.py`).

`data/` is not in git; regenerate with the commands above.
