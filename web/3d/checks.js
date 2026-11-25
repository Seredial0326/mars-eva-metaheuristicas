// Reproducible checks of the 3D map, run in the browser with ?check=<name>.
// They print a JSON result on the page; the numbers go into paper/notes/P1_3d_map.md.
import * as THREE from 'three';
import { SOL_IN_SECONDS, sunPosition } from './mars_sun.js';

function correlation(x, y) {
  const n = x.length;
  let mx = 0, my = 0;
  for (let i = 0; i < n; i++) { mx += x[i]; my += y[i]; }
  mx /= n; my /= n;
  let sxy = 0, sxx = 0, syy = 0;
  for (let i = 0; i < n; i++) {
    sxy += (x[i] - mx) * (y[i] - my); sxx += (x[i] - mx) ** 2; syy += (y[i] - my) ** 2;
  }
  return Number((sxy / Math.sqrt(sxx * syy)).toFixed(3));
}

// ?check=shading : is the terrain lit from the right side?
//
// Renders the terrain without the photo, seen from straight above, four times: lit
// from the north, south, east and west. The north-minus-south image must follow the
// north-facing slope of the surface being shaded, low + k * detail (same for east
// minus west). If the normal map were mirrored or inverted, the correlation with the
// "detail flipped" surface would be the high one instead.
export function shadingCheck({terrain, scene, renderer, sun, sunDirection, shadows}) {
  const N = 250, block = terrain.n / N, k = terrain.k;
  const cast = shadows.enabled;
  shadows.set(false);                                      // the shading alone is measured
  const target = new THREE.WebGLRenderTarget(N, N);
  const camera = new THREE.OrthographicCamera(-terrain.half, terrain.half, terrain.half, -terrain.half, 1, 20000);
  camera.position.set(0, 8000, 0);
  camera.up.set(0, 0, -1);                                 // north at the top of the image
  camera.lookAt(0, 0, 0);

  const hemi = scene.children.find(o => o.isHemisphereLight);
  const saved = {fog: scene.fog, sun: sun.intensity, hemi: hemi.intensity, pos: sun.position.clone(),
                 maps: terrain.materials.map(m => m.map)};
  // Only the terrain is measured: hide the route, the markers and the rotation ring.
  const hidden = scene.children.filter(o => o !== terrain.group && !o.isLight && o.visible);
  hidden.forEach(o => { o.visible = false; });
  scene.fog = null;
  sun.intensity = 1.2;                                     // dim enough not to clip at 255
  hemi.intensity = 0.3;
  terrain.materials.forEach(m => { m.map = null; m.needsUpdate = true; });

  const shot = azimuth => {
    sun.position.copy(sunDirection(azimuth, 35)).multiplyScalar(5000);
    renderer.setRenderTarget(target);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    const rgba = new Uint8Array(N * N * 4);
    renderer.readRenderTargetPixels(target, 0, 0, N, N, rgba);     // rows from the south
    return Float32Array.from({length: N * N}, (_, i) => rgba[i * 4 + 1]);
  };
  const [north, south, east, west] = [0, 180, 90, 270].map(shot);

  const {n, step, low, detail} = terrain;
  const slope = (a, i, j) => {                             // [d/dEast, d/dNorth]
    const jm = Math.max(0, j - 1), jp = Math.min(n - 1, j + 1);
    const im = Math.max(0, i - 1), ip = Math.min(n - 1, i + 1);
    return [(a[i * n + jp] - a[i * n + jm]) / ((jp - jm) * step),
            (a[im * n + j] - a[ip * n + j]) / ((ip - im) * step)];
  };
  const c = {ns: [], ew: [], okN: [], flipN: [], lowN: [], okE: [], flipE: [], lowE: []};
  for (let py = 2; py < N - 2; py++) {
    for (let px = 2; px < N - 2; px++) {
      let le = 0, ln = 0, de = 0, dn = 0;
      for (let a = 0; a < block; a++) {
        for (let b = 0; b < block; b++) {
          const i = (N - 1 - py) * block + a, j = px * block + b;
          const gl = slope(low, i, j), gd = slope(detail, i, j);
          le += gl[0]; ln += gl[1]; de += gd[0]; dn += gd[1];
        }
      }
      const m = block * block, p = py * N + px;
      le /= m; ln /= m; de /= m; dn /= m;
      c.ns.push(north[p] - south[p]); c.ew.push(east[p] - west[p]);
      c.okN.push(-(ln + k * dn)); c.flipN.push(-(ln - k * dn)); c.lowN.push(-ln);
      c.okE.push(-(le + k * de)); c.flipE.push(-(le - k * de)); c.lowE.push(-le);
    }
  }

  scene.fog = saved.fog; sun.intensity = saved.sun; hemi.intensity = saved.hemi;
  sun.position.copy(saved.pos);
  hidden.forEach(o => { o.visible = true; });
  terrain.materials.forEach((m, i) => { m.map = saved.maps[i]; m.needsUpdate = true; });
  shadows.set(cast);
  target.dispose();

  const mean = a => Number((a.reduce((s, v) => s + v, 0) / a.length).toFixed(2));
  return {
    check: 'shading', quality: terrain.quality, mesh_step_m: step, exaggeration: k,
    north_minus_south: {correct: correlation(c.ns, c.okN), detail_flipped: correlation(c.ns, c.flipN),
                        hillside_only: correlation(c.ns, c.lowN)},
    east_minus_west: {correct: correlation(c.ew, c.okE), detail_flipped: correlation(c.ew, c.flipE),
                      hillside_only: correlation(c.ew, c.lowE)},
    mean_brightness: {north: mean(north), south: mean(south), east: mean(east), west: mean(west)},
  };
}

// ?check=route : is the route on the ground, as long as the plan says, and are the
// markers where the plan puts them?
//
// For k = 1, 3 and 5 it measures the height of the drawn route above the drawn terrain
// at every vertex of the drawn line and at three points inside every segment (a straight
// segment would dip under a convex crease of the mesh if the line were not cut at the
// triangle edges). The terrain height used is terrain.surfaceAt(); to show that it is
// the mesh that is really drawn, vertical rays are cast against the triangles at about
// 20 vertices spread along each leg and compared with it.
export function routeCheck({terrain, overlays, markers, plan, setRelief}) {
  const round = (v, d = 3) => Number(v.toFixed(d));
  const out = {check: 'route', quality: terrain.quality, mesh_step_m: terrain.step, lift_m: overlays.lift,
               source: plan && plan.source, legs: overlays.legs.map(l => ({name: l.name, route_vertices: l.x.length, drawn_vertices: l.ground.length / 2}))};
  if (!overlays.legs.length) return {...out, error: 'no route drawn'};
  const startK = terrain.k, raycaster = new THREE.Raycaster(), down = new THREE.Vector3(0, -1, 0);
  out.clearance_m = [1, 3, 5].map(k => {
    setRelief(k);
    let atVertex = Infinity, inside = Infinity, rayError = 0, rays = 0;
    for (const {positions: p} of overlays.legs) {
      const n = p.length / 3, every = Math.max(1, Math.floor(n / 20));
      for (let i = 0; i < n; i++) {
        const X = p[i * 3], Y = p[i * 3 + 1], Z = p[i * 3 + 2];
        atVertex = Math.min(atVertex, Y - terrain.surfaceAt(X, Z));
        if (i % every === 0) {
          raycaster.set(new THREE.Vector3(X, 10000, Z), down);
          const hit = raycaster.intersectObjects(terrain.group.children, false)[0];
          if (hit) { rayError = Math.max(rayError, Math.abs(hit.point.y - terrain.surfaceAt(X, Z))); rays++; }
        }
        if (i === n - 1) continue;
        for (const f of [0.25, 0.5, 0.75]) {
          const x = X + (p[i * 3 + 3] - X) * f, y = Y + (p[i * 3 + 4] - Y) * f, z = Z + (p[i * 3 + 5] - Z) * f;
          inside = Math.min(inside, y - terrain.surfaceAt(x, z));
        }
      }
    }
    return {k: terrain.k, min_at_vertices: round(atVertex), min_inside_segments: round(inside),
            rays, max_ray_vs_surfaceAt: round(rayError, 6)};
  });
  setRelief(startK);

  // 2D length of what is drawn (both legs, the return one with its sideways shift)
  // against the length the plan declares.
  let drawn = 0;
  for (const {positions: p} of overlays.legs) {
    for (let i = 3; i < p.length; i += 3) drawn += Math.hypot(p[i] - p[i - 3], p[i + 2] - p[i - 1]);
  }
  const route = plan && plan.model && plan.model.routes.find(r => r.kind === 'route');
  const declared = route ? route.totals.length_m : null;
  out.length_m = {drawn: round(drawn, 1), declared, vertices_2d: route ? round(route.lengthM, 1) : null,
                  drawn_vs_declared_pct: declared ? round(100 * (drawn - declared) / declared, 2) : null};

  // Markers: scene position back to Mars metres against the marker's own coordinates,
  // and height above the ground (the habitat label stands on its dome).
  let offset = 0, above = 0;
  for (const item of markers.items) {
    const [x, y] = terrain.toMars(item.position[0], item.position[2]);
    offset = Math.max(offset, Math.hypot(x - item.marker.x, y - item.marker.y));
    if (!item.dome) above = Math.max(above, Math.abs(item.sprite.position.y - terrain.surfaceAt(item.position[0], item.position[2])));
  }
  out.markers = {count: markers.items.length, kinds: markers.items.map(i => i.marker.kind).join(' '),
                 max_position_error_m: round(offset, 6), max_height_off_ground_m: round(above, 6)};
  return out;
}

