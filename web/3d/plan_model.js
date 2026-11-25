// Plan model of the 3D map, with no dependencies (tested with `node --test`).
//
// Turns the GeoJSON of POST /plan (or GET /plan/last) into what the page draws.
// Rule: the page draws what the response contains, as is. Every optional field may
// be missing, and nothing here assumes a single goal, a round trip or a profile.
// Coordinates stay in Mars CRS metres (x east, y north) and in 64-bit numbers; the
// conversion to scene coordinates happens in overlays.js and markers.js.

export const PROFILE_KEYS = ['t_s', 'used_wh', 'rv_wh', 'rv_time_s', 'slack_wh', 'o2_used_l'];
export const ROUTE_COLOR = [0, 200, 255];           // the HUD's route colour
export const RETURN_COLOR = [255, 110, 220];        // return leg: far from cyan and from the ground
// Station colours by rubric type: the same as TYPE_COLORS in web/index.html.
export const TYPE_COLORS = {ridge: [255, 214, 10], hollow: [64, 160, 255],
                            contact: [180, 120, 255], curiosity: [0, 220, 140]};
export const UNKNOWN_COLOR = [200, 200, 200];
export const HABITAT_COLOR = [255, 255, 255];

const isXY = c => Array.isArray(c) && Number.isFinite(c[0]) && Number.isFinite(c[1]);
const numberOrNull = v => (typeof v === 'number' && Number.isFinite(v) ? v : null);

// GET /plan/last answers {request, plan}; POST /plan answers the FeatureCollection.
// Returns the FeatureCollection of either, or null.
export function featureCollectionOf(json) {
  if (json && Array.isArray(json.features)) return json;
  if (json && json.plan && Array.isArray(json.plan.features)) return json.plan;
  return null;
}

// Cumulative 2D length (metres) at each vertex of a list of [x, y].
export function cumulativeLength(coords) {
  const out = new Float64Array(coords.length);
  for (let i = 1; i < coords.length; i++) {
    out[i] = out[i - 1] + Math.hypot(coords[i][0] - coords[i - 1][0], coords[i][1] - coords[i - 1][1]);
  }
  return out;
}

function parseRoute(feature, notes) {
  const p = feature.properties || {}, coords = feature.geometry.coordinates;
  const kind = p.kind ?? 'line';
  if (!Array.isArray(coords) || coords.length < 2 || !coords.every(isXY)) {
    notes.push(`${kind}: line skipped (fewer than 2 vertices or a bad coordinate)`);
    return null;
  }
  const n = coords.length;
  // Profile arrays are kept only when they have one value per vertex.
  let profile = null;
  for (const key of PROFILE_KEYS) {
    if (p[key] == null) continue;
    if (Array.isArray(p[key]) && p[key].length === n) (profile ??= {})[key] = p[key];
    else notes.push(`${kind}: ${key} ignored (not one value per vertex)`);
  }
  let turnIndex = null;
  if (p.turn_index != null) {
    if (Number.isInteger(p.turn_index) && p.turn_index > 0 && p.turn_index < n - 1) turnIndex = p.turn_index;
    else notes.push(`${kind}: turn_index ${p.turn_index} ignored (outside the route)`);
  }
  // Stops of a multi-station tour (E5): vertex index and station id, in visiting order.
  const stops = [];
  if (Array.isArray(p.stop_index) && Array.isArray(p.visit_order) &&
      p.stop_index.length === p.visit_order.length) {
    p.stop_index.forEach((index, i) => {
      if (Number.isInteger(index) && index >= 0 && index < n) stops.push({index, id: String(p.visit_order[i])});
    });
  }
  const dist = cumulativeLength(coords);
  return {
    kind, coords, profile, turnIndex, stops,
    lengthM: dist[n - 1],                           // measured here, 2D
    totals: {length_m: numberOrNull(p.length_m), time_s: numberOrNull(p.time_s),
             energy_wh: numberOrNull(p.energy_wh), usable_wh: numberOrNull(p.usable_wh),
             o2_l: numberOrNull(p.o2_l), feasible: typeof p.feasible === 'boolean' ? p.feasible : null},
    properties: p,
  };
}

