// "Rehearse the route" mode of the 3D map (P1, issue #42, block 3).
//
// Walks the planned route at eye height before the EVA. The numbers (where the walker
// is, time, energy) come from rehearse_model.js; this file owns what the mode does to
// the page while it is on, and puts everything back when it is left:
//   - camera: first person, the eye EYE_HEIGHT above the shown ground, looking along the
//     path; dragging looks around (offsets from the direction of travel), double-click
//     or "Recentre" looks forward again. "Chase view" sees the walker from behind and
//     above. The free-flight controls are off and the near plane comes in to NEAR.
//   - relief: forced to true scale. At eye height an exaggerated knoll would be a wall
//     that is not there, and slopes are what the rehearsal is for.
//   - player bar (#124, block 2): the next maneuver as the arm tablet shows it; one row of
//     main buttons (play / pause, Return home, Off route, Solar storm); speed, "Chase view",
//     "Recentre", voice, the "Use xk" demo and the energy numbers under "More"; the
//     scrubber, the clock line (the EVA clock, which goes on after a way home or a rejoin:
//     the way home is a stretch of it), the panel's Sun line and the 2D planner's energy bar.
//   - side panel: hidden while rehearsing, so the scene shows; "Panel" opens and closes it
//     without leaving. Its own body class (the photo view's would hide the map layer too).
//   - keys: Space plays or pauses unless a focused control owns the key. Entering focuses
//     Play; leaving focuses Rehearse. Esc closes what is on top (the card, or the message
//     box of main.js) and pauses. Esc never leaves the mode, which would lose the end
//     summary and the place reached: only "Exit" does (#124).
//   - stops: arriving at one while playing pauses and shows its card; play again lets
//     the service time run with the walker standing.
//   - at the habitat the rehearsal stays on (#124): the storm alert ends, the player
//     shrinks and the end summary card offers "Replay" (from the start, as a new walk) and
//     "Exit". Play (now "Replay") and Space outside controls replay too; the scrubber goes back.
//   - on pause: the walkback lines from that point (30 min return in red, energy-safe
//     boundary in cyan), as the 2D planner draws them; cleared on play and on exit.
//   - EVA clock: onTime(seconds since the start of the EVA) at every move, and
//     onTime(null) on exit; main.js moves the Sun with it (sun.js).
//   - guide: the same logic as the arm-tablet guide (web/guide_core.js, shared): next
//     maneuver, voice (on/off), energy left after returning, time back against the
//     30 min line, EVA time left against the plan's maximum duration, station tasks,
//     Return home, a demo detour that rejoins the route, and the solar storm alert. A
//     way home or a rejoin replaces the walked route (drawn on the ground) until exit.
//     The storm alert also shows beyond the player, as page elements: a red band across
//     the top and a red vignette over the view. Nothing is added to the scene for it
//     (sun.js repaints the sky every frame, and ?check=rehearse compares the scene).
//   - adaptive walkback (X2, #101, #129), as on the arm tablet (#116): every 30 m played,
//     guide_core simulates this astronaut's real energy use (k_true x the plan, the "Use
//     xk" demo button) and POST /walkback/update learns k. The meter "Spare energy at
//     your pace" (the tablet's name since #124), the RETURN NOW alert and 4 rows of the final card come from
//     the same guide_core functions as the tablet. It asks the server only while playing,
//     and not when walkbackOnPause is off (checks.js), so the checks are unchanged.
//   - words and numbers: the names, state words and formats of the shared glossary
//     (web/terms.js, #166), as on the HUD, the tablet and the wrist card: whole minutes and
//     Wh everywhere; m:ss only on the clock line (progressText).
// Nothing is rendered here: update(dt) says whether the view changed, and main.js draws.
import '../terms.js';
import * as THREE from 'three';
import { requestWalkback, walkbackRequest } from './api.js';
import { createAstronaut, disposeAstronaut, poseAstronaut } from './astronaut.js';
import * as M from './camera_math.js';
import { cardShown, hideCard, showCard, stationCard } from './card.js';
import { TYPE_COLORS, mainRoute } from './plan_model.js';
import { EYE_HEIGHT, adaptiveCardRows, buildRehearsal, energyReadout, eyeAltitude, homeInText, kAlarmAction,
         maneuverDistance, progressText } from './rehearse_model.js';
import * as G from '../guide_core.js';

const T = globalThis.TERMS, N = T.NAMES;

const DEG = Math.PI / 180;
export const FOV = 60;             // degrees, vertical: wider than free flight, closer to what a walker sees
export const NEAR = 0.3;           // m: the ground is 1.7 m from the eye (free flight keeps 2 m)
const LOOK_DOWN = 3 * DEG;         // first person looks this far below the slope of the path
const PITCH_LIMIT = 70 * DEG;      // first person: how far up or down one can look
const CHASE_BACK = 15, CHASE_UP = 8;       // m behind the walker and above the ground it stands on
const CHASE_TARGET = 1.2;          // m above the ground: the camera looks at the walker's chest
const CHASE_TILT = Math.atan2(CHASE_UP - CHASE_TARGET, CHASE_BACK);
const CHASE_RANGE = Math.hypot(CHASE_UP - CHASE_TARGET, CHASE_BACK);
const CHASE_PITCH = [5 * DEG, 80 * DEG];   // the chase camera stays above the walker's horizon
const CHASE_FLOOR = 2;             // m: the chase camera stays this far above the ground
const VIEW_EASE = 6;               // 1/s: how fast the view follows a change of heading
const MAX_FRAME = 0.1;             // s: a frame never counts for more (tab in the background)
const STRIDE = {period: 1, swing: 0.3};    // the astronaut's legs: one stride per second of screen time
const RED_LINE = [255, 59, 48], SAFE_LINE = [54, 209, 255];       // the 2D planner's walkback colours
const HOME_LINE = [255, 69, 58], REJOIN_LINE = [255, 140, 58];     // guide: way home, rejoining path
// The bars of the meters by their state (guide_core's ok / low / out), in guide.html's
// colours; the state words beside them are coloured by index.html (.rh-word).
const METER = {good: '#3ddc84', warn: '#ffb020', bad: '#ff5147'};
const RELIEF_REASON = 'Relief at true scale while rehearsing (eye height is real)';

