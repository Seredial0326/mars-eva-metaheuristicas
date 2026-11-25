// Walk-freely model of the 3D map, with no dependencies (tested with `node --test`).
//
// The first-person mode of issue #109: which keys move the walker and how fast, where it
// may stand (inside the 2 x 2 km box, never inside the habitat dome), how keys and mouse turn
// the view, how far the walker is from the planned route, where it starts, the ground
// strip that shows the route and the line of text under the view. walk.js does the
// three.js and page side; everything here is plain numbers.
//
// Scene axes as camera_math.js: X = east, Y = up, Z = south (north is -Z), metres, origin
// at the box centre. Points on the ground are [X, Z] arrays. yaw = heading from north
// towards east, pitch = angle below the horizon (positive looking down), both in radians.
export { EYE_HEIGHT } from './rehearse_model.js';   // same eye as the rehearsal walker

export const SPEEDS = Object.freeze({walk: 1, run: 3, fast: 20});   // m/s
export const EDGE_MARGIN = 1;          // m kept inside the box edge (there is no ground past it)
export const BODY_RADIUS = 0.3;        // m: the walker is a disc this wide, not a point
export const LOOK_RAD_PER_PX = 0.0025; // radians of turn per pixel of mouse or finger
export const TURN_SPEED = Math.PI / 2; // rad/s: a quarter turn in one second with the arrow keys
export const PITCH_LIMIT = 85 * Math.PI / 180;   // never quite straight up or down
export const MAX_SUBSTEP = 0.5;        // m: longest move between two collision checks
// KeyboardEvent.code values, so the keys stay in place on any keyboard layout.
export const KEYS = Object.freeze({
  forward: Object.freeze(['KeyW', 'ArrowUp']),
  back: Object.freeze(['KeyS', 'ArrowDown']),
  left: Object.freeze(['KeyA']),
  right: Object.freeze(['KeyD']),
  turnLeft: Object.freeze(['ArrowLeft']),
  turnRight: Object.freeze(['ArrowRight']),
});

const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// ---- moving -------------------------------------------------------------------------

// Wanted direction from what is held down: key codes and/or the on-screen pad's names
// ('forward', 'back', 'left', 'right'). Returns {forward, right}, each -1, 0 or 1;
// opposite keys cancel.
export function moveAxes(pressed) {
  const down = new Set(pressed ?? []);
  const held = name => down.has(name) || KEYS[name].some(code => down.has(code));
  return {forward: held('forward') - held('back'), right: held('right') - held('left')};
}

// Speed in m/s; fast travel wins over running.
export function speedOf({run = false, fast = false} = {}) {
  return fast ? SPEEDS.fast : run ? SPEEDS.run : SPEEDS.walk;
}

// Horizontal unit vectors of a heading: where forward and right point on the ground.
export function heading(yaw) {
  const s = Math.sin(yaw), c = Math.cos(yaw);
  return {forward: [s, -c], right: [c, s]};
}

// Nearest place the walker may stand: out of every obstacle circle {x, z, r} (pushed
// straight away from its centre, to r + bodyRadius; from the very centre, towards +X),
// then inside the box. Returns a new [X, Z].
export function constrain(p, {half = Infinity, margin = EDGE_MARGIN, circles = [], bodyRadius = BODY_RADIUS} = {}) {
  let x = p[0], z = p[1];
  for (const c of circles || []) {
    const keep = c.r + bodyRadius, dx = x - c.x, dz = z - c.z, d = Math.hypot(dx, dz);
    if (!(d < keep)) continue;
    if (d > 0) { x = c.x + dx / d * keep; z = c.z + dz / d * keep; }
    else { x = c.x + keep; z = c.z; }
  }
  const edge = half - margin;
  return [clamp(x, -edge, edge), clamp(z, -edge, edge)];
}

