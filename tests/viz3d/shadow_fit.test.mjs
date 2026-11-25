// The shadow camera of the 3D map (web/3d/shadow_fit.js). Run from the repo root:  node --test tests/viz3d/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import * as F from '../../web/3d/shadow_fit.js';
import * as M from '../../web/3d/sun_model.js';

const close = (a, b, tol = 1e-9, what = '') => assert.ok(Math.abs(a - b) <= tol, `${what} ${a} vs ${b}`);
const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
// The study box: 2 x 2 km, 475 m of relief around Y = 0 (terrain.js).
const BLOCK = {half: 1000, yMin: -238, yMax: 242};
const SITE = M.siteFromCrs((8142537.492786024 + 8144537.492786024) / 2, (-285463.075189438 - 283463.075189438) / 2);
const DISTANCE = 5000;

// Suns above the horizon: every 15 degrees of azimuth at eight heights, the zenith, and
// the Sun of sol 4711 through the day.
function suns() {
  const list = [{name: 'zenith', dir: [0, 1, 0]}];
  for (const el of [0.5, 3, 14.4, 30, 43.9, 60, 80, 89.9]) {
    for (let az = 0; az < 360; az += 15) list.push({name: `az ${az} el ${el}`, dir: M.sunVector(az, el)});
  }
  for (const hours of [6.2, 7, 9, 12, 15, 17, 17.8]) {
    list.push({name: `sol 4711 at ${hours}`, dir: M.sunState({sol: 4711, hours}, SITE).direction});
  }
  return list;
}

// Where a point falls in the camera's view: across, up, and metres in front of it.
function seen(point, dir) {
  const {right, up, back} = F.lightAxes(dir);
  return [dot(point, right), dot(point, up), DISTANCE - dot(point, back)];
}

test('axes of the light camera: unit, square to each other, level across the Sun', () => {
  for (const {name, dir} of suns()) {
    const {right, up, back} = F.lightAxes(dir);
    for (const axis of [right, up, back]) close(Math.hypot(...axis), 1, 1e-12, name);
    close(dot(right, up), 0, 1e-12, name);
    close(dot(right, back), 0, 1e-12, name);
    close(dot(up, back), 0, 1e-12, name);
    assert.equal(right[1], 0, `${name}: right is horizontal`);
    assert.ok(up[1] >= 0, `${name}: up does not point down`);
  }
  // Sun in the west (15:00): looking east, north is to the left, so right is south (+Z).
  assert.deepEqual(F.lightAxes(M.sunVector(270, 0)).right.map(v => Math.round(v)), [0, 0, 1]);
  assert.deepEqual(F.lightAxes([0, 1, 0]).right, [1, 0, 0]);
});

test('every corner of the block, lowest and highest, is inside the box for any Sun', () => {
  const corners = F.blockCorners(BLOCK);
  assert.equal(corners.length, 8);
  assert.deepEqual([...new Set(corners.map(c => c[1]))].sort((a, b) => a - b), [BLOCK.yMin, BLOCK.yMax]);
  for (const {name, dir} of suns()) {
    const fit = F.fitShadowBox(dir, BLOCK, {distance: DISTANCE});
    assert.ok(fit.near > 0 && fit.far > fit.near, `${name}: the box is in front of the camera`);
    for (const corner of corners) {
      const [x, y, depth] = seen(corner, dir);
      assert.ok(x > fit.left && x < fit.right, `${name}: ${corner} across ${x}`);
      assert.ok(y > fit.bottom && y < fit.top, `${name}: ${corner} up ${y}`);
      assert.ok(depth > fit.near && depth < fit.far, `${name}: ${corner} depth ${depth}`);
    }
  }
});

test('points on and inside the block are inside too (a box is the hull of its corners)', () => {
  const dir = M.sunVector(282.27, 43.91);                 // sol 4711 at 15:00
  const fit = F.fitShadowBox(dir, BLOCK, {distance: DISTANCE});
  for (let i = 0; i < 500; i++) {
    const t = n => ((i * n) % 101) / 100;                  // a fixed scatter, no random numbers
    const point = [BLOCK.half * (2 * t(7) - 1), BLOCK.yMin + (BLOCK.yMax - BLOCK.yMin) * t(13), BLOCK.half * (2 * t(29) - 1)];
    const [x, y, depth] = seen(point, dir);
    assert.ok(x >= fit.left && x <= fit.right && y >= fit.bottom && y <= fit.top && depth >= fit.near && depth <= fit.far);
  }
});