// ?check=rehearse : does the rehearsal camera walk the route as it should, and does
// leaving the rehearsal put everything back?
//
// Enters the rehearsal and walks the whole route on the real terrain in steps of 0.1 s
// of plan time (under 0.1 m), in first person: height of the eye above the drawn ground
// under it, largest move of the camera in one step, fastest turn of the heading per
// metre walked (the turn on the spot at a stop is reported apart), and distance of the
// camera from the true route (against every segment of it). Then the chase view every
// second; then real playback at x60 through update(), to see it pause at each stop
// with its card; then exit, twice, comparing camera, relief and scene with before.
// Nothing is asked from the server (the walkback lines on pause are switched off).
export function rehearseCheck({terrain, scene, camera, controls, rehearsal, plan}) {
  const round = (v, d = 3) => Number(v.toFixed(d));
  const model = rehearsal.model, route = plan && plan.model && plan.model.routes.find(r => r.kind === 'route');
  const out = {check: 'rehearse', quality: terrain.quality, mesh_step_m: terrain.step, source: plan && plan.source};
  if (!model || !route) return {...out, error: 'no route to rehearse'};
  const snapshot = () => ({
    position: camera.position.toArray(), quaternion: camera.quaternion.toArray(), fov: camera.fov, near: camera.near,
    k: terrain.k, yaw: controls.yaw, pitch: controls.pitch, enabled: controls.enabled,
    children: scene.children.map(o => o.name || o.type).join(' '),
    label: document.getElementById('relief-label').textContent, slider: document.getElementById('relief').disabled,
    player: document.getElementById('player').hidden, card: document.getElementById('card').hidden});
  const before = snapshot(), walkbackOnPause = rehearsal.walkbackOnPause, DEG = Math.PI / 180;
  const turnOf = (a, b) => { let d = Math.abs(a - b) % (2 * Math.PI); return (d > Math.PI ? 2 * Math.PI - d : d) / DEG; };
  rehearsal.walkbackOnPause = false;
  rehearsal.enter();
  out.route = {vertices: route.coords.length, length_m: round(model.length, 1), duration_s: round(model.duration, 1),
               time_base: model.assumedSpeed === null ? 'profile t_s' : `assumed ${model.assumedSpeed} m/s`,
               stops: model.stops.map(s => ({vertex: s.index, station: s.station && s.station.id,
                                             arrive_s: round(s.arrive, 1), wait_s: round(s.waitS, 1)}))};
  out.while_rehearsing = {relief_k: terrain.k, relief_label: document.getElementById('relief-label').textContent,
                          slider_disabled: document.getElementById('relief').disabled, near_m: camera.near,
                          fov_deg: camera.fov, controls_enabled: controls.enabled};

  // First person, every 0.1 s of plan time.
  const first = {steps: 0, eye_min_m: Infinity, eye_max_m: 0, max_move_m: 0, max_turn_deg_per_m: 0,
                 max_turn_on_the_spot_deg: 0, max_off_route_m: 0};
  const c = route.coords;
  let prev = null;
  for (let time = model.start; ; time = Math.min(model.end, time + 0.1)) {
    rehearsal.seek(time);
    const s = rehearsal.state, p = camera.position, eye = p.y - terrain.surfaceAt(p.x, p.z);
    first.eye_min_m = Math.min(first.eye_min_m, eye); first.eye_max_m = Math.max(first.eye_max_m, eye);
    const [x, y] = terrain.toMars(p.x, p.z);
    let off = Infinity;
    for (let i = 1; i < c.length; i++) {
      const ax = c[i - 1][0], ay = c[i - 1][1], dx = c[i][0] - ax, dy = c[i][1] - ay, len2 = dx * dx + dy * dy;
      const f = len2 > 0 ? Math.min(1, Math.max(0, ((x - ax) * dx + (y - ay) * dy) / len2)) : 0;
      off = Math.min(off, Math.hypot(x - ax - dx * f, y - ay - dy * f));
    }
    first.max_off_route_m = Math.max(first.max_off_route_m, off);
    if (prev) {
      const walked = s.distance - prev.distance, turn = turnOf(rehearsal.pose.yaw, prev.yaw);
      first.max_move_m = Math.max(first.max_move_m, p.distanceTo(prev.p));
      const atStop = s.standing || prev.standing ||
        model.stops.some(stop => [stop.arrive, stop.leave].some(t => t > prev.time - 1e-9 && t < s.time + 1e-9));
      if (atStop || walked < 1e-9) first.max_turn_on_the_spot_deg = Math.max(first.max_turn_on_the_spot_deg, turn);
      else first.max_turn_deg_per_m = Math.max(first.max_turn_deg_per_m, turn / walked);
    }
    prev = {p: p.clone(), yaw: rehearsal.pose.yaw, distance: s.distance, standing: s.standing, time: s.time};
    first.steps++;
    if (time >= model.end) break;
  }
  out.first_person = Object.fromEntries(Object.entries(first).map(([key, v]) => [key, round(v)]));

  // Chase view, every second.
  rehearsal.setChase(true);
  const chase = {steps: 0, camera_min_above_ground_m: Infinity, to_walker_min_m: Infinity, to_walker_max_m: 0, walker_shown: true};
  for (let time = model.start; time <= model.end; time += 1) {
    rehearsal.seek(time);
    const p = camera.position, w = rehearsal.walker.position;
    chase.camera_min_above_ground_m = Math.min(chase.camera_min_above_ground_m, p.y - terrain.surfaceAt(p.x, p.z));
    chase.to_walker_min_m = Math.min(chase.to_walker_min_m, p.distanceTo(w));
    chase.to_walker_max_m = Math.max(chase.to_walker_max_m, p.distanceTo(w));
    chase.walker_shown = chase.walker_shown && rehearsal.walker.visible && scene.children.includes(rehearsal.walker);
    chase.steps++;
  }
  out.chase = Object.fromEntries(Object.entries(chase).map(([key, v]) => [key, typeof v === 'number' ? round(v) : v]));
  rehearsal.setChase(false);

  // Real playback: x60, 60 updates per second of screen time, pressing play again at each stop.
  rehearsal.seek(model.start);
  rehearsal.speed = 60;
  const playback = {updates: 0, pauses: [], needs_render_while_paused: 0};
  rehearsal.update(0);
  playback.needs_render_while_paused += rehearsal.update(1 / 60) ? 1 : 0;      // paused, nothing touched: no frame
  rehearsal.play();
  while (playback.updates < 1e5) {
    rehearsal.update(1 / 60);
    playback.updates++;
    if (rehearsal.playing) continue;
    const s = rehearsal.state, card = document.querySelector('#card .card-title');
    playback.pauses.push({time_s: round(s.time, 1), vertex: round(s.at, 2), distance_m: round(s.distance, 1),
                          card: document.getElementById('card').hidden ? null : card && card.textContent,
                          text: document.getElementById('rh-progress').textContent});
    if (s.time >= model.end) break;
    rehearsal.play();
  }
  out.playback_x60 = playback;

  // Leave, and do it all once more: nothing may be left behind.
  rehearsal.exit();
  const after1 = snapshot();
  rehearsal.enter(); rehearsal.setChase(true); rehearsal.seek((model.start + model.end) / 2); rehearsal.exit();
  const after2 = snapshot();
  rehearsal.walkbackOnPause = walkbackOnPause;
  const same = after => ({
    camera_moved_m: round(Math.hypot(...after.position.map((v, i) => v - before.position[i])), 9),
    camera_turned: round(Math.max(...after.quaternion.map((v, i) => Math.abs(v - before.quaternion[i]))), 9),
    rest_equal: ['fov', 'near', 'k', 'yaw', 'pitch', 'enabled', 'children', 'label', 'slider', 'player', 'card']
      .every(key => after[key] === before[key])});
  out.after_exit = {once: same(after1), twice: same(after2), relief_k: after2.k, fov_deg: after2.fov, near_m: after2.near,
                    scene: after2.children, listeners_left: rehearsal._listeners.length};
  return out;
}

