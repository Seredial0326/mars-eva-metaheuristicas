# 3D map of the boxwork box (`/3d/`)

A page that shows the 2 × 2 km study box in 3D: the DEM with the HiRISE photo on it, the
plan of the 2D planner drawn on the ground (route, stations, habitat), one of its map layers
draped on the relief, a walk-through of the route at eye height, and the light and shadows
of the Sun of Mars at a sol and a local time. It reads the plan; it never makes one unless asked. three.js is vendored
(`vendor/`), so the page needs no internet. Method, numbers and limits:
`paper/notes/P1_3d_map.md`.

## Run it

From the repo root, with `data/base/` in place:

```
python src/viz3d/build_terrain_assets.py      # once: writes data/tiles/3d/ (a few seconds)
python -m uvicorn api.main:app --port 8000    # the API serves the page and the assets
```

Open `http://localhost:8000/3d/` (the 2D planner links to it). `MARTIAN_DATA` selects
another data folder, as for the API. `data/tiles/3d/` is not in the tiles release: if
`data/tiles/` is replaced, build again; without it the page shows the command.

The route comes from `GET /plan/last`: plan an EVA in the 2D planner, then open the page
or press "Reload plan". With no saved plan the terrain still works.

## Controls

| | Mouse | Touch |
|---|---|---|
| Rotate around the point under the cursor | drag | one finger |
| Move | right-drag or Shift + drag | two fingers |
| Zoom towards the point under the cursor | wheel | pinch (twist turns) |

- Compass (top right, a button that the keyboard reaches too): face north. Under it, the frame
  (four corners): back to the opening view. The house icon is only the rehearsal's "Return home".
- **Relief slider**: ×1 is the DEM; ×1.5 to ×5 exaggerate only the local relief.
- **Panel**: only *Plan* is open when the page opens, at every screen size; *Sun*, *Map layer*,
  *Rover photos* and *About this view* are one click on their title away (the photo view hides
  them and gives them back as they were). No text under 12 px. On touch screens every control
  of the panel (section titles, buttons, ticks with their words, fields, slider thumbs) is at
  least 44 px tall. The page can be zoomed on a phone by pinching a panel; a pinch on the view
  is the 3D's own zoom.
- **Plan**: where the plan comes from, length, time and energy; the plan's own messages in
  plain words, with their numbers ("8 of 13 stations visited · science value 37 · order
  R3 → R2 → …", "Left out, they do not fit in the limits: …", "Power used at the stations:
  205 W (the planner's default)"); ⚠ in amber only for what needs a look (not feasible, no
  route, a failed request, a point the planner moved, a sample route that is not a plan, a
  message the page does not know). Which planner made it and the project codes the API
  writes stay out of the panel (`planMessages` in `plan_model.js`; the source is in
  `viz3d.plan`). "Reload plan"; "Rehearse". "Plan with default settings" appears
  only when there is no plan, and makes the server plan and save (it replaces the last plan
  of the 2D planner).
- **Pins**: click one for its card; "Fly here" views it from 60 m. Stations a tour did not
  visit are dimmed. A station's card also shows the nearest rover photo within 150 m: how far
  and from which side it was taken, and whether the station is inside its field (orientation:
  the terrain may still hide it); "View the rover photo" opens its photo view. With none that
  near, the card says so. At a rehearsal stop the card shows the same photo, without the button
  and without moving the walker or the clock.
- **Keyboard stop lists**: *Plan → Stations (count)* and *Rover photos → Photo stops (count)*
  start folded and scroll when opened. Tab reaches their titles and buttons; Enter or Space
  opens a list or chooses a stop. Stations appear in visit order (for example,
  "1 · R3 · Boxwork ridge"), then the stations marked "Not visited"; without visit information,
  they keep the plan's order without invented visit numbers. A station button flies there
  and opens the same card as its pin. Photo buttons show a stop number, sol and view count;
  they turn on "Show photo stops" and open the existing card, whose "View from here" starts
  the photo view. Focus moves to the card's Close button and returns to the list on Close.
  Both lists are disabled, with an explanation, during Rehearse (including pause), photo
  view and Walk freely. Leaving the mode restores them. Empty or unavailable lists say why.
- **Guide** (the arm tablet's logic, shared in `web/guide_core.js`): the next maneuver as
  the tablet shows it (the arrow, the distance big, "350 m" or "Now", the instruction under
  it), voice on/off, the tablet's meters with its labels ("Spare energy" after
  walking home, "Home in · limit 30", "Radio", "EVA time left" against the plan's
  maximum duration and, once the walk has learned it, "Spare energy at your pace" with this
  astronaut's own energy use, X2), each value with the state word before it (OK, LOW or TURN
  BACK on every meter), bold in its state's colour, and its bar in that colour; the time
  home reads "home in 12 min", as on the tablet; the radio row says
  "checking…" until the server answers (no jump), and goes if there is no radio data; a
  RETURN NOW alert when the way home no longer fits at that use (screen readers
  announce it, as the storm alert),
  station tasks with "Done, continue", "Return home", "Off route" (demo: 25 m off the route,
  then rejoin), "Solar storm" (demo: automatic way home with the dose) and "Use ×k" (demo:
  the simulated energy use against the model, 1.0 / 1.2 / 1.5 / 0.8). A way home is
  drawn red and a rejoin orange; it replaces the walked route until "Exit". The solar storm
  also shows beyond the player: a red band across the top with the tablet's banner ("SOLAR
  STORM · return home now") and a red vignette over the view, page elements (nothing is
  added to the 3D scene); both go at the habitat, on "Replay" and on "Exit".
