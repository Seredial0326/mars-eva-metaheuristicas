// Route of the plan drawn on the terrain (P1, issue #42, block 2).
//
// Every line of the plan (plan_model.js) becomes fat lines (Line2: width in pixels,
// whatever the distance):
//   - outbound leg in the 2D planner's route colour; return leg (after turn_index) in
//     another colour and shifted 0.8 m to the right of travel, so the two legs do not
//     hide each other where they follow the same cells;
//   - each leg is drawn twice: solid and depth-tested, plus a faint pass with no depth
//     test, so the route can be followed behind a knoll.
// The line is draped on the mesh: besides the route's own vertices (1 m apart at most)
// it gets a vertex wherever it crosses an edge of a terrain triangle, and every vertex
// sits on the drawn triangles (terrain.surfaceAt) plus a small lift. So the whole
// line, not only its vertices, is that lift above the ground. The shown height
// depends on the exaggeration k: call refresh() after terrain.setExaggeration().
import * as THREE from 'three';
import { Line2 } from 'three/addons/lines/Line2.js';
import { LineGeometry } from 'three/addons/lines/LineGeometry.js';
import { LineMaterial } from 'three/addons/lines/LineMaterial.js';
import { LineSegments2 } from 'three/addons/lines/LineSegments2.js';
import { LineSegmentsGeometry } from 'three/addons/lines/LineSegmentsGeometry.js';
import { ROUTE_COLOR, RETURN_COLOR, UNKNOWN_COLOR, densify, offsetSideways, splitAtTurn } from './plan_model.js';

const MAX_STEP = 1;                // m between route vertices
const LIFT = 0.3;                  // m above the ground
const RETURN_SHIFT = 0.8;          // m to the right of travel, return leg only
const WIDTH = 4;                   // CSS pixels
const GHOST_OPACITY = 0.3;         // the pass seen through the terrain

const css = ([r, g, b]) => new THREE.Color(`rgb(${r}, ${g}, ${b})`);

// Scene [X, Z, X, Z, ...] of a path in Mars metres, with one more point wherever a
// segment crosses a mesh column, a mesh row or the diagonal of a cell. Between two
// consecutive points the path stays on one triangle, where the ground is a plane.
export function drape(terrain, x, y) {
  const {half, first, step} = terrain, out = [];
  let [X0, Z0] = terrain.toLocal(x[0], y[0]);
  out.push(X0, Z0);
  for (let i = 1; i < x.length; i++) {
    const [X1, Z1] = terrain.toLocal(x[i], y[i]);
    // Position in mesh cells: u counts columns (east), w counts rows (south).
    const u0 = (X0 + half - first) / step, u1 = (X1 + half - first) / step;
    const w0 = (Z0 + half - first) / step, w1 = (Z1 + half - first) / step;
    const cuts = [];
    for (const [a, b] of [[u0, u1], [w0, w1], [u0 + w0, u1 + w1]]) {      // columns, rows, diagonals
      for (let c = Math.floor(Math.min(a, b)) + 1; c < Math.max(a, b); c++) cuts.push((c - a) / (b - a));
    }
    cuts.sort((p, q) => p - q);
    let last = 0;
    for (const t of cuts) {
      if (t - last < 1e-6 || 1 - t < 1e-6) continue;                      // same point again
      out.push(X0 + (X1 - X0) * t, Z0 + (Z1 - Z0) * t);
      last = t;
    }
    out.push(X1, Z1);
    X0 = X1; Z0 = Z1;
  }
  return Float64Array.from(out);
}

export class RouteOverlay {
  constructor(terrain, scene) {
    this.terrain = terrain;
    this.lift = LIFT;
    this.routes = [];              // [{route, dense, split}]: plan_model.js data, for later blocks
    // Legs drawn: {name, color, solid, ghost} plus
    //   x, y, at, dist  the route's vertices of this leg (Mars metres; plan_model.js)
    //   ground          scene [X, Z, ...] of the drawn line (those vertices + mesh crossings)
    //   positions       scene [X, Y, Z, ...] of the drawn line at the current exaggeration
    this.legs = [];
    this.group = new THREE.Group();
    this.group.name = 'route';
    this._size = [1, 1];
    scene.add(this.group);
  }

  // plan: the result of parsePlan(), or null to draw nothing.
  setPlan(plan) {
    this.clear();
    for (const route of (plan ? plan.routes : [])) {
      const dense = densify(route.coords, MAX_STEP);
      const split = splitAtTurn(dense, route.turnIndex);
      this.routes.push({route, dense, split});
      const [a, b] = split.outbound;
      this._addLeg('outbound', route.kind === 'route' ? ROUTE_COLOR : UNKNOWN_COLOR,
                   {x: dense.x.subarray(a, b + 1), y: dense.y.subarray(a, b + 1)}, dense, a);
      if (split.back) {
        this._addLeg('return', RETURN_COLOR, offsetSideways(dense, split.back, RETURN_SHIFT), dense, split.back[0]);
      }
    }
    this.refresh();
  }

