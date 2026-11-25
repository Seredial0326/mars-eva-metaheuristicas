// Rehearsal model of the 3D map, with no dependencies but the team's glossary (tested with
// `node --test`).
//
// Turns a parsed route (plan_model.js) into "where is the walker at playback time t":
//   - Time base: the profile's t_s when the answer has one. A stop is charged to the
//     segment that ARRIVES at it (E4 and the tour both add the service time to the stop
//     vertex), so a segment far slower than its neighbours is split into the walk and a
//     wait at its end: the walker reaches the vertex and stands there. With no profile,
//     time = distance at ASSUMED_SPEED (the page must say so).
//   - Profile values come from the TRUE route, interpolated between its vertices.
//   - The camera follows a smoothed copy of the route. The planner moves cell to cell in
//     eight directions, so the true path is a staircase: walked as is, the view would
//     shake at every step. The copy is a Gaussian average along the path (SMOOTH_SIGMA),
//     pinned at the route ends, at the stops and at the turn, and made less smooth
//     wherever it would leave the true route by more than MAX_CUT.
//   - Heading: towards the point LOOK_AHEAD metres further along the smoothed path, never
//     beyond the next stop (looking past a turn-back point would spin the view). While
//     the walker stands at a stop the heading turns from the arrival to the departure
//     direction. A route with no direction at all (a single point) has no heading: null.
//   - A route of a single vertex (the way home asked at the habitat, issue #115) is the
//     walker standing there: no length and no time.
// Distances are metres along the true route; x east, y north (Mars CRS); headings in
// radians from north towards east, as in camera_math.js.
// What the screen says takes its names and number formats from the shared glossary,
// web/terms.js (#166), as the HUD, the arm tablet and the wrist card do.
import '../terms.js';
import { cumulativeLength } from './plan_model.js';

const T = globalThis.TERMS;

export const EYE_HEIGHT = 1.7;         // m above the shown ground
export const MIN_EYE = 1.6;            // m: floor of the eye above the ground right under it
export const ASSUMED_SPEED = 1.0;      // m/s when the answer has no time profile
export const LOOK_AHEAD = 12;          // m, like the heading arrow of the 2D planner (12 vertices)
export const HEADING_HOLD = 3;         // m before a stop where the heading stops changing
export const STOP_RADIUS = 3;          // m: a visited station this close to a vertex is a stop
export const SMOOTH_SIGMA = 2.5;       // m
export const MAX_CUT = 1.5;            // m: largest distance of the camera path from the route
export const SAMPLE = 0.5;             // m between samples of the camera path
export const GROUND_WINDOW = 3;        // m each way: the eye follows the ground averaged over it
const WAIT_FACTOR = 5;                 // a segment this many times slower than the median...
const WAIT_MIN_S = 10;                 // ...and this much longer than that is walk + wait

const lerp = (a, b, f) => a + (b - a) * f;
const smoothstep = f => f * f * (3 - 2 * f);

// Smallest signed difference between two angles (radians).
export function angleDelta(to, from) {
  let d = (to - from) % (2 * Math.PI);
  if (d > Math.PI) d -= 2 * Math.PI;
  if (d < -Math.PI) d += 2 * Math.PI;
  return d;
}

// Minutes and seconds (m:ss), the glossary's clock: only for the clock line of the player
// (progressText). Every other time the 3D shows is in whole minutes (T.min).
export const clock = T.clock;

// Index of the last element <= value in an ascending array (0 if none).
function lastAtMost(array, value, last = array.length - 1) {
  let lo = 0, hi = last;
  while (lo < hi) {
    const mid = (lo + hi + 1) >> 1;
    if (array[mid] <= value) lo = mid; else hi = mid - 1;
  }
  return lo;
}

function distanceToSegment(px, py, ax, ay, bx, by) {
  const dx = bx - ax, dy = by - ay, len2 = dx * dx + dy * dy;
  const f = len2 > 0 ? Math.min(1, Math.max(0, ((px - ax) * dx + (py - ay) * dy) / len2)) : 0;
  return Math.hypot(px - ax - dx * f, py - ay - dy * f);
}

