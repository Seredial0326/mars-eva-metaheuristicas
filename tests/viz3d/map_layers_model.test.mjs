// Map layers of the 3D map (web/3d/map_layers_model.js, issue #110). Run from the repo
// root:  node --test tests/viz3d/
//
// Every legend string, colour and URL that mirrors the 2D HUD is asserted twice: against
// the literal copied here, and as text found in web/index.html, so a change on either
// side is noticed. The layer names and hover texts are the HUD's words without its project
// codes (#124), checked the same way. The slope tile colours are checked against SLOPE_RAMP of
// src/gis/tiles.py. Fixture: fixtures/tiles_meta.json, the tiles.json of the tiles
// release (data/tiles/tiles.json), as served in GET /layers.
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import { DEFAULT_LIMITS } from '../../web/3d/api.js';
import { parsePlan } from '../../web/3d/plan_model.js';
import * as L from '../../web/3d/map_layers_model.js';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8');
const HUD = read('../../web/index.html').replace(/\r\n/g, '\n');
const TILES_PY = read('../../src/gis/tiles.py').replace(/\r\n/g, '\n');
const META = JSON.parse(read('./fixtures/tiles_meta.json'));
const PLAN_E4 = parsePlan(JSON.parse(read('./fixtures/plan_e4.json')));
const BBOX = {xmin: 8142537.492786024, ymin: -285463.075189438, xmax: 8144537.492786024, ymax: -283463.075189438};
const CENTRE = [(BBOX.xmin + BBOX.xmax) / 2, (BBOX.ymin + BBOX.ymax) / 2];
const close = (a, b, tol, what = '') => assert.ok(Math.abs(a - b) <= tol, `${what} ${a} vs ${b} (tolerance ${tol})`);
const inHud = (text, what = text) => assert.ok(HUD.includes(text), `web/index.html no longer contains: ${what}`);
const shifted = (east, north = 0) => ({xmin: BBOX.xmin + east, xmax: BBOX.xmax + east,
                                       ymin: BBOX.ymin + north, ymax: BBOX.ymax + north});

// A w x h RGBA image from fn(i, j) -> [r, g, b, a].
function image(w, h, fn) {
  const out = new Uint8Array(w * h * 4);
  for (let i = 0; i < h; i++) for (let j = 0; j < w; j++) out.set(fn(i, j), (i * w + j) * 4);
  return out;
}
// The 8-bit colour of a slope on a ramp, as gdaldem color-relief writes it (linear between stops).
function rampColor(deg, ramp = L.SLOPE_TILE_RAMP) {
  let k = 0;
  while (k < ramp.length - 2 && ramp[k + 1].deg <= deg) k++;
  const a = ramp[k], b = ramp[k + 1], t = (deg - a.deg) / (b.deg - a.deg);
  return a.rgb.map((v, c) => Math.round(v + t * (b.rgb[c] - v)));
}
// Repeatable noise (a small LCG), so the tests do not depend on Math.random.
function noise(seed) {
  let s = seed >>> 0;
  return () => ((s = (Math.imul(s, 1664525) + 1013904223) >>> 0) >>> 24);
}

test('six layers in drawing order, with the labels, sources and default sliders of the spec', () => {
  assert.deepEqual(L.LAYERS.map(l => l.id), ['radio', 'slope', 'steep', 'sand', 'cost', 'rocks']);
  assert.deepEqual(L.LAYERS.map(l => l.label), ['Radio coverage', 'Slope', 'Too steep to cross',
                                                'Sand detected', 'Walking cost', 'Boulders']);
  assert.deepEqual(L.LAYERS.map(l => l.source), ['png', 'tiles', 'png', 'png', 'png', 'png']);
  assert.deepEqual(L.LAYERS.map(l => l.slider), [1, 0.5, 1, 1, 0.75, 1]);
  for (const l of L.LAYERS) {
    assert.equal(L.layerById(l.id), l);
    assert.ok(['fill', 'gradient', 'hatch', 'dots'].includes(l.legend.kind), l.id);
    assert.ok(Array.isArray(l.legend.ticks), l.id);
    for (const v of Object.values(l.legend)) if (typeof v === 'string') assert.doesNotMatch(v, /[<>]/, `${l.id}: HTML in the legend`);
  }
  assert.equal(L.layerById('thermal'), null);
  // The default sliders are the 2D's: slope-opacity starts at 0.5, the cost is drawn at 0.75 ** 2.2.
  inHud('id="slope-opacity" min="0" max="1" step="0.05" value="0.5"');
  inHud('opacity: Math.pow(0.75, 2.2)');
  inHud('Math.pow(Math.min(Number(ui("slope-opacity").value), currentTab === "walk" ? 0.18 : 1), 2.2)');
});

