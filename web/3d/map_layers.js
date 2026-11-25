// Map layers of the 2D planner draped on the 3D terrain (issue #110): the "Map layer"
// section of the panel and the layer drawn on the ground.
//
// One layer at a time, the same images as the HUD (map_layers_model.js has the list, the
// URLs and the legend data; this file draws them):
//   - nothing happens until a layer is picked: no request, nothing in the scene. The first
//     pick asks GET /layers (the box and the tile list) and builds the overlay.
//   - the overlay is a group of its own, 'map-layer', in the scene (never inside the
//     terrain's group, which the relief, the shadows and the checks read as terrain tiles
//     only). One mesh per terrain mesh, SHARING its geometry: the relief slider rewrites
//     the shared heights, so the layer follows with nothing to refresh. The terrain's UVs
//     cover the whole box (u east, v north) and the PNGs have row 0 north, so a texture
//     with flipY lands on the same 1 m cells.
//   - unlit (MeshBasicMaterial): the colours are the 2D legend's, and the shaded relief and
//     the shadows of the terrain under it show through the opacity.
//   - drawing order: after every opaque object (renderOrder 1 in the opaque list, through
//     CustomBlending with transparent false) and at the terrain's own depth (the same
//     polygon offset): it tints only the terrain pixels left visible, so the route, its
//     faint pass behind the hills, the pins and the dome look exactly as without it.
//   - the slope is not a /layers PNG: its 64 tiles (zoom 3, 1 m) are put together on one
//     canvas of the box, as the HUD shows them.
//   - switching layer frees the previous texture first (about 16 MB of GPU memory each),
//     and a load that finishes after another pick is thrown away.
//   - hidden while the photo view is on (body.photo-view), shown again on exit; it stays
//     on during the rehearsal.
// Text from the server goes in as text, never as HTML.
import * as THREE from 'three';
import { LAYERS, layerById, layerRequest, legendView, planHabitat, planSlopeLimit, sliderToOpacity,
         slopeTileGrid } from './map_layers_model.js';

const el = id => document.getElementById(id);

function make(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  return node;
}

// The words of an error answer: FastAPI's {detail: "..."} (or a list of {msg}), else the status.
async function errorText(res) {
  const body = await res.json().catch(() => null);
  const detail = body && body.detail;
  if (typeof detail === 'string') return detail;
  if (Array.isArray(detail) && detail.length) return detail.map(d => (d && d.msg) || String(d)).join('; ');
  return `HTTP ${res.status}`;
}

// An image from a same-origin URL, loaded: {image} or {error}. The load event, not
// decode(): a page that draws no frames (a hidden tab) never settles decode().
async function fetchImage(url) {
  let res;
  try { res = await fetch(url); } catch (err) { return {error: err.message}; }
  if (!res.ok) return {error: await errorText(res)};
  const blobUrl = URL.createObjectURL(await res.blob()), image = new Image();
  try {
    await new Promise((resolve, reject) => {
      image.onload = resolve;
      image.onerror = reject;
      image.src = blobUrl;
    });
    return {image};
  } catch {
    return {error: `${url}: not an image`};
  } finally {
    URL.revokeObjectURL(blobUrl);
  }
}

// A slope tile, or null when it is missing (the box is still drawn, without it).
function loadTile(url) {
  return new Promise(resolve => {
    const image = new Image();
    image.onload = () => resolve(image);
    image.onerror = () => resolve(null);
    image.src = url;
  });
}

export class MapLayers {
  constructor({terrain, scene, renderer, redraw = () => {}, plan = null}) {
    Object.assign(this, {terrain, scene, renderer, redraw});
    this.group = new THREE.Group();
    this.group.name = 'map-layer';
    this.group.visible = false;
    this.material = null;          // made on the first pick
    this.texture = null;           // of the layer shown, or null
    this.slider = 1;
    this.habitat = null;
    this.limit = undefined;
    this.layersMeta = null;        // GET /layers, once asked
    this.current = {id: null, image: null, error: null, width: 0, height: 0};
    this._meta = null;             // the promise of GET /layers
    this._token = 0;               // the latest pick: older loads are thrown away
    this._info = null;             // info JSON of the layer shown

    const pick = el('layer-pick');
    for (const layer of LAYERS) {
      const option = make('option', '', layer.label);
      option.value = layer.id;
      if (layer.title) option.title = layer.title;
      pick.append(option);
    }
    pick.addEventListener('change', e => this.select(e.target.value));
    el('layer-opacity').addEventListener('input', e => this.setOpacity(e.target.value));
    // The photo view compares the rover photo with the bare terrain: the layer steps aside.
    new MutationObserver(() => this._show()).observe(document.body, {attributes: true, attributeFilter: ['class']});
    this.setPlan(plan);
  }

  // ---- public ------------------------------------------------------------------

