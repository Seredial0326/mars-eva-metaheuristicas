// Map layers of the 3D map (issue #110): the numbers behind the 2D layers draped on the
// terrain, with no dependencies but api.js (tested with `node --test`).
//
// The 2D HUD (web/index.html) is the reference: the same images, the same URLs, the same
// legend colours and words, the same opacity slider. Six layers:
//   radio  /layers/comms.png?x=&y=         E11 line of sight from the habitat antenna
//   slope  the XYZ slope tiles of /layers  (not a /layers PNG, as in the 2D)
//   steep  /layers/blocked.png?max_cell_slope_deg=L, the plan's own limit
//   sand   /layers/sand.png                E8
//   cost   /layers/cost.png                E3
//   rocks  /layers/rocks.png               E9
// Every /layers PNG is one 2000 x 2000 image of the box: row 0 north, 1 px = 1 m cell,
// straight alpha. Legend data is plain text and CSS strings, never HTML.
//
// The check helpers at the end compare RGBA images of the box (row 0 north): what the
// 3D drew against what the API serves, so a layer that slid or stretched is noticed.
import { DEFAULT_LIMITS } from './api.js';

// Slope legend of the HUD (CSS .legend, web/index.html): the colours the 2D legend shows.
// Since #149 they are the tiles' own colours from 0 to 45° (SLOPE_RAMP below).
export const SLOPE_LEGEND_RAMP = [
  {deg: 0, rgb: [26, 152, 80]}, {deg: 15, rgb: [254, 224, 139]},
  {deg: 30, rgb: [244, 109, 67]}, {deg: 45, rgb: [165, 0, 38]},
];
// Colours actually in the slope tiles: SLOPE_RAMP of src/gis/tiles.py (gdaldem
// color-relief, linear between stops), up to 90°; decode tiles with this one.
export const SLOPE_TILE_RAMP = [
  {deg: 0, rgb: [26, 152, 80]}, {deg: 15, rgb: [254, 224, 139]}, {deg: 30, rgb: [244, 109, 67]},
  {deg: 45, rgb: [165, 0, 38]}, {deg: 90, rgb: [80, 0, 20]},
];

const HATCH = 'repeating-linear-gradient(45deg, rgba(14,16,20,.95) 0 3px, rgba(14,16,20,.45) 3px 6px)';
const STEEP_OFF = 'The plan does not block steep cells.';
const finite = v => typeof v === 'number' && Number.isFinite(v);
const isXY = c => Array.isArray(c) && finite(c[0]) && finite(c[1]);

// Legend of a layer, as the HUD draws it:
//   kind     'fill' | 'gradient' | 'hatch' | 'dots'
//   css      background of the swatch in the map legend (renderLegend)
//   sidebar  background of the bar or swatch in the sidebar, or null
//   border   CSS border of the swatch, or null
//   dots     dot sizes in px of the boulder key (rocks only)
//   text     line of the map legend ('{limit}' is the steep-cell limit)
//   caption  words of the sidebar next to the swatch or under the bar, or null
//   ticks    the row under the bar, left to right, as the HUD lays it out ([] when none)
//   unit     unit of the bar, or null
//   note     the sidebar note shown before the info JSON arrives, or null
const legend = fields => ({kind: 'fill', css: null, sidebar: null, border: null, text: '', caption: null,
                           ticks: [], unit: null, note: null, ...fields});