// ---- time ---------------------------------------------------------------------------

// Per-vertex clock of a route. Returns {t, walk, wait, assumed}: t[i] is the time the
// walker LEAVES vertex i; segment i -> i+1 takes walk[i] seconds of walking followed by
// wait[i] seconds standing at vertex i+1.
function timeline(route, dist) {
  const n = route.coords.length, walk = new Float64Array(n - 1), wait = new Float64Array(n - 1);
  const ts = route.profile && route.profile.t_s;
  let usable = Boolean(ts) && ts.every(Number.isFinite);
  for (let i = 1; usable && i < n; i++) usable = ts[i] >= ts[i - 1];
  if (!usable) {
    const t = Float64Array.from(dist, d => d / ASSUMED_SPEED);
    for (let i = 0; i < n - 1; i++) walk[i] = t[i + 1] - t[i];
    return {t, walk, wait, assumed: true};
  }
  const t = Float64Array.from(ts), pace = [];
  for (let i = 0; i < n - 1; i++) {
    const len = dist[i + 1] - dist[i];
    if (len > 0 && t[i + 1] > t[i]) pace.push((t[i + 1] - t[i]) / len);
  }
  pace.sort((a, b) => a - b);
  const median = pace.length ? pace[pace.length >> 1] : 1 / ASSUMED_SPEED;
  const slow = i => {
    const len = dist[i + 1] - dist[i], dt = t[i + 1] - t[i];
    return len <= 0 ? dt > 0 : dt > len * median * WAIT_FACTOR + WAIT_MIN_S;
  };
  const ordinary = i => dist[i + 1] > dist[i] && t[i + 1] > t[i] && !slow(i);
  for (let i = 0; i < n - 1; i++) {
    const len = dist[i + 1] - dist[i], dt = t[i + 1] - t[i];
    if (!slow(i)) { walk[i] = dt; continue; }
    // Walking pace of the nearest ordinary segment: before this one, else after.
    let near = median, j = i - 1;
    while (j >= 0 && !ordinary(j)) j--;
    if (j < 0) { j = i + 1; while (j < n - 1 && !ordinary(j)) j++; }
    if (j >= 0 && j < n - 1) near = (t[j + 1] - t[j]) / (dist[j + 1] - dist[j]);
    walk[i] = Math.min(dt, len * near);
    wait[i] = dt - walk[i];
  }
  return {t, walk, wait, assumed: false};
}

// ---- stops --------------------------------------------------------------------------

