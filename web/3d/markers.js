// Markers on the terrain (P1, issue #42, block 2): stations, goal and habitat.
//
// A generic layer: give it a list of {id, x, y, kind, label, color, data} (x, y in
// Mars CRS metres, color as [r, g, b]) and it draws, for each one, a pin: a thin pole
// standing on the ground point with the label on top. The pin is a sprite of constant
// size on screen (the same pixels from 5 m or from 5 km) and is never hidden by the
// terrain, like the labels of a map. Kinds with a special look:
//   'goal'     highlighted: filled label, larger, taller pole
//   'habitat'  also a white dome about 8 m across standing on the ground; it casts a shadow
// A marker whose data.visited is false (a station the tour skipped) is dimmed.
// pick() finds the marker under a screen point; select() calls onSelect(marker), the
// hook for later blocks (station card, rover photos).
import * as THREE from 'three';

const TEXTURE_SCALE = 2;           // canvas pixels per CSS pixel: sharp on dense screens
const DOME_RADIUS = 4;             // m
const STYLE = {                    // font: label size in CSS pixels, 12 or more (#124)
  station: {font: 12, pole: 22, filled: false},
  goal: {font: 14, pole: 34, filled: true},
  habitat: {font: 12, pole: 14, filled: false},
  point: {font: 12, pole: 16, filled: false},
  photo: {font: 12, pole: 10, filled: false},     // rover photo stops (P3): short, under the stations
};
const PANEL = 'rgba(16, 20, 26, 0.9)';     // the page's panel colour

// Draws the pin into a canvas. Returns the texture, its size in CSS pixels, where the
// ground point is inside it (fraction of the height, from the bottom) and which canvas
// pixels are painted (for picking: the sprite is a rectangle, the pin is not).
function pinTexture(label, color, style) {
  const s = TEXTURE_SCALE, rgb = `rgb(${color.join(',')})`;
  const font = `600 ${style.font * s}px system-ui, -apple-system, "Segoe UI", sans-serif`;
  const canvas = document.createElement('canvas');
  let ctx = canvas.getContext('2d');
  ctx.font = font;
  const padX = 6 * s, boxH = (style.font + 8) * s, dot = 3 * s, border = (style.filled ? 2.5 : 1.5) * s;
  const boxW = label ? Math.ceil(ctx.measureText(label).width) + 2 * padX : 0;
  const width = Math.max(boxW, 2 * dot) + 2 * border + 2 * s;
  const height = (label ? boxH + border : 0) + style.pole * s + dot + s;
  canvas.width = width; canvas.height = height;
  ctx = canvas.getContext('2d');
  const cx = width / 2, groundY = height - dot - s / 2, boxTop = border / 2;

  // Pole and ground dot, with a dark edge so they read on bright ground.
  ctx.lineCap = 'round';
  for (const [stroke, w] of [['rgba(0, 0, 0, 0.75)', 3.5 * s], [rgb, 1.5 * s]]) {
    ctx.strokeStyle = stroke; ctx.lineWidth = w;
    ctx.beginPath(); ctx.moveTo(cx, label ? boxTop + boxH : s); ctx.lineTo(cx, groundY); ctx.stroke();
  }
  ctx.fillStyle = 'rgba(0, 0, 0, 0.75)';
  ctx.beginPath(); ctx.arc(cx, groundY, dot, 0, 2 * Math.PI); ctx.fill();
  ctx.fillStyle = rgb;
  ctx.beginPath(); ctx.arc(cx, groundY, dot - s, 0, 2 * Math.PI); ctx.fill();

  if (label) {
    ctx.beginPath();
    ctx.roundRect(cx - boxW / 2, boxTop, boxW, boxH, 4 * s);
    ctx.fillStyle = style.filled ? rgb : PANEL;
    ctx.fill();
    ctx.strokeStyle = style.filled ? 'rgba(0, 0, 0, 0.85)' : rgb;
    ctx.lineWidth = border;
    ctx.stroke();
    ctx.font = font; ctx.textAlign = 'center'; ctx.textBaseline = 'middle';
    ctx.fillStyle = style.filled ? '#0b0d10' : '#ffffff';
    ctx.fillText(label, cx, boxTop + boxH / 2 + s);
  }
  const rgba = ctx.getImageData(0, 0, width, height).data;
  const painted = Uint8Array.from({length: width * height}, (_, i) => (rgba[i * 4 + 3] > 40 ? 1 : 0));
  const texture = new THREE.CanvasTexture(canvas);
  texture.colorSpace = THREE.SRGBColorSpace;
  texture.generateMipmaps = false;
  texture.minFilter = THREE.LinearFilter;
  return {texture, width: width / s, height: height / s, anchor: 1 - groundY / height,
          painted, columns: width, rows: height};
}

// Is the pin painted near a point of its sprite (uv)? A few pixels of slack.
function painted(pin, uv) {
  const col = Math.round(uv.x * pin.columns), row = Math.round((1 - uv.y) * pin.rows);
  const slack = 3 * TEXTURE_SCALE;
  for (let r = Math.max(0, row - slack); r <= Math.min(pin.rows - 1, row + slack); r += 2) {
    for (let c = Math.max(0, col - slack); c <= Math.min(pin.columns - 1, col + slack); c += 2) {
      if (pin.painted[r * pin.columns + c]) return true;
    }
  }
  return false;
}

