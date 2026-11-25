// Camera controls of the 3D map: an arcball that sits on the terrain.
//
// Everything is done to the ground point under the cursor (found by casting a ray
// against the height grid), so what you touch is what moves:
//   - rotate: the view turns around that point, which stays still on screen. The
//     horizon stays level (heading and tilt only, no roll).
//   - move:   the grabbed point follows the cursor; the camera keeps its altitude.
//   - zoom:   towards / away from that point, which stays under the cursor.
// Mouse: drag = rotate, right-drag or Shift+drag = move, wheel = zoom.
// Touch: one finger = rotate, two fingers = move, pinch = zoom, twist = turn.
// (leftDrag: 'pan' swaps the two drags: map style.)
// flyTo() moves the camera to a given pose with an eased flight (station cards now,
// rover photo poses later). While `enabled` is false (route rehearsal) the controls
// leave the camera alone.
import * as THREE from 'three';
import * as M from './camera_math.js';

const ROTATE_SPEED = 0.8;          // turns per screen height dragged, times 2 pi
const WHEEL_SPEED = 0.0012;        // zoom (log scale) per wheel pixel
const ZOOM_EASE = 14;              // 1/s: how fast a wheel step is absorbed
const MIN_DISTANCE = 4;            // m: closest approach to the zoom point
const CLEARANCE = 2;               // m: the camera stays this far above the ground
const MAX_RANGE = 7000;            // m: horizontal distance from the box centre
const MAX_ALTITUDE = 9000;         // m above the reference height
const MIN_POSE_HEIGHT = 0.3;       // m: lowest eye of a flyTo() pose
const MAX_POSE_PITCH = 89.5 * Math.PI / 180;       // a pose may look up; gestures may not

const ease = f => f * f * (3 - 2 * f);

