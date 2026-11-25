// "Walk freely" mode of the 3D map (issue #109).
//
// Walk anywhere in the box at eye height, like a game: W/S or Up/Down walk forward/back,
// A/D step sideways and Left/Right turn. The mouse looks (click the view to capture it;
// Esc frees it, a second Esc leaves). Shift runs, F toggles fast travel, C the view from
// behind. On a touch screen an arrow pad moves the walker, buttons switch modes, and
// dragging looks around. The rehearsal (which walks the route on its own clock) is a
// separate mode and is not changed by this one.
// The numbers (speeds, limits, distance to the route) come from walk_model.js; this file
// owns what the mode does to the page while it is on, and puts everything back on exit:
//   - camera: first person, the eye EYE_HEIGHT above the ground; "Chase view" shows the
//     astronaut (astronaut.js) from behind and above. The free-flight controls are off
//     and the near plane comes in, as in the rehearsal.
//   - relief: forced to true scale, as in the rehearsal (eye height and slopes are real).
//   - the route: drawn as a path on the ground (80 cm wide, each leg in its colour) and
//     every station as a ring with a flag, as a walker would see them; the free-flight
//     route lines are hidden meanwhile.
//   - limits: never out of the box (1 m from its edge) nor into the habitat dome.
// Nothing is rendered here: update(dt) says whether the view changed, and main.js draws.
import * as THREE from 'three';
import * as M from './camera_math.js';
import { createAstronaut, disposeAstronaut, poseAstronaut, ANCHOR_HEIGHT } from './astronaut.js';
import { FOV, NEAR } from './rehearse.js';
import * as W from './walk_model.js';

const DEG = Math.PI / 180;
export const RELIEF_REASON = 'Relief at true scale while walking (eye height is real)';
const START_PITCH = 6 * DEG;       // first person starts looking a little down, at the path ahead
const PATH_HALF_WIDTH = 0.4;       // m: the route as an 80 cm path
const PATH_LIFT = 0.08;            // m above the ground (plus a depth offset): no flicker
const PATH_OPACITY = 0.6;
const RING = [2.2, 2.8];           // m: inner and outer radius of a station's ring
const POLE = 2.4;                  // m: height of a station's flag pole
const DOME_RADIUS = 4;             // m: the habitat dome of markers.js
const CHASE_BACK = 6, CHASE_UP = 2.5;      // m behind the walker and above its ground
const CHASE_TARGET = 1.2;          // m above the ground: the camera looks at the chest
const CHASE_TILT = Math.atan2(CHASE_UP - CHASE_TARGET, CHASE_BACK);
const CHASE_RANGE = Math.hypot(CHASE_UP - CHASE_TARGET, CHASE_BACK);
const CHASE_PITCH = [3 * DEG, 80 * DEG];
const CHASE_FLOOR = 2;             // m: the chase camera stays this far above the ground
const MAX_FRAME = 0.1;             // s: a frame never counts for more (tab in the background)
const SWING = 0.3;                 // rad: leg swing; the legs are stiff, so more lifts the feet
const WALK_CODES = new Set(Object.values(W.KEYS).flat());
const PAD = ['forward', 'back', 'left', 'right'];

const el = id => document.getElementById(id);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));
const css = ([r, g, b]) => new THREE.Color(`rgb(${r}, ${g}, ${b})`);
// Typing a sol or a number: the keys are the field's, not the walker's.
const typing = t => Boolean(t && t.closest && t.closest('select, textarea, input:not([type=range]):not([type=checkbox])'));

