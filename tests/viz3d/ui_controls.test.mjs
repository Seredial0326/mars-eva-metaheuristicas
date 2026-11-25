// Controls of the 3D map (web/3d): the safety net of issue #124. Run from the repo root:
//   node --test tests/viz3d/
//
// Simplifying the interface must not drop a feature that works. For each of the 31
// features of the 3D view (the list of #124, in its order), for the adaptive walkback
// that #160 added to the rehearsal (32), and for the "Panel" and "More" buttons that block 2
// of #124 put in the player (33), this reads the files and checks
// that the feature's control or way in is still there and still wired: the element ids of
// web/3d/index.html (buttons stay buttons, inputs stay inputs), the handlers behind them,
// the URL parameters, the ?check= modes and the keys. Layout and colours are not checked,
// and wording only where something depends on it: the card button labels that
// ?check=stations compares ("Done, continue", "View the rover photo") and the words
// "EVA clock" of the Sun note. A feature moved on purpose (a new id, another key) is
// updated here in the same PR.
import assert from 'node:assert/strict';
import { readdirSync, readFileSync } from 'node:fs';
import { test } from 'node:test';
import { runInNewContext } from 'node:vm';

import '../../web/terms.js';

import * as L from '../../web/3d/map_layers_model.js';
import * as W from '../../web/3d/walk_model.js';