// FeatureCollection -> {routes, points, properties, warnings, notes}.
// `routes` holds every LineString (the planned route has kind 'route'); `points`
// every Point with its kind ('start', 'goal', 'station', ...). `notes` lists what was
// ignored and why, so a malformed field is reported instead of breaking the page.
export function parsePlan(fc) {
  const routes = [], points = [], notes = [];
  for (const f of (fc && Array.isArray(fc.features) ? fc.features : [])) {
    const g = f && f.geometry, p = (f && f.properties) || {};
    if (!g) continue;
    if (g.type === 'LineString') {
      const route = parseRoute(f, notes);
      if (route) routes.push(route);
    } else if (g.type === 'Point') {
      if (isXY(g.coordinates)) points.push({kind: p.kind ?? 'point', x: g.coordinates[0], y: g.coordinates[1], properties: p});
      else notes.push(`${p.kind ?? 'point'}: point skipped (bad coordinate)`);
    }
  }
  const properties = (fc && fc.properties) || {};
  const warnings = Array.isArray(properties.warnings) ? properties.warnings.map(String) : [];
  return {routes, points, properties, warnings, notes};
}

// The planned route of a parsed plan (the first line of kind 'route'), or null.
export const mainRoute = plan => plan.routes.find(r => r.kind === 'route') || null;

// The plan's messages (properties.warnings) as they are written in the API, and how the
// panel says them. The API writes them for the team, with project codes and engine names
// ("E5 tour: 8 of 13 stations, prize 37 (order R3 > R2 > …)", "service power assumed
// 205 W (E4 default)"). One that only says what the plan is, or how the planner made it,
// becomes a plain line with all its numbers (warn false); the 2D HUD keeps the first four
// out of its warnings too (PLAN_NOTES in web/index.html). One that may need a look stays a
// warning (warn true): a sample route that is not a plan, a feasibility it cannot tell.
const PLAN_MESSAGES = [
  // api/main.py _plan_tour (E5 tour)
  {re: /^E5 tour: (\d+) of (\d+) stations(?:, prize (\S+))?(?: \(order (.+)\))?$/,
   plain: (n, of, value, order) => [`${n} of ${of} stations visited`, value && `science value ${value}`,
                                    order && `order ${order.split(' > ').join(' → ')}`].filter(Boolean).join(' · ')},
  {re: /^not visited within the limits: (.+)$/, plain: ids => `Left out, they do not fit in the limits: ${ids}`},
  // api/main.py _plan_tour and _plan_live (E4 round trip)
  {re: /^service power assumed (\S+) W \(E4 default\)$/,
   plain: w => `Power used at the stations: ${w} W (the planner's default)`},
  {re: /^single-goal round trip to the best-scoring station ([^;]+?)(?:;.*)?$/,
   plain: id => `Round trip to ${id} (highest science value)`},
  // src/orienteering/tour.py and api/tour.py (E5)
  {re: /^O2 budget is the tighter limit: (\S+) Wh of (\S+) usable$/,
   plain: (o2, usable) => `Oxygen is the tighter limit: it allows ${o2} Wh of the ${usable} Wh usable`},
  {re: /^walkback: re-planned (\d+) time\(s\) with a lower budget$/,
   plain: n => `Planned again ${n} ${n === '1' ? 'time' : 'times'} with less energy, so the astronaut can get back from every point`},
  // api/main.py plan(): no stations and no goal
  {re: /^fixed test route \(Curiosity trajectory\)/, warn: true,
   plain: () => "Sample route (Curiosity's path), not a plan: add stations in the planner to plan a walk"},
  {re: /^service_energy_wh_per_min is null\b/, warn: true,
   plain: () => 'The energy for the work at the stations is not given, so the plan cannot be called energy-feasible'},
];

