// Rehearsal model of the 3D map. Run from the repo root:  node --test tests/viz3d/
//
// Fixtures: the same real answers as plan_model.test.mjs (E4 round trip with the
// profile; fixed route with no profile, first 400 vertices; E5 tour of 8 stations).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import '../../web/terms.js';
import * as P from '../../web/3d/plan_model.js';
import * as R from '../../web/3d/rehearse_model.js';
import { loadRubric, requestWalkback, walkbackRequest } from '../../web/3d/api.js';
import * as G from '../../web/guide_core.js';

const T = globalThis.TERMS;                 // the team's glossary (#166): names and number formats

const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), 'utf8'));
const E4 = fixture('plan_e4.json'), FIXED = fixture('plan_fixed_route.json'), TOUR = fixture('plan_tour_e5.json');
const DEG = Math.PI / 180;
const close = (a, b, tol = 1e-6) => assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);

function modelOf(fc) {
  const plan = P.parsePlan(fc), route = P.mainRoute(plan);
  return {plan, route, model: R.buildRehearsal(route, plan.points)};
}

// A route written by hand: [x, y] vertices, optional seconds at each vertex.
function handRoute(coords, {t = null, turn = null, points = [], stops = null} = {}) {
  const properties = {kind: 'route', usable_wh: 900};
  if (t) Object.assign(properties, {t_s: t, used_wh: t.map(v => v / 10), rv_wh: coords.map((_, i) => Math.min(i, coords.length - 1 - i))});
  if (turn !== null) properties.turn_index = turn;
  if (stops) Object.assign(properties, {stop_index: stops.map(s => s[0]), visit_order: stops.map(s => s[1])});
  const fc = {type: 'FeatureCollection', features: [
    {type: 'Feature', geometry: {type: 'LineString', coordinates: coords}, properties},
    ...points.map(p => ({type: 'Feature', geometry: {type: 'Point', coordinates: [p.x, p.y]}, properties: p.properties}))]};
  return modelOf(fc);
}

// Distance from a point to the whole route (every segment: slow, independent of the model).
function offRoute(coords, x, y) {
  let best = Infinity;
  for (let i = 1; i < coords.length; i++) {
    const [ax, ay] = coords[i - 1], dx = coords[i][0] - ax, dy = coords[i][1] - ay, len2 = dx * dx + dy * dy;
    const f = len2 > 0 ? Math.min(1, Math.max(0, ((x - ax) * dx + (y - ay) * dy) / len2)) : 0;
    best = Math.min(best, Math.hypot(x - ax - dx * f, y - ay - dy * f));
  }
  return best;
}

// Ground made up for the eye test: a 25 % hillside, 2 m ripples and a 2 m scarp.
const ground = (x, y) => 0.25 * (x - 8143000) + 0.15 * Math.sin(Math.PI * x) + 0.1 * Math.cos(Math.PI * y) +
                         (Math.floor((y + 285000) / 40) % 2 ? 2 : 0);

// Walk a whole rehearsal in small time steps and measure what the camera does.
function walk(model, coords, dt) {
  const out = {steps: 0, maxJump: 0, maxSpeed: 0, maxTurnPerM: 0, maxOff: 0, minEye: Infinity, maxEye: 0, standingTurn: 0};
  const under = d => ground(...model.cameraAt(d));
  let prev = null;
  for (let time = model.start; ; time = Math.min(model.end, time + dt)) {
    const s = model.stateAt(time);
    const eye = R.eyeAltitude(under, s.distance, model.length) - ground(s.cx, s.cy);
    out.minEye = Math.min(out.minEye, eye); out.maxEye = Math.max(out.maxEye, eye);
    out.maxOff = Math.max(out.maxOff, offRoute(coords, s.cx, s.cy));
    if (prev) {
      const jump = Math.hypot(s.cx - prev.cx, s.cy - prev.cy), walked = s.distance - prev.distance;
      const turn = Math.abs(R.angleDelta(s.heading, prev.heading)) / DEG;
      out.maxJump = Math.max(out.maxJump, jump);
      out.maxSpeed = Math.max(out.maxSpeed, jump / (s.time - prev.time));
      assert.ok(jump <= walked + 1e-6, `camera moved ${jump} m while the walker walked ${walked} m`);
      // Turning is measured per metre while walking; at a stop the walker turns on the spot.
      const atStop = model.stops.some(stop => stop.arrive > prev.time - 1e-9 && stop.arrive < s.time + 1e-9) ||
                     model.stops.some(stop => stop.leave > prev.time - 1e-9 && stop.leave < s.time + 1e-9);
      if (s.standing || prev.standing || atStop) out.standingTurn = Math.max(out.standingTurn, turn);
      else if (walked > 1e-9) out.maxTurnPerM = Math.max(out.maxTurnPerM, turn / walked);
      else assert.ok(turn < 1e-9, 'the heading changed without walking');
    }
    prev = s; out.steps++;
    if (time >= model.end) break;
  }
  return out;
}

