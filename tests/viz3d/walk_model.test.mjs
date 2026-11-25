// Walk-freely model of the 3D map. Run from the repo root:  node --test tests/viz3d/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import * as W from '../../web/3d/walk_model.js';
import { EYE_HEIGHT } from '../../web/3d/rehearse_model.js';

const DEG = Math.PI / 180;
const close = (a, b, tol = 1e-9) => assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);
const closeVec = (a, b, tol = 1e-9) => {
  assert.equal(a.length, b.length);
  a.forEach((v, i) => close(v, b[i], tol));
};
const BOX = {half: 1000};                             // the 2 x 2 km box, no obstacles
const DOME = {x: 0, z: -10, r: 4};                    // a habitat dome 10 m north of the origin

// ---- constants ----------------------------------------------------------------------

test('constants: the eye is the rehearsal eye, speeds and limits as agreed', () => {
  assert.equal(W.EYE_HEIGHT, EYE_HEIGHT);
  assert.equal(W.EYE_HEIGHT, 1.7);
  assert.deepEqual({...W.SPEEDS}, {walk: 1, run: 3, fast: 20});
  assert.equal(W.EDGE_MARGIN, 1);
  assert.equal(W.BODY_RADIUS, 0.3);
  assert.equal(W.LOOK_RAD_PER_PX, 0.0025);
  close(W.TURN_SPEED, 90 * DEG);
  close(W.PITCH_LIMIT, 85 * DEG);
  assert.equal(W.MAX_SUBSTEP, 0.5);
  assert.deepEqual(W.KEYS.forward, ['KeyW', 'ArrowUp']);
  assert.deepEqual(W.KEYS.back, ['KeyS', 'ArrowDown']);
  assert.deepEqual(W.KEYS.left, ['KeyA']);
  assert.deepEqual(W.KEYS.right, ['KeyD']);
  assert.deepEqual(W.KEYS.turnLeft, ['ArrowLeft']);
  assert.deepEqual(W.KEYS.turnRight, ['ArrowRight']);
});

// ---- moveAxes, speedOf, heading -----------------------------------------------------

test('moveAxes: WASD and Up/Down move, Left/Right do not strafe, opposite keys cancel', () => {
  assert.deepEqual(W.moveAxes([]), {forward: 0, right: 0});
  assert.deepEqual(W.moveAxes(undefined), {forward: 0, right: 0});
  assert.deepEqual(W.moveAxes(['KeyW']), {forward: 1, right: 0});
  assert.deepEqual(W.moveAxes(new Set(['ArrowDown'])), {forward: -1, right: 0});
  assert.deepEqual(W.moveAxes(['ArrowUp', 'KeyD']), {forward: 1, right: 1});
  assert.deepEqual(W.moveAxes(['KeyA', 'KeyS']), {forward: -1, right: -1});
  assert.deepEqual(W.moveAxes(['KeyW', 'KeyS']), {forward: 0, right: 0});
  assert.deepEqual(W.moveAxes(['KeyA']), {forward: 0, right: -1});
  assert.deepEqual(W.moveAxes(['KeyD']), {forward: 0, right: 1});
  assert.deepEqual(W.moveAxes(['KeyA', 'KeyD']), {forward: 0, right: 0});
  for (const code of ['ArrowLeft', 'ArrowRight']) {
    assert.deepEqual(W.moveAxes([code]), {forward: 0, right: 0});
  }
  assert.deepEqual(W.moveAxes(['ArrowLeft', 'KeyD', 'KeyW']), {forward: 1, right: 1});
  assert.deepEqual(W.moveAxes(['KeyW', 'ArrowUp']), {forward: 1, right: 0});   // both forward keys: still 1
  assert.deepEqual(W.moveAxes(['ShiftLeft', 'KeyF', 'Space']), {forward: 0, right: 0});
});

test('moveAxes: the on-screen pad names count like keys and mix with them', () => {
  assert.deepEqual(W.moveAxes(new Set(['back', 'left'])), {forward: -1, right: -1});
  assert.deepEqual(W.moveAxes(['forward', 'right']), {forward: 1, right: 1});
  assert.deepEqual(W.moveAxes(['forward', 'ArrowDown']), {forward: 0, right: 0});
  assert.deepEqual(W.moveAxes(['right', 'KeyA', 'KeyW']), {forward: 1, right: 0});
});

