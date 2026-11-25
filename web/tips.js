// In-context tips for the 2D HUD, in the spirit of Apple's TipKit (#125): one short tip
// at a time, next to the control it is about, at the moment it is useful. A tip closes
// with "Got it", with ×, with Esc (while it has focus) or by doing what it suggests,
// and it does not come back. Seen tips are remembered in the browser.
//   ?tips=reset  show every tip again (demo)      ?tips=off  no tips
// No libraries. The HUD is only read (tab state, station count, plan, panels): no id or
// function of web/index.html is changed. The tip list and the choice of the next tip
// are pure functions, tested with Node (tests/web/tips.test.mjs). The engine (box,
// memory, placement, keyboard) is shared with the 3D map: web/tips_core.js.

import * as core from "./tips_core.js";

export const STORAGE_KEY = "martian.tips.v1";
export const tipsMode = core.tipsMode;

// Order = the demo flow. `when(s)`: the moment the tip helps. `done(s)`: the user already
// did it, so the tip is retired without being shown. `anchor`: CSS selector of the control.
export const TIPS = [
  {
    id: "layers",
    anchor: "#show-slope",
    title: "Start with the terrain",
    text: "Switch layers on to see slope, sand and boulders. Hatched cells are too steep to walk.",
    when: s => s.tab === "terrain",
    done: s => s.planned,
  },
  {
    id: "stations",
    anchor: "#load-candidates",
    title: "Add science stations",
    text: "Load Curiosity's drill sites, or tick “Add stations” and click the map. Each type has a science value.",
    when: s => s.tab === "stations",
    done: s => s.planned,
  },
  {
    id: "go-plan",
    anchor: '#panel-stations .next[data-go="plan"]',
    title: "Ready to plan",
    text: "Edit work minutes or science values if you like, then go to step 3.",
    when: s => s.tab === "stations" && s.stations > 0 && s.seen.includes("stations"),
    done: s => s.planned || s.visited.includes("plan"),
  },
  {
    id: "plan",
    anchor: "#plan-btn",
    title: "Plan the walk",
    text: "Set the habitat and the limits, then plan. At every point of the route the planner keeps enough energy and time to walk home.",
    when: s => s.tab === "plan" && !s.planned,
    done: s => s.planned,
  },
  {
    id: "rehearse",
    anchor: "#walk-it",
    title: "Rehearse it",
    text: "Walk the plan step by step and watch the energy used, the energy needed to return and the spare.",
    when: s => s.tab === "plan" && s.planned,
    done: s => s.visited.includes("walk"),
  },
  {
    id: "play",
    anchor: "#play-btn",
    title: "Play the walk",
    text: "Space plays or pauses. The red line on the map is 30 min from the habitat; the dark shade is out of reach with the energy left.",
    when: s => s.tab === "walk" && s.profile,
    done: () => false,
  },
  {
    id: "probe",
    anchor: "#probe > summary",
    title: "Could they still get home?",
    text: "Place the astronaut anywhere on the map with some energy left and see the way back.",
    when: s => s.tab === "walk" && s.seen.includes("play"),
    done: s => s.probeOpen,
  },
  {
    id: "views",
    anchor: 'a[href="/3d/"]',
    title: "Other views of the same plan",
    text: "Open the tablet guide for turn-by-turn steps, or the 3D view to walk it at eye height.",
    when: s => s.tab === "walk" && s.profile && s.seen.includes("probe"),
    done: () => false,
  },
  {
    id: "storm",
    anchor: "#sep-btn",
    title: "What if a solar storm comes?",
    text: "Simulate the alert: the planner sends the astronaut home by the fastest way.",
    when: s => s.tab === "context",
    done: () => false,
  },
];

/** Tips the user already did: they count as seen, so they never show. */
export function retired(state, tips = TIPS) { return core.retired(state, tips); }

/** The one tip to show now, or null: the first unseen, not done, whose moment is now
 *  and whose control is on screen (state.visible(selector)). */
export function nextTip(state, tips = TIPS) { return core.nextTip(state, tips); }

// ------------------------------------------------------------------ browser part

function readState() {
  const tab = document.querySelector('.tabs [role="tab"][aria-selected="true"]')?.dataset.tab || "terrain";
  const count = parseInt(document.getElementById("station-count")?.textContent || "0", 10);
  const profile = document.getElementById("profile");
  return {
    tab,
    stations: Number.isFinite(count) ? count : 0,
    planned: Boolean(document.getElementById("walk-it")) || Boolean(profile && !profile.hidden),
    profile: Boolean(profile && !profile.hidden),
    probeOpen: Boolean(document.getElementById("probe")?.open),
  };
}

export function start({ win = window, storage = window.localStorage } = {}) {
  // Controls in the sidebar: the tip sits just right of it, over the map, so it never
  // covers the controls themselves.
  return core.startTips({tips: TIPS, readState, storageKey: STORAGE_KEY,
                         bars: [{selector: "#side", side: "right"}], win, storage});
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const go = () => { window.martianTips = start(); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go);
  else go();
}
