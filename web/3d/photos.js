// Rover photos in the 3D map (P3, issue #46, blocks 2 and 3): pins, card, photo view
// and the preview on a station's card.
//
// Curiosity's Navcam photos (the catalogue of block 1, read by photos_model.js) are
// pinned at the stops where the rover took them. This file owns what the page does with
// them, and puts everything back when the photo view is left:
//   - pins: one per stop, on a MarkerLayer of their own (main.js makes it). Off until main.js
//     shows them (its "Show photo stops" box starts unticked: the 100 pins of the 383 photos
//     covered the route, #124); opening a photo view turns them on, so they are there after
//     Exit, wherever the photo was opened from. Hidden while the rehearsal runs (setVisible)
//     and while the photo view is on, so they do not sit on the very terrain being compared.
//   - card: the photo of one view, a button per view of the stop (its compass word),
//     the facts and "View from here". Where stops overlap, chooseStop() lists them first.
//   - photo view: the camera flies to where the rover camera was, with the relief at
//     true scale (the photo saw the real ground), the near plane brought in (the eye is
//     about 2 m above the ground, as in the rehearsal) and the Sun at the photo's local
//     time. The corrected photo (40 degrees square, no roll) lies over the 3D view on the
//     centred square that spans the same 40 degrees, so fading it in and out compares
//     the photo with the terrain. Exit or Escape puts back camera, field of view, near
//     plane, relief and Sun exactly.
//   - station preview (block 3): for main.js and the rehearsal's stop cards, the nearest
//     photo of a station (stationPreview), where it was taken and whether the station
//     falls in its field: a direction only, never a promise that the station is seen.
// A pose that does not fit the map (outside the box, camera under or too far above the
// shown ground) is still flown, and the reason is written in the bar: never hidden.
// The numbers are in photos_model.js (tested in Node). Text from the catalogue is set as
// text, never as HTML. Nothing is rendered here: onChange() asks main.js to draw.
import { MIN_EYE_HEIGHT_M, PHOTO_ROOT, nearestPhoto, parseCatalog, photoFacts, photoMarkers, photoPose, previewText,
         squareView, sunOf, viewsOf } from './photos_model.js';

const NEAR = 0.3;                  // m: near plane in the photo view, as in the rehearsal (the camera's own is 2 m)
const FLIGHT_S = 1;                // s: flight to a photo pose
const DEFAULT_OPACITY = 50;        // % of the photo over the terrain when the page opens
const RELIEF_REASON = 'Photo view: relief at true scale';
const DEG = Math.PI / 180;

function make(tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;           // catalogue text: never as HTML
  return node;
}

function button(text, title, onClick) {
  const b = make('button', '', text);
  b.type = 'button';
  if (title) b.title = title;
  b.addEventListener('click', onClick);
  return b;
}

const plural = (n, word) => `${n} ${word}${n === 1 ? '' : 's'}`;
const headingDeg = photo => ((Math.round(photo.heading / DEG) % 360) + 360) % 360;

// Plain data for the keyboard list, in catalogue order, using the same stops and views
// as the pins and cards. Missing images still have a card explaining their absence.
export function photoStopList(model) {
  if (!model) return [];
  return model.groups.filter(g => g.photoIds.length).map((g, i) => {
    const views = viewsOf(model, g.id), sols = [...new Set(views.map(v => v.sol))].sort((a, b) => a - b);
    return {id: g.id, label: `${i + 1} · Sol ${sols.join(', ')} · ${plural(views.length, 'view')}`};
  });
}

export class PhotoLayer {
  // markers: a MarkerLayer of its own for the photo pins; relief: {lock(reason),
  // unlock(k)} from main.js; showCard/hideCard: card.js; isBusy(): true while the
  // rehearsal runs; onChange(): something to draw; onShowPins(): the photo view turned
  // the pins on by itself (main.js ticks its box).
  constructor({terrain, controls, camera, canvas, relief, sunView, markers, showCard, hideCard,
               onChange = () => {}, isBusy = () => false, onShowPins = () => {}}) {
    Object.assign(this, {terrain, controls, camera, canvas, relief, sunView, markers, showCard, hideCard,
                         onChange, isBusy, onShowPins});
    this.model = null;             // parseCatalog() result once load() worked
    this.visible = false;          // what setVisible() asked for the pins (off until asked)
    this.opacity = DEFAULT_OPACITY;            // % of the overlay, kept from one photo view to the next
    this._view = null;             // the photo view while it is on (see _start)
    this._card = false;            // a card of this layer is shown
    this._listeners = [];
    // A pin's own select opens its stop. main.js may pick overlapping pins itself and
    // call chooseStop() instead.
    markers.onSelect = marker => {
      const groupId = marker && marker.data && marker.data.groupId;
      if (groupId) this.openGroup(groupId);
    };
  }