// Stops of a route: [{index, arrive, leave, waitS, station}] in walking order.
//   index    vertex of the route
//   arrive   time the walker gets there; leave = arrive + waitS
//   station  {id, type, score, serviceMin, order, x, y} of the station there, or null
// A stop is a vertex where the walker stands still, a vertex the answer lists as a stop
// (tour: stop_index / visit_order), or the vertex nearest to a station that the answer
// marks as visited or as the goal, when it is within STOP_RADIUS. Nothing here assumes
// a single goal.
function findStops(route, points, clockOf) {
  const {coords} = route, n = coords.length, byIndex = new Map();
  const stations = points.filter(p => p.kind === 'station');
  const info = p => p && {
    id: p.properties.id != null ? String(p.properties.id) : (p.kind === 'goal' ? 'Goal' : ''),
    type: p.properties.type ?? null,
    score: Number.isFinite(p.properties.score) ? p.properties.score : null,
    serviceMin: Number.isFinite(p.properties.service_time_min) ? p.properties.service_time_min : null,
    order: Number.isFinite(p.properties.order) ? p.properties.order : null,
    x: p.x, y: p.y};
  const near = (p, i) => Math.hypot(coords[i][0] - p.x, coords[i][1] - p.y);
  const put = (index, point) => {
    const stop = byIndex.get(index) || {index, station: null};
    if (point && !stop.station) stop.station = info(point);
    byIndex.set(index, stop);
  };

  for (let i = 0; i < n - 1; i++) if (clockOf.wait[i] > 0) put(i + 1, null);
  const placed = new Set();
  for (const s of route.stops) {                    // the tour says where each station is visited
    const point = stations.find(p => String(p.properties.id) === s.id);
    put(s.index, point || {kind: 'station', x: coords[s.index][0], y: coords[s.index][1], properties: {id: s.id}});
    placed.add(s.id);
  }
  // Stations to stop at: visited ones and the one a goal point names; a goal point that
  // names no station of this plan is a stop itself.
  const goals = points.filter(p => p.kind === 'goal');
  const named = new Set(goals.filter(p => p.properties.station != null).map(p => String(p.properties.station)));
  const wanted = stations.filter(p => p.properties.visited === true || named.has(String(p.properties.id)));
  for (const g of goals) {
    if (g.properties.station == null || !stations.some(p => String(p.properties.id) === String(g.properties.station))) wanted.push(g);
  }
  for (const p of wanted) {
    if (p.kind === 'station' && placed.has(String(p.properties.id))) continue;
    let best = -1;                                  // a vertex where the walker waits wins
    for (let i = 1; i < n; i++) {
      if (near(p, i) > STOP_RADIUS) continue;
      const better = best < 0 || (byIndex.has(i) !== byIndex.has(best) ? byIndex.has(i) : near(p, i) < near(p, best));
      if (better) best = i;
    }
    if (best >= 0) put(best, p);
  }
  // A wait with no station attached yet: any station of the plan standing right there.
  for (const stop of byIndex.values()) {
    if (stop.station) continue;
    const here = stations.filter(p => near(p, stop.index) <= STOP_RADIUS)
                         .sort((a, b) => near(a, stop.index) - near(b, stop.index))[0];
    if (here) stop.station = info(here);
  }
  return [...byIndex.values()].sort((a, b) => a.index - b.index).map(stop => {
    const waitS = stop.index > 0 ? clockOf.wait[stop.index - 1] : 0;
    return {...stop, waitS, leave: clockOf.t[stop.index], arrive: clockOf.t[stop.index] - waitS};
  });
}

// ---- camera path --------------------------------------------------------------------

// Smoothed copy of the route between consecutive anchors (vertex indices where the
// path must pass exactly). Returns the pieces [{a, b, step, x, y}]: positions every
// `step` metres of TRUE route distance from a to b, plus the largest distance of any
// sample from the true route.
function smoothPath(coords, dist, anchors) {
  const truePoint = d => {
    const i = Math.min(coords.length - 2, lastAtMost(dist, d)), len = dist[i + 1] - dist[i];
    const f = len > 0 ? Math.min(1, Math.max(0, (d - dist[i]) / len)) : 0;
    return [lerp(coords[i][0], coords[i + 1][0], f), lerp(coords[i][1], coords[i + 1][1], f)];
  };
  // Distance from a point to the stretch of the true route around distance d.
  const offRoute = (px, py, d, reach) => {
    const first = lastAtMost(dist, d - reach), last = Math.min(coords.length - 2, lastAtMost(dist, d + reach));
    let best = Infinity;
    for (let i = first; i <= last; i++) {
      best = Math.min(best, distanceToSegment(px, py, coords[i][0], coords[i][1], coords[i + 1][0], coords[i + 1][1]));
    }
    return best;
  };

  const pieces = [];
  let maxOff = 0;
  for (let p = 0; p < anchors.length - 1; p++) {
    const a = dist[anchors[p]], b = dist[anchors[p + 1]], m = Math.max(1, Math.ceil((b - a) / SAMPLE));
    const step = (b - a) / m, tx = new Float64Array(m + 1), ty = new Float64Array(m + 1);
    for (let k = 0; k <= m; k++) [tx[k], ty[k]] = truePoint(a + step * k);
    const x = Float64Array.from(tx), y = Float64Array.from(ty);
    if (step > 0) {
      // Beyond an end of the piece the path is continued by its own mirror image through
      // that end, so the average leaves the end exactly where it is.
      const at = (array, q) => (q < 0 ? 2 * array[0] - array[Math.min(m, -q)]
                                : q > m ? 2 * array[m] - array[Math.max(0, 2 * m - q)] : array[q]);
      const sigma = new Float64Array(m + 1).fill(Math.min(SMOOTH_SIGMA, (b - a) / 4) / step);
      for (let pass = 0; pass < 12; pass++) {
        let worst = 0;
        const off = new Float64Array(m + 1);
        for (let k = 0; k <= m; k++) {
          const s = sigma[k], reach = Math.ceil(3 * s);
          let sx = 0, sy = 0, sw = 0;
          for (let u = -reach; u <= reach; u++) {
            const w = s > 0 ? Math.exp(-0.5 * (u / s) ** 2) : 1;
            sx += w * at(tx, k + u); sy += w * at(ty, k + u); sw += w;
          }
          x[k] = sx / sw; y[k] = sy / sw;
          off[k] = offRoute(x[k], y[k], a + step * k, 3 * SMOOTH_SIGMA + 2);
          worst = Math.max(worst, off[k]);
        }
        if (worst <= 0.8 * MAX_CUT) break;
        // Too far from the route somewhere (a sharp corner): smooth less around it.
        const next = Float64Array.from(sigma);
        for (let k = 0; k <= m; k++) {
          if (off[k] <= 0.8 * MAX_CUT) continue;
          const reach = Math.ceil(3 * sigma[k]);
          for (let q = Math.max(0, k - reach); q <= Math.min(m, k + reach); q++) next[q] = Math.min(next[q], 0.7 * sigma[k]);
        }
        sigma.set(next);
      }
      for (let k = 0; k <= m; k++) maxOff = Math.max(maxOff, offRoute(x[k], y[k], a + step * k, 3 * SMOOTH_SIGMA + 2));
    }
    pieces.push({a, b, step, x, y, first: anchors[p], last: anchors[p + 1]});
  }
  return {pieces, maxOff};
}

