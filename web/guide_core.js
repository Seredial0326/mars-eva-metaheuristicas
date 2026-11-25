// Guide logic shared by the two views of a walk: the arm-tablet guide (web/guide.html,
// 2D map) and the 3D rehearsal (web/3d/). No drawing here: maneuvers, voice, the
// "can I make it back?" meters, and the server calls for the way home, rejoining the
// route and the solar storm. Pure functions take a `route` object:
//
//   {coords: [[x, y], ...]   Mars CRS metres, one per vertex
//    t: [s], used: [Wh]      EVA clock and energy used at each vertex (absolute)
//    rv: [Wh] | null         energy needed to return from each vertex (E4's R(v))
//    rvTime: [s] | null      time to return from each vertex
//    usable: Wh              usable energy (budget minus margin)
//    turnIndex, goalName     single-goal round trip (E4)
//    stops: [{i, name}]      multi-station tour (E5): vertex index and station id
//    kind: "plan" | "home"}  "home" after Return home (drawn red, no station cards)
//
// prepareRoute(route) adds `d` (cumulative distance) and `events` (maneuvers).
//
// Names, state words, thresholds and number formats come from the shared glossary
// (web/terms.js, #166), the same one the HUD and the wrist card use.
import "./terms.js";
const T = globalThis.TERMS;

export const OFF_ROUTE_M = 15;          // farther than this from the route: off route
export const REJOIN_AHEAD_M = 30;       // rejoin this far ahead of the nearest point
export const EMERGENCY_RETURN_S = 1800; // the red line: 30 min of emergency oxygen
export const STATION_RADIUS_M = 12;     // closer than this to a station: arrived

export const TASKS = {
  ridge: ["Photograph the ridge wall and its central fracture", "Sample the ridge cement (clays + Fe oxides)"],
  hollow: ["Image the hollow floor", "Sample bedrock under the sand (siderite)", "Watch your footing: loose sand"],
  contact: ["Photograph both sides of the contact", "Sample each unit near the contact"],
  curiosity: ["Find and photograph Curiosity's drill hole", "Compare the rock with the rover's data"],
};

// --- voice -----------------------------------------------------------------
// Voice with priorities. An alert (storm, turn back, off route) interrupts whatever is
// being said and cannot be interrupted by a routine line; routine lines (turns, arrivals,
// radio) wait for the current one to finish, and only the two newest are kept, so a
// late instruction never talks over a safety alert. repeat() says the last line again.
export function createVoice({lang = "en-US", rate = 1.0, synth = globalThis.speechSynthesis} = {}) {
  let on = true, speaking = null, last = "";
  const queue = [];
  const can = () => on && synth && typeof SpeechSynthesisUtterance !== "undefined";
  const next = () => {
    speaking = null;
    if (!queue.length || !can()) return;
    const item = queue.shift();
    start(item.text, item.priority);
  };
  const start = (text, priority) => {
    const u = new SpeechSynthesisUtterance(text); u.lang = lang; u.rate = rate;
    u.onend = u.onerror = () => { if (speaking === u) next(); };
    speaking = u; u.priority = priority; last = text;
    synth.speak(u);
  };
  return {
    get on() { return on; },
    get last() { return last; },
    set(value) { on = Boolean(value); if (!on) { queue.length = 0; speaking = null; if (synth) synth.cancel(); } return on; },
    toggle() { return this.set(!on); },
    say(text, {priority = "normal"} = {}) {
      if (!can()) return false;
      if (priority === "alert") {
        queue.splice(0, queue.length, ...queue.filter(q => q.priority === "alert"));
        if (speaking && speaking.priority === "alert") { queue.push({text, priority}); return true; }
        synth.cancel(); start(text, priority); return true;
      }
      if (!speaking) { start(text, priority); return true; }
      queue.push({text, priority});
      while (queue.filter(q => q.priority !== "alert").length > 2) queue.splice(queue.findIndex(q => q.priority !== "alert"), 1);
      return true;
    },
    repeat() { return last ? this.say(last) : false; },
  };
}

// --- maneuvers from the route geometry -------------------------------------
export function cumulativeDistance(c) {
  const d = [0];
  for (let i = 1; i < c.length; i++) d.push(d[i - 1] + Math.hypot(c[i][0] - c[i - 1][0], c[i][1] - c[i - 1][1]));
  return d;
}

export function headingAt(c, d, i, span) {
  // Heading (rad, east = 0, counter-clockwise) over +-span metres, robust to 1 m staircases.
  let a = i, b = i;
  while (a > 0 && d[i] - d[a] < span) a--;
  while (b < c.length - 1 && d[b] - d[i] < span) b++;
  return Math.atan2(c[b][1] - c[a][1], c[b][0] - c[a][0]);
}

