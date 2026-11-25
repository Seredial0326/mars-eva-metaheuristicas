// Plan model of the 3D map. Run from the repo root:  node --test tests/viz3d/
//
// Fixtures (tests/viz3d/fixtures/), real answers of the API on 2026-11-14:
//   plan_e4.json           POST /plan with the 13 saved stations and the 2D planner's
//                          default limits: E4 round trip to R0, with the profile. Whole.
//   plan_fixed_route.json  POST /plan with stations: []: the fixed test route, with no
//                          profile, cut to its first 400 vertices.
//   plan_tour_e5.json      what POST /plan answers to the same default request when the
//                          tour planner (E5, branch 9-e5-orienteering) is present: 8 of
//                          the 13 stations in 111 min. Whole. Made in-process, nothing
//                          saved, by src/viz3d/make_tour_fixture.py.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import * as P from '../../web/3d/plan_model.js';
import { defaultPlanRequest, loadLastPlan, requestDefaultPlan, stationTypes } from '../../web/3d/api.js';

const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), 'utf8'));
const E4 = fixture('plan_e4.json'), FIXED = fixture('plan_fixed_route.json'), TOUR = fixture('plan_tour_e5.json');
const close = (a, b, tol = 1e-6) => assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);

test('station list: real tour order, rubric names and the unvisited pins, without changing the plan', () => {
  const plan = P.parsePlan(TOUR), before = structuredClone(plan);
  const rubric = {ridge: {label: 'Boxwork ridge'}, hollow: {label: 'Hollow'}};
  const entries = P.stationList(plan, {}, rubric);
  assert.deepEqual(entries.slice(0, 8).map(e => e.id), ['R3', 'R2', 'H2', 'H4', 'H0', 'R0', 'R4', 'R1']);
  assert.equal(entries[0].label, '1 · R3 · Boxwork ridge');
  assert.equal(entries[2].label, '3 · H2 · Hollow');
  assert.equal(entries.length, 13);
  assert.ok(entries.slice(8).every(e => e.order === null && e.label.startsWith('Not visited · ')));
  const pins = new Map(P.planMarkers(plan).map(m => [m.id, m]));
  for (const entry of entries) {
    assert.deepEqual(entry.marker, pins.get(entry.id), 'same marker data as a pin click');
    assert.doesNotMatch(entry.label, /\bE(?:[1-9]|1[0-2])\b/);
  }
  assert.deepEqual(plan, before);
});

test('station list: single goal first; no stations, no plan and no route are supported', () => {
  const entries = P.stationList(P.parsePlan(E4));
  assert.equal(entries[0].label, '1 · R0');
  assert.equal(entries[0].marker.kind, 'goal');
  assert.ok(entries.slice(1).every(e => e.label.startsWith('Not visited · ')));
  assert.deepEqual(P.stationList(null), []);
  assert.deepEqual(P.stationList(P.parsePlan(FIXED)), []);
  const plan = P.parsePlan(tourPlan());
  plan.routes = [];
  for (const p of plan.points) { delete p.properties.order; delete p.properties.visited; }
  const unordered = P.stationList(plan);
  assert.deepEqual(unordered.map(e => e.label), ['H0', 'R0', 'C1']);
  assert.ok(unordered.every(e => e.order === null), 'no made-up visit numbers');
});

test('station list: route order wins over feature order, saved types and late rubric names work', () => {
  const plan = P.parsePlan(tourPlan());
  plan.points.reverse();
  for (const p of plan.points) delete p.properties.type;
  const types = {R0: 'ridge', H0: 'hollow'}, rubric = {ridge: {label: 'Boxwork ridge'}};
  const bare = P.stationList(plan, types);
  const named = P.stationList(plan, types, rubric);
  assert.deepEqual(named.map(e => e.id), ['H0', 'R0', 'C1']);
  assert.equal(bare[1].label, '2 · R0');
  assert.equal(named[1].label, '2 · R0 · Boxwork ridge');
  assert.equal(named[1].marker.data.type, 'ridge');
  delete plan.routes[0].properties.visit_order;
  assert.deepEqual(P.stationList(plan).map(e => e.id), named.map(e => e.id), 'station order is the fallback');
  plan.points.find(p => p.properties.id === 'C1').properties.name = '<b>Contact</b>';
  assert.equal(P.stationList(plan)[2].label, 'Not visited · C1 · <b>Contact</b>', 'plain text for textContent');
});