// ?check=sun : is the scene lit by the Sun of Mars of the chosen sol and time?
//
// For 07:00, 12:00, 15:00, 17:00 and 21:00 local true solar time of the page's sol: the
// Sun's azimuth and elevation computed here again with mars_sun.js from the instant
// the page says, the direction of the light in the scene against the unit vector of
// that azimuth and elevation, the light levels and what the panel says. Then, with
// "Relief only" on, the terrain is rendered from straight above with the page's own
// lights at 07:00 and at 17:00: slopes facing east must be the bright ones in the
// morning and the dark ones in the afternoon. Then the photo is put back and compared
// with before, and the rehearsal is entered to see the Sun advance with the EVA clock
// and return to the start on exit. Everything is left as it was found. Cast shadows are
// off while it runs (they have their own check): the slopes' own shading is measured.
export function sunCheck({terrain, scene, renderer, sun, sunView, rehearsal, shadows}) {
  const round = (v, d = 3) => Number(v.toFixed(d)), text = id => document.getElementById(id).textContent;
  const out = {check: 'sun', quality: terrain.quality, exaggeration: terrain.k};
  if (!sunView.state) return {...out, error: 'the light is fixed by ?light=: the Sun is not used'};
  const hemi = scene.children.find(o => o.isHemisphereLight);
  const before = {start: {...sunView.start}, reliefOnly: sunView.reliefOnly, shadows: shadows.enabled};
  const site = sunView.site, sol = before.start.sol;
  shadows.set(false);
  out.site = {lon_east_deg: round(site.lonEastDeg, 4), lat_planetocentric_deg: round(site.latCentricDeg, 4),
              lat_planetographic_deg: round(site.latDeg, 4)};
  out.sol = sol;

  // Light direction, levels and panel at five times of the sol.
  out.times = [7, 12, 15, 17, 21].map(hours => {
    sunView.set({hours});
    const s = sunView.state, p = sunPosition(s.utcMs, site);
    const az = THREE.MathUtils.degToRad(p.azimuth), el = THREE.MathUtils.degToRad(p.elevation);
    const want = new THREE.Vector3(Math.sin(az) * Math.cos(el), Math.sin(el), -Math.cos(az) * Math.cos(el));
    const light = sun.position.clone().sub(sun.target.position).normalize();
    return {local_true_solar_time: text('sun-time-text'), utc: new Date(s.utcMs).toISOString(), ls_deg: round(p.ls, 2),
            ltst_h: round(p.ltst, 5), azimuth_deg: round(p.azimuth, 2), elevation_deg: round(p.elevation, 2),
            light_off_the_sun_deg: round(THREE.MathUtils.radToDeg(light.angleTo(want)), 6),
            light_from: light.x > 0.1 ? 'east' : light.x < -0.1 ? 'west' : 'meridian',
            sun_light: round(sun.intensity), sky_light: round(hemi.intensity),
            sky_colour: `#${scene.background.getHexString()}`, panel: text('sun-readout')};
  });

  // Relief only, from above, with the page's own lights: 07:00 against 17:00.
  const maps = terrain.materials.map(m => m.map), colours = terrain.materials.map(m => m.color.getHex());
  sunView.setReliefOnly(true);
  const N = 250, block = terrain.n / N, k = terrain.k;
  const target = new THREE.WebGLRenderTarget(N, N);
  const camera = new THREE.OrthographicCamera(-terrain.half, terrain.half, terrain.half, -terrain.half, 1, 20000);
  camera.position.set(0, 8000, 0);
  camera.up.set(0, 0, -1);                                 // north at the top of the image
  camera.lookAt(0, 0, 0);
  const hidden = scene.children.filter(o => o !== terrain.group && !o.isLight && o.visible);
  hidden.forEach(o => { o.visible = false; });
  const fog = scene.fog;
  scene.fog = null;
  const shot = hours => {
    sunView.set({hours});
    renderer.setRenderTarget(target);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    const rgba = new Uint8Array(N * N * 4);
    renderer.readRenderTargetPixels(target, 0, 0, N, N, rgba);     // rows from the south
    return Float32Array.from({length: N * N}, (_, i) => rgba[i * 4 + 1]);
  };
  const morning = shot(7), afternoon = shot(17);
  scene.fog = fog;
  hidden.forEach(o => { o.visible = true; });
  target.dispose();

  // East-facing slope of the shaded surface (low + k * detail), mean of each block.
  const {n, step, low, detail} = terrain;
  const eastward = (a, i, j) => {
    const jm = Math.max(0, j - 1), jp = Math.min(n - 1, j + 1);
    return -(a[i * n + jp] - a[i * n + jm]) / ((jp - jm) * step);
  };
  const diff = [], facing = [], side = {east: [0, 0, 0], west: [0, 0, 0]};
  let clipped = 0;
  for (let py = 2; py < N - 2; py++) {
    for (let px = 2; px < N - 2; px++) {
      let e = 0;
      for (let a = 0; a < block; a++) {
        for (let b = 0; b < block; b++) {
          const i = (N - 1 - py) * block + a, j = px * block + b;
          e += eastward(low, i, j) + k * eastward(detail, i, j);
        }
      }
      e /= block * block;
      const q = py * N + px;
      diff.push(morning[q] - afternoon[q]);
      facing.push(e);
      if (morning[q] >= 255 || afternoon[q] >= 255) clipped++;
      const bin = e > 0.1 ? side.east : e < -0.1 ? side.west : null;       // steeper than 1 in 10
      if (bin) { bin[0] += morning[q]; bin[1] += afternoon[q]; bin[2]++; }
    }
  }
  const means = b => ({pixels: b[2], at_07: round(b[0] / b[2], 1), at_17: round(b[1] / b[2], 1)});
  out.relief_only_from_above = {
    morning_minus_afternoon_vs_east_facing_slope: correlation(diff, facing),
    mean_brightness_east_facing: means(side.east), mean_brightness_west_facing: means(side.west),
    clipped_pixels: clipped, photo_hidden: terrain.materials.every(m => m.map === null)};

  sunView.setReliefOnly(false);
  out.photo_back = {tiles: maps.length, same_textures: terrain.materials.every((m, i) => m.map === maps[i]),
                    same_colours: terrain.materials.every((m, i) => m.color.getHex() === colours[i])};

  // Rehearsal: the Sun follows the EVA clock from 15:00 and goes back on exit.
  sunView.set({hours: 15});
  const start = {...sunView.state}, model = rehearsal.model;
  if (model) {
    const walkbackOnPause = rehearsal.walkbackOnPause;
    rehearsal.walkbackOnPause = false;
    rehearsal.enter();
    const moved = elapsed => {
      rehearsal.seek(model.start + elapsed);
      const s = sunView.state;
      return {eva_s: round(elapsed, 1), sun_advanced_s: round((s.utcMs - start.utcMs) / 1000, 3),
              local_time_advanced_min: round((s.ltst - start.ltst) * 60, 3),
              expected_min: round(elapsed / SOL_IN_SECONDS * 1440, 3), panel_time: text('sun-time-text'),
              elevation_deg: round(s.elevation, 2), azimuth_deg: round(s.azimuth, 2),
              controls_disabled: document.getElementById('sun-time').disabled && document.getElementById('sun-sol').disabled,
              note: text('sun-note')};
    };
    out.rehearsal = {duration_s: round(model.duration, 1), at: [0, 600, model.duration].map(moved)};
    rehearsal.exit();
    rehearsal.walkbackOnPause = walkbackOnPause;
    const s = sunView.state;
    out.rehearsal.after_exit = {sun_back_at_start: s.utcMs === start.utcMs && s.elevation === start.elevation,
                                panel_time: text('sun-time-text'), elevation_deg: round(s.elevation, 2),
                                controls_disabled: document.getElementById('sun-time').disabled};
  } else {
    out.rehearsal = {error: 'no route to rehearse'};
  }

  sunView.set(before.start);
  sunView.setReliefOnly(before.reliefOnly);
  shadows.set(before.shadows);
  return out;
}

