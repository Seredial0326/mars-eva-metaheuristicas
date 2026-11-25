// Screenshots of the real app for the landing page and the demo page (web/home/, #126, #173).
// Reproducible: run from the repo root with the API and a browser started with remote
// debugging (Edge or Chrome; headless is fine):
//
//   python -m uvicorn api.main:app --port 8000
//   chrome --headless=new --remote-debugging-port=9222 --window-size=1440,900 about:blank
//   node docs/landing/capture.mjs [http://localhost:8000] [9222] [out-dir] [only,these,shots]
//   python docs/landing/make_webp.py [out-dir]          # PNG -> web/home/assets/*.webp
//
// It plans the default walk (120 min, 1,000 Wh), so it REPLACES data/plans/last_plan.json:
// back it up first. It saves no stations and no walks. Use the stations-v1 release (13
// stations): the numbers on the pages come from it. PNGs are taken at 2x and written to
// out-dir (default: the system temp folder), named after the image they replace.
// photo-3d and the photo pins need the rover photo catalogue (data/tiles/3d/photos/);
// without it photo-3d is skipped and says so.
import { mkdirSync, writeFileSync } from 'node:fs';
import { tmpdir } from 'node:os';
import { join } from 'node:path';

const BASE = process.argv[2] || 'http://localhost:8000';
const PORT = process.argv[3] || '9222';
const OUT = process.argv[4] || join(tmpdir(), 'landing-shots');
const ONLY = process.argv[5] ? new Set(process.argv[5].split(',')) : null;
mkdirSync(OUT, {recursive: true});
const want = name => !ONLY || ONLY.has(name);

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const ws = new WebSocket(list.find(t => t.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise(r => { ws.onopen = r; });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async x => (await send('Runtime.evaluate', {expression: x, awaitPromise: true, returnByValue: true})).result.result?.value;
const sleep = ms => new Promise(r => setTimeout(r, ms));
const until = async (expr, ms = 60000, step = 500) => {
  for (let t = 0; t < ms; t += step) { if (await ev(expr)) return true; await sleep(step); }
  console.warn(`  timed out waiting for: ${expr}`); return false;
};

const HELPERS = `
window.__q = sel => document.querySelector(sel);
window.__check = (sel, on) => { const el = __q(sel); if (el && el.checked !== on) el.click(); };
window.__set = (sel, v) => { const e = __q(sel); e.value = String(v); e.dispatchEvent(new Event('input')); e.dispatchEvent(new Event('change')); };
window.__text = sel => (__q(sel) || {}).innerText || '';
`;
const page = async (url, w, h, wait = 6000) => {
  await send('Emulation.setDeviceMetricsOverride', {width: w, height: h, deviceScaleFactor: 2, mobile: false});
  await send('Page.navigate', {url});
  await sleep(wait);
  await ev(HELPERS);
};
const shot = async name => {
  const {result} = await send('Page.captureScreenshot', {format: 'png'});
  writeFileSync(join(OUT, `${name}.png`), Buffer.from(result.data, 'base64'));
  console.log(`${name}.png`);
};
const click = sel => ev(`(__q(${JSON.stringify(sel)}) || {click(){}}).click(); 1`);
const tab = async t => { await click(`#tab-${t}`); await sleep(900); };

// ---- 2D planner, 1440 x 900 ------------------------------------------------------------
// The terrain and station shots come first, before anything is planned (stations only, no
// route), as a presenter sees them in steps 1-4 of docs/demo.md.
await page(`${BASE}/?tips=off`, 1440, 900, 8000);
await ev(`try { localStorage.clear(); } catch {} 1`);
await page(`${BASE}/?tips=off`, 1440, 900, 8000);

if (want('step-terrain')) {
  await tab('terrain');
  await ev(`__check('#show-slope', true); __check('#show-sand', true); __check('#show-rocks', true); 1`);
  await click('#fit-all'); await sleep(4000); await shot('step-terrain');
  await ev(`__check('#show-sand', false); __check('#show-rocks', false); 1`);
}
if (want('step-cost')) {
  await tab('terrain');
  await ev(`__check('#show-slope', false); __check('#show-cost', true); 1`); await sleep(4000); await shot('step-cost');
  await ev(`__check('#show-cost', false); __check('#show-slope', true); 1`);
}
if (want('step-steep')) {
  await tab('terrain');
  await ev(`__check('#block-on', true); __set('#block-slope', 20); 1`);
  await until(`/off limits/.test(__text('#block-info'))`, 30000);
  await sleep(3000); await shot('step-steep');
  await ev(`__set('#block-slope', 30); 1`); await sleep(2000);
}
if (want('step-stations')) { await tab('stations'); await sleep(2000); await shot('step-stations'); }

// Plan the default walk: the plan, walk, radio and storm shots need it.
await tab('plan');
await ev(`__set('#max-min', 120); __set('#budget-wh', 1000); 1`);
await click('#plan-btn');
await until(`/Stations visited|No plan/.test(__text('#plan-info'))`, 120000, 1500);
await sleep(3000);
if (want('plan-2d')) { await click('#fit-plan'); await sleep(2500); await shot('plan-2d'); }
if (want('step-radio')) {
  await click('#radio-show'); await sleep(5000); await shot('step-radio');
  await click('#radio-show'); await sleep(1000);
}
// Walk: rehearse about 6.5 min of the EVA (6.5 s at x60), so the astronaut is out on the route.
if (want('walkback-2d') || want('step-storm')) {
  await tab('walk');
  await ev(`__check('#show-radius', true); 1`);
  await click('#play-btn'); await sleep(6500); await click('#play-btn');
  await click('#fit-all'); await sleep(5000);
  if (want('walkback-2d')) await shot('walkback-2d');
}
if (want('step-storm')) {
  await tab('context');
  await ev(`document.querySelectorAll('#panel-context details').forEach((d, k) => d.open = k === 0); 1`);   // Radiation only
  await click('#sep-btn');
  await until(`!__q('#storm-banner').hidden`, 60000); await sleep(4000); await shot('step-storm');
  await click('#storm-dismiss'); await sleep(1000);
}
if (want('step-weather')) {
  await tab('context');
  await ev(`document.querySelectorAll('#panel-context details').forEach(d => d.open = /Weather on the day/.test(d.querySelector('summary')?.innerText || '')); 1`);
  await sleep(3000); await shot('step-weather');
}

// ---- Tablet guide, 592 x 1180 ----------------------------------------------------------
if (want('guide-walk') || want('guide-storm')) {
  await page(`${BASE}/guide.html`, 592, 1180, 8000);
  // Walk until the guide warns that direct radio is about to drop, then pause.
  await click('#walk-btn');
  const warned = await until(`/lose direct radio/i.test(__text('#status'))`, 120000, 250);
  await click('#walk-btn'); await sleep(1500);
  if (want('guide-walk')) { if (!warned) console.warn('  guide-walk: no radio warning seen'); await shot('guide-walk'); }
  if (want('guide-storm')) {
    // Further out (about 6 min from home, before the first station: the guide stops at
    // each station's card), so the way home is a real walk.
    await click('#walk-btn');
    await until(`parseInt(__text('#t-val').split('home in ')[1]) >= 6`, 120000, 250);
    await click('#walk-btn'); await sleep(1000);
    await ev(`document.getElementById('demo').open = true; 1`);
    await click('#sep-btn');
    await until(`!__q('#alert').hidden && /home now/i.test(__text('#alert')) && /home in/.test(__text('#man-text'))`, 60000, 200);
    await click('#walk-btn');                          // the guide walks home on its own: hold it here
    await ev(`document.getElementById('demo').open = false; window.scrollTo(0, 0); 1`);
    await sleep(1500); await shot('guide-storm');
  }
}

// ---- 3D view ---------------------------------------------------------------------------
// Ready: the terrain is built (window.viz3d) and the saved plan is loaded (Rehearse enabled).
const fold3d = () => ev(`document.querySelectorAll('details').forEach(d => d.open = false); 1`);
const ready3d = () => until(`!!(window.viz3d && window.viz3d.terrain) && !document.getElementById('rehearse').disabled`, 90000, 1000);
if (want('poster-3d')) { await page(`${BASE}/3d/?q=high&lt=11:00`, 1600, 900, 4000); await ready3d(); await fold3d(); await sleep(6000); await shot('poster-3d'); }
if (want('hero-3d')) {
  // An angle from the south-west over the tour, looking north-east to the habitat.
  await page(`${BASE}/3d/?q=high&lt=11:00&view=8143080,-285230,-3340,32,24`, 1600, 900, 4000);
  await ready3d(); await fold3d(); await sleep(8000); await shot('hero-3d');
}
// Rehearsal: play at the fastest speed; it pauses at every stop with the station's card.
const rehearseTo = async (stops, chase) => {
  await page(`${BASE}/3d/?q=high&lt=11:00`, chase ? 1600 : 1440, 900, 4000);
  await ready3d(); await sleep(3000);
  await ev(`(() => { const d = [...document.querySelectorAll('details')].find(x => /Plan/.test(x.querySelector('summary')?.innerText || '')); if (d) d.open = true; })(); 1`);
  await click('#rehearse'); await sleep(3000);
  await ev(`(() => { const s = __q('#rh-speed'); if (s) { s.value = s.options[s.options.length - 1].value; s.dispatchEvent(new Event('change')); } })(); 1`);
  for (let k = 0; k < stops; k++) {
    const before = await ev(`__text('#rh-progress')`);
    await click('#rh-play');
    await until(`__text('#rh-progress') !== ${JSON.stringify(before)} && / at [A-Z]\\d/.test(__text('#rh-progress')) && /Play/.test(__text('#rh-play'))`, 90000, 300);
  }
  if (chase) await click('#rh-chase');
  await sleep(4000);
};
if (want('rehearse-3d')) {
  await rehearseTo(2, true);                 // at R2, on a ridge
  await ev(`document.dispatchEvent(new KeyboardEvent('keydown', {key: 'Escape', bubbles: true})); 1`);   // close the card
  await sleep(2500); await shot('rehearse-3d');
}
if (want('step-rehearse')) { await rehearseTo(5, false); await shot('step-rehearse'); }
if (want('photo-3d')) {
  const hasPhotos = await ev(`fetch('/tiles/3d/photos/catalog.json').then(r => r.ok)`);
  if (!hasPhotos) console.warn('photo-3d: skipped, no rover photo catalogue on this machine');
  else {
    await page(`${BASE}/3d/?q=high&lt=11:00`, 1000, 989, 4000); await ready3d();
    const pid = await ev(`fetch('/tiles/3d/photos/catalog.json').then(r => r.json()).then(c => (c.photos || [])[0]?.id || null)`);
    await page(`${BASE}/3d/?q=high&lt=11:00&photo=${pid}`, 1000, 989, 4000); await ready3d(); await sleep(8000); await shot('photo-3d');
  }
}
console.log(`done: ${OUT}`);
ws.close();
