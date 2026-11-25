// Where the Sun is in the sky of Mars, and what time it is there (P1, issue #42, block 4).
//
// The Mars24 algorithm of Allison and McEwen (2000), written from the equation list of
// https://www.giss.nasa.gov/tools/mars24/help/algorithm.html (equation numbers A-1 ... D-6
// below are the ones of that page). No dependencies: tested in Node
// (tests/viz3d/mars_sun.test.mjs) against the page's two worked examples and against
// the local times that Curiosity's own image index gives.
//
// Conventions of THIS file (they differ from the page, which is west-positive):
//   - instants are UTC milliseconds since 1970 (Date.getTime());
//   - longitudes are degrees EAST, as the project's CRS gives them; they are turned
//     into degrees west only inside the equations;
//   - latitudes given to sunPosition() are planetographic, as in Mars24
//     (planetographicLatitude() converts the CRS's planetocentric ones);
//   - azimuth is the compass bearing of the Sun: from north, clockwise through east;
//   - angles in degrees, clock times in hours (0 to 24).
// Not modelled: refraction, the size of the solar disc, the local horizon (terrain).

const DEG = Math.PI / 180;
const sind = a => Math.sin(a * DEG), cosd = a => Math.cos(a * DEG);
const mod = (a, n) => ((a % n) + n) % n;

export const SOL_IN_DAYS = 1.0274912517;        // mean solar day of Mars in Earth days (C-2)
export const SOL_IN_SECONDS = SOL_IN_DAYS * 86400;
const MARS_FLATTENING = 1 - 3376.2 / 3396.19;   // polar and equatorial radius, IAU 2000

// Curiosity's mission clock: local mean solar time at 137.42 E, the landing site as it
// was planned (not where the rover is), with sol 0 the sol of landing (2012-08-06 UTC).
export const MSL_CLOCK_LON_EAST = 137.42;
export const MSL_SOL0_MSD = 49269;

// TT - UTC in seconds: 32.184 s plus the leap seconds (TAI - UTC) in force at the
// instant (A-4). Only the steps since 1999 are listed, enough for the worked examples
// (2000, 2004: 64.184 s) and for the whole Curiosity mission; none was added after
// 2017 as of this writing (69.184 s). Pass {ttMinusUtc} to the functions to override.
const LEAP_STEPS = [['1999-01-01', 32], ['2006-01-01', 33], ['2009-01-01', 34], ['2012-07-01', 35],
                    ['2015-07-01', 36], ['2017-01-01', 37]].map(([day, s]) => [Date.parse(`${day}T00:00:00Z`), s]);

export function ttMinusUtc(utcMs) {
  let leap = LEAP_STEPS[0][1];                  // before 1999: wrong by up to 22 s, never used here
  for (const [from, s] of LEAP_STEPS) if (utcMs >= from) leap = s;
  return 32.184 + leap;
}

// The seven largest planetary perturbations of the Sun's longitude seen from Mars (B-3):
// amplitude (deg), period (years), phase (deg).
const PERTURBERS = [[0.0071, 2.2353, 49.409], [0.0057, 2.7543, 168.173], [0.0039, 1.1177, 191.837],
                    [0.0037, 15.7866, 21.736], [0.0021, 2.1354, 15.704], [0.0020, 2.4694, 95.528],
                    [0.0018, 32.8493, 49.095]];

// Mars time quantities of an instant, the same for the whole planet.
//   ls            areocentric solar longitude (season): 0 northern spring equinox, 90 solstice...
//   eot           equation of time in degrees (true minus mean solar time; 15 degrees = 1 h)
//   msd, mtc      Mars Sol Date (days) and Coordinated Mars Time (hours at longitude 0)
//   subsolarLonEast, declination   where the Sun is overhead (planetographic)
export function marsTime(utcMs, {ttMinusUtc: tt = ttMinusUtc(utcMs)} = {}) {
  // A-2, A-5, A-6 in one step: days since J2000 (JD 2451545.0 = day 10957.5 of 1970) in TT.
  const dt = utcMs / 86400000 - 10957.5 + tt / 86400;
  const M = 19.3871 + 0.52402073 * dt;                                        // B-1 mean anomaly
  const alphaFMS = 270.3871 + 0.524038496 * dt;                               // B-2 fictitious mean sun
  let pbs = 0;                                                                // B-3
  for (const [A, tau, phi] of PERTURBERS) pbs += A * cosd(0.985626 * dt / tau + phi);
  const nuMinusM = (10.691 + 3.0e-7 * dt) * sind(M) + 0.623 * sind(2 * M) + 0.050 * sind(3 * M) +
                   0.005 * sind(4 * M) + 0.0005 * sind(5 * M) + pbs;           // B-4 equation of centre
  const ls = mod(alphaFMS + nuMinusM, 360);                                   // B-5
  const eot = 2.861 * sind(2 * ls) - 0.071 * sind(4 * ls) + 0.002 * sind(6 * ls) - nuMinusM;    // C-1
  const msd = (dt - 4.5) / SOL_IN_DAYS + 44796.0 - 0.0009626;                 // C-2 (JD_TT - 2451549.5 = dt - 4.5)
  const mtc = mod(msd, 1) * 24;
  const subsolarLonWest = mod(mtc * 15 + eot + 180, 360);                     // C-5
  const declination = Math.asin(0.42565 * sind(ls)) / DEG + 0.25 * sind(ls);  // D-1
  const distanceAu = 1.52367934 * (1.00436 - 0.09309 * cosd(M) - 0.004336 * cosd(2 * M) -
                                   0.00031 * cosd(3 * M) - 0.00003 * cosd(4 * M));               // D-2
  const helioLon = mod(ls + 85.061 - 0.015 * sind(71 + 2 * ls) - 5.5e-6 * dt, 360);              // D-3
  const helioLat = -(1.8497 - 2.23e-5 * dt) * sind(ls - 144.50 + 2.57e-6 * dt);                  // D-4
  return {dtJ2000: dt, ttMinusUtc: tt, meanAnomaly: mod(M, 360), alphaFMS: mod(alphaFMS, 360), pbs, nuMinusM,
          ls, eot, msd, mtc, subsolarLonWest, subsolarLonEast: mod(-subsolarLonWest, 360), declination,
          distanceAu, helioLon, helioLat};
}