// A tour as api/tour.py writes it (E5 on E4): no 'goal' point, no crs, stations with
// visited / order, and the stops along the route. Coordinates are made up.
function tourPlan() {
  const coords = Array.from({length: 13}, (_, i) => [8143000 + Math.min(i, 12 - i) * 1.5 + (i > 6 ? 0.5 : 0), -284000 - i]);
  const profile = Object.fromEntries(P.PROFILE_KEYS.map(key => [key, coords.map((_, i) => i * 2)]));
  const station = (id, type, x, y, order) => ({type: 'Feature', geometry: {type: 'Point', coordinates: [x, y]},
    properties: {kind: 'station', id, type, score: 4, service_time_min: 10, visited: order != null, order}});
  return {type: 'FeatureCollection',
    features: [
      {type: 'Feature', geometry: {type: 'LineString', coordinates: coords},
       properties: {kind: 'route', approach: 'E5_orienteering_on_E4', feasible: true, length_m: 21.6,
                    time_s: 24, energy_wh: 24, usable_wh: 900, visit_order: ['H0', 'R0'],
                    stop_index: [3, 6], turn_index: 6, ...profile}},
      {type: 'Feature', geometry: {type: 'Point', coordinates: coords[0]},
       properties: {kind: 'start', requested: coords[0], moved_m: 0}},
      station('H0', 'hollow', coords[3][0], coords[3][1], 1),
      station('R0', 'ridge', coords[6][0], coords[6][1], 2),
      station('C1', 'contact', 8143050, -284020, null),
    ],
    properties: {source: 'E5_orienteering_on_E4 (live)', warnings: ['E5 tour: 2 of 3 stations']}};
}

test('E4 answer: one route with an aligned profile, a turn and its totals', () => {
  const plan = P.parsePlan(E4);
  assert.equal(plan.routes.length, 1);
  assert.deepEqual(plan.notes, []);
  const route = P.mainRoute(plan), n = route.coords.length;
  assert.equal(n, 1073);
  assert.deepEqual(Object.keys(route.profile), P.PROFILE_KEYS);
  for (const key of P.PROFILE_KEYS) assert.equal(route.profile[key].length, n);
  assert.equal(route.turnIndex, 536);
  assert.equal(route.totals.length_m, 1333.8);
  assert.equal(route.totals.feasible, true);
  // The API's length is the 2D length of the same vertices (rounded to 0.1 m).
  close(route.lengthM, route.totals.length_m, 0.06);
  assert.equal(plan.warnings.length, 2);
  const kinds = plan.points.map(p => p.kind);
  assert.equal(kinds.filter(k => k === 'start').length, 1);
  assert.equal(kinds.filter(k => k === 'goal').length, 1);
  assert.equal(kinds.filter(k => k === 'station').length, 13);
});

test('GET /plan/last wraps the plan with its request; both shapes are read', () => {
  assert.equal(P.featureCollectionOf(E4), E4);
  assert.equal(P.featureCollectionOf({request: {}, plan: E4}), E4);
  assert.equal(P.featureCollectionOf({detail: 'no plan yet'}), null);
  assert.equal(P.featureCollectionOf(null), null);
});

test('densify: no step over 1 m, original vertices kept, index and length consistent', () => {
  for (const fc of [E4, FIXED]) {
    const route = P.mainRoute(P.parsePlan(fc)), c = route.coords, d = P.densify(c, 1);
    assert.ok(d.at.length >= c.length);
    close(d.length, route.lengthM, 1e-6);
    close(d.dist[d.dist.length - 1], route.lengthM, 1e-6);
    let whole = 0;
    for (let i = 0; i < d.at.length; i++) {
      if (i > 0) {
        const step = Math.hypot(d.x[i] - d.x[i - 1], d.y[i] - d.y[i - 1]);
        assert.ok(step <= 1 + 1e-9, `step ${step} m at ${i}`);
        close(d.dist[i] - d.dist[i - 1], step, 1e-6);
        assert.ok(d.at[i] >= d.at[i - 1]);
      }
      // The fractional index gives the position back from the original vertices.
      close(P.sampleAt(c.map(p => p[0]), d.at[i]), d.x[i], 1e-6);
      close(P.sampleAt(c.map(p => p[1]), d.at[i]), d.y[i], 1e-6);
      if (Number.isInteger(d.at[i])) {
        assert.deepEqual([d.x[i], d.y[i]], c[d.at[i]]);
        whole++;
      }
    }
    assert.equal(whole, c.length);
  }
});

