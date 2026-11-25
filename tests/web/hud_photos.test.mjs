// Rover photos in the 2D HUD (web/hud_photos.js). Run from the repo root:  node --test tests/web/
// Uses the 3D map's photo fixture (tests/viz3d/fixtures/photos_catalog.json, read only):
// three stops of the real catalogue, 7 Navcam photos (1, 2 and 4 views).
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';

import * as P from '../../web/3d/photos_model.js';
import * as H from '../../web/hud_photos.js';

const RAW = JSON.parse(readFileSync(new URL('../viz3d/fixtures/photos_catalog.json', import.meta.url), 'utf8'));
const MODEL = P.parseCatalog(structuredClone(RAW));
const DEG = Math.PI / 180;
const close = (a, b, tol, what = '') => assert.ok(Math.abs(a - b) <= tol, `${what} ${a} vs ${b} (tolerance ${tol})`);
// The catalogue changed by `change` (a function that edits a copy).
const changed = change => { const c = structuredClone(RAW); change(c); return c; };
// A fake fetch: answers `res` (or what `res` makes of the url), and remembers the urls asked.
const fakeFetch = res => { const urls = []; const f = async url => { urls.push(url); return typeof res === 'function' ? res(url) : res; }; f.urls = urls; return f; };
const answer = (json, status = 200) => ({ok: status >= 200 && status < 300, status, json: async () => structuredClone(json)});
const bearing = ([x0, y0], [x1, y1]) => ((Math.atan2(x1 - x0, y1 - y0) / DEG) % 360 + 360) % 360;
const NOT_SEEN = /\b(visible|visibility|seen|see|sees|shows?|can)\b/i;

test('constants: the catalogue address of the 3D map, and the wedge as long as the photo line looks', () => {
  assert.equal(H.CATALOG_URL, '/tiles/3d/photos/catalog.json');
  assert.equal(H.CATALOG_URL, P.PHOTO_ROOT + 'catalog.json');
  assert.equal(H.WEDGE_RADIUS_M, P.PREVIEW_MAX_M);
});

test('loadCatalog: the fixture loads, with the photos that have images and the stops that have photos', async () => {
  const f = fakeFetch(answer(RAW));
  const r = await H.loadCatalog(f);
  assert.deepEqual(f.urls, [H.CATALOG_URL]);
  assert.deepEqual(Object.keys(r).sort(), ['model', 'ok', 'photoCount', 'stopCount']);
  assert.deepEqual([r.ok, r.photoCount, r.stopCount], [true, 7, 3]);
  assert.deepEqual(r.model, MODEL);
  const other = fakeFetch(answer(RAW));
  assert.equal((await H.loadCatalog(other, '/elsewhere.json')).ok, true);
  assert.deepEqual(other.urls, ['/elsewhere.json']);
  // Photos without images are not counted; their stop still is.
  const blank = changed(c => { for (const p of c.photos) if (p.group_id === 'stop_0079') p.assets.status = 'missing_source'; });
  const b = await H.loadCatalog(fakeFetch(answer(blank)));
  assert.deepEqual([b.ok, b.photoCount, b.stopCount], [true, 3, 3]);
  // A stop whose only photo did not parse has no pin, so it is not counted.
  const lost = changed(c => { delete c.photos[0].pose; });
  const l = await H.loadCatalog(fakeFetch(answer(lost)));
  assert.deepEqual([l.ok, l.photoCount, l.stopCount], [true, 6, 2]);
  const empty = await H.loadCatalog(fakeFetch(answer({schema_version: 1, groups: [], photos: []})));
  assert.deepEqual([empty.ok, empty.photoCount, empty.stopCount], [true, 0, 0]);
});