export function buildEvents(c, d, turnIndex, goalName, endText, stops) {
  // stops: [{i, name}] for a multi-station tour (E5); otherwise the single goal at turnIndex.
  const stopIdx = (stops || []).map(s => s.i).concat(turnIndex != null ? [turnIndex] : []);
  const ev = [];
  let last = -1e9;
  for (let i = 0; i < c.length; i++) {
    if (d[i] - last < 25 || d[i] < 10 || d[d.length - 1] - d[i] < 10) continue;
    // turnarounds at stations are announced as arrivals, not as sharp turns
    if (stopIdx.some(k => Math.abs(d[i] - d[k]) < 25)) continue;
    let ahead = i; while (ahead < c.length - 1 && d[ahead] - d[i] < 15) ahead++;
    let behind = i; while (behind > 0 && d[i] - d[behind] < 15) behind--;
    const hin = headingAt(c, d, behind, 8), hout = headingAt(c, d, ahead, 8);
    let delta = (hout - hin) * 180 / Math.PI;
    delta = ((delta + 540) % 360) - 180;                     // -180..180, + = left
    if (Math.abs(delta) < 40) continue;
    const side = delta > 0 ? "left" : "right";
    const kind = Math.abs(delta) > 135 ? "Sharp " + side : Math.abs(delta) > 70 ? "Turn " + side : "Bear " + side;
    const arrow = Math.abs(delta) > 135 ? (delta > 0 ? "↶" : "↷") : delta > 0 ? (Math.abs(delta) > 70 ? "←" : "↖") : (Math.abs(delta) > 70 ? "→" : "↗");
    ev.push({i, dist: d[i], text: kind, arrow}); last = d[i];
  }
  if (stops && stops.length) {
    for (const s of stops) ev.push({i: s.i, dist: d[s.i], text: `Arrive at station ${s.name}`, arrow: "⚑", goal: true});
  } else if (turnIndex != null && turnIndex > 0 && turnIndex < c.length - 1) {
    ev.push({i: turnIndex, dist: d[turnIndex], text: goalName, arrow: "⚑", goal: true});
  }
  ev.push({i: c.length - 1, dist: d[c.length - 1], text: endText, arrow: "⌂", end: true});
  return ev.sort((a, b) => a.dist - b.dist);
}

export function prepareRoute(r) {
  r.d = cumulativeDistance(r.coords);
  r.events = buildEvents(r.coords, r.d, r.turnIndex, r.goalName, "Arrive at the habitat", r.stops);
  return r;
}

// The route of the plan saved by the HUD (GET /plan/last), ready to walk.
export function routeFromPlan(saved) {
  const feats = saved.plan.features;
  const f = feats.find(x => x.properties.kind === "route");
  const goalSt = feats.find(x => x.properties.kind === "goal");
  const goalName = goalSt && goalSt.properties.station ? `Arrive at station ${goalSt.properties.station}` : "Arrive at the goal";
  const p = f.properties;
  const stops = (p.stop_index || []).map((i, k) => ({i, name: p.visit_order[k]}));
  return prepareRoute({coords: f.geometry.coordinates, t: p.t_s, used: p.used_wh, rv: p.rv_wh, rvTime: p.rv_time_s,
                       usable: p.usable_wh, turnIndex: p.turn_index, goalName, kind: "plan", stops});
}

// Maximum EVA duration of the saved plan (s), or null when the plan had none.
export function evaLimitS(saved) {
  const m = saved && saved.request && saved.request.max_duration_min;
  return Number.isFinite(m) && m > 0 ? m * 60 : null;
}

// Next maneuver from vertex i: the event, the metres to it and the banner text.
export function nextManeuver(r, i) {
  const next = r.events.find(e => e.dist > r.d[i] + 1) || r.events[r.events.length - 1];
  const togo = Math.max(0, next.dist - r.d[i]);
  return {event: next, togo, distText: togo < 5 ? "now" : `in ${Math.round(togo / 10) * 10} m`};
}

// What to say at vertex i ("In 80 meters, turn left", then "Turn left"), each once.
export function announcements(r, i, spoken) {
  const {event: next, togo} = nextManeuver(r, i);
  const out = [];
  for (const th of [80, 20]) {
    const key = `${r.kind}-${next.i}-${th}`;
    if (togo <= th && togo > (th === 80 ? 20 : 0) && !spoken.has(key)) {
      spoken.add(key);
      // At a station the card says the arrival itself, so the 20 m call is skipped there.
      if (th === 20 && next.goal) continue;
      const lower = next.text.charAt(0).toLowerCase() + next.text.slice(1);     // keep "R3", lower only "Turn"
      out.push(th === 80 ? `In ${Math.round(togo / 10) * 10} meters, ${lower}` : next.text);
    }
  }
  return out;
}