// ---- the model ----------------------------------------------------------------------

// The same route with its single vertex (and each profile value) written twice: a
// segment of no length and no time, which everything below handles.
function standStill(route) {
  const twice = a => (Array.isArray(a) || ArrayBuffer.isView(a)) && a.length === 1 ? [a[0], a[0]] : a;
  const profile = route.profile && Object.fromEntries(Object.entries(route.profile).map(([k, v]) => [k, twice(v)]));
  return {...route, coords: twice(route.coords), profile};
}

// route: a route of parsePlan(), or one vertex long (see standStill); points: the plan's
// points (for the stops). Returns
//   hasProfile, assumedSpeed (null when the answer gives the time), start, end,
//   duration (s), length (m), usableWh, stops, anchors (vertices the camera path passes
//   through exactly), maxOffRoute (m, camera path from the true route), times and
//   distances (per vertex), and
//   stateAt(time)  where the walker is at a playback time (seconds on the plan's clock):
//                  {time, at (fractional vertex), distance, x, y (true route), cx, cy
//                  (camera path), heading (null on a route with no direction), ahead (the
//                  point looked at), leg ('outbound', 'return' or null), standing, stop,
//                  profile (interpolated values or null)}
//   cameraAt(d), headingAt(d)  the camera path by distance along the route.
// ---- simulated energy-use bias (X2, #101) -------------------------------------------
// The adaptive walkback learns the astronaut's own factor k (real use = k x E3's
// prediction) from each walked segment. In a rehearsal there is no sensor, so the "real"
// use is simulated: every BIAS_SEG_M metres of route, k_true x the predicted use x
// lognormal noise (seeded, repeatable). Nothing else in the rehearsal changes: the
// profile keeps E3's values and the bias only adds used_real_wh beside them.
export const BIAS_SEG_M = 30;          // m per observed segment, as web/guide_core.js
export const BIAS_NOISE = 0.15;        // sd of log(real / predicted) per segment

