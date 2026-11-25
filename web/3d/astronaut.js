// The astronaut of the 3D map (issue #109): the walker seen in the rehearsal's chase view
// and in "Walk freely", built from a few three.js primitives (no model, no texture).
//
//   - About 1.85 m to the top of the helmet; the visor centre at EYE_HEIGHT (1.7 m)
//     above the feet.
//   - Its origin is ANCHOR_HEIGHT above the feet, where the old capsule marker had its
//     centre: place it with position.set(X, ground + ANCHOR_HEIGHT, Z), and camera
//     distances to figure.position keep their meaning (checks.js).
//   - It faces -Z (north) at rotation.y = 0, its left side towards -X. poseAstronaut()
//     turns it to a heading and swings the legs and arms, which hang from pivot groups at
//     the hips and shoulders and turn around their X axis.
//   - White suit, grey boots and gloves, a life-support backpack on its back (+Z) and a
//     gold visor. Bands of the 2D planner's astronaut pink on the backpack and the upper
//     arms keep it easy to spot.
//   - Lit materials (they shade with the Sun) with a little emissive light of their own,
//     so the side in shadow, or the night, is never black. Like the capsule, no part
//     casts or receives shadows (the three.js default).
import * as THREE from 'three';
import { EYE_HEIGHT } from './rehearse_model.js';

export const ANCHOR_HEIGHT = EYE_HEIGHT / 2;       // m: the figure's origin above its feet

const SUIT = 0xeeeeea, GREY = 0x8a8e94, ACCENT = 0xff40c8;   // accent: the 2D planner's astronaut dot
const GOLD = 0xc8921a;
const GLOW = 0.15;                 // emissive share of each colour: the floor of its brightness
const HELMET = {y: 1.68, r: 0.17};                  // m above the feet: top at 1.85
const HIP = {x: 0.11, y: 0.92}, SHOULDER = {x: 0.28, y: 1.40};   // pivots, m above the feet
const LEG = 0.80, ARM = 0.62;      // m from the pivot to the bottom of the leg / the glove centre
const ARM_SWING = 0.7;             // arm swing per unit of leg swing, the other way round
const VISOR_HALF = 0.9;            // rad: half the visor's width around the helmet

function lit(color, glow = GLOW) {
  return new THREE.MeshLambertMaterial({color, emissive: color, emissiveIntensity: glow});
}

// A mesh at (x, y, z) inside parent.
function part(parent, geometry, material, x, y, z) {
  const mesh = new THREE.Mesh(geometry, material);
  mesh.position.set(x, y, z);
  parent.add(mesh);
  return mesh;
}

// A group the limb hangs from, at (x, y, 0) inside parent.
function pivot(parent, name, x, y) {
  const group = new THREE.Group();
  group.name = name;
  group.position.set(x, y, 0);
  parent.add(group);
  return group;
}

// A new astronaut, standing straight and facing north: a Group named 'walker' whose
// userData holds the swing pivots, {legs: [left, right], arms: [left, right]}.
export function createAstronaut() {
  const suit = lit(SUIT), grey = lit(GREY), accent = lit(ACCENT, 0.35);
  const visor = new THREE.MeshPhongMaterial({color: GOLD, specular: 0xfff0c0, shininess: 90,
                                             emissive: 0x4a3008});     // glossy gold, dim in shade
  const figure = new THREE.Group();
  figure.name = 'walker';
  const body = new THREE.Group();                  // the feet at y = 0 inside it
  body.name = 'walker-body';
  body.position.y = -ANCHOR_HEIGHT;
  figure.add(body);

  // Torso, hips, neck ring, and the backpack with its pink band.
  part(body, new THREE.BoxGeometry(0.42, 0.52, 0.28), suit, 0, 1.18, 0);
  part(body, new THREE.BoxGeometry(0.36, 0.18, 0.24), suit, 0, 0.92, 0);
  part(body, new THREE.CylinderGeometry(0.13, 0.15, 0.08, 16), grey, 0, 1.47, 0);
  part(body, new THREE.BoxGeometry(0.40, 0.52, 0.18), suit, 0, 1.20, 0.23);
  part(body, new THREE.BoxGeometry(0.42, 0.05, 0.19), accent, 0, 1.36, 0.23);

  // Helmet, and the visor: a slice of a slightly larger sphere on its front (-Z),
  // centred at eye height.
  part(body, new THREE.SphereGeometry(HELMET.r, 16, 12), suit, 0, HELMET.y, 0);
  part(body, new THREE.SphereGeometry(HELMET.r * 1.035, 12, 6, 1.5 * Math.PI - VISOR_HALF, 2 * VISOR_HALF,
                                      0.30 * Math.PI, 0.32 * Math.PI), visor, 0, HELMET.y, 0);

  // Legs and arms, one geometry of each part shared by both sides.
  const leg = new THREE.CapsuleGeometry(0.085, LEG - 0.17, 4, 12);
  const boot = new THREE.BoxGeometry(0.15, 0.13, 0.27);
  const shoulder = new THREE.SphereGeometry(0.085, 12, 8);
  const arm = new THREE.CapsuleGeometry(0.065, ARM - 0.13, 4, 12);
  const band = new THREE.CylinderGeometry(0.072, 0.072, 0.045, 12);
  const glove = new THREE.SphereGeometry(0.075, 12, 8);
  const legs = [], arms = [];
  for (const [side, name] of [[-1, 'left'], [1, 'right']]) {
    const hip = pivot(body, `${name}-leg`, side * HIP.x, HIP.y);
    part(hip, leg, suit, 0, -LEG / 2, 0);
    part(hip, boot, grey, 0, 0.065 - HIP.y, -0.03);           // sole on the ground, toe forward
    legs.push(hip);
    const joint = pivot(body, `${name}-arm`, side * SHOULDER.x, SHOULDER.y);
    part(joint, shoulder, suit, 0, 0, 0);
    part(joint, arm, suit, 0, -ARM / 2, 0);
    part(joint, band, accent, 0, -0.14, 0);
    part(joint, glove, grey, 0, -ARM, 0);
    arms.push(joint);
  }
  figure.userData = {legs, arms};
  return figure;
}

// Turn the figure to face `yaw` (radians from north towards east: north is -Z, east +X)
// and swing it: the left leg forward by `swing` radians and the right one back, the arms
// the other way round by ARM_SWING times as much. swing = 0 is standing straight.
export function poseAstronaut(figure, {yaw = 0, swing = 0} = {}) {
  figure.rotation.y = -yaw;          // rotation.y turns -Z towards -X: the opposite of the heading
  const [leftLeg, rightLeg] = figure.userData.legs, [leftArm, rightArm] = figure.userData.arms;
  leftLeg.rotation.x = swing;        // a positive turn around X brings the foot to -Z: forward
  rightLeg.rotation.x = -swing;
  leftArm.rotation.x = -ARM_SWING * swing;
  rightArm.rotation.x = ARM_SWING * swing;
  return figure;
}

// Take the figure out of the scene and free its geometries and materials. Safe to call
// again on the same figure, or with null.
export function disposeAstronaut(figure) {
  if (!figure) return;
  figure.removeFromParent();
  figure.traverse(object => {
    if (!object.isMesh) return;
    object.geometry.dispose();
    object.material.dispose();
  });
}
