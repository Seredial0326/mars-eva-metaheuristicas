// Engine of the in-context tips (#125), in the spirit of Apple's TipKit: one short tip at a
// time, next to the control it is about, at the moment it is useful. A tip closes with
// "Got it", with ×, with Esc (while it or its control has focus) or by using its control,
// and it does not come back. Seen tips are remembered in the browser.
//   ?tips=reset  show every tip again (demo)      ?tips=off  no tips
// No libraries. Each view brings its own tip list and its own way to read the screen:
// the 2D HUD in web/tips.js, the 3D map in web/3d/tips_3d.js. The choice of the next tip
// is a pure function, tested with Node (tests/web/tips*.test.mjs).
//
// A tip is {id, anchor, title, text, when(s), done(s), alt?}. `when(s)`: the moment the tip
// helps. `done(s)`: the user already did it, so the tip is retired without being shown.
// `anchor`: CSS selector of the control. `alt`: an alternative to the next tip (say, "no
// plan yet" instead of "read the plan"), so both share one number in "n / N".

/** Parse the ?tips= switch: "reset", "off" or null. */
export function tipsMode(search) {
  const v = new URLSearchParams(search || "").get("tips");
  return v === "reset" || v === "off" ? v : null;
}

/** Tips the user already did: they count as seen, so they never show. */
export function retired(state, tips) {
  return tips.filter(t => t.done(state)).map(t => t.id);
}

/** The one tip to show now, or null: the first unseen, not done, whose moment is now
 *  and whose control is on screen (state.visible(selector)). */
export function nextTip(state, tips) {
  const seen = new Set(state.seen);
  for (const t of tips) {
    if (seen.has(t.id) || t.done(state) || !t.when(state)) continue;
    if (state.visible && !state.visible(t.anchor)) continue;
    return t;
  }
  return null;
}

/** "n / N" of a tip: alternatives share the number of the tip they stand in for. */
export function tipNumber(tip, tips) {
  const main = tips.filter(t => !t.alt);
  const i = tips.indexOf(tip);
  const n = tips.slice(0, i + 1).filter(t => !t.alt).length + (tip.alt ? 1 : 0);
  return {n: Math.min(n, main.length), total: main.length};
}

// ------------------------------------------------------------------ browser part

function loadSeen(storage, key) {
  try { return JSON.parse(storage.getItem(key) || "[]"); } catch { return []; }
}

function saveSeen(storage, key, seen) {
  try { storage.setItem(key, JSON.stringify([...new Set(seen)])); } catch { /* private mode */ }
}

const CSS = `
.tipkit { position: fixed; z-index: 9000; width: 280px; max-width: calc(100vw - 24px);
  background: var(--surface-2, #1c232c); color: var(--text, #e8ecf1);
  border: 1px solid var(--accent, #ff7a45); border-radius: 10px; padding: 12px 14px 10px;
  box-shadow: 0 8px 28px rgba(0,0,0,.45); font-size: 13px; line-height: 1.4; box-sizing: border-box; }
.tipkit[hidden] { display: none; }
.tipkit:focus { outline: none; }
.tipkit:focus-visible { outline: 2px solid var(--accent, #ff7a45); outline-offset: 2px; }
.tipkit h3 { margin: 0 22px 4px 0; font-size: 13.5px; color: var(--accent, #ff7a45); }
.tipkit p { margin: 0 0 10px; }
.tipkit .tip-row { display: flex; justify-content: space-between; align-items: center; gap: 8px; }
.tipkit .tip-count { color: var(--muted, #a3aebb); font-size: 11.5px; white-space: nowrap; }
.tipkit button.tip-ok { background: var(--accent, #ff7a45); color: var(--accent-ink, #1a0f08); border: 0;
  border-radius: 6px; padding: 4px 12px; font: inherit; font-weight: 600; cursor: pointer; }
.tipkit button.tip-x { position: absolute; top: 6px; right: 6px; width: 26px; height: 26px; border: 0;
  background: transparent; color: var(--muted, #a3aebb); font-size: 18px; line-height: 1; cursor: pointer;
  border-radius: 6px; }
.tipkit button.tip-x:hover { color: var(--text, #e8ecf1); background: var(--surface-3, #262f3a); }
.tipkit::before { content: ""; position: absolute; width: 12px; height: 12px; background: inherit;
  border: inherit; transform: rotate(45deg); }
.tipkit[data-side="right"]::before { left: -7px; top: var(--tip-arrow, 18px); border-top: 0; border-right: 0; }
.tipkit[data-side="below"]::before { top: -7px; left: var(--tip-arrow, 24px); border-right: 0; border-bottom: 0; }
.tipkit[data-side="above"]::before { bottom: -7px; left: var(--tip-arrow, 24px); border-left: 0; border-top: 0; }
.tip-target { outline: 2px dashed var(--accent, #ff7a45) !important; outline-offset: 3px; }
.tip-sr { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap; }
@media (prefers-reduced-motion: no-preference) { .tipkit { animation: tipin .18s ease-out; } }
@keyframes tipin { from { opacity: 0; transform: translateY(4px); } to { opacity: 1; transform: none; } }
`;

