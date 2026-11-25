// Cast shadows of the 3D map (P1, issue #42, block 5): the shadow map of the sun light.
//
// three.js' own shadow maps, nothing else: the sun light draws the scene's depth seen
// from the Sun into a texture, and the terrain compares against it. The terrain casts
// and receives (terrain.js), the habitat dome casts (markers.js); pins and lines do
// neither. This file owns the light's shadow settings, the "Shadows" switch and the
// decision of WHEN the map is drawn again, which is never "every frame":
//   - the Sun moved more than REDRAW_DEG since the map was drawn (time slider, rehearsal),
//   - the relief changed, or the plan did (the dome): invalidate().
// The camera of the map is fitted to the whole block for the Sun's direction
// (shadow_fit.js). Shadows are those of the relief AS SHOWN: true only at relief x1.
import * as THREE from 'three';
import { angleDeg, depthBias, fitShadowBox, groundTexel } from './shadow_fit.js';

const MAP_SIZE = {high: 4096, low: 2048};   // texels per side
const REDRAW_DEG = 0.2;                     // a 100 m shadow moves 0.35 m: under one texel
const CASTER_HEIGHT = 5;                    // m above the ground: the habitat dome (4 m)
// The depth map holds the faces turned away from the Sun (three.js' default for a
// one-sided material), so sunlit ground is never compared with itself: that is what
// keeps gentle slopes free of acne, not the bias. Measured with ?check=shadows, even
// with no bias under 0.01 % of the sunlit pixels away from shadow edges came out shaded.
// The bias is a guard for the facets that are compared with themselves (turned a few
// degrees away from the Sun while the smooth shading normal still lights them): only
// ground more than this far in front of a point shades it. In texels of the map, so it
// is about 0.9 m along the light in the high preset and 1.7 m in the low one. More
// only detaches shadows from what casts them; normalBias stays 0 (not needed).
const BIAS_TEXELS = 1.5;

const el = id => document.getElementById(id);

export class Shadows {
  // sun: the DirectionalLight; onChange(): something to draw.
  constructor({renderer, scene, sun, terrain, enabled = true, onChange = () => {}}) {
    Object.assign(this, {renderer, sun, terrain, onChange});
    this.mapSize = MAP_SIZE[terrain.quality] || MAP_SIZE.low;
    this.biasTexels = BIAS_TEXELS;
    this.updates = 0;                       // times the map was drawn (for the checks)
    this.block = null;                      // what the map covers: {half, yMin, yMax} as shown
    this.fit = null;                        // shadow_fit.fitShadowBox() of the map as drawn
    this.texel = null;                      // ground metres per texel: {across, along}
    this.biasM = 0;                         // the bias in metres along the light
    this._drawn = null;                     // Sun direction of the map as drawn
    this._stale = true;

    renderer.shadowMap.enabled = true;
    renderer.shadowMap.type = THREE.PCFShadowMap;
    renderer.shadowMap.autoUpdate = false;  // drawn when prepare() says so
    sun.shadow.mapSize.set(this.mapSize, this.mapSize);
    // Every render of the scene (the page's frames and the checks' own) first asks
    // whether the map is still good; three.js draws it right after this call.
    scene.onBeforeRender = () => this.prepare();

    el('shadows').addEventListener('change', e => this.set(e.target.checked));
    this.set(enabled);
  }

  get enabled() { return this.sun.castShadow; }

  // Switch the shadows. Off is the page as it was before this block: a light that
  // casts no shadow compiles the same programs as before.
  set(on) {
    on = Boolean(on);
    el('shadows').checked = on;
    if (on === this.sun.castShadow) return;
    this.sun.castShadow = on;
    this._stale = true;
    this.onChange();
  }

  // What casts or receives changed shape or place: the next frame draws the map again.
  invalidate() { this._stale = true; }

  // Called before every render. Fits the map's camera and asks three.js to draw the map
  // when it is stale or the Sun has moved enough; otherwise the map of the last time is
  // used as it is, with the camera it was drawn with.
  prepare() {
    const {sun, terrain} = this;
    if (!sun.castShadow || sun.intensity <= 0) return;     // off, or night: nothing to shade
    const to = sun.position.clone().sub(sun.target.position), distance = to.length();
    const dir = to.divideScalar(distance).toArray();
    if (dir[1] <= 0) return;
    if (!this._stale && angleDeg(dir, this._drawn) < REDRAW_DEG) return;

    let yMin = Infinity, yMax = -Infinity;                 // of the relief as shown now
    for (const mesh of terrain.group.children) {
      yMin = Math.min(yMin, mesh.geometry.boundingBox.min.y);
      yMax = Math.max(yMax, mesh.geometry.boundingBox.max.y);
    }
    this.block = {half: terrain.half, yMin, yMax: yMax + CASTER_HEIGHT};
    const fit = this.fit = fitShadowBox(dir, this.block, {distance});
    const camera = sun.shadow.camera;
    Object.assign(camera, {left: fit.left, right: fit.right, bottom: fit.bottom, top: fit.top, near: fit.near, far: fit.far});
    camera.updateProjectionMatrix();
    this.texel = groundTexel(fit, this.mapSize, dir);
    this.biasM = this.biasTexels * Math.max(fit.width, fit.height) / this.mapSize;
    sun.shadow.bias = depthBias(fit, this.biasM);

    this.renderer.shadowMap.needsUpdate = true;
    this._drawn = dir;
    this._stale = false;
    this.updates++;
  }
}