// One frame of walking: from p along axes ({forward, right}, as moveAxes) at `speed`
// m/s for dt seconds. A diagonal is no faster than a straight move. Long moves are cut
// into equal steps of at most MAX_SUBSTEP metres, each one constrained, so fast travel
// cannot jump over a dome. Returns {position, moved}: moved is the ground distance
// actually covered (less than speed * dt when the walker is held back).
export function step(p, yaw, axes, speed, dt, limits = {}) {
  let at = constrain(p, limits), moved = 0;
  const f = axes?.forward || 0, r = axes?.right || 0, {forward, right} = heading(yaw);
  const mx = f * forward[0] + r * right[0], mz = f * forward[1] + r * right[1];
  const len = Math.hypot(mx, mz), distance = Math.min(1, len) * speed * dt;
  if (!(len > 0) || !(distance > 0)) return {position: at, moved: 0};
  const n = Math.max(1, Math.ceil(distance / MAX_SUBSTEP)), each = distance / n;
  const ux = mx / len * each, uz = mz / len * each;
  for (let k = 0; k < n; k++) {
    const next = constrain([at[0] + ux, at[1] + uz], limits);
    moved += Math.hypot(next[0] - at[0], next[1] - at[1]);
    at = next;
  }
  return {position: at, moved};
}

// ---- looking ------------------------------------------------------------------------

// Angle in (-pi, pi]. One already there is returned as is, so a still mouse never drifts.
function wrapAngle(a) {
  if (a > -Math.PI && a <= Math.PI) return a;
  const turn = 2 * Math.PI;
  let w = Math.PI - ((Math.PI - a) % turn + turn) % turn;
  if (w <= -Math.PI) w += turn;
  return w;
}

// Held arrow keys turn the current heading at TURN_SPEED rad/s; opposite arrows cancel.
// Uses the latest yaw (including mouse look), with no change to pitch or pad movement.
export function turn(yaw, pressed, dt) {
  const down = new Set(pressed ?? []);
  const direction = KEYS.turnRight.some(code => down.has(code)) - KEYS.turnLeft.some(code => down.has(code));
  if (!direction || !(dt > 0)) return yaw;
  return wrapAngle(yaw + direction * TURN_SPEED * dt);
}

// Mouse or finger drag of (dx, dy) pixels: right turns right, down looks down.
// Returns {yaw, pitch}, yaw in (-pi, pi], pitch within +-PITCH_LIMIT.
export function look(yaw, pitch, dx, dy, radPerPx = LOOK_RAD_PER_PX) {
  return {yaw: wrapAngle(yaw + (dx || 0) * radPerPx),
          pitch: clamp(pitch + (dy || 0) * radPerPx, -PITCH_LIMIT, PITCH_LIMIT)};
}

// ---- the route ----------------------------------------------------------------------

// Nearest point of a polyline [[X, Z], ...] to p: {distance, point, segment (index of its
// first vertex), along (metres from the path start)}, or null with no path. Segments of
// no length are skipped; a single vertex is its own nearest point.
export function nearestOnPath(p, path) {
  if (!path || !path.length) return null;
  const [px, pz] = p, [x0, z0] = path[0];
  let best = {distance: Math.hypot(px - x0, pz - z0), point: [x0, z0], segment: 0, along: 0};
  let start = 0;                                    // metres from the path start to vertex i
  for (let i = 0; i + 1 < path.length; i++) {
    const [ax, az] = path[i], [bx, bz] = path[i + 1];
    const dx = bx - ax, dz = bz - az, len = Math.hypot(dx, dz);
    if (len > 1e-12) {
      const f = clamp(((px - ax) * dx + (pz - az) * dz) / (len * len), 0, 1);
      const qx = ax + dx * f, qz = az + dz * f, d = Math.hypot(px - qx, pz - qz);
      if (d < best.distance) best = {distance: d, point: [qx, qz], segment: i, along: start + len * f};
    }
    start += len;
  }
  return best;
}