const read = path => readFileSync(new URL(path, import.meta.url), 'utf8').replace(/\r\n/g, '\n');
// Without comments, so that a comment naming a control cannot pass for it. (No string of
// these files holds "/*", or "//" after a space.)
const code = path => read(path).replace(/\/\*[\s\S]*?\*\//g, '').replace(/(^|\s)\/\/.*$/gm, '$1');
const PAGE = read('../../web/3d/index.html').replace(/<!--[\s\S]*?-->/g, '');
const JS = Object.fromEntries(readdirSync(new URL('../../web/3d/', import.meta.url)).filter(f => f.endsWith('.js'))
  .map(f => [f.slice(0, -3), code(`../../web/3d/${f}`)]));
const GUIDE = code('../../web/guide_core.js');
const literal = text => text.replace(/[.*+?^${}()|[\]\\]/g, '\\$&');

// ---- the page ------------------------------------------------------------------------

// Start tags with their attributes; values in double quotes, single quotes or bare.
const TAG = /<([a-zA-Z][\w-]*)((?:\s+[\w:-]+(?:\s*=\s*(?:"[^"]*"|'[^']*'|[^\s"'=<>`]+))?)*)\s*\/?>/g;
const ATTR = /([\w:-]+)(?:\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+)))?/g;
const tags = html => [...html.matchAll(TAG)].map(m => ({
  tag: m[1].toLowerCase(), end: m.index + m[0].length,
  attrs: Object.fromEntries([...m[2].matchAll(ATTR)].map(([, k, ...v]) => [k.toLowerCase(), v.find(x => x !== undefined) ?? ''])),
}));
const TAGS = tags(PAGE);
const PAGE_IDS = TAGS.filter(t => t.attrs.id !== undefined).map(t => t.attrs.id);
const ELEMENTS = new Map(TAGS.filter(t => t.attrs.id !== undefined).map(t => [t.attrs.id, t]));
// What is inside the element with this id, up to its own closing tag.
function inner(id) {
  const el = ELEMENTS.get(id);
  if (!el) return '';
  const re = new RegExp(`${TAG.source}|</(${el.tag})\\s*>`, 'gi');
  re.lastIndex = el.end;
  for (let depth = 1, m; (m = re.exec(PAGE));) {
    if (m[3]) depth--; else if (m[1].toLowerCase() === el.tag) depth++;
    if (!depth) return PAGE.slice(el.end, m.index);
  }
  return PAGE.slice(el.end);
}
// Elements that the code makes (they are not in index.html), by the module that makes them.
const BUILT = {'message-close': 'main', 'photo-overlay': 'photos', 'photo-bar': 'photos', 'photo-opacity': 'photos',
               'photo-prev': 'photos', 'photo-next': 'photos', 'photo-realign': 'photos', 'photo-exit': 'photos'};

// The element with this id; one of `kinds` when given.
function element(id, kinds = null) {
  const el = ELEMENTS.get(id);
  assert.ok(el, `web/3d/index.html has no element with id="${id}"`);
  if (kinds) assert.ok(kinds.includes(el.tag), `#${id} is a <${el.tag}>, no longer a <${kinds.join('> or <')}>`);
  return el;
}
const present = (...ids) => ids.forEach(id => element(id));
const buttons = (...ids) => ids.forEach(id => element(id, ['button']));
// Inputs stay usable from the keyboard: an input, a select or a button, never a plain box.
const inputs = (...ids) => ids.forEach(id => element(id, ['input', 'select', 'textarea', 'button']));

// ---- the code ------------------------------------------------------------------------

// The module web/3d/<file>.js has code that matches re.
function inCode(file, re, what) {
  assert.ok(file in JS, `web/3d/${file}.js is gone`);
  assert.match(JS[file], re, `web/3d/${file}.js: ${what}`);
}
// main.js reads ?name= (and compares it with `value` in the same statement, when given).
const param = (name, value) => inCode('main',
  new RegExp(`params\\.get\\(\\s*['"]${name}['"]\\s*\\)${value === undefined ? '' : `[^;]*['"]${value}['"]`}`),
  `?${name}=${value ?? ''} is no longer read`);
// Index just past the bracket that closes the one at src[open]; strings are skipped.
function closing(src, open) {
  const pairs = {'(': ')', '[': ']', '{': '}'}, wanted = [];
  for (let i = open; i < src.length; i++) {
    const c = src[i];
    if (c === '"' || c === "'" || c === '`') {
      while (++i < src.length && src[i] !== c && (c === '`' || src[i] !== '\n')) if (src[i] === '\\') i++;
    } else if (pairs[c]) {
      wanted.push(pairs[c]);
    } else if (c === wanted[wanted.length - 1]) {
      wanted.pop();
      if (!wanted.length) return i + 1;
    }
  }
  return src.length;
}
// Each `<target>.addEventListener(...)` of a module: the event type and the text of the call.
function listeners(file, target) {
  const src = JS[file];
  return [...src.matchAll(new RegExp(`${target}\\.addEventListener\\(`, 'g'))].map(m => {
    const text = src.slice(m.index + m[0].length - 1, closing(src, m.index + m[0].length - 1));
    return {file, type: /^\(\s*['"]([\w-]+)['"]/.exec(text)?.[1], text};
  });
}
// The text of a function or method of a module, by name ('' when it has none).
function bodyOf(file, name) {
  const src = JS[file];
  for (const m of src.matchAll(new RegExp(`(?:\\bfunction\\s+|^[ \\t]+(?:async\\s+)?)${literal(name)}\\s*\\(`, 'gm'))) {
    const after = closing(src, m.index + m[0].length - 1), brace = /^\s*\{/.exec(src.slice(after));
    if (brace) return src.slice(after + brace[0].length - 1, closing(src, after + brace[0].length - 1));
  }
  return '';
}
const KEYWORDS = new Set(['if', 'for', 'while', 'switch', 'catch', 'function', 'return', 'typeof', 'await', 'new']);
// Does this code of a module call fn (a pattern, as 'hideMessage' or 'this\\.enter'), or pass
// it as the handler, itself or in a function or method of the module that it calls?
function calls(file, text, fn) {
  const re = new RegExp(`(?<![\\w$])${fn}\\(|[(,]\\s*${fn}\\s*[,)]`);
  if (re.test(text)) return true;
  const names = new Set([...text.matchAll(/(?<![\w$])([\w$]+)\(/g)].map(m => m[1]).filter(n => !KEYWORDS.has(n)));
  return [...names].some(name => re.test(bodyOf(file, name)));
}
// The listeners of #id in the modules but the checks: looked up by id, or through a const.
function listenersOf(id) {
  const find = `\\b(?:el|ui|getElementById)\\(\\s*['"]${id}['"]\\s*\\)`;
  return Object.keys(JS).filter(file => file !== 'checks').flatMap(file => {
    // const pick = el('layer-pick');
    const held = new RegExp(`\\b(?:const|let)\\s+([\\w$]+)\\s*=\\s*${find}\\s*[;,]`).exec(JS[file]);
    return [...listeners(file, find), ...(held ? listeners(file, `\\b${literal(held[1])}`) : [])];
  });
}
// Something listens to `type` on #id; with fn, its handler calls fn (as calls() says).
function wired(id, type, fn = null) {
  const found = listenersOf(id).filter(l => l.type === type);
  assert.ok(found.length, `nothing listens to "${type}" on #${id} any more`);
  if (fn) {
    assert.ok(found.some(l => calls(l.file, l.text, fn)),
              `#${id}: its "${type}" handler no longer calls ${fn.replace(/\\/g, '')}()`);
  }
}
// A card button (card.js makes one for each {label, onClick}) whose onClick calls fn first.
const cardAction = (file, fn, what) => inCode(file, new RegExp(
  `\\blabel:\\s*(?:'[^']*'|"[^"]*")\\s*,\\s*onClick:\\s*(?:\\([^)]*\\)|[\\w$]+)\\s*=>\\s*\\{?\\s*${fn}\\(`), what);
// Every label that checks.js compares (?check=stations) is the label of a card button in a module.
function sameLabels() {
  const wanted = [...JS.checks.matchAll(/\.includes\(\s*'([^']+)'\s*\)|textContent === '([^']+)'/g)].map(m => m[1] ?? m[2]);
  assert.ok(wanted.length >= 2, 'web/3d/checks.js no longer compares the card labels');
  for (const label of wanted) {
    const button = new RegExp(`\\blabel:\\s*['"]${literal(label)}['"]\\s*,\\s*onClick:`);
    assert.ok(Object.entries(JS).some(([file, src]) => file !== 'checks' && button.test(src)),
              `?check=stations looks for "${label}", which no card button says any more`);
  }
}
// The module that makes this element still gives it its id.
const built = id => inCode(BUILT[id], new RegExp(`(?:\\.id\\s*=\\s*|\\bid:\\s*)['"]${id}['"]|\\bid=["']${id}["']`),
                           `#${id} is no longer made`);
// The methods of a module's classes (two-space indent, as in web/3d), as text.
const methods = file => JS[file].split(/\n(?= {2}(?:async )?[\w$]+\([^)]*\) \{[ \t]*\n)/);
const methodWith = (file, re) => methods(file).find(m => re.test(m)) ?? '';

test('the page: every id is read here, used once, and not made again by the code', () => {
  const raw = [...PAGE.matchAll(/\sid\s*=\s*(?:"([^"]*)"|'([^']*)'|([^\s"'=<>`]+))/g)].map(m => m[1] ?? m[2] ?? m[3]);
  assert.deepEqual(PAGE_IDS, raw, 'an element of web/3d/index.html was not read');
  const twice = PAGE_IDS.filter((id, i) => PAGE_IDS.indexOf(id) !== i);
  assert.deepEqual(twice, [], `ids used twice in web/3d/index.html: ${twice.join(' ')}`);
  for (const id of Object.keys(BUILT)) assert.ok(!ELEMENTS.has(id), `#${id} is in the page and made by ${BUILT[id]}.js too`);
});

test('1. free flight: drag, right-drag or Shift + drag, wheel and touch; ?drag=pan', () => {
  element('view', ['canvas']);
  inCode('main', /new TerrainControls\(\s*camera,\s*canvas\b/, 'the free-flight controls are no longer on the view');
  param('drag', 'pan');
  for (const type of ['pointerdown', 'pointermove', 'wheel']) {
    inCode('controls', new RegExp(`\\.addEventListener\\(\\s*'${type}'`), `nothing handles "${type}" any more`);
  }
  inCode('controls', /e\.button === 2/, 'the right button no longer moves the map');
  inCode('controls', /e\.shiftKey/, 'Shift + drag no longer moves the map');
  inCode('controls', /type:\s*'two'/, 'two fingers no longer move, pinch and twist');
  // The page can be zoomed on a phone (#124: WCAG 1.4.4), but not from the view: a pinch
  // there is the camera's zoom, so the view keeps every touch for itself.
  const viewport = TAGS.find(t => t.tag === 'meta' && t.attrs.name === 'viewport');
  assert.ok(viewport, 'web/3d/index.html has no viewport meta');
  const vp = Object.fromEntries((viewport.attrs.content ?? '').split(',').map(p => p.split('=').map(s => s.trim().toLowerCase())));
  assert.ok(!(Number(vp['maximum-scale']) < 2) && !['no', '0'].includes(vp['user-scalable']),
            `the viewport stops zooming the page again: "${viewport.attrs.content}"`);
  assert.match(PAGE, /#view\s*\{[^}]*\btouch-action:\s*none\b/, 'a pinch on the view would zoom the page: #view lost touch-action: none');
});

test('2. compass (face north) and home (reset the view)', () => {
  // Buttons, so the keyboard reaches them (#124 c); both are a picture alone, so each has a name.
  buttons('compass', 'home');
  present('compass-needle');
  for (const id of ['compass', 'home']) assert.ok(element(id).attrs['aria-label'], `#${id} has no aria-label`);
  wired('compass', 'click', 'faceNorth');
  wired('home', 'click', 'controls\\.home');
});

test('3. readout of position, height and speed; ?fps=1', () => {
  present('readout');
  param('fps', '1');
});

test('4. relief x1 to x5: the slider and ?k=', () => {
  inputs('relief');
  present('relief-label');
  wired('relief', 'input');
  param('k');
});

test('5. quality and debugging: ?q=, ?light=, ?spin=1', () => {
  param('q');
  param('light');
  param('spin', '1');
  present('quality-label');
});

test('6. view link: ?view= and "Copy link to this view"', () => {
  param('view');
  buttons('copy-view');
  inputs('view-link');
  present('share-note');
  wired('copy-view', 'click');
});

test('7. Save image', () => {
  buttons('save-image');
  wired('save-image', 'click');
});

test('8. last plan, Reload plan and the default plan; ?plan=default', () => {
  buttons('plan-reload', 'plan-default');
  present('plan-default-box', 'plan-source');
  wired('plan-reload', 'click');
  wired('plan-default', 'click');
  param('plan', 'default');
  inCode('main', /\bloadLastPlan\(/, 'the last plan is no longer loaded');
  inCode('main', /\brequestDefaultPlan\(/, 'the default plan can no longer be asked for');
});

test('9. link back to the 2D planner', () => {
  assert.ok(TAGS.some(t => t.tag === 'a' && ['/', '../', '/index.html'].includes(t.attrs.href)),
            'web/3d/index.html has no link to the 2D planner (href "/", "../" or "/index.html")');
});

test('10. route on the relief', () => {
  inCode('main', /new RouteOverlay\(/, 'the route is no longer drawn');
  inCode('main', /\boverlays\.setPlan\(/, 'the plan no longer reaches the route');
});

test('11. pins, their card and "Fly here"', () => {
  element('card');
  // A click (pointerup) on the view picks the pin under it and selects it; the pin's card follows.
  const up = listeners('main', `\\b(?:canvas|ui\\(\\s*['"]view['"]\\s*\\))`).filter(l => l.type === 'pointerup');
  assert.ok(up.some(l => calls('main', l.text, 'markers\\.pick') && calls('main', l.text, 'markers\\.select')),
            'web/3d/main.js: a click on the view no longer picks and selects a pin');
  inCode('main', /\bmarkers\.onSelect\s*=/, 'a selected pin no longer shows its card');
  cardAction('main', 'flyToMarker', 'a pin card no longer flies there');
  // The parts of the card that the checks read, its buttons and its close cross.
  for (const cls of ['card-title', 'card-media']) inCode('card', new RegExp(`'${cls}'`), `the card has no .${cls}`);
  inCode('card', /'button',\s*'card-action'/, 'the card actions are no longer buttons');
  inCode('card', /'button',\s*'card-close'/, 'the card can no longer be closed');
});

test('12. Sun: sol, local solar time and sky; ?sol= and ?lt=', () => {
  inputs('sun-sol', 'sun-time');
  present('sun-time-text', 'sun-readout');
  wired('sun-sol', 'change');
  wired('sun-time', 'input');
  param('sol');
  param('lt');
});

test('13. the Sun follows the EVA clock while rehearsing', () => {
  present('sun-note');
  inCode('rehearse', /\bthis\.onTime\((?!\s*null\b)/, 'the rehearsal no longer gives its EVA clock');
  inCode('main', /\bonTime:[^;]*\bsunView\.follow\(/, 'the EVA clock no longer moves the Sun');
  // The note may move to the player and change its words (#124, block 2): any module but the checks.
  assert.ok(Object.entries(JS).some(([file, src]) => file !== 'checks' && /[`'"][^`'"]*EVA clock/.test(src)),
            'no module says "EVA clock" any more');
  // The panel is hidden while rehearsing (#124, block 2): the player repeats its Sun line.
  present('rh-sun');
  assert.ok(inner('player').includes('id="rh-sun"'), '#rh-sun is no longer in the player');
  inCode('rehearse', /['"]rh-sun['"]/, 'the player no longer shows the Sun line');
  inCode('rehearse', /['"]sun-note['"]/, 'the player no longer repeats the Sun note ("Following the EVA clock")');
});

test('14. Relief only and Shadows; ?shadows=0', () => {
  inputs('relief-only', 'shadows');
  wired('relief-only', 'change');
  wired('shadows', 'change');
  param('shadows', '0');
});

test('15. map layer of the 2D planner (six), its opacity and legend', () => {
  inputs('layer-pick', 'layer-opacity');
  present('layer-legend', 'layer-note');
  assert.ok(tags(inner('layer-pick')).some(t => t.tag === 'option' && t.attrs.value === ''),
            '#layer-pick has no "off" option (value="")');
  wired('layer-pick', 'change');
  wired('layer-opacity', 'input');
  for (const id of ['radio', 'slope', 'steep', 'sand', 'cost', 'rocks']) {
    assert.ok((L.LAYERS ?? []).some(l => l.id === id), `web/3d/map_layers_model.js has no "${id}" layer`);
  }
  inCode('map_layers', /\bof LAYERS\b|\bLAYERS\.(?:forEach|map)\(/, 'the layers are no longer offered in #layer-pick');
  inCode('main', /import\(\s*'\.\/map_layers\.js'\s*\)/, 'the map layers are no longer loaded');
});

test('16. rover photo stops: pins and cards', () => {
  inputs('photos-show');
  present('photos-note');
  wired('photos-show', 'change');
  // Off when the page opens (#124: 100 pins covered the route). Opening a photo turns them on,
  // so they are there after the photo view: ?photo=, a stop's card and a station's card all go
  // through enter(), and main.js ticks the box when it does.
  assert.equal(element('photos-show').attrs.checked, undefined, '#photos-show starts ticked again');
  const enter = bodyOf('photos', 'enter');
  const reached = [enter, ...[...enter.matchAll(/\bthis\.([\w$]+)\(/g)].map(m => bodyOf('photos', m[1]))];
  assert.ok(reached.some(text => /\bthis\.visible\s*=\s*true\b/.test(text) && /\bthis\.onShowPins\(/.test(text)),
            'web/3d/photos.js: opening a photo no longer turns the photo stops on');
  inCode('main', /\bonShowPins:[^;]*\bui\(\s*'photos-show'\s*\)\.checked\s*=\s*true\b/,
         'a photo view that turns the stops on no longer ticks "Show photo stops"');
  inCode('main', /import\(\s*'\.\/photos\.js'\s*\)/, 'the rover photos are no longer loaded');
  inCode('main', /\bphotoMarkers\.pickAll\(/, 'a click no longer picks a photo stop');
  inCode('main', /\bphotos\.openGroup\(/, 'a photo stop no longer opens its card');
  inCode('main', /\bphotos\.chooseStop\(/, 'stops on top of each other can no longer be chosen');
});

test('17. photo view: fade, Previous / Next, Realign, Exit and Esc', () => {
  cardAction('photos', 'this\\.enter', 'a photo stop card no longer opens the photo view');
  for (const id of ['photo-overlay', 'photo-bar', 'photo-opacity', 'photo-prev', 'photo-next', 'photo-realign',
                    'photo-exit']) built(id);
  inCode('photos', /\bmake\('button'/, 'the photo bar has no buttons any more');
  inCode('photos', /'keydown'/, 'the photo view no longer listens to the keys');
  assert.match(methodWith('photos', /'Escape'/), /\bthis\.exit\(\)/, 'web/3d/photos.js: Esc no longer leaves the photo view');
});

test('18. photo by link: ?photo= (the "Open in 3D" of the HUD)', () => {
  param('photo');
  inCode('main', /\bparsePhotoParam\(/, '?photo= is no longer read as a photo id');
  inCode('main', /\bphotos\.enter\(/, '?photo= no longer opens the photo view');
});

test('19. nearest rover photo on a station card', () => {
  inCode('main', /\bphotos\.stationPreview\(/, 'a station card no longer shows its nearest photo');
  inCode('rehearse', /\bthis\.stationMedia\(/, 'a stop card of the rehearsal no longer shows its nearest photo');
  assert.ok(calls('photos', bodyOf('photos', 'stationPreview'), 'this\\.enter'),
            'web/3d/photos.js: the nearest photo can no longer be opened from the card');
  sameLabels();
});

// Use the page's local import map in Node; no server or installed dependencies.
async function rehearsalModule() {
  const {registerHooks} = await import('node:module');
  const hook = registerHooks({resolve(specifier, context, next) {
    return next(specifier === 'three'
      ? new URL('../../web/3d/vendor/three/build/three.module.js', import.meta.url).href : specifier, context);
  }});
  try { return await import('../../web/3d/rehearse.js'); }
  finally { hook.deregister(); }
}

test('20. enter and leave the rehearsal with focus; disclosures and Tab order', async t => {
  buttons('rehearse', 'rh-exit');
  present('player', 'rehearse-note');
  wired('rehearse', 'click');
  wired('rh-exit', 'click');
  // Esc closes what is on top and pauses, but never leaves: leaving loses the end summary (#124 c).
  const esc = methodWith('rehearse', /'Escape'/);
  assert.match(esc, /\bthis\.pause\(/, 'web/3d/rehearse.js: Esc no longer pauses the rehearsal');
  assert.doesNotMatch(esc, /\bthis\.exit\(/, 'web/3d/rehearse.js: Esc leaves the rehearsal, and loses the end summary');

  // DOM order is the visible order, without positive tabindex or CSS reordering.
  const player = tags(inner('player'));
  assert.deepEqual(player.filter(t => ['button', 'input', 'select'].includes(t.tag)).map(t => t.attrs.id),
    ['rh-play', 'rh-home', 'rh-detour', 'rh-storm', 'rh-summary', 'rh-more', 'rh-panel', 'rh-exit',
     'rh-chase', 'rh-recentre', 'rh-speed', 'rh-voice', 'rh-ktrue', 'rh-scrub']);
  assert.ok(element('rh-man').end < element('rh-main').end);
  assert.ok(player.every(t => !(Number(t.attrs.tabindex) > 0)), 'the player overrides the normal Tab order');
  const playerCSS = PAGE.slice(PAGE.indexOf('  #player {'), PAGE.indexOf('  /* Solar storm'));
  assert.doesNotMatch(playerCSS, /(?:^|[;{])\s*order\s*:|(?:row|column)-reverse/);
  assert.match(playerCSS, /#player :focus-visible[^{}]*\{[^}]*outline:\s*2px solid/);
  assert.match(playerCSS, /#rh-play:focus[^{}]*\{[^}]*outline:/, 'entry focus needs a ring even after a click');
  assert.match(playerCSS, /#rehearse:focus-visible[^{}]*\{[^}]*outline:/);

  const {Rehearsal} = await rehearsalModule();
  // Only rendering and route setup are stubbed; enter, exit, click handlers and focus run.
  const classList = () => {
    const values = new Set();
    return {add: (...names) => names.forEach(n => values.add(n)),
            remove: (...names) => names.forEach(n => values.delete(n)),
            toggle: (name, on) => on ? values.add(name) : values.delete(name),
            contains: name => values.has(name)};
  };
  const nodes = new Map(PAGE_IDS.map(id => [id, Object.assign(new EventTarget(), {
    id, tagName: ELEMENTS.get(id).tag.toUpperCase(), hidden: 'hidden' in ELEMENTS.get(id).attrs,
    classList: classList(), attrs: {...ELEMENTS.get(id).attrs},
    setAttribute(name, value) { this.attrs[name] = value; },
    getAttribute(name) { return this.attrs[name] ?? null; },
    focus() {
      assert.ok(!this.hidden, `focused hidden #${id}`);
      if (id.startsWith('rh-')) assert.ok(!nodes.get('player').hidden, 'focused the hidden player');
      if (id === 'rehearse') {
        assert.ok(!document.body.classList.contains('rh-panel-hidden'), 'focused the hidden panel');
        assert.ok(nodes.get('plan-box').open, 'focused Rehearse inside the folded Plan section');
      }
      document.activeElement = this;
    },
    click() { this.dispatchEvent(new Event('click')); },
  })]));
  const saved = {document: globalThis.document, window: globalThis.window};
  t.after(() => {
    for (const [name, value] of Object.entries(saved)) {
      if (value === undefined) delete globalThis[name]; else globalThis[name] = value;
    }
  });
  globalThis.document = {getElementById: id => nodes.get(id), activeElement: null,
                         body: {classList: classList(), style: {removeProperty() {}}}};
  globalThis.window = new EventTarget();
  const rehearsal = new Rehearsal({terrain: {k: 1}, scene: {add() {}},
    camera: {near: 2, updateProjectionMatrix() {}}, canvas: new EventTarget(),
    controls: {pose: () => ({}), cancel() {}, restore() {}}, relief: {lock() {}, unlock() {}}});
  rehearsal._restart = rehearsal._place = rehearsal._clearWalkback = () => {};
  nodes.get('plan-box').open = true;
  nodes.get('rehearse').focus();
  assert.equal(rehearsal.enter(), false, 'no route must not move focus');
  assert.equal(document.activeElement.id, 'rehearse');
  rehearsal.model = {};
  for (let entry = 0; entry < 2; entry++) {
    nodes.get('rehearse').click();
    assert.equal(rehearsal.active, true);
    assert.equal(document.activeElement.id, 'rh-play');
    assert.equal(rehearsal.playing, false);
    assert.equal(rehearsal.enter(), false, 'entering twice must not steal focus');
    for (const [toggle, content, inside] of [['rh-more', 'rh-more-box', 'rh-speed'], ['rh-panel', 'info', 'plan-reload']]) {
      nodes.get(toggle).click();
      assert.equal(nodes.get(toggle).attrs['aria-expanded'], 'true');
      assert.equal(document.activeElement.id, toggle);
      if (content === 'info') assert.equal(document.body.classList.contains('rh-panel-hidden'), false);
      else assert.equal(nodes.get(content).hidden, false);
      nodes.get(inside).focus();
      nodes.get(toggle).click();
      assert.equal(nodes.get(toggle).attrs['aria-expanded'], 'false');
      assert.equal(document.activeElement.id, toggle, 'closing returns focus from the hidden contents');
      if (content === 'info') assert.equal(document.body.classList.contains('rh-panel-hidden'), true);
      else assert.equal(nodes.get(content).hidden, true);
    }
    nodes.get('plan-box').open = false;
    nodes.get('rh-exit').click();
    assert.equal(rehearsal.active, false);
    assert.equal(nodes.get('player').hidden, true);
    assert.equal(document.activeElement.id, 'rehearse');
    assert.equal(rehearsal._listeners.length, 0);
  }
});

test('21. player: Space respects focused controls; play / pause, speed and position bar', async () => {
  buttons('rh-play');
  inputs('rh-speed', 'rh-scrub');
  present('rh-progress');
  wired('rh-play', 'click');
  wired('rh-speed', 'change');
  wired('rh-scrub', 'input');
  // Outside a control, Space does what the Play button does, whatever that method is called.
  const play = listenersOf('rh-play').filter(l => l.type === 'click').map(l => /\bthis\.([\w$]+)\(/.exec(l.text)?.[1])
    .find(Boolean);
  inCode('rehearse', /'keydown'/, 'the rehearsal no longer listens to the keys');
  assert.ok(play && new RegExp(`\\bthis\\.${literal(play)}\\(`).test(methodWith('rehearse', /'Space'/)),
            'web/3d/rehearse.js: Space no longer does what Play does');

  const {Rehearsal, spaceBelongsTo} = await rehearsalModule();
  const node = (tagName, role = null, parentElement = null, isContentEditable = false) =>
    ({tagName, parentElement, isContentEditable, getAttribute: name => name === 'role' ? role : null,
      blur() { assert.fail('Space must not blur a focused control'); }});
  const owned = [
    ...['BUTTON', 'A', 'INPUT', 'SELECT', 'TEXTAREA', 'SUMMARY'].flatMap(tag => {
      const control = node(tag);
      return [control, node('SPAN', null, control)];
    }),
    ...['button', 'link', 'checkbox', 'slider', 'switch checkbox'].flatMap(role => {
      const control = node('DIV', role);
      return [control, node('svg', null, control)];
    }),
    node('button'), node('DIV', null, null, true), node('SPAN', null, node('DIV', null, null, true)),
  ];
  const unowned = [null, undefined, {}, node('BODY'), node('CANVAS'), node('DIV', 'meter'),
                   node('SPAN', null, node('DIV')), node('DIV', 'mybutton')];
  const rehearsal = {playing: false, togglePlay() { this.playing = !this.playing; }};
  const press = (target, extra = {}) => {
    const event = {target, code: 'Space', repeat: false, defaultPrevented: false,
                   preventDefault() { this.defaultPrevented = true; }, ...extra};
    Rehearsal.prototype._key.call(rehearsal, event);
    return event;
  };
  for (const target of owned) {
    assert.equal(spaceBelongsTo(target), true, `Space belongs to ${target.tagName}`);
    for (const playing of [false, true]) {
      rehearsal.playing = playing;
      assert.equal(press(target).defaultPrevented, false, 'keep the native Space action');
      assert.equal(rehearsal.playing, playing, 'focused controls must not toggle playback');
    }
  }
  for (const target of unowned) {
    assert.equal(spaceBelongsTo(target), false);
    rehearsal.playing = false;
    assert.equal(press(target).defaultPrevented, true, 'Space outside controls must not scroll');
    assert.equal(rehearsal.playing, true);
    press(target);
    assert.equal(rehearsal.playing, false);
  }
  for (const extra of [{repeat: true}, {defaultPrevented: true}, {code: 'Enter'}]) {
    const event = press(node('BODY'), extra);
    assert.equal(event.defaultPrevented, Boolean(extra.defaultPrevented));
    assert.equal(rehearsal.playing, false, 'ignore repeated, handled or unrelated keys');
  }
});

test('22. chase view, looking around and Recentre (also double-click)', () => {
  buttons('rh-chase', 'rh-recentre');
  wired('rh-chase', 'click');
  wired('rh-recentre', 'click');
  inCode('rehearse', /'pointermove'/, 'dragging no longer looks around');
  inCode('rehearse', /'dblclick'[^;]*\brecentre\(\)/, 'a double-click no longer looks forward again');
});

test('23. stops: card, tasks and "Done, continue"', () => {
  element('card');
  inCode('rehearse', /\bG\.stationCard\(/, 'a stop card no longer lists the tasks');
  sameLabels();
});

test('24. energy bar and walkback lines on pause', () => {
  present('rh-energy', 'rh-bar-used', 'rh-bar-rv', 'rh-bar-free', 'rh-energy-text');
  inCode('rehearse', /\brequestWalkback\(/, 'a pause no longer asks for the walkback lines');
});

test('25. guide: next maneuver, meters and radio', () => {
  // The banner and the values of the meters; ?check=guide reads all but the radio.
  present('rh-man', 'rh-man-arrow', 'rh-man-text', 'rh-man-dist', 'rh-meters', 'rh-v-energy', 'rh-v-back',
          'rh-eva-track', 'rh-v-eva', 'rh-v-radio');
});

test('26. voice on / off', () => {
  buttons('rh-voice');
  wired('rh-voice', 'click');
});

test('27. Return home, Detour and Solar storm', () => {
  buttons('rh-home', 'rh-detour', 'rh-storm');
  present('rh-alert', 'rh-note');
  for (const id of ['rh-home', 'rh-detour', 'rh-storm']) wired(id, 'click');
  // The storm also shows beyond the player (#124 b): a band on top and a vignette, page
  // elements that the rehearsal shows and hides. Nothing goes into the 3D scene for it
  // (sun.js repaints the sky, ?check=rehearse compares the scene): only the walker does.
  present('rh-storm-band', 'rh-tint');
  inCode('rehearse', /['"]rh-storm-band['"]/, 'the storm band is no longer shown');
  inCode('rehearse', /['"]rh-tint['"]/, 'the storm vignette is no longer shown');
  assert.equal((JS.rehearse.match(/\bscene\.add\(/g) || []).length, 1,
               'web/3d/rehearse.js adds something besides the walker to the 3D scene');
});

test('28. end summary card and the walk log (POST /walks)', () => {
  // The method that sums up the walk, whatever its name: something calls it, and it shows a card.
  const end = methodWith('rehearse', /\bG\.walkSummary\(/), name = /^ {2}(?:async )?([\w$]+)\(/.exec(end)?.[1];
  assert.ok(name && new RegExp(`\\bthis\\.${literal(name)}\\(`).test(JS.rehearse),
            'web/3d/rehearse.js: arriving no longer sums up the walk');
  assert.match(end, /\bshowCard\(/, 'web/3d/rehearse.js: the end summary is no longer a card');
  inCode('rehearse', /\bG\.postWalk\(/, 'the walk is no longer kept for the debrief');
  assert.match(GUIDE, /fetch\(\s*["']\/walks["']\s*,\s*\{\s*method:\s*["']POST["']/,
               'web/guide_core.js no longer posts the walk to /walks');
  // At the habitat the rehearsal stays on (#124, row 20): leaving would lose the summary,
  // the replay and the Sun of the end. The end card offers "Replay" and "Exit".
  const arrive = methodWith('rehearse', /You have arrived at the habitat/);
  assert.ok(arrive, 'web/3d/rehearse.js no longer says the walker has arrived');
  assert.doesNotMatch(arrive, /\bthis\.exit\(/, 'web/3d/rehearse.js: arriving at the habitat leaves the rehearsal');
  cardAction('rehearse', 'this\\.replay', 'the end card no longer offers "Replay"');
  cardAction('rehearse', 'this\\.exit', 'the end card no longer offers "Exit"');
});

test('29. replay from the end', () => {
  // In play() or in a method of its own: back to the start, then playing.
  assert.ok(methods('rehearse').some(m => /\bthis\.seek\(this\.model\.start\)/.test(m) &&
                                          /\bthis\.play\(\)|\bthis\.playing\s*=\s*true\b/.test(m)),
            'web/3d/rehearse.js: nothing plays again from the start any more');
});

test('30. Walk freely: W A S D or arrows, Shift, F, C, Esc and the touch pad', () => {
  buttons('walk', 'wk-run', 'wk-fast', 'wk-chase', 'wk-exit');
  present('walk-bar', 'wk-keys', 'wk-hint');
  for (const id of ['walk', 'wk-run', 'wk-fast', 'wk-chase', 'wk-exit']) wired(id, 'click');
  // Keys by KeyboardEvent.code. A and D step sideways; Left and Right turn the walker.
  const moves = {forward: ['KeyW', 'ArrowUp'], back: ['KeyS', 'ArrowDown'], left: ['KeyA'], right: ['KeyD']};
  for (const [way, codes] of Object.entries(moves)) {
    for (const c of codes) assert.ok(W.KEYS?.[way]?.includes(c), `web/3d/walk_model.js: ${c} no longer moves ${way}`);
  }
  for (const [way, code] of [['turnLeft', 'ArrowLeft'], ['turnRight', 'ArrowRight']]) {
    assert.deepEqual(W.KEYS?.[way], [code], `web/3d/walk_model.js: ${code} must turn, without A/D`);
    assert.deepEqual(W.moveAxes([code]), {forward: 0, right: 0}, `${code} must not strafe`);
  }
  assert.deepEqual(W.moveAxes(['KeyA']), {forward: 0, right: -1}, 'A must strafe left');
  assert.deepEqual(W.moveAxes(['KeyD']), {forward: 0, right: 1}, 'D must strafe right');
  inCode('walk', /\bW\.KEYS\b/, 'the walk no longer moves with the keys of walk_model.js');
  inCode('walk', /'keydown'/, 'the walk no longer listens to the keys');
  inCode('walk', /\bshiftKey\b|'Shift(?:Left|Right)'/, 'Shift no longer runs');
  inCode('walk', /'KeyF'/, 'F no longer switches fast travel');
  inCode('walk', /'KeyC'/, 'C no longer switches the chase view');
  assert.match(methodWith('walk', /'Escape'/), /\bthis\.exit\(\)/, 'web/3d/walk.js: Esc no longer leaves the walk');
  // The arrow pad of touch screens (its buttons may sit in rows): walk.js wires them and
  // ?check=walk presses one.
  element('walk-pad');
  const pad = tags(inner('walk-pad'));
  for (const way of ['forward', 'back', 'left', 'right']) {
    assert.ok(pad.some(t => t.tag === 'button' && t.attrs['data-walk'] === way), `#walk-pad has no "${way}" button`);
  }
  inCode('walk', /#walk-pad \[data-walk\]/, 'the pad buttons are no longer wired');
});

test('31. messages and the ten ?check= modes', () => {
  present('message');
  built('message-close');
  wired('message-close', 'click', 'hideMessage');
  // Esc closes the message: a key handler that sees Escape and hides it, itself or through a function.
  const keys = listeners('main', '\\b(?:window|document)').filter(l => l.type === 'keydown' && /['"]Escape['"]/.test(l.text));
  assert.ok(keys.some(l => calls('main', l.text, 'hideMessage')), 'web/3d/main.js: Esc no longer closes the message');
  param('check');
  inCode('main', /import\(\s*'\.\/checks\.js'\s*\)/, 'the checks are no longer loaded');
  inCode('main', /\bCHECKS\[check\]/, 'the check named in the address is no longer run');
  const table = /export const CHECKS = \{([^}]*)\}/.exec(JS.checks);
  assert.ok(table, 'web/3d/checks.js has no CHECKS table');
  const modes = Object.fromEntries([...table[1].matchAll(/(\w+):\s*(\w+)/g)].map(([, name, fn]) => [name, fn]));
  for (const name of ['shading', 'route', 'rehearse', 'sun', 'shadows', 'guide', 'photos', 'stations', 'walk', 'layers']) {
    assert.ok(modes[name], `?check=${name} is gone`);
    inCode('checks', new RegExp(`\\bfunction ${modes[name]}\\(`), `?check=${name} runs ${modes[name]}(), which is gone`);
  }
});

test('32. adaptive walkback (#160): the ×k demo button, the meter at your pace, RETURN NOW, the summary rows', () => {
  // The demo button cycles the simulated energy use (k_true) through the choices of guide_core.
  buttons('rh-ktrue');
  const clicks = listenersOf('rh-ktrue').filter(l => l.type === 'click');
  assert.ok(clicks.length, 'nothing listens to "click" on #rh-ktrue any more');
  const cycles = l => [l.text, ...[...l.text.matchAll(/(?<![\w$])([\w$]+)\(/g)].map(m => bodyOf(l.file, m[1]))]
    .some(text => /\bG\.K_TRUE_CHOICES\b/.test(text));
  assert.ok(clicks.some(cycles), '#rh-ktrue: its click no longer cycles the demo choices of k (G.K_TRUE_CHOICES)');
  assert.match(GUIDE, /export const K_TRUE_CHOICES\s*=/, 'web/guide_core.js no longer offers the demo choices of k');
  // "Spare energy at your pace": hidden until the first answer of POST /walkback/update;
  // its state word apart from the value, as the other meters (#124, block 2).
  present('rh-k-label', 'rh-m-k', 'rh-v-k', 'rh-w-k');
  assert.equal(element('rh-k-track').attrs.role, 'meter', '#rh-k-track is no longer a meter');
  inCode('rehearse', /\bG\.adaptiveStep\(/, 'the rehearsal no longer learns k as it plays');
  // RETURN NOW comes from guide_core and shows in #rh-alert (the storm wins).
  inCode('rehearse', /\bG\.kAlarmMessage\(/, 'the rehearsal no longer raises RETURN NOW');
  // The adaptive rows of "Plan against the walk".
  inCode('rehearse', /\badaptiveCardRows\(/, 'the end summary no longer has the adaptive rows');
});

test('33. while rehearsing: "Panel" brings the side panel back, "More" holds the rest of the player (#124, block 2)', () => {
  buttons('rh-panel', 'rh-more');
  for (const id of ['rh-panel', 'rh-more']) assert.ok(inner('player').includes(`id="${id}"`), `#${id} is no longer in the player`);
  // A handler's text and the methods of the module that it calls.
  const reach = (file, text) => [text, ...[...text.matchAll(/(?<![\w$])(?:this\.)?([\w$]+)\(/g)]
    .map(m => bodyOf(file, m[1]))].join('\n');
  // "Panel": its click shows or hides #info through a class of the body of its own (the
  // photo view's, photo-view, also hides the map layer), and leaving takes the class away.
  const panel = listenersOf('rh-panel').filter(l => l.type === 'click').map(l => reach(l.file, l.text)).join('\n');
  const cls = /document\.body\.classList\.toggle\(\s*'([\w-]+)'/.exec(panel)?.[1];
  assert.ok(cls, '#rh-panel: its click no longer shows or hides the side panel (a class of the body)');
  assert.notEqual(cls, 'photo-view', "#rh-panel uses the photo view's class, which also hides the map layer");
  assert.match(PAGE, new RegExp(`body\\.${literal(cls)}\\s+#info\\s*\\{[^}]*display:\\s*none`),
               `web/3d/index.html: body.${cls} no longer hides #info`);
  assert.match(reach('rehearse', bodyOf('rehearse', 'exit')), new RegExp(`classList\\.(?:remove|toggle)\\([^)]*'${literal(cls)}'`),
               'web/3d/rehearse.js: leaving the rehearsal no longer brings the side panel back');
  // "More": a disclosure (aria-expanded, aria-controls) over the box of the other controls.
  const more = element('rh-more'), box = more.attrs['aria-controls'];
  assert.ok(more.attrs['aria-expanded'] !== undefined && box && ELEMENTS.has(box),
            '#rh-more no longer says what it opens (aria-expanded, aria-controls)');
  wired('rh-more', 'click');
  const under = tags(inner(box)).map(t => t.attrs.id).filter(Boolean);
  for (const id of ['rh-chase', 'rh-recentre', 'rh-speed', 'rh-voice', 'rh-ktrue']) {
    assert.ok(under.includes(id), `#${id} is no longer under "More"`);
  }
  // One row of main buttons, none of them folded; the ×k demo button no longer beside Return home.
  const main = tags(inner('rh-main')).map(t => t.attrs.id);
  for (const id of ['rh-play', 'rh-home', 'rh-detour', 'rh-storm']) {
    assert.ok(main.includes(id), `#${id} is no longer in the main row of the player`);
    assert.ok(!under.includes(id), `#${id} is folded under "More"`);
  }
  assert.ok(!main.includes('rh-ktrue'), 'the ×k demo button is back beside Return home');
});

test('34. keyboard station and photo lists: folded native buttons, names, cards and focus', () => {
  for (const [kind, section] of [['station', 'plan-box'], ['photo', 'photos-box']]) {
    const title = `${kind}-list-title`, note = `${kind}-list-note`;
    const group = element(`${kind}-controls`, ['fieldset']);
    element(`${kind}-list`, ['ul']);
    element(title, ['summary']);
    assert.equal(group.attrs['aria-labelledby'], title);
    assert.equal(group.attrs['aria-describedby'], note);
    assert.ok('disabled' in group.attrs, 'disabled until data arrives');
    assert.equal(element(note).attrs.role, 'status', 'mode reason is readable and announced');
    assert.ok(inner(section).includes(`id="${title}"`));
    const disclosure = new RegExp(`<details\\b([^>]*)>\\s*<summary\\b[^>]*id="${title}"`);
    assert.doesNotMatch(disclosure.exec(PAGE)?.[1] ?? 'missing open', /\bopen\b/, 'list starts folded');
  }
  const fill = bodyOf('main', 'fillStopList');
  assert.match(fill, /createElement\('button'\)/);
  assert.match(fill, /button\.type = 'button'/);
  assert.match(fill, /button\.textContent = entry\.label/);
  assert.match(fill, /setAttribute\('aria-describedby'/);
  assert.match(fill, /addEventListener\('click'/, 'native Enter and Space activation');
  assert.match(fill, /if \(busy\(\) \|\| photos\?\.active\) return/, 'activation checks the mode too');
  assert.match(fill, /close\?\.focus\(\)/, 'card actions follow activation');
  assert.match(fill, /button\.focus\(\)/, 'Close returns to the list');
  const stations = bodyOf('main', 'refreshStationList');
  assert.match(stations, /stationList\(/);
  assert.match(stations, /flyToMarker\(marker\)/);
  assert.match(stations, /markers\.select\(marker\)/);
  const photos = bodyOf('main', 'loadPhotos');
  assert.match(photos, /photoStopList\(layer\.model\)/);
  assert.match(photos, /ui\('photos-show'\)\.checked = true;\s*showPhotoPins\(\);\s*photos\.openGroup\(id\)/);
  assert.match(photos, /onChange:[^\n]*updateStopControls\(\)/, 'photo enter/exit refreshes the lists');
  inCode('main', /const result = original\(\.\.\.args\);\s*showPhotoPins\(\);\s*updateStopControls\(\)/,
         'rehearsal and walk enter/exit refresh the lists, including programmatic calls');
  assert.match(bodyOf('main', 'showPlan'), /refreshStationList\(\)/, 'reloading replaces the station list');
  inCode('main', /loadRubric\(\)\.then\([^\n]*refreshStationList\(\)/, 'late rubric labels reach the list');
  assert.match(PAGE, /#info \.stop-list\s*\{[^}]*max-height:[^}]*overflow-y:\s*auto/);
});

test('keyboard lists: each camera mode disables both lists with a reason, then restores them', () => {
  const nodes = new Map();
  for (const kind of ['station', 'photo']) {
    nodes.set(`${kind}-list`, {children: [{}]});
    nodes.set(`${kind}-controls`, {disabled: true});
    nodes.set(`${kind}-list-note`, {textContent: ''});
  }
  const rehearsal = {active: false}, walk = {active: false}, photos = {active: false};
  const update = () => runInNewContext(`(() => ${bodyOf('main', 'updateStopControls')})()`, {
    ui: id => nodes.get(id), rehearsal, photos, T: globalThis.TERMS,
    busy: () => rehearsal.active || walk.active, photoListNote: 'No photo stops in this catalogue.',
  });
  for (const [mode, reason] of [[rehearsal, 'Exit the rehearsal'], [walk, 'Exit Walk freely'], [photos, 'Exit the photo view']]) {
    mode.active = true;
    update();
    for (const kind of ['station', 'photo']) {
      assert.equal(nodes.get(`${kind}-controls`).disabled, true);
      assert.ok(nodes.get(`${kind}-list-note`).textContent.startsWith(reason));
    }
    mode.active = false;
    update();
    for (const kind of ['station', 'photo']) assert.equal(nodes.get(`${kind}-controls`).disabled, false);
  }
  for (const kind of ['station', 'photo']) nodes.get(`${kind}-list`).children = [];
  update();
  for (const kind of ['station', 'photo']) {
    assert.equal(nodes.get(`${kind}-controls`).disabled, true);
    assert.match(nodes.get(`${kind}-list-note`).textContent, /^No /);
  }
});

test('every id that the 3D code looks up is in the page, or made by the code', () => {
  const lookups = /(?:(?<![\w.$])(?:el|ui|text|fill|show)|\bdocument\.getElementById)\(\s*['"]([\w-]+)['"]/g;
  const loops = /for \(const id of \[([^\]]*)\]\)\s*(?:el|ui)\(id\)/g;
  const selectors = /\b(?:querySelector(?:All)?|closest)\(\s*(['"])(.*?)\1/g;
  for (const [file, src] of Object.entries(JS)) {
    const wanted = new Set([...src.matchAll(lookups)].map(m => m[1]));
    for (const [, list] of src.matchAll(loops)) for (const [, id] of list.matchAll(/['"]([\w-]+)['"]/g)) wanted.add(id);
    for (const [, , sel] of src.matchAll(selectors)) for (const [, id] of sel.matchAll(/#([\w-]+)/g)) wanted.add(id);
    for (const id of wanted) {
      if (BUILT[id]) built(id);
      else assert.ok(ELEMENTS.has(id), `web/3d/${file}.js looks up #${id}, which web/3d/index.html no longer has`);
    }
  }
});
