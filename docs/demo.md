# Running the demo

The demo is a FastAPI backend (`api/`) that serves the HUD (`web/index.html`) and the map tiles from one address. Owner: Sebas (#10). The team decided not to freeze the code at hour 40; changes still go through PRs.

## 1. Set up (once per machine)

1. **Python packages** (normal terminal, not admin; inside the team's environment):
   ```
   python -m pip install -r api/requirements.txt
   ```
2. **Data.** Nothing large is in git. Download the releases from the repo root (`gh auth login` first). Then check what is missing:
   ```
   python -m api.check_data
   ```
   It lists each folder, what breaks without it and the exact download command.

   | Folder | Release | Needed for |
   |---|---|---|
   | `data/base/` | `base-grid-v2` | everything (DEM, slope, grid, ortho) |
   | `data/tiles/` | `tiles-v2` | map tiles |
   | `data/e2/` | `e2-trajectory-v1` | fixed test route (Curiosity) |
   | `data/stations/` | `stations-v1` | saved science stations (optional) |
   | `data/stations/` | `stations-e8-v0` | the 15 E8 contact stations button (optional): `gh release download stations-e8-v0 -D data/stations` |
   | `data/e12/` | `e12-dose-v1` | radiation panel (optional) |
   | `data/e8/` | `e8-v0` | sand layer (optional) |
   | `data/e9/` | `e9-rocks-v1` | boulder layer (optional; unzip `e9_rocks_v1.zip` there) |
   | `data/e1/` | `e1-sand-v1` | human cost: E3 × E1 sand price (optional; without it E3 alone) |
   | `data/rems/` | `rems-v1` | surface weather panel (REMS) (optional) |
   | `data/minerals/` | `minerals-v1` | regional minerals panel (CRISM/OMEGA) (optional) |
   | `data/thermal/` | `themis-v1` | night thermal layer (THEMIS) (optional) |
   | `data/tiles/3d/` | generated | 3D view: run once `python src/viz3d/build_terrain_assets.py` (optional) |

   Optional software: **GDAL** (`osgeo`) for the radio (E11; without it those routes answer 503 and the HUD says "unavailable"), and **OR-Tools** for tours of more than 20 stations (E5 switches from the exact DP to CP-SAT).

   PowerShell example: `gh release download base-grid-v2 --dir data; Expand-Archive data\base_grid_v2.zip data\base -Force; Remove-Item data\base_grid_v2.zip`. The stations release has no zip: `gh release download stations-v1 --dir data\stations`.

## 2. Start

```
python -m uvicorn api.main:app --port 8000
```
Open **http://localhost:8000/**. The first plan or walkback takes about 10 s while the graph is built and cached; later calls take well under a second.

Health check: `http://localhost:8000/health`. Tests: `python -m pytest tests -q`.

No internet is needed at demo time: deck.gl is vendored in `web/vendor/` and all data is local.

**Guide mode (arm tablet):** after planning, press *Guide (tablet)* under the plan (or open `http://localhost:8000/guide.html`). Press ▶ Walk. *Repeat* says the last instruction again and *Return home* turns back at any time. Under *Demo controls*, try *Step off route* (off route → recalculating) and *Solar storm*: the alert goes to the top, any open station card closes, and the guide turns home on its own and gives the dose. Each meter shows a word (OK, LOW, TURN BACK) as well as a bar, and the voice says when one crosses a limit. At the habitat a card compares the plan with what was walked (also at the end of the 3D rehearsal), and the walk is saved in `data/walks/`.

**Wrist card:** *Wrist card* under the plan opens a printable step list with the turn-back rules and a QR to guide mode; *Print / Save as PDF*. For the QR to work on a tablet, open the page through the computer's network address, not `localhost`.

## 3. Seven-minute walkthrough

This follows the guide's demo script (zero-to-hero REV3, section 51). The sidebar's tabs are the order of work: **1 Terrain → 2 Stations → 3 Plan → 4 Walk**, plus **Context**. The legend on the map (*On the map*) lists only what is drawn. The labels are in plain words; hover one to see the piece behind it (E3, E8, E11…).

1. **Terrain (30 s).** Tab *1 Terrain*: the photo from orbit with *Slope* on top; switch on *Sand detected*, then *Boulders*: one dot per 10 m square, sized by the share covered by boulders larger than about 1 m (E9, Aaron's BoulderNet distilled). The boulder fields sit on the scarp edges. The layer is context only, not part of the route cost. Say that the 1 m DEM does not resolve the boxwork ridges, but the 0.25 m image does. Press the chip under the title, *7 data types from 4 missions* (HiRISE image and DEM, and CRISM minerals, from MRO; OMEGA from Mars Express; THEMIS night thermal from Mars Odyssey; Curiosity's traverse, RAD and REMS from MSL), counted only when used. Optionally switch on *Night temperature*: at 81 m it does not see the sand patches (rank correlation 0.00), an honest negative. Switch on *Rover photos* and click a dot (or, in *2 Stations*, a station's photo line) to see what Curiosity saw there; *Open in 3D* jumps to the same view.
2. **What a step costs (45 s).** Still in *Terrain*, turn on *Walking cost*. In *3 Plan → More options*, *Charge extra energy on sand* multiplies E3's energy by E1's sand price (up to +11.5 % on sand), the one terrain term learned from Curiosity's route that held up on unseen data. The cost is Santee 2001 with Mars gravity only in the slope term. Whole-power scaling fails the lunar check (52 W against 292 W on flat ground). The cheapest metre is a gentle descent (338.75 J/m), not flat ground.
3. **Steep cells (20 s).** Move *Never cross cells steeper than N°* (30° by default; 20° puts 30 % of the area off limits). This is the decision that changes routes the most (E3 sensitivity).
4. **Science stations (45 s).** Tab *2 Stations* lists 13 stations. Three are Curiosity's real drill sites (Nevado Sajama ridge, Valle de la Luna hollow, Altadena); the rest are candidates. Open *Advanced: science values and AI-found sites*: *Science value by type* (ridge 5, hollow 4, contact 4, Curiosity site 3) is editable live; its literature review is in `docs/research/`. *Load AI-found sites* adds JB's 15 stations found by E8 (rock next to boxwork sand patches), unsaved. **Do not press *Save stations* after this during a demo:** it rewrites `data/stations/` and the plan no longer matches these numbers (restore with `gh release download stations-v1 -D data/stations --clobber`). *Add stations by clicking the map* shows on the map what a click will do; Esc stops it. A removed station can be brought back with *Undo*.
5. **Plan (60 s).** Tab *3 Plan*: the habitat comes first (*Set on the map* to move it), then *Longest walk*, *Energy budget* and *Reserve kept unused*; press *Plan the walk* (or Enter in a field). Limits out of range are flagged at the field. E5 (Diana) chooses which stations and in what order, exactly (DP, or CP-SAT above 20 stations); E4 (Aaron) gives each leg and checks the walkback at every vertex. The map zooms to the walk and numbers the stations in visiting order (*Fit plan* / *Whole area* top right). The summary shows how much of each limit the walk uses, the visiting order and the stations left out. With the 13 stations and 1,000 Wh: 120 min visits 8; 60 min keeps only the 3 highest-scoring ridges, so the rubric decides when time is short. The limits fold into a one-line summary so the result is in view (click it to change them). Change a limit and the plan is marked out of date until you plan again; if the new plan fails, the previous one stays, marked *Not updated*. Press *Rehearse it*: tab *4 Walk* opens and plays the route.
6. **Walkback (45 s).** In *4 Walk* the map frames the route and the nearest stretch of the red line, and the answer sits on top: *Back at the habitat in N of 30 min*, the energy spare after returning and a bar for the margin left to the 30 min line (OK, TURN SOON, OVER 30 MIN), updated as the route plays (Space plays or pauses). Pause anywhere. The **red line** is the 30 min emergency-oxygen return (R_T = 1800 s), the only strong red on the map: the slope fades on this tab and the cells too steep to cross are a dark hatch. A **dark shade** covers what the astronaut could not reach and come back from with the energy left (F_E + R_E). Neither limit is a circle: scarps and slopes shape them. The dashed, labelled circles are the classic fixed-distance rules (1.35 km, Apollo 1.7 km): about a third of what they call safe cannot get back in 30 min, as the panel says. *Try another point* places the astronaut anywhere.
7. **Radio (20 s).** Back in *3 Plan*, read the one-line *Radio* summary (*More* opens the details) and press *Show on the map* (or *Radio coverage* in *Terrain*): the habitat antenna sees about a quarter of the area (blue), and the route's stretches with no direct radio are magenta (for the 120 min tour, about 40 % of the walk; as a pair 20 m apart a little less). In guide mode the voice warns about 80 m before radio is lost. Below it, the *Best time to leave* line: for the 120 min tour on sol 4711 (the sol of *Context → Weather on the day*), leave between 06:45 and 15:15 and the whole walk is in sunlight; best 11:00. The terrain's shadows cut 15–45 min off that window (section 6).
8. **Solar storm (30 s).** Tab *Context → Radiation*: pick a storm and press *Simulate a solar storm alert*. It pauses the rehearsal where it is (or uses the point you placed), shows the alert on the map with the way home as an amber dashed line (the red line stays the 30 min limit), and gives the dose on the way back: the return time × the storm rate. The time in the alert is the same as the walk card's, from the same position. The way home is checked against the energy left on that same path; if it does not fit, the alert says so. Background radiation does not change the plan; a storm does. *Dismiss* clears the alert, and so does a new plan.
9. **Weather of the EVA's sol (20 s).** *Context → Weather on the day*: sol 4711 (the Nevado Sajama drill) had air from −74 to −4 °C, ground from −86 to +12 °C and 11.9 h of daylight, so a 120 min EVA fits. Weather is context: REMS gives one value per sol, not a map. Below it, *Minerals seen from orbit*: the box sits inside Gale; the nearest hydrous detection (CRISM/OMEGA) is 16 km away and the nearest clay 30 km. Orbit only sees the region; Curiosity measured the box itself at the drill sites.
10. **3D rehearsal (40 s).** Press *3D view* (or open `/3d/`): the last plan is drawn on the terrain with the HiRISE photo. Press *Rehearse the route* to walk it at eye height with the same energy bar; the Sun is set for the same sol 4711 and local time, with shadows. Say that the relief of the 1–2 m ridges comes from the photo, not the DEM. The 3D view carries the same guide as the arm tablet (one module, `web/guide_core.js`): next maneuver, voice, the meters (energy, time back, EVA time left, radio), *Return home*, *Detour* and *Solar storm*. They are two views of one walk. In both, the way home and a re-route are checked for energy, time and O2 on the same path: if the fastest way home does not fit, a slower one that does is taken and the guide says why; if none fits, it says so instead of calling the fastest path safe (#119 A2).

## 4. What to say honestly

**Works without Earth.** A radio signal takes about 3 to 22 minutes to cross from Mars to Earth, one way, so mission control cannot steer an EVA in real time. Martian Map does not ask Earth: the planner, the walkback check, the way home, the off-route recalculation and the solar-storm return all run on the local server, from data already on board, and the HUD and the guide load no script from the internet (deck.gl is vendored; a test fails if a page loads one from a CDN). The tablet decides alone, with everything already computed. (Paragraph by Diana, #45.)


- **The guarantee is conditional.** "The astronaut can get back from every point" means: on E3's costs over the 1 m DEM, with the service placeholder (205 W) and O2 as energy / 20.1 kJ/L, every vertex of the plan fits the energy and O2 budget for the way home, and the plan fits the time limit. The 30 min emergency-oxygen line is a separate contingency rule, shown on the map, not part of that check. Uncertainty in the cost itself (an astronaut working harder than the model) is handled by the adaptive walkback, validated in simulation only.
- Santee 2001 with g = 3.71 m/s² is an extrapolation, not validated for a suited astronaut on Mars. O2 is a metabolic equivalent (20.1 kJ/L), not a tank reading.
- In this 2 × 2 km box energy rarely binds (the costliest round trip is about 560 Wh against 2,813 Wh xEMU); time does.
- E1 (learning from Curiosity's route) found no DEM terrain price; only E8's sand helps on unseen data. Its price is small: the route to Nevado Sajama moves up to 23 m and costs 1.8 % more, and the 120 min tour visits the same stations. It applies to astronauts what rover drivers avoided, which is an assumption.
- Station values encode an expert ranking, not measurements. The walkback fields are on the same E3 costs as E4.
- There is no GPS on Mars: walking the route is simulated.
- Radio is pure line of sight on the 1 m DEM, with no diffraction or link budget: conservative, and the DEM misses the 1–3 m ridges and boulders that can block more.
- THEMIS and CRISM are coarse (81 m pixels; detections rounded to kilometres): regional context, never a per-cell cost.

## 5. Before presenting

- [ ] `python -m pytest tests -q` and `node --test tests/web/ tests/viz3d/` pass on the demo machine.
- [ ] `python -m api.check_data` passes; the releases are the final versions.
- [ ] `data/stations/` is the release `stations-v1` (13 stations; sha256 d62fde941c49 for the gpkg and dd183e59ccbf for the rubric). A *Save stations* after loading AI-found sites changes the plan.
- [ ] Server started from `main`; press *Plan the walk* once before presenting (warm cache: the first plan takes 10–30 s).
- [ ] The browser was reloaded with Ctrl+F5 after the last `git pull` (it caches the JavaScript modules).
- [ ] Every piece's paper note is up to date (`paper/notes/`, AGENTS.md rule 7).
- [ ] Rehearse the walkthrough above twice with the timer, speakers on (guide voice).

## 6. Best time to leave (P6)

In the HUD it is the *Best time to leave* line under the plan (step 7 of the walkthrough), from `GET /plan/departure?sol=`. The same table from the command line, on the saved plan:

```powershell
python src/orienteering/departure.py --plan data/plans/last_plan.json --sol 4711
```

It replays the plan's own clock at each departure time (every 15 min) and says how much of the walk is in sunlight, in the shadow of the terrain (1 m DEM) or in the dark, and recommends one. For the 120 min tour on sol 4711: the whole walk is in sunlight for departures from 06:45 to 15:15 local true solar time, best 11:00 (10:22 on the mission clock); terrain shadows cut 15–45 min off that window. Details and checks: `paper/notes/P6_departure_time.md`.

**The light also chooses the stations (#111).** Not in the HUD: from the command line, each station is served only while it is in sunlight and out of the terrain's shadow, and the planner sweeps the departure time:

```powershell
python src/orienteering/run.py --habitat 8143537.99 -284463.58 --light-sol 4711
```

For the nominal tour, leaving between 05:00 and 14:45 still collects all 56 points; leaving at 16:00 the evening shadows leave 37, and from 17:45 nothing. At 06:00 the 120 min tour keeps its 37 points with a different set of stations. Details: `paper/notes/E5_orienteering.md`, *Results with time windows from the light*.
