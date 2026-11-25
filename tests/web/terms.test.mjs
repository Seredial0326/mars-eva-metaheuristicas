// Shared glossary (web/terms.js, #166): one name, one number format and one set of state
// words for the HUD, the tablet guide and the wrist card.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import '../../web/terms.js';
import * as G from '../../web/guide_core.js';

const T = globalThis.TERMS;
const page = name => readFileSync(new URL(`../../web/${name}`, import.meta.url), 'utf8');

test('number formats: whole minutes, and a clock that never shows :60', () => {
  assert.equal(T.minutes(4.1 * 60), '4');
  assert.equal(T.min(111.4 * 60), '111 min');
  assert.equal(T.clock(779.6), '13:00');          // 12:59.6 rounds to 13:00, not 12:60
  assert.equal(T.clock(258), '4:18');
  assert.equal(T.wh(445.1), '445 Wh');
  assert.equal(T.homeIn(745), 'Home in 12 min');
});

test('state words: OK, LOW, TURN BACK, each with a level and never colour alone', () => {
  assert.deepEqual(['ok', 'low', 'out'].map(T.word), ['OK', 'LOW', 'TURN BACK']);
  assert.equal(T.STATES.out.level, 'alert');
  assert.equal(T.STATES.low.mark, '!');
  assert.equal(T.word('unknown'), 'OK');
});

test('guide_core meters use the glossary words and whole minutes', () => {
  const coords = Array.from({length: 3}, (_, k) => [k, 0]);
  const r = G.prepareRoute({coords, t: [0, 60, 120], used: [0, 1, 2], rv: [0, 1, 2], rvTime: [0, 1560, 1900],
                            usable: 100, stops: []});
  assert.equal(G.meters(r, 1).back.word, 'LOW');                    // 26 min: attention
  assert.equal(G.meters(r, 1).back.text, 'home in 26 min');
  assert.equal(G.meters(r, 2).back.word, 'TURN BACK');              // past the 30 min line
  assert.equal(G.meters(r, 0, 3600).eva.text, '60 of 60 min left');
});

test('every view loads the glossary and uses its names', () => {
  const hud = page('index.html'), guide = page('guide.html'), card = page('card.html');
  assert.match(hud, /<script src="\/terms.js"><\/script>/);
  assert.match(guide, /import "\/terms.js"|import "\.\/terms.js"/);
  assert.match(card, /import "\/terms.js"|import "\.\/terms.js"/);
  for (const [name, html] of [['index.html', hud], ['guide.html', guide], ['card.html', card]]) {
    for (const old of ['TURN SOON', 'OVER 30 MIN', 'Spare after returning', 'Time home (limit 30 min)',
                       'Back at the habitat in', 'Left after return', 'Same walk in 3D', 'Step off route']) {
      assert.ok(!html.includes(old), `${name} still says "${old}"`);
    }
  }
});