function seeded(seed) {                // mulberry32
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6D2B79F5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// Segments of BIAS_SEG_M metres over the route and the simulated real use per vertex.
//   used  E3's cumulative use per vertex (Wh, profile.used_wh); dist: cumulative metres.
// Returns {kTrue, noise, seed, segments: [{from, to, predicted, observed}], realUsed}
// with realUsed[v] the simulated cumulative real use, starting at used[0].
export function biasSegments(used, dist, {kTrue = 1, noise = BIAS_NOISE, seed = 101} = {}) {
  const n = used.length, rand = seeded(seed), segments = [];
  const realUsed = new Float64Array(n);
  realUsed[0] = used[0];
  let from = 0;
  while (from < n - 1) {
    let to = from + 1;
    while (to < n - 1 && dist[to] - dist[from] < BIAS_SEG_M) to++;
    const u = Math.max(rand(), 1e-12), v = rand();
    const factor = kTrue * Math.exp(noise * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * v));
    for (let k = from + 1; k <= to; k++) realUsed[k] = realUsed[k - 1] + factor * (used[k] - used[k - 1]);
    segments.push({from, to, predicted: used[to] - used[from], observed: realUsed[to] - realUsed[from]});
    from = to;
  }
  return {kTrue, noise, seed, segments, realUsed};
}

// bias (optional): {kTrue, noise, seed}. Without it the rehearsal is exactly as before.
export function buildRehearsal(route, points = [], bias = null) {
  if (route.coords.length === 1) route = standStill(route);
  const {coords, profile} = route, n = coords.length;
  const dist = cumulativeLength(coords), length = dist[n - 1];
  const clockOf = timeline(route, dist), {t, walk, wait} = clockOf;
  const stops = findStops(route, points, clockOf);
  const turn = route.turnIndex;
  const biasModel = bias && profile && profile.used_wh ? biasSegments(profile.used_wh, dist, bias) : null;

  // The camera path passes exactly through the ends, the stops and the turn.
  const anchors = [...new Set([0, n - 1, ...stops.map(s => s.index), ...(turn != null ? [turn] : [])])]
    .sort((a, b) => a - b);
  const {pieces, maxOff} = smoothPath(coords, dist, anchors);

  const pieceOfVertex = i => {                      // piece that starts at or before vertex i
    let p = 0;
    while (p < pieces.length - 1 && pieces[p + 1].first <= i) p++;
    return p;
  };
  const onPiece = (piece, d) => {
    if (piece.step <= 0) return [piece.x[0], piece.y[0]];
    const g = Math.min(piece.x.length - 1, Math.max(0, (d - piece.a) / piece.step));
    const k = Math.min(piece.x.length - 2, Math.floor(g)), f = g - k;
    return [lerp(piece.x[k], piece.x[k + 1], f), lerp(piece.y[k], piece.y[k + 1], f)];
  };
  // Heading on a piece at distance d, and the point it looks at.
  const lookOn = (piece, d) => {
    const from = Math.min(d, Math.max(piece.a, piece.b - HEADING_HOLD)), to = Math.min(from + LOOK_AHEAD, piece.b);
    const p = onPiece(piece, from), q = onPiece(piece, to);
    const flat = Math.hypot(q[0] - p[0], q[1] - p[1]) < 1e-6;
    return {heading: flat ? null : Math.atan2(q[0] - p[0], q[1] - p[1]), ahead: q};
  };
  // A piece with no length has no direction of its own: take the nearest one that has.
  // With none at all (a single point) the heading stays null and the view keeps its own.
  const headings = pieces.map(piece => [lookOn(piece, piece.a).heading, lookOn(piece, piece.b).heading]);
  let known = headings.find(h => h[0] !== null);
  known = known ? known[0] : null;
  for (const h of headings) { if (h[0] === null) h[0] = h[1] = known; else known = h[1]; }

  const pieceAtDistance = d => {
    let p = 0;
    while (p < pieces.length - 1 && pieces[p].b <= d) p++;
    return p;
  };

  function stateAt(time) {
    const now = Math.min(t[n - 1], Math.max(t[0], time));
    const i = Math.min(n - 2, lastAtMost(t, now));
    const dt = t[i + 1] - t[i], e = now - t[i], len = dist[i + 1] - dist[i];
    const moved = walk[i] > 0 ? Math.min(1, e / walk[i]) : (e > 0 || dt === 0 ? 1 : 0);
    // (the margin: a stop's arrival time is t - wait, which rounding can leave a hair short)
    const standing = wait[i] > 0 && e >= walk[i] - 1e-9 && e < dt;
    const clockF = dt > 0 ? e / dt : moved;
    const distance = dist[i] + len * moved;
    // Until the walker leaves vertex i+1 it is on the piece that ends there.
    const p = pieceOfVertex(i);
    const piece = pieces[p];
    const [cx, cy] = onPiece(piece, distance);
    const look = lookOn(piece, distance);
    let heading = look.heading ?? headings[p][0];
    if (standing && p + 1 < pieces.length && heading !== null) {   // turn towards the way out while waiting
      const f = smoothstep((e - walk[i]) / wait[i]);
      heading = headings[p][1] + angleDelta(headings[p + 1][0], headings[p][1]) * f;
    }
    let values = null;
    if (profile) {
      // What accumulates (energy, O2) follows the clock, also while standing; what
      // depends on the place (energy and time to return) follows the position.
      values = {};
      for (const key of Object.keys(profile)) {
        const f = key === 'rv_wh' || key === 'rv_time_s' ? moved : clockF;
        values[key] = lerp(profile[key][i], profile[key][i + 1], f);
      }
      if (biasModel) values.used_real_wh = lerp(biasModel.realUsed[i], biasModel.realUsed[i + 1], clockF);
    }
    const stop = standing ? stops.find(s => s.index === i + 1) || null : null;
    return {
      time: now, at: i + moved, distance, x: lerp(coords[i][0], coords[i + 1][0], moved),
      y: lerp(coords[i][1], coords[i + 1][1], moved), cx, cy, heading, ahead: look.ahead,
      leg: turn == null ? null : (now >= t[turn] ? 'return' : 'outbound'),
      standing, stop, profile: values,
    };
  }

  return {
    hasProfile: Boolean(profile), assumedSpeed: clockOf.assumed ? ASSUMED_SPEED : null,
    start: t[0], end: t[n - 1], duration: t[n - 1] - t[0], length,
    usableWh: route.totals.usable_wh, stops, anchors, maxOffRoute: maxOff, turnIndex: turn,
    times: t, distances: dist, stateAt,
    bias: biasModel,                 // null unless a bias was asked for (X2, #101)
    // Camera path (Mars x, y) and heading at a distance along the route, on the piece
    // being walked towards (at a stop: arriving).
    cameraAt(d) { return onPiece(pieces[pieceAtDistance(d)], d); },
    headingAt(d) {
      const p = pieceAtDistance(d);
      return lookOn(pieces[p], d).heading ?? headings[p][0];
    },
  };
}