test('densify splits long steps evenly and keeps repeated vertices', () => {
  const d = P.densify([[0, 0], [2.5, 0], [2.5, 0], [2.5, 1]], 1);
  assert.deepEqual([...d.at].map(v => Number(v.toFixed(4))), [0, 0.3333, 0.6667, 1, 2, 3]);
  assert.deepEqual([...d.dist].map(v => Number(v.toFixed(4))), [0, 0.8333, 1.6667, 2.5, 2.5, 3.5]);
  // The fixed test route does have steps over 1 m and repeated vertices.
  const c = P.mainRoute(P.parsePlan(FIXED)).coords;
  const steps = c.slice(1).map((p, i) => Math.hypot(p[0] - c[i][0], p[1] - c[i][1]));
  assert.ok(Math.max(...steps) > 1 && Math.min(...steps) === 0);
});

test('sampleAt interpolates a profile and clamps at the ends', () => {
  const route = P.mainRoute(P.parsePlan(E4)), t = route.profile.t_s;
  close(P.sampleAt(t, 10.5), (t[10] + t[11]) / 2, 1e-9);
  assert.equal(P.sampleAt(t, -3), t[0]);
  assert.equal(P.sampleAt(t, t.length + 5), t[t.length - 1]);
  assert.equal(P.sampleAt([7], 0.4), 7);
});

test('the route splits into outbound and return at the turn vertex', () => {
  const route = P.mainRoute(P.parsePlan(E4)), d = P.densify(route.coords, 1);
  const {outbound, back} = P.splitAtTurn(d, route.turnIndex);
  assert.equal(outbound[0], 0);
  assert.equal(outbound[1], back[0]);
  assert.equal(back[1], d.at.length - 1);
  assert.equal(d.at[back[0]], route.turnIndex);
  assert.deepEqual([d.x[back[0]], d.y[back[0]]], route.coords[route.turnIndex]);
  // The turn is at the goal, and the two legs add up to the route.
  const goal = P.parsePlan(E4).points.find(p => p.kind === 'goal');
  close(Math.hypot(d.x[back[0]] - goal.x, d.y[back[0]] - goal.y), 0, 1e-6);
  close(d.dist[outbound[1]] + (d.dist[back[1]] - d.dist[back[0]]), route.lengthM, 1e-6);
});

test('fixed test route: no profile, no turn, missing totals stay null', () => {
  const plan = P.parsePlan(FIXED), route = P.mainRoute(plan);
  assert.equal(route.profile, null);
  assert.equal(route.turnIndex, null);
  assert.deepEqual(route.stops, []);
  assert.equal(route.totals.time_s, null);
  assert.equal(route.totals.energy_wh, null);
  assert.equal(route.totals.feasible, null);
  assert.equal(route.totals.length_m, 3900.3);        // of the whole route, not of the cut fixture
  const d = P.densify(route.coords, 1);
  assert.deepEqual(P.splitAtTurn(d, route.turnIndex), {outbound: [0, d.at.length - 1], back: null});
  assert.deepEqual(P.planMarkers(plan).map(m => m.kind), ['habitat']);
});

test('tour (E5 shape): several stops, no goal point, nothing assumes a single goal', () => {
  const plan = P.parsePlan(tourPlan()), route = P.mainRoute(plan);
  assert.deepEqual(plan.notes, []);
  assert.deepEqual(route.stops, [{index: 3, id: 'H0'}, {index: 6, id: 'R0'}]);
  assert.equal(route.turnIndex, 6);
  const markers = P.planMarkers(plan);
  assert.deepEqual(markers.map(m => `${m.kind}:${m.label}`),
                   ['habitat:Habitat', 'station:H0', 'station:R0', 'station:C1']);
  assert.equal(markers[3].data.visited, false);
  assert.deepEqual(markers[1].color, P.TYPE_COLORS.hollow);
});