const el = id => document.getElementById(id);
const clamp = (v, lo, hi) => Math.min(hi, Math.max(lo, v));

// Leave Space to controls and editable text, including children of a custom control.
// No page state: plain element-shaped objects work in the Node tests too.
export function spaceBelongsTo(target) {
  for (let node = target; node; node = node.parentElement) {
    if (node.isContentEditable || /^(button|a|input|select|textarea|summary)$/i.test(node.tagName) ||
        /(^|\s)(button|link|checkbox|slider)(\s|$)/.test(node.getAttribute?.('role') || '')) return true;
  }
  return false;
}

export class Rehearsal {
  // relief: {lock(reason), unlock(k)} from main.js; lines: a GroundLines layer for the
  // walkback boundaries; rubric(): the station rubric for the cards; onTime: see above;
  // stationMedia(station): an element for a stop card's media slot (the nearest rover
  // photo, P3) or null. It only adds to the card: no camera, clock or task changes.
  constructor({terrain, scene, camera, canvas, controls, relief, lines, rubric = () => ({}), onTime = () => {},
               stationMedia = () => null}) {
    Object.assign(this, {terrain, scene, camera, canvas, controls, relief, lines, rubric, onTime, stationMedia});
    this.active = false;
    this.playing = false;
    this.plan = null;              // parsePlan() result
    this.model = null;             // buildRehearsal() result, or null when there is no route
    this.state = null;             // model.stateAt(time) of what is shown
    this.time = 0;
    this.speed = 60;
    this.chase = false;
    this.look = {yaw: 0, pitch: 0};        // what dragging adds to the direction of travel
    this.view = {heading: 0, pitch: 0};    // direction of travel as shown (eased while playing)
    this.viewYaw = 0;                      // heading of the camera itself, for the compass
    this.walkback = null;                  // properties of the last walkback answer shown
    this.walkbackOnPause = true;           // checks.js turns it off: it asks the server
    this._listeners = [];
    this._dirty = false;
    this._snap = true;
    this._drag = null;
    this._token = 0;
    this._stopCard = false;
    this.voice = G.createVoice();          // guide: spoken maneuvers and arrivals
    this.guide = null;                     // guide_core route of what is walked (null: no profile)
    this._extra = [];                      // lines of a way home or a rejoin, kept on play
    this._spoken = new Set();
    this._radInfo = undefined;
    this.kTrue = 1.0;                      // demo: simulated energy use against the model (X2)
    this.adaptive = null;                  // guide_core adaptive state of the walk (X2)
    this._kAlarm = false;                  // the RETURN NOW banner is on screen
    this._storm = false;                   // a solar storm owns the banner (and the band on top)
    this._homeStart = null;                // plan time when the way home began, else null
    this._arrived = false;                 // played to the habitat: player shrunk, end card up
    this._endCard = null;                  // the end summary card, shown again on a later arrival
    this._panelOpen = false;               // the side panel opened with "Panel" while rehearsing
    this._radioPending = null;             // guide route whose radio is still being asked for
    this._sizer = null;                    // ResizeObserver of the player's height

    // The player's own controls. They are hidden outside the rehearsal.
    el('rh-play').addEventListener('click', () => this.togglePlay());
    el('rh-more').addEventListener('click', () => this._setMore(el('rh-more-box').hidden));
    el('rh-panel').addEventListener('click', () => this._setPanel(!this._panelOpen));
    el('rh-summary').addEventListener('click', () => this._showEnd());
    el('rh-speed').addEventListener('change', e => { this.speed = Number(e.target.value) || 60; });
    el('rh-scrub').addEventListener('input', e => { this.pause(false); this.seek(Number(e.target.value)); });
    el('rh-scrub').addEventListener('change', () => this._settle());
    el('rh-chase').addEventListener('click', () => this.setChase(!this.chase));
    el('rh-recentre').addEventListener('click', () => this.recentre());
    el('rh-exit').addEventListener('click', () => this.exit());
    el('rehearse').addEventListener('click', () => (this.active ? this.exit() : this.enter()));
    el('rh-voice').addEventListener('click', () => {
      const on = this.voice.toggle();
      el('rh-voice').textContent = on ? '🔊 Voice on' : '🔇 Voice off';
      el('rh-voice').setAttribute('aria-pressed', String(on));
    });
    el('rh-home').addEventListener('click', () => this.returnHome());
    el('rh-detour').addEventListener('click', () => this.detour());
    el('rh-storm').addEventListener('click', () => this.solarStorm());
    el('rh-ktrue').addEventListener('click', () => this.cycleKTrue());
  }

  // Demo: the next simulated energy use (k_true). Before anything is learned it starts
  // a fresh walk; later it changes the use from here on and the walk keeps learning.
  cycleKTrue() {
    const ch = G.K_TRUE_CHOICES;
    this.kTrue = ch[(ch.indexOf(this.kTrue) + 1) % ch.length];
    el('rh-ktrue').textContent = `Use ×${this.kTrue.toFixed(1)}`;
    if (!this.adaptive || !this.adaptive.history.length) this._newAdaptive();
    else this.adaptive.kTrue = this.kTrue;
    if (this.active) this._note(`Simulated energy use: ${this.kTrue.toFixed(1)}× the model (demo).`);
  }

  // ---- public ------------------------------------------------------------------

  // plan: the result of parsePlan(), or null. Leaves the rehearsal if it was on.
  setPlan(plan) {
    this.exit();
    const route = plan ? mainRoute(plan) : null;
    this.plan = plan;
    this.model = route ? buildRehearsal(route, plan.points) : null;
    el('rehearse').disabled = !this.model;
    const m = this.model;
    el('rehearse-note').textContent =
      !plan ? 'No route to rehearse: there is no plan.'
      : !m ? 'No route to rehearse: the plan has no route.'
      : m.assumedSpeed !== null
        ? `Walk it at eye height. The plan has no times: ${T.min(m.duration)} at an assumed ${m.assumedSpeed.toFixed(0)} m/s.`
        : `Walk it at eye height: ${T.min(m.duration)} of EVA` +
          (m.stops.length ? `, ${m.stops.length} stop${m.stops.length > 1 ? 's' : ''}.` : '.');
  }

