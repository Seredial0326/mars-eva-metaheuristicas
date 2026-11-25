// A free-flight view as text, with no dependencies (tested with `node --test`).
//
// ?view=x,y,z,heading,pitch places the camera of the 3D map exactly:
//   x, y     Mars CRS metres (x east, y north), written to the centimetre
//   z        elevation of the camera in metres on the DEM datum (not a height above the
//            ground: the shown ground moves with the relief slider, the camera does not)
//   heading  degrees from north towards east, 0 to 360
//   pitch    degrees below the horizon (37 looks down 37 degrees)
// Example: ?view=8143537.49,-286459.66,-2146.25,0,37 is the opening view.
// The page still applies the free-flight limits when it places the camera (at least 2 m
// above the shown ground, pitch between 2 and 89.5 degrees), so a link made by the page
// comes back as it was made.

const round = (v, digits) => Number(v.toFixed(digits));

// {x, y, z, heading, pitch} (heading and pitch in degrees) -> "x,y,z,heading,pitch".
export function formatView({x, y, z, heading, pitch}) {
  const turn = ((heading % 360) + 360) % 360;
  return [round(x, 2), round(y, 2), round(z, 2), round(turn, 3) % 360, round(pitch, 3)].join(',');
}

// "x,y,z,heading,pitch" -> {x, y, z, heading, pitch}, or null when it is not five numbers.
export function parseView(text) {
  const parts = String(text ?? '').split(',');
  if (parts.length !== 5 || parts.some(p => p.trim() === '')) return null;
  const [x, y, z, heading, pitch] = parts.map(Number);
  return [x, y, z, heading, pitch].every(Number.isFinite) ? {x, y, z, heading, pitch} : null;
}

// The address that opens the page as it is now: the current query string with the view
// and the settings that change the picture put in (`set`: {name: value}; null or
// undefined removes the name). Parameters that must not travel with a link are dropped:
// check and spin (not a view), and plan (plan=default makes the server plan and replace
// the saved plan). Commas and colons stay readable.
export function viewLink(base, search, set) {
  const params = new URLSearchParams(search);
  for (const name of ['check', 'spin', 'plan']) params.delete(name);
  for (const [name, value] of Object.entries(set)) {
    if (value === null || value === undefined) params.delete(name); else params.set(name, String(value));
  }
  const query = [...params].map(([name, value]) =>
    `${encodeURIComponent(name)}=${encodeURIComponent(value).replace(/%2C/g, ',').replace(/%3A/g, ':')}`).join('&');
  return query ? `${base}?${query}` : base;
}