// ?check=shadows : are the cast shadows where the terrain puts them?
//
// At 07:00, 15:00 and 17:00 of sol 4711, at relief x1 and x5, with "Relief only" on, the
// terrain is rendered from straight above three times with the page's own lights:
// without shadows, with them, and with the sun light off. A pixel is "in shadow" when
// the shadows take away more than half of the sun light it had; pixels that the sun
// light does not reach anyway (slopes shaded as facing away) cannot tell and are left
// out. Independently, for the ground point of every pixel, a ray is marched towards the
// Sun over terrain.surfaceAt (the drawn triangles): the point is in shadow when the
// ground rises above the ray. The march starts as far from the point as the shadow
// map's bias, which is the same rule by another route; how much more ground is shaded
// when the march starts at the point itself (single facets shading themselves) is
// reported apart. The two answers are compared over all pixels and away from the shadow
// edges (the computed answer is the same all around the pixel, three texels of the
// shadow map or more). The same march with the Sun mirrored east-west says which side
// the shadows fall to: the rendered shadows must be the true Sun's, not the mirrored
// one's (at x1 only: at x5 the hollows are shaded from both sides).
// Two views: the whole block (5 m pixels) and, at 07:00 and 17:00, a close-up of 200 m
// at the box centre (0.5 m pixels, finer than a texel). Acne or stripes on sunlit
// ground would show there as shadow drawn where none is computed, or as sunlit pixels
// that get darker at all when the shadows are switched on (by 2 levels of 255 or more:
// the same frame drawn twice can differ by 1).
// The camera of the shadow map is also checked with three.js' own matrices: the block's
// corners must fall inside it. Everything is left as it was found.
export function shadowsCheck({terrain, scene, renderer, sun, sunView, shadows, setRelief}) {
  const round = (v, d = 3) => Number(v.toFixed(d));
  const out = {check: 'shadows', quality: terrain.quality, mesh_step_m: terrain.step, map_size: shadows.mapSize,
               bias_texels: shadows.biasTexels, sol: 4711};
  if (!sunView.state) return {...out, error: 'the light is fixed by ?light=: the Sun is not used'};
  const before = {start: {...sunView.start}, reliefOnly: sunView.reliefOnly, k: terrain.k, shadows: shadows.enabled};
  const N = 400, half = terrain.half, MIN_DIRECT = 8;
  const target = new THREE.WebGLRenderTarget(N, N);
  // Only the terrain is measured: hidden objects cast no shadow either.
  const hidden = scene.children.filter(o => o !== terrain.group && !o.isLight && o.visible);
  hidden.forEach(o => { o.visible = false; });
  const fog = scene.fog;
  scene.fog = null;
  sunView.setReliefOnly(true);
  const shot = camera => {
    renderer.setRenderTarget(target);
    renderer.render(scene, camera);
    renderer.setRenderTarget(null);
    const rgba = new Uint8Array(N * N * 4);
    renderer.readRenderTargetPixels(target, 0, 0, N, N, rgba);     // rows from the south
    return Float32Array.from({length: N * N}, (_, i) => rgba[i * 4 + 1]);
  };

  // Distance along the ray from the ground point (X, Z) towards `dir` at which the
  // ground first rises above it, looking between `from` and `to` metres; 0 if it never does.
  const blockedAt = (X, Z, dir, from, to, stride, top) => {
    const y0 = terrain.surfaceAt(X, Z);
    for (let s = from; s <= to; s += stride) {
      const x = X + dir[0] * s, z = Z + dir[2] * s, y = y0 + dir[1] * s;
      if (y > top || Math.abs(x) > half || Math.abs(z) > half) return 0;
      if (y < terrain.surfaceAt(x, z)) return s;
    }
    return 0;
  };

  // view: {name, x, z, span}: a square of `span` metres centred on scene (x, z).
  const measure = (k, hours, view) => {
    const pixel = view.span / N;
    const camera = new THREE.OrthographicCamera(-view.span / 2, view.span / 2, view.span / 2, -view.span / 2, 1, 20000);
    camera.position.set(view.x, 8000, view.z);
    camera.up.set(0, 0, -1);                               // north at the top of the image
    camera.lookAt(view.x, 0, view.z);
    sunView.set({sol: 4711, hours});
    const s = sunView.state, dir = s.direction;
    shadows.set(false);
    const open = shot(camera), level = sun.intensity;
    sun.intensity = 0;
    const ambient = shot(camera);
    sun.intensity = level;
    shadows.set(true);
    const drawn = shadows.updates, cast = shot(camera);

    // The camera of the shadow map, with three.js' own matrices.
    const light = sun.shadow.camera, ndc = {xy: 0, zMin: Infinity, zMax: -Infinity};
    for (const x of [-half, half]) for (const y of [shadows.block.yMin, shadows.block.yMax]) for (const z of [-half, half]) {
      const p = new THREE.Vector3(x, y, z).project(light);
      ndc.xy = Math.max(ndc.xy, Math.abs(p.x), Math.abs(p.y));
      ndc.zMin = Math.min(ndc.zMin, p.z); ndc.zMax = Math.max(ndc.zMax, p.z);
    }

    // The independent answer, for the centre of every pixel.
    const top = shadows.block.yMax, stride = terrain.step / 2, bias = shadows.biasM;
    const mirrored = [-dir[0], dir[1], dir[2]];
    const far = new Float32Array(N * N), near = new Uint8Array(N * N), flipped = new Uint8Array(N * N);
    for (let py = 0; py < N; py++) {
      for (let px = 0; px < N; px++) {
        const X = view.x - view.span / 2 + (px + 0.5) * pixel, Z = view.z + view.span / 2 - (py + 0.5) * pixel, p = py * N + px;
        far[p] = blockedAt(X, Z, dir, bias, Infinity, stride, top);
        near[p] = far[p] > 0 || blockedAt(X, Z, dir, 0.01, bias, 0.1, top) > 0 ? 1 : 0;
        if (k === 1) flipped[p] = blockedAt(X, Z, mirrored, bias, Infinity, stride, top) > 0 ? 1 : 0;
      }
    }

    // Away from the edges: the computed answer is the same within R pixels all around.
    const R = Math.max(2, Math.ceil(3 * Math.max(shadows.texel.across, shadows.texel.along) / pixel));
    const c = {seen: 0, rendered: 0, computed: 0, agree: 0, inside: 0, insideAgree: 0, insideLit: 0, falseShadow: 0,
               insideDark: 0, missed: 0, dimmed: 0, computedAll: 0, nearAll: 0, both: 0, bothFlipped: 0, distance: 0};
    for (let py = 0; py < N; py++) {
      for (let px = 0; px < N; px++) {
        const p = py * N + px, dark = far[p] > 0;
        c.computedAll += dark; c.nearAll += near[p];
        const direct = open[p] - ambient[p];
        if (direct < MIN_DIRECT) continue;                 // the sun light does not reach it anyway
        const shaded = cast[p] - ambient[p] < 0.5 * direct;
        c.seen++; c.rendered += shaded; c.computed += dark; c.agree += shaded === dark;
        if (shaded && dark) { c.both++; c.distance += far[p]; }
        if (shaded && flipped[p]) c.bothFlipped++;
        let edge = px < R || py < R || px >= N - R || py >= N - R;
        for (let a = -R; a <= R && !edge; a++) for (let b = -R; b <= R; b++) if ((far[p + a * N + b] > 0) !== dark) { edge = true; break; }
        if (edge) continue;
        c.inside++; c.insideAgree += shaded === dark;
        if (dark) { c.insideDark++; c.missed += !shaded; } else { c.insideLit++; c.falseShadow += shaded; c.dimmed += open[p] - cast[p] >= 2; }
      }
    }
    const share = (a, b) => (b ? round(a / b, 4) : null), flat = Math.hypot(dir[0], dir[2]);
    return {
      view: view.name, pixel_m: pixel, relief_k: k, local_true_solar_time: document.getElementById('sun-time-text').textContent,
      sun: {azimuth_deg: round(s.azimuth, 2), elevation_deg: round(s.elevation, 2)},
      shadow_map: {drawn_once: shadows.updates === drawn + 1, width_m: round(shadows.fit.width, 1),
                   height_m: round(shadows.fit.height, 1), texel_across_m: round(shadows.texel.across),
                   texel_along_m: round(shadows.texel.along), bias_m: round(bias),
                   corners_inside: ndc.xy <= 1 && ndc.zMin >= -1 && ndc.zMax <= 1,
                   corners_max_xy: round(ndc.xy, 4), corners_depth: [round(ndc.zMin, 4), round(ndc.zMax, 4)]},
      pixels: N * N, sun_light_reaches: share(c.seen, N * N),
      in_shadow: {rendered: share(c.rendered, c.seen), computed: share(c.computed, c.seen),
                  computed_all_pixels: share(c.computedAll, N * N),
                  computed_from_the_point_itself_all_pixels: share(c.nearAll, N * N)},
      agreement: {all: share(c.agree, c.seen), away_from_edges: share(c.insideAgree, c.inside),
                  edge_pixels_each_way: R, pixels_away_from_edges: c.inside,
                  sunlit_pixels_away_from_edges: c.insideLit, of_them_drawn_in_shadow: c.falseShadow,
                  of_them_darker_at_all: c.dimmed,
                  shaded_pixels_away_from_edges: c.insideDark, of_them_drawn_sunlit: c.missed},
      // Which Sun explains the rendered shadows: share of them that the march also shades.
      rendered_shadow_pixels: c.rendered,
      explained_by: {the_sun: share(c.both, c.rendered), the_sun_mirrored_east_west: k === 1 ? share(c.bothFlipped, c.rendered) : null},
      // From a shadowed point (by both answers) to the ground that blocks its sunlight.
      to_the_blocking_ground: {east: round(dir[0] / flat), north: round(-dir[2] / flat),
                               mean_distance_m: c.both ? round(c.distance / c.both, 1) : null},
      shadows_fall_towards: dir[0] < 0 ? 'east' : 'west',
    };
  };

  const started = performance.now();
  const block = {name: 'whole block', x: 0, z: 0, span: terrain.size}, closeUp = {name: 'close-up at the box centre', x: 0, z: 0, span: 200};
  out.cases = [];
  for (const k of [1, 5]) {
    setRelief(k);
    for (const hours of [7, 15, 17]) out.cases.push(measure(k, hours, block));
    for (const hours of [7, 17]) out.cases.push(measure(k, hours, closeUp));
  }
  out.seconds = round((performance.now() - started) / 1000, 1);

  scene.fog = fog;
  hidden.forEach(o => { o.visible = true; });
  target.dispose();
  setRelief(before.k);
  sunView.set(before.start);
  sunView.setReliefOnly(before.reliefOnly);
  shadows.set(before.shadows);
  return out;
}