  enter() {
    if (this.active || !this.model) return false;
    const {controls, camera} = this;
    // Everything that exit() must put back.
    this._saved = {pose: controls.pose(), near: camera.near, relief: this.terrain.k};
    controls.cancel();
    controls.enabled = false;
    this.relief.lock(RELIEF_REASON);
    camera.near = NEAR;
    camera.fov = FOV;
    camera.updateProjectionMatrix();

    // The walker, seen only in the chase view: the astronaut (astronaut.js), its origin
    // where the old capsule had its centre, half the eye height above the ground.
    this.walker = createAstronaut();
    this.walker.visible = false;
    this._stride = 0;
    this.scene.add(this.walker);

    this._listen(this.canvas, 'pointerdown', e => this._down(e));
    this._listen(this.canvas, 'pointermove', e => this._move(e));
    for (const type of ['pointerup', 'pointercancel', 'lostpointercapture']) {
      this._listen(this.canvas, type, e => { if (this._drag && this._drag.id === e.pointerId) this._drag = null; });
    }
    this._listen(this.canvas, 'dblclick', () => this.recentre());
    this._listen(window, 'keydown', e => this._key(e));

    Object.assign(this, {active: true, chase: false});
    this.speed = Number(el('rh-speed').value) || 60;
    document.body.classList.add('rehearsing');
    this._setPanel(false);                     // the scene first; the panel is one press away
    el('player').hidden = false;
    this._watchPlayer(true);
    el('rehearse').textContent = 'Exit rehearsal';
    el('rh-chase').setAttribute('aria-pressed', 'false');
    this._restart();
    this._snap = true;
    this._place(0);
    this._dirty = true;
    el('rh-play').focus({preventScroll: true});
    return true;
  }

  // The rehearsal from the start of the plan, as a new walk: the planned route (a way
  // home or a rejoin is dropped), the clock at its start, a new walk log, no storm, no
  // RETURN NOW, the player full size. enter() and replay() share it; nothing is drawn.
  _restart() {
    this.playing = false;
    if (this._replaced) {                      // a way home or a rejoin: back to the plan
      this.model = buildRehearsal(mainRoute(this.plan), this.plan.points);
      this._replaced = false;
    }
    this._extra = [];
    this._clearWalkback();                     // also drops answers still on their way
    this._setStorm(false);
    this._kAlarm = false;
    this._setArrived(false);
    this._homeStart = null;
    this._endCard = null;
    this.time = this._evaStart = this.model.start;
    this.guide = this._guideRoute(mainRoute(this.plan), 'plan');
    this._radio(this.guide);
    this.walkLog = this.guide ? G.createWalkLog(this.guide) : null;   // plan against the walk (P6)
    this._newAdaptive();
    this._spoken.clear();
    el('rh-alert').hidden = true;
    for (const id of ['rh-home', 'rh-detour', 'rh-storm']) el(id).disabled = !this.guide;
    this.look = {yaw: 0, pitch: 0};
    hideCard();
    el('rh-scrub').min = this.model.start;
    el('rh-scrub').max = this.model.end;
    this._note();
  }

  // Back to free flight exactly as it was: camera view, field of view and relief.
  exit() {
    if (!this.active) return false;
    const {controls, camera} = this, saved = this._saved;
    this.playing = false;
    this._extra = [];
    this._kAlarm = false;
    this._setStorm(false);
    this._setArrived(false);
    this._homeStart = null;
    this._endCard = null;
    this._clearWalkback();
    if (this._replaced) {                      // a way home or a rejoin: back to the plan
      this.model = buildRehearsal(mainRoute(this.plan), this.plan.points);
      this._replaced = false;
    }
    if (typeof speechSynthesis !== 'undefined') speechSynthesis.cancel();
    hideCard();
    for (const [target, type, handler] of this._listeners) target.removeEventListener(type, handler);
    this._listeners = [];
    this._drag = null;
    disposeAstronaut(this.walker);             // out of the scene, buffers freed
    this.walker = null;
    this.active = false;
    this.state = null;
    document.body.classList.remove('rehearsing', 'rh-panel-hidden');     // the side panel is back
    this._panelOpen = false;
    el('rh-panel').setAttribute('aria-expanded', 'false');
    this._watchPlayer(false);
    el('player').hidden = true;
    el('rehearse').textContent = N.rehearse;
    camera.near = saved.near;
    this.relief.unlock(saved.relief);          // the ground first: the saved camera height belongs to it
    controls.enabled = true;
    controls.restore(saved.pose);              // also puts the field of view back
    this.onTime(null);
    el('plan-box').open = true;                // Rehearse must be reachable even if Plan was folded
    el('rehearse').focus();
    return true;
  }

  play() {
    if (!this.active || this.playing) return;
    // Played to the habitat: the button says "Replay", and it is one.
    if (this._arrived) { this.replay(); return; }
    // At the end: start again. The scrubber dragged to its end stops a hair before it
    // (a range input keeps 15 digits of its value), and that is the end too.
    if (this.model.end - this.time < 1e-3) this.seek(this.model.start);
    this._clearWalkback();
    if (this._stopCard) hideCard();
    this.playing = true;
    el('rh-play').textContent = '❚❚ Pause';
  }

  // "Replay" (end card, or Play at the habitat): the rehearsal again from the start of the
  // plan, as a new walk (its own summary and walk log at the end), without leaving.
  replay() {
    if (!this.active) return;
    this._restart();
    this.seek(this.model.start);
    this.play();
  }

  // settle: also ask for the walkback lines from here, as the 2D planner does on pause.
  pause(settle = true) {
    if (!this.active) return;
    const was = this.playing;
    this.playing = false;
    el('rh-play').textContent = this._arrived ? '↺ Replay' : '▶ Play';
    if (settle && was) this._settle();
  }

  togglePlay() { if (this.playing) this.pause(); else this.play(); }

  // Jump to a playback time (seconds on the plan's clock).
  seek(time) {
    if (!this.active) return;
    this.time = clamp(time, this.model.start, this.model.end);
    if (this._arrived && this.model.end - this.time >= 1e-3) this._setArrived(false);   // back from the habitat
    this._clearWalkback();
    this._snap = true;
    this._place(0);
    // Landing inside a wait shows where the walker is standing.
    if (this.state.standing && this.state.stop) this._showStop(this.state.stop);
    else if (this._stopCard) hideCard();
    this._dirty = true;
  }

