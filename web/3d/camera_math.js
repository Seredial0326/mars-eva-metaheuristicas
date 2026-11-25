// Camera maths of the 3D map, with no dependencies (tested with `node --test`).
//
// Scene axes: X = east, Y = up, Z = south. Vectors are plain [x, y, z] arrays.
// The camera never rolls: its attitude is a heading (yaw, from north towards east)
// and a pitch (angle below the horizon, positive looking down), both in radians.

export const MIN_PITCH = 2 * Math.PI / 180;        // almost level
export const MAX_PITCH = 89.5 * Math.PI / 180;     // almost straight down

export const clampPitch = p => Math.min(MAX_PITCH, Math.max(MIN_PITCH, p));
export const add = (a, b) => [a[0] + b[0], a[1] + b[1], a[2] + b[2]];
export const sub = (a, b) => [a[0] - b[0], a[1] - b[1], a[2] - b[2]];
export const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];
export const along = (o, d, t) => [o[0] + d[0] * t, o[1] + d[1] * t, o[2] + d[2] * t];
export const distance = (a, b) => Math.hypot(a[0] - b[0], a[1] - b[1], a[2] - b[2]);

// Unit axes of a camera with this heading and pitch.
export function basis(yaw, pitch) {
  const cy = Math.cos(yaw), sy = Math.sin(yaw), cp = Math.cos(pitch), sp = Math.sin(pitch);
  return {
    forward: [sy * cp, -sp, -cy * cp],
    right: [cy, 0, sy],
    up: [sy * sp, cp, -cy * sp],                    // right x forward
  };
}

// Arcball step: turn the camera from one attitude to another around `pivot`.
// The pivot keeps its coordinates in the camera frame, so it does not move on screen.
export function orbit(position, pivot, from, to) {
  const a = basis(from.yaw, from.pitch), b = basis(to.yaw, to.pitch), v = sub(position, pivot);
  const x = dot(v, a.right), y = dot(v, a.up), z = dot(v, a.forward);
  return [
    pivot[0] + x * b.right[0] + y * b.up[0] + z * b.forward[0],
    pivot[1] + x * b.right[1] + y * b.up[1] + z * b.forward[1],
    pivot[2] + x * b.right[2] + y * b.up[2] + z * b.forward[2],
  ];
}

// Direction of the ray through a screen point. ndc: x right, y up, both in [-1, 1].
export function rayDirection(axes, ndcX, ndcY, tanHalfFov, aspect) {
  const sx = ndcX * tanHalfFov * aspect, sy = ndcY * tanHalfFov;
  const d = [axes.forward[0] + sx * axes.right[0] + sy * axes.up[0],
             axes.forward[1] + sx * axes.right[1] + sy * axes.up[1],
             axes.forward[2] + sx * axes.right[2] + sy * axes.up[2]];
  const n = Math.hypot(d[0], d[1], d[2]);
  return [d[0] / n, d[1] / n, d[2] / n];
}

// Where a camera at `position` sees `point`: [ndcX, ndcY], or null if it is behind.
export function project(position, axes, point, tanHalfFov, aspect) {
  const v = sub(point, position), depth = dot(v, axes.forward);
  if (depth <= 0) return null;
  return [dot(v, axes.right) / (depth * tanHalfFov * aspect), dot(v, axes.up) / (depth * tanHalfFov)];
}

// Where a ray meets the horizontal plane at height y, or null (ray level, upwards, too far).
export function hitPlane(origin, dir, y, maxT = 40000) {
  if (dir[1] > -1e-3) return null;
  const t = (y - origin[1]) / dir[1];
  return t > 0 && t < maxT ? along(origin, dir, t) : null;
}

// Pan step: slide the camera horizontally so that the ray `dir` lands on `grab`
// (the ground point taken when the drag started). Null when the ray misses its plane.
export function panToGrab(position, dir, grab) {
  const hit = hitPlane(position, dir, grab[1]);
  return hit ? [position[0] + grab[0] - hit[0], position[1], position[2] + grab[2] - hit[2]] : null;
}

// Zoom step: scale the distance to `pivot` by `factor`, never closer than `minDistance`.
export function zoomAbout(position, pivot, factor, minDistance) {
  const d = distance(position, pivot);
  if (d < 1e-6) return position;
  const f = Math.max(factor, minDistance / d);
  return [pivot[0] + (position[0] - pivot[0]) * f, pivot[1] + (position[1] - pivot[1]) * f,
          pivot[2] + (position[2] - pivot[2]) * f];
}

// First point where a ray meets the terrain. heightAt(x, z) gives the ground height
// inside the square |x|, |z| <= half; outside it there is no ground. Null if it misses.
export function pickHeightfield(origin, dir, heightAt, half, maxT = 40000) {
  let t0 = 0, t1 = maxT;
  for (const axis of [0, 2]) {                      // clip the ray to the square
    if (Math.abs(dir[axis]) < 1e-9) {
      if (Math.abs(origin[axis]) > half) return null;
      continue;
    }
    let a = (-half - origin[axis]) / dir[axis], b = (half - origin[axis]) / dir[axis];
    if (a > b) [a, b] = [b, a];
    t0 = Math.max(t0, a); t1 = Math.min(t1, b);
  }
  if (t0 >= t1) return null;
  const above = t => origin[1] + dir[1] * t - heightAt(origin[0] + dir[0] * t, origin[2] + dir[2] * t);
  let t = t0, gap = above(t);
  if (gap <= 0) return along(origin, dir, t);       // enters through the side of the block
  for (let i = 0; i < 800 && t < t1; i++) {
    const next = Math.min(t1, t + Math.max(0.5, 0.4 * gap)), nextGap = above(next);
    if (nextGap <= 0) {                             // crossed the surface: bisect
      let lo = t, hi = next;
      for (let k = 0; k < 24; k++) {
        const mid = (lo + hi) / 2;
        if (above(mid) > 0) lo = mid; else hi = mid;
      }
      return along(origin, dir, hi);
    }
    t = next; gap = nextGap;
  }
  return null;
}

// Smallest signed difference between two angles (radians).
export function angleDelta(to, from) {
  let d = (to - from) % (2 * Math.PI);
  if (d > Math.PI) d -= 2 * Math.PI;
  if (d < -Math.PI) d += 2 * Math.PI;
  return d;
}