// "Can I make it back?" at vertex i, and how much of the EVA's time is left.
//   energy: left after returning (Wh) out of usable; good while above 25 %.
//   back:   time to the habitat against the 30 min line; good up to 25 min.
//   eva:    elapsed EVA time against max_duration (null when there is no limit).
export function meters(r, i, limitS = null) {
  const used = r.used[i], need = r.rv ? r.rv[i] : 0, left = r.usable - used - need;
  const back = r.rvTime ? r.rvTime[i] : r.t[r.t.length - 1] - r.t[i];
  // Every bar means "how much is left": full is good, empty is the limit. Each also
  // carries a state word, so meaning never rests on colour alone.
  const L = T.LIMITS;
  const eState = left <= 0 ? "out" : left <= L.spareLowFrac * r.usable ? "low" : "ok";
  const bState = back > EMERGENCY_RETURN_S ? "out" : back > L.homeLowS ? "low" : "ok";
  const out = {
    energy: {leftWh: left, usableWh: r.usable, frac: left / r.usable, good: eState === "ok", state: eState,
             word: T.word(eState),
             text: `${left.toFixed(0)} of ${r.usable.toFixed(0)} Wh`},
    back: {s: back, marginS: EMERGENCY_RETURN_S - back, frac: 1 - back / EMERGENCY_RETURN_S, good: bState === "ok", state: bState,
           word: T.word(bState),
           text: `home in ${T.minutes(back)} min`},
    eva: null,
  };
  if (limitS) {
    const elapsed = r.t[i], leftS = limitS - elapsed, endS = elapsed + back;   // back home if you turn now
    const vState = endS > limitS ? "out" : leftS <= L.evaLowFrac * limitS ? "low" : "ok";
    out.eva = {elapsedS: elapsed, limitS, leftS, frac: leftS / limitS, state: vState,
               good: vState === "ok", overrun: r.t[r.t.length - 1] > limitS,
               word: T.word(vState),
               text: `${T.minutes(Math.max(0, leftS))} of ${T.minutes(limitS)} min left`};
  }
  return out;
}

// Stations the walker reaches at vertex i (planned ones only, each once).
export function arrivals(r, i, stationFeatures, visited) {
  if (r.kind !== "plan") return [];
  const here = r.coords[i], out = [];
  for (const f of stationFeatures) {
    const id = f.properties.id, [sx, sy] = f.geometry.coordinates;
    if (f.properties.visited === false) continue;              // not in the E5 tour
    if (!visited.has(id) && Math.hypot(sx - here[0], sy - here[1]) < STATION_RADIUS_M) {
      visited.add(id); out.push(f.properties);
    }
  }
  return out;
}

// Card of a station: title, why it matters (rubric) and the tasks of its type.
export function stationCard(p, rubric) {
  const type = (rubric || {})[p.type];
  return {title: `Station ${p.id}${type ? " · " + type.label : ""} · ${p.service_time_min ?? 10} min`,
          why: type ? type.why : "", tasks: TASKS[p.type] || ["Document the site"],
          speech: `Arrived at station ${p.id}. ${type ? type.label : ""}.`};
}

// Vertex index reached after `seconds` of EVA clock from vertex i.
export function advance(r, i, seconds) {
  const target = r.t[i] + seconds;
  let k = i; while (k < r.t.length - 1 && r.t[k] < target) k++;
  return k;
}

// --- server calls ----------------------------------------------------------
const post = async (url, body) => {
  const res = await fetch(url, {method: "POST", headers: {"Content-Type": "application/json"}, body: JSON.stringify(body)});
  const out = await res.json();
  if (!res.ok) throw new Error(typeof out.detail === "string" ? out.detail : `HTTP ${res.status}`);
  return out;
};

const planLimits = saved => ({habitat: saved.plan.properties.habitat,
                              max_cell_slope_deg: saved.plan.properties.max_cell_slope_deg,
                              human_cost: saved.plan.properties.human_cost !== false});

// What the walker has left (#119 A2), sent with the way home and the rejoin so the
// server checks energy, time and O2 on the same path. Energy: the usable budget (the
// plan's margin is already out of it) minus what was used; time: the plan's maximum
// EVA duration minus the clock; O2: the plan's O2 budget minus the O2 of that energy.
export const KJ_PER_L_O2 = 20.1;
export function remaining(r, saved, t0, u0) {
  const out = {energy_remaining_wh: Math.max(0, r.usable - u0)};
  const limit = evaLimitS(saved);
  if (limit !== null) out.time_remaining_s = Math.max(0, limit - t0);
  const o2 = saved && saved.request && saved.request.o2_budget_l;
  if (Number.isFinite(o2) && o2 > 0) out.o2_remaining_l = Math.max(0, o2 - u0 * 3.6 / KJ_PER_L_O2);
  return out;
}