// Layer descriptors in drawing order. slider: the default value of the opacity slider
// (0..1, mapped with sliderToOpacity). Radio, steep, sand and rocks carry their alpha in
// the PNG and the 2D draws them at opacity 1; cost is 0.75 and slope 0.5 as in the 2D.
// label: the name of the HUD's checkbox (the steep one: its map legend). title: the HUD's
// hover text of that checkbox, or null. Both in plain words: the HUD's hover texts start
// with the project code (E11 radio, E8 sand, E3 cost, E9 boulders) and the boulders one
// names the network; the 3D leaves those out (#124).
export const LAYERS = [
  {id: 'radio', label: 'Radio coverage', source: 'png', slider: 1,
   title: 'Line of sight from the habitat antenna to a suit radio',
   legend: legend({kind: 'fill', css: 'rgba(42,120,214,0.75)', sidebar: 'rgba(42,120,214,0.7)',
                   text: 'Habitat antenna in sight', caption: 'the habitat antenna is in sight',
                   note: 'Line of sight on the 1 m terrain model (cautious).'})},
  {id: 'slope', label: 'Slope', source: 'tiles', slider: 0.5, title: null,
   legend: legend({kind: 'gradient', css: 'linear-gradient(90deg,#1a9850 0%,#fee08b 33.3%,#f46d43 66.7%,#a50026 100%)',
                   sidebar: 'linear-gradient(90deg, #1a9850 0%, #fee08b 33.3%, #f46d43 66.7%, #a50026 100%)',
                   text: 'Slope, 0° to 45°', ticks: ['0°', '15°', '30°', '45°+'], unit: '°'})},
  {id: 'steep', label: 'Too steep to cross', source: 'png', slider: 1, title: null,
   legend: legend({kind: 'hatch', css: HATCH, sidebar: HATCH, border: '1px solid rgba(255,255,255,.25)',
                   text: 'Too steep to cross (over {limit}°)', caption: 'Never cross cells steeper than {limit}°',
                   unit: '°'})},
  {id: 'sand', label: 'Sand detected', source: 'png', slider: 1,
   title: 'Sand detected on the orbital photo by a neural network',
   legend: legend({kind: 'gradient', css: 'rgb(250,246,235)',
                   sidebar: 'linear-gradient(90deg, rgba(250,246,235,0), rgb(250,246,235))',
                   text: 'Sand detected', ticks: ['0', 'sand fraction per 1 m cell', '1'],
                   unit: 'sand fraction per 1 m cell',
                   caption: 'A cautious detector: when it marks sand it is right about 92 % of the time, ' +
                            'but it misses a lot of sand.'})},
  {id: 'cost', label: 'Walking cost', source: 'png', slider: 0.75,
   title: 'Energy to cross each 1 m cell (Santee 2001, Mars gravity)',
   legend: legend({kind: 'gradient', css: 'linear-gradient(90deg,#000004,#8c2981,#fe9f6d,#fcfdbf)',
                   sidebar: 'linear-gradient(90deg, #000004, #3b0f70, #8c2981, #de4968, #fe9f6d, #fcfdbf)',
                   text: 'Walking cost, low to high', ticks: ['', 'Wh per 1 m cell', ''],
                   unit: 'Wh per 1 m cell'})},
  {id: 'rocks', label: 'Boulders', source: 'png', slider: 1,
   title: 'Boulders found on the orbital photo by a neural network',
   legend: legend({kind: 'dots', css: 'rgb(232, 236, 255)', border: '1px solid #0a0c10', dots: [4, 7, 10],
                   text: 'Boulders (bigger dot, more cover)',
                   caption: 'bigger dot, more of the 10 m square under boulders (largest: 10 % or more)',
                   note: 'Boulders larger than about 1 m. Shown for context: the route cost does not use them.'})},
];

export const layerById = id => LAYERS.find(l => l.id === id) || null;

// Opacity slider (0..1) -> layer opacity, as the 2D does it (value ** 2.2, so the slider
// reads linearly once the renderer's gamma is applied).
export function sliderToOpacity(v) {
  const x = Number(v);
  return Number.isFinite(x) ? Math.min(1, Math.max(0, x)) ** 2.2 : 0;
}

// Where the radio antenna stands: the plan's habitat, else its start point, else the box
// centre (the 2D uses the plan's habitat, else the base the user set, else the centre).
export function planHabitat(model, bbox) {
  const habitat = model && model.properties && model.properties.habitat;
  if (isXY(habitat)) return [habitat[0], habitat[1]];
  const start = model && Array.isArray(model.points)
    ? model.points.find(p => p && p.kind === 'start' && finite(p.x) && finite(p.y)) : null;
  if (start) return [start.x, start.y];
  return [(bbox.xmin + bbox.xmax) / 2, (bbox.ymin + bbox.ymax) / 2];
}