  // Show a layer by id ('' or an unknown id: none). Resolves with `current` once it is
  // drawn or has failed (current.error says why); a pick overtaken by another resolves
  // with {id, stale: true}.
  select(id) { return this._load(id, {keepSlider: false}); }

  setOpacity(value) {
    const v = Math.min(1, Math.max(0, Number(value)));
    this.slider = Number.isFinite(v) ? v : 0;
    el('layer-opacity').value = this.slider;
    if (this.material) this.material.opacity = sliderToOpacity(this.slider);
    this.redraw();
  }

  // A new plan (parsePlan() result or null): the radio antenna stands at its habitat and
  // the steep cells are those over its limit. A shown radio or steep layer whose image
  // changes with it is loaded again; the slider stays where it is.
  setPlan(model) {
    const before = this._request(this.current.id);
    this.habitat = planHabitat(model, this.terrain.meta.bbox);
    this.limit = planSlopeLimit(model);
    const id = this.current.id;
    if (id === 'radio' || id === 'steep') {
      const after = this._request(id);
      if (!before || before.image !== after.image || before.reason !== after.reason) {
        return this._load(id, {keepSlider: true});
      }
    }
    if (id) this._legend(id, this._info);
    return Promise.resolve(this.current);
  }

  state() { return {id: this.current.id, slider: this.slider}; }

  async restore(state) {
    if ((state && state.id) !== this.current.id) await this.select(state ? state.id : '');
    if (state) this.setOpacity(state.slider);
    return this.current;
  }

  // The source image of the layer shown (the PNG as served, or the slope canvas) decoded
  // through a 2D canvas: {w, h, rgba}, row 0 north, straight alpha. null when none.
  async imageData() {
    const image = this.current.image;
    if (!image) return null;
    const w = this.current.width, h = this.current.height;
    let ctx = image.getContext ? image.getContext('2d') : null;
    if (!ctx) {
      const canvas = make('canvas');
      canvas.width = w; canvas.height = h;
      ctx = canvas.getContext('2d');
      ctx.drawImage(image, 0, 0);
    }
    return {w, h, rgba: new Uint8Array(ctx.getImageData(0, 0, w, h).data.buffer)};
  }

  // ---- inside ------------------------------------------------------------------

  _request(id) { return id ? layerRequest(id, {habitat: this.habitat, limit: this.limit}) : null; }

  async _load(id, {keepSlider}) {
    const token = ++this._token, layer = layerById(id);
    const stale = () => token !== this._token;
    el('layer-pick').value = layer ? layer.id : '';
    el('layer-opacity').disabled = !layer;
    this._drop();                                  // the old texture goes now, not after the new one loads
    this._info = null;
    if (!keepSlider || !layer) this.setOpacity(layer ? layer.slider : 1);
    if (!layer) {
      this.current = {id: null, image: null, error: null, width: 0, height: 0};
      this.scene.remove(this.group);               // off: the scene is as without this file
      this._legend(null);
      this._note('');
      this.redraw();
      return this.current;
    }
    this._legend(layer.id, null);
    const req = this._request(layer.id);
    if (req.reason) return this._fail(layer.id, req.reason, {plain: true});
    this._note('Loading…');
    this._build();

    const [info, got] = await Promise.all([this._fetchInfo(req.info),
                                           req.tiles ? this._slopeCanvas() : fetchImage(req.image)]);
    if (stale()) return {id: layer.id, stale: true};
    if (info.error || got.error) return this._fail(layer.id, info.error || got.error);

    const image = got.image;
    const texture = image.getContext ? new THREE.CanvasTexture(image) : new THREE.Texture(image);
    texture.colorSpace = THREE.SRGBColorSpace;
    texture.anisotropy = this.renderer.capabilities.getMaxAnisotropy();
    texture.needsUpdate = true;
    this.texture = texture;
    this.material.map = texture;
    this.material.needsUpdate = true;
    this._info = info.info;
    this.current = {id: layer.id, image, error: null, width: image.naturalWidth || image.width,
                    height: image.naturalHeight || image.height};
    this.scene.add(this.group);
    this._legend(layer.id, info.info);
    this._note(this._noteText(layer.id, info.info, got.missing));
    this._show();
    this.redraw();
    return this.current;
  }

  _fail(id, error, {plain = false} = {}) {
    this.current = {id, image: null, error, width: 0, height: 0};
    this._note(plain ? error : `Unavailable: ${error}`);
    this.redraw();
    return this.current;
  }