  // Re-place every vertex on the ground as it is shown now.
  refresh() {
    const {terrain} = this;
    for (const leg of this.legs) {
      const n = leg.ground.length / 2, positions = new Float32Array(n * 3);
      for (let i = 0; i < n; i++) {
        const X = leg.ground[i * 2], Z = leg.ground[i * 2 + 1];
        positions[i * 3] = X;
        positions[i * 3 + 1] = terrain.surfaceAt(X, Z) + this.lift;
        positions[i * 3 + 2] = Z;
      }
      leg.positions = positions;
      // A new geometry each time: setPositions() on the old one would leave its
      // buffers on the GPU.
      const geometry = new LineGeometry();
      geometry.setPositions(positions);
      leg.solid.geometry.dispose();
      leg.solid.geometry = leg.ghost.geometry = geometry;
    }
  }

  // Canvas size in CSS pixels: the line width is measured against it. (three.js also
  // sets it when it draws a line; this keeps it right before the first frame.)
  setResolution(width, height) {
    this._size = [width, height];
    for (const leg of this.legs) {
      leg.solid.material.resolution.set(width, height);
      leg.ghost.material.resolution.set(width, height);
    }
  }

  clear() {
    for (const leg of this.legs) {
      leg.solid.geometry.dispose();
      leg.solid.material.dispose();
      leg.ghost.material.dispose();
    }
    this.group.clear();
    this.legs = [];
    this.routes = [];
  }

  // first: index of the leg's first vertex in the densified route (for `at` and `dist`).
  _addLeg(name, color, path, dense, first) {
    // Repeated vertices are dropped: a segment of zero length has no direction to draw.
    const keep = [];
    for (let i = 0; i < path.x.length; i++) {
      if (i === 0 || path.x[i] !== path.x[keep.at(-1)] || path.y[i] !== path.y[keep.at(-1)]) keep.push(i);
    }
    if (keep.length < 2) return;
    const take = (array, shift = 0) => Float64Array.from(keep, i => array[i + shift]);
    const leg = {name, color, x: take(path.x), y: take(path.y),
                 at: take(dense.at, first), dist: take(dense.dist, first), positions: null};
    leg.ground = drape(this.terrain, leg.x, leg.y);
    const base = {color: css(color), linewidth: WIDTH, worldUnits: false};
    leg.solid = new Line2(new LineGeometry(), new LineMaterial(base));
    // The 1 m segments overlap on screen: without the stencil test the faint pass
    // would add up to a solid line. Each leg marks the pixels it has already painted.
    const ref = this.legs.length + 1;
    leg.ghost = new Line2(leg.solid.geometry, new LineMaterial({
      ...base, transparent: true, opacity: GHOST_OPACITY, depthTest: false, depthWrite: false,
      stencilWrite: true, stencilRef: ref, stencilFunc: THREE.NotEqualStencilFunc,
      stencilZPass: THREE.ReplaceStencilOp}));
    leg.ghost.renderOrder = ref;
    for (const line of [leg.solid, leg.ghost]) {
      line.material.resolution.set(...this._size);
      line.frustumCulled = false;              // one object spanning the box: nothing to cull
      this.group.add(line);
    }
    this.legs.push(leg);
  }
}

// Any other lines on the ground (the walkback boundaries of the rehearsal): sets of
// polylines in Mars metres, each set with its colour and width, draped on the mesh like
// the route. One object per set, however many separate lines it has.
export class GroundLines {
  constructor(terrain, scene, name) {
    this.terrain = terrain;
    this.lift = LIFT;
    this.sets = [];                // [{ground: [Float64Array of scene X, Z, ...], mesh}]
    this.group = new THREE.Group();
    this.group.name = name;
    this._size = [1, 1];
    scene.add(this.group);
  }

  // sets: [{lines: [[[x, y], ...], ...], color: [r, g, b], width}] (width in CSS pixels).
  set(sets) {
    this.clear();
    for (const {lines, color, width} of sets) {
      const ground = lines.filter(line => line.length > 1)
                          .map(line => drape(this.terrain, line.map(c => c[0]), line.map(c => c[1])));
      if (!ground.length) continue;
      const mesh = new LineSegments2(new LineSegmentsGeometry(),
                                     new LineMaterial({color: css(color), linewidth: width, worldUnits: false}));
      mesh.material.resolution.set(...this._size);
      mesh.frustumCulled = false;
      this.group.add(mesh);
      this.sets.push({ground, mesh});
    }
    this.refresh();
  }

  // Re-place every vertex on the ground as it is shown now.
  refresh() {
    const {terrain} = this;
    for (const {ground, mesh} of this.sets) {
      const pairs = [];                        // segments: start and end of each, one after another
      for (const g of ground) {
        for (let i = 0; i + 3 < g.length; i += 2) {
          pairs.push(g[i], terrain.surfaceAt(g[i], g[i + 1]) + this.lift, g[i + 1],
                     g[i + 2], terrain.surfaceAt(g[i + 2], g[i + 3]) + this.lift, g[i + 3]);
        }
      }
      const geometry = new LineSegmentsGeometry();
      geometry.setPositions(pairs);
      mesh.geometry.dispose();
      mesh.geometry = geometry;
    }
  }

  setResolution(width, height) {
    this._size = [width, height];
    for (const {mesh} of this.sets) mesh.material.resolution.set(width, height);
  }

  clear() {
    for (const {mesh} of this.sets) { mesh.geometry.dispose(); mesh.material.dispose(); }
    this.group.clear();
    this.sets = [];
  }
}
