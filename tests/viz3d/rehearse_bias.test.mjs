// Simulated energy-use bias in the 3D rehearsal (X2, #101): web/3d/rehearse_model.js.
// Run from the repo root:  node --test tests/viz3d/
// Same real answers as rehearse_model.test.mjs (read only).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import * as P from '../../web/3d/plan_model.js';
import * as R from '../../web/3d/rehearse_model.js';

const fixture = name => JSON.parse(readFileSync(new URL(`./fixtures/${name}`, import.meta.url), 'utf8'));
const routeOf = name => { const plan = P.parsePlan(fixture(name)); return {plan, route: P.mainRoute(plan)}; };

test('without a bias the rehearsal is exactly as before', () => {
  for (const name of ['plan_e4.json', 'plan_tour_e5.json', 'plan_fixed_route.json']) {
    const {plan, route} = routeOf(name);
    const a = R.buildRehearsal(route, plan.points), b = R.buildRehearsal(route, plan.points, null);
    assert.equal(a.bias, null);
    for (let s = 0; s <= 50; s++) {
      const time = a.start + a.duration * s / 50;
      assert.deepEqual(a.stateAt(time), b.stateAt(time));
      assert.ok(!a.stateAt(time).profile || !('used_real_wh' in a.stateAt(time).profile));
    }
  }
});

test('with a bias only used_real_wh is added; every other value is unchanged', () => {
  const {plan, route} = routeOf('plan_tour_e5.json');
  const a = R.buildRehearsal(route, plan.points), b = R.buildRehearsal(route, plan.points, {kTrue: 1.5});
  for (let s = 0; s <= 80; s++) {
    const time = a.start + a.duration * s / 80;
    const sa = a.stateAt(time), sb = b.stateAt(time);
    const {used_real_wh, ...rest} = sb.profile;
    assert.deepEqual({...sb, profile: rest}, sa);
    assert.ok(Number.isFinite(used_real_wh));
  }
});

test('segments every 30 m cover the route; k_true = 1 without noise is E3 itself', () => {
  const {plan, route} = routeOf('plan_e4.json');
  const m = R.buildRehearsal(route, plan.points, {kTrue: 1, noise: 0});
  const used = route.profile.used_wh, dist = m.distances;
  assert.equal(m.bias.segments[0].from, 0);
  assert.equal(m.bias.segments.at(-1).to, used.length - 1);
  for (const g of m.bias.segments.slice(0, -1)) assert.ok(dist[g.to] - dist[g.from] >= R.BIAS_SEG_M);
  for (let k = 0; k < used.length; k++) assert.ok(Math.abs(m.bias.realUsed[k] - used[k]) < 1e-9);
});

test('k_true scales the real use; the noise is seeded and averages out', () => {
  const {route} = routeOf('plan_tour_e5.json');
  const used = route.profile.used_wh, dist = P.cumulativeLength(route.coords);
  const exact = R.biasSegments(used, dist, {kTrue: 1.5, noise: 0});
  const total = used.at(-1) - used[0];
  assert.ok(Math.abs((exact.realUsed.at(-1) - used[0]) / total - 1.5) < 1e-9);
  const a = R.biasSegments(used, dist, {kTrue: 1.2, seed: 9}), b = R.biasSegments(used, dist, {kTrue: 1.2, seed: 9});
  assert.deepEqual(Array.from(a.realUsed), Array.from(b.realUsed));                 // repeatable
  const ratio = (a.realUsed.at(-1) - used[0]) / total;
  assert.ok(Math.abs(ratio - 1.2) < 0.06, `ratio ${ratio}`);                          // ~sigma/sqrt(n) noise
  for (const g of a.segments) assert.ok(g.observed >= 0 && g.predicted >= 0);
});

test('a route with no profile gets no bias', () => {
  const {plan, route} = routeOf('plan_fixed_route.json');
  assert.equal(R.buildRehearsal(route, plan.points, {kTrue: 1.5}).bias, null);
});
