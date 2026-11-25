// In-context tips for the 3D map (#125), with the same engine as the 2D HUD
// (web/tips_core.js): one short tip at a time, next to its control, remembered in the
// browser under its own key. Order = the 3D user guide (docs/user_guide_3d.md): move the
// view, read the plan, relief, rehearse, play, meters, what can go wrong, More, Exit, Sun,
// walk freely. Names and words as on the screen and in web/terms.js.
//   ?tips=reset  show every tip again (demo)      ?tips=off  no tips
// Off with ?check=<name>: a check measures the scene and must not see a tip.
// The page is only read (body classes, hidden panels, button states): no id or function
// of the 3D map changes. The tip list is pure and tested (tests/viz3d/tips_3d.test.mjs).

import * as core from "../tips_core.js";

export const STORAGE_KEY = "martian.tips.3d.v1";

// `s.tab`: "free" (looking around), "rehearse" or "walk"; `s.visited` remembers them.
export const TIPS = [
  {
    id: "view",
    anchor: "#home",
    title: "Move around the ground",
    text: "Drag to turn, right-drag to slide, wheel to zoom (touch: one finger, two fingers, pinch). This button brings back the whole area.",
    when: s => s.loaded && s.tab === "free",
    done: () => false,
  },
  {
    id: "no-plan",
    alt: true,
    anchor: "#plan-default",
    title: "No plan yet",
    text: "Plan a walk in the 2D planner, or plan here with default settings. That replaces the saved plan for the tablet and the card too.",
    when: s => s.noPlan && s.tab === "free",
    done: s => s.hasPlan,
  },
  {
    id: "plan",
    anchor: "#plan-box > summary",
    title: "The plan from the 2D planner",
    text: "Distance, time and energy of the saved plan. Open Stations and pick one to fly there and read its card.",
    when: s => s.hasPlan && s.tab === "free",
    done: s => s.stationsOpen,
  },
  {
    id: "relief",
    anchor: "#relief",
    title: "Make the hills easier to see",
    text: "Raise the local relief to make small hills and slopes look taller. ×1 is the real height.",
    when: s => s.loaded && s.tab === "free" && (s.seen.includes("plan") || s.seen.includes("no-plan")),
    done: s => s.reliefMoved,
  },
  {
    id: "rehearse",
    anchor: "#rehearse",
    title: "Rehearse the walk",
    text: "Walk the plan at eye level, on its own clock, with the tablet's instructions and meters.",
    when: s => s.canRehearse && s.tab === "free",
    done: s => s.visited.includes("rehearse"),
  },
  {
    id: "play",
    anchor: "#rh-play",
    title: "Play the walk",
    text: "Space plays or pauses. The arrow and the distance on top are the tablet's next instruction.",
    when: s => s.tab === "rehearse" && !s.arrived,
    done: s => s.played,
  },
  {
    id: "meters",
    anchor: "#rh-meters",
    title: "Read the meters",
    text: "Spare energy, Home in (limit 30 min), Radio and EVA time left, as on the tablet. Each says OK, LOW or TURN BACK.",
    when: s => s.tab === "rehearse" && s.meters && s.played,
    done: () => false,
  },
  {
    id: "trouble",
    anchor: "#rh-storm",
    title: "Practise what can go wrong",
    text: "Return home, Off route (25 m astray) or Solar storm. The way home is drawn in red, the way back to the route in orange.",
    when: s => s.tab === "rehearse" && s.seen.includes("meters"),
    done: () => false,
  },
  {
    id: "more",
    anchor: "#rh-more",
    title: "More controls",
    text: "Chase view, speed, voice, and Use ×k: test an astronaut who uses more energy than planned.",
    when: s => s.tab === "rehearse" && s.seen.includes("trouble"),
    done: s => s.moreOpen,
  },
  {
    id: "exit",
    anchor: "#rh-exit",
    title: "Leaving the rehearsal",
    text: "Esc only pauses. Exit goes back to the free view. At the habitat, Summary puts the walk next to the plan.",
    when: s => s.tab === "rehearse" && (s.arrived || s.seen.includes("more")),
    done: () => false,
  },
  {
    id: "sun",
    anchor: "#sun-box > summary",
    title: "Light at departure",
    text: "Open Sun and drag the hour to see the shadows the astronaut will meet. Shadows are true to scale at relief ×1.",
    when: s => s.tab === "free" && s.visited.includes("rehearse"),
    done: s => s.sunOpen,
  },
  {
    id: "walk",
    anchor: "#walk",
    title: "Walk freely",
    text: "Walk anywhere at eye level: W/S or ↑/↓, A/D sideways, ←/→ turn, Shift runs. A game: slope and energy limits do not apply.",
    when: s => s.tab === "free" && s.visited.includes("rehearse") && s.seen.includes("sun"),
    done: s => s.visited.includes("walk"),
  },
];

export const tipsMode = core.tipsMode;
export function retired(state, tips = TIPS) { return core.retired(state, tips); }
export function nextTip(state, tips = TIPS) { return core.nextTip(state, tips); }

/** Tips run unless ?tips=off or a ?check= is running. */
export function tipsOn(search) {
  const p = new URLSearchParams(search || "");
  return !p.get("check") && core.tipsMode(search) !== "off";
}

// ------------------------------------------------------------------ browser part

// What the user did once stays done for this page (a tip waits for "after you played").
const sticky = {played: false, stationsOpen: false, moreOpen: false, sunOpen: false, reliefMoved: false};

function readState() {
  const $ = id => document.getElementById(id);
  const body = document.body.classList;
  const tab = body.contains("walking") ? "walk" : body.contains("rehearsing") ? "rehearse" : "free";
  const planBox = $("plan-default-box");
  const facts = ($("plan-facts")?.textContent || "").trim();
  const play = $("rh-play")?.textContent || "";
  if (/pause/i.test(play)) sticky.played = true;
  if (document.querySelector("#plan-box .stop-picker")?.open) sticky.stationsOpen = true;
  if ($("rh-more")?.getAttribute("aria-expanded") === "true") sticky.moreOpen = true;
  if ($("sun-box")?.open) sticky.sunOpen = true;
  return {
    tab,
    loaded: Boolean(window.viz3d && window.viz3d.terrain),
    hasPlan: Boolean(facts) && Boolean(planBox && planBox.hidden),
    noPlan: Boolean(planBox && !planBox.hidden),
    canRehearse: Boolean($("rehearse") && !$("rehearse").disabled),
    meters: Boolean($("rh-meters") && !$("rh-meters").hidden),
    arrived: Boolean($("player")?.classList.contains("rh-arrived")),
    ...sticky,
  };
}

export function start({ win = window, storage = window.localStorage } = {}) {
  if (!tipsOn(win.location.search)) return null;
  document.getElementById("relief")?.addEventListener("input", () => { sticky.reliefMoved = true; });
  return core.startTips({
    tips: TIPS, readState, storageKey: STORAGE_KEY, win, storage,
    // The side panel and the bars at the bottom stay readable: the tip goes beside the
    // panel, or above the player and the walk bar.
    bars: [{selector: "#info", side: "right"}, {selector: "#player", side: "above"},
           {selector: "#walk-bar", side: "above"}],
    attributes: ["hidden", "open", "class", "disabled", "aria-expanded"],
    // No tip over a rover photo or while the mouse is captured to look around.
    paused: () => document.body.classList.contains("photo-view") || Boolean(document.pointerLockElement),
  });
}

if (typeof window !== "undefined" && typeof document !== "undefined") {
  const go = () => { window.martianTips = start(); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", go);
  else go();
}
