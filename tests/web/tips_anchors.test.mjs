// Every in-context tip (#125) points at a control that exists in its page. A renamed id
// or link would otherwise only make its tip stop showing, with no test noticing.
// Run from the repo root:  node --test tests/web/
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { TIPS as TIPS_2D } from '../../web/tips.js';
import { TIPS as TIPS_3D } from '../../web/3d/tips_3d.js';

const page = path => readFileSync(new URL(`../../${path}`, import.meta.url), 'utf8');

// The parts of a selector that must be in the HTML: ids (#x) and attribute values ([a="v"]).
function parts(selector) {
  const ids = [...selector.matchAll(/#([\w-]+)/g)].map(m => `id="${m[1]}"`);
  const attrs = [...selector.matchAll(/\[([\w-]+)="([^"]+)"\]/g)].map(m => `${m[1]}="${m[2]}"`);
  return [...ids, ...attrs];
}

for (const [name, path, tips] of [['2D HUD', 'web/index.html', TIPS_2D], ['3D map', 'web/3d/index.html', TIPS_3D]]) {
  test(`${name}: every tip's control is in ${path}`, () => {
    const html = page(path);
    for (const t of tips) {
      const need = parts(t.anchor);
      assert.ok(need.length, `${t.id}: anchor ${t.anchor} names no id or attribute`);
      for (const p of need) assert.ok(html.includes(p), `${t.id}: ${p} not found in ${path}`);
    }
  });
}

test('the 3D page loads its tips', () => {
  assert.match(page('web/3d/index.html'), /<script type="module" src="\.\/tips_3d\.js"><\/script>/);
  assert.match(page('web/index.html'), /<script type="module" src="\/tips\.js"><\/script>/);
});