  // ---- public ------------------------------------------------------------------

  // Read the catalogue and pin its stops. Never throws: on failure there are no pins
  // and the page goes on without photos.
  async load(url = PHOTO_ROOT + 'catalog.json') {
    this.exit();
    this._closeCard();
    try {
      const res = await fetch(url);
      if (!res.ok) {
        throw new Error(res.status === 404 ? 'the server has no photo catalogue (HTTP 404)'
                                           : `the server answered HTTP ${res.status}`);
      }
      this.model = parseCatalog(await res.json());
      const pins = photoMarkers(this.model);
      this.markers.set(pins);
      this._showPins();
      this.onChange();
      return {ok: true, count: this.model.photos.length, error: null,
              stops: pins.length, problems: this.model.problems.length};
    } catch (err) {
      this.model = null;
      this.markers.set([]);
      this.onChange();
      return {ok: false, count: 0, error: err.message, stops: 0, problems: 0};
    }
  }

  // Show or hide the pins (main.js hides them while the rehearsal runs). Hiding them
  // also closes a photo card.
  setVisible(on) {
    this.visible = Boolean(on);
    this._showPins();
    if (!this.visible) this._closeCard();
    this.onChange();
  }

  // Card of a stop showing one of its views (the first, from north clockwise, when
  // photoId is not one of them). Does nothing while the rehearsal runs.
  openGroup(groupId, photoId = null) {
    if (this.isBusy() || !this.model) return false;
    const views = viewsOf(this.model, groupId);
    if (!views.length) return false;
    const photo = views.find(v => v.id === photoId) || views[0];
    const group = this.model.groups.find(g => g.id === groupId);

    const media = make('div', 'photo-media');
    media.append(this._cardImage(photo));
    if (views.length > 1) {
      const row = make('div', 'photo-views');
      row.setAttribute('role', 'group');
      row.setAttribute('aria-label', 'Views of this stop');
      // A stop often has two views towards the same compass point: those get their degrees.
      const repeated = word => views.filter(v => v.direction === word).length > 1;
      for (const v of views) {
        const label = repeated(v.direction) ? `${v.direction} ${headingDeg(v)}°` : v.direction;
        const b = button(label, `${v.camera}, heading ${headingDeg(v)}°`, () => this.openGroup(groupId, v.id));
        b.setAttribute('aria-pressed', String(v.id === photo.id));
        row.append(b);
      }
      media.append(row);
    }
    if (photo.sourceUrl) {                     // photos_model.js keeps only plain https addresses
      const a = make('a', 'photo-source', 'Original image (NASA)');
      a.href = photo.sourceUrl;
      a.target = '_blank';
      a.rel = 'noopener noreferrer';
      media.append(a);
    }
    const missing = group && group.missingSectors.length ? `No view here faces ${group.missingSectors.join(' or ')}.` : '';
    this._openCard({
      title: 'Rover photo stop',
      subtitle: `${plural(views.length, 'Navcam view')} · sol ${photo.sol}`,
      rows: [...photoFacts(photo), ['Photo', photo.id]],
      note: missing, media,
      actions: [{label: 'View from here', onClick: () => this.enter(photo.id)}]});
    return true;
  }

  // Card listing stops whose pins overlap where the user clicked: a button for each.
  chooseStop(groupIds) {
    if (this.isBusy() || !this.model) return false;
    const stops = [...new Set(groupIds)].map(id => ({id, views: viewsOf(this.model, id)})).filter(s => s.views.length);
    if (stops.length <= 1) return stops.length ? this.openGroup(stops[0].id) : false;
    const list = make('div', 'photo-stops');
    for (const {id, views} of stops) {
      const sols = [...new Set(views.map(v => v.sol))].join(', ');
      const b = button(`Sol ${sols} · ${plural(views.length, 'view')}`, null, () => this.openGroup(id));
      b.append(make('span', 'muted', id));
      list.append(b);
    }
    this._openCard({title: 'Rover photo stops', subtitle: `${stops.length} stops overlap here: choose one.`, media: list});
    return true;
  }

