# Landing page (issue #126)

The app's front page and its "Watch the demo" page. The app serves them at **http://localhost:8000/home/** (and `/home/demo.html`) from `web/home/`.

Juan's Claude made the design mock (PR #153, 2026-11-15); Diana's Claude moved it into the app. This file and `review.md` are the design notes. The pages themselves live in `web/home/`.

## How to view it

- Start the app as in the README, then open http://localhost:8000/home/.
- *Plan (2D)*, *Open in 3D* and *Guide (tablet)* open `/`, `/3d/` and `/guide.html`; *Watch the demo* opens `demo.html` next to it.
- Without the server: `python -m http.server 8061 --directory web`, then http://localhost:8061/home/ (the app buttons then open the static pages, without the API).
- Checks: `node --test tests/web/` (`tests/web/landing.test.mjs`: every link and image resolves in `web/`, no external files, the video slot stays hidden until it has a link, every image in `assets/` is used).

## Files

| File | What it is |
|---|---|
| `web/home/index.html` | Landing page: what the app does in two sentences, the four buttons, the video slot, four sections with real screenshots (Plan, Check the way back, Rehearse, Follow), limits, team and credits. |
| `web/home/demo.html` | The seven-minute walkthrough of `docs/demo.md`, step by step: what to press, what to look for and a screenshot for each step. |
| `web/home/styles.css` | Shared styles: system fonts, light and dark themes, works from 320 px. |
| `web/home/assets/` | Screenshots of the real app as WebP, in three widths each (5.3 MB). |
| `docs/landing/review.md` | Design and accessibility self-review of the mock, with the fixes made. |

## Decided

- **Where it lives:** `/home/`, its own folder. The 2D planner stays at `/`, so no existing link, test or the deploy guard changes. Moving the landing page to `/` later means moving the HUD and updating the links listed under "Still open".
- **Hero:** A (the 3D view under the title). Hero B (the boxwork from orbit) and the mock's hero switch were removed with its images.
- **Product name:** Mars EVA Planner, the app's own title.

## Design decisions

- **Headline:** "Every step keeps a way home." It is the paper's core claim: the planner checks at every point of the route that there is energy and time left to get back.
- **The app is the hero.** Real screenshots only, with no renders, stock images or icons. The colour comes from the Mars imagery; the only accent is the app's own orange. A red underline under "way home" recalls the app's 30 min red line.
- **Structure taken from Apple's product pages and the HIG:**
  - one message per section, a short headline over 1–2 sentences, and a large real image;
  - one filled button for the most likely action;
  - 44 px targets, contrast of at least 4.5:1 (most text is above 6:1), and light and dark modes.