test('speedOf: walk by default, Shift runs, fast travel wins over running', () => {
  assert.equal(W.speedOf(), 1);
  assert.equal(W.speedOf({}), 1);
  assert.equal(W.speedOf({run: true}), 3);
  assert.equal(W.speedOf({fast: true}), 20);
  assert.equal(W.speedOf({run: true, fast: true}), 20);
});

test('heading: yaw 0 faces north with east on the right, yaw 90 faces east with south on the right', () => {
  const north = W.heading(0);
  closeVec(north.forward, [0, -1]);
  closeVec(north.right, [1, 0]);
  const east = W.heading(90 * DEG);
  closeVec(east.forward, [1, 0]);
  closeVec(east.right, [0, 1]);
  for (const yaw of [0.3, 2.2, -1.4]) {                // unit, perpendicular, right turned clockwise
    const h = W.heading(yaw);
    close(Math.hypot(...h.forward), 1); close(Math.hypot(...h.right), 1);
    close(h.forward[0] * h.right[0] + h.forward[1] * h.right[1], 0);
    closeVec(W.heading(yaw + 90 * DEG).forward, h.right);
  }
});

// ---- constrain ----------------------------------------------------------------------

test('constrain: a free point is unchanged and copied; the box keeps the margin', () => {
  const p = [12, -34];
  const q = W.constrain(p, BOX);
  assert.deepEqual(q, [12, -34]);
  assert.notEqual(q, p);
  assert.deepEqual(W.constrain([1500, -2000], BOX), [999, -999]);
  assert.deepEqual(W.constrain([1500, 5], {half: 1000, margin: 10}), [990, 5]);
  assert.deepEqual(W.constrain([999.5, -999.5], BOX), [999, -999]);
});

test('constrain: out of a circle radially to r + bodyRadius; from its centre towards +X', () => {
  const limits = {half: 1000, circles: [DOME]};
  closeVec(W.constrain([0, -10], limits), [4.3, -10]);                    // exactly at the centre
  closeVec(W.constrain([0, -8], limits), [0, -10 + 4.3]);                 // 2 m south of it
  closeVec(W.constrain([1.5, -12], limits), [0.6 * 4.3, -10 - 0.8 * 4.3]); // along (0.6, -0.8)
  assert.deepEqual(W.constrain([0, -5], limits), [0, -5]);                // already outside
  closeVec(W.constrain([1, -10], {...limits, bodyRadius: 1}), [5, -10]);
  // A dome near the corner: pushed out, then still kept inside the box.
  closeVec(W.constrain([998, 0], {half: 1000, circles: [{x: 996, z: 0, r: 4}]}), [999, 0]);
});

// ---- step ---------------------------------------------------------------------------

test('step: on open ground the walker covers exactly speed * dt the way it faces', () => {
  const a = W.step([10, 20], 0, {forward: 1, right: 0}, 3, 0.2, BOX);
  closeVec(a.position, [10, 20 - 0.6]);
  close(a.moved, 0.6);
  const b = W.step([0, 0], 90 * DEG, {forward: 1, right: 0}, 1, 1, BOX);   // facing east
  closeVec(b.position, [1, 0]);
  close(b.moved, 1);
  const c = W.step([0, 0], 0, {forward: 0, right: 1}, 1, 1, BOX);          // strafe right = east
  closeVec(c.position, [1, 0]);
  const d = W.step([0, 0], 0, {forward: -1, right: 0}, 1, 2, BOX);         // back = south
  closeVec(d.position, [0, 2]);
  close(d.moved, 2);
});

test('step: a diagonal is not faster than a straight move', () => {
  const s = W.step([0, 0], 0, {forward: 1, right: 1}, 1, 1, BOX);
  close(s.moved, 1);
  close(Math.hypot(...s.position), 1);
  closeVec(s.position, [Math.SQRT1_2, -Math.SQRT1_2]);                     // north-east
});

test('step: no keys or no time leaves the walker where it is (still constrained)', () => {
  const p = [5, 5];
  const a = W.step(p, 0, {forward: 0, right: 0}, 20, 0.1, BOX);
  assert.deepEqual(a, {position: [5, 5], moved: 0});
  assert.notEqual(a.position, p);
  assert.deepEqual(W.step(p, 0, {forward: 1, right: 0}, 1, 0, BOX), {position: [5, 5], moved: 0});
  assert.deepEqual(W.step(p, 0, {forward: 1, right: 0}, 1, -0.5, BOX), {position: [5, 5], moved: 0});
  assert.deepEqual(W.step([2000, 0], 0, {forward: 0, right: 0}, 1, 1, BOX), {position: [999, 0], moved: 0});
  assert.deepEqual(p, [5, 5]);                                             // the input is not changed
});