test('E4 answer: the time base is the profile, and every vertex is where the profile says', () => {
  const {route, model} = modelOf(E4);
  assert.equal(model.hasProfile, true);
  assert.equal(model.assumedSpeed, null);
  assert.equal(model.start, 0);
  close(model.duration, route.totals.time_s, 1e-9);         // 2402.5 s
  close(model.length, route.totals.length_m, 0.06);
  for (let i = 0; i < route.coords.length; i += 7) {
    const s = model.stateAt(route.profile.t_s[i]);
    close(s.at, i, 1e-9);
    close(s.x, route.coords[i][0]); close(s.y, route.coords[i][1]);
    for (const key of P.PROFILE_KEYS) close(s.profile[key], route.profile[key][i], 1e-9);
    assert.equal(s.leg, i >= route.turnIndex ? 'return' : 'outbound');     // as the 2D planner
  }
  // Half-way between two vertices in time is half-way between them on the ground.
  const mid = model.stateAt((route.profile.t_s[100] + route.profile.t_s[101]) / 2);
  close(mid.at, 100.5, 1e-9);
  close(mid.profile.used_wh, (route.profile.used_wh[100] + route.profile.used_wh[101]) / 2, 1e-9);
});

test('E4 answer: one stop, at the goal station, and the walker stands there for the service time', () => {
  const {route, model} = modelOf(E4);
  assert.equal(model.stops.length, 1);
  const [stop] = model.stops, goal = route.coords[route.turnIndex], ts = route.profile.t_s;
  assert.equal(stop.index, 536);
  assert.equal(stop.station.id, 'R0');
  assert.equal(stop.station.type, 'ridge');
  assert.equal(stop.station.score, 5);
  assert.equal(stop.station.serviceMin, 10);
  // t_s jumps 601.6 s over the 1 m that reaches the goal: about 1.7 s of walking at the
  // pace of the step before, the rest standing (the 10 min of service).
  close(stop.leave, ts[536], 1e-9);
  close(stop.waitS, 600, 0.5);
  close(stop.arrive - ts[535], (ts[535] - ts[534]) / 1, 1e-9);
  const before = model.stateAt(stop.arrive - 0.5);
  assert.equal(before.standing, false);
  assert.ok(before.at > 535 && before.at < 536);
  for (const f of [0, 0.01, 0.3, 0.75, 0.999]) {
    const s = model.stateAt(stop.arrive + f * stop.waitS);
    assert.equal(s.standing, true);
    assert.equal(s.stop, stop);
    close(s.x, goal[0]); close(s.y, goal[1]);
    close(s.cx, goal[0]); close(s.cy, goal[1]);                     // the camera path passes through the stop
    close(s.distance, model.distances[536], 1e-9);
    close(s.profile.rv_wh, route.profile.rv_wh[536], 1e-9);         // the way back does not change while standing
    close(s.profile.t_s, s.time, 1e-9);
    assert.equal(s.leg, 'outbound');
  }
  // Energy keeps being used while standing (service), up to the profile's value on leaving.
  const early = model.stateAt(stop.arrive + 60), late = model.stateAt(stop.arrive + 540);
  assert.ok(late.profile.used_wh - early.profile.used_wh > 20);
  close(model.stateAt(stop.leave).profile.used_wh, route.profile.used_wh[536], 1e-9);
  assert.equal(model.stateAt(stop.leave).standing, false);
  assert.equal(model.stateAt(stop.leave).leg, 'return');
  // The view turns round while waiting: arrival and departure headings are opposite.
  const turned = Math.abs(R.angleDelta(model.stateAt(stop.leave).heading, model.stateAt(stop.arrive).heading)) / DEG;
  assert.ok(turned > 150, `turned ${turned} degrees`);
  close(R.angleDelta(model.stateAt(stop.arrive + 1e-6).heading, model.stateAt(stop.arrive - 1e-6).heading), 0, 1e-3);
});