test('legend data copied from the HUD, literally', () => {
  const g = id => L.layerById(id).legend;
  assert.deepEqual(g('radio'), {kind: 'fill', css: 'rgba(42,120,214,0.75)', sidebar: 'rgba(42,120,214,0.7)', border: null,
    text: 'Habitat antenna in sight', caption: 'the habitat antenna is in sight', ticks: [], unit: null,
    note: 'Line of sight on the 1 m terrain model (cautious).'});
  assert.deepEqual(g('slope'), {kind: 'gradient', css: 'linear-gradient(90deg,#1a9850 0%,#fee08b 33.3%,#f46d43 66.7%,#a50026 100%)',
    sidebar: 'linear-gradient(90deg, #1a9850 0%, #fee08b 33.3%, #f46d43 66.7%, #a50026 100%)', border: null,
    text: 'Slope, 0° to 45°', caption: null, ticks: ['0°', '15°', '30°', '45°+'], unit: '°', note: null});
  const hatch = 'repeating-linear-gradient(45deg, rgba(14,16,20,.95) 0 3px, rgba(14,16,20,.45) 3px 6px)';
  assert.deepEqual(g('steep'), {kind: 'hatch', css: hatch, sidebar: hatch, border: '1px solid rgba(255,255,255,.25)',
    text: 'Too steep to cross (over {limit}°)', caption: 'Never cross cells steeper than {limit}°', ticks: [],
    unit: '°', note: null});
  assert.deepEqual(g('sand'), {kind: 'gradient', css: 'rgb(250,246,235)',
    sidebar: 'linear-gradient(90deg, rgba(250,246,235,0), rgb(250,246,235))', border: null, text: 'Sand detected',
    caption: 'A cautious detector: when it marks sand it is right about 92 % of the time, but it misses a lot of sand.',
    ticks: ['0', 'sand fraction per 1 m cell', '1'], unit: 'sand fraction per 1 m cell', note: null});
  assert.deepEqual(g('cost'), {kind: 'gradient', css: 'linear-gradient(90deg,#000004,#8c2981,#fe9f6d,#fcfdbf)',
    sidebar: 'linear-gradient(90deg, #000004, #3b0f70, #8c2981, #de4968, #fe9f6d, #fcfdbf)', border: null,
    text: 'Walking cost, low to high', caption: null, ticks: ['', 'Wh per 1 m cell', ''], unit: 'Wh per 1 m cell',
    note: null});
  assert.deepEqual(g('rocks'), {kind: 'dots', css: 'rgb(232, 236, 255)', sidebar: null, border: '1px solid #0a0c10',
    dots: [4, 7, 10], text: 'Boulders (bigger dot, more cover)',
    caption: 'bigger dot, more of the 10 m square under boulders (largest: 10 % or more)', ticks: [], unit: null,
    note: 'Boulders larger than about 1 m. Shown for context: the route cost does not use them.'});
  assert.equal(L.layerById('radio').title, 'Line of sight from the habitat antenna to a suit radio');
  assert.equal(L.layerById('sand').title, 'Sand detected on the orbital photo by a neural network');
  assert.equal(L.layerById('cost').title, 'Energy to cross each 1 m cell (Santee 2001, Mars gravity)');
  assert.equal(L.layerById('rocks').title, 'Boulders found on the orbital photo by a neural network');
  assert.equal(L.layerById('slope').title, null);
  assert.equal(L.layerById('steep').title, null);
});

test('layer names and hover texts: the HUD\'s words, without its project codes', () => {
  // <label title="E8: sand detected on …"><input type="checkbox" id="show-sand"> Sand detected</label>
  for (const id of ['radio', 'slope', 'sand', 'cost', 'rocks']) {
    const layer = L.layerById(id);
    const hud = new RegExp(`<label(?: title="([^"]*)")?><input type="checkbox" id="show-${id}"[^>]*>\\s*([^<]+?)\\s*</label>`).exec(HUD);
    assert.ok(hud, `web/index.html has no "${id}" checkbox any more`);
    assert.equal(layer.label, hud[2], `${id}: the HUD names it "${hud[2]}"`);
    // The HUD's hover text less its code ("E8: "); the 3D's may stop before a closing note.
    const words = (hud[1] ?? '').replace(/^E\d+:\s*/, '');
    if (layer.title) assert.ok(words.toLowerCase().startsWith(layer.title.toLowerCase()), `${id}: the HUD says "${hud[1]}"`);
    else assert.equal(hud[1], undefined, `${id}: the HUD has a hover text now, "${hud[1]}"`);
  }
  // The steep layer is named as the HUD's map legend names it.
  inHud(`<i class="hatch"></i>${L.layerById('steep').label} (over \${blockLimit()}°)`);
  for (const l of L.LAYERS) {
    assert.doesNotMatch(`${l.label} | ${l.title ?? ''}`, /\bE\d{1,2}\b|BoulderNet|distilled|src\//,
                        `${l.id}: a project code or an engine name on screen`);
  }
});