test('step: long moves are split into sub-steps, so fast travel cannot jump over a dome', () => {
  // 20 m in one frame straight at a dome 10 m ahead: one 20 m jump would land past it
  // (10 m beyond its centre); in 0.5 m sub-steps the walker stops at its wall.
  const s = W.step([0, 0], 0, {forward: 1, right: 0}, 20, 1, {half: 1000, circles: [DOME]});
  closeVec(s.position, [0, -10 + 4.3]);
  close(s.moved, 10 - 4.3);
  // On open ground the sub-steps add up to the whole move.
  const free = W.step([0, 0], 0, {forward: 1, right: 0}, 20, 1, BOX);
  closeVec(free.position, [0, -20]);
  close(free.moved, 20);
});

test('step: walking out of the box stops at half - margin and moved shrinks', () => {
  const s = W.step([998, 0], 90 * DEG, {forward: 1, right: 0}, 1, 2, BOX);
  closeVec(s.position, [999, 0]);
  close(s.moved, 1);
  const again = W.step(s.position, 90 * DEG, {forward: 1, right: 0}, 1, 2, BOX);
  closeVec(again.position, [999, 0]);
  close(again.moved, 0);
  // Diagonally into the east edge: only the northward part is left.
  const slide = W.step([999, 0], 45 * DEG, {forward: 1, right: 0}, 1, 1, BOX);
  closeVec(slide.position, [999, -Math.SQRT1_2]);
  close(slide.moved, Math.SQRT1_2);
});

test('step: fast travel (20 m/s, dt 0.1) at a dome never ends inside r + bodyRadius', () => {
  const limits = {half: 1000, circles: [DOME]}, keep = DOME.r + W.BODY_RADIUS;
  for (const start of [[0, 0], [0.5, 0], [-1.2, 3]]) {
    let p = start, total = 0;
    for (let frame = 0; frame < 100; frame++) {
      const s = W.step(p, 0, {forward: 1, right: 0}, 20, 0.1, limits);
      assert.ok(Math.hypot(s.position[0] - DOME.x, s.position[1] - DOME.z) >= keep - 1e-9, `${s.position}`);
      assert.ok(s.moved <= 2 + 1e-9);
      p = s.position; total += s.moved;
    }
    if (start[0] === 0) {                                                  // head on: stuck at the wall
      closeVec(p, [0, -10 + 4.3]);
      close(total, 5.7);
    } else {
      assert.ok(p[1] < DOME.z - keep, `slid around the dome: ${p}`);     // off-centre: slides past it
    }
  }
});

// ---- look ---------------------------------------------------------------------------

test('turn: Left/Right turn, opposite arrows cancel, movement keys and the pad do not turn', () => {
  close(W.turn(0.3, ['ArrowLeft'], 0.1), 0.3 - W.TURN_SPEED * 0.1);
  close(W.turn(0.3, new Set(['ArrowRight']), 0.1), 0.3 + W.TURN_SPEED * 0.1);
  for (const pressed of [undefined, [], ['ArrowLeft', 'ArrowRight'],
                         ['KeyW', 'KeyS', 'ArrowUp', 'ArrowDown'], ['ShiftLeft', 'KeyF', 'KeyC'],
                         ['KeyA'], ['KeyD'], ['left'], ['right'], ['forward', 'back']]) {
    assert.equal(W.turn(0.3, pressed, 1), 0.3);
  }
  close(W.turn(0.3, ['KeyD', 'ArrowLeft'], 0.1), 0.3 - W.TURN_SPEED * 0.1);
});

