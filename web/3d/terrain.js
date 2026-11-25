// Terrain of the 3D map (P1, issue #42).
//
// Loads the assets written by src/viz3d/build_terrain_assets.py (served by the API at
// /tiles/3d/) and builds the meshes. Conventions:
//   - Scene axes: X = east, Y = up, Z = SOUTH (so north is -Z). Origin = box centre.
//     The API speaks metres in the Mars CRS (x about 8.1e6): always convert with
//     toLocal() before sending anything to the GPU, which only has 32-bit floats.
//   - Shown height = height + (k - 1) * detail. k = 1 is the DEM; k > 1 exaggerates
//     only the smoothed local relief (never the 475 m hillside nor the DEM noise).
//   - Shading: vertex normals come from the smooth hillside (`low`), the local relief
//     comes from the normal map with normalScale = k / gain. Both quality presets
//     share the same normal map, so they shade the same.
import * as THREE from 'three';

export const ASSET_URL = '/tiles/3d/';
export const BUILD_HINT = 'python src/viz3d/build_terrain_assets.py';

async function fetchLayer(layer, count, zRef) {
  const res = await fetch(ASSET_URL + layer.file);
  if (!res.ok) throw new Error(`${layer.file}: HTTP ${res.status}`);
  const raw = new Uint16Array(await res.arrayBuffer());
  if (raw.length !== count) throw new Error(`${layer.file}: expected ${count} values, got ${raw.length}`);
  const out = new Float32Array(count);
  for (let i = 0; i < count; i++) out[i] = layer.offset_m + layer.scale_m * raw[i] - zRef;
  return out;
}

// Mean of each 2 x 2 block: the 2 m grid becomes the 4 m grid of the low preset.
function halve(a, n) {
  const m = n / 2, out = new Float32Array(m * m);
  for (let i = 0; i < m; i++) {
    for (let j = 0; j < m; j++) {
      const p = 2 * i * n + 2 * j;
      out[i * m + j] = 0.25 * (a[p] + a[p + 1] + a[p + n] + a[p + n + 1]);
    }
  }
  return out;
}

export class Terrain {
  // quality: 'low' (4 m mesh, one 4096 px photo) or 'high' (2 m mesh, photo at 0.25 m).
  static async load(quality, {maxAnisotropy = 1, onProgress = () => {}} = {}) {
    const res = await fetch(ASSET_URL + 'terrain.json');
    if (!res.ok) {
      throw new Error(`3D terrain assets not found (HTTP ${res.status}). ` +
                      `Build them from the repo root: ${BUILD_HINT}`);
    }
    const meta = await res.json();
    const t = new Terrain(meta, quality);
    onProgress('heights');
    const count = meta.grid.rows * meta.grid.cols;
    let [z, low, detail] = await Promise.all(
      ['height', 'low', 'detail'].map(name => fetchLayer(meta.layers[name], count, name === 'detail' ? 0 : t.zRef)));
    if (quality === 'low') [z, low, detail] = [z, low, detail].map(a => halve(a, meta.grid.cols));
    Object.assign(t, {z, low, detail});

    onProgress('photo');
    const loader = new THREE.TextureLoader();
    const tiles = quality === 'low' ? [meta.ortho.low] : meta.ortho.high;
    const [normalMap, ...maps] = await Promise.all(
      [meta.normal.file, ...tiles.map(tile => tile.file)].map(f => loader.loadAsync(ASSET_URL + f)));
    onProgress('mesh');
    t._build(tiles, maps, normalMap, maxAnisotropy);
    return t;
  }

  constructor(meta, quality) {
    this.meta = meta;
    this.quality = quality;
    const factor = quality === 'low' ? 2 : 1;
    this.n = meta.grid.cols / factor;                       // vertices per side
    this.step = meta.grid.spacing_m * factor;               // metres between vertices
    this.first = meta.grid.first_center_m * factor;         // first vertex, metres from the edge
    this.size = meta.size_m;
    this.half = this.size / 2;
    this.zRef = Math.round((meta.relief.z_min_m + meta.relief.z_max_m) / 2);   // Y = 0
    this.maxExaggeration = meta.relief.max_exaggeration;
    this.k = 1;
    this.group = new THREE.Group();
    this.group.name = 'terrain';
    this.materials = [];
  }