  setChase(on) {
    if (!this.active) return;
    this.chase = Boolean(on);
    this.look = {yaw: 0, pitch: 0};
    el('rh-chase').setAttribute('aria-pressed', String(this.chase));
    this._dirty = true;
  }

  // Look forward again.
  recentre() {
    this.look = {yaw: 0, pitch: 0};
    this._dirty = true;
  }

  // Call once per frame with the seconds elapsed. Returns true when the view changed
  // (always while playing or dragging; otherwise only after an input).
  update(dt) {
    if (!this.active) return false;
    const step = clamp(dt, 0, MAX_FRAME);
    let changed = this._dirty || this._easing;
    if (this.playing) { this._advance(step); changed = true; }
    if (changed) this._place(step);
    this._dirty = false;
    return changed;
  }

  // Where the walker is, for the readout of main.js.
  positionText() {
    const s = this.state, {terrain} = this;
    if (!s) return '';
    const [X, Z] = terrain.toLocal(s.x, s.y);
    return `Walker at x ${s.x.toFixed(0)} m · y ${s.y.toFixed(0)} m · elevation ` +
           `${terrain.elevation(terrain.heightAt(X, Z, 1)).toFixed(0)} m`;
  }

  // ---- playback ----------------------------------------------------------------

  _advance(step) {
    const {model} = this, from = this.time, to = Math.min(model.end, from + step * this.speed);
    const stop = model.stops.find(s => s.arrive > from && s.arrive <= to);
    if (stop) {                                // arrive, stop the clock and say where we are
      this.time = stop.arrive;
      this.playing = false;
      el('rh-play').textContent = '▶ Play';
      this._place(step);
      this._showStop(stop);
      this._settle();
      return;
    }
    this.time = to;
    if (to >= model.end) {
      this._place(step);
      this._arrive();
    }
  }

  // At the habitat the rehearsal stays on (#124): leaving would drop the summary, the
  // replay and the Sun of the end. The storm alert (and RETURN NOW) end here, the player
  // shrinks, and the end summary card comes with "Replay" and "Exit". A later arrival on
  // the same walk (after going back with the scrubber) shows the same card again.
  _arrive() {
    this.pause(false);
    this.voice.say('You have arrived at the habitat.');
    this._setStorm(false);
    this._kAlarm = false;
    el('rh-alert').hidden = true;
    this._setArrived(true);
    this._showGuide();                         // the maneuver says "Home"
    if (!this._finishWalk()) this._showEnd();
  }

  // The end card once more ("Summary" at the habitat, or a later arrival): the summary of
  // this walk, or a plain card when there is none (no guide, or nothing was played).
  _showEnd() {
    showCard(this._endCard || {title: 'At the habitat', subtitle: 'rehearsal', note: 'End of the rehearsal.',
                               actions: this._endActions()});
    this._stopCard = true;
  }

  _endActions() {
    return [{label: 'Replay', onClick: () => this.replay()}, {label: 'Exit', onClick: () => this.exit()}];
  }

  // The shrunk player at the habitat (CSS: #player.rh-arrived): Play as "Replay", and
  // "Summary" to see the end card again after closing it.
  _setArrived(on) {
    this._arrived = Boolean(on);
    el('player').classList.toggle('rh-arrived', this._arrived);
    el('rh-summary').hidden = !this._arrived;
    el('rh-play').textContent = this._arrived ? '↺ Replay' : '▶ Play';
  }

  _showStop(stop) {
    const {model} = this, s = stop.station;
    const base = s ? stationCard(s, this.rubric()) : {title: 'Stop', subtitle: '', rows: []};
    const rows = [...base.rows, ['Arrival', `${T.min(stop.arrive - this._evaStart)} into the EVA`]];
    if (stop.waitS > 0) rows.push(['Standing here', T.min(stop.waitS)]);
    // Guide: why the station matters and its tasks, as on the arm tablet.
    const g = s ? G.stationCard({id: s.id, type: s.type, service_time_min: s.serviceMin}, this.rubric()) : null;
    if (s && this.walkLog && this.guide && this.guide.kind === 'plan') G.logArrival(this.walkLog, s.id);
    if (g && g.why) rows.push(['Why', g.why]);
    if (g) g.tasks.forEach((t, k) => rows.push([k ? '' : 'Tasks', `• ${t}`]));
    showCard({...base, rows, color: s ? TYPE_COLORS[s.type] || null : null,
              media: s ? this.stationMedia(s) : null,
              note: stop.waitS > 0
                ? 'Press play: the time here runs at the playback speed, with the walker standing.'
                : 'Press play to walk on.',
              actions: [{label: 'Done, continue', onClick: () => { hideCard(); this.play(); }}],
              onClose: () => { this._stopCard = false; }});
    if (g && this.playing === false && !this._spoken.has(`stop-${stop.index}`)) {
      this._spoken.add(`stop-${stop.index}`);
      this.voice.say(g.speech);
    }
    this._stopCard = true;
  }

  // ---- camera ------------------------------------------------------------------

  // Shown ground height under the camera path at a distance along the route.
  _ground(d) {
    const [x, y] = this.model.cameraAt(d), [X, Z] = this.terrain.toLocal(x, y);
    return this.terrain.surfaceAt(X, Z);
  }

