// The Sun of the 3D map (web/3d/sun_model.js). Run from the repo root:  node --test tests/viz3d/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { loadDeparture } from '../../web/3d/api.js';
import { SOL_IN_SECONDS, sunPosition } from '../../web/3d/mars_sun.js';
import * as M from '../../web/3d/sun_model.js';
import { viewLink } from '../../web/3d/view_link.js';

const close = (a, b, tol = 1e-9, what = '') => assert.ok(Math.abs(a - b) <= tol, `${what} ${a} vs ${b}`);
// Centre of the study box (AGENTS.md, contract table).
const SITE = M.siteFromCrs((8142537.492786024 + 8144537.492786024) / 2, (-285463.075189438 - 283463.075189438) / 2);

test('site of the box centre from CRS metres', () => {
  close(SITE.lonEastDeg, 137.3864, 1e-4);
  close(SITE.latCentricDeg, -4.7991, 1e-4);
  close(SITE.latDeg, -4.8558, 1e-4);                     // planetographic
});

test('URL values: sol and local time', () => {
  assert.equal(M.parseSol('4711'), 4711);
  assert.equal(M.parseSol('0'), 0);
  for (const bad of ['', null, undefined, '-3', '47.5', 'abc', '10000']) assert.equal(M.parseSol(bad), null);
  assert.equal(M.parseClock('15:00'), 15);
  assert.equal(M.parseClock('7:30'), 7.5);
  assert.equal(M.parseClock('07'), 7);
  for (const bad of ['', null, '24:00', '12:60', '15h', '1500', '-1:00']) assert.equal(M.parseClock(bad), null);
  assert.equal(M.clockText(15), '15:00');
  assert.equal(M.clockText(7.0833), '07:05');
  assert.equal(M.clockText(23.9999), '00:00');
  assert.equal(M.clockText(24.5), '00:30');
});

test('compass words and the light vector in scene axes (X east, Y up, Z south)', () => {
  assert.deepEqual([0, 44, 90, 135, 180, 225, 270, 315, 350, -10].map(M.compassWord),
                   ['north', 'north-east', 'east', 'south-east', 'south', 'south-west', 'west', 'north-west', 'north', 'north']);
  const same = (a, b) => a.forEach((v, i) => close(v, b[i], 1e-12));
  same(M.sunVector(0, 0), [0, 0, -1]);                   // from the north: -Z
  same(M.sunVector(90, 0), [1, 0, 0]);                   // from the east
  same(M.sunVector(270, 0), [-1, 0, 0]);
  same(M.sunVector(123, 90), [0, 1, 0]);
  const v = M.sunVector(282, 44);
  close(Math.hypot(...v), 1, 1e-12);
});

test('light levels: full by day, no sun light at the horizon, a dim sky at night, no jumps', () => {
  const day = M.lightLevels(44), horizon = M.lightLevels(0), night = M.lightLevels(-30);
  assert.deepEqual([day.sun, day.sky, day.night], [M.SUN_FULL, M.SKY_DAY, false]);     // as before this block
  assert.equal(horizon.sun, 0);
  assert.equal(night.sun, 0);
  assert.equal(night.sky, M.SKY_NIGHT);
  assert.ok(night.night && M.SKY_NIGHT > 0.2);                                         // never black
  assert.ok(horizon.sky > M.SKY_NIGHT && horizon.sky < M.SKY_DAY);
  let prev = M.lightLevels(-20);
  for (let el = -19.9; el <= 30; el += 0.1) {
    const now = M.lightLevels(el);
    assert.ok(now.sun >= prev.sun && now.sky >= prev.sky && now.day >= prev.day, `monotonic at ${el}`);
    assert.ok(now.sun - prev.sun < 0.04 && now.sky - prev.sky < 0.02, `smooth at ${el}`);
    prev = now;
  }
});

test('default afternoon: sol 4711 at 15:00 is lit from the west at full level', () => {
  const s = M.sunState({sol: M.DEFAULT_SOL, hours: M.DEFAULT_HOURS}, SITE);
  assert.equal(new Date(s.utcMs).toISOString().slice(0, 16), '2025-11-06T16:52');
  close(s.ltst, 15, 1e-6);
  close(s.elevation, 43.9, 0.1);
  close(s.azimuth, 282.3, 0.1);
  close(s.ls, 167.4, 0.1);
  assert.equal(s.sun, M.SUN_FULL);
  assert.equal(s.sky, M.SKY_DAY);
  assert.ok(s.direction[0] < 0 && s.direction[1] > 0 && s.direction[2] < 0);           // west, up, a little north
  assert.equal(M.readoutText(s), 'Sun 44° high, light from the west');
  assert.equal(M.readoutTitle(s), 'The Sun is 43.9° above the horizon, 282.3° clockwise from north (azimuth). ' +
                                  "Season: 167.4° round Mars's orbit from the start of northern spring (solar longitude, Ls).");
  assert.equal(M.utcText(s.utcMs), '2025-11-06 16:52 UTC');
});

