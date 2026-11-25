// View links of the 3D map (?view=). Run from the repo root:  node --test tests/viz3d/
import assert from 'node:assert/strict';
import { test } from 'node:test';

import * as M from '../../web/3d/camera_math.js';
import { formatView, parseView, viewLink } from '../../web/3d/view_link.js';

const DEG = Math.PI / 180;
const close = (a, b, tol) => assert.ok(Math.abs(a - b) <= tol, `${a} vs ${b}`);

test('a view is written as x,y,z,heading,pitch and read back', () => {
  const text = formatView({x: 8143537.492786, y: -286459.668204, z: -2145.861, heading: 0, pitch: 37});
  assert.equal(text, '8143537.49,-286459.67,-2145.86,0,37');
  assert.deepEqual(parseView(text), {x: 8143537.49, y: -286459.67, z: -2145.86, heading: 0, pitch: 37});
  assert.deepEqual(parseView(' 8143000 , -284000 , -3600.5 , 271.25 , 12.5 '),
                   {x: 8143000, y: -284000, z: -3600.5, heading: 271.25, pitch: 12.5});
});

test('the heading is written from 0 to 360 whatever the turns made', () => {
  const heading = text => parseView(text).heading;
  assert.equal(heading(formatView({x: 0, y: 0, z: 0, heading: -90, pitch: 30})), 270);
  assert.equal(heading(formatView({x: 0, y: 0, z: 0, heading: 725.5, pitch: 30})), 5.5);
  assert.equal(heading(formatView({x: 0, y: 0, z: 0, heading: 359.99996, pitch: 30})), 0);
  assert.equal(heading(formatView({x: 0, y: 0, z: 0, heading: -0.00001, pitch: 30})), 0);
});

test('what is not five numbers is not a view', () => {
  for (const text of [null, undefined, '', '1,2,3,4', '1,2,3,4,5,6', '1,2,3,4,', 'a,b,c,d,e', '1,2,3,4,north',
                      '1,2,,4,5', '1,2,3,Infinity,5']) {
    assert.equal(parseView(text), null, String(text));
  }
});

test('written and read back, a view is the same picture: centimetres and thousandths of a degree', () => {
  // A camera 2500 m from what it looks at: how far the centre of the picture moves.
  for (const [yaw, pitch] of [[0, 37], [123.4567, 12.3456], [301.1111, 88.8888], [-45.6789, 2.0004]]) {
    const position = [-812.7249, 2184.1361, 1343.9287];
    const view = parseView(formatView({x: 8143537.4928 + position[0], y: -284463.0752 - position[2], z: position[1] - 3638,
                                       heading: yaw, pitch}));
    close(view.x - 8143537.4928, position[0], 0.005);
    close(-284463.0752 - view.y, position[2], 0.005);
    close(view.z + 3638, position[1], 0.005);
    const before = M.basis(yaw * DEG, pitch * DEG).forward, after = M.basis(view.heading * DEG, view.pitch * DEG).forward;
    const angle = Math.acos(Math.min(1, M.dot(before, after))) / DEG;
    assert.ok(angle < 0.001, `the view turned ${angle} degrees`);
    assert.ok(2500 * angle * DEG < 0.05, 'under 5 cm at 2500 m');
  }
});

test('the link keeps the address, sets the view and what changes the picture, and never plans', () => {
  const base = 'http://localhost:8000/3d/';
  const link = viewLink(base, '?q=low&plan=default&check=route&spin=1&drag=pan&k=2',
                        {view: '8143537.49,-286459.67,-2145.86,0,37', k: 3.5, sol: 4711, lt: '15:00', shadows: 0});
  assert.equal(link, `${base}?q=low&drag=pan&k=3.5&view=8143537.49,-286459.67,-2145.86,0,37&sol=4711&lt=15:00&shadows=0`);
  const params = new URL(link).searchParams;
  assert.equal(params.get('plan'), null);          // plan=default would make the server replace the saved plan
  assert.equal(params.get('check'), null);
  assert.equal(params.get('spin'), null);
  assert.deepEqual(parseView(params.get('view')), {x: 8143537.49, y: -286459.67, z: -2145.86, heading: 0, pitch: 37});
  assert.equal(params.get('lt'), '15:00');
  // null takes a setting out (shadows on is the default); with nothing left there is no "?".
  assert.equal(viewLink(base, '?shadows=0', {view: '1,2,3,4,5', shadows: null}), `${base}?view=1,2,3,4,5`);
  assert.equal(viewLink(base, '?check=sun', {}), base);
  // Text that is not plain is still escaped.
  assert.equal(viewLink(base, '', {view: '1,2,3,4,5', note: 'a b&c'}), `${base}?view=1,2,3,4,5&note=a%20b%26c`);
});