  // Put the camera (and the player's texts) where the playback time says. step: seconds
  // since the last frame, for the easing of the view.
  _place(step) {
    const {terrain, model, camera} = this, s = this.state = model.stateAt(this.time);
    const [X, Z] = terrain.toLocal(s.cx, s.cy), ground = terrain.surfaceAt(X, Z);
    const [AX, AZ] = terrain.toLocal(s.ahead[0], s.ahead[1]);
    // Look along the slope of the path, a little down: the ground ahead stays in view
    // uphill and downhill.
    const slope = Math.atan2(terrain.surfaceAt(AX, AZ) - ground, Math.max(3, Math.hypot(AX - X, AZ - Z)));
    // A route with no direction (standing at the habitat) keeps the heading shown.
    const want = {heading: s.heading ?? this.view.heading, pitch: LOOK_DOWN - slope};
    // While playing, a sudden change of direction (leaving a stop, fast playback) is
    // followed over a few frames instead of in one.
    const k = this._snap || !this.playing && !this._easing ? 1 : 1 - Math.exp(-VIEW_EASE * step);
    this.view.heading += M.angleDelta(want.heading, this.view.heading) * k;
    this.view.pitch += (want.pitch - this.view.pitch) * k;
    const off = Math.abs(M.angleDelta(want.heading, this.view.heading)) + Math.abs(want.pitch - this.view.pitch);
    this._easing = off > 5e-4;                 // under 0.03 degrees: there
    if (!this._easing) Object.assign(this.view, want);
    this._snap = false;

    let position, yaw = this.view.heading + this.look.yaw, pitch;
    if (this.chase) {
      const target = [X, ground + CHASE_TARGET, Z];
      const tilt = clamp(CHASE_TILT + this.look.pitch, ...CHASE_PITCH);
      position = M.along(target, M.basis(yaw, tilt).forward, -CHASE_RANGE);
      // A slope behind the walker: the camera rides over it and keeps looking at the walker.
      position[1] = Math.max(position[1], terrain.surfaceAt(position[0], position[2]) + CHASE_FLOOR);
      pitch = Math.atan2(position[1] - target[1], Math.hypot(position[0] - X, position[2] - Z));
    } else {
      position = [X, eyeAltitude(d => this._ground(d), s.distance, model.length), Z];
      pitch = clamp(this.view.pitch + this.look.pitch, -PITCH_LIMIT, PITCH_LIMIT);
    }
    const {right, up, forward} = M.basis(yaw, pitch);
    camera.position.set(position[0], position[1], position[2]);
    camera.quaternion.setFromRotationMatrix(new THREE.Matrix4().makeBasis(
      new THREE.Vector3(...right), new THREE.Vector3(...up), new THREE.Vector3(...forward).negate()));
    camera.updateMatrixWorld();
    this.viewYaw = yaw;
    this.pose = {position, yaw, pitch, ground};

    this.walker.visible = this.chase;
    this.walker.position.set(X, ground + EYE_HEIGHT / 2, Z);
    // It faces the way it walks and swings its legs while playing, at a steady pace on
    // screen whatever the playback speed (at x60 a pace per metre would only flicker).
    const walking = this.playing && !s.standing;
    if (walking) this._stride = (this._stride + step / STRIDE.period) % 1;
    poseAstronaut(this.walker, {yaw: this.view.heading,
                                swing: walking ? STRIDE.swing * Math.sin(2 * Math.PI * this._stride) : 0});
    this._show();
    this._showGuide();
    this.onTime(s.time - this._evaStart);
    this._showSun();
  }

  _show() {
    const {model, state} = this;
    el('rh-scrub').value = state.time;
    el('rh-progress').textContent = progressText(model, state, {evaStart: this._evaStart, homeStart: this._homeStart});
    const bar = energyReadout(state.profile, model.usableWh);
    el('rh-energy').hidden = !bar;
    if (!bar) { el('rh-energy-text').replaceChildren(); return; }
    el('rh-bar-used').style.width = `${bar.usedPct}%`;
    el('rh-bar-rv').style.width = `${bar.rvPct}%`;
    el('rh-bar-free').style.width = `${bar.freePct}%`;
    el('rh-energy-text').replaceChildren(...bar.lines.map(text => Object.assign(document.createElement('div'), {textContent: text})));
  }

  // The Sun line of the side panel (sun.js), repeated in the player because the panel is
  // hidden while rehearsing (#124): the local solar time that moves with the EVA clock,
  // how high the Sun is and where the light comes from, and the note "Following the EVA
  // clock: it started at …". Read after onTime(), which has just written them.
  _showSun() {
    const text = id => { const node = document.getElementById(id); return node ? node.textContent.trim() : ''; };
    const time = text('sun-time-text');
    const line = [time && `Local solar time ${time}`, text('sun-readout'), text('sun-note')].filter(Boolean).join(' · ');
    if (el('rh-sun').textContent !== line) el('rh-sun').textContent = line;
  }

  // ---- what the player shows around the scene (#124, block 2) -------------------

  // Disclosures keep focus on their toggle, also when closing hides the focused control.
  // "More": the controls that are not in the main row (and the energy numbers).
  _setMore(open) {
    el('rh-more-box').hidden = !open;
    el('rh-more').setAttribute('aria-expanded', String(Boolean(open)));
    el('rh-more').focus({preventScroll: true});
  }

  // "Panel": the side panel (#info) while rehearsing. Hidden on entering, so the scene
  // shows; a class of its own on the body (the photo view's, photo-view, also hides the
  // map layer). exit() takes the class away.
  _setPanel(open) {
    this._panelOpen = Boolean(open);
    document.body.classList.toggle('rh-panel-hidden', this.active && !this._panelOpen);
    el('rh-panel').setAttribute('aria-expanded', String(this._panelOpen));
    if (!el('player').hidden) el('rh-panel').focus({preventScroll: true});
  }

  // The solar storm beyond the player: the red band across the top and the red vignette
  // (index.html, body.rh-storm moves what is at the top under the band). Page elements, no
  // objects in the scene. Off at the habitat, on Replay and on exit.
  _setStorm(on) {
    this._storm = Boolean(on);
    document.body.classList.toggle('rh-storm', this._storm);
    el('rh-storm-band').hidden = el('rh-tint').hidden = !this._storm;
  }

  // The player's height in --rh-player-h while rehearsing: the card and an opened panel
  // end above the player on narrow screens (index.html), whatever the player shows.
  _watchPlayer(on) {
    const style = document.body.style;
    if (this._sizer) { this._sizer.disconnect(); this._sizer = null; }
    if (!on) { style.removeProperty('--rh-player-h'); return; }
    if (typeof ResizeObserver === 'undefined') return;
    this._sizer = new ResizeObserver(() => style.setProperty('--rh-player-h', `${el('player').offsetHeight}px`));
    this._sizer.observe(el('player'));
  }

  // ---- input (only while rehearsing) -------------------------------------------

