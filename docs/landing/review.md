# Mock review: design critique and accessibility

Self-review of `index.html` and `demo.html`, run with the `design:design-critique` and `design:accessibility-review` checklists on the pages served at `http://127.0.0.1:8050/` and captured in headless Edge at 1440×900, 1366×768, 768×1024 and 375×812, light and dark.

## Design critique

**First impression.** The headline is read first, and the red underline under "way home" points at the thesis. The real 3D view follows. Purpose, three views and the demo are reachable from the first screen. Hero B gives up the product shot for the place (the boxwork from orbit) and is the more dramatic of the two.

| Finding | Severity | Fix applied |
|---|---|---|
| The hidden "Watch on YouTube" button was visible (`.btn { display }` beat `[hidden]`) | Critical | `[hidden] { display: none !important }` |
| At 1440×900 the hero text filled the first screen; the 3D shot started at 690 px | Moderate | From 1080 px wide, the title sits left and the text and buttons right. The shot now starts at 484 px (1440×900) and 479 px (1366×768). |
| Team names came out small and grey (selector specificity) | Moderate | `.credits .team li` |
| "Watch the demo" in the header wrapped onto three lines at 375 px | Moderate | Hidden below 520 px; the hero keeps it |
| In "Rehearse", the two shots had different heights | Minor | Navcam view cropped to 1:1 and columns set to 1.76 : 1, so both shots are the same height |
| One caption ran about 180 characters per line | Minor | Captions capped at 72 characters per line; the key numbers are bold |
| "What to say honestly" was larger than the step titles | Minor | Same size as the step titles |
| "More in the demo notes" was a 20 px tall target | Minor | Uses the 44 px section-link style |

**Kept on purpose.**
- Numbered dots only where the order is real (the order you use the app), copying the app's own tab dots.
- One accent colour, the app's orange; colour otherwise comes from the Mars imagery.
- No cards, icons or gradients, except the dark scrim that keeps hero B's text readable.

**Left for the team.**
- Hero A or B.
- One name per view (see `README.md`).
- Hero B's photo shows the layered slopes more than the boxwork network; a tighter crop on the ridges is possible.

## Accessibility (WCAG 2.2 AA)

**Result:** no critical or major issues left after the fixes above.

| Check | Result |
|---|---|
| Text contrast (computed from the tokens) | Light: body 17.8:1, secondary 6.9:1 (6.2:1 on the grey bands), orange links and labels 5.8:1 (5.3:1 on grey), white on the orange button 5.8:1. Dark: body 16.3:1, secondary 8.6:1, orange 7.5:1, dark text on the orange button 7.3:1. Hero B: white text over a scrim of 72–90 % black, about 12:1; the credit line about 6:1. |
| Non-text contrast | Outlined-button borders 3.8:1 (light) and 3.4:1 (dark); focus ring 5.8:1 and 7.5:1. |
| Keyboard | The skip link is the first Tab stop. The order then follows the page: wordmark, header links, then the hero buttons. The focus ring (3 px, offset 3 px) shows in both themes. Enter on an app link shows the mock notice, announced through `role="status"`. |
| Structure | `lang="en"`, one `h1` per page and an `h2` per section. Landmarks: `header`, `nav` "Main", `main` and `footer`, plus `nav` "Steps" on the demo page. Step headings read "Step N: …" to screen readers; the big numbers are `aria-hidden`. |
| Images | Every image has `alt`. The video poster is decorative (`alt=""`) because the text beside it explains it. Screenshots containing UI text are described in their `alt`. |
| Target size | No focusable element smaller than 24×24 px at 1440 and 320 px. Buttons and section links are 44 px; links in the step index are 40 px. |
| Reflow | No horizontal scroll at 320, 375, 768, 1366 or 1440 px (`scrollWidth` equals the viewport). |
| Motion | No animation. Smooth scrolling only under `prefers-reduced-motion: no-preference`. |
| Not tested | Real screen readers (NVDA, VoiceOver) and Windows high-contrast mode. |