test('the copied legend strings are still in web/index.html', () => {
  // Map legend (renderLegend).
  inHud('fill("rgba(42,120,214,0.75)", "Habitat antenna in sight")');
  inHud('fill("linear-gradient(90deg,#1a9850 0%,#fee08b 33.3%,#f46d43 66.7%,#a50026 100%)", currentTab === "walk" ? "Slope (faded here)" : "Slope, 0° to 45°")');
  inHud('<i class="hatch"></i>Too steep to cross (over ${blockLimit()}°)');
  inHud('fill("rgb(250,246,235)", "Sand detected")');
  inHud('<i class="rock"></i>Boulders (bigger dot, more cover)');
  inHud('fill("linear-gradient(90deg,#000004,#8c2981,#fe9f6d,#fcfdbf)", "Walking cost, low to high")');
  // Sidebar legends and their CSS.
  inHud('<span class="swatch" style="background: rgba(42,120,214,0.7)"></span>the habitat antenna is in sight');
  inHud('<span id="radio-note">Line of sight on the 1 m terrain model (cautious).</span>');
  inHud('background: linear-gradient(90deg, #1a9850 0%, #fee08b 33.3%, #f46d43 66.7%, #a50026 100%);');
  inHud('<span>0°</span><span>15°</span><span>30°</span><span>45°+</span>');
  inHud(`--hatch: ${L.layerById('steep').legend.css};`);
  inHud('.lg i.hatch { height: 10px; border: 1px solid rgba(255,255,255,.25);');
  inHud('Never cross cells steeper than <b id="block-value">30</b>°');
  inHud('background: linear-gradient(90deg, rgba(250,246,235,0), rgb(250,246,235))');
  inHud('<span>0</span><span>sand fraction per 1 m cell</span><span>1</span>');
  inHud(L.layerById('sand').legend.caption);
  inHud('.legend.cost { background: linear-gradient(90deg, #000004, #3b0f70, #8c2981, #de4968, #fe9f6d, #fcfdbf); }');
  inHud('<span id="cost-min"></span><span>Wh per 1 m cell</span><span id="cost-max"></span>');
  inHud('background: rgb(232, 236, 255); border: 1px solid #0a0c10;');
  inHud('<i style="width:4px;height:4px"></i><i style="width:7px;height:7px"></i><i style="width:10px;height:10px"></i>');
  inHud(`<span>${L.layerById('rocks').legend.caption}</span>`);
  inHud(`<span id="rocks-note">${L.layerById('rocks').legend.note}</span>`);
});

test('sliderToOpacity is the 2D mapping, value ** 2.2, kept inside 0..1', () => {
  assert.equal(L.sliderToOpacity(1), 1);
  assert.equal(L.sliderToOpacity(0), 0);
  assert.equal(L.sliderToOpacity(0.5), Math.pow(0.5, 2.2));
  assert.equal(L.sliderToOpacity(0.75), Math.pow(0.75, 2.2));
  assert.equal(L.sliderToOpacity('0.75'), Math.pow(0.75, 2.2));
  assert.equal(L.sliderToOpacity(2), 1);
  assert.equal(L.sliderToOpacity(-1), 0);
  assert.equal(L.sliderToOpacity(NaN), 0);
  assert.equal(L.sliderToOpacity(undefined), 0);
});

test('planHabitat: the plan habitat, else the start point, else the box centre; bad values skipped', () => {
  assert.deepEqual(L.planHabitat(PLAN_E4, BBOX), [8143537.492786024, -284463.075189438]);
  const start = {kind: 'start', x: 8143000.25, y: -284000.75, properties: {}};
  assert.deepEqual(L.planHabitat({properties: {}, points: [start]}, BBOX), [8143000.25, -284000.75]);
  assert.deepEqual(L.planHabitat({properties: {habitat: [8143100, -284100]}, points: [start]}, BBOX), [8143100, -284100]);
  // A habitat that is not two finite numbers falls to the start point; a bad start to the centre.
  for (const habitat of [[NaN, -284100], [8143100], '8143100,-284100', null, [8143100, Infinity]]) {
    assert.deepEqual(L.planHabitat({properties: {habitat}, points: [start]}, BBOX), [8143000.25, -284000.75], String(habitat));
  }
  const badStart = {kind: 'start', x: Infinity, y: -284000, properties: {}};
  assert.deepEqual(L.planHabitat({properties: {habitat: [NaN, 0]}, points: [badStart]}, BBOX), CENTRE);
  assert.deepEqual(L.planHabitat({properties: {}, points: [{kind: 'goal', x: 1, y: 2}]}, BBOX), CENTRE);
  assert.deepEqual(L.planHabitat(null, BBOX), CENTRE);
  assert.deepEqual(L.planHabitat(undefined, BBOX), CENTRE);
  // The HUD's chain, for reference: plan habitat, base the user set, box centre.
  inHud('const radioHabitat = () => (planFC && planFC.properties.habitat) || baseXY ||\n  [X0 + SIZE_M / 2, Y0 - SIZE_M / 2];');
});