// ---- what the screen says -----------------------------------------------------------

// Height of the eye at a distance along the route. ground(d) gives the shown ground
// height under the camera path at distance d. The eye follows the ground averaged over
// +-GROUND_WINDOW metres of path, so it does not bob over every facet of the mesh, but
// never comes closer than MIN_EYE to the ground right under it.
export function eyeAltitude(ground, d, length) {
  let sum = 0, count = 0;
  for (let u = -GROUND_WINDOW; u <= GROUND_WINDOW; u++) {
    sum += ground(Math.min(length, Math.max(0, d + u)));
    count++;
  }
  return Math.max(sum / count + EYE_HEIGHT, ground(d) + MIN_EYE);
}

// The value of the tablet's "Home in" meter in its own words, "home in 12 min"
// (guide_core meters().back.text): the glossary's name and whole minutes, written here from
// its seconds (meters().back.s). Never negative: on arrival the time left to walk can come
// out a hair under zero (rounding).
export function homeInText(seconds) {
  return `${T.NAMES.home.toLowerCase()} ${T.min(Math.max(0, seconds))}`;
}

// Energy bar and its text for the values of a state, with the 2D planner's arithmetic
// (showRouteIdx in web/index.html) and the glossary's names and numbers: whole Wh, "spare"
// for what is left after returning, "home in" in whole minutes. values: state.profile;
// usable in Wh. Returns null when there is nothing to show.
export function energyReadout(values, usable) {
  if (!values || values.used_wh == null || values.rv_wh == null || !(usable > 0)) return null;
  const used = values.used_wh, rv = values.rv_wh, free = Math.max(0, usable - used - rv);
  const pct = v => Math.max(0, 100 * v / usable);
  // At the habitat the energy to return can come out a hair below zero (-2e-5 Wh): never
  // write a minus sign. "spare" is the word of the HUD's key for the same bar.
  const lines = [`Energy used ${T.wh(Math.max(0, used))} · return needs ${T.wh(Math.max(0, rv))} · ` +
                 `spare ${Math.round(free)} of ${T.wh(usable)}`];
  const more = [];
  if (values.o2_used_l != null) more.push(`O₂ used ${values.o2_used_l.toFixed(1)} L (metabolic equivalent)`);
  if (values.rv_time_s != null) more.push(homeInText(values.rv_time_s));
  if (more.length) lines.push(more.join(' · '));
  return {used, rv, free, usable, usedPct: pct(used), rvPct: pct(rv), freePct: pct(free), lines,
          energyLeft: Math.round(usable - used)};
}