export class MarkerLayer {
  constructor(terrain, scene, camera) {
    Object.assign(this, {terrain, camera});
    this.items = [];               // [{marker, sprite, dome, size, position}]
    this.selected = null;
    this.onSelect = null;          // function (marker), called by select()
    this.group = new THREE.Group();
    this.group.name = 'markers';
    this._viewHeight = 1;
    this._raycaster = new THREE.Raycaster();
    this._dome = new THREE.SphereGeometry(DOME_RADIUS, 32, 12, 0, 2 * Math.PI, 0, Math.PI / 2);
    scene.add(this.group);
  }

  // Replace all markers. list: [{id, x, y, kind, label, color, data}].
  set(list) {
    this.clear();
    for (const marker of list) {
      const pin = pinTexture(marker.label || '', marker.color || [200, 200, 200],
                             STYLE[marker.kind] || STYLE.point);
      const dimmed = marker.data && marker.data.visited === false;
      const sprite = new THREE.Sprite(new THREE.SpriteMaterial({
        map: pin.texture, sizeAttenuation: false, depthTest: false, depthWrite: false,
        transparent: true, opacity: dimmed ? 0.5 : 1, fog: false}));
      sprite.center.set(0.5, pin.anchor);
      sprite.renderOrder = marker.kind === 'photo' ? 19 : 20;   // after the route's faint pass; photos under stations
      sprite.userData.marker = marker;
      sprite.userData.pin = pin;
      const item = {marker, sprite, dome: null, size: [pin.width, pin.height], position: [0, 0, 0]};
      if (marker.kind === 'habitat') {
        // It casts a shadow (shadows.js) with its sunlit side: the shadow map's bias would
        // leave a gap behind the dome if its far side were the one that counted.
        item.dome = new THREE.Mesh(this._dome, new THREE.MeshStandardMaterial({
          color: 0xffffff, roughness: 0.7, shadowSide: THREE.FrontSide}));
        item.dome.castShadow = true;
        item.dome.userData.marker = marker;
        this.group.add(item.dome);
      }
      this.group.add(sprite);
      this.items.push(item);
    }
    this.refresh();
    this._scale();
  }

  // Re-place every marker on the ground as it is shown now (after the relief changes).
  refresh() {
    const {terrain} = this;
    for (const item of this.items) {
      const [X, Z] = terrain.toLocal(item.marker.x, item.marker.y);
      let Y = terrain.surfaceAt(X, Z);
      item.position = [X, Y, Z];               // the ground point of the marker
      if (item.dome) {
        // The dome stands on the lowest ground under its rim, so no side floats on a
        // slope; its label goes on top of it.
        let base = Y;
        for (let a = 0; a < 8; a++) {
          base = Math.min(base, terrain.surfaceAt(X + DOME_RADIUS * Math.cos(a * Math.PI / 4),
                                                  Z + DOME_RADIUS * Math.sin(a * Math.PI / 4)));
        }
        item.dome.position.set(X, base, Z);
        Y = base + DOME_RADIUS;
      }
      item.sprite.position.set(X, Y, Z);
    }
  }

  // Canvas size in CSS pixels: keeps the pins the same size on screen after a resize.
  setResolution(width, height) {
    this._viewHeight = height;
    this._scale();
  }

  // Marker under a screen point (normalised device coordinates), or null. Where pins
  // overlap, the nearest to the camera wins: it is the one drawn on top. Only the
  // painted part of a pin counts (label, pole and dot, with a few pixels of slack).
  pick(ndc) {
    return this.pickAll(ndc)[0] || null;
  }

  // Every marker under a screen point, nearest first (overlapping photo stops are offered
  // as a choice).
  pickAll(ndc) {
    if (!this.group.visible) return [];
    this.camera.updateMatrixWorld();
    this._raycaster.setFromCamera(new THREE.Vector2(ndc[0], ndc[1]), this.camera);
    const found = [];
    for (const hit of this._raycaster.intersectObjects(this.group.children, false)) {
      const {marker, pin} = hit.object.userData;
      if (found.includes(marker)) continue;
      if (!pin || painted(pin, hit.uv)) found.push(marker);      // no pin: the habitat dome
    }
    return found;
  }

  select(marker) {
    this.selected = marker;
    if (this.onSelect) this.onSelect(marker);
  }

  // Scene position [X, Y, Z] of a marker's ground point, by id.
  positionOf(id) {
    const item = this.items.find(it => it.marker.id === id);
    return item ? item.position : null;
  }

  clear() {
    for (const item of this.items) {
      item.sprite.material.map.dispose();
      item.sprite.material.dispose();
      if (item.dome) item.dome.material.dispose();
    }
    this.group.clear();
    this.items = [];
    this.selected = null;
  }

  // With sizeAttenuation off, a sprite of scale 1 is as tall as the view at distance 1.
  _scale() {
    const unit = 2 * Math.tan(THREE.MathUtils.degToRad(this.camera.fov) / 2) / this._viewHeight;
    for (const item of this.items) item.sprite.scale.set(item.size[0] * unit, item.size[1] * unit, 1);
  }
}
