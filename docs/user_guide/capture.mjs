// Screenshots of the 2D planner for the user guide, with the on-screen box of every
// control the guide points at. Reproducible: run from the repo root, with the API on
// port 8000 and Edge (or Chrome) started with --remote-debugging-port=9222:
//
//   python -m uvicorn api.main:app --port 8000
//   msedge --headless=new --remote-debugging-port=9222 --window-size=1440,900 about:blank
//   node docs/user_guide/capture.mjs [http://localhost:8000] [9222]
//
// Writes docs/user_guide/img/<shot>.jpg and docs/user_guide/shots.json
// ({shot: {img, w, h, marks: [{n, x, y, w, h}]}}); build.py turns them into the page.
import { mkdirSync, writeFileSync } from 'node:fs';

const BASE = process.argv[2] || 'http://localhost:8000';
const PORT = process.argv[3] || '9222';
const W = 1440, H = 900;
const OUT = new URL('./', import.meta.url);
mkdirSync(new URL('img/', OUT), {recursive: true});

const list = await (await fetch(`http://127.0.0.1:${PORT}/json/list`)).json();
const ws = new WebSocket(list.find(t => t.type === 'page').webSocketDebuggerUrl);
let id = 0; const pending = new Map();
ws.onmessage = e => { const m = JSON.parse(e.data); if (m.id && pending.has(m.id)) { pending.get(m.id)(m); pending.delete(m.id); } };
await new Promise(r => { ws.onopen = r; });
const send = (method, params = {}) => new Promise(r => { const i = ++id; pending.set(i, r); ws.send(JSON.stringify({id: i, method, params})); });
const ev = async x => (await send('Runtime.evaluate', {expression: x, awaitPromise: true, returnByValue: true})).result.result?.value;
const sleep = ms => new Promise(r => setTimeout(r, ms));

// In-page helpers: find an element by CSS or by its visible text, and its box.
const HELPERS = `
window.__q = (sel) => {
  if (sel.startsWith('text:')) {
    const [tag, text] = sel.slice(5).split('|');
    return [...document.querySelectorAll(tag)].find(e => e.offsetParent !== null && e.textContent.trim().startsWith(text)) || null;
  }
  return document.querySelector(sel);
};
window.__box = (sel, label) => {
  let el = __q(sel); if (!el) return null;
  if (label && el.closest('label')) el = el.closest('label');
  const r = el.getBoundingClientRect();
  return r.width && r.height ? {x: r.x, y: r.y, w: r.width, h: r.height} : null;
};
window.__check = (sel, on) => { const el = __q(sel); if (el && el.checked !== on) el.click(); };
`;

await send('Emulation.setDeviceMetricsOverride', {width: W, height: H, deviceScaleFactor: 1, mobile: false});
const shots = {};
// 0. The in-context tips (Aaron, #125), as a first-time user sees them: no remembered
// tab or tips in the browser, then ?tips=reset.
await send('Page.navigate', {url: `${BASE}/?tips=off`});
await sleep(4000);
await ev(`try { localStorage.clear(); } catch {} 1`);
await send('Page.navigate', {url: `${BASE}/?tips=reset`});
await sleep(8000);
await ev(HELPERS);
await shotRaw('tips', [[1, '.tipkit'], [2, '.tip-target'], [3, '.tipkit .tip-ok']]);
// Every other screen without tips (?tips=off), so nothing covers the controls.
await ev(`try { localStorage.removeItem('hud-tab'); } catch {} 1`);
await send('Page.navigate', {url: `${BASE}/?tips=off`});
await sleep(8000);
await ev(HELPERS);

async function shot(name, marks) { return shotRaw(name, marks); }
async function shotRaw(name, marks) {
  const boxes = [];
  for (const [n, sel, label] of marks) {
    const b = await ev(`__box(${JSON.stringify(sel)}, ${label ? 'true' : 'false'})`);
    if (b) boxes.push({n, ...b}); else console.warn(`  ${name}: mark ${n} not found (${sel})`);
  }
  const {result} = await send('Page.captureScreenshot', {format: 'jpeg', quality: 82});
  writeFileSync(new URL(`img/${name}.jpg`, OUT), Buffer.from(result.data, 'base64'));
  shots[name] = {img: `img/${name}.jpg`, w: W, h: H, marks: boxes};
  console.log(`${name}: ${boxes.length} marks`);
}
const tab = async t => { await ev(`document.getElementById('tab-${t}').click(); 1`); await sleep(900); };
const click = async sel => { await ev(`(__q(${JSON.stringify(sel)}) || {click(){}}).click(); 1`); };
const set = async (sel, v) => { await ev(`(() => { const e = __q(${JSON.stringify(sel)}); e.value = ${JSON.stringify(String(v))}; e.dispatchEvent(new Event('input')); e.dispatchEvent(new Event('change')); })(); 1`); };
const waitPlan = async () => {
  for (let k = 0; k < 60; k++) {
    await sleep(1500);
    const s = await ev(`document.getElementById('plan-info').innerText`);
    if (s && /Stations visited|No plan/.test(s)) break;
  }
  await sleep(2500);
};