test('the box is not larger than needed: each side touches a corner but for the margin', () => {
  const margin = 4, depthMargin = 10;
  for (const {name, dir} of suns()) {
    const fit = F.fitShadowBox(dir, BLOCK, {distance: DISTANCE, margin, depthMargin});
    const views = F.blockCorners(BLOCK).map(c => seen(c, dir));
    const min = i => Math.min(...views.map(v => v[i])), max = i => Math.max(...views.map(v => v[i]));
    close(fit.left, min(0) - margin, 1e-9, name);
    close(fit.right, max(0) + margin, 1e-9, name);
    close(fit.bottom, min(1) - margin, 1e-9, name);
    close(fit.top, max(1) + margin, 1e-9, name);
    close(fit.near, min(2) - depthMargin, 1e-9, name);
    close(fit.far, max(2) + depthMargin, 1e-9, name);
    const tight = (max(0) - min(0)) * (max(1) - min(1));
    assert.ok(fit.width * fit.height < 1.03 * tight, `${name}: area ${fit.width * fit.height} vs ${tight}`);
    // Never wider than the block's diagonal, never taller than diagonal plus relief.
    const diagonal = 2 * BLOCK.half * Math.SQRT2, relief = BLOCK.yMax - BLOCK.yMin;
    assert.ok(fit.width <= diagonal + 2 * margin + 1e-9, name);
    assert.ok(fit.height <= Math.hypot(diagonal, relief) + 2 * margin + 1e-9, name);
  }
});

test('from straight above the box is the block itself; a higher block only changes the depth', () => {
  const fit = F.fitShadowBox([0, 1, 0], BLOCK, {distance: DISTANCE, margin: 0, depthMargin: 0});
  assert.deepEqual([fit.left, fit.right, fit.bottom, fit.top], [-1000, 1000, -1000, 1000]);
  assert.deepEqual([fit.near, fit.far], [DISTANCE - BLOCK.yMax, DISTANCE - BLOCK.yMin]);
  const taller = F.fitShadowBox([0, 1, 0], {...BLOCK, yMax: 300}, {distance: DISTANCE, margin: 0, depthMargin: 0});
  assert.deepEqual([taller.width, taller.height, taller.near], [2000, 2000, DISTANCE - 300]);
  // With a low Sun a higher block (exaggerated relief, the habitat dome) needs a taller box.
  const low = M.sunVector(277, 14.4);
  assert.ok(F.fitShadowBox(low, {...BLOCK, yMax: 300}).height > F.fitShadowBox(low, BLOCK).height + 50);
});

test('ground size of a texel: finer across the Sun, stretched along it when the Sun is low', () => {
  const at = hours => {
    const dir = M.sunState({sol: 4711, hours}, SITE).direction;
    return F.groundTexel(F.fitShadowBox(dir, BLOCK, {distance: DISTANCE}), 4096, dir);
  };
  const noon = at(12), afternoon = at(15), evening = at(17);
  for (const t of [noon, afternoon, evening]) assert.ok(t.across > 0.48 && t.across < 0.70, `across ${t.across}`);
  assert.ok(afternoon.along > 0.6 && afternoon.along < 0.8, `along at 15:00 ${afternoon.along}`);
  assert.ok(evening.along > 0.95 && evening.along < 1.15, `along at 17:00 ${evening.along}`);
  assert.ok(evening.along > afternoon.along && afternoon.along > noon.along);
  // Half the map size, twice the texel.
  const dir = M.sunVector(282, 44), fit = F.fitShadowBox(dir, BLOCK);
  close(F.groundTexel(fit, 2048, dir).across, 2 * F.groundTexel(fit, 4096, dir).across, 1e-12);
  close(F.groundTexel(fit, 2048, dir).along, 2 * F.groundTexel(fit, 4096, dir).along, 1e-12);
});

test('bias in metres along the light, and the angle that decides a redraw', () => {
  const fit = F.fitShadowBox(M.sunVector(282, 44), BLOCK);
  close(F.depthBias(fit, 1.5) * fit.depth, -1.5, 1e-12);
  assert.ok(F.depthBias(fit, 1.5) < 0);                                    // towards the light
  close(F.angleDeg([1, 0, 0], [0, 1, 0]), 90, 1e-12);
  close(F.angleDeg(M.sunVector(100, 30), M.sunVector(100, 30.2)), 0.2, 1e-9);
  assert.equal(F.angleDeg([0, 1, 0], [0, 1, 0]), 0);
  // Five minutes of the time slider move the Sun by about 1.2 degrees in mid-afternoon.
  const a = M.sunState({sol: 4711, hours: 15}, SITE).direction, b = M.sunState({sol: 4711, hours: 15 + 5 / 60}, SITE).direction;
  close(F.angleDeg(a, b), 1.2, 0.1);
});