test('turn: radians per second scale with dt, independent of frame rate', () => {
  for (const code of ['ArrowLeft', 'ArrowRight']) {
    const sign = code === 'ArrowLeft' ? -1 : 1;
    for (const dt of [0, 1 / 144, 1 / 60, 0.1, 1]) {
      close(W.turn(0, [code], dt), sign * W.TURN_SPEED * dt);
    }
    for (const fps of [30, 60, 144]) {
      let yaw = 0;
      for (let i = 0; i < fps; i++) yaw = W.turn(yaw, [code], 1 / fps);
      close(yaw, sign * W.TURN_SPEED);
    }
    const frames = [0.01, 0.04, 0.02, 0.08, 0.05];
    const yaw = frames.reduce((at, dt) => W.turn(at, [code], dt), 0);
    close(yaw, sign * W.TURN_SPEED * 0.2);
    assert.equal(W.turn(0.3, [code], -1), 0.3);
  }
});

test('turn: wraps the heading at +-pi while preserving the turn direction', () => {
  close(W.turn(175 * DEG, ['ArrowRight'], 1 / 9), -175 * DEG);
  close(W.turn(-175 * DEG, ['ArrowLeft'], 1 / 9), 175 * DEG);
  close(W.turn(0, ['ArrowRight'], 2), Math.PI);
  close(W.turn(0, ['ArrowLeft'], 2), Math.PI);
});

test('turn: releasing a held arrow stops turning immediately', () => {
  for (const code of ['ArrowLeft', 'ArrowRight']) {
    const pressed = new Set(['ArrowUp', code]);
    const yaw = W.turn(0.3, pressed, 0.1);
    assert.notEqual(yaw, 0.3);
    pressed.delete(code);
    for (let i = 0; i < 60; i++) assert.equal(W.turn(yaw, pressed, 1 / 60), yaw);
    assert.deepEqual(W.moveAxes(pressed), {forward: 1, right: 0}); // forward stays held
  }
});

test('turn and step: Up with Left/Right walks a curve at the selected speed', () => {
  for (const code of ['ArrowLeft', 'ArrowRight']) {
    const sign = code === 'ArrowLeft' ? -1 : 1, pressed = new Set(['ArrowUp', code]);
    for (const speed of Object.values(W.SPEEDS)) for (const fps of [30, 60, 144]) {
      let position = [0, 0], yaw = 0, distance = 0;
      for (let i = 0; i < fps; i++) {
        yaw = W.turn(yaw, pressed, 1 / fps);
        const got = W.step(position, yaw, W.moveAxes(pressed), speed, 1 / fps, BOX);
        assert.ok(sign * (got.position[0] - position[0]) > 0);
        assert.ok(got.position[1] <= position[1] + 1e-9);
        position = got.position;
        distance += got.moved;
      }
      close(yaw, sign * Math.PI / 2);
      close(distance, speed);                           // one second, no strafe speed boost
      const radius = speed / W.TURN_SPEED;
      closeVec(position, [sign * radius, -radius], speed / fps); // within one step of the arc
    }
  }
});

test('turn and look: keyboard and mouse deltas add to the current yaw without changing pitch', () => {
  for (const code of ['ArrowLeft', 'ArrowRight']) {
    const mouse = W.look(3, 0.2, 100, -40);
    const yaw = W.turn(mouse.yaw, [code], 0.1);
    const reverse = W.look(W.turn(3, [code], 0.1), 0.2, 100, -40);
    close(yaw, reverse.yaw);
    close(mouse.pitch, 0.1);
    close(mouse.pitch, reverse.pitch);
    assert.equal(W.turn(mouse.yaw, [], 0.1), mouse.yaw);
  }
});

test('look: right turns right, down looks down, by radPerPx per pixel', () => {
  const a = W.look(0, 0, 100, 40);
  close(a.yaw, 100 * 0.0025);
  close(a.pitch, 40 * 0.0025);
  const b = W.look(1, 0.5, -200, -100);
  close(b.yaw, 1 - 0.5);
  close(b.pitch, 0.5 - 0.25);
  const c = W.look(0, 0, 10, 10, 0.01);
  close(c.yaw, 0.1);
  close(c.pitch, 0.1);
  assert.deepEqual(W.look(0.3, 0.2, 0, 0), {yaw: 0.3, pitch: 0.2});
});