// Steepest cell the plan allows (degrees), or null when the plan blocks none (the key is
// there and null). Without a plan, or without the key, the planner's default (30).
export function planSlopeLimit(model) {
  const p = model && model.properties;
  if (p && Object.prototype.hasOwnProperty.call(p, 'max_cell_slope_deg')) {
    if (p.max_cell_slope_deg === null) return null;
    if (finite(p.max_cell_slope_deg)) return p.max_cell_slope_deg;
  }
  return DEFAULT_LIMITS.max_cell_slope_deg;
}

// What to load for a layer: {tiles, image, info, reason}. image and info are same-origin
// URLs built as the HUD builds them (the image and its info JSON); tiles is true for the
// slope (use slopeTileGrid); reason says why there is nothing to load. null for an
// unknown id. limit undefined means the default limit; null means no blocked cells.
export function layerRequest(id, {habitat, limit} = {}) {
  const png = (image, info) => ({tiles: false, image, info, reason: null});
  const none = reason => ({tiles: false, image: null, info: null, reason});
  switch (id) {
    case 'radio': {
      if (!isXY(habitat)) return none('No habitat position for the antenna.');
      const q = `x=${habitat[0].toFixed(1)}&y=${habitat[1].toFixed(1)}`;
      return png(`/layers/comms.png?${q}`, `/layers/comms?${q}`);
    }
    case 'slope': return {tiles: true, image: null, info: null, reason: null};
    case 'steep': {
      const L = limit === undefined ? DEFAULT_LIMITS.max_cell_slope_deg : limit;
      if (L === null) return none(STEEP_OFF);
      if (!finite(L)) return none('The steep-cell limit is not a number.');
      return png(`/layers/blocked.png?max_cell_slope_deg=${L}`, `/layers/blocked?max_cell_slope_deg=${L}`);
    }
    case 'sand': return png('/layers/sand.png', '/layers/sand');
    case 'cost': return png('/layers/cost.png', '/layers/cost');
    case 'rocks': return png('/layers/rocks.png', '/layers/rocks');
    default: return null;
  }
}

const fillLimit = (s, limit) => (s == null ? s : s.replace('{limit}', String(limit)));

// The one-line note under a legend, from the layer's info JSON, in the HUD's words.
// An error answer ({detail: "..."}) reads "Unavailable: ..." as in the HUD; '' when
// there is no info or it lacks the numbers.
export function legendNote(id, info, {limit} = {}) {
  if (!info || typeof info !== 'object') return '';
  if (typeof info.detail === 'string') return `Unavailable: ${info.detail}`;
  switch (id) {
    case 'radio':
      return finite(info.coverage)
        ? `The antenna sees ${(info.coverage * 100).toFixed(1)} % of the box. Pure line of sight on the 1 m DEM (conservative).`
        : '';
    case 'steep': {
      const L = finite(limit) ? limit : info.max_cell_slope_deg;
      if (!finite(info.blocked_fraction) || !finite(L)) return '';
      return `${(info.blocked_fraction * 100).toFixed(1)} % of the box is off limits (cells steeper than ${L}°).`;
    }
    case 'sand':
      return finite(info.share_of_box_with_sand_pct)
        ? `Sand detected on ${info.share_of_box_with_sand_pct.toFixed(1)} % of the box (cells more than half sand).`
        : '';
    case 'cost':
      return finite(info.vmin) && finite(info.vmax)
        ? `Walking cost from ${info.vmin.toFixed(3)} to ${info.vmax.toFixed(3)}+ ${info.units || 'Wh per 1 m cell'}.`
        : '';
    case 'rocks':
      return finite(info.mean_cover_pct) && finite(info.share_of_squares_over_5pct_pct)
        ? `Boulders cover ${info.mean_cover_pct.toFixed(2)} % of the area; ` +
          `${info.share_of_squares_over_5pct_pct.toFixed(1)} % of the 10 m squares are over 5 % boulders. ` +
          'Only boulders larger than about 1 m are seen. Shown for context: the route cost does not use them.'
        : '';
    default: return '';
  }
}

