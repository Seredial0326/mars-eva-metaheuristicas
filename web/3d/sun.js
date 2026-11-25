// The Sun of Mars in the 3D map (P1, issue #42, block 4): lights and panel.
//
// The directional light is put where the Sun is at the box centre for a sol and a
// local true solar time (sun_model.js, mars_sun.js), and the light levels follow its
// height. This file owns the two lights, the sky colour, the "Sun" section of the
// panel and the "Relief only" switch; the numbers are in sun_model.js.
//   - Start: sol 4711 at 15:00 unless the address says ?sol=<n>&lt=<hh:mm>. Once a plan
//     is drawn, the start moves to the plan's best time to leave, the one the 2D planner
//     shows (startAtBestTime(), GET /plan/departure), unless the address sets the time.
//   - While the route is rehearsed the Sun moves with the EVA clock (follow()), and
//     goes back to the start when the rehearsal ends.
//   - ?light=az,el (debug) fixes the light as before this block: the Sun is not used.
// The light is a look, not a radiometric model: no atmosphere, no dust, no sky
// brightness. The shadows this light casts are in shadows.js. The photo keeps its own
// mid-afternoon light under the one added here ("Relief only" hides the photo to judge
// the light).
import * as THREE from 'three';
import { loadDeparture } from './api.js';
import * as M from './sun_model.js';

const DISTANCE = 5000;                 // m from the origin: only the direction matters
const NIGHT_SKY = 0x231c18;            // sky and haze at night: dark, not black
const RELIEF_ONLY_GROUND = 0xb4b4b4;   // plain grey ground when the photo is hidden

const el = id => document.getElementById(id);

export class SunView {
  // sun: the DirectionalLight; hemi: the HemisphereLight; sky: the scene's sky colour
  // (number); fixed: [azimuth, elevation] from ?light, or null; start: {sol, hours}, each
  // given only when the address sets it; onChange(): something to draw.
  constructor({terrain, scene, sun, hemi, sky, fixed = null, start = {}, onChange = () => {}}) {
    Object.assign(this, {terrain, scene, sun, hemi, fixed, onChange});
    this.site = M.siteFromCrs(...terrain.toMars(0, 0));
    this.start = {sol: start.sol ?? M.DEFAULT_SOL, hours: start.hours ?? M.DEFAULT_HOURS};
    this.timeFromAddress = start.hours != null;         // ?lt= wins over the planner's time
    this.best = null;                  // the planner's best time to leave {sol, hours}, once it answers
    this.chosen = false;               // the sol or the time was set in the panel
    this.elapsed = null;               // seconds of EVA while rehearsing, else null
    this.state = null;                 // sun_model.sunState() of what is lit (null with ?light)
    this.reliefOnly = false;
    this.daySky = new THREE.Color(sky);
    this.nightSky = new THREE.Color(NIGHT_SKY);
    this.fog = scene.fog;              // kept: a check takes the fog off the scene for a while
    this._photos = null;               // what "Relief only" took away, to put back exactly

    el('sun-sol').max = M.MAX_SOL;
    el('sun-sol').addEventListener('change', e => {
      const sol = M.parseSol(e.target.value);
      if (sol !== null) this.chosen = true;
      this.set({sol: sol === null ? this.start.sol : sol});            // not a sol: the field goes back
    });
    el('sun-time').addEventListener('input', e => {
      this.chosen = true;
      this.set({hours: Number(e.target.value) / 60});
    });
    el('relief-only').addEventListener('change', e => this.setReliefOnly(e.target.checked));
    if (fixed) {
      for (const id of ['sun-sol', 'sun-time']) el(id).disabled = true;
      el('sun-readout').textContent = `Light fixed from the ${M.compassWord(fixed[0])} (${fixed[0]}° from north), ` +
                                      `${fixed[1]}° high.`;
      el('sun-note').textContent = 'The address has ?light= (debug): the Sun of Mars is not used.';
    }
    this._apply();
  }

