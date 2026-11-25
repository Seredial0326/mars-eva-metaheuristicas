# Station rewards in orienteering and planetary traverse planning

Scope: how planetary rover and astronaut science-planning studies assign reward ("science value") to targets and stations; whether integer priority scales are used; whether reward sensitivity is analysed; how the generic orienteering (OP) literature treats scores. Goal: material to defend a simple integer rubric (5/4/3/3) for a Mars EVA orienteering planner.

Method note: about 20 tool calls. Several NASA/JPL PDFs could not be rendered by the fetch tool; the text of Smith (ICAPS 2004) and Estlin et al. (ICRA 2008 workshop) was pulled out of the raw PDFs with a stdlib script, so quotes from those two are verbatim. Broddrick et al. (LPSC 2024) details come from the NTRS record page, not the PDF, which failed to extract.

## Q1. How do planetary rover/astronaut science-planning papers define target reward or "science value"?

### Takeaway
There are four families: (a) values elicited from scientists and given to the planner as fixed numbers or priority classes (Smith 2004, OASIS/CASPER, the NASA lunar EVA "Science Yield" tool, the JETT3 station lists); (b) similarity to a scientist-specified feature "signature" (OASIS, AEGIS); (c) novelty or representativeness relative to data already collected (OASIS); (d) information-theoretic value from a probabilistic map, such as entropy reduction or classification confidence (Candela, Thompson, Wettergreen at CMU). Learned reward maps (inverse RL) are a fifth, less common route. For crewed EVA planning the documented practice is (a): a science team ranks stations or objectives.