// 1. The whole screen.
await tab('terrain');
await ev(`__check('#show-slope', true); 1`); await sleep(2500);
await shot('overview', [
  [1, '.tabs'], [2, '#panel-terrain'], [3, '#stage'], [4, '#legend'], [5, '#map-tools'], [6, '#readout'], [7, '#sources-chip'],
]);

// 2. Terrain layers.
await ev(`__check('#show-sand', true); 1`); await sleep(2500);
await shot('terrain', [
  [1, '#show-ortho', true], [2, '#show-hillshade', true], [3, '#show-slope', true], [4, '#block-on', true], [5, '#block-info'],
  [6, '#show-sand', true], [7, '#show-rocks', true], [8, '#show-cost', true], [9, '#show-radio', true], [10, '#show-thermal', true],
  [11, '#show-photos', true],
]);
await ev(`__check('#show-sand', false); 1`);

// 3. Stations.
await tab('stations');
await ev(`document.getElementById('stations-advanced').open = true; 1`); await sleep(600);
await shot('stations', [
  [1, '#new-type'], [2, '#add-mode', true], [3, '#load-candidates'], [4, '#stations-advanced > summary'], [5, '#load-e8'],
  [6, '#rubric'], [7, '#station-list'], [8, '#save-stations'],
]);
await ev(`document.getElementById('stations-advanced').open = false; 1`);

// 4. Placing mode: the banner on the map says what a click does.
await ev(`__check('#add-mode', true); 1`); await sleep(800);
await shot('placing', [[1, '#add-mode', true], [2, '#mode-banner']]);
await ev(`__check('#add-mode', false); 1`);

// 5. Plan inputs, before planning.
await tab('plan');
await ev(`document.querySelectorAll('#plan-inputs details.more').forEach(d => d.open = true); 1`); await sleep(500);
await set('#max-min', 120);
await shot('plan-inputs', [
  [1, '#base-mode', true], [2, '#habitat-text'], [3, '#max-min'], [4, '#budget-wh'], [5, '#margin-pct'],
  [6, '#o2-l'], [7, '#human-cost', true], [8, '#plan-btn'],
]);

// 6. The plan.
await click('#plan-btn'); await waitPlan();
await shot('plan-result', [
  [1, '#plan-inputs > summary'], [2, '#plan-info .chip'], [3, '#plan-info .stats'], [4, '#plan-info .order'],
  [5, '#plan-radio'], [6, '#plan-departure'], [7, '#walk-it'], [8, '#fit-plan'],
]);

// 7. When nothing fits.
await ev(`document.getElementById('plan-inputs').open = true; 1`); await sleep(300);
await set('#budget-wh', 60); await click('#replan'); await click('#plan-btn'); await waitPlan();
await ev(`document.querySelectorAll('#plan-inputs details.more').forEach(d => d.open = false); document.getElementById('plan-info').scrollIntoView({block: 'end'}); 1`);
await sleep(600);
await shot('no-plan', [[1, '#budget-wh'], [2, '#plan-info']]);
await set('#budget-wh', 1000); await click('#replan'); await click('#plan-btn'); await waitPlan();

// 8. Walk: rehearse and the safety lines.
await tab('walk');
await ev(`__check('#show-radius', true); 1`);
await click('#play-btn'); await sleep(7000); await click('#play-btn'); await sleep(5000);
await shot('walk', [
  [1, '#ws-back'], [2, '#ws-spare'], [3, '#ws-word'], [4, '#profile'], [5, '#play-btn'], [6, '#play-speed'],
  [7, 'text:a|Tablet'], [8, 'text:button|Show the safety lines'], [9, '#show-radius', true], [10, '#stage'],
]);

// 9. Try another point.
await ev(`document.getElementById('probe').open = true; 1`); await sleep(400);
await ev(`__check('#wb-mode', true); 1`); await sleep(500);
const m = await ev(`__box('#map')`);
await send('Input.dispatchMouseEvent', {type: 'mousePressed', x: m.x + m.w * 0.7, y: m.y + m.h * 0.35, button: 'left', clickCount: 1});
await send('Input.dispatchMouseEvent', {type: 'mouseReleased', x: m.x + m.w * 0.7, y: m.y + m.h * 0.35, button: 'left', clickCount: 1});
await sleep(9000);
await shot('probe', [[1, '#wb-mode', true], [2, '#wb-energy'], [3, '#wb-info'], [4, '#stage']]);
await ev(`__check('#wb-mode', false); 1`);

// 10. Context.
await tab('context');
await ev(`document.querySelectorAll('#panel-context details').forEach(d => d.open = true); 1`); await sleep(2500);
await shot('context', [
  [1, '#rad-summary'], [2, '#sep-btn'], [3, '#wx-sol'], [4, '#wx-chart'], [5, '#min-map'], [6, '#sources > summary'],
]);

writeFileSync(new URL('shots.json', OUT), JSON.stringify(shots, null, 1));
console.log('done');
ws.close();