test('loadCatalog: no catalogue, no server or a bad file is one plain clause, never a rejection', async () => {
  assert.deepEqual(await H.loadCatalog(fakeFetch(answer(null, 404))),
                   {ok: false, error: 'the server has no photo catalogue (HTTP 404)'});
  assert.deepEqual(await H.loadCatalog(fakeFetch(answer(RAW, 500))),
                   {ok: false, error: 'the server has no photo catalogue (HTTP 500)'});
  const offline = async () => { throw new TypeError('Failed to fetch'); };
  assert.deepEqual(await H.loadCatalog(offline),
                   {ok: false, error: 'the photo catalogue could not be reached (Failed to fetch)'});
  const notJson = {ok: true, status: 200, json: async () => { throw new SyntaxError('Unexpected token < in JSON at position 0'); }};
  assert.deepEqual(await H.loadCatalog(fakeFetch(notJson)),
                   {ok: false, error: 'the photo catalogue could not be read (Unexpected token < in JSON at position 0)'});
  assert.deepEqual(await H.loadCatalog(fakeFetch(answer({...RAW, schema_version: 2}))),
                   {ok: false, error: 'the photo catalogue could not be read (photo catalogue schema_version 2 is not 1)'});
  // Anything else that goes wrong is still an answer, never a throw or a rejection.
  const odd = [
    [fakeFetch(answer(null, 403)), /^the server has no photo catalogue \(HTTP 403\)$/],
    [fakeFetch(answer('catalog')), /could not be read \(not a photo catalogue/],
    [fakeFetch(answer({schema_version: 1, groups: {}, photos: []})), /could not be read \(not a photo catalogue/],
    [fakeFetch(null), /^the photo catalogue could not be reached \(no response\)$/],
    [fakeFetch({ok: true, status: 200}), /could not be read/],                         // no json()
    [() => { throw 'boom'; }, /^the photo catalogue could not be reached \(boom\)$/],   // throws at once, not an Error
    [async () => { throw Object.create(null); }, /could not be reached \(unknown error\)$/],
    [null, /could not be reached/],                                                       // not a fetch at all
    ['fetch', /could not be reached/],
  ];
  for (const [fetchImpl, error] of odd) {
    const r = await H.loadCatalog(fetchImpl);
    assert.deepEqual(Object.keys(r), ['ok', 'error']);
    assert.equal(r.ok, false);
    assert.match(r.error, error);
    // One plain lowercase clause: no capital, no full stop at its end.
    assert.match(r.error, /^the (server has no photo catalogue|photo catalogue could not be (reached|read)) \(.+\)$/);
  }
});

test('loadCatalog: by default, the page fetch and the catalogue address of the 3D map', async () => {
  const saved = globalThis.fetch, f = fakeFetch(answer(RAW));
  globalThis.fetch = f;
  try {
    const r = await H.loadCatalog();
    assert.deepEqual([r.ok, r.photoCount, r.stopCount], [true, 7, 3]);
    assert.deepEqual(f.urls, ['/tiles/3d/photos/catalog.json']);
  } finally {
    globalThis.fetch = saved;
  }
});

test('photoStops: the pins of the 3D map, each with how many photos its stop has', () => {
  const stops = H.photoStops(MODEL);
  const markers = P.photoMarkers(MODEL);
  assert.deepEqual(stops.map(s => [s.groupId, s.x, s.y]), markers.map(m => [m.data.groupId, m.x, m.y]));
  assert.deepEqual(stops, [
    {groupId: 'stop_0000', x: RAW.groups[0].representative.xy[0], y: RAW.groups[0].representative.xy[1], views: 1},
    {groupId: 'stop_0018', x: RAW.groups[1].representative.xy[0], y: RAW.groups[1].representative.xy[1], views: 2},
    {groupId: 'stop_0079', x: RAW.groups[2].representative.xy[0], y: RAW.groups[2].representative.xy[1], views: 4},
  ]);
  // A stop with no photo left has no pin; a stop that lost a view counts the views it has.
  const m = P.parseCatalog(changed(c => { delete c.photos[0].pose; delete c.photos[3].pose; }));
  assert.deepEqual(H.photoStops(m).map(s => [s.groupId, s.views]), [['stop_0018', 2], ['stop_0079', 3]]);
  assert.deepEqual(H.photoStops(m).map(s => s.groupId), P.photoMarkers(m).map(x => x.data.groupId));
  assert.deepEqual(H.photoStops(null), []);
});

test('wedgeRing: from the camera along the arc of its field and back, north = +y, east = +x', () => {
  const cam = {x: 100, y: 200, heading: 0, fov: 40};
  const ring = H.wedgeRing(cam);
  assert.equal(ring.length, 16 + 3);
  assert.deepEqual(ring[0], [100, 200]);
  assert.deepEqual(ring.at(-1), [100, 200]);
  const arc = ring.slice(1, -1);
  assert.equal(arc.length, 17);
  close(arc[8][0], 100, 1e-9, 'heading 0: the middle of the arc is due north (x)');
  close(arc[8][1], 200 + H.WEDGE_RADIUS_M, 1e-9, 'heading 0: the middle of the arc is due north (y)');
  for (const p of arc) close(Math.hypot(p[0] - 100, p[1] - 200), H.WEDGE_RADIUS_M, 1e-9, 'on the radius');
  // The arc spans the field, from its left edge to its right edge, in equal steps.
  close(bearing([100, 200], arc[0]), 340, 1e-9, 'left edge');
  close(bearing([100, 200], arc.at(-1)), 20, 1e-9, 'right edge');
  for (let i = 1; i < arc.length; i++) {
    const turn = ((bearing([100, 200], arc[i]) - bearing([100, 200], arc[i - 1])) % 360 + 360) % 360;
    close(turn, 40 / 16, 1e-9, `step ${i}`);
  }
  // Heading east: the middle is due east; another radius and number of steps.
  const east = H.wedgeRing({...cam, heading: Math.PI / 2}, 50, 4);
  assert.equal(east.length, 4 + 3);
  close(east[3][0], 150, 1e-9, 'heading east (x)');
  close(east[3][1], 200, 1e-9, 'heading east (y)');
  close(bearing([100, 200], east[1]), 70, 1e-9);
  close(bearing([100, 200], east[5]), 110, 1e-9);
  assert.equal(H.wedgeRing(cam, 10, 1).length, 4);
  // The real photos: the middle of each wedge lies along its heading, its edges fov apart.
  for (const photo of MODEL.photos) {
    const r = H.wedgeRing(photo);
    assert.deepEqual([r[0], r.at(-1)], [[photo.x, photo.y], [photo.x, photo.y]]);
    const mid = bearing([photo.x, photo.y], r[9]);
    close(((mid - photo.heading / DEG) % 360 + 540) % 360 - 180, 0, 1e-6, `${photo.id} middle`);
    const span = ((bearing([photo.x, photo.y], r[17]) - bearing([photo.x, photo.y], r[1])) % 360 + 360) % 360;
    close(span, photo.fov, 1e-6, `${photo.id} span`);
  }
});

test('wedgeRing: null without a position, heading or field, or with no radius', () => {
  const cam = {x: 100, y: 200, heading: 0, fov: 40};
  for (const bad of [{x: NaN}, {y: Infinity}, {heading: null}, {heading: '0'}, {fov: 0}, {fov: -5}, {fov: undefined}, {x: undefined}]) {
    assert.equal(H.wedgeRing({...cam, ...bad}), null, JSON.stringify(bad));
  }
  for (const r of [0, -1, NaN, Infinity, '150']) assert.equal(H.wedgeRing(cam, r), null, `radius ${r}`);
  for (const s of [0, -2, 1.5, NaN]) assert.equal(H.wedgeRing(cam, 150, s), null, `steps ${s}`);
  for (const photo of [null, undefined, 42]) assert.equal(H.wedgeRing(photo), null);
});

test('open3dUrl: a real photo id opens the 3D map on it; anything else is null', () => {
  for (const p of MODEL.photos) assert.equal(H.open3dUrl(p.id), `/3d/?photo=${p.id}`);
  assert.equal(H.open3dUrl('a-b_C9'), '/3d/?photo=a-b_C9');
  for (const bad of ['../x', '<b>', '', 'a'.repeat(81), 'a/b', 'x%2F', ' NRB_1', 'a b', null, undefined, 42]) {
    assert.equal(H.open3dUrl(bad), null, JSON.stringify(bad));
  }
});

test('stopCard: the views of a stop from north clockwise, each with images, words, rows, link and wedge', () => {
  const card = H.stopCard(MODEL, 'stop_0079');
  const group = MODEL.groups.find(g => g.id === 'stop_0079');
  assert.deepEqual([card.groupId, card.x, card.y], ['stop_0079', group.x, group.y]);
  assert.equal(card.title, 'Rover photo stop · 4 views');
  assert.equal(H.stopCard(MODEL, 'stop_0018').title, 'Rover photo stop · 2 views');
  assert.equal(H.stopCard(MODEL, 'stop_0000').title, 'Rover photo stop · 1 view');
  const views = P.viewsOf(MODEL, 'stop_0079');
  assert.deepEqual(card.views.map(v => [v.id, v.direction]), views.map(v => [v.id, v.direction]));
  assert.deepEqual(card.views.map(v => v.direction), ['north-east', 'east', 'south-west', 'north']);
  for (const [i, v] of card.views.entries()) {
    const photo = MODEL.byId.get(v.id);
    assert.deepEqual(Object.keys(v), ['id', 'direction', 'available', 'thumb', 'card', 'alt', 'facts', 'open3d', 'ring']);
    assert.deepEqual([v.available, v.thumb, v.card], [true, photo.images.thumb, photo.images.card]);
    assert.equal(v.alt, `Curiosity Navcam view looking ${views[i].direction}, sol 4667`);
    assert.deepEqual(v.facts, P.photoFacts(photo));
    assert.equal(v.open3d, H.open3dUrl(v.id));
    assert.deepEqual(v.ring, H.wedgeRing(photo));
    for (const s of [v.alt, ...v.facts.flat()]) assert.doesNotMatch(s, /[<>&]/);
  }
  assert.equal(H.stopCard(MODEL, 'stop_0000').views[0].alt, 'Curiosity Navcam view looking south-west, sol 4450');
  // No images: the view stays, said as not available, without image addresses.
  const blank = P.parseCatalog(changed(c => { c.photos[0].assets.status = 'missing_source'; }));
  const v = H.stopCard(blank, 'stop_0000').views[0];
  assert.deepEqual([v.available, v.thumb, v.card], [false, null, null]);
  assert.ok(v.open3d && v.ring);
  // Unknown stop, a stop without photos, no model.
  assert.equal(H.stopCard(MODEL, 'stop_9999'), null);
  assert.equal(H.stopCard(P.parseCatalog(changed(c => { delete c.photos[0].pose; })), 'stop_0000'), null);
  assert.equal(H.stopCard(null, 'stop_0000'), null);
  assert.equal(H.stopCard(undefined, 'stop_0000'), null);
});

const shorts = [];                                       // every short line made below, for the last test
const line = (model, station) => { const l = H.stationPhotoLine(model, station); if (l) shorts.push(l.short); return l; };

test('stationPhotoLine: a photo near the station, where it was taken and where it looks', () => {
  // A station 87 m north-east of stop_0000's only camera, which looks south-west (208°, away from it).
  const photo = MODEL.photos[0];
  const station = {x: photo.x + 87 * Math.sin(45 * DEG), y: photo.y + 87 * Math.cos(45 * DEG)};
  const l = line(MODEL, station);
  assert.deepEqual(Object.keys(l), ['short', 'text', 'groupId', 'photoId', 'distanceM']);
  assert.equal(l.short, 'Photo 87 m south-west, looking south-west');
  assert.equal(l.text, P.previewText(P.nearestPhoto(MODEL, station)));
  assert.equal(l.text, 'Nearest rover photo: 87 m south-west of the station, looking south-west; ' +
                       'the station is 163° to the left of its centre, outside its field.');
  assert.deepEqual([l.groupId, l.photoId], ['stop_0000', photo.id]);
  close(l.distanceM, 87, 1e-6);
  // A station 30 m out along stop_0079's east view: in its field (side to side only in 2D).
  const east = MODEL.byId.get('NRB_811806355EDR_F1190000NCAM00288M_');
  const ahead = {x: east.x + 30 * Math.sin(east.heading), y: east.y + 30 * Math.cos(east.heading)};
  const a = line(MODEL, ahead);
  assert.equal(a.short, 'Photo 30 m west, looking east · station in its field');
  assert.equal(a.text, P.previewText(P.nearestPhoto(MODEL, ahead)));
  assert.match(a.text, /inside its field from side to side \(not checked up and down; the terrain may still hide it\)\.$/);
  assert.deepEqual([a.groupId, a.photoId], ['stop_0079', east.id]);
  // On the camera's very spot, and under a metre from it.
  const at = line(MODEL, {x: photo.x, y: photo.y});
  assert.equal(at.short, 'Photo at the station, looking south-west');
  assert.deepEqual([at.photoId, at.distanceM], [photo.id, 0]);
  const near = line(MODEL, {x: photo.x + 0.4 * Math.sin(45 * DEG), y: photo.y + 0.4 * Math.cos(45 * DEG)});
  assert.equal(near.short, 'Photo under 1 m south-west, looking south-west');
  assert.match(near.text, /under 1 m south-west of the station/);
});

test('stationPhotoLine: no photo near, with how far the nearest is; null without a model or a point', () => {
  const [a, b] = MODEL.groups;
  const mid = {x: (a.x + b.x) / 2, y: (a.y + b.y) / 2};
  const miss = line(MODEL, mid);
  assert.deepEqual(miss, {short: 'No photo nearby (nearest 180 m)',
                          text: 'No rover photo within 150 m of this station (the nearest is 180 m away).',
                          groupId: null, photoId: null, distanceM: null});
  assert.equal(miss.text, P.previewText(P.nearestPhoto(MODEL, mid)));
  const far = line(MODEL, {x: a.x + 412, y: a.y});
  assert.match(far.short, /^No photo nearby \(nearest \d+ m\)$/);
  const empty = P.parseCatalog({schema_version: 1, groups: [], photos: []});
  assert.deepEqual(line(empty, mid), {short: 'No photo nearby',
                                      text: 'No rover photo within 150 m of this station (no rover photo is published for this map).',
                                      groupId: null, photoId: null, distanceM: null});
  for (const station of [{x: NaN, y: 0}, {x: 1, y: Infinity}, {x: '1000', y: 2000}, {}, undefined, null]) {
    assert.equal(H.stationPhotoLine(MODEL, station), null, JSON.stringify(station));
  }
  assert.equal(H.stationPhotoLine(null, mid), null);
  assert.equal(H.stationPhotoLine(undefined, mid), null);
});

// Stations due north of stop_0000's only camera, at the 150 m limit; the other stops are far from there.
test('stationPhotoLine: just inside the 150 m limit (149.7 m) is still a photo', () => {
  const photo = MODEL.photos[0];
  const inside = line(MODEL, {x: photo.x, y: photo.y + 149.7});
  assert.equal(inside.short, 'Photo 150 m south, looking south-west');
  assert.deepEqual([inside.groupId, inside.photoId], ['stop_0000', photo.id]);
  close(inside.distanceM, 149.7, 1e-6);
});

test('stationPhotoLine: just past the 150 m limit (150.3 m) says "just over 150 m", not "150 m"', () => {
  const photo = MODEL.photos[0];
  const past = {x: photo.x, y: photo.y + 150.3};
  const miss = line(MODEL, past);
  assert.deepEqual(miss, {short: 'No photo nearby (nearest just over 150 m)',
                          text: 'No rover photo within 150 m of this station (the nearest is just over 150 m away).',
                          groupId: null, photoId: null, distanceM: null});
  assert.equal(miss.text, P.previewText(P.nearestPhoto(MODEL, past)));
});

test('stationPhotoLine: the short line gives a direction only, never that the station is seen', () => {
  // Stations around every real stop, near and far.
  for (const g of MODEL.groups) {
    for (const d of [0, 5, 40, 120, 200]) {
      for (const deg of [0, 90, 180, 270]) line(MODEL, {x: g.x + d * Math.sin(deg * DEG), y: g.y + d * Math.cos(deg * DEG)});
    }
  }
  assert.ok(shorts.length >= 60, `${shorts.length} lines`);
  assert.ok(shorts.some(s => s.endsWith(' · station in its field')));
  assert.ok(shorts.some(s => s.startsWith('No photo nearby')));
  for (const s of shorts) {
    assert.match(s, /^(Photo (at the station|(under 1|\d+) m [a-z-]+), looking [a-z-]+( · station in its field)?|No photo nearby( \(nearest (just over )?\d+ m\))?)$/, s);
    assert.doesNotMatch(s, NOT_SEEN, s);
    assert.doesNotMatch(s, /[<>&.]/, s);
  }
});