test('planSlopeLimit: the plan value; null blocks nothing; absent or no plan is the default 30', () => {
  assert.equal(DEFAULT_LIMITS.max_cell_slope_deg, 30);
  assert.equal(L.planSlopeLimit(PLAN_E4), 30);
  assert.equal(L.planSlopeLimit({properties: {}}), 30);
  assert.equal(L.planSlopeLimit({properties: {max_cell_slope_deg: null}}), null);
  assert.equal(L.planSlopeLimit({properties: {max_cell_slope_deg: 25}}), 25);
  assert.equal(L.planSlopeLimit({properties: {max_cell_slope_deg: 27.5}}), 27.5);
  assert.equal(L.planSlopeLimit({properties: {max_cell_slope_deg: 'steep'}}), 30);
  assert.equal(L.planSlopeLimit({}), 30);
  assert.equal(L.planSlopeLimit(null), 30);
});

test('layerRequest builds the URLs as the HUD does', () => {
  const h = [8143537.492786024, -284463.075189438];
  assert.deepEqual(L.layerRequest('radio', {habitat: h}),
    {tiles: false, image: '/layers/comms.png?x=8143537.5&y=-284463.1', info: '/layers/comms?x=8143537.5&y=-284463.1', reason: null});
  inHud('image: `/layers/comms.png?x=${h[0].toFixed(1)}&y=${h[1].toFixed(1)}`');
  inHud('fetch(`/layers/comms?x=${h[0].toFixed(1)}&y=${h[1].toFixed(1)}`)');
  assert.equal(L.layerRequest('radio', {habitat: [8143000, -284000.04]}).image, '/layers/comms.png?x=8143000.0&y=-284000.0');
  assert.equal(L.layerRequest('radio', {}).image, null);
  assert.match(L.layerRequest('radio', {habitat: [NaN, 1]}).reason, /habitat/);

  assert.deepEqual(L.layerRequest('steep', {limit: 25}), {tiles: false, image: '/layers/blocked.png?max_cell_slope_deg=25',
    info: '/layers/blocked?max_cell_slope_deg=25', reason: null});
  assert.equal(L.layerRequest('steep', {limit: 27.5}).image, '/layers/blocked.png?max_cell_slope_deg=27.5');
  assert.equal(L.layerRequest('steep', {}).image, '/layers/blocked.png?max_cell_slope_deg=30');
  assert.equal(L.layerRequest('steep').info, '/layers/blocked?max_cell_slope_deg=30');
  assert.deepEqual(L.layerRequest('steep', {limit: null}),
    {tiles: false, image: null, info: null, reason: 'The plan does not block steep cells.'});
  assert.equal(L.layerRequest('steep', {limit: NaN}).image, null);
  inHud('image: `/layers/blocked.png?max_cell_slope_deg=${limit}`');
  inHud('fetch(`/layers/blocked?max_cell_slope_deg=${limit}`)');

  assert.deepEqual(L.layerRequest('slope'), {tiles: true, image: null, info: null, reason: null});
  assert.deepEqual(L.layerRequest('sand'), {tiles: false, image: '/layers/sand.png', info: '/layers/sand', reason: null});
  assert.deepEqual(L.layerRequest('cost'), {tiles: false, image: '/layers/cost.png', info: '/layers/cost', reason: null});
  assert.deepEqual(L.layerRequest('rocks'), {tiles: false, image: '/layers/rocks.png', info: '/layers/rocks', reason: null});
  for (const url of ['"/layers/sand.png"', '"/layers/cost.png"', '"/layers/rocks.png"', 'fetch("/layers/cost")', 'fetch("/layers/rocks")']) inHud(url);
  assert.equal(L.layerRequest('thermal'), null);
});