// The plan's messages as lines of the plan panel: [{text, warn}], in the API's order. A
// message not listed above is shown as the API wrote it, as a warning (a point the planner
// moved, a new message), so nothing is hidden.
export function planMessages(warnings) {
  return (Array.isArray(warnings) ? warnings : []).map(message => {
    const text = String(message);
    for (const {re, plain, warn = false} of PLAN_MESSAGES) {
      const m = re.exec(text);
      if (m) return {text: plain(...m.slice(1)), warn};
    }
    return {text, warn: true};
  });
}

// Split every segment so that no step is longer than maxStep metres. The original
// vertices are all kept. For every new vertex:
//   at[i]   fractional index into the original vertices (2.25 = a quarter of the way
//           from vertex 2 to vertex 3), to interpolate the profile with sampleAt();
//   dist[i] cumulative 2D length in metres.
export function densify(coords, maxStep = 1) {
  const x = [coords[0][0]], y = [coords[0][1]], at = [0], dist = [0];
  let done = 0;
  for (let i = 1; i < coords.length; i++) {
    const [x0, y0] = coords[i - 1], dx = coords[i][0] - x0, dy = coords[i][1] - y0;
    const length = Math.hypot(dx, dy);
    const pieces = Math.max(1, Math.ceil(length / maxStep - 1e-9));
    for (let j = 1; j <= pieces; j++) {
      const f = j / pieces;                         // exactly 1 at the original vertex
      x.push(x0 + dx * f); y.push(y0 + dy * f);
      at.push(i - 1 + f); dist.push(done + length * f);
    }
    done += length;
  }
  return {x: Float64Array.from(x), y: Float64Array.from(y), at: Float64Array.from(at),
          dist: Float64Array.from(dist), length: done};
}

// Value of a per-vertex array at a fractional index (linear between vertices).
export function sampleAt(values, f) {
  const last = values.length - 1, g = Math.min(last, Math.max(0, f)), i = Math.min(last - 1, Math.floor(g));
  return last === 0 ? values[0] : values[i] + (values[i + 1] - values[i]) * (g - i);
}

// Where a densified route turns back: {outbound: [first, last], back: [first, last]}
// as indices into the densified arrays (the turn vertex is in both legs). With no
// turn index the whole route is outbound and `back` is null.
export function splitAtTurn(dense, turnIndex) {
  const last = dense.at.length - 1;
  if (turnIndex == null) return {outbound: [0, last], back: null};
  let j = 0;
  while (j < last && dense.at[j] < turnIndex) j++;
  return {outbound: [0, j], back: [j, last]};
}

// Copy of the stretch [first, last] of a path shifted `offset` metres to the RIGHT of
// the direction of travel (x east, y north). Used for the return leg, so that it does
// not hide the outbound leg where both follow the same cells: each leg keeps to its
// right, like traffic. The direction is taken over +-`window` vertices so a zigzag of
// grid steps does not make the shifted line jitter, and the shift fades to zero over
// `taper` metres at both ends so the legs still meet at the turn and at the habitat.
export function offsetSideways(dense, [first, last], offset, {window = 3, taper = 4} = {}) {
  const n = last - first + 1, x = new Float64Array(n), y = new Float64Array(n);
  let nx = 0, ny = 0;
  for (let i = 0; i < n; i++) {
    const a = first + Math.max(0, i - window), b = first + Math.min(n - 1, i + window);
    const tx = dense.x[b] - dense.x[a], ty = dense.y[b] - dense.y[a], length = Math.hypot(tx, ty);
    if (length > 1e-9) { nx = ty / length; ny = -tx / length; }     // else keep the last one
    const p = first + i;
    const fade = taper > 0
      ? Math.min(1, (dense.dist[p] - dense.dist[first]) / taper, (dense.dist[last] - dense.dist[p]) / taper) : 1;
    x[i] = dense.x[p] + nx * offset * fade;
    y[i] = dense.y[p] + ny * offset * fade;
  }
  return {x, y};
}