// The tick row of a layer's bar; the cost ends come from its info, as in the HUD
// (vmin.toFixed(3) and vmax.toFixed(3) + "+").
export function legendTicks(id, info) {
  const layer = layerById(id);
  if (!layer) return [];
  if (id === 'cost' && info && finite(info.vmin) && finite(info.vmax)) {
    return [info.vmin.toFixed(3), layer.legend.unit, info.vmax.toFixed(3) + '+'];
  }
  return [...layer.legend.ticks];
}

// Everything a renderer writes for one layer's legend, filled in: the legend fields with
// {limit} replaced, the ticks and the note (from the info JSON, else the static note).
// With limit null the steep layer has no swatch and its note says why.
export function legendView(id, {info = null, limit} = {}) {
  const layer = layerById(id);
  if (!layer) return null;
  const L = limit === undefined ? DEFAULT_LIMITS.max_cell_slope_deg : limit;
  if (id === 'steep' && L === null) return {...layer.legend, text: '', caption: null, note: STEEP_OFF};
  return {...layer.legend, text: fillLimit(layer.legend.text, L), caption: fillLimit(layer.legend.caption, L),
          ticks: legendTicks(id, info), note: legendNote(id, info, {limit: L}) || layer.legend.note};
}

// Highest zoom of a tile layer: "0-3" -> 3, "5" -> 5, 3 -> 3; null when unreadable.
export function maxZoom(zoom) {
  if (finite(zoom)) return zoom;
  const parts = String(zoom ?? '').split('-').map(s => Number(s.trim()));
  const z = parts[parts.length - 1];
  return Number.isInteger(z) && z >= 0 ? z : null;
}

export const TILE_PX = 256;
const snap = v => (Math.abs(v - Math.round(v)) < 1e-6 ? Math.round(v) : v);

// The slope tiles that cover the box at their highest zoom, placed on one canvas whose
// (0, 0) is the box's north-west corner: {z, mpp (metres per pixel), width, height,
// tileSize, tiles: [{url, x, y, px, py}]}, px and py being the canvas pixel of the tile's
// top-left corner (draw each tile tileSize x tileSize there). Only existing tiles (0 to
// 2**z - 1 each way) that overlap the box. null when the tiles meta lacks the slope layer.
export function slopeTileGrid(tilesMeta, bbox) {
  const layer = tilesMeta && tilesMeta.layers && tilesMeta.layers.slope;
  const z = layer ? maxZoom(layer.zoom) : null;
  const origin = tilesMeta && tilesMeta.origin_m;
  if (z === null || !origin || !finite(tilesMeta.tile_z0_m) || typeof layer.url !== 'string') return null;
  const s = tilesMeta.tile_z0_m / 2 ** z, mpp = s / TILE_PX, n = 2 ** z, eps = 1e-6;
  const range = (lo, hi) => [Math.max(0, Math.floor((lo + eps) / s)), Math.min(n - 1, Math.ceil((hi - eps) / s) - 1)];
  const [x0, x1] = range(bbox.xmin - origin.xmin, bbox.xmax - origin.xmin);
  const [y0, y1] = range(origin.ymax - bbox.ymax, origin.ymax - bbox.ymin);
  const template = '/' + layer.url.replace(/^\/+/, '');
  const tiles = [];
  for (let y = y0; y <= y1; y++) {
    for (let x = x0; x <= x1; x++) {
      tiles.push({url: template.replace('{z}', z).replace('{x}', x).replace('{y}', y), x, y,
                  px: snap((origin.xmin + x * s - bbox.xmin) / mpp), py: snap((bbox.ymax - (origin.ymax - y * s)) / mpp)});
    }
  }
  return {z, mpp, width: Math.round((bbox.xmax - bbox.xmin) / mpp), height: Math.round((bbox.ymax - bbox.ymin) / mpp),
          tileSize: TILE_PX, tiles};
}

// ---- Checks on RGBA images (Uint8 arrays, row 0 north, w x h, 4 bytes a cell) ----

