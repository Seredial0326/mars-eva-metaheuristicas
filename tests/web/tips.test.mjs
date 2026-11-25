// In-context tips of the 2D HUD (web/tips.js, #125). Run from the repo root:  node --test tests/web/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { TIPS, nextTip, retired, tipsMode } from '../../web/tips.js';

const base = (over = {}) => ({tab: 'terrain', stations: 0, planned: false, profile: false,
  probeOpen: false, seen: [], visited: [], visible: () => true, ...over});
const ids = TIPS.map(t => t.id);

test('every tip has an id, an anchor, a title and a short text', () => {
  assert.equal(new Set(ids).size, ids.length);
  for (const t of TIPS) {
    assert.ok(t.anchor && t.title && t.text, t.id);
    assert.ok(t.text.length <= 160, `${t.id} is too long for a tip`);
  }
});

test('the demo flow shows one tip at each step, in order', () => {
  const seen = [];
  const step = (over) => {
    const s = base({...over, seen: [...seen]});
    for (const id of retired(s)) if (!seen.includes(id)) seen.push(id);
    const t = nextTip({...s, seen});
    if (t) seen.push(t.id);                     // the user reads it and closes it
    return t && t.id;
  };
  assert.equal(step({tab: 'terrain'}), 'layers');
  assert.equal(step({tab: 'stations', visited: ['terrain', 'stations']}), 'stations');
  assert.equal(step({tab: 'stations', stations: 13, visited: ['terrain', 'stations']}), 'go-plan');
  assert.equal(step({tab: 'plan', stations: 13, visited: ['terrain', 'stations', 'plan']}), 'plan');
  assert.equal(step({tab: 'plan', stations: 13, planned: true, visited: ['terrain', 'stations', 'plan']}), 'rehearse');
  const walk = {tab: 'walk', stations: 13, planned: true, profile: true, visited: ['terrain', 'stations', 'plan', 'walk']};
  assert.equal(step(walk), 'play');
  assert.equal(step(walk), 'probe');
  assert.equal(step(walk), 'views');
  assert.equal(step(walk), null);              // nothing left on this tab
  assert.equal(step({...walk, tab: 'context'}), 'storm');
  assert.equal(step({...walk, tab: 'context'}), null);
  assert.deepEqual([...seen].sort(), [...ids].sort());
});

test('a seen tip never comes back', () => {
  assert.equal(nextTip(base({seen: ['layers']})), null);
});

test('doing what a tip suggests retires it without showing it', () => {
  const s = base({tab: 'plan', stations: 5, planned: true, visited: ['plan']});
  const r = retired(s);
  assert.ok(r.includes('layers') && r.includes('stations') && r.includes('plan') && r.includes('go-plan'));
  assert.equal(nextTip({...s, seen: r}).id, 'rehearse');
});

test('no tip while its control is not on screen', () => {
  const s = base({tab: 'plan', stations: 3, visible: sel => sel !== '#plan-btn'});
  assert.equal(nextTip({...s, seen: retired(s)}), null);
});

test('saved stations do not hide the first tips; "ready to plan" waits for the stations tip', () => {
  // the HUD loads the saved list at start, so a new user already has stations
  const s = base({tab: 'terrain', stations: 13});
  assert.equal(nextTip({...s, seen: retired(s)}).id, 'layers');
  const st = base({tab: 'stations', stations: 13, seen: ['layers']});
  assert.equal(nextTip(st).id, 'stations');
  assert.equal(nextTip({...st, seen: ['layers', 'stations']}).id, 'go-plan');
});

test('plan tip only before a plan', () => {
  assert.equal(nextTip(base({tab: 'plan', planned: true, seen: ['rehearse']})), null);
});

test('?tips= switch', () => {
  assert.equal(tipsMode('?tips=reset'), 'reset');
  assert.equal(tipsMode('?x=1&tips=off'), 'off');
  assert.equal(tipsMode('?tips=yes'), null);
  assert.equal(tipsMode(''), null);
});