// ?check=guide : does the rehearsal carry the arm-tablet guide (web/guide_core.js)?
// Enters the rehearsal and reads the maneuver banner and the three meters at the start,
// in the middle and at the end; then asks the server, as the buttons do, for a way home
// from the middle, a demo detour that rejoins the route, and the solar storm; then exits
// and checks that the planned route is back. Voice is switched off (no sound).
export async function guideCheck({rehearsal}) {
  const el = id => document.getElementById(id);
  const out = {check: 'guide'};
  if (!rehearsal.model) return {...out, error: 'no route to rehearse'};
  rehearsal.walkbackOnPause = false;
  const voiceWas = rehearsal.voice.on;
  rehearsal.voice.set(false);
  rehearsal.enter();
  const m = rehearsal.model, planned = {vertices: rehearsal.guide ? rehearsal.guide.coords.length : 0, end_s: m.end};
  const read = () => ({maneuver: `${el('rh-man-arrow').textContent} ${el('rh-man-text').textContent} ${el('rh-man-dist').textContent}`,
                       energy: el('rh-v-energy').textContent, back: el('rh-v-back').textContent,
                       eva: el('rh-eva-track').hidden ? null : el('rh-v-eva').textContent,
                       banner_shown: !el('rh-man').hidden, meters_shown: !el('rh-meters').hidden});
  out.has_guide = Boolean(rehearsal.guide);
  out.events = rehearsal.guide ? rehearsal.guide.events.length : 0;
  out.start = read();
  rehearsal.seek((m.start + m.end) / 2); out.middle = read();
  rehearsal.seek(m.end); out.end = read();
  rehearsal.seek((m.start + m.end) / 2);
  const home = await rehearsal.returnHome();
  out.return_home = home ? {vertices: rehearsal.guide.coords.length, kind: rehearsal.guide.kind,
                            starts_at_s: Math.round(rehearsal.model.start), text: home.text,
                            drawn: rehearsal._extra.length === 1, now: read()} : el('rh-note').textContent;
  rehearsal.exit(); rehearsal.enter();
  rehearsal.seek((m.start + m.end) / 3);
  await rehearsal.detour();
  out.detour = {kind: rehearsal.guide.kind, vertices: rehearsal.guide.coords.length, note: el('rh-note').textContent,
                drawn: rehearsal._extra.length === 1};
  rehearsal.exit(); rehearsal.enter();
  rehearsal.seek((m.start + m.end) / 2);
  await rehearsal.solarStorm();
  rehearsal.pause(false);
  out.storm = {alert: el('rh-alert').textContent.replace(/\s+/g, ' ').trim(), kind: rehearsal.guide.kind};
  rehearsal.exit();
  out.after_exit = {end_s: rehearsal.model.end, back_to_plan: rehearsal.model.end === planned.end_s};
  rehearsal.walkbackOnPause = true;
  rehearsal.voice.set(voiceWas);                 // as the user had it
  return out;
}

// Rover photos (P3): does the photo view put the camera where the Navcam was, at true
// relief, under the photo's Sun, with the photo on the centred square that spans the
// camera's field; and does Exit give back camera, relief, Sun and field exactly? For
// three photos of different sols (?ids=a,b,c to choose them). It measures the mechanics;
// whether the photo and the terrain agree is judged from the pictures and
// src/viz3d/photo_skyline.py.
async function photosCheck(viz) {
  const {photos, controls, camera, terrain, sunView} = viz;
  const el = id => document.getElementById(id), DEG = Math.PI / 180;
  if (!photos) return {error: 'no rover photos loaded', note: el('photos-note').textContent};
  const {photoPose, squareView, sunOf} = await import('./photos_model.js');
  // Pauses on a timer and the flight stepped here, as the frame loop would: a hidden page
  // draws no frames, and nothing measured needs a picture.
  const frames = n => new Promise(done => setTimeout(done, 50 * n));
  const landed = async () => { for (let i = 0; i < 100 && controls._flight; i++) controls.update(0.05); };
  const wrap = deg => ((deg + 540) % 360) - 180;
  const asked = (new URLSearchParams(location.search).get('ids') || '').split(',').filter(Boolean);
  const ids = asked.length ? asked : (() => {
    const bySol = new Map();
    for (const p of photos.model.photos) if (p.available && !bySol.has(p.sol)) bySol.set(p.sol, p.id);
    const sols = [...bySol.keys()].sort((a, b) => a - b);
    return [sols[0], sols[Math.floor(sols.length / 2)], sols[sols.length - 1]].map(s => bySol.get(s));
  })();
  const before = {pose: controls.pose(), k: terrain.k, sun: {...sunView.start}};
  const out = {photos: photos.model.photos.length, stops: viz.photoMarkers.items.length,
               problems: photos.model.problems.length, views: []};
  for (const id of ids) {
    const photo = photos.model.byId.get(id);
    if (!photo) { out.views.push({id, error: 'not in the catalogue'}); continue; }
    if (!photos.enter(id)) { out.views.push({id, error: 'the photo view did not open'}); continue; }
    await landed();
    await frames(2);
    const [X, Z] = terrain.toLocal(photo.x, photo.y);
    const inside = Math.abs(X) <= terrain.half && Math.abs(Z) <= terrain.half;
    const want = photoPose(photo, inside ? terrain.elevation(terrain.surfaceAt(X, Z, 1)) : null);
    const [x, y] = terrain.toMars(controls.position[0], controls.position[2]);
    const ground = terrain.surfaceAt(controls.position[0], controls.position[2], 1);
    const canvas = viz.renderer.domElement, square = squareView(canvas.clientWidth, canvas.clientHeight);
    const img = el('photo-overlay'), r = img ? img.getBoundingClientRect() : null, c = canvas.getBoundingClientRect();
    const sun = sunOf(photo, sunView.site.lonEastDeg);
    out.views.push({
      id, sol: photo.sol, pose_ok: want.ok, reason: want.reason,
      eye_height_m: +(controls.position[1] - ground).toFixed(3),
      expected_eye_height_m: want.eyeHeight === null ? null : +want.eyeHeight.toFixed(3),
      position_error_m: +Math.hypot(x - photo.x, y - photo.y).toFixed(3),
      heading_error_deg: +wrap((controls.yaw - photo.heading) / DEG).toFixed(4),
      pitch_error_deg: +((controls.pitch - photo.pitch) / DEG).toFixed(4),
      fov_error_deg: +(camera.fov - square.fovY).toFixed(4),
      relief_k: terrain.k,
      sun_set: {sol: sunView.start.sol, hours: +sunView.start.hours.toFixed(4)},
      sun_expected: {sol: sun.sol, hours: +sun.hours.toFixed(4)},
      overlay_px_error: r ? +Math.max(Math.abs(r.left - c.left - square.left), Math.abs(r.top - c.top - square.top),
                                      Math.abs(r.width - square.side), Math.abs(r.height - square.side)).toFixed(2) : null,
      overlay_loaded: Boolean(img && img.complete && img.naturalWidth === 768),
    });
  }
  photos.exit();
  await frames(2);
  const now = controls.pose();
  out.after_exit = {
    position_m: +Math.hypot(...now.position.map((v, i) => v - before.pose.position[i])).toFixed(6),
    yaw_deg: +((now.yaw - before.pose.yaw) / DEG).toFixed(6),
    pitch_deg: +((now.pitch - before.pose.pitch) / DEG).toFixed(6),
    fov_deg: +(now.fov - before.pose.fov).toFixed(6),
    relief_back: terrain.k === before.k,
    sun_back: sunView.start.sol === before.sun.sol && sunView.start.hours === before.sun.hours,
    bar_gone: !el('photo-bar') || el('photo-bar').hidden || !document.body.contains(el('photo-bar')),
  };
  return out;
}