// Rows reversed (WebGL readPixels gives the bottom row first). A new array.
export function flipRows(rgba, w, h) {
  const out = new rgba.constructor(rgba.length), row = w * 4;
  for (let i = 0; i < h; i++) out.set(rgba.subarray(i * row, (i + 1) * row), (h - 1 - i) * row);
  return out;
}

// The colours over black: [r a/255, g a/255, b a/255, a], rounded. A 2D canvas keeps its
// pixels this way (premultiplied), so the RGB it gives back for a faint pixel is rounded
// coarsely; compare two images in this space. A new Uint8Array.
export function premultiply(rgba) {
  const out = new Uint8Array(rgba.length);
  for (let k = 0; k < rgba.length; k += 4) {
    const a = rgba[k + 3];
    out[k] = Math.round(rgba[k] * a / 255);
    out[k + 1] = Math.round(rgba[k + 1] * a / 255);
    out[k + 2] = Math.round(rgba[k + 2] * a / 255);
    out[k + 3] = a;
  }
  return out;
}

// Half-open region {i0, j0, i1, j1} (i rows, j columns), clipped to the image.
function clip(region, w, h) {
  const r = region || {i0: 0, j0: 0, i1: h, j1: w};
  return {i0: Math.max(0, r.i0), j0: Math.max(0, r.j0), i1: Math.min(h, r.i1), j1: Math.min(w, r.j1)};
}

// Largest channel difference of two cells; 0 when both are transparent (alpha <= tol),
// whose RGB means nothing.
function cellError(a, ia, b, ib, tol) {
  if (a[ia + 3] <= tol && b[ib + 3] <= tol) return 0;
  return Math.max(Math.abs(a[ia] - b[ib]), Math.abs(a[ia + 1] - b[ib + 1]),
                  Math.abs(a[ia + 2] - b[ib + 2]), Math.abs(a[ia + 3] - b[ib + 3]));
}

// Cell (i, j) of `expected` against cell (i + dy, j + dx) of `actual`, every `step` cells
// of the region (default: the whole image less what the shift pushes out). A cell
// matches when every channel is within tol. Returns {cells, match_pct, mean_abs_err
// (mean of each cell's largest channel difference), max_abs_err}, unrounded; the
// numbers are null when no cell is compared.
export function compareRGBA(expected, actual, w, h, {tol = 2, step = 1, dx = 0, dy = 0, region} = {}) {
  const r = clip(region, w, h);
  const i0 = Math.max(r.i0, -dy), i1 = Math.min(r.i1, h - dy), j0 = Math.max(r.j0, -dx), j1 = Math.min(r.j1, w - dx);
  let cells = 0, matches = 0, sum = 0, max = 0;
  for (let i = i0; i < i1; i += step) {
    for (let j = j0; j < j1; j += step) {
      const e = cellError(expected, (i * w + j) * 4, actual, ((i + dy) * w + j + dx) * 4, tol);
      cells++; sum += e;
      if (e <= tol) matches++;
      if (e > max) max = e;
    }
  }
  if (cells === 0) return {cells, match_pct: null, mean_abs_err: null, max_abs_err: null};
  return {cells, match_pct: 100 * matches / cells, mean_abs_err: sum / cells, max_abs_err: max};
}

// The shift (dx, dy) in [-max, max]^2 of `actual` against `expected` with the smallest
// mean_abs_err (ties: the shorter shift). One region for every shift (default: the image
// less a border of `max`), so the errors compare. Returns {dx, dy, err, err_at_zero,
// errs: [{dx, dy, err}]}.
export function bestShift(expected, actual, w, h, {max = 3, step = 4, tol, region} = {}) {
  const r = clip(region || {i0: 0, j0: 0, i1: h, j1: w}, w, h);
  const fixed = {i0: Math.max(r.i0, max), j0: Math.max(r.j0, max), i1: Math.min(r.i1, h - max), j1: Math.min(r.j1, w - max)};
  const errs = [];
  let best = null;
  for (let dy = -max; dy <= max; dy++) {
    for (let dx = -max; dx <= max; dx++) {
      const err = compareRGBA(expected, actual, w, h, {tol, step, dx, dy, region: fixed}).mean_abs_err;
      errs.push({dx, dy, err});
      if (err !== null && (best === null || err < best.err ||
          (err === best.err && Math.hypot(dx, dy) < Math.hypot(best.dx, best.dy)))) best = {dx, dy, err};
    }
  }
  const zero = errs.find(e => e.dx === 0 && e.dy === 0);
  return {dx: best ? best.dx : 0, dy: best ? best.dy : 0, err: best ? best.err : null, err_at_zero: zero.err, errs};
}