const RESOURCE_WORD = {energy: "energy", time: "time", o2: "oxygen"};
const limitingWords = d => (d && d.limiting || []).map(n => RESOURCE_WORD[n] || n).join(" and ");

// Way home from vertex i (POST /guide/return_home), as a route of kind "home": the
// fastest one that fits what is left, a slower one that does, or (feasible false) the
// least-energy one with a warning, never the fastest as if it were safe.
// The EVA clock and the energy keep counting from where the walker was. now: {t, used}
// of the walker when it is between vertices or standing at a stop (else vertex i's).
export async function returnHome(r, i, saved, here = r.coords[i], now = null) {
  const t0 = now ? now.t : r.t[i], u0 = now ? now.used : r.used[i];
  const out = await post("/guide/return_home", {position: here, ...planLimits(saved),
                                                ...remaining(r, saved, t0, u0)});
  const f = out.features[0], p = f.properties;
  // On the way home, what returning still needs is what is left of this path.
  const route = prepareRoute({coords: f.geometry.coordinates, t: p.t_s.map(v => v + t0),
                              used: p.used_wh.map(v => v + u0), rv: p.used_wh.map(v => p.energy_wh - v),
                              rvTime: p.t_s.map(v => p.time_s - v),
                              usable: r.usable, turnIndex: null, goalName: "", kind: "home"});
  const base = `${T.NAMES.returnHome}: ${T.min(p.time_s)}, ${p.length_m.toFixed(0)} m, ${p.energy_wh.toFixed(0)} Wh.`;
  if (p.feasible === false) {
    const what = limitingWords(p.diagnosis) || "resources";
    return {route, summary: p, feasible: false,
            text: `${base} Not enough ${what} left for any way home: walking the least-energy one. Call the habitat.`,
            speech: `Warning. Not enough ${what} to reach the habitat. Walk home now on the least energy path and call the habitat.`};
  }
  const slower = p.choice === "tradeoff" || p.choice === "least_energy";
  return {route, summary: p, feasible: p.feasible === true ? true : null,
          text: slower ? `${base} Slower than the fastest way, which would not fit the ${limitingWords({limiting: p.fastest.failing})} left.` : base,
          speech: `Returning home. ${Math.round(p.time_s / 60)} minutes.`};
}

// Where pt meets the route, searching from vertex `from` on. dist: the smallest distance.
// k: the FIRST vertex ahead within NEAR_TIE_M of that distance, so on a round trip with
// parallel legs a walker on the way out rejoins the way out and does not skip the goal.
export const NEAR_TIE_M = 10;
export function nearestOnRoute(r, pt, from = 0) {
  const dd = k => Math.hypot(r.coords[k][0] - pt[0], r.coords[k][1] - pt[1]);
  let bestD = Infinity;
  for (let k = from; k < r.coords.length; k++) bestD = Math.min(bestD, dd(k));
  let k = from;
  while (k < r.coords.length - 1 && dd(k) > bestD + NEAR_TIE_M) k++;
  return {k, dist: bestD};
}

// Demo: a point 25 m to the left of the walking direction at vertex i.
export function detourPoint(r, i) {
  const c = r.coords, a = Math.min(i, c.length - 2), b = Math.min(c.length - 1, a + 10);
  const hx = c[b][0] - c[a][0], hy = c[b][1] - c[a][1], n = Math.hypot(hx, hy) || 1;
  return [c[a][0] - 25 * hy / n, c[a][1] + 25 * hx / n];
}