  // What a station's card shows of the rover photos at (x, y) (Mars CRS metres): media, an
  // element for the card's media slot (the nearest photo's thumbnail, the previewText
  // sentence and "sol N · credit"; only the sentence when no photo is near), and action,
  // the button that opens that photo's view, or null (no photo, the layer is busy, or
  // interactive is false: the rehearsal's cards). null when no catalogue is loaded or
  // (x, y) is not a point. The card is the caller's: nothing is shown or drawn here.
  stationPreview({x, y, label} = {}, {interactive = true} = {}) {
    if (!this.model) return null;
    const near = nearestPhoto(this.model, {x, y}, {groundElevation: this._groundElevation(x, y)});
    if (!near) return null;
    const {photo} = near, media = make('div', 'photo-preview');
    if (photo) media.append(this._previewImage(photo, near.looking, label));
    media.append(make('div', 'photo-preview-text', previewText(near)));
    if (photo) media.append(make('div', 'muted photo-preview-meta', `sol ${photo.sol} · ${photo.credit ?? 'credit not given'}`));
    // The button sits on the station's card, which the photo view has no room for.
    const action = interactive && photo && !this.isBusy()
      ? {label: 'View the rover photo', onClick: () => { if (this.enter(photo.id)) this.hideCard(); }} : null;
    return {media, action};
  }

  // Photo view of a photo. Called again while on, it changes photo and keeps what exit()
  // puts back. Does nothing while the rehearsal runs.
  enter(photoId) {
    if (this.isBusy() || !this.model || !this.model.byId.has(photoId)) return false;
    if (!this._view) this._start();
    this._closeCard();                         // the view needs the screen; the bar says what is shown
    this._show(this.model.byId.get(photoId));
    return true;
  }

  // Back to the view as it was: camera (with its field of view), near plane, relief and Sun.
  exit() {
    const v = this._view;
    if (!v) return false;
    const {controls, camera} = this, saved = v.saved;
    for (const [target, type, handler] of this._listeners) target.removeEventListener(type, handler);
    this._listeners = [];
    this._overlay.remove();
    this._bar.remove();
    this._overlay = this._bar = null;
    this._view = null;
    this._closeCard();
    document.body.classList.remove('photo-view');
    camera.near = saved.near;
    this.relief.unlock(saved.k);               // the ground first: the saved camera height belongs to it
    controls.restore(saved.pose);              // also puts the field of view back
    this.sunView.set(saved.sun);
    this._showPins();
    this.onChange();
    return true;
  }

  get active() { return Boolean(this._view); }

  // What the photo view shows, for the checks (null when it is off). pose: photoPose() as
  // given; flight: what was flown (eye raised to MIN_EYE_HEIGHT_M when the pose is lower);
  // square: squareView() of the canvas now; opacity: of the overlay, 0 to 1.
  get state() {
    const v = this._view;
    if (!v) return null;
    return {photoId: v.photo.id, groupId: v.photo.groupId, pose: {...v.pose}, flight: {...v.flight},
            square: {...v.square}, opacity: this.opacity / 100, overlay: v.photo.images.compare,
            overlayFailed: v.failed};
  }

  // ---- photo view ----------------------------------------------------------------

  _start() {
    const {controls, camera, terrain, sunView} = this;
    // Everything exit() must put back.
    this._view = {saved: {pose: controls.pose(), near: camera.near, k: terrain.k, sun: {...sunView.start}},
                  photo: null, views: [], index: 0, pose: null, flight: null, square: null,
                  flyingUntil: 0, failed: false};
    // A photo opened by link or from a card turns the photo stops on: hidden while the view
    // is on (_showPins), they are there after Exit.
    if (!this.visible) {
      this.visible = true;
      this.onShowPins();
    }
    controls.cancel();
    this.relief.lock(RELIEF_REASON);
    camera.near = NEAR;
    camera.updateProjectionMatrix();

    // Over the canvas and under the panels (they come later in the page); clicks go through.
    const img = this._overlay = make('img', 'photo-overlay');
    img.id = 'photo-overlay';
    img.alt = '';
    img.draggable = false;
    img.setAttribute('aria-hidden', 'true');
    this.canvas.after(img);
    this._bar = this._makeBar();
    document.body.append(this._bar);
    document.body.classList.add('photo-view');
    this._showPins();

    this._listen(window, 'resize', () => this._resize());
    this._listen(window, 'keydown', e => { if (e.key === 'Escape') this.exit(); });
  }