test('real E5 tour: one route with its profile, eight stops in visiting order, no goal', () => {
  const plan = P.parsePlan(TOUR), route = P.mainRoute(plan), props = TOUR.features[0].properties;
  assert.deepEqual(plan.notes, []);
  assert.equal(plan.routes.length, 1);
  assert.equal(route.coords.length, 1134);
  assert.deepEqual(Object.keys(route.profile).sort(), [...P.PROFILE_KEYS].sort());
  for (const key of P.PROFILE_KEYS) assert.equal(route.profile[key].length, 1134);
  close(route.lengthM, route.totals.length_m, 0.06);         // 1391.9 m, given to 0.1 m
  assert.equal(route.totals.time_s, 6686.7);
  assert.equal(route.totals.feasible, true);
  // The stops are the answer's own: vertex and station, in visiting order.
  assert.deepEqual(route.stops.map(s => s.id), ['R3', 'R2', 'H2', 'H4', 'H0', 'R0', 'R4', 'R1']);
  assert.deepEqual(route.stops.map(s => s.index), props.stop_index);
  assert.ok(route.stops.every((s, i) => i === 0 || s.index > route.stops[i - 1].index));
  // The answer marks the last station as the turn: the way back to the habitat is the return leg.
  assert.equal(route.turnIndex, route.stops.at(-1).index);
  assert.equal(plan.points.filter(p => p.kind === 'goal').length, 0);
  // E5 writes a 'stop' point on the route for every station it visits, where the route
  // really passes (the station snapped to its cell), next to the 13 'station' points.
  const stops = plan.points.filter(p => p.kind === 'stop');
  assert.equal(stops.length, 8);
  stops.forEach((p, i) => {
    assert.equal(String(p.properties.id), route.stops[i].id);
    const [x, y] = route.coords[route.stops[i].index];
    close(p.x, x); close(p.y, y);
  });
  assert.equal(plan.warnings.length, 3);
});

test('real E5 tour: one pin per station (visited or not), none for the stop points', () => {
  const plan = P.parsePlan(TOUR), markers = P.planMarkers(plan);
  assert.equal(markers.length, 14);                          // the habitat and the 13 stations
  assert.deepEqual(markers.map(m => m.kind), ['habitat', ...Array(13).fill('station')]);
  assert.equal(new Set(markers.map(m => m.id)).size, 14);
  assert.ok(markers.slice(1).every(m => m.id === m.label), 'no station pin was renamed by a second pin');
  const visited = markers.filter(m => m.data.visited === true), skipped = markers.filter(m => m.data.visited === false);
  assert.deepEqual(visited.map(m => m.label).sort(), ['H0', 'H2', 'H4', 'R0', 'R1', 'R2', 'R3', 'R4']);
  assert.deepEqual(skipped.map(m => m.label).sort(), ['C1', 'C2', 'H1', 'H3', 'Q1']);
  assert.deepEqual(visited.map(m => m.data.order).sort(), [1, 2, 3, 4, 5, 6, 7, 8]);
  assert.ok(skipped.every(m => m.data.order == null));
  assert.deepEqual(markers.find(m => m.label === 'R3').color, P.TYPE_COLORS.ridge);
  assert.deepEqual(markers.find(m => m.label === 'Q1').color, P.TYPE_COLORS.curiosity);
  // A stop that names no station of the plan is still shown, as a plain point.
  const lone = P.parsePlan({features: [{type: 'Feature', geometry: {type: 'Point', coordinates: [8143000, -284000]},
                                        properties: {kind: 'stop', id: 'X9'}}]});
  assert.deepEqual(P.planMarkers(lone).map(m => `${m.kind}:${m.label}`), ['point:X9']);
});