export class Walk {
  // relief: {lock(reason), unlock(k)} from main.js; overlays: the RouteOverlay (its legs
  // are the route); markers: the plan's MarkerLayer (stations and the habitat).
  constructor({terrain, scene, camera, canvas, controls, relief, overlays, markers}) {
    Object.assign(this, {terrain, scene, camera, canvas, controls, relief, overlays, markers});
    this.active = false;
    this.chase = false;
    this.run = false;              // the "Run" button; Shift runs while held
    this.fast = false;
    this.position = [0, 0];        // scene [X, Z] of the walker
    this.yaw = 0;                  // where the walker looks: heading from north, and pitch
    this.pitch = START_PITCH;
    this.viewYaw = 0;              // heading of the camera itself, for the compass
    this.pose = null;              // {position: [X, Y, Z], yaw, pitch, ground} of the camera
    this.distance = 0;             // m walked since entering (drives the legs)
    this.toRoute = null;           // m to the nearest leg of the route, or null without one
    this.speedNow = 0;             // m/s of the last frame
    this.walker = null;            // the astronaut, seen only in the chase view
    this._keys = new Set();        // KeyboardEvent.code of the movement and turn keys held
    this._pad = new Set();         // pad buttons held
    this._shift = false;
    this._facing = 0;              // heading of the astronaut's body
    this._paths = [];              // route legs as [[X, Z], ...]
    this._listeners = [];
    this._drag = null;
    this._dirty = false;
    this._locked = false;          // the mouse captured (pointer lock) at the last change
    this._unlockedAt = -Infinity;  // when the browser last freed it

    // The bar's own controls. They are hidden outside the mode.
    for (const button of document.querySelectorAll('#walk-pad [data-walk]')) {
      const name = button.dataset.walk, release = e => {
        if (e.pointerId !== undefined && button.hasPointerCapture && button.hasPointerCapture(e.pointerId)) {
          button.releasePointerCapture(e.pointerId);
        }
        this.press(name, false);
      };
      button.addEventListener('pointerdown', e => {
        e.preventDefault();
        try { button.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
        this.press(name, true);
      });
      for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) button.addEventListener(type, release);
      button.addEventListener('contextmenu', e => e.preventDefault());       // a long press is not a menu
    }
    el('wk-run').addEventListener('click', () => this.setRun(!this.run));
    el('wk-fast').addEventListener('click', () => this.setFast(!this.fast));
    el('wk-chase').addEventListener('click', () => this.setChase(!this.chase));
    el('wk-exit').addEventListener('click', () => this.exit());
  }

  // ---- public ------------------------------------------------------------------

  // at: {position: [X, Z], yaw} to start somewhere else than next to the habitat.
  enter(at = null) {
    if (this.active) return false;
    const {controls, camera, terrain} = this;
    // Everything that exit() must put back.
    this._saved = {pose: controls.pose(), near: camera.near, relief: terrain.k, route: this.overlays.group.visible};
    controls.cancel();
    controls.enabled = false;
    this.relief.lock(RELIEF_REASON);
    camera.near = NEAR;
    camera.fov = FOV;
    camera.updateProjectionMatrix();
    if (document.activeElement && document.activeElement.blur) document.activeElement.blur();

    // The route and the stations as a walker sees them, instead of the map's lines.
    this._paths = this.overlays.legs.map(leg => {
      const points = [];
      for (let i = 0; i + 1 < leg.ground.length; i += 2) points.push([leg.ground[i], leg.ground[i + 1]]);
      return points;
    });
    this.ground = new THREE.Group();
    this.ground.name = 'walk ground';
    this.overlays.legs.forEach((leg, i) => {
      const mesh = this._pathMesh(this._paths[i], leg.color);
      if (mesh) this.ground.add(mesh);
    });
    const habitat = this.markers.items.find(it => it.marker.kind === 'habitat');
    for (const item of this.markers.items) if (item !== habitat) this.ground.add(this._stationMark(item));
    this.scene.add(this.ground);
    this.overlays.group.visible = false;
    this._limits = {half: terrain.half,
                    circles: habitat ? [{x: habitat.position[0], z: habitat.position[2], r: DOME_RADIUS}] : []};

    // Where to start: next to the habitat, facing the way the route leaves it; with no
    // plan, at the ground point in the middle of the screen.
    let start = at;
    if (!start) {
      const centre = controls.centreGround();
      const inside = centre && Math.abs(centre[0]) <= terrain.half && Math.abs(centre[2]) <= terrain.half;
      start = W.startPose({habitat: habitat ? [habitat.position[0], habitat.position[2]] : null,
                           path: this._paths[0] || null, domeRadius: DOME_RADIUS,
                           fallback: inside ? [centre[0], centre[2]] : [0, 0], fallbackYaw: controls.yaw});
    }
    this.position = W.constrain(start.position, this._limits);
    this.yaw = start.yaw;
    this._facing = start.yaw;
    this.pitch = START_PITCH;
    this.distance = 0;
    this.speedNow = 0;
    this._keys.clear();
    this._pad.clear();
    this._shift = false;
    this.chase = false;
    this.setRun(false);
    this.setFast(false);

    this.walker = createAstronaut();
    this.walker.visible = false;
    this.scene.add(this.walker);

    this._listen(window, 'keydown', e => this._key(e, true));
    this._listen(window, 'keyup', e => this._key(e, false));
    this._listen(window, 'blur', () => { this._keys.clear(); this._pad.clear(); this._shift = false; });
    this._listen(this.canvas, 'pointerdown', e => this._down(e));
    this._listen(this.canvas, 'pointermove', e => this._move(e));
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      this._listen(this.canvas, type, e => { if (this._drag && this._drag.id === e.pointerId) this._drag = null; });
    }
    this._listen(document, 'pointerlockchange', () => this._lockChanged());
    // Some browsers or embedded views refuse to capture the mouse: say what works instead.
    this._listen(document, 'pointerlockerror', () => { el('wk-hint').textContent = 'Drag the view to look around'; });