- **Offline, like the demo, except the video.** Both pages embed the 30 s demo video from YouTube (https://www.youtube.com/watch?v=7LSQqSFdU6c, through youtube-nocookie.com), the only external resource; the "Watch on YouTube" button under it links out too, for when the embed cannot load. Everything else is served by the app.
- **Button names** follow the brief: *Plan (2D)*, *Open in 3D*, *Guide (tablet)*, *Watch the demo*. The demo page quotes the app's current labels (for example *3D view*) so that whoever presents presses the right button.
- **Team:** first names only, alphabetical, no titles.

## Where every number comes from

| Number | Source |
|---|---|
| 2 × 2 km box, 1 m grid, 0.25 m photo | `paper/sections/00_abstract.md`, `02_study_area_data.md` |
| 30 min of emergency oxygen | `paper/sections/03_10_product.md` (R_T = 1800 s) |
| About a third of what a 1.35 km circle calls safe | `00_abstract.md`; `paper/notes/product_api_hud.md` (36 %) |
| 21–46 % false safe for simple rules, 0 % for the planner | `00_abstract.md`, `06_conclusions.md`, `04_results.md` |
| 13 stations, 120 min → 8 visited | `04_results.md`; `paper/notes/E5_orienteering.md` |
| 60 min → the 3 best ridges; 1,000 Wh | `paper/notes/product_api_hud.md` |
| 383 Curiosity photos | `03_10_product.md`; `paper/notes/P3_rover_photos.md` |
| 3–22 min radio delay to Earth | `01_introduction.md`; `paper/notes/P6_departure_time.md` |
| 1–3 m ridges the DEM misses | `02_study_area_data.md` |
| Sand adds up to 11.5 % | `paper/notes/E1_maxent_irl.md` |
| 30° default limit; 29.6 % of the box off limits at 20°; it is the setting that changes routes most | `paper/notes/E3_metabolic_cost.md`; `product_api_hud.md` |
| Values by type 5/4/4/3; 13 stations | `paper/notes/E5_orienteering.md` |
| 15 E8 stations | `paper/notes/product_api_hud.md` |
| 1.35 km and Apollo 1.7 km circles | `paper/notes/product_api_hud.md` |
| 22.6 % radio coverage; 41 % of the tour without direct radio | `paper/notes/E11_comms.md`; `04_results.md` |
| Sol 4711: −74 to −4 °C, 11.9 h of daylight | `paper/notes/product_api_hud.md` |
| Time binds before energy; the energy model is an extrapolation; no GPS on Mars | `00_abstract.md`, `05_discussion.md`, `product_api_hud.md` |
| Step durations (30 s, 45 s…) and "seven minutes" | `docs/demo.md` §3. These are script timings, not results. |

Two numbers from `docs/demo.md` were left out because the notes disagree:
- "three are Curiosity's real drill sites" (the E5 note lists one Curiosity site);
- "rank correlation 0.00" (the note gives −0.001).

## Still open

1. **The video (#123):** when it exists, put its URL in the `<a data-youtube-link>` of both pages and remove `hidden`. The test checks that a placeholder link stays hidden.
2. **Links into the landing page** (files owned by Sebastian, asked on the board): a link to `/home/` from the HUD, the guide and the 3D view; the demo script (`docs/demo.md`). If the landing page later takes `/`, also "← 2D planner" in `web/3d/index.html`, "Planner" in `web/guide.html`, the deploy guard (`api/public_mode.py`, PR #152) and the README. The wrist card's QR points to `/guide.html` and stays.
3. **Deploy (#122, PR #152):** its guard treats `/`, `.html`, `.js`, `.css`, `/tiles/`, `/vendor/` and `/3d/` as static; the `.webp` images under `/home/assets/` would count as computational requests. Needs `.webp` (or `/home/`) in that list.
4. **One name per view (#124).** The 3D view is "3D view" in the HUD, "Open in 3D" on the photo card and here, and "Same walk in 3D" in the guide.
5. **`photo-3d`** (the Navcam photo laid over the terrain) is still the mock's: it needs the rover photo catalogue (`data/tiles/3d/photos/`), which only Juan's machine has. Rerun `node docs/landing/capture.mjs … photo-3d` and `python docs/landing/make_webp.py … photo-3d` there. With the catalogue, `hero-3d` gets its photo pins back and `step-rehearse`'s station card shows the nearest photo; rerun those two as well and restore their alt text.
6. Add "HiRISE: NASA/JPL-Caltech/University of Arizona" to `paper/references.md`. It is the usual HiRISE credit and is used here.

## How the app screenshots were made

All 15 are taken by a script, so they can be retaken after any UI change (#173). Retaken 2026-11-15 on Diana's machine, from `main` at `caeb21a` (after #157, #158, #168, #169, #177 and #182); `photo-3d` was not (see "Still open").

```
python -m uvicorn api.main:app --port 8000
chrome --headless=new --remote-debugging-port=9222 --window-size=1440,900 about:blank
node docs/landing/capture.mjs http://localhost:8000 9222 <png-dir> [shot,shot,…]
python docs/landing/make_webp.py <png-dir> [shot,shot,…]
```

- **What it does:** `capture.mjs` drives the real app over the DevTools protocol at 2× and writes one PNG per image. `make_webp.py` writes the WebP files in the widths the pages use, at quality 80.
- **Data:** every release. The HUD's source chip reads "7 data types from 4 missions". The `stations-v1` release must be in `data/stations/` (13 stations, rubric 5/4/4/3); the numbers on the pages come from it. Back up your own stations first and put them back after.
- **The plan:** the script plans the default walk (120 min, 1,000 Wh, 10 % reserve, 30°, sand cost), so it **replaces `data/plans/last_plan.json`**: back it up first. It gives 8 of 13 stations, 111 of 120 min, 448 of 900 Wh, 1.39 km and 41 % of the walk without direct radio. It saves no stations and no walks.
- **Sizes:**
  - 1440×900 for the 2D planner and the eye-height rehearsal;
  - 1600×900 for the 3D overview, the hero and the chase view;
  - 592×1180 for the tablet guide.
- **What each shot shows:**
  - **Steps 1–4** (terrain, walking cost, steep cells at 20°, stations): taken before planning, so no route.
  - **Plan, radio:** after planning, with the radio layer from the Plan tab's "Show on the map".
  - **Walk, storm:** the astronaut 6.5 min into the rehearsal; the storm is the HUD's default scenario.
  - **Weather:** sol 4711.
  - **Tablet:** walking until the radio warning, then about 6 min from home for the storm.
  - **3D:**
    - the opening view and the hero, with the panel folded;
    - the chase view at R2;
    - the eye-height view at H0, with its station card.
