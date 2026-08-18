three.js r160 — vendored, not a build step
==========================================

Copied straight out of the npm package `three@0.160.0` (MIT licence, see
https://github.com/mrdoob/three.js). Nothing here is modified.

  three.module.js                 build/three.module.js
  loaders/GLTFLoader.js           examples/jsm/loaders/GLTFLoader.js
  utils/BufferGeometryUtils.js    examples/jsm/utils/BufferGeometryUtils.js   (GLTFLoader imports it)
  libs/meshopt_decoder.module.js  examples/jsm/libs/meshopt_decoder.module.js (models/*.glb are meshopt-compressed)

Why vendored rather than a CDN: the page then has no third-party dependency
to go down, get blocked, or change under it, and it keeps working offline.
The paths matter — GLTFLoader does `import '../utils/BufferGeometryUtils.js'`,
so loaders/ and utils/ must stay siblings.

Used by: room-walk.html
