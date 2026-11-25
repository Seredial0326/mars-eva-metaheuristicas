# Mars EVA Planner · User guide: the 2D planner (HUD)

**Illustrated version:** open `docs/user_guide/index.html` in a browser: the same guide with annotated screenshots of every button.

*Draft (JB's Claude, 2026-11-15), from `web/index.html` and `docs/demo.md` in main, and checked against the running app (every quoted text below is what the screen shows). Covers the 2D planner at `http://localhost:8000/` only; the 3D map has its own guide (`docs/user_guide_3d.md`, illustrated in `docs/user_guide_3d/index.html`); the tablet guide and the wrist card are to do.*

## 1. What the planner does

You choose science stations in a 2 × 2 km area of the Gale crater boxwork and set the EVA's limits (time, energy, reserve, oxygen). The planner returns a walk that:
- visits the stations that give the most science value within those limits, in the best order;
- **checks at every point of the route that the astronaut can get back to the habitat**: the energy used plus the energy needed to return fits the budget (*walkback*). The check is exact on the model's costs (walking energy on the 1 m terrain model, oxygen estimated from it); a body that works harder than the model is covered by the tablet's adaptive meter;
- avoids cells steeper than the slope limit.

Then you rehearse the walk and check, at any point, how far the astronaut can still go and come back.

Everything runs on the local server; no internet is needed during use.

## 2. Starting

1. Start the server: `python -m uvicorn api.main:app --port 8000` (data set-up: `docs/demo.md` and `python -m api.check_data`).
2. Open `http://localhost:8000/`.
3. The screen has the **map** and a **side panel with tabs**: **1 Terrain → 2 Stations → 3 Plan → 4 Walk**, plus **Context**. Follow them in order; each tab ends with a **Next** button.
4. **Tips** appear in context the first time each step matters. A tip you have seen, or whose suggestion you followed, does not come back.

**Coordinates and units.** Positions are metres in the Mars map projection of the terrain model, energy is Wh, time minutes, oxygen litres. Move the cursor over the map: the box in the corner says where it is, in metres east and north of the area's south-west corner.

**On the map:** drag to pan, scroll to zoom. **Fit plan** zooms to the walk; **Whole area** shows the whole box. The **On the map** legend lists only what is drawn right now (closed by default on small screens).

## 3. Tab 1 · Terrain: read the ground

| Control | What it shows | How to read it |
|---|---|---|
| **Photo from orbit** (HiRISE, 25 cm) | The orbital photograph | The only layer that shows the boxwork ridges (bright lines) and the sand (dark grey-blue) |
| **Shaded relief** | Hillshade of the 1 m terrain model | Knolls and scarps; it does not resolve the 1–3 m ridges |
| **Slope** | Steepest slope per cell | Green 0°, yellow 15°, orange 30°, red 45° and more |
| **Never cross cells steeper than N°** | Cells blocked for the planner (dark hatch) | Default 30°; the line under it says how much is blocked ("12.4 % of the area is off limits" at 30°). **The setting that changes routes the most.** 20° blocks about 30 % of the box. Changing it marks the plan out of date |
| **Sand detected** | Fraction of each 1 m cell detected as sand | Cautious: when it marks sand it is right about 92 % of the time, but it misses most sand |
| **Boulders** | Dots per 10 m square; bigger dot, more boulder cover | Boulders larger than about 1 m. Context only: the route cost does not use them |
| **Walking cost** | Wh to cross each 1 m cell | The cheapest metre is a gentle descent, not flat ground |

**More layers:**
- **Radio coverage:** cells from which a suit radio sees the habitat antenna, and, with a plan, the stretches of the route with no direct radio (magenta). Pure line of sight on the terrain model: cautious.
- **Night temperature** (Mars Odyssey, 81 m pixels): context, not a cost.
- **Rover photos:** where Curiosity's Navcam photos were taken, with the direction each one looks. Click one for its card. Photos show the view, not a promise that a station is visible. Without the photo catalogue on the server the checkbox says "Unavailable…" and the rest of the map works.

## 4. Tab 2 · Stations: where to go

**Add a station:** pick a **Type** (**Boxwork ridge**, **Hollow between ridges**, **Contact between units**, **Curiosity measurement site**), switch on **＋ Add stations by clicking the map** and click. The banner on the map says what a click will do; **Esc** stops placing.
- **Load Curiosity sites** adds Curiosity's drill sites.
- **Advanced:**
  - **Load AI-found sites** adds sand-rock contacts found by the boxwork detector (E8). They are added unsaved.
  - **Science value by type** edits the points of each type. Default: ridge 5, hollow 4, contact 4, Curiosity site 3.

**Stations table** (title *Stations N*): **Id**, **Type**, **Work (min)** (minutes of service at the station) and **Value**; change the type, work time and value in place, or remove a row. The saved set has 13 stations (Q1, H0–H4, R0–R4, C1, C2). A "?" after an id marks a rough position; hover the id for its source.

**Save stations** keeps the list for next time. **Careful:** saving rewrites the whole saved list (and the values) with what is loaded now. Plans already use the list without saving.

## 5. Tab 3 · Plan: set the limits and plan

**Habitat** (where the walk starts and ends): **Centre of the area** by default; **Set on the map** to move it (click), **Back to the centre** to reset. A habitat on a blocked or cut-off cell is moved to the nearest valid one, and the plan says by how much.

**Limits:**
| Field | Meaning |
|---|---|
| **EVA length** (min) | Maximum duration of the walk, station work included |
| **Energy budget** (Wh) | Suit energy for the walk, from 50 to 2,800 Wh (a full suit ≈ 2,800) |
| **Reserve kept unused** (%) | Part of the budget never planned (default 10 %) |
| More options · **Oxygen budget** (L, 0 = no limit) | Metabolic oxygen, estimated from the energy |
| More options · **Charge extra energy on sand** | Uses the sand price learned from Curiosity's route (up to +11.5 % on sand) |

Press **Plan the walk** (or **Enter** in a field); after the first plan the button reads **Plan again**. The first plan takes 10–30 s while the terrain graph is built; later ones are fast. A value out of range is flagged under the fields (for example "Energy budget must be between 50 and 2800 Wh."). Once planned, the inputs fold into one line, *Habitat and limits · 120 min · 1000 Wh · 10 % reserve · habitat at the centre*; click it to change them.

**The summary:**
- a chip: **"The astronaut can get back from every point"** (or a warning if not);
- **Stations visited**, **Time**, **Energy** (of the budget minus the reserve) and **Distance**, each with a bar of how much of the limit it uses;
- the **visiting order**, and the stations **left out** because they do not fit;
- **Radio:** the share of the walk without direct radio (for example "Radio: 41 % of the walk without direct radio"); **Show on the map** draws it; **More** gives metres and minutes;
- **Best time to leave:** the departures that keep the whole walk in sunlight (for example "06:45–15:15, all in sunlight"); **More** gives the best time;
- **Details:** oxygen estimate, planner and energy model used.

**Out of date:** if you change limits, stations or habitat after planning, the plan is marked out of date until you plan again. If a new plan fails, the previous one stays, marked **Not updated**.

**No plan:** when nothing fits, the planner says why and what would fit. With a 60 Wh budget the screen says: *"No plan. Not even the closest station, C1, fits on its own (energy: needs 57 Wh, 54 Wh available). To fit C1 alone you need an energy budget of at least 63 Wh with the same reserve; that is enough for C1 only, not a promise of more stations."* It never invents a route.

## 6. Tab 4 · Walk: rehearse and check safety

Without a plan the tab says *"Plan a walk in step 3 to rehearse it here. To check one point now, open Try another point below."*

**Rehearse:** **Play** runs the walk (**Space** plays or pauses), at ×30, ×60 or ×180. Here it plays through the stations; the tablet guide and the 3D rehearsal stop at each one. At the top, updated as the walker moves:
- **Home in N min · limit 30:** the time back to the habitat against the 30 min emergency-oxygen limit;
- **Spare energy:** energy left after returning, and "On the plan, returning costs N Wh";
- **Margin to the 30 min line**, with a word: OK, TURN SOON or OVER 30 MIN (for example "OK · 30 min spare");
- the energy bar split into **used**, **needed to return** and **spare**, which only shrinks, and the clock line *"0:00 of 111:27 · used 0 Wh, returning needs 0 Wh"* with the oxygen used.

Links open the same walk in the **Tablet** guide, the **3D** view and the **Wrist card**.

**Safety on the map** (**Show the safety lines**):
- **red line:** the cells from which the astronaut can still walk home in 30 min;
- **dark shade:** out of reach with the energy left;
- neither is a circle: scarps and slopes shape them;
- the lines appear once there is a plan or a placed astronaut;
- **Compare with a fixed-distance rule:** draws the classic 1.35 km and Apollo 1.7 km circles and says how much of them is not safe, for example *"Fixed-distance rule: 37 % of its 1.70 km circle cannot get back in 30 min."* About a third of what they call safe cannot get back in 30 min.

**Try another point:** **Place the astronaut on the map** anywhere and set the **Energy still in the suit**; the lines and the numbers are computed from there.

## 7. Context

- **Radiation:** the dose accumulated over a sample walk; **Simulate a solar storm** pauses the rehearsal, shows the alert with the way home from where the walker is (the same time as the walk card) and its dose; if the way home does not fit the energy left, the alert says so. The background dose does not change the plan; a storm does.
- **Weather on the day:** air temperature for a chosen **Sol** (one value per sol, from Curiosity's REMS).
- **Minerals seen from orbit** within 100 km: regional context.
- **Data sources:** where every layer comes from ("N data types from M missions"; also the *Data sources* chip at the top).

None of these enter the route cost. Radiation, weather and photos need their optional data releases (`e12-dose-v1`, `rems-v1`, the photo catalogue); without them the panel says what is missing (for example "E12 outputs missing in data/e12/") and the rest works (`python -m api.check_data` lists them).

## 8. Keyboard and accessibility

| Key | Action |
|---|---|
| ← → Home End (on the tabs) | Move between tabs |
| Tab to the map, arrows (Shift: bigger steps), Enter | Place a station, the habitat or the astronaut without a mouse |
| Esc | Stop placing; close the photo card |
| Enter (in a limit field) | Plan |
| Space (Walk tab) | Play / pause the rehearsal |

Touch targets are 44 px on touch screens; on narrow screens the map goes on top and the legend starts closed.

## 9. Suggested routes to learn the tool

1. **First plan (5 min).** Terrain: turn on Slope and Sand. Stations: Load Curiosity sites. Plan: keep the defaults, Plan the walk. Walk: ▶, then pause and Show the safety lines.
2. **Time is the limit.** Plan with EVA length 120, then 60 min: fewer stations; at 60 min the highest-value ridges are kept. In this area time runs out long before energy.
3. **The slope limit.** Change *Never cross cells steeper than* from 30° to 20° and plan again: the route changes and more of the area is blocked.
4. **When nothing fits.** Set the energy budget to 60 Wh and plan: read why there is no plan and the budget that would fit (63 Wh); plan with it and only C1 is visited.
5. **Fixed radius vs terrain.** Walk tab: Compare with a fixed-distance rule; look at the cells inside the circle but outside the red line.
6. **Any point.** Try another point: place the astronaut far from the habitat with little energy and watch the shade grow.
7. **Radio and light.** Plan: Show on the map the stretches with no radio; read the best time to leave.
8. **Science values.** Stations → Advanced: raise the value of *Hollow between ridges*, plan with a short EVA (60 min), and see which stations change.

## 10. What the numbers mean (and do not)

- Energy is a model (Santee 2001 with Mars gravity), not validated for a suited astronaut; oxygen is estimated from energy, not a tank reading.
- The terrain model does not resolve the 1–3 m boxwork ridges; sand and boulder layers miss part of what is there.
- Station values are an expert ranking, not measurements; service time and power are placeholders.
- Walking is simulated: there is no GPS on Mars.