test('look: yaw wraps into (-pi, pi], pitch stops at +-85 degrees', () => {
  close(W.look(3, 0, 200, 0).yaw, 3.5 - 2 * Math.PI);
  close(W.look(-3, 0, -200, 0).yaw, -3.5 + 2 * Math.PI);
  close(W.look(Math.PI, 0, 0, 0).yaw, Math.PI);
  close(W.look(-Math.PI, 0, 0, 0).yaw, Math.PI);
  close(W.look(0, 0, 10 * 2 * Math.PI / 0.0025 + 100, 0).yaw, 0.25, 1e-6);  // ten whole turns and a bit
  for (const dx of [-5000, -1300, 0, 777, 9000]) {
    const yaw = W.look(2.9, 0, dx, 0).yaw;
    assert.ok(yaw > -Math.PI && yaw <= Math.PI, `${yaw}`);
  }
  assert.equal(W.look(0, 1.4, 0, 1000).pitch, W.PITCH_LIMIT);
  assert.equal(W.look(0, -1.4, 0, -1000).pitch, -W.PITCH_LIMIT);
  close(W.look(0, 0, 0, 100).pitch, 0.25);                                 // well inside: not clamped
});

// ---- nearestOnPath ------------------------------------------------------------------

test('nearestOnPath: an L path, 10 m east then 10 m south', () => {
  const path = [[0, 0], [10, 0], [10, 10]];
  const a = W.nearestOnPath([12, 5], path);
  close(a.distance, 2); closeVec(a.point, [10, 5]); assert.equal(a.segment, 1); close(a.along, 15);
  const b = W.nearestOnPath([5, -3], path);
  close(b.distance, 3); closeVec(b.point, [5, 0]); assert.equal(b.segment, 0); close(b.along, 5);
  const c = W.nearestOnPath([-3, -4], path);                               // before the start
  close(c.distance, 5); closeVec(c.point, [0, 0]); assert.equal(c.segment, 0); close(c.along, 0);
  const d = W.nearestOnPath([10, 16], path);                               // past the end
  close(d.distance, 6); closeVec(d.point, [10, 10]); assert.equal(d.segment, 1); close(d.along, 20);
  const e = W.nearestOnPath([7, 3], path);                                 // on the inside of the corner
  close(e.distance, 3); assert.equal(e.segment, 0); close(e.along, 7);
  const f = W.nearestOnPath([10, 4], path);                                // on the route
  close(f.distance, 0); close(f.along, 14);
});

test('nearestOnPath: no path is null, one point is its own nearest, empty segments are skipped', () => {
  assert.equal(W.nearestOnPath([1, 1], []), null);
  assert.equal(W.nearestOnPath([1, 1], null), null);
  assert.equal(W.nearestOnPath([1, 1], undefined), null);
  assert.deepEqual(W.nearestOnPath([3, 4], [[0, 0]]), {distance: 5, point: [0, 0], segment: 0, along: 0});
  assert.deepEqual(W.nearestOnPath([3, 4], [[0, 0], [0, 0]]), {distance: 5, point: [0, 0], segment: 0, along: 0});
  const g = W.nearestOnPath([12, 5], [[0, 0], [10, 0], [10, 0], [10, 10]]);
  close(g.distance, 2); assert.equal(g.segment, 2); close(g.along, 15);
  assert.ok(Number.isFinite(g.point[0]) && Number.isFinite(g.point[1]));
});

// ---- startPose ----------------------------------------------------------------------

test('startPose: with no habitat, the fallback place and heading', () => {
  assert.deepEqual(W.startPose({}), {position: [0, 0], yaw: 0});
  assert.deepEqual(W.startPose({fallback: [5, -6], fallbackYaw: 1.2}), {position: [5, -6], yaw: 1.2});
  assert.deepEqual(W.startPose({habitat: null, path: [[0, 0], [50, 0]], fallback: [7, 8]}), {position: [7, 8], yaw: 0});
});

test('startPose: outside the dome door, facing the way the route leaves', () => {
  const clearance = 4 + W.BODY_RADIUS + 1.5;                               // 5.8 m from the habitat centre
  const east = W.startPose({habitat: [100, 200], path: [[100, 200], [140, 200]]});
  closeVec(east.position, [100 + clearance, 200]);
  close(east.yaw, 90 * DEG);
  const south = W.startPose({habitat: [0, 0], path: [[0, 0], [0, 30]]});
  closeVec(south.position, [0, clearance]);
  close(Math.abs(south.yaw), Math.PI);
  const ne = W.startPose({habitat: [0, 0], path: [[30, -30]]});
  closeVec(ne.position, [clearance * Math.SQRT1_2, -clearance * Math.SQRT1_2]);
  close(ne.yaw, 45 * DEG);
  const wider = W.startPose({habitat: [0, 0], path: [[0, 0], [-20, 0]], domeRadius: 6, gap: 2});
  closeVec(wider.position, [-(6 + W.BODY_RADIUS + 2), 0]);
  close(wider.yaw, -90 * DEG);
  for (const pose of [east, south, ne, wider]) {                          // the yaw really faces that way
    const at = pose === east ? [100, 200] : [0, 0];
    const d = [pose.position[0] - at[0], pose.position[1] - at[1]], len = Math.hypot(...d);
    closeVec(W.heading(pose.yaw).forward, [d[0] / len, d[1] / len]);
  }
});

