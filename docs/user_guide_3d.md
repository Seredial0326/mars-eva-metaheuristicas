# Mars EVA Planner · User guide: the 3D map

**Illustrated version:** open `docs/user_guide_3d/index.html` in a browser. It is the same guide, with annotated screenshots of every button.

*Written from `web/3d/README.md` and checked against the code and the running page. Quoted texts are what the screen shows with a plan of 120 min and 1,000 Wh over the 13 saved stations. The 2D planner has its own guide: `docs/user_guide_2d.md`.*

## 1. Open the 3D map

The 3D map shows the same 2 × 2 km area of Gale crater as the 2D planner: a terrain model with 1 m detail, covered by a HiRISE orbital photo with 25 cm detail. It does not make plans: it **shows the plan you saved** in the 2D planner. It runs on your computer and needs no internet.

The easiest way in: plan a walk in the 2D planner, then use the **3D** link in its step 4 (Walk). To start it yourself:

```
python src/viz3d/build_terrain_assets.py      # only the first time: builds the 3D terrain
python -m uvicorn api.main:app --port 8000    # then open http://localhost:8000/3d/
```

If no plan has been saved yet, the ground still shows, and the panel offers **Plan with default settings**.

> **Plan with default settings replaces your saved plan.** The 2D planner and the tablet read that same plan, so use this button only when there is no plan you want to keep.

## 2. The screen

The ground fills the screen. The panel on the left holds the plan and the settings, in sections that open and close. At the start only *Plan* is open (on a small window, all of them start closed). The route has two colours: cyan on the way out, pink on the way back.

- **Panel**: sections Plan, Sun, Map layer, Rover photos and About this view. Click a title to open or close it.
- **Local relief**: ×1 shows the real height of the ground. ×1.5 to ×5 make small hills and slopes look taller, so they are easier to see. It starts at ×2.
- **← Planner**: goes back to the 2D planner, to change the plan.
- **Compass** (top right): the needle points north; click it to face north. **Frame**: goes back to the starting view of the whole area.
- **Habitat and stations**: pins on the ground. Stations the plan does not visit look faded. Click a pin to open its card.
- **Position** (bottom left): map position and height of the point at the centre of the screen, in metres. While you rehearse or walk, it shows where the walker is.

## 3. Move the view

The view turns around the point under the mouse, so whatever you point at stays in place.

| To | Mouse | Touch screen |
|---|---|---|
| Turn around a point | drag | one finger |
| Slide the view | right-drag, or Shift + drag | two fingers |
| Zoom in or out | mouse wheel | pinch (twist to turn) |

Prefer the mouse of a web map (drag slides, right-drag turns)? Add `?drag=pan` to the address.

## 4. Read the plan

The *Plan* section repeats what the 2D planner decided, in plain words: where the plan comes from ("Last plan from the planner"), its distance, time and energy ("1392 m · 111 min · 448 Wh of 900 usable"), the stations visited and in what order, the ones left out, and the energy used at the stations. An amber ⚠ marks only what is worth checking, such as a habitat the planner had to move.

- **Stations (13)**: the full list, first the visited stations in order, then the others. Click one ("1 · R3 · Boxwork ridge"), or press Enter, to fly there and open its card.
- **The station card**: what kind of station it is, its science score, the time needed there and its place in the order. If a rover photo was taken within 150 m, the card shows it too. **Fly here** moves the view close to the station, about 60 m away. Click × to close it (during the rehearsal, Esc closes it too).
- **Reload plan**: loads the plan again after you change it in the 2D planner.
- **Rehearse** and **Walk freely**: sections 5 and 9.

## 5. Rehearse the walk

This is the main use of the 3D map. **Rehearse** plays the planned walk at eye level, on the walk's own clock, with the same instructions and meters as the astronaut's arm tablet. The panel hides so you can see the ground (**Panel** shows it again), the relief goes back to its real height (×1), and the Sun moves with the clock.

