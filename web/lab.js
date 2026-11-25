// Laboratorio de metaheuristicas (web/lab.html). The pure functions at the top are tested
// with Node (tests/web/lab.test.mjs); the DOM is only touched inside initLab().

export const COLOURS = {dp: "#2a78d6", ils: "#eb6834", sa: "#1baf7a", aco: "#eda100",
                        ga: "#e87ba4", cpsat: "#6250d6"};      // same as analyze.COLOURS
export const LABELS = {dp: "DP (exacto)", cpsat: "CP-SAT (exacto)", ils: "ILS", sa: "SA",
                       aco: "ACO", ga: "GA"};
export const ORDER = ["dp", "ils", "sa", "aco", "ga", "cpsat"];
export const LIMITS = {dp: 18, cpsat: 60};                      // max nodes per exact solver

/** traces {alg: [{seed, t_s, best_prize}]} -> {alg: {seed: [[t, prize], ...]}} sorted by t. */
export function convergenceSeries(traces) {
  const out = {};
  for (const [alg, rows] of Object.entries(traces || {})) {
    const bySeed = {};
    for (const r of rows) {
      if (r.t_s == null || r.best_prize == null) continue;
      const key = r.seed == null ? "" : String(r.seed);
      (bySeed[key] ||= []).push([Number(r.t_s), Number(r.best_prize)]);
    }
    for (const pts of Object.values(bySeed)) pts.sort((a, b) => a[0] - b[0]);
    out[alg] = bySeed;
  }
  return out;
}

/** Linear map from domain [d0, d1] to range [r0, r1]; a degenerate domain maps to the middle. */
export function scale([d0, d1], [r0, r1]) {
  if (d1 === d0) return () => (r0 + r1) / 2;
  return v => r0 + ((v - d0) / (d1 - d0)) * (r1 - r0);
}

/** "x,y x,y ..." for the stations in routeIds order; `project(x, y) -> [px, py]` is optional. */
export function routePolyline(stations, routeIds, project = (x, y) => [x, y]) {
  const byId = new Map(stations.map(s => [s.id, s]));
  return routeIds.filter(id => byId.has(id)).map(id => {
    const s = byId.get(id);
    const [px, py] = project(s.x, s.y);
    return `${+px.toFixed(2)},${+py.toFixed(2)}`;
  }).join(" ");
}

/** runs.csv stores the route as ids joined by "-"; ids may contain "-", so match known ids. */
export function parseRoute(text, ids) {
  const known = new Set(ids), out = [];
  const parts = String(text || "").split("-").filter(p => p !== "");
  let i = 0;
  while (i < parts.length) {
    let found = false;
    for (let j = parts.length; j > i; j--) {            // longest known id first
      const cand = parts.slice(i, j).join("-");
      if (known.has(cand)) { out.push(cand); i = j; found = true; break; }
    }
    if (!found) i++;
  }
  return out;
}

