// Lab page (web/lab.html + web/lab.js) and the HUD solver selector. Run from the repo root:  node --test tests/web
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { convergenceSeries, routePolyline, scale, parseRoute } from '../../web/lab.js';

const read = name => readFileSync(new URL('../../web/' + name, import.meta.url), 'utf8');

test('convergenceSeries groups by algorithm and seed and sorts by t_s', () => {
  const traces = {
    sa: [
      {seed: 1, t_s: 0.5, best_prize: 4}, {seed: 0, t_s: 0.2, best_prize: 3},
      {seed: 0, t_s: 0.1, best_prize: 1}, {seed: 1, t_s: 0.1, best_prize: 2},
    ],
    dp: [{seed: '', t_s: 0.3, best_prize: 8}, {seed: '', t_s: 0.1, best_prize: 5}],
  };
  const out = convergenceSeries(traces);
  assert.deepEqual(Object.keys(out).sort(), ['dp', 'sa']);
  assert.deepEqual(out.sa['0'], [[0.1, 1], [0.2, 3]]);
  assert.deepEqual(out.sa['1'], [[0.1, 2], [0.5, 4]]);
  assert.deepEqual(out.dp[''], [[0.1, 5], [0.3, 8]]);
});

test('routePolyline keeps the visiting order', () => {
  const stations = [{id: 'habitat', x: 0, y: 0}, {id: 'A', x: 10, y: 5}, {id: 'B', x: 3, y: 9}];
  assert.equal(routePolyline(stations, ['habitat', 'B', 'A', 'habitat']), '0,0 3,9 10,5 0,0');
});

test('routePolyline can map the points through a projection', () => {
  const stations = [{id: 'a', x: 1, y: 2}, {id: 'b', x: 3, y: 4}];
  assert.equal(routePolyline(stations, ['b', 'a'], (x, y) => [x * 2, y * 2]), '6,8 2,4');
});

test('parseRoute splits a dash-joined route even when ids contain dashes', () => {
  const ids = ['habitat', 'S-1', 'S2'];
  assert.deepEqual(parseRoute('habitat-S-1-S2-habitat', ids), ['habitat', 'S-1', 'S2', 'habitat']);
  assert.deepEqual(parseRoute('', ids), []);
});

test('scale maps the domain ends to the range ends', () => {
  const f = scale([0, 10], [100, 0]);
  assert.equal(f(0), 100);
  assert.equal(f(10), 0);
  assert.equal(f(5), 50);
  assert.equal(scale([3, 3], [0, 10])(3), 5);             // degenerate domain: the middle
});

test('the HUD has a solver selector wired into the /plan body', () => {
  const html = read('index.html');
  assert.match(html, /id="solver"/);
  for (const v of ['auto', 'dp', 'cpsat', 'ils', 'sa', 'aco', 'ga'])
    assert.match(html, new RegExp(`<option value="${v}"`));
  assert.match(html, /solver:\s*ui\("solver"\)\.value/);
  assert.match(html, /href="\/lab\.html"/);
});

test('lab.html is Spanish, accessible and loads lab.js as a module', () => {
  const html = read('lab.html');
  assert.match(html, /<html lang="es"/);
  assert.match(html, /<script type="module" src="\/lab\.js">/);
  assert.match(html, /aria-live="polite"/);
  assert.match(html, /role="alert"/);
  for (const h of ['Corridas', 'Ejecutar', 'Resultados en vivo']) assert.ok(html.includes(h), h);
});