- **Words and numbers**: the 3D takes its names, state words and number formats from the
  team's glossary, `web/terms.js` (#166), as the HUD, the tablet and the wrist card do: one
  name per idea ("Return home", "Off route", "Rehearse", "Planner"), whole minutes and Wh
  everywhere, m:ss only on the player's clock line.
- **Rehearsal**: the side panel is hidden while rehearsing, so the scene shows; "Panel" in the
  player opens it (and closes it) without leaving. The player has the maneuver on top, then
  one row of main buttons: play / pause, "Return home", "Off route", "Solar storm"; then
  "More", "Panel" and "Exit". Under "More": "Chase view" (the astronaut seen from
  behind), "Recentre", the speed (×1 to ×180), voice, "Use ×k" and the energy numbers. Then
  the scrubber, the clock line, the panel's Sun line (local solar time, the Sun's height and
  light, "Following the EVA clock: …") and the 2D planner's energy bar. The clock line is the
  EVA clock, "EVA 3:02 of 111:27 · outbound · 132 of 1392 m"; after "Return home" or the
  storm it goes on and the way home is a stretch of it, "EVA 102:04 · return home 2:02 of 2:51 ·
  120 of 160 m" (after a rejoin, the EVA's new end), while the scrubber covers the new route.
  Drag to look around; double-click or "Recentre" looks forward.
  Entering focuses Play with a visible ring. Tab follows the visible order: main buttons,
  More, Panel, Exit, then the other visible controls; Shift + Tab goes back. More and Panel
  keep focus on their toggle when opened or closed. Exit returns focus to Rehearse, opening
  Plan if it was folded. Space plays or pauses only outside controls: buttons (including
  Play), links, fields, section titles, editable text and custom buttons, checkboxes or
  sliders keep their own Space action and their focus. Holding Space does not repeat the
  rehearsal shortcut, and a key already handled by another control is left alone.
  Esc closes what is on top (the card, or a message) and pauses; it never leaves the rehearsal,
  which would lose the end summary: only "Exit" does.
  It pauses at every stop with the station's card; on pause it draws the walkback lines from
  there and says the way home from there ("Return home from here: ✔ 3 min (limit 30) · ✔ 14
  Wh, 869 Wh spare after it", red line: 30 min from home, cyan: energy-safe area). At the
  habitat it stays in the rehearsal: the storm alert ends, the player shrinks (the maneuver
  says "Home"), and the card "Plan against the walk" has "Replay" (from the start, as a new
  walk with its own summary) and "Exit"; Play (now "↺ Replay") and Space outside controls replay too,
  "Summary" shows the card again after closing it, and the scrubber goes back. On touch
  screens the player's buttons are at least 44 px tall. The relief is locked at ×1 and the Sun
  follows the EVA clock.
- **Walk freely** (Plan section; works without a plan too): walk anywhere in the box in first
  person, like a game. It starts next to the habitat, facing the way the route leaves (with
  no plan: at the ground point in the middle of the screen).

  | | Keyboard and mouse | Touch screen |
  |---|---|---|
  | Walk forward/back | W/S or Up/Down arrows | the up/down arrow pad (hold) |
  | Step sideways | A/D | the left/right arrow pad (hold) |
  | Turn | Left/Right arrows (also while walking) | drag |
  | Look | click the view, then move the mouse (where the browser will not capture it: drag) | drag |
  | Run (3 m/s) | hold Shift, or "Run" | "Run" |
  | Fast travel (20 m/s) | F, or "Fast" | "Fast" |
  | View from behind (the astronaut) | C, or "Chase view" | "Chase view" |
  | Leave | Esc (the first Esc frees a captured mouse), or "Exit" | "Exit" |

  Left/Right turn at 90°/s (a quarter turn in one second), using elapsed frame time.
  Release the arrow to stop turning. Turning also works while walking and adds to mouse look.

  Walking is 1 m/s, the eye 1.7 m above the ground, the relief locked at ×1. The walker stays
  1 m inside the box edge and out of the habitat dome. The route is a path on the ground,
  80 cm wide, in the colours of its legs, and each station has a ring and a flag; the readout
  says the speed and how far the route is. Space and the photo view's Escape are not used.
  Leaving puts the free-flight view, the relief and the route lines back as they were.
- **Sun**: Curiosity sol, local true solar time, "Relief only" (hide the photo), "Shadows".
  The Sun opens at 15:00 and, once a plan is drawn, moves to that plan's best time to leave,
  the one the 2D planner shows under the plan (`GET /plan/departure` for the sol shown; 11:00
  for its 120 min tour on sol 4711), and the note says so. It stays where it is if the sol or
  the time was moved first, during a rehearsal or a photo view, with `?lt=`, or when the
  planner gives no best time. The readout says how high the Sun is and where the light comes
  from ("Sun 44° high, light from the west"); its tooltip has the exact height, the compass
  bearing (azimuth) and the season (Ls).
- **Map layer**: one layer of the 2D planner draped on the terrain, Off by default: Radio
  coverage, Slope, Too steep to cross, Sand detected, Walking cost or Boulders (the 2D's names;
  the hover texts are the 2D's without its codes E11, E8, E3 and E9), with the
  2D's images, opacity slider, legend and note. The radio is seen from the plan's habitat (else
  its start, else the box centre) and the steep cells are those over the plan's own limit.
  Nothing is asked from the server until a layer is picked; one the server cannot give says
  "Unavailable: …". It stays on while rehearsing and with "Relief only"; the photo view hides
  it until "Exit".
- **Rover photos**: orange camera pins at the stops where Curiosity's Navcam took photos, off
  when the page opens (they covered the route): "Show photo stops" shows them, and opening a
  photo (`?photo=`, the 2D planner's "Open in 3D", "View the rover photo" on a station's card)
  turns them on, so they are there after "Exit". They are hidden while rehearsing. A pin opens
  the stop's card: the photo, one button per view, date, sol, local time, direction and credit.
  Pins on top of each other offer a list of stops. "View from here" puts the camera where the
  Navcam was (relief ×1, the Sun of the photo's sol and time) and lays the corrected photo over
  the view: the slider fades it, "Previous"/"Next" change view, "Realign" flies back after a
  drag, "Exit" (or Escape) puts camera, relief and Sun back as they were. A camera pose that
  does not fit the ground (under it, or more than 4 m above it) is said in the bar, not
  corrected.
- **About this view**: "Copy link to this view" (the address of the free-flight view, with
  relief, sol, time and the shadows switch) and "Save image" (the picture without the
  panels, as a PNG, through the browser's download).

## Address parameters

All optional; they combine with `&`.

| Parameter | Meaning |
|---|---|
| `q=low` / `q=high` | quality preset. Low: 4 m mesh, one 4096 px photo, 2048 shadow map. High: 2 m mesh, photo at 0.25 m, 4096 shadow map. Default: low on touch or small screens, else high |
| `k=1..5` | relief exaggeration at the start, in steps of 0.5 (default 2) |
| `view=x,y,z,heading,pitch` | where the camera starts: Mars CRS metres, elevation of the camera in metres (DEM datum), heading from north and pitch below the horizon in degrees. Example (the opening view): `view=8143537.49,-286459.66,-2146.25,0,37` |
| `sol=4711` | Curiosity sol whose Sun lights the scene (default 4711) |
| `lt=15:00` | local true solar time at the box centre (default: the plan's best time to leave, else 15:00; with `lt` the planner is not asked) |
| `shadows=0` | start without cast shadows |
| `light=az,el` | debug: a fixed light direction in degrees instead of the Sun |
| `drag=pan` | map-style mouse: drag moves, right-drag rotates |
| `plan=default` | on load, ask the server for a plan with the default settings. **It replaces the saved plan**, like the button |
| `fps=1` | draw every frame and show frames per second in the readout |
| `spin=1` | slowly orbit the camera (to measure speed without touching anything) |
| `photo=<id>` | open a rover photo (its Navcam image id) in the photo view; the photo stops are shown after it. An id that is not in the catalogue opens the *Rover photos* section, which says so |
| `check=<name>` | run a check (below) and show its result as JSON |
| `tips=reset` / `tips=off` | show the in-context tips again from the first / no tips. They are off during a `check=` |

## Checks in the page

`/3d/?check=<name>` runs a measurement in the running page and shows the result (also in
`viz3d.checkResult` and the console). Add `&q=low` for the low preset. They ask nothing
from the server (but `guide`, as its row says; `layers` only GETs the images and info JSON
the 2D asks for, which changes nothing there) and leave the page as they found it. With a
check in the address the page does not ask for the best time to leave: the Sun starts at
15:00 (or `?lt=`), so a check gives the same answer whatever the plan.

| Name | What it answers |
|---|---|
| `shading` | is the terrain lit from the right side? (lit from N, S, E, W against the slopes) |
| `route` | is the route 0.3 m above the drawn ground at relief ×1, ×3 and ×5, as long as the plan says, with the pins where the plan puts them? |
| `rehearse` | the whole walk in steps of 0.1 s: eye height, turns, distance from the route, pauses at the stops (and the clock line at each, "EVA …"); does leaving put everything back? |
| `sun` | is the light where the Sun of Mars is at five times of the sol; morning against afternoon; does the Sun follow the rehearsal? |
| `guide` | does the rehearsal carry the arm-tablet guide? banner and meters at start, middle and end; Return home, detour and solar storm (asks the server); the plan is back after exit |
| `shadows` | rendered shadows against a ray march over the mesh, 07:00, 15:00 and 17:00 at ×1 and ×5 (about 12 s; 7 s in the low preset) |
| `photos` | for three photos of different sols (`&ids=a,b,c` to choose): camera position, eye height, heading, pitch and field against the catalogue, relief ×1, the photo's Sun, the photo on the centred square; does Exit put everything back? It leaves the photo stops on, as opening any photo does. Whether photo and terrain agree: `src/viz3d/photo_skyline.py` |
| `stations` | for every station of the plan: its nearest rover photo (or that there is none within 150 m) as its card shows it; then each rehearsal stop: the photo is in the card, the clock, the walker and the tasks stay as they were, and the photo pins are hidden (since #124 the stops start off, so this holds even if the rehearsal did not hide them) |
| `walk` | "Walk freely" driven through its own key, pad and drag handlers: speeds walking, running, fast, diagonal, backwards and with the pad; the eye above the ground after every step; a drag turns the view as much as in free flight, the pitch stops at ±85°; fast travel straight at each box edge and at the habitat dome; the chase view; does leaving (Escape, and Exit from the chase view) put everything back? |
| `layers` | is each map layer on the right 1 m cells? Each one alone from straight above (1 px a cell) against the image the 2D shows: share within 3 levels, best shift within ±3 cells, error if flipped north–south; again at relief ×5; the slope tiles over the plan's limit against the steep cells; "Relief only" keeps the layer, the photo view hides it; terrain and page as before (about 8 s) |

From the console, `viz3d` gives the page's objects, and `viz3d.showPlan({fc})` draws any
plan answer without touching the server (how the test fixtures were looked at).

## Files

| File | What it does |
|---|---|
| `index.html` | the page: panels, styles, import map for three.js |
| `main.js` | entry point: address parameters, scene, frame loop, plan panel, view link and image |
| `terrain.js` | loads the assets, builds the meshes, heights, CRS ↔ scene coordinates, relief factor |
| `controls.js` | free-flight camera (arcball on the terrain), `flyTo` |
| `camera_math.js` | the camera's maths: axes, orbit, pan, zoom, ray against the heights |
| `api.js` | the requests: saved plan, default plan, rubric, walkback, best time to leave |
| `plan_model.js` | plan answer → routes, points, profile, markers |
| `overlays.js` | route and walkback lines draped on the mesh |
| `markers.js` | pins and the habitat dome; picking |
| `card.js` | the side card of a station (and of a photo stop) |
| `photos_model.js` | the photo catalogue → stops, views, card facts, camera pose, the photo's Sun, the square of the view |
| `photos.js` | rover photos: pins, the stop's card, the photo view and its bar, the photo laid over the view |
| `photos.css` | styles of the photo card, the bar and the laid photo |
| `map_layers_model.js` | the 2D planner's map layers as data: list, URLs, legends, the slope tiles of the box; the image comparisons of `?check=layers` |
| `map_layers.js` | the "Map layer" section and the layer drawn on the terrain (meshes sharing the terrain's geometry) |
| `map_layers.css` | styles of the "Map layer" section and its legends |
| `rehearse_model.js` | where the walker is at a time of the plan: clock, stops, camera path |
| `rehearse.js` | the rehearsal mode: camera, player, stops, walkback on pause |
| `walk_model.js` | walking freely: keys to direction, speeds, box and dome limits, mouse look, distance to the route, start next to the habitat, the path strip |
| `walk.js` | the "Walk freely" mode: keys, mouse capture, arrow pad, camera, the route as a path and the stations as rings |
| `astronaut.js` | the walker of the chase views: an astronaut of a few three.js shapes that turns and swings its legs |
| `mars_sun.js` | Mars24: where the Sun is for a UTC instant; sols and local times |
| `sun_model.js` | sol and local time → light direction, light levels, panel texts; the best time to leave out of the planner's answer |
| `sun.js` | the lights, the sky colour, the Sun section and its start at the best time to leave, "Relief only" |
| `shadow_fit.js` | the box the shadow map must cover for a Sun direction |
| `shadows.js` | cast shadows: when the shadow map is drawn again |
| `view_link.js` | `?view=`: a free-flight view as text, and the link that carries it |
| `checks.js` | the `?check=` measurements |
| `tips_3d.js` | the in-context tips of this page (#125): the list, when each one shows; the engine is the HUD's, `../tips_core.js` |
| `vendor/` | three.js r187, only the files the page imports (`vendor/README.md`) |

The files with "model", "math", "fit" or "link" in the name, `mars_sun.js` and `api.js`
import nothing from three.js and are tested in Node.

## Tests

From the repo root (Node 26, nothing to install):

```
node --test tests/viz3d/            # camera, plan, rehearsal, Sun, shadow camera, view link, photos, walking, map layers
python -m pytest tests/viz3d -q     # the terrain assets against the DEM
```

`map_layers_model.test.mjs` also fails if a legend string copied from the 2D is no longer in
`web/index.html`, if a layer's name or hover text is no longer the 2D's words (less its
codes), or if the slope tile colours of `src/gis/tiles.py` change. `plan_model.test.mjs`
checks the plain words of the plan's messages on the three real answers.
The exported pure helpers `stationList` (`plan_model.js`) and `photoStopList` (`photos.js`)
are covered by `plan_model.test.mjs` and `photos_model.test.mjs`; `ui_controls.test.mjs`
checks both lists' native controls, existing card/flight wiring and mode restrictions.
Run `node --test tests/viz3d/ tests/web/` for the combined regression suite.

Fixtures in `tests/viz3d/fixtures/` are real answers of the API: an E4 round trip, the
fixed route with no profile, and a multi-station E5 tour
(`src/viz3d/make_tour_fixture.py` says how it was made).

## Rover photos (P3)

Curiosity Navcam photos placed where the camera was (issue #46): the pins, cards and photo
view above read what this step builds. Without it the page works and says there are no photos;
this section says how to build them. Method,
numbers and limits: `paper/notes/P3_rover_photos.md`.

`<raw>` below is the full data folder outside the repo (`data/README.md`). From the repo
root:

```
python -m src.viz3d.build_rover_photos \
  --index-dir <raw>/03_curiosity/imagenes_crudas/indice_soles_4450_4848 \
  --places-csv <raw>/03_curiosity/places_pds/data_localizations/localized_interp.csv \
  --images-dir <raw>/03_curiosity/imagenes_crudas \
  --dem data/base/dem_1m.tif --output-dir data/tiles/3d/photos
```

It never downloads. It writes `data/tiles/3d/photos/catalog.json` (stops, chosen photos,
camera position and direction, time, credit), `report.json` (counts, discards and checks)
and `download_manifest.json` (chosen photos with no local file, with an estimated size).
After the size has been agreed, fetch them and build again:

```
python -m src.viz3d.fetch_rover_photos \
  --manifest data/tiles/3d/photos/download_manifest.json \
  --dest <raw>/03_curiosity/imagenes_crudas/navcam_p3
```

It accepts only full 1024 × 1024 JPEGs from `mars.nasa.gov/msl-raw-images/`, skips files
already present and logs size and SHA-256 in `navcam_p3/_download_log.json`. Tests:
`python -m pytest tests/viz3d -q` (no network, no real photos needed).

## Known limits

- The DEM (1 m) does not resolve the 1–2 m boxwork ridges: the relief and the shadows show
  the hillside, knolls and scarps; the ridges are seen in the photo only.
- Relief above ×1 is exaggerated and no longer to scale; shadows follow the relief as
  shown, so they are true only at ×1. The photo also carries its own mid-afternoon shadows.
- Light levels are a look, not a physical model (no atmosphere or dust). Only the box
  casts shadows.
- The rehearsal plays the plan back on its own clock; with no profile in the plan it
  assumes 1 m/s. The camera follows a smoothed copy of the route (up to about 1 m from it).
- "Plan with default settings" and `plan=default` replace the saved plan that the guide
  screen loads. A copied view link never carries `plan`.
- The view link is of the free-flight view (not offered while rehearsing) and does not
  carry "Relief only" or the map layer. The page keeps the camera 2 m above the shown ground
  and the pitch between 2° and 89.5°, also when it opens a link.
- "Copy link" writes to the clipboard only on `localhost` or https; from another machine of
  the local network the link is shown in a box to copy by hand.
- "Save image" saves the canvas at its size on screen (times the pixel ratio, at most 2;
  1.5 in the low preset): terrain, route and pins, without the panels, the card or the player
  (nor the storm's band and vignette, which are page elements).
- The player's Sun line repeats the panel's Sun section as text (`rehearse.js` reads it after
  the Sun moves); it follows that section's wording.
- The pixel ratio is read when the page loads: moving the window to a screen with another
  density needs a reload.
- Speed was measured on one laptop (60 fps in both presets); no tablet was measured.
- Walking freely is a game, not a model of the EVA: it walks through rocks and up any slope
  at the same speed (the planner's slope limit and E3 cost are not applied), and the speed
  is measured on the map, not along the slope. Frames longer than 0.1 s count as 0.1 s, so
  on a very slow machine the walker is slower, not jumpier. The arrow pad shows only on
  screens whose main pointer is a finger.
- Map layer: one at a time (the 2D stacks several), with the plan's steep limit (not the 2D's
  slider) and no radio from a base set in the 2D. The slope legend is the 2D's, which since #149
  shows the colours of the slope tiles (`src/gis/tiles.py`). The hatch
  swatch of the steep cells is dark on the dark panel, as in the 2D. Night temperature (81 m
  pixels), climate, minerals and dose are not draped. A few route pixels at depth ties with the
  ground are still tinted.
