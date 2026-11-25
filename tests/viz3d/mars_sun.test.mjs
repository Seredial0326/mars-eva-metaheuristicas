// Mars time and Sun position (web/3d/mars_sun.js). Run from the repo root:  node --test tests/viz3d/
//
// Reference values: the two worked examples printed at
// https://www.giss.nasa.gov/tools/mars24/help/algorithm.html (read 2026-11-14, page dated
// 2025-01-07), and real pairs of UTC and mission local time from Curiosity's raw-image
// index (fixtures/msl_lmst_pairs.json, made by src/viz3d/make_lmst_fixture.py).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import * as S from '../../web/3d/mars_sun.js';

const close = (a, b, tol, what = '') => assert.ok(Math.abs(a - b) <= tol, `${what} ${a} vs ${b} (tolerance ${tol})`);
// The page prints five decimals, some rounded and some cut (Ls 277.187589 is printed
// 277.18758, the equation of time -5.187746 as -5.18774): a value that agrees with it is
// within one unit of the last digit.
const PRINTED = 1e-5;
// Clock times compared around the 24 h wrap: 23.9999999 is next to 0.
const clockClose = (a, b, tol, what = '') => close(((a - b + 36) % 24) - 12, 0, tol, `${what} ${a} vs ${b}:`);

// [our name, printed value, tolerance]. Where the tolerance is wider than PRINTED the
// page's own digits do not follow from its formulas and printed inputs (see the test
// "the page's second example is not consistent with itself to its last digits").
const EXAMPLE_1 = {
  utc: Date.UTC(2000, 0, 6, 0, 0, 0), site: {latDeg: 0, lonEastDeg: 0},
  want: [['dtJ2000', 4.50074], ['meanAnomaly', 21.74558], ['alphaFMS', 272.74566], ['pbs', 0.00142],
         ['nuMinusM', 4.44193], ['ls', 277.18758], ['eot', -5.18774], ['mtc', 23.99425], ['lmst', 23.99425],
         ['ltst', 23.64840], ['subsolarLonWest', 174.72600], ['declination', -25.22825], ['distanceAu', 1.39358],
         ['helioLon', 2.26352], ['helioLat', -1.35957], ['zenith', 154.26182, 1e-4], ['azimuth', 191.03905]],
};
const EXAMPLE_2 = {      // Spirit's landing target, local true midnight before touchdown
  utc: Date.UTC(2004, 0, 3, 13, 46, 31), site: {latDeg: -14.640, lonEastDeg: -184.702},
  want: [['dtJ2000', 1463.07471], ['meanAnomaly', 66.06858], ['alphaFMS', 317.09457], ['pbs', 0.01614],
         ['nuMinusM', 10.22959], ['ls', 327.32416], ['eot', -12.77553], ['mtc', 13.16537], ['lmst', 0.85190],
         ['ltst', 0.00025, 1e-4], ['subsolarLonWest', 4.70500], ['declination', -13.42065, 1e-3],
         ['distanceAu', 1.47767], ['helioLon', 52.37564], ['helioLat', 0.08965], ['zenith', 151.93895, 1e-3],
         ['azimuth', 179.99383, 1e-4]],
};

for (const [name, example] of [['2000-01-06 00:00 UTC at 0 N 0 W', EXAMPLE_1], ['Spirit landing, 2004-01-03 13:46:31 UTC', EXAMPLE_2]]) {
  test(`Mars24 worked example: ${name}`, () => {
    assert.equal(S.ttMinusUtc(example.utc), 64.184);                 // the value the page uses for both
    const got = S.sunPosition(example.utc, example.site);
    for (const [key, value, tol = PRINTED] of example.want) close(got[key], value, tol, key);
  });
}

test("the page's second example is not consistent with itself to its last digits", () => {
  // Its printed LMST and equation of time give LTST 0.00020 h, not the printed 0.00025 h;
  // so the wider tolerances above are the page's, not ours.
  close(0.85190 - 0.85170, 0.00020, 1e-12);
  const got = S.sunPosition(EXAMPLE_2.utc, EXAMPLE_2.site);
  close(got.ltst, got.lmst + got.eot / 15, 1e-12);
  close(got.ltst, 0.00020, PRINTED);
  // What the example is for holds: local true midnight within a second, Sun due south.
  assert.ok(got.ltst * 3600 < 1 && Math.abs(got.azimuth - 180) < 0.01 && got.elevation < -60);
});