  _listen(target, type, handler) {
    target.addEventListener(type, handler);
    this._listeners.push([target, type, handler]);
  }

  _down(e) {
    if (e.pointerType === 'mouse' && e.button !== 0) return;
    try { this.canvas.setPointerCapture(e.pointerId); } catch { /* pointer already gone */ }
    this._drag = {id: e.pointerId, x: e.clientX, y: e.clientY};
  }

  // Dragging moves the scene with the cursor, as in a street-level viewer: drag right to
  // look left. In the chase view the same drag turns the camera around the walker.
  _move(e) {
    const d = this._drag;
    if (!d || d.id !== e.pointerId) return;
    const scale = this.camera.fov * DEG / this.canvas.clientHeight;
    this.look.yaw = M.angleDelta(this.look.yaw - (e.clientX - d.x) * scale, 0);
    const tilt = (e.clientY - d.y) * scale * (this.chase ? 1 : -1);
    const range = this.chase ? CHASE_PITCH.map(p => p - CHASE_TILT)
                             : [-PITCH_LIMIT - this.view.pitch, PITCH_LIMIT - this.view.pitch];
    this.look.pitch = clamp(this.look.pitch + tilt, ...range);
    d.x = e.clientX; d.y = e.clientY;
    this._dirty = true;
  }

  _key(e) {
    if (e.repeat) return;
    // Esc closes what is on top and pauses; it never leaves the rehearsal (top of this
    // file). main.js closes the message box on the same key and marks the key as used
    // (defaultPrevented): the card then stays, so that one press closes one thing.
    if (e.key === 'Escape') {
      if (!e.defaultPrevented && cardShown()) hideCard();
      this.pause();
      return;
    }
    if (e.code !== 'Space' || e.defaultPrevented || spaceBelongsTo(e.target)) return;
    e.preventDefault();
    this.togglePlay();
  }

  // ---- guide (web/guide_core.js, shared with the arm-tablet guide) ---------------

  // guide_core route of a parsed route; null without a time and energy profile.
  _guideRoute(route, kind) {
    const pr = route && route.profile;
    if (!pr || !pr.t_s || !pr.used_wh || !(route.totals.usable_wh > 0)) return null;
    const goal = this.plan.points.find(p => p.kind === 'goal');
    return G.prepareRoute({coords: route.coords, t: pr.t_s, used: pr.used_wh, rv: pr.rv_wh || null,
                           rvTime: pr.rv_time_s || null, usable: route.totals.usable_wh,
                           turnIndex: route.turnIndex, kind,
                           goalName: goal && goal.properties.station ? `Arrive at station ${goal.properties.station}` : 'Arrive at the goal',
                           stops: route.stops.map(st => ({i: st.index, name: st.id}))});
  }

  _vertex() { return Math.min(this.guide.coords.length - 1, Math.floor(this.state.at + 1e-6)); }

  _limitS() { return G.evaLimitS({request: {max_duration_min: this.plan && this.plan.properties.max_duration_min}}); }

  // Clock and energy of the walker now (between vertices, or standing at a stop).
  _now() {
    const s = this.state, pr = s && s.profile;
    return pr && Number.isFinite(pr.used_wh) ? {t: s.time, used: pr.used_wh} : null;
  }

  _showGuide() {
    const g = this.guide;
    el('rh-man').hidden = !g;
    el('rh-meters').hidden = !g;
    if (!g) return;
    // The next maneuver as on the tablet: the arrow, the distance big ("350 m", "Now"), the
    // instruction under it; at the habitat, "Home". Written only when it changes: the box
    // is a live region, read out at every change.
    const i = this._vertex(), {event, distText} = G.nextManeuver(g, i);
    const put = (id, text) => { if (el(id).textContent !== text) el(id).textContent = text; };
    put('rh-man-arrow', this._arrived ? '⌂' : event.arrow);
    put('rh-man-dist', this._arrived ? 'Home' : maneuverDistance(distText));
    put('rh-man-text', this._arrived ? 'You are at the habitat.' : event.text);
    if (this.playing) {
      for (const text of G.announcements(g, i, this._spoken)) this.voice.say(text);
      for (const text of G.radioAnnouncements(g, i, this._spoken)) {
        this.voice.say(text);
        if (this.walkLog) G.logEvent(this.walkLog, 'radio', text, g, i);
      }
      // Only what is played counts as walked (dragging the scrubber is not walking).
      if (this.walkLog) G.logStep(this.walkLog, g, i, [this.state.x, this.state.y]);
      this._adaptiveStep(g, i);
    }
    // The meters as on the tablet: each bar coloured by its state, and the glossary's state
    // word (OK / LOW / TURN BACK, on every meter) beside the value, so that the meaning never
    // rests on colour alone. The values keep their own elements, which ?check=guide reads.
    const m = G.meters(g, i, this._limitS());
    const fill = (id, frac, state) => {
      const f = el(id);
      f.style.width = `${Math.max(0, Math.min(1, frac)) * 100}%`;
      f.style.background = state === 'ok' ? METER.good : state === 'low' ? METER.warn : METER.bad;
    };
    const word = (id, meter) => Object.assign(el(id), {textContent: meter.word, className: `rh-word ${meter.state}`});
    fill('rh-m-energy', m.energy.frac, m.energy.state); word('rh-w-energy', m.energy);
    el('rh-v-energy').textContent = m.energy.text;
    fill('rh-m-back', m.back.frac, m.back.state); word('rh-w-back', m.back);
    el('rh-v-back').textContent = homeInText(m.back.s);              // the tablet's "home in 12 min"
    // The radio row keeps its place while the server is asked (it answers a moment after
    // entering, or after a way home), so the player does not jump when it answers; with no
    // radio data at all it goes, as on the tablet.
    const radio = G.radioState(g, i), checking = !radio && this._radioPending === g;
    for (const id of ['rh-radio-label', 'rh-radio-track', 'rh-v-radio']) el(id).hidden = !radio && !checking;
    if (radio) {                     // as the tablet's radio line: green, amber with no link
      fill('rh-m-radio', radio.state === 'direct' ? 1 : radio.state === 'relay' ? 0.5 : 0, radio.good ? 'ok' : 'low');
      el('rh-v-radio').textContent = radio.text;
    } else if (checking) {
      el('rh-m-radio').style.width = '0%';
      el('rh-v-radio').textContent = 'checking…';
    }
    for (const id of ['rh-eva-label', 'rh-eva-track', 'rh-eva-value']) el(id).hidden = !m.eva;
    if (m.eva) {
      fill('rh-m-eva', m.eva.frac, m.eva.state); word('rh-w-eva', m.eva);
      el('rh-v-eva').textContent = m.eva.text;
    }
  }