test('no profile: time is distance at an assumed 1 m/s, and the text says so', () => {
  const {route, model} = modelOf(FIXED);
  assert.equal(model.hasProfile, false);
  assert.equal(model.assumedSpeed, 1);
  assert.equal(model.stops.length, 0);
  close(model.duration, route.lengthM / R.ASSUMED_SPEED, 1e-9);
  const s = model.stateAt(100);
  close(s.distance, 100, 1e-9);
  assert.equal(s.profile, null);
  assert.equal(s.leg, null);
  assert.equal(R.energyReadout(s.profile, 900), null);
  assert.equal(R.progressText(model, s), 'EVA 1:40 of 5:32 (assumed 1 m/s) · 100 of 332 m');
  // The route has repeated vertices (steps of 0 m): they take no time and break nothing.
  for (let i = 0; i < route.coords.length; i++) {
    const at = model.stateAt(model.times[i]);
    close(at.x, route.coords[i][0]); close(at.y, route.coords[i][1]);
  }
});

test('walking the whole E4 route: continuous, gentle turns, close to the route, eye above the ground', () => {
  const {route, model} = modelOf(E4);
  const w = walk(model, route.coords, 0.1);
  assert.ok(w.steps > 24000);
  assert.ok(w.maxSpeed <= 0.92, `camera speed ${w.maxSpeed} m/s`);                  // the walker's fastest step is 0.91 m/s
  assert.ok(w.maxJump <= 0.092, `largest move in 0.1 s: ${w.maxJump} m`);
  assert.ok(w.maxTurnPerM < 10, `heading turns ${w.maxTurnPerM} deg per metre`);    // measured 4.0
  assert.ok(w.maxOff <= R.MAX_CUT, `camera path ${w.maxOff} m from the route`);     // measured 0.81
  close(w.maxOff, model.maxOffRoute, 0.1);                                          // the model measures it at its samples
  assert.ok(w.minEye >= R.MIN_EYE - 1e-9, `eye ${w.minEye} m above the ground`);
  assert.ok(w.standingTurn < 1, `turn in one 0.1 s step at the stop: ${w.standingTurn} deg`);
});

test('walking the fixed route with no profile: same limits', () => {
  const {route, model} = modelOf(FIXED);
  const w = walk(model, route.coords, 0.05);
  assert.ok(w.maxJump <= 0.05 + 1e-9, `largest move in 0.05 s: ${w.maxJump} m`);
  assert.ok(w.maxTurnPerM < 10, `heading turns ${w.maxTurnPerM} deg per metre`);    // measured 8.9
  assert.ok(w.maxOff <= R.MAX_CUT, `camera path ${w.maxOff} m from the route`);     // measured 1.06
  assert.ok(w.minEye >= R.MIN_EYE - 1e-9);
});

test('the camera path irons out the staircase but keeps the ends and the corners', () => {
  // Heading about 22 degrees north of east on the grid: east and north-east steps in turn.
  const stairs = [[0, 0]];
  for (let i = 0; i < 60; i++) stairs.push([stairs.at(-1)[0] + 1, stairs.at(-1)[1] + (i % 2)]);
  const {model} = handRoute(stairs);
  const bearing = Math.atan2(60, 30);
  let side = 0, turn = 0;
  for (let d = 10; d <= model.length - 22; d += 0.1) {
    const [x, y] = model.cameraAt(d);
    side = Math.max(side, Math.abs((x * 30 - y * 60) / Math.hypot(30, 60) - 0.224));  // off the mean line
    turn = Math.max(turn, Math.abs(R.angleDelta(model.headingAt(d), bearing)));
  }
  assert.ok(side < 0.02, `sideways wobble ${side} m`);          // the true path wobbles 0.22 m each way
  assert.ok(turn < 1 * DEG, `heading off by ${turn / DEG} degrees`);
  model.cameraAt(0).forEach(v => close(v, 0, 1e-12));
  model.cameraAt(model.length).forEach((v, i) => close(v, stairs.at(-1)[i], 1e-12));

  // A right angle: the camera rounds it, but by less than MAX_CUT.
  const corner = [...Array.from({length: 41}, (_, i) => [i, 0]), ...Array.from({length: 40}, (_, i) => [40, i + 1])];
  const bend = handRoute(corner).model;
  assert.ok(bend.maxOffRoute > 0.5 && bend.maxOffRoute <= R.MAX_CUT, `cut ${bend.maxOffRoute} m`);
  // A hairpin sharper than that: the smoothing gives way instead of leaving the route.
  const hairpin = [...Array.from({length: 41}, (_, i) => [i, 0]), ...Array.from({length: 40}, (_, i) => [39 - i, i + 1])];
  assert.ok(handRoute(hairpin).model.maxOffRoute <= R.MAX_CUT);
});

