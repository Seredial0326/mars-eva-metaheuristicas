# How human planetary EVA campaigns and analogs prioritise science stations

Scope note: ~17 tool calls. PMC pages for the BASALT papers were blocked by a bot check, so the full texts were read through the Europe PMC full-text API (same articles, same PMCIDs). One NTRS PDF (Desert RATS 2010 science ops, citation 20130014887) returned an unrelated article and was **not** used. Nothing below is an invented numeric scale. Where a source gives no numbers, these notes say so.

## Q1. Apollo traverse planning (Apollo 15-17): did stations have priority tiers?

### Takeaway
Apollo planning used **ordinal priorities, prime vs. alternate stations, and an order for deleting stations under time pressure**. It did not use numeric science scores. Priorities were set at three levels: terrain/objective (e.g. Apollo 17 target units in decreasing priority), station (a "highest priority traverse station"; prime vs. "real time alternate"; low-priority stops dropped first) and task within a station (an ordered list of sample types).

### Cited Findings
- Apollo 17 target terrains were listed **in decreasing priority: highlands, dark mantle, subfloor material**. The same source notes that a geologist-astronaut (Schmitt) was "intimately involved in all stages of planning and mission operation." — [NTRS 19930009614 (Apollo 17 geology summary, Muehlberger)](https://ntrs.nasa.gov/api/citations/19930009614/downloads/19930009614.pdf) (seen through a search snippet; full PDF not read)
- The Apollo 17 Lunar Surface Procedures Vol. 2 has a section on "experiment priorities and traverse planning criteria." Its detailed objectives include "documented sample collection at highest priority traverse station." — [A17 Final Lunar Surface Procedures Vol. 2](https://pds-geosciences.wustl.edu/Lunar/urn-nasa-pds-apollodoc/document_a17/mission/a17_final_lunar_surface_procedures_vol2_contingency.pdf) (search snippet; the PDF was over the 10 MB fetch limit)
- Prime vs. alternate stations: "EVA 3: Station 10 has been eliminated in favor of station 10b. This possibility was discussed in the previous edition as a real time alternate, but subsequent discussions have led to the decision to select 10b as the prime station." — [Apollo 17 Traverse Planning Data (MSC), ALSJ](https://www.nasa.gov/wp-content/uploads/static/history/alsj/a17/A17TraversePlanningData.pdf) (search snippet). The book was compiled with input from the Field Geology Experiment Team, the Science and Applications Directorate and the EVA Planning Branch.
- Apollo 15: "Science planners had decided to shorten the traverse somewhat... A low-priority sampling stop had been tentatively deleted and the route at the foot of Hadley Delta curtailed." Plans for the second traverse "could well be changed in light of what had been accomplished." — [NASA SP-4214, *Where No Man Has Gone Before*, ch. 13-4](https://www.nasa.gov/wp-content/uploads/static/history/SP-4214/ch13-4.html)
- Task-level priorities within a station: the Apollo 15 Station 8 checklist lists tasks "in priority order": comprehensive sample area, then double core tube, then documented samples of the large crater. — [A15 LSP Station 8 procedures checklist](https://www.nasa.gov/wp-content/uploads/static/history/alsj/a15/a15lsp_Station8_Proc_Checklists.pdf) (search snippet)
- Apollo 17 Station 1 sampling priorities: blocks (with any soil on them) first, rake soil second, double core third. — [ALSJ Apollo 17 Station 1](https://www.nasa.gov/history/alsj/a17/a17.sta1.html) (search snippet; a direct fetch returned only the banner page)
- Station-by-station geology results for Apollo 17 are in USGS Professional Paper 1080 (Wolfe, Bailey, Lucchitta, Muehlberger, Scott, Sutton, Wilshire). — [USGS PP 1080](https://pubs.usgs.gov/pp/1080/report.pdf)

### Inferences
- The Apollo pattern is a **ranked list plus a deletion order**: the lowest-value stops are cut first when the timeline slips. That fits an orienteering formulation in which station value decides what is dropped under a time or O2 budget. It supports *relative* values (ridge > hollow > contact) more than the absolute numbers.
- Units were ranked by the science questions each could answer (highlands > dark mantle > subfloor). This is a precedent for giving geomorphic units different base values, as the team's ridge/hollow split does.

### Gaps
- No Apollo source found gives numeric station scores. The Traverse Planning Data book and the Surface Procedures volumes were not read in full (size limit), so the full station priority list and deletion order are unverified.
- No source found on how the Apollo Field Geology Team (Muehlberger, Swann) resolved disagreements among scientists when ranking stations.

## Q2. BASALT, Desert RATS, NEEMO, RATS, Minerva: how were stations and samples ranked? Any numeric scales?

### Takeaway
BASALT, the best-documented case, used **ordinal rankings, not scores**. Before the EVAs, stations were chosen against a Science Traceability Matrix (STM) to span a gradient of alteration types and to be representative and widely distributed. During EVAs, candidate samples were ranked on a **"dynamic leaderboard"**: an ordered list with written justifications, built by consensus of the science team, with deadlocks broken by a Science Lead. None of the papers read uses a "priority 1-3" numeric scale. Message headers did carry "SCIENCE SURVEY PRIORITY" and "SCIENCE SAMPLING PRIORITY" labels.

### Cited Findings
**Minerva / BASALT, Marquez et al. 2019**, *Astrobiology* 19(3):440-461, doi:10.1089/ast.2018.1838 — [PMC6442304](https://pmc.ncbi.nlm.nih.gov/articles/PMC6442304)
- The science team had two decisions to convey to the crew: "(1) where to conduct presampling survey and (2) where to sample."
- The Science Support Team "methodically determined a set of priority sampling sites, ranked in a leaderboard." The leaderboard was "periodically updated by the SST with rankings and justifications as new scientific information arrived."
- Mission Briefs set each EVA's priorities, "balanced across the competing scientific aims of the various scientists."
- Message headers "SCIENCE SURVEY PRIORITY" and "SCIENCE SAMPLING PRIORITY". High-priority messages were visually flagged in the Mission Log.
- During planning, the SST "finalized traverses to specific locations that met their science objectives." The exact sampling spot was chosen during execution.
- No numeric scale is described. The scientific criteria are deferred to Stevens et al. 2019.

**Stevens et al. 2019, "Tactical Scientific Decision-Making during Crewed Astrobiology Mars Missions"**, *Astrobiology* 19(3):369-386, doi:10.1089/ast.2018.1837 — [PMC6442282](https://pmc.ncbi.nlm.nih.gov/articles/PMC6442282) (read through the [Europe PMC full text](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6442282/fullTextXML))
- The leaderboard was a spreadsheet that let the Mission Support Center (MSC) "place the candidates in a priority order." It "represented the MSC preferences on a moment-by-moment basis." Each entry carried a description, reasoning tied to the EVA objectives, and images.
- Only the top 3-5 candidates were sent to the crew. "Not all candidates were given a priority, if they were deemed not to meet the EVA's science objectives." In one figure, a candidate was given "very low priority", which left a gap at position 8. The scheme is ordinal, with a "does not qualify" category.
- The criterion was fit to the objectives: whether a candidate matched "one of the alteration conditions required by the science objectives," and whether it was a better or worse example of that condition.
- How the judgment was elicited: the MSC "was frequently queried to ensure consensus was made among the various scientific experts." The Biology and Geology Leads reported to a Science Lead, who could "break any deadlocks." The Science Lead's style "depended heavily on the personality of the person in the role," with no appreciable difference in outcome reported.
- Weighting of evidence: "The MSC placed a high weight on the opinions of the EV crew where given." Crew confidence and handheld-instrument geochemistry "were key in how the MSC prioritized the candidates."
- The presampling priority was not the same as the sampling priority. The MSC favoured candidates it "most wanted scanned with the scientific instruments."

**Brady et al. 2019, "Strategic Planning Insights for Future Science-Driven Extravehicular Activity on Mars"**, *Astrobiology* 19(3):347-368, doi:10.1089/ast.2018.1850 — [PMC6442241](https://www.ncbi.nlm.nih.gov/pmc/articles/PMC6442241/) (read through the [Europe PMC full text](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6442241/fullTextXML), first half only)
- STM columns: "First-order question," "Specific objectives and questions," "What do we want to know?," "Associated hypotheses," "Proposed 2016 priorities and science tasks."
- Regions were chosen for "(1) accessibility and safety, (2) scientific interest, and (3) potential for communications coverage."
- Stations "represent alteration types and features targeted in the objectives and hypotheses outlined in the STM." Multispectral imagery was used "to select a variety of stations that represented a gradient of alteration ranging from high to low." Aerial imagery alone was judged insufficient.
- At HVNP, more than 65 candidate stations were cut to about 30 by "removal of redundant locations," "iterative discussions regarding confidence in the interpretation of alteration features," and choosing "stations with representatives of each alteration feature that were widely distributed across the geographic region." At COTM about 25 stations were chosen, with bright tones assumed to mean high alteration and dark tones unaltered basalt.
- Objectives were ordered: "Hot, active fumaroles were considered by the scientists to represent a high-priority science target," so those EVAs were scheduled early. Within an EVA, the first two stations addressed the primary objective and "the third station represented the secondary objective."
- Process: weekly teleconferences with "extensive discussion and input from all scientists." Station selection was "a collaborative effort among SST members via teleconference and synchronous use of xGDS."

**Desert RATS 2010**
- Traverse planning began about 12 months before the field test. It went from photogeologic maps of the test area to "prioritized science objectives and candidate sites." Operational constraints combined with those objectives produced 24 traverses for 12 field days and two rovers. — [The traverse planning process for D-RATS 2010, Acta Astronautica 90 (2013) 254, ADS](https://ui.adsabs.harvard.edu/abs/2013AcAau..90..254H/abstract) (search snippet; the ADS page returned HTTP 405)
- 164 samples were collected over 21 simulated EVAs for one rover, each EVA at a different science station. — [Gruener et al., LPS XLII, via NTRS](https://ntrs.nasa.gov/api/citations/20110008009/downloads/20110008009.pdf) (search snippet)

### Inferences
- **No analog program read here published a numeric station-value scale.** A 5/4/3/3 rubric therefore has no direct precedent. It can be presented as a **cardinal encoding of the ordinal, objective-based ranking** these programs used (STM objective, then the station's fit to it, then its rank). It should be labelled as the team's own expert judgment, as BASALT did.
- The BASALT criteria that map onto the boxwork rubric:
  - "represents a target feature named in the objectives" maps to ridge and hollow as the primary targets;
  - "gradient/variety" and "representatives of each feature... widely distributed" map to diversity and contact stations;
  - "removal of redundant locations" maps to penalising or not stacking value for nearby duplicate stations;
  - primary vs. secondary objective ordering (2 stations primary, 1 secondary) maps to ridge/hollow > contact/rover point.

### Gaps
- No primary source was found on how NEEMO or the original RATS rovers ranked stations or samples. They were not searched in depth for lack of budget.
- The second half of Brady et al. and the last ~9% of Stevens et al. were not read. They may contain more criteria, e.g. on contacts.
- The Desert RATS 2010 science operations paper (Hörz, Eppler et al., Acta Astronautica 2013) was not read. The NTRS PDF link returned an unrelated article.

## Q3. How did MIT SEXTANT and other traverse planners represent the science value of a site?

### Takeaway
According to the abstract, SEXTANT does **not** model per-site science value. It optimises the path between **user-specified Activity Points** by distance, time or metabolic energy, with walkback, thermal-load and solar-power analyses. Choosing and prioritising sites is left to humans.

### Cited Findings
- SEXTANT (Johnson 2010, MIT SM thesis, advisors Hoffman and Newman) "computes the most efficient path between user-specified Activity Points," with efficiency measured as "the path distance, time, or the explorer's energy consumption." It computes walkback paths and thermal and solar loads from shadow data. Its stated aim is to support "scientific return" together with productivity and safety, and it has no site-scoring mechanism. — [DSpace@MIT 1721.1/59560](https://dspace.mit.edu/handle/1721.1/59560)
- A field evaluation found actual traverse time significantly longer than predicted, while distance did not differ significantly. — [DSpace@MIT 1721.1/81322 / 81410 records](https://dspace.mit.edu/handle/1721.1/81322)
- Norheim (2018, MIT) ported SEXTANT to Python and integrated it with NASA Ames xGDS. — [MIT thesis record](https://libmast.utm.my/Record/mit-1721.1%2F119309/Details)

### Inferences
- The planner's split (an E3 metabolic cost and E4 walkback layer, separate from E5 station values) matches SEXTANT's design. Adding science value as a reward per station in an orienteering problem goes **beyond** SEXTANT and should be framed that way.

### Gaps
- The full thesis was not read, so a secondary science-weighting feature cannot be ruled out.
- No other human-EVA planner with explicit numeric site rewards was found within budget. Robotic orienteering and science-reward literature is outside this scope.

## Q4. Did any of them weight geologic contacts, diversity of units, or previously characterised (reference) sites?

### Takeaway
**Diversity and representativeness were explicit criteria** in BASALT and Apollo: a gradient of alteration, a representative of each feature, removal of redundant stations, and ranked target units. **Geologic contacts** and **previously characterised reference sites** were not found as explicit, named ranking criteria in the texts read.

### Cited Findings
- BASALT chose stations "that represented a gradient of alteration ranging from high to low" and "representatives of each alteration feature that were widely distributed," and removed "redundant locations." — [Brady et al. 2019](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6442241/fullTextXML)
- BASALT aimed for "a suite of samples representative of a given location." Stevens et al. do not tie contacts, unit diversity or reference sites to the leaderboard ranking. — [Stevens et al. 2019](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6442282/fullTextXML)
- Apollo 17 sampled three target units in ranked order (highlands, dark mantle, subfloor). — [NTRS 19930009614](https://ntrs.nasa.gov/api/citations/19930009614/downloads/19930009614.pdf)
- BASALT used precursor data (multispectral imagery) to pick stations and found aerial imagery alone insufficient. — [Brady et al. 2019](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6442241/fullTextXML)

### Inferences
- **Unit contact = 3**: justify it from general field-geology practice (contacts constrain relative age and the relations between units) and from the diversity/representativeness criterion. It is not backed by an analog scoring precedent. The sources here do not state that contacts were weighted.
- **Rover-data point = 3**: the nearest precedent is BASALT's reliance on precursor data to choose stations. The value comes from ground-truthing or linking to existing measurements (here, Curiosity's), not from novelty. This is an inference. No source found names "reference sites" as a ranking criterion.

### Gaps
- No source found states a weight for geologic contacts or for revisiting previously characterised sites in Apollo or analog station ranking. USGS PP 1080 and the Apollo Traverse Planning Data book might contain such reasoning but were not read in full.

## Q5. Explicit statements that scores are subjective, and how they were elicited

### Takeaway
None of the sources calls its rankings "subjective" in so many words. They do describe expert-consensus elicitation: discipline leads reported to a Science Lead with tie-breaking power, priorities were "balanced across the competing scientific aims," the crew's opinion was weighted heavily, and the result depended partly on the Science Lead's personality. That is the documented basis for calling a rubric expert judgment.

### Cited Findings
- Priorities were "balanced across the competing scientific aims of the various scientists"; SST decisions "required discussions among the various scientists"; the team had to "arrive at a consensus." — [Marquez et al. 2019](https://pmc.ncbi.nlm.nih.gov/articles/PMC6442304)
- The MSC "was frequently queried to ensure consensus"; the Science Lead could "break any deadlocks"; the role "depended heavily on the personality of the person in the role"; and "the MSC placed a high weight on the opinions of the EV crew." — [Stevens et al. 2019](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6442282/fullTextXML)
- Station selection involved "iterative discussions regarding confidence in the interpretation of alteration features" in weekly teleconferences with "input from all scientists." — [Brady et al. 2019](https://www.ebi.ac.uk/europepmc/webservices/rest/PMC6442241/fullTextXML)
- Apollo station choices were revised through "subsequent discussions," e.g. promoting alternate station 10b to prime. — [A17 Traverse Planning Data](https://www.nasa.gov/wp-content/uploads/static/history/alsj/a17/A17TraversePlanningData.pdf)

### Inferences
- A defensible write-up could say: "Following BASALT and Apollo practice, which ranked stations ordinally by expert consensus against prioritised science objectives, we encode that ranking as values 5/4/3/3. The absolute numbers are a modelling choice. We report a sensitivity analysis (e.g. permuted or equal weights) to show which routes are robust to the rubric."
- No source found used formal elicitation such as Delphi, AHP or numeric voting. Calling the team's rubric AHP-like would go beyond the precedent.

### Gaps
- No documented use of formal multi-criteria scoring (AHP, Delphi, weighted voting) for EVA station value was found in Apollo or the analog programs searched.