  // Walk a new guide route from here on (a way home or a rejoin), drawn on the ground.
  _walkRoute(groute, color, points) {
    const used = groute.used, last = used.length - 1;
    const route = {kind: 'route', coords: groute.coords, turnIndex: groute.turnIndex,
                   stops: (groute.stops || []).map(st => ({index: st.i, id: st.name})),
                   totals: {usable_wh: groute.usable},
                   profile: {t_s: groute.t, used_wh: used, rv_time_s: groute.rvTime,
                             rv_wh: groute.rv || used.map(v => used[last] - v)}};   // guide_core sets rv
    this.model = buildRehearsal(route, points);
    this._replaced = true;
    this.guide = groute;
    if (this.adaptive) G.adaptiveNewRoute(this.adaptive, groute);
    this._radio(groute);
    this._spoken.clear();
    this._extra = [{lines: [groute.coords], color, width: 4}];
    el('rh-scrub').min = this.model.start;
    el('rh-scrub').max = this.model.end;
    this.seek(this.model.start);
  }

  // Radio along a guide route (E11), asked in the background; redraw when it answers.
  _radio(g) {
    if (!g) return;
    const habitat = this.plan && this.plan.properties.habitat;
    this._radioPending = g;
    G.attachComms(g, Array.isArray(habitat) ? habitat : null).then(() => {
      if (this._radioPending === g) this._radioPending = null;
      if (this.active && this.guide === g) { this._showGuide(); this._dirty = true; }
    });
  }

  // At the habitat: the walk against the plan, as a card with "Replay" and "Exit", kept
  // for the debrief (POST /walks). Once per walk log; the card is kept for a later arrival.
  _finishWalk() {
    const log = this.walkLog;
    if (!log || log.done) return null;
    log.done = true;
    const s = G.walkSummary(log);
    if (!s) return null;
    const rows = G.summaryRows(s).map(([label, plan, walked]) => [label, `${walked} (plan ${plan})`]);
    if (s.skipped.length) rows.push(['Skipped', s.skipped.join(', ')]);
    rows.push(...adaptiveCardRows(G.adaptiveRows(this.adaptive)));
    const events = s.events.map(e => `${e.t != null ? T.min(e.t - this._evaStart) + ' · ' : ''}${e.text}`);
    this._endCard = {title: 'Plan against the walk', subtitle: 'rehearsal', rows,
                     note: events.length ? events.join(' | ') : 'Walked as planned.', actions: this._endActions()};
    showCard(this._endCard);
    this._stopCard = true;
    G.postWalk(s, log);
    return s;
  }

  _planRef() { return {plan: {properties: this.plan.properties}}; }   // what guide_core asks of a saved plan

  async returnHome() {
    if (!this.active || !this.guide) return null;
    this.pause(false);
    this._note('Computing the fastest way home…');
    const token = ++this._token;               // a later click, a seek or exit drops this answer
    try {
      const i = this._vertex();
      let home = await G.returnHome(this.guide, i, this._planRef(), [this.state.x, this.state.y], this._now());
      if (token !== this._token || !this.active) return null;
      // Already at the habitat: the way home is a single point, walked in no time (#115).
      if (home.route.coords.length === 1) home = {...home, text: 'You are already at the habitat.', speech: 'You are at the habitat.'};
      if (this.walkLog) G.logEvent(this.walkLog, 'home', home.text, this.guide, this._vertex());
      // The way home is a stretch of the EVA, from the first time home was asked (#124).
      if (this._homeStart === null) this._homeStart = home.route.t[0];
      this._walkRoute(home.route, HOME_LINE, []);
      this._note(home.text);
      this.voice.say(home.speech);
      return home;
    } catch (err) { this._note(`${N.returnHome}: ${err.message}`); return null; }
  }

  async detour() {
    if (!this.active || !this.guide) return;
    this.pause(false);
    const i = this._vertex(), pt = G.detourPoint(this.guide, i);
    this._note(`${N.offRoute} (25 m) — recalculating…`);
    this.voice.say('You are off route. Recalculating.', {priority: 'alert'});   // routine lines cannot cut it off
    const token = ++this._token;
    try {
      const out = await G.rejoin(this.guide, i, pt, this._planRef(), this._now());
      if (token !== this._token || !this.active) return;
      if (!out) { this._note('Still within 15 m of the route: no rejoin needed.'); return; }
      if (this.walkLog) G.logEvent(this.walkLog, 'detour', `off route ${out.offM.toFixed(0)} m; ${out.text}`, this.guide, i);
      this._walkRoute(out.route, REJOIN_LINE, this.guide.kind === 'plan' ? this.plan.points : []);
      this._note(out.text);
      this.voice.say('New route found.');
    } catch (err) { this._note(`Rejoin: ${err.message}`); }
  }

  async solarStorm() {
    if (!this.active || !this.guide) return;
    const alert = el('rh-alert');
    this._setStorm(true);                      // also the band on top and the red vignette
    this._kAlarm = false;
    alert.hidden = false;
    alert.innerHTML = G.STORM_PENDING;
    if (this.walkLog) G.logEvent(this.walkLog, 'storm', 'solar storm alert: return home', this.guide, this._vertex());
    this.voice.say(`Solar storm alert. ${N.returnHome} now.`, {priority: 'alert'});     // the tablet's words
    if (this._radInfo === undefined) {
      try { const res = await fetch('/radiation'); this._radInfo = res.ok ? await res.json() : null; }
      catch { this._radInfo = null; }
      if (!this.active || !this._storm) return;          // left, replayed or arrived meanwhile
    }
    const home = await this.returnHome();
    if (!home) {
      if (this.active && this._storm) alert.innerHTML = G.stormFailedHtml(el('rh-note').textContent);
      return;
    }
    alert.innerHTML = G.stormHtml(G.stormMessage(home.route, this._radInfo));
    this.play();
  }