export class TerrainControls {
  constructor(camera, dom, terrain, scene, {leftDrag = 'rotate'} = {}) {
    Object.assign(this, {camera, dom, terrain, leftDrag});
    this.position = [0, 0, 0];
    this.yaw = 0;
    this.pitch = Math.PI / 4;
    this.enabled = true;
    this.autoRotate = false;       // slow orbit around the box centre
    this.onChange = () => {};
    this._pointers = new Map();    // pointerId -> {x, y} in client pixels
    this._gesture = null;
    this._zoom = {log: 0, ndc: [0, 0], pivot: null};
    this._groundY = terrain.heightAt(0, 0);        // height used when a ray misses the terrain
    this._clearance = CLEARANCE;   // lower only while the camera rests on a flyTo() pose
    this._flight = null;           // {from, to, t, seconds} while flying
    this._changed = true;

    // Small ring on the ground at the point being rotated around.
    this.marker = new THREE.Mesh(
      new THREE.RingGeometry(0.72, 1, 40).rotateX(-Math.PI / 2),
      new THREE.MeshBasicMaterial({color: 0xff7a45, transparent: true, opacity: 0.95,
                                   depthTest: false, fog: false}));
    this.marker.renderOrder = 10;
    this.marker.visible = false;
    scene.add(this.marker);

    dom.style.cursor = 'grab';
    dom.addEventListener('pointerdown', e => this._down(e));
    dom.addEventListener('pointermove', e => this._move(e));
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      dom.addEventListener(type, e => this._up(e));
    }
    dom.addEventListener('wheel', e => this._wheel(e), {passive: false});
    dom.addEventListener('contextmenu', e => e.preventDefault());
  }

  // ---- public ------------------------------------------------------------------

  // Place the camera: position [x, y, z] in scene metres, heading and pitch in radians.
  setView(position, yaw, pitch) {
    this.position = [...position];
    this.yaw = yaw;
    this.pitch = M.clampPitch(pitch);
    this._zoom.log = 0;
    this._flight = null;
    this._clearance = CLEARANCE;
    this._apply();
  }

  // The whole state of the view, to put it back later exactly as it is now.
  pose() {
    return {position: [...this.position], yaw: this.yaw, pitch: this.pitch, fov: this.camera.fov,
            clearance: this._clearance};
  }

  restore(pose) {
    this.cancel();
    Object.assign(this, {position: [...pose.position], yaw: pose.yaw, pitch: pose.pitch, _clearance: pose.clearance});
    this.camera.fov = pose.fov;
    this.camera.updateProjectionMatrix();
    this._apply();
  }

  // Eased flight (about a second) to a pose: Mars position (x, y), eye height above the
  // shown ground there, heading, pitch (below the horizon; negative looks up) and
  // vertical field of view in degrees. A pose may be lower than the gestures allow and
  // may look above the horizon (a rover camera does both); the next gesture brings the
  // usual limits back. Any gesture stops the flight where it is.
  flyTo({x, y, eyeHeight = CLEARANCE, heading = this.yaw, pitch = this.pitch, fov = this.camera.fov,
         seconds = 1}) {
    const [X, Z] = this.terrain.toLocal(x, y), height = Math.max(MIN_POSE_HEIGHT, eyeHeight);
    this._zoom.log = 0;
    this._clearance = Math.min(CLEARANCE, height / 2);
    this._flight = {
      from: {position: [...this.position], yaw: this.yaw, pitch: this.pitch, fov: this.camera.fov},
      to: {position: [X, this.terrain.surfaceAt(X, Z) + height, Z], yaw: heading,
           pitch: Math.max(-MAX_POSE_PITCH, Math.min(MAX_POSE_PITCH, pitch)), fov},
      t: 0, seconds};
    if (!(seconds > 0)) this._fly(1);
    this._changed = true;
  }

  // Fly to where a ground point [X, Y, Z] (scene metres) is seen from `distance` metres
  // away. If the ground rises behind the point, the camera goes over it and tilts so
  // that the point stays at the centre.
  flyToLook(point, distance, {yaw = this.yaw, pitch = this.pitch, fov, seconds} = {}) {
    const eye = M.along(point, M.basis(yaw, M.clampPitch(pitch)).forward, -distance);
    const ground = this.terrain.surfaceAt(eye[0], eye[2]), height = Math.max(CLEARANCE, eye[1] - ground);
    const [x, y] = this.terrain.toMars(eye[0], eye[2]);
    this.flyTo({x, y, eyeHeight: height, heading: yaw, fov, seconds,
                pitch: Math.atan2(ground + height - point[1], Math.hypot(eye[0] - point[0], eye[2] - point[2]))});
  }

  // Drop whatever is going on: gestures, wheel easing and flights.
  cancel() {
    this._pointers.clear();
    this._gesture = null;
    this._zoom.log = 0;
    this._flight = null;
    this.dom.style.cursor = 'grab';
    this._showMarker(null);
  }

  // Look at a ground point from `distance` metres away.
  lookAt(point, distance, yaw = this.yaw, pitch = this.pitch) {
    const p = M.clampPitch(pitch);
    this.setView(M.along(point, M.basis(yaw, p).forward, -distance), yaw, p);
  }

  // Turn to face north around what is at the centre of the screen.
  faceNorth() {
    this._turn(this._pivotAt(null), {yaw: 0, pitch: this.pitch});
  }

  // Ground point at the centre of the screen (null when looking at the sky).
  centreGround() { return this.pick([0, 0]); }

  // Terrain point under a screen position (normalised device coordinates), or null
  // when the ray misses the terrain block.
  pickTerrain(ndc) {
    const hit = M.pickHeightfield(this.position, this._ray(ndc),
                                  (x, z) => this.terrain.heightAt(x, z), this.terrain.half);
    if (hit) this._groundY = hit[1];
    return hit;
  }

  // Same, but beyond the block it falls back to a flat plane at the last ground height.
  pick(ndc) {
    return this.pickTerrain(ndc) || M.hitPlane(this.position, this._ray(ndc), this._groundY);
  }

  // Back to the opening view: south of the box, looking north.
  home() {
    this.lookAt([0, this.terrain.heightAt(0, 0), 0], 2500, 0, 37 * Math.PI / 180);
  }

  // Call after the terrain changed height (relief slider): the camera is lifted if the
  // ground rose above it.
  refresh() { this._apply(); }

  // Call once per frame with the seconds elapsed. Returns true when the view changed.
  update(dt) {
    if (!this.enabled) return false;
    if (this._flight) this._fly(this._flight.t + dt / this._flight.seconds);
    if (this.autoRotate && !this._gesture && !this._flight) {
      const centre = [0, this.terrain.heightAt(0, 0), 0];
      this._turn(centre, {yaw: this.yaw + 0.2 * dt, pitch: this.pitch});
    }
    const z = this._zoom;
    if (Math.abs(z.log) > 1e-4 && z.pivot) {
      const step = z.log * (1 - Math.exp(-ZOOM_EASE * Math.min(dt, 0.1)));
      z.log -= step;
      const moved = M.zoomAbout(this.position, z.pivot, Math.exp(step), MIN_DISTANCE);
      if (this._inRange(moved)) { this.position = moved; this._apply(); } else z.log = 0;
    }
    const changed = this._changed;
    this._changed = false;
    return changed;
  }

  // ---- gestures ----------------------------------------------------------------

  _down(e) {
    if (!this.enabled) return;
    try { this.dom.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
    this._pointers.set(e.pointerId, {x: e.clientX, y: e.clientY});
    this._zoom.log = 0;
    this._limits();
    this._begin(e);
  }

  _begin(e) {
    const pts = [...this._pointers.values()];
    if (pts.length >= 2) {
      const [a, b] = pts, mid = {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2};
      this._gesture = {type: 'two', pivot: this._pivotAt(mid), mid,
                       spread: Math.hypot(a.x - b.x, a.y - b.y), angle: Math.atan2(b.y - a.y, b.x - a.x)};
    } else if (pts.length === 1) {
      const other = this.leftDrag === 'rotate' ? 'pan' : 'rotate';
      const swap = e && (e.button === 2 || e.button === 1 || e.shiftKey || e.ctrlKey);
      const type = swap ? other : this.leftDrag;
      // Moving can grab the flat plane around the block; rotating needs real terrain.
      const pivot = (type === 'pan' && this.pick(this._ndc(pts[0]))) || this._pivotAt(pts[0]);
      this._gesture = {type, pivot, last: {...pts[0]}};
    } else {
      this._gesture = null;
    }
    const type = this._gesture && this._gesture.type;
    this.dom.style.cursor = type ? 'grabbing' : 'grab';
    this._showMarker(type === 'rotate' || type === 'two' ? this._gesture.pivot : null);
  }

  _move(e) {
    const p = this._pointers.get(e.pointerId), g = this._gesture;
    if (!p || !g) return;
    p.x = e.clientX; p.y = e.clientY;
    if (g.type === 'rotate') {
      const scale = ROTATE_SPEED * 2 * Math.PI / this.dom.clientHeight;
      this._turn(g.pivot, {yaw: this.yaw + (p.x - g.last.x) * scale,
                           pitch: this.pitch + (p.y - g.last.y) * scale});
      g.last = {...p};
    } else if (g.type === 'pan') {
      this._slide(p, g.pivot);
    } else {
      const [a, b] = [...this._pointers.values()];
      const mid = {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2};
      const spread = Math.hypot(a.x - b.x, a.y - b.y), angle = Math.atan2(b.y - a.y, b.x - a.x);
      // Twisting clockwise on screen turns the ground clockwise: the heading decreases.
      this._turn(g.pivot, {yaw: this.yaw - M.angleDelta(angle, g.angle), pitch: this.pitch});
      const closer = M.zoomAbout(this.position, g.pivot, g.spread / Math.max(spread, 1), MIN_DISTANCE);
      if (this._inRange(closer)) { this.position = closer; this._apply(); }
      this._slide(mid, g.pivot);
      Object.assign(g, {mid, spread, angle});
    }
    this._showMarker(g.type === 'pan' ? null : g.pivot);
  }

  _up(e) {
    if (!this._pointers.delete(e.pointerId)) return;
    this._begin(null);             // carry on with the fingers that remain, from where they are
  }

  _wheel(e) {
    if (!this.enabled) return;
    e.preventDefault();
    this._limits();
    const pixels = e.deltaY * (e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1);
    const ndc = this._ndc({x: e.clientX, y: e.clientY}), z = this._zoom;
    // Keep the same zoom point while the wheel keeps turning over the same spot.
    if (!z.pivot || Math.abs(z.log) < 1e-4 || Math.hypot(ndc[0] - z.ndc[0], ndc[1] - z.ndc[1]) > 0.02) {
      z.pivot = this._pivotAt({x: e.clientX, y: e.clientY});
      z.ndc = ndc;
    }
    z.log += pixels * WHEEL_SPEED * (e.ctrlKey ? 6 : 1);          // ctrl = trackpad pinch
    z.log = Math.max(-3, Math.min(3, z.log));
    this._changed = true;
  }

  // ---- internals ---------------------------------------------------------------

  // A gesture starts: stop any flight, and if the camera rests on a flyTo() pose that is
  // lower or looks higher than the gestures allow, bring it within their limits where it
  // stands (otherwise the first rotation would swing it around a far pivot).
  _limits() {
    this._flight = null;
    if (this._clearance === CLEARANCE && this.pitch >= M.MIN_PITCH) return;
    this._clearance = CLEARANCE;
    this.pitch = M.clampPitch(this.pitch);
    this._apply();
  }

  // Flight at fraction t of its way (1 = arrived).
  _fly(t) {
    const f = this._flight, {from, to} = f, e = ease(Math.min(1, t));
    f.t = t;
    this.position = from.position.map((v, i) => v + (to.position[i] - v) * e);
    this.yaw = from.yaw + M.angleDelta(to.yaw, from.yaw) * e;       // the short way round
    this.pitch = from.pitch + (to.pitch - from.pitch) * e;
    this.camera.fov = from.fov + (to.fov - from.fov) * e;
    this.camera.updateProjectionMatrix();
    if (t >= 1) { this.yaw = to.yaw; this._flight = null; }
    this._apply();
  }

  _turn(pivot, to) {
    const target = {yaw: to.yaw, pitch: M.clampPitch(to.pitch)};
    this.position = M.orbit(this.position, pivot, {yaw: this.yaw, pitch: this.pitch}, target);
    this.yaw = target.yaw;
    this.pitch = target.pitch;
    this._apply();
  }

  _slide(pointer, grab) {
    const moved = M.panToGrab(this.position, this._ray(this._ndc(pointer)), grab);
    if (moved && this._inRange(moved)) { this.position = moved; this._apply(); }
  }

  // Point to rotate or zoom around: the terrain under the cursor; if the cursor is off
  // the terrain, the terrain at the centre of the screen; failing that, the box centre.
  // (Never a point in empty space: zooming into it would lose the terrain.)
  _pivotAt(pointer) {
    return (pointer && this.pickTerrain(this._ndc(pointer))) || this.pickTerrain([0, 0]) ||
           [0, this.terrain.heightAt(0, 0), 0];
  }

  _ndc(p) {
    const r = this.dom.getBoundingClientRect();
    return [(p.x - r.left) / r.width * 2 - 1, -((p.y - r.top) / r.height * 2 - 1)];
  }

  _ray(ndc) {
    const tan = Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2);
    return M.rayDirection(M.basis(this.yaw, this.pitch), ndc[0], ndc[1], tan, this.camera.aspect);
  }

  _inRange(p) {
    return Math.hypot(p[0], p[2]) <= MAX_RANGE && p[1] <= MAX_ALTITUDE;
  }

  _showMarker(pivot) {
    this.marker.visible = Boolean(pivot);
    if (pivot) {
      this.marker.position.set(pivot[0], pivot[1], pivot[2]);
      this.marker.scale.setScalar(Math.max(0.5, M.distance(this.position, pivot) * 0.012));
    }
    this._changed = true;
  }

  _apply() {
    if (!this.enabled) return;                                    // the rehearsal owns the camera
    const p = this.position, half = this.terrain.half;
    if (Math.abs(p[0]) <= half && Math.abs(p[2]) <= half) {       // never under the ground
      p[1] = Math.max(p[1], this.terrain.heightAt(p[0], p[2]) + this._clearance);
    }
    const {right, up, forward} = M.basis(this.yaw, this.pitch);
    this.camera.position.set(p[0], p[1], p[2]);
    this.camera.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3(...right), new THREE.Vector3(...up), new THREE.Vector3(...forward).negate()));
    this.camera.updateMatrixWorld();
    this._changed = true;
    this.onChange();
  }
}
