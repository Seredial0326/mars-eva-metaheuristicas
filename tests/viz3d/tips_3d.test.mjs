// In-context tips of the 3D map (web/3d/tips_3d.js, #125). Run from the repo root:
//   node --test tests/viz3d/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import { TIPS, nextTip, retired, tipsOn } from '../../web/3d/tips_3d.js';
import { tipNumber } from '../../web/tips_core.js';

const base = (over = {}) => ({tab: 'free', loaded: true, hasPlan: true, noPlan: false,
  canRehearse: true, meters: false, arrived: false, played: false, stationsOpen: false,
  moreOpen: false, sunOpen: false, reliefMoved: false,
  seen: [], visited: ['free'], visible: () => true, ...over});
const ids = TIPS.map(t => t.id);

// Show the tip due now and close it, as a user who reads every tip would.
function walker() {
  const seen = [];
  return over => {
    const s = base({...over, seen: [...seen]});
    for (const id of retired(s)) if (!seen.includes(id)) seen.push(id);
    const t = nextTip({...s, seen});
    if (t) seen.push(t.id);
    return t && t.id;
  };
}

test('every tip has an id, an anchor, a title and a short text', () => {
  assert.equal(new Set(ids).size, ids.length);
  for (const t of TIPS) {
    assert.ok(t.anchor && t.title && t.text, t.id);
    assert.ok(t.text.length <= 160, `${t.id} is too long for a tip (${t.text.length})`);
  }
});

test('the demo flow of the 3D user guide, one tip at each step, in order', () => {
  const step = walker();
  assert.equal(step({}), 'view');
  assert.equal(step({}), 'plan');
  assert.equal(step({}), 'relief');
  assert.equal(step({}), 'rehearse');
  assert.equal(step({}), null);                          // nothing else before rehearsing
  const rh = {tab: 'rehearse', visited: ['free', 'rehearse']};
  assert.equal(step(rh), 'play');
  assert.equal(step(rh), null);                          // the meters wait for Play
  const playing = {...rh, played: true, meters: true};
  assert.equal(step(playing), 'meters');
  assert.equal(step(playing), 'trouble');
  assert.equal(step(playing), 'more');
  assert.equal(step(playing), 'exit');
  assert.equal(step(playing), null);
  const back = {tab: 'free', visited: ['free', 'rehearse']};
  assert.equal(step(back), 'sun');
  assert.equal(step(back), 'walk');
  assert.equal(step(back), null);
});

test('without a saved plan the first tips point at the default plan, not at the plan', () => {
  const step = walker();
  const none = {hasPlan: false, noPlan: true, canRehearse: false};
  assert.equal(step(none), 'view');
  assert.equal(step(none), 'no-plan');
  assert.equal(step(none), 'relief');
  assert.equal(step(none), null);                         // no Rehearse without a route
  assert.equal(step({}), 'plan');                         // the plan arrived: what it says,
  assert.equal(step({}), 'rehearse');                     // then rehearse it
});

test('doing what a tip suggests retires it', () => {
  const s = base({stationsOpen: true, reliefMoved: true, visited: ['free', 'rehearse', 'walk'],
                  played: true, moreOpen: true, sunOpen: true, hasPlan: true});
  const r = retired(s);
  for (const id of ['plan', 'relief', 'rehearse', 'play', 'more', 'sun', 'walk', 'no-plan']) assert.ok(r.includes(id), id);
  assert.ok(!r.includes('view') && !r.includes('meters') && !r.includes('exit'));
});

test('an arrival goes straight to the exit tip', () => {
  const s = base({tab: 'rehearse', visited: ['free', 'rehearse'], arrived: true, played: true,
                  seen: ['view', 'plan', 'relief', 'rehearse', 'play', 'meters', 'trouble', 'more']});
  assert.equal(nextTip(s).id, 'exit');
  const early = base({tab: 'rehearse', visited: ['free', 'rehearse'], arrived: true,
                      seen: ['view', 'plan', 'relief', 'rehearse']});
  assert.equal(nextTip(early).id, 'exit');               // played to the end, Play's tip is over
});

test('no tip while its control is not on screen, no tip before the terrain', () => {
  assert.equal(nextTip(base({loaded: false, hasPlan: false, canRehearse: false})), null);
  const hidden = base({seen: ['view', 'plan', 'relief'], visible: sel => sel !== '#rehearse'});
  assert.equal(nextTip(hidden), null);
});

test('"no plan" shares the number of the plan tip; 11 tips in all', () => {
  const by = id => TIPS.find(t => t.id === id);
  assert.deepEqual(tipNumber(by('view'), TIPS), {n: 1, total: 11});
  assert.deepEqual(tipNumber(by('no-plan'), TIPS), {n: 2, total: 11});
  assert.deepEqual(tipNumber(by('plan'), TIPS), {n: 2, total: 11});
  assert.deepEqual(tipNumber(by('walk'), TIPS), {n: 11, total: 11});
});

test('off with ?tips=off and while a ?check= runs', () => {
  assert.equal(tipsOn(''), true);
  assert.equal(tipsOn('?tips=reset'), true);
  assert.equal(tipsOn('?tips=off'), false);
  assert.equal(tipsOn('?check=rehearse'), false);
  assert.equal(tipsOn('?q=low&check=sun&tips=reset'), false);
});