test('startPose: route vertices near the dome do not set the direction; none far away means north', () => {
  // Clearance 5.8 m, so vertices up to 7.8 m from the habitat are skipped: these wind
  // south and south-east around the door before the route heads east.
  const path = [[0, 0], [0, 3], [5, 5], [7, 0], [7.8, 0], [20, 0]];
  const pose = W.startPose({habitat: [0, 0], path});
  closeVec(pose.position, [5.8, 0]);
  close(pose.yaw, 90 * DEG);
  const near = W.startPose({habitat: [10, 10], path: [[10, 10], [13, 14], [15, 15]]});   // all within 7.8 m
  closeVec(near.position, [10, 10 - 5.8]);
  close(near.yaw, 0);
  const none = W.startPose({habitat: [10, 10]});
  closeVec(none.position, [10, 10 - 5.8]);
  close(none.yaw, 0);
});

// ---- ribbon -------------------------------------------------------------------------

test('ribbon: a straight line, edges exactly halfWidth away, left on the walker\'s left', () => {
  const r = W.ribbon([[0, 0], [10, 0], [20, 0]], 2);                       // walking east: left is north
  assert.deepEqual(r.centre, [[0, 0], [10, 0], [20, 0]]);
  r.left.forEach((v, i) => closeVec(v, [10 * i, -2]));
  r.right.forEach((v, i) => closeVec(v, [10 * i, 2]));
  // The same thing seen through heading(): left = -right.
  const yaw = 1.0, h = W.heading(yaw), a = [3, 4], b = [3 + 50 * h.forward[0], 4 + 50 * h.forward[1]];
  const s = W.ribbon([a, b], 1.5);
  closeVec(s.left[0], [a[0] - 1.5 * h.right[0], a[1] - 1.5 * h.right[1]]);
  closeVec(s.right[1], [b[0] + 1.5 * h.right[0], b[1] + 1.5 * h.right[1]]);
  for (let i = 0; i < 2; i++) close(Math.hypot(s.left[i][0] - s.centre[i][0], s.left[i][1] - s.centre[i][1]), 1.5);
});

test('ribbon: repeated vertices are dropped; fewer than two distinct vertices give nothing', () => {
  const r = W.ribbon([[0, 0], [0, 0], [10, 0], [10, 1e-8], [10, 10]], 1);
  assert.deepEqual(r.centre, [[0, 0], [10, 0], [10, 10]]);
  assert.equal(r.left.length, 3);
  assert.equal(r.right.length, 3);
  const empty = {left: [], right: [], centre: []};
  assert.deepEqual(W.ribbon([], 1), empty);
  assert.deepEqual(W.ribbon(null, 1), empty);
  assert.deepEqual(W.ribbon([[5, 5]], 1), empty);
  assert.deepEqual(W.ribbon([[5, 5], [5, 5 + 1e-9]], 1), empty);
});

test('ribbon: a right-angle corner sits on the mitre', () => {
  const hw = 2, r = W.ribbon([[0, 0], [10, 0], [10, 10]], hw);             // east, then south
  closeVec(r.left[0], [0, -hw]);                                          // end vertices: perpendicular
  closeVec(r.right[0], [0, hw]);
  closeVec(r.left[2], [10 + hw, 10]);                                     // walking south: left is east
  closeVec(r.right[2], [10 - hw, 10]);
  closeVec(r.left[1], [10 + hw, -hw]);                                    // where the offset edges meet
  closeVec(r.right[1], [10 - hw, hw]);
  close(Math.hypot(r.left[1][0] - 10, r.left[1][1]), hw * Math.SQRT2);
});