// Off route at pt while at vertex i: null if within OFF_ROUTE_M, else the new route
// (least-energy path back to the route a little ahead, then the rest of the plan with
// its clock and energy shifted), from POST /guide/rejoin.
export async function rejoin(r, i, pt, saved, now = null) {
  const near = nearestOnRoute(r, pt, i);
  if (near.dist <= OFF_ROUTE_M) return null;
  let j = near.k;
  while (j < r.coords.length - 1 && r.d[j] - r.d[near.k] < REJOIN_AHEAD_M) j++;
  const t0 = now ? now.t : r.t[i], u0 = now ? now.used : r.used[i];
  const last = r.coords.length - 1;
  const out = await post("/guide/rejoin", {position: pt, target: r.coords[j], ...planLimits(saved),
                                           ...remaining(r, saved, t0, u0),
                                           continuation: {energy_wh: Math.max(0, r.used[last] - r.used[j]),
                                                          time_s: Math.max(0, r.t[last] - r.t[j])}});
  const p = out.features[0].properties, rc = out.features[0].geometry.coordinates;
  const dt = t0 + p.time_s - r.t[j], du = u0 + p.energy_wh - r.used[j];
  const tail = k => k > j;
  const route = prepareRoute({...r,
    coords: rc.concat(r.coords.filter((_, k) => tail(k))),
    t: p.t_s.map(v => v + t0).concat(r.t.filter((_, k) => tail(k)).map(v => v + dt)),
    used: p.used_wh.map(v => v + u0).concat(r.used.filter((_, k) => tail(k)).map(v => v + du)),
    rv: r.rv ? p.rv_wh.concat(r.rv.filter((_, k) => tail(k))) : null,
    rvTime: r.rvTime ? p.rv_time_s.concat(r.rvTime.filter((_, k) => tail(k))) : null,
    turnIndex: r.turnIndex != null && r.turnIndex > j ? r.turnIndex - (j + 1) + rc.length : null,
    stops: (r.stops || []).filter(s => s.i > j).map(s => ({...s, i: s.i - (j + 1) + rc.length}))});
  // goHome (#119 A2): rejoining is possible, but the way home along it or the rest of
  // the plan no longer fits what is left; the caller should go home instead.
  const goHome = p.feasible === false;
  return {route, offM: near.dist, goHome, diagnosis: p.diagnosis || null,
          text: goHome ? `Rejoining no longer fits the ${limitingWords(p.diagnosis) || "resources"} left. Go home instead.`
                       : `Back on track: ${p.time_s.toFixed(0)} s to rejoin the route.`};
}

// Solar storm (E12): the dose on the way home for the real event and a 50x storm.
export function stormMessage(homeRoute, radInfo) {
  const tH = (homeRoute.t[homeRoute.t.length - 1] - homeRoute.t[0]) / 3600;
  const sc = radInfo ? radInfo.scenarios : [];
  const real = sc.find(s => s.id === "real"), x50 = sc.find(s => s.id === "x50");
  return {minutes: tH * 60,
          realUgy: real ? tH * real.rate_ugy_h : null, x50Ugy: x50 ? tH * x50.rate_ugy_h : null,
          rule: "RAD rate above 1.5× its 3-day median, 2 readings in a row"};
}

// The alert both views show once the way home is known (HTML), and while it is computed.
// The banner says only what to do (#124): the live time home is on the maneuver card,
// so no frozen minutes here. Dose and the alarm rule stay, folded.
export function stormHtml(s) {
  const dose = s.realUgy != null
    ? `Dose on the way back: ${s.realUgy.toFixed(1)} µGy` +
      (s.x50Ugy != null ? ` (${s.x50Ugy.toFixed(0)} µGy if it were 50× stronger).` : ".") : "";
  return `<b>SOLAR STORM · return home now</b>` +
    `<details class="more"><summary>Why and how much</summary>${dose}` +
    ` <span class="muted">Alarm when the radiation rate on Curiosity exceeds 1.5× its recent median twice in a row.</span></details>`;
}
export const STORM_PENDING = "<b>SOLAR STORM · return home now</b> · finding the fastest way…";
export const stormFailedHtml = why =>
  `<b>SOLAR STORM · return home now</b> · the way home could not be computed: ${why}`;

// --- radio (E11, JB): line of sight to the habitat antenna, and the pair relay ----------
// POST /comms/check answers, per route vertex, radio_ok (one astronaut sees the habitat
// antenna) and pair_state ("direct" / "relay" / "none": a partner walking behind can relay).
// attachComms(r, habitat) adds r.radio, r.pair and r.radioEvents; without the API (no
// GDAL, E11 not merged) the route simply has no radio and the views hide the meter.
export const RADIO_WARN_M = 80;          // announce a radio loss this far ahead
export const RADIO_FLICKER_M = 10;       // radio back for less than this is not "back"

export async function attachComms(r, habitat) {
  try {
    const out = await post("/comms/check", {route: {coordinates: r.coords, t_s: r.t}, habitat});
    const p = out.properties || {};
    if (!Array.isArray(p.radio_ok) || p.radio_ok.length !== r.coords.length) return r;
    r.radio = p.radio_ok.map(Boolean);
    r.pair = Array.isArray(p.pair_state) && p.pair_state.length === r.coords.length ? p.pair_state : null;
    r.radioEvents = radioEvents(r);
  } catch { /* no radio data: the meter stays hidden */ }
  return r;
}

// Direct radio with flickers removed: a stretch WITH radio shorter than RADIO_FLICKER_M
// between two silent stretches counts as silent (the DEM edge of a shadow), so the voice
// does not say "radio back" and "you lose radio" a metre apart.
export function steadyRadio(radio, d) {
  const out = radio.slice();
  for (let a = 0; a < out.length; a++) {
    if (!out[a]) continue;
    let b = a; while (b + 1 < out.length && out[b + 1]) b++;
    if (a > 0 && b < out.length - 1 && d[b] - d[a] < RADIO_FLICKER_M) out.fill(false, a, b + 1);
    a = b;
  }
  return out;
}