// Station photo previews (P3 block 3): for every station of the plan, the nearest rover
// photo (or the explicit "none near"), as its card shows it; then the rehearsal's stop
// cards: the preview is in the card, and showing it changes neither the clock nor the
// walker, nor what the card already said.
async function stationsCheck(viz) {
  const {photos, markers, rehearsal, terrain} = viz;
  const el = id => document.getElementById(id);
  if (!photos) return {error: 'no rover photos loaded', note: el('photos-note').textContent};
  const {nearestPhoto, PREVIEW_MAX_M} = await import('./photos_model.js');
  const stations = markers.items.map(it => it.marker).filter(m => m.kind === 'station' || m.kind === 'goal');
  const out = {plan_source: viz.plan ? viz.plan.source : null, stations: stations.length, max_distance_m: PREVIEW_MAX_M,
               with_photo: 0, in_field: 0, without_photo: 0, cards: []};
  for (const m of stations) {
    const [X, Z] = terrain.toLocal(m.x, m.y);
    const r = nearestPhoto(photos.model, {x: m.x, y: m.y},
                           {groundElevation: terrain.elevation(terrain.surfaceAt(X, Z, 1))});
    markers.select(m);
    const card = el('card'), media = card.querySelector('.card-media');
    const buttons = [...card.querySelectorAll('.card-action')].map(b => b.textContent);
    if (r.photo) { out.with_photo++; if (r.inField) out.in_field++; } else out.without_photo++;
    out.cards.push({station: m.label, photo: r.photo ? r.photo.id : null,
                    distance_m: r.photo ? +r.distanceM.toFixed(1) : null,
                    off_axis_deg: r.photo ? +r.offAxisDeg.toFixed(1) : null, in_field: r.photo ? r.inField : null,
                    nearest_m: r.photo ? null : (r.nearestM === null ? null : +r.nearestM.toFixed(0)),
                    card_text: media ? media.textContent.replace(/\s+/g, ' ').trim() : null,
                    view_button: buttons.includes('View the rover photo')});
  }
  viz.redraw();
  // The rehearsal: seek to each stop (that shows its card), compare before and after.
  // A pause on a timer, not on frames: a hidden page draws none, and nothing here needs one.
  const frames = () => new Promise(done => setTimeout(done, 100));
  if (rehearsal.model) {
    rehearsal.enter();
    out.rehearsal = [];
    for (const stop of rehearsal.model.stops) {
      const t = stop.arrive + 1;
      rehearsal.seek(t);
      const card = el('card'), media = card.querySelector('.card-media');
      const walker = rehearsal.camera.position.toArray();
      await frames();                            // the card stays up: nothing may move meanwhile
      out.rehearsal.push({station: stop.station ? stop.station.id : null, card_shown: !card.hidden,
                          photo_in_card: Boolean(media), clock_kept: Math.abs(rehearsal.time - t) < 1e-9,
                          playing: rehearsal.playing,
                          tasks_kept: card.textContent.includes('Done, continue'),
                          view_button: [...card.querySelectorAll('.card-action')].some(b => b.textContent === 'View the rover photo'),
                          walker_kept: walker.every((v, i) => Math.abs(v - rehearsal.camera.position.toArray()[i]) < 1e-9),
                          photo_pins_hidden: !viz.photoMarkers.group.visible});
    }
    rehearsal.exit();
  }
  return out;
}