// Rows of the "plan against the walk" card for the adaptive walkback (X2, #129): the
// [label, plan, walked] rows of guide_core.adaptiveRows as the card's [label, text].
// A plan of "—" (nothing planned to compare with) is left out of the text.
export function adaptiveCardRows(rows) {
  return (rows || []).map(([label, plan, walked]) =>
    [label, plan === '—' ? walked : plan.includes('(') ? `${walked} · plan ${plan}` : `${walked} (plan ${plan})`]);
}

// What the RETURN NOW banner does after an answer of POST /walkback/update (X2, #129),
// with the tablet's rules: a solar storm owns the banner; on the way home there is
// nothing to add; it shows once and clears when the way home fits again.
//   returnNow  the answer's return_now;  storm  a storm alert is on;
//   home       the walked route is the way home;  showing  the banner is up now.
// Returns 'show', 'clear' or 'keep'.
export function kAlarmAction({returnNow, storm, home, showing}) {
  if (storm) return 'keep';
  if (returnNow && !home && !showing) return 'show';
  if (showing && (home || !returnNow)) return 'clear';
  return 'keep';
}

// The clock line of the player: the EVA clock, the leg and the distance. A way home or a
// rejoin is a new route that starts where the walker was, but the EVA clock goes on (#124):
//   evaStart   the EVA's start on the plan's clock (the planned route's start; by default
//              this route's own, which is right for the planned route)
//   homeStart  when the way home began (Return home or the solar storm), or null. The way
//              home is then a stretch of the EVA, from that moment to the habitat.
// "EVA 3:02 of 111:27 · outbound · 132 of 1392 m"; after a rejoin, the EVA's new end;
// on the way home, by the glossary's name, "EVA 102:04 · return home 2:02 of 2:51 · 120 of
// 160 m", and "EVA 2:05 · at the habitat" when the way home is a single point (pressed at
// the habitat, #115). This line is the rehearsal clock: the only text of the 3D in m:ss.
export function progressText(model, state, {evaStart = model.start, homeStart = null} = {}) {
  const eva = `EVA ${clock(state.time - evaStart)}`;
  const metres = `${state.distance.toFixed(0)} of ${model.length.toFixed(0)} m`;
  if (homeStart !== null && homeStart !== undefined) {
    if (!(model.length > 0)) return `${eva} · at the habitat`;
    return `${eva} · ${T.NAMES.returnHome.toLowerCase()} ${clock(state.time - homeStart)} of ` +
           `${clock(model.end - homeStart)} · ${metres}`;
  }
  const parts = [`${eva} of ${clock(model.end - evaStart)}`];
  if (model.assumedSpeed !== null) parts[0] += ` (assumed ${model.assumedSpeed.toFixed(0)} m/s)`;
  if (state.standing && state.stop) parts.push(`at ${state.stop.station ? state.stop.station.id : 'a stop'}`);
  else if (state.leg) parts.push(state.leg === 'return' ? 'returning' : 'outbound');
  parts.push(metres);
  return parts.join(' · ');
}

// The distance to the next maneuver as the arm tablet writes it, big (web/guide.html):
// guide_core's "in 350 m" as "350 m", and "now" as "Now".
export function maneuverDistance(distText) {
  return distText === 'now' ? 'Now' : String(distText ?? '').replace(/^in /, '');
}