test('real E5 tour: the drawn legs split at the last station and no step is over 1 m', () => {
  const route = P.mainRoute(P.parsePlan(TOUR)), d = P.densify(route.coords, 1);
  for (let i = 1; i < d.dist.length; i++) assert.ok(d.dist[i] - d.dist[i - 1] <= 1 + 1e-9);
  const split = P.splitAtTurn(d, route.turnIndex);
  assert.equal(d.at[split.outbound[1]], route.turnIndex);
  assert.deepEqual(split.back, [split.outbound[1], d.at.length - 1]);
});

test('malformed optional fields are dropped and reported, not fatal', () => {
  const fc = tourPlan(), p = fc.features[0].properties;
  p.t_s = p.t_s.slice(0, 5);
  p.turn_index = 99;
  p.stop_index = [3, 500];
  fc.features.push({type: 'Feature', geometry: {type: 'Point', coordinates: [null, 3]}, properties: {kind: 'station'}});
  fc.features.push({type: 'Feature', geometry: {type: 'LineString', coordinates: [[1, 2]]}, properties: {kind: 'route'}});
  fc.features.push({type: 'Feature', geometry: null, properties: {}});
  const plan = P.parsePlan(fc), route = P.mainRoute(plan);
  assert.equal(route.profile.t_s, undefined);
  assert.equal(route.profile.used_wh.length, route.coords.length);
  assert.equal(route.turnIndex, null);
  assert.deepEqual(route.stops, [{index: 3, id: 'H0'}]);
  assert.equal(plan.routes.length, 1);
  assert.equal(plan.notes.length, 4);
  for (const empty of [null, {}, {features: 'x'}]) {
    assert.deepEqual(P.parsePlan(empty).routes, []);
    assert.equal(P.mainRoute(P.parsePlan(empty)), null);
  }
});

test('plan messages of the three real answers, in plain words, as the panel shows them', () => {
  assert.deepEqual(P.planMessages(P.parsePlan(TOUR).warnings), [
    {text: '8 of 13 stations visited · science value 37 · order R3 → R2 → H2 → H4 → H0 → R0 → R4 → R1', warn: false},
    {text: 'Left out, they do not fit in the limits: Q1, C1, C2, H1, H3', warn: false},
    {text: "Power used at the stations: 205 W (the planner's default)", warn: false}]);
  assert.deepEqual(P.planMessages(P.parsePlan(E4).warnings), [
    {text: 'Round trip to R0 (highest science value)', warn: false},
    {text: "Power used at the stations: 205 W (the planner's default)", warn: false}]);
  // The fixed route is not a plan, and its energy cannot be judged: both stay warnings.
  assert.deepEqual(P.planMessages(P.parsePlan(FIXED).warnings), [
    {text: "Sample route (Curiosity's path), not a plan: add stations in the planner to plan a walk", warn: true},
    {text: 'The energy for the work at the stations is not given, so the plan cannot be called energy-feasible',
     warn: true}]);
  assert.deepEqual(P.planMessages(P.parsePlan(tourPlan()).warnings), [{text: '2 of 3 stations visited', warn: false}]);
});

test('plan messages keep every number, and lose the codes, the engines and the "prize"', () => {
  const made = ['O2 budget is the tighter limit: 820 Wh of 900 usable',
                'walkback: re-planned 1 time(s) with a lower budget', 'walkback: re-planned 3 time(s) with a lower budget'];
  assert.deepEqual(P.planMessages(made), [
    {text: 'Oxygen is the tighter limit: it allows 820 Wh of the 900 Wh usable', warn: false},
    {text: 'Planned again 1 time with less energy, so the astronaut can get back from every point', warn: false},
    {text: 'Planned again 3 times with less energy, so the astronaut can get back from every point', warn: false}]);
  const all = [TOUR, E4, FIXED].flatMap(fc => P.parsePlan(fc).warnings).concat(made);
  P.planMessages(all).forEach(({text}, i) => {
    assert.doesNotMatch(text, /\bE\d{1,2}\b|src\/|plan_tour|prize|walkback|_wh_|\bnull\b/, text);
    for (const n of all[i].replace(/\bE\d+\b/g, '').match(/\d+(\.\d+)?/g) || []) assert.ok(text.includes(n), `${n} lost: ${text}`);
  });
});