  // Mars CRS metres -> scene [X, Z]; and back.
  toLocal(x, y) { return [x - this.meta.bbox.xmin - this.half, this.meta.bbox.ymax - y - this.half]; }
  toMars(X, Z) { return [X + this.half + this.meta.bbox.xmin, this.meta.bbox.ymax - Z - this.half]; }

  // Shown ground height (scene Y) at a scene position, bilinear between vertices.
  heightAt(X, Z, k = this.k) {
    const {n, step, first, half, z, detail} = this;
    const gj = Math.min(n - 1, Math.max(0, (X + half - first) / step));
    const gi = Math.min(n - 1, Math.max(0, (Z + half - first) / step));
    const j0 = Math.min(n - 2, Math.floor(gj)), i0 = Math.min(n - 2, Math.floor(gi));
    const fj = gj - j0, fi = gi - i0, p = i0 * n + j0;
    const at = q => z[q] + (k - 1) * detail[q];
    return (1 - fi) * ((1 - fj) * at(p) + fj * at(p + 1)) +
           fi * ((1 - fj) * at(p + n) + fj * at(p + n + 1));
  }

  // Height of the drawn mesh at a scene position. Like heightAt, but linear inside each
  // of the two triangles of a cell (see _geometry), so anything laid on the ground sits
  // on the triangles exactly. Bilinear and triangles differ by decimetres at scarps,
  // which is enough to bury a line drawn 0.3 m above the ground.
  surfaceAt(X, Z, k = this.k) {
    const {n, step, first, half, z, detail} = this;
    const gj = Math.min(n - 1, Math.max(0, (X + half - first) / step));
    const gi = Math.min(n - 1, Math.max(0, (Z + half - first) / step));
    const j0 = Math.min(n - 2, Math.floor(gj)), i0 = Math.min(n - 2, Math.floor(gi));
    const fj = gj - j0, fi = gi - i0, p = i0 * n + j0;
    const at = q => z[q] + (k - 1) * detail[q];
    // a = north-west corner, b = south-west, c = north-east, d = south-east; the two
    // triangles are a-b-c and b-d-c (the diagonal joins b and c).
    const a = at(p), b = at(p + n), c = at(p + 1), d = at(p + n + 1);
    return fi + fj <= 1 ? a + fi * (b - a) + fj * (c - a)
                        : d + (1 - fi) * (c - d) + (1 - fj) * (b - d);
  }

  // Real elevation (metres, DEM datum) of a shown height.
  elevation(Y) { return Y + this.zRef; }

  setExaggeration(k) {
    this.k = Math.min(this.maxExaggeration, Math.max(1, k));
    const {n, z, detail} = this, extra = this.k - 1;
    for (const mesh of this.group.children) {
      const {i0, j0, rows, cols} = mesh.userData;
      const pos = mesh.geometry.attributes.position;
      for (let i = 0; i < rows; i++) {
        for (let j = 0; j < cols; j++) {
          const p = (i0 + i) * n + j0 + j;
          pos.array[(i * cols + j) * 3 + 1] = z[p] + extra * detail[p];
        }
      }
      pos.needsUpdate = true;
      mesh.geometry.computeBoundingSphere();
      mesh.geometry.computeBoundingBox();
    }
    const scale = this.k / this.meta.normal.gain;
    for (const m of this.materials) m.normalScale.set(scale, scale);
    return this.k;
  }