test('legendNote: one line from the info JSON, in the HUD words', () => {
  assert.equal(L.legendNote('radio', {coverage: 0.4321, habitat: [0, 0], habitat_source: 'request'}),
    'The antenna sees 43.2 % of the box. Pure line of sight on the 1 m DEM (conservative).');
  inHud('`The antenna sees ${((await res.json()).coverage * 100).toFixed(1)} % of the box. Pure line of sight on the 1 m DEM (conservative).`');
  assert.equal(L.legendNote('steep', {max_cell_slope_deg: 30, blocked_fraction: 0.0734}, {limit: 30}),
    '7.3 % of the box is off limits (cells steeper than 30°).');
  assert.equal(L.legendNote('steep', {max_cell_slope_deg: 25, blocked_fraction: 0.2}), '20.0 % of the box is off limits (cells steeper than 25°).');
  inHud('`${(r.blocked_fraction * 100).toFixed(1)} % of the area is off limits`');
  assert.equal(L.legendNote('sand', {share_of_box_with_sand_pct: 12.345, source: 'E8', note: 'conservative'}),
    'Sand detected on 12.3 % of the box (cells more than half sand).');
  assert.equal(L.legendNote('cost', {units: 'Wh per cell (1 m)', vmin: 0.0123456, vmax: 0.0456789}),
    'Walking cost from 0.012 to 0.046+ Wh per cell (1 m).');
  assert.equal(L.legendNote('rocks', {mean_cover_pct: 1.2345, share_of_squares_over_5pct_pct: 4.56}),
    'Boulders cover 1.23 % of the area; 4.6 % of the 10 m squares are over 5 % boulders. ' +
    'Only boulders larger than about 1 m are seen. Shown for context: the route cost does not use them.');
  inHud('`Boulders cover ${r.mean_cover_pct.toFixed(2)} % of the area; ` +');
  inHud('`${r.share_of_squares_over_5pct_pct.toFixed(1)} % of the 10 m squares are over 5 % boulders. ` +');
  inHud('"Only boulders larger than about 1 m are seen. Shown for context: the route cost does not use them."');
  // An error answer reads as in the HUD; no info or missing numbers give ''.
  assert.equal(L.legendNote('sand', {detail: 'data/e8/sand.tif missing (release e8-v0)'}),
    'Unavailable: data/e8/sand.tif missing (release e8-v0)');
  inHud('`Unavailable: ${(await res.json()).detail}`');
  for (const id of ['radio', 'slope', 'steep', 'sand', 'cost', 'rocks']) {
    assert.equal(L.legendNote(id, null), '', id);
    assert.equal(L.legendNote(id, {}), '', id);
  }
  assert.equal(L.legendNote('radio', {coverage: null}), '');
});

test('legendTicks and legendView fill in the limit, the cost range and the note', () => {
  const info = {units: 'Wh per cell (1 m)', vmin: 0.0123456, vmax: 0.0456789};
  assert.deepEqual(L.legendTicks('cost', info), ['0.012', 'Wh per 1 m cell', '0.046+']);
  inHud('ui("cost-min").textContent = L.vmin.toFixed(3);');
  inHud('ui("cost-max").textContent = L.vmax.toFixed(3) + "+";');
  assert.deepEqual(L.legendTicks('cost', null), ['', 'Wh per 1 m cell', '']);
  assert.deepEqual(L.legendTicks('slope'), ['0°', '15°', '30°', '45°+']);
  assert.deepEqual(L.legendTicks('nope'), []);

  const steep = L.legendView('steep', {limit: 25, info: {blocked_fraction: 0.1, max_cell_slope_deg: 25}});
  assert.equal(steep.text, 'Too steep to cross (over 25°)');
  assert.equal(steep.caption, 'Never cross cells steeper than 25°');
  assert.equal(steep.note, '10.0 % of the box is off limits (cells steeper than 25°).');
  assert.equal(L.legendView('steep').text, 'Too steep to cross (over 30°)');
  const off = L.legendView('steep', {limit: null});
  assert.equal(off.text, '');
  assert.equal(off.note, 'The plan does not block steep cells.');
  assert.deepEqual(L.legendView('cost', {info}).ticks, ['0.012', 'Wh per 1 m cell', '0.046+']);
  assert.equal(L.legendView('rocks').note, 'Boulders larger than about 1 m. Shown for context: the route cost does not use them.');
  assert.equal(L.legendView('radio', {info: {coverage: 0.5}}).note,
    'The antenna sees 50.0 % of the box. Pure line of sight on the 1 m DEM (conservative).');
  assert.equal(L.legendView('nope'), null);
  // The descriptors are not changed by filling them in.
  assert.equal(L.layerById('steep').legend.text, 'Too steep to cross (over {limit}°)');
});