const fmt = (v, d = 1) => v === "" || v == null || Number.isNaN(Number(v)) ? "–" : Number(v).toFixed(d);
const ENT = {"&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;"};
const esc = s => String(s ?? "").replace(/[&<>"']/g, c => ENT[c]);
const SVG = "http://www.w3.org/2000/svg";
const FIGS = {
  "fig1_convergence.png": ["Convergencia", "Mejor puntaje encontrado frente al tiempo, por algoritmo."],
  "fig2_quality_vs_time.png": ["Calidad frente a tiempo", "Brecha con la referencia frente al tiempo de cómputo."],
  "fig3_scalability.png": ["Escalabilidad", "Cómo crecen brecha y tiempo con el número de estaciones."],
  "fig4_gap_boxplots.png": ["Distribución de la brecha", "Cajas de la brecha (%) por algoritmo y tamaño de instancia."],
  "fig5_internal_dynamics.png": ["Dinámica interna", "Temperatura, aceptación y diversidad dentro de cada metaheurística."],
  "fig6_routes.png": ["Rutas", "La ruta que encuentra cada algoritmo sobre las mismas estaciones."],
  "fig7_performance_profile.png": ["Perfil de desempeño", "Fracción de instancias resueltas a cierta distancia del mejor."],
};

function el(name, attrs = {}, text) {
  const e = document.createElementNS(SVG, name);
  for (const [k, v] of Object.entries(attrs)) e.setAttribute(k, v);
  if (text != null) e.textContent = text;
  return e;
}

/** SVG line chart: best prize vs time, one polyline per (algorithm, seed). */
export function convergenceChart(series, runs) {
  const W = 640, H = 340, m = {l: 48, r: 14, t: 14, b: 40};
  const svg = el("svg", {viewBox: `0 0 ${W} ${H}`, role: "img",
    "aria-label": "Convergencia: mejor puntaje frente al tiempo, una línea por algoritmo y semilla"});
  const lines = [];
  for (const [alg, bySeed] of Object.entries(series)) {
    for (const [seed, pts0] of Object.entries(bySeed)) {
      const pts = pts0.slice();
      const run = runs.find(r => r.algorithm === alg && String(r.seed ?? "") === seed && r.status === "ok");
      if (run && run.runtime_s != null && run.runtime_s !== "") pts.push([Number(run.runtime_s), Number(run.prize)]);
      if (pts.length) lines.push({alg, seed, pts});
    }
  }
  if (!lines.length) {
    svg.append(el("text", {x: W / 2, y: H / 2, class: "axis", "text-anchor": "middle"}, "sin datos"));
    return svg;
  }
  const all = lines.flatMap(l => l.pts);
  const pos = all.map(p => p[0]).filter(t => t > 0), tmax = Math.max(...all.map(p => p[0]), 1e-3);
  const tmin = pos.length ? Math.min(...pos) : tmax / 10;
  const log = tmax / tmin > 100;                           // more than 2 decades
  const tx = log ? t => Math.log10(Math.max(t, tmin)) : t => t;
  const xs = scale(log ? [tx(tmin), tx(tmax)] : [0, tmax], [m.l, W - m.r]);
  const pmax = Math.max(...all.map(p => p[1]), 1);
  const ys = scale([0, pmax * 1.05], [H - m.b, m.t]);
  for (let i = 0; i <= 4; i++) {                           // y grid
    const v = (pmax * 1.05 * i) / 4, y = ys(v);
    svg.append(el("line", {x1: m.l, x2: W - m.r, y1: y, y2: y, class: "grid"}));
    svg.append(el("text", {x: m.l - 6, y: y + 4, class: "tick", "text-anchor": "end"}, v.toFixed(0)));
  }
  let ticks;
  if (log) {
    const a = Math.ceil(Math.log10(tmin)), b = Math.floor(Math.log10(tmax));
    ticks = Array.from({length: Math.max(b - a + 1, 0)}, (_, i) => 10 ** (a + i));
  } else ticks = [0, 1, 2, 3, 4].map(i => (tmax * i) / 4);
  for (const t of ticks) {
    svg.append(el("text", {x: xs(tx(t)), y: H - m.b + 16, class: "tick", "text-anchor": "middle"},
      t >= 1 ? t.toFixed(0) : String(+t.toPrecision(2))));
  }
  svg.append(el("text", {x: (m.l + W - m.r) / 2, y: H - 6, class: "axis", "text-anchor": "middle"},
    log ? "tiempo (s, escala log)" : "tiempo (s)"));
  const cy = (m.t + H - m.b) / 2;
  svg.append(el("text", {x: 12, y: cy, class: "axis", "text-anchor": "middle",
    transform: `rotate(-90 12 ${cy})`}, "mejor puntaje"));
  for (const l of lines) {
    const d = l.pts.map(([t, p]) => `${xs(tx(t)).toFixed(1)},${ys(p).toFixed(1)}`).join(" ");
    const pl = el("polyline", {points: d, fill: "none", stroke: COLOURS[l.alg] || "#888",
      "stroke-width": 1.8, "stroke-linejoin": "round", opacity: 0.9});
    pl.append(el("title", {}, `${LABELS[l.alg] || l.alg}${l.seed !== "" ? " semilla " + l.seed : ""}`));
    svg.append(pl);
    const [lt, lp] = l.pts[l.pts.length - 1];
    svg.append(el("circle", {cx: xs(tx(lt)).toFixed(1), cy: ys(lp).toFixed(1), r: 3, fill: COLOURS[l.alg] || "#888"}));
  }
  return svg;
}

/** Colour legend as HTML, in the fixed algorithm order. */
export function legend(algs) {
  return ORDER.filter(a => algs.includes(a)).map(a =>
    `<span class="key"><i style="background:${COLOURS[a]}"></i>${LABELS[a]}</span>`).join("");
}

/** Small multiples: the route of each algorithm (first run) over the stations. */
export function routeCharts(stations, runs) {
  const frag = document.createDocumentFragment();
  if (!stations.length) return frag;
  const xsAll = stations.map(s => s.x), ysAll = stations.map(s => s.y);
  const x0 = Math.min(...xsAll), x1 = Math.max(...xsAll), y0 = Math.min(...ysAll), y1 = Math.max(...ysAll);
  const span = Math.max(x1 - x0, y1 - y0, 1e-9), S = 200, pad = 12;
  const px = scale([x0, x0 + span], [pad, S - pad]), py = scale([y0, y0 + span], [S - pad, pad]);
  const project = (x, y) => [px(x), py(y)];
  const ids = stations.map(s => s.id);
  const first = {};
  for (const r of runs) if (r.status === "ok" && !(r.algorithm in first)) first[r.algorithm] = r;
  for (const alg of ORDER.filter(a => a in first)) {
    const r = first[alg];
    const fig = document.createElement("figure");
    const svg = el("svg", {viewBox: `0 0 ${S} ${S}`, role: "img",
      "aria-label": `Ruta de ${LABELS[alg]}: ${r.prize} puntos, ${r.n_visited} estaciones visitadas`});
    const poly = routePolyline(stations, parseRoute(r.route, ids), project);
    svg.append(el("polyline", {points: poly, fill: "none", stroke: COLOURS[alg], "stroke-width": 2,
      "stroke-linejoin": "round"}));
    for (const s of stations) {
      const [cx, cy] = project(s.x, s.y);
      if (s.type === "habitat" || s.id === "habitat") svg.append(el("rect", {x: cx - 4.5, y: cy - 4.5, width: 9, height: 9, class: "hab"}));
      else svg.append(el("circle", {cx, cy, r: 2.6, class: "st"}));
    }
    const cap = document.createElement("figcaption");
    cap.innerHTML = `<b>${esc(LABELS[alg])}</b> · ${fmt(r.prize, 0)} puntos`;
    fig.append(svg, cap);
    frag.append(fig);
  }
  return frag;
}

function referenceText(ref) {
  if (!ref || ref.prize == null) return "Referencia: no disponible.";
  const note = {
    dp_optimal: "óptimo probado por programación dinámica",
    cpsat_optimal: "óptimo probado por CP-SAT",
    best_known: "mejor conocido, no probado: ninguna cota cerró el problema, así que la brecha es respecto al mejor puntaje visto",
  }[ref.kind] || ref.kind;
  const ub = ref.upper_bound != null ? ` Cota superior: ${fmt(ref.upper_bound, 1)}.` : "";
  return `Referencia: ${fmt(ref.prize, 0)} puntos (${ref.kind}: ${note}).${ub}`;
}

export function initLab() {
  const $ = id => document.getElementById(id);
  const status = $("status"), errBox = $("error");
  const say = msg => { status.textContent = msg; };
  const fail = msg => { errBox.textContent = msg; errBox.hidden = !msg; };
  const getJSON = async url => {
    const res = await fetch(url);
    if (!res.ok) throw new Error(`${url}: ${res.status}`);
    return res.json();
  };

  // ---- Corridas ----
  let runs = [];
  async function showRun(id) {
    const runInfo = runs.find(r => r.id === id);
    const tbody = $("summary-body"), gallery = $("gallery"), dl = $("downloads");
    tbody.innerHTML = ""; gallery.innerHTML = ""; dl.innerHTML = "";
    $("run-meta").textContent = runInfo
      ? `${runInfo.instances} instancias · ${runInfo.rows} corridas · ${runInfo.has_analysis ? "con análisis" : "sin análisis (ejecuta orienteering.lab.analyze)"}` : "";
    if (!runInfo) return;
    const base = `/lab/runs/${encodeURIComponent(id)}/files/`;
    let algs = [];
    if (runInfo.has_analysis) {
      try {
        const rows = await getJSON(`/lab/runs/${encodeURIComponent(id)}/summary`);
        algs = [...new Set(rows.map(r => r.algorithm))];
        tbody.innerHTML = rows.map(r => `<tr><td>${esc(LABELS[r.algorithm] || r.algorithm)}</td><td>${esc(r.size_bucket)}</td>` +
          `<td class="n">${esc(r.runs)}</td><td class="n">${fmt(r.mean_gap_pct, 2)}</td><td class="n">${fmt(r.median_gap_pct, 2)}</td>` +
          `<td class="n">${fmt(r.optimal_share, 2)}</td><td class="n">${fmt(r.mean_runtime_s, 3)}</td></tr>`).join("")
          || `<tr><td colspan="7">Sin filas.</td></tr>`;
      } catch (e) { fail(`No se pudo cargar el resumen: ${e.message}`); }
    } else tbody.innerHTML = `<tr><td colspan="7">Esta corrida no tiene análisis.</td></tr>`;
    for (const f of runInfo.figures) {
      const [title, desc] = FIGS[f] || [f, "Figura del análisis."];
      const url = esc(`${base}analysis/${encodeURIComponent(f)}`);
      const fig = document.createElement("figure");
      fig.innerHTML = `<a href="${url}" target="_blank" rel="noopener"><img src="${url}" loading="lazy" ` +
        `alt="${esc(title)}: ${esc(desc)}"></a><figcaption><b>${esc(title)}.</b> ${esc(desc)} <span class="muted">(clic para ampliar)</span></figcaption>`;
      gallery.append(fig);
    }
    if (!runInfo.figures.length) gallery.innerHTML = `<p class="muted">Sin figuras para esta corrida.</p>`;
    const traces = ORDER.filter(a => algs.includes(a) && a !== "dp" && a !== "cpsat").map(a => `traces/trace_${a}.csv`);
    const files = ["runs.csv", "instances.csv", "config.json", "analysis/stats.csv", ...traces];
    dl.innerHTML = files.map(f => `<li><a href="${esc(base + f.split("/").map(encodeURIComponent).join("/"))}" download>${esc(f)}</a></li>`).join("");
  }

  async function loadRuns() {
    try {
      runs = await getJSON("/lab/runs");
      const sel = $("run-select");
      sel.innerHTML = runs.map(r => `<option value="${esc(r.id)}">${esc(r.id)} (${r.rows} corridas${r.has_analysis ? "" : ", sin análisis"})</option>`).join("");
      if (!runs.length) { $("run-meta").textContent = "Todavía no hay corridas guardadas."; return; }
      const pick = runs.find(r => r.has_analysis) || runs[0];
      sel.value = pick.id;
      await showRun(pick.id);
    } catch (e) { fail(`No se pudieron cargar las corridas: ${e.message}`); }
  }
  $("run-select").addEventListener("change", e => showRun(e.target.value));

  // ---- Ejecutar ----
  let instances = [];
  const algBoxes = () => [...document.querySelectorAll("#algs input[type=checkbox]")];
  function syncAlgs(first) {
    const inst = instances.find(i => i.name === $("instance").value);
    if (!inst) return;
    const notes = [];
    for (const b of algBoxes()) {
      const max = LIMITS[b.value], tooBig = max != null && inst.n > max;
      b.disabled = tooBig;
      if (tooBig) { b.checked = false; notes.push(`${LABELS[b.value]} solo hasta ${max} nodos (esta instancia tiene ${inst.n})`); }
      else if (first || b.dataset.wasOff) b.checked = true;
      b.dataset.wasOff = tooBig ? "1" : "";
    }
    $("alg-note").textContent = notes.join(" · ");
  }
  async function loadInstances() {
    try {
      instances = await getJSON("/lab/instances");
      const groups = {};
      for (const i of instances) (groups[i.set] ||= []).push(i);
      const known = ["synthetic", "real", "manual"];
      const order = known.filter(s => groups[s]).concat(Object.keys(groups).filter(s => !known.includes(s)));
      $("instance").innerHTML = order.map(s => `<optgroup label="${esc(s)}">` +
        groups[s].map(i => `<option value="${esc(i.name)}">${esc(i.name)} (n=${i.n})</option>`).join("") + `</optgroup>`).join("");
      const pref = instances.find(i => i.name === "real-n20-0-120min") || instances[0];
      if (pref) $("instance").value = pref.name;
      syncAlgs(true);
    } catch (e) { fail(`No se pudieron cargar las instancias: ${e.message}`); }
  }
  $("instance").addEventListener("change", () => syncAlgs(false));

  $("run-form").addEventListener("submit", async ev => {
    ev.preventDefault();
    const btn = $("run-btn");
    if (btn.getAttribute("aria-busy") === "true") return;
    fail("");
    const algorithms = algBoxes().filter(b => b.checked && !b.disabled).map(b => b.value);
    if (!algorithms.length) { fail("Elige al menos un algoritmo."); return; }
    const k = Math.min(5, Math.max(1, Math.floor(Number($("seeds").value) || 1)));
    btn.setAttribute("aria-busy", "true"); btn.textContent = "Ejecutando…";
    say("Ejecutando los algoritmos; puede tardar hasta un minuto.");
    try {
      const res = await fetch("/lab/solve", {method: "POST", headers: {"Content-Type": "application/json"},
        body: JSON.stringify({instance: $("instance").value, algorithms, seeds: Array.from({length: k}, (_, i) => i)})});
      if (!res.ok) {
        let d = res.statusText;
        try { const j = await res.json(); d = typeof j.detail === "string" ? j.detail : JSON.stringify(j.detail); } catch { /* keep statusText */ }
        throw new Error(`${res.status}: ${d}`);
      }
      renderResult(await res.json());
      say(`Listo: ${algorithms.length} algoritmos en ${$("instance").value}.`);
    } catch (e) { fail(`La ejecución falló. ${e.message}`); say("La ejecución falló."); }
    finally { btn.removeAttribute("aria-busy"); btn.textContent = "Ejecutar"; }
  });

  function renderResult(d) {
    $("live").hidden = false;
    $("live-title").textContent = `${d.instance} (n=${d.n}, ${d.set})`;
    $("reference").textContent = referenceText(d.reference);
    const rows = d.runs || [];
    $("live-body").innerHTML = rows.map(r => `<tr><td>${esc(LABELS[r.algorithm] || r.algorithm)}</td><td class="n">${esc(r.seed === "" || r.seed == null ? "–" : r.seed)}</td>` +
      `<td class="n">${fmt(r.prize, 0)}</td><td class="n">${fmt(r.gap_pct, 2)}</td><td class="n">${fmt(r.energy_wh, 2)}</td>` +
      `<td class="n">${fmt(r.distance_m, 0)}</td><td class="n">${esc(r.n_visited ?? "–")}</td><td class="n">${fmt(r.runtime_s, 3)}</td>` +
      `<td>${esc(r.status)}</td></tr>`).join("");
    const box = $("conv"); box.innerHTML = "";
    box.append(convergenceChart(convergenceSeries(d.traces), rows));
    $("conv-legend").innerHTML = legend(rows.map(r => r.algorithm));
    const rbox = $("routes"); rbox.innerHTML = "";
    rbox.append(routeCharts(d.stations || [], rows.filter(r => r.seed === "" || r.seed == null || Number(r.seed) === 0)));
    $("live").scrollIntoView({behavior: "smooth", block: "start"});
  }

  loadRuns(); loadInstances();
}

if (typeof document !== "undefined") initLab();