- **Next instruction**: as on the tablet, an arrow, the distance in large type ("220 m") and what to do ("Arrive at station R3"). With Voice on, it is read aloud.
- **Play / Pause**, or Space when no button or field is selected.
- **Return home**, **Off route** and **Solar storm**: see section 6.
- **More**: **Chase view** (see the astronaut from behind), **Recentre** (look ahead again; a double-click does the same), speed (×1 real time, ×30, ×60, ×180; it starts at ×60), **Voice** (on at the start), **Use ×k** (test: the astronaut uses more or less energy than planned; each click: 1.0 → 1.2 → 1.5 → 0.8) and the energy numbers (the plan's estimate: used, needed to get home, to spare, oxygen used, time home).
- **Exit** ends the rehearsal. Esc does not end it: it only closes a card and pauses.
- **Timeline**: drag it to jump to any moment of the walk. Under it, the walk clock ("EVA 6:01 of 111:27 · outbound · 262 of 1392 m"), the Sun line (solar time and Sun height now, and the start time, 11:00) and the energy bar (used, needed to get home, to spare).
- **Tablet meters**: Spare energy, Home in (limit 30 min), Radio, Spare energy at your pace and EVA time left. Each one, except Radio, shows OK, LOW or TURN BACK, and a bar in that colour. Radio says “Direct to the habitat”, “Relay through your partner” or “No radio link”. Spare energy at your pace appears after the first 30 m.
- **Return home from here** (when paused): the time and energy to walk home from this point ("✓ 6 min (limit 30) · ✓ 28 Wh, 839 Wh spare after it"). On the ground, the red line is 30 min from home and the cyan area is what the energy left can still reach and come back from.

**At each station** the walk stops and shows the station's card: when you arrive, how long to stay, why the station matters and what to do there. **Done, continue** carries on walking.

**If the astronaut tires faster than planned.** As the walk goes on, the tablet compares the energy the astronaut really uses with the plan's estimate, and recalculates the energy to spare at that real pace. Try it with More → **Use ×k** until it reads ×1.5. The reading "k 1.06 (90 % 1.00–1.12) · 634 Wh" says how many times more energy than planned is being used (k), its likely range, and the energy to spare at that pace. If going home no longer fits at the real pace, a **RETURN NOW** alert appears (in the test for this guide, 900 Wh at ×1.5, it did not appear; with a smaller energy budget it does).

## 6. Practise what can go wrong

Three buttons in the rehearsal practise an emergency. The way home is drawn in red and the way back to the route in orange. The walk clock keeps running through them, and the new line stays until you press **Exit** or **Replay**.

- **Return home**: stops the walk and takes the fastest way home from here.
- **Off route**: the walker strays 25 m from the route and the next instruction steers them back. The clock adds the way back to the route.
- **Solar storm**: the banner "SOLAR STORM · return home now", a red edge around the view, and the automatic way home ("EVA 11:30 · return home 2:30 of 8:23 · 112 of 380 m"). *Why and how much* shows the radiation dose.

**Back at the habitat** the card **Plan against the walk** puts what the rehearsal did next to what the plan said: time 111 min (plan 111), energy 447 Wh (448), distance 1363 m (1392), stations 8 (8), metres without direct radio, how far it strayed, and k. **Summary** opens it again, **Replay** starts a new walk from the beginning (Space does the same), **Exit** goes back to the normal view.

## 7. Sun and shadows

The scene is lit by the Sun of Mars on a chosen day (**Curiosity sol**, the Mars day counted from Curiosity's landing; it starts at 4711) and hour (**Local solar time**; drag to move the Sun). Once a plan is shown, the Sun moves to that plan's best time to leave (11:00 for this 111 min plan, limit 120 min), the same time the 2D planner gives. A line says where the light comes from ("Sun 7° high, light from the west" at 17:30), with the date on Earth.

**Relief only** hides the photo, so you see only the shape of the ground lit by this Sun. This matters because the orbital photo has shadows of its own, taken in the middle of the afternoon. **Shadows** shows the shadows the hills cast; they are true to scale only at relief ×1.

## 8. Map layer

Lays one map of the 2D planner over the ground, with the same colours and legend, and an **Opacity** slider (the higher, the less of the photo shows through): Radio coverage (measured from the plan's habitat), Slope, Too steep to cross (the plan's slope limit), Sand detected, Walking cost or Boulders. It is off at the start, and it stays on while you rehearse.

## 9. Walk freely

Walk anywhere in the area, seen through the astronaut's eyes; it works without a plan. You start next to the habitat, facing the way the route leaves. The route becomes a path on the ground and each station a ring with a flag.

- W/S or ↑/↓ forward and back, A/D sideways, ←/→ turn (90° per second). Click the view and move the mouse to look around. On a touch screen: an arrow pad and drag.
- **Run** (3 m/s, or hold Shift), **Fast** (20 m/s, or F), **Chase view** (C), **Exit** (Esc; if the mouse is captured, the first Esc only frees it).

> **Walking freely is a game, not the real walk.** You can go through rocks and up any slope at the same speed: the planner's slope limit and energy cost do not apply. To check the plan, use **Rehearse**.

## 10. Rover photos

Photos taken by Curiosity's navigation camera (Navcam), placed where the camera stood. **Show photo stops** puts orange camera pins on the ground (off at the start, hidden while you rehearse or walk freely). A pin opens the stop's card: the photo, one button per view, date, sol, local time, direction and credit. **View from here** puts you where the camera was, with the Sun of the photo's day and hour, and lays the photo over the view: a slider to fade it, **Previous**/**Next**, **Realign**, and **Exit** or Esc.

The photos need the photo catalogue in `data/tiles/3d/photos/`. Without it the section says "No rover photos: the server has no photo catalogue …", and everything else still works.

## 11. Share a view

*About this view*: **Copy link to this view** (a web address that opens this same camera, relief, sol, hour and shadows) and **Save image** (a PNG picture without the panels). **Quality** says how detailed the ground is ("Quality: high · mesh every 2 m · …"); on a slow computer add `?q=low` (a point every 4 m). Touch screens, small screens and computers with little memory start on low.

## 12. Six short exercises

1. **Read the ground (3 min).** Local relief ×4; Map layer: Slope, then Too steep to cross.
2. **Rehearse the plan (5 min).** Rehearse, Play at ×60; read R3's card; pause and read Return home from here.
3. **Light at departure (3 min).** Sun: drag the hour from 07:00 to 17:30 with Shadows on.
4. **Something goes wrong (3 min).** Solar storm; Replay; Off route; Return home.
5. **A tired astronaut (4 min).** More → Use ×k until ×1.5; watch Spare energy at your pace.
6. **Walk the ridges (3 min).** Walk freely, C for the chase view, follow the path to R3, F to travel fast.

## 13. What the 3D map can tell you, and what it cannot

- The relief has 1 m detail: it shows the hillside, small hills and drops, but not the 1–2 m boxwork ridges, which only the photo shows. Above ×1 the height is exaggerated.
- Shadows come from the real position of the Sun of Mars, but they are true only at ×1, and the brightness is only a look (no dust or air is simulated).
- The rehearsal plays the plan back; it never changes the route. The energy comes from a model, and the extra effort is simulated with *Use ×k*.
- Walking freely ignores the slope limit and the energy cost.
- A rover photo shows where the camera looked, not proof that a station can be seen from there.

## 14. Keyboard and address options

| Keys | Where | What happens |
|---|---|---|
| Tab, Enter or Space | Panel | Open a section or a list; choose a station or a photo stop |
| Space | Rehearsal | Play or pause, when no button or field is selected |
| Tab / Shift + Tab | Rehearsal | Go through the main buttons, More, Panel, Exit, then the rest |
| Esc | Rehearsal | Close the card or message on top and pause; it never ends the rehearsal |
| W A S D, arrows, Shift, F, C, Esc | Walk freely | Walk, turn, run, travel fast, chase view, leave |
| Esc | Photo view | Leave the photo view |

Address options (add to `http://localhost:8000/3d/`, join several with `&`): `?q=low` or `?q=high` (detail), `?k=3` (starting relief, 1 to 5), `?sol=4711&lt=15:00` (day and hour of the Sun), `?shadows=0`, `?drag=pan`, `?photo=<id>`, and `?plan=default` (**replaces your saved plan**).

## 15. If something looks wrong

| You see | What to do |
|---|---|
| A command instead of the ground | Run `python src/viz3d/build_terrain_assets.py` |
| No route, or an old one | Plan in the 2D planner, then press **Reload plan** |
| "No rover photos…" | The photo catalogue is missing; everything else works |
| Slow or jerky | Add `?q=low` to the address |
| Copy link does nothing | Copying only works on localhost or https: copy from the box |
| Esc does not end the rehearsal | On purpose, so the final summary is not lost; press **Exit** |