function isVisible(sel) {
  const el = document.querySelector(sel);
  if (!el || el.closest("[hidden]")) return false;
  const r = el.getBoundingClientRect();
  return r.width > 0 && r.height > 0 && r.bottom > 0 && r.top < innerHeight && r.left < innerWidth;
}

const clamp = (v, lo, hi) => Math.min(Math.max(v, lo), Math.max(lo, hi));

// `bars`: containers the tip must not cover, each {selector, side}. A control inside a
// side panel ("right") gets its tip just right of the panel, over the map; a control
// inside a bar at the bottom ("above") gets it just above the bar.
function place(box, target, bars) {
  const r = target.getBoundingClientRect(), w = box.offsetWidth, h = box.offsetHeight, gap = 12;
  const bar = bars.map(b => ({...b, el: target.closest(b.selector)})).find(b => b.el);
  const c = bar ? bar.el.getBoundingClientRect() : r;
  let side, x, y;
  if (bar && bar.side === "above" && c.top - gap - h >= 8) {
    side = "above"; x = clamp(r.left + r.width / 2 - 40, 8, innerWidth - w - 8); y = c.top - gap - h;
    box.style.setProperty("--tip-arrow", `${clamp(r.left + r.width / 2 - x - 6, 12, w - 24)}px`);
  } else if ((!bar || bar.side === "right") && c.right + gap + w <= innerWidth - 8) {
    side = "right"; x = c.right + gap; y = clamp(r.top + r.height / 2 - 24, 8, innerHeight - h - 8);
    box.style.setProperty("--tip-arrow", `${clamp(r.top + r.height / 2 - y - 6, 10, h - 22)}px`);
  } else {
    side = r.bottom + gap + h <= innerHeight - 8 ? "below" : "above";
    x = clamp(r.left, 8, innerWidth - w - 8);
    y = side === "below" ? r.bottom + gap : Math.max(8, r.top - gap - h);
    box.style.setProperty("--tip-arrow", `${clamp(r.left + 16 - x, 12, w - 24)}px`);
  }
  box.dataset.side = side;
  box.style.left = `${Math.round(x)}px`;
  box.style.top = `${Math.round(y)}px`;
}

/**
 * Start the tips of one view.
 *   tips        the tip list, in the order of the demo
 *   readState   () => state of the screen (anything the tips' when/done read). It may
 *               return `tab`: the view's current step, remembered in `visited`.
 *   storageKey  where the seen tips are kept (localStorage)
 *   bars        containers not to cover, [{selector, side: "right" | "above"}]
 *   attributes  attribute changes that can make a tip due (MutationObserver filter)
 *   paused      () => true while no tip may show (say, walking with the mouse captured)
 */