  // Show a photo: its Sun, the flight to its pose, the overlay and the bar.
  _show(photo) {
    const v = this._view, views = viewsOf(this.model, photo.groupId);
    const index = Math.max(0, views.findIndex(p => p.id === photo.id));
    const shown = views[index] || {...photo, direction: ''};
    const pose = photoPose(shown, this._groundElevation(shown.x, shown.y));
    v.square = this._fit();
    // The pose as given, except that the eye never goes under MIN_EYE_HEIGHT_M (it would
    // start inside the terrain). Outside the box there is no ground under the camera: the
    // terrain's edge height keeps the camera at the photo's own elevation.
    const [X, Z] = this.terrain.toLocal(shown.x, shown.y);
    const eye = pose.eyeHeight ?? shown.z - this.terrain.elevation(this.terrain.surfaceAt(X, Z, 1));
    v.flight = {x: pose.x, y: pose.y, eyeHeight: Math.max(MIN_EYE_HEIGHT_M, eye), heading: pose.heading,
                pitch: pose.pitch, fov: v.square.fovY, seconds: FLIGHT_S};
    Object.assign(v, {photo: shown, views, index, pose, failed: false});
    this.sunView.set(sunOf(shown, this.sunView.site.lonEastDeg));     // SunView's clock is the box centre's
    this._fly();
    this._showOverlay(shown);
    this._fillBar();
    this.onChange();
  }

  _fly() {
    const v = this._view;
    this.controls.cancel();
    this.controls.flyTo(v.flight);
    v.flyingUntil = performance.now() + FLIGHT_S * 1000;
  }

  // Previous / next view of the stop, round the compass.
  _step(by) {
    const v = this._view, n = v.views.length;
    if (n > 1) this._show(v.views[(v.index + by + n) % n]);
  }

  // DEM elevation (m) under a Mars point at relief x1, or null outside the box.
  _groundElevation(x, y) {
    const [X, Z] = this.terrain.toLocal(x, y), half = this.terrain.half;
    if (!(Math.abs(X) <= half && Math.abs(Z) <= half)) return null;
    return this.terrain.elevation(this.terrain.surfaceAt(X, Z, 1));
  }

  // Place the overlay on the centred square of the canvas. Returns squareView().
  _fit() {
    const {canvas} = this, square = squareView(canvas.clientWidth, canvas.clientHeight);
    const r = canvas.getBoundingClientRect();
    Object.assign(this._overlay.style, {left: `${r.left + square.left}px`, top: `${r.top + square.top}px`,
                                        width: `${square.side}px`, height: `${square.side}px`});
    return square;
  }

  // The window changed shape: a new square, and the field of view that matches it.
  _resize() {
    const v = this._view;
    if (!v) return;
    v.square = this._fit();
    v.flight.fov = v.square.fovY;
    if (performance.now() < v.flyingUntil) {
      this._fly();                             // a flight ends on the field it was given: give it the new one
    } else {
      this.camera.fov = v.square.fovY;
      this.camera.updateProjectionMatrix();
    }
    this.onChange();
  }

  _showOverlay(photo) {
    const img = this._overlay, url = photo.images.compare;
    img.style.opacity = String(this.opacity / 100);
    img.onload = img.onerror = null;           // an answer for the photo shown before is dropped
    if (!url) {
      img.removeAttribute('src');
      img.hidden = true;
      return;
    }
    img.hidden = false;
    img.onerror = () => {
      if (!this._view || this._overlay !== img) return;
      this._view.failed = true;
      img.hidden = true;
      this._fillBar();
    };
    img.src = url;
  }

  // ---- bar -----------------------------------------------------------------------