test('TT - UTC: the leap seconds of the date, or the value given', () => {
  assert.equal(S.ttMinusUtc(Date.UTC(2012, 7, 6)), 67.184);          // Curiosity's landing
  assert.equal(S.ttMinusUtc(Date.UTC(2016, 11, 31, 23, 59, 59)), 68.184);
  assert.equal(S.ttMinusUtc(Date.UTC(2017, 0, 1)), 69.184);
  assert.equal(S.ttMinusUtc(Date.UTC(2025, 10, 6)), 69.184);
  const utc = Date.UTC(2025, 10, 6, 12);
  assert.equal(S.marsTime(utc).ttMinusUtc, 69.184);
  // Five seconds more of TT - UTC move the Mars clock by five seconds (in Mars hours).
  const shift = S.marsTime(utc, {ttMinusUtc: 69.184}).mtc - S.marsTime(utc, {ttMinusUtc: 64.184}).mtc;
  close(shift * 3600, 5 / S.SOL_IN_DAYS, 1e-6);
});

test('longitudes are east: local time grows to the east, one hour per 15 degrees', () => {
  const utc = Date.UTC(2025, 10, 6, 12);
  const at = lon => S.localMeanSolarTime(utc, lon);
  close((at(15) - at(0) + 24) % 24, 1, 1e-9);
  close(at(137.42), at(137.42 - 360), 1e-9);
  close(at(-184.702), at(175.298), 1e-9);                            // 184.702 W of the page
  const t = S.marsTime(utc);
  close(S.localTrueSolarTime(utc, 100) - S.localMeanSolarTime(utc, 100), t.eot / 15, 1e-9);
  close((t.subsolarLonEast + t.subsolarLonWest) % 360, 0, 1e-9);
  // At the subsolar longitude it is local true noon and the Sun is overhead.
  close(S.localTrueSolarTime(utc, t.subsolarLonEast), 12, 1e-9);
  close(S.sunPosition(utc, {latDeg: t.declination, lonEastDeg: t.subsolarLonEast}).elevation, 90, 1e-5);
});

test('Sun through a sol at the equator: rises in the east, culminates on the meridian, sets in the west', () => {
  const lon = 137.39, site = {latDeg: -4.86, lonEastDeg: lon};
  const at = hours => S.sunPosition(S.utcOfTrueSolarTime(4711, hours, lon), site);
  const morning = at(7), noon = at(12), afternoon = at(15), evening = at(17);
  assert.ok(morning.azimuth > 45 && morning.azimuth < 135, `morning azimuth ${morning.azimuth}`);
  assert.ok(afternoon.azimuth > 225 && afternoon.azimuth < 315, `afternoon azimuth ${afternoon.azimuth}`);
  assert.ok(evening.azimuth > 225 && evening.azimuth < 315);
  // On the meridian at 12:00: due north or due south, and nothing higher that sol.
  assert.ok(Math.min(noon.azimuth, 360 - noon.azimuth, Math.abs(noon.azimuth - 180)) < 1e-6, `noon azimuth ${noon.azimuth}`);
  close(noon.hourAngle, 0, 1e-6);
  close(noon.elevation, 90 - Math.abs(site.latDeg - noon.declination), 1e-6);
  for (let h = 0; h < 24; h += 0.25) assert.ok(at(h).elevation <= noon.elevation + 1e-9);
  // Same height three hours before and after noon (the declination barely moves in a sol).
  close(at(9).elevation, afternoon.elevation, 0.05);
  close(morning.hourAngle, -75, 1e-6);
  close(evening.hourAngle, 75, 1e-6);
  assert.ok(at(0).elevation < -80 && at(6.5).elevation > 0 && at(17.5).elevation > 0 && at(18.5).elevation < 0);
});