// Where direct radio is lost and recovered along the route, with the silent time.
export function radioEvents(r) {
  const ev = [], radio = steadyRadio(r.radio, r.d);
  for (let k = 1; k < radio.length; k++) {
    if (radio[k - 1] && !radio[k]) {
      let e = k; while (e < radio.length - 1 && !radio[e]) e++;
      const relay = r.pair ? r.pair.slice(k, e).every(s => s !== "none") : false;
      ev.push({i: k, dist: r.d[k], kind: "loss", silentS: r.t[e] - r.t[k], relay});
    } else if (!radio[k - 1] && radio[k]) {
      ev.push({i: k, dist: r.d[k], kind: "back"});
    }
  }
  return ev;
}

// Radio state at vertex i for the meter: null when the route has no radio data.
export function radioState(r, i) {
  if (!r.radio) return null;
  const pair = r.pair ? r.pair[i] : null;
  if (r.radio[i]) return {state: "direct", good: true, text: "Direct to the habitat"};
  if (pair === "relay") return {state: "relay", good: true, text: "Relay through your partner"};
  return {state: "none", good: false, text: "No radio link"};
}

// Spoken radio warnings: "In 80 meters you lose direct radio for 7 minutes", "Radio back".
export function radioAnnouncements(r, i, spoken) {
  if (!r.radioEvents) return [];
  const out = [];
  for (const e of r.radioEvents) {
    const togo = e.dist - r.d[i], key = `${r.kind}-radio-${e.i}`;
    if (e.kind === "loss" && togo <= RADIO_WARN_M && togo > 0 && !spoken.has(key)) {
      spoken.add(key);
      const min = Math.max(1, Math.round(e.silentS / 60));
      out.push(`In ${Math.max(10, Math.round(togo / 10) * 10)} meters you lose direct radio for about ${min} minute${min > 1 ? "s" : ""}` +
               (e.relay ? ". Your partner can relay." : ". Stay with your partner."));
    } else if (e.kind === "back" && togo <= 0 && togo > -15 && !spoken.has(key)) {
      spoken.add(key);
      out.push("Direct radio back.");
    }
  }
  return out;
}

// --- plan against the walk (P6, #45) -------------------------------------------------
// A log of what was actually walked (simulated in the demo): positions, clock, energy,
// radio, arrivals and events (detour, way home, storm). At the habitat, walkSummary()
// compares it with the plan; postWalk() keeps it for the debrief (POST /walks).
const LOG_STEP_M = 1;                    // a point every metre at most

export function createWalkLog(planRoute) {
  const n = planRoute.coords.length - 1;
  const planned = planRoute.stops && planRoute.stops.length ? planRoute.stops.map(s => s.name)
    : (planRoute.goalName || "").startsWith("Arrive at station ") ? [planRoute.goalName.slice(18)] : [];
  return {
    plan: {coords: planRoute.coords, timeS: planRoute.t[n] - planRoute.t[0], energyWh: planRoute.used[n],
           lengthM: planRoute.d[n], stations: planned, t0: planRoute.t[0],
           noRadioM: planRoute.radio ? silentMetres(planRoute.radio, planRoute.d) : null},
    points: [], events: [], visited: [], done: false, route: null, lastI: -1,
    planRoute,                                  // its radio may arrive later (attachComms)
  };
}

function silentMetres(radio, d) {
  let m = 0;
  for (let k = 1; k < radio.length; k++) if (!radio[k]) m += d[k] - d[k - 1];
  return m;
}

// One step of the walk: vertex i of the route being walked, at position pos. When the
// walker moves along the route (onRoute), the vertices skipped since the last step are
// logged too, so a fast simulation (x180 jumps ~30 m per tick) does not cut corners.
export function logStep(log, r, i, pos = r.coords[i], onRoute = true) {
  if (onRoute && log.route === r && i > log.lastI + 1) {
    for (let k = log.lastI + 1; k < i; k++) pushPoint(log, r, k, r.coords[k]);
  }
  pushPoint(log, r, i, pos);
  log.route = r; log.lastI = i;
}

function pushPoint(log, r, i, pos) {
  const last = log.points[log.points.length - 1];
  if (last && last.kind === r.kind && Math.hypot(pos[0] - last.x, pos[1] - last.y) < LOG_STEP_M) return;
  log.points.push({x: pos[0], y: pos[1], t: r.t[i], used: r.used[i], kind: r.kind, radio: r.radio ? r.radio[i] : null});
}