export function startTips({tips, readState, storageKey, bars = [], paused = () => false,
                          attributes = ["hidden", "aria-selected", "open", "class", "disabled"],
                          win = window, storage = window.localStorage} = {}) {
  const mode = tipsMode(win.location.search);
  if (mode === "off") return null;
  let seen = mode === "reset" ? [] : loadSeen(storage, storageKey);
  if (mode === "reset") saveSeen(storage, storageKey, seen);
  const visited = [];

  const style = document.createElement("style");
  style.textContent = CSS;
  document.head.appendChild(style);
  const box = document.createElement("div");
  box.className = "tipkit";
  box.id = "tipkit";
  box.hidden = true;
  box.setAttribute("role", "dialog");
  box.setAttribute("aria-modal", "false");
  box.setAttribute("aria-labelledby", "tipkit-title");
  box.setAttribute("aria-describedby", "tipkit-text");
  box.tabIndex = -1;        // a click on the tip's text puts the focus in it, so Esc closes it
  box.innerHTML = `<button class="tip-x" type="button" aria-label="Close tip" title="Close (Esc)">×</button>
    <h3 id="tipkit-title"></h3><p id="tipkit-text"></p>
    <div class="tip-row"><span class="tip-count"></span><button class="tip-ok" type="button">Got it</button></div>`;
  const live = document.createElement("div");
  live.className = "tip-sr";
  live.setAttribute("role", "status");
  live.setAttribute("aria-live", "polite");
  document.body.append(box, live);

  let current = null, target = null;

  function remember(id) {
    if (!seen.includes(id)) { seen = [...seen, id]; saveSeen(storage, storageKey, seen); }
  }
  function hide() {
    if (target) { target.classList.remove("tip-target"); target.removeAttribute("aria-describedby"); }
    box.hidden = true; current = null; target = null;
  }
  function dismiss() {
    if (!current) return;
    const id = current.id, hadFocus = box.contains(document.activeElement), back = target;
    remember(id); hide();
    if (hadFocus && back) back.focus({preventScroll: true});
    schedule();
  }
  function show(tip) {
    hide();
    current = tip;
    const el = document.querySelector(tip.anchor);
    target = el.closest("label") || el;            // a checkbox is pointed at with its whole row
    box.querySelector("#tipkit-title").textContent = tip.title;
    box.querySelector("#tipkit-text").textContent = tip.text;
    const {n, total} = tipNumber(tip, tips);
    box.querySelector(".tip-count").textContent = `${n} / ${total}`;
    box.querySelector(".tip-count").setAttribute("aria-label", `Tip ${n} of ${total}`);
    box.hidden = false;
    target.classList.add("tip-target");
    target.setAttribute("aria-describedby", "tipkit-text");
    place(box, target, bars);
    live.textContent = `Tip: ${tip.title}. ${tip.text}`;
  }
  function update() {
    if (paused()) { if (current) hide(); return; }
    const s = {...readState(), visible: isVisible};
    if (s.tab && !visited.includes(s.tab)) visited.push(s.tab);
    s.visited = visited;
    s.seen = seen;
    for (const id of retired(s, tips)) remember(id);
    s.seen = seen;
    const tip = nextTip(s, tips);
    if (!tip) { if (current) hide(); return; }
    if (current && current.id === tip.id && target && document.body.contains(target)) { place(box, target, bars); return; }
    show(tip);
  }
  let queued = false;
  function schedule() {
    if (queued) return;
    queued = true;
    requestAnimationFrame(() => { queued = false; update(); });
  }

  box.querySelector(".tip-ok").addEventListener("click", dismiss);
  box.querySelector(".tip-x").addEventListener("click", dismiss);
  // Esc in the tip closes only the tip: the view's own Esc (pause, close a card) waits.
  box.addEventListener("keydown", e => { if (e.key === "Escape") { e.stopPropagation(); dismiss(); } });
  // Keyboard users hear the tip as the control's description (aria-describedby); Esc on
  // the control closes it too.
  document.addEventListener("keydown", e => {
    if (e.key === "Escape" && current && target && target.contains(document.activeElement)) dismiss();
  });
  // Using the control the tip points at also closes it for good.
  document.addEventListener("click", e => {
    if (current && target && target.contains(e.target)) { remember(current.id); hide(); schedule(); }
  }, true);
  new MutationObserver(schedule).observe(document.body, {
    subtree: true, childList: true, attributes: true, attributeFilter: attributes,
  });
  win.addEventListener("resize", schedule);
  document.addEventListener("scroll", schedule, true);
  schedule();
  return { update, dismiss, schedule, get current() { return current; } };
}