test('heading: looks 12 m ahead, never past a stop, and is held on the last metres', () => {
  // Out east 50 m, back the same way, 60 s standing at the far end (charged to the arriving step).
  const out = Array.from({length: 51}, (_, i) => [i, 0]), back = Array.from({length: 50}, (_, i) => [49 - i, 0]);
  const t = [...out.map((_, i) => i + (i === 50 ? 60 : 0)), ...back.map((_, i) => 111 + i)];
  const {model} = handRoute([...out, ...back], {t, turn: 50});
  assert.equal(model.stops.length, 1);
  assert.equal(model.stops[0].station, null);                // a wait with no station there
  close(model.stops[0].waitS, 60, 1e-9);
  for (const time of [0, 20, 45, 49.5, 50]) close(model.stateAt(time).heading, 90 * DEG, 1e-9);      // east all the way in
  for (const time of [110, 111, 130, 160]) close(Math.abs(model.stateAt(time).heading), 90 * DEG, 1e-9);
  close(model.stateAt(130).heading, -90 * DEG, 1e-9);        // west on the way back
  const half = model.stateAt(80);                            // half-way through the wait: half-way round
  assert.equal(half.standing, true);
  close(Math.abs(R.angleDelta(half.heading, 90 * DEG)), 90 * DEG, 1e-6);
  assert.equal(R.progressText(model, half), 'EVA 1:20 of 2:40 · at a stop · 50 of 100 m');
  assert.equal(R.progressText(model, model.stateAt(130)), 'EVA 2:10 of 2:40 · returning · 70 of 100 m');
});

test('stops: a tour has several, taken from the answer; skipped stations are not stops', () => {
  const coords = Array.from({length: 61}, (_, i) => [8143000 + (i <= 30 ? i : 60 - i), -284000 - (i <= 30 ? 0 : 2)]);
  coords[31] = [8143029.5, -284001];
  const t = coords.map((_, i) => i + (i >= 10 ? 300 : 0) + (i >= 30 ? 600 : 0));
  const station = (id, x, y, visited, order) =>
    ({x, y, properties: {kind: 'station', id, type: 'hollow', score: 4, service_time_min: order === 1 ? 5 : 10, visited, order}});
  const points = [{x: coords[0][0], y: coords[0][1], properties: {kind: 'start'}},
                  station('A', coords[10][0], coords[10][1] + 1, true, 1), station('B', coords[30][0] + 0.5, coords[30][1], true, 2),
                  station('skipped', coords[20][0], coords[20][1] + 1, false, null),
                  station('passed', coords[45][0], coords[45][1] - 1, true, 3)];
  const viaAnswer = handRoute(coords, {t, turn: 30, points, stops: [[10, 'A'], [30, 'B']]}).model;
  const viaPlace = handRoute(coords, {t, turn: 30, points}).model;
  for (const model of [viaAnswer, viaPlace]) {
    assert.deepEqual(model.stops.map(s => [s.index, s.station.id, Math.round(s.waitS)]),
                     [[10, 'A', 300], [30, 'B', 600], [45, 'passed', 0]]);
    assert.equal(model.stops[0].station.serviceMin, 5);
    assert.equal(model.stops[0].station.order, 1);
    close(model.stops[0].arrive, 10, 1e-9); close(model.stops[0].leave, 310, 1e-9);
    assert.deepEqual(model.anchors, [0, 10, 30, 45, 60]);
    assert.equal(model.stateAt(200).stop.station.id, 'A');
    assert.equal(model.stateAt(320).stop, null);
  }
  // A goal point that names no station of the plan is a stop on its own.
  const lone = handRoute(coords, {turn: 30, points: [{x: coords[30][0], y: coords[30][1], properties: {kind: 'goal'}}]}).model;
  assert.deepEqual(lone.stops.map(s => [s.index, s.station.id, s.waitS]), [[30, 'Goal', 0]]);
});