### Cited Findings
- **Smith 2004 (NASA Ames, ICAPS):** frames Mars rover science planning as over-subscription: "there are a large number of possible goals of differing value, and the planning system must choose a subset that can be accomplished within the limited time and resources available." Goal values are inputs: each goal becomes an orienteering node "with reward equal to that of the goal g". The paper does not derive the values; they are taken as given, which implies they come from the scientists ("many science targets that the planetary geologists would like to visit"). — [Smith, Choosing Objectives in Over-Subscription Planning, ICAPS 2004](https://icaps04.icaps-conference.org/icapspapers/ICAPS04SmithD.pdf) (also [NTRS 20040015108](https://ntrs.nasa.gov/citations/20040015108))
- **Smith 2004, why order matters:** greedy selection "in descending order of their importance or priority" works when cost does not depend on order, but "this assumption does not hold for a Mars rover ... there is a significant cost in moving from one target to the next, and that cost depends on the distance and terrain between the two targets." — [Smith 2004](https://icaps04.icaps-conference.org/icapspapers/ICAPS04SmithD.pdf)
- **OASIS (JPL):** prioritises data "based on criteria set by the science team" using three algorithms: target signature, novelty, and representative sampling. Target signature "enables scientists to efficiently and easily stipulate the value and importance to give each particular feature. Rocks are then prioritized as a function of the distance of their extracted feature vector from the specified weighted feature vector." Novelty ranks highly "rocks that are dissimilar from any rocks seen previously." — [Estlin et al., Autonomous Science for Mars Rovers, ICRA 2008 Planetary Rovers workshop](https://ewh.ieee.org/conf/icra/2008/workshops/PlanetaryRovers/09Estlin/Estlin%20paper_ICRA%20wkshp%202008%20Final.pdf); see also [Castaño et al., OASIS, J. Field Robotics 2007](https://ai.jpl.nasa.gov/public/papers/castano-jfr07-oasis.pdf) (link now redirects; not read)
- **OASIS/CASPER planning:** "Science alerts can also contain priorities, which are representative of their scientific value." The planner resolves resource conflicts "by deleting a low-priority science activity to ensure that enough time remains to execute a later, high-priority science activity". Hardware tests covered "multiple, prioritized science targets, limited time and resources". — [Estlin et al. 2008](https://ewh.ieee.org/conf/icra/2008/workshops/PlanetaryRovers/09Estlin/Estlin%20paper_ICRA%20wkshp%202008%20Final.pdf)
- **AEGIS (Curiosity, Perseverance):** picks targets that best match "parameters specified by mission scientists" (for example rock type by colour, shape and size). It extracts features (size, shape, intensity, orientation, range), filters, and ranks candidates. Reported first-year preferred-target rate above 93%, against about 24% for blind targeting. The exact ranking formula was not found. — [JPL AEGIS project page](https://ai.jpl.nasa.gov/public/projects/aegis); [JPL news 2017](https://www.jpl.nasa.gov/news/nasa-mars-rover-can-choose-laser-targets-on-its-own); [Francis et al., i-SAIRAS 2024](https://ai.jpl.nasa.gov/public/documents/papers/francis-isairas-2024.pdf) (not read in full)
- **Lunar EVA "Science Yield" (NASA, LPSC 2024):** a mixed integer linear programming tool for the Science Evaluation Room (SER). It is built from the Science Traceability Matrix (STM) and the SER's priority scheme, under duration, traverse speed and distance limits. Each crew action's relevance to an STM objective is scored High = 3, Medium = 2, Low = 1. Each STM objective's priority is also High = 3, Medium = 2, Low = 1. Relevance is multiplied by priority and summed into a global Science Yield. Proof of concept: 3 objectives, 4 stations, 4 actions, solved in under a minute, including a mid-EVA replan. — [Broddrick et al., An Optimization Approach to Support Science Decision Making for Lunar Surface Exploration, LPSC 2024, NTRS 20240000165](https://ntrs.nasa.gov/citations/20240000165)
- **JETT3 Artemis analog:** four science subteams proposed preferred stations, which were merged into one prioritised station list. That list then shaped the initial EVA traverses. — [Young et al., NTRS 20230003806 poster](https://ntrs.nasa.gov/api/citations/20230003806/downloads/Young.theintegration.poster.pdf) (from search snippet)
- **Information-theoretic value (CMU):** the "science hypothesis map" holds scientists' hypotheses and updates as the robot measures. Information-gain path planning beat science-blind baselines when mapping geologic units at Cuprite, NV. — [Candela, Thompson, Noe Dobrea, Wettergreen, IROS 2017](https://www.ri.cmu.edu/publications/planetary-robotic-exploration-driven-by-science-hypotheses-for-geologic-mapping). A related planner uses projected entropy reduction (Multi-Heuristic A*). — [Gautam et al., Science-Aware Exploration Using Entropy-Based Planning, IROS 2017](https://www.ri.cmu.edu/publications/science-aware-exploration-using-entropy-based-planning). See also [Non-myopic Planetary Exploration Combining In Situ and Remote Measurements, arXiv 1904.12255](https://ar5iv.labs.arxiv.org/html/1904.12255).
- **Science value plus risk:** science value comes from the rover's confidence in its mineral-composition estimates, fused with a terrain-traversability risk model. Tested on Mars data and on the Zoë rover. — [Candela et al., IEEE RA-L 2022, DOI 10.1109/LRA.2022.3191949](https://www.eurekalert.org/news-releases/968980)
- **Learned reward maps:** a CNN learns per-cell reward from demonstrations, and value iteration turns it into a planning value map. — [Pflueger, Agha-mohammadi, Sukhatme, Rover-IRL, RA-L 2019](https://sites.google.com/view/rover-irl/home)
- **Unknown or stochastic rewards:** OP in structured environments with time limits and initially unknown rewards, using bandit ideas. — [Korein, CMU-RI thesis 2021](https://www.ri.cmu.edu/app/uploads/2021/08/KoreinThesisFinal.pdf)
- **Apollo precedent:** EVA energy budgets were split among overhead, science and locomotion, with trade studies between distance travelled and number of science stops. — [NTRS 19700009560](https://ntrs.nasa.gov/api/citations/19700009560/downloads/19700009560.pdf) (from search snippet)

### Inferences
- For crewed EVA with a handful of hand-picked stations, the closest precedent is expert-assigned ordinal priorities turned into numbers (NASA SER Science Yield, JETT3). Data-driven value (information gain, novelty) suits autonomous rovers that see many candidate targets online. A 5/4/3/3 rubric belongs to the expert-scoring family.
- The project's E8 boxwork layers (top-hat / U-Net) could serve as a map-based prior (family d) that justifies which stations get the top score, but the literature found does not use such a prior for EVA station scores.

### Gaps
- Full text of Castaño et al. JFR 2007 and of the AEGIS ranking formulas (redirect or failed fetch).
- No MSL or M2020 strategic route-planning paper was found that publishes a numeric science-value scheme for waypoints. Not searched in depth.
- The Broddrick et al. PDF did not extract, so details come from the NTRS record summary.

## Q2. Are integer priority scales common? Are reward ratios discussed?

### Takeaway
Yes, for human-in-the-loop planning: the NASA lunar EVA tool uses 3/2/1 (High/Med/Low), multiplied across relevance and objective priority, and OASIS/CASPER use discrete goal priorities. No source found explicitly discusses ratios such as "one high-value target versus two medium". The only ratio argument available is implicit in additive OP objectives.

### Cited Findings
- 3/2/1 integer scale for action relevance and for objective priority, combined multiplicatively (products range 1 to 9) and summed. The weightings "can be adjusted by the SER as desired." — [Broddrick et al., LPSC 2024](https://ntrs.nasa.gov/citations/20240000165)
- OASIS/CASPER attach "priorities" to science alerts and goals and delete low-priority activities first. — [Estlin et al. 2008](https://ewh.ieee.org/conf/icra/2008/workshops/PlanetaryRovers/09Estlin/Estlin%20paper_ICRA%20wkshp%202008%20Final.pdf)
- Classic OP formulation: each vertex has a score, and the path, under a length limit, maximises the total collected score. Scores are inputs to the problem. — [Vansteenwegen, Souffriau, Van Oudheusden, The orienteering problem: a survey, EJOR 209(1):1-10, 2011](https://econpapers.repec.org/RePEc:eee:ejores:v:209:y:2011:i:1:p:1-10); updated by [Gunawan, Lau, Vansteenwegen, Orienteering Problem: a survey of recent variants, solution approaches and applications, EJOR 255(2):315-332, 2016](https://econpapers.repec.org/RePEc:eee:ejores:v:255:y:2016:i:2:p:315-332)

### Inferences
- Because OP sums scores, a 5/4/3/3 rubric fixes trade-offs: one 5-station is worth less than two 3-stations (5 < 6), and a 4 plus a 3 (7) beats a 5. The team should state this explicitly, as it is the "ratio" decision the rubric makes. A 3/2/1 scale (NASA) makes one High equal to one Medium plus one Low.
- With the multiplicative NASA scheme, a High-relevance action on a High-priority objective is worth 9 times a Low/Low one. This is a much wider spread than 5:3. Either convention has published precedent only for the 3/2/1 form.

### Gaps
- Not verified (training knowledge only, needs checking): standard OP benchmarks such as Tsiligirides (1984) and Chao, Golden and Wasil (1996) use small integer scores, and Fischetti, Salazar-González and Toth (1998) generated profits as all-equal (1), pseudo-random, or distance-correlated. A search did not confirm the generation scheme ([Fischetti et al., INFORMS JoC 10(2):133-148, 1998](https://pubsonline.informs.org/doi/references/10.1287/ijoc.10.2.133)).
- No planetary paper was found that discusses "one high versus two medium" explicitly.

## Q3. Do studies run sensitivity analysis on rewards, and what do they conclude?

### Takeaway
Formal reward-sensitivity analyses are rare in this literature. What exists is: reordering priorities changes the optimal route (NASA lunar tool); guided OP-based selection beats greedy priority ordering by 10-30% when goals are sparse, with the gap closing as resources grow (Smith 2004); and risk-attitude sweeps (CMU, GORADRO). Robust-OP research focuses on uncertain travel costs, not uncertain scores.

### Cited Findings
- Changing the STM objective priority order produced a different optimal route. In the replanning case, extending the EVA to 66 min made the original station more valuable than the replacement. No formal sensitivity analysis is described. — [Broddrick et al., LPSC 2024](https://ntrs.nasa.gov/citations/20240000165)
- Smith 2004 experiments (25 rocks in a 50×50 area): orienteering guidance gave "improvements averaging from 10% to 30% depending on the density of goals. When the field is rich in goals, greedy approaches tend to work reasonably well. But when the goals are widely scattered, or there are many intermediate waypoints with no reward, the choice of goals and goal order can make a large difference in net reward". As "resources become plentiful, the greedy solutions catch up to the orienteering solutions." — [Smith 2004](https://icaps04.icaps-conference.org/icapspapers/ICAPS04SmithD.pdf)
- Simulated missions at several risk levels measured science return; even at high risk "there were still plenty of areas for the rover to explore". This is a sweep of the risk weight, not of science values. — [Candela et al. RA-L 2022 (press release)](https://www.eurekalert.org/news-releases/968980)
- A risk-attitude parameter ζ trades scientific return against terrain hazard in a reward potential. — [Mimlitz, GORADRO slides, Colorado Space Grant](https://www.colorado.edu/center/spacegrant/sites/default/files/attached-files/16_GoalOrientedRiskMitigatingAutonomousBehaviorForExtraterrestrialRovers_Mimlitz_Presentation.pdf)
- Robust and stochastic OP work mostly treats uncertain weights (travel times). Stochastic node scores are mentioned as a variant but are not the focus. — [Shang et al., Two-stage robust optimization for the OP with stochastic weights, Complexity 2020](https://doaj.org/article/d6210037e5cf415582199216a071cb70); [Evers et al., robust vs stochastic OP, Erasmus report 2012](https://repub.eur.nl/pub/37193)

### Inferences
- A defensible sensitivity test for the team: perturb the rubric (for example 5/4/3/3 to 3/2/1/1, to all equal at 1, to ±1 on each station, or to a wider 9/4/1-style spread) and report whether the selected station set and order change under the O2 and time budget. The literature suggests that rankings matter most when the budget is tight and stations are scattered (Smith 2004) and matter little when the budget covers almost all stations.
- If the route is unchanged across plausible perturbations, that is the strongest argument that the integer rubric is not driving the result. If it changes, report the threshold (as Broddrick et al. did with the 66-minute case).

### Gaps
- No paper found that runs a systematic reward-perturbation study for planetary orienteering.
- Robust OP with uncertain profits (prize-collecting, chance-constrained) was not searched in depth.

## Q4. Standard OP references: how are scores treated, and is there guidance on eliciting them?

### Takeaway
The OP surveys define scores as given problem data and offer no elicitation guidance. Elicitation in the planetary setting is done by science teams (STM and SER priorities, merged station lists, scientist-defined signatures).

### Cited Findings
- OP definition: a set of vertices each with a score; find a path within a length or time limit that maximises total score. Scores are exogenous. — [Vansteenwegen et al. 2011](https://econpapers.repec.org/RePEc:eee:ejores:v:209:y:2011:i:1:p:1-10); [Gunawan et al. 2016](https://econpapers.repec.org/RePEc:eee:ejores:v:255:y:2016:i:2:p:315-332); [arXiv 2512.16865 survey 2025](https://arxiv.org/html/2512.16865v1)
- Benchmark lineage: Tsiligirides' 21, 32 and 33-node sets, later corrected and extended by Chao et al. (1996). — [Chao/Tsiligirides lineage, NYCU repository](https://ir.lib.nycu.edu.tw/bitstream/11536/57279/1/350801.pdf) (from snippet); [OPLIB](https://www.smu.edu.sg/sites/default/files/archives/unicen/unicen.smu.edu.sg/node/386.html)
- Planetary elicitation: STM objectives ranked by the SER ([Broddrick et al. 2024](https://ntrs.nasa.gov/citations/20240000165)); subteam station proposals merged into one prioritised list ([JETT3 poster](https://ntrs.nasa.gov/api/citations/20230003806/downloads/Young.theintegration.poster.pdf)); scientist-weighted feature vectors ([Estlin et al. 2008](https://ewh.ieee.org/conf/icra/2008/workshops/PlanetaryRovers/09Estlin/Estlin%20paper_ICRA%20wkshp%202008%20Final.pdf)).

### Inferences
- The team can say that OP theory treats scores as inputs, that NASA's own EVA optimisation prototype uses a coarse integer expert scale (3/2/1) that the science room can adjust, and that its rubric follows the same practice, backed by a sensitivity check. Tying each score level to a written criterion (for example, linking it to STM-style objectives such as boxwork ridge or vein exposure) would mirror the STM-relevance step.

### Gaps
- I did not open the Vansteenwegen 2011 or Gunawan 2016 full texts. The claim that they give no elicitation guidance rests on their problem definitions and general knowledge of the papers.
- I found no decision-analysis literature (for example AHP or swing weighting) applied to planetary station scoring.