  // ---- adaptive walkback (X2, #101, #129) ---------------------------------------

  _newAdaptive() {
    this.adaptive = G.createAdaptive({kTrue: this.kTrue});
    if (this.guide) G.adaptiveNewRoute(this.adaptive, this.guide);
    this._kAlarm = false;
    this._kState = null;
    for (const id of ['rh-k-label', 'rh-k-track', 'rh-k-value']) el(id).hidden = true;
  }

  // One observed segment every 30 m played: the posterior of k, the meter and the alarm.
  _adaptiveStep(g, i) {
    if (!this.adaptive || !this.walkbackOnPause) return;      // checks.js: ask nothing
    const state = this.adaptive;
    G.adaptiveStep(state, g, i).then(res => {
      // (at the habitat the walk is over: an answer still on its way changes nothing)
      if (!res || !this.active || this.adaptive !== state || this._arrived) return;
      const km = G.kMeter(res);
      for (const id of ['rh-k-label', 'rh-k-track', 'rh-k-value']) el(id).hidden = false;
      const fill = el('rh-m-k'), frac = Math.max(0, Math.min(1, km.frac));
      fill.style.width = `${frac * 100}%`;
      fill.style.background = km.state === 'ok' ? METER.good : km.state === 'low' ? METER.warn : METER.bad;
      el('rh-k-track').setAttribute('aria-valuenow', String(Math.round(frac * 100)));
      el('rh-k-track').setAttribute('aria-valuetext', `${km.word}, ${km.text}`);
      // The state word as the other meters have it: bold, in its state's colour (OK, LOW,
      // TURN BACK; the RETURN NOW banner is the alert's), then the value.
      Object.assign(el('rh-w-k'), {textContent: km.word, className: `rh-word ${km.state}`});
      el('rh-v-k').textContent = km.text;
      // Crossing into LOW is said once, as on the tablet (RETURN NOW has its own line).
      if (km.state === 'low' && this._kState === 'ok') {
        this.voice.say('Your energy use is above the plan. Plan to turn back.', {priority: 'alert'});
      }
      this._kState = km.state;
      // The RETURN NOW banner, with the tablet's rules (kAlarmAction in rehearse_model.js).
      const home = Boolean(this.guide && this.guide.kind === 'home'), alert = el('rh-alert');
      const action = kAlarmAction({returnNow: res.return_now, storm: this._storm, home, showing: this._kAlarm});
      if (action === 'show') {
        this._kAlarm = true;
        const msg = G.kAlarmMessage(res);
        alert.innerHTML = msg.html;
        alert.hidden = false;
        this.voice.say(msg.speech, {priority: 'alert'});
        if (this.walkLog) G.logEvent(this.walkLog, 'k_alarm', 'return now: way home at k p90 does not fit', g, i);
      } else if (action === 'clear') {
        this._kAlarm = false;
        alert.hidden = true;
      }
    });
  }

  // ---- walkback lines on pause -------------------------------------------------

  _note(...nodes) {
    const m = this.model, note = el('rh-note');
    if (nodes.length) { note.replaceChildren(...nodes); return; }
    note.textContent = m.assumedSpeed !== null
      ? `This plan has no times or energy: walking at an assumed ${m.assumedSpeed.toFixed(0)} m/s.` : '';
  }

  _clearWalkback() {
    this._token++;                             // an answer still on its way is dropped
    if (this._extra.length) { this.lines.set(this._extra); this._dirty = true; }
    else if (this.lines.sets.length) { this.lines.clear(); this._dirty = true; }
    this.walkback = null;
    if (this.active) this._note();
  }

  // Ask for the walkback lines from where the walker is, with the energy left.
  async _settle() {
    const {model, state, plan} = this;
    const bar = state && energyReadout(state.profile, model.usableWh);
    if (!this.active || !bar || !this.walkbackOnPause) return;
    const token = ++this._token, start = plan.points.find(p => p.kind === 'start');
    const base = start ? [start.x, start.y] : (Array.isArray(plan.properties.habitat) ? plan.properties.habitat : null);
    const lead = `${N.returnHome} from here: `;
    this._note(`${lead}computing…`);
    const {fc, error} = await requestWalkback(walkbackRequest(
      {x: state.x, y: state.y, energyLeftWh: bar.energyLeft, base, properties: plan.properties}));
    if (token !== this._token || !this.active) return;         // played on, moved or left meanwhile
    if (!fc) { this._note(`${lead}${error}`); return; }
    const lines = kind => fc.features.filter(f => f.properties && f.properties.kind === kind && f.geometry &&
                                                  f.geometry.type === 'MultiLineString')
                                     .flatMap(f => f.geometry.coordinates);
    this.lines.set([...this._extra, {lines: lines('energy_safe_boundary'), color: SAFE_LINE, width: 2.5},
                    {lines: lines('emergency_time_boundary'), color: RED_LINE, width: 3}]);
    const p = this.walkback = fc.properties || {};
    const part = (ok, text) => Object.assign(document.createElement('span'),
                                             {className: ok ? 'wb-ok' : 'wb-bad', textContent: `${ok ? '✔' : '⚠'} ${text}`});
    // In the tablet's words ("Return home: 13 min, …", "spare") and the glossary's numbers
    // (whole minutes and Wh, "limit 30"): time against the 30 min line, then energy and what
    // is left after it; then what the two lines on the ground are.
    const parts = [];
    if (Number.isFinite(p.return_time_s)) {
      parts.push(part(p.contingency_ok, `${T.min(p.return_time_s)} (${N.homeLimit})`));
    }
    if (Number.isFinite(p.return_energy_wh) && Number.isFinite(p.energy_left_after_return_wh)) {
      parts.push(part(p.energy_ok, `${T.wh(p.return_energy_wh)}, ${T.wh(p.energy_left_after_return_wh)} spare after it`));
    }
    this._note(lead, ...parts.flatMap((node, k) => (k ? [' · ', node] : [node])),
               ' (red line: 30 min from home · cyan line: energy-safe area)');
    this._dirty = true;
  }
}