test('real E5 tour: eight stops where the answer puts them, each with its 10 min of service', () => {
  const {plan, route, model} = modelOf(TOUR), ts = route.profile.t_s;
  const written = TOUR.features.filter(f => f.properties.kind === 'stop').map(f => f.properties);
  assert.equal(model.assumedSpeed, null);
  close(model.duration, 6686.7, 1e-9);
  assert.deepEqual(model.stops.map(s => s.station.id), ['R3', 'R2', 'H2', 'H4', 'H0', 'R0', 'R4', 'R1']);
  assert.deepEqual(model.stops.map(s => s.index), route.stops.map(s => s.index));
  assert.deepEqual(model.stops.map(s => s.station.order), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.deepEqual(model.anchors, [0, ...route.stops.map(s => s.index), 1133]);
  model.stops.forEach((stop, i) => {
    // The wait is inferred from the profile (the step that arrives carries the service
    // time); E5 also writes the arrival and departure times: they must agree.
    close(stop.leave, ts[stop.index], 1e-9);
    close(stop.leave, written[i].departure_time_s, 0.05);
    close(stop.arrive, written[i].arrival_time_s, 0.6);            // measured: 0.46 s at most
    close(stop.waitS, 600, 0.6);
    assert.equal(stop.station.serviceMin, 10);
    // On arrival and through the wait the walker stands on the stop's vertex.
    for (const f of [0, 0.5, 0.999]) {
      const s = model.stateAt(stop.arrive + f * stop.waitS);
      assert.equal(s.standing, true, `stop ${stop.station.id} at ${f}`);
      assert.equal(s.stop, stop);
      close(s.x, route.coords[stop.index][0]); close(s.y, route.coords[stop.index][1]);
      close(s.cx, s.x); close(s.cy, s.y);
      close(s.profile.rv_wh, route.profile.rv_wh[stop.index], 1e-9);
      assert.equal(R.progressText(model, s).includes(`at ${stop.station.id}`), true);
    }
    assert.equal(model.stateAt(stop.arrive - 0.5).standing, false);
    assert.equal(model.stateAt(stop.leave).standing, false);
    close(model.stateAt(stop.leave).profile.used_wh, route.profile.used_wh[stop.index], 1e-9);
  });
  // Stations the tour skipped are not stops, and no stop is the single goal of the route.
  const skipped = plan.points.filter(p => p.kind === 'station' && p.properties.visited === false).map(p => String(p.properties.id));
  assert.equal(skipped.length, 5);
  assert.ok(model.stops.every(s => !skipped.includes(s.station.id)));
  // Outbound until the walker leaves the last station, then returning to the habitat.
  assert.equal(model.stateAt(model.stops[3].leave + 5).leg, 'outbound');
  assert.equal(model.stateAt(model.stops[7].arrive + 300).leg, 'outbound');
  assert.equal(model.stateAt(model.stops[7].leave + 5).leg, 'return');
  assert.equal(R.progressText(model, model.stateAt(6000)), 'EVA 100:00 of 111:27 · returning · 862 of 1392 m');
  // Every vertex is where the profile says, with the answer's own values.
  for (let i = 0; i < route.coords.length; i += 9) {
    const s = model.stateAt(ts[i]);
    close(s.x, route.coords[i][0]); close(s.y, route.coords[i][1]);
    for (const key of P.PROFILE_KEYS) close(s.profile[key], route.profile[key][i], 1e-9);
  }
  const end = R.energyReadout(model.stateAt(model.end).profile, model.usableWh);
  close(end.used, 447.5225, 1e-9); close(end.rv, 0, 1e-9);
});

test('walking the whole E5 tour: same limits as the round trip, through eight stops', () => {
  const {route, model} = modelOf(TOUR);
  const w = walk(model, route.coords, 0.1);
  assert.ok(w.steps > 66000);
  assert.ok(w.maxJump <= 0.095, `largest move in 0.1 s: ${w.maxJump} m`);           // measured 0.091
  assert.ok(w.maxTurnPerM < 10, `heading turns ${w.maxTurnPerM} deg per metre`);    // measured 8.6
  assert.ok(w.maxOff <= R.MAX_CUT, `camera path ${w.maxOff} m from the route`);     // measured 0.98
  assert.ok(w.minEye >= R.MIN_EYE - 1e-9, `eye ${w.minEye} m above the ground`);
  assert.ok(w.standingTurn < 1, `turn in one 0.1 s step at a stop: ${w.standingTurn} deg`);   // measured 0.41
});

test('energy bar and texts: the numbers of the 2D planner, in the words and formats of the glossary', () => {
  const {route, model} = modelOf(E4);
  // showRouteIdx() of web/index.html, written out again on the raw answer; the names and the
  // number formats of web/terms.js (#166): whole Wh, "spare", "home in" in whole minutes.
  const r = {...E4.features[0].properties}, usable = r.usable_wh;
  const mm = s => `${Math.floor(s / 60)}:${String(Math.round(s % 60)).padStart(2, '0')}`;
  for (const i of [0, 1, 250, 535, 536, 537, 800, 1072]) {
    const used = r.used_wh[i], rv = r.rv_wh[i], free = Math.max(0, usable - used - rv);
    const pct = v => Math.max(0, 100 * v / usable);
    const state = model.stateAt(r.t_s[i]), bar = R.energyReadout(state.profile, model.usableWh);
    close(bar.usedPct, pct(used), 1e-9); close(bar.rvPct, pct(rv), 1e-9); close(bar.freePct, pct(free), 1e-9);
    close(bar.usedPct + bar.rvPct + bar.freePct, 100, 1e-9);
    assert.equal(bar.lines[0], `Energy used ${used.toFixed(0)} Wh · return needs ${rv.toFixed(0)} Wh · ` +
                               `spare ${free.toFixed(0)} of ${usable.toFixed(0)} Wh`);
    assert.equal(bar.lines[1], `O₂ used ${r.o2_used_l[i].toFixed(1)} L (metabolic equivalent) · ` +
                               `home in ${Math.round(r.rv_time_s[i] / 60)} min`);
    assert.equal(bar.energyLeft, Math.round(usable - used));               // what the 2D planner sends to /walkback
    assert.equal(R.progressText(model, state),
                 `EVA ${mm(r.t_s[i])} of ${mm(r.t_s.at(-1))} · ${i >= r.turn_index ? 'returning' : 'outbound'} · ` +
                 `${model.distances[i].toFixed(0)} of ${route.lengthM.toFixed(0)} m`);
  }
  assert.equal(R.progressText(model, model.stateAt(1000)), 'EVA 16:40 of 40:03 · at R0 · 666 of 1334 m');
  assert.equal(R.clock(59.6), '1:00');                       // the 2D planner would write 0:60
  // With no usable budget in the answer there is no bar, and nothing breaks.
  assert.equal(R.energyReadout(model.stateAt(0).profile, null), null);
  // On arrival the time and the energy to return can come out a hair under zero: 0, never a
  // minus sign (#124).
  const home = R.energyReadout({used_wh: 447.4, rv_wh: -2e-5, o2_used_l: 80, rv_time_s: -1e-9}, 900);
  assert.equal(home.lines[0], 'Energy used 447 Wh · return needs 0 Wh · spare 453 of 900 Wh');
  assert.equal(home.lines[1], 'O₂ used 80.0 L (metabolic equivalent) · home in 0 min');
});

test('time home: the words of the tablet meter, from its seconds, in whole minutes and never negative', () => {
  // guide_core's meters() of the same E4 answer, as the rehearsal reads them (back.s, back.text).
  const r = G.routeFromPlan({plan: E4});
  for (const i of [0, 1, 250, 535, 536, 800, r.coords.length - 1]) {
    const back = G.meters(r, i).back;
    assert.equal(R.homeInText(back.s), back.text);
  }
  assert.equal(R.homeInText(754), 'home in 13 min');         // 12.6 min: whole minutes, as the glossary
  assert.equal(R.homeInText(754), T.homeIn(754).toLowerCase());
  assert.equal(R.homeInText(-1e-9), 'home in 0 min');        // a hair under zero on arrival
  assert.equal(R.homeInText(-0), 'home in 0 min');
  assert.equal(R.homeInText(-40), 'home in 0 min');          // never "-1 min"
});

test('the player and the panel say the names of the glossary, and the band the tablet\'s banner', () => {
  // web/3d/index.html without its comments (HTML and CSS): what the page shows.
  const page = readFileSync(new URL('../../web/3d/index.html', import.meta.url), 'utf8')
    .replace(/<!--[\s\S]*?-->/g, '').replace(/\/\*[\s\S]*?\*\//g, '');
  const N = T.NAMES;
  // The meter labels exactly as the tablet shows them (web/guide.html).
  for (const label of [N.spare, `${N.home} · ${N.homeLimit}`, N.evaLeft, N.radio]) {
    assert.ok(page.includes(`>${label}</span>`), `no meter label "${label}"`);
  }
  // The main buttons of the player, the way into the rehearsal and the link back to the planner.
  const button = id => new RegExp(`<button id="${id}"[^>]*>([^<]*)</button>`).exec(page)?.[1] ?? '';
  assert.match(button('rh-home'), new RegExp(`${N.returnHome}$`));
  assert.match(button('rh-detour'), new RegExp(`${N.offRoute}$`));
  assert.match(button('rh-storm'), new RegExp(`${N.storm}$`));
  assert.equal(button('rehearse'), N.rehearse);
  assert.ok(page.includes(`href="/">← ${N.planner}</a>`), 'the link back is not the planner\'s name');
  // The storm band: the headline of the tablet's banner, pending and once the way home is known.
  const band = /<div id="rh-storm-band"[^>]*>([^<]*)<\/div>/.exec(page)?.[1];
  const headline = html => /<b>([^<]*)<\/b>/.exec(html)?.[1];
  assert.equal(band, headline(G.STORM_PENDING));
  assert.equal(band, headline(G.stormHtml({realUgy: 2.2, x50Ugy: 54})));
  assert.equal(band, `${N.storm.toUpperCase()} · ${N.returnHome.toLowerCase()} now`);
  for (const old of ['Time home (limit 30 min)', 'go home now', '2D planner', 'Detour', 'Rehearse the route', 'free<']) {
    assert.ok(!page.includes(old), `web/3d/index.html still says "${old}"`);
  }
});

test('a way home of one point (Return home or the storm pressed at the habitat): the walker stands there', () => {
  // POST /guide/return_home answers a single vertex when the walker is already home; the
  // rehearsal builds its route the way rehearse.js _walkRoute does (issue #115).
  const home = [8143537.992786024, -284463.575189438];
  const route = {kind: 'route', coords: [home], turnIndex: null, stops: [], totals: {usable_wh: 900},
                 profile: {t_s: [125], used_wh: [12.5], rv_time_s: [0], rv_wh: [0]}};
  const model = R.buildRehearsal(route, []);
  assert.equal(model.start, 125);
  assert.equal(model.end, 125);
  assert.equal(model.duration, 0);
  assert.equal(model.length, 0);
  assert.deepEqual(model.stops, []);
  for (const time of [0, 125, 300]) {                      // before, at and after: always the same place
    const s = model.stateAt(time);
    assert.deepEqual([s.time, s.x, s.y, s.cx, s.cy, s.distance], [125, ...home, ...home, 0]);
    assert.equal(s.standing, false);
    assert.equal(s.heading, null);                         // no direction: the view keeps its own
    assert.equal(s.profile.used_wh, 12.5);
    // The player keeps the EVA clock (#124): asked 2:05 into the EVA, it says so, and that
    // the walker is home, not a way home of "0:00 of 0:00". On its own clock (no options)
    // the route would read as a route of no time.
    assert.equal(R.progressText(model, s, {evaStart: 0, homeStart: 125}), 'EVA 2:05 · at the habitat');
    assert.equal(R.progressText(model, s), 'EVA 0:00 of 0:00 · 0 of 0 m');
  }
  assert.deepEqual(model.cameraAt(0), home);
  assert.equal(model.headingAt(0), null);
  close(R.eyeAltitude(d => ground(...model.cameraAt(d)), 0, model.length), ground(...home) + R.EYE_HEIGHT, 1e-9);
  // A route that has a direction still has a heading everywhere.
  assert.ok(Number.isFinite(modelOf(E4).model.stateAt(0).heading));
});

test('player clock: the EVA clock goes on after Return home, the storm or a rejoin; the way home is a stretch of it', () => {
  // Routes built as rehearse.js _walkRoute builds them: a guide_core route whose clock
  // starts where the walker was (seconds on the plan's clock), and the EVA started at 0.
  const straight = (n, t0, seconds) => {
    const coords = Array.from({length: n + 1}, (_, i) => [8143000 + i, -284000]);
    const t = coords.map((_, i) => t0 + i * seconds / n);
    return R.buildRehearsal({kind: 'route', coords, turnIndex: null, stops: [], totals: {usable_wh: 900},
                             profile: {t_s: t, used_wh: t.map(v => v / 10), rv_time_s: t.map(v => t0 + seconds - v),
                                       rv_wh: coords.map((_, i) => n - i)}}, []);
  };
  // Return home pressed 100:02 into the EVA: 160 m and 2:51 to the habitat. The stretch has
  // the glossary's name, "return home" (it said "way home" before #166).
  const home = straight(160, 6002, 171), opts = {evaStart: 0, homeStart: 6002};
  assert.equal(R.progressText(home, home.stateAt(6002), opts), 'EVA 100:02 · return home 0:00 of 2:51 · 0 of 160 m');
  assert.equal(R.progressText(home, home.stateAt(6124), opts), 'EVA 102:04 · return home 2:02 of 2:51 · 114 of 160 m');
  assert.equal(R.progressText(home, home.stateAt(6173), opts), 'EVA 102:53 · return home 2:51 of 2:51 · 160 of 160 m');
  // Before #124 the same state read as the way home's own clock, from 0:00.
  assert.equal(R.progressText(home, home.stateAt(6124)), 'EVA 2:02 of 2:51 · 114 of 160 m');
  // A detour on the way home (60 s later): the rejoined way home is longer, and the stretch
  // still counts from the first time home was asked.
  const rejoined = straight(120, 6062, 150);
  assert.equal(R.progressText(rejoined, rejoined.stateAt(6092), opts), 'EVA 101:32 · return home 1:30 of 3:30 · 24 of 120 m');
  // A rejoin of the plan (the detour 25:00 into the EVA): the rest of the plan, so the EVA
  // clock of the plan's new end; never 0:00.
  const plan = straight(800, 1500, 1000);
  assert.equal(R.progressText(plan, plan.stateAt(1500), {evaStart: 0}), 'EVA 25:00 of 41:40 · 0 of 800 m');
  assert.equal(R.progressText(plan, plan.stateAt(1600), {evaStart: 0, homeStart: null}), 'EVA 26:40 of 41:40 · 80 of 800 m');
  // The planned route itself: the same numbers as always, with "EVA" in front.
  const {model} = modelOf(E4);
  assert.equal(R.progressText(model, model.stateAt(1000), {evaStart: model.start}), 'EVA 16:40 of 40:03 · at R0 · 666 of 1334 m');
});

test('maneuver distance: written big as on the tablet, "350 m" or "Now"', () => {
  assert.equal(R.maneuverDistance('in 350 m'), '350 m');
  assert.equal(R.maneuverDistance('in 1250 m'), '1250 m');
  assert.equal(R.maneuverDistance('now'), 'Now');
  // Every vertex of the E4 route, from guide_core's own banner text.
  const r = G.routeFromPlan({plan: E4});
  for (let i = 0; i < r.coords.length; i++) {
    const {distText} = G.nextManeuver(r, i);
    assert.equal(R.maneuverDistance(distText), distText === 'now' ? 'Now' : distText.slice(3));
    assert.match(R.maneuverDistance(distText), /^(Now|\d+ m)$/);
  }
});

test('eye height: follows the ground averaged along the path, never under 1.6 m', () => {
  const flat = () => 5, ramp = d => 0.3 * d, crest = d => -Math.abs(d - 50);
  close(R.eyeAltitude(flat, 20, 100), 5 + R.EYE_HEIGHT, 1e-12);
  close(R.eyeAltitude(ramp, 20, 100), 6 + R.EYE_HEIGHT, 1e-12);          // a steady slope is not changed
  close(R.eyeAltitude(crest, 50, 100), R.MIN_EYE, 1e-12);                // a sharp crest: the floor holds
  // Ripples of 10 cm every 2 m: the eye moves much less than the ground.
  const ripples = d => 0.1 * Math.sin(Math.PI * d);
  let swing = 0;
  for (let d = 10; d < 20; d += 0.05) swing = Math.max(swing, Math.abs(R.eyeAltitude(ripples, d, 100) - R.EYE_HEIGHT));
  assert.ok(swing < 0.02, `eye swings ${swing} m`);
});

test('walkback request: the position, the energy left and the limits of the plan; one POST /walkback', async () => {
  const {plan, model} = modelOf(E4);
  const state = model.stateAt(721), bar = R.energyReadout(state.profile, model.usableWh);
  const start = plan.points.find(p => p.kind === 'start');
  const body = walkbackRequest({x: state.x, y: state.y, energyLeftWh: bar.energyLeft, base: [start.x, start.y],
                                properties: plan.properties});
  assert.deepEqual(body, {current_position: [state.x, state.y], energy_remaining_wh: 832, emergency_return_time_s: 1800,
                          base: [start.x, start.y], max_cell_slope_deg: 30});
  // No base and no limits in the plan: the server's defaults apply (box centre, 30 degrees).
  assert.deepEqual(walkbackRequest({x: 1, y: 2, energyLeftWh: -5}),
                   {current_position: [1, 2], energy_remaining_wh: 0, emergency_return_time_s: 1800, base: null});
  const calls = [];
  const fetchFn = async (url, init) => {
    calls.push([url, init && init.method]);
    return {ok: true, status: 200, json: async () => ({type: 'FeatureCollection', features: [], properties: {return_time_s: 60}})};
  };
  const got = await requestWalkback(body, {fetchFn});
  assert.deepEqual(calls, [['/walkback', 'POST']]);
  assert.equal(got.error, null);
  assert.equal(got.fc.properties.return_time_s, 60);
  const failed = await requestWalkback(body, {fetchFn: async () => ({ok: false, status: 422, json: async () => ({detail: 'no walkable path'})})});
  assert.deepEqual(failed, {fc: null, error: 'no walkable path'});
});

test('rubric: the type labels of the cards, or nothing when the server does not answer', async () => {
  const rubric = {ridge: {label: 'Boxwork ridge', score: 5}};
  assert.deepEqual(await loadRubric({fetchFn: async () => ({ok: true, status: 200, json: async () => rubric})}), rubric);
  assert.deepEqual(await loadRubric({fetchFn: async () => { throw new Error('offline'); }}), {});
});