  // The meshes, once: one per terrain mesh, on its geometry, with its place.
  _build() {
    if (this.material) return;
    this.material = new THREE.MeshBasicMaterial({
      map: null, opacity: sliderToOpacity(this.slider), toneMapped: false, fog: true, depthWrite: false,
      transparent: false, blending: THREE.CustomBlending,            // drawn in the opaque pass, blended
      blendSrc: THREE.SrcAlphaFactor, blendDst: THREE.OneMinusSrcAlphaFactor,
      polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,   // the terrain's depth exactly
    });
    const {group} = this.terrain;
    this.group.position.copy(group.position);
    this.group.quaternion.copy(group.quaternion);
    this.group.scale.copy(group.scale);
    for (const tile of group.children) {
      const mesh = new THREE.Mesh(tile.geometry, this.material);
      mesh.name = 'map-layer tile';
      mesh.position.copy(tile.position);
      mesh.quaternion.copy(tile.quaternion);
      mesh.scale.copy(tile.scale);
      mesh.castShadow = mesh.receiveShadow = false;
      mesh.renderOrder = 1;                        // after the terrain and the lines of the opaque pass
      this.group.add(mesh);
    }
  }

  // Free the texture shown (the meshes and their shared geometry stay).
  _drop() {
    if (this.material) { this.material.map = null; this.material.needsUpdate = true; }
    if (this.texture) this.texture.dispose();
    this.texture = null;
    this._show();
  }

  _show() {
    const visible = Boolean(this.texture) && !document.body.classList.contains('photo-view');
    if (this.group.visible === visible) return;
    this.group.visible = visible;
    this.redraw();
  }

  // GET /layers, asked once (the slope needs its tile list and box).
  _layers() {
    if (!this._meta) {
      this._meta = fetch('/layers').then(async res => {
        if (!res.ok) throw new Error(`/layers: ${await errorText(res)}`);
        this.layersMeta = await res.json();
        return this.layersMeta;
      });
      this._meta.catch(() => { this._meta = null; });        // asked again next time
    }
    return this._meta;
  }

  async _fetchInfo(url) {
    if (!url) return {info: null};
    try {
      const res = await fetch(url);
      if (!res.ok) return {error: await errorText(res)};
      return {info: await res.json()};
    } catch (err) {
      return {error: err.message};
    }
  }

  // The slope tiles of the box on one canvas (north-west corner at 0, 0); a missing
  // tile is left transparent.
  async _slopeCanvas() {
    let meta;
    try { meta = await this._layers(); } catch (err) { return {error: err.message}; }
    const grid = slopeTileGrid(meta.tiles, meta.grid && meta.grid.bbox);
    if (!grid) return {error: 'the tile list of /layers has no slope layer'};
    const canvas = make('canvas');
    canvas.width = grid.width; canvas.height = grid.height;
    const ctx = canvas.getContext('2d');
    const images = await Promise.all(grid.tiles.map(t => loadTile(t.url)));
    let missing = 0;
    images.forEach((image, k) => {
      if (image) ctx.drawImage(image, grid.tiles[k].px, grid.tiles[k].py, grid.tileSize, grid.tileSize);
      else missing++;
    });
    if (missing === grid.tiles.length) return {error: 'no slope tile could be loaded'};
    return {image: canvas, missing};
  }

  _noteText(id, info, missing) {
    const view = legendView(id, {info, limit: this.limit});
    const note = (view && view.note) || '';
    return missing ? `${note}${note ? ' ' : ''}${missing} slope tiles are missing: left blank.` : note;
  }

  _note(text) { el('layer-note').textContent = text; }

  // The legend as the HUD's sidebar draws it: a bar with its ticks, a swatch, the hatch
  // or the boulder dots, with their words.
  _legend(id, info) {
    const box = el('layer-legend');
    box.replaceChildren();
    const view = id ? legendView(id, {info, limit: this.limit}) : null;
    if (!view || (!view.text && !view.caption)) return;
    if (view.kind === 'gradient') {
      const bar = make('div', 'layer-bar');
      bar.style.background = view.sidebar || view.css;
      box.append(bar);
      if (view.ticks.length) {
        const row = make('div', 'layer-ticks');
        for (const tick of view.ticks) row.append(make('span', '', tick));
        box.append(row);
      }
      if (view.caption) box.append(make('div', 'muted layer-caption', view.caption));
    } else if (view.kind === 'dots') {
      const row = make('div', 'layer-dots');
      for (const size of view.dots) {
        const dot = make('i');
        dot.style.width = dot.style.height = `${size}px`;
        dot.style.background = view.css;
        if (view.border) dot.style.border = view.border;
        row.append(dot);
      }
      row.append(make('span', 'muted', view.caption));
      box.append(row);
    } else {                                       // fill, hatch
      const line = make('div', 'muted layer-key'), swatch = make('span', 'layer-swatch');
      swatch.style.background = view.sidebar || view.css;
      if (view.border) swatch.style.border = view.border;
      line.append(swatch, view.caption || view.text);
      box.append(line);
    }
  }
}

// main.js: wires the panel; nothing is asked from the server until a layer is picked.
export function setupMapLayers(viz) {
  return new MapLayers({terrain: viz.terrain, scene: viz.scene, renderer: viz.renderer,
                        redraw: () => viz.redraw(), plan: viz.plan ? viz.plan.model : null});
}