test('ribbon: a hairpin is capped at 2 * halfWidth, and edges stay symmetric', () => {
  const hw = 1.5, cap = 2 * hw;
  for (const path of [[[0, 0], [10, 0], [0, 1]], [[0, 0], [10, 0], [0, -1]], [[0, 0], [10, 0], [0, 0]],
                      [[0, 0], [10, 0], [10, 10], [9.9, 0], [20, 5]]]) {
    const r = W.ribbon(path, hw);
    assert.equal(r.left.length, path.length);
    for (let i = 0; i < r.centre.length; i++) {
      const [cx, cz] = r.centre[i];
      const dl = Math.hypot(r.left[i][0] - cx, r.left[i][1] - cz);
      assert.ok(Number.isFinite(dl) && dl >= hw - 1e-9 && dl <= cap + 1e-9, `${dl}`);
      closeVec([r.left[i][0] + r.right[i][0], r.left[i][1] + r.right[i][1]], [2 * cx, 2 * cz]);
    }
  }
  const tip = W.ribbon([[0, 0], [10, 0], [0, 1]], hw);                     // uncapped this would be ~30 m out
  close(Math.hypot(tip.left[1][0] - 10, tip.left[1][1]), cap);
  const back = W.ribbon([[0, 0], [10, 0], [0, 0]], hw);                    // exact turn-back
  closeVec(back.left[1], [10 + cap, 0]);
  closeVec(back.right[1], [10 - cap, 0]);
  // Up to 120 degrees of turn the mitre is not capped (hw / cos 60 = 2 hw).
  const wide = W.ribbon([[0, 0], [10, 0], [10 - 5, 5 * Math.sqrt(3)]], hw);
  close(Math.hypot(wide.left[1][0] - 10, wide.left[1][1]), cap);
});

// ---- swing and readoutText ----------------------------------------------------------

test('swing: amplitude * sin(2 pi d / stride), one period per stride', () => {
  close(W.swing(0), 0);
  close(W.swing(1.4 / 4), 0.5);
  close(W.swing(1.4 / 2), 0);
  close(W.swing(3 * 1.4 / 4), -0.5);
  for (const d of [0.1, 0.77, 3.3, 41.9]) close(W.swing(d + 1.4), W.swing(d));
  close(W.swing(0.5, {stride: 2, amplitude: 0.8}), 0.8);
  close(W.swing(3, {stride: 2}), 0);
  close(W.swing(1.5, {amplitude: 1}), Math.sin(2 * Math.PI * 1.5 / 1.4));
});

test('readoutText: mode, speed and how far the route is', () => {
  assert.equal(W.readoutText({speed: 1, mode: 'walk'}), 'Walking 1.0 m/s');
  assert.equal(W.readoutText({speed: 3, mode: 'run'}), 'Running 3.0 m/s');
  assert.equal(W.readoutText({speed: 20, mode: 'fast'}), 'Fast 20 m/s');
  assert.equal(W.readoutText({speed: 2.25, mode: 'walk'}), 'Walking 2.3 m/s');
  assert.equal(W.readoutText({speed: 12.6, mode: 'fast'}), 'Fast 13 m/s');
  assert.equal(W.readoutText({speed: 1, mode: 'walk', toRoute: 12.4}), 'Walking 1.0 m/s · 12 m from the route');
  assert.equal(W.readoutText({speed: 3, mode: 'run', toRoute: 1}), 'Running 3.0 m/s · 1 m from the route');
  assert.equal(W.readoutText({speed: 1, mode: 'walk', toRoute: 0.99}), 'Walking 1.0 m/s · on the route');
  assert.equal(W.readoutText({speed: 1, mode: 'walk', toRoute: 0}), 'Walking 1.0 m/s · on the route');
  assert.equal(W.readoutText({speed: 20, mode: 'fast', toRoute: 999.4}), 'Fast 20 m/s · 999 m from the route');
  assert.equal(W.readoutText({speed: 20, mode: 'fast', toRoute: 999.7}), 'Fast 20 m/s · 1.0 km from the route');
  assert.equal(W.readoutText({speed: 20, mode: 'fast', toRoute: 1234}), 'Fast 20 m/s · 1.2 km from the route');
  for (const toRoute of [undefined, null, NaN, Infinity, '12']) {
    assert.equal(W.readoutText({speed: 1, mode: 'walk', toRoute}), 'Walking 1.0 m/s');
  }
});
