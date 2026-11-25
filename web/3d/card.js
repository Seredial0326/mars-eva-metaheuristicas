// Side card of the 3D map: one box for "what is this thing" (a station now; rover
// photos in a later block). No three import.
//
//   showCard({title, subtitle, rows, note, color, actions, media})
//     rows     [[label, value], ...]
//     color    [r, g, b] of the stripe beside the title (a station's type colour)
//     actions  [{label, onClick}, ...] buttons at the bottom
//     media    an element to show under the title (a photo), or nothing
//   hideCard()
// All text is set as text, never as HTML: ids and labels come from the server.
const root = () => document.getElementById('card');
let onHide = null;

function add(parent, tag, cls, text) {
  const node = document.createElement(tag);
  if (cls) node.className = cls;
  if (text != null) node.textContent = text;
  parent.append(node);
  return node;
}

export function showCard({title, subtitle = '', rows = [], note = '', color = null, actions = [], media = null,
                          onClose = null}) {
  const card = root(), replaced = onHide;
  onHide = null;
  if (replaced) replaced();                  // the card it takes the place of is gone
  card.replaceChildren();
  const close = add(card, 'button', 'card-close', '×');
  close.title = 'Close';
  close.setAttribute('aria-label', 'Close');
  close.addEventListener('click', hideCard);
  const head = add(card, 'div', 'card-title', title);
  if (color) head.style.borderLeftColor = `rgb(${color.join(',')})`;
  if (subtitle) add(card, 'div', 'muted', subtitle);
  if (media) add(card, 'div', 'card-media').append(media);
  if (rows.length) {
    const list = add(card, 'dl', 'card-rows');
    for (const [label, value] of rows) { add(list, 'dt', 'muted', label); add(list, 'dd', '', value); }
  }
  if (note) add(card, 'div', 'card-note muted', note);
  for (const action of actions) add(card, 'button', 'card-action', action.label).addEventListener('click', action.onClick);
  onHide = onClose;
  card.hidden = false;
  return card;
}

export function hideCard() {
  const card = root();
  if (card.hidden) return;
  card.hidden = true;
  card.replaceChildren();
  const done = onHide;
  onHide = null;
  if (done) done();
}

export const cardShown = () => !root().hidden;

// What the card says about a station. station: {id, type, score, serviceMin, order,
// visited} (any may be missing); rubric: the answer of GET /stations/rubric, whose type
// labels are the ones the 2D planner shows.
export function stationCard(station, rubric = {}) {
  const kind = rubric[station.type];
  const rows = [];
  if (station.score != null) rows.push(['Science score', String(station.score)]);
  if (station.serviceMin != null) rows.push(['Service time', `${station.serviceMin} min`]);
  if (station.order != null) rows.push(['Visit order', String(station.order)]);
  if (station.visited === false) rows.push(['In this plan', 'not visited']);
  return {title: station.id || 'Station', subtitle: kind ? kind.label : (station.type || ''), rows};
}