export function logEvent(log, kind, text, r = null, i = 0) {
  log.events.push({kind, text, t: r ? r.t[i] : null});
}

export function logArrival(log, id) { if (!log.visited.includes(id)) log.visited.push(id); }

// The walk against the plan. Off-route distances are to the nearest planned vertex
// (the planned line has a vertex every metre or so).
export function walkSummary(log) {
  const pts = log.points, p = log.plan;
  if (pts.length < 2) return null;
  let length = 0, silent = 0, maxOff = 0, sumOff = 0;
  for (let k = 0; k < pts.length; k++) {
    if (k) {
      const step = Math.hypot(pts[k].x - pts[k - 1].x, pts[k].y - pts[k - 1].y);
      length += step;
      if (pts[k].radio === false) silent += step;
    }
    let best = Infinity;
    for (const c of p.coords) { const dd = Math.hypot(c[0] - pts[k].x, c[1] - pts[k].y); if (dd < best) best = dd; }
    maxOff = Math.max(maxOff, best); sumOff += best;
  }
  const end = pts[pts.length - 1];
  const walked = {timeS: end.t - p.t0, energyWh: end.used, lengthM: length,
                  stations: log.visited.slice(), maxOffRouteM: maxOff, meanOffRouteM: sumOff / pts.length,
                  noRadioM: pts.some(q => q.radio !== null) ? silent : null,
                  wentHome: pts.some(q => q.kind === "home")};
  const planRadio = p.noRadioM ?? (log.planRoute && log.planRoute.radio ? silentMetres(log.planRoute.radio, log.planRoute.d) : null);
  return {
    plan: {timeS: p.timeS, energyWh: p.energyWh, lengthM: p.lengthM, stations: p.stations, noRadioM: planRadio},
    walked,
    skipped: p.stations.filter(id => !walked.stations.includes(id)),
    delta: {timeS: walked.timeS - p.timeS, energyWh: walked.energyWh - p.energyWh, lengthM: walked.lengthM - p.lengthM},
    events: log.events.slice(),
  };
}

// Rows for a "plan against the walk" table: [label, plan, walked].
export function summaryRows(s) {
  const min = T.min, wh = v => `${v.toFixed(0)} Wh`, m = v => `${v.toFixed(0)} m`;
  const rows = [["Time", min(s.plan.timeS), min(s.walked.timeS)],
                ["Energy", wh(s.plan.energyWh), wh(s.walked.energyWh)],
                ["Distance", m(s.plan.lengthM), m(s.walked.lengthM)],
                ["Stations", `${s.plan.stations.length}`, `${s.walked.stations.length}`]];
  if (s.plan.noRadioM != null || s.walked.noRadioM != null) {
    rows.push(["No direct radio", s.plan.noRadioM == null ? "—" : m(s.plan.noRadioM),
               s.walked.noRadioM == null ? "—" : m(s.walked.noRadioM)]);
  }
  rows.push(["Farthest from the plan", "0 m", m(s.walked.maxOffRouteM)]);
  return rows;
}

export async function postWalk(summary, log) {
  try {
    const res = await fetch("/walks", {method: "POST", headers: {"Content-Type": "application/json"},
      body: JSON.stringify({summary, points: log.points.map(q => [q.x, q.y, q.t, q.used, q.kind, q.radio])})});
    return res.ok ? (await res.json()).saved : null;
  } catch { return null; }
}

// --- adaptive walkback (X2, #101) --------------------------------------------------
// The planner trusts E3's cost. During the walk the guide learns this astronaut's own
// factor k (real use = k x E3) from each walked segment, through POST /walkback/update
// (stateless: the posterior it returns is sent back with the next segment), and re-checks
// the way home with the 90th percentile k_p90. In the demo the "real" use is simulated
// from a chosen k_true with noise per segment; there is no O2 sensor behind it.
export const K_SEG_M = 30;               // one observation every 30 m walked
export const K_NOISE = 0.15;             // simulated noise of log(real / E3) per segment
export const K_TRUE_CHOICES = [1.0, 1.2, 1.5, 0.8];

// Small seeded generator (mulberry32) and a normal draw, so a demo walk is repeatable.
function rng(seed) {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
function normal(rand) {
  const u = Math.max(rand(), 1e-12), v = rand();
  return Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v);
}

export function createAdaptive({kTrue = 1.0, seed = 101, noise = K_NOISE} = {}) {
  return {kTrue, noise, rand: rng(seed), route: null, lastI: 0, usedReal: 0,
          result: null, history: [], firstAlarm: null, firstAlarmFixed: null, chain: Promise.resolve()};
}