test('slopeTileGrid: the 64 tiles of zoom 3 over the box, on a 2000 px canvas', () => {
  const g = L.slopeTileGrid(META, BBOX);
  assert.equal(g.z, 3);
  assert.equal(g.mpp, 1);
  assert.equal(g.tileSize, 256);
  assert.equal(g.width, 2000);
  assert.equal(g.height, 2000);
  assert.equal(g.tiles.length, 64);
  for (const t of g.tiles) {
    assert.equal(t.px, t.x * 256);
    assert.equal(t.py, t.y * 256);
    assert.equal(t.url, `/tiles/slope/3/${t.x}/${t.y}.png`);
  }
  assert.ok(g.tiles.some(t => t.url === '/tiles/slope/3/7/7.png'));
  assert.deepEqual(g.tiles[0], {url: '/tiles/slope/3/0/0.png', x: 0, y: 0, px: 0, py: 0});
  assert.equal(L.maxZoom('0-3'), 3);
  assert.equal(L.maxZoom('5'), 5);
  assert.equal(L.maxZoom(2), 2);
  assert.equal(L.maxZoom('x'), null);
  assert.equal(L.slopeTileGrid({...META, layers: {}}, BBOX), null);
  inHud('tileLayer("slope", "/" + L.slope.url, 3,');
});

test('slopeTileGrid uses the tile origin, not the box: a shifted box moves the offsets', () => {
  // 256 m east: column 0 no longer overlaps, and no column 8 exists (2**3 tiles across).
  const east = L.slopeTileGrid(META, shifted(256));
  assert.equal(east.width, 2000);
  assert.equal(east.tiles.length, 56);
  assert.deepEqual([...new Set(east.tiles.map(t => t.x))], [1, 2, 3, 4, 5, 6, 7]);
  for (const t of east.tiles) {
    assert.equal(t.px, (t.x - 1) * 256);
    assert.equal(t.py, t.y * 256);
    assert.equal(t.px % 256, 0);
  }
  // 128 m east: still 8 columns, cut in half at the west edge.
  const half = L.slopeTileGrid(META, shifted(128));
  assert.equal(half.tiles.length, 64);
  assert.deepEqual(half.tiles.filter(t => t.y === 0).map(t => t.px), [-128, 128, 384, 640, 896, 1152, 1408, 1664]);
  // 256 m north: row 0 starts 256 px down the canvas, the bottom row 7 leaves the box.
  const north = L.slopeTileGrid(META, shifted(0, 256));
  assert.deepEqual([...new Set(north.tiles.map(t => t.y))], [0, 1, 2, 3, 4, 5, 6]);
  assert.deepEqual(north.tiles.filter(t => t.x === 0).map(t => t.py), [256, 512, 768, 1024, 1280, 1536, 1792]);
  // A 300 m box inside: 3 x 3 tiles.
  const small = L.slopeTileGrid(META, {xmin: BBOX.xmin + 500, xmax: BBOX.xmin + 800, ymax: BBOX.ymax - 500, ymin: BBOX.ymax - 800});
  assert.equal(small.width, 300);
  assert.equal(small.tiles.length, 9);
  assert.deepEqual(small.tiles[0], {url: '/tiles/slope/3/1/1.png', x: 1, y: 1, px: -244, py: -244});
});

test('flipRows reverses the rows and leaves the input alone', () => {
  const src = image(2, 3, (i, j) => [i, j, 10 * i + j, 255]);
  const flipped = L.flipRows(src, 2, 3);
  assert.notEqual(flipped, src);
  assert.deepEqual([...flipped.subarray(0, 8)], [2, 0, 20, 255, 2, 1, 21, 255]);
  assert.deepEqual([...flipped.subarray(16, 24)], [0, 0, 0, 255, 0, 1, 1, 255]);
  assert.deepEqual(L.flipRows(flipped, 2, 3), src);
  assert.equal(src[0], 0);
});

