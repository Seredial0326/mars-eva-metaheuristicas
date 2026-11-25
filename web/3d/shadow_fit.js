// Cast shadows of the 3D map (P1, issue #42, block 5): the numbers.
//
// The shadow map is drawn by an orthographic camera that looks along the sunlight.
// This file says which box that camera must see to hold the whole terrain block for a
// given Sun direction, how much ground one texel of the map covers, and when the Sun
// has moved enough to draw the map again. No three.js and no page here, so it is tested
// in Node (tests/viz3d/shadow_fit.test.mjs); shadows.js applies it to the light.
//
// Scene axes: X east, Y up, Z SOUTH. A direction is the unit vector TOWARDS the Sun.

const dot = (a, b) => a[0] * b[0] + a[1] * b[1] + a[2] * b[2];

// Axes of a camera that sits towards the Sun and looks at the scene, as three.js builds
// them (Matrix4.lookAt with up = +Y): `right` is horizontal and across the Sun's
// azimuth, `up` lies in the vertical plane of the Sun, `back` points to the Sun. With
// the Sun exactly overhead any horizontal axis would do; three.js takes east.
export function lightAxes(dir) {
  const h = Math.hypot(dir[0], dir[2]);
  const right = h === 0 ? [1, 0, 0] : [dir[2] / h, 0, -dir[0] / h];
  const up = [dir[1] * right[2] - dir[2] * right[1], dir[2] * right[0] - dir[0] * right[2],
              dir[0] * right[1] - dir[1] * right[0]];                       // back x right
  return {right, up, back: [dir[0], dir[1], dir[2]]};
}

// The eight corners of the block: X and Z within +-half, Y from yMin to yMax.
export function blockCorners({half, yMin, yMax}) {
  const corners = [];
  for (const x of [-half, half]) for (const y of [yMin, yMax]) for (const z of [-half, half]) corners.push([x, y, z]);
  return corners;
}

// Box of an orthographic camera placed `distance` metres from the block centre towards
// the Sun and looking at it: left, right, bottom, top (metres across the view) and near,
// far (metres from the camera). It is the bounding box of the block seen from the Sun
// plus `margin` metres on every side (a few texels, so the filter taps of the border
// stay inside) and `depthMargin` metres in depth.
export function fitShadowBox(dir, block, {distance = 5000, margin = 4, depthMargin = 10} = {}) {
  const {right, up, back} = lightAxes(dir);
  const lo = [Infinity, Infinity, Infinity], hi = [-Infinity, -Infinity, -Infinity];
  for (const corner of blockCorners(block)) {
    [right, up, back].forEach((axis, i) => {
      const v = dot(corner, axis);
      lo[i] = Math.min(lo[i], v); hi[i] = Math.max(hi[i], v);
    });
  }
  const fit = {left: lo[0] - margin, right: hi[0] + margin, bottom: lo[1] - margin, top: hi[1] + margin,
               near: distance - hi[2] - depthMargin, far: distance - lo[2] + depthMargin};
  return {...fit, width: fit.right - fit.left, height: fit.top - fit.bottom, depth: fit.far - fit.near};
}

// Ground covered by one texel of a square shadow map of `mapSize` texels, in metres:
// `across` the Sun's azimuth, and `along` it on level ground, where a texel is stretched
// by 1 / sin(elevation): the lower the Sun, the coarser its shadows.
export function groundTexel(fit, mapSize, dir) {
  return {across: fit.width / mapSize, along: fit.height / mapSize / Math.max(dir[1], 1e-6)};
}

// three.js adds the bias to a depth that goes from 0 at `near` to 1 at `far`; a negative
// value moves the lit point towards the light. This one is `metres` along the sunlight.
export function depthBias(fit, metres) {
  return -metres / fit.depth;
}

// Angle between two directions, in degrees.
export function angleDeg(a, b) {
  const cos = dot(a, b) / Math.sqrt(dot(a, a) * dot(b, b));
  return Math.acos(Math.min(1, Math.max(-1, cos))) * 180 / Math.PI;
}