// A new route (way home, rejoin): segments restart at its first vertex; the real use
// so far carries on.
export function adaptiveNewRoute(state, r) { state.route = r; state.lastI = 0; }

// The segment walked since the last observation, when it is at least K_SEG_M long (or
// the route ends): E3's predicted use and the simulated real use. null otherwise.
export function adaptiveSegment(state, r, i) {
  if (state.route !== r) adaptiveNewRoute(state, r);
  const j = state.lastI;
  if (i <= j || (r.d[i] - r.d[j] < K_SEG_M && i < r.coords.length - 1)) return null;
  const predicted = Math.max(0, r.used[i] - r.used[j]);
  const observed = state.kTrue * predicted * Math.exp(state.noise * normal(state.rand));
  state.lastI = i; state.usedReal += observed;
  return {i, predicted, observed};
}

// Body of POST /walkback/update for vertex i after a segment (Wh throughout).
export function adaptiveRequest(state, r, i, seg) {
  return {posterior: state.result ? state.result.posterior : null,
          segment: seg ? {observed: seg.observed, predicted: seg.predicted} : null,
          unit: "Wh", used: state.usedReal, budget: r.usable,
          return_predicted: r.rv ? r.rv[i] : 0,
          plan_used: r.used.slice(i), plan_return: r.rv ? r.rv.slice(i) : r.used.slice(i).map(() => 0)};
}

// Observe vertex i: when a segment is due, ask the server (calls are chained so each
// carries the previous posterior). Resolves to the new result, or null when nothing
// was due. postFn is injectable for tests.
export function adaptiveStep(state, r, i, postFn = post) {
  const seg = adaptiveSegment(state, r, i);
  if (!seg) return Promise.resolve(null);
  const at = {d: r.d[i], t: r.t[i], kind: r.kind};
  state.chain = state.chain.then(async () => {
    const res = await postFn("/walkback/update", adaptiveRequest(state, r, i, seg));
    state.result = res;
    state.history.push({...at, k: res.k.median, lo: res.k.ci90[0], hi: res.k.ci90[1],
                        kReserve: res.k.reserve, returnNow: res.return_now, fixedReturnNow: res.fixed.return_now});
    if (res.return_now && !state.firstAlarm) state.firstAlarm = at;
    if (res.fixed.return_now && !state.firstAlarmFixed) state.firstAlarmFixed = at;
    return res;
  }).catch(() => null);
  return state.chain;
}

// The learned-k meter, in the style of meters(): "spare energy after returning" with the
// real use so far and the way home at k_p90. Full is good; a state word always.
export function kMeter(res) {
  if (!res) return null;
  const left = res.reserve.margin_after_return, budget = res.budget;
  const state = res.return_now ? "out" : left <= 0.25 * budget ? "low" : "ok";
  const [lo, hi] = res.k.ci90;
  return {state, frac: left / budget, good: state === "ok", k: res.k.median, ci90: [lo, hi],
          kReserve: res.k.reserve, returnNow: res.return_now,
          word: T.word(state),             // the RETURN NOW banner stays kAlarmMessage's
          text: `k ${res.k.median.toFixed(2)} (90 % ${lo.toFixed(2)}–${hi.toFixed(2)}) · ${Math.max(0, left).toFixed(0)} Wh`};
}

// Banner and voice for the "return now" alarm (shown in #alert).
export function kAlarmMessage(res) {
  const need = res.reserve.reserve_needed, left = res.reserve.remaining;
  return {html: `<b>⚠ RETURN NOW</b> · You are using ${res.k.median.toFixed(2)}× the model. ` +
                `The way home needs ${need.toFixed(0)} Wh at k ${res.k.reserve.toFixed(2)} (90 %); ` +
                `${Math.max(0, left).toFixed(0)} Wh left. <span class="muted">Learned from this walk (simulated use).</span>`,
          speech: "Return now. Your energy use is higher than planned. The way home no longer fits with a safe margin."};
}

// Extra rows for the "plan against the walk" table: [label, plan, walked].
export function adaptiveRows(state) {
  if (!state || !state.history.length) return [];
  const last = state.history[state.history.length - 1];
  const at = a => a ? `${a.d.toFixed(0)} m, min ${(a.t / 60).toFixed(0)}${a.kind === "home" ? " (way home)" : ""}` : "never";
  return [["Metabolic factor k", "1.00 (model)", `${last.k.toFixed(2)} (90 % ${last.lo.toFixed(2)}–${last.hi.toFixed(2)})`],
          ["Real energy (simulated k)", "—", `${state.usedReal.toFixed(0)} Wh`],
          ["\"Return now\" with k p90", "—", at(state.firstAlarm)],
          ["\"Return now\" with k = 1", "—", at(state.firstAlarmFixed)]];
}