// ?check=walk : does "Walk freely" (issue #109) move at the speeds it says, keep the eye
// 1.7 m over the ground, stay inside the box and out of the habitat dome, turn with the
// mouse or a finger, and does leaving put everything back?
//
// Drives the mode by hand at 60 updates per second of time, through the same handlers
// as a person: keys as keyboard events on the window, the arrow pad as pointer events on
// its buttons, looking as a touch drag on the view (a captured mouse cannot be faked:
// both end in the same look() of walk_model.js). After every update in first person, the
// eye's height above the drawn ground under it. Nothing is asked from the server.
export function walkCheck({terrain, scene, camera, controls, walk, overlays, markers, photoMarkers}) {
  const round = (v, d = 3) => Number(v.toFixed(d)), DEG = Math.PI / 180;
  const out = {check: 'walk', quality: terrain.quality, mesh_step_m: terrain.step};
  const ui = id => document.getElementById(id);
  const snapshot = () => ({
    position: camera.position.toArray(), quaternion: camera.quaternion.toArray(), fov: camera.fov, near: camera.near,
    k: terrain.k, yaw: controls.yaw, pitch: controls.pitch, enabled: controls.enabled,
    children: scene.children.map(o => o.name || o.type).join(' '),
    label: ui('relief-label').textContent, slider: ui('relief').disabled, bar: ui('walk-bar').hidden,
    walking: document.body.classList.contains('walking'), route: overlays.group.visible,
    photos: photoMarkers.group.visible, button: ui('walk').textContent});
  const before = snapshot();
  const key = (code, down, init = {}) => window.dispatchEvent(new KeyboardEvent(down ? 'keydown' : 'keyup', {code, bubbles: true, ...init}));
  const tap = code => { key(code, true); key(code, false); };
  const eye = {min: Infinity, max: 0, max_off_true_scale_m: 0};
  // Hold for `seconds` of time; returns the horizontal distance walked.
  const hold = seconds => {
    const from = [...walk.position];
    for (let i = 0; i < Math.round(seconds * 60); i++) {
      walk.update(1 / 60);
      if (walk.chase) continue;
      const p = camera.position, h = p.y - terrain.surfaceAt(p.x, p.z);
      eye.min = Math.min(eye.min, h); eye.max = Math.max(eye.max, h);
      eye.max_off_true_scale_m = Math.max(eye.max_off_true_scale_m, Math.abs(p.y - terrain.surfaceAt(p.x, p.z, 1) - 1.7));
    }
    return Math.hypot(walk.position[0] - from[0], walk.position[1] - from[1]);
  };

  walk.enter();
  const habitat = markers.items.find(it => it.marker.kind === 'habitat');
  const toHabitat = () => habitat ? round(Math.hypot(walk.position[0] - habitat.position[0], walk.position[1] - habitat.position[2]), 2) : null;
  out.start = {habitat: Boolean(habitat), from_habitat_centre_m: toHabitat(), heading_deg: round(walk.yaw / DEG, 1),
               to_route_m: walk.toRoute === null ? null : round(walk.toRoute, 2)};
  out.while_walking = {relief_k: terrain.k, relief_label: ui('relief-label').textContent, slider_disabled: ui('relief').disabled,
                       near_m: camera.near, fov_deg: camera.fov, controls_enabled: controls.enabled,
                       route_lines_shown: overlays.group.visible, photo_pins_shown: photoMarkers.group.visible,
                       ground_paths: walk.ground.children.filter(o => o.name === 'walk path').length,
                       station_marks: walk.ground.children.filter(o => o.name === 'walk station').length,
                       walker_in_scene: scene.children.includes(walk.walker), bar_shown: !ui('walk-bar').hidden};

  // Speeds: 10 s with W, then with Shift, then fast travel (F) for 3 s; W + D together;
  // S backwards; the pad's forward button for 2 s.
  const speeds = {};
  key('KeyW', true); speeds.walk_m_s = round(hold(10) / 10); key('KeyW', false);
  key('ShiftLeft', true); key('KeyW', true, {shiftKey: true}); speeds.run_m_s = round(hold(10) / 10);
  key('KeyW', false, {shiftKey: true}); key('ShiftLeft', false);
  tap('KeyF'); key('ArrowUp', true); speeds.fast_m_s = round(hold(3) / 3); key('ArrowUp', false); tap('KeyF');
  speeds.fast_off_after_second_f = !walk.fast;
  key('KeyW', true); key('KeyD', true); speeds.diagonal_m_s = round(hold(5) / 5); key('KeyW', false); key('KeyD', false);
  key('KeyS', true); speeds.backwards_m_s = round(hold(5) / 5); key('KeyS', false);
  const pad = document.querySelector('#walk-pad [data-walk="forward"]');
  pad.dispatchEvent(new PointerEvent('pointerdown', {pointerId: 91, bubbles: true}));
  speeds.pad_forward_m_s = round(hold(2) / 2);
  pad.dispatchEvent(new PointerEvent('pointerup', {pointerId: 91, bubbles: true}));
  speeds.stops_when_released_m = round(hold(1), 6);
  speeds.no_frame_when_still = !walk.update(1 / 60);
  out.speeds = speeds;
  out.to_route_after_walking_m = walk.toRoute === null ? null : round(walk.toRoute, 2);
  out.readout = walk.positionText();

  // Looking: a touch drag of 100 px to the left turns the view right by the same angle
  // the free-flight and rehearsal drags use; huge drags stop at the pitch limit.
  const canvas = walk.canvas, drag = (dx, dy) => {
    canvas.dispatchEvent(new PointerEvent('pointerdown', {pointerId: 92, pointerType: 'touch', clientX: 400, clientY: 300, bubbles: true}));
    canvas.dispatchEvent(new PointerEvent('pointermove', {pointerId: 92, pointerType: 'touch', clientX: 400 + dx, clientY: 300 + dy, bubbles: true}));
    canvas.dispatchEvent(new PointerEvent('pointerup', {pointerId: 92, pointerType: 'touch', clientX: 400 + dx, clientY: 300 + dy, bubbles: true}));
    walk.update(1 / 60);
  };
  const yaw0 = walk.yaw;
  drag(-100, 0);
  let turned = (walk.yaw - yaw0) / DEG;
  turned = ((turned + 540) % 360) - 180;
  out.look = {drag_100px_left_turns_deg: round(turned, 3),
              expected_deg: round(100 * camera.fov / canvas.clientHeight, 3)};
  drag(0, 20000); out.look.pitch_up_limit_deg = round(walk.pitch / DEG, 3);
  drag(0, -40000); out.look.pitch_down_limit_deg = round(walk.pitch / DEG, 3);
  drag(0, 40000 - 20000 * 0); walk.pitch = 6 * DEG; walk.update(0);

  // The box: from 30 m inside each edge, 5 s of fast travel straight out (100 m).
  const half = terrain.half, edges = {east: [[half - 30, 0], 90], west: [[-(half - 30), 0], -90],
                                       north: [[0, -(half - 30)], 0], south: [[0, half - 30], 180]};
  out.box = {half_m: half};
  let farthest = 0;
  walk.setFast(true);
  for (const [name, [p, heading]] of Object.entries(edges)) {
    walk.position = p; walk.yaw = heading * DEG;
    key('KeyW', true);
    for (let i = 0; i < 300; i++) {
      walk.update(1 / 60);
      farthest = Math.max(farthest, Math.abs(walk.position[0]), Math.abs(walk.position[1]));
    }
    key('KeyW', false);
    out.box[`${name}_edge_left_m`] = round(half - Math.max(Math.abs(walk.position[0]), Math.abs(walk.position[1])), 6);
  }
  out.box.farthest_from_centre_m = round(farthest, 6);
  out.box.eye_after_m = round(camera.position.y - terrain.surfaceAt(camera.position.x, camera.position.z), 6);

  // The habitat dome: from 30 m west of it, 3 s of fast travel straight at its centre.
  if (habitat) {
    walk.position = [habitat.position[0] - 30, habitat.position[2]]; walk.yaw = 90 * DEG;
    let closest = Infinity;
    key('KeyW', true);
    for (let i = 0; i < 180; i++) { walk.update(1 / 60); closest = Math.min(closest, toHabitat()); }
    key('KeyW', false);
    out.dome = {closest_to_centre_m: round(closest, 6), limit_m: 4.3};
  }
  walk.setFast(false);

  // The view from behind (C), then first person again.
  tap('KeyC');
  walk.update(1 / 60);
  const w = walk.walker.position, p = camera.position;
  out.chase = {on: walk.chase, walker_shown: walk.walker.visible,
               camera_above_ground_m: round(p.y - terrain.surfaceAt(p.x, p.z)),
               camera_to_walker_m: round(p.distanceTo(w)),
               walker_feet_above_ground_m: round(w.y - 0.85 - terrain.surfaceAt(w.x, w.z), 6)};
  tap('KeyC');
  walk.update(1 / 60);
  out.chase.off_again = !walk.chase && !walk.walker.visible;
  out.eye = {min_m: round(eye.min), max_m: round(eye.max), max_off_1_7_at_true_scale_m: round(eye.max_off_true_scale_m, 6)};

  // Leave with Escape, then once more from the chase view with the Exit button.
  tap('Escape');
  const after1 = snapshot();
  walk.enter(); walk.setChase(true); key('KeyW', true); hold(1); key('KeyW', false); ui('wk-exit').click();
  const after2 = snapshot();
  const same = after => ({
    camera_moved_m: round(Math.hypot(...after.position.map((v, i) => v - before.position[i])), 9),
    camera_turned: round(Math.max(...after.quaternion.map((v, i) => Math.abs(v - before.quaternion[i]))), 9),
    rest_equal: ['fov', 'near', 'k', 'yaw', 'pitch', 'enabled', 'children', 'label', 'slider', 'bar', 'walking',
                 'route', 'photos', 'button'].every(k => after[k] === before[k])});
  out.after_exit = {escape: same(after1), exit_button: same(after2), relief_k: after2.k, fov_deg: after2.fov,
                    near_m: after2.near, scene: after2.children, listeners_left: walk._listeners.length};
  return out;
}