// Local mean (C-3) and local true (C-4) solar time, in hours, at a longitude east.
export function localMeanSolarTime(utcMs, lonEastDeg, opts) {
  return mod(marsTime(utcMs, opts).mtc + lonEastDeg / 15, 24);
}

export function localTrueSolarTime(utcMs, lonEastDeg, opts) {
  const t = marsTime(utcMs, opts);
  return mod(t.mtc + lonEastDeg / 15 + t.eot / 15, 24);
}

// Planetographic latitude (the one of a map's "up", used by Mars24) from the
// planetocentric latitude of the project's CRS. They differ by at most 0.34 degrees
// (at 45 degrees) and by 0.06 degrees at the study box.
export function planetographicLatitude(planetocentricDeg) {
  if (Math.abs(planetocentricDeg) >= 90) return Math.sign(planetocentricDeg) * 90;
  return Math.atan(Math.tan(planetocentricDeg * DEG) / (1 - MARS_FLATTENING) ** 2) / DEG;
}

// The Sun seen from a site at an instant. latDeg planetographic, lonEastDeg east.
//   elevation   degrees above the horizon of a smooth planet (negative: night)
//   azimuth     compass bearing of the Sun, degrees from north through east
//   hourAngle   degrees, 0 at local true noon, positive in the afternoon
// plus the local times (hours) and everything marsTime() gives.
export function sunPosition(utcMs, {latDeg, lonEastDeg}, opts) {
  const t = marsTime(utcMs, opts);
  const H = mod(-lonEastDeg, 360) - t.subsolarLonWest;         // D-5: site minus subsolar longitude, both WEST
  const cosZ = sind(t.declination) * sind(latDeg) + cosd(t.declination) * cosd(latDeg) * cosd(H);
  const zenith = Math.acos(Math.min(1, Math.max(-1, cosZ))) / DEG;
  // D-6 with atan2, so the quadrant is right. H grows to the west of the Sun, which is
  // why this is a bearing through east although it looks like the usual formula mirrored.
  const azimuth = mod(Math.atan2(sind(H), cosd(latDeg) * Math.tan(t.declination * DEG) - sind(latDeg) * cosd(H)) / DEG, 360);
  const lmst = mod(t.mtc + lonEastDeg / 15, 24);
  return {...t, zenith, elevation: 90 - zenith, azimuth, hourAngle: mod(-H + 180, 360) - 180,
          lmst, ltst: mod(lmst + t.eot / 15, 24)};
}

// ---- Curiosity's mission clock ---------------------------------------------------

// Mission sol and local mean solar time as the mission writes them (e.g. the "lmst"
// field of the raw image index, Sol-04450M08:30:55.289).
export function mslClock(utcMs, opts) {
  const date = marsTime(utcMs, opts).msd + MSL_CLOCK_LON_EAST / 360 - MSL_SOL0_MSD;
  const sol = Math.floor(date);
  return {sol, lmst: (date - sol) * 24, solDate: date};
}

// UTC instant (ms) of a mission sol and mission LMST in hours: mslClock() backwards.
export function utcOfMslClock(sol, lmstHours = 0, {ttMinusUtc: tt} = {}) {
  const msd = sol + lmstHours / 24 + MSL_SOL0_MSD - MSL_CLOCK_LON_EAST / 360;
  const toUtc = seconds => (((msd - 44796.0 + 0.0009626) * SOL_IN_DAYS + 4.5) - seconds / 86400 + 10957.5) * 86400000;
  if (tt !== undefined) return toUtc(tt);
  const first = toUtc(69.184);
  return toUtc(ttMinusUtc(first));              // the leap seconds of that date, read at a close guess
}

// ---- true solar days at a site ---------------------------------------------------

// A day count that follows the Sun at a longitude: its whole part is the sol (numbered
// like Curiosity's) and its fraction times 24 is the local TRUE solar time there, so it
// runs without a jump through midnight. Because true and mean time differ by the
// equation of time (up to 51 min), the number changes up to 51 min before or after the
// mission's own sol number does; away from midnight they are the same sol.
export function trueSolarDate(utcMs, lonEastDeg, opts) {
  const t = marsTime(utcMs, opts);
  return t.msd + lonEastDeg / 360 + t.eot / 360 - MSL_SOL0_MSD;
}

// The inverse the page needs: UTC instant (ms) at which, at a longitude, it is the
// given local true solar time (hours) of the given sol. Newton steps on
// trueSolarDate(), whose rate is one per sol to within 2e-4 (the equation of time
// drifts by a minute per sol at most): three steps reach well under a millisecond.
export function utcOfTrueSolarTime(sol, ltstHours, lonEastDeg, opts) {
  const target = sol + ltstHours / 24;
  let utc = utcOfMslClock(sol, ltstHours, opts);
  for (let i = 0; i < 4; i++) utc += (target - trueSolarDate(utc, lonEastDeg, opts)) * SOL_IN_SECONDS * 1000;
  return utc;
}
