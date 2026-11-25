// 3D map of the boxwork box (P1, issue #42): entry point.
//
// URL parameters (all optional):
//   q=low|high      quality preset (default: low on touch or small screens, else high)
//   k=1..5          local relief exaggeration at the start (default 2; the panel has a slider)
//   plan=default    ask the server for a plan with the default settings on load, as the
//                   "Plan with default settings" button does (see api.js)
//   sol=4711        Curiosity sol whose Sun lights the scene (default 4711; sun.js)
//   lt=15:00        local true solar time at the box centre (default: the plan's best
//                   time to leave from GET /plan/departure, else 15:00)
//   light=az,el     debug: a fixed light direction in degrees (azimuth from north towards
//                   east, elevation) instead of the Sun of Mars
//   shadows=0       start without cast shadows (the Sun section has the switch; shadows.js)
//   fps=1           render every frame and show frames per second
//   spin=1          slowly orbit the camera (to measure fps without touching anything)
//   check=shading   run a check from checks.js (shading, route, rehearse, sun, shadows) and show its
//                   result as JSON
//   drag=pan        map-style mouse: drag moves, right-drag rotates (default: drag rotates)
//   view=x,y,z,heading,pitch   where the free-flight camera starts: Mars CRS metres, the
//                   camera's elevation in metres (DEM datum), heading from north and pitch
//                   below the horizon in degrees (view_link.js). "Copy link to this view"
//                   in the About section writes it.
//   photo=<id>      open a rover photo (P3, photos.js) in the photo view, from where the
//                   Navcam took it; the photo stops are shown after it
// Names and number formats of the panel come from the shared glossary (web/terms.js, #166).
import '../terms.js';
import * as THREE from 'three';
import { loadLastPlan, loadRubric, requestDefaultPlan } from './api.js';
import { hideCard, showCard, stationCard } from './card.js';
import { TerrainControls } from './controls.js';
import { MarkerLayer } from './markers.js';
import { GroundLines, RouteOverlay } from './overlays.js';
import { mainRoute, parsePlan, planMarkers, planMessages, stationList } from './plan_model.js';
import { Rehearsal } from './rehearse.js';
import { Shadows } from './shadows.js';
import { SunView } from './sun.js';
import { clockText, parseClock, parseSol } from './sun_model.js';
import { Terrain, BUILD_HINT } from './terrain.js';
import { formatView, parseView, viewLink } from './view_link.js';
import { Walk } from './walk.js';

const T = globalThis.TERMS;
const ui = id => document.getElementById(id);
const params = new URLSearchParams(location.search);
const SKY = 0xd8b690;                       // dusty butterscotch sky (a look, not a model)
const DEG = Math.PI / 180;
// Text from the address or from an error, made safe to put inside HTML.
const esc = text => String(text).replace(/[&<>"']/g, ch => `&#${ch.charCodeAt(0)};`);

function pickQuality() {
  const q = params.get('q');
  if (q === 'low' || q === 'high') return q;
  const small = Math.min(screen.width, screen.height) < 900;
  return navigator.maxTouchPoints > 0 || small || (navigator.deviceMemory || 8) <= 4 ? 'low' : 'high';
}

// Unit vector towards the light. Azimuth from north, clockwise; scene Z is south.
function sunDirection(azDeg, elDeg) {
  const az = THREE.MathUtils.degToRad(azDeg), el = THREE.MathUtils.degToRad(elDeg);
  return new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el));
}

// Centred message box. It can always be closed: the cross, the Escape key or a
// click outside it. An Escape that closes it is marked as used (defaultPrevented), so
// that the rehearsal, which also listens to Escape, only pauses (rehearse.js).
function showMessage(html) {
  const box = ui('message');
  box.innerHTML = `<button id="message-close" title="Close (Esc)" aria-label="Close">×</button>${html}`;
  box.hidden = false;
  ui('message-close').addEventListener('click', hideMessage);
}

function hideMessage() { ui('message').hidden = true; }