    this.active = true;
    this._locked = false;
    this._unlockedAt = -Infinity;
    document.body.classList.add('walking');
    el('walk-bar').hidden = false;
    el('walk').textContent = 'Exit walk';
    el('wk-chase').setAttribute('aria-pressed', 'false');
    this._lockChanged();
    this._place();
    this._dirty = true;
    return true;
  }

  // Back to free flight exactly as it was: camera view, field of view, relief, route lines.
  exit() {
    if (!this.active) return false;
    const {controls, camera} = this, saved = this._saved;
    for (const [target, type, handler] of this._listeners) target.removeEventListener(type, handler);
    this._listeners = [];
    if (document.pointerLockElement === this.canvas && document.exitPointerLock) document.exitPointerLock();
    this._drag = null;
    this._keys.clear();
    this._pad.clear();
    disposeAstronaut(this.walker);
    this.walker = null;
    this.scene.remove(this.ground);
    this.ground.traverse(o => { if (o.geometry) o.geometry.dispose(); if (o.material) o.material.dispose(); });
    this.ground = null;
    this.overlays.group.visible = saved.route;
    this.active = false;
    this.pose = null;
    document.body.classList.remove('walking');
    el('walk-bar').hidden = true;
    el('walk').textContent = 'Walk freely';
    camera.near = saved.near;
    this.relief.unlock(saved.relief);          // the ground first: the saved camera height belongs to it
    controls.enabled = true;
    controls.restore(saved.pose);              // also puts the field of view back
    return true;
  }

  setChase(on) {
    this.chase = Boolean(on);
    el('wk-chase').setAttribute('aria-pressed', String(this.chase));
    this._dirty = true;
  }

  setRun(on) {
    this.run = Boolean(on);
    el('wk-run').setAttribute('aria-pressed', String(this.run));
  }

  setFast(on) {
    this.fast = Boolean(on);
    el('wk-fast').setAttribute('aria-pressed', String(this.fast));
  }

  // A pad button ('forward', 'back', 'left', 'right') held or released.
  press(name, down) {
    if (!PAD.includes(name)) return;
    if (down) this._pad.add(name); else this._pad.delete(name);
  }

  get mode() { return this.fast ? 'fast' : this.run || this._shift ? 'run' : 'walk'; }

  // One frame: turn and move with the keys held, place the camera. True when the view changed.
  update(dt) {
    if (!this.active) return false;
    const step = Math.min(Math.max(dt, 0), MAX_FRAME);
    const yaw = W.turn(this.yaw, this._keys, step);
    if (yaw !== this.yaw) {
      this.yaw = yaw;
      this._facing = yaw;
      this._dirty = true;                       // turning on the spot also needs a frame
    }
    const axes = W.moveAxes([...this._keys, ...this._pad]);
    const speed = W.speedOf({run: this.run || this._shift, fast: this.fast});
    let moved = 0;
    if ((axes.forward || axes.right) && step > 0) {
      const from = this.position, got = W.step(from, this.yaw, axes, speed, step, this._limits);
      moved = got.moved;
      if (moved > 1e-9) {
        const dX = got.position[0] - from[0], dZ = got.position[1] - from[1];
        // The body turns to where it walks; walking backwards it keeps facing forward.
        this._facing = axes.forward >= 0 ? Math.atan2(dX, -dZ) : this.yaw;
        this.position = got.position;
        this.distance += moved;
      }
    }
    this.speedNow = step > 0 ? moved / step : 0;
    if (!moved && !this._dirty) return false;
    this._place();
    this._dirty = false;
    return true;
  }

  // The readout line: speed and distance to the route.
  positionText() {
    return W.readoutText({speed: W.speedOf({run: this.run || this._shift, fast: this.fast}),
                          mode: this.mode, toRoute: this.toRoute});
  }

  // ---- camera ------------------------------------------------------------------

  _place() {
    const {terrain, camera} = this, [X, Z] = this.position, ground = terrain.surfaceAt(X, Z);
    let position, yaw = this.yaw, pitch;
    if (this.chase) {
      const target = [X, ground + CHASE_TARGET, Z];
      const tilt = clamp(CHASE_TILT + this.pitch, ...CHASE_PITCH);
      position = M.along(target, M.basis(yaw, tilt).forward, -CHASE_RANGE);
      // A slope behind the walker: the camera rides over it and keeps looking at the walker.
      position[1] = Math.max(position[1], terrain.surfaceAt(position[0], position[2]) + CHASE_FLOOR);
      pitch = Math.atan2(position[1] - target[1], Math.hypot(position[0] - X, position[2] - Z));
    } else {
      position = [X, ground + W.EYE_HEIGHT, Z];
      pitch = this.pitch;
    }
    const {right, up, forward} = M.basis(yaw, pitch);
    camera.position.set(position[0], position[1], position[2]);
    camera.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3(...right), new THREE.Vector3(...up), new THREE.Vector3(...forward).negate()));
    camera.updateMatrixWorld();
    this.viewYaw = yaw;
    this.pose = {position, yaw, pitch, ground};

    this.walker.visible = this.chase;
    this.walker.position.set(X, ground + ANCHOR_HEIGHT, Z);
    poseAstronaut(this.walker, {yaw: this._facing,
                                swing: this.speedNow > 0 ? W.swing(this.distance, {amplitude: SWING}) : 0});
    let best = null;
    for (const path of this._paths) {
      const near = W.nearestOnPath(this.position, path);
      if (near && (best === null || near.distance < best)) best = near.distance;
    }
    this.toRoute = best;
  }

  // ---- what is drawn on the ground -----------------------------------------------

  // A leg of the route as a flat strip on the ground, in the leg's colour.
  _pathMesh(points, color) {
    const {left, right} = W.ribbon(points, PATH_HALF_WIDTH), n = left.length;
    if (n < 2) return null;
    const positions = new Float32Array(n * 6), index = [];
    for (let i = 0; i < n; i++) {
      for (const [j, [X, Z]] of [[0, left[i]], [1, right[i]]]) {
        positions.set([X, this.terrain.surfaceAt(X, Z) + PATH_LIFT, Z], (2 * i + j) * 3);
      }
      if (i) { const a = 2 * (i - 1); index.push(a, a + 1, a + 2, a + 1, a + 3, a + 2); }
    }
    const geometry = new THREE.BufferGeometry();
    geometry.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    geometry.setIndex(index);
    const mesh = new THREE.Mesh(geometry, new THREE.MeshBasicMaterial({
      color: css(color), transparent: true, opacity: PATH_OPACITY, depthWrite: false, side: THREE.DoubleSide,
      polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4}));
    mesh.name = 'walk path';
    mesh.frustumCulled = false;                // one object along the whole route
    return mesh;
  }

  // A station as a walker finds it: a ring on the ground and a flag in its colour.
  _stationMark(item) {
    const [X, , Z] = item.position, color = css(item.marker.color || [200, 200, 200]);
    const dimmed = item.marker.data && item.marker.data.visited === false;
    const group = new THREE.Group();
    group.name = 'walk station';
    const segments = 48, positions = new Float32Array((segments + 1) * 6), index = [];
    for (let s = 0; s <= segments; s++) {
      const a = s / segments * 2 * Math.PI, c = Math.cos(a), d = Math.sin(a);
      RING.forEach((r, j) => {
        const x = X + r * c, z = Z + r * d;
        positions.set([x, this.terrain.surfaceAt(x, z) + PATH_LIFT, z], (2 * s + j) * 3);
      });
      if (s) { const b = 2 * (s - 1); index.push(b, b + 1, b + 2, b + 1, b + 3, b + 2); }
    }
    const ring = new THREE.BufferGeometry();
    ring.setAttribute('position', new THREE.BufferAttribute(positions, 3));
    ring.setIndex(index);
    const paint = new THREE.MeshBasicMaterial({color, transparent: true, opacity: dimmed ? 0.35 : 0.8,
                                               depthWrite: false, side: THREE.DoubleSide,
                                               polygonOffset: true, polygonOffsetFactor: -2, polygonOffsetUnits: -4});
    group.add(new THREE.Mesh(ring, paint));
    const ground = this.terrain.surfaceAt(X, Z);
    const pole = new THREE.Mesh(new THREE.CylinderGeometry(0.03, 0.03, POLE, 8),
                                new THREE.MeshLambertMaterial({color: 0xdddddd}));
    pole.position.set(X, ground + POLE / 2, Z);
    const flag = new THREE.Mesh(new THREE.PlaneGeometry(0.7, 0.45),
                                new THREE.MeshBasicMaterial({color, side: THREE.DoubleSide,
                                                             transparent: dimmed, opacity: dimmed ? 0.5 : 1}));
    flag.position.set(X + 0.35, ground + POLE - 0.25, Z);
    group.add(pole, flag);
    return group;
  }

  // ---- input (only while walking) -------------------------------------------------

  _listen(target, type, handler) {
    target.addEventListener(type, handler);
    this._listeners.push([target, type, handler]);
  }

  _key(e, down) {
    if (e.ctrlKey || e.metaKey || e.altKey || typing(e.target)) return;
    if (e.code === 'ShiftLeft' || e.code === 'ShiftRight') { this._shift = down; return; }
    this._shift = e.shiftKey;
    if (WALK_CODES.has(e.code)) {
      if (down) this._keys.add(e.code); else this._keys.delete(e.code);
      e.preventDefault();                      // an arrow on a slider would move it too
      return;
    }
    if (!down || e.repeat) return;
    if (e.code === 'KeyF') this.setFast(!this.fast);
    else if (e.code === 'KeyC') this.setChase(!this.chase);
    else if (e.code === 'Escape') {
      // With the mouse captured, the browser takes the first Escape to free it: only a
      // second one leaves the mode.
      if (document.pointerLockElement === this.canvas || performance.now() - this._unlockedAt < 300) return;
      this.exit();
    }
  }

  _down(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    // A mouse click captures the mouse to look around; touch and pen drag to look.
    if (e.pointerType === 'mouse' && this.canvas.requestPointerLock && document.pointerLockElement !== this.canvas) {
      try {
        const asked = this.canvas.requestPointerLock();
        if (asked && asked.catch) asked.catch(() => {});        // refused: dragging still works
      } catch { /* not allowed here: dragging still works */ }
    }
    try { this.canvas.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
    this._drag = {id: e.pointerId, x: e.clientX, y: e.clientY};
  }

  _move(e) {
    if (document.pointerLockElement === this.canvas) {          // captured mouse: look like a game
      this._look(e.movementX || 0, e.movementY || 0, W.LOOK_RAD_PER_PX);
      return;
    }
    const d = this._drag;
    if (!d || d.id !== e.pointerId) return;
    // Dragging moves the scene with the finger, as in the rehearsal: drag right to look left.
    const scale = this.camera.fov * DEG / this.canvas.clientHeight;
    this._look(-(e.clientX - d.x), -(e.clientY - d.y), scale);
    d.x = e.clientX; d.y = e.clientY;
  }

  _look(dx, dy, radPerPx) {
    if (!dx && !dy) return;
    // In the chase view moving the mouse down raises the camera (it looks down at the walker).
    const got = W.look(this.yaw, this.pitch, dx, dy, radPerPx);
    this.yaw = got.yaw;
    this.pitch = got.pitch;
    this._dirty = true;
  }

  _lockChanged() {
    const locked = document.pointerLockElement === this.canvas;
    if (this._locked && !locked) this._unlockedAt = performance.now();     // the Escape that freed it
    this._locked = locked;
    this._drag = null;
    el('wk-hint').textContent = locked
      ? 'Mouse captured: move it to look · Esc frees it'
      : 'Click the view to look with the mouse';
  }
}