// Markers of a parsed plan, for markers.js: [{id, x, y, kind, label, color, data}].
//   habitat  every 'start' point
//   goal     the station named by a 'goal' point (it keeps its own position and the
//            colour of its type), or the goal point itself when it names no station
//   station  every other 'station' point, coloured by type
//   (a 'stop' point, which the E5 tour writes on the route for every station it visits,
//   is not drawn apart when it names a station of the plan: that station's marker is it)
//   point    anything else, grey
// `stationTypes` ({id: type}, from GET /stations or the saved request) fills in the
// type when the response does not carry it.
export function planMarkers(plan, stationTypes = {}) {
  const out = [], used = new Set();
  const unique = base => {
    let id = base, n = 2;
    while (used.has(id)) id = `${base}#${n++}`;
    used.add(id);
    return id;
  };
  const stationIds = new Set(plan.points.filter(p => p.kind === 'station' && p.properties.id != null)
                                        .map(p => String(p.properties.id)));
  const goalStations = new Set(plan.points.filter(p => p.kind === 'goal' && p.properties.station != null)
                                          .map(p => String(p.properties.station)));
  for (const p of plan.points) {
    const props = p.properties;
    if (p.kind === 'start') {
      out.push({id: unique('habitat'), x: p.x, y: p.y, kind: 'habitat', label: 'Habitat',
                color: HABITAT_COLOR, data: props});
    } else if (p.kind === 'station') {
      const name = props.id != null ? String(props.id) : '';
      const type = props.type ?? stationTypes[name] ?? null;
      out.push({id: unique(name || 'station'), x: p.x, y: p.y,
                kind: goalStations.has(name) ? 'goal' : 'station', label: name,
                color: TYPE_COLORS[type] || UNKNOWN_COLOR, data: {...props, type}});
    } else if (p.kind === 'goal') {
      // A goal that names a station of this plan is shown on that station's marker.
      if (props.station != null && stationIds.has(String(props.station))) continue;
      out.push({id: unique('goal'), x: p.x, y: p.y, kind: 'goal', label: 'Goal',
                color: ROUTE_COLOR, data: props});
    } else if (p.kind === 'stop' && props.id != null && stationIds.has(String(props.id))) {
      continue;                                     // shown on that station's marker
    } else {
      out.push({id: unique(String(props.id ?? p.kind)), x: p.x, y: p.y, kind: 'point',
                label: String(props.id ?? p.kind), color: UNKNOWN_COLOR, data: props});
    }
  }
  return out;
}

// Keyboard list of the station pins: visiting order first, then the stations left out.
// Keep the marker itself so a button selects exactly what its pin would select. A plan
// without visit information keeps its input order; it must not invent an itinerary.
export function stationList(plan, stationTypes = {}, rubric = {}) {
  if (!plan) return [];
  const route = mainRoute(plan), visit = route?.properties.visit_order;
  const order = new Map((Array.isArray(visit) ? visit : []).map((id, i) => [String(id), i + 1]));
  const stations = planMarkers(plan, stationTypes).filter(m => m.data.kind === 'station');
  const hasGoal = stations.some(m => m.kind === 'goal');
  return stations.map(marker => {
    const d = marker.data;
    const n = order.get(marker.label) ??
      (Number.isInteger(d.order) && d.order > 0 ? d.order : marker.kind === 'goal' ? 1 : null);
    const unvisited = d.visited === false || (n === null && (Array.isArray(visit) || hasGoal));
    const name = d.name || rubric[d.type]?.label;
    const label = [n ?? (unvisited ? 'Not visited' : null), marker.label || 'Station', name]
      .filter(v => v != null && v !== '').join(' · ');
    return {id: marker.id, marker, label, order: n};
  }).sort((a, b) => (a.order ?? Infinity) - (b.order ?? Infinity));
}