  // Choose the start: a sol and/or a local true solar time in hours.
  set({sol = this.start.sol, hours = this.start.hours} = {}) {
    this.start = {sol: Math.min(M.MAX_SOL, Math.max(0, Math.round(sol))), hours: ((hours % 24) + 24) % 24};
    this._apply();
  }

  // Start at the plan's best time to leave, as the 2D planner gives it (GET
  // /plan/departure for the sol shown; main.js calls this once a plan is drawn, with that
  // plan). Nothing waits for the answer. The start moves only if nothing has moved the
  // Sun in the meantime (the panel, a photo view, a rehearsal); otherwise the note just
  // says the best time. Nothing changes with ?lt= or ?light= in the address, with no
  // plan, or when the planner gives no best time: the start stays (15:00 by default).
  // ask(sol) is the request (api.js). Resolves to true when the start moved.
  async startAtBestTime(plan, {ask = loadDeparture} = {}) {
    if (this.fixed || this.timeFromAddress || !(plan && plan.fc)) return false;
    const asked = {...this.start};
    const hours = M.bestDeparture(await ask(asked.sol), asked.sol);
    if (hours === null) {
      if (this.best) { this.best = null; this._apply(); }               // an older answer no longer holds
      return false;
    }
    this.best = {sol: asked.sol, hours};
    const moved = this.chosen || this.elapsed !== null || this.start.sol !== asked.sol ||
                  Math.abs(this.start.hours - asked.hours) > 1e-6;
    if (moved) { this._apply(); return false; }
    this.set({hours});
    return true;
  }

  // Rehearsal: seconds of EVA since its start, or null when it is over.
  follow(elapsedS) {
    if (elapsedS === this.elapsed) return;
    this.elapsed = elapsedS;
    this._apply();
  }

  // Hide the photo (plain grey ground) to judge the light without the photo's own
  // shadows; false puts the same textures and colours back.
  setReliefOnly(on) {
    on = Boolean(on);
    el('relief-only').checked = on;
    if (on === this.reliefOnly) return;
    this.reliefOnly = on;
    const materials = this.terrain.materials;
    if (on) {
      this._photos = materials.map(m => ({map: m.map, color: m.color.clone()}));
      for (const m of materials) { m.map = null; m.color.setHex(RELIEF_ONLY_GROUND); m.needsUpdate = true; }
    } else {
      materials.forEach((m, i) => { m.map = this._photos[i].map; m.color.copy(this._photos[i].color); m.needsUpdate = true; });
      this._photos = null;
    }
    this.onChange();
  }

  _apply() {
    const {sun, hemi, fixed} = this;
    if (fixed) {                       // as before this block: full levels from a given direction
      sun.position.set(...M.sunVector(fixed[0], fixed[1])).multiplyScalar(DISTANCE);
      sun.intensity = M.SUN_FULL;
      hemi.intensity = M.SKY_DAY;
      this.onChange();
      return;
    }
    const rehearsing = this.elapsed !== null;
    const s = this.state = M.sunState({...this.start, elapsedS: rehearsing ? this.elapsed : 0}, this.site);
    sun.position.set(...s.direction).multiplyScalar(DISTANCE);
    sun.intensity = s.sun;
    hemi.intensity = s.sky;
    this.scene.background.lerpColors(this.nightSky, this.daySky, s.day);
    this.fog.color.copy(this.scene.background);

    // Panel. The texts are compared first: while playing this runs every frame.
    const show = (id, text) => { if (el(id).textContent !== text) el(id).textContent = text; };
    el('sun-sol').value = this.start.sol;
    el('sun-sol').disabled = el('sun-time').disabled = rehearsing;
    el('sun-time').value = Math.round((rehearsing ? s.ltst : this.start.hours) * 60);
    show('sun-time-text', M.clockText(rehearsing ? s.ltst : this.start.hours));
    show('sun-readout', M.readoutText(s));
    const exact = M.readoutTitle(s);                                    // the numbers, as a tooltip
    if (el('sun-readout').title !== exact) el('sun-readout').title = exact;
    show('sun-note', M.noteText({...this.start, rehearsing, best: this.best, utcMs: s.utcMs}));
    this.onChange();
  }
}
