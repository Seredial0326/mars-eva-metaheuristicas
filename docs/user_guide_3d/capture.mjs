// Screenshots of the 3D map (/3d/) for its user guide, with the on-screen box of every
// control the guide points at. Run from the repo root with the API on port 8000, a saved
// plan (plan once in the 2D planner) and Edge or Chrome started with a debugging port:
//
//   python -m uvicorn api.main:app --port 8000
//   msedge --headless=new --remote-debugging-port=9222 --window-size=1440,900 about:blank
//   node docs/user_guide_3d/capture.mjs [http://localhost:8000] [9222] [only,these,shots]
//
// Writes docs/user_guide_3d/img/<shot>.jpg and docs/user_guide_3d/shots.json; then
// `python docs/user_guide/build.py docs/user_guide_3d` writes the page.
import { mkdirSync, writeFileSync, readFileSync, existsSync } from 'node:fs';

const BASE = process.argv[2] || 'http://localhost:8000';
const PORT = process.argv[3] || '9222';
const ONLY = process.argv[4] ? new Set(process.argv[4].split(',')) : null;
const W = 1440, H = 900;
const OUT = new URL('./', import.meta.url);
mkdirSync(new URL('img/', OUT), {recursive: true});
const shotsFile = new URL('shots.json', OUT);
const shots = existsSync(shotsFile) ? JSON.parse(readFileSync(shotsFile, 'utf8')) : {};

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const ws = new WebSocket(list.find(t => t.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise(r => { ws.onopen = r; });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async x => (await send('Runtime.evaluate', {expression: x, awaitPromise: true, returnByValue: true})).result.result?.value;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// In-page helpers. A mark is a CSS selector, 'text:<tag>|<start of its text>', or
// 'pin:<label>' (a pin of the plan: its 3D point projected to the screen).
const HELPERS = `
window.__q = (sel) => {
  if (sel.startsWith('text:')) {
    const [tag, text] = sel.slice(5).split('|');
    return [...document.querySelectorAll(tag)].find(e => e.offsetParent !== null && e.textContent.trim().startsWith(text)) || null;
  }
  return document.querySelector(sel);
};
window.__box = (sel, label) => {
  if (sel.startsWith('pin:')) {
    const m = viz3d.markers, it = m.items.find(i => i.marker.label === sel.slice(4));
    if (!it || !m.group.visible) return null;
    const p = viz3d.camera.position.clone().set(...it.position).project(viz3d.camera);
    if (p.z > 1) return null;
    const r = viz3d.renderer.domElement.getBoundingClientRect();
    const x = r.x + (p.x + 1) / 2 * r.width, y = r.y + (1 - p.y) / 2 * r.height;
    return {x: x - 30, y: y - 52, w: 60, h: 56};
  }
  let el = __q(sel); if (!el) return null;
  if (label && el.closest('label')) el = el.closest('label');
  const r = el.getBoundingClientRect();
  return r.width && r.height ? {x: r.x, y: r.y, w: r.width, h: r.height} : null;
};
window.__open = (id, on = true) => { const d = document.getElementById(id); if (d && d.open !== on) d.open = on; return 1; };
window.__click = (sel) => { const e = __q(sel); if (e) e.click(); return !!e; };
`;
const load = async (query = '') => {
  await send('Page.navigate', {url: `${BASE}/3d/?q=high${query ? '&' + query : ''}`});   // sharp photo, 2 m mesh
  for (let k = 0; k < 60; k++) {                        // the terrain and the plan are in
    await sleep(1000);
    if (await ev(`!!(window.viz3d && viz3d.plan && document.getElementById('plan-facts')?.textContent.trim())`)) break;
  }
  await sleep(3000);
  await ev(HELPERS);
};
const want = name => !ONLY || ONLY.has(name);
// panel: right edge of the side panel (badges of its controls in one column beside it);
// around: a box whose controls get their badges in two columns at its sides (the player).
async function shot(name, marks, panel = 0, around = null) {
  await ev('viz3d.redraw && viz3d.redraw(); 1'); await sleep(700);
  const boxes = [];
  for (const [n, sel, label] of marks) {
    const b = await ev(`__box(${JSON.stringify(sel)}, ${label ? 'true' : 'false'})`);
    if (b) boxes.push({n, ...b}); else console.warn(`  ${name}: mark ${n} not found (${sel})`);
  }
  const {result} = await send('Page.captureScreenshot', {format: 'jpeg', quality: 82});
  writeFileSync(new URL(`img/${name}.jpg`, OUT), Buffer.from(result.data, 'base64'));
  shots[name] = {img: `img/${name}.jpg`, w: W, h: H, panel_w: panel, marks: boxes};
  if (around) {
    const a = await ev(`__box(${JSON.stringify(around)})`);
    if (a) shots[name].columns = [Math.round(a.x - 34), Math.round(a.x + a.w + 34)];
  }
  console.log(`${name}: ${boxes.length} marks`);
}
const click = sel => ev(`__click(${JSON.stringify(sel)})`);
const cardHas = text => ev(`!document.getElementById('card').hidden && document.getElementById('card').textContent.includes(${JSON.stringify(text)})`);
const PANEL = 270;                                       // right edge of the side panel

await send('Emulation.setDeviceMetricsOverride', {width: W, height: H, deviceScaleFactor: 1, mobile: false});

// 1. The page as it opens; 2. the plan section; 3. a station's card.
if (want('overview') || want('plan') || want('station')) {
  await load();
  if (want('overview')) await shot('overview', [
    [1, '#info'], [2, '#relief'], [3, '#plan-box'], [4, 'text:a|← Planner'], [5, '#compass'], [6, '#home'],
    [7, 'pin:Habitat'], [8, '#readout'],
  ], PANEL);
  await ev(`document.getElementById('station-list-title').parentElement.open = true; 1`); await sleep(800);
  if (want('plan')) await shot('plan', [
    [1, '#plan-source'], [2, '#plan-facts'], [3, '#plan-key'], [4, '#plan-warnings'], [5, '#station-list-title'],
    [6, '#station-list'], [7, '#plan-reload'], [8, '#rehearse'], [9, '#walk'],
  ], PANEL);
  await ev(`(document.querySelector('#station-list button') || {click(){}}).click(); 1`);
  await sleep(5000);
  if (want('station')) await shot('station', [[1, '#station-list button'], [2, '#card'], [3, 'text:button|Fly here'], [4, '#card .card-close']], PANEL);
}

// 4. Sun and shadows, late afternoon.
if (want('sun')) {
  await load('lt=17:30');
  await ev(`__open('plan-box', false); __open('sun-box'); const s = document.getElementById('shadows'); if (!s.checked) s.click(); 1`);
  await sleep(4000);
  await shot('sun', [
    [1, '#sun-sol'], [2, '#sun-time'], [3, '#sun-readout'], [4, '#sun-note'], [5, '#relief-only', true], [6, '#shadows', true],
  ], PANEL);
}

// 5. A map layer on the relief.
if (want('layer')) {
  await load();
  await ev(`__open('plan-box', false); __open('layers-box'); const s = document.getElementById('layer-pick');
    s.value = [...s.options].find(o => /slope/i.test(o.textContent) && !/steep/i.test(o.textContent)).value;
    s.dispatchEvent(new Event('change')); 1`);
  await sleep(7000);
  await shot('layer', [[1, '#layer-pick'], [2, '#layer-opacity'], [3, '#layer-legend']], PANEL);
}

// 6. About this view.
if (want('about')) {
  await load();
  await ev(`__open('plan-box', false); __open('about'); 1`); await sleep(800);
  await shot('about', [[1, '#copy-view'], [2, '#save-image']], PANEL);
}

// 7. Rehearsal a few minutes in, paused; its More box; the first stop; energy use above the model.
if (want('rehearse') || want('rehearse-more') || want('stop') || want('adaptive')) {
  await load();
  await click('#rehearse'); await sleep(4000);
  await click('#rh-play'); await sleep(6000); await click('#rh-play'); await sleep(4000);
  if (want('rehearse')) await shot('rehearse', [
    [1, '#rh-man'], [2, '#rh-play'], [3, '#rh-home'], [4, '#rh-detour'], [5, '#rh-storm'], [6, '#rh-more'],
    [7, '#rh-panel'], [8, '#rh-exit'], [9, '#rh-scrub'], [10, '#rh-progress'], [11, '#rh-sun'], [12, '#rh-energy'],
    [13, '#rh-meters'], [14, '#rh-note'],
  ], 0, '#player');
  await click('#rh-more'); await sleep(800);
  if (want('rehearse-more')) await shot('rehearse-more', [
    [1, '#rh-chase'], [2, '#rh-recentre'], [3, '#rh-speed'], [4, '#rh-voice'], [5, '#rh-ktrue'], [6, '#rh-energy-text']], 0, '#player');
  await click('#rh-more');
  await click('#rh-play');
  for (let k = 0; k < 60; k++) { await sleep(1000); if (await cardHas('Done, continue')) break; }
  await sleep(5000);
  if (want('stop')) await shot('stop', [[1, '#card'], [2, 'text:button|Done, continue'], [3, '#rh-note'], [4, '#rh-man']]);
  await click('text:button|Done, continue');
  await click('#rh-more');
  await ev(`(() => { const b = document.getElementById('rh-ktrue'); for (let i = 0; i < 4 && !/1\\.5/.test(b.textContent); i++) b.click(); })(); 1`);
  for (let k = 0; k < 25; k++) {                         // about 25 min of EVA at x60
    await sleep(1000);
    if (await cardHas('Done, continue')) await click('text:button|Done, continue');
  }
  await click('#rh-play'); await sleep(3000);
  if (want('adaptive')) await shot('adaptive', [[1, '#rh-ktrue'], [2, '#rh-k-label'], [3, '#rh-v-k'], [4, '#rh-energy-text']], 0, '#player');
}

// 8. Solar storm.
if (want('storm')) {
  await load();
  await click('#rehearse'); await sleep(4000);
  await click('#rh-play'); await sleep(9000);
  await click('#rh-storm'); await sleep(2500); await click('#rh-play'); await sleep(2500);
  await shot('storm', [[1, '#rh-storm-band'], [2, '#rh-storm'], [3, '#rh-man'], [4, '#rh-progress']], 0, '#player');
}

// 9. Off route: 25 m away, then the way back to the route.
if (want('detour')) {
  await load();
  await click('#rehearse'); await sleep(4000);
  await click('#rh-play'); await sleep(9000);
  await click('#rh-detour'); await sleep(3000); await click('#rh-play'); await sleep(2500);
  await shot('detour', [[1, '#rh-detour'], [2, '#rh-man'], [3, '#rh-progress']], 0, '#player');
}

// 10. Home: the end card.
if (want('end')) {
  await load();
  await click('#rehearse'); await sleep(4000);
  // The whole walk at x180, through every stop, so the end card compares a full walk.
  await click('#rh-more');
  await ev(`(() => { const s = document.getElementById('rh-speed'); s.value = '180'; s.dispatchEvent(new Event('change')); })(); 1`);
  await click('#rh-more'); await click('#rh-play');
  for (let k = 0; k < 150; k++) {
    await sleep(1000);
    if (await cardHas('Plan against the walk')) break;
    if (await cardHas('Done, continue')) await click('text:button|Done, continue');
  }
  await sleep(3000);
  await shot('end', [[1, '#card'], [2, '#rh-summary'], [3, '#rh-play'], [4, '#rh-exit']]);
}

// 11. Walk freely, seen from behind.
if (want('walk')) {
  await load();
  await click('#walk'); await sleep(4000);
  await click('#wk-chase'); await sleep(3000);
  await shot('walk', [[1, '#walk-bar'], [2, '#wk-run'], [3, '#wk-fast'], [4, '#wk-chase'], [5, '#wk-exit'], [6, '#wk-keys'], [7, '#readout']]);
}

writeFileSync(shotsFile, JSON.stringify(shots, null, 1));
console.log('done');
ws.close();