  _build(tiles, maps, normalMap, maxAnisotropy) {
    const {n, size} = this;
    normalMap.anisotropy = maxAnisotropy;
    // One mesh per photo tile. Neighbouring meshes share a row/column of vertices.
    const split = tiles.length === 1 ? [[0, n - 1]] : [[0, n / 2], [n / 2, n - 1]];
    tiles.forEach((tile, t) => {
      const map = maps[t];
      map.colorSpace = THREE.SRGBColorSpace;
      map.anisotropy = maxAnisotropy;
      // The geometry has one UV set over the whole box (u east, v north); each photo
      // tile maps its own part of it with the texture transform.
      const south = size - tile.north_m - tile.size_m;
      map.repeat.set(size / tile.size_m, size / tile.size_m);
      map.offset.set(-tile.west_m / tile.size_m, -south / tile.size_m);
      const material = new THREE.MeshStandardMaterial({
        map, normalMap, roughness: 1, metalness: 0,
        polygonOffset: true, polygonOffsetFactor: 1, polygonOffsetUnits: 1,   // lines drawn on top win
      });
      this.materials.push(material);
      const [i0, i1] = split[tiles.length === 1 ? 0 : Math.floor(t / 2)];
      const [j0, j1] = split[tiles.length === 1 ? 0 : t % 2];
      const mesh = new THREE.Mesh(this._geometry(i0, i1, j0, j1), material);
      mesh.userData = {i0, j0, rows: i1 - i0 + 1, cols: j1 - j0 + 1};
      mesh.castShadow = mesh.receiveShadow = true;           // used when the sun light casts (shadows.js)
      this.group.add(mesh);
    });
    this.setExaggeration(this.k);
  }

  _geometry(i0, i1, j0, j1) {
    const {n, step, first, half, size, low} = this;
    const rows = i1 - i0 + 1, cols = j1 - j0 + 1;
    const position = new Float32Array(rows * cols * 3);
    const normal = new Float32Array(rows * cols * 3);
    const uv = new Float32Array(rows * cols * 2);
    for (let i = 0; i < rows; i++) {
      for (let j = 0; j < cols; j++) {
        const gi = i0 + i, gj = j0 + j, v = i * cols + j;
        const east = first + gj * step, south = first + gi * step;
        position[v * 3] = east - half;
        position[v * 3 + 2] = south - half;                  // Y is set by setExaggeration
        uv[v * 2] = east / size;
        uv[v * 2 + 1] = 1 - south / size;
        // Normal of the smooth hillside: (-dh/dEast, 1, +dh/dNorth), since Z = south.
        const w = low[gi * n + Math.max(0, gj - 1)], e = low[gi * n + Math.min(n - 1, gj + 1)];
        const nn = low[Math.max(0, gi - 1) * n + gj], s = low[Math.min(n - 1, gi + 1) * n + gj];
        const dEast = (e - w) / ((Math.min(n - 1, gj + 1) - Math.max(0, gj - 1)) * step);
        const dNorth = (nn - s) / ((Math.min(n - 1, gi + 1) - Math.max(0, gi - 1)) * step);
        const inv = 1 / Math.hypot(dEast, 1, dNorth);
        normal[v * 3] = -dEast * inv;
        normal[v * 3 + 1] = inv;
        normal[v * 3 + 2] = dNorth * inv;
      }
    }
    // Two triangles per cell, counter-clockwise seen from above (front face up).
    const index = new Uint32Array((rows - 1) * (cols - 1) * 6);
    let q = 0;
    for (let i = 0; i < rows - 1; i++) {
      for (let j = 0; j < cols - 1; j++) {
        const a = i * cols + j, b = a + cols, c = a + 1, d = b + 1;
        index[q++] = a; index[q++] = b; index[q++] = c;
        index[q++] = b; index[q++] = d; index[q++] = c;
      }
    }
    const g = new THREE.BufferGeometry();
    g.setAttribute('position', new THREE.BufferAttribute(position, 3));
    g.setAttribute('normal', new THREE.BufferAttribute(normal, 3));
    g.setAttribute('uv', new THREE.BufferAttribute(uv, 2));
    g.setIndex(new THREE.BufferAttribute(index, 1));
    return g;
  }

  get triangles() {
    return this.group.children.reduce((sum, m) => sum + m.geometry.index.count / 3, 0);
  }
}