test('morning from the east, afternoon from the west, noon on the meridian, night says so', () => {
  const at = hours => M.sunState({sol: 4711, hours}, SITE);
  assert.ok(at(7).direction[0] > 0.9 && at(17).direction[0] < -0.9);                   // opposite sides
  close(at(7).elevation, at(17).elevation, 0.05);
  close(at(12).direction[0], 0, 1e-6);
  assert.ok(at(12).elevation > at(11).elevation && at(12).elevation > at(13).elevation);
  const night = at(21);
  assert.ok(night.night && night.sun === 0 && night.sky === M.SKY_NIGHT);
  assert.equal(M.readoutText(night), 'Night: the Sun is 45° below the horizon');
  assert.match(M.readoutTitle(night), /^The Sun is 45\.2° below the horizon\. Season: 167\.5° round Mars's orbit/);
  assert.equal(M.readoutText(at(18)), 'Night: the Sun is 1° below the horizon');             // 0.45° under it
  assert.equal(M.readoutText(at(11)), 'Sun 72° high, light from the north-east');
});

test('the readout says it in plain words at every time of the sol; the numbers stay in its tooltip', () => {
  for (let minute = 0; minute < 1440; minute += 5) {
    const s = M.sunState({sol: 4711, hours: minute / 60}, SITE), text = M.readoutText(s);
    assert.doesNotMatch(text, /azimuth|\bLs\b/i, `${M.clockText(minute / 60)}: ${text}`);
    assert.match(text, s.night ? /^Night: the Sun is \d+° below the horizon$/
                               : /^Sun \d+° high, light from the (north|east|south|west|north-east|south-east|south-west|north-west)$/);
    assert.match(M.readoutTitle(s), /\(solar longitude, Ls\)\.$/);
  }
});

test('rehearsal: the Sun advances with the elapsed EVA time from the chosen start', () => {
  const start = M.sunState({sol: 4711, hours: 15}, SITE);
  const later = M.sunState({sol: 4711, hours: 15, elapsedS: 2402.5}, SITE);            // the E4 plan: 40 min
  assert.equal(later.startUtcMs, start.utcMs);
  close(later.utcMs - start.utcMs, 2402500, 1e-6);
  close(later.ltst - 15, M.solarHours(2402.5), 1e-4);                                  // 39 min of Mars clock
  close(M.solarHours(SOL_IN_SECONDS), 24, 1e-12);
  assert.equal(M.clockText(later.ltst), '15:39');
  close(later.hourAngle - start.hourAngle, 360 * 2402.5 / SOL_IN_SECONDS, 1e-3);       // 9.7 degrees
  assert.ok(later.elevation < start.elevation);
  // The state is the Sun of mars_sun.js at that instant, nothing else.
  const p = sunPosition(later.utcMs, SITE);
  assert.deepEqual([later.elevation, later.azimuth, later.ls], [p.elevation, p.azimuth, p.ls]);
});

// ---- the plan's best time to leave (GET /plan/departure, #124) ------------------------
// An answer for the 120 min E5 tour on sol 4711, in the shape of api/departure.py, with the
// times that tests/api/test_departure_api.py asserts (best 11:00, all lit 06:45-15:15);
// the 57 rows are left out.
const DEPARTURE = {
  sol: 4711, duration_min: 111.4, habitat_lon_east_deg: 137.3864, habitat_lat_deg: -4.7991,
  clock: 'local true solar time at the habitat (start_lmst_h: local mean solar time, the mission clock)',
  step_min: 15, lit_window_ltst_h: [6.75, 15.25],
  best: {start_ltst_h: 11, start_lmst_h: 10.367, end_ltst_h: 12.876, sunlit_share: 1, shadow_share: 0, dark_share: 0,
         min_sun_elevation_deg: 71.8, longest_unlit_min: 0},
  best_clock: '11:00', best_mission_clock: '10:22', lit_window_clock: ['06:45', '15:15'], rows: [],
};
const answer = (best, more = {}) => ({...DEPARTURE, best: best === null ? null : {...DEPARTURE.best, ...best}, ...more});

test('the best time to leave is read from the planner\'s answer, and only from a usable one', () => {
  assert.equal(M.DEFAULT_HOURS, 15);                                      // the start without it
  assert.equal(M.bestDeparture(DEPARTURE, 4711), 11);
  assert.equal(M.bestDeparture(answer({start_ltst_h: 6.75}), 4711), 6.75);
  assert.equal(M.bestDeparture(answer({start_ltst_h: 10.2499}), 4711), 10.25);          // to the minute
  assert.equal(M.bestDeparture(answer({sunlit_share: 0.37}), 4711), 11);                // partly lit: still the best there is
  // The clock text when the hours are missing.
  assert.equal(M.bestDeparture(answer({start_ltst_h: undefined}), 4711), 11);
  assert.equal(M.bestDeparture(answer({start_ltst_h: undefined}, {best_clock: '07:30'}), 4711), 7.5);
  // Nothing usable: the start stays as it is.
  for (const bad of [null, undefined, '', 'eleven', 11, [], {}, {detail: 'no plan yet: plan an EVA in the HUD first'}]) {
    assert.equal(M.bestDeparture(bad, 4711), null, JSON.stringify(bad));
  }
  assert.equal(M.bestDeparture(DEPARTURE, 4712), null);                   // an answer for another sol
  assert.equal(M.bestDeparture(answer(null), 4711), null);                // no best departure
  assert.equal(M.bestDeparture(answer({sunlit_share: 0}), 4711), null);   // no sunlight at all on the walk
  for (const hours of [-0.25, 24, 25, NaN, Infinity, '11']) {
    assert.equal(M.bestDeparture(answer({start_ltst_h: hours}, {best_clock: null}), 4711), null, String(hours));
  }
  assert.equal(M.bestDeparture(answer({start_ltst_h: undefined}, {best_clock: '24:00'}), 4711), null);
});

test('a start at the best time travels in a view link and comes back the same', () => {
  // Every departure the planner tries: 05:00 to 19:00 every 15 min (api/departure.py).
  for (let quarter = 20; quarter <= 76; quarter++) {
    const hours = M.bestDeparture(answer({start_ltst_h: quarter / 4}), 4711);
    const link = viewLink('http://localhost:8000/3d/', '', {view: '1,2,3,4,5', sol: 4711, lt: M.clockText(hours)});
    const back = new URL(link).searchParams;
    assert.equal(M.parseClock(back.get('lt')), hours, link);
    assert.equal(M.parseSol(back.get('sol')), 4711);
  }
});

test('the note says when the start is the planner\'s best time to leave, in plain words', () => {
  const utcMs = M.sunState({sol: 4711, hours: 11}, SITE).utcMs, best = {sol: 4711, hours: 11};
  const earth = 'On Earth: 2025-11-06 12:45 UTC.';
  assert.equal(M.utcText(utcMs), '2025-11-06 12:45 UTC');
  assert.equal(M.noteText({sol: 4711, hours: 11, best, utcMs}), `Starts at the best time to leave, 11:00, as the planner suggests. ${earth}`);
  assert.equal(M.noteText({sol: 4711, hours: 15, best, utcMs}), `The planner suggests leaving at 11:00. ${earth}`);
  assert.equal(M.noteText({sol: 4711, hours: 11, rehearsing: true, best, utcMs}),
               `Following the EVA clock: it started at 11:00, the best time to leave. ${earth}`);
  assert.equal(M.noteText({sol: 4711, hours: 15, rehearsing: true, best, utcMs}), `Following the EVA clock: it started at 15:00. ${earth}`);
  // The slider moves in whole minutes: 11:00 set by hand is the best time again.
  assert.equal(M.noteText({sol: 4711, hours: 660 / 60, best: {sol: 4711, hours: 11.004}, utcMs}),
               `Starts at the best time to leave, 11:00, as the planner suggests. ${earth}`);
  // Another sol than the one asked, or no best time: the note is as before.
  assert.equal(M.noteText({sol: 4712, hours: 11, best, utcMs}), earth);
  assert.equal(M.noteText({sol: 4711, hours: 15, utcMs}), earth);
  assert.equal(M.noteText({sol: 4711, hours: 15, rehearsing: true, utcMs}), `Following the EVA clock: it started at 15:00. ${earth}`);
});

test('GET /plan/departure: the answer, or null without a plan, a clock or a server', async () => {
  const urls = [];
  const server = (status, body) => async url => { urls.push(url); return {ok: status < 400, status, json: async () => body}; };
  assert.deepEqual(await loadDeparture(4711, {fetchFn: server(200, DEPARTURE)}), DEPARTURE);
  assert.deepEqual(urls, ['/plan/departure?sol=4711']);
  assert.equal(M.bestDeparture(await loadDeparture(4600, {fetchFn: server(200, {...DEPARTURE, sol: 4600})}), 4600), 11);
  assert.equal(urls[1], '/plan/departure?sol=4600');
  assert.equal(await loadDeparture(4711, {fetchFn: server(404, {detail: 'no plan yet: plan an EVA in the HUD first'})}), null);
  assert.equal(await loadDeparture(4711, {fetchFn: server(422, {detail: 'the last plan has no timed route'})}), null);
  assert.equal(await loadDeparture(0, {fetchFn: server(422, {detail: [{msg: 'Input should be greater than or equal to 1'}]})}), null);
  assert.equal(await loadDeparture(4711, {fetchFn: async () => { throw new Error('offline'); }}), null);
  assert.equal(await loadDeparture(4711, {fetchFn: async () => ({ok: true, status: 200, json: async () => { throw new Error('not JSON'); }})}), null);
});