  _makeBar() {
    const bar = make('div', 'panel');
    bar.id = 'photo-bar';
    bar.setAttribute('role', 'region');
    bar.setAttribute('aria-label', 'Photo view');
    this._barTitle = make('div', 'photo-bar-title');
    this._barId = make('div', 'muted photo-bar-id');
    this._barWarn = make('div', 'warn');
    this._barWarn.setAttribute('role', 'status');
    this._barNote = make('div', 'muted photo-bar-note');

    const fade = make('div', 'photo-bar-row');
    const label = make('label', 'muted', 'Photo over the terrain');
    const slider = make('input');
    Object.assign(slider, {type: 'range', id: 'photo-opacity', min: 0, max: 100, step: 1, value: this.opacity});
    label.htmlFor = 'photo-opacity';
    const value = make('span', 'photo-opacity-value', `${this.opacity} %`);
    slider.addEventListener('input', () => {
      this.opacity = Number(slider.value);
      value.textContent = `${this.opacity} %`;
      if (this._overlay) this._overlay.style.opacity = String(this.opacity / 100);
    });
    fade.append(label, slider, value);

    const row = make('div', 'photo-bar-row');
    this._prev = button('◀ Previous', 'Previous view of this stop', () => this._step(-1));
    this._next = button('Next ▶', 'Next view of this stop', () => this._step(1));
    const realign = button('Realign', "Back to the rover camera's pose", () => this._fly());
    const exit = button('Exit', 'Back to the view as it was (Esc)', () => this.exit());
    this._prev.id = 'photo-prev'; this._next.id = 'photo-next';
    realign.id = 'photo-realign'; exit.id = 'photo-exit';
    row.append(this._prev, this._next, realign, exit);

    bar.append(this._barTitle, this._barId, this._barWarn, this._barNote, fade, row);
    return bar;
  }

  _fillBar() {
    const v = this._view, p = v.photo;
    this._barTitle.textContent = `${p.camera} looking ${p.direction} (${headingDeg(p)}°)`;
    this._barId.textContent = `${p.id} · sol ${p.sol} · view ${v.index + 1} of ${v.views.length}`;
    let warn = '';
    if (!v.pose.ok) {
      const raised = v.pose.eyeHeight !== null && v.pose.eyeHeight < MIN_EYE_HEIGHT_M;
      warn = `⚠ ${v.pose.reason}` + (raised ? ` It is shown from ${MIN_EYE_HEIGHT_M} m above the ground instead.` : '');
    }
    this._barWarn.textContent = warn;
    this._barWarn.hidden = !warn;
    const note = !p.images.compare ? 'No corrected photo for this view: only the terrain is shown.'
               : v.failed ? 'The corrected photo could not be loaded: only the terrain is shown.' : '';
    this._barNote.textContent = note;
    this._barNote.hidden = !note;
    this._prev.disabled = this._next.disabled = v.views.length < 2;
  }

  // ---- card and pins -------------------------------------------------------------

  // The card's image of a view, or a short text when there is none or it does not load.
  _cardImage(photo) {
    const missing = text => make('div', 'photo-missing', text);
    if (!photo.images.card) return missing('Image not available for this view.');
    const img = make('img', 'photo-card-img');
    img.alt = `Navcam photo looking ${photo.direction}`;
    img.decoding = 'async';
    img.addEventListener('error', () => img.replaceWith(missing('Image not available: it could not be loaded.')),
                         {once: true});
    img.src = photo.images.card;
    return img;
  }

  // The thumbnail of a station preview, or a short text when it does not load.
  _previewImage(photo, looking, label) {
    const missing = text => make('div', 'photo-missing', text);
    if (!photo.images.thumb) return missing('Image not available for this photo.');
    const img = make('img', 'photo-preview-img');
    img.alt = `Navcam photo looking ${looking}, the nearest to ${label || 'this station'}`;
    img.decoding = 'async';
    img.addEventListener('error', () => img.replaceWith(missing('Image not available: it could not be loaded.')),
                         {once: true});
    img.src = photo.images.thumb;
    return img;
  }

  _openCard(card) {
    this.showCard({...card, onClose: () => { this._card = false; }});
    this._card = true;                         // after showCard: it closes the card it replaces first
    this.onChange();
  }

  // Close the card only if it is one of this layer's (never a station's or the rehearsal's).
  _closeCard() {
    if (this._card) this.hideCard();
  }

  _showPins() {
    this.markers.group.visible = this.visible && !this._view;
  }

  _listen(target, type, handler) {
    target.addEventListener(type, handler);
    this._listeners.push([target, type, handler]);
  }
}
