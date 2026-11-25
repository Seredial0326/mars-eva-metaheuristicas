// Adaptive walkback in the 3D rehearsal (X2, #129): the card rows. The wiring in
// web/3d/rehearse.js reuses guide_core (tested in tests/web/guide_adaptive_k.test.mjs);
// this checks the one pure piece it adds. Run from the repo root:  node --test tests/viz3d/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import * as G from '../../web/guide_core.js';
import { adaptiveCardRows, kAlarmAction } from '../../web/3d/rehearse_model.js';

test('adaptive rows become card rows; "—" plans are left out of the text', () => {
  const rows = adaptiveCardRows([['Metabolic factor k', '1.00 (model)', '1.42 (90 % 1.31–1.55)'],
                                 ['Real energy (simulated k)', '—', '62 Wh']]);
  assert.deepEqual(rows, [['Metabolic factor k', '1.42 (90 % 1.31–1.55) · plan 1.00 (model)'],
                          ['Real energy (simulated k)', '62 Wh']]);
  assert.deepEqual(adaptiveCardRows([['Energy', '133 Wh', '140 Wh']]), [['Energy', '140 Wh (plan 133 Wh)']]);
  assert.deepEqual(adaptiveCardRows(null), []);
  assert.deepEqual(adaptiveCardRows([]), []);
});

test('nothing learned yet: no rows on the card (guide_core.adaptiveRows of a fresh walk)', () => {
  assert.deepEqual(adaptiveCardRows(G.adaptiveRows(G.createAdaptive({kTrue: 1.5}))), []);
});

test('RETURN NOW banner: the tablet rules (storm owns it, cleared on the way home, shown once)', () => {
  const a = o => kAlarmAction({returnNow: false, storm: false, home: false, showing: false, ...o});
  assert.equal(a({returnNow: true}), 'show');
  assert.equal(a({returnNow: true, showing: true}), 'keep');               // shown once
  assert.equal(a({returnNow: false, showing: true}), 'clear');             // the way home fits again
  assert.equal(a({returnNow: true, showing: true, home: true}), 'clear');  // walking home: nothing to add
  assert.equal(a({returnNow: true, home: true}), 'keep');
  assert.equal(a({returnNow: true, storm: true}), 'keep');                 // a storm owns the banner
  assert.equal(a({returnNow: false, storm: true, showing: true}), 'keep');
  assert.equal(a({}), 'keep');
});
