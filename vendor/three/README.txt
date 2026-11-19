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

Added for light-show-3d.html (glow on the LED strips):

  postprocessing/{EffectComposer,RenderPass,UnrealBloomPass,OutputPass,
                  ShaderPass,MaskPass,Pass}.js   examples/jsm/postprocessing/
  shaders/{CopyShader,LuminosityHighPassShader,OutputShader}.js
                                                 examples/jsm/shaders/

These are the one exception to "nothing modified": their `from 'three'` was
changed to `from '../three.module.js'`, same as the loaders, so no import map
is needed (see the note in room-walk.html).
