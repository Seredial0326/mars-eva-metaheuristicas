# Vendored libraries for the 3D map

Copied into the repo so the 3D page works with no internet access (demo rule).
Do not edit these files; to update, replace them from the same npm package.

| Library | Version | Licence | Source |
|---|---|---|---|
| three.js | 0.187.0 (r187) | MIT (`three/LICENSE`) | `https://registry.npmjs.org/three/-/three-0.187.0.tgz` |

npm integrity of the tarball:
`sha512-Qiu7R+Cmh8CstZsY1uJOSWnVlfo7ZtNLV7mF8Jltk3LB3AtDu9cRZlcnRKkAk8Y4z6KKw35z7Y7Urd7jWY8etA==`

Only the files the page imports were kept, with their original paths:

- `three/build/three.module.js`, `three/build/three.core.js`
- `three/examples/jsm/lines/Line2.js`, `LineSegments2.js`, `LineGeometry.js`,
  `LineSegmentsGeometry.js`, `LineMaterial.js`

`web/3d/index.html` maps `three` and `three/addons/` to these folders with an import map.
