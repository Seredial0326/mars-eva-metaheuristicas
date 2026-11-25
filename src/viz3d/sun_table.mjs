// Table of the Sun through one sol at a site, as JSON on standard output (P1, block 4).
//
// The Mars24 algorithm of the 3D map exists only in JavaScript (web/3d/mars_sun.js), so
// the paper figure and the numbers of paper/notes/P1_3d_map.md are made from this same
// code instead of a second implementation in Python. src/viz3d/paper_figures.py runs:
//     node src/viz3d/sun_table.mjs --sol 4711 --x 8143537.49 --y -284463.08 [--step-min 10]
// x, y: the site in metres of the project's CRS (the centre of the study box).
import { mslClock } from '../../web/3d/mars_sun.js';
import { clockText, siteFromCrs, sunState } from '../../web/3d/sun_model.js';

const args = Object.fromEntries(process.argv.slice(2).join(' ').split('--').filter(Boolean)
  .map(pair => pair.trim().split(/\s+/)).map(([key, value]) => [key, Number(value)]));
for (const key of ['sol', 'x', 'y']) {
  if (!Number.isFinite(args[key])) {
    console.error('usage: node src/viz3d/sun_table.mjs --sol <n> --x <m> --y <m> [--step-min <minutes>]');
    process.exit(2);
  }
}
const stepMin = args['step-min'] || 10;
const site = siteFromCrs(args.x, args.y);
const round = (v, d) => Number(v.toFixed(d));

function row(hours) {
  const s = sunState({sol: args.sol, hours}, site), mission = mslClock(s.utcMs);
  return {local_true_solar_time: clockText(hours), hours: round(hours, 4), utc: new Date(s.utcMs).toISOString(),
          elevation_deg: round(s.elevation, 3), azimuth_deg: round(s.azimuth, 3), hour_angle_deg: round(s.hourAngle, 3),
          ls_deg: round(s.ls, 3), equation_of_time_min: round(s.eot * 4, 2),
          mission_sol: mission.sol, mission_lmst: clockText(mission.lmst),
          sun_light: round(s.sun, 3), sky_light: round(s.sky, 3)};
}

const rows = [];
for (let minutes = 0; minutes <= 1440; minutes += stepMin) rows.push(row(Math.min(minutes, 1439.999) / 60));
// Sunrise and sunset of a smooth planet: where the elevation changes sign, to the second.
const crossings = [];
for (let i = 1; i < rows.length; i++) {
  if (rows[i - 1].elevation_deg < 0 === rows[i].elevation_deg < 0) continue;
  let a = rows[i - 1].hours, b = rows[i].hours;
  const rising = rows[i].elevation_deg > 0;
  for (let n = 0; n < 40; n++) {
    const mid = (a + b) / 2;
    if (sunState({sol: args.sol, hours: mid}, site).elevation > 0 === rising) b = mid; else a = mid;
  }
  crossings.push({what: rising ? 'sunrise' : 'sunset', ...row((a + b) / 2)});
}

console.log(JSON.stringify({
  made_by: 'src/viz3d/sun_table.mjs (web/3d/mars_sun.js: Mars24 algorithm, Allison and McEwen 2000)',
  sol: args.sol, step_min: stepMin,
  site: {x_m: args.x, y_m: args.y, lon_east_deg: round(site.lonEastDeg, 5),
         lat_planetocentric_deg: round(site.latCentricDeg, 5), lat_planetographic_deg: round(site.latDeg, 5)},
  key_times: [7, 12, 15, 17].map(row), crossings, rows,
}, null, 1));