// Share (0..1) of the sampled cells of the region with alpha > 0; null when none sampled.
export function coverage(rgba, w, h, {region, step = 1} = {}) {
  const r = clip(region, w, h);
  let cells = 0, seen = 0;
  for (let i = r.i0; i < r.i1; i += step) {
    for (let j = r.j0; j < r.j1; j += step) {
      cells++;
      if (rgba[(i * w + j) * 4 + 3] > 0) seen++;
    }
  }
  return cells ? seen / cells : null;
}

// Slope (degrees) of a colour: the angle of the nearest point of the piecewise-linear
// colour ramp (default: the ramp of the slope tiles, 0 to 90 degrees; SLOPE_LEGEND_RAMP
// for the HUD legend's colours, 0 to 45).
export function slopeFromColor(r, g, b, ramp = SLOPE_TILE_RAMP) {
  let best = Infinity, deg = ramp[0].deg;
  for (let k = 1; k < ramp.length; k++) {
    const p = ramp[k - 1].rgb, q = ramp[k].rgb, d = [q[0] - p[0], q[1] - p[1], q[2] - p[2]];
    const v = [r - p[0], g - p[1], b - p[2]];
    const t = Math.min(1, Math.max(0, (v[0] * d[0] + v[1] * d[1] + v[2] * d[2]) / (d[0] ** 2 + d[1] ** 2 + d[2] ** 2)));
    const dist = Math.hypot(v[0] - t * d[0], v[1] - t * d[1], v[2] - t * d[2]);
    if (dist < best) { best = dist; deg = ramp[k - 1].deg + t * (ramp[k].deg - ramp[k - 1].deg); }
  }
  return deg;
}

// 0/1 mask of the cells with alpha > 0 (e.g. the cells blocked.png draws).
export function alphaMask(rgba, w, h) {
  const out = new Uint8Array(w * h);
  for (let c = 0; c < w * h; c++) out[c] = rgba[c * 4 + 3] > 0 ? 1 : 0;
  return out;
}

// 0/1 mask of the cells of a slope image steeper than `limit`, decoded with `ramp`.
// Transparent cells (no slope) count as steep by default, as blocked.png counts them.
export function slopeMask(rgba, w, h, limit, {ramp = SLOPE_TILE_RAMP, transparentIsSteep = true} = {}) {
  const out = new Uint8Array(w * h);
  for (let c = 0; c < w * h; c++) {
    const k = c * 4;
    out[c] = rgba[k + 3] === 0 ? (transparentIsSteep ? 1 : 0)
                               : (slopeFromColor(rgba[k], rgba[k + 1], rgba[k + 2], ramp) > limit ? 1 : 0);
  }
  return out;
}

// Agreement of two masks of the same length (booleans or 0/1): {cells, agree_pct,
// only_a, only_b, both}.
export function maskAgreement(maskA, maskB) {
  if (maskA.length !== maskB.length) throw new Error(`masks differ in length (${maskA.length} vs ${maskB.length})`);
  let agree = 0, onlyA = 0, onlyB = 0, both = 0;
  for (let c = 0; c < maskA.length; c++) {
    const a = Boolean(maskA[c]), b = Boolean(maskB[c]);
    if (a === b) agree++;
    if (a && b) both++; else if (a) onlyA++; else if (b) onlyB++;
  }
  return {cells: maskA.length, agree_pct: maskA.length ? 100 * agree / maskA.length : null,
          only_a: onlyA, only_b: onlyB, both};
}
