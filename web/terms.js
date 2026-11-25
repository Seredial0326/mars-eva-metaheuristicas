// Shared glossary for every view of a walk (#124 point 27, #166): the HUD (index.html),
// the arm-tablet guide (guide.html), the wrist card (card.html) and the guide logic
// (guide_core.js). One name per idea, one number format, one set of state words, so the
// same thing reads the same everywhere.
//
// Plain script, no import/export: the HUD loads it with <script src="/terms.js"> before
// its own code, and the modules load it with `import "./terms.js"`. Both read
// globalThis.TERMS.

(function () {
  const NAMES = {
    spare: "Spare energy",            // energy left after returning (Wh)
    home: "Home in",                  // time back to the habitat, against the 30 min line
    homeLimit: "limit 30",
    evaLeft: "EVA time left",
    evaLength: "EVA length",          // the limit set in the planner
    radio: "Radio",
    offRoute: "Off route",
    storm: "Solar storm",
    rehearse: "Rehearse",
    returnHome: "Return home",
    planner: "Planner",
    tablet: "Tablet",
    view3d: "3D",
    card: "Wrist card",
  };

  // State of every meter and alert. Red = turn back now, amber = attention, green = OK.
  // The word always goes with the colour, so meaning never rests on colour alone.
  const STATES = {
    ok: {word: "OK", level: "ok", mark: ""},
    low: {word: "LOW", level: "attention", mark: "!"},
    out: {word: "TURN BACK", level: "alert", mark: "!"},
  };

  // Thresholds the guide, the HUD and the card all use (guide_core.meters).
  const LIMITS = {
    homeS: 1800,          // the 30 min emergency-oxygen line
    homeLowS: 1500,       // LOW from 25 min
    spareLowFrac: 0.25,   // LOW at or under 25 % of usable energy
    evaLowFrac: 0.1,      // LOW at or under 10 % of the EVA length
  };

  // Numbers: whole minutes everywhere; m:ss only on the rehearsal clock.
  const minutes = s => `${Math.round(s / 60)}`;
  const min = s => `${minutes(s)} min`;
  const clock = s => {
    const r = Math.max(0, Math.round(s));            // round first: never "12:60"
    return `${Math.floor(r / 60)}:${String(r % 60).padStart(2, "0")}`;
  };
  const wh = v => `${Math.round(v)} Wh`;
  const homeIn = s => `${NAMES.home} ${minutes(s)} min`;

  globalThis.TERMS = Object.freeze({NAMES, STATES, LIMITS, minutes, min, clock, wh, homeIn,
                                    word: state => (STATES[state] || STATES.ok).word});
})();