// Where the walker appears: just outside the habitat dome (a gap away from its wall),
// facing the way the route leaves. The direction is taken from the first route vertex
// clearly past that ring (2 m more), so a route that winds around the dome door does
// not set it; with no such vertex the walker faces north. With no habitat: the fallback.
// Returns {position: [X, Z], yaw}.
export function startPose({habitat = null, path = null, fallback = [0, 0], fallbackYaw = 0,
                           domeRadius = 4, gap = 1.5} = {}) {
  if (!habitat) return {position: [fallback[0], fallback[1]], yaw: fallbackYaw};
  const [hx, hz] = habitat, clearance = domeRadius + BODY_RADIUS + gap;
  const far = (path || []).find(v => Math.hypot(v[0] - hx, v[1] - hz) > clearance + 2);
  let d = [0, -1];
  if (far) {
    const len = Math.hypot(far[0] - hx, far[1] - hz);
    d = [(far[0] - hx) / len, (far[1] - hz) / len];
  }
  return {position: [hx + d[0] * clearance, hz + d[1] * clearance], yaw: Math.atan2(d[0], -d[1])};
}

// Edges of a flat strip 2 * halfWidth wide along a polyline, to lay the route on the
// ground: {left, right, centre}, one [X, Z] per vertex (repeated vertices dropped).
// "left" is on the walker's left going along the path. Inner vertices sit on the mitre
// (where the offset edges meet), but never farther than 2 * halfWidth from the centre,
// so a hairpin does not throw a spike. Fewer than 2 distinct vertices: empty arrays.
export function ribbon(path, halfWidth) {
  const centre = [];
  for (const v of path || []) {
    const last = centre[centre.length - 1];
    if (!last || Math.hypot(v[0] - last[0], v[1] - last[1]) >= 1e-6) centre.push([v[0], v[1]]);
  }
  if (centre.length < 2) return {left: [], right: [], centre: []};
  const n = centre.length, normals = [];          // left of each segment: [dZ, -dX]
  for (let i = 0; i + 1 < n; i++) {
    const dx = centre[i + 1][0] - centre[i][0], dz = centre[i + 1][1] - centre[i][1], len = Math.hypot(dx, dz);
    normals.push([dz / len, -dx / len]);
  }
  const left = [], right = [], cap = 2 * halfWidth;
  for (let i = 0; i < n; i++) {
    let m, reach = halfWidth;
    if (i === 0 || i === n - 1) m = normals[i === 0 ? 0 : n - 2];
    else {
      const a = normals[i - 1], b = normals[i], sx = a[0] + b[0], sz = a[1] + b[1], s = Math.hypot(sx, sz);
      if (s > 1e-9) {
        m = [sx / s, sz / s];
        reach = Math.min(cap, halfWidth / (m[0] * a[0] + m[1] * a[1]));
      } else {                                      // exact turn-back: no mitre, point ahead
        m = [-a[1], a[0]];
        reach = cap;
      }
    }
    const [cx, cz] = centre[i];
    left.push([cx + m[0] * reach, cz + m[1] * reach]);
    right.push([cx - m[0] * reach, cz - m[1] * reach]);
  }
  return {left, right, centre};
}

// ---- the walker and the screen ------------------------------------------------------

// Leg swing (radians) of the animated walker after `distance` metres: one full swing
// back and forth per stride.
export function swing(distance, {stride = 1.4, amplitude = 0.5} = {}) {
  return amplitude * Math.sin(2 * Math.PI * distance / stride);
}

const MODE_WORDS = {walk: 'Walking', run: 'Running', fast: 'Fast'};

// The line under the view: "Walking 1.0 m/s · 12 m from the route". The distance part
// only when toRoute is a number.
export function readoutText({speed, mode, toRoute} = {}) {
  const v = Number.isFinite(speed) ? speed : 0;
  let text = `${MODE_WORDS[mode] ?? MODE_WORDS.walk} ${v < 10 ? v.toFixed(1) : v.toFixed(0)} m/s`;
  if (Number.isFinite(toRoute)) {
    const metres = Math.round(toRoute);
    text += ' · ' + (toRoute < 1 ? 'on the route'
      : metres >= 1000 ? `${(toRoute / 1000).toFixed(1)} km from the route`
      : `${metres} m from the route`);
  }
  return text;
}