test('sol and local true solar time back to UTC, and forth', () => {
  const lon = 137.3864;
  for (const [sol, hours] of [[4711, 15], [4711, 0], [4711, 23.99], [0, 12], [3000, 6.5], [4848, 17]]) {
    const utc = S.utcOfTrueSolarTime(sol, hours, lon);
    close(S.trueSolarDate(utc, lon), sol + hours / 24, 1e-9);
    clockClose(S.localTrueSolarTime(utc, lon), hours, 1e-6);         // under 4 ms
  }
  // One hour of local solar time is 1/24 of a sol, to within the drift of the equation of time.
  const step = S.utcOfTrueSolarTime(4711, 16, lon) - S.utcOfTrueSolarTime(4711, 15, lon);
  close(step / 1000, S.SOL_IN_SECONDS / 24, 1);                      // 3698.7 s against 3699.0 s that sol
  // Away from midnight the sol of the true solar clock is the mission's own sol.
  for (const hours of [2, 7, 12, 15, 22]) assert.equal(S.mslClock(S.utcOfTrueSolarTime(4711, hours, lon)).sol, 4711);
});

test("Curiosity's clock: landing was on sol 0 in the mid-afternoon", () => {
  const landing = S.mslClock(Date.UTC(2012, 7, 6, 5, 17, 57));       // touchdown, UTC at the spacecraft
  assert.equal(landing.sol, 0);
  close(landing.lmst, 15.05, 0.02);
  for (const [sol, lmst] of [[0, 0.001], [4711, 10.6], [4848, 23.999]]) {
    const back = S.mslClock(S.utcOfMslClock(sol, lmst));
    assert.equal(back.sol, sol);
    close(back.lmst, lmst, 1e-6);
  }
  close(S.mslClock(S.utcOfMslClock(4711, 0)).solDate, 4711, 1e-9);    // midnight itself, either side of the wrap
});

test("Curiosity's clock against the mission's own local times (Navcam images, sols 4450 to 4848)", t => {
  const fixture = JSON.parse(readFileSync(new URL('./fixtures/msl_lmst_pairs.json', import.meta.url), 'utf8'));
  assert.ok(fixture.pairs.length >= 30);
  assert.ok(fixture.pairs.some(p => p.sol === 4711));
  const errors = fixture.pairs.map(pair => {
    const m = /^Sol-(\d{5})M(\d\d):(\d\d):(\d\d\.\d+)$/.exec(pair.lmst);
    const got = S.mslClock(Date.parse(pair.date_taken));
    assert.equal(got.sol, Number(m[1]), `sol of ${pair.date_taken}`);
    assert.equal(got.sol, pair.sol);
    return got.lmst * 3600 - (Number(m[2]) * 3600 + Number(m[3]) * 60 + Number(m[4]));    // seconds of Mars clock
  });
  const mean = errors.reduce((a, b) => a + b, 0) / errors.length;
  const largest = Math.max(...errors.map(Math.abs));
  t.diagnostic(`${errors.length} pairs: our LMST minus the mission's is ${Math.min(...errors).toFixed(2)} to ` +
               `${Math.max(...errors).toFixed(2)} s, mean ${mean.toFixed(2)} s; every sol matches`);
  // Stated tolerance: 4 s. What is found is a steady offset: this clock is 2.4 to 3.4 s
  // AHEAD of the mission's in every pair (mean 2.85 s). The constants of Mars24 are kept
  // as published, not tuned to remove it: 3 s move the Sun by 0.012 degrees.
  assert.ok(largest < 4, `largest error ${largest.toFixed(3)} s`);
  assert.ok(mean > 2.5 && mean < 3.2, `mean error ${mean.toFixed(3)} s`);
  // Around that offset the pairs scatter by about half a second, which is what the whole
  // seconds of date_taken allow.
  for (const e of errors) assert.ok(Math.abs(e - mean) < 0.6, `error ${e.toFixed(3)} s against mean ${mean.toFixed(3)} s`);
});

test('planetographic latitude: equal at the equator and the poles, larger in between', () => {
  close(S.planetographicLatitude(0), 0, 1e-12);
  assert.equal(S.planetographicLatitude(90), 90);
  assert.equal(S.planetographicLatitude(-90), -90);
  close(S.planetographicLatitude(45) - 45, 0.338, 0.002);
  close(S.planetographicLatitude(-4.7991), -4.8558, 1e-4);           // the study box: 0.057 degrees
});
