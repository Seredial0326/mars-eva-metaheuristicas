// Adaptive walkback in the guide (X2, #101): web/guide_core.js, section "adaptive walkback".
// Run from the repo root:  node --test tests/web/
// The server is replaced by a local copy of the conjugate update, so the client logic
// (segments, chaining the posterior, meter, alarm, summary rows) is tested on its own.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import * as G from '../../web/guide_core.js';

const fixture = name => JSON.parse(readFileSync(new URL(`../viz3d/fixtures/${name}.json`, import.meta.url), 'utf8'));
const route = () => G.routeFromPlan({request: {max_duration_min: 120}, plan: fixture('plan_e4')});

// Same maths as src/fisica/adaptive_k.py and api/adaptive.py (prior N(0, 0.3^2), sigma 0.15).
function fakeServer(calls) {
  return async (url, b) => {
    calls.push({url, body: b});
    let {mu, sd, n} = b.posterior || {mu: 0, sd: 0.3, n: 0};
    if (b.segment && b.segment.observed > 0 && b.segment.predicted > 0) {
      const p0 = 1 / sd ** 2, py = 1 / 0.15 ** 2, y = Math.log(b.segment.observed / b.segment.predicted);
      mu = (mu * p0 + y * py) / (p0 + py); sd = Math.sqrt(1 / (p0 + py)); n += 1;
    }
    const kq = q => Math.exp(mu + q * sd), k90 = kq(1.2816);
    const check = k => {
      const need = k * b.return_predicted, left = b.budget - b.used;
      return {reserve_needed: need, remaining: left, margin_after_return: left - need, return_now: need > left, k};
    };
    return {posterior: {mu, sd, n}, budget: b.budget, used: b.used,
            k: {median: Math.exp(mu), mean: Math.exp(mu + sd * sd / 2), reserve: k90, q_reserve: 0.9,
                ci90: [kq(-1.6449), kq(1.6449)], ci90_width: kq(1.6449) - kq(-1.6449)},
            reserve: check(k90), fixed: check(1), return_now: check(k90).return_now};
  };
}

async function walkAll(r, state, post) {
  for (let i = 0; i < r.coords.length; i++) await G.adaptiveStep(state, r, i, post);
}

test('segments: one every 30 m, E3 prediction from the route, nothing at k_true = 1 without noise', () => {
  const r = route(), s = G.createAdaptive({kTrue: 1.0, noise: 0});
  const segs = [];
  for (let i = 0; i < r.coords.length; i++) { const g = G.adaptiveSegment(s, r, i); if (g) segs.push(g); }
  assert.ok(segs.length >= Math.floor(r.d[r.d.length - 1] / G.K_SEG_M) - 1);
  for (const g of segs) assert.ok(Math.abs(g.observed - g.predicted) < 1e-9);       // k = 1, no noise
  const total = segs.reduce((a, g) => a + g.predicted, 0);
  assert.ok(Math.abs(total - r.used[r.used.length - 1]) < 1e-6);                     // covers the route
  assert.ok(Math.abs(s.usedReal - total) < 1e-6);
});

test('the posterior is chained call to call and learns k_true = 1.5', async () => {
  const r = route(), s = G.createAdaptive({kTrue: 1.5, seed: 7}), calls = [];
  await walkAll(r, s, fakeServer(calls));
  assert.ok(calls.length > 10);
  assert.equal(calls[0].body.posterior, null);                                      // starts at the prior
  for (let c = 1; c < calls.length; c++) assert.equal(calls[c].body.posterior.n, c);  // previous answer sent back
  assert.equal(calls[0].body.plan_used.length, calls[0].body.plan_return.length);
  const last = s.history[s.history.length - 1];
  assert.ok(last.lo <= 1.5 && 1.5 <= last.hi, `IC90 ${last.lo}-${last.hi}`);
  assert.ok(Math.abs(last.k - 1.5) < 0.1);
});

test('meter and alarm: tight budget at k_true = 1.5 raises "return now"; k = 1 never does', async () => {
  const tight = {...route()}; tight.usable = 1.25 * tight.used[tight.used.length - 1];
  const s15 = G.createAdaptive({kTrue: 1.5, seed: 3});
  await walkAll(tight, s15, fakeServer([]));
  assert.ok(s15.firstAlarm, 'adaptive alarm fires');
  const m = G.kMeter(s15.history.length && s15.result);
  assert.ok(['ok', 'low', 'out'].includes(m.state) && m.word && m.text.startsWith('k '));
  const s10 = G.createAdaptive({kTrue: 1.0, noise: 0});
  await walkAll(tight, s10, fakeServer([]));
  assert.equal(s10.firstAlarmFixed, null);                                           // fixed never alarms at k = 1
  assert.equal(G.kMeter(null), null);
});

test('summary rows and alarm text', async () => {
  const r = route(), s = G.createAdaptive({kTrue: 1.2, seed: 5});
  assert.deepEqual(G.adaptiveRows(s), []);                                          // nothing walked yet
  await walkAll(r, s, fakeServer([]));
  const rows = G.adaptiveRows(s);
  assert.equal(rows.length, 4);
  assert.equal(rows[0][0], 'Metabolic factor k');
  const msg = G.kAlarmMessage(s.result);
  assert.match(msg.html, /RETURN NOW/);
  assert.match(msg.speech, /^Return now/);
});

test('a server error does not break the walk', async () => {
  const r = route(), s = G.createAdaptive();
  const failing = async () => { throw new Error('HTTP 500'); };
  for (let i = 0; i < 200; i++) await G.adaptiveStep(s, r, i, failing);
  assert.equal(s.result, null);
  assert.deepEqual(G.adaptiveRows(s), []);
});
