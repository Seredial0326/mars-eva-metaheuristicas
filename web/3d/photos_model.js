// Rover photos of the 3D map (P3, issue #46, blocks 2 and 3): the numbers.
//
// Reads the catalogue of block 1 (src/viz3d/build_rover_photos.py, served at
// /tiles/3d/photos/catalog.json) and turns it into what photos.js shows: one pin per
// stop, the views of a stop, the rows of the card, where the camera stands, the
// square of the canvas the photo covers and, on a station's card, its nearest photo
// (block 3). No three.js and no page here, so it is tested in Node
// (tests/viz3d/photos_model.test.mjs).
//
// A bad photo or stop is skipped and listed in `problems`, never thrown. Text from the
// catalogue is data: it comes back as plain strings for textContent, never as HTML.
// Positions stay in Mars CRS metres (x east, y north, z elevation on the DEM's datum);
// heading is radians clockwise from north, pitch radians positive BELOW the horizon.
import { trueSolarDate } from './mars_sun.js';
import { compassWord, siteFromCrs, utcText } from './sun_model.js';

export const PHOTO_ROOT = '/tiles/3d/photos/';
export const SCHEMA_VERSION = 1;
export const PHOTO_COLOR = [255, 150, 60];      // the pins: orange, apart from the station and route colours
export const CAMERA_GLYPH = '📷';
// Where a Navcam stands above the ground it sees (about 1.9 m on the mast). Outside
// these limits the camera and the terrain shown disagree, and the view says so.
export const MIN_EYE_HEIGHT_M = 0.5;
export const MAX_EYE_HEIGHT_M = 4;
// Headings 0 to 90 degrees are sector 0, and so on (the catalogue's "quadrants").
export const SECTOR_LABELS = ['N to E', 'E to S', 'S to W', 'W to N'];
// A station's card shows the nearest photo taken at most PREVIEW_MAX_M away (block 3).
// Photos up to PREVIEW_TIE_M farther than the nearest are as near (the views of one
// stop lie a few metres apart): among them, the one that looks most towards the station.
export const PREVIEW_MAX_M = 150;
export const PREVIEW_TIE_M = 10;
const AT_CAMERA_M = 1e-3;          // closer than this the station has no direction from the camera

const ID = /^[A-Za-z0-9_-]{1,80}$/;
const LMST = /^Sol-(\d+)M(\d\d):(\d\d):(\d\d(?:\.\d+)?)$/;
const CAMERAS = {LEFT: 'Navcam left', RIGHT: 'Navcam right'};
const DEG = Math.PI / 180;
const isObject = v => v !== null && typeof v === 'object' && !Array.isArray(v);
const finite = v => typeof v === 'number' && Number.isFinite(v);
const text = v => (typeof v === 'string' && v.trim() ? v : null);
const degrees360 = rad => ((Math.round(rad / DEG) % 360) + 360) % 360;
const around360 = deg => ((deg % 360) + 360) % 360;
const signed180 = deg => around360(deg + 180) - 180;

// An asset path of the catalogue (relative to PHOTO_ROOT) as an address under it, or
// null when it could leave the photo folder or carry a scheme, query or escape.
function assetUrl(path) {
  if (typeof path !== 'string' || !path) return null;
  const parts = path.split('/');
  if (!parts.every(p => /^[A-Za-z0-9_.-]+$/.test(p) && p !== '.' && p !== '..')) return null;
  return PHOTO_ROOT + path;
}

