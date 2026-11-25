// Rover photos in the 2D HUD (P3b, issue #103): the numbers.
//
// The 2D map (web/index.html) loads this with `await import("/hud_photos.js")`. It reads
// the same catalogue as the 3D map and reuses web/3d/photos_model.js to parse it, order
// the views of a stop, write the card rows and find a station's nearest photo, so both
// maps say the same thing. What is added here: the stops to pin, the view wedge of a
// photo, the card of a stop and the photo line under a station in the station list.
// No DOM, no deck.gl and no three.js: the HUD owns all drawing, and this file is tested
// in Node (tests/web/hud_photos.test.mjs).
//
// Units as in photos_model.js: positions in Mars CRS metres (x east, y north), heading in
// radians clockwise from north, fov in degrees. Text comes back plain, for textContent.
// Like the 3D map, a photo line gives a direction only: it never says a station is seen.
import {
  nearestPhoto, parseCatalog, parsePhotoParam, photoFacts, photoMarkers, previewText, viewsOf,
} from "./3d/photos_model.js";

export const CATALOG_URL = "/tiles/3d/photos/catalog.json";
// How far out a view wedge is drawn: as far as a station's photo line looks
// (PREVIEW_MAX_M of photos_model.js; the tests check they match).
export const WEDGE_RADIUS_M = 150;

const DEG = Math.PI / 180;
const finite = v => typeof v === "number" && Number.isFinite(v);
const plural = (n, word) => `${n} ${word}${n === 1 ? "" : "s"}`;
// Whole metres, and "under 1 m" below that, as previewText says them.
const metres = m => { const r = Math.round(m); return `${r < 1 ? "under 1" : r} m`; };
// The words of an error, whatever was thrown.
function why(err) {
  try { return err instanceof Error || typeof err?.message === "string" ? err.message : String(err); }
  catch { return "unknown error"; }
}

// Fetch and parse the catalogue. Never throws or rejects:
// {ok: true, model, photoCount (photos with images), stopCount (stops with a photo)}, or
// {ok: false, error}, error one plain lowercase clause for the HUD's status line.
export async function loadCatalog(fetchImpl = globalThis.fetch, url = CATALOG_URL) {
  let res;
  try {
    res = await fetchImpl(url);
    if (!res) throw new Error("no response");
  } catch (err) {
    return {ok: false, error: `the photo catalogue could not be reached (${why(err)})`};
  }
  try {
    if (!res.ok) return {ok: false, error: `the server has no photo catalogue (HTTP ${res.status})`};
    const model = parseCatalog(await res.json());
    return {ok: true, model, photoCount: model.photos.filter(p => p.available).length,
            stopCount: photoStops(model).length};
  } catch (err) {
    return {ok: false, error: `the photo catalogue could not be read (${why(err)})`};
  }
}

// The stops to pin: one per stop with at least one photo (the 3D map's pins), with how
// many photos it has. [] for no model.
export function photoStops(model) {
  if (!model) return [];
  const groups = new Map(model.groups.map(g => [g.id, g]));
  return photoMarkers(model).map(({x, y, data: {groupId}}) => ({groupId, x, y, views: groups.get(groupId).photoIds.length}));
}

// The view wedge of a photo: a closed ring from the camera out along the arc of its field
// (heading - fov/2 to heading + fov/2, steps + 1 points at radiusM) and back to the camera.
// null when the photo has no position, heading or field, or radiusM or steps make no wedge.
export function wedgeRing(photo, radiusM = WEDGE_RADIUS_M, steps = 16) {
  if (!photo || ![photo.x, photo.y, photo.heading, photo.fov].every(finite) || photo.fov <= 0) return null;
  if (!finite(radiusM) || radiusM <= 0 || !Number.isInteger(steps) || steps < 1) return null;
  const {x, y} = photo, from = photo.heading - photo.fov * DEG / 2, step = photo.fov * DEG / steps;
  const arc = Array.from({length: steps + 1}, (_, i) => {
    const a = from + i * step;                    // north = +y, east = +x
    return [x + radiusM * Math.sin(a), y + radiusM * Math.cos(a)];
  });
  return [[x, y], ...arc, [x, y]];
}

// The 3D map opened on this photo's view, or null when the id cannot be a photo id.
export function open3dUrl(photoId) {
  const id = parsePhotoParam(photoId);
  return id === null ? null : "/3d/?photo=" + encodeURIComponent(id);
}

// The card of a stop: its views from north clockwise, each with its images (null when
// there are none), alt text, card rows, 3D link and wedge. null for no model, an unknown
// stop or a stop without photos.
export function stopCard(model, groupId) {
  if (!model) return null;
  const group = model.groups.find(g => g.id === groupId);
  const views = viewsOf(model, groupId);
  if (!group || !views.length) return null;
  return {
    groupId: group.id, x: group.x, y: group.y,
    title: `Rover photo stop · ${plural(views.length, "view")}`,
    views: views.map(v => ({
      id: v.id, direction: v.direction, available: v.available,
      thumb: v.images?.thumb ?? null, card: v.images?.card ?? null,
      alt: `Curiosity Navcam view looking ${v.direction}, sol ${v.sol}`,
      facts: photoFacts(v), open3d: open3dUrl(v.id), ring: wedgeRing(v),
    })),
  };
}

// The photo line under a station of the station list, station = {x, y} (Mars CRS metres).
// The 2D map has no ground elevation, so the field is checked side to side only; `text`
// is the 3D card's full sentence (for a tooltip), `short` the line itself. null for no
// model or when (x, y) is not a point.
export function stationPhotoLine(model, station) {
  if (!model) return null;
  const {x, y} = station ?? {};
  const result = nearestPhoto(model, {x, y});
  if (!result) return null;
  const text = previewText(result);
  if (!result.photo) {
    // Just past the limit the rounded distance would equal it ("nearest 150 m"): said as
    // previewText says it, "just over 150 m".
    const nearest = result.nearestM === null ? null : Math.round(result.nearestM);
    const max = `${Number(result.maxDistanceM.toFixed(1))} m`;
    const short = nearest === null ? "No photo nearby"
      : `No photo nearby (nearest ${nearest > result.maxDistanceM ? `${nearest} m` : `just over ${max}`})`;
    return {short, text, groupId: null, photoId: null, distanceM: null};
  }
  const {photo, distanceM, cameraSide, looking, inField} = result;
  const where = cameraSide === null ? "at the station" : `${metres(distanceM)} ${cameraSide}`;
  return {short: `Photo ${where}, looking ${looking}${inField ? " · station in its field" : ""}`,
          text, groupId: photo.groupId, photoId: photo.id, distanceM};
}