test('compareRGBA: identical images match, tolerance per channel, transparent RGB ignored', () => {
  const rnd = noise(7), a = image(8, 8, () => [rnd(), rnd(), rnd(), 255]);
  assert.deepEqual(L.compareRGBA(a, a.slice(), 8, 8), {cells: 64, match_pct: 100, mean_abs_err: 0, max_abs_err: 0});
  // Two transparent cells match whatever their RGB; one barely visible does not.
  const t1 = image(1, 1, () => [255, 0, 0, 0]), t2 = image(1, 1, () => [0, 255, 9, 2]), t3 = image(1, 1, () => [0, 255, 9, 5]);
  assert.deepEqual(L.compareRGBA(t1, t2, 1, 1), {cells: 1, match_pct: 100, mean_abs_err: 0, max_abs_err: 0});
  assert.deepEqual(L.compareRGBA(t1, t3, 1, 1), {cells: 1, match_pct: 0, mean_abs_err: 255, max_abs_err: 255});
  assert.equal(L.compareRGBA(t1, t2, 1, 1, {tol: 1}).match_pct, 0);
  // tol: within 2 matches, 3 does not; the error of a cell is its largest channel difference.
  const b = image(2, 1, () => [100, 100, 100, 255]), c = image(2, 1, (i, j) => (j === 0 ? [102, 99, 100, 255] : [100, 103, 100, 255]));
  assert.deepEqual(L.compareRGBA(b, c, 2, 1), {cells: 2, match_pct: 50, mean_abs_err: 2.5, max_abs_err: 3});
  assert.equal(L.compareRGBA(b, c, 2, 1, {tol: 3}).match_pct, 100);
  // A shift drops what it pushes out; a region and a step pick cells.
  assert.equal(L.compareRGBA(a, a, 4, 4, {dx: 2, dy: -1}).cells, 6);
  assert.equal(L.compareRGBA(a, a, 8, 8, {step: 2}).cells, 16);
  assert.equal(L.compareRGBA(a, a, 8, 8, {region: {i0: 1, j0: 2, i1: 4, j1: 7}}).cells, 15);
  assert.equal(L.compareRGBA(a, a, 8, 8, {region: {i0: 4, j0: 4, i1: 4, j1: 8}}).match_pct, null);
});

test('bestShift finds a known shift, and (0, 0) on identical images', () => {
  const w = 40, h = 32, rnd = noise(42), expected = image(w, h, () => [rnd(), rnd(), rnd(), 255]);
  // actual(i + dy, j + dx) = expected(i, j), with dx = 2 and dy = -1; the cells nothing lands on are noise.
  const dx = 2, dy = -1, other = noise(3);
  const actual = image(w, h, (i, j) => {
    const si = i - dy, sj = j - dx;
    return si >= 0 && si < h && sj >= 0 && sj < w ? [...expected.subarray((si * w + sj) * 4, (si * w + sj) * 4 + 4)]
      : [other(), other(), other(), 255];
  });
  const found = L.bestShift(expected, actual, w, h);
  assert.equal(found.dx, 2);
  assert.equal(found.dy, -1);
  assert.equal(found.err, 0);
  assert.ok(found.err_at_zero > 30, `error at zero ${found.err_at_zero}`);
  assert.equal(found.errs.length, 49);
  assert.equal(L.compareRGBA(expected, actual, w, h, {dx: 2, dy: -1}).match_pct, 100);
  // Same with every cell, and with a region of its own.
  assert.deepEqual([L.bestShift(expected, actual, w, h, {step: 1}).dx, L.bestShift(expected, actual, w, h, {step: 1}).dy], [2, -1]);
  const r = L.bestShift(expected, actual, w, h, {max: 2, region: {i0: 5, j0: 5, i1: 25, j1: 30}});
  assert.deepEqual([r.dx, r.dy, r.errs.length], [2, -1, 25]);
  // Identical images: no shift, even where a flat image ties every shift.
  const same = L.bestShift(expected, expected.slice(), w, h);
  assert.deepEqual([same.dx, same.dy, same.err, same.err_at_zero], [0, 0, 0, 0]);
  const flat = image(w, h, () => [9, 9, 9, 255]);
  assert.deepEqual([L.bestShift(flat, flat, w, h).dx, L.bestShift(flat, flat, w, h).dy], [0, 0]);
});

test('coverage is the share of cells with alpha above 0', () => {
  const img = image(4, 2, (i, j) => [0, 0, 0, i === 0 && j < 2 ? 1 : 0]);
  assert.equal(L.coverage(img, 4, 2), 0.25);
  assert.equal(L.coverage(img, 4, 2, {region: {i0: 0, j0: 0, i1: 1, j1: 2}}), 1);
  assert.equal(L.coverage(img, 4, 2, {step: 2}), 0.5);          // cells (0, 0) and (0, 2) only
  assert.equal(L.coverage(img, 4, 2, {region: {i0: 1, j0: 0, i1: 1, j1: 4}}), null);
});