test('a plan message the page does not know is shown as written, as a warning', () => {
  const moved = ['habitat moved 1.4 m to the nearest walkable cell',
                 'station R3 moved 2.0 m to the nearest walkable cell of the main connected area',
                 'service power assumed 205 W (E4 default) per astronaut', 'E5 tour: something new'];
  assert.deepEqual(P.planMessages(moved), moved.map(text => ({text, warn: true})));
  assert.deepEqual(P.planMessages(undefined), []);
  assert.deepEqual(P.planMessages([42]), [{text: '42', warn: true}]);
});

test('markers: stations by type, the goal on its station, unknown types grey', () => {
  const plan = P.parsePlan(E4), markers = P.planMarkers(plan);
  assert.equal(markers.length, 14);                       // habitat + 13 stations
  assert.equal(new Set(markers.map(m => m.id)).size, 14);
  const goal = markers.filter(m => m.kind === 'goal');
  assert.equal(goal.length, 1);
  assert.equal(goal[0].label, 'R0');
  assert.deepEqual(goal[0].color, P.TYPE_COLORS.ridge);
  // Markers stay at the stations' own coordinates (the goal point is the snapped cell).
  const r0 = E4.features.find(f => f.properties.id === 'R0').geometry.coordinates;
  assert.deepEqual([goal[0].x, goal[0].y], r0);
  assert.deepEqual(markers.find(m => m.label === 'Q1').color, P.TYPE_COLORS.curiosity);

  // Types missing from the answer come from GET /stations; otherwise the marker is grey.
  const bare = structuredClone(E4);
  for (const f of bare.features) delete f.properties.type;
  const joined = P.planMarkers(P.parsePlan(bare), {H0: 'hollow'});
  assert.deepEqual(joined.find(m => m.label === 'H0').color, P.TYPE_COLORS.hollow);
  assert.equal(joined.find(m => m.label === 'H0').data.type, 'hollow');
  assert.deepEqual(joined.find(m => m.label === 'C1').color, P.UNKNOWN_COLOR);

  // A goal that names no station gets its own marker.
  const free = structuredClone(E4);
  free.features.find(f => f.properties.kind === 'goal').properties.station = null;
  assert.deepEqual(P.planMarkers(P.parsePlan(free)).filter(m => m.kind === 'goal').map(m => m.label), ['Goal']);
});

test('the return leg is shifted to the right of travel and meets the ends', () => {
  const coords = Array.from({length: 41}, (_, i) => [i, 0]);       // heading east
  const d = P.densify(coords, 1), shifted = P.offsetSideways(d, [0, 40], 0.8);
  close(shifted.y[20], -0.8, 1e-9);                                // right of east is south
  close(shifted.x[20], 20, 1e-9);
  close(shifted.y[0], 0, 1e-9);
  close(shifted.y[40], 0, 1e-9);
  close(shifted.y[2], -0.4, 1e-9);                                 // fading in over 4 m
  // On the real route the shift never exceeds 0.8 m and is 0.8 m away from the ends.
  const route = P.mainRoute(P.parsePlan(E4)), dense = P.densify(route.coords, 1);
  const {back} = P.splitAtTurn(dense, route.turnIndex), leg = P.offsetSideways(dense, back, 0.8);
  let max = 0;
  for (let i = 0; i < leg.x.length; i++) {
    const shift = Math.hypot(leg.x[i] - dense.x[back[0] + i], leg.y[i] - dense.y[back[0] + i]);
    max = Math.max(max, shift);
    const fromEnds = Math.min(dense.dist[back[0] + i] - dense.dist[back[0]], dense.dist[back[1]] - dense.dist[back[0] + i]);
    if (fromEnds >= 4) close(shift, 0.8, 1e-9);
  }
  close(max, 0.8, 1e-9);
});