window.addEventListener('keydown', e => {
  if (e.key !== 'Escape' || ui('message').hidden) return;
  hideMessage();
  e.preventDefault();
});
window.addEventListener('pointerdown', e => {
  if (!ui('message').hidden && !ui('message').contains(e.target)) hideMessage();
});

async function main() {
  // Only Plan starts open (#124); on a phone or a small window it starts closed too, so the
  // panel does not cover most of the view.
  if (window.innerWidth < 700 || window.innerHeight < 500) ui('plan-box').open = false;
  const quality = pickQuality();
  const canvas = ui('view');
  // The stencil buffer is used by the route's see-through pass (overlays.js).
  const renderer = new THREE.WebGLRenderer({canvas, antialias: quality === 'high', stencil: true,
                                            powerPreference: 'high-performance'});
  renderer.setPixelRatio(Math.min(window.devicePixelRatio, quality === 'high' ? 2 : 1.5));

  const scene = new THREE.Scene();
  scene.background = new THREE.Color(SKY);
  scene.fog = new THREE.Fog(SKY, 4000, 12000);

  const camera = new THREE.PerspectiveCamera(50, 1, 2, 30000);

  ui('readout').textContent = 'Loading terrain…';
  let terrain;
  try {
    terrain = await Terrain.load(quality, {
      maxAnisotropy: renderer.capabilities.getMaxAnisotropy(),
      onProgress: step => { ui('readout').textContent = `Loading ${step}…`; },
    });
  } catch (err) {
    console.error(err);
    ui('readout').textContent = 'Terrain not loaded';
    ui('plan-source').textContent = 'No terrain to draw the plan on.';
    ui('station-list-note').textContent = ui('photo-list-note').textContent = 'Terrain not loaded: stops are unavailable.';
    showMessage(`${esc(err.message.replace(BUILD_HINT, ''))}<code>${BUILD_HINT}</code>`);
    return;
  }
  scene.add(terrain.group);
  ui('quality-label').textContent = `Quality: ${quality} · mesh every ${terrain.step} m · ` +
    `${(terrain.triangles / 1e6).toFixed(1)} M triangles`;

  // Light: one "sun" plus sky light, so slopes facing away are dim but not black.
  // Where the sun is and how strong both are is set by sun.js (SunView, below).
  const sun = new THREE.DirectionalLight(0xfff2e2, 2.6);
  const hemi = new THREE.HemisphereLight(0xf0d6b8, 0x6b4a36, 1.1);
  scene.add(sun, sun.target, hemi);

  // Camera: an arcball on the terrain (controls.js). Start south of the box looking
  // north, like a tilted map.
  const controls = new TerrainControls(camera, canvas, terrain, scene,
                                       {leftDrag: params.get('drag') === 'pan' ? 'pan' : 'rotate'});
  controls.autoRotate = params.get('spin') === '1';
  controls.home();
  // While rehearsing or walking the camera belongs to that mode: these two do nothing then.
  const busy = () => rehearsal.active || walk.active;
  ui('compass').addEventListener('click', () => { if (!busy()) controls.faceNorth(); });
  ui('home').addEventListener('click', () => { if (!busy()) controls.home(); });

  // What is drawn on the ground: the route of the plan, the markers, and the walkback
  // lines of the rehearsal.
  const overlays = new RouteOverlay(terrain, scene);
  const markers = new MarkerLayer(terrain, scene, camera);
  const photoMarkers = new MarkerLayer(terrain, scene, camera);       // rover photo stops (P3): their own layer
  photoMarkers.group.name = 'photo markers';
  const walkbackLines = new GroundLines(terrain, scene, 'walkback');

  function resize() {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false);
    camera.aspect = w / h;
    camera.updateProjectionMatrix();
    overlays.setResolution(w, h);
    markers.setResolution(w, h);
    photoMarkers.setResolution(w, h);
    walkbackLines.setResolution(w, h);
    shownFov = camera.fov;
    dirty = true;
  }

  // Render only when something changed, unless fps/spin ask for every frame.
  const continuous = params.get('fps') === '1' || controls.autoRotate;
  let dirty = true, frames = 0, since = performance.now(), fps = 0, last = performance.now();
  let shownFov = camera.fov;                   // the pins are sized for this field of view
  window.addEventListener('resize', resize);
  resize();

  function readout() {
    // What is at the middle of the screen; while rehearsing or walking, where the walker is.
    const centre = busy() ? null : controls.centreGround();
    let text = 'Looking at the sky';
    if (rehearsal.active) {
      text = rehearsal.positionText();
    } else if (walk.active) {
      text = walk.positionText();
    } else if (centre && Math.abs(centre[0]) <= terrain.half && Math.abs(centre[2]) <= terrain.half) {
      const [x, y] = terrain.toMars(centre[0], centre[2]);
      text = `x ${x.toFixed(0)} m · y ${y.toFixed(0)} m · elevation ` +
        `${terrain.elevation(terrain.heightAt(centre[0], centre[2], 1)).toFixed(0)} m`;
    } else if (centre) {
      text = 'Outside the study box';
    }
    ui('readout').textContent = continuous ? `${text} · ${fps.toFixed(0)} fps` : text;
    // The needle shows where north is on screen: it turns against the heading.
    const heading = rehearsal.active ? rehearsal.viewYaw : walk.active ? walk.viewYaw : controls.yaw;
    ui('compass-needle').setAttribute('transform', `rotate(${-THREE.MathUtils.radToDeg(heading)})`);
  }

  // Shadows cast by the relief and the habitat dome from the sun light (shadows.js).
  // Its map is drawn again only when the Sun, the relief or the plan change.
  const shadows = new Shadows({renderer, scene, sun, terrain, enabled: params.get('shadows') !== '0',
                               onChange: () => { dirty = true; }});

  // Relief slider. The shown height is DEM + (k - 1) * local relief, so everything
  // that stands on the ground is placed again: route, markers and the camera's floor.
  // The rehearsal locks it at true scale (reliefLock is the reason shown) and gives the
  // previous value back when it ends.
  let reliefLock = null;
  function setRelief(value) {
    const k = terrain.setExaggeration(reliefLock ? 1 : Number(value) || 1);
    overlays.refresh();
    markers.refresh();
    photoMarkers.refresh();
    walkbackLines.refresh();
    controls.refresh();
    shadows.invalidate();                      // what casts and receives changed shape
    ui('relief').value = k;
    ui('relief').disabled = Boolean(reliefLock);
    ui('relief-label').textContent = reliefLock || (k === 1 ? 'Relief at true scale' : `Local relief ×${k} (exaggerated)`);
    dirty = true;
    return k;
  }
  const relief = {
    lock(reason) { reliefLock = reason; pendingRelief = null; setRelief(1); },
    unlock(k) { reliefLock = null; setRelief(k); },
  };
  let pendingRelief = null;                    // dragging the slider: at most one update per frame
  ui('relief').max = terrain.maxExaggeration;
  ui('relief').disabled = false;
  ui('relief').addEventListener('input', e => { pendingRelief = e.target.value; });
  // ?k= that is not a number means the default; the slider moves in steps of 0.5.
  const startK = parseFloat(params.get('k'));
  setRelief(Number.isFinite(startK) ? Math.round(startK * 2) / 2 : 2);

  // ?view= places the camera (view_link.js). After the relief: the camera's floor is the
  // ground as shown.
  const startView = parseView(params.get('view'));
  if (startView) {
    const [X, Z] = terrain.toLocal(startView.x, startView.y);
    controls.setView([X, startView.z - terrain.zRef, Z], startView.heading * DEG, startView.pitch * DEG);
  }

  // The Sun of Mars for a sol and a local solar time (sun.js). ?light=az,el wins over it.
  const fixedLight = (params.get('light') || '').split(',').map(Number);
  const sunView = new SunView({
    terrain, scene, sun, hemi, sky: SKY,
    fixed: fixedLight.length === 2 && fixedLight.every(Number.isFinite) ? fixedLight : null,
    start: {sol: parseSol(params.get('sol')) ?? undefined, hours: parseClock(params.get('lt')) ?? undefined},
    onChange: () => { dirty = true; },
  });

  // Route rehearsal (rehearse.js) and the card of a station (card.js). The type labels
  // of the card come from the server's rubric, asked once; until it answers (or if it
  // does not) the card shows the type as the plan writes it.
  let rubric = {};
  loadRubric().then(r => { rubric = r; refreshStationList(); });
  const rehearsal = new Rehearsal({terrain, scene, camera, canvas, controls, relief, lines: walkbackLines,
                                   rubric: () => rubric,
                                   onTime: elapsed => sunView.follow(elapsed),       // the Sun follows the EVA clock
                                   // A stop's card also shows the nearest rover photo (P3): the card only.
                                   stationMedia: s => (photos && s.x != null
                                     ? (photos.stationPreview({x: s.x, y: s.y, label: s.id}, {interactive: false}) || {}).media || null
                                     : null)});
  // "Walk freely" (walk.js, issue #109): first person anywhere in the box, with the keys.
  const walk = new Walk({terrain, scene, camera, canvas, controls, relief, overlays, markers});
  ui('walk').addEventListener('click', () => (walk.active ? walk.exit() : walk.enter()));

  // Fly to where a marker is seen from about 60 m, coming from where the camera is now.
  function flyToMarker(marker) {
    const point = markers.positionOf(marker.id);
    if (!point || busy() || photos?.active) return;
    const dx = point[0] - controls.position[0], dz = point[2] - controls.position[2];
    const yaw = Math.hypot(dx, dz) > 1 ? Math.atan2(dx, -dz) : controls.yaw;       // north is -Z
    controls.flyToLook(point, 60, {yaw, pitch: THREE.MathUtils.degToRad(20)});
  }

  // Clicking a pin shows its card; in free flight the card can take the camera there.
  markers.onSelect = marker => {
    const d = marker.data || {};
    const what = marker.kind === 'habitat' ? {title: 'Habitat', subtitle: 'Start and end of the EVA', rows: []}
      : d.kind === 'station'
        ? stationCard({id: marker.label, type: d.type, score: d.score, serviceMin: d.service_time_min,
                       order: d.order, visited: d.visited}, rubric)
        : {title: marker.label || 'Point', subtitle: '', rows: []};
    if (marker.kind === 'goal') what.subtitle = what.subtitle ? `${what.subtitle} · goal of the route` : 'Goal of the route';
    // A station's card also shows its nearest rover photo, or says there is none near (P3).
    const preview = photos && marker.kind !== 'habitat'
      ? photos.stationPreview({x: marker.x, y: marker.y, label: marker.label}, {interactive: !rehearsal.active}) : null;
    const actions = rehearsal.active ? [] : [{label: 'Fly here', onClick: () => flyToMarker(marker)}];
    if (preview && preview.action) actions.push(preview.action);
    showCard({...what, color: marker.color, media: preview ? preview.media : null, actions});
    dirty = true;
  };

  // A click (not a drag) on a marker selects it (markers.onSelect).
  let press = null;
  canvas.addEventListener('pointerdown', e => { press = {x: e.clientX, y: e.clientY, id: e.pointerId}; });
  canvas.addEventListener('pointerup', e => {
    if (walk.active) return;                   // walking, a click captures the mouse to look
    if (!press || press.id !== e.pointerId || Math.hypot(e.clientX - press.x, e.clientY - press.y) > 4) return;
    const r = canvas.getBoundingClientRect();
    const ndc = [(e.clientX - r.left) / r.width * 2 - 1, -((e.clientY - r.top) / r.height * 2 - 1)];
    const hit = markers.pick(ndc);
    if (hit) { markers.select(hit); return; }
    // Rover photo stops: one opens its card; pins on top of each other offer a choice.
    const stops = photos ? photoMarkers.pickAll(ndc).map(m => m.data.groupId) : [];
    if (stops.length === 1) photos.openGroup(stops[0]);
    else if (stops.length > 1) photos.chooseStop(stops);
    if (stops.length) dirty = true;
  });

  // ---- rover photos (P3, photos.js) ---------------------------------------------------
  // Loaded on their own: a missing catalogue, missing images or an error in this part
  // leaves the rest of the map as it is.
  let photos = null;
  let photoListNote = 'Waiting for the photo catalogue…';
  const photosNote = text => { ui('photos-note').textContent = text; };
  const showPhotoPins = () => photos && photos.setVisible(ui('photos-show').checked && !busy());

  // Native buttons keep Tab, Enter and Space. Their fieldsets disable every entry while
  // another mode owns the camera; the reason stays readable outside the disabled group.
  function updateStopControls() {
    const reason = busy()
      ? (rehearsal.active ? 'Exit the rehearsal to choose a stop.' : 'Exit Walk freely to choose a stop.')
      : photos?.active ? 'Exit the photo view to choose a stop.' : '';
    for (const kind of ['station', 'photo']) {
      const empty = ui(`${kind}-list`).children.length === 0;
      ui(`${kind}-controls`).disabled = Boolean(reason) || empty;
      const note = reason || (empty
        ? (kind === 'photo' ? photoListNote : 'No stations in this plan.')
        : kind === 'photo' ? 'Choose a stop to show its photos.' : 'Choose a station to fly there and open its card.');
      const node = ui(`${kind}-list-note`);
      if (node.textContent !== note) node.textContent = note;
    }
  }

  function fillStopList(kind, entries, choose) {
    const list = ui(`${kind}-list`);
    const focused = list.contains(document.activeElement) ? document.activeElement.dataset.stopId : null;
    list.replaceChildren();
    ui(`${kind}-list-title`).textContent = `${kind === 'station' ? 'Stations' : 'Photo stops'} (${entries.length})`;
    for (const entry of entries) {
      const item = document.createElement('li'), button = document.createElement('button');
      button.type = 'button';
      button.textContent = entry.label;        // plan and catalogue text: never HTML
      button.dataset.stopId = entry.id;
      button.setAttribute('aria-describedby', `${kind}-list-note`);
      button.addEventListener('click', () => {
        if (busy() || photos?.active) return;
        choose(entry);
        // The card follows the panel in tab order. Start at Close, so a long list does
        // not stand between the chosen stop and its card's actions; Close returns here.
        const close = ui('card').querySelector('.card-close');
        close?.focus();
        close?.addEventListener('click', () => {
          if (button.isConnected && !ui(`${kind}-controls`).disabled) button.focus();
        }, {once: true});
      });
      item.append(button);
      list.append(item);
    }
    updateStopControls();
    // A late rubric answer only changes the names; keep the keyboard's place in the list.
    if (focused && !ui(`${kind}-controls`).disabled) {
      [...list.querySelectorAll('button')].find(b => b.dataset.stopId === focused)?.focus();
    }
  }

  function refreshStationList() {
    const plan = window.viz3d?.plan;
    fillStopList('station', stationList(plan?.model, plan?.stationTypes, rubric), ({marker}) => {
      flyToMarker(marker);
      markers.select(marker);
    });
  }

  async function loadPhotos() {
    try {
      const {PhotoLayer, photoStopList} = await import('./photos.js');
      const layer = new PhotoLayer({terrain, controls, camera, canvas, relief, sunView, markers: photoMarkers,
                                    showCard, hideCard, onChange: () => { dirty = true; updateStopControls(); },
                                    isBusy: busy,
                                    // Opening a photo turned the stops on (photos.js): the box says so.
                                    onShowPins: () => { ui('photos-show').checked = true; }});
      const got = await layer.load();
      if (!got.ok) {
        // How to build them: web/3d/README.md, "Rover photos" (for the team, not on screen).
        photosNote(`No rover photos: ${got.error}. The rest of the map works without them.`);
        photoListNote = 'No photo stops available. See the catalogue message above.';
        updateStopControls();
        return;
      }
      photos = layer;
      window.viz3d.photos = layer;
      ui('photos-show').disabled = false;
      photoListNote = 'No photo stops in this catalogue.';
      fillStopList('photo', photoStopList(layer.model), ({id}) => {
        ui('photos-show').checked = true;
        showPhotoPins();
        photos.openGroup(id);
      });
      photosNote(`${got.count} Navcam photos (black and white, 2025–2026) at the stops where they were ` +
                 'taken. Choose a photo stop below or show the pins and click one; "View from here" lays its photo ' +
                 'over the terrain.');
      showPhotoPins();
      dirty = true;
    } catch (err) {
      console.error(err);
      photosNote(`Rover photos not available (${err.message}). The rest of the map works without them.`);
      photoListNote = 'No photo stops available. See the catalogue message above.';
      updateStopControls();
    }
  }
  ui('photos-show').addEventListener('change', showPhotoPins);
  // The rehearsal and the free walk take the camera and the relief: leave the photo view
  // (and the other mode) before one starts.
  document.addEventListener('click', e => {
    const mode = e.target.closest && e.target.closest('#rehearse, #walk');
    if (!mode) return;
    if (photos && photos.active) photos.exit();
    if (mode.id === 'rehearse') walk.exit(); else rehearsal.exit();
  }, true);
  // Photo pins out of the way of the walk and back after it, whoever starts or ends it
  // (its button, a check, a plan that replaces the route): the modes' own calls go
  // through these, so nothing waits for a frame to be drawn.
  for (const mode of [rehearsal, walk]) {
    for (const name of ['enter', 'exit']) {
      const original = mode[name].bind(mode);
      mode[name] = (...args) => {
        const result = original(...args);
        showPhotoPins();
        updateStopControls();
        dirty = true;
        return result;
      };
    }
  }

  // ---- plan ---------------------------------------------------------------------
  const line = (parent, cls, text) => {
    const div = document.createElement('div');
    div.className = cls;
    div.textContent = text;                    // text from the server: never as HTML
    parent.append(div);
  };

  // Draw a plan: {fc, source, error, missing, stationTypes} as api.js returns it. The
  // page draws what the answer contains; a plan with no route still shows its points.
  function showPlan(got) {
    const model = got.fc ? parsePlan(got.fc) : null;
    walk.exit();                               // its path on the ground is of the old route
    rehearsal.setPlan(model);                  // leaves the rehearsal: its route is gone
    hideCard();
    overlays.setPlan(model);
    markers.set(model ? planMarkers(model, got.stationTypes || {}) : []);
    shadows.invalidate();                      // the habitat dome casts one
    window.viz3d.plan = {...got, model};
    refreshStationList();
    window.viz3d.mapLayers?.setPlan(model);    // the radio antenna and the steep limit follow the plan

    // Which planner made it (model.properties.source, e.g. "E5 tour (live, ...)") is for
    // the team: it stays in viz3d.plan, not on screen (#124).
    const route = model && mainRoute(model), facts = [], warnings = ui('plan-warnings');
    ui('plan-source').textContent =
      got.source === 'last' ? 'Last plan from the planner'
      : got.source === 'default' ? "Default request: saved stations, the planner's default limits, start at the box centre"
      : got.fc ? 'Plan given to the page'
      : got.missing ? 'No plan yet: plan an EVA in the planner, then press Reload plan'
      : 'No plan to show: the terrain works without it.';
    ui('plan-default-box').hidden = Boolean(got.fc);
    if (route) {
      const t = route.totals;
      facts.push(`${(t.length_m ?? route.lengthM).toFixed(0)} m`);
      if (t.time_s !== null) facts.push(T.min(t.time_s));
      if (t.energy_wh !== null) {
        facts.push(`${T.wh(t.energy_wh)}${t.usable_wh !== null ? ` of ${Math.round(t.usable_wh)} usable` : ''}`);
      }
    }
    ui('plan-facts').textContent = facts.join(' · ');
    const key = ui('plan-key');
    key.replaceChildren();
    for (const leg of overlays.legs.slice(0, 2)) {
      const item = document.createElement('span'), swatch = document.createElement('i');
      item.className = 'key';
      swatch.style.background = `rgb(${leg.color.join(',')})`;
      item.append(swatch, overlays.legs.length > 1 ? leg.name : 'route');
      key.append(item);
    }
    warnings.replaceChildren();
    if (got.error) line(warnings, 'warn', got.error);
    if (model && !route) line(warnings, 'warn', 'The plan has no route.');
    if (route && route.totals.feasible === false) line(warnings, 'warn', '⚠ Not feasible within the limits');
    // The answer's messages in plain words (plan_model.js): what only describes the plan is
    // a plain line; ⚠ and amber stay for what needs a look.
    for (const m of planMessages(model ? model.warnings : [])) {
      if (m.warn) line(warnings, 'warn', `⚠ ${m.text}`);
      else line(warnings, 'muted plan-note', m.text);
    }
    for (const n of (model ? model.notes : [])) line(warnings, 'warn', `Ignored: ${n}`);
    dirty = true;
  }

  // The page only reads the saved plan. It never asks for a new one by itself: the
  // server saves every plan it makes, and the guide screen loads the saved one.
  async function fetchPlan(text, ask) {
    ui('plan-reload').disabled = ui('plan-default').disabled = true;
    ui('plan-source').textContent = text;
    try {
      showPlan(await ask());
    } finally {
      ui('plan-reload').disabled = ui('plan-default').disabled = false;
    }
    // Then the Sun moves to this plan's best time to leave (sun.js), on the first plan and
    // on every reload, without holding the page; not with ?check=: a check must give the
    // same answer whatever the planner says.
    if (!params.get('check')) void sunView.startAtBestTime(window.viz3d.plan);
  }
  const reloadPlan = () => fetchPlan('Loading the saved plan…', () => loadLastPlan());
  const planDefault = () => fetchPlan('Planning with the default settings… (about 10 s the first time)',
                                      () => requestDefaultPlan({start: terrain.toMars(0, 0)}));
  ui('plan-reload').addEventListener('click', reloadPlan);
  ui('plan-default').addEventListener('click', planDefault);

  // ---- a view to share: its address and its picture --------------------------------
  // The address that opens the page on the free-flight view as it is now, with what
  // changes the picture: relief, sol, time and the shadows switch (view_link.js).
  function currentViewLink() {
    const [x, y] = terrain.toMars(controls.position[0], controls.position[2]);
    const view = formatView({x, y, z: terrain.elevation(controls.position[1]),
                             heading: controls.yaw / DEG, pitch: controls.pitch / DEG});
    const fixed = Boolean(sunView.fixed);      // ?light= stays as it is in the address
    return viewLink(location.origin + location.pathname, location.search, {
      view, k: terrain.k, sol: fixed ? params.get('sol') : sunView.start.sol,
      lt: fixed ? params.get('lt') : clockText(sunView.start.hours), shadows: shadows.enabled ? null : 0});
  }
  // The link is always shown in the box, selected: the clipboard only works on localhost
  // or https, and the page is also opened from other machines of the local network.
  ui('copy-view').addEventListener('click', async () => {
    const link = currentViewLink(), box = ui('view-link');
    box.value = link;
    box.hidden = false;
    box.select();
    let copied = false;
    try { await navigator.clipboard.writeText(link); copied = true; } catch { /* no clipboard here */ }
    ui('share-note').textContent = copied ? 'Link copied.' : 'Copy the link from the box.';
  });
  // The picture is the canvas alone (no panels), at its size on screen times the pixel
  // ratio. The frame is drawn again right before it is read: three.js does not keep the
  // drawing buffer between frames.
  function capture() {
    renderer.render(scene, camera);
    return new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
  }
  ui('save-image').addEventListener('click', async () => {
    const blob = await capture();
    if (!blob) { ui('share-note').textContent = 'The browser could not make the image.'; return; }
    const a = document.createElement('a'), url = URL.createObjectURL(blob);
    a.href = url;
    a.download = 'mars-eva-3d.png';
    a.click();
    setTimeout(() => URL.revokeObjectURL(url), 10000);        // after the download has started
    ui('share-note').textContent = `Image saved (${canvas.width} × ${canvas.height} px).`;
  });

  function frame(now) {
    requestAnimationFrame(frame);
    if (pendingRelief !== null) { setRelief(pendingRelief); pendingRelief = null; }
    if (controls.update((now - last) / 1000)) dirty = true;    // wheel easing, auto-rotate, drags, flights
    if (rehearsal.update((now - last) / 1000)) dirty = true;   // every frame only while playing or dragging
    if (walk.update((now - last) / 1000)) dirty = true;        // every frame only while moving or looking
    last = now;
    if (!dirty && !continuous) return;
    if (camera.fov !== shownFov) {             // a flight or the rehearsal changed it: resize the pins
      shownFov = camera.fov;
      markers.setResolution(canvas.clientWidth, canvas.clientHeight);
      photoMarkers.setResolution(canvas.clientWidth, canvas.clientHeight);
    }
    renderer.render(scene, camera);
    dirty = false;
    frames++;
    if (now - since >= 1000) {
      fps = frames * 1000 / (now - since);
      frames = 0; since = now;
    }
    readout();
  }
  requestAnimationFrame(frame);

  // Handle for the manual checks listed in the PR and for later blocks.
  // `plan` is {fc, source, error, missing, stationTypes, model} once a plan was asked for.
  // `photos` is the PhotoLayer once its catalogue has loaded (photosReady), else missing.
  window.viz3d = {terrain, scene, camera, controls, renderer, sun, sunDirection, sunView, shadows, overlays, markers,
                  photoMarkers, rehearsal, walk, walkbackLines, plan: null, showPlan, reloadPlan, planDefault, setRelief,
                  currentViewLink, capture, get fps() { return fps; }, redraw() { dirty = true; }};
  // The terrain is usable while the plan loads. ?plan=default is the user asking.
  const planReady = params.get('plan') === 'default' ? planDefault() : reloadPlan();
  const photosReady = loadPhotos();
  window.viz3d.photosReady = photosReady;
  // Map layers of the 2D planner on the terrain (map_layers.js): nothing is asked until one
  // is picked, and an error in that part leaves the rest of the map as it is.
  window.viz3d.mapLayersReady = (async () => {
    try {
      const {setupMapLayers} = await import('./map_layers.js');
      window.viz3d.mapLayers = setupMapLayers(window.viz3d);
    } catch (err) {
      console.error(err);
      ui('layer-note').textContent = `Map layers not available (${err.message}).`;
    }
  })();

  // ?photo=<id>: its card and the photo view, once the plan has drawn (it hides the card).
  // Entering the view turns the photo stops on, so they are there after Exit (photos.js).
  const startPhoto = params.get('photo');
  if (startPhoto) {
    Promise.all([planReady, photosReady]).then(async () => {
      const {parsePhotoParam} = await import('./photos_model.js');
      const id = parsePhotoParam(startPhoto), photo = photos && id && photos.model.byId.get(id);
      if (photo) {
        photos.openGroup(photo.groupId, id);
        photos.enter(id);
      } else {
        photosNote(photos ? `The address asks for photo "${startPhoto}", which is not in the catalogue.`
                          : ui('photos-note').textContent);
        ui('photos-box').open = true;          // the section that says why starts closed (#124)
      }
      dirty = true;
    });
  }

  // ?check=<name>: run a reproducible check (checks.js) and show its JSON result.
  const check = params.get('check');
  if (check) {
    const {CHECKS} = await import('./checks.js');
    await planReady;
    await photosReady;
    await window.viz3d.mapLayersReady;
    const result = CHECKS[check] ? await CHECKS[check](window.viz3d) : {error: `unknown check: ${check}`};   // guide is async
    window.viz3d.checkResult = result;
    console.log(JSON.stringify(result));
    const plain = new URLSearchParams(params);
    plain.delete('check');
    // The name comes from the address: as text, never as HTML.
    showMessage(`<div class="muted">Result of the "${esc(check)}" check, shown because the address has
      <b>?check=${esc(check)}</b>. <a href="?${esc(plain)}">Open the map without it</a>.</div>
      <code style="text-align:left;white-space:pre-wrap">${esc(JSON.stringify(result, null, 1))}</code>`);
    dirty = true;
  }
}

main().catch(err => {
  console.error(err);
  showMessage(`Error: ${esc(err.message)}`);
});