test('the slope tile ramp is the one of src/gis/tiles.py; the HUD legend ramp is its CSS', () => {
  const line = /SLOPE_RAMP = "nv 0 0 0 0\\n(.*)\\n"/.exec(TILES_PY);
  assert.ok(line, 'SLOPE_RAMP not found in src/gis/tiles.py');
  const stops = line[1].split('\\n').map(s => s.split(' ').map(Number)).map(([deg, r, g, b]) => ({deg, rgb: [r, g, b]}));
  assert.deepEqual(L.SLOPE_TILE_RAMP, stops);
  const hex = ramp => ramp.map(s => '#' + s.rgb.map(v => v.toString(16).padStart(2, '0')).join(''));
  assert.deepEqual(hex(L.SLOPE_LEGEND_RAMP), ['#1a9850', '#fee08b', '#f46d43', '#a50026']);
  assert.deepEqual(L.SLOPE_LEGEND_RAMP, L.SLOPE_TILE_RAMP.slice(0, 4));   // since #149: legend = tiles, 0-45°
  assert.deepEqual(L.SLOPE_LEGEND_RAMP.map(s => s.deg), [0, 15, 30, 45]);
});

test('slopeFromColor reads the angle back from a ramp colour', () => {
  for (const ramp of [L.SLOPE_TILE_RAMP, L.SLOPE_LEGEND_RAMP]) {
    for (const s of ramp) assert.equal(L.slopeFromColor(...s.rgb, ramp), s.deg);
  }
  // The four stops of the spec, on the HUD legend colours.
  assert.equal(L.slopeFromColor(0x1a, 0x98, 0x50, L.SLOPE_LEGEND_RAMP), 0);
  assert.equal(L.slopeFromColor(0xfe, 0xe0, 0x8b, L.SLOPE_LEGEND_RAMP), 15);
  assert.equal(L.slopeFromColor(0xf4, 0x6d, 0x43, L.SLOPE_LEGEND_RAMP), 30);
  assert.equal(L.slopeFromColor(0xa5, 0x00, 0x26, L.SLOPE_LEGEND_RAMP), 45);
  // Midpoints: halfway between 15 and 30 on the legend, between 0 and 15 on the tiles (the default).
  close(L.slopeFromColor(249, 166.5, 103, L.SLOPE_LEGEND_RAMP), 22.5, 1e-9, 'legend 15-30');
  close(L.slopeFromColor(140, 188, 109.5), 7.5, 1e-9, 'tiles 0-15');
  // Off the ramp it clamps to the nearest end; 8-bit colours of the tiles read back within half a degree to 45°.
  assert.equal(L.slopeFromColor(0, 255, 0), 0);
  for (let deg = 0; deg <= 90; deg += 0.5) close(L.slopeFromColor(...rampColor(deg)), deg, deg <= 45 ? 0.5 : 1, `${deg}°`);
});

test('masks: alpha, steeper than a limit, and their agreement', () => {
  const at = deg => [...rampColor(deg), 255];
  const slope = image(4, 1, (i, j) => [at(10), at(35), [0, 0, 0, 0], at(29)][j]);
  assert.deepEqual([...L.slopeMask(slope, 4, 1, 30)], [0, 1, 1, 0]);
  assert.deepEqual([...L.slopeMask(slope, 4, 1, 30, {transparentIsSteep: false})], [0, 1, 0, 0]);
  const blocked = image(4, 1, (i, j) => [14, 16, 20, [0, 190, 95, 190][j]]);
  assert.deepEqual([...L.alphaMask(blocked, 4, 1)], [0, 1, 1, 1]);
  assert.deepEqual(L.maskAgreement(L.slopeMask(slope, 4, 1, 30), L.alphaMask(blocked, 4, 1)),
    {cells: 4, agree_pct: 75, only_a: 0, only_b: 1, both: 2});
  assert.deepEqual(L.maskAgreement([1, 0, 1, 0], [true, false, false, true]),
    {cells: 4, agree_pct: 50, only_a: 1, only_b: 1, both: 1});
  assert.deepEqual(L.maskAgreement([], []), {cells: 0, agree_pct: null, only_a: 0, only_b: 0, both: 0});
  assert.throws(() => L.maskAgreement([1], [1, 0]), /length/);
});

test('premultiply puts the colours over black, as a 2D canvas keeps them, and leaves the input alone', () => {
  const src = Uint8Array.from([255, 128, 0, 128, 42, 120, 214, 110, 9, 9, 9, 0, 10, 20, 30, 255]);
  const copy = src.slice();
  assert.deepEqual([...L.premultiply(src)], [128, 64, 0, 128, 18, 52, 92, 110, 0, 0, 0, 0, 10, 20, 30, 255]);
  assert.deepEqual(src, copy);
  // Two straight colours that a canvas cannot tell apart at alpha 3 are the same over black.
  assert.deepEqual([...L.premultiply([200, 100, 50, 3])], [...L.premultiply([170, 85, 51, 3])]);
  assert.ok(L.premultiply(new Uint8ClampedArray(8)) instanceof Uint8Array);
});
