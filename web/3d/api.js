// Where the 3D page gets its plan (no three import: Node can test the pure parts).
//
//   loadLastPlan()        GET /plan/last: the last plan made in the 2D planner, saved
//                         by the server. This is all the page does by itself.
//   requestDefaultPlan()  POST /plan with the saved stations and the 2D planner's
//                         default limits, starting at the box centre. Only when the
//                         user asks (button, or ?plan=default): the server saves every
//                         plan it makes as the last plan, and the guide screen loads
//                         that one, so the page must never plan on its own.
//   loadRubric()          GET /stations/rubric: the type labels of the station cards.
//   requestWalkback()     POST /walkback: the 30 min line and the energy-safe boundary
//                         from a position. The server computes and answers; it saves
//                         nothing (api/main.py walkback(): return fields cached in
//                         memory, no file is written), so the rehearsal may ask freely.
//   loadDeparture()       GET /plan/departure?sol=: the best time to leave of the last
//                         plan, the line under the plan in the 2D planner (P6,
//                         api/departure.py). The server computes it (the terrain horizon
//                         of the route, about 1 s) and saves nothing, so the Sun asks for
//                         it by itself once a plan is drawn (sun.js).
// Whatever comes back is drawn as is (plan_model.js). With no plan the page keeps
// working with the terrain alone and says why.
import { featureCollectionOf } from './plan_model.js';

// Defaults of the inputs in web/index.html (requestPlan). No base is set in this
// page, so the start is the box centre, as in the 2D planner before a base is chosen.
export const DEFAULT_LIMITS = {
  energy_budget_wh: 1000, gravity_m_s2: 3.71, margin: 0.10, max_duration_min: 120,
  o2_budget_l: null, apollo_speed_uses_signed_slope: true, service_energy_wh_per_min: null,
  max_cell_slope_deg: 30,
};

// Body of the default POST /plan. `saved` is the answer of GET /stations ({rubric,
// stations}) or null. The score of a station is the rubric score of its type.
export function defaultPlanRequest(start, saved) {
  const rubric = (saved && saved.rubric) || {};
  const stations = ((saved && saved.stations) || []).map(s => ({
    id: s.id, x: s.x, y: s.y, type: s.type, score: Number(rubric[s.type] ?? 0),
    service_time_min: s.service_time_min ?? 0}));
  return {start: [start[0], start[1]], stations, ...DEFAULT_LIMITS};
}

// {id: type} of the stations in a GET /stations answer or in a saved plan request.
export function stationTypes(...sources) {
  const out = {};
  for (const src of sources) {
    for (const s of (src && Array.isArray(src.stations) ? src.stations : [])) {
      if (s && s.id != null && s.type != null) out[String(s.id)] = s.type;
    }
  }
  return out;
}

// FastAPI errors: {detail: "text"} or {detail: [{msg, loc}, ...]}.
function reason(status, body) {
  const d = body && body.detail;
  if (typeof d === 'string') return d;
  if (Array.isArray(d)) return d.map(e => e.msg || JSON.stringify(e)).join('; ');
  return `HTTP ${status}`;
}

async function request(fetchFn, url, init) {
  try {
    const res = await fetchFn(url, init);
    let body = null;
    try { body = await res.json(); } catch { /* not JSON */ }
    return {ok: res.ok, status: res.status, body, error: res.ok ? null : reason(res.status, body)};
  } catch (err) {
    return {ok: false, status: 0, body: null, error: `no answer from the server (${err.message})`};
  }
}

// Both functions return {fc, source, error, missing, stationTypes, request}:
//   fc       the FeatureCollection to draw, or null
//   source   'last' (GET /plan/last), 'default' (POST /plan) or null
//   missing  true when the server has no saved plan yet (404): not an error
//   error    why there is no plan, when fc is null and it is not just missing
const nothing = (error, missing, saved, body = null) =>
  ({fc: null, source: null, error, missing, request: body, stationTypes: stationTypes(saved)});

async function savedStations(fetchFn) {
  const res = await request(fetchFn, '/stations');
  return res.ok ? res.body : null;
}

export async function loadLastPlan({fetchFn = fetch} = {}) {
  const saved = await savedStations(fetchFn);
  const last = await request(fetchFn, '/plan/last');
  const fc = last.ok ? featureCollectionOf(last.body) : null;
  if (fc) {
    return {fc, source: 'last', error: null, missing: false, request: last.body.request || null,
            stationTypes: stationTypes(saved, last.body.request)};
  }
  if (last.status === 404) return nothing(null, true, saved);
  return nothing(`saved plan: ${last.ok ? 'the answer has no features' : last.error}`, false, saved);
}

// Makes the server plan, and save the result as the last plan: call it only on an
// explicit request of the user.
export async function requestDefaultPlan({start, fetchFn = fetch} = {}) {
  const saved = await savedStations(fetchFn);
  const body = defaultPlanRequest(start, saved);
  const res = await request(fetchFn, '/plan', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                              body: JSON.stringify(body)});
  const fc = res.ok ? featureCollectionOf(res.body) : null;
  if (fc) {
    return {fc, source: 'default', error: null, missing: false, request: body,
            stationTypes: stationTypes(saved, body)};
  }
  return nothing(`default request: ${res.ok ? 'the answer has no features' : res.error}`, false, saved, body);
}

// Station rubric {type: {label, score, why}}, or {} when the server does not answer.
export async function loadRubric({fetchFn = fetch} = {}) {
  const res = await request(fetchFn, '/stations/rubric');
  return res.ok && res.body && typeof res.body === 'object' ? res.body : {};
}

// Body of POST /walkback for a point of a plan, as the 2D planner sends it on pause
// (requestWalkback in web/index.html), with the limits the plan was made with.
//   properties  the plan's own properties (max_cell_slope_deg, human_cost, habitat)
//   base        the habitat [x, y], or null for the server's default (the box centre)
export function walkbackRequest({x, y, energyLeftWh, base = null, properties = {}}) {
  const body = {current_position: [x, y], energy_remaining_wh: Math.max(0, energyLeftWh),
                emergency_return_time_s: 1800, base: base ? [base[0], base[1]] : null};
  if (properties.max_cell_slope_deg !== undefined) body.max_cell_slope_deg = properties.max_cell_slope_deg;
  if (typeof properties.human_cost === 'boolean') body.human_cost = properties.human_cost;
  return body;
}

// Returns {fc, error}: the FeatureCollection of the answer, or why there is none.
export async function requestWalkback(body, {fetchFn = fetch} = {}) {
  const res = await request(fetchFn, '/walkback', {method: 'POST', headers: {'Content-Type': 'application/json'},
                                                  body: JSON.stringify(body)});
  const fc = res.ok ? featureCollectionOf(res.body) : null;
  return {fc, error: fc ? null : (res.ok ? 'the answer has no features' : res.error)};
}

// The answer of GET /plan/departure for a sol, or null: no saved plan (404), a route with
// no clock or a sol the server refuses (422), no server. sun_model.bestDeparture() reads
// the time out of it.
export async function loadDeparture(sol, {fetchFn = fetch} = {}) {
  const res = await request(fetchFn, `/plan/departure?sol=${encodeURIComponent(sol)}`);
  return res.ok ? res.body : null;
}