// ?check=layers : are the map layers of the 2D planner drawn on the right 1 m cells?
//
// For every layer of map_layers_model.js: pick it, read the image the 2D shows (the PNG as
// served, or the slope tiles put together) through a 2D canvas, and render the layer's
// group alone from straight above (orthographic, the box exactly on 2000 x 2000 pixels:
// one pixel a 1 m cell, north up), at full opacity with no blending so each texel is
// written as it is. The two are compared over black (a 2D canvas keeps colours
// premultiplied and rounds faint ones coarsely) on the cells inside the terrain mesh less
// one all round: share of cells within 3 levels, the errors, the shift that fits best
// (it must be 0, 0) and the error against the image flipped north-south (it must be
// clearly worse). The same at relief x5, which must not move the layer. Five named cells
// with both colours. Then the slope steeper than the plan's limit against the steep-cell
// layer, as masks: two different sources on the same cells. Then "Relief only", the photo
// view, and the terrain's own materials, untouched. It only GETs the images and the info
// JSON the 2D asks for. Everything is put back as it was.
async function layersCheck(viz) {
  const {terrain, scene, renderer, shadows, sunView, mapLayers: layers} = viz;
  const M = await import('./map_layers_model.js');
  const round = (v, d = 4) => (typeof v === 'number' && Number.isFinite(v) ? Number(v.toFixed(d)) : v ?? null);
  const wait = ms => new Promise(done => setTimeout(done, ms));       // not frames: a hidden page draws none
  const out = {check: 'layers', quality: terrain.quality, mesh_step_m: terrain.step};
  if (!layers) return {...out, error: 'map layers not loaded', note: document.getElementById('layer-note').textContent};
  const started = performance.now();
  const W = 2000, cell = terrain.size / W, bbox = terrain.meta.bbox;
  // The mesh's vertices run from `first` to first + (n - 1) step metres from the west and
  // north edges: the cells wholly inside it, less one all round.
  const lo = Math.ceil(terrain.first / cell) + 1;
  const hi = Math.floor((terrain.first + (terrain.n - 1) * terrain.step) / cell) - 1;
  const region = {i0: lo, j0: lo, i1: hi, j1: hi};
  Object.assign(out, {render_px: W, relief_k: terrain.k,
                      region: {...region, cells: (hi - lo) ** 2, rows_and_columns: `${lo} to ${hi - 1}, row 0 north`}});
  const before = {state: layers.state(), k: terrain.k, reliefOnly: sunView.reliefOnly,
                  children: scene.children.map(o => o.name || o.type).join(' ')};
  const terrainLook = () => terrain.materials.map(m => ({map: m.map, color: m.color.getHex()}));
  const look = terrainLook();

  const camera = new THREE.OrthographicCamera(-terrain.half, terrain.half, terrain.half, -terrain.half, 1, 20000);
  camera.position.set(0, 8000, 0);
  camera.up.set(0, 0, -1);                                 // north at the top of the image
  camera.lookAt(0, 0, 0);
  // The layer alone, its texels as they are; rows north first. The target is sRGB like the
  // texture: the shader works in linear and the GPU encodes the bytes back on writing.
  const topDown = () => {
    const m = layers.material, target = new THREE.WebGLRenderTarget(W, W, {colorSpace: THREE.SRGBColorSpace});
    const saved = {opacity: m.opacity, blending: m.blending, fog: scene.fog, background: scene.background,
                   clear: renderer.getClearColor(new THREE.Color()), alpha: renderer.getClearAlpha(), cast: shadows.enabled};
    const hidden = scene.children.filter(o => o !== layers.group && o.visible);
    try {
      hidden.forEach(o => { o.visible = false; });
      shadows.set(false);                                  // no shadow map drawn of a scene with no terrain
      scene.fog = null;
      scene.background = null;
      renderer.setClearColor(0x000000, 0);
      m.opacity = 1;
      m.blending = THREE.NoBlending;
      renderer.setRenderTarget(target);
      renderer.render(scene, camera);
      const rgba = new Uint8Array(W * W * 4);
      renderer.readRenderTargetPixels(target, 0, 0, W, W, rgba);     // rows from the south
      return M.flipRows(rgba, W, W);
    } finally {
      renderer.setRenderTarget(null);
      m.opacity = saved.opacity;
      m.blending = saved.blending;
      Object.assign(scene, {fog: saved.fog, background: saved.background});
      renderer.setClearColor(saved.clear, saved.alpha);
      hidden.forEach(o => { o.visible = true; });
      shadows.set(saved.cast);
      target.dispose();
    }
  };
  const shift = s => ({dx: s.dx, dy: s.dy, err: round(s.err), err_at_zero: round(s.err_at_zero)});
  const at = (rgba, row, col) => [...rgba.subarray((row * W + col) * 4, (row * W + col) * 4 + 4)];
  const sample = (name, row, col, png, drawn) => ({name, x: round(bbox.xmin + (col + 0.5) * cell, 2),
                                                  y: round(bbox.ymax - (row + 0.5) * cell, 2), cell: [row, col],
                                                  png: at(png, row, col), drawn: at(drawn, row, col)});
  const maskImage = mask => {                              // 0/1 mask -> grey RGBA, for bestShift
    const rgba = new Uint8Array(mask.length * 4);
    for (let c = 0; c < mask.length; c++) { rgba.fill(mask[c] * 255, c * 4, c * 4 + 3); rgba[c * 4 + 3] = 255; }
    return rgba;
  };
  const crop = mask => {                                   // the region of a W x W mask
    const part = new Uint8Array((hi - lo) ** 2);
    for (let i = lo; i < hi; i++) part.set(mask.subarray(i * W + lo, i * W + hi), (i - lo) * (hi - lo));
    return part;
  };

  out.layers = [];
  const masks = {};
  try {
    for (const layer of M.LAYERS) {
      try {
        const got = await layers.select(layer.id);
        if (got.error || !got.image) { out.layers.push({id: layer.id, error: got.error || 'nothing drawn'}); continue; }
        const src = await layers.imageData();
        if (src.w !== W || src.h !== W) { out.layers.push({id: layer.id, error: `image of ${src.w} x ${src.h} px`}); continue; }
        const drawnRaw = topDown();
        const expected = M.premultiply(src.rgba), drawn = M.premultiply(drawnRaw);
        const c = M.compareRGBA(expected, drawn, W, W, {tol: 3, region});
        const s = M.bestShift(expected, drawn, W, W, {max: 3, tol: 3, region});
        const flipped = M.compareRGBA(M.flipRows(expected, W, W), drawn, W, W, {tol: 3, region});
        viz.setRelief(5);
        const k5 = terrain.k, drawn5 = M.premultiply(topDown());
        viz.setRelief(before.k);
        const c5 = M.compareRGBA(expected, drawn5, W, W, {tol: 3, region});
        const s5 = M.bestShift(expected, drawn5, W, W, {max: 3, tol: 3, region});
        const [hx, hy] = layers.habitat;
        let first = null;
        for (let i = lo; i < hi && !first; i++) {
          for (let j = lo; j < hi; j++) if (src.rgba[(i * W + j) * 4 + 3] > 0) { first = [i, j]; break; }
        }
        const samples = [['box centre', W / 2, W / 2],
                         ['habitat', Math.floor((bbox.ymax - hy) / cell), Math.floor((hx - bbox.xmin) / cell)],
                         ['NW quarter', W / 4, W / 4], ['SE quarter', (3 * W) / 4, (3 * W) / 4]]
          .map(([name, row, col]) => sample(name, row, col, src.rgba, drawnRaw));
        samples.push(first ? sample('first painted cell of the region', ...first, src.rgba, drawnRaw)
                           : {name: 'first painted cell of the region', cell: null});
        out.layers.push({
          id: layer.id, label: layer.label, slider: layers.slider,
          match_pct: round(c.match_pct), mean_abs_err: round(c.mean_abs_err), max_abs_err: c.max_abs_err,
          best_shift: shift(s), mean_abs_err_flipped_ns: round(flipped.mean_abs_err),
          coverage_png: round(M.coverage(src.rgba, W, W, {region})), coverage_drawn: round(M.coverage(drawnRaw, W, W, {region})),
          relief_k5: k5, match_pct_k5: round(c5.match_pct), mean_abs_err_k5: round(c5.mean_abs_err), best_shift_k5: shift(s5),
          samples,
        });
        if (layer.id === 'slope' && Number.isFinite(layers.limit)) {
          masks.limit = layers.limit;
          masks.slope = M.slopeMask(src.rgba, W, W, layers.limit);
        }
        if (layer.id === 'steep') masks.steep = M.alphaMask(src.rgba, W, W);
      } catch (err) {
        console.error(err);
        out.layers.push({id: layer.id, error: err.message});
      }
    }

    // Two sources, one set of cells: the slope tiles steeper than the limit, against the
    // cells blocked.png draws. Both come from slope_deg.tif; cells just over the limit (up
    // to ~0.07° at 30°) are blocked but their 8-bit tile colour reads as the limit itself.
    if (masks.slope && masks.steep) {
      const a = M.maskAgreement(crop(masks.slope), crop(masks.steep));
      const s = M.bestShift(maskImage(masks.slope), maskImage(masks.steep), W, W, {max: 3, region});
      out.slope_vs_steep = {limit_deg: masks.limit, cells: a.cells, agree_pct: round(a.agree_pct),
                            only_slope_tiles: a.only_a, only_steep_png: a.only_b, both: a.both, best_shift: shift(s)};
    } else {
      out.slope_vs_steep = {error: 'the slope or the steep layer did not load (or the plan blocks no cell)'};
    }
    delete masks.slope; delete masks.steep;

    // Once, with a layer on: "Relief only" keeps it; the photo view hides it and gives it back.
    const shown = out.layers.filter(l => !l.error).map(l => l.id).at(-1);
    if (shown) {
      if (layers.current.id !== shown) await layers.select(shown);
      sunView.setReliefOnly(true);
      out.relief_only = {layer: shown, group_visible: layers.group.visible,
                         layer_map_kept: Boolean(layers.texture) && layers.material.map === layers.texture,
                         terrain_photo_hidden: terrain.materials.every(m => m.map === null)};
      sunView.setReliefOnly(before.reliefOnly);
      const inPhotoView = document.body.classList.contains('photo-view');
      document.body.classList.add('photo-view');
      await wait(50);
      const hiddenThere = !layers.group.visible;
      document.body.classList.remove('photo-view');
      await wait(50);
      out.photo_view = {layer: shown, hidden_in_photo_view: hiddenThere, shown_again_after: layers.group.visible};
      if (inPhotoView) document.body.classList.add('photo-view');
    }
    if (layers.layersMeta && layers.layersMeta.grid) {
      const g = layers.layersMeta.grid.bbox;
      out.layers_box_vs_terrain_box_m = round(Math.max(...['xmin', 'ymin', 'xmax', 'ymax'].map(key => Math.abs(g[key] - bbox[key]))), 6);
    }
  } finally {
    await layers.restore(before.state);
    if (terrain.k !== before.k) viz.setRelief(before.k);
    sunView.setReliefOnly(before.reliefOnly);
    viz.redraw();
  }
  const now = terrainLook(), after = layers.state();
  out.terrain_untouched = now.every((l, i) => l.map === look[i].map && l.color === look[i].color);
  const children = scene.children.map(o => o.name || o.type).join(' ');
  out.after_exit = {same: after.id === before.state.id && after.slider === before.state.slider && terrain.k === before.k &&
                          children === before.children,
                    state_before: before.state, state_after: after, relief_before: before.k, relief_after: terrain.k,
                    scene_children_same: children === before.children};
  out.seconds = round((performance.now() - started) / 1000, 1);
  return out;
}

export const CHECKS = {shading: shadingCheck, route: routeCheck, rehearse: rehearseCheck, sun: sunCheck,
                       shadows: shadowsCheck, guide: guideCheck, photos: photosCheck, stations: stationsCheck,
                       walk: walkCheck, layers: layersCheck};