test('default request: saved stations scored by the rubric, the 2D planner limits', () => {
  const saved = {rubric: {ridge: 5, hollow: 4},
                 stations: [{id: 'R0', type: 'ridge', x: 1, y: 2, service_time_min: 10, note: 'n'},
                            {id: 'X1', type: 'other', x: 3, y: 4}]};
  const body = defaultPlanRequest([10, 20], saved);
  assert.deepEqual(body.start, [10, 20]);
  assert.deepEqual(body.stations, [{id: 'R0', x: 1, y: 2, type: 'ridge', score: 5, service_time_min: 10},
                                   {id: 'X1', x: 3, y: 4, type: 'other', score: 0, service_time_min: 0}]);
  assert.equal(body.energy_budget_wh, 1000);
  assert.equal(body.margin, 0.1);
  assert.equal(body.max_duration_min, 120);
  assert.equal(body.max_cell_slope_deg, 30);
  assert.deepEqual(defaultPlanRequest([0, 0], null).stations, []);
  assert.deepEqual(stationTypes(saved, {stations: [{id: 'H9', type: 'hollow'}]}),
                   {R0: 'ridge', X1: 'other', H9: 'hollow'});
});

// A server made of canned answers; it records every request it gets.
function fakeServer(routes) {
  const calls = [];
  const fetchFn = async (url, init) => {
    const key = `${init && init.method === 'POST' ? 'POST' : 'GET'} ${url}`;
    calls.push(key);
    if (!routes[key]) throw new Error('offline');
    const [status, body] = routes[key];
    return {ok: status < 400, status, json: async () => body};
  };
  return {fetchFn, calls};
}
const STATIONS = [200, {rubric: {ridge: 5}, stations: [{id: 'R0', type: 'ridge', x: 1, y: 2}]}];

test('the page only reads the saved plan: it never plans by itself', async () => {
  const withPlan = fakeServer({'GET /stations': STATIONS, 'POST /plan': [200, FIXED],
                               'GET /plan/last': [200, {request: {stations: []}, plan: E4}]});
  const last = await loadLastPlan(withPlan);
  assert.equal(last.source, 'last');
  assert.equal(last.fc, E4);
  assert.equal(last.missing, false);
  assert.equal(last.stationTypes.R0, 'ridge');

  // No saved plan: say so, and do NOT ask the server for one (POST /plan saves it).
  const empty = fakeServer({'GET /stations': STATIONS, 'POST /plan': [200, FIXED],
                            'GET /plan/last': [404, {detail: 'no plan yet'}]});
  const none = await loadLastPlan(empty);
  assert.equal(none.fc, null);
  assert.equal(none.missing, true);
  assert.equal(none.error, null);
  assert.equal(none.stationTypes.R0, 'ridge');

  const offline = await loadLastPlan(fakeServer({}));
  assert.equal(offline.fc, null);
  assert.equal(offline.missing, false);
  assert.match(offline.error, /no answer from the server/);
  const broken = await loadLastPlan(fakeServer({'GET /plan/last': [500, {detail: 'boom'}]}));
  assert.equal(broken.missing, false);
  assert.match(broken.error, /saved plan: boom/);

  for (const server of [withPlan, empty]) assert.ok(!server.calls.some(c => c.startsWith('POST')), server.calls.join());
});

test('default plan: one POST /plan, only when asked', async () => {
  const server = fakeServer({'GET /stations': STATIONS, 'POST /plan': [200, FIXED],
                             'GET /plan/last': [200, {request: {}, plan: E4}]});
  const made = await requestDefaultPlan({start: [10, 20], ...server});
  assert.equal(made.source, 'default');
  assert.equal(made.fc, FIXED);
  assert.deepEqual(made.request.start, [10, 20]);
  assert.equal(made.request.stations[0].score, 5);
  assert.deepEqual(server.calls, ['GET /stations', 'POST /plan']);

  const refused = await requestDefaultPlan({start: [0, 0], ...fakeServer({
    'GET /stations': STATIONS, 'POST /plan': [422, {detail: 'no feasible route: budget too small'}]})});
  assert.equal(refused.fc, null);
  assert.equal(refused.missing, false);
  assert.match(refused.error, /default request: no feasible route/);
  // Without saved stations the request still goes out, with none.
  const bare = fakeServer({'POST /plan': [200, FIXED]});
  assert.deepEqual((await requestDefaultPlan({start: [0, 0], ...bare})).request.stations, []);
});