function parseGroup(raw) {
  if (!isObject(raw)) return {reason: 'not an object'};
  if (typeof raw.id !== 'string' || !ID.test(raw.id)) return {reason: 'bad id (letters, digits, _ and - only, 1 to 80 characters)'};
  const rep = raw.representative, xy = isObject(rep) && Array.isArray(rep.xy) ? rep.xy : null;
  if (!xy || !finite(xy[0]) || !finite(xy[1]) || !finite(rep.z)) {
    return {reason: 'no position: representative.xy and representative.z must be finite numbers'};
  }
  if (!Array.isArray(raw.photo_ids)) return {reason: 'photo_ids is not a list'};
  const missing = Array.isArray(raw.missing_quadrants) ? raw.missing_quadrants : [];
  const sectors = [...new Set(missing.filter(q => Number.isInteger(q) && q >= 0 && q < 4))].sort();
  return {group: {id: raw.id, x: xy[0], y: xy[1], z: rep.z, listed: raw.photo_ids.filter(id => typeof id === 'string'),
                  photoIds: [], missingSectors: sectors.map(q => SECTOR_LABELS[q])}};
}

function parsePhoto(raw, groups) {
  if (!isObject(raw)) return {reason: 'not an object'};
  if (typeof raw.id !== 'string' || !ID.test(raw.id)) return {reason: 'bad id (letters, digits, _ and - only, 1 to 80 characters)'};
  if (typeof raw.group_id !== 'string' || !groups.has(raw.group_id)) {
    return {reason: `unknown group ${JSON.stringify(String(raw.group_id ?? ''))}`};
  }
  const pose = raw.pose;
  if (!isObject(pose)) return {reason: 'missing pose'};
  for (const key of ['x', 'y', 'z', 'heading', 'pitch', 'fov']) {
    if (!finite(pose[key])) return {reason: `pose.${key} is not a finite number`};
  }
  if (pose.fov <= 0 || pose.fov >= 180) return {reason: `pose.fov ${pose.fov} is not a field of view in degrees`};
  if (!Number.isInteger(raw.sol) || raw.sol < 0) return {reason: 'sol is not a whole number'};
  const utcMs = typeof raw.date_taken === 'string' ? Date.parse(raw.date_taken) : NaN;
  if (!Number.isFinite(utcMs)) return {reason: 'date_taken is not a UTC date'};
  const side = /^NAV_(LEFT|RIGHT)_[AB]$/.exec(String(raw.instrument ?? ''));
  if (!side) return {reason: `instrument ${JSON.stringify(String(raw.instrument ?? ''))} is not a Navcam`};

  const assets = isObject(raw.assets) ? raw.assets : {};
  let images = {thumb: null, card: null, compare: null}, note = null;
  if (assets.status === 'available') {
    const got = {thumb: assetUrl(assets.thumbnail), card: assetUrl(assets.unwarped), compare: assetUrl(assets.rectified)};
    if (Object.values(got).every(Boolean)) images = got;
    else note = 'assets are marked available but an image path is missing or unsafe: shown without images';
  }
  const url = text(raw.https_url);
  return {note, photo: {
    id: raw.id, groupId: raw.group_id, sol: raw.sol, utcMs, lmst: text(raw.lmst),
    camera: CAMERAS[side[1]], credit: text(raw.image_credit),
    sourceUrl: url && /^https:\/\/[^\s"'<>]+$/.test(url) ? url : null,
    x: pose.x, y: pose.y, z: pose.z, heading: pose.heading, pitch: pose.pitch, fov: pose.fov,
    distanceM: finite(raw.distance_to_representative_m) ? raw.distance_to_representative_m : null,
    images, available: images.compare !== null,
  }};
}

// Catalogue JSON -> {generation, groups, photos, byId (Map id -> photo), problems}.
// Throws only when the JSON is not a catalogue of schema_version 1.
export function parseCatalog(json) {
  if (!isObject(json)) throw new Error('not a photo catalogue (not a JSON object)');
  if (json.schema_version !== SCHEMA_VERSION) {
    throw new Error(`photo catalogue schema_version ${JSON.stringify(json.schema_version)} is not ${SCHEMA_VERSION}`);
  }
  if (!Array.isArray(json.groups) || !Array.isArray(json.photos)) {
    throw new Error('not a photo catalogue (groups and photos must be lists)');
  }
  const problems = [], groupsById = new Map(), byId = new Map(), photos = [];
  const idOf = (raw, i, kind) => (isObject(raw) && typeof raw.id === 'string' ? raw.id.slice(0, 80) : `${kind}[${i}]`);
  json.groups.forEach((raw, i) => {
    const {group, reason} = parseGroup(raw);
    if (group && groupsById.has(group.id)) problems.push({id: group.id, reason: 'stop skipped: duplicate id'});
    else if (group) groupsById.set(group.id, group);
    else problems.push({id: idOf(raw, i, 'groups'), reason: `stop skipped: ${reason}`});
  });
  json.photos.forEach((raw, i) => {
    const {photo, reason, note} = parsePhoto(raw, groupsById);
    if (!photo) return problems.push({id: idOf(raw, i, 'photos'), reason: `photo skipped: ${reason}`});
    if (byId.has(photo.id)) return problems.push({id: photo.id, reason: 'photo skipped: duplicate id'});
    if (!groupsById.get(photo.groupId).listed.includes(photo.id)) {
      return problems.push({id: photo.id, reason: `photo skipped: its stop ${photo.groupId} does not list it`});
    }
    if (note) problems.push({id: photo.id, reason: note});
    byId.set(photo.id, photo);
    photos.push(photo);
  });
  const groups = [], inCatalogue = new Set(json.photos.map(p => (isObject(p) ? p.id : undefined)));
  for (const {listed, ...group} of groupsById.values()) {
    for (const id of new Set(listed)) {
      if (byId.get(id)?.groupId === group.id) group.photoIds.push(id);
      else if (!inCatalogue.has(id)) problems.push({id, reason: `stop ${group.id} lists a photo that is not in the catalogue`});
    }
    groups.push(group);
  }
  return {generation: text(json.generation), groups, photos, byId, problems};
}

// MarkerLayer list: one pin per stop with at least one photo, labelled with a camera
// only: 100 stops lie along one traverse, and a count on each would hide the stations.
// The card says how many views a stop has.
export function photoMarkers(model) {
  return model.groups.filter(g => g.photoIds.length > 0).map(g => ({
    id: `photo:${g.id}`, x: g.x, y: g.y, kind: 'photo', label: CAMERA_GLYPH,
    color: PHOTO_COLOR, data: {kind: 'photo', groupId: g.id},
  }));
}

// The photos of a stop, from north clockwise, each with the compass word of its heading
// (copies: the model is not changed). An unknown stop has none.
export function viewsOf(model, groupId) {
  const group = model.groups.find(g => g.id === groupId);
  if (!group) return [];
  const turn = 2 * Math.PI, around = h => ((h % turn) + turn) % turn;
  return group.photoIds.map(id => model.byId.get(id))
    .sort((a, b) => around(a.heading) - around(b.heading) || (a.id < b.id ? -1 : 1))
    .map(p => ({...p, direction: compassWord(p.heading / DEG)}));
}

// Rows of the card: [[label, value], ...], all plain text.
export function photoFacts(photo) {
  const clock = photo.lmst && LMST.exec(photo.lmst);
  const pitchDeg = Math.round(Math.abs(photo.pitch) / DEG);
  const tilt = pitchDeg === 0 ? 'level with the horizon'
             : `${pitchDeg}° ${photo.pitch > 0 ? 'below' : 'above'} the horizon`;
  return [
    ['Date', utcText(photo.utcMs)],
    ['Sol', String(photo.sol)],
    ['Local time', clock ? `${clock[2]}:${clock[3]} LMST` : 'not given'],
    ['Camera', `${photo.camera}, black and white`],
    ['Looking', `${compassWord(photo.heading / DEG)} (${degrees360(photo.heading)}°), ${tilt}`],
    ['Credit', photo.credit ?? 'not given'],
  ];
}

// Where the camera of the photo view stands. groundElevation: the DEM elevation (m)
// under (x, y) at relief x1, or null outside the box. The numbers are never adjusted:
// when ok is false the caller decides how to fly and shows `reason`.
export function photoPose(photo, groundElevation) {
  const base = {x: photo.x, y: photo.y, heading: photo.heading, pitch: photo.pitch, fov: photo.fov};
  if (!finite(groundElevation)) {
    return {...base, eyeHeight: null, ok: false,
            reason: 'There is no ground of the 3D map under this camera: the photo was taken outside the map.'};
  }
  const eyeHeight = photo.z - groundElevation;
  const m = `${Math.abs(eyeHeight).toFixed(2)} m`;
  let reason = null;
  if (eyeHeight < 0) {
    reason = `The camera is ${m} under the ground shown here (it should be about 2 m above it): ` +
             'the map and the rover position disagree, so the photo will not line up well.';
  } else if (eyeHeight < MIN_EYE_HEIGHT_M) {
    reason = `The camera is only ${m} above the ground shown here (it should be about 2 m): ` +
             'the map and the rover position disagree, so the photo will not line up well.';
  } else if (eyeHeight > MAX_EYE_HEIGHT_M) {
    reason = `The camera is ${m} above the ground shown here (it should be about 2 m): ` +
             'the map and the rover position disagree, so the photo will not line up well.';
  }
  return {...base, eyeHeight, ok: reason === null, reason};
}

// The camera's vertical field (deg) and the centred square of the canvas (CSS px) that
// spans fovDeg both across and up: the whole height on a wide canvas, the whole width
// on a tall one.
export function squareView(widthPx, heightPx, fovDeg = 40) {
  if (!(widthPx > 0 && heightPx > 0 && Number.isFinite(widthPx) && Number.isFinite(heightPx))) {
    return {fovY: fovDeg, side: 0, left: 0, top: 0};
  }
  if (widthPx >= heightPx) return {fovY: fovDeg, side: heightPx, left: (widthPx - heightPx) / 2, top: 0};
  const fovY = 2 * Math.atan(Math.tan(fovDeg * DEG / 2) * heightPx / widthPx) / DEG;
  return {fovY, side: widthPx, left: 0, top: (heightPx - widthPx) / 2};
}

// Sol and local TRUE solar time (hours) of the photo at a longitude east (by default
// the photo's own): what SunView.set takes to light the scene as it was.
export function sunOf(photo, lonEastDeg = siteFromCrs(photo.x, photo.y).lonEastDeg) {
  const date = trueSolarDate(photo.utcMs, lonEastDeg);
  const sol = Math.floor(date);
  return {sol, hours: (date - sol) * 24};
}

// Where a station lies for one photo: bearing from the camera (degrees clockwise from
// north), off the photo's centre across (+ right) and, with the ground under the station,
// up and down (+ below), and whether it falls in the comparison frame (fov square). Only
// the direction: nothing here says the terrain between them lets the station be seen.
function aim(photo, x, y, distanceM, groundElevation) {
  const headingDeg = around360(photo.heading / DEG), half = photo.fov / 2;
  const verticalChecked = finite(groundElevation);
  // Angle of the station's ground point under the camera's horizon, minus the photo's pitch.
  const verticalOffDeg = verticalChecked
    ? Math.atan2(photo.z - groundElevation, distanceM) / DEG - photo.pitch / DEG : null;
  const at = {verticalChecked, verticalOffDeg, looking: compassWord(headingDeg)};
  if (distanceM < AT_CAMERA_M) {
    // Straight under the camera: no side and no bearing. Given as the heading itself
    // (0 off the centre) so the numbers stay numbers, but never in the field.
    return {...at, bearingDeg: headingDeg, offAxisDeg: 0, inField: false, cameraSide: null};
  }
  const bearingDeg = around360(Math.atan2(x - photo.x, y - photo.y) / DEG);
  const offAxisDeg = signed180(bearingDeg - headingDeg);
  const inField = Math.abs(offAxisDeg) <= half && (!verticalChecked || Math.abs(verticalOffDeg) <= half);
  return {...at, bearingDeg, offAxisDeg, inField, cameraSide: compassWord(bearingDeg + 180)};
}

// The rover photo for a station's card at (x, y) (Mars CRS metres): of the photos with
// images, the nearest across the ground; any up to tieM farther counts as as near, and of
// those the one that looks most towards the station wins, then the nearer, then the id.
// groundElevation: the DEM elevation (m) at the station at relief x1, or null (outside
// the box): with it the station must also fall in the frame up and down (verticalChecked).
// Returns {photo, distanceM, bearingDeg (camera -> station, 0 to 360), offAxisDeg (station
// bearing minus heading, -180 to 180, + right), verticalOffDeg (+ below the centre, null
// unchecked), inField, verticalChecked, cameraSide (compass word, station -> camera),
// looking (compass word of the heading)}; or, when no photo is within maxDistanceM,
// {photo: null, nearestM (null when no photo has images), maxDistanceM}. null when (x, y)
// is not a point. The photo is the model's own (not a copy); the model is not changed.
export function nearestPhoto(model, {x, y} = {}, {groundElevation = null, maxDistanceM = PREVIEW_MAX_M,
                                                    tieM = PREVIEW_TIE_M} = {}) {
  if (!finite(x) || !finite(y)) return null;
  const near = model.photos.filter(p => p.available)
    .map(photo => ({photo, distanceM: Math.hypot(photo.x - x, photo.y - y)}));
  const d0 = near.reduce((min, n) => Math.min(min, n.distanceM), Infinity);
  if (!(d0 <= maxDistanceM)) return {photo: null, nearestM: near.length ? d0 : null, maxDistanceM};
  // As near as the nearest: within tieM of it, and never past maxDistanceM.
  const limit = Math.min(d0 + tieM, maxDistanceM);
  const away = r => (r.cameraSide === null ? Infinity : Math.abs(r.offAxisDeg));   // under the camera: looks nowhere at it
  return near.filter(n => n.distanceM <= limit)
    .map(n => ({...n, ...aim(n.photo, x, y, n.distanceM, groundElevation)}))
    .sort((a, b) => away(a) - away(b) || a.distanceM - b.distanceM || (a.photo.id < b.photo.id ? -1 : 1))[0];
}

// The station's photo line of its card, one plain sentence from nearestPhoto(). It says
// where the photo was taken and whether the station falls in its field, which is a
// direction only: the terrain may still hide the station, and the words never say it is seen.
export function previewText(result) {
  const metres = m => `${Number(m.toFixed(1))} m`;
  if (!result.photo) {
    const max = metres(result.maxDistanceM);
    if (result.nearestM === null) return `No rover photo within ${max} of this station (no rover photo is published for this map).`;
    const nearest = Math.round(result.nearestM);
    return `No rover photo within ${max} of this station ` +
           `(the nearest is ${nearest > result.maxDistanceM ? `${nearest} m` : `just over ${max}`} away).`;
  }
  const {photo, distanceM, cameraSide, looking, offAxisDeg: off, verticalOffDeg: down} = result;
  const m = Math.round(distanceM);
  const where = cameraSide === null ? 'right at the station' : `${m < 1 ? 'under 1' : m} m ${cameraSide} of the station`;
  if (result.inField) {
    // Without the ground under the station only the side to side test was made: said so.
    const [field, note] = result.verticalChecked ? ['inside its field', 'the terrain may still hide it']
      : ['inside its field from side to side', 'not checked up and down; the terrain may still hide it'];
    return `Rover photo taken ${where}, looking ${looking}: the station is ${field} (${note}).`;
  }
  const why = cameraSide === null ? 'the station is straight under the camera'
    : Math.abs(off) > photo.fov / 2 ? `the station is ${Math.round(Math.abs(off))}° to the ${off > 0 ? 'right' : 'left'} of its centre`
    : `the station is ${Math.round(Math.abs(down))}° ${down > 0 ? 'below' : 'above'} its centre`;
  return `Nearest rover photo: ${where}, looking ${looking}; ${why}, outside its field.`;
}

// ?photo=<id>: the id when it can be one, else null.
export function parsePhotoParam(value) {
  return typeof value === 'string' && ID.test(value) ? value : null;
}
