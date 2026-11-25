// Camera maths of the 3D map. Run from the repo root:  node --test tests/viz3d/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import * as M from '../../web/3d/camera_math.js';

const DEG = Math.PI / 180;
const TAN = Math.tan(25 * DEG), ASPECT = 1.6;       // 50 degree vertical field of view
const close = (a, b, tol = 1e-9) => assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);
const closeVec = (a, b, tol = 1e-9) => a.forEach((v, i) => close(v, b[i], tol));

test('axes: heading 0 looks north, heading 90 looks east, pitch 90 looks down', () => {
  closeVec(M.basis(0, 0).forward, [0, 0, -1]);          // north is -Z
  closeVec(M.basis(0, 0).right, [1, 0, 0]);             // east
  closeVec(M.basis(0, 0).up, [0, 1, 0]);
  closeVec(M.basis(90 * DEG, 0).forward, [1, 0, 0]);
  closeVec(M.basis(90 * DEG, 0).right, [0, 0, 1]);      // south
  closeVec(M.basis(0, 90 * DEG).forward, [0, -1, 0]);
  closeVec(M.basis(0, 90 * DEG).up, [0, 0, -1]);        // top of the screen is north
});

test('axes are orthonormal and never roll', () => {
  for (const [yaw, pitch] of [[0.3, 0.2], [2.5, 1.1], [-1.7, 1.55]]) {
    const b = M.basis(yaw, pitch);
    for (const v of [b.forward, b.right, b.up]) close(M.dot(v, v), 1);
    close(M.dot(b.forward, b.right), 0); close(M.dot(b.forward, b.up), 0); close(M.dot(b.right, b.up), 0);
    close(b.right[1], 0);                               // the horizon stays level
  }
});

test('orbit keeps the pivot at the same place on screen and at the same distance', () => {
  const pivot = [120, 35, -60], position = [400, 900, 700];
  const from = {yaw: 0.4, pitch: 0.7}, to = {yaw: 1.9, pitch: 1.2};
  const before = M.project(position, M.basis(from.yaw, from.pitch), pivot, TAN, ASPECT);
  const moved = M.orbit(position, pivot, from, to);
  const after = M.project(moved, M.basis(to.yaw, to.pitch), pivot, TAN, ASPECT);
  closeVec(after, before, 1e-9);
  close(M.distance(moved, pivot), M.distance(position, pivot), 1e-9);
});

test('orbit: turning the heading 90 degrees carries the camera a quarter turn around', () => {
  // Camera south of the pivot looking north; after heading east it must be west of it.
  const moved = M.orbit([0, 0, 100], [0, 0, 0], {yaw: 0, pitch: 0}, {yaw: 90 * DEG, pitch: 0});
  closeVec(moved, [-100, 0, 0], 1e-9);
});

test('a ray through a projected point comes back to that point', () => {
  const position = [10, 500, 300], axes = M.basis(0.6, 0.9), point = [80, 12, -140];
  const [x, y] = M.project(position, axes, point, TAN, ASPECT);
  const dir = M.rayDirection(axes, x, y, TAN, ASPECT);
  const t = M.distance(point, position);
  closeVec(M.along(position, dir, t), point, 1e-8);
});

test('pan puts the grabbed ground point back under the cursor, at the same altitude', () => {
  const axes = M.basis(0.3, 0.8), grab = [50, 20, -30], position = [0, 600, 400];
  const dir = M.rayDirection(axes, 0.4, -0.2, TAN, ASPECT);
  const moved = M.panToGrab(position, dir, grab);
  assert.equal(moved[1], position[1]);
  closeVec(M.project(moved, axes, grab, TAN, ASPECT), [0.4, -0.2], 1e-9);
  // A ray at or above the horizon cannot grab the ground.
  assert.equal(M.panToGrab(position, [0, 0.1, -1], grab), null);
});

test('zoom moves along the line to the pivot and respects the minimum distance', () => {
  const pivot = [0, 10, 0], position = [0, 110, 0];
  closeVec(M.zoomAbout(position, pivot, 0.5, 5), [0, 60, 0]);
  closeVec(M.zoomAbout(position, pivot, 0.001, 5), [0, 15, 0]);
});

test('picking hits a flat floor, a ramp, and misses outside the block', () => {
  const down = [0, -1, 0];
  closeVec(M.pickHeightfield([10, 100, 20], down, () => 7, 1000), [10, 7, 20], 1e-4);
  const ramp = (x) => 0.5 * x;                                  // rises to the east
  const dir = M.rayDirection(M.basis(90 * DEG, 30 * DEG), 0, 0, TAN, ASPECT);   // east, 30 deg down
  const hit = M.pickHeightfield([-500, 300, 0], dir, ramp, 1000);
  close(hit[1], ramp(hit[0]), 1e-3);
  assert.ok(hit[0] > -500 && hit[0] < 1000);
  assert.equal(M.pickHeightfield([5000, 100, 5000], down, () => 0, 1000), null);
  assert.equal(M.pickHeightfield([0, 100, 0], [0, 1, 0], () => 0, 1000), null);   // looking at the sky
});

test('picking finds the near face of a wall, not the ground behind it', () => {
  const wall = (x) => (x > 100 && x < 110 ? 50 : 0);            // 50 m high, 10 m thick
  const dir = M.rayDirection(M.basis(90 * DEG, 5 * DEG), 0, 0, TAN, ASPECT);
  const hit = M.pickHeightfield([0, 30, 0], dir, wall, 1000);
  assert.ok(hit[0] >= 99.5 && hit[0] <= 110, `hit at x = ${hit[0]}`);
});

test('angleDelta wraps around the circle', () => {
  close(M.angleDelta(10 * DEG, 350 * DEG), 20 * DEG, 1e-12);
  close(M.angleDelta(350 * DEG, 10 * DEG), -20 * DEG, 1e-12);
});

test('pitch is clamped between almost level and almost straight down', () => {
  assert.equal(M.clampPitch(-1), M.MIN_PITCH);
  assert.equal(M.clampPitch(3), M.MAX_PITCH);
});
